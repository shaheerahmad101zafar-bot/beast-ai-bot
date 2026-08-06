"""
Process self-healing and memory garbage daemon.
"""

from __future__ import annotations

import asyncio
import gc
import os
import time
import tracemalloc
from datetime import datetime, timezone
from typing import Any, Callable

try:
    import psutil
except Exception:  # noqa: BLE001
    psutil = None

from sqlalchemy import text

import config
from backup_engine import backup_engine
from database import engine
from websocket_manager import ws_hub


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class SystemHealthDaemon:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._save_fn: Callable[[], None] | None = None
        self._snapshot: dict[str, Any] = {"rss_mb": 0.0, "gc_runs": 0, "updated_at": _utc_now()}

    async def start(self, save_fn: Callable[[], None] | None = None) -> None:
        if self._task and not self._task.done():
            return
        self._save_fn = save_fn
        self._stop.clear()
        tracemalloc.start()
        self._task = asyncio.create_task(self._loop(), name="system-health-daemon")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def snapshot(self) -> dict[str, Any]:
        return dict(self._snapshot)

    async def _loop(self) -> None:
        while not self._stop.is_set():
            self._tick()
            await asyncio.sleep(30)

    def _tick(self) -> None:
        rss_mb = 0.0
        if psutil is not None:
            try:
                rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
            except Exception:
                rss_mb = 0.0
        current, peak = tracemalloc.get_traced_memory()
        acted = False
        if rss_mb >= 450 or current >= 250 * 1024 * 1024:
            gc.collect()
            acted = True
            if self._save_fn:
                try:
                    self._save_fn()
                except Exception:
                    pass
            self._snapshot["gc_runs"] = int(self._snapshot.get("gc_runs") or 0) + 1
        self._snapshot = {
            **self._snapshot,
            "rss_mb": round(rss_mb, 2),
            "heap_mb": round(current / (1024 * 1024), 2),
            "peak_heap_mb": round(peak / (1024 * 1024), 2),
            "acted": acted,
            "updated_at": _utc_now(),
        }


system_health = SystemHealthDaemon()


def _utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def measure_db_latency_ms() -> float:
    started = time.perf_counter()
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return round((time.perf_counter() - started) * 1000.0, 3)


def collect_system_health() -> dict[str, Any]:
    cpu_pct = None
    mem: dict[str, Any] = {}
    try:
        if psutil is not None:
            process = psutil.Process(os.getpid())
            cpu_pct = psutil.cpu_percent(interval=0.1)
            proc_cpu = process.cpu_percent(interval=0.0)
            vm = psutil.virtual_memory()
            pmem = process.memory_info()
            mem = {
                "system_total_mb": round(vm.total / (1024 * 1024), 1),
                "system_used_mb": round(vm.used / (1024 * 1024), 1),
                "system_percent": vm.percent,
                "process_rss_mb": round(pmem.rss / (1024 * 1024), 2),
                "process_cpu_percent": proc_cpu,
            }
    except Exception as exc:  # noqa: BLE001
        mem = {"error": str(exc)}
    return {
        "ok": True,
        "ts": _utc(),
        "cpu": {
            "system_percent": cpu_pct,
            "process_percent": mem.get("process_cpu_percent"),
        },
        "memory": mem,
        "websockets": {
            "market_clients": ws_hub.manager.client_count("market"),
            "bot_clients": ws_hub.manager.client_count("bot-status"),
            "binance_connected": ws_hub.listener.connected,
            "binance_base": ws_hub.listener.active_base,
            "total_clients": ws_hub.manager.client_count(),
        },
        "database": {
            "latency_ms": measure_db_latency_ms(),
            "url": config.DATABASE_URL.split("///")[-1] if "///" in config.DATABASE_URL else "sqlite",
        },
        "backup": backup_engine.status(),
        "daemon": system_health.snapshot(),
        "process": {
            "pid": os.getpid(),
            "version": "14.0.0",
        },
    }
