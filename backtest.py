"""
Beast AI historical backtester.
"""

from __future__ import annotations

from typing import Any

from bot_service import bot_service
from risk_manager import DEFAULT_ACCOUNT_BALANCE
from trading_engine import trading_engine


class Backtester:
    def run(
        self,
        *,
        symbol: str,
        timeframe: str = "1h",
        days: int = 30,
        starting_balance: float = DEFAULT_ACCOUNT_BALANCE,
    ) -> dict[str, Any]:
        limit = max(120, min(1500, int(days * 24)))
        df = bot_service.market.get_market_snapshot(symbol, timeframe=timeframe, limit=limit)
        if df is None or df.empty or len(df) < 60:
            return {
                "ok": False,
                "detail": "Not enough history for backtest",
                "symbol": symbol,
                "timeframe": timeframe,
            }

        equity = float(starting_balance)
        peak = equity
        drawdown = 0.0
        trades: list[dict[str, Any]] = []
        curve: list[dict[str, Any]] = []
        position: dict[str, Any] | None = None

        for i in range(55, len(df)):
            hist = df.iloc[: i + 1].copy()
            row = hist.iloc[-1]
            signal = trading_engine.evaluate(
                hist,
                symbol=symbol,
                sentiment_score=50.0,
                equity=equity,
            )
            price = float(row["close"])
            ts = str(hist.index[-1])

            if position:
                side = position["direction"]
                entry = position["entry"]
                tp = position["tp"]
                sl = position["sl"]
                exit_reason = None
                if side == "LONG":
                    if float(row["low"]) <= sl:
                        exit_px = sl
                        exit_reason = "stop_loss"
                    elif float(row["high"]) >= tp:
                        exit_px = tp
                        exit_reason = "take_profit"
                else:
                    if float(row["high"]) >= sl:
                        exit_px = sl
                        exit_reason = "stop_loss"
                    elif float(row["low"]) <= tp:
                        exit_px = tp
                        exit_reason = "take_profit"
                if not exit_reason and signal.get("signal") in {"BUY", "SELL"}:
                    if (side == "LONG" and signal["signal"] == "SELL") or (
                        side == "SHORT" and signal["signal"] == "BUY"
                    ):
                        exit_px = price
                        exit_reason = "signal_flip"
                if exit_reason:
                    pnl = (
                        (exit_px - entry) * position["size"]
                        if side == "LONG"
                        else (entry - exit_px) * position["size"]
                    )
                    equity += pnl
                    trades.append(
                        {
                            "timestamp": ts,
                            "pair": symbol,
                            "direction": side,
                            "entry_price": round(entry, 8),
                            "exit_price": round(exit_px, 8),
                            "pnl_usd": round(pnl, 4),
                            "exit_reason": exit_reason,
                        }
                    )
                    position = None

            if not position and signal.get("signal") in {"BUY", "SELL"}:
                direction = "LONG" if signal["signal"] == "BUY" else "SHORT"
                risk_usd = equity * 0.01
                stop = float(signal.get("stop_loss_price") or price)
                dist = abs(price - stop) or price * 0.01
                size = risk_usd / dist
                position = {
                    "direction": direction,
                    "entry": price,
                    "tp": float(signal.get("take_profit_price") or price),
                    "sl": stop,
                    "size": size,
                }

            peak = max(peak, equity)
            drawdown = max(drawdown, 0.0 if peak <= 0 else (peak - equity) / peak)
            curve.append({"time": ts, "equity": round(equity, 4)})

        wins = sum(1 for t in trades if float(t.get("pnl_usd") or 0) > 0)
        total_pnl = sum(float(t.get("pnl_usd") or 0) for t in trades)
        return {
            "ok": True,
            "symbol": symbol,
            "timeframe": timeframe,
            "days": days,
            "starting_balance": round(starting_balance, 4),
            "ending_equity": round(equity, 4),
            "win_rate_pct": round((wins / len(trades)) * 100, 2) if trades else 0.0,
            "max_drawdown_pct": round(drawdown * 100, 3),
            "cumulative_pnl_usd": round(total_pnl, 4),
            "trade_count": len(trades),
            "equity_curve": curve,
            "trades": trades[-100:],
        }


backtester = Backtester()
