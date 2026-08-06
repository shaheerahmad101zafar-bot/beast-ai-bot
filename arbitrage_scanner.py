"""
Cross-exchange arbitrage monitor.

Tracks Binance vs Bybit futures prices and surfaces spread opportunities.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

import websockets


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class ArbitrageScanner:
    def __init__(self) -> None:
        self.symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.latest: dict[str, dict[str, float]] = {}
        self.opportunities: list[dict[str, Any]] = []

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="arbitrage-scanner")

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
                await asyncio.gather(self._poll_binance(), self._poll_bybit())
                self._recompute()
            except Exception:
                pass
            await asyncio.sleep(5)

    async def _poll_binance(self) -> None:
        streams = "/".join(f"{sym.lower()}@markPrice@1s" for sym in self.symbols)
        url = f"wss://fstream.binance.com/stream?streams={streams}"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=6)
            msg = json.loads(raw)
            data = msg.get("data") or {}
            sym = str(data.get("s") or "")
            price = float(data.get("p") or 0.0)
            if sym and price > 0:
                self.latest.setdefault(sym, {})["binance"] = price

    async def _poll_bybit(self) -> None:
        url = "wss://stream.bybit.com/v5/public/linear"
        async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(json.dumps({"op": "subscribe", "args": [f"tickers.{sym}" for sym in self.symbols]}))
            raw = await asyncio.wait_for(ws.recv(), timeout=6)
            msg = json.loads(raw)
            for row in msg.get("data") or []:
                sym = str(row.get("symbol") or "")
                price = float(row.get("lastPrice") or 0.0)
                if sym and price > 0:
                    self.latest.setdefault(sym, {})["bybit"] = price

    def _recompute(self) -> None:
        opps: list[dict[str, Any]] = []
        for sym, row in self.latest.items():
            b = float(row.get("binance") or 0.0)
            y = float(row.get("bybit") or 0.0)
            if b <= 0 or y <= 0:
                continue
            spread_pct = ((b - y) / ((b + y) / 2.0)) * 100
            if abs(spread_pct) >= 0.15:
                opps.append(
                    {
                        "symbol": sym,
                        "binance": round(b, 6),
                        "bybit": round(y, 6),
                        "spread_pct": round(spread_pct, 4),
                        "buy_exchange": "BYBIT" if spread_pct > 0 else "BINANCE",
                        "sell_exchange": "BINANCE" if spread_pct > 0 else "BYBIT",
                        "ts": _utc_now(),
                    }
                )
        self.opportunities = opps[:20]

    def snapshot(self) -> dict[str, Any]:
        return {
            "symbols": self.symbols,
            "latest": self.latest,
            "opportunities": self.opportunities,
            "updated_at": _utc_now(),
        }


arbitrage_scanner = ArbitrageScanner()
