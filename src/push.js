require('dotenv').config();

const { ensureProxySupport } = require('./network');

const PUSH_TIMEOUT_MS = Number(process.env.PUSH_TIMEOUT_MS || 20000);

function normalizeWebhookUrl(url) {
  const text = String(url || '').trim();
  if (!text) return '';
  try {
    const parsed = new URL(text);
    if (!/^https?:$/.test(parsed.protocol)) return '';
    return parsed.toString();
  } catch {
    return '';
  }
}

function formatDate(value) {
  const timestamp = Date.parse(value || '');
  if (Number.isNaN(timestamp)) return '-';
  return new Date(timestamp).toISOString();
}

function reportTypeLabel(type) {
  if (type === 'weekly') return '竞对动态周报';
  if (type === 'trend') return '行业趋势研判报告';
  return type || '-';
}

function extractHighlights(report, maxItems = 3) {
  const structured = report?.structured || {};
  const items = [];

  for (const highlight of structured.keyHighlights || []) {
    const title = String(highlight?.title || '').trim();
    const insight = String(highlight?.insight || '').trim();
    if (!title || !insight) continue;
    items.push({
      title,
      insight,
      citations: Array.isArray(highlight.citations) ? highlight.citations.slice(0, 3) : []
    });
    if (items.length >= maxItems) break;
  }

  if (items.length) return items;

  for (const section of structured.sections || []) {
    for (const point of section?.points || []) {
      const text = typeof point === 'string'
        ? point
        : (point?.text || point?.content || '');
      const normalized = String(text || '').trim();
      if (!normalized) continue;
      items.push({
        title: String(section?.title || '重点事项').trim() || '重点事项',
        insight: normalized,
        citations: Array.isArray(point?.citations) ? point.citations.slice(0, 3) : []
      });
      if (items.length >= maxItems) {
        return items;
      }
    }
  }

  return items;
}

function extractRecommendations(report, maxItems = 3) {
  const rows = Array.isArray(report?.structured?.recommendations)
    ? report.structured.recommendations
    : [];

  return rows
    .map((item) => ({
      priority: String(item?.priority || '中').trim() || '中',
      action: String(item?.action || '').trim(),
      rationale: String(item?.rationale || '').trim()
    }))
    .filter((item) => item.action)
    .slice(0, maxItems);
}

function extractTopSources(report, maxItems = 5) {
  const rows = Array.isArray(report?.sourceSnapshot)
    ? report.sourceSnapshot
    : [];

  return rows.slice(0, maxItems).map((item) => ({
    sourceId: item.sourceId || null,
    title: item.title,
    competitor: item.competitor,
    category: item.category,
    publishedAt: formatDate(item.publishedAt),
    sourceUrl: item.sourceUrl
  }));
}

function buildReportPushPayload(report, options = {}) {
  const trigger = options.trigger || 'manual_push';
  const operator = options.operator || '系统';
  const highlights = extractHighlights(report, 3);
  const recommendations = extractRecommendations(report, 3);

  return {
    channel: 'cmhk_management_brief',
    trigger,
    operator,
    pushedAt: new Date().toISOString(),
    report: {
      id: report.id,
      title: report.title,
      type: report.type,
      typeLabel: reportTypeLabel(report.type),
      createdAt: report.createdAt,
      rangeStart: report.rangeStart,
      rangeEnd: report.rangeEnd,
      sourceCount: report.sourceCount || 0,
      summary: report?.structured?.summary || report.content || ''
    },
    highlights,
    recommendations,
    topSources: extractTopSources(report, 5)
  };
}

async function sendWebhookNotification(webhookUrl, payload, options = {}) {
  ensureProxySupport();

  const target = normalizeWebhookUrl(webhookUrl);
  if (!target) {
    throw new Error('推送地址无效，请配置可访问的 http/https webhook URL。');
  }

  const timeoutMs = Number(options.timeoutMs || PUSH_TIMEOUT_MS);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(target, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers || {})
      },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    const bodyText = await response.text();
    if (!response.ok) {
      throw new Error(`Webhook 返回 ${response.status}: ${bodyText.slice(0, 240)}`);
    }

    return {
      ok: true,
      status: response.status,
      responseText: bodyText.slice(0, 500)
    };
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`推送超时（>${Math.round(timeoutMs / 1000)} 秒）`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function pushReportToManagement(report, pushConfig, options = {}) {
  const payload = buildReportPushPayload(report, options);
  const result = await sendWebhookNotification(pushConfig?.webhookUrl, payload, options);

  return {
    ...result,
    reportId: report.id,
    payloadPreview: {
      title: payload.report.title,
      summary: String(payload.report.summary || '').slice(0, 180),
      highlights: payload.highlights.length,
      recommendations: payload.recommendations.length
    }
  };
}

module.exports = {
  normalizeWebhookUrl,
  buildReportPushPayload,
  sendWebhookNotification,
  pushReportToManagement
};
