(() => {
  const TOKEN_KEY = "beast_jwt";
  const els = {
    meta: document.getElementById("admin-meta"),
    users: document.getElementById("stat-users"),
    paid: document.getElementById("stat-paid"),
    mrr: document.getElementById("stat-mrr"),
    copy: document.getElementById("stat-copy"),
    usersBody: document.getElementById("users-body"),
    usersMeta: document.getElementById("users-meta"),
    paymentsBody: document.getElementById("payments-body"),
    paymentsMeta: document.getElementById("payments-meta"),
    movementsBody: document.getElementById("movements-body"),
    movementsMeta: document.getElementById("movements-meta"),
    cmsMeta: document.getElementById("cms-meta"),
    cmsStatus: document.getElementById("cms-status"),
    cmsForm: document.getElementById("cms-form"),
    healthMeta: document.getElementById("health-meta"),
    healthCpu: document.getElementById("health-cpu"),
    healthMem: document.getElementById("health-mem"),
    healthWs: document.getElementById("health-ws"),
    healthDb: document.getElementById("health-db"),
    gaugeCpu: document.getElementById("gauge-cpu"),
    gaugeMem: document.getElementById("gauge-mem"),
    gaugeWs: document.getElementById("gauge-ws"),
    gaugeDb: document.getElementById("gauge-db"),
    backupMeta: document.getElementById("backup-meta"),
    gatewaysForm: document.getElementById("gateways-form"),
    gatewaysStatus: document.getElementById("gateways-status"),
    socialForm: document.getElementById("social-form"),
    socialStatus: document.getElementById("social-status"),
  };

  const LIST_SPECS = {
    features: {
      mount: "cms-features-list",
      fields: [
        { key: "title", label: "Title", type: "text" },
        { key: "body", label: "Body", type: "textarea" },
      ],
      blank: () => ({ title: "", body: "" }),
    },
    testimonials: {
      mount: "cms-testimonials-list",
      fields: [
        { key: "text", label: "Quote", type: "textarea" },
        { key: "author", label: "Author", type: "text" },
      ],
      blank: () => ({ text: "", author: "" }),
    },
    faq: {
      mount: "cms-faq-list",
      fields: [
        { key: "question", label: "Question", type: "text" },
        { key: "answer", label: "Answer", type: "textarea" },
      ],
      blank: () => ({ question: "", answer: "" }),
    },
  };

  const listState = {
    features: [],
    testimonials: [],
    faq: [],
  };

  const money = (n) => {
    const x = Number(n);
    if (!Number.isFinite(x)) return "$—";
    return `$${x.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
  };

  async function fetchJson(url, options = {}) {
    const token = localStorage.getItem(TOKEN_KEY);
    const headers = {
      ...(options.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    const res = await fetch(url, { ...options, headers });
    if (res.status === 401 || res.status === 403) {
      window.location.href = "/?auth=login&next=/admin";
      throw new Error("Admin auth required");
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

  function statusBadge(status) {
    const s = String(status || "trialing").toLowerCase();
    const cls =
      s === "active" ? "badge-active" : s === "canceled" || s === "expired" ? "badge-canceled" : "badge-trialing";
    return `<span class="badge ${cls}">${s}</span>`;
  }

  function escapeAttr(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
  }

  function renderList(kind) {
    const spec = LIST_SPECS[kind];
    const mount = document.getElementById(spec.mount);
    if (!mount) return;
    const rows = listState[kind] || [];
    if (!rows.length) {
      mount.innerHTML = `<p class="text-sm text-mist">No items yet. Click + Add.</p>`;
      return;
    }
    mount.innerHTML = rows
      .map((row, idx) => {
        const fields = spec.fields
          .map((f) => {
            const val = escapeAttr(row[f.key] || "");
            if (f.type === "textarea") {
              return `<label><span>${f.label}</span><textarea data-list="${kind}" data-idx="${idx}" data-key="${f.key}" rows="2">${val}</textarea></label>`;
            }
            return `<label><span>${f.label}</span><input type="text" data-list="${kind}" data-idx="${idx}" data-key="${f.key}" value="${val}" /></label>`;
          })
          .join("");
        return `
      <div class="crud-item" data-kind="${kind}" data-idx="${idx}">
        ${fields}
        <div class="crud-actions">
          <button type="button" class="admin-btn secondary" data-remove-list="${kind}" data-idx="${idx}">Delete</button>
        </div>
      </div>`;
      })
      .join("");
  }

  function syncListFromDom(kind) {
    const spec = LIST_SPECS[kind];
    const next = (listState[kind] || []).map((row, idx) => {
      const out = { ...row };
      spec.fields.forEach((f) => {
        const el = document.querySelector(
          `[data-list="${kind}"][data-idx="${idx}"][data-key="${f.key}"]`
        );
        if (el) out[f.key] = el.value.trim();
      });
      return out;
    });
    listState[kind] = next;
  }

  function renderStats(stats) {
    els.users.textContent = String(stats.total_users ?? 0);
    els.paid.textContent = String(stats.active_paid_subscribers ?? 0);
    els.mrr.textContent = money(stats.monthly_revenue_usd);
    els.copy.textContent = String(stats.active_copy_traders ?? 0);
  }

  function renderUsers(users) {
    els.usersMeta.textContent = `${users.length} accounts`;
    if (!users.length) {
      els.usersBody.innerHTML = `<tr><td colspan="9" class="empty">No users yet</td></tr>`;
      return;
    }
    els.usersBody.innerHTML = users
      .map(
        (u) => `
      <tr>
        <td>
          <div class="font-semibold text-white">${u.full_name || "—"}</div>
          <div>${u.email}${u.is_admin ? ' <span class="badge badge-active">ADMIN</span>' : ""}</div>
        </td>
        <td>${u.phone || "—"}</td>
        <td>${u.address || "—"}${u.country ? `<div class="text-mist">${u.country}</div>` : ""}</td>
        <td>${String(u.auth_provider || "email").toUpperCase()}</td>
        <td>${u.joined_at ? new Date(u.joined_at).toLocaleDateString() : "—"}</td>
        <td>${u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "—"}</td>
        <td>${String(u.plan || "—").toUpperCase()}</td>
        <td>${statusBadge(u.subscription_status)}</td>
        <td>${u.total_trades ?? 0}</td>
      </tr>`
      )
      .join("");
  }

  function renderMovements(movements) {
    if (!els.movementsBody) return;
    if (els.movementsMeta) els.movementsMeta.textContent = `${movements.length} events`;
    if (!movements.length) {
      els.movementsBody.innerHTML = `<tr><td colspan="5" class="empty">No movements logged yet</td></tr>`;
      return;
    }
    els.movementsBody.innerHTML = movements
      .map(
        (m) => `
      <tr>
        <td>${m.created_at ? new Date(m.created_at).toLocaleString() : "—"}</td>
        <td>${m.email || m.user_id || "—"}</td>
        <td><span class="badge badge-active">${m.action || "—"}</span></td>
        <td>${m.detail || "—"}</td>
        <td>${m.ip_address || "—"}</td>
      </tr>`
      )
      .join("");
  }

  function renderPayments(payments) {
    els.paymentsMeta.textContent = `${payments.length} records`;
    if (!payments.length) {
      els.paymentsBody.innerHTML = `<tr><td colspan="6" class="empty">No payments logged yet</td></tr>`;
      return;
    }
    els.paymentsBody.innerHTML = payments
      .map(
        (p) => `
      <tr>
        <td>${p.email || "—"}</td>
        <td>${money(p.amount_usd)}</td>
        <td>${String(p.gateway || "—").toUpperCase()}</td>
        <td>${p.created_at ? new Date(p.created_at).toLocaleString() : "—"}</td>
        <td>${statusBadge(p.status)}</td>
        <td>${String(p.tier || "—").toUpperCase()}</td>
      </tr>`
      )
      .join("");
  }

  function fillCms(content) {
    document.getElementById("cms-meta-title").value = content.meta?.title || "";
    document.getElementById("cms-meta-desc").value = content.meta?.description || "";
    document.getElementById("cms-hero-headline").value = content.hero?.headline || "";
    document.getElementById("cms-hero-sub").value = content.hero?.subheadline || "";
    document.getElementById("cms-hero-video").value = content.hero?.video_url || "";
    document.getElementById("cms-cta-primary").value = content.hero?.cta_primary || "";
    document.getElementById("cms-cta-secondary").value = content.hero?.cta_secondary || "";
    document.getElementById("cms-price-starter").value = content.pricing_rates?.starter ?? 29;
    document.getElementById("cms-price-pro").value = content.pricing_rates?.pro ?? 79;
    document.getElementById("cms-price-vip").value = content.pricing_rates?.vip ?? 199;
    document.getElementById("cms-risk").value = content.risk_disclaimer || "";
    document.getElementById("cms-terms").value = content.terms_of_service || "";

    listState.features = Array.isArray(content.features) ? content.features.map((f) => ({ ...f })) : [];
    listState.testimonials = Array.isArray(content.testimonials)
      ? content.testimonials.map((t) => ({ ...t }))
      : Array.isArray(content.trustpilot?.quotes)
        ? content.trustpilot.quotes.map((t) => ({ ...t }))
        : [];
    listState.faq = Array.isArray(content.faq) ? content.faq.map((f) => ({ ...f })) : [];
    renderList("features");
    renderList("testimonials");
    renderList("faq");

    els.cmsMeta.textContent = content.updated_at
      ? `Updated ${content.updated_at}`
      : "Never saved";
  }

  function collectCms() {
    ["features", "testimonials", "faq"].forEach(syncListFromDom);
    return {
      meta: {
        title: document.getElementById("cms-meta-title").value.trim(),
        description: document.getElementById("cms-meta-desc").value.trim(),
      },
      hero: {
        headline: document.getElementById("cms-hero-headline").value.trim(),
        subheadline: document.getElementById("cms-hero-sub").value.trim(),
        video_url: document.getElementById("cms-hero-video").value.trim(),
        cta_primary: document.getElementById("cms-cta-primary").value.trim(),
        cta_secondary: document.getElementById("cms-cta-secondary").value.trim(),
      },
      features: listState.features,
      testimonials: listState.testimonials,
      faq: listState.faq,
      pricing_rates: {
        starter: Number(document.getElementById("cms-price-starter").value || 29),
        pro: Number(document.getElementById("cms-price-pro").value || 79),
        vip: Number(document.getElementById("cms-price-vip").value || 199),
      },
      risk_disclaimer: document.getElementById("cms-risk").value.trim(),
      terms_of_service: document.getElementById("cms-terms").value.trim(),
    };
  }

  function fillSettings(settings) {
    const pay = settings.payments || {};
    const social = settings.social || {};
    document.getElementById("pay-stripe-enabled").checked = !!pay.stripe_enabled;
    document.getElementById("pay-stripe-secret").value = pay.stripe_secret_key || "";
    document.getElementById("pay-stripe-webhook").value = pay.stripe_webhook_secret || "";
    document.getElementById("pay-price-starter").value = pay.stripe_price_starter || "";
    document.getElementById("pay-price-pro").value = pay.stripe_price_pro || "";
    document.getElementById("pay-price-vip").value = pay.stripe_price_vip || "";
    document.getElementById("pay-crypto-enabled").checked = !!pay.crypto_enabled;
    document.getElementById("pay-now-key").value = pay.nowpayments_api_key || "";
    document.getElementById("pay-now-ipn").value = pay.nowpayments_ipn_secret || "";
    document.getElementById("pay-usdt-trc20").value = pay.usdt_trc20_address || "";
    document.getElementById("pay-usdt-bep20").value = pay.usdt_bep20_address || "";
    document.getElementById("social-facebook").value = social.facebook || "";
    document.getElementById("social-youtube").value = social.youtube || "";
    document.getElementById("social-instagram").value = social.instagram || "";
    document.getElementById("social-linkedin").value = social.linkedin || "";
  }

  function collectPayments() {
    return {
      stripe_enabled: document.getElementById("pay-stripe-enabled").checked,
      stripe_secret_key: document.getElementById("pay-stripe-secret").value.trim(),
      stripe_webhook_secret: document.getElementById("pay-stripe-webhook").value.trim(),
      stripe_price_starter: document.getElementById("pay-price-starter").value.trim(),
      stripe_price_pro: document.getElementById("pay-price-pro").value.trim(),
      stripe_price_vip: document.getElementById("pay-price-vip").value.trim(),
      crypto_enabled: document.getElementById("pay-crypto-enabled").checked,
      nowpayments_api_key: document.getElementById("pay-now-key").value.trim(),
      nowpayments_ipn_secret: document.getElementById("pay-now-ipn").value.trim(),
      usdt_trc20_address: document.getElementById("pay-usdt-trc20").value.trim(),
      usdt_bep20_address: document.getElementById("pay-usdt-bep20").value.trim(),
    };
  }

  function collectSocial() {
    return {
      facebook: document.getElementById("social-facebook").value.trim(),
      youtube: document.getElementById("social-youtube").value.trim(),
      instagram: document.getElementById("social-instagram").value.trim(),
      linkedin: document.getElementById("social-linkedin").value.trim(),
    };
  }

  function setGauge(el, labelEl, value, display) {
    const p = Math.max(0, Math.min(100, Number(value) || 0));
    if (el) el.style.setProperty("--p", String(p));
    if (labelEl) labelEl.textContent = display;
  }

  function renderHealth(health) {
    const cpu = Number(health.cpu?.system_percent ?? health.cpu?.process_percent ?? 0);
    const mem = Number(health.memory?.system_percent ?? 0);
    const ws = Number(health.websockets?.total_clients ?? 0);
    const dbMs = Number(health.database?.latency_ms ?? 0);
    setGauge(els.gaugeCpu, els.healthCpu, cpu, `${cpu.toFixed(0)}%`);
    setGauge(els.gaugeMem, els.healthMem, mem, `${mem.toFixed(0)}%`);
    setGauge(els.gaugeWs, els.healthWs, Math.min(100, ws * 10), String(ws));
    setGauge(els.gaugeDb, els.healthDb, Math.min(100, dbMs * 2), `${dbMs.toFixed(1)} ms`);
    if (els.healthMeta) {
      els.healthMeta.textContent = `${health.ts || "live"} · pid ${health.process?.pid || "—"}`;
    }
    const backup = health.backup || {};
    if (els.backupMeta) {
      const latest = backup.latest_file || backup.last_backup?.file || "none yet";
      const err = backup.last_error ? ` · err: ${backup.last_error}` : "";
      els.backupMeta.textContent = `Backup: ${latest} · keep ${backup.retain ?? "—"} · count ${
        backup.count ?? 0
      }${err}`;
    }
  }

  async function loadHealth() {
    const health = await fetchJson("/api/admin/system-health");
    renderHealth(health);
  }

  async function loadDashboard() {
    const data = await fetchJson("/api/admin/dashboard");
    renderStats(data.stats || {});
    renderUsers(data.users || []);
    renderPayments(data.payments || []);
    renderMovements(data.movements || []);
    els.meta.textContent = `Signed in as ${data.admin?.email || "admin"} · ${data.server_time || ""}`;
    await loadHealth();
  }

  async function loadCms() {
    const data = await fetchJson("/api/admin/content");
    fillCms(data.content || {});
  }

  async function loadSettings() {
    const data = await fetchJson("/api/admin/settings");
    fillSettings(data.settings || {});
  }

  function showPanel(panel) {
    ["users", "movements", "payments", "gateways", "social", "cms"].forEach((name) => {
      const el = document.getElementById(`panel-${name}`);
      if (el) el.classList.toggle("hidden", name !== panel);
    });
  }

  document.querySelectorAll(".admin-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".admin-tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      const panel = btn.dataset.panel;
      showPanel(panel);
      if (panel === "cms") loadCms().catch(console.error);
      if (panel === "gateways" || panel === "social") loadSettings().catch(console.error);
    });
  });

  document.getElementById("btn-refresh-admin").addEventListener("click", () => {
    loadDashboard().catch((err) => {
      els.meta.textContent = err.message;
    });
  });

  document.getElementById("btn-run-backup")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-run-backup");
    if (btn) btn.disabled = true;
    try {
      const result = await fetchJson("/api/admin/backup/run", { method: "POST" });
      if (els.backupMeta) {
        els.backupMeta.textContent = `Backup created: ${result.backup?.file || "ok"}`;
        els.backupMeta.style.color = "#2dd4bf";
      }
      await loadHealth();
    } catch (err) {
      if (els.backupMeta) {
        els.backupMeta.textContent = err.message;
        els.backupMeta.style.color = "#f43f5e";
      }
    } finally {
      if (btn) btn.disabled = false;
    }
  });

  document.getElementById("btn-admin-logout").addEventListener("click", async () => {
    try {
      await fetchJson("/api/auth/logout", { method: "POST" });
    } catch (_) {
      /* ignore */
    }
    localStorage.removeItem(TOKEN_KEY);
    window.location.href = "/";
  });

  document.getElementById("btn-reload-cms").addEventListener("click", () => {
    loadCms().catch((err) => {
      els.cmsStatus.textContent = err.message;
    });
  });

  document.querySelectorAll("[data-add-list]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const kind = btn.dataset.addList;
      if (!LIST_SPECS[kind]) return;
      syncListFromDom(kind);
      listState[kind].push(LIST_SPECS[kind].blank());
      renderList(kind);
    });
  });

  document.getElementById("panel-cms")?.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-remove-list]");
    if (!btn) return;
    const kind = btn.dataset.removeList;
    const idx = Number(btn.dataset.idx);
    syncListFromDom(kind);
    listState[kind].splice(idx, 1);
    renderList(kind);
  });

  els.cmsForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    els.cmsStatus.textContent = "Saving…";
    try {
      const result = await fetchJson("/api/admin/content/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content: collectCms() }),
      });
      fillCms(result.content || {});
      els.cmsStatus.textContent = "CMS content saved.";
      els.cmsStatus.style.color = "#2dd4bf";
    } catch (err) {
      els.cmsStatus.textContent = err.message;
      els.cmsStatus.style.color = "#f43f5e";
    }
  });

  els.gatewaysForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    els.gatewaysStatus.textContent = "Saving…";
    try {
      const result = await fetchJson("/api/admin/settings/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ payments: collectPayments() }),
      });
      fillSettings(result.settings || {});
      els.gatewaysStatus.textContent = "Payment gateways updated.";
      els.gatewaysStatus.style.color = "#2dd4bf";
    } catch (err) {
      els.gatewaysStatus.textContent = err.message;
      els.gatewaysStatus.style.color = "#f43f5e";
    }
  });

  els.socialForm?.addEventListener("submit", async (e) => {
    e.preventDefault();
    els.socialStatus.textContent = "Saving…";
    try {
      const result = await fetchJson("/api/admin/settings/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ social: collectSocial() }),
      });
      fillSettings(result.settings || {});
      els.socialStatus.textContent = "Social links updated.";
      els.socialStatus.style.color = "#2dd4bf";
    } catch (err) {
      els.socialStatus.textContent = err.message;
      els.socialStatus.style.color = "#f43f5e";
    }
  });

  (async () => {
    try {
      await loadDashboard();
      await loadCms();
      await loadSettings();
      setInterval(() => {
        loadHealth().catch(() => {});
      }, 5000);
    } catch (err) {
      els.meta.textContent = err.message;
    }
  })();
})();
