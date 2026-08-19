(() => {
  "use strict";

  const MODULES = ["dashboard", "monitoring", "competitor", "news", "weekly", "performance", "review", "subscriptions", "ai", "log", "fault"];
  const state = {
    status: null,
    metrics: null,
    briefs: [],
    tasks: [],
    faultTotal: 0,
    competitorData: null,
    competitorSelection: { companies: [], metric: "", years: 5 },
    competitorInsightRequest: 0,
    competitorInsightController: null,
    newsRuns: [],
    newsSelectedDate: "",
    newsSelectedRunIds: [],
    newsRunDetails: {},
    newsItemFallback: {},
    newsRunRequest: 0,
    newsSelectedStage: "search",
    newsLineageZoom: 1,
    newsLineagePaused: false,
    schedulerOverview: null,
    executiveIntelligence: null,
    previewRequest: { weekly: 0, performance: 0 },
    faultFilters: { status: "all", kind: "all", query: "" },
    faultSort: { key: "time", direction: "desc" },
    faultPage: 1,
    faultPageSize: 100,
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

  function moduleFromLocation() {
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    const requested = params.get("workspace");
    return MODULES.includes(requested) ? requested : "dashboard";
  }

  function activateModule(name, { focus = false, updateUrl = true } = {}) {
    const target = MODULES.includes(name) ? name : "dashboard";
    state.previewRequest.weekly += 1;
    state.previewRequest.performance += 1;
    tabs.forEach((tab) => {
      const selected = tab.dataset.workspaceTab === target;
      tab.classList.toggle("is-active", selected);
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
      if (selected && focus) tab.focus();
    });
    panels.forEach((panel) => { panel.hidden = panel.dataset.workspacePanel !== target; });
    document.querySelectorAll("[data-report-preview].is-maximized").forEach((preview) => preview.classList.remove("is-maximized"));
    document.body.classList.remove("has-maximized-report-preview");
    document.body.classList.toggle("workspace-dashboard-active", target === "dashboard");
    document.body.classList.toggle("workspace-ai-active", target === "ai");
    syncEmbeddedVisibility(target);
    if (target === "fault" && state.tasks.length) refreshFaultData();
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

  function competitorHasCommonMetric(data, companyIds) {
    if (companyIds.length < 2) return true;
    return data.metrics.some((metric) => {
      const cells = data.cells.filter((cell) => companyIds.includes(cell.company) && cell.metric === metric.key);
      return new Set(cells.map((cell) => cell.company)).size === companyIds.length
        && new Set(cells.map((cell) => cell.unit)).size === 1;
    });
  }

  function visibleCompetitorIds(data, selectedCompanies) {
    if (!selectedCompanies.length) return new Set(data.companies.map((company) => company.id));
    return new Set(data.companies
      .filter((company) => selectedCompanies.includes(company.id) || competitorHasCommonMetric(data, [...selectedCompanies, company.id]))
      .map((company) => company.id));
  }

  function renderCompetitor({ revealedCompanies = [] } = {}) {
    const panel = document.querySelector('[data-workspace-panel="competitor"]');
    const data = state.competitorData || { companies: [], metrics: [], cells: [] };
    const selection = state.competitorSelection;
    const groupKnowledgeLabel = (group) => group === "香港运营商" ? "本地运营商知识库" : "全球重点运营商知识库";
    const groups = data.companies.reduce((map, company) => {
      (map[company.group] ||= []).push(company);
      return map;
    }, {});
    const visibleCompanies = visibleCompetitorIds(data, selection.companies);
    const metricUnit = (metric) => {
      const selectedCells = data.cells.filter((cell) => (!selection.companies.length || selection.companies.includes(cell.company)) && cell.metric === metric.key);
      const units = [...new Set(selectedCells.map((cell) => cell.unit).filter(Boolean))];
      return units.length === 1 ? (metric.unitLabels?.[units[0]] || units[0]) : "按所选竞对确定单位";
    };
    const comparableMetrics = selection.companies.length < 2 ? data.metrics : data.metrics.filter((metric) => {
      const selectedCells = data.cells.filter((cell) => selection.companies.includes(cell.company) && cell.metric === metric.key);
      const coveredCompanies = new Set(selectedCells.map((cell) => cell.company));
      const units = new Set(selectedCells.map((cell) => cell.unit));
      return coveredCompanies.size === selection.companies.length && units.size === 1;
    });
    if (selection.metric && !comparableMetrics.some((metric) => metric.key === selection.metric)) selection.metric = "";
    panel.innerHTML = `<div class="workspace-module-inner competitor-workbench"><section class="workspace-panel competitor-builder">
      <header class="competitor-builder-head"><strong>竞对数据工作台</strong><button class="workspace-button" type="button" data-competitor-clear>清空选择</button></header>
      <div class="competitor-steps">
        <fieldset><legend><i>01</i>选择竞对 <small>至少 2 家，最多 6 家</small></legend>${Object.entries(groups).map(([group, companies]) => [group, companies.filter((company) => visibleCompanies.has(company.id))]).filter(([, companies]) => companies.length).map(([group, companies]) => `<div class="competitor-option-group"><span><b>${esc(group)}</b><small>${esc(groupKnowledgeLabel(group))}</small></span><div>${companies.map((company) => `<label class="${revealedCompanies.includes(company.id) ? "is-appearing" : ""}" data-competitor-option="${esc(company.id)}"><input type="checkbox" value="${esc(company.id)}" data-competitor-company ${selection.companies.includes(company.id) ? "checked" : ""} ${selection.companies.length >= 6 && !selection.companies.includes(company.id) ? "disabled" : ""}><b>${esc(company.label)}</b></label>`).join("")}</div></div>`).join("")}</fieldset>
        <fieldset><legend><i>02</i>选择指标 <small>${selection.companies.length >= 2 ? "仅展示所选竞对同单位可比指标" : "仅展示具备多年记录的指标"}</small></legend><label class="competitor-select"><span>比较数据</span><select data-competitor-metric><option value="">${comparableMetrics.length ? "请选择指标" : "所选竞对暂无共同指标"}</option>${comparableMetrics.map((metric) => `<option value="${esc(metric.key)}" ${selection.metric === metric.key ? "selected" : ""}>${esc(metric.label)} · ${esc(metricUnit(metric))}</option>`).join("")}</select></label></fieldset>
        <fieldset><legend><i>03</i>选择年限 <small>截至最后共同披露年</small></legend><div class="competitor-year-options">${[3,5,10].map((years) => `<label><input type="radio" name="competitor-years" value="${years}" ${selection.years === years ? "checked" : ""}><span>最近 ${years} 年窗口</span></label>`).join("")}<label><input type="radio" name="competitor-years" value="99" ${selection.years === 99 ? "checked" : ""}><span>全部</span></label></div></fieldset>
      </div></section><section class="workspace-panel competitor-result" id="competitorResult"></section></div>`;
    panel.querySelectorAll("[data-competitor-company]").forEach((input) => input.addEventListener("change", () => {
      const previouslyVisible = new Set([...panel.querySelectorAll("[data-competitor-option]")].map((item) => item.dataset.competitorOption));
      const selected = [...panel.querySelectorAll("[data-competitor-company]:checked")].map((item) => item.value).slice(0, 6);
      state.competitorSelection.companies = selected;
      const nextVisible = visibleCompetitorIds(data, selected);
      const disappearing = [...panel.querySelectorAll("[data-competitor-option]")].filter((item) => !nextVisible.has(item.dataset.competitorOption));
      const revealed = [...nextVisible].filter((company) => !previouslyVisible.has(company));
      if (!disappearing.length) {
        renderCompetitor({ revealedCompanies: revealed });
        return;
      }
      panel.querySelectorAll("[data-competitor-company]").forEach((item) => { item.disabled = true; });
      disappearing.forEach((item) => item.classList.add("is-disappearing"));
      panel.querySelectorAll(".competitor-option-group").forEach((group) => {
        const remaining = [...group.querySelectorAll("[data-competitor-option]")].some((item) => nextVisible.has(item.dataset.competitorOption));
        if (!remaining) group.classList.add("is-disappearing");
      });
      window.setTimeout(() => renderCompetitor(), 220);
    }));
    panel.querySelector("[data-competitor-metric]")?.addEventListener("change", (event) => { state.competitorSelection.metric = event.target.value; renderCompetitorResult(); });
    panel.querySelectorAll('[name="competitor-years"]').forEach((input) => input.addEventListener("change", () => { state.competitorSelection.years = Number(input.value); renderCompetitorResult(); }));
    panel.querySelector("[data-competitor-clear]")?.addEventListener("click", () => {
      const currentlyVisible = new Set([...panel.querySelectorAll("[data-competitor-option]")].map((item) => item.dataset.competitorOption));
      state.competitorSelection = { companies: [], metric: "", years: 5 };
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
    const { companies, metric, years } = state.competitorSelection;
    if (companies.length < 2 || !metric) {
      host.innerHTML = `<div class="competitor-empty"><span>01 — 03</span><strong>完成上方选择后生成对比图</strong><p>选择至少两家竞对、一个指标和回看年限；AI 将比较多家公司的竞争位置、分化路径与业务含义。</p></div>`;
      return;
    }
    const data = state.competitorData;
    const metricMeta = data.metrics.find((item) => item.key === metric) || { label: metric, unit: "" };
    const available = data.cells.filter((cell) => companies.includes(cell.company) && cell.metric === metric);
    const availableUnits = [...new Set(available.map((cell) => cell.unit).filter(Boolean))];
    if (availableUnits.length !== 1) {
      host.innerHTML = `<div class="competitor-empty"><span>数据边界</span><strong>所选组合的计量单位不一致</strong><p>请更换竞对或指标；系统不会把不同币种或单位的数据画在同一张对比图中。</p></div>`;
      return;
    }
    const allYears = [...new Set(available.map((cell) => cell.year))].sort((a, b) => a - b);
    const companyYears = companies.map((company) => new Set(available.filter((cell) => cell.company === company).map((cell) => cell.year)));
    const commonYears = allYears.filter((year) => companyYears.every((set) => set.has(year)));
    const commonAnchor = commonYears.at(-1);
    const visibleYears = years === 99
      ? Array.from({ length: (allYears.at(-1) || 0) - (allYears[0] || 0) + 1 }, (_item, index) => allYears[0] + index)
      : commonAnchor ? Array.from({ length: years }, (_item, index) => commonAnchor - years + 1 + index) : [];
    const pointsPerCompany = companies.map((company) => visibleYears.filter((year) => companyYears[companies.indexOf(company)].has(year)).length);
    const sharedVisibleYears = visibleYears.filter((year) => companyYears.every((set) => set.has(year)));
    if (!visibleYears.length || pointsPerCompany.some((count) => count < 2) || sharedVisibleYears.length < 2) {
      host.innerHTML = `<div class="competitor-empty"><span>数据边界</span><strong>所选组合暂无可直接比较的数据</strong><p>请更换竞对或指标；系统不会用缺失值、不同口径或估算值补齐表格。</p></div>`;
      return;
    }
    const lookup = new Map(available.map((cell) => [`${cell.company}|${cell.year}`, cell]));
    const companyMeta = new Map(data.companies.map((item) => [item.id, item]));
    const companyLabel = (company) => companyMeta.get(company)?.label || company;
    const unitLabel = metricMeta.unitLabels?.[availableUnits[0]] || availableUnits[0];
    const chartLegend = companies.map((company, index) => `<span><i style="--series-color:${COMPETITOR_CHART_PALETTE[index % COMPETITOR_CHART_PALETTE.length]}"></i>${esc(companyLabel(company))}</span>`).join("");
    const chart = buildCompetitorChart({ companies, companyLabel, visibleYears, lookup, unit: unitLabel });
    const fallbackInsight = buildCompetitorFallbackInsight({ companies, companyLabel, visibleYears, lookup, unit: unitLabel });
    const rows = visibleYears.map((year) => `<tr><th>${year}</th>${companies.map((company) => { const cell = lookup.get(`${company}|${year}`); return `<td title="${esc(cell ? [cell.period, cell.periodEnd, cell.scope, cell.basis, cell.note].filter(Boolean).join(" · ") : "未披露")}">${cell ? `<strong>${esc(`${competitorComparator(cell.comparator)}${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 2 }).format(cell.value)}`)}</strong><small>${esc([cell.period, cell.periodEnd].filter(Boolean).join(" · "))}</small>${cell.source ? `<a href="${esc(safeUrl(cell.source))}" target="_blank" rel="noreferrer">官方来源</a>` : ""}` : '<span class="competitor-missing">— 未披露</span>'}</td>`; }).join("")}</tr>`).join("");
    const fallbackItems = fallbackInsight.insights.map((item, index) => `<li><b>${["竞争格局", "公司定位", "业务含义"][index]}</b><span>${esc(item.replace(/^(竞争格局|公司定位|业务含义)[：|｜]\s*/, ""))}</span></li>`).join("");
    host.innerHTML = `<header class="workspace-panel-header competitor-result-header"><div><h2>${esc(metricMeta.label)}</h2><span>${esc(unitLabel)} · ${visibleYears[0] || "—"}—${visibleYears.at(-1) || "—"}</span></div><div class="competitor-chart-legend" aria-label="竞对图例">${chartLegend}</div></header>
      <div class="competitor-result-overview">
      ${chart}
      <section class="competitor-insight" id="competitorInsight" role="status" aria-live="polite" aria-busy="false">
        <header class="competitor-insight-header">
          <div class="competitor-insight-identity"><i data-competitor-insight-icon>AI</i><div><b data-competitor-insight-title>AI 竞争洞察</b><small data-competitor-insight-status>当前显示本地数据总结</small></div></div>
          <span class="competitor-insight-badge" data-competitor-insight-badge>LOCAL DATA</span>
        </header>
        <div class="competitor-insight-body">
          <div class="competitor-insight-loading" aria-hidden="true"><span></span><span></span><span></span><span></span></div>
          <ol class="competitor-insight-list" data-competitor-insight-list>${fallbackItems}</ol>
        </div>
      </section></div>
      <details class="competitor-data-details"><summary>查看数据明细与官方来源 <span>${visibleYears.length} 个披露年度</span></summary><div class="workspace-table-wrap"><table class="workspace-table competitor-matrix"><thead><tr><th>披露年度</th>${companies.map((company) => `<th>${esc(companyLabel(company))}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div></details>`;
    requestCompetitorInsight({ companies, metric: { key: metricMeta.key, label: metricMeta.label }, years: visibleYears, evidenceVersion: data.evidenceVersion }, requestId, fallbackInsight);
  }

  function competitorComparator(value) {
    return ({ ">=": "≥", "<=": "≤", "~": "≈", "approx": "≈" })[String(value || "").toLowerCase()] || (value === "=" ? "" : String(value || ""));
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

  function buildCompetitorChart({ companies, companyLabel, visibleYears, lookup, unit }) {
    const width = 960;
    const height = 330;
    const margin = { top: 26, right: 205, bottom: 42, left: 66 };
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
    const lastPoints = companies.map((company) => {
      const points = visibleYears.map((year) => ({ year, cell: lookup.get(`${company}|${year}`) })).filter((item) => Number.isFinite(item.cell?.value));
      return { company, point: points.at(-1) };
    }).filter((item) => item.point).sort((a, b) => y(a.point.cell.value) - y(b.point.cell.value));
    const labelPositions = new Map();
    lastPoints.forEach((item, index) => labelPositions.set(item.company, Math.max(y(item.point.cell.value), index ? labelPositions.get(lastPoints[index - 1].company) + 16 : margin.top + 4)));
    const overflow = Math.max(0, (labelPositions.get(lastPoints.at(-1)?.company) || 0) - (height - margin.bottom - 4));
    if (overflow) lastPoints.forEach((item) => labelPositions.set(item.company, labelPositions.get(item.company) - overflow));
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
      const dots = points.map(({ year, cell }) => { const description = `${companyLabel(company)} · ${cell.period || `${year}年`} · ${competitorComparator(cell.comparator)}${format(cell.value)} ${unit} · ${cell.scope || "以官方披露为准"}`; return `<g class="competitor-chart-point ${cell.comparator && cell.comparator !== "=" ? "is-bound" : ""}" tabindex="0" role="img" aria-label="${esc(description)}"><circle cx="${x(year).toFixed(1)}" cy="${y(cell.value).toFixed(1)}" r="4.5" style="--series-color:${color}"></circle><title>${esc(description)}</title></g>`; }).join("");
      const last = points.at(-1);
      const labelY = labelPositions.get(company);
      const stopped = last && last.year < visibleYears.at(-1) ? `（止于${last.year}）` : "";
      const endLabel = last ? `<g class="competitor-chart-end-label"><path d="M${x(last.year).toFixed(1)},${y(last.cell.value).toFixed(1)} L${(width - margin.right + 10).toFixed(1)},${labelY.toFixed(1)}" style="--series-color:${color}"></path><circle cx="${(width - margin.right + 10).toFixed(1)}" cy="${labelY.toFixed(1)}" r="3" style="--series-color:${color}"></circle><text x="${(width - margin.right + 20).toFixed(1)}" y="${(labelY + 4).toFixed(1)}">${esc(`${companyLabel(company)} ${competitorComparator(last.cell.comparator)}${format(last.cell.value)} ${unit}${stopped}`)}</text></g>` : "";
      return `<g class="competitor-chart-series">${paths}${dots}${endLabel}</g>`;
    }).join("");
    return `<figure class="competitor-chart-card"><div class="competitor-chart-scroll"><svg class="competitor-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="${esc(`所选 ${companies.length} 家竞对在 ${visibleYears[0]} 至 ${visibleYears.at(-1)} 年的趋势对比图`)}">${grid}${years}${series}</svg></div><p>注：按各公司披露年度展示；财年与自然年口径差异请以数据明细中的官方来源为准。</p></figure>`;
  }

  function settleCompetitorInsight(card, { mode, insights, status = "" }) {
    if (!card) return;
    const isAi = mode === "ai";
    const items = (Array.isArray(insights) ? insights : [insights]).map((item) => String(item || "").trim()).filter(Boolean).slice(0, 3);
    card.classList.remove("is-loading", "is-streaming");
    card.classList.toggle("is-ai", isAi);
    card.setAttribute("aria-busy", "false");
    card.querySelector("[data-competitor-insight-icon]").textContent = "AI";
    card.querySelector("[data-competitor-insight-title]").textContent = "AI 竞争洞察";
    card.querySelector("[data-competitor-insight-status]").textContent = status || (isAi ? "内网 AI 已完成真实生成" : "当前显示本地数据总结");
    card.querySelector("[data-competitor-insight-badge]").textContent = isAi ? "COMPETITIVE INSIGHT" : "LOCAL DATA";
    const list = card.querySelector("[data-competitor-insight-list]");
    list.replaceChildren(...items.map((item, index) => {
      const labels = ["竞争格局", "公司定位", "业务含义"];
      const li = document.createElement("li");
      const label = document.createElement("b");
      const copy = document.createElement("span");
      label.textContent = labels[index] || "观察";
      copy.textContent = item.replace(/^(竞争格局|公司分化|公司定位|业务含义|数据格局|共同年度|解读边界)[：|｜]\s*/, "");
      li.append(label, copy);
      return li;
    }));
  }

  function beginCompetitorInsightStream(card) {
    if (!card) return;
    card.classList.remove("is-ai", "is-streaming");
    card.classList.add("is-loading");
    card.setAttribute("aria-busy", "true");
    card.querySelector("[data-competitor-insight-status]").textContent = "正在连接内网 AI";
    card.querySelector("[data-competitor-insight-badge]").textContent = "CONNECTING";
  }

  function renderCompetitorInsightDraft(card, text) {
    const drafts = String(text || "").split(/\n+/).map((item) => item.trim()).filter(Boolean).slice(0, 3);
    if (!card || !drafts.length) return;
    card.classList.remove("is-loading");
    card.classList.add("is-streaming");
    card.querySelector("[data-competitor-insight-status]").textContent = `内网 AI 正在流式生成 · 已收到 ${String(text).length} 字`;
    card.querySelector("[data-competitor-insight-badge]").textContent = "AI STREAM";
    const labels = ["竞争格局", "公司定位", "业务含义"];
    card.querySelector("[data-competitor-insight-list]").replaceChildren(...drafts.map((item, index) => {
      const li = document.createElement("li");
      const label = document.createElement("b");
      const copy = document.createElement("span");
      label.textContent = labels[index];
      copy.textContent = item.replace(/^(竞争格局|公司分化|公司定位|业务含义)[：|｜]\s*/, "");
      li.append(label, copy);
      return li;
    }));
  }

  async function requestLegacyCompetitorInsight(payload, requestId, controller, card) {
    card.classList.add("is-loading");
    card.setAttribute("aria-busy", "true");
    card.querySelector("[data-competitor-insight-status]").textContent = "兼容模式正在生成真实 AI 结果";
    card.querySelector("[data-competitor-insight-badge]").textContent = "GENERATING";
    const response = await fetch("/api/competitor-insight", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requestId: String(requestId), ...payload }), signal: controller.signal });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || !result.ok) throw new Error(result.error || `AI兼容接口 HTTP ${response.status}`);
    if (requestId !== state.competitorInsightRequest) return false;
    settleCompetitorInsight(card, { mode: "ai", insights: result.insights });
    return true;
  }

  async function requestCompetitorInsight(payload, requestId, fallbackInsight) {
    const controller = new AbortController();
    state.competitorInsightController = controller;
    const card = document.querySelector("#competitorInsight");
    beginCompetitorInsightStream(card);
    try {
      const response = await fetch("/api/competitor-insight-stream", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ requestId: String(requestId), ...payload }), signal: controller.signal });
      if (response.status === 404) {
        await requestLegacyCompetitorInsight(payload, requestId, controller, card);
        return;
      }
      if (!response.ok || !response.body) throw new Error(`AI流式接口 HTTP ${response.status}`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let generated = "";
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
            card.querySelector("[data-competitor-insight-status]").textContent = event.message || "内网 AI 正在处理";
            card.querySelector("[data-competitor-insight-badge]").textContent = event.stage === "queue" ? "QUEUED" : "GENERATING";
          } else if (event.type === "delta") {
            generated += String(event.text || "");
            renderCompetitorInsightDraft(card, generated);
          } else if (event.type === "done" && event.ok) {
            completed = true;
            settleCompetitorInsight(card, { mode: "ai", insights: event.insights });
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
        settleCompetitorInsight(card, { mode: "data", insights: fallbackInsight.insights, status: `AI未生成：${error.message || "服务不可用"}；当前显示本地数据总结` });
      }
    } finally {
      if (state.competitorInsightController === controller) state.competitorInsightController = null;
    }
  }

  function newsRunDate(run) {
    return String(run?.started_at_hkt || "").slice(0, 10);
  }

  function newsRunTime(run) {
    return String(run?.started_at_hkt || "").slice(11, 16) || "--:--";
  }

  function logLine(content, prefix) {
    return String(content || "").split("\n").find((line) => line.includes(prefix)) || "";
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
    const discovered = logNumber(content, /新闻发现完成：时间窗内发现\s*(\d+)\s*条/, summary.discovered);
    const gateInput = logNumber(content, /候选确定性门禁：输入\s*(\d+)\s*条/, discovered);
    const gatePassed = logNumber(content, /候选确定性门禁：输入\s*\d+\s*条，通过\s*(\d+)\s*条/, gateInput);
    const aiInput = logNumber(content, /AI审核完成：输入\s*(\d+)\s*条/, gatePassed);
    const aiRetained = logNumber(content, /AI审核完成：输入\s*\d+\s*条，纳入\s*(\d+)\s*条/, summary.ai_retained);
    const aiRejected = logNumber(content, /AI审核完成：[^\n]*排除\s*(\d+)\s*条/, Math.max(0, aiInput - aiRetained));
    const duplicates = logNumber(content, /语义去重完成：[^\n]*重复\s*(\d+)\s*条/, summary.history_duplicates);
    const newCount = logNumber(content, /语义去重完成：[^\n]*保留\s*(\d+)\s*条/, summary.new_count);
    const keywordCount = logNumber(content, /搜索准备：已加载\s*\d+\s*个监控模块、\s*(\d+)\s*个关键词/, 0);
    const pageCount = logNumber(content, /搜索准备：[^\n]*、\s*(\d+)\s*个固定页面来源/, 0);
    const fixedQueries = logNumber(content, /固定监控检索：执行\s*(\d+)\s*条查询/, 0);
    const agentQueries = logNumber(content, /Agentic Search补缺：[^\n]*规划并执行\s*(\d+)\s*条补缺查询/, 0);
    const pageClues = logNumber(content, /定时页面线索合并：读取\s*(\d+)\s*条页面变化线索/, 0);
    const historical = logNumber(content, /语义去重完成：候选\s*\d+\s*条，历史\s*(\d+)\s*条/, 0);
    const readbackCells = logNumber(content, /飞书逐格回读：[^\n]*所有\s*(\d+)\s*个单元格一致/, 0);
    const notificationSent = /群通知完成：通知状态：sent/.test(content) || summary.notification_status === "sent";
    const lines = {
      search: logLine(content, "新闻发现完成"),
      gate: logLine(content, "候选确定性门禁"),
      ai: logLine(content, "AI审核完成"),
      dedupe: logLine(content, "语义去重完成"),
      write: logLine(content, "飞书逐格回读：第 1 次回读通过"),
      push: logLine(content, "群通知完成"),
    };
    const rawStages = [
      { key: "search", label: "线索发现", value: discovered, input: `${keywordCount || "—"} 个关键词 · ${pageCount || "—"} 个固定来源`, lost: 0, details: [`固定监控执行 ${fixedQueries || "—"} 条查询`, `Agentic Search 执行 ${agentQueries || "—"} 条补缺查询`, `合并 ${pageClues || "—"} 条页面变化线索`], evidence: lines.search },
      { key: "gate", label: "确定性门禁", value: gatePassed, input: `${gateInput || discovered} 条候选进入`, lost: Math.max(0, gateInput - gatePassed), details: ["校验时间窗、发布日期、规范化 URL 与基础重复", "不满足硬规则的线索不会消耗 AI 审核额度"], evidence: lines.gate },
      { key: "ai", label: "AI 语义审核", value: aiRetained, input: `${aiInput || gatePassed} 条送审`, lost: aiRejected, details: ["结合竞对、政策、市场、网络与战略相关性逐条判定", `该次运行排除 ${aiRejected} 条；单条异常隔离，不影响其余候选`], evidence: lines.ai },
      { key: "dedupe", label: "历史语义去重", value: newCount, input: `${aiRetained} 条 AI 保留`, lost: duplicates, details: [`与 ${historical || "—"} 条当日历史事件进行语义比对`, `识别 ${duplicates} 条重复事件，保留 ${newCount} 条新增`], evidence: lines.dedupe },
      { key: "write", label: "飞书写入回读", value: newCount, input: `${newCount} 条新增写入`, lost: 0, details: [`逐格回读 ${readbackCells ? number(readbackCells) : "—"} 个单元格`, "只有写入值与回读值完全一致才视为交付成功"], evidence: lines.write },
      { key: "push", label: "群组推送", value: newCount, input: "归档与回读通过后", lost: 0, details: [notificationSent ? "正式群卡片已发送" : "尚未到达推送门禁", "推送发生在审核、去重、写入、回读和归档全部完成之后"], evidence: lines.push },
    ];
    let waiting = false;
    return rawStages.map((stage) => {
      const done = Boolean(stage.evidence) || (stage.key === "push" && notificationSent);
      const status = done ? "done" : waiting ? "pending" : "current";
      if (!done) waiting = true;
      return { ...stage, status };
    });
  }

  function selectedNewsRuns() {
    const dates = [...new Set(state.newsRuns.map(newsRunDate).filter(Boolean))];
    const params = new URLSearchParams(location.hash.replace(/^#/, ""));
    let selectedDate = state.newsSelectedDate || params.get("newsDate") || "";
    if (!dates.includes(selectedDate)) {
      const legacyRunId = String(params.get("newsRuns") || params.get("newsRun") || "").split(",").find(Boolean);
      selectedDate = newsRunDate(state.newsRuns.find((run) => run.crawl_run_id === legacyRunId));
    }
    if (!dates.includes(selectedDate)) selectedDate = dates[0] || "";
    state.newsSelectedDate = selectedDate;
    const selected = state.newsRuns.filter((run) => newsRunDate(run) === selectedDate);
    state.newsSelectedRunIds = selected.map((run) => run.crawl_run_id);
    return selected;
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

  function lineageRunStatus(run) {
    return ({ completed: "已完成", running: "进行中", failed: "已中断" })[run?.run_status] || (run?.run_status ? String(run.run_status) : "配置态");
  }

  function lineageStageStatus(stage) {
    return ({ done: "已完成", current: "进行中", pending: "待执行" })[stage?.status] || "待归档";
  }

  function lineageProcessStep(title, status, input, action, rule, output, next, evidence) {
    return { title, status, input, action, rule, output, next, evidence };
  }

  function globalSchedulerLineageModel(runs, stages) {
    const overview = state.schedulerOverview || {};
    const frequency = overview.frequency_counts || {};
    const latest = overview.latest || {};
    const mainRun = latest.main_crawl || {};
    const newsRun = runs[0] || latest.strategic_news || {};
    const intelligenceRun = latest.four_database_refresh || {};
    const domains = new Map((state.executiveIntelligence?.domains || []).map((domain) => [domain.id, domain]));
    const domainNode = (key, fallbackLabel, position) => {
      const domain = domains.get(key) || {};
      const metric = domain.metric || {};
      return {
        key: `database-${key}`,
        label: domain.title || fallbackLabel,
        value: metric.value === undefined || metric.value === null || metric.value === "" ? "—" : String(metric.value),
        unit: metric.unit || "",
        note: metric.label || "等待质量门禁后的正式数据",
        tone: "mint",
        position,
        details: [domain.context || domain.data_time || "仅展示通过质量检查的数据库记录", `四库刷新：${runCompletionText(intelligenceRun)}`],
        evidence: domain.context || state.executiveIntelligence?.method || intelligenceRun.progress_detail || "四库运行证据暂不可用。",
      };
    };
    const strategicDedupe = stages.find((stage) => stage.key === "dedupe") || { value: 0, lost: 0 };
    const configured = Number(overview.configured_rows || 0);
    const sources = (overview.source_groups || []).filter((item) => Number(item.count || 0) > 0);
    const mainEvidence = [
      `${configured || "—"} 条有效飞书频率配置`,
      ...sources.map((item) => `${item.label} ${number(item.count)} 条`),
      `最近完成 ${runCompletionText(mainRun)}`,
    ];
    const nodes = [
      { key: "strategic", label: "06:00 / 13:30 战略新闻", value: newsRun.run_status === "running" ? "运行中" : "每日2轮", note: `最近完成 ${runCompletionText(newsRun)}`, tone: "cyan", position: [18, 50], details: ["固定时点独立扫描战略新闻", "接收主爬虫产生的页面变化线索"], evidence: newsRun.progress_detail || newsRun.status_detail || newsRun.scope || "战略新闻运行归档" },
      { key: "news-search", label: "线索补缺", value: number((stages.find((stage) => stage.key === "search") || {}).value), unit: "条发现", note: "固定来源 + Agentic + 页面变化", tone: "cyan", position: [365, 50], details: ["固定关键词和页面来源", "对页面变化生成关联查询", "Agentic Search补齐空白"], evidence: (stages.find((stage) => stage.key === "search") || {}).evidence || "等待所选日期的新闻证据" },
      { key: "news-ai", label: "AI审核", value: number((stages.find((stage) => stage.key === "ai") || {}).value), unit: "条纳入", note: "逐条判断战略相关性", tone: "cyan", position: [712, 50], details: ["确定性门禁先筛时间、日期与URL", "AI逐条判断战略价值"], evidence: (stages.find((stage) => stage.key === "ai") || {}).evidence || "等待所选日期的新闻证据" },
      { key: "news-dedupe", label: "历史去重", value: number(strategicDedupe.lost), unit: "条重复", note: `留下 ${number(strategicDedupe.value)} 条新增`, tone: "mint", position: [1059, 50], details: ["与历史事件语义比对", "新增事件进入后续历史记忆"], evidence: strategicDedupe.evidence || "等待所选日期的新闻证据" },
      { key: "news-output", label: "新增新闻", value: number(strategicDedupe.value), unit: "条", note: "审核表 · 推送 · 历史记忆", tone: "focus", position: [1406, 50], details: ["正式写入并回读", "保留的新增事件影响下一轮去重与补缺"], evidence: (stages.find((stage) => stage.key === "push") || {}).evidence || newsRun.progress_detail || "等待所选日期的新闻证据" },
      { key: "main", label: "03:00 主爬虫", value: configured ? number(configured) : "—", unit: "条配置", note: `${number(frequency.daily)}每日 · ${number(frequency.weekly)}每周 · ${number(frequency.monthly)}每月`, tone: "focus", position: [14, 318], details: mainEvidence, evidence: mainRun.status_detail || mainRun.progress_detail || mainEvidence.join("\n") },
      { key: "agent", label: "Agent 证据审核", value: "10", unit: "节点", note: "分类 · 抽取 · 校验 · 仲裁", tone: "cyan", position: [212, 318], details: ["证据接收与来源分类", "事实抽取、主体校验与质量审计", "冲突仲裁、搜索验证与发布"], evidence: mainRun.curation?.summary || mainRun.status_detail || "主爬虫完成后执行统一 Agent 审核。" },
      domainNode("local", "本地运营商", [410, 318]),
      domainNode("international", "内地电讯企业", [608, 318]),
      domainNode("cloud", "全球云厂商", [806, 318]),
      domainNode("macro", "香港电讯市场", [1004, 318]),
      { key: "insights", label: "17项AI洞察", value: number(intelligenceRun.operational_summary?.model_analysis?.focuses_passed || 17), unit: "项通过", note: "四库统一证据链", tone: "cyan", position: [1202, 318], details: ["四库事实通过质量门禁后统一分析", "指标、期间、口径或来源变化会整批失效重算", `最近完成 ${runCompletionText(intelligenceRun)}`], evidence: intelligenceRun.progress_detail || intelligenceRun.status_detail || state.executiveIntelligence?.method || "四库刷新运行归档" },
      { key: "consumers", label: "情报进入业务入口", value: "3", unit: "个入口", note: "主页 · 小竞AI · 公开页", tone: "mint", position: [1400, 318], details: ["主页展示最新通过事实", "小竞AI检索四库与历史证据", "公开页发布已验证快照"], evidence: intelligenceRun.operational_summary?.pages_publish?.public_url || intelligenceRun.progress_detail || "主页与公开页发布证据" },
    ];
    const stageByKey = new Map(stages.map((stage) => [stage.key, stage]));
    const newsSearch = stageByKey.get("search") || {};
    const newsGate = stageByKey.get("gate") || {};
    const newsAi = stageByKey.get("ai") || {};
    const newsDedupe = stageByKey.get("dedupe") || {};
    const newsWrite = stageByKey.get("write") || {};
    const newsPush = stageByKey.get("push") || {};
    const runListEvidence = runs.map((run) => `${newsRunDate(run)} ${newsRunTime(run)} · ${lineageRunStatus(run)} · ${runCompletionText(run)}`).join("\n") || newsRun.progress_detail || "当天运行尚未归档";
    const sourceEvidence = sources.map((item) => `${item.label} ${number(item.count)} 条`).join("、") || "待读取有效来源分组";
    const intelligenceSummary = intelligenceRun.operational_summary || {};
    const modelAnalysis = intelligenceSummary.model_analysis || {};
    const pagesPublish = intelligenceSummary.pages_publish || {};
    const newsStageStep = (stage, title, action, rule, next) => lineageProcessStep(
      title,
      lineageStageStatus(stage),
      stage.input || "等待当天运行归档",
      action,
      rule,
      stage.value === undefined ? "暂无可用结果" : `保留 ${number(stage.value)} 条${stage.lost ? `，排除 ${number(stage.lost)} 条` : ""}`,
      next,
      stage.evidence || "该步骤尚未留下独立日志。",
    );
    const domainProcess = (key, fallbackLabel) => {
      const domain = domains.get(key) || {};
      const metric = domain.metric || {};
      const label = domain.title || fallbackLabel;
      const domainEvidence = domain.context || state.executiveIntelligence?.method || intelligenceRun.progress_detail || "四库运行证据暂不可用";
      const metricText = metric.value === undefined || metric.value === null || metric.value === "" ? "暂无通过门禁的数值" : `${metric.label || "当前指标"}：${metric.value}${metric.unit || ""}`;
      return [
        lineageProcessStep("接收 Agent 审核证据", lineageRunStatus(intelligenceRun), "主爬虫抽取的候选事实、来源链接和原文快照", `只接收与「${label}」数据域匹配的候选记录`, "来源、主体、期间或指标不完整时不进入正式库", "形成待规范化的数据域候选集", "主体与指标标准化", domainEvidence),
        lineageProcessStep("主体、指标与期间标准化", "处理规则", "原文中的公司别名、指标名、单位、年份或季度", "映射到统一主体、指标ID、时间粒度和单位", "不将不同单位、不同期间或不同口径强行合并", "生成可比对、可去重的结构化主键", "来源独立性与证据门禁", domainEvidence),
        lineageProcessStep("来源独立性与证据门禁", "质量门禁", "结构化候选值与其来源文档", "核对来源数、原文定义、单位和计算过程", "冲突、定义变化或证据不足时保留空值与待补清单，不用近似值填补", "通过记录和明确的 backlog 分开保存", "写入数据域与质量审计", domainEvidence),
        lineageProcessStep("写入数据域与质量审计", lineageRunStatus(intelligenceRun), "通过门禁的结构化事实和未通过的待补记录", `更新${label}数据库、覆盖率、冲突账本和来源索引`, "事实值、来源、口径和质量状态必须同步更新", metricText, "17项AI洞察统一取数", `${domainEvidence}\n四库刷新：${runCompletionText(intelligenceRun)}`),
      ];
    };
    const processByNode = {
      strategic: [
        lineageProcessStep("计算当天调度时点", lineageRunStatus(newsRun), "Asia/Hong_Kong 时区、06:00/13:30 定时槽与已执行状态", "调度器为每个时点创建独立运行归档", "同一时点不重复执行；失败重试保留原归档证据", `当天读取 ${number(runs.length)} 次战略新闻运行`, "加载搜索配置与历史记忆", runListEvidence),
        lineageProcessStep("加载搜索配置与历史记忆", lineageStageStatus(newsSearch), "固定关键词、页面来源、主爬虫页面变化线索和历史事件", "将固定扫描与上一轮留下的线索组合为本轮输入", "不直接将页面变化当作新闻，必须重新搜索与审核", newsSearch.input || "已准备当天搜索输入", "线索发现与补缺", newsSearch.evidence || runListEvidence),
        newsStageStep(newsSearch, "执行线索发现", "合并固定检索、Agentic Search 和页面变化关联查询", "每条候选保留来源URL、发布时间和原始文本", "确定性门禁"),
      ],
      "news-search": [
        lineageProcessStep("固定监控扫描", lineageStageStatus(newsSearch), newsSearch.input || "关键词与固定来源", "按已批准关键词和页面清单抓取候选", "保留原始来源与时间信息", `当天共发现 ${number(newsSearch.value || 0)} 条候选`, "Agentic Search补缺", newsSearch.evidence),
        lineageProcessStep("Agentic Search 补缺", lineageStageStatus(newsSearch), "固定扫描结果和未覆盖的竞对/政策/网络主题", "根据缺口规划补充查询，扩展同义实体和关联事件", "补充查询仍需通过后续时间、URL和AI门禁", "形成补缺候选集", "合并主爬虫页面变化线索", newsSearch.evidence),
        lineageProcessStep("合并页面变化线索", lineageStageStatus(newsSearch), "03:00主爬虫发现的标题、链接、数值或页面差异", "将变化点转为可检索的事件查询并与新闻候选合并", "变化线索只扩大搜索范围，不跳过审核", `统一候选集：${number(newsSearch.value || 0)} 条`, "确定性门禁", newsSearch.evidence),
        newsStageStep(newsGate, "确定性门禁", "规范化URL，检查发布时间、日期窗口与基础重复", "硬规则不通过的候选不消耗AI审核额度", "AI语义审核"),
      ],
      "news-ai": [
        newsStageStep(newsGate, "审核前确定性门禁", "检查时间窗口、发布日期、URL合法性与基础重复", "硬条件先于LLM执行，失败记录明确排除原因", "构造AI审核上下文"),
        lineageProcessStep("构造单条审核上下文", lineageStageStatus(newsAi), `${number(Number(newsAi.value || 0) + Number(newsAi.lost || 0))} 条通过硬门禁的候选`, "整理标题、摘要、来源、日期、竞对实体和业务上下文", "每条候选独立审核，单条异常隔离，不阻断整批", "形成可追溯的逐条审核输入", "LLM战略相关性判断", newsAi.evidence),
        newsStageStep(newsAi, "LLM战略相关性判断", "结合竞对、政策、市场、网络、云与战略影响逐条判定", "必须输出纳入/排除结果与理由，不以模型推断替代来源事实", "历史语义去重"),
        lineageProcessStep("保存审核理由与影响标签", lineageStageStatus(newsAi), `${number(newsAi.value || 0)} 条纳入、${number(newsAi.lost || 0)} 条排除`, "将每条的纳入理由、业务影响和审核状态写入运行归档", "排除候选保留审计轨迹，不进入正式输出", `审核保留 ${number(newsAi.value || 0)} 条`, "历史语义去重", newsAi.evidence),
      ],
      "news-dedupe": [
        lineageProcessStep("准备历史事件索引", lineageStageStatus(newsDedupe), `${number(newsAi.value || 0)} 条AI保留候选与历史新闻事件`, "规范化标题、来源URL、实体、时间和事件摘要", "先做确定性链接/标题比对，再做语义事件比对", "生成待匹配的候选与历史索引", "语义重复识别", newsDedupe.evidence),
        newsStageStep(newsDedupe, "语义重复识别", "比较同一事件的不同来源、改写标题和后续进展", "相同事件的转载/改写归为历史重复；有实质新进展时保留", "新增新闻写入与回读"),
        lineageProcessStep("回写历史记忆", lineageStageStatus(newsDedupe), `${number(newsDedupe.value || 0)} 条新增与 ${number(newsDedupe.lost || 0)} 条重复判定`, "保存新事件及重复关系，为下一轮提供去重和补缺上下文", "历史记忆只使用已审核的新增事件", `保留 ${number(newsDedupe.value || 0)} 条新增新闻`, "飞书写入、回读与业务入口", newsDedupe.evidence),
      ],
      "news-output": [
        newsStageStep(newsWrite, "写入飞书审核表", "将新增新闻的标题、摘要、来源、理由和业务影响写入正式表", "只写入通过AI审核和历史去重的新闻", "逐格回读校验"),
        lineageProcessStep("逐格回读校验", lineageStageStatus(newsWrite), `${number(newsWrite.value || newsDedupe.value || 0)} 条写入结果`, "重新读取已写单元格，逐一比较标题、来源、分类与摘要", "写入值与回读值必须完全一致；不一致时不得宣告交付成功", "形成可审计的正式新闻归档", "生成群卡片与订阅内容", newsWrite.evidence),
        newsStageStep(newsPush, "生成并发送业务内容", "根据正式归档生成审核表、订阅文本和群组卡片", "审核、去重、写入、回读和归档全部通过后才能推送", "主页、订阅者与历史记忆"),
        lineageProcessStep("影响下一轮", lineageStageStatus(newsPush), "已归档新闻、重复关系和本轮缺口", "更新历史去重索引与关联补缺线索", "只使用已完成的运行归档，不将中间态当作历史事实", "下一轮能识别旧事件并针对缺口搜索", "06:00 / 13:30 下一次运行", newsPush.evidence || newsDedupe.evidence),
      ],
      main: [
        lineageProcessStep("读取有效频率配置", lineageRunStatus(mainRun), "飞书频率表、禁用状态与上次执行状态", "排除禁用行，按每日/每周/每月和下次运行时间计算到期任务", "每行配置独立保留频率和执行状态，不将未到期行强制执行", `${configured || 0} 条有效配置：${number(frequency.daily)}每日、${number(frequency.weekly)}每周、${number(frequency.monthly)}每月`, "分组并抓取到期来源", sourceEvidence),
        lineageProcessStep("分组并抓取到期来源", lineageRunStatus(mainRun), `${configured || 0} 条有效配置`, "按香港本地竞对、全球标杆运营商、香港重点资讯和国际政策行业分组采集", "每个来源保留原文链接、抓取时间和页面结果；单源失败不覆盖其他结果", sourceEvidence, "页面差异与事实候选抽取", mainRun.progress_detail || mainRun.status_detail || sourceEvidence),
        lineageProcessStep("页面差异与事实候选抽取", lineageRunStatus(mainRun), "当前页面、上次快照和抓取返回的结构化内容", "对标题、链接、表格、数值和文本变化做差异检测，同时抽取候选事实", "页面变化是线索而不是已验证事实，必须进入Agent审核", "事实候选集与战略新闻关联线索", "Agent 证据审核", mainRun.status_detail || mainRun.progress_detail || "主爬虫运行归档"),
        lineageProcessStep("保存运行归档与下次状态", lineageRunStatus(mainRun), "抓取结果、失败行、页面变化和候选事实", "写入日志、运行状态、快照和下次执行时间", "中断或失败必须保留独立状态，不标记为成功", `最近完成 ${runCompletionText(mainRun)}`, "Agent审核和战略新闻补缺", mainRun.progress_detail || mainRun.status_detail || mainEvidence.join("\n")),
      ],
      agent: [
        lineageProcessStep("证据接收与来源分类", lineageRunStatus(mainRun), "主爬虫候选事实、原文、URL和页面快照", "识别官方披露、监管文件、公司页面、媒体与二手来源", "来源类型和原文定位不清时不进入正式事实", "带来源等级的证据候选", "事实和主体抽取", mainRun.curation?.summary || mainRun.status_detail || "Agent审核归档"),
        lineageProcessStep("事实、主体、指标与期间抽取", lineageRunStatus(mainRun), "已分类的证据候选", "抽取公司/市场主体、指标、值、单位、期间、口径和原文片段", "每个数值必须与原文片段及来源链接绑定", "生成可审核的结构化事实", "主体、单位与口径校验", mainRun.curation?.summary || mainRun.status_detail),
        lineageProcessStep("主体、单位与口径校验", lineageRunStatus(mainRun), "结构化事实与原文定义", "统一别名，校验期间、币种、百分比、用户数和网络单位", "单位或口径不同时不强行合并或计算", "得到可比的标准化候选", "来源独立性和质量门禁", mainRun.curation?.summary || "实体与口径校验规则"),
        lineageProcessStep("来源独立性与质量门禁", lineageRunStatus(mainRun), "标准化候选与全部证据链", "检查来源数、官方性、相互独立性、数值一致性和原文可达性", "冲突、定义变化、精度不一致或来源不足时进入backlog而非正式值", "划分通过记录、冲突记录和待补记录", "冲突仲裁与搜索验证", mainRun.curation?.summary || "质量审计规则"),
        lineageProcessStep("冲突仲裁与搜索验证", lineageRunStatus(mainRun), "冲突、缺口和高价值待补记录", "回到官方原文、补充搜索并比较连续期间披露", "不能确定唯一正确口径时保持空值并记录待办", "产生最终事实、来源证据包和审计结果", "分发到四个业务数据库", mainRun.curation?.summary || mainRun.status_detail),
        lineageProcessStep("发布审计包并分发四库", lineageRunStatus(mainRun), "通过的事实、来源、口径、冲突与backlog", "保存完整审计记录，按业务域分流到本地运营商、内地电讯企业、全球云厂商与香港电讯市场", "只分发通过质量门禁的正式事实，backlog保持可追踪但不作为已知数值", "四库刷新输入和可检索证据链", "四库更新", mainRun.curation?.summary || mainRun.status_detail),
      ],
      "database-local": domainProcess("local", "本地运营商"),
      "database-international": domainProcess("international", "内地电讯企业"),
      "database-cloud": domainProcess("cloud", "全球云厂商"),
      "database-macro": domainProcess("macro", "香港电讯市场"),
      insights: [
        lineageProcessStep("聚合四库通过事实", lineageRunStatus(intelligenceRun), "本地运营商、内地电讯企业、全球云厂商和香港电讯市场四库", "只加载通过质量门禁并具有来源链的正式事实", "指标、期间、单位和口径必须可比；缺口保持缺口", "形成统一证据输入包", "计算证据指纹与失效检查", state.executiveIntelligence?.method || intelligenceRun.progress_detail || "四库刷新归档"),
        lineageProcessStep("计算证据指纹与失效检查", lineageRunStatus(intelligenceRun), "四库事实、来源、期间、口径与上次证据指纹", "对全部输入计算证据哈希并比对变化", "任一指标、期间、口径或来源变化都使相关总结失效，不局部沿用旧结论", modelAnalysis.evidence_hash ? `证据指纹 ${modelAnalysis.evidence_hash}` : "生成当次分析证据指纹", "执行17项洞察", modelAnalysis.evidence_hash || intelligenceRun.progress_detail || "证据指纹待归档"),
        lineageProcessStep("执行17项AI洞察", lineageRunStatus(intelligenceRun), "统一证据输入包和洞察主题清单", "逐项生成竞对、运营、云与市场分析，并将结论绑定到具体证据", "禁止超越数据期间做因果外推；模型失败或证据不足时显式标记", `${number(modelAnalysis.focuses_passed || 17)} 项洞察通过`, "洞察质量门禁与发布包", modelAnalysis.model ? `模型：${modelAnalysis.model}\n回退：${modelAnalysis.fallback_used ? "是" : "否"}` : intelligenceRun.progress_detail || "模型运行归档"),
        lineageProcessStep("洞察质量门禁与发布包", lineageRunStatus(intelligenceRun), "17项洞察、证据引用、模型状态和证据指纹", "检查每项洞察是否有足够证据、无口径冲突并可以重现", "未通过门禁的洞察不进入主页或公开页", "形成主页、小竞AI与公开页的统一发布包", "情报进入业务入口", intelligenceRun.progress_detail || intelligenceRun.status_detail || state.executiveIntelligence?.method),
      ],
      consumers: [
        lineageProcessStep("组装业务交付包", lineageRunStatus(intelligenceRun), "通过的17项洞察、四库事实、新增新闻与全部证据链", "按主页、小竞AI检索和公开页所需结构组装同一批已审核内容", "三个入口共用同一证据边界，不在前端另行编造结论", "生成三类可发布产物", "主页展示、RAG索引和公开页发布", intelligenceRun.progress_detail || intelligenceRun.status_detail || "业务交付归档"),
        lineageProcessStep("更新主页展示", lineageRunStatus(intelligenceRun), "最新通过门禁的指标、洞察和新闻", "替换驾驶舱与相关业务页的当前快照", "显示值必须保留数据日期、口径和来源状态", "主页可见最新情报", "小竞AI知识索引", intelligenceRun.progress_detail || "主页刷新归档"),
        lineageProcessStep("更新小竞AI知识索引", lineageRunStatus(intelligenceRun), "四库结构化事实、新闻归档、洞察与证据片段", "分块、绑定来源和业务别名后加入检索范围", "检索结果必须返回来源证据；缺口和冲突不作为确定事实", "小竞AI可按中文别名查询已审核情报", "公开页生成与发布", state.executiveIntelligence?.method || intelligenceRun.progress_detail),
        lineageProcessStep("生成并发布公开页", pagesPublish.ok ? "已发布" : pagesPublish.status || "待发布", "经过脱敏和门禁的主页快照、四库概览与洞察", "生成静态站点快照，发布后回读站点状态与版本", "只发布可公开内容；发布失败保留错误且不伪装为成功", pagesPublish.ok ? `已发布版本 ${pagesPublish.site_version || "未记录"}` : `发布状态：${pagesPublish.status || "待归档"}`, "业务用户访问与下一轮更新", pagesPublish.public_url || pagesPublish.error || intelligenceRun.progress_detail || "公开页发布证据"),
      ],
    };
    nodes.forEach((node) => { node.processSteps = processByNode[node.key] || []; });
    const edges = [
      ["strategic", "news-search", "到点启动", "cyan"], ["news-search", "news-ai", "进入审核", "cyan"], ["news-ai", "news-dedupe", "相关事件", "cyan"], ["news-dedupe", "news-output", "新增线索", "cyan"], ["news-output", "strategic", "", "feedback"],
      ["main", "agent", "", "cyan"], ["main", "news-search", "", "amber"],
      ["agent", "database-local", "", "cyan"], ["agent", "database-international", "", "cyan"], ["agent", "database-cloud", "", "cyan"], ["agent", "database-macro", "", "cyan"],
      ["database-local", "insights", "", "cyan"], ["database-international", "insights", "", "cyan"], ["database-cloud", "insights", "", "cyan"], ["database-macro", "insights", "", "cyan"], ["insights", "consumers", "", "cyan"], ["news-output", "consumers", "", "cyan"],
    ];
    return {
      nodes,
      edges,
      canvasSize: [1580, 492],
      feedbackLabel: "历史记忆影响下一轮",
      groups: [{ key: "databases", label: "四库更新", note: `最近完成 ${runCompletionText(intelligenceRun)}`, position: [394, 282], size: [794, 190] }],
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
    const forward = target.x >= source.x;
    const sx = forward ? source.x + source.w : source.x;
    const sy = source.y + source.h / 2;
    const tx = forward ? target.x : target.x + target.w;
    const ty = target.y + target.h / 2;
    const bend = Math.max(48, Math.abs(tx - sx) * .44);
    return `M ${sx} ${sy} C ${sx + (forward ? bend : -bend)} ${sy}, ${tx - (forward ? bend : -bend)} ${ty}, ${tx} ${ty}`;
  }

  function syncNewsLineageEdges() {
    document.querySelectorAll("[data-news-lineage-edge]").forEach((path) => {
      path.setAttribute("d", newsLineageEdgePath(path.dataset.from, path.dataset.to, path.dataset.kind));
    });
  }

  function lineageStageKey(nodeKey) {
    return ({ strategic: "search", "news-search": "search", "news-ai": "ai", "news-dedupe": "dedupe", "news-output": "push" })[nodeKey] || "";
  }

  async function openNewsLineageDetail(nodeKey) {
    state.newsSelectedStage = nodeKey;
    let runs = selectedNewsRuns();
    const missing = runs.filter((run) => !state.newsRunDetails[run.crawl_run_id]);
    if (missing.length) await loadNewsRuns(missing.map((run) => run.crawl_run_id));
    runs = selectedNewsRuns();
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = globalSchedulerLineageModel(runs, stages);
    const node = lineage.nodes.find((item) => item.key === nodeKey);
    const dialog = document.querySelector("#newsLineageDialog");
    const body = document.querySelector("#newsLineageDialogBody");
    if (!node || !dialog || !body) return;
    const nodesByKey = new Map(lineage.nodes.map((item) => [item.key, item]));
    const incoming = lineage.edges.filter(([, to]) => to === nodeKey).map(([from, , label]) => `${nodesByKey.get(from)?.label || from}${label ? ` · ${label}` : ""}`);
    const outgoing = lineage.edges.filter(([from]) => from === nodeKey).map(([, to, label]) => `${nodesByKey.get(to)?.label || to}${label ? ` · ${label}` : ""}`);
    const stageKey = lineageStageKey(nodeKey);
    const relatedItems = stageKey ? runs.flatMap((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      return (Array.isArray(detail.newsItems) ? detail.newsItems : []).map((item) => ({ run, item }));
    }) : [];
    const runEvidence = stageKey ? runs.map((run) => {
      const detail = state.newsRunDetails[run.crawl_run_id] || {};
      const runStage = buildNewsProcess(run, detail).find((item) => item.key === stageKey);
      const matched = newsStageLogLines(detail.content || "", stageKey);
      const statusLabel = ({ completed: "已完成", running: "运行中", failed: "已中断" })[run.run_status] || run.run_status || "未知";
      return `<article class="news-lineage-run-card"><header><div><strong>${esc(newsRunTime(run))} ${esc(run.scope || "战略新闻扫描")}</strong><span>${esc(runCompletionText(run))}</span></div><em>${esc(statusLabel)}</em></header><dl><div><dt>阶段输入</dt><dd>${esc(runStage?.input || "当天运行归档")}</dd></div><div><dt>阶段结果</dt><dd>${runStage ? `保留 ${number(runStage.value)} 条${runStage.lost ? `，排除 ${number(runStage.lost)} 条` : ""}` : "详见节点证据"}</dd></div></dl><div class="news-lineage-run-evidence"><strong>运行证据</strong><pre>${esc(matched.join("\n") || runStage?.evidence || run.progress_detail || run.status_detail || "该次运行尚未留下此节点的独立日志。")}</pre></div></article>`;
    }).join("") : "";
    const processFlow = `<section class="news-lineage-dialog-section is-process-flow"><header><h3>完整处理流程</h3><span>${number((node.processSteps || []).length)} 个可核对步骤</span></header><ol class="news-lineage-process-steps">${(node.processSteps || []).map((step, index) => {
      const statusClass = /(已完成|已发布)/.test(step.status || "") ? "is-done" : /进行中/.test(step.status || "") ? "is-running" : "is-config";
      return `<li><article><header><span>${String(index + 1).padStart(2, "0")}</span><div><h4>${esc(step.title || `步骤 ${index + 1}`)}</h4><em class="${statusClass}">${esc(step.status || "待归档")}</em></div></header><dl><div><dt>输入</dt><dd>${esc(step.input || "未记录")}</dd></div><div><dt>处理动作</dt><dd>${esc(step.action || "未记录")}</dd></div><div><dt>规则／门禁</dt><dd>${esc(step.rule || "未记录")}</dd></div><div><dt>本步产出</dt><dd>${esc(step.output || "未记录")}</dd></div><div><dt>进入下一步</dt><dd>${esc(step.next || "流程结束")}</dd></div></dl><div class="news-lineage-step-evidence"><strong>当天证据／执行依据</strong><pre>${esc(step.evidence || "该步骤尚未留下独立证据。")}</pre></div></article></li>`;
    }).join("")}</ol></section>`;
    const itemDetails = relatedItems.length ? `<section class="news-lineage-dialog-section is-item-details"><header><h3>当天具体内容</h3><span>${number(relatedItems.length)} 条已归档新闻</span></header><div class="news-lineage-detail-items">${relatedItems.map(({ run, item }) => `<article><div><span>${esc(item.category || "未分类")}</span><time>${esc(newsRunTime(run))} · ${esc(String(item.publishedAt || "").replace("T", " ").slice(0, 16) || "未记录发布时间")}</time></div><h4>${item.url ? `<a href="${esc(safeUrl(item.url))}" target="_blank" rel="noreferrer">${esc(item.title)}</a>` : esc(item.title)}</h4><p>${esc(item.summary || "运行归档未保存摘要。")}</p><dl><div><dt>来源</dt><dd>${esc(item.source || "未记录")}</dd></div><div><dt>AI 纳入理由</dt><dd>${esc(item.inclusionReason || "运行归档未记录纳入理由。")}</dd></div>${item.businessImpact ? `<div><dt>业务影响</dt><dd>${esc(item.businessImpact)}</dd></div>` : ""}</dl></article>`).join("")}</div></section>` : "";
    body.innerHTML = `<header><div><span>${esc(state.newsSelectedDate || newsRunDate(runs[0]))} · 每日全景</span><h2>${esc(node.label)}</h2><p>已将当天运行记录、节点作用和真实证据整理在一起。</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header><div class="news-lineage-dialog-content">
      <section class="news-lineage-dialog-summary"><div><span>当天结果</span><strong>${esc(node.value)}<small>${esc(node.unit || "")}</small></strong><p>${esc(node.note || "")}</p></div><dl><div><dt>上游来源</dt><dd>${esc(incoming.join("、") || "定时调度与固定配置")}</dd></div><div><dt>下游去向</dt><dd>${esc(outgoing.join("、") || "作为最终业务交付节点")}</dd></div><div><dt>数据日期</dt><dd>${esc(state.newsSelectedDate || newsRunDate(runs[0]) || "最新可用记录")}</dd></div></dl></section>
      ${processFlow}
      <section class="news-lineage-dialog-section is-node-notes"><header><h3>整理后的节点说明</h3><span>本页直接可核对</span></header><ul>${(node.details || []).map((item) => `<li>${esc(item)}</li>`).join("")}</ul></section>
      ${runEvidence ? `<section class="news-lineage-dialog-section is-run-history"><header><h3>当天运行记录</h3><span>${number(runs.length)} 次定时运行</span></header><div class="news-lineage-run-list">${runEvidence}</div></section>` : ""}
      ${itemDetails}
      <section class="news-lineage-dialog-section is-node-evidence"><header><h3>节点证据摘录</h3><span>来自调度概览、四库结果或运行归档</span></header><pre class="news-lineage-node-evidence">${esc(node.evidence || "当前归档未保存可展示的证据。")}</pre></section>
    </div>`;
    dialog.showModal();
  }

  function bindNewsLineageInteractions(panel) {
    const canvas = panel.querySelector("[data-news-lineage-canvas]");
    if (!canvas) return;
    canvas.addEventListener("click", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (!node) return;
      panel.querySelectorAll("[data-news-lineage-node]").forEach((item) => item.classList.toggle("is-selected", item === node));
      openNewsLineageDetail(node.dataset.newsLineageNode);
    });
    requestAnimationFrame(syncNewsLineageEdges);
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

  function renderNews() {
    const panel = document.querySelector('[data-workspace-panel="news"]');
    const runs = selectedNewsRuns();
    const run = runs[0] || null;
    const dates = [...new Set(state.newsRuns.map(newsRunDate).filter(Boolean))];
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = globalSchedulerLineageModel(runs, stages);
    const selectedLineageNode = lineage.nodes.find((node) => node.key === state.newsSelectedStage);
    const [lineageWidth, lineageHeight] = lineage.canvasSize || [1260, 480];
    panel.innerHTML = `<div class="workspace-module-inner news-process-workbench">
      <section class="workspace-panel news-process-panel">
        <header class="news-process-toolbar"><h2>新闻获取与 AI 审核流程</h2>
          <div class="news-run-controls"><label><span>日期</span><select data-news-date-select aria-label="选择要查看的日期">${dates.map((date) => `<option value="${esc(date)}"${date === state.newsSelectedDate ? " selected" : ""}>${esc(date)}</option>`).join("")}</select></label></div>
        </header>
        ${!run ? '<div class="workspace-empty">正在读取新闻采集运行归档…</div>' : `<section class="news-lineage is-global" aria-label="${esc(state.newsSelectedDate)} 情报获取流程，点击卡片查看详情">
          <div class="news-lineage-viewport" tabindex="0" aria-label="可横向滚动的情报生成流程图">
            <div class="news-lineage-canvas${state.newsLineagePaused ? " is-paused" : ""}" data-news-lineage-canvas style="--lineage-zoom:${state.newsLineageZoom};width:${lineageWidth}px;height:${lineageHeight}px">
              <svg class="news-lineage-edges" viewBox="0 0 ${lineageWidth} ${lineageHeight}" style="width:${lineageWidth}px;height:${lineageHeight}px" aria-hidden="true"><defs><marker id="newsLineageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${lineage.edges.map(([from, to, label, kind], index) => `<g class="news-lineage-edge is-${esc(kind)}"><path id="newsLineageEdge${index}" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path><path class="news-lineage-pulse" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path>${label ? `<text dy="-8"><textPath href="#newsLineageEdge${index}" startOffset="50%">${esc(label)}</textPath></text>` : ""}</g>`).join("")}</svg>
              ${lineage.feedbackLabel ? `<span class="news-lineage-feedback-label">${esc(lineage.feedbackLabel)}</span>` : ""}
              ${(lineage.groups || []).map((group) => `<div class="news-lineage-group" style="transform:translate(${group.position[0]}px,${group.position[1]}px);width:${group.size[0]}px;height:${group.size[1]}px"><strong>${esc(group.label)}</strong><span>${esc(group.note)}</span></div>`).join("")}
              <div class="news-lineage-nodes" role="list">${lineage.nodes.map((node) => `<button class="news-lineage-node is-${esc(node.tone)}${node.key === selectedLineageNode?.key ? " is-selected" : ""}" type="button" role="listitem" data-news-lineage-node="${esc(node.key)}" data-x="${node.position[0]}" data-y="${node.position[1]}" style="transform:translate(${node.position[0]}px,${node.position[1]}px)" aria-label="${esc(node.label)}，${esc(node.value)}${esc(node.unit || "")}，点击查看整理详情"><i class="news-lineage-open" aria-hidden="true">↗</i><span>${esc(node.label)}</span><strong>${esc(node.value)}<small>${esc(node.unit || "")}</small></strong><em>${esc(node.note || "")}</em></button>`).join("")}</div>
            </div>
          </div>
        </section>
        ${renderNewsItems(runs)}
        <dialog class="news-stage-dialog news-lineage-dialog" id="newsLineageDialog"><div id="newsLineageDialogBody"></div></dialog>`}
      </section>
    </div>`;
    bindNewsLineageInteractions(panel);
  }

  async function loadNewsRuns(runIds) {
    if (!runIds.length) return;
    const requestId = ++state.newsRunRequest;
    renderNews();
    const missing = runIds.filter((id) => !state.newsRunDetails[id]);
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
    renderNews();
  }

  function renderReports(kind) {
    const weekly = kind === "weekly";
    const panel = document.querySelector(`[data-workspace-panel="${kind}"]`);
    panel.innerHTML = `<div class="workspace-module-inner">
      <div class="workspace-grid"><div class="workspace-report-host" id="workspaceReportHost-${kind}"></div>
      <aside class="workspace-report-side" id="workspaceReportSide-${kind}">${reportPreviewPlaceholder()}</aside></div></div>`;
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

  async function showReportPreview(path) {
    const resolved = reportKindForPath(path);
    if (!resolved) return;
    const { item, kind } = resolved;
    const side = document.querySelector(`#workspaceReportSide-${kind}`);
    if (!side) return;
    const requestId = ++state.previewRequest[kind];
    document.querySelectorAll(`#workspaceReportHost-${kind} .file-row.is-previewing`).forEach((row) => row.classList.remove("is-previewing"));
    document.querySelector(`#workspaceReportHost-${kind} .file-row[data-path="${CSS.escape(path)}"]`)?.classList.add("is-previewing");
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
    return ({ crawl: "定期数据爬虫", "strategic-news": "战略新闻监测", "weekly-report": "战略周报生成", "carrier-performance": "业绩摘要生成", "executive-intelligence-refresh": "四域数据刷新", "audio-generation": "音频摘要生成" })[kind] || kind || "后台任务";
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
        <label>状态<select data-fault-filter="status"><option value="all">全部记录</option><option value="attention">需要处理</option><option value="completed">已恢复</option></select></label>
        <label>任务类型<select data-fault-filter="kind"><option value="all">全部任务</option>${kinds.map((kind) => `<option value="${esc(kind)}">${esc(taskLabel(kind))}</option>`).join("")}</select></label>
        <label class="fault-search">搜索<input type="search" data-fault-filter="query" placeholder="任务、原因或阶段"></label>
        <button class="workspace-button" type="button" data-refresh-fault>刷新</button>
      </div></header>
      <div class="workspace-table-wrap fault-table-wrap"><table class="workspace-table fault-table"><thead><tr>${faultSortableHeader("status", "状态")}${faultSortableHeader("severity", "紧急程度")}${faultSortableHeader("task", "报警任务")}<th>原因摘要</th>${faultSortableHeader("handler", "处理人员")}${faultSortableHeader("time", "发生时间")}<th>详情</th></tr></thead><tbody id="faultTableBody"></tbody></table></div>
      <footer class="fault-monitor-footer"><nav class="fault-pagination" id="faultPagination" aria-label="报警记录分页"></nav><span class="fault-monitor-note" id="faultMonitorStatus" role="status" aria-live="polite"></span></footer>
    </section><dialog class="fault-detail" id="faultDetail"><form method="dialog"><button aria-label="关闭详情">×</button></form><div id="faultDetailBody"></div></dialog></div>`;
    panel.querySelector('[data-fault-filter="status"]').value = state.faultFilters.status;
    panel.querySelector('[data-fault-filter="kind"]').value = state.faultFilters.kind;
    panel.querySelector('[data-fault-filter="query"]').value = state.faultFilters.query;
    renderFaultRows();
  }

  function faultStatus(task) {
    if (task.incident_status === "open") return task.handler_name ? { key: "attention", label: "处理中", tone: "is-running" } : { key: "attention", label: "待处理", tone: "is-alert" };
    if (task.incident_status === "resolved") return { key: "completed", label: "已恢复", tone: "is-ok" };
    if (task.interrupted) return { key: "attention", label: "中断", tone: "is-alert" };
    if (task.run_status === "failed") return { key: "attention", label: "失败", tone: "is-alert" };
    if (task.run_status === "running") return { key: "running", label: "运行中", tone: "is-running" };
    if (task.run_status === "cutoff") return { key: "completed", label: "已截止", tone: "is-muted" };
    return { key: "completed", label: "已完成", tone: "is-ok" };
  }

  function faultCause(task) {
    const status = faultStatus(task);
    if (task.source === "project-monitor") return task.error || task.summary || "监控账本未记录具体故障原因。";
    if (status.key === "running") return task.progress_detail || task.status_detail || `任务正在${task.phase || "运行"}，当前未记录故障。`;
    if (status.key === "completed") return task.status_detail || task.progress_detail || "任务已正常完成，未记录故障原因。";
    return task.error || task.warning || task.status_detail || task.progress_detail || task.detail || task.message || "任务归档未记录具体故障原因，请查看运行日志。";
  }

  function faultSeverity(task) {
    const code = String(task.severity || "").toUpperCase();
    const label = task.severity_label || ({ P1: "紧急", P2: "高", P3: "中" })[code] || "";
    return { code, label, rank: ({ P1: 1, P2: 2, P3: 3 })[code] || 9 };
  }

  function faultHandler(task) {
    return task.handler_name || (task.incident_status === "open" ? "待认领" : "—");
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
      return !query || [task.title, task.scope, task.phase, task.summary, task.error, task.impact, task.kind].some((value) => String(value || "").toLowerCase().includes(query));
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
    const totalPages = Math.max(1, Math.ceil(rows.length / state.faultPageSize));
    state.faultPage = Math.min(Math.max(1, state.faultPage), totalPages);
    const pageStart = (state.faultPage - 1) * state.faultPageSize;
    const visibleRows = rows.slice(pageStart, pageStart + state.faultPageSize);
    document.querySelector("#faultResultCount").textContent = number(filtersActive ? rows.length : state.faultTotal || rows.length);
    body.innerHTML = visibleRows.length ? visibleRows.map(({ task, index, status }) => {
      const severity = faultSeverity(task);
      return `<tr class="fault-row" tabindex="0" role="button" aria-label="查看${esc(task.title || taskLabel(task.kind))}详情" data-fault-detail="${index}"><td><span class="fault-status ${status.tone}"><i></i>${status.label}</span></td><td>${severity.code ? `<span class="fault-severity is-${severity.code.toLowerCase()}">${esc(severity.code)} · ${esc(severity.label)}</span>` : "—"}</td><td><strong>${esc(task.title || taskLabel(task.kind))}</strong><small>${esc(task.scope || taskLabel(task.kind))}</small></td><td><span class="fault-cause">${esc(faultCause(task))}</span><small>${esc(task.phase || "未记录阶段")}</small></td><td class="fault-handler">${esc(faultHandler(task))}</td><td>${esc(taskTime(task))}</td><td><span class="fault-open-label">查看</span></td></tr>`;
    }).join("") : '<tr><td colspan="7" class="fault-empty">没有符合筛选条件的记录。</td></tr>';
    const pagination = document.querySelector("#faultPagination");
    if (pagination) {
      const pageButtons = Array.from({ length: totalPages }, (_, index) => index + 1).map((page) => `<button type="button" data-fault-page="${page}" class="${page === state.faultPage ? "is-active" : ""}" aria-current="${page === state.faultPage ? "page" : "false"}">${page}</button>`).join("");
      pagination.innerHTML = `<button type="button" data-fault-page="${state.faultPage - 1}"${state.faultPage === 1 ? " disabled" : ""} aria-label="上一页">‹</button>${pageButtons}<button type="button" data-fault-page="${state.faultPage + 1}"${state.faultPage === totalPages ? " disabled" : ""} aria-label="下一页">›</button><em>每页 ${state.faultPageSize} 条 · 共 ${number(rows.length)} 条</em>`;
    }
  }

  async function openFaultDetail(index) {
    const task = state.tasks[index];
    const dialog = document.querySelector("#faultDetail");
    const body = document.querySelector("#faultDetailBody");
    if (!task || !dialog || !body) return;
    const status = faultStatus(task);
    const severity = faultSeverity(task);
    const details = [["紧急程度", severity.code ? `${severity.code} · ${severity.label}` : "—"], ["处理人员", faultHandler(task)], ["任务类型", taskLabel(task.kind)], ["当前阶段", task.phase || "未记录"], ["发生时间", taskTime(task)], ["影响范围", task.scope || "未记录"]];
    body.innerHTML = `<header><div><span class="fault-status ${status.tone}"><i></i>${status.label}</span><h2>${esc(task.title || taskLabel(task.kind))}</h2></div><time>${esc(taskTime(task))}</time></header>
      <section class="fault-detail-section fault-reason"><h3>原因</h3><p>${esc(faultCause(task))}</p></section>
      <section class="fault-detail-section"><h3>解决方法</h3><ol>${faultSolutions(task).map((item) => `<li>${esc(item)}</li>`).join("")}</ol></section>
      <dl>${details.map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${esc(value)}</dd></div>`).join("")}</dl>
      <details class="fault-evidence"><summary>查看运行证据</summary><pre id="faultEvidenceLog">${esc(task.evidence?.join("\n") || task.error || "该报警没有更多证据记录。")}</pre></details>`;
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

  async function refreshFaultData() {
    const status = document.querySelector("#faultMonitorStatus");
    if (status) status.textContent = "正在刷新故障与心跳状态…";
    try {
      const response = await fetch("/api/project-incidents?limit=500", { cache: "no-store" });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || `HTTP ${response.status}`);
      state.tasks = Array.isArray(data.incidents) ? data.incidents : [];
      state.faultTotal = Number(data.total || state.tasks.length);
      state.faultPage = 1;
      renderFaultMonitor();
      document.querySelector("#faultMonitorStatus").textContent = `状态已刷新 · 第 ${state.faultPage} / ${Math.max(1, Math.ceil(state.tasks.length / state.faultPageSize))} 页 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
    } catch (error) {
      if (status) status.textContent = `状态刷新失败：${error.message}`;
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
    const row = event.target.closest(".workspace-report-host .file-row[data-path]");
    if (row && !row.classList.contains("with-select") && !event.target.closest("button, a, input, .file-name-editable")) showReportPreview(row.dataset.path);
    const expandPreview = event.target.closest("[data-report-preview-expand]");
    if (expandPreview) {
      const preview = expandPreview.closest("[data-report-preview]");
      const expanded = preview.classList.toggle("is-maximized");
      document.body.classList.toggle("has-maximized-report-preview", expanded);
      expandPreview.setAttribute("aria-label", expanded ? "还原预览" : "放大预览");
      expandPreview.title = expanded ? "还原预览" : "放大预览";
    }
    if (event.target.closest("[data-refresh-fault]")) refreshFaultData();
    const faultPage = event.target.closest("[data-fault-page]");
    if (faultPage && !faultPage.disabled) {
      state.faultPage = Number(faultPage.dataset.faultPage) || 1;
      renderFaultRows();
    }
    const faultSort = event.target.closest("[data-fault-sort]");
    if (faultSort) {
      const key = faultSort.dataset.faultSort;
      state.faultSort = { key, direction: state.faultSort.key === key && state.faultSort.direction === "asc" ? "desc" : "asc" };
      state.faultPage = 1;
      renderFaultMonitor();
    }
    const faultDetail = event.target.closest("[data-fault-detail]");
    if (faultDetail) openFaultDetail(Number(faultDetail.dataset.faultDetail));
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
    const faultRow = event.target.closest?.(".fault-row[data-fault-detail]");
    if (faultRow && ["Enter", " "].includes(event.key)) {
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
      row.tabIndex = 0;
      row.setAttribute("role", "button");
      row.setAttribute("aria-label", `预览报告 ${row.dataset.path || ""}`);
    });
  });
  reportRowObserver.observe(document.body, { childList: true, subtree: true });
  document.addEventListener("change", (event) => {
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
    state.faultPage = 1;
    renderFaultRows();
  });
  document.addEventListener("input", (event) => {
    const filter = event.target.closest('[data-fault-filter="query"]');
    if (!filter) return;
    state.faultFilters.query = filter.value;
    state.faultPage = 1;
    renderFaultRows();
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
      fetch("/api/project-incidents?limit=500").then((response) => response.ok ? response.json() : Promise.reject(new Error(`incidents ${response.status}`))),
      fetch("/api/crawl-runs?taskKind=strategic-news&limit=365").then((response) => response.ok ? response.json() : Promise.reject(new Error(`news runs ${response.status}`))),
      fetch("/api/scheduler-overview", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`scheduler overview ${response.status}`))),
      fetch("/api/executive-intelligence", { cache: "no-store" }).then((response) => response.ok ? response.json() : Promise.reject(new Error(`executive intelligence ${response.status}`))),
      fetch("./static/news-run-items.json?v=1").then((response) => response.ok ? response.json() : {}),
      fetch("./static/competitor-workbench-data.json?v=2").then((response) => response.ok ? response.json() : Promise.reject(new Error(`workbench ${response.status}`)))
    ]);
    const [statusResult, metricsResult, briefsResult, tasksResult, newsRunsResult, schedulerOverviewResult, executiveIntelligenceResult, newsFallbackResult, workbenchResult] = requests;
    if (statusResult.status === "fulfilled") state.status = statusResult.value.status || {};
    if (metricsResult.status === "fulfilled") state.metrics = metricsResult.value.data || {};
    if (briefsResult.status === "fulfilled") state.briefs = briefsResult.value.items || [];
    if (tasksResult.status === "fulfilled") {
      state.tasks = tasksResult.value.incidents || [];
      state.faultTotal = Number(tasksResult.value.total || state.tasks.length);
    }
    if (newsRunsResult.status === "fulfilled") {
      state.newsRuns = (newsRunsResult.value.runs || []).filter((run) => run.task_kind === "strategic-news");
    }
    if (schedulerOverviewResult.status === "fulfilled") state.schedulerOverview = schedulerOverviewResult.value;
    if (executiveIntelligenceResult.status === "fulfilled") state.executiveIntelligence = executiveIntelligenceResult.value;
    if (newsFallbackResult.status === "fulfilled") state.newsItemFallback = newsFallbackResult.value || {};
    if (workbenchResult.status === "fulfilled") state.competitorData = workbenchResult.value;

    state.competitorData ? renderCompetitor() : renderLoadError("competitor", "竞对");
    (state.status || newsRunsResult.status === "fulfilled") ? renderNews() : renderLoadError("news", "新闻");
    if (state.status) { renderReports("weekly"); renderReports("performance"); }
    else { renderLoadError("weekly", "周报"); renderLoadError("performance", "业绩摘要"); }
    tasksResult.status === "fulfilled" ? renderFaultMonitor() : renderLoadError("fault", "故障监控");
    const running = Boolean(state.status?.tasks?.hasRunning);
    const runningDot = document.querySelector("[data-workspace-running]");
    if (runningDot) runningDot.hidden = !running;
    const initialNewsRuns = selectedNewsRuns();
    if (initialNewsRuns.length) loadNewsRuns(initialNewsRuns.map((run) => run.crawl_run_id));
    requests.filter((result) => result.status === "rejected").forEach((result) => console.warn("Workspace module data unavailable", result.reason));
  }

  renderAi();
  renderEmbeddedShells();
  setupEmbeddedSurfaces();
  setupNavCollapse();
  activateModule(moduleFromLocation(), { updateUrl: false });
  loadWorkspaceData();
})();
