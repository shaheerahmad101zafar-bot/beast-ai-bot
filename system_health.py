"""
Beast AI Trading Bot — Phase 13 System Diagnostics Helpers
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

import config
from database import engine
from websocket_manager import ws_hub
from backup_engine import backup_engine


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
        import psutil

        process = psutil.Process(os.getpid())
        cpu_pct = psutil.cpu_percent(interval=0.15)
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

    db_ms = measure_db_latency_ms()
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
            "latency_ms": db_ms,
            "url": config.DATABASE_URL.split("///")[-1] if "///" in config.DATABASE_URL else "sqlite",
        },
        "backup": backup_engine.status(),
        "process": {
            "pid": os.getpid(),
            "version": "14.0.0",
        },
    }
