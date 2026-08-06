"""
Beast AI historical strategy backtester.

Compatibility surface for `/api/backtest` and genetic tuner.
Delegates to the L3-slippage-aware engine while preserving the
classic `backtester` import path.
"""

from __future__ import annotations

from backtest_engine import BacktestEngine, backtester

__all__ = ["BacktestEngine", "Backtester", "backtester"]

# Alias retained for older call sites expecting `Backtester`.
Backtester = BacktestEngine
