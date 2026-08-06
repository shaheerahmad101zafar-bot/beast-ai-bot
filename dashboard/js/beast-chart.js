/**
 * Beast Native Canvas Charting Engine
 * Candlesticks, volume, MA/BB/RSI overlays, order-book depth tint.
 * Path: /static/js/beast-chart.js
 */
(function (global) {
  function clamp(v, a, b) {
    return Math.max(a, Math.min(b, v));
  }

  function sma(values, period) {
    const out = new Array(values.length).fill(null);
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += values[i];
      if (i >= period) sum -= values[i - period];
      if (i >= period - 1) out[i] = sum / period;
    }
    return out;
  }

  function stdev(values, period, means) {
    const out = new Array(values.length).fill(null);
    for (let i = period - 1; i < values.length; i++) {
      const m = means[i];
      if (m == null) continue;
      let acc = 0;
      for (let j = i - period + 1; j <= i; j++) {
        const d = values[j] - m;
        acc += d * d;
      }
      out[i] = Math.sqrt(acc / period);
    }
    return out;
  }

  function rsiSeries(closes, period) {
    const out = new Array(closes.length).fill(null);
    if (closes.length < period + 1) return out;
    let avgGain = 0;
    let avgLoss = 0;
    for (let i = 1; i <= period; i++) {
      const ch = closes[i] - closes[i - 1];
      if (ch >= 0) avgGain += ch;
      else avgLoss -= ch;
    }
    avgGain /= period;
    avgLoss /= period;
    out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    for (let i = period + 1; i < closes.length; i++) {
      const ch = closes[i] - closes[i - 1];
      const gain = ch > 0 ? ch : 0;
      const loss = ch < 0 ? -ch : 0;
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
    return out;
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
    root.appendChild(canvas);
    const ctx = canvas.getContext("2d");

    let candles = [];
    let depth = { bids: [], asks: [] };
    let symbol = "BTC/USDT";
    let showMA = true;
    let showBB = true;
    let showRSI = true;
    let showDepth = true;
    let flash = null;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const w = root.clientWidth || 640;
      const h = root.clientHeight || 360;
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      draw();
    }

    function setSymbol(next) {
      symbol = next || symbol;
      draw();
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
      draw();
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
      draw();
    }

    function setDepth(book) {
      depth = {
        bids: (book?.bids || []).slice(0, 24),
        asks: (book?.asks || []).slice(0, 24),
      };
      draw();
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
      draw();
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

      const view = candles.slice(-120);
      const closes = view.map((c) => c.close);
      const highs = view.map((c) => c.high);
      const lows = view.map((c) => c.low);
      const vols = view.map((c) => c.volume);
      const ma20 = sma(closes, 20);
      const ma50 = sma(closes, 50);
      const bbMid = sma(closes, 20);
      const bbSd = stdev(closes, 20, bbMid);
      const rsi = rsiSeries(closes, 14);

      let minP = Math.min(...lows);
      let maxP = Math.max(...highs);
      if (showBB) {
        for (let i = 0; i < view.length; i++) {
          if (bbMid[i] != null && bbSd[i] != null) {
            minP = Math.min(minP, bbMid[i] - 2 * bbSd[i]);
            maxP = Math.max(maxP, bbMid[i] + 2 * bbSd[i]);
          }
        }
      }
      const span = maxP - minP || 1;
      const maxVol = Math.max(...vols, 1);
      const slot = (w - padL - padR) / view.length;
      const bodyW = clamp(slot * 0.62, 2, 14);

      const yPrice = (p) => priceTop + ((maxP - p) / span) * priceH;

      // depth tint
      if (showDepth && (depth.bids.length || depth.asks.length)) {
        const mid = closes[closes.length - 1];
        depth.bids.forEach((b, i) => {
          const p = +b[0] || mid * (1 - i * 0.001);
          const y = yPrice(p);
          ctx.fillStyle = `rgba(0,245,160,${0.04 + (1 - i / 24) * 0.05})`;
          ctx.fillRect(padL, y, w - padL - padR, 3);
        });
        depth.asks.forEach((a, i) => {
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
        draw();
      },
      redraw: draw,
      engine: "beast-native",
    };
  }

  global.BeastNativeChart = { createBeastChart };
})(window);
