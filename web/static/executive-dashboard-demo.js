(() => {
  "use strict";

  const SOURCES = {
    interim2026: "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0729/2026072900430.pdf",
    annual2025: "https://www.hkt.com/api-service/assets/e-2025_Annual_Report.pdf",
    esg2025: "https://www.hkt.com/api-service/assets/e-2025_ESG_Report.pdf",
    cmhkBusiness2024: "https://omniapi.hk.chinamobile.com/upload/onlineshop/9208%20%E6%95%B8%E7%A2%BC%E8%BD%89%E5%9E%8B%E6%94%AF%E6%8F%B4%E5%85%88%E5%B0%8E%E8%A8%88%E5%8A%83%E5%A5%97%E9%A4%90%20%E9%9B%BB%E5%AD%90%E7%89%88booklet_FINAL_240621.pdf",
    cmhkStores: "https://www.discoverhongkong.com/eng/travel-guide/qts/shops-results/shops-details.id9615.china-mobile-hong-kong-company-limited.html"
  };

  const missingMetric = (label, extra = {}) => ({
    label, value: "—", unit: "", trend: "未披露", periods: ["未披露"], values: [0], valueLabels: ["—"], ...extra
  });
  const disclosedMetric = (label, value, unit, values = [Number(value)], extra = {}) => ({
    label, value: String(value), unit, trend: "最新披露", periods: values.map(() => "最新披露"), values, ...extra
  });
  const makeNetworkMetrics = () => [
    missingMetric("基站总数（4G）"),
    missingMetric("基站总数（5G）"),
    missingMetric("智算能力 PFLOPS")
  ];
  const makeBusinessGroups = (metrics = {}) => [
    { title: "移动业务", accent: "blue", metrics: [metrics.totalMobile || missingMetric("总移动用户数"), metrics.mobileArpu || missingMetric("移动综合ARPU")] },
    { title: "家庭业务", accent: "green", metrics: [metrics.homeBroadband || missingMetric("家庭宽带用户数"), metrics.homeArpu || missingMetric("家庭户均收益（ARPU）")] },
    { title: "政企业务", accent: "amber", metrics: [metrics.enterpriseCustomers || missingMetric("客户数（大中型企业/中小企业-参考政府公布的分类）"), metrics.projectValue || missingMetric("项目签约额")] }
  ];
  const makeReachMetrics = () => [
    missingMetric("全港实体门市数量", { dial: 0, color: "#55d9ff" }),
    missingMetric("官方手机应用程式 (如MyLink) 活跃用户数", { dial: 0, color: "#5de2b6" })
  ];

  const halfYearPeriods = ["2025H1", "2025H2", "2026H1"];
  const financeMetrics = [
    { label: "营运收入", value: "18.685", unit: "十亿港元", trend: "同比 +8%", periods: halfYearPeriods, values: [17.322, 19.231, 18.685], source: SOURCES.interim2026 },
    { label: "EBITDA率", value: "35.2", unit: "%", trend: "最新披露", periods: halfYearPeriods, values: [36.8, 40.8, 35.2], source: SOURCES.interim2026, gauge: 70 },
    { label: "净利润", value: "2.153", unit: "十亿港元", trend: "同比 +4%", periods: halfYearPeriods, values: [2.070, 3.216, 2.153], source: SOURCES.interim2026, gauge: 72 }
  ];

  const financeCompanyFallbacks = [
    { key: "hkt", company: "HKT", period: "H1 2026", metrics: financeMetrics },
    { key: "three", company: "3香港", period: "H1 2026", metrics: [
      { label: "营运收入", value: "2.846", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [2.846] },
      { label: "EBITDA率", value: "26.8", unit: "%", trend: "最新披露", periods: ["最新披露"], values: [26.8], gauge: 54 },
      { label: "净利润", value: "0.011", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [0.011], gauge: 72 }
    ] },
    { key: "smartone", company: "SmarTone", period: "H1 2026", metrics: [
      { label: "营运收入", value: "3.561", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [3.561] },
      { label: "EBITDA率", value: "—", unit: "", trend: "未披露", periods: ["未披露"], values: [0], valueLabels: ["—"], gauge: 0 },
      { label: "净利润", value: "0.278", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [0.278], gauge: 72 }
    ] },
    { key: "hkbn", company: "HKBN", period: "H1 2026", metrics: [
      { label: "营运收入", value: "6.029", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [6.029] },
      { label: "EBITDA率", value: "20.8", unit: "%", trend: "最新披露", periods: ["最新披露"], values: [20.8], gauge: 42 },
      { label: "净利润", value: "0.108", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [0.108], gauge: 72 }
    ] },
    { key: "icable", company: "i-CABLE", period: "FY 2025", metrics: [
      { label: "营运收入", value: "0.539", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [0.539] },
      { label: "EBITDA率", value: "—", unit: "", trend: "未披露", periods: ["未披露"], values: [0], valueLabels: ["—"], gauge: 0 },
      { label: "净利润", value: "-0.490", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [-0.490], gauge: 72 }
    ] },
    { key: "cmhk", company: "CMHK", period: "未披露", metrics: [
      missingMetric("营运收入"),
      missingMetric("EBITDA率", { gauge: 0 }),
      missingMetric("净利润", { gauge: 0 })
    ] }
  ];
  const operatorProfiles = [
    { key: "hkt", company: "HKT", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      totalMobile: { label: "总移动用户数", value: "4.923", unit: "百万户", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [4.875, 4.817, 4.923] },
      homeBroadband: { label: "家庭宽带用户数", value: "1.497", unit: "百万户", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [1.482, 1.488, 1.497] },
      projectValue: { label: "项目签约额", value: ">2.2", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [2.2], valueLabels: [">2.2"] }
    }), reachMetrics: makeReachMetrics() },
    { key: "three", company: "3香港", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      totalMobile: disclosedMetric("总移动用户数", "8.132", "百万户", [8.132])
    }), reachMetrics: makeReachMetrics() },
    { key: "smartone", company: "SmarTone", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      totalMobile: { label: "总移动用户数", value: "2.75", unit: "百万户", trend: "已披露口径", periods: ["已披露口径"], values: [2.75] }
    }), reachMetrics: makeReachMetrics() },
    { key: "hkbn", company: "HKBN", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      homeBroadband: disclosedMetric("家庭宽带用户数", "0.916", "百万户", [0.916]),
      homeArpu: disclosedMetric("家庭户均收益（ARPU）", "186", "港元/月", [186])
    }), reachMetrics: makeReachMetrics() },
    { key: "icable", company: "i-CABLE", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      homeBroadband: { label: "家庭宽带用户数", value: "0.198", unit: "百万户", trend: "已披露口径", periods: ["已披露口径"], values: [0.198] }
    }), reachMetrics: makeReachMetrics() },
    { key: "cmhk", company: "CMHK", networkMetrics: makeNetworkMetrics(), businessGroups: makeBusinessGroups({
      totalMobile: { label: "总移动用户数", value: "5.0", unit: "百万户", trend: "已披露口径", periods: ["2024年公开材料"], values: [5.0], source: SOURCES.cmhkBusiness2024 }
    }), reachMetrics: [
      { label: "全港实体门市数量", value: "49", unit: "间", trend: "当前列示", periods: ["当前列示"], values: [49], dial: 82, color: "#55d9ff", source: SOURCES.cmhkStores },
      missingMetric("官方手机应用程式 (如MyLink) 活跃用户数", { dial: 0, color: "#5de2b6" })
    ] }
  ];
  let financeCompaniesData = financeCompanyFallbacks;
  let selectedOperator = 0;
  let operatorRotationTimer = null;
  let operatorManualPauseUntil = 0;

  const comparisonSections = [
    { key: "network", number: "01", title: "资源与基础设施层", metricCount: 3 },
    { key: "business", number: "02", title: "客户与业务对标层", metricCount: 6 },
    { key: "reach", number: "03", title: "渠道与品牌触达层", metricCount: 2 },
    { key: "finance", number: "04", title: "财务成果", metricCount: 3 }
  ];

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const displayValue = (metric, index) => metric.valueLabels?.[index] ?? String(metric.values[index]);
  const tooltipText = (metric) => `${metric.label}\n${metric.periods.map((period, index) => `${period}：${displayValue(metric, index)} ${metric.fullUnit || metric.unit}`.trim()).join("\n")}`;

  function renderOperatorTabs(section) {
    return `<div class="operator-tabs" role="tablist" aria-label="本地运营商">
      ${operatorProfiles.map((item, index) => `<button type="button" role="tab" aria-selected="${index === selectedOperator}" data-operator-index="${index}" data-operator-section="${section}" title="查看${escapeHtml(item.company)}"><span>${escapeHtml(item.company)}</span></button>`).join("")}
    </div>`;
  }

  function chartGeometry(values, width, height, padX = 4, padY = 5) {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const points = values.map((value, index) => ({
      x: padX + (index * (width - padX * 2)) / Math.max(1, values.length - 1),
      y: padY + ((max - value) * (height - padY * 2)) / range
    }));
    return { points, line: points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(" ") };
  }

  function sparkline(metric) {
    const { points, line } = chartGeometry(metric.values, 100, 34, 3, 5);
    return `<svg class="metric-sparkline" viewBox="0 0 100 34" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(metric.label)}真实趋势">
      <path d="${line}"/>
      <g class="spark-points">${points.map((point, index) => `<circle cx="${point.x}" cy="${point.y}" r="2.5"><title>${escapeHtml(metric.periods[index])}：${escapeHtml(displayValue(metric, index))} ${escapeHtml(metric.unit)}</title></circle>`).join("")}</g>
    </svg>`;
  }

  const metricCard = (metric, index = 0) => `
    <div class="monitor-kpi has-data-tooltip${metric.value === "—" ? " is-missing" : ""}" tabindex="0" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--metric-order:${index}">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}<small>${escapeHtml(metric.unit)}</small></strong>
      ${metric.trend ? `<em class="${metric.trend.startsWith("-") ? "is-negative" : ""}">${escapeHtml(metric.trend)}</em>` : ""}
      ${metric.value === "—" ? "" : sparkline(metric)}
    </div>`;

  function renderNetwork() {
    const profile = operatorProfiles[selectedOperator];
    const visual = document.querySelector("[data-network-visual]");
    const metrics = document.querySelector("[data-network-metrics]");
    document.querySelector('[data-operator-tabs="network"]').innerHTML = renderOperatorTabs("network");
    const [first, second, third] = profile.networkMetrics;
    visual.innerHTML = `
      <div class="section-label"><span>${escapeHtml(profile.company)} NETWORK</span><strong>网络与连接资源</strong></div>
      <div class="network-architecture" role="img" aria-label="${escapeHtml(profile.company)}网络与连接资源">
        <section class="architecture-stage stage-access">
          <span class="stage-label"><b>01</b> 移动网络基础设施</span>
          <div class="access-stack">
            <div class="architecture-node node-4g"><small>${escapeHtml(first.label)}</small><strong>${escapeHtml(first.value)}<em>${escapeHtml(first.unit)}</em></strong></div>
            <div class="architecture-node node-5g"><small>${escapeHtml(second.label)}</small><strong>${escapeHtml(second.value)}<em>${escapeHtml(second.unit)}</em></strong></div>
          </div>
        </section>
        <section class="architecture-stage stage-backbone">
          <span class="stage-label"><b>02</b> 数据与云基础设施</span>
          <div class="architecture-node node-backbone"><small>${escapeHtml(third.label)}</small><strong>${escapeHtml(third.value)}<em>${escapeHtml(third.unit)}</em></strong></div>
        </section>
        <section class="architecture-stage stage-core">
          <span class="stage-label"><b>03</b> 本地运营商</span>
          <div class="architecture-core"><b>${escapeHtml(profile.company)}</b><span>LOCAL NETWORK</span><small>香港本地通信网络</small></div>
        </section>
        <div class="architecture-caption"><span>4G基站</span><i>→</i><span>5G基站</span><i>→</i><span>智算能力</span></div>
      </div>`;
    metrics.innerHTML = profile.networkMetrics.map(metricCard).join("");
  }

  function renderBusiness() {
    const profile = operatorProfiles[selectedOperator];
    const target = document.querySelector("[data-business-cards]");
    document.querySelector('[data-operator-tabs="business"]').innerHTML = renderOperatorTabs("business");
    target.innerHTML = profile.businessGroups.map((group) => `
      <section class="business-card ${group.accent}">
        <header><strong>${escapeHtml(group.title)}</strong></header>
        <div class="business-pair">${group.metrics.map(metricCard).join("")}</div>
      </section>`).join("");
  }

  function renderReach() {
    const profile = operatorProfiles[selectedOperator];
    const target = document.querySelector("[data-reach-content]");
    target.innerHTML = renderOperatorTabs("reach") + profile.reachMetrics.map((metric, index) => {
      const max = Math.max(...metric.values, 1);
      return `<section class="reach-dial-card has-data-tooltip${metric.value === "—" ? " is-missing" : ""}" tabindex="0" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--dial:${metric.dial || 0}; --dial-color:${metric.color}">
        <div class="reach-dial" aria-hidden="true"><i></i><span></span><b>0${index + 1}</b></div>
        <div class="reach-dial-copy">
          <span>${escapeHtml(metric.label)}</span>
          <strong>${escapeHtml(metric.value)}<small>${escapeHtml(metric.unit)}</small></strong>
          <em>${escapeHtml(metric.trend)}</em>
          ${metric.value === "—" ? "" : `<div class="reach-wave" aria-label="${escapeHtml(metric.label)}真实趋势">${metric.values.map((value, valueIndex) => `<i style="height:${Math.max(18, (value / max) * 82)}%"><span>${escapeHtml(metric.periods[valueIndex])}：${escapeHtml(value)} ${escapeHtml(metric.unit)}</span></i>`).join("")}</div>`}
        </div>
      </section>`;
    }).join("");
  }

  function financeChart(metric, company) {
    const { points, line } = chartGeometry(metric.values, 480, 170, 0, 24);
    const area = `${line} L480 170 L0 170 Z`;
    return `<svg class="finance-area-chart" viewBox="0 0 480 170" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(company)}营运收入趋势">
      <defs><linearGradient id="financeArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#54d9ff" stop-opacity=".42"/><stop offset="1" stop-color="#357ee8" stop-opacity="0"/></linearGradient></defs>
      <path class="finance-grid-line" d="M0 42H480M0 85H480M0 128H480"/>
      <path class="finance-area" d="${area}"/>
      <path class="finance-line" d="${line}"/>
      <g class="finance-points">${points.map((point, index) => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(metric.periods[index])}：${escapeHtml(metric.values[index])} ${escapeHtml(metric.unit)}</title></circle>`).join("")}</g>
    </svg>`;
  }

  function renderFinance() {
    const target = document.querySelector("[data-finance-content]");
    const selected = financeCompaniesData[selectedOperator] || financeCompaniesData[0];
    const metrics = selected.metrics;
    const revenue = metrics[0];
    target.innerHTML = `
      ${renderOperatorTabs("finance")}
      <section class="finance-revenue-hero has-data-tooltip" tabindex="0" data-tooltip="${escapeHtml(tooltipText(revenue))}">
        <div class="finance-revenue-copy"><span>${escapeHtml(revenue.label)}</span><strong>${escapeHtml(revenue.value)}<small>${escapeHtml(revenue.unit)}</small></strong><em>${escapeHtml(revenue.trend)}</em></div>
        ${financeChart(revenue, selected.company)}
      </section>
      <div class="finance-gauge-stack">${metrics.slice(1).map((metric, index) => `
        <section class="finance-gauge-card gauge-${index + 1} has-data-tooltip${metric.value === "—" ? " is-missing" : ""}" tabindex="0" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--gauge:${metric.gauge}">
          <div class="finance-gauge" aria-hidden="true"><i></i><span></span></div>
          ${metricCard(metric, index)}
      </section>`).join("")}</div>`;
  }

  function metricNumber(value) {
    const text = String(value || "").replace(/,/g, "");
    const match = text.match(/\d+(?:\.\d+)?/);
    if (!match || /nil|n\/a|not disclosed|未披露|—/i.test(text)) return null;
    const sign = /-\s*(?:HK\$)?\s*\d/.test(text) ? -1 : 1;
    const number = Number(match[0]) * sign;
    return /\bmillion\b/i.test(text) ? number / 1000 : number;
  }

  function companyKey(name) {
    if (/^HKT$/i.test(name)) return "hkt";
    if (/3HK|3香港|Hutchison/i.test(name)) return "three";
    if (/SmarTone/i.test(name)) return "smartone";
    if (/HKBN/i.test(name)) return "hkbn";
    if (/i-CABLE/i.test(name)) return "icable";
    if (/CMHK|China Mobile Hong Kong|中国移动香港|中國移動香港/i.test(name)) return "cmhk";
    return String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
  }

  function normalizeFinancialReport(report) {
    const values = new Map((report.metrics || []).map((metric) => [metric.metric_key, metric.value]));
    const revenue = metricNumber(values.get("revenue"));
    const ebitda = metricNumber(values.get("ebitda"));
    const profit = metricNumber(values.get("net_profit"));
    const margin = Number.isFinite(revenue) && revenue !== 0 && Number.isFinite(ebitda) ? (ebitda / revenue) * 100 : null;
    const normalized = [
      { label: "营运收入", numeric: revenue, unit: "十亿港元", decimals: 3 },
      { label: "EBITDA率", numeric: margin, unit: "%", decimals: 1 },
      { label: "净利润", numeric: profit, unit: "十亿港元", decimals: 3 }
    ];
    return {
      key: companyKey(report.company),
      company: companyKey(report.company) === "three" ? "3香港" : report.company,
      period: report.period || "最新披露期",
      metrics: normalized.map(({ label, numeric, unit, decimals }, index) => {
        const disclosed = Number.isFinite(numeric);
        return {
          label,
          value: disclosed ? numeric.toFixed(decimals) : "—",
          unit: disclosed ? unit : "",
          trend: disclosed ? "最新披露" : "未披露",
          periods: [disclosed ? "最新披露" : "未披露"],
          values: [disclosed ? numeric : 0],
          valueLabels: [disclosed ? numeric.toFixed(decimals) : "—"],
          gauge: disclosed ? (index === 1 ? Math.min(100, numeric * 2) : 72) : 0
        };
      })
    };
  }

  function refreshFinancialCompanies() {
    return fetch("/api/executive-intelligence", { cache: "no-store" })
      .then((response) => response.json().then((data) => ({ response, data })))
      .then(({ response, data }) => {
        if (!response.ok || !data.ok) throw new Error(data.error || "财务数据读取失败");
        const local = (data.domains || []).find((domain) => domain.id === "local");
        const reports = Array.isArray(local?.latest_financial_results) ? local.latest_financial_results : [];
        if (!reports.length) return;
        const byKey = new Map(reports.map((report) => [companyKey(report.company), normalizeFinancialReport(report)]));
        financeCompaniesData = financeCompanyFallbacks.map((fallback) => byKey.get(fallback.key) || fallback);
        selectedOperator = Math.min(selectedOperator, financeCompaniesData.length - 1);
        renderFinance();
        renderComparison();
      })
      .catch(() => {});
  }

  function renderOperatorPanels({ animate = false } = {}) {
    renderNetwork();
    renderBusiness();
    renderReach();
    renderFinance();
    const overview = document.querySelector("[data-overview-view]");
    overview.setAttribute("aria-label", `${operatorProfiles[selectedOperator].company}战略监控四层体系`);
    if (!animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    overview.querySelectorAll(".monitor-content").forEach((content) => {
      content.classList.remove("is-operator-switching");
      void content.offsetWidth;
      content.classList.add("is-operator-switching");
    });
  }

  function selectOperator(index, { manual = false, focusSection = "" } = {}) {
    selectedOperator = (index + operatorProfiles.length) % operatorProfiles.length;
    if (manual) operatorManualPauseUntil = Date.now() + 12000;
    renderOperatorPanels({ animate: true });
    if (focusSection) document.querySelector(`[data-operator-section="${focusSection}"][data-operator-index="${selectedOperator}"]`)?.focus();
  }

  function setupOperatorTabs() {
    const overview = document.querySelector("[data-overview-view]");
    overview.addEventListener("click", (event) => {
      const button = event.target.closest("[data-operator-index]");
      if (!button) return;
      selectOperator(Number(button.dataset.operatorIndex) || 0, { manual: true, focusSection: button.dataset.operatorSection });
    });
    overview.addEventListener("keydown", (event) => {
      const button = event.target.closest("[data-operator-index]");
      if (!button || !["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const current = Number(button.dataset.operatorIndex) || 0;
      const next = event.key === "Home" ? 0 : event.key === "End" ? operatorProfiles.length - 1 : current + (event.key === "ArrowRight" ? 1 : -1);
      selectOperator(next, { manual: true, focusSection: button.dataset.operatorSection });
    });
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    operatorRotationTimer = window.setInterval(() => {
      const overviewVisible = !document.querySelector("[data-overview-view]")?.hidden;
      if (!overviewVisible || document.hidden || Date.now() < operatorManualPauseUntil) return;
      selectOperator(selectedOperator + 1);
    }, 5000);
  }

  function comparisonRows(rows) {
    const max = Math.max(...rows.map((item) => Math.abs(item.value || 0)), 1);
    return `<div class="comparison-table" role="table">
      ${rows.map((item) => {
        const width = item.value === null ? 0 : Math.max(2, (Math.abs(item.value) / max) * 100);
        return `<div class="comparison-row${item.value === null ? " is-missing" : ""}${item.value < 0 ? " is-negative" : ""}" role="row" aria-label="${escapeHtml(`${item.company} ${item.display}`)}">
          <span class="comparison-company" role="cell">${escapeHtml(item.company)}</span>
          <span class="comparison-meter" role="cell"><i style="--bar:${width}%"></i></span>
          <strong role="cell">${escapeHtml(item.display)}</strong>
          <small role="cell">${escapeHtml(item.status)}</small>
        </div>`;
      }).join("")}
    </div>`;
  }

  function sectionMetrics(sectionKey, companyIndex) {
    if (sectionKey === "finance") return financeCompaniesData[companyIndex]?.metrics || [];
    const profile = operatorProfiles[companyIndex];
    if (sectionKey === "network") return profile.networkMetrics;
    if (sectionKey === "reach") return profile.reachMetrics;
    return profile.businessGroups.flatMap((group) => group.metrics);
  }

  function comparisonMetric(sectionKey, metricIndex) {
    const metrics = operatorProfiles.map((profile, companyIndex) => ({ profile, metric: sectionMetrics(sectionKey, companyIndex)[metricIndex] }));
    const label = metrics.find((item) => item.metric)?.metric.label || "指标";
    return {
      label,
      rows: metrics.map(({ profile, metric }) => {
        const numeric = metric?.value === "—" ? null : Number(metric?.values?.at(-1));
        return {
          company: profile.company,
          value: Number.isFinite(numeric) ? numeric : null,
          display: metric?.value === "—" ? "—" : `${metric?.value || "—"}${metric?.unit ? ` ${metric.unit}` : ""}`,
          status: metric?.value === "—" ? "未披露" : (metric?.trend || "最新披露")
        };
      })
    };
  }

  function comparisonPanel(panel) {
    const labels = sectionMetrics(panel.key, 0).map((metric) => metric.label);
    const metric = comparisonMetric(panel.key, 0);
    return `<article class="panel comparison-panel is-visible">
      <header class="panel-heading"><span>${escapeHtml(panel.number)}</span><h2>${escapeHtml(panel.title)}</h2></header>
      <div class="monitor-content comparison-content">
        <div class="comparison-toolbar comparison-finance-toolbar">
          <div class="comparison-metric-tabs" role="tablist" aria-label="${escapeHtml(panel.title)}对比指标">
            ${labels.map((label, index) => `<button type="button" role="tab" aria-selected="${index === 0}" data-comparison-section="${escapeHtml(panel.key)}" data-comparison-metric="${index}">${escapeHtml(label)}</button>`).join("")}
          </div>
          <em>六家本地运营商</em>
        </div>
        <div data-comparison-rows="${escapeHtml(panel.key)}">${comparisonRows(metric.rows)}</div>
        <p class="comparison-scope-note">只展示大屏指标；未披露同口径数据时显示“—”。</p>
      </div>
    </article>`;
  }

  function renderComparison() {
    const target = document.querySelector("[data-comparison-view]");
    target.innerHTML = comparisonSections.map(comparisonPanel).join("");
  }

  function setupComparisonMetricTabs() {
    const comparison = document.querySelector("[data-comparison-view]");
    comparison.addEventListener("click", (event) => {
      const button = event.target.closest("[data-comparison-metric]");
      if (!button) return;
      const sectionKey = button.dataset.comparisonSection;
      const panel = button.closest(".comparison-panel");
      panel.querySelectorAll("[data-comparison-metric]").forEach((item) => item.setAttribute("aria-selected", String(item === button)));
      const metric = comparisonMetric(sectionKey, Number(button.dataset.comparisonMetric) || 0);
      panel.querySelector(`[data-comparison-rows="${sectionKey}"]`).innerHTML = comparisonRows(metric.rows);
    });
  }

  function setupViewTabs() {
    const buttons = Array.from(document.querySelectorAll("[data-monitor-view]"));
    const overview = document.querySelector("[data-overview-view]");
    const comparison = document.querySelector("[data-comparison-view]");
    buttons.forEach((button) => button.addEventListener("click", () => {
      const showComparison = button.dataset.monitorView === "comparison";
      overview.hidden = showComparison;
      comparison.hidden = !showComparison;
      buttons.forEach((item) => item.setAttribute("aria-selected", String(item === button)));
      if (showComparison) comparison.querySelectorAll(".panel").forEach((panel) => panel.classList.add("is-visible"));
    }));
  }

  function setupMotion() {
    const panels = Array.from(document.querySelectorAll(".panel"));
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    panels.forEach((panel, index) => {
      panel.style.setProperty("--panel-delay", `${index * 70}ms`);
      panel.addEventListener("pointermove", (event) => {
        const rect = panel.getBoundingClientRect();
        panel.style.setProperty("--pointer-x", `${event.clientX - rect.left}px`);
        panel.style.setProperty("--pointer-y", `${event.clientY - rect.top}px`);
      });
    });
    if (reducedMotion) {
      panels.forEach((panel) => panel.classList.add("is-visible"));
      return;
    }
    document.body.classList.add("motion-enabled");
    if (!("IntersectionObserver" in window)) {
      window.requestAnimationFrame(() => panels.forEach((panel) => panel.classList.add("is-visible")));
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.12 });
    panels.forEach((panel) => observer.observe(panel));
  }

  renderOperatorPanels();
  setupOperatorTabs();
  refreshFinancialCompanies();
  renderComparison();
  setupComparisonMetricTabs();
  setupViewTabs();
  setupMotion();
})();
