"""
Beast AI — Full Trading Engine

Multi-indicator confluence (RSI + MACD + Volume + OI proxy) with
anti-wick divergence protection, wired to quantum risk gates.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import config
from quantum_engine import quantum_engine
from strategy import SignalGenerator


class TradingEngine:
    """Confluence signal engine with wick/divergence filters."""

    def __init__(self) -> None:
        self.signals = SignalGenerator()

    @staticmethod
    def _build_reasoning(
        final: str,
        votes: dict[str, int],
        *,
        regime: dict[str, Any],
        wick: dict[str, Any],
        sentiment_score: float | None,
    ) -> str:
        if final == "HOLD":
            return "No strong AI confluence edge detected."
        parts: list[str] = []
        if votes.get("rsi", 0) > 0:
            parts.append("RSI oversold rebound")
        elif votes.get("rsi", 0) < 0:
            parts.append("RSI overbought fade")
        if votes.get("macd", 0) > 0:
            parts.append("MACD momentum turned positive")
        elif votes.get("macd", 0) < 0:
            parts.append("MACD momentum rolled negative")
        if votes.get("volume", 0) > 0:
            parts.append("volume expansion confirmed move")
        if votes.get("oi", 0) > 0:
            parts.append("positioning build supported continuation")
        elif votes.get("oi", 0) < 0:
            parts.append("positioning unwind supported reversal")
        if sentiment_score is not None:
            if sentiment_score >= 60:
                parts.append("positive news tone")
            elif sentiment_score <= 40:
                parts.append("defensive news tone")
        if regime.get("label"):
            parts.append(f"regime {regime['label'].replace('_', ' ').title()}")
        if wick.get("ok"):
            parts.append("anti-wick filter passed")
        return " + ".join(parts[:5]) or "AI confluence aligned across momentum, volume, and risk filters."

    def _volume_score(self, df: pd.DataFrame) -> float:
        if "volume" not in df.columns or len(df) < 20:
            return 0.5
        vol = df["volume"].astype(float)
        ma = vol.rolling(20).mean().iloc[-1]
        last = float(vol.iloc[-1])
        if not ma or ma != ma or ma <= 0:
            return 0.5
        ratio = last / float(ma)
        return float(min(1.0, max(0.0, (ratio - 0.5) / 1.5)))

    def _oi_proxy(self, df: pd.DataFrame) -> float:
        """
        Open-interest proxy: rising range expansion + volume = positioning build.
        Returns 0..1 bullish positioning bias.
        """
        if len(df) < 30:
            return 0.5
        close = df["close"].astype(float)
        high = df["high"].astype(float)
        low = df["low"].astype(float)
        rng = (high - low) / close.replace(0, np.nan)
        slope = float(rng.tail(10).mean() - rng.tail(30).mean())
        return float(min(1.0, max(0.0, 0.5 + slope * 40)))

    def _anti_wick_ok(self, df: pd.DataFrame, direction: str) -> dict[str, Any]:
        """Reject entries that pierce liquidity with oversized wicks (stop-hunt)."""
        row = df.iloc[-1]
        o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
        body = abs(c - o) + 1e-12
        upper = h - max(c, o)
        lower = min(c, o) - l
        upper_ratio = upper / body
        lower_ratio = lower / body
        # Divergence: price extreme vs RSI
        rsi = float(row["rsi"]) if "rsi" in df.columns else 50.0
        reject = False
        reason = ""
        if direction == "BUY" and lower_ratio > 2.8 and rsi > 40:
            reject = True
            reason = "long_lower_wick_trap"
        if direction == "SELL" and upper_ratio > 2.8 and rsi < 60:
            reject = True
            reason = "short_upper_wick_trap"
        # RSI divergence vs last 5 bars
        if len(df) >= 6 and "rsi" in df.columns:
            closes = df["close"].astype(float).tail(6)
            rsis = df["rsi"].astype(float).tail(6)
            if direction == "BUY" and closes.iloc[-1] < closes.min() and rsis.iloc[-1] > rsis.min():
                # bullish divergence — allow
                pass
            elif direction == "BUY" and closes.iloc[-1] <= closes.iloc[-2] and rsis.iloc[-1] < rsis.iloc[-2] - 5:
                reject = True
                reason = reason or "bearish_rsi_divergence"
            if direction == "SELL" and closes.iloc[-1] > closes.max() and rsis.iloc[-1] < rsis.max():
                pass
            elif direction == "SELL" and closes.iloc[-1] >= closes.iloc[-2] and rsis.iloc[-1] > rsis.iloc[-2] + 5:
                reject = True
                reason = reason or "bullish_rsi_divergence"
        return {
            "ok": not reject,
            "upper_wick_ratio": round(upper_ratio, 3),
            "lower_wick_ratio": round(lower_ratio, 3),
            "reason": reason or "pass",
        }

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        sentiment_score: float | None = None,
        equity: float | None = None,
    ) -> dict[str, Any]:
        if equity is not None:
            breaker = quantum_engine.update_circuit_breaker(equity)
            if breaker["tripped"]:
                last = float(df["close"].iloc[-1]) if len(df) else 0.0
                return {
                    "symbol": symbol,
                    "signal": "HOLD",
                    "confidence_score": 0.0,
                    "entry_price": last,
                    "stop_loss_price": last,
                    "take_profit_price": last,
                    "atr": 0.0,
                    "confluence": {},
                    "blocked_by": "circuit_breaker",
                    "circuit_breaker": breaker,
                }

        base = self.signals.generate(df, symbol=symbol, sentiment_score=sentiment_score)
        regime = quantum_engine.classify_regime(df)
        mark = float(df["close"].iloc[-1])
        quantum_engine._price_hist[symbol].append(mark)
        quantum_engine.update_liquidation_heatmap(symbol, mark)

        rsi = float(df["rsi"].iloc[-1])
        macd_hist = float(df["macd_hist"].iloc[-1])
        vol_s = self._volume_score(df)
        oi_s = self._oi_proxy(df)

        votes = {
            "rsi": 1 if rsi < 35 else (-1 if rsi > 65 else 0),
            "macd": 1 if macd_hist > 0 else (-1 if macd_hist < 0 else 0),
            "volume": 1 if vol_s >= 0.55 else (-1 if vol_s <= 0.35 else 0),
            "oi": 1 if oi_s >= 0.58 else (-1 if oi_s <= 0.42 else 0),
        }
        score = sum(votes.values())
        if score >= 2:
            conf_signal = "BUY"
        elif score <= -2:
            conf_signal = "SELL"
        else:
            conf_signal = "HOLD"

        # Blend with classic strategy signal
        classic = str(base.get("signal") or "HOLD").upper()
        if classic == conf_signal and conf_signal != "HOLD":
            final = conf_signal
            conf = min(98.0, float(base.get("confidence_score") or 50) + 12)
        elif classic != "HOLD" and conf_signal == "HOLD":
            final = classic
            conf = float(base.get("confidence_score") or 50) * 0.85
        elif classic == "HOLD" and conf_signal != "HOLD":
            final = conf_signal
            conf = 55.0 + abs(score) * 8
        else:
            final = "HOLD"
            conf = max(float(base.get("confidence_score") or 0) * 0.5, 20.0)

        wick = self._anti_wick_ok(df, final) if final in {"BUY", "SELL"} else {"ok": True, "reason": "n/a"}
        if final in {"BUY", "SELL"} and not wick["ok"]:
            final = "HOLD"
            conf = min(conf, 25.0)

        if not quantum_engine.trading_allowed():
            final = "HOLD"
            conf = 0.0

        # RL observe light reward shaping from confluence alignment
        state = quantum_engine.regime_state_key(
            regime["label"],
            quantum_engine.toxicity_label(symbol)["label"],
            "UP" if votes["macd"] > 0 else "DOWN",
        )
        reward = 0.05 if classic == conf_signal and final != "HOLD" else -0.01
        quantum_engine.rl_observe(state, final if final != "HOLD" else "HOLD", reward, state)
        policy = quantum_engine.rl_policy(state)

        return {
            **base,
            "symbol": symbol,
            "signal": final,
            "confidence_score": round(float(conf), 2),
            "confluence": {
                "votes": votes,
                "score": score,
                "volume_score": round(vol_s, 3),
                "oi_proxy": round(oi_s, 3),
                "classic_signal": classic,
            },
            "anti_wick": wick,
            "regime": regime,
            "rl_policy": policy,
            "liquidation": quantum_engine.liquidation_heatmap(symbol),
            "vpin": quantum_engine.toxicity_label(symbol),
            "ai_reasoning": self._build_reasoning(
                final,
                votes,
                regime=regime,
                wick=wick,
                sentiment_score=sentiment_score,
            ),
        }


trading_engine = TradingEngine()
