"""
Secure TradingView / external alert webhook ingestion.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from typing import Any

from sqlalchemy.orm import Session

import config
from bot_service import bot_service
from database import User


class WebhookManager:
    """Resolve user webhook keys and execute paper/live orders from alerts."""

    def ensure_user_key(self, db: Session, user: User, *, rotate: bool = False) -> str:
        current = str(getattr(user, "webhook_key", None) or "").strip()
        if current and not rotate:
            return current
        key = secrets.token_urlsafe(24)
        user.webhook_key = key
        db.add(user)
        db.commit()
        db.refresh(user)
        return key

    def resolve_user(self, db: Session, user_key: str) -> User | None:
        key = str(user_key or "").strip()
        if not key or len(key) < 16:
            return None
        return db.query(User).filter(User.webhook_key == key).first()

    @staticmethod
    def _normalize_symbol(raw: str) -> str:
        s = str(raw or "").upper().replace("-", "/").replace(":", "/").strip()
        if not s:
            return "BTC/USDT"
        if "/" not in s and s.endswith("USDT"):
            return f"{s[:-4]}/USDT"
        if "/" not in s:
            return f"{s}/USDT"
        parts = [p for p in s.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[0]}/USDT" if parts[1] in {"USDT", "USD"} else f"{parts[0]}/{parts[1]}"
        return s

    @staticmethod
    def _parse_side(payload: dict[str, Any]) -> str | None:
        for key in ("side", "signal", "action", "order_action", "strategy.order.action"):
            val = str(payload.get(key) or "").upper().strip()
            if val in {"BUY", "LONG", "ENTER_LONG"}:
                return "BUY"
            if val in {"SELL", "SHORT", "ENTER_SHORT"}:
                return "SELL"
            if val in {"CLOSE", "EXIT", "FLAT"}:
                return "CLOSE"
        return None

    def parse_tradingview_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        symbol = self._normalize_symbol(
            str(payload.get("symbol") or payload.get("ticker") or payload.get("pair") or "BTCUSDT")
        )
        side = self._parse_side(payload)
        price = float(
            payload.get("price")
            or payload.get("close")
            or payload.get("mark_price")
            or bot_service._mark_prices.get(symbol)  # noqa: SLF001
            or 0.0
        )
        leverage = float(payload.get("leverage") or 5.0)
        size = float(payload.get("size") or payload.get("qty") or payload.get("quantity") or 0.0)
        conf = float(payload.get("confidence") or payload.get("confidence_score") or 75.0)
        reason = str(
            payload.get("reason")
            or payload.get("comment")
            or payload.get("strategy")
            or "TradingView webhook alert"
        )
        return {
            "symbol": symbol,
            "side": side,
            "price": price,
            "leverage": max(1.0, min(20.0, leverage)),
            "size": size,
            "confidence": conf,
            "reason": reason,
            "raw": payload,
        }

    def execute_alert(self, *, user: User, payload: dict[str, Any]) -> dict[str, Any]:
        parsed = self.parse_tradingview_payload(payload)
        side = parsed.get("side")
        symbol = str(parsed["symbol"])
        if not side:
            return {"ok": False, "detail": "Missing side/signal (BUY/SELL/CLOSE)", "parsed": parsed}

        mark = float(parsed["price"] or 0.0)
        if mark <= 0:
            mark = float(bot_service._mark_prices.get(symbol) or 0.0)  # noqa: SLF001
        if mark <= 0:
            return {"ok": False, "detail": f"No market price for {symbol}", "parsed": parsed}

        if side == "CLOSE":
            if not bot_service.execution.has_position(symbol):
                return {"ok": True, "action": "noop", "detail": "No open position to close", "symbol": symbol}
            trade = bot_service.execution.close_position(symbol, mark, "Webhook Close")
            return {"ok": True, "action": "close", "trade": trade, "user_id": user.id}

        if bot_service.execution.has_position(symbol):
            return {
                "ok": False,
                "detail": f"Position already open for {symbol}",
                "symbol": symbol,
                "user_id": user.id,
            }

        # Size from risk manager when qty omitted
        from risk_manager import RiskManager

        equity = max(bot_service.execution.equity(bot_service._mark_prices), 1.0)  # noqa: SLF001
        risk = RiskManager(account_balance=equity)
        sl_pct = float(config.DEFAULT_STOP_LOSS)
        tp_pct = float(config.DEFAULT_TAKE_PROFIT)
        if side == "BUY":
            stop = mark * (1.0 - sl_pct)
            take = mark * (1.0 + tp_pct)
        else:
            stop = mark * (1.0 + sl_pct)
            take = mark * (1.0 - tp_pct)

        atr_proxy = mark * max(sl_pct, 0.008)
        sized = risk.evaluate_trade(
            {
                "entry_price": mark,
                "stop_loss_price": stop,
                "atr": atr_proxy,
            }
        )
        size = float(parsed["size"] or sized["position_size_units"])
        leverage = min(float(parsed["leverage"]), float(sized["leverage"]))

        order = bot_service.execution.place_order(
            symbol=symbol,
            signal=side,
            size_units=size,
            leverage=leverage,
            market_price=mark,
            stop_loss=stop,
            take_profit=take,
            metadata={
                "ai_reasoning": f"Webhook: {parsed['reason']}",
                "atr_pct_frac": sized.get("atr_pct_frac"),
                "source": "tradingview_webhook",
                "user_id": user.id,
            },
        )
        return {
            "ok": True,
            "action": "open",
            "order": order,
            "risk": sized,
            "user_id": user.id,
            "received_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }

    @staticmethod
    def verify_optional_hmac(body: bytes, signature: str | None, secret: str) -> bool:
        if not signature or not secret:
            return True
        digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature.strip().lower().removeprefix("sha256="))


webhook_manager = WebhookManager()
