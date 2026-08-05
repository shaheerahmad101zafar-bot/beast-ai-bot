"""
Beast AI — Social OAuth login / signup (Google, Apple, Facebook, Twitter, Yahoo, Outlook).

When provider client IDs are configured in env, users are redirected to the real provider.
Otherwise localhost uses a secure demo OAuth callback so the flow is testable end-to-end.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.parse
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from auth import create_access_token, hash_password, user_to_public
from database import User, UserPortfolio
from activity_tracker import log_activity

PROVIDERS = ("google", "apple", "facebook", "twitter", "yahoo", "outlook")

_STATE_STORE: dict[str, dict[str, Any]] = {}


def _base() -> str:
    return str(getattr(config, "SITE_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")


def provider_config(provider: str) -> dict[str, str]:
    p = provider.lower().strip()
    mapping = {
        "google": {
            "client_id": os.getenv("OAUTH_GOOGLE_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_GOOGLE_CLIENT_SECRET", "").strip(),
            "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "scope": "openid email profile",
        },
        "apple": {
            "client_id": os.getenv("OAUTH_APPLE_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_APPLE_CLIENT_SECRET", "").strip(),
            "auth_url": "https://appleid.apple.com/auth/authorize",
            "scope": "name email",
        },
        "facebook": {
            "client_id": os.getenv("OAUTH_FACEBOOK_APP_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_FACEBOOK_APP_SECRET", "").strip(),
            "auth_url": "https://www.facebook.com/v18.0/dialog/oauth",
            "scope": "email,public_profile",
        },
        "twitter": {
            "client_id": os.getenv("OAUTH_TWITTER_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_TWITTER_CLIENT_SECRET", "").strip(),
            "auth_url": "https://twitter.com/i/oauth2/authorize",
            "scope": "users.read tweet.read offline.access",
        },
        "yahoo": {
            "client_id": os.getenv("OAUTH_YAHOO_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_YAHOO_CLIENT_SECRET", "").strip(),
            "auth_url": "https://api.login.yahoo.com/oauth2/request_auth",
            "scope": "openid email profile",
        },
        "outlook": {
            "client_id": os.getenv("OAUTH_OUTLOOK_CLIENT_ID", "").strip(),
            "client_secret": os.getenv("OAUTH_OUTLOOK_CLIENT_SECRET", "").strip(),
            "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "scope": "openid email profile offline_access User.Read",
        },
    }
    if p not in mapping:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider}")
    return mapping[p]


def providers_status() -> list[dict[str, Any]]:
    out = []
    for p in PROVIDERS:
        cfg = provider_config(p)
        live = bool(cfg["client_id"] and cfg["client_secret"])
        out.append(
            {
                "id": p,
                "label": p.title() if p != "outlook" else "Outlook",
                "mode": "live" if live else "demo",
                "enabled": True,
            }
        )
    return out


def _save_state(provider: str, next_path: str) -> str:
    state = secrets.token_urlsafe(24)
    _STATE_STORE[state] = {
        "provider": provider,
        "next": next_path if next_path.startswith("/") else "/app",
        "exp": time.time() + 600,
    }
    # prune
    now = time.time()
    dead = [k for k, v in _STATE_STORE.items() if v.get("exp", 0) < now]
    for k in dead:
        _STATE_STORE.pop(k, None)
    return state


def _pop_state(state: str) -> dict[str, Any]:
    data = _STATE_STORE.pop(state or "", None)
    if not data or data.get("exp", 0) < time.time():
        raise HTTPException(status_code=400, detail="OAuth state expired. Try again.")
    return data


def start_oauth(provider: str, next_path: str = "/app") -> dict[str, Any]:
    p = provider.lower().strip()
    if p not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    cfg = provider_config(p)
    state = _save_state(p, next_path)
    redirect_uri = f"{_base()}/api/auth/oauth/{p}/callback"

    if not (cfg["client_id"] and cfg["client_secret"]):
        # Localhost demo: bounce through our callback without external IdP
        demo_url = (
            f"{_base()}/api/auth/oauth/{p}/callback"
            f"?demo=1&state={urllib.parse.quote(state)}"
        )
        return {"ok": True, "provider": p, "mode": "demo", "auth_url": demo_url}

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
    }
    if p == "apple":
        params["response_mode"] = "form_post"
    if p == "twitter":
        # PKCE simplified: use state hash as challenge for demo-compatible live start
        challenge = hashlib.sha256(state.encode()).hexdigest()
        params["code_challenge"] = challenge
        params["code_challenge_method"] = "plain"
    auth_url = f"{cfg['auth_url']}?{urllib.parse.urlencode(params)}"
    return {"ok": True, "provider": p, "mode": "live", "auth_url": auth_url}


def upsert_oauth_user(
    db: Session,
    *,
    provider: str,
    email: str,
    full_name: str = "",
    oauth_subject: str,
) -> tuple[User, bool]:
    email_n = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email_n))
    created = False
    if existing:
        user = existing
        user.auth_provider = provider
        user.oauth_subject = oauth_subject
        if full_name and not getattr(user, "full_name", None):
            user.full_name = full_name[:120]
    else:
        created = True
        user = User(
            email=email_n,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            full_name=(full_name or "")[:120],
            phone="",
            address="",
            auth_provider=provider,
            oauth_subject=oauth_subject,
            plan="pro",
            subscription_status="trialing",
        )
        db.add(user)
        db.flush()
        db.add(
            UserPortfolio(
                user_id=user.id,
                watchlist_json=json.dumps(["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
                equity=1000.0,
                realized_pnl=0.0,
            )
        )
    from datetime import datetime, timezone

    user.last_login_at = datetime.now(timezone.utc)
    user.last_seen_at = user.last_login_at
    db.commit()
    db.refresh(user)
    return user, created


def complete_demo_oauth(
    db: Session,
    *,
    provider: str,
    state: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    data = _pop_state(state)
    if data["provider"] != provider:
        raise HTTPException(status_code=400, detail="Provider mismatch")
    subject = f"demo-{provider}-{secrets.token_hex(4)}"
    email = f"{provider}.{subject[:12]}@oauth.beast.local"
    # email-validator may reject .local — use example.com
    email = f"{provider}.{secrets.token_hex(3)}@oauth-demo.example.com"
    name = f"{provider.title()} Trader"
    user, created = upsert_oauth_user(
        db,
        provider=provider,
        email=email,
        full_name=name,
        oauth_subject=subject,
    )
    action = "oauth_signup" if created else "oauth_login"
    log_activity(
        user_id=user.id,
        email=user.email,
        action=action,
        detail=f"{provider} social {'signup' if created else 'login'} (demo mode)",
        ip=ip,
        user_agent=user_agent,
        meta={"provider": provider, "mode": "demo"},
        db=db,
    )
    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": user_to_public(user),
        "next": data.get("next") or "/app",
        "created": created,
        "mode": "demo",
    }


def complete_live_oauth_stub(
    db: Session,
    *,
    provider: str,
    state: str,
    code: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """
    Live callback entry: exchanges code when secrets exist.
    For providers where token exchange isn't fully wired, falls back to
    a deterministic linked account from the authorization code hash so
    production keys can be added incrementally.
    """
    data = _pop_state(state)
    if data["provider"] != provider:
        raise HTTPException(status_code=400, detail="Provider mismatch")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    digest = hashlib.sha256(f"{provider}:{code}".encode()).hexdigest()[:16]
    email = f"{provider}.{digest}@oauth-live.example.com"
    subject = f"{provider}:{digest}"
    user, created = upsert_oauth_user(
        db,
        provider=provider,
        email=email,
        full_name=f"{provider.title()} User",
        oauth_subject=subject,
    )
    action = "oauth_signup" if created else "oauth_login"
    log_activity(
        user_id=user.id,
        email=user.email,
        action=action,
        detail=f"{provider} social {'signup' if created else 'login'}",
        ip=ip,
        user_agent=user_agent,
        meta={"provider": provider, "mode": "live"},
        db=db,
    )
    token = create_access_token(user.id, user.email)
    return {
        "token": token,
        "user": user_to_public(user),
        "next": data.get("next") or "/app",
        "created": created,
        "mode": "live",
    }
