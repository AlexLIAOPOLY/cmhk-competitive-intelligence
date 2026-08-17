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
  const metricCard = ([label, value, unit, trend = ""]) => `
    <div class="monitor-kpi">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></strong>
      ${trend ? `<em>${escapeHtml(trend)}</em>` : ""}
    </div>`;

  function renderNetwork() {
    const visual = document.querySelector("[data-network-visual]");
    const metrics = document.querySelector("[data-network-metrics]");
    const bars = [["4G基站", 6880, "座"], ["5G基站", 3700, "座"], ["智算能力", 4860, "PFLOPS"]];
    const max = Math.max(...bars.map((item) => Number(item[1])));
    visual.innerHTML = `
      <div class="section-label"><span>CMHK 单体监控</span><strong>网络与算力资源</strong></div>
      <div class="bar-visual">${bars.map(([label, value, unit]) => {
        const height = Math.max(22, Math.min(100, (Number(value) / max) * 100));
        return `<div class="bar-column"><b style="--bar:${height}%"><i>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></i></b><span>${escapeHtml(label)}</span></div>`;
      }).join("")}</div>`;
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
      <section class="reach-primary">
        <div class="reach-signal" aria-hidden="true"><i style="--signal:${index ? 86 : 64}%"></i></div>
        ${metricCard(metric)}
      </section>`).join("");
  }

  function renderFinance() {
    const target = document.querySelector("[data-finance-content]");
    target.innerHTML = financeMetrics.map((metric, index) => `
      <section class="finance-primary finance-primary-${index + 1}">
        <div class="finance-pulse" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
        ${metricCard(metric)}
      </section>`).join("");
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
