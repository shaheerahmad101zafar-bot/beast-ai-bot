"""
TWAP / iceberg slicer plan for larger orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SlicePlan:
    enabled: bool
    slices: int
    notional_usd: float
    slice_notional_usd: float
    cadence_ms: int


class ExecutionSlicer:
    def __init__(self, threshold_usd: float = 250.0, cadence_ms: int = 1200) -> None:
        self.threshold_usd = float(threshold_usd)
        self.cadence_ms = int(cadence_ms)

    def plan(self, *, size_units: float, market_price: float) -> SlicePlan:
        notional = float(size_units) * float(market_price)
        if notional < self.threshold_usd:
            return SlicePlan(False, 1, round(notional, 4), round(notional, 4), self.cadence_ms)
        slices = min(6, max(2, int(round(notional / self.threshold_usd))))
        return SlicePlan(
            True,
            slices,
            round(notional, 4),
            round(notional / slices, 4),
            self.cadence_ms,
        )

    def enrich_metadata(self, metadata: dict[str, Any] | None, *, size_units: float, market_price: float) -> dict[str, Any]:
        meta = dict(metadata or {})
        plan = self.plan(size_units=size_units, market_price=market_price)
        meta["slice_plan"] = {
            "enabled": plan.enabled,
            "slices": plan.slices,
            "notional_usd": plan.notional_usd,
            "slice_notional_usd": plan.slice_notional_usd,
            "cadence_ms": plan.cadence_ms,
            "strategy": "TWAP",
        }
        return meta


execution_slicer = ExecutionSlicer()
