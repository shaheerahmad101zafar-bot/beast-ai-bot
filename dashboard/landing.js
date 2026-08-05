(() => {
  const TOKEN_KEY = "beast_jwt";
  const pricingGrid = document.getElementById("pricing-grid");
  const authModal = document.getElementById("auth-modal");
  const authForm = document.getElementById("auth-form");
  const authTitle = document.getElementById("auth-title");
  const authSubmit = document.getElementById("auth-submit");
  const authError = document.getElementById("auth-error");
  const payHint = document.getElementById("land-pay-hint");
  let authMode = "signup";
  let payMethod = "stripe";
  let pendingTierCheckout = null;

  const money = (n) => {
    const x = Number(n);
    if (!Number.isFinite(x)) return "$—";
    const sign = x < 0 ? "-" : x > 0 ? "+" : "";
    return `${sign}$${Math.abs(x).toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  };

  async function fetchJson(url, options) {
    const res = await fetch(url, options);
    if (!res.ok) {
      let detail = `${url} ${res.status}`;
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

  function saveSession(token, user) {
    localStorage.setItem(TOKEN_KEY, token);
    if (user) localStorage.setItem("beast_user", JSON.stringify(user));
  }

  function syncAuthFields(mode) {
    const signup = mode === "signup";
    document.getElementById("signup-extra")?.classList.toggle("hidden", !signup);
    document.getElementById("confirm-wrap")?.classList.toggle("hidden", !signup);
    const confirm = document.getElementById("auth-confirm");
    const name = document.getElementById("auth-fullname");
    const phone = document.getElementById("auth-phone");
    const address = document.getElementById("auth-address");
    if (confirm) confirm.required = signup;
    if (name) name.required = signup;
    if (phone) phone.required = signup;
    if (address) address.required = signup;
    const pass = document.getElementById("auth-password");
    if (pass) pass.autocomplete = signup ? "new-password" : "current-password";
  }

  function openAuth(mode = "signup") {
    authMode = mode;
    authError.classList.add("hidden");
    authTitle.textContent = mode === "signup" ? "See what’s trading" : "Welcome back";
    const sub = document.getElementById("auth-subtitle");
    if (sub) {
      sub.textContent =
        mode === "signup"
          ? "Create your Beast AI desk · 7-day Pro trial"
          : "Log in to continue to your desk";
    }
    authSubmit.textContent = mode === "signup" ? "Create account" : "Continue";
    document.querySelectorAll(".auth-tab").forEach((tab) => {
      tab.classList.toggle("active", tab.dataset.authTab === mode);
    });
    syncAuthFields(mode);
    authModal.classList.remove("hidden");
    authModal.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
  }

  function closeAuth() {
    authModal.classList.add("hidden");
    authModal.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  async function startCheckout(tier) {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      pendingTierCheckout = tier;
      openAuth("signup");
      return;
    }
    if (payHint) payHint.textContent = "Creating checkout session…";
    try {
      const result = await fetchJson("/api/payments/create-checkout-session", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          tier,
          method: payMethod,
          pay_currency: "usdttrc20",
        }),
      });
      if (!result.checkout_url) throw new Error("No checkout URL");
      window.location.href = result.checkout_url;
    } catch (err) {
      if (String(err.message || "").includes("401") || String(err.message).includes("authenticated")) {
        pendingTierCheckout = tier;
        openAuth("login");
        return;
      }
      if (payHint) {
        payHint.textContent = err.message;
        payHint.style.color = "#f43f5e";
      }
    }
  }

  function renderPricing(tiers) {
    pricingGrid.innerHTML = tiers
      .map((t) => {
        const highlighted = t.highlighted ? "highlighted" : "";
        const features = (t.features || []).map((f) => `<li>${f}</li>`).join("");
        return `
      <article class="price-card ${highlighted}">
        <div class="price-name">${t.name}</div>
        <div class="price-amount">$${t.price_usd}<span>/${t.interval}</span></div>
        <p class="price-headline">${t.headline || ""}</p>
        <ul class="price-features">${features}</ul>
        <button type="button" class="cta-primary w-full price-cta" data-tier="${t.id}">Subscribe Now</button>
      </article>`;
      })
      .join("");

    document.querySelectorAll(".price-cta").forEach((btn) => {
      btn.addEventListener("click", () => startCheckout(btn.dataset.tier || "pro"));
    });
  }

  async function goAppIfAuthed() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
      openAuth("login");
      return;
    }
    try {
      await fetchJson("/api/auth/me", {
        headers: { Authorization: `Bearer ${token}` },
      });
      window.location.href = "/app";
    } catch (_) {
      localStorage.removeItem(TOKEN_KEY);
      openAuth("login");
    }
  }

  let cmsContent = null;
  let proPrice = 79;

  function applyHeroVideo(hero) {
    const video = document.getElementById("hero-video");
    const demo = document.getElementById("hero-svg-demo");
    if (!video || !demo) return;
    const url = String(hero?.video_url || "").trim();
    const poster = String(hero?.banner_poster || "").trim();
    if (url) {
      video.src = url;
      if (poster) video.poster = poster;
      video.classList.remove("hidden");
      demo.classList.add("hidden");
      video.play?.().catch(() => {});
    } else {
      video.removeAttribute("src");
      video.load?.();
      video.classList.add("hidden");
      demo.classList.remove("hidden");
    }
  }

  function applyCms(content) {
    cmsContent = content || {};
    const metaTitle = content.meta?.title;
    const metaDesc = content.meta?.description;
    if (metaTitle) document.title = metaTitle;
    const descTag = document.querySelector('meta[name="description"]');
    if (descTag && metaDesc) descTag.setAttribute("content", metaDesc);

    const brand = document.getElementById("hero-brand");
    const headline = document.getElementById("hero-headline");
    const sub = document.getElementById("hero-subheadline");
    const trial = document.getElementById("btn-trial");
    const launch = document.getElementById("btn-launch");
    if (brand && content.hero?.brand) brand.textContent = content.hero.brand;
    if (headline && content.hero?.headline) headline.textContent = content.hero.headline;
    if (sub && content.hero?.subheadline) sub.textContent = content.hero.subheadline;
    if (trial && content.hero?.cta_primary) trial.textContent = content.hero.cta_primary;
    if (launch && content.hero?.cta_secondary) launch.textContent = content.hero.cta_secondary;
    applyHeroVideo(content.hero || {});

    const servicesGrid = document.getElementById("services-grid");
    if (servicesGrid) {
      servicesGrid.innerHTML = (content.services || [])
        .map(
          (s) => `
        <article class="service-card">
          <h3>${s.title || ""}</h3>
          <p>${s.body || ""}</p>
        </article>`
        )
        .join("");
    }
    const featuresGrid = document.getElementById("features-grid");
    if (featuresGrid) {
      featuresGrid.innerHTML = (content.features || [])
        .map(
          (f) => `
        <article class="feature-chip">
          <strong>${f.title || ""}</strong>
          <span>${f.body || ""}</span>
        </article>`
        )
        .join("");
    }

    const tp = content.trustpilot || {};
    if (document.getElementById("tp-score")) {
      document.getElementById("tp-score").textContent = String(tp.rating ?? 4.8);
    }
    if (document.getElementById("tp-label")) {
      document.getElementById("tp-label").textContent = `${tp.label || "Excellent"} on Trustpilot`;
    }
    if (document.getElementById("tp-count")) {
      document.getElementById("tp-count").textContent = `Based on ${
        tp.reviews ?? 214
      } verified reviews (demo widget)`;
    }
    const quotes =
      Array.isArray(content.testimonials) && content.testimonials.length
        ? content.testimonials
        : tp.quotes || [];
    const reviewsGrid = document.getElementById("reviews-grid");
    if (reviewsGrid) {
      reviewsGrid.innerHTML = quotes
        .map(
          (q) => `
        <blockquote class="quote">
          <p>“${q.text || ""}”</p>
          <footer>— ${q.author || ""}</footer>
        </blockquote>`
        )
        .join("");
    }

    const faqList = document.getElementById("faq-list");
    if (faqList) {
      const faq = Array.isArray(content.faq) ? content.faq : [];
      faqList.innerHTML = faq
        .map(
          (item) => `
        <details>
          <summary>${item.question || ""}</summary>
          <p>${item.answer || ""}</p>
        </details>`
        )
        .join("");
    }

    const risk = document.getElementById("risk-disclaimer-text");
    if (risk && content.risk_disclaimer) risk.textContent = content.risk_disclaimer;
    const tosBody = document.getElementById("tos-body");
    if (tosBody) tosBody.textContent = content.terms_of_service || "";

    if (content.pricing_rates?.pro) proPrice = Number(content.pricing_rates.pro) || 79;

    if (content.site?.social && window.BeastSocial) {
      window.BeastSocial.renderInto("[data-social-links]", content.site.social);
    }
  }

  function startDemoLoop() {
    const signals = ["BTC LONG", "ETH LONG", "SOL SHORT", "BNB LONG"];
    const sentiments = ["62 Bullish", "58 Neutral", "41 Cautious", "71 Risk-On"];
    let i = 0;
    setInterval(() => {
      i = (i + 1) % signals.length;
      const sig = document.getElementById("hero-signal");
      const sent = document.getElementById("hero-sentiment");
      if (sig) sig.textContent = signals[i];
      if (sent) sent.textContent = sentiments[i];
    }, 3750);
  }

  function calcRoi() {
    const capital = Number(document.getElementById("roi-capital")?.value || 5000);
    const win = Number(document.getElementById("roi-winrate")?.value || 62) / 100;
    const edge = Number(document.getElementById("roi-edge")?.value || 1.8) / 100;
    const trades = 20;
    const expectancy = win * edge - (1 - win) * (edge * 0.75);
    const monthRet = capital * expectancy * trades;
    const quarterEq = capital * Math.pow(1 + expectancy * trades, 3);
    const payback =
      monthRet > 0 ? Math.max(1, Math.ceil(proPrice / monthRet)) : "—";
    const monthEl = document.getElementById("roi-month");
    const quarterEl = document.getElementById("roi-quarter");
    const paybackEl = document.getElementById("roi-payback");
    if (monthEl) monthEl.textContent = money(monthRet);
    if (quarterEl) {
      quarterEl.textContent = `$${quarterEq.toLocaleString(undefined, {
        maximumFractionDigits: 0,
      })}`;
    }
    if (paybackEl) {
      paybackEl.textContent = typeof payback === "number" ? `${payback} mo` : payback;
    }
  }

  function openTos() {
    const modal = document.getElementById("tos-modal");
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeTos() {
    const modal = document.getElementById("tos-modal");
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  async function hydrate() {
    try {
      const [pricing, portfolio, status, cms] = await Promise.all([
        fetchJson("/api/pricing"),
        fetchJson("/api/portfolio").catch(() => null),
        fetchJson("/api/status").catch(() => null),
        fetchJson("/api/cms/public").catch(() => null),
      ]);

      if (cms?.content) {
        const payload = { ...cms.content };
        if (cms.site) payload.site = cms.site;
        applyCms(payload);
      }
      if (window.BeastSocial) {
        window.BeastSocial.hydrate().catch(() => {});
      }
      renderPricing(pricing.tiers || []);
      calcRoi();

      const winRate = Number(portfolio?.win_rate);
      const equity = Number(portfolio?.equity);
      const daily = Number(portfolio?.daily_realized_pnl);
      const confAvg =
        (status?.markets || []).reduce((a, m) => a + Number(m.confidence || 0), 0) /
        Math.max(1, (status?.markets || []).length);

      document.getElementById("perf-winrate").textContent = `${(
        Number.isFinite(winRate) && winRate > 0 ? winRate : 71.4
      ).toFixed(1)}%`;
      document.getElementById("hero-winrate").textContent =
        document.getElementById("perf-winrate").textContent;

      const pnlShow = Number.isFinite(daily) && Math.abs(daily) > 0 ? daily * 30 : 18920;
      document.getElementById("perf-pnl").textContent = money(pnlShow);
      document.getElementById("perf-conf").textContent = `${(
        Number.isFinite(confAvg) && confAvg > 0 ? confAvg : 76
      ).toFixed(0)}%`;

      if (Number.isFinite(equity) && equity > 0) {
        document.getElementById("hero-equity").textContent = `$${equity.toLocaleString(
          undefined,
          { maximumFractionDigits: 0 }
        )}`;
      }
    } catch (err) {
      console.error(err);
      renderPricing([
        {
          name: "Starter",
          price_usd: 29,
          interval: "month",
          headline: "Solo traders validating AI signals",
          features: ["1 connected exchange", "Paper trading engine"],
          cta: "Start Free Trial",
        },
        {
          name: "Pro Trader",
          price_usd: 79,
          interval: "month",
          headline: "Active futures desks scaling edge",
          features: ["3 connected exchanges", "Copy trading"],
          cta: "Go Pro",
          highlighted: true,
        },
        {
          name: "Institutional VIP",
          price_usd: 199,
          interval: "month",
          headline: "Unlimited routing",
          features: ["Unlimited exchanges", "Priority Telegram"],
          cta: "Talk to Sales",
        },
      ]);
    }
  }

  document.getElementById("btn-login")?.addEventListener("click", () => openAuth("login"));
  document.getElementById("btn-signup")?.addEventListener("click", () => openAuth("signup"));
  document.getElementById("btn-trial")?.addEventListener("click", () => openAuth("signup"));
  document.getElementById("btn-launch")?.addEventListener("click", goAppIfAuthed);
  authModal.querySelectorAll("[data-close-auth]").forEach((el) => {
    el.addEventListener("click", closeAuth);
  });
  document.querySelectorAll(".auth-tab").forEach((tab) => {
    tab.addEventListener("click", () => openAuth(tab.dataset.authTab || "signup"));
  });

  authForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    authError.classList.add("hidden");
    authSubmit.disabled = true;
    const email = document.getElementById("auth-email").value.trim();
    const password = document.getElementById("auth-password").value;
    const endpoint = authMode === "signup" ? "/api/auth/signup" : "/api/auth/login";
    let payload = { email, password };
    if (authMode === "signup") {
      const confirm = document.getElementById("auth-confirm")?.value || "";
      if (password !== confirm) {
        authError.textContent = "Passwords do not match";
        authError.classList.remove("hidden");
        authSubmit.disabled = false;
        return;
      }
      payload = {
        email,
        password,
        confirm_password: confirm,
        full_name: document.getElementById("auth-fullname")?.value.trim() || "",
        phone: document.getElementById("auth-phone")?.value.trim() || "",
        address: document.getElementById("auth-address")?.value.trim() || "",
        country: document.getElementById("auth-country")?.value.trim() || "",
      };
    }
    try {
      const result = await fetchJson(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      saveSession(result.access_token, result.user);
      if (pendingTierCheckout) {
        const tier = pendingTierCheckout;
        pendingTierCheckout = null;
        await startCheckout(tier);
        return;
      }
      const next = new URLSearchParams(window.location.search).get("next");
      if (next === "/admin" && result.user?.is_admin) {
        window.location.href = "/admin";
        return;
      }
      window.location.href = next && next.startsWith("/") ? next : "/app";
    } catch (err) {
      authError.textContent = err.message || "Authentication failed";
      authError.classList.remove("hidden");
    } finally {
      authSubmit.disabled = false;
    }
  });

  document.querySelectorAll("[data-oauth]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.oauth;
      authError.classList.add("hidden");
      btn.disabled = true;
      try {
        const next = new URLSearchParams(window.location.search).get("next") || "/app";
        const data = await fetchJson(
          `/api/auth/oauth/${provider}/start?next=${encodeURIComponent(next)}`
        );
        if (!data.auth_url) throw new Error("OAuth unavailable");
        window.location.href = data.auth_url;
      } catch (err) {
        authError.textContent = err.message || "Social login failed";
        authError.classList.remove("hidden");
        btn.disabled = false;
      }
    });
  });

  document.getElementById("oauth-other-toggle")?.addEventListener("click", () => {
    const panel = document.getElementById("oauth-other");
    const toggle = document.getElementById("oauth-other-toggle");
    const label = document.getElementById("oauth-other-label");
    if (!panel || !toggle) return;
    const open = !panel.classList.toggle("hidden");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
    if (label) label.textContent = open ? "Hide" : "Other";
  });

  document.getElementById("nav-toggle")?.addEventListener("click", () => {
    const nav = document.getElementById("site-nav");
    const btn = document.getElementById("nav-toggle");
    if (!nav || !btn) return;
    const open = nav.classList.toggle("open");
    btn.setAttribute("aria-expanded", open ? "true" : "false");
  });

  document.querySelectorAll("#site-nav a, #site-nav button").forEach((el) => {
    el.addEventListener("click", () => {
      document.getElementById("site-nav")?.classList.remove("open");
      document.getElementById("nav-toggle")?.setAttribute("aria-expanded", "false");
    });
  });

  document.getElementById("btn-tos-auth")?.addEventListener("click", openTos);

  document.querySelectorAll(".pay-opt").forEach((btn) => {
    btn.addEventListener("click", () => {
      payMethod = btn.dataset.method || "stripe";
      document.querySelectorAll(".pay-opt").forEach((b) => {
        b.classList.toggle("active", b.dataset.method === payMethod);
      });
      if (payHint) {
        payHint.style.color = "";
        payHint.textContent =
          payMethod === "crypto"
            ? "Crypto checkout uses USDT TRC20 by default (BEP20 on /pricing)."
            : "Card checkout opens Stripe (mock URL if keys unset).";
      }
    });
  });

  ["roi-capital", "roi-winrate", "roi-edge"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", calcRoi);
  });
  document.getElementById("btn-tos")?.addEventListener("click", openTos);
  document.getElementById("btn-tos-footer")?.addEventListener("click", openTos);
  document.querySelectorAll("[data-close-tos]").forEach((el) => {
    el.addEventListener("click", closeTos);
  });

  const params = new URLSearchParams(window.location.search);
  const oauthToken = params.get("oauth_token");
  if (oauthToken) {
    localStorage.setItem(TOKEN_KEY, oauthToken);
    params.delete("oauth_token");
    const clean = `${window.location.pathname}${params.toString() ? `?${params}` : ""}`;
    window.history.replaceState({}, "", clean);
    window.location.href = params.get("next") || "/app";
  }
  if (params.get("auth") === "login" || params.get("auth") === "required") {
    openAuth("login");
  }
  if (params.get("denied") === "1") {
    openAuth("login");
    authError.textContent = "Admin privilege required. Sign in with an admin account.";
    authError.classList.remove("hidden");
  }

  startDemoLoop();
  syncAuthFields(authMode);
  hydrate();
})();
