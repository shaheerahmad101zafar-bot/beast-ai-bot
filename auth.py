"""
Beast AI Trading Bot — JWT Authentication + Professional Signup
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
from database import SessionLocal, User, UserPortfolio, get_db
from security import sanitize_text

bearer_scheme = HTTPBearer(auto_error=False)


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=40)
    address: str = Field(min_length=5, max_length=255)
    country: str = Field(default="", max_length=80)

    @field_validator("full_name", "phone", "address", "country")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return sanitize_text(str(value or "").strip(), max_len=255)

    @model_validator(mode="after")
    def passwords_match(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


def _jwt_secret() -> str:
    secret = os.getenv(config.JWT_SECRET_ENV, "").strip()
    if secret:
        return secret
    path = "jwt_dev_secret.txt"
    if os.path.exists(path):
        return open(path, encoding="utf-8").read().strip()
    secret = secrets.token_urlsafe(48)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(secret)
    return secret


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=config.JWT_EXPIRE_HOURS)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=config.JWT_ALGORITHM)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[config.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def user_to_public(user: User) -> dict[str, Any]:
    watchlist = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    equity = 1000.0
    if user.portfolio:
        try:
            watchlist = json.loads(user.portfolio.watchlist_json)
        except json.JSONDecodeError:
            pass
        equity = float(user.portfolio.equity or 1000.0)
    return {
        "id": user.id,
        "email": user.email,
        "full_name": getattr(user, "full_name", "") or "",
        "phone": getattr(user, "phone", "") or "",
        "address": getattr(user, "address", "") or "",
        "country": getattr(user, "country", "") or "",
        "auth_provider": getattr(user, "auth_provider", None) or "email",
        "plan": user.plan,
        "subscription_status": getattr(user, "subscription_status", None) or "trialing",
        "payment_provider": getattr(user, "payment_provider", None),
        "stripe_customer_id": getattr(user, "stripe_customer_id", None),
        "subscription_expires_at": (
            user.subscription_expires_at.isoformat()
            if getattr(user, "subscription_expires_at", None)
            else None
        ),
        "last_login_at": (
            user.last_login_at.isoformat() if getattr(user, "last_login_at", None) else None
        ),
        "last_seen_at": (
            user.last_seen_at.isoformat() if getattr(user, "last_seen_at", None) else None
        ),
        "is_admin": bool(getattr(user, "is_admin", False)),
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "watchlist": watchlist,
        "equity": equity,
    }


def signup_user(
    db: Session,
    *,
    email: str,
    password: str,
    full_name: str,
    phone: str,
    address: str,
    country: str = "",
) -> User:
    email_n = email.strip().lower()
    existing = db.scalar(select(User).where(User.email == email_n))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    now = datetime.now(timezone.utc)
    user = User(
        email=email_n,
        password_hash=hash_password(password),
        full_name=sanitize_text(full_name, max_len=120),
        phone=sanitize_text(phone, max_len=40),
        address=sanitize_text(address, max_len=255),
        country=sanitize_text(country or "", max_len=80),
        auth_provider="email",
        plan="pro",
        subscription_status="trialing",
        last_login_at=now,
        last_seen_at=now,
        created_at=now,
    )
    db.add(user)
    db.flush()
    db.add(
        UserPortfolio(
            user_id=user.id,
            watchlist_json=json.dumps(["BTC/USDT", "ETH/USDT", "SOL/USDT"]),
            equity=1000.0,
            realized_pnl=0.0,
            updated_at=now,
        )
    )
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> User:
    email_n = email.strip().lower()
    user = db.scalar(select(User).where(User.email == email_n))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    now = datetime.now(timezone.utc)
    user.last_login_at = now
    user.last_seen_at = now
    db.commit()
    db.refresh(user)
    return user


def _extract_token(request: Request, creds: HTTPAuthorizationCredentials | None) -> str | None:
    if creds and creds.credentials:
        return creds.credentials
    cookie = request.cookies.get(config.AUTH_COOKIE_NAME)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = _extract_token(request, creds)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(token)
    user_id = int(payload.get("sub") or 0)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def resolve_optional_user(request: Request) -> User | None:
    token = _extract_token(request, None)
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub") or 0)
    except HTTPException:
        return None
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if user:
            # Touch attrs before close so logout/log helpers stay safe
            _ = (user.id, user.email)
            db.expunge(user)
        return user
    finally:
        db.close()


def get_optional_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> User | None:
    token = _extract_token(request, creds)
    if not token:
        return None
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub") or 0)
    except HTTPException:
        return None
    db = SessionLocal()
    try:
        return db.get(User, user_id)
    finally:
        db.close()


def update_user_watchlist(db: Session, user: User, symbols: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for sym in symbols:
        s = str(sym).strip().upper().replace("-", "/")
        if not s or s in seen:
            continue
        if "/" not in s and s.endswith("USDT"):
            s = s[:-4] + "/USDT"
        seen.add(s)
        cleaned.append(s)
    if not cleaned:
        cleaned = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]

    if not user.portfolio:
        user.portfolio = UserPortfolio(user_id=user.id)
        db.add(user.portfolio)
    user.portfolio.watchlist_json = json.dumps(cleaned)
    user.portfolio.updated_at = datetime.now(timezone.utc)
    db.commit()
    return cleaned


def client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()
    ua = request.headers.get("user-agent")
    return ip, ua
