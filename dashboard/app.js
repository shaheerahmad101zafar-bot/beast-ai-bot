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
  let chartCandles = [];
  let chartSymbol = "BTC/USDT";
  let lastMarkets = [];
  let lastPositions = [];
  let knownPositionKeys = new Set();
  let marketWs = null;
  let botWs = null;
  let wsRetryMs = 1000;

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
    chartSymbol: document.getElementById("chart-symbol"),
    chartMeta: document.getElementById("chart-meta"),
    wsStatus: document.getElementById("ws-status"),
    activityFeed: document.getElementById("activity-feed"),
  };

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
    if (els.chartMeta) els.chartMeta.textContent = `${chartSymbol} · ${tv}`;
    // Optional candle meta for markers (non-blocking)
    try {
      const data = await fetchJson(
        `/api/market/ohlcv?symbol=${encodeURIComponent(chartSymbol)}&timeframe=1h&limit=200`
      );
      chartCandles = data.candles || [];
      if (chartEngine) {
        const markers = window.BeastCharts.buildSignalMarkers(
          chartCandles,
          lastMarkets,
          chartSymbol
        );
        chartEngine.setMarkers(markers);
        const market = lastMarkets.find((m) => m.symbol === chartSymbol);
        const pos = lastPositions.find((p) => p.symbol === chartSymbol);
        chartEngine.applyMarketRow(market, pos);
      }
      if (els.chartMeta && chartCandles.length) {
        els.chartMeta.textContent = `${chartSymbol} · ${tv} · ${chartCandles.length} bars`;
      }
    } catch (_) {
      /* TradingView widget remains the primary chart */
    }
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
    els.footerClock.textContent = `Stream ${msg.server_time || msg.ts || "—"} · cycle #${
      msg.cycle || 0
    }`;
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
    };
    marketWs.onmessage = (ev) => {
      try {
        handleMarketMessage(JSON.parse(ev.data));
      } catch (_) {
        /* ignore */
      }
    };
    marketWs.onclose = () => {
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
        <td data-label="Pair" class="font-semibold text-white">${m.symbol}</td>
        <td data-label="Price">${fmt(m.price || m.entry_price, (m.price || m.entry_price) >= 100 ? 2 : 4)}</td>
        <td data-label="AI Signal">${signalBadge(m.signal)}</td>
        <td data-label="Confidence">${fmt(m.confidence ?? m.confidence_score, 1)}%</td>
      </tr>`
      )
      .join("");
  }

  function renderPositions(portfolio) {
    const positions = portfolio.positions || [];
    els.posMeta.textContent = `${positions.length} open`;
    if (!positions.length) {
      els.positionsBody.innerHTML = `<tr><td colspan="7" class="empty">No open positions</td></tr>`;
      return;
    }
    els.positionsBody.innerHTML = positions
      .map((p) => {
        const upnl = Number(p.unrealized_pnl || 0);
        return `
      <tr class="fade-in">
        <td data-label="Symbol" class="font-semibold text-white">${p.symbol}</td>
        <td data-label="Side">${sideBadge(p.direction)}</td>
        <td data-label="Entry">${fmt(p.entry_price)}</td>
        <td data-label="Mark">${fmt(p.mark_price)}</td>
        <td data-label="SL">${fmt(p.stop_loss)}</td>
        <td data-label="TP">${fmt(p.take_profit)}</td>
        <td data-label="Live PnL" class="${pnlClass(upnl)}">${money(upnl)}</td>
      </tr>`;
      })
      .join("");
  }

  function renderHistory(payload) {
    const trades = payload.trades || [];
    els.historyMeta.textContent = `${payload.count || 0} total`;
    if (!trades.length) {
      els.historyBody.innerHTML = `<tr><td colspan="7" class="empty">No closed trades yet</td></tr>`;
      return;
    }
    els.historyBody.innerHTML = trades
      .slice(0, 20)
      .map((t) => {
        const pnl = Number(t.pnl_usd || 0);
        return `
      <tr class="fade-in">
        <td data-label="Time">${t.timestamp || "—"}</td>
        <td data-label="Pair">${t.pair || "—"}</td>
        <td data-label="Side">${sideBadge(t.direction)}</td>
        <td data-label="Entry">${fmt(t.entry_price)}</td>
        <td data-label="Exit">${fmt(t.exit_price)}</td>
        <td data-label="PnL" class="${pnlClass(pnl)}">${money(pnl)}</td>
        <td data-label="Reason">${t.exit_reason || "—"}</td>
      </tr>`;
      })
      .join("");
  }

  function renderStats(portfolio) {
    els.equity.textContent = money(portfolio.equity);
    els.wallet.textContent = `Wallet ${money(portfolio.wallet_balance)} · Avail ${money(
      portfolio.available_balance
    )}`;
    els.active.textContent = String(
      portfolio.open_positions ?? (portfolio.positions || []).length
    );
    els.dailyPnl.textContent = money(portfolio.daily_realized_pnl);
    els.dailyPnl.className = `stat-value ${pnlClass(portfolio.daily_realized_pnl)}`;
    els.realized.textContent = `All-time ${money(portfolio.realized_pnl)}`;
    els.winrate.textContent = `${fmt(portfolio.win_rate, 1)}%`;
    els.closed.textContent = `${portfolio.closed_trades || 0} closed trades`;
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
      const data = await fetchJson("/api/scanner/pairs?limit=50");
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
      const [sentiment, blogs, copy] = await Promise.all([
        fetchJson("/api/sentiment"),
        fetchJson("/api/seo/blogs?limit=20&generate=false"),
        fetchJson("/api/copy-trading/followers").catch(() => ({
          followers: [],
          follower_count: 0,
          total_master_commission: 0,
          total_follower_net_pnl: 0,
          profit_share_pct: 15,
        })),
      ]);
      renderSentiment(sentiment);
      renderSeo(blogs);
      renderCopy(copy);
    } catch (err) {
      console.error(err);
    }
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
    await loadUniverse().catch((err) => {
      els.watchMeta.textContent = `Using seeded top 50 · ${err.message}`;
    });
    populateChartSymbols([
      ...watchlist,
      ...SEED_TOP_50,
      ...universe.map((p) => p.symbol),
    ]);
    if (window.BeastCharts) {
      chartEngine = window.BeastCharts.createChartEngine("tv-chart");
    }
    chartSymbol = watchlist[0] || "BTC/USDT";
    if (els.chartSymbol) els.chartSymbol.value = chartSymbol;
    await loadChart(chartSymbol);
    connectMarketWs();
    connectBotWs();
    await refreshSecondary();
    if (tab === "billing") await loadBilling().catch(console.error);
    // Slow REST for non-stream panels; trading desk is WebSocket-driven
    setInterval(refreshSecondary, SLOW_REFRESH_MS);
    // Safety net if WS drops for an extended period
    setInterval(() => {
      if (!marketWs || marketWs.readyState !== WebSocket.OPEN) refresh();
    }, 8000);
  })();
})();
