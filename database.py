"""
Beast AI Trading Bot — Phase 8 SQLite / SQLAlchemy Database Layer
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

import config


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    address: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    country: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    auth_provider: Mapped[str] = mapped_column(String(32), default="email", nullable=False)
    oauth_subject: Mapped[str | None] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    plan: Mapped[str] = mapped_column(String(32), default="pro", nullable=False)
    subscription_status: Mapped[str] = mapped_column(String(32), default="trialing", nullable=False)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    payment_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    api_keys: Mapped[list[UserApiKey]] = relationship(back_populates="user", cascade="all, delete-orphan")
    portfolio: Mapped[UserPortfolio | None] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
    )
    payments: Mapped[list[PaymentLog]] = relationship(back_populates="user", cascade="all, delete-orphan")
    activities: Mapped[list["UserActivity"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )


class UserApiKey(Base):
    __tablename__ = "user_api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(String(120), default="Exchange")
    api_key_enc: Mapped[str] = mapped_column(Text, nullable=False)
    api_secret_enc: Mapped[str] = mapped_column(Text, nullable=False)
    passphrase_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="follower")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    user: Mapped[User] = relationship(back_populates="api_keys")


class UserPortfolio(Base):
    __tablename__ = "user_portfolios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    watchlist_json: Mapped[str] = mapped_column(
        Text,
        default='["BTC/USDT","ETH/USDT","SOL/USDT"]',
    )
    equity: Mapped[float] = mapped_column(Float, default=1000.0)
    realized_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    user: Mapped[User] = relationship(back_populates="portfolio")


class Setting(Base):
    """Key/value JSON settings store for Super-Admin dynamic configuration."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class UserActivity(Base):
    """Every user movement for Super-Admin audit (login, signup, trading, billing…)."""

    __tablename__ = "user_activities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    detail: Mapped[str] = mapped_column(String(500), default="")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now, index=True)

    user: Mapped[User | None] = relationship(back_populates="activities")


class PaymentLog(Base):
    __tablename__ = "payment_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    amount_usd: Mapped[float] = mapped_column(Float, default=0.0)
    gateway: Mapped[str] = mapped_column(String(32), default="stripe")
    status: Mapped[str] = mapped_column(String(32), default="completed")
    tier: Mapped[str] = mapped_column(String(32), default="pro")
    external_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)

    user: Mapped[User | None] = relationship(back_populates="payments")


engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False},
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def _ensure_user_columns() -> None:
    """SQLite-safe additive migrations for subscription + admin fields."""
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("users")}
    alters = {
        "subscription_status": "ALTER TABLE users ADD COLUMN subscription_status VARCHAR(32) DEFAULT 'trialing'",
        "stripe_customer_id": "ALTER TABLE users ADD COLUMN stripe_customer_id VARCHAR(120)",
        "stripe_subscription_id": "ALTER TABLE users ADD COLUMN stripe_subscription_id VARCHAR(120)",
        "payment_provider": "ALTER TABLE users ADD COLUMN payment_provider VARCHAR(32)",
        "subscription_expires_at": "ALTER TABLE users ADD COLUMN subscription_expires_at DATETIME",
        "is_admin": "ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0",
        "full_name": "ALTER TABLE users ADD COLUMN full_name VARCHAR(120) DEFAULT ''",
        "phone": "ALTER TABLE users ADD COLUMN phone VARCHAR(40) DEFAULT ''",
        "address": "ALTER TABLE users ADD COLUMN address VARCHAR(255) DEFAULT ''",
        "country": "ALTER TABLE users ADD COLUMN country VARCHAR(80) DEFAULT ''",
        "auth_provider": "ALTER TABLE users ADD COLUMN auth_provider VARCHAR(32) DEFAULT 'email'",
        "oauth_subject": "ALTER TABLE users ADD COLUMN oauth_subject VARCHAR(255)",
        "avatar_url": "ALTER TABLE users ADD COLUMN avatar_url VARCHAR(512)",
        "last_login_at": "ALTER TABLE users ADD COLUMN last_login_at DATETIME",
        "last_seen_at": "ALTER TABLE users ADD COLUMN last_seen_at DATETIME",
    }
    with engine.begin() as conn:
        for name, sql in alters.items():
            if name not in existing:
                conn.execute(text(sql))


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _ensure_user_columns()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
