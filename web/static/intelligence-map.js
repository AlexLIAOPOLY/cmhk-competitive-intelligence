(() => {
  "use strict";

  const panel = document.querySelector('[data-workspace-panel="intelligence-map"]');
  if (!panel) return;

  const palette = ["#16c8e5", "#4d8dff", "#26b9aa", "#8962e9", "#f2a516"];
  const typeColors = { entity: "#6679e8", topic: "#55aaf0", concept: "#23c574" };
  const cacheKey = "cmhk-intelligence-map-v2";
  const state = { payload: null, chart: null, graph: null, fullscreenGraph: null, graphPayload: null, view: "graph", keyword: "" };
  const $ = (id) => panel.querySelector(`#${id}`) || document.getElementById(id);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
  const ranked = (map) => [...map.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-CN"));

  function termsFor(item) {
    return [...new Set([item.category, ...(item.entities || []), ...(item.concepts || []),
      ...String(item.keywords || "").split(/[、,，;；|/\s]+/).map((term) => term.trim()).filter((term) => term.length > 1),
    ].filter(Boolean))];
  }

  function itemEvidence(item) {
    return { id: item.id, title: item.title, summary: item.summary, source: item.source, source_date: item.sourceDate, source_url: item.sourceUrl };
  }

  function graphData(items) {
    const nodes = new Map();
    const edges = new Map();
    const touch = (id, label, type, item) => {
      const node = nodes.get(id) || { id, label, type, count: 0, description: `${label}在已审核情报中的关联证据`, evidence: [] };
      node.count += 1;
      if (!node.evidence.some((evidence) => evidence.id === item.id)) node.evidence.push(itemEvidence(item));
      nodes.set(id, node);
    };
    const link = (source, target, label, item) => {
      const id = `${source}::${target}`;
      const edge = edges.get(id) || { id, source, target, label, weight: 0, description: `${label}，来自已审核情报的共同出现关系`, evidence: [] };
      edge.weight += 1;
      if (!edge.evidence.some((evidence) => evidence.id === item.id)) edge.evidence.push(itemEvidence(item));
      edges.set(id, edge);
    };
    items.forEach((item) => {
      const topic = `topic:${item.category}`;
      touch(topic, item.category, "topic", item);
      (item.entities || []).forEach((entity) => {
        const entityId = `entity:${entity}`;
        touch(entityId, entity, "entity", item);
        link(entityId, topic, "涉及议题", item);
      });
      (item.concepts || []).forEach((concept) => {
        const conceptId = `concept:${concept}`;
        touch(conceptId, concept, "concept", item);
        link(topic, conceptId, "关联概念", item);
        (item.entities || []).forEach((entity) => link(`entity:${entity}`, conceptId, "共同出现", item));
      });
    });
    const selectedNodes = [...nodes.values()].sort((a, b) => b.count - a.count).slice(0, 26);
    const ids = new Set(selectedNodes.map((node) => node.id));
    return { nodes: selectedNodes, edges: [...edges.values()].filter((edge) => ids.has(edge.source) && ids.has(edge.target)).sort((a, b) => b.weight - a.weight).slice(0, 40) };
  }

  function pageMarkup() {
    panel.innerHTML = `<section class="market-intel-page">
      <section class="market-situation-stage" aria-label="市场议题与关键词态势">
        <article class="market-trend-visual">
          <div class="market-trend-chart"><canvas id="market-topic-trend-chart" aria-label="可交互市场情报趋势图"></canvas></div>
          <div class="market-trend-detail" id="market-trend-detail" aria-live="polite">悬停查看数值，点击数据点查看对应情报</div>
        </article>
        <aside class="market-keyword-stage market-graph-stage">
          <header><div class="market-graph-toolbar"><div class="market-view-switch" role="tablist" aria-label="情报关联视图"><button class="act" type="button" role="tab" aria-selected="true" data-market-view="graph">图谱</button><button type="button" role="tab" aria-selected="false" data-market-view="cloud">词云</button></div><span id="market-graph-status">共现关系</span><button id="market-graph-expand" type="button" aria-label="放大知识图谱" title="放大知识图谱"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button></div></header>
          <div class="market-knowledge-graph">
            <div class="market-graph-canvas is-active" id="market-graph-canvas" role="application" aria-label="情报实体关系图，可拖拽、缩放、平移并点击节点或关系查看详情"></div>
            <div class="market-keyword-cloud" id="market-keyword-cloud" aria-label="可点击热门关键词云"></div>
            <div class="market-graph-legend" aria-label="节点类型"><span class="entity">主体</span><span class="topic">议题</span><span class="concept">概念</span></div>
            <section class="market-graph-detail" id="market-graph-detail" aria-live="polite" hidden></section>
          </div>
          <dialog class="market-graph-dialog" id="market-graph-dialog">
            <div class="market-graph-dialog-shell"><header><span id="market-graph-dialog-status">共现关系</span><div><button type="button" data-graph-reset>复位</button><button type="button" aria-label="关闭大图" data-graph-close>×</button></div></header><div class="market-graph-dialog-body"><div class="market-graph-canvas" id="market-graph-dialog-canvas"></div><div class="market-graph-legend"><span class="entity">主体</span><span class="topic">议题</span><span class="concept">概念</span></div><section class="market-graph-inspector" id="market-graph-dialog-detail"><div class="market-graph-inspector-empty">选择节点或关系查看证据</div></section></div></div>
          </dialog>
        </aside>
      </section>
      <section class="market-ai-section" aria-label="AI 情报洞察"><div class="market-ai-title"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m10 2 1.8 5.2L17 9l-5.2 1.8L10 16l-1.8-5.2L3 9l5.2-1.8zM18.5 14l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z"/></svg><strong>AI 情报洞察</strong></div><div id="market-ai-insights"></div></section>
    </section>`;
  }

  function renderTrend(items) {
    state.chart?.destroy();
    const canvas = $("market-topic-trend-chart");
    if (!canvas || !window.Chart) return;
    const dates = [...new Set(items.map((item) => item.sourceDate))].sort();
    const counts = new Map();
    items.forEach((item) => counts.set(item.category, (counts.get(item.category) || 0) + 1));
    const categories = ranked(counts).slice(0, 5).map(([label]) => label);
    const datasets = categories.map((label, index) => ({
      label, data: dates.map((date) => items.filter((item) => item.sourceDate === date && item.category === label).length),
      borderColor: palette[index], backgroundColor: `${palette[index]}18`, borderWidth: 2,
      pointRadius: 2.5, pointHoverRadius: 5, tension: .28, fill: false,
    }));
    state.chart = new window.Chart(canvas, {
      type: "line", data: { labels: dates.map((date) => date.slice(5)), datasets },
      options: {
        responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        onClick(_event, active) {
          if (!active.length) return;
          const point = active.find((candidate) => datasets[candidate.datasetIndex].data[candidate.index] > 0) || active[0];
          const date = dates[point.index]; const category = datasets[point.datasetIndex].label;
          const evidence = items.filter((item) => item.sourceDate === date && item.category === category);
          $("market-trend-detail").innerHTML = `<strong>${esc(date)} · ${esc(category)} · ${evidence.length} 条</strong><span>${evidence.slice(0, 2).map((item) => esc(item.title)).join("；") || "当日无对应情报"}</span>`;
        },
        plugins: {
          legend: { position: "top", labels: { color: "#8da3bb", usePointStyle: true, pointStyle: "line", boxWidth: 24, font: { size: 11 } } },
          tooltip: { backgroundColor: "#0b1728", borderColor: "rgba(84,136,177,.45)", borderWidth: 1, titleColor: "#dbe9f5", bodyColor: "#a8bdd2", padding: 10 },
        },
        scales: { x: { grid: { display: false }, ticks: { color: "#718aa4", maxTicksLimit: 10 } }, y: { beginAtZero: true, ticks: { color: "#718aa4", precision: 0 }, grid: { color: "rgba(95,128,158,.17)" } } },
      },
    });
  }

  function keywordTerms(items) {
    const counts = new Map();
    items.forEach((item) => termsFor(item).forEach((term) => counts.set(term, (counts.get(term) || 0) + 1)));
    return ranked(counts).slice(0, 24).map(([label, count]) => ({ label, count }));
  }

  function layoutWordCloud(target) {
    const buttons = [...target.querySelectorAll(".market-keyword")]; const width = target.clientWidth; const height = target.clientHeight;
    if (!buttons.length || width < 80 || height < 80) return;
    const edge = 10; const gap = 6; const placed = []; const candidates = [];
    const stepX = Math.max(14, Math.min(26, width / 25)); const stepY = Math.max(12, Math.min(22, height / 20));
    const rings = Math.ceil(Math.max(width / stepX, height / stepY));
    for (let ring = 0; ring <= rings; ring += 1) for (let row = -ring; row <= ring; row += 1) for (let column = -ring; column <= ring; column += 1) if (Math.max(Math.abs(column), Math.abs(row)) === ring) candidates.push([width / 2 + column * stepX, height / 2 + row * stepY]);
    buttons.forEach((button) => {
      let fontSize = Number(button.dataset.cloudSize || 14); let position = null; button.hidden = false;
      while (!position && fontSize >= 10) {
        button.style.setProperty("--cloud-size", `${fontSize}px`); const wordWidth = button.offsetWidth; const wordHeight = button.offsetHeight;
        position = candidates.find(([x, y]) => { const rect = { left: x - wordWidth / 2 - gap, right: x + wordWidth / 2 + gap, top: y - wordHeight / 2 - gap, bottom: y + wordHeight / 2 + gap }; return rect.left >= edge && rect.right <= width - edge && rect.top >= edge && rect.bottom <= height - edge && placed.every((other) => rect.right <= other.left || rect.left >= other.right || rect.bottom <= other.top || rect.top >= other.bottom); });
        if (!position) fontSize -= 1;
      }
      if (!position) { button.hidden = true; return; }
      button.style.setProperty("--cloud-x", `${position[0]}px`); button.style.setProperty("--cloud-y", `${position[1]}px`);
      placed.push({ left: position[0] - button.offsetWidth / 2 - gap, right: position[0] + button.offsetWidth / 2 + gap, top: position[1] - button.offsetHeight / 2 - gap, bottom: position[1] + button.offsetHeight / 2 + gap });
    });
  }

  function renderWordCloud(allItems) {
    const target = $("market-keyword-cloud"); const terms = keywordTerms(allItems); const max = Math.max(...terms.map((term) => term.count), 1); const min = Math.min(...terms.map((term) => term.count), max);
    target.innerHTML = terms.map((term, index) => { const normalized = max === min ? 1 : (term.count - min) / (max - min); const size = Math.round(10 + Math.pow(normalized, .72) * 30); return `<button class="market-keyword${state.keyword === term.label ? " is-active" : ""}" style="--cloud-size:${size}px;--word-color:${palette[index % palette.length]}" data-cloud-size="${size}" data-market-keyword="${esc(term.label)}" type="button" title="${esc(term.label)}：出现 ${term.count} 次"><span>${esc(term.label)}</span></button>`; }).join("");
    requestAnimationFrame(() => layoutWordCloud(target));
  }

  function graphStyle() {
    return [
      { selector: "node", style: { "background-color": (node) => typeColors[node.data("type")], "border-color": "#09182a", "border-width": 2, width: "mapData(count,1,8,20,42)", height: "mapData(count,1,8,20,42)", label: "data(label)", color: "#c9d9e8", "font-family": "inherit", "font-size": 9, "font-weight": 600, "text-wrap": "wrap", "text-max-width": 82, "text-valign": "bottom", "text-margin-y": 5 } },
      { selector: "edge", style: { width: "mapData(weight,1,6,1,3.6)", "line-color": "#263c54", "target-arrow-color": "#263c54", "target-arrow-shape": "triangle", "arrow-scale": .65, "curve-style": "bezier", label: "data(label)", color: "#647d96", "font-size": 7, "font-family": "inherit", "text-rotation": "autorotate", "text-background-color": "#081729", "text-background-opacity": .82, "text-background-padding": 2 } },
      { selector: ":selected", style: { "overlay-opacity": 0, "border-color": "#e1edf7", "border-width": 3 } },
      { selector: "edge:selected", style: { "line-color": "#16c8e5", "target-arrow-color": "#16c8e5", width: 3.2, color: "#dbe9f5" } },
      { selector: ".is-muted", style: { opacity: .13, "text-opacity": 0 } }, { selector: ".is-neighbor", style: { opacity: 1, "text-opacity": 1 } },
    ];
  }

  function graphLayout(fullscreen = false) {
    return { name: "cose", animate: false, fit: true, randomize: true, padding: fullscreen ? 58 : 30, nodeDimensionsIncludeLabels: true, componentSpacing: fullscreen ? 130 : 82, nodeRepulsion: () => fullscreen ? 10000 : 6500, nodeOverlap: fullscreen ? 22 : 14, idealEdgeLength: () => fullscreen ? 108 : 74, edgeElasticity: () => fullscreen ? 90 : 68, gravity: fullscreen ? .15 : .22, numIter: fullscreen ? 1700 : 1300 };
  }

  function evidenceHtml(data) {
    return (data.evidence || []).slice(0, 4).map((item) => `<a class="market-graph-evidence-row" href="${esc(item.source_url || "#")}" target="_blank" rel="noopener noreferrer"><span>${esc(item.title)}</span><small>${esc(item.source)} · ${esc(item.source_date)} <b aria-hidden="true">↗</b></small></a>`).join("");
  }

  function selectGraphElement(element, detailId = "market-graph-detail") {
    const cy = element?.cy?.(); if (!cy || !element.length) return;
    cy.elements().addClass("is-muted").removeClass("is-neighbor"); const neighborhood = element.isNode() ? element.closedNeighborhood() : element.connectedNodes().union(element);
    neighborhood.removeClass("is-muted").addClass("is-neighbor"); cy.elements().unselect(); element.select();
    const data = element.data(); const detail = $(detailId); if (!detail) return; detail.hidden = false;
    if (element.isNode()) { const type = { entity: "主体", topic: "议题", concept: "概念" }[data.type]; detail.innerHTML = `<div class="market-graph-detail-head"><strong>${esc(data.label)}</strong><span>${type} · ${data.count} 条证据</span></div><p>${esc(data.description)}</p><div class="market-graph-evidence-list">${evidenceHtml(data)}</div>`; }
    else { const source = cy.getElementById(data.source).data("label"); const target = cy.getElementById(data.target).data("label"); detail.innerHTML = `<div class="market-graph-detail-head"><strong>${esc(data.label)}</strong><span>${esc(source)} → ${esc(target)}</span></div><p>${esc(data.description)}</p><div class="market-graph-evidence-list">${evidenceHtml(data)}</div>`; }
  }

  function makeGraph(container, payload, fullscreen = false) {
    if (!container || !window.cytoscape) return null; container.innerHTML = "";
    const cy = window.cytoscape({ container, elements: [...payload.nodes.map((node) => ({ group: "nodes", data: node })), ...payload.edges.map((edge) => ({ group: "edges", data: edge }))], minZoom: fullscreen ? .35 : .45, maxZoom: fullscreen ? 3 : 2.4, boxSelectionEnabled: false, style: graphStyle(), layout: graphLayout(fullscreen) });
    cy.on("tap", "node, edge", (event) => selectGraphElement(event.target, fullscreen ? "market-graph-dialog-detail" : "market-graph-detail"));
    cy.on("tap", (event) => { if (event.target === cy) { cy.elements().removeClass("is-muted is-neighbor").unselect(); const detail = $(fullscreen ? "market-graph-dialog-detail" : "market-graph-detail"); if (detail) detail.hidden = true; } });
    cy.on("mouseover", "node, edge", () => { container.style.cursor = "pointer"; }); cy.on("mouseout", "node, edge", () => { container.style.cursor = "grab"; }); return cy;
  }

  function renderGraph(items) {
    state.graph?.destroy(); state.graphPayload = graphData(items); state.graph = makeGraph($("market-graph-canvas"), state.graphPayload);
    $("market-graph-status").textContent = `${state.graphPayload.nodes.length} 节点 · ${state.graphPayload.edges.length} 关系`;
  }

  function switchView(view) {
    state.view = view === "cloud" ? "cloud" : "graph";
    panel.querySelectorAll("[data-market-view]").forEach((button) => { const active = button.dataset.marketView === state.view; button.classList.toggle("act", active); button.setAttribute("aria-selected", String(active)); });
    $("market-graph-canvas").classList.toggle("is-active", state.view === "graph"); $("market-keyword-cloud").classList.toggle("is-active", state.view === "cloud");
    panel.querySelector(".market-knowledge-graph > .market-graph-legend").hidden = state.view !== "graph"; $("market-graph-status").hidden = state.view !== "graph"; $("market-graph-expand").hidden = state.view !== "graph";
    if (state.view === "graph") requestAnimationFrame(() => { state.graph?.resize(); state.graph?.fit(state.graph.elements(), 24); }); else requestAnimationFrame(() => layoutWordCloud($("market-keyword-cloud")));
  }

  function insights(items) {
    const count = (values) => { const map = new Map(); values.filter(Boolean).forEach((value) => map.set(value, (map.get(value) || 0) + 1)); return ranked(map); };
    const topics = count(items.map((item) => item.category)); const entities = count(items.flatMap((item) => item.entities || [])); const concepts = count(items.flatMap((item) => item.concepts || []));
    const latest = items.map((item) => item.sourceDate).sort().at(-1); let recent = "暂无近期变化。";
    if (latest) { const end = new Date(`${latest}T00:00:00`); const floor = new Date(end); floor.setDate(end.getDate() - 6); recent = `近 7 日新增 ${items.filter((item) => item.sourceDate >= floor.toISOString().slice(0, 10)).length} 条已审核情报。`; }
    return [["近期变化", recent, palette[1]], ["议题集中", topics[0] ? `${topics[0][0]} ${topics[0][1]} 条，占当前情报 ${Math.round(topics[0][1] / Math.max(1, items.length) * 100)}%。` : "暂无议题数据。", palette[3]], ["主体集中", entities.slice(0, 3).map(([name, total]) => `${name}${total}条`).join("、") || "暂无主体命中。", "#25c576"], ["热点集中", concepts.slice(0, 3).map(([name, total]) => `${name}${total}条`).join("、") || "暂无热点命中。", palette[4]]].map(([title, copy, color]) => `<article style="--accent:${color}"><strong>${title}</strong><p>${esc(copy)}</p></article>`).join("");
  }

  function renderAll() {
    const allItems = state.payload?.items || []; const items = state.keyword ? allItems.filter((item) => termsFor(item).includes(state.keyword)) : allItems;
    renderTrend(items); renderWordCloud(allItems); renderGraph(items); $("market-ai-insights").innerHTML = insights(items); switchView(state.view);
  }

  function openFullscreen() {
    const dialog = $("market-graph-dialog"); if (!dialog || !state.graphPayload) return; dialog.showModal();
    requestAnimationFrame(() => { state.fullscreenGraph?.destroy(); state.fullscreenGraph = makeGraph($("market-graph-dialog-canvas"), state.graphPayload, true); });
  }

  panel.addEventListener("click", (event) => {
    const view = event.target.closest("[data-market-view]"); if (view) return switchView(view.dataset.marketView);
    const keyword = event.target.closest("[data-market-keyword]"); if (keyword) { state.keyword = state.keyword === keyword.dataset.marketKeyword ? "" : keyword.dataset.marketKeyword; return renderAll(); }
    if (event.target.closest("#market-graph-expand")) return openFullscreen(); if (event.target.closest("[data-graph-close]")) return $("market-graph-dialog").close();
    if (event.target.closest("[data-graph-reset]")) { state.fullscreenGraph?.elements().removeClass("is-muted is-neighbor").unselect(); state.fullscreenGraph?.fit(state.fullscreenGraph.elements(), 52); }
  });

  async function initialize() {
    pageMarkup();
    $("market-graph-dialog").addEventListener("close", () => { state.fullscreenGraph?.destroy(); state.fullscreenGraph = null; });
    try { const cached = JSON.parse(sessionStorage.getItem(cacheKey) || "null"); if (cached?.ok && Array.isArray(cached.items)) { state.payload = cached; renderAll(); } } catch (_error) { /* cache is optional */ }
    try {
      await Promise.race([window.CMHKAuth?.ready, new Promise((_, reject) => setTimeout(() => reject(new Error("auth timeout")), 4000))]);
      if (!window.CMHKAuth?.hasModule("competitor")) return;
      const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 4000); const response = await fetch("/api/competitor-intelligence-map", { cache: "no-store", signal: controller.signal }); clearTimeout(timeout);
      if (!response.ok) throw new Error(`HTTP ${response.status}`); state.payload = await response.json(); renderAll();
      try { sessionStorage.setItem(cacheKey, JSON.stringify(state.payload)); } catch (_error) { /* cache is optional */ }
    } catch (_error) { if (!state.payload) panel.innerHTML = '<div class="intelligence-map-loading">暂时无法读取情报图谱，请稍后刷新。</div>'; }
  }

  initialize();
})();
