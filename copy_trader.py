"""
Beast AI Trading Bot — Phase 6 Copy Trading Execution Layer

Master -> Follower replication with equity-proportional sizing and a
15% master profit-share ledger.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
from vault import CredentialVault, vault


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class CopyTradingManager:
    """Replicate master fills across follower accounts with proportional sizing."""

    def __init__(
        self,
        credential_vault: CredentialVault | None = None,
        ledger_path: str | Path = config.COPY_LEDGER_PATH,
        profit_share_pct: float = config.COPY_PROFIT_SHARE_PCT,
        live_orders: bool = config.COPY_TRADING_LIVE_ORDERS,
    ) -> None:
        self.vault = credential_vault or vault
        self.ledger_path = Path(ledger_path)
        self.profit_share_pct = float(profit_share_pct)
        self.live_orders = bool(live_orders)
        self._lock = threading.RLock()
        self._ledger = self._load_ledger()

    # ------------------------------------------------------------------
    # Ledger persistence
    # ------------------------------------------------------------------
    def _load_ledger(self) -> dict[str, Any]:
        if not self.ledger_path.exists():
            return {
                "version": 1,
                "updated_at": _utc_now(),
                "followers": {},
                "events": [],
            }
        try:
            with self.ledger_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            data.setdefault("followers", {})
            data.setdefault("events", [])
            return data
        except (OSError, json.JSONDecodeError):
            return {
                "version": 1,
                "updated_at": _utc_now(),
                "followers": {},
                "events": [],
            }

    def _save_ledger(self) -> None:
        self._ledger["updated_at"] = _utc_now()
        with self.ledger_path.open("w", encoding="utf-8") as fh:
            json.dump(self._ledger, fh, indent=2)

    def _follower_stats(self, account_id: str) -> dict[str, Any]:
        followers = self._ledger["followers"]
        if account_id not in followers:
            followers[account_id] = {
                "account_id": account_id,
                "copied_trades": 0,
                "open_copies": 0,
                "realized_pnl": 0.0,
                "gross_profit": 0.0,
                "master_commission": 0.0,
                "net_follower_pnl": 0.0,
                "last_copy_at": None,
                "status": "idle",
            }
        return followers[account_id]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def list_followers(self) -> list[dict[str, Any]]:
        with self._lock:
            accounts = self.vault.get_followers(include_secrets=False)
            rows: list[dict[str, Any]] = []
            for acc in accounts:
                stats = self._follower_stats(acc["id"])
                rows.append(
                    {
                        **acc,
                        "copy_status": stats.get("status", "idle"),
                        "copied_trades": stats.get("copied_trades", 0),
                        "open_copies": stats.get("open_copies", 0),
                        "realized_pnl": round(float(stats.get("realized_pnl") or 0.0), 4),
                        "gross_profit": round(float(stats.get("gross_profit") or 0.0), 4),
                        "master_commission": round(
                            float(stats.get("master_commission") or 0.0), 4
                        ),
                        "net_follower_pnl": round(
                            float(stats.get("net_follower_pnl") or 0.0), 4
                        ),
                        "last_copy_at": stats.get("last_copy_at"),
                        "equity": acc.get("equity_hint")
                        or (acc.get("permissions") or {}).get("equity")
                        or 0.0,
                    }
                )
            # Leaderboard: highest net follower pnl first
            rows.sort(key=lambda r: float(r.get("net_follower_pnl") or 0.0), reverse=True)
            return rows

    def leaderboard_summary(self) -> dict[str, Any]:
        followers = self.list_followers()
        master = self.vault.get_master(include_secrets=False)
        total_commission = sum(float(f.get("master_commission") or 0.0) for f in followers)
        total_follower_pnl = sum(float(f.get("net_follower_pnl") or 0.0) for f in followers)
        return {
            "master": master,
            "follower_count": len(followers),
            "followers": followers,
            "total_master_commission": round(total_commission, 4),
            "total_follower_net_pnl": round(total_follower_pnl, 4),
            "profit_share_pct": self.profit_share_pct * 100.0,
            "live_orders": self.live_orders,
            "updated_at": self._ledger.get("updated_at"),
        }

    def proportional_size(
        self,
        master_equity: float,
        follower_equity: float,
        master_size_units: float,
    ) -> float:
        """
        Scale follower units by equity ratio.

        Example: Master $10,000 / Follower $100 => 1% of master size.
        """
        if master_equity <= 0 or follower_equity <= 0 or master_size_units <= 0:
            return 0.0
        ratio = follower_equity / master_equity
        return round(master_size_units * ratio, 8)

    def on_master_open(
        self,
        *,
        symbol: str,
        signal: str,
        master_size_units: float,
        master_equity: float,
        market_price: float,
        leverage: float,
        stop_loss: float,
        take_profit: float,
        master_trade_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Replicate a master open across all active followers."""
        with self._lock:
            results: list[dict[str, Any]] = []
            followers = self.vault.get_followers(include_secrets=True)
            for acc in followers:
                stats = self._follower_stats(acc["id"])
                follower_equity = float(
                    acc.get("equity_hint")
                    or (acc.get("permissions") or {}).get("equity")
                    or 0.0
                )
                size = self.proportional_size(
                    master_equity=master_equity,
                    follower_equity=follower_equity,
                    master_size_units=master_size_units,
                )
                if size <= 0:
                    results.append(
                        {
                            "account_id": acc["id"],
                            "label": acc.get("label"),
                            "status": "skipped",
                            "reason": "Non-positive proportional size",
                        }
                    )
                    continue

                try:
                    fill = self._execute_follower_order(
                        account=acc,
                        symbol=symbol,
                        signal=signal,
                        size_units=size,
                        market_price=market_price,
                        leverage=leverage,
                    )
                    event = {
                        "event_id": str(uuid.uuid4())[:8],
                        "type": "copy_open",
                        "timestamp": _utc_now(),
                        "account_id": acc["id"],
                        "label": acc.get("label"),
                        "exchange": acc.get("exchange"),
                        "symbol": symbol,
                        "signal": signal,
                        "direction": "LONG" if signal == "BUY" else "SHORT",
                        "master_trade_id": master_trade_id,
                        "master_equity": master_equity,
                        "follower_equity": follower_equity,
                        "equity_ratio": round(follower_equity / master_equity, 8)
                        if master_equity
                        else 0.0,
                        "size_units": size,
                        "entry_price": fill.get("entry_price", market_price),
                        "leverage": leverage,
                        "stop_loss": stop_loss,
                        "take_profit": take_profit,
                        "mode": fill.get("mode"),
                        "status": "filled",
                    }
                    self._ledger["events"].append(event)
                    stats["copied_trades"] = int(stats.get("copied_trades") or 0) + 1
                    stats["open_copies"] = int(stats.get("open_copies") or 0) + 1
                    stats["last_copy_at"] = event["timestamp"]
                    stats["status"] = "copying"
                    # stash open copy for close matching
                    opens = stats.setdefault("open_positions", {})
                    opens[symbol] = {
                        "direction": event["direction"],
                        "size_units": size,
                        "entry_price": event["entry_price"],
                        "master_trade_id": master_trade_id,
                        "opened_at": event["timestamp"],
                    }
                    results.append(event)
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        {
                            "account_id": acc["id"],
                            "label": acc.get("label"),
                            "status": "error",
                            "reason": str(exc),
                        }
                    )
                    stats["status"] = "error"

            self._save_ledger()
            return results

    def on_master_close(
        self,
        *,
        symbol: str,
        exit_price: float,
        master_trade_id: str | None = None,
        pnl_usd: float | None = None,
    ) -> list[dict[str, Any]]:
        """Close mirrored follower positions and book profit share."""
        with self._lock:
            results: list[dict[str, Any]] = []
            followers = self.vault.get_followers(include_secrets=True)

            for acc in followers:
                stats = self._follower_stats(acc["id"])
                opens = stats.get("open_positions") or {}
                pos = opens.get(symbol)
                if not pos:
                    continue

                direction = pos["direction"]
                size = float(pos["size_units"])
                entry = float(pos["entry_price"])
                gross = (
                    (exit_price - entry) * size
                    if direction == "LONG"
                    else (entry - exit_price) * size
                )

                commission = 0.0
                if gross > 0:
                    commission = gross * self.profit_share_pct
                net = gross - commission

                try:
                    self._close_follower_position(acc, symbol, direction, size)
                except Exception as exc:  # noqa: BLE001
                    results.append(
                        {
                            "account_id": acc["id"],
                            "status": "error",
                            "reason": str(exc),
                        }
                    )
                    continue

                event = {
                    "event_id": str(uuid.uuid4())[:8],
                    "type": "copy_close",
                    "timestamp": _utc_now(),
                    "account_id": acc["id"],
                    "label": acc.get("label"),
                    "symbol": symbol,
                    "direction": direction,
                    "entry_price": entry,
                    "exit_price": exit_price,
                    "size_units": size,
                    "gross_pnl": round(gross, 4),
                    "master_commission": round(commission, 4),
                    "net_follower_pnl": round(net, 4),
                    "master_trade_id": master_trade_id or pos.get("master_trade_id"),
                    "master_pnl_ref": pnl_usd,
                    "status": "closed",
                }
                self._ledger["events"].append(event)

                stats["realized_pnl"] = round(float(stats.get("realized_pnl") or 0.0) + gross, 4)
                if gross > 0:
                    stats["gross_profit"] = round(
                        float(stats.get("gross_profit") or 0.0) + gross, 4
                    )
                stats["master_commission"] = round(
                    float(stats.get("master_commission") or 0.0) + commission, 4
                )
                stats["net_follower_pnl"] = round(
                    float(stats.get("net_follower_pnl") or 0.0) + net, 4
                )
                stats["open_copies"] = max(0, int(stats.get("open_copies") or 0) - 1)
                stats["status"] = "idle" if stats["open_copies"] == 0 else "copying"
                del opens[symbol]
                results.append(event)

            self._save_ledger()
            return results

    # ------------------------------------------------------------------
    # Execution helpers
    # ------------------------------------------------------------------
    def _execute_follower_order(
        self,
        account: dict[str, Any],
        symbol: str,
        signal: str,
        size_units: float,
        market_price: float,
        leverage: float,
    ) -> dict[str, Any]:
        if account.get("paper_mode") or not self.live_orders:
            slip = config.DEFAULT_SLIPPAGE_BPS / 10_000.0
            px = market_price * (1 + slip if signal == "BUY" else 1 - slip)
            return {
                "mode": "paper_copy",
                "entry_price": round(px, 8),
                "size_units": size_units,
                "leverage": leverage,
            }

        client = self.vault.build_exchange(account)
        try:
            side = "buy" if signal == "BUY" else "sell"
            if hasattr(client, "set_leverage"):
                try:
                    client.set_leverage(int(max(1, leverage)), symbol)
                except Exception:
                    pass
            order = client.create_order(symbol, "market", side, size_units)
            fill_px = float(order.get("average") or order.get("price") or market_price)
            return {
                "mode": "live_copy",
                "entry_price": fill_px,
                "size_units": size_units,
                "leverage": leverage,
                "order_id": order.get("id"),
            }
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _close_follower_position(
        self,
        account: dict[str, Any],
        symbol: str,
        direction: str,
        size_units: float,
    ) -> None:
        if account.get("paper_mode") or not self.live_orders:
            return
        client = self.vault.build_exchange(account)
        try:
            side = "sell" if direction == "LONG" else "buy"
            client.create_order(symbol, "market", side, size_units, params={"reduceOnly": True})
        finally:
            try:
                client.close()
            except Exception:
                pass


copy_trader = CopyTradingManager()
