"""
Compatibility models module + AES-256-GCM helpers.

Keeps legacy imports working while exposing shared SQLAlchemy models and
API-key encryption helpers for SQLite / PostgreSQL / Supabase deployments.

Secrets are encrypted at rest with AES-256-GCM (`encrypt_api_secret`) and
only decrypted in-memory for exchange routing / validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

import config
from database import (
    Base,
    PaymentLog,
    SessionLocal,
    Setting,
    User,
    UserActivity,
    UserApiKey,
    UserPortfolio,
    engine,
    get_db,
    init_db,
)


def _raw_cipher_key() -> bytes:
    raw = os.getenv(config.API_CIPHER_KEY_ENV, "").strip()
    if raw:
        try:
            data = base64.urlsafe_b64decode(raw.encode("utf-8"))
        except Exception:
            data = raw.encode("utf-8")
        digest = hashlib.sha256(data).digest()
        return digest
    path = ".api_cipher_key"
    if os.path.exists(path):
        blob = open(path, "rb").read().strip()
        try:
            data = base64.urlsafe_b64decode(blob)
        except Exception:
            data = blob
        return hashlib.sha256(data).digest()
    seed = secrets.token_bytes(32)
    token = base64.urlsafe_b64encode(seed)
    with open(path, "wb") as fh:
        fh.write(token)
    return hashlib.sha256(seed).digest()


def api_key_cipher() -> AESGCM:
    """AES-256-GCM cipher derived from env/file key."""
    return AESGCM(_raw_cipher_key())


def encrypt_api_secret(payload: dict[str, Any] | str) -> str:
    """Encrypt API secrets with AES-256-GCM and return URL-safe token."""
    blob = payload if isinstance(payload, str) else json.dumps(payload, separators=(",", ":"))
    data = blob.encode("utf-8")
    nonce = secrets.token_bytes(12)
    ct = api_key_cipher().encrypt(nonce, data, None)
    return base64.urlsafe_b64encode(nonce + ct).decode("utf-8")


def decrypt_api_secret(token: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(token.encode("utf-8"))
        nonce, ct = raw[:12], raw[12:]
        data = api_key_cipher().decrypt(nonce, ct, None)
        return data.decode("utf-8")
    except Exception:
        # Backward compatibility for older plain/legacy vault entries.
        return token
