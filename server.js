require('dotenv').config();

const express = require('express');
const path = require('path');
const {
  ensureDb,
  readDb,
  queryReports,
  queryJobs,
  getMonitoringConfig,
  updateMonitoringConfig,
  addJob,
  getReportById
} = require('./src/db');
const {
  runFullScan,
  startScan,
  requestStopScan,
  getRecentFindings,
  getScanState
} = require('./src/scanner');
const { buildCompetitorDashboard } = require('./src/dashboard');
const { runCoverageBoost } = require('./src/coverageBoost');
const {
  generateWeeklyReport,
  generateTrendReport,
  regenerateReportsToFormal,
  answerReportQuestion,
  answerReportQuestionStream
} = require('./src/reports');
const { exportReportAsDocx, exportReportAsPdf } = require('./src/exporters');
const { startScheduler, getSchedulerState, updateHeartbeatConfig } = require('./src/scheduler');
const { validateMonitoredCompetitors } = require('./src/config');

const app = express();
const port = Number(process.env.PORT || 3000);

function safeExportFilename(value) {
  const text = String(value || 'report')
    .replace(/[^\x20-\x7E]/g, '_')
    .replace(/[\\/:*?"<>|]/g, '_')
    .replace(/\s+/g, '_')
    .replace(/_+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 80);
  return text || 'report';
}

ensureDb();
app.use(express.json({ limit: '5mb' }));
app.use(express.static(path.join(__dirname, 'public')));

app.get('/api/health', (req, res) => {
  res.json({ ok: true, now: new Date().toISOString() });
});

app.get('/api/config', (req, res) => {
  const monitoring = getMonitoringConfig();
  const scheduler = getSchedulerState();
  res.json({
    ok: true,
    competitors: monitoring.competitors,
    categories: monitoring.categories,
    scanSchedule: process.env.SCAN_SCHEDULE || '*/30 * * * *',
    timezone: process.env.SCAN_TIMEZONE || 'Asia/Hong_Kong',
    heartbeat: scheduler.heartbeat
  });
});

app.put('/api/config/competitors', (req, res) => {
  const payload = req.body || {};
  const validation = validateMonitoredCompetitors(payload.competitors);

  if (!validation.ok) {
    res.status(400).json({
      ok: false,
      error: validation.errors.join('；')
    });
    return;
  }

  const updated = updateMonitoringConfig(payload.competitors);
  addJob({
    type: 'config',
    status: 'success',
    message: `监测配置已更新：${updated.competitors.length} 个竞对，${updated.categories.length} 个类别。`
  });

  res.json({
    ok: true,
    ...updated
  });
});

app.get('/api/status', (req, res) => {
  const db = readDb();
  const monitoring = getMonitoringConfig();
  res.json({
    ok: true,
    now: new Date().toISOString(),
    lastScanAt: db.lastScanAt,
    findingCount: db.findings.length,
    reportCount: db.reports.length,
    jobCount: db.jobs.length,
    competitors: monitoring.competitors.map((item) => item.name),
    categories: monitoring.categories,
    scheduler: getSchedulerState(),
    scanner: getScanState()
  });
});

app.get('/api/heartbeat', (req, res) => {
  const scheduler = getSchedulerState();
  res.json({
    ok: true,
    heartbeat: scheduler.heartbeat,
    scheduler
  });
});

app.put('/api/heartbeat', (req, res) => {
  try {
    const result = updateHeartbeatConfig(req.body || {}, { operator: '控制台' });
    res.json({
      ok: true,
      ...result
    });
  } catch (error) {
    res.status(400).json({
      ok: false,
      error: error.message
    });
  }
});

app.get('/api/scan/state', (req, res) => {
  res.json({ ok: true, state: getScanState() });
});

app.get('/api/metrics', (req, res) => {
  const db = readDb();
  const limit = Math.max(50, Math.min(500, Number(req.query.limit || 200)));
  const items = db.findings.slice(0, limit);

  const competitorMap = new Map();
  const categoryMap = new Map();

  for (const item of items) {
    if (item.competitor) {
      competitorMap.set(item.competitor, (competitorMap.get(item.competitor) || 0) + 1);
    }
    if (item.category) {
      categoryMap.set(item.category, (categoryMap.get(item.category) || 0) + 1);
    }
  }

  const byCompetitor = Array.from(competitorMap.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);

  const byCategory = Array.from(categoryMap.entries())
    .map(([name, count]) => ({ name, count }))
    .sort((a, b) => b.count - a.count);

  const byDateMap = new Map();
  const trendDays = Math.max(7, Math.min(30, Number(req.query.days || 14)));
  for (let i = trendDays - 1; i >= 0; i -= 1) {
    const date = new Date(Date.now() - i * 24 * 60 * 60 * 1000);
    const key = date.toISOString().slice(0, 10);
    byDateMap.set(key, 0);
  }

  for (const item of items) {
    const baseline = item.publishedAt || item.capturedAt || item.createdAt;
    if (!baseline) continue;
    const parsed = Date.parse(baseline);
    if (Number.isNaN(parsed)) continue;
    const key = new Date(parsed).toISOString().slice(0, 10);
    if (!byDateMap.has(key)) continue;
    byDateMap.set(key, (byDateMap.get(key) || 0) + 1);
  }

  const byDate = Array.from(byDateMap.entries()).map(([date, count]) => ({
    date,
    count
  }));

  res.json({
    ok: true,
    sampleSize: items.length,
    byCompetitor,
    byCategory,
    byDate
  });
});

app.get('/api/dashboard/competitors', (req, res) => {
  try {
    const days = Number(req.query.days || 180);
    const payload = buildCompetitorDashboard({ days });
    res.json({
      ok: true,
      ...payload
    });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message
    });
  }
});

app.post('/api/scan/run', async (req, res) => {
  const runAsync = req.query.async === '1' || req.body?.async === true || req.body?.wait === false;

  try {
    if (runAsync) {
      const result = startScan({ trigger: 'manual' });
      res.status(202).json({ ok: true, mode: 'async', ...result });
      return;
    }

    const result = await runFullScan({ trigger: 'manual' });
    res.json({ ok: true, mode: 'wait', result });
  } catch (error) {
    if (error.code === 'SCAN_IN_PROGRESS') {
      res.status(409).json({ ok: false, error: error.message });
      return;
    }
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/scan/stop', (req, res) => {
  try {
    const result = requestStopScan({
      reason: req.body?.reason || '用户在控制台手动截停'
    });

    res.json({
      ok: true,
      ...result
    });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/scan/coverage-boost', async (req, res) => {
  try {
    if (getScanState().running) {
      res.status(409).json({
        ok: false,
        error: '当前有扫描任务正在执行，请先等待完成或截停后再执行覆盖增强。'
      });
      return;
    }

    const result = await runCoverageBoost({
      maxResults: Number(req.body?.maxResults || 5)
    });

    res.json({
      ok: true,
      result
    });
  } catch (error) {
    res.status(500).json({
      ok: false,
      error: error.message
    });
  }
});

app.get('/api/findings', (req, res) => {
  const {
    competitor,
    category,
    keyword,
    from,
    to,
    limit
  } = req.query;

  const items = getRecentFindings({
    competitor,
    category,
    keyword,
    from,
    to,
    limit: limit ? Number(limit) : 100
  });

  res.json({ ok: true, items });
});

app.post('/api/reports/weekly/generate', async (req, res) => {
  try {
    const report = await generateWeeklyReport();
    res.json({ ok: true, report });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/reports/trends/generate', async (req, res) => {
  try {
    const report = await generateTrendReport();
    res.json({ ok: true, report });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/reports/upgrade-formal', (req, res) => {
  try {
    const result = regenerateReportsToFormal();
    res.json({ ok: true, result });
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.post('/api/reports/:id/qa', async (req, res) => {
  try {
    const result = await answerReportQuestion({
      reportId: req.params.id,
      question: req.body?.question
    });
    res.json({ ok: true, ...result });
  } catch (error) {
    res.status(400).json({ ok: false, error: error.message });
  }
});

app.post('/api/reports/:id/qa/stream', async (req, res) => {
  res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
  res.setHeader('Cache-Control', 'no-cache, no-transform');
  res.setHeader('Connection', 'keep-alive');
  res.setHeader('X-Accel-Buffering', 'no');

  const writeEvent = (payload) => {
    res.write(`${JSON.stringify(payload)}\n`);
  };

  try {
    await answerReportQuestionStream({
      reportId: req.params.id,
      question: req.body?.question,
      onEvent: writeEvent
    });
  } catch (error) {
    writeEvent({
      type: 'error',
      error: error.message
    });
  } finally {
    res.end();
  }
});

app.get('/api/reports/:id/export/word', async (req, res) => {
  try {
    const report = getReportById(req.params.id);
    if (!report) {
      res.status(404).json({ ok: false, error: '报告不存在。' });
      return;
    }

    const buffer = await exportReportAsDocx(report);
    const filename = `${safeExportFilename(report.title)}_${String(report.id || '').slice(-6)}.docx`;

    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"; filename*=UTF-8''${encodeURIComponent(filename)}`);
    res.send(buffer);
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.get('/api/reports/:id/export/pdf', async (req, res) => {
  try {
    const report = getReportById(req.params.id);
    if (!report) {
      res.status(404).json({ ok: false, error: '报告不存在。' });
      return;
    }

    const buffer = await exportReportAsPdf(report);
    const filename = `${safeExportFilename(report.title)}_${String(report.id || '').slice(-6)}.pdf`;

    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', `attachment; filename="${filename}"; filename*=UTF-8''${encodeURIComponent(filename)}`);
    res.send(buffer);
  } catch (error) {
    res.status(500).json({ ok: false, error: error.message });
  }
});

app.get('/api/reports', (req, res) => {
  const { type, limit } = req.query;
  const items = queryReports({
    type,
    limit: limit ? Number(limit) : 50
  });
  res.json({ ok: true, items });
});

app.get('/api/jobs', (req, res) => {
  const { limit } = req.query;
  const items = queryJobs(limit ? Number(limit) : 100);
  res.json({ ok: true, items });
});

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(port, () => {
  startScheduler();
  console.log(`CMHK intelligence platform running at http://localhost:${port}`);
});
