const panels = [...document.querySelectorAll(".panel")];
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const brandTrack = document.querySelector(".brand-track");
const brandSourceSet = brandTrack?.querySelector(".brand-set");
let brandResizeFrame = 0;
const networkPanel = document.querySelector(".panel-network");
const networkContent = document.querySelector("#network-detail");
const networkTabs = [...document.querySelectorAll("[data-network-view]")];

const networkViews = {
  fixed: {
    hero: ["光纖接入端口", "228萬", "+6.7%"],
    chartLabel: "核心固定網絡資源",
    bars: [["骨幹光纖", "18,600 km", "100%"], ["接入機樓", "312 個", "82%"], ["10G PON", "76 萬", "74%"], ["國際出口", "9.8 Tbps", "66%"]],
    extras: [["家居覆蓋", "245", "萬戶"], ["專線節點", "168", "個"], ["可用率", "99.999", "%"]],
    pair: [["光纖到樓", "98.6", "%"], ["平均時延", "1.8", "ms"]]
  },
  mobile: {
    hero: ["5G 基站", "3,700", "+8.4%"],
    chartLabel: "各營運商5G基站比較",
    bars: [["CMHK", "1,620", "90%"], ["HKT", "1,810", "100%"], ["3香港", "1,390", "77%"], ["SmarTone", "1,260", "70%"]],
    extras: [["5G 頻譜", "140", "MHz"], ["邊緣節點", "26", "個"], ["網絡可用率", "99.99", "%"]],
    pair: [["人口覆蓋", "99.9", "%"], ["智能算力", "1,680", "PFLOPS"]]
  },
  cloud: {
    hero: ["智算資源池", "4,860P", "+21.6%"],
    chartLabel: "數據中心核心能力",
    bars: [["將軍澳 DC", "1,680P", "100%"], ["葵涌 DC", "1,320P", "79%"], ["火炭 DC", "1,080P", "64%"], ["邊緣節點", "780P", "46%"]],
    extras: [["機架規模", "8,600", "架"], ["綠電使用", "72", "%"], ["PUE", "1.28", ""]],
    pair: [["雲節點", "42", "個"], ["儲存容量", "26.8", "EB"]]
  },
  research: {
    hero: ["年度研發投入", "18.6億", "+15.2%"],
    chartLabel: "重點研發方向投入",
    bars: [["AI 與大模型", "6.8億", "100%"], ["6G 預研", "4.9億", "72%"], ["雲網融合", "4.2億", "62%"], ["安全技術", "2.7億", "40%"]],
    extras: [["研發人員", "1,260", "人"], ["有效專利", "486", "項"], ["聯合實驗室", "12", "個"]],
    pair: [["成果轉化", "68", "%"], ["年度新增專利", "92", "項"]]
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

networkTabs.forEach((tab) => {
  tab.addEventListener("click", () => showNetworkView(tab.dataset.networkView));
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

function rebuildBrandRail() {
  if (!brandTrack || !brandSourceSet) return;

  brandTrack.querySelectorAll("[data-brand-clone]").forEach((clone) => clone.remove());
  const brandSetWidth = brandSourceSet.getBoundingClientRect().width;
  if (!brandSetWidth) return;

  const requiredSets = Math.ceil(window.innerWidth / brandSetWidth) + 2;
  for (let index = 1; index < requiredSets; index += 1) {
    const clone = brandSourceSet.cloneNode(true);
    clone.dataset.brandClone = "";
    clone.setAttribute("aria-hidden", "true");
    clone.querySelectorAll("img").forEach((image) => image.setAttribute("alt", ""));
    brandTrack.append(clone);
  }

  brandTrack.style.setProperty("--brand-loop-width", `${brandSetWidth}px`);
  brandTrack.style.setProperty("--brand-duration", `${brandSetWidth / 34}s`);
}

rebuildBrandRail();

window.addEventListener("resize", () => {
  cancelAnimationFrame(brandResizeFrame);
  brandResizeFrame = requestAnimationFrame(rebuildBrandRail);
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
