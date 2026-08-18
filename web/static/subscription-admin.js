(() => {
  "use strict";

  const root = document.querySelector("#subscriptionAdmin");
  const state = { data: null, briefs: [], notice: "", noticeKind: "" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const serviceLabel = (value) => ({ weekly: "战略双周报", performance: "运营商业绩摘要", news: "战略新闻" }[value] || value);
  const modeLabel = (value) => ({ text: "文字", pdf: "PDF 文件", pdf_audio: "PDF + 独立语音", audio: "语音", both: "文字 + 语音" }[value] || value);

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

  function render() {
    const data = state.data;
    if (!data) return;
    const counts = Object.fromEntries((data.services || []).map((item) => [item.key, item.subscriber_count]));
    const targets = (data.targets || []).map((item) => `<option value="${esc(item.chat_id)}">${esc(item.name)}</option>`).join("");
    const latest = state.briefs[0] || {};
    const newsTitle = latest.title || latest.headline || "战略新闻推送";
    const newsBody = latest.summary || latest.brief || latest.description || "";
    root.innerHTML = `<div class="admin">
      <header class="topbar"><div><p class="eyebrow">FEISHU DELIVERY CONTROL</p><h1>订阅与推送管理</h1><p class="subtitle">同事通过飞书卡片自助选择；管理员控制正式内容和投递范围。</p></div><button class="button" type="button" data-refresh>刷新数据</button></header>
      <p class="notice ${esc(state.noticeKind)}" role="status">${esc(state.notice || `数据更新于 ${data.updated_at || "刚刚"}。默认测试模式只发给系统管理员。`)}</p>
      <section class="kpis"><article class="kpi"><span>有效订阅者</span><strong>${number(data.active_subscriber_count)}</strong><small>服务器持久化</small></article><article class="kpi"><span>战略双周报</span><strong>${number(counts.weekly)}</strong><small>PDF 文件</small></article><article class="kpi"><span>业绩摘要</span><strong>${number(counts.performance)}</strong><small>PDF 文件</small></article><article class="kpi"><span>战略新闻</span><strong>${number(counts.news)}</strong><small>即时文字</small></article></section>
      <section class="controls">
        <article class="panel"><header class="panel-header"><div><h2>发布订阅入口</h2><span>自助多选卡片</span></div></header><div class="panel-body"><form class="publish-form" id="publishForm"><label>目标群<select name="targetId" required>${targets || '<option value="">暂无白名单群</option>'}</select></label><button class="button primary" type="submit">发布到群</button><button class="button" type="button" data-test-card>先发给我测试</button></form><p class="form-note">群发布只发送订阅入口，不会自动推送报告或新闻。</p></div></article>
        <article class="panel"><header class="panel-header"><div><h2>执行内容推送</h2><span>逐条回读消息 ID</span></div></header><div class="panel-body"><form id="pushForm"><div class="form-row"><label>服务<select name="service">${serviceOptions()}</select></label><label>交付方式<select name="mode"><option value="pdf">仅 PDF</option><option value="pdf_audio">PDF + 单独语音</option></select></label></div><label data-report>正式报告<select name="path">${reportOptions()}</select></label><label data-news hidden>新闻标题<input name="title" value="${esc(newsTitle)}" maxlength="120"></label><label data-news hidden>新闻正文<textarea name="body" placeholder="填写经审核的战略新闻正文">${esc(newsBody)}</textarea></label><label class="test-toggle"><input name="testOnly" type="checkbox" checked><span>仅发给我测试；取消勾选后才可向全部有效订阅者推送</span></label><button class="button primary" type="submit">执行推送</button></form></div></article>
      </section>
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
    if (event.target.id === "publishForm") {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(event.target).entries());
      if (!window.confirm("确认把订阅入口卡片发布到所选群？这不会推送任何报告或新闻。")) return;
      try { await post({ action: "publish", targetType: "chat", targetId: values.targetId }, "正在发布订阅入口并回读…"); }
      catch (error) { state.notice = `发布失败：${error.message}`; state.noticeKind = "error"; render(); }
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
