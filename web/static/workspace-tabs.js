(() => {
  "use strict";

  const MODULES = ["dashboard", "monitoring", "competitor", "intelligence-map", "news", "weekly", "performance", "review", "subscriptions", "ai", "log", "fault", "architecture", "organization", "footprint"];
  const NEWS_REVIEW_SNAPSHOT_CACHE_KEY = "cmhk-news-review-lineage-snapshot-v1";
  let allowedModules = [];
  const state = {
    status: null,
    metrics: null,
    briefs: [],
    tasks: [],
    faultTotal: 0,
    competitorData: null,
    competitorSelection: { companies: [], metric: "", years: null },
    competitorChartTypes: {},
    competitorInsightRequest: 0,
    competitorInsightController: null,
    competitorInsightRetryTimer: null,
    competitorInsightRetryAttempt: 0,
    newsRuns: [],
    crawlRuns: [],
    newsSelectedDate: "",
    newsSelectedRunIds: [],
    newsRunDetails: {},
    fixedSourceSummary: {},
    newsItemFallback: {},
    newsReviewSheet: null,
    newsRunRequest: 0,
    newsSelectedStage: "search",
    newsLineageZoom: 1,
    newsLineagePaused: false,
    newsLineageFitFrame: 0,
    newsLineageResizeObserver: null,
    newsLineageWindowResizeHandler: null,
    newsLineageTabChangeHandler: null,
    newsLivePollTimer: 0,
    newsLiveRefreshInFlight: false,
    newsLiveReviewTick: 0,
    newsLiveSignature: "",
    schedulerOverview: null,
    executiveIntelligence: null,
    previewRequest: { weekly: 0, performance: 0 },
    activeReportPreview: { weekly: "", performance: "" },
    faultFilters: { status: "all", kind: "all", query: "" },
    faultSort: { key: "time", direction: "desc" },
    faultFeedback: null,
    loadedKeys: new Set(),
    dirtyModules: new Set(),
    renderFrames: {},
  };
  const esc = (value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const number = (value) => new Intl.NumberFormat("zh-CN").format(Number(value || 0));
  const COMPETITOR_CHART_PALETTE = ["#55c7de", "#66d9ad", "#f3b74f", "#9aa8ff", "#ff8e78", "#b98ee8"];
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
  let setWorkspaceNavCollapsed = null;
  const permissionModule = (module) => ({ footprint: "organization", "intelligence-map": "competitor", architecture: "dashboard" }[module] || module);
  const can = (module) => allowedModules.includes(module);
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  const motionState = { queue: Promise.resolve(), knownFaults: new Set(), faultBaselineReady: false, pollingTimer: 0 };
  const MOTION_TYPES = {
    task: { target: "log", kicker: "NEW TASK", icon: "↗", tone: "cyan" },
    fault: { target: "fault", kicker: "ALERT", icon: "!", tone: "red" },
    subscription: { target: "subscriptions", kicker: "DELIVERED", icon: "✓", tone: "mint" },
  };

  const wait = (delay) => new Promise((resolve) => window.setTimeout(resolve, delay));

  function workspaceSignalDot(tab) {
    let dot = tab?.querySelector("[data-workspace-indicator]");
    if (!dot && tab) {
      dot = document.createElement("i");
      dot.className = "workspace-signal-dot";
      dot.dataset.workspaceIndicator = "";
      dot.hidden = true;
      tab.appendChild(dot);
    }
    return dot;
  }

  function clearWorkspaceSignal(module) {
    const tab = document.querySelector(`[data-workspace-tab="${module}"]`);
    const dot = tab?.querySelector("[data-workspace-indicator]");
    if (!tab || !dot) return;
    delete dot.dataset.indicatorSignal;
    dot.hidden = !["indicatorRunning", "indicatorReport", "indicatorSignal"]
      .some((key) => dot.dataset[key] === "true");
    tab.classList.remove("has-unread-signal");
    delete tab.dataset.signalTone;
  }

  function markWorkspaceSignal(module, tone) {
    const tab = document.querySelector(`[data-workspace-tab="${module}"]`);
    if (!tab || tab.classList.contains("is-active")) return;
    const dot = workspaceSignalDot(tab);
    dot.dataset.indicatorSignal = "true";
    dot.hidden = false;
    tab.dataset.signalTone = tone;
    tab.classList.add("has-unread-signal");
  }

  function ensureMotionStage() {
    let stage = document.querySelector("#workspaceMotionStage");
    if (stage) return stage;
    stage = document.createElement("div");
    stage.id = "workspaceMotionStage";
    stage.className = "workspace-motion-stage";
    stage.setAttribute("aria-live", "polite");
    stage.setAttribute("aria-atomic", "true");
    document.body.appendChild(stage);
    return stage;
  }

  async function playWorkspaceMotion(event) {
    const type = MOTION_TYPES[event.kind] || MOTION_TYPES.task;
    const targetName = can(event.target || type.target) ? (event.target || type.target) : type.target;
    const target = document.querySelector(`[data-workspace-tab="${targetName}"]`);
    const stage = ensureMotionStage();
    const card = document.createElement("div");
    const tone = event.tone || type.tone;
    card.className = "workspace-motion-card";
    card.dataset.tone = tone;
    card.setAttribute("role", event.kind === "fault" ? "alert" : "status");
    card.innerHTML = `<span class="workspace-motion-icon" aria-hidden="true">${esc(type.icon)}</span><span class="workspace-motion-copy"><small>${esc(event.kicker || type.kicker)}</small><strong>${esc(event.title || "任务已创建")}</strong><em>${esc(event.detail || "已写入系统记录")}</em></span><span class="workspace-motion-tail" aria-hidden="true"></span>`;
    stage.appendChild(card);
    markWorkspaceSignal(targetName, tone);

    if (motionPreference.matches || !card.animate) {
      card.classList.add("is-static");
      await wait(1100);
      card.remove();
      return;
    }

    await card.animate([
      { opacity: 0, transform: "translate3d(18px,-18px,0) scale(.62)", offset: 0 },
      { opacity: 1, transform: "translate3d(-2px,2px,0) scale(1.075)", offset: .42 },
      { opacity: 1, transform: "translate3d(0,0,0) scale(.975)", offset: .7 },
      { opacity: 1, transform: "translate3d(0,0,0) scale(1)", offset: 1 },
    ], { duration: 620, easing: "linear", fill: "forwards" }).finished;
    await wait(event.kind === "fault" ? 1050 : 820);
    card.classList.add("is-compacting");
    await wait(210);

    if (target && !motionPreference.matches) {
      target.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "nearest" });
      await wait(260);
    }
    const cardRect = card.getBoundingClientRect();
    const targetRect = target?.getBoundingClientRect();
    const hasTarget = targetRect && targetRect.width > 0 && targetRect.height > 0;
    const dx = hasTarget ? targetRect.left + targetRect.width / 2 - (cardRect.left + cardRect.width / 2) : 0;
    const dy = hasTarget ? targetRect.top + targetRect.height / 2 - (cardRect.top + cardRect.height / 2) : -34;
    await card.animate([
      { opacity: 1, transform: "translate3d(0,0,0) scale(1)", borderRadius: "22px", offset: 0 },
      { opacity: 1, transform: `translate3d(${dx * .16}px,${dy * .08}px,0) scale(.88)`, borderRadius: "24px", offset: .2 },
      { opacity: .88, transform: `translate3d(${dx * .78}px,${dy * .7}px,0) scale(.34)`, borderRadius: "50%", offset: .72 },
      { opacity: 0, transform: `translate3d(${dx}px,${dy}px,0) scale(.12)`, borderRadius: "50%", offset: 1 },
    ], { duration: 720, easing: "cubic-bezier(.32,.72,0,1)", fill: "forwards" }).finished;
    card.remove();
    if (target) {
      target.classList.remove("is-signal-arrival");
      target.getBoundingClientRect();
      target.classList.add("is-signal-arrival");
      window.setTimeout(() => target.classList.remove("is-signal-arrival"), 760);
    }
  }

  function announceWorkspaceEvent(event = {}) {
    motionState.queue = motionState.queue.catch(() => {}).then(() => playWorkspaceMotion(event)).catch((error) => console.warn("Workspace motion unavailable", error));
    return motionState.queue;
  }

  function faultSignalKey(task) {
    return String(task.incident_id || task.alert_id || task.task_id || task.task_run_id || `${task.kind || "task"}:${task.occurred_at_hkt || task.started_at_hkt || task.error || "unknown"}`);
  }

  function observeFaultSignals(tasks, { baseline = false } = {}) {
    const next = Array.isArray(tasks) ? tasks : [];
    if (baseline || !motionState.faultBaselineReady) {
      motionState.knownFaults = new Set(next.map(faultSignalKey));
      motionState.faultBaselineReady = true;
      return;
    }
    const unseen = next.filter((task) => !motionState.knownFaults.has(faultSignalKey(task)) && faultStatus(task).key === "attention");
    next.forEach((task) => motionState.knownFaults.add(faultSignalKey(task)));
    unseen.slice(0, 3).forEach((task) => {
      const severity = faultSeverity(task);
      announceWorkspaceEvent({
        kind: "fault",
        target: "fault",
        tone: severity.code === "P3" ? "amber" : "red",
        kicker: severity.code ? `${severity.code} ${severity.label}` : "SYSTEM ALERT",
        title: task.title || taskLabel(task.kind),
        detail: faultCause(task),
      });
    });
  }

  window.CMHKMotion = { announce: announceWorkspaceEvent };
  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || event.data?.type !== "cmhk-workspace-motion") return;
    announceWorkspaceEvent(event.data.event || {});
  });

  function applyModulePermissions() {
    allowedModules = MODULES.filter((module) => window.CMHKAuth?.hasModule(permissionModule(module)));
    tabs.forEach((tab) => {
      const allowed = can(tab.dataset.workspaceTab);
      const hiddenFromNavigation = tab.hasAttribute("data-workspace-tab-hidden");
      tab.hidden = !allowed || hiddenFromNavigation;
      tab.disabled = !allowed || hiddenFromNavigation;
      tab.setAttribute("aria-hidden", String(!allowed || hiddenFromNavigation));
    });
    panels.forEach((panel) => {
      const allowed = can(panel.dataset.workspacePanel);
      panel.hidden = true;
      panel.toggleAttribute("inert", !allowed);
    });
    document.querySelectorAll(".workspace-nav-group").forEach((group) => {
      group.hidden = !group.querySelector("[data-workspace-tab]:not([hidden])");
    });
  }

  function hydrateAuthorizedFrame(module) {
    const frame = document.querySelector(`[data-workspace-panel="${module}"] iframe[data-src]`);
    if (frame && can(module)) {
      frame.src = frame.dataset.src;
      frame.removeAttribute("data-src");
    }
  }

  function moduleFromLocation() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const requested = params.get("workspace");
    return allowedModules.includes(requested) ? requested : (allowedModules[0] || "dashboard");
  }

  function animateActivatedPanel(panel) {
    if (!panel || motionPreference.matches) return;
    panel.classList.remove("is-panel-entering");
    void panel.offsetWidth;
    panel.classList.add("is-panel-entering");
    window.setTimeout(() => panel.classList.remove("is-panel-entering"), 220);
  }

  let workspaceLayoutSwitchRevision = 0;

  function synchronizeWorkspaceLayoutScale(active) {
    if (!active) return;
    const revision = ++workspaceLayoutSwitchRevision;
    document.body.classList.add("is-workspace-layout-switching");
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (revision === workspaceLayoutSwitchRevision) document.body.classList.remove("is-workspace-layout-switching");
    }));
  }

  function activateModule(name, { focus = false, updateUrl = true } = {}) {
    const target = allowedModules.includes(name) ? name : (allowedModules[0] || "dashboard");
    const targetIsDashboard = target === "dashboard";
    const wasDashboard = document.body.classList.contains("workspace-dashboard-active");
    const targetIsAi = target === "ai";
    const wasAi = document.body.classList.contains("workspace-ai-active");
    const navLayout = document.querySelector("#workspaceLayout");
    const navButton = document.querySelector("#workspaceNavCollapse");
    const navTransitionStart = wasAi !== targetIsAi ? navButton?.getBoundingClientRect() : null;
    const activePanel = panels.find((panel) => panel.dataset.workspacePanel === target);
    const shouldAnimatePanel = Boolean(activePanel?.hidden);
    state.previewRequest.weekly += 1;
    state.previewRequest.performance += 1;
    tabs.forEach((tab) => {
      const selected = tab.dataset.workspaceTab === target;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    const selectedTab = tabs.find((tab) => tab.dataset.workspaceTab === target);
    if (selectedTab && window.matchMedia("(max-width: 720px)").matches) {
      selectedTab.scrollIntoView({ block: "nearest", inline: "center", behavior: motionPreference.matches ? "auto" : "smooth" });
    }
    clearWorkspaceSignal(target);
    panels.forEach((panel) => { panel.hidden = panel.dataset.workspacePanel !== target; });
    if (shouldAnimatePanel) animateActivatedPanel(activePanel);
    document.querySelectorAll("[data-report-preview].is-maximized").forEach((preview) => preview.classList.remove("is-maximized"));
    document.body.classList.remove("has-maximized-report-preview");
    synchronizeWorkspaceLayoutScale(wasDashboard !== targetIsDashboard);
    document.body.classList.toggle("workspace-dashboard-active", targetIsDashboard);
    document.body.classList.toggle("workspace-ai-active", targetIsAi);
    if (targetIsAi) {
      setWorkspaceNavCollapsed?.(true, { fromRect: navTransitionStart });
    } else if (navTransitionStart && navLayout) {
      setWorkspaceNavCollapsed?.(navLayout.classList.contains("is-nav-collapsed"), { fromRect: navTransitionStart });
    }
    hydrateAuthorizedFrame(target);
    syncEmbeddedVisibility(target);
    renderWorkspaceModule(target);
    if (target === "fault" && state.tasks.length) refreshFaultData();
    if (updateUrl) history.replaceState(null, "", target === "dashboard" ? location.pathname + location.search : `${location.pathname}${location.search}#workspace=${target}`);
    window.dispatchEvent(new CustomEvent("workspace-tab-change", { detail: { tab: target } }));
    window.scrollTo({ top: 0, behavior: motionPreference.matches ? "auto" : "smooth" });
  }

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activateModule(tab.dataset.workspaceTab));
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const availableTabs = tabs.filter((item) => !item.hidden);
      const index = availableTabs.indexOf(tab);
      if (index < 0 || !availableTabs.length) return;
      let next = index;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) next = (index + 1) % availableTabs.length;
      if (["ArrowLeft", "ArrowUp"].includes(event.key)) next = (index - 1 + availableTabs.length) % availableTabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = availableTabs.length - 1;
      activateModule(availableTabs[next].dataset.workspaceTab, { focus: true });
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

  function competitorComparableWindow(data, companyIds, metricKey, years) {
    if (!companyIds.length || !metricKey) return { ok: false, reason: "selection_incomplete", visibleYears: [], sharedVisibleYears: [] };
    const cells = data.cells.filter((cell) => companyIds.includes(cell.company) && cell.metric === metricKey);
    const gaps = (data.gaps || []).filter((gap) => companyIds.includes(gap.company) && gap.metric === metricKey);
    const auditedRows = [...cells, ...gaps];
    const coveredCompanies = new Set(cells.map((cell) => cell.company));
    const units = [...new Set(auditedRows.map((row) => row.unit).filter(Boolean))];
    if (units.length !== 1) return { ok: false, reason: "unit_mismatch", visibleYears: [], sharedVisibleYears: [] };
    const companyYears = companyIds.map((company) => new Set(cells.filter((cell) => cell.company === company).map((cell) => cell.year)));
    const allYears = [...new Set(auditedRows.map((row) => row.year))].sort((a, b) => a - b);
    const commonYears = allYears.filter((year) => companyYears.every((set) => set.has(year)));
    const commonAnchor = allYears.at(-1);
    const visibleYears = years === 99
      ? (allYears.length ? Array.from({ length: allYears.at(-1) - allYears[0] + 1 }, (_item, index) => allYears[0] + index) : [])
      : commonAnchor ? Array.from({ length: years }, (_item, index) => commonAnchor - years + 1 + index) : [];
    const sharedVisibleYears = visibleYears.filter((year) => companyYears.every((set) => set.has(year)));
    const pointsPerCompany = companyYears.map((set) => visibleYears.filter((year) => set.has(year)).length);
    const ok = visibleYears.length > 0 && auditedRows.length > 0;
    return { ok, reason: ok ? "" : "no_audited_rows", unit: units[0], allYears, commonYears, visibleYears, sharedVisibleYears, companyYears, coveredCompanies, pointsPerCompany };
  }

  function competitorHasCompleteMetric(data, companyIds, years, metricKey = "") {
    const rows = [...data.cells, ...(data.gaps || [])];
    const metrics = metricKey ? data.metrics.filter((metric) => metric.key === metricKey) : data.metrics;
    return metrics.some((metric) => {
      const metricRows = rows.filter((row) => companyIds.includes(row.company) && row.metric === metric.key);
      const coveredCompanies = new Set(metricRows.map((row) => row.company));
      const units = new Set(metricRows.map((row) => row.unit).filter(Boolean));
      if (coveredCompanies.size !== companyIds.length || units.size !== 1) return false;
      const windows = years ? [years] : [3, 5, 10, 99];
      return windows.some((windowYears) => {
        const comparison = competitorComparableWindow(data, companyIds, metric.key, windowYears);
        if (!comparison.ok || !comparison.visibleYears.length) return false;
        if (companyIds.length === 1) {
          const audited = new Set(metricRows.map((row) => `${row.company}|${row.year}`));
          return comparison.visibleYears.every((year) => audited.has(`${companyIds[0]}|${year}`));
        }
        const disclosed = new Set(data.cells
          .filter((cell) => companyIds.includes(cell.company)
            && cell.metric === metric.key
            && comparison.visibleYears.includes(cell.year)
            && Number.isFinite(cell.value))
          .map((cell) => `${cell.company}|${cell.year}`));
        return companyIds.every((company) => comparison.visibleYears.every((year) => disclosed.has(`${company}|${year}`)));
      });
    });
  }

  function competitorHasComparablePeer(data, companyId, years, metricKey = "") {
    return data.companies.some((company) => company.id !== companyId
      && competitorHasCompleteMetric(data, [companyId, company.id], years, metricKey));
  }

  function visibleCompetitorIds(data, selectedCompanies, years, metricKey = "") {
    if (!selectedCompanies.length) return new Set(data.companies
      .filter((company) => competitorHasComparablePeer(data, company.id, years, metricKey))
      .map((company) => company.id));
    return new Set(data.companies
      .filter((company) => selectedCompanies.includes(company.id) || competitorHasCompleteMetric(data, [...selectedCompanies, company.id], years, metricKey))
      .map((company) => company.id));
  }

  function competitorSourceLinks(values, label, declaredCount = 0) {
    const urls = [...new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean))];
    if (!urls.length) return "";
    const total = Math.max(Number(declaredCount || 0), urls.length);
    return `<span class="competitor-source-links">${urls.map((url, index) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noreferrer">${esc(label)} ${index + 1}/${total}</a>`).join(" · ")}</span>`;
  }

  function renderCompetitor({ revealedCompanies = [] } = {}) {
    const panel = document.querySelector('[data-workspace-panel="competitor"]');
    const data = state.competitorData || { companies: [], metrics: [], cells: [], gaps: [] };
    const selection = state.competitorSelection;
    const groupKnowledgeLabel = (group) => group === "香港运营商" ? "本地运营商知识库" : "全球重点运营商知识库";
    const groups = data.companies.reduce((map, company) => {
      (map[company.group] ||= []).push(company);
      return map;
    }, {});
    const visibleCompanies = visibleCompetitorIds(data, selection.companies, selection.years, selection.metric);
    const metricUnit = (metric) => {
      const selectedRows = [...data.cells, ...(data.gaps || [])].filter((row) => (!selection.companies.length || selection.companies.includes(row.company)) && row.metric === metric.key);
      const units = [...new Set(selectedRows.map((row) => row.unit).filter(Boolean))];
      return units.length === 1 ? (metric.unitLabels?.[units[0]] || units[0]) : "按所选竞对确定单位";
    };
    const comparableMetrics = selection.companies.length
      ? data.metrics.filter((metric) => competitorHasCompleteMetric(data, selection.companies, selection.years, metric.key))
      : data.metrics;
    if (selection.metric && !comparableMetrics.some((metric) => metric.key === selection.metric)) selection.metric = "";
    const yearOptions = [3, 5, 10, 99];
    const validYears = new Set(selection.companies.length && selection.metric
      ? yearOptions.filter((years) => competitorHasCompleteMetric(data, selection.companies, years, selection.metric))
      : yearOptions);
    panel.innerHTML = `<div class="workspace-module-inner competitor-workbench"><section class="workspace-panel competitor-builder">
      <header class="competitor-builder-head"><strong>竞对数据工作台 <small>${selection.companies.length ? `已选 ${selection.companies.length} 家` : ""}</small></strong><button class="workspace-button" type="button" data-competitor-clear>清空选择</button></header>
      <div class="competitor-steps">
        <fieldset><legend><i>01</i>选择竞对 <small>至少 1 家，最多 6 家</small></legend>${Object.entries(groups).map(([group, companies]) => [group, companies.filter((company) => visibleCompanies.has(company.id))]).filter(([, companies]) => companies.length).map(([group, companies]) => `<div class="competitor-option-group"><span><b>${esc(group)}</b><small>${esc(groupKnowledgeLabel(group))}</small></span><div>${companies.map((company, optionIndex) => `<label class="${revealedCompanies.includes(company.id) ? "is-appearing" : ""}" style="--option-order:${optionIndex}" data-competitor-option="${esc(company.id)}"><input type="checkbox" value="${esc(company.id)}" data-competitor-company ${selection.companies.includes(company.id) ? "checked" : ""} ${selection.companies.length >= 6 && !selection.companies.includes(company.id) ? "disabled" : ""}><b>${esc(company.label)}</b></label>`).join("")}</div></div>`).join("")}</fieldset>
        <fieldset><legend><i>02</i>选择指标 <small>仅显示所选竞对在整个年份窗口均有披露值的指标</small></legend><label class="competitor-select"><span>比较数据</span><select data-competitor-metric><option value="">${comparableMetrics.length ? "请选择指标" : "所选组合暂无完整披露数据"}</option>${comparableMetrics.map((metric) => `<option value="${esc(metric.key)}" ${selection.metric === metric.key ? "selected" : ""}>${esc(metric.label)} · ${esc(metricUnit(metric))}</option>`).join("")}</select></label></fieldset>
        <fieldset><legend><i>03</i>选择年限 <small>仅可选所选竞对逐年数据完整的窗口</small></legend><div class="competitor-year-options">${[3,5,10].map((years) => `<label><input type="radio" name="competitor-years" value="${years}" ${selection.years === years ? "checked" : ""} ${!validYears.has(years) ? "disabled" : ""}><span>最近 ${years} 年窗口</span></label>`).join("")}<label><input type="radio" name="competitor-years" value="99" ${selection.years === 99 ? "checked" : ""} ${!validYears.has(99) ? "disabled" : ""}><span>全部</span></label></div></fieldset>
      </div></section><section class="workspace-panel competitor-result" id="competitorResult"></section></div>`;
    const transitionCompetitorOptions = (nextVisible, revealed = []) => {
      const previouslyVisible = new Set([...panel.querySelectorAll("[data-competitor-option]")].map((item) => item.dataset.competitorOption));
      const appearing = revealed.length ? revealed : [...nextVisible].filter((company) => !previouslyVisible.has(company));
      const disappearing = [...panel.querySelectorAll("[data-competitor-option]")].filter((item) => !nextVisible.has(item.dataset.competitorOption));
      if (!disappearing.length) {
        renderCompetitor({ revealedCompanies: appearing });
        return;
      }
      panel.querySelectorAll("input,select,button").forEach((item) => { item.disabled = true; });
      disappearing.forEach((item) => item.classList.add("is-disappearing"));
      panel.querySelectorAll(".competitor-option-group").forEach((group) => {
        const remaining = [...group.querySelectorAll("[data-competitor-option]")].some((item) => nextVisible.has(item.dataset.competitorOption));
        if (!remaining) group.classList.add("is-disappearing");
      });
      window.setTimeout(() => renderCompetitor({ revealedCompanies: appearing }), motionPreference.matches ? 0 : 430);
    };
    panel.querySelectorAll("[data-competitor-company]").forEach((input) => input.addEventListener("change", () => {
      const selected = [...panel.querySelectorAll("[data-competitor-company]:checked")].map((item) => item.value).slice(0, 6);
      state.competitorSelection.companies = selected;
      const nextVisible = visibleCompetitorIds(data, selected, selection.years, selection.metric);
      transitionCompetitorOptions(nextVisible);
    }));
    panel.querySelector("[data-competitor-metric]")?.addEventListener("change", (event) => {
      state.competitorSelection.metric = event.target.value;
      transitionCompetitorOptions(visibleCompetitorIds(data, selection.companies, selection.years, selection.metric));
    });
    panel.querySelectorAll('[name="competitor-years"]').forEach((input) => input.addEventListener("change", () => {
      state.competitorSelection.years = Number(input.value);
      transitionCompetitorOptions(visibleCompetitorIds(data, selection.companies, selection.years, selection.metric));
    }));
    panel.querySelector("[data-competitor-clear]")?.addEventListener("click", () => {
      const currentlyVisible = new Set([...panel.querySelectorAll("[data-competitor-option]")].map((item) => item.dataset.competitorOption));
      state.competitorSelection = { companies: [], metric: "", years: null };
      renderCompetitor({ revealedCompanies: data.companies.map((company) => company.id).filter((company) => !currentlyVisible.has(company)) });
    });
    renderCompetitorResult();
  }

  function renderCompetitorResult() {
    const host = document.querySelector("#competitorResult");
    if (!host) return;
    const requestId = ++state.competitorInsightRequest;
    state.competitorInsightController?.abort();
    state.competitorInsightController = null;
    window.clearTimeout(state.competitorInsightRetryTimer);
    state.competitorInsightRetryTimer = null;
    state.competitorInsightRetryAttempt = 0;
    const { companies, metric, years } = state.competitorSelection;
    if (companies.length < 1 || !metric || !years) {
      host.innerHTML = `<div class="competitor-empty"><span>01 — 03</span><strong>完成上方选择后查看数据</strong><p>选择至少一家竞对、一个指标和回看年限；单家公司可查看全部已披露数据，两家以上可生成AI竞争洞察。</p></div>`;
      return;
    }
    const data = state.competitorData;
    const metricMeta = data.metrics.find((item) => item.key === metric) || { label: metric, unit: "" };
    const comparison = competitorComparableWindow(data, companies, metric, years);
    const available = data.cells.filter((cell) => companies.includes(cell.company) && cell.metric === metric);
    const auditedGaps = (data.gaps || []).filter((gap) => companies.includes(gap.company) && gap.metric === metric);
    if (comparison.reason === "unit_mismatch") {
      host.innerHTML = `<div class="competitor-empty"><span>数据边界</span><strong>所选组合的计量单位不一致</strong><p>请更换竞对或指标；系统不会把不同币种或单位的数据画在同一张对比图中。</p></div>`;
      return;
    }
    if (!comparison.ok) {
      host.innerHTML = `<div class="competitor-empty"><span>数据边界</span><strong>所选组合尚无审计记录</strong><p>该指标仍保留在数据库中；完成官方来源复核后会显示数值或明确的未披露理由。</p></div>`;
      return;
    }
    const visibleYears = comparison.visibleYears;
    const lookup = new Map(available.map((cell) => [`${cell.company}|${cell.year}`, cell]));
    const gapLookup = new Map(auditedGaps.map((gap) => [`${gap.company}|${gap.year}`, gap]));
    const companyMeta = new Map(data.companies.map((item) => [item.id, item]));
    const companyLabel = (company) => companyMeta.get(company)?.label || company;
    const unitLabel = metricMeta.unitLabels?.[comparison.unit] || comparison.unit;
    const coincidentGroups = competitorCoincidentGroups(companies, visibleYears, lookup);
    const coincidentMembers = new Set(coincidentGroups.flatMap((group) => group.companies));
    const chartLegend = companies.map((company, index) => `<span class="${coincidentMembers.has(company) ? "is-coincident" : ""}"><i style="--series-color:${COMPETITOR_CHART_PALETTE[index % COMPETITOR_CHART_PALETTE.length]}"></i>${esc(companyLabel(company))}${coincidentMembers.has(company) ? "<em>曲线重合</em>" : ""}</span>`).join("");
    const coreSummary = buildCompetitorCoreSummary({ companies, companyLabel, visibleYears, lookup, unit: unitLabel, coincidentGroups });
    const chartKey = `${companies.join("|")}|${metric}|${years}`;
    const chartType = state.competitorChartTypes[chartKey] || competitorDefaultChartType(metricMeta);
    const chartPayload = { companies, companyLabel, visibleYears, lookup, unit: unitLabel, chartType };
    const visibleValueCount = visibleYears.reduce((count, year) => count + companies.filter((company) => Number.isFinite(lookup.get(`${company}|${year}`)?.value)).length, 0);
    const chart = visibleValueCount ? buildCompetitorChart(chartPayload) : `<figure class="competitor-chart-card competitor-chart-no-values"><div><strong>已完成官方来源复核</strong><span>当前窗口没有可直接复用的年度数值，未披露原因与复核链接见下方明细。</span></div></figure>`;
    const rows = visibleYears.map((year) => `<tr><th>${year}</th>${companies.map((company) => {
      const cell = lookup.get(`${company}|${year}`);
      const gap = gapLookup.get(`${company}|${year}`);
      const gapTitle = gap ? [gap.reason, `${gap.reviewedSourceCount || gap.reviewedSources?.length || 0} 份官方材料已复核`].filter(Boolean).join(" · ") : "暂无审计记录";
      const disclosedSources = cell ? [...new Set([...(cell.sources || []), cell.source].filter(Boolean))] : [];
      const sourceAuthorityLabel = ["public_reported_company_statement", "distributed_company_press_release"].includes(cell?.sourceAuthority)
        ? "公共来源转述"
        : cell?.sourceAuthority === "derived_verified_timeline"
          ? "核验时间线"
          : "官方来源";
      const disclosedSourceLinks = competitorSourceLinks(
        disclosedSources,
        sourceAuthorityLabel,
        cell?.distinctSourceDocumentCount || cell?.verificationCount || disclosedSources.length,
      );
      const reviewedSourceLinks = competitorSourceLinks(
        gap?.reviewedSources || [],
        "已复核来源",
        gap?.reviewedSourceCount || gap?.reviewedSources?.length || 0,
      );
      const relatedValue = gap?.relatedPublicValue;
      const relatedEvidence = relatedValue
        ? `<strong class="competitor-related-value">相关口径：${esc(`${competitorComparator(gap.relatedPublicComparator)}${relatedValue} ${gap.relatedPublicUnit || ""}`.trim())}</strong><small>${esc(gap.relatedPublicNote || gap.relatedPublicMetric || "非目标年度同口径值")}</small>`
        : "";
      const gapLabel = gap?.searchStatus === "not_applicable_precommercial"
        ? "— 商用前不适用"
        : gap?.searchStatus === "not_applicable_business_scope"
          ? "— 业务不适用"
          : gap?.searchStatus === "scope_not_comparable"
            ? "— 口径不可比"
        : gap?.searchStatus === "targeted_public_search_not_recorded"
          ? "— 尚未记录定向检索"
          : gap
            ? "— 未披露"
            : "— 尚无审计记录";
      return `<td title="${esc(cell ? [cell.period, cell.periodEnd, cell.scope, cell.basis, cell.usagePolicy, cell.note].filter(Boolean).join(" · ") : gapTitle)}">${cell ? `<strong>${esc(`${competitorComparator(cell.comparator)}${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(cell.value)}`)}</strong><small>${esc([cell.period, cell.periodEnd, sourceAuthorityLabel].filter(Boolean).join(" · "))}</small>${disclosedSourceLinks}` : `<span class="competitor-missing">${gapLabel}</span>${relatedEvidence}<small>${esc(gap?.reason || "尚无审计记录")}</small>${reviewedSourceLinks}`}</td>`;
    }).join("")}</tr>`).join("");
    host.innerHTML = `<header class="workspace-panel-header competitor-result-header"><div><h2>${esc(metricMeta.label)}</h2><span>${companies.length} 家 · ${esc(unitLabel)} · ${visibleYears[0] || "—"}—${visibleYears.at(-1) || "—"}</span></div><div class="competitor-chart-legend" aria-label="竞对图例">${chartLegend}</div></header>
      <div class="competitor-core-summary is-loading" role="status" aria-live="polite" aria-busy="true" data-competitor-core-summary-shell data-fallback="${esc(coreSummary)}"><strong data-competitor-core-summary><i aria-hidden="true"><u></u><u></u><u></u></i></strong></div>
      <div class="competitor-result-overview">
      ${chart}
      <section class="competitor-insight" id="competitorInsight" role="status" aria-live="polite" aria-busy="false">
        <header class="competitor-insight-header">
          <div class="competitor-insight-identity"><i data-competitor-insight-icon><svg viewBox="0 0 32 32" aria-hidden="true" focusable="false"><path d="M13 2.5c1.05 5.52 3.48 7.95 9 9-5.52 1.05-7.95 3.48-9 9-1.05-5.52-3.48-7.95-9-9 5.52-1.05 7.95-3.48 9-9Z"/><path d="M24.5 2c.45 2.35 1.65 3.55 4 4-2.35.45-3.55 1.65-4 4-.45-2.35-1.65-3.55-4-4 2.35-.45 3.55-1.65 4-4Z"/></svg></i><div><b data-competitor-insight-title>AI 竞争洞察</b><small data-competitor-insight-status>正在连接 AI</small></div></div>
          <span class="competitor-insight-badge" data-competitor-insight-badge>CONNECTING</span>
        </header>
        <div class="competitor-insight-body">
          <div class="competitor-insight-loading" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
          <ol class="competitor-insight-list" data-competitor-insight-list></ol>
        </div>
      </section></div>
      <details class="competitor-data-details"><summary>查看数据明细、缺口理由与官方来源 <span>${visibleYears.length} 个审计年度</span></summary><div class="workspace-table-wrap"><table class="workspace-table competitor-matrix"><thead><tr><th>披露年度</th>${companies.map((company) => `<th>${esc(companyLabel(company))}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
    bindCompetitorChartTooltip(host);
    bindCompetitorChartTypeToggle(host, chartPayload, chartKey);
    if (companies.length >= 2 && visibleValueCount) {
      requestCompetitorInsight({ companies, metric: { key: metricMeta.key, label: metricMeta.label }, years: visibleYears, evidenceVersion: data.evidenceVersion }, requestId);
    } else {
      const insight = host.querySelector("#competitorInsight");
      if (insight) insight.innerHTML = `<header class="competitor-insight-header"><div class="competitor-insight-identity"><strong>数据说明</strong></div></header><div class="competitor-insight-body"><ol class="competitor-insight-list"><li>${visibleValueCount ? "当前为单家公司数据查看；再选择一家竞对后，可生成AI竞争洞察。" : "当前窗口均为确认未披露；小竞AI可继续读取每年缺口原因与已复核官方来源。"}</li></ol></div>`;
    }
  }

  function competitorComparator(value) {
    return ({ ">=": "≥", "<=": "≤", "~": "≈", "approx": "≈" })[String(value || "").toLowerCase()] || (value === "=" ? "" : String(value || ""));
  }

  function competitorCoincidentGroups(companies, visibleYears, lookup) {
    const signatures = new Map();
    companies.forEach((company) => {
      const cells = visibleYears.map((year) => lookup.get(`${company}|${year}`));
      if (!cells.length || cells.some((cell) => !Number.isFinite(cell?.value))) return;
      const signature = cells.map((cell) => `${cell.comparator || "="}:${cell.value}`).join("|");
      const group = signatures.get(signature) || [];
      group.push(company);
      signatures.set(signature, group);
    });
    return [...signatures.values()].filter((group) => group.length > 1).map((group) => ({
      companies: group,
      sharedScope: group.every((company) => visibleYears.some((year) => /shared|共建|共享/i.test(String(lookup.get(`${company}|${year}`)?.scope || "")))),
    }));
  }

  function buildCompetitorCoreSummary({ companies, companyLabel, visibleYears, lookup, unit, coincidentGroups = [] }) {
    const lastYear = visibleYears.at(-1);
    const latest = companies.map((company) => ({ company, cell: lookup.get(`${company}|${lastYear}`) })).filter((item) => Number.isFinite(item.cell?.value));
    const sharedOverlap = coincidentGroups.find((group) => group.sharedScope);
    if (sharedOverlap) {
      const sharedLabels = sharedOverlap.companies.map(companyLabel).join("与");
      const others = latest.filter((item) => !sharedOverlap.companies.includes(item.company)).sort((a, b) => b.cell.value - a.cell.value);
      const leaderCopy = others.length ? `${companyLabel(others[0].company)}保持独立建设规模领先；` : "";
      return `${leaderCopy}${sharedLabels}共用同一张网络，双方的竞争焦点不在基站数量差异，而在共享网络的运营效率和业务转化能力。`;
    }
    const ranked = [...latest].sort((a, b) => b.cell.value - a.cell.value);
    if (!ranked.length) return "当前窗口暂无可用的共同披露值。";
    const leader = ranked[0];
    const overlap = coincidentGroups.length ? `；${coincidentGroups[0].companies.map(companyLabel).join("与")}暂未形成可区分的位置` : "";
    return `${companyLabel(leader.company)}当前处于领先位置，其他公司能否缩小差距，将决定后续竞争格局${overlap}。`;
  }

  function buildCompetitorFallbackInsight({ companies, companyLabel, visibleYears, lookup, unit }) {
    const format = (value) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
    const cells = companies.flatMap((company) => visibleYears.map((year) => lookup.get(`${company}|${year}`)).filter(Boolean));
    const hasSharedScope = cells.some((cell) => /shared|共建|共享/i.test(String(cell.scope || "")));
    const hasScopeBreak = cells.some((cell) => /scope change|口径变化|unsafe|not comparable|不可比|restated/i.test([cell.scope, cell.basis, cell.note].filter(Boolean).join(" ")));
    const comparableYears = visibleYears.filter((year) => companies.every((company) => Number.isFinite(lookup.get(`${company}|${year}`)?.value)));
    const firstYear = comparableYears[0];
    const lastYear = comparableYears.at(-1);
    const valuesAt = (year) => companies.map((company) => ({ company, label: companyLabel(company), cell: lookup.get(`${company}|${year}`) })).filter((item) => Number.isFinite(item.cell?.value));
    const firstValues = valuesAt(firstYear);
    const lastValues = valuesAt(lastYear);
    const movements = companies.map((company) => {
      const first = lookup.get(`${company}|${firstYear}`);
      const last = lookup.get(`${company}|${lastYear}`);
      const change = last.value - first.value;
      return { company, change, direction: Math.abs(change) < 1e-9 ? "稳定" : change > 0 ? "上升" : "下降" };
    });
    const spread = (values) => values.length > 1 ? Math.max(...values.map((item) => item.cell.value)) - Math.min(...values.map((item) => item.cell.value)) : 0;
    const firstSpread = spread(firstValues);
    const lastSpread = spread(lastValues);
    const hasBounds = [...firstValues, ...lastValues].some((item) => item.cell.comparator && item.cell.comparator !== "=");
    const endpointComparators = [...firstValues, ...lastValues].map((item) => String(item.cell.comparator || "="));
    const hasDirectionalBounds = endpointComparators.some((value) => /[<>]/.test(value));
    const hasApproxValues = endpointComparators.some((value) => ["~", "approx", "≈"].includes(value.toLowerCase()));
    const spreadDelta = lastSpread - firstSpread;
    const tolerance = Math.max(Math.abs(firstSpread), Math.abs(lastSpread), 1) * .005;
    const relation = hasScopeBreak ? "口径变化" : hasSharedScope ? "共享口径" : hasBounds ? "边界值" : Math.abs(spreadDelta) <= tolerance ? "绝对差距稳定" : spreadDelta < 0 ? "绝对差距收窄" : "绝对差距扩大";
    const directions = [...new Set(movements.map((item) => item.direction))];
    const commonDirection = directions.length === 1 ? directions[0] : "";
    const directionalComparators = endpointComparators.filter((value) => /[<>]/.test(value));
    const boundLabel = directionalComparators.length && directionalComparators.every((value) => value.includes(">"))
      ? directionalComparators.length === endpointComparators.length ? "披露下限" : "含披露下限"
      : directionalComparators.length && directionalComparators.every((value) => value.includes("<"))
        ? directionalComparators.length === endpointComparators.length ? "披露上限" : "含披露上限"
        : "披露边界值";
    const directionSummary = hasDirectionalBounds
      ? commonDirection ? `${boundLabel}较${firstYear}年均${commonDirection}` : `${boundLabel}变化方向不同`
      : hasApproxValues
        ? commonDirection ? `约数显示较${firstYear}年均${commonDirection}` : `约数显示走势出现分化`
        : commonDirection
          ? commonDirection === "稳定" ? `较${firstYear}年均保持稳定` : `较${firstYear}年均${commonDirection}`
          : `较${firstYear}年走势出现分化`;
    const sharedSameValue = hasSharedScope && lastValues.every((item) => item.cell.value === lastValues[0]?.cell.value && item.cell.comparator === lastValues[0]?.cell.comparator);
    const latestComparison = sharedSameValue
      ? `${lastYear}年双方披露同一共建共享口径${competitorComparator(lastValues[0].cell.comparator)}${format(lastValues[0].cell.value)}${unit}`
      : `${lastYear}年${lastValues.map((item) => `${item.label}为${competitorComparator(item.cell.comparator)}${format(item.cell.value)}${unit}`).join("、")}`;
    const gapFinding = hasScopeBreak
      ? "区间内存在口径变化，不计算趋势差距"
      : hasSharedScope
      ? "该指标涉及共建共享口径，数值不可相加"
      : hasBounds
        ? "部分数值为边界披露，不对差距作精确计算"
        : `所选公司最大最小值的绝对差较${firstYear}年${relation.replace("绝对差距", "")}`;
    const caveats = ["披露期或财年结束日可能不同，仅比较共同披露年度，不推算缺失值。"];
    if (hasSharedScope) caveats.push("存在共建共享口径，相关数值不可相加。");
    if (hasScopeBreak) caveats.push("区间内存在口径变化，禁止跨口径计算趋势或差距。");
    const isPercent = unit === "%" || /百分/.test(unit);
    const headline = hasScopeBreak
      ? `${firstYear}—${lastYear}共同披露期内存在口径变化；${latestComparison}，不作跨口径趋势或差距计算。`
      : `${firstYear}—${lastYear}共同披露期内，所选公司${directionSummary}；${latestComparison}，${gapFinding}。`;
    return {
      headline,
      period: `${firstYear}—${lastYear}`,
      gap: hasScopeBreak || hasSharedScope || hasBounds ? `${lastYear} · 不作精算` : `${lastYear} · ${format(lastSpread)}${isPercent ? "个百分点" : unit}`,
      relation,
      caveat: caveats.join(" "),
      insights: [
        `竞争格局｜${headline}`,
        `公司定位｜${movements.map((item) => `${companyLabel(item.company)}较${firstYear}年${item.direction}`).join("；")}；${latestComparison}。`,
        `业务含义｜${gapFinding}。${caveats.join(" ")}`,
      ],
    };
  }

  function competitorDefaultChartType(metric) {
    const text = `${metric?.label || ""} ${metric?.unit || ""} ${(metric?.units || []).join(" ")}`;
    return /率|ARPU|ARPA|ARPH|DOU|增长|覆盖|percent|percentage/i.test(text) ? "line" : "bar";
  }

  function competitorChartPointItems({ companies, companyLabel, lookup, year, cell, unit, format }) {
    return companies.map((peer) => ({ company: peer, cell: lookup.get(`${peer}|${year}`) }))
      .filter((item) => Number.isFinite(item.cell?.value) && item.cell.value === cell.value && String(item.cell.comparator || "=") === String(cell.comparator || "="))
      .map((item) => ({
        company: companyLabel(item.company),
        period: item.cell.period || `${year}年`,
        value: `${competitorComparator(item.cell.comparator)}${format(item.cell.value)} ${unit}`,
        shared: /shared|共建|共享/i.test(String(item.cell.scope || "")),
      }));
  }

  function competitorChartToggle(chartType) {
    const types = ["bar", "line", "combo"];
    const currentIndex = Math.max(0, types.indexOf(chartType));
    const nextType = types[(currentIndex + 1) % types.length];
    const labels = { line: "切换为折线图", bar: "切换为柱状图", combo: "切换为柱线组合图" };
    const icons = {
      line: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="m3 14 4-4 3 2 6-7"/><circle cx="3" cy="14" r="1"/><circle cx="7" cy="10" r="1"/><circle cx="10" cy="12" r="1"/><circle cx="16" cy="5" r="1"/></svg>',
      bar: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 16.5V10h3v6.5m2-9h3v9m2-12h3v12M2.5 16.5h15"/></svg>',
      combo: '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M3.5 16.5v-5h3v5m2-8h3v8m2-11h3v11M2.5 16.5h15"/><path d="m3.5 10 4-3 3 2 6-6"/><circle cx="3.5" cy="10" r=".75"/><circle cx="7.5" cy="7" r=".75"/><circle cx="10.5" cy="9" r=".75"/><circle cx="16.5" cy="3" r=".75"/></svg>',
    };
    return `<button class="competitor-chart-type-toggle" type="button" data-competitor-chart-toggle data-current-chart-type="${chartType}" data-next-chart-type="${nextType}" aria-label="${labels[nextType]}" title="${labels[nextType]}">${icons[nextType]}</button>`;
  }

  function buildCompetitorChart({ companies, companyLabel, visibleYears, lookup, unit, chartType = "line" }) {
    if (chartType === "bar" || chartType === "combo") return buildCompetitorBarChart({ companies, companyLabel, visibleYears, lookup, unit, chartType });
    const width = 960;
    const height = 390;
    const margin = { top: 26, right: 24, bottom: 42, left: 66 };
    const values = companies.flatMap((company) => visibleYears.map((year) => lookup.get(`${company}|${year}`)?.value).filter((value) => Number.isFinite(value)));
    let min = Math.min(...values);
    let max = Math.max(...values);
    if (min === max) { const offset = Math.abs(min || 1) * .12; min -= offset; max += offset; }
    const pad = (max - min) * .12;
    min -= pad;
    max += pad;
    const x = (year) => visibleYears.length === 1 ? (margin.left + width - margin.right) / 2 : margin.left + (visibleYears.indexOf(year) / (visibleYears.length - 1)) * (width - margin.left - margin.right);
    const y = (value) => margin.top + ((max - value) / (max - min)) * (height - margin.top - margin.bottom);
    const format = (value) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
    const ticks = Array.from({ length: 5 }, (_, index) => max - ((max - min) * index / 4));
    const grid = ticks.map((value) => `<g class="competitor-chart-grid"><line x1="${margin.left}" x2="${width - margin.right}" y1="${y(value).toFixed(1)}" y2="${y(value).toFixed(1)}"></line><text x="${margin.left - 12}" y="${(y(value) + 4).toFixed(1)}">${esc(format(value))}</text></g>`).join("");
    const years = visibleYears.map((year) => `<g class="competitor-chart-year"><line x1="${x(year).toFixed(1)}" x2="${x(year).toFixed(1)}" y1="${height - margin.bottom}" y2="${height - margin.bottom + 5}"></line><text x="${x(year).toFixed(1)}" y="${height - 18}">${esc(year)}</text></g>`).join("");
    const series = companies.map((company, index) => {
      const color = COMPETITOR_CHART_PALETTE[index % COMPETITOR_CHART_PALETTE.length];
      const points = visibleYears.map((year) => ({ year, cell: lookup.get(`${company}|${year}`) })).filter((item) => Number.isFinite(item.cell?.value));
      const segments = [];
      let active = [];
      visibleYears.forEach((year) => {
        const cell = lookup.get(`${company}|${year}`);
        if (Number.isFinite(cell?.value)) active.push({ year, cell });
        else if (active.length) { segments.push(active); active = []; }
      });
      if (active.length) segments.push(active);
      const paths = segments.filter((segment) => segment.length > 1).map((segment) => `<path d="${segment.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${x(point.year).toFixed(1)},${y(point.cell.value).toFixed(1)}`).join(" ")}" style="--series-color:${color};--series-dash:${["none", "7 4", "2 4", "10 4 2 4", "12 5", "5 3"][index]}"></path>`).join("");
      const dots = points.map(({ year, cell }) => {
        const period = cell.period || `${year}年`;
        const value = `${competitorComparator(cell.comparator)}${format(cell.value)} ${unit}`;
        const coincidentItems = competitorChartPointItems({ companies, companyLabel, lookup, year, cell, unit, format });
        const description = coincidentItems.map((item) => `${item.company} · ${item.period} · ${item.value}`).join("；");
        const pointKey = `${year}|${cell.comparator || "="}|${cell.value}`;
        return `<g class="competitor-chart-point ${cell.comparator && cell.comparator !== "=" ? "is-bound" : ""}" tabindex="0" role="img" aria-label="${esc(description)}" data-chart-point-key="${esc(pointKey)}" data-chart-items="${esc(JSON.stringify(coincidentItems))}"><circle class="competitor-chart-point-hit" cx="${x(year).toFixed(1)}" cy="${y(cell.value).toFixed(1)}" r="13"></circle><circle class="competitor-chart-point-marker" cx="${x(year).toFixed(1)}" cy="${y(cell.value).toFixed(1)}" r="4.5" style="--series-color:${color}"></circle></g>`;
      }).join("");
      return `<g class="competitor-chart-series">${paths}${dots}</g>`;
    }).join("");
    return `<figure class="competitor-chart-card" data-chart-type="line">${competitorChartToggle("line")}<div class="competitor-chart-scroll"><svg class="competitor-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(`所选 ${companies.length} 家竞对在 ${visibleYears[0]} 至 ${visibleYears.at(-1)} 年的趋势对比图`)}">${grid}${years}${series}</svg></div><div class="competitor-chart-tooltip" role="tooltip" hidden></div><p>注：将鼠标移到数据点可查看具体数值；重合点会同时显示全部公司；财年与自然年口径差异请以数据明细中的官方来源为准。</p></figure>`;
  }

  function buildCompetitorBarChart({ companies, companyLabel, visibleYears, lookup, unit, chartType = "bar" }) {
    const width = 960;
    const height = 390;
    const margin = { top: 26, right: 24, bottom: 42, left: 66 };
    const values = companies.flatMap((company) => visibleYears.map((year) => lookup.get(`${company}|${year}`)?.value).filter((value) => Number.isFinite(value)));
    let min = Math.min(0, ...values);
    let max = Math.max(0, ...values);
    if (min === max) max = Math.abs(max || 1);
    const pad = (max - min) * .1;
    if (min < 0) min -= pad;
    max += pad;
    const plotWidth = width - margin.left - margin.right;
    const groupStep = plotWidth / visibleYears.length;
    const barGap = 2;
    const groupWidth = Math.min(groupStep * .72, 58);
    const barWidth = Math.max(3, (groupWidth - barGap * (companies.length - 1)) / companies.length);
    const barTotalWidth = barWidth * companies.length + barGap * (companies.length - 1);
    const x = (year, companyIndex) => margin.left + (visibleYears.indexOf(year) + .5) * groupStep - barTotalWidth / 2 + companyIndex * (barWidth + barGap);
    const y = (value) => margin.top + ((max - value) / (max - min)) * (height - margin.top - margin.bottom);
    const baseline = y(0);
    const format = (value) => new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(value);
    const ticks = Array.from({ length: 5 }, (_, index) => max - ((max - min) * index / 4));
    const grid = ticks.map((value) => `<g class="competitor-chart-grid"><line x1="${margin.left}" x2="${width - margin.right}" y1="${y(value).toFixed(1)}" y2="${y(value).toFixed(1)}"></line><text x="${margin.left - 12}" y="${(y(value) + 4).toFixed(1)}">${esc(format(value))}</text></g>`).join("");
    const axis = `<line class="competitor-chart-zero" x1="${margin.left}" x2="${width - margin.right}" y1="${baseline.toFixed(1)}" y2="${baseline.toFixed(1)}"></line>`;
    const years = visibleYears.map((year) => { const center = margin.left + (visibleYears.indexOf(year) + .5) * groupStep; return `<g class="competitor-chart-year"><line x1="${center.toFixed(1)}" x2="${center.toFixed(1)}" y1="${height - margin.bottom}" y2="${height - margin.bottom + 5}"></line><text x="${center.toFixed(1)}" y="${height - 18}">${esc(year)}</text></g>`; }).join("");
    const bars = companies.map((company, companyIndex) => {
      const color = COMPETITOR_CHART_PALETTE[companyIndex % COMPETITOR_CHART_PALETTE.length];
      return visibleYears.map((year) => {
        const cell = lookup.get(`${company}|${year}`);
        if (!Number.isFinite(cell?.value)) return "";
        const valueY = y(cell.value);
        const top = Math.min(valueY, baseline);
        const barHeight = Math.max(1, Math.abs(baseline - valueY));
        const coincidentItems = competitorChartPointItems({ companies, companyLabel, lookup, year, cell, unit, format });
        const description = coincidentItems.map((item) => `${item.company} · ${item.period} · ${item.value}`).join("；");
        const pointKey = `${year}|${cell.comparator || "="}|${cell.value}`;
        return `<rect class="competitor-chart-point competitor-chart-bar ${cell.comparator && cell.comparator !== "=" ? "is-bound" : ""}" tabindex="0" role="img" aria-label="${esc(description)}" data-chart-point-key="${esc(pointKey)}" data-chart-items="${esc(JSON.stringify(coincidentItems))}" x="${x(year, companyIndex).toFixed(1)}" y="${top.toFixed(1)}" width="${barWidth.toFixed(1)}" height="${barHeight.toFixed(1)}" rx="1.5" style="--series-color:${color}"></rect>`;
      }).join("");
    }).join("");
    const comboLines = chartType === "combo" ? companies.map((company, companyIndex) => {
      const color = COMPETITOR_CHART_PALETTE[companyIndex % COMPETITOR_CHART_PALETTE.length];
      const segments = [];
      let active = [];
      visibleYears.forEach((year) => {
        const cell = lookup.get(`${company}|${year}`);
        if (Number.isFinite(cell?.value)) active.push({ year, cell });
        else if (active.length) { segments.push(active); active = []; }
      });
      if (active.length) segments.push(active);
      const centerX = (year) => x(year, companyIndex) + barWidth / 2;
      const paths = segments.filter((segment) => segment.length > 1).map((segment) => `<path d="${segment.map((point, pointIndex) => `${pointIndex ? "L" : "M"}${centerX(point.year).toFixed(1)},${y(point.cell.value).toFixed(1)}`).join(" ")}" style="--series-color:${color};--series-dash:${["none", "7 4", "2 4", "10 4 2 4", "12 5", "5 3"][companyIndex]}"></path>`).join("");
      const markers = segments.flat().map((point) => `<circle cx="${centerX(point.year).toFixed(1)}" cy="${y(point.cell.value).toFixed(1)}" r="3" style="--series-color:${color}"></circle>`).join("");
      return `<g class="competitor-chart-combo-series">${paths}${markers}</g>`;
    }).join("") : "";
    const isCombo = chartType === "combo";
    const chartLabel = isCombo ? "柱线组合对比图" : "年度分组对比图";
    const interactionTarget = isCombo ? "柱形或折线节点" : "柱形";
    return `<figure class="competitor-chart-card" data-chart-type="${chartType}">${competitorChartToggle(chartType)}<div class="competitor-chart-scroll"><svg class="competitor-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(`所选 ${companies.length} 家竞对在 ${visibleYears[0]} 至 ${visibleYears.at(-1)} 年的${chartLabel}`)}">${grid}${axis}${years}<g class="competitor-chart-bars">${bars}</g>${comboLines}</svg></div><div class="competitor-chart-tooltip" role="tooltip" hidden></div><p>注：将鼠标移到${interactionTarget}可查看具体数值；重合值会同时显示全部公司；财年与自然年口径差异请以数据明细中的官方来源为准。</p></figure>`;
  }

  function bindCompetitorChartTypeToggle(scope, payload, chartKey) {
    const button = scope.querySelector("[data-competitor-chart-toggle]");
    if (!button) return;
    button.addEventListener("click", () => {
      const chartType = ["line", "bar", "combo"].includes(button.dataset.nextChartType) ? button.dataset.nextChartType : "line";
      state.competitorChartTypes[chartKey] = chartType;
      const current = scope.querySelector(".competitor-chart-card");
      if (!current) return;
      const template = document.createElement("template");
      template.innerHTML = buildCompetitorChart({ ...payload, chartType });
      current.replaceWith(template.content.firstElementChild);
      bindCompetitorChartTooltip(scope);
      bindCompetitorChartTypeToggle(scope, { ...payload, chartType }, chartKey);
    });
  }

  function bindCompetitorChartTooltip(scope) {
    const card = scope.querySelector(".competitor-chart-card");
    const tooltip = card?.querySelector(".competitor-chart-tooltip");
    if (!card || !tooltip) return;
    const position = (point, clientX = null) => {
      const cardRect = card.getBoundingClientRect();
      const pointRect = point.getBoundingClientRect();
      const rawLeft = clientX == null ? pointRect.left + pointRect.width / 2 - cardRect.left : clientX - cardRect.left;
      const halfWidth = Math.max(76, Math.min(tooltip.offsetWidth, cardRect.width - 12) / 2);
      tooltip.style.left = `${Math.min(cardRect.width - halfWidth - 6, Math.max(halfWidth + 6, rawLeft))}px`;
      const pointTop = pointRect.top - cardRect.top;
      const showBelow = pointTop < tooltip.offsetHeight + 18;
      tooltip.classList.toggle("is-below", showBelow);
      tooltip.style.top = `${showBelow ? pointRect.bottom - cardRect.top + 10 : pointTop - 10}px`;
    };
    const show = (point, event = null) => {
      let items = [];
      try { items = JSON.parse(point.dataset.chartItems || "[]"); } catch (_error) { items = []; }
      const header = document.createElement("span");
      header.className = "competitor-chart-tooltip-period";
      header.textContent = `${items.length > 1 ? "重合数据点 · " : ""}${items[0]?.period || ""}`;
      const list = document.createElement("div");
      list.className = "competitor-chart-tooltip-list";
      items.forEach((item) => {
        const row = document.createElement("div");
        const label = document.createElement("strong");
        const itemValue = document.createElement("b");
        label.textContent = item.company || "";
        itemValue.textContent = item.value || "";
        row.append(label, itemValue);
        list.append(row);
      });
      const children = [header, list];
      if (items.length > 1 && items.every((item) => item.shared)) {
        const note = document.createElement("small");
        note.textContent = "共建共享网络口径，数值不可相加";
        children.push(note);
      }
      tooltip.replaceChildren(...children);
      tooltip.hidden = false;
      position(point, event?.clientX ?? null);
      card.querySelectorAll(".competitor-chart-point.is-active").forEach((item) => item.classList.remove("is-active"));
      card.querySelectorAll(".competitor-chart-point").forEach((item) => {
        if (item.dataset.chartPointKey === point.dataset.chartPointKey) item.classList.add("is-active");
      });
    };
    const hide = () => {
      tooltip.hidden = true;
      card.querySelectorAll(".competitor-chart-point.is-active").forEach((item) => item.classList.remove("is-active"));
    };
    card.querySelectorAll(".competitor-chart-point").forEach((point) => {
      point.addEventListener("pointerenter", (event) => show(point, event));
      point.addEventListener("pointermove", (event) => position(point, event.clientX));
      point.addEventListener("pointerleave", () => hide(point));
      point.addEventListener("focus", () => show(point));
      point.addEventListener("blur", () => hide(point));
    });
  }

  function settleCompetitorInsight(card, { mode, strategicIndicator = "", strategicHighlights = [], insight = "", insights = [], status = "" }) {
    if (!card) return;
    const isAi = mode === "ai";
    card.classList.remove("is-loading", "is-streaming");
    card.classList.toggle("is-ai", isAi);
    card.setAttribute("aria-busy", "false");
    card.querySelector("[data-competitor-insight-title]").textContent = "AI 竞争洞察";
    setCompetitorInsightStatus(card, status || (isAi ? "" : "AI暂未完成"));
    card.querySelector("[data-competitor-insight-badge]").textContent = isAi ? "COMPETITIVE INSIGHT" : "RETRY";
    const sourceItems = Array.isArray(insights) && insights.length ? insights : parseCompetitorInsightItems(insight);
    const items = sourceItems.map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3);
    syncCompetitorInsightRows(card, items);
    const parsedSignal = parseCompetitorStrategicSignal(insight);
    const generatedIndicator = String(strategicIndicator || parsedSignal.text).trim();
    const generatedHighlights = Array.isArray(strategicHighlights) && strategicHighlights.length ? strategicHighlights : parsedSignal.highlights;
    settleCompetitorStrategicIndicator(generatedIndicator, { fallback: !generatedIndicator, highlights: generatedHighlights });
  }

  function competitorStrategicSummaryElements() {
    const shell = document.querySelector("[data-competitor-core-summary-shell]");
    return { shell, copy: shell?.querySelector("[data-competitor-core-summary]") };
  }

  function beginCompetitorStrategicIndicator() {
    const { shell, copy } = competitorStrategicSummaryElements();
    if (!shell || !copy) return;
    shell.classList.remove("is-streaming", "is-ready", "is-fallback");
    shell.classList.add("is-loading");
    shell.setAttribute("aria-busy", "true");
    copy.innerHTML = '<i aria-hidden="true"><u></u><u></u><u></u></i>';
  }

  function renderCompetitorStrategicIndicatorCopy(copy, text, highlights = []) {
    const value = String(text || "").trim().replace(/[。．.]+$/, "");
    const phrases = [...new Set((Array.isArray(highlights) ? highlights : []).map((item) => String(item || "").trim()).filter((item) => item.length >= 2 && value.includes(item)))].slice(0, 3);
    if (!phrases.length) {
      copy.textContent = value;
      return;
    }
    const pattern = new RegExp(`(${phrases.map((item) => item.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "g");
    const phraseSet = new Set(phrases);
    const fragment = document.createDocumentFragment();
    value.split(pattern).filter(Boolean).forEach((part) => {
      if (!phraseSet.has(part)) {
        fragment.append(document.createTextNode(part));
        return;
      }
      const mark = document.createElement("mark");
      mark.textContent = part;
      fragment.append(mark);
    });
    copy.replaceChildren(fragment);
  }

  function streamCompetitorStrategicIndicator(text, highlights = []) {
    const { shell, copy } = competitorStrategicSummaryElements();
    if (!shell || !copy || !text) return;
    shell.classList.remove("is-loading", "is-ready", "is-fallback");
    shell.classList.add("is-streaming");
    shell.setAttribute("aria-busy", "true");
    renderCompetitorStrategicIndicatorCopy(copy, text, highlights);
  }

  function settleCompetitorStrategicIndicator(text, { fallback = false, highlights = [] } = {}) {
    const { shell, copy } = competitorStrategicSummaryElements();
    if (!shell || !copy) return;
    const finalText = String(text || shell.dataset.fallback || "当前暂未形成可用战略判断。").trim();
    shell.classList.remove("is-loading", "is-streaming");
    shell.classList.add("is-ready");
    shell.classList.toggle("is-fallback", fallback);
    shell.setAttribute("aria-busy", "false");
    renderCompetitorStrategicIndicatorCopy(copy, finalText, fallback ? [] : highlights);
  }

  function syncCompetitorInsightRows(card, items, { streaming = false } = {}) {
    const list = card?.querySelector("[data-competitor-insight-list]");
    if (!list) return;
    const body = card.querySelector(".competitor-insight-body");
    const shouldFollow = body && body.scrollHeight - body.scrollTop - body.clientHeight <= 24;
    const labels = ["竞争格局", "公司定位", "业务含义"];
    items.slice(0, 3).forEach((item, index) => {
      let li = list.children[index];
      if (!li) {
        li = document.createElement("li");
        const label = document.createElement("b");
        const copy = document.createElement("span");
        li.append(label, copy);
        list.append(li);
      }
      const label = li.querySelector("b");
      const copy = li.querySelector("span");
      const nextCopy = String(item || "").replace(/^(竞争格局|公司分化|公司定位|业务含义|数据格局|共同年度|解读边界)[：|｜]\s*/, "");
      if (label.textContent !== labels[index]) label.textContent = labels[index];
      const currentCopy = copy.textContent;
      const isContinuousDraft = !currentCopy || nextCopy.startsWith(currentCopy);
      if (copy.textContent !== nextCopy && (!streaming || isContinuousDraft)) copy.textContent = nextCopy;
    });
    if (!streaming) {
      while (list.children.length > items.length) list.lastElementChild.remove();
    }
    if (body && shouldFollow) {
      window.requestAnimationFrame(() => { body.scrollTop = body.scrollHeight; });
    }
  }

  function parseCompetitorInsightItems(content) {
    const text = String(content || "").replace(/^```(?:json|text|markdown)?\s*|\s*```$/gi, "").trim();
    if (!text) return [];
    const labelled = new Map();
    const candidates = [];
    let activeLabelIndex = null;
    text.split(/\n+/).forEach((rawLine) => {
      const line = rawLine
        .replace(/^\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)、]\s*)/, "")
        .replace(/^\*\*(.*?)\**$/, "$1")
        .trim();
      if (!line || /^\|?\s*:?-{2,}[-| :]*$/.test(line)) return;
      if (/^(战略指标|核心结论)[：|｜]/.test(line)) {
        activeLabelIndex = null;
        return;
      }
      const match = line.match(/^(?:一|二|三)?[、.\s]*(竞争格局|公司分化|公司定位|业务含义)[：|｜]\s*(.+)$/);
      if (match) {
        const index = match[1] === "竞争格局" ? 0 : match[1] === "业务含义" ? 2 : 1;
        const value = match[2].trim();
        activeLabelIndex = /[。！？!?；;]$/.test(value) ? null : index;
        if (!labelled.has(index)) labelled.set(index, value);
      } else if (activeLabelIndex !== null) {
        labelled.set(activeLabelIndex, `${labelled.get(activeLabelIndex) || ""}${line}`.trim());
      } else if (line.length < 12 && !/[\d。！？!?；;，,]/.test(line)) {
        return;
      } else if (!(line.startsWith("|") && line.endsWith("|"))) {
        candidates.push(line);
      }
    });
    if (candidates.length < 3 && labelled.size === 0) {
      const sentences = candidates.join(" ").split(/(?<=[。！？!?])\s*/).map((item) => item.trim()).filter(Boolean);
      if (sentences.length > candidates.length) candidates.splice(0, candidates.length, ...sentences);
    }
    const labels = ["竞争格局", "公司定位", "业务含义"];
    let candidateIndex = 0;
    return labels.flatMap((label, index) => {
      let value = labelled.get(index) || "";
      if (!labelled.size && !value) value = candidates[candidateIndex++] || "";
      value = value.replace(/^(竞争格局|公司分化|公司定位|业务含义)[：|｜]\s*/, "").trim();
      if (!value) return [];
      if (value.length > 180) value = `${value.slice(0, 179).replace(/[，,；;\s]+$/, "")}…`;
      return [`${label}｜${value}`];
    });
  }

  function parseCompetitorStrategicSignal(content) {
    const text = String(content || "").replace(/^```(?:json|text|markdown)?\s*|\s*```$/gi, "");
    const line = text.split(/\n/).find((item) => /^(?:\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)、]\s*))?(战略指标|核心结论)[：|｜]/.test(item));
    if (!line) return { text: "", highlights: [] };
    const marked = line.replace(/^\s*(?:#{1,6}\s*|[-*•]\s+|\d+[.)、]\s*)/, "").replace(/^(战略指标|核心结论)[：|｜]\s*/, "").trim();
    const highlights = [...marked.matchAll(/【([^【】]{2,12})】/g)].map((match) => match[1].trim()).filter(Boolean).slice(0, 3);
    const value = marked.replace(/[【】]/g, "").trim().replace(/[。．.]+$/, "").slice(0, 100);
    return { text: value, highlights: [...new Set(highlights)].filter((item) => value.includes(item)) };
  }

  function parseCompetitorStrategicIndicator(content) {
    return parseCompetitorStrategicSignal(content).text;
  }

  function setCompetitorInsightStatus(card, message = "") {
    const status = card?.querySelector("[data-competitor-insight-status]");
    if (!status) return;
    status.textContent = message;
    status.hidden = !message;
  }

  function beginCompetitorInsightStream(card, { preserveVisible = false } = {}) {
    if (!card) return;
    const list = card.querySelector("[data-competitor-insight-list]");
    const keepVisible = preserveVisible && list.children.length > 0;
    card.classList.remove("is-ai", "is-loading", "is-streaming");
    card.classList.add(keepVisible ? "is-streaming" : "is-loading");
    card.setAttribute("aria-busy", "true");
    setCompetitorInsightStatus(card, "正在连接 AI");
    card.querySelector("[data-competitor-insight-badge]").textContent = "CONNECTING";
    if (!keepVisible) {
      list.replaceChildren();
      beginCompetitorStrategicIndicator();
    }
  }

  function renderCompetitorInsightDraft(card, text) {
    const strategicSignal = parseCompetitorStrategicSignal(text);
    if (strategicSignal.text) streamCompetitorStrategicIndicator(strategicSignal.text, strategicSignal.highlights);
    const drafts = parseCompetitorInsightItems(text);
    if (!card || !drafts.length) return;
    card.classList.remove("is-loading");
    card.classList.add("is-streaming");
    setCompetitorInsightStatus(card, `AI 正在流式生成 · 已收到 ${String(text).length} 字`);
    card.querySelector("[data-competitor-insight-badge]").textContent = "AI STREAM";
    syncCompetitorInsightRows(card, drafts, { streaming: true });
  }

  function scheduleCompetitorInsightRecovery(payload, requestId, card, error) {
    if (requestId !== state.competitorInsightRequest || !card) return;
    const delays = [5, 15, 30, 60, 120, 300];
    const attempt = ++state.competitorInsightRetryAttempt;
    const delay = delays[Math.min(attempt - 1, delays.length - 1)];
    card.querySelector("[data-competitor-insight-badge]").textContent = "AUTO HEAL";
    setCompetitorInsightStatus(card, `AI 生成失败，已告警 · ${delay} 秒后自动恢复（第 ${attempt} 次）`);
    console.warn("Competitor insight recovery scheduled", error);
    window.clearTimeout(state.competitorInsightRetryTimer);
    state.competitorInsightRetryTimer = window.setTimeout(() => {
      state.competitorInsightRetryTimer = null;
      if (requestId === state.competitorInsightRequest) requestCompetitorInsight(payload, requestId, { recovery: true });
    }, delay * 1000);
  }

  async function requestCompetitorInsight(payload, requestId, { recovery = false } = {}) {
    const controller = new AbortController();
    state.competitorInsightController = controller;
    const card = document.querySelector("#competitorInsight");
    beginCompetitorInsightStream(card, { preserveVisible: recovery });
    if (recovery) {
      setCompetitorInsightStatus(card, `自动恢复中 · 第 ${state.competitorInsightRetryAttempt} 次`);
      card.querySelector("[data-competitor-insight-badge]").textContent = "RECOVERING";
    }
    let generated = "";
    try {
      const response = await fetch("/api/competitor-insight-stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requestId: String(requestId), ...payload }), signal: controller.signal });
      if (!response.ok || !response.body) throw new Error(`AI流式接口 HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          const line = block.split("\n").find((item) => item.startsWith("data:"));
          if (!line) continue;
          const event = JSON.parse(line.replace(/^data:\s*/, ""));
          if (requestId !== state.competitorInsightRequest) return;
          if (event.type === "status") {
            setCompetitorInsightStatus(card, event.message || "AI 正在处理");
            card.querySelector("[data-competitor-insight-badge]").textContent = event.stage === "queue" ? "QUEUED" : "GENERATING";
          } else if (event.type === "delta") {
            generated += String(event.text || "");
            renderCompetitorInsightDraft(card, generated);
            await new Promise((resolve) => window.requestAnimationFrame(resolve));
          } else if (event.type === "done" && event.ok) {
            completed = true;
            state.competitorInsightRetryAttempt = 0;
            window.clearTimeout(state.competitorInsightRetryTimer);
            state.competitorInsightRetryTimer = null;
            settleCompetitorInsight(card, { mode: "ai", strategicIndicator: event.strategicIndicator, strategicHighlights: event.strategicHighlights, insight: event.insight, insights: event.insights });
          } else if (event.type === "error") {
            throw new Error(event.error || "AI生成失败");
          }
        }
        if (done) break;
      }
      if (!completed) throw new Error("AI流式响应未正常完成");
    } catch (error) {
      if (error.name === "AbortError") return;
      if (requestId === state.competitorInsightRequest && card) {
        const partial = parseCompetitorInsightItems(generated);
        const partialSignal = parseCompetitorStrategicSignal(generated);
        settleCompetitorInsight(card, {
          mode: partial.length ? "ai" : "unavailable",
          strategicIndicator: partialSignal.text,
          strategicHighlights: partialSignal.highlights,
          insight: generated,
          insights: partial,
          status: partial.length ? "本次生成提前结束，已保留 AI 返回内容；故障已告警" : "AI 生成失败，已告警并启动自动恢复",
        });
        scheduleCompetitorInsightRecovery(payload, requestId, card, error);
      }
    } finally {
      if (state.competitorInsightController === controller) state.competitorInsightController = null;
    }
  }

  function newsRunDate(run) {
    return String(run?.started_at_hkt || "").slice(0, 10);
  }

  function runCompletedDate(run) {
    return String(run?.completed_at_hkt || "").slice(0, 10);
  }

  function mainRunForDate(date) {
    const mainRuns = state.crawlRuns.filter((run) => String(run.trigger || "") === "定时爬虫");
    return mainRuns.find((run) => newsRunDate(run) === date)
      || mainRuns.find((run) => runCompletedDate(run) === date)
      || {};
  }

  function newsRunTime(run) {
    return String(run?.started_at_hkt || "").slice(11, 16) || "--:--";
  }

  function logLine(content, prefix) {
    return String(content || "").split("\n").find((line) => line.includes(prefix)) || "";
  }

  function logLineMatching(content, pattern) {
    return String(content || "").split("\n").find((line) => pattern.test(line)) || "";
  }

  function logNumber(content, pattern, fallback = 0) {
    const match = String(content || "").match(pattern);
    return match ? Number(match[1] || 0) : Number(fallback || 0);
  }

  const newsStageLogPatterns = {
    search: /搜索准备|固定监控|Agentic Search|页面线索|新闻发现|线索合并|检索/,
    gate: /确定性门禁|硬规则|时间窗|发布日期|规范化 URL|候选门禁/,
    ai: /AI审核|AI 审核|逐条审核|语义审核|单条异常|审核队列/,
    dedupe: /语义去重|历史事件|重复事件|去重/,
    write: /飞书|写入|逐格回读|单元格|审核表/,
    push: /群通知|群组推送|通知状态|结果归档|归档完成/,
  };

  function newsStageLogLines(content, stageKey) {
    const pattern = newsStageLogPatterns[stageKey];
    if (!pattern) return [];
    return String(content || "").split("\n").filter((line) => pattern.test(line));
  }

  function buildNewsProcess(run, detail) {
    const content = detail?.content || "";
    const summary = run?.operational_summary || {};
    const runStatus = String(run?.run_status || run?.status || "").toLowerCase();
    const runCompleted = ["completed", "complete", "success", "succeeded", "done"].includes(runStatus);
    const discovered = logNumber(content, /新闻发现完成：时间窗内发现\s*(\d+)\s*条/, summary.discovered);
    const gateInput = logNumber(content, /候选确定性门禁：输入\s*(\d+)\s*条/, discovered);
    const gatePassed = logNumber(content, /候选确定性门禁：输入\s*\d+\s*条，通过\s*(\d+)\s*条/, gateInput);
    const aiInput = logNumber(content, /AI审核完成：输入\s*(\d+)\s*条/, gatePassed);
    const aiRetained = logNumber(content, /AI审核完成：输入\s*\d+\s*条，纳入\s*(\d+)\s*条/, summary.ai_retained);
    const aiRejected = logNumber(content, /AI审核完成：[^\n]*排除\s*(\d+)\s*条/, Math.max(0, aiInput - aiRetained));
    const duplicates = logNumber(content, /(?:语义去重完成|历史语义去重)：[^\n]*(?:重复|确认重复)\s*(\d+)\s*条/, summary.history_duplicates);
    const newCount = logNumber(content, /(?:语义去重完成|历史语义去重)：[^\n]*(?:总保留|保留新增)\s*(\d+)\s*条/, summary.new_count);
    const keywordCount = logNumber(content, /搜索准备：已加载\s*\d+\s*个监控模块、\s*(\d+)\s*个关键词/, 0);
    const pageCount = logNumber(content, /搜索准备：[^\n]*、\s*(\d+)\s*个固定页面来源/, 0);
    const fixedQueries = logNumber(content, /固定监控检索：执行\s*(\d+)\s*条查询/, 0);
    const agentQueries = logNumber(content, /Agentic Search补缺：[^\n]*规划并执行\s*(\d+)\s*条补缺查询/, 0);
    const pageClues = logNumber(content, /定时页面线索合并：读取\s*(\d+)\s*条页面变化线索/, 0);
    const historical = logNumber(content, /语义去重完成：候选\s*\d+\s*条，历史\s*(\d+)\s*条/, 0);
    const readbackCells = logNumber(content, /飞书逐格回读：[^\n]*所有\s*(\d+)\s*个单元格一致/, 0);
    const notificationStatus = String(summary.notification_status || "").trim();
    const notificationCompleted = /群通知完成：通知状态：/.test(content)
      || (runCompleted && Boolean(notificationStatus));
    const lines = {
      search: logLine(content, "新闻发现完成"),
      gate: logLine(content, "候选确定性门禁"),
      ai: logLine(content, "AI审核完成"),
      dedupe: logLineMatching(content, /(?:^|\]\s*)(?:语义去重完成|历史语义去重)：/),
      write: logLine(content, "飞书逐格回读：第 1 次回读通过") || logLine(content, "飞书写入与逐格回读"),
      push: logLine(content, "群通知完成"),
    };
    const rawStages = [
      { key: "search", label: "线索发现", value: discovered, input: `${keywordCount || "—"} 个关键词 · ${pageCount || "—"} 个固定来源`, lost: 0, details: [`固定监控执行 ${fixedQueries || "—"} 条查询`, `Agentic Search 执行 ${agentQueries || "—"} 条补缺查询`, `合并 ${pageClues || "—"} 条页面变化线索`], evidence: lines.search },
      { key: "gate", label: "确定性门禁", value: gatePassed, input: `${gateInput || discovered} 条候选进入`, lost: Math.max(0, gateInput - gatePassed), details: ["校验时间窗、发布日期、规范化 URL 与基础重复", "不满足硬规则的线索不会消耗 AI 审核额度"], evidence: lines.gate },
      { key: "ai", label: "AI 语义审核", value: aiRetained, input: `${aiInput || gatePassed} 条送审`, lost: aiRejected, details: ["结合竞对、政策、市场、网络与战略相关性逐条判定", `该次运行排除 ${aiRejected} 条；单条异常隔离，不影响其余候选`], evidence: lines.ai },
      { key: "dedupe", label: "历史语义去重", value: newCount, input: `${aiRetained} 条 AI 保留`, lost: duplicates, details: [`与 ${historical || "—"} 条当日历史事件进行语义比对`, `识别 ${duplicates} 条重复事件，保留 ${newCount} 条新增`], evidence: lines.dedupe },
      { key: "write", label: "飞书写入回读", value: newCount, input: `${newCount} 条新增写入`, lost: 0, details: [`逐格回读 ${readbackCells ? number(readbackCells) : "—"} 个单元格`, "只有写入值与回读值完全一致才视为交付成功"], evidence: lines.write },
      { key: "push", label: "群组推送", value: newCount, input: "归档与回读通过后", lost: 0, details: [notificationStatus === "sent" ? "正式群卡片已发送" : notificationCompleted ? "通知已按当前配置完成处理" : "尚未到达推送门禁", "推送发生在审核、去重、写入、回读和归档全部完成之后"], evidence: lines.push },
    ];
    const completedFromSummary = {
      search: runCompleted && summary.discovered !== undefined,
      gate: runCompleted && summary.ai_retained !== undefined,
      ai: runCompleted && summary.ai_retained !== undefined,
      dedupe: runCompleted && summary.history_duplicates !== undefined && summary.new_count !== undefined,
      write: runCompleted && summary.readback_verified === true,
      push: notificationCompleted,
    };
    let waiting = false;
    return rawStages.map((stage) => {
      const done = Boolean(stage.evidence) || completedFromSummary[stage.key] === true;
      const status = done ? "done" : waiting ? "pending" : "current";
      if (!done) waiting = true;
      const evidence = stage.evidence || (completedFromSummary[stage.key]
        ? `${runCompletionText(run)}｜运行完成摘要已确认该阶段完成`
        : "");
      return { ...stage, status, evidence };
    });
  }

  function selectedNewsRuns() {
    const dates = [...new Set(state.newsRuns.map(newsRunDate).filter(Boolean))];
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    let selectedDate = state.newsSelectedDate || params.get("newsDate") || "";
    if (!/^\d{4}-\d{2}-\d{2}$/.test(selectedDate)) {
      const legacyRunId = String(params.get("newsRuns") || params.get("newsRun") || "").split(",").find(Boolean);
      selectedDate = newsRunDate(state.newsRuns.find((run) => run.crawl_run_id === legacyRunId));
    }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(selectedDate)) selectedDate = dates[0] || "";
    state.newsSelectedDate = selectedDate;
    const selected = state.newsRuns.filter((run) => newsRunDate(run) === selectedDate);
    state.newsSelectedRunIds = selected.map((run) => run.crawl_run_id);
    return selected;
  }

  function strategicNewsBatchKey(run) {
    const explicit = String(run?.operational_summary?.slot || "").trim();
    if (explicit) return explicit;
    const scopeSlot = String(run?.scope || "").match(/(\d{4}-\d{2}-\d{2}@\d{2}:\d{2})/)?.[1];
    return scopeSlot || String(run?.crawl_run_id || "");
  }

  function strategicNewsRunRank(run) {
    const status = String(run?.run_status || run?.status || "").toLowerCase();
    const completed = ["completed", "complete", "success", "succeeded", "done"].includes(status);
    if (completed && run?.operational_summary?.readback_verified === true) return 4;
    if (completed) return 3;
    if (["running", "queued", "pending"].includes(status)) return 2;
    return 1;
  }

  function authoritativeStrategicNewsRuns(attempts) {
    const batches = new Map();
    attempts.forEach((run) => {
      const key = strategicNewsBatchKey(run);
      const current = batches.get(key);
      const rank = strategicNewsRunRank(run);
      const currentRank = strategicNewsRunRank(current);
      const runTime = String(run?.completed_at_hkt || run?.started_at_hkt || "");
      const currentTime = String(current?.completed_at_hkt || current?.started_at_hkt || "");
      if (!current || rank > currentRank || (rank === currentRank && runTime > currentTime)) batches.set(key, run);
    });
    return [...batches.values()].sort((left, right) => (
      String(right?.started_at_hkt || "").localeCompare(String(left?.started_at_hkt || ""))
    ));
  }

  function updateNewsDateUrl(date) {
    history.replaceState(null, "", `${location.pathname}${location.search}#workspace=news&newsDate=${encodeURIComponent(date)}`);
  }

  function aggregateNewsStages(runs) {
    const stageSets = runs.map((run) => buildNewsProcess(run, state.newsRunDetails[run.crawl_run_id]));
    return (stageSets[0] || []).map((stage, index) => {
      const variants = stageSets.map((set) => set[index]).filter(Boolean);
      const status = variants.some((item) => item.status === "current") ? "current" : variants.every((item) => item.status === "done") ? "done" : "pending";
      return {
        ...stage,
        value: variants.reduce((sum, item) => sum + item.value, 0),
        lost: variants.reduce((sum, item) => sum + item.lost, 0),
        input: `当天 ${runs.length} 次运行合计`,
        details: variants.map((item, itemIndex) => `${newsRunDate(runs[itemIndex])} ${newsRunTime(runs[itemIndex])}：保留 ${number(item.value)} 条${item.lost ? `，淘汰 ${number(item.lost)} 条` : ""}`),
        evidence: variants.map((item, itemIndex) => `${newsRunDate(runs[itemIndex])} ${newsRunTime(runs[itemIndex])}｜${item.evidence || "尚未到达此步骤"}`).join("\n"),
        status,
      };
    });
  }

  function runCompletionText(run) {
    return String(run?.completed_at_hkt || run?.heartbeat_at_hkt || run?.started_at_hkt || "")
      .replace("T", " ").replace(/\+\d{2}:\d{2}$/, "").slice(0, 16) || "暂无完成记录";
  }

  function linkedParentRunId(run) {
    const explicit = String(run?.parent_crawl_run_id || "").trim();
    if (explicit) return explicit;
    return String(run?.scope || "").match(/父任务\s+([A-Za-z0-9_.-]+)/)?.[1] || "";
  }

  function selectionRunBatchKey(run) {
    const explicit = String(
      run?.idempotency_key
      || run?.operational_summary?.idempotency_key
      || ""
    ).trim();
    if (explicit) return explicit;
    const scopeKey = String(run?.scope || "")
      .match(/爬虫后选材[（(]([^）)]+)[）)]/)?.[1];
    return String(scopeKey || linkedParentRunId(run) || run?.crawl_run_id || "").trim();
  }

  function selectionRunBusinessDate(run) {
    return selectionRunBatchKey(run).match(/(\d{4}-\d{2}-\d{2})@/)?.[1]
      || newsRunDate(run);
  }

  function verifiedSelectionRun(run) {
    const status = String(run?.run_status || run?.status || "").toLowerCase();
    return ["completed", "complete", "success", "succeeded", "done"].includes(status)
      && run?.operational_summary?.readback_verified === true;
  }

  function selectionAttemptRunsForDate(date) {
    return state.crawlRuns.filter((run) => (
      run.task_kind === "news-selection-agent"
      && selectionRunBusinessDate(run) === date
    ));
  }

  function authoritativeSelectionRunsForDate(date) {
    const batches = new Map();
    selectionAttemptRunsForDate(date).forEach((run) => {
      const batchKey = selectionRunBatchKey(run);
      const current = batches.get(batchKey);
      const runVerified = verifiedSelectionRun(run);
      const currentVerified = verifiedSelectionRun(current);
      const preferOriginalVerifiedRun = (
        runVerified
        && currentVerified
        && current?.operational_summary?.reused === true
        && run?.operational_summary?.reused !== true
      );
      if (!current || (runVerified && !currentVerified) || preferOriginalVerifiedRun) {
        batches.set(batchKey, run);
      }
    });
    return [...batches.values()];
  }

  function dailyNewsReviewResults(date) {
    const sheet = state.newsReviewSheet;
    if (!sheet || !Array.isArray(sheet.headers) || !Array.isArray(sheet.rows)) {
      return { available: false, rows: [], appRows: [], appSyncedRows: [], weeklyRows: [], appMachineRows: [], appHumanRows: [], weeklyMachineRows: [], weeklyHumanRows: [] };
    }
    if (sheet.snapshotMode === "cached" && sheet.snapshotCoverageStart && date < sheet.snapshotCoverageStart) {
      return { available: false, rows: [], appRows: [], appSyncedRows: [], weeklyRows: [], appMachineRows: [], appHumanRows: [], weeklyMachineRows: [], weeklyHumanRows: [] };
    }
    const indexes = new Map(sheet.headers.map((header, index) => [String(header || "").trim(), index]));
    const valueAt = (row, ...headers) => {
      const index = headers.map((header) => indexes.get(header)).find((candidate) => candidate !== undefined);
      return String(row?.values?.[index] ?? "").trim();
    };
    const reviewerFor = (row, ...fields) => fields.map((field) => row?.reviewers?.[field]).find(Boolean) || (!row?.reviewers ? row?.reviewer : null);
    const isMachineReviewer = (reviewer) => reviewer?.role === "SYSTEM" || reviewer?.id === "news-auto-screening-bot";
    const rows = sheet.rows.filter((row) => valueAt(row, "检索日期").slice(0, 10) === date).map((row) => ({
      rowNumber: row.rowNumber,
      rollingStatus: valueAt(row, "纳入滚动栏", "是否纳入滚动"),
      weeklyStatus: valueAt(row, "纳入周报", "是否纳入周报"),
      syncStatus: valueAt(row, "同步状态"),
      title: valueAt(row, "新闻标题（AI）"),
      summary: valueAt(row, "内容简介（AI）"),
      source: valueAt(row, "来源媒体"),
      publishedAt: valueAt(row, "发布时间"),
      url: valueAt(row, "原文链接"),
      category: valueAt(row, "分类"),
      reason: valueAt(row, "入池理由"),
      appReviewer: reviewerFor(row, "纳入滚动栏", "是否纳入滚动"),
      weeklyReviewer: reviewerFor(row, "纳入周报", "是否纳入周报"),
    }));
    const appRows = rows.filter((row) => row.rollingStatus === "接受");
    const weeklyRows = rows.filter((row) => row.weeklyStatus === "接受");
    return {
      available: true,
      cached: ["cached", "local_history"].includes(sheet.snapshotMode),
      rows,
      appRows,
      appSyncedRows: appRows.filter((row) => row.syncStatus === "已纳入"),
      weeklyRows,
      appMachineRows: appRows.filter((row) => isMachineReviewer(row.appReviewer)),
      appHumanRows: appRows.filter((row) => !isMachineReviewer(row.appReviewer)),
      weeklyMachineRows: weeklyRows.filter((row) => isMachineReviewer(row.weeklyReviewer)),
      weeklyHumanRows: weeklyRows.filter((row) => !isMachineReviewer(row.weeklyReviewer)),
    };
  }

  function executiveDomainFactsForDate(domain, date) {
    if (!domain || !String(domain.ai_updated_at || "").startsWith(date)) return [];
    return Array.isArray(domain.ai_analysis) ? domain.ai_analysis : [];
  }

  function hktCalendarDate() {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Hong_Kong",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    const value = Object.fromEntries(parts.map((part) => [part.type, part.value]));
    return `${value.year}-${value.month}-${value.day}`;
  }

  function newsLineageRouteId(from, to) {
    return `${from}->${to}`;
  }

  function lineageStatusIcon(status) {
    const paths = {
      healthy: '<path d="m4 12 5 5L20 6"></path>',
      running: '<path d="M3 12h4l2.5-7 5 14 2.5-7h4"></path>',
      warning: '<path d="M12 3 2.5 20h19L12 3Z"></path><path d="M12 9v5"></path><path d="M12 17h.01"></path>',
      critical: '<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8l5-5Z"></path><path d="m9 9 6 6"></path><path d="m15 9-6 6"></path>',
      unknown: '<path d="M5 12h14"></path>',
      interrupted: '<path d="m9 15-2 2a3 3 0 0 1-4-4l3-3a3 3 0 0 1 4-.2"></path><path d="m15 9 2-2a3 3 0 0 1 4 4l-3 3a3 3 0 0 1-4 .2"></path><path d="m4 4 16 16"></path>',
      degraded: '<path d="M12 3 2.5 20h19L12 3Z"></path><path d="M12 9v5"></path><path d="M12 17h.01"></path>',
      "at-risk": '<path d="M12 3 20 7v5c0 5-3.4 8-8 9-4.6-1-8-4-8-9V7l8-4Z"></path><path d="M12 8v5"></path><path d="M12 16h.01"></path>',
    };
    return `<svg class="news-lineage-status-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">${paths[status] || paths.unknown}</svg>`;
  }

  function activeNewsStage(stages) {
    return (Array.isArray(stages) ? stages : []).find((stage) => stage?.status === "current") || null;
  }

  function activeNewsStageNodeKey(stageKey) {
    return ({ search: "news-search", gate: "news-search", ai: "news-ai", dedupe: "news-dedupe", write: "news-output", push: "news-output" })[stageKey] || "";
  }

  function activeNewsStageNodeLabel(stageKey) {
    return ({ search: "公开网页新闻链接搜索", gate: "公开网页新闻链接搜索", ai: "AI 新闻相关性审核", dedupe: "历史新闻重复检查", write: "新增战略新闻归档", push: "新增战略新闻归档" })[stageKey] || "未定位";
  }

  function newsStageHealth(stage, aggregateHealth) {
    if (!stage) return aggregateHealth || { key: "unknown", label: "无记录" };
    if (stage.status === "done") return { key: "healthy", label: "正常" };
    if (stage.status === "pending") return { key: "unknown", label: "无记录" };
    if (aggregateHealth?.key === "critical") return { key: "critical", label: "异常" };
    if (aggregateHealth?.key === "warning") return { key: "warning", label: "警告" };
    if (aggregateHealth?.key === "running") return { key: "running", label: "运行中" };
    return aggregateHealth || { key: "unknown", label: "无记录" };
  }

  function activeLineageRouteAssessments(selectedDate) {
    if (selectedDate !== hktCalendarDate()) return new Map();
    const priority = { interrupted: 4, degraded: 3, at_risk: 2 };
    const routes = new Map();
    (state.tasks || []).filter((task) => (
      task.source === "project-monitor"
      && ["open", "recovery_pending"].includes(String(task.incident_status || ""))
      && Number(task.route_assessment_version || 0) >= 1
    )).forEach((task) => {
      (Array.isArray(task.affected_routes) ? task.affected_routes : []).forEach((route) => {
        const routeId = String(route?.route_id || "");
        const impact = String(route?.impact || "");
        const confidence = String(route?.confidence || "");
        if (!routeId || !priority[impact]) return;
        if (impact === "interrupted" && confidence !== "high") return;
        if (impact === "degraded" && !["high", "medium"].includes(confidence)) return;
        const current = routes.get(routeId);
        if (current && priority[current.impact] >= priority[impact]) return;
        routes.set(routeId, {
          ...route,
          incidentId: task.incident_id || "",
          incidentTitle: task.title || task.alarm_type || "项目告警",
        });
      });
    });
    return routes;
  }

  function newsLineageEdgeStatus(from, to, nodesByKey, selectedDate, routeAssessments) {
    const routeId = newsLineageRouteId(from, to);
    const assessed = routeAssessments.get(routeId);
    const routeImpact = {
      interrupted: { key: "interrupted", label: "中断" },
      degraded: { key: "degraded", label: "降级" },
      at_risk: { key: "at-risk", label: "有风险" },
    }[assessed?.impact];
    if (routeImpact) {
      return {
        ...routeImpact,
        routeId,
        source: "llm-incident",
        confidence: assessed.confidence || "",
        reason: `${assessed.incidentTitle}：${assessed.reason || "LLM判断该线路受影响。"}`,
        incidentId: assessed.incidentId || "",
      };
    }

    const sourceHealth = nodesByKey.get(from)?.health || { key: "unknown", label: "无记录" };
    const targetHealth = nodesByKey.get(to)?.health || { key: "unknown", label: "无记录" };
    if (sourceHealth.key === "critical" && !["healthy", "running"].includes(targetHealth.key)) {
      return { key: "interrupted", label: "中断", routeId, source: "run-evidence", confidence: "high", reason: `${nodesByKey.get(from)?.label || "上游节点"}有真实异常记录，下游交接未确认完成。` };
    }
    if (targetHealth.key === "critical" || targetHealth.key === "warning" || (sourceHealth.key === "warning" && targetHealth.key !== "healthy")) {
      return { key: "degraded", label: "降级", routeId, source: "run-evidence", confidence: "high", reason: `${nodesByKey.get(["critical", "warning"].includes(targetHealth.key) ? to : from)?.label || "相邻节点"}处于异常或警告状态；现有证据不足以把该输入线路判为中断。` };
    }
    if (targetHealth.key === "unknown" || sourceHealth.key === "unknown") {
      return { key: "unknown", label: "待确认", routeId, source: "run-evidence", confidence: "", reason: "缺少相邻节点的运行记录，不推测线路中断。" };
    }
    const runningNode = sourceHealth.key === "running" ? nodesByKey.get(from) : targetHealth.key === "running" ? nodesByKey.get(to) : null;
    return { key: "healthy", label: "正常", routeId, source: "run-evidence", confidence: "high", reason: runningNode ? `当前执行已定位在“${runningNode.label}”节点；未发现线路异常证据。` : "上下游节点均有正常完成记录。" };
  }

  function globalSchedulerLineageModel(runs, stages, attemptRuns = runs) {
    const overview = state.schedulerOverview || {};
    const latest = overview.latest || {};
    const selectedDate = state.newsSelectedDate || newsRunDate(runs[0]);
    const mainRun = mainRunForDate(selectedDate);
    const newsRun = runs[0] || latest.strategic_news || {};
    const sourceDiscoveryRun = state.crawlRuns.find((run) => (
      run.task_kind === "four-database-source-discovery"
      && newsRunDate(run) === selectedDate
    )) || {};
    const selectionAttemptRuns = selectionAttemptRunsForDate(selectedDate);
    const selectionRuns = authoritativeSelectionRunsForDate(selectedDate);
    const matchingIntelligenceRuns = state.crawlRuns.filter((run) => (
      run.task_kind === "executive-intelligence-refresh"
      && (
        newsRunDate(run) === selectedDate
        || (mainRun.crawl_run_id && linkedParentRunId(run) === mainRun.crawl_run_id)
      )
    ));
    const intelligenceRun = matchingIntelligenceRuns.find((run) => (
      run.completed_at_hkt && run.operational_summary?.model_analysis
    )) || matchingIntelligenceRuns[0] || {};
    const runHealth = (run) => {
      if (!run || !Object.keys(run).length) return { key: "unknown", label: "无记录" };
      const status = String(run.run_status || run.status || "").toLowerCase();
      if (run.interrupted || ["failed", "error", "errored"].includes(status)) return { key: "critical", label: "异常" };
      if (["partial", "warning", "degraded", "cutoff"].includes(status)) return { key: "warning", label: "警告" };
      if (["running", "queued", "pending"].includes(status)) return { key: "running", label: "运行中" };
      if (["completed", "complete", "success", "succeeded", "done"].includes(status)) return { key: "healthy", label: "正常" };
      return { key: "warning", label: "待确认" };
    };
    const combinedRunHealth = (items) => {
      const healthItems = items.map(runHealth);
      return healthItems.find((item) => item.key === "critical")
        || healthItems.find((item) => item.key === "running")
        || healthItems.find((item) => item.key === "warning")
        || healthItems.find((item) => item.key === "healthy")
        || { key: "unknown", label: "无记录" };
    };
    const strategicHealth = combinedRunHealth(runs);
    const mainHealth = runHealth(mainRun);
    const sourceDiscoveryHealth = runHealth(sourceDiscoveryRun);
    const selectionHealth = combinedRunHealth(selectionRuns);
    const intelligenceHealth = runHealth(intelligenceRun);
    const strategicSearchHealth = newsStageHealth(stages.find((stage) => stage.key === "search"), strategicHealth);
    const strategicAiHealth = newsStageHealth(stages.find((stage) => stage.key === "ai"), strategicHealth);
    const strategicDedupeHealth = newsStageHealth(stages.find((stage) => stage.key === "dedupe"), strategicHealth);
    const strategicOutputHealth = newsStageHealth(stages.find((stage) => stage.key === "push"), strategicHealth);
    const currentStrategicStage = strategicHealth.key === "running" ? activeNewsStage(stages) : null;
    const currentStrategicNodeKey = activeNewsStageNodeKey(currentStrategicStage?.key);
    const preciseStrategicHealth = (nodeKey, fallbackHealth) => currentStrategicNodeKey === nodeKey
      ? { key: "running", label: "运行中" }
      : fallbackHealth;
    const preciseStrategicNote = (nodeKey, fallbackNote) => currentStrategicNodeKey === nodeKey
      ? `当前阶段：${currentStrategicStage.label}`
      : fallbackNote;
    const domains = new Map((state.executiveIntelligence?.domains || []).map((domain) => [domain.id, domain]));
    const expectedFocusInsightCount = Number(
      intelligenceRun.operational_summary?.model_analysis?.focuses_expected
      || state.executiveIntelligence?.ui_contract?.focuses_expected
      || 15
    );
    const sourceAudit = intelligenceRun.operational_summary?.overview_source_recrawl || {};
    const refreshState = state.executiveIntelligence?.refresh || {};
    const refreshMatchesDate = String(refreshState.completed_at_hkt || "").startsWith(selectedDate);
    const uiValueChanges = refreshMatchesDate ? refreshState.ui_value_changes || {} : {};
    const numericBaselineAvailable = uiValueChanges.baseline_available === true;
    const domainNode = (key, fallbackLabel, position, variant) => {
      const domain = domains.get(key) || {};
      const sourceStats = sourceAudit.domains?.[key] || {};
      const refreshDomain = refreshMatchesDate ? refreshState.domains?.[key] || {} : {};
      const archivedFacts = executiveDomainFactsForDate(domain, selectedDate);
      const factCount = Number(refreshDomain.agent_fact_update?.facts ?? archivedFacts.length ?? 0);
      const uiItems = String(domain.ai_updated_at || "").startsWith(selectedDate) && Array.isArray(domain.entities)
        ? domain.entities
        : [];
      const uiItemCount = uiItems.length;
      const sourceChanged = Number(sourceStats.content_changed || 0);
      const firstObserved = Number(sourceStats.first_observation || 0);
      const retrieved = Number(sourceStats.retrieved || 0);
      const failed = Number(sourceStats.failed || 0);
      const sourceUnchanged = Math.max(0, retrieved - sourceChanged - firstObserved);
      const databaseChanged = Boolean(refreshDomain.database_changed);
      const numericChangeCount = Number(uiValueChanges.domains?.[key]?.changed || 0);
      const numericChangeText = numericBaselineAvailable ? `${number(numericChangeCount)} 项` : "未留存";
      return {
        key: `database-${key}`,
        label: `${domain.title || fallbackLabel}数据发布`,
        value: intelligenceRun.crawl_run_id ? number(uiItemCount) : "—",
        unit: "个主体发布到 UI",
        note: intelligenceRun.crawl_run_id ? `重新发布 ${number(uiItemCount)} 个主体 · 数据指标变化 ${numericChangeText}` : "当天未留下四库刷新归档",
        health: intelligenceHealth,
        variant,
        compact: true,
        position,
        details: intelligenceRun.crawl_run_id ? [
          `当天重新发布到 UI ${number(uiItemCount)} 个公司或厂商主体；结构化数据指标变化 ${numericChangeText}`,
          `数据库事实快照 ${number(factCount)} 条；本库文件内容${databaseChanged ? "有变动" : "未变动"}，不据此计算数值变化`,
          `官方来源检查 ${number(Number(sourceStats.official_urls || 0))} 条：成功 ${number(retrieved)} 条、失败 ${number(failed)} 条`,
          `成功来源中：页面内容指纹变化 ${number(sourceChanged)} 条、首次采样 ${number(firstObserved)} 条、内容未变 ${number(sourceUnchanged)} 条；这些均不计作数值变化`,
          numericBaselineAvailable ? "数值变化只按同一UI字段旧值→新值比较；点开可查看重新发布对象及明确的前后值" : "本轮未留存更新前数值基线，页面不推测变化数量",
          `运行 ${intelligenceRun.crawl_run_id} · 完成 ${runCompletionText(intelligenceRun)}`,
        ] : ["所选日期没有该数据库的刷新记录"],
        evidence: intelligenceRun.progress_detail || intelligenceRun.status_detail || "当天未留下该数据库的运行证据。",
      };
    };
    const databaseFactCount = [...domains.values()].reduce(
      (sum, domain) => sum + executiveDomainFactsForDate(domain, selectedDate).length,
      0
    );
    const refreshFactCount = refreshMatchesDate
      ? ["local", "international", "cloud", "mainland"].reduce(
        (sum, key) => sum + Number(refreshState.domains?.[key]?.agent_fact_update?.facts || 0),
        0
      )
      : databaseFactCount;
    const sourceRetrieved = Number(sourceAudit.retrieved || 0);
    const sourceChanged = Number(sourceAudit.content_changed || 0);
    const sourceFirstObserved = Number(sourceAudit.first_observation || 0);
    const sourceUnchanged = Math.max(0, sourceRetrieved - sourceChanged - sourceFirstObserved);
    const changedDatabaseCount = Array.isArray(refreshState.change_summary?.database_changed_domains)
      ? refreshState.change_summary.database_changed_domains.length
      : ["local", "international", "cloud", "mainland"].filter((key) => refreshState.domains?.[key]?.database_changed).length;
    const numericChangeCount = Number(uiValueChanges.changed || 0);
    const numericChangeText = numericBaselineAvailable ? `${number(numericChangeCount)} 项` : "未留存";
    const modelAnalysis = intelligenceRun.operational_summary?.model_analysis || {};
    const focusInsightCount = Number(modelAnalysis.focuses_passed || 0);
    const expectedDiscoveryInsightCount = Number(modelAnalysis.discoveries_expected ?? 4);
    const discoveryInsightCount = Number(
      modelAnalysis.discoveries_passed
      ?? (modelAnalysis.discovery_model ? expectedDiscoveryInsightCount : 0)
    );
    const expectedInsightCount = Number(
      modelAnalysis.insights_expected
      ?? (expectedFocusInsightCount + expectedDiscoveryInsightCount)
    );
    const insightCount = Number(
      modelAnalysis.insights_passed
      ?? (focusInsightCount + discoveryInsightCount)
    );
    const insightCoverageComplete = insightCount === expectedInsightCount
      && focusInsightCount === expectedFocusInsightCount
      && discoveryInsightCount === expectedDiscoveryInsightCount;
    const insightGenerationLabel = modelAnalysis.reused ? "复用" : "重新生成";
    const strategicDedupe = stages.find((stage) => stage.key === "dedupe") || { value: 0, lost: 0 };
    const mainRunDetail = state.newsRunDetails[mainRun.crawl_run_id] || {};
    const fixedSourceSummary = state.fixedSourceSummary
      || mainRunDetail.fixedSourceSummary
      || state.newsRunDetails[newsRun.crawl_run_id]?.fixedSourceSummary
      || {};
    const scheduledMainRows = new Set(
      [...String(mainRun.scope || "").matchAll(/第\s*(\d+)\s*行/g)].map((match) => match[1])
    ).size;
    const fixedSourceUrlCount = Number(fixedSourceSummary.uniqueUrls || 0);
    const configuredSourceRows = Number(fixedSourceSummary.configuredRows || scheduledMainRows || 0);
    const configuredSourceOccurrences = Number(fixedSourceSummary.configuredUrlOccurrences || 0);
    const crawlUrlAttemptCount = Number(mainRun.run_log?.rows || 0);
    const mainRowsProcessed = Number(mainRun.final_audit?.rows_crawled || 0);
    const mainValue = mainRun.crawl_run_id && fixedSourceUrlCount ? number(fixedSourceUrlCount) : "—";
    const mainUnit = "条当前固定链接";
    const mainCrossedDate = mainRun.crawl_run_id && newsRunDate(mainRun) !== selectedDate;
    const mainDetails = mainRun.crawl_run_id ? [
      `运行 ${mainRun.crawl_run_id}`,
      `状态 ${mainRun.run_status || "未记录"}`,
      ...(mainCrossedDate ? [`跨日任务：${newsRunDate(mainRun)} 启动，${selectedDate} 完成`] : []),
      `开始 ${String(mainRun.started_at_hkt || "未记录").replace("T", " ")}`,
      `完成 ${String(mainRun.completed_at_hkt || "未记录").replace("T", " ")}`,
      ...(fixedSourceUrlCount ? [`当前飞书配置快照含 ${number(fixedSourceUrlCount)} 条去重后的固定链接`, `${number(configuredSourceRows)} 行配置共出现 ${number(configuredSourceOccurrences)} 处链接`] : ["本轮归档未保存可核对的固定链接总数，不再用行数代替链接数"]),
      ...(crawlUrlAttemptCount ? [`本轮共执行 ${number(crawlUrlAttemptCount)} 次网址抓取：成功 ${number(mainRun.run_log?.success_urls)} 次、失败 ${number(mainRun.run_log?.failed_urls)} 次`] : []),
      ...(mainRowsProcessed ? [`旧审计记录为 ${number(mainRowsProcessed)} 行结果；它不是固定链接数量`] : []),
    ] : ["所选日期没有主爬虫运行记录"];
    const archivedAgentCandidateCount = Number(mainRunDetail.agentReviewSummary?.total || 0);
    const companyAgentProgress = mainRunDetail.companyAgentProgress || {};
    const hasCompanyAgentProgress = Number(companyAgentProgress.recordedCompanies || 0) > 0;
    const companyAgentVersion = Number(companyAgentProgress.version || 0);
    const reviewResults = dailyNewsReviewResults(selectedDate);
    const selectionSummary = selectionRuns.reduce((summary, run) => {
      const item = run.operational_summary || {};
      summary.candidates += Number(item.candidate_count || 0);
      summary.verifiedCells += Number(item.verified_field_count ?? item.changed_count ?? 0);
      summary.newCells += Number(item.newly_written_count ?? item.changed_count ?? 0);
      summary.alreadyAppliedCells += Number(item.already_applied_count || 0);
      summary.appAccepted += Number(item.app_accepted_count || 0);
      summary.weeklyAccepted += Number(item.weekly_accepted_count || 0);
      summary.verified = summary.verified && item.readback_verified === true;
      return summary;
    }, { candidates: 0, verifiedCells: 0, newCells: 0, alreadyAppliedCells: 0, appAccepted: 0, weeklyAccepted: 0, verified: selectionRuns.length > 0 });
    const reviewEvidence = (rows, label) => rows.length
      ? rows.map((row) => `审核表第 ${row.rowNumber} 行｜${row.title || "未命名新闻"}｜${label}`).join("\n")
      : reviewResults.available ? `当天没有${label}的消息。` : "审核表数据暂时无法读取。";
    const sourceDiscoverySummary = sourceDiscoveryRun.operational_summary || intelligenceRun.operational_summary?.news_database_signals || {};
    const nodes = [
      { key: "strategic", label: "07:30 / 14:00 战略新闻扫描", value: newsRun.run_status === "running" ? "运行中" : number(runs.length), unit: newsRun.run_status === "running" ? "" : "轮新闻扫描任务", note: currentStrategicStage ? `当前节点：${activeNewsStageNodeLabel(currentStrategicStage.key)} · ${currentStrategicStage.label}` : runs.length ? `${attemptRuns.length} 次扫描尝试 · 最近完成 ${runCompletionText(newsRun)}` : "当天没有新闻扫描归档", health: strategicHealth, variant: "crawler", position: [18, 52], details: ["同一时段重试只由最终权威批次参与统计；所有新闻扫描尝试仍保留在此处供追溯", ...attemptRuns.map((run) => `${newsRunTime(run)} · ${run.scope || "战略新闻扫描"} · ${run.run_status || "未记录状态"}`)], evidence: attemptRuns.map((run) => run.progress_detail || run.status_detail || run.scope).filter(Boolean).join("\n") || "当天没有战略新闻运行归档" },
      { key: "news-search", label: "公开网页新闻链接搜索", value: number((stages.find((stage) => stage.key === "search") || {}).value), unit: "条候选新闻链接", note: preciseStrategicNote("news-search", `当天 ${runs.length} 轮新闻扫描权威结果`), health: preciseStrategicHealth("news-search", strategicSearchHealth), variant: "source", position: [295, 52], details: [`实际发现 ${number((stages.find((stage) => stage.key === "search") || {}).value)} 条新闻线索`, ...((stages.find((stage) => stage.key === "search") || {}).details || [])], evidence: (stages.find((stage) => stage.key === "search") || {}).evidence || "当天未留下新闻线索发现日志" },
      { key: "news-ai", label: "AI 新闻相关性审核", value: number((stages.find((stage) => stage.key === "ai") || {}).value), unit: "条相关新闻通过审核", note: preciseStrategicNote("news-ai", `实际排除 ${number((stages.find((stage) => stage.key === "ai") || {}).lost)} 条新闻`), health: preciseStrategicHealth("news-ai", strategicAiHealth), variant: "ai", position: [572, 52], details: [`实际输入 ${number(Number((stages.find((stage) => stage.key === "ai") || {}).value || 0) + Number((stages.find((stage) => stage.key === "ai") || {}).lost || 0))} 条新闻`, `实际纳入 ${number((stages.find((stage) => stage.key === "ai") || {}).value)} 条新闻`, `实际排除 ${number((stages.find((stage) => stage.key === "ai") || {}).lost)} 条新闻`], evidence: (stages.find((stage) => stage.key === "ai") || {}).evidence || "当天未留下新闻 AI 审核日志" },
      { key: "news-dedupe", label: "历史新闻重复检查", value: number(strategicDedupe.lost), unit: "条历史重复新闻", note: preciseStrategicNote("news-dedupe", `去重后留下 ${number(strategicDedupe.value)} 条新闻`), health: preciseStrategicHealth("news-dedupe", strategicDedupeHealth), variant: "gate", position: [849, 52], details: [`当天确认 ${number(strategicDedupe.lost)} 条重复新闻`, `当天去重后保留 ${number(strategicDedupe.value)} 条新闻`], evidence: strategicDedupe.evidence || "当天未留下新闻历史去重日志" },
      { key: "news-output", label: "新增战略新闻归档", value: number(strategicDedupe.value), unit: "条新增战略新闻", note: preciseStrategicNote("news-output", `当天 ${runs.length} 轮新闻扫描权威归档`), health: preciseStrategicHealth("news-output", strategicOutputHealth), variant: "output", position: [1126, 52], details: [`当天新增 ${number(strategicDedupe.value)} 条战略新闻`, `当天识别 ${number(strategicDedupe.lost)} 条历史重复新闻`], evidence: (stages.find((stage) => stage.key === "push") || {}).evidence || newsRun.progress_detail || "当天未留下新闻写入与通知日志" },
      { key: "news-selection-agent", label: "滚动栏与周报自动初筛", value: selectionRuns.length ? `周报新闻 ${number(selectionSummary.weeklyAccepted)} 条` : "—", unit: "", note: selectionRuns.length ? `滚动栏新闻 ${number(selectionSummary.appAccepted)} 条` : "当天未留下新闻初筛任务日志", health: selectionHealth, variant: "ai", dualMetric: true, position: [1392, 92], details: selectionRuns.length ? [`权威新闻批次 ${number(selectionRuns.length)} 个；运行尝试 ${number(selectionAttemptRuns.length)} 次；按批次业务日期 ${selectedDate} 归档，成功回读覆盖同批失败尝试`, `机器纳入周报 ${number(selectionSummary.weeklyAccepted)} 条新闻；机器纳入滚动栏 ${number(selectionSummary.appAccepted)} 条新闻`, `飞书机器人验证 ${number(selectionSummary.verifiedCells)} 格；本次新写 ${number(selectionSummary.newCells)} 格，写前已有 ${number(selectionSummary.alreadyAppliedCells)} 格；逐格回读${selectionSummary.verified ? "全部通过" : "存在未核对项"}`, "点击查看每条新闻的接受/不接受结果、模型理由、置信度、机器人身份、具体报错和处理日志"] : ["所选日期没有新闻自动初筛运行记录"], evidence: selectionAttemptRuns.map((run) => `${run.crawl_run_id}｜${run.progress_detail || run.status_detail || "未记录进度"}`).join("\n") || "当天未留下新闻自动初筛日志" },
      { key: "app-result", label: "滚动栏新闻最终接受结果", value: reviewResults.available ? number(reviewResults.appRows.length) : "—", unit: "条新闻", note: reviewResults.available ? `${reviewResults.cached ? "最近完整快照 · " : ""}机器 ${number(reviewResults.appMachineRows.length)} 条新闻 · 人工 ${number(reviewResults.appHumanRows.length)} 条新闻` : "新闻审核表暂时不可用", health: reviewResults.available ? { key: "healthy", label: reviewResults.cached ? "快照" : "正常" } : { key: "warning", label: "警告" }, variant: "app", position: [1668, 24], result: true, reviewRows: reviewResults.appRows, details: [reviewResults.cached ? "实时读取短暂失败，按最近完整新闻审核快照统计当天结果" : "按新闻审核表检索日期统计当天结果", `机器纳入 ${number(reviewResults.appMachineRows.length)} 条新闻；人工纳入 ${number(reviewResults.appHumanRows.length)} 条新闻`, "机器只按已验证的新闻自动初筛操作者统计，其余接受结果计为人工", `${number(reviewResults.appSyncedRows.length)} 条新闻同步状态为“已纳入”`], evidence: reviewEvidence(reviewResults.appRows, "纳入滚动栏") },
      { key: "weekly-result", label: "周报新闻最终接受结果", value: reviewResults.available ? number(reviewResults.weeklyRows.length) : "—", unit: "条新闻", note: reviewResults.available ? `${reviewResults.cached ? "最近完整快照 · " : ""}机器 ${number(reviewResults.weeklyMachineRows.length)} 条新闻 · 人工 ${number(reviewResults.weeklyHumanRows.length)} 条新闻` : "新闻审核表暂时不可用", health: reviewResults.available ? { key: "healthy", label: reviewResults.cached ? "快照" : "正常" } : { key: "warning", label: "警告" }, variant: "report", position: [1668, 184], result: true, reviewRows: reviewResults.weeklyRows, details: [reviewResults.cached ? "实时读取短暂失败，按最近完整新闻审核快照统计当天结果" : "按新闻审核表检索日期统计当天结果", `机器纳入 ${number(reviewResults.weeklyMachineRows.length)} 条新闻；人工纳入 ${number(reviewResults.weeklyHumanRows.length)} 条新闻`, "机器只按已验证的新闻自动初筛操作者统计，其余接受结果计为人工", "生成周报时继续校验新闻发布时间、链接与重复项"], evidence: reviewEvidence(reviewResults.weeklyRows, "纳入周报") },
      { key: "previous-news", label: "前一日新闻线索参考", value: number(sourceDiscoverySummary.previous_day_reference_count || 0), unit: "条历史新闻参考", note: `${number((sourceDiscoverySummary.previous_day_news_runs || []).length)} 轮战略新闻归档`, health: sourceDiscoveryHealth, variant: "history", compact: true, position: [70, 270], details: ["读取前一日战略新闻任务归档", "只筛选与四库主体及数据指标相关的新闻", "新闻摘要只作数据追证线索，不直接成为数据库事实"], evidence: (sourceDiscoverySummary.previous_day_news_runs || []).join("\n") || "当天未读取到前一日战略新闻归档" },
      { key: "news-db-signal", label: "01:00 四库缺口链接搜索", value: number(sourceDiscoverySummary.signal_count || 0), unit: "条待追证数据线索", note: "自动发现补缺链接 · 交给03:00追官方原文", health: sourceDiscoveryHealth, variant: "source", position: [300, 270], details: ["独立搜索 Agent 按四库主体与数据指标字段检索最近24小时资料", "合并前一天07:30/14:00两次战略新闻任务内容作参考", "搜索结果与新闻结果都只作数据线索，不直接成为数据库事实", "数据线索包交给03:00链路继续追查公司 IR、财报或监管披露原文", "飞书独立子表记录查询、URL抓取、HTTP结果、入库决定与拒绝原因"], evidence: sourceDiscoverySummary.audit_path || sourceDiscoveryRun.progress_detail || "当天未留下01:00四库数据资料补缺审计" },
      { key: "main", label: "03:00 固定链接与官方原文抓取", value: mainValue, unit: mainUnit, note: mainRun.crawl_run_id ? `${mainCrossedDate ? "跨日完成 · " : ""}${number(configuredSourceRows)} 行飞书配置 · 本轮 ${number(crawlUrlAttemptCount)} 次网址抓取` : "当天未找到主爬虫归档", health: mainHealth, variant: "crawler", position: [300, 520], details: ["从飞书配置表读取人工维护的固定网址，并接收01:00补缺线索，再抓取网页及后续发现的官方原文", "固定链接数、配置行数和实际网址抓取次数分别统计，互不替代", ...mainDetails], evidence: mainRun.status_detail || mainRun.progress_detail || "当天未留下主爬虫运行证据" },
      { key: "agent", label: "Agent 数据证据审核", value: mainRun.curation?.accepted !== undefined ? number(mainRun.curation.accepted) : hasCompanyAgentProgress ? `${number(companyAgentProgress.recordedCompanies)}/${number(companyAgentProgress.expectedCompanies || 41)}` : "—", unit: mainRun.curation?.accepted !== undefined ? "条数据事实审核通过" : hasCompanyAgentProgress ? "家公司数据证据已记录" : "条数据事实审核通过", note: mainRun.curation?.accepted !== undefined ? "数据事实审核通过量 · 非入库变化量" : hasCompanyAgentProgress ? `V${number(companyAgentVersion)} 检查点 · ${number(companyAgentProgress.recordedMetrics)} 项数据指标` : "当天未留下数据证据审核轨迹", health: mainRun.curation?.accepted !== undefined ? mainHealth : hasCompanyAgentProgress ? { key: "warning", label: "待续跑" } : (mainHealth.key === "healthy" ? { key: "warning", label: "警告" } : mainHealth), variant: "audit", primary: true, position: [545, 392], details: mainRun.curation?.accepted !== undefined ? [`原始数据指标证据 ${number(mainRun.curation.tasks)} 条`, archivedAgentCandidateCount ? `形成并归档候选数据事实 ${number(archivedAgentCandidateCount)} 条${archivedAgentCandidateCount !== Number(mainRun.curation.tasks || 0) ? `；另 ${number(Number(mainRun.curation.tasks || 0) - archivedAgentCandidateCount)} 条未形成候选数据事实` : ""}` : "候选数据事实逐条归档尚未读取", `审核通过 ${number(mainRun.curation.accepted)} 条数据事实；这是证据门禁通过量，不是数据库变化量`, `拒绝 ${number(mainRun.curation.rejected)} 条数据事实 · 待复核 ${number(mainRun.curation.review)} 条数据事实`, `数据审核轨迹事件 ${number(mainRun.curation.trace_events)} 条 · Agent run ${mainRun.curation.agent_run_id || "未记录"}`] : hasCompanyAgentProgress ? [`V${number(companyAgentVersion)} 最后更新 ${String(companyAgentProgress.updatedAt || "未记录").replace("T", " ")}`, `已记录 ${number(companyAgentProgress.recordedCompanies)} / ${number(companyAgentProgress.expectedCompanies || 41)} 家公司`, `数据指标记录 ${number(companyAgentProgress.recordedMetrics)} 项；合规终态 ${number(companyAgentProgress.terminalMetrics)} 项`, `未解决公司 ${number(companyAgentProgress.unresolvedCompanies)} 家；冲突数据指标 ${number(companyAgentProgress.conflictMetrics)} 项；Agent 未完成数据指标 ${number(companyAgentProgress.agentErrorMetrics)} 项`, "当前展示持久检查点；正常调度续跑后自动更新，最终结果文件生成后自动优先显示正式结果"] : ["所选日期没有 Agent 数据证据审核记录"], evidence: mainRun.curation?.summary || (hasCompanyAgentProgress ? `V${number(companyAgentVersion)} 公司 Agent 检查点：${number(companyAgentProgress.recordedCompanies)} 家、${number(companyAgentProgress.recordedMetrics)} 项数据指标，更新时间 ${companyAgentProgress.updatedAt || "未记录"}` : mainRun.status_detail || "当天未留下 Agent 数据证据审核记录") },
      { key: "database-hub", label: "审核通过事实写入四库", value: intelligenceRun.crawl_run_id ? number(refreshFactCount) : "—", unit: "条数据事实写入四库", note: intelligenceRun.crawl_run_id ? `写入 ${number(refreshFactCount)} 条数据事实 · 数据指标变化 ${numericChangeText}` : "当天未留下数据入库归档", health: intelligenceHealth, variant: "database-hub", compact: true, position: [790, 415], details: intelligenceRun.crawl_run_id ? [`当天写入四库数据库事实快照 ${number(refreshFactCount)} 条；结构化数据指标变化 ${numericChangeText}`, `四个可见库中 ${number(changedDatabaseCount)} 个库文件内容有变动；文件或文本变动不计作数据指标变化`, `官方来源检查 ${number(sourceAudit.official_urls || 0)} 条：成功 ${number(sourceRetrieved)} 条、失败 ${number(sourceAudit.failed)} 条`, `成功来源中：页面内容指纹变化 ${number(sourceChanged)} 条、首次采样 ${number(sourceFirstObserved)} 条、内容未变 ${number(sourceUnchanged)} 条；这些均不计作数据指标变化`, numericBaselineAvailable ? "数据指标变化只按同一UI字段旧值→新值比较" : "本轮未留存更新前数值基线，页面不推测数据指标变化数量", "点开下方数据库事实明细可查看公司、数据指标、依据、官方链接和证据哈希"] : ["所选日期没有数据入库记录"], evidence: intelligenceRun.progress_detail || intelligenceRun.status_detail || "当天未留下数据入库记录" },
      domainNode("local", "本地运营商", [990, 410], "database-local"),
      domainNode("international", "国际运营商", [1155, 410], "database-international"),
      domainNode("cloud", "全球云厂商", [990, 535], "database-cloud"),
      domainNode("mainland", "内地运营商", [1155, 535], "database-mainland"),
      { key: "insights", label: "AI 战略洞察生成与 UI 发布", value: intelligenceRun.crawl_run_id ? number(insightCount) : "—", unit: "项数据洞察发布到 UI", note: intelligenceRun.crawl_run_id ? `${insightGenerationLabel} ${number(insightCount)} 项数据洞察 · ${intelligenceRun.operational_summary?.pages_publish?.ok ? "页面发布已验证" : "发布待核对"}` : "当天未运行", health: modelAnalysis.fallback_used || (intelligenceRun.crawl_run_id && intelligenceHealth.key === "healthy" && (!intelligenceRun.operational_summary?.pages_publish?.ok || !insightCoverageComplete)) ? { key: "warning", label: "警告" } : intelligenceHealth, variant: "insight", position: [1385, 455], details: intelligenceRun.crawl_run_id ? [`AI数据洞察通过 ${number(insightCount)} / ${expectedInsightCount} 项；分域洞察 ${number(focusInsightCount)} / ${number(expectedFocusInsightCount)}，顶部跨库研判 ${number(discoveryInsightCount)} / ${number(expectedDiscoveryInsightCount)}；本轮${insightGenerationLabel}`, "数据洞察生成数与数据库事实数、UI发布主体数分别统计，不可互相替代", `模型 ${modelAnalysis.model || "未记录"}`, `证据指纹 ${modelAnalysis.evidence_hash || "未记录"}`, intelligenceRun.operational_summary?.pages_publish?.ok ? `业务发布 主页与公开页已验证 · 版本 ${intelligenceRun.operational_summary.pages_publish.site_version || "未记录"}` : "业务发布 未留下可核对记录"] : ["所选日期没有数据洞察与业务发布归档"], evidence: [intelligenceRun.progress_detail || intelligenceRun.status_detail, intelligenceRun.operational_summary?.pages_publish?.public_url].filter(Boolean).join("\n") || "当天未留下AI数据洞察与业务发布证据" },
    ];
    const nodePurposes = {
      strategic: "按两个固定时段启动当天战略新闻采集",
      "news-search": "搜索公开网页，补齐当天候选新闻链接",
      "news-ai": "逐条判断新闻是否与公司业务和战略相关",
      "news-dedupe": "与历史新闻对比，识别并剔除重复事件",
      "news-output": "保存去重后确认新增的战略新闻",
      "news-selection-agent": "判断每条新闻是否适合滚动栏或战略周报",
      "app-result": "统计新闻审核表中滚动栏字段的最终接受结果，并区分机器与人工操作及同步状态",
      "weekly-result": "统计新闻审核表中周报字段的最终接受结果，并区分机器与人工操作",
      "previous-news": "提供前一日新闻，作为四库数据追证线索",
      "news-db-signal": "自动搜索四库数据缺口相关链接，形成待追证线索并交给03:00抓取链路",
      main: "读取飞书人工维护的固定链接和01:00补缺线索，抓取网页及官方原文后提交审核",
      agent: "逐条审核03:00抓取结果，核对主体、指标、期间、单位、官方来源和证据完整性",
      "database-hub": "只把证据门禁通过的数据事实写入四库",
      "database-local": "把本地运营商主体数据发布到界面",
      "database-international": "把国际运营商主体数据发布到界面",
      "database-cloud": "把全球云厂商主体数据发布到界面",
      "database-mainland": "把内地运营商主体数据发布到界面",
      insights: "根据四库已发布数据生成并发布战略洞察",
    };
    nodes.forEach((node) => { node.purpose = nodePurposes[node.key] || "显示该环节当天的处理作用与结果"; });
    const edges = [
      ["strategic", "news-search", "按时启动公开网页检索", "cyan"], ["news-search", "news-ai", "候选新闻提交相关性审核", "cyan"], ["news-ai", "news-dedupe", "相关新闻进入历史重复检查", "cyan"], ["news-dedupe", "news-output", "非重复新闻写入新增归档", "cyan"], ["news-output", "news-selection-agent", "新增新闻提交发布初筛", "cyan"], ["news-selection-agent", "app-result", "机器初筛写入滚动栏字段", "cyan"], ["news-selection-agent", "weekly-result", "机器初筛写入周报字段", "cyan"], ["news-output", "strategic", "新增归档成为下轮去重基线", "feedback"],
      ["previous-news", "news-db-signal", "前一日新闻提供补缺方向", "amber"], ["news-db-signal", "main", "补缺链接交给03:00追官方原文", "handoff-down"], ["main", "agent", "抓取结果提交证据审核", "cyan"], ["main", "news-search", "固定源网页变化回流为新闻线索", "feedback-side"], ["agent", "database-hub", "审核通过事实写入四库", "cyan"],
      ["database-hub", "database-local", "", "branch"], ["database-hub", "database-international", "", "branch"], ["database-hub", "database-cloud", "", "branch"], ["database-hub", "database-mainland", "", "branch"],
      ["database-local", "insights", "", "merge"], ["database-international", "insights", "", "merge"], ["database-cloud", "insights", "", "merge"], ["database-mainland", "insights", "", "merge"],
    ];
    const nodesByKey = new Map(nodes.map((node) => [node.key, node]));
    const routeAssessments = activeLineageRouteAssessments(selectedDate);
    const edgesWithStatus = edges.map(([from, to, label, kind]) => [
      from,
      to,
      label,
      kind,
      newsLineageEdgeStatus(from, to, nodesByKey, selectedDate, routeAssessments),
    ]);
    return {
      nodes,
      edges: edgesWithStatus,
      canvasSize: [1850, 680],
      feedbackLabel: "新增新闻归档用于下一轮历史去重",
      laneLabels: [
        { label: "A｜战略新闻智能检索线", position: [18, 22] },
        { label: "B｜四库数据资料补缺线", position: [18, 230] },
        { label: "C｜证据审核主链：两类链接 → 审核 → 入库 → UI", position: [18, 430] },
      ],
      groups: [{ key: "databases", label: "审核事实按主体类型写入四库并发布到 UI", note: "四库已发布数据汇总生成右侧 AI 战略洞察", position: [950, 370], size: [389, 301] }],
    };
  }

  function newsLineageEdgePath(from, to, kind = "") {
    const box = (key) => {
      const node = document.querySelector(`[data-news-lineage-node="${key}"]`);
      if (!node) return null;
      return { x: Number(node.dataset.x || 0), y: Number(node.dataset.y || 0), w: node.offsetWidth, h: node.offsetHeight };
    };
    const source = box(from);
    const target = box(to);
    if (!source || !target) return "";
    if (kind === "feedback") {
      const sx = source.x + source.w / 2;
      const upperLoop = source.y < 150 && target.y < 150 && from !== "business";
      const sy = upperLoop ? source.y : source.y + source.h;
      const tx = target.x + target.w / 2;
      const ty = upperLoop ? target.y : target.y + target.h;
      const railY = upperLoop ? 8 : from === "business" ? 425 : 472;
      return `M ${sx} ${sy} C ${sx + 60} ${railY}, ${tx - 110} ${railY}, ${tx} ${ty}`;
    }
    if (kind === "handoff-down") {
      const sx = source.x + source.w / 2;
      const sy = source.y + source.h;
      const tx = target.x + target.w / 2;
      const ty = target.y;
      return `M ${sx} ${sy} V ${ty}`;
    }
    if (kind === "feedback-side") {
      const sx = source.x;
      const sy = source.y + source.h / 2;
      const tx = target.x;
      const ty = target.y + target.h / 2;
      const railX = 10;
      return `M ${sx} ${sy} H ${railX} V ${ty} H ${tx}`;
    }
    if (kind === "branch") {
      const sx = source.x + source.w;
      const sy = source.y + source.h / 2;
      const tx = target.x;
      const ty = target.y + target.h / 2;
      const railX = target.x - 8;
      return `M ${sx} ${sy} H ${railX} V ${ty} H ${tx}`;
    }
    if (kind === "merge") {
      const sx = source.x + source.w;
      const sy = source.y + source.h / 2;
      const tx = target.x;
      const ty = target.y + target.h / 2;
      const railX = source.x + source.w + 8;
      return `M ${sx} ${sy} H ${railX} V ${ty} H ${tx}`;
    }
    const forward = target.x >= source.x;
    const sx = forward ? source.x + source.w : source.x;
    const sy = source.y + source.h / 2;
    const tx = forward ? target.x : target.x + target.w;
    const ty = target.y + target.h / 2;
    const gap = Math.abs(tx - sx);
    const bend = Math.min(Math.max(20, gap * .44), gap / 2);
    return `M ${sx} ${sy} C ${sx + (forward ? bend : -bend)} ${sy}, ${tx - (forward ? bend : -bend)} ${ty}, ${tx} ${ty}`;
  }

  function syncNewsLineageEdges() {
    document.querySelectorAll("[data-news-lineage-edge]").forEach((path) => {
      path.setAttribute("d", newsLineageEdgePath(path.dataset.from, path.dataset.to, path.dataset.kind));
    });
    document.querySelectorAll("[data-news-lineage-label]").forEach((label) => {
      const path = document.querySelector(`#newsLineageEdge${label.dataset.edgeIndex}`);
      if (!path) return;
      const length = path.getTotalLength();
      const point = path.getPointAtLength(path.dataset.kind === "feedback-side" ? length * .1 : length / 2);
      label.style.transform = `translate(${point.x}px,${point.y - 13}px) translate(-50%,-50%)`;
    });
    document.querySelectorAll("[data-news-lineage-state]").forEach((label) => {
      const path = document.querySelector(`#newsLineageEdge${label.dataset.edgeIndex}`);
      if (!path) return;
      const length = path.getTotalLength();
      const point = path.getPointAtLength(path.dataset.kind === "feedback-side" ? length * .1 : length / 2);
      label.style.transform = `translate(${point.x}px,${point.y + 13}px) translate(-50%,-50%)`;
    });
  }

  function scheduleNewsLineageEdgeSync() {
    requestAnimationFrame(() => requestAnimationFrame(syncNewsLineageEdges));
  }

  function fitNewsLineageToViewport(panel) {
    const viewport = panel.querySelector("[data-news-lineage-viewport]");
    const stage = panel.querySelector("[data-news-lineage-stage]");
    const canvas = panel.querySelector("[data-news-lineage-canvas]");
    if (!viewport || !stage || !canvas || viewport.clientWidth <= 0) return;
    const canvasWidth = Number(canvas.dataset.lineageWidth || canvas.offsetWidth || 0);
    const canvasHeight = Number(canvas.dataset.lineageHeight || canvas.offsetHeight || 0);
    if (!canvasWidth || !canvasHeight) return;
    const viewportTop = Math.max(0, viewport.getBoundingClientRect().top);
    const availableHeight = Math.max(1, window.innerHeight - viewportTop - 12);
    const zoom = Math.min(1, viewport.clientWidth / canvasWidth, availableHeight / canvasHeight);
    const scaledWidth = Math.max(1, Math.round(canvasWidth * zoom));
    const scaledHeight = Math.max(1, Math.round(canvasHeight * zoom));
    state.newsLineageZoom = Number(zoom.toFixed(4));
    canvas.style.setProperty("--lineage-zoom", String(state.newsLineageZoom));
    stage.style.width = `${scaledWidth}px`;
    stage.style.height = `${scaledHeight}px`;
    viewport.style.height = `${scaledHeight}px`;
    viewport.dataset.lineageFit = zoom < .9999 ? "scaled" : "native";
  }

  function scheduleNewsLineageFit(panel) {
    cancelAnimationFrame(state.newsLineageFitFrame);
    state.newsLineageFitFrame = requestAnimationFrame(() => {
      fitNewsLineageToViewport(panel);
      scheduleNewsLineageEdgeSync();
    });
  }

  function newsLineageIncidentSignature(tasks) {
    return (Array.isArray(tasks) ? tasks : []).map((task) => ({
      id: task.incident_id || task.task_id || task.task_run_id || "",
      status: task.incident_status || task.status || "",
      severity: task.severity || task.severity_code || "",
      routes: (Array.isArray(task.affected_routes) ? task.affected_routes : []).map((route) => [
        route?.route_id || route?.id || "",
        route?.impact || route?.status || "",
        route?.confidence || "",
      ]),
    })).sort((left, right) => JSON.stringify(left).localeCompare(JSON.stringify(right)));
  }

  function lineageStageKey(nodeKey) {
    return ({ strategic: "search", "news-search": "search", "news-ai": "ai", "news-dedupe": "dedupe", "news-output": "push", "news-selection-agent": "push", "app-result": "push", "weekly-result": "push" })[nodeKey] || "";
  }

  function lineageRunsForNode(nodeKey) {
    const date = state.newsSelectedDate;
    if (["strategic", "news-search", "news-ai", "news-dedupe", "news-output"].includes(nodeKey)) return selectedNewsRuns();
    if (["app-result", "weekly-result"].includes(nodeKey)) return [];
    if (nodeKey === "news-selection-agent") {
      return selectionAttemptRunsForDate(date);
    }
    if (nodeKey === "news-db-signal") {
      return state.crawlRuns.filter((run) => run.task_kind === "four-database-source-discovery" && newsRunDate(run) === date);
    }
    if (["main", "agent"].includes(nodeKey)) {
      const mainRun = mainRunForDate(date);
      return mainRun.crawl_run_id ? [mainRun] : [];
    }
    const mainRun = mainRunForDate(date);
    return state.crawlRuns.filter((run) => (
      run.task_kind === "executive-intelligence-refresh"
      && (
        newsRunDate(run) === date
        || (mainRun.crawl_run_id && linkedParentRunId(run) === mainRun.crawl_run_id)
      )
    ));
  }

  const actualNodeLogPatterns = {
    strategic: /启动门控|搜索准备|新闻发现完成|审核周期完成|结果归档完成|群通知完成/,
    "news-search": /搜索准备|新闻发现完成|检索时间窗|全领域候选保留门禁|固定监控检索|Agentic Search补缺|定时页面线索合并|候选源汇总/,
    "news-ai": /候选确定性门禁|AI逐条审核|AI审核队列|AI审核缓存盘点|AI批量审核|AI紧凑补审|AI审核完成|AI审核结果/,
    "news-dedupe": /语义去重|确定性去重|历史语义去重/,
    "news-output": /新增候选组装|人工审核状态|飞书分批写入|飞书逐格回读|审核周期完成|飞书写入与逐格回读|结果归档完成|群通知/,
    "app-result": /人工审核状态同步|审核周期完成|结果归档完成/,
    "weekly-result": /飞书分批写入|飞书逐格回读|审核周期完成/,
    "news-selection-agent": /人工样本隔离|LangChain 偏好学习|LangChain 分批判断|Skill 更新|机器人权限|机器人身份纠正|当天范围门禁|机器人分批写入(?:与回读)?|处理结果|逐格回读|自动勾选与回读(?:完成)?|失败/,
    agent: /\[数据整理\]/,
    "database-local": /\[本地竞对\]|\[发布审核事实\]/,
    "database-international": /\[国际运营商\]|\[发布审核事实\]/,
    "database-cloud": /\[全球云厂商\]|\[发布审核事实\]/,
    "database-mainland": /\[内地运营商\]|\[发布审核事实\]/,
    insights: /\[生成AI洞察\]|\[更新主页UI\]|\[任务完成\]/,
  };

  function actualEventMeta(rawLine, index) {
    const line = String(rawLine || "").trim();
    if (line.startsWith("{")) {
      try {
        const payload = JSON.parse(line);
        return { time: payload.ts || payload.at || payload.timestamp || "未单独记录时间", title: payload.type || `运行事件 ${index + 1}`, content: payload.message || JSON.stringify(payload), raw: line };
      } catch (_error) { /* keep the original line below */ }
    }
    const timestamp = line.match(/^\[([^\]]*(?:\d{2}:\d{2}:\d{2})[^\]]*)\]\s*/);
    const withoutTime = timestamp ? line.slice(timestamp[0].length) : line;
    const nestedStage = withoutTime.match(/^\[([^\]]+)\]\[([^\]]+)\]\s*/);
    const stage = nestedStage || withoutTime.match(/^\[([^\]]+)\]\s*/);
    const content = stage ? withoutTime.slice(stage[0].length) : withoutTime;
    const title = nestedStage?.[2] || stage?.[1] || content.split(/[:：]/, 1)[0].slice(0, 36) || `运行事件 ${index + 1}`;
    return { time: timestamp?.[1] || "未单独记录时间", title, content: content || line, raw: line };
  }

  function actualEventsForNode(nodeKey, run, detail) {
    if (nodeKey === "news-db-signal") {
      const summary = run?.operational_summary || {};
      const signals = Array.isArray(summary.signals) ? summary.signals : [];
      const summaryEvent = {
        time: run.completed_at_hkt || run.started_at_hkt || "未单独记录时间",
        title: "四库资料补缺完成",
        content: `执行 ${number(summary.query_count || 0)} 个查询，得到 ${number(summary.search_result_count || 0)} 条搜索结果，筛出 ${number(summary.signal_count || signals.length)} 条需追官方原文的线索。`,
        run,
      };
      return [summaryEvent, ...signals.map((signal) => ({
        time: signal.published_at || run.completed_at_hkt || "未单独记录时间",
        title: `${signal.entity || "未记录主体"} · ${signal.title || "未命名线索"}`,
        content: `线索地址：${signal.news_url || "未记录"}\n交接要求：只作为追证入口，03:00链路须访问 ${number((signal.official_followup_urls || []).length)} 个官方地址核实，不直接写入数据库。`,
        run,
      }))];
    }
    const lines = String(detail?.content || "").split("\n").map((line) => line.trim()).filter(Boolean);
    if (nodeKey === "agent") {
      const structured = lines.flatMap((line) => {
        if (!line.startsWith("AGENT_TRACE=")) return [];
        try {
          const event = JSON.parse(line.slice("AGENT_TRACE=".length));
          const facts = [event.message];
          if (event.input) facts.push(`实际输入：${JSON.stringify(event.input)}`);
          if (event.output) facts.push(`实际输出：${JSON.stringify(event.output)}`);
          if (event.result) facts.push(`工具结果：${JSON.stringify(event.result)}`);
          if (event.decision) facts.push(`实际决策：${event.decision}`);
          return [{ time: event.ts || "未单独记录时间", title: [event.node, event.phase].filter(Boolean).join(" · ") || "Agent 轨迹", content: facts.filter(Boolean).join("\n"), raw: line, run }];
        } catch (_error) { return []; }
      });
      if (structured.length) return structured;
    }
    const pattern = actualNodeLogPatterns[nodeKey];
    let selected = pattern ? lines.filter((line) => !/^AGENT_TRACE=|^CURATION_SUMMARY=/.test(line) && pattern.test(line)) : [];
    if (nodeKey === "main") {
      selected = lines.filter((line) => !/^AGENT_TRACE=|^CURATION_SUMMARY=/.test(line) && !/\[数据整理\]/.test(line));
    }
    return selected.map((line, index) => ({ ...actualEventMeta(line, index), run }));
  }

  const newsErrorStageLabels = {
    strategic_news: "战略新闻任务",
    scheduled_cutoff: "战略新闻调度截止",
    four_database_source_discovery: "01:00 四库资料补缺",
    financial_frontend_publish: "AI战略洞察UI更新 / 前端发布",
    executive_intelligence_refresh: "四库更新",
  };

  function newsErrorLocation(nodeKey, run, event, message) {
    const text = `${event?.stage || ""}\n${message || ""}`;
    if (/后台服务已重新启动|原爬虫进程已不存在|任务中断/.test(text)) return { label: "运行进程 / 服务重启", nodeKey: "news-search" };
    if (/新闻偏好学习|新闻自动初筛|机器人分批写入|news_selection_agent/.test(text)) return { label: "新闻自动初筛", nodeKey: "news-selection-agent" };
    if (/飞书审核表|逐格回读|写入后|群通知/.test(text)) return { label: "新增新闻 / 飞书写入回读", nodeKey: "news-output" };
    if (/新闻索引|搜索|检索|查询/.test(text)) return { label: "线索补缺 / 检索", nodeKey: "news-search" };
    if (/AI审核|AI 审核|模型调用|模型返回/.test(text)) return { label: "AI审核", nodeKey: "news-ai" };
    if (/语义去重|历史去重|重复判定/.test(text)) return { label: "历史去重", nodeKey: "news-dedupe" };
    if (/financial_frontend_publish|前端发布|publish_executive_dashboard_pages|\/api\/status/.test(text)) return { label: "AI战略洞察UI更新 / 前端发布", nodeKey: "insights" };
    const rowMatch = text.match(/第\s*(\d+)\s*行失败/);
    if (rowMatch) return { label: `03:00 主爬虫 / 第 ${rowMatch[1]} 行网页抓取`, nodeKey: "main" };
    if (/AGENT_TRACE|数据整理|Agent/.test(text)) return { label: "Agent 证据审核", nodeKey: "agent" };
    const stage = String(event?.stage || run?.failure_stage || "").trim();
    return { label: newsErrorStageLabels[stage] || stage || "运行登记 / 未细分阶段", nodeKey: nodeKey === "strategic" ? "strategic" : "" };
  }

  function newsErrorMessage(event) {
    const raw = event?.error || event?.message || event?.text || "";
    return String(raw).replace(/^\[[^\]]+\]\s*/, "").replace(/^失败[:：]\s*/, "").trim();
  }

  function newsRunErrors(nodeKey, run, detail) {
    const diagnostics = [];
    let lastTime = String(run?.started_at_hkt || "").replace("T", " ").slice(0, 19) || "未记录时间";
    const add = (event, source) => {
      const message = newsErrorMessage(event);
      if (!message) return;
      const time = String(event?.timestamp || event?.ts || event?.at || lastTime || "未记录时间").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
      const location = newsErrorLocation(nodeKey, run, event, message);
      const signature = `${run.crawl_run_id}|${location.label}|${time}|${message}`;
      if (diagnostics.some((item) => item.signature === signature)) return;
      diagnostics.push({ signature, run, time, location, message, source });
    };
    String(detail?.raw || "").split("\n").forEach((line) => {
      const value = String(line || "").trim();
      if (!value) return;
      try {
        const event = JSON.parse(value);
        lastTime = String(event.timestamp || event.ts || event.at || event.startedAt || lastTime);
        const status = String(event.status || "").toLowerCase();
        const explicitLogFailure = event.type === "log" && /(?:^|\])\s*(?:失败[:：]|\[任务中断\])/.test(String(event.text || ""));
        if (event.ok === false || event.interrupted === true || ["failed", "error", "errored"].includes(status) || explicitLogFailure) add(event, "原始运行日志");
      } catch (_error) { /* unstructured traceback is retained by the structured failure event that follows it */ }
    });
    const runStatus = String(run?.run_status || run?.status || "").toLowerCase();
    if (run.interrupted || ["failed", "error", "errored"].includes(runStatus) || detail?.error) {
      const registeredMessage = String(detail?.error || run.status_detail || run.progress_detail || "运行登记为失败，但没有保存错误正文。").trim();
      const alreadyCovered = diagnostics.some((item) => item.message === newsErrorMessage({ message: registeredMessage }));
      if (!alreadyCovered) add({ stage: run.failure_stage, message: registeredMessage, timestamp: run.completed_at_hkt || run.heartbeat_at_hkt || lastTime }, detail?.error ? "日志读取失败" : "运行状态登记");
    }
    return diagnostics;
  }

  function renderNewsErrors(nodeKey, relatedRuns) {
    const diagnostics = relatedRuns.flatMap((run) => newsRunErrors(nodeKey, run, state.newsRunDetails[run.crawl_run_id] || {}));
    const directCount = diagnostics.filter((item) => item.location.nodeKey === nodeKey || nodeKey === "strategic").length;
    if (!diagnostics.length) {
      return `<section class="news-lineage-dialog-section is-error-details is-clear"><header><h3>错误定位与完整明细</h3><span>0 条</span></header><div class="news-lineage-error-empty"><strong>该节点关联运行没有记录错误</strong><p>如果节点仍显示异常，说明当天归档只保留了汇总状态，没有留下可逐条定位的错误正文。</p></div></section>`;
    }
    const relation = directCount ? `本节点直接错误 ${number(directCount)} 条` : "本节点无直接错误；异常来自关联运行的其他环节";
    return `<section class="news-lineage-dialog-section is-error-details"><header><h3>错误定位与完整明细</h3><span>${number(diagnostics.length)} 条 · ${esc(relation)}</span></header><ol class="news-lineage-error-list">${diagnostics.map((item, index) => {
      const facts = item.message.split(/；|\n+/).map((part) => part.trim()).filter(Boolean);
      const relationLabel = item.location.nodeKey === nodeKey || nodeKey === "strategic" ? "本节点直接错误" : `异常位置：${item.location.label}`;
      return `<li><article><header><span>${String(index + 1).padStart(2, "0")}</span><div><strong>${esc(item.location.label)}</strong><em>${esc(relationLabel)}</em></div></header><dl><div><dt>所属运行</dt><dd>${esc(item.run.crawl_run_id || "未记录运行ID")} · ${esc(newsRunTime(item.run))}</dd></div><div><dt>失败阶段</dt><dd>${esc(item.run.failure_stage || item.location.label)}</dd></div><div><dt>记录时间</dt><dd>${esc(item.time)}</dd></div><div><dt>证据来源</dt><dd>${esc(item.source)}</dd></div></dl><div class="news-lineage-error-facts"><strong>具体错误</strong><ol>${facts.map((fact) => `<li>${esc(fact)}</li>`).join("")}</ol></div><details><summary>查看完整错误原文</summary><pre>${esc(item.message)}</pre></details></article></li>`;
    }).join("")}</ol></section>`;
  }

  function executiveNodeRecords(nodeKey) {
    const domainKey = nodeKey.replace(/^database-/, "");
    const domains = state.executiveIntelligence?.domains || [];
    const refreshState = state.executiveIntelligence?.refresh || {};
    const refreshMatchesDate = String(refreshState.completed_at_hkt || "").startsWith(state.newsSelectedDate);
    const uiValueChanges = refreshMatchesDate ? refreshState.ui_value_changes || {} : {};
    const numericBaselineAvailable = uiValueChanges.baseline_available === true;
    const numericChangeItems = numericBaselineAvailable && Array.isArray(uiValueChanges.items) ? uiValueChanges.items : [];
    const factRecord = (domain, item) => ({
      title: `${item.company || domain.title || "未分类"} · ${item.metric || "审核事实"}`,
      summary: item.analysis || item.basis || "",
      source: item.source_url || "",
      status: "updated",
      resultLabel: "已入库",
      reason: item.basis || item.analysis || "本轮归档没有保存处理依据。",
      extra: [
        `所属库：${domain.title || domain.id || "未记录"}`,
        `证据层级：${item.source_tier || "未记录"}`,
        `质量分：${item.quality_score ?? "—"}`,
        `置信度：${item.confidence ?? "—"}`,
        `行引用：${item.row_ref || "未记录"}`,
        `证据哈希：${item.evidence_hash || "未记录"}`,
      ].join("\n"),
      publishedAt: domain.ai_updated_at || "",
    });
    const uiRecord = (domain, item) => {
      const entityName = item.name || `${domain.title || "未分类"} UI对象`;
      const changes = numericChangeItems.filter((change) => change.domain === domain.id && change.entity === entityName);
      const changeDetails = changes.map((change) => `${change.field || "数值字段"}：${change.old_value ?? "—"}${change.unit || ""} → ${change.new_value ?? "—"}${change.unit || ""}`);
      const hasNumericChange = changes.length > 0;
      return {
        title: entityName,
        summary: item.analysis || item.detail || "",
        source: item.source_url || "",
        status: hasNumericChange ? "value-changed" : "updated",
        resultLabel: hasNumericChange ? `数值变化 ${number(changes.length)} 项` : "重新发布 · 数值未变",
        reason: hasNumericChange
          ? `本对象有 ${number(changes.length)} 项结构化数值发生变化：${changeDetails.join("；")}。`
          : numericBaselineAvailable
            ? `已重新发布到${domain.title || domain.id || "四库"}前端数据区；与更新前相同字段逐项比较后，未发现结构化数值变化。`
            : `已重新发布到${domain.title || domain.id || "四库"}前端数据区；本轮未留存更新前数值基线，不能推测数值是否变化。`,
        extra: [
          `所属UI库：${domain.title || domain.id || "未记录"}`,
          `页面主值：${item.value ?? "—"}${item.unit || ""}${item.period ? ` · ${item.period}` : ""}`,
          `UI字段：${(item.components || []).map((part) => `${part.label || "指标"} ${part.value ?? "—"}${part.unit || ""}${part.detail ? `（${part.detail}）` : ""}`).join("；") || "未记录"}`,
          numericBaselineAvailable ? `数值变化：${hasNumericChange ? changeDetails.join("；") : "0 项（数值与更新前相同）"}` : "数值变化：未留存更新前数值基线",
          `核验来源：${item.verification_count ?? "—"} 个`,
        ].join("\n"),
        publishedAt: domain.ai_updated_at || "",
      };
    };
    const insightRecord = (domain, focus) => ({
      title: `${domain.title || domain.id || "未分类"} · ${focus.label || focus.id || "AI洞察"}`,
      summary: focus.insight || focus.headline || "",
      source: (focus.items || []).find((item) => item.source_url)?.source_url || "",
      status: "included",
      resultLabel: "洞察已发布",
      reason: focus.headline || focus.insight || "本轮归档没有保存洞察依据。",
      extra: [
        `主指标：${focus.metric?.label || "未记录"} ${focus.metric?.value ?? "—"}${focus.metric?.unit || ""}`,
        `上下文：${focus.context || "未记录"}`,
        `覆盖UI对象：${(focus.items || []).length} 项`,
      ].join("\n"),
      publishedAt: domain.ai_updated_at || "",
    });
    if (nodeKey === "database-hub") {
      return domains.flatMap((domain) => executiveDomainFactsForDate(domain, state.newsSelectedDate).map((item) => factRecord(domain, item)));
    }
    if (nodeKey.startsWith("database-")) {
      const domain = domains.find((item) => item.id === domainKey);
      if (!domain || !String(domain.ai_updated_at || "").startsWith(state.newsSelectedDate)) return [];
      return (domain.entities || []).map((item) => uiRecord(domain, item));
    }
    if (nodeKey === "insights") {
      return domains.flatMap((domain) => {
        if (!String(domain.ai_updated_at || "").startsWith(state.newsSelectedDate)) return [];
        return (domain.focuses || []).map((focus) => insightRecord(domain, focus));
      });
    }
    if (nodeKey === "main") {
      return relatedRuns.flatMap((run) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        return (Array.isArray(detail.crawlItems) ? detail.crawlItems : []).map((item) => {
          const status = item.status === "completed" ? "included" : item.status === "failed" ? "excluded" : "deferred";
          const urls = Array.isArray(item.urls) ? item.urls : [];
          return {
            run,
            title: item.title || `第 ${item.rowNumber || "—"} 行抓取`,
            summary: item.summary || "本轮没有保存该行抓取摘要。",
            source: urls[0] || "",
            status,
            resultLabel: item.status === "completed" ? "抓取完成" : item.status === "failed" ? "抓取失败" : "部分完成 / 质量待核",
            reason: item.errors?.length ? item.errors.join("；") : "已按该行配置逐一访问来源，并保留HTTP结果、抓取方法与字段覆盖。",
            evidenceUrls: urls,
            evidenceLinkLabel: "实际抓取",
            extra: [
              `调度行：第 ${item.rowNumber || "—"} 行`,
              `行状态：${(item.rowStatuses || []).join("、") || "未记录"}`,
              `来源类型：${(item.sourceTypes || []).join("、") || "未记录"}`,
              `抓取方法：${Object.entries(item.methodCounts || {}).map(([method, count]) => `${method} ${number(count)}次`).join("、") || "未记录"}`,
              `提取字段：${(item.extractedFields || []).join("、") || "未提取到字段"}`,
            ].join("\n"),
          };
        });
      });
    }
    if (nodeKey === "agent") {
      return relatedRuns.flatMap((run) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        return (Array.isArray(detail.agentReviewItems) ? detail.agentReviewItems : []).map((item) => {
          const decision = String(item.decision || "").toLowerCase();
          const status = decision === "accepted" ? "included" : decision === "rejected" ? "excluded" : "deferred";
          const sources = (Array.isArray(item.sources) ? item.sources : []).map((source) => source?.url || "").filter(Boolean);
          const verification = item.search_verification || {};
          return {
            run,
            title: `${item.company || "未记录主体"} · ${item.metric || "未记录指标"}`,
            summary: item.value || item.note || "未提取到可发布数值",
            source: sources[0] || "",
            status,
            resultLabel: decision === "accepted" ? "审核通过" : decision === "rejected" ? "审核拒绝" : "待人工复核",
            reason: [item.basis, ...(item.reasons || [])].filter(Boolean).join("；") || item.note || "本轮未保存审核依据。",
            evidenceUrls: sources,
            evidenceLinkLabel: "证据来源",
            extra: [
              `调度行：${item.row_ref || "未记录"}`,
              `证据层级：${item.source_tier || "未记录"}`,
              `质量分：${item.quality_score ?? "—"} · 置信度：${item.confidence ?? "—"}`,
              `主体支持：${item.entity_supported ? "是" : "否"} · 指标支持：${item.metric_supported ? "是" : "否"} · 数值支持：${item.value_supported ? "是" : "否"}`,
              `在线核验：${verification.status || "未记录"} · ${number(verification.vote_count || 0)} 票 · 冲突 ${number(verification.conflict_count || 0)} 项`,
              verification.online_search?.query ? `核验查询：${verification.online_search.query}` : "核验查询：未记录",
            ].join("\n"),
          };
        });
      });
    }
    return [];
  }

  function detailedRecordsForNode(nodeKey, relatedRuns) {
    if (nodeKey === "news-db-signal") {
      const domainLabels = { local: "本地运营商", international: "国际运营商", mainland: "内地运营商", cloud: "全球云厂商" };
      const originLabels = { "0100_search_engine": "01:00 搜索引擎补缺", previous_day_strategic_news: "前一日战略新闻交接" };
      return relatedRuns.flatMap((run) => {
        const summary = run.operational_summary || {};
        return (Array.isArray(summary.signals) ? summary.signals : []).map((signal) => ({
          run,
          title: signal.title || `${signal.entity || "未记录主体"}线索`,
          summary: `${domainLabels[signal.domain] || signal.domain || "未分类"}｜${signal.entity || "未记录主体"}｜${originLabels[signal.reference_origin] || signal.reference_origin || "来源未记录"}`,
          source: signal.news_url || "",
          status: "handoff",
          resultLabel: "待追官方原文",
          reason: "该条只是公开信息线索，不是数据库事实；已交给03:00链路访问公司 IR、财报或监管披露原文，字段门禁通过后才能入库。",
          officialFollowupUrls: Array.isArray(signal.official_followup_urls) ? signal.official_followup_urls : [],
          extra: [
            `所属库：${domainLabels[signal.domain] || signal.domain || "未记录"}`,
            `涉及主体：${signal.entity || "未记录"}`,
            `线索来源：${originLabels[signal.reference_origin] || signal.reference_origin || "未记录"}`,
            `当前处置：${signal.disposition === "official_followup_required" ? "待追官方原文" : signal.disposition || "未记录"}`,
          ].join("\n"),
          publishedAt: signal.published_at || "",
        }));
      });
    }
    if (nodeKey === "news-selection-agent") {
      return relatedRuns.flatMap((run) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        return (Array.isArray(detail.newsSelectionItems) ? detail.newsSelectionItems : []).map((item) => ({ ...item, run }));
      });
    }
    const detailKey = ({ "news-search": "discoveryItems", "news-ai": "aiReviewItems", "news-dedupe": "dedupeItems", "news-output": "newsItems" })[nodeKey];
    if (detailKey) {
      return relatedRuns.flatMap((run) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        return (Array.isArray(detail[detailKey]) ? detail[detailKey] : []).map((item) => ({ ...item, run }));
      });
    }
    if (nodeKey === "database-hub" || nodeKey.startsWith("database-") || nodeKey === "insights") return executiveNodeRecords(nodeKey);
    return [];
  }

  function detailedRecordStatus(record) {
    const status = String(record.status || "").toLowerCase();
    if (record.resultLabel) return record.resultLabel;
    return ({ included: "AI纳入", excluded: "AI排除", deferred: "延期复审", unrecorded: "未留存决策", duplicate: "历史重复", kept: "去重保留", updated: "已更新" })[status] || "已处理";
  }

  function renderDetailedRecords(nodeKey, records, relatedRuns = []) {
    if (!records.length) {
      const auditedNode = ["news-db-signal", "news-selection-agent", "main", "agent", "database-hub", "insights"].includes(nodeKey) || nodeKey.startsWith("database-");
      if (!auditedNode) return "";
      return `<section class="news-lineage-dialog-section is-item-details is-audit-details"><header><h3>当天逐条内容归档</h3><span>0 条</span></header><p class="news-lineage-detail-coverage">该节点有汇总结果，但当前运行未读取到逐条归档；这属于明细缺口，不代表当天没有处理。请按运行编号检查原始归档。</p></section>`;
    }
    const included = records.filter((item) => ["included", "kept", "updated"].includes(String(item.status || "").toLowerCase()) || item.shouldInclude === true).length;
    const excluded = records.filter((item) => ["excluded", "duplicate"].includes(String(item.status || "").toLowerCase()) || item.shouldInclude === false).length;
    const databaseHubNode = nodeKey === "database-hub";
    const databaseUiNode = !databaseHubNode && nodeKey.startsWith("database-");
    const sourceDiscoveryNode = nodeKey === "news-db-signal";
    const mainCrawlNode = nodeKey === "main";
    const agentAuditNode = nodeKey === "agent";
    const selectionAgentNode = nodeKey === "news-selection-agent";
    const refreshState = state.executiveIntelligence?.refresh || {};
    const refreshMatchesDate = String(refreshState.completed_at_hkt || "").startsWith(state.newsSelectedDate);
    const uiValueChanges = refreshMatchesDate ? refreshState.ui_value_changes || {} : {};
    const numericBaselineAvailable = uiValueChanges.baseline_available === true;
    const domainKey = nodeKey.replace(/^database-/, "");
    const numericChangeCount = Number(databaseUiNode ? uiValueChanges.domains?.[domainKey]?.changed || 0 : uiValueChanges.changed || 0);
    const numericChangeLabel = numericBaselineAvailable ? `数值变化 ${number(numericChangeCount)} 项` : "数值变化未留存";
    const recordLabel = nodeKey === "news-ai" ? `逐条审核 ${records.length} 条 · 纳入 ${included} · 排除 ${excluded}` : sourceDiscoveryNode ? `具体线索 ${records.length} 条` : selectionAgentNode ? `当天自动判断 ${records.length} 条 · 至少一项接受 ${included} 条 · 两项均不接受 ${excluded} 条` : mainCrawlNode ? `实际处理 ${records.length} 行` : agentAuditNode ? `逐条审核 ${records.length} 条 · 通过 ${included} · 拒绝 ${excluded}` : databaseHubNode ? `${numericChangeLabel} · 数据库事实 ${records.length} 条` : databaseUiNode ? `${numericChangeLabel} · UI发布对象 ${records.length} 项` : nodeKey === "insights" ? `逐项洞察 ${records.length} 项` : `逐条记录 ${records.length} 条`;
    const archivedRuns = new Set(records.map((record) => record.run?.crawl_run_id).filter(Boolean));
    const showCoverage = ["news-search", "news-ai", "news-dedupe"].includes(nodeKey) && relatedRuns.length > archivedRuns.size;
    const coverageNote = showCoverage ? `<p class="news-lineage-detail-coverage">逐条归档覆盖 ${number(archivedRuns.size)}/${number(relatedRuns.length)} 次当天运行；其余历史运行只保留了批次汇总，页面不会虚构逐条结果。</p>` : "";
    const detailTitle = sourceDiscoveryNode ? "当天具体线索与官方追证入口" : selectionAgentNode ? "当天新闻自动初筛明细" : mainCrawlNode ? "当天固定源逐行抓取明细" : agentAuditNode ? "当天Agent逐条证据审核明细" : databaseHubNode ? "当天数据库入库与数值变化" : databaseUiNode ? "当天UI重新发布与数值变化" : nodeKey === "insights" ? "当天AI洞察明细" : "当天处理对象明细";
    const numericChangeNote = databaseHubNode || databaseUiNode
      ? numericBaselineAvailable
        ? numericChangeCount > 0
          ? `<p class="news-lineage-value-change-note is-changed">仅带“数值变化”标记的对象计入；详情必须明确显示同一字段的旧值 → 新值。</p>`
          : `<p class="news-lineage-value-change-note is-none">本轮结构化数值变化 0 项；下方 ${number(records.length)} ${databaseHubNode ? "条数据库事实" : "项UI对象"}不代表数值发生变化。</p>`
        : `<p class="news-lineage-value-change-note is-unavailable">本轮未留存更新前数值基线，因此不展示或推测数值变化数量。</p>`
      : "";
    return `<section class="news-lineage-dialog-section is-item-details is-audit-details"><header><h3>${detailTitle}</h3><span>${esc(recordLabel)}</span></header>${coverageNote}${numericChangeNote}<div class="news-lineage-detail-items">${records.map((record) => {
      const status = String(record.status || "processed").toLowerCase();
      const title = record.aiTitle || record.sourceTitle || record.title || "未命名处理对象";
      const sourceUrl = record.url || (String(record.source || "").startsWith("http") ? record.source : "");
      const sourceName = String(record.source || "").startsWith("http") ? "原始来源" : record.source || "未记录";
      const reasonLabel = status === "excluded" ? "AI 排除原因" : status === "duplicate" ? "重复判定依据" : status === "deferred" ? "延期原因" : "处理依据";
      const runLabel = record.run ? `${newsRunTime(record.run)} · ${record.run.crawl_run_id}` : databaseHubNode ? "当天数据库写入" : databaseUiNode ? "当天UI发布" : "当天洞察发布";
      const evidenceUrls = record.evidenceUrls?.length ? record.evidenceUrls : record.officialFollowupUrls || [];
      return `<article class="is-decision-${esc(status)}"><div><span>${esc(detailedRecordStatus(record))}</span><time>${esc(runLabel)}</time></div><h4>${sourceUrl ? `<a href="${esc(safeUrl(sourceUrl))}" target="_blank" rel="noreferrer">${esc(title)}</a>` : esc(title)}</h4><p>${esc(record.aiSummary || record.sourceSummary || record.summary || "未保存内容摘要。")}</p><dl><div><dt>来源</dt><dd>${esc(sourceName)}${record.publishedAt ? ` · ${esc(String(record.publishedAt).replace("T", " ").slice(0, 19))}` : ""}</dd></div>${record.matchedKeywords ? `<div><dt>命中词</dt><dd>${esc(record.matchedKeywords)}</dd></div>` : ""}${record.exclusionCode ? `<div><dt>排除代码</dt><dd>${esc(record.exclusionCode)}</dd></div>` : ""}${record.duplicateOf ? `<div><dt>重复对象</dt><dd>${esc(record.duplicateOf)}</dd></div>` : ""}${evidenceUrls.length ? `<div><dt>${esc(record.evidenceLinkLabel || "官方追证")}</dt><dd class="news-lineage-official-links">${evidenceUrls.map((url, index) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noreferrer">${esc(record.evidenceLinkLabel || "官方地址")} ${number(index + 1)}</a>`).join(" · ")}</dd></div>` : ""}<div><dt>${reasonLabel}</dt><dd>${esc(record.reason || "本轮归档没有保存该条理由。")}</dd></div>${record.extra ? `<div><dt>输出明细</dt><dd class="is-preline">${esc(record.extra)}</dd></div>` : ""}</dl></article>`;
    }).join("")}</div></section>`;
  }

  function companyAgentExecutionModel(relatedRuns) {
    const reports = relatedRuns.flatMap((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      return Array.isArray(detail.companyAgentReports) ? detail.companyAgentReports : [];
    });
    const traces = relatedRuns.flatMap((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      return Array.isArray(detail.companyAgentTrace) ? detail.companyAgentTrace : [];
    });
    const progressRows = relatedRuns.map((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      return detail.companyAgentProgress || {};
    }).filter((progress) => Number(progress.recordedCompanies || 0) > 0);
    const progress = progressRows.sort((left, right) => String(right.updatedAt || "").localeCompare(String(left.updatedAt || "")))[0] || {};
    const unique = new Map();
    reports.forEach((report) => unique.set(report.company, report));
    const groupLabels = { local: "香港运营商", international: "国际运营商", mainland: "内地运营商", cloud: "云厂商" };
    const groups = ["local", "international", "mainland", "cloud"].map((key) => ({
      key,
      label: groupLabels[key],
      reports: [...unique.values()].filter((report) => report.group === key),
    }));
    return {
      reports: [...unique.values()],
      groups,
      traces,
      expected: Number(progress.expectedCompanies || 41),
      recorded: [...unique.values()].length,
      completed: [...unique.values()].filter((report) => ["verified_latest", "not_disclosed", "not_applicable", "search_exhausted"].includes(report.status)).length,
      recordedMetrics: Number(progress.recordedMetrics || [...unique.values()].reduce((sum, report) => sum + (Array.isArray(report.metric_results) ? report.metric_results.length : 0), 0)),
      completedMetrics: Number(progress.terminalMetrics || [...unique.values()].reduce((sum, report) => sum + (Array.isArray(report.metric_results) ? report.metric_results.filter((metric) => ["verified_latest", "not_disclosed", "not_applicable", "search_exhausted"].includes(metric.status)).length : 0), 0)),
      unresolvedCompanies: Number(progress.unresolvedCompanies || 0),
      conflictMetrics: Number(progress.conflictMetrics || 0),
      agentErrorMetrics: Number(progress.agentErrorMetrics || 0),
      version: Number(progress.version || 0),
      updatedAt: progress.updatedAt || "",
    };
  }

  function renderCompanyAgentExecutionGraph(relatedRuns) {
    const model = companyAgentExecutionModel(relatedRuns);
    if (!model.reports.length) {
      return `<section class="news-lineage-dialog-section company-agent-graph-section"><header><h3>公司 Agent 执行图</h3><span>未留存多 Agent 轨迹</span></header><div class="company-agent-graph-empty"><strong>该历史运行尚未使用 41 公司 Multi-Agent 子图</strong><p>页面不会用逐条审核记录伪造 Agent 身份；新版运行完成后将显示真实的搜索、打开原文和终态。</p></div></section>`;
    }
    const statusLabels = { verified_latest: "已核验最新值", not_disclosed: "当期未披露", not_applicable: "不适用", search_exhausted: "搜索未取得证据", conflict: "证据冲突", unsearched: "尚未搜索", agent_error: "Agent 未完成" };
    const groups = model.groups.map((group) => `<section class="company-agent-group is-${esc(group.key)}"><header><strong>${esc(group.label)}</strong><span>${number(group.reports.length)} 家</span></header><ol role="list">${group.reports.map((report, index) => {
      const panelId = `companyAgentDetail-${esc(group.key)}-${index}`;
      const status = report.status || "agent_error";
      const queries = Array.isArray(report.queries) ? report.queries : [];
      const evidenceUrls = Array.isArray(report.evidence_urls) ? report.evidence_urls : [];
      const openAttempts = Array.isArray(report.open_attempts) ? report.open_attempts : [];
      const metricResults = Array.isArray(report.metric_results) ? report.metric_results : [];
      const completedMetrics = metricResults.filter((metric) => ["verified_latest", "not_disclosed", "not_applicable", "search_exhausted"].includes(metric.status)).length;
      const metricDetails = metricResults.length ? `<div><dt>逐指标终态</dt><dd class="company-agent-metric-results">${metricResults.map((metric) => {
        const metricEvidenceUrls = Array.isArray(metric.evidence_urls) ? metric.evidence_urls : [];
        return `<span class="is-${esc(metric.status || "conflict")}"><strong>${esc(metric.metric || "未命名指标")}</strong><em>${esc(statusLabels[metric.status] || metric.status || "未记录")}</em><small class="company-agent-metric-value">记录值：${esc(String(metric.value || "未写入"))}</small><small>搜索 ${number(metric.search_count || 0)} · 当期原文 ${number(metric.fresh_official_open_count || 0)} · 证据 ${number(metric.evidence_count || 0)}</small><p>${esc(metric.rationale || "未留存逐指标理由")}</p>${metricEvidenceUrls.length ? `<p class="company-agent-metric-links">${metricEvidenceUrls.map((url, urlIndex) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noreferrer">指标证据 ${number(urlIndex + 1)}</a>`).join(" · ")}</p>` : ""}</span>`;
      }).join("")}</dd></div>` : "";
      return `<li><button type="button" class="company-agent-node is-${esc(status)}" data-company-agent-node="${esc(report.company)}" aria-expanded="false" aria-controls="${panelId}"><span>${esc(report.company || "未记录公司")}</span><strong>${esc(statusLabels[status] || status)}</strong><em>指标 ${number(completedMetrics)}/${number(metricResults.length)} · 搜索 ${number(report.search_count || 0)} · 原文成功 ${number(report.open_success_count || 0)} · 被拒 ${number(report.open_blocked_count || 0)} · 证据 ${number(report.evidence_count || 0)}</em></button><div class="company-agent-detail" id="${panelId}" hidden><dl><div><dt>最终判断</dt><dd>${esc(report.rationale || "未留存判断理由")}</dd></div><div><dt>研究路径</dt><dd>规划查询 → 搜索引擎 → 打开官方原文 → 逐指标证据门禁 → 提交</dd></div>${metricDetails}${queries.length ? `<div><dt>搜索查询</dt><dd>${queries.map((query) => esc(query)).join("<br>")}</dd></div>` : ""}${openAttempts.length ? `<div><dt>原文打开</dt><dd>${openAttempts.map((attempt) => `${esc(attempt.opened ? "成功" : attempt.blocked_reason || "失败")} · ${esc(attempt.url || "未记录 URL")}`).join("<br>")}</dd></div>` : ""}${evidenceUrls.length ? `<div><dt>官方证据</dt><dd>${evidenceUrls.map((url, urlIndex) => `<a href="${esc(safeUrl(url))}" target="_blank" rel="noreferrer">证据 ${number(urlIndex + 1)}</a>`).join(" · ")}</dd></div>` : ""}</dl></div></li>`;
    }).join("")}</ol></section>`).join("");
    return `<section class="news-lineage-dialog-section company-agent-graph-section"><header><h3>公司 Agent 执行图</h3><span>${model.version ? `V${number(model.version)} · ` : ""}${number(model.recorded)}/${number(model.expected)} 家已记录 · ${number(model.completedMetrics)}/${number(model.recordedMetrics)} 项合规终态${model.updatedAt ? ` · ${esc(String(model.updatedAt).replace("T", " "))}` : ""}</span></header><div class="company-agent-graph" aria-label="Lead Research Agent 到 ${number(model.expected)} 个公司 Agent 再到公司和指标完整性门禁的执行图"><article class="company-agent-lead"><span>LEAD</span><strong>Lead Research Agent</strong><em>确定性派发 ${number(model.expected)} 家</em></article><i class="company-agent-connector" aria-hidden="true"></i><div class="company-agent-groups">${groups}</div><i class="company-agent-connector" aria-hidden="true"></i><article class="company-agent-gate"><span>GATE</span><strong>公司＋指标完整性门禁</strong><em>${number(model.recorded)}/${number(model.expected)} 家已记录 · ${number(model.completedMetrics)}/${number(model.recordedMetrics)} 项终态 · ${number(model.unresolvedCompanies)} 家待复核 · 冲突 ${number(model.conflictMetrics)} 项 · Agent 未完成 ${number(model.agentErrorMetrics)} 项</em></article></div></section>`;
  }

  function bindCompanyAgentGraphInteractions(dialog) {
    dialog.querySelectorAll("[data-company-agent-node]").forEach((button) => {
      button.addEventListener("click", () => {
        const expanded = button.getAttribute("aria-expanded") === "true";
        const panel = dialog.querySelector(`#${CSS.escape(button.getAttribute("aria-controls"))}`);
        button.setAttribute("aria-expanded", expanded ? "false" : "true");
        if (panel) panel.hidden = expanded;
      });
    });
  }

  async function openActualNewsLineageDetail(nodeKey) {
    state.newsSelectedStage = nodeKey;
    const relatedRuns = lineageRunsForNode(nodeKey);
    const missing = relatedRuns.filter((run) => !state.newsRunDetails[run.crawl_run_id]);
    if (missing.length) await loadNewsRuns(missing.map((run) => run.crawl_run_id));
    const attemptRuns = selectedNewsRuns();
    const newsRuns = authoritativeStrategicNewsRuns(attemptRuns);
    const stages = newsRuns.length ? aggregateNewsStages(newsRuns) : [];
    const lineage = globalSchedulerLineageModel(newsRuns, stages, attemptRuns);
    const node = lineage.nodes.find((item) => item.key === nodeKey);
    const dialog = document.querySelector("#newsLineageDialog");
    const body = document.querySelector("#newsLineageDialogBody");
    if (!node || !dialog || !body) return;
    const nodesByKey = new Map(lineage.nodes.map((item) => [item.key, item]));
    const incoming = lineage.edges.filter(([, to]) => to === nodeKey).map(([from]) => nodesByKey.get(from)?.label || from);
    const outgoing = lineage.edges.filter(([from]) => from === nodeKey).map(([, to]) => nodesByKey.get(to)?.label || to);
    const events = (node.reviewRows || []).length ? node.reviewRows.map((row) => ({
      time: row.publishedAt || state.newsSelectedDate,
      title: row.title || `审核表第 ${row.rowNumber} 行`,
      content: `${node.label}｜APP ${row.rollingStatus || "未记录"}｜周报 ${row.weeklyStatus || "未记录"}｜同步 ${row.syncStatus || "未记录"}`,
      run: { crawl_run_id: "飞书审核表", scope: `第 ${row.rowNumber} 行` },
    })) : relatedRuns.flatMap((run) => actualEventsForNode(nodeKey, run, state.newsRunDetails[run.crawl_run_id] || {}));
    const detailedRecords = detailedRecordsForNode(nodeKey, relatedRuns);
    const traceBody = events.length ? `<ol class="news-lineage-process-steps is-actual-trace">${events.map((event, index) => `<li><article><header><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${esc(event.title)}</h4><em class="is-done">${esc(event.time)}</em></div></header><dl><div><dt>所属运行</dt><dd>${esc(event.run.crawl_run_id || "未记录运行ID")} · ${esc(event.run.scope || event.run.trigger || "未记录范围")}</dd></div><div><dt>当天原始处理记录</dt><dd>${esc(event.content)}</dd></div></dl></article></li>`).join("")}</ol>` : `<div class="news-lineage-trace-empty"><strong>${esc(state.newsSelectedDate)} 当天未留下该节点的逐步处理记录</strong><p>这不代表当天没有处理，只表示历史归档没有记到这个粒度。后续定时爬虫的运行日志会自动显示在这里。</p></div>`;
    const relatedItems = node.result ? (node.reviewRows || []).map((item) => ({ run: relatedRuns[0] || {}, item: { ...item, inclusionReason: item.reason } })) : nodeKey === "news-output" ? newsRuns.flatMap((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      return (Array.isArray(detail.newsItems) ? detail.newsItems : []).map((item) => ({ run, item }));
    }) : [];
    const itemDetails = relatedItems.length ? `<section class="news-lineage-dialog-section is-item-details"><header><h3>当天具体内容</h3><span>${number(relatedItems.length)} 条已归档新闻</span></header><div class="news-lineage-detail-items">${relatedItems.map(({ run, item }) => `<article><div><span>${esc(item.category || "未分类")}</span><time>${esc(newsRunTime(run))} · ${esc(String(item.publishedAt || "").replace("T", " ").slice(0, 16) || "未记录发布时间")}</time></div><h4>${item.url ? `<a href="${esc(safeUrl(item.url))}" target="_blank" rel="noreferrer">${esc(item.title)}</a>` : esc(item.title)}</h4><p>${esc(item.summary || "运行归档未保存摘要。")}</p><dl><div><dt>来源</dt><dd>${esc(item.source || "未记录")}</dd></div><div><dt>AI 纳入理由</dt><dd>${esc(item.inclusionReason || "运行归档未记录纳入理由。")}</dd></div></dl></article>`).join("")}</div></section>` : "";
    const reviewItemDetails = (node.reviewRows || []).length ? `<section class="news-lineage-dialog-section is-item-details"><header><h3>当天选用明细</h3><span>${number(node.reviewRows.length)} 条审核表记录</span></header><div class="news-lineage-detail-items">${node.reviewRows.map((item) => `<article><div><span>${esc(item.category || "未分类")}</span><time>${esc(item.publishedAt || "未记录发布时间")}</time></div><h4>${item.url ? `<a href="${esc(safeUrl(item.url))}" target="_blank" rel="noreferrer">${esc(item.title || "未命名新闻")}</a>` : esc(item.title || "未命名新闻")}</h4><p>${esc(item.summary || "审核表未保存内容简介。")}</p><dl><div><dt>来源</dt><dd>${esc(item.source || "未记录")}</dd></div><div><dt>APP状态</dt><dd>${esc(item.rollingStatus || "未记录")} · ${esc(item.syncStatus || "未记录同步状态")}</dd></div><div><dt>周报状态</dt><dd>${esc(item.weeklyStatus || "未记录")}</dd></div><div><dt>入池理由</dt><dd>${esc(item.reason || "审核表未记录入池理由。")}</dd></div></dl></article>`).join("")}</div></section>` : "";
    body.innerHTML = `<header><div><span>${esc(state.newsSelectedDate)} · 当天实际记录</span><h2>${esc(node.label)}</h2><p>只展示所选日期真实发生的处理事件，不展示通用逻辑原则。</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header><div class="news-lineage-dialog-content">
      <section class="news-lineage-dialog-summary"><div><span>当天结果</span><strong>${esc(node.value)}<small>${esc(node.unit || "")}</small></strong><p>${esc(node.note || "")}</p></div><dl><div><dt>当天运行</dt><dd>${relatedRuns.length ? relatedRuns.map((run) => `${newsRunTime(run)} · ${run.crawl_run_id}`).join("、") : "未找到当天运行归档"}</dd></div><div><dt>上下游</dt><dd>${esc(`${incoming.join("、") || "无"} → ${outgoing.join("、") || "无"}`)}</dd></div><div><dt>数据日期</dt><dd>${esc(state.newsSelectedDate)}</dd></div></dl></section>
      ${nodeKey === "agent" ? renderCompanyAgentExecutionGraph(relatedRuns) : ""}
      ${renderNewsErrors(nodeKey, relatedRuns)}
      <section class="news-lineage-dialog-section is-process-flow"><header><h3>当天实际处理轨迹</h3><span>${number(events.length)} 条真实运行事件</span></header>${traceBody}</section>
      ${renderDetailedRecords(nodeKey, detailedRecords, relatedRuns)}
      <section class="news-lineage-dialog-section is-node-notes"><header><h3>当天结果摘要</h3><span>来自当天归档</span></header><ul>${(node.details || []).map((item) => `<li>${esc(item)}</li>`).join("") || "<li>当天未留下结果摘要。</li>"}</ul></section>
      ${itemDetails}
      ${reviewItemDetails}
      <section class="news-lineage-dialog-section is-node-evidence"><header><h3>当天归档摘要</h3><span>运行状态与交付证据</span></header><pre class="news-lineage-node-evidence">${esc(node.evidence || "当天归档未保存可展示的摘要。")}</pre></section>
    </div>`;
    bindCompanyAgentGraphInteractions(dialog);
    dialog.showModal();
  }


  function bindNewsLineageInteractions(panel) {
    state.newsLineageResizeObserver?.disconnect();
    if (state.newsLineageWindowResizeHandler) window.removeEventListener("resize", state.newsLineageWindowResizeHandler);
    if (state.newsLineageTabChangeHandler) window.removeEventListener("workspace-tab-change", state.newsLineageTabChangeHandler);
    const canvas = panel.querySelector("[data-news-lineage-canvas]");
    if (!canvas) return;
    const viewport = panel.querySelector("[data-news-lineage-viewport]");
    const purposeTooltip = panel.querySelector("#newsLineagePurposeTooltip");
    let purposeTooltipNode = null;
    const hidePurposeTooltip = () => {
      if (!purposeTooltip) return;
      purposeTooltip.hidden = true;
      purposeTooltip.classList.remove("is-below");
      purposeTooltipNode?.removeAttribute("aria-describedby");
      purposeTooltipNode = null;
    };
    const showPurposeTooltip = (node) => {
      if (!purposeTooltip || !node) return;
      const label = node.querySelector(":scope > span")?.textContent?.trim() || "当前节点";
      const purpose = node.dataset.newsLineagePurpose || "当前节点尚未填写具体作用。";
      purposeTooltip.querySelector("strong").textContent = label;
      purposeTooltip.querySelector("span").textContent = purpose;
      purposeTooltip.hidden = false;
      purposeTooltipNode?.removeAttribute("aria-describedby");
      purposeTooltipNode = node;
      node.setAttribute("aria-describedby", purposeTooltip.id);
      const nodeRect = node.getBoundingClientRect();
      const tooltipRect = purposeTooltip.getBoundingClientRect();
      const below = nodeRect.top < tooltipRect.height + 24;
      const halfWidth = tooltipRect.width / 2;
      const center = nodeRect.left + nodeRect.width / 2;
      purposeTooltip.classList.toggle("is-below", below);
      purposeTooltip.style.left = `${Math.max(halfWidth + 12, Math.min(window.innerWidth - halfWidth - 12, center))}px`;
      purposeTooltip.style.top = `${below ? nodeRect.bottom + 12 : nodeRect.top - 12}px`;
    };
    canvas.addEventListener("pointerover", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (node && node !== purposeTooltipNode) showPurposeTooltip(node);
    });
    canvas.addEventListener("pointerout", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (node && !node.contains(event.relatedTarget)) hidePurposeTooltip();
    });
    canvas.addEventListener("focusin", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (node) showPurposeTooltip(node);
    });
    canvas.addEventListener("focusout", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (node && !node.contains(event.relatedTarget)) hidePurposeTooltip();
    });
    canvas.addEventListener("click", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (!node) return;
      hidePurposeTooltip();
      panel.querySelectorAll("[data-news-lineage-node]").forEach((item) => item.classList.toggle("is-selected", item === node));
      openActualNewsLineageDetail(node.dataset.newsLineageNode);
    });
    const scheduleFit = () => scheduleNewsLineageFit(panel);
    if (window.ResizeObserver) {
      state.newsLineageResizeObserver = new ResizeObserver(scheduleFit);
      if (viewport) state.newsLineageResizeObserver.observe(viewport);
      state.newsLineageResizeObserver.observe(canvas);
      canvas.querySelectorAll("[data-news-lineage-node]").forEach((node) => state.newsLineageResizeObserver.observe(node));
    }
    state.newsLineageWindowResizeHandler = scheduleFit;
    state.newsLineageTabChangeHandler = scheduleFit;
    window.addEventListener("resize", state.newsLineageWindowResizeHandler, { passive: true });
    window.addEventListener("workspace-tab-change", state.newsLineageTabChangeHandler);
    scheduleFit();
    document.fonts?.ready.then(scheduleFit);
  }

  function renderNewsItems(runs) {
    const groups = runs.map((run) => ({ run, detail: state.newsRunDetails[run.crawl_run_id] })).filter(({ detail }) => detail);
    const itemCount = groups.reduce((sum, group) => sum + (group.detail.newsItems || []).length, 0);
    return `<section class="news-real-items"><header><div><strong>当天真实新增新闻</strong><span>${esc(state.newsSelectedDate)} · ${runs.length} 次定时运行 · 共 ${number(itemCount)} 条</span></div><span>标题、摘要与 AI 纳入理由来自运行归档</span></header>
      <div class="news-real-items-body">${groups.length ? groups.map(({ run, detail }) => {
        const items = Array.isArray(detail.newsItems) ? detail.newsItems : [];
        return `<section class="news-run-group"><header><strong>${esc(newsRunDate(run))} ${esc(newsRunTime(run))}</strong><span>${esc(run.scope || "新闻扫描")} · ${items.length} 条新增</span></header>${items.length ? `<div class="news-item-list">${items.map((item) => `<article class="news-item"><div class="news-item-tags"><span>${esc(item.category || "未分类")}</span>${item.businessImpact ? `<em>${esc(item.businessImpact)}</em>` : ""}</div><h3>${item.url ? `<a href="${esc(safeUrl(item.url))}" target="_blank" rel="noreferrer">${esc(item.title)}</a>` : esc(item.title)}</h3><p>${esc(item.summary || "暂无摘要")}</p><dl><div><dt>来源</dt><dd>${esc(item.source || "未记录")} · ${esc(String(item.publishedAt || "").replace("T", " ").slice(0, 16))}</dd></div><div><dt>AI纳入理由</dt><dd>${esc(item.inclusionReason || "运行归档未记录理由")}</dd></div></dl></article>`).join("")}</div>` : `<div class="news-run-empty">${run.run_status === "completed" ? "该次运行没有新增新闻，或历史归档未保存逐条明细。" : "该次运行尚未完成，真实新增新闻将在归档后出现。"}</div>`}</section>`;
      }).join("") : '<div class="news-run-empty">正在读取所选日期的真实新闻归档…</div>'}</div></section>`;
  }

  function newsViewSnapshot(panel) {
    const viewport = panel?.querySelector("[data-news-lineage-viewport]");
    return {
      windowX: window.scrollX,
      windowY: window.scrollY,
      viewportLeft: viewport?.scrollLeft || 0,
      viewportTop: viewport?.scrollTop || 0,
    };
  }

  function restoreNewsView(panel, snapshot) {
    if (!snapshot) return;
    requestAnimationFrame(() => {
      const viewport = panel?.querySelector("[data-news-lineage-viewport]");
      if (viewport) {
        viewport.scrollLeft = snapshot.viewportLeft;
        viewport.scrollTop = snapshot.viewportTop;
      }
      window.scrollTo(snapshot.windowX, snapshot.windowY);
    });
  }

  function newsLineageMotionStyle() {
    const wallClock = Date.now();
    const delay = duration => `-${wallClock % duration}ms`;
    return `--news-flow-delay:${delay(2400)};--news-degraded-delay:${delay(4800)};--news-schedule-delay:${delay(2100)};--news-schedule-global-delay:${delay(2250)};--news-schedule-degraded-delay:${delay(4500)};--news-feedback-delay:${delay(4200)};--news-feedback-global-delay:${delay(4400)};--news-feedback-degraded-delay:${delay(8800)};`;
  }

  function renderNews({ preserveView = false } = {}) {
    const panel = document.querySelector('[data-workspace-panel="news"]');
    const viewSnapshot = preserveView ? newsViewSnapshot(panel) : null;
    const attemptRuns = selectedNewsRuns();
    const runs = authoritativeStrategicNewsRuns(attemptRuns);
    const run = runs[0] || null;
    const dates = [...new Set(state.newsRuns.map(newsRunDate).filter(Boolean))];
    const sortedDates = [...dates].sort();
    const earliestDate = sortedDates[0] || "";
    const latestDate = sortedDates.at(-1) || "";
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = globalSchedulerLineageModel(runs, stages, attemptRuns);
    const selectedLineageNode = lineage.nodes.find((node) => node.key === state.newsSelectedStage);
    const [lineageWidth, lineageHeight] = lineage.canvasSize || [1260, 480];
    const initialLineageZoom = Number.isFinite(state.newsLineageZoom) && state.newsLineageZoom > 0
      ? Math.min(1, state.newsLineageZoom)
      : 1;
    const initialLineageWidth = Math.max(1, Math.round(lineageWidth * initialLineageZoom));
    const initialLineageHeight = Math.max(1, Math.round(lineageHeight * initialLineageZoom));
    panel.innerHTML = `<div class="workspace-module-inner news-process-workbench">
      <section class="workspace-panel news-process-panel">
        <header class="news-process-toolbar"><h2>三线爬虫与 AI 审核流程</h2><div class="news-monitor-legends"><div class="news-health-legend" aria-label="节点健康状态图例"><span class="is-healthy">${lineageStatusIcon("healthy")}正常</span><span class="is-running">${lineageStatusIcon("running")}运行中</span><span class="is-warning">${lineageStatusIcon("warning")}警告</span><span class="is-critical">${lineageStatusIcon("critical")}异常</span><span class="is-unknown">${lineageStatusIcon("unknown")}无记录</span></div><div class="news-line-health-legend" aria-label="线路状态图例"><span class="is-line-healthy"><i></i>线路正常</span><span class="is-line-scheduled"><i></i>定时</span><span class="is-line-feedback"><i></i>回流</span><span class="is-line-degraded"><i></i>降级</span><span class="is-line-interrupted"><i></i>中断</span></div></div>
          <div class="news-run-controls"><label><span>日期</span><input class="news-date-input" type="date" data-news-date-select aria-label="选择要查看的日期" value="${esc(state.newsSelectedDate)}"${earliestDate ? ` min="${esc(earliestDate)}"` : ""}${latestDate ? ` max="${esc(latestDate)}"` : ""}></label></div>
        </header>
        ${!run ? `<div class="workspace-empty" role="status">${esc(state.newsSelectedDate)} 当天暂无新闻采集运行归档。</div>` : `<section class="news-lineage is-global" aria-label="${esc(state.newsSelectedDate)} 情报获取流程，点击卡片查看详情">
          <div class="news-lineage-viewport" data-news-lineage-viewport tabindex="0" aria-label="自动适配当前屏幕的完整情报生成流程图">
            <div class="news-lineage-stage" data-news-lineage-stage style="width:${initialLineageWidth}px;height:${initialLineageHeight}px">
            <div class="news-lineage-canvas${state.newsLineagePaused ? " is-paused" : ""}" data-news-lineage-canvas data-lineage-width="${lineageWidth}" data-lineage-height="${lineageHeight}" style="--lineage-zoom:${initialLineageZoom};${newsLineageMotionStyle()}width:${lineageWidth}px;height:${lineageHeight}px">
              <svg class="news-lineage-edges" viewBox="0 0 ${lineageWidth} ${lineageHeight}" style="width:${lineageWidth}px;height:${lineageHeight}px" aria-hidden="true"><defs><marker id="newsLineageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowRoutine" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowFeedback" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowRed" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${lineage.edges.map(([from, to, , kind, line], index) => `<g class="news-lineage-edge is-${esc(kind)} is-line-${esc(line?.key || "unknown")}" data-route-id="${esc(line?.routeId || newsLineageRouteId(from, to))}" data-line-state="${esc(line?.key || "unknown")}"><path id="newsLineageEdge${index}" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path><path class="news-lineage-pulse" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path></g>`).join("")}</svg>
              <div class="news-lineage-edge-labels" aria-hidden="true">${lineage.edges.map(([, , label, kind, line], index) => label ? `<span class="news-lineage-edge-label is-${esc(kind)} is-line-${esc(line?.key || "unknown")}" data-news-lineage-label data-edge-index="${index}">${esc(label)}</span>` : "").join("")}</div>
              <div class="news-lineage-edge-states" role="list" aria-label="异常线路状态">${lineage.edges.map(([, , , kind, line], index) => ["interrupted", "degraded", "at-risk"].includes(line?.key) ? `<span class="news-lineage-edge-state is-${esc(line.key)}" role="listitem" data-news-lineage-state data-edge-index="${index}" title="${esc(line.reason || "")}">${lineageStatusIcon(line.key)}${esc(line.label)}</span>` : "").join("")}</div>
              ${lineage.feedbackLabel ? `<span class="news-lineage-feedback-label">${esc(lineage.feedbackLabel)}</span>` : ""}
              ${(lineage.laneLabels || []).map((lane) => `<span class="news-lineage-lane-label" style="transform:translate(${lane.position[0]}px,${lane.position[1]}px)">${esc(lane.label)}</span>`).join("")}
              ${(lineage.groups || []).map((group) => `<div class="news-lineage-group" style="transform:translate(${group.position[0]}px,${group.position[1]}px);width:${group.size[0]}px;height:${group.size[1]}px"><strong>${esc(group.label)}</strong>${group.note ? `<span>${esc(group.note)}</span>` : ""}</div>`).join("")}
              <div class="news-lineage-nodes" role="list">${lineage.nodes.map((node) => `<button class="news-lineage-node is-health-${esc(node.health?.key || "unknown")}${node.variant ? ` is-${esc(node.variant)}` : ""}${node.primary ? " is-primary" : ""}${node.compact ? " is-compact" : ""}${node.result ? " is-result" : ""}${node.dualMetric ? " is-dual-metric" : ""}${node.key === selectedLineageNode?.key ? " is-selected" : ""}" type="button" role="listitem" data-news-lineage-node="${esc(node.key)}" data-news-lineage-purpose="${esc(node.purpose || "未说明")}" data-health="${esc(node.health?.key || "unknown")}" data-x="${node.position[0]}" data-y="${node.position[1]}" style="transform:translate(${node.position[0]}px,${node.position[1]}px)" aria-label="${esc(node.label)}，作用：${esc(node.purpose || "未说明")}，健康状态${esc(node.health?.label || "无记录")}，${esc(node.value)}${esc(node.unit || "")}，${esc(node.note || "")}，点击查看整理详情"><i class="news-lineage-open" aria-hidden="true">↗</i>${node.primary ? '<i class="news-lineage-primary-badge" aria-hidden="true">证据审核核心</i>' : ""}<b class="news-lineage-health">${lineageStatusIcon(node.health?.key || "unknown")}${esc(node.health?.label || "无记录")}</b><span>${esc(node.label)}</span><p>作用：${esc(node.purpose || "未说明")}</p><strong>${esc(node.value)}<small>${esc(node.unit || "")}</small></strong><em>${esc(node.note || "")}</em></button>`).join("")}</div>
            </div>
            </div>
          </div>
        </section>
        ${renderNewsItems(runs)}
        <div class="news-lineage-purpose-tooltip" id="newsLineagePurposeTooltip" role="tooltip" hidden><small>节点具体作用</small><strong></strong><span></span><em>点击节点可查看当天真实处理记录</em></div>
        <dialog class="news-stage-dialog news-lineage-dialog" id="newsLineageDialog"><div id="newsLineageDialogBody"></div></dialog>`}
      </section>
    </div>`;
    bindNewsLineageInteractions(panel);
    restoreNewsView(panel, viewSnapshot);
  }

  async function loadNewsRuns(runIds, { force = false, quiet = false } = {}) {
    if (!runIds.length) return;
    const requestId = ++state.newsRunRequest;
    if (!quiet) markWorkspaceModulesDirty("news");
    const missing = force ? runIds : runIds.filter((id) => !state.newsRunDetails[id]);
    const results = await Promise.all(missing.map(async (runId) => {
      try {
        const response = await fetch(`/api/crawl-run-log?id=${encodeURIComponent(runId)}`, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
        if (!Array.isArray(payload.newsItems) || !payload.newsItems.length) payload.newsItems = state.newsItemFallback[runId] || [];
        return [runId, payload];
      } catch (error) {
        return [runId, { run: { crawl_run_id: runId }, content: "", newsItems: [], error: error.message }];
      }
    }));
    if (requestId !== state.newsRunRequest) return;
    results.forEach(([runId, payload]) => { state.newsRunDetails[runId] = payload; });
    if (!quiet) markWorkspaceModulesDirty("news");
  }

  function newsLiveRenderSignature() {
    const attemptRuns = selectedNewsRuns();
    const runs = authoritativeStrategicNewsRuns(attemptRuns);
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = globalSchedulerLineageModel(runs, stages, attemptRuns);
    return JSON.stringify({
      date: state.newsSelectedDate,
      nodes: lineage.nodes.map((node) => [node.key, node.purpose, node.value, node.unit, node.note, node.health?.key, node.evidence]),
      edges: lineage.edges.map(([from, to, label, kind, line]) => [from, to, label, kind, line?.key, line?.reason]),
      runs: attemptRuns.map((run) => [run.crawl_run_id, run.run_status || run.status, run.heartbeat_at_hkt, run.completed_at_hkt, run.progress_detail, run.status_detail]),
      details: runs.map((run) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        return [run.crawl_run_id, String(detail.content || "").slice(-1200), (detail.newsItems || []).length];
      }),
    });
  }

  function patchNewsLiveView() {
    const panel = document.querySelector('[data-workspace-panel="news"]');
    const canvas = panel?.querySelector("[data-news-lineage-canvas]");
    if (!panel || !canvas) return false;
    const attemptRuns = selectedNewsRuns();
    const runs = authoritativeStrategicNewsRuns(attemptRuns);
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = globalSchedulerLineageModel(runs, stages, attemptRuns);
    const selectedLineageNode = lineage.nodes.find((node) => node.key === state.newsSelectedStage);
    const currentNodes = [...canvas.querySelectorAll("[data-news-lineage-node]")];
    const currentEdges = [...canvas.querySelectorAll(".news-lineage-edge")];
    const nodeKeys = currentNodes.map((node) => node.dataset.newsLineageNode);
    const routeIds = currentEdges.map((edge) => edge.dataset.routeId);
    const nextNodeKeys = lineage.nodes.map((node) => node.key);
    const nextRouteIds = lineage.edges.map(([from, to]) => newsLineageRouteId(from, to));
    if (JSON.stringify(nodeKeys) !== JSON.stringify(nextNodeKeys)
      || JSON.stringify(routeIds) !== JSON.stringify(nextRouteIds)) return false;

    lineage.nodes.forEach((node, index) => {
      const element = currentNodes[index];
      element.className = `news-lineage-node is-health-${node.health?.key || "unknown"}${node.variant ? ` is-${node.variant}` : ""}${node.compact ? " is-compact" : ""}${node.result ? " is-result" : ""}${node.dualMetric ? " is-dual-metric" : ""}${node.key === selectedLineageNode?.key ? " is-selected" : ""}`;
      element.dataset.health = node.health?.key || "unknown";
      element.dataset.newsLineagePurpose = node.purpose || "未说明";
      element.setAttribute("aria-label", `${node.label}，作用：${node.purpose || "未说明"}，健康状态${node.health?.label || "无记录"}，${node.value}${node.unit || ""}，${node.note || ""}，点击查看整理详情`);
      const health = element.querySelector(".news-lineage-health");
      const label = element.querySelector(":scope > span");
      const purpose = element.querySelector(":scope > p");
      const value = element.querySelector(":scope > strong");
      const note = element.querySelector(":scope > em");
      if (health && health.textContent !== (node.health?.label || "无记录")) {
        health.innerHTML = `${lineageStatusIcon(node.health?.key || "unknown")}${esc(node.health?.label || "无记录")}`;
      }
      if (label) label.textContent = node.label;
      if (purpose) purpose.textContent = `作用：${node.purpose || "未说明"}`;
      if (value) {
        value.textContent = node.value;
        if (node.unit) {
          const unit = document.createElement("small");
          unit.textContent = node.unit;
          value.appendChild(unit);
        }
      }
      if (note) note.textContent = node.note || "";
    });

    lineage.edges.forEach(([, , label, kind, line], index) => {
      const edge = currentEdges[index];
      edge.setAttribute("class", `news-lineage-edge is-${kind} is-line-${line?.key || "unknown"}`);
      edge.dataset.lineState = line?.key || "unknown";
      const edgeLabel = canvas.querySelector(`[data-news-lineage-label][data-edge-index="${index}"]`);
      if (edgeLabel && label) {
        edgeLabel.className = `news-lineage-edge-label is-${kind} is-line-${line?.key || "unknown"}`;
        edgeLabel.textContent = label;
      }
    });

    const currentItems = panel.querySelector(".news-real-items");
    if (currentItems) {
      const holder = document.createElement("div");
      holder.innerHTML = renderNewsItems(runs);
      const nextItems = holder.firstElementChild;
      if (nextItems && currentItems.innerHTML !== nextItems.innerHTML) currentItems.replaceWith(nextItems);
    }
    return true;
  }

  async function refreshNewsLiveData() {
    if (state.newsLiveRefreshInFlight || document.visibilityState !== "visible" || activeWorkspaceModule() !== "news") return;
    state.newsLiveRefreshInFlight = true;
    try {
      const requests = [
        ["status", "/api/status"],
        ["newsRuns", "/api/crawl-runs?taskKind=strategic-news&limit=365"],
        ["crawlRuns", "/api/crawl-runs?limit=500"],
        ["scheduler", "/api/scheduler-overview"],
      ];
      if (state.newsLiveReviewTick % 3 === 0) requests.push(
        ["tasks", "/api/project-incidents?limit=500"],
        ["intelligence", "/api/executive-intelligence"],
      );
      const settled = await Promise.allSettled(requests.map(async ([key, url]) => {
        const response = await fetch(url, { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok) throw new Error(`${key} ${response.status}`);
        return [key, payload];
      }));
      settled.forEach((result) => {
        if (result.status !== "fulfilled") return;
        const [key, payload] = result.value;
        if (key === "status") { state.status = payload.status || {}; updateRunningIndicator(); }
        else if (key === "tasks") {
          const nextTasks = payload.incidents || [];
          observeFaultSignals(nextTasks);
          state.tasks = nextTasks;
          state.faultTotal = Number(payload.total || nextTasks.length);
        } else if (key === "newsRuns") state.newsRuns = (payload.runs || []).filter((run) => run.task_kind === "strategic-news");
        else if (key === "crawlRuns") state.crawlRuns = payload.runs || [];
        else if (key === "scheduler") state.schedulerOverview = payload;
        else if (key === "intelligence") state.executiveIntelligence = payload;
      });
      const selectedRuns = selectedNewsRuns();
      const selectedRunIds = selectedRuns.map((run) => run.crawl_run_id);
      await loadNewsRuns(selectedRunIds, { force: true, quiet: true });
      state.newsLiveReviewTick += 1;
      if (state.newsLiveReviewTick % 4 === 0) {
        try { state.newsReviewSheet = await fetchNewsReviewSheetSnapshot(); } catch (_error) { /* keep the last complete snapshot */ }
      }
      const nextSignature = newsLiveRenderSignature();
      if (nextSignature !== state.newsLiveSignature) {
        const dialogOpen = document.querySelector("#newsLineageDialog")?.open;
        if (!dialogOpen) {
          state.newsLiveSignature = nextSignature;
          if (!patchNewsLiveView()) renderNews({ preserveView: true });
        }
      }
    } catch (error) {
      console.warn("News live refresh unavailable", error);
    } finally {
      state.newsLiveRefreshInFlight = false;
    }
  }

  function startNewsLiveRefresh() {
    if (state.newsLivePollTimer || !can("news")) return;
    state.newsLiveSignature = newsLiveRenderSignature();
    state.newsLivePollTimer = window.setInterval(refreshNewsLiveData, 4000);
    window.addEventListener("workspace-tab-change", (event) => {
      if (event.detail?.tab === "news") refreshNewsLiveData();
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible" && activeWorkspaceModule() === "news") refreshNewsLiveData();
    });
  }

  function renderReports(kind) {
    const weekly = kind === "weekly";
    const panel = document.querySelector(`[data-workspace-panel="${kind}"]`);
    panel.innerHTML = `<div class="workspace-module-inner">
      <div class="workspace-grid"><div class="workspace-report-host" id="workspaceReportHost-${kind}"></div>
      <aside class="workspace-report-side" id="workspaceReportSide-${kind}">${reportPreviewPlaceholder()}</aside></div></div>`;
    state.activeReportPreview[kind] = "";
    const outputBlock = document.querySelector(weekly ? "#weeklyOutputBlock" : "#performanceOutputBlock");
    if (outputBlock) {
      outputBlock.hidden = false;
      outputBlock.classList.add("workspace-inline-report-block");
      panel.querySelector(`#workspaceReportHost-${kind}`)?.appendChild(outputBlock);
      outputBlock.querySelector(".output-tabs")?.setAttribute("hidden", "");
      const generateButton = document.querySelector(weekly ? "#generateButtonSecondary" : "#generatePerformanceButton");
      if (generateButton) outputBlock.querySelector(".output-actions")?.prepend(generateButton);
    }
  }

  function reportPreviewPlaceholder() {
    return `<section class="workspace-panel report-preview is-placeholder" data-report-preview aria-label="PDF 预览区">
      <div class="report-preview-guide" role="status">
        <div class="report-preview-guide-icons" aria-hidden="true">
          <span><svg viewBox="0 0 48 48"><path d="M13 5h15l8 8v30H13z"/><path d="M28 5v9h8M19 23h12M19 29h12M19 35h8"/></svg></span>
          <i><svg viewBox="0 0 24 24"><path d="m5 12 14 0M14 7l5 5-5 5"/></svg></i>
          <span><svg viewBox="0 0 48 48"><rect x="7" y="8" width="34" height="32" rx="3"/><path d="M7 17h34M13 13h.01M18 13h.01M23 13h.01M15 24h18M15 30h14"/></svg></span>
        </div>
        <strong>选择一份报告预览</strong>
        <p>点击左侧报告行，在这里查看对应的 PDF 文件</p>
      </div>
    </section>`;
  }

  function reportKindForPath(path) {
    const item = (state.status?.outputs || []).find((output) => output.path_str === path);
    if (!item) return null;
    if (item.reportType === "weekly") return { item, kind: "weekly" };
    if (item.reportType === "carrier-performance") return { item, kind: "performance" };
    return null;
  }

  function previewShell(item, body, { error = false } = {}) {
    return `<section class="workspace-panel report-preview${error ? " has-error" : ""}" data-report-preview>
      <header class="report-preview-header"><div><strong title="${esc(item.name)}">${esc(item.name)}</strong><span>PDF 预览</span></div><div class="report-preview-actions">
        <button type="button" data-report-editor-path="${esc(item.path_str)}" aria-label="全屏编辑 ${esc(item.name)}" title="全屏编辑 Word 内容"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg></button>
        <button type="button" data-report-preview-expand aria-label="放大预览" title="放大预览"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button>
      </div></header><div class="report-preview-viewport">${body}</div></section>`;
  }

  function reportPreviewPdfUrl(item) {
    const base = String(item.name || "").replace(/\.docx$/i, "");
    const bytes = new TextEncoder().encode(base);
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    const key = btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    return `/static/report-previews/${key}.pdf`;
  }

  function setReportPreviewRowState(kind, path = "") {
    document.querySelectorAll(`#workspaceReportHost-${kind} .file-row[data-path]`).forEach((row) => {
      const active = row.dataset.path === path;
      row.classList.toggle("is-previewing", active);
      row.setAttribute("aria-pressed", String(active));
      row.setAttribute("aria-label", `${active ? "取消预览" : "预览报告"} ${row.dataset.path || ""}`);
    });
  }

  function clearReportPreview(kind) {
    state.previewRequest[kind] += 1;
    state.activeReportPreview[kind] = "";
    setReportPreviewRowState(kind);
    const side = document.querySelector(`#workspaceReportSide-${kind}`);
    if (side) side.innerHTML = reportPreviewPlaceholder();
    document.body.classList.remove("has-maximized-report-preview");
  }

  async function showReportPreview(path) {
    const resolved = reportKindForPath(path);
    if (!resolved) return;
    const { item, kind } = resolved;
    const side = document.querySelector(`#workspaceReportSide-${kind}`);
    if (!side) return;
    if (state.activeReportPreview[kind] === path) {
      clearReportPreview(kind);
      return;
    }
    const requestId = ++state.previewRequest[kind];
    state.activeReportPreview[kind] = path;
    setReportPreviewRowState(kind, path);
    side.innerHTML = previewShell(item, '<div class="report-preview-loading" role="status">正在读取 PDF 版式预览…</div>');
    try {
      const pdfUrl = reportPreviewPdfUrl(item);
      const response = await fetch(pdfUrl, { method: "HEAD", cache: "no-store" });
      if (!response.ok) throw new Error("这份历史报告尚未生成 PDF 预览");
      if (requestId !== state.previewRequest[kind]) return;
      const viewport = side.querySelector(".report-preview-viewport");
      viewport.innerHTML = `<iframe class="report-preview-pdf" src="${esc(pdfUrl)}#toolbar=0&navpanes=0&view=FitH" title="${esc(item.name)} PDF 预览"></iframe>`;
    } catch (error) {
      if (requestId === state.previewRequest[kind]) side.innerHTML = previewShell(item, `<div class="report-preview-empty" role="status">${esc(error.message || "报告暂时无法预览")}<br><a href="${esc(safeUrl(item.url, { allowOutput: true }))}">下载原始 Word</a></div>`, { error: true });
    }
  }

  function renderAi() {
    const panel = document.querySelector('[data-workspace-panel="ai"]');
    panel.innerHTML = `<div class="workspace-embedded-host" id="workspaceAiHost"></div>`;
  }

  function taskTime(task) {
    return String(task.occurred_at_hkt || task.started_at_hkt || task.heartbeat_at_hkt || task.completed_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "").slice(0, 19) || "暂无记录";
  }

  function taskLabel(kind) {
    return ({ crawl: "定期数据爬虫", "strategic-news": "战略新闻监测", "four-database-source-discovery": "01:00四库资料搜索", "weekly-report": "战略周报生成", "carrier-performance": "业绩摘要生成", "executive-intelligence-refresh": "四域数据刷新", "audio-generation": "音频摘要生成" })[kind] || kind || "后台任务";
  }

  function faultSortableHeader(key, label) {
    const active = state.faultSort.key === key;
    const direction = active ? state.faultSort.direction : "none";
    const ariaSort = active ? (direction === "asc" ? "ascending" : "descending") : "none";
    return `<th aria-sort="${ariaSort}"><button class="fault-sort-button ${active ? "is-active" : ""}" type="button" data-fault-sort="${key}" aria-label="${esc(label)}，当前${active ? (direction === "asc" ? "升序" : "降序") : "未排序"}">${esc(label)}<i aria-hidden="true"></i></button></th>`;
  }

  function renderFaultMonitor() {
    const panel = document.querySelector('[data-workspace-panel="fault"]');
    const tasks = state.tasks || [];
    const kinds = [...new Set(tasks.map((task) => task.kind).filter(Boolean))];
    panel.innerHTML = `<div class="workspace-module-inner fault-monitor"><section class="workspace-panel fault-workbench">
      <header class="fault-toolbar"><div class="fault-total"><span>报警总数</span><strong id="faultResultCount">0</strong><em>条</em></div><div class="fault-filter-row">
        <label>状态<select data-fault-filter="status"><option value="all">全部记录</option><option value="attention">需要处理</option><option value="completed">已结案</option></select></label>
        <label>任务类型<select data-fault-filter="kind"><option value="all">全部任务</option>${kinds.map((kind) => `<option value="${esc(kind)}">${esc(taskLabel(kind))}</option>`).join("")}</select></label>
        <label class="fault-search">搜索<input type="search" data-fault-filter="query" placeholder="任务、原因或阶段"></label>
        <button class="workspace-button" type="button" data-refresh-fault>刷新</button>
        <div class="operational-report-control is-fault" aria-label="导出报警统计报告"><label>PDF 报告<select data-alert-report-period><option value="daily">日报</option><option value="weekly">周报</option><option value="monthly">月报</option><option value="annual">年报</option></select></label><button class="workspace-button" type="button" data-download-alert-report>导出 PDF</button></div>
      </div></header>
      <div class="fault-action-feedback" id="faultActionFeedback" role="status" aria-live="polite" aria-atomic="true" hidden></div>
      <div class="workspace-table-wrap fault-table-wrap" tabindex="0" aria-label="报警记录列表，可滚动"><table class="workspace-table fault-table"><thead><tr><th>处理确认</th>${faultSortableHeader("status", "状态")}${faultSortableHeader("severity", "紧急程度")}${faultSortableHeader("task", "报警任务")}<th>报警原因</th><th>解决原因</th>${faultSortableHeader("handler", "处理主体")}${faultSortableHeader("time", "发生时间")}<th>处理时间</th><th>详情</th></tr></thead><tbody id="faultTableBody"></tbody></table></div>
      <footer class="fault-monitor-footer"><span class="fault-monitor-note" id="faultMonitorStatus" role="status" aria-live="polite"></span></footer>
    </section><dialog class="fault-detail" id="faultDetail"><form method="dialog"><button aria-label="关闭详情">×</button></form><div id="faultDetailBody"></div></dialog></div>`;
    panel.querySelector('[data-fault-filter="status"]').value = state.faultFilters.status;
    panel.querySelector('[data-fault-filter="kind"]').value = state.faultFilters.kind;
    panel.querySelector('[data-fault-filter="query"]').value = state.faultFilters.query;
    renderFaultRows();
    renderFaultFeedback();
  }

  function renderFaultFeedback() {
    const feedback = document.querySelector("#faultActionFeedback");
    if (!feedback) return;
    const current = state.faultFeedback;
    feedback.hidden = !current;
    feedback.className = `fault-action-feedback${current ? ` is-${current.tone || "info"}` : ""}`;
    feedback.setAttribute("role", current?.tone === "error" ? "alert" : "status");
    feedback.setAttribute("aria-live", current?.tone === "error" ? "assertive" : "polite");
    feedback.innerHTML = current ? `<i aria-hidden="true"></i><span><strong>${esc(current.title)}</strong><small>${esc(current.detail)}</small></span>` : "";
  }

  function faultStatus(task) {
    if (task.handler_name) return { key: "completed", label: task.handler_source === "feishu_robot" ? "机器人处理" : "人工修复", tone: "is-ok" };
    if (task.incident_status === "open") return { key: "attention", label: "待处理", tone: "is-alert" };
    if (task.incident_status === "recovery_pending" || task.resolution_status === "awaiting_evidence") return { key: "attention", label: "待验证", tone: "is-running" };
    if (task.incident_status === "resolved") return { key: "completed", label: task.resolution_type_label || task.phase || "已结案", tone: "is-ok" };
    if (task.interrupted) return { key: "attention", label: "中断", tone: "is-alert" };
    if (task.run_status === "failed") return { key: "attention", label: "失败", tone: "is-alert" };
    if (task.run_status === "running") return { key: "running", label: "运行中", tone: "is-running" };
    if (task.run_status === "cutoff") return { key: "completed", label: "已截止", tone: "is-muted" };
    return { key: "completed", label: "已完成", tone: "is-ok" };
  }

  function faultCause(task) {
    const status = faultStatus(task);
    if (task.source === "project-monitor") return task.alarm_reason || task.error || task.summary || "监控账本未记录具体故障原因。";
    if (status.key === "running") return task.progress_detail || task.status_detail || `任务正在${task.phase || "运行"}，当前未记录故障。`;
    if (status.key === "completed") return task.status_detail || task.progress_detail || "任务已正常完成，未记录故障原因。";
    return task.error || task.warning || task.status_detail || task.progress_detail || task.detail || task.message || "任务归档未记录具体故障原因，请查看运行日志。";
  }

  function faultResolutionReason(task) {
    if (task.resolution_reason) return task.resolution_reason;
    if (task.recovery_cause) return task.recovery_cause;
    if (task.incident_status === "open") return "尚未结案，等待处理或恢复证据。";
    if (task.incident_status === "recovery_pending" || task.resolution_status === "awaiting_evidence") return "告警条件当前未再出现，但正向恢复证据不足，暂不判定已恢复。";
    if (task.handler_name) return task.handler_source === "feishu_robot"
      ? "已由项目监控机器人标记处理；飞书主表与 App 状态已同步。"
      : "已由人工标记修复；本次记录没有填写结构化解决原因。";
    if (task.incident_status === "resolved" && !task.resolution_type) return "历史记录未保存结构化解决原因，不能据此判断为自动恢复。";
    return task.verification_summary || "尚未记录解决原因。";
  }

  function faultSeverity(task) {
    const code = String(task.severity || "").toUpperCase();
    const label = task.severity_label || ({ P1: "紧急", P2: "高", P3: "中" })[code] || "";
    return { code, label, rank: ({ P1: 1, P2: 2, P3: 3 })[code] || 9 };
  }

  function faultHandler(task) {
    if (task.handler_name) return task.handler_name;
    if (task.incident_status === "resolved") return "监控验证器";
    return task.incident_status === "open" ? "待认领" : "—";
  }

  function faultHandlerAvatar(task) {
    if (!task.handler_name && task.incident_status === "resolved") {
      return `<span class="fault-handler-avatar is-system" title="监控验证器·${esc(task.phase || "已验证结案")}" aria-label="结案验证：${esc(task.phase || "已验证结案")}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v2M8 3h8M6.5 7.5h11a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-11a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2Z"/><circle cx="9" cy="12" r="1"/><circle cx="15" cy="12" r="1"/><path d="M8.5 15.5h7"/></svg></span>`;
    }
    if (!task.handler_name) return "—";
    const raw = String(task.handler_avatar_url || "").trim();
    let image = "";
    try {
      if (!raw) throw new Error("missing avatar URL");
      const url = new URL(raw, location.origin);
      if (["http:", "https:"].includes(url.protocol)) image = `<img src="${esc(url.href)}" alt="" />`;
    } catch (_error) { image = ""; }
    return `<span class="fault-handler-avatar" title="${esc(task.handler_name)}" aria-label="处理人：${esc(task.handler_name)}">${image || esc(String(task.handler_name).slice(0, 1))}</span>`;
  }

  function faultSortValue(row, key) {
    if (key === "status") return ({ attention: 1, running: 2, completed: 3 })[row.status.key] || 9;
    if (key === "severity") return faultSeverity(row.task).rank;
    if (key === "task") return row.task.title || taskLabel(row.task.kind);
    if (key === "handler") return faultHandler(row.task);
    return row.task.occurred_at_hkt || row.task.started_at_hkt || row.task.heartbeat_at_hkt || row.task.completed_at_hkt || "";
  }

  function faultSolutions(task) {
    if (Array.isArray(task.suggestions) && task.suggestions.length) return task.suggestions;
    const status = faultStatus(task);
    const cause = faultCause(task);
    if (status.key === "running") return ["继续观察任务心跳和当前阶段。", "只有心跳停止或超过任务正常时长后，才按异常任务处理。"];
    if (status.key === "completed") return ["当前无需处理。", "如业务结果仍未出现，请核对输出归档、发布时间和后续页面刷新状态。"];
    if (task.interrupted || /重启|进程已不存在|中断/.test(cause)) return ["确认中断时的最后阶段和最后心跳，判断是否已有部分结果归档。", "检查后续同类型调度是否已经成功接续，避免重复处理已完成部分。", "确需补跑时，通过原任务入口或安全调度机制执行，并在完成后核对归档状态。"];
    if (task.kind === "strategic-news") return ["先查看运行证据中的首个错误和最后成功阶段。", "修复对应的数据源、模型审核或飞书回读问题后，通过原战略新闻调度入口重试。", "重试完成后核对审核、去重、飞书回读和归档是否全部通过。"];
    return ["查看运行证据中的首个错误，确认失败发生的阶段。", "修复对应配置、数据源或依赖后，通过原任务入口重试。", "重试后确认任务状态、输出归档和下游页面均已恢复。"];
  }

  function renderFaultRows() {
    const body = document.querySelector("#faultTableBody");
    if (!body) return;
    const query = state.faultFilters.query.trim().toLowerCase();
    const rows = state.tasks.map((task, index) => ({ task, index, status: faultStatus(task) })).filter(({ task, status }) => {
      if (state.faultFilters.status !== "all" && status.key !== state.faultFilters.status) return false;
      if (state.faultFilters.kind !== "all" && task.kind !== state.faultFilters.kind) return false;
      const routeSearchText = (Array.isArray(task.affected_routes) ? task.affected_routes : []).map((route) => `${route?.label || ""} ${route?.reason || ""}`).join(" ");
      return !query || [task.title, task.scope, task.phase, task.alarm_type, task.alarm_reason, task.summary, task.error, task.impact, task.resolution_type_label, task.resolution_reason, task.recovery_cause, task.verification_summary, routeSearchText, task.kind].some((value) => String(value || "").toLowerCase().includes(query));
    });
    const collator = new Intl.Collator("zh-CN", { numeric: true, sensitivity: "base" });
    const direction = state.faultSort.direction === "asc" ? 1 : -1;
    rows.sort((left, right) => {
      const a = faultSortValue(left, state.faultSort.key);
      const b = faultSortValue(right, state.faultSort.key);
      const compared = typeof a === "number" && typeof b === "number" ? a - b : collator.compare(String(a), String(b));
      return compared ? compared * direction : left.index - right.index;
    });
    const filtersActive = state.faultFilters.status !== "all" || state.faultFilters.kind !== "all" || Boolean(query);
    document.querySelector("#faultResultCount").textContent = number(filtersActive ? rows.length : state.faultTotal || rows.length);
    body.innerHTML = rows.length ? rows.map(({ task, index, status }) => {
      const severity = faultSeverity(task);
      const canResolve = task.source === "project-monitor" && task.incident_id && window.CMHKAuth?.user?.authProvider === "feishu";
      const checked = Boolean(task.handler_name);
      const closedByMonitor = task.incident_status === "resolved" && !checked;
      const resolving = state.faultFeedback?.incidentId === task.incident_id && state.faultFeedback?.tone === "progress";
      const resolveTitle = resolving ? "正在匹配登录身份并同步飞书" : task.handler_name ? `已由${faultHandler(task)}处理并同步飞书` : task.incident_status === "resolved" ? `监控已按证据结案：${task.phase || "已验证"}` : canResolve ? "记录人工修复并同步原飞书消息" : "请使用飞书账号登录后记录人工修复";
      const handlerTimeLabel = task.handler_source === "feishu_robot" ? "机器人" : "人工";
      const repairTimes = `<small>结案 · ${esc(task.resolved_at_hkt || task.completed_at_hkt || "—")}</small><small>${handlerTimeLabel} · ${esc(task.manual_repaired_at_hkt || "—")}</small>`;
      return `<tr ${resolving ? 'class="fault-row is-resolving"' : 'class="fault-row"'} tabindex="0" role="button" aria-label="查看${esc(task.title || taskLabel(task.kind))}详情" data-fault-detail="${index}"><td class="fault-resolve-cell"><input type="checkbox" data-fault-resolve="${esc(task.incident_id || "")}" aria-label="${esc(resolveTitle)}" title="${esc(resolveTitle)}" ${checked || resolving ? "checked" : ""} ${checked || resolving || closedByMonitor || !canResolve ? "disabled" : ""}${resolving ? ' aria-busy="true"' : ""}></td><td><span class="fault-status ${resolving ? "is-running" : status.tone}"><i></i>${resolving ? "处理中" : status.label}</span></td><td>${severity.code ? `<span class="fault-severity is-${severity.code.toLowerCase()}">${esc(severity.code)} · ${esc(severity.label)}</span>` : "—"}</td><td><strong>${esc(task.title || taskLabel(task.kind))}</strong><small>${esc(task.scope || taskLabel(task.kind))}</small></td><td><span class="fault-cause">${esc(faultCause(task))}</span><small>${esc(task.alarm_type || "未分类告警")}</small></td><td><span class="fault-resolution-cause">${esc(faultResolutionReason(task))}</span><small>${esc(task.resolution_type_label || task.phase || "尚未结案")}</small></td><td class="fault-handler">${faultHandlerAvatar(task)}</td><td>${esc(taskTime(task))}</td><td class="fault-repair-times">${repairTimes}</td><td><span class="fault-open-label">查看</span></td></tr>`;
    }).join("") : '<tr><td colspan="10" class="fault-empty">没有符合筛选条件的记录。</td></tr>';
  }

  async function openFaultDetail(index) {
    const task = state.tasks[index];
    const dialog = document.querySelector("#faultDetail");
    const body = document.querySelector("#faultDetailBody");
    if (!task || !dialog || !body) return;
    const status = faultStatus(task);
    const severity = faultSeverity(task);
    const details = [["报警类型", task.alarm_type || "未分类告警"], ["紧急程度", severity.code ? `${severity.code} · ${severity.label}` : "—"], ["处理或验证主体", faultHandler(task)], ["任务类型", taskLabel(task.kind)], ["当前阶段", task.phase || "未记录"], ["解决类型", task.resolution_type_label || "尚未结案"], ["发生时间", taskTime(task)], ["证据结案时间", task.resolved_at_hkt || task.completed_at_hkt || "—"], [task.handler_source === "feishu_robot" ? "机器人处理时间" : "人工修复时间", task.manual_repaired_at_hkt || "—"], ["影响范围", task.impact || task.scope || "未记录"], ["告警LLM", task.diagnosis_model || "—"], ["结案LLM", task.resolution_model || "—"]];
    const confirmedFacts = Array.isArray(task.confirmed_facts) ? task.confirmed_facts.filter(Boolean) : [];
    const inferences = Array.isArray(task.inferences) ? task.inferences.filter(Boolean) : [];
    const affectedRoutes = Array.isArray(task.affected_routes) ? task.affected_routes.filter((route) => route && typeof route === "object") : [];
    const routeImpactLabels = { interrupted: "中断", degraded: "降级", at_risk: "有风险" };
    const routeConfidenceLabels = { high: "高置信", medium: "中置信", low: "低置信" };
    const resolutionEvidence = Array.isArray(task.resolution_evidence) ? task.resolution_evidence.filter(Boolean) : [];
    const resolutionAction = task.resolution_action && typeof task.resolution_action === "object" ? task.resolution_action : {};
    const actionSummary = resolutionAction.performed ? `已执行：${resolutionAction.type || "未命名动作"}` : "未执行自动修复动作";
    body.innerHTML = `<header><div><span class="fault-status ${status.tone}"><i></i>${status.label}</span><h2>${esc(task.title || taskLabel(task.kind))}</h2></div><time>${esc(taskTime(task))}</time></header>
      <section class="fault-detail-section fault-reason"><h3>报警原因 · ${esc(task.alarm_type || "未分类告警")}</h3><p>${esc(faultCause(task))}</p>${task.alarm_trigger_summary && task.alarm_trigger_summary !== faultCause(task) ? `<small>触发摘要：${esc(task.alarm_trigger_summary)}</small>` : ""}</section>
      ${confirmedFacts.length ? `<section class="fault-detail-section"><h3>已确认事实</h3><ul>${confirmedFacts.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}
      ${inferences.length ? `<section class="fault-detail-section is-inference"><h3>分析推断</h3><ul>${inferences.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}
      ${task.diagnosis_summary ? `<section class="fault-detail-section"><h3>LLM 告警总结</h3><p>${esc(task.diagnosis_summary)}</p><small>模型：${esc(task.diagnosis_model || "—")} · 来源：${esc(task.diagnosis_source || "未记录")}</small></section>` : ""}
      <section class="fault-detail-section fault-route-impact"><h3>受影响线路 · LLM 受限复核</h3>${affectedRoutes.length ? `<div>${affectedRoutes.map((route) => `<article class="is-${esc(route.impact || "at_risk")}"><header><strong>${esc(route.label || route.route_id || "未命名线路")}</strong><span>${esc(routeImpactLabels[route.impact] || "待核对")} · ${esc(routeConfidenceLabels[route.confidence] || "置信度未记录")}</span></header><p>${esc(route.reason || "未记录判断依据。")}</p></article>`).join("")}</div>` : `<p>本次告警未识别到与三线监控图直接相关的受影响线路；系统不会把无证据的相邻线路标记为中断。</p>`}<small>模型只能从系统候选线路中选择；仅高置信度中断可触发红色断线。</small></section>
      <section class="fault-detail-section fault-resolution"><h3>解决原因 · ${esc(task.resolution_type_label || "尚未结案")}</h3><p>${esc(faultResolutionReason(task))}</p><small>${esc(actionSummary)}</small></section>
      ${task.resolution_summary ? `<section class="fault-detail-section"><h3>LLM 结案总结</h3><p>${esc(task.resolution_summary)}</p><p><strong>验证结论：</strong>${esc(task.verification_summary || "—")}</p><p><strong>剩余风险：</strong>${esc(task.remaining_risk || "—")}</p><small>模型：${esc(task.resolution_model || "—")}</small></section>` : ""}
      ${resolutionEvidence.length ? `<section class="fault-detail-section"><h3>结案验证证据</h3><ul>${resolutionEvidence.map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>` : ""}
      <section class="fault-detail-section"><h3>${task.incident_status === "open" ? "建议处理方法" : "当时的处理建议"}</h3><ol>${faultSolutions(task).map((item) => `<li>${esc(item)}</li>`).join("")}</ol></section>
      <dl>${details.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
      <details class="fault-evidence"><summary>查看运行证据</summary><pre id="faultEvidenceLog">${esc([...(task.evidence || []), ...(task.resolution_evidence || [])].join("\n") || task.error || "该报警没有更多证据记录。")}</pre></details>`;
    dialog.showModal();
    if (task.source === "project-monitor") return;
    try {
      const response = await fetch(`/api/task-run-log?id=${encodeURIComponent(task.task_id || task.task_run_id || "")}`, { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      const lines = String(payload.content || payload.raw || "").split("\n").filter(Boolean);
      document.querySelector("#faultEvidenceLog").textContent = lines.slice(-80).join("\n") || "该任务没有可读取的日志内容。";
    } catch (error) {
      const evidence = document.querySelector("#faultEvidenceLog");
      if (evidence) evidence.textContent = `运行日志读取失败：${error.message}`;
    }
  }

  async function refreshFaultData({ quiet = false, preserveFeedback = false } = {}) {
    const status = document.querySelector("#faultMonitorStatus");
    if (!quiet && !preserveFeedback) {
      state.faultFeedback = null;
      renderFaultFeedback();
    }
    if (status && !quiet) status.textContent = "正在刷新故障与心跳状态…";
    try {
      const response = await fetch("/api/project-incidents?limit=500", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      const nextTasks = Array.isArray(data.incidents) ? data.incidents : [];
      const newsLineageChanged = JSON.stringify(newsLineageIncidentSignature(state.tasks))
        !== JSON.stringify(newsLineageIncidentSignature(nextTasks));
      observeFaultSignals(nextTasks);
      state.tasks = nextTasks;
      state.faultTotal = Number(data.total || state.tasks.length);
      if (newsLineageChanged && document.querySelector('[data-workspace-tab="news"]')?.classList.contains("is-active")) {
        const dialogOpen = document.querySelector("#newsLineageDialog")?.open;
        if (!dialogOpen) {
          state.newsLiveSignature = newsLiveRenderSignature();
          if (!patchNewsLiveView()) renderNews({ preserveView: true });
        }
      }
      if (!quiet || document.querySelector('[data-workspace-tab="fault"]')?.classList.contains("is-active")) {
        renderFaultMonitor();
        const nextStatus = document.querySelector("#faultMonitorStatus");
        if (nextStatus) nextStatus.textContent = `状态已刷新 · 共 ${number(state.tasks.length)} 条 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
      }
    } catch (error) {
      if (status && !quiet) status.textContent = `状态刷新失败：${error.message}`;
    }
  }

  async function resolveFault(input) {
    const incidentId = String(input.dataset.faultResolve || "");
    const taskIndex = state.tasks.findIndex((task) => task.incident_id === incidentId);
    const task = state.tasks[taskIndex];
    const taskTitle = task?.title || taskLabel(task?.kind) || "该报警";
    input.disabled = true;
    input.setAttribute("aria-busy", "true");
    input.closest(".fault-row")?.classList.add("is-resolving");
    state.faultFeedback = { incidentId, tone: "progress", title: "正在处理报警", detail: `${taskTitle} · 正在匹配登录身份并同步飞书` };
    renderFaultRows();
    renderFaultFeedback();
    try {
      const response = await fetch("/api/project-incidents/resolve", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ incidentId }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
      const operatorName = payload.result?.operator_name || "当前用户";
      if (taskIndex >= 0) {
        state.tasks[taskIndex] = {
          ...state.tasks[taskIndex],
          ...(payload.incident || {}),
          handler_name: operatorName,
          manual_repaired_at_hkt: payload.result?.handled_at_hkt || "",
        };
      }
      state.faultFeedback = { incidentId, tone: "success", title: "人工修复已记录", detail: `${taskTitle} · ${operatorName} · 原飞书消息更新及回读已确认` };
      renderFaultRows();
      renderFaultFeedback();
      await refreshFaultData({ quiet: true, preserveFeedback: true });
    } catch (error) {
      state.faultFeedback = { incidentId, tone: "error", title: "处理失败，未改变报警状态", detail: `${taskTitle} · ${error.message}` };
      renderFaultRows();
      renderFaultFeedback();
    }
  }

  function renderEmbeddedShells() {
    const log = document.querySelector('[data-workspace-panel="log"]');
    const review = document.querySelector('[data-workspace-panel="review"]');
    log.innerHTML = `<div class="workspace-embedded-host" id="workspaceLogHost"></div>`;
    review.innerHTML = `<div class="workspace-embedded-host" id="workspaceReviewHost"></div>`;
  }

  function setupEmbeddedSurfaces() {
    const chat = document.querySelector("#chatModal");
    const log = document.querySelector("#logModal");
    const review = document.querySelector("#newsReviewWorkspace");
    if (chat) {
      chat.classList.add("workspace-inline-surface");
      document.querySelector("#workspaceAiHost")?.appendChild(chat);
    }
    if (log) {
      log.classList.add("workspace-inline-surface");
      document.querySelector("#workspaceLogHost")?.appendChild(log);
    }
    if (review) {
      review.classList.add("workspace-inline-review");
      document.querySelector("#workspaceReviewHost")?.appendChild(review);
    }
  }

  function syncEmbeddedVisibility(target) {
    const chat = document.querySelector("#chatModal");
    const log = document.querySelector("#logModal");
    const review = document.querySelector("#newsReviewWorkspace");
    if (chat) chat.hidden = target !== "ai";
    if (target === "log" && log?.hidden) document.querySelector("#logButton")?.click();
    if (log) log.hidden = target !== "log";
    if (target === "review" && review?.hidden) document.querySelector("#openNewsReviewSheetButton")?.click();
    if (review) review.hidden = target !== "review";
    if (target !== "review") document.body.classList.remove("news-review-open");
  }

  function setupNavCollapse() {
    const layout = document.querySelector("#workspaceLayout");
    const button = document.querySelector("#workspaceNavCollapse");
    if (!layout || !button) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let motionTimer = 0;
    const clearMotion = () => {
      if (motionTimer) window.clearTimeout(motionTimer);
      motionTimer = 0;
      layout.classList.remove("is-nav-positioning", "is-nav-transitioning");
      button.removeAttribute("aria-busy");
      layout.style.removeProperty("--workspace-nav-motion-x");
      layout.style.removeProperty("--workspace-nav-motion-y");
      layout.style.removeProperty("--workspace-nav-motion-scale");
    };
    const apply = (collapsed) => {
      layout.classList.toggle("is-nav-collapsed", collapsed);
      button.setAttribute("aria-expanded", String(!collapsed));
      button.setAttribute("aria-label", collapsed ? "展开项目导航" : "收回项目导航");
      button.title = collapsed ? "展开项目导航" : "收回项目导航";
    };
    const animateTo = (collapsed, { fromRect = null } = {}) => {
      const first = fromRect || button.getBoundingClientRect();
      clearMotion();
      apply(collapsed);
      if (reducedMotion.matches) return;
      const last = button.getBoundingClientRect();
      const offsetX = first.left + first.width / 2 - (last.left + last.width / 2);
      const offsetY = first.top + first.height / 2 - (last.top + last.height / 2);
      if (Math.abs(offsetX) < 1 && Math.abs(offsetY) < 1) return;
      layout.style.setProperty("--workspace-nav-motion-x", `${offsetX}px`);
      layout.style.setProperty("--workspace-nav-motion-y", `${offsetY}px`);
      layout.style.setProperty("--workspace-nav-motion-scale", String(first.width / last.width));
      layout.classList.add("is-nav-positioning");
      button.setAttribute("aria-busy", "true");
      button.getBoundingClientRect();
      requestAnimationFrame(() => {
        layout.classList.add("is-nav-transitioning");
        layout.classList.remove("is-nav-positioning");
      });
      motionTimer = window.setTimeout(() => {
        clearMotion();
      }, 540);
    };
    setWorkspaceNavCollapsed = animateTo;
    apply(localStorage.getItem("cmhk-workspace-nav-collapsed") === "1");
    button.addEventListener("click", () => {
      const collapsed = !layout.classList.contains("is-nav-collapsed");
      animateTo(collapsed);
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
    const newsDatePicker = event.target.closest?.("[data-news-date-select]");
    if (newsDatePicker && typeof newsDatePicker.showPicker === "function") {
      try { newsDatePicker.showPicker(); } catch (_error) { /* Native input remains keyboard-operable. */ }
    }
    const row = event.target.closest(".workspace-report-host .file-row[data-path]");
    if (row && !row.classList.contains("with-select") && !event.target.closest("button, a, input, .file-name-editable")) showReportPreview(row.dataset.path);
    const editPreview = event.target.closest("[data-report-editor-path]");
    if (editPreview) window.CMHKReportEditor?.open(editPreview.dataset.reportEditorPath);
    const expandPreview = event.target.closest("[data-report-preview-expand]");
    if (expandPreview) {
      const preview = expandPreview.closest("[data-report-preview]");
      const expanded = preview.classList.toggle("is-maximized");
      document.body.classList.toggle("has-maximized-report-preview", expanded);
      expandPreview.setAttribute("aria-label", expanded ? "还原预览" : "放大预览");
      expandPreview.title = expanded ? "还原预览" : "放大预览";
    }
    if (event.target.closest("[data-refresh-fault]")) refreshFaultData();
    if (event.target.closest("[data-download-alert-report]")) {
      const period = document.querySelector("[data-alert-report-period]")?.value || "daily";
      window.location.assign(`/api/alert-report.pdf?period=${encodeURIComponent(period)}`);
    }
    const faultSort = event.target.closest("[data-fault-sort]");
    if (faultSort) {
      const key = faultSort.dataset.faultSort;
      state.faultSort = { key, direction: state.faultSort.key === key && state.faultSort.direction === "asc" ? "desc" : "asc" };
      renderFaultMonitor();
    }
    const faultDetail = event.target.closest("[data-fault-detail]");
    if (faultDetail && !event.target.closest("input,button,a,select")) openFaultDetail(Number(faultDetail.dataset.faultDetail));
    if (event.target.closest("[data-open-task-log]")) activateModule("log");
    const jump = event.target.closest("[data-jump-dashboard]");
    if (jump) activateModule("dashboard");
    if (event.target.closest("[data-open-subscriptions]")) activateModule("subscriptions");
    const generate = event.target.closest("[data-generate-report]");
    if (generate) {
      document.querySelector(generate.dataset.generateReport === "weekly" ? "#generateButtonSecondary" : "#generatePerformanceButton")?.click();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (window.CMHKReportEditor?.isOpen()) return;
    const faultRow = event.target.closest?.(".fault-row[data-fault-detail]");
    if (faultRow && !event.target.closest("input,button,a,select") && ["Enter", " "].includes(event.key)) {
      event.preventDefault();
      openFaultDetail(Number(faultRow.dataset.faultDetail));
      return;
    }
    if (event.key === "Escape") {
      const expanded = document.querySelector("[data-report-preview].is-maximized");
      if (expanded) {
        expanded.classList.remove("is-maximized");
        document.body.classList.remove("has-maximized-report-preview");
        const expandButton = expanded.querySelector("[data-report-preview-expand]");
        expandButton?.setAttribute("aria-label", "放大预览");
        if (expandButton) expandButton.title = "放大预览";
        return;
      }
    }
    if (!["Enter", " "].includes(event.key)) return;
    const row = event.target.closest(".workspace-report-host .file-row[data-path]");
    if (!row || row.classList.contains("with-select") || event.target.closest("button, a, input, .file-name-editable")) return;
    event.preventDefault();
    showReportPreview(row.dataset.path);
  });

  const reportRowObserver = new MutationObserver(() => {
    document.querySelectorAll(".workspace-report-host .file-row[data-path]").forEach((row) => {
      const resolved = reportKindForPath(row.dataset.path);
      const active = Boolean(resolved && state.activeReportPreview[resolved.kind] === row.dataset.path);
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.setAttribute("aria-pressed", String(active));
      row.setAttribute("aria-label", `${active ? "取消预览" : "预览报告"} ${row.dataset.path || ""}`);
    });
  });

  window.addEventListener("cmhk-report-saved", (event) => {
    if (!event.detail?.status) return;
    state.status = event.detail.status;
    if (can("weekly")) renderReports("weekly");
    if (can("performance")) renderReports("performance");
  });
  if (document.body) reportRowObserver.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("change", (event) => {
    const faultResolve = event.target.closest("[data-fault-resolve]");
    if (faultResolve) {
      if (faultResolve.checked) resolveFault(faultResolve);
      return;
    }
    const newsDate = event.target.closest("[data-news-date-select]");
    if (newsDate) {
      state.newsSelectedDate = newsDate.value;
      state.newsSelectedStage = "";
      const selected = selectedNewsRuns();
      updateNewsDateUrl(state.newsSelectedDate);
      loadNewsRuns(selected.map((run) => run.crawl_run_id));
      return;
    }
    const filter = event.target.closest("[data-fault-filter]");
    if (!filter || filter.dataset.faultFilter === "query") return;
    state.faultFilters[filter.dataset.faultFilter] = filter.value;
    renderFaultRows();
  });
  document.addEventListener("input", (event) => {
    const filter = event.target.closest('[data-fault-filter="query"]');
    if (!filter) return;
    state.faultFilters.query = filter.value;
    renderFaultRows();
  });

  function renderLoadError(module, label) {
    const panel = document.querySelector(`[data-workspace-panel="${module}"]`);
    panel.innerHTML = `<div class="workspace-module-inner"><div class="workspace-panel workspace-error"><div class="workspace-empty" role="status">${esc(label)}数据暂时无法读取，请稍后刷新。</div></div></div>`;
  }

  function activeWorkspaceModule() {
    return document.querySelector("[data-workspace-tab].is-active")?.dataset.workspaceTab || "";
  }

  function renderWorkspaceModule(module) {
    if (!state.dirtyModules.has(module)) return;
    if (module === "competitor" && state.loadedKeys.has("workbench")) renderCompetitor();
    else if (module === "news" && state.loadedKeys.has("newsRuns")) renderNews();
    else if (module === "weekly" && state.loadedKeys.has("status")) renderReports("weekly");
    else if (module === "performance" && state.loadedKeys.has("status")) renderReports("performance");
    else if (module === "fault" && state.loadedKeys.has("tasks")) renderFaultMonitor();
    else return;
    state.dirtyModules.delete(module);
  }

  function markWorkspaceModulesDirty(...modules) {
    modules.filter((module) => can(module)).forEach((module) => state.dirtyModules.add(module));
    const active = activeWorkspaceModule();
    if (!state.dirtyModules.has(active) || state.renderFrames[active]) return;
    state.renderFrames[active] = requestAnimationFrame(() => {
      state.renderFrames[active] = 0;
      renderWorkspaceModule(active);
    });
  }

  function updateRunningIndicator() {
    const running = Boolean(state.status?.tasks?.hasRunning);
    const runningIndicator = workspaceSignalDot(document.querySelector('[data-workspace-tab="log"]'));
    if (!runningIndicator) return;
    if (running) runningIndicator.dataset.indicatorRunning = "true";
    else delete runningIndicator.dataset.indicatorRunning;
    runningIndicator.hidden = !["indicatorRunning", "indicatorReport", "indicatorSignal"]
      .some((key) => runningIndicator.dataset[key] === "true");
  }

  function applyWorkspacePayload(key, payload) {
    state.loadedKeys.add(key);
    if (key === "status") {
      state.status = payload.status || {};
      updateRunningIndicator();
      markWorkspaceModulesDirty("news", "weekly", "performance");
    } else if (key === "metrics") state.metrics = payload.data || {};
    else if (key === "briefs") state.briefs = payload.items || [];
    else if (key === "tasks") {
      state.tasks = payload.incidents || [];
      state.faultTotal = Number(payload.total || state.tasks.length);
      observeFaultSignals(state.tasks, { baseline: true });
      markWorkspaceModulesDirty("fault", "news");
    } else if (key === "newsRuns") {
      state.newsRuns = (payload.runs || []).filter((run) => run.task_kind === "strategic-news");
      markWorkspaceModulesDirty("news");
      const initialNewsRuns = selectedNewsRuns();
      if (initialNewsRuns.length) loadNewsRuns(initialNewsRuns.map((run) => run.crawl_run_id));
    } else if (key === "crawlRuns") {
      state.crawlRuns = payload.runs || [];
      markWorkspaceModulesDirty("news");
      const initialCrawlRuns = selectedNewsRuns();
      if (initialCrawlRuns.length) loadNewsRuns(initialCrawlRuns.map((run) => run.crawl_run_id));
    }
    else if (key === "fixedSourceSummary") { state.fixedSourceSummary = payload || {}; markWorkspaceModulesDirty("news"); }
    else if (key === "scheduler") { state.schedulerOverview = payload; markWorkspaceModulesDirty("news"); }
    else if (key === "intelligence") { state.executiveIntelligence = payload; markWorkspaceModulesDirty("news"); }
    else if (key === "reviewSheet") { state.newsReviewSheet = payload; markWorkspaceModulesDirty("news"); }
    else if (key === "newsFallback") { state.newsItemFallback = payload || {}; markWorkspaceModulesDirty("news"); }
    else if (key === "workbench") { state.competitorData = payload; markWorkspaceModulesDirty("competitor"); }
  }

  function validNewsReviewSnapshot(payload) {
    return Boolean(payload && Array.isArray(payload.headers) && Array.isArray(payload.rows));
  }

  function compactNewsReviewSnapshot(payload) {
    const requiredHeaders = [
      "检索日期", "纳入滚动栏", "是否纳入滚动", "纳入周报", "是否纳入周报", "同步状态",
      "新闻标题（AI）", "内容简介（AI）", "来源媒体", "发布时间", "原文链接", "分类", "入池理由",
    ];
    const indexes = requiredHeaders
      .map((header) => ({ header, index: payload.headers.indexOf(header) }))
      .filter((item) => item.index >= 0);
    const coverage = new Date();
    coverage.setDate(coverage.getDate() - 21);
    const snapshotCoverageStart = coverage.toISOString().slice(0, 10);
    const searchDateIndex = payload.headers.indexOf("检索日期");
    return {
      ok: true,
      updatedAt: payload.updatedAt,
      snapshotCoverageStart,
      headers: indexes.map((item) => item.header),
      rows: payload.rows
        .filter((row) => String(row?.values?.[searchDateIndex] || "").slice(0, 10) >= snapshotCoverageStart)
        .map((row) => ({
          rowNumber: row.rowNumber,
          recordId: row.recordId,
          values: indexes.map((item) => row?.values?.[item.index] ?? ""),
          reviewers: row.reviewers,
          reviewer: row.reviewer,
        })),
    };
  }

  async function fetchNewsReviewSheetSnapshot() {
    try {
      const response = await fetch("/api/news-review-sheet", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok || !validNewsReviewSnapshot(payload)) {
        throw new Error(payload.error || `news review sheet ${response.status}`);
      }
      const compact = JSON.stringify(compactNewsReviewSnapshot(payload));
      try { sessionStorage.setItem(NEWS_REVIEW_SNAPSHOT_CACHE_KEY, compact); } catch (_error) { /* cache is optional */ }
      try { localStorage.setItem(NEWS_REVIEW_SNAPSHOT_CACHE_KEY, compact); } catch (_error) { /* cache is optional */ }
      return payload;
    } catch (error) {
      try {
        const cached = JSON.parse(
          sessionStorage.getItem(NEWS_REVIEW_SNAPSHOT_CACHE_KEY)
          || localStorage.getItem(NEWS_REVIEW_SNAPSHOT_CACHE_KEY)
          || "null"
        );
        if (validNewsReviewSnapshot(cached)) {
          return {
            ...cached,
            ok: true,
            snapshotMode: "cached",
            liveReadError: error.message || String(error),
          };
        }
      } catch (_cacheError) { /* report the original live-read failure */ }
      throw error;
    }
  }

  async function loadWorkspaceData() {
    const definitions = [
      ["status", "dashboard", () => fetch("/api/status").then((response) => response.ok ? response.json() : Promise.reject(new Error(`status ${response.status}`)))],
      ["metrics", "competitor", () => fetch("/api/company-metrics").then((response) => response.ok ? response.json() : Promise.reject(new Error(`metrics ${response.status}`)))],
      ["briefs", "dashboard", () => fetch("/api/strategic-briefs").then((response) => response.ok ? response.json() : Promise.reject(new Error(`briefs ${response.status}`)))],
      ["tasks", "fault", () => fetch("/api/project-incidents?limit=500").then((response) => response.ok ? response.json() : Promise.reject(new Error(`incidents ${response.status}`)))],
      ["newsRuns", "news", () => fetch("/api/crawl-runs?taskKind=strategic-news&limit=365").then((response) => response.ok ? response.json() : Promise.reject(new Error(`news runs ${response.status}`)))],
      ["crawlRuns", "log", () => fetch("/api/crawl-runs?limit=500", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`crawl runs ${response.status}`)))],
      ["fixedSourceSummary", "news", () => fetch("/api/fixed-source-summary", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`fixed source summary ${response.status}`)))],
      ["scheduler", "monitoring", () => fetch("/api/scheduler-overview", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`scheduler overview ${response.status}`)))],
      ["intelligence", "dashboard", () => fetch("/api/executive-intelligence", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`executive intelligence ${response.status}`)))],
      ["reviewSheet", "review", fetchNewsReviewSheetSnapshot],
      ["newsFallback", "news", () => fetch("/static/news-run-items.json?v=1").then((response) => response.ok ? response.json() : {})],
      ["workbench", "competitor", () => fetch("/static/competitor-workbench-data.json?v=2").then((response) => response.ok ? response.json() : Promise.reject(new Error(`workbench ${response.status}`)))],
    ];
    const activeDefinitions = definitions.filter(([, module]) => can(module));
    const requests = activeDefinitions.map(async ([key, module, request]) => {
      try {
        applyWorkspacePayload(key, await request());
      } catch (error) {
        console.warn("Workspace module data unavailable", error);
        const coreModule = { workbench: "competitor", newsRuns: "news", status: "weekly", tasks: "fault" }[key];
        if (coreModule && activeWorkspaceModule() === coreModule) renderLoadError(coreModule, { competitor: "竞对", news: "新闻", weekly: "周报", fault: "故障监控" }[coreModule]);
        if (key === "status" && can("performance") && activeWorkspaceModule() === "performance") renderLoadError("performance", "业绩摘要");
      }
    });
    if (can("fault") && !motionState.pollingTimer) {
      motionState.pollingTimer = window.setInterval(() => {
        if (document.visibilityState === "visible") refreshFaultData({ quiet: true });
      }, 30000);
    }
    await Promise.allSettled(requests);
    startNewsLiveRefresh();
  }

  async function initializeWorkspace() {
    try {
      await window.CMHKAuth?.ready;
    } catch (_error) {
      return;
    }
    applyModulePermissions();
    if (can("ai")) renderAi();
    if (can("log") || can("review") || can("ai")) {
      renderEmbeddedShells();
      setupEmbeddedSurfaces();
    }
    setupNavCollapse();
    activateModule(moduleFromLocation(), { updateUrl: false });
    loadWorkspaceData();
  }

  initializeWorkspace();
})();
