"""
Beast AI Trading Bot — Phase 5 News & Sentiment Analytics Engine

Fetches public crypto RSS headlines and computes a 0-100 Market Sentiment Score
(0 = Extreme Fear, 100 = Extreme Greed / Bullish).
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

import feedparser
import requests

import config

BULLISH_KEYWORDS: dict[str, float] = {
    "surge": 2.0,
    "rally": 2.0,
    "bull": 1.5,
    "bullish": 2.5,
    "breakout": 2.0,
    "ath": 2.0,
    "all-time high": 2.5,
    "approval": 1.5,
    "etf inflow": 2.0,
    "inflows": 1.5,
    "adoption": 1.5,
    "partnership": 1.2,
    "record": 1.2,
    "soar": 2.0,
    "jump": 1.2,
    "gain": 1.0,
    "recovery": 1.3,
    "optimism": 1.5,
    "upgrade": 1.2,
    "institutional": 1.0,
}

BEARISH_KEYWORDS: dict[str, float] = {
    "crash": 2.5,
    "plunge": 2.2,
    "bear": 1.5,
    "bearish": 2.5,
    "hack": 2.5,
    "exploit": 2.2,
    "lawsuit": 1.8,
    "ban": 2.0,
    "sec": 1.0,
    "fraud": 2.5,
    "liquidation": 2.0,
    "sell-off": 2.0,
    "selloff": 2.0,
    "fear": 1.8,
    "panic": 2.2,
    "outflow": 1.8,
    "outflows": 1.8,
    "collapse": 2.5,
    "investigation": 1.5,
    "default": 2.0,
    "bankruptcy": 2.5,
    "dump": 1.8,
    "decline": 1.2,
    "drop": 1.0,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def score_headline(text: str) -> float:
    """Return raw sentiment polarity for one headline (-max..+max)."""
    blob = _normalize(text)
    score = 0.0
    for word, weight in BULLISH_KEYWORDS.items():
        if word in blob:
            score += weight
    for word, weight in BEARISH_KEYWORDS.items():
        if word in blob:
            score -= weight
    return score


class SentimentEngine:
    """RSS-driven crypto market sentiment scorer with in-memory cache."""

    def __init__(
        self,
        feeds: list[str] | None = None,
        cache_seconds: int = config.SENTIMENT_CACHE_SECONDS,
    ) -> None:
        self.feeds = list(feeds or config.CRYPTO_RSS_FEEDS)
        self.cache_seconds = int(cache_seconds)
        self._cached_at: float = 0.0
        self._snapshot: dict[str, Any] | None = None

    def get_sentiment(self, force_refresh: bool = False) -> dict[str, Any]:
        now = time.time()
        if (
            not force_refresh
            and self._snapshot is not None
            and (now - self._cached_at) < self.cache_seconds
        ):
            return dict(self._snapshot)

        headlines = self.fetch_headlines()
        snapshot = self._compute_score(headlines)
        self._snapshot = snapshot
        self._cached_at = now
        return dict(snapshot)

    def fetch_headlines(self, max_per_feed: int = 12) -> list[dict[str, str]]:
        items: list[dict[str, str]] = []
        headers = {"User-Agent": "BeastAITradingBot/5.0 (+localhost sentiment)"}

        for url in self.feeds:
            try:
                resp = requests.get(url, timeout=12, headers=headers)
                resp.raise_for_status()
                parsed = feedparser.parse(resp.content)
            except Exception:
                # Soft-fail individual feeds
                continue

            for entry in (parsed.entries or [])[:max_per_feed]:
                title = str(getattr(entry, "title", "") or "").strip()
                if not title:
                    continue
                summary = str(getattr(entry, "summary", "") or "")
                link = str(getattr(entry, "link", "") or "")
                items.append(
                    {
                        "title": title,
                        "summary": re.sub(r"<[^>]+>", "", summary)[:280],
                        "link": link,
                        "source": url,
                    }
                )

        # Deduplicate by title
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for item in items:
            key = _normalize(item["title"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique[:60]

    def _compute_score(self, headlines: list[dict[str, str]]) -> dict[str, Any]:
        if not headlines:
            # Neutral fallback when feeds unavailable
            return {
                "score": 50.0,
                "label": "Neutral",
                "headline_count": 0,
                "bullish_count": 0,
                "bearish_count": 0,
                "updated_at": _utc_now(),
                "headlines": [],
                "source": "fallback",
                "note": "No headlines fetched; defaulting to neutral 50",
            }

        scored: list[dict[str, Any]] = []
        raw_scores: list[float] = []
        for h in headlines:
            raw = score_headline(f"{h['title']} {h.get('summary', '')}")
            raw_scores.append(raw)
            tone = "bullish" if raw > 0.4 else "bearish" if raw < -0.4 else "neutral"
            scored.append({**h, "raw_score": round(raw, 3), "tone": tone})

        avg = sum(raw_scores) / len(raw_scores)
        # Map average polarity roughly from [-3, +3] -> [0, 100]
        mapped = 50.0 + (avg / 3.0) * 50.0
        score = round(max(0.0, min(100.0, mapped)), 2)

        bullish_count = sum(1 for s in scored if s["tone"] == "bullish")
        bearish_count = sum(1 for s in scored if s["tone"] == "bearish")

        return {
            "score": score,
            "label": self.label_for_score(score),
            "headline_count": len(scored),
            "bullish_count": bullish_count,
            "bearish_count": bearish_count,
            "avg_raw": round(avg, 4),
            "updated_at": _utc_now(),
            "headlines": scored[:15],
            "source": "rss",
            "note": None,
        }

    def get_news_feed(self, limit: int = 25) -> dict[str, Any]:
        """Real-time crypto news + market wire with AI sentiment badges."""
        sentiment = self.get_sentiment()
        headlines = list(sentiment.get("headlines") or [])[:limit]
        extra: list[dict[str, Any]] = []
        try:
            bn = feedparser.parse("https://news.treeofalpha.com/rss")
            for e in (bn.entries or [])[:12]:
                title = str(getattr(e, "title", "") or "")
                if not title:
                    continue
                raw = score_headline(title)
                badge = "Bullish" if raw > 0.4 else ("Bearish" if raw < -0.4 else "Neutral")
                extra.append(
                    {
                        "title": title,
                        "link": str(getattr(e, "link", "") or ""),
                        "published": str(getattr(e, "published", "") or ""),
                        "source": "market_wire",
                        "raw_score": round(raw, 3),
                        "badge": badge,
                        "tone": badge.lower(),
                    }
                )
        except Exception:
            extra = []

        merged = []
        for h in headlines:
            tone = str(h.get("tone") or "neutral")
            badge = "Bullish" if tone == "bullish" else ("Bearish" if tone == "bearish" else "Neutral")
            merged.append(
                {
                    "title": h.get("title") or h.get("summary") or "",
                    "link": h.get("link") or "",
                    "published": h.get("published") or "",
                    "source": h.get("source") or "rss",
                    "raw_score": h.get("raw_score"),
                    "badge": badge,
                    "tone": tone,
                }
            )
        merged.extend(extra)
        return {
            "ok": True,
            "sentiment_score": sentiment.get("score"),
            "sentiment_label": sentiment.get("label"),
            "items": merged[:limit],
            "updated_at": _utc_now(),
        }

    @staticmethod
    def label_for_score(score: float) -> str:
        if score < 20:
            return "Extreme Fear"
        if score < 40:
            return "Fear"
        if score <= 60:
            return "Neutral"
        if score <= 80:
            return "Greed"
        return "Extreme Greed"


# Process-wide singleton
sentiment_engine = SentimentEngine()
