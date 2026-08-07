const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const newsRail = document.querySelector(".news-rail");
const newsTrack = document.querySelector(".news-track");
const newsSourceSet = newsTrack?.querySelector(".news-set");
let newsResizeFrame = 0;
let newsResumeTimer = 0;
var benchmarkPayload = null;
const selectedBenchmarkCompanyIds = new Set();
const benchmarkMetricSelections = new Map();
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
  clearBenchmarkCharts();

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
  renderBenchmarkCharts();
}

function stopNetworkRotation() {
  window.clearTimeout(networkRotationTimer);
}

function networkRotationIsPaused() {
  return (
    !networkPanel ||
    networkTabs.length < 2 ||
    selectedBenchmarkCompanyIds.size > 0 ||
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
    renderBenchmarkCharts();
  }

  function paused() {
    return (
      selectedBenchmarkCompanyIds.size > 0 ||
      reducedMotion.matches ||
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

fetch("./strategic-briefs.json", { cache: "no-store" })
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

function visibleDetailMetrics(panel) {
  if (!panel) return [];
  const metrics = [];
  const add = (label, value, unit = "", host = null) => {
    const cleanLabel = String(label || "").trim();
    const cleanValue = String(value || "").trim();
    if (!cleanLabel || !cleanValue || metrics.some((item) => item.label === cleanLabel)) return;
    metrics.push({ label: cleanLabel, value: cleanValue, unit: String(unit || "").trim(), host });
  };

  if (panel.classList.contains("panel-network")) {
    add(
      panel.querySelector("[data-network-label='hero']")?.textContent,
      panel.querySelector(".hero-metric strong")?.textContent,
      "",
      panel.querySelector(".hero-metric")
    );
    panel.querySelectorAll(".network-bars > div:not([hidden])").forEach((item) => {
      add(item.querySelector("span")?.textContent, item.querySelector("b")?.textContent, "", item);
    });
    return metrics.slice(0, 5);
  }

  panel.querySelectorAll(".detail-item:not([hidden])").forEach((item) => {
    const label = item.querySelector("span")?.textContent;
    const valueNode = item.querySelector("[data-business-metric-value], [data-reach-metric-value], [data-finance-metric-value]");
    const unitNode = item.querySelector("[data-business-metric-unit], [data-reach-metric-unit], [data-finance-metric-unit]");
    add(label, valueNode?.textContent, unitNode?.textContent, item);
  });

  if (panel.classList.contains("panel-finance")) {
    const activeView = panel.querySelector("#finance-detail")?.dataset.activeView;
    if (activeView === "income") {
      metrics.unshift({ label: "营运收入", value: panel.querySelector("[data-key='cmhkRevenue']")?.textContent || "", unit: "亿港元", host: panel.querySelector(".revenue-block") });
    } else if (activeView === "margin") {
      metrics.unshift(
        { label: "EBITDA率", value: panel.querySelector("[data-key='ebitdaMargin']")?.textContent || "", unit: "%", host: panel.querySelector("[data-key='ebitdaMargin']")?.closest("div") },
        { label: "EBITDA", value: panel.querySelector("[data-key='ebitda']")?.textContent || "", unit: "亿港元", host: panel.querySelector("[data-key='ebitda']")?.closest("div") },
        { label: "净利润", value: panel.querySelector("[data-key='netProfit']")?.textContent || "", unit: "亿港元", host: panel.querySelector("[data-key='netProfit']")?.closest("div") }
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
  return null;
}

function formatBenchmarkValue(value) {
  const numeric = Number(String(value).replace(/,/g, ""));
  if (!Number.isFinite(numeric)) return String(value || "—");
  return new Intl.NumberFormat("zh-HK", { maximumFractionDigits: 2 }).format(numeric);
}

function benchmarkNumericValue(record) {
  const match = String(record?.value ?? "").replace(/,/g, "").match(/-?\d+(?:\.\d+)?/);
  if (!match) return null;
  const value = Number(match[0]);
  return Number.isFinite(value) ? value : null;
}

function benchmarkMetricUnit(value, explicitUnit = "") {
  if (explicitUnit) return explicitUnit;
  const text = String(value || "");
  const numeric = text.match(/-?\d+(?:\.\d+)?/);
  return numeric ? text.replace(numeric[0], "").trim() : "";
}

function uniqueBenchmarkMetrics(items) {
  const seen = new Set();
  return items.filter((item) => {
    if (!item?.label || benchmarkNumericValue({ value: item.value }) === null || seen.has(item.label)) return false;
    seen.add(item.label);
    item.unit = benchmarkMetricUnit(item.value, item.unit);
    return true;
  });
}

function benchmarkMetricCatalog(panelIndex) {
  if (panelIndex === 3 && benchmarkPayload?.metrics && benchmarkPayload?.values?.cmhk) {
    return Object.entries(benchmarkPayload.metrics).map(([metricId, definition]) => ({
      id: metricId,
      label: definition.label,
      value: benchmarkPayload.values.cmhk[metricId]?.value,
      unit: definition.unit
    }));
  }

  if (panelIndex === 0) {
    const items = [];
    Object.values(networkViews).forEach((view) => {
      items.push({ label: view.hero?.[0], value: view.hero?.[1], unit: benchmarkMetricUnit(view.hero?.[1]) });
      [...(view.bars || []), ...(view.extras || []), ...(view.pair || [])].forEach(([label, value, unit]) => {
        items.push({ label, value, unit });
      });
    });
    return uniqueBenchmarkMetrics(items);
  }

  const sourceViews = panelIndex === 1 ? businessViews : panelIndex === 2 ? reachViews : financeViews;
  const items = [];
  Object.values(sourceViews).forEach((view) => {
    (view.groups || []).forEach((group) => {
      (group.metrics || []).forEach(([label, value, unit]) => items.push({ label, value, unit }));
    });
  });
  if (panelIndex === 2) {
    items.unshift(
      { label: "品牌认知度", value: "91.6", unit: "%" },
      { label: "品牌综合指数", value: "88.7", unit: "分" }
    );
  }
  return uniqueBenchmarkMetrics(items);
}

function benchmarkChartKind(panelIndex, metric) {
  const descriptor = `${metric.label}${metric.unit}`;
  if (/%|率|覆盖|满意|认知|指数|份额|时效/.test(descriptor)) return "lollipop";
  if (panelIndex === 3) return "columns";
  return "bars";
}

function clearBenchmarkCharts() {
  document.querySelectorAll(".benchmark-native-chart, .benchmark-panel-company").forEach((item) => item.remove());
  document.querySelectorAll(".has-benchmark-native-chart").forEach((target) => {
    target.classList.remove("has-benchmark-native-chart");
    if (target.dataset.benchmarkWasHidden === "true") target.hidden = true;
    delete target.dataset.benchmarkWasHidden;
  });
  document.body.removeAttribute("data-benchmark-companies");
}

function benchmarkComparisonNote(records) {
  const missing = records.filter(({ companyId, record }) => (
    companyId !== "cmhk" && benchmarkNumericValue(record) === null
  ));
  if (missing.length) {
    const labels = missing.map(({ company }) => company?.label).filter(Boolean).join("、");
    return `${labels}暂无同口径披露`;
  }
  return "最新可核验披露 · 各公司期间可能不同";
}

function closeBenchmarkMetricMenus(except = null) {
  document.querySelectorAll(".benchmark-metric-picker.is-open").forEach((picker) => {
    if (picker === except) return;
    picker.classList.remove("is-open");
    picker.querySelector(".benchmark-metric-trigger")?.setAttribute("aria-expanded", "false");
  });
}

function createBenchmarkMetricPicker(panelIndex, catalog, metric, headingText) {
  const picker = document.createElement("div");
  picker.className = "benchmark-metric-picker";

  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "benchmark-metric-trigger";
  trigger.setAttribute("aria-label", `选择${headingText}比较指标，当前为${metric.label}`);
  trigger.setAttribute("aria-haspopup", "listbox");
  trigger.setAttribute("aria-expanded", "false");

  const current = document.createElement("span");
  current.className = "benchmark-metric-current";
  current.textContent = metric.label;
  const chevron = document.createElement("i");
  chevron.setAttribute("aria-hidden", "true");
  trigger.append(chevron);

  const menu = document.createElement("div");
  menu.className = "benchmark-metric-menu";
  menu.setAttribute("role", "listbox");
  menu.setAttribute("aria-label", `${headingText}可比较指标`);

  catalog.forEach((item) => {
    const option = document.createElement("button");
    option.type = "button";
    option.className = "benchmark-metric-option";
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(item.label === metric.label));
    option.textContent = item.label;
    option.addEventListener("click", () => {
      benchmarkMetricSelections.set(panelIndex, item.label);
      closeBenchmarkMetricMenus();
      renderBenchmarkCharts();
      window.requestAnimationFrame(() => {
        document.querySelectorAll(".benchmark-metric-trigger")[panelIndex]?.focus();
      });
    });
    menu.append(option);
  });

  trigger.addEventListener("click", () => {
    const willOpen = !picker.classList.contains("is-open");
    closeBenchmarkMetricMenus(picker);
    picker.classList.toggle("is-open", willOpen);
    trigger.setAttribute("aria-expanded", String(willOpen));
    if (willOpen) {
      window.requestAnimationFrame(() => {
        menu.querySelector('[aria-selected="true"]')?.focus();
      });
    }
  });
  picker.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeBenchmarkMetricMenus();
      trigger.focus();
      return;
    }
    if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
    const options = [...menu.querySelectorAll(".benchmark-metric-option")];
    const currentIndex = options.indexOf(document.activeElement);
    const direction = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = currentIndex < 0 ? 0 : (currentIndex + direction + options.length) % options.length;
    event.preventDefault();
    options[nextIndex]?.focus();
  });

  picker.append(current, trigger, menu);
  return picker;
}

document.addEventListener("pointerdown", (event) => {
  if (!event.target.closest(".benchmark-metric-picker")) closeBenchmarkMetricMenus();
});

function renderBenchmarkCharts() {
  clearBenchmarkCharts();
  if (!benchmarkPayload || !selectedBenchmarkCompanyIds.size) return;

  const companyIds = ["cmhk", ...selectedBenchmarkCompanyIds];
  document.body.dataset.benchmarkCompanies = companyIds.join(",");

  const targetSelectors = ["#network-detail", ".business-content", ".reach-content", ".finance-content"];
  panels.forEach((panel, panelIndex) => {
    const catalog = benchmarkMetricCatalog(panelIndex);
    const selectedLabel = benchmarkMetricSelections.get(panelIndex);
    const metric = catalog.find((item) => item.label === selectedLabel) || catalog.at(0);
    const target = panel.querySelector(targetSelectors[panelIndex]);
    if (!metric || !target) return;

    const heading = panel.querySelector(".panel-heading h2");
    if (heading) {
      const badge = document.createElement("span");
      badge.className = "benchmark-panel-company";
      const comparedCompanies = companyIds.map(companyLabel).join(" · ");
      badge.textContent = comparedCompanies;
      badge.title = `当前对比：${comparedCompanies}`;
      badge.setAttribute("aria-label", `当前对比公司：${comparedCompanies}`);
      heading.after(badge);
    }

    const chart = document.createElement("section");
    chart.className = `benchmark-native-chart benchmark-panel-view is-${benchmarkChartKind(panelIndex, metric)}`;
    chart.style.setProperty("--benchmark-company-count", String(companyIds.length));
    chart.setAttribute("aria-label", `${heading?.textContent || "当前板块"}多企业指标对比`);

    const records = companyIds.map((companyId) => ({
      companyId,
      company: benchmarkPayload.companies.find((item) => item.id === companyId),
      record: benchmarkRecord(companyId, metric)
    }));
    const maximum = Math.max(1, ...records.map(({ record }) => Math.abs(benchmarkNumericValue(record) || 0)));
    const filter = document.createElement("label");
    filter.className = "benchmark-metric-filter";
    const filterText = document.createElement("span");
    filterText.textContent = "指标";
    const picker = createBenchmarkMetricPicker(panelIndex, catalog, metric, heading?.textContent || "当前板块");
    const unit = document.createElement("small");
    unit.textContent = records.find(({ record }) => record?.unit)?.record?.unit || metric.unit || "";
    filter.append(filterText, picker, unit);
    chart.append(filter);

    records.forEach(({ companyId, company, record }) => {
      const numericValue = benchmarkNumericValue(record);
      const row = document.createElement("div");
      row.className = "benchmark-chart-row";
      row.dataset.company = companyId;
      row.classList.toggle("is-missing", numericValue === null);
      row.title = [record?.period, record?.period_end, record?.source_label].filter(Boolean).join(" · ");
      const label = document.createElement("span");
      label.textContent = company?.label || companyId;
      const track = document.createElement("i");
      const bar = document.createElement("b");
      const percentage = numericValue === null ? 0 : Math.max(3, Math.abs(numericValue) / maximum * 100);
      bar.style.setProperty("--benchmark-value", `${percentage}%`);
      bar.style.setProperty("--benchmark-height", `${percentage}%`);
      track.append(bar);
      const value = document.createElement("strong");
      value.textContent = numericValue === null ? "暂无" : formatBenchmarkValue(record.value);
      row.append(label, track, value);
      chart.append(row);
    });

    const note = document.createElement("p");
    note.className = "benchmark-comparison-note";
    note.textContent = benchmarkComparisonNote(records);
    chart.append(note);

    target.dataset.benchmarkWasHidden = String(target.hidden);
    target.hidden = false;
    target.classList.add("has-benchmark-native-chart");
    target.append(chart);
  });
}

function renderBenchmarkCompanySelector() {
  if (!benchmarkCompanySelector || !benchmarkPayload) return;
  const fragment = document.createDocumentFragment();
  benchmarkPayload.companies.forEach((company) => {
    const button = document.createElement("button");
    const selected = company.id === "cmhk"
      ? selectedBenchmarkCompanyIds.size === 0
      : selectedBenchmarkCompanyIds.has(company.id);
    button.type = "button";
    button.dataset.company = company.id;
    button.className = selected ? "is-selected" : "";
    button.setAttribute("aria-pressed", String(selected));
    button.textContent = company.label;
    button.classList.toggle("is-primary", company.id === "cmhk");
    button.title = company.id === "cmhk" ? "清除竞对并恢复CMHK原始视图" : `在原图表中${selected ? "移除" : "加入"}${company.label}`;
    button.addEventListener("click", () => {
      if (company.id === "cmhk") selectedBenchmarkCompanyIds.clear();
      else if (selectedBenchmarkCompanyIds.has(company.id)) selectedBenchmarkCompanyIds.delete(company.id);
      else selectedBenchmarkCompanyIds.add(company.id);
      renderBenchmarkCompanySelector();
      syncBenchmarkRotationState();
      renderBenchmarkCharts();
    });
    fragment.append(button);
  });
  benchmarkCompanySelector.replaceChildren(fragment);
  if (benchmarkCount) benchmarkCount.textContent = selectedBenchmarkCompanyIds.size
    ? `已选 ${selectedBenchmarkCompanyIds.size} 家竞对`
    : "原始视图";
}

function companyLabel(companyId) {
  return benchmarkPayload?.companies?.find((item) => item.id === companyId)?.label || companyId;
}

function syncBenchmarkRotationState() {
  const rotators = [businessRotator, reachRotator, financeRotator];
  if (selectedBenchmarkCompanyIds.size) {
    stopNetworkRotation();
    rotators.forEach((rotator) => rotator?.stop());
    return;
  }
  scheduleNetworkRotation();
  rotators.forEach((rotator) => rotator?.schedule());
}

fetch(document.body.dataset.benchmarkUrl || "/api/executive-company-benchmarks", { cache: "no-store" })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then((payload) => {
    if (!payload.ok || !Array.isArray(payload.companies)) throw new Error(payload.error || "对标数据不可用");
    benchmarkPayload = payload;
    document.body.classList.add("benchmark-data-ready");
    renderBenchmarkCompanySelector();
    renderBenchmarkCharts();
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
