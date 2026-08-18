(() => {
  "use strict";

  const SOURCES = {
    sustainability: "https://www.chinamobileltd.com/en/ir/reports/ar2024/sd2024.pdf",
    business: "https://www.chinamobileltd.com/sc/ir/business.php",
    quarterly: "https://www.chinamobileltd.com/sc/ir/operation_q.php"
  };

  const networkMetrics = [
    { label: "4G基站总数", value: ">339", unit: "万座", trend: "2024年末", periods: ["2022", "2023", "2024"], values: [334, 337, 339], valueLabels: ["334", "337", ">339"], source: SOURCES.sustainability },
    { label: "5G基站总数", value: ">240", unit: "万座", trend: "2024年末", periods: ["2022", "2023", "2024"], values: [128.5, 194, 240], valueLabels: ["128.5", ">194", ">240"], source: SOURCES.sustainability },
    { label: "互联网骨干带宽", value: "633", unit: "Tbps", trend: "2024年末", periods: ["2022", "2023", "2024"], values: [519, 633, 633], source: SOURCES.sustainability }
  ];

  const businessGroups = [
    { title: "移动业务", accent: "blue", metrics: [
      { label: "移动客户数", value: "1,004", unit: "百万户", trend: "+1.3%", periods: ["2022", "2023", "2024"], values: [975, 991, 1004], source: SOURCES.sustainability },
      { label: "移动ARPU", value: "48.5", unit: "元/户/月", trend: "-1.6%", periods: ["2022", "2023", "2024"], values: [49.0, 49.3, 48.5], source: SOURCES.business }
    ] },
    { title: "家庭业务", accent: "green", metrics: [
      { label: "有线宽带客户数", value: "315", unit: "百万户", trend: "+5.5%", periods: ["2022", "2023", "2024"], values: [272, 298, 315], source: SOURCES.sustainability },
      { label: "家庭客户综合ARPU", value: "43.8", unit: "元/户/月", trend: "+1.6%", periods: ["2022", "2023", "2024"], values: [42.1, 43.1, 43.8], source: SOURCES.business }
    ] },
    { title: "政企与数字化业务", accent: "amber", metrics: [
      { label: "政企客户数", value: "32.59", unit: "百万家", trend: "+14.9%", periods: ["2022", "2023", "2024"], values: [23.20, 28.37, 32.59], source: SOURCES.sustainability },
      { label: "物联网卡客户数", value: "1,416", unit: "百万", trend: "+7.6%", periods: ["2022", "2023", "2024"], values: [1062, 1316, 1416], source: SOURCES.sustainability }
    ] }
  ];

  const reachMetrics = [
    { label: "4G国际漫游覆盖", value: "241", unit: "个国家和地区", trend: "+5.2%", periods: ["2022", "2023", "2024"], values: [218, 229, 241], source: SOURCES.sustainability, dial: 86, color: "#55d9ff" },
    { label: "5G国际漫游覆盖", value: "87", unit: "个国家和地区", trend: "+16.0%", periods: ["2022", "2023", "2024"], values: [60, 75, 87], source: SOURCES.sustainability, dial: 72, color: "#5de2b6" }
  ];

  const quarterlyPeriods = ["24Q1", "24Q2", "24Q3", "24Q4", "25Q1", "25Q2", "25Q3"];
  const financeMetrics = [
    { label: "营运收入", value: "794.7", unit: "人民币十亿元", trend: "前三季度 +0.4%", periods: quarterlyPeriods, values: [263.7, 283.0, 244.8, 249.3, 263.8, 280.0, 250.9], source: SOURCES.quarterly },
    { label: "EBITDA", value: "265.4", unit: "人民币十亿元", trend: "前三季度 +0.9%", periods: quarterlyPeriods, values: [78.0, 104.3, 80.8, 70.6, 80.7, 105.3, 79.4], source: SOURCES.quarterly, gauge: 75 },
    { label: "股东应占利润", value: "115.4", unit: "人民币十亿元", trend: "前三季度 +4.0%", periods: quarterlyPeriods, values: [29.6, 50.6, 30.7, 27.5, 30.6, 53.6, 31.2], source: SOURCES.quarterly, gauge: 75 }
  ];

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const displayValue = (metric, index) => metric.valueLabels?.[index] ?? String(metric.values[index]);
  const tooltipText = (metric) => `${metric.label}\n${metric.periods.map((period, index) => `${period}：${displayValue(metric, index)} ${metric.unit}`).join("\n")}\n来源：中国移动公开数据`;

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
    <div class="monitor-kpi has-data-tooltip" tabindex="0" data-source="${escapeHtml(metric.source)}" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--metric-order:${index}">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}<small>${escapeHtml(metric.unit)}</small></strong>
      ${metric.trend ? `<em class="${metric.trend.startsWith("-") ? "is-negative" : ""}">${escapeHtml(metric.trend)}</em>` : ""}
      ${sparkline(metric)}
    </div>`;

  function renderNetwork() {
    const visual = document.querySelector("[data-network-visual]");
    const metrics = document.querySelector("[data-network-metrics]");
    visual.innerHTML = `
      <div class="section-label"><span>CHINA MOBILE NETWORK</span><strong>网络与算力资源</strong></div>
      <div class="network-topology" aria-hidden="true">
        <div class="topology-orbit orbit-one"><i></i><i></i><i></i></div>
        <div class="topology-orbit orbit-two"><i></i><i></i><i></i><i></i></div>
        <div class="topology-core"><b>CMCC</b><span>CORE</span></div>
        <div class="topology-beam beam-a"></div><div class="topology-beam beam-b"></div><div class="topology-beam beam-c"></div>
      </div>`;
    metrics.innerHTML = networkMetrics.map(metricCard).join("");
  }

  function renderBusiness() {
    const target = document.querySelector("[data-business-cards]");
    target.innerHTML = businessGroups.map((group) => `
      <section class="business-card ${group.accent}">
        <header><strong>${escapeHtml(group.title)}</strong></header>
        <div class="business-pair">${group.metrics.map(metricCard).join("")}</div>
      </section>`).join("");
  }

  function renderReach() {
    const target = document.querySelector("[data-reach-content]");
    target.innerHTML = reachMetrics.map((metric, index) => {
      const max = Math.max(...metric.values);
      return `<section class="reach-dial-card has-data-tooltip" tabindex="0" data-source="${escapeHtml(metric.source)}" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--dial:${metric.dial}; --dial-color:${metric.color}">
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

  function financeChart(metric) {
    const { points, line } = chartGeometry(metric.values, 480, 170, 0, 24);
    const area = `${line} L480 170 L0 170 Z`;
    return `<svg class="finance-area-chart" viewBox="0 0 480 170" preserveAspectRatio="none" role="img" aria-label="营运收入季度真实趋势">
      <defs><linearGradient id="financeArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#54d9ff" stop-opacity=".42"/><stop offset="1" stop-color="#357ee8" stop-opacity="0"/></linearGradient></defs>
      <path class="finance-grid-line" d="M0 42H480M0 85H480M0 128H480"/>
      <path class="finance-area" d="${area}"/>
      <path class="finance-line" d="${line}"/>
      <g class="finance-points">${points.map((point, index) => `<circle cx="${point.x}" cy="${point.y}" r="4"><title>${escapeHtml(metric.periods[index])}：${escapeHtml(metric.values[index])} ${escapeHtml(metric.unit)}</title></circle>`).join("")}</g>
    </svg>`;
  }

  function renderFinance() {
    const target = document.querySelector("[data-finance-content]");
    const revenue = financeMetrics[0];
    target.innerHTML = `
      <section class="finance-revenue-hero has-data-tooltip" tabindex="0" data-source="${escapeHtml(revenue.source)}" data-tooltip="${escapeHtml(tooltipText(revenue))}">
        <div class="finance-revenue-copy"><span>${escapeHtml(revenue.label)}</span><strong>${escapeHtml(revenue.value)}<small>${escapeHtml(revenue.unit)}</small></strong><em>${escapeHtml(revenue.trend)}</em></div>
        ${financeChart(revenue)}
      </section>
      <div class="finance-gauge-stack">${financeMetrics.slice(1).map((metric, index) => `
        <section class="finance-gauge-card gauge-${index + 1} has-data-tooltip" tabindex="0" data-source="${escapeHtml(metric.source)}" data-tooltip="${escapeHtml(tooltipText(metric))}" style="--gauge:${metric.gauge}">
          <div class="finance-gauge" aria-hidden="true"><i></i><span></span></div>
          ${metricCard(metric, index)}
        </section>`).join("")}</div>`;
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

  renderNetwork();
  renderBusiness();
  renderReach();
  renderFinance();
  setupMotion();
})();
