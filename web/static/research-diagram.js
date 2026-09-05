/* Six-agent diagram: the server supplies the same assignments execution uses. */
(() => {
  "use strict";
  const status = (value) => ({
    completed: { key: "healthy", label: "已完成" }, running: { key: "running", label: "运行中" },
    partial: { key: "warning", label: "部分完成" }, error: { key: "critical", label: "执行失败" },
    pending: { key: "unknown", label: "待执行" },
  })[value] || { key: "unknown", label: "无记录" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const terms = { verified: "已核验", missing: "本轮未找到", conflict: "待复核", not_applicable: "不适用", error: "执行失败" };
  // Presentation only: keep persisted assignments unchanged for same-run resume.
  const childTitle = (title) => String(title || "").replace(/研究 Agent$/, "研究子 Agent");
  const link = (url) => /^https?:\/\//i.test(String(url || "")) ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(url)}</a>` : esc(url);
  function build(legacy, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : { plan: snapshot?.plan || [] };
    const run = data.run;
    const plan = data.plan || [];
    const agents = data.agents || [];
    const nodes = legacy.nodes.filter((n) => ["strategic", "news-search", "news-ai", "news-dedupe", "news-output", "news-selection-agent", "app-result", "weekly-result"].includes(n.key));
    const newsKeys = new Set(nodes.map((node) => node.key));
    const edges = legacy.edges.filter(([from, to, , kind]) => newsKeys.has(from) && newsKeys.has(to) && !kind.startsWith("feedback"));
    const add = (key, label, position, value, unit, purpose, details, health, extra = {}) => {
      const node = { key, label, position, value, unit, purpose, details, health, note: details[0],
        variant: "research-step", research: true, evidence: run?.run_id || "所选日期暂无六Agent研究任务", ...extra };
      nodes.push(node);
      return node;
    };
    // Align the supervisor with the midpoint of the six equal-width worker cards.
    const dispatchX = 20 + Math.max(0, plan.length - 1) * 300 / 2;
    add("research-dispatch", "03:00 Supervisor · Agent 任务分配", [dispatchX, 365], plan.length || "—", "个研究 Agent", "规则型 Supervisor 主控：按公司与指标目录分配六个研究 Agent 的任务", [
      "这是同一个规则型 Supervisor 主控的任务分配阶段；不是额外调用大模型的研究 Agent",
      "香港、内地、亚太、欧洲、美洲与中东、全球云厂商六组并行研究",
      "公司是任务条目，每家公司只归属一个研究 Agent；所有预期指标必须返回处理结果",
      "输入：公司目录、需要更新的指标和当前日期；输出：六份明确的研究任务",
      "每天03:00启动；各 Agent 的网页搜索与原文读取在同一轮内完成",
      "执行基础：Deep Agents 0.7.13 开源 harness；关闭默认嵌套子 Agent，研究 Agent 最多六个",
    ], status(run?.status === "running" ? "completed" : run?.status), { note: "规则型主控：每日分配六组研究任务" });
    plan.forEach((task, index) => {
      const actual = agents.find((agent) => agent.key === task.key);
      const reports = actual?.reports || [];
      const done = reports.filter((report) => report.status === "completed").length;
      add(`research-${task.key}`, childTitle(task.title), [20 + index * 300, 560], run ? `${done}/${task.companies.length}` : "—", "家公司完成研究", task.purpose, [
        `负责 ${task.companies.length} 家公司：${task.companies.join("、")}`,
        "逐公司读取指标任务，联网搜索相关披露，去重后读取官方网页或财报",
        "提交主体、指标、期间、数值、单位、原文地址、引用摘录和处理结果",
        "缺失指标明确返回本轮未找到；有冲突的值交汇总步骤标记待复核",
        "每次只提交一个指标，已完成结果立即保存；截断响应禁止入库，传输重试不触发重新抓取",
      ], status(actual?.status || (run?.status === "running" ? "running" : undefined)), { assignment: task, agent: actual, variant: "research-agent" });
      edges.push(["research-dispatch", `research-${task.key}`, "", "research-fan", {}]);
      edges.push([`research-${task.key}`, "research-merge", "", "research-join", {}]);
    });
    add("research-merge", "Supervisor · Agent 结果汇总", [20, 820], run?.tasks ?? "—", "项指标结果", "规则型 Supervisor 主控：收齐六个 Agent 的结果，统一校验来源与字段并合并", [
      "这是同一个规则型 Supervisor 主控的结果汇总阶段，与03:00任务分配共用一轮运行编号；不是新增一个研究 Agent",
      "检查公司与指标覆盖、重复项、原文摘录、数值、期间和单位",
      "有原文支持的数据进入更新批次；缺失、冲突和执行失败分别记录",
      "输入：六个研究 Agent 的报告；输出：本轮可更新事实及待复核清单",
      "流程单向结束；下一次定时研究再检查未找到的数据",
    ], status(run?.status === "running" ? undefined : run?.status));
    add("research-update", "四库数据更新", [660, 820], run?.publication?.database_updated ? run.accepted : "—", "条本轮通过数据", "统一写入本地、国际、内地运营商和全球云厂商四库", [
      "由一个更新步骤处理六个 Agent 提交的数据，防止多个研究任务同时覆盖文件",
      "先写入四库审核事实层；主表继续执行既有的字段、期间和核验等级门禁，不强制覆盖KPI",
      "分别记录审核事实发布、主表增量晋升、文件变化和界面数值变化，不能把四者混为一谈",
      "输入：本轮审核通过事实；输出：四库更新结果与前后变化记录",
    ], status(run?.publication?.database_updated ? "completed" : run?.publication?.status), { publication: run?.publication });
    add("research-publish", "AI 洞察生成与页面发布", [1320, 820], run?.publication?.insights ?? "—", "项洞察", "使用四库最新数据生成洞察，更新页面并读取发布结果", [
      "读取更新后的四库数据，生成分库分析和跨库洞察",
      "校验洞察引用的数据与主体，更新主页数据和公开页面",
      "发布后读取实际版本，只有成功读取后才记录为发布完成",
      "输入：四库已发布数据；输出：AI洞察、页面版本及发布结果",
    ], status(run?.publication?.status), { publication: run?.publication });
    edges.push(["research-merge", "research-update", "可更新事实", "cyan", {}], ["research-update", "research-publish", "四库最新数据", "cyan", {}]);
    return { nodes, edges, canvasSize: [1850, 1040], laneLabels: [
      { label: "战略新闻采集与初筛", position: [18, 22] },
      { label: "六 Agent 并行研究与四库更新", position: [18, 325] },
    ], groups: [] };
  }
  function detail(node, snapshot, date) {
    const run = snapshot?.date === date ? snapshot.run : null;
    const agent = node.agent;
    const agents = agent ? [agent] : (snapshot?.date === date ? snapshot.agents || [] : []);
    const events = (snapshot?.date === date ? snapshot.events || [] : []).filter((event) => !node.assignment || event.agent_id === node.assignment.key);
    const field = (name, value) => `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`;
    const records = agents.flatMap((a) => (a.reports || []).map((report) => ({ a, report })));
    const resultLabel = !run ? "尚无本轮结果" : run.status === "running"
      ? `研究仍在进行，已保存 ${records.reduce((count, { report }) => count + (report.items || []).length, 0)} 项指标记录；最终通过数量待汇总校验`
      : `已核验 ${run.accepted ?? "未提供"} 项，待复核或缺失 ${run.review ?? "未提供"} 项`;
    return `<header><div><span>${esc(date)} · 节点详情</span><h2>${esc(node.label)}</h2><p>${esc(node.purpose)}</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header>
      <div class="news-lineage-dialog-content research-node-detail">
      <section class="news-lineage-dialog-section"><header><h3>这个节点如何处理</h3></header><ol>${node.details.map((text) => `<li>${esc(text)}</li>`).join("")}</ol></section>
      <section class="news-lineage-dialog-section"><header><h3>本轮运行</h3></header><dl>${field("运行编号", esc(run?.run_id || "所选日期没有六Agent任务记录"))}${field("开始时间", esc(run?.started_at || "—"))}${field("结束时间", esc(run?.completed_at || "—"))}${field("本轮结果", esc(resultLabel))}</dl></section>
      ${node.publication ? `<section class="news-lineage-dialog-section"><header><h3>四库及页面交付明细</h3></header><pre>${esc(JSON.stringify(node.publication, null, 2))}</pre></section>` : ""}
      <section class="news-lineage-dialog-section"><header><h3>逐公司、逐指标处理结果</h3><span>${records.length} 份公司报告</span></header>
      ${records.map(({ a, report }) => `<details class="research-company" ${agent ? "open" : ""}><summary>${esc(report.company)} · ${esc(a.title)} · ${report.items?.length || 0} 项指标</summary>
        ${(report.items || []).map((item) => `<article class="research-metric"><h4>${esc(item.metric)} <small>${esc(terms[item.status] || item.status)}</small></h4><dl>${field("记录值", esc(item.value || "无可更新值"))}${field("期间与单位", esc([item.period, item.unit].filter(Boolean).join(" · ") || "—"))}${field("处理说明", esc(item.reason || "—"))}${field("原文", link(item.source_url || "—"))}${field("原文摘录", esc(item.quote || "—"))}${field("期间及单位上下文", esc(item.context_quote || "—"))}${field("披露主体依据", esc(item.entity_quote || "主体见原文摘录"))}${field("来源内容哈希", esc(item.evidence_hash || "—"))}</dl></article>`).join("")}
        <details><summary>全部检索与网页读取记录</summary>${(report.searches || []).map((search) => `<article><strong>${esc(search.metric)}</strong><p>检索：${esc(search.query)} · ${esc(search.provider)}</p><ul>${(search.results || []).map((r) => `<li>${link(r.url)}<p>${esc(r.title)} · ${esc(r.snippet)}</p></li>`).join("")}</ul></article>`).join("")}
        ${Object.entries(report.pages || {}).map(([url, page]) => `<p>${link(url)} · HTTP ${esc(page.http_status)} · ${page.opened ? "已读取" : "读取失败"} ${esc(page.blocked_reason || "")}</p>`).join("")}</details></details>`).join("") || "<p>该节点的实际处理记录将在任务运行后显示。</p>"}</section>
      <section class="news-lineage-dialog-section"><header><h3>执行时间线</h3><span>${events.length} 条记录</span></header><ol>${events.map((event) => `<li><time>${esc(event.ts)}</time> · ${esc(event.message)}<details><summary>${esc(event.phase)} · 查看原始处理记录</summary><pre>${esc(JSON.stringify(event.data || {}, null, 2))}</pre></details></li>`).join("") || "<li>暂无执行记录。</li>"}</ol></section></div>`;
  }
  window.CmhkResearchDiagram = { build, detail };
})();
