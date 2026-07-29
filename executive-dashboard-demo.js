const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const newsRail = document.querySelector(".news-rail");
const newsTrack = document.querySelector(".news-track");
const newsSourceSet = newsTrack?.querySelector(".news-set");
let newsResizeFrame = 0;
let newsResumeTimer = 0;
const networkPanel = document.querySelector(".panel-network");
const networkContent = document.querySelector("#network-detail");
const networkTabs = [...document.querySelectorAll("[data-network-view]")];
const NETWORK_ROTATE_DELAY = 9000;
let networkRotationTimer = 0;

const networkViews = {
  fixed: {
    hero: ["光纤接入端口", "228万", "+6.7%"],
    chartLabel: "核心固定网络资源",
    bars: [["骨干光纤", "18,600 km", "100%"], ["接入机楼", "312 个", "82%"], ["10G PON", "76 万", "74%"], ["国际出口", "9.8 Tbps", "66%"]],
    extras: [["家居覆盖", "245", "万户"], ["专线节点", "168", "个"], ["可用率", "99.999", "%"]],
    pair: [["光纤到楼", "98.6", "%"], ["平均时延", "1.8", "ms"]]
  },
  mobile: {
    hero: ["5G 基站", "3,700", "+8.4%"],
    chartLabel: "各运营商5G基站比较",
    bars: [["CMHK", "1,620", "90%"], ["HKT", "1,810", "100%"], ["3香港", "1,390", "77%"], ["SmarTone", "1,260", "70%"]],
    extras: [["5G 频谱", "140", "MHz"], ["边缘节点", "26", "个"], ["网络可用率", "99.99", "%"]],
    pair: [["人口覆盖", "99.9", "%"], ["智能算力", "1,680", "PFLOPS"]]
  },
  cloud: {
    hero: ["智算资源池", "4,860P", "+21.6%"],
    chartLabel: "数据中心核心能力",
    bars: [["将军澳 DC", "1,680P", "100%"], ["葵涌 DC", "1,320P", "79%"], ["火炭 DC", "1,080P", "64%"], ["边缘节点", "780P", "46%"]],
    extras: [["机架规模", "8,600", "架"], ["绿电使用", "72", "%"], ["PUE", "1.28", ""]],
    pair: [["云节点", "42", "个"], ["存储容量", "26.8", "EB"]]
  },
  research: {
    hero: ["年度研发投入", "18.6亿", "+15.2%"],
    chartLabel: "重点研发方向投入",
    bars: [["AI 与大模型", "6.8亿", "100%"], ["6G 预研", "4.9亿", "72%"], ["云网融合", "4.2亿", "62%"], ["安全技术", "2.7亿", "40%"]],
    extras: [["研发人员", "1,260", "人"], ["有效专利", "486", "项"], ["联合实验室", "12", "个"]],
    pair: [["成果转化", "68", "%"], ["年度新增专利", "92", "项"]]
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
    const [label, value, width] = view.bars[index];
    bar.querySelector("[data-network-bar-label]").textContent = label;
    bar.querySelector("i").style.setProperty("--value", width);
    bar.querySelector("b").textContent = value;
  });

  const extraLabels = networkContent.querySelectorAll("[data-network-extra-label]");
  const extraValues = networkContent.querySelectorAll("[data-network-extra-value]");
  const extraUnits = networkContent.querySelectorAll("[data-network-extra-unit]");
  view.extras.forEach(([label, value, unit], index) => {
    extraLabels[index].textContent = label;
    extraValues[index].textContent = value;
    extraUnits[index].textContent = unit;
  });

  const pairLabels = networkContent.querySelectorAll("[data-network-pair-label]");
  const pairValues = networkContent.querySelectorAll("[data-network-pair-value]");
  const pairUnits = networkContent.querySelectorAll("[data-network-pair-unit]");
  view.pair.forEach(([label, value, unit], index) => {
    pairLabels[index].textContent = label;
    pairValues[index].textContent = value;
    pairUnits[index].textContent = unit;
  });

  networkPanel.dataset.networkView = viewName;
  networkContent.classList.remove("is-switching");
  void networkContent.offsetWidth;
  networkContent.classList.add("is-switching");
}

function stopNetworkRotation() {
  window.clearTimeout(networkRotationTimer);
}

function networkRotationIsPaused() {
  return (
    !networkPanel ||
    networkTabs.length < 2 ||
    reducedMotion.matches ||
    document.hidden ||
    networkPanel.matches(":hover") ||
    networkPanel.contains(document.activeElement)
  );
}

function scheduleNetworkRotation() {
  stopNetworkRotation();
  if (networkRotationIsPaused()) return;

  networkRotationTimer = window.setTimeout(() => {
    if (networkRotationIsPaused()) return;
    const current = networkTabs.findIndex((tab) => tab.classList.contains("is-active"));
    const next = networkTabs[(current + 1 + networkTabs.length) % networkTabs.length];
    showNetworkView(next.dataset.networkView);
    scheduleNetworkRotation();
  }, NETWORK_ROTATE_DELAY);
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
scheduleNetworkRotation();

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
