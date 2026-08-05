"""
Beast AI Trading Bot — Phase 7 Subscription Management Engine

Mock / Stripe-ready subscription state with tier feature limits.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv

import config

SubscriptionStatus = Literal["active", "trialing", "expired", "canceled"]
TierId = Literal["starter", "pro", "vip"]

PRICING_TIERS: list[dict[str, Any]] = [
    {
        "id": "starter",
        "name": "Starter",
        "price_usd": 29,
        "interval": "month",
        "headline": "Solo traders validating AI signals",
        "features": [
            "1 connected exchange",
            "Paper trading engine",
            "Live scanner + risk sizing",
            "Email support",
        ],
        "limits": {
            "max_exchanges": 1,
            "copy_trading": False,
            "priority_telegram": False,
            "unlimited_exchanges": False,
        },
        "cta": "Start Free Trial",
    },
    {
        "id": "pro",
        "name": "Pro Trader",
        "price_usd": 79,
        "interval": "month",
        "headline": "Active futures desks scaling edge",
        "features": [
            "3 connected exchanges",
            "Copy trading master/follower",
            "Sentiment confluence filter",
            "Standard Telegram alerts",
        ],
        "limits": {
            "max_exchanges": 3,
            "copy_trading": True,
            "priority_telegram": False,
            "unlimited_exchanges": False,
        },
        "cta": "Go Pro",
        "highlighted": True,
    },
    {
        "id": "vip",
        "name": "Institutional VIP",
        "price_usd": 199,
        "interval": "month",
        "headline": "Desks that need unlimited routing",
        "features": [
            "Unlimited exchanges",
            "Priority Telegram signals",
            "Copy trading + profit share ledger",
            "White-glove onboarding",
        ],
        "limits": {
            "max_exchanges": 10_000,
            "copy_trading": True,
            "priority_telegram": True,
            "unlimited_exchanges": True,
        },
        "cta": "Talk to Sales",
    },
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


class BillingManager:
    """Local subscription state with Stripe-shaped fields (mock by default)."""

    def __init__(self, state_path: str | Path = config.BILLING_STATE_PATH) -> None:
        load_dotenv()
        self.state_path = Path(state_path)
        self.stripe_secret = os.getenv(config.STRIPE_SECRET_KEY_ENV, "").strip()
        self._state = self._load_or_create()

    @property
    def stripe_mode(self) -> str:
        return "live_ready" if self.stripe_secret else "mock"

    def _default_state(self) -> dict[str, Any]:
        now = _utc_now()
        trial_end = now + timedelta(days=config.TRIAL_DAYS)
        return {
            "customer_id": "cus_mock_beast_ai",
            "subscription_id": "sub_mock_beast_ai",
            "tier": config.DEFAULT_SUBSCRIPTION_TIER,
            "status": config.DEFAULT_SUBSCRIPTION_STATUS,
            "trial_ends_at": _utc_iso(trial_end),
            "current_period_end": _utc_iso(trial_end),
            "cancel_at_period_end": False,
            "provider": "mock",
            "updated_at": _utc_iso(now),
        }

    def _load_or_create(self) -> dict[str, Any]:
        if not self.state_path.exists():
            state = self._default_state()
            self._save(state)
            return state
        try:
            with self.state_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("invalid state")
            return data
        except (OSError, json.JSONDecodeError, ValueError):
            state = self._default_state()
            self._save(state)
            return state

    def _save(self, state: dict[str, Any]) -> None:
        state["updated_at"] = _utc_iso()
        with self.state_path.open("w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
        self._state = state

    def get_tier_config(self, tier_id: str | None = None) -> dict[str, Any]:
        tier_id = (tier_id or self._state.get("tier") or "starter").lower()
        for tier in PRICING_TIERS:
            if tier["id"] == tier_id:
                return tier
        return PRICING_TIERS[0]

    def refresh_status(self) -> dict[str, Any]:
        """Expire trials that have lapsed (mock clock)."""
        state = dict(self._state)
        status = str(state.get("status") or "expired")
        trial_ends = state.get("trial_ends_at") or state.get("current_period_end")
        if status == "trialing" and trial_ends:
            try:
                end = datetime.fromisoformat(str(trial_ends).replace("Z", "+00:00"))
                if _utc_now() > end:
                    state["status"] = "expired"
                    self._save(state)
            except ValueError:
                pass
        else:
            self._state = state
        return self.get_status()

    def get_status(self) -> dict[str, Any]:
        state = dict(self._state)
        tier = self.get_tier_config(state.get("tier"))
        status = str(state.get("status") or "expired")
        active_like = status in {"active", "trialing"}
        return {
            **state,
            "tier_name": tier["name"],
            "price_usd": tier["price_usd"],
            "limits": tier["limits"],
            "features": tier["features"],
            "is_active": active_like,
            "stripe_mode": self.stripe_mode,
            "server_time": _utc_iso(),
        }

    def list_pricing(self) -> dict[str, Any]:
        tiers = PRICING_TIERS
        try:
            from cms_engine import cms_engine

            tiers = cms_engine.apply_pricing_to_tiers(PRICING_TIERS)
        except Exception:
            pass
        return {
            "currency": "USD",
            "trial_days": config.TRIAL_DAYS,
            "stripe_mode": self.stripe_mode,
            "tiers": tiers,
        }

    def set_tier(self, tier: TierId, status: SubscriptionStatus | None = None) -> dict[str, Any]:
        if tier not in {t["id"] for t in PRICING_TIERS}:
            raise ValueError(f"Unknown tier: {tier}")
        state = dict(self._state)
        state["tier"] = tier
        if status:
            state["status"] = status
        # Stripe hook placeholder
        if self.stripe_secret:
            state["provider"] = "stripe"
            state["stripe_note"] = "Stripe secret detected — wire checkout session in production."
        else:
            state["provider"] = "mock"
        self._save(state)
        return self.get_status()

    def start_trial(self, tier: TierId = "pro") -> dict[str, Any]:
        now = _utc_now()
        end = now + timedelta(days=config.TRIAL_DAYS)
        state = dict(self._state)
        state.update(
            {
                "tier": tier,
                "status": "trialing",
                "trial_ends_at": _utc_iso(end),
                "current_period_end": _utc_iso(end),
                "cancel_at_period_end": False,
            }
        )
        self._save(state)
        return self.get_status()

    def assert_can_connect_exchange(self, current_exchange_count: int) -> None:
        status = self.refresh_status()
        if not status["is_active"]:
            raise PermissionError(
                f"Subscription {status['status']}. Activate a plan to connect exchanges."
            )
        limits = status["limits"]
        if limits.get("unlimited_exchanges"):
            return
        max_ex = int(limits.get("max_exchanges") or 0)
        if current_exchange_count >= max_ex:
            raise PermissionError(
                f"{status['tier_name']} plan allows {max_ex} exchange(s). "
                "Upgrade to connect more."
            )

    def assert_can_use_copy_trading(self) -> None:
        status = self.refresh_status()
        if not status["is_active"]:
            raise PermissionError("Active subscription required for copy trading.")
        if not status["limits"].get("copy_trading"):
            raise PermissionError(
                f"{status['tier_name']} does not include Copy Trading. Upgrade to Pro or VIP."
            )

    def telegram_priority(self) -> bool:
        status = self.get_status()
        return bool(status["is_active"] and status["limits"].get("priority_telegram"))


billing = BillingManager()
