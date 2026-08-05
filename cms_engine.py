"""
Beast AI Trading Bot — Phase 12 CMS Content Editor Engine
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

CMS_PATH = Path(getattr(config, "CMS_CONTENT_PATH", "content/cms_content.json"))

DEFAULT_CONTENT: dict[str, Any] = {
    "meta": {
        "title": "Beast AI — Automated Futures Trading SaaS",
        "description": (
            "Beast AI Trading Bot: multi-exchange futures automation, copy trading, "
            "sentiment filters, and risk-first execution."
        ),
        "keywords": "crypto trading bot, futures AI, copy trading, beast ai",
    },
    "hero": {
        "brand": "Beast AI",
        "headline": "Futures automation that sizes risk before it chases alpha.",
        "subheadline": (
            "Multi-exchange signals, copy trading, and Telegram alerts — "
            "paper-trade first, go live when ready."
        ),
        "cta_primary": "Start 7-Day Free Trial",
        "cta_secondary": "Launch Dashboard",
        "video_url": "",
        "banner_poster": "",
    },
    "faq": [
        {
            "question": "Is the 7-day trial really free?",
            "answer": "Yes. Trialing status unlocks the Pro feature set locally so you can connect exchanges in paper mode, run the scanner, and test Telegram mock alerts before billing.",
        },
        {
            "question": "Do you place live orders by default?",
            "answer": "No. Paper trading is the default. Live copy routing is gated by configuration and requires validated API keys with withdrawals disabled.",
        },
        {
            "question": "Which exchanges are supported?",
            "answer": "Binance, Bybit, KuCoin, and OKX via CCXT, with tier limits on how many accounts you can vault.",
        },
        {
            "question": "How does copy trading sizing work?",
            "answer": "Follower order size scales by equity ratio versus the master account — a $100 follower mirrors 1% of a $10,000 master notional.",
        },
        {
            "question": "What if I don’t have a Telegram bot token yet?",
            "answer": "Alerts run in mock mode and append to a local outbox file so you can verify message content without leaving the machine.",
        },
    ],
    "testimonials": [
        {
            "text": "Risk sizing finally feels institutional. We paper-traded for a week, then mirrored to Bybit followers.",
            "author": "Lena K., Prop Desk Lead",
        },
        {
            "text": "The sentiment gate saved us from longing into a fear spike. Telegram pings are clean and actionable.",
            "author": "Marcus R., Crypto Fund Analyst",
        },
        {
            "text": "Copy trading proportional sizing is the feature we were hacking together manually.",
            "author": "Ava S., Boutique Quant",
        },
    ],
    "features": [
        {
            "title": "Risk-first signal engine",
            "body": "RSI, EMA, MACD and ATR confluence with position sizing before every entry.",
        },
        {
            "title": "Multi-exchange vault",
            "body": "Connect Binance, Bybit, KuCoin, and OKX with encrypted local key storage.",
        },
        {
            "title": "Copy trading desk",
            "body": "Proportional follower sizing and a 15% master profit-share ledger.",
        },
        {
            "title": "Sentiment confluence",
            "body": "Live news scoring blocks FOMO longs and panic shorts at the edge.",
        },
        {
            "title": "Telegram ops alerts",
            "body": "Signal, fill, and daily PnL notifications with mock mode for local demos.",
        },
        {
            "title": "PWA + live charts",
            "body": "Installable trading desk with WebSocket ticks and TradingView candles.",
        },
    ],
    "pricing_rates": {
        "starter": 29,
        "pro": 79,
        "vip": 199,
    },
    "services": [
        {
            "title": "Managed signal routing",
            "body": "Automated scan cycles across your watchlist with SL/TP overlays and confidence gates.",
        },
        {
            "title": "Desk analytics",
            "body": "Equity, win rate, and trade history streamed to the dashboard in real time.",
        },
        {
            "title": "Follower capital scaling",
            "body": "Mirror master notionals by equity ratio without manual calculator spreadsheets.",
        },
    ],
    "trustpilot": {
        "rating": 4.8,
        "reviews": 214,
        "label": "Excellent",
        "quotes": [
            {
                "text": "Risk sizing finally feels institutional. We paper-traded for a week, then mirrored to Bybit followers.",
                "author": "Lena K., Prop Desk Lead",
            },
            {
                "text": "The sentiment gate saved us from longing into a fear spike. Telegram pings are clean and actionable.",
                "author": "Marcus R., Crypto Fund Analyst",
            },
            {
                "text": "Copy trading proportional sizing is the feature we were hacking together manually.",
                "author": "Ava S., Boutique Quant",
            },
        ],
    },
    "risk_disclaimer": (
        "Trading futures and crypto involves substantial risk of loss and is not suitable for every investor. "
        "Past performance — including paper-trading showcases — does not guarantee future results. "
        "Beast AI provides software tools only and does not offer investment advice. "
        "You are solely responsible for API keys, exchange permissions, and live order decisions."
    ),
    "terms_of_service": (
        "By using Beast AI you agree to: (1) use the platform at your own risk; "
        "(2) keep withdrawal permissions disabled on exchange API keys; "
        "(3) comply with applicable laws in your jurisdiction; "
        "(4) accept that subscriptions renew monthly unless canceled; "
        "(5) acknowledge paper mode is default and live execution requires explicit configuration. "
        "We may suspend accounts that abuse webhooks, payment systems, or other users. "
        "Content and signals are informational. No fiduciary relationship is created."
    ),
    "updated_at": None,
}


class CMSEngine:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or CMS_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save(deepcopy(DEFAULT_CONTENT))

    def _utc(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return deepcopy(DEFAULT_CONTENT)
            merged = deepcopy(DEFAULT_CONTENT)
            self._deep_merge(merged, data)
            return merged
        except (OSError, json.JSONDecodeError):
            return deepcopy(DEFAULT_CONTENT)

    def save(self, content: dict[str, Any]) -> dict[str, Any]:
        payload = deepcopy(content)
        payload["updated_at"] = self._utc()
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    def get_public(self) -> dict[str, Any]:
        return self.load()

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        data = patch or {}
        # Full-replace list sections so admin CRUD can delete items
        for list_key in ("features", "faq", "testimonials", "services"):
            if list_key in data and isinstance(data[list_key], list):
                current[list_key] = data[list_key]
                data = {k: v for k, v in data.items() if k != list_key}
        self._deep_merge(current, data)
        # Keep Trustpilot quotes aligned with testimonials when present
        if isinstance(current.get("testimonials"), list):
            current.setdefault("trustpilot", {})
            current["trustpilot"]["quotes"] = current["testimonials"]
        return self.save(current)

    @staticmethod
    def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
        for key, value in patch.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                CMSEngine._deep_merge(base[key], value)
            else:
                base[key] = value

    def apply_pricing_to_tiers(self, tiers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rates = self.load().get("pricing_rates") or {}
        out = []
        for tier in tiers:
            row = dict(tier)
            tid = row.get("id")
            if tid in rates:
                row["price_usd"] = float(rates[tid])
            out.append(row)
        return out


cms_engine = CMSEngine()
