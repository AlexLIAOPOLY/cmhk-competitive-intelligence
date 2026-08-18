(() => {
  "use strict";

  const OFFICIAL = {
    quarterly: "https://www.chinamobileltd.com/sc/ir/operation_q.php",
    business: "https://www.chinamobileltd.com/sc/ir/business.php",
    report: "https://www.chinamobileltd.com/en/ir/reports/ar2024.pdf",
    faq: "https://www.chinamobileltd.com/sc/ir/faq.php",
    sustainability: "https://www.chinamobileltd.com/sc/file/view.php?id=310003"
  };

  const DATA = {
    infrastructure: [
      { title: "5G基站建设总数", color: "#66cfff", unit: "万座", prefix: ">", labels: ["2022", "2023", "2024"], values: [128.5, 194, 240] },
      { title: "已开通基站总数", color: "#62dfb5", unit: "万座", prefix: ">", labels: ["2022", "2023", "2024"], values: [600, 660, 686] },
      { title: "光缆长度", color: "#a78bfa", unit: "万皮长公里", labels: ["2022", "2023", "2024"], values: [2594, 2874, 3586] },
      { title: "骨干传送网带宽", color: "#efb65a", unit: "Tbps", prefix: ">", labels: ["2022", "2023", "2024"], values: [809, 859, 1042] }
    ],
    customer: [
      { title: "移动客户", color: "#66cfff", unit: "百万户", labels: ["23Q4", "24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [991, 996, 1000, 1004, 1004, 1003, 1005, 1009] },
      { title: "5G网络客户", color: "#62dfb5", unit: "百万户", labels: ["23Q4", "24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [465, 488, 514, 539, 552, 578, 599, 622] },
      { title: "有线宽带客户", color: "#efb65a", unit: "百万户", labels: ["23Q4", "24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [298, 305, 309, 314, 315, 320, 323, 329] }
    ],
    reach: [
      { title: "政企客户", color: "#66cfff", unit: "百万家", labels: ["2022", "2023", "2024"], values: [23.20, 28.37, 32.59] },
      { title: "物联网卡客户", color: "#62dfb5", unit: "百万", labels: ["2022", "2023", "2024"], values: [1062, 1316, 1416] },
      { title: "4G国际漫游覆盖", color: "#a78bfa", unit: "国家和地区", labels: ["2022", "2023", "2024"], values: [218, 229, 241] },
      { title: "5G国际漫游覆盖", color: "#efb65a", unit: "国家和地区", labels: ["2022", "2023", "2024"], values: [60, 75, 87] }
    ],
    finance: [
      { title: "营运收入", color: "#66cfff", unit: "人民币十亿元", total: 794.7, labels: ["24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [263.7, 283.0, 244.8, 249.3, 263.8, 280.0, 250.9] },
      { title: "EBITDA", color: "#62dfb5", unit: "人民币十亿元", total: 265.4, labels: ["24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [78.0, 104.3, 80.8, 70.6, 80.7, 105.3, 79.4] },
      { title: "股东应占利润", color: "#efb65a", unit: "人民币十亿元", total: 115.4, labels: ["24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"], values: [29.6, 50.6, 30.7, 27.5, 30.6, 53.6, 31.2] }
    ]
  };

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[character]);
  const formatNumber = (value, digits = 1) => Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });

  function sourceLink(label, url, period) {
    return `<div class="source-row"><span>${escapeHtml(period)}</span><a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)} ↗</a></div>`;
  }

  function lineChart(series, options = {}) {
    const width = 360;
    const height = options.compact ? 96 : 164;
    const pad = { left: 18, right: 12, top: 16, bottom: options.compact ? 20 : 28 };
    const minValue = Math.min(...series.values);
    const maxValue = Math.max(...series.values);
    const buffer = Math.max((maxValue - minValue) * 0.18, maxValue * 0.025, 1);
    const low = Math.max(0, minValue - buffer);
    const high = maxValue + buffer;
    const chartWidth = width - pad.left - pad.right;
    const chartHeight = height - pad.top - pad.bottom;
    const points = series.values.map((value, index) => ({
      x: pad.left + (index * chartWidth) / Math.max(series.values.length - 1, 1),
      y: pad.top + ((high - value) / Math.max(high - low, 1)) * chartHeight,
      value,
      label: series.labels[index]
    }));
    const line = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
    const area = `${line} L${points.at(-1).x.toFixed(2)} ${height - pad.bottom} L${points[0].x.toFixed(2)} ${height - pad.bottom} Z`;
    const labels = points.map((point, index) => index % (options.compact ? 2 : 1) === 0 || index === points.length - 1
      ? `<text x="${point.x}" y="${height - 5}" text-anchor="${index === 0 ? "start" : index === points.length - 1 ? "end" : "middle"}">${escapeHtml(point.label)}</text>`
      : "").join("");
    const marks = points.map((point) => `<g class="chart-point" tabindex="0" role="img" aria-label="${escapeHtml(point.label)} ${formatNumber(point.value)} ${escapeHtml(series.unit)}"><circle cx="${point.x}" cy="${point.y}" r="3.2"><title>${escapeHtml(point.label)}：${formatNumber(point.value)} ${escapeHtml(series.unit)}</title></circle></g>`).join("");
    return `<svg class="data-chart line-chart ${options.compact ? "is-compact" : ""}" style="--chart-color:${series.color}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(series.title)}官方披露趋势"><path class="chart-grid" d="M${pad.left} ${pad.top}H${width - pad.right} M${pad.left} ${pad.top + chartHeight / 2}H${width - pad.right} M${pad.left} ${height - pad.bottom}H${width - pad.right}"/><path class="chart-area" d="${area}"/><path class="chart-line" pathLength="1" d="${line}"/>${marks}<g class="chart-labels">${labels}</g></svg>`;
  }

  function columnChart(series, options = {}) {
    const width = 360;
    const height = options.compact ? 96 : 164;
    const pad = { left: 20, right: 12, top: 18, bottom: options.compact ? 21 : 30 };
    const maxValue = Math.max(...series.values) * 1.16;
    const plotHeight = height - pad.top - pad.bottom;
    const slot = (width - pad.left - pad.right) / series.values.length;
    const bars = series.values.map((value, index) => {
      const barHeight = (value / maxValue) * plotHeight;
      const barWidth = Math.min(slot * .56, options.compact ? 32 : 52);
      const x = pad.left + index * slot + (slot - barWidth) / 2;
      const y = height - pad.bottom - barHeight;
      return `<g class="column-mark" tabindex="0" role="img" aria-label="${escapeHtml(series.labels[index])} ${formatNumber(value)} ${escapeHtml(series.unit)}"><rect x="${x}" y="${y}" width="${barWidth}" height="${barHeight}" rx="3"><title>${escapeHtml(series.labels[index])}：${formatNumber(value)} ${escapeHtml(series.unit)}</title></rect><text x="${x + barWidth / 2}" y="${Math.max(y - 5, 10)}" text-anchor="middle">${formatNumber(value, Number.isInteger(value) ? 0 : 2)}</text><text class="axis-label" x="${x + barWidth / 2}" y="${height - 5}" text-anchor="middle">${escapeHtml(series.labels[index])}</text></g>`;
    }).join("");
    return `<svg class="data-chart column-chart ${options.compact ? "is-compact" : ""}" style="--chart-color:${series.color}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(series.title)}官方柱状趋势"><path class="chart-grid" d="M${pad.left} ${height - pad.bottom}H${width - pad.right}"/>${bars}</svg>`;
  }

  function lollipopChart(series, options = {}) {
    const width = 360;
    const height = options.compact ? 96 : 164;
    const pad = { left: 22, right: 12, top: 18, bottom: options.compact ? 21 : 30 };
    const maxValue = Math.max(...series.values) * 1.17;
    const plotHeight = height - pad.top - pad.bottom;
    const slot = (width - pad.left - pad.right) / series.values.length;
    const marks = series.values.map((value, index) => {
      const x = pad.left + slot * index + slot / 2;
      const y = height - pad.bottom - (value / maxValue) * plotHeight;
      return `<g class="lollipop-mark" tabindex="0" role="img" aria-label="${escapeHtml(series.labels[index])} ${formatNumber(value)} ${escapeHtml(series.unit)}"><line x1="${x}" y1="${height - pad.bottom}" x2="${x}" y2="${y}"/><circle cx="${x}" cy="${y}" r="5"><title>${escapeHtml(series.labels[index])}：${formatNumber(value)} ${escapeHtml(series.unit)}</title></circle><text x="${x}" y="${Math.max(y - 8, 10)}" text-anchor="middle">${formatNumber(value, Number.isInteger(value) ? 0 : 2)}</text><text class="axis-label" x="${x}" y="${height - 5}" text-anchor="middle">${escapeHtml(series.labels[index])}</text></g>`;
    }).join("");
    return `<svg class="data-chart lollipop-chart ${options.compact ? "is-compact" : ""}" style="--chart-color:${series.color}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(series.title)}官方棒棒糖趋势"><path class="chart-grid" d="M${pad.left} ${height - pad.bottom}H${width - pad.right}"/>${marks}</svg>`;
  }

  function horizontalBarChart(series, options = {}) {
    const width = 360;
    const height = options.compact ? 96 : 164;
    const maxValue = Math.max(...series.values) * 1.18;
    const left = 50;
    const right = 45;
    const rowHeight = (height - 14) / series.values.length;
    const rows = series.values.map((value, index) => {
      const y = 7 + index * rowHeight + rowHeight * .2;
      const barHeight = rowHeight * .42;
      const barWidth = ((width - left - right) * value) / maxValue;
      return `<g class="horizontal-mark" tabindex="0" role="img" aria-label="${escapeHtml(series.labels[index])} ${formatNumber(value)} ${escapeHtml(series.unit)}"><text class="axis-label" x="0" y="${y + barHeight * .78}">${escapeHtml(series.labels[index])}</text><rect x="${left}" y="${y}" width="${barWidth}" height="${barHeight}" rx="3"><title>${escapeHtml(series.labels[index])}：${formatNumber(value)} ${escapeHtml(series.unit)}</title></rect><text x="${left + barWidth + 7}" y="${y + barHeight * .78}">${formatNumber(value, Number.isInteger(value) ? 0 : 2)}</text></g>`;
    }).join("");
    return `<svg class="data-chart horizontal-chart ${options.compact ? "is-compact" : ""}" style="--chart-color:${series.color}" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(series.title)}官方横向条形趋势">${rows}</svg>`;
  }

  const CHARTS = { line: lineChart, column: columnChart, lollipop: lollipopChart, horizontal: horizontalBarChart };

  function trendCard(series, chartType, options = {}) {
    const latest = options.total ?? series.values.at(-1);
    const digits = options.digits ?? (Number.isInteger(latest) ? 0 : 1);
    const context = options.context || `${series.labels[0]}–${series.labels.at(-1)}`;
    return `<section class="trend-card" style="--group-accent:${series.color}">
      <header><strong>${escapeHtml(series.title)}</strong><small>${escapeHtml(options.badge || "官方披露")}</small></header>
      <div class="trend-card-kpi"><strong>${escapeHtml(series.prefix || "")}${formatNumber(latest, digits)}<small>${escapeHtml(series.unit)}</small></strong><em>${escapeHtml(options.note || context)}</em></div>
      <div class="trend-card-chart">${CHARTS[chartType](series)}</div>
      ${sourceLink(options.sourceLabel, options.sourceUrl, context)}
    </section>`;
  }

  function renderNetwork() {
    const chartTypes = ["column", "column", "line", "lollipop"];
    document.querySelector("#network-detail").innerHTML = `<div class="balanced-grid infrastructure-grid">${DATA.infrastructure.map((series, index) => trendCard(series, chartTypes[index], {
      badge: "年度数据",
      context: "2022–2024",
      sourceLabel: "中国移动年报及可持续发展报告",
      sourceUrl: OFFICIAL.sustainability,
      digits: Number.isInteger(series.values.at(-1)) ? 0 : 1
    })).join("")}</div>`;
  }

  function renderBusiness() {
    const penetration = {
      title: "5G客户渗透率",
      color: "#a78bfa",
      unit: "%",
      labels: DATA.customer[0].labels,
      values: DATA.customer[1].values.map((value, index) => Number(((value / DATA.customer[0].values[index]) * 100).toFixed(1)))
    };
    const businessSeries = [...DATA.customer, penetration];
    const chartTypes = ["column", "line", "lollipop", "line"];
    document.querySelector("[data-business-cards]").innerHTML = businessSeries.map((series, index) => {
      const latest = series.values.at(-1);
      const previous = series.values.at(-2);
      const delta = latest - previous;
      return trendCard(series, chartTypes[index], {
        badge: index === 3 ? "官方数据计算" : "季度数据",
        context: "2023Q4–2025Q3",
        note: `25Q3 环比 ${delta >= 0 ? "+" : ""}${formatNumber(delta, index === 3 ? 1 : 0)}${index === 3 ? "pct" : ""}`,
        sourceLabel: "中国移动营运数据",
        sourceUrl: OFFICIAL.quarterly,
        digits: index === 3 ? 1 : 0
      });
    }).join("");
  }

  function renderReach() {
    const chartTypes = ["lollipop", "column", "horizontal", "column"];
    document.querySelector("[data-reach-content]").innerHTML = `<div class="balanced-grid reach-trend-grid">${DATA.reach.map((series, index) => trendCard(series, chartTypes[index], {
      badge: "年度数据",
      context: "2022–2024",
      sourceLabel: "中国移动可持续发展报告",
      sourceUrl: OFFICIAL.sustainability,
      digits: series.values.at(-1) < 100 ? 2 : 0
    })).join("")}</div>`;
  }

  function renderFinance() {
    const margin = {
      title: "EBITDA率",
      color: "#a78bfa",
      unit: "%",
      total: Number(((DATA.finance[1].total / DATA.finance[0].total) * 100).toFixed(1)),
      labels: DATA.finance[0].labels,
      values: DATA.finance[1].values.map((value, index) => Number(((value / DATA.finance[0].values[index]) * 100).toFixed(1)))
    };
    const financeSeries = [...DATA.finance, margin];
    const chartTypes = ["column", "line", "lollipop", "line"];
    document.querySelector("[data-finance-content]").innerHTML = `<div class="finance-card-grid">${financeSeries.map((series, index) => trendCard(series, chartTypes[index], {
      badge: index === 3 ? "官方数据计算" : "季度数据",
      total: series.total,
      context: "2024Q1–2025Q3",
      note: "2025年前三季度累计",
      sourceLabel: "中国移动季度营运数据",
      sourceUrl: OFFICIAL.quarterly,
      digits: 1
    })).join("")}</div>`;
  }

  function setupMotion() {
    const panels = Array.from(document.querySelectorAll(".panel"));
    panels.forEach((panel, index) => panel.style.setProperty("--panel-delay", `${index * 70}ms`));
    document.body.classList.add("motion-enabled");
    const show = (panel) => panel.classList.add("is-visible");
    if (!("IntersectionObserver" in window)) { panels.forEach(show); return; }
    const observer = new IntersectionObserver((entries) => entries.forEach((entry) => { if (entry.isIntersecting) { show(entry.target); observer.unobserve(entry.target); } }), { threshold: 0.1 });
    panels.forEach((panel) => observer.observe(panel));
  }

  renderNetwork();
  renderBusiness();
  renderReach();
  renderFinance();
  setupMotion();
})();
