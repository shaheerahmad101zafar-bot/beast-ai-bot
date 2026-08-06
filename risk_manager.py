"""
Beast AI Trading Bot — Phase 2 Risk Management Module

Position sizing from account equity + risk %, ATR-volatility-aware leverage,
and portfolio basket correlation guard for altcoin flash-crash containment.
"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any
import time

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
        *,
        atr_1m: float | None = None,
        recent_range_pct: float | None = None,
    ) -> dict[str, float]:
        """
        Inverse-volatility leverage from ATR, with dynamic max-leverage caps
        when 1-minute / short-horizon volatility spikes.
        """
        if entry_price <= 0:
            raise ValueError("entry_price must be positive")

        atr_pct = (atr / entry_price) if atr > 0 and atr == atr else self.target_atr_pct
        # Prefer explicit 1m ATR; else short-horizon range; else scale bar ATR toward 1m proxy
        if atr_1m is not None and atr_1m > 0:
            spike_pct = float(atr_1m) / entry_price
        elif recent_range_pct is not None and recent_range_pct > 0:
            spike_pct = float(recent_range_pct)
        else:
            spike_pct = atr_pct

        vol_cap = self.volatility_max_leverage(spike_pct)
        effective_max = min(self.max_leverage, vol_cap)
        raw = effective_max * (self.target_atr_pct / max(atr_pct, 1e-9))
        leverage = max(self.min_leverage, min(effective_max, raw))

        return {
            "atr_pct": round(atr_pct * 100.0, 4),  # percent points for display
            "atr_pct_frac": round(atr_pct, 6),
            "spike_atr_pct": round(spike_pct * 100.0, 4),
            "vol_leverage_cap": round(vol_cap, 2),
            "leverage": round(leverage, 2),
            "leverage_raw": round(raw, 4),
        }

    @staticmethod
    def volatility_max_leverage(spike_atr_pct: float) -> float:
        """
        Down-scale max allowable leverage when 1-minute volatility spikes.
        spike_atr_pct is a fraction (0.02 = 2%).
        """
        spike = float(spike_atr_pct or 0.0)
        if spike >= float(config.VOL_LEV_CAP_EXTREME_ATR):
            return float(config.VOL_LEV_EXTREME_MAX)
        if spike >= float(config.VOL_LEV_CAP_HARD_ATR):
            return float(config.VOL_LEV_HARD_MAX)
        if spike >= float(config.VOL_LEV_CAP_SOFT_ATR):
            return float(config.VOL_LEV_SOFT_MAX)
        return float(MAX_LEVERAGE)

    def evaluate_trade(
        self,
        signal_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Combine signal levels into a full risk package."""
        entry = float(signal_payload["entry_price"])
        stop = float(signal_payload["stop_loss_price"])
        atr = float(signal_payload.get("atr") or 0.0)
        atr_1m = signal_payload.get("atr_1m")
        recent_range_pct = signal_payload.get("recent_range_pct")

        sizing = self.calculate_position_size(entry, stop)
        lev = self.calculate_leverage(
            entry,
            atr,
            atr_1m=float(atr_1m) if atr_1m is not None else None,
            recent_range_pct=float(recent_range_pct) if recent_range_pct is not None else None,
        )

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

    # ------------------------------------------------------------------
    # Live funding-rate arbitrage / bleed guard
    # ------------------------------------------------------------------
    def refresh_funding_rates(self, symbols: list[str] | None = None) -> dict[str, float]:
        """Fetch Binance USD-M premiumIndex funding for active pairs."""
        import requests

        out: dict[str, float] = {}
        wanted = [str(s).upper().replace("-", "/") for s in (symbols or [])]
        try:
            resp = requests.get("https://fapi.binance.com/fapi/v1/premiumIndex", timeout=8)
            if resp.status_code in {429, 500, 502, 503, 504}:
                # soft fail — keep prior cache
                return dict(getattr(self, "_funding_cache", {}) or {})
            resp.raise_for_status()
            rows = resp.json()
            if isinstance(rows, dict):
                rows = [rows]
            for row in rows or []:
                raw = str(row.get("symbol") or "")
                if not raw.endswith("USDT"):
                    continue
                display = f"{raw[:-4]}/USDT"
                if wanted and display not in wanted and raw not in {
                    w.replace("/", "") for w in wanted
                }:
                    continue
                rate = float(row.get("lastFundingRate") or 0.0)
                out[display] = rate
            self._funding_cache = out
            self._funding_updated_at = time.time()
        except Exception:
            out = dict(getattr(self, "_funding_cache", {}) or {})
        return out

    def funding_bleed_guard(
        self,
        symbol: str,
        direction: str,
        funding_rate: float | None = None,
    ) -> dict[str, Any]:
        """
        Halt new entries (or flag micro-hedge) when |funding| > 0.05% per cycle
        and the position would pay the funding side.
        """
        import time as _time

        threshold = float(getattr(config, "FUNDING_BLEED_THRESHOLD", 0.0005))
        rate = funding_rate
        if rate is None:
            cache = getattr(self, "_funding_cache", {}) or {}
            # refresh at most every 60s
            if time.time() - float(getattr(self, "_funding_updated_at", 0.0) or 0.0) > 60:
                self.refresh_funding_rates([symbol])
                cache = getattr(self, "_funding_cache", {}) or {}
            rate = float(cache.get(str(symbol).upper()) or 0.0)

        direction = str(direction or "").upper()
        if direction == "BUY":
            direction = "LONG"
        if direction == "SELL":
            direction = "SHORT"

        # Positive funding → longs pay shorts; negative → shorts pay longs
        pays_funding = (direction == "LONG" and rate > 0) or (direction == "SHORT" and rate < 0)
        bleed = abs(float(rate)) >= threshold and pays_funding
        hedge = None
        if bleed:
            hedge = {
                "action": "micro_hedge_or_halt",
                "hedge_side": "SHORT" if direction == "LONG" else "LONG",
                "reason": "funding_bleed",
            }
        return {
            "ok": not bleed,
            "symbol": symbol,
            "direction": direction,
            "funding_rate": round(float(rate), 8),
            "threshold": threshold,
            "pays_funding": pays_funding,
            "halt_entries": bleed,
            "hedge": hedge,
            "detail": "funding_ok" if not bleed else "funding_bleed_exceeds_0.05pct",
        }


# Shared singleton for live basket correlation across bot cycles
portfolio_risk_guard = RiskManager()
portfolio_risk_guard._funding_cache = {}  # type: ignore[attr-defined]
portfolio_risk_guard._funding_updated_at = 0.0  # type: ignore[attr-defined]
