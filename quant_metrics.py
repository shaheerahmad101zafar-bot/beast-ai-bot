"""
Institutional quant metrics over realized trade history.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class QuantMetrics:
    @staticmethod
    def compute(trades: list[dict[str, Any]]) -> dict[str, Any]:
        if not trades:
            return {
                "sharpe_ratio": 0.0,
                "sortino_ratio": 0.0,
                "var_24h_usd": 0.0,
                "returns_count": 0,
                "updated_at": _utc_now(),
            }
        returns: list[float] = []
        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_pnls: list[float] = []
        for trade in trades:
            pnl = float(trade.get("pnl_usd") or 0.0)
            entry = abs(float(trade.get("entry_price") or 0.0) * float(trade.get("size") or 0.0))
            base = max(entry, 1.0)
            returns.append(pnl / base)
            ts = str(trade.get("timestamp") or "")
            try:
                dt = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
                if dt >= recent_cutoff:
                    recent_pnls.append(pnl)
            except Exception:
                continue
        if not returns:
            returns = [0.0]
        mean = sum(returns) / len(returns)
        variance = sum((r - mean) ** 2 for r in returns) / max(len(returns) - 1, 1)
        std = math.sqrt(max(variance, 0.0))
        downside = [r for r in returns if r < 0]
        down_std = math.sqrt(sum(r * r for r in downside) / max(len(downside), 1)) if downside else 0.0
        sharpe = (mean / std) * math.sqrt(len(returns)) if std > 0 else 0.0
        sortino = (mean / down_std) * math.sqrt(len(returns)) if down_std > 0 else 0.0
        recent_sorted = sorted(recent_pnls or [0.0])
        idx = max(0, math.floor(0.05 * (len(recent_sorted) - 1)))
        var_24h = abs(float(recent_sorted[idx]))
        return {
            "sharpe_ratio": round(sharpe, 3),
            "sortino_ratio": round(sortino, 3),
            "var_24h_usd": round(var_24h, 2),
            "returns_count": len(returns),
            "updated_at": _utc_now(),
        }


quant_metrics = QuantMetrics()
