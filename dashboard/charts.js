/**
 * Beast AI — TradingView Lightweight Charts engine
 * Candles, signal markers, SL/TP lines, live tick updates.
 */
(function (global) {
  function createChartEngine(containerId) {
    const el = document.getElementById(containerId);
    if (!el || typeof LightweightCharts === "undefined") {
      return null;
    }

    let chart = null;
    let candleSeries = null;
    let slLine = null;
    let tpLine = null;
    let entryLine = null;
    let symbol = "BTC/USDT";
    let markers = [];
    let flashEl = null;

    function ensure() {
      if (chart) return;
      chart = LightweightCharts.createChart(el, {
        layout: {
          background: { type: "solid", color: "rgba(7, 16, 24, 0.2)" },
          textColor: "#9DB4C4",
        },
        grid: {
          vertLines: { color: "rgba(30, 51, 68, 0.55)" },
          horzLines: { color: "rgba(30, 51, 68, 0.55)" },
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: "#1E3344" },
        timeScale: { borderColor: "#1E3344", timeVisible: true, secondsVisible: false },
        width: el.clientWidth,
        height: el.clientHeight || 360,
      });
      candleSeries = chart.addCandlestickSeries({
        upColor: "#2DD4BF",
        downColor: "#F43F5E",
        borderUpColor: "#2DD4BF",
        borderDownColor: "#F43F5E",
        wickUpColor: "#2DD4BF",
        wickDownColor: "#F43F5E",
      });
      window.addEventListener("resize", () => {
        if (chart && el) {
          chart.applyOptions({
            width: el.clientWidth,
            height: el.clientHeight || 280,
          });
        }
      });
    }

    function setSymbol(next) {
      symbol = next;
    }

    function loadCandles(candles) {
      ensure();
      if (!candleSeries || !candles?.length) return;
      const data = candles.map((c) => ({
        time: c.time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      }));
      candleSeries.setData(data);
      chart.timeScale().fitContent();
    }

    function updateLiveCandle(candle) {
      ensure();
      if (!candleSeries || !candle?.time) return;
      candleSeries.update({
        time: candle.time,
        open: candle.open,
        high: candle.high,
        low: candle.low,
        close: candle.close,
      });
    }

    function setMarkers(signalMarkers) {
      ensure();
      markers = signalMarkers || [];
      if (candleSeries) candleSeries.setMarkers(markers);
    }

    function setLevels({ stopLoss, takeProfit, entry } = {}) {
      ensure();
      if (!candleSeries) return;
      if (slLine) {
        candleSeries.removePriceLine(slLine);
        slLine = null;
      }
      if (tpLine) {
        candleSeries.removePriceLine(tpLine);
        tpLine = null;
      }
      if (entryLine) {
        candleSeries.removePriceLine(entryLine);
        entryLine = null;
      }
      if (stopLoss > 0) {
        slLine = candleSeries.createPriceLine({
          price: stopLoss,
          color: "#F43F5E",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: "SL",
        });
      }
      if (takeProfit > 0) {
        tpLine = candleSeries.createPriceLine({
          price: takeProfit,
          color: "#2DD4BF",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dashed,
          axisLabelVisible: true,
          title: "TP",
        });
      }
      if (entry > 0) {
        entryLine = candleSeries.createPriceLine({
          price: entry,
          color: "#F59E0B",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: "ENTRY",
        });
      }
    }

    function flashExecution(side, text) {
      if (!el) return;
      if (!flashEl) {
        flashEl = document.createElement("div");
        flashEl.className = "chart-exec-flash";
        el.appendChild(flashEl);
      }
      flashEl.textContent = text || (side === "BUY" || side === "LONG" ? "LONG FILLED" : "SHORT FILLED");
      flashEl.classList.remove("buy", "sell", "show");
      flashEl.classList.add(side === "BUY" || side === "LONG" ? "buy" : "sell");
      // retrigger animation
      void flashEl.offsetWidth;
      flashEl.classList.add("show");
    }

    function applyMarketRow(market, position) {
      if (!market) return;
      const sig = String(market.signal || "HOLD").toUpperCase();
      const lastTime = markers.length ? markers[markers.length - 1].time : undefined;
      // Keep historical markers; add new tip marker from latest signal if actionable
      if (sig === "BUY" || sig === "SELL") {
        // Marker time filled by caller with last candle time usually
      }
      setLevels({
        stopLoss: Number(market.stop_loss || position?.stop_loss || 0),
        takeProfit: Number(market.take_profit || position?.take_profit || 0),
        entry: Number(position?.entry_price || 0),
      });
    }

    return {
      setSymbol,
      loadCandles,
      updateLiveCandle,
      setMarkers,
      setLevels,
      flashExecution,
      applyMarketRow,
      getSymbol: () => symbol,
    };
  }

  function buildSignalMarkers(candles, markets, symbol) {
    if (!candles?.length || !markets?.length) return [];
    const m = markets.find((x) => x.symbol === symbol);
    if (!m) return [];
    const sig = String(m.signal || "HOLD").toUpperCase();
    if (sig !== "BUY" && sig !== "SELL") return [];
    const last = candles[candles.length - 1];
    return [
      {
        time: last.time,
        position: sig === "BUY" ? "belowBar" : "aboveBar",
        color: sig === "BUY" ? "#2DD4BF" : "#F43F5E",
        shape: sig === "BUY" ? "arrowUp" : "arrowDown",
        text: `${sig} ${Number(m.confidence || 0).toFixed(0)}%`,
      },
    ];
  }

  global.BeastCharts = { createChartEngine, buildSignalMarkers };
})(window);
