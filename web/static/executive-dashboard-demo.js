(() => {
  "use strict";

  const networkMetrics = [
    ["基站总数（4G）", "6,880", "座", "+2.6%"],
    ["基站总数（5G）", "3,700", "座", "+8.4%"],
    ["智算能力 PFLOPS", "4,860", "PFLOPS", "+14.2%"]
  ];

  const businessGroups = [
    { title: "移动业务", accent: "blue", metrics: [["总移动用户数", "342.8", "万户", "+5.6%"], ["移动综合ARPU", "138.6", "港元", "+3.9%"]] },
    { title: "家庭业务", accent: "green", metrics: [["家庭宽带用户数", "86.4", "万户", "+6.3%"], ["家庭户均收益（ARPU）", "198.2", "港元", "+3.2%"]] },
    { title: "政企与数字化业务", accent: "amber", metrics: [["客户数（大中型企业/中小企业-参考政府公布的分类）", "38,200", "户", "+8.1%"], ["项目签约额", "28.6", "亿港元", "+12.7%"]] }
  ];

  const reachMetrics = [
    ["全港实体门市数量", "138", "间", "+4"],
    ["官方手机应用程式 (如MyLink) 活跃用户数", "218", "万", "+9.8%"]
  ];

  const financeMetrics = [
    ["营运收入", "96.8", "亿港元", "+5.2%"],
    ["EBITDA率", "35.9", "%", "+1.6pct"],
    ["净利润", "12.4", "亿港元", "+8.7%"]
  ];

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const metricCard = ([label, value, unit, trend = ""], index = 0) => `
    <div class="monitor-kpi" style="--metric-order:${index}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></strong>
      ${trend ? `<em>${escapeHtml(trend)}</em>` : ""}
    </div>`;

  function renderNetwork() {
    const visual = document.querySelector("[data-network-visual]");
    const metrics = document.querySelector("[data-network-metrics]");
    visual.innerHTML = `
      <div class="section-label"><span>CMHK NETWORK FABRIC</span><strong>网络与算力资源</strong></div>
      <div class="network-topology" aria-hidden="true">
        <div class="topology-orbit orbit-one"><i></i><i></i><i></i></div>
        <div class="topology-orbit orbit-two"><i></i><i></i><i></i><i></i></div>
        <div class="topology-core"><b>CMHK</b><span>CORE</span></div>
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
    target.innerHTML = reachMetrics.map((metric, index) => `
      <section class="reach-dial-card" style="--dial:${index ? 86 : 64}; --dial-color:${index ? "#5de2b6" : "#55d9ff"}">
        <div class="reach-dial" aria-hidden="true"><i></i><span></span><b>0${index + 1}</b></div>
        <div class="reach-dial-copy">
          <span>${escapeHtml(metric[0])}</span>
          <strong>${escapeHtml(metric[1])}<small>${escapeHtml(metric[2])}</small></strong>
          <em>${escapeHtml(metric[3])}</em>
          <div class="reach-wave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i></div>
        </div>
      </section>`).join("");
  }

  function renderFinance() {
    const target = document.querySelector("[data-finance-content]");
    const revenue = financeMetrics[0];
    target.innerHTML = `
      <section class="finance-revenue-hero">
        <div class="finance-revenue-copy"><span>${escapeHtml(revenue[0])}</span><strong>${escapeHtml(revenue[1])}<small>${escapeHtml(revenue[2])}</small></strong><em>${escapeHtml(revenue[3])}</em></div>
        <svg class="finance-area-chart" viewBox="0 0 480 170" preserveAspectRatio="none" aria-hidden="true">
          <defs><linearGradient id="financeArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#54d9ff" stop-opacity=".42"/><stop offset="1" stop-color="#357ee8" stop-opacity="0"/></linearGradient></defs>
          <path class="finance-grid-line" d="M0 42H480M0 85H480M0 128H480"/>
          <path class="finance-area" d="M0 142 L68 126 L137 132 L206 94 L274 103 L343 62 L411 75 L480 28 L480 170 L0 170 Z"/>
          <path class="finance-line" d="M0 142 L68 126 L137 132 L206 94 L274 103 L343 62 L411 75 L480 28"/>
          <g class="finance-points"><circle cx="68" cy="126" r="4"/><circle cx="206" cy="94" r="4"/><circle cx="343" cy="62" r="4"/><circle cx="480" cy="28" r="4"/></g>
        </svg>
      </section>
      <div class="finance-gauge-stack">${financeMetrics.slice(1).map((metric, index) => `
        <section class="finance-gauge-card gauge-${index + 1}" style="--gauge:${index ? 72 : 86}">
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
