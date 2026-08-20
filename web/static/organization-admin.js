(() => {
  "use strict";

  const host = document.getElementById("organizationAdmin");
  if (!host) return;
  const state = {
    loaded: false, loading: false, query: "", department: "", role: "", selectedUserId: "",
    users: [], departments: [], roles: {}, modules: {}, roleModules: {}, audit: [],
    directory: { open: false, query: "", loading: false, users: [], error: "", timer: null },
  };
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));

  async function request(url, options = {}) {
    const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || payload.ok === false) throw new Error(payload.message || `请求失败（${response.status}）`);
    return payload;
  }

  function safeImageUrl(raw) {
    try {
      const url = new URL(String(raw || "").trim(), location.origin);
      return ["http:", "https:"].includes(url.protocol) ? url.href : "";
    } catch (_) { return ""; }
  }

  function avatar(person, size = "") {
    const name = String(person.name || person.actor_name || person.account || "用户");
    const image = safeImageUrl(person.avatarUrl || person.avatar_url || person.actor_avatar_url);
    return `<span class="organization-avatar ${size}" aria-hidden="true"><span>${esc(name.slice(0, 1) || "用")}</span>${image ? `<img src="${esc(image)}" alt="" loading="lazy" onerror="this.remove()" />` : ""}</span>`;
  }

  function filteredUsers() {
    const query = state.query.trim().toLowerCase();
    return state.users.filter((user) => {
      const matchesQuery = !query || [user.name, user.account, user.email, user.department, user.title, user.roleLabel].some((value) => String(value || "").toLowerCase().includes(query));
      return matchesQuery && (!state.department || user.department === state.department) && (!state.role || user.role === state.role);
    });
  }

  function selectedUser(users = filteredUsers()) {
    const selected = state.users.find((user) => String(user.id) === String(state.selectedUserId));
    if (selected && users.includes(selected)) return selected;
    const next = users[0] || null;
    state.selectedUserId = next ? String(next.id) : "";
    return next;
  }

  function memberIdentity(user) {
    const secondary = user.account || user.email || "—";
    return `<span class="organization-member">${avatar(user, "is-member")}<span><strong>${esc(user.name || user.account || "未命名成员")}${user.current ? '<em>当前管理员</em>' : ""}</strong><small>${esc(secondary)}</small></span></span>`;
  }

  function roleOptions(user) {
    return Object.entries(state.roles).map(([value, label]) => `<option value="${esc(value)}"${user.role === value ? " selected" : ""}>${esc(label)}</option>`).join("");
  }

  function selectOptions(values, current, allLabel) {
    return `<option value="">${esc(allLabel)}</option>${values.map((value) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(value)}</option>`).join("")}`;
  }

  function memberList(users, selected) {
    const trashIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5" /></svg>';
    const items = users.map((user) => `<li class="organization-member-entry"><button type="button" class="organization-member-row${selected?.id === user.id ? " is-selected" : ""}" data-select-user="${esc(user.id)}" aria-pressed="${selected?.id === user.id}">
      ${memberIdentity(user)}
      <span class="organization-member-meta"><strong>${esc(user.department || "未填写部门")}</strong><small>${esc(user.roleLabel || "待分配")} · ${user.status === "disabled" ? "已停用" : "启用"}</small></span>
    </button><button type="button" class="organization-delete-user" data-delete-user="${esc(user.id)}" aria-label="删除成员 ${esc(user.name || user.account || "未命名成员")}" title="删除成员"${user.current ? " disabled" : ""}>${trashIcon}</button></li>`).join("");
    return `<aside class="organization-member-list" aria-label="成员列表"><header><strong>成员（${users.length}）</strong><span>部门与角色</span></header><ul>${items || '<li class="organization-empty">没有符合条件的成员</li>'}</ul></aside>`;
  }

  function memberEvents(user) {
    if (!user) return [];
    return state.audit.filter((event) => String(event.actor_id || "") === String(user.id) || String(event.target || "") === String(user.id));
  }

  function auditAction(event) {
    return ({ "fault.mark_handled": "处理告警", "news_review.update": "复核新闻", "organization.user_update": "修改成员权限", "organization.user_import": "添加组织成员", "organization.user_delete": "删除组织成员" })[event.action] || event.action || "系统操作";
  }

  function auditTime(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return String(value || "—");
    return date.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Hong_Kong" });
  }

  function eventList(user) {
    const events = memberEvents(user);
    const rows = events.map((event) => `<li><span class="organization-event-dot ${event.result === "failure" ? "is-failure" : ""}"></span><span><strong>${esc(auditAction(event))}</strong><small>${esc(event.target || "—")} · ${esc(auditTime(event.at))}</small></span><em>${String(event.actor_id || "") === String(user.id) ? "本人操作" : "成员变更"}</em></li>`).join("");
    return `<section class="organization-detail-section organization-member-events"><header><div><h3>个人行动记录</h3><p>来自独立操作审计日志，按当前成员身份或成员对象筛选。</p></div><strong>${events.length} 条</strong></header><ul>${rows || '<li class="organization-detail-empty">暂无可审计行动记录</li>'}</ul></section>`;
  }

  function memberDetail(user) {
    if (!user) return '<section class="organization-member-detail"><div class="organization-detail-empty">请选择一名成员查看资料与权限</div></section>';
    const checks = Object.entries(state.modules).map(([key, label]) => {
      const checked = user.modules?.[key] === true;
      const protectedPermission = user.current && key === "organization";
      return `<label class="organization-permission"><input type="checkbox" data-module="${esc(key)}"${checked ? " checked" : ""}${protectedPermission ? " disabled" : ""} /><span><strong>${esc(label)}</strong><small>${esc(key)}.view</small></span></label>`;
    }).join("");
    const enabled = Object.values(user.modules || {}).filter(Boolean).length;
    return `<section class="organization-member-detail" data-user-id="${esc(user.id)}">
      <header class="organization-profile-heading">${avatar(user, "is-profile")}<div><h2>${esc(user.name || user.account || "未命名成员")}</h2><p>${esc(user.account || user.email || "—")}</p></div><span class="organization-account-state ${user.status === "disabled" ? "is-disabled" : ""}">${user.status === "disabled" ? "已停用" : "启用"}</span></header>
      <section class="organization-detail-section"><h3>组织信息</h3><dl class="organization-info-grid"><div><dt>所属部门</dt><dd>${esc(user.department || (user.authProvider === "feishu" ? "飞书未提供" : "—"))}</dd></div><div><dt>员工岗位</dt><dd>${esc(user.title || (user.authProvider === "feishu" ? "飞书未填写" : "—"))}</dd></div></dl></section>
      <section class="organization-detail-section"><h3>成员资料</h3><dl class="organization-info-grid is-three"><div><dt>企业邮箱</dt><dd>${esc(user.email || "—")}</dd></div><div><dt>登录账号</dt><dd>${esc(user.account || "—")}</dd></div><div><dt>身份来源</dt><dd>${user.authProvider === "feishu" ? "飞书企业身份" : "本地账号"}</dd></div></dl></section>
      <section class="organization-detail-section"><h3>角色与账号</h3><div class="organization-control-grid"><label><span>角色层级</span><select class="organization-select" data-role>${roleOptions(user)}</select></label><label><span>账号状态</span><select class="organization-select" data-status${user.current ? " disabled" : ""}><option value="active"${user.status === "active" ? " selected" : ""}>启用</option><option value="disabled"${user.status === "disabled" ? " selected" : ""}>停用</option></select></label></div></section>
      <section class="organization-detail-section"><header><div><h3>功能权限</h3><p>控制该成员可查看和使用的工作页签。</p></div><strong data-permission-count>已启用 ${enabled} / ${Object.keys(state.modules).length} 项</strong></header><div class="organization-permission-grid">${checks}</div></section>
      <footer class="organization-save-bar"><span data-row-status aria-live="polite">选择角色或权限后保存</span><button type="button" data-save disabled>保存成员权限</button></footer>
      ${eventList(user)}
    </section>`;
  }

  function auditSurface() {
    const rows = state.audit.map((event) => `<tr><td><div class="organization-member">${avatar({ name: event.actor_name, avatar_url: event.actor_avatar_url }, "is-audit")}<span><strong>${esc(event.actor_name || "未知用户")}</strong><small>${esc(event.actor_id || "—")}</small></span></div></td><td><strong>${esc(auditAction(event))}</strong><small>${esc(event.target || "—")}</small></td><td><span class="organization-audit-result ${event.result === "failure" ? "is-failure" : "is-success"}">${event.result === "failure" ? "失败" : "成功"}</span></td><td>${esc(auditTime(event.at))}</td></tr>`).join("");
    return `<section class="organization-surface organization-audit-surface"><header><div><span>OPERATION AUDIT</span><h2>可审计操作记录</h2><p>独立记录告警处理、新闻复核与成员权限变更，管理员可按登录身份追踪操作人。</p></div><strong>${state.audit.length} 条</strong></header><div class="organization-table-wrap"><table class="organization-table organization-audit-table"><thead><tr><th>操作人</th><th>动作与对象</th><th>结果</th><th>时间</th></tr></thead><tbody>${rows || '<tr><td colspan="4"><div class="organization-empty">暂无操作审计记录</div></td></tr>'}</tbody></table></div></section>`;
  }

  function directoryResults() {
    const directory = state.directory;
    if (directory.loading) return '<div class="organization-directory-state">正在搜索飞书通讯录…</div>';
    if (directory.error) return `<div class="organization-directory-state is-error">${esc(directory.error)}</div>`;
    if (directory.query.trim().length < 2) return '<div class="organization-directory-state">请输入至少 2 个字符，可按姓名或企业邮箱搜索。</div>';
    if (!directory.users.length) return '<div class="organization-directory-state">飞书通讯录中没有匹配成员。</div>';
    return `<div class="organization-directory-list">${directory.users.map((user) => `<article class="organization-directory-user" data-directory-email="${esc(user.email)}">${avatar(user, "is-directory")}<span><strong>${esc(user.name || "未命名成员")}</strong><small>${esc([user.department, user.email].filter(Boolean).join(" · ") || "—")}</small></span><button type="button" data-import-email="${esc(user.email)}"${user.added ? " disabled" : ""}>${user.added ? "已添加" : "加入组织"}</button></article>`).join("")}</div>`;
  }

  function directoryPanel() {
    if (!state.directory.open) return "";
    return `<section class="organization-directory" aria-labelledby="directoryTitle"><header><div><strong id="directoryTitle">添加飞书成员</strong><span>从 CMHK 飞书通讯录加入权限名单，成员头像与资料以飞书企业身份为准。</span></div><button type="button" data-directory-close aria-label="关闭添加成员">×</button></header><label><span class="sr-only">搜索飞书成员</span><input type="search" data-directory-search value="${esc(state.directory.query)}" placeholder="输入姓名或企业邮箱（至少 2 个字符）" autocomplete="off" /></label><div data-directory-results aria-live="polite">${directoryResults()}</div></section>`;
  }

  function render() {
    const users = filteredUsers();
    const selected = selectedUser(users);
    const roleFilter = `<option value="">全部角色</option>${Object.entries(state.roles).map(([value, label]) => `<option value="${esc(value)}"${state.role === value ? " selected" : ""}>${esc(label)}</option>`).join("")}`;
    host.innerHTML = `<header class="organization-heading"><div><span>ORGANIZATION &amp; ACCESS</span><h1>组织管理</h1><p>点击成员查看真实个人资料、个人行动记录并配置角色与功能权限。</p></div></header>
      ${directoryPanel()}
      <section class="organization-surface organization-access-surface">
        <div class="organization-toolbar"><label><span class="sr-only">搜索成员</span><input type="search" data-search value="${esc(state.query)}" placeholder="搜索姓名、账号或部门" /></label><label><span class="sr-only">筛选部门</span><select data-department-filter>${selectOptions(state.departments, state.department, "全部部门")}</select></label><label><span class="sr-only">筛选角色</span><select data-role-filter>${roleFilter}</select></label><button type="button" class="organization-add-member" data-directory-open aria-label="添加成员" title="添加成员">＋</button></div>
        <div class="organization-access-layout">${memberList(users, selected)}${memberDetail(selected)}</div>
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
      const [payload, auditPayload] = await Promise.all([request("/api/auth/admin/users"), request("/api/auth/admin/audit?limit=200")]);
      const loadedUsers = Array.isArray(payload.users) ? payload.users : [];
      const hasEnterpriseMembers = loadedUsers.some((user) => user.authProvider === "feishu");
      state.users = hasEnterpriseMembers ? loadedUsers.filter((user) => !user.developmentAccount) : loadedUsers;
      state.departments = [...new Set(state.users.map((user) => user.department).filter(Boolean))].sort();
      state.roles = payload.roles || {};
      state.modules = payload.modules || {};
      state.roleModules = payload.roleModules || {};
      state.audit = Array.isArray(auditPayload.events) ? auditPayload.events : [];
      if (!state.selectedUserId && state.users.length) state.selectedUserId = String(state.users[0].id);
      state.loaded = true;
      render();
    } catch (error) { renderError(error.message); }
    finally { state.loading = false; }
  }

  function renderDirectoryResults() {
    const results = host.querySelector("[data-directory-results]");
    if (results) results.innerHTML = directoryResults();
  }

  async function searchDirectory() {
    const query = state.directory.query.trim();
    if (query.length < 2) { state.directory.loading = false; state.directory.users = []; state.directory.error = ""; renderDirectoryResults(); return; }
    state.directory.loading = true; state.directory.error = ""; renderDirectoryResults();
    try {
      const payload = await request(`/api/auth/admin/directory/search?q=${encodeURIComponent(query)}`);
      if (query !== state.directory.query.trim()) return;
      state.directory.users = Array.isArray(payload.users) ? payload.users : [];
    } catch (error) { state.directory.users = []; state.directory.error = error.message; }
    finally { if (query === state.directory.query.trim()) { state.directory.loading = false; renderDirectoryResults(); } }
  }

  async function importDirectoryUser(button) {
    const email = button.dataset.importEmail;
    if (!email) return;
    button.disabled = true; button.textContent = "添加中…";
    try {
      const payload = await request("/api/auth/admin/users/import", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email }) });
      state.selectedUserId = String(payload.user?.id || "");
      await load({ force: true });
    } catch (error) { button.disabled = false; button.textContent = "重试"; state.directory.error = error.message; renderDirectoryResults(); }
  }

  function markDirty(detail) {
    detail.classList.add("is-dirty");
    const button = detail.querySelector("[data-save]");
    if (button) button.disabled = false;
    const status = detail.querySelector("[data-row-status]");
    if (status) { status.textContent = "有未保存修改"; status.classList.remove("is-error"); }
    const count = [...detail.querySelectorAll("[data-module]")].filter((input) => input.checked).length;
    const countHost = detail.querySelector("[data-permission-count]");
    if (countHost) countHost.textContent = `已启用 ${count} / ${Object.keys(state.modules).length} 项`;
  }

  function applyRoleDefaults(detail, role) {
    const defaults = state.roleModules[role] || {};
    detail.querySelectorAll("[data-module]").forEach((input) => {
      input.checked = defaults[input.dataset.module] === true;
      if (detail.dataset.userId === state.users.find((user) => user.current)?.id && input.dataset.module === "organization") input.checked = true;
    });
    markDirty(detail);
  }

  async function save(detail) {
    const button = detail.querySelector("[data-save]");
    const rowStatus = detail.querySelector("[data-row-status]");
    const modules = Object.fromEntries([...detail.querySelectorAll("[data-module]")].map((input) => [input.dataset.module, input.checked]));
    button.disabled = true; button.textContent = "保存中…"; rowStatus.textContent = "正在写入权限";
    try {
      await request(`/api/auth/admin/users/${encodeURIComponent(detail.dataset.userId)}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: detail.querySelector("[data-role]").value, status: detail.querySelector("[data-status]").value, modules }) });
      rowStatus.textContent = "已保存并写入审计记录"; button.textContent = "保存成员权限";
      window.setTimeout(() => load({ force: true }), 450);
    } catch (error) { rowStatus.textContent = error.message; rowStatus.classList.add("is-error"); button.disabled = false; button.textContent = "重试"; }
  }

  async function removeUser(button) {
    const userId = button.dataset.deleteUser;
    const user = state.users.find((item) => String(item.id) === String(userId));
    if (!userId || !user) return;
    if (!window.confirm(`确认从组织中删除“${user.name || user.account}”？该成员的现有登录会话会同时失效。`)) return;
    button.disabled = true;
    try {
      await request(`/api/auth/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
      if (state.selectedUserId === userId) state.selectedUserId = "";
      await load({ force: true });
    } catch (error) {
      button.disabled = false;
      window.alert(error.message);
    }
  }

  host.addEventListener("input", (event) => {
    if (event.target.matches("[data-directory-search]")) { state.directory.query = event.target.value; window.clearTimeout(state.directory.timer); state.directory.timer = window.setTimeout(searchDirectory, 320); return; }
    if (!event.target.matches("[data-search]")) return;
    state.query = event.target.value; render();
    const search = host.querySelector("[data-search]"); search?.focus(); search?.setSelectionRange(state.query.length, state.query.length);
  });
  host.addEventListener("change", (event) => {
    if (event.target.matches("[data-department-filter]")) { state.department = event.target.value; render(); return; }
    if (event.target.matches("[data-role-filter]")) { state.role = event.target.value; render(); return; }
    const detail = event.target.closest("[data-user-id]");
    if (!detail) return;
    if (event.target.matches("[data-role]")) applyRoleDefaults(detail, event.target.value);
    else if (event.target.matches("[data-status], [data-module]")) markDirty(detail);
  });
  host.addEventListener("click", (event) => {
    const deleteButton = event.target.closest("[data-delete-user]");
    if (deleteButton) { removeUser(deleteButton); return; }
    const select = event.target.closest("[data-select-user]");
    if (select) { state.selectedUserId = select.dataset.selectUser; render(); return; }
    if (event.target.closest("[data-directory-open]")) { state.directory.open = true; render(); host.querySelector("[data-directory-search]")?.focus(); return; }
    if (event.target.closest("[data-directory-close]")) { state.directory.open = false; render(); return; }
    const importButton = event.target.closest("[data-import-email]");
    if (importButton) { importDirectoryUser(importButton); return; }
    if (event.target.closest("[data-refresh]")) { load({ force: true }); return; }
    const saveButton = event.target.closest("[data-save]");
    if (saveButton) save(saveButton.closest("[data-user-id]"));
  });

  window.addEventListener("workspace-tab-change", (event) => { if (event.detail?.tab === "organization") load(); });
  window.CMHKOrganizationAdmin = { load };
})();
