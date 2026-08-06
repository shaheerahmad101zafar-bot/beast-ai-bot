"""
Algorithmic iceberg stop-loss slicer.
"""

from __future__ import annotations

from typing import Any


class SlippageGuard:
    def build_iceberg(self, *, symbol: str, direction: str, size: float, mark_price: float) -> dict[str, Any]:
        clips = min(8, max(2, int(round(abs(size) * max(mark_price, 1.0) / 25.0))))
        return {
            "symbol": symbol,
            "direction": direction,
            "strategy": "micro_limit_iceberg",
            "clips": clips,
            "clip_size": round(size / clips, 8),
            "reference_price": round(mark_price, 8),
        }


slippage_guard = SlippageGuard()
