(() => {
  "use strict";

  const state = { user: null, error: null };
  const loginPath = "./static/login.html";

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
    const role = String(user.roleLabel || "").trim() || "待分配";
    const account = String(user.email || user.account || "").trim();
    document.getElementById("authUserName").textContent = name;
    const departmentLabel = department || "未设置部门";
    const departmentElement = document.getElementById("authUserDepartment");
    departmentElement.textContent = departmentLabel;
    departmentElement.title = departmentLabel;
    document.getElementById("authUserRole").textContent = role;
    document.getElementById("authUserMenuButton").setAttribute("aria-label", `${name}，打开账户菜单`);
    document.getElementById("authUserAvatarInitial").textContent = name.trim().slice(0, 1) || "用";
    document.getElementById("authMenuUserName").textContent = name;
    document.getElementById("authMenuUserAccount").textContent = account || "飞书统一身份";
    document.getElementById("authMenuDepartment").textContent = departmentLabel;
    document.getElementById("authMenuRole").textContent = role;
    const avatarImage = document.getElementById("authUserAvatarImage");
    const avatarInitial = document.getElementById("authUserAvatarInitial");
    try {
      const rawAvatar = String(user.avatarUrl || "").trim();
      if (!rawAvatar) throw new Error("missing avatar URL");
      const avatarUrl = new URL(rawAvatar, location.origin);
      if (!["http:", "https:"].includes(avatarUrl.protocol)) throw new Error("unsupported avatar URL");
      avatarImage.src = avatarUrl.href;
      avatarImage.hidden = false;
      avatarInitial.hidden = true;
    } catch (_) {
      avatarImage.removeAttribute("src");
      avatarImage.hidden = true;
      avatarInitial.hidden = false;
    }
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

  function setMenu(open) {
    const button = document.getElementById("authUserMenuButton");
    const menu = document.getElementById("authUserMenu");
    if (!button || !menu) return;
    menu.hidden = !open;
    button.setAttribute("aria-expanded", open ? "true" : "false");
    if (open) menu.querySelector('[role="menuitem"]')?.focus();
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
  document.getElementById("authUserMenuButton")?.addEventListener("click", () => {
    const menu = document.getElementById("authUserMenu");
    setMenu(Boolean(menu?.hidden));
  });
  document.addEventListener("pointerdown", (event) => {
    const host = document.getElementById("authUser");
    if (host && !host.contains(event.target)) setMenu(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      setMenu(false);
      document.getElementById("authUserMenuButton")?.focus();
    }
  });
})();
