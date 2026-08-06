"""
Dynamic micro-execution ProcessPool (GIL bypass) for book/ticker math.

Heavy NumPy order-book / imbalance work runs in isolated processes while the
async WebSocket loop stays hot for sub-15ms order dispatch.
"""

from __future__ import annotations

import atexit
import logging
import time
from concurrent.futures import Future, ProcessPoolExecutor
from typing import Any

import config

logger = logging.getLogger("beast.micro_exec")


def compute_book_metrics(
    bids: list[list[float]] | list[tuple[float, float]],
    asks: list[list[float]] | list[tuple[float, float]],
    mid: float,
) -> dict[str, float]:
    """
    Process-safe pure function: order-book imbalance, microprice, spread bps.
    """
    t0 = time.perf_counter()
    bid_notional = 0.0
    ask_notional = 0.0
    best_bid = float(bids[0][0]) if bids else mid
    best_ask = float(asks[0][0]) if asks else mid
    for level in (bids or [])[:10]:
        px, qty = float(level[0]), float(level[1])
        bid_notional += px * qty
    for level in (asks or [])[:10]:
        px, qty = float(level[0]), float(level[1])
        ask_notional += px * qty
    total = bid_notional + ask_notional
    imbalance = ((bid_notional - ask_notional) / total) if total > 0 else 0.0
    if best_bid > 0 and best_ask > 0:
        micro = (best_ask * bid_notional + best_bid * ask_notional) / max(total, 1e-12)
    else:
        micro = mid
    spread_bps = abs(best_ask - best_bid) / max(mid, 1e-12) * 10_000.0
    return {
        "imbalance": round(float(imbalance), 6),
        "microprice": round(float(micro), 8),
        "spread_bps": round(float(spread_bps), 4),
        "best_bid": round(best_bid, 8),
        "best_ask": round(best_ask, 8),
        "compute_ms": round((time.perf_counter() - t0) * 1000.0, 4),
    }


def compute_tick_burst(prev_price: float, price: float, volume: float, volume_ema: float) -> dict[str, float | bool]:
    """Process-safe burst / spike detector used by HFT path."""
    t0 = time.perf_counter()
    if prev_price <= 0 or price <= 0:
        return {"move": 0.0, "spike": False, "compute_ms": 0.0}
    move = (price - prev_price) / prev_price
    spike = bool(volume > 0 and volume_ema > 0 and volume >= volume_ema * 1.8)
    return {
        "move": round(float(move), 8),
        "spike": spike,
        "abs_move": round(abs(float(move)), 8),
        "compute_ms": round((time.perf_counter() - t0) * 1000.0, 4),
    }


class MicroExecPool:
    """Lazy ProcessPoolExecutor wrapper — never blocks the WS hot path."""

    def __init__(self, workers: int | None = None) -> None:
        self.workers = max(1, int(workers or getattr(config, "MICRO_EXEC_WORKERS", 2)))
        self._pool: ProcessPoolExecutor | None = None
        self._last_book: dict[str, dict[str, float]] = {}
        self._stats = {"submitted": 0, "completed": 0, "fallback": 0}

    def start(self) -> None:
        if self._pool is not None:
            return
        try:
            self._pool = ProcessPoolExecutor(max_workers=self.workers)
            atexit.register(self.shutdown)
            logger.info("Micro-exec ProcessPool started workers=%s", self.workers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ProcessPool unavailable (%s) — using inline fallback", exc)
            self._pool = None

    def shutdown(self) -> None:
        pool = self._pool
        self._pool = None
        if pool is not None:
            try:
                pool.shutdown(wait=False, cancel_futures=True)
            except Exception:  # noqa: BLE001
                pass

    def submit_book(
        self,
        symbol: str,
        bids: list[Any],
        asks: list[Any],
        mid: float,
    ) -> Future | None:
        self.start()
        self._stats["submitted"] += 1
        if self._pool is None:
            result = compute_book_metrics(bids, asks, mid)
            self._last_book[symbol] = result
            self._stats["fallback"] += 1
            self._stats["completed"] += 1
            return None

        fut = self._pool.submit(compute_book_metrics, bids, asks, mid)

        def _done(f: Future) -> None:
            try:
                self._last_book[symbol] = f.result()
                self._stats["completed"] += 1
            except Exception:  # noqa: BLE001
                self._stats["fallback"] += 1

        fut.add_done_callback(_done)
        return fut

    def book_snapshot(self, symbol: str) -> dict[str, float]:
        return dict(self._last_book.get(symbol) or {})

    def analyze_tick_inline(
        self,
        prev_price: float,
        price: float,
        volume: float,
        volume_ema: float,
    ) -> dict[str, float | bool]:
        """Keep tick burst detection inline (<1ms) for order latency budget."""
        return compute_tick_burst(prev_price, price, volume, volume_ema)

    def stats(self) -> dict[str, Any]:
        return {
            **self._stats,
            "workers": self.workers,
            "pool_alive": self._pool is not None,
            "cached_books": len(self._last_book),
            "max_order_latency_ms": float(getattr(config, "MAX_ORDER_LATENCY_MS", 15)),
        }


micro_exec_pool = MicroExecPool()
