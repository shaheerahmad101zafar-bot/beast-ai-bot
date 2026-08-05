/**
 * Beast AI — shared social icon renderer for navbar/footer.
 */
(function (global) {
  const ICONS = {
    facebook:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M14 9h3V6h-3c-1.7 0-3 1.3-3 3v2H8v3h3v7h3v-7h3l1-3h-4V9c0-.6.4-1 1-1z"/></svg>',
    youtube:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M23 12.2s0-3.2-.4-4.7c-.2-.9-.9-1.6-1.8-1.8C18.5 5.2 12 5.2 12 5.2s-6.5 0-8.8.5c-.9.2-1.6.9-1.8 1.8C1 9 1 12.2 1 12.2s0 3.2.4 4.7c.2.9.9 1.6 1.8 1.8 2.3.5 8.8.5 8.8.5s6.5 0 8.8-.5c.9-.2 1.6-.9 1.8-1.8.4-1.5.4-4.7.4-4.7zM9.8 15.5v-6.6l5.7 3.3-5.7 3.3z"/></svg>',
    instagram:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4zm10 2H7a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm-5 3.2A3.8 3.8 0 1 1 8.2 12 3.8 3.8 0 0 1 12 8.2zm0 1.6A2.2 2.2 0 1 0 14.2 12 2.2 2.2 0 0 0 12 9.8zM17.4 7a1 1 0 1 1-1 1 1 1 0 0 1 1-1z"/></svg>',
    linkedin:
      '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M6.2 9.2H3.4V20h2.8V9.2zM4.8 4a1.6 1.6 0 1 0 1.6 1.6A1.6 1.6 0 0 0 4.8 4zM20.6 20h-2.8v-5.4c0-1.5-.6-2.5-2-2.5s-1.8.9-1.8 2.5V20H11V9.2h2.7v1.5a3.2 3.2 0 0 1 2.8-1.6c2.1 0 4.1 1.4 4.1 4.5V20z"/></svg>',
  };

  function normalize(social) {
    const src = social || {};
    return ["facebook", "youtube", "instagram", "linkedin"]
      .map((key) => ({ key, url: String(src[key] || "").trim() }))
      .filter((item) => item.url && /^https?:\/\//i.test(item.url));
  }

  function renderInto(selector, social) {
    const nodes = document.querySelectorAll(selector);
    if (!nodes.length) return;
    const items = normalize(social);
    const html = items.length
      ? items
          .map(
            (item) =>
              `<a class="social-link" href="${item.url}" target="_blank" rel="noopener noreferrer" aria-label="${item.key}">${ICONS[item.key]}</a>`
          )
          .join("")
      : "";
    nodes.forEach((el) => {
      el.innerHTML = html;
      el.classList.toggle("hidden", !items.length);
      el.classList.toggle("is-empty", !items.length);
    });
  }

  async function hydrate(selector = "[data-social-links]") {
    try {
      const res = await fetch("/api/public/site-config");
      if (!res.ok) return;
      const data = await res.json();
      renderInto(selector, data.social || {});
      return data;
    } catch (_) {
      return null;
    }
  }

  global.BeastSocial = { hydrate, renderInto, normalize };
})(window);
