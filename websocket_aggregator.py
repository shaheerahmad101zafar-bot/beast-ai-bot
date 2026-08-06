"""
Multi-node websocket failover coordination.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class WebsocketAggregator:
    def __init__(self) -> None:
        self.primary: str | None = None
        self.secondary: str | None = None
        self.active: str | None = None
        self.last_frame_latency_ms: float = 0.0
        self.failovers = 0

    def configure(self, bases: list[str]) -> None:
        self.primary = bases[0] if bases else None
        self.secondary = bases[1] if len(bases) > 1 else self.primary
        self.active = self.active or self.primary

    def report_frame(self, latency_ms: float, base: str) -> bool:
        self.last_frame_latency_ms = round(float(latency_ms), 3)
        self.active = base
        if latency_ms > 50 and self.secondary and base == self.primary:
            self.active = self.secondary
            self.failovers += 1
            return True
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "primary": self.primary,
            "secondary": self.secondary,
            "active": self.active,
            "last_frame_latency_ms": self.last_frame_latency_ms,
            "failovers": self.failovers,
            "updated_at": _utc_now(),
        }


websocket_aggregator = WebsocketAggregator()
