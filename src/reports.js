const { deepseekChat, deepseekChatStream } = require('./deepseek');
const { addReport, addJob, readDb, writeDb, getReportById, appendReportQa } = require('./db');

const REPORT_TIMEOUT_MS = Number(process.env.DS_REPORT_TIMEOUT_MS || 420000);
const REPORT_QA_TIMEOUT_MS = Number(process.env.DS_REPORT_QA_TIMEOUT_MS || 180000);

const TRUSTED_REPORT_DOMAINS = [
  'vodafone.com',
  'orange.com',
  'pccw.com',
  'smartone.com',
  'cmhk.com.hk',
  'lightreading.com',
  'telecoms.com',
  'developingtelecoms.com',
  'totaltele.com',
  'mobileworldlive.com',
  'reuters.com',
  'ft.com',
  'wsj.com',
  'bloomberg.com',
  'sec.gov',
  'fcc.gov',
  'ofcom.org.uk',
  'ec.europa.eu',
  'europa.eu',
  'ofca.gov.hk',
  'gov.hk',
  'news.gov.hk',
  'info.gov.hk',
  'legco.gov.hk',
  'censtatd.gov.hk',
  'data.gov.hk',
  'hkma.gov.hk',
  'gsma.com',
  'gsmaintelligence.com',
  'gsa.com',
  'itu.int',
  'oecd.org',
  'imf.org',
  'worldbank.org',
  'miit.gov.cn',
  'cac.gov.cn',
  'stats.gov.cn',
  'gov.cn'
];

const TELECOM_KEYWORDS = [
  'telecom', 'telco', 'operator', 'carrier', 'mobile', '5g', '5g-a', '6g',
  'network', 'core network', 'broadband', 'fiber', 'fibre', 'spectrum',
  'roaming', 'data center', 'cloud', 'satellite', 'enterprise connectivity',
  '电信', '电讯', '通信业', '运营商', '5g', '网络', '宽带', '光纤', '频谱', '漫游', '算力', '数据中心', '云网', '卫星通信'
];

const CATEGORY_KEYWORDS = {
  财报: ['earnings', 'results', 'revenue', 'ebitda', 'net profit', 'dividend', 'guidance', 'annual report', 'quarterly', 'investor', '财报', '业绩', '营收', '净利润', '资本开支', '派息'],
  产品发布会: ['launch', 'product', 'release', 'solution', 'platform', 'service', '发布', '推出', '升级', '方案', '平台'],
  中标公示: ['tender', 'bid', 'contract', 'award', 'procurement', 'framework', '中标', '招标', '采购', '合同', '框架协议'],
  高管言论: ['ceo', 'chairman', 'executive', 'interview', 'comment', 'statement', '董事长', '总裁', '高管', '采访', '表示', '发言'],
  政策法规: ['policy', 'regulation', 'law', 'act', 'compliance', 'license', 'consultation', 'directive', '法案', '政策', '法规', '监管', '合规', '牌照', '条例', '咨询'],
  宏观数据: ['gdp', 'cpi', 'inflation', 'unemployment', 'market data', 'indicator', 'statistics', 'forecast', '宏观', '统计', '指标', '通胀', '失业', '增速', '经济运行']
};

const IRRELEVANT_KEYWORDS = [
  'nba', 'nfl', 'mlb', 'football', 'soccer', 'yahoo sports', 'guess what',
  'celebrity', 'movie', 'music', 'gaming', 'lottery', 'horoscope',
  'mining', 'drilling', 'biotech', 'pharma', 'hospital', 'aesthetics',
  'energy security', 'oil tanker', 'fashion', 'retail beauty',
  '篮球', '足球', '娱乐', '明星', '电影', '博彩', '医美', '矿业', '石油'
];

const WEEKLY_SECTION_ORDER = ['政治资讯', '行业资讯', '社会资讯', '国际资讯'];
const WEEKLY_MAX_ITEMS = 10;
const WEEKLY_RANGE_TOLERANCE_MS = 0;
const WEEKLY_SECTION_CAPS = {
  政治资讯: 2,
  行业资讯: 4,
  社会资讯: 2,
  国际资讯: 2
};

const WEEKLY_TAG_RULES = [
  { tag: '香港施政治理', keywords: ['李家超', '施政', '特区政府', '立法会', '香港五年规划', '北部都会区', '施政治理'] },
  { tag: '低空经济', keywords: ['低空', '无人机', '飞行器', '空域'] },
  { tag: '人工智能', keywords: ['人工智能', 'ai', '大模型', '具身智能', '算力', 'token'] },
  { tag: 'Web3.0', keywords: ['web3', '稳定币', '数字资产', '虚拟资产'] },
  { tag: '八大中心', keywords: ['国际金融中心', '港交所', '基金', '家族办公室', '人民币业务'] },
  { tag: '漫游市场需求', keywords: ['漫游', '旅游消费', '跨境便利', '访港客'] },
  { tag: '本地生活', keywords: ['公屋', '轮候', '房屋局', '民生', '本地生活'] },
  { tag: '社会民生', keywords: ['就业', '失业', '工资', '收入', '消费', '零售', '医疗', '教育', '交通', '公共服务'] },
  { tag: '地缘政治与经济', keywords: ['地缘', '投资承诺', '新加坡', '宏观', '经济'] },
  { tag: '行业相关监管', keywords: ['监管', '法案', '条例', '批准', '反垄断', 'compliance'] },
  { tag: '跨境贸易', keywords: ['跨境', '物流网络', '同日达', '次日达', '贸易'] },
  { tag: '友商动态', keywords: ['kddi', 'at&t', 'aws', 'orange', 'vodafone', 'pccw', 'smartone', '中国移动', '中国电信', '中国联通', '中国铁塔'] }
];

const WEEKLY_SOCIAL_KEYWORDS = [
  '公屋', '房屋', '轮候', '简约公屋', '基层', '民生', '本地生活', '社区',
  '旅游', '访港', '旅客', '酒店入住', '消费', '零售', '餐饮', '就业', '失业',
  '工资', '薪酬', '家庭收入', '居民收入', '可支配收入', '医疗', '教育', '交通', '公共服务', '福利', '养老',
  '住房', '居住', '生活成本', 'cpi', '通胀',
  'public housing', 'housing', 'livelihood', 'local life', 'tourism', 'visitor arrivals',
  'hotel occupancy', 'consumption', 'retail sales', 'employment', 'unemployment',
  'wage', 'household income', 'median income', 'healthcare', 'education', 'transport', 'public service', 'social welfare'
];

const WEEKLY_SOCIAL_INSTITUTIONS = [
  'housing bureau', 'housing authority', 'census and statistics department',
  'hong kong tourism board', 'labour and welfare bureau', 'transport department',
  'medical', 'education bureau', '社会', '民生', '房屋局', '房屋署', '香港政府统计处',
  '旅游发展局', '劳工及福利局', '运输署', '卫生', '教育局'
];

const WEEKLY_SOCIAL_SOURCE_COMPETITORS = [
  'hong kong sar government',
  'census and statistics department (hong kong)',
  'hong kong social and livelihood statistics',
  'ofca (hong kong)'
];

const WEEKLY_TELECOM_OPERATOR_HINTS = [
  'vodafone',
  'orange',
  'pccw',
  'smartone',
  'kddi',
  'at&t',
  'china mobile',
  'china telecom',
  'china unicom',
  'china tower',
  '中国移动',
  '中国电信',
  '中国联通',
  '中国铁塔',
  '沃达丰',
  '法国电信',
  '电讯盈科',
  '数码通'
];

const WEEKLY_ENTITY_ALIAS_CN = [
  ['vodafone', '沃达丰'],
  ['orange', '法国电信'],
  ['pccw', '电讯盈科'],
  ['smartone', '数码通'],
  ['ofca (hong kong)', '香港通讯事务管理局'],
  ['ofca', '香港通讯事务管理局'],
  ['hong kong sar government', '香港特别行政区政府'],
  ['ofcom (uk telecom regulator)', '英国通信管理局'],
  ['ofcom', '英国通信管理局'],
  ['fcc (us communications regulator)', '美国联邦通信委员会'],
  ['fcc', '美国联邦通信委员会'],
  ['miit / cac (mainland china policy)', '中国工信部与网信办政策渠道'],
  ['miit', '中国工业和信息化部'],
  ['cac', '中国国家互联网信息办公室'],
  ['world bank / imf digital economy', '世界银行与国际货币基金组织数字经济渠道'],
  ['world bank', '世界银行'],
  ['imf', '国际货币基金组织'],
  ['census and statistics department (hong kong)', '香港政府统计处'],
  ['gsma intelligence', '全球移动通信系统协会研究部门'],
  ['gsma', '全球移动通信系统协会'],
  ['european commission (digital policy)', '欧盟委员会数字政策部门'],
  ['european commission', '欧盟委员会'],
  ['itu / oecd telecom indicators', '国际电联与经合组织电信指标'],
  ['itu', '国际电信联盟'],
  ['oecd', '经济合作与发展组织'],
  ['at&t', '美国电话电报公司'],
  ['aws', '亚马逊云科技'],
  ['kddi', '日本第二电电'],
  ['google', '谷歌'],
  ['china mobile', '中国移动'],
  ['china telecom', '中国电信'],
  ['china unicom', '中国联通'],
  ['china tower', '中国铁塔']
];

const WEEKLY_FACT_SIGNAL_REGEX = /(发布|公布|宣布|披露|通报|签署|完成|启动|上线|成立|获批|批准|通过|收购|合作|融资|投资|派息|分红|下调|上调|增长|下降|达到|提交|实施|召开|举行|财报|业绩|法案|政策|条例|计划)/;
const WEEKLY_SUBJECTIVE_REGEX = /(趋势|态势|前景|潜力|动向|有助于|驱动|反映|体现|意味着|揭示|推断|推测|建议|应当|应尽快|宜|需持续|可作为)/;
const WEEKLY_INTERPRETIVE_REGEX = /(旨在|反映|体现|意味着|揭示|趋势|动向|潜力|机会|挑战|前景|有助于|推动|驱动|战略|路径|生态|议程|可作为|用于分析|参考框架|说明其目的)/;
const WEEKLY_METRIC_UNIT_REGEX = /(亿元|亿港元|亿美元|万元|港元|美元|欧元|人民币|元|亿户|万户|人次|万人次|%|个百分点|倍|项|条|家|座|个|笔|Gbps|Mbps|Kbps)/i;
const WEEKLY_METRIC_CUE_REGEX = /(同比|环比|增长|下降|提升|下滑|减少|增加|达到|为|至|约|超|超过|不少于|高于|低于|营收|收入|净利润|利润|资本开支|派息|用户|覆盖|渗透率|中标金额|融资金额|订单金额|市值|估值)/;
const FORMAL_META_PREFIX_REGEX = /(?:文件标题为|标题为|输入内容为|文章(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|该文章(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|该文(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|本文(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|文中(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|报道(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|该报道(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|报告(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|该报告(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|该文件(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|原文(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明)|这表明|这意味着|可见|显示了)/;
const FORMAL_NOISE_REGEX = /(文章讨论|文章分析|文中指出|文件标题为|输入内容为|参考框架|用于分析|可能|或许|推测)/;
const FORMAL_SECTION_HINTS = [
  { regex: /(executive summary|investment highlights|key highlights|overview)/i, title: '一、执行摘要与核心结论' },
  { regex: /(financial|earnings|results|revenue|ebitda|profit|capex)/i, title: '二、关键经营数据与财务对比' },
  { regex: /(competitor|operator|peer|telecom|market|trend|industry)/i, title: '三、行业与竞对动态' },
  { regex: /(policy|regulation|law|macro|government)/i, title: '四、政策与宏观影响' },
  { regex: /(risk|uncertainty|warning)/i, title: '五、风险提示' },
  { regex: /(action|recommendation|strategy)/i, title: '六、行动建议' }
];
const FORMAL_EN_CN_REPLACEMENTS = [
  [/\bexecutive summary\b/gi, '执行摘要'],
  [/\binvestment highlights?\b/gi, '核心要点'],
  [/\bkey highlights?\b/gi, '关键要点'],
  [/\bpolicy measures?\b/gi, '政策措施'],
  [/\bpolicy\b/gi, '政策'],
  [/\brisk alerts?\b/gi, '风险提示'],
  [/\brisk warnings?\b/gi, '风险提示'],
  [/\brisk\b/gi, '风险'],
  [/\btrend\b/gi, '趋势'],
  [/\bcompetitor\b/gi, '竞对'],
  [/\boperator\b/gi, '运营商'],
  [/\brevenue\b/gi, '营收'],
  [/\bnet profit\b/gi, '净利润'],
  [/\bebitda\b/gi, '息税折旧摊销前利润'],
  [/\bcapex\b/gi, '资本开支'],
  [/\bguidance\b/gi, '业绩指引'],
  [/\bmarket reaction\b/gi, '市场反应'],
  [/\bsource link\b/gi, '来源链接'],
  [/\bupdate\b/gi, '更新'],
  [/\bAI\b/g, '人工智能'],
  [/\bcloud\b/gi, '云'],
  [/\bsatellite\b/gi, '卫星'],
  [/\bbroadband\b/gi, '宽带'],
  [/\bmobile network\b/gi, '移动网络'],
  [/\bUSD\b/g, '美元'],
  [/\bHKD\b/g, '港元'],
  [/\bCNY\b/g, '人民币'],
  [/\bRMB\b/g, '人民币'],
  [/\bEUR\b/g, '欧元'],
  [/\bYoY\b/gi, '同比'],
  [/\bQoQ\b/gi, '环比'],
  [/\bFY\b/gi, '财年']
];

function toIsoDate(dateValue) {
  return new Date(dateValue).toISOString();
}

function formatShortDate(iso) {
  const timestamp = Date.parse(iso);
  if (Number.isNaN(timestamp)) return '-';
  return new Date(timestamp).toISOString().slice(0, 10);
}

function formatDateTime(iso) {
  const timestamp = Date.parse(String(iso || ''));
  if (Number.isNaN(timestamp)) return '-';
  return new Date(timestamp).toLocaleString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Hong_Kong'
  });
}

function getWindowRange(days) {
  const end = new Date();
  const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000);
  return {
    start: toIsoDate(start),
    end: toIsoDate(end)
  };
}

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

function normalizeText(value, max = 300) {
  const text = typeof value === 'string' ? value.trim() : '';
  if (!text) return '';
  if (text.length <= max) return text;
  return `${text.slice(0, max)}...`;
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function containsChinese(value) {
  return /[\u4e00-\u9fff]/.test(String(value || ''));
}

function replaceWeeklyEntityAlias(text) {
  let next = String(text || '');
  for (const [rawAlias, chineseName] of WEEKLY_ENTITY_ALIAS_CN) {
    const alias = String(rawAlias || '').trim();
    if (!alias) continue;
    next = next.replace(new RegExp(escapeRegExp(alias), 'gi'), chineseName);
  }
  return next;
}

function stripAsciiWords(text) {
  return String(text || '')
    .replace(/\b[0-9]*[A-Za-z][A-Za-z0-9&.'’\-]*\b/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。；：！？])/g, '$1')
    .trim();
}

function replaceFormalReportTerms(text) {
  let next = String(text || '');
  for (const [pattern, replacement] of FORMAL_EN_CN_REPLACEMENTS) {
    next = next.replace(pattern, replacement);
  }
  return next;
}

function splitFormalSentences(text) {
  return String(text || '')
    .replace(/\r?\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[。！？!?；;])\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function sanitizeFormalPlainText(text) {
  if (!text) return '';

  let next = String(text || '')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .replace(/^\s*(?:[-*•]|\d+[.)、])\s*/g, '')
    .replace(/^文件标题为[“"']([^”"']+)[”"']\s*[，,:：]?\s*/i, '')
    .replace(/^标题为[“"']([^”"']+)[”"']\s*[，,:：]?\s*/i, '')
    .replace(/^输入内容为\s*/i, '')
    .replace(/^(?:根据|结合|依据)(?:上述|以下|该)?(?:文章|该文章|该文|本文|文中|报道|该报道|文件|该文件|原文)?[^，。；:：]{0,24}[，,:：]\s*/i, '')
    .replace(/^(?:文章|该文章|该文|本文|文中|报道|该报道|报告|该报告|文件|该文件|原文)(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|说明|表明)(?:了|：|,|，)?/i, '')
    .replace(/(?:文章|该文章|该文|本文|文中|报道|该报道|报告|该报告|文件|该文件|原文)(?:中)?/g, '')
    .replace(/(?:报告|该报告)(?:指出|显示|提到|分析|讨论|说明|称)(?:了)?/g, '')
    .replace(/(?:可|可以|能够)?为[^。；]*提供(?:参考|框架|借鉴)[^。；]*[。；]?/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  next = replaceWeeklyEntityAlias(next);
  next = replaceFormalReportTerms(next);

  next = next
    .replace(/包括\s*[、，]\s*和/g, '包括')
    .replace(/[、，]\s*和\s*\.\.\./g, '')
    .replace(/\s*\.\.\.\s*/g, '')
    .replace(/\s*([，。；：！？])/g, '$1')
    .replace(/\(\s*\)/g, '')
    .replace(/（\s*）/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!next) return '';
  if (FORMAL_NOISE_REGEX.test(next)) return '';

  const stripped = stripAsciiWords(next);
  if (containsChinese(stripped)) {
    next = stripped;
  } else if (!containsChinese(next)) {
    return '';
  }

  if (!next) return '';
  if (FORMAL_META_PREFIX_REGEX.test(next.slice(0, 40))) {
    next = next.replace(FORMAL_META_PREFIX_REGEX, '').trim();
  }

  next = next.replace(/^[，。；：！？\-\s]+/g, '').trim();
  if (!next) return '';
  if (!/[。！？]$/.test(next)) next = `${next}。`;
  return next;
}

function sanitizeFormalParagraph(text, options = {}) {
  const maxLength = Math.max(120, Number(options.maxLength) || 1200);
  const minLength = Math.max(0, Number(options.minLength) || 0);
  const maxSentences = Math.max(1, Number(options.maxSentences) || 6);
  const preferNumeric = Boolean(options.preferNumeric);

  const raw = String(text || '').trim();
  if (!raw) return '';

  const candidates = splitFormalSentences(raw)
    .map((sentence) => sanitizeFormalPlainText(sentence))
    .filter(Boolean);

  if (!candidates.length) return '';

  const unique = uniqueList(candidates).slice(0, 20);
  const ordered = preferNumeric
    ? unique.sort((a, b) => {
      const scoreA = hasMeaningfulNumericSignal(a) ? 1 : 0;
      const scoreB = hasMeaningfulNumericSignal(b) ? 1 : 0;
      return scoreB - scoreA;
    })
    : unique;

  let merged = ordered.slice(0, maxSentences).join('');
  if (merged.length > maxLength) {
    merged = `${merged.slice(0, maxLength)}...`;
  }
  if (merged.length < minLength) {
    return '';
  }
  return merged;
}

function sanitizeFormalTitle(value, fallback = '未命名章节') {
  const raw = String(value || '').trim();
  if (!raw) return fallback;

  let normalized = sanitizeFormalParagraph(raw, {
    maxLength: 80,
    maxSentences: 1
  }).replace(/[。！？!?；;]+$/g, '').trim();

  if (!normalized || !containsChinese(normalized)) {
    for (const hint of FORMAL_SECTION_HINTS) {
      if (hint.regex.test(raw)) return hint.title;
    }
    return fallback;
  }

  return normalized;
}

function sanitizeFormalCell(value) {
  const text = String(value ?? '').trim();
  if (!text) return '-';
  if (/^https?:\/\//i.test(text)) return text;
  if (/^S\d+$/i.test(text)) return text.toUpperCase();

  const normalized = sanitizeFormalParagraph(text, {
    maxLength: 100,
    maxSentences: 1
  }).replace(/[。！？!?；;]+$/g, '').trim();

  if (normalized) return normalized;

  const replaced = replaceFormalReportTerms(replaceWeeklyEntityAlias(text));
  if (containsChinese(replaced)) {
    return replaced.replace(/\s+/g, ' ').trim();
  }

  if (hasMeaningfulNumericSignal(replaced) || /\d/.test(replaced)) {
    return replaced;
  }

  return '-';
}

function buildFactPointFromSource(source, fallbackText = '原始来源未披露具体数值。') {
  const facts = extractWeeklyQuantFacts(source, 2);
  if (facts.length) {
    const merged = sanitizeFormalParagraph(facts.join(' '), {
      maxLength: 220,
      maxSentences: 3,
      preferNumeric: true
    });
    if (merged) return merged;
  }

  const base = sanitizeFormalParagraph(source?.summary || source?.title || '', {
    maxLength: 180,
    maxSentences: 2
  });
  if (base) {
    if (hasMeaningfulNumericSignal(base)) return base;
    return `${base.replace(/[。！？!?；;]+$/g, '')} 原始来源未披露具体数值。`;
  }

  return fallbackText;
}

function cleanupWeeklyCandidateText(text) {
  return String(text || '')
    .replace(/[“”"']/g, '')
    .replace(/\(\s*\)/g, '')
    .replace(/（\s*）/g, '')
    .replace(/\s*-\s*/g, ' ')
    .replace(/\s*[,:;]\s*/g, '，')
    .replace(/^\d+(?:\.\d+)?%?\s*[，、\-:：]*\s*(?=[\u4e00-\u9fff])/g, '')
    .replace(/^[^\u4e00-\u9fff]*(?=[\u4e00-\u9fff])/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。；：！？])/g, '$1')
    .trim();
}

function normalizeWeeklyEntityName(value) {
  const replaced = replaceWeeklyEntityAlias(normalizeText(value, 80));
  const stripped = stripAsciiWords(replaced);
  if (containsChinese(stripped)) return stripped;
  if (containsChinese(replaced)) return replaced;
  return '相关主体';
}

function normalizeWeeklyCategoryName(value) {
  const raw = normalizeText(value, 40);
  if (!raw) return '相关动态';
  const replaced = replaceWeeklyEntityAlias(raw);
  const stripped = stripAsciiWords(replaced);
  if (containsChinese(stripped)) return stripped;
  if (containsChinese(replaced)) return replaced;
  return '相关动态';
}

function hasWeeklyFactSignal(sentence) {
  const text = String(sentence || '');
  if (!text) return false;
  if (WEEKLY_FACT_SIGNAL_REGEX.test(text)) return true;
  return /\d+(?:\.\d+)?\s*(?:亿元|亿户|万户|万|亿|%|亿美元|港元|人民币|个|项|条|年|月|日)/.test(text);
}

function isWeeklySubjectiveSentence(sentence) {
  return WEEKLY_SUBJECTIVE_REGEX.test(String(sentence || ''));
}

function isWeeklyInterpretiveSentence(sentence) {
  return WEEKLY_INTERPRETIVE_REGEX.test(String(sentence || ''));
}

function pickWeeklyEventDateText(item) {
  const value = item?.publishedAt || item?.capturedAt || item?.createdAt || '';
  const ts = Date.parse(String(value || ''));
  if (Number.isNaN(ts)) return '本周';
  return formatShortDate(new Date(ts).toISOString());
}

function weeklyCategoryAction(category) {
  const name = String(category || '').trim();
  if (name === '财报') return '披露财务信息';
  if (name === '产品发布会') return '发布产品或技术信息';
  if (name === '中标公示') return '披露项目中标信息';
  if (name === '高管言论') return '披露管理层公开表态';
  if (name === '政策法规') return '发布政策或监管信息';
  if (name === '宏观数据') return '发布统计或宏观数据信息';
  return '发布公开信息';
}

function buildWeeklyBaseFactDetail(item) {
  const eventText = pickWeeklyEventDateText(item);
  const competitor = normalizeWeeklyEntityName(item?.competitor);
  const category = normalizeWeeklyCategoryName(item?.category);
  const action = weeklyCategoryAction(item?.category);
  return `${eventText}，${competitor}在${category}领域${action}。`;
}

function stripDateLikeNumbers(text) {
  return String(text || '')
    .replace(/20\d{2}\s*[年\/\-.]\s*\d{1,2}\s*[月\/\-.]\s*\d{1,2}\s*日?/g, ' ')
    .replace(/\d{1,2}\s*[\/\-.]\s*\d{1,2}\s*[\/\-.]\s*20\d{2}/g, ' ')
    .replace(/\d{1,2}:\d{2}(?::\d{2})?/g, ' ')
    .replace(/\b20\d{2}\b/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function hasMeaningfulNumericSignal(rawText) {
  const raw = String(rawText || '');
  if (!raw) return false;
  const withoutDates = stripDateLikeNumbers(raw);
  const numbers = withoutDates.match(/\d+(?:,\d{3})*(?:\.\d+)?/g) || [];
  if (!numbers.length) return false;
  if (WEEKLY_METRIC_UNIT_REGEX.test(raw)) return true;
  return WEEKLY_METRIC_CUE_REGEX.test(raw);
}

function toWeeklySentenceCandidate(rawSentence) {
  const rewritten = rewriteWeeklyMetaSentence(rawSentence);
  const replaced = replaceWeeklyEntityAlias(rewritten);
  const cleaned = cleanupWeeklyCandidateText(stripAsciiWords(replaced))
    .replace(/\s+/g, ' ')
    .trim();
  return {
    raw: String(rawSentence || ''),
    text: cleaned
  };
}

function isReadableWeeklyChineseSentence(text) {
  const value = String(text || '').trim();
  if (!value) return false;
  if (/^[,，.。;；:：\-]/.test(value)) return false;

  const chineseCount = (value.match(/[\u4e00-\u9fff]/g) || []).length;
  if (chineseCount < 8) return false;

  const meaningfulCount = (value.match(/[A-Za-z\u4e00-\u9fff0-9]/g) || []).length;
  if (!meaningfulCount) return false;

  const punctuationCount = (value.match(/[，。；：、,.;:（）()\-]/g) || []).length;
  if (punctuationCount > chineseCount) return false;

  return (chineseCount / meaningfulCount) >= 0.4;
}

function extractWeeklyQuantFacts(item, maxItems = 2) {
  const rawSnippet = String(item?.rawSnippet || '').trim();
  const rawText = [
    item?.title,
    item?.summary,
    item?.significance,
    containsChinese(rawSnippet) ? rawSnippet : ''
  ].filter(Boolean).join(' ');

  const candidates = splitWeeklySentences(rawText)
    .map((sentence) => toWeeklySentenceCandidate(sentence))
    .filter((row) => row.text)
    .filter((row) => containsChinese(row.text))
    .filter((row) => isReadableWeeklyChineseSentence(row.text))
    .filter((row) => !isWeeklyMetaNoise(row.text))
    .filter((row) => !isWeeklyInterpretiveSentence(row.text))
    .filter((row) => hasMeaningfulNumericSignal(replaceWeeklyEntityAlias(row.raw) || row.text))
    .map((row) => {
      const normalized = cleanupWeeklyCandidateText(row.text)
        .replace(/(\.\.\.|…|……)+/g, '')
        .replace(/[。！？!?；;]+$/g, '')
        .trim();
      if (!normalized) return '';
      if (!isReadableWeeklyChineseSentence(normalized)) return '';
      if (normalized.length <= 96) return `${normalized}。`;
      return `${normalized.slice(0, 96).replace(/[，,、和及与或并且同时]+$/g, '').trim()}。`;
    })
    .filter(Boolean);

  return uniqueList(candidates).slice(0, Math.max(1, Number(maxItems) || 2));
}

function weeklyQuantSignalScore(item) {
  const rawSnippet = String(item?.rawSnippet || '').trim();
  const rawText = [
    item?.title,
    item?.summary,
    item?.significance,
    containsChinese(rawSnippet) ? rawSnippet : ''
  ].filter(Boolean).join(' ');

  if (!rawText) return 0;

  const rows = splitWeeklySentences(rawText).map((sentence) => ({
    raw: replaceWeeklyEntityAlias(sentence),
    text: stripAsciiWords(replaceWeeklyEntityAlias(sentence))
  }));

  let score = 0;
  for (const row of rows) {
    if (!row.text || !containsChinese(row.text)) continue;
    if (hasMeaningfulNumericSignal(row.raw)) score += 3;
    if (WEEKLY_METRIC_UNIT_REGEX.test(row.raw)) score += 1;
    if (WEEKLY_METRIC_CUE_REGEX.test(row.raw)) score += 1;
  }

  return score;
}

function parseDateYmdToIso(year, month, day) {
  const y = Number(year);
  const m = Number(month);
  const d = Number(day);
  if (!Number.isFinite(y) || !Number.isFinite(m) || !Number.isFinite(d)) return '';
  if (y < 2000 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return '';
  const date = new Date(Date.UTC(y, m - 1, d, 4, 0, 0));
  if (date.getUTCFullYear() !== y || date.getUTCMonth() !== (m - 1) || date.getUTCDate() !== d) return '';
  return date.toISOString();
}

function parseMonthNameToNumber(value) {
  const key = String(value || '').trim().toLowerCase();
  const map = {
    jan: 1,
    january: 1,
    feb: 2,
    february: 2,
    mar: 3,
    march: 3,
    apr: 4,
    april: 4,
    may: 5,
    jun: 6,
    june: 6,
    jul: 7,
    july: 7,
    aug: 8,
    august: 8,
    sep: 9,
    sept: 9,
    september: 9,
    oct: 10,
    october: 10,
    nov: 11,
    november: 11,
    dec: 12,
    december: 12
  };
  return map[key] || 0;
}

function extractDateCandidates(text) {
  const raw = String(text || '');
  if (!raw) return [];

  const candidates = [];
  const pushIso = (iso) => {
    const ts = Date.parse(String(iso || ''));
    if (Number.isNaN(ts)) return;
    candidates.push(new Date(ts).toISOString());
  };

  raw.replace(/(20\d{2})\s*[年\/\-.]\s*(\d{1,2})\s*[月\/\-.]\s*(\d{1,2})\s*日?/g, (match, year, month, day) => {
    pushIso(parseDateYmdToIso(year, month, day));
    return match;
  });

  raw.replace(/(\d{1,2})\s*[\/\-.]\s*(\d{1,2})\s*[\/\-.]\s*(20\d{2})/g, (match, month, day, year) => {
    pushIso(parseDateYmdToIso(year, month, day));
    return match;
  });

  raw.replace(/\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t|tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2}),?\s+(20\d{2})\b/gi, (match, monthName, day, year) => {
    const month = parseMonthNameToNumber(monthName);
    pushIso(parseDateYmdToIso(year, month, day));
    return match;
  });

  return uniqueList(candidates).sort((a, b) => Date.parse(b) - Date.parse(a));
}

function getRangeMs(range) {
  const startMs = Date.parse(String(range?.start || ''));
  const endMs = Date.parse(String(range?.end || ''));
  return {
    startMs: Number.isNaN(startMs) ? 0 : startMs,
    endMs: Number.isNaN(endMs) ? Date.now() : endMs
  };
}

function inWeeklyRange(timestamp, range, toleranceMs = WEEKLY_RANGE_TOLERANCE_MS) {
  const ts = Number(timestamp);
  if (!Number.isFinite(ts) || ts <= 0) return false;
  const { startMs, endMs } = getRangeMs(range);
  return ts >= (startMs - toleranceMs) && ts <= (endMs + toleranceMs);
}

function resolveWeeklyEventAt(item, range) {
  const rangeMs = getRangeMs(range);
  const baselineCandidates = [item?.publishedAt, item?.capturedAt, item?.createdAt]
    .map((value) => {
      const ts = Date.parse(String(value || ''));
      if (Number.isNaN(ts)) return null;
      return { ts, iso: new Date(ts).toISOString() };
    })
    .filter(Boolean)
    .sort((a, b) => b.ts - a.ts);

  const fallback = baselineCandidates.find((row) => inWeeklyRange(row.ts, range));

  const textPool = [item?.title, item?.summary, item?.significance, item?.rawSnippet].join(' ');
  const textDateCandidates = extractDateCandidates(textPool)
    .map((iso) => {
      const ts = Date.parse(iso);
      return Number.isNaN(ts) ? null : { ts, iso };
    })
    .filter(Boolean);

  const inRangeTextDate = textDateCandidates.find((row) => inWeeklyRange(row.ts, range));
  if (inRangeTextDate) return inRangeTextDate.iso;

  if (textDateCandidates.length) {
    const freshestTextTs = textDateCandidates[0].ts;
    if (freshestTextTs < (rangeMs.startMs - WEEKLY_RANGE_TOLERANCE_MS)) {
      return '';
    }
  }

  return fallback ? fallback.iso : '';
}

function splitWeeklySentences(text) {
  return String(text || '')
    .replace(/\r?\n+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .split(/(?<=[。！？!?；;])\s+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function rewriteWeeklyMetaSentence(sentence) {
  let text = String(sentence || '')
    .replace(/\*\*/g, '')
    .replace(/`/g, '')
    .replace(/\[[^\]]+\]/g, '')
    .replace(/^\s*(?:[-*•]|\d+[.)、])\s*/g, '')
    .trim();

  text = replaceWeeklyEntityAlias(text);

  text = text
    .replace(/^文件标题为[“"']([^”"']+)[”"']\s*[，,:：]?\s*摘要(?:说明|提及)?(?:其目的(?:是)?|指出)?(?:为|是)?\s*/i, '《$1》显示')
    .replace(/^标题为[“"']([^”"']+)[”"']\s*[，,:：]?\s*摘要(?:说明|提及)?(?:其目的(?:是)?|指出)?(?:为|是)?\s*/i, '《$1》显示')
    .replace(/^输入内容为\s*/i, '')
    .replace(/^该文件表明\s*/i, '该文件显示')
    .replace(/^件表明\s*/i, '该文件显示')
    .replace(/^件显示\s*/i, '该文件显示')
    .replace(/^\s*是\s+/g, '')
    .replace(/^(?:文章|该文章|该文|文中|报道|报告)(?:主要)?(?:讨论|分析|指出|提到|介绍|聚焦|围绕|显示|称|提及|报道)(?:了|：|,|，)?/i, '')
    .replace(/(?:可|可以|能够)?为[^。；]*提供(?:参考|框架|借鉴)[^。；]*[。；]?/g, '')
    .replace(/^\s*(?:并|且|同时|此外|另外|其中)\s*/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  if (!text) return '';

  text = text
    .replace(/这表明/g, '公开信息显示')
    .replace(/这意味着/g, '公开信息显示')
    .replace(/值得关注的是/g, '')
    .replace(/本文|该文|该报道|该报告|文章|报道/g, '')
    .replace(/^关于/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。；：！？])/g, '$1')
    .trim();

  if (!text) return '';
  if (!/[。！？]$/.test(text)) return `${text}。`;
  return text;
}

function isWeeklyMetaNoise(sentence) {
  const text = String(sentence || '');
  if (!text) return true;

  return /(与查询主题(?:高度)?不相关|信息不相关|无直接情报价值|仅供参考|参考框架|查询主题|无法从中提炼|建议即刻|建议管理层|人工复核|可能|或许|推测|建议|宜|应当|应尽快|文章讨论|文章分析|文中指出|摘要说明|输入内容为|文件标题为)/.test(text);
}

function normalizeWeeklyFactSentence(text) {
  const rewritten = splitWeeklySentences(text)
    .map((sentence) => rewriteWeeklyMetaSentence(sentence))
    .map((sentence) => replaceWeeklyEntityAlias(sentence))
    .map((sentence) => stripAsciiWords(sentence))
    .filter(Boolean)
    .filter((sentence) => containsChinese(sentence))
    .filter((sentence) => !isWeeklyMetaNoise(sentence));

  if (!rewritten.length) return '';

  const factual = rewritten.filter((sentence) => (
    (hasWeeklyFactSignal(sentence) || !isWeeklySubjectiveSentence(sentence))
    && !isWeeklyInterpretiveSentence(sentence)
  ));
  if (!factual.length) return '';

  return uniqueList(factual).slice(0, 2).join(' ');
}

function normalizeSourceId(value) {
  const text = String(value || '').trim().toUpperCase();
  if (!/^S\d+$/.test(text)) return '';
  return text;
}

function uniqueList(items) {
  const seen = new Set();
  const result = [];
  for (const item of items) {
    const key = String(item || '');
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(key);
  }
  return result;
}

function extractSourceIdsFromText(text) {
  const raw = String(text || '');
  const found = [];
  raw.replace(/\[\s*(S\d+)\s*\]/gi, (match, sourceId) => {
    const normalized = normalizeSourceId(sourceId);
    if (normalized) found.push(normalized);
    return match;
  });

  return uniqueList(found);
}

function extractYearHints(text, upperYear) {
  const maxYear = Number.isFinite(upperYear) ? upperYear : (new Date().getFullYear() + 1);
  const years = new Set();
  String(text || '').replace(/(?:19|20)\d{2}/g, (match) => {
    const year = Number(match);
    if (Number.isFinite(year) && year >= 2000 && year <= maxYear) {
      years.add(year);
    }
    return match;
  });
  return Array.from(years).sort((a, b) => a - b);
}

function detectFiscalYearHint(text, upperYear) {
  const maxYear = Number.isFinite(upperYear) ? upperYear : (new Date().getFullYear() + 1);
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
    if (Number.isFinite(year) && year >= 2000 && year <= maxYear) {
      return year;
    }
  }

  return null;
}

function isOutdatedFinanceFinding(item, rangeEndIso) {
  const reportYear = new Date(rangeEndIso || Date.now()).getFullYear();
  const staleThreshold = reportYear - 2;
  const category = String(item?.category || '');
  if (category !== '财报') return false;

  const title = String(item?.title || '');
  const summary = String(item?.summary || '');
  const snippet = String(item?.rawSnippet || '');
  const text = `${title} ${summary} ${snippet}`;

  const fiscalYear = detectFiscalYearHint(text, reportYear + 1);
  if (fiscalYear && fiscalYear <= staleThreshold) {
    return true;
  }

  const yearHints = extractYearHints(text, reportYear + 1);
  if (!yearHints.length) return false;

  const hasFinanceCue = /(业绩|财报|年报|results|earnings|annual report|interim report)/i.test(text);
  if (!hasFinanceCue) return false;
  return Math.max(...yearHints) <= staleThreshold;
}

function isOutdatedByYearHint(item, rangeEndIso) {
  const reportYear = new Date(rangeEndIso || Date.now()).getFullYear();
  const staleThreshold = reportYear - 2;
  const text = `${item?.title || ''} ${item?.summary || ''} ${item?.rawSnippet || ''}`;
  const hints = extractYearHints(text, reportYear + 1);
  if (!hints.length) return false;
  return Math.max(...hints) <= staleThreshold;
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

function containsAny(text, keywords) {
  const haystack = String(text || '').toLowerCase();
  if (!haystack) return false;
  return keywords.some((keyword) => haystack.includes(String(keyword || '').toLowerCase()));
}

function findingTimestamp(item) {
  const baseline = item?.publishedAt || item?.capturedAt || item?.createdAt;
  const ts = Date.parse(String(baseline || ''));
  return Number.isNaN(ts) ? 0 : ts;
}

function isWeeklySocialCandidate(item) {
  if (!item || typeof item !== 'object') return false;
  if (hasWeeklySocialSignal(item)) return true;

  const category = String(item?.category || '').trim();
  const policyOrMacro = ['政策法规', '宏观数据'].includes(category);
  const officialSocialSource = isWeeklyOfficialSocialSource(item);
  if (!policyOrMacro && !officialSocialSource) return false;
  if (isWeeklyTelecomOperatorSource(item) && !policyOrMacro) return false;

  const text = [
    item?.title,
    item?.summary,
    item?.significance,
    item?.competitor,
    item?.region,
    item?.sourceUrl
  ].join(' ').toLowerCase();
  return /香港|hong kong|gov\.hk|censtatd|news\.gov\.hk|housing|tourism|employment|retail|cpi|房屋|旅游|就业|零售|通胀|社会|民生/.test(text);
}

function scoreFindingRelevance(item, reportType) {
  const hostname = extractHostname(item?.sourceUrl);
  const url = String(item?.sourceUrl || '').toLowerCase();
  const titleText = String(item?.title || '').toLowerCase();
  const summaryText = [
    item?.summary,
    item?.significance,
    ...(Array.isArray(item?.keywords) ? item.keywords : [])
  ].join(' ').toLowerCase();
  const coreText = [titleText, summaryText].join(' ');
  const extendedText = [
    coreText,
    item?.rawSnippet
  ].join(' ').toLowerCase();

  const competitorName = String(item?.competitor || '').trim().toLowerCase();
  const categoryName = String(item?.category || '').trim();

  let score = 0;
  const reasons = [];
  const trustedDomain = TRUSTED_REPORT_DOMAINS.some((domain) => domainMatches(hostname, domain));
  const competitorMention = Boolean(competitorName && (titleText.includes(competitorName) || String(item?.sourceUrl || '').toLowerCase().includes(competitorName)));
  const telecomSignal = containsAny(coreText, TELECOM_KEYWORDS);
  const socialSignal = containsAny(coreText, WEEKLY_SOCIAL_KEYWORDS);
  const policySignal = (categoryName === '政策法规') || (Array.isArray(CATEGORY_KEYWORDS.政策法规) && containsAny(coreText, CATEGORY_KEYWORDS.政策法规));
  const macroSignal = (categoryName === '宏观数据') || (Array.isArray(CATEGORY_KEYWORDS.宏观数据) && containsAny(coreText, CATEGORY_KEYWORDS.宏观数据));
  const titleLooksNoise = containsAny(titleText, IRRELEVANT_KEYWORDS);
  const disclosureSignal = /earnings|results|financial|investor|announcement|guidance|dividend|capex|财报|业绩|发布|中标|招标|高管|发言/.test(coreText);
  const institutionEntitySignal = /ofca|commission|itu|oecd|government|statistics|census|ofcom|fcc|world bank|imf|gsma|miit|gov|政府|统计|监管|工信部|网信办/.test(competitorName);
  const hkPublicSignal = /hong kong|香港|gov\.hk|censtatd|news\.gov\.hk|housing|tourism|employment|retail|cpi|房屋|旅游|就业|零售|通胀/.test(extendedText);

  if (competitorMention) {
    score += 4;
    reasons.push('命中竞对实体');
  }

  if (telecomSignal) {
    score += 3;
    reasons.push('命中电信行业关键词');
  }

  if (policySignal) {
    score += 2;
    reasons.push('命中政策法规信号');
  }

  if (macroSignal) {
    score += 2;
    reasons.push('命中宏观数据信号');
  }

  if (socialSignal) {
    score += 2;
    reasons.push('命中社会民生信号');
  }

  if (socialSignal && (categoryName === '宏观数据' || categoryName === '政策法规' || hkPublicSignal)) {
    score += 1;
    reasons.push('社会资讯优先信号');
  }

  if (categoryName && Array.isArray(CATEGORY_KEYWORDS[categoryName]) && containsAny(coreText, CATEGORY_KEYWORDS[categoryName])) {
    score += 2;
    reasons.push(`命中类别关键词:${categoryName}`);
  }

  if (trustedDomain) {
    score += 3;
    reasons.push('权威/行业来源域名');
  }

  if (institutionEntitySignal) {
    score += 1;
    reasons.push('命中机构/监管对象');
  }

  if (/investor|earnings|results|financial|press|newsroom|announcement|ir\//i.test(url)) {
    score += 1;
    reasons.push('命中披露类URL特征');
  }

  if (containsAny(extendedText, IRRELEVANT_KEYWORDS)) {
    score -= 5;
    reasons.push('疑似非行业噪音');
  }
  if (titleLooksNoise) {
    score -= 3;
  }

  const weeklyHardEligible = Boolean(
    competitorMention
    || (trustedDomain && (telecomSignal || disclosureSignal || policySignal || macroSignal))
    || ((policySignal || macroSignal) && (trustedDomain || institutionEntitySignal))
    || (socialSignal && (trustedDomain || institutionEntitySignal || hkPublicSignal))
  );
  const trendHardEligible = Boolean(telecomSignal || trustedDomain || competitorMention || policySignal || macroSignal);

  if (reportType === 'weekly' && !weeklyHardEligible) {
    score -= 6;
    reasons.push('未通过周报硬性相关性门槛');
  }

  if (reportType === 'trend' && !trendHardEligible) {
    score -= 3;
    reasons.push('未通过趋势报告基础相关性门槛');
  }

  return {
    score,
    reasons,
    hostname,
    weeklyHardEligible,
    trendHardEligible,
    competitorMention,
    telecomSignal,
    trustedDomain
  };
}

function selectRelevantFindings(findings, { reportType, maxFindings }) {
  const dedupByUrl = new Map();
  for (const item of findings || []) {
    const key = String(item?.sourceUrl || '').trim() || String(item?.id || '');
    if (!key) continue;
    if (!dedupByUrl.has(key)) {
      dedupByUrl.set(key, item);
    }
  }

  const scored = Array.from(dedupByUrl.values()).map((item) => {
    const relevance = scoreFindingRelevance(item, reportType);
    return {
      item,
      relevance,
      timestamp: findingTimestamp(item)
    };
  }).sort((a, b) => {
    if (b.relevance.score !== a.relevance.score) {
      return b.relevance.score - a.relevance.score;
    }
    return b.timestamp - a.timestamp;
  });

  const highThreshold = reportType === 'weekly' ? 6 : 4;
  const mediumThreshold = reportType === 'weekly' ? 3 : 2;
  const minTarget = reportType === 'weekly' ? 8 : 12;

  const selected = [];
  for (const row of scored) {
    if (reportType === 'weekly' && !row.relevance.weeklyHardEligible) continue;
    if (reportType === 'trend' && !row.relevance.trendHardEligible) continue;
    if (row.relevance.score >= highThreshold) {
      selected.push(row);
    }
    if (selected.length >= maxFindings) break;
  }

  if (selected.length < minTarget) {
    for (const row of scored) {
      if (selected.includes(row)) continue;
      if (reportType === 'weekly' && !row.relevance.weeklyHardEligible) continue;
      if (reportType === 'trend' && !row.relevance.trendHardEligible) continue;
      if (row.relevance.score < mediumThreshold) continue;
      selected.push(row);
      if (selected.length >= Math.min(maxFindings, minTarget)) break;
    }
  }

  if (selected.length < 6) {
    for (const row of scored) {
      if (selected.includes(row)) continue;
      if (reportType === 'weekly' && !row.relevance.weeklyHardEligible) continue;
      if (reportType === 'trend' && !row.relevance.trendHardEligible) continue;
      if (row.relevance.score <= 0) continue;
      selected.push(row);
      if (selected.length >= Math.min(maxFindings, 8)) break;
    }
  }

  if (reportType === 'weekly' && selected.length) {
    const hasSocialCandidateInSelected = selected.some((row) => isWeeklySocialCandidate(row.item));
    if (!hasSocialCandidateInSelected) {
      const candidate = scored.find((row) => (
        !selected.includes(row)
        && row.relevance.weeklyHardEligible
        && isWeeklySocialCandidate(row.item)
      ));

      if (candidate) {
        if (selected.length < maxFindings) {
          selected.push(candidate);
        } else {
          let replaceIndex = -1;
          for (let i = selected.length - 1; i >= 0; i -= 1) {
            if (!isWeeklySocialCandidate(selected[i].item)) {
              replaceIndex = i;
              break;
            }
          }
          if (replaceIndex >= 0) {
            selected[replaceIndex] = candidate;
          }
        }
      }
    }
  }

  selected.sort((a, b) => {
    if (b.relevance.score !== a.relevance.score) return b.relevance.score - a.relevance.score;
    return b.timestamp - a.timestamp;
  });

  const finalSelected = selected.slice(0, maxFindings).map((row) => row.item);
  return {
    findings: finalSelected,
    stats: {
      totalWindowFindings: scored.length,
      selectedCount: finalSelected.length,
      highQualityCount: scored.filter((row) => row.relevance.score >= highThreshold).length,
      mediumQualityCount: scored.filter((row) => row.relevance.score >= mediumThreshold).length,
      droppedCount: Math.max(0, scored.length - finalSelected.length),
      topSamples: scored.slice(0, 5).map((row) => ({
        score: row.relevance.score,
        title: normalizeText(row.item.title, 120),
        url: row.item.sourceUrl
      }))
    }
  };
}

function pickFindingsByWindow(findings, startIso, endIso, maxItems) {
  const startMs = Date.parse(startIso);
  const endMs = Date.parse(endIso);
  const safeMax = Number.isFinite(Number(maxItems)) && Number(maxItems) > 0
    ? Math.floor(Number(maxItems))
    : Number.POSITIVE_INFINITY;

  const filtered = findings.filter((item) => {
    const baseline = item.publishedAt || item.capturedAt || item.createdAt;
    if (!baseline) return false;
    const timestamp = Date.parse(baseline);
    if (Number.isNaN(timestamp)) return false;
    return timestamp >= startMs && timestamp <= endMs;
  });

  return filtered
    .sort((a, b) => findingTimestamp(b) - findingTimestamp(a))
    .slice(0, safeMax);
}

function buildSourceCatalog(findings, limit = 30) {
  return findings.slice(0, limit).map((item, index) => ({
    ...item,
    sourceId: `S${index + 1}`
  }));
}

function buildSourcePack(sourceCatalog) {
  return sourceCatalog.map((item) => ({
    sourceId: item.sourceId,
    findingId: item.id,
    competitor: item.competitor,
    region: item.region,
    category: item.category,
    title: item.title,
    summary: item.summary,
    significance: item.significance,
    keywords: item.keywords,
    sourceUrl: item.sourceUrl,
    publishedAt: item.publishedAt,
    capturedAt: item.capturedAt
  }));
}

function buildDistribution(findings, key, maxItems = 8) {
  const map = new Map();
  for (const item of findings) {
    const label = normalizeText(item[key] || '未知', 60) || '未知';
    map.set(label, (map.get(label) || 0) + 1);
  }

  return Array.from(map.entries())
    .map(([label, count]) => ({ label, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, maxItems);
}

function buildTrendSeries(findings, days = 14) {
  const safeDays = Math.max(7, Math.min(30, Number(days) || 14));
  const byDate = new Map();

  for (let i = safeDays - 1; i >= 0; i -= 1) {
    const date = new Date(Date.now() - i * 24 * 60 * 60 * 1000);
    const key = date.toISOString().slice(0, 10);
    byDate.set(key, 0);
  }

  for (const item of findings) {
    const baseline = item.publishedAt || item.capturedAt || item.createdAt;
    const timestamp = Date.parse(baseline || '');
    if (Number.isNaN(timestamp)) continue;
    const key = new Date(timestamp).toISOString().slice(0, 10);
    if (!byDate.has(key)) continue;
    byDate.set(key, (byDate.get(key) || 0) + 1);
  }

  const labels = Array.from(byDate.keys()).map((date) => date.slice(5));
  const values = Array.from(byDate.values());
  return { labels, values };
}

function toPercentText(count, total) {
  if (!total) return '0.0%';
  return `${((count / total) * 100).toFixed(1)}%`;
}

function normalizeWeeklyTitle(item) {
  const sanitizeTitle = (value) => String(value || '')
    .replace(/(\.\.\.|…|……)+/g, '')
    .replace(/[。！？!?；;]+$/g, '')
    .replace(/[，,、和及与或并且同时]+$/g, '')
    .replace(/\s+/g, ' ')
    .trim();

  const quantHeadline = extractWeeklyQuantFacts(item, 1)[0] || '';
  if (quantHeadline) {
    const compact = sanitizeTitle(cleanupWeeklyCandidateText(quantHeadline)
      .replace(/^[\d\s:/-]+[，,]\s*/g, '')
      .trim());
    if (compact && /^[\u4e00-\u9fff]/.test(compact) && isReadableWeeklyChineseSentence(compact)) {
      return compact;
    }
  }

  const raw = [
    normalizeText(item?.title, 220),
    normalizeText(item?.summary, 260)
  ].join(' ');

  const candidates = uniqueList(
    splitWeeklySentences(raw)
      .map((sentence) => rewriteWeeklyMetaSentence(sentence))
      .map((sentence) => replaceWeeklyEntityAlias(sentence))
      .map((sentence) => cleanupWeeklyCandidateText(stripAsciiWords(sentence)))
      .map((sentence) => sentence
        .replace(/^[【\[][^】\]]+[】\]]\s*/g, '')
        .replace(/[。！？!?；;]+$/g, '')
        .trim())
      .filter(Boolean)
      .filter((sentence) => containsChinese(sentence))
      .filter((sentence) => /^[\u4e00-\u9fff]/.test(sentence))
      .filter((sentence) => !isWeeklyMetaNoise(sentence))
      .filter((sentence) => !isWeeklyInterpretiveSentence(sentence))
      .filter((sentence) => hasWeeklyFactSignal(sentence))
  );

  let title = sanitizeTitle(candidates[0] || `${normalizeWeeklyEntityName(item?.competitor)}${normalizeWeeklyCategoryName(item?.category)}信息更新`);
  return title || '行业动态更新';
}

function normalizeWeeklyDetail(item) {
  const base = buildWeeklyBaseFactDetail(item);
  const quantFacts = extractWeeklyQuantFacts(item, 2);
  if (quantFacts.length) {
    return `${base} ${quantFacts.join(' ')}`.trim();
  }

  const summary = normalizeWeeklyFactSentence(normalizeText(item?.summary, 360));
  const significance = normalizeWeeklyFactSentence(normalizeText(item?.significance, 360));
  const mergedSentences = uniqueList([
    ...splitWeeklySentences(summary),
    ...splitWeeklySentences(significance)
  ]
    .map((sentence) => replaceWeeklyEntityAlias(sentence))
    .map((sentence) => cleanupWeeklyCandidateText(stripAsciiWords(sentence)))
    .map((sentence) => sentence.trim())
    .filter((sentence) => containsChinese(sentence))
    .filter((sentence) => isReadableWeeklyChineseSentence(sentence))
    .filter((sentence) => !isWeeklyMetaNoise(sentence))
    .filter((sentence) => !isWeeklyInterpretiveSentence(sentence))
    .filter((sentence) => hasWeeklyFactSignal(sentence))
    .filter((sentence) => sentence !== base)
  ).slice(0, 1);

  if (!mergedSentences.length) {
    return `${base} 原文未披露具体金额、用户规模或同比数据。`;
  }
  const fact = mergedSentences[0].replace(/[。！？!?；;]+$/g, '');
  return `${base} ${fact}。 原文未披露具体金额、用户规模或同比数据。`;
}

function extractWeeklyTag(item) {
  const text = [
    item?.title,
    item?.summary,
    item?.significance,
    item?.category,
    item?.competitor
  ].join(' ').toLowerCase();

  for (const rule of WEEKLY_TAG_RULES) {
    if (rule.keywords.some((keyword) => text.includes(String(keyword || '').toLowerCase()))) {
      return rule.tag;
    }
  }

  const category = String(item?.category || '');
  if (category === '政策法规') return '行业相关监管';
  if (category === '宏观数据') return '地缘政治与经济';
  if (category === '财报') return '运营商财报';
  if (category === '产品发布会') return '产品发布会';
  if (category === '中标公示') return '中标公示';
  if (category === '高管言论') return '高管言论';
  return '行业动态';
}

function isWeeklyOfficialSocialSource(item) {
  const competitor = String(item?.competitor || '').trim().toLowerCase();
  const url = String(item?.sourceUrl || '').toLowerCase();
  const region = String(item?.region || '').toLowerCase();
  if (WEEKLY_SOCIAL_SOURCE_COMPETITORS.includes(competitor)) return true;
  return /gov\.hk|news\.gov\.hk|censtatd\.gov\.hk|td\.gov\.hk|housingauthority\.gov\.hk/.test(url)
    || /hong kong/.test(region);
}

function isWeeklyTelecomOperatorSource(item) {
  const competitor = String(item?.competitor || '').trim().toLowerCase();
  if (!competitor) return false;
  return WEEKLY_TELECOM_OPERATOR_HINTS.some((hint) => competitor.includes(hint));
}

function hasWeeklySocialSignal(item) {
  const title = String(item?.title || '');
  const summary = String(item?.summary || '');
  const significance = String(item?.significance || '');
  const competitor = String(item?.competitor || '');
  const region = String(item?.region || '');
  const category = String(item?.category || '').trim();
  const text = `${title} ${summary} ${significance} ${competitor} ${region}`.toLowerCase();
  const socialKeywordHit = containsAny(text, WEEKLY_SOCIAL_KEYWORDS);
  const hkLocalSignal = /香港|hong kong|gov\.hk|censtatd|news\.gov\.hk|房屋局|旅发局|劳工及福利局/.test(text);
  const socialInstitutionHit = containsAny(text, WEEKLY_SOCIAL_INSTITUTIONS);
  const officialSocialSource = isWeeklyOfficialSocialSource(item);
  const telecomOperatorSource = isWeeklyTelecomOperatorSource(item);
  const policyOrMacro = category === '宏观数据' || category === '政策法规';

  if (telecomOperatorSource && !policyOrMacro) {
    return false;
  }

  if (officialSocialSource && (socialKeywordHit || socialInstitutionHit || policyOrMacro)) {
    return true;
  }

  if (socialKeywordHit && ((hkLocalSignal && policyOrMacro) || socialInstitutionHit || officialSocialSource)) {
    return true;
  }

  if (socialInstitutionHit && (officialSocialSource || policyOrMacro)) {
    return true;
  }

  if (!hkLocalSignal || !policyOrMacro) return false;

  if (/(统计|指数|就业|失业|工资|收入|零售|旅游|房屋|公屋|民生|inflation|retail|tourism|employment|income|housing|livelihood)/.test(text)) {
    return true;
  }

  return false;
}

function weeklySocialFallbackScore(item) {
  const title = String(item?.title || '');
  const summary = String(item?.summary || '');
  const significance = String(item?.significance || '');
  const competitor = String(item?.competitor || '');
  const region = String(item?.region || '');
  const category = String(item?.category || '').trim();
  const text = `${title} ${summary} ${significance} ${competitor} ${region}`.toLowerCase();
  const hkLocalSignal = /香港|hong kong|gov\.hk|censtatd|news\.gov\.hk|房屋局|旅发局|劳工及福利局/.test(text);
  const socialInstitutionHit = containsAny(text, WEEKLY_SOCIAL_INSTITUTIONS);
  const hasSocial = hasWeeklySocialSignal(item);
  const officialSocialSource = isWeeklyOfficialSocialSource(item);
  const telecomOperatorSource = isWeeklyTelecomOperatorSource(item);
  const policyOrMacro = category === '宏观数据' || category === '政策法规';

  let score = 0;
  if (hasSocial) score += 6;
  if (officialSocialSource) score += 4;
  if (socialInstitutionHit) score += 3;
  if (hkLocalSignal) score += 2;
  if ((hasSocial || socialInstitutionHit || hkLocalSignal) && category === '宏观数据') score += 3;
  if ((hasSocial || socialInstitutionHit || hkLocalSignal) && category === '政策法规') score += 2;

  if (telecomOperatorSource && !policyOrMacro) score -= 6;
  if (!policyOrMacro && !officialSocialSource) score -= 4;
  if (/africa|ethiopia|eswatini|europe|latin america|middle east/.test(text) && !hkLocalSignal) score -= 3;

  return score;
}

function classifyWeeklySection(item) {
  const title = String(item?.title || '');
  const summary = String(item?.summary || '');
  const significance = String(item?.significance || '');
  const competitor = String(item?.competitor || '');
  const region = String(item?.region || '');
  const category = String(item?.category || '');
  const text = `${title} ${summary} ${significance} ${competitor} ${region}`.toLowerCase();

  const isHongKongPolicy = /香港|特区|施政|立法会|房屋局|公屋|北部都会区|ofca|gov\.hk|财经事务及库务局|财政司/.test(text);
  const isSocial = hasWeeklySocialSignal(item);
  const isInternational = /国际|全球|欧盟|新加坡|美国|中东|东盟|跨境贸易|地缘|kddi|at&t|aws|google|wiz/.test(text);

  if (isHongKongPolicy && !isSocial) return '政治资讯';
  if (isSocial) return '社会资讯';

  if (category === '政策法规' && isHongKongPolicy) return '政治资讯';
  if (category === '政策法规' && !isHongKongPolicy) return '国际资讯';
  if (category === '宏观数据' && isInternational) return '国际资讯';
  if (category === '宏观数据' && !isInternational) return '行业资讯';

  if (isInternational) return '国际资讯';
  return '行业资讯';
}

function getWeeklySectionCap(sectionName) {
  const cap = Number(WEEKLY_SECTION_CAPS[sectionName]);
  if (Number.isFinite(cap) && cap > 0) return cap;
  return 2;
}

function countSectionItems(items, sectionName) {
  return items.reduce((sum, item) => sum + (item.section === sectionName ? 1 : 0), 0);
}

function buildWeeklySectionNarrative(sectionName, rows, range) {
  const periodText = range?.start && range?.end
    ? `${formatShortDate(range.start)}至${formatShortDate(range.end)}`
    : '本周统计窗口';

  if (!Array.isArray(rows) || !rows.length) {
    return `统计区间为${periodText}。${sectionName}暂无纳入条目。`;
  }

  const tags = uniqueList(rows.map((row) => row.tag).filter(Boolean)).slice(0, 4);
  const tagText = tags.length ? `，涉及主题：${tags.join('、')}` : '';
  const eventTimes = rows
    .map((row) => Date.parse(String(row?.eventAt || row?.publishedAt || '')))
    .filter((ts) => Number.isFinite(ts) && ts > 0)
    .sort((a, b) => a - b);
  const eventWindowText = eventTimes.length
    ? `，事件时间范围为${formatShortDate(new Date(eventTimes[0]).toISOString())}至${formatShortDate(new Date(eventTimes[eventTimes.length - 1]).toISOString())}`
    : '';
  return `统计区间为${periodText}。本期${sectionName}共收录${rows.length}条事件${tagText}${eventWindowText}。`;
}

function pickWeeklyEntries(sourceCatalog, range, maxItems = WEEKLY_MAX_ITEMS) {
  const bySection = new Map(WEEKLY_SECTION_ORDER.map((section) => [section, []]));
  const dedupe = new Set();

  const scoredCatalog = [...sourceCatalog].map((item) => ({
    item,
    quantScore: weeklyQuantSignalScore(item),
    ts: findingTimestamp(item)
  }));

  const sortedCatalog = scoredCatalog
    .sort((a, b) => {
      if (b.quantScore !== a.quantScore) return b.quantScore - a.quantScore;
      return b.ts - a.ts;
    })
    .map((row) => row.item);

  for (const source of sortedCatalog) {
    const eventAt = resolveWeeklyEventAt(source, range);
    const eventTs = Date.parse(eventAt || '');
    if (!eventAt || Number.isNaN(eventTs) || !inWeeklyRange(eventTs, range)) continue;

    const title = normalizeWeeklyTitle(source);
    const key = `${title}|${source?.competitor || ''}|${new Date(eventTs).toISOString().slice(0, 10)}`;
    if (dedupe.has(key)) continue;
    dedupe.add(key);

    const section = classifyWeeklySection(source);
    const tag = extractWeeklyTag(source);
    const detail = normalizeWeeklyDetail(source);
    const socialPriority = weeklySocialFallbackScore(source);

    const target = bySection.get(section) || bySection.get('行业资讯');
    target.push({
      findingId: source?.id || '',
      sourceId: source?.sourceId || '',
      competitor: normalizeWeeklyEntityName(source?.competitor || ''),
      section,
      tag,
      title,
      detail,
      eventAt,
      publishedAt: source?.publishedAt || source?.capturedAt || '',
      sourceUrl: source?.sourceUrl || '',
      socialPriority,
      eventTs
    });
  }

  // 社会资讯兜底：当常规分类未命中时，从同一批真实来源中补入社会民生候选，避免周报社会板块缺失。
  const socialRows = bySection.get('社会资讯') || [];
  if (!socialRows.length) {
    const fallbackCandidates = [];
    for (const source of sortedCatalog) {
      const eventAt = resolveWeeklyEventAt(source, range);
      const eventTs = Date.parse(eventAt || '');
      if (!eventAt || Number.isNaN(eventTs) || !inWeeklyRange(eventTs, range)) continue;

      const score = weeklySocialFallbackScore(source);
      if (score <= 0) continue;
      fallbackCandidates.push({ source, score, eventAt, eventTs });
    }

    fallbackCandidates.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return b.eventTs - a.eventTs;
    });

    for (const row of fallbackCandidates) {
      if (socialRows.length >= getWeeklySectionCap('社会资讯')) break;

      const source = row.source;
      const normalizedCompetitor = normalizeWeeklyEntityName(source?.competitor || '');
      const title = normalizeWeeklyTitle(source);
      const key = `${title}|${source?.competitor || ''}|${new Date(row.eventTs).toISOString().slice(0, 10)}`;
      if (dedupe.has(key)) {
        let moved = false;
        for (const sectionName of WEEKLY_SECTION_ORDER) {
          if (sectionName === '社会资讯') continue;
          const sectionRows = bySection.get(sectionName) || [];
          const targetIndex = sectionRows.findIndex((item) => {
            const itemDay = item?.eventAt ? String(item.eventAt).slice(0, 10) : '';
            const rowDay = String(row.eventAt || '').slice(0, 10);
            return String(item?.title || '') === title
              && String(item?.competitor || '') === normalizedCompetitor
              && itemDay === rowDay;
          });
          if (targetIndex < 0) continue;

          const [entry] = sectionRows.splice(targetIndex, 1);
          if (entry) {
            entry.section = '社会资讯';
            socialRows.push(entry);
            moved = true;
          }
          break;
        }
        if (moved) continue;
        continue;
      }
      dedupe.add(key);

      socialRows.push({
        findingId: source?.id || '',
        sourceId: source?.sourceId || '',
        competitor: normalizedCompetitor,
        section: '社会资讯',
        tag: extractWeeklyTag(source),
        title,
        detail: normalizeWeeklyDetail(source),
        eventAt: row.eventAt,
        publishedAt: source?.publishedAt || source?.capturedAt || '',
        sourceUrl: source?.sourceUrl || '',
        socialPriority: row.score,
        eventTs: row.eventTs
      });
    }

    if (!socialRows.length) {
      for (const sectionName of WEEKLY_SECTION_ORDER) {
        if (sectionName === '社会资讯') continue;
        const sectionRows = bySection.get(sectionName) || [];
        const moveIndex = sectionRows.findIndex((entry) => {
          const text = `${entry?.title || ''} ${entry?.detail || ''} ${entry?.competitor || ''}`.toLowerCase();
          const socialHit = /香港|hong kong|民生|公屋|房屋|旅游|访港|就业|零售|医疗|教育|交通|统计处|census and statistics/.test(text);
          const financeNoise = /财报|业绩|营收|净利润|ebitda|资本开支|派息|dividend|earnings|results/.test(text);
          return socialHit && !financeNoise;
        });
        if (moveIndex < 0) continue;
        const [entry] = sectionRows.splice(moveIndex, 1);
        if (entry) {
          entry.section = '社会资讯';
          socialRows.push(entry);
        }
        if (socialRows.length) break;
      }
    }
  }

  for (const sectionName of WEEKLY_SECTION_ORDER) {
    const rows = bySection.get(sectionName) || [];
    if (!rows.length) continue;
    rows.sort((a, b) => {
      if (sectionName === '社会资讯') {
        const scoreA = Number(a?.socialPriority || 0);
        const scoreB = Number(b?.socialPriority || 0);
        if (scoreB !== scoreA) return scoreB - scoreA;
      }
      const tsA = Number(a?.eventTs || Date.parse(String(a?.eventAt || a?.publishedAt || '')) || 0);
      const tsB = Number(b?.eventTs || Date.parse(String(b?.eventAt || b?.publishedAt || '')) || 0);
      return tsB - tsA;
    });
  }

  const selected = [];
  for (const section of WEEKLY_SECTION_ORDER) {
    const rows = bySection.get(section) || [];
    if (rows.length) {
      selected.push(rows.shift());
    }
  }

  if (selected.length < maxItems) {
    let added = true;
    while (selected.length < maxItems && added) {
      added = false;
      for (const section of WEEKLY_SECTION_ORDER) {
        if (selected.length >= maxItems) break;
        const rows = bySection.get(section) || [];
        if (!rows.length) continue;
        if (countSectionItems(selected, section) >= getWeeklySectionCap(section)) continue;
        selected.push(rows.shift());
        added = true;
      }
    }
  }

  const minItems = Math.min(6, maxItems);
  if (selected.length < minItems) {
    const merged = WEEKLY_SECTION_ORDER.flatMap((section) => bySection.get(section) || []);
    for (const row of merged) {
      if (selected.length >= minItems) break;
      selected.push(row);
    }
  }

  return selected.slice(0, maxItems);
}

function buildWeeklyBulletin(sourceCatalog, range) {
  const selected = pickWeeklyEntries(sourceCatalog, range, WEEKLY_MAX_ITEMS);
  let globalIndex = 1;

  const sections = WEEKLY_SECTION_ORDER.map((sectionName) => {
    const rows = selected.filter((item) => item.section === sectionName);
    const items = rows.map((row, localIndex) => ({
      id: `W${globalIndex}`,
      index: globalIndex++,
      localIndex: localIndex + 1,
      tag: row.tag,
      title: row.title,
      detail: row.detail,
      sourceIds: row.sourceId ? [row.sourceId] : [],
      eventAt: row.eventAt || null,
      publishedAt: row.publishedAt || null,
      sourceUrl: row.sourceUrl || '',
      competitor: row.competitor || ''
    }));
    return {
      name: sectionName,
      narrative: buildWeeklySectionNarrative(sectionName, rows, range),
      items
    };
  });

  const toc = sections.flatMap((section) => section.items.map((item) => ({
    index: item.index,
    section: section.name,
    tag: item.tag,
    title: item.title
  })));

  return {
    templateVersion: 'weekly_fixed_v1',
    company: '中国移动香港公司',
    department: '中国移动香港公司战略部',
    generatedDate: formatShortDate(new Date().toISOString()),
    range: {
      start: range.start,
      end: range.end
    },
    toc,
    sections
  };
}

function toChineseOrder(value) {
  const n = Number(value || 0);
  const map = ['零', '一', '二', '三', '四', '五', '六', '七', '八', '九', '十'];
  if (n <= 10) return map[n] || String(n);
  if (n < 20) return `十${map[n - 10] || ''}`;
  if (n < 100) {
    const tens = Math.floor(n / 10);
    const ones = n % 10;
    return `${map[tens]}十${ones ? map[ones] : ''}`;
  }
  return String(n);
}

function weeklyBulletinToText(bulletin) {
  const lines = [];
  lines.push(bulletin.company || '中国移动香港公司');
  lines.push('');
  lines.push(`${bulletin.department || '中国移动香港公司战略部'}    ${bulletin.generatedDate || '-'}`);
  lines.push('');
  lines.push('目 录');
  lines.push('');

  for (const section of bulletin.sections || []) {
    const items = Array.isArray(section.items) ? section.items : [];
    lines.push(section.name);
    if (items.length) {
      for (const item of items) {
        lines.push(`${item.index}.【${item.tag}】${item.title}`);
      }
    } else {
      lines.push('（本期暂无更新）');
    }
    lines.push('');
  }

  for (const section of bulletin.sections || []) {
    const items = Array.isArray(section.items) ? section.items : [];
    lines.push(section.name);
    if (section.narrative) {
      lines.push(section.narrative);
    }
    if (!items.length) {
      lines.push('（本期暂无更新）');
      lines.push('');
      continue;
    }
    for (const item of items) {
      lines.push(`${toChineseOrder(item.localIndex)}、【${item.tag}】${item.title}`);
      lines.push(item.detail);
      lines.push(`事件时间：${formatDateTime(item.eventAt || item.publishedAt)}`);
      if (Array.isArray(item.sourceIds) && item.sourceIds.length) {
        lines.push(`来源：${item.sourceIds.join('、')}`);
      }
      lines.push('');
    }
  }

  return lines.join('\n');
}

function buildFallbackStructuredReport({ title, type, findings, range, sourceCatalog, windowDays }) {
  const competitorRows = buildDistribution(findings, 'competitor', 8);
  const categoryRows = buildDistribution(findings, 'category', 8);
  const trend = buildTrendSeries(findings, Math.min(14, windowDays));
  const periodText = `${formatShortDate(range.start)} 至 ${formatShortDate(range.end)}`;
  const total = findings.length || 1;
  const topCompetitor = competitorRows[0];
  const topCategory = categoryRows[0];
  const trendPeak = trend.values.length ? Math.max(...trend.values) : 0;

  const scoredSources = sourceCatalog
    .map((source) => ({
      ...source,
      quantFacts: extractWeeklyQuantFacts(source, 2),
      quantScore: weeklyQuantSignalScore(source)
    }))
    .sort((a, b) => b.quantScore - a.quantScore || findingTimestamp(b) - findingTimestamp(a));

  const keySources = scoredSources.slice(0, 12);
  const quantifiedCount = keySources.filter((item) => item.quantFacts.length > 0).length;
  const noQuantCount = Math.max(0, keySources.length - quantifiedCount);

  const competitorSummary = competitorRows
    .slice(0, 4)
    .map((item) => `${sanitizeFormalCell(item.label)} ${item.count}条（${toPercentText(item.count, total)}）`)
    .join('；');

  const categorySummary = categoryRows
    .slice(0, 4)
    .map((item) => `${sanitizeFormalCell(item.label)} ${item.count}条（${toPercentText(item.count, total)}）`)
    .join('；');

  const keyHighlights = keySources.slice(0, 6).map((source, index) => {
    const eventDate = formatShortDate(source.publishedAt || source.capturedAt || range.end);
    const competitor = sanitizeFormalCell(source.competitor || '相关主体');
    const category = sanitizeFormalCell(source.category || '相关类别');
    const quantified = source.quantFacts.length
      ? (sanitizeFormalParagraph(source.quantFacts.join(' '), {
        maxLength: 240,
        maxSentences: 3,
        preferNumeric: true
      }) || '原始来源未披露具体金额、用户规模或同比数据。')
      : '原始来源未披露具体金额、用户规模或同比数据。';
    return {
      title: `重点事项${index + 1}：${eventDate}${competitor}${category}动态`,
      insight: `${quantified}`,
      citations: [source.sourceId]
    };
  });

  const eventPoints = keySources.map((source) => {
    const eventDate = formatShortDate(source.publishedAt || source.capturedAt || range.end);
    const competitor = sanitizeFormalCell(source.competitor || '相关主体');
    const category = sanitizeFormalCell(source.category || '相关类别');
    const factText = buildFactPointFromSource(source, '原始来源未披露具体金额、用户规模或同比数据。');
    return {
      text: `${eventDate}，${competitor}在${category}领域披露信息：${factText}`,
      citations: [source.sourceId]
    };
  });

  const policyMacroSources = keySources
    .filter((source) => ['政策法规', '宏观数据'].includes(String(source.category || '').trim()))
    .slice(0, 6);

  const sections = [
    {
      title: '一、执行摘要与样本口径',
      analysis: [
        `报告统计窗口为 ${periodText}，纳入真实来源 ${findings.length} 条，覆盖竞对主体 ${competitorRows.length} 家、议题类别 ${categoryRows.length} 类。`,
        `样本中信息量最高的主体为 ${topCompetitor ? sanitizeFormalCell(topCompetitor.label) : '暂无'}，对应 ${topCompetitor ? topCompetitor.count : 0} 条，占比 ${topCompetitor ? toPercentText(topCompetitor.count, total) : '0%'}。`,
        `议题分布中占比最高类别为 ${topCategory ? sanitizeFormalCell(topCategory.label) : '暂无'}，对应 ${topCategory ? topCategory.count : 0} 条，占比 ${topCategory ? toPercentText(topCategory.count, total) : '0%'}。`,
        `近${Math.min(14, windowDays)}日单日最高披露量为 ${trendPeak} 条；重点来源中含量化数据 ${quantifiedCount} 条，未披露具体数值 ${noQuantCount} 条。`
      ].join(''),
      points: eventPoints.slice(0, 5)
    },
    {
      title: '二、关键经营数据与议题分布',
      analysis: [
        `竞对维度前四位分别为：${competitorSummary || '暂无数据'}。`,
        `议题维度前四位分别为：${categorySummary || '暂无数据'}。`,
        `以上统计均按来源条数计数，时间戳口径统一为来源发布时间优先、抓取时间为补充。`
      ].join(''),
      points: [
        ...competitorRows.slice(0, 6).map((row) => ({
          text: `${sanitizeFormalCell(row.label)}：${row.count}条，占比${toPercentText(row.count, total)}。`,
          citations: []
        })),
        ...categoryRows.slice(0, 6).map((row) => ({
          text: `${sanitizeFormalCell(row.label)}：${row.count}条，占比${toPercentText(row.count, total)}。`,
          citations: []
        }))
      ].slice(0, 10)
    },
    {
      title: '三、行业与竞对重点事件',
      analysis: [
        `本节按发布时间倒序列示窗口内高相关来源，逐条保留事件时间、主体、类别及量化信息。`,
        `对于原始来源未披露金额、用户规模或同比增幅的条目，统一标注“原始来源未披露具体数值”。`
      ].join(''),
      points: eventPoints.slice(0, 12)
    },
    {
      title: '四、政策与宏观影响',
      analysis: [
        `窗口内政策法规与宏观数据来源共 ${findings.filter((item) => ['政策法规', '宏观数据'].includes(String(item.category || '').trim())).length} 条。`,
        `本节仅列示可追溯来源，不附加延伸推断。`
      ].join(''),
      points: (policyMacroSources.length ? policyMacroSources : keySources.slice(0, 6)).map((source) => ({
        text: `${formatShortDate(source.publishedAt || source.capturedAt || range.end)}，${sanitizeFormalCell(source.competitor || '相关主体')}发布${sanitizeFormalCell(source.category || '相关类别')}信息：${buildFactPointFromSource(source, '原始来源未披露具体数值。')}`,
        citations: [source.sourceId]
      }))
    },
    {
      title: '五、风险提示',
      analysis: [
        `当前样本的主要风险来源于披露完整性差异，不同来源在金额、口径和时间粒度上存在不一致。`,
        `重点来源中未披露具体数值比例为 ${keySources.length ? toPercentText(noQuantCount, keySources.length) : '0%'}，该部分仅可用于事件确认，不用于横向量化比较。`,
        '统计口径已在数据表中明示，所有结论均以来源原文可复核字段为准。'
      ].join(''),
      points: [
        {
          text: `样本规模：${findings.length}条来源；量化条目：${quantifiedCount}条；未披露具体数值条目：${noQuantCount}条。`,
          citations: []
        },
        {
          text: `时间窗口：${periodText}；单日峰值：${trendPeak}条。`,
          citations: []
        }
      ]
    },
    {
      title: '六、免责声明',
      analysis: [
        '本报告仅基于公开来源整理，不构成任何投资建议或收益承诺。',
        '引用数据以来源原文为准，若来源后续修订，相关结论需按最新披露同步更新。',
        '本报告仅用于内部研判与管理决策支持，不得脱离原始来源单独传播。'
      ].join(''),
      points: []
    }
  ];

  const generatedDate = formatShortDate(new Date().toISOString());

  const trendRows = trend.labels.map((label, index) => [label, String(trend.values[index] || 0)]);
  const topSourceRows = keySources.slice(0, 12).map((item) => [
    item.sourceId,
    sanitizeFormalCell(item.competitor || '-'),
    sanitizeFormalCell(item.category || '-'),
    sanitizeFormalCell(item.title || item.summary || '-'),
    formatShortDate(item.publishedAt || item.capturedAt || range.end),
    item.quantFacts.length
      ? (sanitizeFormalParagraph(item.quantFacts.join(' '), {
        maxLength: 220,
        maxSentences: 3,
        preferNumeric: true
      }) || '原始来源未披露具体数值')
      : '原始来源未披露具体数值'
  ]);

  const tocRows = [
    ['一、执行摘要与样本口径', '窗口样本规模、主体分布、议题分布、量化覆盖'],
    ['二、关键经营数据与议题分布', '竞对/议题数量与占比对比'],
    ['三、行业与竞对重点事件', '按时间列示事件事实与量化信息'],
    ['四、政策与宏观影响', '政策与宏观来源事实'],
    ['五、风险提示', '样本完整性与量化可比性提示'],
    ['六、免责声明', '使用范围与责任边界']
  ];

  return {
    styleVersion: 'formal_v3',
    reportMeta: {
      department: '战略部（智库）',
      generatedAt: generatedDate,
      period: periodText,
      reportType: type
    },
    summary: [
      `报告周期：${periodText}。`,
      `纳入来源：${findings.length}条。`,
      `覆盖竞对：${competitorRows.length}家。`,
      `覆盖议题：${categoryRows.length}类。`,
      `重点来源量化覆盖：${quantifiedCount}条含明确数值，${noQuantCount}条未披露具体数值。`
    ].join(''),
    keyHighlights: keyHighlights.length
      ? keyHighlights
      : [{ title: '重点事项：样本更新', insight: '本期样本已更新，原始来源未披露具体数值。', citations: [] }],
    sections,
    dataTables: [
      {
        title: '目录',
        columns: ['章节', '内容'],
        rows: tocRows
      },
      {
        title: '核心监测指标汇总',
        columns: ['指标', '数值'],
        rows: [
          ['报告名称', title],
          ['报告周期', periodText],
          ['纳入来源', `${findings.length} 条`],
          ['覆盖竞对', `${competitorRows.length} 家`],
          ['覆盖类别', `${categoryRows.length} 类`]
        ]
      },
      {
        title: '竞对情报数量对比',
        columns: ['竞对', '情报条数', '占比'],
        rows: competitorRows.map((item) => [sanitizeFormalCell(item.label), String(item.count), toPercentText(item.count, findings.length)])
      },
      {
        title: '议题分布对比',
        columns: ['议题', '情报条数', '占比'],
        rows: categoryRows.map((item) => [sanitizeFormalCell(item.label), String(item.count), toPercentText(item.count, findings.length)])
      },
      {
        title: '时间分布（日频）',
        columns: ['日期', '情报条数'],
        rows: trendRows
      },
      {
        title: '重点来源清单（前12条）',
        columns: ['来源ID', '竞对', '类别', '标题', '发布时间', '量化事实'],
        rows: topSourceRows
      }
    ],
    charts: [
      {
        title: '近14天情报趋势',
        type: 'line',
        unit: '条',
        labels: trend.labels,
        values: trend.values
      },
      {
        title: '竞对情报分布',
        type: 'bar',
        unit: '条',
        labels: competitorRows.map((item) => sanitizeFormalCell(item.label)),
        values: competitorRows.map((item) => item.count)
      },
      {
        title: '议题分布',
        type: 'bar',
        unit: '条',
        labels: categoryRows.map((item) => item.label),
        values: categoryRows.map((item) => item.count)
      }
    ],
    recommendations: [
      {
        priority: '高',
        action: '按周固定复核重点来源中的量化字段',
        rationale: '重点来源中存在未披露具体数值条目，需要周度补齐口径后再做横向比较。'
      },
      {
        priority: '中',
        action: '建立竞对财务与资本开支跟踪表',
        rationale: '便于按统一口径对比营收、净利润、资本开支与用户规模。'
      },
      {
        priority: '中',
        action: '将政策与宏观条目单列并独立编号',
        rationale: '可降低混合口径对竞对经营判断的干扰。'
      },
      {
        priority: '低',
        action: '固化趋势图与对比表导出模板',
        rationale: '可直接用于周例会与月度复盘场景。'
      }
    ],
    tracking: [
      '持续跟踪重点竞对下一次财报与经营指引更新时间。',
      '持续跟踪香港本地竞对在企业市场与5G业务发布节奏。'
    ],
    sourceRefs: sourceCatalog.map((item) => ({
      sourceId: item.sourceId,
      findingId: item.id,
      note: sanitizeFormalCell(item.title || item.summary || '')
    })),
    generatedBy: 'fallback',
    reportTitle: title
  };
}

function sanitizePoint(point, allowedSourceIds) {
  if (typeof point === 'string') {
    const text = sanitizeFormalParagraph(point.replace(/\[\s*S\d+\s*\]/gi, '').trim(), {
      maxLength: 620,
      maxSentences: 3,
      preferNumeric: true
    });
    const citations = extractSourceIdsFromText(point).filter((id) => allowedSourceIds.has(id));
    if (!text) return null;
    return { text, citations };
  }

  if (!point || typeof point !== 'object') return null;

  const baseText = String(point.text || point.content || '').trim();
  const fromText = extractSourceIdsFromText(baseText);
  const fromField = Array.isArray(point.citations)
    ? point.citations.map(normalizeSourceId).filter(Boolean)
    : [];

  const citations = uniqueList([...fromField, ...fromText]).filter((id) => allowedSourceIds.has(id));
  const text = sanitizeFormalParagraph(baseText.replace(/\[\s*S\d+\s*\]/gi, '').trim(), {
    maxLength: 620,
    maxSentences: 3,
    preferNumeric: true
  });

  if (!text) return null;
  return { text, citations };
}

function sanitizeDataTables(rawTables, fallbackTables) {
  const normalized = Array.isArray(rawTables)
    ? rawTables
      .map((table) => {
        if (!table || typeof table !== 'object') return null;
        const title = sanitizeFormalTitle(table.title, '数据表');
        const columns = Array.isArray(table.columns)
          ? table.columns.map((item, index) => sanitizeFormalTitle(item, `字段${index + 1}`)).filter(Boolean).slice(0, 8)
          : [];

        if (!title || columns.length < 2) return null;

        const rows = Array.isArray(table.rows)
          ? table.rows
            .map((row) => {
              if (!Array.isArray(row)) return null;
              const cells = row.slice(0, columns.length).map((cell) => sanitizeFormalCell(cell));
              while (cells.length < columns.length) {
                cells.push('-');
              }
              return cells;
            })
            .filter(Boolean)
            .slice(0, 50)
          : [];

        if (!rows.length) return null;

        return {
          title,
          columns,
          rows,
          note: sanitizeFormalParagraph(table.note, {
            maxLength: 140,
            maxSentences: 2
          })
        };
      })
      .filter(Boolean)
      .slice(0, 6)
    : [];

  if (!normalized.length) {
    return fallbackTables;
  }

  const merged = [...normalized];
  const existing = new Set(merged.map((item) => item.title));
  for (const fallback of fallbackTables || []) {
    if (!fallback || existing.has(fallback.title)) continue;
    merged.push(fallback);
    existing.add(fallback.title);
    if (merged.length >= 5) break;
  }

  return merged;
}

function sanitizeCharts(rawCharts, fallbackCharts) {
  const normalized = Array.isArray(rawCharts)
    ? rawCharts
      .map((chart) => {
        if (!chart || typeof chart !== 'object') return null;
        const title = sanitizeFormalTitle(chart.title, '图表');
        const type = String(chart.type || 'bar').toLowerCase();
        const safeType = type === 'line' ? 'line' : 'bar';
        const unit = sanitizeFormalCell(chart.unit || '条') || '条';

        const labels = Array.isArray(chart.labels)
          ? chart.labels.map((item) => sanitizeFormalCell(item)).filter(Boolean).slice(0, 24)
          : [];

        const valuesRaw = Array.isArray(chart.values) ? chart.values.slice(0, labels.length) : [];
        const values = valuesRaw
          .map((item) => Number(item))
          .map((item) => (Number.isFinite(item) ? Number(item.toFixed(2)) : null));

        if (!title || labels.length < 2 || values.length !== labels.length || values.some((item) => item === null)) {
          return null;
        }

        return {
          title,
          type: safeType,
          unit,
          labels,
          values
        };
      })
      .filter(Boolean)
      .slice(0, 4)
    : [];

  if (!normalized.length) {
    return fallbackCharts;
  }

  const merged = [...normalized];
  const existing = new Set(merged.map((item) => item.title));
  for (const fallback of fallbackCharts || []) {
    if (!fallback || existing.has(fallback.title)) continue;
    merged.push(fallback);
    existing.add(fallback.title);
    if (merged.length >= 3) break;
  }

  return merged;
}

function sanitizeStructuredReport(raw, findings, sourceCatalog, fallback) {
  if (!raw || typeof raw !== 'object') {
    return fallback;
  }

  const findingMap = new Map(findings.map((item) => [item.id, item]));
  const sourceIdByFindingId = new Map(sourceCatalog.map((item) => [item.id, item.sourceId]));
  const allowedSourceIds = new Set(sourceCatalog.map((item) => item.sourceId));

  const summaryRaw = sanitizeFormalParagraph(raw.summary, {
    maxLength: 1200,
    minLength: 100,
    maxSentences: 8,
    preferNumeric: true
  });
  const summaryFallback = sanitizeFormalParagraph(fallback.summary, {
    maxLength: 1200,
    maxSentences: 8,
    preferNumeric: true
  });
  const summary = summaryRaw || summaryFallback || fallback.summary;

  const keyHighlights = Array.isArray(raw.keyHighlights)
    ? raw.keyHighlights
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const title = sanitizeFormalTitle(item.title, '重点事项');
        const insight = sanitizeFormalParagraph(item.insight || item.summary || item.text, {
          maxLength: 260,
          maxSentences: 3,
          preferNumeric: true
        });
        const citations = uniqueList([
          ...(Array.isArray(item.citations) ? item.citations.map(normalizeSourceId).filter(Boolean) : []),
          ...extractSourceIdsFromText(insight)
        ]).filter((id) => allowedSourceIds.has(id));

        if (!title || !insight) return null;
        return { title, insight, citations };
      })
      .filter(Boolean)
      .slice(0, 8)
    : [];

  const sections = Array.isArray(raw.sections)
    ? raw.sections
      .map((section) => {
        if (!section || typeof section !== 'object') return null;
        const title = sanitizeFormalTitle(section.title, '未命名章节');
        const analysis = sanitizeFormalParagraph(section.analysis || section.narrative || section.intro || '', {
          maxLength: 1600,
          maxSentences: 8,
          preferNumeric: true
        });
        const points = Array.isArray(section.points)
          ? section.points
            .map((point) => sanitizePoint(point, allowedSourceIds))
            .filter(Boolean)
            .slice(0, 16)
          : [];

        if (!title || (!analysis && !points.length)) return null;
        return { title, analysis, points };
      })
      .filter(Boolean)
      .slice(0, 10)
    : [];

  const mergedSections = sections.length ? [...sections] : [];
  const sectionTitleSet = new Set(mergedSections.map((item) => item.title));
  for (const fallbackSection of fallback.sections || []) {
    if (!fallbackSection || sectionTitleSet.has(fallbackSection.title)) continue;
    if (mergedSections.length >= 8) break;
    mergedSections.push(fallbackSection);
    sectionTitleSet.add(fallbackSection.title);
  }

  const recommendations = Array.isArray(raw.recommendations)
    ? raw.recommendations
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const action = sanitizeFormalParagraph(item.action, {
          maxLength: 180,
          maxSentences: 1
        }).replace(/[。！？!?；;]+$/g, '');
        const rationale = sanitizeFormalParagraph(item.rationale, {
          maxLength: 220,
          maxSentences: 2,
          preferNumeric: true
        });
        if (!action || !rationale) return null;
        const priorityRaw = normalizeText(item.priority, 10);
        const priority = ['高', '中', '低'].includes(priorityRaw) ? priorityRaw : '中';
        return { priority, action, rationale };
      })
      .filter(Boolean)
      .slice(0, 10)
    : [];

  const mergedRecommendations = recommendations.length ? [...recommendations] : [];
  const recommendationSet = new Set(mergedRecommendations.map((item) => item.action));
  for (const fallbackRow of fallback.recommendations || []) {
    if (!fallbackRow || recommendationSet.has(fallbackRow.action)) continue;
    if (mergedRecommendations.length >= 4) break;
    mergedRecommendations.push(fallbackRow);
    recommendationSet.add(fallbackRow.action);
  }

  const tracking = Array.isArray(raw.tracking)
    ? raw.tracking
      .map((item) => sanitizeFormalParagraph(item, {
        maxLength: 160,
        maxSentences: 1
      }).replace(/[。！？!?；;]+$/g, ''))
      .filter(Boolean)
      .slice(0, 12)
    : [];

  const sourceRefs = Array.isArray(raw.sourceRefs)
    ? raw.sourceRefs
      .map((item) => {
        if (!item || typeof item !== 'object') return null;
        const findingId = String(item.findingId || '').trim();
        if (!findingMap.has(findingId)) return null;

        const fallbackSourceId = sourceIdByFindingId.get(findingId);
        const sourceId = normalizeSourceId(item.sourceId) || fallbackSourceId;
        if (!sourceId || !allowedSourceIds.has(sourceId)) return null;

        return {
          sourceId,
          findingId,
          note: sanitizeFormalParagraph(item.note, {
            maxLength: 140,
            maxSentences: 2,
            preferNumeric: true
          })
        };
      })
      .filter(Boolean)
      .slice(0, 50)
    : [];

  const finalizedSourceRefs = sourceRefs.length
    ? sourceRefs
    : fallback.sourceRefs;

  const fallbackMeta = fallback.reportMeta || {};
  const rawMeta = raw.reportMeta && typeof raw.reportMeta === 'object' ? raw.reportMeta : {};

  return {
    styleVersion: 'formal_v3',
    reportMeta: {
      department: normalizeText(rawMeta.department, 60) || fallbackMeta.department,
      generatedAt: normalizeText(rawMeta.generatedAt, 30) || fallbackMeta.generatedAt,
      period: normalizeText(rawMeta.period, 40) || fallbackMeta.period,
      reportType: normalizeText(rawMeta.reportType, 30) || fallbackMeta.reportType
    },
    summary,
    keyHighlights: keyHighlights.length ? keyHighlights : fallback.keyHighlights,
    sections: mergedSections.length ? mergedSections : fallback.sections,
    dataTables: sanitizeDataTables(raw.dataTables, fallback.dataTables),
    charts: sanitizeCharts(raw.charts, fallback.charts),
    recommendations: mergedRecommendations.length ? mergedRecommendations : fallback.recommendations,
    tracking: tracking.length ? tracking : fallback.tracking,
    sourceRefs: finalizedSourceRefs,
    generatedBy: 'model'
  };
}

function renderPointToText(point) {
  if (!point) return '';
  if (typeof point === 'string') return point;
  const text = normalizeText(point.text, 240);
  const citations = Array.isArray(point.citations)
    ? point.citations.map(normalizeSourceId).filter(Boolean)
    : [];

  return citations.length ? `${text} ${citations.map((id) => `[${id}]`).join('')}` : text;
}

function structuredToText(title, structured, findings) {
  if (structured?.weeklyBulletin && typeof structured.weeklyBulletin === 'object') {
    return weeklyBulletinToText(structured.weeklyBulletin);
  }

  const findingMap = new Map(findings.map((item) => [item.id, item]));
  const lines = [];

  lines.push(title);
  lines.push('');

  if (structured.reportMeta) {
    lines.push(`部门：${structured.reportMeta.department || '-'}`);
    lines.push(`报告周期：${structured.reportMeta.period || '-'}`);
    lines.push(`生成日期：${structured.reportMeta.generatedAt || '-'}`);
    lines.push('');
  }

  lines.push(`执行摘要：${structured.summary || '-'}`);
  lines.push('');

  if (Array.isArray(structured.keyHighlights) && structured.keyHighlights.length) {
    lines.push('关键重点');
    for (const item of structured.keyHighlights) {
      const citations = Array.isArray(item.citations) && item.citations.length
        ? ` ${item.citations.map((id) => `[${id}]`).join('')}`
        : '';
      lines.push(`- ${item.title}：${item.insight}${citations}`);
    }
    lines.push('');
  }

  for (const section of structured.sections || []) {
    lines.push(section.title);
    if (section.analysis) {
      lines.push(section.analysis);
    }
    for (const point of section.points || []) {
      lines.push(`- ${renderPointToText(point)}`);
    }
    lines.push('');
  }

  for (const table of structured.dataTables || []) {
    lines.push(table.title);
    lines.push(`- 列：${(table.columns || []).join(' | ')}`);
    for (const row of table.rows || []) {
      lines.push(`- ${row.join(' | ')}`);
    }
    lines.push('');
  }

  for (const chart of structured.charts || []) {
    const labels = Array.isArray(chart.labels) ? chart.labels.join('、') : '';
    const values = Array.isArray(chart.values) ? chart.values.join('、') : '';
    lines.push(`${chart.title || '图表'}`);
    lines.push(`- 类型：${chart.type || 'bar'} | 单位：${chart.unit || '条'}`);
    lines.push(`- 维度：${labels}`);
    lines.push(`- 数值：${values}`);
    lines.push('');
  }

  lines.push('建议动作');
  for (const item of structured.recommendations || []) {
    lines.push(`- [${item.priority}] ${item.action}（依据：${item.rationale}）`);
  }
  lines.push('');

  lines.push('持续跟踪');
  for (const item of structured.tracking || []) {
    lines.push(`- ${item}`);
  }
  lines.push('');

  lines.push('来源清单');
  for (const ref of structured.sourceRefs || []) {
    const finding = findingMap.get(ref.findingId);
    if (!finding) continue;
    const sourceTitle = sanitizeFormalCell(finding.title || finding.summary || '来源条目');
    lines.push(`- [${ref.sourceId || '-'}] ${sourceTitle} | ${finding.sourceUrl}`);
  }

  return lines.join('\n');
}

async function generateReport({ type, title, sectionInstruction, windowDays, maxFindings }) {
  const db = readDb();
  if (!db.findings.length) {
    throw new Error('当前没有可用于生成报告的真实情报。请先执行扫描。');
  }

  const range = getWindowRange(windowDays);
  const windowFindings = pickFindingsByWindow(db.findings, range.start, range.end, Math.max(maxFindings * 2, 80));
  const freshnessFilteredFindings = windowFindings.filter((item) => (
    !isOutdatedFinanceFinding(item, range.end)
    && !isOutdatedByYearHint(item, range.end)
  ));
  const staleDropped = Math.max(0, windowFindings.length - freshnessFilteredFindings.length);
  const relevanceSelection = selectRelevantFindings(freshnessFilteredFindings, {
    reportType: type,
    maxFindings
  });
  const findings = relevanceSelection.findings;

  if (!findings.length) {
    throw new Error('当前时间窗口内未找到可用于生成报告的高相关来源。请优化检索语句后重试。');
  }

  const sourceCatalogLimit = type === 'weekly' ? 80 : 40;
  const sourceCatalog = buildSourceCatalog(findings, sourceCatalogLimit);

  addJob({
    type: 'report',
    status: 'started',
    message: `开始生成${title}，窗口来源 ${relevanceSelection.stats.totalWindowFindings} 条，高相关入选 ${findings.length} 条，过滤 ${relevanceSelection.stats.droppedCount} 条，过旧年份剔除 ${staleDropped} 条。`
  });

  if (findings.length < Math.min(8, maxFindings)) {
    addJob({
      type: 'report',
      status: 'warning',
      message: `${title}高相关来源数量偏少（${findings.length}条），报告已按真实证据生成并附保守判断。`
    });
  }

  const prompt = [
    {
      role: 'system',
      content: [
        '你是CMHK战略研究部负责人助理。',
        `请基于真实来源生成正式、端庄、可直接提交决策层审阅的《${title}》。`,
        '你在撰写行业研究报告，不是新闻摘抄。先结论后论据，禁止空话。',
        '禁止编造。任何事实、数字与判断必须可追溯到输入来源。',
        '对证据不足的结论必须明确标注“证据不足”并说明缺口，不得硬性推断。',
        '引用规则：文内引用使用 sourceId（例如 [S1]、[S2]），且 sourceId 必须来自输入 sources。',
        '全文必须为中文。英文专有名词需转换为中文（必要时可在括号保留缩写）。',
        '正文语气必须客观事实化，禁止使用“文章/文件/文中/本文/报道 + 讨论/指出/分析/显示”句式。',
        '所有章节优先保留带时间、金额、同比、用户规模、资本开支等量化信息；来源未披露数值时，写“原始来源未披露具体数值”。',
        '必须采用标准研报结构：封面信息、目录、执行摘要、关键数据表、正文分章、风险提示、行动建议、来源清单与免责声明。',
        '输出必须是 JSON 对象，不得输出 Markdown，不得输出额外解释。',
        'JSON schema:',
        '{',
        '  reportMeta:{department:string, generatedAt:string, period:string, reportType:string},',
        '  summary:string,',
        '  keyHighlights:[{title:string, insight:string, citations:string[]}],',
        '  sections:[{title:string, analysis:string, points:[{text:string, citations:string[]}]}],',
        '  dataTables:[{title:string, columns:string[], rows:string[][], note?:string}],',
        '  charts:[{title:string, type:"line|bar", unit:string, labels:string[], values:number[]}],',
        '  recommendations:[{priority:"高|中|低", action:string, rationale:string}],',
        '  tracking:string[],',
        '  sourceRefs:[{sourceId:string, findingId:string, note:string}]',
        '}',
        '写作要求：按行研风格组织内容，必须包含“执行摘要、关键经营数据与财务对比、行业与竞对动态、政策与宏观影响、风险提示、行动建议”。',
        'sections.analysis 必须为正式完整段落，每节不少于160字，且至少包含一个时间或数值事实。',
        'dataTables至少4个（必须含目录表、对比表、时间序列表）；charts至少2个。',
        '禁止出现泛化描述、主观修辞或空泛结论。',
        sectionInstruction
      ].join(' ')
    },
    {
      role: 'user',
      content: JSON.stringify({
        reportType: type,
        reportTitle: title,
        range,
        totalSources: findings.length,
        sourceSelection: {
          ...relevanceSelection.stats,
          staleDropped
        },
        sources: buildSourcePack(sourceCatalog)
      })
    }
  ];

  let rawContent = null;
  try {
    rawContent = await deepseekChat(prompt, 0.15, { timeoutMs: REPORT_TIMEOUT_MS });
  } catch (error) {
    addJob({
      type: 'report',
      status: 'warning',
      message: `${title}模型生成失败，已回退为规则化报告：${error.message}`
    });
  }
  const fallbackStructured = buildFallbackStructuredReport({
    title,
    type,
    findings,
    range,
    sourceCatalog,
    windowDays
  });

  const parsed = parseJsonPayload(rawContent || '');
  const structured = sanitizeStructuredReport(parsed, findings, sourceCatalog, fallbackStructured);

  if (type === 'weekly') {
    structured.weeklyBulletin = buildWeeklyBulletin(sourceCatalog, range);
  }

  const content = structuredToText(title, structured, findings);

  const sourceIdMap = new Map(sourceCatalog.map((item) => [item.id, item.sourceId]));

  const report = addReport({
    type,
    title,
    format: 'structured_v2',
    content,
    structured,
    sourceSnapshot: findings.map((item) => ({
      sourceId: sourceIdMap.get(item.id) || null,
      findingId: item.id,
      title: item.title,
      competitor: item.competitor,
      category: item.category,
      sourceUrl: item.sourceUrl,
      publishedAt: item.publishedAt || item.capturedAt || item.createdAt
    })),
    sourceCount: findings.length,
    rangeStart: range.start,
    rangeEnd: range.end,
    sourceFindingIds: findings.map((item) => item.id)
  });

  addJob({
    type: 'report',
    status: 'success',
    message: `${title}生成完成，引用 ${findings.length} 条高相关来源。`
  });

  return report;
}

async function generateWeeklyReport() {
  return generateReport({
    type: 'weekly',
    title: '竞对动态周报',
    sectionInstruction:
      '报告结构应突出竞对近期动作、对CMHK影响与建议动作，重点覆盖财报、产品发布会、中标公示、高管言论；行文要正式、完整、可直接送审，避免口语化。数据表需包含可量化对比。必须基于近7天完整窗口做周度汇总，不得按单日口径叙述。',
    windowDays: 7,
    maxFindings: 120
  });
}

async function generateTrendReport() {
  return generateReport({
    type: 'trend',
    title: '行业趋势研判报告',
    sectionInstruction:
      '按标准研报体例输出：封面信息、目录、执行摘要、关键经营数据与财务对比、行业与竞对动态、政策与宏观影响、风险提示、行动建议、来源清单、免责声明。所有段落必须使用客观事实句，禁止“文章/文件/文中指出”句式；每节至少给出一条带时间和数值的事实，无法量化时明确写“原始来源未披露具体数值”。',
    windowDays: 30,
    maxFindings: 70
  });
}

function resolveReportFindings(db, report) {
  const findingMap = new Map((db.findings || []).map((item) => [item.id, item]));
  const resolved = [];
  const seen = new Set();

  const sourceIds = Array.isArray(report.sourceFindingIds) ? report.sourceFindingIds : [];
  for (const findingId of sourceIds) {
    const key = String(findingId || '').trim();
    if (!key || seen.has(key)) continue;
    const finding = findingMap.get(key);
    if (!finding) continue;
    resolved.push(finding);
    seen.add(key);
  }

  if (resolved.length >= 6) {
    return resolved;
  }

  const snapshotRows = Array.isArray(report.sourceSnapshot) ? report.sourceSnapshot : [];
  for (const row of snapshotRows) {
    const key = String(row?.findingId || '').trim() || `snapshot_${resolved.length + 1}`;
    if (seen.has(key)) continue;

    resolved.push({
      id: key,
      competitor: row?.competitor || '',
      category: row?.category || '',
      title: row?.title || row?.note || '来源摘要',
      summary: row?.note || row?.title || '',
      significance: '',
      sourceUrl: row?.sourceUrl || '',
      publishedAt: row?.publishedAt || report.rangeEnd || report.createdAt,
      capturedAt: report.createdAt || new Date().toISOString()
    });
    seen.add(key);
  }

  if (resolved.length) {
    return resolved;
  }

  return (db.findings || []).slice(0, 30);
}

function inferWindowDays(report) {
  const startMs = Date.parse(report.rangeStart || '');
  const endMs = Date.parse(report.rangeEnd || '');
  if (Number.isNaN(startMs) || Number.isNaN(endMs) || endMs <= startMs) {
    return report.type === 'trend' ? 30 : 7;
  }

  const days = Math.max(1, Math.round((endMs - startMs) / (24 * 60 * 60 * 1000)));
  return Math.min(90, Math.max(7, days));
}

function upgradeSingleReportToFormal(db, report) {
  const findings = resolveReportFindings(db, report);
  if (!Array.isArray(findings) || !findings.length) {
    return null;
  }

  const sourceCatalog = buildSourceCatalog(findings, report.type === 'weekly' ? 80 : 40);
  const range = {
    start: report.rangeStart || getWindowRange(inferWindowDays(report)).start,
    end: report.rangeEnd || report.createdAt || new Date().toISOString()
  };
  const fallback = buildFallbackStructuredReport({
    title: report.title || '报告',
    type: report.type || 'weekly',
    findings,
    range,
    sourceCatalog,
    windowDays: inferWindowDays(report)
  });

  const parsed = (report.structured && typeof report.structured === 'object')
    ? report.structured
    : parseJsonPayload(report.content || '');
  const structured = sanitizeStructuredReport(parsed, findings, sourceCatalog, fallback);

  if (report.type === 'weekly') {
    structured.weeklyBulletin = buildWeeklyBulletin(sourceCatalog, range);
  }

  const content = structuredToText(report.title || '报告', structured, findings);

  const sourceIdMap = new Map(sourceCatalog.map((item) => [item.id, item.sourceId]));
  const normalizedSnapshot = findings.map((item) => ({
    sourceId: sourceIdMap.get(item.id) || null,
    findingId: item.id,
    title: item.title,
    competitor: item.competitor,
    category: item.category,
    sourceUrl: item.sourceUrl,
    publishedAt: item.publishedAt || item.capturedAt || report.createdAt
  }));

  return {
    ...report,
    format: 'structured_v2',
    structured,
    content,
    sourceSnapshot: normalizedSnapshot,
    sourceCount: normalizedSnapshot.length,
    sourceFindingIds: normalizedSnapshot.map((item) => item.findingId),
    rangeStart: range.start,
    rangeEnd: range.end
  };
}

function regenerateReportsToFormal() {
  const db = readDb();
  const reports = Array.isArray(db.reports) ? db.reports : [];
  const next = [];
  let updated = 0;
  let skipped = 0;

  for (const report of reports) {
    const weeklySections = Array.isArray(report?.structured?.weeklyBulletin?.sections)
      ? report.structured.weeklyBulletin.sections
      : [];
    const weeklyDetails = weeklySections.flatMap((section) => Array.isArray(section?.items) ? section.items : []);
    const weeklyNarratives = weeklySections.map((section) => String(section?.narrative || ''));
    const needsWeeklyCleanup = Boolean(
      report?.type === 'weekly'
      && (
        weeklyDetails.some((item) => (
          /(文章讨论|文章分析|文中指出|文件标题为|摘要说明|输入内容为|件表明|可能|建议|推测)/.test(String(item?.detail || ''))
          || /[A-Za-z]{3,}/.test(String(item?.title || ''))
          || /[A-Za-z]{3,}/.test(String(item?.detail || ''))
          || WEEKLY_INTERPRETIVE_REGEX.test(String(item?.title || ''))
          || WEEKLY_INTERPRETIVE_REGEX.test(String(item?.detail || ''))
          || !/^[\u4e00-\u9fff《「（(]/.test(String(item?.title || '').trim())
        ))
        || weeklyNarratives.some((line) => /[A-Za-z]{3,}/.test(line) || WEEKLY_INTERPRETIVE_REGEX.test(line))
      )
    );
    const weeklyItemCount = weeklySections.reduce((sum, section) => {
      if (!Array.isArray(section?.items)) return sum;
      return sum + section.items.length;
    }, 0);
    const hasWeeklyTemplate = report?.type !== 'weekly'
      || (weeklySections.length > 0
        && weeklySections.every((section) => typeof section?.narrative === 'string' && section.narrative.trim().length > 0)
        && weeklyItemCount <= WEEKLY_MAX_ITEMS);
    const structured = report?.structured && typeof report.structured === 'object' ? report.structured : {};
    const sectionTexts = Array.isArray(structured.sections)
      ? structured.sections.flatMap((section) => {
        const points = Array.isArray(section?.points) ? section.points : [];
        return [
          String(section?.title || ''),
          String(section?.analysis || ''),
          ...points.map((point) => String(point?.text || point || ''))
        ];
      })
      : [];
    const highlightTexts = Array.isArray(structured.keyHighlights)
      ? structured.keyHighlights.flatMap((item) => [String(item?.title || ''), String(item?.insight || '')])
      : [];
    const extraTexts = [
      String(structured.summary || ''),
      ...sectionTexts,
      ...highlightTexts
    ];
    const needsFormalLanguageCleanup = extraTexts.some((text) => (
      FORMAL_NOISE_REGEX.test(text)
      || /(文章|该文章|该文|本文|文中|报道|该报道|文件|该文件|原文)/.test(text)
      || /[A-Za-z]{4,}/.test(text)
    ));
    const isFormal = report?.format === 'structured_v2'
      && ['formal_v2', 'formal_v3'].includes(String(report?.structured?.styleVersion || ''))
      && hasWeeklyTemplate
      && !needsWeeklyCleanup
      && !needsFormalLanguageCleanup;
    if (isFormal) {
      next.push(report);
      skipped += 1;
      continue;
    }

    const upgraded = upgradeSingleReportToFormal(db, report);
    if (!upgraded) {
      next.push(report);
      skipped += 1;
      continue;
    }

    next.push(upgraded);
    updated += 1;
  }

  db.reports = next;
  writeDb(db);

  addJob({
    type: 'report_upgrade',
    status: 'success',
    message: `历史报告正式化升级完成：更新 ${updated} 份，跳过 ${skipped} 份。`
  });

  return {
    total: reports.length,
    updated,
    skipped
  };
}

function normalizeQaList(list, maxItems = 6, maxLength = 240) {
  if (!Array.isArray(list)) return [];
  return list
    .map((item) => normalizeText(item, maxLength))
    .filter(Boolean)
    .slice(0, maxItems);
}

function getReportSourceIdSet(report) {
  const set = new Set();
  const rows = Array.isArray(report?.sourceSnapshot) ? report.sourceSnapshot : [];
  for (const row of rows) {
    const sourceId = normalizeSourceId(row?.sourceId);
    if (sourceId) set.add(sourceId);
  }
  return set;
}

function normalizeReportStructured(report) {
  if (report?.structured && typeof report.structured === 'object') {
    return report.structured;
  }
  return parseJsonPayload(report?.content || '');
}

function buildReportQaContext(report) {
  const structured = normalizeReportStructured(report) || {};
  const sectionRows = Array.isArray(structured.sections)
    ? structured.sections.slice(0, 10).map((section) => ({
      title: normalizeText(section?.title, 80),
      analysis: normalizeText(section?.analysis, 1200),
      points: Array.isArray(section?.points)
        ? section.points.slice(0, 18).map((point) => {
          const normalized = sanitizePoint(point, getReportSourceIdSet(report));
          return normalized || null;
        }).filter(Boolean)
        : []
    }))
    : [];

  const sourceRows = Array.isArray(report?.sourceSnapshot)
    ? report.sourceSnapshot.slice(0, 60).map((row) => ({
      sourceId: normalizeSourceId(row?.sourceId),
      findingId: row?.findingId || '',
      competitor: normalizeText(row?.competitor, 60),
      category: normalizeText(row?.category, 40),
      title: normalizeText(row?.title, 200),
      publishedAt: row?.publishedAt || '',
      sourceUrl: row?.sourceUrl || ''
    }))
    : [];

  const qaHistory = Array.isArray(report?.qaHistory)
    ? report.qaHistory.slice(0, 8).map((row) => ({
      question: normalizeText(row?.question, 220),
      answer: normalizeText(row?.answer, 320),
      citations: normalizeQaList(row?.citations, 8, 8)
    }))
    : [];

  return {
    reportMeta: {
      id: report.id,
      title: report.title,
      type: report.type,
      createdAt: report.createdAt,
      rangeStart: report.rangeStart,
      rangeEnd: report.rangeEnd
    },
    summary: normalizeText(structured.summary, 1400),
    keyHighlights: normalizeQaList((structured.keyHighlights || []).map((item) => `${item.title}：${item.insight}`), 8, 260),
    sections: sectionRows,
    recommendations: normalizeQaList((structured.recommendations || []).map((item) => `${item.priority || '中'}优先级｜${item.action}｜依据：${item.rationale}`), 10, 260),
    tracking: normalizeQaList(structured.tracking, 10, 180),
    sources: sourceRows,
    previousQa: qaHistory
  };
}

function splitQuestionKeywords(question) {
  const tokens = String(question || '')
    .split(/[\s,，。；;：:、|/\\()（）【】\[\]\-]+/)
    .map((item) => item.trim())
    .filter((item) => item.length >= 2);
  return uniqueList(tokens).slice(0, 12);
}

function buildFallbackQaAnswer(report, question) {
  const structured = normalizeReportStructured(report) || {};
  const allowedSourceIds = getReportSourceIdSet(report);
  const keywords = splitQuestionKeywords(question);

  const candidates = [];
  if (structured.summary) {
    candidates.push({ text: normalizeText(structured.summary, 500), citations: [] });
  }

  for (const section of structured.sections || []) {
    if (section?.analysis) {
      candidates.push({
        text: `${normalizeText(section.title, 80)}：${normalizeText(section.analysis, 700)}`,
        citations: []
      });
    }

    for (const point of section.points || []) {
      const normalized = sanitizePoint(point, allowedSourceIds);
      if (normalized?.text) {
        candidates.push(normalized);
      }
    }
  }

  const scored = candidates
    .map((row) => {
      const haystack = String(row.text || '').toLowerCase();
      const score = keywords.reduce((sum, token) => {
        return sum + (haystack.includes(token.toLowerCase()) ? 1 : 0);
      }, 0);
      return { ...row, score };
    })
    .sort((a, b) => b.score - a.score);

  const picked = scored.filter((item) => item.score > 0).slice(0, 3);
  const finalRows = picked.length ? picked : scored.slice(0, 3);

  const citations = uniqueList(finalRows.flatMap((item) => item.citations || [])).slice(0, 8);
  const answer = finalRows.length
    ? `根据当前报告已归档证据，针对“${normalizeText(question, 120)}”，可归纳为：${finalRows.map((item) => item.text).join('；')}`
    : `当前报告中未检索到可直接支撑“${normalizeText(question, 120)}”的明确证据，建议补充检索后再判读。`;

  return {
    answer,
    keyPoints: finalRows.map((item) => item.text).slice(0, 4),
    citations,
    confidence: finalRows.length ? '中' : '低',
    followups: finalRows.length
      ? ['是否需要按竞对拆分影响结论？', '是否需要补充最近7天新增来源后再回答？']
      : ['是否需要扩大检索范围到政策与宏观数据来源？']
  };
}

function sanitizeQaResponse(raw, fallback, report) {
  const allowedSourceIds = getReportSourceIdSet(report);
  if (!raw || typeof raw !== 'object') {
    return fallback;
  }

  const answerText = normalizeText(raw.answer, 2200) || fallback.answer;
  const keyPoints = normalizeQaList(raw.keyPoints, 8, 320);
  const followups = normalizeQaList(raw.followups, 5, 140);
  const confidenceRaw = normalizeText(raw.confidence, 4);
  const confidence = ['高', '中', '低'].includes(confidenceRaw) ? confidenceRaw : fallback.confidence;
  const citations = uniqueList([
    ...(Array.isArray(raw.citations) ? raw.citations.map(normalizeSourceId).filter(Boolean) : []),
    ...extractSourceIdsFromText(answerText)
  ]).filter((id) => allowedSourceIds.has(id)).slice(0, 10);

  return {
    answer: answerText,
    keyPoints: keyPoints.length ? keyPoints : fallback.keyPoints,
    citations: citations.length ? citations : fallback.citations,
    confidence,
    followups: followups.length ? followups : fallback.followups
  };
}

function deriveKeyPointsFromAnswer(answerText) {
  const rows = String(answerText || '')
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean);

  const bullets = rows
    .filter((item) => /^([\-*•]|\d+[.)、])\s*/.test(item))
    .map((item) => item.replace(/^([\-*•]|\d+[.)、])\s*/, ''))
    .map((item) => normalizeText(item, 220))
    .filter(Boolean)
    .slice(0, 6);

  if (bullets.length) {
    return bullets;
  }

  return String(answerText || '')
    .split(/[。；;!?！？]/)
    .map((item) => normalizeText(item.trim(), 220))
    .filter(Boolean)
    .slice(0, 5);
}

function sanitizeQaFromStreamText(answerText, fallback, report) {
  const safeAnswer = normalizeText(answerText, 2800) || fallback.answer;
  const citations = uniqueList([
    ...extractSourceIdsFromText(safeAnswer),
    ...(fallback.citations || [])
  ]).filter((id) => getReportSourceIdSet(report).has(id)).slice(0, 10);

  const keyPoints = deriveKeyPointsFromAnswer(safeAnswer);
  return {
    answer: safeAnswer,
    keyPoints: keyPoints.length ? keyPoints : fallback.keyPoints,
    citations,
    confidence: keyPoints.length >= 3 ? '中' : '低',
    followups: fallback.followups
  };
}

async function answerReportQuestion({ reportId, question }) {
  const id = String(reportId || '').trim();
  const safeQuestion = normalizeText(question, 500);

  if (!id) {
    throw new Error('缺少报告ID。');
  }
  if (!safeQuestion || safeQuestion.length < 2) {
    throw new Error('问题内容过短，请补充具体问题。');
  }

  const report = getReportById(id);
  if (!report) {
    throw new Error('报告不存在或已删除。');
  }

  addJob({
    type: 'report_qa',
    status: 'started',
    message: `开始处理报告问答：${normalizeText(report.title, 40)}。`
  });

  const context = buildReportQaContext(report);
  const fallback = buildFallbackQaAnswer(report, safeQuestion);
  const prompt = [
    {
      role: 'system',
      content: [
        '你是CMHK战略部分析师，回答报告相关问题。',
        '只能基于输入的report_context与sources回答，不得编造事实。',
        '如证据不足，明确指出不足与建议补充方向。',
        '引用规则：仅使用已给出的 sourceId（例如 [S1]）。',
        '输出必须是JSON，不要输出Markdown。',
        'JSON schema:',
        '{',
        '  answer:string,',
        '  keyPoints:string[],',
        '  citations:string[],',
        '  confidence:"高|中|低",',
        '  followups:string[]',
        '}'
      ].join(' ')
    },
    {
      role: 'user',
      content: JSON.stringify({
        question: safeQuestion,
        report_context: context
      })
    }
  ];

  let parsed = null;
  try {
    const raw = await deepseekChat(prompt, 0.1, { timeoutMs: REPORT_QA_TIMEOUT_MS });
    parsed = parseJsonPayload(raw || '');
  } catch (error) {
    addJob({
      type: 'report_qa',
      status: 'warning',
      message: `报告问答模型调用失败，已回退规则化回答：${error.message}`
    });
  }

  const normalized = sanitizeQaResponse(parsed, fallback, report);
  const qa = appendReportQa(id, {
    question: safeQuestion,
    answer: normalized.answer,
    keyPoints: normalized.keyPoints,
    citations: normalized.citations,
    confidence: normalized.confidence,
    followups: normalized.followups
  });

  if (!qa) {
    throw new Error('问答结果写入失败。');
  }

  addJob({
    type: 'report_qa',
    status: 'success',
    message: `报告问答已完成：${normalizeText(safeQuestion, 50)}`
  });

  return {
    reportId: id,
    qa
  };
}

async function answerReportQuestionStream({ reportId, question, onEvent }) {
  const emit = (payload) => {
    if (typeof onEvent === 'function') {
      onEvent(payload);
    }
  };

  const id = String(reportId || '').trim();
  const safeQuestion = normalizeText(question, 500);

  if (!id) {
    throw new Error('缺少报告ID。');
  }
  if (!safeQuestion || safeQuestion.length < 2) {
    throw new Error('问题内容过短，请补充具体问题。');
  }

  const report = getReportById(id);
  if (!report) {
    throw new Error('报告不存在或已删除。');
  }

  addJob({
    type: 'report_qa',
    status: 'started',
    message: `开始处理报告问答（流式）：${normalizeText(report.title, 40)}。`
  });

  const context = buildReportQaContext(report);
  const fallback = buildFallbackQaAnswer(report, safeQuestion);
  const prompt = [
    {
      role: 'system',
      content: [
        '你是CMHK战略部分析师，基于报告上下文回答用户问题。',
        '只能使用输入中的证据，不得编造。',
        '输出为正式中文正文，可使用小标题和要点；请在关键结论后附 [Sx] 引用。',
        '若证据不足，必须明确标注“证据不足”。'
      ].join(' ')
    },
    {
      role: 'user',
      content: JSON.stringify({
        question: safeQuestion,
        report_context: context
      })
    }
  ];

  emit({
    type: 'start',
    reportId: id,
    question: safeQuestion
  });

  let answerText = '';
  let usedFallback = false;
  try {
    answerText = await deepseekChatStream(prompt, 0.1, {
      timeoutMs: REPORT_QA_TIMEOUT_MS,
      onDelta: (delta) => {
        emit({ type: 'delta', text: delta });
      }
    });
  } catch (error) {
    usedFallback = true;
    answerText = fallback.answer;
    emit({
      type: 'warning',
      message: `流式模型响应失败，已回退规则化回答：${error.message}`
    });

    addJob({
      type: 'report_qa',
      status: 'warning',
      message: `流式问答模型调用失败，已回退规则化回答：${error.message}`
    });
  }

  const normalized = sanitizeQaFromStreamText(answerText, fallback, report);
  const qa = appendReportQa(id, {
    question: safeQuestion,
    answer: normalized.answer,
    keyPoints: normalized.keyPoints,
    citations: normalized.citations,
    confidence: normalized.confidence,
    followups: normalized.followups
  });

  if (!qa) {
    throw new Error('问答结果写入失败。');
  }

  addJob({
    type: 'report_qa',
    status: 'success',
    message: `报告问答已完成（流式）：${normalizeText(safeQuestion, 50)}${usedFallback ? '（回退）' : ''}`
  });

  emit({
    type: 'done',
    reportId: id,
    qa
  });

  return {
    reportId: id,
    qa
  };
}

module.exports = {
  generateWeeklyReport,
  generateTrendReport,
  regenerateReportsToFormal,
  answerReportQuestion,
  answerReportQuestionStream
};
