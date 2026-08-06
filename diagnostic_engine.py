"""
Coin Diagnostic Terminal intelligence engine.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import requests

from bot_service import bot_service
from market_data import MarketDataEngine
from news_fetcher import news_fetcher


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class DiagnosticEngine:
    def __init__(self) -> None:
        self.market = MarketDataEngine()

    def _post_mortem(self, trade: dict[str, Any]) -> dict[str, Any]:
        reasons: list[str] = []
        pnl = float(trade.get("pnl_usd") or 0.0)
        exit_reason = str(trade.get("exit_reason") or "")
        ai_reasoning = str(trade.get("ai_reasoning") or "")
        if pnl < 0:
            reasons.append("Slippage and adverse momentum likely amplified the loss.")
        else:
            reasons.append("Directional confluence and favorable follow-through supported the trade.")
        if "sl" in exit_reason.lower() or "stop" in exit_reason.lower():
            reasons.append("Stop-loss was hit before the market could recover.")
        if "tp" in exit_reason.lower():
            reasons.append("Take-profit captured the impulse before mean reversion.")
        if "panic" in exit_reason.lower():
            reasons.append("Macro panic protection intervened to cap cascading downside.")
        if "HFT" in ai_reasoning.upper():
            reasons.append("Microstructure noise and order book velocity dominated the outcome.")
        if not reasons:
            reasons.append("Outcome driven by local liquidity, fees, and directional follow-through.")
        return {"headline": " ".join(reasons[:2]), "details": reasons, "ai_reasoning": ai_reasoning}

    def _surge_metrics(self, symbol: str) -> dict[str, Any]:
        df = self.market.get_market_snapshot(symbol, timeframe="1m", limit=120)
        if df.empty:
            return {"pump": 0.0, "dump": 0.0, "vol_1m": 0.0, "vol_5m": 0.0, "vol_1h": 0.0}
        vol = df["volume"].astype(float)
        close = df["close"].astype(float)
        vol_1m = float(vol.iloc[-1] / max(vol.tail(20).mean(), 1e-9))
        vol_5m = float(vol.tail(5).sum() / max(vol.tail(25).mean() * 5, 1e-9))
        vol_1h = float(vol.tail(60).sum() / max(vol.mean() * 60, 1e-9))
        move = float(((close.iloc[-1] - close.iloc[-5]) / max(close.iloc[-5], 1e-9)) * 100)
        return {
            "pump": round(max(0.0, move), 3),
            "dump": round(max(0.0, -move), 3),
            "vol_1m": round(vol_1m, 3),
            "vol_5m": round(vol_5m, 3),
            "vol_1h": round(vol_1h, 3),
        }

    def _depth_metrics(self, symbol: str) -> dict[str, Any]:
        raw = symbol.replace("/", "")
        try:
            resp = requests.get(
                "https://fapi.binance.com/fapi/v1/depth",
                params={"symbol": raw, "limit": 20},
                timeout=8,
            )
            resp.raise_for_status()
            data = resp.json()
            bids = data.get("bids") or []
            asks = data.get("asks") or []
            bid_notional = sum(float(px) * float(qty) for px, qty in bids[:10])
            ask_notional = sum(float(px) * float(qty) for px, qty in asks[:10])
            return {
                "bid_depth_usd": round(bid_notional, 2),
                "ask_depth_usd": round(ask_notional, 2),
                "imbalance_pct": round(((bid_notional - ask_notional) / max(bid_notional + ask_notional, 1e-9)) * 100, 3),
            }
        except Exception:
            return {"bid_depth_usd": 0.0, "ask_depth_usd": 0.0, "imbalance_pct": 0.0}

    def snapshot(self, limit: int = 40) -> dict[str, Any]:
        history = bot_service.get_trade_history(limit=limit).get("trades") or []
        positions = bot_service.get_portfolio().get("positions") or []
        symbols = list({str(t.get("pair") or "") for t in history if t.get("pair")} | {str(p.get("symbol") or "") for p in positions if p.get("symbol")})
        cards: list[dict[str, Any]] = []
        for symbol in symbols[:20]:
            trades = [t for t in history if str(t.get("pair") or "") == symbol][:5]
            cards.append(
                {
                    "symbol": symbol,
                    "open_positions": [p for p in positions if str(p.get("symbol") or "") == symbol],
                    "post_mortems": [{**t, "analysis": self._post_mortem(t)} for t in trades],
                    "surge": self._surge_metrics(symbol),
                    "depth": self._depth_metrics(symbol),
                    "news": news_fetcher.for_symbol(symbol, limit=5).get("items", []),
                }
            )
        return {"ok": True, "cards": cards, "updated_at": _utc_now()}


diagnostic_engine = DiagnosticEngine()
