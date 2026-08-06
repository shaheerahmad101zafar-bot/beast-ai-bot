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
