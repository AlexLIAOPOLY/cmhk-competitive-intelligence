const { tavilySearch } = require('./tavily');
const { deepseekChat } = require('./deepseek');
const { upsertFindings, addJob, normalizeUrl } = require('./db');

const QUERY_TIMEOUT_MS = Number(process.env.COVERAGE_QUERY_TIMEOUT_MS || 25000);
const MAX_RESULTS_PER_QUERY = Number(process.env.COVERAGE_MAX_RESULTS_PER_QUERY || 5);
const MAX_QUERIES = Number(process.env.COVERAGE_MAX_QUERIES || 40);
const DEEPSEEK_TIMEOUT_MS = Number(process.env.COVERAGE_DS_TIMEOUT_MS || 90000);

const TRUSTED_DOMAINS = [
  'vodafone.com',
  'orange.com',
  'pccw.com',
  'hkt.com',
  'smartone.com',
  'chinamobileltd.com',
  'chinatelecom-h.com',
  'chinaunicom.com.hk',
  'china-tower.com',
  'att.com',
  'verizon.com',
  'deutschetelekom.com',
  'telefonica.com',
  'reuters.com',
  'bloomberg.com',
  'ft.com',
  'wsj.com',
  'lightreading.com',
  'telecoms.com',
  'developingtelecoms.com',
  'totaltele.com',
  'mobileworldlive.com',
  'ofca.gov.hk',
  'gov.hk',
  'gsma.com',
  'itu.int',
  'oecd.org'
];

const NOISE_KEYWORDS = [
  'nba', 'nfl', 'mlb', 'soccer', 'football', 'celebrity', 'movie', 'music', 'gaming',
  'lottery', 'vogue', 'fashion', 'beauty', 'hospital', 'biotech', 'mining', 'drilling',
  '娱乐', '电影', '博彩', '时尚', '矿业', '医美'
];

const COVERAGE_TARGETS = [
  {
    name: 'Vodafone',
    region: 'Global',
    aliases: ['Vodafone'],
    irDomain: 'vodafone.com'
  },
  {
    name: 'Orange',
    region: 'Global',
    aliases: ['Orange', 'Orange Group'],
    irDomain: 'orange.com'
  },
  {
    name: 'PCCW',
    region: 'Hong Kong',
    aliases: ['PCCW', 'HKT'],
    irDomain: 'pccw.com'
  },
  {
    name: 'SmarTone',
    region: 'Hong Kong',
    aliases: ['SmarTone', 'Smartone'],
    irDomain: 'smartone.com'
  },
  {
    name: 'China Mobile',
    region: 'China',
    aliases: ['China Mobile', '中国移动'],
    irDomain: 'chinamobileltd.com'
  },
  {
    name: 'China Telecom',
    region: 'China',
    aliases: ['China Telecom', '中国电信'],
    irDomain: 'chinatelecom-h.com'
  },
  {
    name: 'China Unicom',
    region: 'China',
    aliases: ['China Unicom', '中国联通'],
    irDomain: 'chinaunicom.com.hk'
  },
  {
    name: 'China Tower',
    region: 'China',
    aliases: ['China Tower', '中国铁塔'],
    irDomain: 'china-tower.com'
  }
];

function normalizeText(value) {
  return String(value || '').trim();
}

function truncateText(value, max = 300) {
  const text = normalizeText(value);
  if (!text) return '';
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function parseJsonPayload(content) {
  const cleaned = normalizeText(content);
  if (!cleaned) return null;

  try {
    return JSON.parse(cleaned);
  } catch {
    const match = cleaned.match(/```(?:json)?\s*([\s\S]*?)\s*```/i);
    if (!match) return null;
    try {
      return JSON.parse(match[1]);
    } catch {
      return null;
    }
  }
}

function extractHostname(url) {
  try {
    return new URL(String(url || '').trim()).hostname.toLowerCase();
  } catch {
    return '';
  }
}

function domainMatches(hostname, domain) {
  const host = String(hostname || '').toLowerCase();
  const target = String(domain || '').toLowerCase();
  if (!host || !target) return false;
  return host === target || host.endsWith(`.${target}`);
}

function isTrustedDomain(url) {
  const hostname = extractHostname(url);
  if (!hostname) return false;
  return TRUSTED_DOMAINS.some((domain) => domainMatches(hostname, domain));
}

function containsNoise(text) {
  const haystack = String(text || '').toLowerCase();
  if (!haystack) return false;
  return NOISE_KEYWORDS.some((word) => haystack.includes(word));
}

function containsAlias(text, alias) {
  const haystack = String(text || '').toLowerCase();
  const needle = String(alias || '').toLowerCase();
  if (!haystack || !needle) return false;

  if (/^[a-z0-9 .+-]+$/i.test(needle)) {
    return new RegExp(`\\b${needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`, 'i').test(haystack);
  }
  return haystack.includes(needle);
}

function normalizePublishedAt(value) {
  if (!value) return null;
  const timestamp = Date.parse(String(value));
  if (Number.isNaN(timestamp)) return null;
  return new Date(timestamp).toISOString();
}

function transformSearchResult(raw) {
  const title = truncateText(raw?.title, 240);
  const sourceUrl = normalizeUrl(raw?.url || '');
  if (!title || !sourceUrl || !/^https?:\/\//i.test(sourceUrl)) return null;

  const rawContent = truncateText(raw?.raw_content || '', 2800);
  const fallbackContent = truncateText(raw?.content || '', 1200);

  return {
    title,
    sourceUrl,
    rawSnippet: rawContent || fallbackContent,
    publishedAt: normalizePublishedAt(raw?.published_time)
  };
}

function buildCoverageQueries() {
  const queries = [];

  for (const target of COVERAGE_TARGETS) {
    const mainAlias = target.aliases[0];
    const cnAlias = target.aliases.find((alias) => /[\u4e00-\u9fa5]/.test(alias));
    const domain = target.irDomain;

    queries.push({
      competitor: target.name,
      region: target.region,
      aliases: target.aliases,
      category: '财报',
      irDomain: domain,
      query: `${mainAlias} 2025 annual results revenue EBITDA net profit capex site:${domain}`
    });
    queries.push({
      competitor: target.name,
      region: target.region,
      aliases: target.aliases,
      category: '财报',
      irDomain: domain,
      query: `${mainAlias} investor presentation 2025 guidance capex site:${domain}`
    });
    queries.push({
      competitor: target.name,
      region: target.region,
      aliases: target.aliases,
      category: '财报',
      irDomain: domain,
      query: `${mainAlias} 2025 results revenue EBITDA Reuters telecom`
    });

    if (cnAlias) {
      queries.push({
        competitor: target.name,
        region: target.region,
        aliases: target.aliases,
        category: '财报',
        irDomain: domain,
        query: `${cnAlias} 2025 年度业绩 营收 EBITDA 资本开支`
      });
    }
  }

  return queries.slice(0, MAX_QUERIES);
}

function buildFallbackInterpretation(item) {
  return {
    id: item.id,
    summary: truncateText(item.rawSnippet || item.title, 220),
    significance: '基于公开网页提炼，建议结合原文复核关键数字与结论。',
    keywords: []
  };
}

async function enrichBatch(items, context) {
  if (!items.length) return [];

  const prompt = [
    {
      role: 'system',
      content: [
        '你是CMHK战略研究助理。',
        '请仅基于输入内容输出JSON数组，每项字段：id、summary、significance、keywords。',
        'summary需简洁提炼事件事实；significance说明对运营商竞争与经营影响。',
        '不得编造输入中不存在的信息。'
      ].join(' ')
    },
    {
      role: 'user',
      content: JSON.stringify({
        competitor: context.competitor,
        category: context.category,
        query: context.query,
        items: items.map((item) => ({
          id: item.id,
          title: item.title,
          snippet: item.rawSnippet,
          sourceUrl: item.sourceUrl,
          publishedAt: item.publishedAt
        }))
      })
    }
  ];

  try {
    const raw = await deepseekChat(prompt, 0.1, { timeoutMs: DEEPSEEK_TIMEOUT_MS });
    const parsed = parseJsonPayload(raw);
    if (!Array.isArray(parsed)) {
      return items.map(buildFallbackInterpretation);
    }

    const map = new Map();
    for (const row of parsed) {
      if (!row || typeof row !== 'object' || !row.id) continue;
      map.set(String(row.id), {
        id: String(row.id),
        summary: truncateText(row.summary, 320),
        significance: truncateText(row.significance, 320),
        keywords: Array.isArray(row.keywords)
          ? row.keywords.map((item) => normalizeText(item)).filter(Boolean).slice(0, 10)
          : []
      });
    }

    return items.map((item) => {
      const enriched = map.get(item.id);
      if (!enriched || !enriched.summary) {
        return buildFallbackInterpretation(item);
      }
      return {
        ...enriched,
        significance: enriched.significance || '需结合后续披露进一步评估对CMHK影响。'
      };
    });
  } catch {
    return items.map(buildFallbackInterpretation);
  }
}

function isCandidateRelevant(item, aliases) {
  const title = normalizeText(item.title);
  const url = normalizeText(item.sourceUrl);
  const snippet = normalizeText(item.rawSnippet);
  const merged = `${title} ${url} ${snippet}`;

  const mention = aliases.some((alias) => containsAlias(`${title} ${url}`, alias) || containsAlias(merged, alias));
  if (!mention) return false;
  if (containsNoise(merged)) return false;

  return isTrustedDomain(url) || /earnings|results|revenue|ebitda|guidance|财报|业绩|营收|净利润|资本开支/i.test(merged);
}

async function runCoverageBoost(options = {}) {
  const queries = buildCoverageQueries();
  const maxResults = Math.max(3, Math.min(8, Number(options.maxResults || MAX_RESULTS_PER_QUERY)));
  const seen = new Set();
  const stats = {
    queryCount: queries.length,
    sourceHits: 0,
    keptCandidates: 0,
    queryErrors: 0,
    inserted: 0,
    updated: 0,
    totalWritten: 0,
    totalFindings: 0
  };

  addJob({
    type: 'coverage_boost',
    status: 'started',
    message: `开始执行定向覆盖增强，共 ${queries.length} 条检索。`
  });

  for (let i = 0; i < queries.length; i += 1) {
    const task = queries[i];
    const progress = `[${i + 1}/${queries.length}]`;
    const queryShort = truncateText(task.query, 96);

    let rawResults;
    try {
      rawResults = await tavilySearch(task.query, {
        maxResults: maxResults * 2,
        timeoutMs: QUERY_TIMEOUT_MS,
        topic: 'general',
        includeRawContent: true,
        includeDomains: [
          task.irDomain,
          'reuters.com',
          'bloomberg.com',
          'lightreading.com',
          'telecoms.com',
          'developingtelecoms.com',
          'totaltele.com'
        ].filter(Boolean),
        searchDepth: 'advanced'
      });
    } catch (error) {
      stats.queryErrors += 1;
      addJob({
        type: 'coverage_boost_progress',
        status: 'warning',
        message: `${progress} ${task.competitor} ${task.category} | 检索失败：${error.message} | query="${queryShort}"`
      });
      continue;
    }

    const transformed = Array.isArray(rawResults.results)
      ? rawResults.results.map(transformSearchResult).filter(Boolean)
      : [];

    stats.sourceHits += transformed.length;

    const filtered = [];
    for (const result of transformed) {
      const dedupeKey = `${task.competitor}::${result.sourceUrl}`;
      if (seen.has(dedupeKey)) continue;
      if (!isCandidateRelevant(result, task.aliases)) continue;
      seen.add(dedupeKey);
      filtered.push({
        ...result,
        id: `boost_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`
      });
      if (filtered.length >= maxResults) break;
    }

    stats.keptCandidates += filtered.length;
    if (!filtered.length) {
      addJob({
        type: 'coverage_boost_progress',
        status: 'warning',
        message: `${progress} ${task.competitor} ${task.category} | 无高相关候选 | query="${queryShort}"`
      });
      continue;
    }

    const interpretations = await enrichBatch(filtered, task);
    const findings = filtered.map((item) => {
      const interpreted = interpretations.find((row) => row.id === item.id) || buildFallbackInterpretation(item);
      return {
        competitor: task.competitor,
        region: task.region,
        category: task.category,
        title: item.title,
        summary: interpreted.summary,
        significance: interpreted.significance,
        keywords: interpreted.keywords,
        sourceUrl: item.sourceUrl,
        sourceName: extractHostname(item.sourceUrl),
        publishedAt: item.publishedAt,
        query: task.query,
        rawSnippet: item.rawSnippet,
        capturedAt: new Date().toISOString()
      };
    });

    const persisted = upsertFindings(findings);
    stats.inserted += persisted.inserted;
    stats.updated += persisted.updated;
    stats.totalWritten += persisted.totalWritten;
    stats.totalFindings = persisted.totalFindings;

    addJob({
      type: 'coverage_boost_progress',
      status: persisted.totalWritten > 0 ? 'success' : 'warning',
      message: `${progress} ${task.competitor} ${task.category} | 入库 ${persisted.totalWritten}（新增${persisted.inserted}/更新${persisted.updated}） | query="${queryShort}"`
    });
  }

  addJob({
    type: 'coverage_boost',
    status: 'success',
    message: `定向覆盖增强完成：写入 ${stats.totalWritten}（新增${stats.inserted}/更新${stats.updated}），保留候选 ${stats.keptCandidates}，总来源命中 ${stats.sourceHits}。`
  });

  return stats;
}

module.exports = {
  runCoverageBoost
};
