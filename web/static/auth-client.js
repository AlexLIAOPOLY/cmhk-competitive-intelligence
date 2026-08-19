(() => {
  "use strict";

  const state = { user: null, error: null };
  const loginPath = "/static/login.html";

  function safeNext() {
    return `${location.pathname}${location.search}${location.hash}`;
  }

  function loginUrl() {
    return `${loginPath}?next=${encodeURIComponent(safeNext())}`;
  }

  async function readJson(response) {
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || `身份服务返回 ${response.status}`);
    }
    return payload;
  }

  function renderUser(user) {
    const host = document.getElementById("authUser");
    if (!host || !user) return;
    const name = String(user.name || user.account || "当前用户");
    const department = String(user.department || "").trim();
    const role = String(user.roleLabel || "待分配");
    document.getElementById("authUserName").textContent = name;
    document.getElementById("authUserRole").textContent = department ? `${department} · ${role}` : role;
    document.getElementById("authUserAvatar").textContent = name.trim().slice(0, 1) || "用";
    const modules = user.permissions?.modules || {};
    if (!modules.ai) {
      document.getElementById("chatFab")?.setAttribute("hidden", "");
      document.getElementById("chatModal")?.setAttribute("hidden", "");
    }
    if (!modules.weekly && !modules.performance) {
      document.getElementById("reportLibraryButton")?.setAttribute("hidden", "");
      document.getElementById("outputArea")?.setAttribute("hidden", "");
    }
    host.hidden = false;
  }

  async function loadCurrentUser() {
    try {
      const payload = await fetch("/api/auth/me", { credentials: "same-origin", cache: "no-store" }).then(readJson);
      if (!payload.authenticated || !payload.user) {
        location.replace(loginUrl());
        return null;
      }
      state.user = payload.user;
      renderUser(state.user);
      window.dispatchEvent(new CustomEvent("cmhk-auth-ready", { detail: { user: state.user } }));
      return state.user;
    } catch (error) {
      state.error = error;
      window.dispatchEvent(new CustomEvent("cmhk-auth-error", { detail: { error } }));
      throw error;
    }
  }

  async function logout() {
    const button = document.getElementById("authLogoutButton");
    if (button) {
      button.disabled = true;
      button.textContent = "退出中…";
    }
    try {
      await fetch("/api/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      }).then(readJson);
    } finally {
      location.replace(loginPath);
    }
  }

  const api = {
    state,
    ready: null,
    get user() { return state.user; },
    get modules() { return state.user?.permissions?.modules || {}; },
    hasModule(name) { return state.user?.permissions?.modules?.[name] === true; },
    logout,
  };
  window.CMHKAuth = api;
  api.ready = loadCurrentUser();
  api.ready.catch((error) => console.error("Unable to initialize CMHK identity", error));

  document.getElementById("authLogoutButton")?.addEventListener("click", logout);
})();
