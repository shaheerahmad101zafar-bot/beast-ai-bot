"""
Beast AI Trading Bot — Live Market Data Ingestion Engine

CCXT Binance Futures connector with OHLCV fetch and technical indicators
(RSI, EMA 20/50/200, ATR, MACD) via the `ta` library.
"""

from __future__ import annotations

import asyncio
from typing import Any

import ccxt
import ccxt.async_support as ccxt_async
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD
from ta.volatility import AverageTrueRange

import config


class MarketDataEngine:
    """Sync + async Binance USD-M Futures market data with indicator enrichment."""

    def __init__(
        self,
        exchange_id: str = config.EXCHANGE_ID,
        enable_rate_limit: bool = True,
    ) -> None:
        self.exchange_id = exchange_id
        self._enable_rate_limit = enable_rate_limit
        self._sync_exchange: ccxt.Exchange | None = None

    # ------------------------------------------------------------------
    # Exchange factories
    # ------------------------------------------------------------------
    def _create_sync_exchange(self) -> ccxt.Exchange:
        exchange_class = getattr(ccxt, self.exchange_id)
        return exchange_class(
            {
                "enableRateLimit": self._enable_rate_limit,
                "options": {"defaultType": "future"},
            }
        )

    def _create_async_exchange(self) -> ccxt_async.Exchange:
        exchange_class = getattr(ccxt_async, self.exchange_id)
        return exchange_class(
            {
                "enableRateLimit": self._enable_rate_limit,
                "options": {"defaultType": "future"},
            }
        )

    @property
    def sync_exchange(self) -> ccxt.Exchange:
        if self._sync_exchange is None:
            self._sync_exchange = self._create_sync_exchange()
        return self._sync_exchange

    def close(self) -> None:
        if self._sync_exchange is not None:
            self._sync_exchange.close()
            self._sync_exchange = None

    # ------------------------------------------------------------------
    # OHLCV fetch
    # ------------------------------------------------------------------
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = config.DEFAULT_TIMEFRAME,
        limit: int = config.DEFAULT_OHLCV_LIMIT,
    ) -> pd.DataFrame:
        """Fetch OHLCV synchronously and return a timestamp-indexed DataFrame."""
        raw = self.sync_exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self._ohlcv_to_dataframe(raw)

    async def fetch_ohlcv_async(
        self,
        symbol: str,
        timeframe: str = config.DEFAULT_TIMEFRAME,
        limit: int = config.DEFAULT_OHLCV_LIMIT,
    ) -> pd.DataFrame:
        """Fetch OHLCV asynchronously and return a timestamp-indexed DataFrame."""
        exchange = self._create_async_exchange()
        try:
            raw = await exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            return self._ohlcv_to_dataframe(raw)
        finally:
            await exchange.close()

    async def fetch_ohlcv_many_async(
        self,
        symbols: list[str],
        timeframe: str = config.DEFAULT_TIMEFRAME,
        limit: int = config.DEFAULT_OHLCV_LIMIT,
    ) -> dict[str, pd.DataFrame]:
        """Concurrent async OHLCV fetch for multiple symbols."""
        tasks = [
            self.fetch_ohlcv_async(symbol, timeframe=timeframe, limit=limit)
            for symbol in symbols
        ]
        frames = await asyncio.gather(*tasks)
        return dict(zip(symbols, frames, strict=True))

    # ------------------------------------------------------------------
    # Indicators
    # ------------------------------------------------------------------
    @staticmethod
    def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
        """
        Enrich OHLCV DataFrame with RSI(14), EMA(20/50/200), ATR(14), MACD.

        Expects columns: open, high, low, close, volume.
        """
        if df.empty:
            return df.copy()

        out = df.copy()
        close = out["close"]
        high = out["high"]
        low = out["low"]

        out["rsi"] = RSIIndicator(close=close, window=config.RSI_PERIOD).rsi()
        out["ema_20"] = EMAIndicator(close=close, window=config.EMA_FAST).ema_indicator()
        out["ema_50"] = EMAIndicator(close=close, window=config.EMA_MID).ema_indicator()
        out["ema_200"] = EMAIndicator(close=close, window=config.EMA_SLOW).ema_indicator()
        out["atr"] = AverageTrueRange(
            high=high,
            low=low,
            close=close,
            window=config.ATR_PERIOD,
        ).average_true_range()

        macd = MACD(
            close=close,
            window_slow=config.MACD_SLOW,
            window_fast=config.MACD_FAST,
            window_sign=config.MACD_SIGNAL,
        )
        out["macd"] = macd.macd()
        out["macd_signal"] = macd.macd_signal()
        out["macd_hist"] = macd.macd_diff()

        return out

    def get_market_snapshot(
        self,
        symbol: str,
        timeframe: str = config.DEFAULT_TIMEFRAME,
        limit: int = config.DEFAULT_OHLCV_LIMIT,
    ) -> pd.DataFrame:
        """Fetch OHLCV and return a fully indicator-enriched DataFrame."""
        ohlcv = self.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        return self.add_indicators(ohlcv)

    async def get_market_snapshot_async(
        self,
        symbol: str,
        timeframe: str = config.DEFAULT_TIMEFRAME,
        limit: int = config.DEFAULT_OHLCV_LIMIT,
    ) -> pd.DataFrame:
        """Async variant of get_market_snapshot."""
        ohlcv = await self.fetch_ohlcv_async(symbol, timeframe=timeframe, limit=limit)
        return self.add_indicators(ohlcv)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _ohlcv_to_dataframe(raw: list[list[Any]]) -> pd.DataFrame:
        df = pd.DataFrame(
            raw,
            columns=["timestamp", "open", "high", "low", "close", "volume"],
        )
        if df.empty:
            return df

        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df = df.astype(
            {
                "open": "float64",
                "high": "float64",
                "low": "float64",
                "close": "float64",
                "volume": "float64",
            }
        )
        df = df.set_index("timestamp")
        df.index.name = "timestamp"
        return df


def fetch_enriched_ohlcv(
    symbol: str,
    timeframe: str = config.DEFAULT_TIMEFRAME,
    limit: int = config.DEFAULT_OHLCV_LIMIT,
) -> pd.DataFrame:
    """Convenience wrapper: sync fetch + indicators, auto-closes exchange."""
    engine = MarketDataEngine()
    try:
        return engine.get_market_snapshot(symbol, timeframe=timeframe, limit=limit)
    finally:
        engine.close()
