(() => {
  "use strict";

  const panel = document.querySelector('[data-workspace-panel="intelligence-map"]');
  if (!panel) return;

  const palette = ["#18c8e6", "#4e8eff", "#2fc1b4", "#8a63ea", "#f3a719"];
  const cacheKey = "cmhk-intelligence-map-v1";
  const state = { payload: null, hiddenCategories: new Set(), networkView: "graph", selectedTrend: null, selectedNode: null };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const countBy = (values) => values.reduce((counts, value) => value ? counts.set(value, (counts.get(value) || 0) + 1) : counts, new Map());
  const ranked = (counts) => [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"));

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
      const hidden = state.hiddenCategories.has(category);
      const points = dates.map((date, index) => ({ date, count: items.filter((item) => item.sourceDate === date && item.category === category).length, x: x(index) }));
      return `<g class="series-group${hidden ? " is-hidden" : ""}" data-series-group="${esc(category)}"><polyline class="series" stroke="${color}" points="${points.map((point) => `${point.x},${y(point.count)}`).join(" ")}"></polyline>${points.map((point) => `<g class="trend-point" tabindex="0" role="button" aria-label="${esc(point.date)}，${esc(category)}，${point.count} 条" data-trend-point data-category="${esc(category)}" data-date="${point.date}" data-count="${point.count}"><circle class="point-hit" cx="${point.x}" cy="${y(point.count)}" r="9"></circle><circle class="point" stroke="${color}" cx="${point.x}" cy="${y(point.count)}" r="2.8"></circle><title>${esc(point.date)} · ${esc(category)} · ${point.count} 条</title></g>`).join("")}</g>`;
    }).join("");
    const selected = state.selectedTrend;
    const evidence = selected ? items.filter((item) => item.sourceDate === selected.date && item.category === selected.category) : [];
    return `<div class="intelligence-trend-legend" aria-label="点击图例显示或隐藏曲线">${categories.map((category, index) => `<button type="button" data-trend-series="${esc(category)}" aria-pressed="${String(!state.hiddenCategories.has(category))}" class="${state.hiddenCategories.has(category) ? "is-muted" : ""}"><i style="--legend-color:${palette[index]}"></i>${esc(category)}</button>`).join("")}</div>
      <svg class="intelligence-trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="可交互议题变化趋势图">${grid}${series}${labels}</svg>
      <div class="intelligence-selection-detail" data-trend-detail aria-live="polite">${selected ? `<strong>${esc(selected.date)} · ${esc(selected.category)} · ${selected.count} 条</strong><span>${evidence.length ? evidence.slice(0, 2).map((item) => esc(item.title)).join("；") : "当日无对应情报"}</span>` : "悬停查看数值，点击数据点查看对应情报"}</div>`;
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
      return `<line class="edge" data-edge-source="${esc(edge.source)}" data-edge-target="${esc(edge.target)}" style="--edge-width:${Math.min(3.5, 1 + edge.count * .32)}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"><title>共同出现 ${edge.count} 条</title></line>`;
    }).join("");
    const nodeMarkup = nodes.map((node) => {
      const point = positions.get(node.id);
      const radius = Math.min(16, 6 + Math.sqrt(node.count) * 2.2);
      return `<g class="node${state.selectedNode?.id === node.id ? " is-selected" : ""}" tabindex="0" role="button" aria-label="${esc(node.label)}，${node.count} 条证据" data-map-node="${esc(node.id)}" data-node-label="${esc(node.label)}" data-node-type="${esc(node.type)}" data-node-count="${node.count}" style="--node-color:${nodeColor[node.type]}" transform="translate(${point.x} ${point.y})"><circle r="${radius}"><title>${esc(node.label)} · ${node.count} 条证据</title></circle><text y="${radius + 14}">${esc(node.label)}</text></g>`;
    }).join("");
    return `<svg class="intelligence-network-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="情报主体、议题与概念关联图">${edgeMarkup}${nodeMarkup}</svg>`;
  }

  function wordCloud(items) {
    const words = new Map();
    const add = (label, type) => {
      const key = `${type}:${label}`;
      const word = words.get(key) || { id: key, label, type, count: 0 };
      word.count += 1;
      words.set(key, word);
    };
    items.forEach((item) => {
      add(item.category, "topic");
      item.entities.forEach((label) => add(label, "entity"));
      item.concepts.forEach((label) => add(label, "concept"));
    });
    const rankedWords = [...words.values()].sort((a, b) => b.count - a.count).slice(0, 32);
    const maxCount = Math.max(1, ...rankedWords.map((word) => word.count));
    return `<div class="intelligence-word-cloud" role="list" aria-label="可交互情报词云">${rankedWords.map((word, index) => `<button type="button" role="listitem" data-map-node="${esc(word.id)}" data-node-label="${esc(word.label)}" data-node-type="${esc(word.type)}" data-node-count="${word.count}" class="${state.selectedNode?.id === word.id ? "is-selected" : ""}" style="--word-size:${12 + Math.round(word.count / maxCount * 18)}px;--word-color:${palette[index % palette.length]}">${esc(word.label)}<small>${word.count}</small></button>`).join("")}</div>`;
  }

  function relationDetail(items) {
    const selected = state.selectedNode;
    if (!selected) return "悬停查看关系，点击节点或词语查看对应情报";
    const evidence = items.filter((item) => item.category === selected.label || item.entities.includes(selected.label) || item.concepts.includes(selected.label));
    const typeLabel = { entity: "主体", topic: "议题", concept: "概念" }[selected.type] || "节点";
    return `<strong>${esc(selected.label)} · ${typeLabel} · ${selected.count} 条</strong><span>${evidence.slice(0, 2).map((item) => esc(item.title)).join("；") || "暂无对应情报标题"}</span>`;
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
    const items = state.payload?.items || [];
    panel.innerHTML = `<div class="intelligence-map-workbench">
      <section class="intelligence-map-main" id="intelligenceMapMain">
        <div class="intelligence-trend-panel">
          ${trendChart(items)}
        </div>
        <div class="intelligence-network-panel">
          <header class="intelligence-map-network-header">
            <div class="intelligence-map-network-actions" role="group" aria-label="关系视图"><button class="intelligence-map-mode${state.networkView === "graph" ? " is-active" : ""}" type="button" data-network-view="graph" aria-pressed="${String(state.networkView === "graph")}">图谱</button><button class="intelligence-map-mode${state.networkView === "cloud" ? " is-active" : ""}" type="button" data-network-view="cloud" aria-pressed="${String(state.networkView === "cloud")}">词云</button></div>
            <button class="intelligence-map-icon-button" type="button" data-map-fullscreen aria-label="全屏查看情报关联"><svg viewBox="0 0 24 24"><path d="M8 3H3v5M16 3h5v5M21 16v5h-5M3 16v5h5"></path></svg></button>
          </header>
          ${state.networkView === "graph" ? '<div class="intelligence-network-legend"><span><i style="--node-color:#6679e8"></i>主体</span><span><i style="--node-color:#55aaf0"></i>议题</span><span><i style="--node-color:#23c574"></i>概念</span></div>' : ""}
          <div class="intelligence-network-canvas">${state.networkView === "cloud" ? wordCloud(items) : networkGraph(items)}</div>
          <div class="intelligence-selection-detail" data-network-detail aria-live="polite">${relationDetail(items)}</div>
        </div>
      </section>
      <section class="intelligence-insight-strip" aria-label="AI 情报洞察">
        <div class="intelligence-insight-title"><svg viewBox="0 0 24 24"><path d="m12 3 1.7 4.3L18 9l-4.3 1.7L12 15l-1.7-4.3L6 9l4.3-1.7L12 3ZM5 15l1 2.5L8.5 19 6 20l-1 2.5L4 20l-2.5-1L4 17.5 5 15Z"></path></svg><div><strong>AI 情报洞察</strong><small>基于已审核证据自动归纳</small></div></div>
        ${insights(items)}
      </section>
    </div>`;
  }

  panel.addEventListener("click", (event) => {
    const series = event.target.closest("[data-trend-series]");
    if (series) {
      const category = series.dataset.trendSeries;
      if (state.hiddenCategories.has(category)) state.hiddenCategories.delete(category);
      else state.hiddenCategories.add(category);
      render();
      return;
    }
    const point = event.target.closest("[data-trend-point]");
    if (point) {
      state.selectedTrend = { category: point.dataset.category, date: point.dataset.date, count: Number(point.dataset.count || 0) };
      render();
      return;
    }
    const node = event.target.closest("[data-map-node]");
    if (node) {
      state.selectedNode = { id: node.dataset.mapNode, label: node.dataset.nodeLabel, type: node.dataset.nodeType, count: Number(node.dataset.nodeCount || 0) };
      render();
      return;
    }
    const view = event.target.closest("[data-network-view]");
    if (view) {
      state.networkView = view.dataset.networkView;
      state.selectedNode = null;
      render();
      return;
    }
    if (event.target.closest("[data-map-fullscreen]")) panel.querySelector("#intelligenceMapMain")?.requestFullscreen?.();
  });

  panel.addEventListener("pointerover", (event) => {
    const series = event.target.closest("[data-trend-series], [data-series-group]");
    if (series) panel.querySelectorAll("[data-series-group]").forEach((group) => group.classList.toggle("is-hover-muted", group.dataset.seriesGroup !== (series.dataset.trendSeries || series.dataset.seriesGroup)));
    const node = event.target.closest("[data-map-node]");
    if (!node || state.networkView !== "graph") return;
    const id = node.dataset.mapNode;
    const connected = new Set([id]);
    panel.querySelectorAll("[data-edge-source]").forEach((edge) => {
      const active = edge.dataset.edgeSource === id || edge.dataset.edgeTarget === id;
      edge.classList.toggle("is-hover-muted", !active);
      if (active) connected.add(edge.dataset.edgeSource === id ? edge.dataset.edgeTarget : edge.dataset.edgeSource);
    });
    panel.querySelectorAll("[data-map-node]").forEach((item) => item.classList.toggle("is-hover-muted", !connected.has(item.dataset.mapNode)));
  });
  panel.addEventListener("pointerout", (event) => {
    if (!event.target.closest("[data-trend-series], [data-series-group], [data-map-node]")) return;
    panel.querySelectorAll(".is-hover-muted").forEach((item) => item.classList.remove("is-hover-muted"));
  });
  panel.addEventListener("keydown", (event) => {
    if (!["Enter", " "].includes(event.key) || !event.target.closest("[data-trend-point], [data-map-node]")) return;
    event.preventDefault();
    event.target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });

  async function initialize() {
    try {
      const cached = JSON.parse(sessionStorage.getItem(cacheKey) || "null");
      if (cached?.ok && Array.isArray(cached.items)) {
        state.payload = cached;
        render();
      }
    } catch (_error) { /* A fresh request below remains authoritative. */ }
    try {
      await Promise.race([
        window.CMHKAuth?.ready,
        new Promise((_, reject) => window.setTimeout(() => reject(new Error("auth timeout")), 4000)),
      ]);
      if (!window.CMHKAuth?.hasModule("competitor")) return;
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 4000);
      const response = await fetch("/api/competitor-intelligence-map", { cache: "no-store", signal: controller.signal });
      window.clearTimeout(timeout);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.payload = await response.json();
      render();
      try { sessionStorage.setItem(cacheKey, JSON.stringify(state.payload)); } catch (_error) { /* Cache is optional. */ }
    } catch (_error) {
      if (!state.payload) panel.innerHTML = '<div class="intelligence-map-loading" role="status">暂时无法读取情报图谱，请稍后刷新。</div>';
    }
  }

  initialize();
})();
