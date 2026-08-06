const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const newsRail = document.querySelector(".news-rail");
const newsTrack = document.querySelector(".news-track");
const newsSourceSet = newsTrack?.querySelector(".news-set");
let newsResizeFrame = 0;
let newsResumeTimer = 0;
var benchmarkPayload = null;
var selectedBenchmarkCompanies = new Set(["cmhk", "hkt", "three", "smartone", "hkbn"]);
const networkPanel = document.querySelector(".panel-network");
const networkContent = document.querySelector("#network-detail");
const networkTabs = [...document.querySelectorAll("[data-network-view]")];
const NETWORK_ROTATE_DELAY = 9000;
const NETWORK_INITIAL_OFFSET = 0;
const BUSINESS_INITIAL_OFFSET = 900;
const REACH_INITIAL_OFFSET = 1800;
const FINANCE_INITIAL_OFFSET = 2700;
let networkRotationTimer = 0;

function restartContentSwitch(content, switchKey) {
  if (!content || content.dataset.switchKey === switchKey) return;
  content.dataset.switchKey = switchKey;
  content.classList.remove("is-switching");
  void content.offsetWidth;
  content.classList.add("is-switching");
}

const networkViews = {
  fixed: {
    hero: ["住宅覆盖户数", "245万户", "+6.7%"],
    chartLabel: "固定网络覆盖指标",
    bars: [["住宅覆盖户数", "245万户", "100%"], ["商业楼宇及设施覆盖数", "12,800栋", "82%"], ["", "", "0%"], ["", "", "0%"]],
    extras: [["", "", ""], ["", "", ""], ["", "", ""]],
    pair: [["", "", ""], ["", "", ""]]
  },
  mobile: {
    hero: ["5G基站总数", "3,700", "+8.4%"],
    chartLabel: "移动网络覆盖与速率指标",
    bars: [["4G基站总数", "6,880", "100%"], ["5G基站总数", "3,700", "82%"], ["5G平均下载速率", "1.1Gbps", "68%"], ["4G MR覆盖率", "99.2%", "96%"]],
    extras: [["5G MR覆盖率", "98.8", "%"], ["3.3-4.9GHz持牌带宽", "140", "MHz"], ["700-900MHz低频带宽", "50", "MHz"]],
    pair: [["26/28GHz高频带宽", "1,200", "MHz"], ["", "", ""]]
  },
  cloud: {
    hero: ["自有数据中心数", "6", "+1"],
    chartLabel: "数据中心与云基础设施指标",
    bars: [["总建筑面积", "32.8万㎡", "100%"], ["智算能力PFLOPS", "4,860", "79%"], ["机柜上架率", "78%", "78%"], ["单机柜ARPU", "$2,980", "64%"]],
    extras: [["总可用电力容量", "108", "MW"], ["PUE", "1.28", ""], ["", "", ""]],
    pair: [["", "", ""], ["", "", ""]]
  },
  research: {
    hero: ["专利数量", "486", "+12.4%"],
    chartLabel: "研发能力指标",
    bars: [["", "", "0%"], ["", "", "0%"], ["", "", "0%"], ["", "", "0%"]],
    extras: [["", "", ""], ["", "", ""], ["", "", ""]],
    pair: [["", "", ""], ["", "", ""]]
  }
};

function showNetworkView(viewName) {
  const view = networkViews[viewName];
  if (!view || !networkContent) return;

  networkTabs.forEach((tab) => {
    const active = tab.dataset.networkView === viewName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });

  networkContent.querySelector("[data-network-label='hero']").textContent = view.hero[0];
  networkContent.querySelector(".hero-metric strong").textContent = view.hero[1];
  networkContent.querySelector(".hero-metric em").textContent = view.hero[2];

  const chart = networkContent.querySelector("[data-network-label='chart']");
  chart.setAttribute("aria-label", view.chartLabel);
  [...chart.children].forEach((bar, index) => {
    const [label = "", value = "", width = "0%"] = view.bars[index] || [];
    bar.hidden = !label;
    bar.querySelector("[data-network-bar-label]").textContent = label;
    bar.querySelector("i").style.setProperty("--value", width);
    bar.querySelector("b").textContent = value;
  });
  chart.hidden = ![...chart.children].some((bar) => !bar.hidden);

  const extraLabels = networkContent.querySelectorAll("[data-network-extra-label]");
  const extraValues = networkContent.querySelectorAll("[data-network-extra-value]");
  const extraUnits = networkContent.querySelectorAll("[data-network-extra-unit]");
  extraLabels.forEach((labelNode, index) => {
    const [label = "", value = "", unit = ""] = view.extras[index] || [];
    labelNode.parentElement.hidden = !label;
    extraLabels[index].textContent = label;
    extraValues[index].textContent = value;
    extraUnits[index].textContent = unit;
  });
  const networkExtra = networkContent.querySelector(".network-extra");
  if (networkExtra) networkExtra.hidden = ![...networkExtra.children].some((child) => !child.hidden);

  const pairLabels = networkContent.querySelectorAll("[data-network-pair-label]");
  const pairValues = networkContent.querySelectorAll("[data-network-pair-value]");
  const pairUnits = networkContent.querySelectorAll("[data-network-pair-unit]");
  pairLabels.forEach((labelNode, index) => {
    const [label = "", value = "", unit = ""] = view.pair[index] || [];
    labelNode.parentElement.hidden = !label;
    pairLabels[index].textContent = label;
    pairValues[index].textContent = value;
    pairUnits[index].textContent = unit;
  });
  const networkPair = networkContent.querySelector(".metric-pair");
  if (networkPair) networkPair.hidden = ![...networkPair.children].some((child) => !child.hidden);

  if (networkPanel) networkPanel.dataset.networkView = viewName;
  restartContentSwitch(networkContent, viewName);
  renderBenchmarkOverlays();
}

function stopNetworkRotation() {
  window.clearTimeout(networkRotationTimer);
}

function networkRotationIsPaused() {
  return (
    !networkPanel ||
    networkTabs.length < 2 ||
    document.body.classList.contains("benchmark-mode") ||
    reducedMotion.matches ||
    document.hidden ||
    networkPanel.matches(":hover") ||
    networkPanel.contains(document.activeElement)
  );
}

function scheduleNetworkRotation(delay = NETWORK_ROTATE_DELAY) {
  stopNetworkRotation();
  if (networkRotationIsPaused()) return;

  networkRotationTimer = window.setTimeout(() => {
    if (networkRotationIsPaused()) return;
    const current = networkTabs.findIndex((tab) => tab.classList.contains("is-active"));
    const next = networkTabs[(current + 1 + networkTabs.length) % networkTabs.length];
    showNetworkView(next.dataset.networkView);
    scheduleNetworkRotation();
  }, delay);
}

networkTabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    showNetworkView(tab.dataset.networkView);
    scheduleNetworkRotation();
  });
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const current = networkTabs.indexOf(tab);
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const next = networkTabs[(current + direction + networkTabs.length) % networkTabs.length];
    next.focus();
    showNetworkView(next.dataset.networkView);
  });
});

networkPanel?.addEventListener("pointerenter", stopNetworkRotation);
networkPanel?.addEventListener("pointerleave", scheduleNetworkRotation);
networkPanel?.addEventListener("focusin", stopNetworkRotation);
networkPanel?.addEventListener("focusout", () => {
  window.setTimeout(scheduleNetworkRotation, 0);
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) stopNetworkRotation();
  else scheduleNetworkRotation();
});
reducedMotion.addEventListener("change", scheduleNetworkRotation);
showNetworkView("mobile");
scheduleNetworkRotation(NETWORK_ROTATE_DELAY + NETWORK_INITIAL_OFFSET);

const businessViews = {
  toc: {
    label: "TOC · 用户结构",
    groups: [
      { label: "TOC · 用户结构", metrics: [["后付用户", "218.4", "万"], ["预付用户", "124.4", "万"], ["5G后付用户", "128.6", "万"]] },
      { label: "TOC · 携号与净增", metrics: [["携号转入", "8.6", "万"], ["携号转出", "6.9", "万"], ["净增", "1.7", "万"]] },
      { label: "TOC · ARPU", metrics: [["移动综合ARPU", "138.6", "$"], ["后付ARPU", "166.8", "$"], ["预付ARPU", "46.2", "$"]] },
      { label: "TOC · 使用与份额", metrics: [["后付DOU", "28.6", "GB"], ["流量份额", "31.8", "%"], ["月度离网率", "1.12", "%"]] },
      { label: "TOC · 服务体验", metrics: [["月度投诉量", "2,480", "宗"], ["投诉处理时效", "6.2", "小时"], ["总移动用户", "342.8", "万"]] }
    ]
  },
  toh: {
    label: "TOH · 家庭宽带",
    groups: [
      { label: "TOH · 用户与端口", metrics: [["家庭宽带用户", "86.4", "万"], ["端口数", "128.6", "万"], ["离网率", "0.86", "%"]] },
      { label: "TOH · 家庭价值", metrics: [["家庭ARPU", "198.2", "$"], ["家庭宽带用户", "86.4", "万"], ["端口数", "128.6", "万"]] }
    ]
  },
  tob: {
    label: "TOB · 企业增长",
    groups: [
      { label: "TOB · 客户与项目", metrics: [["客户数", "38.2", "万"], ["项目签约额", "18.6", "亿"], ["应收账款占收比", "12.4", "%"]] },
      { label: "TOB · 云网收入", metrics: [["连接收入", "21.8", "亿"], ["云应用收入", "13.6", "亿"], ["算力收入", "9.4", "亿"]] },
      { label: "TOB · 生态收入", metrics: [["生态合作收入", "6.8", "亿"], ["ICT收入", "17.2", "亿"], ["5G专网收入", "4.6", "亿"]] }
    ]
  }
};

const reachViews = {
  brand: {
    groups: [{ label: "品牌触达", metrics: [["品牌认知度", "91.6", "%"], ["品牌满意度", "89.2", "%"], ["转台考虑品牌", "CMHK", "首选"]] }]
  },
  channel: {
    groups: [
      { label: "渠道触达 · 实体渠道", metrics: [["全港实体门市数量", "138", "间"], ["直销+街霸数量", "620", "人"], ["渠道销售收入占比", "28.6", "%"]] },
      { label: "渠道触达 · 数字渠道", metrics: [["官方社交媒体覆盖平台", "8", "个平台"], ["官方网站活跃用户数", "96.8", "万"], ["官方手机应用活跃用户数", "218", "万"]] }
    ]
  }
};

const financeViews = {
  income: {
    groups: [{ label: "收入结构", metrics: [["主营移动收入", "61.4", "亿"], ["主营全业务收入", "84.2", "亿"], ["手机及附件销售收入", "12.6", "亿"]] }]
  },
  margin: {
    groups: [{ label: "盈利能力", metrics: [["手机及附件毛利率", "8.6", "%"], ["净利润率", "12.8", "%"], ["运营成本含折旧摊销", "61.5", "亿"], ["运营成本不含折旧摊销", "44.8", "亿"]] }]
  },
  cost: {
    groups: [{ label: "成本与投入", metrics: [["折旧摊销", "16.7", "亿"], ["手机及附件销售成本", "11.5", "亿"], ["资本支出", "18.9", "亿"], ["频谱牌照费", "4.2", "亿"]] }]
  },
  investment: {
    groups: [{ label: "资本开支与投资", metrics: [["资本支出", "18.9", "亿"], ["频谱牌照费", "4.2", "亿"], ["总资产收益率", "6.8", "%"], ["广义固定资产收益率", "9.4", "%"]] }]
  },
  cash: {
    groups: [{ label: "现金流", metrics: [["自由现金流", "16.2", "亿"], ["现金及现金等值", "42.8", "亿"]] }]
  }
};

function createMetricRotator({ panel, tabs, content, views, getGroups, prefix, initialOffset = 0 }) {
  if (!panel || !content || !tabs.length) return null;

  let timer = 0;
  let activeViewIndex = 0;
  let activeGroupIndex = 0;

  const viewNames = tabs.map((tab) => tab.dataset[`${prefix}View`]);
  const metricLabels = [...content.querySelectorAll(`[data-${prefix}-metric-label]`)];
  const metricValues = [...content.querySelectorAll(`[data-${prefix}-metric-value]`)];
  const metricUnits = [...content.querySelectorAll(`[data-${prefix}-metric-unit]`)];

  function currentGroups() {
    const viewName = viewNames[activeViewIndex];
    return getGroups(views[viewName]) || [];
  }

  function apply(viewIndex, groupIndex = 0) {
    activeViewIndex = (viewIndex + viewNames.length) % viewNames.length;
    const groups = currentGroups();
    activeGroupIndex = groups.length ? (groupIndex + groups.length) % groups.length : 0;
    const group = groups[activeGroupIndex] || { label: "", metrics: [] };

    tabs.forEach((tab, index) => {
      const active = index === activeViewIndex;
      tab.classList.toggle("is-active", active);
      tab.setAttribute("aria-selected", String(active));
    });

    const label = content.querySelector(`[data-${prefix}-detail-label]`);
    const index = content.querySelector(`[data-${prefix}-detail-index]`);
    if (label) label.textContent = group.label || "";
    if (index) index.textContent = `${activeGroupIndex + 1} / ${Math.max(groups.length, 1)}`;

    metricLabels.forEach((labelNode, metricIndex) => {
      const metric = group.metrics[metricIndex];
      const item = labelNode.closest(".detail-item");
      if (item) item.hidden = !metric;
      labelNode.textContent = metric?.[0] || "";
      if (metricValues[metricIndex]) {
        const valueNode = metricValues[metricIndex];
        if (valueNode.tagName === "I") valueNode.textContent = metric?.[1] || "";
        else valueNode.textContent = metric?.[1] || "";
      }
      if (metricUnits[metricIndex]) metricUnits[metricIndex].textContent = metric?.[2] || "";
    });

    content.dataset.activeView = viewNames[activeViewIndex] || "";
    content.dataset.activeGroup = String(activeGroupIndex);
    restartContentSwitch(content, `${content.dataset.activeView}:${content.dataset.activeGroup}`);
    renderBenchmarkOverlays();
  }

  function paused() {
    return (
      reducedMotion.matches ||
      document.body.classList.contains("benchmark-mode") ||
      document.hidden ||
      panel.matches(":hover") ||
      panel.contains(document.activeElement)
    );
  }

  function stop() { window.clearTimeout(timer); }

  function schedule(delay = NETWORK_ROTATE_DELAY) {
    stop();
    if (paused()) return;
    timer = window.setTimeout(() => {
      if (paused()) return;
      const groups = currentGroups();
      if (groups.length > 1 && activeGroupIndex < groups.length - 1) {
        apply(activeViewIndex, activeGroupIndex + 1);
      } else {
        apply((activeViewIndex + 1) % viewNames.length, 0);
      }
      schedule();
    }, delay);
  }

  tabs.forEach((tab, tabIndex) => {
    tab.addEventListener("click", () => {
      apply(tabIndex, 0);
      schedule();
    });
    tab.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
      event.preventDefault();
      const direction = event.key === "ArrowRight" ? 1 : -1;
      const nextIndex = (tabIndex + direction + tabs.length) % tabs.length;
      tabs[nextIndex].focus();
      apply(nextIndex, 0);
    });
  });

  panel.addEventListener("pointerenter", stop);
  panel.addEventListener("pointerleave", schedule);
  panel.addEventListener("focusin", stop);
  panel.addEventListener("focusout", () => window.setTimeout(schedule, 0));
  apply(0, 0);
  schedule(NETWORK_ROTATE_DELAY + initialOffset);
  return { apply, schedule, stop };
}

const businessRotator = createMetricRotator({
  panel: document.querySelector(".panel-business"),
  tabs: [...document.querySelectorAll("[data-business-view]")],
  content: document.querySelector("#business-detail"),
  views: businessViews,
  getGroups: (view) => view?.groups,
  prefix: "business",
  initialOffset: BUSINESS_INITIAL_OFFSET
});

const reachRotator = createMetricRotator({
  panel: document.querySelector(".panel-reach"),
  tabs: [...document.querySelectorAll("[data-reach-view]")],
  content: document.querySelector("#reach-detail"),
  views: reachViews,
  getGroups: (view) => view?.groups,
  prefix: "reach",
  initialOffset: REACH_INITIAL_OFFSET
});

const financeRotator = createMetricRotator({
  panel: document.querySelector(".panel-finance"),
  tabs: [...document.querySelectorAll("[data-finance-view]")],
  content: document.querySelector("#finance-detail"),
  views: financeViews,
  getGroups: (view) => view?.groups,
  prefix: "finance",
  initialOffset: FINANCE_INITIAL_OFFSET
});

document.addEventListener("visibilitychange", () => {
  [businessRotator, reachRotator, financeRotator].forEach((rotator) => {
    if (!rotator) return;
    if (document.hidden) rotator.stop();
    else rotator.schedule();
  });
});
reducedMotion.addEventListener("change", () => {
  [businessRotator, reachRotator, financeRotator].forEach((rotator) => rotator?.schedule());
});

function rebuildNewsRail() {
  if (!newsTrack || !newsSourceSet) return;

  newsTrack.querySelectorAll("[data-news-clone]").forEach((clone) => clone.remove());
  const newsSetWidth = newsSourceSet.getBoundingClientRect().width;
  if (!newsSetWidth) return;

  const requiredSets = Math.ceil(window.innerWidth / newsSetWidth) + 2;
  for (let index = 1; index < requiredSets; index += 1) {
    const clone = newsSourceSet.cloneNode(true);
    clone.dataset.newsClone = "";
    clone.setAttribute("aria-hidden", "true");
    clone.querySelectorAll("a").forEach((link) => {
      link.tabIndex = -1;
    });
    newsTrack.append(clone);
  }

  newsTrack.style.setProperty("--news-loop-width", `${newsSetWidth}px`);
  newsTrack.style.setProperty("--news-duration", `${newsSetWidth / 42}s`);
}

rebuildNewsRail();

function formatNewsDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    timeZone: "Asia/Hong_Kong"
  }).format(date);
}

function renderNewsRail(items) {
  if (!newsSourceSet || !Array.isArray(items)) return;
  const usableItems = items.filter((item) => item?.title && item?.source_url).slice(0, 8);
  if (!usableItems.length) return;

  const fragment = document.createDocumentFragment();
  usableItems.forEach((item) => {
    const link = document.createElement("a");
    link.className = "news-item";
    link.href = item.source_url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.setAttribute("aria-label", `${item.title}，打开新闻来源`);

    const meta = document.createElement("div");
    const time = document.createElement("time");
    time.dateTime = item.published_at || "";
    time.textContent = formatNewsDate(item.published_at);
    const category = document.createElement("span");
    category.textContent = item.category || "行业动态";
    meta.append(time, category);

    const title = document.createElement("h3");
    title.textContent = item.title;
    const summary = document.createElement("p");
    summary.textContent = item.summary || "";
    link.append(meta, title, summary);
    fragment.append(link);
  });

  newsSourceSet.replaceChildren(fragment);
  rebuildNewsRail();
}

fetch("/api/strategic-briefs", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((payload) => renderNewsRail(payload.items))
  .catch(() => {});

const benchmarkToggle = document.querySelector("#benchmarkToggle");
const benchmarkCount = document.querySelector("#benchmarkCount");
const benchmarkCompanySelector = document.querySelector("#benchmarkCompanySelector");
const BENCHMARK_METRIC_IDS = {
  "营运收入": "revenue",
  "EBITDA": "ebitda",
  "EBITDA率": "ebitda_margin",
  "净利润": "net_profit",
  "净利润率": "net_margin",
  "资本支出": "capital_expenditure",
  "现金及现金等值": "cash",
  "自由现金流": "free_cash_flow"
};
const BENCHMARK_SIMULATION_BASE = { hkt: 1.08, three: .82, smartone: .76, hkbn: .69 };

function visibleDetailMetrics(panel) {
  if (!panel) return [];
  const metrics = [];
  const add = (label, value, unit = "") => {
    const cleanLabel = String(label || "").trim();
    const cleanValue = String(value || "").trim();
    if (!cleanLabel || !cleanValue || metrics.some((item) => item.label === cleanLabel)) return;
    metrics.push({ label: cleanLabel, value: cleanValue, unit: String(unit || "").trim() });
  };

  if (panel.classList.contains("panel-network")) {
    add(
      panel.querySelector("[data-network-label='hero']")?.textContent,
      panel.querySelector(".hero-metric strong")?.textContent,
      ""
    );
    panel.querySelectorAll(".network-bars > div:not([hidden])").forEach((item) => {
      add(item.querySelector("span")?.textContent, item.querySelector("b")?.textContent, "");
    });
    return metrics.slice(0, 5);
  }

  panel.querySelectorAll(".detail-item:not([hidden])").forEach((item) => {
    const label = item.querySelector("span")?.textContent;
    const valueNode = item.querySelector("[data-business-metric-value], [data-reach-metric-value], [data-finance-metric-value]");
    const unitNode = item.querySelector("[data-business-metric-unit], [data-reach-metric-unit], [data-finance-metric-unit]");
    add(label, valueNode?.textContent, unitNode?.textContent);
  });

  if (panel.classList.contains("panel-finance")) {
    const activeView = panel.querySelector("#finance-detail")?.dataset.activeView;
    if (activeView === "income") {
      metrics.unshift({ label: "营运收入", value: panel.querySelector("[data-key='cmhkRevenue']")?.textContent || "", unit: "亿港元" });
    } else if (activeView === "margin") {
      metrics.unshift(
        { label: "EBITDA率", value: panel.querySelector("[data-key='ebitdaMargin']")?.textContent || "", unit: "%" },
        { label: "EBITDA", value: panel.querySelector("[data-key='ebitda']")?.textContent || "", unit: "亿港元" },
        { label: "净利润", value: panel.querySelector("[data-key='netProfit']")?.textContent || "", unit: "亿港元" }
      );
    }
  }
  return metrics.filter((item) => item.value).slice(0, 5);
}

function benchmarkRecord(companyId, metric) {
  if (companyId === "cmhk") {
    return { value: metric.value, unit: metric.unit, period: "驾驶舱当前口径", source_url: "" };
  }
  const metricId = BENCHMARK_METRIC_IDS[metric.label];
  const record = metricId ? benchmarkPayload?.values?.[companyId]?.[metricId] : null;
  if (record) {
    return {
      ...record,
      unit: benchmarkPayload?.metrics?.[metricId]?.unit || metric.unit,
      simulated: false
    };
  }
  return simulatedBenchmarkRecord(companyId, metric);
}

function simulatedBenchmarkRecord(companyId, metric) {
  const company = benchmarkPayload?.companies?.find((item) => item.id === companyId);
  const raw = String(metric.value || "").replace(/,/g, "").trim();
  const numericMatch = raw.match(/-?\d+(?:\.\d+)?/);
  if (!numericMatch) {
    return {
      value: company?.label || "模拟值",
      unit: metric.unit,
      period: "模拟估算",
      source_label: "基于CMHK当前值的界面模拟",
      source_url: "",
      simulated: true
    };
  }
  let hash = 0;
  `${metric.label}:${companyId}`.split("").forEach((character) => {
    hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  });
  const jitter = ((hash % 17) - 8) / 100;
  const ratio = (BENCHMARK_SIMULATION_BASE[companyId] || .72) + jitter;
  const sourceValue = Number(numericMatch[0]);
  let value = sourceValue * ratio;
  const unit = metric.unit || raw.replace(numericMatch[0], "").trim();
  if (unit.includes("%")) value = Math.min(99.9, Math.max(-99.9, value));
  const decimals = Math.abs(sourceValue) >= 100 ? 0 : (Math.abs(sourceValue) >= 10 ? 1 : 2);
  return {
    value: Number(value.toFixed(decimals)),
    unit,
    period: "模拟估算",
    source_label: "基于CMHK当前值与企业规模系数的界面模拟",
    source_url: "",
    simulated: true
  };
}

function formatBenchmarkValue(value) {
  const numeric = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(numeric)) return String(value || "—");
  return new Intl.NumberFormat("zh-HK", { maximumFractionDigits: 2 }).format(numeric);
}

function ensureBenchmarkOverlays() {
  panels.forEach((panel) => {
    if (panel.querySelector(".company-benchmark-overlay")) return;
    const overlay = document.createElement("section");
    overlay.className = "company-benchmark-overlay";
    overlay.setAttribute("aria-label", `${panel.querySelector("h2")?.textContent || "指标"}企业对标`);
    overlay.innerHTML = '<header><div><strong></strong><span></span></div><em></em></header><div class="company-benchmark-table"></div><footer><b>SIM</b> 为基于CMHK当前值的界面模拟，并非企业公开披露；官方值可悬停查看期间与来源。</footer>';
    panel.append(overlay);
  });
}

function renderBenchmarkOverlays() {
  if (!benchmarkPayload) return;
  ensureBenchmarkOverlays();
  const companies = benchmarkPayload.companies.filter((item) => selectedBenchmarkCompanies.has(item.id));

  panels.forEach((panel) => {
    const overlay = panel.querySelector(".company-benchmark-overlay");
    if (!overlay) return;
    const metrics = visibleDetailMetrics(panel);
    const table = overlay.querySelector(".company-benchmark-table");
    const title = panel.querySelector("h2")?.textContent || "指标";
    const tableFragment = document.createDocumentFragment();
    let verifiedPeerCells = 0;
    let simulatedPeerCells = 0;
    let totalPeerCells = 0;

    const heading = document.createElement("div");
    heading.className = "company-benchmark-row company-benchmark-head";
    heading.style.setProperty("--benchmark-companies", String(companies.length));
    const metricHeading = document.createElement("span");
    metricHeading.textContent = "当前指标";
    heading.append(metricHeading);
    companies.forEach((company) => {
      const companyHeading = document.createElement("strong");
      companyHeading.dataset.company = company.id;
      companyHeading.textContent = company.label;
      heading.append(companyHeading);
    });
    tableFragment.append(heading);

    metrics.forEach((metric) => {
      const row = document.createElement("div");
      row.className = "company-benchmark-row";
      row.style.setProperty("--benchmark-companies", String(companies.length));
      const label = document.createElement("span");
      label.textContent = metric.label;
      row.append(label);

      companies.forEach((company) => {
        const record = benchmarkRecord(company.id, metric);
        if (company.id !== "cmhk") {
          totalPeerCells += 1;
          if (record?.simulated) simulatedPeerCells += 1;
          else if (record) verifiedPeerCells += 1;
        }
        const cell = record?.source_url ? document.createElement("a") : document.createElement("strong");
        cell.dataset.company = company.id;
        cell.classList.toggle("is-simulated", Boolean(record?.simulated));
        if (record?.source_url) {
          cell.href = record.source_url;
          cell.target = "_blank";
          cell.rel = "noopener noreferrer";
        }
        cell.title = record
          ? [record.period, record.period_end, record.source_label].filter(Boolean).join(" · ")
          : "暂无同口径公开数据";
        const value = document.createElement("b");
        value.textContent = record ? formatBenchmarkValue(record.value) : "—";
        const unit = document.createElement("small");
        unit.textContent = record ? (record.unit || "") : "";
        cell.append(value, unit);
        if (record?.simulated) {
          const simulationTag = document.createElement("i");
          simulationTag.textContent = "SIM";
          cell.append(simulationTag);
        }
        row.append(cell);
      });
      tableFragment.append(row);
    });

    table.replaceChildren(tableFragment);
    overlay.querySelector("header strong").textContent = `${title} · 企业横向对标`;
    overlay.querySelector("header span").textContent = benchmarkPayload.comparison_basis;
    overlay.querySelector("header em").textContent = totalPeerCells
      ? `真实 ${verifiedPeerCells} · 模拟 ${simulatedPeerCells}`
      : "等待同行数据";
  });
}

function renderBenchmarkCompanySelector() {
  if (!benchmarkCompanySelector || !benchmarkPayload) return;
  const fragment = document.createDocumentFragment();
  benchmarkPayload.companies.forEach((company) => {
    const button = document.createElement("button");
    const selected = selectedBenchmarkCompanies.has(company.id);
    button.type = "button";
    button.dataset.company = company.id;
    button.className = selected ? "is-selected" : "";
    button.setAttribute("aria-pressed", String(selected));
    button.textContent = company.label;
    if (company.id === "cmhk") {
      button.classList.add("is-primary");
      button.setAttribute("aria-disabled", "true");
      button.title = "CMHK固定为主对标企业";
    } else {
      button.addEventListener("click", () => {
        if (selectedBenchmarkCompanies.has(company.id)) {
          if (selectedBenchmarkCompanies.size <= 2) return;
          selectedBenchmarkCompanies.delete(company.id);
        } else {
          selectedBenchmarkCompanies.add(company.id);
        }
        renderBenchmarkCompanySelector();
        renderBenchmarkOverlays();
      });
    }
    fragment.append(button);
  });
  benchmarkCompanySelector.replaceChildren(fragment);
  if (benchmarkCount) benchmarkCount.textContent = `${selectedBenchmarkCompanies.size}家`;
}

benchmarkToggle?.addEventListener("click", () => {
  if (!benchmarkPayload) return;
  const active = !document.body.classList.contains("benchmark-mode");
  document.body.classList.toggle("benchmark-mode", active);
  benchmarkToggle.setAttribute("aria-pressed", String(active));
  benchmarkToggle.querySelector("span").textContent = active ? "返回经营视图" : "企业对标";
  if (active) {
    stopNetworkRotation();
    [businessRotator, reachRotator, financeRotator].forEach((rotator) => rotator?.stop());
    renderBenchmarkOverlays();
  } else {
    scheduleNetworkRotation();
    [businessRotator, reachRotator, financeRotator].forEach((rotator) => rotator?.schedule());
  }
});

if (benchmarkToggle) benchmarkToggle.disabled = true;
fetch(document.body.dataset.benchmarkUrl || "/api/executive-company-benchmarks", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((payload) => {
    if (!payload.ok || !Array.isArray(payload.companies)) throw new Error(payload.error || "对标数据不可用");
    benchmarkPayload = payload;
    document.body.classList.add("benchmark-data-ready");
    if (benchmarkToggle) benchmarkToggle.disabled = false;
    renderBenchmarkCompanySelector();
    renderBenchmarkOverlays();
  })
  .catch(() => {
    if (benchmarkCount) benchmarkCount.textContent = "数据未就绪";
    document.body.classList.add("benchmark-data-error");
  });

function pauseNewsRail() {
  window.clearTimeout(newsResumeTimer);
  if (newsTrack) newsTrack.style.animationPlayState = "paused";
}

function resumeNewsRail(delay = 0) {
  window.clearTimeout(newsResumeTimer);
  newsResumeTimer = window.setTimeout(() => {
    if (newsTrack) newsTrack.style.animationPlayState = "running";
  }, delay);
}

newsRail?.addEventListener("pointerenter", pauseNewsRail);
newsRail?.addEventListener("pointerleave", () => resumeNewsRail(300));
newsRail?.addEventListener("focusin", pauseNewsRail);
newsRail?.addEventListener("focusout", () => resumeNewsRail(300));

window.addEventListener("resize", () => {
  cancelAnimationFrame(newsResizeFrame);
  newsResizeFrame = requestAnimationFrame(rebuildNewsRail);
});

if (!reducedMotion.matches) {
  document.documentElement.classList.add("motion-enabled");

  panels.forEach((panel, index) => {
    panel.style.setProperty("--panel-delay", `${index * 85}ms`);
  });

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14 }
  );

  panels.forEach((panel) => observer.observe(panel));

  if (window.matchMedia("(pointer: fine)").matches) {
    document.addEventListener("pointermove", (event) => {
      const activePanel = event.target.closest?.(".panel") || null;

      panels.forEach((panel) => {
        const isActive = panel === activePanel;
        panel.classList.toggle("is-pointer-active", isActive);
        if (!isActive) return;

        const bounds = panel.getBoundingClientRect();
        panel.style.setProperty("--pointer-x", `${((event.clientX - bounds.left) / bounds.width) * 100}%`);
        panel.style.setProperty("--pointer-y", `${((event.clientY - bounds.top) / bounds.height) * 100}%`);
      });
    });
  }
} else {
  panels.forEach((panel) => panel.classList.add("is-visible"));
}
