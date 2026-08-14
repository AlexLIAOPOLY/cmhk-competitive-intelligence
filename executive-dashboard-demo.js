const monitoringViews = {
  network: {
    initial: "mobile",
    views: {
      fixed: {
        lead: ["住宅覆盖户数", "245", "万户", "+6.7%"],
        metrics: [["商业楼宇及设施覆盖", "12,800", "栋"], ["网络可用率", "99.99", "%"], ["重点监控", "覆盖与装机效率", ""]]
      },
      mobile: {
        lead: ["5G基站总数", "3,700", "座", "+8.4%"],
        metrics: [["4G基站总数", "6,880", "座"], ["5G平均下载速率", "1.1", "Gbps"], ["5G MR覆盖率", "98.8", "%"], ["3.3–4.9GHz持牌带宽", "140", "MHz"]]
      },
      cloud: {
        lead: ["自有数据中心", "6", "个", "+1"],
        metrics: [["总建筑面积", "32.8", "万㎡"], ["智算能力", "4,860", "PFLOPS"], ["机柜上架率", "78", "%"], ["PUE", "1.28", ""]]
      },
      research: {
        lead: ["专利数量", "486", "项", "+12.4%"],
        metrics: [["5G-A / 6G", "持续跟踪", ""], ["AI 与算力", "重点监控", ""], ["云网融合", "重点监控", ""]]
      }
    }
  },
  business: {
    initial: "toc",
    views: {
      toc: {
        lead: ["总移动用户", "342.8", "万", "TOC"],
        metrics: [["后付用户", "218.4", "万"], ["预付用户", "124.4", "万"], ["5G后付用户", "128.6", "万"], ["移动综合 ARPU", "138.6", "港元"]]
      },
      toh: {
        lead: ["家庭宽带用户", "86.4", "万", "TOH"],
        metrics: [["家庭 ARPU", "198.2", "港元"], ["端口数", "128.6", "万"], ["离网率", "0.86", "%"]]
      },
      tob: {
        lead: ["企业客户数", "38.2", "万", "TOB"],
        metrics: [["项目签约额", "18.6", "亿港元"], ["连接收入", "21.8", "亿港元"], ["云应用收入", "13.6", "亿港元"], ["5G专网收入", "4.6", "亿港元"]]
      }
    }
  },
  reach: {
    initial: "brand",
    views: {
      brand: {
        lead: ["品牌认知度", "91.6", "%", "CMHK"],
        metrics: [["品牌满意度", "89.2", "%"], ["转台考虑品牌", "CMHK", "首选"], ["品牌综合指数", "88.7", "分"]]
      },
      channel: {
        lead: ["全港实体门市", "138", "间", "渠道触达"],
        metrics: [["直销及外展团队", "620", "人"], ["官方社交平台", "8", "个平台"], ["网站活跃用户", "96.8", "万"], ["手机应用活跃用户", "218", "万"]]
      }
    }
  },
  finance: {
    initial: "income",
    views: {
      income: {
        lead: ["营运收入", "96.8", "亿港元", "CMHK"],
        metrics: [["主营移动收入", "61.4", "亿港元"], ["主营全业务收入", "84.2", "亿港元"], ["手机及附件销售收入", "12.6", "亿港元"]]
      },
      margin: {
        lead: ["EBITDA", "34.8", "亿港元", "35.9%"],
        metrics: [["EBITDA率", "35.9", "%"], ["净利润", "12.4", "亿港元"], ["净利润率", "12.8", "%"]]
      },
      cost: {
        lead: ["运营成本", "61.5", "亿港元", "含折旧摊销"],
        metrics: [["不含折旧摊销", "44.8", "亿港元"], ["折旧摊销", "16.7", "亿港元"], ["手机及附件销售成本", "11.5", "亿港元"]]
      },
      investment: {
        lead: ["资本支出", "18.9", "亿港元", "资本投资"],
        metrics: [["频谱牌照费", "4.2", "亿港元"], ["总资产收益率", "6.8", "%"], ["广义固定资产收益率", "9.4", "%"]]
      },
      cash: {
        lead: ["自由现金流", "16.2", "亿港元", "现金流"],
        metrics: [["现金及现金等值", "42.8", "亿港元"], ["净利润", "12.4", "亿港元"], ["现金监控", "保持关注", ""]]
      }
    }
  }
};

function metricRow([label, value, unit]) {
  const row = document.createElement("div");
  row.className = "metric-row";
  const labelNode = document.createElement("span");
  labelNode.textContent = label;
  const valueNode = document.createElement("strong");
  valueNode.textContent = value;
  if (unit) {
    const unitNode = document.createElement("small");
    unitNode.textContent = unit;
    valueNode.append(unitNode);
  }
  row.append(labelNode, valueNode);
  return row;
}

function renderPanel(panelName, viewName, focusTab = false) {
  const config = monitoringViews[panelName];
  const view = config?.views?.[viewName];
  const panel = document.querySelector(`[data-panel="${panelName}"]`);
  if (!panel || !view) return;

  const tabs = [...panel.querySelectorAll(`[data-${panelName}-view]`)];
  tabs.forEach((tab) => {
    const active = tab.dataset[`${panelName}View`] === viewName;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
    if (active && focusTab) tab.focus();
  });

  const [label, value, unit, change] = view.lead;
  panel.querySelector("[data-lead-label]").textContent = label;
  panel.querySelector("[data-lead-value]").textContent = value;
  panel.querySelector("[data-lead-unit]").textContent = unit;
  panel.querySelector("[data-lead-change]").textContent = change;

  const list = panel.querySelector("[data-metric-list]");
  list.replaceChildren(...view.metrics.map(metricRow));
  const content = panel.querySelector(".metric-layout");
  content.dataset.activeView = viewName;
  content.classList.remove("is-updating");
  void content.offsetWidth;
  content.classList.add("is-updating");
}

Object.entries(monitoringViews).forEach(([panelName, config]) => {
  const panel = document.querySelector(`[data-panel="${panelName}"]`);
  const tabs = [...panel.querySelectorAll(`[data-${panelName}-view]`)];
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => renderPanel(panelName, tab.dataset[`${panelName}View`]));
    tab.addEventListener("keydown", (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      let nextIndex = index;
      if (event.key === 'ArrowRight') nextIndex = (index + 1) % tabs.length;
      if (event.key === 'ArrowLeft') nextIndex = (index - 1 + tabs.length) % tabs.length;
      if (event.key === 'Home') nextIndex = 0;
      if (event.key === 'End') nextIndex = tabs.length - 1;
      renderPanel(panelName, tabs[nextIndex].dataset[`${panelName}View`], true);
    });
  });
  renderPanel(panelName, config.initial);
});

const signalMatchers = [
  { name: "宏观与国际", terms: ["HIBOR", "汇率", "GDP", "财政", "地缘", "国际", "制裁"] },
  { name: "政策法规", terms: ["OFCA", "通讯局", "牌照", "频谱", "隐私", "跨境", "监管", "政策"] },
  { name: "基础设施与技术", terms: ["5G", "6G", "AI", "算力", "数据中心", "卫星", "云", "网络"] },
  { name: "市场与产品", terms: ["企业", "eSIM", "物联网", "专网", "产品", "业务", "漫游"] }
];

function signalCategory(item) {
  const haystack = `${item.category || ""} ${item.title || ""} ${item.summary || ""}`;
  return signalMatchers.find((group) => group.terms.some((term) => haystack.includes(term)))?.name || "市场与产品";
}

function formatSignalDate(value) {
  if (!value) return "持续监测";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "持续监测";
  return new Intl.DateTimeFormat("zh-HK", { month: "numeric", day: "numeric" }).format(date);
}

async function refreshStrategicSignals() {
  const list = document.querySelector("#signalList");
  if (!list) return;
  try {
    const response = await fetch("./strategic-briefs.json", { cache: "no-store" });
    if (!response.ok) return;
    const payload = await response.json();
    const competitorTerms = ["HKT", "香港电讯", "香港電訊", "3香港", "SmarTone", "数码通", "數碼通", "HKBN", "香港宽频", "香港寬頻", "HGC", "和记电讯", "和記電訊"];
    const items = (Array.isArray(payload.items) ? payload.items : []).filter((item) => {
      const text = `${item.title || ""} ${item.summary || ""}`;
      return !competitorTerms.some((term) => text.includes(term));
    });
    if (!items.length) return;
    const selected = [];
    signalMatchers.forEach((group) => {
      const match = items.find((item) => signalCategory(item) === group.name && !selected.includes(item));
      if (match) selected.push(match);
    });
    items.forEach((item) => {
      if (selected.length < 4 && !selected.includes(item)) selected.push(item);
    });
    list.replaceChildren(...selected.slice(0, 4).map((item) => {
      const link = document.createElement("a");
      link.className = "signal-item";
      link.href = item.source_url || "/#strategyTickerList";
      if (item.source_url) {
        link.target = "_blank";
        link.rel = "noreferrer";
      }
      const category = document.createElement("span");
      category.textContent = signalCategory(item);
      const title = document.createElement("strong");
      title.textContent = item.title || "战略监测动态";
      const date = document.createElement("small");
      date.textContent = formatSignalDate(item.published_at);
      link.append(category, title, date);
      return link;
    }));
  } catch (_error) {
    // Keep the monitoring-rule fallback visible when the live feed is unavailable.
  }
}

refreshStrategicSignals();
