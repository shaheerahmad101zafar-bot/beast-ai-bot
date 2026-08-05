(() => {
  const INSTALL_KEY = "beast_pwa_install_dismissed";
  let deferredPrompt = null;

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true
    );
  }

  function isMobile() {
    return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent) || window.innerWidth < 820;
  }

  function ensureBanner() {
    let el = document.getElementById("pwa-install-banner");
    if (el) return el;
    el = document.createElement("div");
    el.id = "pwa-install-banner";
    el.className = "pwa-install-banner hidden";
    el.innerHTML = `
      <div class="pwa-install-inner">
        <div>
          <strong>Install Beast AI</strong>
          <p>Add to your home screen for a full-screen trading desk.</p>
        </div>
        <div class="pwa-install-actions">
          <button type="button" id="pwa-install-btn" class="pwa-install-cta">Install</button>
          <button type="button" id="pwa-dismiss-btn" class="pwa-install-dismiss" aria-label="Dismiss">✕</button>
        </div>
      </div>`;
    document.body.appendChild(el);
    return el;
  }

  function showBanner() {
    if (isStandalone()) return;
    if (localStorage.getItem(INSTALL_KEY) === "1") return;
    if (!isMobile() && !deferredPrompt) return;
    const banner = ensureBanner();
    banner.classList.remove("hidden");
    const installBtn = document.getElementById("pwa-install-btn");
    const dismissBtn = document.getElementById("pwa-dismiss-btn");
    if (installBtn && !installBtn.dataset.bound) {
      installBtn.dataset.bound = "1";
      installBtn.addEventListener("click", async () => {
        if (deferredPrompt) {
          deferredPrompt.prompt();
          try {
            await deferredPrompt.userChoice;
          } catch (_) {
            /* ignore */
          }
          deferredPrompt = null;
          banner.classList.add("hidden");
          return;
        }
        // iOS Safari has no beforeinstallprompt — show tip
        installBtn.textContent = "Share → Add to Home Screen";
      });
    }
    if (dismissBtn && !dismissBtn.dataset.bound) {
      dismissBtn.dataset.bound = "1";
      dismissBtn.addEventListener("click", () => {
        localStorage.setItem(INSTALL_KEY, "1");
        banner.classList.add("hidden");
      });
    }
  }

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker
        .register("/service-worker.js", { scope: "/" })
        .catch((err) => console.warn("SW register failed", err));
    });
  }

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    showBanner();
  });

  // iOS / small screens: show soft prompt even without beforeinstallprompt
  window.addEventListener("load", () => {
    setTimeout(() => {
      if (isMobile() && !isStandalone()) showBanner();
    }, 2500);
  });
})();
