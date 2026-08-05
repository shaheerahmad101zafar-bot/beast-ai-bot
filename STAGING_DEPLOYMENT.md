# Staging Deployment Guide — Beast AI (Render / Koyeb)

Free-cloud QA staging for the Phase 14 FastAPI app + background worker.

## What you get

| Piece | Role |
|---|---|
| **Web** | `uvicorn server:app --host 0.0.0.0 --port $PORT` — landing, `/app`, `/admin`, APIs, WebSockets |
| **Worker** | `python run_worker.py` — market scan loop + Telegram alerts |
| **Config** | `render.yaml`, `Procfile`, `runtime.txt`, cloud-aware `PORT` / CORS in `config.py` |

> Free-tier note: Render/Koyeb free workers may sleep or require a paid slot. For QA, keep `BOT_AUTO_START=true` on the **web** service so scanning still runs without a worker.

---

## 0) Prerequisites

1. GitHub account  
2. Render account ([https://render.com](https://render.com)) **or** Koyeb ([https://www.koyeb.com](https://www.koyeb.com))  
3. This project folder on your PC  

---

## 1) Push the repo to GitHub

In PowerShell (project root):

```powershell
cd C:\Users\ashah\Desktop\beast-ai-bot
git init
git add .
git commit -m "Prepare Phase 14 staging deploy for Render/Koyeb"
```

Create an empty GitHub repo (e.g. `beast-ai-bot`), then:

```powershell
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/beast-ai-bot.git
git push -u origin main
```

Do **not** commit `.env`, `beast_app.db`, `venv/`, or `backups/` (keep them gitignored).

---

## 2) Deploy on Render (recommended for free QA)

### Option A — Blueprint (fastest)

1. Open [https://dashboard.render.com](https://dashboard.render.com)  
2. **New** → **Blueprint**  
3. Connect the GitHub repo  
4. Render reads `render.yaml` and creates:
   - `beast-ai-web` (web)
   - `beast-ai-worker` (worker)  
5. Set secrets when prompted:
   - `ADMIN_PASSWORD` (strong password)
   - Optional: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, Stripe keys  
6. After first deploy, copy the public URL (e.g. `https://beast-ai-web.onrender.com`)  
7. In **Environment**, set:
   - `SITE_BASE_URL=https://beast-ai-web.onrender.com`
   - `CORS_ORIGINS=https://beast-ai-web.onrender.com`  
8. **Manual Deploy** → clear build cache / redeploy  

### Option B — Manual Web Service

1. **New** → **Web Service** → select repo  
2. Runtime: **Python 3**  
3. Build: `pip install -r requirements.txt`  
4. Start: `uvicorn server:app --host 0.0.0.0 --port $PORT`  
5. Health check path: `/api/health`  
6. Add env vars from section 4 below  
7. Optional: **New** → **Background Worker** with start `python run_worker.py`  

### Verify

- Landing: `https://YOUR-SERVICE.onrender.com/`  
- Health: `https://YOUR-SERVICE.onrender.com/api/health`  
- Admin: `https://YOUR-SERVICE.onrender.com/admin`  
  - Default email: `admin@example.com` (or your `ADMIN_EMAIL`)  
  - Password: whatever you set in `ADMIN_PASSWORD`  

Free web services **spin down** after idle time — first request can take 30–60s.

---

## 3) Deploy on Koyeb

1. [https://app.koyeb.com](https://app.koyeb.com) → **Create App** → **GitHub**  
2. Select `beast-ai-bot`  
3. Builder: **Buildpack** (or Docker if preferred)  
4. Run command (web):

```bash
uvicorn server:app --host 0.0.0.0 --port $PORT
```

5. Add env vars (section 4). Koyeb sets `PORT` automatically.  
6. Public URL looks like: `https://YOUR-APP-YOUR-ORG.koyeb.app`  
7. Set `SITE_BASE_URL` to that HTTPS URL and redeploy.  
8. Optional second service for worker:

```bash
python run_worker.py
```

`Procfile` is included for platforms that auto-detect `web` / `worker` process types.

---

## 4) Required environment variables

| Variable | Required | Example / notes |
|---|---|---|
| `JWT_SECRET` | Yes | Long random string (Render can auto-generate) |
| `ADMIN_EMAIL` | Yes | `admin@example.com` |
| `ADMIN_PASSWORD` | Yes | Strong password for QA admin |
| `SITE_BASE_URL` | Yes after first URL known | `https://beast-ai-web.onrender.com` |
| `OAUTH_GOOGLE_CLIENT_ID` | For live Google login | Google Cloud OAuth client ID |
| `OAUTH_GOOGLE_CLIENT_SECRET` | For live Google login | Google Cloud OAuth secret |
| `BINANCE_FUTURES_WS` | Optional | `wss://fstream.binance.com` (default) |
| `API_HOST` | Optional | Defaults to `0.0.0.0` in cloud |
| `PORT` | Auto | Injected by Render/Koyeb — do not hardcode |
| `BOT_AUTO_START` | Recommended `true` on web | Keeps scanner alive without worker |
| `CORS_ORIGINS` | Optional | Comma-separated exact origins |
| `CORS_ORIGIN_REGEX` | Optional | Defaults allow `*.onrender.com`, `*.koyeb.app`, etc. |
| `TELEGRAM_BOT_TOKEN` | Optional | Real alerts; mock mode if empty |
| `TELEGRAM_CHAT_ID` | Optional | |
| `STRIPE_*` / `NOWPAYMENTS_*` | Optional | Mock checkout without keys |

---

## 5) QA checklist after deploy

1. `/` loads landing + Sign Up modal  
2. `/api/health` returns `ok`  
3. Sign up with name/phone/address → redirects to `/app`  
4. Social buttons (Google/Apple/Facebook) complete demo OAuth on staging  
5. `/admin` login works; **User Database** + **User Movements** show events  
6. WebSocket desk updates (may be limited on free cold starts)  

---

## 6) Staging limits (expected)

- **SQLite** on free disks is ephemeral — redeploy/restart can wipe local DB (fine for QA)  
- Free web **sleeps** when idle  
- Separate free **worker** may not always stay online — use web `BOT_AUTO_START=true`  
- For production later: paid plan + persistent volume / Postgres + custom domain  

---

## Quick commands (local smoke before push)

```powershell
cd C:\Users\ashah\Desktop\beast-ai-bot
$env:PORT="8000"; $env:API_HOST="0.0.0.0"; $env:SITE_BASE_URL="http://127.0.0.1:8000"
.\venv\Scripts\python.exe -m uvicorn server:app --host 0.0.0.0 --port 8000
```

Health: http://127.0.0.1:8000/api/health
