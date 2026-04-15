require('dotenv').config();

const { tavilySearch } = require('./tavily');
const { deepseekChat } = require('./deepseek');
const {
  upsertFindings,
  addJob,
  queryFindings,
  normalizeUrl,
  readDb,
  getMonitoringConfig
} = require('./db');

const MAX_ITEMS_PER_QUERY = Number(process.env.MAX_ITEMS_PER_QUERY || 3);

const CATEGORY_MAX_AGE_DAYS = {
  财报: 420,
  产品发布会: 300,
  中标公示: 420,
  高管言论: 420,
  政策法规: 730,
  宏观数据: 730
};

const scanState = {
  running: false,
  trigger: null,
  startedAt: null,
  finishedAt: null,
  durationMs: null,
  lastError: null,
  lastResult: null,
  stopRequested: false,
  stopRequestedAt: null,
  stopReason: null,
  progress: {
    totalQueries: 0,
    completedQueries: 0,
    currentQuery: null,
    written: 0
  }
};

let activeScanPromise = null;
let activeRequestController = null;

function parseJsonPayload(content) {
  if (!content || typeof content !== 'string') return null;

  const cleaned = content.trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    const codeBlockMatch = cleaned.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
    if (!codeBlockMatch) return null;
    try {
      return JSON.parse(codeBlockMatch[1]);
    } catch {
      return null;
    }
  }
}

function normalizePublishedAt(value) {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return null;
  return new Date(timestamp).toISOString();
}

function getSourceName(url) {
  if (!url) return 'unknown';
  try {
    return new URL(url).hostname;
  } catch {
    return 'unknown';
  }
}

function truncateText(value, maxLength = 1200) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return '';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function getCurrentYear() {
  return new Date().getFullYear();
}

function extractYears(text) {
  const currentYear = getCurrentYear();
  const source = String(text || '');
  const years = new Set();
  source.replace(/(?:19|20)\d{2}/g, (match) => {
    const year = Number(match);
    if (Number.isFinite(year) && year >= 2000 && year <= currentYear + 1) {
      years.add(year);
    }
    return match;
  });
  return Array.from(years).sort((a, b) => a - b);
}

function detectFiscalYear(text) {
  const currentYear = getCurrentYear();
  const source = String(text || '');
  const patterns = [
    /(20\d{2})\s*年(?:度)?\s*(?:业绩|财报|年报|中期业绩|全年业绩)/i,
    /(?:FY|Fiscal\s*Year)\s*(20\d{2})/i,
    /(?:annual\s+results|annual\s+report|earnings|financial\s+results)\s*(?:for\s+|fy\s*)?(20\d{2})/i
  ];

  for (const pattern of patterns) {
    const match = source.match(pattern);
    if (!match) continue;
    const year = Number(match[1]);
    if (Number.isFinite(year) && year >= 2000 && year <= currentYear + 1) {
      return year;
    }
  }

  return null;
}

function buildTimeAwareQuery(query, category) {
  const currentYear = getCurrentYear();
  const base = String(query || '').trim();
  if (!base) return '';

  const normalized = base.toLowerCase();
  const hasCurrentYear = normalized.includes(String(currentYear));
  const hasPrevYear = normalized.includes(String(currentYear - 1));
  const hasLatestWord = /(latest|recent|newest|最新|近期|本周|本月)/i.test(base);

  const suffix = [];
  if (!hasCurrentYear) suffix.push(String(currentYear));
  if (!hasPrevYear) suffix.push(String(currentYear - 1));
  if (!hasLatestWord) {
    suffix.push(category === '财报' ? 'latest earnings 最新业绩' : 'latest updates 最新动态');
  }

  return suffix.length ? `${base} ${suffix.join(' ')}` : base;
}

function isStaleByPublishedAt(item, category) {
  const maxAgeDays = Number(CATEGORY_MAX_AGE_DAYS[category] || 420);
  const baseline = item?.publishedAt;
  if (!baseline) return false;
  const publishedMs = Date.parse(String(baseline));
  if (Number.isNaN(publishedMs)) return false;
  const ageDays = (Date.now() - publishedMs) / (24 * 60 * 60 * 1000);
  return ageDays > maxAgeDays;
}

function isStaleByReportYear(item, category) {
  if (category !== '财报') return false;
  const currentYear = getCurrentYear();

  const title = String(item?.title || '');
  const content = String(item?.content || '');
  const fiscalYear = detectFiscalYear(`${title} ${content}`);
  if (fiscalYear && fiscalYear <= currentYear - 2) {
    return true;
  }

  const years = extractYears(`${title} ${content}`);
  if (!years.length) return false;
  const maxYear = Math.max(...years);
  const financeCue = /(业绩|财报|年报|results|earnings|annual report|interim report)/i.test(`${title} ${content}`);
  return financeCue && maxYear <= currentYear - 2;
}

function isStaleByYearHint(item) {
  const currentYear = getCurrentYear();
  const title = String(item?.title || '');
  const content = String(item?.content || '');
  const years = extractYears(`${title} ${content}`);
  if (!years.length) return false;
  return Math.max(...years) <= currentYear - 2;
}

function isStaleResult(item, category) {
  return isStaleByPublishedAt(item, category)
    || isStaleByReportYear(item, category)
    || isStaleByYearHint(item);
}

function buildFallbackInterpretation(item) {
  return {
    id: item.id,
    summary: truncateText(item.content || item.title, 220),
    significance: '基于公开网页摘要提炼，需结合原文进一步复核业务影响。',
    keywords: []
  };
}

function createStopError(reason) {
  const error = new Error(reason || '扫描已被中止');
  error.code = 'SCAN_STOPPED';
  return error;
}

function isStopError(error) {
  return error?.code === 'SCAN_STOPPED';
}

function shouldStopScan() {
  return Boolean(scanState.stopRequested);
}

function throwIfStopRequested(defaultReason) {
  if (!shouldStopScan()) return;
  throw createStopError(scanState.stopReason || defaultReason || '扫描已被中止');
}

function beginRequestContext() {
  const controller = new AbortController();
  activeRequestController = controller;
  return controller;
}

function endRequestContext(controller) {
  if (activeRequestController === controller) {
    activeRequestController = null;
  }
}

async function enrichBatch(items, context, options = {}) {
  if (!items.length) return [];

  const prompt = [
    {
      role: 'system',
      content: [
        '你是CMHK战略研究部分析员。',
        '任务：基于提供的公开网页标题、摘要、发布时间与链接，生成正式、克制、可复核的情报提炼。',
        '约束：不得编造任何未在输入中出现的事实。',
        '输出：必须是JSON数组，每一项字段为 id、summary、significance、keywords。',
        '要求：keywords 为数组；summary 与 significance 使用中文。'
      ].join(' ')
    },
    {
      role: 'user',
      content: JSON.stringify({
        competitor: context.competitor,
        region: context.region,
        category: context.category,
        query: context.query,
        items: items.map((item) => ({
          id: item.id,
          title: item.title,
          snippet: item.content,
          url: item.url,
          publishedAt: item.publishedAt
        }))
      })
    }
  ];

  const rawResponse = await deepseekChat(prompt, 0.1, {
    signal: options.signal
  });
  const parsed = parseJsonPayload(rawResponse);

  if (!Array.isArray(parsed)) {
    return items.map(buildFallbackInterpretation);
  }

  const mapped = new Map();
  for (const row of parsed) {
    if (!row || typeof row !== 'object' || !row.id) continue;
    mapped.set(String(row.id), {
      id: String(row.id),
      summary: truncateText(typeof row.summary === 'string' ? row.summary : '', 320),
      significance: truncateText(typeof row.significance === 'string' ? row.significance : '', 320),
      keywords: Array.isArray(row.keywords)
        ? row.keywords.map((value) => String(value).trim()).filter(Boolean).slice(0, 12)
        : []
    });
  }

  return items.map((item) => {
    const parsedItem = mapped.get(item.id);
    if (!parsedItem || !parsedItem.summary) {
      return buildFallbackInterpretation(item);
    }

    return {
      ...parsedItem,
      significance: parsedItem.significance || '需结合原始来源进一步评估对CMHK的影响。'
    };
  });
}

function transformSearchResult(rawItem) {
  const title = truncateText(rawItem.title || '', 240);
  const normalized = {
    title,
    content: truncateText(rawItem.content || '', 1200),
    url: normalizeUrl(rawItem.url || ''),
    publishedAt: normalizePublishedAt(rawItem.published_time)
  };

  if (!normalized.title) return null;
  if (!normalized.url || !/^https?:\/\//i.test(normalized.url)) return null;

  return normalized;
}

function getTotalQueryCount(monitoredCompetitors) {
  return monitoredCompetitors.reduce((count, competitor) => {
    return count + competitor.topics.reduce((topicCount, topic) => topicCount + topic.queries.length, 0);
  }, 0);
}

function buildScanTasks(monitoredCompetitors) {
  const perObjectTasks = (monitoredCompetitors || []).map((competitor) => {
    const tasks = [];
    for (const topic of competitor.topics || []) {
      for (const query of topic.queries || []) {
        tasks.push({
          competitor,
          topic,
          query
        });
      }
    }
    return tasks;
  });

  const total = perObjectTasks.reduce((sum, row) => sum + row.length, 0);
  const queue = [];
  let cursor = 0;

  while (queue.length < total) {
    let added = false;
    for (const tasks of perObjectTasks) {
      if (cursor >= tasks.length) continue;
      queue.push(tasks[cursor]);
      added = true;
    }
    if (!added) break;
    cursor += 1;
  }

  return queue;
}

function createProgress(totalQueries) {
  return {
    totalQueries,
    completedQueries: 0,
    currentQuery: null,
    written: 0
  };
}

function updateProgress(step = {}) {
  scanState.progress = {
    ...scanState.progress,
    ...step
  };
}

function buildProgressLabel(completed, total) {
  const safeTotal = total > 0 ? total : 1;
  const pct = Math.min(100, Math.round((completed / safeTotal) * 100));
  return `${completed}/${total} (${pct}%)`;
}

function buildPartialResult(trigger, startMs, collectionStats) {
  return {
    trigger,
    stopped: true,
    stopReason: scanState.stopReason,
    durationMs: Date.now() - startMs,
    queryCount: collectionStats.queryCount,
    completedQueries: scanState.progress.completedQueries,
    sourceHits: collectionStats.sourceHits,
    skippedDuplicate: collectionStats.skippedDuplicate,
    skippedInvalid: collectionStats.skippedInvalid,
    skippedStale: collectionStats.skippedStale,
    queryErrors: collectionStats.queryErrors,
    inserted: collectionStats.inserted,
    updated: collectionStats.updated,
    totalWritten: collectionStats.totalWritten,
    totalFindings: collectionStats.totalFindings
  };
}

async function runFullScan(options = {}) {
  const trigger = options.trigger || 'manual';

  if (scanState.running) {
    const error = new Error('扫描任务正在执行，请稍后重试。');
    error.code = 'SCAN_IN_PROGRESS';
    throw error;
  }

  const monitoringConfig = getMonitoringConfig();
  const monitoredCompetitors = monitoringConfig.competitors;

  if (!Array.isArray(monitoredCompetitors) || !monitoredCompetitors.length) {
    throw new Error('当前监测配置为空，请先维护竞对名单与检索语句。');
  }

  const scanTasks = buildScanTasks(monitoredCompetitors);
  const totalQueries = scanTasks.length;

  scanState.running = true;
  scanState.trigger = trigger;
  scanState.startedAt = new Date().toISOString();
  scanState.finishedAt = null;
  scanState.durationMs = null;
  scanState.lastError = null;
  scanState.lastResult = null;
  scanState.stopRequested = false;
  scanState.stopRequestedAt = null;
  scanState.stopReason = null;
  scanState.progress = createProgress(totalQueries);

  const startMs = Date.now();
  const collectionStats = {
    queryCount: totalQueries,
    sourceHits: 0,
    skippedDuplicate: 0,
    skippedInvalid: 0,
    skippedStale: 0,
    queryErrors: 0,
    inserted: 0,
    updated: 0,
    totalWritten: 0,
    totalFindings: readDb().findings.length
  };

  addJob({
    type: 'scan',
    status: 'started',
    message: `开始执行${trigger === 'scheduled' ? '定时' : '手动'}扫描，总查询数 ${totalQueries}。`
  });

  try {
    const seen = new Set();

    for (const task of scanTasks) {
      throwIfStopRequested('扫描已在检索前中止');

      const { competitor, topic, query } = task;
      const effectiveQuery = buildTimeAwareQuery(query, topic.category);
      updateProgress({
        currentQuery: `${competitor.name} / ${topic.category}`
      });

      const queryShort = truncateText(effectiveQuery, 96);
      const queryStats = {
        rawHits: 0,
        validCandidates: 0,
        inserted: 0,
        updated: 0,
        written: 0,
        skippedInvalid: 0,
        skippedStale: 0,
        skippedDuplicate: 0,
        warning: null
      };

      let searchResult;
      let searchController;
      try {
        searchController = beginRequestContext();
        searchResult = await tavilySearch(effectiveQuery, {
          maxResults: MAX_ITEMS_PER_QUERY * 2,
          signal: searchController.signal
        });
      } catch (error) {
        if (scanState.stopRequested && error?.code === 'REQUEST_ABORTED') {
          throw createStopError(scanState.stopReason || '扫描已中止');
        }

        collectionStats.queryErrors += 1;
        queryStats.warning = `检索失败：${error.message}`;
        const completedQueries = scanState.progress.completedQueries + 1;
        updateProgress({ completedQueries });
        addJob({
          type: 'scan_progress',
          status: 'warning',
          message: `[${buildProgressLabel(completedQueries, totalQueries)}] ${competitor.name} ${topic.category} | ${queryStats.warning} | query="${queryShort}"`
        });
        continue;
      } finally {
        endRequestContext(searchController);
      }

      throwIfStopRequested('扫描已在检索后中止');

      const results = Array.isArray(searchResult.results)
        ? searchResult.results.slice(0, MAX_ITEMS_PER_QUERY * 2)
        : [];

      queryStats.rawHits = results.length;
      collectionStats.sourceHits += results.length;

      const candidates = [];
      for (const rawItem of results) {
        const item = transformSearchResult(rawItem);
        if (!item) {
          collectionStats.skippedInvalid += 1;
          queryStats.skippedInvalid += 1;
          continue;
        }

        if (isStaleResult(item, topic.category)) {
          collectionStats.skippedInvalid += 1;
          queryStats.skippedInvalid += 1;
          collectionStats.skippedStale += 1;
          queryStats.skippedStale += 1;
          continue;
        }

        const dedupeKey = `${competitor.name}::${item.url}`;
        if (seen.has(dedupeKey)) {
          collectionStats.skippedDuplicate += 1;
          queryStats.skippedDuplicate += 1;
          continue;
        }

        seen.add(dedupeKey);
        candidates.push({
          ...item,
          id: `${competitor.name}_${topic.category}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
        });
      }

      if (candidates.length > MAX_ITEMS_PER_QUERY) {
        candidates.splice(MAX_ITEMS_PER_QUERY);
      }
      queryStats.validCandidates = candidates.length;

      if (candidates.length) {
        let interpretations;
        let enrichController;
        try {
          enrichController = beginRequestContext();
          interpretations = await enrichBatch(candidates, {
            competitor: competitor.name,
            region: competitor.region,
            category: topic.category,
            query
          }, {
            signal: enrichController.signal
          });
        } catch (error) {
          if (scanState.stopRequested && error?.code === 'REQUEST_ABORTED') {
            throw createStopError(scanState.stopReason || '扫描已中止');
          }

          queryStats.warning = `智能提炼失败，已自动使用保守摘要：${error.message}`;
          interpretations = candidates.map(buildFallbackInterpretation);
        } finally {
          endRequestContext(enrichController);
        }

        throwIfStopRequested('扫描已在入库前中止');

        const findingsChunk = candidates.map((item) => {
          const interpreted = interpretations.find((row) => row.id === item.id) || buildFallbackInterpretation(item);
          return {
            competitor: competitor.name,
            region: competitor.region,
            category: topic.category,
            title: item.title,
            summary: interpreted.summary,
            significance: interpreted.significance,
            keywords: interpreted.keywords,
            sourceUrl: item.url,
            sourceName: getSourceName(item.url),
            publishedAt: item.publishedAt,
            query: effectiveQuery,
            rawSnippet: item.content,
            capturedAt: new Date().toISOString()
          };
        });

        const persisted = upsertFindings(findingsChunk);
        collectionStats.inserted += persisted.inserted;
        collectionStats.updated += persisted.updated;
        collectionStats.totalWritten += persisted.totalWritten;
        collectionStats.totalFindings = persisted.totalFindings;
        queryStats.inserted = persisted.inserted;
        queryStats.updated = persisted.updated;
        queryStats.written = persisted.totalWritten;

        updateProgress({
          written: scanState.progress.written + persisted.totalWritten
        });
      }

      const completedQueries = scanState.progress.completedQueries + 1;
      updateProgress({ completedQueries });

      const isWarning = Boolean(queryStats.warning) || queryStats.written === 0;
      const detail = [
        `[${buildProgressLabel(completedQueries, totalQueries)}] ${competitor.name} ${topic.category}`,
        `检索${queryStats.rawHits}条`,
        `有效${queryStats.validCandidates}条`,
        `入库${queryStats.written}条（新增${queryStats.inserted}/更新${queryStats.updated}）`,
        `无效过滤${queryStats.skippedInvalid}条（含过旧${queryStats.skippedStale}条）`,
        `重复过滤${queryStats.skippedDuplicate}条`,
        `累计写入${scanState.progress.written}条`,
        `query="${queryShort}"`
      ];

      if (queryStats.warning) {
        detail.push(`备注：${queryStats.warning}`);
      }

      addJob({
        type: 'scan_progress',
        status: isWarning ? 'warning' : 'success',
        message: detail.join(' | ')
      });
    }

    if (collectionStats.queryErrors === collectionStats.queryCount) {
      throw new Error('全部检索请求失败，请检查网络连通性、Tavily 配额或访问策略。');
    }

    const durationMs = Date.now() - startMs;

    const result = {
      trigger,
      stopped: false,
      durationMs,
      queryCount: collectionStats.queryCount,
      completedQueries: scanState.progress.completedQueries,
      sourceHits: collectionStats.sourceHits,
      skippedDuplicate: collectionStats.skippedDuplicate,
      skippedInvalid: collectionStats.skippedInvalid,
      skippedStale: collectionStats.skippedStale,
      queryErrors: collectionStats.queryErrors,
      inserted: collectionStats.inserted,
      updated: collectionStats.updated,
      totalWritten: collectionStats.totalWritten,
      totalFindings: collectionStats.totalFindings
    };

    scanState.finishedAt = new Date().toISOString();
    scanState.durationMs = durationMs;
    scanState.lastResult = result;
    updateProgress({ currentQuery: null });

    addJob({
      type: 'scan',
      status: result.totalWritten > 0 ? 'success' : 'warning',
      message: result.totalWritten > 0
        ? `扫描完成：写入${result.totalWritten}条（新增${result.inserted}，更新${result.updated}），耗时${Math.round(durationMs / 1000)}秒。`
        : `扫描完成但未写入新情报，耗时${Math.round(durationMs / 1000)}秒。建议检查查询条件或网络连通性。`
    });

    return result;
  } catch (error) {
    scanState.finishedAt = new Date().toISOString();
    scanState.durationMs = Date.now() - startMs;
    updateProgress({ currentQuery: null });

    if (isStopError(error)) {
      const partialResult = buildPartialResult(trigger, startMs, collectionStats);
      scanState.lastError = null;
      scanState.lastResult = partialResult;

      addJob({
        type: 'scan',
        status: 'warning',
        message: `扫描已截停：${scanState.stopReason || error.message}。已完成 ${scanState.progress.completedQueries}/${scanState.progress.totalQueries}，累计写入 ${scanState.progress.written} 条。`
      });

      return partialResult;
    }

    scanState.lastError = error.message;

    addJob({
      type: 'scan',
      status: 'failed',
      message: `扫描失败：${error.message}`
    });

    throw error;
  } finally {
    activeRequestController = null;
    scanState.running = false;
    scanState.stopRequested = false;
    scanState.stopRequestedAt = null;
    scanState.stopReason = null;
  }
}

function startScan(options = {}) {
  if (scanState.running) {
    const error = new Error('扫描任务正在执行，请稍后重试。');
    error.code = 'SCAN_IN_PROGRESS';
    throw error;
  }

  activeScanPromise = runFullScan(options)
    .catch((error) => {
      if (!isStopError(error)) {
        throw error;
      }
      return scanState.lastResult;
    })
    .finally(() => {
      activeScanPromise = null;
    });

  return {
    accepted: true,
    state: getScanState()
  };
}

async function waitCurrentScan() {
  return activeScanPromise;
}

function requestStopScan(options = {}) {
  const reason = String(options.reason || '用户手动截停').trim();

  if (!scanState.running) {
    return {
      accepted: false,
      state: getScanState(),
      message: '当前没有正在执行的扫描任务。'
    };
  }

  if (scanState.stopRequested) {
    return {
      accepted: true,
      state: getScanState(),
      message: '截停请求已发出，正在等待当前步骤结束。'
    };
  }

  scanState.stopRequested = true;
  scanState.stopRequestedAt = new Date().toISOString();
  scanState.stopReason = reason;

  if (activeRequestController && !activeRequestController.signal.aborted) {
    activeRequestController.abort(new Error('scan-stop-requested'));
  }

  addJob({
    type: 'scan',
    status: 'warning',
    message: `收到扫描截停指令：${reason}。系统正在中止当前请求。`
  });

  return {
    accepted: true,
    state: getScanState(),
    message: '截停指令已接收，正在终止当前请求。'
  };
}

function getRecentFindings(filters = {}) {
  return queryFindings(filters);
}

function getScanState() {
  return {
    ...scanState
  };
}

module.exports = {
  runFullScan,
  startScan,
  waitCurrentScan,
  requestStopScan,
  getRecentFindings,
  getScanState
};
