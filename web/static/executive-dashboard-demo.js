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
  const currentMetric = (label, value, unit, extra = {}) => ({
    label, value: String(value), unit, trend: "当前口径", periods: ["当前口径"], values: [Number(value)], ...extra
  });
  const makeNetworkMetrics = (metrics = {}) => [
    metrics.fourG || missingMetric("基站总数（4G）"),
    metrics.fiveG || missingMetric("基站总数（5G）"),
    metrics.compute || missingMetric("智算能力 PFLOPS")
  ];
  const makeBusinessGroups = (metrics = {}) => [
    { title: "移动业务", accent: "blue", metrics: [metrics.totalMobile || missingMetric("总移动用户数"), metrics.mobileArpu || missingMetric("移动综合ARPU")] },
    { title: "家庭业务", accent: "green", metrics: [metrics.homeBroadband || missingMetric("家庭宽带用户数"), metrics.homeArpu || missingMetric("家庭户均收益（ARPU）")] },
    { title: "政企业务", accent: "amber", metrics: [metrics.enterpriseCustomers || missingMetric("客户数"), metrics.projectValue || missingMetric("项目签约额")] }
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
    { key: "cmhk", company: "CMHK", period: "当前口径", metrics: [
      currentMetric("营运收入", "6.420", "十亿港元"),
      currentMetric("EBITDA率", "32.4", "%", { gauge: 65 }),
      currentMetric("净利润", "0.681", "十亿港元", { gauge: 72 })
    ] }
  ];
  const operatorProfiles = [
    { key: "hkt", company: "HKT", networkMetrics: makeNetworkMetrics({
      fourG: currentMetric("基站总数（4G）", "5800", "座"),
      fiveG: currentMetric("基站总数（5G）", "4500", "座"),
      compute: currentMetric("智算能力 PFLOPS", "72", "PFLOPS")
    }), businessGroups: makeBusinessGroups({
      totalMobile: { label: "总移动用户数", value: "4.923", unit: "百万户", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [4.875, 4.817, 4.923] },
      mobileArpu: currentMetric("移动综合ARPU", "121", "港元/月"),
      homeBroadband: { label: "家庭宽带用户数", value: "1.497", unit: "百万户", trend: "同比 +1%", periods: ["2025年6月", "2025年12月", "2026年6月"], values: [1.482, 1.488, 1.497] },
      homeArpu: currentMetric("家庭户均收益（ARPU）", "226", "港元/月"),
      enterpriseCustomers: currentMetric("客户数", "4.6", "万户"),
      projectValue: { label: "项目签约额", value: ">2.2", unit: "十亿港元", trend: "最新披露", periods: ["最新披露"], values: [2.2], valueLabels: [">2.2"] }
    }), reachMetrics: [
      currentMetric("全港实体门市数量", "36", "间", { dial: 72, color: "#55d9ff" }),
      currentMetric("官方手机应用程式 (如MyLink) 活跃用户数", "2.3", "百万户", { dial: 67, color: "#5de2b6" })
    ] },
    { key: "three", company: "3香港", networkMetrics: makeNetworkMetrics({
      fourG: currentMetric("基站总数（4G）", "5100", "座"),
      fiveG: currentMetric("基站总数（5G）", "3900", "座"),
      compute: currentMetric("智算能力 PFLOPS", "60", "PFLOPS")
    }), businessGroups: makeBusinessGroups({
      totalMobile: disclosedMetric("总移动用户数", "8.132", "百万户", [8.132]),
      mobileArpu: currentMetric("移动综合ARPU", "88", "港元/月"),
      homeBroadband: currentMetric("家庭宽带用户数", "0.310", "百万户"),
      homeArpu: currentMetric("家庭户均收益（ARPU）", "169", "港元/月"),
      enterpriseCustomers: currentMetric("客户数", "2.9", "万户"),
      projectValue: currentMetric("项目签约额", "1.4", "十亿港元")
    }), reachMetrics: [
      currentMetric("全港实体门市数量", "42", "间", { dial: 76, color: "#55d9ff" }),
      currentMetric("官方手机应用程式 (如MyLink) 活跃用户数", "3.1", "百万户", { dial: 74, color: "#5de2b6" })
    ] },
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
    { key: "cmhk", company: "CMHK", networkMetrics: makeNetworkMetrics({
      fourG: currentMetric("基站总数（4G）", "6200", "座"),
      fiveG: currentMetric("基站总数（5G）", "4800", "座"),
      compute: currentMetric("智算能力 PFLOPS", "85", "PFLOPS")
    }), businessGroups: makeBusinessGroups({
      totalMobile: { label: "总移动用户数", value: "5.0", unit: "百万户", trend: "已披露口径", periods: ["2024年公开材料"], values: [5.0], source: SOURCES.cmhkBusiness2024 },
      mobileArpu: currentMetric("移动综合ARPU", "96", "港元/月"),
      homeBroadband: currentMetric("家庭宽带用户数", "0.420", "百万户"),
      homeArpu: currentMetric("家庭户均收益（ARPU）", "148", "港元/月"),
      enterpriseCustomers: currentMetric("客户数", "3.8", "万户"),
      projectValue: currentMetric("项目签约额", "1.9", "十亿港元")
    }), reachMetrics: [
      { label: "全港实体门市数量", value: "49", unit: "间", trend: "当前列示", periods: ["当前列示"], values: [49], dial: 82, color: "#55d9ff", source: SOURCES.cmhkStores },
      currentMetric("官方手机应用程式 (如MyLink) 活跃用户数", "2.8", "百万户", { dial: 72, color: "#5de2b6" })
    ] }
  ];
  const comparisonOperatorKeys = ["cmhk", "hkt", "three"];
  const comparisonCompanyNames = { cmhk: "CMHK", hkt: "HKT", three: "3HK" };
  let financeCompaniesData = financeCompanyFallbacks;

  const comparisonSections = [
    { key: "network", number: "01", title: "资源与基础设施层", metricCount: 3, chartTypes: ["column", "column", "lollipop"], groups: [
      { title: "基站总数（4G / 5G）", indices: [0, 1], sharedChart: "grouped-column" },
      { indices: [2] }
    ] },
    { key: "business", number: "02", title: "客户与业务对标层", metricCount: 6, chartTypes: ["column", "bar", "column", "lollipop", "column", "column"], groups: [
      { title: "移动业务", indices: [0, 1] },
      { title: "家庭业务", indices: [2, 3] },
      { title: "政企业务", indices: [4, 5] }
    ] },
    { key: "reach", number: "03", title: "渠道与品牌触达层", metricCount: 2, chartTypes: ["column", "bar"], groups: [
      { indices: [0] },
      { indices: [1] }
    ] },
    { key: "finance", number: "04", title: "财务成果", metricCount: 3, chartTypes: ["bar", "radial", "diverging"], groups: [
      { title: "经营规模与盈利", indices: [0, 2] },
      { indices: [1] }
    ] }
  ];
  const chartColors = ["#64cdf4", "#5c9cff", "#60d9aa", "#efb354", "#b68cff", "#f37f8c"];
  const chartTypeNames = { column: "柱状图", lollipop: "棒棒糖图", bar: "横向条形图", radial: "百分比环形图", donut: "环形图", line: "折线图", diverging: "正负发散条形图" };
  const comparisonEchartSpecs = new Map();
  let comparisonEchartInstances = [];
  let comparisonEchartResizeObserver = null;
  let comparisonEchartSequence = 0;

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const metricTitle = (metric) => `${metric.label}${metric.unit ? `（${metric.unit}）` : ""}`;
  const tooltipAttributes = (text, company) => `tabindex="0" data-company="${escapeHtml(company)}" data-chart-tooltip="${escapeHtml(text)}" aria-label="${escapeHtml(text)}"`;
  const metricTooltip = (item, metricLabel) => tooltipAttributes(`${item.company}｜${metricLabel}：${item.display}｜${item.status}`, item.company);

  function echartDescription(spec) {
    if (spec.kind === "grouped-column") {
      return `${spec.title}。${spec.metrics[0].rows.map((row, index) => `${row.company}：${spec.metrics.map((metric) => `${metric.label}${metric.rows[index].display}`).join("，")}`).join("；")}`;
    }
    return `${spec.metricLabel}。${spec.rows.map((row) => `${row.company}${row.display}，${row.status}`).join("；")}`;
  }

  function echartHost(spec) {
    const id = `comparison-echart-${++comparisonEchartSequence}`;
    const description = echartDescription(spec);
    comparisonEchartSpecs.set(id, { ...spec, description });
    return `<div id="${id}" class="comparison-echart" tabindex="0" role="img" aria-label="${escapeHtml(description)}"></div>`;
  }

  function echartTooltip(spec) {
    return {
      trigger: "item",
      confine: true,
      backgroundColor: "rgba(5, 18, 30, .96)",
      borderColor: "rgba(100, 205, 244, .42)",
      borderWidth: 1,
      padding: [9, 11],
      textStyle: { color: "#dcecf4", fontSize: 12, lineHeight: 19 },
      extraCssText: "border-radius:8px;box-shadow:0 12px 34px rgba(0,0,0,.34)",
      formatter(params) {
        const index = spec.kind === "radial" ? (Number(params.seriesIndex) || 0) : (Number(params.dataIndex) || 0);
        if (spec.kind === "grouped-column") {
          const row = spec.metrics[0].rows[index];
          return `<strong style="color:#fff">${escapeHtml(row.company)}</strong><br>${spec.metrics.map((metric) => `${escapeHtml(metric.label)}：${escapeHtml(metric.rows[index].display)}`).join("<br>")}`;
        }
        const row = spec.rows[index];
        return `<strong style="color:#fff">${escapeHtml(row.company)}</strong><br>${escapeHtml(spec.metricLabel)}：${escapeHtml(row.display)}<br><span style="color:#86a8b8">${escapeHtml(row.status)}</span>`;
      }
    };
  }

  function echartBaseOption(spec) {
    return {
      animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      animationDuration: 420,
      animationEasing: "cubicOut",
      backgroundColor: "transparent",
      textStyle: { fontFamily: '"SF Pro Text", "PingFang SC", "Microsoft YaHei", sans-serif' },
      aria: { enabled: true, decal: { show: false }, description: spec.description },
      tooltip: echartTooltip(spec)
    };
  }

  function echartAxisLabel(rows) {
    const rich = {};
    rows.forEach((row, index) => {
      rich[`dot${index}`] = { color: chartColors[index], fontSize: 14, lineHeight: 20 };
    });
    rich.name = { color: "#a9c0cb", fontSize: 11, fontWeight: 600, lineHeight: 20 };
    return {
      color: "#a9c0cb",
      margin: 9,
      formatter(value, index) { return `{dot${index}|●}  {name|${value}}`; },
      rich
    };
  }

  function echartHorizontalOption(spec) {
    const rows = spec.rows;
    const disclosed = rows.filter((row) => row.value !== null);
    const absoluteMax = Math.max(...disclosed.map((row) => Math.abs(row.value)), 1);
    const diverging = spec.kind === "diverging";
    const lollipop = spec.kind === "lollipop";
    const barData = rows.map((row, index) => ({
      value: row.value === null ? 0 : row.value,
      itemStyle: { color: row.value === null ? "transparent" : (row.value < 0 ? "#efb354" : chartColors[index]) },
      label: { color: row.value === null ? "#718e9b" : "#eaf6fb" }
    }));
    const pointData = rows.map((row, index) => ({
      value: [row.value, row.company],
      itemStyle: { color: row.value < 0 ? "#efb354" : chartColors[index] }
    }));
    return {
      ...echartBaseOption(spec),
      grid: { left: 72, right: 58, top: 9, bottom: 8 },
      xAxis: {
        type: "value",
        min: diverging ? -absoluteMax * 1.18 : 0,
        max: absoluteMax * 1.18,
        axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false }
      },
      yAxis: {
        type: "category", inverse: true, data: rows.map((row) => row.company),
        axisLine: { show: false }, axisTick: { show: false }, axisLabel: echartAxisLabel(rows)
      },
      series: [
        {
          name: spec.metricLabel,
          type: "bar",
          data: barData,
          barWidth: diverging ? 8 : (lollipop ? 7 : 10),
          showBackground: !diverging,
          backgroundStyle: { color: "rgba(90, 132, 151, .14)", borderRadius: 3 },
          itemStyle: { borderRadius: 6 },
          label: {
            show: true,
            position: "right",
            distance: 8,
            fontSize: 11,
            fontWeight: 700,
            formatter(params) { return rows[params.dataIndex].chartDisplay; }
          },
          emphasis: { focus: "self", itemStyle: { shadowBlur: 10, shadowColor: "rgba(100, 205, 244, .45)" } },
          markLine: diverging ? { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "rgba(153, 190, 207, .34)", width: 1 }, data: [{ xAxis: 0 }] } : undefined,
          z: 2
        },
        {
          type: "scatter",
          data: pointData,
          symbolSize: lollipop ? 14 : (diverging ? 10 : 0),
          tooltip: { show: false },
          emphasis: { scale: 1.35 },
          z: 3
        }
      ]
    };
  }

  function echartGroupedColumnOption(spec) {
    const rows = spec.metrics[0].rows;
    return {
      ...echartBaseOption(spec),
      grid: { left: 18, right: 12, top: 34, bottom: 27 },
      legend: {
        top: 3, right: 8, itemWidth: 10, itemHeight: 7, itemGap: 16, icon: "roundRect",
        textStyle: { color: "#a9c0cb", fontSize: 11, fontWeight: 600 }
      },
      xAxis: {
        type: "category", data: rows.map((row) => row.company),
        axisLine: { lineStyle: { color: "rgba(135, 180, 200, .2)" } },
        axisTick: { show: false }, axisLabel: { color: "#a9c0cb", fontSize: 11, fontWeight: 600, margin: 9 }
      },
      yAxis: { type: "value", axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      series: spec.metrics.map((metric, metricIndex) => ({
        name: metricIndex === 0 ? "4G" : "5G",
        type: "bar",
        data: metric.rows.map((row) => row.value),
        barWidth: 17,
        barGap: "30%",
        itemStyle: { color: metricIndex === 0 ? "#64cdf4" : "#60d9aa", borderRadius: [4, 4, 1, 1] },
        label: {
          show: true, position: "top", distance: 5, color: "#eaf6fb", fontSize: 11, fontWeight: 700,
          formatter(params) { return metric.rows[params.dataIndex].chartDisplay; }
        },
        emphasis: { focus: "series", itemStyle: { shadowBlur: 12, shadowColor: metricIndex === 0 ? "rgba(100,205,244,.45)" : "rgba(96,217,170,.42)" } }
      }))
    };
  }

  function echartColumnOption(spec) {
    const rows = spec.rows;
    return {
      ...echartBaseOption(spec),
      grid: { left: 14, right: 14, top: 25, bottom: 27 },
      xAxis: {
        type: "category", data: rows.map((row) => row.company),
        axisLine: { lineStyle: { color: "rgba(135, 180, 200, .2)" } }, axisTick: { show: false },
        axisLabel: { color: "#a9c0cb", fontSize: 11, fontWeight: 600, margin: 9 }
      },
      yAxis: { type: "value", axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: false }, splitLine: { show: false } },
      series: [{
        name: spec.metricLabel,
        type: "bar",
        barWidth: 22,
        data: rows.map((row, index) => ({ value: row.value, itemStyle: { color: chartColors[index] } })),
        itemStyle: { borderRadius: [6, 6, 2, 2] },
        label: {
          show: true, position: "top", distance: 5, color: "#eaf6fb", fontSize: 11, fontWeight: 700,
          formatter(params) { return rows[params.dataIndex].chartDisplay; }
        },
        emphasis: { focus: "self", itemStyle: { shadowBlur: 12, shadowColor: "rgba(100,205,244,.4)" } }
      }]
    };
  }

  function echartRadialOption(spec) {
    const rows = spec.rows;
    const radii = [["19%", "27%"], ["34%", "42%"], ["49%", "57%"]];
    return {
      ...echartBaseOption(spec),
      graphic: rows.map((row, index) => ({
        type: "group", left: "68%", top: `${28 + (index * 22)}%`,
        children: [
          { type: "circle", shape: { cx: 4, cy: 7, r: 4 }, style: { fill: chartColors[index] } },
          { type: "text", left: 14, top: 0, style: { text: `${row.company}  ${row.chartDisplay}`, fill: "#b8ced7", font: '600 11px "SF Pro Text", "PingFang SC", sans-serif' } }
        ]
      })),
      series: rows.map((row, index) => ({
        name: row.company,
        type: "pie",
        center: ["29%", "50%"],
        radius: radii[index],
        clockwise: true,
        startAngle: 90,
        silent: row.value === null,
        avoidLabelOverlap: true,
        label: { show: false }, labelLine: { show: false },
        emphasis: { scale: false, itemStyle: { shadowBlur: 12, shadowColor: chartColors[index] } },
        data: [
          { value: Math.max(0, Math.min(100, row.value || 0)), name: row.company, itemStyle: { color: chartColors[index], borderRadius: 4 } },
          { value: Math.max(0, 100 - (row.value || 0)), name: `余量-${index}`, tooltip: { show: false }, itemStyle: { color: "rgba(90,132,151,.14)" }, emphasis: { disabled: true } }
        ]
      }))
    };
  }

  function echartOption(spec) {
    if (spec.kind === "grouped-column") return echartGroupedColumnOption(spec);
    if (spec.kind === "column") return echartColumnOption(spec);
    if (spec.kind === "radial") return echartRadialOption(spec);
    return echartHorizontalOption(spec);
  }

  function disposeComparisonEcharts() {
    comparisonEchartResizeObserver?.disconnect();
    comparisonEchartResizeObserver = null;
    comparisonEchartInstances.forEach((chart) => chart.dispose());
    comparisonEchartInstances = [];
  }

  function initializeEcharts(root) {
    if (!window.echarts) return;
    comparisonEchartResizeObserver = "ResizeObserver" in window ? new ResizeObserver((entries) => {
      entries.forEach((entry) => window.echarts.getInstanceByDom(entry.target)?.resize());
    }) : null;
    comparisonEchartSpecs.forEach((spec, id) => {
      const element = root.querySelector(`#${id}`);
      if (!element) return;
      const chart = window.echarts.init(element, null, { renderer: "svg" });
      chart.setOption(echartOption(spec));
      element.dataset.echartReady = "1";
      let activeIndex = 0;
      const rowCount = spec.kind === "grouped-column" ? spec.metrics[0].rows.length : spec.rows.length;
      const showActive = () => {
        const seriesIndex = spec.kind === "radial" ? activeIndex : 0;
        const dataIndex = spec.kind === "radial" ? 0 : activeIndex;
        chart.dispatchAction({ type: "downplay" });
        chart.dispatchAction({ type: "highlight", seriesIndex, dataIndex });
        chart.dispatchAction({ type: "showTip", seriesIndex, dataIndex });
      };
      element.addEventListener("focus", showActive);
      element.addEventListener("blur", () => chart.dispatchAction({ type: "hideTip" }));
      element.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) return;
        event.preventDefault();
        activeIndex = (activeIndex + (["ArrowRight", "ArrowDown"].includes(event.key) ? 1 : -1) + rowCount) % rowCount;
        showActive();
      });
      comparisonEchartResizeObserver?.observe(element);
      comparisonEchartInstances.push(chart);
    });
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
        financeCompaniesData = financeCompanyFallbacks.map((fallback) => {
          const current = byKey.get(fallback.key);
          if (!current) return fallback;
          return {
            ...current,
            metrics: current.metrics.map((metric, index) => metric.value === "—" ? fallback.metrics[index] : metric)
          };
        });
        renderComparison();
      })
      .catch(() => {});
  }

  function emptyChart(rows, metricLabel, chartType) {
    return `<svg class="comparison-chart comparison-chart-empty" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}${chartTypeNames[chartType]}，暂无披露数据`)}">
      <text x="90" y="20" text-anchor="middle" class="chart-empty-label">暂无披露</text>
      ${rows.map((item, index) => {
        const x = 20 + (index * 70);
        return `<g class="chart-mark-missing chart-interactive-mark" ${metricTooltip(item, metricLabel)}><text x="${x}" y="70" text-anchor="middle" class="chart-direct-value">—</text><line x1="${x - 6}" y1="78" x2="${x + 6}" y2="78" class="chart-missing-line"></line><text x="${x}" y="104" text-anchor="middle">${escapeHtml(item.company)}</text></g>`;
      }).join("")}
    </svg>`;
  }

  function columnChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(rows, metricLabel, "column");
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    const slot = 156 / rows.length;
    const barWidth = Math.min(24, slot * .46);
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}三家重点运营商柱状图`)}">
      <line x1="12" y1="91" x2="168" y2="91" class="chart-axis"></line>
      ${rows.map((item, index) => {
        const height = item.value === null ? 0 : Math.max(3, (Math.abs(item.value) / max) * 66);
        const x = 12 + (index * slot) + ((slot - barWidth) / 2);
        return `<g class="chart-interactive-mark ${item.value === null ? "chart-mark-missing" : ""}" ${metricTooltip(item, metricLabel)}>
          ${item.value === null ? `<text x="${x + (barWidth / 2)}" y="80" text-anchor="middle" class="chart-direct-value">—</text><line x1="${x}" y1="87" x2="${x + barWidth}" y2="87" class="chart-missing-line"></line>` : `<rect class="chart-column-mark" x="${x}" y="${91 - height}" width="${barWidth}" height="${height}" rx="3" fill="${chartColors[index]}"></rect><text x="${x + (barWidth / 2)}" y="${Math.max(13, 86 - height)}" text-anchor="middle" class="chart-direct-value">${escapeHtml(item.chartDisplay)}</text>`}
          <text x="${x + (barWidth / 2)}" y="108" text-anchor="middle">${escapeHtml(item.company)}</text>
        </g>`;
      }).join("")}
    </svg>`;
  }

  function groupedColumnChart(metrics, title) {
    if (window.echarts) return echartHost({ kind: "grouped-column", metrics, title });
    const disclosed = metrics.flatMap((metric) => metric.rows).filter((item) => item.value !== null);
    if (!disclosed.length) {
      return `<svg class="comparison-chart comparison-grouped-chart comparison-chart-empty" viewBox="0 0 300 116" role="img" aria-label="${escapeHtml(`${title}三家重点运营商分组柱状图，暂无披露数据`)}">
        <g class="comparison-svg-legend"><rect x="172" y="5" width="8" height="8" rx="2" class="series-a"></rect><text x="184" y="13">4G</text><rect x="224" y="5" width="8" height="8" rx="2" class="series-b"></rect><text x="236" y="13">5G</text></g>
        <text x="75" y="14" text-anchor="middle" class="chart-empty-label">暂无披露</text>
        ${metrics[0].rows.map((row, index) => {
          const center = 62 + (index * 88);
          const paired = metrics[1].rows[index];
          const tooltip = `${row.company}｜${metrics[0].label}：${row.display}｜${metrics[1].label}：${paired.display}｜未披露`;
          return `<g class="chart-mark-missing chart-interactive-mark" ${tooltipAttributes(tooltip, row.company)}><text x="${center - 12}" y="65" text-anchor="middle" class="chart-direct-value">—</text><text x="${center + 12}" y="65" text-anchor="middle" class="chart-direct-value">—</text><line x1="${center - 20}" y1="75" x2="${center - 4}" y2="75" class="chart-missing-line"></line><line x1="${center + 4}" y1="75" x2="${center + 20}" y2="75" class="chart-missing-line"></line><text x="${center}" y="102" text-anchor="middle">${escapeHtml(row.company)}</text></g>`;
        }).join("")}
      </svg>`;
    }
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    const slot = 264 / metrics[0].rows.length;
    const barWidth = Math.min(18, slot * .24);
    return `<svg class="comparison-chart comparison-grouped-chart" viewBox="0 0 300 116" role="img" aria-label="${escapeHtml(`${title}三家重点运营商分组柱状图`)}">
      <line x1="18" y1="88" x2="282" y2="88" class="chart-axis"></line>
      <g class="comparison-svg-legend"><rect x="172" y="5" width="8" height="8" rx="2" class="series-a"></rect><text x="184" y="13">4G</text><rect x="224" y="5" width="8" height="8" rx="2" class="series-b"></rect><text x="236" y="13">5G</text></g>
      ${metrics[0].rows.map((row, index) => {
        const paired = metrics[1].rows[index];
        const x = 18 + (index * slot) + (slot / 2) - barWidth - 2;
        const firstHeight = row.value === null ? 0 : Math.max(3, (Math.abs(row.value) / max) * 62);
        const secondHeight = paired.value === null ? 0 : Math.max(3, (Math.abs(paired.value) / max) * 62);
        const tooltip = `${row.company}｜${metrics[0].label}：${row.display}｜${metrics[1].label}：${paired.display}`;
        return `<g class="chart-interactive-mark" ${tooltipAttributes(tooltip, row.company)}>
          ${row.value === null ? `<text x="${x + (barWidth / 2)}" y="76" text-anchor="middle" class="chart-direct-value">—</text><line x1="${x}" y1="84" x2="${x + barWidth}" y2="84" class="chart-missing-line"></line>` : `<rect x="${x}" y="${88 - firstHeight}" width="${barWidth}" height="${firstHeight}" rx="3" class="series-a chart-column-mark"></rect><text x="${x + (barWidth / 2)}" y="${Math.max(20, 83 - firstHeight)}" text-anchor="middle" class="chart-direct-value">${escapeHtml(row.chartDisplay)}</text>`}
          ${paired.value === null ? `<text x="${x + barWidth + 4 + (barWidth / 2)}" y="76" text-anchor="middle" class="chart-direct-value">—</text><line x1="${x + barWidth + 4}" y1="84" x2="${x + (barWidth * 2) + 4}" y2="84" class="chart-missing-line"></line>` : `<rect x="${x + barWidth + 4}" y="${88 - secondHeight}" width="${barWidth}" height="${secondHeight}" rx="3" class="series-b chart-column-mark"></rect><text x="${x + barWidth + 4 + (barWidth / 2)}" y="${Math.max(20, 83 - secondHeight)}" text-anchor="middle" class="chart-direct-value">${escapeHtml(paired.chartDisplay)}</text>`}
          <text x="${18 + (index * slot) + (slot / 2)}" y="105" text-anchor="middle">${escapeHtml(row.company)}</text>
        </g>`;
      }).join("")}
    </svg>`;
  }

  function horizontalChart(rows, metricLabel, chartType) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(rows, metricLabel, chartType);
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    const isLollipop = chartType === "lollipop";
    return `<div class="comparison-bars${isLollipop ? " is-lollipop" : ""}" role="img" aria-label="${escapeHtml(`${metricLabel}三家重点运营商${chartTypeNames[chartType]}`)}">
      ${rows.map((item, index) => {
        const width = item.value === null ? 0 : Math.max(4, (Math.abs(item.value) / max) * 100);
        return `<div class="comparison-bar-row chart-interactive-mark ${item.value === null ? "chart-mark-missing" : ""}" style="--series-color:${chartColors[index]};--bar-width:${width}%" ${metricTooltip(item, metricLabel)}>
          <span class="comparison-bar-company"><i></i>${escapeHtml(item.company)}</span>
          <span class="comparison-bar-track"><i class="comparison-bar-fill"></i>${isLollipop && item.value !== null ? '<b class="comparison-bar-dot"></b>' : ""}</span>
          <strong>${escapeHtml(item.chartDisplay)}</strong>
        </div>`;
      }).join("")}
    </div>`;
  }

  function lineChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(rows, metricLabel, "line");
    const values = disclosed.map((item) => item.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.max(Math.abs(max), 1);
    const point = (item, index) => ({ x: rows.length === 1 ? 90 : 20 + (index * (140 / (rows.length - 1))), y: 84 - (((item.value - min) / range) * 58) });
    const segments = [];
    let current = [];
    rows.forEach((item, index) => {
      if (item.value === null) {
        if (current.length) segments.push(current);
        current = [];
      } else current.push(point(item, index));
    });
    if (current.length) segments.push(current);
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}三家重点运营商折线图，缺失值留空`)}">
      <line x1="12" y1="88" x2="168" y2="88" class="chart-axis"></line>
      ${segments.filter((segment) => segment.length > 1).map((segment) => `<polyline points="${segment.map(({ x, y }) => `${x},${y}`).join(" ")}" class="chart-line"></polyline>`).join("")}
      ${rows.map((item, index) => {
        const x = rows.length === 1 ? 90 : 20 + (index * (140 / (rows.length - 1)));
        if (item.value === null) return `<g class="chart-mark-missing chart-interactive-mark" ${metricTooltip(item, metricLabel)}><text x="${x}" y="76" text-anchor="middle" class="chart-direct-value">—</text><line x1="${x - 5}" y1="84" x2="${x + 5}" y2="84" class="chart-missing-line"></line><text x="${x}" y="106" text-anchor="middle">${escapeHtml(item.company)}</text></g>`;
        const { y } = point(item, index);
        return `<g class="chart-interactive-mark" ${metricTooltip(item, metricLabel)}><circle class="chart-point" cx="${x}" cy="${y}" r="7" fill="${chartColors[index]}"></circle><text x="${x}" y="${Math.max(13, y - 11)}" text-anchor="middle" class="chart-direct-value">${escapeHtml(item.chartDisplay)}</text><text x="${x}" y="106" text-anchor="middle">${escapeHtml(item.company)}</text></g>`;
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
      const dashArray = `${length} ${circumference - length}`;
      const dashOffset = -offset;
      const ring = `<g class="chart-interactive-mark" ${metricTooltip(item, metricLabel)}><circle class="chart-donut-segment" cx="72" cy="56" r="${radius}" fill="none" stroke="${chartColors[index]}" stroke-width="18" stroke-dasharray="${dashArray}" stroke-dashoffset="${dashOffset}" transform="rotate(-90 72 56)"></circle></g>`;
      offset += length;
      return ring;
    }).join("");
    return `<svg class="comparison-chart" viewBox="0 0 180 116" role="img" aria-label="${escapeHtml(`${metricLabel}已披露运营商构成环形图`)}">
      <circle cx="72" cy="56" r="${radius}" fill="none" class="chart-track-ring" stroke-width="18"></circle>
      ${rings}
      <text x="72" y="60" text-anchor="middle" class="chart-donut-count">${disclosed.length} 家</text>
      ${disclosed.map((item, index) => `<g class="chart-donut-legend" transform="translate(122 ${34 + index * 24})"><circle class="chart-point" r="5" fill="${chartColors[rows.indexOf(item)]}"></circle><text x="9" y="4" class="chart-direct-value">${escapeHtml(`${item.company} ${item.chartDisplay}`)}</text></g>`).join("")}
    </svg>`;
  }

  function divergingChart(rows, metricLabel) {
    const disclosed = rows.filter((item) => item.value !== null);
    if (!disclosed.length) return emptyChart(rows, metricLabel, "diverging");
    const max = Math.max(...disclosed.map((item) => Math.abs(item.value)), 1);
    return `<div class="comparison-bars is-diverging" role="img" aria-label="${escapeHtml(`${metricLabel}三家重点运营商正负发散条形图`)}">
      ${rows.map((item, index) => {
        const width = item.value === null ? 0 : Math.max(3, (Math.abs(item.value) / max) * 50);
        const start = item.value < 0 ? 50 - width : 50;
        const color = item.value < 0 ? "#efb354" : chartColors[index];
        return `<div class="comparison-bar-row chart-interactive-mark ${item.value === null ? "chart-mark-missing" : ""}" style="--series-color:${color};--bar-width:${width}%;--bar-start:${start}%" ${metricTooltip(item, metricLabel)}>
          <span class="comparison-bar-company"><i></i>${escapeHtml(item.company)}</span>
          <span class="comparison-bar-track"><i class="comparison-bar-fill"></i></span>
          <strong>${escapeHtml(item.chartDisplay)}</strong>
        </div>`;
      }).join("")}
    </div>`;
  }

  function comparisonChart(rows, metricLabel, chartType) {
    if (window.echarts && ["column", "lollipop", "bar", "radial", "diverging"].includes(chartType)) {
      return echartHost({ kind: chartType, rows, metricLabel });
    }
    if (chartType === "column") return columnChart(rows, metricLabel);
    if (chartType === "lollipop" || chartType === "bar") return horizontalChart(rows, metricLabel, chartType);
    if (chartType === "radial") return horizontalChart(rows, metricLabel, "bar");
    if (chartType === "donut") return donutChart(rows, metricLabel);
    if (chartType === "diverging") return divergingChart(rows, metricLabel);
    return lineChart(rows, metricLabel);
  }

  function combinedMetricCard(panel, metrics, group, groupIndex) {
    const cardId = `${panel.key}-group-${groupIndex}`;
    const charts = group.sharedChart === "grouped-column"
      ? groupedColumnChart(metrics, group.title)
      : `<div class="comparison-mini-charts">${metrics.map((metric, index) => `<div class="comparison-mini-chart"><span>${escapeHtml(metricTitle(metric))}</span>${comparisonChart(metric.rows, metric.label, panel.chartTypes[group.indices[index]])}</div>`).join("")}</div>`;
    return `<section class="comparison-metric-card comparison-combined-card" style="--card-delay:${groupIndex * 80}ms" data-chart-type="${escapeHtml(group.sharedChart || "paired")}" aria-labelledby="${escapeHtml(cardId)}">
      <header><h3 id="${escapeHtml(cardId)}">${escapeHtml(group.title)}</h3></header>
      <div class="comparison-chart-only">${charts}</div>
    </section>`;
  }

  function singleMetricCard(panel, metric, metricIndex) {
    const chartType = panel.chartTypes[metricIndex];
    const cardId = `${panel.key}-metric-${metricIndex}`;
    return `<section class="comparison-metric-card" style="--card-delay:${metricIndex * 80}ms" data-chart-type="${escapeHtml(chartType)}" aria-labelledby="${escapeHtml(cardId)}">
      <header><h3 id="${escapeHtml(cardId)}">${escapeHtml(metricTitle(metric))}</h3></header>
      <div class="comparison-chart-only">${comparisonChart(metric.rows, metric.label, chartType)}</div>
    </section>`;
  }

  function sectionMetrics(sectionKey, profile) {
    if (sectionKey === "finance") return financeCompaniesData.find((company) => company.key === profile.key)?.metrics || [];
    if (sectionKey === "network") return profile.networkMetrics;
    if (sectionKey === "reach") return profile.reachMetrics;
    return profile.businessGroups.flatMap((group) => group.metrics);
  }

  function comparisonMetric(sectionKey, metricIndex) {
    const selectedProfiles = comparisonOperatorKeys.map((key) => operatorProfiles.find((profile) => profile.key === key)).filter(Boolean);
    const metrics = selectedProfiles.map((profile) => ({ profile, metric: sectionMetrics(sectionKey, profile)[metricIndex] }));
    const label = metrics.find((item) => item.metric)?.metric.label || "指标";
    const unit = metrics.find((item) => item.metric?.unit)?.metric.unit || "";
    return {
      label,
      unit,
      rows: metrics.map(({ profile, metric }) => {
        const numeric = metric?.value === "—" ? null : Number(metric?.values?.at(-1));
        return {
          company: comparisonCompanyNames[profile.key] || profile.company,
          value: Number.isFinite(numeric) ? numeric : null,
          chartDisplay: metric?.value === "—" ? "—" : (metric?.value || "—"),
          display: metric?.value === "—" ? "—" : `${metric?.value || "—"}${metric?.unit ? ` ${metric.unit}` : ""}`,
          status: metric?.value === "—" ? "未披露" : (metric?.trend || "最新披露")
        };
      })
    };
  }

  function comparisonPanel(panel) {
    const metrics = Array.from({ length: panel.metricCount }, (_, index) => comparisonMetric(panel.key, index));
    const groups = panel.groups || metrics.map((_, index) => ({ indices: [index] }));
    return `<article class="panel panel-${escapeHtml(panel.key)} comparison-panel is-visible">
      <header class="panel-heading"><span>${escapeHtml(panel.number)}</span><h2>${escapeHtml(panel.title)}</h2></header>
      <div class="monitor-content comparison-content">
        <div class="comparison-metric-grid comparison-metric-grid-${groups.length} comparison-metric-grid-${escapeHtml(panel.key)}">
          ${groups.map((group, groupIndex) => {
            const groupedMetrics = group.indices.map((index) => metrics[index]);
            return groupedMetrics.length > 1
              ? combinedMetricCard(panel, groupedMetrics, group, groupIndex)
              : singleMetricCard(panel, groupedMetrics[0], group.indices[0]);
          }).join("")}
        </div>
      </div>
    </article>`;
  }

  function setupChartTooltips(root) {
    if (root.dataset.chartTooltipsReady === "1") return;
    root.dataset.chartTooltipsReady = "1";
    const tooltip = document.createElement("div");
    tooltip.className = "comparison-chart-tooltip";
    tooltip.hidden = true;
    tooltip.setAttribute("role", "tooltip");
    document.body.appendChild(tooltip);
    let activeMark = null;

    const placeTooltip = (clientX, clientY) => {
      const gap = 14;
      const width = tooltip.offsetWidth;
      const height = tooltip.offsetHeight;
      tooltip.style.left = `${Math.max(8, Math.min(window.innerWidth - width - 8, clientX + gap))}px`;
      tooltip.style.top = `${Math.max(8, Math.min(window.innerHeight - height - 8, clientY + gap))}px`;
    };
    const showTooltip = (mark, clientX, clientY) => {
      activeMark?.classList.remove("is-active");
      activeMark = mark;
      activeMark.classList.add("is-active");
      const parts = (mark.dataset.chartTooltip || "").split("｜");
      tooltip.replaceChildren(...parts.map((part, index) => {
        const line = document.createElement(index === 0 ? "strong" : "span");
        line.textContent = part;
        return line;
      }));
      tooltip.hidden = false;
      placeTooltip(clientX, clientY);
    };
    const hideTooltip = (mark) => {
      if (mark && activeMark !== mark) return;
      activeMark?.classList.remove("is-active");
      activeMark = null;
      tooltip.hidden = true;
    };

    root.addEventListener("pointerover", (event) => {
      const mark = event.target.closest?.("[data-chart-tooltip]");
      if (mark) showTooltip(mark, event.clientX, event.clientY);
    });
    root.addEventListener("pointermove", (event) => {
      if (activeMark) placeTooltip(event.clientX, event.clientY);
    });
    root.addEventListener("pointerout", (event) => {
      const mark = event.target.closest?.("[data-chart-tooltip]");
      if (mark && !mark.contains(event.relatedTarget)) hideTooltip(mark);
    });
    root.addEventListener("focusin", (event) => {
      const mark = event.target.closest?.("[data-chart-tooltip]");
      if (!mark) return;
      const rect = mark.getBoundingClientRect();
      showTooltip(mark, rect.left + (rect.width / 2), rect.top + (rect.height / 2));
    });
    root.addEventListener("focusout", (event) => {
      const mark = event.target.closest?.("[data-chart-tooltip]");
      if (mark) hideTooltip(mark);
    });
  }

  function renderComparison() {
    const target = document.querySelector("[data-comparison-view]");
    disposeComparisonEcharts();
    comparisonEchartSpecs.clear();
    comparisonEchartSequence = 0;
    target.innerHTML = comparisonSections.map(comparisonPanel).join("");
    initializeEcharts(target);
    setupChartTooltips(target);
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
