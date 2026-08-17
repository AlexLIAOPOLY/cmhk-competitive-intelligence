(() => {
  "use strict";

  const networkViews = {
    fixed: {
      eyebrow: "固定网络基础设施",
      title: "高密度城区接入能力",
      bars: [["家居覆盖", 245, "万户"], ["商厦覆盖", 12800, "栋"], ["核心节点", 42, "个"], ["网络可用率", 99.99, "%"]],
      metrics: [["家居宽带覆盖", "245", "万户", "+4.8%"], ["商业楼宇覆盖", "12,800", "栋", "+6.2%"], ["核心网络节点", "42", "个", "+3"], ["网络可用率", "99.99", "%", "稳定"]]
    },
    mobile: {
      eyebrow: "移动网络基础设施",
      title: "4G / 5G 基站总数",
      bars: [["4G基站", 6880, "座"], ["5G基站", 3700, "座"], ["平均下载", 1.1, "Gbps"], ["室外覆盖", 98.8, "%"]],
      metrics: [["4G 基站", "6,880", "座", "+2.6%"], ["5G 基站", "3,700", "座", "+8.4%"], ["5G 频谱", "140", "MHz", "充足"], ["网络可用率", "99.99", "%", "稳定"]]
    },
    cloud: {
      eyebrow: "数据中心与云基础设施",
      title: "云网算力资源池",
      bars: [["数据中心", 6, "个"], ["智能算力", 4860, "PFLOPS"], ["机架利用率", 78, "%"], ["平均PUE", 1.28, ""]],
      metrics: [["数据中心", "6", "个", "+1"], ["智能算力", "4,860", "PFLOPS", "+14.2%"], ["机架利用率", "78", "%", "+5.0%"], ["平均 PUE", "1.28", "", "优化"]]
    },
    research: {
      eyebrow: "研发与技术储备",
      title: "创新能力建设进度",
      bars: [["专利储备", 486, "项"], ["研发项目", 36, "个"], ["技术进度", 92, "%"], ["联合实验室", 12, "个"]],
      metrics: [["专利储备", "486", "项", "+38"], ["在研项目", "36", "个", "+7"], ["5G-A / 6G 进度", "92", "%", "领先"], ["联合实验室", "12", "个", "+2"]]
    }
  };

  const businessViews = {
    toc: {
      code: "TOC", title: "移动业务", accent: "blue",
      metrics: [["总移动用户数", "342.8", "万户", "+5.6%"], ["5G 用户占比", "62", "%", "+7.8%"], ["移动综合 ARPU", "138.6", "港元", "+3.9%"], ["月均流量 DOU", "26.4", "GB", "+12.4%"]]
    },
    toh: {
      code: "TOH", title: "家庭业务", accent: "green",
      metrics: [["家庭宽带用户", "86.4", "万户", "+6.3%"], ["家庭市场渗透率", "41", "%", "+2.8%"], ["家庭综合 ARPU", "198.2", "港元", "+3.2%"], ["平均接入带宽", "310", "Mbps", "+18.6%"]]
    },
    tob: {
      code: "TOB", title: "政企与数字化业务", accent: "amber",
      metrics: [["政企客户数", "38,200", "户", "+8.1%"], ["ICT 收入占比", "36", "%", "+4.5%"], ["数字化项目", "1,286", "个", "+16.2%"], ["大型项目占比", "57", "%", "+6.0%"]]
    }
  };

  const reachViews = {
    brand: {
      score: 91.6, title: "品牌认知度", summary: "CMHK 用户首选心智持续领先",
      metrics: [["客户满意度", "89.2", "%"], ["品牌首选率", "87.6", "%"], ["品牌综合指数", "88.7", "分"], ["推荐意愿 NPS", "62", "分"]]
    },
    channel: {
      score: 88.4, title: "全渠道触达率", summary: "线下服务与数字渠道协同覆盖",
      metrics: [["实体门店", "138", "间"], ["社交平台", "8", "个"], ["网站月活", "96.8", "万"], ["APP 月活", "218", "万"]]
    }
  };

  const financeViews = {
    income: { title: "收入规模与结构", hero: ["96.8", "亿港元", "营运收入"], bars: [["移动业务", 61.4], ["家庭与政企", 22.8], ["终端及其他", 12.6]], metrics: [["移动业务收入", "61.4", "亿"], ["全业务收入", "84.2", "亿"], ["终端及附件", "12.6", "亿"], ["收入增幅", "+5.2", "%"]] },
    margin: { title: "盈利能力", hero: ["35.9", "%", "EBITDA 率"], bars: [["EBITDA", 34.8], ["净利润", 12.4], ["自由现金流", 10.8]], metrics: [["EBITDA", "34.8", "亿"], ["净利润", "12.4", "亿"], ["净利润率", "12.8", "%"], ["投入资本回报率", "12.6", "%"]] },
    cost: { title: "成本与效率", hero: ["3.2", "%", "运营效率改善"], bars: [["运营成本", 61.5], ["折旧前成本", 44.8], ["折旧摊销", 16.7]], metrics: [["运营成本", "61.5", "亿"], ["折旧前成本", "44.8", "亿"], ["折旧摊销", "16.7", "亿"], ["终端销售成本", "11.5", "亿"]] },
    investment: { title: "资本开支与投资", hero: ["18.9", "亿港元", "资本开支"], bars: [["移动网络", 7.9], ["云与数据中心", 5.1], ["频谱及其他", 5.9]], metrics: [["资本开支", "18.9", "亿"], ["频谱投资", "4.2", "亿"], ["资产回报率", "6.8", "%"], ["网络投资占比", "42", "%"]] }
  };

  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
  const metricCard = ([label, value, unit, trend = ""]) => `
    <div class="monitor-kpi">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></strong>
      ${trend ? `<em>${escapeHtml(trend)}</em>` : ""}
    </div>`;

  function renderNetwork(key) {
    const view = networkViews[key];
    const visual = document.querySelector("[data-network-visual]");
    const metrics = document.querySelector("[data-network-metrics]");
    const max = Math.max(...view.bars.map((item) => Number(item[1])));
    visual.innerHTML = `
      <div class="section-label"><span>${view.eyebrow}</span><strong>${view.title}</strong></div>
      <div class="bar-visual">${view.bars.map(([label, value, unit]) => {
        const height = Math.max(22, Math.min(100, (Number(value) / max) * 100));
        return `<div class="bar-column"><b style="--bar:${height}%"><i>${escapeHtml(value)}<small>${escapeHtml(unit)}</small></i></b><span>${escapeHtml(label)}</span></div>`;
      }).join("")}</div>`;
    metrics.innerHTML = view.metrics.map(metricCard).join("");
  }

  function renderBusiness(key) {
    const view = businessViews[key];
    const target = document.querySelector("[data-business-cards]");
    target.innerHTML = view.metrics.map((metric, index) => `
      <section class="business-card ${view.accent}">
        <header><b>${view.code}</b><span>${view.title}</span><i>0${index + 1}</i></header>
        <div class="mini-chart" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span></div>
        ${metricCard(metric)}
      </section>`).join("");
  }

  function renderReach(key) {
    const view = reachViews[key];
    const target = document.querySelector("[data-reach-content]");
    target.innerHTML = `
      <div class="reach-overview">
        <div class="score-ring" style="--score:${view.score}"><strong>${view.score}<small>%</small></strong></div>
        <div class="reach-copy"><span>${view.title}</span><strong>${view.summary}</strong><p>聚焦 CMHK 单体经营表现与触达效率。</p></div>
      </div>
      <div class="reach-metrics">${view.metrics.map(metricCard).join("")}</div>`;
  }

  function renderFinance(key) {
    const view = financeViews[key];
    const target = document.querySelector("[data-finance-content]");
    const max = Math.max(...view.bars.map((item) => item[1]));
    target.innerHTML = `
      <div class="finance-overview">
        <div class="finance-hero"><span>${view.hero[2]}</span><strong>${view.hero[0]}<small>${view.hero[1]}</small></strong><em>${view.title}</em></div>
        <div class="horizontal-bars">${view.bars.map(([label, value]) => `<div><span>${label}</span><i><b style="--bar:${Math.max(12, value / max * 100)}%"></b></i><strong>${value}</strong></div>`).join("")}</div>
      </div>
      <div class="finance-metrics">${view.metrics.map(metricCard).join("")}</div>`;
  }

  function setupTabs(config) {
    const buttons = Array.from(document.querySelectorAll(`[${config.attribute}]`));
    let active = Math.max(0, buttons.findIndex((button) => button.classList.contains("is-active")));
    let timer;
    const activate = (index, moveFocus = false) => {
      active = (index + buttons.length) % buttons.length;
      buttons.forEach((button, itemIndex) => {
        const selected = itemIndex === active;
        button.classList.toggle("is-active", selected);
        button.setAttribute("aria-selected", String(selected));
        button.tabIndex = selected ? 0 : -1;
      });
      config.render(buttons[active].getAttribute(config.attribute));
      if (moveFocus) buttons[active].focus();
    };
    const restart = () => {
      window.clearInterval(timer);
      if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) timer = window.setInterval(() => activate(active + 1), 12000);
    };
    buttons.forEach((button, index) => {
      button.addEventListener("click", () => { activate(index); restart(); });
      button.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1 : active + (event.key === "ArrowRight" ? 1 : -1);
        activate(next, true);
        restart();
      });
    });
    activate(active);
    restart();
  }

  function extendNewsRail() {
    const track = document.querySelector(".news-track");
    const set = track?.querySelector(".news-set");
    if (!track || !set || track.children.length > 1) return;
    const clone = set.cloneNode(true);
    clone.setAttribute("aria-hidden", "true");
    clone.querySelectorAll("a").forEach((link) => link.tabIndex = -1);
    track.appendChild(clone);
  }

  function setupMotion() {
    document.querySelectorAll(".panel").forEach((panel, index) => {
      panel.style.setProperty("--panel-delay", `${index * 70}ms`);
      panel.addEventListener("pointermove", (event) => {
        const rect = panel.getBoundingClientRect();
        panel.style.setProperty("--pointer-x", `${event.clientX - rect.left}px`);
        panel.style.setProperty("--pointer-y", `${event.clientY - rect.top}px`);
      });
    });
  }

  setupTabs({ attribute: "data-network-view", render: renderNetwork });
  setupTabs({ attribute: "data-business-view", render: renderBusiness });
  setupTabs({ attribute: "data-reach-view", render: renderReach });
  setupTabs({ attribute: "data-finance-view", render: renderFinance });
  extendNewsRail();
  setupMotion();
})();
