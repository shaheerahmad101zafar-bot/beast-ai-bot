"""
Production state hydration on restart.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class StateManager:
    def hydrate(self, bot_service) -> dict[str, Any]:
        portfolio = bot_service.execution.portfolio_snapshot(bot_service._mark_prices)  # noqa: SLF001
        for pos in portfolio.get("positions") or []:
            symbol = str(pos.get("symbol") or "")
            mark = float(pos.get("mark_price") or pos.get("entry_price") or 0.0)
            if symbol and mark > 0:
                bot_service._mark_prices[symbol] = mark  # noqa: SLF001
        return {
            "ok": True,
            "positions": len(portfolio.get("positions") or []),
            "equity": float(portfolio.get("equity") or 0.0),
            "updated_at": _utc_now(),
        }


state_manager = StateManager()
