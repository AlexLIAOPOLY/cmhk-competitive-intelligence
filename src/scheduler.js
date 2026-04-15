require('dotenv').config();

const cron = require('node-cron');
const { runFullScan, getScanState } = require('./scanner');
const { generateWeeklyReport, generateTrendReport } = require('./reports');
const {
  addJob,
  getHeartbeatConfig,
  updateHeartbeatConfig: persistHeartbeatConfig,
  normalizeHeartbeatSettings
} = require('./db');

const runtime = {
  started: false,
  timezone: process.env.SCAN_TIMEZONE || 'Asia/Hong_Kong',
  heartbeat: normalizeHeartbeatSettings(),
  scanTimerId: null,
  weeklyTask: null,
  trendTask: null,
  inFlight: {
    scan: false,
    weekly: false,
    trend: false
  },
  lastTriggeredAt: {
    scan: null,
    weekly: null,
    trend: null
  },
  nextTriggeredAt: {
    scan: null,
    weekly: null,
    trend: null
  }
};

const WEEKDAY_LABELS = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];

function parseClockTime(value, fallback = '09:00') {
  const text = String(value || fallback).trim();
  const match = text.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
  if (!match) {
    const fallbackMatch = String(fallback).match(/^([01]\d|2[0-3]):([0-5]\d)$/);
    return {
      hour: Number(fallbackMatch[1]),
      minute: Number(fallbackMatch[2]),
      normalized: `${fallbackMatch[1]}:${fallbackMatch[2]}`
    };
  }

  return {
    hour: Number(match[1]),
    minute: Number(match[2]),
    normalized: `${match[1]}:${match[2]}`
  };
}

function normalizeWeekday(value, fallback = 1) {
  const day = Number(value);
  if (!Number.isFinite(day)) return fallback;
  return Math.max(0, Math.min(6, Math.round(day)));
}

function formatWeekdayLabel(day) {
  const normalized = normalizeWeekday(day, 1);
  return WEEKDAY_LABELS[normalized] || `周${normalized}`;
}

function clearCronTask(task) {
  if (!task) return;
  try {
    task.stop();
  } catch {
    // ignore
  }
  try {
    task.destroy();
  } catch {
    // ignore
  }
}

function clearScanTimer() {
  if (!runtime.scanTimerId) return;
  clearInterval(runtime.scanTimerId);
  runtime.scanTimerId = null;
}

async function triggerScanTask(trigger = 'heartbeat_scan') {
  if (runtime.inFlight.scan) return;
  runtime.inFlight.scan = true;
  runtime.lastTriggeredAt.scan = new Date().toISOString();

  try {
    await runFullScan({ trigger });
  } catch (error) {
    if (error.code === 'SCAN_IN_PROGRESS') {
      addJob({
        type: 'heartbeat_scan',
        status: 'warning',
        message: '心跳扫描触发时发现已有扫描任务在执行，本次自动跳过。'
      });
      return;
    }

    addJob({
      type: 'heartbeat_scan',
      status: 'failed',
      message: `心跳扫描失败：${error.message}`
    });
  } finally {
    runtime.inFlight.scan = false;
  }
}

async function triggerWeeklyReportTask(trigger = 'heartbeat_weekly_report') {
  if (runtime.inFlight.weekly) return;
  runtime.inFlight.weekly = true;
  runtime.lastTriggeredAt.weekly = new Date().toISOString();

  try {
    await generateWeeklyReport();
    addJob({
      type: 'heartbeat_weekly_report',
      status: 'success',
      message: '心跳任务已自动生成竞对动态周报。'
    });
  } catch (error) {
    addJob({
      type: 'heartbeat_weekly_report',
      status: 'failed',
      message: `自动生成竞对动态周报失败：${error.message}`
    });
  } finally {
    runtime.inFlight.weekly = false;
  }
}

async function triggerTrendReportTask(trigger = 'heartbeat_trend_report') {
  if (runtime.inFlight.trend) return;
  runtime.inFlight.trend = true;
  runtime.lastTriggeredAt.trend = new Date().toISOString();

  try {
    await generateTrendReport();
    addJob({
      type: 'heartbeat_trend_report',
      status: 'success',
      message: '心跳任务已自动生成行业趋势研判报告。'
    });
  } catch (error) {
    addJob({
      type: 'heartbeat_trend_report',
      status: 'failed',
      message: `自动生成行业趋势研判报告失败：${error.message}`
    });
  } finally {
    runtime.inFlight.trend = false;
  }
}

function scheduleScanByInterval(heartbeat) {
  clearScanTimer();
  runtime.nextTriggeredAt.scan = null;

  if (!heartbeat.scan.enabled) {
    return;
  }

  const intervalMs = heartbeat.scan.intervalMinutes * 60 * 1000;
  runtime.nextTriggeredAt.scan = new Date(Date.now() + intervalMs).toISOString();

  runtime.scanTimerId = setInterval(() => {
    runtime.nextTriggeredAt.scan = new Date(Date.now() + intervalMs).toISOString();
    triggerScanTask('heartbeat_scan').catch((error) => {
      addJob({
        type: 'heartbeat_scan',
        status: 'failed',
        message: `心跳扫描异常：${error.message}`
      });
    });
  }, intervalMs);
}

function scheduleDailyReportTask(taskName, options) {
  const {
    enabled,
    time,
    fallback,
    runtimeTaskKey,
    nextTriggerKey,
    triggerFn
  } = options;

  clearCronTask(runtime[runtimeTaskKey]);
  runtime[runtimeTaskKey] = null;
  runtime.nextTriggeredAt[nextTriggerKey] = null;

  if (!enabled) return;

  const parsed = parseClockTime(time, fallback);
  const cronExpression = `${parsed.minute} ${parsed.hour} * * *`;

  if (!cron.validate(cronExpression)) {
    addJob({
      type: 'scheduler',
      status: 'warning',
      message: `${taskName} 配置时间无效：${time}，已跳过。`
    });
    return;
  }

  runtime[runtimeTaskKey] = cron.schedule(
    cronExpression,
    () => {
      triggerFn().catch((error) => {
        addJob({
          type: taskName,
          status: 'failed',
          message: `${taskName} 执行异常：${error.message}`
        });
      });
    },
    {
      timezone: runtime.timezone
    }
  );

  runtime.nextTriggeredAt[nextTriggerKey] = `${parsed.normalized} (${runtime.timezone})`;
}

function scheduleWeeklyReportTask(taskName, options) {
  const {
    enabled,
    dayOfWeek,
    time,
    fallbackDay = 1,
    fallbackTime = '09:00',
    runtimeTaskKey,
    nextTriggerKey,
    triggerFn
  } = options;

  clearCronTask(runtime[runtimeTaskKey]);
  runtime[runtimeTaskKey] = null;
  runtime.nextTriggeredAt[nextTriggerKey] = null;

  if (!enabled) return;

  const parsed = parseClockTime(time, fallbackTime);
  const weeklyDay = normalizeWeekday(dayOfWeek, fallbackDay);
  const cronExpression = `${parsed.minute} ${parsed.hour} * * ${weeklyDay}`;

  if (!cron.validate(cronExpression)) {
    addJob({
      type: 'scheduler',
      status: 'warning',
      message: `${taskName} 配置无效：${formatWeekdayLabel(weeklyDay)} ${parsed.normalized}，已跳过。`
    });
    return;
  }

  runtime[runtimeTaskKey] = cron.schedule(
    cronExpression,
    () => {
      triggerFn().catch((error) => {
        addJob({
          type: taskName,
          status: 'failed',
          message: `${taskName} 执行异常：${error.message}`
        });
      });
    },
    {
      timezone: runtime.timezone
    }
  );

  runtime.nextTriggeredAt[nextTriggerKey] = `${formatWeekdayLabel(weeklyDay)} ${parsed.normalized} (${runtime.timezone})`;
}

function applyHeartbeatConfig(inputHeartbeat, options = {}) {
  const heartbeat = normalizeHeartbeatSettings(inputHeartbeat);

  runtime.heartbeat = heartbeat;
  runtime.timezone = heartbeat.timezone;

  scheduleScanByInterval(heartbeat);
  scheduleWeeklyReportTask('heartbeat_weekly_report', {
    enabled: heartbeat.weeklyReport.enabled,
    dayOfWeek: heartbeat.weeklyReport.dayOfWeek,
    time: heartbeat.weeklyReport.time,
    fallbackDay: 1,
    fallbackTime: '09:00',
    runtimeTaskKey: 'weeklyTask',
    nextTriggerKey: 'weekly',
    triggerFn: () => triggerWeeklyReportTask('heartbeat_weekly_report')
  });
  scheduleDailyReportTask('heartbeat_trend_report', {
    enabled: heartbeat.trendReport.enabled,
    time: heartbeat.trendReport.time,
    fallback: '09:20',
    runtimeTaskKey: 'trendTask',
    nextTriggerKey: 'trend',
    triggerFn: () => triggerTrendReportTask('heartbeat_trend_report')
  });

  if (options.emitJob) {
    const details = [
      heartbeat.scan.enabled
        ? `自动检索每 ${heartbeat.scan.intervalMinutes} 分钟`
        : '自动检索关闭',
      heartbeat.weeklyReport.enabled
        ? `自动周报 每${formatWeekdayLabel(heartbeat.weeklyReport.dayOfWeek)} ${heartbeat.weeklyReport.time}`
        : '自动周报关闭',
      heartbeat.trendReport.enabled
        ? `自动趋势报告 ${heartbeat.trendReport.time}`
        : '自动趋势报告关闭',
      `时区 ${heartbeat.timezone}`
    ];

    addJob({
      type: 'scheduler',
      status: 'success',
      message: `心跳策略已应用：${details.join(' | ')}${options.reason ? ` | ${options.reason}` : ''}`
    });
  }
}

function startScheduler() {
  const heartbeat = getHeartbeatConfig();
  runtime.started = true;
  applyHeartbeatConfig(heartbeat, {
    emitJob: true,
    reason: '系统启动'
  });
}

function updateHeartbeatConfig(nextHeartbeat, options = {}) {
  const operator = options.operator || '系统';
  const normalized = normalizeHeartbeatSettings(nextHeartbeat);
  const persisted = persistHeartbeatConfig(normalized);

  applyHeartbeatConfig(persisted, {
    emitJob: true,
    reason: `由${operator}更新`
  });

  return {
    heartbeat: runtime.heartbeat,
    scheduler: getSchedulerState()
  };
}

function getSchedulerState() {
  return {
    started: runtime.started,
    schedule: runtime.heartbeat.scan.enabled
      ? `每${runtime.heartbeat.scan.intervalMinutes}分钟`
      : '已关闭',
    timezone: runtime.timezone,
    heartbeat: runtime.heartbeat,
    lastTriggeredAt: runtime.lastTriggeredAt,
    nextTriggeredAt: runtime.nextTriggeredAt,
    scanState: getScanState()
  };
}

module.exports = {
  startScheduler,
  getSchedulerState,
  updateHeartbeatConfig
};
