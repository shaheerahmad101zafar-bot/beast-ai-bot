"""
Beast AI Trading Bot — Phase 8 Dynamic All-Crypto Futures Scanner

Fetches top USDT-M futures pairs by quote volume from Binance via CCXT
and runs strategy scans on watchlists or a global top-N universe.
"""

from __future__ import annotations

import time
from typing import Any

import ccxt

import config
from market_data import MarketDataEngine
from risk_manager import DEFAULT_ACCOUNT_BALANCE, RiskManager
from strategy import SignalGenerator
from sentiment_engine import sentiment_engine


class MarketScanner:
    """Universe discovery + multi-pair signal scanning."""

    def __init__(self, exchange_id: str = config.EXCHANGE_ID) -> None:
        self.exchange_id = exchange_id
        self._pairs_cache: list[dict[str, Any]] = []
        self._pairs_cached_at: float = 0.0
        self._market = MarketDataEngine(exchange_id=exchange_id)
        self._signals = SignalGenerator()

    def close(self) -> None:
        self._market.close()

    def fetch_top_usdt_pairs(
        self,
        limit: int = config.SCANNER_TOP_PAIRS,
        force: bool = False,
    ) -> list[dict[str, Any]]:
        now = time.time()
        if (
            not force
            and self._pairs_cache
            and (now - self._pairs_cached_at) < config.SCANNER_CACHE_SECONDS
        ):
            return self._pairs_cache[:limit]

        exchange_class = getattr(ccxt, self.exchange_id)
        exchange = exchange_class({"enableRateLimit": True, "options": {"defaultType": "future"}})
        try:
            markets = exchange.load_markets()
            tickers = exchange.fetch_tickers()
        finally:
            try:
                exchange.close()
            except Exception:
                pass

        rows: list[dict[str, Any]] = []
        for symbol, market in markets.items():
            if not market.get("active", True):
                continue
            # Prefer perpetual linear USDT swaps
            if not market.get("swap", False):
                continue
            settle = (market.get("settle") or "").upper()
            quote = (market.get("quote") or "").upper()
            if settle != "USDT" and quote != "USDT":
                continue
            if market.get("spot"):
                continue

            ticker = tickers.get(symbol) or {}
            qv = ticker.get("quoteVolume")
            if qv is None:
                last = float(ticker.get("last") or ticker.get("close") or 0.0)
                base_vol = float(ticker.get("baseVolume") or 0.0)
                qv = last * base_vol
            try:
                qv_f = float(qv or 0.0)
            except (TypeError, ValueError):
                qv_f = 0.0
            if qv_f <= 0:
                continue

            display = symbol.split(":")[0] if ":" in symbol else symbol
            rows.append(
                {
                    "symbol": display,
                    "ccxt_symbol": symbol,
                    "base": market.get("base"),
                    "quote": market.get("quote") or "USDT",
                    "quote_volume": round(qv_f, 2),
                    "last": float(ticker.get("last") or ticker.get("close") or 0.0),
                    "percentage": float(ticker.get("percentage") or 0.0),
                    "info_type": "swap",
                }
            )

        rows.sort(key=lambda r: r["quote_volume"], reverse=True)
        # De-duplicate by base asset keeping highest volume symbol
        seen_bases: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            base = str(row.get("base") or row["symbol"]).upper()
            if base in seen_bases:
                continue
            seen_bases.add(base)
            unique.append(row)

        self._pairs_cache = unique
        self._pairs_cached_at = now
        return unique[:limit]

    def list_symbols(self, limit: int = config.SCANNER_TOP_PAIRS) -> list[str]:
        return [p["symbol"] for p in self.fetch_top_usdt_pairs(limit=limit)]

    def resolve_ccxt_symbol(self, symbol: str) -> str:
        """Map display symbol (BTC/USDT) to cached CCXT market id when available."""
        s = symbol.strip()
        display = s.split(":")[0]
        for row in self._pairs_cache:
            if row["symbol"] == display or row.get("ccxt_symbol") == s:
                return str(row.get("ccxt_symbol") or row["symbol"])
        return s

    def scan_pairs(
        self,
        symbols: list[str],
        *,
        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
        timeframe: str = config.DEFAULT_TIMEFRAME,
    ) -> list[dict[str, Any]]:
        if not self._pairs_cache:
            self.fetch_top_usdt_pairs()
        sentiment = sentiment_engine.get_sentiment()
        sentiment_score = float(sentiment.get("score") or 50.0)
        risk = RiskManager(account_balance=max(account_balance, 1.0))
        results: list[dict[str, Any]] = []

        for symbol in symbols:
            display = symbol.split(":")[0]
            market_symbol = self.resolve_ccxt_symbol(symbol)
            try:
                df = self._market.get_market_snapshot(market_symbol, timeframe=timeframe)
                if df.empty:
                    continue
                signal = self._signals.generate(
                    df,
                    symbol=display,
                    sentiment_score=sentiment_score,
                )
                sized = risk.evaluate_trade(signal)
                results.append(
                    {
                        **signal,
                        **sized,
                        "symbol": display,
                        "candles": len(df),
                        "quote_volume": next(
                            (
                                p["quote_volume"]
                                for p in self._pairs_cache
                                if p["symbol"] == display
                            ),
                            None,
                        ),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "symbol": display,
                        "signal": "HOLD",
                        "confidence_score": 0.0,
                        "error": str(exc),
                    }
                )
        # Rank actionable signals first
        results.sort(
            key=lambda r: (
                0 if r.get("signal") in {"BUY", "SELL"} else 1,
                -float(r.get("confidence_score") or 0.0),
            )
        )
        return results

    def global_scan(
        self,
        limit: int = config.SCANNER_GLOBAL_DEFAULT,
        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
    ) -> dict[str, Any]:
        pairs = self.fetch_top_usdt_pairs(limit=max(limit, 1))
        symbols = [p["symbol"] for p in pairs[:limit]]
        scanned = self.scan_pairs(symbols, account_balance=account_balance)
        return {
            "mode": "global",
            "limit": limit,
            "universe_size": len(self._pairs_cache),
            "scanned": len(scanned),
            "results": scanned,
        }

    def watchlist_scan(
        self,
        watchlist: list[str],
        account_balance: float = DEFAULT_ACCOUNT_BALANCE,
    ) -> dict[str, Any]:
        # Ensure universe cache warm for volumes
        if not self._pairs_cache:
            self.fetch_top_usdt_pairs()
        scanned = self.scan_pairs(watchlist, account_balance=account_balance)
        return {
            "mode": "watchlist",
            "watchlist": watchlist,
            "scanned": len(scanned),
            "results": scanned,
        }


market_scanner = MarketScanner()
