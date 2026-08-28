(() => {
  "use strict";

  const panel = document.querySelector('[data-workspace-panel="intelligence-map"]');
  if (!panel) return;

  const palette = ["#18c8e6", "#4e8eff", "#2fc1b4", "#8a63ea", "#f3a719"];
  const state = { payload: null, filters: { days: "all", category: "all", region: "all" } };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const countBy = (values) => values.reduce((counts, value) => value ? counts.set(value, (counts.get(value) || 0) + 1) : counts, new Map());
  const ranked = (counts) => [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"));

  function filteredItems() {
    const all = state.payload?.items || [];
    let floor = "";
    if (state.filters.days !== "all" && all.length) {
      const latest = new Date(`${all.map((item) => item.sourceDate).sort().at(-1)}T00:00:00`);
      latest.setDate(latest.getDate() - Number(state.filters.days) + 1);
      floor = latest.toISOString().slice(0, 10);
    }
    return all.filter((item) => (!floor || item.sourceDate >= floor)
      && (state.filters.category === "all" || item.category === state.filters.category)
      && (state.filters.region === "all" || item.region === state.filters.region));
  }

  function filterOptions(values, selected, allLabel) {
    return `<option value="all">${allLabel}</option>${[...new Set(values)].sort((a, b) => a.localeCompare(b, "zh-CN"))
      .map((value) => `<option value="${esc(value)}"${value === selected ? " selected" : ""}>${esc(value)}</option>`).join("")}`;
  }

  function trendChart(items) {
    const dates = [...new Set(items.map((item) => item.sourceDate))].sort();
    const categories = ranked(countBy(items.map((item) => item.category))).slice(0, 5).map(([name]) => name);
    if (!dates.length) return '<div class="intelligence-map-empty">当前筛选范围内暂无已审核情报</div>';
    const width = 980;
    const height = 360;
    const margin = { top: 18, right: 18, bottom: 38, left: 36 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const values = categories.flatMap((category) => dates.map((date) => items.filter((item) => item.sourceDate === date && item.category === category).length));
    const maxValue = Math.max(4, ...values);
    const x = (index) => margin.left + (dates.length === 1 ? plotWidth / 2 : index * plotWidth / (dates.length - 1));
    const y = (value) => margin.top + plotHeight - value * plotHeight / maxValue;
    const grid = Array.from({ length: maxValue + 1 }, (_, value) => value).map((value) => `
      <line class="grid" x1="${margin.left}" y1="${y(value)}" x2="${width - margin.right}" y2="${y(value)}"></line>
      <text class="axis-label" x="${margin.left - 10}" y="${y(value) + 3}" text-anchor="end">${value}</text>`).join("");
    const labelStep = Math.max(1, Math.ceil(dates.length / 9));
    const labels = dates.map((date, index) => index % labelStep === 0 || index === dates.length - 1
      ? `<text class="axis-label" x="${x(index)}" y="${height - 12}" text-anchor="middle">${date.slice(5)}</text>` : "").join("");
    const series = categories.map((category, categoryIndex) => {
      const color = palette[categoryIndex];
      const points = dates.map((date, index) => ({ x: x(index), y: y(items.filter((item) => item.sourceDate === date && item.category === category).length) }));
      return `<polyline class="series" stroke="${color}" points="${points.map((point) => `${point.x},${point.y}`).join(" ")}"></polyline>${points.map((point) => `<circle class="point" stroke="${color}" cx="${point.x}" cy="${point.y}" r="2.6"></circle>`).join("")}`;
    }).join("");
    return `<div class="intelligence-trend-legend">${categories.map((category, index) => `<span><i style="--legend-color:${palette[index]}"></i>${esc(category)}</span>`).join("")}</div>
      <svg class="intelligence-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="议题变化趋势图">${grid}${series}${labels}</svg>`;
  }

  function graphData(items) {
    const nodes = new Map();
    const edges = new Map();
    const touch = (id, label, type) => {
      const node = nodes.get(id) || { id, label, type, count: 0 };
      node.count += 1;
      nodes.set(id, node);
    };
    const link = (source, target) => {
      const key = [source, target].sort().join("::");
      const edge = edges.get(key) || { source, target, count: 0 };
      edge.count += 1;
      edges.set(key, edge);
    };
    items.forEach((item) => {
      const topicId = `topic:${item.category}`;
      touch(topicId, item.category, "topic");
      item.entities.forEach((entity) => {
        const entityId = `entity:${entity}`;
        touch(entityId, entity, "entity");
        link(entityId, topicId);
        item.concepts.forEach((concept) => link(entityId, `concept:${concept}`));
      });
      item.concepts.forEach((concept) => {
        const conceptId = `concept:${concept}`;
        touch(conceptId, concept, "concept");
        link(topicId, conceptId);
      });
    });
    const selectedNodes = [...nodes.values()].sort((a, b) => b.count - a.count).slice(0, 24);
    const selectedIds = new Set(selectedNodes.map((node) => node.id));
    return { nodes: selectedNodes, edges: [...edges.values()].filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target)).sort((a, b) => b.count - a.count).slice(0, 42) };
  }

  function networkGraph(items) {
    const { nodes, edges } = graphData(items);
    if (!nodes.length) return '<div class="intelligence-map-empty">当前筛选范围内暂无可关联实体</div>';
    const width = 560;
    const height = 410;
    const center = { x: width / 2, y: height / 2 + 4 };
    const positions = new Map();
    nodes.forEach((node, index) => {
      if (index === 0) return positions.set(node.id, center);
      const ringIndex = index - 1;
      const innerCount = Math.min(8, nodes.length - 1);
      const inner = ringIndex < innerCount;
      const count = inner ? innerCount : Math.max(1, nodes.length - 1 - innerCount);
      const localIndex = inner ? ringIndex : ringIndex - innerCount;
      const radius = inner ? 112 : 184;
      const angle = -Math.PI / 2 + localIndex * Math.PI * 2 / count + (inner ? 0 : .18);
      positions.set(node.id, { x: center.x + Math.cos(angle) * radius, y: center.y + Math.sin(angle) * radius });
    });
    const nodeColor = { entity: "#6679e8", topic: "#55aaf0", concept: "#23c574" };
    const edgeMarkup = edges.map((edge) => {
      const source = positions.get(edge.source);
      const target = positions.get(edge.target);
      return `<line class="edge" style="--edge-width:${Math.min(3.5, 1 + edge.count * .32)}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"><title>共同出现 ${edge.count} 条</title></line>`;
    }).join("");
    const nodeMarkup = nodes.map((node) => {
      const point = positions.get(node.id);
      const radius = Math.min(16, 6 + Math.sqrt(node.count) * 2.2);
      return `<g class="node" style="--node-color:${nodeColor[node.type]}" transform="translate(${point.x} ${point.y})"><circle r="${radius}"><title>${esc(node.label)} · ${node.count} 条证据</title></circle><text y="${radius + 14}">${esc(node.label)}</text></g>`;
    }).join("");
    return `<svg class="intelligence-network-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="情报主体、议题与概念关联图">${edgeMarkup}${nodeMarkup}</svg>`;
  }

  function insights(items) {
    const topicRanks = ranked(countBy(items.map((item) => item.category)));
    const entityRanks = ranked(countBy(items.flatMap((item) => item.entities)));
    const conceptRanks = ranked(countBy(items.flatMap((item) => item.concepts)));
    const latest = items.map((item) => item.sourceDate).sort().at(-1);
    let recentCopy = "当前筛选范围内暂无可归纳情报。";
    if (latest) {
      const end = new Date(`${latest}T00:00:00`);
      const recentFloor = new Date(end); recentFloor.setDate(end.getDate() - 6);
      const previousFloor = new Date(end); previousFloor.setDate(end.getDate() - 13);
      const recent = items.filter((item) => item.sourceDate >= recentFloor.toISOString().slice(0, 10)).length;
      const previous = items.filter((item) => item.sourceDate >= previousFloor.toISOString().slice(0, 10) && item.sourceDate < recentFloor.toISOString().slice(0, 10)).length;
      recentCopy = `近 7 日新增 ${recent} 条，较前一周期${recent >= previous ? "增加" : "减少"} ${Math.abs(recent - previous)} 条。`;
    }
    const concentration = topicRanks[0] ? `${topicRanks[0][0]} ${topicRanks[0][1]} 条，占当前情报 ${Math.round(topicRanks[0][1] / Math.max(1, items.length) * 100)}%。` : "暂无议题集中度数据。";
    const subjects = entityRanks.length ? entityRanks.slice(0, 3).map(([label, count]) => `${label} ${count}条`).join("、") : "暂无明确主体命中。";
    const hotspots = conceptRanks.length ? conceptRanks.slice(0, 3).map(([label, count]) => `${label} ${count}条`).join("、") : "暂无明确热点命中。";
    return [
      ["近期变化", recentCopy, "#4e8eff"],
      ["议题集中", concentration, "#8171ef"],
      ["主体集中", subjects, "#25c576"],
      ["热点集中", hotspots, "#f0a514"],
    ].map(([title, copy, color]) => `<article class="intelligence-insight-item" style="--accent:${color}"><strong>${title}</strong><p>${esc(copy)}</p></article>`).join("");
  }

  function render() {
    const all = state.payload?.items || [];
    const items = filteredItems();
    const dates = items.map((item) => item.sourceDate).sort();
    const range = dates.length ? `${dates[0].slice(5)} — ${dates.at(-1).slice(5)}` : "暂无数据";
    panel.innerHTML = `<div class="intelligence-map-workbench">
      <section class="intelligence-map-main" id="intelligenceMapMain">
        <div class="intelligence-trend-panel">
          <header class="intelligence-map-header">
            <div class="intelligence-map-heading"><strong>议题变化趋势</strong><span>${esc(range)} · ${items.length} 条已审核情报</span></div>
            <div class="intelligence-map-filters" aria-label="情报图谱筛选">
              <select data-map-filter="days" aria-label="时间范围"><option value="all">全部时间</option><option value="7"${state.filters.days === "7" ? " selected" : ""}>近 7 日</option><option value="14"${state.filters.days === "14" ? " selected" : ""}>近 14 日</option><option value="30"${state.filters.days === "30" ? " selected" : ""}>近 30 日</option></select>
              <select data-map-filter="category" aria-label="议题">${filterOptions(all.map((item) => item.category), state.filters.category, "全部议题")}</select>
              <select data-map-filter="region" aria-label="区域">${filterOptions(all.map((item) => item.region), state.filters.region, "全部区域")}</select>
            </div>
          </header>
          ${trendChart(items)}
        </div>
        <div class="intelligence-network-panel">
          <header class="intelligence-map-network-header">
            <div class="intelligence-map-heading"><strong>情报关联</strong><span>主体、议题与概念的共同出现关系</span></div>
            <div class="intelligence-map-network-actions"><span class="intelligence-map-mode">图谱</span><button class="intelligence-map-icon-button" type="button" data-map-fullscreen aria-label="全屏查看情报关联"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"></path></svg></button></div>
          </header>
          <div class="intelligence-network-legend"><span><i style="--node-color:#6679e8"></i>主体</span><span><i style="--node-color:#55aaf0"></i>议题</span><span><i style="--node-color:#23c574"></i>概念</span></div>
          <div class="intelligence-network-canvas">${networkGraph(items)}</div>
        </div>
      </section>
      <section class="intelligence-insight-strip" aria-label="AI 情报洞察">
        <div class="intelligence-insight-title"><svg viewBox="0 0 24 24"><path d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3ZM5 15l1 2.5L8.5 19 6 20l-1 2.5L4 20l-2.5-1L4 17.5 5 15Z"></path></svg><div><strong>AI 情报洞察</strong><small>基于已审核证据自动归纳</small></div></div>
        ${insights(items)}
      </section>
    </div>`;
  }

  panel.addEventListener("change", (event) => {
    const filter = event.target.closest("[data-map-filter]");
    if (!filter) return;
    state.filters[filter.dataset.mapFilter] = filter.value;
    render();
  });
  panel.addEventListener("click", (event) => {
    if (!event.target.closest("[data-map-fullscreen]")) return;
    panel.querySelector("#intelligenceMapMain")?.requestFullscreen?.();
  });

  async function initialize() {
    await window.CMHKAuth?.ready;
    if (!window.CMHKAuth?.hasModule("competitor")) return;
    try {
      const response = await fetch("/api/competitor-intelligence-map", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.payload = await response.json();
      render();
    } catch (_error) {
      panel.innerHTML = '<div class="intelligence-map-empty" role="status">情报图谱数据暂时无法读取，请稍后刷新。</div>';
    }
  }

  initialize();
})();
