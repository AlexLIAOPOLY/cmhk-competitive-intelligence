(() => {
  "use strict";

  const controlHost = document.getElementById("organizationAdmin");
  const footprintHost = document.getElementById("organizationFootprint");
  const hosts = [controlHost, footprintHost].filter(Boolean);
  if (!hosts.length) return;
  const state = {
    loaded: false, loading: false, query: "", department: "", role: "", selectedUserId: "",
    users: [], departments: [], roles: {}, modules: {}, roleModules: {}, audit: [], incidents: [],
    view: "control", profileKey: "", eventKey: "", auditQuery: "", auditAction: "", auditResult: "",
    directory: { open: false, query: "", loading: false, users: [], error: "", timer: null },
  };
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const escapeRegExp = (value) => String(value ?? "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  function highlightSearchMatch(value, query) {
    const text = String(value ?? "");
    const keyword = String(query ?? "").trim();
    if (!keyword) return esc(text);
    const matcher = new RegExp(escapeRegExp(keyword), "giu");
    let cursor = 0;
    let html = "";
    for (const match of text.matchAll(matcher)) {
      html += esc(text.slice(cursor, match.index));
      html += `<mark class="organization-search-match">${esc(match[0])}</mark>`;
      cursor = match.index + match[0].length;
    }
    return html + esc(text.slice(cursor));
  }

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

  function profileKey(person) {
    return String(person.id || person.actor_id || person.email || person.account || person.name || person.actor_name || "unknown");
  }

  function profileButton(person, size = "is-member") {
    const name = String(person.name || person.actor_name || person.account || "用户");
    return `<button type="button" class="organization-avatar-button" data-profile-key="${esc(profileKey(person))}" aria-label="查看 ${esc(name)} 的详情" aria-haspopup="dialog">${avatar(person, size)}</button>`;
  }

  function memberIdentity(user) {
    const secondary = user.account || user.email || "—";
    return `<span class="organization-member"><span><strong>${esc(user.name || user.account || "未命名成员")}${user.current ? '<em>当前管理员</em>' : ""}</strong><small>${esc(secondary)}</small></span></span>`;
  }

  function roleOptions(user) {
    return Object.entries(state.roles).map(([value, label]) => `<option value="${esc(value)}"${user.role === value ? " selected" : ""}>${esc(label)}</option>`).join("");
  }

  function selectOptions(values, current, allLabel) {
    return `<option value="">${esc(allLabel)}</option>${values.map((value) => `<option value="${esc(value)}"${value === current ? " selected" : ""}>${esc(value)}</option>`).join("")}`;
  }

  function addMemberIcon() {
    return '<svg class="organization-add-member-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="9" cy="7" r="3.25" /><path d="M3.5 19.5c.2-3.7 2.3-5.8 5.5-5.8s5.3 2.1 5.5 5.8M18.25 7.75v6.5M15 11h6.5" /></svg>';
  }

  function memberList(users, selected) {
    const trashIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4h6v3m-8 0 1 13h8l1-13M10 11v5m4-5v5" /></svg>';
    const items = users.map((user) => `<li class="organization-member-entry">${profileButton(user)}<button type="button" class="organization-member-row${selected?.id === user.id ? " is-selected" : ""}" data-select-user="${esc(user.id)}" aria-pressed="${selected?.id === user.id}">
      ${memberIdentity(user)}
      <span class="organization-member-meta"><strong>${esc(user.department || "未填写部门")}</strong><small>${esc(user.roleLabel || "待分配")} · ${user.status === "disabled" ? "已停用" : "启用"}</small></span>
    </button><button type="button" class="organization-delete-user" data-delete-user="${esc(user.id)}" aria-label="删除成员 ${esc(user.name || user.account || "未命名成员")}" title="删除成员"${user.current ? " disabled" : ""}>${trashIcon}</button></li>`).join("");
    return `<aside class="organization-member-list" aria-label="成员列表"><header><strong>成员（${users.length}）</strong><span>部门与角色</span></header><ul>${items || '<li class="organization-empty">没有符合条件的成员</li>'}</ul></aside>`;
  }

  function auditAction(event) {
    return ({ "fault.mark_handled": "处理告警", "news_review.update": "复核新闻", "organization.user_update": "修改成员权限", "organization.user_import": "添加组织成员", "organization.user_delete": "删除组织成员" })[event.action] || event.action || "系统操作";
  }

  function auditTime(value) {
    const date = new Date(String(value || ""));
    if (Number.isNaN(date.getTime())) return String(value || "—");
    return date.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Hong_Kong" });
  }

  function detailSection({ title, summary, body, open = false, className = "" }) {
    const chevron = '<span class="organization-section-chevron" aria-hidden="true"></span>';
    return `<details class="organization-detail-section ${className}"${open ? " open" : ""}><summary class="organization-section-summary"><span class="organization-section-copy"><h3>${esc(title)}</h3>${summary ? `<small>${esc(summary)}</small>` : ""}</span>${chevron}</summary><div class="organization-section-body">${body}</div></details>`;
  }

  function memberDetail(user) {
    if (!user) return '<section class="organization-member-detail"><div class="organization-detail-empty">请选择一名成员查看资料与权限</div></section>';
    const checks = Object.entries(state.modules).map(([key, label]) => {
      const checked = user.modules?.[key] === true;
      const protectedPermission = user.current && key === "organization";
      return `<label class="organization-permission"><input type="checkbox" data-module="${esc(key)}"${checked ? " checked" : ""}${protectedPermission ? " disabled" : ""} /><span><strong>${esc(label)}</strong><small>${esc(key)}.view</small></span></label>`;
    }).join("");
    const enabled = Object.values(user.modules || {}).filter(Boolean).length;
    const organization = `<dl class="organization-info-grid"><div><dt>所属部门</dt><dd>${esc(user.department || (user.authProvider === "feishu" ? "飞书未提供" : "—"))}</dd></div><div><dt>员工岗位</dt><dd>${esc(user.title || (user.authProvider === "feishu" ? "飞书未提供" : "—"))}</dd></div></dl>`;
    const profile = `<dl class="organization-info-grid is-three"><div><dt>企业邮箱</dt><dd>${esc(user.email || "—")}</dd></div><div><dt>登录账号</dt><dd>${esc(user.account || "—")}</dd></div><div><dt>身份来源</dt><dd>${user.authProvider === "feishu" ? "飞书企业身份" : "本地账号"}</dd></div></dl>`;
    const account = `<div class="organization-control-grid"><label><span>角色层级</span><select class="organization-select" data-role>${roleOptions(user)}</select></label><label><span>账号状态</span><select class="organization-select" data-status${user.current ? " disabled" : ""}><option value="active"${user.status === "active" ? " selected" : ""}>启用</option><option value="disabled"${user.status === "disabled" ? " selected" : ""}>停用</option></select></label></div>`;
    const permissions = `<div class="organization-permission-grid">${checks}</div>`;
    return `<section class="organization-member-detail" data-user-id="${esc(user.id)}">
      <header class="organization-profile-heading">${avatar(user, "is-profile")}<div><h2>${esc(user.name || user.account || "未命名成员")}</h2><p>${esc(user.account || user.email || "—")}</p></div><span class="organization-account-state ${user.status === "disabled" ? "is-disabled" : ""}">${user.status === "disabled" ? "已停用" : "启用"}</span></header>
      ${detailSection({ title: "组织信息", summary: user.department || "部门资料未填写", body: organization, open: true })}
      ${detailSection({ title: "成员资料", summary: user.authProvider === "feishu" ? "飞书企业身份" : "本地账号", body: profile, open: true })}
      ${detailSection({ title: "角色与账号", summary: `${user.roleLabel || "待分配"} · ${user.status === "disabled" ? "已停用" : "启用"}`, body: account, open: true })}
      <details class="organization-detail-section"><summary class="organization-section-summary"><span class="organization-section-copy"><h3>功能权限</h3><small data-permission-count>已启用 ${enabled} / ${Object.keys(state.modules).length} 项</small></span><span class="organization-section-chevron" aria-hidden="true"></span></summary><div class="organization-section-body">${permissions}</div></details>
      <footer class="organization-save-bar"><span data-row-status aria-live="polite">修改角色或权限后保存</span><button type="button" data-save disabled>保存成员资料</button></footer>
    </section>`;
  }

  function eventPerson(event) {
    return state.users.find((user) => String(user.id) === String(event.actor_id)) || {
      id: event.actor_id,
      name: event.actor_name || "未知用户",
      avatar_url: event.actor_avatar_url,
    };
  }

  function eventTarget(event) {
    const details = event.details || {};
    const memberName = String(event.target_label || details.name || details.member_name || "").trim();
    const member = state.users.find((user) => String(user.id) === String(event.target_member_id || ""))
      || state.users.find((user) => memberName && String(user.name || "") === memberName);
    if (event.target_type === "member" || event.action === "organization.user_import") {
      return { type: "member", label: member?.name || memberName || "组织成员", person: member || null };
    }
    const incident = state.incidents.find((item) => String(item.incident_id || "") === String(event.target || ""));
    if (event.target_type === "fault" || event.action === "fault.mark_handled") {
      return { type: "fault", label: String(event.target_label || incident?.title || incident?.summary || "故障记录"), person: null };
    }
    return { type: "record", label: String(event.target_label || "操作记录"), person: null };
  }

  function targetCell(event) {
    const target = eventTarget(event);
    if (target.type === "member" && target.person) {
      return `<button type="button" class="organization-target-person" data-profile-key="${esc(profileKey(target.person))}" aria-label="查看成员 ${esc(target.label)} 的详情" aria-haspopup="dialog">${avatar(target.person, "is-audit")}<span><strong>${esc(target.label)}</strong><small>组织成员</small></span></button>`;
    }
    const kind = target.type === "fault" ? "故障" : "处理对象";
    return `<button type="button" class="organization-event-button is-target" data-event-key="${esc(event.id)}" aria-label="查看${kind} ${esc(target.label)} 的足迹详情" aria-haspopup="dialog"><strong>${esc(target.label)}</strong><small>${kind}</small></button>`;
  }

  function filteredAudit() {
    const query = state.auditQuery.trim().toLowerCase();
    return state.audit.filter((event) => {
      const person = eventPerson(event);
      const matchesQuery = !query || [person.name, person.department, person.title, person.roleLabel, auditAction(event), event.action, eventTarget(event).label, event.target]
        .some((value) => String(value || "").toLowerCase().includes(query));
      return matchesQuery && (!state.auditAction || event.action === state.auditAction) && (!state.auditResult || event.result === state.auditResult);
    });
  }

  function footprintSurface() {
    const events = filteredAudit();
    const actionOptions = [...new Set(state.audit.map((event) => String(event.action || "")).filter(Boolean))]
      .sort((left, right) => auditAction({ action: left }).localeCompare(auditAction({ action: right }), "zh-CN"))
      .map((action) => `<option value="${esc(action)}"${state.auditAction === action ? " selected" : ""}>${esc(auditAction({ action }))}</option>`)
      .join("");
    const rows = events.map((event) => {
      const person = eventPerson(event);
      const action = auditAction(event);
      return `<tr><td><div class="organization-member">${profileButton(person, "is-audit")}<span><strong>${esc(person.name || "未知用户")}</strong><small>${esc(person.department || person.roleLabel || "—")}</small></span></div></td><td><button type="button" class="organization-event-button is-action" data-event-key="${esc(event.id)}" aria-label="查看动作 ${esc(action)} 的足迹详情" aria-haspopup="dialog">${esc(action)}</button></td><td>${targetCell(event)}</td><td><span class="organization-audit-result ${event.result === "failure" ? "is-failure" : "is-success"}">${event.result === "failure" ? "失败" : "成功"}</span></td><td>${esc(auditTime(event.at))}</td></tr>`;
    }).join("");
    const count = events.length === state.audit.length ? `${state.audit.length} 条` : `${events.length} / ${state.audit.length} 条`;
    return `<section class="organization-surface organization-footprint-surface" aria-label="团队足迹"><div class="organization-footprint-bar"><strong>团队足迹</strong><span aria-live="polite">${count}</span></div><div class="organization-footprint-toolbar" aria-label="筛选团队足迹"><label><span class="sr-only">搜索成员、动作或处理对象</span><input type="search" data-audit-search value="${esc(state.auditQuery)}" placeholder="搜索成员、动作或处理对象" /></label><label><span class="sr-only">筛选动作</span><select data-audit-action-filter><option value="">全部动作</option>${actionOptions}</select></label><label><span class="sr-only">筛选结果</span><select data-audit-result-filter><option value="">全部结果</option><option value="success"${state.auditResult === "success" ? " selected" : ""}>成功</option><option value="failure"${state.auditResult === "failure" ? " selected" : ""}>失败</option></select></label></div><div class="organization-table-wrap"><table class="organization-table organization-audit-table"><thead><tr><th>成员</th><th>动作</th><th>处理对象</th><th>结果</th><th>时间</th></tr></thead><tbody>${rows || '<tr><td colspan="5"><div class="organization-empty">没有符合筛选条件的团队足迹</div></td></tr>'}</tbody></table></div></section>`;
  }

  function profilePerson() {
    if (!state.profileKey) return null;
    return state.users.find((user) => profileKey(user) === state.profileKey)
      || state.audit.map(eventPerson).find((person) => profileKey(person) === state.profileKey)
      || null;
  }

  function profileCard() {
    const person = profilePerson();
    if (!person) return "";
    const status = person.status === "disabled" ? "已停用" : "启用";
    return `<section class="organization-profile-card" role="dialog" aria-modal="false" aria-label="${esc(person.name || "成员")}的成员详情" tabindex="-1">
      <button type="button" class="organization-profile-close" data-profile-close aria-label="关闭成员详情">×</button>
      <header>${avatar(person, "is-profile-card")}<div><h2>${esc(person.name || person.account || "未命名成员")}</h2><span>${esc(person.title || person.roleLabel || "团队成员")}</span></div><em class="organization-account-state ${person.status === "disabled" ? "is-disabled" : ""}">${status}</em></header>
      <dl><div><dt>部门</dt><dd>${esc(person.department || "—")}</dd></div><div><dt>岗位</dt><dd>${esc(person.title || "—")}</dd></div><div><dt>邮箱</dt><dd>${esc(person.email || "—")}</dd></div><div><dt>账号</dt><dd>${esc(person.account || person.actor_id || "—")}</dd></div></dl>
    </section>`;
  }

  function eventCard() {
    const event = state.audit.find((item) => String(item.id) === state.eventKey);
    if (!event) return "";
    const person = eventPerson(event);
    const target = eventTarget(event);
    const labels = { email: "成员邮箱", name: "成员姓名", handler_name: "处理人", feishu_sync: "飞书同步", sheet_row: "表格行", error: "失败原因" };
    const details = Object.entries(event.details || {}).map(([key, value]) => `<div><dt>${esc(labels[key] || key)}</dt><dd>${esc(typeof value === "object" ? JSON.stringify(value) : value || "—")}</dd></div>`).join("");
    return `<section class="organization-event-card" role="dialog" aria-modal="false" aria-label="足迹详情" tabindex="-1">
      <button type="button" class="organization-profile-close" data-event-close aria-label="关闭足迹详情">×</button>
      <header><span>${avatar(person, "is-audit")}</span><div><small>团队足迹</small><h2>${esc(auditAction(event))}</h2><p>${esc(target.label)}</p></div><em class="organization-audit-result ${event.result === "failure" ? "is-failure" : "is-success"}">${event.result === "failure" ? "失败" : "成功"}</em></header>
      <dl><div><dt>操作成员</dt><dd>${esc(person.name || "未知用户")}</dd></div><div><dt>处理对象</dt><dd>${esc(target.label)}</dd></div><div><dt>发生时间</dt><dd>${esc(auditTime(event.at))}</dd></div>${event.target ? `<div><dt>追踪编号</dt><dd>${esc(event.target)}</dd></div>` : ""}${details}</dl>
    </section>`;
  }

  function controlSurface(users, selected, roleFilter) {
    return `${directoryPanel()}<section class="organization-surface organization-access-surface" aria-label="团队管理">
      <div class="organization-toolbar"><label><span class="sr-only">搜索成员</span><input type="search" data-search value="${esc(state.query)}" placeholder="搜索姓名、账号或部门" /></label><label><span class="sr-only">筛选部门</span><select data-department-filter>${selectOptions(state.departments, state.department, "全部部门")}</select></label><label><span class="sr-only">筛选角色</span><select data-role-filter>${roleFilter}</select></label><button type="button" class="organization-add-member" data-directory-open aria-label="添加成员" title="添加成员">${addMemberIcon()}</button></div>
      <div class="organization-access-layout">${memberList(users, selected)}${memberDetail(selected)}</div>
    </section>`;
  }

  function directoryResults() {
    const directory = state.directory;
    if (directory.loading) return '<div class="organization-directory-state">正在搜索飞书通讯录…</div>';
    if (directory.error) return `<div class="organization-directory-state is-error">${esc(directory.error)}</div>`;
    if (directory.query.trim().length < 2) return '<div class="organization-directory-state">请输入至少 2 个字符，可按姓名或企业邮箱搜索。</div>';
    if (!directory.users.length) return '<div class="organization-directory-state">飞书通讯录中没有匹配成员。</div>';
    return `<div class="organization-directory-list">${directory.users.map((user) => `<article class="organization-directory-user" data-directory-email="${esc(user.email)}">${avatar(user, "is-directory")}<span><strong>${highlightSearchMatch(user.name || "未命名成员", directory.query)}</strong><small>${highlightSearchMatch([user.department, user.email].filter(Boolean).join(" · ") || "—", directory.query)}</small></span><button type="button" data-import-email="${esc(user.email)}"${user.added ? " disabled" : ""}>${user.added ? "已添加" : "加入组织"}</button></article>`).join("")}</div>`;
  }

  function directoryPanel() {
    if (!state.directory.open) return "";
    return `<section class="organization-directory" aria-labelledby="directoryTitle"><header><div><strong id="directoryTitle">添加飞书成员</strong><span>从 CMHK 飞书通讯录加入权限名单，成员头像与资料以飞书企业身份为准。</span></div><button type="button" data-directory-close aria-label="关闭添加成员">×</button></header><label><span class="sr-only">搜索飞书成员</span><input type="search" data-directory-search value="${esc(state.directory.query)}" placeholder="输入姓名或企业邮箱（至少 2 个字符）" autocomplete="off" /></label><div data-directory-results aria-live="polite">${directoryResults()}</div></section>`;
  }

  function render() {
    const users = filteredUsers();
    const selected = selectedUser(users);
    const roleFilter = `<option value="">全部角色</option>${Object.entries(state.roles).map(([value, label]) => `<option value="${esc(value)}"${state.role === value ? " selected" : ""}>${esc(label)}</option>`).join("")}`;
    if (controlHost) controlHost.innerHTML = `${controlSurface(users, selected, roleFilter)}${state.view === "control" ? profileCard() : ""}`;
    if (footprintHost) footprintHost.innerHTML = `${footprintSurface()}${state.view === "footprint" ? profileCard() + eventCard() : ""}`;
    if (state.profileKey || state.eventKey) window.requestAnimationFrame(() => activeHost()?.querySelector(".organization-profile-card, .organization-event-card")?.focus());
  }

  function activeHost() {
    return state.view === "footprint" ? footprintHost : controlHost;
  }

  function renderError(message) {
    hosts.forEach((host) => { host.innerHTML = `<div class="organization-error" role="alert"><strong>组织信息读取失败</strong><p>${esc(message)}</p><button type="button" data-refresh>重新读取</button></div>`; });
  }

  async function load({ force = false } = {}) {
    if (state.loading || (state.loaded && !force)) return;
    state.loading = true;
    if (!state.loaded) hosts.forEach((host) => { host.innerHTML = '<div class="organization-loading" role="status">正在读取组织成员与权限…</div>'; });
    try {
      const [payload, auditPayload, incidentsPayload] = await Promise.all([request("/api/auth/admin/users"), request("/api/auth/admin/audit?limit=200"), request("/api/project-incidents?limit=500")]);
      const loadedUsers = Array.isArray(payload.users) ? payload.users : [];
      const hasEnterpriseMembers = loadedUsers.some((user) => user.authProvider === "feishu");
      state.users = hasEnterpriseMembers ? loadedUsers.filter((user) => !user.developmentAccount) : loadedUsers;
      state.departments = [...new Set(state.users.map((user) => user.department).filter(Boolean))].sort();
      state.roles = payload.roles || {};
      state.modules = payload.modules || {};
      state.roleModules = payload.roleModules || {};
      state.audit = Array.isArray(auditPayload.events) ? auditPayload.events : [];
      state.incidents = Array.isArray(incidentsPayload.incidents) ? incidentsPayload.incidents : [];
      if (!state.selectedUserId && state.users.length) state.selectedUserId = String(state.users[0].id);
      state.loaded = true;
      render();
    } catch (error) { renderError(error.message); }
    finally { state.loading = false; }
  }

  function renderDirectoryResults() {
    const results = controlHost?.querySelector("[data-directory-results]");
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
      rowStatus.textContent = "已保存并写入审计记录"; button.textContent = "保存成员资料";
      window.setTimeout(() => load({ force: true }), 450);
    } catch (error) { rowStatus.textContent = error.message; rowStatus.classList.add("is-error"); button.disabled = false; button.textContent = "重试"; }
  }

  async function removeUser(button) {
    const userId = button.dataset.deleteUser;
    const user = state.users.find((item) => String(item.id) === String(userId));
    if (!userId || !user) return;
    const confirmed = await window.CMHKDialog.confirm({
      tone: "danger",
      title: `从组织中删除“${user.name || user.account}”？`,
      message: "该成员将失去项目访问权限，现有登录会话会同时失效。",
      detail: "删除动作会绑定当前管理员身份并写入团队足迹。",
      confirmLabel: "确认删除成员",
    });
    if (!confirmed) return;
    button.disabled = true;
    try {
      await request(`/api/auth/admin/users/${encodeURIComponent(userId)}`, { method: "DELETE" });
      if (state.selectedUserId === userId) state.selectedUserId = "";
      await load({ force: true });
    } catch (error) {
      button.disabled = false;
      await window.CMHKDialog.alert({ tone: "danger", title: "成员删除失败", message: error.message });
    }
  }

  hosts.forEach((host) => {
    host.addEventListener("input", (event) => {
      if (event.target.matches("[data-directory-search]")) { state.directory.query = event.target.value; window.clearTimeout(state.directory.timer); state.directory.timer = window.setTimeout(searchDirectory, 320); return; }
      if (event.target.matches("[data-audit-search]")) { state.auditQuery = event.target.value; render(); const search = footprintHost?.querySelector("[data-audit-search]"); search?.focus(); search?.setSelectionRange(state.auditQuery.length, state.auditQuery.length); return; }
      if (!event.target.matches("[data-search]")) return;
      state.query = event.target.value; render();
      const search = controlHost?.querySelector("[data-search]"); search?.focus(); search?.setSelectionRange(state.query.length, state.query.length);
    });
    host.addEventListener("change", (event) => {
      if (event.target.matches("[data-audit-action-filter]")) { state.auditAction = event.target.value; render(); return; }
      if (event.target.matches("[data-audit-result-filter]")) { state.auditResult = event.target.value; render(); return; }
      if (event.target.matches("[data-department-filter]")) { state.department = event.target.value; render(); return; }
      if (event.target.matches("[data-role-filter]")) { state.role = event.target.value; render(); return; }
      const detail = event.target.closest("[data-user-id]");
      if (!detail) return;
      if (event.target.matches("[data-role]")) applyRoleDefaults(detail, event.target.value);
      else if (event.target.matches("[data-status], [data-module]")) markDirty(detail);
    });
    host.addEventListener("click", (event) => {
      const profile = event.target.closest("[data-profile-key]");
      if (profile) { state.profileKey = profile.dataset.profileKey; state.eventKey = ""; render(); return; }
      if (event.target.closest("[data-profile-close]")) { state.profileKey = ""; render(); return; }
      const eventButton = event.target.closest("[data-event-key]");
      if (eventButton) { state.eventKey = eventButton.dataset.eventKey; state.profileKey = ""; render(); return; }
      if (event.target.closest("[data-event-close]")) { state.eventKey = ""; render(); return; }
      const deleteButton = event.target.closest("[data-delete-user]");
      if (deleteButton) { removeUser(deleteButton); return; }
      const select = event.target.closest("[data-select-user]");
      if (select) { state.selectedUserId = select.dataset.selectUser; render(); return; }
      if (event.target.closest("[data-directory-open]")) { state.directory.open = true; render(); controlHost?.querySelector("[data-directory-search]")?.focus(); return; }
      if (event.target.closest("[data-directory-close]")) { state.directory.open = false; render(); return; }
      const importButton = event.target.closest("[data-import-email]");
      if (importButton) { importDirectoryUser(importButton); return; }
      if (event.target.closest("[data-refresh]")) { load({ force: true }); return; }
      const saveButton = event.target.closest("[data-save]");
      if (saveButton) { save(saveButton.closest("[data-user-id]")); return; }
      if ((state.profileKey || state.eventKey) && !event.target.closest(".organization-profile-card, .organization-event-card")) { state.profileKey = ""; state.eventKey = ""; render(); }
    });
    host.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && (state.profileKey || state.eventKey)) { state.profileKey = ""; state.eventKey = ""; render(); return; }
      if (!["Enter", " "].includes(event.key)) return;
      const summary = event.target.closest(".organization-section-summary, .organization-audit-summary");
      if (!summary) return;
      const disclosure = summary.closest("details");
      if (!disclosure) return;
      event.preventDefault();
      disclosure.open = !disclosure.open;
    });
  });

  window.addEventListener("workspace-tab-change", (event) => {
    if (!["organization", "footprint"].includes(event.detail?.tab)) return;
    state.view = event.detail.tab === "footprint" ? "footprint" : "control";
    state.profileKey = "";
    state.eventKey = "";
    if (state.loaded) render(); else load();
  });
  window.CMHKOrganizationAdmin = { load };
})();
