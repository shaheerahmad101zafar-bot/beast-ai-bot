"""
Macro correlation and geopolitical shock guard.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from hedging_engine import hedging_engine


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class MacroGuard:
    def __init__(self) -> None:
        self._last_snapshot: dict[str, Any] = {
            "dxy_vol": 0.0,
            "spx_vol": 0.0,
            "shock_score": 0.0,
            "label": "calm",
            "updated_at": _utc_now(),
        }

    @staticmethod
    def _fetch_chart(symbol: str) -> list[float]:
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        resp = requests.get(url, params={"range": "5d", "interval": "15m"}, timeout=8)
        resp.raise_for_status()
        result = ((resp.json() or {}).get("chart") or {}).get("result") or [{}]
        closes = (((result[0] or {}).get("indicators") or {}).get("quote") or [{}])[0].get("close") or []
        return [float(x) for x in closes if x is not None]

    @staticmethod
    def _realized_vol(closes: list[float]) -> float:
        if len(closes) < 10:
            return 0.0
        moves = [abs((closes[i] - closes[i - 1]) / max(closes[i - 1], 1e-9)) for i in range(1, len(closes))]
        recent = moves[-24:]
        return round(sum(recent) / len(recent) * 100, 4)

    def snapshot(self) -> dict[str, Any]:
        try:
            dxy_vol = self._realized_vol(self._fetch_chart("DX-Y.NYB"))
            spx_vol = self._realized_vol(self._fetch_chart("ES=F"))
            shock_score = min(100.0, dxy_vol * 18.0 + spx_vol * 14.0)
            label = "shock" if shock_score >= 65 else ("elevated" if shock_score >= 35 else "calm")
            self._last_snapshot = {
                "dxy_vol": dxy_vol,
                "spx_vol": spx_vol,
                "shock_score": round(shock_score, 2),
                "label": label,
                "updated_at": _utc_now(),
            }
        except Exception as exc:
            self._last_snapshot = {**self._last_snapshot, "error": str(exc), "updated_at": _utc_now()}
        return dict(self._last_snapshot)

    def apply_guard(self, execution, mark_prices: dict[str, float]) -> dict[str, Any]:
        snap = self.snapshot()
        positions = list(execution.positions.values())
        if not positions:
            return {**snap, "acted": False}
        if snap.get("label") == "shock":
            hedge = hedging_engine.apply_flash_hedge(execution, positions=positions, mark_prices=mark_prices)
            for pos in execution.positions.values():
                pos["leverage"] = round(max(1.0, float(pos.get("leverage") or 1.0) * 0.65), 2)
            return {**snap, "acted": True, "action": "hedge_and_reduce_leverage", "hedge": hedge}
        if snap.get("label") == "elevated":
            for pos in execution.positions.values():
                pos["leverage"] = round(max(1.0, float(pos.get("leverage") or 1.0) * 0.85), 2)
            return {**snap, "acted": True, "action": "reduce_leverage"}
        return {**snap, "acted": False}


macro_guard = MacroGuard()
