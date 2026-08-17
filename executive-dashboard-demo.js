(() => {
  "use strict";

  /* ---------------------------------------------------------------------
   * 指标数据
   * label 为主标签，note 为口径补充说明（避免主标签过长破坏排版）
   * ------------------------------------------------------------------- */

  const NETWORK_METRICS = [
    { label: "基站总数", note: "4G", value: "6,880", unit: "座", delta: "+2.6%" },
    { label: "基站总数", note: "5G", value: "3,700", unit: "座", delta: "+8.4%" },
    { label: "智算能力", note: "PFLOPS", value: "4,860", unit: "PFLOPS", delta: "+14.2%" }
  ];

  const BUSINESS_GROUPS = [
    {
      title: "移动业务",
      caption: "MOBILE",
      accent: "cyan",
      metrics: [
        { label: "总移动用户数", value: "342.8", unit: "万户", delta: "+5.6%" },
        { label: "移动综合 ARPU", value: "138.6", unit: "港元", delta: "+3.9%" }
      ]
    },
    {
      title: "家庭业务",
      caption: "HOME",
      accent: "mint",
      metrics: [
        { label: "家庭宽带用户数", value: "86.4", unit: "万户", delta: "+6.3%" },
        { label: "家庭户均收益", note: "ARPU", value: "198.2", unit: "港元", delta: "+3.2%" }
      ]
    },
    {
      title: "政企与数字化业务",
      caption: "ENTERPRISE",
      accent: "amber",
      metrics: [
        {
          label: "客户数",
          note: "大中型企业 / 中小企业 · 参考政府公布的分类",
          value: "38,200",
          unit: "户",
          delta: "+8.1%"
        },
        { label: "项目签约额", value: "28.6", unit: "亿港元", delta: "+12.7%" }
      ]
    }
  ];

  const REACH_METRICS = [
    {
      label: "全港实体门市数量",
      note: "线下渠道",
      value: "138",
      unit: "间",
      delta: "+4",
      accent: "cyan"
    },
    {
      label: "官方手机应用程式活跃用户数",
      note: "如 MyLink",
      value: "218",
      unit: "万",
      delta: "+9.8%",
      accent: "mint"
    }
  ];

  const FINANCE_HERO = { label: "营运收入", value: "96.8", unit: "亿港元", delta: "+5.2%" };

  const FINANCE_METRICS = [
    { label: "EBITDA 率", value: "35.9", unit: "%", delta: "+1.6pct", accent: "cyan" },
    { label: "净利润", value: "12.4", unit: "亿港元", delta: "+8.7%", accent: "amber" }
  ];

  /* ------------------------------------------------------------------ */

  const HTML_ENTITIES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => HTML_ENTITIES[char]);

  const deltaAmount = (delta) => {
    const match = /-?\d+(?:\.\d+)?/.exec(String(delta || ""));
    return match ? Math.abs(parseFloat(match[0])) : 0;
  };

  const isNegative = (delta) => String(delta || "").trim().startsWith("-");

  const deltaChip = (delta) => {
    if (!delta) return "";
    const direction = isNegative(delta) ? "is-down" : "is-up";
    return `<span class="delta ${direction}"><i aria-hidden="true"></i>${escapeHtml(delta)}</span>`;
  };

  const labelBlock = (metric) => `
    <p class="kpi-label">
      <span>${escapeHtml(metric.label)}</span>
      ${metric.note ? `<em>${escapeHtml(metric.note)}</em>` : ""}
    </p>`;

  const valueBlock = (metric, size = "") => `
    <p class="kpi-value${size ? ` ${size}` : ""}">
      <span class="num" data-count="${escapeHtml(metric.value)}">${escapeHtml(metric.value)}</span>
      <small>${escapeHtml(metric.unit)}</small>
    </p>`;

  /** 进度轨代表同比变动幅度在本板块内的相对强度，非绝对数值比例。 */
  const meterBlock = (metric, peak) => {
    const amount = deltaAmount(metric.delta);
    const ratio = peak > 0 ? Math.max(0.22, amount / peak) : 0.22;
    return `<span class="meter" aria-hidden="true"><i style="--fill:${(ratio * 100).toFixed(1)}%"></i></span>`;
  };

  function renderNetwork() {
    const stage = document.querySelector("[data-network-visual]");
    const list = document.querySelector("[data-network-metrics]");
    if (!stage || !list) return;

    stage.innerHTML = `
      <figure class="topology" aria-hidden="true">
        <span class="topology-ring ring-1"></span>
        <span class="topology-ring ring-2"></span>
        <span class="topology-ring ring-3"></span>
        <span class="topology-node node-1"></span>
        <span class="topology-node node-2"></span>
        <span class="topology-node node-3"></span>
        <span class="topology-node node-4"></span>
        <span class="topology-node node-5"></span>
        <span class="topology-core"><b>CMHK</b><i>CORE NETWORK</i></span>
      </figure>
      <figcaption class="topology-caption">
        <span>CMHK NETWORK FABRIC</span>
        <strong>全网资源统一纳管</strong>
      </figcaption>`;

    const peak = Math.max(...NETWORK_METRICS.map((metric) => deltaAmount(metric.delta)));
    list.innerHTML = NETWORK_METRICS.map((metric, index) => `
      <article class="kpi kpi-row" style="--order:${index}">
        <span class="kpi-rank">${String(index + 1).padStart(2, "0")}</span>
        <div class="kpi-main">
          ${labelBlock(metric)}
          ${valueBlock(metric)}
        </div>
        <div class="kpi-trend">
          ${deltaChip(metric.delta)}
          ${meterBlock(metric, peak)}
        </div>
      </article>`).join("");
  }

  function renderBusiness() {
    const target = document.querySelector("[data-business-cards]");
    if (!target) return;

    target.innerHTML = BUSINESS_GROUPS.map((group, groupIndex) => {
      const peak = Math.max(...group.metrics.map((metric) => deltaAmount(metric.delta)));
      return `
      <article class="business-card accent-${group.accent}" style="--order:${groupIndex}">
        <header class="business-card-head">
          <h3>${escapeHtml(group.title)}</h3>
          <span>${escapeHtml(group.caption)}</span>
        </header>
        <div class="business-card-body">
          ${group.metrics.map((metric) => `
          <div class="kpi kpi-stack">
            ${labelBlock(metric)}
            ${valueBlock(metric)}
            <div class="kpi-trend">
              ${deltaChip(metric.delta)}
              ${meterBlock(metric, peak)}
            </div>
          </div>`).join("")}
        </div>
      </article>`;
    }).join("");
  }

  function renderReach() {
    const target = document.querySelector("[data-reach-content]");
    if (!target) return;

    target.innerHTML = REACH_METRICS.map((metric, index) => `
      <article class="reach-card accent-${metric.accent}" style="--order:${index}">
        <span class="reach-mark" aria-hidden="true"><i></i><b>${String(index + 1).padStart(2, "0")}</b></span>
        <div class="reach-copy">
          ${labelBlock(metric)}
          ${valueBlock(metric, "is-large")}
          ${deltaChip(metric.delta)}
        </div>
        <span class="reach-bars" aria-hidden="true">${Array.from({ length: 9 }, (_, bar) =>
          `<i style="--bar:${38 + ((bar * (index ? 7 : 5) + index * 11) % 60)}%;--bar-order:${bar}"></i>`).join("")}</span>
      </article>`).join("");
  }

  function renderFinance() {
    const target = document.querySelector("[data-finance-content]");
    if (!target) return;

    const peak = Math.max(...FINANCE_METRICS.map((metric) => deltaAmount(metric.delta)));
    target.innerHTML = `
      <article class="finance-hero">
        <div class="finance-hero-copy">
          ${labelBlock(FINANCE_HERO)}
          ${valueBlock(FINANCE_HERO, "is-hero")}
          ${deltaChip(FINANCE_HERO.delta)}
        </div>
        <div class="finance-chart">
          <svg viewBox="0 0 480 150" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <linearGradient id="financeArea" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0" stop-color="#4cc9f0" stop-opacity=".34"/>
                <stop offset="1" stop-color="#4cc9f0" stop-opacity="0"/>
              </linearGradient>
            </defs>
            <path class="chart-grid" d="M0 38H480M0 76H480M0 114H480"/>
            <path class="chart-area" d="M0 126 L68 112 L137 117 L206 83 L274 91 L343 55 L411 66 L480 25 L480 150 L0 150 Z"/>
            <path class="chart-line" d="M0 126 L68 112 L137 117 L206 83 L274 91 L343 55 L411 66 L480 25"/>
            <g class="chart-dots"><circle cx="206" cy="83" r="3.4"/><circle cx="343" cy="55" r="3.4"/><circle cx="480" cy="25" r="3.4"/></g>
          </svg>
          <p class="finance-chart-caption"><span>营运收入走势</span><span>近八期</span></p>
        </div>
      </article>
      <div class="finance-side">
        ${FINANCE_METRICS.map((metric, index) => `
        <article class="kpi kpi-card accent-${metric.accent}" style="--order:${index}">
          ${labelBlock(metric)}
          ${valueBlock(metric)}
          <div class="kpi-trend">
            ${deltaChip(metric.delta)}
            ${meterBlock(metric, peak)}
          </div>
        </article>`).join("")}
      </div>`;
  }

  /* ------------------------------------------------------------------ */

  function formatLike(template, value) {
    const decimals = (template.split(".")[1] || "").length;
    const grouped = template.includes(",");
    const fixed = value.toFixed(decimals);
    if (!grouped) return fixed;
    const [whole, fraction] = fixed.split(".");
    const spaced = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return fraction ? `${spaced}.${fraction}` : spaced;
  }

  function animateNumbers(reducedMotion) {
    const nodes = Array.from(document.querySelectorAll(".num[data-count]"));
    if (reducedMotion) return;

    nodes.forEach((node, index) => {
      const template = node.dataset.count || "";
      const target = parseFloat(template.replace(/,/g, ""));
      if (!Number.isFinite(target)) return;

      const duration = 1000;
      const delay = 120 + index * 55;
      const start = performance.now() + delay;
      node.textContent = formatLike(template, 0);

      const step = (now) => {
        if (now < start) {
          window.requestAnimationFrame(step);
          return;
        }
        const progress = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - progress, 3);
        node.textContent = formatLike(template, target * eased);
        if (progress < 1) window.requestAnimationFrame(step);
        else node.textContent = template;
      };
      window.requestAnimationFrame(step);
    });
  }

  function revealPanels(reducedMotion) {
    const panels = Array.from(document.querySelectorAll(".panel"));
    panels.forEach((panel, index) => panel.style.setProperty("--panel-delay", `${index * 90}ms`));

    if (reducedMotion || !("IntersectionObserver" in window)) {
      panels.forEach((panel) => panel.classList.add("is-visible"));
      return;
    }
    document.body.classList.add("motion-enabled");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    }, { threshold: 0.1 });
    panels.forEach((panel) => observer.observe(panel));
  }

  function startClock() {
    const node = document.querySelector("[data-clock]");
    if (!node) return;
    const tick = () => {
      const now = new Date();
      const pad = (part) => String(part).padStart(2, "0");
      node.dateTime = now.toISOString();
      node.textContent = `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())}　${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
    };
    tick();
    window.setInterval(tick, 1000);
  }

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  renderNetwork();
  renderBusiness();
  renderReach();
  renderFinance();
  revealPanels(reducedMotion);
  animateNumbers(reducedMotion);
  startClock();
})();
