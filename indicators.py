"""
C-backed vectorized indicator helpers via numpy/pandas ops.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, window: int) -> pd.Series:
    return series.astype(float).ewm(span=window, adjust=False).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    delta = series.astype(float).diff().fillna(0.0)
    gains = np.clip(delta.to_numpy(dtype=float), 0.0, None)
    losses = np.clip(-delta.to_numpy(dtype=float), 0.0, None)
    gain_s = pd.Series(gains, index=series.index).ewm(alpha=1 / window, adjust=False).mean()
    loss_s = pd.Series(losses, index=series.index).ewm(alpha=1 / window, adjust=False).mean()
    rs = gain_s / loss_s.replace(0.0, np.nan)
    out = 100.0 - (100.0 / (1.0 + rs))
    return out.fillna(50.0)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    h = high.astype(float)
    l = low.astype(float)
    c = close.astype(float)
    prev_close = c.shift(1)
    tr = np.maximum.reduce([
        (h - l).to_numpy(dtype=float),
        (h - prev_close).abs().to_numpy(dtype=float),
        (l - prev_close).abs().to_numpy(dtype=float),
    ])
    tr_s = pd.Series(tr, index=close.index)
    return tr_s.ewm(alpha=1 / window, adjust=False).mean()


def macd_hist(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd = fast_ema - slow_ema
    sig = macd.ewm(span=signal, adjust=False).mean()
    hist = macd - sig
    return macd, sig, hist
