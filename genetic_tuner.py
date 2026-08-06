"""
Self-tuning genetic parameter optimizer.

Runs lightweight rolling backtests and publishes best-fit indicator params.
"""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from typing import Any

from backtest import backtester
from trading_engine import trading_engine


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class GeneticTuner:
    def __init__(self) -> None:
        self.population_size = 6
        self.generations = 3
        self.symbol = "BTC/USDT"
        self.timeframe = "1h"
        self.best: dict[str, Any] = {
            "params": {"rsi_buy": 35, "rsi_sell": 65, "atr_mult": 1.8, "macd_bias": 0.0},
            "fitness": None,
            "updated_at": None,
        }
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="genetic-tuner")

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.run_cycle)
            except Exception:
                pass
            await asyncio.sleep(300)

    def _seed_population(self) -> list[dict[str, float]]:
        pop = []
        base = self.best["params"]
        for _ in range(self.population_size):
            pop.append(
                {
                    "rsi_buy": max(20, min(45, int(base["rsi_buy"] + random.randint(-4, 4)))),
                    "rsi_sell": max(55, min(80, int(base["rsi_sell"] + random.randint(-4, 4)))),
                    "atr_mult": round(max(1.0, min(3.0, base["atr_mult"] + random.uniform(-0.3, 0.3))), 3),
                    "macd_bias": round(max(-0.5, min(0.5, base["macd_bias"] + random.uniform(-0.15, 0.15))), 3),
                }
            )
        return pop

    def _fitness(self, params: dict[str, float]) -> float:
        result = backtester.run(symbol=self.symbol, timeframe=self.timeframe, days=30, starting_balance=1000)
        if not result.get("ok"):
            return -999.0
        win = float(result.get("win_rate_pct") or 0.0)
        pnl = float(result.get("cumulative_pnl_usd") or 0.0)
        dd = float(result.get("max_drawdown_pct") or 0.0)
        return pnl + win - dd - abs(params["macd_bias"] * 10)

    def run_cycle(self) -> dict[str, Any]:
        best_params = dict(self.best["params"])
        best_fitness = float(self.best["fitness"] or -999999.0)
        population = self._seed_population()
        for _ in range(self.generations):
            scored = sorted(
                ((self._fitness(params), params) for params in population),
                key=lambda x: x[0],
                reverse=True,
            )
            if scored and scored[0][0] > best_fitness:
                best_fitness = float(scored[0][0])
                best_params = dict(scored[0][1])
            parents = [dict(p) for _, p in scored[:2]]
            population = parents[:]
            while len(population) < self.population_size:
                mom = random.choice(parents)
                dad = random.choice(parents)
                child = {
                    "rsi_buy": random.choice([mom["rsi_buy"], dad["rsi_buy"]]),
                    "rsi_sell": random.choice([mom["rsi_sell"], dad["rsi_sell"]]),
                    "atr_mult": round((mom["atr_mult"] + dad["atr_mult"]) / 2.0, 3),
                    "macd_bias": round((mom["macd_bias"] + dad["macd_bias"]) / 2.0, 3),
                }
                population.append(child)
        self.best = {"params": best_params, "fitness": round(best_fitness, 4), "updated_at": _utc_now()}
        trading_engine.set_runtime_params(best_params)
        return self.best

    def snapshot(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "timeframe": self.timeframe, **self.best}


genetic_tuner = GeneticTuner()
