"""
Beast AI Trading Bot — Phase 13 Security & Rate-Limiting Layer

Auth brute-force protection, CMS/admin input sanitization, and secure headers.
"""

from __future__ import annotations

import os
import re
import time
from collections import defaultdict, deque
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from models import decrypt_api_secret, encrypt_api_secret
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

import config

# Auth endpoints subject to strict rate limits
AUTH_PATHS = {
    "/api/auth/login",
    "/api/auth/signup",
}

# Broader API soft limit (requests / window)
API_PREFIX = "/api/"

_SCRIPT_RE = re.compile(r"<\s*script[^>]*>.*?<\s*/\s*script\s*>", re.I | re.S)
_EVENT_RE = re.compile(r"\son\w+\s*=\s*([\"']).*?\1", re.I | re.S)
_JS_URL_RE = re.compile(r"javascript\s*:", re.I)
_SQL_META_RE = re.compile(r"(--|/\*|\*/|;|\b(DROP|ALTER|EXEC|UNION|INSERT|DELETE|UPDATE)\b)", re.I)


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host or "unknown"
    return "unknown"


class RateLimiter:
    """Simple sliding-window rate limiter (in-process)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str, *, limit: int, window_seconds: float) -> tuple[bool, int]:
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry = int(max(1, window_seconds - (now - bucket[0])))
            return False, retry
        bucket.append(now)
        return True, 0


rate_limiter = RateLimiter()


def sanitize_text(value: str, *, max_len: int = 8000) -> str:
    """Neutralize XSS / script payloads and trim length."""
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\x00", "")
    text = _SCRIPT_RE.sub("", text)
    text = _EVENT_RE.sub("", text)
    text = _JS_URL_RE.sub("", text)
    # Soft SQL meta neutralization for free-text fields (ORM remains parameterized)
    text = text.replace(";", " ")
    text = _SQL_META_RE.sub(" ", text)
    if len(text) > max_len:
        text = text[:max_len]
    return text.strip()


def sanitize_value(value: Any, *, max_len: int = 8000) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, max_len=max_len)
    if isinstance(value, list):
        return [sanitize_value(v, max_len=max_len) for v in value[:200]]
    if isinstance(value, dict):
        return {
            sanitize_text(str(k), max_len=120): sanitize_value(v, max_len=max_len)
            for k, v in list(value.items())[:200]
        }
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return sanitize_text(str(value), max_len=max_len)


def sanitize_cms_content(content: dict[str, Any]) -> dict[str, Any]:
    """Sanitize CMS/admin content payloads before persistence."""
    if not isinstance(content, dict):
        return {}
    rates = content.get("pricing_rates") if isinstance(content.get("pricing_rates"), dict) else {}
    cleaned = sanitize_value(content)
    if not isinstance(cleaned, dict):
        return {}
    if rates:
        out_rates: dict[str, float] = {}
        for key in ("starter", "pro", "vip"):
            try:
                out_rates[key] = float(rates.get(key))
            except (TypeError, ValueError):
                continue
        if out_rates:
            cleaned["pricing_rates"] = out_rates
    return cleaned


def cors_origins() -> list[str]:
    raw = getattr(config, "CORS_ORIGINS", "") or ""
    origins = [o.strip().rstrip("/") for o in str(raw).split(",") if o.strip()]
    base = str(getattr(config, "SITE_BASE_URL", "http://127.0.0.1:8000")).rstrip("/")
    defaults = [
        base,
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]
    # Render injects RENDER_EXTERNAL_URL at runtime
    render = (os.getenv("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    if render:
        defaults.append(render)
    koyeb = (os.getenv("KOYEB_PUBLIC_DOMAIN") or "").strip()
    if koyeb:
        defaults.append(koyeb if koyeb.startswith("http") else f"https://{koyeb}")
    merged: list[str] = []
    for origin in origins + defaults:
        if origin and origin not in merged:
            merged.append(origin)
    return merged


def cors_origin_regex() -> str | None:
    pattern = str(getattr(config, "CORS_ORIGIN_REGEX", "") or "").strip()
    return pattern or None


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        # Frame / content sniffing / referrer hardening
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        response.headers.setdefault("X-XSS-Protection", "0")
        # CSP tuned for local Tailwind/CDN + app assets (tighten further in pure prod builds)
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://unpkg.com; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https:; "
            "media-src 'self' https: blob:; "
            "connect-src 'self' ws: wss: https: http://127.0.0.1:* http://localhost:*; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'"
        )
        response.headers.setdefault("Content-Security-Policy", csp)
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        ip = client_ip(request)

        if path in AUTH_PATHS and request.method.upper() == "POST":
            ok, retry = rate_limiter.allow(
                f"auth:{ip}:{path}",
                limit=int(getattr(config, "AUTH_RATE_LIMIT", 8)),
                window_seconds=float(getattr(config, "AUTH_RATE_WINDOW_SECONDS", 900)),
            )
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Too many authentication attempts. Try again later.",
                        "retry_after_seconds": retry,
                    },
                    headers={"Retry-After": str(retry)},
                )

        if path.startswith(API_PREFIX) and request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            ok, retry = rate_limiter.allow(
                f"apiwrite:{ip}",
                limit=int(getattr(config, "API_WRITE_RATE_LIMIT", 120)),
                window_seconds=float(getattr(config, "API_WRITE_RATE_WINDOW_SECONDS", 60)),
            )
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "API rate limit exceeded.",
                        "retry_after_seconds": retry,
                    },
                    headers={"Retry-After": str(retry)},
                )

        return await call_next(request)


def configure_security(app: FastAPI) -> None:
    """Attach CORS + security middleware to the FastAPI app."""
    origins = cors_origins()
    kwargs: dict[str, Any] = {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "X-Requested-With"],
        "expose_headers": ["Retry-After"],
        "max_age": 600,
    }
    regex = cors_origin_regex()
    if regex:
        kwargs["allow_origin_regex"] = regex
    app.add_middleware(CORSMiddleware, **kwargs)
    # Starlette executes middleware in reverse add order — add headers last so it wraps outer
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)


def origin_host(origin: str) -> str:
    try:
        return urlparse(origin).netloc
    except Exception:
        return origin


def secure_encrypt_api_secret(value: str) -> str:
    return encrypt_api_secret(value)


def secure_decrypt_api_secret(value: str) -> str:
    return decrypt_api_secret(value)
