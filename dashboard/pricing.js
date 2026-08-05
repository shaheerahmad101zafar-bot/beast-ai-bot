(() => {
  const TOKEN_KEY = "beast_jwt";
  let method = "stripe";
  const grid = document.getElementById("pricing-grid");
  const statusEl = document.getElementById("pay-status");
  const networkEl = document.getElementById("crypto-network");

  async function fetchJson(url, options = {}) {
    const token = localStorage.getItem(TOKEN_KEY);
    const headers = {
      ...(options.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401) {
      window.location.href = "/?auth=login";
      throw new Error("Login required for checkout");
    }
    if (!res.ok) {
      let detail = `${url} ${res.status}`;
      try {
        const body = await res.json();
        if (body.detail) detail = body.detail;
      } catch (_) {
        /* ignore */
      }
      throw new Error(detail);
    }
    return res.json();
  }

  function setMethod(next) {
    method = next;
    document.querySelectorAll(".pay-opt").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.method === method);
    });
    networkEl.classList.toggle("hidden", method !== "crypto");
  }

  function renderPricing(tiers) {
    grid.innerHTML = tiers
      .map((t) => {
        const highlighted = t.highlighted ? "highlighted" : "";
        const features = (t.features || []).map((f) => `<li>${f}</li>`).join("");
        return `
      <article class="price-card ${highlighted}">
        <div class="price-name">${t.name}</div>
        <div class="price-amount">$${t.price_usd}<span>/${t.interval}</span></div>
        <p class="price-headline">${t.headline || ""}</p>
        <ul class="price-features">${features}</ul>
        <button type="button" class="cta-primary w-full subscribe-btn" data-tier="${t.id}">
          Subscribe Now
        </button>
      </article>`;
      })
      .join("");

    document.querySelectorAll(".subscribe-btn").forEach((btn) => {
      btn.addEventListener("click", () => startCheckout(btn.dataset.tier, btn));
    });
  }

  async function startCheckout(tier, btn) {
    const label = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Creating session…";
    try {
      const body = {
        tier,
        method,
        pay_currency: networkEl.value || "usdttrc20",
      };
      const result = await fetchJson("/api/payments/create-checkout-session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!result.checkout_url) throw new Error("No checkout URL returned");
      window.location.href = result.checkout_url;
    } catch (err) {
      statusEl.textContent = err.message;
      statusEl.style.color = "#f43f5e";
      btn.disabled = false;
      btn.textContent = label;
    }
  }

  document.querySelectorAll(".pay-opt").forEach((btn) => {
    btn.addEventListener("click", () => setMethod(btn.dataset.method));
  });

  (async () => {
    try {
      const [pricing, payStatus] = await Promise.all([
        fetchJson("/api/pricing"),
        fetchJson("/api/payments/status"),
      ]);
      renderPricing(pricing.tiers || []);
      statusEl.textContent = `Stripe: ${payStatus.stripe_mode} · Crypto: ${payStatus.crypto_mode}`;
    } catch (err) {
      statusEl.textContent = err.message;
      statusEl.style.color = "#f43f5e";
    }
  })();
})();
