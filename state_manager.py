"""
Production state hydration + local disk fallback ledger.

Persists open positions and wallet balance to `state_backup.json` every
5 seconds so server restarts never lose active trade tracking.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger("beast.state")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class StateManager:
    def __init__(self) -> None:
        self.backup_path = Path(getattr(config, "STATE_BACKUP_PATH", "state_backup.json"))
        self.interval_seconds = float(getattr(config, "STATE_BACKUP_INTERVAL_SECONDS", 5.0))
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.last_backup_at: str | None = None
        self.last_error: str | None = None

    def hydrate(self, bot_service) -> dict[str, Any]:
        # Prefer primary portfolio; fall back to state_backup.json if needed.
        restored_from_backup = False
        if self.backup_path.exists() and not Path(config.PAPER_PORTFOLIO_PATH).exists():
            try:
                with self.backup_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                bot_service.execution.wallet_balance = float(
                    data.get("wallet_balance", bot_service.execution.wallet_balance)
                )
                bot_service.execution.realized_pnl = float(data.get("realized_pnl") or 0.0)
                bot_service.execution.positions = {
                    str(k): v for k, v in (data.get("positions") or {}).items()
                }
                bot_service.execution._save_portfolio()  # noqa: SLF001
                restored_from_backup = True
            except Exception as exc:  # noqa: BLE001
                logger.warning("state_backup hydrate failed: %s", exc)

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
            "restored_from_backup": restored_from_backup,
            "updated_at": _utc_now(),
        }

    def persist(self, bot_service) -> dict[str, Any]:
        with bot_service._lock:  # noqa: SLF001
            snap = bot_service.execution.portfolio_snapshot(bot_service._mark_prices)  # noqa: SLF001
            payload = {
                "mode": snap.get("mode"),
                "updated_at": _utc_now(),
                "wallet_balance": float(snap.get("wallet_balance") or 0.0),
                "available_balance": float(snap.get("available_balance") or 0.0),
                "equity": float(snap.get("equity") or 0.0),
                "realized_pnl": float(snap.get("realized_pnl") or 0.0),
                "positions": {
                    str(p.get("symbol")): p
                    for p in (snap.get("positions") or [])
                    if p.get("symbol")
                },
            }
            bot_service.execution.save()
        with self.backup_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        self.last_backup_at = payload["updated_at"]
        self.last_error = None
        return payload

    async def start(self, bot_service) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(bot_service), name="state-backup-loop")
        logger.info(
            "State backup loop started → %s every %.1fs",
            self.backup_path,
            self.interval_seconds,
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _loop(self, bot_service) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.persist, bot_service)
            except Exception as exc:  # noqa: BLE001
                self.last_error = str(exc)
                logger.warning("state_backup persist failed: %s", exc)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval_seconds)
            except asyncio.TimeoutError:
                continue


state_manager = StateManager()
