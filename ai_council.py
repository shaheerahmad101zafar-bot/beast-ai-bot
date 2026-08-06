"""
Three-agent AI decision council for trade consensus.
"""

from __future__ import annotations

from typing import Any


class AICouncil:
    @staticmethod
    def vote(
        signal: str,
        confidence: float,
        *,
        sentiment_score: float | None,
        regime: dict[str, Any],
        vpin: dict[str, Any],
        funding_rate: float,
        depth_guard: dict[str, Any],
    ) -> dict[str, Any]:
        if signal not in {"BUY", "SELL"}:
            return {
                "approved": False,
                "agreement": 0,
                "votes": {"quant": "HOLD", "sentiment": "HOLD", "risk": "HOLD"},
                "summary": "No actionable council vote.",
            }
        quant_vote = signal if confidence >= 55 else "HOLD"
        if sentiment_score is None:
            sentiment_vote = signal
        elif signal == "BUY":
            sentiment_vote = "BUY" if sentiment_score >= 45 else "HOLD"
        else:
            sentiment_vote = "SELL" if sentiment_score <= 55 else "HOLD"
        toxic = str(vpin.get("label") or "").lower() in {"toxic", "elevated"}
        regime_label = str(regime.get("label") or "").lower()
        risk_clear = depth_guard.get("ok") and abs(float(funding_rate)) < 0.0008 and not toxic and "chaotic" not in regime_label
        risk_vote = signal if risk_clear else "HOLD"
        votes = {"quant": quant_vote, "sentiment": sentiment_vote, "risk": risk_vote}
        agreement = sum(1 for v in votes.values() if v == signal)
        return {
            "approved": agreement >= 2,
            "agreement": agreement,
            "votes": votes,
            "summary": f"{agreement}/3 agents aligned for {signal}",
        }


ai_council = AICouncil()
