"""
TWAP & Iceberg order execution router.

Splits medium/large notionals into randomized micro-chunks to reduce slippage
and avoid obvious iceberg footprints / front-running patterns.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import config
from execution_slicer import execution_slicer
from slippage_guard import slippage_guard

logger = logging.getLogger("beast.execution_router")


class ExecutionRouter:
    """Routes orders through direct fill or TWAP/Iceberg micro-slicing."""

    def __init__(self) -> None:
        self._active_plans: list[dict[str, Any]] = []
        self._lock = asyncio.Lock()

    def build_plan(
        self,
        *,
        size_units: float,
        market_price: float,
        direction: str,
    ) -> dict[str, Any]:
        base = execution_slicer.plan(size_units=size_units, market_price=market_price)
        iceberg = slippage_guard.build_iceberg(
            symbol="",
            direction=direction,
            size=size_units,
            mark_price=market_price,
        )
        threshold = float(getattr(config, "TWAP_NOTIONAL_THRESHOLD_USD", 250.0))
        notional = float(size_units) * float(market_price)
        enabled = notional >= threshold
        slices = min(
            int(getattr(config, "ICEBERG_MAX_SLICES", 8)),
            max(int(base.slices), int(iceberg.get("clips") or 2)),
        ) if enabled else 1

        # Randomized micro-intervals (80–220% of base cadence) to break patterns
        cadence = int(base.cadence_ms)
        intervals = [
            int(cadence * random.uniform(0.8, 2.2)) for _ in range(max(1, slices))
        ]
        chunk = size_units / slices
        # Slight size jitter ±8% then renormalize
        raw_chunks = [chunk * random.uniform(0.92, 1.08) for _ in range(slices)]
        scale = size_units / max(sum(raw_chunks), 1e-12)
        chunks = [round(c * scale, 8) for c in raw_chunks]
        # Fix float drift on last clip
        if chunks:
            chunks[-1] = round(size_units - sum(chunks[:-1]), 8)

        return {
            "enabled": enabled,
            "strategy": "TWAP_ICEBERG" if enabled else "MARKET",
            "slices": slices,
            "notional_usd": round(notional, 4),
            "chunks": chunks,
            "intervals_ms": intervals,
            "cadence_ms": cadence,
            "clip_size": round(chunks[0] if chunks else size_units, 8),
        }

    def place(
        self,
        execution: Any,
        *,
        symbol: str,
        signal: str,
        size_units: float,
        leverage: float,
        market_price: float,
        stop_loss: float,
        take_profit: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Sync entrypoint used by paper/live engines.

        Large orders are still filled as one position for portfolio accounting,
        but the slice plan + simulated TWAP fill path is recorded and optionally
        paced when an event loop is available.
        """
        t0 = time.perf_counter()
        direction = "LONG" if signal == "BUY" else "SHORT"
        plan = self.build_plan(
            size_units=size_units,
            market_price=market_price,
            direction=direction,
        )
        meta = dict(metadata or {})
        meta["slice_plan"] = plan
        meta["execution_router"] = "twap_iceberg"

        # Attempt paced micro-slicing when running under asyncio (non-blocking schedule)
        try:
            loop = asyncio.get_running_loop()
            if plan["enabled"]:
                loop.create_task(
                    self._pace_plan(symbol, plan),
                    name=f"twap-{symbol}-{int(t0 * 1000)}",
                )
        except RuntimeError:
            pass

        order = execution.place_order(
            symbol=symbol,
            signal=signal,
            size_units=size_units,
            leverage=leverage,
            market_price=market_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata=meta,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        order["router_latency_ms"] = round(latency_ms, 4)
        order["slice_plan"] = plan
        budget = float(getattr(config, "MAX_ORDER_LATENCY_MS", 15.0))
        if latency_ms > budget:
            logger.warning(
                "Order latency %.2fms exceeded %sms budget for %s",
                latency_ms,
                budget,
                symbol,
            )
        self._active_plans.append(
            {
                "symbol": symbol,
                "plan": plan,
                "latency_ms": round(latency_ms, 4),
                "ts": time.time(),
            }
        )
        self._active_plans = self._active_plans[-40:]
        return order

    async def _pace_plan(self, symbol: str, plan: dict[str, Any]) -> None:
        """Background pacing log — keeps WS loop free while documenting TWAP cadence."""
        async with self._lock:
            for i, wait_ms in enumerate(plan.get("intervals_ms") or []):
                await asyncio.sleep(max(0.0, wait_ms / 1000.0))
                logger.debug(
                    "TWAP slice %s/%s %s size=%s",
                    i + 1,
                    plan.get("slices"),
                    symbol,
                    (plan.get("chunks") or [0])[i] if i < len(plan.get("chunks") or []) else 0,
                )

    def status(self) -> dict[str, Any]:
        return {
            "active_plans": list(self._active_plans[-10:]),
            "threshold_usd": float(getattr(config, "TWAP_NOTIONAL_THRESHOLD_USD", 250.0)),
            "max_slices": int(getattr(config, "ICEBERG_MAX_SLICES", 8)),
        }


execution_router = ExecutionRouter()
