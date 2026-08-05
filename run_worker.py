"""
Beast AI Trading Bot — Phase 11 Background Worker

Runs the trading scan loop, SEO/sentiment warmup, and Telegram alerts
without binding the HTTP/WebSocket API (used by docker beast_worker).
"""

from __future__ import annotations

import asyncio
import signal

import config
from bot_service import bot_service
from database import init_db
from seo_generator import seo_generator
from sentiment_engine import sentiment_engine
from telegram_bot import telegram_notifier


async def _main() -> None:
    print("=" * 64)
    print("  Beast AI Trading Bot - Phase 11 Worker")
    print(f"  Mode      : {config.EXECUTION_MODE}")
    print(f"  Interval  : {config.LOOP_INTERVAL_SECONDS}s")
    print(f"  Telegram  : {telegram_notifier.status().get('mode', 'unknown')}")
    print("=" * 64)

    init_db()
    await asyncio.to_thread(seo_generator.generate_daily_article)
    await asyncio.to_thread(sentiment_engine.get_sentiment)
    await asyncio.to_thread(bot_service.refresh_scan_once)
    await bot_service.start()

    stop = asyncio.Event()

    def _signal_handler(*_args) -> None:
        stop.set()

    try:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _signal_handler)
            except (NotImplementedError, RuntimeError):
                # Windows: signal handlers limited
                signal.signal(sig, lambda *_: stop.set())
    except Exception:
        pass

    await stop.wait()
    await bot_service.stop()
    bot_service.shutdown()
    print("Worker stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
