(() => {
  "use strict";

  const SOURCES = {
    interim2026: "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0729/2026072900430.pdf",
    annual2025: "https://www.hkt.com/api-service/assets/e-2025_Annual_Report.pdf",
    esg2025: "https://www.hkt.com/api-service/assets/e-2025_ESG_Report.pdf"
  };

  const networkMetrics = [
    { label: "5G网络香港覆盖率", value: "99", unit: "%", trend: "2025年末", periods: ["2025年末"], values: [99], source: SOURCES.esg2025 },
    { label: "Wi-Fi热点", value: "19,097", unit: "个", trend: "2025年末", periods: ["2025年末"], values: [19097], valueLabels: ["19,097"], source: SOURCES.esg2025 },
    { label: "2025年新增流动通信站点", value: "94", unit: "个", trend: "2025年", periods: ["2025"], values: [94], source: SOURCES.annual2025 }
  ];

  const businessGroups = [
    { title: "移动业务", accent: "blue", metrics: [
      { label: "移动用户数", value: "4.923", unit: "百万户", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [4.875, 4.817, 4.923], source: SOURCES.interim2026 },
      { label: "5G用户数", value: "2.2", unit: "百万户", trend: "同比 +16%", periods: ["2025年12月", "2026年6月"], values: [2.096, 2.2], source: SOURCES.interim2026 }
    ] },
    { title: "宽带业务", accent: "green", metrics: [
      { label: "零售住宅宽带线路", value: "1.497", unit: "百万条", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [1.482, 1.488, 1.497], source: SOURCES.interim2026 },
      { label: "FTTH光纤到户连接", value: "1.101", unit: "百万条", trend: "同比 +4%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [1.055, 1.086, 1.101], source: SOURCES.interim2026 }
    ] },
    { title: "企业与数据业务", accent: "amber", metrics: [
      { label: "新签企业项目金额", value: ">2.2", unit: "十亿港元", trend: "2026年上半年", periods: ["2026H1"], values: [2.2], valueLabels: [">2.2"], source: SOURCES.interim2026 },
      { label: "本地数据服务收入", value: "7.265", unit: "十亿港元", trend: "同比 +6%", periods: ["2026H1"], values: [7.265], source: SOURCES.interim2026 }
    ] }
  ];

  const reachMetrics = [
    { label: "The Club会员", value: "4.226", unit: "百万名", trend: "同比 +4%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [4.070, 4.148, 4.226], source: SOURCES.interim2026, dial: 84, color: "#55d9ff" },
    { label: "Now TV已安装用户", value: "1.490", unit: "百万户", trend: "同比 +3%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [1.448, 1.464, 1.490], source: SOURCES.interim2026, dial: 74, color: "#5de2b6" }
  ];

  const halfYearPeriods = ["2025H1", "2025H2", "2026H1"];
  const financeMetrics = [
    { label: "总收入", value: "18.685", unit: "十亿港元", trend: "同比 +8%", periods: halfYearPeriods, values: [17.322, 19.231, 18.685], source: SOURCES.interim2026 },
    { label: "EBITDA", value: "6.586", unit: "十亿港元", trend: "同比 +3%", periods: halfYearPeriods, values: [6.380, 7.854, 6.586], source: SOURCES.interim2026, gauge: 74 },
    { label: "股份合订单位持有人应占溢利", value: "2.153", unit: "十亿港元", trend: "同比 +4%", periods: halfYearPeriods, values: [2.070, 3.216, 2.153], source: SOURCES.interim2026, gauge: 72 }
  ];

  const financeCompanyFallbacks = [
    { key: "hkt", company: "HKT", period: "H1 2026", metrics: financeMetrics },
    { key: "three", company: "3香港", period: "H1 2026", metrics: [
      { label: "总收入", value: "2.846", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [2.846] },
      { label: "EBITDA", value: "0.763", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [0.763], gauge: 74 },
      { label: "净利润", value: "0.011", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [0.011], gauge: 72 }
    ] },
    { key: "smartone", company: "SmarTone", period: "H1 2026", metrics: [
      { label: "总收入", value: "3.561", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [3.561] },
      { label: "EBITDA", value: "—", unit: "", trend: "未披露", periods: ["H1 2026"], values: [0], valueLabels: ["—"], gauge: 0 },
      { label: "净利润", value: "0.278", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [0.278], gauge: 72 }
    ] },
    { key: "hkbn", company: "HKBN", period: "H1 2026", metrics: [
      { label: "总收入", value: "6.029", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [6.029] },
      { label: "EBITDA", value: "1.257", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [1.257], gauge: 74 },
      { label: "净利润", value: "0.108", unit: "十亿港元", trend: "H1 2026", periods: ["H1 2026"], values: [0.108], gauge: 72 }
    ] },
    { key: "icable", company: "i-CABLE", period: "FY 2025", metrics: [
      { label: "总收入", value: "0.539", unit: "十亿港元", trend: "FY 2025", periods: ["FY 2025"], values: [0.539] },
      { label: "EBITDA", value: "—", unit: "", trend: "未披露", periods: ["FY 2025"], values: [0], valueLabels: ["—"], gauge: 0 },
      { label: "净利润", value: "-0.490", unit: "十亿港元", trend: "FY 2025", periods: ["FY 2025"], values: [-0.490], gauge: 72 }
    ] }
  ];
  const missingMetric = (label) => ({
    label, value: "—", unit: "", trend: "未披露", periods: ["未披露"], values: [0], valueLabels: ["—"]
  });
  const operatorProfiles = [
    { key: "hkt", company: "HKT", networkMetrics, businessGroups, reachMetrics },
    { key: "three", company: "3香港", networkMetrics: [
      { label: "5G客户渗透率", value: "62", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [62] },
      { label: "移动后付客户", value: "1.289", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [1.289] },
      missingMetric("网络节点与设施")
    ], businessGroups: [
      { title: "移动业务", accent: "blue", metrics: [
        { label: "移动后付客户", value: "1.289", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [1.289] },
        { label: "5G客户渗透率", value: "62", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [62] }
      ] },
      { title: "宽带业务", accent: "green", metrics: [missingMetric("住宅宽带客户"), missingMetric("FTTH连接")] },
      { title: "企业与数据业务", accent: "amber", metrics: [missingMetric("企业客户"), missingMetric("数据业务收入")] }
    ], reachMetrics: [
      { label: "登记客户连接", value: "8.132", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [8.132], dial: 78, color: "#55d9ff" },
      { label: "预付客户连接", value: "6.843", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [6.843], dial: 66, color: "#5de2b6" }
    ] },
    { key: "smartone", company: "SmarTone", networkMetrics: [
      { label: "5G客户渗透率", value: "40", unit: "%", trend: "最新披露", periods: ["FY2024"], values: [40] },
      { label: "5G家宽收入增长", value: "≥33", unit: "%", trend: "最新披露", periods: ["FY2024"], values: [33], valueLabels: ["≥33"] },
      { label: "5G家宽EBITDA增长", value: "18", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [18] }
    ], businessGroups: [
      { title: "移动业务", accent: "blue", metrics: [
        { label: "移动客户", value: "2.75", unit: "百万户", trend: "已披露口径", periods: ["FY2022"], values: [2.75] },
        { label: "5G客户渗透率", value: "40", unit: "%", trend: "最新披露", periods: ["FY2024"], values: [40] }
      ] },
      { title: "宽带业务", accent: "green", metrics: [
        { label: "5G家宽收入增长", value: "≥33", unit: "%", trend: "最新披露", periods: ["FY2024"], values: [33], valueLabels: ["≥33"] },
        { label: "5G家宽EBITDA增长", value: "18", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [18] }
      ] },
      { title: "企业与数据业务", accent: "amber", metrics: [missingMetric("企业客户"), missingMetric("数据业务收入")] }
    ], reachMetrics: [
      { label: "移动客户", value: "2.75", unit: "百万户", trend: "已披露口径", periods: ["FY2022"], values: [2.75], dial: 70, color: "#55d9ff" },
      { label: "移动后付期末ARPU", value: "213", unit: "港元/月", trend: "已披露口径", periods: ["FY2022"], values: [213], dial: 64, color: "#5de2b6" }
    ] },
    { key: "hkbn", company: "HKBN", networkMetrics: [
      { label: "网络覆盖家庭", value: "2.646", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [2.646] },
      { label: "商业楼宇覆盖", value: "8,220", unit: "幢", trend: "最新披露", periods: ["FY2025"], values: [8220], valueLabels: ["8,220"] },
      missingMetric("移动通信站点")
    ], businessGroups: [
      { title: "移动业务", accent: "blue", metrics: [missingMetric("移动后付客户"), missingMetric("5G客户渗透率")] },
      { title: "宽带业务", accent: "green", metrics: [
        { label: "住宅宽带客户", value: "0.907", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [0.907] },
        { label: "网络覆盖家庭", value: "2.646", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [2.646] }
      ] },
      { title: "企业与数据业务", accent: "amber", metrics: [
        { label: "商业楼宇覆盖", value: "8,220", unit: "幢", trend: "最新披露", periods: ["FY2025"], values: [8220], valueLabels: ["8,220"] },
        { label: "企业客户流失率", value: "1.2", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [1.2] }
      ] }
    ], reachMetrics: [
      { label: "网络覆盖家庭", value: "2.646", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [2.646], dial: 82, color: "#55d9ff" },
      { label: "商业楼宇覆盖", value: "8,220", unit: "幢", trend: "最新披露", periods: ["FY2025"], values: [8220], valueLabels: ["8,220"], dial: 68, color: "#5de2b6" }
    ] },
    { key: "icable", company: "i-CABLE", networkMetrics: [
      { label: "免费电视人口覆盖率", value: "99", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [99] },
      { label: "网络覆盖家庭", value: ">2.3", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [2.3], valueLabels: [">2.3"] },
      missingMetric("网络节点与设施")
    ], businessGroups: [
      { title: "移动业务", accent: "blue", metrics: [missingMetric("移动后付客户"), missingMetric("5G客户渗透率")] },
      { title: "宽带业务", accent: "green", metrics: [
        { label: "住宅宽带客户", value: "0.198", unit: "百万户", trend: "已披露口径", periods: ["FY2022"], values: [0.198] },
        { label: "网络覆盖家庭", value: ">2.3", unit: "百万户", trend: "最新披露", periods: ["FY2025"], values: [2.3], valueLabels: [">2.3"] }
      ] },
      { title: "电视与内容业务", accent: "amber", metrics: [
        { label: "收费电视客户", value: "0.662", unit: "百万户", trend: "已披露口径", periods: ["FY2022"], values: [0.662] },
        { label: "免费电视人口覆盖率", value: "99", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [99] }
      ] }
    ], reachMetrics: [
      { label: "收费电视客户", value: "0.662", unit: "百万户", trend: "已披露口径", periods: ["FY2022"], values: [0.662], dial: 64, color: "#55d9ff" },
      { label: "免费电视人口覆盖率", value: "99", unit: "%", trend: "最新披露", periods: ["FY2025"], values: [99], dial: 92, color: "#5de2b6" }
    ] }
  ];
  let financeCompaniesData = financeCompanyFallbacks;
  let selectedOperator = 0;
  let operatorRotationTimer = null;
  let operatorManualPauseUntil = 0;

  const COMPARISON_SOURCES = {
    hkt: SOURCES.annual2025,
    three: "https://www.hthkh.com/en/ir/reports/ar2025/ar2025.pdf",
    smartone: "https://www.smartoneholdings.com/about/investor/financial_reports/english/2024_2025_annual.pdf",
    hkbn: "https://reg.hkbn.net/WwwCMS/upload/pdf/en/e_AnnualReport_2025.pdf"
  };

  const comparisonPanels = [
    {
      number: "01",
      title: "移动后付客户",
      note: "FY2025年末 · 百万户",
      rows: [
        { company: "HKT", value: 3.494, display: "3.494", period: "2025-12-31", source: COMPARISON_SOURCES.hkt },
        { company: "3香港", value: 1.289, display: "1.289", period: "2025-12-31", source: COMPARISON_SOURCES.three },
        { company: "SmarTone", value: null, display: "-", period: "未披露同口径", source: COMPARISON_SOURCES.smartone },
        { company: "HKBN", value: null, display: "-", period: "未披露同口径", source: COMPARISON_SOURCES.hkbn }
      ]
    },
    {
      number: "02",
      title: "5G客户渗透率",
      note: "FY2025年末 · %后付客户",
      suffix: "%",
      rows: [
        { company: "HKT", value: 60, display: "60", period: "2025-12-31", source: COMPARISON_SOURCES.hkt },
        { company: "3香港", value: 62, display: "62", period: "2025-12-31", source: COMPARISON_SOURCES.three },
        { company: "SmarTone", value: null, display: "-", period: "FY2025未披露", source: COMPARISON_SOURCES.smartone },
        { company: "HKBN", value: null, display: "-", period: "不适用", source: COMPARISON_SOURCES.hkbn }
      ]
    },
    {
      number: "03",
      title: "住宅宽带客户",
      note: "FY2025年末 · 百万户",
      rows: [
        { company: "HKT", value: 1.488, display: "1.488", period: "2025-12-31", source: COMPARISON_SOURCES.hkt },
        { company: "HKBN", value: 0.907, display: "0.907", period: "2025-08-31", source: COMPARISON_SOURCES.hkbn },
        { company: "3香港", value: null, display: "-", period: "未披露同口径", source: COMPARISON_SOURCES.three },
        { company: "SmarTone", value: null, display: "-", period: "未披露同口径", source: COMPARISON_SOURCES.smartone }
      ]
    }
  ];

  const financeComparison = {
    revenue: { label: "总收入", rows: [36553, 5448, 6253, 11129] },
    ebitda: { label: "EBITDA", rows: [14234, 1508, 2445, 2451] },
    profit: { label: "应占溢利", rows: [5286, -25, 479, 207] },
    capex: { label: "资本开支", rows: [1977, 433, 597, 511] }
  };
  const financeCompanies = [
    { company: "HKT", period: "截至2025-12-31", source: COMPARISON_SOURCES.hkt },
    { company: "3香港", period: "截至2025-12-31", source: COMPARISON_SOURCES.three },
    { company: "SmarTone", period: "截至2025-06-30", source: COMPARISON_SOURCES.smartone },
    { company: "HKBN", period: "截至2025-08-31", source: COMPARISON_SOURCES.hkbn }
  ];

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const displayValue = (metric, index) => metric.valueLabels?.[index] ?? String(metric.values[index]);
  const tooltipText = (metric) => `${metric.label}\n${metric.periods.map((period, index) => `${period}：${displayValue(metric, index)} ${metric.fullUnit || metric.unit}`.trim()).join("\n")}`;
  const formatInteger = (value) => new Intl.NumberFormat("zh-HK", { maximumFractionDigits: 0 }).format(value);

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
          <span class="stage-label"><b>01</b> 移动接入层</span>
          <div class="access-stack">
            <div class="architecture-node node-4g"><small>${escapeHtml(first.label)}</small><strong>${escapeHtml(first.value)}<em>${escapeHtml(first.unit)}</em></strong></div>
            <div class="architecture-node node-5g"><small>${escapeHtml(second.label)}</small><strong>${escapeHtml(second.value)}<em>${escapeHtml(second.unit)}</em></strong></div>
          </div>
        </section>
        <section class="architecture-stage stage-backbone">
          <span class="stage-label"><b>02</b> 光纤承载层</span>
          <div class="architecture-node node-backbone"><small>${escapeHtml(third.label)}</small><strong>${escapeHtml(third.value)}<em>${escapeHtml(third.unit)}</em></strong></div>
        </section>
        <section class="architecture-stage stage-core">
          <span class="stage-label"><b>03</b> 融合服务层</span>
          <div class="architecture-core"><b>${escapeHtml(profile.company)}</b><span>LOCAL NETWORK</span><small>香港本地通信网络</small></div>
        </section>
        <div class="architecture-caption"><span>用户接入</span><i>→</i><span>网络承载</span><i>→</i><span>融合服务</span></div>
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
          <div class="reach-wave" aria-label="${escapeHtml(metric.label)}真实趋势">${metric.values.map((value, valueIndex) => `<i style="height:${Math.max(18, (value / max) * 82)}%"><span>${escapeHtml(metric.periods[valueIndex])}：${escapeHtml(value)} ${escapeHtml(metric.unit)}</span></i>`).join("")}</div>
        </div>
      </section>`;
    }).join("");
  }

  function financeChart(metric, company) {
    const { points, line } = chartGeometry(metric.values, 480, 170, 0, 24);
    const area = `${line} L480 170 L0 170 Z`;
    return `<svg class="finance-area-chart" viewBox="0 0 480 170" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(company)}总收入趋势">
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
    return String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
  }

  function normalizeFinancialReport(report) {
    const definitions = [
      ["revenue", "总收入"],
      ["ebitda", "EBITDA"],
      ["net_profit", "净利润"]
    ];
    const values = new Map((report.metrics || []).map((metric) => [metric.metric_key, metric.value]));
    return {
      key: companyKey(report.company),
      company: companyKey(report.company) === "three" ? "3香港" : report.company,
      period: report.period || "最新披露期",
      metrics: definitions.map(([key, label], index) => {
        const raw = values.get(key);
        const numeric = metricNumber(raw);
        const disclosed = Number.isFinite(numeric);
        return {
          label,
          value: disclosed ? numeric.toFixed(3) : "—",
          unit: disclosed ? "十亿港元" : "",
          trend: disclosed ? (report.period || "最新披露期") : "未披露",
          periods: [report.period || "最新披露期"],
          values: [disclosed ? numeric : 0],
          valueLabels: [disclosed ? numeric.toFixed(3) : "—"],
          gauge: disclosed ? (index === 1 ? 74 : 72) : 0
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

  function comparisonRows(rows, suffix = "") {
    const max = Math.max(...rows.map((item) => Math.abs(item.value || 0)), 1);
    return `<div class="comparison-table" role="table">
      ${rows.map((item) => {
        const width = item.value === null ? 0 : Math.max(2, (Math.abs(item.value) / max) * 100);
        return `<a class="comparison-row${item.value === null ? " is-missing" : ""}${item.value < 0 ? " is-negative" : ""}" href="${escapeHtml(item.source)}" target="_blank" rel="noopener noreferrer" role="row" aria-label="${escapeHtml(`${item.company} ${item.display}${suffix}，${item.period}，打开官方来源`)}">
          <span class="comparison-company" role="cell">${escapeHtml(item.company)}</span>
          <span class="comparison-meter" role="cell"><i style="--bar:${width}%"></i></span>
          <strong role="cell">${escapeHtml(item.display)}${item.value === null ? "" : escapeHtml(suffix)}</strong>
          <small role="cell">${escapeHtml(item.period)}</small>
        </a>`;
      }).join("")}
    </div>`;
  }

  function comparisonPanel(panel) {
    return `<article class="panel comparison-panel is-visible">
      <header class="panel-heading"><span>${escapeHtml(panel.number)}</span><h2>${escapeHtml(panel.title)}</h2></header>
      <div class="monitor-content comparison-content">
        <div class="comparison-toolbar"><span>${escapeHtml(panel.note)}</span><em>同指标 · 同单位</em></div>
        ${comparisonRows(panel.rows, panel.suffix || "")}
      </div>
    </article>`;
  }

  function financeComparisonRows(metricKey) {
    const metric = financeComparison[metricKey];
    return comparisonRows(financeCompanies.map((company, index) => ({
      ...company,
      value: metric.rows[index],
      display: formatInteger(metric.rows[index])
    })), "");
  }

  function renderComparison() {
    const target = document.querySelector("[data-comparison-view]");
    target.innerHTML = comparisonPanels.map(comparisonPanel).join("") + `
      <article class="panel comparison-panel comparison-finance-panel is-visible">
        <header class="panel-heading"><span>04</span><h2>财务指标</h2></header>
        <div class="monitor-content comparison-content">
          <div class="comparison-toolbar comparison-finance-toolbar">
            <div class="comparison-metric-tabs" role="tablist" aria-label="财务对比指标">
              ${Object.entries(financeComparison).map(([key, metric], index) => `<button type="button" role="tab" aria-selected="${index === 0}" data-finance-metric="${key}">${escapeHtml(metric.label)}</button>`).join("")}
            </div>
            <em>百万港元 · 各公司FY2025</em>
          </div>
          <div data-finance-comparison-rows>${financeComparisonRows("revenue")}</div>
          <p class="comparison-scope-note">各公司财年截止日不同；EBITDA按各公司官方披露口径展示。</p>
        </div>
      </article>`;
  }

  function setupComparisonMetricTabs() {
    const buttons = Array.from(document.querySelectorAll("[data-finance-metric]"));
    const target = document.querySelector("[data-finance-comparison-rows]");
    buttons.forEach((button) => button.addEventListener("click", () => {
      buttons.forEach((item) => item.setAttribute("aria-selected", String(item === button)));
      target.innerHTML = financeComparisonRows(button.dataset.financeMetric);
    }));
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
