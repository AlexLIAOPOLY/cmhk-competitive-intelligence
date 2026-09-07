/* Six-agent diagram: the server supplies the same assignments execution uses. */
(() => {
  "use strict";
  const status = (value) => ({
    completed: { key: "healthy", label: "已完成" }, running: { key: "running", label: "运行中" },
    partial: { key: "warning", label: "部分完成" }, error: { key: "critical", label: "执行失败" },
    pending: { key: "unknown", label: "待执行" },
  })[value] || { key: "unknown", label: "无记录" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const fallbackNote = (publication) => {
    const model = publication?.model_analysis;
    if (publication?.result_status !== "completed_with_fallback" && !model?.fallback_used && !model?.discovery_fallback_used) return "";
    if (!model || !Number.isFinite(model.focuses_passed) || !Number.isFinite(model.discoveries_passed)) return "部分洞察使用规则回退；详见发布记录";
    const fallback = (model.fallback_used ? model.focuses_passed : 0) + (model.discovery_fallback_used ? model.discoveries_passed : 0);
    return `模型生成 ${model.focuses_passed + model.discoveries_passed - fallback} 项 · 规则回退 ${fallback} 项`;
  };
  const terms = { no_update: "库内已有", verified: "新增更新", missing: "执行失败", conflict: "执行失败", not_applicable: "执行失败", error: "执行失败" };
  const reportTerms = { completed: "研究已完成", running: "研究中", partial: "部分完成", error: "执行失败", pending: "待执行" };
  // Presentation only: keep persisted assignments unchanged for same-run resume.
  const childTitle = (title) => String(title || "").replace(/研究 Agent$/, "研究子 Agent");
  const link = (url) => /^https?:\/\//i.test(String(url || "")) ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a>` : esc(url);
  const reportCoverage = (report) => {
    const items = Array.isArray(report?.items) ? report.items : [];
    const expected = new Set((Array.isArray(report?.metrics) ? report.metrics : []).map(String).filter(Boolean));
    items.forEach((item) => { if (item?.metric) expected.add(String(item.metric)); });
    items.filter((item) => item?.status === "not_applicable").forEach((item) => expected.delete(String(item.metric || "")));
    const collected = new Set(items.filter((item) => item?.status === "verified" && item.metric).map((item) => String(item.metric)));
    return { collected: collected.size, total: expected.size };
  };
  const reportsCoverage = (reports) => (reports || []).reduce((sum, report) => {
    const current = reportCoverage(report);
    return { collected: sum.collected + current.collected, total: sum.total + current.total };
  }, { collected: 0, total: 0 });
  const isIncremental = (run) => run?.research_policy === "latest_disclosure_incremental_v1";
  const itemLabel = (value) => terms[value] || "执行失败";
  const resultCounts = (reports) => {
    const items = (reports || []).flatMap((report) => report.items || []);
    return `库内已有 ${items.filter((item) => item.status === "no_update").length} 项 · 新增更新 ${items.filter((item) => item.status === "verified").length} 项 · 执行失败 ${items.filter((item) => !["verified", "no_update"].includes(item.status)).length} 项`;
  };
  const researchHealth = (actual, run) => {
    const execution = actual?.status || (run?.status === "running" ? "running" : undefined);
    if (execution !== "completed") return status(execution);
    const reports = actual?.reports || [];
    if (reports.some((report) => report.status === "error" || (report.items || []).some((item) => item.status === "error"))) return status("error");
    if (isIncremental(run)) {
      const needsReview = reports.some((report) => (report.items || []).some((item) => !["verified", "no_update"].includes(item.status)));
      return { key: needsReview ? "warning" : "healthy", label: needsReview ? "执行失败" : "已完成" };
    }
    return { key: "healthy", label: "历史核验记录" };
  };
  function build(legacy, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : { plan: snapshot?.plan || [] };
    const run = data.run;
    const incremental = isIncremental(run);
    const plan = data.plan || [];
    const agents = data.agents || [];
    const canvasWidth = 2366;
    const researchInset = 20;
    const researchCardWidth = 250;
    const researchSpan = canvasWidth - researchInset * 2 - researchCardWidth;
    const researchX = (index) => plan.length <= 1
      ? Math.round((canvasWidth - researchCardWidth) / 2)
      : Math.round(researchInset + index * researchSpan / (plan.length - 1));
    const newsColumns = ["strategic", "news-search", "news-ai", "news-dedupe", "news-output", "news-selection-agent", "app-result", "weekly-result"];
    // A 120px connector run between 230px cards also leaves room for the fork.
    const nodes = legacy.nodes.filter((n) => newsColumns.includes(n.key)).map((node) => ({
      ...node, position: [18 + Math.min(newsColumns.indexOf(node.key), 6) * 350, node.position[1]],
    }));
    const newsKeys = new Set(nodes.map((node) => node.key));
    const edges = legacy.edges.filter(([from, to, , kind]) => newsKeys.has(from) && newsKeys.has(to) && !kind.startsWith("feedback"));
    const add = (key, label, position, value, unit, purpose, details, health, extra = {}) => {
      const node = { key, label, position, value, unit, purpose, details, health, note: details[0],
        variant: "research-step", research: true, evidence: run?.run_id || "所选日期暂无六Agent研究任务", ...extra };
      nodes.push(node);
      return node;
    };
    // Spread the research lane across the same full canvas width as the news lane.
    const dispatchX = plan.length ? Math.round((researchX(0) + researchX(plan.length - 1)) / 2) : Math.round((canvasWidth - researchCardWidth) / 2);
    add("research-dispatch", "03:00 Supervisor · Agent 任务分配", [dispatchX, 330], plan.length || "—", "个研究 Agent", "规则型 Supervisor 主控：以库内数据为可信基线，分配六组最新披露搜索任务", [
      "这是同一个规则型 Supervisor 主控的任务分配阶段；不是额外调用大模型的研究 Agent",
      "香港、内地、亚太、欧洲、美洲与中东、全球云厂商六组并行研究",
      "已有数据库默认正确；任务目标是搜索尚未入库的新披露，保留库内同期间与更新期间数据",
      "输入：公司、指标、库内最新期间与当前日期；输出：六份最新披露搜索任务",
      "每天03:00启动；各 Agent 的网页搜索与原文读取在同一轮内完成",
      "执行基础：Deep Agents 0.7.13 开源 harness；关闭默认嵌套子 Agent，研究 Agent 最多六个",
    ], status(run?.status === "running" ? "completed" : run?.status), { note: "规则型主控：每日分配六组研究任务" });
    plan.forEach((task, index) => {
      const actual = agents.find((agent) => agent.key === task.key);
      const reports = actual?.reports || [];
      const done = reports.filter((report) => report.status === "completed").length;
      add(`research-${task.key}`, childTitle(task.title), [researchX(index), 560], incremental && actual && (reports.some((report) => (report.items || []).length) || actual.status === "completed") ? reports.flatMap((report) => report.items || []).filter((item) => item.status === "verified").length : "—", run && !incremental ? "新增披露未统计" : "项新增更新", "查找负责公司的最新披露，与库内可信基线比较，仅提交新期间或新指标", [
        `负责 ${task.companies.length} 家公司：${task.companies.join("、")}`,
        "先读取库内最新期间，再查最新业绩公告；继续打开官方公告入口中关联的报告原文",
        "提交主体、指标、期间、数值、单位、原文地址、引用摘录和处理结果",
        "结果只分库内已有、新增更新、执行失败；找不到可靠内容时写明失败原因",
        "每次只提交一个指标，已完成结果立即保存；截断响应禁止入库，传输重试不触发重新抓取",
      ], researchHealth(actual, run), { assignment: task, agent: actual, variant: "research-agent",
        note: `${run && !incremental ? "旧流程已处理" : "已完成搜索"} ${done}/${task.companies.length} 家公司${incremental && actual ? ` · ${resultCounts(reports)}` : ""} · 负责公司：${task.companies.join("、")}` });
      edges.push(["research-dispatch", `research-${task.key}`, "", "research-fan", {}]);
      edges.push([`research-${task.key}`, "research-merge", "", "research-join", {}]);
    });
    add("research-merge", "最终审核 Agent · 联网核对", [20, 820], run?.tasks ?? "—", "项指标结果", "核对各公司最新指标；对未找到或失败的项目继续联网补查，一个可信原文即可", [
      "比较六个研究 Agent 的新披露与库内可信基线，排除同期间已有数据和更旧的披露",
      "检查公司与指标覆盖、重复项、原文摘录、数值、期间和单位",
      "有可信原文支持的新数据进入更新批次；库内已有则保留，无法核实则记执行失败并说明原因",
      "输入：六个研究 Agent 的报告；输出：本轮可更新字段及待复核清单",
      "本轮结束后，下一次定时任务继续搜索最新披露；已有数据保持可信",
    ], status(run?.final_review?.status || (run?.status === "running" ? undefined : run?.status)), {
      agent: data.final_reviewer || null,
      assignment: { key: "final-review" },
      note: data.final_reviewer ? resultCounts(data.final_reviewer.reports || []) : "收齐研究结果后，继续联网补查并核对",
    });
    add("research-update", "四库数据更新", [Math.round((canvasWidth - researchCardWidth) / 2), 820], run?.publication?.database_updated ? run.accepted : incremental && run?.publication?.result_status === "no_new_disclosures" ? 0 : "—", incremental ? "项新增更新" : "条历史核验通过数据", "统一写入本地、国际、内地运营商和全球云厂商四库", [
      "由一个更新步骤处理六个 Agent 提交的数据，防止多个研究任务同时覆盖文件",
      "仅把有来源支持的新期间或新指标写入四库；已有同期间数据作为可信基线保留",
      "分别记录已审核字段写入、主表增量更新、文件变化和界面数值变化，不能把四者混为一谈",
      "输入：本轮审核通过字段；输出：四库更新结果与前后变化记录",
    ], status(run?.publication?.database_updated ? "completed" : run?.publication?.status), { publication: run?.publication });
    add("research-publish", "AI 洞察生成与页面发布", [canvasWidth - researchInset - researchCardWidth, 820], run?.publication?.insights ?? "—", "项洞察", "使用四库最新数据生成洞察，更新页面并读取发布结果", [
      "读取更新后的四库数据，生成分库分析和跨库洞察",
      "校验洞察引用的数据与主体，更新主页数据和公开页面",
      "发布后读取实际版本，只有成功读取后才记录为发布完成",
      "输入：四库已发布数据；输出：AI洞察、页面版本及发布结果",
    ], status(run?.publication?.status), { publication: run?.publication });
    edges.push(["research-merge", "research-update", "可更新字段", "cyan", {}], ["research-update", "research-publish", "四库最新数据", "cyan", {}]);
    nodes.filter((node) => node.research).forEach((node) => {
      if (node.key === "research-publish" && run?.publication?.status === "completed" && fallbackNote(run.publication)) {
        node.health = { key: "warning", label: "含规则回退" };
        node.note = `${fallbackNote(run.publication)}；页面发布状态：${run.publication.pages?.status || "未记录"}`;
      }
      if (run && !incremental) {
        node.note = `历史运行 · ${node.note}`;
        if (node.health.key === "healthy") node.health = { key: "healthy", label: "历史记录" };
      }
      if (incremental && ["research-update", "research-publish"].includes(node.key) && run.publication?.result_status === "no_new_disclosures") {
        node.health = { key: "healthy", label: node.key === "research-update" ? "无新增·保留原库" : "无新增·沿用页面" };
        node.note = "本轮未发现可写入的新披露，保留现有数据库和页面，不重复生成洞察";
      } else if (incremental && ["research-update", "research-publish"].includes(node.key) && run.publication?.result_status === "needs_review") {
        node.health = { key: "warning", label: "执行失败" };
        node.note = "本轮未形成可写入的新数据；执行失败原因见结果明细";
      }
    });
    return { nodes, edges, canvasSize: [canvasWidth, 1040], laneLabels: [
      { label: "战略新闻采集与初筛", position: [18, 22] },
      { label: "六 Agent 最新披露搜索与四库增量更新", position: [18, 325] },
    ], groups: [] };
  }
  const domainNames = { local: "本地运营商", international: "国际运营商", mainland: "内地运营商", cloud: "全球云厂商", cross: "跨库研判" };
  function actualList(node, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : {};
    const run = data.run;
    const section = (title, note, rows) => `<section class="news-lineage-dialog-section research-actual-list"><header><h3>${esc(title)}</h3><span>${rows.length} 条明细</span></header><p>${esc(note)}</p><div class="news-lineage-preview-scroll" role="region" aria-label="本节点逐条明细" tabindex="0">${rows.join("") || "<p>本轮未保存可展示明细；不以其他日期的数据补齐。</p>"}</div></section>`;
    if (node.key === "research-dispatch") return section("本轮分配给哪六个研究 Agent", run ? "按公司分组查找最新披露；已保存数据作为比较基线。" : "尚未执行；以下是计划任务", (run?.plan || data.plan || []).map((task, i) => `<article><strong>${i + 1}. ${esc(childTitle(task.title))}</strong><p>${esc(task.companies.join("、"))}</p><p>${esc(task.purpose)}</p></article>`));
    if (node.key === "research-publish") {
      const items = data.insight_items || [];
      const publication = run?.publication;
      return section(`本轮 ${publication?.insights ?? "—"} 项洞察具体内容`, `${fallbackNote(publication)}${fallbackNote(publication) ? "。" : ""}已读取 ${items.length} 项同一研究运行的明细。页面发布：${publication?.pages?.status || "未记录"}`, items.map((item, i) => `<article><strong>${i + 1}. ${esc(item.headline || item.title || item.id || "跨库洞察")}</strong><p>${esc(domainNames[item.domain] || item.domain)} · ${esc(item.analysis || item.detail || item.insight || "未保存正文")}</p>${item.risk ? `<p>口径与风险：${esc(item.risk)}</p>` : ""}<p>${(item.source_urls || []).map(link).join("<br>")}</p></article>`));
    }
    const reports = (node.agent ? [node.agent] : data.agents || []).flatMap((a) => (a.reports || []).flatMap((r) => (r.items || []).map((item) => ({ ...item, company: r.company }))));
    const update = node.key === "research-update";
    const items = update ? data.accepted_items || [] : node.key === "research-merge" ? data.result_items || reports : reports;
    const selected = node.agent ? [...items].sort((a, b) => Number(b.status === "verified") - Number(a.status === "verified")) : items;
    const title = update ? `${isIncremental(run) ? "新增更新" : "历史核验通过"}的 ${run?.accepted ?? "—"} 项数据是哪几项` : node.agent ? `${node.label}：${isIncremental(run) ? "逐公司、逐指标结果" : "历史核验结果（新增未统计）"}` : `本轮 ${run?.tasks ?? "—"} 项指标结果清单`;
    const note = update ? `实际读取 ${items.length} 项审核通过记录；本轮页面数值变化 ${run?.publication?.changes?.changed ?? "未记录"} 项。通过审核、写入事实层与主表数值变化分别记录。` : `只列本节点的公司与指标；${isIncremental(run) ? "只显示库内已有、新增更新、执行失败；失败原因逐项写明" : "历史核验结果不代表数据库缺失，也不能换算成新增披露数量"}；共 ${items.length} 项处理记录。`;
    return section(title, note, selected.map((raw, i) => { const existing = (raw.research_status || raw.status) === "no_update"; const item = existing && raw.latest_baseline ? { ...raw, ...raw.latest_baseline, baseline: [raw.latest_baseline] } : { ...raw, baseline: raw.latest_baseline ? [raw.latest_baseline] : [] }; return `<article><strong>${i + 1}. ${esc(item.company)} · ${esc(item.metric)}</strong><p>${esc(item.value === "" || item.value == null ? "未取得可更新值" : item.value)} · ${esc(item.period || "期间未记录")} · ${esc(item.unit || "单位未记录")} · ${esc(itemLabel(item.research_status || item.status || (item.decision === "accepted" ? "verified" : "conflict"), isIncremental(run)))}</p><p>${esc(item.reason || (item.reasons || []).join("；"))}</p>${item.baseline?.length ? `<p>库内基线：${item.baseline.map((old) => esc(`${old.period} · ${old.value} ${old.unit || ""}`)).join("；")}</p>` : ""}<p>${(item.sources || [item.source_url]).filter(Boolean).map((source) => link(typeof source === "string" ? source : source.url)).join("<br>")}</p></article>`; }));
  }
  function searchHistory(node, agents, events) {
    if (!node.assignment) return "";
    const searches = events.filter((event) => event.phase === "search" && event.data?.query)
      .map((event) => ({ ...event.data, ts: event.ts }));
    // Checkpoints repeat the same searches as the trace. Match occurrences,
    // preserving genuine retries and searches before a company checkpoint exists.
    const identity = (search) => JSON.stringify([search.company, search.metric, search.query, search.provider]);
    const remaining = new Map();
    searches.forEach((search) => remaining.set(identity(search), (remaining.get(identity(search)) || 0) + 1));
    agents.filter((agent) => agent.key === node.assignment.key).forEach((agent) => (agent.reports || []).forEach((report) => (report.searches || []).forEach((search) => {
      const row = { ...search, company: search.company || report.company };
      const key = identity(row);
      if (remaining.get(key)) remaining.set(key, remaining.get(key) - 1);
      else searches.push(row);
    })));
    const resultCount = searches.reduce((count, search) => count + (search.results || []).length, 0);
    return `<section class="news-lineage-dialog-section research-actual-list research-search-history"><header><h3>AI 搜索关键词与返回结果</h3><span>已记录 ${searches.length} 次搜索 · ${resultCount} 条返回结果</span></header>
      <p>逐次展示实际提交给搜索引擎的完整关键词及返回结果；搜索结果尚未经过原文核验。</p>
      <div class="news-lineage-preview-scroll" role="region" aria-label="逐次搜索关键词与返回结果" tabindex="0">${searches.map((search, index) => `<article class="research-search-record"><strong>${index + 1}. ${esc(search.company || "公司未记录")} · ${esc(search.metric || "最新披露")}</strong>
        <p class="research-search-query">搜索关键词：${esc(search.query)}</p><details class="news-lineage-technical"><summary>搜索执行信息</summary><p>${esc(search.ts || "搜索时间未记录")} · ${esc(search.provider || "未记录")}</p></details>
        ${(search.results || []).length ? `<div class="research-search-results"><strong>本次返回 ${search.results.length} 条结果</strong><ol>${search.results.map((result) => `<li><strong>${esc(result.title || "标题未记录")}</strong><p>${link(result.url)}</p><p>${esc(result.snippet || "摘要未记录")}</p></li>`).join("")}</ol></div>` : "<p>本次未返回搜索结果；不能据此判断没有相关披露。</p>"}</article>`).join("") || "<p>本节点尚无已保存的搜索记录；关键词和结果将在搜索完成后显示。</p>"}</div></section>`;
  }
  function companyCoverageOverview(node, run) {
    if (!node.agent) return "";
    const reports = node.agent.reports || [];
    const coverage = reportsCoverage(reports);
    if (isIncremental(run)) return `<section class="news-lineage-dialog-section"><header><h3>各公司最新披露搜索结果</h3></header>${reports.map((report) => `<article><strong>${esc(report.company)}</strong><p>${resultCounts([report])}</p></article>`).join("")}</section>`;
    return `<section class="news-lineage-dialog-section research-actual-list"><header><h3>分公司历史核验记录</h3><span>历史核验通过 ${coverage.collected}/${coverage.total} 项</span></header><p>以下仅为旧流程核验记录；不代表原库缺失，新增披露数量未统计。</p><div class="news-lineage-preview-scroll" role="region" aria-label="分公司历史核验记录" tabindex="0">${reports.map((report, index) => { const current = reportCoverage(report); return `<article><strong>${index + 1}. ${esc(report.company)} · 历史核验通过 ${current.collected}/${current.total} 项</strong><p>${esc(reportTerms[report.status] || report.status || "未记录状态")}</p></article>`; }).join("") || "<p>暂无分公司研究记录。</p>"}</div></section>`;
  }
  function detail(node, snapshot, date) {
    const run = snapshot?.date === date ? snapshot.run : null;
    const agent = node.agent;
    const agents = agent ? [agent] : (snapshot?.date === date ? snapshot.agents || [] : []);
    const events = (snapshot?.date === date ? snapshot.events || [] : []).filter((event) => !node.assignment || event.agent_id === node.assignment.key);
    const field = (name, value) => `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`;
    const records = agents.flatMap((a) => (a.reports || []).map((report) => ({ a, report })));
    const coverage = reportsCoverage(records.map(({ report }) => report));
    const resultLabel = !run ? "尚无本轮结果" : run.status === "running"
      ? `研究仍在进行，已保存 ${records.reduce((count, { report }) => count + (report.items || []).length, 0)} 项指标记录；最终通过数量待汇总校验`
      : isIncremental(run) ? resultCounts((snapshot.agents || []).flatMap((a) => a.reports || [])) : `已核验 ${run.accepted ?? "未提供"} 项，待复核或缺失 ${run.review ?? "未提供"} 项（历史运行未区分新增与重复数据）`;
    return `<header><div><span>${esc(date)} · ${run && !isIncremental(run) ? "历史运行（新增披露未统计）" : "最新披露增量更新"} · 节点详情</span><h2>${esc(node.label)}</h2><p>${esc(node.purpose)}</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header>
      <div class="news-lineage-dialog-content research-node-detail">
      <section class="news-lineage-dialog-section research-outcome"><header><h3>本节点结果</h3></header><p>${esc(node.agent ? resultCounts(node.agent.reports || []) : node.key === "research-publish" ? `${fallbackNote(run?.publication) || "模型结果未记录"}；页面${run?.publication?.pages?.status === "published" ? "已发布" : "发布状态：" + (run?.publication?.pages?.status || "未记录")}` : node.key === "research-update" ? `新增更新 ${run?.accepted ?? "未记录"} 项；页面指标数值变化 ${run?.publication?.changes?.baseline_available === true ? run.publication.changes.changed : "未记录"} 项。${run?.publication?.database_updated ? "已执行数据写入。" : "尚未确认数据写入。"}` : resultLabel)}</p></section>
      ${actualList(node, snapshot, date)}
      ${searchHistory(node, agents, events)}
      <details class="news-lineage-technical"><summary>运行日志、核验依据与技术详情</summary>
      ${companyCoverageOverview(node, run)}
      <section class="news-lineage-dialog-section"><header><h3>这个节点如何处理</h3></header><ol>${node.details.map((text) => `<li>${esc(text)}</li>`).join("")}</ol></section>
      <section class="news-lineage-dialog-section"><header><h3>本轮运行</h3></header><dl>${field("运行编号", esc(run?.run_id || "所选日期没有六Agent任务记录"))}${field("开始时间", esc(run?.started_at || "—"))}${field("结束时间", esc(run?.completed_at || "—"))}${field("本轮结果", esc(resultLabel))}</dl></section>
      ${node.publication ? `<section class="news-lineage-dialog-section"><header><h3>四库及页面交付明细</h3></header><pre>${esc(JSON.stringify(node.publication, null, 2))}</pre></section>` : ""}
      <section class="news-lineage-dialog-section"><header><h3>逐公司、逐指标处理结果</h3><span>${records.length} 份公司报告 · ${isIncremental(run) ? resultCounts(records.map(({ report }) => report)) : `历史核验通过 ${coverage.collected}/${coverage.total} 项`}</span></header>
      ${records.map(({ a, report }) => { const companyCoverage = reportCoverage(report); return `<details class="research-company"><summary>${esc(report.company)} · ${isIncremental(run) ? resultCounts([report]) : `历史核验通过 ${companyCoverage.collected}/${companyCoverage.total} 项`} · ${esc(reportTerms[report.status] || report.status || "未记录状态")}</summary>
        ${(report.items || []).map((item) => `<article class="research-metric"><h4>${esc(item.metric)} <small>${esc(itemLabel(item.status, isIncremental(run)))}</small></h4><dl>${field("记录值", esc(item.value ?? "无可更新值"))}${field("期间与单位", esc([item.period, item.unit].filter(Boolean).join(" · ") || "—"))}${field("处理说明", esc(item.reason || "—"))}${field("原文", link(item.source_url || "—"))}${field("原文摘录", esc(item.quote || "—"))}${field("期间及单位上下文", esc(item.context_quote || "—"))}${field("披露主体依据", esc(item.entity_quote || "主体见原文摘录"))}${field("来源内容哈希", esc(item.evidence_hash || "—"))}</dl></article>`).join("")}
        <details><summary>全部检索与网页读取记录</summary>${(report.searches || []).map((search) => `<article><strong>${esc(search.metric)}</strong><p>检索：${esc(search.query)} · ${esc(search.provider)}</p><ul>${(search.results || []).map((r) => `<li>${link(r.url)}<p>${esc(r.title)} · ${esc(r.snippet)}</p></li>`).join("")}</ul></article>`).join("")}
        ${Object.entries(report.pages || {}).map(([url, page]) => `<p>${link(url)} · HTTP ${esc(page.http_status)} · ${page.opened ? "已读取" : "读取失败"} ${esc(page.blocked_reason || "")}</p>`).join("")}</details></details>`; }).join("") || "<p>该节点的实际处理记录将在任务运行后显示。</p>"}</section>
      <section class="news-lineage-dialog-section"><header><h3>执行时间线</h3><span>${events.length} 条记录</span></header><ol>${events.map((event) => `<li><time>${esc(event.ts)}</time> · ${esc(event.message)}<details><summary>${esc(event.phase)} · 查看原始处理记录</summary><pre>${esc(JSON.stringify(event.data || {}, null, 2))}</pre></details></li>`).join("") || "<li>暂无执行记录。</li>"}</ol></section></details></div>`;
  }
  window.CmhkResearchDiagram = { build, detail };
})();
