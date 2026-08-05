"""
Beast AI — Curated top-50 Binance USDT futures seed universe.

Used to pre-populate the scanner dropdown / watchlist grid with zero
network latency before live CCXT volume ranking refreshes.
"""

from __future__ import annotations

from typing import Any

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
                # Pseudo volume rank so seeds sort in curated order until live refresh.
                "quote_volume": float(50_000_000 - i * 100_000),
                "last": 0.0,
                "percentage": 0.0,
                "info_type": "seed",
            }
        )
    return rows
