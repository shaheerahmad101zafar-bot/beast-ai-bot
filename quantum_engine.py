"""
Beast AI — Quantitative Risk & Flow Suite

VPIN toxicity, cointegration pair-trading, Q-learning policy hints,
liquidation heatmap proxy, ADX/ATR regime classifier, and 5% daily
drawdown circuit breaker.
"""

from __future__ import annotations

import math
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

import config

MAX_DAILY_DRAWDOWN = 0.05  # 5% circuit breaker


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class QuantumEngine:
    """Institutional-style quant helpers for the Beast desk."""

    def __init__(self) -> None:
        self._bucket_buys: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self._bucket_sells: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=50))
        self._price_hist: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=240))
        self._q_table: dict[str, dict[str, float]] = defaultdict(
            lambda: {"HOLD": 0.0, "BUY": 0.0, "SELL": 0.0}
        )
        self._day_start_equity: float | None = None
        self._day_key: str | None = None
        self._breaker_tripped = False
        self._breaker_reason: str | None = None
        self._liq_levels: dict[str, list[dict[str, Any]]] = {}
        self._last_regime: dict[str, Any] = {"label": "UNKNOWN", "adx": 0, "atr_pct": 0}

    # ------------------------------------------------------------------
    # VPIN — Volume-Synchronized Probability of Informed Trading (proxy)
    # ------------------------------------------------------------------
    def ingest_trade_flow(self, symbol: str, price: float, size: float, side: str) -> float:
        """Update buy/sell volume buckets; return VPIN in [0,1]."""
        bucket = self._bucket_buys[symbol] if side.upper() in {"BUY", "LONG", "B"} else self._bucket_sells[symbol]
        bucket.append(max(0.0, float(size)))
        self._price_hist[symbol].append(float(price))
        return self.vpin(symbol)

    def vpin(self, symbol: str) -> float:
        buys = list(self._bucket_buys[symbol])
        sells = list(self._bucket_sells[symbol])
        if not buys and not sells:
            return 0.0
        # Align lengths
        n = max(len(buys), len(sells), 1)
        buy_arr = np.array((buys + [0.0] * n)[:n], dtype=float)
        sell_arr = np.array((sells + [0.0] * n)[:n], dtype=float)
        imbalance = np.abs(buy_arr - sell_arr)
        total = buy_arr + sell_arr
        denom = float(np.sum(total)) or 1.0
        return float(min(1.0, np.sum(imbalance) / denom))

    def toxicity_label(self, symbol: str) -> dict[str, Any]:
        v = self.vpin(symbol)
        if v >= 0.65:
            label = "TOXIC"
        elif v >= 0.4:
            label = "ELEVATED"
        else:
            label = "CLEAN"
        return {"symbol": symbol, "vpin": round(v, 4), "label": label, "ts": _utc_iso()}

    # ------------------------------------------------------------------
    # Cointegration pair trading (delta-neutral residual)
    # ------------------------------------------------------------------
    def cointegration_spread(
        self,
        series_a: list[float] | np.ndarray,
        series_b: list[float] | np.ndarray,
    ) -> dict[str, Any]:
        a = np.asarray(series_a, dtype=float)
        b = np.asarray(series_b, dtype=float)
        n = min(len(a), len(b))
        if n < 30:
            return {"ok": False, "detail": "Need >=30 overlapping samples"}
        a, b = a[-n:], b[-n:]
        # OLS hedge ratio: a ~ beta * b
        beta = float(np.dot(b, a) / (np.dot(b, b) + 1e-12))
        spread = a - beta * b
        mean = float(np.mean(spread))
        std = float(np.std(spread) + 1e-12)
        z = float((spread[-1] - mean) / std)
        # Engle-Granger residual ADF-lite: correlation of Δspread vs lag
        ds = np.diff(spread)
        lag = spread[:-1]
        if len(ds) > 5:
            rho = float(np.corrcoef(ds, lag - mean)[0, 1])
        else:
            rho = 0.0
        cointegrated = rho < -0.15 and abs(z) > 0.5
        signal = "HOLD"
        if z > 1.8:
            signal = "SHORT_A_LONG_B"  # spread rich
        elif z < -1.8:
            signal = "LONG_A_SHORT_B"
        return {
            "ok": True,
            "beta": round(beta, 6),
            "zscore": round(z, 4),
            "mean": round(mean, 6),
            "std": round(std, 6),
            "rho": round(rho, 4),
            "cointegrated": cointegrated,
            "delta_neutral_signal": signal,
            "ts": _utc_iso(),
        }

    # ------------------------------------------------------------------
    # Q-Learning policy optimizer (tabular, online)
    # ------------------------------------------------------------------
    def rl_observe(
        self,
        state_key: str,
        action: str,
        reward: float,
        next_state_key: str,
        *,
        alpha: float = 0.15,
        gamma: float = 0.9,
    ) -> dict[str, float]:
        action = action.upper()
        if action not in {"HOLD", "BUY", "SELL"}:
            action = "HOLD"
        q = self._q_table[state_key]
        q_next = self._q_table[next_state_key]
        best_next = max(q_next.values()) if q_next else 0.0
        q[action] = (1 - alpha) * q.get(action, 0.0) + alpha * (reward + gamma * best_next)
        return dict(q)

    def rl_policy(self, state_key: str) -> dict[str, Any]:
        q = self._q_table[state_key]
        best = max(q, key=q.get) if q else "HOLD"
        return {"state": state_key, "action": best, "q": {k: round(v, 4) for k, v in q.items()}}

    def regime_state_key(self, regime: str, vpin_bucket: str, trend: str) -> str:
        return f"{regime}|{vpin_bucket}|{trend}"

    # ------------------------------------------------------------------
    # Liquidation heatmap (synthetic density from price history + leverage bands)
    # ------------------------------------------------------------------
    def update_liquidation_heatmap(self, symbol: str, mark: float) -> list[dict[str, Any]]:
        hist = list(self._price_hist[symbol])
        if mark > 0:
            hist.append(mark)
        if len(hist) < 5:
            return []
        arr = np.asarray(hist[-120:], dtype=float)
        mid = float(arr[-1])
        levers = [5, 10, 20, 25, 50, 75, 100, 125]
        levels: list[dict[str, Any]] = []
        for lev in levers:
            # Approx long liq below / short liq above (simplified maintenance)
            long_liq = mid * (1 - 0.9 / lev)
            short_liq = mid * (1 + 0.9 / lev)
            # Density proxy: how often price visited near those bands
            long_dens = float(np.mean(np.abs(arr - long_liq) / mid < 0.01))
            short_dens = float(np.mean(np.abs(arr - short_liq) / mid < 0.01))
            levels.append(
                {
                    "leverage": lev,
                    "long_liq": round(long_liq, 6),
                    "short_liq": round(short_liq, 6),
                    "long_density": round(long_dens, 4),
                    "short_density": round(short_dens, 4),
                }
            )
        self._liq_levels[symbol] = levels
        return levels

    def liquidation_heatmap(self, symbol: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "levels": self._liq_levels.get(symbol) or [],
            "ts": _utc_iso(),
        }

    # ------------------------------------------------------------------
    # Market regime classifier (ADX / ATR driven)
    # ------------------------------------------------------------------
    def classify_regime(self, df: pd.DataFrame) -> dict[str, Any]:
        if df is None or len(df) < 30:
            return {"label": "UNKNOWN", "adx": 0.0, "atr_pct": 0.0}
        work = df.copy()
        high = work["high"].astype(float)
        low = work["low"].astype(float)
        close = work["close"].astype(float)
        plus_dm = high.diff().clip(lower=0)
        minus_dm = (-low.diff()).clip(lower=0)
        tr = pd.concat(
            [
                (high - low),
                (high - close.shift()).abs(),
                (low - close.shift()).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = tr.rolling(14).mean()
        atr_pct = float((atr.iloc[-1] / close.iloc[-1]) * 100) if atr.iloc[-1] == atr.iloc[-1] else 0.0
        # Simplified DX
        plus_di = 100 * (plus_dm.rolling(14).mean() / (atr + 1e-12))
        minus_di = 100 * (minus_dm.rolling(14).mean() / (atr + 1e-12))
        dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-12)).rolling(14).mean()
        adx = float(dx.iloc[-1]) if dx.iloc[-1] == dx.iloc[-1] else 0.0
        if adx >= 25 and atr_pct >= 1.2:
            label = "TRENDING_VOLATILE"
        elif adx >= 25:
            label = "TRENDING"
        elif atr_pct >= 1.5:
            label = "RANGE_VOLATILE"
        else:
            label = "RANGE_QUIET"
        out = {
            "label": label,
            "adx": round(adx, 2),
            "atr_pct": round(atr_pct, 3),
            "plus_di": round(float(plus_di.iloc[-1] or 0), 2),
            "minus_di": round(float(minus_di.iloc[-1] or 0), 2),
            "ts": _utc_iso(),
        }
        self._last_regime = out
        return out

    # ------------------------------------------------------------------
    # 5% max daily drawdown circuit breaker
    # ------------------------------------------------------------------
    def update_circuit_breaker(self, equity: float) -> dict[str, Any]:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._day_key != day:
            self._day_key = day
            self._day_start_equity = float(equity)
            self._breaker_tripped = False
            self._breaker_reason = None
        start = float(self._day_start_equity or equity)
        dd = 0.0 if start <= 0 else (start - float(equity)) / start
        if dd >= MAX_DAILY_DRAWDOWN:
            self._breaker_tripped = True
            self._breaker_reason = f"Daily drawdown {dd*100:.2f}% >= {MAX_DAILY_DRAWDOWN*100:.0f}%"
        return {
            "tripped": self._breaker_tripped,
            "daily_drawdown_pct": round(dd * 100, 3),
            "max_allowed_pct": MAX_DAILY_DRAWDOWN * 100,
            "day_start_equity": round(start, 4),
            "equity": round(float(equity), 4),
            "reason": self._breaker_reason,
            "ts": _utc_iso(),
        }

    def trading_allowed(self) -> bool:
        return not self._breaker_tripped

    def snapshot(self, symbol: str = "BTC/USDT") -> dict[str, Any]:
        tox = self.toxicity_label(symbol)
        return {
            "vpin": tox,
            "regime": self._last_regime,
            "liquidation": self.liquidation_heatmap(symbol),
            "circuit_breaker": {
                "tripped": self._breaker_tripped,
                "reason": self._breaker_reason,
                "max_daily_drawdown_pct": MAX_DAILY_DRAWDOWN * 100,
            },
            "rl": self.rl_policy(self.regime_state_key(
                str(self._last_regime.get("label") or "UNKNOWN"),
                tox["label"],
                "NEUTRAL",
            )),
            "ts": _utc_iso(),
        }


quantum_engine = QuantumEngine()
