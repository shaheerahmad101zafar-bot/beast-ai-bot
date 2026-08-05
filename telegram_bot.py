"""
Beast AI Trading Bot — Phase 7 Telegram Signal & Alert Dispatcher

Sends signal, execution, and daily PnL alerts via Telegram Bot API.
Falls back to a local mock outbox when no bot token is configured.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

import config


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class TelegramNotifier:
    """HTTP Telegram notifier with graceful mock mode."""

    def __init__(
        self,
        bot_token: str | None = None,
        chat_id: str | None = None,
        mock_log_path: str | Path = config.TELEGRAM_MOCK_LOG_PATH,
        enabled: bool = config.TELEGRAM_ENABLED,
    ) -> None:
        load_dotenv()
        self.bot_token = (bot_token or os.getenv(config.TELEGRAM_BOT_TOKEN_ENV, "")).strip()
        self.chat_id = (chat_id or os.getenv(config.TELEGRAM_CHAT_ID_ENV, "")).strip()
        self.mock_log_path = Path(mock_log_path)
        self.enabled = bool(enabled)
        self.mode = "live" if (self.bot_token and self.chat_id) else "mock"

    @property
    def is_live(self) -> bool:
        return self.mode == "live"

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": self.mode,
            "chat_configured": bool(self.chat_id),
            "token_configured": bool(self.bot_token),
            "mock_log_path": str(self.mock_log_path),
        }

    def send_message(self, text: str, *, parse_mode: str = "HTML") -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "mode": self.mode, "skipped": True, "reason": "disabled"}

        payload = {
            "timestamp": _utc_now(),
            "text": text,
            "parse_mode": parse_mode,
            "mode": self.mode,
        }

        if self.mode == "mock":
            return self._write_mock(payload)

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            data = resp.json() if resp.content else {}
            ok = resp.ok and bool(data.get("ok"))
            result = {
                "ok": ok,
                "mode": "live",
                "status_code": resp.status_code,
                "response": data,
                "timestamp": payload["timestamp"],
            }
            if not ok:
                # Still record failure locally for debugging
                payload["error"] = data
                self._write_mock(payload)
            return result
        except Exception as exc:  # noqa: BLE001
            payload["error"] = str(exc)
            mock = self._write_mock(payload)
            mock["ok"] = False
            mock["reason"] = str(exc)
            return mock

    def notify_signal(
        self,
        symbol: str,
        signal: str,
        confidence: float,
        price: float | None = None,
    ) -> dict[str, Any]:
        side = "LONG" if signal == "BUY" else "SHORT" if signal == "SELL" else "HOLD"
        price_bit = f" @ <b>{price:,.2f}</b>" if price is not None else ""
        text = (
            f"📡 <b>Beast AI Signal</b>\n"
            f"{symbol} <b>{side}</b> Signal{price_bit}\n"
            f"Confidence: <b>{confidence:.1f}%</b>\n"
            f"{_utc_now()}"
        )
        return self.send_message(text)

    def notify_order_event(
        self,
        event: str,
        symbol: str,
        direction: str,
        price: float,
        extra: str | None = None,
    ) -> dict[str, Any]:
        text = (
            f"⚙️ <b>Order {event}</b>\n"
            f"{symbol} {direction} @ <b>{price:,.4f}</b>\n"
        )
        if extra:
            text += f"{extra}\n"
        text += _utc_now()
        return self.send_message(text)

    def notify_daily_pnl(
        self,
        equity: float,
        daily_pnl: float,
        realized_pnl: float,
        open_positions: int,
    ) -> dict[str, Any]:
        sign = "+" if daily_pnl >= 0 else ""
        text = (
            f"📊 <b>Daily Portfolio Summary</b>\n"
            f"Equity: <b>${equity:,.2f}</b>\n"
            f"Daily PnL: <b>{sign}${daily_pnl:,.2f}</b>\n"
            f"Realized: <b>${realized_pnl:,.2f}</b>\n"
            f"Open positions: <b>{open_positions}</b>\n"
            f"{_utc_now()}"
        )
        return self.send_message(text)

    def _write_mock(self, payload: dict[str, Any]) -> dict[str, Any]:
        history: list[dict[str, Any]] = []
        if self.mock_log_path.exists():
            try:
                history = json.loads(self.mock_log_path.read_text(encoding="utf-8"))
                if not isinstance(history, list):
                    history = []
            except (OSError, json.JSONDecodeError):
                history = []
        history.append(payload)
        history = history[-200:]
        self.mock_log_path.write_text(json.dumps(history, indent=2), encoding="utf-8")
        return {"ok": True, "mode": "mock", "queued": True, "timestamp": payload["timestamp"]}


telegram_notifier = TelegramNotifier()
