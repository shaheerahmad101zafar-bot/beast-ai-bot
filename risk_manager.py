"""
Beast AI Trading Bot — Phase 2 Risk Management Module

Position sizing from account equity + risk %, ATR-volatility-aware leverage,
and portfolio basket correlation guard for altcoin flash-crash containment.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

import numpy as np

import config

# Default paper-trading equity used by the live scan
DEFAULT_ACCOUNT_BALANCE: float = 1_000.0

# Leverage bounds for Binance-style USD-M futures scaffolding
MIN_LEVERAGE: float = 1.0
MAX_LEVERAGE: float = 20.0
# Target ATR as % of price; higher realized vol => lower leverage
TARGET_ATR_PCT: float = 0.015  # 1.5%


def _base_asset(symbol: str) -> str:
    return str(symbol or "").upper().replace("-", "/").split("/")[0].strip()


def _is_altcoin(symbol: str) -> bool:
    return _base_asset(symbol) not in {"BTC", "WBTC"}


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
        lookback = max(20, int(getattr(config, "CORRELATION_LOOKBACK", 48)))
        self._price_hist: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=lookback))
        self.correlation_threshold = float(getattr(config, "CORRELATION_THRESHOLD", 0.70))
        self.max_correlated_alts = int(getattr(config, "MAX_CORRELATED_ALT_POSITIONS", 3))

    @property
    def risk_amount(self) -> float:
        """Dollar amount willing to lose on a single trade."""
        return self.account_balance * self.risk_per_trade

    def record_price(self, symbol: str, price: float) -> None:
        """Ingest live marks for real-time basket correlation."""
        px = float(price or 0.0)
        if px <= 0:
            return
        hist = self._price_hist[str(symbol).upper()]
        if hist and abs(hist[-1] - px) / max(hist[-1], 1e-12) < 1e-8:
            return
        hist.append(px)

    def ingest_marks(self, mark_prices: dict[str, float]) -> None:
        for symbol, price in (mark_prices or {}).items():
            self.record_price(str(symbol), float(price))

    @staticmethod
    def _returns(prices: list[float]) -> np.ndarray:
        if len(prices) < 3:
            return np.array([], dtype=float)
        arr = np.asarray(prices, dtype=float)
        prev = arr[:-1]
        return (arr[1:] - prev) / np.maximum(prev, 1e-12)

    def pairwise_correlation(self, symbol_a: str, symbol_b: str) -> float | None:
        a = list(self._price_hist.get(str(symbol_a).upper()) or [])
        b = list(self._price_hist.get(str(symbol_b).upper()) or [])
        ra, rb = self._returns(a), self._returns(b)
        n = min(len(ra), len(rb))
        if n < 8:
            return None
        ra, rb = ra[-n:], rb[-n:]
        if float(np.std(ra)) < 1e-12 or float(np.std(rb)) < 1e-12:
            return None
        corr = float(np.corrcoef(ra, rb)[0, 1])
        if corr != corr:
            return None
        return max(-1.0, min(1.0, corr))

    def basket_correlation_guard(
        self,
        symbol: str,
        direction: str,
        open_positions: dict[str, dict[str, Any]] | list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Block opening more than N correlated altcoin positions in the same
        direction (Long/Short) to limit portfolio drawdown in a BTC flash crash.
        """
        direction = str(direction or "").upper()
        if direction not in {"LONG", "SHORT", "BUY", "SELL"}:
            return {"ok": True, "reason": "non_directional"}
        if direction == "BUY":
            direction = "LONG"
        if direction == "SELL":
            direction = "SHORT"

        if not _is_altcoin(symbol):
            return {"ok": True, "reason": "btc_exempt", "correlated_peers": []}

        if isinstance(open_positions, dict):
            positions = list(open_positions.values())
        else:
            positions = list(open_positions or [])

        same_dir_alts = [
            p
            for p in positions
            if str(p.get("direction") or "").upper() == direction
            and _is_altcoin(str(p.get("symbol") or ""))
            and str(p.get("symbol") or "").upper() != str(symbol).upper()
        ]

        peers: list[dict[str, Any]] = []
        for pos in same_dir_alts:
            peer_sym = str(pos.get("symbol") or "")
            corr = self.pairwise_correlation(symbol, peer_sym)
            # Insufficient history: treat alt vs alt as correlated (flash-crash safe)
            if corr is None:
                btc_a = self.pairwise_correlation(symbol, "BTC/USDT")
                btc_b = self.pairwise_correlation(peer_sym, "BTC/USDT")
                if btc_a is not None and btc_b is not None:
                    corr = min(btc_a, btc_b)
                else:
                    corr = self.correlation_threshold
            if corr >= self.correlation_threshold:
                peers.append({"symbol": peer_sym, "correlation": round(float(corr), 4)})

        ok = len(peers) < self.max_correlated_alts
        return {
            "ok": ok,
            "reason": "pass" if ok else "basket_correlation_limit",
            "direction": direction,
            "threshold": self.correlation_threshold,
            "max_correlated_alts": self.max_correlated_alts,
            "correlated_peers": peers,
            "correlated_count": len(peers),
        }

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
            "atr_pct_frac": round(atr_pct, 6),
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


# Shared singleton for live basket correlation across bot cycles
portfolio_risk_guard = RiskManager()
