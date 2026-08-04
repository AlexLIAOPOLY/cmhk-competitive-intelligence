(function initializeSiteTheme() {
  const STORAGE_KEY = "cmhk-color-theme";
  const THEMES = new Set(["dark", "light"]);

  function storedTheme() {
    try {
      const value = window.localStorage.getItem(STORAGE_KEY);
      return THEMES.has(value) ? value : "dark";
    } catch (_error) {
      return "dark";
    }
  }

  function updateControls(theme) {
    const nextTheme = theme === "dark" ? "light" : "dark";
    const nextLabel = nextTheme === "light" ? "切换至浅色模式" : "切换至深色模式";
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.setAttribute("aria-label", nextLabel);
      button.setAttribute("title", nextLabel);
      button.setAttribute("aria-pressed", String(theme === "light"));
      const label = button.querySelector("[data-theme-label]");
      if (label) label.textContent = theme === "light" ? "浅色" : "深色";
    });
  }

  function applyTheme(theme, persist) {
    const resolved = THEMES.has(theme) ? theme : "dark";
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    const colorSchemeMeta = document.querySelector('meta[name="color-scheme"]');
    if (colorSchemeMeta) colorSchemeMeta.setAttribute("content", resolved);
    updateControls(resolved);
    if (persist) {
      try {
        window.localStorage.setItem(STORAGE_KEY, resolved);
      } catch (_error) {
        // The theme remains active for this page even when storage is unavailable.
      }
    }
    window.dispatchEvent(new CustomEvent("cmhk-theme-change", { detail: { theme: resolved } }));
  }

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(document.documentElement.dataset.theme || storedTheme(), false);
    document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light", true);
      });
    });
  });

  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY && THEMES.has(event.newValue)) applyTheme(event.newValue, false);
  });
})();
