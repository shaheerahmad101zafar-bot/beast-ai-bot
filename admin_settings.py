"""
Beast AI Trading Bot — Phase 14 Dynamic Super-Admin Settings

SQLite-backed payment gateway keys, crypto wallets, and social link config.
"""

from __future__ import annotations

import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from database import SessionLocal, Setting
from security import sanitize_text

SETTINGS_KEY = "app_config"

DEFAULT_SETTINGS: dict[str, Any] = {
    "payments": {
        "stripe_enabled": True,
        "stripe_secret_key": "",
        "stripe_webhook_secret": "",
        "stripe_price_starter": "",
        "stripe_price_pro": "",
        "stripe_price_vip": "",
        "crypto_enabled": True,
        "nowpayments_api_key": "",
        "nowpayments_ipn_secret": "",
        "usdt_trc20_address": "",
        "usdt_bep20_address": "",
    },
    "social": {
        "facebook": "",
        "youtube": "",
        "instagram": "",
        "linkedin": "",
    },
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _mask_secret(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 8:
        return "••••••••"
    return f"{text[:4]}••••{text[-4:]}"


class AdminSettings:
    """Load/save dynamic runtime settings from the `settings` table."""

    def ensure_defaults(self) -> None:
        db = SessionLocal()
        try:
            row = db.get(Setting, SETTINGS_KEY)
            if row:
                return
            # Seed from environment when available
            seeded = deepcopy(DEFAULT_SETTINGS)
            seeded["payments"].update(
                {
                    "stripe_secret_key": os.getenv(config.STRIPE_SECRET_KEY_ENV, "").strip(),
                    "stripe_webhook_secret": os.getenv(config.STRIPE_WEBHOOK_SECRET_ENV, "").strip(),
                    "stripe_price_starter": os.getenv(config.STRIPE_PRICE_STARTER_ENV, "").strip(),
                    "stripe_price_pro": os.getenv(config.STRIPE_PRICE_PRO_ENV, "").strip(),
                    "stripe_price_vip": os.getenv(config.STRIPE_PRICE_VIP_ENV, "").strip(),
                    "nowpayments_api_key": os.getenv(config.NOWPAYMENTS_API_KEY_ENV, "").strip(),
                    "nowpayments_ipn_secret": os.getenv(config.NOWPAYMENTS_IPN_SECRET_ENV, "").strip(),
                }
            )
            db.add(
                Setting(
                    key=SETTINGS_KEY,
                    value=json.dumps(seeded),
                    updated_at=_utc_now(),
                )
            )
            db.commit()
        finally:
            db.close()

    def _read_raw(self, db: Session) -> dict[str, Any]:
        row = db.get(Setting, SETTINGS_KEY)
        if not row:
            return deepcopy(DEFAULT_SETTINGS)
        try:
            data = json.loads(row.value or "{}")
            if not isinstance(data, dict):
                return deepcopy(DEFAULT_SETTINGS)
        except json.JSONDecodeError:
            return deepcopy(DEFAULT_SETTINGS)
        merged = deepcopy(DEFAULT_SETTINGS)
        for section, payload in data.items():
            if isinstance(payload, dict) and isinstance(merged.get(section), dict):
                merged[section].update(payload)
            else:
                merged[section] = payload
        return merged

    def get_all(self, *, mask_secrets: bool = False) -> dict[str, Any]:
        db = SessionLocal()
        try:
            data = self._read_raw(db)
        finally:
            db.close()
        if not mask_secrets:
            return data
        payments = dict(data.get("payments") or {})
        for key in (
            "stripe_secret_key",
            "stripe_webhook_secret",
            "nowpayments_api_key",
            "nowpayments_ipn_secret",
        ):
            if payments.get(key):
                payments[key] = _mask_secret(str(payments[key]))
                payments[f"{key}_configured"] = True
            else:
                payments[f"{key}_configured"] = False
        data["payments"] = payments
        return data

    def get_payments(self) -> dict[str, Any]:
        return dict(self.get_all().get("payments") or {})

    def get_social(self) -> dict[str, Any]:
        return dict(self.get_all().get("social") or {})

    def get_public(self) -> dict[str, Any]:
        """Safe payload for landing/nav (no secret keys)."""
        data = self.get_all()
        payments = data.get("payments") or {}
        return {
            "social": data.get("social") or {},
            "payments": {
                "stripe_enabled": bool(payments.get("stripe_enabled", True)),
                "crypto_enabled": bool(payments.get("crypto_enabled", True)),
                "usdt_trc20_address": payments.get("usdt_trc20_address") or "",
                "usdt_bep20_address": payments.get("usdt_bep20_address") or "",
                "stripe_configured": bool(str(payments.get("stripe_secret_key") or "").strip()),
                "crypto_configured": bool(str(payments.get("nowpayments_api_key") or "").strip()),
            },
        }

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            current = self._read_raw(db)
            incoming = patch or {}

            if isinstance(incoming.get("payments"), dict):
                pay = dict(current.get("payments") or {})
                for key, value in incoming["payments"].items():
                    if key.endswith("_configured"):
                        continue
                    # Keep previous secret when masked placeholder is posted back
                    if key in {
                        "stripe_secret_key",
                        "stripe_webhook_secret",
                        "nowpayments_api_key",
                        "nowpayments_ipn_secret",
                    }:
                        text = str(value or "").strip()
                        if not text or "••••" in text:
                            continue
                        pay[key] = sanitize_text(text, max_len=500)
                    elif key in {"stripe_enabled", "crypto_enabled"}:
                        pay[key] = bool(value)
                    else:
                        pay[key] = sanitize_text(str(value or ""), max_len=500)
                current["payments"] = pay

            if isinstance(incoming.get("social"), dict):
                social = dict(current.get("social") or {})
                for key in ("facebook", "youtube", "instagram", "linkedin"):
                    if key in incoming["social"]:
                        social[key] = sanitize_text(str(incoming["social"].get(key) or ""), max_len=500)
                current["social"] = social

            row = db.get(Setting, SETTINGS_KEY)
            payload = json.dumps(current)
            if row:
                row.value = payload
                row.updated_at = _utc_now()
            else:
                db.add(Setting(key=SETTINGS_KEY, value=payload, updated_at=_utc_now()))
            db.commit()
        finally:
            db.close()

        # Hot-reload payment engine credentials
        try:
            from payments import payments

            payments.reload_credentials()
        except Exception:
            pass
        return self.get_all(mask_secrets=True)


admin_settings = AdminSettings()
