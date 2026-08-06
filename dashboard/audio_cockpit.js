(() => {
  const TOKEN_KEY = "beast_jwt";
  const state = {
    enabled: false,
    lastRiskKey: "",
    lastTradeKey: "",
    lastPnlKey: "",
  };

  function authHeaders() {
    const token = localStorage.getItem(TOKEN_KEY);
    return token ? { Authorization: `Bearer ${token}` } : {};
  }

  async function fetchJson(url) {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) throw new Error(String(res.status));
    return res.json();
  }

  function speak(text) {
    if (!state.enabled || !("speechSynthesis" in window) || !text) return;
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 1.03;
    u.pitch = 0.95;
    u.volume = 0.9;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(u);
  }

  function ensureButton() {
    if (document.getElementById("audio-cockpit-toggle")) return;
    const btn = document.createElement("button");
    btn.id = "audio-cockpit-toggle";
    btn.className = "action-btn secondary";
    btn.style.position = "fixed";
    btn.style.right = "16px";
    btn.style.bottom = "16px";
    btn.style.zIndex = "60";
    btn.textContent = "Audio Tactical Cockpit: OFF";
    btn.addEventListener("click", () => {
      state.enabled = !state.enabled;
      btn.textContent = `Audio Tactical Cockpit: ${state.enabled ? "ON" : "OFF"}`;
      if (state.enabled) {
        speak("Beast AI audio tactical cockpit online.");
      } else if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    });
    document.body.appendChild(btn);
  }

  async function poll() {
    if (!state.enabled) return;
    try {
      const [quant, portfolio, status] = await Promise.all([
        fetchJson("/api/quant/snapshot?symbol=BTC%2FUSDT"),
        fetchJson("/api/portfolio"),
        fetchJson("/api/status"),
      ]);
      const macro = quant.macro_guard || {};
      const liq = quant.liquidation_hunter || {};
      const riskKey = `${macro.label}:${liq.last_cluster?.symbol || ""}:${liq.last_cluster?.cluster_notional_usd || 0}`;
      if (riskKey !== state.lastRiskKey) {
        state.lastRiskKey = riskKey;
        if (macro.label === "shock") {
          speak(`Macro shock guard active. DXY and S and P turbulence detected. Hedge posture engaged.`);
        } else if (liq.last_cluster?.symbol) {
          speak(`Liquidation cluster detected on ${liq.last_cluster.symbol}. Bounce order bias ${liq.last_cluster.bounce_bias}.`);
        }
      }
      const positions = portfolio.positions || [];
      const tradeKey = positions.map((p) => `${p.symbol}:${p.direction}`).join("|");
      if (tradeKey && tradeKey !== state.lastTradeKey) {
        state.lastTradeKey = tradeKey;
        speak(`Active trade update. ${positions.length} live position${positions.length === 1 ? "" : "s"} on desk.`);
      }
      const pnlKey = `${Math.round(Number(portfolio.daily_realized_pnl || 0))}:${Math.round(Number(portfolio.realized_pnl || 0))}`;
      if (pnlKey !== state.lastPnlKey) {
        state.lastPnlKey = pnlKey;
        if (Number(portfolio.daily_realized_pnl || 0) > 0) {
          speak(`Daily profit is now ${Math.round(Number(portfolio.daily_realized_pnl))} dollars.`);
        }
      }
      const council = (status.markets || []).find((m) => m.council?.approved);
      if (council) {
        speak(`AI council approved ${council.signal} setup on ${council.symbol}.`);
      }
    } catch (_) {
      /* ignore */
    }
  }

  ensureButton();
  setInterval(poll, 15000);
})();
