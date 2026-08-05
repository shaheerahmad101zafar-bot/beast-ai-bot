"""
Beast AI Trading Bot — Phase 5 Automated SEO Blog Generator

Produces daily SEO-optimized Markdown + HTML articles with JSON-LD schema,
meta descriptions, target keywords, internal SaaS links, and sitemap.xml.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import config

TOPIC_BANK: list[dict[str, Any]] = [
    {
        "keyword": "Best AI Futures Bot 2026",
        "slug": "best-ai-futures-bot-2026",
        "title": "Best AI Futures Bot 2026: How Beast AI Automates Binance Risk",
        "secondary": ["AI trading bot", "Binance futures automation", "crypto quant signals"],
    },
    {
        "keyword": "Binance Automated Risk Management",
        "slug": "binance-automated-risk-management",
        "title": "Binance Automated Risk Management with ATR Stops & Position Sizing",
        "secondary": ["futures risk management", "ATR stop loss", "leverage control"],
    },
    {
        "keyword": "How to Trade BTC Volatility",
        "slug": "how-to-trade-btc-volatility",
        "title": "How to Trade BTC Volatility Using AI Confluence Signals",
        "secondary": ["BTC volatility trading", "RSI MACD strategy", "crypto futures"],
    },
    {
        "keyword": "AI Crypto Trading Signals Explained",
        "slug": "ai-crypto-trading-signals-explained",
        "title": "AI Crypto Trading Signals Explained: RSI, EMA Cross & MACD",
        "secondary": ["trading confluence", "EMA crossover", "paper trading bot"],
    },
    {
        "keyword": "Paper Trading Crypto Futures Bot",
        "slug": "paper-trading-crypto-futures-bot",
        "title": "Paper Trading Crypto Futures: Test an AI Bot Before Going Live",
        "secondary": ["paper trading", "crypto SaaS", "futures simulator"],
    },
    {
        "keyword": "SOL ETH BTC Multi Asset Bot",
        "slug": "sol-eth-btc-multi-asset-bot",
        "title": "Multi-Asset AI Bot for SOL, ETH & BTC Futures in 2026",
        "secondary": ["multi asset trading", "SOL futures", "ETH bot"],
    },
]


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def _utc_date() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SEOBlogGenerator:
    """Template-driven daily SEO article factory for Beast AI."""

    def __init__(
        self,
        blog_dir: str | Path = config.BLOG_DIR,
        sitemap_path: str | Path = config.SITEMAP_PATH,
        site_base_url: str = config.SITE_BASE_URL,
        subscription_url: str = config.SAAS_SUBSCRIPTION_URL,
        brand: str = config.SEO_BRAND_NAME,
    ) -> None:
        self.blog_dir = Path(blog_dir)
        self.sitemap_path = Path(sitemap_path)
        self.site_base_url = site_base_url.rstrip("/")
        self.subscription_url = subscription_url
        self.brand = brand
        self.blog_dir.mkdir(parents=True, exist_ok=True)
        self.sitemap_path.parent.mkdir(parents=True, exist_ok=True)

    def generate_daily_article(self, force: bool = False) -> dict[str, Any]:
        """
        Generate (or return existing) SEO article for today's UTC date.
        Rotates topic bank by day-of-year.
        """
        today = _utc_date()
        topic = TOPIC_BANK[datetime.now(timezone.utc).timetuple().tm_yday % len(TOPIC_BANK)]
        slug = f"{today}-{topic['slug']}"
        md_path = self.blog_dir / f"{slug}.md"
        html_path = self.blog_dir / f"{slug}.html"
        meta_path = self.blog_dir / f"{slug}.json"

        if meta_path.exists() and not force:
            with meta_path.open("r", encoding="utf-8") as fh:
                meta = json.load(fh)
            self.rebuild_sitemap()
            return meta

        meta_description = (
            f"Discover how {self.brand} delivers {topic['keyword'].lower()} with "
            f"live Binance futures signals, ATR risk controls, and paper-trading automation."
        )
        article = self._build_article(topic=topic, date=today, meta_description=meta_description)
        schema = self._build_schema(topic=topic, date=today, meta_description=meta_description, slug=slug)

        md_path.write_text(article["markdown"], encoding="utf-8")
        html_path.write_text(article["html"], encoding="utf-8")

        meta = {
            "slug": slug,
            "date": today,
            "title": topic["title"],
            "keyword": topic["keyword"],
            "secondary_keywords": topic["secondary"],
            "meta_description": meta_description,
            "subscription_url": self.subscription_url,
            "markdown_path": str(md_path).replace("\\", "/"),
            "html_path": str(html_path).replace("\\", "/"),
            "canonical_url": f"{self.site_base_url}/content/blogs/{slug}.html",
            "schema_json_ld": schema,
            "generated_at": _utc_iso(),
            "excerpt": article["excerpt"],
        }
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self.rebuild_sitemap()
        return meta

    def list_articles(self, limit: int = 50) -> list[dict[str, Any]]:
        metas = sorted(self.blog_dir.glob("*.json"), reverse=True)
        articles: list[dict[str, Any]] = []
        for path in metas[:limit]:
            try:
                with path.open("r", encoding="utf-8") as fh:
                    articles.append(json.load(fh))
            except (OSError, json.JSONDecodeError):
                continue
        return articles

    def rebuild_sitemap(self) -> Path:
        articles = self.list_articles(limit=500)
        urls = [
            f"  <url>\n    <loc>{escape(self.site_base_url)}/</loc>\n"
            f"    <changefreq>daily</changefreq>\n    <priority>1.0</priority>\n  </url>"
        ]
        for art in articles:
            loc = art.get("canonical_url") or f"{self.site_base_url}/"
            lastmod = art.get("date") or _utc_date()
            urls.append(
                "  <url>\n"
                f"    <loc>{escape(str(loc))}</loc>\n"
                f"    <lastmod>{escape(str(lastmod))}</lastmod>\n"
                "    <changefreq>weekly</changefreq>\n"
                "    <priority>0.8</priority>\n"
                "  </url>"
            )

        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(urls)
            + "\n</urlset>\n"
        )
        self.sitemap_path.write_text(xml, encoding="utf-8")
        # Mirror at project root for convenience
        root_sitemap = Path("sitemap.xml")
        root_sitemap.write_text(xml, encoding="utf-8")
        return self.sitemap_path

    def _build_article(
        self,
        topic: dict[str, Any],
        date: str,
        meta_description: str,
    ) -> dict[str, str]:
        keyword = topic["keyword"]
        title = topic["title"]
        secondary = ", ".join(topic["secondary"])
        cta = self.subscription_url

        markdown = f"""---
title: "{title}"
date: {date}
keyword: "{keyword}"
meta_description: "{meta_description}"
---

# {title}

**Primary keyword:** {keyword}  
**Secondary keywords:** {secondary}  
**Updated:** {date}

{meta_description}

## Why traders search for "{keyword}"

In 2026, discretionary crypto futures trading is being replaced by systematic AI stacks.
Traders evaluating **{keyword}** want three things: signal quality, enforceable risk, and
transparent paper-trading before capital is deployed.

[{self.brand}]({cta}) is built around that exact workflow — live Binance USD-M data,
multi-indicator confluence, ATR-based stops, and a localhost control plane.

## The Beast AI confluence stack

1. **RSI(14)** for oversold / overbought extremes  
2. **EMA 20/50 crossover** for trend regime shifts  
3. **MACD histogram** for momentum confirmation  
4. **News sentiment filter** to block trades against extreme fear/greed  

When these layers agree, the engine sizes risk at `{config.MAX_RISK_PER_TRADE * 100:.1f}%`
of equity and publishes SL/TP from ATR volatility.

## Automated risk management on Binance Futures

- Max risk per trade from config  
- Volatility-aware leverage scaling  
- Paper mode with fees + slippage before live routing  

Internal resource: [Start your Beast AI subscription]({cta})

## How to trade BTC volatility with AI

BTC expansion regimes punish fixed-percentage stops. ATR-normalized exits adapt to the tape,
while sentiment analytics reduce the odds of longing into headline-driven capitulation.

## CTA: Launch paper trading today

Ready to evaluate **{keyword}** with a real engine instead of screenshots?

👉 **[Subscribe to Beast AI Trading Bot]({cta})**

---
*Generated automatically by the Beast AI SEO engine for educational SaaS distribution.*
"""

        excerpt = meta_description
        html = self._markdownish_to_html(
            title=title,
            meta_description=meta_description,
            keyword=keyword,
            date=date,
            body_md=markdown,
            schema=self._build_schema(topic, date, meta_description, f"{date}-{topic['slug']}"),
        )
        return {"markdown": markdown, "html": html, "excerpt": excerpt}

    def _build_schema(
        self,
        topic: dict[str, Any],
        date: str,
        meta_description: str,
        slug: str,
    ) -> dict[str, Any]:
        return {
            "@context": "https://schema.org",
            "@type": "BlogPosting",
            "headline": topic["title"],
            "description": meta_description,
            "datePublished": date,
            "dateModified": date,
            "author": {
                "@type": "Organization",
                "name": self.brand,
                "url": self.site_base_url,
            },
            "publisher": {
                "@type": "Organization",
                "name": self.brand,
                "url": self.site_base_url,
            },
            "mainEntityOfPage": f"{self.site_base_url}/content/blogs/{slug}.html",
            "keywords": ", ".join([topic["keyword"], *topic["secondary"]]),
            "about": topic["keyword"],
            "isPartOf": {
                "@type": "WebSite",
                "name": self.brand,
                "url": self.site_base_url,
            },
            "offers": {
                "@type": "Offer",
                "url": self.subscription_url,
                "name": f"{self.brand} Subscription",
                "category": "SaaS",
            },
        }

    def _markdownish_to_html(
        self,
        title: str,
        meta_description: str,
        keyword: str,
        date: str,
        body_md: str,
        schema: dict[str, Any],
    ) -> str:
        # Lightweight conversion for headings / paragraphs / links (good enough for SEO files)
        body = body_md.split("---", 2)[-1].strip()
        lines = body.splitlines()
        html_parts: list[str] = []
        for line in lines:
            raw = line.strip()
            if not raw:
                continue
            if raw.startswith("# "):
                html_parts.append(f"<h1>{escape(raw[2:])}</h1>")
            elif raw.startswith("## "):
                html_parts.append(f"<h2>{escape(raw[3:])}</h2>")
            elif raw.startswith("- "):
                html_parts.append(f"<li>{self._inline(raw[2:])}</li>")
            elif re.match(r"^\d+\.\s+", raw):
                html_parts.append(f"<li>{self._inline(re.sub(r'^\\d+\\.\\s+', '', raw))}</li>")
            else:
                html_parts.append(f"<p>{self._inline(raw)}</p>")

        schema_json = json.dumps(schema, indent=2)
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{escape(title)}</title>
  <meta name="description" content="{escape(meta_description)}" />
  <meta name="keywords" content="{escape(keyword)}" />
  <link rel="canonical" href="{escape(schema['mainEntityOfPage'])}" />
  <script type="application/ld+json">
{schema_json}
  </script>
</head>
<body>
  <article>
    <header>
      <p><strong>Published:</strong> {escape(date)}</p>
      <p><strong>Target keyword:</strong> {escape(keyword)}</p>
    </header>
    {''.join(html_parts)}
    <footer>
      <p><a href="{escape(self.subscription_url)}">Subscribe to {escape(self.brand)}</a></p>
    </footer>
  </article>
</body>
</html>
"""

    @staticmethod
    def _inline(text: str) -> str:
        # bold + links
        text = escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(
            r"\[(.+?)\]\((https?://[^\s)]+)\)",
            r'<a href="\2">\1</a>',
            text,
        )
        # recover escaped anchors from escape() — redo on unescaped path
        return text


# Process-wide singleton
seo_generator = SEOBlogGenerator()
