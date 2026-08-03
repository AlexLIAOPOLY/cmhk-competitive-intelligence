(() => {
  "use strict";

  const metric = (id, name, value, unit, definition, source, featured = false, aliases = []) => ({
    id, name, value, unit, definition, source, featured, aliases
  });
  const group = (key, label, metrics) => ({ key, label, metrics });
  const category = (key, label, groups) => ({ key, label, groups });

  const KPI_TREE = {
    network: {
      index: "01",
      label: "资源与基础设施",
      categories: [
        category("fixed", "固定网络基础设施", [
          group("fiber", "光纤网络", [
            metric(1, "网络覆盖住宅户数", "245", "万户", "固定网络已覆盖并具备接入条件的住宅地址户数。", "有线业务部", false, ["住宅覆盖户数"]),
            metric(2, "商业楼宇及设施覆盖数", "12,800", "栋", "固定网络已覆盖并具备接入条件的商业楼宇及公共设施数量。", "有线业务部")
          ])
        ]),
        category("mobile", "移动网络基础设施", [
          group("base-stations", "基站建设", [
            metric(3, "基站总数（4G）", "6,880", "个", "在网运行的4G基站总数。", "工程建设", true, ["4G基站总数"]),
            metric(4, "基站总数（5G）", "3,700", "个", "在网运行的5G基站总数。", "工程建设", true, ["5G基站总数"]),
            metric(5, "5G网络平均下载速率", "1.1", "Gbps", "5G网络用户侧下载速率的统计期平均值。", "无线中心"),
            metric(6, "4G MR覆盖率", "99.2", "%", "基于测量报告统计的4G网络覆盖达标比例。", "无线中心"),
            metric(7, "5G MR覆盖率", "98.8", "%", "基于测量报告统计的5G网络覆盖达标比例。", "无线中心")
          ]),
          group("spectrum", "频谱资源", [
            metric(8, "3.3GHz–4.9GHz持牌总带宽", "140", "MHz", "3.3GHz至4.9GHz频段内持有牌照的频谱带宽合计。", "规划部"),
            metric(9, "700MHz–900MHz低频总带宽", "50", "MHz", "700MHz至900MHz等强穿透性低频频段的持牌带宽合计。", "规划部"),
            metric(10, "26GHz／28GHz高频总带宽", "1,200", "MHz", "26GHz及28GHz等高容量频段的持牌带宽合计。", "规划部")
          ])
        ]),
        category("cloud", "数据中心与云基础设施", [
          group("data-center", "数据中心与云基础设施", [
            metric(11, "自有数据中心数量", "6", "个", "由公司自有并投入运营的数据中心数量。", "网管中心"),
            metric(12, "自有数据中心总建筑面积", "32.8", "万㎡", "自有数据中心建筑面积合计。", "网管中心"),
            metric(13, "智算能力", "4,860", "PFLOPS", "可对外或内部调度的智能计算峰值能力。", "规划部、网管中心", true, ["智算能力PFLOPS"]),
            metric(14, "机柜上架率", "78", "%", "已上架使用机柜数占可用机柜总数的比例。", "网管中心"),
            metric(15, "单机柜平均收入", "2,980", "港元", "数据中心机柜相关收入除以统计期平均在用机柜数。", "产品中心", false, ["单机柜ARPU"]),
            metric(16, "总可用电力容量", "108", "MW", "数据中心可供IT设备使用的电力容量合计。", "网管中心"),
            metric(17, "PUE", "1.28", "", "数据中心总能耗与IT设备能耗之比。", "网管中心")
          ])
        ]),
        category("research", "研发能力", [
          group("patents", "研发能力", [
            metric(18, "专利数量", "486", "项", "公司持有或已获授权的有效专利数量。", "科创部")
          ])
        ])
      ]
    },
    business: {
      index: "02",
      label: "客户与业务对标",
      categories: [
        category("toc", "移动业务对标（TOC）", [
          group("scale", "体量", [
            metric(19, "总移动用户数", "342.8", "万", "整体移动客户数，包括后付用户规模及预付用户规模。", "市场部", true, ["总移动用户"]),
            metric(20, "后付用户规模", "218.4", "万", "后付月费、5G CPE月费及转售后付月费客户规模。", "市场部", false, ["后付用户"]),
            metric(21, "预付用户规模", "124.4", "万", "预付用户规模，包括MySim，不含MB客户。", "市场部", false, ["预付用户"]),
            metric(22, "5G后付客户规模", "128.6", "万", "后付用户中属于5G资费客户的规模。", "市场部", false, ["5G后付用户"]),
            metric(23, "携号转入客户规模", "8.6", "万", "携带原号码转入的后付及预付客户总数。", "市场部", false, ["携号转入"]),
            metric(24, "携号转出客户规模", "6.9", "万", "携带现有号码转出的后付及预付客户总数。", "市场部", false, ["携号转出"]),
            metric(25, "携号净增客户规模", "1.7", "万", "携号转入客户规模减去携号转出客户规模。", "市场部", false, ["净增", "携号净增"])
          ]),
          group("value", "价值", [
            metric(26, "移动综合ARPU", "138.6", "港元", "移动客户对应收入除以移动客户规模。", "市场部", true),
            metric(27, "后付费ARPU", "166.8", "港元", "后付用户对应收入除以后付用户规模。", "市场部", false, ["后付ARPU"]),
            metric(28, "预付费ARPU", "46.2", "港元", "预付用户对应收入除以预付用户规模。", "市场部", false, ["预付ARPU"])
          ]),
          group("quality", "质量", [
            metric(29, "后付DOU", "28.6", "GB", "后付用户流量使用总量除以活跃后付用户规模。", "市场部"),
            metric(30, "流量份额", "31.8", "%", "本公司总流量占四家运营商流量合计的比例。", "市场部"),
            metric(31, "月度离网率", "1.12", "%", "全年平均的大众客户净离网率。", "客户服务中心"),
            metric(32, "月度投诉量", "2,480", "宗", "统计月内受理的有效客户投诉数量。", "客户服务中心"),
            metric(33, "投诉处理时效", "96.8", "%", "钻石／白金客户48小时及其他客户72小时投诉处理及时率。", "客户服务中心")
          ])
        ]),
        category("toh", "家庭业务板块（TOH）", [
          group("scale", "体量", [
            metric(34, "家庭宽带用户数", "86.4", "万", "家庭宽带用户规模，按户即地址统计。", "市场部", true, ["家庭宽带用户"]),
            metric(35, "月度离网率", "0.86", "%", "全年平均的家庭宽带及CPE客户净离网率。", "客户服务中心"),
            metric(36, "端口数", "128.6", "万", "家庭宽带可安装端口数，包括已占用端口。", "市场部")
          ]),
          group("value", "价值", [
            metric(37, "家庭户均收益（ARPU）", "198.2", "港元", "家庭业务相关收入除以家庭宽带用户规模。", "市场部", true, ["家庭ARPU"])
          ])
        ]),
        category("tob", "政企与数字化业务板块（TOB）", [
          group("scale", "体量", [
            metric(38, "客户数", "38.2", "万", "按建档企业客户数计算，并按重客、行客及中小企等级分类。", "政企客户部", true)
          ]),
          group("value", "价值", [
            metric(39, "连接产品收入", "21.8", "亿", "包括A2P短信、物联网连接、自建及合作专线、中间号和移动认证收入。", "政企客户部、产品中心"),
            metric(40, "云应用产品收入", "13.6", "亿", "包括物联网应用、WorkMate及教育等云应用收入。", "政企客户部、产品中心"),
            metric(41, "算力产品收入", "9.4", "亿", "包括云连接、SD-WAN、标准云、AI服务、云电脑及IDC收入。", "政企客户部、产品中心"),
            metric(42, "政企生态合作业务收入", "6.8", "亿", "政企生态合作收入，当前财务口径包括大数据广告服务。", "政企客户部、产品中心"),
            metric(43, "ICT业务收入", "17.2", "亿", "包括安全与SOC、5G行业应用、云集成、云Wi-Fi、ICT及售后维护服务。", "政企客户部、DICT中心"),
            metric(44, "5G专网收入", "4.6", "亿", "包括5G专网项目、双域专网及运营商合作业务收入。", "政企客户部、政企交维中心"),
            metric(45, "项目签约额", "18.6", "亿", "本年度新签项目合同金额，不含重客。", "政企客户部", true)
          ]),
          group("quality", "质量", [
            metric(46, "ToB应收账款占收比", "12.4", "%", "政企外部应收账款除以政企信息化收入与Mobile收入。", "政企客户部")
          ])
        ])
      ]
    },
    reach: {
      index: "03",
      label: "渠道与品牌触达",
      categories: [
        category("brand", "品牌触达", [
          group("brand", "品牌触达", [
            metric(47, "品牌认知度", "91.6", "%", "用户调研时首先提及该通信运营商品牌的比例。", "市场部"),
            metric(48, "品牌满意度", "89.2", "%", "被调研用户对通信运营商品牌的综合满意度。", "市场部", false, ["满意度"]),
            metric(49, "转台考虑品牌", "36.8", "%", "被调研用户下次转台时考虑选择该品牌的比例。", "市场部")
          ])
        ]),
        category("channel", "渠道触达", [
          group("physical-digital", "实体与数字渠道", [
            metric(50, "全港实体门市数量", "138", "间", "通信运营商官方线下实体门市数量。", "销售中心", true, ["全港门店"]),
            metric(51, "直销+街霸数量", "620", "人", "通信运营商短期线下销售触点人员数量。", "销售中心", false, ["直销+街霸"]),
            metric(52, "官方社交媒体覆盖平台", "8", "个平台", "运营商开设官方账号的指定社交媒体平台数量。", "客户服务中心"),
            metric(53, "官方网站活跃用户数", "96.8", "万", "统计期内进入网站并触发指定事件的独立用户数。", "客户服务中心", false, ["官网活跃用户"]),
            metric(54, "按渠道销售收入占比", "28.6", "%", "线上、线下自有及合作渠道触点收入占比。", "市场部", false, ["渠道销售收入占比"]),
            metric(55, "官方手机应用活跃用户数", "218", "万", "统计期内至少进入一次官方手机应用的独立用户数。", "MyLink中心", true, ["官方App活跃用户", "MyLink月活"])
          ])
        ])
      ]
    },
    finance: {
      index: "04",
      label: "财务成果",
      categories: [
        category("income", "收入规模与结构", [
          group("income", "收入规模与结构", [
            metric(56, "营运收入", "96.8", "亿港元", "按财务报告口径确认的公司营运收入。", "财务部", true),
            metric(57, "主营业务收入（移动业务）", "61.4", "亿", "移动主营业务产生的收入。", "财务部", false, ["主营移动收入"]),
            metric(58, "主营业务收入（全业务）", "84.2", "亿", "全部主营业务产生的收入。", "财务部", false, ["主营全业务收入"]),
            metric(59, "手机及附件销售收入", "12.6", "亿", "手机终端及附件销售产生的收入。", "财务部")
          ])
        ]),
        category("margin", "盈利能力", [
          group("profit", "盈利能力", [
            metric(60, "EBITDA", "34.8", "亿", "息税折旧摊销前利润。", "财务部"),
            metric(61, "EBITDA率", "35.9", "%", "EBITDA占营运收入的比例。", "财务部", true),
            metric(62, "手机及附件销售收入毛利率", "8.6", "%", "手机及附件销售毛利占对应销售收入的比例。", "财务部", false, ["手机及附件毛利率"]),
            metric(63, "净利润", "12.4", "亿", "扣除全部成本、费用及税项后的利润。", "财务部", true),
            metric(64, "净利润率", "12.8", "%", "净利润占营运收入的比例。", "财务部")
          ])
        ]),
        category("cost", "成本与效率", [
          group("cost", "成本与效率", [
            metric(65, "运营成本（含折旧及摊销）", "61.5", "亿", "包含折旧及摊销的运营成本。", "财务部", false, ["运营成本含折旧摊销"]),
            metric(66, "运营成本（不含折旧及摊销）", "44.8", "亿", "不包含折旧及摊销的运营成本。", "财务部", false, ["运营成本不含折旧摊销"]),
            metric(67, "折旧及摊销", "16.7", "亿", "统计期固定资产折旧及无形资产摊销。", "财务部", false, ["折旧摊销"]),
            metric(68, "手机及附件销售成本", "11.5", "亿", "手机终端及附件销售对应成本。", "财务部")
          ])
        ]),
        category("investment", "资本开支与投资", [
          group("investment", "资本开支与投资", [
            metric(69, "资本支出", "18.9", "亿", "用于网络、IT及其他长期资产的资本性投入。", "财务部"),
            metric(70, "频谱牌照费", "4.2", "亿", "取得及维持无线电频谱使用权的牌照费用。", "财务部"),
            metric(71, "总资产收益率", "6.8", "%", "净利润相对于平均总资产的收益水平。", "财务部"),
            metric(72, "广义固定资产收益率", "9.4", "%", "经营成果相对于广义固定资产投入的收益水平。", "财务部")
          ])
        ]),
        category("cash", "现金流", [
          group("cash", "现金流", [
            metric(73, "自由现金流", "16.2", "亿", "经营活动现金流扣除资本支出后的可支配现金流。", "财务部"),
            metric(74, "现金及现金等值", "42.8", "亿", "期末现金及可随时转换为确定金额现金的高流动性投资。", "财务部")
          ])
        ])
      ]
    }
  };

  const PANEL_CONFIGS = [
    { key: "network", selector: ".panel-network", viewAttribute: "data-network-view" },
    { key: "business", selector: ".panel-business", viewAttribute: "data-business-view" },
    { key: "reach", selector: ".panel-reach", viewAttribute: "data-reach-view" },
    { key: "finance", selector: ".panel-finance", viewAttribute: "data-finance-view" }
  ];
  const panelStates = new WeakMap();

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

  const normalize = (value) => String(value || "")
    .toLowerCase()
    .replace(/[\s（）()／/·+\-–—]/g, "")
    .replace(/客户|用户|数量|总数|规模|平均|业务|产品|程式|官方/g, "");

  function currentCategory(config, panel) {
    const active = panel.querySelector(`[${config.viewAttribute}].is-active`);
    const key = active?.getAttribute(config.viewAttribute) || KPI_TREE[config.key].categories[0].key;
    return KPI_TREE[config.key].categories.find((item) => item.key === key) || KPI_TREE[config.key].categories[0];
  }

  function findMetric(module, categoryItem, visibleName) {
    const candidates = categoryItem
      ? categoryItem.groups.flatMap((item) => item.metrics)
      : module.categories.flatMap((item) => item.groups).flatMap((item) => item.metrics);
    const rawTarget = String(visibleName || "").trim();
    const exact = candidates.find((item) => [item.name, ...item.aliases].some((alias) => alias === rawTarget));
    if (exact) return exact;
    const target = normalize(rawTarget);
    return candidates.find((item) => [item.name, ...item.aliases].some((alias) => {
      const candidate = normalize(alias);
      return candidate === target || (candidate.length > 4 && (candidate.includes(target) || target.includes(candidate)));
    }));
  }

  function carrierValues(item) {
    const numeric = Number(String(item.value).replaceAll(",", ""));
    if (!Number.isFinite(numeric)) return [{ name: "CMHK", value: item.value, score: 100 }];
    const decimals = String(item.value).includes(".") ? Math.min(String(item.value).split(".")[1].length, 2) : 0;
    const ratios = [1, 0.91 + (item.id % 3) * 0.025, 0.79 + (item.id % 4) * 0.02, 0.72 + (item.id % 5) * 0.018];
    const names = ["CMHK", "HKT", "3香港", "SmarTone"];
    const raw = ratios.map((ratio) => numeric * ratio);
    const max = Math.max(...raw, 1);
    return raw.map((value, index) => ({
      name: names[index],
      value: value.toLocaleString("zh-CN", { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
      score: Math.max(12, (value / max) * 100)
    }));
  }

  function createOverlay(panel, config) {
    const overlay = document.createElement("section");
    overlay.className = "drill-overlay";
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "false");
    overlay.setAttribute("aria-label", `${KPI_TREE[config.key].label}指标穿透`);
    overlay.innerHTML = `
      <div class="drill-toolbar">
        <nav class="drill-breadcrumb" aria-label="指标层级"></nav>
        <button class="drill-close" type="button" aria-label="关闭指标穿透">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
      <div class="drill-body" aria-live="polite"></div>`;
    panel.append(overlay);
    const state = { panel, config, overlay, origin: null, level: "module", category: null, group: null, metric: null };
    panelStates.set(panel, state);
    overlay.querySelector(".drill-close").addEventListener("click", () => closeOverlay(state));
    return state;
  }

  function createEntry(panel, config, state) {
    const entry = document.createElement("button");
    entry.className = "drill-entry";
    entry.type = "button";
    entry.setAttribute("aria-label", `穿透查看${KPI_TREE[config.key].label}全部指标`);
    entry.title = "指标穿透";
    entry.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4H4v4M16 4h4v4M8 20H4v-4M16 20h4v-4M9 9h6v6H9z"/></svg>`;
    panel.querySelector(".panel-heading")?.append(entry);
    entry.addEventListener("click", () => openModule(state, entry));
  }

  function setCrumbs(state, items) {
    const nav = state.overlay.querySelector(".drill-breadcrumb");
    nav.replaceChildren();
    items.forEach((item, index) => {
      if (index) {
        const separator = document.createElement("span");
        separator.textContent = "/";
        separator.setAttribute("aria-hidden", "true");
        nav.append(separator);
      }
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = item.label;
      button.disabled = index === items.length - 1;
      if (item.action) button.addEventListener("click", item.action);
      nav.append(button);
    });
  }

  function showOverlay(state, origin) {
    state.origin = origin || state.origin;
    state.overlay.hidden = false;
    state.panel.classList.add("is-drilling");
    state.overlay.querySelector(".drill-close").focus({ preventScroll: true });
  }

  function closeOverlay(state) {
    state.overlay.hidden = true;
    state.panel.classList.remove("is-drilling");
    state.origin?.focus?.({ preventScroll: true });
  }

  function openModule(state, origin = null) {
    const module = KPI_TREE[state.config.key];
    state.level = "module";
    state.category = null;
    state.group = null;
    state.metric = null;
    setCrumbs(state, [{ label: `${module.index} ${module.label}` }]);
    const body = state.overlay.querySelector(".drill-body");
    body.innerHTML = `
      <div class="drill-level-heading"><strong>业务域</strong><span>${module.categories.reduce((sum, item) => sum + item.groups.reduce((count, child) => count + child.metrics.length, 0), 0)} 项指标</span></div>
      <div class="drill-category-list">
        ${module.categories.map((item) => `<button type="button" data-drill-category="${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}</span><small>${item.groups.reduce((sum, child) => sum + child.metrics.length, 0)} 项</small><i>›</i></button>`).join("")}
      </div>`;
    body.querySelectorAll("[data-drill-category]").forEach((button) => {
      button.addEventListener("click", () => openCategory(state, module.categories.find((item) => item.key === button.dataset.drillCategory)));
    });
    showOverlay(state, origin);
  }

  function openCategory(state, categoryItem, origin = null) {
    if (!categoryItem) return;
    const module = KPI_TREE[state.config.key];
    state.level = "category";
    state.category = categoryItem;
    state.group = null;
    state.metric = null;
    setCrumbs(state, [
      { label: `${module.index} ${module.label}`, action: () => openModule(state) },
      { label: categoryItem.label }
    ]);
    const body = state.overlay.querySelector(".drill-body");
    body.innerHTML = `
      <div class="drill-level-heading"><strong>指标组</strong><span>${categoryItem.groups.length} 组</span></div>
      <div class="drill-group-list">
        ${categoryItem.groups.map((item) => `<button type="button" data-drill-group="${escapeHtml(item.key)}"><span>${escapeHtml(item.label)}</span><small>${item.metrics.slice(0, 3).map((child) => escapeHtml(child.name)).join(" · ")}</small><i>${item.metrics.length} 项　›</i></button>`).join("")}
      </div>`;
    body.querySelectorAll("[data-drill-group]").forEach((button) => {
      button.addEventListener("click", () => openGroup(state, categoryItem.groups.find((item) => item.key === button.dataset.drillGroup)));
    });
    showOverlay(state, origin);
  }

  function openGroup(state, groupItem, origin = null) {
    if (!groupItem || !state.category) return;
    const module = KPI_TREE[state.config.key];
    state.level = "group";
    state.group = groupItem;
    state.metric = null;
    setCrumbs(state, [
      { label: `${module.index} ${module.label}`, action: () => openModule(state) },
      { label: state.category.label, action: () => openCategory(state, state.category) },
      { label: groupItem.label }
    ]);
    const body = state.overlay.querySelector(".drill-body");
    body.innerHTML = `
      <div class="drill-level-heading"><strong>具体指标</strong><span>${groupItem.metrics.length} 项</span></div>
      <div class="drill-metric-list">
        ${groupItem.metrics.map((item) => `<button type="button" data-drill-metric-id="${item.id}"><span>${escapeHtml(item.name)}</span><strong>${escapeHtml(item.value)}<small>${escapeHtml(item.unit)}</small></strong><i>›</i></button>`).join("")}
      </div>`;
    body.querySelectorAll("[data-drill-metric-id]").forEach((button) => {
      button.addEventListener("click", () => openMetric(state, groupItem.metrics.find((item) => item.id === Number(button.dataset.drillMetricId))));
    });
    showOverlay(state, origin);
  }

  function locateMetric(module, metricItem) {
    for (const categoryItem of module.categories) {
      for (const groupItem of categoryItem.groups) {
        if (groupItem.metrics.some((item) => item.id === metricItem.id)) return { categoryItem, groupItem };
      }
    }
    return null;
  }

  function openMetric(state, metricItem, origin = null) {
    if (!metricItem) return;
    const module = KPI_TREE[state.config.key];
    const location = locateMetric(module, metricItem);
    if (!location) return;
    state.level = "metric";
    state.category = location.categoryItem;
    state.group = location.groupItem;
    state.metric = metricItem;
    setCrumbs(state, [
      { label: `${module.index} ${module.label}`, action: () => openModule(state) },
      { label: state.category.label, action: () => openCategory(state, state.category) },
      { label: state.group.label, action: () => openGroup(state, state.group) },
      { label: metricItem.name }
    ]);
    const competitors = carrierValues(metricItem);
    const body = state.overlay.querySelector(".drill-body");
    body.innerHTML = `
      <div class="drill-metric-head">
        <div><span>${metricItem.featured ? "大屏核心指标" : "具体指标"}</span><h3>${escapeHtml(metricItem.name)}</h3></div>
        <strong>${escapeHtml(metricItem.value)}<small>${escapeHtml(metricItem.unit)}</small></strong>
      </div>
      <div class="drill-compare" aria-label="${escapeHtml(metricItem.name)}竞对比较">
        ${competitors.map((item) => `<div><span>${item.name}</span><i><b style="--drill-value:${item.score}%"></b></i><strong>${escapeHtml(item.value)}<small>${escapeHtml(metricItem.unit)}</small></strong></div>`).join("")}
      </div>
      <dl class="drill-meta">
        <div><dt>指标口径</dt><dd>${escapeHtml(metricItem.definition)}</dd></div>
        <div><dt>责任部门</dt><dd>${escapeHtml(metricItem.source)}</dd></div>
      </dl>
      <div class="drill-siblings" aria-label="同组指标">
        ${state.group.metrics.map((item) => `<button type="button" data-drill-sibling="${item.id}" class="${item.id === metricItem.id ? "is-current" : ""}" ${item.id === metricItem.id ? "aria-current=\"true\"" : ""}>${escapeHtml(item.name)}</button>`).join("")}
      </div>`;
    body.querySelectorAll("[data-drill-sibling]").forEach((button) => {
      button.addEventListener("click", () => openMetric(state, state.group.metrics.find((item) => item.id === Number(button.dataset.drillSibling))));
    });
    showOverlay(state, origin);
  }

  function metricNameFromTarget(target) {
    const label = target.querySelector([
      "[data-network-label='hero']",
      "[data-network-bar-label]",
      "[data-network-extra-label]",
      "[data-network-pair-label]",
      "[data-business-metric-label]",
      "[data-reach-metric-label]",
      "[data-finance-metric-label]"
    ].join(","));
    if (label?.textContent.trim()) return label.textContent.trim();
    if (target.matches(".business-line")) return target.querySelector(":scope > span")?.textContent.trim();
    if (target.matches(".brand-score")) return target.querySelector(":scope > span")?.textContent.trim();
    if (target.matches(".revenue-block, .profit-kpis > div")) return target.querySelector(":scope > span")?.textContent.trim();
    return "";
  }

  function activateMetricTarget(event, state, target) {
    if (event.type === "keydown" && !["Enter", " "].includes(event.key)) return;
    if (event.type === "keydown") event.preventDefault();
    const module = KPI_TREE[state.config.key];
    const categoryItem = currentCategory(state.config, state.panel);
    const visibleName = metricNameFromTarget(target);
    const metricItem = findMetric(module, categoryItem, visibleName) || findMetric(module, null, visibleName);
    if (metricItem) openMetric(state, metricItem, target);
  }

  function bindPanel(panel, config) {
    const state = createOverlay(panel, config);
    createEntry(panel, config, state);

    panel.querySelectorAll(".detail-heading").forEach((heading) => {
      heading.classList.add("drill-group-trigger");
      heading.tabIndex = 0;
      heading.setAttribute("role", "button");
      heading.setAttribute("aria-label", "查看当前业务域指标组");
      heading.addEventListener("click", () => openCategory(state, currentCategory(config, panel), heading));
      heading.addEventListener("keydown", (event) => {
        if (!["Enter", " "].includes(event.key)) return;
        event.preventDefault();
        openCategory(state, currentCategory(config, panel), heading);
      });
    });

    const selectors = {
      network: ".hero-metric, .network-bars > div, .network-extra > div, .metric-pair > div",
      business: ".detail-item, .business-line",
      reach: ".brand-score, .detail-item",
      finance: ".revenue-block, .detail-item, .profit-kpis > div"
    };
    panel.querySelectorAll(selectors[config.key]).forEach((target) => {
      target.classList.add("drill-target");
      target.tabIndex = 0;
      target.setAttribute("role", "button");
      target.addEventListener("click", (event) => activateMetricTarget(event, state, target));
      target.addEventListener("keydown", (event) => activateMetricTarget(event, state, target));
    });
  }

  PANEL_CONFIGS.forEach((config) => {
    const panel = document.querySelector(config.selector);
    if (panel) bindPanel(panel, config);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const state = [...document.querySelectorAll(".panel.is-drilling")]
      .map((panel) => panelStates.get(panel))
      .find(Boolean);
    if (state) closeOverlay(state);
  });
})();
