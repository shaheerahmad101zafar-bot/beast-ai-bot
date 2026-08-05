/**
 * Beast AI — Official TradingView embed widget (dark theme).
 * Symbol format: BINANCE:BTCUSDT
 */
(function (global) {
  function toTradingViewSymbol(symbol) {
    const raw = String(symbol || "BTC/USDT")
      .trim()
      .toUpperCase()
      .replace(/[-_]/g, "/")
      .replace(/\s+/g, "");
    const compact = raw.includes("/")
      ? raw.replace("/", "")
      : raw.endsWith("USDT")
        ? raw
        : `${raw}USDT`;
    return `BINANCE:${compact}`;
  }

  function createChartEngine(containerId) {
    const el = document.getElementById(containerId);
    if (!el) return null;

    let widget = null;
    let symbol = "BTC/USDT";
    let tvSymbol = toTradingViewSymbol(symbol);
    let ready = false;
    let pendingSymbol = null;
    let flashEl = null;

    function mount(nextTvSymbol) {
      tvSymbol = nextTvSymbol || tvSymbol;
      el.innerHTML = "";
      ready = false;

      if (typeof TradingView === "undefined" || !TradingView.widget) {
        el.innerHTML =
          '<div class="tv-fallback">TradingView failed to load. Check network / ad blockers.</div>';
        return;
      }

      widget = new TradingView.widget({
        autosize: true,
        symbol: tvSymbol,
        interval: "60",
        timezone: "Etc/UTC",
        theme: "dark",
        style: "1",
        locale: "en",
        toolbar_bg: "#0E1A24",
        enable_publishing: false,
        allow_symbol_change: true,
        hide_side_toolbar: false,
        withdateranges: true,
        details: false,
        hotlist: false,
        calendar: false,
        container_id: containerId,
        backgroundColor: "rgba(7, 16, 24, 0.85)",
        gridColor: "rgba(30, 51, 68, 0.55)",
      });

      if (widget && typeof widget.onChartReady === "function") {
        widget.onChartReady(() => {
          ready = true;
          if (pendingSymbol) {
            const next = pendingSymbol;
            pendingSymbol = null;
            applySymbol(next);
          }
        });
      } else {
        ready = true;
      }
    }

    function applySymbol(next) {
      symbol = next || symbol;
      const mapped = toTradingViewSymbol(symbol);
      tvSymbol = mapped;
      if (!widget || !ready) {
        pendingSymbol = symbol;
        if (!widget) mount(mapped);
        return;
      }
      try {
        const chart =
          (typeof widget.activeChart === "function" && widget.activeChart()) ||
          (typeof widget.chart === "function" && widget.chart());
        if (chart && typeof chart.setSymbol === "function") {
          chart.setSymbol(mapped);
          return;
        }
      } catch (_) {
        /* recreate below */
      }
      mount(mapped);
    }

    function setSymbol(next) {
      applySymbol(next);
    }

    function flashExecution(side, text) {
      if (!el) return;
      if (!flashEl) {
        flashEl = document.createElement("div");
        flashEl.className = "chart-exec-flash";
        el.appendChild(flashEl);
      }
      flashEl.textContent =
        text || (side === "BUY" || side === "LONG" ? "LONG FILLED" : "SHORT FILLED");
      flashEl.classList.remove("buy", "sell", "show");
      flashEl.classList.add(side === "BUY" || side === "LONG" ? "buy" : "sell");
      void flashEl.offsetWidth;
      flashEl.classList.add("show");
    }

    // Compatibility stubs — TradingView owns candles/markers.
    function loadCandles() {}
    function updateLiveCandle() {}
    function setMarkers() {}
    function setLevels() {}
    function applyMarketRow() {}

    mount(tvSymbol);

    return {
      setSymbol,
      loadCandles,
      updateLiveCandle,
      setMarkers,
      setLevels,
      flashExecution,
      applyMarketRow,
      getSymbol: () => symbol,
      toTradingViewSymbol,
    };
  }

  function buildSignalMarkers() {
    return [];
  }

  global.BeastCharts = {
    createChartEngine,
    buildSignalMarkers,
    toTradingViewSymbol,
  };
})(window);
