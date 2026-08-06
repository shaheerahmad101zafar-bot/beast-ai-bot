function clamp(v, a, b) {
  return Math.max(a, Math.min(b, v));
}

function sma(values, period) {
  const out = new Array(values.length).fill(null);
  let sum = 0;
  for (let i = 0; i < values.length; i += 1) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

function stdev(values, period, means) {
  const out = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i += 1) {
    const m = means[i];
    if (m == null) continue;
    let acc = 0;
    for (let j = i - period + 1; j <= i; j += 1) {
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
  for (let i = 1; i <= period; i += 1) {
    const ch = closes[i] - closes[i - 1];
    if (ch >= 0) avgGain += ch;
    else avgLoss -= ch;
  }
  avgGain /= period;
  avgLoss /= period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < closes.length; i += 1) {
    const ch = closes[i] - closes[i - 1];
    const gain = ch > 0 ? ch : 0;
    const loss = ch < 0 ? -ch : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

self.onmessage = (event) => {
  const msg = event.data || {};
  if (msg.type === "parse_ws") {
    try {
      self.postMessage({ id: msg.id, type: "parsed_ws", payload: JSON.parse(msg.raw || "{}") });
    } catch (_) {
      self.postMessage({ id: msg.id, type: "parsed_ws", payload: null });
    }
    return;
  }
  if (msg.type !== "compute_chart_state") return;
  const candles = Array.isArray(msg.candles) ? msg.candles.slice(-120) : [];
  const depth = msg.depth || { bids: [], asks: [] };
  const closes = candles.map((c) => Number(c.close || 0));
  const highs = candles.map((c) => Number(c.high || 0));
  const lows = candles.map((c) => Number(c.low || 0));
  const vols = candles.map((c) => Number(c.volume || 0));
  const ma20 = sma(closes, 20);
  const ma50 = sma(closes, 50);
  const bbMid = sma(closes, 20);
  const bbSd = stdev(closes, 20, bbMid);
  const rsi = rsiSeries(closes, 14);
  let minP = lows.length ? Math.min(...lows) : 0;
  let maxP = highs.length ? Math.max(...highs) : 1;
  for (let i = 0; i < candles.length; i += 1) {
    if (bbMid[i] != null && bbSd[i] != null) {
      minP = Math.min(minP, bbMid[i] - 2 * bbSd[i]);
      maxP = Math.max(maxP, bbMid[i] + 2 * bbSd[i]);
    }
  }
  const maxVol = Math.max(...vols, 1);
  const bidQty = depth.bids.reduce((acc, row) => acc + Number(row[1] || 0), 0);
  const askQty = depth.asks.reduce((acc, row) => acc + Number(row[1] || 0), 0);
  const obi = bidQty + askQty > 0 ? clamp(((bidQty - askQty) / (bidQty + askQty)) * 100, -100, 100) : 0;
  self.postMessage({
    type: "chart_state",
    state: {
      candles,
      ma20,
      ma50,
      bbMid,
      bbSd,
      rsi,
      minP,
      maxP,
      maxVol,
      obi,
      depth,
    },
  });
};
