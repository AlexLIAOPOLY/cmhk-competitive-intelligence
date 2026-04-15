const { readDb, getMonitoringConfig } = require('./db');

const DAY_MS = 24 * 60 * 60 * 1000;
const WEEK_MS = 7 * DAY_MS;

const METRIC_DEFS = [
  {
    key: 'revenue',
    label: '营业收入',
    type: 'money',
    keywords: ['营业收入', '主营业务收入', '营收', 'revenue', 'sales']
  },
  {
    key: 'ebitda',
    label: 'EBITDA',
    type: 'money',
    keywords: ['ebitda', 'EBITDA']
  },
  {
    key: 'netProfit',
    label: '净利润',
    type: 'money',
    keywords: ['归母净利润', '净利润', 'net profit', 'profit attributable']
  },
  {
    key: 'capex',
    label: '资本开支',
    type: 'money',
    keywords: ['资本开支', 'capex', 'capital expenditure', 'capital spending']
  },
  {
    key: 'mobileUsers',
    label: '移动用户',
    type: 'users',
    keywords: ['移动用户', 'mobile users', 'mobile subscribers', 'subscriber base']
  },
  {
    key: 'fiveGUsers',
    label: '5G用户',
    type: 'users',
    keywords: ['5g用户', '5g users', '5g subscribers', '5g network users']
  },
  {
    key: 'fiveGPenetration',
    label: '5G渗透率',
    type: 'ratio',
    keywords: ['5g渗透率', '5g penetration', 'penetration rate']
  }
];

const TELECOM_KEYWORDS = [
  'telecom', 'telco', 'operator', 'carrier', 'mobile', '5g', '5g-a', '6g',
  'network', 'core network', 'broadband', 'fiber', 'fibre', 'spectrum',
  'roaming', 'data center', 'cloud', 'satellite', 'enterprise connectivity',
  '电信', '运营商', '网络', '宽带', '光纤', '频谱', '漫游', '算力', '云网', '卫星通信'
];

const POLICY_KEYWORDS = [
  'policy', 'regulation', 'regulatory', 'directive', 'consultation', 'compliance',
  'license', 'licence', 'spectrum auction', 'data act', 'ai act',
  '政策', '法规', '监管', '牌照', '条例', '法案', '合规', '审批'
];

const FINANCIAL_KEYWORDS = [
  'earnings', 'results', 'financial', 'revenue', 'ebitda', 'net profit', 'guidance',
  '财报', '业绩', '营收', '净利润', '资本开支', '派息', '指引'
];

const IRRELEVANT_KEYWORDS = [
  'nba', 'nfl', 'mlb', 'soccer', 'football', 'celebrity', 'movie', 'music', 'gaming',
  'lottery', 'fashion', 'retail beauty', 'hospital', 'biotech', 'mining', 'drilling',
  'basketball', 'cricket', '歌手', '娱乐', '电影', '博彩', '矿业', '油田', '医美'
];

const BASE_VALUE_PATTERN = String.raw`(?<value>[+\-−]?\d{1,3}(?:[\d,\.\s]{0,16}\d)?)`;
const BASE_UNIT_PATTERN = String.raw`(?<unit>万亿元|亿港元|亿人民币|亿元人民币|亿元|亿日元|亿欧元|亿戶|亿户|万戶|万户|亿|万|trillion|tn|billion|bn|million|mn|HK\$|US\$|USD|HKD|RMB|CNY|EUR|JPY|港元|美元|人民币|元|戶|户|users?|subscribers?|%)?`;
const BASE_PREFIX_PATTERN = String.raw`(?<prefix>HK\$|US\$|USD|HKD|RMB|CNY|EUR|JPY)?`;

function escapeRegExp(text) {
  return String(text || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function normalizeText(value) {
  return String(value || '').trim();
}

function normalizeWhitespace(value) {
  return normalizeText(value).replace(/\s+/g, ' ');
}

function findingTimestamp(item) {
  const baseline = item?.publishedAt || item?.capturedAt || item?.createdAt;
  const timestamp = Date.parse(String(baseline || ''));
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

function hasAnyKeyword(text, keywords) {
  const haystack = String(text || '').toLowerCase();
  if (!haystack) return false;
  return keywords.some((keyword) => haystack.includes(String(keyword || '').toLowerCase()));
}

function getCompetitorAliases(name) {
  const raw = String(name || '').trim();
  if (!raw) return [];
  const segments = raw
    .split(/[()\/|]/g)
    .map((item) => item.trim())
    .filter(Boolean);
  const aliases = new Set([raw, ...segments]);
  for (const segment of segments) {
    const words = segment.split(/\s+/).map((item) => item.trim()).filter((item) => item.length >= 3);
    for (const word of words) aliases.add(word);
  }
  return Array.from(aliases).filter((item) => item.length >= 3);
}

function containsAlias(text, alias) {
  const haystack = String(text || '').toLowerCase();
  const needle = String(alias || '').toLowerCase();
  if (!haystack || !needle) return false;

  if (/^[a-z0-9 .+-]+$/i.test(needle)) {
    const pattern = new RegExp(`\\b${escapeRegExp(needle)}\\b`, 'i');
    return pattern.test(haystack);
  }

  return haystack.includes(needle);
}

function isInstitutionCompetitor(name) {
  const text = String(name || '').toLowerCase();
  return /commission|ofca|itu|oecd|policy|regulator/.test(text);
}

function isFindingRelevantForBoard(item, competitorName) {
  const aliases = getCompetitorAliases(competitorName);
  if (!aliases.length) return false;

  const title = String(item?.title || '');
  const url = String(item?.sourceUrl || '');
  const summary = String(item?.summary || '');
  const significance = String(item?.significance || '');
  const snippet = String(item?.rawSnippet || '');
  const titleUrl = `${title} ${url}`;
  const fullText = `${title} ${summary} ${significance} ${snippet} ${url}`;

  const mention = aliases.some((alias) => containsAlias(titleUrl, alias));
  if (!mention) return false;

  if (hasAnyKeyword(fullText, IRRELEVANT_KEYWORDS)) {
    return false;
  }

  const telecomSignal = hasAnyKeyword(fullText, TELECOM_KEYWORDS);
  const policySignal = hasAnyKeyword(fullText, POLICY_KEYWORDS);
  const financialSignal = hasAnyKeyword(fullText, FINANCIAL_KEYWORDS);
  const categoryName = String(item?.category || '');

  if (isInstitutionCompetitor(competitorName)) {
    return telecomSignal || policySignal || categoryName === '政策法规' || categoryName === '宏观数据';
  }

  if (telecomSignal) return true;
  if (categoryName === '财报' && financialSignal) return true;
  return false;
}

function sanitizeNumberText(raw) {
  return String(raw || '')
    .replace(/[，,\s]/g, '')
    .replace(/−/g, '-')
    .replace(/[^\d.+-]/g, '');
}

function parseNumber(raw) {
  const cleaned = sanitizeNumberText(raw);
  if (!cleaned || !/^[+\-]?\d+(?:\.\d+)?$/.test(cleaned)) {
    return null;
  }
  const value = Number(cleaned);
  if (!Number.isFinite(value)) return null;
  return value;
}

function isLikelyYear(value) {
  return Number.isInteger(value) && value >= 1900 && value <= 2100;
}

function normalizeUnit(unit, metricType) {
  const raw = normalizeText(unit);
  if (!raw) return '';

  const lower = raw.toLowerCase();
  if (metricType === 'ratio') return '%';

  if (lower === 'users' || lower === 'user' || lower === 'subscriber' || lower === 'subscribers') {
    return '户';
  }
  if (lower === 'bn' || lower === 'billion') return 'bn';
  if (lower === 'mn' || lower === 'million') return 'mn';
  if (lower === 'tn' || lower === 'trillion') return 'tn';
  if (raw === '億戶' || raw === '亿戶') return '亿户';
  if (raw === '萬戶' || raw === '万戶') return '万户';
  if (raw === '戶') return '户';
  return raw;
}

function formatDisplayNumber(value) {
  if (!Number.isFinite(value)) return '';
  if (Number.isInteger(value)) {
    return value.toLocaleString('en-US');
  }
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2
  });
}

function normalizePercentText(rawValue) {
  const value = parseNumber(rawValue);
  if (!Number.isFinite(value)) return null;
  const sign = value > 0 ? '+' : '';
  const text = `${sign}${formatDisplayNumber(value)}%`;
  return {
    value,
    text
  };
}

function extractYoyAround(text, start, length) {
  const content = String(text || '');
  const left = Math.max(0, Number(start || 0) - 56);
  const right = Math.min(content.length, Number(start || 0) + Number(length || 0) + 64);
  const snippet = content.slice(left, right);

  const direct = snippet.match(/([+\-−]?\d+(?:\.\d+)?)\s*%\s*(?:yoy|YoY|同比|按年|year[-\s]?on[-\s]?year)?/);
  if (direct) {
    return normalizePercentText(direct[1]);
  }

  const prefixed = snippet.match(/(?:同比|按年|year[-\s]?on[-\s]?year|yoy)[^\d+\-−]{0,10}([+\-−]?\d+(?:\.\d+)?)\s*%/i);
  if (prefixed) {
    return normalizePercentText(prefixed[1]);
  }

  return null;
}

function normalizeBaseValue(value, unit) {
  if (!Number.isFinite(value)) return null;
  const normalizedUnit = String(unit || '').toLowerCase();

  if (!normalizedUnit) return value;
  if (normalizedUnit.includes('%')) return value;
  if (normalizedUnit.includes('万亿元') || normalizedUnit === 'tn') return value * 1e12;
  if (normalizedUnit.includes('亿元') || normalizedUnit === '亿' || normalizedUnit.includes('亿港元') || normalizedUnit.includes('亿人民币') || normalizedUnit.includes('亿日元') || normalizedUnit.includes('亿欧元')) {
    return value * 1e8;
  }
  if (normalizedUnit.includes('万户') || normalizedUnit === '万') return value * 1e4;
  if (normalizedUnit.includes('亿户')) return value * 1e8;
  if (normalizedUnit === 'bn') return value * 1e9;
  if (normalizedUnit === 'mn') return value * 1e6;
  return value;
}

function isPlausibleValue(metric, value, unit) {
  if (!Number.isFinite(value)) return false;
  if (Math.abs(value) > 1e16) return false;
  const normalizedUnit = String(unit || '').toLowerCase();

  if (metric.type === 'ratio') {
    return Math.abs(value) <= 1000 && normalizedUnit === '%';
  }

  if (metric.type === 'money') {
    if (unit === '%') return false;
    if (!unit) return false;
    if (normalizedUnit.includes('户') || normalizedUnit.includes('user') || normalizedUnit.includes('subscriber')) return false;
    if (value <= 0) return false;
    return Math.abs(value) >= 0.01;
  }

  if (metric.type === 'users') {
    if (unit === '%') return false;
    if (!unit && isLikelyYear(value)) return false;
    return Math.abs(value) >= 0.01;
  }

  return true;
}

function buildMetricPatterns(metric) {
  const keywordPattern = metric.keywords.map((word) => escapeRegExp(word)).join('|');
  const primary = new RegExp(`(?:${keywordPattern})[^\\n\\d%]{0,15}${BASE_PREFIX_PATTERN}\\s*${BASE_VALUE_PATTERN}\\s*${BASE_UNIT_PATTERN}`, 'ig');
  const secondary = new RegExp(`${BASE_PREFIX_PATTERN}\\s*${BASE_VALUE_PATTERN}\\s*${BASE_UNIT_PATTERN}[^\\n]{0,10}(?:${keywordPattern})`, 'ig');

  if (metric.type === 'money') {
    return [primary];
  }

  if (metric.type === 'ratio') {
    return [new RegExp(`(?:${keywordPattern})[^\\n\\d]{0,20}${BASE_VALUE_PATTERN}\\s*%`, 'ig')];
  }

  if (metric.type === 'users') {
    const usersSecondary = new RegExp(`${BASE_PREFIX_PATTERN}\\s*${BASE_VALUE_PATTERN}\\s*${BASE_UNIT_PATTERN}[^\\n]{0,8}(?:${keywordPattern})`, 'ig');
    return [primary, usersSecondary];
  }

  return [primary, secondary];
}

function buildMetricCandidates(metric, finding, text) {
  if (!hasAnyKeyword(text, metric.keywords)) return [];

  const patterns = buildMetricPatterns(metric);
  const candidates = [];
  const seen = new Set();
  const timestamp = findingTimestamp(finding);

  for (const pattern of patterns) {
    let match = pattern.exec(text);
    while (match) {
      const value = parseNumber(match.groups?.value);
      const unit = normalizeUnit(match.groups?.unit, metric.type);
      const prefix = normalizeText(match.groups?.prefix).toUpperCase();

      if (isPlausibleValue(metric, value, unit)) {
        const key = [
          metric.key,
          String(value),
          unit,
          prefix,
          Math.floor(Number(match.index || 0) / 20)
        ].join('|');

        if (!seen.has(key)) {
          const snippetStart = Math.max(0, Number(match.index || 0) - 36);
          const snippetEnd = Math.min(text.length, Number(match.index || 0) + String(match[0] || '').length + 36);
          const snippet = normalizeWhitespace(text.slice(snippetStart, snippetEnd));
          const snippetLower = snippet.toLowerCase();
          const categoryName = normalizeText(finding.category);
          const unitLower = String(unit || '').toLowerCase();
          const metricSignalMap = {
            revenue: /(revenue|sales|营业收入|营收|主营业务收入|收入)/i,
            ebitda: /\bebitda\b/i,
            netProfit: /(net profit|profit attributable|归母净利润|净利润|归属于母公司股东利润)/i,
            capex: /(capex|capital expenditure|capital spending|资本开支|资本性支出|投资开支)/i,
            mobileUsers: /(mobile users?|mobile subscribers?|移动用户|移动电话用户|用户数)/i,
            fiveGUsers: /(5g users?|5g subscribers?|5g用户|5g网络用户)/i,
            fiveGPenetration: /(5g penetration|5g渗透率|penetration rate)/i
          };
          const minBaseByMetric = {
            revenue: 1e8,
            ebitda: 1e7,
            netProfit: 1e7,
            capex: 1e7
          };
          const baseValue = normalizeBaseValue(value, unit);

          if (metricSignalMap[metric.key] && !metricSignalMap[metric.key].test(snippet)) {
            seen.add(key);
            match = pattern.exec(text);
            continue;
          }

          if (metric.type === 'money') {
            const hasMoneySignal = /(revenue|sales|profit|ebitda|capex|income|营收|营业收入|收入|利润|净利润|资本开支|投资)/i.test(snippet);
            const hasUserConflict = /(user|users|subscriber|subscribers|用户|客户|户数|用户数)/i.test(snippet);
            const hasScaleSignal = Boolean(prefix) || /(usd|hkd|rmb|cny|eur|jpy|港元|美元|人民币|元|亿|bn|mn|tn)/i.test(unitLower);
            const hasFinancialContext = categoryName === '财报'
              || /(earnings|annual results|interim results|quarterly|financial|财报|业绩|年度报告|中期业绩|业绩公告)/i.test(`${finding.title || ''} ${snippet}`);
            const containsPercent = /%/.test(String(match[0] || ''));

            if (!hasMoneySignal) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            if (!hasFinancialContext || !hasScaleSignal || containsPercent) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            if (hasUserConflict) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            if (metric.key === 'revenue' && unitLower === 'mn' && !prefix) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            if (value <= 0 || !Number.isFinite(baseValue)) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            const minBase = minBaseByMetric[metric.key] || 0;
            if (minBase > 0 && baseValue < minBase) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
          }

          if (metric.type === 'users' && !/(user|users|subscriber|subscribers|用户|客户|户)/i.test(`${unit} ${snippetLower}`)) {
            seen.add(key);
            match = pattern.exec(text);
            continue;
          }

          if (metric.type === 'users') {
            const hasCurrencyUnit = /(usd|hkd|rmb|cny|eur|jpy|港元|美元|人民币|欧元|元)/i.test(`${prefix} ${unit}`);
            if (hasCurrencyUnit) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
            if (!unit && value < 10000) {
              seen.add(key);
              match = pattern.exec(text);
              continue;
            }
          }

          const yoy = extractYoyAround(text, match.index || 0, String(match[0] || '').length);
          const score = [
            unit ? 2 : 0,
            prefix ? 1 : 0,
            yoy ? 1 : 0,
            Number(match.index || 0) <= 200 ? 1 : 0,
            categoryName === '财报' ? 2 : 0
          ].reduce((sum, part) => sum + part, 0);

          const valueText = `${prefix ? `${prefix} ` : ''}${formatDisplayNumber(value)}${unit}`;

          candidates.push({
            metricKey: metric.key,
            metricLabel: metric.label,
            value,
            unit,
            prefix,
            valueText,
            valueBase: baseValue,
            yoyValue: yoy?.value ?? null,
            yoyText: yoy?.text || '',
            score,
            timestamp,
            source: {
              findingId: finding.id,
              title: finding.title || '',
              competitor: finding.competitor || '',
              category: finding.category || '',
              sourceUrl: finding.sourceUrl || '',
              publishedAt: finding.publishedAt || finding.capturedAt || finding.createdAt || null
            },
            snippet
          });
          seen.add(key);
        }
      }

      if (candidates.length >= 8) break;
      match = pattern.exec(text);
    }
  }

  return candidates;
}

function collectFindingMetricCandidates(finding) {
  const text = normalizeWhitespace([
    finding?.title,
    finding?.summary,
    finding?.significance,
    finding?.rawSnippet
  ].filter(Boolean).join('\n'));

  if (!text) return [];
  return METRIC_DEFS.flatMap((metric) => buildMetricCandidates(metric, finding, text));
}

function pickBestCandidate(candidates) {
  if (!Array.isArray(candidates) || !candidates.length) return null;
  const sorted = [...candidates].sort((a, b) => {
    if ((b.timestamp || 0) !== (a.timestamp || 0)) {
      return (b.timestamp || 0) - (a.timestamp || 0);
    }
    if ((b.score || 0) !== (a.score || 0)) {
      return (b.score || 0) - (a.score || 0);
    }
    return Math.abs(b.valueBase || 0) - Math.abs(a.valueBase || 0);
  });
  return sorted[0] || null;
}

function buildMomentum(recentCount, previousCount) {
  const current = Number(recentCount || 0);
  const previous = Number(previousCount || 0);
  const delta = current - previous;
  const denominator = previous > 0 ? previous : 1;
  const pct = previous > 0 ? (delta / denominator) * 100 : (current > 0 ? 100 : 0);
  const pctText = `${delta >= 0 ? '+' : ''}${pct.toFixed(1)}%`;

  return {
    recentCount: current,
    previousCount: previous,
    delta,
    deltaPct: Number(pct.toFixed(1)),
    deltaPctText: pctText,
    tone: delta > 0 ? 'up' : (delta < 0 ? 'down' : 'flat')
  };
}

function buildWeekBuckets(weeks = 12) {
  const safeWeeks = Math.max(6, Math.min(26, Number(weeks) || 12));
  const end = Date.now();
  const start = end - safeWeeks * WEEK_MS;
  const buckets = [];

  for (let i = 0; i < safeWeeks; i += 1) {
    const bucketStart = start + i * WEEK_MS;
    const bucketEnd = bucketStart + WEEK_MS;
    const label = new Date(bucketStart).toISOString().slice(5, 10);
    buckets.push({
      start: bucketStart,
      end: bucketEnd,
      label
    });
  }

  return buckets;
}

function getBucketIndex(timestamp, buckets) {
  for (let i = 0; i < buckets.length; i += 1) {
    if (timestamp >= buckets[i].start && timestamp < buckets[i].end) {
      return i;
    }
  }
  return -1;
}

function buildCompetitorRows(windowFindings, monitoringCompetitors, buckets) {
  const rowMap = new Map();
  for (const competitor of monitoringCompetitors || []) {
    rowMap.set(competitor.name, {
      name: competitor.name,
      region: competitor.region || 'Unknown',
      findingCount: 0,
      lastFindingAt: null,
      lastFindingTs: 0,
      categoryMap: new Map(),
      trendCounts: new Array(buckets.length).fill(0),
      recentSignals: [],
      recentCount: 0,
      previousCount: 0,
      metricCandidates: Object.fromEntries(METRIC_DEFS.map((item) => [item.key, []]))
    });
  }

  const now = Date.now();
  const recentStart = now - 28 * DAY_MS;
  const previousStart = now - 56 * DAY_MS;

  for (const item of windowFindings) {
    const competitorName = normalizeText(item.competitor);
    if (!competitorName) continue;

    if (!rowMap.has(competitorName)) {
      rowMap.set(competitorName, {
        name: competitorName,
        region: normalizeText(item.region) || 'Unknown',
        findingCount: 0,
        lastFindingAt: null,
        lastFindingTs: 0,
        categoryMap: new Map(),
        trendCounts: new Array(buckets.length).fill(0),
        recentSignals: [],
        recentCount: 0,
        previousCount: 0,
        metricCandidates: Object.fromEntries(METRIC_DEFS.map((metric) => [metric.key, []]))
      });
    }

    const row = rowMap.get(competitorName);
    if (!row) continue;
    if (!isFindingRelevantForBoard(item, row.name)) continue;

    const timestamp = findingTimestamp(item);
    row.findingCount += 1;

    if (timestamp > row.lastFindingTs) {
      row.lastFindingTs = timestamp;
      row.lastFindingAt = timestamp ? new Date(timestamp).toISOString() : null;
    }

    const category = normalizeText(item.category) || '未分类';
    row.categoryMap.set(category, (row.categoryMap.get(category) || 0) + 1);

    if (timestamp >= recentStart) {
      row.recentCount += 1;
    } else if (timestamp >= previousStart) {
      row.previousCount += 1;
    }

    const bucketIndex = getBucketIndex(timestamp, buckets);
    if (bucketIndex >= 0) {
      row.trendCounts[bucketIndex] += 1;
    }

    row.recentSignals.push({
      timestamp,
      competitor: row.name,
      category,
      title: normalizeText(item.title),
      summary: normalizeText(item.summary || item.significance),
      publishedAt: item.publishedAt || item.capturedAt || item.createdAt || null,
      sourceUrl: item.sourceUrl || ''
    });

    const candidates = collectFindingMetricCandidates(item);
    for (const candidate of candidates) {
      if (row.metricCandidates[candidate.metricKey]) {
        row.metricCandidates[candidate.metricKey].push(candidate);
      }
    }
  }

  const finalizedRows = Array.from(rowMap.values()).map((row) => {
    const kpis = {};
    let kpiCoverage = 0;

    for (const metric of METRIC_DEFS) {
      const best = pickBestCandidate(row.metricCandidates[metric.key]);
      if (best) {
        kpis[metric.key] = {
          label: metric.label,
          valueText: best.valueText,
          value: best.value,
          valueBase: best.valueBase,
          unit: best.unit,
          yoyText: best.yoyText,
          yoyValue: best.yoyValue,
          source: best.source,
          snippet: best.snippet
        };
        kpiCoverage += 1;
      } else {
        kpis[metric.key] = null;
      }
    }

    const categoryMix = Array.from(row.categoryMap.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    const trend = row.trendCounts.map((count, index) => ({
      label: buckets[index]?.label || '',
      count
    }));

    const recentSignals = row.recentSignals
      .sort((a, b) => b.timestamp - a.timestamp)
      .slice(0, 6);

    return {
      name: row.name,
      region: row.region,
      findingCount: row.findingCount,
      lastFindingAt: row.lastFindingAt,
      categoryMix,
      momentum: buildMomentum(row.recentCount, row.previousCount),
      kpis,
      kpiCoverage,
      trend,
      recentSignals
    };
  });

  return finalizedRows.sort((a, b) => {
    if (b.findingCount !== a.findingCount) return b.findingCount - a.findingCount;
    return Date.parse(b.lastFindingAt || '') - Date.parse(a.lastFindingAt || '');
  });
}

function buildChartRows(rows) {
  const activity = rows
    .map((row) => ({ name: row.name, count: row.findingCount }))
    .filter((item) => item.count > 0)
    .slice(0, 10);

  const coverage = [...rows]
    .sort((a, b) => b.kpiCoverage - a.kpiCoverage)
    .map((row) => ({ name: row.name, count: row.kpiCoverage }))
    .slice(0, 10);

  const revenueYoy = rows
    .map((row) => ({
      name: row.name,
      value: row.kpis.revenue?.yoyValue
    }))
    .filter((row) => Number.isFinite(row.value))
    .sort((a, b) => b.value - a.value)
    .slice(0, 10);

  return {
    activity,
    coverage,
    revenueYoy
  };
}

function buildSourceHighlights(rows) {
  const merged = [];

  for (const row of rows) {
    for (const signal of row.recentSignals || []) {
      merged.push({
        competitor: row.name,
        category: signal.category || '',
        title: signal.title || '',
        summary: signal.summary || '',
        sourceUrl: signal.sourceUrl || '',
        publishedAt: signal.publishedAt || null,
        tag: '情报'
      });
    }

    for (const metric of METRIC_DEFS) {
      const cell = row.kpis[metric.key];
      if (!cell?.source) continue;
      merged.push({
        competitor: row.name,
        category: cell.source.category || '',
        title: `${metric.label}：${cell.valueText}${cell.yoyText ? `（同比 ${cell.yoyText}）` : ''}`,
        summary: cell.snippet || '',
        sourceUrl: cell.source.sourceUrl || '',
        publishedAt: cell.source.publishedAt || null,
        tag: '指标'
      });
    }
  }

  const dedup = new Map();
  for (const item of merged) {
    const key = `${item.title}|${item.sourceUrl}|${item.competitor}|${item.tag}`;
    if (!dedup.has(key)) {
      dedup.set(key, item);
    }
  }

  return Array.from(dedup.values())
    .sort((a, b) => Date.parse(b.publishedAt || '') - Date.parse(a.publishedAt || ''))
    .slice(0, 18);
}

function buildCompetitorDashboard(options = {}) {
  const days = Math.max(30, Math.min(730, Number(options.days || 180)));
  const sinceMs = Date.now() - days * DAY_MS;

  const db = readDb();
  const config = getMonitoringConfig();
  const monitoringCompetitors = Array.isArray(config.competitors) ? config.competitors : [];

  const windowFindings = (db.findings || []).filter((item) => {
    const timestamp = findingTimestamp(item);
    if (!timestamp || timestamp < sinceMs) return false;
    return Boolean(item.competitor);
  });

  const buckets = buildWeekBuckets(12);
  const rows = buildCompetitorRows(windowFindings, monitoringCompetitors, buckets);
  const charts = buildChartRows(rows);
  const sources = buildSourceHighlights(rows);

  const totalFindings = rows.reduce((sum, row) => sum + row.findingCount, 0);
  const activeCompetitors = rows.filter((row) => row.findingCount > 0).length;
  const financialCoverage = rows.filter((row) => (
    row.kpis.revenue || row.kpis.ebitda || row.kpis.netProfit || row.kpis.capex
  )).length;
  const avgKpiCoverage = rows.length
    ? Number((rows.reduce((sum, row) => sum + row.kpiCoverage, 0) / rows.length).toFixed(2))
    : 0;

  return {
    asOf: new Date().toISOString(),
    windowDays: days,
    summary: {
      competitorCount: rows.length,
      activeCompetitors,
      totalFindings,
      financialCoverage,
      avgKpiCoverage
    },
    charts,
    competitors: rows,
    sources
  };
}

module.exports = {
  buildCompetitorDashboard
};
