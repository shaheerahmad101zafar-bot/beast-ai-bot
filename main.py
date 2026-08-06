"""
Beast AI Trading Bot — Phase 3 Entrypoint

Automated paper-trading loop:
  market data -> strategy signal -> risk sizing -> execution -> SL/TP monitor
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import config
from execution_engine import ExecutionEngine
from market_data import MarketDataEngine
from network_tuning import apply_global_socket_tuning
from risk_manager import DEFAULT_ACCOUNT_BALANCE, RiskManager
from strategy import SignalGenerator
from trading_engine import trading_engine
from trade_logger import TradeLogger

apply_global_socket_tuning()


def _fmt(value: float | None, decimals: int = 2) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "N/A"
    return f"{value:,.{decimals}f}"


def _clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_table(headers: list[str], rows: list[list[str]]) -> None:
    if not rows:
        print("  (none)")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    header_row = "|" + "|".join(f" {h:<{w}} " for h, w in zip(headers, widths, strict=True)) + "|"
    print(sep)
    print(header_row)
    print(sep)
    for row in rows:
        print("|" + "|".join(f" {c:>{w}} " for c, w in zip(row, widths, strict=True)) + "|")
    print(sep)


def evaluate_universe(
    market: MarketDataEngine,
    signal_gen: SignalGenerator,
    risk_mgr: RiskManager,
    pairs: list[str],
    timeframe: str,
    sentiment_score: float | None = None,
) -> list[dict[str, Any]]:
    """Fetch enriched OHLCV and produce signal + risk packages per pair."""
    results: list[dict[str, Any]] = []
    for symbol in pairs:
        df = market.get_market_snapshot(symbol, timeframe=timeframe)
        if df.empty:
            continue
        signal = trading_engine.evaluate(
            df,
            symbol=symbol,
            sentiment_score=sentiment_score,
            equity=risk_mgr.account_balance,
        )
        risk = risk_mgr.evaluate_trade(signal)
        results.append({**signal, **risk, "candles": len(df)})
    return results


def maybe_execute(
    execution: ExecutionEngine,
    scan_row: dict[str, Any],
    min_confidence: float,
) -> dict[str, Any] | None:
    """
    Open a paper/live order when signal is actionable and no position exists.

    Returns {"message": str, "order": dict|None, "signal": str|None} or None.
    """
    symbol = str(scan_row["symbol"])
    signal = str(scan_row["signal"])
    confidence = float(scan_row["confidence_score"])

    if signal not in {"BUY", "SELL"}:
        return None
    if confidence < min_confidence:
        return {
            "message": f"SKIP {symbol}: confidence {confidence:.1f}% < {min_confidence:.1f}%",
            "order": None,
            "signal": signal,
        }
    if execution.has_position(symbol):
        return {
            "message": f"SKIP {symbol}: position already open",
            "order": None,
            "signal": signal,
        }

    try:
        order = execution.place_order(
            symbol=symbol,
            signal=signal,
            size_units=float(scan_row["position_size_units"]),
            leverage=float(scan_row["leverage"]),
            market_price=float(scan_row["entry_price"]),
            stop_loss=float(scan_row["stop_loss_price"]),
            take_profit=float(scan_row["take_profit_price"]),
            metadata={"ai_reasoning": str(scan_row.get("ai_reasoning") or "")},
        )
        return {
            "message": (
                f"OPEN {order['direction']} {symbol} @ {_fmt(float(order['entry_price']))} | "
                f"size={_fmt(float(order['size']), 6)} lev={_fmt(float(order['leverage']), 1)}x"
            ),
            "order": order,
            "signal": signal,
            "scan_row": scan_row,
        }
    except Exception as exc:  # noqa: BLE001 - surface to dashboard
        return {"message": f"ERROR {symbol}: {exc}", "order": None, "signal": signal}


def render_dashboard(
    cycle: int,
    interval: int,
    portfolio: dict[str, Any],
    scan_rows: list[dict[str, Any]],
    events: list[str],
    trade_logger: TradeLogger,
) -> None:
    _clear_screen()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    width = 108

    print("=" * width)
    print("  Beast AI Trading Bot - Phase 3 Automated Paper Trading Dashboard")
    print(f"  Mode     : {portfolio['mode']}")
    print(f"  Time     : {now}  |  Cycle #{cycle}  |  Interval {interval}s")
    print("=" * width)
    print(
        f"  Equity ${_fmt(float(portfolio['equity']))}  |  "
        f"Wallet ${_fmt(float(portfolio['wallet_balance']))}  |  "
        f"Available ${_fmt(float(portfolio['available_balance']))}  |  "
        f"Realized PnL ${_fmt(float(portfolio['realized_pnl']))}  |  "
        f"Closed Trades {trade_logger.trade_count()}"
    )
    print("-" * width)

    print("\n  ACTIVE POSITIONS")
    pos_headers = ["Pair", "Side", "Entry", "Mark", "Size", "Lev", "uPnL", "SL", "TP"]
    pos_rows: list[list[str]] = []
    for p in portfolio.get("positions") or []:
        pos_rows.append(
            [
                str(p["symbol"]),
                str(p["direction"]),
                _fmt(float(p["entry_price"])),
                _fmt(float(p["mark_price"])),
                _fmt(float(p["size"]), 6),
                f"{_fmt(float(p['leverage']), 1)}x",
                _fmt(float(p["unrealized_pnl"])),
                _fmt(float(p["stop_loss"])),
                _fmt(float(p["take_profit"])),
            ]
        )
    _print_table(pos_headers, pos_rows)

    print("\n  LIVE MARKET SCANNER")
    scan_headers = ["Pair", "Price", "Signal", "Conf %", "Pos Notional", "Lev", "SL", "TP"]
    scan_table: list[list[str]] = []
    for r in scan_rows:
        scan_table.append(
            [
                str(r["symbol"]),
                _fmt(float(r["entry_price"])),
                str(r["signal"]),
                _fmt(float(r["confidence_score"]), 1),
                _fmt(float(r["position_size_notional"])),
                f"{_fmt(float(r['leverage']), 1)}x",
                _fmt(float(r["stop_loss_price"])),
                _fmt(float(r["take_profit_price"])),
            ]
        )
    _print_table(scan_headers, scan_table)

    print("\n  CYCLE EVENTS")
    if events:
        for event in events:
            print(f"  - {event}")
    else:
        print("  - No new events")
    print()
    print("  Press Ctrl+C to stop gracefully.")
    print("=" * width)


def run_loop(
    interval: int,
    cycles: int | None,
    account_balance: float,
    mode: str,
    min_confidence: float,
    seed_demo: bool,
) -> None:
    trade_logger = TradeLogger()
    execution = ExecutionEngine(
        mode=mode,
        starting_balance=account_balance,
        trade_logger=trade_logger,
    )
    market = MarketDataEngine()
    signal_gen = SignalGenerator()
    pairs = list(config.DEFAULT_TRADING_PAIRS)
    timeframe = config.DEFAULT_TIMEFRAME

    cycle = 0
    try:
        while True:
            cycle += 1
            events: list[str] = []

            risk_mgr = RiskManager(account_balance=execution.equity())
            scan_rows = evaluate_universe(
                market=market,
                signal_gen=signal_gen,
                risk_mgr=risk_mgr,
                pairs=pairs,
                timeframe=timeframe,
            )
            mark_prices = {str(r["symbol"]): float(r["entry_price"]) for r in scan_rows}
            signal_map = {str(r["symbol"]): str(r["signal"]) for r in scan_rows}

            # Optional first-cycle demo fill so SL/TP monitoring is visible even in HOLD markets
            if seed_demo and cycle == 1 and scan_rows and not execution.positions:
                demo = scan_rows[0]
                px = float(demo["entry_price"])
                atr = float(demo.get("atr") or px * 0.01)
                try:
                    order = execution.place_order(
                        symbol=str(demo["symbol"]),
                        signal="BUY",
                        size_units=max(float(demo["position_size_units"]) * 0.25, 1e-6),
                        leverage=min(float(demo["leverage"]), 5.0),
                        market_price=px,
                        stop_loss=px - atr * 1.5,
                        take_profit=px + atr * 3.0,
                    )
                    events.append(
                        f"DEMO OPEN LONG {order['symbol']} @ {_fmt(float(order['entry_price']))} "
                        f"(seed-demo for SL/TP path)"
                    )
                except Exception as exc:  # noqa: BLE001
                    events.append(f"DEMO OPEN failed: {exc}")

            closed = execution.monitor_positions(mark_prices, signals=signal_map)
            for trade in closed:
                events.append(
                    f"CLOSE {trade['direction']} {trade['pair']} @ {_fmt(float(trade['exit_price']))} | "
                    f"PnL ${_fmt(float(trade['pnl_usd']))} | {trade['exit_reason']}"
                )

            for row in scan_rows:
                msg = maybe_execute(execution, row, min_confidence=min_confidence)
                if msg:
                    events.append(msg)

            # Refresh marks after any new opens
            portfolio = execution.portfolio_snapshot(mark_prices)
            render_dashboard(
                cycle=cycle,
                interval=interval,
                portfolio=portfolio,
                scan_rows=scan_rows,
                events=events,
                trade_logger=trade_logger,
            )

            if cycles is not None and cycle >= cycles:
                print(f"\nCompleted {cycles} cycle(s). Exiting.")
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n\nStopped by user. Portfolio persisted to", config.PAPER_PORTFOLIO_PATH)
    finally:
        market.close()
        execution.save()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Beast AI Trading Bot - Phase 3")
    parser.add_argument(
        "--mode",
        default=config.EXECUTION_MODE,
        choices=["PAPER_TRADING", "LIVE_BINANCE"],
        help="Execution mode (default: PAPER_TRADING)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=config.LOOP_INTERVAL_SECONDS,
        help="Seconds between scan cycles (default: 10)",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=None,
        help="Optional max cycles (default: run forever)",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=DEFAULT_ACCOUNT_BALANCE,
        help="Starting paper balance if no portfolio file exists",
    )
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=config.MIN_SIGNAL_CONFIDENCE,
        help="Minimum confidence %% required to open a trade",
    )
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Open a small demo LONG on cycle 1 to exercise the paper engine",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    if args.mode == "LIVE_BINANCE":
        print(
            "LIVE_BINANCE is scaffolded but order routing is intentionally disabled. "
            "Use PAPER_TRADING for automated simulation."
        )
        sys.exit(1)

    run_loop(
        interval=max(1, int(args.interval)),
        cycles=args.cycles,
        account_balance=float(args.balance),
        mode=args.mode,
        min_confidence=float(args.min_confidence),
        seed_demo=bool(args.seed_demo),
    )


if __name__ == "__main__":
    main()
