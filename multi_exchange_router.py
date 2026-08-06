"""
Multi-exchange execution failover router.
"""

from __future__ import annotations

import time
from typing import Any

import config
from execution_ws import BinanceWsExecutionClient


class _MockExchangeClient:
    def __init__(self, name: str) -> None:
        self.name = name
        self.last_latency_ms: float | None = None

    async def place_order(self, **kwargs: Any) -> dict[str, Any]:
        started = time.perf_counter()
        latency = (time.perf_counter() - started) * 1000
        self.last_latency_ms = latency
        return {"ok": True, "mode": "mock", "exchange": self.name, "latency_ms": round(latency, 3), "request": kwargs}


class MultiExchangeRouter:
    def __init__(self) -> None:
        self.clients = {
            "binance": BinanceWsExecutionClient(url=config.BINANCE_FUTURES_TRADE_WS),
            "bybit": _MockExchangeClient("bybit"),
            "okx": _MockExchangeClient("okx"),
        }
        self.primary = "binance"
        self.fallbacks = ["bybit", "okx"]
        self.last_route = self.primary

    async def place_order(self, **kwargs: Any) -> dict[str, Any]:
        order = [self.primary, *self.fallbacks]
        for name in order:
            client = self.clients[name]
            result = await client.place_order(**kwargs)
            latency = float(result.get("latency_ms") or getattr(client, "last_latency_ms", 0.0) or 0.0)
            if result.get("ok") and latency <= 200:
                self.last_route = name
                return {**result, "routed_exchange": name, "region": config.BEST_REGION_NODE}
        self.last_route = order[-1]
        return {**result, "routed_exchange": order[-1], "region": config.BEST_REGION_NODE}

    def status(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "fallbacks": list(self.fallbacks),
            "last_route": self.last_route,
            "region": config.BEST_REGION_NODE,
        }


multi_exchange_router = MultiExchangeRouter()
