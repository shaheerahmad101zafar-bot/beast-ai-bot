"""
Coin-specific real-world news fetcher with sentiment/impact tags.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import feedparser

from sentiment_engine import score_headline


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


COIN_ALIASES: dict[str, list[str]] = {
    "BTC": ["bitcoin", "btc"],
    "ETH": ["ethereum", "eth"],
    "SOL": ["solana", "sol"],
    "XRP": ["xrp", "ripple"],
    "DOGE": ["dogecoin", "doge"],
}


class CoinNewsFetcher:
    def __init__(self) -> None:
        self.feeds = [
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            "https://cointelegraph.com/rss",
            "https://news.treeofalpha.com/rss",
        ]

    def for_symbol(self, symbol: str, limit: int = 12) -> dict[str, Any]:
        base = str(symbol or "BTC").upper().replace("/USDT", "").replace("USDT", "")
        aliases = COIN_ALIASES.get(base, [base.lower()])
        items: list[dict[str, Any]] = []
        for feed in self.feeds:
            try:
                parsed = feedparser.parse(feed)
            except Exception:
                continue
            for entry in parsed.entries or []:
                title = str(getattr(entry, "title", "") or "")
                summary = str(getattr(entry, "summary", "") or "")
                blob = f"{title} {summary}".lower()
                if not any(alias in blob for alias in aliases):
                    continue
                raw = score_headline(blob)
                badge = "Bullish" if raw > 0.4 else ("Bearish" if raw < -0.4 else "Caution")
                items.append(
                    {
                        "symbol": base,
                        "title": title,
                        "summary": summary[:260],
                        "link": str(getattr(entry, "link", "") or ""),
                        "published": str(getattr(entry, "published", "") or ""),
                        "source": feed,
                        "impact_score": round(min(100.0, abs(raw) * 28.0 + 12.0), 2),
                        "badge": badge,
                        "raw_score": round(raw, 3),
                    }
                )
        items.sort(key=lambda row: float(row["impact_score"]), reverse=True)
        return {"ok": True, "symbol": base, "items": items[:limit], "updated_at": _utc_now()}


news_fetcher = CoinNewsFetcher()
