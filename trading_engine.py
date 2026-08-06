"""
Beast AI — Full Trading Engine

Multi-indicator confluence (RSI + MACD + Volume + OI proxy) with
anti-wick divergence protection, wired to quantum risk gates.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import requests
import time

from ai_council import ai_council
import config
from quantum_engine import quantum_engine
from regime_classifier import regime_classifier
from slippage_guard import slippage_guard
from strategy import SignalGenerator


class TradingEngine:
    """Confluence signal engine with wick/divergence filters."""

    def __init__(self) -> None:
        self.signals = SignalGenerator()
        self.runtime_params = {
            "rsi_buy": 35.0,
            "rsi_sell": 65.0,
            "atr_mult": 1.8,
            "macd_bias": 0.0,
        }

    def set_runtime_params(self, params: dict[str, float]) -> None:
        self.runtime_params.update({k: float(v) for k, v in params.items() if k in self.runtime_params})

    @staticmethod
    def _build_reasoning(
        final: str,
        votes: dict[str, int],
        *,
        regime: dict[str, Any],
        wick: dict[str, Any],
        sentiment_score: float | None,
        depth_guard: dict[str, Any] | None = None,
        volume_score: float | None = None,
        oi_proxy: float | None = None,
    ) -> str:
        if final == "HOLD":
            return "No strong AI confluence edge detected."
        parts: list[str] = []
        if votes.get("rsi", 0) > 0:
            parts.append("RSI oversold")
        elif votes.get("rsi", 0) < 0:
            parts.append("RSI overbought")
        if votes.get("macd", 0) > 0:
            parts.append("MACD hist +")
        elif votes.get("macd", 0) < 0:
            parts.append("MACD hist -")
        if volume_score is not None and volume_score >= 0.55:
            parts.append(f"Volume thrust {volume_score:+.2f}")
        elif votes.get("volume", 0) > 0:
            parts.append("Volume expansion")
        if oi_proxy is not None:
            delta = (float(oi_proxy) - 0.5) * 2.0
            if abs(delta) >= 0.15:
                parts.append(f"Order Book Delta {delta:+.2f}")
        elif votes.get("oi", 0) != 0:
            parts.append("OI positioning aligned")
        slip = float((depth_guard or {}).get("slippage_pct") or 0.0)
        if slip > 0:
            parts.append(f"Book spread {slip:.3f}%")
        if sentiment_score is not None:
            if sentiment_score >= 60:
                parts.append("Bullish news tone")
            elif sentiment_score <= 40:
                parts.append("Defensive news tone")
        if regime.get("label"):
            parts.append(f"Regime {str(regime['label']).replace('_', ' ').title()}")
        if wick.get("ok"):
            parts.append("Anti-wick OK")
        return " + ".join(parts[:5]) or "AI confluence aligned"

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

    @staticmethod
    def _binance_get(url: str, params: dict[str, Any] | None = None, timeout: float = 6.0) -> dict[str, Any]:
        """GET with exponential backoff on 429 / 5xx Binance errors."""
        delays = (0.35, 0.8, 1.6, 3.2)
        last_exc: Exception | None = None
        for attempt, delay in enumerate(delays):
            try:
                resp = requests.get(url, params=params or {}, timeout=timeout)
                if resp.status_code in {429, 500, 502, 503, 504}:
                    raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
                resp.raise_for_status()
                return resp.json() if resp.content else {}
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= len(delays) - 1:
                    break
                time.sleep(delay)
        if last_exc:
            raise last_exc
        return {}

    @staticmethod
    def _funding_rate(symbol: str) -> float:
        raw = symbol.replace("/", "")
        try:
            data = TradingEngine._binance_get(
                "https://fapi.binance.com/fapi/v1/premiumIndex",
                params={"symbol": raw},
                timeout=6,
            )
            return float(data.get("lastFundingRate") or 0.0)
        except Exception:
            return 0.0

    @staticmethod
    def _depth_ok(symbol: str, mark: float) -> dict[str, Any]:
        raw = symbol.replace("/", "")
        try:
            data = TradingEngine._binance_get(
                "https://fapi.binance.com/fapi/v1/depth",
                params={"symbol": raw, "limit": 5},
                timeout=6,
            )
            best_bid = float((data.get("bids") or [[mark, 0]])[0][0])
            best_ask = float((data.get("asks") or [[mark, 0]])[0][0])
            slippage_pct = abs(best_ask - best_bid) / max(mark, 1e-9) * 100
            return {"ok": slippage_pct < 0.05, "slippage_pct": round(slippage_pct, 4)}
        except Exception:
            return {"ok": True, "slippage_pct": 0.0}

    def evaluate(
        self,
        df: pd.DataFrame,
        *,
        symbol: str,
        sentiment_score: float | None = None,
        equity: float | None = None,
        mtf: dict[str, Any] | None = None,
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
        regime_rotation = regime_classifier.classify(df)
        if regime_rotation.get("params"):
            self.set_runtime_params(regime_rotation["params"])
        mark = float(df["close"].iloc[-1])
        quantum_engine._price_hist[symbol].append(mark)
        quantum_engine.update_liquidation_heatmap(symbol, mark)

        rsi = float(df["rsi"].iloc[-1])
        macd_hist = float(df["macd_hist"].iloc[-1]) - float(self.runtime_params.get("macd_bias") or 0.0)
        vol_s = self._volume_score(df)
        oi_s = self._oi_proxy(df)
        rsi_buy = float(self.runtime_params.get("rsi_buy") or 35.0)
        rsi_sell = float(self.runtime_params.get("rsi_sell") or 65.0)

        votes = {
            "rsi": 1 if rsi < rsi_buy else (-1 if rsi > rsi_sell else 0),
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

        funding_rate = self._funding_rate(symbol) if final in {"BUY", "SELL"} else 0.0
        depth_guard = self._depth_ok(symbol, mark) if final in {"BUY", "SELL"} else {"ok": True, "slippage_pct": 0.0}
        # Legacy soft filters (extreme funding)
        if final == "BUY" and funding_rate >= 0.0008:
            final = "HOLD"
            conf = 0.0
        if final == "SELL" and funding_rate <= -0.0008:
            final = "HOLD"
            conf = 0.0
        # Hard 0.05% funding bleed guard
        if final in {"BUY", "SELL"}:
            from risk_manager import portfolio_risk_guard

            bleed = portfolio_risk_guard.funding_bleed_guard(symbol, final, funding_rate)
            if not bleed.get("ok"):
                final = "HOLD"
                conf = 0.0
        else:
            bleed = {"ok": True, "detail": "n/a"}
        if final in {"BUY", "SELL"} and not depth_guard["ok"]:
            final = "HOLD"
            conf = 0.0

        # Multi-timeframe confluence gate (filters wick / false breakouts)
        mtf_info = mtf or {"ok": True, "aligned": True, "detail": "mtf_not_provided"}
        if final in {"BUY", "SELL"} and mtf_info.get("ok") is False:
            final = "HOLD"
            conf = min(conf, 18.0)

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
        council = ai_council.vote(
            final,
            conf,
            sentiment_score=sentiment_score,
            regime=regime,
            vpin=quantum_engine.toxicity_label(symbol),
            funding_rate=funding_rate,
            depth_guard=depth_guard,
        )
        if final in {"BUY", "SELL"} and not council["approved"]:
            final = "HOLD"
            conf = min(conf, 22.0)

        atr_val = float(base.get("atr") or (df["atr"].iloc[-1] if "atr" in df.columns else 0.0) or 0.0)
        atr_pct_frac = (atr_val / mark) if mark > 0 and atr_val > 0 else 0.0
        exec_slip = slippage_guard.volatility_slippage_pct(atr_pct=atr_pct_frac)

        # Short-horizon range as 1-minute volatility proxy from last few bars
        recent_range_pct = 0.0
        if len(df) >= 3 and mark > 0:
            hi = float(df["high"].tail(3).max())
            lo = float(df["low"].tail(3).min())
            recent_range_pct = max(0.0, (hi - lo) / mark)
        # Approximate 1m ATR from bar ATR scaled by sqrt of minutes in bar (default 60 for 1h)
        atr_1m = atr_val / (60.0 ** 0.5) if atr_val > 0 else 0.0

        return {
            **base,
            "symbol": symbol,
            "signal": final,
            "confidence_score": round(float(conf), 2),
            "atr": atr_val,
            "atr_1m": round(atr_1m, 8),
            "recent_range_pct": round(recent_range_pct, 6),
            "atr_pct_frac": round(atr_pct_frac, 6),
            "execution_slippage_pct": round(exec_slip, 6),
            "taker_fee_rate": float(config.FUTURES_FEE_RATE),
            "confluence": {
                "votes": votes,
                "score": score,
                "volume_score": round(vol_s, 3),
                "oi_proxy": round(oi_s, 3),
                "classic_signal": classic,
            },
            "anti_wick": wick,
            "regime": regime,
            "regime_rotation": regime_rotation,
            "rl_policy": policy,
            "liquidation": quantum_engine.liquidation_heatmap(symbol),
            "vpin": quantum_engine.toxicity_label(symbol),
            "funding_rate": round(funding_rate, 6),
            "funding_guard": bleed,
            "mtf": mtf_info,
            "depth_guard": depth_guard,
            "ai_council": council,
            "ai_reasoning": self._build_reasoning(
                final,
                votes,
                regime=regime,
                wick=wick,
                sentiment_score=sentiment_score,
                depth_guard=depth_guard,
                volume_score=vol_s,
                oi_proxy=oi_s,
            ),
        }


trading_engine = TradingEngine()
