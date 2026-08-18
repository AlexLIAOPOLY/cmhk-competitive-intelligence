(() => {
  "use strict";

  const MODULES = ["dashboard", "competitor", "news", "weekly", "performance", "ai"];
  const state = { status: null, metrics: null, briefs: [], starters: [] };
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
    if (updateUrl) history.replaceState(null, "", target === "dashboard" ? location.pathname + location.search : `${location.pathname}${location.search}#workspace=${target}`);
    window.dispatchEvent(new CustomEvent("workspace-tab-change", { detail: { tab: target } }));
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => activateModule(tab.dataset.workspaceTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      let next = index;
      if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
      if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
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
      ${heading("COMPETITOR INTELLIGENCE", "竞对数据分析", "把分散的运营商披露、公开爬取和已核验业绩数据统一为可比较、可追溯的竞争情报底座。", '<button class="workspace-button is-primary" type="button" data-jump-dashboard>查看四域驾驶舱</button>')}
      ${kpis([{ label: "覆盖公司", value: number(summary.companies), note: "香港、内地及国际运营商" }, { label: "指标维度", value: number(summary.metrics), note: "经营、产品、网络与市场" }, { label: "结构化记录", value: number(summary.records), note: "通过质量门禁的数据" }, { label: "已核验记录", value: number(summary.verifiedRecords), note: "具备可回溯来源" }])}
      <div class="workspace-grid"><section class="workspace-panel"><header class="workspace-panel-header"><div><h2>竞对覆盖概览</h2><span>展示当前记录数前 12 家</span></div><input class="workspace-search" id="competitorSearch" type="search" placeholder="搜索公司" aria-label="搜索公司"></header><div id="competitorTable">${competitorTable(top)}</div></section>
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
      ${heading("NEWS ACQUISITION & DELIVERY", "新闻获取与推送", "把定时采集、AI相关性确认、历史语义去重、飞书回写和通知串成一条可审计的情报生产线。", '<button class="workspace-button is-primary" type="button" data-open-news-review>打开新闻审核表</button><a class="workspace-link-button" href="https://cmhk-try.feishu.cn/sheets/NB6Gsi9tChARfGtBDpFc6QfOnmb?sheet=n1fzSN" target="_blank" rel="noreferrer">查看监测规则</a>')}
      ${kpis([{ label: "本轮发现", value: number(summary.discovered), note: funnel.label || "最近扫描" }, { label: "AI确认", value: number(summary.confirmed), note: "相关性与证据核验" }, { label: "本轮新增", value: number(summary.newCount), note: "完成历史语义去重" }, { label: "来源媒体", value: number(summary.sourceCount), note: "本轮有效来源" }])}
      <section class="workspace-panel"><header class="workspace-panel-header"><h2>新闻生产漏斗</h2><span>${esc(funnel.scope || "等待扫描数据")}</span></header><div class="workspace-panel-body"><div class="workspace-pipeline">${stages.map((stage) => `<article class="workspace-stage"><span>${esc(stage.label)}</span><strong>${number(stage.value)}</strong><small>${esc(stage.note)}</small><p>${esc(stage.detail)}</p></article>`).join("") || '<div class="workspace-empty">正在读取流程数据</div>'}</div></div></section>
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
    const title = weekly ? "战略周报" : "业绩摘要模块";
    const kicker = weekly ? "STRATEGY WEEKLY" : "PERFORMANCE DIGEST";
    const description = weekly ? "将一周竞争动态、政策信号和关键判断沉淀为可下载、可播报，并可扩展为订阅服务的战略产品。" : "自动归集运营商定期业绩披露，提炼核心指标、同比变化和经营信号，形成标准化摘要。";
    const action = `<button class="workspace-button is-primary" type="button" data-generate-report="${kind}">${weekly ? "生成最新周报" : "生成业绩摘要"}</button><button class="workspace-button" type="button" data-open-report-library="${kind}">进入报告库</button>`;
    panel.innerHTML = `<div class="workspace-module-inner">${heading(kicker, title, description, action)}
      ${kpis([{ label: "历史产物", value: number(outputs.length), note: weekly ? "战略周报归档" : "业绩摘要归档" }, { label: "音频摘要", value: number(audioCount), note: "可供移动场景收听" }, { label: "最新产物", value: latest ? latest.mtimeText.slice(5, 16) : "—", note: latest?.name || "暂无" }, { label: "交付形态", value: weekly ? "文档 + 音频" : "结构化文档", note: "支持下载与报告库管理" }])}
      <div class="workspace-grid"><section class="workspace-panel"><header class="workspace-panel-header"><div><h2>最近产物</h2><span>显示最近 10 份</span></div></header>${reportRows(outputs)}</section>
      <aside>${weekly ? subscriptionPanel() : performancePanel()}</aside></div></div>`;
    if (weekly) bindSubscriptionForm(panel);
  }

  function subscriptionPanel() {
    return `<section class="workspace-panel"><header class="workspace-panel-header"><h2>订阅方案预览</h2><span>本机方案草案</span></header><div class="workspace-panel-body"><form class="workspace-subscription-form" id="weeklySubscriptionForm"><label>发送频率<select name="frequency"><option value="weekly">每周</option><option value="biweekly">每两周</option><option value="monthly">每月</option></select></label><label>计划交付方式<select name="channel"><option value="feishu">飞书推送</option><option value="library">报告库查阅</option><option value="both">飞书 + 报告库</option></select></label><label>关注主题<select name="topic"><option value="all">综合战略情报</option><option value="competitor">竞对动态</option><option value="policy">政策与监管</option><option value="technology">网络与技术</option></select></label><button class="workspace-button is-primary" type="submit">保存方案草案</button><p class="workspace-form-note" id="subscriptionStatus" role="status" aria-live="polite">此处仅用于展示和保存当前浏览器的方案草案，尚未连接收件人管理或飞书自动发送后台。</p></form></div></section>`;
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
    const summary = state.metrics?.summary || {};
    panel.innerHTML = `<div class="workspace-module-inner">
      ${heading("ASK YOUR DATA", "AI问数模块", "让小竞AI在已核验数据库和网页来源之间协同检索，支持查询、比较、趋势分析、预测与政策解读。", '<button class="workspace-button is-primary" type="button" data-open-ai>打开小竞AI</button>')}
      ${kpis([{ label: "可用问数入口", value: number(state.starters.length), note: "香港市场常用分析场景" }, { label: "结构化记录", value: number(summary.records), note: "可进入问数上下文" }, { label: "可发布 AI 事实", value: number(summary.publishableAiFacts), note: "通过清洗与质量门禁" }, { label: "联网来源", value: "可选", note: "回答中保留来源链接" }])}
      <div class="workspace-grid"><section class="workspace-panel"><header class="workspace-panel-header"><h2>从常用问题开始</h2><span>点击后带入小竞AI</span></header><div class="workspace-panel-body"><div class="workspace-ai-prompts">${state.starters.map((item) => `<button class="workspace-ai-prompt" type="button" data-ai-prompt="${esc(item.prompt)}"><strong>${esc(item.title)}</strong><span>${esc(item.detail)}</span></button>`).join("") || '<div class="workspace-empty">正在读取问数入口</div>'}</div></div></section><aside><section class="workspace-panel"><header class="workspace-panel-header"><h2>回答链路</h2><span>证据优先</span></header><div class="workspace-panel-body"><ul class="workspace-status-list"><li><span>选择数据库</span><strong>按问题范围</strong></li><li><span>召回结构化事实</span><strong>RAG 检索</strong></li><li><span>补充网页来源</span><strong>可切换</strong></li><li><span>生成分析与图表</span><strong>保留依据</strong></li></ul></div></section></aside></div>
    </div>`;
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
    const library = event.target.closest("[data-open-report-library]");
    if (library) openDashboardAction("#reportLibraryButton", () => document.querySelector(`[data-scroll-report="${library.dataset.openReportLibrary}"]`)?.click());
    const generate = event.target.closest("[data-generate-report]");
    if (generate) openDashboardAction(generate.dataset.generateReport === "weekly" ? "#generateButtonSecondary" : "#generatePerformanceButton");
    const prompt = event.target.closest("[data-ai-prompt]");
    const openAi = event.target.closest("[data-open-ai]");
    if (prompt || openAi) {
      document.querySelector("#chatFab")?.click();
      if (prompt) requestAnimationFrame(() => {
        const input = document.querySelector("#chatInput");
        if (!input) return;
        input.value = prompt.dataset.aiPrompt;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.focus();
      });
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
      fetch("/api/strategic-briefs").then((response) => response.ok ? response.json() : Promise.reject(new Error(`briefs ${response.status}`))),
      fetch("/api/chat-starters").then((response) => response.ok ? response.json() : Promise.reject(new Error(`starters ${response.status}`)))
    ]);
    const [statusResult, metricsResult, briefsResult, startersResult] = requests;
    if (statusResult.status === "fulfilled") state.status = statusResult.value.status || {};
    if (metricsResult.status === "fulfilled") state.metrics = metricsResult.value.data || {};
    if (briefsResult.status === "fulfilled") state.briefs = briefsResult.value.items || [];
    if (startersResult.status === "fulfilled") state.starters = startersResult.value.starters || [];

    state.metrics ? renderCompetitor() : renderLoadError("competitor", "竞对");
    (state.status || briefsResult.status === "fulfilled") ? renderNews() : renderLoadError("news", "新闻");
    if (state.status) { renderReports("weekly"); renderReports("performance"); }
    else { renderLoadError("weekly", "周报"); renderLoadError("performance", "业绩摘要"); }
    (state.metrics || startersResult.status === "fulfilled") ? renderAi() : renderLoadError("ai", "AI问数");
    requests.filter((result) => result.status === "rejected").forEach((result) => console.warn("Workspace module data unavailable", result.reason));
  }

  activateModule(moduleFromLocation(), { updateUrl: false });
  loadWorkspaceData();
})();
