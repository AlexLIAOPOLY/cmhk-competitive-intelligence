(() => {
  "use strict";

  const host = document.getElementById("organizationAdmin");
  if (!host) return;
  const state = {
    loaded: false, loading: false, query: "", users: [], roles: {}, modules: {}, roleModules: {},
    audit: [],
    directory: { open: false, query: "", loading: false, users: [], error: "", timer: null },
  };
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  async function request(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.message || `请求失败（${response.status}）`);
    return payload;
  }

  function filteredUsers() {
    const query = state.query.trim().toLowerCase();
    if (!query) return state.users;
    return state.users.filter((user) => [user.name, user.account, user.email, user.department, user.roleLabel].some((value) => String(value || "").toLowerCase().includes(query)));
  }

  function memberIdentity(user) {
    const secondary = [user.department, user.email || user.account].filter(Boolean).join(" · ") || "—";
    return `<div class="organization-member"><span class="organization-avatar">${esc(String(user.name || user.account || "用").slice(0, 1))}</span><span><strong>${esc(user.name || user.account || "未命名成员")}${user.current ? '<em>当前账号</em>' : ""}</strong><small>${esc(secondary)}</small></span></div>`;
  }

  function roleOptions(user) {
    return Object.entries(state.roles).map(([value, label]) => `<option value="${esc(value)}"${user.role === value ? " selected" : ""}>${esc(label)}</option>`).join("");
  }

  function permissionEditor(user) {
    const enabled = Object.values(user.modules || {}).filter(Boolean).length;
    const checks = Object.entries(state.modules).map(([key, label]) => {
      const checked = user.modules?.[key] === true;
      const protectedPermission = user.current && key === "organization";
      return `<label class="organization-permission"><input type="checkbox" data-module="${esc(key)}"${checked ? " checked" : ""}${protectedPermission ? " disabled" : ""} /><span>${esc(label)}</span></label>`;
    }).join("");
    return `<details class="organization-permissions"><summary><span data-permission-count>${enabled} / ${Object.keys(state.modules).length} 个模块</span><b>编辑权限</b></summary><div class="organization-permission-grid">${checks}</div></details>`;
  }

  function row(user) {
    return `<tr data-user-id="${esc(user.id)}"${user.current ? ' class="is-current"' : ""}>
      <td>${memberIdentity(user)}</td>
      <td><select class="organization-select" data-role aria-label="${esc(user.name)}的角色">${roleOptions(user)}</select></td>
      <td><select class="organization-select" data-status aria-label="${esc(user.name)}的状态"${user.current ? " disabled" : ""}><option value="active"${user.status === "active" ? " selected" : ""}>启用</option><option value="disabled"${user.status === "disabled" ? " selected" : ""}>停用</option></select></td>
      <td>${permissionEditor(user)}</td>
      <td class="organization-actions"><button type="button" data-save disabled>保存</button><span data-row-status aria-live="polite"></span></td>
    </tr>`;
  }

  function auditAvatar(event) {
    const name = String(event.actor_name || "未知用户");
    const raw = String(event.actor_avatar_url || "").trim();
    try {
      if (!raw) throw new Error("missing avatar URL");
      const url = new URL(raw, location.origin);
      if (["http:", "https:"].includes(url.protocol)) return `<span class="organization-avatar is-round"><img src="${esc(url.href)}" alt="" /></span>`;
    } catch (_) { /* use initial */ }
    return `<span class="organization-avatar is-round">${esc(name.slice(0, 1) || "用")}</span>`;
  }

  function auditAction(event) {
    return ({ "fault.mark_handled": "处理告警", "news_review.update": "复核新闻", "organization.user_update": "修改成员权限", "organization.user_import": "添加组织成员" })[event.action] || event.action || "系统操作";
  }

  function auditTime(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return String(value || "—");
    return date.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Hong_Kong" });
  }

  function auditSurface() {
    const rows = state.audit.map((event) => `<tr><td><div class="organization-member">${auditAvatar(event)}<span><strong>${esc(event.actor_name || "未知用户")}</strong><small>${esc(event.actor_id || "—")}</small></span></div></td><td><strong>${esc(auditAction(event))}</strong><small>${esc(event.target || "—")}</small></td><td><span class="organization-audit-result ${event.result === "failure" ? "is-failure" : "is-success"}">${event.result === "failure" ? "失败" : "成功"}</span></td><td>${esc(auditTime(event.at))}</td></tr>`).join("");
    return `<section class="organization-surface organization-audit-surface"><header><div><span>OPERATION AUDIT</span><h2>操作审计</h2><p>独立记录告警处理、新闻复核等关键操作，管理员可按登录身份追踪操作人。</p></div><strong>${state.audit.length} 条</strong></header><div class="organization-table-wrap"><table class="organization-table organization-audit-table"><thead><tr><th>操作人</th><th>动作与对象</th><th>结果</th><th>时间</th></tr></thead><tbody>${rows || '<tr><td colspan="4"><div class="organization-empty">暂无操作审计记录</div></td></tr>'}</tbody></table></div></section>`;
  }

  function directoryResults() {
    const directory = state.directory;
    if (directory.loading) return '<div class="organization-directory-state">正在搜索飞书通讯录…</div>';
    if (directory.error) return `<div class="organization-directory-state is-error">${esc(directory.error)}</div>`;
    if (directory.query.trim().length < 2) return '<div class="organization-directory-state">请输入至少 2 个字符，可按姓名或企业邮箱搜索。</div>';
    if (!directory.users.length) return '<div class="organization-directory-state">飞书通讯录中没有匹配成员。</div>';
    return `<div class="organization-directory-list">${directory.users.map((user) => `<article class="organization-directory-user" data-directory-email="${esc(user.email)}"><span class="organization-avatar">${esc(String(user.name || "用").slice(0, 1))}</span><span><strong>${esc(user.name || "未命名成员")}</strong><small>${esc([user.department, user.email].filter(Boolean).join(" · ") || "—")}</small></span><button type="button" data-import-email="${esc(user.email)}"${user.added ? " disabled" : ""}>${user.added ? "已添加" : "加入组织"}</button></article>`).join("")}</div>`;
  }

  function directoryPanel() {
    if (!state.directory.open) return "";
    return `<section class="organization-directory" aria-labelledby="directoryTitle"><header><div><strong id="directoryTitle">添加飞书成员</strong><span>从 CMHK 飞书通讯录加入权限名单，初始角色为“待分配”。</span></div><button type="button" data-directory-close aria-label="关闭添加成员">×</button></header><label><span class="sr-only">搜索飞书成员</span><input type="search" data-directory-search value="${esc(state.directory.query)}" placeholder="输入姓名或企业邮箱（至少 2 个字符）" autocomplete="off" /></label><div data-directory-results aria-live="polite">${directoryResults()}</div></section>`;
  }

  function render() {
    const users = filteredUsers();
    host.innerHTML = `<header class="organization-heading"><div><span>ORGANIZATION &amp; ACCESS</span><h1>组织管理</h1><p>按成员岗位分配角色，并细化可查看的工作页签。权限保存后将在下次页面加载时生效。</p></div><div class="organization-heading-actions"><button type="button" data-directory-open>添加飞书成员</button><button type="button" data-refresh>刷新成员</button></div></header>
      ${directoryPanel()}
      <section class="organization-surface">
        <div class="organization-toolbar"><label><span class="sr-only">搜索成员</span><input type="search" data-search value="${esc(state.query)}" placeholder="搜索姓名、部门、账号或角色" /></label><span>显示 <strong>${users.length}</strong> / ${state.users.length} 名成员</span></div>
        <div class="organization-table-wrap"><table class="organization-table"><thead><tr><th>成员</th><th>角色</th><th>状态</th><th>模块权限</th><th>操作</th></tr></thead><tbody>${users.length ? users.map(row).join("") : '<tr><td colspan="5"><div class="organization-empty">没有符合条件的成员</div></td></tr>'}</tbody></table></div>
      </section>${auditSurface()}`;
  }

  function renderError(message) {
    host.innerHTML = `<div class="organization-error" role="alert"><strong>组织信息读取失败</strong><p>${esc(message)}</p><button type="button" data-refresh>重新读取</button></div>`;
  }

  async function load({ force = false } = {}) {
    if (state.loading || (state.loaded && !force)) return;
    state.loading = true;
    if (!state.loaded) host.innerHTML = '<div class="organization-loading" role="status">正在读取组织成员与权限…</div>';
    try {
      const [payload, auditPayload] = await Promise.all([
        request("/api/auth/admin/users"),
        request("/api/auth/admin/audit?limit=200"),
      ]);
      state.users = Array.isArray(payload.users) ? payload.users : [];
      state.roles = payload.roles || {};
      state.modules = payload.modules || {};
      state.roleModules = payload.roleModules || {};
      state.audit = Array.isArray(auditPayload.events) ? auditPayload.events : [];
      state.loaded = true;
      render();
    } catch (error) {
      renderError(error.message);
    } finally {
      state.loading = false;
    }
  }

  function renderDirectoryResults() {
    const results = host.querySelector("[data-directory-results]");
    if (results) results.innerHTML = directoryResults();
  }

  async function searchDirectory() {
    const query = state.directory.query.trim();
    if (query.length < 2) {
      state.directory.loading = false;
      state.directory.users = [];
      state.directory.error = "";
      renderDirectoryResults();
      return;
    }
    state.directory.loading = true;
    state.directory.error = "";
    renderDirectoryResults();
    try {
      const payload = await request(`/api/auth/admin/directory/search?q=${encodeURIComponent(query)}`);
      if (query !== state.directory.query.trim()) return;
      state.directory.users = Array.isArray(payload.users) ? payload.users : [];
    } catch (error) {
      state.directory.users = [];
      state.directory.error = error.message;
    } finally {
      if (query === state.directory.query.trim()) {
        state.directory.loading = false;
        renderDirectoryResults();
      }
    }
  }

  async function importDirectoryUser(button) {
    const email = button.dataset.importEmail;
    if (!email) return;
    button.disabled = true;
    button.textContent = "添加中…";
    try {
      await request("/api/auth/admin/users/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const user = state.directory.users.find((item) => item.email === email);
      if (user) user.added = true;
      button.textContent = "已添加";
      await load({ force: true });
    } catch (error) {
      button.disabled = false;
      button.textContent = "重试";
      state.directory.error = error.message;
      renderDirectoryResults();
    }
  }

  function markDirty(row) {
    row.classList.add("is-dirty");
    const button = row.querySelector("[data-save]");
    if (button) button.disabled = false;
    const status = row.querySelector("[data-row-status]");
    if (status) status.textContent = "有未保存修改";
    const count = [...row.querySelectorAll("[data-module]")].filter((input) => input.checked).length;
    const countHost = row.querySelector("[data-permission-count]");
    if (countHost) countHost.textContent = `${count} / ${Object.keys(state.modules).length} 个模块`;
  }

  function applyRoleDefaults(row, role) {
    const defaults = state.roleModules[role] || {};
    row.querySelectorAll("[data-module]").forEach((input) => {
      input.checked = defaults[input.dataset.module] === true;
      if (row.classList.contains("is-current") && input.dataset.module === "organization") input.checked = true;
    });
    markDirty(row);
  }

  async function save(row) {
    const button = row.querySelector("[data-save]");
    const rowStatus = row.querySelector("[data-row-status]");
    const modules = Object.fromEntries([...row.querySelectorAll("[data-module]")].map((input) => [input.dataset.module, input.checked]));
    button.disabled = true;
    button.textContent = "保存中…";
    rowStatus.textContent = "正在写入权限";
    try {
      await request(`/api/auth/admin/users/${encodeURIComponent(row.dataset.userId)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: row.querySelector("[data-role]").value, status: row.querySelector("[data-status]").value, modules }),
      });
      row.classList.remove("is-dirty");
      rowStatus.textContent = "已保存";
      button.textContent = "保存";
      window.setTimeout(() => load({ force: true }), 450);
    } catch (error) {
      rowStatus.textContent = error.message;
      rowStatus.classList.add("is-error");
      button.disabled = false;
      button.textContent = "重试";
    }
  }

  host.addEventListener("input", (event) => {
    if (event.target.matches("[data-directory-search]")) {
      state.directory.query = event.target.value;
      window.clearTimeout(state.directory.timer);
      state.directory.timer = window.setTimeout(searchDirectory, 320);
      return;
    }
    if (!event.target.matches("[data-search]")) return;
    state.query = event.target.value;
    render();
    const search = host.querySelector("[data-search]");
    search?.focus();
    search?.setSelectionRange(state.query.length, state.query.length);
  });
  host.addEventListener("change", (event) => {
    const row = event.target.closest("[data-user-id]");
    if (!row) return;
    if (event.target.matches("[data-role]")) applyRoleDefaults(row, event.target.value);
    else if (event.target.matches("[data-status], [data-module]")) markDirty(row);
  });
  host.addEventListener("click", (event) => {
    if (event.target.closest("[data-directory-open]")) {
      state.directory.open = true;
      render();
      host.querySelector("[data-directory-search]")?.focus();
      return;
    }
    if (event.target.closest("[data-directory-close]")) {
      state.directory.open = false;
      render();
      return;
    }
    const importButton = event.target.closest("[data-import-email]");
    if (importButton) {
      importDirectoryUser(importButton);
      return;
    }
    if (event.target.closest("[data-refresh]")) load({ force: true });
    const saveButton = event.target.closest("[data-save]");
    if (saveButton) save(saveButton.closest("[data-user-id]"));
  });

  window.addEventListener("workspace-tab-change", (event) => {
    if (event.detail?.tab === "organization") load();
  });
  window.CMHKOrganizationAdmin = { load };
})();
