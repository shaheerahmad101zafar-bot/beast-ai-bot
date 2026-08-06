"""
Beast AI notifications orchestration.

Centralizes Telegram execution/TP/SL alerts so trade events can trigger
webhook-style messaging from one place.
"""

from __future__ import annotations

from typing import Any

from telegram_bot import telegram_notifier


class NotificationRouter:
    def notify_order_execution(self, trade: dict[str, Any]) -> dict[str, Any]:
        return telegram_notifier.notify_order_event(
            "FILLED",
            str(trade.get("pair") or trade.get("symbol") or "UNKNOWN"),
            str(trade.get("direction") or trade.get("signal") or "").upper(),
            float(trade.get("entry_price") or trade.get("price") or 0.0),
            extra=f"Leverage: {trade.get('leverage') or 1}x",
        )

    def notify_order_close(self, trade: dict[str, Any]) -> dict[str, Any]:
        reason = str(trade.get("exit_reason") or "").lower()
        if "tp" in reason:
            event = "TAKE PROFIT"
        elif "sl" in reason or "stop" in reason:
            event = "STOP LOSS"
        else:
            event = "CLOSED"
        extra = f"PnL: ${float(trade.get('pnl_usd') or 0.0):,.2f}"
        return telegram_notifier.notify_order_event(
            event,
            str(trade.get("pair") or trade.get("symbol") or "UNKNOWN"),
            str(trade.get("direction") or "").upper(),
            float(trade.get("exit_price") or trade.get("price") or 0.0),
            extra=extra,
        )


notifications = NotificationRouter()
