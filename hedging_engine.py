"""
Delta-neutral flash hedging engine.

When panic volatility hits, Beast can short BTC/USDT as a fast hedge instead
of force-closing all positions into slippage.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class HedgingEngine:
    def __init__(self) -> None:
        self.last_hedge: dict[str, Any] | None = None

    def net_delta_notional(self, positions: list[dict[str, Any]]) -> float:
        total = 0.0
        for pos in positions:
            notional = float(pos.get("notional") or 0.0)
            total += notional if str(pos.get("direction") or "").upper() == "LONG" else -notional
        return total

    def apply_flash_hedge(
        self,
        execution,
        *,
        positions: list[dict[str, Any]],
        mark_prices: dict[str, float],
        hedge_symbol: str = "BTC/USDT",
        hedge_ratio: float = 0.85,
        leverage: float = 4.0,
    ) -> dict[str, Any] | None:
        net_notional = self.net_delta_notional(positions)
        if net_notional <= 0:
            return None
        hedge_price = float(mark_prices.get(hedge_symbol) or 0.0)
        if hedge_price <= 0 or execution.has_position(hedge_symbol):
            return None
        hedge_notional = net_notional * hedge_ratio
        size_units = hedge_notional / hedge_price
        order = execution.place_order(
            symbol=hedge_symbol,
            signal="SELL",
            size_units=size_units,
            leverage=leverage,
            market_price=hedge_price,
            stop_loss=hedge_price * 1.01,
            take_profit=hedge_price * 0.985,
            metadata={
                "ai_reasoning": (
                    "Flash hedge engaged: short BTC/USDT to neutralize portfolio delta during panic volatility."
                )
            },
        )
        self.last_hedge = {
            "ts": _utc_now(),
            "hedge_symbol": hedge_symbol,
            "hedge_notional": round(hedge_notional, 4),
            "net_notional": round(net_notional, 4),
            "order": order,
        }
        return self.last_hedge

    def snapshot(self) -> dict[str, Any]:
        return self.last_hedge or {"ts": _utc_now(), "status": "idle"}


hedging_engine = HedgingEngine()
