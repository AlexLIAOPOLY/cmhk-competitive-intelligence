(() => {
  "use strict";

  const state = { user: null, error: null };
  const loginPath = "/static/login.html";
  let profileCard = null;
  let profileReturnFocus = null;

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

  function safeImageUrl(raw) {
    try {
      const url = new URL(String(raw || "").trim(), location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) {
      return "";
    }
  }

  function closeProfile({ restoreFocus = true } = {}) {
    if (!profileCard) return;
    profileCard.remove();
    profileCard = null;
    const target = profileReturnFocus;
    profileReturnFocus = null;
    if (restoreFocus && target?.isConnected) target.focus();
  }

  function profileField(label, value) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const detail = document.createElement("dd");
    term.textContent = label;
    detail.textContent = String(value || "—");
    row.append(term, detail);
    return row;
  }

  function positionProfileCard(card, anchor) {
    const edge = 10;
    const gap = 10;
    const anchorRect = anchor?.getBoundingClientRect?.();
    if (!anchorRect) return;
    const cardRect = card.getBoundingClientRect();
    const roomOnLeft = anchorRect.left - gap - edge;
    const placeLeft = roomOnLeft >= cardRect.width;
    let left = placeLeft ? anchorRect.left - cardRect.width - gap : anchorRect.right + gap;
    left = Math.max(edge, Math.min(left, window.innerWidth - cardRect.width - edge));
    let top = anchorRect.top - 12;
    top = Math.max(edge, Math.min(top, window.innerHeight - cardRect.height - edge));
    card.dataset.placement = placeLeft ? "left" : "right";
    card.style.left = `${Math.round(left)}px`;
    card.style.top = `${Math.round(top)}px`;
  }

  function openProfile(user = state.user, returnFocus = document.activeElement) {
    if (!user) return;
    closeProfile({ restoreFocus: false });
    profileReturnFocus = returnFocus;
    const name = String(user.name || user.account || "当前用户");
    const card = document.createElement("section");
    card.className = "organization-profile-card auth-user-profile-card";
    card.setAttribute("role", "dialog");
    card.setAttribute("aria-modal", "false");
    card.setAttribute("aria-label", `${name}的成员详情`);
    card.tabIndex = -1;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "organization-profile-close";
    close.setAttribute("aria-label", "关闭成员详情");
    close.textContent = "×";
    close.addEventListener("click", () => closeProfile());

    const header = document.createElement("header");
    const avatar = document.createElement("span");
    avatar.className = "organization-avatar is-profile-card";
    avatar.setAttribute("aria-hidden", "true");
    const initial = document.createElement("span");
    initial.textContent = name.trim().slice(0, 1) || "用";
    avatar.appendChild(initial);
    const imageUrl = safeImageUrl(user.avatarUrl || user.avatar_url);
    if (imageUrl) {
      const image = document.createElement("img");
      image.src = imageUrl;
      image.alt = "";
      image.addEventListener("error", () => image.remove(), { once: true });
      avatar.appendChild(image);
    }
    const heading = document.createElement("div");
    const title = document.createElement("h2");
    const subtitle = document.createElement("span");
    title.textContent = name;
    subtitle.textContent = String(user.title || user.roleLabel || "团队成员");
    heading.append(title, subtitle);
    const status = document.createElement("em");
    status.className = `organization-account-state${user.status === "disabled" ? " is-disabled" : ""}`;
    status.textContent = user.status === "disabled" ? "已停用" : "启用";
    header.append(avatar, heading, status);

    const details = document.createElement("dl");
    details.append(
      profileField("所属部门", user.department),
      profileField("企业邮箱", user.email),
      profileField("登录账号", user.account),
      profileField("身份来源", user.authProvider === "feishu" ? "飞书企业身份" : "本地账号"),
    );
    card.append(close, header, details);
    document.body.appendChild(card);
    profileCard = card;
    positionProfileCard(card, returnFocus);
    requestAnimationFrame(() => card.focus());
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
    openProfile,
    closeProfile,
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
    if (profileCard && !profileCard.contains(event.target)) closeProfile({ restoreFocus: false });
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      if (profileCard) {
        closeProfile();
        return;
      }
      setMenu(false);
      document.getElementById("authUserMenuButton")?.focus();
    }
  });
  window.addEventListener("resize", () => {
    if (profileCard) positionProfileCard(profileCard, profileReturnFocus);
  });
})();
