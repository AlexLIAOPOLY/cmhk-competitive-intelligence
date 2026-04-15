const fs = require('fs');
const path = require('path');
const PDFDocument = require('pdfkit');
const puppeteer = require('puppeteer-core');
const {
  Document,
  Packer,
  Paragraph,
  TextRun,
  Table,
  TableRow,
  TableCell,
  WidthType,
  AlignmentType,
  HeadingLevel,
  BorderStyle
} = require('docx');
const { renderReportPreviewHtml } = require('./reportPreviewRenderer');

const PDF_FONT_PATH = path.join(__dirname, '..', 'assets', 'fonts', 'NotoSansCJKsc-Regular.otf');
const DOCX_FONT = 'Microsoft YaHei';
const COVER_COMPANY = '中国移动香港公司';
const COVER_DEPT = '中国移动香港公司战略部';
const REPORT_STYLESHEET_PATH = path.join(__dirname, '..', 'public', 'styles.css');
const DEFAULT_CHROME_PATHS = [
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  '/Applications/Chromium.app/Contents/MacOS/Chromium',
  '/usr/bin/google-chrome',
  '/usr/bin/chromium-browser',
  '/usr/bin/chromium'
];
let reportStylesheetCache = null;
const REPORT_ENTITY_ALIAS_CN = [
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

function formatDate(value) {
  const ts = Date.parse(String(value || ''));
  if (Number.isNaN(ts)) return '-';
  const date = new Date(ts);
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatDateOnly(value) {
  const ts = Date.parse(String(value || ''));
  if (Number.isNaN(ts)) return '-';
  const date = new Date(ts);
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function formatRange(start, end) {
  if (!start || !end) return '-';
  return `${formatDate(start)} 至 ${formatDate(end)}`;
}

function getReportStylesheet() {
  if (typeof reportStylesheetCache === 'string') {
    return reportStylesheetCache;
  }
  reportStylesheetCache = fs.readFileSync(REPORT_STYLESHEET_PATH, 'utf8');
  return reportStylesheetCache;
}

function resolveChromeExecutablePath() {
  const envCandidates = [
    process.env.CHROME_PATH,
    process.env.GOOGLE_CHROME_PATH,
    process.env.PUPPETEER_EXECUTABLE_PATH
  ]
    .map((value) => String(value || '').trim())
    .filter(Boolean);

  const candidates = [...envCandidates, ...DEFAULT_CHROME_PATHS];
  for (const candidate of candidates) {
    try {
      if (fs.existsSync(candidate)) {
        return candidate;
      }
    } catch {
      continue;
    }
  }

  return '';
}

function buildReportPrintHtml(report) {
  const reportHtml = renderReportPreviewHtml(report);
  const stylesheet = getReportStylesheet();

  return `<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>${normalizeText(report?.title || '报告')}</title>
    <style>
${stylesheet}

@page {
  size: A4;
  margin: 11mm 10mm 12mm;
}

html, body {
  margin: 0;
  padding: 0;
  background: #ffffff !important;
}

body::before,
body::after {
  display: none !important;
}

.report-print-root {
  margin: 0;
  padding: 0;
}

.report-content {
  margin: 0 !important;
  border: none !important;
  border-radius: 0 !important;
  box-shadow: none !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: visible !important;
  padding: 0 !important;
  background: #ffffff !important;
  animation: none !important;
  scrollbar-width: none !important;
}

* {
  animation: none !important;
  transition: none !important;
}
    </style>
  </head>
  <body>
    <main class="report-print-root">
      <section class="report-content">
        ${reportHtml}
      </section>
    </main>
  </body>
</html>`;
}

function normalizeText(value, fallback = '-') {
  const text = String(value || '').trim();
  return text || fallback;
}

function escapeRegExp(value) {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function replaceReportEntityAlias(text) {
  let next = String(text || '');
  for (const [alias, cn] of REPORT_ENTITY_ALIAS_CN) {
    const raw = String(alias || '').trim();
    if (!raw) continue;
    next = next.replace(new RegExp(escapeRegExp(raw), 'gi'), cn);
  }
  return next;
}

function containsChineseText(value) {
  return /[\u4e00-\u9fff]/.test(String(value || ''));
}

function stripAsciiWords(text) {
  return String(text || '')
    .replace(/\b[A-Za-z][A-Za-z0-9&.'’\-]*\b/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。；：！？])/g, '$1')
    .trim();
}

function normalizeChineseReportText(value, fallback = '-') {
  const raw = String(value || '').trim();
  if (!raw) return fallback;
  const replaced = replaceReportEntityAlias(raw);
  const stripped = stripAsciiWords(replaced);
  if (containsChineseText(stripped)) return stripped;
  if (containsChineseText(replaced)) return replaced;
  return fallback;
}

function normalizeSourceTitleForReport(source) {
  const fromTitle = normalizeChineseReportText(source?.title || '', '');
  if (fromTitle && fromTitle !== '-') return fromTitle;
  const competitor = normalizeChineseReportText(source?.competitor || '', '相关主体');
  const category = normalizeChineseReportText(source?.category || '', '相关类别');
  return `${competitor}${category}来源条目`;
}

function normalizeStructured(report) {
  return report?.structured && typeof report.structured === 'object'
    ? report.structured
    : null;
}

function normalizeWeeklyBulletin(structured) {
  const bulletin = structured?.weeklyBulletin;
  if (!bulletin || typeof bulletin !== 'object') return null;
  if (!Array.isArray(bulletin.sections) || !bulletin.sections.length) return null;
  return bulletin;
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

function normalizeSourceRows(report, structured) {
  const rows = Array.isArray(report?.sourceSnapshot) ? report.sourceSnapshot : [];
  const rowMap = new Map(rows.map((row) => [String(row.findingId || ''), row]));

  const refs = Array.isArray(structured?.sourceRefs) ? structured.sourceRefs : [];
  const used = new Set();
  const result = [];

  for (const ref of refs) {
    const findingId = String(ref?.findingId || '');
    const source = rowMap.get(findingId);
    if (!source) continue;
    const key = `${findingId}|${source.sourceUrl || ''}`;
    if (used.has(key)) continue;
    used.add(key);
    result.push({
      sourceId: String(ref?.sourceId || source.sourceId || '').trim().toUpperCase() || `S${result.length + 1}`,
      title: normalizeSourceTitleForReport(source),
      competitor: normalizeChineseReportText(source.competitor || '', source.competitor || '-'),
      category: normalizeChineseReportText(source.category || '', source.category || '-'),
      sourceUrl: source.sourceUrl || '',
      publishedAt: source.publishedAt || '',
      note: ref?.note || ''
    });
  }

  if (result.length) return result;

  return rows.slice(0, 40).map((row, index) => ({
    sourceId: String(row?.sourceId || '').trim().toUpperCase() || `S${index + 1}`,
    title: normalizeSourceTitleForReport(row),
    competitor: normalizeChineseReportText(row?.competitor || '', row?.competitor || '-'),
    category: normalizeChineseReportText(row?.category || '', row?.category || '-'),
    sourceUrl: row?.sourceUrl || '',
    publishedAt: row?.publishedAt || '',
    note: ''
  }));
}

function buildExportModel(report) {
  const structured = normalizeStructured(report) || {};
  const sourceRows = normalizeSourceRows(report, structured);
  const weeklyBulletin = normalizeWeeklyBulletin(structured);

  return {
    title: normalizeText(report?.title || '报告'),
    reportType: normalizeText(report?.type || structured?.reportMeta?.reportType || '-'),
    createdAt: report?.createdAt,
    rangeStart: report?.rangeStart,
    rangeEnd: report?.rangeEnd,
    summary: normalizeText(structured.summary || report?.content || '无执行摘要'),
    keyHighlights: Array.isArray(structured.keyHighlights) ? structured.keyHighlights : [],
    sections: Array.isArray(structured.sections) ? structured.sections : [],
    dataTables: Array.isArray(structured.dataTables) ? structured.dataTables : [],
    charts: Array.isArray(structured.charts) ? structured.charts : [],
    recommendations: Array.isArray(structured.recommendations) ? structured.recommendations : [],
    tracking: Array.isArray(structured.tracking) ? structured.tracking : [],
    sources: sourceRows,
    weeklyBulletin
  };
}

function pText(text, options = {}) {
  const {
    bold = false,
    size = 22,
    align = AlignmentType.LEFT,
    spacingAfter = 100,
    indent = 0
  } = options;

  return new Paragraph({
    alignment: align,
    spacing: { after: spacingAfter },
    indent: indent ? { left: indent } : undefined,
    children: [
      new TextRun({
        text: String(text || ''),
        bold,
        size,
        font: DOCX_FONT
      })
    ]
  });
}

function heading(text, level = HeadingLevel.HEADING_2) {
  return new Paragraph({
    heading: level,
    spacing: { before: 180, after: 100 },
    children: [
      new TextRun({
        text: String(text || ''),
        bold: true,
        size: 26,
        font: DOCX_FONT
      })
    ]
  });
}

function toDocxTable(table) {
  const columns = Array.isArray(table?.columns) ? table.columns.map((item) => String(item || '')) : [];
  const rows = Array.isArray(table?.rows) ? table.rows.filter((row) => Array.isArray(row)) : [];
  if (!columns.length || !rows.length) return null;

  const headerRow = new TableRow({
    children: columns.map((column) => new TableCell({
      children: [pText(column, { bold: true, size: 20, spacingAfter: 0 })],
      shading: { fill: 'EDF3FB' }
    }))
  });

  const bodyRows = rows.slice(0, 40).map((row) => {
    const cells = columns.map((_, index) => String(row[index] ?? '-'));
    return new TableRow({
      children: cells.map((cell) => new TableCell({
        children: [pText(cell, { size: 20, spacingAfter: 0 })]
      }))
    });
  });

  return new Table({
    width: { size: 100, type: WidthType.PERCENTAGE },
    borders: {
      top: { style: BorderStyle.SINGLE, color: 'CBD7E4', size: 1 },
      bottom: { style: BorderStyle.SINGLE, color: 'CBD7E4', size: 1 },
      left: { style: BorderStyle.SINGLE, color: 'CBD7E4', size: 1 },
      right: { style: BorderStyle.SINGLE, color: 'CBD7E4', size: 1 },
      insideHorizontal: { style: BorderStyle.SINGLE, color: 'DFE7F0', size: 1 },
      insideVertical: { style: BorderStyle.SINGLE, color: 'DFE7F0', size: 1 }
    },
    rows: [headerRow, ...bodyRows]
  });
}

function buildWeeklyTocRows(weeklyBulletin) {
  if (Array.isArray(weeklyBulletin?.toc) && weeklyBulletin.toc.length) {
    return weeklyBulletin.toc;
  }

  const rows = [];
  for (const section of weeklyBulletin?.sections || []) {
    for (const item of section.items || []) {
      rows.push({
        index: item.index,
        section: section.name,
        tag: item.tag,
        title: normalizeChineseReportText(item.title, '未命名动态')
      });
    }
  }
  return rows;
}

function exportWeeklyDocx(model) {
  const bulletin = model.weeklyBulletin;
  const tocRows = buildWeeklyTocRows(bulletin);
  const tocSectionOrder = ['政治资讯', '行业资讯', '社会资讯', '国际资讯'];
  const sourceMap = new Map((model.sources || []).map((row) => [String(row.sourceId || '').toUpperCase(), row]));

  const children = [];
  children.push(pText(bulletin.company || COVER_COMPANY, { bold: true, size: 34, spacingAfter: 180, align: AlignmentType.CENTER }));
  children.push(pText(`${bulletin.department || COVER_DEPT}    ${formatDateOnly(model.createdAt)}`, { size: 22, spacingAfter: 260, align: AlignmentType.CENTER }));
  children.push(pText(model.title, { bold: true, size: 32, spacingAfter: 220, align: AlignmentType.CENTER }));

  children.push(heading('目 录', HeadingLevel.HEADING_1));
  tocSectionOrder.forEach((sectionName) => {
    const rows = tocRows.filter((item) => item.section === sectionName);
    children.push(pText(sectionName, { bold: true, size: 24, spacingAfter: 60 }));
    if (rows.length) {
      rows.forEach((item) => {
        children.push(pText(`${normalizeText(item.index)}.【${normalizeText(item.tag, '行业动态')}】${normalizeChineseReportText(item.title, '未命名动态')}`, {
          size: 22,
          spacingAfter: 40,
          indent: 200
        }));
      });
    } else {
      children.push(pText('（本期暂无更新）', {
        size: 21,
        spacingAfter: 36,
        indent: 200
      }));
    }
    children.push(pText('', { size: 10, spacingAfter: 20 }));
  });

  for (const section of bulletin.sections || []) {
    const items = Array.isArray(section.items) ? section.items : [];
    children.push(heading(normalizeChineseReportText(section.name, '行业资讯'), HeadingLevel.HEADING_1));
    if (section.narrative) {
      children.push(pText(normalizeChineseReportText(section.narrative, '-'), { size: 21, spacingAfter: 55 }));
    }
    if (!items.length) {
      children.push(pText('（本期暂无更新）', { size: 21, spacingAfter: 60 }));
      continue;
    }
    for (const item of items) {
      const localIndex = toChineseOrder(item.localIndex || 1);
      children.push(pText(`${localIndex}、${normalizeChineseReportText(item.title, '未命名动态')}`, { bold: true, size: 22, spacingAfter: 40 }));
      children.push(pText(`【${normalizeText(item.tag, '行业动态')}】${normalizeChineseReportText(item.detail, '暂无可披露事实信息。')}`, { size: 22, spacingAfter: 50 }));
      children.push(pText(`事件时间：${formatDate(item.eventAt || item.publishedAt)}`, { size: 20, spacingAfter: 50 }));

      const sourceIds = Array.isArray(item.sourceIds)
        ? item.sourceIds.map((id) => String(id || '').trim().toUpperCase()).filter(Boolean)
        : [];
      if (sourceIds.length) {
        const sourceLine = sourceIds.join('、');
        children.push(pText(`来源：${sourceLine}`, { size: 20, spacingAfter: 70 }));
      }
    }
  }

  if (model.sources.length) {
    children.push(heading('来源清单', HeadingLevel.HEADING_1));
    const sourceTable = toDocxTable({
      columns: ['来源ID', '栏目', '标题', '发布时间', '链接'],
      rows: model.sources.slice(0, 60).map((row) => [
        normalizeText(row.sourceId),
        `${normalizeChineseReportText(row.competitor, '-')}/${normalizeChineseReportText(row.category, '-')}`,
        normalizeSourceTitleForReport(row),
        normalizeText(formatDate(row.publishedAt)),
        normalizeText(row.sourceUrl)
      ])
    });
    if (sourceTable) {
      children.push(sourceTable);
    }
  }

  return new Document({
    sections: [{ children }]
  });
}

async function exportReportAsDocx(report) {
  const model = buildExportModel(report);

  if (model.weeklyBulletin && model.reportType === 'weekly') {
    const weeklyDoc = exportWeeklyDocx(model);
    return Packer.toBuffer(weeklyDoc);
  }

  const tocItems = [
    ...model.sections.map((section) => section.title),
    ...(model.dataTables || []).map((table) => table.title),
    '建议动作',
    '持续跟踪',
    '来源清单'
  ].filter(Boolean);

  const children = [];
  children.push(pText(COVER_COMPANY, { bold: true, size: 34, spacingAfter: 180, align: AlignmentType.CENTER }));
  children.push(pText(`${COVER_DEPT}    ${formatDateOnly(model.createdAt)}`, { size: 22, spacingAfter: 260, align: AlignmentType.CENTER }));
  children.push(pText(model.title, { bold: true, size: 32, spacingAfter: 220, align: AlignmentType.CENTER }));
  children.push(heading('目录', HeadingLevel.HEADING_1));
  tocItems.forEach((item, index) => {
    children.push(pText(`${index + 1}. ${item}`, { size: 22, spacingAfter: 50 }));
  });

  children.push(heading('报告概览', HeadingLevel.HEADING_1));
  children.push(pText(`报告类型：${model.reportType}`, { size: 22, spacingAfter: 40 }));
  children.push(pText(`生成时间：${formatDate(model.createdAt)}`, { size: 22, spacingAfter: 40 }));
  children.push(pText(`时间窗口：${formatRange(model.rangeStart, model.rangeEnd)}`, { size: 22, spacingAfter: 120 }));
  children.push(heading('执行摘要', HeadingLevel.HEADING_2));
  children.push(pText(normalizeChineseReportText(model.summary, '无执行摘要。'), { size: 22, spacingAfter: 120 }));

  if (model.keyHighlights.length) {
    children.push(heading('关键重点', HeadingLevel.HEADING_2));
    model.keyHighlights.slice(0, 10).forEach((row, index) => {
      const cites = Array.isArray(row?.citations) && row.citations.length ? `（${row.citations.join('、')}）` : '';
      children.push(pText(`${index + 1}. ${normalizeChineseReportText(row?.title, `重点事项${index + 1}`)}：${normalizeChineseReportText(row?.insight, '原始来源未披露具体数值。')}${cites}`, { size: 22, spacingAfter: 70 }));
    });
  }

  model.sections.forEach((section) => {
    children.push(heading(normalizeChineseReportText(section.title, '未命名章节'), HeadingLevel.HEADING_2));
    if (section.analysis) {
      children.push(pText(normalizeChineseReportText(section.analysis, '原始来源未披露具体数值。'), { size: 22, spacingAfter: 70 }));
    }
    (section.points || []).slice(0, 20).forEach((point) => {
      const text = typeof point === 'string' ? point : point?.text;
      const cites = Array.isArray(point?.citations) && point.citations.length ? `（${point.citations.join('、')}）` : '';
      children.push(pText(`• ${normalizeChineseReportText(text, '原始来源未披露具体数值。')}${cites}`, { size: 22, spacingAfter: 50 }));
    });
  });

  model.dataTables.forEach((table) => {
    children.push(heading(table.title || '数据表', HeadingLevel.HEADING_2));
    const tableNode = toDocxTable(table);
    if (tableNode) {
      children.push(tableNode);
    }
  });

  if (model.charts.length) {
    children.push(heading('图表数据', HeadingLevel.HEADING_2));
    model.charts.forEach((chart, index) => {
      const labels = Array.isArray(chart.labels) ? chart.labels : [];
      const values = Array.isArray(chart.values) ? chart.values : [];
      children.push(pText(`${index + 1}. ${normalizeChineseReportText(chart.title, '图表')}（${normalizeText(chart.type)} | 单位：${normalizeChineseReportText(chart.unit, '条')}）`, { bold: true, size: 21, spacingAfter: 60 }));
      labels.slice(0, 30).forEach((label, idx) => {
        children.push(pText(`   - ${normalizeChineseReportText(label, '维度')}：${normalizeText(values[idx], '-')}`, { size: 21, spacingAfter: 20 }));
      });
    });
  }

  if (model.recommendations.length) {
    children.push(heading('建议动作', HeadingLevel.HEADING_2));
    model.recommendations.forEach((row, index) => {
      children.push(pText(`${index + 1}. [${normalizeText(row?.priority, '中')}] ${normalizeChineseReportText(row?.action, '执行动作')}。依据：${normalizeChineseReportText(row?.rationale, '原始来源未披露具体依据。')}`, { size: 22, spacingAfter: 70 }));
    });
  }

  if (model.tracking.length) {
    children.push(heading('持续跟踪', HeadingLevel.HEADING_2));
    model.tracking.forEach((row) => {
      children.push(pText(`• ${normalizeChineseReportText(row, '持续跟踪项')}`, { size: 22, spacingAfter: 45 }));
    });
  }

  if (model.sources.length) {
    children.push(heading('来源清单', HeadingLevel.HEADING_2));
    const sourceTable = toDocxTable({
      columns: ['来源ID', '竞对', '类别', '标题', '发布时间', '链接'],
      rows: model.sources.slice(0, 50).map((row) => [
        normalizeText(row.sourceId),
        normalizeText(row.competitor),
        normalizeText(row.category),
        normalizeText(row.title),
        normalizeText(formatDate(row.publishedAt)),
        normalizeText(row.sourceUrl)
      ])
    });
    if (sourceTable) {
      children.push(sourceTable);
    }
  }

  const doc = new Document({
    sections: [{ children }]
  });

  return Packer.toBuffer(doc);
}

function ensurePdfSpace(doc, requiredHeight = 28) {
  const bottom = doc.page.height - doc.page.margins.bottom;
  if (doc.y + requiredHeight <= bottom) return;
  doc.addPage();
}

function pdfHeading(doc, text, level = 2) {
  const size = level === 1 ? 18 : 14;
  ensurePdfSpace(doc, 34);
  doc.fontSize(size).fillColor('#1e3552').text(String(text || ''), { lineGap: 3 });
  doc.moveDown(0.4);
}

function pdfParagraph(doc, text, options = {}) {
  const size = Number(options.size || 10.5);
  const color = options.color || '#1f2f44';
  ensurePdfSpace(doc, 24);
  doc.fontSize(size).fillColor(color).text(String(text || ''), {
    lineGap: 2,
    paragraphGap: Number(options.paragraphGap || 6),
    indent: Number(options.indent || 0)
  });
}

function truncateCell(value, maxLength = 90) {
  const text = String(value ?? '');
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function pdfTable(doc, table) {
  const columns = Array.isArray(table?.columns) ? table.columns.map((item) => String(item || '')) : [];
  const rows = Array.isArray(table?.rows) ? table.rows.filter((row) => Array.isArray(row)).slice(0, 30) : [];
  if (!columns.length || !rows.length) return;

  const pageWidth = doc.page.width - doc.page.margins.left - doc.page.margins.right;
  const colWidth = pageWidth / columns.length;

  const drawRow = (cells, header = false) => {
    const safeCells = cells.map((cell) => truncateCell(cell, header ? 30 : 90));
    let rowHeight = 24;
    safeCells.forEach((cell) => {
      const h = doc.heightOfString(String(cell || ''), { width: colWidth - 8 });
      rowHeight = Math.max(rowHeight, h + 10);
    });

    ensurePdfSpace(doc, rowHeight + 2);
    const top = doc.y;
    safeCells.forEach((cell, idx) => {
      const x = doc.page.margins.left + idx * colWidth;
      doc.save();
      if (header) {
        doc.rect(x, top, colWidth, rowHeight).fillAndStroke('#EDF3FB', '#C9D5E3');
      } else {
        doc.rect(x, top, colWidth, rowHeight).stroke('#DDE6F0');
      }
      doc.restore();
      doc.fontSize(header ? 10.2 : 9.8).fillColor('#1F3148').text(String(cell || '-'), x + 4, top + 4, {
        width: colWidth - 8,
        height: rowHeight - 8
      });
    });
    doc.y = top + rowHeight;
  };

  drawRow(columns, true);
  rows.forEach((row) => {
    const safeRow = columns.map((_, index) => String(row[index] ?? '-'));
    drawRow(safeRow, false);
  });

  doc.moveDown(0.5);
}

function buildWeeklySectionsForExport(bulletin) {
  const order = ['政治资讯', '行业资讯', '社会资讯', '国际资讯'];
  const raw = Array.isArray(bulletin?.sections) ? bulletin.sections : [];
  const map = new Map(raw.map((section) => [String(section?.name || ''), section]));
  const ordered = order.map((name) => ({
    name: normalizeChineseReportText(name, '行业资讯'),
    narrative: normalizeChineseReportText(map.get(name)?.narrative, ''),
    items: Array.isArray(map.get(name)?.items) ? map.get(name).items : []
  }));
  const custom = raw
    .filter((section) => section && !order.includes(String(section.name || '')))
    .map((section) => ({
      name: normalizeChineseReportText(section.name, '行业资讯'),
      narrative: normalizeChineseReportText(section?.narrative, ''),
      items: Array.isArray(section.items) ? section.items : []
    }));
  return [...ordered, ...custom];
}

function renderWeeklyPdf(doc, model) {
  const bulletin = model.weeklyBulletin;
  const sections = buildWeeklySectionsForExport(bulletin);
  const tocRows = buildWeeklyTocRows(bulletin);
  const tocSectionOrder = ['政治资讯', '行业资讯', '社会资讯', '国际资讯'];
  const sourceMap = new Map((model.sources || []).map((row) => [String(row.sourceId || '').toUpperCase(), row]));

  doc.fontSize(21).fillColor('#183A63').text(bulletin.company || COVER_COMPANY, { align: 'center' });
  doc.moveDown(0.4);
  doc.fontSize(12.5).fillColor('#365271').text(`${bulletin.department || COVER_DEPT}    ${formatDateOnly(model.createdAt)}`, { align: 'center' });
  doc.moveDown(0.8);
  doc.fontSize(18).fillColor('#132E4E').text(model.title, { align: 'center' });
  doc.moveDown(0.8);

  pdfHeading(doc, '目 录', 1);
  for (const sectionName of tocSectionOrder) {
    pdfParagraph(doc, sectionName, { size: 11.5, color: '#1f3551', paragraphGap: 2 });
    const rows = tocRows.filter((item) => item.section === sectionName);
    if (!rows.length) {
      pdfParagraph(doc, '（本期暂无更新）', { size: 10.2, color: '#607289', paragraphGap: 3, indent: 10 });
      continue;
    }
    rows.forEach((item) => {
      pdfParagraph(doc, `${normalizeText(item.index)}.【${normalizeText(item.tag, '行业动态')}】${normalizeChineseReportText(item.title, '未命名动态')}`, {
        size: 10.3,
        paragraphGap: 2,
        indent: 10
      });
    });
    doc.moveDown(0.1);
  }

  for (const section of sections) {
    pdfHeading(doc, section.name, 1);
    const rows = Array.isArray(section.items) ? section.items : [];
    if (section.narrative) {
      pdfParagraph(doc, normalizeChineseReportText(section.narrative, '-'), {
        size: 10.6,
        color: '#314a68',
        paragraphGap: 4
      });
    }
    if (!rows.length) {
      pdfParagraph(doc, '（本期暂无更新）', { size: 10.4, color: '#607289', paragraphGap: 5 });
      continue;
    }

    for (const item of rows) {
      pdfParagraph(doc, `${toChineseOrder(item.localIndex || 1)}、${normalizeChineseReportText(item.title, '未命名动态')}`, {
        size: 11,
        color: '#1f3551',
        paragraphGap: 2
      });
      pdfParagraph(doc, `【${normalizeText(item.tag, '行业动态')}】${normalizeChineseReportText(item.detail, '暂无可披露事实信息。')}`, {
        size: 10.5,
        paragraphGap: 3
      });
      pdfParagraph(doc, `事件时间：${formatDate(item.eventAt || item.publishedAt)}`, {
        size: 9.8,
        color: '#4c627b',
        paragraphGap: 3
      });

      const sourceIds = Array.isArray(item.sourceIds)
        ? item.sourceIds.map((id) => String(id || '').trim().toUpperCase()).filter(Boolean)
        : [];
      if (sourceIds.length) {
        const sourceLine = sourceIds.join('、');
        pdfParagraph(doc, `来源：${sourceLine}`, {
          size: 9.8,
          color: '#4c627b',
          paragraphGap: 6
        });
      }
    }
  }

  if (model.sources.length) {
    pdfHeading(doc, '来源清单', 1);
    pdfTable(doc, {
      columns: ['来源ID', '栏目', '标题', '发布时间'],
      rows: model.sources.slice(0, 60).map((row) => [
        normalizeText(row.sourceId),
        `${normalizeChineseReportText(row.competitor, '-')}/${normalizeChineseReportText(row.category, '-')}`,
        normalizeSourceTitleForReport(row),
        normalizeText(formatDate(row.publishedAt))
      ])
    });
  }
}

async function exportReportAsPdf(report) {
  const model = buildExportModel(report);

  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({
      size: 'A4',
      margin: 45
    });
    const chunks = [];
    doc.on('data', (chunk) => chunks.push(chunk));
    doc.on('end', () => resolve(Buffer.concat(chunks)));
    doc.on('error', reject);

    doc.font(PDF_FONT_PATH);

    if (model.weeklyBulletin && model.reportType === 'weekly') {
      renderWeeklyPdf(doc, model);
      doc.end();
      return;
    }

    doc.fontSize(21).fillColor('#183A63').text(COVER_COMPANY, { align: 'center' });
    doc.moveDown(0.4);
    doc.fontSize(12.5).fillColor('#365271').text(`${COVER_DEPT}    ${formatDateOnly(model.createdAt)}`, { align: 'center' });
    doc.moveDown(0.8);
    doc.fontSize(18).fillColor('#132E4E').text(model.title, { align: 'center' });
    doc.moveDown(0.8);

    pdfHeading(doc, '目录', 1);
    const tocItems = [
      '报告概览',
      '执行摘要',
      ...(model.sections || []).map((item) => item.title).filter(Boolean),
      ...((model.dataTables || []).map((item) => item.title).filter(Boolean)),
      '建议动作',
      '持续跟踪',
      '来源清单'
    ];
    tocItems.forEach((row, index) => {
      pdfParagraph(doc, `${index + 1}. ${row}`, { size: 10.5, paragraphGap: 2 });
    });

    pdfHeading(doc, '报告概览', 1);
    pdfParagraph(doc, `报告类型：${model.reportType}`, { size: 11, paragraphGap: 2 });
    pdfParagraph(doc, `生成时间：${formatDate(model.createdAt)}`, { size: 11, paragraphGap: 2 });
    pdfParagraph(doc, `时间窗口：${formatRange(model.rangeStart, model.rangeEnd)}`, { size: 11, paragraphGap: 6 });

    pdfHeading(doc, '执行摘要', 2);
    pdfParagraph(doc, normalizeChineseReportText(model.summary, '无执行摘要。'), { size: 11 });

    if (model.keyHighlights.length) {
      pdfHeading(doc, '关键重点', 2);
      model.keyHighlights.slice(0, 10).forEach((row, index) => {
        const cites = Array.isArray(row?.citations) && row.citations.length ? `（${row.citations.join('、')}）` : '';
        pdfParagraph(doc, `${index + 1}. ${normalizeChineseReportText(row?.title, `重点事项${index + 1}`)}：${normalizeChineseReportText(row?.insight, '原始来源未披露具体数值。')}${cites}`, { size: 10.6, paragraphGap: 4 });
      });
    }

    (model.sections || []).forEach((section) => {
      pdfHeading(doc, normalizeChineseReportText(section.title, '未命名章节'), 2);
      if (section.analysis) {
        pdfParagraph(doc, normalizeChineseReportText(section.analysis, '原始来源未披露具体数值。'), { size: 10.8, paragraphGap: 5 });
      }
      (section.points || []).slice(0, 20).forEach((point) => {
        const text = typeof point === 'string' ? point : point?.text;
        const cites = Array.isArray(point?.citations) && point.citations.length ? `（${point.citations.join('、')}）` : '';
        pdfParagraph(doc, `• ${normalizeChineseReportText(text, '原始来源未披露具体数值。')}${cites}`, { size: 10.3, paragraphGap: 3, indent: 10 });
      });
    });

    (model.dataTables || []).forEach((table) => {
      pdfHeading(doc, table.title || '数据表', 2);
      pdfTable(doc, table);
    });

    if (model.charts.length) {
      pdfHeading(doc, '图表数据', 2);
      model.charts.forEach((chart, index) => {
        pdfParagraph(doc, `${index + 1}. ${normalizeChineseReportText(chart.title, '图表')}（${normalizeText(chart.type)} | 单位：${normalizeChineseReportText(chart.unit, '条')}）`, { size: 10.8, paragraphGap: 2 });
        const labels = Array.isArray(chart.labels) ? chart.labels : [];
        const values = Array.isArray(chart.values) ? chart.values : [];
        const rows = labels.slice(0, 25).map((label, idx) => [normalizeChineseReportText(label, '维度'), String(values[idx] ?? '-')]);
        pdfTable(doc, {
          columns: ['维度', '数值'],
          rows
        });
      });
    }

    if (model.recommendations.length) {
      pdfHeading(doc, '建议动作', 2);
      model.recommendations.forEach((row, index) => {
        pdfParagraph(doc, `${index + 1}. [${normalizeText(row?.priority, '中')}] ${normalizeChineseReportText(row?.action, '执行动作')}。依据：${normalizeChineseReportText(row?.rationale, '原始来源未披露具体依据。')}`, {
          size: 10.5,
          paragraphGap: 4
        });
      });
    }

    if (model.tracking.length) {
      pdfHeading(doc, '持续跟踪', 2);
      model.tracking.forEach((row) => {
        pdfParagraph(doc, `• ${normalizeChineseReportText(row, '持续跟踪项')}`, { size: 10.3, paragraphGap: 3, indent: 10 });
      });
    }

    if (model.sources.length) {
      pdfHeading(doc, '来源清单', 2);
      pdfTable(doc, {
        columns: ['来源ID', '竞对', '类别', '标题', '发布时间'],
        rows: model.sources.slice(0, 50).map((row) => [
          normalizeText(row.sourceId),
          normalizeText(row.competitor),
          normalizeText(row.category),
          normalizeText(row.title),
          normalizeText(formatDate(row.publishedAt))
        ])
      });
    }

    doc.end();
  });
}

async function exportReportAsPdfByBrowser(report) {
  const executablePath = resolveChromeExecutablePath();
  if (!executablePath) {
    throw new Error('未找到可用浏览器，无法进行高保真 PDF 导出。请安装 Chrome/Edge 或设置 CHROME_PATH。');
  }

  const browser = await puppeteer.launch({
    executablePath,
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--font-render-hinting=medium'
    ]
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({
      width: 1280,
      height: 1960,
      deviceScaleFactor: 2
    });

    const html = buildReportPrintHtml(report);
    await page.setContent(html, {
      waitUntil: 'domcontentloaded',
      timeout: 120000
    });
    await page.emulateMediaType('screen');
    await page.evaluate(async () => {
      if (document.fonts && document.fonts.ready) {
        await document.fonts.ready;
      }
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    });

    const pdfBytes = await page.pdf({
      printBackground: true,
      preferCSSPageSize: true
    });
    if (Buffer.isBuffer(pdfBytes)) {
      return pdfBytes;
    }
    return Buffer.from(pdfBytes);
  } finally {
    await browser.close();
  }
}

module.exports = {
  exportReportAsDocx,
  exportReportAsPdf: exportReportAsPdfByBrowser
};
