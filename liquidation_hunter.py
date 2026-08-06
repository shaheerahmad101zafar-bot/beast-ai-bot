"""
Liquidation cascade hunter for Binance futures force-order stream.
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone
from typing import Any

import websockets


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class LiquidationHunter:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.events: deque[dict[str, Any]] = deque(maxlen=200)
        self.last_cluster: dict[str, Any] | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="liquidation-hunter")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        url = "wss://fstream.binance.com/ws/!forceOrder@arr"
        while not self._stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    async for raw in ws:
                        payload = json.loads(raw)
                        for event in payload.get("o") and [payload] or (payload if isinstance(payload, list) else []):
                            self._record(event.get("o") or {})
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(3)

    def _record(self, order: dict[str, Any]) -> None:
        symbol = str(order.get("s") or "")
        qty = float(order.get("q") or 0.0)
        price = float(order.get("ap") or order.get("p") or 0.0)
        side = str(order.get("S") or "")
        notion = qty * price
        item = {"symbol": symbol, "qty": qty, "price": price, "side": side, "notional_usd": notion, "ts": _utc_now()}
        self.events.append(item)
        recent = [e for e in self.events if e["symbol"] == symbol and e["side"] == side]
        cluster_notional = sum(float(e["notional_usd"]) for e in recent[-12:])
        if cluster_notional >= 250000:
            self.last_cluster = {
                "symbol": symbol,
                "side": side,
                "cluster_notional_usd": round(cluster_notional, 2),
                "bounce_bias": "BUY" if side == "SELL" else "SELL",
                "reference_price": price,
                "updated_at": _utc_now(),
            }

    def maybe_bounce_order(self, execution, mark_prices: dict[str, float]) -> dict[str, Any] | None:
        cluster = self.last_cluster
        if not cluster:
            return None
        symbol = cluster["symbol"]
        pretty_symbol = f"{symbol[:-4]}/USDT" if symbol.endswith("USDT") else symbol
        if execution.has_position(pretty_symbol):
            return None
        px = float(mark_prices.get(pretty_symbol) or cluster.get("reference_price") or 0.0)
        if px <= 0:
            return None
        signal = str(cluster.get("bounce_bias") or "BUY")
        size = max(15.0 / px, 1e-6)
        order = execution.place_order(
            symbol=pretty_symbol,
            signal=signal,
            size_units=size,
            leverage=3.0,
            market_price=px,
            stop_loss=px * (0.992 if signal == "BUY" else 1.008),
            take_profit=px * (1.008 if signal == "BUY" else 0.992),
            metadata={
                "ai_reasoning": f"Liquidation cascade hunter bounce order after {cluster['cluster_notional_usd']:.0f} USD cluster."
            },
        )
        self.last_cluster = None
        return order

    def snapshot(self) -> dict[str, Any]:
        return {
            "recent_events": list(self.events)[-20:],
            "last_cluster": self.last_cluster,
            "updated_at": _utc_now(),
        }


liquidation_hunter = LiquidationHunter()
