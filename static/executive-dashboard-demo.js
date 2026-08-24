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

  const comparisonSections = [
    { key: "network", number: "01", title: "资源与基础设施层", metricCount: 3, chartTypes: ["column", "lollipop", "bar"] },
    { key: "business", number: "02", title: "客户与业务对标层", metricCount: 6, chartTypes: ["donut", "line", "column", "lollipop", "line", "bar"] },
    { key: "reach", number: "03", title: "渠道与品牌触达层", metricCount: 2, chartTypes: ["column", "line"] },
    { key: "finance", number: "04", title: "财务成果", metricCount: 3, chartTypes: ["line", "lollipop", "diverging"] }
  ];
  const chartColors = ["#64cdf4", "#5c9cff", "#60d9aa", "#efb354", "#b68cff", "#f37f8c"];
  const chartTypeNames = { column: "柱状图", lollipop: "棒棒糖图", bar: "横向条形图", donut: "环形图", line: "折线图", diverging: "正负发散条形图" };

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

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
        renderComparison();
      })
      .catch(() => {});
  }

  function emptyChart(metricLabel, chartType) {
    return `<svg class="comparison-chart comparison-chart-empty" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}${chartTypeNames[chartType]}，暂无披露数据`)}">
      <circle cx="90" cy="54" r="31" fill="none" stroke="rgba(122,166,187,.28)" stroke-width="8" stroke-dasharray="4 6"></circle>
      <text x="90" y="58" text-anchor="middle">暂无披露</text>
    </svg>`;
  }

  function columnChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(metricLabel, "column");
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}六家本地运营商柱状图`)}">
      <line x1="12" y1="91" x2="168" y2="91" class="chart-axis"></line>
      ${rows.map((item, index) => {
        const height = item.value === null ? 0 : Math.max(3, (Math.abs(item.value) / max) * 66);
        const x = 17 + (index * 26);
        return `<g class="${item.value === null ? "chart-mark-missing" : ""}">
          ${item.value === null ? `<line x1="${x}" y1="87" x2="${x + 14}" y2="87" class="chart-missing-line"></line>` : `<rect x="${x}" y="${91 - height}" width="14" height="${height}" rx="2" fill="${chartColors[index]}"></rect>`}
          <text x="${x + 7}" y="108" text-anchor="middle">${escapeHtml(item.company.replace("香港", ""))}</text>
        </g>`;
      }).join("")}
    </svg>`;
  }

  function horizontalChart(rows, metricLabel, chartType) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(metricLabel, chartType);
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    const isLollipop = chartType === "lollipop";
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}六家本地运营商${chartTypeNames[chartType]}`)}">
      ${rows.map((item, index) => {
        const y = 13 + (index * 18);
        const width = item.value === null ? 0 : Math.max(3, (Math.abs(item.value) / max) * 118);
        return `<g class="${item.value === null ? "chart-mark-missing" : ""}">
          <text x="4" y="${y + 4}">${escapeHtml(item.company.replace("香港", ""))}</text>
          <line x1="52" y1="${y}" x2="170" y2="${y}" class="chart-track"></line>
          ${item.value === null ? `<line x1="52" y1="${y}" x2="60" y2="${y}" class="chart-missing-line"></line>` : isLollipop ? `<line x1="52" y1="${y}" x2="${52 + width}" y2="${y}" stroke="${chartColors[index]}" class="chart-lollipop-line"></line><circle cx="${52 + width}" cy="${y}" r="4" fill="${chartColors[index]}"></circle>` : `<rect x="52" y="${y - 4}" width="${width}" height="8" rx="4" fill="${chartColors[index]}"></rect>`}
        </g>`;
      }).join("")}
    </svg>`;
  }

  function lineChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(metricLabel, "line");
    const values = disclosed.map((item) => item.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.max(Math.abs(max), 1);
    const point = (item, index) => ({ x: 17 + (index * 29), y: 84 - (((item.value - min) / range) * 58) });
    const segments = [];
    let current = [];
    rows.forEach((item, index) => {
      if (item.value === null) {
        if (current.length) segments.push(current);
        current = [];
      } else current.push(point(item, index));
    });
    if (current.length) segments.push(current);
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}六家本地运营商折线图，缺失值留空`)}">
      <line x1="12" y1="88" x2="168" y2="88" class="chart-axis"></line>
      ${segments.filter((segment) => segment.length > 1).map((segment) => `<polyline points="${segment.map(({ x, y }) => `${x},${y}`).join(" ")}" class="chart-line"></polyline>`).join("")}
      ${rows.map((item, index) => {
        const x = 17 + (index * 29);
        if (item.value === null) return `<g class="chart-mark-missing"><line x1="${x - 4}" y1="84" x2="${x + 4}" y2="84" class="chart-missing-line"></line><text x="${x}" y="106" text-anchor="middle">${escapeHtml(item.company.replace("香港", ""))}</text></g>`;
        const { y } = point(item, index);
        return `<g><circle cx="${x}" cy="${y}" r="4" fill="${chartColors[index]}"></circle><text x="${x}" y="106" text-anchor="middle">${escapeHtml(item.company.replace("香港", ""))}</text></g>`;
      }).join("")}
    </svg>`;
  }

  function donutChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null && item.value > 0);
    if (disclosed.length < 2) return columnChart(rows, metricLabel);
    const total = disclosed.reduce((sum, item) => sum + item.value, 0);
    const radius = 36;
    const circumference = 2 * Math.PI * radius;
    let offset = 0;
    const rings = disclosed.map((item) => {
      const index = rows.indexOf(item);
      const length = (item.value / total) * circumference;
      const ring = `<circle cx="72" cy="56" r="${radius}" fill="none" stroke="${chartColors[index]}" stroke-width="18" stroke-dasharray="${length} ${circumference - length}" stroke-dashoffset="${-offset}" transform="rotate(-90 72 56)"></circle>`;
      offset += length;
      return ring;
    }).join("");
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}已披露运营商构成环形图`)}">
      <circle cx="72" cy="56" r="${radius}" fill="none" class="chart-track-ring" stroke-width="18"></circle>
      ${rings}
      <text x="72" y="53" text-anchor="middle" class="chart-donut-total">已披露</text>
      <text x="72" y="66" text-anchor="middle" class="chart-donut-count">${disclosed.length} 家</text>
      ${disclosed.map((item, index) => `<g transform="translate(128 ${28 + index * 18})"><circle r="4" fill="${chartColors[rows.indexOf(item)]}"></circle><text x="8" y="4">${escapeHtml(item.company.replace("香港", ""))}</text></g>`).join("")}
    </svg>`;
  }

  function divergingChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(metricLabel, "diverging");
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}六家本地运营商正负发散条形图`)}">
      <line x1="91" y1="5" x2="91" y2="111" class="chart-axis chart-zero-axis"></line>
      ${rows.map((item, index) => {
        const y = 10 + (index * 18);
        const width = item.value === null ? 0 : Math.max(3, (Math.abs(item.value) / max) * 70);
        const x = item.value < 0 ? 91 - width : 91;
        return `<g class="${item.value === null ? "chart-mark-missing" : ""}"><text x="4" y="${y + 4}">${escapeHtml(item.company.replace("香港", ""))}</text>${item.value === null ? `<line x1="87" y1="${y}" x2="95" y2="${y}" class="chart-missing-line"></line>` : `<rect x="${x}" y="${y - 4}" width="${width}" height="8" rx="4" fill="${item.value < 0 ? "#efb354" : chartColors[index]}"></rect>`}</g>`;
      }).join("")}
    </svg>`;
  }

  function comparisonChart(rows, metricLabel, chartType) {
    if (chartType === "column") return columnChart(rows, metricLabel);
    if (chartType === "lollipop" || chartType === "bar") return horizontalChart(rows, metricLabel, chartType);
    if (chartType === "donut") return donutChart(rows, metricLabel);
    if (chartType === "diverging") return divergingChart(rows, metricLabel);
    return lineChart(rows, metricLabel);
  }

  function comparisonValues(rows, metricLabel) {
    return `<div class="comparison-values" role="table" aria-label="${escapeHtml(metricLabel)}六家本地运营商完整数值">
      ${rows.map((item, index) => `<div class="comparison-value-row${item.value === null ? " is-missing" : ""}${item.value < 0 ? " is-negative" : ""}" role="row" aria-label="${escapeHtml(`${item.company} ${item.display} ${item.status}`)}">
        <i style="--series-color:${chartColors[index]}" aria-hidden="true"></i>
        <span class="comparison-company" role="cell">${escapeHtml(item.company)}</span>
        <strong role="cell">${escapeHtml(item.display)}</strong>
        <small role="cell">${escapeHtml(item.status)}</small>
      </div>`).join("")}
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
    const metrics = Array.from({ length: panel.metricCount }, (_, index) => comparisonMetric(panel.key, index));
    return `<article class="panel panel-${escapeHtml(panel.key)} comparison-panel is-visible">
      <header class="panel-heading"><span>${escapeHtml(panel.number)}</span><h2>${escapeHtml(panel.title)}</h2></header>
      <div class="monitor-content comparison-content">
        <div class="comparison-metric-grid comparison-metric-grid-${metrics.length}">
          ${metrics.map((metric, index) => {
            const chartType = panel.chartTypes[index];
            return `<section class="comparison-metric-card" data-chart-type="${escapeHtml(chartType)}" aria-labelledby="${escapeHtml(`${panel.key}-metric-${index}`)}">
            <header><h3 id="${escapeHtml(`${panel.key}-metric-${index}`)}">${escapeHtml(metric.label)}</h3></header>
            <div class="comparison-chart-layout">
              ${comparisonChart(metric.rows, metric.label, chartType)}
              ${comparisonValues(metric.rows, metric.label)}
            </div>
          </section>`;
          }).join("")}
        </div>
      </div>
    </article>`;
  }

  function renderComparison() {
    const target = document.querySelector("[data-comparison-view]");
    target.innerHTML = comparisonSections.map(comparisonPanel).join("");
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

  renderComparison();
  setupMotion();
  refreshFinancialCompanies();
})();
