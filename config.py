"""
Beast AI Trading Bot — Configuration
Enterprise multi-asset trading defaults and risk parameters.
"""

from __future__ import annotations

import os
from typing import Final

# ---------------------------------------------------------------------------
# Exchange / Market Defaults
# ---------------------------------------------------------------------------
EXCHANGE_ID: Final[str] = "binanceusdm"  # Binance USD-M Futures (CCXT id)
DEFAULT_TIMEFRAME: Final[str] = "1h"
DEFAULT_OHLCV_LIMIT: Final[int] = 250  # Enough bars for EMA(200) + buffer

# Default trading pairs (Binance Futures)
DEFAULT_TRADING_PAIRS: Final[list[str]] = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
]

# ---------------------------------------------------------------------------
# Risk Parameters
# ---------------------------------------------------------------------------
MAX_RISK_PER_TRADE: Final[float] = 0.015  # 1.5% of equity per trade
DEFAULT_STOP_LOSS: Final[float] = 0.010  # 1.0%
DEFAULT_TAKE_PROFIT: Final[float] = 0.020  # 2.0%

# ---------------------------------------------------------------------------
# Technical Indicator Parameters
# ---------------------------------------------------------------------------
RSI_PERIOD: Final[int] = 14
EMA_FAST: Final[int] = 20
EMA_MID: Final[int] = 50
EMA_SLOW: Final[int] = 200
ATR_PERIOD: Final[int] = 14
MACD_FAST: Final[int] = 12
MACD_SLOW: Final[int] = 26
MACD_SIGNAL: Final[int] = 9

# ---------------------------------------------------------------------------
# Execution / Paper Trading
# ---------------------------------------------------------------------------
EXECUTION_MODE: Final[str] = "PAPER_TRADING"  # PAPER_TRADING | LIVE_BINANCE
LOOP_INTERVAL_SECONDS: Final[int] = 10
MIN_SIGNAL_CONFIDENCE: Final[float] = 50.0
FUTURES_FEE_RATE: Final[float] = 0.0004  # 0.04% taker fee (per side)
DEFAULT_SLIPPAGE_BPS: Final[float] = 2.0  # 2 bps = 0.02%
PAPER_PORTFOLIO_PATH: Final[str] = "paper_portfolio.json"
TRADE_HISTORY_CSV: Final[str] = "trade_history.csv"
TRADE_HISTORY_JSON: Final[str] = "trade_history.json"

# ---------------------------------------------------------------------------
# Web Dashboard / API
# ---------------------------------------------------------------------------
# Cloud platforms (Render / Koyeb / Heroku-style) inject PORT; bind 0.0.0.0 there.
_IS_CLOUD: Final[bool] = bool(
    os.getenv("PORT")
    or os.getenv("RENDER")
    or os.getenv("RENDER_EXTERNAL_URL")
    or os.getenv("KOYEB_APP_ID")
    or os.getenv("KOYEB_APP_NAME")
)
API_HOST: Final[str] = os.getenv(
    "API_HOST",
    "0.0.0.0" if _IS_CLOUD else "127.0.0.1",
)
API_PORT: Final[int] = int(os.getenv("PORT") or os.getenv("API_PORT", "8000"))
DASHBOARD_DIR: Final[str] = "dashboard"
BOT_AUTO_START: Final[bool] = os.getenv("BOT_AUTO_START", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
STATUS_SCAN_CACHE_SECONDS: Final[int] = 3
WS_SNAPSHOT_INTERVAL: Final[float] = float(os.getenv("WS_SNAPSHOT_INTERVAL", "1.0"))
# Prefer fstream.binance.com — stream.binancefutures.com often fails DNS on cloud hosts.
BINANCE_FUTURES_WS: Final[str] = os.getenv(
    "BINANCE_FUTURES_WS",
    "wss://fstream.binance.com",
)

# ---------------------------------------------------------------------------
# SEO Content Engine
# ---------------------------------------------------------------------------
CONTENT_DIR: Final[str] = "content"
BLOG_DIR: Final[str] = "content/blogs"
SITEMAP_PATH: Final[str] = "content/sitemap.xml"
def _resolve_site_base_url() -> str:
    explicit = (os.getenv("SITE_BASE_URL") or "").strip()
    if explicit:
        return explicit.rstrip("/")
    render = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
    if render:
        return render.rstrip("/")
    koyeb = (os.getenv("KOYEB_PUBLIC_DOMAIN") or "").strip()
    if koyeb:
        if koyeb.startswith("http"):
            return koyeb.rstrip("/")
        return f"https://{koyeb}".rstrip("/")
    return "http://127.0.0.1:8000"


SITE_BASE_URL: Final[str] = _resolve_site_base_url()
SAAS_SUBSCRIPTION_URL: Final[str] = os.getenv(
    "SAAS_SUBSCRIPTION_URL",
    f"{SITE_BASE_URL}/#pricing",
)
SEO_BRAND_NAME: Final[str] = "Beast AI Trading Bot"

# ---------------------------------------------------------------------------
# Telegram Alerts
# ---------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN_ENV: Final[str] = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV: Final[str] = "TELEGRAM_CHAT_ID"
TELEGRAM_MOCK_LOG_PATH: Final[str] = "telegram_mock_outbox.json"
TELEGRAM_ENABLED: Final[bool] = True

# ---------------------------------------------------------------------------
# SaaS Billing / Payments
# ---------------------------------------------------------------------------
BILLING_STATE_PATH: Final[str] = "subscription_state.json"
STRIPE_SECRET_KEY_ENV: Final[str] = "STRIPE_SECRET_KEY"
STRIPE_WEBHOOK_SECRET_ENV: Final[str] = "STRIPE_WEBHOOK_SECRET"
STRIPE_PRICE_STARTER_ENV: Final[str] = "STRIPE_PRICE_STARTER"
STRIPE_PRICE_PRO_ENV: Final[str] = "STRIPE_PRICE_PRO"
STRIPE_PRICE_VIP_ENV: Final[str] = "STRIPE_PRICE_VIP"
NOWPAYMENTS_API_KEY_ENV: Final[str] = "NOWPAYMENTS_API_KEY"
NOWPAYMENTS_IPN_SECRET_ENV: Final[str] = "NOWPAYMENTS_IPN_SECRET"
DEFAULT_SUBSCRIPTION_TIER: Final[str] = "pro"
DEFAULT_SUBSCRIPTION_STATUS: Final[str] = "trialing"
TRIAL_DAYS: Final[int] = 7
PAYMENTS_MOCK_LOG: Final[str] = "payments_mock_log.json"

# ---------------------------------------------------------------------------
# Sentiment Engine
# ---------------------------------------------------------------------------
SENTIMENT_CACHE_SECONDS: Final[int] = 300  # 5 minutes
SENTIMENT_BUY_MIN: Final[float] = 40.0  # Block LONGs below this (fear filter)
SENTIMENT_SELL_MAX: Final[float] = 60.0  # Block SHORTs above this (greed filter)
CRYPTO_RSS_FEEDS: Final[list[str]] = [
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "https://cointelegraph.com/rss",
    "https://www.theblock.co/rss.xml",
    "https://bitcoinmagazine.com/.rss/full/",
]

# ---------------------------------------------------------------------------
# Exchange Vault & Copy Trading
# ---------------------------------------------------------------------------
VAULT_KEY_PATH: Final[str] = ".vault_key"
VAULT_STORE_PATH: Final[str] = "vault_store.enc"
COPY_LEDGER_PATH: Final[str] = "copy_trading_ledger.json"
COPY_PROFIT_SHARE_PCT: Final[float] = 0.15  # 15% master commission on follower profits
COPY_TRADING_LIVE_ORDERS: Final[bool] = False  # True = real CCXT follower orders
SUPPORTED_EXCHANGES: Final[dict[str, str]] = {
    "binance": "binanceusdm",
    "bybit": "bybit",
    "kucoin": "kucoinfutures",
    "okx": "okx",
}

# ---------------------------------------------------------------------------
# Auth / Database / Scanner
# ---------------------------------------------------------------------------
DATABASE_URL: Final[str] = "sqlite:///beast_app.db"
JWT_SECRET_ENV: Final[str] = "JWT_SECRET"
JWT_ALGORITHM: Final[str] = "HS256"
JWT_EXPIRE_HOURS: Final[int] = 72
AUTH_COOKIE_NAME: Final[str] = "beast_token"
ADMIN_EMAIL_ENV: Final[str] = "ADMIN_EMAIL"
ADMIN_PASSWORD_ENV: Final[str] = "ADMIN_PASSWORD"
DEFAULT_ADMIN_EMAIL: Final[str] = "admin@example.com"
DEFAULT_ADMIN_PASSWORD: Final[str] = "AdminPass123!"
CMS_CONTENT_PATH: Final[str] = "content/cms_content.json"

# ---------------------------------------------------------------------------
# Security / Backups (Phase 13)
# ---------------------------------------------------------------------------
CORS_ORIGINS: Final[str] = os.getenv("CORS_ORIGINS", "")
# Regex for free staging hosts (Render / Koyeb / Railway / Fly / Cloudflare tunnel)
CORS_ORIGIN_REGEX: Final[str] = os.getenv(
    "CORS_ORIGIN_REGEX",
    r"https://.*\.(onrender\.com|koyeb\.app|railway\.app|up\.railway\.app|fly\.dev|trycloudflare\.com)",
)
AUTH_RATE_LIMIT: Final[int] = int(os.getenv("AUTH_RATE_LIMIT", "8"))
AUTH_RATE_WINDOW_SECONDS: Final[int] = int(os.getenv("AUTH_RATE_WINDOW_SECONDS", "900"))
API_WRITE_RATE_LIMIT: Final[int] = int(os.getenv("API_WRITE_RATE_LIMIT", "120"))
API_WRITE_RATE_WINDOW_SECONDS: Final[int] = int(os.getenv("API_WRITE_RATE_WINDOW_SECONDS", "60"))
BACKUP_DIR: Final[str] = os.getenv("BACKUP_DIR", "backups")
BACKUP_RETAIN_COUNT: Final[int] = int(os.getenv("BACKUP_RETAIN_COUNT", "14"))
BACKUP_INTERVAL_SECONDS: Final[float] = float(os.getenv("BACKUP_INTERVAL_SECONDS", "86400"))
BACKUP_KEY_ENV: Final[str] = "BACKUP_KEY"
SCANNER_TOP_PAIRS: Final[int] = 120
SCANNER_GLOBAL_DEFAULT: Final[int] = 50
SCANNER_CACHE_SECONDS: Final[int] = 300
# Curated zero-latency seed size (see scanner.TOP_50_USDT_PAIRS)
SCANNER_SEED_PAIRS: Final[int] = 50
