/* Six-agent diagram: the server supplies the same assignments execution uses. */
(() => {
  "use strict";
  const status = (value) => ({
    completed: { key: "healthy", label: "已完成" }, running: { key: "running", label: "运行中" },
    partial: { key: "warning", label: "部分完成" }, error: { key: "critical", label: "执行失败" },
    cancelled: { key: "warning", label: "已中止" },
    pending: { key: "unknown", label: "待执行" },
  })[value] || { key: "unknown", label: "无记录" };
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const plainText = (value) => String(value ?? "")
    .replace(/事实层|事实/g, "字段数据")
    .replace(/可信基线|基线/g, "已有数据")
    .replace(/最新披露/g, "最新数据")
    .replace(/新披露/g, "新数据")
    .replace(/披露期间/g, "报告期")
    .replace(/披露/g, "公布信息")
    .replace(/核验|复核/g, "核对")
    .replace(/主体/g, "公司")
    .replace(/合规终态|终态/g, "处理结果")
    .replace(/门禁/g, "审核")
    .replace(/增量更新/g, "新增或更新")
    .replace(/规则回退/g, "非AI历史结果");
  const pageState = (value) => ({published:"已发布", completed:"已完成", running:"更新中", pending:"等待更新", error:"更新失败", failed:"更新失败", skipped:"未更新", blocked:"暂未发布", deferred:"稍后更新"})[value] || "未记录";
  const fallbackNote = (publication) => {
    const model = publication?.model_analysis;
    if (publication?.result_status !== "completed_with_fallback" && !model?.fallback_used && !model?.discovery_fallback_used) return "";
    if (!model || !Number.isFinite(model.focuses_passed) || !Number.isFinite(model.discoveries_passed)) return "AI 生成未全部完成；详见失败记录";
    const fallback = (model.fallback_used ? model.focuses_passed : 0) + (model.discovery_fallback_used ? model.discoveries_passed : 0);
    return `AI 已生成 ${model.focuses_passed + model.discoveries_passed - fallback} 项 · AI 未生成 ${fallback} 项`;
  };
  const aiGeneratedCount = (publication) => {
    const model = publication?.model_analysis;
    if (!model) return "—";
    if (model.ok === false) return 0;
    if (Number.isFinite(model.focuses_passed) && Number.isFinite(model.discoveries_passed)) return (model.fallback_used ? 0 : model.focuses_passed) + (model.discovery_fallback_used ? 0 : model.discoveries_passed);
    return publication?.result_status === "completed_with_fallback" ? "—" : model.insights_passed ?? "—";
  };
  const aiNote = (publication) => fallbackNote(publication) || (publication?.model_analysis?.ok === false ? `AI 生成失败：${businessReason(publication.model_analysis.error || "未取得有效模型结果")}` : `AI 已生成 ${aiGeneratedCount(publication)} 项`);
  const terms = { no_update: "库内已有", verified: "数据通过（入库另核对）", missing: "执行失败", conflict: "执行失败", not_applicable: "执行失败", error: "执行失败" };
  const reportTerms = { completed: "研究已完成", running: "研究中", partial: "部分完成", error: "执行失败", pending: "待执行" };
  // Presentation only: keep persisted assignments unchanged for same-run resume.
  const childTitle = (title) => String(title || "").replace(/研究 Agent$/, "研究子 Agent");
  const metricValue = (item) => {
    const value = String(item.value ?? "").trim();
    const unit = String(item.unit || "").trim();
    return !value ? "未取得可更新值" : !unit || unit.split(/\s+/).every((part) => value.includes(part)) ? value : `${value} ${unit}`;
  };
  const link = (url, label) => /^https?:\/\//i.test(String(url || "")) ? `<a href="${esc(url)}" target="_blank" rel="noreferrer">${esc(typeof label === "string" ? label : url)}</a>` : esc(url);
  const businessReason = (reason) => {
    if (/budget.exceeded|budget has been exceeded|quota.exceeded|insufficient_quota/i.test(reason)) return "模型服务额度不足，本项研究未完成；未取得可核验的数据，不能入库。";
    if (/401|unauthorized|authentication.error/i.test(reason)) return "模型服务鉴权失败，本项未完成核对，不能入库。";
    if (/429|rate.limit|too many requests/i.test(reason)) return "服务请求受限，本项未完成；需重试取得可靠数据后再审核。";
    if (/timed?\s*out|timeout/i.test(reason)) return "处理超时，本项未取得完整结果；不能据此判断库内已有或没有新数据。";
    return plainText(reason);
  };
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
  const mainTableChanges = (publication) => {
    let recorded = false;
    let added = 0;
    let upgraded = 0;
    Object.values(publication?.domains || {}).forEach((domain) => {
      Object.entries(domain || {}).forEach(([key, promotion]) => {
        if (!key.endsWith("_promotion") || !promotion || typeof promotion !== "object") return;
        if (Number.isFinite(promotion.added_rows)) { added += promotion.added_rows; recorded = true; }
        if (Number.isFinite(promotion.upgraded_rows)) { upgraded += promotion.upgraded_rows; recorded = true; }
      });
    });
    return recorded ? { added, upgraded } : null;
  };
  const visibleChanges = (publication) => {
    const changes = publication?.changes;
    if (changes?.baseline_available !== true) return null;
    const changed = Number(changes.changed || 0);
    const added = Number(changes.added || 0);
    const removed = Number(changes.removed || 0);
    return { changed, added, removed, total: changed + added + removed };
  };
  const updateSummary = (run, compact = false) => {
    const check = run?.publication?.storage_readback;
    if (!check) return `本轮提交 ${run?.accepted ?? "—"} 项；尚未执行正式表回读，不能确认入库`;
    const written = writtenCount(check);
    return `本轮提交 ${check.accepted} 项：已入库 ${written} 项；未入库 ${Math.max(0, check.accepted - written)} 项${compact ? "" : "。只按正式表逐条回读计数；已有及重复记录已在Agent审核阶段排除"}`;
  };
  const writtenCount = (check) => (check?.items || []).filter((i) => ["written", "saved"].includes(i.main_table?.status)).length;
  const storageComplete = (check) => check?.ok === true && Number(check.accepted) === writtenCount(check);
  const itemLabel = (value) => terms[value] || "执行失败";
  const resultCounts = (reports) => {
    const items = mergeSubmissions((reports || []).flatMap((report) => (report.items || []).map((item) => ({ ...item, company: report.company }))));
    return `库内已有 ${items.filter((item) => item.status === "no_update").length} 项 · ${items.filter((item) => item.status === "verified").length}组数据通过 · 执行失败 ${items.filter((item) => !["verified", "no_update"].includes(item.status)).length} 项`;
  };
  const researchHealth = (actual, run) => {
    const execution = actual?.status || (run?.status === "running" ? "running" : undefined);
    if (execution !== "completed") return status(execution);
    const reports = actual?.reports || [];
    if (reports.some((report) => report.status === "error" || (report.items || []).some((item) => item.status === "error"))) return status("error");
    if (isIncremental(run)) {
      const needsReview = reports.some((report) => (report.items || []).some((item) => !["verified", "no_update"].includes(item.status)));
      return { key: needsReview ? "warning" : "healthy", label: needsReview ? "已完成·含失败项" : "已完成" };
    }
    return { key: "healthy", label: "历史核对记录" };
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
    add("research-dispatch", "03:00 研究任务分配", [dispatchX, 330], plan.length || "—", "个研究 Agent", "每天分配六组研究任务，查找各公司最新数据", [
      "程序按公司分配任务，此步骤不调用 AI",
      "香港、内地、亚太、欧洲、美洲与中东、全球云厂商六组并行研究",
      "已有数据库默认正确；任务目标是搜索尚未入库的新数据，保留库内同一报告期或更新报告期的数据",
      "输入：公司、指标、库内最新期间与当前日期；输出：六份最新数据搜索任务",
      "每天03:00启动；各 Agent 的网页搜索与原文读取在同一轮内完成",
      "使用 Deep Agents 0.7.13；六组研究任务同时执行",
    ], status(run ? "completed" : "pending"), { note: run ? "六组公司研究任务已成功分配" : "每日分配六组公司研究任务" });
    plan.forEach((task, index) => {
      const actual = agents.find((agent) => agent.key === task.key);
      const reports = actual?.reports || [];
      const done = reports.filter((report) => report.status === "completed").length;
      add(`research-${task.key}`, childTitle(task.title), [researchX(index), 560], incremental && actual && (reports.some((report) => (report.items || []).length) || actual.status === "completed") ? reports.flatMap((report) => report.items || []).filter((item) => item.status === "verified").length : "—", run && !incremental ? "新增数据未统计" : run?.final_review?.status === "completed" ? "组数据通过" : "组数据通过·待终审", "查找负责公司的最新数据，与库内已有数据比较，仅提交新报告期或新指标", [
        `负责 ${task.companies.length} 家公司：${task.companies.join("、")}`,
        "先查看库内最新报告期，再搜索最新业绩公告并读取原文",
        "提交公司、指标、期间、数值、单位、原文地址、引用摘录和处理结果",
        "数据通过只表示提交了候选资料，不代表最终审核通过或数据库已写入；找不到可靠内容时写明失败原因",
        "每次只提交一个指标，已完成结果立即保存；截断响应禁止入库，传输重试不触发重新抓取",
      ], researchHealth(actual, run), { assignment: task, agent: actual, variant: "research-agent",
        note: `负责 ${task.companies.length} 家公司${incremental && actual ? ` · ${resultCounts(reports)}` : ""} · 负责公司：${task.companies.join("、")}` });
      edges.push(["research-dispatch", `research-${task.key}`, "", "research-fan", {}]);
      edges.push([`research-${task.key}`, "research-merge", "", "research-join", {}]);
    });
    add("research-merge", "最终审核 Agent · 联网核对", [20, 820], incremental && run ? run.accepted ?? "—" : "—", incremental ? "组数据通过" : "新增数据未统计", "核对原文、目标字段、期间与单位；已有和重复数据在此排除，只将可入库数据提交写入", [
      "比较六个研究 Agent 的新数据与库内已有数据，排除同期间已有数据和更旧的数据",
      "检查每家公司、每个指标是否有结果，并核对数值、报告期、单位和原文",
      "有可信原文支持的新数据进入更新批次；库内已有则保留，无法核实则记执行失败并说明原因",
      "输入：六个研究 Agent 的报告；输出：本次可更新字段及待核对清单",
      "本次结束后，下一次定时任务继续搜索最新数据；已有数据保持可信",
    ], run?.final_review?.status === "completed" && run?.review > 0 ? {key: "warning", label: "审核结束·含未通过项"} : status(run?.final_review?.status), {
      agent: data.final_reviewer || null,
      assignment: { key: "final-review" },
      note: data.final_reviewer ? finalReviewSummary(data) : "收齐研究结果后，继续联网补查并核对",
    });
    add("research-update", "四库数据更新", [Math.round((canvasWidth - researchCardWidth) / 2), 820], run?.publication?.storage_readback ? writtenCount(run.publication.storage_readback) : "—", "组数据已入库", "将终审确认可入库的数据写入正式指标表，逐项返回已入库或未入库；点击查看实际表格、字段、数值及原因。", [
      "由一个更新步骤处理六个 Agent 提交的数据，防止多个研究任务同时覆盖文件",
      "库内已有、本轮重复和不具备入库条件的记录在Agent终审排除，不进入写入批次",
      "已入库必须与正式表的字段、数值、单位及来源证据一致；否则为未入库，并保留原因",
      "输入：本次可入库字段；输出：已入库、未入库两类结果及正式表回读明细",
    ], run?.publication?.storage_readback ? { key: storageComplete(run.publication.storage_readback) ? "healthy" : "critical", label: storageComplete(run.publication.storage_readback) ? "已入库" : "存在未入库项" } : status(run?.publication?.status === "completed" ? "pending" : run?.publication?.status), {
      publication: run?.publication,
      note: incremental && run ? updateSummary(run, true) : "统一写入本地、国际、内地运营商和全球云厂商四库",
    });
    add("research-publish", "AI 分析与页面更新", [canvasWidth - researchInset - researchCardWidth, 820], aiGeneratedCount(run?.publication), "项AI生成", "使用四库最新数据调用AI生成分析；全部通过校验后才更新页面", [
      "读取更新后的四库数据，生成分库分析和跨库分析",
      "校验分析引用的数据与公司，更新主页数据和公开页面",
      "发布后读取实际版本，只有成功读取后才记录为发布完成",
      "输入：四库已发布数据；输出：AI分析、页面版本及发布结果",
    ], status(run?.publication?.status), { publication: run?.publication, note: aiNote(run?.publication) });
    edges.push(["research-merge", "research-update", "可更新字段", "cyan", {}], ["research-update", "research-publish", "四库最新数据", "cyan", {}]);
    nodes.filter((node) => node.research).forEach((node) => {
      if (node.key === "research-publish" && run?.publication?.status === "completed" && fallbackNote(run.publication)) {
        node.health = { key: "warning", label: "AI 生成未完成" };
        node.note = `${fallbackNote(run.publication)}；页面发布状态：${pageState(run.publication.pages?.status)}`;
      }
      if (node.key === "research-publish" && run?.publication?.storage_readback?.ok === false) {
        node.health = { key: "critical", label: "数据回读异常" };
        node.note = "历史页面曾发布，但当前数据库回读未通过；不能视为完整交付";
      }
      if (node.key === "research-publish" && run?.publication?.storage_replay?.analysis_rebuilt === false) {
        node.health = { key: "warning", label: "入库已重跑·分析未重跑" };
        node.note = `显示原批次分析：${fallbackNote(run.publication) || "生成情况见详情"}；本次仅重跑审核判断和正式表写入`;
      }
      if (["research-update", "research-publish"].includes(node.key) && run?.publication?.result_status === "needs_review") {
        node.health = { key: "warning", label: "未取得可入库数据" };
        node.note = "研究仍有未通过或失败项；保留原库与页面，不代表已确认没有新数据";
      }
      if (run && !incremental) {
        node.note = `历史运行 · ${node.note}`;
        if (node.health.key === "healthy") node.health = { key: "healthy", label: "历史记录" };
      }
      if (incremental && ["research-update", "research-publish"].includes(node.key) && run.publication?.result_status === "no_new_disclosures") {
        node.health = { key: "healthy", label: node.key === "research-update" ? "无新增·保留原库" : "无新增·沿用页面" };
        node.note = "本次未发现可写入的新数据，保留现有数据库和页面，不重复生成分析";
      } else if (incremental && ["research-update", "research-publish"].includes(node.key) && run.publication?.result_status === "needs_review") {
        node.health = { key: "warning", label: "未更新·含失败项" };
        node.note = "本次未形成可写入的新数据；执行失败原因见结果明细";
      }
    });
    return { nodes, edges, canvasSize: [canvasWidth, 1040], laneLabels: [
      { label: "战略新闻采集与初筛", position: [18, 22] },
      { label: "六 Agent 最新数据搜索与四库更新", position: [18, 325] },
    ], groups: [] };
  }
  const domainNames = { local: "本地运营商", international: "国际运营商", mainland: "内地运营商", cloud: "全球云厂商", cross: "跨库研判" };
  function mergeSubmissions(items) {
    // Alias submissions belong to their representative's evidence, not a fourth outcome.
    // Keep archived records immutable and fail closed if their representative is absent.
    const primary = items.filter((item) => item.write_preflight?.status !== "duplicate")
      .map((item) => ({ ...item, mergedSubmissions: [] }));
    const byId = new Map(primary.filter((item) => item.id).map((item) => [item.id, item]));
    items.filter((item) => item.write_preflight?.status === "duplicate").forEach((item) => {
      const target = item.write_preflight;
      const matches = primary.filter((row) => row.company === item.company && target.path && target.field && target.period
        && row.write_preflight?.path === target.path && row.write_preflight?.field === target.field
        && row.write_preflight?.period === target.period);
      const representative = byId.get(target.represented_by) || (matches.length === 1 ? matches[0] : null);
      if (representative && representative.company === item.company) representative.mergedSubmissions.push(item);
      else primary.push({ ...item, write_preflight: { ...item.write_preflight, status: "rejected", reason: "未找到该指标对应的主记录，无法确认合并关系；需补齐后重新审核，不能独立入库" } });
    });
    return primary;
  }
  function finalReviewGroups(items) {
    const primary = mergeSubmissions(items);
    const groups = { ready: [], existing: [], rejected: [] };
    primary.forEach((item) => {
      const state = item.write_preflight?.status;
      if (state === "ready" || state === "existing") groups[state].push(item);
      else if (!state && (item.research_status || item.status) === "no_update") groups.existing.push(item);
      else if (state === "pending" || (!state && ((item.research_status || item.status) === "verified" || item.decision === "accepted"))) {
        groups.rejected.push({ ...item, write_preflight: { ...item.write_preflight, status: "rejected", reason: "入库条件尚未核对完成，暂不可入库；不能仅凭数据通过确认可写入" } });
      } else groups.rejected.push(item);
    });
    return groups;
  }
  function finalReviewSummary(data) {
    const reports = data.final_reviewer?.reports || (data.agents || []).flatMap((agent) => agent.reports || []);
    const items = data.result_items || reports.flatMap((report) => (report.items || []).map((item) => ({ ...item, company: report.company })));
    const groups = finalReviewGroups(items);
    return `可入库 ${groups.ready.length} 项 · 库内已有 ${groups.existing.length} 项 · 不可入库 ${groups.rejected.length} 项`;
  }
  // Report periods describe the source data, never the crawler run date.
  function reportPeriod(item = {}) {
    const target = item.write_preflight || item.main_table || {};
    const baselinePeriod = (item.research_status || item.status) === "no_update" ? item.latest_baseline?.period : "";
    const original = String(item.period || baselinePeriod || target.period || "").trim();
    const text = String(target.period || original).toLowerCase().replace(/\s+/g, " ");
    const full = original.toLowerCase();
    if (!text || /未取得|未明确|unknown|未提供/.test(text)) return { key: "unknown", label: "报告期未取得", year: "", kind: "unknown", original };
    const fiscal = /\bfy\s*\d|fiscal|financial year/.test(text + " " + full);
    const fy = (text + " " + full).match(/\bfy\s*(\d{4}|\d{2})(?!\d)/);
    const year = fy ? String(Number(fy[1]) + (fy[1].length === 2 ? 2000 : 0)) : ((text + " " + full).match(/20\d{2}/) || [""])[0];
    const quarterText = (text + " " + full).replace(/(first|second|third|fourth) quarter/g, (_, word) => `Q${["first", "second", "third", "fourth"].indexOf(word) + 1}`).replace(/第([一二三四])季/g, (_, word) => `Q${"一二三四".indexOf(word) + 1}`).toLowerCase();
    const quarter = quarterText.match(/q\s*([1-4])|([1-4])\s*q/);
    let kind = quarter ? `Q${quarter[1] || quarter[2]}` : /h\s*1|1\s*h|first half|first six months|上半年/.test(text) ? "H1"
      : /h\s*2|2\s*h|second half|下半年/.test(text) ? "H2" : "";
    let end = target.period_end || "";
    if (!end) {
      const iso = original.match(/(20\d{2})[-年](\d{1,2})[-月](\d{1,2})/);
      const months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"];
      const english = full.match(/(\d{1,2})\s+([a-z]+)\s+(20\d{2})/) || full.match(/([a-z]+)\s+(\d{1,2}),?\s+(20\d{2})/);
      if (iso) end = `${iso[1]}-${iso[2].padStart(2, "0")}-${iso[3].padStart(2, "0")}`;
      else if (english) {
        const dayFirst = /^\d/.test(english[1]);
        const month = months.indexOf(dayFirst ? english[2] : english[1]) + 1;
        if (month) end = `${english[3]}-${String(month).padStart(2, "0")}-${(dayFirst ? english[1] : english[2]).padStart(2, "0")}`;
      }
    }
    if (!end && year && !fiscal && /^(H[12]|Q[1-4])$/.test(kind)) {
      const month = kind === "H1" ? 6 : kind === "H2" ? 12 : Number(kind[1]) * 3;
      end = `${year}-${String(month).padStart(2, "0")}-${[6, 9].includes(month) ? "30" : "31"}`;
    }
    if (!kind) kind = /six months|six-month|半年|中期/.test(text + " " + full) ? "half"
      : /three months|three-month|quarter|季度/.test(text + " " + full) ? "quarter"
      : /year|年度|全年|\bfy|^20\d{2}$/.test(text) ? "FY" : "other";
    const names = { FY: fiscal ? "全年" : "年度", half: "六个月", quarter: "三个月", other: "报告区间" };
    let label = year && !["half", "quarter", "other"].includes(kind) ? `${fiscal ? "FY" : ""}${year} ${names[kind] || kind}`
      : names[kind] || kind;
    if (end) label += ` · 截至${end}`;
    // Without a verified interval keep the original wording visible and distinct.
    if (!end && ["half", "quarter", "other"].includes(kind)) label = original;
    if (!year) label = original;
    const key = JSON.stringify([year, fiscal, kind, end || (["half", "quarter", "other"].includes(kind) ? original : "")]);
    return { key, label, year, kind, original };
  }
  function withReportEvidence(item, reports) {
    const candidates = reports.filter((row) => row.company === item.company && row.metric === item.metric);
    const report = candidates.find((row) => reportPeriod(row).key === reportPeriod(item).key) || (candidates.length === 1 ? candidates[0] : {});
    return { ...report, ...item, value: item.value === "" ? report.value : item.value };
  }
  function matrixModel(node, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : {};
    const run = data.run;
    if (node.key === "research-publish") return [];
    const plan = run?.plan || data.plan || [];
    const assignedTask = plan.find((task) => task.key === (node.assignment?.key || node.key.replace(/^research-/, "")));
    const scoped = assignedTask ? [assignedTask] : ["research-dispatch", "research-merge", "research-update"].includes(node.key) ? plan : [];
    const scopedAgents = (data.agents || []).filter((agent) => scoped.some((task) => task.key === agent.key));
    const allReports = scopedAgents.flatMap((agent) => agent.reports || []);
    const rawItems = allReports.flatMap((report) => (report.items || []).map((item) => ({ ...item, company: report.company })));
    const mergedRawItems = mergeSubmissions(rawItems);
    const primaryKeys = new Set(mergedRawItems.map((item) => JSON.stringify([item.company, item.metric])));
    const mergedAliasKeys = new Set(mergedRawItems.flatMap((item) => (item.mergedSubmissions || []).map((alias) => JSON.stringify([alias.company, alias.metric]))).filter((key) => !primaryKeys.has(key)));
    const finalItems = (data.result_items || []).map((item) => withReportEvidence(item, rawItems));
    // Each downstream node owns its actual input set, not the complete research plan.
    const scopeItems = node.key === "research-update" ? (data.accepted_items ?? run?.publication?.storage_readback?.items ?? [])
      : node.key === "research-merge" ? Object.values(finalReviewGroups(data.result_items ? finalItems : rawItems)).flat() : null;
    const receipts = run?.publication?.storage_readback?.items || [];
    const identity = (item) => JSON.stringify([item.company, item.metric]);
    const samePeriod = (a, b) => reportPeriod(a).key === reportPeriod(b).key;
    const index = (items) => {
      const map = new Map();
      items.forEach((item) => { const key = identity(item); if (!map.has(key)) map.set(key, []); map.get(key).push(item); });
      return map;
    };
    const rawIndex = index(mergedRawItems), finalIndex = index(mergeSubmissions(finalItems)), receiptIndex = index(receipts);
    const byId = new Map(finalItems.filter((item) => item.id).map((item) => [item.id, item]));
    const finished = run && ["completed", "partial", "error", "cancelled"].includes(run.display_status || run.status);
    const outcome = (item) => {
      if (!item) return { key: "pending", label: finished ? "未取得结果" : "待检索" };
      const state = item.write_preflight?.status;
      if (state === "duplicate") {
        const primary = byId.get(item.write_preflight.represented_by);
        if (primary && primary.company === item.company && primary.write_preflight?.status !== "duplicate") {
          const result = outcome(primary);
          return { ...result, label: `${result.label}·合并` };
        }
        return { key: "rejected", label: "合并待核对" };
      }
      if (state === "existing" || (!state && (item.research_status || item.status) === "no_update")) return { key: "existing", label: "库内已有" };
      if (state === "rejected") return { key: "rejected", label: "不可入库" };
      if (state === "ready") {
        const saved = (receiptIndex.get(identity(item)) || []).filter((receipt) => samePeriod(item, receipt));
        if (saved.length && saved.every((receipt) => ["written", "saved"].includes(receipt.main_table?.status))) return { key: "written", label: "已入库" };
        if (saved.length) return { key: "rejected", label: "未入库" };
        return { key: "ready", label: "可入库" };
      }
      if (state === "pending") return { key: "pending", label: "待核对" };
      const researchState = item.research_status || item.status;
      if (researchState === "not_applicable") return { key: "na", label: "不适用" };
      if (["running", "pending"].includes(researchState)) return { key: "pending", label: finished ? "未取得结果" : "检索中" };
      if (researchState === "verified" || item.decision === "accepted") return { key: "ready", label: "数据通过" };
      return { key: "rejected", label: "不可入库" };
    };
    return scoped.map((task) => {
      const companies = [...new Set([...(task.companies || []), ...scopedAgents.filter((agent) => agent.key === task.key).flatMap((agent) => (agent.reports || []).map((report) => report.company))])]
        .filter((company) => scopeItems === null || scopeItems.some((item) => item.company === company));
      const rows = companies.map((company) => {
        const reports = allReports.filter((report) => report.company === company);
        const companyItems = scopeItems?.filter((item) => item.company === company);
        const metrics = [...new Set((companyItems ? companyItems.map((item) => item.metric)
          : reports.flatMap((report) => [...(report.metrics || []), ...(report.items || []).map((item) => item.metric)])).filter((metric) => metric && !mergedAliasKeys.has(JSON.stringify([company, metric]))))];
        // Archived contracts win; never infer old tasks from today's metric catalog.
        return { company, cells: metrics.map((metric) => {
          const key = identity({ company, metric });
          const raw = rawIndex.get(key) || [];
          const final = finalIndex.get(key) || [];
          const items = companyItems ? companyItems.filter((item) => item.metric === metric) : final.length ? final : raw;
          const periods = new Map();
          (items.length ? items : [null]).forEach((item) => {
            const period = reportPeriod(item || {});
            if (!periods.has(period.key)) periods.set(period.key, { period, items: [] });
            if (item) periods.get(period.key).items.push(item);
          });
          const slices = [...periods.values()].map(({ period, items: periodItems }) => {
            const outcomes = periodItems.length ? periodItems.map(outcome) : [outcome(null)];
            const result = outcomes.every((current) => current.key === outcomes[0].key && current.label === outcomes[0].label)
              ? outcomes[0] : { key: "mixed", label: "结果不一" };
            return { company, metric, targetMetric: metric, ...result, period, items: periodItems,
              raw: raw.filter((item) => reportPeriod(item).key === period.key),
              receipts: (receiptIndex.get(identity({ company, metric })) || []).filter((item) => reportPeriod(item).key === period.key) };
          }).sort((a, b) => b.period.year.localeCompare(a.period.year) || a.period.label.localeCompare(b.period.label));
          return { company, metric, ...slices[0], slices };

        }) };
      });
      return { key: task.key, title: childTitle(task.title), rows, metrics: [...new Set(rows.flatMap((row) => row.cells.map((cell) => cell.metric)))] };
    }).filter((group) => group.rows.length);
  }
  function researchMatrix(node, snapshot, date) {
    if (node.key === "research-publish") return "";
    const groups = matrixModel(node, snapshot, date);
    const groupCount = (group) => `${group?.rows.length || 0} 家公司 · ${group?.rows.reduce((sum, row) => sum + row.cells.length, 0) || 0} 项指标`;
    const scopeNote = node.key === "research-update" ? "仅列本节点收到的本次写入项目。"
      : node.key === "research-merge" ? "仅列本节点审核的主指标，合并提交保留在主指标依据中。"
      : node.key === "research-dispatch" ? "仅列本节点派发给当前研究组的公司和指标。" : "仅列本研究节点负责的公司和指标。";
    const periods = groups.flatMap((group) => group.rows.flatMap((row) => row.cells.flatMap((cell) => cell.slices.map((slice) => slice.period))));
    const years = [...new Set(periods.map((period) => period.year).filter(Boolean))].sort().reverse();
    const kindNames = { H1: "H1 · 上半期", H2: "H2 · 下半期", Q1: "Q1 · 第一季度", Q2: "Q2 · 第二季度", Q3: "Q3 · 第三季度", Q4: "Q4 · 第四季度", FY: "全年", half: "六个月区间", quarter: "三个月区间", other: "其他报告期", unknown: "报告期未取得" };
    return `<section class="news-lineage-dialog-section research-matrix" data-matrix-view="${esc(`${date}/${node.key}`)}"><header><h3>公司 × 指标 × 报告期矩阵</h3><span data-matrix-count>${groupCount(groups[0])}</span></header>
      <p class="research-matrix-note">${scopeNote}每格按报告期分层；点击某一期跳到对应明细，颜色表示该期结果。报告期是数据所属期间，与本轮检索日期不同。</p>
      <div class="research-matrix-time" role="group" aria-label="筛选矩阵报告期">
        <label>报告年份<select data-custom-select="native" data-matrix-year aria-label="矩阵报告年份"><option value="">全部年份</option>${years.map((year) => `<option>${esc(year)}</option>`).join("")}</select></label>
        <label>报告类型<select data-custom-select="native" data-matrix-kind aria-label="矩阵报告类型"><option value="">全部报告期</option>${Object.entries(kindNames).map(([kind, label]) => `<option value="${kind}">${label}</option>`).join("")}</select></label>
        <button type="button" data-matrix-time-clear disabled>清除时间筛选</button><span data-matrix-time-status role="status" aria-live="polite"></span>
      </div>
      <div class="research-matrix-legend" aria-label="矩阵结果图例">${[["written", "已入库"], ["ready", "数据通过 / 可入库"], ["existing", "库内已有"], ["rejected", "不可入库 / 未入库"], ["pending", "待检索 / 待核对 / 未取得结果"], ["na", "不适用"]].map(([key, label]) => `<span class="is-${key}"><i aria-hidden="true"></i>${label}</span>`).join("")}</div>
      ${groups.length > 1 ? `<div class="research-matrix-groups" role="group" aria-label="选择研究组">${groups.map((group, index) => `<button type="button" data-matrix-group="${esc(group.key)}" aria-pressed="${index === 0}">${esc(group.title.replace(/研究子 Agent$/, ""))}</button>`).join("")}</div>` : ""}
      ${groups.map((group, index) => `<section data-matrix-panel="${esc(group.key)}" data-matrix-count="${groupCount(group)}" aria-label="${esc(group.title)}检索矩阵"${index ? " hidden" : ""}><div class="research-matrix-scroll" role="region" aria-label="公司指标矩阵，可横向滚动" tabindex="0"><table><thead><tr><th scope="col">公司 / 对象</th>${group.metrics.map((metric) => `<th scope="col">${esc(metric)}</th>`).join("") || '<th scope="col">检索指标</th>'}</tr></thead><tbody>${group.rows.map((row) => `<tr><th scope="row">${esc(row.company)}</th>${!row.cells.length ? `<td colspan="${group.metrics.length || 1}" class="research-matrix-unassigned">本轮尚未保存该公司的指标清单</td>` : group.metrics.map((metric) => {
        const cell = row.cells.find((item) => item.metric === metric);
        if (!cell) return '<td class="research-matrix-outside" aria-label="不在该公司的检索清单">—</td>';
        return `<td>${cell.slices.map((cell) => {
        const details = cell.items.length ? cell.items.map((item) => {
          const raw = cell.raw.find((record) => record.metric === item.metric) || {};
          const reason = item.write_preflight?.reason || item.reason || (item.reasons || []).join("；") || raw.reason || "未保存判断依据";
          return `<p>${esc(metricValue(item))} · ${esc(item.period || "报告期未取得")}</p><p>${esc(businessReason(reason))}</p><p>${(item.sources || raw.sources || [item.source_url || raw.source_url]).filter(Boolean).map((source) => link(typeof source === "string" ? source : source.url)).join("<br>") || "尚未取得可用来源"}</p>`;
        }).join("") : '<p>该指标在本轮检索清单内，尚未保存处理结果；不能视为库内已有或已完成。</p>';
        return `<div data-matrix-entry data-year="${esc(cell.period.year)}" data-kind="${esc(cell.period.kind)}"><button type="button" class="research-matrix-cell is-${cell.key}" aria-pressed="false" data-matrix-period="${esc(cell.period.key)}" data-matrix-company="${esc(cell.company)}" data-matrix-metric="${esc(cell.metric)}" data-matrix-target-metric="${esc(cell.targetMetric)}" aria-label="${esc(`${cell.company} · ${cell.metric} · ${cell.period.label} · ${cell.label}，点击查看明细`)}" title="${esc(`${cell.company} · ${cell.metric} · ${cell.period.label}：${cell.label}`)}"><span class="research-matrix-period">${esc(cell.period.label)}</span><span>${esc(cell.label)}</span></button><template><h4>${esc(cell.company)} · ${esc(cell.metric)} · ${esc(cell.period.label)} <span>${esc(cell.label)}</span></h4>${details}${cell.receipts.map((receipt) => `<p>正式表回读：${esc(receipt.main_table?.reason || receipt.reason || "未保存回读说明")} · 当前值 ${esc(receipt.main_table?.current_value ?? "未确认")}</p>`).join("")}</template></div>`;
        }).join("")}<span data-matrix-period-empty hidden>本期无记录</span></td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div></section>`).join("") || '<p class="research-matrix-note">本节点尚无对应的公司与指标项目。</p>'}
      <p class="research-matrix-note">“—”表示不在检索清单；“本期无记录”表示本轮没有该期记录，不代表数值为零或不可入库。FY为公司财年；不确定H1/H2的区间保留截止日。可左右滚动查看。</p>
    </section><section class="news-lineage-dialog-section research-matrix-selection" data-matrix-selection tabindex="-1" hidden></section>`;
  }
  const matrixViews = new Map();
  function mountMatrix(root) {
    const matrix = root.querySelector(".research-matrix");
    if (!matrix || matrix.dataset.mounted) return;
    matrix.dataset.mounted = "true";
    const selection = root.querySelector("[data-matrix-selection]");
    matrix.querySelectorAll("[data-matrix-group]").forEach((button) => button.addEventListener("click", () => {
      matrix.querySelectorAll("[data-matrix-group]").forEach((tab) => tab.setAttribute("aria-pressed", String(tab === button)));
      matrix.querySelectorAll("[data-matrix-panel]").forEach((panel) => {
        panel.hidden = panel.dataset.matrixPanel !== button.dataset.matrixGroup;
        if (!panel.hidden) matrix.querySelector("header [data-matrix-count]").textContent = panel.dataset.matrixCount;
      });
    }));
    const jump = (target) => {
      target.tabIndex = -1;
      target.focus({ preventScroll: true });
      target.scrollIntoView({ block: "start", behavior: "instant" });
    };
    let restoreSelection = null;
    const cells = [...matrix.querySelectorAll("[data-matrix-company]")];
    const yearSelect = matrix.querySelector("[data-matrix-year]"), kindSelect = matrix.querySelector("[data-matrix-kind]");
    const timeClear = matrix.querySelector("[data-matrix-time-clear]");
    const savedTime = matrixViews.get(matrix.dataset.matrixView) || {};
    yearSelect.value = savedTime.year || ""; kindSelect.value = savedTime.kind || "";
    const clearSelection = () => {
      if (restoreSelection) { restoreSelection(); restoreSelection = null; }
      cells.forEach((cell) => { cell.classList.remove("is-selected"); cell.setAttribute("aria-pressed", "false"); });
    };
    const renderTime = () => {
      let count = 0, unknown = 0;
      matrix.querySelectorAll("[data-matrix-entry]").forEach((entry) => {
        entry.hidden = !!((yearSelect.value && entry.dataset.year !== yearSelect.value) || (kindSelect.value && entry.dataset.kind !== kindSelect.value));
        if (!entry.hidden && !entry.closest("[data-matrix-panel]").hidden) { count++; if (entry.dataset.kind === "unknown") unknown++; }
      });
      matrix.querySelectorAll("[data-matrix-period-empty]").forEach((empty) => {
        empty.hidden = [...empty.parentElement.querySelectorAll("[data-matrix-entry]")].some((entry) => !entry.hidden);
      });
      matrix.querySelector("[data-matrix-time-status]").textContent = `当前显示 ${count} 条期间记录${unknown ? ` · ${unknown} 条报告期未取得` : ""}`;
      timeClear.disabled = !yearSelect.value && !kindSelect.value;
      matrixViews.set(matrix.dataset.matrixView, { year: yearSelect.value, kind: kindSelect.value,
        group: matrix.querySelector('[data-matrix-panel]:not([hidden])')?.dataset.matrixPanel });
    };
    [yearSelect, kindSelect].forEach((select) => select.addEventListener("change", () => { clearSelection(); renderTime(); }));
    timeClear.addEventListener("click", () => { clearSelection(); yearSelect.value = kindSelect.value = ""; renderTime(); });
    matrix.querySelectorAll("[data-matrix-group]").forEach((button) => button.addEventListener("click", () => { clearSelection(); renderTime(); }));
    const savedGroup = [...matrix.querySelectorAll("[data-matrix-group]")].find((button) => button.dataset.matrixGroup === savedTime.group);
    if (savedGroup) savedGroup.click(); else renderTime();
    cells.forEach((button) => button.addEventListener("click", () => {
      const wasSelected = button.classList.contains("is-selected");
      if (restoreSelection) { restoreSelection(); restoreSelection = null; }
      cells.forEach((cell) => {
        const selected = !wasSelected && cell === button;
        cell.classList.toggle("is-selected", selected);
        cell.setAttribute("aria-pressed", String(selected));
      });
      if (wasSelected) return;
      const company = button.dataset.matrixCompany, metric = button.dataset.matrixMetric, period = button.dataset.matrixPeriod;
      const section = root.querySelector(".research-decisions");
      const content = root.querySelector(".research-node-detail");
      const scrollTop = content?.scrollTop || 0;
      const originalView = section ? { ...decisionViews.get(section.dataset.researchView) } : null;
      const openedDetails = [];
      const openDetail = (detail) => { if (detail && !detail.open) { openedDetails.push(detail); detail.open = true; } };
      restoreSelection = () => {
        selection.hidden = true;
        openedDetails.forEach((detail) => { detail.open = false; });
        if (section && originalView) {
          Object.assign(decisionViews.get(section.dataset.researchView), originalView);
          section.dispatchEvent(new Event("research-decision-restore"));
        }
        if (content) content.scrollTop = scrollTop;
      };
      const row = [...root.querySelectorAll("[data-research-row]")].find((item) => item.dataset.company === company && item.dataset.period === period
        && (item.dataset.metric === metric || JSON.parse(item.dataset.mergedMetrics || "[]").includes(metric)));
      if (section && row) {
        selection.hidden = true;
        const category = row.closest("[data-research-panel]").dataset.researchPanel;
        [...section.querySelectorAll("[data-research-filter]")].find((tab) => tab.dataset.researchFilter === category).click();
        section.querySelector("[data-research-company]").value = company;
        const metricSelect = section.querySelector("[data-research-metric]");
        metricSelect.value = row.dataset.metric;
        section.querySelector("[data-research-period]").value = period;
        metricSelect.dispatchEvent(new Event("change"));
        // Keep the matching row below the sticky filtering toolbar.
        row.style.scrollMarginTop = `${section.querySelector(".research-decision-controls").offsetHeight + 16}px`;
        if (row.dataset.metric !== metric) openDetail(row.querySelector(".research-record-source"));
        jump(row);
        return;
      }
      const storedRow = [...root.querySelectorAll("[data-research-storage-row]")].find((item) => item.dataset.company === company && item.dataset.metric === button.dataset.matrixTargetMetric && item.dataset.period === period);
      if (storedRow) {
        selection.hidden = true;
        for (let parent = storedRow.parentElement; parent && parent !== root; parent = parent.parentElement) {
          if (parent.tagName === "DETAILS") openDetail(parent);
        }
        jump(storedRow);
        return;
      }
      selection.innerHTML = button.nextElementSibling.innerHTML;
      selection.hidden = false;
      jump(selection);
    }));
  }
  function decisionGroups(node, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : {};
    const reports = (node.agent ? [node.agent] : data.agents || []).flatMap((a) => (a.reports || []).flatMap((r) => (r.items || []).map((i) => ({ ...i, company: r.company }))));
    const final = node.key === "research-merge";
    const items = final ? (data.result_items || reports).map((i) => {
      return withReportEvidence(i, reports);
    }) : reports;
    const groups = final ? finalReviewGroups(items) : { ready: [], existing: [], rejected: [], pending: [] };
    if (!final) mergeSubmissions(items).forEach((item) => {
      const state = item.write_preflight?.status || ((item.research_status || item.status) === "no_update" ? "existing" : (item.research_status || item.status) === "verified" || item.decision === "accepted" ? (final ? "pending" : "ready") : "rejected");
      (groups[state] || groups.rejected).push(item);
    });
    const labels = { ready: final ? "可入库" : "数据通过", existing: "库内已有 · 不提交", rejected: "不可入库", pending: "待入库条件核对" };
    const descriptions = { ready: final ? "字段、期间、单位与证据已核对；实际写入结果见四库更新节点。" : "展示本Agent提交的具体指标；最终判断及写入结果分别在下游节点查看。", existing: "已在Agent阶段识别，无需重复提交四库更新。", rejected: "逐项说明未通过的原因；这些记录不进入写入批次。", pending: "已取得候选数据，但尚无正式表入库检查结果。" };
    const categories = Object.entries(groups).filter(([key]) => key !== "pending" || groups.pending.length);
    const shortLabels = { ...labels, existing: "库内已有" };
    const displayCount = categories.reduce((count, [, rows]) => count + rows.length, 0);
    const filterItems = categories.flatMap(([, rows]) => rows);
    const filterOptions = (field) => [...new Set(filterItems.map((item) => String(item[field] ?? "")).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "zh-Hans-CN", { numeric: true }))
      .map((value) => `<option value="${esc(value)}">${esc(value)}</option>`).join("");
    const periodOptions = [...new Map(filterItems.map((item) => { const period = reportPeriod(item); return [period.key, period]; })).values()]
      .sort((a, b) => b.year.localeCompare(a.year) || a.label.localeCompare(b.label))
      .map((period) => `<option value="${esc(period.key)}">${esc(period.label)}</option>`).join("");
    return `<section class="news-lineage-dialog-section research-decisions" data-research-view="${esc(`${date}/${node.key}`)}"><header><h3>${final ? "终审入库判断" : "本Agent指标与判断"}</h3><span>共 ${displayCount} 项指标 · 同指标提交已合并</span></header>
      <div class="research-decision-controls"><div class="research-decision-toolbar"><div class="research-decision-switcher" role="group" aria-label="按入库判断筛选">${categories.map(([key, rows], index) => `<button type="button" data-research-filter="${key}" aria-pressed="${index === 0}" title="${labels[key]}"><span>${shortLabels[key]}</span><b>${rows.length}</b></button>`).join("")}</div><div class="research-decision-filters" role="group" aria-label="筛选指标"><label><span>公司/对象</span><select data-custom-select="native" data-research-company aria-label="筛选公司或对象"><option value="">全部公司/对象</option>${filterOptions("company")}</select></label><label><span>指标</span><select data-custom-select="native" data-research-metric aria-label="筛选指标"><option value="">全部指标</option>${filterOptions("metric")}</select></label><label><span>报告期</span><select data-custom-select="native" data-research-period aria-label="筛选报告期"><option value="">全部报告期</option>${periodOptions}</select></label><button type="button" data-research-clear disabled>清除</button></div></div><div class="research-decision-meta"><p data-research-description>${descriptions.ready}</p><div class="research-decision-pagination"><span data-research-page-status role="status" aria-live="polite"></span><button type="button" data-research-page="-1" aria-label="上一页指标">上一页</button><button type="button" data-research-page="1" aria-label="下一页指标">下一页</button></div></div></div>
      ${categories.map(([key, rows], index) => `<section class="research-decision-panel is-${key}" data-research-panel="${key}" data-description="${esc(descriptions[key])}" aria-label="${labels[key]}指标明细"${index ? " hidden" : ""}><table class="research-decision-table"><thead><tr><th scope="col">公司／具体指标</th><th scope="col">数值／报告期</th><th scope="col">判断原因与依据</th></tr></thead><tbody>${rows.map((raw) => {
      const old = raw.latest_baseline;
      const item = key === "existing" && old ? { ...raw, ...old } : raw;
      const target = raw.write_preflight || {};
      const reason = target.reason || raw.reason || (raw.reasons || []).join("；") || "未保存判断依据，不能据此确认可入库";
      return `<tr data-research-row data-period="${esc(reportPeriod(raw).key)}" data-company="${esc(raw.company)}" data-metric="${esc(raw.metric)}" data-merged-metrics="${esc(JSON.stringify((raw.mergedSubmissions || []).map((item) => item.metric)))}"><th scope="row"><strong>${esc(raw.company)}</strong><span>${esc(raw.metric)}</span>${target.field ? `<code>${esc(target.field)}</code>` : ""}</th><td class="research-decision-value"><strong>${esc(metricValue(item))}</strong><span>${esc(item.period || "报告期未取得")}</span>${target.field ? `<small>标准值 ${esc(target.value)} ${esc(target.unit)} · ${esc(target.period)}</small>` : ""}</td><td><p>${esc(businessReason(reason))}</p>${key === "existing" && target.previous_value != null ? `<p>正式表已有值：${esc(target.previous_value)} ${esc(target.unit)}</p>` : ""}<details class="research-record-source"><summary>查看来源与原文依据</summary><p>${(item.sources || [item.source_url]).filter(Boolean).map((u) => link(typeof u === "string" ? u : u.url)).join("<br>") || "本条未取得可用来源"}</p><p>${esc(raw.quote || raw.basis || "未保存可用原文摘录")}</p><p>原始判断记录：${esc(reason)}</p>${raw.mergedSubmissions?.length ? `<h4>同指标合并记录</h4><p>以下提交已并入当前指标，不单独计数或再次写入。</p><ul>${raw.mergedSubmissions.map((merged) => `<li><strong>${esc(merged.company)} · ${esc(merged.metric)}</strong><p>${esc(metricValue(merged))} · ${esc(merged.period)}</p><p>${esc(merged.write_preflight?.reason || "同指标合并")}</p><p>${(merged.sources || [merged.source_url]).filter(Boolean).map((u) => link(typeof u === "string" ? u : u.url)).join("<br>")}</p></li>`).join("")}</ul>` : ""}</details></td></tr>`;
    }).join("")}</tbody></table><p class="research-empty" data-research-empty hidden>本类暂无记录</p></section>`).join("")}</section>`;
  }
  const decisionViews = new Map();
  function decisionPage(rows, filters, page, size = 20) {
    const matched = rows.filter((row) => (!filters.company || row.dataset.company === filters.company)
      && (!filters.metric || row.dataset.metric === filters.metric)
      && (!filters.period || row.dataset.period === filters.period));
    const pages = Math.max(1, Math.ceil(matched.length / size));
    const current = Math.max(0, Math.min(page, pages - 1));
    return { matched, pages, current, visible: matched.slice(current * size, (current + 1) * size) };
  }
  function mount(root) {
    mountMatrix(root);
    const section = root.querySelector(".research-decisions");
    if (!section || section.dataset.mounted) return;
    section.dataset.mounted = "true";
    const buttons = [...section.querySelectorAll("[data-research-filter]")];
    const panels = [...section.querySelectorAll("[data-research-panel]")];
    const company = section.querySelector("[data-research-company]");
    const metric = section.querySelector("[data-research-metric]");
    const period = section.querySelector("[data-research-period]");
    const clear = section.querySelector("[data-research-clear]");
    const key = section.dataset.researchView;
    const view = decisionViews.get(key) || { category: buttons[0].dataset.researchFilter, company: "", metric: "", period: "", page: 0 };
    if (!panels.some((panel) => panel.dataset.researchPanel === view.category)) view.category = buttons[0].dataset.researchFilter;
    [[company, "company"], [metric, "metric"], [period, "period"]].forEach(([select, field]) => {
      if (![...select.options].some((option) => option.value === view[field])) { view[field] = ""; view.page = 0; }
      select.value = view[field];
    });
    const render = () => {
      buttons.forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.researchFilter === view.category)));
      panels.forEach((panel) => { panel.hidden = panel.dataset.researchPanel !== view.category; });
      const panel = panels.find((item) => !item.hidden);
      const rows = [...panel.querySelectorAll("[data-research-row]")];
      const result = decisionPage(rows, view, view.page);
      view.page = result.current;
      const visible = new Set(result.visible);
      rows.forEach((row) => { row.hidden = !visible.has(row); });
      panel.querySelector("table").hidden = !result.matched.length;
      const empty = panel.querySelector("[data-research-empty]");
      empty.hidden = !!result.matched.length;
      empty.textContent = rows.length ? "本类没有符合筛选条件的记录，请调整或清除筛选。" : "本类暂无记录。";
      section.querySelector("[data-research-description]").textContent = panel.dataset.description;
      section.querySelector("[data-research-page-status]").textContent = `${result.matched.length} 项 · ${result.current + 1} / ${result.pages} 页`;
      section.querySelector('[data-research-page="-1"]').disabled = result.current === 0;
      section.querySelector('[data-research-page="1"]').disabled = result.current + 1 === result.pages;
      clear.disabled = !view.company && !view.metric && !view.period;
      decisionViews.set(key, view);
    };
    section.addEventListener("research-decision-restore", () => {
      company.value = view.company; metric.value = view.metric; period.value = view.period || ""; render();
    });
    const resetScroll = () => section.scrollIntoView({ block: "start", behavior: "instant" });
    buttons.forEach((button) => button.addEventListener("click", () => { view.category = button.dataset.researchFilter; view.page = 0; render(); resetScroll(); }));
    section.querySelectorAll("[data-research-page]").forEach((button) => button.addEventListener("click", () => { view.page += Number(button.dataset.researchPage); render(); resetScroll(); }));
    [company, metric, period].forEach((select) => select.addEventListener("change", () => {
      view.company = company.value; view.metric = metric.value; view.period = period.value; view.page = 0; render(); resetScroll();
    }));
    clear.addEventListener("click", () => {
      view.company = company.value = ""; view.metric = metric.value = ""; view.period = period.value = ""; view.page = 0; render(); resetScroll();
    });
    render();
  }
  function actualList(node, snapshot, date) {
    const data = snapshot?.date === date ? snapshot : {};
    const run = data.run;
    const section = (title, note, rows) => `<section class="news-lineage-dialog-section research-actual-list"><header><h3>${esc(title)}</h3><span>${rows.length} 条明细</span></header><p>${esc(note)}</p><div class="news-lineage-preview-scroll" role="region" aria-label="本节点逐条明细" tabindex="0">${rows.join("") || "<p>本次未保存可展示明细；不以其他日期的数据补齐。</p>"}</div></section>`;
    if (node.key === "research-dispatch") return section("本次分配的公司与指标", run ? "按公司分组查找最新披露，以正式表已有数据判断是否需要新增。" : "尚未执行；以下是计划任务", (run?.plan || data.plan || []).map((task, i) => `<article><strong>${i + 1}. ${esc(childTitle(task.title))}</strong><p>分配原因：${esc(plainText(task.purpose))}</p>${task.companies.map((company) => {
      const report = (data.agents || []).flatMap((a) => a.reports || []).find((r) => r.company === company);
      return `<p><strong>${esc(company)}</strong>：${esc((report?.metrics || []).join("、") || "指标将在任务启动时按页面关注项展开")}</p>`;
    }).join("")}</article>`));
    if (node.key === "research-publish") {
      const items = data.insight_items || [];
      const publication = run?.publication;
      return section(`本轮 ${aiGeneratedCount(publication)} 项AI分析具体内容`, `${publication?.storage_replay?.analysis_rebuilt === false ? "本次仅重跑审核与入库，下面保留重跑前的分析和发布记录，未重新生成或发布。" : ""}${fallbackNote(publication)}${fallbackNote(publication) ? "。" : ""}已读取 ${items.length} 项本次任务的明细。页面发布：${pageState(publication?.pages?.status)}`, items.map((item, i) => `<article><strong>${i + 1}. ${esc(item.headline || item.title || item.id || "跨库分析")}</strong><p>${esc(domainNames[item.domain] || item.domain)} · ${esc(item.analysis || item.detail || item.insight || "未保存正文")}</p>${item.risk ? `<p>判断依据与风险：${esc(item.risk)}</p>` : ""}<p>${(item.source_urls || []).map(link).join("<br>")}</p></article>`));
    }
    const reports = (node.agent ? [node.agent] : data.agents || []).flatMap((a) => (a.reports || []).flatMap((r) => (r.items || []).map((item) => ({ ...item, company: r.company }))));
    const update = node.key === "research-update";
    const items = update ? data.accepted_items || [] : node.key === "research-merge" ? data.result_items || reports : reports;
    const selected = (node.agent ? [...items].sort((a, b) => Number(b.status === "verified") - Number(a.status === "verified")) : items)
      .map((item) => item.decision === "accepted" ? { ...item, status: "verified", research_status: "verified" } : item);
    const title = update ? `${isIncremental(run) ? "审核通过" : "历史核对通过"}的 ${run?.accepted ?? "—"} 项数据是哪几项` : node.agent ? `${node.label}：${isIncremental(run) ? "逐公司、逐指标结果" : "历史核对结果（新增未统计）"}` : `本次 ${run?.tasks ?? "—"} 项指标结果清单`;
    const main = update ? mainTableChanges(run?.publication) : null;
    const visible = update ? visibleChanges(run?.publication) : null;
    const note = update ? `实际读取 ${items.length} 项审核档案；${main ? `原运行记录主表新增 ${main.added} 行、升级 ${main.upgraded} 行；` : "原运行主表新增或升级数量未记录；"}${visible ? `原发布时页面指标新增 ${visible.added} 项、变更 ${visible.changed} 项、删除 ${visible.removed} 项。` : "原页面数值变化未记录。"}后续修复及当前保存情况以逐项回读为准。` : `只列本节点的公司与指标；${isIncremental(run) ? "数据通过不等于已入库；失败原因逐项写明" : "历史核对结果不代表数据库缺失，也不能换算成新增数据数量"}；共 ${items.length} 项处理记录。`;
    return section(title, note, selected.map((raw, i) => { const existing = (raw.research_status || raw.status) === "no_update"; const item = existing && raw.latest_baseline ? { ...raw, ...raw.latest_baseline, baseline: [raw.latest_baseline] } : { ...raw, baseline: raw.latest_baseline ? [raw.latest_baseline] : [] }; return `<article><strong>${i + 1}. ${esc(item.company)} · ${esc(item.metric)}</strong><p>${esc(metricValue(item))} · ${esc(item.period || "报告期未记录")} · ${esc(itemLabel(item.research_status || item.status || (item.decision === "accepted" ? "verified" : "conflict"), isIncremental(run)))}</p><p>${esc(plainText(item.reason || (item.reasons || []).join("；")))}</p>${!existing && item.baseline?.length ? `<p>库内已有：${item.baseline.map((old) => esc(`${old.period || "报告期未记录"} · ${metricValue(old)}`)).join("；")}</p>` : ""}<p>${(item.sources || [item.source_url]).filter(Boolean).map((source) => link(typeof source === "string" ? source : source.url)).join("<br>")}</p></article>`; }));
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
      <p>逐次展示实际提交给搜索引擎的完整关键词及返回结果；搜索结果尚未经过原文核对。</p>
      <div class="news-lineage-preview-scroll" role="region" aria-label="逐次搜索关键词与返回结果" tabindex="0">${searches.map((search, index) => `<article class="research-search-record"><strong>${index + 1}. ${esc(search.company || "公司未记录")} · ${esc(plainText(search.metric || "最新数据"))}</strong>
        <p class="research-search-query">搜索关键词：${esc(search.query)}</p><details class="news-lineage-technical"><summary>搜索执行信息</summary><p>${esc(search.ts || "搜索时间未记录")} · ${esc(search.provider || "未记录")}</p></details>
        ${(search.results || []).length ? `<div class="research-search-results"><strong>本次返回 ${search.results.length} 条结果</strong><ol>${search.results.map((result) => `<li><strong>${esc(result.title || "标题未记录")}</strong><p>${link(result.url)}</p><p>${esc(result.snippet || "摘要未记录")}</p></li>`).join("")}</ol></div>` : "<p>本次未返回搜索结果；不能据此判断没有相关数据。</p>"}</article>`).join("") || "<p>本节点尚无已保存的搜索记录；关键词和结果将在搜索完成后显示。</p>"}</div></section>`;
  }
  function companyCoverageOverview(node, run) {
    if (!node.agent) return "";
    const reports = node.agent.reports || [];
    const coverage = reportsCoverage(reports);
    if (isIncremental(run)) return `<section class="news-lineage-dialog-section"><header><h3>各公司最新数据搜索结果</h3></header>${reports.map((report) => `<article><strong>${esc(report.company)}</strong><p>${resultCounts([report])}</p></article>`).join("")}</section>`;
    return `<section class="news-lineage-dialog-section research-actual-list"><header><h3>分公司历史核对记录</h3><span>历史核对通过 ${coverage.collected}/${coverage.total} 项</span></header><p>以下仅为旧流程核对记录；不代表原库缺失，新增数据数量未统计。</p><div class="news-lineage-preview-scroll" role="region" aria-label="分公司历史核对记录" tabindex="0">${reports.map((report, index) => { const current = reportCoverage(report); return `<article><strong>${index + 1}. ${esc(report.company)} · 历史核对通过 ${current.collected}/${current.total} 项</strong><p>${esc(reportTerms[report.status] || report.status || "未记录状态")}</p></article>`; }).join("") || "<p>暂无分公司研究记录。</p>"}</div></section>`;
  }
  function detail(node, snapshot, date) {
    const run = snapshot?.date === date ? snapshot.run : null;
    const agent = node.agent;
    const agents = agent ? [agent] : (snapshot?.date === date ? snapshot.agents || [] : []);
    const events = (snapshot?.date === date ? snapshot.events || [] : []).filter((event) => !node.assignment || event.agent_id === node.assignment.key);
    const field = (name, value) => `<div><dt>${esc(name)}</dt><dd>${value}</dd></div>`;
    const records = agents.flatMap((a) => (a.reports || []).map((report) => ({ a, report })));
    const coverage = reportsCoverage(records.map(({ report }) => report));
    const resultLabel = !run ? "尚无本次结果" : run.display_status === "cancelled"
      ? `本轮已由用户中止；已保存 ${records.reduce((count, { report }) => count + (report.items || []).length, 0)} 项指标记录，未继续写入四库或生成页面分析`
      : run.status === "running"
      ? `研究仍在进行，已保存 ${records.reduce((count, { report }) => count + (report.items || []).length, 0)} 项指标记录；最终通过数量待汇总校验`
      : isIncremental(run) ? resultCounts((snapshot.agents || []).flatMap((a) => a.reports || [])) : `已核对 ${run.accepted ?? "未提供"} 项，待核对或缺失 ${run.review ?? "未提供"} 项（历史运行未区分新增与重复数据）`;
    return `<header><div><span>${esc(date)} · ${run && !isIncremental(run) ? "历史运行（新增数据未统计）" : "查找最新数据并更新四库"} · 节点详情</span><h2>${esc(node.label)}</h2><p>${esc(plainText(node.purpose))}</p></div><form method="dialog"><button type="submit" aria-label="关闭节点详情">×</button></form></header>
      <div class="news-lineage-dialog-content research-node-detail">
      ${researchMatrix(node, snapshot, date)}
      ${node.key === "research-update" ? storageDetails(run) : ["research-dispatch", "research-publish"].includes(node.key) ? actualList(node, snapshot, date) : decisionGroups(node, snapshot, date)}
      <section class="news-lineage-dialog-section research-outcome"><header><h3>本节点结果</h3></header><p>${esc(node.key === "research-merge" ? finalReviewSummary(snapshot?.date === date ? snapshot : {}) : node.agent ? resultCounts(node.agent.reports || []) : node.key === "research-publish" ? `${run?.display_status === "cancelled" ? "本轮已中止，未生成分析" : aiNote(run?.publication)}；页面${run?.publication?.pages?.status === "published" ? "已发布" : "发布状态：" + pageState(run?.publication?.pages?.status)}` : node.key === "research-update" ? `${updateSummary(run)}。${run?.publication?.database_updated ? "四库写入已完成。" : run?.display_status === "cancelled" ? "本轮已中止，未执行四库写入。" : "尚未确认字段数据已保存。"}` : resultLabel)}</p>${snapshot?.task?.task_id ? `<button type="button" class="research-open-task-log" data-research-task-log="${esc(snapshot.task.task_id)}">在任务日志中打开本轮记录</button>` : ""}</section>
      ${node.key === "research-publish" && fallbackNote(run?.publication) ? '<section class="news-lineage-dialog-section"><header><h3>AI 未生成原因</h3></header><p>原批次存在模型调用失败或校验未通过，未生成部分不计作 AI 成果。规则结果不再作为 AI 分析展示或发布；原始失败记录保留在运行日志中，数据库已入库结果不受影响。</p></section>' : ""}
      ${node.assignment ? `<details class="news-lineage-technical research-search-disclosure"><summary>查看检索过程与搜索结果</summary>${searchHistory(node, agents, events)}</details>` : ""}
      <details class="news-lineage-technical"><summary>运行日志与详细依据</summary>
      ${companyCoverageOverview(node, run)}
      <section class="news-lineage-dialog-section"><header><h3>这个节点如何处理</h3></header><ol>${node.details.map((text) => `<li>${esc(text)}</li>`).join("")}</ol></section>
      <section class="news-lineage-dialog-section"><header><h3>本次运行</h3></header><dl>${field("运行编号", esc(run?.run_id || "所选日期没有六Agent任务记录"))}${field("开始时间", esc(run?.started_at || "—"))}${field("结束时间", esc(run?.completed_at || "—"))}${field("本次结果", esc(resultLabel))}</dl></section>
      ${node.publication ? `<section class="news-lineage-dialog-section"><header><h3>四库及页面交付明细</h3></header><pre>${esc(JSON.stringify(node.publication, null, 2))}</pre></section>` : ""}
      <section class="news-lineage-dialog-section"><header><h3>逐公司、逐指标处理结果</h3><span>${records.length} 份公司报告 · ${isIncremental(run) ? resultCounts(records.map(({ report }) => report)) : `历史核对通过 ${coverage.collected}/${coverage.total} 项`}</span></header>
      ${records.map(({ a, report }) => { const companyCoverage = reportCoverage(report); return `<details class="research-company"><summary>${esc(report.company)} · ${isIncremental(run) ? resultCounts([report]) : `历史核对通过 ${companyCoverage.collected}/${companyCoverage.total} 项`} · ${esc(reportTerms[report.status] || report.status || "未记录状态")}</summary>
        ${(report.items || []).map((item) => `<article class="research-metric"><h4>${esc(item.metric)} <small>${esc(itemLabel(item.status, isIncremental(run)))}</small></h4><dl>${field("记录值", esc(item.value ?? "无可更新值"))}${field("报告期与单位", esc([item.period, item.unit].filter(Boolean).join(" · ") || "—"))}${field("处理说明", esc(plainText(item.reason || "—")))}${field("原文", link(item.source_url || "—"))}${field("原文摘录", esc(item.quote || "—"))}${field("报告期与单位说明", esc(item.context_quote || "—"))}${field("公司名称所在原文", esc(item.entity_quote || "公司见原文摘录"))}${field("来源内容哈希", esc(item.evidence_hash || "—"))}</dl></article>`).join("")}
        <details><summary>全部检索与网页读取记录</summary>${(report.searches || []).map((search) => `<article><strong>${esc(search.metric)}</strong><p>检索：${esc(search.query)} · ${esc(search.provider)}</p><ul>${(search.results || []).map((r) => `<li>${link(r.url)}<p>${esc(r.title)} · ${esc(r.snippet)}</p></li>`).join("")}</ul></article>`).join("")}
        ${Object.entries(report.pages || {}).map(([url, page]) => `<p>${link(url)} · HTTP ${esc(page.http_status)} · ${page.opened ? "已读取" : "读取失败"} ${esc(page.blocked_reason || "")}</p>`).join("")}</details></details>`; }).join("") || "<p>该节点的实际处理记录将在任务运行后显示。</p>"}</section>
      <section class="news-lineage-dialog-section"><header><h3>执行时间线</h3><span>${events.length} 条记录</span></header><ol>${events.map((event) => `<li><time>${esc(event.ts)}</time> · ${esc(plainText(event.message))}<details><summary>${esc(event.phase)} · 查看原始处理记录</summary><pre>${esc(JSON.stringify(event.data || {}, null, 2))}</pre></details></li>`).join("") || "<li>暂无执行记录。</li>"}</ol></section></details></div>`;
  }
  function storageDetails(run) {
    const check = run?.publication?.storage_readback;
    if (!check) return '<section class="news-lineage-dialog-section"><p>尚无逐项回读证据，不能仅凭审核通过数确认入库。</p></section>';
    const written = writtenCount(check);
    const rowWritten = (item) => ["written", "saved"].includes(item.main_table?.status);
    const tableName = (path) => path?.includes("cloud_vendor_metrics") ? "云厂商年度指标表" : path?.includes("quarterly_metrics") ? "运营商正式指标表（香港／内地／国际）" : "目标表尚未明确";
    return `<section class="news-lineage-dialog-section research-storage-results"><header><h3>正式表入库结果</h3><span>回读 ${esc(check.checked_at)}</span></header><p>${esc(updateSummary(run))}</p>${run?.publication?.storage_replay ? `<p>本轮修复累计补写 ${esc(run.publication.storage_replay.total_added_rows ?? run.publication.storage_replay.added_rows)} 行；最近一次重跑新增 ${esc(run.publication.storage_replay.added_rows)} 行。已入库数量包含本轮先前写入且回读一致的记录，重跑不重复加行。</p>` : ""}${[true, false].map((success) => {
      const rows = (check.items || []).filter((item) => rowWritten(item) === success);
      const tables = new Map();
      rows.forEach((item) => { const path = item.main_table?.path || item.path || "未记录"; if (!tables.has(path)) tables.set(path, []); tables.get(path).push(item); });
      const count = success ? written : Math.max(0, check.accepted - written);
      return `<details class="research-storage-group ${success ? "is-written" : "is-not-written"}" open><summary>${success ? "已入库" : "未入库"} <b>${count} 项</b></summary>${[...tables.entries()].map(([path, items]) => `<section class="research-formal-table"><h4>${esc(tableName(path))} · ${items.length} 项</h4><p class="research-table-path">实际表文件：<code>${esc(path)}</code></p><div class="research-table-scroll" role="region" aria-label="${success ? "已入库" : "未入库"}的具体表格" tabindex="0"><table><caption>${success ? "正式表当前记录" : "写入失败或未确认的记录"}</caption><thead><tr><th>公司／报告期</th><th>新增指标字段</th><th>提交值</th><th>正式表回读值</th><th>结果与原因</th></tr></thead><tbody>${items.map((item) => { const row = item.main_table || {}; return `<tr data-research-storage-row data-period="${esc(reportPeriod(item).key)}" data-company="${esc(item.company)}" data-metric="${esc(item.metric)}"><th scope="row">${esc(item.company)}<small>${esc(row.period || item.period || "期间未明确")}${row.period_end ? `<br>截至 ${esc(row.period_end)}` : ""}</small></th><td>${esc(row.metric_zh || item.metric)}<code>${esc(row.metric_key || "未形成字段映射")}</code></td><td>${esc(row.candidate_value ?? item.value ?? "—")}<small>${esc(row.unit || item.unit || "")}${row.currency ? ` · ${esc(row.currency)}` : ""}</small></td><td>${esc(row.current_value ?? "未找到匹配记录")}<small>${esc(row.unit || "")}</small></td><td><strong>${success ? "已入库" : "未入库"}</strong><p>${esc(row.reason || item.reason || "未保存写入结果")}</p>${row.source_url ? link(row.source_url, "官方来源") : ""}</td></tr>`; }).join("")}</tbody></table></div></section>`).join("") || `<p class="research-empty">${count ? "提交档案未完整读取，不能确认入库；请查看任务日志。" : success ? "本次没有已入库记录。" : "本次提交项均已入库，无未入库项。"}</p>`}</details>`;
    }).join("")}</section>`;
  }
  window.CmhkResearchDiagram = { build, detail, mount, decisionPage, finalReviewGroups, matrixModel, reportPeriod };
})();
