"""
Beast AI Trading Bot — Quantitative Signal Strategy Engine

Multi-indicator confluence signals (RSI, EMA crossover, MACD histogram)
plus news-sentiment filter, with ATR-based stop-loss / take-profit levels.
"""

from __future__ import annotations

from typing import Any, Literal

import pandas as pd

import config

SignalType = Literal["BUY", "SELL", "HOLD"]

# ATR multipliers preserve ~1:2 risk/reward (mirrors config SL/TP ratio)
ATR_SL_MULTIPLIER: float = 1.5
ATR_TP_MULTIPLIER: float = 3.0

RSI_OVERSOLD: float = 30.0
RSI_OVERBOUGHT: float = 70.0


class SignalGenerator:
    """Generate BUY / SELL / HOLD signals from an indicator-enriched OHLCV DataFrame."""

    def __init__(
        self,
        atr_sl_mult: float = ATR_SL_MULTIPLIER,
        atr_tp_mult: float = ATR_TP_MULTIPLIER,
        rsi_oversold: float = RSI_OVERSOLD,
        rsi_overbought: float = RSI_OVERBOUGHT,
        sentiment_buy_min: float = config.SENTIMENT_BUY_MIN,
        sentiment_sell_max: float = config.SENTIMENT_SELL_MAX,
    ) -> None:
        self.atr_sl_mult = atr_sl_mult
        self.atr_tp_mult = atr_tp_mult
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.sentiment_buy_min = sentiment_buy_min
        self.sentiment_sell_max = sentiment_sell_max

    def generate(
        self,
        df: pd.DataFrame,
        symbol: str | None = None,
        sentiment_score: float | None = None,
    ) -> dict[str, Any]:
        """
        Ingest enriched OHLCV DataFrame and return a signal dict.

        Expected columns: close, rsi, ema_20, ema_50, macd_hist, atr
        Optional sentiment_score (0-100) acts as a confluence gate.
        """
        required = {"close", "rsi", "ema_20", "ema_50", "macd_hist", "atr"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"DataFrame missing required columns: {sorted(missing)}")
        if len(df) < 2:
            raise ValueError("DataFrame requires at least 2 rows for crossover detection")

        latest = df.iloc[-1]
        prev = df.iloc[-2]

        entry_price = float(latest["close"])
        rsi = float(latest["rsi"])
        atr = float(latest["atr"])
        macd_hist = float(latest["macd_hist"])
        ema_20 = float(latest["ema_20"])
        ema_50 = float(latest["ema_50"])
        prev_ema_20 = float(prev["ema_20"])
        prev_ema_50 = float(prev["ema_50"])

        bullish_cross = prev_ema_20 <= prev_ema_50 and ema_20 > ema_50
        bearish_cross = prev_ema_20 >= prev_ema_50 and ema_20 < ema_50

        # BUY: RSI < 30 OR (EMA20 crosses above EMA50 AND MACD hist > 0)
        rsi_buy = rsi < self.rsi_oversold
        trend_buy = bullish_cross and macd_hist > 0
        buy_triggered = rsi_buy or trend_buy

        # SELL: RSI > 70 OR (EMA20 crosses below EMA50 AND MACD hist < 0)
        rsi_sell = rsi > self.rsi_overbought
        trend_sell = bearish_cross and macd_hist < 0
        sell_triggered = rsi_sell or trend_sell

        if buy_triggered and not sell_triggered:
            signal: SignalType = "BUY"
        elif sell_triggered and not buy_triggered:
            signal = "SELL"
        else:
            signal = "HOLD"

        sentiment_blocked = False
        sentiment_reason: str | None = None
        if sentiment_score is not None and signal in {"BUY", "SELL"}:
            if signal == "BUY" and sentiment_score < self.sentiment_buy_min:
                sentiment_blocked = True
                sentiment_reason = (
                    f"Sentiment filter blocked BUY "
                    f"({sentiment_score:.1f} < {self.sentiment_buy_min:.1f} fear zone)"
                )
                signal = "HOLD"
            elif signal == "SELL" and sentiment_score > self.sentiment_sell_max:
                sentiment_blocked = True
                sentiment_reason = (
                    f"Sentiment filter blocked SELL "
                    f"({sentiment_score:.1f} > {self.sentiment_sell_max:.1f} greed zone)"
                )
                signal = "HOLD"

        confidence = self._confidence_score(
            signal=signal,
            rsi=rsi,
            rsi_buy=rsi_buy,
            rsi_sell=rsi_sell,
            trend_buy=trend_buy,
            trend_sell=trend_sell,
            bullish_cross=bullish_cross,
            bearish_cross=bearish_cross,
            macd_hist=macd_hist,
            ema_20=ema_20,
            ema_50=ema_50,
            sentiment_score=sentiment_score,
            sentiment_blocked=sentiment_blocked,
        )

        stop_loss_price, take_profit_price = self._atr_levels(
            signal=signal,
            entry_price=entry_price,
            atr=atr,
        )

        reasons = self._reasons(
            signal=signal,
            rsi_buy=rsi_buy,
            rsi_sell=rsi_sell,
            trend_buy=trend_buy,
            trend_sell=trend_sell,
        )
        if sentiment_reason:
            reasons.append(sentiment_reason)

        return {
            "symbol": symbol,
            "signal": signal,
            "confidence_score": confidence,
            "entry_price": round(entry_price, 8),
            "stop_loss_price": round(stop_loss_price, 8),
            "take_profit_price": round(take_profit_price, 8),
            "atr": round(atr, 8),
            "rsi": round(rsi, 4),
            "macd_hist": round(macd_hist, 8),
            "ema_20": round(ema_20, 8),
            "ema_50": round(ema_50, 8),
            "bullish_cross": bullish_cross,
            "bearish_cross": bearish_cross,
            "sentiment_score": None if sentiment_score is None else round(float(sentiment_score), 2),
            "sentiment_blocked": sentiment_blocked,
            "reasons": reasons,
        }

    def _atr_levels(
        self,
        signal: SignalType,
        entry_price: float,
        atr: float,
    ) -> tuple[float, float]:
        """ATR-based SL/TP. HOLD uses long-side scaffolding for planning."""
        sl_dist = atr * self.atr_sl_mult
        tp_dist = atr * self.atr_tp_mult

        if atr <= 0 or atr != atr:  # NaN guard
            sl_dist = entry_price * config.DEFAULT_STOP_LOSS
            tp_dist = entry_price * config.DEFAULT_TAKE_PROFIT

        if signal == "SELL":
            return entry_price + sl_dist, entry_price - tp_dist
        return entry_price - sl_dist, entry_price + tp_dist

    def _confidence_score(
        self,
        signal: SignalType,
        rsi: float,
        rsi_buy: bool,
        rsi_sell: bool,
        trend_buy: bool,
        trend_sell: bool,
        bullish_cross: bool,
        bearish_cross: bool,
        macd_hist: float,
        ema_20: float,
        ema_50: float,
        sentiment_score: float | None,
        sentiment_blocked: bool,
    ) -> float:
        """Map confluence strength to a 0-100 confidence score."""
        if sentiment_blocked:
            return 25.0

        if signal == "BUY":
            score = 45.0
            if rsi_buy:
                score += min(25.0, (30.0 - rsi) * 1.25)
            if trend_buy:
                score += 25.0
            elif bullish_cross:
                score += 10.0
            if macd_hist > 0:
                score += 10.0
            if ema_20 > ema_50:
                score += 5.0
            if sentiment_score is not None and sentiment_score >= 55:
                score += 8.0
        elif signal == "SELL":
            score = 45.0
            if rsi_sell:
                score += min(25.0, (rsi - 70.0) * 1.25)
            if trend_sell:
                score += 25.0
            elif bearish_cross:
                score += 10.0
            if macd_hist < 0:
                score += 10.0
            if ema_20 < ema_50:
                score += 5.0
            if sentiment_score is not None and sentiment_score <= 45:
                score += 8.0
        else:
            score = 20.0
            if 40.0 <= rsi <= 60.0:
                score += 15.0
            if macd_hist > 0 and ema_20 > ema_50:
                score += 10.0
            elif macd_hist < 0 and ema_20 < ema_50:
                score += 10.0
            if rsi_buy and rsi_sell:
                score = 10.0

        return round(max(0.0, min(100.0, score)), 2)

    @staticmethod
    def _reasons(
        signal: SignalType,
        rsi_buy: bool,
        rsi_sell: bool,
        trend_buy: bool,
        trend_sell: bool,
    ) -> list[str]:
        reasons: list[str] = []
        if signal == "BUY":
            if rsi_buy:
                reasons.append("RSI oversold (<30)")
            if trend_buy:
                reasons.append("EMA20 crossed above EMA50 with MACD hist > 0")
        elif signal == "SELL":
            if rsi_sell:
                reasons.append("RSI overbought (>70)")
            if trend_sell:
                reasons.append("EMA20 crossed below EMA50 with MACD hist < 0")
        else:
            reasons.append("Mixed / insufficient confluence")
        return reasons
