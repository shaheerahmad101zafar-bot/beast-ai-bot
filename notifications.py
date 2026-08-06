"""
Beast AI notifications orchestration.

Centralizes Telegram webhook-style alerts for:
  - order execution (FILLED)
  - take-profit hits
  - stop-loss closures
"""

from __future__ import annotations

from typing import Any

from telegram_bot import telegram_notifier


class NotificationRouter:
    def notify_order_execution(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Telegram alert when a new order fills / opens."""
        return telegram_notifier.notify_order_event(
            "FILLED",
            str(trade.get("pair") or trade.get("symbol") or "UNKNOWN"),
            str(trade.get("direction") or trade.get("signal") or "").upper(),
            float(trade.get("entry_price") or trade.get("price") or 0.0),
            extra=f"Leverage: {trade.get('leverage') or 1}x",
        )

    def notify_order_close(self, trade: dict[str, Any]) -> dict[str, Any]:
        """Telegram alert on TP, SL, or generic position close."""
        reason = str(trade.get("exit_reason") or "").lower()
        if "tp" in reason or "take_profit" in reason or "take profit" in reason:
            event = "TAKE PROFIT"
        elif "sl" in reason or "stop" in reason:
            event = "STOP LOSS"
        else:
            event = "CLOSED"
        extra = (
            f"PnL: ${float(trade.get('pnl_usd') or 0.0):,.2f} · "
            f"Reason: {trade.get('exit_reason') or event}"
        )
        return telegram_notifier.notify_order_event(
            event,
            str(trade.get("pair") or trade.get("symbol") or "UNKNOWN"),
            str(trade.get("direction") or "").upper(),
            float(trade.get("exit_price") or trade.get("price") or 0.0),
            extra=extra,
        )


notifications = NotificationRouter()
