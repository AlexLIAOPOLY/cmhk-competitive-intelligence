(() => {
  "use strict";

  const root = document.querySelector("#subscriptionAdmin");
  const state = {
    data: null, briefs: [], searchResults: [], chatSearchResults: [], searchQuery: "",
    notice: "", noticeKind: "", activeView: "invite", drawerOpen: false, peopleOpen: false, drawerTab: "invitations",
  };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const highlight = (value, query = state.searchQuery) => {
    const text = String(value ?? "");
    const needle = String(query ?? "").trim();
    if (!needle) return esc(text);
    const pattern = new RegExp(`(${needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")})`, "giu");
    return text.split(pattern).map((part, index) => index % 2
      ? `<mark class="search-highlight">${esc(part)}</mark>`
      : esc(part)).join("");
  };
  const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const serviceLabel = (value) => ({ weekly: "战略双周报", performance: "运营商业绩摘要", news: "战略新闻" }[value] || value);
  const modeLabel = (value) => ({ text: "文字", pdf: "PDF 文件", pdf_audio: "PDF + 独立语音", audio: "语音", both: "文字 + 语音" }[value] || value);
  const invitationStatus = (value) => ({ pending: "等待选择", accepted: "已接受", paused: "已暂停", failed: "发送失败" }[value] || value);
  const icon = (name) => ({
    add: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 5 16 7-16 7 3-7-3-7Z"/><path d="M7 12h13"/></svg>',
    history: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h9"/><circle cx="18" cy="18" r="3"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  }[name] || "");
  const avatar = (item) => item.avatar_url
    ? `<img class="avatar" src="/api/subscriptions/avatar?openId=${encodeURIComponent(item.directory_open_id || item.callback_open_id || "")}" alt="" loading="lazy">`
    : `<span class="avatar avatar-fallback" aria-hidden="true">${esc((item.display_name || "飞").slice(0, 1))}</span>`;

  function serviceOptions() {
    return [["weekly", "战略双周报"], ["performance", "运营商业绩摘要"], ["news", "战略新闻"]]
      .map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  }

  function newsFrequencyOptions(selected = "once_daily") {
    const frequencies = state.data?.frequencies || [
      { key: "twice_daily", label: "每天两次" },
      { key: "once_daily", label: "每天一次" },
    ];
    return frequencies.map((item) => `<option value="${esc(item.key)}"${item.key === selected ? " selected" : ""}>${esc(item.label)}</option>`).join("");
  }

  function reportModeOptions(selected = "pdf") {
    const modes = state.data?.report_modes || [
      { key: "pdf", label: "仅 PDF" },
      { key: "pdf_audio", label: "PDF + 单独语音" },
      { key: "audio", label: "仅语音" },
    ];
    return modes.map((item) => `<option value="${esc(item.key)}"${item.key === selected ? " selected" : ""}>${esc(item.label)}</option>`).join("");
  }

  function reportOptions() {
    const reports = state.data?.reports || [];
    if (!reports.length) return '<option value="">当前没有可推送报告</option>';
    return reports.map((item) => `<option value="${esc(item.path)}" data-report-type="${esc(item.report_type)}" data-report-name="${esc(item.name)}">${esc(item.name)} · PDF</option>`).join("");
  }

  function outgoingNames(form) {
    const option = form?.elements.path?.selectedOptions?.[0];
    if (!option || form.elements.service.value === "news") return "";
    const service = form.elements.service.value;
    const serviceName = service === "weekly" ? "战略双周报" : "运营商业绩摘要";
    const original = option.dataset.reportName || option.textContent.split(" · ")[0] || "正式报告";
    const stem = original.replace(/\.docx$/i, "").replace(/[\\/:*?\"<>|\x00-\x1f]+/g, "_").replace(/^[ ._]+|[ ._]+$/g, "") || "正式报告";
    const prefix = stem.startsWith(serviceName) ? "CMHK_" : stem.startsWith(`CMHK_${serviceName}`) ? "" : `CMHK_${serviceName}_`;
    const filename = (suffix) => `${prefix}${stem.slice(0, Math.max(12, 120 - prefix.length - suffix.length))}${suffix}`;
    const mode = form.elements.mode.value;
    const names = [];
    if (["pdf", "pdf_audio"].includes(mode)) names.push(filename(".pdf"));
    if (["audio", "pdf_audio"].includes(mode)) names.push(filename("_音频.opus"));
    return names.join("；");
  }

  function subscriberRows() {
    const rows = state.data?.subscribers || [];
    if (!rows.length) return '<tr><td colspan="9" class="empty">尚无订阅者。先把测试卡片发给自己，确认后再发布到同事群。</td></tr>';
    return rows.map((item) => `<tr data-subscriber-row="${esc(item.open_id)}">
      <td class="name">${esc(item.display_name)}</td><td class="muted">${esc(item.open_id.slice(0, 8))}…</td>
      ${["weekly", "performance", "news"].map((service) => `<td><label class="service-check"><input type="checkbox" value="${service}"${item.services.includes(service) ? " checked" : ""}><span>${service === "weekly" ? "周报" : service === "performance" ? "业绩" : "新闻"}</span></label></td>`).join("")}
      <td><select data-subscriber-report-mode>${reportModeOptions(item.report_mode)}</select></td>
      <td><select data-subscriber-news-frequency>${newsFrequencyOptions(item.news_frequency || item.frequency)}</select></td>
      <td><select data-subscriber-status><option value="active"${item.status === "active" ? " selected" : ""}>启用</option><option value="paused"${item.status === "paused" ? " selected" : ""}>暂停</option></select></td>
      <td><button class="button" type="button" data-save-subscriber>保存</button></td></tr>`).join("");
  }

  function compactSubscriberRows() {
    const rows = state.data?.subscribers || [];
    if (!rows.length) return '<tr><td colspan="6" class="empty">尚无订阅者</td></tr>';
    return rows.map((item) => `<tr data-subscriber-row="${esc(item.open_id)}">
      <td><strong class="table-person-name">${esc(item.display_name)}</strong><small class="table-person-id">${esc(item.open_id.slice(0, 8))}…</small></td>
      <td><div class="service-group">${["weekly", "performance", "news"].map((service) => `<label class="service-check"><input type="checkbox" value="${service}"${item.services.includes(service) ? " checked" : ""}><span>${service === "weekly" ? "周报" : service === "performance" ? "业绩" : "新闻"}</span></label>`).join("")}</div></td>
      <td><select data-subscriber-report-mode>${reportModeOptions(item.report_mode)}</select></td>
      <td><select data-subscriber-news-frequency>${newsFrequencyOptions(item.news_frequency || item.frequency)}</select></td>
      <td><select data-subscriber-status><option value="active"${item.status === "active" ? " selected" : ""}>启用</option><option value="paused"${item.status === "paused" ? " selected" : ""}>暂停</option></select></td>
      <td><button class="button compact-save" type="button" data-save-subscriber>保存</button></td></tr>`).join("");
  }

  function deliveryRows() {
    const rows = state.data?.deliveries || [];
    if (!rows.length) return '<tr><td colspan="6" class="empty">尚无推送记录</td></tr>';
    return rows.slice(0, 40).map((item) => `<tr><td>${esc(item.created_at)}</td><td>${esc(serviceLabel(item.service))}</td><td>${esc(modeLabel(item.mode))}</td><td class="muted">${esc(item.content_ref || "—")}</td><td><span class="status ${esc(item.status)}">${item.status === "verified" ? "已发送并回读" : item.status === "queued" ? "等待重试" : item.status === "sending" ? "发送中" : item.status === "retrying" ? "等待重试" : item.status === "superseded" ? "已按新规则停用" : "失败"}</span></td><td title="${esc(item.error || "")}">${item.error ? esc(item.error.slice(0, 90)) : number(item.message_ids?.length || 0) + " 条消息"}</td></tr>`).join("");
  }

  function searchResultRows() {
    if (!state.searchQuery) return '<p class="empty compact">输入关键词检索飞书人员和群聊；搜索本身不会发送消息。</p>';
    const people = state.searchResults.map((item) => `<div class="person-row">
      ${avatar(item)}<span class="person-copy"><strong>${highlight(item.display_name)}</strong><small>${highlight([item.en_name, (item.department_names || []).join(" / ") || item.job_title].filter(Boolean).join(" · ") || "飞书用户")}</small></span>
      <button class="icon-button add" type="button" data-add-candidate="${esc(item.directory_open_id)}" aria-label="添加 ${esc(item.display_name)}" title="加入待邀请名单">${icon("add")}</button>
    </div>`).join("");
    const chats = state.chatSearchResults.map((item) => `<div class="person-row chat-row">
      <span class="avatar avatar-fallback chat-avatar" aria-hidden="true">群</span><span class="person-copy"><strong>${highlight(item.name)}</strong><small>${highlight(item.description || (item.external ? "外部群聊" : "飞书群聊"))}</small></span>
      <span class="result-type">群聊</span>
    </div>`).join("");
    if (!people && !chats) return `<p class="empty compact">没有找到包含“${esc(state.searchQuery)}”的人员或群聊。</p>`;
    return `${people ? `<div class="result-section-label">人员 · ${number(state.searchResults.length)}</div>${people}` : ""}${chats ? `<div class="result-section-label">群聊 · ${number(state.chatSearchResults.length)}</div>${chats}` : ""}`;
  }

  function candidateRows() {
    const rows = state.data?.invite_candidates || [];
    if (!rows.length) return '<p class="empty compact">尚无待邀请人员</p>';
    return rows.map((item) => `<label class="invite-row">
      <input type="checkbox" value="${esc(item.callback_open_id)}" data-invite-candidate>
      ${avatar(item)}<span class="person-copy"><strong>${esc(item.display_name)}</strong><small>${esc((item.department_names || []).join(" / ") || item.job_title || "已验证飞书用户")}</small></span>
      <span class="invite-meta"><span class="status ${esc(item.latest_invitation?.status || "pending")}">${esc(invitationStatus(item.latest_invitation?.status || "未邀请"))}</span><small>${esc(item.latest_invitation?.sent_at || "未发送")}</small></span>
    </label>`).join("");
  }

  function invitationRows() {
    const rows = state.data?.invitations || [];
    if (!rows.length) return '<tr><td colspan="4" class="empty">尚无邀请记录</td></tr>';
    return rows.slice(0, 60).map((item) => `<tr><td class="name">${esc(item.display_name)}</td><td>${esc(item.sent_at || "-")}</td><td><span class="status ${esc(item.status)}">${esc(invitationStatus(item.status))}</span></td><td class="muted">${esc(item.message_id || "-")}</td></tr>`).join("");
  }

  function drawerContent() {
    const data = state.data || {};
    if (state.drawerTab === "deliveries") {
      return `<div class="table-wrap"><table><thead><tr><th>时间</th><th>服务</th><th>方式</th><th>内容</th><th>状态</th><th>证据 / 错误</th></tr></thead><tbody>${deliveryRows()}</tbody></table></div>`;
    }
    return `<p class="drawer-summary">待选择 ${number(data.invitation_counts?.pending)} · 已接受 ${number(data.invitation_counts?.accepted)} · 失败 ${number(data.invitation_counts?.failed)}</p><div class="table-wrap"><table><thead><tr><th>人员</th><th>发送时间</th><th>状态</th><th>消息 ID</th></tr></thead><tbody>${invitationRows()}</tbody></table></div>`;
  }

  function render() {
    const data = state.data;
    if (!data) return;
    const latest = state.briefs[0] || {};
    const newsTitle = latest.title || latest.headline || "战略新闻推送";
    const newsBody = latest.summary || latest.brief || latest.description || "";
    const inviteCount = (data.invite_candidates || []).length;
    root.innerHTML = `<div class="admin">
      <header class="topbar"><h1>订阅与推送管理</h1><button class="icon-button management-button" type="button" data-open-management aria-label="查看管理记录" title="邀请结果、订阅者与推送记录">${icon("history")}<span class="icon-badge">${number((data.deliveries || []).length)}</span></button></header>
      ${state.notice ? `<p class="notice ${esc(state.noticeKind)}" role="status">${esc(state.notice)}</p>` : ""}
      <main class="three-block-layout">
        <div class="upper-grid">
          <section class="surface invite-surface"><header class="surface-header"><div><h2>邀请</h2><p>${number(inviteCount)} 人在待邀请名单</p></div><div class="surface-actions"><button class="icon-button" type="button" data-open-people aria-label="添加人员" title="添加人员">${icon("add")}</button><button class="button primary" type="button" data-send-invites>${icon("send")}<span>发送所选</span></button></div></header><div class="surface-body invite-list-main">${candidateRows()}</div></section>
          <section class="surface subscriber-surface"><header class="surface-header"><div><h2>订阅者</h2><p>${number((data.subscribers || []).length)} 人 · 直接调整接收内容与方式</p></div></header><div class="surface-body table-wrap subscriber-table"><table><thead><tr><th>姓名</th><th>订阅内容</th><th>报告方式</th><th>新闻频率</th><th>状态</th><th>操作</th></tr></thead><tbody>${compactSubscriberRows()}</tbody></table></div></section>
        </div>
        <section class="surface push-surface"><header class="surface-header"><div><h2>推送</h2><p>正式内容发送前自动命名 PDF 与音频文件</p></div></header><div class="surface-body"><form id="pushForm"><div class="push-form-fields"><label>服务<select name="service">${serviceOptions()}</select></label><label>交付方式<select name="mode"><option value="pdf">仅 PDF</option><option value="pdf_audio">PDF + 单独语音</option><option value="audio">仅语音</option></select></label><label data-report>正式报告<select name="path">${reportOptions()}</select><small data-outgoing-names></small></label></div><label data-news hidden>新闻标题<input name="title" value="${esc(newsTitle)}" maxlength="120"></label><label data-news hidden>新闻正文<textarea name="body" placeholder="仅用于人工补发经审核的战略新闻">${esc(newsBody)}</textarea></label><div class="push-actions"><label class="test-toggle"><input name="testOnly" type="checkbox" checked><span>仅发给我测试</span></label><button class="button primary" type="submit">执行推送</button></div></form></div></section>
      </main>
      <div class="drawer-backdrop" data-drawer-backdrop${state.drawerOpen ? "" : " hidden"}><aside class="management-drawer" role="dialog" aria-modal="true" aria-label="管理记录"><header class="drawer-header"><div><h2>记录</h2><p>邀请结果与推送回读</p></div><button class="icon-button" type="button" data-close-management aria-label="关闭记录">${icon("close")}</button></header><nav class="drawer-tabs" aria-label="记录分类"><button type="button" data-drawer-tab="invitations" class="${state.drawerTab === "invitations" ? "is-active" : ""}">邀请结果</button><button type="button" data-drawer-tab="deliveries" class="${state.drawerTab === "deliveries" ? "is-active" : ""}">推送记录</button></nav><div class="drawer-body">${drawerContent()}</div></aside></div>
      <div class="drawer-backdrop" data-people-backdrop${state.peopleOpen ? "" : " hidden"}><aside class="people-picker" role="dialog" aria-modal="true" aria-label="添加邀请人员"><header class="drawer-header"><div><h2>添加人员</h2><p>搜索飞书通讯录并加入待邀请名单</p></div><button class="icon-button" type="button" data-close-people aria-label="关闭人员选择">${icon("close")}</button></header><div class="people-picker-body"><form class="people-search" id="peopleSearchForm"><input name="query" value="${esc(state.searchQuery)}" maxlength="50" aria-label="飞书检索关键字" placeholder="搜索姓名或群聊" required><button class="icon-button primary" type="submit" aria-label="搜索飞书人员和群聊" title="搜索">${icon("search")}</button></form><div class="people-results">${searchResultRows()}</div></div></aside></div>
    </div>`;
    syncPushFields();
  }

  function syncPushFields() {
    const form = document.querySelector("#pushForm");
    if (!form) return;
    const news = form.elements.service.value === "news";
    form.querySelectorAll("[data-news]").forEach((element) => { element.hidden = !news; });
    form.querySelector("[data-report]").hidden = news;
    if (news) {
      form.elements.mode.innerHTML = '<option value="text">飞书消息</option>';
    } else {
      form.elements.mode.innerHTML = '<option value="pdf">仅 PDF</option><option value="pdf_audio">PDF + 单独语音</option><option value="audio">仅语音</option>';
    }
    Array.from(form.elements.path.options).forEach((option) => {
      const type = form.elements.service.value === "weekly" ? "weekly" : "carrier-performance";
      option.hidden = !news && option.dataset.reportType !== type;
    });
    if (!news) {
      const first = Array.from(form.elements.path.options).find((option) => !option.hidden);
      if (first) form.elements.path.value = first.value;
    }
    const names = form.querySelector("[data-outgoing-names]");
    if (names) names.textContent = news ? "" : `发送前自动命名：${outgoingNames(form)}`;
  }

  async function loadData({ keepNotice = false } = {}) {
    if (!keepNotice) { state.notice = "正在刷新后台数据…"; state.noticeKind = ""; }
    const [subscriptions, briefs] = await Promise.all([
      fetch("/api/subscriptions", { cache: "no-store" }),
      fetch("/api/strategic-briefs", { cache: "no-store" }),
    ]);
    const payload = await subscriptions.json();
    if (!subscriptions.ok || !payload.ok) throw new Error(payload.error || `HTTP ${subscriptions.status}`);
    state.data = payload;
    if (briefs.ok) state.briefs = (await briefs.json()).items || [];
    if (!keepNotice) { state.notice = ""; state.noticeKind = ""; }
    render();
  }

  async function post(payload, pendingText) {
    state.notice = pendingText;
    state.noticeKind = "";
    render();
    document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    const response = await fetch("/api/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    const evidence = result.result?.message_id || result.result?.batch_id || "已完成";
    state.notice = `操作成功并完成飞书回读：${evidence}`;
    state.noticeKind = "success";
    await loadData({ keepNotice: true });
  }

  document.addEventListener("click", async (event) => {
    if (event.target.closest("[data-open-people]")) {
      state.peopleOpen = true;
      render();
      return;
    }
    if (event.target.closest("[data-close-people]") || event.target.matches("[data-people-backdrop]")) {
      state.peopleOpen = false;
      render();
      return;
    }
    if (event.target.closest("[data-open-management]")) {
      state.drawerOpen = true;
      render();
      return;
    }
    if (event.target.closest("[data-close-management]") || event.target.matches("[data-drawer-backdrop]")) {
      state.drawerOpen = false;
      render();
      return;
    }
    const workflow = event.target.closest("[data-workflow-view]");
    if (workflow) {
      state.activeView = workflow.dataset.workflowView;
      render();
      return;
    }
    const drawerTab = event.target.closest("[data-drawer-tab]");
    if (drawerTab) {
      state.drawerTab = drawerTab.dataset.drawerTab;
      render();
      return;
    }
    if (event.target.closest("[data-test-card]")) {
      try { await post({ action: "publish", targetType: "user", targetId: state.data?.test_target?.callback_open_id || "" }, "正在把订阅卡片发给你本人并回读…"); }
      catch (error) { state.notice = `测试卡片发送失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.closest("[data-refresh-directory]")) {
      try { await post({ action: "refreshDirectory" }, "正在从飞书授权范围刷新人员、头像和部门信息…"); }
      catch (error) { state.notice = `通讯录刷新失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    const addCandidate = event.target.closest("[data-add-candidate]");
    if (addCandidate) {
      try { await post({ action: "addCandidates", directoryOpenIds: [addCandidate.dataset.addCandidate] }, "正在加入待邀请名单…"); }
      catch (error) { state.notice = `加入名单失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.closest("[data-send-invites]")) {
      const ids = Array.from(document.querySelectorAll("[data-invite-candidate]:checked")).map((item) => item.value);
      if (!ids.length) { state.notice = "请先勾选要邀请的人员。"; state.noticeKind = "error"; render(); return; }
      if (!window.confirm(`确认只向选中的 ${ids.length} 人发送订阅邀请？`)) return;
      try { await post({ action: "invite", callbackOpenIds: ids, confirmInvite: true }, "正在逐人发送邀请并回读消息…"); }
      catch (error) { state.notice = `邀请发送失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    const save = event.target.closest("[data-save-subscriber]");
    if (save) {
      const row = save.closest("[data-subscriber-row]");
      const services = Array.from(row.querySelectorAll('input[type="checkbox"]:checked')).map((input) => input.value);
      try { await post({ action: "update", openId: row.dataset.subscriberRow, services, reportMode: row.querySelector("[data-subscriber-report-mode]").value, newsFrequency: row.querySelector("[data-subscriber-news-frequency]").value, status: row.querySelector("[data-subscriber-status]").value }, "正在保存订阅者设置…"); }
      catch (error) { state.notice = `保存失败：${error.message}`; state.noticeKind = "error"; render(); }
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.closest('#pushForm [name="service"], #pushForm [name="mode"], #pushForm [name="path"]')) syncPushFields();
  });

  document.addEventListener("submit", async (event) => {
    if (event.target.id === "peopleSearchForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      try {
        const response = await fetch("/api/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "searchDirectory", query: values.query }) });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        state.searchResults = payload.result?.people || [];
        state.chatSearchResults = payload.result?.chats || [];
        state.searchQuery = payload.result?.query || values.query;
        state.notice = `找到 ${state.searchResults.length} 位人员、${state.chatSearchResults.length} 个群聊。`;
        state.noticeKind = "success";
        render();
      } catch (error) { state.notice = `飞书搜索失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.id === "pushForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      const payload = { action: "push", service: values.service, mode: values.mode, path: values.path || "", title: values.title || "", body: values.body || "" };
      if (values.testOnly) payload.testOpenId = state.data?.test_target?.delivery_open_id || "";
      else {
        if (!window.confirm("确认向该服务的全部有效订阅者推送这份内容？发送后无法撤回。")) return;
        payload.confirmBulk = true;
      }
      try { await post(payload, values.testOnly ? "正在只向你本人发送并回读…" : "正在向全部有效订阅者推送并逐条回读…"); }
      catch (error) { state.notice = `推送失败：${error.message}`; state.noticeKind = "error"; render(); }
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && (state.drawerOpen || state.peopleOpen)) {
      state.drawerOpen = false;
      state.peopleOpen = false;
      render();
    }
  });

  loadData().catch((error) => {
    root.innerHTML = `<div class="loading">订阅后台加载失败：${esc(error.message)}</div>`;
  });
})();
