(() => {
  "use strict";

  const MODULES = ["dashboard", "monitoring", "competitor", "news", "weekly", "performance", "ai", "log"];
  const state = { status: null, metrics: null, briefs: [] };
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const safeUrl = (value, { allowOutput = false } = {}) => {
    const raw = String(value || "").trim();
    if (allowOutput && raw.startsWith("/outputs/")) return raw;
    try {
      const parsed = new URL(raw, location.origin);
      return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : "#";
    } catch (_error) { return "#"; }
  };

  const tabs = Array.from(document.querySelectorAll("[data-workspace-tab]"));
  const panels = Array.from(document.querySelectorAll("[data-workspace-panel]"));

  function moduleFromLocation() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const requested = params.get("workspace");
    return MODULES.includes(requested) ? requested : "dashboard";
  }

  function activateModule(name, { focus = false, updateUrl = true } = {}) {
    const target = MODULES.includes(name) ? name : "dashboard";
    tabs.forEach((tab) => {
      const selected = tab.dataset.workspaceTab === target;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.workspacePanel !== target; });
    document.body.classList.toggle("workspace-dashboard-active", target === "dashboard");
    syncEmbeddedVisibility(target);
    if (updateUrl) history.replaceState(null, "", target === "dashboard" ? location.pathname + location.search : `${location.pathname}${location.search}#workspace=${target}`);
    window.dispatchEvent(new CustomEvent("workspace-tab-change", { detail: { tab: target } }));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateModule(tab.dataset.workspaceTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) next = (index + 1) % tabs.length;
      if (["ArrowLeft", "ArrowUp"].includes(event.key)) next = (index - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      activateModule(tabs[next].dataset.workspaceTab, { focus: true });
    });
  });
  window.addEventListener("hashchange", () => activateModule(moduleFromLocation(), { updateUrl: false }));

  function heading(kicker, title, description, actions = "") {
    return `<header class="workspace-module-heading"><div><span class="workspace-module-kicker">${esc(kicker)}</span><h1>${esc(title)}</h1><p>${esc(description)}</p></div><div class="workspace-module-actions">${actions}</div></header>`;
  }

  function kpis(items) {
    return `<div class="workspace-kpi-strip">${items.map((item) => `<div class="workspace-kpi"><span>${esc(item.label)}</span><strong>${esc(item.value)}</strong><small>${esc(item.note || "")}</small></div>`).join("")}</div>`;
  }

  function reportRows(items) {
    if (!items.length) return `<div class="workspace-empty">当前没有可展示的报告</div>`;
    return `<div class="workspace-table-scroll-note">表格可左右滑动查看完整内容</div><div class="workspace-table-wrap"><table class="workspace-table"><thead><tr><th style="width:48%">文件</th><th style="width:24%">生成时间</th><th style="width:14%">音频摘要</th><th style="width:14%">操作</th></tr></thead><tbody>${items.slice(0, 10).map((item) => `<tr><td class="workspace-cell-title" title="${esc(item.name)}">${esc(item.name)}</td><td class="workspace-cell-muted">${esc(item.mtimeText)}</td><td>${item.audio?.exists ? "已生成" : "—"}</td><td><a href="${esc(safeUrl(item.url, { allowOutput: true }))}">下载</a></td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderCompetitor() {
    const panel = document.querySelector('[data-workspace-panel="competitor"]');
    const data = state.metrics || {};
    const summary = data.summary || {};
    const rows = Array.isArray(data.rows) ? data.rows : [];
    const companyCounts = rows.reduce((map, row) => map.set(row.company, (map.get(row.company) || 0) + 1), new Map());
    const top = [...companyCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
    panel.innerHTML = `<div class="workspace-module-inner">
      ${kpis([{ label: "覆盖公司", value: number(summary.companies), note: "香港、内地及国际运营商" }, { label: "指标维度", value: number(summary.metrics), note: "经营、产品、网络与市场" }, { label: "结构化记录", value: number(summary.records), note: "通过质量门禁的数据" }, { label: "已核验记录", value: number(summary.verifiedRecords), note: "具备可回溯来源" }])}
      <div class="workspace-grid"><section class="workspace-panel"><header class="workspace-panel-header"><div><h2>竞对覆盖概览</h2><span>展示当前记录数前 12 家</span></div><div class="workspace-panel-actions"><input class="workspace-search" id="competitorSearch" type="search" placeholder="搜索公司" aria-label="搜索公司"><button class="workspace-button" type="button" data-jump-dashboard>四域驾驶舱</button></div></header><div id="competitorTable">${competitorTable(top)}</div></section>
      <aside><section class="workspace-panel"><header class="workspace-panel-header"><h2>数据治理链路</h2><span>当前数据底座</span></header><div class="workspace-panel-body"><ul class="workspace-status-list"><li><span>公开爬取记录</span><strong>${number(summary.crawlRecords)}</strong></li><li><span>可发布 AI 事实</span><strong>${number(summary.publishableAiFacts)}</strong></li><li><span>质量门禁通过</span><strong>${number(summary.qualityPassedRecords)}</strong></li><li><span>被抑制记录</span><strong>${number(summary.suppressedRecords)}</strong></li></ul></div></section><section class="workspace-panel"><header class="workspace-panel-header"><h2>观众能看到什么</h2></header><div class="workspace-panel-body"><ul class="workspace-status-list"><li><span>公司横向对比</span><strong>已覆盖</strong></li><li><span>指标来源回溯</span><strong>已覆盖</strong></li><li><span>数据质量状态</span><strong>已覆盖</strong></li><li><span>四域关系解释</span><strong>驾驶舱入口</strong></li></ul></div></section></aside></div>
    </div>`;
    const search = panel.querySelector("#competitorSearch");
    search?.addEventListener("input", () => {
      const query = search.value.trim().toLowerCase();
      panel.querySelector("#competitorTable").innerHTML = competitorTable(top.filter(([name]) => name.toLowerCase().includes(query)));
    });
  }

  function competitorTable(items) {
    if (!items.length) return `<div class="workspace-empty">没有匹配的公司</div>`;
    return `<div class="workspace-table-wrap"><table class="workspace-table"><thead><tr><th>公司</th><th>记录数</th><th>覆盖状态</th></tr></thead><tbody>${items.map(([name, count]) => `<tr><td class="workspace-cell-title">${esc(name)}</td><td>${number(count)}</td><td><span class="workspace-dot"></span>已入库</td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderNews() {
    const panel = document.querySelector('[data-workspace-panel="news"]');
    const funnel = state.status?.visuals?.newsFunnel || {};
    const summary = funnel.summary || {};
    const stages = Array.isArray(funnel.stages) ? funnel.stages : [];
    panel.innerHTML = `<div class="workspace-module-inner">
      ${kpis([{ label: "本轮发现", value: number(summary.discovered), note: funnel.label || "最近扫描" }, { label: "AI确认", value: number(summary.confirmed), note: "相关性与证据核验" }, { label: "本轮新增", value: number(summary.newCount), note: "完成历史语义去重" }, { label: "来源媒体", value: number(summary.sourceCount), note: "本轮有效来源" }])}
      <section class="workspace-panel"><header class="workspace-panel-header"><div><h2>新闻生产漏斗</h2><span>${esc(funnel.scope || "等待扫描数据")}</span></div><div class="workspace-panel-actions"><button class="workspace-button is-primary" type="button" data-open-news-review>打开新闻审核表</button><a class="workspace-link-button" href="https://cmhk-try.feishu.cn/sheets/NB6Gsi9tChARfGtBDpFc6QfOnmb?sheet=n1fzSN" target="_blank" rel="noreferrer">监测规则</a></div></header><div class="workspace-panel-body"><div class="workspace-pipeline">${stages.map((stage) => `<article class="workspace-stage"><span>${esc(stage.label)}</span><strong>${number(stage.value)}</strong><small>${esc(stage.note)}</small><p>${esc(stage.detail)}</p></article>`).join("") || '<div class="workspace-empty">正在读取流程数据</div>'}</div></div></section>
      <section class="workspace-panel"><header class="workspace-panel-header"><div><h2>最新战略快讯</h2><span>${number(state.briefs.length)} 条已确认内容</span></div></header>${newsTable(state.briefs)}</section>
    </div>`;
  }

  function newsTable(items) {
    if (!items.length) return `<div class="workspace-empty">当前没有已确认快讯</div>`;
    return `<div class="workspace-table-scroll-note">表格可左右滑动查看完整内容</div><div class="workspace-table-wrap"><table class="workspace-table"><thead><tr><th style="width:16%">分类</th><th style="width:36%">标题</th><th style="width:36%">摘要</th><th style="width:12%">来源</th></tr></thead><tbody>${items.slice(0, 10).map((item) => `<tr><td class="workspace-cell-muted">${esc(item.category)}</td><td class="workspace-cell-title" title="${esc(item.title)}">${esc(item.title)}</td><td>${esc(item.summary)}</td><td><a href="${esc(safeUrl(item.source_url))}" target="_blank" rel="noreferrer">原文</a></td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderReports(kind) {
    const weekly = kind === "weekly";
    const panel = document.querySelector(`[data-workspace-panel="${kind}"]`);
    const outputs = (state.status?.outputs || []).filter((item) => item.reportType === (weekly ? "weekly" : "carrier-performance"));
    const audioCount = outputs.filter((item) => item.audio?.exists).length;
    const latest = outputs[0];
    panel.innerHTML = `<div class="workspace-module-inner">
      ${kpis([{ label: "历史产物", value: number(outputs.length), note: weekly ? "战略周报归档" : "业绩摘要归档" }, { label: "音频摘要", value: number(audioCount), note: "可供移动场景收听" }, { label: "最新产物", value: latest ? latest.mtimeText.slice(5, 16) : "—", note: latest?.name || "暂无" }, { label: "交付形态", value: weekly ? "文档 + 音频" : "结构化文档", note: "支持下载与报告库管理" }])}
      <div class="workspace-grid"><div class="workspace-report-host" id="workspaceReportHost-${kind}"></div>
      <aside>${weekly ? subscriptionPanel() : performancePanel()}</aside></div></div>`;
    const outputBlock = document.querySelector(weekly ? "#weeklyOutputBlock" : "#performanceOutputBlock");
    if (outputBlock) {
      outputBlock.hidden = false;
      outputBlock.classList.add("workspace-inline-report-block");
      panel.querySelector(`#workspaceReportHost-${kind}`)?.appendChild(outputBlock);
      outputBlock.querySelector(".output-tabs")?.setAttribute("hidden", "");
      const generateButton = document.querySelector(weekly ? "#generateButtonSecondary" : "#generatePerformanceButton");
      if (generateButton) outputBlock.querySelector(".output-actions")?.prepend(generateButton);
    }
    if (weekly) bindSubscriptionForm(panel);
  }

  function subscriptionPanel() {
    return `<section class="workspace-panel"><header class="workspace-panel-header"><h2>订阅服务 UI DEMO</h2><span>本机方案草案</span></header><div class="workspace-panel-body"><form class="workspace-subscription-form" id="weeklySubscriptionForm"><label>发送频率<select name="frequency"><option value="weekly">每周</option><option value="biweekly">每两周</option><option value="monthly">每月</option></select></label><label>计划交付方式<select name="channel"><option value="feishu">飞书推送</option><option value="library">报告库查阅</option><option value="both">飞书 + 报告库</option></select></label><label>关注主题<select name="topic"><option value="all">综合战略情报</option><option value="competitor">竞对动态</option><option value="policy">政策与监管</option><option value="technology">网络与技术</option></select></label><button class="workspace-button is-primary" type="submit">保存方案草案</button><p class="workspace-form-note" id="subscriptionStatus" role="status" aria-live="polite">此处是订阅服务 UI DEMO，仅保存当前浏览器的方案草案，尚未连接收件人管理或飞书自动发送后台。</p></form></div></section>`;
  }

  function performancePanel() {
    return `<section class="workspace-panel"><header class="workspace-panel-header"><h2>摘要能力</h2><span>标准化提炼</span></header><div class="workspace-panel-body"><ul class="workspace-status-list"><li><span>财务与运营指标抽取</span><strong>已接入</strong></li><li><span>披露期与数值绑定</span><strong>已校验</strong></li><li><span>原始来源追溯</span><strong>已覆盖</strong></li><li><span>批量历史归档</span><strong>已覆盖</strong></li></ul></div></section>`;
  }

  function bindSubscriptionForm(panel) {
    const form = panel.querySelector("#weeklySubscriptionForm");
    let saved = null;
    try { saved = JSON.parse(localStorage.getItem("cmhk-weekly-subscription") || "null"); } catch (_error) { localStorage.removeItem("cmhk-weekly-subscription"); }
    if (saved) Object.entries(saved).forEach(([key, value]) => { if (form.elements[key]) form.elements[key].value = value; });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const values = Object.fromEntries(new FormData(form).entries());
      localStorage.setItem("cmhk-weekly-subscription", JSON.stringify(values));
      form.querySelector("#subscriptionStatus").textContent = "方案草案已保存在当前浏览器；尚未创建正式订阅或触发飞书推送。";
    });
  }

  function renderAi() {
    const panel = document.querySelector('[data-workspace-panel="ai"]');
    panel.innerHTML = `<div class="workspace-embedded-host" id="workspaceAiHost"></div>`;
  }

  function renderEmbeddedShells() {
    const log = document.querySelector('[data-workspace-panel="log"]');
    log.innerHTML = `<div class="workspace-embedded-host" id="workspaceLogHost"></div>`;
  }

  function setupEmbeddedSurfaces() {
    const chat = document.querySelector("#chatModal");
    const log = document.querySelector("#logModal");
    if (chat) {
      chat.classList.add("workspace-inline-surface");
      document.querySelector("#workspaceAiHost")?.appendChild(chat);
    }
    if (log) {
      log.classList.add("workspace-inline-surface");
      document.querySelector("#workspaceLogHost")?.appendChild(log);
    }
  }

  function syncEmbeddedVisibility(target) {
    const chat = document.querySelector("#chatModal");
    const log = document.querySelector("#logModal");
    if (chat) chat.hidden = target !== "ai";
    if (target === "log" && log?.hidden) document.querySelector("#logButton")?.click();
    if (log) log.hidden = target !== "log";
  }

  function setupNavCollapse() {
    const layout = document.querySelector("#workspaceLayout");
    const button = document.querySelector("#workspaceNavCollapse");
    if (!layout || !button) return;
    const apply = (collapsed) => {
      layout.classList.toggle("is-nav-collapsed", collapsed);
      button.setAttribute("aria-expanded", String(!collapsed));
      button.setAttribute("aria-label", collapsed ? "展开项目导航" : "收回项目导航");
      button.title = collapsed ? "展开项目导航" : "收回项目导航";
    };
    apply(localStorage.getItem("cmhk-workspace-nav-collapsed") === "1");
    button.addEventListener("click", () => {
      const collapsed = !layout.classList.contains("is-nav-collapsed");
      apply(collapsed);
      localStorage.setItem("cmhk-workspace-nav-collapsed", collapsed ? "1" : "0");
    });
  }

  function openDashboardAction(selector, callback) {
    activateModule("dashboard");
    requestAnimationFrame(() => {
      document.querySelector(selector)?.click();
      if (callback) requestAnimationFrame(callback);
    });
  }

  document.addEventListener("click", (event) => {
    const jump = event.target.closest("[data-jump-dashboard]");
    if (jump) activateModule("dashboard");
    const news = event.target.closest("[data-open-news-review]");
    if (news) openDashboardAction("#openNewsReviewSheetButton");
    const generate = event.target.closest("[data-generate-report]");
    if (generate) {
      document.querySelector(generate.dataset.generateReport === "weekly" ? "#generateButtonSecondary" : "#generatePerformanceButton")?.click();
    }
  });

  function renderLoadError(module, label) {
    const panel = document.querySelector(`[data-workspace-panel="${module}"]`);
    panel.innerHTML = `<div class="workspace-module-inner"><div class="workspace-panel workspace-error"><div class="workspace-empty" role="status">${esc(label)}数据暂时无法读取，请稍后刷新。</div></div></div>`;
  }

  async function loadWorkspaceData() {
    const requests = await Promise.allSettled([
      fetch("/api/status").then((response) => response.ok ? response.json() : Promise.reject(new Error(`status ${response.status}`))),
      fetch("/api/company-metrics").then((response) => response.ok ? response.json() : Promise.reject(new Error(`metrics ${response.status}`))),
      fetch("/api/strategic-briefs").then((response) => response.ok ? response.json() : Promise.reject(new Error(`briefs ${response.status}`)))
    ]);
    const [statusResult, metricsResult, briefsResult] = requests;
    if (statusResult.status === "fulfilled") state.status = statusResult.value.status || {};
    if (metricsResult.status === "fulfilled") state.metrics = metricsResult.value.data || {};
    if (briefsResult.status === "fulfilled") state.briefs = briefsResult.value.items || [];

    state.metrics ? renderCompetitor() : renderLoadError("competitor", "竞对");
    (state.status || briefsResult.status === "fulfilled") ? renderNews() : renderLoadError("news", "新闻");
    if (state.status) { renderReports("weekly"); renderReports("performance"); }
    else { renderLoadError("weekly", "周报"); renderLoadError("performance", "业绩摘要"); }
    const running = Boolean(state.status?.tasks?.hasRunning);
    const runningDot = document.querySelector("[data-workspace-running]");
    if (runningDot) runningDot.hidden = !running;
    requests.filter((result) => result.status === "rejected").forEach((result) => console.warn("Workspace module data unavailable", result.reason));
  }

  renderAi();
  renderEmbeddedShells();
  setupEmbeddedSurfaces();
  setupNavCollapse();
  activateModule(moduleFromLocation(), { updateUrl: false });
  loadWorkspaceData();
})();
