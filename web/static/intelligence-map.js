(() => {
  "use strict";

  const panel = document.querySelector('[data-workspace-panel="intelligence-map"]');
  if (!panel) return;

  const palette = ["#16c8e5", "#4d8dff", "#26b9aa", "#8962e9", "#f2a516"];
  const typeColors = { entity: "#6679e8", topic: "#55aaf0", concept: "#23c574" };
  const cacheKey = "cmhk-intelligence-map-v2";
  const activeRefreshIntervalMs = 30000;
  const state = { payload: null, graph: null, fullscreenGraph: null, graphPayload: null, keyword: "", receivedStart: "", receivedEnd: "", refreshPromise: null, lastRefreshAt: 0, signature: "", pollTimer: null, layoutFrame: null, resizeObserver: null };
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

  function keywordValues(item) {
    const aliases = { "人工智能": "AI", aigc: "AI", "5g": "5G", "6g": "6G" };
    const stopwords = new Set(["香港", "中国", "中國", "香港本地", "国际", "國際", "行业", "行業", "新闻", "新聞", "公司", "市场", "市場", "业务", "業務", "服务", "服務"]);
    return [...new Set(String(item.keywords || "").split(/[、，,；;|]+/).map((term) => term.trim().replace(/^#+/, "")).filter((term) => term.length > 1 && !stopwords.has(term)).map((term) => aliases[term] || aliases[term.toLowerCase()] || term))];
  }

  function graphTopic(value) {
    return { "政策与监管": "政策监管", "竞争对手": "竞对动态", "基础设施/网络/技术类": "基础设施／网络／技术", "市场/产品类": "市场／产品", "宏观经济&国际形势&地缘政治&其他国际性质关注词汇": "宏观／国际" }[value] || value || "其他情报";
  }

  function connectedGraph(nodes, candidateEdges, maxNodes = 20, maxEdges = 28) {
    const adjacency = new Map();
    candidateEdges.forEach((edge) => {
      if (!adjacency.has(edge.source)) adjacency.set(edge.source, new Set());
      if (!adjacency.has(edge.target)) adjacency.set(edge.target, new Set());
      adjacency.get(edge.source).add(edge.target); adjacency.get(edge.target).add(edge.source);
    });
    const unseen = new Set(adjacency.keys()); const components = [];
    while (unseen.size) {
      const start = unseen.values().next().value; const ids = new Set([start]); const queue = [start]; unseen.delete(start);
      while (queue.length) adjacency.get(queue.shift()).forEach((id) => { if (unseen.delete(id)) { ids.add(id); queue.push(id); } });
      const componentEdges = candidateEdges.filter((edge) => ids.has(edge.source) && ids.has(edge.target));
      components.push({ ids, edges: componentEdges, score: componentEdges.reduce((sum, edge) => sum + edge.weight, 0) });
    }
    const core = components.sort((a, b) => b.score - a.score || b.ids.size - a.ids.size)[0];
    if (!core) return { nodes: [], edges: [] };

    const parent = new Map([...core.ids].map((id) => [id, id]));
    const find = (id) => { let root = id; while (parent.get(root) !== root) root = parent.get(root); while (parent.get(id) !== id) { const next = parent.get(id); parent.set(id, root); id = next; } return root; };
    const treeEdges = [];
    core.edges.forEach((edge) => { const sourceRoot = find(edge.source); const targetRoot = find(edge.target); if (sourceRoot !== targetRoot) { parent.set(sourceRoot, targetRoot); treeEdges.push(edge); } });

    const selectedIds = new Set(core.ids);
    while (selectedIds.size > maxNodes) {
      const degree = new Map([...selectedIds].map((id) => [id, 0]));
      treeEdges.forEach((edge) => { if (selectedIds.has(edge.source) && selectedIds.has(edge.target)) { degree.set(edge.source, degree.get(edge.source) + 1); degree.set(edge.target, degree.get(edge.target) + 1); } });
      const leaf = [...selectedIds].filter((id) => degree.get(id) <= 1).sort((a, b) => nodes.get(a).count - nodes.get(b).count || ({ entity: 0, concept: 1, topic: 2 }[nodes.get(a).type] - ({ entity: 0, concept: 1, topic: 2 }[nodes.get(b).type])) || nodes.get(a).label.localeCompare(nodes.get(b).label, "zh-CN"))[0];
      if (!leaf) break;
      selectedIds.delete(leaf);
    }
    const requiredEdges = treeEdges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target));
    const requiredIds = new Set(requiredEdges.map((edge) => edge.id));
    const extraEdges = core.edges.filter((edge) => selectedIds.has(edge.source) && selectedIds.has(edge.target) && !requiredIds.has(edge.id));
    const selectedEdges = [...requiredEdges, ...extraEdges.slice(0, Math.max(0, maxEdges - requiredEdges.length))].sort((a, b) => b.weight - a.weight || a.id.localeCompare(b.id, "zh-CN"));
    const typeOrder = { entity: 0, topic: 1, concept: 2 };
    const selectedNodes = [...selectedIds].map((id) => nodes.get(id)).sort((a, b) => typeOrder[a.type] - typeOrder[b.type] || b.count - a.count || a.label.localeCompare(b.label, "zh-CN"));
    return { nodes: selectedNodes, edges: selectedEdges };
  }

  function graphData(items) {
    const nodes = new Map();
    const edges = new Map();
    const keywordCounts = new Map();
    items.forEach((item) => keywordValues(item).forEach((term) => keywordCounts.set(term, (keywordCounts.get(term) || 0) + 1)));
    const graphKeywords = new Set(ranked(keywordCounts).slice(0, 12).map(([label]) => label));
    const touch = (id, label, type, item) => {
      const node = nodes.get(id) || { id, label, type, count: 0, description: `${label}在本批次收到新闻中的关联证据`, evidence: [] };
      node.count += 1;
      if (!node.evidence.some((evidence) => evidence.id === item.id)) node.evidence.push(itemEvidence(item));
      nodes.set(id, node);
    };
    const link = (source, target, label, item) => {
      const id = `${source}::${target}`;
      const edge = edges.get(id) || { id, source, target, label, weight: 0, description: `${label}，来自本批次收到新闻的共同出现关系`, evidence: [] };
      edge.weight += 1;
      if (!edge.evidence.some((evidence) => evidence.id === item.id)) edge.evidence.push(itemEvidence(item));
      edges.set(id, edge);
    };
    items.forEach((item) => {
      const topicLabel = graphTopic(item.category);
      const topic = `topic:${topicLabel}`;
      touch(topic, topicLabel, "topic", item);
      const entityIds = (item.entities || []).map((entity) => {
        const entityId = `entity:${entity}`;
        touch(entityId, entity, "entity", item);
        link(entityId, topic, "涉及议题", item);
        return entityId;
      });
      const concepts = [...new Set([...(item.concepts || []), ...keywordValues(item).filter((term) => graphKeywords.has(term))])];
      concepts.forEach((concept) => {
        const conceptId = `concept:${concept}`;
        touch(conceptId, concept, "concept", item);
        link(topic, conceptId, "包含概念", item);
        entityIds.forEach((entityId) => link(entityId, conceptId, "关联概念", item));
      });
      entityIds.forEach((source, index) => entityIds.slice(index + 1).forEach((target) => link(source, target, "共同出现", item)));
    });
    const candidateEdges = [...edges.values()].sort((a, b) => b.weight - a.weight || a.label.localeCompare(b.label, "zh-CN") || a.id.localeCompare(b.id, "zh-CN"));
    return connectedGraph(nodes, candidateEdges);
  }

  function pageMarkup() {
    panel.innerHTML = `<section class="market-intel-page">
      <section class="market-situation-stage" aria-label="市场议题与关键词态势">
        <article class="market-keyword-stage market-cloud-stage">
          <header><h2>情报词云</h2><span>点击关键词聚焦右侧关联</span></header>
          <div class="market-keyword-cloud is-active" id="market-keyword-cloud" aria-label="可点击热门关键词云"></div>
        </article>
        <aside class="market-keyword-stage market-graph-stage">
          <header><h2>情报图谱</h2><div class="market-graph-toolbar"><span id="market-graph-status">共现关系</span><button id="market-graph-expand" type="button" aria-label="放大知识图谱" title="放大知识图谱"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button></div></header>
          <div class="market-knowledge-graph">
            <div class="market-graph-canvas is-active" id="market-graph-canvas" role="application" aria-label="情报实体关系图，可拖拽、缩放、平移并点击节点或关系查看详情"></div>
            <div class="market-graph-legend" aria-label="节点类型"><span class="entity">主体</span><span class="topic">议题</span><span class="concept">概念</span></div>
            <section class="market-graph-detail" id="market-graph-detail" aria-live="polite" hidden></section>
          </div>
          <dialog class="market-graph-dialog" id="market-graph-dialog">
            <div class="market-graph-dialog-shell"><header><h2>情报知识图谱</h2><div><span id="market-graph-dialog-status">共现关系</span><button type="button" data-graph-reset>复位</button><button type="button" aria-label="关闭大图" data-graph-close>×</button></div></header><div class="market-graph-dialog-body"><div class="market-graph-canvas" id="market-graph-dialog-canvas"></div><div class="market-graph-legend"><span class="entity">主体</span><span class="topic">议题</span><span class="concept">概念</span></div><section class="market-graph-inspector" id="market-graph-dialog-detail"><div class="market-graph-inspector-empty"><strong>选择一个节点或关系</strong><span>下方会展开关联路径、证据摘要和新闻原文。</span></div></section></div></div>
          </dialog>
        </aside>
      </section>
      <section class="market-daily-section" aria-label="收到的新闻明细"><div class="market-daily-table-wrap" id="market-daily-table"></div></section>
    </section>`;
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
    target.innerHTML = terms.map((term, index) => { const normalized = max === min ? 1 : (term.count - min) / (max - min); const size = Math.round(10 + Math.pow(normalized, .72) * 30); return `<button class="market-keyword${state.keyword === term.label ? " is-active" : ""}" style="--cloud-size:${size}px;--word-color:${palette[index % palette.length]};--word-index:${index}" data-cloud-size="${size}" data-market-keyword="${esc(term.label)}" type="button" title="${esc(term.label)}：出现 ${term.count} 次"><span>${esc(term.label)}</span></button>`; }).join("");
    requestAnimationFrame(() => layoutWordCloud(target));
  }

  function graphStyle() {
    return [
      { selector: "node", style: { "background-color": (node) => typeColors[node.data("type")], "border-color": "#09182a", "border-width": 2, width: "mapData(count,1,8,20,42)", height: "mapData(count,1,8,20,42)", label: "data(label)", color: "#c9d9e8", "font-family": "inherit", "font-size": 9, "font-weight": 600, "text-wrap": "wrap", "text-max-width": 82, "text-valign": "bottom", "text-margin-y": 5 } },
      { selector: "edge", style: { width: "mapData(weight,1,6,1,3.6)", "line-color": "#263c54", "target-arrow-color": "#263c54", "target-arrow-shape": "triangle", "arrow-scale": .65, "curve-style": "bezier", label: "data(label)", color: "#536c86", "font-size": 7, "font-family": "inherit", "text-rotation": "autorotate", "text-background-color": "#081729", "text-background-opacity": .76, "text-background-padding": 2 } },
      { selector: ":selected", style: { "overlay-opacity": 0, "border-color": "#e1edf7", "border-width": 3 } },
      { selector: "edge:selected", style: { "line-color": "#16c8e5", "target-arrow-color": "#16c8e5", width: 3.2, color: "#dbe9f5" } },
      { selector: ".is-muted", style: { opacity: .13, "text-opacity": 0 } }, { selector: ".is-neighbor", style: { opacity: 1, "text-opacity": 1 } },
    ];
  }

  function graphLayout(fullscreen = false) {
    return { name: "cose", animate: false, fit: true, randomize: false, padding: fullscreen ? 46 : 36, nodeDimensionsIncludeLabels: true, componentSpacing: fullscreen ? 58 : 44, nodeRepulsion: () => fullscreen ? 5200 : 4000, nodeOverlap: 10, idealEdgeLength: (edge) => Math.max(fullscreen ? 52 : 42, (fullscreen ? 76 : 62) - Math.min(Number(edge.data("weight")) || 1, 5) * 4), edgeElasticity: () => 32, gravity: fullscreen ? .5 : .65, numIter: 1400 };
  }

  function evidenceHtml(data) {
    return (data.evidence || []).slice(0, 4).map((item) => `<a class="market-graph-evidence-row" href="${esc(item.source_url || "#")}" target="_blank" rel="noopener noreferrer"><span>${esc(item.title)}</span><small>${esc(item.source)} · ${esc(item.source_date)} <b aria-hidden="true">↗</b></small></a>`).join("");
  }

  function inspectorHtml(element) {
    const cy = element.cy(); const data = element.data(); let title = data.label; let description = data.description; let meta = ""; let relations = [];
    if (element.isNode()) {
      const type = { entity: "主体", topic: "议题", concept: "概念" }[data.type] || "节点";
      meta = `${type} · ${data.count} 条证据`;
      relations = element.connectedEdges().toArray().sort((a, b) => Number(b.data("weight")) - Number(a.data("weight"))).map((edge) => {
        const neighbor = edge.source().id() === element.id() ? edge.target() : edge.source();
        return { id: neighbor.id(), label: neighbor.data("label"), relation: edge.data("label"), weight: edge.data("weight") };
      });
    } else {
      const source = cy.getElementById(data.source); const target = cy.getElementById(data.target);
      title = data.label; meta = `${source.data("label")} → ${target.data("label")} · ${data.weight} 条证据`;
      relations = [source, target].map((node) => ({ id: node.id(), label: node.data("label"), relation: "关联节点", weight: node.data("count") }));
    }
    const paths = relations.slice(0, 8).map((relation) => `<button type="button" data-graph-focus="${esc(relation.id)}"><span>${esc(relation.relation)} →</span><strong>${esc(relation.label)}</strong><small>${relation.weight} 条</small></button>`).join("");
    const proofs = (data.evidence || []).slice(0, 8).map((item) => `<article><div><span>${esc(item.source)} · ${esc(item.source_date)}</span><small>${esc(item.id)}</small></div><a href="${esc(item.source_url || "#")}" target="_blank" rel="noopener noreferrer">${esc(item.title)}</a>${item.summary ? `<p>${esc(item.summary)}</p>` : ""}<a class="market-graph-source-link" href="${esc(item.source_url || "#")}" target="_blank" rel="noopener noreferrer">打开新闻原文 <span>↗</span></a></article>`).join("");
    return `<header><div><strong>${esc(title)}</strong><span>${esc(meta)}</span></div><p>${esc(description)}</p></header><div class="market-graph-inspector-grid"><section><h3>关联路径 <span>${relations.length}</span></h3><div class="market-graph-path-list">${paths || "暂无关联路径"}</div></section><section><h3>证据新闻 <span>${(data.evidence || []).length}</span></h3><div class="market-graph-proof-list">${proofs || "暂无证据新闻"}</div></section></div>`;
  }

  function selectGraphElement(element, detailId = "market-graph-detail") {
    const cy = element?.cy?.(); if (!cy || !element.length) return;
    cy.elements().addClass("is-muted").removeClass("is-neighbor"); const neighborhood = element.isNode() ? element.closedNeighborhood() : element.connectedNodes().union(element);
    neighborhood.removeClass("is-muted").addClass("is-neighbor"); cy.elements().unselect(); element.select();
    const data = element.data(); const detail = $(detailId); if (!detail) return; detail.hidden = false;
    if (detailId === "market-graph-dialog-detail") { detail.innerHTML = inspectorHtml(element); return; }
    if (element.isNode()) { const type = { entity: "主体", topic: "议题", concept: "概念" }[data.type]; detail.innerHTML = `<div class="market-graph-detail-head"><strong>${esc(data.label)}</strong><span>${type} · ${data.count} 条证据</span></div><p>${esc(data.description)}</p><div class="market-graph-evidence-list">${evidenceHtml(data)}</div>`; }
    else { const source = cy.getElementById(data.source).data("label"); const target = cy.getElementById(data.target).data("label"); detail.innerHTML = `<div class="market-graph-detail-head"><strong>${esc(data.label)}</strong><span>${esc(source)} → ${esc(target)}</span></div><p>${esc(data.description)}</p><div class="market-graph-evidence-list">${evidenceHtml(data)}</div>`; }
  }

  function makeGraph(container, payload, fullscreen = false) {
    if (!container || !window.cytoscape) return null; container.innerHTML = "";
    const cy = window.cytoscape({ container, elements: [...payload.nodes.map((node) => ({ group: "nodes", data: node })), ...payload.edges.map((edge) => ({ group: "edges", data: edge }))], minZoom: fullscreen ? .35 : .45, maxZoom: fullscreen ? 3 : 2.4, boxSelectionEnabled: false, style: graphStyle(), layout: graphLayout(fullscreen) });
    cy.on("tap", "node, edge", (event) => selectGraphElement(event.target, fullscreen ? "market-graph-dialog-detail" : "market-graph-detail"));
    cy.on("tap", (event) => { if (event.target === cy) { cy.elements().removeClass("is-muted is-neighbor").unselect(); const detail = $(fullscreen ? "market-graph-dialog-detail" : "market-graph-detail"); if (detail && fullscreen) { detail.hidden = false; detail.innerHTML = '<div class="market-graph-inspector-empty"><strong>选择一个节点或关系</strong><span>下方会展开关联路径、证据摘要和新闻原文。</span></div>'; } else if (detail) detail.hidden = true; } });
    cy.on("mouseover", "node, edge", (event) => { event.target.addClass("is-hover"); container.style.cursor = "pointer"; }); cy.on("mouseout", "node, edge", (event) => { event.target.removeClass("is-hover"); container.style.cursor = "grab"; });
    if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      cy.nodes().style("opacity", .18); cy.edges().style("opacity", .08);
      cy.nodes().forEach((node, index) => window.setTimeout(() => { if (!node.removed()) node.animate({ style: { opacity: 1 } }, { duration: 420 }); }, index * 28));
      window.setTimeout(() => { if (!cy.destroyed()) cy.edges().animate({ style: { opacity: 1 } }, { duration: 620 }); }, 180);
    }
    return cy;
  }

  function renderGraph(items) {
    state.graph?.destroy(); state.graphPayload = graphData(items); state.graph = makeGraph($("market-graph-canvas"), state.graphPayload);
    $("market-graph-status").textContent = `${state.graphPayload.nodes.length} 节点 · ${state.graphPayload.edges.length} 关系`;
  }

  function scheduleVisualLayout() {
    window.cancelAnimationFrame(state.layoutFrame); state.layoutFrame = window.requestAnimationFrame(() => {
      state.layoutFrame = null;
      const cloud = $("market-keyword-cloud");
      if (cloud?.clientWidth > 0) layoutWordCloud(cloud);
      const graph = $("market-graph-canvas");
      if (graph?.clientWidth > 0) { state.graph?.resize(); state.graph?.fit(state.graph.elements(), 38); }
    });
  }

  function receivedMinute(item) {
    return String(item.publishedAt || "").slice(0, 16);
  }

  function renderReceivedNewsTable(items) {
    const target = $("market-daily-table"); if (!target) return;
    if (!items.length) { target.innerHTML = '<div class="market-daily-empty">最新批次暂无收到的新闻</div>'; return; }
    const receivedAt = String(state.payload?.receivedAt || "").replace("T", " ").slice(0, 16);
    const minutes = items.map(receivedMinute).filter(Boolean).sort(); const min = minutes[0] || ""; const max = minutes.at(-1) || "";
    const filtered = items.filter((item) => { const value = receivedMinute(item); return (!state.receivedStart || value >= state.receivedStart) && (!state.receivedEnd || value <= state.receivedEnd); });
    const selected = Boolean(state.receivedStart || state.receivedEnd);
    target.innerHTML = `<div class="market-received-toolbar"><div><h2>收到的新闻</h2><span>${selected ? `当前显示 ${filtered.length} / 本批次 ${items.length} 条` : `本批次共 ${items.length} 条`}${receivedAt ? ` · ${esc(receivedAt)}` : ""}</span></div><div class="market-time-filter" role="group" aria-label="按发布时间筛选新闻"><label><span>开始时间</span><input type="datetime-local" value="${esc(state.receivedStart)}" min="${esc(min)}" max="${esc(max)}" data-news-time-filter="start"></label><i aria-hidden="true">—</i><label><span>结束时间</span><input type="datetime-local" value="${esc(state.receivedEnd)}" min="${esc(min)}" max="${esc(max)}" data-news-time-filter="end"></label><button type="button" data-news-time-clear ${selected ? "" : "disabled"}>清除</button></div></div><table aria-label="收到的新闻明细"><thead><tr><th scope="col">发布时间</th><th scope="col">新闻标题</th><th scope="col">来源</th><th scope="col">监测模块</th><th scope="col">命中关键词</th></tr></thead><tbody>${filtered.map((item) => {
      const publishedAt = String(item.publishedAt || "").replace("T", " ").slice(0, 16) || "—";
      const title = item.url ? `<a href="${esc(item.url)}" target="_blank" rel="noopener noreferrer">${esc(item.title)}<b aria-hidden="true">↗</b></a>` : `<span>${esc(item.title)}</span>`;
      const keywords = Array.isArray(item.keywords) && item.keywords.length ? item.keywords.map((keyword) => `<em>${esc(keyword)}</em>`).join("") : "—";
      return `<tr><td class="received-time">${esc(publishedAt)}</td><th scope="row" class="received-title">${title}</th><td>${esc(item.source || "未标注来源")}</td><td>${esc(item.module || "其他情报")}</td><td class="received-keywords">${keywords}</td></tr>`;
    }).join("") || '<tr><td class="market-filter-empty" colspan="5">该时间范围内没有收到新闻</td></tr>'}</tbody></table>`;
  }

  function renderAll() {
    const allItems = state.payload?.receivedItems || []; const items = state.keyword ? allItems.filter((item) => termsFor(item).includes(state.keyword)) : allItems;
    renderWordCloud(allItems); renderGraph(items); renderReceivedNewsTable(state.payload?.receivedItems || []); scheduleVisualLayout();
  }

  function openFullscreen() {
    const dialog = $("market-graph-dialog"); if (!dialog || !state.graphPayload) return; dialog.showModal();
    requestAnimationFrame(() => { state.fullscreenGraph?.destroy(); state.fullscreenGraph = makeGraph($("market-graph-dialog-canvas"), state.graphPayload, true); });
  }

  panel.addEventListener("click", (event) => {
    const keyword = event.target.closest("[data-market-keyword]"); if (keyword) { state.keyword = state.keyword === keyword.dataset.marketKeyword ? "" : keyword.dataset.marketKeyword; return renderAll(); }
    if (event.target.closest("#market-graph-expand")) return openFullscreen(); if (event.target.closest("[data-graph-close]")) return $("market-graph-dialog").close();
    const focus = event.target.closest("[data-graph-focus]");
    if (focus && state.fullscreenGraph) { const element = state.fullscreenGraph.getElementById(focus.dataset.graphFocus); if (element.length) { selectGraphElement(element, "market-graph-dialog-detail"); state.fullscreenGraph.animate({ center: { eles: element }, zoom: Math.max(state.fullscreenGraph.zoom(), 1.1) }, { duration: 260 }); } return; }
    if (event.target.closest("[data-graph-reset]")) { state.fullscreenGraph?.elements().removeClass("is-muted is-neighbor").unselect(); state.fullscreenGraph?.fit(state.fullscreenGraph.elements(), 52); }
    if (event.target.closest("[data-news-time-clear]")) { state.receivedStart = ""; state.receivedEnd = ""; renderReceivedNewsTable(state.payload?.receivedItems || []); }
  });
  panel.addEventListener("change", (event) => {
    const input = event.target.closest("[data-news-time-filter]"); if (!input) return;
    if (input.dataset.newsTimeFilter === "start") state.receivedStart = input.value; else state.receivedEnd = input.value;
    renderReceivedNewsTable(state.payload?.receivedItems || []);
  });

  function payloadSignature(payload) {
    // A completed crawl is a new batch even when it finds the same items (or
    // zero items). Include its timestamp so the graph, cloud and table redraw
    // for every completed discovery batch instead of only for content changes.
    return `${payload?.evidenceHash || ""}:${payload?.receivedHash || ""}:${payload?.receivedAt || ""}`;
  }

  async function refreshData() {
    if (state.refreshPromise) return state.refreshPromise;
    state.refreshPromise = (async () => {
      const controller = new AbortController(); const timeout = window.setTimeout(() => controller.abort(), 4000);
      try {
        const response = await fetch(`/api/competitor-intelligence-map?_=${Date.now()}`, { cache: "no-store", signal: controller.signal });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json(); const signature = payloadSignature(payload); const changed = signature !== state.signature;
        state.payload = payload; state.lastRefreshAt = Date.now(); state.signature = signature;
        if (changed) renderAll();
        try { sessionStorage.setItem(cacheKey, JSON.stringify(state.payload)); } catch (_error) { /* cache is optional */ }
        return state.payload;
      } finally { window.clearTimeout(timeout); }
    })().catch(() => null).finally(() => { state.refreshPromise = null; });
    return state.refreshPromise;
  }

  async function initialize() {
    pageMarkup();
    $("market-graph-dialog").addEventListener("close", () => { state.fullscreenGraph?.destroy(); state.fullscreenGraph = null; });
    if (window.ResizeObserver) {
      state.resizeObserver = new ResizeObserver(scheduleVisualLayout);
      state.resizeObserver.observe($("market-keyword-cloud")); state.resizeObserver.observe($("market-graph-canvas"));
    }
    try { const cached = JSON.parse(sessionStorage.getItem(cacheKey) || "null"); if (cached?.ok && Array.isArray(cached.items)) { state.payload = cached; state.signature = payloadSignature(cached); renderAll(); } } catch (_error) { /* cache is optional */ }
    try {
      await Promise.race([window.CMHKAuth?.ready, new Promise((_, reject) => setTimeout(() => reject(new Error("auth timeout")), 4000))]);
      if (!window.CMHKAuth?.hasModule("competitor")) return;
      await refreshData();
      if (!state.payload) throw new Error("intelligence unavailable");
    } catch (_error) { if (!state.payload) panel.innerHTML = '<div class="intelligence-map-loading">暂时无法读取情报图谱，请稍后刷新。</div>'; }
  }

  function schedulePolling() {
    window.clearTimeout(state.pollTimer); state.pollTimer = null;
    if (document.hidden || panel.hidden) return;
    state.pollTimer = window.setTimeout(async () => { await refreshData(); schedulePolling(); }, activeRefreshIntervalMs);
  }
  window.addEventListener("workspace-tab-change", (event) => {
    if (event.detail?.tab !== "intelligence-map") { window.clearTimeout(state.pollTimer); state.pollTimer = null; return; }
    if (Date.now() - state.lastRefreshAt >= activeRefreshIntervalMs) refreshData();
    schedulePolling(); scheduleVisualLayout();
  });
  window.addEventListener("resize", scheduleVisualLayout);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && !panel.hidden && Date.now() - state.lastRefreshAt >= activeRefreshIntervalMs) refreshData();
    schedulePolling();
  });
  initialize();
  schedulePolling();
})();
