"""
Beast AI Trading Bot — Phase 14 FastAPI Backend

Dynamic admin configurator, media landing, security, CMS, and trading plane.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from activity_tracker import list_activities, log_activity
from auth import (
    LoginRequest,
    SignupRequest,
    client_meta,
    create_access_token,
    authenticate_user,
    decode_token,
    ensure_same_user,
    get_current_user,
    get_db,
    google_oauth_callback,
    google_oauth_login_url,
    resolve_optional_user,
    signup_user,
    update_user_watchlist,
    user_to_public,
)
from admin_auth import (
    admin_user_public,
    build_admin_dashboard,
    ensure_bootstrap_admin,
    get_current_admin,
)
from oauth_auth import (
    PROVIDERS,
    complete_demo_oauth,
    complete_live_oauth_stub,
    providers_status,
    start_oauth,
)
from admin_settings import admin_settings
from arbitrage_scanner import arbitrage_scanner
from auth_validator import auth_validator
from backup_engine import backup_engine
from backtest import backtester
from billing import billing
from diagnostic_engine import diagnostic_engine
from hft_scalper import hft_scalper
from execution_ws import execution_ws
from genetic_tuner import genetic_tuner
from hedging_engine import hedging_engine
from liquidation_hunter import liquidation_hunter
from macro_guard import macro_guard
from multi_exchange_router import multi_exchange_router
from news_fetcher import news_fetcher
from quant_metrics import quant_metrics
from quantum_engine import quantum_engine
from system_health import system_health
from time_sync import time_sync
from bot_service import bot_service
from cms_engine import cms_engine
from copy_trader import copy_trader
from database import SessionLocal, User, UserApiKey, init_db
from security import secure_encrypt_api_secret as encrypt_api_secret
from market_scanner import market_scanner
from payments import payments
from security import configure_security, sanitize_cms_content
from seo_generator import seo_generator
from sentiment_engine import sentiment_engine
from system_health import collect_system_health
from telegram_bot import telegram_notifier
from vault import vault
from websocket_manager import binance_http_guard, ws_hub
from state_manager import state_manager


class ToggleRequest(BaseModel):
    enabled: bool | None = Field(
        default=None,
        description="Optional explicit state. If omitted, toggles current state.",
    )


class ExchangeConnectRequest(BaseModel):
    exchange: Literal["binance", "bybit", "kucoin", "okx"]
    api_key: str = Field(min_length=4)
    api_secret: str = Field(min_length=4)
    passphrase: str | None = None
    label: str = "Exchange Account"
    role: Literal["master", "follower"] = "follower"
    paper_mode: bool = Field(
        default=False,
        description="If true, skip live exchange validation (local demo / paper follower).",
    )
    equity_hint: float | None = Field(
        default=1000.0,
        description="Used for paper_mode sizing and as fallback equity.",
    )


class TelegramTestRequest(BaseModel):
    message: str | None = Field(
        default=None,
        description="Optional custom test message",
    )


class WatchlistRequest(BaseModel):
    symbols: list[str] = Field(default_factory=list)


class ScanRequest(BaseModel):
    mode: Literal["watchlist", "global"] = "watchlist"
    limit: int = Field(default=50, ge=1, le=120)
    symbols: list[str] | None = None


class CheckoutRequest(BaseModel):
    tier: Literal["starter", "pro", "vip"] = "pro"
    method: Literal["stripe", "crypto"] = "stripe"
    pay_currency: str = "usdttrc20"


class CMSUpdateRequest(BaseModel):
    content: dict[str, Any] = Field(default_factory=dict)


class BacktestRequest(BaseModel):
    symbol: str = "BTC/USDT"
    timeframe: str = "1h"
    days: int = Field(default=config.BACKTEST_LOOKBACK_DAYS, ge=7, le=90)
    starting_balance: float = Field(default=1000.0, ge=100.0, le=1_000_000.0)


class StressTestRequest(BaseModel):
    shocks: list[float] = Field(default_factory=lambda: [-5.0, -10.0, -20.0])


class AdminSettingsUpdateRequest(BaseModel):
    payments: dict[str, Any] | None = None
    social: dict[str, Any] | None = None


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=config.AUTH_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=config.JWT_EXPIRE_HOURS * 3600,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    ensure_bootstrap_admin()
    admin_settings.ensure_defaults()
    payments.reload_credentials()
    cms_engine.load()
    await asyncio.to_thread(seo_generator.generate_daily_article)
    await asyncio.to_thread(sentiment_engine.get_sentiment)
    await asyncio.to_thread(billing.refresh_status)
    try:
        # Instant seed universe first; live ranking refreshes below.
        await asyncio.to_thread(market_scanner.fetch_top_usdt_pairs, 50, False)
    except Exception:
        pass
    await ws_hub.start()
    await time_sync.start()
    await arbitrage_scanner.start()
    await genetic_tuner.start()
    await liquidation_hunter.start()
    await backup_engine.start()
    await system_health.start(bot_service.execution.save)
    await asyncio.to_thread(state_manager.hydrate, bot_service)
    await state_manager.start(bot_service)
    # Upgrade seeded top-50 pairs to live Binance volume ranking in background.
    try:
        await asyncio.to_thread(market_scanner.refresh_live_universe)
    except Exception:
        pass
    if config.BOT_AUTO_START:
        await asyncio.to_thread(bot_service.refresh_scan_once)
        await bot_service.start()
    yield
    await bot_service.stop()
    await state_manager.stop()
    await genetic_tuner.stop()
    await arbitrage_scanner.stop()
    await liquidation_hunter.stop()
    await backup_engine.stop()
    await system_health.stop()
    await time_sync.stop()
    await ws_hub.stop()
    bot_service.shutdown()
    market_scanner.close()


app = FastAPI(
    title="Beast AI Trading Bot API",
    version="14.0.0",
    description="Dynamic admin configurator, media landing, security, CMS, and trading plane",
    lifespan=lifespan,
)

from routes import router as institutional_router  # noqa: E402

app.include_router(institutional_router)
configure_security(app)

DASHBOARD_DIR = Path(__file__).resolve().parent / config.DASHBOARD_DIR
CONTENT_DIR = Path(__file__).resolve().parent / config.CONTENT_DIR

if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(DASHBOARD_DIR)), name="static")
if CONTENT_DIR.exists():
    app.mount("/content", StaticFiles(directory=str(CONTENT_DIR)), name="content")


@app.get("/")
async def landing() -> FileResponse:
    page = DASHBOARD_DIR / "landing.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Landing page missing")
    return FileResponse(page)


@app.get("/app")
async def app_dashboard(request: Request):
    index = DASHBOARD_DIR / "index.html"
    if not index.exists():
        raise HTTPException(status_code=404, detail="Dashboard missing")
    token = request.cookies.get(config.AUTH_COOKIE_NAME)
    if not token:
        return RedirectResponse(url="/?auth=login", status_code=302)
    try:
        decode_token(token)
    except HTTPException:
        return RedirectResponse(url="/?auth=login", status_code=302)
    return FileResponse(index)


@app.get("/app/terminal")
async def app_terminal(request: Request):
    page = DASHBOARD_DIR / "terminal.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Terminal missing")
    token = request.cookies.get(config.AUTH_COOKIE_NAME)
    if not token:
        return RedirectResponse(url="/?auth=login", status_code=302)
    try:
        decode_token(token)
    except HTTPException:
        return RedirectResponse(url="/?auth=login", status_code=302)
    return FileResponse(page)


@app.get("/pricing")
async def pricing_page() -> FileResponse:
    page = DASHBOARD_DIR / "pricing.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Pricing page missing")
    return FileResponse(page)


@app.get("/admin")
async def admin_page(request: Request):
    page = DASHBOARD_DIR / "admin.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="Admin panel missing")
    token = request.cookies.get(config.AUTH_COOKIE_NAME)
    if not token:
        return RedirectResponse(url="/?auth=login&next=/admin", status_code=302)
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub") or 0)
    except HTTPException:
        return RedirectResponse(url="/?auth=login&next=/admin", status_code=302)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user or not getattr(user, "is_admin", False):
            return RedirectResponse(url="/?auth=login&next=/admin&denied=1", status_code=302)
    finally:
        db.close()
    return FileResponse(page)


@app.get("/manifest.json")
async def pwa_manifest() -> FileResponse:
    path = DASHBOARD_DIR / "manifest.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="manifest.json missing")
    return FileResponse(path, media_type="application/manifest+json")


@app.get("/service-worker.js")
async def pwa_service_worker() -> FileResponse:
    path = DASHBOARD_DIR / "service-worker.js"
    if not path.exists():
        raise HTTPException(status_code=404, detail="service-worker.js missing")
    return FileResponse(
        path,
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache",
        },
    )


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "beast-ai-trading-bot",
        "version": "14.0.0",
        "pwa": {
            "manifest": "/manifest.json",
            "service_worker": "/service-worker.js",
        },
        "admin": "/admin",
        "security": {
            "rate_limit": True,
            "secure_headers": True,
            "cors_origins": True,
        },
        "backup": backup_engine.status(),
        "websocket": {
            "market_clients": ws_hub.manager.client_count("market"),
            "bot_clients": ws_hub.manager.client_count("bot-status"),
            "binance_connected": ws_hub.listener.connected,
            "binance_base": ws_hub.listener.active_base,
        },
    }


@app.get("/api/cms/public")
async def api_cms_public() -> dict[str, Any]:
    return {
        "ok": True,
        "content": cms_engine.get_public(),
        "site": admin_settings.get_public(),
    }


@app.get("/api/public/site-config")
async def api_public_site_config() -> dict[str, Any]:
    return {"ok": True, **admin_settings.get_public()}


@app.get("/api/admin/dashboard")
async def api_admin_dashboard(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    data = build_admin_dashboard(db)
    data["admin"] = admin_user_public(admin)
    return {"ok": True, **data}


@app.get("/api/admin/user-movements")
async def api_admin_user_movements(
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: int | None = Query(default=None),
) -> dict[str, Any]:
    rows = list_activities(db, limit=limit, user_id=user_id)
    return {
        "ok": True,
        "count": len(rows),
        "movements": rows,
        "admin": admin_user_public(admin),
    }


@app.get("/api/admin/content")
async def api_admin_content(admin: User = Depends(get_current_admin)) -> dict[str, Any]:
    return {"ok": True, "content": cms_engine.load(), "admin": admin_user_public(admin)}


@app.post("/api/admin/content/update")
async def api_admin_content_update(
    body: CMSUpdateRequest,
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    cleaned = sanitize_cms_content(body.content or {})
    saved = cms_engine.update(cleaned)
    return {"ok": True, "content": saved, "admin": admin_user_public(admin)}


@app.get("/api/admin/system-health")
async def api_admin_system_health(admin: User = Depends(get_current_admin)) -> dict[str, Any]:
    data = await asyncio.to_thread(collect_system_health)
    data["admin"] = admin_user_public(admin)
    return data


@app.post("/api/admin/backup/run")
async def api_admin_backup_run(admin: User = Depends(get_current_admin)) -> dict[str, Any]:
    try:
        manifest = await asyncio.to_thread(backup_engine.create_backup)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True, "backup": manifest, "admin": admin_user_public(admin)}


@app.get("/api/admin/settings")
async def api_admin_settings(admin: User = Depends(get_current_admin)) -> dict[str, Any]:
    return {
        "ok": True,
        "settings": admin_settings.get_all(mask_secrets=True),
        "admin": admin_user_public(admin),
    }


@app.post("/api/admin/settings/update")
async def api_admin_settings_update(
    body: AdminSettingsUpdateRequest,
    admin: User = Depends(get_current_admin),
) -> dict[str, Any]:
    patch: dict[str, Any] = {}
    if body.payments is not None:
        patch["payments"] = body.payments
    if body.social is not None:
        patch["social"] = body.social
    saved = admin_settings.update(patch)
    return {"ok": True, "settings": saved, "admin": admin_user_public(admin)}


@app.websocket("/ws/market")
async def ws_market(websocket: WebSocket) -> None:
    """Stream live market ticks, snapshots, positions, and activity logs."""
    await ws_hub.handle_market_socket(websocket)


@app.websocket("/ws/bot-status")
async def ws_bot_status(websocket: WebSocket) -> None:
    """Stream instant bot lifecycle and cycle notifications."""
    await ws_hub.handle_bot_status_socket(websocket)


@app.get("/api/market/ohlcv")
async def api_market_ohlcv(
    symbol: str = Query(default="BTC/USDT"),
    timeframe: str = Query(default=config.DEFAULT_TIMEFRAME),
    limit: int = Query(default=200, ge=20, le=500),
) -> dict[str, Any]:
    """Bootstrap candles for TradingView Lightweight Charts."""
    try:
        await binance_http_guard.acquire(weight=2, label=f"ohlcv:{symbol}:{timeframe}")
        df = await bot_service.market.fetch_ohlcv_async(symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    candles: list[dict[str, Any]] = []
    if df is not None and not df.empty:
        for ts, row in df.iterrows():
            # ts may be Timestamp
            try:
                t = int(ts.timestamp())
            except Exception:  # noqa: BLE001
                t = int(ts.value // 10**9) if hasattr(ts, "value") else int(ts)
            candles.append(
                {
                    "time": t,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row.get("volume") or 0),
                }
            )
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "count": len(candles),
        "candles": candles,
        "stream": {
            "binance_connected": ws_hub.listener.connected,
            "tick": ws_hub.ticks.get(symbol),
        },
    }


@app.post("/api/auth/signup")
async def api_auth_signup(
    body: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = signup_user(
        db,
        email=body.email,
        password=body.password,
        full_name=body.full_name,
        phone=body.phone,
        address=body.address,
        country=body.country,
    )
    try:
        billing.start_trial(tier="pro")
    except Exception:
        pass
    ip, ua = client_meta(request)
    log_activity(
        user_id=user.id,
        email=user.email,
        action="signup",
        detail=f"Email signup · {body.full_name} · {body.phone}",
        ip=ip,
        user_agent=ua,
        meta={"provider": "email"},
        db=db,
    )
    token = create_access_token(user.id, user.email)
    _set_auth_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_public(user),
    }


@app.post("/api/auth/login")
async def api_auth_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    user = authenticate_user(db, body.email, body.password)
    ip, ua = client_meta(request)
    log_activity(
        user_id=user.id,
        email=user.email,
        action="login",
        detail="Email/password login",
        ip=ip,
        user_agent=ua,
        meta={"provider": "email"},
        db=db,
    )
    token = create_access_token(user.id, user.email)
    _set_auth_cookie(response, token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": user_to_public(user),
    }


@app.get("/api/auth/me")
async def api_auth_me(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from datetime import datetime, timezone

    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()
    return {"user": user_to_public(user)}


@app.post("/api/auth/logout")
async def api_auth_logout(
    request: Request,
    response: Response,
) -> dict[str, Any]:
    user = resolve_optional_user(request)
    if user is not None:
        ip, ua = client_meta(request)
        log_activity(
            user_id=int(user.id),
            email=str(user.email),
            action="logout",
            detail="User logged out",
            ip=ip,
            user_agent=ua,
        )
    response.delete_cookie(config.AUTH_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/oauth/providers")
async def api_oauth_providers() -> dict[str, Any]:
    return {"ok": True, "providers": providers_status()}


@app.get("/api/auth/google/login")
async def api_google_login(
    next: str = Query(default="/app"),
) -> RedirectResponse:
    """Redirect browser to Google's OAuth consent screen."""
    next_path = next if next.startswith("/") else "/app"
    auth_url = google_oauth_login_url(next_path=next_path)
    return RedirectResponse(url=auth_url, status_code=302)


@app.get("/api/auth/google/callback")
async def api_google_callback(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    state: str = Query(default=""),
    code: str = Query(default=""),
    demo: int = Query(default=0),
    error: str = Query(default=""),
) -> RedirectResponse:
    """
    Google OAuth callback: verify ID token, upsert user, set JWT cookie,
    redirect signed-in users to /app (or next).
    """
    if error:
        raise HTTPException(status_code=400, detail=f"Google OAuth error: {error}")
    ip, ua = client_meta(request)
    result = google_oauth_callback(
        db,
        state=state,
        code=code,
        demo=bool(demo == 1),
        ip=ip,
        user_agent=ua,
    )
    token = result["token"]
    _set_auth_cookie(response, token)
    next_path = result.get("next") or "/app"
    if not str(next_path).startswith("/"):
        next_path = "/app"
    sep = "&" if "?" in next_path else "?"
    return RedirectResponse(
        url=f"{next_path}{sep}oauth_token={token}",
        status_code=302,
    )


@app.get("/api/auth/oauth/{provider}/start")
async def api_oauth_start(
    provider: str,
    next: str = Query(default="/app"),
) -> dict[str, Any]:
    if provider.lower() not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    # Dedicated Google flow prefers /api/auth/google/login
    if provider.lower() == "google":
        from oauth_auth import start_google_oauth

        return start_google_oauth(next_path=next or "/app")
    return start_oauth(provider, next_path=next or "/app")


@app.get("/api/auth/oauth/{provider}/callback")
@app.post("/api/auth/oauth/{provider}/callback")
async def api_oauth_callback(
    provider: str,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    state: str = Query(default=""),
    code: str = Query(default=""),
    demo: int = Query(default=0),
) -> RedirectResponse:
    if provider.lower() not in PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported provider")
    # Apple may POST form fields
    if request.method == "POST":
        form = await request.form()
        state = str(form.get("state") or state)
        code = str(form.get("code") or code)
    ip, ua = client_meta(request)
    if provider.lower() == "google":
        result = google_oauth_callback(
            db,
            state=state,
            code=code,
            demo=bool(demo == 1),
            ip=ip,
            user_agent=ua,
        )
    elif demo == 1:
        result = complete_demo_oauth(
            db, provider=provider.lower(), state=state, ip=ip, user_agent=ua
        )
    elif code:
        result = complete_live_oauth_stub(
            db,
            provider=provider.lower(),
            state=state,
            code=code,
            ip=ip,
            user_agent=ua,
        )
    else:
        raise HTTPException(status_code=400, detail="Missing OAuth code")
    token = result["token"]
    _set_auth_cookie(response, token)
    next_path = result.get("next") or "/app"
    # Pass token in hash-less query for SPA localStorage hydrate once
    sep = "&" if "?" in next_path else "?"
    return RedirectResponse(
        url=f"{next_path}{sep}oauth_token={token}",
        status_code=302,
    )


@app.get("/api/scanner/pairs")
async def api_scanner_pairs(
    limit: int = Query(default=100, ge=1, le=250),
    refresh: bool = Query(default=False),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    pairs = await asyncio.to_thread(market_scanner.fetch_top_usdt_pairs, limit, refresh)
    return {
        "count": len(pairs),
        "pairs": pairs,
        "user_id": user.id,
    }


@app.post("/api/scanner/scan")
async def api_scanner_scan(
    body: ScanRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    public = user_to_public(user)
    if body.mode == "global":
        result = await asyncio.to_thread(
            market_scanner.global_scan,
            body.limit,
            float(public.get("equity") or 1000.0),
        )
    else:
        symbols = body.symbols or public.get("watchlist") or list(config.DEFAULT_TRADING_PAIRS)
        result = await asyncio.to_thread(
            market_scanner.watchlist_scan,
            symbols,
            float(public.get("equity") or 1000.0),
        )
        # Keep bot loop aligned to active watchlist
        bot_service.set_active_pairs(list(symbols))
    return result


@app.put("/api/scanner/watchlist")
async def api_scanner_watchlist(
    body: WatchlistRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Re-bind user to this session
    db_user = db.get(User, user.id)
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    watchlist = update_user_watchlist(db, db_user, body.symbols)
    bot_service.set_active_pairs(watchlist)
    return {"ok": True, "watchlist": watchlist}


@app.get("/api/status")
async def api_status() -> dict[str, Any]:
    status = bot_service.get_status()
    if not status.get("markets"):
        await asyncio.to_thread(bot_service.refresh_scan_once)
        status = bot_service.get_status()
    return status


@app.get("/api/portfolio")
async def api_portfolio(user: User = Depends(get_current_user)) -> dict[str, Any]:
    portfolio = bot_service.get_portfolio()
    metrics = quant_metrics.compute(bot_service.get_trade_history(limit=500).get("trades") or [])
    return {"user_id": user.id, **portfolio, "quant_metrics": metrics}


@app.get("/api/trade-history")
async def api_trade_history(
    limit: int = Query(default=100, ge=1, le=1000),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"user_id": user.id, **bot_service.get_trade_history(limit=limit)}


@app.get("/api/wallet")
async def api_wallet(
    user_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_same_user(user_id, user)
    portfolio = bot_service.get_portfolio()
    return {
        "ok": True,
        "user_id": user.id,
        "wallet_balance": float(portfolio.get("wallet_balance") or 0.0),
        "available_balance": float(portfolio.get("available_balance") or 0.0),
        "equity": float(portfolio.get("equity") or 0.0),
        "mode": portfolio.get("mode"),
    }


@app.get("/api/trades")
async def api_trades(
    limit: int = Query(default=100, ge=1, le=1000),
    user_id: int | None = Query(default=None),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_same_user(user_id, user)
    history = bot_service.get_trade_history(limit=limit)
    return {"ok": True, "user_id": user.id, **history}


@app.post("/api/bot/toggle")
async def api_bot_toggle(body: ToggleRequest | None = None) -> dict[str, Any]:
    body = body or ToggleRequest()
    if body.enabled is None:
        result = await bot_service.toggle()
    elif body.enabled and not bot_service.running:
        result = await bot_service.start()
    elif not body.enabled and bot_service.running:
        result = await bot_service.stop()
    else:
        result = {
            "running": bot_service.running,
            "message": "Bot already in requested state",
        }

    status = bot_service.get_status()
    return {
        **result,
        "status": "LIVE" if result["running"] else "IDLE",
        "cycle": status.get("cycle"),
        "last_cycle_at": status.get("last_cycle_at"),
    }


@app.get("/api/sentiment")
async def api_sentiment(
    refresh: bool = Query(default=False, description="Force RSS refresh"),
) -> dict[str, Any]:
    snapshot = await asyncio.to_thread(sentiment_engine.get_sentiment, refresh)
    return snapshot


@app.get("/api/news/feed")
async def api_news_feed(
    limit: int = Query(default=25, ge=1, le=80),
) -> dict[str, Any]:
    return await asyncio.to_thread(sentiment_engine.get_news_feed, limit)


@app.get("/api/news/coin/{symbol}")
async def api_coin_news(
    symbol: str,
    limit: int = Query(default=12, ge=1, le=30),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"user_id": user.id, **(await asyncio.to_thread(news_fetcher.for_symbol, symbol, limit))}


@app.get("/api/quant/snapshot")
async def api_quant_snapshot(
    symbol: str = Query(default="BTC/USDT"),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    portfolio = bot_service.get_portfolio()
    equity = float(portfolio.get("equity") or 1000)
    quantum_engine.update_circuit_breaker(equity)
    return {
        "ok": True,
        "user_id": user.id,
        "quant": quantum_engine.snapshot(symbol),
        "hft": hft_scalper.get_status(),
        "hedging": hedging_engine.snapshot(),
        "arbitrage": arbitrage_scanner.snapshot(),
        "genetic_tuner": genetic_tuner.snapshot(),
        "execution_ws": execution_ws.status(),
        "multi_exchange_router": multi_exchange_router.status(),
        "macro_guard": macro_guard.snapshot(),
        "liquidation_hunter": liquidation_hunter.snapshot(),
        "system_health": system_health.snapshot(),
        "time_sync": time_sync.snapshot(),
    }


@app.get("/api/diagnostic/terminal")
async def api_diagnostic_terminal(
    limit: int = Query(default=40, ge=5, le=100),
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    return {"user_id": user.id, **(await asyncio.to_thread(diagnostic_engine.snapshot, limit))}


@app.get("/api/hft/status")
async def api_hft_status(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "user_id": user.id, **hft_scalper.get_status()}


@app.get("/api/arbitrage/snapshot")
async def api_arbitrage_snapshot(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "user_id": user.id, **arbitrage_scanner.snapshot()}


@app.get("/api/genetic-tuner/status")
async def api_genetic_tuner_status(user: User = Depends(get_current_user)) -> dict[str, Any]:
    return {"ok": True, "user_id": user.id, **genetic_tuner.snapshot()}


@app.post("/api/hft/toggle")
async def api_hft_toggle(
    body: ToggleRequest | None = None,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    enabled = True if body is None or body.enabled is None else bool(body.enabled)
    if hft_scalper.execution is None:
        hft_scalper.execution = bot_service.execution
    result = hft_scalper.set_enabled(enabled)
    return {"ok": True, "user_id": user.id, **result, **hft_scalper.get_status()}


@app.post("/api/desk/manual-order")
async def api_desk_manual_order(
    body: dict[str, Any],
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Manual Pro Order Desk — paper/live order with leverage + margin mode."""
    symbol = str(body.get("symbol") or "BTC/USDT").upper().replace("-", "/")
    if "/" not in symbol and symbol.endswith("USDT"):
        symbol = f"{symbol[:-4]}/USDT"
    side = str(body.get("side") or "BUY").upper()
    leverage = float(body.get("leverage") or 5)
    leverage = max(1.0, min(125.0, leverage))
    margin_mode = str(body.get("margin_mode") or "isolated").lower()
    notional = float(body.get("notional") or 50)
    price = float(body.get("price") or 0)
    ai_reasoning = str(body.get("ai_reasoning") or "Manual order from dashboard")
    if price <= 0:
        # best-effort mark from status
        status = bot_service.get_status()
        for m in status.get("markets") or []:
            if m.get("symbol") == symbol and m.get("price"):
                price = float(m["price"])
                break
    if price <= 0:
        raise HTTPException(status_code=400, detail="Mark price unavailable")
    size = notional / price
    # Liq price approx
    if side in {"BUY", "LONG"}:
        liq = price * (1 - 0.9 / leverage)
        sl = price * (1 - 0.01)
        tp = price * (1 + 0.02)
        signal = "BUY"
    else:
        liq = price * (1 + 0.9 / leverage)
        sl = price * (1 + 0.01)
        tp = price * (1 - 0.02)
        signal = "SELL"
    if not quantum_engine.trading_allowed():
        raise HTTPException(status_code=423, detail="Circuit breaker tripped — trading halted")
    result = bot_service.execution.place_order(
        symbol=symbol,
        signal=signal,
        size_units=size,
        leverage=leverage,
        market_price=price,
        stop_loss=sl,
        take_profit=tp,
        metadata={"ai_reasoning": ai_reasoning},
    )
    return {
        "ok": True,
        "user_id": user.id,
        "margin_mode": margin_mode,
        "leverage": leverage,
        "liquidation_price": round(liq, 6),
        "order": result,
    }


@app.get("/api/seo/blogs")
async def api_seo_blogs(
    limit: int = Query(default=20, ge=1, le=200),
    generate: bool = Query(default=False, description="Ensure today's article exists"),
) -> dict[str, Any]:
    if generate:
        await asyncio.to_thread(seo_generator.generate_daily_article)
    articles = seo_generator.list_articles(limit=limit)
    return {
        "count": len(articles),
        "sitemap": config.SITEMAP_PATH,
        "subscription_url": config.SAAS_SUBSCRIPTION_URL,
        "articles": articles,
    }


@app.post("/api/seo/generate")
async def api_seo_generate(force: bool = Query(default=False)) -> dict[str, Any]:
    article = await asyncio.to_thread(seo_generator.generate_daily_article, force)
    return {"ok": True, "article": article}


@app.post("/api/exchange/connect")
async def api_exchange_connect(
    body: ExchangeConnectRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        current = (
            db.query(UserApiKey)
            .filter(UserApiKey.user_id == user.id)
            .count()
        )
        billing.assert_can_connect_exchange(current)
        # Master/follower mapping is a Pro+ feature
        if body.role in {"master", "follower"}:
            billing.assert_can_use_copy_trading()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        validation = await asyncio.to_thread(
            vault.validate_connection,
            exchange=body.exchange,
            api_key=body.api_key,
            api_secret=body.api_secret,
            passphrase=body.passphrase,
            paper_mode=body.paper_mode,
            equity_hint=body.equity_hint,
        )
        await asyncio.to_thread(auth_validator.audit, validation)
    except (ValueError, PermissionError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    account = await asyncio.to_thread(
        vault.save_account,
        exchange=body.exchange,
        api_key=body.api_key,
        api_secret=body.api_secret,
        passphrase=body.passphrase,
        label=body.label,
        role=body.role,
        paper_mode=body.paper_mode,
        equity_hint=float(validation.get("equity") or body.equity_hint or 0.0),
        permissions=validation.get("permissions"),
    )
    account["equity"] = validation.get("equity")
    account["user_id"] = user.id
    db_key = (
        db.query(UserApiKey)
        .filter(UserApiKey.user_id == user.id, UserApiKey.exchange == body.exchange)
        .first()
    )
    if not db_key:
        db_key = UserApiKey(user_id=user.id, exchange=body.exchange)
        db.add(db_key)
    db_key.label = body.label
    db_key.role = body.role
    db_key.api_key_enc = encrypt_api_secret(body.api_key)
    db_key.api_secret_enc = encrypt_api_secret(body.api_secret)
    db_key.passphrase_enc = encrypt_api_secret(body.passphrase) if body.passphrase else None
    db.commit()
    account["validation"] = {
        "can_read": validation.get("can_read"),
        "can_trade": validation.get("can_trade"),
        "can_withdraw": validation.get("can_withdraw"),
        "message": validation.get("message"),
    }
    account["subscription"] = billing.get_status()
    return {"ok": True, "account": account}


@app.get("/api/exchange/accounts")
async def api_exchange_accounts(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    rows = db.query(UserApiKey).filter(UserApiKey.user_id == user.id).all()
    accounts = [
        {
            "id": row.id,
            "exchange": row.exchange,
            "label": row.label,
            "role": row.role,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "api_key_masked": "****",
        }
        for row in rows
    ]
    return {
        "user_id": user.id,
        "master": next((a for a in accounts if a.get("role") == "master"), None),
        "accounts": accounts,
        "supported_exchanges": list(config.SUPPORTED_EXCHANGES.keys()),
    }


@app.post("/api/backtest")
async def api_backtest(
    body: BacktestRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    result = await asyncio.to_thread(
        backtester.run,
        symbol=str(body.symbol or "BTC/USDT").upper().replace("-", "/"),
        timeframe=body.timeframe,
        days=body.days,
        starting_balance=body.starting_balance,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Backtest failed")
    return {"ok": True, "user_id": user.id, **result}


@app.get("/api/public-proof")
async def api_public_proof() -> dict[str, Any]:
    portfolio = bot_service.get_portfolio()
    history = bot_service.get_trade_history(limit=25).get("trades") or []
    redacted = [
        {
            "timestamp": t.get("timestamp"),
            "pair": t.get("pair"),
            "direction": t.get("direction"),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "pnl_usd": t.get("pnl_usd"),
            "exit_reason": t.get("exit_reason"),
        }
        for t in history
    ]
    return {
        "ok": True,
        "equity": float(portfolio.get("equity") or 0.0),
        "wallet_balance": float(portfolio.get("wallet_balance") or 0.0),
        "win_rate": float(portfolio.get("win_rate") or 0.0),
        "closed_trades": int(portfolio.get("closed_trades") or 0),
        "open_positions": int(portfolio.get("open_positions") or 0),
        "recent_trades": redacted,
        "quant_metrics": portfolio.get("quant_metrics") or {},
    }


@app.post("/api/simulate-stress")
async def api_simulate_stress(
    body: StressTestRequest | None = None,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    payload = body or StressTestRequest()
    portfolio = bot_service.get_portfolio()
    positions = portfolio.get("positions") or []
    shocks = [float(s) for s in (payload.shocks or [-5.0, -10.0, -20.0])]
    scenarios: list[dict[str, Any]] = []
    for shock in shocks:
        shocked_positions: list[dict[str, Any]] = []
        total = 0.0
        liquidations = 0
        for pos in positions:
            entry = float(pos.get("entry_price") or 0.0)
            size = float(pos.get("size") or 0.0)
            direction = str(pos.get("direction") or "LONG").upper()
            liq = float(pos.get("liquidation_price") or pos.get("stop_loss") or 0.0)
            stressed = entry * (1 + shock / 100.0)
            pnl = (stressed - entry) * size if direction == "LONG" else (entry - stressed) * size
            vuln = liq > 0 and ((direction == "LONG" and stressed <= liq) or (direction == "SHORT" and stressed >= liq))
            liquidations += 1 if vuln else 0
            total += pnl
            shocked_positions.append(
                {
                    "symbol": pos.get("symbol"),
                    "direction": direction,
                    "stressed_price": round(stressed, 6),
                    "projected_pnl_usd": round(pnl, 4),
                    "liquidation_risk": vuln,
                    "ai_reasoning": pos.get("ai_reasoning") or "",
                }
            )
        recommendations = []
        if liquidations:
            recommendations.append("Reduce leverage or cut weakest positions before macro selloffs.")
        if total < -250:
            recommendations.append("Move to demo mode and tighten auto-pilot until volatility normalizes.")
        if not recommendations:
            recommendations.append("Portfolio remains resilient under this shock profile.")
        scenarios.append(
            {
                "shock_pct": shock,
                "projected_total_pnl_usd": round(total, 4),
                "liquidation_vulnerabilities": liquidations,
                "positions": shocked_positions,
                "recommendations": recommendations,
            }
        )
    return {"ok": True, "user_id": user.id, "position_count": len(positions), "scenarios": scenarios}


@app.get("/api/copy-trading/followers")
async def api_copy_trading_followers() -> dict[str, Any]:
    try:
        billing.assert_can_use_copy_trading()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    summary = copy_trader.leaderboard_summary()
    summary["subscription"] = billing.get_status()
    return summary


@app.get("/api/pricing")
async def api_pricing() -> dict[str, Any]:
    data = billing.list_pricing()
    data["payments"] = payments.status()
    return data


@app.get("/api/subscription/status")
async def api_subscription_status(
    request: Request,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    # Prefer per-user subscription when authenticated
    user = resolve_optional_user(request)
    global_status = billing.refresh_status()
    if user:
        # Reload in this session
        db_user = db.get(User, user.id)
        if db_user:
            return {
                **global_status,
                "user": user_to_public(db_user),
                "source": "user",
            }
    return {**global_status, "source": "global"}


@app.post("/api/telegram/test")
async def api_telegram_test(body: TelegramTestRequest | None = None) -> dict[str, Any]:
    body = body or TelegramTestRequest()
    priority = billing.telegram_priority()
    prefix = "⚡ PRIORITY " if priority else ""
    message = body.message or (
        f"{prefix}Beast AI Telegram link test — mock/live dispatcher online."
    )
    result = await asyncio.to_thread(telegram_notifier.send_message, message)
    return {
        "ok": bool(result.get("ok")),
        "notifier": telegram_notifier.status(),
        "priority_telegram": priority,
        "result": result,
    }


@app.post("/api/payments/create-checkout-session")
async def api_create_checkout(
    body: CheckoutRequest,
    user: User = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        session = await asyncio.to_thread(
            payments.create_checkout_session,
            user=user,
            tier=body.tier,
            method=body.method,
            pay_currency=body.pay_currency,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **session}


@app.post("/api/payments/customer-portal")
async def api_customer_portal(user: User = Depends(get_current_user)) -> dict[str, Any]:
    try:
        portal = await asyncio.to_thread(payments.create_customer_portal, user)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **portal}


@app.get("/api/payments/status")
async def api_payments_status() -> dict[str, Any]:
    return payments.status()


@app.get("/api/payments/mock-complete")
async def api_payments_mock_complete(
    provider: Literal["stripe", "crypto"] = "stripe",
    tier: Literal["starter", "pro", "vip"] = "pro",
    user_id: int = Query(...),
    session_id: str | None = None,
    order_id: str | None = None,
    db: Session = Depends(get_db),
):
    """Local mock success URL used when Stripe/NOWPayments keys are unset."""
    try:
        result = payments.activate_subscription(
            db,
            user_id=user_id,
            tier=tier,
            provider=provider,
            status="active",
            stripe_subscription_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        url=f"/app?tab=billing&billing=success&tier={tier}&provider={provider}",
        status_code=302,
    )


@app.post("/api/payments/stripe-webhook")
async def api_stripe_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    try:
        event = payments.construct_stripe_event(payload, sig)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook: {exc}") from exc

    # stripe Event object or dict
    event_type = event["type"] if isinstance(event, dict) else event.type
    data_object = (
        event["data"]["object"] if isinstance(event, dict) else event.data.object
    )

    if event_type == "checkout.session.completed":
        metadata = data_object.get("metadata") or {}
        user_id = metadata.get("user_id") or data_object.get("client_reference_id")
        tier = metadata.get("tier") or "pro"
        if user_id:
            payments.activate_subscription(
                db,
                user_id=int(user_id),
                tier=str(tier),
                provider="stripe",
                status="active",
                stripe_customer_id=data_object.get("customer"),
                stripe_subscription_id=data_object.get("subscription"),
            )
        return {"ok": True, "handled": event_type}

    if event_type == "customer.subscription.deleted":
        metadata = data_object.get("metadata") or {}
        user_id = metadata.get("user_id")
        customer_email = None
        if user_id:
            payments.cancel_subscription(db, user_id=int(user_id))
        else:
            # Best-effort: leave global canceled if no mapping
            billing.set_tier(billing.get_status().get("tier", "pro"), status="canceled")
        return {"ok": True, "handled": event_type, "email": customer_email}

    return {"ok": True, "handled": False, "type": event_type}


@app.post("/api/payments/crypto-webhook")
async def api_crypto_webhook(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = await request.json()
    signature = request.headers.get("x-nowpayments-sig")
    if not payments.verify_nowpayments_ipn(payload, signature):
        raise HTTPException(status_code=401, detail="Invalid NOWPayments signature")

    status = str(payload.get("payment_status") or payload.get("status") or "").lower()
    order_id = str(payload.get("order_id") or "")
    # order_id format: beast_{user_id}_{tier}_{rand}
    parts = order_id.split("_")
    user_id = None
    tier = "pro"
    if len(parts) >= 3 and parts[0] == "beast":
        try:
            user_id = int(parts[1])
            tier = parts[2]
        except ValueError:
            user_id = None

    if status in {"finished", "confirmed", "paid", "completed"} and user_id:
        payments.activate_subscription(
            db,
            user_id=user_id,
            tier=tier if tier in {"starter", "pro", "vip"} else "pro",
            provider="crypto",
            status="active",
        )
        return {"ok": True, "activated": True, "user_id": user_id, "tier": tier}

    return {"ok": True, "activated": False, "status": status}
