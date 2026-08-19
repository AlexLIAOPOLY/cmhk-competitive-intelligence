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
    newsSelectedRunIds: [],
    newsRunDetails: {},
    newsItemFallback: {},
    newsRunRequest: 0,
    newsSelectedStage: "search",
    newsLineageMode: "global",
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
      { key: "ai", label: "AI 语义审核", value: aiRetained, input: `${aiInput || gatePassed} 条送审`, lost: aiRejected, details: ["结合竞对、政策、市场、网络与战略相关性逐条判定", `本轮排除 ${aiRejected} 条；单条异常隔离，不影响其余候选`], evidence: lines.ai },
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
    const available = new Set(state.newsRuns.map((run) => run.crawl_run_id));
    let selected = state.newsSelectedRunIds.filter((id) => available.has(id));
    if (!selected.length) {
      const params = new URLSearchParams(location.hash.replace(/^#/, ""));
      selected = String(params.get("newsRuns") || params.get("newsRun") || "").split(",").filter((id) => available.has(id));
    }
    if (!selected.length && state.newsRuns[0]) selected = [state.newsRuns[0].crawl_run_id];
    state.newsSelectedRunIds = selected.slice(0, 8);
    return state.newsRuns.filter((run) => state.newsSelectedRunIds.includes(run.crawl_run_id));
  }

  function newsTimeline(content) {
    const wanted = [
      ["搜索准备", "准备关键词与固定来源"],
      ["新闻发现完成", "汇总固定搜索与 Agentic 线索"],
      ["候选确定性门禁", "执行硬规则门禁"],
      ["AI审核完成", "完成逐条语义审核"],
      ["语义去重完成", "完成历史事件比对"],
      ["飞书逐格回读：第 1 次回读通过", "完成飞书写入校验"],
      ["结果归档完成", "候选与结果落盘"],
      ["群通知完成", "完成正式群组推送"],
    ];
    return wanted.map(([needle, label]) => {
      const evidence = logLine(content, needle);
      const time = evidence.match(/\[(?:\d{4}-\d{2}-\d{2}[T ])?(\d{2}:\d{2}:\d{2})/)?.[1] || "--:--:--";
      return { label, time, evidence, done: Boolean(evidence) };
    });
  }

  function updateNewsRunUrl(runIds) {
    history.replaceState(null, "", `${location.pathname}${location.search}#workspace=news&newsRuns=${encodeURIComponent(runIds.join(","))}`);
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
        input: `${runs.length} 次批次汇总`,
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

  function globalSchedulerLineageModel(runs, stages) {
    const overview = state.schedulerOverview || {};
    const frequency = overview.frequency_counts || {};
    const latest = overview.latest || {};
    const mainRun = latest.main_crawl || {};
    const newsRun = latest.strategic_news || runs[0] || {};
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
      { key: "strategic", label: "06:00 / 13:30 战略新闻", value: newsRun.run_status === "running" ? "运行中" : "每日2轮", note: `最近完成 ${runCompletionText(newsRun)}`, tone: "cyan", position: [30, 58], details: ["固定时点独立扫描战略新闻", "接收主爬虫产生的页面变化线索"], evidence: newsRun.progress_detail || newsRun.status_detail || newsRun.scope || "战略新闻运行归档" },
      { key: "news-search", label: "线索补缺", value: number((stages.find((stage) => stage.key === "search") || {}).value), unit: "条发现", note: "固定来源 + Agentic + 页面变化", tone: "cyan", position: [390, 58], details: ["固定关键词和页面来源", "对页面变化生成关联查询", "Agentic Search补齐空白"], evidence: (stages.find((stage) => stage.key === "search") || {}).evidence || "等待所选新闻批次证据" },
      { key: "news-ai", label: "AI审核", value: number((stages.find((stage) => stage.key === "ai") || {}).value), unit: "条纳入", note: "逐条判断战略相关性", tone: "cyan", position: [750, 58], details: ["确定性门禁先筛时间、日期与URL", "AI逐条判断战略价值"], evidence: (stages.find((stage) => stage.key === "ai") || {}).evidence || "等待所选新闻批次证据" },
      { key: "news-dedupe", label: "历史去重", value: number(strategicDedupe.lost), unit: "条重复", note: `留下 ${number(strategicDedupe.value)} 条新增`, tone: "mint", position: [1110, 58], details: ["与历史事件语义比对", "新增事件进入后续历史记忆"], evidence: strategicDedupe.evidence || "等待所选新闻批次证据" },
      { key: "news-output", label: "新增新闻", value: number(strategicDedupe.value), unit: "条", note: "审核表 · 推送 · 历史记忆", tone: "focus", position: [1470, 58], details: ["正式写入并回读", "保留的新增事件影响下一轮去重与补缺"], evidence: (stages.find((stage) => stage.key === "push") || {}).evidence || newsRun.progress_detail || "等待所选新闻批次证据" },
      { key: "main", label: "03:00 主爬虫", value: configured ? number(configured) : "—", unit: "条配置", note: `${number(frequency.daily)}每日 · ${number(frequency.weekly)}每周 · ${number(frequency.monthly)}每月`, tone: "focus", position: [24, 356], details: mainEvidence, evidence: mainRun.status_detail || mainRun.progress_detail || mainEvidence.join("\n") },
      { key: "agent", label: "Agent 证据审核", value: "10", unit: "节点", note: "分类 · 抽取 · 校验 · 仲裁", tone: "cyan", position: [232, 356], details: ["证据接收与来源分类", "事实抽取、主体校验与质量审计", "冲突仲裁、搜索验证与发布"], evidence: mainRun.curation?.summary || mainRun.status_detail || "主爬虫完成后执行统一 Agent 审核。" },
      domainNode("local", "本地运营商", [440, 356]),
      domainNode("international", "内地电讯企业", [648, 356]),
      domainNode("cloud", "全球云厂商", [856, 356]),
      domainNode("macro", "香港电讯市场", [1064, 356]),
      { key: "insights", label: "17项AI洞察", value: number(intelligenceRun.operational_summary?.model_analysis?.focuses_passed || 17), unit: "项通过", note: "四库统一证据链", tone: "cyan", position: [1272, 356], details: ["四库事实通过质量门禁后统一分析", "指标、期间、口径或来源变化会整批失效重算", `最近完成 ${runCompletionText(intelligenceRun)}`], evidence: intelligenceRun.progress_detail || intelligenceRun.status_detail || state.executiveIntelligence?.method || "四库刷新运行归档" },
      { key: "consumers", label: "情报进入业务入口", value: "3", unit: "个入口", note: "主页 · 小竞AI · 公开页", tone: "mint", position: [1480, 356], details: ["主页展示最新通过事实", "小竞AI检索四库与历史证据", "公开页发布已验证快照"], evidence: intelligenceRun.operational_summary?.pages_publish?.public_url || intelligenceRun.progress_detail || "主页与公开页发布证据" },
    ];
    const edges = [
      ["strategic", "news-search", "到点启动", "cyan"], ["news-search", "news-ai", "候选进入审核", "cyan"], ["news-ai", "news-dedupe", "相关事件", "cyan"], ["news-dedupe", "news-output", "新增事件", "cyan"], ["news-output", "strategic", "历史记忆影响下一轮", "feedback"],
      ["main", "agent", "页面与字段证据", "cyan"], ["main", "news-search", "页面变化线索", "amber"],
      ["agent", "database-local", "", "cyan"], ["agent", "database-international", "", "cyan"], ["agent", "database-cloud", "", "cyan"], ["agent", "database-macro", "", "cyan"],
      ["database-local", "insights", "", "cyan"], ["database-international", "insights", "", "cyan"], ["database-cloud", "insights", "", "cyan"], ["database-macro", "insights", "", "cyan"], ["insights", "consumers", "发布通过结论", "cyan"], ["news-output", "consumers", "新增新闻", "cyan"],
    ];
    return {
      nodes,
      edges,
      canvasSize: [1690, 560],
      groups: [{ key: "databases", label: "四库更新", note: `最近完成 ${runCompletionText(intelligenceRun)}`, position: [420, 314], size: [836, 216] }],
    };
  }

  function newsLineageModel(runs, stages) {
    const run = runs[0] || {};
    const detail = state.newsRunDetails[run.crawl_run_id] || {};
    const content = String(detail.content || "");
    const items = Array.isArray(detail.newsItems) ? detail.newsItems : [];
    const first = stages[0] || { value: 0 };
    const stage = (key) => stages.find((item) => item.key === key) || { key, value: 0, lost: 0, details: [], evidence: "" };
    const search = stage("search");
    const gate = stage("gate");
    const ai = stage("ai");
    const dedupe = stage("dedupe");
    const write = stage("write");
    const push = stage("push");
    const keywordCount = logNumber(content, /搜索准备：已加载\s*\d+\s*个监控模块、\s*(\d+)\s*个关键词/, 0);
    const pageCount = logNumber(content, /搜索准备：[^\n]*、\s*(\d+)\s*个固定页面来源/, 0);
    const pageClues = logNumber(content, /定时页面线索合并：读取\s*(\d+)\s*条页面变化线索/, 0);
    const pageClueResults = logNumber(content, /定时页面线索合并：[^\n]*返回\s*(\d+)\s*条/, 0);
    const agentQueries = logNumber(content, /Agentic Search补缺：[^\n]*规划并执行\s*(\d+)\s*条补缺查询/, 0);
    const agentResults = logNumber(content, /Agentic Search补缺：[^\n]*补回\s*(\d+)\s*条候选/, 0);
    const deferred = logNumber(content, /AI审核完成：[^\n]*延期\s*(\d+)\s*条/, 0);
    const timeBudgetDeferred = logNumber(content, /30分钟到时转下轮\s*(\d+)\s*条/, 0);
    const nextTime = /晨间/.test(String(run.scope || "")) ? "13:30" : "次日 06:00";
    const categoryCounts = items.reduce((map, item) => {
      const key = String(item.category || "未分类");
      map[key] = (map[key] || 0) + 1;
      return map;
    }, {});
    const topCategories = Object.entries(categoryCounts).sort((a, b) => b[1] - a[1]).slice(0, 3);
    const positions = {
      schedule: [28, 38], inputs: [28, 205], pageclues: [228, 246], search: [254, 94], gate: [455, 94], ai: [646, 94], dedupe: [837, 94], output: [1026, 78], next: [1052, 286],
    };
    const nodes = [
      { key: "schedule", label: "定时触发", value: "06:00 / 13:30", note: "香港时间", tone: "neutral", position: positions.schedule, details: ["战略新闻固定扫描时点", `当前查看 ${newsRunDate(run)} ${newsRunTime(run)}`], evidence: run.scope || "定时扫描" },
      { key: "inputs", label: "固定来源与关键词", value: keywordCount ? number(keywordCount) : "—", unit: "关键词", note: `${pageCount ? number(pageCount) : "—"} 个固定页面`, tone: "neutral", position: positions.inputs, details: [`${keywordCount || "—"} 个监控关键词`, `${pageCount || "—"} 个固定页面来源`], evidence: logLine(content, "搜索准备") },
      { key: "pageclues", label: "定时爬虫页面线索", value: number(pageClues), unit: "条变化", note: `关联检索返回 ${number(pageClueResults)} 条`, tone: "amber", position: positions.pageclues, details: [`读取 ${number(pageClues)} 条页面变化线索`, `关联查询返回 ${number(pageClueResults)} 条`], evidence: logLine(content, "定时页面线索合并") },
      { key: "search", label: "Agentic 补缺搜索", value: number(search.value || first.value), unit: "条发现", note: `${number(agentQueries)} 条补缺查询 · 补回 ${number(agentResults)} 条`, tone: "cyan", position: positions.search, details: search.details, evidence: search.evidence },
      { key: "gate", label: "确定性门禁", value: number(gate.value), unit: "条通过", note: gate.lost ? `挡回 ${number(gate.lost)} 条` : "时间窗 · 日期 · URL", tone: "mint", position: positions.gate, details: gate.details, evidence: gate.evidence },
      { key: "ai", label: "AI 语义审核", value: number(ai.value), unit: "条纳入", note: ai.lost ? `排除 ${number(ai.lost)} 条` : "逐条判断战略相关性", tone: "cyan", position: positions.ai, details: ai.details, evidence: ai.evidence },
      { key: "dedupe", label: "历史语义去重", value: number(dedupe.lost), unit: "条重复", note: `留下 ${number(dedupe.value)} 条新增`, tone: "mint", position: positions.dedupe, details: dedupe.details, evidence: dedupe.evidence },
      { key: "output", label: "本轮新增线索", value: number(dedupe.value), unit: "条", note: `${topCategories.map(([name, count]) => `${name} ${count}`).join(" · ") || "等待逐条归档"}`, tone: "focus", position: positions.output, details: [`写入回读 ${number(write.value)} 条`, `正式推送 ${number(push.value)} 条`, ...items.slice(0, 3).map((item) => item.title)], evidence: dedupe.evidence || push.evidence },
      { key: "next", label: "影响下一轮", value: nextTime, note: `历史库 + 待重试 ${number(deferred + timeBudgetDeferred)} 条`, tone: "amber", position: positions.next, details: [`本轮 ${number(dedupe.value)} 条新增进入历史语义库`, `${number(deferred + timeBudgetDeferred)} 条延期或超时候选留待下轮`, "页面变化线索会生成关联查询与关键词"], evidence: [logLine(content, "定时页面线索合并"), logLine(content, "AI审核完成")].filter(Boolean).join("\n") },
    ];
    const edges = [
      ["schedule", "search", "到点启动", "cyan"], ["inputs", "search", "固定监控", "cyan"], ["pageclues", "search", `${number(pageClues)} 条页面变化`, "amber"],
      ["search", "gate", `${number(search.value)} 条候选`, "cyan"], ["gate", "ai", `${number(gate.value)} 条通过`, "cyan"], ["ai", "dedupe", `${number(ai.value)} 条保留`, "cyan"],
      ["dedupe", "output", `${number(dedupe.value)} 条新增`, "cyan"], ["output", "next", "写入历史与延期队列", "amber"], ["next", "search", "下一轮补缺", "feedback"],
    ];
    return { nodes, edges, nextTime };
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

  function bindNewsLineageInteractions(panel) {
    const canvas = panel.querySelector("[data-news-lineage-canvas]");
    if (!canvas) return;
    const storageKey = `cmhk-news-lineage:${state.newsLineageMode}:${state.newsSelectedRunIds.join(",") || "latest"}`;
    let saved = {};
    try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch (_error) { saved = {}; }
    canvas.querySelectorAll("[data-news-lineage-node]").forEach((node) => {
      const key = node.dataset.newsLineageNode;
      const position = saved[key];
      if (Array.isArray(position) && position.length === 2) {
        node.dataset.x = String(position[0]);
        node.dataset.y = String(position[1]);
        node.style.transform = `translate(${position[0]}px, ${position[1]}px)`;
      }
      node.addEventListener("pointerdown", (event) => {
        if (event.button !== 0) return;
        const startX = event.clientX;
        const startY = event.clientY;
        const originX = Number(node.dataset.x || 0);
        const originY = Number(node.dataset.y || 0);
        let dragged = false;
        node.setPointerCapture(event.pointerId);
        const move = (moveEvent) => {
          const dx = (moveEvent.clientX - startX) / state.newsLineageZoom;
          const dy = (moveEvent.clientY - startY) / state.newsLineageZoom;
          if (Math.abs(dx) + Math.abs(dy) > 4) dragged = true;
          const x = Math.max(6, Math.min(canvas.offsetWidth - node.offsetWidth - 8, originX + dx));
          const y = Math.max(8, Math.min(canvas.offsetHeight - node.offsetHeight - 8, originY + dy));
          node.dataset.x = x.toFixed(1);
          node.dataset.y = y.toFixed(1);
          node.style.transform = `translate(${x}px, ${y}px)`;
          syncNewsLineageEdges();
        };
        const up = () => {
          node.removeEventListener("pointermove", move);
          node.removeEventListener("pointerup", up);
          if (dragged) {
            const positions = {};
            canvas.querySelectorAll("[data-news-lineage-node]").forEach((item) => { positions[item.dataset.newsLineageNode] = [Number(item.dataset.x), Number(item.dataset.y)]; });
            localStorage.setItem(storageKey, JSON.stringify(positions));
          }
        };
        node.addEventListener("pointermove", move);
        node.addEventListener("pointerup", up);
      });
    });
    canvas.addEventListener("click", (event) => {
      const node = event.target.closest("[data-news-lineage-node]");
      if (!node) return;
      state.newsSelectedStage = node.dataset.newsLineageNode;
      panel.querySelectorAll("[data-news-lineage-node]").forEach((item) => item.classList.toggle("is-selected", item === node));
      panel.querySelectorAll("[data-news-lineage-detail]").forEach((item) => { item.hidden = item.dataset.newsLineageDetail !== state.newsSelectedStage; });
    });
    panel.querySelectorAll("[data-news-lineage-action]").forEach((button) => button.addEventListener("click", () => {
      const action = button.dataset.newsLineageAction;
      if (action === "motion") state.newsLineagePaused = !state.newsLineagePaused;
      if (action === "reset") {
        localStorage.removeItem(storageKey);
        renderNews();
        return;
      }
      canvas.style.setProperty("--lineage-zoom", state.newsLineageZoom);
      canvas.classList.toggle("is-paused", state.newsLineagePaused);
      const motionButton = panel.querySelector('[data-news-lineage-action="motion"]');
      if (motionButton) motionButton.textContent = state.newsLineagePaused ? "播放流动" : "暂停流动";
    }));
    panel.querySelectorAll("[data-news-lineage-mode]").forEach((button) => button.addEventListener("click", () => {
      const mode = button.dataset.newsLineageMode;
      if (!mode || mode === state.newsLineageMode) return;
      state.newsLineageMode = mode;
      state.newsSelectedStage = mode === "global" ? "main" : "search";
      renderNews();
    }));
    requestAnimationFrame(syncNewsLineageEdges);
  }

  function renderNewsItems(runs) {
    const groups = runs.map((run) => ({ run, detail: state.newsRunDetails[run.crawl_run_id] })).filter(({ detail }) => detail);
    const itemCount = groups.reduce((sum, group) => sum + (group.detail.newsItems || []).length, 0);
    return `<section class="news-real-items"><header><div><strong>本轮真实新增新闻</strong><span>所选 ${runs.length} 次批次 · 共 ${number(itemCount)} 条</span></div><span>标题、摘要与AI纳入理由来自运行归档</span></header>
      <div class="news-real-items-body">${groups.length ? groups.map(({ run, detail }) => {
        const items = Array.isArray(detail.newsItems) ? detail.newsItems : [];
        return `<section class="news-run-group"><header><strong>${esc(newsRunDate(run))} ${esc(newsRunTime(run))}</strong><span>${esc(run.scope || "新闻扫描")} · ${items.length} 条新增</span></header>${items.length ? `<div class="news-item-list">${items.map((item) => `<article class="news-item"><div class="news-item-tags"><span>${esc(item.category || "未分类")}</span>${item.businessImpact ? `<em>${esc(item.businessImpact)}</em>` : ""}</div><h3>${item.url ? `<a href="${esc(safeUrl(item.url))}" target="_blank" rel="noreferrer">${esc(item.title)}</a>` : esc(item.title)}</h3><p>${esc(item.summary || "暂无摘要")}</p><dl><div><dt>来源</dt><dd>${esc(item.source || "未记录")} · ${esc(String(item.publishedAt || "").replace("T", " ").slice(0, 16))}</dd></div><div><dt>AI纳入理由</dt><dd>${esc(item.inclusionReason || "运行归档未记录理由")}</dd></div></dl></article>`).join("")}</div>` : `<div class="news-run-empty">${run.run_status === "completed" ? "这一批次没有新增新闻，或历史归档未保存逐条明细。" : "该批次尚未完成，真实新增新闻将在归档后出现。"}</div>`}</section>`;
      }).join("") : '<div class="news-run-empty">正在读取所选批次的真实新闻归档…</div>'}</div></section>`;
  }

  async function openNewsStageDetail(stageKey) {
    state.newsSelectedStage = stageKey;
    const selected = selectedNewsRuns();
    const missing = selected.filter((run) => !state.newsRunDetails[run.crawl_run_id]);
    if (missing.length) await loadNewsRuns(missing.map((run) => run.crawl_run_id));
    renderNews();
    const dialog = document.querySelector("#newsStageDialog");
    const body = document.querySelector("#newsStageDialogBody");
    const runs = selectedNewsRuns();
    const stageSets = runs.map((run) => buildNewsProcess(run, state.newsRunDetails[run.crawl_run_id]));
    const stageIndex = stageSets[0]?.findIndex((stage) => stage.key === stageKey) ?? -1;
    const stage = stageIndex >= 0 ? stageSets[0][stageIndex] : null;
    if (!dialog || !body || !stage) return;
    body.innerHTML = `<header><div><span>阶段 ${String(stageIndex + 1).padStart(2, "0")}</span><h2>${esc(stage.label)} · 详细运行日志</h2><p>以下内容直接来自所选批次的不可变运行归档。</p></div><form method="dialog"><button type="submit" aria-label="关闭阶段日志">×</button></form></header>
      <div class="news-stage-dialog-runs">${runs.map((run, index) => {
        const detail = state.newsRunDetails[run.crawl_run_id] || {};
        const runStage = stageSets[index]?.[stageIndex] || stage;
        const content = String(detail.content || "");
        const matched = newsStageLogLines(content, stageKey);
        const statusLabel = runStage.status === "done" ? "已完成" : runStage.status === "current" ? "执行中/中断于此" : "尚未到达";
        return `<section class="news-stage-run-log"><header><div><strong>${esc(newsRunDate(run))} ${esc(newsRunTime(run))}</strong><span>${esc(run.scope || "战略新闻任务")}</span></div><em class="is-${esc(runStage.status)}">${esc(statusLabel)}</em></header>
          <dl><div><dt>阶段输入</dt><dd>${esc(runStage.input)}</dd></div><div><dt>阶段结果</dt><dd>保留 ${number(runStage.value)} 条${runStage.lost ? `，淘汰 ${number(runStage.lost)} 条` : ""}</dd></div></dl>
          <div class="news-stage-log-block"><h3>该阶段日志输出 <span>${number(matched.length)} 行</span></h3><pre>${esc(matched.join("\n") || runStage.evidence || "该批次尚未产生此阶段日志。")}</pre></div>
          <details class="news-stage-full-log"><summary>展开该批次完整原始日志 · ${number(detail.lines || content.split("\n").filter(Boolean).length)} 行</summary><pre>${esc(content || detail.error || "该批次没有可读取的日志内容。")}</pre></details>
        </section>`;
      }).join("")}</div>`;
    dialog.showModal();
  }

  function renderNews() {
    const panel = document.querySelector('[data-workspace-panel="news"]');
    const runs = selectedNewsRuns();
    const run = runs[0] || null;
    const dates = [...new Set(state.newsRuns.map(newsRunDate).filter(Boolean))];
    const selectedDates = [...new Set(runs.map(newsRunDate))];
    const candidateRuns = state.newsRuns.filter((item) => selectedDates.includes(newsRunDate(item)));
    const stages = runs.length ? aggregateNewsStages(runs) : [];
    const lineage = state.newsLineageMode === "global" ? globalSchedulerLineageModel(runs, stages) : newsLineageModel(runs, stages);
    const primaryDetail = run ? state.newsRunDetails[run.crawl_run_id] : null;
    const timeline = newsTimeline(primaryDetail?.content || "");
    const selectedStage = stages.find((stage) => stage.key === state.newsSelectedStage) || stages[0];
    const selectedLineageNode = lineage.nodes.find((node) => node.key === state.newsSelectedStage) || lineage.nodes.find((node) => node.key === (state.newsLineageMode === "global" ? "main" : "search")) || lineage.nodes[0];
    const [lineageWidth, lineageHeight] = lineage.canvasSize || [1260, 480];
    panel.innerHTML = `<div class="workspace-module-inner news-process-workbench">
      <section class="workspace-panel news-process-panel">
        <header class="news-process-toolbar"><h2>新闻获取与 AI 审核流程</h2>
          <div class="news-run-controls"><details class="news-multi-select" name="news-archive-filter"><summary>日期 <b>${selectedDates.length}</b></summary><div><p class="news-select-caption">完整运行归档 · 共 ${number(dates.length)} 天</p>${dates.map((date) => `<label><input type="checkbox" data-news-date-option value="${esc(date)}"${selectedDates.includes(date) ? " checked" : ""}><span>${esc(date)}</span></label>`).join("")}</div></details><details class="news-multi-select" name="news-archive-filter"><summary>批次 <b>${runs.length}</b></summary><div>${candidateRuns.map((item) => `<label><input type="checkbox" data-news-run-option value="${esc(item.crawl_run_id)}"${state.newsSelectedRunIds.includes(item.crawl_run_id) ? " checked" : ""}><span>${esc(newsRunDate(item))} ${esc(newsRunTime(item))} · ${esc(({ completed: "完成", running: "运行中", failed: "中断" })[item.run_status] || item.run_status)}</span></label>`).join("")}</div></details><button class="workspace-button" type="button" data-open-news-review>进入人工审核表</button></div>
        </header>
        ${!run ? '<div class="workspace-empty">正在读取新闻采集运行归档…</div>' : `<div class="news-process-meta"><span>已选择 ${runs.length} 次批次</span><span>${selectedDates.map(esc).join("、")}</span><span>${runs.every((item) => state.newsRunDetails[item.crawl_run_id]) ? "已载入全部运行证据" : "正在载入运行证据…"}</span></div>
        <section class="news-lineage${state.newsLineageMode === "global" ? " is-global" : ""}" aria-labelledby="newsLineageTitle">
          <header class="news-lineage-header"><div class="news-lineage-heading"><div class="news-lineage-mode-switch" role="tablist" aria-label="情报流程视角"><button type="button" role="tab" data-news-lineage-mode="global" aria-selected="${state.newsLineageMode === "global"}">每日全景</button><button type="button" role="tab" data-news-lineage-mode="run" aria-selected="${state.newsLineageMode === "run"}">本轮线索</button></div><h3 id="newsLineageTitle">${state.newsLineageMode === "global" ? "每天的信息从哪里来" : "本轮线索如何形成"}</h3><p>${state.newsLineageMode === "global" ? "上方是战略新闻链路，下方是主爬虫与四库链路；卡片可拖动，点击查看真实证据。" : "查看所选批次从发现、审核到去重和写入的真实数据。"}</p></div><div class="news-lineage-tools" aria-label="流程图控制"><button type="button" data-news-lineage-action="motion">${state.newsLineagePaused ? "播放流动" : "暂停流动"}</button><button type="button" data-news-lineage-action="reset">恢复排列</button></div></header>
          <div class="news-lineage-viewport" tabindex="0" aria-label="可横向滚动的情报生成流程图">
            <div class="news-lineage-canvas${state.newsLineagePaused ? " is-paused" : ""}" data-news-lineage-canvas style="--lineage-zoom:${state.newsLineageZoom};width:${lineageWidth}px;height:${lineageHeight}px">
              <svg class="news-lineage-edges" viewBox="0 0 ${lineageWidth} ${lineageHeight}" style="width:${lineageWidth}px;height:${lineageHeight}px" aria-hidden="true"><defs><marker id="newsLineageArrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker><marker id="newsLineageArrowAmber" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${lineage.edges.map(([from, to, label, kind], index) => `<g class="news-lineage-edge is-${esc(kind)}"><path id="newsLineageEdge${index}" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path><path class="news-lineage-pulse" data-news-lineage-edge data-from="${esc(from)}" data-to="${esc(to)}" data-kind="${esc(kind)}"></path>${label ? `<text><textPath href="#newsLineageEdge${index}" startOffset="50%">${esc(label)}</textPath></text>` : ""}</g>`).join("")}</svg>
              ${lineage.feedbackLabel ? `<span class="news-lineage-feedback-label">${esc(lineage.feedbackLabel)}</span>` : ""}
              ${(lineage.groups || []).map((group) => `<div class="news-lineage-group" style="transform:translate(${group.position[0]}px,${group.position[1]}px);width:${group.size[0]}px;height:${group.size[1]}px"><strong>${esc(group.label)}</strong><span>${esc(group.note)}</span></div>`).join("")}
              <div class="news-lineage-nodes" role="list">${lineage.nodes.map((node) => `<button class="news-lineage-node is-${esc(node.tone)}${node.key === selectedLineageNode?.key ? " is-selected" : ""}" type="button" role="listitem" data-news-lineage-node="${esc(node.key)}" data-x="${node.position[0]}" data-y="${node.position[1]}" style="transform:translate(${node.position[0]}px,${node.position[1]}px)" aria-label="${esc(node.label)}，${esc(node.value)}${esc(node.unit || "")}，可拖动"><i class="news-lineage-drag" aria-hidden="true">⠿</i><span>${esc(node.label)}</span><strong>${esc(node.value)}<small>${esc(node.unit || "")}</small></strong><em>${esc(node.note || "")}</em></button>`).join("")}</div>
            </div>
          </div>
          <div class="news-lineage-details" aria-live="polite">${lineage.nodes.map((node) => `<section data-news-lineage-detail="${esc(node.key)}"${node.key === selectedLineageNode?.key ? "" : " hidden"}><div><span>当前查看</span><h4>${esc(node.label)}</h4><strong>${esc(node.value)} ${esc(node.unit || "")}</strong></div><ul>${node.details.map((item) => `<li>${esc(item)}</li>`).join("")}</ul><blockquote>${esc(node.evidence || "本轮归档暂未记录这一节点的原始日志。")}</blockquote>${["search", "gate", "ai", "dedupe", "output"].includes(node.key) ? `<button type="button" data-news-stage="${esc(node.key === "output" ? "push" : node.key)}">查看该阶段完整运行证据</button>` : ""}</section>`).join("")}</div>
        </section>
        <div class="news-run-timeline"><header><strong>主批次执行时间轴</strong><span>${esc(newsRunDate(run))} ${esc(newsRunTime(run))} · 按真实运行日志还原</span></header><ol>${timeline.map((item) => `<li class="${item.done ? "is-done" : "is-pending"}" title="${esc(item.evidence || "尚未到达")}"><time>${esc(item.time)}</time><span>${esc(item.label)}</span></li>`).join("")}</ol></div>
        ${renderNewsItems(runs)}
        <dialog class="news-stage-dialog" id="newsStageDialog"><div id="newsStageDialogBody"></div></dialog>`}
      </section>
    </div>`;
    const archiveFilters = [...panel.querySelectorAll('.news-multi-select[name="news-archive-filter"]')];
    archiveFilters.forEach((filter) => filter.addEventListener("toggle", () => {
      if (!filter.open) return;
      archiveFilters.forEach((other) => { if (other !== filter) other.open = false; });
    }));
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
    const news = event.target.closest("[data-open-news-review]");
    if (news) activateModule("review");
    if (event.target.closest("[data-open-subscriptions]")) activateModule("subscriptions");
    const newsStage = event.target.closest("[data-news-stage]");
    if (newsStage) {
      openNewsStageDetail(newsStage.dataset.newsStage);
    }
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
    const newsDate = event.target.closest("[data-news-date-option]");
    if (newsDate) {
      if (newsDate.checked) {
        const candidates = state.newsRuns.filter((item) => newsRunDate(item) === newsDate.value);
        const preferred = candidates.find((item) => item.run_status === "completed") || candidates[0];
        if (preferred) state.newsSelectedRunIds = [...new Set([...state.newsSelectedRunIds, preferred.crawl_run_id])].slice(0, 8);
      } else {
        const remaining = state.newsSelectedRunIds.filter((id) => newsRunDate(state.newsRuns.find((item) => item.crawl_run_id === id)) !== newsDate.value);
        if (!remaining.length) { newsDate.checked = true; return; }
        state.newsSelectedRunIds = remaining;
      }
      state.newsSelectedStage = "search";
      updateNewsRunUrl(state.newsSelectedRunIds);
      loadNewsRuns(state.newsSelectedRunIds);
      return;
    }
    const newsRun = event.target.closest("[data-news-run-option]");
    if (newsRun) {
      if (newsRun.checked) state.newsSelectedRunIds = [...new Set([...state.newsSelectedRunIds, newsRun.value])].slice(0, 8);
      else {
        if (state.newsSelectedRunIds.length === 1) { newsRun.checked = true; return; }
        state.newsSelectedRunIds = state.newsSelectedRunIds.filter((id) => id !== newsRun.value);
      }
      state.newsSelectedStage = "search";
      updateNewsRunUrl(state.newsSelectedRunIds);
      loadNewsRuns(state.newsSelectedRunIds);
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
