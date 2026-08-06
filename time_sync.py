"""
Background Binance server time synchronization.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import requests


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class TimeSyncEngine:
    def __init__(self) -> None:
        self.offset_ms = 0
        self.last_server_time_ms: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="time-sync")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.sync_once)
            except Exception:
                pass
            await asyncio.sleep(300)

    def sync_once(self) -> dict[str, Any]:
        resp = requests.get("https://fapi.binance.com/fapi/v1/time", timeout=8)
        resp.raise_for_status()
        server_ms = int(resp.json().get("serverTime") or 0)
        local_ms = int(time.time() * 1000)
        self.last_server_time_ms = server_ms
        self.offset_ms = server_ms - local_ms
        return self.snapshot()

    def now_ms(self) -> int:
        return int(time.time() * 1000) + int(self.offset_ms)

    def snapshot(self) -> dict[str, Any]:
        return {"offset_ms": int(self.offset_ms), "server_time_ms": self.last_server_time_ms, "updated_at": _utc_now()}


time_sync = TimeSyncEngine()
