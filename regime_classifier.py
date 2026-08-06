"""
Dynamic market regime auto-rotator.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


class RegimeClassifier:
    def classify(self, df: pd.DataFrame) -> dict[str, Any]:
        if df is None or len(df) < 30:
            return {"label": "UNKNOWN", "params": {}}
        close = df["close"].astype(float)
        atr = df["atr"].astype(float) if "atr" in df.columns else close.pct_change().abs().rolling(14).mean() * close
        atr_pct = float((atr.iloc[-1] / max(close.iloc[-1], 1e-9)) * 100)
        std20 = float(close.pct_change().rolling(20).std().iloc[-1] or 0.0)
        trend = float(abs(close.iloc[-1] / max(close.iloc[-20], 1e-9) - 1.0) * 100)
        if atr_pct >= 1.5 and std20 >= 0.018:
            label = "HIGH_VOL"
            params = {"rsi_buy": 30, "rsi_sell": 70, "macd_bias": 0.05}
        elif trend >= 2.0:
            label = "TRENDING"
            params = {"rsi_buy": 38, "rsi_sell": 62, "macd_bias": -0.02}
        elif std20 <= 0.007:
            label = "LOW_VOL_SQUEEZE"
            params = {"rsi_buy": 42, "rsi_sell": 58, "macd_bias": 0.0}
        else:
            label = "RANGING"
            params = {"rsi_buy": 33, "rsi_sell": 67, "macd_bias": 0.0}
        return {"label": label, "atr_pct": round(atr_pct, 3), "volatility": round(std20, 4), "params": params}


regime_classifier = RegimeClassifier()
