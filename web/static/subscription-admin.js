(() => {
  "use strict";

  const root = document.querySelector("#subscriptionAdmin");
  const state = {
    data: null, searchResults: [], chatSearchResults: [], searchQuery: "",
    filters: {
      invite: { kind: "all", status: "all" },
      subscriber: { service: "all", status: "all", frequency: "all" },
    },
    deliveryFilters: { query: "", from: "", to: "", service: "all", recipient: "all", status: "all" },
    invitationFilters: { query: "", from: "", to: "", person: "all", status: "all" },
    openFilter: "", notice: "", noticeKind: "", activeView: "invite", drawerOpen: false, peopleOpen: false, drawerTab: "invitations",
    manualWeeklyPath: "", weeklyPickerOpen: false, weeklyPickerQuery: "", weeklyPickerBusy: false,
    manualPerformancePath: "", performancePickerOpen: false, performancePickerQuery: "", performancePickerBusy: false,
    manualPushJob: null,
    selectedInviteUsers: new Set(), selectedInviteGroups: new Set(),
  };
  const subscriberDrafts = new Map();
  let noticeTimer = 0;
  let noticeExitTimer = 0;
  let scheduledNoticeSignature = "";
  let manualPushPollTimer = 0;
  let manualPushPollId = "";
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
  const manualPushBusy = () => ["queued", "running"].includes(state.manualPushJob?.status);
  const manualPushProgressText = (job) => {
    const completed = Number(job?.completed_steps || 0);
    const total = Number(job?.total_steps || 0);
    const progress = total ? `（${completed}/${total}）` : "";
    return `${job?.detail || "正在后台发送并回读"}${progress}；页面可以继续操作`;
  };
  const serviceLabel = (value) => ({ weekly: "战略双周报", performance: "运营商业绩摘要", news: "战略新闻" }[value] || value);
  const modeLabel = (value) => ({ text: "文字", pdf: "PDF 文件", pdf_audio: "PDF + 独立语音", audio: "语音", both: "文字 + 语音" }[value] || value);
  const invitationStatus = (value) => ({ pending: "等待选择", needs_correction: "待修改选项", accepted: "已接受", paused: "已暂停", unsubscribed: "已退订", rejected: "已拒绝", declined: "已拒绝", failed: "发送失败", verified: "已确认发送", responded: "已有人选择" }[value] || value);
  const icon = (name) => ({
    add: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>',
    search: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>',
    refresh: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 5v6h-6"/></svg>',
    send: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 5 16 7-16 7 3-7-3-7Z"/><path d="M7 12h13"/></svg>',
    history: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h16M4 18h9"/><circle cx="18" cy="18" r="3"/></svg>',
    filter: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16l-6.5 7.2V19l-3 1v-6.8L4 6Z"/></svg>',
    close: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  }[name] || "");
  const avatar = (item, always = false) => {
    const openId = item.directory_open_id || item.callback_open_id || item.open_id || "";
    const fallback = `<span class="avatar avatar-fallback" aria-hidden="true">${esc((item.display_name || "飞").slice(0, 1))}</span>`;
    if (!openId || (!item.avatar_url && !always)) return fallback;
    return `<span class="avatar-stack">${fallback}<img class="avatar" src="/api/subscriptions/avatar?openId=${encodeURIComponent(openId)}" alt="" loading="lazy"></span>`;
  };
  root.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.matches(".avatar-stack > img.avatar")) event.target.remove();
  }, true);

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

  function newsItemLimitOptions(selected = 10) {
    return [5, 10, 15, 20].map((count) => `<option value="${count}"${Number(selected) === count ? " selected" : ""}>${count} 条</option>`).join("");
  }

  function newsCategoryChecks(selected = []) {
    const categories = state.data?.news_categories || [];
    const selectedSet = new Set(selected || []);
    return categories.map((item) => `<label class="news-interest-check"><input type="checkbox" value="${esc(item.key)}" data-news-category${selectedSet.has(item.key) ? " checked" : ""}><span>${esc(item.label)}</span></label>`).join("");
  }

  function conditionalSetting(kind, enabled, content, emptyLabel) {
    return `<div class="subscriber-dependent-setting" data-dependent-setting="${kind}"${enabled ? "" : " hidden"}>${content}</div><select class="subscriber-setting-empty" data-dependent-setting-empty="${kind}" aria-label="${esc(emptyLabel)}" title="${esc(emptyLabel)}" disabled${enabled ? " hidden" : ""}><option value="not_applicable" selected>不适用</option></select>`;
  }

  function syncRowDependentSettings(row, services) {
    const serviceSet = new Set(services || []);
    const visibility = {
      news: serviceSet.has("news"),
      report: serviceSet.has("weekly") || serviceSet.has("performance"),
    };
    Object.entries(visibility).forEach(([kind, enabled]) => {
      row.querySelectorAll(`[data-dependent-setting="${kind}"]`).forEach((container) => {
        container.hidden = !enabled;
        container.querySelectorAll("input, select, button").forEach((control) => { control.disabled = !enabled; });
      });
      row.querySelectorAll(`[data-dependent-setting-empty="${kind}"]`).forEach((placeholder) => { placeholder.hidden = enabled; });
    });
    row.dataset.filterServices = Array.from(serviceSet).join(" ");
    row.dataset.filterFrequency = visibility.news ? row.querySelector("[data-subscriber-news-frequency]")?.value || "once_daily" : "";
  }

  function normalizedPreferenceSnapshot(item = {}) {
    const list = (value) => Array.from(new Set(Array.isArray(value) ? value : [])).sort();
    return {
      services: list(item.services),
      news_categories: list(item.news_categories),
      report_mode: item.report_mode || "pdf",
      frequency: item.news_frequency || item.frequency || "once_daily",
      news_item_limit: Number(item.news_item_limit || 10),
      news_delivery_times: Array.isArray(item.news_delivery_times) ? item.news_delivery_times : ["08:00", "18:30"],
      status: item.status || "active",
    };
  }

  function subscriberDiffersFromDefault(item) {
    if (!item?.default_preferences || !Object.keys(item.default_preferences).length) return false;
    return JSON.stringify(normalizedPreferenceSnapshot(item)) !== JSON.stringify(normalizedPreferenceSnapshot(item.default_preferences));
  }

  function syncResetButton(button, item) {
    if (!button) return;
    const differs = subscriberDiffersFromDefault(item);
    button.classList.toggle("is-different", differs);
    button.dataset.defaultDifferent = String(differs);
    button.setAttribute("aria-label", differs ? `恢复 ${item.display_name} 的默认选项（当前设置与默认不同）` : `${item.display_name} 当前已是默认选项`);
    button.title = differs ? "当前设置与默认订阅不同，点击恢复" : "当前设置与默认订阅一致";
  }

  function subscriberRows() {
    const rows = state.data?.subscribers || [];
    if (!rows.length) return '<tr><td colspan="10" class="empty">尚无订阅者。先把测试卡片发给自己，确认后再发布到同事群。</td></tr>';
    return rows.map((item) => `<tr data-subscriber-row="${esc(item.open_id)}">
      <td class="name">${esc(item.display_name)}</td><td class="muted">${esc(item.open_id.slice(0, 8))}…</td>
      ${["weekly", "performance", "news"].map((service) => `<td><label class="service-check"><input type="checkbox" value="${service}"${item.services.includes(service) ? " checked" : ""}><span>${service === "weekly" ? "周报" : service === "performance" ? "业绩" : "新闻"}</span></label></td>`).join("")}
      <td><select data-subscriber-report-mode>${reportModeOptions(item.report_mode)}</select></td>
      <td><select data-subscriber-news-frequency>${newsFrequencyOptions(item.news_frequency || item.frequency)}</select><select data-subscriber-news-limit aria-label="每次新闻条数">${newsItemLimitOptions(item.news_item_limit)}</select></td>
      <td><select data-subscriber-status><option value="active"${item.status === "active" ? " selected" : ""}>启用</option><option value="paused"${item.status === "paused" ? " selected" : ""}>暂停</option></select></td>
      <td><button class="button" type="button" data-save-subscriber>保存</button></td></tr>`).join("");
  }

  function compactSubscriberRows() {
    const rows = state.data?.subscribers || [];
    if (!rows.length) return '<tr><td colspan="11" class="empty">尚无订阅者</td></tr>';
    const categoryLabels = new Map((state.data?.news_categories || []).map((category) => [category.key, category.label]));
    return rows.map((savedItem) => {
      const item = { ...savedItem, ...subscriberDrafts.get(savedItem.open_id) };
      const hasNews = (item.services || []).includes("news");
      const hasReport = (item.services || []).some((service) => ["weekly", "performance"].includes(service));
      const differsFromDefault = subscriberDiffersFromDefault(item);
      const filterText = [
        item.display_name, item.open_id, ...(item.services || []).flatMap((service) => [service, serviceLabel(service)]),
        ...(item.news_categories || []).flatMap((category) => [category, categoryLabels.get(category)]),
        item.report_mode, modeLabel(item.report_mode), item.news_frequency || item.frequency,
        ...(item.news_delivery_times || ["08:00", "18:30"]),
        item.status, item.status === "paused" ? "暂停" : "启用",
      ].filter(Boolean).join(" ");
      return `<tr data-subscriber-row="${esc(item.open_id)}" data-subscriber-filter-row data-filter-services="${esc((item.services || []).join(" "))}" data-filter-status="${esc(item.status || "active")}" data-filter-frequency="${hasNews ? esc(item.news_frequency || item.frequency || "once_daily") : ""}" data-filter-text="${esc(filterText)}">
      <td><div class="table-person">${avatar(item, true)}<span class="table-person-copy"><strong class="table-person-name">${esc(item.display_name)}</strong><small class="table-person-id">${esc(item.open_id.slice(0, 8))}…</small>${item.preference_source === "group_card" ? `<small class="preference-source" title="${esc(item.preference_message_id)}">群卡本人提交 · ${esc(item.updated_at)}</small>` : ""}</span></div></td>
      <td><div class="service-group">${["weekly", "performance", "news"].map((service) => `<label class="service-check"><input type="checkbox" value="${service}"${item.services.includes(service) ? " checked" : ""}><span>${service === "weekly" ? "周报" : service === "performance" ? "业绩" : "新闻"}</span></label>`).join("")}</div></td>
      <td>${conditionalSetting("report", hasReport, `<select data-subscriber-report-mode${hasReport ? "" : " disabled"}>${reportModeOptions(item.report_mode)}</select>`, "未订阅报告")}</td>
      <td>${conditionalSetting("news", hasNews, `<div class="news-interest-group" aria-label="${esc(item.display_name)}的战略新闻兴趣板块">${newsCategoryChecks(item.news_categories)}</div>`, "未订阅新闻")}</td>
      <td>${conditionalSetting("news", hasNews, `<select data-subscriber-news-frequency${hasNews ? "" : " disabled"}>${newsFrequencyOptions(item.news_frequency || item.frequency)}</select>`, "未订阅新闻")}</td>
      <td>${conditionalSetting("news", hasNews, `<select data-subscriber-news-limit aria-label="每次新闻条数"${hasNews ? "" : " disabled"}>${newsItemLimitOptions(item.news_item_limit)}</select>`, "未订阅新闻")}</td>
      <td>${conditionalSetting("news", hasNews, `<div class="news-delivery-times" aria-label="${esc(item.display_name)}的个人期待收到信息时间"><input data-subscriber-news-time="0" type="time" title="香港时间，不早于08:00" value="${esc((item.news_delivery_times || ["08:00", "18:30"])[0])}" aria-label="第一次期待收到时间"${hasNews ? "" : " disabled"}><input data-subscriber-news-time="1" type="time" title="香港时间，不早于14:00" value="${esc((item.news_delivery_times || ["08:00", "18:30"])[1])}" aria-label="第二次期待收到时间"${hasNews ? "" : " disabled"}></div>`, "未订阅新闻")}</td>
      <td><select data-subscriber-status><option value="active"${item.status === "active" ? " selected" : ""}>启用</option><option value="paused"${item.status === "paused" ? " selected" : ""}>暂停</option></select></td>
      <td class="subscriber-action-cell"><button class="icon-button${differsFromDefault ? " is-different" : ""}" type="button" data-reset-subscriber data-default-different="${differsFromDefault}" aria-label="${differsFromDefault ? `恢复 ${esc(item.display_name)} 的默认选项（当前设置与默认不同）` : `${esc(item.display_name)} 当前已是默认选项`}" title="${differsFromDefault ? "当前设置与默认订阅不同，点击恢复" : "当前设置与默认订阅一致"}">${icon("refresh")}</button></td>
      <td class="subscriber-action-cell"><button class="button compact-save" type="button" data-save-subscriber>保存${subscriberDrafts.has(item.open_id) ? " *" : ""}</button></td>
      <td class="subscriber-action-cell"><button class="icon-button row-send" type="button" data-manual-push-person aria-label="手动推送给 ${esc(item.display_name)}" title="手动推送给 ${esc(item.display_name)}"${manualPushBusy() ? " disabled" : ""}>${icon("send")}</button></td></tr>`;
    }).join("") + '<tr data-subscriber-filter-empty hidden><td colspan="11" class="empty">没有匹配的订阅者</td></tr>';
  }

  function deliveryRows() {
    const rows = state.data?.deliveries || [];
    if (!rows.length) return '<tr><td colspan="7" class="empty">尚无推送记录</td></tr>';
    return rows.map((item) => {
      const openId = item.recipient_open_id || item.open_id || "";
      const recipientName = item.recipient_name || openId || "接收人未记录";
      const recipientIdentity = item.recipient_name && openId ? `${openId.slice(0, 10)}${openId.length > 10 ? "…" : ""}` : "";
      const deliveryStatus = item.status === "verified" ? "verified" : ["queued", "sending", "retrying"].includes(item.status) ? "pending" : "issue";
      const filterText = [item.created_at, serviceLabel(item.service), modeLabel(item.mode), item.content_ref, recipientName, openId, item.status, item.error].filter(Boolean).join(" ");
      const recipientKey = recipientName;
      return `<tr data-delivery-filter-row data-filter-date="${esc(String(item.created_at || "").slice(0, 10))}" data-filter-service="${esc(item.service || "")}" data-filter-recipient="${esc(recipientKey)}" data-filter-status="${deliveryStatus}" data-filter-text="${esc(filterText)}"><td>${esc(item.created_at)}</td><td>${esc(serviceLabel(item.service))}</td><td>${esc(modeLabel(item.mode))}</td><td class="muted">${esc(item.content_ref || "—")}</td><td><span class="delivery-recipient" title="${esc(openId)}"><strong>${esc(recipientName)}</strong>${recipientIdentity ? `<small>${esc(recipientIdentity)}</small>` : ""}</span></td><td><span class="status ${esc(item.status)}">${item.status === "verified" ? "已确认发送" : item.status === "queued" ? "等待重试" : item.status === "sending" ? "发送中" : item.status === "retrying" ? "等待重试" : item.status === "cancelled" ? "发送功能已关闭，已取消" : item.status === "superseded" ? "已按新规则停用" : "失败"}</span></td><td title="${esc(item.error || "")}">${item.error ? esc(item.error.slice(0, 90)) : number(item.message_ids?.length || 0) + " 条消息"}</td></tr>`;
    }).join("") + '<tr data-delivery-filter-empty hidden><td colspan="7" class="empty">没有匹配的推送记录</td></tr>';
  }

  function deliveryRecipientOptions() {
    const recipients = new Map();
    (state.data?.deliveries || []).forEach((item) => {
      const openId = item.recipient_open_id || item.open_id || "";
      const name = item.recipient_name || openId || "接收人未记录";
      recipients.set(name, name);
    });
    return Array.from(recipients.entries()).sort((left, right) => left[1].localeCompare(right[1], "zh-CN"))
      .map(([value, label]) => `<option value="${esc(value)}"${state.deliveryFilters.recipient === value ? " selected" : ""}>${esc(label)}</option>`).join("");
  }

  function deliveryFilterToolbar() {
    const filters = state.deliveryFilters;
    const history = state.data?.delivery_history || {};
    const oldest = String(history.oldest_at || "").slice(0, 10);
    const newest = String(history.newest_at || "").slice(0, 10);
    return `<div class="delivery-filter-toolbar" aria-label="筛选推送记录">
      <label class="delivery-search"><span class="sr-only">搜索推送记录</span><input type="search" value="${esc(filters.query)}" data-delivery-filter="query" placeholder="搜索接收人、内容或错误" autocomplete="off"></label>
      <label><span>从</span><input type="date" value="${esc(filters.from)}" min="${esc(oldest)}" max="${esc(newest)}" data-delivery-filter="from"></label>
      <label><span>到</span><input type="date" value="${esc(filters.to)}" min="${esc(oldest)}" max="${esc(newest)}" data-delivery-filter="to"></label>
      <label><span class="sr-only">服务</span><select data-delivery-filter="service"><option value="all"${filters.service === "all" ? " selected" : ""}>全部服务</option><option value="news"${filters.service === "news" ? " selected" : ""}>战略新闻</option><option value="weekly"${filters.service === "weekly" ? " selected" : ""}>战略双周报</option><option value="performance"${filters.service === "performance" ? " selected" : ""}>运营商业绩摘要</option></select></label>
      <label><span class="sr-only">推送人</span><select data-delivery-filter="recipient" aria-label="按推送人筛选"><option value="all"${filters.recipient === "all" ? " selected" : ""}>全部推送人</option>${deliveryRecipientOptions()}</select></label>
      <label><span class="sr-only">状态</span><select data-delivery-filter="status"><option value="all"${filters.status === "all" ? " selected" : ""}>全部状态</option><option value="verified"${filters.status === "verified" ? " selected" : ""}>已确认发送</option><option value="pending"${filters.status === "pending" ? " selected" : ""}>处理中 / 重试</option><option value="issue"${filters.status === "issue" ? " selected" : ""}>失败 / 已停用</option></select></label>
      <button class="button delivery-filter-clear" type="button" data-clear-delivery-filters>清除</button>
      <p class="delivery-history-summary" data-delivery-filter-summary>全部历史 ${number(history.total ?? (state.data?.deliveries || []).length)} 条${oldest && newest ? ` · ${esc(oldest)} 至 ${esc(newest)}` : ""}</p>
    </div>`;
  }

  function applyDeliveryFilter() {
    const filters = state.deliveryFilters;
    const query = String(filters.query || "").trim().toLocaleLowerCase();
    const rows = Array.from(root.querySelectorAll("[data-delivery-filter-row]"));
    let visibleCount = 0;
    rows.forEach((row) => {
      const date = row.dataset.filterDate || "";
      const visible = (!query || String(row.dataset.filterText || "").toLocaleLowerCase().includes(query))
        && (!filters.from || date >= filters.from)
        && (!filters.to || date <= filters.to)
        && (filters.service === "all" || row.dataset.filterService === filters.service)
        && (filters.recipient === "all" || row.dataset.filterRecipient === filters.recipient)
        && (filters.status === "all" || row.dataset.filterStatus === filters.status);
      row.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const total = Number(state.data?.delivery_history?.total ?? rows.length);
    const oldest = String(state.data?.delivery_history?.oldest_at || "").slice(0, 10);
    const newest = String(state.data?.delivery_history?.newest_at || "").slice(0, 10);
    const summary = root.querySelector("[data-delivery-filter-summary]");
    if (summary) summary.textContent = `显示 ${number(visibleCount)} / ${number(total)} 条历史记录${oldest && newest ? ` · 完整范围 ${oldest} 至 ${newest}` : ""}`;
    const empty = root.querySelector("[data-delivery-filter-empty]");
    if (empty) empty.hidden = visibleCount > 0;
  }

  function searchResultRows() {
    if (!state.searchQuery) return '<p class="empty compact">输入关键词检索飞书人员和群聊；搜索本身不会发送消息。</p>';
    const people = state.searchResults.map((item) => `<div class="person-row">
      ${avatar(item)}<span class="person-copy"><strong>${highlight(item.display_name)}</strong><small>${highlight([item.en_name, (item.department_names || []).join(" / ") || item.job_title].filter(Boolean).join(" · ") || "飞书用户")}</small></span>
      <button class="icon-button add" type="button" data-add-candidate="${esc(item.directory_open_id)}" aria-label="添加 ${esc(item.display_name)}" title="加入待邀请名单">${icon("add")}</button>
    </div>`).join("");
    const chats = state.chatSearchResults.map((item) => `<div class="person-row chat-row">
      <span class="avatar avatar-fallback chat-avatar" aria-hidden="true">群</span><span class="person-copy"><strong>${highlight(item.name)}</strong><small>${highlight(item.description || (item.external ? "外部群聊" : "飞书群聊"))}</small></span>
      <button class="button compact-send" type="button" data-invite-chat="${esc(item.chat_id)}" data-invite-chat-name="${esc(item.name)}" aria-label="发送订阅邀请到 ${esc(item.name)}" title="发送到群聊">${icon("send")}<span>发送到群</span></button>
    </div>`).join("");
    if (!people && !chats) return `<p class="empty compact">没有找到包含“${esc(state.searchQuery)}”的人员或群聊。</p>`;
    return `${people ? `<div class="result-section-label">人员 · ${number(state.searchResults.length)}</div>${people}` : ""}${chats ? `<div class="result-section-label">群聊 · ${number(state.chatSearchResults.length)}</div>${chats}` : ""}`;
  }

  function currentGroupInvitations() {
    return state.data?.group_invitations || [];
  }

  function groupResponseProfile(response) {
    const departments = (response.department_names || []).filter(Boolean).join(" / ");
    const jobTitle = String(response.job_title || "").trim();
    const enName = String(response.en_name || "").trim();
    const displayName = String(response.display_name || "").trim();
    return {
      name: enName && !displayName.toLocaleLowerCase().includes(enName.toLocaleLowerCase())
        ? `${displayName} ${enName}`
        : displayName,
      details: [departments, jobTitle].filter(Boolean).join(" · ") || "已验证飞书用户",
    };
  }

  function invitationSortRank(item) {
    const status = item?.latest_invitation?.status || "";
    if (["accepted", "responded"].includes(status)) return 0;
    if (["pending", "verified"].includes(status)) return 1;
    if (!status) return 2;
    return 3;
  }

  function candidateRows() {
    const rows = state.data?.invite_candidates || [];
    const groups = currentGroupInvitations();
    if (!rows.length && !groups.length) return '<p class="empty compact">尚无待邀请人员或已发送的群邀请</p>';
    const groupRows = groups.map((item) => {
      const responses = item.responses || [];
      const acceptedCount = Number(item.accepted_count || 0);
      const correctionCount = responses.filter((response) => response.status === "needs_correction").length;
      const messageCount = Number(item.message_count || 1);
      const responseSummary = acceptedCount
        ? `${number(acceptedCount)}人已接受${correctionCount ? ` · ${number(correctionCount)}人待修正` : ""}`
        : correctionCount ? `${number(correctionCount)}人待修正` : "已确认发送";
      const groupStatus = acceptedCount ? "accepted" : correctionCount ? "needs_correction" : "verified";
      const filterText = [item.target_name, "群邀请", responseSummary, ...responses.flatMap((response) => [response.display_name, response.en_name, ...(response.department_names || []), response.job_title, invitationStatus(response.status), response.last_error])].filter(Boolean).join(" ");
      return `<details class="group-invite-record" data-invite-filter-row data-filter-kind="group" data-filter-status="${groupStatus}" data-filter-text="${esc(filterText)}"><summary class="invite-row group-invite-row">
        <input type="checkbox" value="${esc(item.target_id)}" data-invite-group-candidate data-invite-group-name="${esc(item.target_name)}" aria-label="选择群聊 ${esc(item.target_name)}"${state.selectedInviteGroups.has(item.target_id) ? " checked" : ""}>
        <span class="avatar avatar-fallback chat-avatar" aria-hidden="true">群</span><span class="person-copy"><strong>${esc(item.target_name)}</strong><small>群邀请 · 已发送 ${number(messageCount)} 次 · 成员按人去重累计</small></span>
        <span class="invite-meta"><span class="status ${groupStatus}">${responseSummary}</span><small>${esc(item.latest_response_at || item.created_at || "-")}</small></span>
      </summary><div class="group-response-list">${responses.length ? responses.map((response) => { const profile = groupResponseProfile(response); return `<span>${avatar(response)}<span><strong>${esc(profile.name)}</strong><small>${esc(profile.details)} · ${esc(invitationStatus(response.status))}${response.last_error ? ` · ${esc(response.last_error)}` : ""} · ${esc(response.responded_at)}</small></span></span>`; }).join("") : "<p>等待群成员提交选择</p>"}</div></details>`;
    }).join("");
    const sortedRows = rows.map((item, index) => ({ item, index }))
      .sort((left, right) => invitationSortRank(left.item) - invitationSortRank(right.item) || left.index - right.index)
      .map(({ item }) => item);
    const personRows = sortedRows.map((item) => {
      const filterText = [item.display_name, item.en_name, ...(item.department_names || []), item.job_title, invitationStatus(item.latest_invitation?.status || "未邀请")].filter(Boolean).join(" ");
      const rawStatus = item.latest_invitation?.status || "pending";
      const filterStatus = ["accepted", "responded"].includes(rawStatus) ? "accepted" : rawStatus === "verified" ? "verified" : ["failed", "paused", "unsubscribed", "rejected", "declined", "needs_correction"].includes(rawStatus) ? "issue" : "pending";
      return `<label class="invite-row" data-invite-filter-row data-filter-kind="person" data-filter-status="${filterStatus}" data-filter-text="${esc(filterText)}">
      <input type="checkbox" value="${esc(item.callback_open_id)}" data-invite-candidate${state.selectedInviteUsers.has(item.callback_open_id) ? " checked" : ""}>
      ${avatar(item)}<span class="person-copy"><strong>${esc(item.display_name)}</strong><small>${esc([(item.department_names || []).join(" / "), item.job_title].filter(Boolean).join(" · ") || "已验证飞书用户")}</small>${item.latest_invitation?.last_error ? `<small>${esc(item.latest_invitation.last_error)}</small>` : ""}</span>
      <span class="invite-meta"><span class="status ${esc(item.latest_invitation?.status || "pending")}">${esc(invitationStatus(item.latest_invitation?.status || "未邀请"))}</span><small>${esc(item.latest_invitation?.sent_at || "未发送")}</small></span>
    </label>`;
    }).join("");
    return groupRows + personRows + '<p class="empty compact" data-invite-filter-empty hidden>没有匹配的邀请对象</p>';
  }

  function activeFilterCount(section) {
    return Object.values(state.filters[section] || {}).filter((value) => value !== "all").length;
  }

  function filterChoice(section, field, value, label) {
    const checked = state.filters[section]?.[field] === value;
    return `<label class="compact-filter-choice"><input type="radio" name="${section}-${field}" value="${esc(value)}" data-filter-section="${section}" data-filter-field="${field}"${checked ? " checked" : ""}><span>${esc(label)}</span></label>`;
  }

  function compactFilter(section) {
    const isInvite = section === "invite";
    const count = activeFilterCount(section);
    const open = state.openFilter === section;
    const groups = isInvite
      ? `<fieldset><legend>对象类型</legend><div class="compact-filter-choices">${filterChoice(section, "kind", "all", "全部")}${filterChoice(section, "kind", "person", "个人")}${filterChoice(section, "kind", "group", "群邀请")}</div></fieldset>
        <fieldset><legend>邀请状态</legend><div class="compact-filter-choices">${filterChoice(section, "status", "all", "全部")}${filterChoice(section, "status", "pending", "待选择")}${filterChoice(section, "status", "verified", "已发送")}${filterChoice(section, "status", "accepted", "已接受")}${filterChoice(section, "status", "issue", "异常")}</div></fieldset>`
      : `<fieldset><legend>订阅内容</legend><div class="compact-filter-choices">${filterChoice(section, "service", "all", "全部")}${filterChoice(section, "service", "weekly", "周报")}${filterChoice(section, "service", "performance", "业绩")}${filterChoice(section, "service", "news", "新闻")}</div></fieldset>
        <fieldset><legend>状态</legend><div class="compact-filter-choices">${filterChoice(section, "status", "all", "全部")}${filterChoice(section, "status", "active", "启用")}${filterChoice(section, "status", "paused", "暂停")}</div></fieldset>
        <fieldset><legend>新闻频率</legend><div class="compact-filter-choices">${filterChoice(section, "frequency", "all", "全部")}${filterChoice(section, "frequency", "once_daily", "每天一次")}${filterChoice(section, "frequency", "twice_daily", "每天两次")}</div></fieldset>`;
    const label = isInvite ? "筛选邀请对象" : "筛选订阅者";
    return `<div class="compact-filter" data-compact-filter="${section}"><button class="icon-button filter-trigger${count ? " is-active" : ""}" type="button" data-filter-trigger="${section}" aria-label="${label}" title="${label}" aria-expanded="${open}" aria-controls="${section}-filter-panel">${icon("filter")}<span class="icon-badge filter-count"${count ? "" : " hidden"}>${count}</span></button><div class="compact-filter-panel" id="${section}-filter-panel" role="dialog" aria-label="${label}"${open ? "" : " hidden"}><div class="compact-filter-heading"><strong>${label}</strong><button type="button" data-filter-reset="${section}"${count ? "" : " disabled"}>清除</button></div>${groups}</div></div>`;
  }

  function updateFilterIndicator(section) {
    const count = activeFilterCount(section);
    const trigger = root.querySelector(`[data-filter-trigger="${section}"]`);
    const badge = trigger?.querySelector(".filter-count");
    trigger?.classList.toggle("is-active", count > 0);
    if (badge) { badge.textContent = String(count); badge.hidden = count === 0; }
    const reset = root.querySelector(`[data-filter-reset="${section}"]`);
    if (reset) reset.disabled = count === 0;
  }

  function applySectionFilter(section) {
    const filters = state.filters[section];
    const rows = Array.from(root.querySelectorAll(`[data-${section}-filter-row]`));
    let visibleCount = 0;
    rows.forEach((row) => {
      const visible = section === "invite"
        ? (filters.kind === "all" || row.dataset.filterKind === filters.kind) && (filters.status === "all" || row.dataset.filterStatus === filters.status)
        : (filters.service === "all" || (row.dataset.filterServices || "").split(" ").includes(filters.service)) && (filters.status === "all" || row.dataset.filterStatus === filters.status) && (filters.frequency === "all" || row.dataset.filterFrequency === filters.frequency);
      row.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const empty = root.querySelector(`[data-${section}-filter-empty]`);
    if (empty) empty.hidden = activeFilterCount(section) === 0 || visibleCount > 0;
    updateFilterIndicator(section);
  }

  function applySavedFilters() {
    applySectionFilter("invite");
    applySectionFilter("subscriber");
    applyDeliveryFilter();
    applyInvitationFilter();
  }

  function invitationRows() {
    const personRows = state.data?.invitations || [];
    const groupRows = state.data?.group_invitations || [];
    if (!personRows.length && !groupRows.length) return '<tr><td colspan="4" class="empty">尚无邀请记录</td></tr>';
    const people = personRows.map((item) => {
      const personKey = item.callback_open_id || item.delivery_open_id || item.display_name || "";
      const filterText = [item.display_name, item.callback_open_id, item.delivery_open_id, item.sent_at, invitationStatus(item.status), item.message_id, item.last_error].filter(Boolean).join(" ");
      return `<tr data-invitation-filter-row data-filter-date="${esc(String(item.sent_at || "").slice(0, 10))}" data-filter-person="${esc(personKey)}" data-filter-status="${esc(item.status || "")}" data-filter-text="${esc(filterText)}"><td class="name">${esc(item.display_name)}</td><td>${esc(item.sent_at || "-")}</td><td><span class="status ${esc(item.status)}">${esc(invitationStatus(item.status))}</span>${item.last_error ? `<small>${esc(item.last_error)}</small>` : ""}</td><td class="muted">${esc(item.message_id || "-")}</td></tr>`;
    });
    const groups = groupRows.map((item) => {
      const responses = item.responses || [];
      const acceptedCount = Number(item.accepted_count || 0);
      const correctionCount = responses.filter((response) => response.status === "needs_correction").length;
      const status = correctionCount ? "needs_correction" : acceptedCount ? "accepted" : "verified";
      const filterStatuses = [acceptedCount ? "accepted" : "", correctionCount ? "needs_correction" : "", !acceptedCount && !correctionCount ? "verified" : ""].filter(Boolean).join(" ");
      const statusText = acceptedCount
        ? `${number(acceptedCount)}人已接受${correctionCount ? ` · ${number(correctionCount)}人待修正` : ""}`
        : correctionCount ? `${number(correctionCount)}人待修正` : "已确认发送";
      const groupKey = `group:${item.target_id || item.chat_id || item.target_name || ""}`;
      const latestMessageId = item.message_id || (item.message_ids || [])[0] || "";
      const filterText = [item.target_name, "群聊", item.created_at, statusText, latestMessageId,
        ...responses.flatMap((response) => [response.display_name, invitationStatus(response.status), response.last_error])].filter(Boolean).join(" ");
      const responseDetails = responses.length
        ? `<div class="invitation-history-responses">${responses.map((response) => { const profile = groupResponseProfile(response); return `<span>${avatar(response)}<span><strong>${esc(profile.name)}</strong><small>${esc(profile.details)} · ${esc(invitationStatus(response.status))}${response.last_error ? ` · ${esc(response.last_error)}` : ""} · ${esc(response.responded_at || "-")}</small></span></span>`; }).join("")}</div>`
        : '<p class="invitation-history-empty">暂无群成员提交</p>';
      return `<tr data-invitation-filter-row data-filter-date="${esc(String(item.created_at || "").slice(0, 10))}" data-filter-person="${esc(groupKey)}" data-filter-status="${filterStatuses}" data-filter-text="${esc(filterText)}"><td class="name"><details class="invitation-history-group" data-history-group="${esc(groupKey)}"><summary><span class="history-group-badge">群</span><span>${esc(item.target_name || "飞书群聊")}</span></summary>${responseDetails}</details></td><td>${esc(item.created_at || "-")}</td><td><span class="status ${status}">${statusText}</span></td><td class="muted">${esc(latestMessageId || "-")}${Number(item.message_count || 0) > 1 ? `<small>共 ${number(item.message_count)} 次群邀请</small>` : ""}</td></tr>`;
    });
    return [...groups, ...people].join("") + '<tr data-invitation-filter-empty hidden><td colspan="4" class="empty">没有匹配的邀请结果</td></tr>';
  }

  function invitationPersonOptions() {
    const people = new Map();
    (state.data?.invitations || []).forEach((item) => {
      const key = item.callback_open_id || item.delivery_open_id || item.display_name || "";
      if (key) people.set(key, item.display_name || key);
    });
    (state.data?.group_invitations || []).forEach((item) => {
      const key = `group:${item.target_id || item.chat_id || item.target_name || ""}`;
      if (key !== "group:") people.set(key, `群聊 · ${item.target_name || "飞书群聊"}`);
    });
    return Array.from(people.entries()).sort((left, right) => left[1].localeCompare(right[1], "zh-CN"))
      .map(([value, label]) => `<option value="${esc(value)}"${state.invitationFilters.person === value ? " selected" : ""}>${esc(label)}</option>`).join("");
  }

  function invitationFilterToolbar() {
    const filters = state.invitationFilters;
    const dates = [
      ...(state.data?.invitations || []).map((item) => item.sent_at),
      ...(state.data?.group_invitations || []).map((item) => item.created_at),
    ].filter(Boolean).sort();
    const oldest = String(dates[0] || "").slice(0, 10);
    const newest = String(dates.at(-1) || "").slice(0, 10);
    return `<div class="invitation-filter-toolbar" aria-label="筛选邀请结果">
      <label class="delivery-search"><span class="sr-only">搜索邀请结果</span><input type="search" value="${esc(filters.query)}" data-invitation-filter="query" placeholder="搜索姓名、消息 ID 或错误" autocomplete="off"></label>
      <label><span>从</span><input type="date" value="${esc(filters.from)}" min="${esc(oldest)}" max="${esc(newest)}" data-invitation-filter="from"></label>
      <label><span>到</span><input type="date" value="${esc(filters.to)}" min="${esc(oldest)}" max="${esc(newest)}" data-invitation-filter="to"></label>
      <label><span class="sr-only">邀请对象</span><select data-invitation-filter="person" aria-label="按邀请对象筛选"><option value="all"${filters.person === "all" ? " selected" : ""}>全部邀请对象</option>${invitationPersonOptions()}</select></label>
      <label><span class="sr-only">状态</span><select data-invitation-filter="status"><option value="all"${filters.status === "all" ? " selected" : ""}>全部状态</option><option value="pending"${filters.status === "pending" ? " selected" : ""}>等待选择</option><option value="needs_correction"${filters.status === "needs_correction" ? " selected" : ""}>待修改选项</option><option value="accepted"${filters.status === "accepted" ? " selected" : ""}>已接受</option><option value="paused"${filters.status === "paused" ? " selected" : ""}>已暂停</option><option value="failed"${filters.status === "failed" ? " selected" : ""}>发送失败</option></select></label>
      <button class="button delivery-filter-clear" type="button" data-clear-invitation-filters>清除</button>
      <p class="delivery-history-summary" data-invitation-filter-summary></p>
    </div>`;
  }

  function applyInvitationFilter() {
    const filters = state.invitationFilters;
    const query = String(filters.query || "").trim().toLocaleLowerCase();
    const rows = Array.from(root.querySelectorAll("[data-invitation-filter-row]"));
    let visibleCount = 0;
    rows.forEach((row) => {
      const date = row.dataset.filterDate || "";
      const visible = (!query || String(row.dataset.filterText || "").toLocaleLowerCase().includes(query))
        && (!filters.from || date >= filters.from)
        && (!filters.to || date <= filters.to)
        && (filters.person === "all" || row.dataset.filterPerson === filters.person)
        && (filters.status === "all" || String(row.dataset.filterStatus || "").split(" ").includes(filters.status));
      row.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    const total = rows.length;
    const dates = rows.map((row) => row.dataset.filterDate).filter(Boolean).sort();
    const oldest = dates[0] || "";
    const newest = dates.at(-1) || "";
    const summary = root.querySelector("[data-invitation-filter-summary]");
    if (summary) summary.textContent = `显示 ${number(visibleCount)} / ${number(total)} 条邀请结果${oldest && newest ? ` · 完整范围 ${oldest} 至 ${newest}` : ""}`;
    const empty = root.querySelector("[data-invitation-filter-empty]");
    if (empty) empty.hidden = visibleCount > 0;
  }

  function drawerContent() {
    const data = state.data || {};
    if (state.drawerTab === "deliveries") {
      return `${deliveryFilterToolbar()}<div class="table-wrap delivery-table"><table><thead><tr><th>时间</th><th>服务</th><th>方式</th><th>内容</th><th>推送给</th><th>状态</th><th>证据 / 错误</th></tr></thead><tbody>${deliveryRows()}</tbody></table></div>`;
    }
    const groupInvitations = data.group_invitations || [];
    const groupAcceptances = groupInvitations.reduce((sum, item) => sum + Number(item.accepted_count || 0), 0);
    return `<p class="drawer-summary">人员邀请 ${number((data.invitations || []).length)} 条 · 群聊邀请 ${number(groupInvitations.length)} 个 · 群成员已接受 ${number(groupAcceptances)} 人</p>${invitationFilterToolbar()}<div class="table-wrap"><table><thead><tr><th>邀请对象</th><th>发送时间</th><th>状态</th><th>消息 ID</th></tr></thead><tbody>${invitationRows()}</tbody></table></div>`;
  }

  function scheduleSummary(schedule) {
    if (!schedule?.enabled) return "未启用；保存后由频率调度器按香港时间执行";
    const next = schedule.next_run_at ? schedule.next_run_at.replace("T", " ").replace("+08:00", "") : "等待下一个有效日期";
    const last = schedule.last_status === "verified" ? "上次已生成并推送" : schedule.last_status === "queued" ? "上次推送等待重试" : schedule.last_status === "failed" ? `上次失败：${schedule.last_error || "请查看日志"}` : "尚未执行";
    return `下次 ${next} · ${last}`;
  }

  function weeklyReports() {
    return (state.data?.reports || []).filter((item) => item.report_type === "weekly");
  }

  function performanceReports() {
    return (state.data?.reports || []).filter((item) => item.report_type === "carrier-performance");
  }

  function selectedWeeklyReport() {
    if (!state.manualWeeklyPath) return null;
    return (state.data?.reports || []).find((item) => item.report_type === "weekly" && item.path === state.manualWeeklyPath) || null;
  }

  function selectedPerformanceReport() {
    if (!state.manualPerformancePath) return null;
    return performanceReports().find((item) => item.path === state.manualPerformancePath) || null;
  }

  function weeklySelectionCopy() {
    const report = selectedWeeklyReport();
    return report
      ? `周报将使用${report.is_edited ? "已编辑版本" : "所选正式版本"}“${report.name}”；业绩摘要与新闻仍按原链路选择。`
      : "未指定周报版本；系统会沿用原有链路，自动选择最新正式生成版。";
  }

  function performanceSelectionCopy() {
    const report = selectedPerformanceReport();
    return report
      ? `业绩摘要将使用${report.is_edited ? "已编辑版本" : "所选正式版本"}“${report.name}”。`
      : "未指定业绩摘要版本；系统会自动选择最新正式生成版。";
  }

  function reportSelectionCopy() {
    return `${weeklySelectionCopy()} ${performanceSelectionCopy()}`;
  }

  function weeklyPickerLabel() {
    const report = selectedWeeklyReport();
    if (!report) return "自动选择最新正式版";
    return `${report.is_edited ? "编辑稿" : "正式版"} · ${report.name}`;
  }

  function weeklyPickerOptions() {
    const automaticSelected = state.manualWeeklyPath ? "" : " is-selected";
    const options = [`<button class="weekly-report-option${automaticSelected}" type="button" role="option" aria-selected="${String(!state.manualWeeklyPath)}" data-weekly-report-option="" data-weekly-report-search="自动 最新 正式版"><span class="weekly-report-radio" aria-hidden="true"></span><span><strong>自动选择最新正式版</strong><small>保留现有正式版链路</small></span></button>`];
    weeklyReports().forEach((report) => {
      const selected = state.manualWeeklyPath === report.path;
      const version = report.is_edited ? `编辑稿${report.edit_revision ? ` r${number(report.edit_revision)}` : ""}` : "正式版";
      options.push(`<button class="weekly-report-option${selected ? " is-selected" : ""}" type="button" role="option" aria-selected="${String(selected)}" data-weekly-report-option="${esc(report.path)}" data-weekly-report-search="${esc(`${version} ${report.name} ${report.mtime_text || ""}`)}"><span class="weekly-report-radio" aria-hidden="true"></span><span><strong>${esc(report.name)}</strong><small>${esc(version)} · ${esc(report.mtime_text || "未记录时间")}</small></span></button>`);
    });
    return options.join("");
  }

  function weeklyReportPicker() {
    const reportCount = weeklyReports().length;
    return `<div class="weekly-report-picker${state.weeklyPickerOpen ? " is-open" : ""}" data-weekly-report-picker>
      <span class="weekly-picker-title">手动推送周报版本</span>
      <button class="weekly-picker-trigger" type="button" data-weekly-picker-trigger aria-haspopup="listbox" aria-expanded="${String(state.weeklyPickerOpen)}"${state.weeklyPickerBusy ? " disabled" : ""}><span>${esc(weeklyPickerLabel())}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"></path></svg></button>
      <div class="weekly-picker-popover"${state.weeklyPickerOpen ? "" : " hidden"}>
        <label class="weekly-picker-search"><span class="sr-only">筛选周报版本</span><input type="search" value="${esc(state.weeklyPickerQuery)}" data-weekly-picker-search placeholder="按名称、版本或日期筛选" autocomplete="off"><small>${number(reportCount)} 个版本</small></label>
        <div class="weekly-picker-options" role="listbox" aria-label="选择下次手动推送的周报版本">${weeklyPickerOptions()}</div>
        <p class="weekly-picker-empty" data-weekly-picker-empty hidden>没有匹配的周报版本</p>
      </div>
    </div>`;
  }

  function performancePickerLabel() {
    const report = selectedPerformanceReport();
    if (!report) return "自动选择最新正式版";
    return `${report.is_edited ? "编辑稿" : "正式版"} · ${report.name}`;
  }

  function performancePickerOptions() {
    const automaticSelected = state.manualPerformancePath ? "" : " is-selected";
    const options = [`<button class="weekly-report-option${automaticSelected}" type="button" role="option" aria-selected="${String(!state.manualPerformancePath)}" data-performance-report-option="" data-performance-report-search="自动 最新 正式版"><span class="weekly-report-radio" aria-hidden="true"></span><span><strong>自动选择最新正式版</strong><small>保留现有正式版链路</small></span></button>`];
    performanceReports().forEach((report) => {
      const selected = state.manualPerformancePath === report.path;
      const version = report.is_edited ? `编辑稿${report.edit_revision ? ` r${number(report.edit_revision)}` : ""}` : "正式版";
      options.push(`<button class="weekly-report-option${selected ? " is-selected" : ""}" type="button" role="option" aria-selected="${String(selected)}" data-performance-report-option="${esc(report.path)}" data-performance-report-search="${esc(`${version} ${report.name} ${report.mtime_text || ""}`)}"><span class="weekly-report-radio" aria-hidden="true"></span><span><strong>${esc(report.name)}</strong><small>${esc(version)} · ${esc(report.mtime_text || "未记录时间")}</small></span></button>`);
    });
    return options.join("");
  }

  function performanceReportPicker() {
    const reportCount = performanceReports().length;
    return `<div class="weekly-report-picker${state.performancePickerOpen ? " is-open" : ""}" data-performance-report-picker>
      <span class="weekly-picker-title">业绩摘要推送版本</span>
      <button class="weekly-picker-trigger" type="button" data-performance-picker-trigger aria-haspopup="listbox" aria-expanded="${String(state.performancePickerOpen)}"${state.performancePickerBusy ? " disabled" : ""}><span>${esc(performancePickerLabel())}</span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m7 10 5 5 5-5"></path></svg></button>
      <div class="weekly-picker-popover"${state.performancePickerOpen ? "" : " hidden"}>
        <label class="weekly-picker-search"><span class="sr-only">筛选业绩摘要版本</span><input type="search" value="${esc(state.performancePickerQuery)}" data-performance-picker-search placeholder="按名称、版本或日期筛选" autocomplete="off"><small>${number(reportCount)} 个版本</small></label>
        <div class="weekly-picker-options" role="listbox" aria-label="选择下次推送的业绩摘要版本">${performancePickerOptions()}</div>
        <p class="weekly-picker-empty" data-performance-picker-empty hidden>没有匹配的业绩摘要版本</p>
      </div>
    </div>`;
  }

  function countdownText(schedule) {
    if (!schedule?.enabled) return "自动发送已暂停";
    const next = Date.parse(schedule.next_run_at || "");
    if (!Number.isFinite(next)) return "等待下一次自动发送排期";
    const remaining = Math.max(0, next - Date.now());
    const days = Math.floor(remaining / 86400000);
    const hours = Math.floor((remaining % 86400000) / 3600000);
    return `距离下一次自动发送还有 ${days} 天 ${hours} 小时`;
  }

  function updateScheduleCountdown() {
    const schedule = state.data?.report_schedule;
    root.querySelectorAll("[data-report-schedule-countdown]").forEach((element) => {
      element.textContent = countdownText(schedule);
      element.title = scheduleSummary(schedule);
    });
    const performanceSchedule = state.data?.performance_schedule;
    root.querySelectorAll("[data-performance-schedule-countdown]").forEach((element) => {
      element.textContent = countdownText(performanceSchedule);
      element.title = scheduleSummary(performanceSchedule);
    });
  }

  function render() {
    const data = state.data;
    if (!data) return;
    // Polling replaces these nodes every 15 seconds; keep each reader's position.
    const scrollPositions = new Map();
    [".invite-list-main", ".subscriber-table"].forEach((selector) => {
      const container = root.querySelector(selector);
      if (container) scrollPositions.set(selector, { top: container.scrollTop, left: container.scrollLeft });
    });
    const openGroupTargets = new Set(Array.from(
      root.querySelectorAll(".group-invite-record[open] [data-invite-group-candidate]"),
      (input) => input.value,
    ));
    const openInvitationHistoryGroups = new Set(Array.from(
      root.querySelectorAll(".invitation-history-group[open]"),
      (details) => details.dataset.historyGroup,
    ));
    const inviteCount = (data.invite_candidates || []).length;
    const groupInviteCount = currentGroupInvitations().length;
    const schedule = data.report_schedule || { days: [15, 30], time: "09:00", enabled: false };
    const performanceSchedule = data.performance_schedule || { days: [15, 30], time: "09:00", enabled: false };
    const newsSchedule = data.strategic_news_schedule || { enabled: false, times_text: "04:00 / 14:00", delivery_times: ["08:00", "18:30"], delivery_times_text: "08:00 / 18:30", timezone_label: "香港时间", dispatch_rule: "个人推送必须等对应爬虫完成；群内仍在爬完后立即发送" };
    root.innerHTML = `<div class="admin">
      ${state.notice ? `<p class="notice ${esc(state.noticeKind)}" role="status" aria-live="polite">${esc(state.notice)}</p>` : ""}
      <main class="three-block-layout">
        <div class="upper-grid">
          <section class="surface invite-surface"><header class="surface-header"><div><h2>邀请</h2><p>${number(inviteCount)} 人在待邀请名单${groupInviteCount ? ` · ${number(groupInviteCount)} 个群邀请` : ""}</p></div><div class="surface-actions">${compactFilter("invite")}<button class="icon-button" type="button" data-open-people aria-label="添加人员" title="添加人员">${icon("add")}</button><button class="button primary" type="button" data-send-invites>${icon("send")}<span>发送所选</span></button></div></header><div class="surface-body invite-list-main">${candidateRows()}</div></section>
          <section class="surface subscriber-surface"><header class="surface-header"><div><h2>订阅者</h2><p>${number((data.subscribers || []).length)} 人 · 仅显示已订阅内容的对应设置</p></div><div class="surface-actions">${compactFilter("subscriber")}<button class="icon-button" type="button" data-open-management aria-label="查看管理记录" title="邀请结果、订阅者与推送记录">${icon("history")}<span class="icon-badge">${number((data.deliveries || []).length)}</span></button><button class="icon-button primary" type="button" data-manual-push-all aria-label="一键推送当前选择给全部有效订阅者" title="一键推送"${manualPushBusy() ? " disabled" : ""}>${icon("send")}</button></div></header><div class="surface-body table-wrap subscriber-table"><table><thead><tr><th>姓名</th><th>订阅内容</th><th><span class="setting-section-title">报告设置</span>报告接收方式</th><th><span class="setting-section-title">战略新闻设置</span>新闻兴趣板块（可多选，每次最多抽取4个）</th><th>新闻推送频率</th><th>每次新闻条数</th><th>新闻接收时间（香港时间）<small>早间≥08:00，下午≥14:00；提前则自动调整</small></th><th><span class="setting-section-title">订阅管理</span>订阅状态</th><th>恢复默认设置</th><th>保存修改</th><th>立即推送</th></tr></thead><tbody>${compactSubscriberRows()}</tbody></table></div></section>
        </div>
        <section class="surface version-surface"><header class="surface-header"><div><h2>推送版本</h2><p>分别选择周报和业绩摘要的推送版本；不选则自动使用最新正式版</p></div></header><div class="surface-body report-version-grid"><div>${weeklyReportPicker()}<p>${esc(weeklySelectionCopy())}</p></div><div>${performanceReportPicker()}<p>${esc(performanceSelectionCopy())}</p></div></div></section>
        <section class="surface push-surface"><header class="surface-header"><div><h2>定时推送</h2><p>仅当接收人已订阅对应内容且自动排期已启用时推送</p></div></header><div class="surface-body"><div class="manual-push-heading news-schedule-heading"><div><h3>战略新闻定时推送</h3><p>爬虫每日 ${esc(newsSchedule.times_text)}（${esc(newsSchedule.timezone_label)}）· ${esc(newsSchedule.dispatch_rule)}</p></div><div class="news-delivery-time-summary" aria-label="当前每日个人推送时间">个人推送 ${esc(newsSchedule.delivery_times_text || "08:00 / 18:30")}</div></div><form id="newsScheduleForm" class="news-schedule-form"><label>早间个人推送时间（香港，不早于08:00）<input name="morningTime" type="time" value="${esc((newsSchedule.delivery_times || ["08:00", "18:30"])[0])}" required></label><label>下午个人推送时间（香港，不早于14:00）<input name="afternoonTime" type="time" value="${esc((newsSchedule.delivery_times || ["08:00", "18:30"])[1])}" required></label><label>自动流程<select name="enabled"><option value="true"${newsSchedule.enabled ? " selected" : ""}>启用</option><option value="false"${newsSchedule.enabled ? "" : " selected"}>暂停</option></select></label><button class="button primary schedule-save" type="submit">保存新闻排期</button><p class="schedule-meta">${newsSchedule.enabled ? "已启用；只有对应爬虫完成后，才会在设定时间向有效订阅者推送" : "已暂停；爬虫和群内消息照常运行，但不会向个人订阅者自动推送"}</p></form><div class="push-divider" role="separator"></div><div class="manual-push-heading weekly-schedule-heading"><div><h3>业绩摘要定时推送</h3><p>按排期推送上方选定的业绩摘要；未选时使用最新正式版</p></div><p class="report-schedule-countdown" data-performance-schedule-countdown title="${esc(scheduleSummary(performanceSchedule))}">${esc(countdownText(performanceSchedule))}</p></div><form id="performanceScheduleForm" class="schedule-form"><label>每月执行日期<input name="days" value="${esc((performanceSchedule.days || [15, 30]).join(", "))}" inputmode="numeric" placeholder="15, 30" required></label><label>执行时间（香港）<input name="time" type="time" value="${esc(performanceSchedule.time || "09:00")}" required></label><label>自动流程<select name="enabled"><option value="true"${performanceSchedule.enabled ? " selected" : ""}>启用</option><option value="false"${performanceSchedule.enabled ? "" : " selected"}>暂停</option></select></label><button class="button primary schedule-save" type="submit">保存业绩摘要排期</button></form><div class="push-divider" role="separator"></div><div class="manual-push-heading weekly-schedule-heading"><div><h3>周报定时推送</h3><p>执行日先生成当天最新周报；成功后仅向已订阅周报且状态启用的人员推送</p></div><p class="report-schedule-countdown" data-report-schedule-countdown title="${esc(scheduleSummary(schedule))}">${esc(countdownText(schedule))}</p></div><form id="reportScheduleForm" class="schedule-form"><label>每月执行日期<input name="days" value="${esc((schedule.days || [15, 30]).join(", "))}" inputmode="numeric" placeholder="15, 30" required></label><label>执行时间（香港）<input name="time" type="time" value="${esc(schedule.time || "09:00")}" required></label><label>自动流程<select name="enabled"><option value="true"${schedule.enabled ? " selected" : ""}>启用</option><option value="false"${schedule.enabled ? "" : " selected"}>暂停</option></select></label><button class="button primary schedule-save" type="submit">保存周报排期</button></form></div></section>
      </main>
      <div class="drawer-backdrop" data-drawer-backdrop${state.drawerOpen ? "" : " hidden"}><aside class="management-drawer" role="dialog" aria-modal="true" aria-label="管理记录"><header class="drawer-header"><div><h2>记录</h2><p>邀请结果与推送回读</p></div><button class="icon-button" type="button" data-close-management aria-label="关闭记录">${icon("close")}</button></header><nav class="drawer-tabs" aria-label="记录分类"><button type="button" data-drawer-tab="invitations" class="${state.drawerTab === "invitations" ? "is-active" : ""}">邀请结果</button><button type="button" data-drawer-tab="deliveries" class="${state.drawerTab === "deliveries" ? "is-active" : ""}">推送记录</button></nav><div class="drawer-body">${drawerContent()}</div></aside></div>
      <div class="drawer-backdrop" data-people-backdrop${state.peopleOpen ? "" : " hidden"}><aside class="people-picker" role="dialog" aria-modal="true" aria-label="添加邀请人员"><header class="drawer-header"><div><h2>添加人员</h2><p>搜索飞书通讯录并加入待邀请名单</p></div><button class="icon-button" type="button" data-close-people aria-label="关闭人员选择">${icon("close")}</button></header><div class="people-picker-body"><form class="people-search" id="peopleSearchForm"><input name="query" value="${esc(state.searchQuery)}" maxlength="50" aria-label="飞书检索关键字" placeholder="搜索姓名或群聊" required><button class="icon-button primary" type="submit" aria-label="搜索飞书人员和群聊" title="搜索">${icon("search")}</button></form><div class="people-results">${searchResultRows()}</div></div></aside></div>
    </div>`;
    root.querySelectorAll("[data-subscriber-row]").forEach((row) => {
      syncRowDependentSettings(row, Array.from(row.querySelectorAll('.service-check input:checked'), (input) => input.value));
    });
    root.querySelectorAll(".group-invite-record").forEach((details) => {
      const targetId = details.querySelector("[data-invite-group-candidate]")?.value || "";
      details.open = openGroupTargets.has(targetId);
    });
    root.querySelectorAll(".invitation-history-group").forEach((details) => {
      details.open = openInvitationHistoryGroups.has(details.dataset.historyGroup);
    });
    applySavedFilters();
    if (state.weeklyPickerOpen) applyWeeklyPickerFilter(state.weeklyPickerQuery);
    if (state.performancePickerOpen) applyPerformancePickerFilter(state.performancePickerQuery);
    updateScheduleCountdown();
    scheduleNoticeDismissal();
    scrollPositions.forEach((position, selector) => {
      const container = root.querySelector(selector);
      if (!container) return;
      container.scrollTop = position.top;
      container.scrollLeft = position.left;
    });
  }

  function scheduleNoticeDismissal() {
    const signature = state.notice ? `${state.noticeKind}\u0000${state.notice}` : "";
    if (!signature) {
      window.clearTimeout(noticeTimer);
      window.clearTimeout(noticeExitTimer);
      scheduledNoticeSignature = "";
      return;
    }
    if (state.noticeKind === "progress") {
      window.clearTimeout(noticeTimer);
      window.clearTimeout(noticeExitTimer);
      scheduledNoticeSignature = signature;
      return;
    }
    if (signature === scheduledNoticeSignature) return;
    window.clearTimeout(noticeTimer);
    window.clearTimeout(noticeExitTimer);
    scheduledNoticeSignature = signature;
    noticeTimer = window.setTimeout(() => {
      if (scheduledNoticeSignature !== signature) return;
      root.querySelector(".notice")?.classList.add("is-leaving");
      noticeExitTimer = window.setTimeout(() => {
        if (scheduledNoticeSignature !== signature) return;
        state.notice = "";
        state.noticeKind = "";
        scheduledNoticeSignature = "";
        render();
      }, 180);
    }, 1000);
  }

  async function loadData({ keepNotice = false } = {}) {
    if (!keepNotice) { state.notice = "正在刷新后台数据…"; state.noticeKind = ""; }
    const subscriptions = await fetch("/api/subscriptions", { cache: "no-store" });
    const payload = await subscriptions.json();
    if (!subscriptions.ok || !payload.ok) throw new Error(payload.error || `HTTP ${subscriptions.status}`);
    state.data = payload;
    const serverPath = String(payload.weekly_report_preference?.path || "");
    state.manualWeeklyPath = (payload.reports || []).some((item) => item.report_type === "weekly" && item.path === serverPath) ? serverPath : "";
    const performanceServerPath = String(payload.performance_report_preference?.path || "");
    state.manualPerformancePath = (payload.reports || []).some((item) => item.report_type === "carrier-performance" && item.path === performanceServerPath) ? performanceServerPath : "";
    if (!keepNotice) { state.notice = ""; state.noticeKind = ""; }
    const serverPushJob = payload.manual_push_job;
    if (["queued", "running"].includes(serverPushJob?.status)) {
      state.manualPushJob = serverPushJob;
      state.notice = manualPushProgressText(serverPushJob);
      state.noticeKind = "progress";
    }
    render();
    if (manualPushBusy()) scheduleManualPushPoll(state.manualPushJob.job_id);
  }

  function applyWeeklyPickerFilter(query) {
    const normalized = String(query || "").trim().toLocaleLowerCase();
    let visible = 0;
    root.querySelectorAll("[data-weekly-report-option]").forEach((option) => {
      const matches = !normalized || String(option.dataset.weeklyReportSearch || "").toLocaleLowerCase().includes(normalized);
      option.hidden = !matches;
      if (matches) visible += 1;
    });
    const empty = root.querySelector("[data-weekly-picker-empty]");
    if (empty) empty.hidden = visible > 0;
  }

  function applyPerformancePickerFilter(query) {
    const normalized = String(query || "").trim().toLocaleLowerCase();
    let visible = 0;
    root.querySelectorAll("[data-performance-report-option]").forEach((option) => {
      const matches = !normalized || String(option.dataset.performanceReportSearch || "").toLocaleLowerCase().includes(normalized);
      option.hidden = !matches;
      if (matches) visible += 1;
    });
    const empty = root.querySelector("[data-performance-picker-empty]");
    if (empty) empty.hidden = visible > 0;
  }

  async function saveWeeklyReportPreference(path) {
    const previous = state.manualWeeklyPath;
    state.weeklyPickerBusy = true;
    state.weeklyPickerOpen = false;
    state.manualWeeklyPath = String(path || "");
    render();
    try {
      const response = await fetch("/api/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "setWeeklyReportPreference", weeklyReportPath: state.manualWeeklyPath }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.manualWeeklyPath = String(payload.result?.path || "");
      state.notice = state.manualWeeklyPath ? `已设为下次推送：${selectedWeeklyReport()?.name || "所选周报"}` : "已恢复自动选择最新正式版";
      state.noticeKind = "success";
      window.parent.postMessage({ type: "cmhk-weekly-report-preference", path: state.manualWeeklyPath }, location.origin);
      await loadData({ keepNotice: true });
    } catch (error) {
      state.manualWeeklyPath = previous;
      state.notice = `周报版本保存失败：${error.message}`;
      state.noticeKind = "error";
      render();
    } finally {
      state.weeklyPickerBusy = false;
      render();
    }
  }

  async function savePerformanceReportPreference(path) {
    const previous = state.manualPerformancePath;
    state.performancePickerBusy = true;
    state.performancePickerOpen = false;
    state.manualPerformancePath = String(path || "");
    render();
    try {
      const response = await fetch("/api/subscriptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "setPerformanceReportPreference", performanceReportPath: state.manualPerformancePath }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      state.manualPerformancePath = String(payload.result?.path || "");
      state.notice = state.manualPerformancePath ? `已设为下次业绩摘要推送：${selectedPerformanceReport()?.name || "所选版本"}` : "业绩摘要已恢复自动选择最新正式版";
      state.noticeKind = "success";
      window.parent.postMessage({ type: "cmhk-performance-report-preference", path: state.manualPerformancePath }, location.origin);
      await loadData({ keepNotice: true });
    } catch (error) {
      state.manualPerformancePath = previous;
      state.notice = `业绩摘要版本保存失败：${error.message}`;
      state.noticeKind = "error";
      render();
    } finally {
      state.performancePickerBusy = false;
      render();
    }
  }

  function announceDeliveredMessage(action, evidence) {
    const messages = {
      pushLatest: ["订阅消息已送达", "正式内容已发送并完成回读"],
      invite: ["订阅邀请已送达", "邀请消息已发送并完成回读"],
      publish: ["订阅卡片已送达", "卡片已发送并完成回读"],
    };
    const copy = messages[action];
    if (!copy || window.parent === window) return;
    window.parent.postMessage({
      type: "cmhk-workspace-motion",
      event: { kind: "subscription", target: "subscriptions", title: copy[0], detail: evidence ? `${copy[1]} · ${evidence}` : copy[1] },
    }, location.origin);
  }

  async function requestSubscription(payload) {
    const response = await fetch("/api/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    return result;
  }

  async function post(payload, pendingText) {
    state.notice = pendingText;
    state.noticeKind = "";
    render();
    document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    const result = await requestSubscription(payload);
    if (["update", "resetSubscriber"].includes(payload.action)) subscriberDrafts.delete(payload.openId);
    const evidence = result.result?.message_id || result.result?.batch_id || "已完成";
    state.notice = `操作成功：${evidence}${result.result?.adjustments?.length ? "；" + result.result.adjustments.join("；") : ""}`;
    state.noticeKind = "success";
    await loadData({ keepNotice: true });
    announceDeliveredMessage(payload.action, evidence);
  }

  function scheduleManualPushPoll(jobId, delay = 800) {
    if (!jobId) return;
    if (manualPushPollTimer && manualPushPollId === jobId) return;
    window.clearTimeout(manualPushPollTimer);
    manualPushPollId = jobId;
    manualPushPollTimer = window.setTimeout(() => {
      manualPushPollTimer = 0;
      pollManualPush(jobId);
    }, delay);
  }

  async function pollManualPush(jobId) {
    try {
      const response = await fetch(`/api/subscriptions/push-status?id=${encodeURIComponent(jobId)}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      const job = payload.job || {};
      state.manualPushJob = job;
      if (["queued", "running"].includes(job.status)) {
        state.notice = manualPushProgressText(job);
        state.noticeKind = "progress";
        render();
        scheduleManualPushPoll(jobId);
        return;
      }
      manualPushPollId = "";
      if (job.status === "completed") {
        const failed = Number(job.result?.failed_count || 0);
        state.notice = failed ? `推送已结束，其中 ${failed} 项失败；请查看推送记录` : "推送完成，所有消息均已确认发送";
        state.noticeKind = failed ? "error" : "success";
        render();
        if (!failed) announceDeliveredMessage("pushLatest", job.result?.batch_id || job.job_id);
        loadData({ keepNotice: true }).catch(() => {});
      } else {
        state.notice = `推送失败：${job.error || job.detail || "未知错误"}`;
        state.noticeKind = "error";
        render();
      }
    } catch (error) {
      manualPushPollId = "";
      state.notice = `推送状态读取失败：${error.message}；后台任务可能仍在继续`;
      state.noticeKind = "error";
      render();
      scheduleManualPushPoll(jobId, 3000);
    }
  }

  async function startManualPush(payload, pendingText) {
    state.manualPushJob = { status: "queued", detail: pendingText, completed_steps: 0, total_steps: 0 };
    state.notice = pendingText;
    state.noticeKind = "progress";
    render();
    const response = await fetch("/api/subscriptions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...payload, action: "pushLatestAsync" }),
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
    state.manualPushJob = result.result;
    state.notice = manualPushProgressText(result.result);
    state.noticeKind = "progress";
    render();
    scheduleManualPushPoll(result.result?.job_id);
  }

  document.addEventListener("click", async (event) => {
    const weeklyPickerTrigger = event.target.closest("[data-weekly-picker-trigger]");
    if (weeklyPickerTrigger) {
      state.weeklyPickerOpen = !state.weeklyPickerOpen;
      render();
      if (state.weeklyPickerOpen) requestAnimationFrame(() => root.querySelector("[data-weekly-picker-search]")?.focus());
      return;
    }
    const weeklyOption = event.target.closest("[data-weekly-report-option]");
    if (weeklyOption) {
      await saveWeeklyReportPreference(weeklyOption.dataset.weeklyReportOption || "");
      return;
    }
    if (state.weeklyPickerOpen && !event.target.closest("[data-weekly-report-picker]")) {
      state.weeklyPickerOpen = false;
      const picker = root.querySelector("[data-weekly-report-picker]");
      picker?.classList.remove("is-open");
      picker?.querySelector(".weekly-picker-popover")?.setAttribute("hidden", "");
      picker?.querySelector("[data-weekly-picker-trigger]")?.setAttribute("aria-expanded", "false");
    }
    const performancePickerTrigger = event.target.closest("[data-performance-picker-trigger]");
    if (performancePickerTrigger) {
      state.performancePickerOpen = !state.performancePickerOpen;
      render();
      if (state.performancePickerOpen) requestAnimationFrame(() => root.querySelector("[data-performance-picker-search]")?.focus());
      return;
    }
    const performanceOption = event.target.closest("[data-performance-report-option]");
    if (performanceOption) {
      await savePerformanceReportPreference(performanceOption.dataset.performanceReportOption || "");
      return;
    }
    if (state.performancePickerOpen && !event.target.closest("[data-performance-report-picker]")) {
      state.performancePickerOpen = false;
      const picker = root.querySelector("[data-performance-report-picker]");
      picker?.classList.remove("is-open");
      picker?.querySelector(".weekly-picker-popover")?.setAttribute("hidden", "");
      picker?.querySelector("[data-performance-picker-trigger]")?.setAttribute("aria-expanded", "false");
    }
    const filterTrigger = event.target.closest("[data-filter-trigger]");
    if (filterTrigger) {
      const section = filterTrigger.dataset.filterTrigger;
      const panel = root.querySelector(`#${section}-filter-panel`);
      const opening = Boolean(panel?.hidden);
      root.querySelectorAll(".compact-filter-panel").forEach((item) => { item.hidden = true; });
      root.querySelectorAll("[data-filter-trigger]").forEach((trigger) => trigger.setAttribute("aria-expanded", "false"));
      if (panel) panel.hidden = !opening;
      filterTrigger.setAttribute("aria-expanded", String(opening));
      state.openFilter = opening ? section : "";
      if (opening) panel?.querySelector("input:checked")?.focus();
      return;
    }
    const resetFilter = event.target.closest("[data-filter-reset]");
    if (resetFilter) {
      const section = resetFilter.dataset.filterReset;
      Object.keys(state.filters[section]).forEach((field) => { state.filters[section][field] = "all"; });
      root.querySelectorAll(`[data-filter-section="${section}"][value="all"]`).forEach((input) => { input.checked = true; });
      applySectionFilter(section);
      return;
    }
    if (state.openFilter && !event.target.closest("[data-compact-filter]")) {
      const trigger = root.querySelector(`[data-filter-trigger="${state.openFilter}"]`);
      const panel = root.querySelector(`#${state.openFilter}-filter-panel`);
      if (panel) panel.hidden = true;
      trigger?.setAttribute("aria-expanded", "false");
      state.openFilter = "";
    }
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
    if (event.target.closest("[data-manual-push-all]")) {
      const confirmed = await window.CMHKDialog.confirm({ title: "向全部订阅者推送？", message: reportSelectionCopy(), detail: "消息发送后无法撤回，系统会按每位订阅者设置发送并逐条回读结果。", confirmLabel: "确认全部推送" });
      if (!confirmed) return;
      try { await startManualPush({ confirmBulk: true, weeklyReportPath: state.manualWeeklyPath, performanceReportPath: state.manualPerformancePath }, "正在创建后台推送任务…"); }
      catch (error) { state.manualPushJob = null; state.notice = `推送失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    const manualPerson = event.target.closest("[data-manual-push-person]");
    if (manualPerson) {
      const row = manualPerson.closest("[data-subscriber-row]");
      const targetOpenId = row?.dataset.subscriberRow || "";
      const targetName = row?.querySelector(".table-person-name")?.textContent?.trim() || "当前订阅者";
      const confirmed = await window.CMHKDialog.confirm({ title: `向 ${targetName} 推送？`, message: reportSelectionCopy(), detail: `系统会按 ${targetName} 当前订阅设置发送；消息发送后无法撤回，完成后会回读结果。`, confirmLabel: "确认推送" });
      if (!confirmed) return;
      try { await startManualPush({ targetOpenId, weeklyReportPath: state.manualWeeklyPath, performanceReportPath: state.manualPerformancePath }, `正在创建给 ${targetName} 的后台推送任务…`); }
      catch (error) { state.manualPushJob = null; state.notice = `推送失败：${error.message}`; state.noticeKind = "error"; render(); }
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
    if (event.target.closest("[data-clear-delivery-filters]")) {
      state.deliveryFilters = { query: "", from: "", to: "", service: "all", recipient: "all", status: "all" };
      render();
      return;
    }
    if (event.target.closest("[data-clear-invitation-filters]")) {
      state.invitationFilters = { query: "", from: "", to: "", person: "all", status: "all" };
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
    const inviteChat = event.target.closest("[data-invite-chat]");
    if (inviteChat) {
      const chatId = inviteChat.dataset.inviteChat || "";
      const chatName = inviteChat.dataset.inviteChatName || "该群聊";
      const confirmed = await window.CMHKDialog.confirm({ title: `向“${chatName}”发送邀请？`, message: "系统将向该群发送一张订阅邀请卡片。", detail: "群内每个人的选择会分别保存，并保留发送与回读记录。", confirmLabel: "发送群邀请" });
      if (!confirmed) return;
      try {
        await post({ action: "inviteTarget", targetId: chatId, confirmInvite: true }, `正在向“${chatName}”发送群邀请并回读…`);
        state.peopleOpen = false;
        render();
      } catch (error) { state.notice = `群邀请发送失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.closest("[data-send-invites]")) {
      const ids = Array.from(document.querySelectorAll("[data-invite-candidate]:checked")).map((item) => item.value);
      const groups = Array.from(document.querySelectorAll("[data-invite-group-candidate]:checked"), (item) => ({ id: item.value, name: item.dataset.inviteGroupName || "飞书群聊" }));
      if (!ids.length && !groups.length) { state.notice = "请先勾选要邀请的人员或群聊。"; state.noticeKind = "error"; render(); return; }
      const targetSummary = [ids.length ? `${ids.length} 人` : "", groups.length ? `${groups.length} 个群` : ""].filter(Boolean).join("、");
      const confirmed = await window.CMHKDialog.confirm({ title: `向选中的${targetSummary}发送邀请？`, message: `系统将向当前选中的${targetSummary}发送订阅邀请卡片。`, detail: "群内每个人将各自填写订阅偏好；发送后逐项回读，未选中的对象不会收到邀请。", confirmLabel: `发送给${targetSummary}` });
      if (!confirmed) return;
      state.notice = `正在向选中的${targetSummary}发送邀请并回读…`;
      state.noticeKind = "";
      render();
      document.querySelectorAll("button").forEach((button) => { button.disabled = true; });
      let sentPeople = 0;
      let sentGroups = 0;
      const failures = [];
      if (ids.length) {
        try {
          const payload = await requestSubscription({ action: "invite", callbackOpenIds: ids, confirmInvite: true });
          const result = payload.result || {};
          sentPeople = Number(result.sent_count || 0);
          (result.results || []).forEach((item) => {
            if (item.status === "failed") failures.push(`${item.display_name || "人员"}：${item.error || "发送失败"}`);
            else state.selectedInviteUsers.delete(item.callback_open_id);
          });
        } catch (error) { failures.push(`人员邀请：${error.message}`); }
      }
      for (const group of groups) {
        try {
          await requestSubscription({ action: "inviteTarget", targetId: group.id, targetType: "chat", confirmInvite: true });
          sentGroups += 1;
          state.selectedInviteGroups.delete(group.id);
        } catch (error) { failures.push(`${group.name}：${error.message}`); }
      }
      const sentSummary = [sentPeople ? `${sentPeople} 人` : "", sentGroups ? `${sentGroups} 个群` : ""].filter(Boolean).join("、") || "0 个对象";
      state.notice = failures.length ? `已发送 ${sentSummary}；${failures.length} 项失败，可保留勾选后重试` : `集体邀请已发送：${sentSummary}`;
      state.noticeKind = failures.length ? "error" : "success";
      try { await loadData({ keepNotice: true }); }
      catch (error) {
        state.notice = `${state.notice}；列表刷新失败：${error.message}`;
        state.noticeKind = "error";
        render();
      }
      if (sentPeople || sentGroups) announceDeliveredMessage("invite", sentSummary);
      return;
    }
    const reset = event.target.closest("[data-reset-subscriber]");
    if (reset) {
      const openId = reset.closest("[data-subscriber-row]").dataset.subscriberRow;
      try {
        await post({ action: "resetSubscriber", openId }, "正在恢复此人的默认选项…");
      } catch (error) { state.notice = `恢复失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    const save = event.target.closest("[data-save-subscriber]");
    if (save) {
      const row = save.closest("[data-subscriber-row]");
      const services = Array.from(row.querySelectorAll('.service-check input[type="checkbox"]:checked')).map((input) => input.value);
      const newsCategories = Array.from(row.querySelectorAll('[data-news-category]:checked')).map((input) => input.value);
      try { await post({ action: "update", openId: row.dataset.subscriberRow, services, newsCategories, reportMode: row.querySelector("[data-subscriber-report-mode]").value, newsFrequency: row.querySelector("[data-subscriber-news-frequency]").value, newsItemLimit: Number(row.querySelector("[data-subscriber-news-limit]").value), newsDeliveryTimes: Array.from(row.querySelectorAll("[data-subscriber-news-time]"), (input) => input.value), status: row.querySelector("[data-subscriber-status]").value }, "正在保存订阅者设置…"); }
      catch (error) { state.notice = `保存失败：${error.message}`; state.noticeKind = "error"; render(); }
    }
  });

  document.addEventListener("submit", async (event) => {
    if (event.target.id === "newsScheduleForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      try {
        await post({ action: "updateNewsSchedule", enabled: values.enabled === "true", deliveryTimes: [values.morningTime, values.afternoonTime] }, "正在保存战略新闻自动排期…");
        state.notice = `战略新闻排期已保存：个人推送 ${values.morningTime} / ${values.afternoonTime}，${values.enabled === "true" ? "自动推送已启用" : "自动推送已暂停"}`;
        state.noticeKind = "success";
        render();
      } catch (error) { state.notice = `新闻排期保存失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.id === "reportScheduleForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      try {
        await post({ action: "updateReportSchedule", days: values.days, time: values.time, enabled: values.enabled === "true" }, "正在保存周报自动排期…");
        state.notice = `周报排期已保存：每月 ${values.days} 日 ${values.time}（香港时间）${values.enabled === "true" ? "自动执行" : "，当前暂停"}`;
        state.noticeKind = "success";
        render();
      } catch (error) { state.notice = `排期保存失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
    if (event.target.id === "performanceScheduleForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      try {
        await post({ action: "updatePerformanceSchedule", days: values.days, time: values.time, enabled: values.enabled === "true" }, "正在保存业绩摘要自动排期…");
        state.notice = `业绩摘要排期已保存：每月 ${values.days} 日 ${values.time}（香港时间）${values.enabled === "true" ? "自动执行" : "，当前暂停"}`;
        state.noticeKind = "success";
        render();
      } catch (error) { state.notice = `业绩摘要排期保存失败：${error.message}`; state.noticeKind = "error"; render(); }
      return;
    }
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
  });

  document.addEventListener("change", (event) => {
    const inviteUser = event.target.closest("[data-invite-candidate]");
    if (inviteUser) {
      if (inviteUser.checked) state.selectedInviteUsers.add(inviteUser.value);
      else state.selectedInviteUsers.delete(inviteUser.value);
      return;
    }
    const inviteGroup = event.target.closest("[data-invite-group-candidate]");
    if (inviteGroup) {
      if (inviteGroup.checked) state.selectedInviteGroups.add(inviteGroup.value);
      else state.selectedInviteGroups.delete(inviteGroup.value);
      return;
    }
    const deliveryFilter = event.target.closest("[data-delivery-filter]");
    if (deliveryFilter) {
      state.deliveryFilters[deliveryFilter.dataset.deliveryFilter] = deliveryFilter.value;
      applyDeliveryFilter();
      return;
    }
    const invitationFilter = event.target.closest("[data-invitation-filter]");
    if (invitationFilter) {
      state.invitationFilters[invitationFilter.dataset.invitationFilter] = invitationFilter.value;
      applyInvitationFilter();
      return;
    }
    const row = event.target.closest("[data-subscriber-row]");
    if (row) {
      const services = Array.from(row.querySelectorAll('.service-check input:checked'), input => input.value);
      syncRowDependentSettings(row, services);
      const draft = {
        services,
        news_categories: Array.from(row.querySelectorAll('[data-news-category]:checked'), input => input.value),
        report_mode: row.querySelector('[data-subscriber-report-mode]').value,
        news_frequency: row.querySelector('[data-subscriber-news-frequency]').value,
        news_item_limit: Number(row.querySelector('[data-subscriber-news-limit]').value),
        news_delivery_times: Array.from(row.querySelectorAll('[data-subscriber-news-time]'), input => input.value),
        status: row.querySelector('[data-subscriber-status]').value,
      };
      subscriberDrafts.set(row.dataset.subscriberRow, draft);
      const savedItem = (state.data?.subscribers || []).find((item) => item.open_id === row.dataset.subscriberRow) || {};
      syncResetButton(row.querySelector('[data-reset-subscriber]'), { ...savedItem, ...draft });
      row.querySelector('[data-save-subscriber]').textContent = "保存 *";
      return;
    }
    const filter = event.target.closest("[data-filter-section][data-filter-field]");
    if (!filter) return;
    state.filters[filter.dataset.filterSection][filter.dataset.filterField] = filter.value;
    applySectionFilter(filter.dataset.filterSection);
  });

  document.addEventListener("input", (event) => {
    const deliveryFilter = event.target.closest('[data-delivery-filter="query"]');
    if (deliveryFilter) {
      state.deliveryFilters.query = deliveryFilter.value;
      applyDeliveryFilter();
      return;
    }
    const invitationFilter = event.target.closest('[data-invitation-filter="query"]');
    if (invitationFilter) {
      state.invitationFilters.query = invitationFilter.value;
      applyInvitationFilter();
      return;
    }
    const weeklySearch = event.target.closest("[data-weekly-picker-search]");
    if (weeklySearch) {
      state.weeklyPickerQuery = weeklySearch.value;
      applyWeeklyPickerFilter(weeklySearch.value);
      return;
    }
    const performanceSearch = event.target.closest("[data-performance-picker-search]");
    if (!performanceSearch) return;
    state.performancePickerQuery = performanceSearch.value;
    applyPerformancePickerFilter(performanceSearch.value);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.openFilter) {
      const section = state.openFilter;
      const panel = root.querySelector(`#${section}-filter-panel`);
      if (panel) panel.hidden = true;
      root.querySelector(`[data-filter-trigger="${section}"]`)?.setAttribute("aria-expanded", "false");
      root.querySelector(`[data-filter-trigger="${section}"]`)?.focus();
      state.openFilter = "";
      return;
    }
    if (event.key === "Escape" && state.weeklyPickerOpen) {
      state.weeklyPickerOpen = false;
      render();
      root.querySelector("[data-weekly-picker-trigger]")?.focus();
      return;
    }
    if (event.key === "Escape" && state.performancePickerOpen) {
      state.performancePickerOpen = false;
      render();
      root.querySelector("[data-performance-picker-trigger]")?.focus();
      return;
    }
    if (event.key === "Escape" && (state.drawerOpen || state.peopleOpen)) {
      state.drawerOpen = false;
      state.peopleOpen = false;
      render();
    }
  });

  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin) return;
    const path = String(event.data.path || "");
    if (event.data?.type === "cmhk-weekly-report-preference") {
      state.manualWeeklyPath = weeklyReports().some((report) => report.path === path) ? path : "";
      state.weeklyPickerOpen = false;
    } else if (event.data?.type === "cmhk-performance-report-preference") {
      state.manualPerformancePath = performanceReports().some((report) => report.path === path) ? path : "";
      state.performancePickerOpen = false;
    } else return;
    render();
  });

  loadData().catch((error) => {
    root.innerHTML = `<div class="loading">订阅后台加载失败：${esc(error.message)}</div>`;
  });
  window.setInterval(() => {
    if (!document.hidden) loadData({ keepNotice: true }).catch(() => {});
  }, 15000);
  window.setInterval(updateScheduleCountdown, 60000);
})();
