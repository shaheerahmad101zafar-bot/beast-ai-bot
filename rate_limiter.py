"""
Global token-bucket rate limiter for exchange request weights.
"""

from __future__ import annotations

import asyncio
import time


class TokenBucket:
    def __init__(self, capacity: int, refill_per_sec: float) -> None:
        self.capacity = float(capacity)
        self.tokens = float(capacity)
        self.refill_per_sec = float(refill_per_sec)
        self.updated_at = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, weight: int = 1) -> None:
        need = float(max(1, weight))
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self.updated_at
                self.updated_at = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_per_sec)
                if self.tokens >= need:
                    self.tokens -= need
                    return
                wait_s = (need - self.tokens) / max(self.refill_per_sec, 1e-9)
            await asyncio.sleep(min(max(wait_s, 0.05), 2.0))


binance_bucket = TokenBucket(capacity=1200, refill_per_sec=20.0)
bybit_bucket = TokenBucket(capacity=1200, refill_per_sec=20.0)
