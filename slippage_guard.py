"""
Algorithmic iceberg stop-loss slicer + volatility slippage model.
"""

from __future__ import annotations

from typing import Any

import config


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

    @staticmethod
    def volatility_slippage_pct(atr_pct: float | None = None, realized_vol: float | None = None) -> float:
        """
        Map pair volatility into a 0.02%–0.08% market slippage penalty.

        atr_pct / realized_vol are fractions (e.g. 0.015 = 1.5%).
        """
        lo = float(config.MIN_SLIPPAGE_PCT)
        hi = float(config.MAX_SLIPPAGE_PCT)
        vol = float(atr_pct if atr_pct is not None else (realized_vol or 0.0))
        if vol != vol or vol <= 0:
            return lo
        # 0.5% ATR → floor, ~3% ATR → ceiling
        t = (vol - 0.005) / 0.025
        t = max(0.0, min(1.0, t))
        return lo + t * (hi - lo)

    def apply_fill_price(
        self,
        price: float,
        *,
        direction: str,
        is_entry: bool,
        atr_pct: float | None = None,
        realized_vol: float | None = None,
    ) -> dict[str, float]:
        slip = self.volatility_slippage_pct(atr_pct=atr_pct, realized_vol=realized_vol)
        buying = (direction == "LONG" and is_entry) or (direction == "SHORT" and not is_entry)
        fill = price * (1.0 + slip) if buying else price * (1.0 - slip)
        return {
            "fill_price": fill,
            "slippage_pct": slip,
            "slippage_bps": round(slip * 10_000.0, 4),
        }


slippage_guard = SlippageGuard()
