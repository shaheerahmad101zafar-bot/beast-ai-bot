"""
Beast AI — Sub-Millisecond HFT Scalper

Ultra-fast paper/live micro-scalp loop targeting 0.2%–0.8% bursts with
trailing micro take-profit and async multi-worker order dispatch.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import config

logger = logging.getLogger("beast.hft")

SCALP_TP_MIN = 0.002  # 0.2%
SCALP_TP_MAX = 0.008  # 0.8%
SCALP_SL = 0.0015  # 0.15% hard stop
TRAIL_ARM_PCT = 0.0012  # arm trailing after +0.12%
TRAIL_GIVEBACK = 0.0006  # give back 0.06% from peak
MAX_HOLD_SECONDS = 12.0
SPIKE_VOLUME_MULT = 1.8


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ScalpPosition:
    symbol: str
    side: str  # LONG | SHORT
    entry: float
    size: float
    opened_at: float
    peak_pnl_pct: float = 0.0
    trail_armed: bool = False
    target_tp: float = SCALP_TP_MIN
    meta: dict[str, Any] = field(default_factory=dict)


class HFTScalper:
    """
    High-frequency micro-scalp executor.

    Uses a dedicated thread pool for order placement to keep the WS loop
    non-blocking (sub-millisecond dispatch path in paper mode).
    """

    def __init__(
        self,
        execution_engine: Any | None = None,
        workers: int = 4,
    ) -> None:
        self.execution = execution_engine
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hft")
        self._lock = threading.RLock()
        self._enabled = False
        self._positions: dict[str, ScalpPosition] = {}
        self._last_ticks: dict[str, dict[str, Any]] = {}
        self._volume_ema: dict[str, float] = {}
        self._audit: list[dict[str, Any]] = []
        self._stats = {
            "signals": 0,
            "entries": 0,
            "exits": 0,
            "realized_pnl": 0.0,
            "avg_hold_ms": 0.0,
            "last_latency_ms": 0.0,
        }

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool) -> dict[str, Any]:
        with self._lock:
            self._enabled = bool(on)
            return {"ok": True, "enabled": self._enabled}

    def ingest_tick(
        self,
        symbol: str,
        price: float,
        *,
        bid: float | None = None,
        ask: float | None = None,
        volume: float | None = None,
        ts: float | None = None,
    ) -> list[dict[str, Any]]:
        """Feed a market tick; returns any exit/entry events produced."""
        if price <= 0:
            return []
        now = ts or time.perf_counter()
        events: list[dict[str, Any]] = []
        with self._lock:
            prev = self._last_ticks.get(symbol) or {}
            self._last_ticks[symbol] = {
                "price": price,
                "bid": bid,
                "ask": ask,
                "volume": volume or 0.0,
                "ts": now,
            }
            if volume is not None and volume > 0:
                ema = self._volume_ema.get(symbol, volume)
                self._volume_ema[symbol] = ema * 0.85 + volume * 0.15

            # Manage open scalp
            pos = self._positions.get(symbol)
            if pos:
                exit_evt = self._manage_position(pos, price, now)
                if exit_evt:
                    events.append(exit_evt)

            if self._enabled and symbol not in self._positions:
                entry = self._maybe_enter(symbol, price, prev, volume, now)
                if entry:
                    events.append(entry)
        return events

    def _maybe_enter(
        self,
        symbol: str,
        price: float,
        prev: dict[str, Any],
        volume: float | None,
        now: float,
    ) -> dict[str, Any] | None:
        prev_price = float(prev.get("price") or 0)
        if prev_price <= 0:
            return None
        move = (price - prev_price) / prev_price
        vol_ema = self._volume_ema.get(symbol, volume or 0)
        spike = bool(volume and vol_ema and volume >= vol_ema * SPIKE_VOLUME_MULT)

        # Burst detector: sharp move + volume spike
        if abs(move) < 0.0008 and not spike:
            return None
        if abs(move) < 0.0004:
            return None

        side = "LONG" if move > 0 else "SHORT"
        burst = min(SCALP_TP_MAX, max(SCALP_TP_MIN, abs(move) * 2.5))
        t0 = time.perf_counter()
        size = self._size_for(price)
        pos = ScalpPosition(
            symbol=symbol,
            side=side,
            entry=price,
            size=size,
            opened_at=now,
            target_tp=burst,
            meta={"move": round(move, 6), "spike": spike},
        )
        self._positions[symbol] = pos
        self._stats["signals"] += 1
        self._stats["entries"] += 1
        latency_ms = (time.perf_counter() - t0) * 1000.0
        self._stats["last_latency_ms"] = round(latency_ms, 4)

        # Async order dispatch (paper fill is near-instant)
        self._pool.submit(self._dispatch_entry, pos)

        evt = {
            "type": "hft_entry",
            "symbol": symbol,
            "side": side,
            "price": price,
            "size": size,
            "target_tp_pct": round(burst * 100, 3),
            "latency_ms": round(latency_ms, 4),
            "ts": _utc_iso(),
        }
        self._push_audit(evt)
        return evt

    def _manage_position(self, pos: ScalpPosition, price: float, now: float) -> dict[str, Any] | None:
        if pos.side == "LONG":
            pnl_pct = (price - pos.entry) / pos.entry
        else:
            pnl_pct = (pos.entry - price) / pos.entry

        pos.peak_pnl_pct = max(pos.peak_pnl_pct, pnl_pct)
        if pnl_pct >= TRAIL_ARM_PCT:
            pos.trail_armed = True

        reason = None
        if pnl_pct <= -SCALP_SL:
            reason = "hard_sl"
        elif pnl_pct >= pos.target_tp:
            reason = "micro_tp"
        elif pos.trail_armed and pnl_pct <= pos.peak_pnl_pct - TRAIL_GIVEBACK:
            reason = "trail_tp"
        elif (now - pos.opened_at) >= MAX_HOLD_SECONDS:
            reason = "max_hold"

        if not reason:
            return None

        hold_ms = (now - pos.opened_at) * 1000.0
        self._positions.pop(pos.symbol, None)
        self._stats["exits"] += 1
        self._stats["realized_pnl"] += pnl_pct * pos.size * pos.entry
        n = max(1, self._stats["exits"])
        self._stats["avg_hold_ms"] = (
            self._stats["avg_hold_ms"] * (n - 1) + hold_ms
        ) / n

        self._pool.submit(self._dispatch_exit, pos, price, reason, pnl_pct)

        evt = {
            "type": "hft_exit",
            "symbol": pos.symbol,
            "side": pos.side,
            "entry": pos.entry,
            "exit": price,
            "pnl_pct": round(pnl_pct * 100, 4),
            "reason": reason,
            "hold_ms": round(hold_ms, 2),
            "peak_pnl_pct": round(pos.peak_pnl_pct * 100, 4),
            "ts": _utc_iso(),
        }
        self._push_audit(evt)
        return evt

    def _size_for(self, price: float) -> float:
        # Tiny notional for micro-scalps (~1% of default paper equity)
        notional = 10.0
        return round(notional / max(price, 1e-9), 8)

    def _dispatch_entry(self, pos: ScalpPosition) -> None:
        if not self.execution:
            return
        try:
            signal = "BUY" if pos.side == "LONG" else "SELL"
            sl = pos.entry * (1 - SCALP_SL) if pos.side == "LONG" else pos.entry * (1 + SCALP_SL)
            tp = (
                pos.entry * (1 + pos.target_tp)
                if pos.side == "LONG"
                else pos.entry * (1 - pos.target_tp)
            )
            self.execution.place_order(
                symbol=pos.symbol,
                signal=signal,
                size_units=pos.size,
                leverage=5.0,
                market_price=pos.entry,
                stop_loss=sl,
                take_profit=tp,
                metadata={"ai_reasoning": "HFT micro-burst entry: volume spike + momentum scalp setup."},
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("HFT entry dispatch failed: %s", exc)

    def _dispatch_exit(
        self,
        pos: ScalpPosition,
        price: float,
        reason: str,
        pnl_pct: float,
    ) -> None:
        if not self.execution:
            return
        try:
            # Opposing signal closes paper position via existing engine path
            signal = "SELL" if pos.side == "LONG" else "BUY"
            if hasattr(self.execution, "close_position"):
                self.execution.close_position(pos.symbol, market_price=price, exit_reason=reason)
            else:
                self.execution.place_order(
                    symbol=pos.symbol,
                    signal=signal,
                    size_units=pos.size,
                    leverage=5.0,
                    market_price=price,
                    stop_loss=price,
                    take_profit=price,
                    metadata={"ai_reasoning": f"HFT opposing exit: {reason}"},
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("HFT exit note: %s pnl=%.4f%%", exc, pnl_pct * 100)

    def _push_audit(self, evt: dict[str, Any]) -> None:
        self._audit.append(evt)
        self._audit = self._audit[-120:]

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self._enabled,
                "open_scalps": [
                    {
                        "symbol": p.symbol,
                        "side": p.side,
                        "entry": p.entry,
                        "target_tp_pct": round(p.target_tp * 100, 3),
                        "trail_armed": p.trail_armed,
                        "peak_pnl_pct": round(p.peak_pnl_pct * 100, 4),
                    }
                    for p in self._positions.values()
                ],
                "stats": dict(self._stats),
                "audit": list(self._audit[-20:]),
                "targets": {
                    "tp_min_pct": SCALP_TP_MIN * 100,
                    "tp_max_pct": SCALP_TP_MAX * 100,
                    "sl_pct": SCALP_SL * 100,
                    "max_hold_s": MAX_HOLD_SECONDS,
                },
            }

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


hft_scalper = HFTScalper()
