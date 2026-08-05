"""
Beast AI — User movement / activity audit log for Super-Admin.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal, User, UserActivity
from security import sanitize_text


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def log_activity(
    *,
    user_id: int | None,
    email: str | None,
    action: str,
    detail: str = "",
    ip: str | None = None,
    user_agent: str | None = None,
    meta: dict[str, Any] | None = None,
    db: Session | None = None,
) -> None:
    """Persist a user movement row. Safe to call from request handlers."""
    owns = db is None
    session = db or SessionLocal()
    try:
        row = UserActivity(
            user_id=user_id,
            email=sanitize_text((email or "").strip().lower(), max_len=255) or None,
            action=sanitize_text(action, max_len=64) or "event",
            detail=sanitize_text(detail or "", max_len=500),
            ip_address=sanitize_text(ip or "", max_len=64) or None,
            user_agent=sanitize_text(user_agent or "", max_len=255) or None,
            meta_json=__import__("json").dumps(meta or {}),
            created_at=_utc_now(),
        )
        session.add(row)
        if user_id:
            user = session.get(User, user_id)
            if user:
                user.last_seen_at = _utc_now()
        session.commit()
    except Exception:
        session.rollback()
    finally:
        if owns:
            session.close()


def list_activities(
    db: Session,
    *,
    limit: int = 200,
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    q = select(UserActivity).order_by(UserActivity.created_at.desc()).limit(limit)
    if user_id is not None:
        q = select(UserActivity).where(UserActivity.user_id == user_id).order_by(
            UserActivity.created_at.desc()
        ).limit(limit)
    rows = db.scalars(q).all()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "user_id": r.user_id,
                "email": r.email,
                "action": r.action,
                "detail": r.detail,
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    return out
