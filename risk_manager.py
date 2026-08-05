"""
Beast AI Trading Bot — Phase 2 Risk Management Module

Position sizing from account equity + risk %, and ATR-volatility-aware leverage.
"""

from __future__ import annotations

from typing import Any

import config

# Default paper-trading equity used by the live scan
DEFAULT_ACCOUNT_BALANCE: float = 1_000.0

# Leverage bounds for Binance-style USD-M futures scaffolding
MIN_LEVERAGE: float = 1.0
MAX_LEVERAGE: float = 20.0
# Target ATR as % of price; higher realized vol => lower leverage
TARGET_ATR_PCT: float = 0.015  # 1.5%


class RiskManager:
    """Compute position size and volatility-scaled leverage for a trade idea."""

    def __init__(
        self,
        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
        risk_per_trade: float = config.MAX_RISK_PER_TRADE,
        min_leverage: float = MIN_LEVERAGE,
        max_leverage: float = MAX_LEVERAGE,
        target_atr_pct: float = TARGET_ATR_PCT,
    ) -> None:
        if account_balance <= 0:
            raise ValueError("account_balance must be positive")
        if not 0 < risk_per_trade <= 1:
            raise ValueError("risk_per_trade must be in (0, 1]")

        self.account_balance = float(account_balance)
        self.risk_per_trade = float(risk_per_trade)
        self.min_leverage = float(min_leverage)
        self.max_leverage = float(max_leverage)
        self.target_atr_pct = float(target_atr_pct)

    @property
    def risk_amount(self) -> float:
        """Dollar amount willing to lose on a single trade."""
        return self.account_balance * self.risk_per_trade

    def calculate_position_size(
        self,
        entry_price: float,
        stop_loss_price: float,
    ) -> dict[str, float]:
        """
        Exact position sizing from equity risk and stop distance.

        units = risk_amount / |entry - stop|
        notional = units * entry_price
        """
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        stop_distance = abs(entry_price - stop_loss_price)
        if stop_distance <= 0 or stop_distance != stop_distance:
            # Degenerate stop: fall back to config default % stop
            stop_distance = entry_price * config.DEFAULT_STOP_LOSS

        units = self.risk_amount / stop_distance
        notional = units * entry_price
        margin_at_1x = notional  # informational; actual margin uses leverage

        return {
            "risk_amount": round(self.risk_amount, 4),
            "stop_distance": round(stop_distance, 8),
            "position_size_units": round(units, 8),
            "position_size_notional": round(notional, 4),
            "margin_at_1x": round(margin_at_1x, 4),
        }

    def calculate_leverage(
        self,
        entry_price: float,
        atr: float,
    ) -> dict[str, float]:
        """
        Inverse-volatility leverage from ATR.

        leverage ≈ max_leverage * (target_atr_pct / atr_pct), clamped to bounds.
        Higher ATR% (chop / expansion) => lower leverage.
        """
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        atr_pct = (atr / entry_price) if atr > 0 and atr == atr else self.target_atr_pct
        raw = self.max_leverage * (self.target_atr_pct / atr_pct)
        leverage = max(self.min_leverage, min(self.max_leverage, raw))

        return {
            "atr_pct": round(atr_pct * 100.0, 4),  # percent points for display
            "leverage": round(leverage, 2),
            "leverage_raw": round(raw, 4),
        }

    def evaluate_trade(
        self,
        signal_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine signal levels into a full risk package."""
        entry = float(signal_payload["entry_price"])
        stop = float(signal_payload["stop_loss_price"])
        atr = float(signal_payload.get("atr") or 0.0)

        sizing = self.calculate_position_size(entry, stop)
        lev = self.calculate_leverage(entry, atr)

        required_margin = (
            sizing["position_size_notional"] / lev["leverage"]
            if lev["leverage"] > 0
            else sizing["position_size_notional"]
        )

        return {
            **sizing,
            **lev,
            "required_margin": round(required_margin, 4),
            "account_balance": self.account_balance,
            "risk_pct": self.risk_per_trade,
        }
