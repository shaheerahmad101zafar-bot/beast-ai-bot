"""
Beast AI Trading Bot — Phase 10 WebSocket Streaming Engine

Connection manager + Binance USD-M Futures market stream
(order book / mark price / kline ticks) with fan-out to dashboard clients.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse

import websockets
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

import config
from database import ring_buffer
from fast_json import loads
from network_tuning import apply_global_socket_tuning
from rate_limiter import binance_bucket
from websocket_aggregator import websocket_aggregator

apply_global_socket_tuning()

logger = logging.getLogger("beast.websocket")

Channel = Literal["market", "bot-status"]

# Known-good public USD-M Futures combined-stream host (DNS-stable on most clouds).
_DEFAULT_BINANCE_WS = "wss://fstream.binance.com"
_FALLBACK_BINANCE_WS = "wss://stream.binancefutures.com"


def _is_dns_failure(exc: BaseException) -> bool:
    """True when the failure is hostname/DNS resolution (noisy on some hosts)."""
    if isinstance(exc, socket.gaierror):
        return True
    msg = str(exc).lower()
    needles = (
        "getaddrinfo failed",
        "name or service not known",
        "nodename nor servname",
        "temporary failure in name resolution",
        "failed to resolve",
        "name resolution",
        "dns",
        "[errno 11001]",  # Windows WSAHOST_NOT_FOUND
        "[errno -2]",
        "[errno -3]",
    )
    return any(n in msg for n in needles)


def _host_resolves(ws_base: str) -> bool:
    """Best-effort DNS preflight; failures are logged quietly and skipped."""
    host = urlparse(ws_base).hostname
    if not host:
        return False
    try:
        socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return True
    except OSError as exc:
        logger.info(
            "Binance WS DNS skip %s (%s) — falling back to next endpoint",
            host,
            exc,
        )
        return False


def _binance_ws_bases() -> tuple[str, ...]:
    """Prefer fstream; treat stream.binancefutures.com as optional fallback."""
    primary = getattr(config, "BINANCE_FUTURES_WS", _DEFAULT_BINANCE_WS) or _DEFAULT_BINANCE_WS
    # Always try the stable host first unless env already points there.
    bases = [_DEFAULT_BINANCE_WS, primary, _FALLBACK_BINANCE_WS]
    seen: set[str] = set()
    out: list[str] = []
    for b in bases:
        b = (b or "").rstrip("/")
        if not b or b in seen:
            continue
        seen.add(b)
        out.append(b)
    # Prefer resolvable hosts; if DNS probe fails for all, still return ordered list.
    resolvable = [b for b in out if _host_resolves(b)]
    return tuple(resolvable or out)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class BinanceHttpWeightGuard:
    """Simple rolling-window guard for Binance REST request weight."""

    def __init__(self, per_minute_limit: int = config.BINANCE_HTTP_WEIGHT_LIMIT_PER_MIN) -> None:
        self.per_minute_limit = max(100, int(per_minute_limit))
        self._events: deque[tuple[float, int]] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self, weight: int = 1, label: str = "request") -> None:
        loop = asyncio.get_running_loop()
        await binance_bucket.acquire(weight)
        while True:
            async with self._lock:
                now = loop.time()
                while self._events and now - self._events[0][0] >= 60.0:
                    self._events.popleft()
                used = sum(w for _, w in self._events)
                if used + weight <= self.per_minute_limit:
                    self._events.append((now, weight))
                    return
                wait_s = max(0.05, 60.0 - (now - self._events[0][0]))
                logger.warning(
                    "Binance REST throttle %s delayed %.2fs (used=%s weight=%s limit=%s)",
                    label,
                    wait_s,
                    used,
                    weight,
                    self.per_minute_limit,
                )
            await asyncio.sleep(min(wait_s, 2.0))

    async def request_json(
        self,
        method: str,
        url: str,
        *,
        weight: int = 1,
        label: str = "request",
        params: dict[str, Any] | None = None,
        timeout: float = 12.0,
    ) -> dict[str, Any] | list[Any]:
        """Weight-gated REST call with exponential backoff on 429/500/502/504."""
        import aiohttp

        await self.acquire(weight=weight, label=label)
        delays = (0.4, 0.9, 1.8, 3.5, 7.0)
        last_exc: Exception | None = None
        for attempt, delay in enumerate(delays):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(
                        method.upper(),
                        url,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=timeout),
                    ) as resp:
                        if resp.status in {429, 500, 502, 503, 504}:
                            body = await resp.text()
                            raise RuntimeError(f"Binance HTTP {resp.status}: {body[:180]}")
                        resp.raise_for_status()
                        return await resp.json(content_type=None)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(
                    "Binance REST %s retry %s/%s after error: %s (sleep %.1fs)",
                    label,
                    attempt + 1,
                    len(delays),
                    exc,
                    delay,
                )
                if attempt >= len(delays) - 1:
                    break
                await asyncio.sleep(delay)
                await self.acquire(weight=weight, label=f"{label}:retry")
        raise RuntimeError(f"Binance REST {label} failed after retries: {last_exc}")


async def sync_open_orders_after_reconnect(mark_prices: dict[str, float] | None = None) -> dict[str, Any]:
    """Restore and sync open order/position marks instantly after WS reconnect."""
    try:
        from bot_service import bot_service

        marks = dict(mark_prices or {})
        with bot_service._lock:  # noqa: SLF001
            marks.update(bot_service._mark_prices)  # noqa: SLF001
            result = bot_service.execution.sync_open_order_state(marks)
        logger.info(
            "WS reconnect synced %s open position(s); wallet=$%.2f",
            result.get("synced_positions"),
            float(result.get("wallet_balance") or 0.0),
        )
        return result
    except Exception as exc:  # noqa: BLE001
        logger.warning("Open-order sync after reconnect failed: %s", exc)
        return {"ok": False, "detail": str(exc)}


def symbol_to_stream(symbol: str) -> str:
    """BTC/USDT → btcusdt"""
    return symbol.replace("/", "").replace("-", "").lower()


def stream_to_symbol(stream_sym: str) -> str:
    """btcusdt → BTC/USDT"""
    s = stream_sym.upper()
    if s.endswith("USDT") and "/" not in s:
        return f"{s[:-4]}/USDT"
    return s


class ConnectionManager:
    """Track and broadcast to dashboard WebSocket clients."""

    def __init__(self) -> None:
        self._channels: dict[Channel, set[WebSocket]] = {
            "market": set(),
            "bot-status": set(),
        }
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, channel: Channel) -> None:
        await websocket.accept()
        async with self._lock:
            self._channels[channel].add(websocket)
        logger.info("WS connect channel=%s clients=%s", channel, len(self._channels[channel]))

    async def disconnect(self, websocket: WebSocket, channel: Channel) -> None:
        async with self._lock:
            self._channels[channel].discard(websocket)
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close()
        except Exception:  # noqa: BLE001
            pass

    def client_count(self, channel: Channel | None = None) -> int:
        if channel:
            return len(self._channels[channel])
        return sum(len(v) for v in self._channels.values())

    async def send_json(self, websocket: WebSocket, payload: dict[str, Any]) -> bool:
        if websocket.client_state != WebSocketState.CONNECTED:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except Exception:  # noqa: BLE001
            return False

    async def broadcast(self, channel: Channel, payload: dict[str, Any]) -> int:
        async with self._lock:
            clients = list(self._channels[channel])
        dead: list[WebSocket] = []
        sent = 0
        for ws in clients:
            ok = await self.send_json(ws, payload)
            if ok:
                sent += 1
            else:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._channels[channel].discard(ws)
        return sent


class BinanceFuturesListener:
    """
    Async listener for Binance Futures combined streams:
    bookTicker + markPrice + kline for configured symbols.
    """

    def __init__(self, on_message) -> None:
        self.on_message = on_message
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.connected = False
        self.active_base: str | None = None
        self.last_error: str | None = None
        self.symbols: list[str] = list(config.DEFAULT_TRADING_PAIRS)
        self.last_message_at: float | None = None
        self.reconnect_attempts = 0
        self.last_backoff_s = 0.0

    def set_symbols(self, symbols: list[str]) -> None:
        cleaned = [s for s in symbols if s]
        if cleaned:
            self.symbols = cleaned

    def _build_url(self, base: str) -> str:
        streams: list[str] = []
        for sym in self.symbols:
            s = symbol_to_stream(sym)
            streams.append(f"{s}@bookTicker")
            streams.append(f"{s}@markPrice@1s")
            streams.append(f"{s}@kline_1m")
        joined = "/".join(streams)
        base = base.rstrip("/")
        # Combined stream path works on both stream.binancefutures.com and fstream.binance.com
        return f"{base}/stream?streams={joined}"

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="binance-futures-ws")

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
        self.connected = False

    async def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            self.reconnect_attempts += 1
            self.last_backoff_s = backoff
            connected_once = False
            bases = list(_binance_ws_bases())
            websocket_aggregator.configure(bases)
            for base in bases:
                if self._stop.is_set():
                    break
                url = self._build_url(base)
                try:
                    logger.info("Connecting Binance Futures WS: %s", base)
                    async with websockets.connect(
                        url,
                        ping_interval=20,
                        ping_timeout=20,
                        max_queue=1024,
                        close_timeout=5,
                    ) as ws:
                        self.connected = True
                        self.active_base = base
                        self.last_error = None
                        connected_once = True
                        self.reconnect_attempts = 0
                        backoff = 1.0
                        self.last_backoff_s = backoff
                        stale_ticks = 0
                        await self.on_message(
                            {
                                "type": "binance_connected",
                                "base": base,
                                "symbols": self.symbols,
                                "ts": _utc_iso(),
                            }
                        )
                        while not self._stop.is_set():
                            try:
                                frame_started = asyncio.get_running_loop().time()
                                raw = await asyncio.wait_for(ws.recv(), timeout=30)
                            except asyncio.TimeoutError:
                                stale_ticks += 1
                                logger.warning("Binance WS stalled on %s (%s/3)", base, stale_ticks)
                                if stale_ticks >= 3:
                                    raise TimeoutError(f"Binance WS stalled on {base}")
                                continue
                            try:
                                msg = loads(raw)
                            except Exception:
                                continue
                            stale_ticks = 0
                            self.last_message_at = asyncio.get_running_loop().time()
                            await self._handle(msg)
                            frame_latency_ms = (asyncio.get_running_loop().time() - frame_started) * 1000.0
                            if websocket_aggregator.report_frame(frame_latency_ms, base):
                                await self.on_message(
                                    {
                                        "type": "binance_failover",
                                        "from": base,
                                        "to": websocket_aggregator.active,
                                        "frame_latency_ms": round(frame_latency_ms, 3),
                                        "ts": _utc_iso(),
                                    }
                                )
                                raise TimeoutError(f"High frame latency {frame_latency_ms:.2f}ms on {base}")
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    self.connected = False
                    self.last_error = str(exc)
                    if _is_dns_failure(exc):
                        # stream.binancefutures.com often NXDOMAIN on Render — soft-log + try fstream.
                        logger.info(
                            "Binance WS DNS unresolved for %s — trying fallback (backoff %.1fs)",
                            base,
                            backoff,
                        )
                    else:
                        logger.warning("Binance WS error (%s): %s", base, exc)
                    await self.on_message(
                        {
                            "type": "binance_disconnected",
                            "base": base,
                            "error": str(exc),
                            "ts": _utc_iso(),
                        }
                    )
                    if websocket_aggregator.active and websocket_aggregator.active != base:
                        continue
                    if connected_once:
                        break  # reconnect same base first after drop
            self.connected = False
            if self._stop.is_set():
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2.0, 60.0)

    async def _handle(self, msg: dict[str, Any]) -> None:
        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        if not isinstance(data, dict):
            return
        event = data.get("e")
        stream = str(msg.get("stream") or "")

        if event == "bookTicker" or "bookTicker" in stream:
            symbol = stream_to_symbol(str(data.get("s") or stream.split("@")[0]))
            payload = {
                "type": "book_ticker",
                "symbol": symbol,
                "bid": float(data.get("b") or 0),
                "bid_qty": float(data.get("B") or 0),
                "ask": float(data.get("a") or 0),
                "ask_qty": float(data.get("A") or 0),
                "mid": (
                    (float(data.get("b") or 0) + float(data.get("a") or 0)) / 2.0
                    if data.get("b") and data.get("a")
                    else None
                ),
                "ts": _utc_iso(),
            }
            await self.on_message(payload)
            return

        if event == "markPriceUpdate" or "markPrice" in stream:
            symbol = stream_to_symbol(str(data.get("s") or stream.split("@")[0]))
            payload = {
                "type": "mark_price",
                "symbol": symbol,
                "mark_price": float(data.get("p") or 0),
                "index_price": float(data.get("i") or 0),
                "funding_rate": float(data.get("r") or 0),
                "ts": _utc_iso(),
            }
            await self.on_message(payload)
            return

        if event == "kline" or "@kline_" in stream:
            k = data.get("k") or {}
            symbol = stream_to_symbol(str(k.get("s") or data.get("s") or stream.split("@")[0]))
            payload = {
                "type": "kline",
                "symbol": symbol,
                "interval": k.get("i"),
                "closed": bool(k.get("x")),
                "candle": {
                    "time": int(k.get("t") or 0) // 1000,
                    "open": float(k.get("o") or 0),
                    "high": float(k.get("h") or 0),
                    "low": float(k.get("l") or 0),
                    "close": float(k.get("c") or 0),
                    "volume": float(k.get("v") or 0),
                },
                "ts": _utc_iso(),
            }
            await self.on_message(payload)


class WebSocketHub:
    """Orchestrates client fan-out, Binance stream, and bot snapshot broadcasts."""

    def __init__(self) -> None:
        self.manager = ConnectionManager()
        self.listener = BinanceFuturesListener(self._on_binance_message)
        self._broadcast_task: asyncio.Task[None] | None = None
        self._started = False
        self.ticks: dict[str, dict[str, Any]] = {}
        self.books: dict[str, dict[str, Any]] = {}
        self.latest_kline: dict[str, dict[str, Any]] = {}
        self._tick_throttle: dict[str, float] = {}
        self._activity: list[dict[str, Any]] = []
        self.snapshot_interval = float(getattr(config, "WS_SNAPSHOT_INTERVAL", 1.0))

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        from bot_service import bot_service

        self.listener.set_symbols(list(bot_service.pairs))
        await self.listener.start()
        self._broadcast_task = asyncio.create_task(self._snapshot_loop(), name="ws-snapshot-loop")
        logger.info("WebSocket hub started")

    async def stop(self) -> None:
        self._started = False
        if self._broadcast_task and not self._broadcast_task.done():
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass
        await self.listener.stop()

    def push_activity(self, message: str, level: str = "info") -> None:
        entry = {"ts": _utc_iso(), "level": level, "message": message}
        self._activity.append(entry)
        self._activity = self._activity[-80:]

    async def notify_bot_lifecycle(self, running: bool, message: str) -> None:
        self.push_activity(message, "lifecycle")
        payload = {
            "type": "bot_lifecycle",
            "bot_running": running,
            "status": "LIVE" if running else "IDLE",
            "message": message,
            "ts": _utc_iso(),
        }
        await self.manager.broadcast("bot-status", payload)
        await self.manager.broadcast("market", payload)

    async def _on_binance_message(self, payload: dict[str, Any]) -> None:
        msg_type = payload.get("type")
        if msg_type in {"binance_connected", "binance_disconnected", "binance_failover"}:
            self.push_activity(
                f"Binance WS {msg_type}: {payload.get('base') or payload.get('from')}",
                "stream",
            )
            if msg_type == "binance_connected":
                marks = {
                    sym: float(tick.get("price") or 0.0)
                    for sym, tick in self.ticks.items()
                    if float(tick.get("price") or 0.0) > 0
                }
                sync_result = await sync_open_orders_after_reconnect(marks)
                payload = {**payload, "order_sync": sync_result}
                self.push_activity(
                    f"Open-order sync restored {sync_result.get('synced_positions', 0)} position(s)",
                    "stream",
                )
            await self.manager.broadcast("market", payload)
            return

        symbol = str(payload.get("symbol") or "")
        if msg_type == "book_ticker" and symbol:
            self.books[symbol] = payload
            mid = payload.get("mid")
            if mid:
                self.ticks[symbol] = {
                    "symbol": symbol,
                    "price": float(mid),
                    "source": "bookTicker",
                    "ts": payload.get("ts"),
                }
                ring_buffer.record_tick(self.ticks[symbol])
                self._apply_mark(symbol, float(mid))
                try:
                    from hft_scalper import hft_scalper

                    events = hft_scalper.ingest_tick(
                        symbol,
                        float(mid),
                        bid=float(payload.get("bid") or 0) or None,
                        ask=float(payload.get("ask") or 0) or None,
                    )
                    for ev in events:
                        self.push_activity(
                            f"HFT {ev.get('type')}: {ev.get('symbol')} {ev.get('side')}",
                            "hft",
                        )
                        await self.manager.broadcast("market", ev)
                        await self.manager.broadcast("bot-status", ev)
                except Exception:  # noqa: BLE001
                    pass
            # Throttle book broadcasts (~8/sec/symbol max)
            await self._throttled_broadcast(symbol, "book_ticker", payload, min_interval=0.12)
            return

        if msg_type == "mark_price" and symbol:
            price = float(payload.get("mark_price") or 0)
            if price > 0:
                self.ticks[symbol] = {
                    "symbol": symbol,
                    "price": price,
                    "source": "markPrice",
                    "funding_rate": payload.get("funding_rate"),
                    "ts": payload.get("ts"),
                }
                ring_buffer.record_tick(self.ticks[symbol])
                self._apply_mark(symbol, price)
                try:
                    from hft_scalper import hft_scalper
                    from quantum_engine import quantum_engine

                    quantum_engine._price_hist[symbol].append(price)
                    quantum_engine.update_liquidation_heatmap(symbol, price)
                    events = hft_scalper.ingest_tick(symbol, price)
                    for ev in events:
                        await self.manager.broadcast("market", ev)
                except Exception:  # noqa: BLE001
                    pass
            await self._throttled_broadcast(symbol, "mark_price", payload, min_interval=0.25)
            return

        if msg_type == "kline" and symbol:
            self.latest_kline[symbol] = payload
            candle = payload.get("candle") or {}
            close = float(candle.get("close") or 0)
            if close > 0:
                self.ticks[symbol] = {
                    "symbol": symbol,
                    "price": close,
                    "source": "kline",
                    "ts": payload.get("ts"),
                }
                ring_buffer.record_tick(self.ticks[symbol])
            await self.manager.broadcast("market", payload)

    def _apply_mark(self, symbol: str, price: float) -> None:
        try:
            from bot_service import bot_service

            with bot_service._lock:  # noqa: SLF001
                bot_service._mark_prices[symbol] = price  # noqa: SLF001
        except Exception:  # noqa: BLE001
            pass

    async def _throttled_broadcast(
        self,
        symbol: str,
        kind: str,
        payload: dict[str, Any],
        min_interval: float,
    ) -> None:
        key = f"{kind}:{symbol}"
        now = asyncio.get_event_loop().time()
        last = self._tick_throttle.get(key, 0.0)
        if now - last < min_interval:
            return
        self._tick_throttle[key] = now
        await self.manager.broadcast("market", payload)

    async def _snapshot_loop(self) -> None:
        while self._started:
            try:
                await self.publish_snapshot()
            except Exception as exc:  # noqa: BLE001
                logger.warning("snapshot broadcast failed: %s", exc)
            await asyncio.sleep(self.snapshot_interval)

    def build_snapshot(self) -> dict[str, Any]:
        from bot_service import bot_service

        status = bot_service.get_status()
        portfolio = bot_service.get_portfolio()
        history = bot_service.get_trade_history(limit=25)

        # Overlay live ticks onto markets
        markets = []
        for m in status.get("markets") or []:
            row = dict(m)
            sym = str(row.get("symbol") or "")
            tick = self.ticks.get(sym)
            if tick and tick.get("price"):
                row["price"] = tick["price"]
                row["live_source"] = tick.get("source")
            book = self.books.get(sym)
            if book:
                row["bid"] = book.get("bid")
                row["ask"] = book.get("ask")
            markets.append(row)

        return {
            "type": "snapshot",
            "ts": _utc_iso(),
            "bot_running": status.get("bot_running"),
            "status": status.get("status"),
            "cycle": status.get("cycle"),
            "last_cycle_at": status.get("last_cycle_at"),
            "server_time": status.get("server_time"),
            "markets": markets,
            "portfolio": portfolio,
            "positions": portfolio.get("positions") or [],
            "history": history,
            "events": status.get("events") or [],
            "activity": list(self._activity[-20:]),
            "ticks": self.ticks,
            "aggregator": websocket_aggregator.snapshot(),
            "stream": {
                "binance_connected": self.listener.connected,
                "binance_base": self.listener.active_base,
                "error": self.listener.last_error,
                "symbols": self.listener.symbols,
                "clients_market": self.manager.client_count("market"),
                "clients_bot": self.manager.client_count("bot-status"),
                "reconnect_attempts": self.listener.reconnect_attempts,
                "reconnect_backoff_ms": round(self.listener.last_backoff_s * 1000, 1),
                "last_message_age_ms": (
                    round((asyncio.get_running_loop().time() - self.listener.last_message_at) * 1000, 1)
                    if self.listener.last_message_at
                    else None
                ),
            },
            "sentiment_score": status.get("sentiment_score"),
            "sentiment_label": status.get("sentiment_label"),
        }

    async def publish_snapshot(self) -> None:
        if self.manager.client_count("market") == 0 and self.manager.client_count("bot-status") == 0:
            return
        snap = self.build_snapshot()
        await self.manager.broadcast("market", snap)
        await self.manager.broadcast(
            "bot-status",
            {
                "type": "bot_status",
                "ts": snap["ts"],
                "bot_running": snap["bot_running"],
                "status": snap["status"],
                "cycle": snap["cycle"],
                "last_cycle_at": snap["last_cycle_at"],
                "events": snap["events"],
                "activity": snap["activity"],
                "stream": snap["stream"],
                "portfolio_summary": {
                    "equity": (snap.get("portfolio") or {}).get("equity"),
                    "open_positions": (snap.get("portfolio") or {}).get("open_positions"),
                    "daily_realized_pnl": (snap.get("portfolio") or {}).get("daily_realized_pnl"),
                },
            },
        )

    async def handle_market_socket(self, websocket: WebSocket) -> None:
        await self.manager.connect(websocket, "market")
        # Immediate snapshot
        await self.manager.send_json(websocket, self.build_snapshot())
        try:
            while True:
                raw = await websocket.receive_text()
                await self._handle_client_command(websocket, raw, "market")
        except WebSocketDisconnect:
            pass
        finally:
            await self.manager.disconnect(websocket, "market")

    async def handle_bot_status_socket(self, websocket: WebSocket) -> None:
        await self.manager.connect(websocket, "bot-status")
        await self.manager.send_json(
            websocket,
            {
                "type": "bot_status",
                "ts": _utc_iso(),
                "bot_running": False,
                "message": "subscribed",
            },
        )
        await self.publish_snapshot()
        try:
            while True:
                raw = await websocket.receive_text()
                await self._handle_client_command(websocket, raw, "bot-status")
        except WebSocketDisconnect:
            pass
        finally:
            await self.manager.disconnect(websocket, "bot-status")

    async def _handle_client_command(self, websocket: WebSocket, raw: str, channel: Channel) -> None:
        try:
            msg = loads(raw)
        except json.JSONDecodeError:
            return
        action = msg.get("action")
        if action == "ping":
            await self.manager.send_json(
                websocket,
                {"type": "pong", "ts": _utc_iso(), "client_ts": msg.get("client_ts")},
            )
            return
        if action == "subscribe_symbols" and channel == "market":
            symbols = msg.get("symbols") or []
            if isinstance(symbols, list) and symbols:
                next_symbols = [str(s) for s in symbols if str(s).strip()]
                if next_symbols and set(next_symbols) != set(self.listener.symbols):
                    self.listener.set_symbols(next_symbols)
                    await self.listener.stop()
                    await self.listener.start()
                await self.manager.send_json(
                    websocket,
                    {"type": "subscribed", "symbols": self.listener.symbols, "ts": _utc_iso()},
                )
            return
        if action == "request_snapshot":
            await self.manager.send_json(websocket, self.build_snapshot())


ws_hub = WebSocketHub()
binance_http_guard = BinanceHttpWeightGuard()
