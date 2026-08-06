(() => {
  const SLOW_REFRESH_MS = 20000; // SEO / sentiment / copy only
  const TOKEN_KEY = "beast_jwt";
  // Zero-latency top-50 seed (mirrors backend scanner.TOP_50_USDT_PAIRS)
  const SEED_TOP_50 = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
    "ADA/USDT", "BNB/USDT", "AVAX/USDT", "LINK/USDT", "MATIC/USDT",
    "DOT/USDT", "NEAR/USDT", "SHIB/USDT", "PEPE/USDT", "SUI/USDT",
    "APT/USDT", "FET/USDT", "ARB/USDT", "OP/USDT", "UNI/USDT",
    "ATOM/USDT", "LTC/USDT", "TRX/USDT", "TON/USDT", "INJ/USDT",
    "RENDER/USDT", "FIL/USDT", "AAVE/USDT", "MKR/USDT", "CRV/USDT",
    "WLD/USDT", "SEI/USDT", "TIA/USDT", "ORDI/USDT", "WIF/USDT",
    "BONK/USDT", "FLOKI/USDT", "ICP/USDT", "HBAR/USDT", "ALGO/USDT",
    "VET/USDT", "GRT/USDT", "STX/USDT", "IMX/USDT", "RUNE/USDT",
    "ENS/USDT", "LDO/USDT", "PYTH/USDT", "JUP/USDT", "ONDO/USDT",
  ];
  let toggling = false;
  let watchlist = ["BTC/USDT", "ETH/USDT", "SOL/USDT"];
  let universe = SEED_TOP_50.map((symbol, i) => ({
    symbol,
    base: symbol.split("/")[0],
    quote: "USDT",
    quote_volume: 50_000_000 - i * 100_000,
    last: 0,
    info_type: "seed",
  }));
  let currentUser = null;
  let chartEngine = null;
  let tvEngine = null;
  let beastEngine = null;
  const parseWorker =
    typeof Worker !== "undefined" ? new Worker("/static/js/chart-worker.js") : null;
  const workerResolvers = new Map();
  let workerSeq = 0;
  let chartEngineMode = localStorage.getItem("beast_chart_engine") || "beast";
  let deskMode = "auto";
  let marginMode = "isolated";
  let uiMode = localStorage.getItem("beast_ui_mode") || "simple";
  let sandboxMode = localStorage.getItem("beast_sandbox_mode") || "demo";
  let hftEnabled = false;
  let chartCandles = [];
  let chartSymbol = "BTC/USDT";
  let lastMarkets = [];
  let lastPositions = [];
  let knownPositionKeys = new Set();
  let lastBookImbalance = null;
  let marketWs = null;
  let botWs = null;
  let wsRetryMs = 1000;
  let pingLoop = null;
  let lastPingSentAt = 0;
  let lastWsPingMs = null;

  const els = {
    statusDot: document.getElementById("status-dot"),
    statusLabel: document.getElementById("bot-status-label"),
    toggle: document.getElementById("bot-toggle"),
    toggleText: document.getElementById("toggle-text"),
    equity: document.getElementById("stat-equity"),
    wallet: document.getElementById("stat-wallet"),
    active: document.getElementById("stat-active"),
    dailyPnl: document.getElementById("stat-daily-pnl"),
    realized: document.getElementById("stat-realized"),
    winrate: document.getElementById("stat-winrate"),
    closed: document.getElementById("stat-closed"),
    scannerBody: document.getElementById("scanner-body"),
    positionsBody: document.getElementById("positions-body"),
    historyBody: document.getElementById("history-body"),
    scanMeta: document.getElementById("scan-meta"),
    posMeta: document.getElementById("pos-meta"),
    historyMeta: document.getElementById("history-meta"),
    footerClock: document.getElementById("footer-clock"),
    sentimentScore: document.getElementById("sentiment-score"),
    sentimentLabel: document.getElementById("sentiment-label"),
    sentimentMeta: document.getElementById("sentiment-meta"),
    sentHeadlines: document.getElementById("sent-headlines"),
    sentBull: document.getElementById("sent-bull"),
    sentBear: document.getElementById("sent-bear"),
    headlineList: document.getElementById("headline-list"),
    gaugeValue: document.getElementById("gauge-value"),
    seoMeta: document.getElementById("seo-meta"),
    seoFeed: document.getElementById("seo-feed"),
    copyMeta: document.getElementById("copy-meta"),
    copyFollowers: document.getElementById("copy-followers"),
    copyCommission: document.getElementById("copy-commission"),
    copyFollowerPnl: document.getElementById("copy-follower-pnl"),
    copyMasterLine: document.getElementById("copy-master-line"),
    copyBody: document.getElementById("copy-body"),
    connectModal: document.getElementById("connect-modal"),
    connectForm: document.getElementById("connect-form"),
    connectError: document.getElementById("connect-error"),
    connectSuccess: document.getElementById("connect-success"),
    connectSubmit: document.getElementById("connect-submit"),
    btnConnect: document.getElementById("btn-connect-exchange"),
    userChip: document.getElementById("user-chip"),
    btnLogout: document.getElementById("btn-logout"),
    pairSearch: document.getElementById("pair-search"),
    pairSelect: document.getElementById("pair-select"),
    btnAddPair: document.getElementById("btn-add-pair"),
    watchChips: document.getElementById("watch-chips"),
    watchMeta: document.getElementById("watch-meta"),
    btnScanWatch: document.getElementById("btn-scan-watchlist"),
    btnScanGlobal: document.getElementById("btn-scan-global"),
    billingMeta: document.getElementById("billing-meta"),
    billingBanner: document.getElementById("billing-banner"),
    billPlan: document.getElementById("bill-plan"),
    billStatus: document.getElementById("bill-status"),
    billProvider: document.getElementById("bill-provider"),
    billExpires: document.getElementById("bill-expires"),
    billEmail: document.getElementById("bill-email"),
    billPayMode: document.getElementById("bill-pay-mode"),
    btnManageBilling: document.getElementById("btn-manage-billing"),
    btnRefreshBilling: document.getElementById("btn-refresh-billing"),
    btnCopilot: document.getElementById("btn-copilot"),
    chartSymbol: document.getElementById("chart-symbol"),
    chartMeta: document.getElementById("chart-meta"),
    wsStatus: document.getElementById("ws-status"),
    wsLatency: document.getElementById("ws-latency"),
    activityFeed: document.getElementById("activity-feed"),
    qLiq: document.getElementById("q-liq"),
    qObi: document.getElementById("q-obi"),
    qFeed: document.getElementById("q-feed"),
    backtestChart: document.getElementById("backtest-chart"),
    backtestMeta: document.getElementById("backtest-meta"),
    backtestSymbol: document.getElementById("backtest-symbol"),
    backtestTimeframe: document.getElementById("backtest-timeframe"),
    backtestDays: document.getElementById("backtest-days"),
    btnRunBacktest: document.getElementById("btn-run-backtest"),
    backtestMsg: document.getElementById("backtest-msg"),
    btWinrate: document.getElementById("bt-winrate"),
    btDrawdown: document.getElementById("bt-drawdown"),
    btPnl: document.getElementById("bt-pnl"),
    btTrades: document.getElementById("bt-trades"),
    leaderWinrate: document.getElementById("leader-winrate"),
    leaderProfitFactor: document.getElementById("leader-profit-factor"),
    leaderDrawdown: document.getElementById("leader-drawdown"),
    leaderSymbol: document.getElementById("leader-symbol"),
    btnStressTest: document.getElementById("btn-stress-test"),
    btnExportCsv: document.getElementById("btn-export-csv"),
    btnExportPdf: document.getElementById("btn-export-pdf"),
    stressMsg: document.getElementById("stress-msg"),
    stressResults: document.getElementById("stress-results"),
    copilotModal: document.getElementById("copilot-modal"),
    copilotInput: document.getElementById("copilot-input"),
    copilotPreview: document.getElementById("copilot-preview"),
    btnCopilotRun: document.getElementById("btn-copilot-run"),
    qmSharpe: document.getElementById("qm-sharpe"),
    qmSortino: document.getElementById("qm-sortino"),
    qmVar: document.getElementById("qm-var"),
  };

  if (parseWorker) {
    parseWorker.onmessage = (event) => {
      const msg = event.data || {};
      const key = Number(msg.id || 0);
      const resolver = workerResolvers.get(key);
      if (resolver) {
        workerResolvers.delete(key);
        resolver(msg.payload);
      }
    };
  }

  function wsUrl(path) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}${path}`;
  }

  function setWsPill(state, text) {
    if (!els.wsStatus) return;
    els.wsStatus.classList.remove("live", "idle", "down");
    els.wsStatus.classList.add(state);
    els.wsStatus.textContent = text;
  }

  function applyUiMode(mode) {
    uiMode = mode === "pro" ? "pro" : "simple";
    localStorage.setItem("beast_ui_mode", uiMode);
    document.body.dataset.uiMode = uiMode;
    document.querySelectorAll("[data-ui-mode]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.uiMode === uiMode);
      btn.classList.toggle("secondary", btn.dataset.uiMode !== uiMode);
    });
    if (uiMode === "simple") {
      switchTab("trading");
      deskMode = "auto";
      document.getElementById("manual-desk")?.classList.add("hidden");
      if (els.backtestMeta) {
        els.backtestMeta.textContent = "Compact trading view · verified card stays visible";
      }
    }
  }

  function applySandboxMode(mode) {
    sandboxMode = mode === "live" ? "live" : "demo";
    localStorage.setItem("beast_sandbox_mode", sandboxMode);
    document.querySelectorAll("[data-sandbox-mode]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.sandboxMode === sandboxMode);
      btn.classList.toggle("secondary", btn.dataset.sandboxMode !== sandboxMode);
    });
    if (els.watchMeta) {
      els.watchMeta.textContent =
        sandboxMode === "demo"
          ? "Risk-free $10,000 sandbox ready"
          : "Live mode armed - connect exchange before real routing";
    }
  }

  function parseWsPayload(raw) {
    if (!parseWorker) {
      try {
        return Promise.resolve(JSON.parse(raw));
      } catch (_) {
        return Promise.resolve(null);
      }
    }
    const id = ++workerSeq;
    return new Promise((resolve) => {
      workerResolvers.set(id, resolve);
      parseWorker.postMessage({ id, type: "parse_ws", raw });
    });
  }

  function renderReasonAccordion(reason) {
    const text = String(reason || "").trim();
    if (!text) return "";
    return `<details class="reason-accordion"><summary>Why AI entered this trade?</summary><p>${text}</p></details>`;
  }

  function aiReasonBadge(reason) {
    const text = String(reason || "").trim();
    if (!text) return `<span class="ai-reason-badge muted">—</span>`;
    const short = text.length > 64 ? `${text.slice(0, 61)}…` : text;
    return `<span class="ai-reason-badge" title="${text.replace(/"/g, "&quot;")}">${short}</span>${renderReasonAccordion(
      text
    )}`;
  }

  async function downloadExport(path, filename) {
    const token = localStorage.getItem("beast_token") || "";
    const res = await fetch(path, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
      credentials: "include",
    });
    if (!res.ok) throw new Error(`Export failed (${res.status})`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  function renderActivity(rows) {
    if (!els.activityFeed) return;
    const list = (rows || []).slice(-8).reverse();
    els.activityFeed.innerHTML = list.length
      ? list
          .map(
            (r) =>
              `<div class="act-row ${r.level || ""}"><span>${r.ts || ""}</span><span>${
                r.message || ""
              }</span></div>`
          )
          .join("")
      : `<div class="act-row">Awaiting stream activity…</div>`;
  }

  function populateChartSymbols(pairs) {
    if (!els.chartSymbol) return;
    const merged = [];
    const seen = new Set();
    for (const s of [...(pairs || []), ...SEED_TOP_50, ...watchlist]) {
      const sym = normalizeSymbol(s);
      if (!sym || seen.has(sym)) continue;
      seen.add(sym);
      merged.push(sym);
    }
    const opts = merged.length ? merged : watchlist;
    els.chartSymbol.innerHTML = opts
      .map((s) => `<option value="${s}" ${s === chartSymbol ? "selected" : ""}>${s}</option>`)
      .join("");
  }

  function selectChartSymbol(symbol) {
    const sym = normalizeSymbol(symbol);
    if (!sym) return;
    chartSymbol = sym;
    if (els.chartSymbol) {
      const has = [...els.chartSymbol.options].some((o) => o.value === sym);
      if (!has) {
        const opt = document.createElement("option");
        opt.value = sym;
        opt.textContent = sym;
        els.chartSymbol.appendChild(opt);
      }
      els.chartSymbol.value = sym;
    }
    loadChart(sym);
  }

  async function loadChart(symbol) {
    chartSymbol = symbol || chartSymbol;
    if (chartEngine) chartEngine.setSymbol(chartSymbol);
    const tv =
      (window.BeastCharts && window.BeastCharts.toTradingViewSymbol
        ? window.BeastCharts.toTradingViewSymbol(chartSymbol)
        : null) || `BINANCE:${String(chartSymbol).replace("/", "")}`;
    if (els.chartMeta) {
      els.chartMeta.textContent = `${chartSymbol} · ${
        chartEngineMode === "beast" ? "Beast Native" : tv
      }`;
    }
    try {
      const data = await fetchJson(
        `/api/market/ohlcv?symbol=${encodeURIComponent(chartSymbol)}&timeframe=1h&limit=200`
      );
      chartCandles = data.candles || [];
      if (chartEngine) {
        chartEngine.loadCandles?.(chartCandles);
        const markers = window.BeastCharts?.buildSignalMarkers?.(
          chartCandles,
          lastMarkets,
          chartSymbol
        );
        chartEngine.setMarkers?.(markers);
        const market = lastMarkets.find((m) => m.symbol === chartSymbol);
        const pos = lastPositions.find((p) => p.symbol === chartSymbol);
        chartEngine.applyMarketRow?.(market, pos);
      }
      if (els.chartMeta && chartCandles.length) {
        els.chartMeta.textContent = `${chartSymbol} · ${
          chartEngineMode === "beast" ? "Beast Native" : tv
        } · ${chartCandles.length} bars`;
      }
    } catch (_) {
      /* chart engines remain primary */
    }
  }

  function setChartEngine(mode) {
    chartEngineMode = mode === "tradingview" ? "tradingview" : "beast";
    localStorage.setItem("beast_chart_engine", chartEngineMode);
    const beastEl = document.getElementById("beast-chart");
    const tvEl = document.getElementById("tv-chart");
    document.querySelectorAll("[data-chart-engine]").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.chartEngine === chartEngineMode);
    });
    if (chartEngineMode === "beast") {
      beastEl?.classList.remove("hidden");
      tvEl?.classList.add("hidden");
      if (!beastEngine && window.BeastNativeChart) {
        beastEngine = window.BeastNativeChart.createBeastChart("beast-chart");
      }
      chartEngine = beastEngine;
    } else {
      tvEl?.classList.remove("hidden");
      beastEl?.classList.add("hidden");
      if (!tvEngine && window.BeastCharts) {
        tvEngine = window.BeastCharts.createChartEngine("tv-chart");
      }
      chartEngine = tvEngine;
    }
    if (chartEngine) chartEngine.setSymbol?.(chartSymbol);
    loadChart(chartSymbol);
  }

  function syncChartFromSnapshot(msg) {
    lastMarkets = msg.markets || lastMarkets;
    lastPositions = msg.positions || msg.portfolio?.positions || lastPositions;
    const market = lastMarkets.find((m) => m.symbol === chartSymbol);
    const pos = lastPositions.find((p) => p.symbol === chartSymbol);
    if (chartEngine) {
      const markers = window.BeastCharts.buildSignalMarkers(
        chartCandles,
        lastMarkets,
        chartSymbol
      );
      chartEngine.setMarkers(markers);
      chartEngine.applyMarketRow(market, pos);
    }
    // Detect new fills for flash animation
    const nextKeys = new Set(
      lastPositions.map((p) => `${p.symbol}:${p.direction}:${p.entry_price}`)
    );
    nextKeys.forEach((key) => {
      if (!knownPositionKeys.has(key) && chartEngine) {
        const [sym, dir] = key.split(":");
        if (sym === chartSymbol) {
          chartEngine.flashExecution(dir, `${dir} OPEN`);
        }
      }
    });
    knownPositionKeys = nextKeys;
  }

  function applySnapshot(msg) {
    if (!toggling && typeof msg.bot_running === "boolean") setBotUi(msg.bot_running);
    if (msg.portfolio) {
      renderStats(msg.portfolio);
      renderPositions(msg.portfolio);
    } else if (msg.positions) {
      renderPositions({ positions: msg.positions });
    }
    if (msg.markets) renderScanner(msg);
    if (msg.history) renderHistory(msg.history);
    if (msg.activity) renderActivity(msg.activity);
    syncChartFromSnapshot(msg);
    const stream = msg.stream || {};
    const live = !!stream.binance_connected;
    setWsPill(
      live ? "live" : "idle",
      live ? `WS live · ${stream.binance_base || "binance"}` : "WS hub · Binance reconnecting"
    );
    if (els.wsLatency) {
      const pingText = Number.isFinite(lastWsPingMs) ? `${fmt(lastWsPingMs, 1)} ms` : "— ms";
      const ageText = Number.isFinite(stream.last_message_age_ms)
        ? `feed age ${fmt(stream.last_message_age_ms, 0)} ms`
        : "feed age —";
      els.wsLatency.textContent = `Ping ${pingText} · ${ageText}`;
    }
    if (els.qFeed) {
      const age = Number.isFinite(stream.last_message_age_ms) ? fmt(stream.last_message_age_ms, 0) : "—";
      const backoff = Number.isFinite(stream.reconnect_backoff_ms) ? fmt(stream.reconnect_backoff_ms, 0) : "—";
      els.qFeed.textContent = `${live ? "Healthy" : "Recovering"} · age ${age} ms · backoff ${backoff} ms`;
    }
    els.footerClock.textContent = `Stream ${msg.server_time || msg.ts || "—"} · cycle #${
      msg.cycle || 0
    } · ping ${Number.isFinite(lastWsPingMs) ? `${fmt(lastWsPingMs, 1)} ms` : "—"}`;
    if (typeof msg.sentiment_score === "number" && els.sentimentScore) {
      // lightweight sentiment update from hub; full headlines via slow REST
      els.sentimentScore.textContent = fmt(msg.sentiment_score, 1);
      if (msg.sentiment_label) els.sentimentLabel.textContent = msg.sentiment_label;
    }
  }

  function handleMarketMessage(msg) {
    if (!msg || !msg.type) return;
    if (msg.type === "snapshot") {
      applySnapshot(msg);
      return;
    }
    if (msg.type === "bot_lifecycle") {
      if (!toggling) setBotUi(!!msg.bot_running);
      if (msg.message) {
        renderActivity([{ ts: msg.ts, level: "lifecycle", message: msg.message }]);
      }
      return;
    }
    if (msg.type === "kline" && msg.symbol === chartSymbol && msg.candle) {
      if (chartEngine) chartEngine.updateLiveCandle(msg.candle);
      // keep local candle cache tip updated
      if (chartCandles.length) {
        const last = chartCandles[chartCandles.length - 1];
        if (last.time === msg.candle.time) chartCandles[chartCandles.length - 1] = msg.candle;
        else if (msg.candle.time > last.time) chartCandles.push(msg.candle);
      }
      if (els.chartMeta && msg.candle.close) {
        els.chartMeta.textContent = `${chartSymbol} · live ${fmt(
          msg.candle.close,
          msg.candle.close >= 100 ? 2 : 4
        )}`;
      }
      return;
    }
    if (msg.type === "pong") {
      const sentAt = Number(msg.client_ts || lastPingSentAt || 0);
      if (sentAt > 0) {
        lastWsPingMs = performance.now() - sentAt;
        if (els.wsLatency) els.wsLatency.textContent = `Ping ${fmt(lastWsPingMs, 1)} ms`;
      }
      return;
    }
    if ((msg.type === "mark_price" || msg.type === "book_ticker") && msg.symbol) {
      const price =
        msg.type === "mark_price" ? Number(msg.mark_price) : Number(msg.mid || msg.bid);
      if (price > 0 && els.scannerBody) {
        const row = [...els.scannerBody.querySelectorAll("tr")].find((tr) =>
          tr.textContent.includes(msg.symbol)
        );
        if (row) {
          const cells = row.querySelectorAll("td");
          if (cells[1]) {
            cells[1].textContent = fmt(price, price >= 100 ? 2 : 4);
            row.classList.remove("tick-pulse");
            void row.offsetWidth;
            row.classList.add("tick-pulse");
          }
        }
        if (chartEngine?.setDepth && msg.bid && msg.ask) {
          chartEngine.setDepth({
            bids: [[msg.bid, msg.bid_qty || 1]],
            asks: [[msg.ask, msg.ask_qty || 1]],
          });
        }
        if (msg.bid_qty || msg.ask_qty) {
          const bidQty = Number(msg.bid_qty || 0);
          const askQty = Number(msg.ask_qty || 0);
          const denom = bidQty + askQty;
          lastBookImbalance = denom > 0 ? ((bidQty - askQty) / denom) * 100 : null;
          if (els.qObi) {
            const bias = lastBookImbalance >= 0 ? "Bid-led" : "Ask-led";
            els.qObi.textContent = Number.isFinite(lastBookImbalance)
              ? `${bias} · ${fmt(lastBookImbalance, 2)}%`
              : "—";
          }
        }
      }
      if (msg.symbol === chartSymbol && els.chartMeta && price > 0) {
        els.chartMeta.textContent = `${chartSymbol} · tick ${fmt(price, price >= 100 ? 2 : 4)}`;
      }
    }
  }

  function connectMarketWs() {
    if (marketWs && (marketWs.readyState === WebSocket.OPEN || marketWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    setWsPill("idle", "WS connecting…");
    marketWs = new WebSocket(wsUrl("/ws/market"));
    marketWs.onopen = () => {
      wsRetryMs = 1000;
      setWsPill("live", "WS connected");
      marketWs.send(JSON.stringify({ action: "subscribe_symbols", symbols: watchlist }));
      marketWs.send(JSON.stringify({ action: "request_snapshot" }));
      if (pingLoop) clearInterval(pingLoop);
      pingLoop = setInterval(() => {
        if (marketWs?.readyState === WebSocket.OPEN) {
          lastPingSentAt = performance.now();
          marketWs.send(JSON.stringify({ action: "ping", client_ts: lastPingSentAt }));
        }
      }, 15000);
    };
    marketWs.onmessage = (ev) => {
      parseWsPayload(ev.data).then((msg) => msg && handleMarketMessage(msg));
    };
    marketWs.onclose = () => {
      if (pingLoop) {
        clearInterval(pingLoop);
        pingLoop = null;
      }
      setWsPill("down", "WS reconnecting…");
      setTimeout(connectMarketWs, wsRetryMs);
      wsRetryMs = Math.min(wsRetryMs * 1.6, 10000);
    };
    marketWs.onerror = () => {
      try {
        marketWs.close();
      } catch (_) {
        /* ignore */
      }
    };
  }

  function connectBotWs() {
    if (botWs && (botWs.readyState === WebSocket.OPEN || botWs.readyState === WebSocket.CONNECTING)) {
      return;
    }
    botWs = new WebSocket(wsUrl("/ws/bot-status"));
    botWs.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.type === "bot_lifecycle" || msg.type === "bot_status") {
          if (!toggling && typeof msg.bot_running === "boolean") setBotUi(msg.bot_running);
          if (msg.activity) renderActivity(msg.activity);
          else if (msg.message) {
            renderActivity([{ ts: msg.ts, level: "lifecycle", message: msg.message }]);
          }
        }
      } catch (_) {
        /* ignore */
      }
    };
    botWs.onclose = () => setTimeout(connectBotWs, 2000);
  }

  const GAUGE_LEN = 157;

  const token = () => localStorage.getItem(TOKEN_KEY);

  const fmt = (n, d = 2) => {
    const x = Number(n);
    if (!Number.isFinite(x)) return "—";
    return x.toLocaleString(undefined, {
      minimumFractionDigits: d,
      maximumFractionDigits: d,
    });
  };

  const money = (n, d = 2) => {
    const x = Number(n);
    if (!Number.isFinite(x)) return "$—";
    const sign = x < 0 ? "-" : "";
    return `${sign}$${fmt(Math.abs(x), d)}`;
  };

  const pnlClass = (n) => (Number(n) >= 0 ? "pnl-pos" : "pnl-neg");

  const signalBadge = (signal) => {
    const s = String(signal || "HOLD").toUpperCase();
    const cls = s === "BUY" ? "badge-buy" : s === "SELL" ? "badge-sell" : "badge-hold";
    return `<span class="badge ${cls}">${s}</span>`;
  };

  const sideBadge = (side) => {
    const s = String(side || "").toUpperCase();
    const cls = s === "LONG" ? "badge-long" : "badge-short";
    return `<span class="badge ${cls}">${s || "—"}</span>`;
  };

  function authHeaders(extra = {}) {
    const t = token();
    return {
      ...extra,
      ...(t ? { Authorization: `Bearer ${t}` } : {}),
    };
  }

  async function fetchJson(url, options = {}) {
    const opts = { ...options, headers: authHeaders(options.headers || {}) };
    const res = await fetch(url, opts);
    if (res.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      window.location.href = "/?auth=login";
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      let detail = `${url} -> ${res.status}`;
      try {
        const body = await res.json();
        if (body.detail) {
          detail = Array.isArray(body.detail)
            ? body.detail.map((d) => d.msg || JSON.stringify(d)).join(", ")
            : body.detail;
        }
      } catch (_) {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json();
  }

  function setBotUi(running) {
    els.statusDot.classList.toggle("live", running);
    els.statusDot.classList.toggle("idle", !running);
    els.statusLabel.textContent = running ? "LIVE" : "IDLE";
    els.toggle.checked = !!running;
    els.toggleText.textContent = running ? "ON" : "OFF";
  }

  function normalizeSymbol(raw) {
    let s = String(raw || "").trim().toUpperCase().replace(/-/g, "/");
    if (!s) return "";
    if (!s.includes("/") && s.endsWith("USDT")) s = `${s.slice(0, -4)}/USDT`;
    if (!s.includes("/")) s = `${s}/USDT`;
    return s;
  }

  function renderWatchChips() {
    els.watchChips.innerHTML = watchlist
      .map(
        (sym) => `
      <span class="watch-chip" data-chart="${sym}" title="Show ${sym} on chart">
        ${sym}
        <button type="button" data-remove="${sym}" aria-label="Remove ${sym}">×</button>
      </span>`
      )
      .join("");
    els.watchMeta.textContent = `${watchlist.length} pairs in watchlist`;
    els.watchChips.querySelectorAll("[data-remove]").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const sym = btn.getAttribute("data-remove");
        watchlist = watchlist.filter((s) => s !== sym);
        await persistWatchlist();
        renderWatchChips();
      });
    });
    els.watchChips.querySelectorAll("[data-chart]").forEach((chip) => {
      chip.addEventListener("click", () => {
        selectChartSymbol(chip.getAttribute("data-chart"));
      });
    });
  }

  function populatePairSelect(filter = "") {
    const q = filter.trim().toUpperCase();
    const options = universe
      .filter((p) => !q || p.symbol.includes(q) || String(p.base || "").includes(q))
      .slice(0, 120);
    els.pairSelect.innerHTML =
      `<option value="">Select from top ${universe.length} pairs</option>` +
      options
        .map(
          (p) =>
            `<option value="${p.symbol}">${p.symbol}${
              Number(p.quote_volume || 0) > 0 && p.info_type !== "seed"
                ? ` · vol $${Number(p.quote_volume || 0).toLocaleString(undefined, {
                    maximumFractionDigits: 0,
                  })}`
                : ""
            }</option>`
        )
        .join("");
  }

  async function persistWatchlist() {
    await fetchJson("/api/scanner/watchlist", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbols: watchlist }),
    });
    populateChartSymbols(watchlist);
    if (marketWs && marketWs.readyState === WebSocket.OPEN) {
      marketWs.send(JSON.stringify({ action: "subscribe_symbols", symbols: watchlist }));
    }
  }

  async function addPair(symbol) {
    const sym = normalizeSymbol(symbol);
    if (!sym) return;
    if (!watchlist.includes(sym)) watchlist.push(sym);
    await persistWatchlist();
    renderWatchChips();
  }

  function renderScanner(statusOrScan) {
    const markets = statusOrScan.markets || statusOrScan.results || [];
    els.scanMeta.textContent = statusOrScan.last_cycle_at
      ? `Cycle #${statusOrScan.cycle || 0} · ${statusOrScan.last_cycle_at}`
      : statusOrScan.mode
        ? `${statusOrScan.mode} scan · ${statusOrScan.scanned || markets.length} pairs`
        : "Awaiting first scan";

    if (!markets.length) {
      els.scannerBody.innerHTML = `<tr><td colspan="4" class="empty">No market data yet</td></tr>`;
      return;
    }

    els.scannerBody.innerHTML = markets
      .slice(0, 50)
      .map(
        (m) => `
      <tr class="fade-in scanner-row" data-symbol="${m.symbol}" title="Open ${m.symbol} chart">
        <td data-label="Pair" title="${m.symbol}"><span class="truncate-cell font-semibold text-white">${m.symbol}</span></td>
        <td data-label="Price"><span class="metric-num">${fmt(m.price || m.entry_price, (m.price || m.entry_price) >= 100 ? 2 : 4)}</span></td>
        <td data-label="AI Signal">${signalBadge(m.signal)}</td>
        <td data-label="Confidence"><span class="metric-num">${fmt(m.confidence ?? m.confidence_score, 1)}%</span></td>
      </tr>`
      )
      .join("");
  }

  function renderPositions(portfolio) {
    const positions = portfolio.positions || [];
    els.posMeta.textContent = `${positions.length} open`;
    if (!positions.length) {
      els.positionsBody.innerHTML = `<tr><td colspan="8" class="empty">No open positions</td></tr>`;
      return;
    }
    els.positionsBody.innerHTML = positions
      .map((p) => {
        const upnl = Number(p.unrealized_pnl || 0);
        return `
      <tr class="fade-in">
        <td data-label="Symbol" title="${p.symbol}"><span class="truncate-cell font-semibold text-white">${p.symbol}</span></td>
        <td data-label="Side">${sideBadge(p.direction)}</td>
        <td data-label="Entry"><span class="metric-num">${fmt(p.entry_price)}</span></td>
        <td data-label="Mark"><span class="metric-num">${fmt(p.mark_price)}</span></td>
        <td data-label="SL"><span class="metric-num">${fmt(p.stop_loss)}</span></td>
        <td data-label="TP"><span class="metric-num">${fmt(p.take_profit)}</span></td>
        <td data-label="Live PnL" class="${pnlClass(upnl)}"><span class="metric-num">${money(upnl)}</span></td>
        <td data-label="AI Reason">${aiReasonBadge(p.ai_reasoning)}</td>
      </tr>`;
      })
      .join("");
  }

  function renderHistory(payload) {
    const trades = payload.trades || [];
    els.historyMeta.textContent = `${payload.count || 0} total · audit log`;
    if (!trades.length) {
      els.historyBody.innerHTML = `<tr><td colspan="8" class="empty">No closed trades yet</td></tr>`;
      return;
    }
    els.historyBody.innerHTML = trades
      .slice(0, 20)
      .map((t) => {
        const pnl = Number(t.pnl_usd || 0);
        const badge =
          pnl > 0
            ? `<span class="pnl-badge profit">PROFIT</span>`
            : pnl < 0
              ? `<span class="pnl-badge loss">LOSS</span>`
              : `<span class="pnl-badge">FLAT</span>`;
        return `
      <tr class="fade-in">
        <td data-label="Time" title="${t.timestamp || "—"}"><span class="truncate-cell">${t.timestamp || "—"}</span></td>
        <td data-label="Pair" title="${t.pair || "—"}"><span class="truncate-cell">${t.pair || "—"}</span></td>
        <td data-label="Side">${sideBadge(t.direction)}</td>
        <td data-label="Entry"><span class="metric-num">${fmt(t.entry_price)}</span></td>
        <td data-label="Exit"><span class="metric-num">${fmt(t.exit_price)}</span></td>
        <td data-label="PnL" class="${pnlClass(pnl)}"><span class="metric-num">${money(pnl)}</span></td>
        <td data-label="Badge">${badge}</td>
        <td data-label="AI Reason">${aiReasonBadge(t.ai_reasoning || t.exit_reason)}</td>
      </tr>`;
      })
      .join("");
  }

  function renderNews(feed) {
    const box = document.getElementById("news-feed");
    const meta = document.getElementById("news-meta");
    if (!box) return;
    const items = feed?.items || [];
    if (meta) {
      meta.textContent = `${items.length} stories · score ${fmt(feed?.sentiment_score, 1)}`;
    }
    if (!items.length) {
      box.innerHTML = `<div class="empty text-mist text-sm">No headlines yet</div>`;
      return;
    }
    box.innerHTML = items
      .slice(0, 20)
      .map((n) => {
        const badge = String(n.badge || "Neutral").toLowerCase();
        const title = n.title || "Untitled";
        const href = n.link || "#";
        return `<article class="news-item">
          <span class="news-badge ${badge}">${n.badge || "Neutral"}</span>
          <div class="min-w-0">
            <a class="text-sm text-white hover:text-teal truncate-cell" title="${title}" href="${href}" target="_blank" rel="noopener">${title}</a>
            <div class="text-[11px] text-mist mt-1 truncate-cell" title="${(n.source || "wire") + " · " + (n.published || "")}">${n.source || "wire"} · ${n.published || ""}</div>
          </div>
        </article>`;
      })
      .join("");
  }

  function updateManualLiq() {
    const lev = Number(document.getElementById("manual-leverage")?.value || 10);
    const side = document.getElementById("manual-side")?.value || "BUY";
    const label = document.getElementById("lev-label");
    if (label) label.textContent = `${lev}x`;
    const market = lastMarkets.find((m) => m.symbol === (document.getElementById("manual-symbol")?.value || chartSymbol));
    const price = Number(market?.price || lastMarkets[0]?.price || 0);
    const liqEl = document.getElementById("manual-liq");
    if (!liqEl || !(price > 0) || !(lev > 0)) {
      if (liqEl) liqEl.textContent = "—";
      return;
    }
    const liq = side === "BUY" ? price * (1 - 0.9 / lev) : price * (1 + 0.9 / lev);
    liqEl.textContent = fmt(liq, price >= 100 ? 2 : 4);
  }

  async function refreshQuant() {
    try {
      const data = await fetchJson(`/api/quant/snapshot?symbol=${encodeURIComponent(chartSymbol)}`);
      const q = data.quant || {};
      const vpin = q.vpin || {};
      const regime = q.regime || {};
      const liq = q.liquidation || {};
      const br = q.circuit_breaker || {};
      const hft = data.hft || {};
      const macro = data.macro_guard || {};
      const liqHunter = data.liquidation_hunter || {};
      const health = data.system_health || {};
      const elV = document.getElementById("q-vpin");
      const elR = document.getElementById("q-regime");
      const elB = document.getElementById("q-breaker");
      const elH = document.getElementById("q-hft-lat");
      if (elV) elV.textContent = `${vpin.label || "—"} · ${fmt(vpin.vpin, 3)}`;
      if (elR) elR.textContent = regime.label || "—";
      if (elB) {
        elB.textContent = br.tripped ? "TRIPPED" : "OK";
        elB.className = `mini-value text-sm ${br.tripped ? "text-rose" : "text-teal"}`;
      }
      if (elH) elH.textContent = `${fmt(hft.stats?.last_latency_ms, 3)} ms`;
      if (els.qLiq) {
        const levels = Array.isArray(liq.levels) ? liq.levels : [];
        const best = levels[0] || {};
        els.qLiq.textContent = levels.length
          ? `L ${fmt(best.long_density, 2)} · S ${fmt(best.short_density, 2)}`
          : "No map yet";
      }
      if (els.qFeed) {
        const latency = Number.isFinite(lastWsPingMs) ? `${fmt(lastWsPingMs, 1)} ms` : "Warmup";
        const macroLabel = macro.label ? `Macro ${macro.label}` : "Macro calm";
        const liqLabel = liqHunter.last_cluster?.symbol
          ? `Liq ${liqHunter.last_cluster.symbol}`
          : "No liq cluster";
        const mem = Number.isFinite(Number(health.rss_mb)) ? `RAM ${fmt(health.rss_mb, 0)}MB` : "RAM —";
        els.qFeed.textContent = `${macroLabel} · ${liqLabel} · ${mem} · ${latency}`;
      }
      hftEnabled = !!hft.enabled;
      const btn = document.getElementById("btn-hft-toggle");
      if (btn) btn.textContent = `HFT Scalper: ${hftEnabled ? "ON" : "OFF"}`;
    } catch (_) {
      /* ignore */
    }
  }

  function renderStats(portfolio) {
    els.equity.innerHTML = `<span class="metric-num">${money(portfolio.equity)}</span>`;
    els.wallet.innerHTML = `<span class="metric-num">Wallet ${money(portfolio.wallet_balance)} · Avail ${money(
      portfolio.available_balance
    )}</span>`;
    els.active.innerHTML = `<span class="metric-num">${String(
      portfolio.open_positions ?? (portfolio.positions || []).length
    )}</span>`;
    els.dailyPnl.innerHTML = `<span class="metric-num">${money(portfolio.daily_realized_pnl)}</span>`;
    els.dailyPnl.className = `stat-value ${pnlClass(portfolio.daily_realized_pnl)}`;
    els.realized.innerHTML = `<span class="metric-num">All-time ${money(portfolio.realized_pnl)}</span>`;
    els.winrate.innerHTML = `<span class="metric-num">${fmt(portfolio.win_rate, 1)}%</span>`;
    els.closed.textContent = `${portfolio.closed_trades || 0} closed trades`;
    const qm = portfolio.quant_metrics || {};
    if (els.qmSharpe) els.qmSharpe.innerHTML = `<span class="metric-num">${fmt(qm.sharpe_ratio, 3)}</span>`;
    if (els.qmSortino) els.qmSortino.innerHTML = `<span class="metric-num">${fmt(qm.sortino_ratio, 3)}</span>`;
    if (els.qmVar) els.qmVar.innerHTML = `<span class="metric-num">${money(qm.var_24h_usd)}</span>`;
  }

  function gaugeColor(score) {
    if (score < 35) return "#f43f5e";
    if (score > 65) return "#2dd4bf";
    return "#f59e0b";
  }

  function renderSentiment(sentiment) {
    const score = Number(sentiment.score);
    const safe = Number.isFinite(score) ? score : 50;
    els.sentimentScore.textContent = fmt(safe, 1);
    els.sentimentLabel.textContent = sentiment.label || "Neutral";
    els.sentimentMeta.textContent = sentiment.updated_at || "—";
    els.sentHeadlines.textContent = String(sentiment.headline_count || 0);
    els.sentBull.textContent = String(sentiment.bullish_count || 0);
    els.sentBear.textContent = String(sentiment.bearish_count || 0);
    const offset = GAUGE_LEN * (1 - Math.max(0, Math.min(100, safe)) / 100);
    els.gaugeValue.style.strokeDashoffset = String(offset);
    els.gaugeValue.style.stroke = gaugeColor(safe);
    const headlines = sentiment.headlines || [];
    els.headlineList.innerHTML = headlines.length
      ? headlines
          .slice(0, 6)
          .map((h) => {
            const cls = h.tone === "bearish" ? "bear" : "";
            const title = h.title || "Untitled";
            const link = h.link
              ? `<a href="${h.link}" target="_blank" rel="noopener noreferrer">${title}</a>`
              : title;
            return `<li class="${cls}">${link}</li>`;
          })
          .join("")
      : `<li>No headlines available</li>`;
  }

  function renderSeo(payload) {
    const articles = payload.articles || [];
    els.seoMeta.textContent = `${payload.count || 0} articles`;
    if (!articles.length) {
      els.seoFeed.innerHTML = `<div class="empty">No SEO articles generated yet</div>`;
      return;
    }
    els.seoFeed.innerHTML = articles
      .map((a) => {
        const htmlPath = a.html_path
          ? `/${String(a.html_path).replace(/\\/g, "/")}`
          : a.canonical_url || "#";
        return `
      <article class="seo-card fade-in">
        <h3>${a.title || "Untitled"}</h3>
        <p>${a.meta_description || a.excerpt || ""}</p>
        <div class="seo-meta-row">
          <span>Keyword: <strong>${a.keyword || "—"}</strong></span>
          <span>${a.date || ""}</span>
          <a href="${htmlPath}" target="_blank" rel="noopener noreferrer">Open HTML</a>
        </div>
      </article>`;
      })
      .join("");
  }

  function renderCopy(payload) {
    const followers = payload.followers || [];
    els.copyFollowers.textContent = String(payload.follower_count || 0);
    els.copyCommission.textContent = money(payload.total_master_commission);
    els.copyFollowerPnl.textContent = money(payload.total_follower_net_pnl);
    els.copyFollowerPnl.className = `mini-value ${pnlClass(payload.total_follower_net_pnl)}`;
    els.copyMeta.textContent = `Profit share ${fmt(payload.profit_share_pct, 0)}%`;
    els.copyMasterLine.textContent = payload.master
      ? `Master: ${payload.master.label} (${payload.master.exchange})`
      : "No master account linked — connect one via Exchange API.";
    if (!followers.length) {
      els.copyBody.innerHTML = `<tr><td colspan="8" class="empty">No follower accounts yet</td></tr>`;
      return;
    }
    els.copyBody.innerHTML = followers
      .map((f, idx) => {
        const net = Number(f.net_follower_pnl || 0);
        return `
      <tr class="fade-in">
        <td data-label="Rank">#${idx + 1}</td>
        <td data-label="Label" class="font-semibold text-white">${f.label || f.id}</td>
        <td data-label="Exchange">${String(f.exchange || "").toUpperCase()}</td>
        <td data-label="Equity">${money(f.equity || f.equity_hint || 0)}</td>
        <td data-label="Status">${f.copy_status || "idle"}</td>
        <td data-label="Copied">${f.copied_trades || 0}</td>
        <td data-label="Net PnL" class="${pnlClass(net)}">${money(net)}</td>
        <td data-label="Master Cut">${money(f.master_commission || 0)}</td>
      </tr>`;
      })
      .join("");
  }

  function openModal() {
    els.connectError.classList.add("hidden");
    els.connectSuccess.classList.add("hidden");
    els.connectModal.classList.remove("hidden");
  }

  function closeModal() {
    els.connectModal.classList.add("hidden");
  }

  async function ensureAuth() {
    try {
      const me = await fetchJson("/api/auth/me");
      currentUser = me.user;
      watchlist = currentUser.watchlist || watchlist;
      els.userChip.textContent = currentUser.email;
      els.userChip.classList.remove("hidden");
      renderWatchChips();
      return true;
    } catch (_) {
      window.location.href = "/?auth=login";
      return false;
    }
  }

  async function loadUniverse() {
    // Seed already populates dropdown instantly; refresh upgrades volume ranking.
    populatePairSelect();
    populateChartSymbols(SEED_TOP_50);
    try {
      const data = await fetchJson("/api/scanner/pairs?limit=250");
      if (data.pairs && data.pairs.length) {
        universe = data.pairs;
        populatePairSelect();
        populateChartSymbols(universe.map((p) => p.symbol));
      }
    } catch (err) {
      // Keep seeded top-50 — no empty dropdown on API latency/failure.
      console.warn("Universe refresh deferred:", err.message);
    }
  }

  async function refreshSecondary() {
    try {
      const [sentiment, blogs, copy, news] = await Promise.all([
        fetchJson("/api/sentiment"),
        fetchJson("/api/seo/blogs?limit=20&generate=false"),
        fetchJson("/api/copy-trading/followers").catch(() => ({
          followers: [],
          follower_count: 0,
          total_master_commission: 0,
          total_follower_net_pnl: 0,
          profit_share_pct: 15,
        })),
        fetchJson("/api/news/feed?limit=25").catch(() => ({ items: [] })),
      ]);
      renderSentiment(sentiment);
      renderSeo(blogs);
      renderCopy(copy);
      renderNews(news);
      await refreshQuant();
      updateManualLiq();
    } catch (err) {
      console.error(err);
    }
  }

  function drawBacktestCurve(points) {
    const canvas = els.backtestChart;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(320, Math.floor(rect.width || 640));
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const w = canvas.width;
    const h = canvas.height;
    ctx.clearRect(0, 0, w, h);
    if (!points || !points.length) return;
    const vals = points.map((p) => Number(p.equity || 0));
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const span = Math.max(1, max - min);
    ctx.strokeStyle = "rgba(0, 217, 246, 0.25)";
    ctx.beginPath();
    for (let i = 0; i < 4; i += 1) {
      const y = 20 + (i * (h - 40)) / 3;
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
    }
    ctx.stroke();
    ctx.strokeStyle = "#00F5A0";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    points.forEach((p, i) => {
      const x = (i / Math.max(1, points.length - 1)) * (w - 24) + 12;
      const y = h - 20 - ((Number(p.equity || 0) - min) / span) * (h - 40);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
  }

  async function runBacktest() {
    if (!els.btnRunBacktest) return;
    els.btnRunBacktest.disabled = true;
    if (els.backtestMsg) els.backtestMsg.textContent = "Running 30-day simulation…";
    try {
      const payload = await fetchJson("/api/backtest", {
        method: "POST",
        body: JSON.stringify({
          symbol: (els.backtestSymbol?.value || chartSymbol || "BTC/USDT").trim(),
          timeframe: els.backtestTimeframe?.value || "1h",
          days: Number(els.backtestDays?.value || 30),
          starting_balance: 1000,
        }),
      });
      els.btWinrate.textContent = `${fmt(payload.win_rate_pct, 1)}%`;
      els.btDrawdown.textContent = `${fmt(payload.max_drawdown_pct, 2)}%`;
      els.btPnl.textContent = money(payload.cumulative_pnl_usd);
      els.btPnl.className = `mini-value ${pnlClass(payload.cumulative_pnl_usd)}`;
      els.btTrades.textContent = `${payload.trade_count || 0}`;
      if (els.leaderWinrate) els.leaderWinrate.textContent = `${fmt(payload.win_rate_pct, 1)}%`;
      if (els.leaderProfitFactor) {
        els.leaderProfitFactor.textContent = fmt(payload.profit_factor, 2);
      }
      if (els.leaderDrawdown) els.leaderDrawdown.textContent = `${fmt(payload.max_drawdown_pct, 2)}%`;
      if (els.leaderSymbol) {
        els.leaderSymbol.textContent = `${payload.symbol} · ${payload.timeframe} · verified ${payload.days}d run`;
      }
      if (els.backtestMeta) {
        els.backtestMeta.textContent = `${payload.symbol} · ${payload.timeframe} · ${payload.days}d`;
      }
      if (els.backtestMsg) {
        els.backtestMsg.textContent = `Ending equity ${money(payload.ending_equity)} from ${money(
          payload.starting_balance
        )}`;
      }
      drawBacktestCurve(payload.equity_curve || []);
    } catch (err) {
      if (els.backtestMsg) els.backtestMsg.textContent = err.message;
    } finally {
      els.btnRunBacktest.disabled = false;
    }
  }

  async function runStressTest() {
    if (!els.btnStressTest) return;
    els.btnStressTest.disabled = true;
    if (els.stressMsg) els.stressMsg.textContent = "Running crash scenarios…";
    try {
      const payload = await fetchJson("/api/simulate-stress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ shocks: [-5, -10, -20] }),
      });
      const rows = payload.scenarios || [];
      els.stressResults.innerHTML = rows.length
        ? rows
            .map(
              (row) => `<article class="stress-card">
              <div class="stress-head">
                <strong>${fmt(row.shock_pct, 0)}% shock</strong>
                <span class="${pnlClass(row.projected_total_pnl_usd)}">${money(
                  row.projected_total_pnl_usd
                )}</span>
              </div>
              <div class="stress-list">
                <div>Liquidation vulnerabilities: ${row.liquidation_vulnerabilities || 0}</div>
                <div>${(row.recommendations || []).join(" ")}</div>
              </div>
            </article>`
            )
            .join("")
        : `<div class="empty text-mist text-sm">No open positions to stress test.</div>`;
      if (els.stressMsg) els.stressMsg.textContent = `Evaluated ${payload.position_count || 0} open positions.`;
    } catch (err) {
      if (els.stressMsg) els.stressMsg.textContent = err.message;
    } finally {
      els.btnStressTest.disabled = false;
    }
  }

  function parseCopilotIntent(text) {
    const input = String(text || "").trim();
    if (!input) return null;
    const side = /\b(long|buy)\b/i.test(input) ? "BUY" : /\b(short|sell)\b/i.test(input) ? "SELL" : "BUY";
    const symbolMatch =
      input.match(/\b(?:long|buy|short|sell)\s+([A-Z]{2,10})\b/i) ||
      input.match(/\b([A-Z]{2,10})USDT\b/i) ||
      input.match(/\b([A-Z]{2,10})\/USDT\b/i);
    const leverageMatch = input.match(/(\d+(?:\.\d+)?)x/i);
    const tpMatch = input.match(/tp\s*(\d+(?:\.\d+)?)%/i);
    const sizeMatch = input.match(/(?:size|notional|usd|usdt)\s*(\d+(?:\.\d+)?)/i);
    const symbol = normalizeSymbol(symbolMatch ? `${symbolMatch[1]}/USDT` : chartSymbol);
    return {
      symbol,
      side,
      leverage: Number(leverageMatch?.[1] || 5),
      notional: Number(sizeMatch?.[1] || 50),
      tpPct: Number(tpMatch?.[1] || 2),
      raw: input,
    };
  }

  function previewCopilotIntent() {
    const parsed = parseCopilotIntent(els.copilotInput?.value || "");
    if (!els.copilotPreview) return parsed;
    if (!parsed) {
      els.copilotPreview.textContent = "Type a command like: Long SOL 5x leverage TP 3%";
      return null;
    }
    els.copilotPreview.textContent = `${parsed.side} ${parsed.symbol} · ${parsed.leverage}x · ${
      parsed.notional
    } USDT · TP ${parsed.tpPct}%`;
    return parsed;
  }

  function setCopilotOpen(open) {
    if (!els.copilotModal) return;
    els.copilotModal.classList.toggle("hidden", !open);
    els.copilotModal.setAttribute("aria-hidden", open ? "false" : "true");
    if (open) setTimeout(() => els.copilotInput?.focus(), 20);
  }

  async function runCopilotIntent() {
    const parsed = previewCopilotIntent();
    if (!parsed) return;
    const market = lastMarkets.find((m) => m.symbol === parsed.symbol);
    const price = Number(market?.price || 0);
    const tpFactor = parsed.side === "BUY" ? 1 + parsed.tpPct / 100 : 1 - parsed.tpPct / 100;
    const result = await fetchJson("/api/desk/manual-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: parsed.symbol,
        side: parsed.side,
        leverage: parsed.leverage,
        notional: parsed.notional,
        price,
        margin_mode: "isolated",
        take_profit_hint: tpFactor,
        ai_reasoning: `Copilot intent: ${parsed.raw}`,
      }),
    });
    if (els.copilotPreview) {
      els.copilotPreview.textContent = `Executed ${parsed.side} ${parsed.symbol} · est liq ${fmt(
        result.liquidation_price,
        price >= 100 ? 2 : 4
      )}`;
    }
    setCopilotOpen(false);
    refresh().catch(console.error);
  }

  async function refresh() {
    // Fallback REST path when WS is down
    try {
      const [status, portfolio, history] = await Promise.all([
        fetchJson("/api/status"),
        fetchJson("/api/portfolio"),
        fetchJson("/api/trade-history?limit=50"),
      ]);
      applySnapshot({
        type: "snapshot",
        bot_running: status.bot_running,
        cycle: status.cycle,
        server_time: status.server_time,
        markets: status.markets,
        portfolio,
        positions: portfolio.positions,
        history,
        events: status.events,
        sentiment_score: status.sentiment_score,
        sentiment_label: status.sentiment_label,
        stream: { binance_connected: false },
      });
      await refreshSecondary();
    } catch (err) {
      console.error(err);
      els.footerClock.textContent = `Refresh failed: ${err.message}`;
    }
  }

  function switchTab(tab) {
    const allowed = ["trading", "copy", "seo", "billing"];
    const next = allowed.includes(tab) ? tab : "trading";
    document.querySelectorAll(".tab-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.tab === next);
    });
    document.getElementById("tab-trading").classList.toggle("hidden", next !== "trading");
    document.getElementById("tab-copy").classList.toggle("hidden", next !== "copy");
    document.getElementById("tab-seo").classList.toggle("hidden", next !== "seo");
    document.getElementById("tab-billing").classList.toggle("hidden", next !== "billing");
    if (next === "billing") loadBilling().catch(console.error);
  }

  async function loadBilling() {
    const [sub, pay] = await Promise.all([
      fetchJson("/api/subscription/status"),
      fetchJson("/api/payments/status"),
    ]);
    const user = sub.user || currentUser || {};
    if (els.billPlan) els.billPlan.textContent = String(user.plan || "free").toUpperCase();
    if (els.billStatus) {
      els.billStatus.textContent = String(user.subscription_status || "trialing").toUpperCase();
    }
    if (els.billProvider) {
      els.billProvider.textContent = user.payment_provider
        ? String(user.payment_provider).toUpperCase()
        : "—";
    }
    if (els.billExpires) {
      els.billExpires.textContent = user.subscription_expires_at
        ? new Date(user.subscription_expires_at).toLocaleString()
        : "—";
    }
    if (els.billEmail) {
      els.billEmail.textContent = user.email
        ? `Signed in as ${user.email}`
        : "Signed in";
    }
    if (els.billPayMode) {
      els.billPayMode.textContent = `Gateway mode · Stripe: ${pay.stripe_mode} · Crypto: ${pay.crypto_mode}`;
    }
    if (els.billingMeta) {
      els.billingMeta.textContent = sub.source === "user" ? "Account billing" : "Global mock";
    }
  }

  document.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  if (els.btnRefreshBilling) {
    els.btnRefreshBilling.addEventListener("click", () => {
      loadBilling().catch((err) => {
        if (els.billingMeta) els.billingMeta.textContent = err.message;
      });
    });
  }

  if (els.btnRunBacktest) {
    els.btnRunBacktest.addEventListener("click", () => {
      runBacktest().catch(console.error);
    });
  }

  document.querySelectorAll("[data-sandbox-mode]").forEach((btn) => {
    btn.addEventListener("click", () => applySandboxMode(btn.dataset.sandboxMode));
  });

  if (els.btnStressTest) {
    els.btnStressTest.addEventListener("click", () => runStressTest().catch(console.error));
  }
  if (els.btnExportCsv) {
    els.btnExportCsv.addEventListener("click", () => {
      downloadExport("/api/export/trades.csv", "beast_ai_trade_ledger.csv").catch((err) =>
        alert(err.message || "CSV export failed")
      );
    });
  }
  if (els.btnExportPdf) {
    els.btnExportPdf.addEventListener("click", () => {
      downloadExport("/api/export/trades.pdf", "beast_ai_trade_ledger.pdf").catch((err) =>
        alert(err.message || "PDF export failed")
      );
    });
  }

  if (els.btnCopilot) els.btnCopilot.addEventListener("click", () => setCopilotOpen(true));
  document.querySelectorAll("[data-close-copilot]").forEach((el) => {
    el.addEventListener("click", () => setCopilotOpen(false));
  });
  els.copilotInput?.addEventListener("input", previewCopilotIntent);
  els.btnCopilotRun?.addEventListener("click", () => runCopilotIntent().catch(console.error));
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      setCopilotOpen(true);
      previewCopilotIntent();
    }
    if (event.key === "Escape") setCopilotOpen(false);
  });

  if (els.btnManageBilling) {
    els.btnManageBilling.addEventListener("click", async () => {
      els.btnManageBilling.disabled = true;
      try {
        const result = await fetchJson("/api/payments/customer-portal", { method: "POST" });
        if (result.url) {
          window.location.href = result.url;
          return;
        }
        throw new Error("No portal URL");
      } catch (err) {
        if (els.billingBanner) {
          els.billingBanner.textContent = err.message;
          els.billingBanner.classList.remove("hidden");
          els.billingBanner.classList.remove("text-teal");
          els.billingBanner.classList.add("text-rose");
        }
      } finally {
        els.btnManageBilling.disabled = false;
      }
    });
  }

  els.btnConnect.addEventListener("click", openModal);
  els.connectModal.querySelectorAll("[data-close-modal]").forEach((el) => {
    el.addEventListener("click", closeModal);
  });

  els.btnLogout.addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
    } catch (_) {
      /* ignore */
    }
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
  });

  els.pairSearch.addEventListener("input", () => {
    populatePairSelect(els.pairSearch.value);
  });

  els.btnAddPair.addEventListener("click", async () => {
    const fromSelect = els.pairSelect.value;
    const fromSearch = els.pairSearch.value;
    await addPair(fromSelect || fromSearch);
    els.pairSearch.value = "";
  });

  els.btnScanWatch.addEventListener("click", async () => {
    els.watchMeta.textContent = "Scanning watchlist…";
    try {
      const result = await fetchJson("/api/scanner/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "watchlist", symbols: watchlist }),
      });
      renderScanner(result);
      els.watchMeta.textContent = `Watchlist scan complete · ${result.scanned} pairs`;
    } catch (err) {
      els.watchMeta.textContent = err.message;
    }
  });

  els.btnScanGlobal.addEventListener("click", async () => {
    els.watchMeta.textContent = "Scanning top 50 by volume…";
    try {
      const result = await fetchJson("/api/scanner/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "global", limit: 50 }),
      });
      renderScanner(result);
      els.watchMeta.textContent = `Global scan · top ${result.limit} / universe ${result.universe_size}`;
    } catch (err) {
      els.watchMeta.textContent = err.message;
    }
  });

  els.connectForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    els.connectError.classList.add("hidden");
    els.connectSuccess.classList.add("hidden");
    els.connectSubmit.disabled = true;
    els.connectSubmit.textContent = "Validating…";
    const payload = {
      exchange: document.getElementById("conn-exchange").value,
      label: document.getElementById("conn-label").value,
      role: document.getElementById("conn-role").value,
      api_key: document.getElementById("conn-key").value,
      api_secret: document.getElementById("conn-secret").value,
      passphrase: document.getElementById("conn-passphrase").value || null,
      equity_hint: Number(document.getElementById("conn-equity").value || 1000),
      paper_mode: document.getElementById("conn-paper").checked,
    };
    try {
      const result = await fetchJson("/api/exchange/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      els.connectSuccess.textContent = `Connected ${result.account.label} (${result.account.role})`;
      els.connectSuccess.classList.remove("hidden");
      els.connectForm.reset();
      document.getElementById("conn-paper").checked = true;
      document.getElementById("conn-equity").value = "1000";
      await refresh();
      setTimeout(closeModal, 900);
    } catch (err) {
      els.connectError.textContent = err.message || "Connection failed";
      els.connectError.classList.remove("hidden");
    } finally {
      els.connectSubmit.disabled = false;
      els.connectSubmit.textContent = "Validate & Save";
    }
  });

  els.toggle.addEventListener("change", async () => {
    toggling = true;
    const enabled = els.toggle.checked;
    setBotUi(enabled);
    try {
      const result = await fetchJson("/api/bot/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      setBotUi(!!result.running);
      await refresh();
    } catch (err) {
      setBotUi(!enabled);
      els.footerClock.textContent = `Toggle failed: ${err.message}`;
    } finally {
      toggling = false;
    }
  });

  if (els.chartSymbol) {
    els.chartSymbol.addEventListener("change", () => {
      selectChartSymbol(els.chartSymbol.value);
    });
  }

  if (els.scannerBody) {
    els.scannerBody.addEventListener("click", (ev) => {
      const row = ev.target.closest("tr[data-symbol]");
      if (row) selectChartSymbol(row.getAttribute("data-symbol"));
    });
  }

  if (els.pairSelect) {
    els.pairSelect.addEventListener("change", () => {
      if (els.pairSelect.value) selectChartSymbol(els.pairSelect.value);
    });
  }

  document.querySelectorAll("[data-chart-engine]").forEach((btn) => {
    btn.addEventListener("click", () => setChartEngine(btn.dataset.chartEngine));
  });

  document.querySelectorAll("[data-ui-mode]").forEach((btn) => {
    btn.addEventListener("click", () => applyUiMode(btn.dataset.uiMode));
  });

  document.querySelectorAll("[data-desk-mode]").forEach((btn) => {
    btn.addEventListener("click", () => {
      deskMode = btn.dataset.deskMode || "auto";
      document.querySelectorAll("[data-desk-mode]").forEach((b) => {
        b.classList.toggle("active", b.dataset.deskMode === deskMode);
        b.classList.toggle("secondary", b.dataset.deskMode !== deskMode);
      });
      document.getElementById("manual-desk")?.classList.toggle("hidden", deskMode !== "manual");
    });
  });

  document.querySelectorAll("[data-margin]").forEach((btn) => {
    btn.addEventListener("click", () => {
      marginMode = btn.dataset.margin || "isolated";
      document.querySelectorAll("[data-margin]").forEach((b) => {
        b.classList.toggle("active", b.dataset.margin === marginMode);
      });
      updateManualLiq();
    });
  });

  document.getElementById("manual-leverage")?.addEventListener("input", updateManualLiq);
  document.getElementById("manual-side")?.addEventListener("change", updateManualLiq);
  document.getElementById("manual-symbol")?.addEventListener("change", updateManualLiq);

  document.getElementById("btn-hft-toggle")?.addEventListener("click", async () => {
    try {
      const next = !hftEnabled;
      const res = await fetchJson("/api/hft/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: next }),
      });
      hftEnabled = !!res.enabled;
      document.getElementById("btn-hft-toggle").textContent = `HFT Scalper: ${
        hftEnabled ? "ON" : "OFF"
      }`;
    } catch (err) {
      els.footerClock.textContent = `HFT toggle failed: ${err.message}`;
    }
  });

  document.getElementById("btn-manual-submit")?.addEventListener("click", async () => {
    const msg = document.getElementById("manual-msg");
    try {
      const body = {
        symbol: document.getElementById("manual-symbol")?.value || chartSymbol,
        side: document.getElementById("manual-side")?.value || "BUY",
        notional: Number(document.getElementById("manual-notional")?.value || 50),
        leverage: Number(document.getElementById("manual-leverage")?.value || 10),
        margin_mode: marginMode,
      };
      const res = await fetchJson("/api/desk/manual-order", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (msg) {
        msg.textContent = `Order accepted · liq ${fmt(res.liquidation_price)} · ${
          res.order?.status || "ok"
        }`;
        msg.className = "text-xs text-teal mt-2";
      }
      await refresh();
    } catch (err) {
      if (msg) {
        msg.textContent = err.message || "Order failed";
        msg.className = "text-xs text-rose mt-2";
      }
    }
  });

  (async () => {
    // Instant UI: seed dropdown / chart symbols before network.
    populatePairSelect();
    populateChartSymbols(SEED_TOP_50);

    const bootParams = new URLSearchParams(window.location.search);
    const oauthToken = bootParams.get("oauth_token");
    if (oauthToken) {
      localStorage.setItem(TOKEN_KEY, oauthToken);
      bootParams.delete("oauth_token");
      const clean = `${window.location.pathname}${
        bootParams.toString() ? `?${bootParams}` : ""
      }${window.location.hash || ""}`;
      window.history.replaceState({}, "", clean);
    }
    const ok = await ensureAuth();
    if (!ok) return;
    const params = new URLSearchParams(window.location.search);
    const tab = params.get("tab");
    if (params.get("billing") === "success" && els.billingBanner) {
      const tier = params.get("tier") || "plan";
      const provider = params.get("provider") || "payment";
      els.billingBanner.textContent = `Payment confirmed via ${provider.toUpperCase()} — ${String(
        tier
      ).toUpperCase()} is active.`;
      els.billingBanner.classList.remove("hidden");
    }
    if (tab) switchTab(tab);
    applyUiMode(uiMode);
    applySandboxMode(sandboxMode);
    await loadUniverse().catch((err) => {
      els.watchMeta.textContent = `Using seeded top 50 · ${err.message}`;
    });
    populateChartSymbols([
      ...watchlist,
      ...SEED_TOP_50,
      ...universe.map((p) => p.symbol),
    ]);
    chartSymbol = watchlist[0] || "BTC/USDT";
    if (els.chartSymbol) els.chartSymbol.value = chartSymbol;
    setChartEngine(chartEngineMode);
    connectMarketWs();
    connectBotWs();
    await refreshSecondary();
    await runBacktest().catch(console.error);
    await runStressTest().catch(console.error);
    if (tab === "billing") await loadBilling().catch(console.error);
    // Slow REST for non-stream panels; trading desk is WebSocket-driven
    setInterval(refreshSecondary, SLOW_REFRESH_MS);
    // Safety net if WS drops for an extended period
    setInterval(() => {
      if (!marketWs || marketWs.readyState !== WebSocket.OPEN) refresh();
    }, 8000);
  })();
})();
