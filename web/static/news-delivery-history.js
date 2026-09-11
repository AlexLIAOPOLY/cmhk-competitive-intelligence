/* Personal news delivery readback. All interactions here are read-only. */
(() => {
  "use strict";
  const canvasWidth = 2716;
  const snapshots = new Map();
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const labels = { verified: "已确认发送", queued: "等待发送", sending: "发送中", retrying: "等待重试", sent: "已发送 · 待确认", prepared: "已准备", failed: "发送失败", cancelled: "已取消", superseded: "已停用" };
  const time = (value) => {
    if (!value) return "未记录";
    const stamp = new Date(value);
    return Number.isNaN(stamp.getTime()) ? String(value) : new Intl.DateTimeFormat("zh-CN", { timeZone: "Asia/Hong_Kong", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(stamp);
  };
  async function request(params) {
    const response = await fetch(`/api/subscriptions/news-deliveries?${new URLSearchParams(params)}`, { cache: "no-store", signal: AbortSignal.timeout(15000) });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || payload.message || `推送记录读取失败（${response.status}）`);
    return payload;
  }
  function setSummary(payload) { if (payload?.ok && payload.date) snapshots.set(payload.date, payload); }
  async function load(date) {
    try { const payload = await request({ date }); setSummary(payload); }
    catch (error) { snapshots.set(date, { error: error.message }); }
  }
  function decorate(model, date) {
    const snapshot = snapshots.get(date);
    const summary = snapshot?.summary;
    const health = !summary ? { key: "unknown", label: snapshot?.error ? "读取失败" : "待读取" }
      : summary.issue ? { key: "warning", label: "有异常" }
      : summary.pending ? { key: "running", label: "待完成" }
      : summary.total ? { key: "healthy", label: "已确认" } : { key: "unknown", label: "无记录" };
    model.nodes.splice(model.nodes.findIndex((node) => node.key === "weekly-result") + 1, 0, { key: "news-subscription", label: "战略新闻订阅推送", value: summary?.recipients ?? "—", unit: "位接收人",
      note: summary ? `确认 ${summary.verified} 次 · 待完成 ${summary.pending} 次 · 异常/停用 ${summary.issue} 次` : snapshot?.error || "点击查看每个人的推送记录",
      health, variant: "output", position: [2468, 92], cornerBadge: "个人推送", cornerTone: "cyan",
      purpose: "按每个人的订阅排期推送战略新闻；点击查看接收人、发送时间、状态和新闻明细", details: [], evidence: date });
    model.canvasSize[0] = Math.max(model.canvasSize[0], canvasWidth);
    model.edges.push(["news-output", "news-subscription", "按个人订阅排期", "news-subscription", { key: "unknown", label: "订阅排期" }]);
    return model;
  }
  const field = (label, value) => `<div><dt>${esc(label)}</dt><dd>${esc(value || "未记录")}</dd></div>`;
  function detail(item) {
    const archived = item.content_source === "receipt";
    const contentLabel = archived ? (item.status_group === "verified" || item.receipt_status === "sent" ? "已发送新闻内容" : "已准备新闻内容（发送尚未确认）")
      : item.content_source === "candidate_archive" ? "任务候选新闻（历史未留存最终发送内容）" : "该历史记录未保存新闻内容";
    const news = item.news_items || [];
    return `<dl class="news-delivery-facts">${field("任务日期", item.task_date)}${field("创建时间", time(item.created_at))}${field(item.retry_count ? "最近排期 / 重试时间" : "排期时间", time(item.due_at))}${field("发送完成时间", time(item.delivered_at))}${field("回执确认时间", time(item.verified_at))}${field("重试次数", String(item.retry_count))}${field("推送批次", item.batch_id)}${field("消息回执", item.message_ids.join("\n"))}</dl>
      ${item.error ? `<p class="news-delivery-error">${esc(item.status_group === "verified" ? "历史错误" : "失败 / 重试原因")}：${esc(item.error)}</p>` : ""}
      <h4>${esc(contentLabel)}${news.length ? ` · ${news.length} 条` : ""}</h4>
      ${archived && news.length ? '<p class="news-delivery-muted">下列为入选新闻及来源；最终推送文案见下方保存的完整卡片文字。</p>' : ""}
      ${archived && !news.length ? "<p>该卡片未包含新闻条目，可能是本轮没有新的可推送事件；以保存的卡片文字为准。</p>" : ""}
      ${!archived ? "<p class=\"news-delivery-muted\">历史消息的发送状态来自推送台账；候选新闻不能用来确认最终卡片内容。</p>" : ""}
      <ol class="news-delivery-news">${news.map((entry) => {
        const url = /^https?:\/\//i.test(String(entry.url || "")) ? entry.url : "";
        return `<li><h5>${url ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(entry.title || "未记录标题")}</a>` : esc(entry.title || "未记录标题")}</h5><p>${esc(entry.summary || entry.content || "未保存摘要")}</p><small>${esc([entry.category, entry.source, entry.publishedAt || entry.published_at].filter(Boolean).join(" · "))}</small></li>`;
      }).join("")}</ol>
      ${item.card_text ? `<details class="news-delivery-card-text"><summary>查看保存的完整卡片文字</summary><pre>${esc(item.card_text)}</pre></details>` : ""}`;
  }
  function open(date) {
    const dialog = document.querySelector("#newsLineageDialog");
    const body = document.querySelector("#newsLineageDialogBody");
    if (!dialog || !body) return;
    body.innerHTML = `<header><div><span>个人订阅 · 香港时间</span><h2>战略新闻订阅推送</h2><p>按任务日期查看每个人的推送记录，跨日补发仍归原任务日期。</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header>
      <div class="news-lineage-dialog-content news-delivery-history"><div class="news-delivery-filters">
      <label>任务日期<input type="date" data-delivery-date value="${esc(date)}"></label><label class="news-delivery-all"><input type="checkbox" data-delivery-all>全部日期</label>
      <label>接收人<select data-delivery-recipient><option value="">全部接收人</option></select></label>
      <label>状态<select data-delivery-status><option value="">全部状态</option><option value="verified">已确认发送</option><option value="pending">等待 / 发送中 / 重试</option><option value="issue">失败 / 取消 / 停用</option></select></label>
      <label class="news-delivery-search">搜索<input type="search" data-delivery-search placeholder="姓名、批次、错误"></label><button type="button" data-delivery-refresh>刷新记录</button></div>
      <p class="news-delivery-summary" role="status"></p><div class="news-delivery-people"></div></div>`;
    const root = body.querySelector(".news-delivery-history");
    const statusLine = root.querySelector(".news-delivery-summary");
    const people = root.querySelector(".news-delivery-people");
    const recipient = root.querySelector("[data-delivery-recipient]");
    const dateInput = root.querySelector("[data-delivery-date]");
    const allDates = root.querySelector("[data-delivery-all]");
    let data = null;
    let generation = 0;
    const active = () => dialog.open && root.isConnected;
    const render = () => {
      if (!data) return;
      const filter = root.querySelector("[data-delivery-status]").value;
      const query = root.querySelector("[data-delivery-search]").value.trim().toLowerCase();
      const rows = data.deliveries.filter((item) => (!recipient.value || item.open_id === recipient.value) && (!filter || item.status_group === filter) && (!query || [item.recipient_name, item.open_id, item.title, item.batch_id, item.content_ref, item.error].join(" ").toLowerCase().includes(query)));
      const groups = new Map();
      rows.forEach((item) => { if (!groups.has(item.open_id)) groups.set(item.open_id, []); groups.get(item.open_id).push(item); });
      statusLine.textContent = `${data.date === "all" ? "全部日期" : data.date} · ${groups.size} 位接收人 · ${rows.length} 次推送 · 已确认 ${rows.filter((i) => i.status_group === "verified").length} 次 · 待完成 ${rows.filter((i) => i.status_group === "pending").length} 次 · 异常/停用 ${rows.filter((i) => i.status_group === "issue").length} 次`;
      people.innerHTML = [...groups.entries()].map(([id, records]) => `<section class="news-delivery-person"><header><h3>${esc(records[0].recipient_name || "未记录姓名")}</h3><span>${records.length} 次推送</span></header><p class="news-delivery-identity">${esc(id)}</p>
        ${records.map((item) => `<details class="news-delivery-record" data-delivery-id="${item.id}"><summary><div><strong>${esc(item.title)}</strong><small>任务 ${esc(item.task_date)} · ${item.delivered_at ? `发送 ${esc(time(item.delivered_at))}` : `创建 ${esc(time(item.created_at))}`}</small></div><span class="news-delivery-status is-${esc(item.status_group)}">${esc(labels[item.status] || item.status)}</span><span class="news-delivery-expand">查看明细</span></summary><div class="news-delivery-detail"></div></details>`).join("")}</section>`).join("") || '<p class="news-delivery-empty">没有匹配的战略新闻推送记录。</p>';
      people.querySelectorAll("[data-delivery-id]").forEach((record) => record.addEventListener("toggle", async () => {
        if (!record.open || record.dataset.loaded) return;
        record.dataset.loaded = "loading";
        const target = record.querySelector(".news-delivery-detail");
        target.innerHTML = '<p role="status">正在读取新闻和消息回执…</p>';
        try {
          const payload = await request({ id: record.dataset.deliveryId });
          if (!active() || !record.isConnected) return;
          target.innerHTML = detail(payload.delivery);
          record.dataset.loaded = "true";
        } catch (error) {
          if (!active() || !record.isConnected) return;
          delete record.dataset.loaded;
          target.innerHTML = `<p class="news-delivery-error" role="alert">${esc(error.message)}；收起后重新展开可重试。</p>`;
        }
      }));
    };
    const refresh = async () => {
      const current = ++generation;
      data = null;
      people.innerHTML = "";
      statusLine.textContent = "正在读取个人推送记录…";
      try {
        const payload = await request({ date: allDates.checked ? "all" : dateInput.value || date });
        if (!active() || current !== generation) return;
        data = payload;
        setSummary(payload);
        const selected = recipient.value;
        const options = new Map(data.deliveries.map((item) => [item.open_id, item.recipient_name || item.open_id]));
        recipient.innerHTML = '<option value="">全部接收人</option>' + [...options].map(([id, name]) => `<option value="${esc(id)}">${esc(name)}</option>`).join("");
        recipient.value = options.has(selected) ? selected : "";
        render();
      } catch (error) { if (active() && current === generation) statusLine.textContent = `${error.message}，可点击“刷新记录”重试。`; }
    };
    root.addEventListener("change", (event) => {
      if (event.target.matches("[data-delivery-date], [data-delivery-all]")) { dateInput.disabled = allDates.checked; refresh(); }
      else render();
    });
    root.querySelector("[data-delivery-search]").addEventListener("input", render);
    root.querySelector("[data-delivery-refresh]").addEventListener("click", refresh);
    if (!dialog.open) dialog.showModal();
    refresh();
  }
  window.CmhkNewsDeliveryHistory = { canvasWidth, decorate, setSummary, load, open };
})();
