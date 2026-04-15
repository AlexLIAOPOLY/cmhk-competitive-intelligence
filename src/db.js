const fs = require('fs');
const path = require('path');
const {
  defaultMonitoredCompetitors,
  normalizeMonitoredCompetitors,
  mergeWithDefaultMonitoredCompetitors,
  getCategoryListFromCompetitors,
  deepClone
} = require('./config');

function resolvePathFromEnv(value, fallbackPath) {
  const text = String(value || '').trim();
  if (!text) return fallbackPath;
  return path.isAbsolute(text)
    ? text
    : path.resolve(process.cwd(), text);
}

const defaultDataDir = path.join(__dirname, '..', 'data');
const dataDir = resolvePathFromEnv(process.env.DATA_DIR, defaultDataDir);
const dbPath = resolvePathFromEnv(process.env.DB_PATH, path.join(dataDir, 'db.json'));
const dbDir = path.dirname(dbPath);
const MAX_JOBS = 500;
const DEFAULT_TIMEZONE = process.env.SCAN_TIMEZONE || 'Asia/Hong_Kong';
const DEFAULT_SCAN_INTERVAL_MINUTES = Number(process.env.SCAN_INTERVAL_MINUTES || 30);

function normalizeClockTime(value, fallback = '09:00') {
  const text = String(value || '').trim();
  if (!text) return fallback;
  const match = text.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) return fallback;
  return `${match[1]}:${match[2]}`;
}

function normalizeIntervalMinutes(value, fallback = DEFAULT_SCAN_INTERVAL_MINUTES) {
  const normalized = Number(value);
  const safe = Number.isFinite(normalized) ? normalized : fallback;
  return Math.max(5, Math.min(1440, Math.round(safe)));
}

function normalizeWeekday(value, fallback = 1) {
  const day = Number(value);
  if (!Number.isFinite(day)) return fallback;
  return Math.max(0, Math.min(6, Math.round(day)));
}

function normalizeWebhookUrl(value) {
  const text = String(value || '').trim();
  if (!text) return '';
  try {
    const parsed = new URL(text);
    if (!/^https?:$/.test(parsed.protocol)) return '';
    return parsed.toString();
  } catch {
    return '';
  }
}

function normalizeHeartbeatSettings(heartbeat) {
  const source = heartbeat && typeof heartbeat === 'object' ? heartbeat : {};
  const scan = source.scan && typeof source.scan === 'object' ? source.scan : {};
  const weeklyReport = source.weeklyReport && typeof source.weeklyReport === 'object' ? source.weeklyReport : {};
  const trendReport = source.trendReport && typeof source.trendReport === 'object' ? source.trendReport : {};
  const push = source.push && typeof source.push === 'object' ? source.push : {};
  const pushDailyDigest = push.dailyDigest && typeof push.dailyDigest === 'object' ? push.dailyDigest : {};
  const pushWeeklySummary = push.weeklySummary && typeof push.weeklySummary === 'object' ? push.weeklySummary : {};

  return {
    timezone: String(source.timezone || DEFAULT_TIMEZONE).trim() || DEFAULT_TIMEZONE,
    scan: {
      enabled: scan.enabled !== false,
      intervalMinutes: normalizeIntervalMinutes(scan.intervalMinutes, DEFAULT_SCAN_INTERVAL_MINUTES)
    },
    weeklyReport: {
      enabled: Boolean(weeklyReport.enabled),
      dayOfWeek: normalizeWeekday(weeklyReport.dayOfWeek, 1),
      time: normalizeClockTime(weeklyReport.time, '09:00')
    },
    trendReport: {
      enabled: Boolean(trendReport.enabled),
      time: normalizeClockTime(trendReport.time, '09:20')
    },
    push: {
      enabled: Boolean(push.enabled),
      webhookUrl: normalizeWebhookUrl(push.webhookUrl),
      onReportGenerated: push.onReportGenerated !== false,
      dailyDigest: {
        enabled: pushDailyDigest.enabled !== false,
        time: normalizeClockTime(pushDailyDigest.time, '08:30')
      },
      weeklySummary: {
        enabled: pushWeeklySummary.enabled !== false,
        dayOfWeek: normalizeWeekday(pushWeeklySummary.dayOfWeek, 1),
        time: normalizeClockTime(pushWeeklySummary.time, '09:10')
      }
    }
  };
}

function createInitialSettings() {
  return {
    competitors: normalizeMonitoredCompetitors(defaultMonitoredCompetitors),
    heartbeat: normalizeHeartbeatSettings()
  };
}

function createInitialDb() {
  return {
    version: 2,
    settings: createInitialSettings(),
    findings: [],
    reports: [],
    jobs: [],
    lastScanAt: null,
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString()
  };
}

function ensureDb() {
  if (!fs.existsSync(dbDir)) {
    fs.mkdirSync(dbDir, { recursive: true });
  }

  if (!fs.existsSync(dbPath)) {
    const initial = createInitialDb();
    fs.writeFileSync(dbPath, JSON.stringify(initial, null, 2), 'utf8');
  }
}

function normalizeSettings(settings) {
  const source = settings && typeof settings === 'object' ? settings : {};
  const normalizedCompetitors = normalizeMonitoredCompetitors(source.competitors);
  return {
    competitors: mergeWithDefaultMonitoredCompetitors(normalizedCompetitors, defaultMonitoredCompetitors),
    heartbeat: normalizeHeartbeatSettings(source.heartbeat)
  };
}

function normalizeExistingDb(data) {
  const initial = createInitialDb();
  return {
    ...initial,
    ...data,
    settings: normalizeSettings(data.settings),
    findings: Array.isArray(data.findings) ? data.findings : [],
    reports: Array.isArray(data.reports) ? data.reports : [],
    jobs: Array.isArray(data.jobs) ? data.jobs : []
  };
}

function readDb() {
  ensureDb();
  try {
    const parsed = JSON.parse(fs.readFileSync(dbPath, 'utf8'));
    return normalizeExistingDb(parsed);
  } catch (error) {
    const backupPath = `${dbPath}.broken.${Date.now()}`;
    fs.copyFileSync(dbPath, backupPath);
    const reset = createInitialDb();
    fs.writeFileSync(dbPath, JSON.stringify(reset, null, 2), 'utf8');
    return reset;
  }
}

function writeDb(data) {
  ensureDb();
  const next = {
    ...normalizeExistingDb(data),
    updatedAt: new Date().toISOString()
  };
  const tempPath = `${dbPath}.tmp`;
  fs.writeFileSync(tempPath, JSON.stringify(next, null, 2), 'utf8');
  fs.renameSync(tempPath, dbPath);
}

function getMonitoringConfig() {
  const db = readDb();
  const competitors = deepClone(db.settings.competitors);
  return {
    competitors,
    categories: getCategoryListFromCompetitors(competitors)
  };
}

function getHeartbeatConfig() {
  const db = readDb();
  return deepClone(normalizeHeartbeatSettings(db.settings.heartbeat));
}

function updateMonitoringConfig(competitors) {
  const db = readDb();
  const normalized = normalizeMonitoredCompetitors(competitors);
  db.settings = {
    ...db.settings,
    competitors: normalized
  };
  writeDb(db);
  return {
    competitors: deepClone(normalized),
    categories: getCategoryListFromCompetitors(normalized)
  };
}

function updateHeartbeatConfig(heartbeat) {
  const db = readDb();
  const normalized = normalizeHeartbeatSettings(heartbeat);
  db.settings = {
    ...db.settings,
    heartbeat: normalized
  };
  writeDb(db);
  return deepClone(normalized);
}

function normalizeUrl(url) {
  if (!url || typeof url !== 'string') return '';
  try {
    const parsed = new URL(url.trim());
    parsed.hash = '';
    parsed.searchParams.delete('utm_source');
    parsed.searchParams.delete('utm_medium');
    parsed.searchParams.delete('utm_campaign');
    parsed.searchParams.delete('utm_term');
    parsed.searchParams.delete('utm_content');
    return parsed.toString();
  } catch {
    return url.trim();
  }
}

function buildFindingKey(item) {
  const normalizedUrl = normalizeUrl(item.sourceUrl);
  const competitor = item.competitor || 'unknown';
  return `${competitor}::${normalizedUrl || item.title || ''}`;
}

function upsertFindings(items) {
  const db = readDb();
  let inserted = 0;
  let updated = 0;

  for (const item of items) {
    const key = buildFindingKey(item);
    const existingIndex = db.findings.findIndex((entry) => buildFindingKey(entry) === key);

    if (existingIndex >= 0) {
      db.findings[existingIndex] = {
        ...db.findings[existingIndex],
        ...item,
        sourceUrl: normalizeUrl(item.sourceUrl),
        updatedAt: new Date().toISOString()
      };
      updated += 1;
      continue;
    }

    db.findings.unshift({
      id: `finding_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      createdAt: new Date().toISOString(),
      sourceUrl: normalizeUrl(item.sourceUrl),
      ...item
    });
    inserted += 1;
  }

  db.lastScanAt = new Date().toISOString();
  writeDb(db);

  return {
    inserted,
    updated,
    totalWritten: inserted + updated,
    totalFindings: db.findings.length,
    items: db.findings
  };
}

function addReport(report) {
  const db = readDb();
  const next = {
    id: `report_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    ...report
  };
  db.reports.unshift(next);
  writeDb(db);
  return next;
}

function getReportById(reportId) {
  const id = String(reportId || '').trim();
  if (!id) return null;
  const db = readDb();
  const found = db.reports.find((item) => item.id === id);
  return found ? deepClone(found) : null;
}

function appendReportQa(reportId, qaItem) {
  const id = String(reportId || '').trim();
  if (!id) return null;
  const db = readDb();
  const index = db.reports.findIndex((item) => item.id === id);
  if (index < 0) return null;

  const report = db.reports[index];
  const history = Array.isArray(report.qaHistory) ? report.qaHistory : [];
  const nextItem = {
    id: `qa_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    ...qaItem
  };

  history.unshift(nextItem);
  report.qaHistory = history.slice(0, 50);
  db.reports[index] = report;
  writeDb(db);
  return deepClone(nextItem);
}

function addJob(job) {
  const db = readDb();
  db.jobs.unshift({
    id: `job_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    createdAt: new Date().toISOString(),
    ...job
  });

  if (db.jobs.length > MAX_JOBS) {
    db.jobs = db.jobs.slice(0, MAX_JOBS);
  }

  writeDb(db);
}

function queryFindings(filters = {}) {
  const db = readDb();
  const {
    competitor,
    category,
    keyword,
    from,
    to,
    limit = 100
  } = filters;

  const competitorList = Array.isArray(competitor)
    ? competitor
    : String(competitor || '').split(',');
  const competitorSet = new Set(
    competitorList
      .map((item) => String(item || '').trim())
      .filter(Boolean)
  );

  const normalizedKeyword = (keyword || '').trim().toLowerCase();
  const fromMs = from ? Date.parse(from) : null;
  const toMs = to
    ? (to.includes('T') ? Date.parse(to) : Date.parse(`${to}T23:59:59.999`))
    : null;

  const items = db.findings.filter((item) => {
    if (competitorSet.size > 0 && !competitorSet.has(String(item.competitor || ''))) return false;
    if (category && item.category !== category) return false;

    if (normalizedKeyword) {
      const haystack = [
        item.title,
        item.summary,
        item.significance,
        item.rawSnippet,
        ...(Array.isArray(item.keywords) ? item.keywords : [])
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(normalizedKeyword)) return false;
    }

    const publishedAt = item.publishedAt || item.createdAt;
    const publishedMs = publishedAt ? Date.parse(publishedAt) : null;

    if (fromMs && publishedMs && publishedMs < fromMs) return false;
    if (toMs && publishedMs && publishedMs > toMs) return false;

    return true;
  });

  return items.slice(0, Number(limit) || 100);
}

function queryReports(filters = {}) {
  const db = readDb();
  const { type, limit = 50 } = filters;

  const items = db.reports.filter((item) => {
    if (type && item.type !== type) return false;
    return true;
  });

  return items.slice(0, Number(limit) || 50);
}

function queryJobs(limit = 100) {
  const db = readDb();
  return db.jobs.slice(0, Number(limit) || 100);
}

module.exports = {
  ensureDb,
  readDb,
  writeDb,
  getMonitoringConfig,
  getHeartbeatConfig,
  updateMonitoringConfig,
  updateHeartbeatConfig,
  upsertFindings,
  addReport,
  getReportById,
  appendReportQa,
  addJob,
  queryFindings,
  queryReports,
  queryJobs,
  normalizeUrl,
  normalizeHeartbeatSettings
};
