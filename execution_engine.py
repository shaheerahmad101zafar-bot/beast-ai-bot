"""
Beast AI Trading Bot — Phase 3 Automated Execution Engine

Supports PAPER_TRADING (default) and LIVE_BINANCE modes.
Paper mode simulates fills with slippage/fees, tracks positions, and
auto-closes on SL / TP / opposing signal. State persists to JSON.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

import config
from execution_slicer import execution_slicer
from execution_ws import execution_ws
from multi_exchange_router import multi_exchange_router
from notifications import notifications
from slippage_guard import slippage_guard
from trade_logger import TradeLogger


class ExecutionMode(str, Enum):
    PAPER_TRADING = "PAPER_TRADING"
    LIVE_BINANCE = "LIVE_BINANCE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class ExecutionEngine:
    """Order router for paper simulation or live Binance Futures."""

    def __init__(
        self,
        mode: str | ExecutionMode = config.EXECUTION_MODE,
        starting_balance: float = 1_000.0,
        portfolio_path: str | Path = config.PAPER_PORTFOLIO_PATH,
        fee_rate: float = config.FUTURES_FEE_RATE,
        slippage_bps: float = config.DEFAULT_SLIPPAGE_BPS,
        trade_logger: TradeLogger | None = None,
    ) -> None:
        load_dotenv()
        self.mode = ExecutionMode(mode)
        self.portfolio_path = Path(portfolio_path)
        self.fee_rate = float(fee_rate)
        self.slippage_bps = float(slippage_bps)
        self.trade_logger = trade_logger or TradeLogger()
        self._live_exchange = None
        self._execution_ws = execution_ws

        self.wallet_balance = float(starting_balance)
        self.realized_pnl = 0.0
        self.positions: dict[str, dict[str, Any]] = {}

        if self.mode == ExecutionMode.PAPER_TRADING:
            self._load_portfolio(starting_balance=starting_balance)
        else:
            self._init_live_exchange()

    @staticmethod
    def _run_coro(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def place_order(
        self,
        symbol: str,
        signal: str,
        size_units: float,
        leverage: float,
        market_price: float,
        stop_loss: float,
        take_profit: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Place a market order from a strategy signal.

        signal: 'BUY' -> LONG, 'SELL' -> SHORT
        """
        if signal not in {"BUY", "SELL"}:
            raise ValueError(f"Unsupported signal for execution: {signal}")
        if size_units <= 0 or market_price <= 0:
            raise ValueError("size_units and market_price must be positive")
        metadata = execution_slicer.enrich_metadata(
            metadata,
            size_units=size_units,
            market_price=market_price,
        )

        direction = "LONG" if signal == "BUY" else "SHORT"

        if self.mode == ExecutionMode.PAPER_TRADING:
            return self._paper_open(
                symbol=symbol,
                direction=direction,
                size_units=size_units,
                leverage=leverage,
                market_price=market_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                metadata=metadata,
            )
        return self._live_open(
            symbol=symbol,
            direction=direction,
            size_units=size_units,
            leverage=leverage,
            market_price=market_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            metadata=metadata,
        )

    def monitor_positions(
        self,
        mark_prices: dict[str, float],
        signals: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Update unrealized PnL and auto-close on SL / TP / opposing signal.

        Returns list of closed-trade records from this pass.
        """
        signals = signals or {}
        closed: list[dict[str, Any]] = []

        for symbol in list(self.positions.keys()):
            mark = mark_prices.get(symbol)
            if mark is None:
                continue

            pos = self.positions[symbol]
            pos["mark_price"] = float(mark)
            pos["unrealized_pnl"] = self._unrealized_pnl(pos, float(mark))

            exit_reason = self._exit_reason(pos, float(mark), signals.get(symbol))
            if exit_reason:
                closed.append(self.close_position(symbol, float(mark), exit_reason))

        if self.mode == ExecutionMode.PAPER_TRADING:
            self._save_portfolio()
        return closed

    def close_position(
        self,
        symbol: str,
        market_price: float,
        exit_reason: str,
    ) -> dict[str, Any]:
        """Force-close an open position at market (with slippage/fees in paper)."""
        if symbol not in self.positions:
            raise KeyError(f"No open position for {symbol}")

        if self.mode == ExecutionMode.PAPER_TRADING:
            return self._paper_close(symbol, market_price, exit_reason)
        return self._live_close(symbol, market_price, exit_reason)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        return self.positions.get(symbol)

    def equity(self, mark_prices: dict[str, float] | None = None) -> float:
        """Wallet + unrealized PnL (margin remains inside wallet accounting)."""
        mark_prices = mark_prices or {}
        unrealized = 0.0
        for symbol, pos in self.positions.items():
            mark = float(mark_prices.get(symbol, pos.get("mark_price") or pos["entry_price"]))
            unrealized += self._unrealized_pnl(pos, mark)
        return round(self.wallet_balance + unrealized, 4)

    def available_balance(self) -> float:
        locked = sum(float(p.get("margin") or 0.0) for p in self.positions.values())
        return round(max(0.0, self.wallet_balance - locked), 4)

    def save(self) -> None:
        """Persist paper portfolio state to disk."""
        if self.mode == ExecutionMode.PAPER_TRADING:
            self._save_portfolio()

    def portfolio_snapshot(self, mark_prices: dict[str, float] | None = None) -> dict[str, Any]:
        mark_prices = mark_prices or {}
        positions_view = []
        for symbol, pos in self.positions.items():
            mark = float(mark_prices.get(symbol, pos.get("mark_price") or pos["entry_price"]))
            view = dict(pos)
            view["mark_price"] = mark
            view["unrealized_pnl"] = round(self._unrealized_pnl(pos, mark), 4)
            positions_view.append(view)

        return {
            "mode": self.mode.value,
            "wallet_balance": round(self.wallet_balance, 4),
            "available_balance": self.available_balance(),
            "equity": self.equity(mark_prices),
            "realized_pnl": round(self.realized_pnl, 4),
            "open_positions": len(self.positions),
            "positions": positions_view,
        }

    # ------------------------------------------------------------------
    # Paper trading
    # ------------------------------------------------------------------
    def _vol_inputs(self, metadata: dict[str, Any] | None, position: dict[str, Any] | None = None) -> dict[str, float | None]:
        meta = metadata or {}
        atr_pct = meta.get("atr_pct_frac")
        if atr_pct is None and meta.get("atr_pct") is not None:
            # atr_pct from risk manager is percent points (1.5 => 1.5%)
            atr_pct = float(meta["atr_pct"]) / 100.0
        if atr_pct is None and position is not None:
            atr_pct = position.get("atr_pct_frac")
        realized = meta.get("realized_vol")
        if realized is None and position is not None:
            realized = position.get("realized_vol")
        return {
            "atr_pct": float(atr_pct) if atr_pct is not None else None,
            "realized_vol": float(realized) if realized is not None else None,
        }

    def _apply_slippage(
        self,
        price: float,
        direction: str,
        is_entry: bool,
        *,
        atr_pct: float | None = None,
        realized_vol: float | None = None,
    ) -> tuple[float, float]:
        """
        Apply dynamic 0.02%–0.08% volatility slippage.
        Returns (fill_price, slippage_pct).
        """
        fill = slippage_guard.apply_fill_price(
            price,
            direction=direction,
            is_entry=is_entry,
            atr_pct=atr_pct,
            realized_vol=realized_vol,
        )
        # Never slip better than configured floor from DEFAULT_SLIPPAGE_BPS
        floor = max(float(config.MIN_SLIPPAGE_PCT), self.slippage_bps / 10_000.0)
        slip = max(floor, float(fill["slippage_pct"]))
        slip = min(float(config.MAX_SLIPPAGE_PCT), slip)
        buying = (direction == "LONG" and is_entry) or (direction == "SHORT" and not is_entry)
        fill_price = price * (1.0 + slip) if buying else price * (1.0 - slip)
        return fill_price, slip

    def _paper_open(
        self,
        symbol: str,
        direction: str,
        size_units: float,
        leverage: float,
        market_price: float,
        stop_loss: float,
        take_profit: float,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if symbol in self.positions:
            raise RuntimeError(f"Position already open for {symbol}")

        vols = self._vol_inputs(metadata)
        fill_price, slip_pct = self._apply_slippage(
            market_price,
            direction,
            is_entry=True,
            atr_pct=vols["atr_pct"],  # type: ignore[arg-type]
            realized_vol=vols["realized_vol"],  # type: ignore[arg-type]
        )
        notional = size_units * fill_price
        leverage = max(1.0, float(leverage))
        margin = notional / leverage
        # Automated 0.04% exchange taker fee on every paper entry
        entry_fee = notional * self.fee_rate

        if margin + entry_fee > self.available_balance() + 1e-9:
            raise RuntimeError(
                f"Insufficient paper balance: need ${margin + entry_fee:.2f}, "
                f"available ${self.available_balance():.2f}"
            )

        self.wallet_balance -= entry_fee
        trade_id = str(uuid.uuid4())[:8]
        position = {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": round(fill_price, 8),
            "size": round(size_units, 8),
            "notional": round(notional, 4),
            "leverage": round(leverage, 2),
            "margin": round(margin, 4),
            "stop_loss": round(float(stop_loss), 8),
            "take_profit": round(float(take_profit), 8),
            "entry_fee": round(entry_fee, 6),
            "fee_rate": self.fee_rate,
            "slippage_pct": round(slip_pct, 6),
            "atr_pct_frac": vols["atr_pct"],
            "realized_vol": vols["realized_vol"],
            "mark_price": round(fill_price, 8),
            "unrealized_pnl": 0.0,
            "opened_at": _utc_now(),
            "ai_reasoning": str((metadata or {}).get("ai_reasoning") or ""),
            "slice_plan": dict((metadata or {}).get("slice_plan") or {}),
        }
        self.positions[symbol] = position
        self._save_portfolio()
        result = {"status": "filled", "mode": self.mode.value, **position}
        try:
            notifications.notify_order_execution({**result, "pair": symbol})
        except Exception:
            pass
        return result

    def _paper_close(
        self,
        symbol: str,
        market_price: float,
        exit_reason: str,
    ) -> dict[str, Any]:
        pos = self.positions[symbol]
        direction = pos["direction"]
        vols = self._vol_inputs(None, position=pos)
        fill_price, slip_pct = self._apply_slippage(
            market_price,
            direction,
            is_entry=False,
            atr_pct=vols["atr_pct"],  # type: ignore[arg-type]
            realized_vol=vols["realized_vol"],  # type: ignore[arg-type]
        )
        size = float(pos["size"])
        entry = float(pos["entry_price"])
        notional_exit = size * fill_price
        # Automated 0.04% exchange taker fee on every paper exit
        exit_fee = notional_exit * self.fee_rate

        gross_pnl = (
            (fill_price - entry) * size
            if direction == "LONG"
            else (entry - fill_price) * size
        )
        entry_fee = float(pos.get("entry_fee") or 0.0)
        total_fees = entry_fee + exit_fee
        # Entry fee was already deducted at open; credit gross PnL minus exit fee only.
        self.wallet_balance += gross_pnl - exit_fee

        trade = {
            "timestamp": _utc_now(),
            "trade_id": pos.get("trade_id"),
            "pair": symbol,
            "direction": direction,
            "entry_price": entry,
            "exit_price": round(fill_price, 8),
            "size": size,
            "leverage": float(pos.get("leverage") or 1.0),
            "pnl_usd": round(gross_pnl - total_fees, 4),
            "fees_usd": round(total_fees, 6),
            "entry_fee": round(entry_fee, 6),
            "exit_fee": round(exit_fee, 6),
            "slippage_pct": round(slip_pct, 6),
            "exit_reason": exit_reason,
            "gross_pnl": round(gross_pnl, 4),
            "ai_reasoning": str(pos.get("ai_reasoning") or ""),
        }

        del self.positions[symbol]
        self.realized_pnl = round(self.realized_pnl + trade["pnl_usd"], 4)
        self.trade_logger.log_trade(trade)
        self._save_portfolio()
        try:
            notifications.notify_order_close(trade)
        except Exception:
            pass
        return trade

    # ------------------------------------------------------------------
    # Live Binance (scaffolded — requires API keys; not used by default)
    # ------------------------------------------------------------------
    def _init_live_exchange(self) -> None:
        api_key = os.getenv("BINANCE_API_KEY", "").strip()
        api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
        if not api_key or not api_secret:
            raise RuntimeError(
                "LIVE_BINANCE mode requires BINANCE_API_KEY and BINANCE_API_SECRET in .env"
            )

        import ccxt

        exchange_class = getattr(ccxt, config.EXCHANGE_ID)
        self._live_exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
                "options": {"defaultType": "future"},
            }
        )

    def _live_open(self, **kwargs: Any) -> dict[str, Any]:
        symbol = str(kwargs["symbol"])
        direction = str(kwargs["direction"])
        size_units = float(kwargs["size_units"])
        market_price = float(kwargs["market_price"])
        leverage = float(kwargs["leverage"])
        response = self._run_coro(
            multi_exchange_router.place_order(
                symbol=symbol,
                side="BUY" if direction == "LONG" else "SELL",
                quantity=size_units,
                reduce_only=False,
            )
        )
        trade_id = str(uuid.uuid4())[:8]
        position = {
            "trade_id": trade_id,
            "symbol": symbol,
            "direction": direction,
            "entry_price": round(market_price, 8),
            "size": round(size_units, 8),
            "notional": round(size_units * market_price, 4),
            "leverage": round(leverage, 2),
            "margin": round((size_units * market_price) / max(leverage, 1.0), 4),
            "stop_loss": round(float(kwargs["stop_loss"]), 8),
            "take_profit": round(float(kwargs["take_profit"]), 8),
            "entry_fee": 0.0,
            "mark_price": round(market_price, 8),
            "unrealized_pnl": 0.0,
            "opened_at": _utc_now(),
            "ai_reasoning": str((kwargs.get("metadata") or {}).get("ai_reasoning") or ""),
            "slice_plan": dict((kwargs.get("metadata") or {}).get("slice_plan") or {}),
            "execution_pipe": response,
        }
        self.positions[symbol] = position
        return {"status": "filled", "mode": "LIVE_BINANCE_WS", **position}

    def _live_close(self, symbol: str, market_price: float, exit_reason: str) -> dict[str, Any]:
        pos = self.positions[symbol]
        response = self._run_coro(
            multi_exchange_router.place_order(
                symbol=symbol,
                side="SELL" if pos["direction"] == "LONG" else "BUY",
                quantity=float(pos["size"]),
                reduce_only=True,
            )
        )
        guard = None
        if "sl" in str(exit_reason).lower():
            guard = slippage_guard.build_iceberg(
                symbol=symbol,
                direction=str(pos["direction"]),
                size=float(pos["size"]),
                mark_price=market_price,
            )
        trade = {
            "timestamp": _utc_now(),
            "trade_id": pos.get("trade_id"),
            "pair": symbol,
            "direction": pos["direction"],
            "entry_price": float(pos["entry_price"]),
            "exit_price": round(market_price, 8),
            "size": float(pos["size"]),
            "leverage": float(pos.get("leverage") or 1.0),
            "pnl_usd": round(self._unrealized_pnl(pos, market_price), 4),
            "fees_usd": 0.0,
            "exit_reason": exit_reason,
            "gross_pnl": round(self._unrealized_pnl(pos, market_price), 4),
            "ai_reasoning": str(pos.get("ai_reasoning") or ""),
            "execution_pipe": response,
            "slippage_guard": guard,
        }
        del self.positions[symbol]
        self.trade_logger.log_trade(trade)
        return trade

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _unrealized_pnl(pos: dict[str, Any], mark: float) -> float:
        size = float(pos["size"])
        entry = float(pos["entry_price"])
        if pos["direction"] == "LONG":
            return (mark - entry) * size
        return (entry - mark) * size

    @staticmethod
    def _exit_reason(
        pos: dict[str, Any],
        mark: float,
        signal: str | None,
    ) -> str | None:
        direction = pos["direction"]
        sl = float(pos["stop_loss"])
        tp = float(pos["take_profit"])

        if direction == "LONG":
            if mark <= sl:
                return "SL Hit"
            if mark >= tp:
                return "TP Hit"
            if signal == "SELL":
                return "Signal Change"
        else:
            if mark >= sl:
                return "SL Hit"
            if mark <= tp:
                return "TP Hit"
            if signal == "BUY":
                return "Signal Change"
        return None

    def sync_open_order_state(self, mark_prices: dict[str, float] | None = None) -> dict[str, Any]:
        """
        Restore / re-sync open position marks after WS reconnect so active
        trade tracking continues without data loss.
        """
        mark_prices = mark_prices or {}
        synced = 0
        for symbol, pos in self.positions.items():
            mark = float(mark_prices.get(symbol) or pos.get("mark_price") or pos.get("entry_price") or 0.0)
            if mark <= 0:
                continue
            pos["mark_price"] = round(mark, 8)
            pos["unrealized_pnl"] = round(self._unrealized_pnl(pos, mark), 4)
            synced += 1
        self._save_portfolio()
        return {
            "ok": True,
            "synced_positions": synced,
            "wallet_balance": round(self.wallet_balance, 4),
            "updated_at": _utc_now(),
        }

    def _load_portfolio(self, starting_balance: float) -> None:
        backup_path = Path(getattr(config, "STATE_BACKUP_PATH", "state_backup.json"))
        data: dict[str, Any] | None = None
        for path in (self.portfolio_path, backup_path):
            if not path.exists():
                continue
            try:
                with path.open("r", encoding="utf-8") as fh:
                    loaded = json.load(fh)
                if isinstance(loaded, dict) and (
                    "wallet_balance" in loaded or "positions" in loaded
                ):
                    data = loaded
                    break
            except (json.JSONDecodeError, OSError):
                continue

        if data is None:
            self.wallet_balance = float(starting_balance)
            self.realized_pnl = 0.0
            self.positions = {}
            self._save_portfolio()
            return

        self.wallet_balance = float(data.get("wallet_balance", starting_balance))
        self.realized_pnl = float(data.get("realized_pnl", 0.0))
        self.positions = {
            str(k): v for k, v in (data.get("positions") or {}).items()
        }

    def _save_portfolio(self) -> None:
        payload = {
            "mode": self.mode.value,
            "updated_at": _utc_now(),
            "wallet_balance": round(self.wallet_balance, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "positions": self.positions,
        }
        with self.portfolio_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
        # Mirror to local fallback ledger for crash-safe restarts
        try:
            backup_path = Path(getattr(config, "STATE_BACKUP_PATH", "state_backup.json"))
            with backup_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
        except OSError:
            pass
