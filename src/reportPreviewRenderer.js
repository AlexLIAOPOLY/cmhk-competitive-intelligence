function escapeHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatDate(value) {
  if (!value) return '-';
  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) return '-';
  return new Date(timestamp).toLocaleString('zh-CN', {
    hour12: false,
    timeZone: 'Asia/Hong_Kong'
  });
}

function formatDateRange(start, end) {
  if (!start || !end) return '-';
  return `${formatDate(start)} 至 ${formatDate(end)}`;
}

function reportTypeLabel(type) {
  if (type === 'weekly') return '竞对动态周报';
  if (type === 'trend') return '行业趋势研判报告';
  return type || '-';
}

function parsePriorityClass(priority) {
  if (priority === '高') return 'high';
  if (priority === '低') return 'low';
  return 'mid';
}

function normalizeStructuredReport(report) {
  if (report?.structured && typeof report.structured === 'object') {
    return report.structured;
  }
  return null;
}

function buildSourceMap(report) {
  const rows = Array.isArray(report?.sourceSnapshot) ? report.sourceSnapshot : [];
  const map = new Map();
  for (const row of rows) {
    if (row?.findingId) {
      map.set(row.findingId, row);
    }
  }
  return map;
}

function isHttpUrl(value) {
  return /^https?:\/\//i.test(String(value || '').trim());
}

function renderSafeLink(url, label) {
  const safeUrl = String(url || '').trim();
  const safeLabel = escapeHtml(label || safeUrl);
  if (!isHttpUrl(safeUrl)) {
    return safeLabel;
  }
  return `<a class="table-link" href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener noreferrer">${safeLabel}</a>`;
}

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

function containsChineseText(text) {
  return /[\u4e00-\u9fff]/.test(String(text || ''));
}

function stripAsciiWords(text) {
  return String(text || '')
    .replace(/\b[A-Za-z][A-Za-z0-9&.'’\-]*\b/g, ' ')
    .replace(/\s+/g, ' ')
    .replace(/\s*([，。；：！？])/g, '$1')
    .trim();
}

function toChineseReportText(value, fallback = '') {
  const raw = String(value || '').trim();
  if (!raw) return fallback;
  const replaced = replaceReportEntityAlias(raw);
  const stripped = stripAsciiWords(replaced);
  if (containsChineseText(stripped)) return stripped;
  if (containsChineseText(replaced)) return replaced;
  return fallback;
}

function formatReportSourceTitle(source) {
  const text = toChineseReportText(source?.title || source?.summary || source?.note || '', '');
  if (text) {
    return text.replace(/[。！？!?；;]+$/g, '').trim() || '来源条目';
  }

  const competitor = toChineseReportText(source?.competitor || '', '相关主体');
  const category = toChineseReportText(source?.category || '', '相关类别');
  return `${competitor}${category}来源条目`;
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(String(text || ''));
  html = html.replace(/\[(.+?)\]\((https?:\/\/[^\s)]+)\)/g, (match, label, url) => renderSafeLink(url, label));
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  return html;
}

function normalizeLegacyMarkdown(content) {
  return String(content || '')
    .replace(/\r\n/g, '\n')
    .replace(/^\s*好的，助理[^\n]*\n*/g, '')
    .replace(/^\s*\*{3,}\s*$/gm, '')
    .trim();
}

function parseMarkdownBlocks(content) {
  const lines = normalizeLegacyMarkdown(content).split('\n');
  const blocks = [];

  const isRule = (line) => /^([-*_]\s*){3,}$/.test(line);
  const isHeading = (line) => /^#{1,6}\s+/.test(line);
  const isUnordered = (line) => /^[-*]\s+/.test(line);
  const isOrdered = (line) => /^\d+\.\s+/.test(line);

  for (let i = 0; i < lines.length;) {
    const rawLine = lines[i] || '';
    const line = rawLine.trim();

    if (!line || isRule(line)) {
      i += 1;
      continue;
    }

    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      const level = Math.min(4, headingMatch[1].length + 1);
      blocks.push({
        type: 'heading',
        level,
        text: headingMatch[2].trim()
      });
      i += 1;
      continue;
    }

    if (isUnordered(line)) {
      const items = [];
      while (i < lines.length && isUnordered((lines[i] || '').trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''));
        i += 1;
      }
      blocks.push({ type: 'ul', items });
      continue;
    }

    if (isOrdered(line)) {
      const items = [];
      while (i < lines.length && isOrdered((lines[i] || '').trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ''));
        i += 1;
      }
      blocks.push({ type: 'ol', items });
      continue;
    }

    const paragraphLines = [];
    while (i < lines.length) {
      const current = (lines[i] || '').trim();
      if (!current || isRule(current) || isHeading(current) || isUnordered(current) || isOrdered(current)) {
        break;
      }
      paragraphLines.push(current.replace(/^>\s?/, ''));
      i += 1;
    }

    if (paragraphLines.length) {
      blocks.push({
        type: 'paragraph',
        lines: paragraphLines
      });
      continue;
    }

    i += 1;
  }

  return blocks;
}

function resolveStructuredSources(report, structured, sourceMap) {
  const rows = [];
  const dedup = new Set();
  const refs = Array.isArray(structured?.sourceRefs) ? structured.sourceRefs : [];

  for (const ref of refs) {
    const source = ref?.findingId ? sourceMap.get(ref.findingId) : null;
    if (!source) continue;
    const key = `${source.findingId || ''}|${source.sourceUrl || ''}|${source.title || ''}`;
    if (dedup.has(key)) continue;
    dedup.add(key);
    rows.push(source);
  }

  if (!rows.length) {
    for (const source of report?.sourceSnapshot || []) {
      const key = `${source.findingId || ''}|${source.sourceUrl || ''}|${source.title || ''}`;
      if (dedup.has(key)) continue;
      dedup.add(key);
      rows.push(source);
      if (rows.length >= 20) break;
    }
  }

  return rows;
}

function normalizeReportSourceRows(report, structured, sourceMap) {
  const refs = Array.isArray(structured?.sourceRefs) ? structured.sourceRefs : [];
  const rows = [];
  const usedFindingIds = new Set();
  const usedSourceIds = new Set();

  for (const ref of refs) {
    const findingId = String(ref?.findingId || '').trim();
    if (!findingId || usedFindingIds.has(findingId)) continue;

    const source = sourceMap.get(findingId);
    if (!source) continue;

    let sourceId = String(ref?.sourceId || source.sourceId || '').trim().toUpperCase();
    if (!/^S\d+$/.test(sourceId) || usedSourceIds.has(sourceId)) {
      sourceId = `S${rows.length + 1}`;
    }

    rows.push({
      ...source,
      sourceId,
      note: String(ref?.note || '').trim()
    });
    usedFindingIds.add(findingId);
    usedSourceIds.add(sourceId);
  }

  if (rows.length) return rows;

  return resolveStructuredSources(report, structured, sourceMap).map((source, index) => ({
    ...source,
    sourceId: String(source?.sourceId || '').trim().toUpperCase().match(/^S\d+$/)
      ? String(source.sourceId).trim().toUpperCase()
      : `S${index + 1}`,
    note: ''
  }));
}

function extractSourceIdsFromText(text) {
  const ids = [];
  const cleaned = String(text || '').replace(/\[\s*(S\d+)\s*\]/gi, (match, sourceId) => {
    const normalized = String(sourceId || '').trim().toUpperCase();
    if (/^S\d+$/.test(normalized) && !ids.includes(normalized)) {
      ids.push(normalized);
    }
    return '';
  });

  return {
    text: cleaned.replace(/\s{2,}/g, ' ').trim(),
    citations: ids
  };
}

function normalizeReportPoint(point) {
  if (typeof point === 'string') {
    return extractSourceIdsFromText(point);
  }

  if (!point || typeof point !== 'object') {
    return { text: '', citations: [] };
  }

  const rawText = String(point.text || point.content || '').trim();
  const extracted = extractSourceIdsFromText(rawText);
  const fromField = Array.isArray(point.citations)
    ? point.citations
      .map((id) => String(id || '').trim().toUpperCase())
      .filter((id) => /^S\d+$/.test(id))
    : [];

  return {
    text: extracted.text,
    citations: Array.from(new Set([...fromField, ...extracted.citations]))
  };
}

function renderCitations(citations, sourceIndex) {
  const safe = Array.isArray(citations)
    ? citations
      .map((item) => String(item || '').trim().toUpperCase())
      .filter((item) => /^S\d+$/.test(item) && sourceIndex.has(item))
    : [];

  if (!safe.length) return '';

  return `<span class="report-cites">${safe.map((id) => `<sup class="report-cite">[${escapeHtml(id)}]</sup>`).join('')}</span>`;
}

function renderStructuredDataTables(tables) {
  if (!Array.isArray(tables) || !tables.length) return '';

  const blocks = tables.map((table) => {
    if (!table || typeof table !== 'object') return '';
    const title = String(table.title || '').trim();
    const columns = Array.isArray(table.columns) ? table.columns.map((item) => String(item || '').trim()).filter(Boolean) : [];
    const rows = Array.isArray(table.rows) ? table.rows.filter((row) => Array.isArray(row)) : [];

    if (!title || columns.length < 2 || !rows.length) return '';

    const headHtml = columns.map((column) => `<th>${escapeHtml(column)}</th>`).join('');
    const rowHtml = rows.slice(0, 40).map((row) => {
      const cells = row.slice(0, columns.length).map((cell) => `<td>${escapeHtml(String(cell ?? '-'))}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');

    const note = String(table.note || '').trim();

    return `
      <section class="report-section">
        <h3>${escapeHtml(title)}</h3>
        <div class="table-wrap report-table-wrap">
          <table class="report-data-table">
            <thead><tr>${headHtml}</tr></thead>
            <tbody>${rowHtml}</tbody>
          </table>
        </div>
        ${note ? `<div class="report-table-note">${escapeHtml(note)}</div>` : ''}
      </section>
    `;
  }).filter(Boolean);

  return blocks.join('');
}

function renderStructuredChart(chart) {
  if (!chart || typeof chart !== 'object') return '';

  const title = String(chart.title || '').trim();
  const unit = String(chart.unit || '条').trim() || '条';
  const labels = Array.isArray(chart.labels) ? chart.labels.map((item) => String(item || '').trim()).filter(Boolean) : [];
  const values = Array.isArray(chart.values) ? chart.values.map((item) => Number(item)) : [];

  if (!title || labels.length < 2 || labels.length !== values.length || values.some((item) => !Number.isFinite(item))) {
    return '';
  }

  const max = Math.max(...values, 1);
  const type = String(chart.type || 'bar').toLowerCase();

  if (type === 'line') {
    const itemsHtml = labels.map((label, index) => {
      const height = Math.max(4, Math.round((values[index] / max) * 100));
      return `
        <div class="report-trend-mini__item">
          <div class="report-trend-mini__bar-wrap">
            <div class="report-trend-mini__bar" style="height:${height}%"></div>
          </div>
          <div class="report-trend-mini__label">${escapeHtml(label)}</div>
        </div>
      `;
    }).join('');

    return `
      <div class="report-chart-card">
        <div class="report-chart-card__head">${escapeHtml(title)}<span>${escapeHtml(unit)}</span></div>
        <div class="report-trend-mini">${itemsHtml}</div>
      </div>
    `;
  }

  const rowsHtml = labels.map((label, index) => {
    const width = Math.max(4, Math.round((values[index] / max) * 100));
    return `
      <div class="report-bar-list__row">
        <div class="report-bar-list__label">${escapeHtml(label)}</div>
        <div class="report-bar-list__bar-wrap"><div class="report-bar-list__bar" style="width:${width}%"></div></div>
        <div class="report-bar-list__value">${escapeHtml(String(values[index]))}</div>
      </div>
    `;
  }).join('');

  return `
    <div class="report-chart-card">
      <div class="report-chart-card__head">${escapeHtml(title)}<span>${escapeHtml(unit)}</span></div>
      <div class="report-bar-list">${rowsHtml}</div>
    </div>
  `;
}

function renderStructuredCharts(charts) {
  if (!Array.isArray(charts) || !charts.length) return '';

  const cards = charts.map((chart) => renderStructuredChart(chart)).filter(Boolean);
  if (!cards.length) return '';

  return `
    <section class="report-section">
      <h3>图表分析</h3>
      <div class="report-chart-grid">${cards.join('')}</div>
    </section>
  `;
}

function renderLegacyReportHtml(content) {
  const blocks = parseMarkdownBlocks(content).slice(0, 260);

  if (!blocks.length) {
    return '<div class="subtle-text">报告内容为空。</div>';
  }

  const bodyHtml = blocks.map((block) => {
    if (block.type === 'heading') {
      const tag = `h${block.level}`;
      return `<${tag} class="report-doc__heading">${renderInlineMarkdown(block.text)}</${tag}>`;
    }
    if (block.type === 'ul') {
      const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('');
      return `<ul class="report-list">${items}</ul>`;
    }
    if (block.type === 'ol') {
      const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('');
      return `<ol class="report-list report-list--ordered">${items}</ol>`;
    }

    const paragraph = (block.lines || []).map((line) => renderInlineMarkdown(line)).join('<br>');
    return `<p class="report-paragraph">${paragraph}</p>`;
  }).join('');

  return `<article class="report-doc report-doc--legacy">${bodyHtml}</article>`;
}

function toChineseOrderText(value) {
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

function normalizeWeeklyBulletin(structured) {
  const bulletin = structured?.weeklyBulletin;
  if (!bulletin || typeof bulletin !== 'object') return null;
  const sections = Array.isArray(bulletin.sections) ? bulletin.sections : [];
  if (!sections.length) return null;
  return bulletin;
}

function formatDateOnlyForWeekly(value) {
  const timestamp = Date.parse(String(value || ''));
  if (Number.isNaN(timestamp)) return '-';
  const date = new Date(timestamp);
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function renderWeeklyBulletinReportHtml(report, structured, sourceRows, sourceIndex) {
  const bulletin = normalizeWeeklyBulletin(structured);
  if (!bulletin) {
    return renderLegacyReportHtml(report?.content || '');
  }

  const sectionOrder = ['政治资讯', '行业资讯', '社会资讯', '国际资讯'];
  const rawSections = Array.isArray(bulletin.sections) ? bulletin.sections : [];
  const sectionMap = new Map(rawSections.map((section) => [String(section?.name || ''), section]));
  const orderedSections = sectionOrder.map((name) => {
    const section = sectionMap.get(name);
    return {
      name,
      items: Array.isArray(section?.items) ? section.items : []
    };
  });
  const customSections = rawSections
    .filter((section) => section && !sectionOrder.includes(String(section.name || '')))
    .map((section) => ({
      name: String(section?.name || '行业资讯') || '行业资讯',
      items: Array.isArray(section?.items) ? section.items : []
    }));
  const sections = [...orderedSections, ...customSections];
  const toc = Array.isArray(bulletin.toc)
    ? bulletin.toc
    : sections.flatMap((section) => (section.items || []).map((item) => ({
      index: item.index,
      section: section.name,
      tag: item.tag,
      title: item.title
    })));

  const tocSectionOrder = sectionOrder;
  const tocHtml = tocSectionOrder.map((sectionName) => {
    const rows = toc.filter((item) => item.section === sectionName);
    const itemsHtml = rows.map((item) => `
      <div class="weekly-toc__item">
        ${escapeHtml(String(item.index || '-'))}.【${escapeHtml(item.tag || '行业动态')}】${escapeHtml(toChineseReportText(item.title || '', '未命名动态'))}
      </div>
    `).join('');
    return `
      <div class="weekly-toc__group">
        <div class="weekly-toc__group-title">${escapeHtml(sectionName)}</div>
        ${itemsHtml || '<div class="weekly-toc__empty">（本期暂无更新）</div>'}
      </div>
    `;
  }).join('');

  const sectionsHtml = sections.map((section) => {
    const rows = Array.isArray(section.items) ? section.items : [];
    const narrative = toChineseReportText(section?.narrative || '', '');
    const itemsHtml = rows.length
      ? rows.map((item) => {
        const localOrder = toChineseOrderText(item.localIndex || 1);
        const itemTitle = toChineseReportText(item.title || '', '未命名动态');
        const itemDetail = toChineseReportText(item.detail || '', '暂无可披露事实信息。');
        const citations = Array.isArray(item.sourceIds)
          ? item.sourceIds
            .map((id) => String(id || '').trim().toUpperCase())
            .filter((id) => /^S\d+$/.test(id) && sourceIndex.has(id))
          : [];

        const sourceHtml = citations.length
          ? `<div class="weekly-item__sources">来源：${citations.map((id) => {
            const source = sourceIndex.get(id);
            const title = `${id} 来源链接`;
            if (source?.sourceUrl) {
              return `<span class="weekly-source-chip">${renderSafeLink(source.sourceUrl, title)}</span>`;
            }
            return `<span class="weekly-source-chip">${escapeHtml(title)}</span>`;
          }).join('')}</div>`
          : '';
        const eventTime = item.eventAt || item.publishedAt || null;

        return `
          <article class="weekly-item">
            <h4 class="weekly-item__title">${localOrder}、${escapeHtml(itemTitle)}</h4>
            <p class="weekly-item__detail"><span class="weekly-item__tag-inline">【${escapeHtml(item.tag || '行业动态')}】</span>${escapeHtml(itemDetail)}</p>
            <p class="weekly-item__time">事件时间：${escapeHtml(formatDate(eventTime))}</p>
            ${sourceHtml}
          </article>
        `;
      }).join('')
      : '<article class="weekly-item weekly-item--empty"><p class="weekly-item__detail">（本期暂无更新）</p></article>';

    return `
      <section class="weekly-section">
        <h3 class="weekly-section__title">${escapeHtml(section.name || '行业资讯')}</h3>
        ${narrative ? `<p class="weekly-section__lead">${escapeHtml(narrative)}</p>` : ''}
        ${itemsHtml}
      </section>
    `;
  }).join('');

  const sourceHtml = sourceRows.length
    ? `
      <section class="weekly-section">
        <h3 class="weekly-section__title">来源清单</h3>
        <ul class="report-source-list">
          ${sourceRows.map((source) => `
            <li class="report-source-item">
              <div class="report-source-item__title"><span class="report-source-item__id">${escapeHtml(source.sourceId || '-')}</span>${escapeHtml(formatReportSourceTitle(source))}</div>
              <div class="report-source-item__meta">
                <span>${escapeHtml(toChineseReportText(source.competitor || '', '-'))} / ${escapeHtml(toChineseReportText(source.category || '', '-'))}</span>
                <span>${escapeHtml(formatDate(source.publishedAt))}</span>
                ${source.sourceUrl ? `<span>${renderSafeLink(source.sourceUrl, '来源链接')}</span>` : ''}
              </div>
            </li>
          `).join('')}
        </ul>
      </section>
    `
    : '';

  return `
    <article class="report-doc weekly-doc">
      <div class="weekly-doc__cover-company">${escapeHtml(bulletin.company || '中国移动香港公司')}</div>
      <div class="weekly-doc__cover-dept">${escapeHtml(bulletin.department || '中国移动香港公司战略部')}    ${escapeHtml(formatDateOnlyForWeekly(report?.createdAt))}</div>
      <h2 class="report-doc__title">${escapeHtml(report?.title || '竞对动态周报')}</h2>

      <section class="weekly-section weekly-section--toc">
        <h3 class="weekly-section__title">目 录</h3>
        <div class="weekly-toc">${tocHtml || '<div class="subtle-text">暂无目录条目。</div>'}</div>
      </section>

      ${sectionsHtml}
      ${sourceHtml}
    </article>
  `;
}

function renderStructuredReportHtml(report, structured) {
  const sourceMap = buildSourceMap(report);
  const sourceRows = normalizeReportSourceRows(report, structured, sourceMap);
  const sourceIndex = new Map(sourceRows.map((row) => [row.sourceId, row]));
  const summaryText = toChineseReportText(structured.summary || '', '无执行摘要');

  if (normalizeWeeklyBulletin(structured) && report?.type === 'weekly') {
    return renderWeeklyBulletinReportHtml(report, structured, sourceRows, sourceIndex);
  }

  const highlights = Array.isArray(structured.keyHighlights) ? structured.keyHighlights : [];
  const highlightsHtml = highlights.length
    ? `
      <section class="report-section">
        <h3>关键重点</h3>
        <div class="report-highlight-list">
          ${highlights.map((item) => {
            const title = toChineseReportText(item?.title || '', '重点事项');
            const insight = toChineseReportText(item?.insight || item?.text || '', '');
            if (!title || !insight) return '';
            const point = normalizeReportPoint({
              text: insight,
              citations: item.citations
            });
            return `
              <div class="report-highlight-item">
                <div class="report-highlight-item__title">${escapeHtml(title)}</div>
                <div class="report-highlight-item__text">${escapeHtml(point.text)}${renderCitations(point.citations, sourceIndex)}</div>
              </div>
            `;
          }).filter(Boolean).join('')}
        </div>
      </section>
    `
    : '';

  const sectionsHtml = (structured.sections || []).map((section) => {
    const title = toChineseReportText(section?.title || '', '未命名章节');
    const analysis = toChineseReportText(section?.analysis || '', '');
    const points = (section.points || []).map((pointRaw) => {
      const point = normalizeReportPoint(pointRaw);
      const text = toChineseReportText(point.text, '');
      if (!text) return '';
      return `<li>${escapeHtml(text)}${renderCitations(point.citations, sourceIndex)}</li>`;
    }).filter(Boolean).join('');

    if (!analysis && !points) return '';

    return `
      <section class="report-section">
        <h3>${escapeHtml(title)}</h3>
        ${analysis ? `<p class="report-section__analysis">${escapeHtml(analysis)}</p>` : ''}
        ${points ? `<ul class="report-list">${points}</ul>` : ''}
      </section>
    `;
  }).filter(Boolean).join('');

  const recommendationHtml = (structured.recommendations || []).map((item) => {
    const action = toChineseReportText(item?.action || '', '执行动作');
    const rationale = toChineseReportText(item?.rationale || '', '原始来源未披露具体依据。');
    return `
      <div class="report-rec-row">
        <div class="report-rec-row__head">
          <span>${escapeHtml(action)}</span>
          <span class="report-rec-row__priority ${parsePriorityClass(item.priority)}">${escapeHtml(item.priority || '中')}</span>
        </div>
        <div>${escapeHtml(rationale)}</div>
      </div>
    `;
  }).join('');

  const trackingHtml = (structured.tracking || [])
    .map((item) => toChineseReportText(item, ''))
    .filter(Boolean)
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join('');
  const sourceHtml = sourceRows.map((source) => {
    const sourceMeta = [
      source.competitor ? `竞对：${escapeHtml(toChineseReportText(source.competitor, '-'))}` : '',
      source.category ? `类别：${escapeHtml(toChineseReportText(source.category, '-'))}` : '',
      source.publishedAt ? `时间：${escapeHtml(formatDate(source.publishedAt))}` : ''
    ].filter(Boolean).join(' | ');
    const linkHtml = source.sourceUrl ? renderSafeLink(source.sourceUrl, '来源链接') : '';

    return `
      <li class="report-source-item">
        <div class="report-source-item__title"><span class="report-source-item__id">${escapeHtml(source.sourceId || '-')}</span>${escapeHtml(formatReportSourceTitle(source))}</div>
        ${source.note ? `<div class="report-source-item__note">${escapeHtml(toChineseReportText(source.note, '来源备注'))}</div>` : ''}
        <div class="report-source-item__meta">
          ${sourceMeta ? `<span>${sourceMeta}</span>` : ''}
          ${linkHtml ? `<span>${linkHtml}</span>` : ''}
        </div>
      </li>
    `;
  }).join('');

  const metaRows = [
    ['报告类型', reportTypeLabel(report?.type)],
    ['生成时间', formatDate(report?.createdAt)],
    ['时间窗口', formatDateRange(report?.rangeStart, report?.rangeEnd)],
    ['引用来源', `${report?.sourceCount || sourceRows.length || 0} 条`]
  ];

  const metaHtml = `
    <section class="report-section report-section--compact">
      <div class="table-wrap report-table-wrap">
        <table class="report-meta-table">
          <tbody>
            ${metaRows.map((row) => `<tr><td>${escapeHtml(row[0])}</td><td>${escapeHtml(row[1])}</td></tr>`).join('')}
          </tbody>
        </table>
      </div>
    </section>
  `;

  const tableHtml = renderStructuredDataTables(structured.dataTables || []);
  const chartHtml = renderStructuredCharts(structured.charts || []);

  return [
    '<article class="report-doc">',
    `<h2 class="report-doc__title">${escapeHtml(report?.title || '报告')}</h2>`,
    metaHtml,
    `<div class="report-summary">${escapeHtml(summaryText)}</div>`,
    highlightsHtml,
    tableHtml,
    chartHtml,
    sectionsHtml,
    recommendationHtml
      ? `<section class="report-section"><h3>建议动作</h3><div class="report-recommendations">${recommendationHtml}</div></section>`
      : '',
    trackingHtml
      ? `<section class="report-section"><h3>持续跟踪</h3><ul class="report-list">${trackingHtml}</ul></section>`
      : '',
    sourceHtml
      ? `<section class="report-section"><h3>来源清单</h3><ul class="report-source-list">${sourceHtml}</ul></section>`
      : '',
    '</article>'
  ].filter(Boolean).join('');
}

function renderReportPreviewHtml(report) {
  const structured = normalizeStructuredReport(report);
  if (structured) {
    return renderStructuredReportHtml(report, structured);
  }
  return renderLegacyReportHtml(report?.content || '');
}

module.exports = {
  renderReportPreviewHtml
};
