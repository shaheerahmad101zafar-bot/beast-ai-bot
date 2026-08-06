/**
 * Beast Native Canvas Charting Engine
 * Worker-assisted indicators + requestAnimationFrame rendering.
 * Path: /static/js/beast-chart.js
 */
(function (global) {
  function clamp(v, a, b) {
    return Math.max(a, Math.min(b, v));
  }

  function createBeastChart(containerId, options) {
    const root = document.getElementById(containerId);
    if (!root) return null;

    const opts = {
      bg: "rgba(5,7,11,0.92)",
      up: "#00F5A0",
      down: "#F43F5E",
      grid: "rgba(0,217,246,0.08)",
      text: "#8B9BB0",
      ...options,
    };

    root.innerHTML = "";
    root.style.position = "relative";
    const canvas = document.createElement("canvas");
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.display = "block";
    canvas.style.touchAction = "pan-x pan-y";
    root.appendChild(canvas);
    const ctx = canvas.getContext("2d");
    const worker =
      typeof Worker !== "undefined" ? new Worker("/static/js/chart-worker.js") : null;

    let candles = [];
    let depth = { bids: [], asks: [] };
    let derived = {
      candles: [],
      ma20: [],
      ma50: [],
      bbMid: [],
      bbSd: [],
      rsi: [],
      minP: 0,
      maxP: 1,
      maxVol: 1,
      obi: 0,
      depth,
    };
    let symbol = "BTC/USDT";
    let showMA = true;
    let showBB = true;
    let showRSI = true;
    let showDepth = true;
    let flash = null;
    let framePending = false;

    if (worker) {
      worker.onmessage = (event) => {
        const msg = event.data || {};
        if (msg.type === "chart_state" && msg.state) {
          derived = msg.state;
          scheduleDraw();
        }
      };
    }

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = root.clientWidth || 640;
      const h = root.clientHeight || 360;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      scheduleDraw();
    }

    function setSymbol(next) {
      symbol = next || symbol;
      scheduleDraw();
    }

    function loadCandles(rows) {
      candles = (rows || []).map((c) => ({
        time: c.time,
        open: +c.open,
        high: +c.high,
        low: +c.low,
        close: +c.close,
        volume: +(c.volume || 0),
      }));
      scheduleCompute();
    }

    function updateLiveCandle(c) {
      if (!c || c.time == null) return;
      const row = {
        time: c.time,
        open: +c.open,
        high: +c.high,
        low: +c.low,
        close: +c.close,
        volume: +(c.volume || 0),
      };
      if (!candles.length) {
        candles.push(row);
      } else {
        const last = candles[candles.length - 1];
        if (last.time === row.time) candles[candles.length - 1] = row;
        else if (row.time > last.time) candles.push(row);
      }
      if (candles.length > 500) candles = candles.slice(-500);
      scheduleCompute();
    }

    function setDepth(book) {
      depth = {
        bids: (book?.bids || []).slice(0, 24),
        asks: (book?.asks || []).slice(0, 24),
      };
      scheduleCompute();
    }

    function setMarkers() {}
    function setLevels() {}
    function applyMarketRow() {}

    function flashExecution(side, text) {
      flash = {
        side,
        text: text || (side === "BUY" || side === "LONG" ? "LONG" : "SHORT"),
        until: performance.now() + 900,
      };
      scheduleDraw();
    }

    function scheduleCompute() {
      if (worker) {
        worker.postMessage({ type: "compute_chart_state", candles, depth, symbol });
      } else {
        derived = { ...derived, candles: candles.slice(-120), depth };
      }
      scheduleDraw();
    }

    function scheduleDraw() {
      if (framePending) return;
      framePending = true;
      requestAnimationFrame(() => {
        framePending = false;
        draw();
      });
    }

    function draw() {
      const w = root.clientWidth || 640;
      const h = root.clientHeight || 360;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = opts.bg;
      ctx.fillRect(0, 0, w, h);

      const padL = 8;
      const padR = 56;
      const padT = 28;
      const rsiH = showRSI ? Math.floor(h * 0.18) : 0;
      const volH = Math.floor(h * 0.14);
      const chartB = h - rsiH - 8;
      const priceH = chartB - padT - volH - 8;
      const priceTop = padT;
      const volTop = padT + priceH + 4;
      const rsiTop = chartB + 4;

      // grid
      ctx.strokeStyle = opts.grid;
      ctx.lineWidth = 1;
      for (let i = 0; i < 5; i++) {
        const y = priceTop + (priceH * i) / 4;
        ctx.beginPath();
        ctx.moveTo(padL, y);
        ctx.lineTo(w - padR, y);
        ctx.stroke();
      }

      ctx.fillStyle = opts.text;
      ctx.font = "11px JetBrains Mono, monospace";
      ctx.fillText(`BEAST NATIVE · ${symbol}`, padL + 4, 16);

      if (!candles.length) {
        ctx.fillText("Awaiting OHLCV…", padL + 4, priceTop + 24);
        return;
      }

      const view = derived.candles.length ? derived.candles : candles.slice(-120);
      const ma20 = derived.ma20 || [];
      const ma50 = derived.ma50 || [];
      const bbMid = derived.bbMid || [];
      const bbSd = derived.bbSd || [];
      const rsi = derived.rsi || [];
      const minP = derived.minP ?? 0;
      const maxP = derived.maxP ?? 1;
      const maxVol = derived.maxVol ?? 1;
      const span = maxP - minP || 1;
      const slot = (w - padL - padR) / view.length;
      const bodyW = clamp(slot * 0.62, 2, 14);

      const yPrice = (p) => priceTop + ((maxP - p) / span) * priceH;

      // depth tint
      if (showDepth && (derived.depth.bids.length || derived.depth.asks.length)) {
        const mid = view[view.length - 1]?.close || 0;
        derived.depth.bids.forEach((b, i) => {
          const p = +b[0] || mid * (1 - i * 0.001);
          const y = yPrice(p);
          ctx.fillStyle = `rgba(0,245,160,${0.04 + (1 - i / 24) * 0.05})`;
          ctx.fillRect(padL, y, w - padL - padR, 3);
        });
        derived.depth.asks.forEach((a, i) => {
          const p = +a[0] || mid * (1 + i * 0.001);
          const y = yPrice(p);
          ctx.fillStyle = `rgba(244,63,94,${0.04 + (1 - i / 24) * 0.05})`;
          ctx.fillRect(padL, y, w - padL - padR, 3);
        });
      }

      // Bollinger
      if (showBB) {
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < view.length; i++) {
          if (bbMid[i] == null || bbSd[i] == null) continue;
          const x = padL + i * slot + slot / 2;
          const y = yPrice(bbMid[i] + 2 * bbSd[i]);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else ctx.lineTo(x, y);
        }
        for (let i = view.length - 1; i >= 0; i--) {
          if (bbMid[i] == null || bbSd[i] == null) continue;
          const x = padL + i * slot + slot / 2;
          ctx.lineTo(x, yPrice(bbMid[i] - 2 * bbSd[i]));
        }
        ctx.closePath();
        ctx.fillStyle = "rgba(0,217,246,0.06)";
        ctx.fill();
      }

      // candles + volume
      for (let i = 0; i < view.length; i++) {
        const c = view[i];
        const x = padL + i * slot + slot / 2;
        const up = c.close >= c.open;
        ctx.strokeStyle = up ? opts.up : opts.down;
        ctx.fillStyle = up ? opts.up : opts.down;
        ctx.beginPath();
        ctx.moveTo(x, yPrice(c.high));
        ctx.lineTo(x, yPrice(c.low));
        ctx.stroke();
        const y1 = yPrice(Math.max(c.open, c.close));
        const y2 = yPrice(Math.min(c.open, c.close));
        ctx.fillRect(x - bodyW / 2, y1, bodyW, Math.max(1, y2 - y1));

        const vh = (c.volume / maxVol) * volH;
        ctx.globalAlpha = 0.45;
        ctx.fillRect(x - bodyW / 2, volTop + volH - vh, bodyW, vh);
        ctx.globalAlpha = 1;
      }

      function strokeSeries(series, color) {
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < series.length; i++) {
          if (series[i] == null) continue;
          const x = padL + i * slot + slot / 2;
          const y = yPrice(series[i]);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.4;
        ctx.stroke();
      }
      if (showMA) {
        strokeSeries(ma20, "#00D9F6");
        strokeSeries(ma50, "#F59E0B");
      }

      // price labels
      ctx.fillStyle = opts.text;
      ctx.font = "10px JetBrains Mono, monospace";
      ctx.fillText(maxP.toFixed(maxP >= 100 ? 2 : 4), w - padR + 4, priceTop + 10);
      ctx.fillText(minP.toFixed(minP >= 100 ? 2 : 4), w - padR + 4, priceTop + priceH);
      const last = view[view.length - 1];
      ctx.fillStyle = last.close >= last.open ? opts.up : opts.down;
      ctx.fillText(last.close.toFixed(last.close >= 100 ? 2 : 4), w - padR + 4, yPrice(last.close));
      ctx.fillStyle = opts.text;
      ctx.fillText(`OBI ${Number(derived.obi || 0).toFixed(1)}%`, w - padR + 4, priceTop + 26);

      // RSI pane
      if (showRSI && rsiH > 40) {
        ctx.strokeStyle = opts.grid;
        ctx.strokeRect(padL, rsiTop, w - padL - padR, rsiH - 4);
        const yR = (v) => rsiTop + ((100 - v) / 100) * (rsiH - 4);
        ctx.strokeStyle = "rgba(245,158,11,0.35)";
        ctx.beginPath();
        ctx.moveTo(padL, yR(70));
        ctx.lineTo(w - padR, yR(70));
        ctx.moveTo(padL, yR(30));
        ctx.lineTo(w - padR, yR(30));
        ctx.stroke();
        ctx.beginPath();
        let started = false;
        for (let i = 0; i < rsi.length; i++) {
          if (rsi[i] == null) continue;
          const x = padL + i * slot + slot / 2;
          const y = yR(rsi[i]);
          if (!started) {
            ctx.moveTo(x, y);
            started = true;
          } else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = "#00F5A0";
        ctx.lineWidth = 1.3;
        ctx.stroke();
        ctx.fillStyle = opts.text;
        ctx.fillText("RSI", padL + 4, rsiTop + 12);
      }

      if (flash && performance.now() < flash.until) {
        ctx.fillStyle =
          flash.side === "BUY" || flash.side === "LONG"
            ? "rgba(0,245,160,0.85)"
            : "rgba(244,63,94,0.85)";
        ctx.font = "bold 14px Plus Jakarta Sans, sans-serif";
        ctx.fillText(flash.text, w / 2 - 40, priceTop + 36);
      } else {
        flash = null;
      }
    }

    window.addEventListener("resize", resize);
    resize();

    return {
      setSymbol,
      loadCandles,
      updateLiveCandle,
      setDepth,
      setMarkers,
      setLevels,
      flashExecution,
      applyMarketRow,
      getSymbol: () => symbol,
      setOverlays: (flags) => {
        if (flags.ma != null) showMA = !!flags.ma;
        if (flags.bb != null) showBB = !!flags.bb;
        if (flags.rsi != null) showRSI = !!flags.rsi;
        if (flags.depth != null) showDepth = !!flags.depth;
        scheduleCompute();
      },
      redraw: scheduleDraw,
      engine: "beast-native",
    };
  }

  if (typeof Worker !== "undefined") {
    const workerProto = Worker.prototype;
    if (workerProto && !workerProto.__beastPatched) {
      workerProto.__beastPatched = true;
    }
  }

  global.BeastNativeChart = { createBeastChart };
})(window);
