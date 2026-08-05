"""
Beast AI Trading Bot — Shared runtime for CLI and FastAPI backgrounds.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone
from typing import Any

import config
from execution_engine import ExecutionEngine
from main import evaluate_universe, maybe_execute
from market_data import MarketDataEngine
from risk_manager import DEFAULT_ACCOUNT_BALANCE, RiskManager
from copy_trader import copy_trader
from seo_generator import seo_generator
from sentiment_engine import sentiment_engine
from strategy import SignalGenerator
from telegram_bot import telegram_notifier
from trade_logger import TradeLogger


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class TradingBotService:
    """Thread-safe paper-trading loop with cached API snapshots."""

    def __init__(self, starting_balance: float = DEFAULT_ACCOUNT_BALANCE) -> None:
        self.trade_logger = TradeLogger()
        self.execution = ExecutionEngine(
            mode=config.EXECUTION_MODE,
            starting_balance=starting_balance,
            trade_logger=self.trade_logger,
        )
        self.market = MarketDataEngine()
        self.signal_gen = SignalGenerator()
        self.pairs = list(config.DEFAULT_TRADING_PAIRS)
        self.timeframe = config.DEFAULT_TIMEFRAME
        self.interval = config.LOOP_INTERVAL_SECONDS
        self.min_confidence = config.MIN_SIGNAL_CONFIDENCE

        self._lock = threading.RLock()
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._cycle = 0
        self._last_cycle_at: str | None = None
        self._latest_scan: list[dict[str, Any]] = []
        self._latest_events: list[str] = []
        self._mark_prices: dict[str, float] = {}
        self._last_error: str | None = None
        self._latest_sentiment: dict[str, Any] | None = None
        self._last_daily_pnl_date: str | None = None
        self._last_signal_fingerprint: dict[str, str] = {}

    def set_active_pairs(self, pairs: list[str]) -> list[str]:
        """Update the bot's active scan/trading universe."""
        cleaned = [str(p).strip() for p in pairs if str(p).strip()]
        if not cleaned:
            cleaned = list(config.DEFAULT_TRADING_PAIRS)
        with self._lock:
            self.pairs = cleaned
        return list(self.pairs)

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> dict[str, Any]:
        if self._running and self._task and not self._task.done():
            return {"running": True, "message": "Bot already running"}

        self._running = True
        self._last_error = None
        self._task = asyncio.create_task(self._loop(), name="beast-trading-loop")
        try:
            from websocket_manager import ws_hub

            await ws_hub.notify_bot_lifecycle(True, "Bot started")
        except Exception:  # noqa: BLE001
            pass
        return {"running": True, "message": "Bot started"}

    async def stop(self) -> dict[str, Any]:
        self._running = False
        task = self._task
        self._task = None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.execution.save()
        try:
            from websocket_manager import ws_hub

            await ws_hub.notify_bot_lifecycle(False, "Bot stopped")
        except Exception:  # noqa: BLE001
            pass
        return {"running": False, "message": "Bot stopped"}

    async def toggle(self) -> dict[str, Any]:
        if self._running:
            return await self.stop()
        return await self.start()

    async def _loop(self) -> None:
        try:
            while self._running:
                await asyncio.to_thread(self._run_cycle)
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._last_error = str(exc)
            self._running = False
        finally:
            self.execution.save()

    def _run_cycle(self) -> None:
        with self._lock:
            self._cycle += 1
            events: list[str] = []
            try:
                sentiment = sentiment_engine.get_sentiment()
                self._latest_sentiment = sentiment
                sentiment_score = float(sentiment.get("score") or 50.0)

                # Ensure today's SEO article exists (idempotent)
                if self._cycle == 1 or self._cycle % 30 == 0:
                    try:
                        article = seo_generator.generate_daily_article()
                        events.append(f"SEO ready: {article.get('title')}")
                    except Exception as seo_exc:  # noqa: BLE001
                        events.append(f"SEO warning: {seo_exc}")

                risk_mgr = RiskManager(account_balance=max(self.execution.equity(self._mark_prices), 1.0))
                scan_rows = evaluate_universe(
                    market=self.market,
                    signal_gen=self.signal_gen,
                    risk_mgr=risk_mgr,
                    pairs=self.pairs,
                    timeframe=self.timeframe,
                    sentiment_score=sentiment_score,
                )
                mark_prices = {str(r["symbol"]): float(r["entry_price"]) for r in scan_rows}
                signal_map = {str(r["symbol"]): str(r["signal"]) for r in scan_rows}

                # Signal alerts (deduped per symbol/signal flip)
                for row in scan_rows:
                    sig = str(row.get("signal") or "HOLD")
                    symbol = str(row.get("symbol") or "")
                    if sig not in {"BUY", "SELL"}:
                        continue
                    fingerprint = f"{sig}:{round(float(row.get('confidence_score') or 0.0), 1)}"
                    if self._last_signal_fingerprint.get(symbol) == fingerprint:
                        continue
                    self._last_signal_fingerprint[symbol] = fingerprint
                    try:
                        telegram_notifier.notify_signal(
                            symbol=symbol,
                            signal=sig,
                            confidence=float(row.get("confidence_score") or 0.0),
                            price=float(row.get("entry_price") or 0.0),
                        )
                        events.append(f"TG signal alert: {symbol} {sig}")
                    except Exception as tg_exc:  # noqa: BLE001
                        events.append(f"TG signal error: {tg_exc}")

                closed = self.execution.monitor_positions(mark_prices, signals=signal_map)
                for trade in closed:
                    events.append(
                        f"CLOSE {trade['direction']} {trade['pair']} | "
                        f"PnL ${float(trade['pnl_usd']):.2f} | {trade['exit_reason']}"
                    )
                    try:
                        telegram_notifier.notify_order_event(
                            event=str(trade.get("exit_reason") or "Exit"),
                            symbol=str(trade["pair"]),
                            direction=str(trade["direction"]),
                            price=float(trade["exit_price"]),
                            extra=f"PnL ${float(trade['pnl_usd']):.2f}",
                        )
                    except Exception as tg_exc:  # noqa: BLE001
                        events.append(f"TG close alert error: {tg_exc}")
                    try:
                        copies = copy_trader.on_master_close(
                            symbol=str(trade["pair"]),
                            exit_price=float(trade["exit_price"]),
                            master_trade_id=str(trade.get("trade_id") or ""),
                            pnl_usd=float(trade.get("pnl_usd") or 0.0),
                        )
                        if copies:
                            events.append(f"COPY close replicated to {len(copies)} follower(s)")
                    except Exception as copy_exc:  # noqa: BLE001
                        events.append(f"COPY close error: {copy_exc}")

                master_equity = max(self.execution.equity(mark_prices), 1.0)
                for row in scan_rows:
                    result = maybe_execute(
                        self.execution, row, min_confidence=self.min_confidence
                    )
                    if not result:
                        continue
                    events.append(str(result["message"]))
                    order = result.get("order")
                    if not order:
                        continue
                    try:
                        telegram_notifier.notify_order_event(
                            event="Entry",
                            symbol=str(order["symbol"]),
                            direction=str(order["direction"]),
                            price=float(order["entry_price"]),
                            extra=(
                                f"SL {float(order.get('stop_loss') or 0):.2f} | "
                                f"TP {float(order.get('take_profit') or 0):.2f}"
                            ),
                        )
                    except Exception as tg_exc:  # noqa: BLE001
                        events.append(f"TG entry alert error: {tg_exc}")
                    try:
                        copies = copy_trader.on_master_open(
                            symbol=str(order["symbol"]),
                            signal=str(result.get("signal") or "BUY"),
                            master_size_units=float(order["size"]),
                            master_equity=master_equity,
                            market_price=float(order["entry_price"]),
                            leverage=float(order.get("leverage") or 1.0),
                            stop_loss=float(order.get("stop_loss") or 0.0),
                            take_profit=float(order.get("take_profit") or 0.0),
                            master_trade_id=str(order.get("trade_id") or ""),
                        )
                        filled = [c for c in copies if c.get("status") == "filled"]
                        if filled:
                            events.append(
                                f"COPY open -> {len(filled)} follower(s) "
                                f"(master equity ${master_equity:,.2f})"
                            )
                    except Exception as copy_exc:  # noqa: BLE001
                        events.append(f"COPY open error: {copy_exc}")

                # Once-per-UTC-day portfolio summary
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if self._last_daily_pnl_date != today:
                    snap = self.execution.portfolio_snapshot(mark_prices)
                    hist = self.trade_logger.load_history()
                    daily = sum(
                        float(t.get("pnl_usd") or 0.0)
                        for t in hist
                        if str(t.get("timestamp") or "").startswith(today)
                    )
                    try:
                        telegram_notifier.notify_daily_pnl(
                            equity=float(snap["equity"]),
                            daily_pnl=float(daily),
                            realized_pnl=float(snap["realized_pnl"]),
                            open_positions=int(snap["open_positions"]),
                        )
                        self._last_daily_pnl_date = today
                        events.append("TG daily PnL summary sent")
                    except Exception as tg_exc:  # noqa: BLE001
                        events.append(f"TG daily summary error: {tg_exc}")

                blocked = sum(1 for r in scan_rows if r.get("sentiment_blocked"))
                if blocked:
                    events.append(f"Sentiment gate held {blocked} signal(s) @ {sentiment_score:.1f}")

                self._latest_scan = scan_rows
                self._mark_prices.update(mark_prices)
                # Prefer live Binance WS ticks over REST scan closes when present
                try:
                    from websocket_manager import ws_hub

                    for sym, tick in ws_hub.ticks.items():
                        px = float(tick.get("price") or 0)
                        if px > 0:
                            self._mark_prices[sym] = px
                    for ev in events[-5:]:
                        ws_hub.push_activity(ev, "cycle")
                except Exception:  # noqa: BLE001
                    pass
                self._latest_events = events
                self._last_cycle_at = _utc_now()
                self._last_error = None
            except Exception as exc:  # noqa: BLE001
                self._last_error = str(exc)
                self._latest_events = [f"ERROR: {exc}"]

    def refresh_scan_once(self) -> list[dict[str, Any]]:
        """One-shot market scan used when the bot is idle."""
        with self._lock:
            sentiment = sentiment_engine.get_sentiment()
            self._latest_sentiment = sentiment
            sentiment_score = float(sentiment.get("score") or 50.0)
            risk_mgr = RiskManager(account_balance=max(self.execution.equity(self._mark_prices), 1.0))
            scan_rows = evaluate_universe(
                market=self.market,
                signal_gen=self.signal_gen,
                risk_mgr=risk_mgr,
                pairs=self.pairs,
                timeframe=self.timeframe,
                sentiment_score=sentiment_score,
            )
            self._latest_scan = scan_rows
            self._mark_prices = {str(r["symbol"]): float(r["entry_price"]) for r in scan_rows}
            self._last_cycle_at = _utc_now()
            return scan_rows

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            scan = list(self._latest_scan)
            if not scan:
                # Avoid blocking API forever on first hit; caller may trigger refresh
                pass

            markets = []
            for row in scan:
                markets.append(
                    {
                        "symbol": row.get("symbol"),
                        "price": float(row.get("entry_price") or 0.0),
                        "signal": row.get("signal"),
                        "confidence": float(row.get("confidence_score") or 0.0),
                        "rsi": float(row.get("rsi") or 0.0),
                        "atr": float(row.get("atr") or 0.0),
                        "macd_hist": float(row.get("macd_hist") or 0.0),
                        "stop_loss": float(row.get("stop_loss_price") or 0.0),
                        "take_profit": float(row.get("take_profit_price") or 0.0),
                        "leverage": float(row.get("leverage") or 1.0),
                        "position_size_notional": float(row.get("position_size_notional") or 0.0),
                        "sentiment_score": row.get("sentiment_score"),
                        "sentiment_blocked": bool(row.get("sentiment_blocked")),
                    }
                )

            sentiment = self._latest_sentiment or {}
            return {
                "bot_running": self._running,
                "status": "LIVE" if self._running else "IDLE",
                "mode": self.execution.mode.value,
                "cycle": self._cycle,
                "last_cycle_at": self._last_cycle_at,
                "interval_seconds": self.interval,
                "timeframe": self.timeframe,
                "pairs": self.pairs,
                "markets": markets,
                "sentiment_score": sentiment.get("score"),
                "sentiment_label": sentiment.get("label"),
                "events": list(self._latest_events),
                "error": self._last_error,
                "server_time": _utc_now(),
            }

    def get_portfolio(self) -> dict[str, Any]:
        with self._lock:
            # Keep marks fresh for open positions even if scan is stale
            snap = self.execution.portfolio_snapshot(self._mark_prices)
            history = self.trade_logger.load_history()
            wins = [t for t in history if float(t.get("pnl_usd") or 0.0) > 0]
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            daily = [
                t
                for t in history
                if str(t.get("timestamp") or "").startswith(today)
            ]
            daily_pnl = round(sum(float(t.get("pnl_usd") or 0.0) for t in daily), 4)
            win_rate = round((len(wins) / len(history)) * 100.0, 2) if history else 0.0

            return {
                **snap,
                "bot_running": self._running,
                "status": "LIVE" if self._running else "IDLE",
                "daily_realized_pnl": daily_pnl,
                "win_rate": win_rate,
                "closed_trades": len(history),
                "server_time": _utc_now(),
            }

    def get_trade_history(self, limit: int = 100) -> dict[str, Any]:
        history = self.trade_logger.load_history()
        # Newest first
        history_sorted = list(reversed(history))
        if limit > 0:
            history_sorted = history_sorted[:limit]
        return {
            "count": len(history),
            "trades": history_sorted,
        }

    def shutdown(self) -> None:
        self._running = False
        self.execution.save()
        self.market.close()


# Process-wide singleton used by FastAPI
bot_service = TradingBotService()
