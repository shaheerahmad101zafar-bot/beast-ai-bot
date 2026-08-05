"""
Beast AI Trading Bot — Phase 9 Payment Processing Engine

Stripe Checkout / Customer Portal + NOWPayments crypto invoices (USDT).
Falls back to mock checkout URLs when API keys are not configured.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

import config
from billing import PRICING_TIERS, billing
from database import PaymentLog, User

TierId = Literal["starter", "pro", "vip"]
PayMethod = Literal["stripe", "crypto"]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso(dt: datetime | None = None) -> str:
    return (dt or _utc_now()).strftime("%Y-%m-%dT%H:%M:%SZ")


class PaymentEngine:
    """Unified Stripe + NOWPayments checkout factory and webhook helpers."""

    def __init__(self) -> None:
        load_dotenv()
        self.mock_log = Path(config.PAYMENTS_MOCK_LOG)
        self.stripe_enabled = True
        self.crypto_enabled = True
        self.stripe_secret = ""
        self.stripe_webhook_secret = ""
        self.nowpayments_key = ""
        self.nowpayments_ipn_secret = ""
        self.usdt_trc20_address = ""
        self.usdt_bep20_address = ""
        self.price_env = {"starter": "", "pro": "", "vip": ""}
        self._stripe = None
        self.reload_credentials()

    def reload_credentials(self) -> None:
        """Refresh secrets from Admin Settings (SQLite) with .env fallback."""
        load_dotenv()
        pay: dict[str, Any] = {}
        try:
            from admin_settings import admin_settings

            pay = admin_settings.get_payments()
        except Exception:
            pay = {}

        self.stripe_enabled = bool(pay.get("stripe_enabled", True))
        self.crypto_enabled = bool(pay.get("crypto_enabled", True))
        self.stripe_secret = (
            str(pay.get("stripe_secret_key") or "").strip()
            or os.getenv(config.STRIPE_SECRET_KEY_ENV, "").strip()
        )
        self.stripe_webhook_secret = (
            str(pay.get("stripe_webhook_secret") or "").strip()
            or os.getenv(config.STRIPE_WEBHOOK_SECRET_ENV, "").strip()
        )
        self.nowpayments_key = (
            str(pay.get("nowpayments_api_key") or "").strip()
            or os.getenv(config.NOWPAYMENTS_API_KEY_ENV, "").strip()
        )
        self.nowpayments_ipn_secret = (
            str(pay.get("nowpayments_ipn_secret") or "").strip()
            or os.getenv(config.NOWPAYMENTS_IPN_SECRET_ENV, "").strip()
        )
        self.usdt_trc20_address = str(pay.get("usdt_trc20_address") or "").strip()
        self.usdt_bep20_address = str(pay.get("usdt_bep20_address") or "").strip()
        self.price_env = {
            "starter": str(pay.get("stripe_price_starter") or "").strip()
            or os.getenv(config.STRIPE_PRICE_STARTER_ENV, "").strip(),
            "pro": str(pay.get("stripe_price_pro") or "").strip()
            or os.getenv(config.STRIPE_PRICE_PRO_ENV, "").strip(),
            "vip": str(pay.get("stripe_price_vip") or "").strip()
            or os.getenv(config.STRIPE_PRICE_VIP_ENV, "").strip(),
        }
        self._stripe = None
        if self.stripe_enabled and self.stripe_secret:
            import stripe

            stripe.api_key = self.stripe_secret
            self._stripe = stripe

    # ------------------------------------------------------------------
    # Public status
    # ------------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        self.reload_credentials()
        return {
            "stripe_enabled": self.stripe_enabled,
            "crypto_enabled": self.crypto_enabled,
            "stripe_mode": "live" if (self.stripe_enabled and self.stripe_secret) else "mock",
            "crypto_mode": "live" if (self.crypto_enabled and self.nowpayments_key) else "mock",
            "webhook_stripe_configured": bool(self.stripe_webhook_secret),
            "webhook_crypto_configured": bool(self.nowpayments_ipn_secret),
            "usdt_trc20_address": self.usdt_trc20_address or None,
            "usdt_bep20_address": self.usdt_bep20_address or None,
            "tiers": [
                {
                    "id": t["id"],
                    "name": t["name"],
                    "price_usd": t["price_usd"],
                    "stripe_price_id": self.price_env.get(t["id"]) or None,
                }
                for t in PRICING_TIERS
            ],
        }

    def tier_amount(self, tier: str) -> int:
        try:
            from cms_engine import cms_engine

            rates = cms_engine.load().get("pricing_rates") or {}
            if tier in rates:
                return int(rates[tier])
        except Exception:
            pass
        for t in PRICING_TIERS:
            if t["id"] == tier:
                return int(t["price_usd"])
        raise ValueError(f"Unknown tier: {tier}")

    # ------------------------------------------------------------------
    # Checkout creation
    # ------------------------------------------------------------------
    def create_checkout_session(
        self,
        *,
        user: User,
        tier: TierId,
        method: PayMethod = "stripe",
        success_url: str | None = None,
        cancel_url: str | None = None,
        pay_currency: str = "usdttrc20",
    ) -> dict[str, Any]:
        if tier not in {"starter", "pro", "vip"}:
            raise ValueError("tier must be starter, pro, or vip")

        self.reload_credentials()
        if method == "stripe" and not self.stripe_enabled:
            raise ValueError("Stripe payments are disabled by admin")
        if method == "crypto" and not self.crypto_enabled:
            raise ValueError("Crypto payments are disabled by admin")

        success_url = success_url or f"{config.SITE_BASE_URL}/app?billing=success"
        cancel_url = cancel_url or f"{config.SITE_BASE_URL}/pricing?billing=cancel"
        amount = self.tier_amount(tier)

        if method == "stripe":
            return self._create_stripe_checkout(user, tier, amount, success_url, cancel_url)
        return self._create_crypto_invoice(user, tier, amount, success_url, pay_currency)

    def create_customer_portal(self, user: User, return_url: str | None = None) -> dict[str, Any]:
        return_url = return_url or f"{config.SITE_BASE_URL}/app?tab=billing"
        if not self._stripe or not user.stripe_customer_id:
            portal = {
                "mode": "mock",
                "url": f"{config.SITE_BASE_URL}/app?tab=billing&portal=mock",
                "message": "Stripe portal mock — configure STRIPE_SECRET_KEY and a customer id.",
            }
            self._log_event("portal_mock", {"user_id": user.id, **portal})
            return portal

        session = self._stripe.billing_portal.Session.create(
            customer=user.stripe_customer_id,
            return_url=return_url,
        )
        return {"mode": "live", "url": session.url, "id": session.id}

    def _create_stripe_checkout(
        self,
        user: User,
        tier: str,
        amount: int,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        if not self._stripe:
            session_id = f"cs_mock_{uuid.uuid4().hex[:12]}"
            url = (
                f"{config.SITE_BASE_URL}/api/payments/mock-complete"
                f"?provider=stripe&tier={tier}&user_id={user.id}&session_id={session_id}"
            )
            payload = {
                "mode": "mock",
                "provider": "stripe",
                "checkout_url": url,
                "session_id": session_id,
                "tier": tier,
                "amount_usd": amount,
                "user_id": user.id,
            }
            self._log_event("stripe_checkout_mock", payload)
            return payload

        price_id = self.price_env.get(tier)
        line_items: list[dict[str, Any]]
        if price_id:
            line_items = [{"price": price_id, "quantity": 1}]
        else:
            line_items = [
                {
                    "price_data": {
                        "currency": "usd",
                        "product_data": {
                            "name": f"Beast AI {tier.upper()} Plan",
                            "description": "Monthly SaaS subscription",
                        },
                        "unit_amount": amount * 100,
                        "recurring": {"interval": "month"},
                    },
                    "quantity": 1,
                }
            ]

        customer_kwargs: dict[str, Any] = {}
        if user.stripe_customer_id:
            customer_kwargs["customer"] = user.stripe_customer_id
        else:
            customer_kwargs["customer_email"] = user.email

        session = self._stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url + "&session_id={CHECKOUT_SESSION_ID}",
            cancel_url=cancel_url,
            line_items=line_items,
            client_reference_id=str(user.id),
            metadata={"user_id": str(user.id), "tier": tier},
            subscription_data={"metadata": {"user_id": str(user.id), "tier": tier}},
            **customer_kwargs,
        )
        return {
            "mode": "live",
            "provider": "stripe",
            "checkout_url": session.url,
            "session_id": session.id,
            "tier": tier,
            "amount_usd": amount,
            "user_id": user.id,
        }

    def _create_crypto_invoice(
        self,
        user: User,
        tier: str,
        amount: int,
        success_url: str,
        pay_currency: str,
    ) -> dict[str, Any]:
        order_id = f"beast_{user.id}_{tier}_{uuid.uuid4().hex[:8]}"
        # Normalize popular aliases
        currency = pay_currency.lower().replace("_", "")
        if currency in {"usdt", "usdttrc20", "trc20"}:
            currency = "usdttrc20"
        elif currency in {"usdtbep20", "bep20"}:
            currency = "usdtbsc"

        if not self.nowpayments_key:
            url = (
                f"{config.SITE_BASE_URL}/api/payments/mock-complete"
                f"?provider=crypto&tier={tier}&user_id={user.id}&order_id={order_id}"
            )
            payload = {
                "mode": "mock",
                "provider": "crypto",
                "checkout_url": url,
                "invoice_id": order_id,
                "order_id": order_id,
                "tier": tier,
                "amount_usd": amount,
                "pay_currency": currency,
                "networks": ["USDT TRC20", "USDT BEP20"],
                "user_id": user.id,
            }
            self._log_event("crypto_invoice_mock", payload)
            return payload

        resp = requests.post(
            "https://api.nowpayments.io/v1/invoice",
            headers={
                "x-api-key": self.nowpayments_key,
                "Content-Type": "application/json",
            },
            json={
                "price_amount": amount,
                "price_currency": "usd",
                "pay_currency": currency,
                "order_id": order_id,
                "order_description": f"Beast AI {tier} monthly",
                "ipn_callback_url": f"{config.SITE_BASE_URL}/api/payments/crypto-webhook",
                "success_url": success_url,
                "cancel_url": f"{config.SITE_BASE_URL}/pricing?billing=cancel",
            },
            timeout=30,
        )
        data = resp.json() if resp.content else {}
        if not resp.ok:
            raise RuntimeError(f"NOWPayments invoice failed: {data}")
        return {
            "mode": "live",
            "provider": "crypto",
            "checkout_url": data.get("invoice_url"),
            "invoice_id": data.get("id"),
            "order_id": order_id,
            "tier": tier,
            "amount_usd": amount,
            "pay_currency": currency,
            "raw": data,
            "user_id": user.id,
        }

    # ------------------------------------------------------------------
    # Plan activation
    # ------------------------------------------------------------------
    def activate_subscription(
        self,
        db: Session,
        *,
        user_id: int,
        tier: str,
        provider: str,
        status: str = "active",
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        days: int = 30,
    ) -> dict[str, Any]:
        user = db.get(User, int(user_id))
        if not user:
            raise ValueError(f"User {user_id} not found")

        user.plan = tier
        user.subscription_status = status
        user.payment_provider = provider
        user.subscription_expires_at = _utc_now() + timedelta(days=days)
        if stripe_customer_id:
            user.stripe_customer_id = stripe_customer_id
        if stripe_subscription_id:
            user.stripe_subscription_id = stripe_subscription_id
        amount = float(self.tier_amount(tier))
        db.add(
            PaymentLog(
                user_id=user.id,
                email=user.email,
                amount_usd=amount,
                gateway=provider,
                status="completed" if status == "active" else status,
                tier=tier,
                external_id=stripe_subscription_id,
            )
        )
        db.commit()
        db.refresh(user)

        # Keep legacy global billing snapshot in sync for feature gates
        try:
            billing.set_tier(tier, status="active" if status == "active" else status)  # type: ignore[arg-type]
        except Exception:
            pass

        result = {
            "user_id": user.id,
            "email": user.email,
            "plan": user.plan,
            "subscription_status": user.subscription_status,
            "payment_provider": user.payment_provider,
            "subscription_expires_at": _utc_iso(user.subscription_expires_at)
            if user.subscription_expires_at
            else None,
            "amount_usd": amount,
        }
        self._log_event("activate_subscription", result)
        return result

    def cancel_subscription(self, db: Session, *, user_id: int | None = None, email: str | None = None) -> dict[str, Any]:
        user = None
        if user_id:
            user = db.get(User, int(user_id))
        if user is None and email:
            from sqlalchemy import select

            user = db.scalar(select(User).where(User.email == email.lower()))
        if not user:
            raise ValueError("User not found for cancellation")

        user.subscription_status = "canceled"
        user.subscription_expires_at = _utc_now()
        db.commit()
        db.refresh(user)
        try:
            billing.set_tier(user.plan, status="canceled")  # type: ignore[arg-type]
        except Exception:
            pass
        result = {
            "user_id": user.id,
            "email": user.email,
            "plan": user.plan,
            "subscription_status": user.subscription_status,
        }
        self._log_event("cancel_subscription", result)
        return result

    # ------------------------------------------------------------------
    # Webhook helpers
    # ------------------------------------------------------------------
    def construct_stripe_event(self, payload: bytes, sig_header: str | None) -> dict[str, Any]:
        if not self._stripe:
            return json.loads(payload.decode("utf-8"))
        if not self.stripe_webhook_secret:
            return json.loads(payload.decode("utf-8"))
        event = self._stripe.Webhook.construct_event(
            payload,
            sig_header,
            self.stripe_webhook_secret,
        )
        return event

    def verify_nowpayments_ipn(self, payload: dict[str, Any], signature: str | None) -> bool:
        if not self.nowpayments_ipn_secret:
            return True  # mock/dev accept
        if not signature:
            return False
        sorted_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        digest = hmac.new(
            self.nowpayments_ipn_secret.encode("utf-8"),
            sorted_json.encode("utf-8"),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        history: list[dict[str, Any]] = []
        if self.mock_log.exists():
            try:
                history = json.loads(self.mock_log.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            except (OSError, json.JSONDecodeError):
                history = []
        history.append({"type": event_type, "timestamp": _utc_iso(), "payload": payload})
        self.mock_log.write_text(json.dumps(history[-300:], indent=2), encoding="utf-8")


payments = PaymentEngine()
