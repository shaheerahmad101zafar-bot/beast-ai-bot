"""
Beast AI Trading Bot — Phase 3 Trade Journal / Order Manager Log

Persists every executed (closed) trade to CSV and a JSON mirror.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config

TRADE_FIELDS: list[str] = [
    "timestamp",
    "pair",
    "direction",
    "entry_price",
    "exit_price",
    "size",
    "leverage",
    "pnl_usd",
    "fees_usd",
    "exit_reason",
    "trade_id",
]


class TradeLogger:
    """Append-only performance journal for closed trades."""

    def __init__(
        self,
        csv_path: str | Path = config.TRADE_HISTORY_CSV,
        json_path: str | Path = config.TRADE_HISTORY_JSON,
    ) -> None:
        self.csv_path = Path(csv_path)
        self.json_path = Path(json_path)
        self._ensure_csv_header()

    def _ensure_csv_header(self) -> None:
        if self.csv_path.exists() and self.csv_path.stat().st_size > 0:
            return
        with self.csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_FIELDS)
            writer.writeheader()

    def log_trade(self, trade: dict[str, Any]) -> dict[str, Any]:
        """
        Record a closed trade.

        Expected keys: pair, direction, entry_price, exit_price, pnl_usd,
        exit_reason; optional size, leverage, fees_usd, trade_id, timestamp.
        """
        record = {
            "timestamp": trade.get("timestamp")
            or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "pair": trade["pair"],
            "direction": trade["direction"],
            "entry_price": float(trade["entry_price"]),
            "exit_price": float(trade["exit_price"]),
            "size": float(trade.get("size") or 0.0),
            "leverage": float(trade.get("leverage") or 1.0),
            "pnl_usd": float(trade["pnl_usd"]),
            "fees_usd": float(trade.get("fees_usd") or 0.0),
            "exit_reason": trade["exit_reason"],
            "trade_id": trade.get("trade_id") or "",
        }

        with self.csv_path.open("a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=TRADE_FIELDS)
            writer.writerow(record)

        history = self.load_history()
        history.append(record)
        with self.json_path.open("w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2)

        return record

    def load_history(self) -> list[dict[str, Any]]:
        if self.json_path.exists():
            try:
                with self.json_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError):
                pass
        return self._load_history_from_csv()

    def _load_history_from_csv(self) -> list[dict[str, Any]]:
        if not self.csv_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        try:
            with self.csv_path.open("r", newline="", encoding="utf-8") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    try:
                        rows.append(
                            {
                                "timestamp": row.get("timestamp") or "",
                                "pair": row.get("pair") or "",
                                "direction": row.get("direction") or "",
                                "entry_price": float(row.get("entry_price") or 0.0),
                                "exit_price": float(row.get("exit_price") or 0.0),
                                "size": float(row.get("size") or 0.0),
                                "leverage": float(row.get("leverage") or 1.0),
                                "pnl_usd": float(row.get("pnl_usd") or 0.0),
                                "fees_usd": float(row.get("fees_usd") or 0.0),
                                "exit_reason": row.get("exit_reason") or "",
                                "trade_id": row.get("trade_id") or "",
                            }
                        )
                    except (TypeError, ValueError):
                        continue
        except OSError:
            return []
        return rows

    def realized_pnl_total(self) -> float:
        return round(sum(float(t.get("pnl_usd") or 0.0) for t in self.load_history()), 4)

    def trade_count(self) -> int:
        return len(self.load_history())
