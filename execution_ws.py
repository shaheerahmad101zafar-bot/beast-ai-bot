"""
Binance Futures WebSocket API execution pipe.

Uses the WS trading endpoint when credentials are available; otherwise
returns a deterministic mock response so the rest of the runtime can remain
stable in demo deployments.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

from dotenv import load_dotenv
import websockets

import config
from rate_limiter import binance_bucket
from time_sync import time_sync


class BinanceWsExecutionClient:
    def __init__(self, url: str | None = None) -> None:
        load_dotenv()
        self.url = url or os.getenv("BINANCE_FUTURES_TRADE_WS", "wss://ws-fapi.binance.com/ws-fapi/v1")
        self.api_key = os.getenv("BINANCE_API_KEY", "").strip()
        self.api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        self.last_latency_ms: float | None = None
        self.last_response: dict[str, Any] | None = None

    @property
    def live_ready(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _sign(self, params: dict[str, Any]) -> str:
        query = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return hmac.new(self.api_secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: float,
        reduce_only: bool = False,
        client_order_id: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        client_id = client_order_id or f"beast-{uuid.uuid4().hex[:10]}"
        await binance_bucket.acquire(1)
        if not self.live_ready:
            latency = (time.perf_counter() - started) * 1000
            self.last_latency_ms = latency
            self.last_response = {
                "mode": "mock",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "reduce_only": reduce_only,
            }
            return {
                "ok": True,
                "mode": "mock",
                "clientOrderId": client_id,
                "symbol": symbol,
                "side": side,
                "origQty": quantity,
                "reduceOnly": reduce_only,
                "latency_ms": round(latency, 3),
            }

        params = {
            "apiKey": self.api_key,
            "newClientOrderId": client_id,
            "quantity": f"{quantity:.8f}",
            "reduceOnly": "true" if reduce_only else "false",
            "side": side,
            "symbol": symbol.replace("/", ""),
            "timestamp": time_sync.now_ms(),
            "type": "MARKET",
        }
        params["signature"] = self._sign(params)
        payload = {"id": client_id, "method": "order.place", "params": params}
        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20, close_timeout=5) as ws:
            await ws.send(json.dumps(payload))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
        data = json.loads(raw)
        latency = (time.perf_counter() - started) * 1000
        self.last_latency_ms = latency
        self.last_response = data
        return {"ok": True, "mode": "live_ws", "latency_ms": round(latency, 3), "response": data}

    def status(self) -> dict[str, Any]:
        return {
            "ready": self.live_ready,
            "url": self.url,
            "last_latency_ms": self.last_latency_ms,
            "last_response": self.last_response,
        }


execution_ws = BinanceWsExecutionClient()
