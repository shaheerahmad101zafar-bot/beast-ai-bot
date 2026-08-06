"""
Beast AI institutional API routes (webhooks + ledger export).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_db, user_to_public
from database import User
from ledger_exporter import ledger_exporter
from webhook_manager import webhook_manager

router = APIRouter(tags=["institutional"])


class WebhookKeyRotateRequest(BaseModel):
    rotate: bool = Field(default=False)


@router.get("/api/webhook/key")
async def api_webhook_key(
    rotate: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    key = webhook_manager.ensure_user_key(db, user, rotate=rotate)
    return {
        "ok": True,
        "webhook_key": key,
        "endpoint": f"/api/v1/webhook/{key}",
        "user": user_to_public(user),
    }


@router.post("/api/v1/webhook/{user_key}")
async def api_external_webhook(
    user_key: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = webhook_manager.resolve_user(db, user_key)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid webhook key")

    raw = await request.body()
    sig = request.headers.get("X-Signature") or request.headers.get("X-Hub-Signature-256")
    if not webhook_manager.verify_optional_hmac(raw, sig, str(user.webhook_key or "")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid JSON payload: {exc}") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    result = webhook_manager.execute_alert(user=user, payload=payload)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Webhook rejected")
    return result


@router.get("/api/export/trades.csv")
async def api_export_trades_csv(user: User = Depends(get_current_user)) -> Response:
    content = ledger_exporter.build_csv()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="beast_ai_trade_ledger.csv"',
            "X-User-Id": str(user.id),
        },
    )


@router.get("/api/export/trades.pdf")
async def api_export_trades_pdf(user: User = Depends(get_current_user)) -> StreamingResponse:
    pdf_bytes = ledger_exporter.build_pdf()
    return StreamingResponse(
        iter([pdf_bytes]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="beast_ai_trade_ledger.pdf"',
            "X-User-Id": str(user.id),
        },
    )
