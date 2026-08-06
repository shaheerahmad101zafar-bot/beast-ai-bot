"""
Beast AI — Universe seed + Binance Futures exchangeInfo loader (200+ USDT pairs).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from fast_json import loads
from network_tuning import apply_global_socket_tuning

apply_global_socket_tuning()

logger = logging.getLogger("beast.scanner")

# Top liquid Binance USDT-M perpetual bases (display as BASE/USDT).
TOP_50_USDT_PAIRS: list[str] = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "BNB/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "MATIC/USDT",
    "DOT/USDT",
    "NEAR/USDT",
    "SHIB/USDT",
    "PEPE/USDT",
    "SUI/USDT",
    "APT/USDT",
    "FET/USDT",
    "ARB/USDT",
    "OP/USDT",
    "UNI/USDT",
    "ATOM/USDT",
    "LTC/USDT",
    "TRX/USDT",
    "TON/USDT",
    "INJ/USDT",
    "RENDER/USDT",
    "FIL/USDT",
    "AAVE/USDT",
    "MKR/USDT",
    "CRV/USDT",
    "WLD/USDT",
    "SEI/USDT",
    "TIA/USDT",
    "ORDI/USDT",
    "WIF/USDT",
    "BONK/USDT",
    "FLOKI/USDT",
    "ICP/USDT",
    "HBAR/USDT",
    "ALGO/USDT",
    "VET/USDT",
    "GRT/USDT",
    "STX/USDT",
    "IMX/USDT",
    "RUNE/USDT",
    "ENS/USDT",
    "LDO/USDT",
    "PYTH/USDT",
    "JUP/USDT",
    "ONDO/USDT",
]

BINANCE_FAPI_EXCHANGE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
BINANCE_FAPI_TICKER_24H = "https://fapi.binance.com/fapi/v1/ticker/24hr"
HTTP = requests.Session()
_RETRY_STATUSES = {429, 500, 502, 503, 504}


def _get_with_backoff(url: str, *, timeout: float = 20.0, label: str = "binance") -> requests.Response:
    """Exponential backoff for Binance HTTP 500/502/504 and rate-limit drops."""
    delays = (0.4, 0.9, 1.8, 3.5, 6.0)
    last_exc: Exception | None = None
    for attempt, delay in enumerate(delays):
        try:
            resp = HTTP.get(url, timeout=timeout)
            if resp.status_code in _RETRY_STATUSES:
                raise requests.HTTPError(
                    f"{label} HTTP {resp.status_code}",
                    response=resp,
                )
            resp.raise_for_status()
            return resp
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning(
                "Binance REST %s attempt %s/%s failed: %s — backoff %.1fs",
                label,
                attempt + 1,
                len(delays),
                exc,
                delay,
            )
            if attempt >= len(delays) - 1:
                break
            time.sleep(delay)
    assert last_exc is not None
    raise last_exc


def seed_pair_rows() -> list[dict[str, Any]]:
    """Build scanner-compatible pair dicts for the seeded universe."""
    rows: list[dict[str, Any]] = []
    for i, symbol in enumerate(TOP_50_USDT_PAIRS):
        base = symbol.split("/")[0]
        rows.append(
            {
                "symbol": symbol,
                "ccxt_symbol": f"{symbol}:USDT",
                "base": base,
                "quote": "USDT",
                "quote_volume": float(50_000_000 - i * 100_000),
                "last": 0.0,
                "percentage": 0.0,
                "info_type": "seed",
            }
        )
    return rows


def fetch_all_usdt_futures_pairs(limit: int = 250) -> list[dict[str, Any]]:
    """
    Dynamically load USDT-M perpetual symbols from Binance /fapi/v1/exchangeInfo
    and enrich with 24h quote volume when available.
    """
    info = _get_with_backoff(BINANCE_FAPI_EXCHANGE_INFO, timeout=20, label="exchangeInfo")
    payload = loads(info.content)
    symbols_meta = payload.get("symbols") or []

    volume_map: dict[str, dict[str, float]] = {}
    try:
        tickers = _get_with_backoff(BINANCE_FAPI_TICKER_24H, timeout=20, label="ticker24h")
        for t in loads(tickers.content) or []:
            sym = str(t.get("symbol") or "")
            volume_map[sym] = {
                "quote_volume": float(t.get("quoteVolume") or 0),
                "last": float(t.get("lastPrice") or 0),
                "percentage": float(t.get("priceChangePercent") or 0),
            }
    except Exception:
        volume_map = {}

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in symbols_meta:
        if str(m.get("contractType") or "").upper() != "PERPETUAL":
            continue
        if str(m.get("quoteAsset") or "").upper() != "USDT":
            continue
        if str(m.get("status") or "").upper() != "TRADING":
            continue
        raw = str(m.get("symbol") or "")
        base = str(m.get("baseAsset") or "")
        if not raw or not base or base in seen:
            continue
        seen.add(base)
        display = f"{base}/USDT"
        stats = volume_map.get(raw) or {}
        rows.append(
            {
                "symbol": display,
                "ccxt_symbol": f"{display}:USDT",
                "base": base,
                "quote": "USDT",
                "quote_volume": float(stats.get("quote_volume") or 0),
                "last": float(stats.get("last") or 0),
                "percentage": float(stats.get("percentage") or 0),
                "info_type": "fapi_exchangeInfo",
                "binance_symbol": raw,
            }
        )

    rows.sort(key=lambda r: r.get("quote_volume") or 0, reverse=True)
    # Ensure curated seeds remain present near the top if missing from feed
    have = {r["symbol"].upper() for r in rows}
    for seed in seed_pair_rows():
        if seed["symbol"].upper() not in have:
            rows.append(seed)
    return rows[: max(1, limit)]


def _ema(series: list[float], window: int) -> float:
    if not series:
        return 0.0
    alpha = 2.0 / (window + 1.0)
    val = float(series[0])
    for x in series[1:]:
        val = alpha * float(x) + (1.0 - alpha) * val
    return val


def compute_mtf_confluence(
    df_1m: Any,
    df_5m: Any,
    df_15m: Any,
    *,
    signal: str = "HOLD",
) -> dict[str, Any]:
    """
    Multi-timeframe confluence:
      - 1m order-flow imbalance (volume-signed proxy)
      - 5m volatility profile (ATR% / range compression)
      - 15m MA trend alignment (EMA20 vs EMA50)
    Rejects wick/false-breakout scalp entries when frames disagree.
    """
    try:
        import pandas as pd
    except Exception:  # noqa: BLE001
        return {"ok": False, "aligned": False, "detail": "pandas unavailable"}

    def _frame_ok(df: Any) -> bool:
        return isinstance(df, pd.DataFrame) and not df.empty and len(df) >= 25

    if not (_frame_ok(df_1m) and _frame_ok(df_5m) and _frame_ok(df_15m)):
        return {"ok": False, "aligned": False, "detail": "insufficient_mtf_bars"}

    # --- 1m order-flow imbalance ---
    c1 = df_1m["close"].astype(float)
    v1 = df_1m["volume"].astype(float) if "volume" in df_1m.columns else c1 * 0 + 1.0
    signed = ((c1.diff().fillna(0.0) > 0).astype(float) * 2 - 1.0) * v1
    buy_vol = float(signed.clip(lower=0).tail(20).sum())
    sell_vol = float((-signed.clip(upper=0)).tail(20).sum())
    flow_den = buy_vol + sell_vol + 1e-12
    flow_imbalance = (buy_vol - sell_vol) / flow_den

    # --- 5m volatility profile ---
    c5 = df_5m["close"].astype(float)
    h5 = df_5m["high"].astype(float)
    l5 = df_5m["low"].astype(float)
    atr5 = float(((h5 - l5).tail(14)).mean())
    atr5_pct = atr5 / max(float(c5.iloc[-1]), 1e-12)
    range_now = float(h5.iloc[-1] - l5.iloc[-1]) / max(float(c5.iloc[-1]), 1e-12)
    vol_expanding = range_now >= atr5_pct * 0.85

    # --- 15m MA trend ---
    c15 = [float(x) for x in df_15m["close"].astype(float).tolist()]
    ema20 = _ema(c15[-60:], 20)
    ema50 = _ema(c15[-80:], 50)
    trend = "UP" if ema20 > ema50 else ("DOWN" if ema20 < ema50 else "FLAT")
    trend_slope = (ema20 - ema50) / max(abs(ema50), 1e-12)

    sig = str(signal or "HOLD").upper()
    flow_ok = True
    trend_ok = True
    vol_ok = atr5_pct < 0.045  # reject chaotic 5m expansion spikes as wick traps
    if sig == "BUY":
        flow_ok = flow_imbalance >= -0.05
        trend_ok = trend in {"UP", "FLAT"} and trend_slope > -0.002
    elif sig == "SELL":
        flow_ok = flow_imbalance <= 0.05
        trend_ok = trend in {"DOWN", "FLAT"} and trend_slope < 0.002

    strong = False
    if sig == "BUY":
        strong = flow_imbalance >= 0.12 and trend == "UP" and vol_expanding and vol_ok
    elif sig == "SELL":
        strong = flow_imbalance <= -0.12 and trend == "DOWN" and vol_expanding and vol_ok

    aligned = bool(flow_ok and trend_ok and vol_ok and sig in {"BUY", "SELL"})
    ok = aligned if sig in {"BUY", "SELL"} else True

    return {
        "ok": ok,
        "aligned": aligned,
        "strong": strong,
        "flow_imbalance": round(flow_imbalance, 4),
        "atr5_pct": round(atr5_pct * 100.0, 4),
        "vol_expanding": bool(vol_expanding),
        "trend_15m": trend,
        "trend_slope": round(trend_slope, 6),
        "ema20_15m": round(ema20, 8),
        "ema50_15m": round(ema50, 8),
        "detail": "pass" if ok else "mtf_divergence_or_wick_risk",
    }
