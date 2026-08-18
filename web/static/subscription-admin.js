(() => {
  "use strict";

  const root = document.querySelector("#subscriptionAdmin");
  const state = { data: null, briefs: [], searchResults: [], notice: "", noticeKind: "" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const serviceLabel = (value) => ({ weekly: "战略双周报", performance: "运营商业绩摘要", news: "战略新闻" }[value] || value);
  const modeLabel = (value) => ({ text: "文字", pdf: "PDF 文件", pdf_audio: "PDF + 独立语音", audio: "语音", both: "文字 + 语音" }[value] || value);
  const invitationStatus = (value) => ({ pending: "等待选择", accepted: "已接受", paused: "已暂停", failed: "发送失败" }[value] || value);
  const avatar = (item) => item.avatar_url
    ? `<img class="avatar" src="/api/subscriptions/avatar?openId=${encodeURIComponent(item.directory_open_id || item.callback_open_id || "")}" alt="" loading="lazy">`
    : `<span class="avatar avatar-fallback" aria-hidden="true">${esc((item.display_name || "飞").slice(0, 1))}</span>`;

  function serviceOptions() {
    return [["weekly", "战略双周报"], ["performance", "运营商业绩摘要"], ["news", "战略新闻"]]
      .map(([value, label]) => `<option value="${value}">${label}</option>`).join("");
  }

  function frequencyOptions(selected = "immediate") {
    const frequencies = state.data?.frequencies || [
      { key: "immediate", label: "即时接收" },
      { key: "daily", label: "每天 18:00" },
      { key: "weekly", label: "每周五 18:00" },
    ];
    return frequencies.map((item) => `<option value="${esc(item.key)}"${item.key === selected ? " selected" : ""}>${esc(item.label)}</option>`).join("");
  }

  function reportOptions() {
    const reports = state.data?.reports || [];
    if (!reports.length) return '<option value="">当前没有可推送报告</option>';
    return reports.map((item) => `<option value="${esc(item.path)}" data-report-type="${esc(item.report_type)}">${esc(item.name)} · PDF</option>`).join("");
  }

  function subscriberRows() {
    const rows = state.data?.subscribers || [];
    if (!rows.length) return '<tr><td colspan="8" class="empty">尚无订阅者。先把测试卡片发给自己，确认后再发布到同事群。</td></tr>';
    return rows.map((item) => `<tr data-subscriber-row="${esc(item.open_id)}">
      <td class="name">${esc(item.display_name)}</td><td class="muted">${esc(item.open_id.slice(0, 8))}…</td>
      ${["weekly", "performance", "news"].map((service) => `<td><label class="service-check"><input type="checkbox" value="${service}"${item.services.includes(service) ? " checked" : ""}><span>${service === "weekly" ? "周报" : service === "performance" ? "业绩" : "新闻"}</span></label></td>`).join("")}
      <td><select data-subscriber-frequency>${frequencyOptions(item.frequency)}</select></td>
      <td><select data-subscriber-status><option value="active"${item.status === "active" ? " selected" : ""}>启用</option><option value="paused"${item.status === "paused" ? " selected" : ""}>暂停</option></select></td>
      <td><button class="button" type="button" data-save-subscriber>保存</button></td></tr>`).join("");
  }

  function deliveryRows() {
    const rows = state.data?.deliveries || [];
    if (!rows.length) return '<tr><td colspan="6" class="empty">尚无推送记录</td></tr>';
    return rows.slice(0, 40).map((item) => `<tr><td>${esc(item.created_at)}</td><td>${esc(serviceLabel(item.service))}</td><td>${esc(modeLabel(item.mode))}</td><td class="muted">${esc(item.content_ref || "—")}</td><td><span class="status ${esc(item.status)}">${item.status === "verified" ? "已发送并回读" : item.status === "queued" ? "等待频率时点" : item.status === "sending" ? "发送中" : item.status === "retrying" ? "等待重试" : "失败"}</span></td><td title="${esc(item.error || "")}">${item.error ? esc(item.error.slice(0, 90)) : number(item.message_ids?.length || 0) + " 条消息"}</td></tr>`).join("");
  }

  function searchResultRows() {
    if (!state.searchResults.length) return '<p class="empty compact">输入姓名搜索授权通讯录；搜索本身不会发送消息。</p>';
    return state.searchResults.map((item) => `<label class="person-card">
      <input type="checkbox" value="${esc(item.directory_open_id)}" data-directory-result>
      ${avatar(item)}<span><strong>${esc(item.display_name)}</strong><small>${esc((item.department_names || []).join(" / ") || item.job_title || "飞书用户")}</small></span>
    </label>`).join("");
  }

  function candidateRows() {
    const rows = state.data?.invite_candidates || [];
    if (!rows.length) return '<tr><td colspan="5" class="empty">尚无待邀请人员。请先从飞书通讯录搜索并加入名单。</td></tr>';
    return rows.map((item) => `<tr><td><label class="person-cell"><input type="checkbox" value="${esc(item.callback_open_id)}" data-invite-candidate>${avatar(item)}<span><strong>${esc(item.display_name)}</strong><small>${esc((item.department_names || []).join(" / ") || item.job_title || "已验证飞书用户")}</small></span></label></td><td class="muted">${esc(item.source === "directory" ? "授权通讯录" : "已有订阅者")}</td><td>${esc(invitationStatus(item.latest_invitation?.status || "未邀请"))}</td><td>${esc(item.latest_invitation?.sent_at || "—")}</td><td class="muted">${esc(item.latest_invitation?.message_id || "—")}</td></tr>`).join("");
  }

  function invitationRows() {
    const rows = state.data?.invitations || [];
    if (!rows.length) return '<tr><td colspan="6" class="empty">尚无邀请记录</td></tr>';
    return rows.map((item) => `<tr><td><span class="person-cell">${avatar(item)}<span><strong>${esc(item.display_name)}</strong><small>${esc(item.callback_open_id.slice(0, 10))}…</small></span></span></td><td><span class="status ${esc(item.status)}">${esc(invitationStatus(item.status))}</span></td><td>${esc(item.sent_at)}</td><td>${esc(item.responded_at || "—")}</td><td class="muted">${esc(item.message_id)}</td><td title="${esc(item.last_error || "")}">${esc(item.last_error ? item.last_error.slice(0, 90) : "已完成消息回读")}</td></tr>`).join("");
  }

  function render() {
    const data = state.data;
    if (!data) return;
    const counts = Object.fromEntries((data.services || []).map((item) => [item.key, item.subscriber_count]));
    const permission = data.invitation_permissions || {};
    const latest = state.briefs[0] || {};
    const newsTitle = latest.title || latest.headline || "战略新闻推送";
    const newsBody = latest.summary || latest.brief || latest.description || "";
    root.innerHTML = `<div class="admin">
      <header class="topbar"><div><p class="eyebrow">FEISHU DELIVERY CONTROL</p><h1>订阅与推送管理</h1><p class="subtitle">同事通过飞书卡片自助选择；管理员控制正式内容和投递范围。</p></div><button class="button" type="button" data-refresh>刷新数据</button></header>
      <p class="notice ${esc(state.noticeKind)}" role="status">${esc(state.notice || `数据更新于 ${data.updated_at || "刚刚"}。默认测试模式只发给系统管理员。`)}</p>
      <section class="kpis"><article class="kpi"><span>有效订阅者</span><strong>${number(data.active_subscriber_count)}</strong><small>服务器持久化</small></article><article class="kpi"><span>战略双周报</span><strong>${number(counts.weekly)}</strong><small>PDF 文件</small></article><article class="kpi"><span>业绩摘要</span><strong>${number(counts.performance)}</strong><small>PDF 文件</small></article><article class="kpi"><span>战略新闻</span><strong>${number(counts.news)}</strong><small>即时文字</small></article></section>
      <section class="permission-panel"><div><strong>飞书人员目录：${permission.status === "ready" ? `已接通 · ${number(permission.people_count)} 人` : "受限或尚未同步"}</strong><span>${esc(permission.summary || "")}</span></div><div class="scope-tags">${(permission.required_scopes || []).map((item) => `<span>${esc(item.scope)}</span>`).join("")}</div><small>${esc(permission.availability_note || "")}${permission.synced_at ? ` · 最近同步 ${esc(permission.synced_at)}` : ""}</small></section>
      <section class="controls">
        <article class="panel"><header class="panel-header"><div><h2>搜索并邀请同事</h2><span>显示飞书头像 · 逐人勾选</span></div><button class="button" type="button" data-refresh-directory>刷新通讯录</button></header><div class="panel-body"><form class="people-search" id="peopleSearchForm"><label>姓名关键字<input name="query" maxlength="50" placeholder="输入中文或英文姓名" required></label><button class="button primary" type="submit">搜索飞书人员</button><button class="button" type="button" data-test-card>先发给我测试</button></form><div class="people-results">${searchResultRows()}</div><div class="inline-actions"><button class="button" type="button" data-add-candidates>加入待邀请名单</button><span>加入名单不会发送消息</span></div></div></article>
        <article class="panel"><header class="panel-header"><div><h2>执行内容推送</h2><span>逐条回读消息 ID</span></div></header><div class="panel-body"><form id="pushForm"><div class="form-row"><label>服务<select name="service">${serviceOptions()}</select></label><label>交付方式<select name="mode"><option value="pdf">仅 PDF</option><option value="pdf_audio">PDF + 单独语音</option></select></label></div><label data-report>正式报告<select name="path">${reportOptions()}</select></label><label data-news hidden>新闻标题<input name="title" value="${esc(newsTitle)}" maxlength="120"></label><label data-news hidden>新闻正文<textarea name="body" placeholder="填写经审核的战略新闻正文">${esc(newsBody)}</textarea></label><label class="test-toggle"><input name="testOnly" type="checkbox" checked><span>仅发给我测试；取消勾选后才可向全部有效订阅者推送</span></label><button class="button primary" type="submit">执行推送</button></form></div></article>
      </section>
      <section class="panel"><header class="panel-header"><div><h2>待邀请人员</h2><span>${number((data.invite_candidates || []).length)} 人 · 只有勾选者会收到邀请</span></div><button class="button primary" type="button" data-send-invites>发送选中邀请</button></header><div class="table-wrap"><table><thead><tr><th>人员</th><th>来源</th><th>最近结果</th><th>邀请时间</th><th>消息 ID</th></tr></thead><tbody>${candidateRows()}</tbody></table></div></section>
      <section class="panel"><header class="panel-header"><div><h2>邀请结果</h2><span>待选择 ${number(data.invitation_counts?.pending)} · 已接受 ${number(data.invitation_counts?.accepted)} · 失败 ${number(data.invitation_counts?.failed)}</span></div></header><div class="table-wrap"><table><thead><tr><th>人员</th><th>状态</th><th>发送时间</th><th>响应时间</th><th>消息 ID</th><th>回读 / 错误</th></tr></thead><tbody>${invitationRows()}</tbody></table></div></section>
      <section class="panel"><header class="panel-header"><div><h2>订阅者</h2><span>${number((data.subscribers || []).length)} 人 · 可调整服务、频率或暂停</span></div></header><div class="table-wrap"><table><thead><tr><th>姓名</th><th>飞书身份</th><th>周报</th><th>业绩</th><th>新闻</th><th>接收频率</th><th>状态</th><th>操作</th></tr></thead><tbody>${subscriberRows()}</tbody></table></div></section>
      <section class="panel"><header class="panel-header"><div><h2>推送台账</h2><span>发送与回读证据</span></div></header><div class="table-wrap"><table><thead><tr><th>时间</th><th>服务</th><th>方式</th><th>内容</th><th>状态</th><th>证据 / 错误</th></tr></thead><tbody>${deliveryRows()}</tbody></table></div></section>
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
      form.elements.mode.innerHTML = '<option value="pdf">仅 PDF</option><option value="pdf_audio">PDF + 单独语音</option>';
    }
    Array.from(form.elements.path.options).forEach((option) => {
      const type = form.elements.service.value === "weekly" ? "weekly" : "carrier-performance";
      option.hidden = !news && option.dataset.reportType !== type;
    });
    if (!news) {
      const first = Array.from(form.elements.path.options).find((option) => !option.hidden);
      if (first) form.elements.path.value = first.value;
    }
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
    if (event.target.closest("[data-refresh]")) {
      try { await loadData(); } catch (error) { state.notice = `刷新失败：${error.message}`; state.noticeKind = "error"; render(); }
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
    if (event.target.closest("[data-add-candidates]")) {
      const ids = Array.from(document.querySelectorAll("[data-directory-result]:checked")).map((item) => item.value);
      if (!ids.length) { state.notice = "请先勾选搜索结果中的人员。"; state.noticeKind = "error"; render(); return; }
      try { await post({ action: "addCandidates", directoryOpenIds: ids }, "正在验证人员身份并加入待邀请名单…"); }
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
      try { await post({ action: "update", openId: row.dataset.subscriberRow, services, frequency: row.querySelector("[data-subscriber-frequency]").value, status: row.querySelector("[data-subscriber-status]").value }, "正在保存订阅者设置…"); }
      catch (error) { state.notice = `保存失败：${error.message}`; state.noticeKind = "error"; render(); }
    }
  });

  document.addEventListener("change", (event) => {
    if (event.target.closest('#pushForm [name="service"]')) syncPushFields();
  });

  document.addEventListener("submit", async (event) => {
    if (event.target.id === "peopleSearchForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      try {
        const response = await fetch("/api/subscriptions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: "searchPeople", query: values.query }) });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        state.searchResults = payload.result?.people || [];
        state.notice = `找到 ${state.searchResults.length} 位授权范围内的飞书人员。`;
        state.noticeKind = "success";
        render();
      } catch (error) { state.notice = `人员搜索失败：${error.message}`; state.noticeKind = "error"; render(); }
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

  loadData().catch((error) => {
    root.innerHTML = `<div class="loading">订阅后台加载失败：${esc(error.message)}</div>`;
  });
})();
