"""
Beast AI Trading Bot — Phase 4 Application Launcher

Starts the FastAPI server (strategy background loop + web dashboard)
on http://localhost:8000.
"""

from __future__ import annotations

import webbrowser
from threading import Timer

import uvicorn

import config


def _open_browser() -> None:
    url = f"http://{config.API_HOST}:{config.API_PORT}"
    try:
        webbrowser.open(url)
    except Exception:
        pass


if __name__ == "__main__":
    host = config.API_HOST
    port = config.API_PORT
    print("=" * 64)
    print("  Beast AI Trading Bot - Phase 14 Launcher")
    print(f"  Landing   : http://{host}:{port}/")
    print(f"  Pricing   : http://{host}:{port}/pricing")
    print(f"  App       : http://{host}:{port}/app")
    print(f"  Admin     : http://{host}:{port}/admin")
    print(f"  Settings  : http://{host}:{port}/api/admin/settings")
    print(f"  Site CFG  : http://{host}:{port}/api/public/site-config")
    print(f"  Health    : http://{host}:{port}/api/admin/system-health")
    print(f"  PWA       : http://{host}:{port}/manifest.json")
    print(f"  WS Market : ws://{host}:{port}/ws/market")
    print(f"  WS Bot    : ws://{host}:{port}/ws/bot-status")
    print(f"  API Docs  : http://{host}:{port}/docs")
    print(f"  Mode      : {config.EXECUTION_MODE}")
    print(f"  AutoStart : {config.BOT_AUTO_START}")
    print(f"  Site URL  : {config.SITE_BASE_URL}")
    print("=" * 64)

    # Open browser only for local desktop launches (skip cloud / PORT-bound hosts)
    if not getattr(config, "_IS_CLOUD", False) and host in {"127.0.0.1", "localhost"}:
        Timer(1.5, _open_browser).start()

    uvicorn.run(
        "server:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
