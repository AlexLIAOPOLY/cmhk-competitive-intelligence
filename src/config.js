const defaultSupportedCategories = ['财报', '产品发布会', '中标公示', '高管言论', '政策法规', '宏观数据'];

const defaultMonitoredCompetitors = [
  {
    name: 'Vodafone',
    region: 'Global',
    topics: [
      {
        category: '财报',
        queries: [
          'Vodafone quarterly results OR annual results OR earnings release',
          'Vodafone investor presentation OR revenue guidance OR EBITDA'
        ]
      },
      {
        category: '产品发布会',
        queries: [
          'Vodafone product launch OR service launch OR network launch',
          'Vodafone enterprise solution launch OR 5G launch event'
        ]
      },
      {
        category: '中标公示',
        queries: [
          'Vodafone tender award OR contract win OR procurement notice',
          'Vodafone framework agreement award OR public contract announcement'
        ]
      },
      {
        category: '高管言论',
        queries: [
          'Vodafone CEO interview OR executive speech OR strategy statement',
          'Vodafone management commentary OR conference remarks'
        ]
      }
    ]
  },
  {
    name: 'Orange',
    region: 'Global',
    topics: [
      {
        category: '财报',
        queries: [
          'Orange quarterly results OR annual results OR earnings release',
          'Orange investor relations update OR financial guidance OR EBITDA'
        ]
      },
      {
        category: '产品发布会',
        queries: [
          'Orange product launch OR service launch OR network launch',
          'Orange enterprise launch OR 5G launch event'
        ]
      },
      {
        category: '中标公示',
        queries: [
          'Orange tender award OR contract win OR procurement notice',
          'Orange public contract announcement OR project award'
        ]
      },
      {
        category: '高管言论',
        queries: [
          'Orange CEO interview OR executive speech OR strategy statement',
          'Orange management commentary OR conference remarks'
        ]
      }
    ]
  },
  {
    name: 'PCCW',
    region: 'Hong Kong',
    topics: [
      {
        category: '财报',
        queries: [
          'PCCW annual results OR interim results OR earnings announcement',
          'PCCW investor presentation OR financial guidance'
        ]
      },
      {
        category: '产品发布会',
        queries: [
          'PCCW product launch OR service launch OR network launch',
          'PCCW 5G launch event OR enterprise launch'
        ]
      },
      {
        category: '中标公示',
        queries: [
          'PCCW tender award OR contract win OR procurement notice',
          'PCCW project award announcement OR public tender result'
        ]
      },
      {
        category: '高管言论',
        queries: [
          'PCCW executive interview OR management speech OR strategy statement',
          'PCCW CEO remarks OR conference commentary'
        ]
      }
    ]
  },
  {
    name: 'SmarTone',
    region: 'Hong Kong',
    topics: [
      {
        category: '财报',
        queries: [
          'SmarTone annual results OR interim results OR earnings announcement',
          'Smartone investor presentation OR financial guidance'
        ]
      },
      {
        category: '产品发布会',
        queries: [
          'SmarTone product launch OR service launch OR network launch',
          'Smartone 5G launch event OR enterprise launch'
        ]
      },
      {
        category: '中标公示',
        queries: [
          'SmarTone tender award OR contract win OR procurement notice',
          'Smartone project award announcement OR public tender result'
        ]
      },
      {
        category: '高管言论',
        queries: [
          'SmarTone executive interview OR management speech OR strategy statement',
          'Smartone CEO remarks OR conference commentary'
        ]
      }
    ]
  },
  {
    name: 'OFCA (Hong Kong)',
    region: 'Hong Kong',
    topics: [
      {
        category: '政策法规',
        queries: [
          'OFCA policy statement OR telecom regulation update Hong Kong',
          'OFCA spectrum auction announcement OR telecom license condition update'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          'Hong Kong communications statistics mobile subscribers OFCA',
          'OFCA broadband penetration data Hong Kong report'
        ]
      }
    ]
  },
  {
    name: 'European Commission (Digital Policy)',
    region: 'EU',
    topics: [
      {
        category: '政策法规',
        queries: [
          'European Commission telecom regulation update Digital Markets Act telecom',
          'European Commission AI Act implementation telecom data compliance'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          'European Commission digital economy indicators telecom market data',
          'EU connectivity targets progress report broadband 5G'
        ]
      }
    ]
  },
  {
    name: 'ITU / OECD Telecom Indicators',
    region: 'Global',
    topics: [
      {
        category: '宏观数据',
        queries: [
          'ITU telecommunications indicators update mobile broadband penetration',
          'OECD telecom outlook report pricing ARPU investment'
        ]
      },
      {
        category: '政策法规',
        queries: [
          'ITU policy and regulatory trends telecom annual report',
          'OECD digital policy recommendation telecommunications data governance'
        ]
      }
    ]
  },
  {
    name: 'Hong Kong SAR Government',
    region: 'Hong Kong',
    topics: [
      {
        category: '政策法规',
        queries: [
          'Hong Kong government digital economy policy data governance AI regulation site:gov.hk',
          'Hong Kong Commerce and Economic Development Bureau telecommunications policy site:gov.hk',
          'Hong Kong housing policy public rental housing waiting time update site:gov.hk',
          'Hong Kong labour welfare healthcare education policy update site:gov.hk'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          'Hong Kong economic outlook GDP inflation unemployment official statistics site:gov.hk',
          'Hong Kong innovation and technology development indicators report site:gov.hk',
          'Hong Kong tourism visitor arrivals retail sales catering statistics site:gov.hk',
          'Hong Kong public housing completion and household livelihood statistics site:gov.hk'
        ]
      }
    ]
  },
  {
    name: 'Census and Statistics Department (Hong Kong)',
    region: 'Hong Kong',
    topics: [
      {
        category: '宏观数据',
        queries: [
          'Hong Kong ICT usage statistics report site:censtatd.gov.hk',
          'Hong Kong tourism retail trade external trade statistics site:censtatd.gov.hk',
          'Hong Kong unemployment rate labour earnings household income statistics site:censtatd.gov.hk',
          'Hong Kong consumer price index inflation housing related statistics site:censtatd.gov.hk'
        ]
      },
      {
        category: '政策法规',
        queries: [
          'Hong Kong official statistical release methodology update site:censtatd.gov.hk',
          'Hong Kong digital economy statistical framework site:censtatd.gov.hk',
          'Hong Kong social indicators publication standard update site:censtatd.gov.hk'
        ]
      }
    ]
  },
  {
    name: 'Hong Kong Social and Livelihood Statistics',
    region: 'Hong Kong',
    topics: [
      {
        category: '宏观数据',
        queries: [
          'Hong Kong unemployment rate median household income retail sales volume index site:censtatd.gov.hk',
          'Hong Kong visitor arrivals hotel occupancy tourism expenditure statistics site:censtatd.gov.hk'
        ]
      },
      {
        category: '政策法规',
        queries: [
          'Hong Kong housing policy public rental housing waiting time update site:gov.hk',
          'Hong Kong labour welfare policy elderly support healthcare policy update site:gov.hk'
        ]
      }
    ]
  },
  {
    name: 'Ofcom (UK Telecom Regulator)',
    region: 'UK',
    topics: [
      {
        category: '政策法规',
        queries: [
          'Ofcom telecom regulation consultation spectrum policy update site:ofcom.org.uk',
          'Ofcom communications review network competition policy site:ofcom.org.uk'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          'Ofcom Connected Nations broadband mobile coverage report site:ofcom.org.uk',
          'Ofcom UK telecom market data revenue ARPU investment site:ofcom.org.uk'
        ]
      }
    ]
  },
  {
    name: 'FCC (US Communications Regulator)',
    region: 'US',
    topics: [
      {
        category: '政策法规',
        queries: [
          'FCC communications regulation rulemaking broadband spectrum site:fcc.gov',
          'FCC AI data privacy telecom policy update site:fcc.gov'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          'FCC communications marketplace report broadband deployment data site:fcc.gov',
          'FCC mobile wireless competition report site:fcc.gov'
        ]
      }
    ]
  },
  {
    name: 'GSMA Intelligence',
    region: 'Global',
    topics: [
      {
        category: '宏观数据',
        queries: [
          'GSMA Intelligence mobile economy report 5G adoption capex',
          'GSMA telecom pricing ARPU investment outlook report'
        ]
      },
      {
        category: '政策法规',
        queries: [
          'GSMA policy position spectrum regulation data governance',
          'GSMA Open Gateway regulatory and industry collaboration update'
        ]
      }
    ]
  },
  {
    name: 'World Bank / IMF Digital Economy',
    region: 'Global',
    topics: [
      {
        category: '宏观数据',
        queries: [
          'World Bank digital development telecommunications indicators data',
          'IMF Asia regional economic outlook digital infrastructure telecommunications'
        ]
      },
      {
        category: '政策法规',
        queries: [
          'World Bank policy note digital regulation telecommunications reform',
          'IMF policy recommendation digital economy data governance telecom sector'
        ]
      }
    ]
  },
  {
    name: 'MIIT / CAC (Mainland China Policy)',
    region: 'Mainland China',
    topics: [
      {
        category: '政策法规',
        queries: [
          '工信部 电信 行业 监管 政策 通知 5G 算力',
          '网信办 数据 安全 人工智能 监管 政策'
        ]
      },
      {
        category: '宏观数据',
        queries: [
          '工信部 通信业 经济运行 数据 公报',
          '国家统计局 数字经济 通信业务 收入 数据'
        ]
      }
    ]
  }
];

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function normalizeQueries(input) {
  if (!Array.isArray(input)) return [];
  return input
    .map((query) => (typeof query === 'string' ? query.trim() : ''))
    .filter(Boolean)
    .slice(0, 30);
}

function normalizeMonitoredCompetitors(input, fallback = defaultMonitoredCompetitors) {
  const source = Array.isArray(input) ? input : deepClone(fallback);
  const result = [];

  for (const competitor of source) {
    const name = typeof competitor?.name === 'string' ? competitor.name.trim() : '';
    if (!name) continue;

    const region = typeof competitor?.region === 'string' && competitor.region.trim()
      ? competitor.region.trim()
      : 'Unknown';

    const topics = Array.isArray(competitor?.topics)
      ? competitor.topics
      : [];

    const normalizedTopics = topics
      .map((topic) => {
        const category = typeof topic?.category === 'string' && topic.category.trim()
          ? topic.category.trim()
          : '';
        const queries = normalizeQueries(topic?.queries);

        if (!category || !queries.length) return null;
        return { category, queries };
      })
      .filter(Boolean)
      .slice(0, 20);

    if (!normalizedTopics.length) continue;

    result.push({
      name,
      region,
      topics: normalizedTopics
    });
  }

  if (!result.length) {
    return deepClone(fallback);
  }

  return result;
}

function normalizeTopicCategoryKey(value) {
  return String(value || '').trim().toLowerCase();
}

function mergeTopicQueries(existingQueries, defaultQueries) {
  const base = normalizeQueries(existingQueries);
  const extras = normalizeQueries(defaultQueries);
  const seen = new Set(base.map((query) => query.toLowerCase()));

  for (const query of extras) {
    const key = query.toLowerCase();
    if (seen.has(key)) continue;
    base.push(query);
    seen.add(key);
    if (base.length >= 30) break;
  }

  return base;
}

function mergeCompetitorTopics(existingTopics, defaultTopics) {
  const normalizedExisting = Array.isArray(existingTopics) ? deepClone(existingTopics) : [];
  const normalizedDefaults = Array.isArray(defaultTopics) ? defaultTopics : [];

  const indexMap = new Map();
  normalizedExisting.forEach((topic, index) => {
    indexMap.set(normalizeTopicCategoryKey(topic?.category), index);
  });

  for (const defaultTopic of normalizedDefaults) {
    const category = String(defaultTopic?.category || '').trim();
    if (!category) continue;
    const key = normalizeTopicCategoryKey(category);
    const existingIndex = indexMap.get(key);

    if (existingIndex === undefined) {
      normalizedExisting.push({
        category,
        queries: normalizeQueries(defaultTopic?.queries)
      });
      indexMap.set(key, normalizedExisting.length - 1);
      continue;
    }

    normalizedExisting[existingIndex] = {
      ...normalizedExisting[existingIndex],
      category: normalizedExisting[existingIndex]?.category || category,
      queries: mergeTopicQueries(normalizedExisting[existingIndex]?.queries, defaultTopic?.queries)
    };
  }

  return normalizedExisting.slice(0, 20);
}

function mergeWithDefaultMonitoredCompetitors(input, defaults = defaultMonitoredCompetitors) {
  const base = normalizeMonitoredCompetitors(input, defaults);
  const normalizedDefaults = normalizeMonitoredCompetitors(defaults, defaults);

  const result = deepClone(base);
  const existingIndex = new Map(result.map((item, index) => [item.name.toLowerCase(), index]));

  for (const candidate of normalizedDefaults) {
    const key = candidate.name.toLowerCase();
    if (!existingIndex.has(key)) {
      result.push(deepClone(candidate));
      existingIndex.set(key, result.length - 1);
      continue;
    }

    const index = existingIndex.get(key);
    const current = result[index];
    const mergedTopics = mergeCompetitorTopics(current.topics, candidate.topics);
    result[index] = {
      ...current,
      region: current.region || candidate.region || 'Unknown',
      topics: mergedTopics
    };
  }

  return normalizeMonitoredCompetitors(result, defaults);
}

function validateMonitoredCompetitors(input) {
  const errors = [];

  if (!Array.isArray(input)) {
    errors.push('competitors 必须为数组');
    return { ok: false, errors };
  }

  if (!input.length) {
    errors.push('至少保留一个监测竞对');
    return { ok: false, errors };
  }

  input.forEach((competitor, competitorIndex) => {
    const row = competitorIndex + 1;
    const name = typeof competitor?.name === 'string' ? competitor.name.trim() : '';
    if (!name) {
      errors.push(`第 ${row} 个竞对缺少名称`);
    }

    if (!Array.isArray(competitor?.topics) || !competitor.topics.length) {
      errors.push(`第 ${row} 个竞对至少需要一个监测类别`);
      return;
    }

    competitor.topics.forEach((topic, topicIndex) => {
      const category = typeof topic?.category === 'string' ? topic.category.trim() : '';
      if (!category) {
        errors.push(`第 ${row} 个竞对的第 ${topicIndex + 1} 个类别缺少名称`);
      }

      const queries = normalizeQueries(topic?.queries);
      if (!queries.length) {
        errors.push(`第 ${row} 个竞对的第 ${topicIndex + 1} 个类别至少需要一条检索语句`);
      }
    });
  });

  return {
    ok: errors.length === 0,
    errors
  };
}

function getCategoryListFromCompetitors(competitors) {
  const values = new Set();

  for (const competitor of competitors || []) {
    for (const topic of competitor.topics || []) {
      if (topic.category) {
        values.add(topic.category);
      }
    }
  }

  const list = Array.from(values);
  if (!list.length) return deepClone(defaultSupportedCategories);
  return list;
}

module.exports = {
  defaultSupportedCategories,
  defaultMonitoredCompetitors,
  normalizeMonitoredCompetitors,
  mergeWithDefaultMonitoredCompetitors,
  validateMonitoredCompetitors,
  getCategoryListFromCompetitors,
  deepClone
};
