const API_BASE = '/api';
const CONFIG_PANEL_COLLAPSED_KEY = 'cmhk_config_panel_collapsed';

const state = {
  config: null,
  status: null,
  metrics: null,
  heartbeat: null,
  reports: [],
  selectedReportId: null,
  activeTab: 'dashboard',
  editConfig: [],
  editorOpenCompetitor: 0,
  ui: {
    configPanelCollapsed: true
  },
  refresh: {
    inFlight: false,
    timerId: null,
    intervalMs: 20000,
    lastAt: null
  },
  scanWatch: {
    timerId: null,
    inFlight: false
  },
  findingsWatch: {
    timerId: null,
    inFlight: false,
    intervalMs: 0
  },
  findingsFilters: {
    selectedCompetitors: [],
    competitorPanelOpen: false
  },
  qaStream: {
    inFlight: false,
    reportId: null,
    question: '',
    answer: '',
    startedAt: null
  },
  board: {
    days: 180,
    data: null,
    selectedCompetitors: []
  }
};

function byId(id) {
  return document.getElementById(id);
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

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
  return new Date(timestamp).toLocaleString('zh-CN', { hour12: false });
}

function formatDateRange(start, end) {
  if (!start || !end) return '-';
  return `${formatDate(start)} 至 ${formatDate(end)}`;
}

function formatWeekdayLabel(dayOfWeek) {
  const labels = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
  const day = Number(dayOfWeek);
  if (!Number.isFinite(day)) return '周一';
  const safe = Math.max(0, Math.min(6, Math.round(day)));
  return labels[safe] || '周一';
}

function reportTypeLabel(type) {
  if (type === 'weekly') return '竞对动态周报';
  if (type === 'trend') return '行业趋势研判报告';
  return type || '-';
}

function setMessage(targetId, text, level = '') {
  const node = byId(targetId);
  if (!node) return;
  const preserved = Array.from(node.classList).filter((className) => className.startsWith('message--'));
  node.className = 'message';
  preserved.forEach((className) => node.classList.add(className));
  if (level) {
    node.classList.add(`is-${level}`);
  }
  node.textContent = text || '';
}

function clearTable(tbodyId, columnCount, message) {
  const tbody = byId(tbodyId);
  if (!tbody) return;
  tbody.innerHTML = '';
  const tr = document.createElement('tr');
  const td = document.createElement('td');
  td.colSpan = columnCount;
  td.className = 'empty-row';
  td.textContent = message;
  tr.appendChild(td);
  tbody.appendChild(tr);
}

async function requestJson(path, options = {}) {
  const { timeoutMs = 120000, ...fetchOptions } = options;
  const safeTimeoutMs = Number(timeoutMs || 120000);
  const headers = {
    ...(fetchOptions.headers || {})
  };

  if (fetchOptions.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), safeTimeoutMs);
  let response;

  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers,
      signal: controller.signal
    });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`请求超时（>${Math.round(safeTimeoutMs / 1000)} 秒）：${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }

  let payload;
  try {
    payload = await response.json();
  } catch {
    payload = { ok: false, error: `接口返回非JSON：${path}` };
  }

  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || `请求失败：${path}`);
  }

  return payload;
}

async function requestNdjson(path, options = {}, handlers = {}) {
  const { timeoutMs = 240000, ...fetchOptions } = options;
  const safeTimeoutMs = Number(timeoutMs || 240000);
  const headers = {
    ...(fetchOptions.headers || {})
  };

  if (fetchOptions.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), safeTimeoutMs);

  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...fetchOptions,
      headers,
      signal: controller.signal
    });
  } catch (error) {
    if (error.name === 'AbortError') {
      throw new Error(`请求超时（>${Math.round(safeTimeoutMs / 1000)} 秒）：${path}`);
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `请求失败：${path}`);
  }

  if (!response.body) {
    throw new Error(`接口未返回流式数据：${path}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let pending = '';

  const processLine = (line) => {
    const text = String(line || '').trim();
    if (!text) return;

    let payload = null;
    try {
      payload = JSON.parse(text);
    } catch {
      return;
    }

    if (payload?.type === 'error') {
      throw new Error(payload.error || '流式处理失败');
    }

    if (typeof handlers.onEvent === 'function') {
      handlers.onEvent(payload);
    }
  };

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    pending += decoder.decode(value, { stream: true });
    let idx = pending.indexOf('\n');
    while (idx >= 0) {
      const line = pending.slice(0, idx);
      pending = pending.slice(idx + 1);
      processLine(line);
      idx = pending.indexOf('\n');
    }
  }

  if (pending.trim()) {
    processLine(pending);
  }
}

function getTodayCount() {
  const rows = state.metrics?.byDate || [];
  if (!rows.length) return 0;
  return rows[rows.length - 1]?.count || 0;
}

function getScanProgressText() {
  const progress = state.status?.scanner?.progress;
  if (!progress) return '-';
  return `${progress.completedQueries || 0}/${progress.totalQueries || 0}，已写入 ${progress.written || 0}`;
}

function setHeaderStatusTone(tone = 'idle') {
  const header = byId('header-status-line');
  if (!header) return;

  header.classList.remove('status-idle', 'status-running', 'status-warning', 'status-error');
  header.classList.add(`status-${tone}`);
}

function renderHeaderKpis() {
  const node = byId('header-kpi-strip');
  if (!node) return;

  if (!state.status) {
    node.innerHTML = '';
    return;
  }

  const running = Boolean(state.status.scanner?.running);
  const todayCount = getTodayCount();
  const chips = [
    {
      label: '情报总量',
      value: `${state.status.findingCount || 0} 条`,
      state: 'up'
    },
    {
      label: '报告总量',
      value: `${state.status.reportCount || 0} 份`,
      state: 'up'
    },
    {
      label: '今日新增',
      value: `${todayCount} 条`,
      state: todayCount > 0 ? 'up' : 'down'
    },
    {
      label: '扫描器状态',
      value: running ? '运行中' : '空闲',
      state: running ? 'up' : (state.status.scanner?.lastError ? 'down' : '')
    },
    {
      label: '最近扫描',
      value: formatDate(state.status.lastScanAt),
      state: ''
    }
  ];

  node.innerHTML = chips.map((item) => `
    <div class="kpi-chip ${item.state ? `kpi-chip--${item.state}` : 'kpi-chip--neutral'}">
      <div class="kpi-chip__label">${escapeHtml(item.label)}</div>
      <div class="kpi-chip__value ${item.state ? `is-${item.state}` : ''}">${escapeHtml(item.value)}</div>
    </div>
  `).join('');
}

function renderCoverage() {
  const tbody = byId('coverage-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  const competitors = state.config?.competitors || [];
  if (!competitors.length) {
    clearTable('coverage-table-body', 4, '暂无监测对象配置');
    return;
  }

  for (const item of competitors) {
    const tr = document.createElement('tr');

    const tdName = document.createElement('td');
    tdName.textContent = item.name || '-';

    const tdRegion = document.createElement('td');
    tdRegion.textContent = item.region || '-';

    const categories = (item.topics || []).map((topic) => topic.category).filter(Boolean);
    const tdCategory = document.createElement('td');
    tdCategory.textContent = categories.length ? categories.join(' / ') : '-';

    const queryCount = (item.topics || []).reduce((sum, topic) => {
      return sum + ((topic.queries || []).length || 0);
    }, 0);

    const tdQueryCount = document.createElement('td');
    tdQueryCount.textContent = String(queryCount);

    tr.appendChild(tdName);
    tr.appendChild(tdRegion);
    tr.appendChild(tdCategory);
    tr.appendChild(tdQueryCount);

    tbody.appendChild(tr);
  }
}

function renderSimpleChart(containerId, rows, emptyText) {
  const container = byId(containerId);
  if (!container) return;

  if (!rows?.length) {
    container.innerHTML = `<div class="subtle-text">${escapeHtml(emptyText)}</div>`;
    return;
  }

  const max = Math.max(...rows.map((item) => item.count), 1);
  container.innerHTML = rows.map((item, index) => {
    const width = Math.max(4, Math.round((item.count / max) * 100));
    const barClass = index % 2 === 0 ? 'simple-chart__bar' : 'simple-chart__bar is-success';
    return `
      <div class="simple-chart__row">
        <div class="simple-chart__label">${escapeHtml(item.name)}</div>
        <div class="simple-chart__bar-wrap">
          <div class="${barClass}" style="width:${width}%"></div>
        </div>
        <div class="simple-chart__value">${item.count}</div>
      </div>
    `;
  }).join('');
}

function renderTrendChart(rows) {
  const container = byId('chart-trend');
  if (!container) return;

  if (!rows?.length) {
    container.innerHTML = '<div class="subtle-text">暂无趋势数据</div>';
    return;
  }

  const max = Math.max(...rows.map((item) => item.count), 1);
  const slice = rows.slice(-14);

  container.innerHTML = slice.map((item) => {
    const heightPct = Math.max(3, Math.round((item.count / max) * 100));
    const shortDate = item.date ? item.date.slice(5) : '--';
    return `
      <div class="trend-chart__item">
        <div class="trend-chart__bar-wrap">
          <div class="trend-chart__bar" style="height:${heightPct}%"></div>
        </div>
        <div class="trend-chart__meta"><strong>${item.count}</strong>${escapeHtml(shortDate)}</div>
      </div>
    `;
  }).join('');
}

function renderCharts() {
  const competitorRows = (state.metrics?.byCompetitor || []).slice(0, 8);
  const categoryRows = (state.metrics?.byCategory || []).slice(0, 8);
  renderSimpleChart('chart-competitors', competitorRows, '暂无竞对统计数据');
  renderSimpleChart('chart-categories', categoryRows, '暂无类别统计数据');
  renderTrendChart(state.metrics?.byDate || []);
}

function formatMetricCell(metric) {
  if (!metric) {
    return '<span class="subtle-text">—</span>';
  }

  const yoyValue = Number(metric.yoyValue);
  const tone = Number.isFinite(yoyValue)
    ? (yoyValue > 0 ? 'up' : (yoyValue < 0 ? 'down' : 'flat'))
    : '';

  return `
    <div class="board-metric">
      <div class="board-metric__value">${escapeHtml(metric.valueText || '-')}</div>
      ${metric.yoyText ? `<div class="board-metric__yoy ${tone ? `is-${tone}` : ''}">${escapeHtml(metric.yoyText)}</div>` : ''}
    </div>
  `;
}

function formatMomentumCell(momentum) {
  if (!momentum || typeof momentum !== 'object') {
    return '<span class="subtle-text">无</span>';
  }
  const tone = momentum.tone === 'up' ? 'up' : (momentum.tone === 'down' ? 'down' : 'flat');
  const label = tone === 'up' ? '升温' : (tone === 'down' ? '降温' : '持平');
  return `<span class="board-badge is-${tone}">${label} ${escapeHtml(momentum.deltaPctText || '0%')}</span>`;
}

function renderBoardSummary(summary, asOf) {
  const node = byId('board-summary');
  if (!node) return;

  if (!summary) {
    node.innerHTML = '';
    return;
  }

  const items = [
    {
      label: '覆盖竞对',
      value: `${summary.competitorCount || 0} 家`,
      tone: 'neutral'
    },
    {
      label: '活跃竞对',
      value: `${summary.activeCompetitors || 0} 家`,
      tone: 'up'
    },
    {
      label: '窗口情报',
      value: `${summary.totalFindings || 0} 条`,
      tone: 'up'
    },
    {
      label: '财务披露覆盖',
      value: `${summary.financialCoverage || 0} 家`,
      tone: summary.financialCoverage > 0 ? 'up' : 'down'
    },
    {
      label: '平均指标覆盖',
      value: `${summary.avgKpiCoverage || 0}`,
      tone: (summary.avgKpiCoverage || 0) >= 2 ? 'up' : 'down'
    },
    {
      label: '数据更新时间',
      value: formatDate(asOf),
      tone: 'neutral'
    }
  ];

  node.innerHTML = items.map((item) => `
    <div class="board-summary-item is-${item.tone}">
      <div class="board-summary-item__label">${escapeHtml(item.label)}</div>
      <div class="board-summary-item__value">${escapeHtml(String(item.value))}</div>
    </div>
  `).join('');
}

function getBoardRows() {
  return Array.isArray(state.board?.data?.competitors) ? state.board.data.competitors : [];
}

function getBoardSelectedSet() {
  const rows = Array.isArray(state.board?.selectedCompetitors) ? state.board.selectedCompetitors : [];
  return new Set(rows.map((item) => String(item || '').trim()).filter(Boolean));
}

function hasBoardSelection() {
  return getBoardSelectedSet().size > 0;
}

function normalizeBoardSelection() {
  const rows = getBoardRows();
  const selectedSet = getBoardSelectedSet();
  const selected = Array.from(selectedSet);

  if (!rows.length) {
    state.board.selectedCompetitors = [];
    return;
  }

  if (!selected.length) {
    state.board.selectedCompetitors = [];
    return;
  }

  const exists = new Set(rows.map((row) => String(row.name || '').trim()));
  state.board.selectedCompetitors = selected.filter((name) => exists.has(name));
}

function isBoardSelected(name) {
  const picked = getBoardSelectedSet();
  if (!picked.size) return false;
  return picked.has(String(name || '').trim());
}

function pickBoardCompetitor(name) {
  const next = String(name || '').trim();

  if (!next) {
    state.board.selectedCompetitors = [];
    renderCompetitorBoard();
    setMessage('board-message', '已切换至全部竞对视图。', 'success');
    return;
  }

  const picked = getBoardSelectedSet();
  if (picked.has(next)) {
    picked.delete(next);
  } else {
    picked.add(next);
  }
  state.board.selectedCompetitors = Array.from(picked);
  renderCompetitorBoard();

  const count = state.board.selectedCompetitors.length;
  if (count === 0) {
    setMessage('board-message', '已切换至全部竞对视图。', 'success');
    return;
  }
  if (count === 1) {
    setMessage('board-message', `已选中 1 家竞对：${state.board.selectedCompetitors[0]}。`, 'success');
    return;
  }
  setMessage('board-message', `已选中 ${count} 家竞对，图表与来源已按多选联动。`, 'success');
}

function aggregateBoardCategoryRows(rows) {
  const map = new Map();
  for (const row of rows || []) {
    for (const item of row.categoryMix || []) {
      const key = String(item?.name || '').trim() || '未分类';
      const count = Number(item?.count || 0);
      map.set(key, (map.get(key) || 0) + count);
    }
  }
  return Array.from(map.entries())
    .map(([name, count]) => ({ name, count }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);
}

function aggregateBoardRegionRows(rows) {
  const map = new Map();
  for (const row of rows || []) {
    const region = String(row?.region || '').trim() || 'Unknown';
    const count = Number(row?.findingCount || 0);
    map.set(region, (map.get(region) || 0) + count);
  }
  return Array.from(map.entries())
    .map(([name, count]) => ({ name, count }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count)
    .slice(0, 8);
}

function aggregateBoardMomentumRows(rows) {
  const bins = {
    up: 0,
    flat: 0,
    down: 0
  };
  for (const row of rows || []) {
    const tone = row?.momentum?.tone === 'up' || row?.momentum?.tone === 'down'
      ? row.momentum.tone
      : 'flat';
    bins[tone] += 1;
  }
  return [
    { name: '升温', count: bins.up, tone: 'up' },
    { name: '持平', count: bins.flat, tone: 'flat' },
    { name: '降温', count: bins.down, tone: 'down' }
  ].filter((item) => item.count > 0);
}

function renderBoardCompetitorPills(rows) {
  const node = byId('board-competitor-pills');
  if (!node) return;

  if (!rows?.length) {
    node.innerHTML = '';
    return;
  }

  const pills = [
    {
      name: '',
      label: '全部竞对',
      count: rows.reduce((sum, row) => sum + Number(row.findingCount || 0), 0)
    },
    ...rows.map((row) => ({
      name: row.name,
      label: row.name,
      count: Number(row.findingCount || 0)
    }))
  ];

  node.innerHTML = pills.map((item) => {
    const selected = item.name
      ? isBoardSelected(item.name)
      : !hasBoardSelection();
    return `
      <button
        class="board-pill ${selected ? 'is-active' : ''}"
        type="button"
        data-board-pick="${escapeHtml(item.name)}"
      >
        <span>${escapeHtml(item.label)}</span>
        <strong>${Number(item.count || 0)}</strong>
      </button>
    `;
  }).join('');
}

function renderBoardPieChart(containerId, rows, options = {}) {
  const node = byId(containerId);
  if (!node) return;

  const safeRows = Array.isArray(rows)
    ? rows
      .map((item) => ({
        name: String(item?.name || '').trim() || '未命名',
        count: Number(item?.count || 0),
        tone: item?.tone || ''
      }))
      .filter((item) => item.count > 0)
      .slice(0, 8)
    : [];

  if (!safeRows.length) {
    node.innerHTML = `<div class="subtle-text">${escapeHtml(options.emptyText || '暂无饼图数据。')}</div>`;
    return;
  }

  const palette = ['#2b72ba', '#2fa26c', '#d94c3f', '#9068d6', '#e08a2e', '#1b9aaa', '#5e6c84', '#7ea04d'];
  const total = safeRows.reduce((sum, item) => sum + item.count, 0);
  let angle = 0;
  const parts = safeRows.map((item, index) => {
    const pct = total > 0 ? (item.count / total) : 0;
    const start = angle;
    const end = angle + pct * 360;
    angle = end;
    const color = palette[index % palette.length];
    return {
      ...item,
      color,
      start,
      end,
      pct
    };
  });

  const gradient = parts
    .map((item) => `${item.color} ${item.start.toFixed(2)}deg ${item.end.toFixed(2)}deg`)
    .join(', ');

  const legend = parts.map((item) => {
    const percent = (item.pct * 100).toFixed(1);
    return `
      <div class="board-pie__legend-item">
        <span class="board-pie__legend-dot" style="background:${item.color}"></span>
        <span class="board-pie__legend-name">${escapeHtml(item.name)}</span>
        <span class="board-pie__legend-value">${item.count}（${percent}%）</span>
      </div>
    `;
  }).join('');

  node.innerHTML = `
    <div class="board-pie">
      <div class="board-pie__chart" style="background:conic-gradient(${gradient})">
        <div class="board-pie__hole">
          <strong>${total}</strong>
          <span>总量</span>
        </div>
      </div>
      <div class="board-pie__legend">${legend}</div>
    </div>
  `;
}

function renderBoardLineChart(containerId, rows) {
  const node = byId(containerId);
  if (!node) return;

  const safeRows = Array.isArray(rows)
    ? rows.map((item) => ({
      label: String(item?.label || '').trim(),
      count: Number(item?.count || 0)
    }))
    : [];

  if (!safeRows.length) {
    node.innerHTML = '<div class="subtle-text">暂无趋势数据。</div>';
    return;
  }

  const width = 560;
  const height = 190;
  const paddingX = 30;
  const paddingY = 22;
  const innerWidth = width - paddingX * 2;
  const innerHeight = height - paddingY * 2;
  const max = Math.max(...safeRows.map((item) => item.count), 1);
  const stepX = safeRows.length > 1 ? innerWidth / (safeRows.length - 1) : innerWidth;

  const points = safeRows.map((item, index) => {
    const x = paddingX + stepX * index;
    const y = paddingY + (1 - (item.count / max)) * innerHeight;
    return { ...item, x, y };
  });

  const linePath = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(' ');
  const areaPath = `${linePath} L${(paddingX + innerWidth).toFixed(2)} ${(paddingY + innerHeight).toFixed(2)} L${paddingX.toFixed(2)} ${(paddingY + innerHeight).toFixed(2)} Z`;
  const labels = points.map((point) => `
    <div class="board-line-chart__label-item">
      <span>${escapeHtml(point.label || '--')}</span>
      <strong>${point.count}</strong>
    </div>
  `).join('');

  node.innerHTML = `
    <svg class="board-line-chart__svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="趋势图">
      <defs>
        <linearGradient id="boardLineFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="rgba(46, 122, 193, 0.34)"></stop>
          <stop offset="100%" stop-color="rgba(46, 122, 193, 0.02)"></stop>
        </linearGradient>
      </defs>
      <path d="${areaPath}" fill="url(#boardLineFill)"></path>
      <path d="${linePath}" fill="none" stroke="#2a71ba" stroke-width="2.5" stroke-linecap="round"></path>
      ${points.map((point) => `<circle cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3.2" fill="#1e5da0"></circle>`).join('')}
    </svg>
    <div class="board-line-chart__labels">${labels}</div>
  `;
}

function renderBoardFocusPanel(rows) {
  const selectedSet = getBoardSelectedSet();
  const selectedNames = Array.from(selectedSet);
  const selectedRows = selectedNames.length
    ? rows.filter((row) => selectedSet.has(String(row.name || '').trim()))
    : [];
  const focus = selectedRows.length === 1 ? selectedRows[0] : null;

  const headerNode = byId('board-focus-header');
  const metricsNode = byId('board-focus-metrics');
  const sourceNode = byId('board-focus-sources');
  if (!headerNode || !metricsNode || !sourceNode) return;

  if (!selectedRows.length) {
    headerNode.innerHTML = '<div class="subtle-text">当前处于全部竞对视图。请选择某个竞对查看深度分析。</div>';
    metricsNode.innerHTML = '';
    renderBoardPieChart('board-focus-category-pie', [], { emptyText: '请选择竞对。' });
    renderBoardLineChart('board-focus-trend-line', []);
    sourceNode.innerHTML = '';
    return;
  }

  if (selectedRows.length > 1) {
    const totalFindings = selectedRows.reduce((sum, row) => sum + Number(row.findingCount || 0), 0);
    const topMover = [...selectedRows]
      .sort((a, b) => Number(b.momentum?.deltaPct || 0) - Number(a.momentum?.deltaPct || 0))[0];

    headerNode.innerHTML = `
      <div class="board-focus-header__main">
        <strong>多竞对联动视图</strong>
        <span>已选 ${selectedRows.length} 家：${escapeHtml(selectedRows.map((row) => row.name).join(' / '))}</span>
      </div>
      <div class="board-focus-header__badge is-flat">合计 ${totalFindings} 条</div>
    `;

    metricsNode.innerHTML = [
      ['选中竞对', `${selectedRows.length} 家`],
      ['合计情报', `${totalFindings} 条`],
      ['最高动量', topMover ? `${topMover.name} ${topMover.momentum?.deltaPctText || '0%'}` : '-']
    ].map(([label, value]) => `
      <div class="board-focus-metric">
        <div class="board-focus-metric__label">${escapeHtml(label)}</div>
        <div class="board-focus-metric__value">${escapeHtml(value)}</div>
        <div class="board-focus-metric__yoy is-flat">多选聚合</div>
      </div>
    `).join('');

    renderBoardPieChart('board-focus-category-pie', aggregateBoardCategoryRows(selectedRows), { emptyText: '暂无类别分布数据。' });
    const mergedTrend = [];
    const map = new Map();
    for (const row of selectedRows) {
      for (const point of row.trend || []) {
        const label = String(point?.label || '');
        map.set(label, (map.get(label) || 0) + Number(point?.count || 0));
      }
    }
    for (const [label, count] of map.entries()) {
      mergedTrend.push({ label, count });
    }
    renderBoardLineChart('board-focus-trend-line', mergedTrend);

    const mergedSources = selectedRows
      .flatMap((row) => row.recentSignals || [])
      .sort((a, b) => Date.parse(b.publishedAt || '') - Date.parse(a.publishedAt || ''))
      .slice(0, 10);

    sourceNode.innerHTML = mergedSources.length
      ? `
        <div class="board-focus-sources__title">多选竞对最新来源</div>
        <div class="board-source-list">
          ${mergedSources.map((item) => `
            <article class="board-source-item">
              <div class="board-source-item__head">
                <span class="board-source-item__tag is-neutral">情报</span>
                <span>${escapeHtml(item.competitor || '-')}</span>
                <span>${escapeHtml(item.category || '-')}</span>
                <span>${escapeHtml(formatDate(item.publishedAt))}</span>
              </div>
              <div class="board-source-item__title">${item.sourceUrl ? renderSafeLink(item.sourceUrl, item.title || '-') : escapeHtml(item.title || '-')}</div>
              ${item.summary ? `<div class="board-source-item__summary">${escapeHtml(item.summary)}</div>` : ''}
            </article>
          `).join('')}
        </div>
      `
      : '<div class="subtle-text">选中竞对暂无来源数据。</div>';
    return;
  }

  headerNode.innerHTML = `
    <div class="board-focus-header__main">
      <strong>${escapeHtml(focus.name || '-')}</strong>
      <span>${escapeHtml(focus.region || '-')} | 情报 ${Number(focus.findingCount || 0)} 条</span>
    </div>
    <div class="board-focus-header__badge is-${escapeHtml(focus.momentum?.tone || 'flat')}">
      ${escapeHtml(focus.momentum?.deltaPctText || '0%')}
    </div>
  `;

  const metricRows = [
    ['营业收入', focus.kpis?.revenue],
    ['EBITDA', focus.kpis?.ebitda],
    ['净利润', focus.kpis?.netProfit],
    ['资本开支', focus.kpis?.capex],
    ['移动用户', focus.kpis?.mobileUsers],
    ['5G用户', focus.kpis?.fiveGUsers],
    ['5G渗透率', focus.kpis?.fiveGPenetration]
  ];

  metricsNode.innerHTML = metricRows.map(([label, metric]) => {
    const value = metric?.valueText || '-';
    const yoy = metric?.yoyText || '';
    const tone = metric?.yoyValue > 0 ? 'up' : (metric?.yoyValue < 0 ? 'down' : 'flat');
    return `
      <div class="board-focus-metric">
        <div class="board-focus-metric__label">${escapeHtml(label)}</div>
        <div class="board-focus-metric__value">${escapeHtml(value)}</div>
        ${yoy ? `<div class="board-focus-metric__yoy is-${tone}">${escapeHtml(yoy)}</div>` : '<div class="board-focus-metric__yoy is-flat">-</div>'}
      </div>
    `;
  }).join('');

  renderBoardPieChart('board-focus-category-pie', focus.categoryMix || [], { emptyText: '暂无类别分布数据。' });
  renderBoardLineChart('board-focus-trend-line', focus.trend || []);

  const focusSources = (focus.recentSignals || []).slice(0, 8);
  sourceNode.innerHTML = focusSources.length
    ? `
      <div class="board-focus-sources__title">选中竞对最新来源</div>
      <div class="board-source-list">
        ${focusSources.map((item) => `
          <article class="board-source-item">
            <div class="board-source-item__head">
              <span class="board-source-item__tag is-neutral">情报</span>
              <span>${escapeHtml(item.category || '-')}</span>
              <span>${escapeHtml(formatDate(item.publishedAt))}</span>
            </div>
            <div class="board-source-item__title">${item.sourceUrl ? renderSafeLink(item.sourceUrl, item.title || '-') : escapeHtml(item.title || '-')}</div>
            ${item.summary ? `<div class="board-source-item__summary">${escapeHtml(item.summary)}</div>` : ''}
          </article>
        `).join('')}
      </div>
    `
    : '<div class="subtle-text">选中竞对暂无来源数据。</div>';
}

function renderBoardBarChart(containerId, rows, emptyText) {
  const container = byId(containerId);
  if (!container) return;

  if (!rows?.length) {
    container.innerHTML = `<div class="subtle-text">${escapeHtml(emptyText)}</div>`;
    return;
  }

  const max = Math.max(...rows.map((item) => Number(item.count || 0)), 1);
  container.innerHTML = rows.slice(0, 10).map((item, index) => {
    const count = Number(item.count || 0);
    const width = Math.max(3, Math.round((count / max) * 100));
    const tone = index % 2 === 0 ? 'up' : 'neutral';
    const name = String(item.name || '').trim();
    const active = name && isBoardSelected(name) ? 'is-selected' : '';
    const attrs = name
      ? `data-board-competitor="${escapeHtml(name)}" role="button" tabindex="0"`
      : '';
    return `
      <div class="board-bar-row ${active}" ${attrs}>
        <div class="board-bar-row__label">${escapeHtml(item.name || '-')}</div>
        <div class="board-bar-row__track">
          <div class="board-bar-row__fill is-${tone}" style="width:${width}%"></div>
        </div>
        <div class="board-bar-row__value">${count}</div>
      </div>
    `;
  }).join('');
}

function renderBoardYoyChart(rows) {
  const container = byId('board-chart-revenue-yoy');
  if (!container) return;

  if (!rows?.length) {
    container.innerHTML = '<div class="subtle-text">当前窗口暂无可比营收同比数据。</div>';
    return;
  }

  const maxAbs = Math.max(...rows.map((item) => Math.abs(Number(item.value || 0))), 1);
  container.innerHTML = rows.slice(0, 10).map((item) => {
    const value = Number(item.value || 0);
    const width = Math.max(2, Math.round((Math.abs(value) / maxAbs) * 50));
    const tone = value > 0 ? 'up' : (value < 0 ? 'down' : 'flat');
    const sign = value > 0 ? '+' : '';
    const name = String(item.name || '').trim();
    const active = name && isBoardSelected(name) ? 'is-selected' : '';
    const attrs = name
      ? `data-board-competitor="${escapeHtml(name)}" role="button" tabindex="0"`
      : '';
    return `
      <div class="board-yoy-row ${active}" ${attrs}>
        <div class="board-yoy-row__label">${escapeHtml(item.name || '-')}</div>
        <div class="board-yoy-row__track">
          <div class="board-yoy-row__axis"></div>
          <div class="board-yoy-row__fill is-${tone}" style="${value >= 0 ? `left:50%;width:${width}%` : `left:${50 - width}%;width:${width}%`}"></div>
        </div>
        <div class="board-yoy-row__value is-${tone}">${sign}${value.toFixed(1)}%</div>
      </div>
    `;
  }).join('');
}

function renderBoardTable(rows) {
  const tbody = byId('board-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!rows?.length) {
    clearTable('board-table-body', 11, '暂无看板数据');
    return;
  }

  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.className = `board-row is-${row.momentum?.tone || 'flat'} ${isBoardSelected(row.name) ? 'is-selected' : ''}`;
    tr.setAttribute('data-board-competitor', String(row.name || ''));
    tr.setAttribute('role', 'button');
    tr.setAttribute('tabindex', '0');

    const topCategory = Array.isArray(row.categoryMix) && row.categoryMix[0]
      ? row.categoryMix[0]
      : null;

    const recentSignal = Array.isArray(row.recentSignals) ? row.recentSignals[0] : null;
    const recentHtml = recentSignal?.sourceUrl
      ? `${escapeHtml(formatDate(recentSignal.publishedAt))}<br>${renderSafeLink(recentSignal.sourceUrl, recentSignal.title || '来源')}`
      : escapeHtml(formatDate(row.lastFindingAt));

    tr.innerHTML = `
      <td>
        <div class="board-company">${escapeHtml(row.name || '-')}</div>
        ${topCategory ? `<div class="board-company__meta">主议题：${escapeHtml(topCategory.name)}（${topCategory.count}）</div>` : '<div class="board-company__meta">主议题：-</div>'}
      </td>
      <td>${escapeHtml(row.region || '-')}</td>
      <td>
        <div>${Number(row.findingCount || 0)} 条</div>
        ${formatMomentumCell(row.momentum)}
      </td>
      <td>${formatMetricCell(row.kpis?.revenue)}</td>
      <td>${formatMetricCell(row.kpis?.ebitda)}</td>
      <td>${formatMetricCell(row.kpis?.netProfit)}</td>
      <td>${formatMetricCell(row.kpis?.capex)}</td>
      <td>${formatMetricCell(row.kpis?.mobileUsers)}</td>
      <td>${formatMetricCell(row.kpis?.fiveGUsers)}</td>
      <td>${formatMetricCell(row.kpis?.fiveGPenetration)}</td>
      <td>${recentHtml}</td>
    `;

    tbody.appendChild(tr);
  }
}

function renderBoardTrend(rows) {
  const node = byId('board-trend-grid');
  if (!node) return;

  if (!rows?.length) {
    node.innerHTML = '<div class="subtle-text">暂无趋势数据。</div>';
    return;
  }

  const cards = rows.slice(0, 8).map((row) => {
    const trendRows = Array.isArray(row.trend) ? row.trend : [];
    const max = Math.max(...trendRows.map((item) => Number(item.count || 0)), 1);
    const bars = trendRows.map((item) => {
      const height = Math.max(3, Math.round((Number(item.count || 0) / max) * 100));
      return `
        <div class="board-mini-trend__item">
          <div class="board-mini-trend__bar-wrap">
            <div class="board-mini-trend__bar" style="height:${height}%"></div>
          </div>
          <div class="board-mini-trend__label">${escapeHtml(item.label || '--')}</div>
        </div>
      `;
    }).join('');

    return `
      <article
        class="board-trend-card ${isBoardSelected(row.name) ? 'is-selected' : ''}"
        data-board-competitor="${escapeHtml(row.name || '')}"
        role="button"
        tabindex="0"
      >
        <div class="board-trend-card__head">
          <strong>${escapeHtml(row.name || '-')}</strong>
          <span>${Number(row.findingCount || 0)} 条</span>
        </div>
        <div class="board-mini-trend">${bars}</div>
      </article>
    `;
  });

  node.innerHTML = cards.join('');
}

function renderBoardSources(items) {
  const node = byId('board-source-list');
  if (!node) return;

  if (!items?.length) {
    node.innerHTML = '<div class="subtle-text">当前窗口暂无可展示来源。</div>';
    return;
  }

  node.innerHTML = items.slice(0, 14).map((item) => `
    <article class="board-source-item" ${item.competitor ? `data-board-competitor="${escapeHtml(item.competitor)}"` : ''}>
      <div class="board-source-item__head">
        <span class="board-source-item__tag is-${item.tag === '指标' ? 'up' : 'neutral'}">${escapeHtml(item.tag || '情报')}</span>
        <span>${escapeHtml(item.competitor || '-')}</span>
        <span>${escapeHtml(item.category || '-')}</span>
        <span>${escapeHtml(formatDate(item.publishedAt))}</span>
      </div>
      <div class="board-source-item__title">${item.sourceUrl ? renderSafeLink(item.sourceUrl, item.title || '-') : escapeHtml(item.title || '-')}</div>
      ${item.summary ? `<div class="board-source-item__summary">${escapeHtml(item.summary)}</div>` : ''}
    </article>
  `).join('');
}

function renderCompetitorBoard() {
  const payload = state.board.data;
  const rows = Array.isArray(payload?.competitors) ? payload.competitors : [];

  normalizeBoardSelection();
  renderBoardSummary(payload?.summary, payload?.asOf);
  renderBoardCompetitorPills(rows);

  const selectedSet = getBoardSelectedSet();
  const hasSelected = selectedSet.size > 0;
  const scopedRows = hasSelected
    ? rows.filter((row) => selectedSet.has(String(row.name || '').trim()))
    : rows;
  const chartRows = scopedRows.length ? scopedRows : rows;

  renderBoardBarChart('board-chart-activity', payload?.charts?.activity || [], '暂无竞对情报热度数据');
  renderBoardBarChart('board-chart-coverage', payload?.charts?.coverage || [], '暂无财务披露覆盖数据');
  renderBoardYoyChart(payload?.charts?.revenueYoy || []);
  renderBoardPieChart('board-chart-category-pie', aggregateBoardCategoryRows(chartRows), { emptyText: '暂无情报类别分布数据。' });
  renderBoardPieChart('board-chart-region-pie', aggregateBoardRegionRows(chartRows), { emptyText: '暂无区域分布数据。' });
  renderBoardPieChart('board-chart-momentum-pie', aggregateBoardMomentumRows(chartRows), { emptyText: '暂无动量分布数据。' });

  renderBoardFocusPanel(rows);
  renderBoardTable(rows);
  renderBoardTrend(rows);

  const allSources = Array.isArray(payload?.sources) ? payload.sources : [];
  const sourceRows = hasSelected
    ? allSources.filter((item) => selectedSet.has(String(item.competitor || '').trim()))
    : allSources;
  renderBoardSources(sourceRows.length ? sourceRows : allSources);
}

function updateHeaderLine() {
  const header = byId('header-status-line');
  if (!header) return;

  if (!state.status) {
    header.textContent = '系统状态加载失败';
    setHeaderStatusTone('error');
    return;
  }

  const scanner = state.status.scanner || {};
  const progress = scanner.progress;
  let tone = 'idle';
  if (scanner.running) {
    tone = scanner.stopRequested ? 'warning' : 'running';
  } else if (scanner.lastError) {
    tone = 'error';
  } else if (scanner.lastResult?.stopped) {
    tone = 'warning';
  }
  setHeaderStatusTone(tone);

  const heartbeat = state.status.scheduler?.heartbeat || state.heartbeat || getDefaultHeartbeat();
  const heartbeatText = heartbeat.scan?.enabled ? `心跳检索 每${heartbeat.scan.intervalMinutes}分钟` : '心跳检索 已关闭';
  const weeklyText = heartbeat.weeklyReport?.enabled
    ? `周报 每${formatWeekdayLabel(heartbeat.weeklyReport.dayOfWeek)} ${heartbeat.weeklyReport.time}`
    : '周报 已关闭';

  const totalQueries = Number(progress?.totalQueries || 0);
  const completedQueries = Number(progress?.completedQueries || 0);
  const written = Number(progress?.written || 0);
  const percent = totalQueries > 0 ? Math.min(100, Math.round((completedQueries / totalQueries) * 100)) : 0;
  const currentQuery = String(progress?.currentQuery || '').trim();

  let statusText = '';
  if (scanner.running) {
    statusText = [
      scanner.stopRequested ? '扫描器 截停中' : '扫描器 执行中',
      `进度 ${completedQueries}/${totalQueries}（${percent}%）`,
      `已写入 ${written}`,
      currentQuery ? `当前 ${currentQuery}` : '当前 准备中'
    ].join(' | ');
  } else {
    const lastResult = scanner.lastResult;
    const lastSummary = lastResult
      ? `上次写入 ${lastResult.totalWritten || 0} 条`
      : null;
    statusText = [
      `扫描器 ${scanner.running ? '运行中' : '空闲'}`,
      heartbeatText,
      weeklyText,
      scanner.lastError ? `异常 ${scanner.lastError}` : null,
      lastSummary
    ].filter(Boolean).join(' | ');
  }

  header.textContent = statusText;
  header.title = statusText;
}

function updateLastRefresh() {
  const node = byId('last-refresh-at');
  if (!node) return;
  node.textContent = `上次刷新：${formatDate(new Date().toISOString())}`;
}

function isScanRunning() {
  return Boolean(state.status?.scanner?.running);
}

function updateScanControls() {
  const scanBtn = byId('btn-scan');
  const stopBtn = byId('btn-scan-stop');
  if (!scanBtn || !stopBtn) return;

  const running = isScanRunning();
  const stopRequested = Boolean(state.status?.scanner?.stopRequested);

  scanBtn.disabled = running;
  stopBtn.disabled = !running || stopRequested;

  scanBtn.textContent = running ? '扫描执行中...' : '立即执行全量扫描';
  stopBtn.textContent = running && stopRequested ? '截停请求已发送' : '截停当前扫描';

  document.body.classList.toggle('is-scanning', running);
  document.body.classList.toggle('is-scan-stopping', running && stopRequested);
}

function getDefaultHeartbeat() {
  return {
    timezone: 'Asia/Hong_Kong',
    scan: {
      enabled: true,
      intervalMinutes: 30
    },
    weeklyReport: {
      enabled: false,
      dayOfWeek: 1,
      time: '09:00'
    },
    trendReport: {
      enabled: false,
      time: '09:20'
    }
  };
}

function normalizeHeartbeatConfig(heartbeat) {
  const source = heartbeat && typeof heartbeat === 'object' ? heartbeat : {};
  const defaults = getDefaultHeartbeat();

  const scanEnabled = source.scan?.enabled !== undefined
    ? Boolean(source.scan.enabled)
    : defaults.scan.enabled;

  const weeklyEnabled = source.weeklyReport?.enabled !== undefined
    ? Boolean(source.weeklyReport.enabled)
    : defaults.weeklyReport.enabled;

  const trendEnabled = source.trendReport?.enabled !== undefined
    ? Boolean(source.trendReport.enabled)
    : defaults.trendReport.enabled;

  const weeklyDay = Number(source.weeklyReport?.dayOfWeek);
  const safeWeeklyDay = Number.isFinite(weeklyDay)
    ? Math.max(0, Math.min(6, Math.round(weeklyDay)))
    : defaults.weeklyReport.dayOfWeek;

  const interval = Number(source.scan?.intervalMinutes || defaults.scan.intervalMinutes);
  const safeInterval = Number.isFinite(interval) ? Math.max(5, Math.min(1440, Math.round(interval))) : defaults.scan.intervalMinutes;

  const normalizeTime = (value, fallback) => {
    const text = String(value || '').trim();
    if (!text) return fallback;
    const match = text.match(/^([01]\d|2[0-3]):([0-5]\d)$/);
    if (!match) return fallback;
    return `${match[1]}:${match[2]}`;
  };

  return {
    timezone: String(source.timezone || defaults.timezone),
    scan: {
      enabled: scanEnabled,
      intervalMinutes: safeInterval
    },
    weeklyReport: {
      enabled: weeklyEnabled,
      dayOfWeek: safeWeeklyDay,
      time: normalizeTime(source.weeklyReport?.time, defaults.weeklyReport.time)
    },
    trendReport: {
      enabled: trendEnabled,
      time: normalizeTime(source.trendReport?.time, defaults.trendReport.time)
    }
  };
}

function syncHeartbeatFieldAvailability() {
  const scanEnabled = byId('hb-scan-enabled')?.value === '1';
  const weeklyEnabled = byId('hb-weekly-enabled')?.value === '1';
  const trendEnabled = byId('hb-trend-enabled')?.value === '1';

  const scanInterval = byId('hb-scan-interval');
  const weeklyTime = byId('hb-weekly-time');
  const weeklyDay = byId('hb-weekly-day');
  const trendTime = byId('hb-trend-time');

  if (scanInterval) scanInterval.disabled = !scanEnabled;
  if (weeklyTime) weeklyTime.disabled = !weeklyEnabled;
  if (weeklyDay) weeklyDay.disabled = !weeklyEnabled;
  if (trendTime) trendTime.disabled = !trendEnabled;
}

function renderHeartbeatForm() {
  const normalized = normalizeHeartbeatConfig(state.heartbeat);
  state.heartbeat = normalized;

  const scanEnabled = byId('hb-scan-enabled');
  const scanInterval = byId('hb-scan-interval');
  const weeklyEnabled = byId('hb-weekly-enabled');
  const weeklyTime = byId('hb-weekly-time');
  const weeklyDay = byId('hb-weekly-day');
  const trendEnabled = byId('hb-trend-enabled');
  const trendTime = byId('hb-trend-time');

  if (!scanEnabled || !scanInterval || !weeklyEnabled || !weeklyTime || !weeklyDay || !trendEnabled || !trendTime) {
    return;
  }

  scanEnabled.value = normalized.scan.enabled ? '1' : '0';
  scanInterval.value = String(normalized.scan.intervalMinutes);
  weeklyEnabled.value = normalized.weeklyReport.enabled ? '1' : '0';
  weeklyDay.value = String(normalized.weeklyReport.dayOfWeek);
  weeklyTime.value = normalized.weeklyReport.time;
  trendEnabled.value = normalized.trendReport.enabled ? '1' : '0';
  trendTime.value = normalized.trendReport.time;

  syncHeartbeatFieldAvailability();
}

function readHeartbeatForm() {
  const scanEnabled = byId('hb-scan-enabled')?.value === '1';
  const weeklyEnabled = byId('hb-weekly-enabled')?.value === '1';
  const trendEnabled = byId('hb-trend-enabled')?.value === '1';
  const weeklyDay = Number(byId('hb-weekly-day')?.value ?? 1);

  const interval = Number(byId('hb-scan-interval')?.value || 0);
  if (!Number.isFinite(interval) || interval < 5 || interval > 1440) {
    throw new Error('检索间隔必须是 5 到 1440 分钟之间的整数。');
  }

  const weeklyTime = String(byId('hb-weekly-time')?.value || '').trim();
  const trendTime = String(byId('hb-trend-time')?.value || '').trim();
  const validTime = /^([01]\d|2[0-3]):([0-5]\d)$/;

  if (weeklyEnabled && !validTime.test(weeklyTime)) {
    throw new Error('周报时间格式无效，请使用 HH:MM。');
  }
  if (!Number.isFinite(weeklyDay) || weeklyDay < 0 || weeklyDay > 6) {
    throw new Error('周报执行日无效，请选择周日到周六。');
  }

  if (trendEnabled && !validTime.test(trendTime)) {
    throw new Error('趋势报告时间格式无效，请使用 HH:MM。');
  }

  return {
    timezone: state.heartbeat?.timezone || 'Asia/Hong_Kong',
    scan: {
      enabled: scanEnabled,
      intervalMinutes: Math.round(interval)
    },
    weeklyReport: {
      enabled: weeklyEnabled,
      dayOfWeek: Math.round(weeklyDay),
      time: weeklyTime || '09:00'
    },
    trendReport: {
      enabled: trendEnabled,
      time: trendTime || '09:20'
    }
  };
}

function getStoredConfigPanelCollapsed() {
  try {
    const saved = localStorage.getItem(CONFIG_PANEL_COLLAPSED_KEY);
    if (saved === null) return true;
    return saved === '1';
  } catch {
    return true;
  }
}

function setConfigPanelCollapsed(collapsed, options = {}) {
  const shouldCollapse = Boolean(collapsed);
  state.ui.configPanelCollapsed = shouldCollapse;

  const grid = document.querySelector('#dashboard .dashboard-grid');
  const toggleButton = byId('btn-config-toggle');

  if (grid) {
    grid.classList.toggle('config-collapsed', shouldCollapse);
  }

  if (toggleButton) {
    toggleButton.textContent = shouldCollapse ? '展开监测配置面板' : '收起监测配置面板';
  }

  if (options.persist !== false) {
    try {
      localStorage.setItem(CONFIG_PANEL_COLLAPSED_KEY, shouldCollapse ? '1' : '0');
    } catch {
      // ignore
    }
  }
}

async function loadHeartbeat(options = {}) {
  const { silent = true } = options;
  const data = await requestJson('/heartbeat');
  state.heartbeat = normalizeHeartbeatConfig(data.heartbeat);
  renderHeartbeatForm();

  if (!silent) {
    setMessage('heartbeat-message', '心跳策略已加载。', 'success');
  }
}

async function saveHeartbeatConfig() {
  await withAction('btn-heartbeat-save', 'heartbeat-message', async () => {
    const payload = readHeartbeatForm();
    setMessage('heartbeat-message', '正在保存心跳策略...', 'warning');

    const data = await requestJson('/heartbeat', {
      method: 'PUT',
      body: JSON.stringify(payload)
    });

    state.heartbeat = normalizeHeartbeatConfig(data.heartbeat);
    renderHeartbeatForm();
    await loadStatus();

    setMessage('heartbeat-message', '心跳策略已保存并生效。', 'success');
    setMessage('dashboard-message', '心跳策略已更新。', 'success');
  });
}

function getConfiguredCompetitorNames() {
  return (state.config?.competitors || [])
    .map((item) => String(item?.name || '').trim())
    .filter(Boolean);
}

function normalizeSelectedFindingsCompetitors(selected, available) {
  const availableSet = new Set(available || []);
  const result = [];
  for (const item of selected || []) {
    const name = String(item || '').trim();
    if (!name || !availableSet.has(name) || result.includes(name)) continue;
    result.push(name);
  }
  return result;
}

function setFindingsCompetitorPanel(open) {
  const trigger = byId('filter-competitor-trigger');
  const panel = byId('filter-competitor-panel');
  if (!trigger || !panel) return;

  const isOpen = Boolean(open);
  state.findingsFilters.competitorPanelOpen = isOpen;
  panel.hidden = !isOpen;
  trigger.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
}

function updateFindingsCompetitorSummary() {
  const selected = state.findingsFilters.selectedCompetitors || [];
  const trigger = byId('filter-competitor-trigger');
  const chips = byId('filter-competitor-chips');
  if (!trigger || !chips) return;

  if (!selected.length) {
    trigger.textContent = '全部竞对';
    chips.innerHTML = '';
    return;
  }

  trigger.textContent = selected.length <= 2
    ? selected.join('、')
    : `已选 ${selected.length} 家竞对`;

  chips.innerHTML = selected.slice(0, 6).map((name) => `
    <span class="multi-pick__chip">${escapeHtml(name)}</span>
  `).join('');
}

function renderFindingsCompetitorOptions() {
  const optionsNode = byId('filter-competitor-options');
  if (!optionsNode) return;

  const names = getConfiguredCompetitorNames();
  const selectedSet = new Set(state.findingsFilters.selectedCompetitors || []);
  optionsNode.innerHTML = '';

  if (!names.length) {
    optionsNode.innerHTML = '<div class="subtle-text">暂无竞对配置。</div>';
    return;
  }

  for (const name of names) {
    const label = document.createElement('label');
    label.className = 'multi-pick__option';

    const input = document.createElement('input');
    input.type = 'checkbox';
    input.value = name;
    input.checked = selectedSet.has(name);
    input.addEventListener('change', () => {
      const next = new Set(state.findingsFilters.selectedCompetitors || []);
      if (input.checked) {
        next.add(name);
      } else {
        next.delete(name);
      }
      state.findingsFilters.selectedCompetitors = normalizeSelectedFindingsCompetitors(
        Array.from(next),
        names
      );
      updateFindingsCompetitorSummary();
    });

    const text = document.createElement('span');
    text.textContent = name;

    label.appendChild(input);
    label.appendChild(text);
    optionsNode.appendChild(label);
  }
}

function populateFindingsFilters() {
  const categorySelect = byId('filter-category');
  if (!categorySelect) return;

  const availableCompetitors = getConfiguredCompetitorNames();
  const currentCompetitors = normalizeSelectedFindingsCompetitors(
    state.findingsFilters.selectedCompetitors,
    availableCompetitors
  );
  const currentCategory = categorySelect.value;

  state.findingsFilters.selectedCompetitors = currentCompetitors;
  categorySelect.innerHTML = '<option value="">全部</option>';

  for (const category of state.config?.categories || []) {
    const option = document.createElement('option');
    option.value = category;
    option.textContent = category;
    categorySelect.appendChild(option);
  }

  categorySelect.value = currentCategory;
  renderFindingsCompetitorOptions();
  updateFindingsCompetitorSummary();
}

function topicQueryCount(topic) {
  return Array.isArray(topic?.queries) ? topic.queries.filter(Boolean).length : 0;
}

function renderConfigEditor() {
  const container = byId('config-editor-list');
  if (!container) return;

  if (!state.editConfig.length) {
    container.innerHTML = '<div class="subtle-text">暂无配置。</div>';
    return;
  }

  container.innerHTML = state.editConfig.map((competitor, ci) => {
    const topicCount = (competitor.topics || []).length;
    const queryCount = (competitor.topics || []).reduce((sum, topic) => sum + topicQueryCount(topic), 0);

    const topicsHtml = (competitor.topics || []).map((topic, ti) => {
      const queryText = (topic.queries || []).join('\n');
      const topicSummary = `${topic.category || `类别 ${ti + 1}`} | 语句 ${topicQueryCount(topic)}`;
      const openTopic = ti === 0 ? 'open' : '';

      return `
        <details class="config-topic" data-ci="${ci}" data-ti="${ti}" ${openTopic}>
          <summary>${escapeHtml(topicSummary)}</summary>
          <div class="config-topic__body">
            <div class="config-topic__head">
              <input data-role="topic-category" data-ci="${ci}" data-ti="${ti}" value="${escapeHtml(topic.category)}" placeholder="监测类别，例如：财报">
              <button class="btn btn-outline" type="button" data-action="remove-topic" data-ci="${ci}" data-ti="${ti}">删除类别</button>
            </div>
            <textarea data-role="topic-queries" data-ci="${ci}" data-ti="${ti}" placeholder="每行一条检索语句">${escapeHtml(queryText)}</textarea>
            <div class="config-topic__hint">检索语句一行一条。</div>
          </div>
        </details>
      `;
    }).join('');

    const openAttr = state.editorOpenCompetitor === ci ? 'open' : '';
    return `
      <details class="config-competitor" data-ci="${ci}" ${openAttr}>
        <summary>${escapeHtml(competitor.name || `竞对 ${ci + 1}`)} | ${escapeHtml(competitor.region || 'Unknown')} | 类别 ${topicCount} | 语句 ${queryCount}</summary>
        <div class="config-competitor__body">
          <div class="config-competitor__head">
            <input data-role="competitor-name" data-ci="${ci}" value="${escapeHtml(competitor.name)}" placeholder="竞对名称">
            <input data-role="competitor-region" data-ci="${ci}" value="${escapeHtml(competitor.region)}" placeholder="区域，例如 Global / Hong Kong">
            <button class="btn btn-outline" type="button" data-action="remove-competitor" data-ci="${ci}">删除竞对</button>
          </div>
          <div class="config-topics">
            ${topicsHtml}
          </div>
          <div class="config-topic__actions">
            <button class="btn btn-outline" type="button" data-action="add-topic" data-ci="${ci}">新增类别</button>
          </div>
        </div>
      </details>
    `;
  }).join('');

  container.querySelectorAll('details.config-competitor').forEach((node) => {
    node.addEventListener('toggle', () => {
      if (node.open) {
        state.editorOpenCompetitor = Number(node.dataset.ci);
      }
    });
  });
}

function setAllConfigOpen(open) {
  const nodes = document.querySelectorAll('details.config-competitor');
  nodes.forEach((node) => {
    node.open = open;
  });
}

function getDefaultCategory() {
  return state.config?.categories?.[0] || '财报';
}

function getDefaultCompetitor() {
  return {
    name: '',
    region: 'Global',
    topics: [
      {
        category: getDefaultCategory(),
        queries: ['']
      }
    ]
  };
}

function normalizeEditorQueries(text) {
  return String(text || '')
    .split('\n')
    .map((value) => value.trim())
    .filter(Boolean);
}

function handleConfigInput(event) {
  const target = event.target;
  if (!target || !target.dataset) return;

  const ci = Number(target.dataset.ci);
  const ti = Number(target.dataset.ti);

  if (Number.isNaN(ci) || !state.editConfig[ci]) return;

  if (target.dataset.role === 'competitor-name') {
    state.editConfig[ci].name = target.value;
    return;
  }

  if (target.dataset.role === 'competitor-region') {
    state.editConfig[ci].region = target.value;
    return;
  }

  if (target.dataset.role === 'topic-category') {
    if (!Number.isNaN(ti) && state.editConfig[ci].topics?.[ti]) {
      state.editConfig[ci].topics[ti].category = target.value;
    }
    return;
  }

  if (target.dataset.role === 'topic-queries') {
    if (!Number.isNaN(ti) && state.editConfig[ci].topics?.[ti]) {
      state.editConfig[ci].topics[ti].queries = normalizeEditorQueries(target.value);
    }
  }
}

function handleConfigAction(event) {
  const target = event.target;
  if (!target || !target.dataset) return;

  const action = target.dataset.action;
  if (!action) return;

  const ci = Number(target.dataset.ci);
  const ti = Number(target.dataset.ti);

  if (action === 'remove-competitor') {
    if (!Number.isNaN(ci)) {
      state.editConfig.splice(ci, 1);
      if (!state.editConfig.length) {
        state.editorOpenCompetitor = null;
      } else if (state.editorOpenCompetitor >= state.editConfig.length) {
        state.editorOpenCompetitor = state.editConfig.length - 1;
      }
      renderConfigEditor();
    }
    return;
  }

  if (action === 'add-topic') {
    if (!Number.isNaN(ci) && state.editConfig[ci]) {
      state.editConfig[ci].topics = state.editConfig[ci].topics || [];
      state.editConfig[ci].topics.push({
        category: getDefaultCategory(),
        queries: ['']
      });
      state.editorOpenCompetitor = ci;
      renderConfigEditor();
    }
    return;
  }

  if (action === 'remove-topic') {
    if (!Number.isNaN(ci) && !Number.isNaN(ti) && state.editConfig[ci]?.topics?.[ti]) {
      state.editConfig[ci].topics.splice(ti, 1);
      renderConfigEditor();
    }
  }
}

function validateEditConfig() {
  if (!Array.isArray(state.editConfig) || !state.editConfig.length) {
    return '至少保留一个监测竞对。';
  }

  for (let ci = 0; ci < state.editConfig.length; ci += 1) {
    const competitor = state.editConfig[ci];
    const row = ci + 1;

    if (!String(competitor.name || '').trim()) {
      return `第 ${row} 个竞对名称不能为空。`;
    }

    if (!Array.isArray(competitor.topics) || !competitor.topics.length) {
      return `第 ${row} 个竞对至少需要一个监测类别。`;
    }

    for (let ti = 0; ti < competitor.topics.length; ti += 1) {
      const topic = competitor.topics[ti];
      if (!String(topic.category || '').trim()) {
        return `第 ${row} 个竞对的第 ${ti + 1} 个类别名称不能为空。`;
      }

      const queryList = Array.isArray(topic.queries) ? topic.queries.filter(Boolean) : [];
      if (!queryList.length) {
        return `第 ${row} 个竞对的第 ${ti + 1} 个类别至少需要一条检索语句。`;
      }
    }
  }

  return null;
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
  const normalizeEllipsis = (text) => String(text || '')
    .replace(/(\.\.\.|…|……)+/g, '')
    .replace(/[，,、和及与或并且同时]+$/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  const stripped = normalizeEllipsis(stripAsciiWords(replaced));
  const cleaned = normalizeEllipsis(replaced);
  if (containsChineseText(stripped)) return stripped;
  if (containsChineseText(cleaned)) return cleaned;
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

function renderLegacyReport(content) {
  const container = byId('report-content');
  if (!container) return;

  const blocks = parseMarkdownBlocks(content).slice(0, 260);

  if (!blocks.length) {
    container.innerHTML = '<div class="subtle-text">报告内容为空。</div>';
    return;
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

  container.innerHTML = `<article class="report-doc report-doc--legacy">${bodyHtml}</article>`;
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

function renderWeeklyBulletinReport(report, structured, sourceRows, sourceIndex) {
  const container = byId('report-content');
  if (!container) return;

  const bulletin = normalizeWeeklyBulletin(structured);
  if (!bulletin) {
    renderLegacyReport(report?.content || '');
    return;
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

  container.innerHTML = `
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

function formatDateOnlyForWeekly(value) {
  const timestamp = Date.parse(String(value || ''));
  if (Number.isNaN(timestamp)) return '-';
  const date = new Date(timestamp);
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日`;
}

function renderStructuredReport(report, structured) {
  const container = byId('report-content');
  if (!container) return;

  const sourceMap = buildSourceMap(report);
  const sourceRows = normalizeReportSourceRows(report, structured, sourceMap);
  const sourceIndex = new Map(sourceRows.map((row) => [row.sourceId, row]));
  const summaryText = toChineseReportText(structured.summary || '', '无执行摘要');

  if (normalizeWeeklyBulletin(structured) && report?.type === 'weekly') {
    renderWeeklyBulletinReport(report, structured, sourceRows, sourceIndex);
    return;
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

  container.innerHTML = [
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

function formatQaConfidence(value) {
  if (value === '高') return '高可信';
  if (value === '低') return '低可信';
  return '中可信';
}

function renderQaAnswerText(text) {
  const blocks = parseMarkdownBlocks(String(text || '')).slice(0, 240);
  if (!blocks.length) {
    return escapeHtml(String(text || '')).replace(/\n/g, '<br>');
  }

  return blocks.map((block) => {
    if (block.type === 'heading') {
      return `<div class="report-qa-item__answer-heading">${renderInlineMarkdown(block.text)}</div>`;
    }
    if (block.type === 'ul') {
      const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('');
      return `<ul class="report-qa-item__answer-list">${items}</ul>`;
    }
    if (block.type === 'ol') {
      const items = block.items.map((item) => `<li>${renderInlineMarkdown(item)}</li>`).join('');
      return `<ol class="report-qa-item__answer-list report-qa-item__answer-list--ordered">${items}</ol>`;
    }

    const paragraph = (block.lines || []).map((line) => renderInlineMarkdown(line)).join('<br>');
    return `<p class="report-qa-item__answer-p">${paragraph}</p>`;
  }).join('');
}

function renderReportQa(report) {
  const listNode = byId('report-qa-list');
  const askBtn = byId('btn-report-qa-ask');
  if (!listNode || !askBtn) return;

  if (!report) {
    askBtn.disabled = true;
    listNode.innerHTML = '<div class="subtle-text">请选择报告后进行问答。</div>';
    return;
  }

  const streamActive = state.qaStream.inFlight && state.qaStream.reportId === report.id;
  askBtn.disabled = streamActive;
  const history = Array.isArray(report.qaHistory) ? report.qaHistory : [];
  if (!history.length && !streamActive) {
    listNode.innerHTML = '<div class="subtle-text">暂无问答记录。输入问题后可生成问答回复。</div>';
    return;
  }

  const streamHtml = streamActive
    ? `
      <article class="report-qa-item is-streaming">
        <div class="report-qa-item__q"><span>问</span>${escapeHtml(state.qaStream.question || '-')}</div>
        <div class="report-qa-item__meta">
          <span>${escapeHtml(formatDate(state.qaStream.startedAt || new Date().toISOString()))}</span>
          <span>流式生成中</span>
          <span>引用：待提取</span>
        </div>
        <div class="report-qa-item__a">${renderQaAnswerText(state.qaStream.answer || '正在生成答复...')}</div>
      </article>
    `
    : '';

  const historyHtml = history.map((item) => {
    const citations = Array.isArray(item.citations)
      ? item.citations
        .map((row) => String(row || '').trim().toUpperCase())
        .filter((row) => /^S\d+$/.test(row))
      : [];
    const keyPoints = Array.isArray(item.keyPoints) ? item.keyPoints.filter(Boolean) : [];
    const followups = Array.isArray(item.followups) ? item.followups.filter(Boolean) : [];

    return `
      <article class="report-qa-item">
        <div class="report-qa-item__q"><span>问</span>${escapeHtml(item.question || '-')}</div>
        <div class="report-qa-item__meta">
          <span>${escapeHtml(formatDate(item.createdAt))}</span>
          <span>${escapeHtml(formatQaConfidence(item.confidence))}</span>
          ${citations.length ? `<span>引用：${escapeHtml(citations.join('、'))}</span>` : '<span>引用：无</span>'}
        </div>
        <div class="report-qa-item__a">${renderQaAnswerText(item.answer || '')}</div>
        ${keyPoints.length ? `<ul class="report-qa-item__list">${keyPoints.map((row) => `<li>${renderInlineMarkdown(row)}</li>`).join('')}</ul>` : ''}
        ${followups.length ? `<div class="report-qa-item__follow">建议追问：${followups.map((row) => renderInlineMarkdown(row)).join('；')}</div>` : ''}
      </article>
    `;
  }).join('');

  listNode.innerHTML = `${streamHtml}${historyHtml}`;
}

function renderFindings(items) {
  const tbody = byId('findings-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!items.length) {
    clearTable('findings-table-body', 7, '暂无符合条件的情报');
    return;
  }

  for (const item of items) {
    const tr = document.createElement('tr');

    const time = document.createElement('td');
    time.textContent = formatDate(item.publishedAt || item.capturedAt || item.createdAt);

    const competitor = document.createElement('td');
    competitor.textContent = item.competitor || '-';

    const category = document.createElement('td');
    category.textContent = item.category || '-';

    const title = document.createElement('td');
    title.textContent = item.title || '-';

    const summary = document.createElement('td');
    summary.textContent = item.summary || '-';

    const significance = document.createElement('td');
    significance.textContent = item.significance || '-';

    const source = document.createElement('td');
    if (item.sourceUrl) {
      const link = document.createElement('a');
      link.className = 'table-link';
      link.href = item.sourceUrl;
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      link.textContent = item.sourceUrl;
      source.appendChild(link);
    } else {
      source.textContent = '-';
    }

    tr.appendChild(time);
    tr.appendChild(competitor);
    tr.appendChild(category);
    tr.appendChild(title);
    tr.appendChild(summary);
    tr.appendChild(significance);
    tr.appendChild(source);

    tbody.appendChild(tr);
  }
}

function readFindingsFilters() {
  const params = new URLSearchParams();

  const competitor = state.findingsFilters.selectedCompetitors || [];
  const category = byId('filter-category').value;
  const keyword = byId('filter-keyword').value.trim();
  const from = byId('filter-from').value;
  const to = byId('filter-to').value;

  for (const name of competitor) {
    params.append('competitor', name);
  }
  if (category) params.set('category', category);
  if (keyword) params.set('keyword', keyword);
  if (from) params.set('from', from);
  if (to) params.set('to', to);
  params.set('limit', '120');

  return params.toString();
}

function renderReports(items) {
  const tbody = byId('reports-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!items.length) {
    clearTable('reports-table-body', 5, '暂无报告');
    byId('report-meta').textContent = '请选择一份报告查看详情。';
    byId('report-content').innerHTML = '';
    renderReportQa(null);
    return;
  }

  for (const item of items) {
    const tr = document.createElement('tr');
    tr.dataset.reportId = item.id;
    tr.style.cursor = 'pointer';
    if (item.id === state.selectedReportId) {
      tr.style.background = '#ecf4ff';
    }

    const createdAt = document.createElement('td');
    createdAt.textContent = formatDate(item.createdAt);

    const title = document.createElement('td');
    title.textContent = item.title || '-';

    const type = document.createElement('td');
    type.textContent = reportTypeLabel(item.type);

    const sourceCount = document.createElement('td');
    sourceCount.textContent = String(item.sourceCount || 0);

    const range = document.createElement('td');
    range.textContent = formatDateRange(item.rangeStart, item.rangeEnd);

    tr.appendChild(createdAt);
    tr.appendChild(title);
    tr.appendChild(type);
    tr.appendChild(sourceCount);
    tr.appendChild(range);

    tr.addEventListener('click', () => {
      state.selectedReportId = item.id;
      renderReports(state.reports);
      renderSelectedReport();
    });

    tbody.appendChild(tr);
  }

  if (!state.selectedReportId || !items.some((item) => item.id === state.selectedReportId)) {
    state.selectedReportId = items[0].id;
  }

  renderSelectedReport();
}

function renderSelectedReport() {
  const report = state.reports.find((item) => item.id === state.selectedReportId);
  if (!report) {
    byId('report-meta').textContent = '请选择一份报告查看详情。';
    byId('report-content').innerHTML = '';
    renderReportQa(null);
    return;
  }

  byId('report-meta').textContent = [
    `报告：${report.title}`,
    `类型：${reportTypeLabel(report.type)}`,
    `生成时间：${formatDate(report.createdAt)}`,
    `来源条数：${report.sourceCount || 0}`,
    `时间窗口：${formatDateRange(report.rangeStart, report.rangeEnd)}`
  ].join(' | ');

  const structured = normalizeStructuredReport(report);
  if (structured) {
    renderStructuredReport(report, structured);
    renderReportQa(report);
    return;
  }

  renderLegacyReport(report.content || '');
  renderReportQa(report);
}

function renderJobs(items) {
  const tbody = byId('jobs-table-body');
  if (!tbody) return;
  tbody.innerHTML = '';

  if (!items.length) {
    clearTable('jobs-table-body', 4, '暂无任务日志');
    return;
  }

  for (const item of items) {
    const tr = document.createElement('tr');

    const time = document.createElement('td');
    time.textContent = formatDate(item.createdAt);

    const type = document.createElement('td');
    type.textContent = item.type || '-';

    const statusCell = document.createElement('td');
    const statusTag = document.createElement('span');
    statusTag.className = `status-pill ${item.status || ''}`;
    statusTag.textContent = item.status || '-';
    statusCell.appendChild(statusTag);

    const message = document.createElement('td');
    message.textContent = item.message || '-';

    tr.appendChild(time);
    tr.appendChild(type);
    tr.appendChild(statusCell);
    tr.appendChild(message);

    tbody.appendChild(tr);
  }
}

async function loadConfig(options = {}) {
  const data = await requestJson('/config');
  state.config = data;
  if (data.heartbeat) {
    state.heartbeat = normalizeHeartbeatConfig(data.heartbeat);
    renderHeartbeatForm();
  }

  if (!options.preserveEditor) {
    state.editConfig = deepClone(data.competitors || []);
    state.editorOpenCompetitor = state.editConfig.length ? 0 : null;
  }

  populateFindingsFilters();
  renderCoverage();
  renderConfigEditor();
}

async function loadStatus() {
  const data = await requestJson('/status');
  state.status = data;
  if (data.scheduler?.heartbeat) {
    state.heartbeat = normalizeHeartbeatConfig(data.scheduler.heartbeat);
    renderHeartbeatForm();
  }
  updateHeaderLine();
  renderHeaderKpis();
  updateScanControls();
  syncScanWatcher();
  syncFindingsWatcher();
}

async function loadMetrics(options = {}) {
  const { silent = false } = options;
  const data = await requestJson('/metrics?limit=220&days=14', { timeoutMs: 30000 });
  state.metrics = data;
  renderCharts();
  renderHeaderKpis();

  if (!silent && typeof data.sampleSize === 'number') {
    setMessage('dashboard-message', `统计已更新（样本 ${data.sampleSize} 条）。`, 'success');
  }
}

async function loadCompetitorBoard(options = {}) {
  const { silent = false } = options;
  const daysSelect = byId('board-days-select');
  const selectedDays = Number(daysSelect?.value || state.board.days || 180);
  state.board.days = Math.max(30, Math.min(730, selectedDays || 180));

  if (!silent) {
    setMessage('board-message', '正在加载竞对经营看板...', 'warning');
  }

  const data = await requestJson(`/dashboard/competitors?days=${state.board.days}`, {
    timeoutMs: 40000
  });

  state.board.data = data;
  renderCompetitorBoard();

  if (!silent) {
    const activeCount = Number(data.summary?.activeCompetitors || 0);
    setMessage('board-message', `看板刷新完成：活跃竞对 ${activeCount} 家。`, 'success');
  }
}

async function loadFindings(options = {}) {
  const { silent = false, allowConcurrent = false } = options;
  if (!allowConcurrent && state.findingsWatch.inFlight) {
    return;
  }

  if (state.findingsFilters.competitorPanelOpen) {
    setFindingsCompetitorPanel(false);
  }

  state.findingsWatch.inFlight = true;

  try {
  if (!silent) {
    setMessage('findings-message', '正在加载情报...', 'warning');
  }

  const query = readFindingsFilters();
  const data = await requestJson(`/findings?${query}`);
  renderFindings(data.items || []);

  if (!silent) {
    setMessage('findings-message', `查询完成：${data.items.length} 条。`, 'success');
  }
  } finally {
    state.findingsWatch.inFlight = false;
  }
}

async function loadReports(options = {}) {
  const { silent = false } = options;
  if (!silent) {
    setMessage('reports-message', '正在加载报告...', 'warning');
  }

  const reportType = byId('report-type-filter').value;
  const params = new URLSearchParams();
  params.set('limit', '50');
  if (reportType) params.set('type', reportType);

  const data = await requestJson(`/reports?${params.toString()}`);
  state.reports = data.items || [];
  renderReports(state.reports);

  if (!silent) {
    setMessage('reports-message', `查询完成：${state.reports.length} 份报告。`, 'success');
  }
}

async function loadJobs(options = {}) {
  const { silent = false } = options;
  if (!silent) {
    setMessage('jobs-message', '正在加载任务日志...', 'warning');
  }

  const data = await requestJson('/jobs?limit=150');
  renderJobs(data.items || []);

  if (!silent) {
    setMessage('jobs-message', `查询完成：${data.items.length} 条日志。`, 'success');
  }
}

async function refreshActiveData(options = {}) {
  const { silent = true, includeAll = false } = options;

  if (state.refresh.inFlight) return;
  state.refresh.inFlight = true;

  try {
    const tasks = [loadStatus()];

    if (includeAll || state.activeTab === 'dashboard') {
      tasks.push(loadMetrics({ silent: true }));
    }

    if (includeAll || state.activeTab === 'board') {
      tasks.push(loadCompetitorBoard({ silent: true }));
    }

    if (includeAll) {
      tasks.push(loadFindings({ silent }), loadReports({ silent }), loadJobs({ silent }));
    } else if (state.activeTab === 'findings') {
      tasks.push(loadFindings({ silent }));
    } else if (state.activeTab === 'reports') {
      tasks.push(loadReports({ silent }));
    } else if (state.activeTab === 'jobs') {
      tasks.push(loadJobs({ silent }));
    }

    await Promise.all(tasks);
    state.refresh.lastAt = new Date().toISOString();
    updateLastRefresh();
  } finally {
    state.refresh.inFlight = false;
  }
}

function stopScanWatcher() {
  if (state.scanWatch.timerId) {
    clearInterval(state.scanWatch.timerId);
    state.scanWatch.timerId = null;
  }
  state.scanWatch.inFlight = false;
}

function startScanWatcher() {
  if (state.scanWatch.timerId) return;

  state.scanWatch.timerId = setInterval(async () => {
    if (state.scanWatch.inFlight) return;
    state.scanWatch.inFlight = true;

    try {
      await loadStatus();
      await loadJobs({ silent: true });
      await loadMetrics({ silent: true });

      if (!isScanRunning()) {
        stopScanWatcher();

        const result = state.status?.scanner?.lastResult;
        if (result?.stopped) {
          setMessage('dashboard-message', `扫描已截停：累计写入 ${result.totalWritten || 0} 条。`, 'warning');
        } else {
          setMessage('dashboard-message', `扫描结束：累计写入 ${result?.totalWritten || 0} 条。`, 'success');
        }

        await refreshActiveData({ silent: true, includeAll: true });
      }
    } catch (error) {
      setMessage('dashboard-message', `扫描进度刷新失败：${error.message}`, 'error');
    } finally {
      state.scanWatch.inFlight = false;
    }
  }, 2000);
}

function syncScanWatcher() {
  if (isScanRunning()) {
    startScanWatcher();
  } else {
    stopScanWatcher();
  }
}

function getFindingsWatchIntervalMs() {
  return isScanRunning() ? 2000 : 4000;
}

function stopFindingsWatcher() {
  if (state.findingsWatch.timerId) {
    clearInterval(state.findingsWatch.timerId);
    state.findingsWatch.timerId = null;
  }
  state.findingsWatch.inFlight = false;
}

function startFindingsWatcher() {
  const intervalMs = getFindingsWatchIntervalMs();

  if (state.findingsWatch.timerId && state.findingsWatch.intervalMs === intervalMs) {
    return;
  }

  stopFindingsWatcher();
  state.findingsWatch.intervalMs = intervalMs;

  const poll = async () => {
    if (state.activeTab !== 'findings') return;
    try {
      await loadFindings({ silent: true });
    } catch (error) {
      setMessage('findings-message', `情报实时刷新失败：${error.message}`, 'error');
    }
  };

  state.findingsWatch.timerId = setInterval(poll, intervalMs);
  poll().catch(() => {});
}

function syncFindingsWatcher() {
  if (state.activeTab !== 'findings') {
    stopFindingsWatcher();
    return;
  }
  startFindingsWatcher();
}

function applyAutoRefreshInterval(intervalMs) {
  if (state.refresh.timerId) {
    clearInterval(state.refresh.timerId);
    state.refresh.timerId = null;
  }

  state.refresh.intervalMs = intervalMs;

  if (intervalMs > 0) {
    state.refresh.timerId = setInterval(() => {
      refreshActiveData({ silent: true }).catch((error) => {
        byId('header-status-line').textContent = `自动刷新失败：${error.message}`;
        setHeaderStatusTone('error');
      });
    }, intervalMs);
  }
}

async function withAction(buttonId, messageId, action) {
  const btn = byId(buttonId);
  if (!btn) return;
  btn.disabled = true;

  try {
    await action();
  } catch (error) {
    setMessage(messageId, error.message, 'error');
  } finally {
    btn.disabled = false;
    updateScanControls();
  }
}

async function runManualScan() {
  await withAction('btn-scan', 'dashboard-message', async () => {
    setMessage('dashboard-message', '正在启动扫描任务...', 'warning');
    await requestJson('/scan/run', {
      method: 'POST',
      body: JSON.stringify({ wait: false }),
      timeoutMs: 20000
    });

    setMessage('dashboard-message', '扫描已启动。系统正在持续刷新进度，可随时点击“截停当前扫描”。', 'warning');
    await refreshActiveData({ silent: true, includeAll: false });
    startScanWatcher();
  });
}

async function stopManualScan() {
  await withAction('btn-scan-stop', 'dashboard-message', async () => {
    setMessage('dashboard-message', '正在发送截停指令...', 'warning');

    const data = await requestJson('/scan/stop', {
      method: 'POST',
      body: JSON.stringify({ reason: '用户手动截停扫描以控制API消耗' }),
      timeoutMs: 15000
    });

    if (!data.accepted) {
      setMessage('dashboard-message', data.message || '当前没有可截停的扫描任务。', 'warning');
      return;
    }

    setMessage('dashboard-message', data.message || '截停指令已发送，正在终止当前请求。', 'warning');
    startScanWatcher();
  });
}

async function runCoverageBoost() {
  await withAction('btn-coverage-boost', 'dashboard-message', async () => {
    const startedAt = Date.now();
    setMessage('dashboard-message', '正在执行定向覆盖增强（财报/IR/权威来源）...', 'warning');

    const heartbeat = setInterval(() => {
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      setMessage('dashboard-message', `定向覆盖增强执行中，已等待 ${seconds} 秒...`, 'warning');
    }, 8000);

    let data;
    try {
      data = await requestJson('/scan/coverage-boost', {
        method: 'POST',
        body: JSON.stringify({ maxResults: 5 }),
        timeoutMs: 960000
      });
    } finally {
      clearInterval(heartbeat);
    }

    const result = data.result || {};
    setMessage(
      'dashboard-message',
      `覆盖增强完成：写入 ${result.totalWritten || 0}（新增 ${result.inserted || 0} / 更新 ${result.updated || 0}），有效候选 ${result.keptCandidates || 0}。`,
      'success'
    );

    if (state.activeTab === 'board') {
      setMessage('board-message', '已补齐覆盖并刷新看板。', 'success');
    }

    await refreshActiveData({ silent: true, includeAll: true });
  });
}

async function runWeeklyReport(messageTarget = 'dashboard-message', buttonId = 'btn-weekly') {
  await withAction(buttonId, messageTarget, async () => {
    const startedAt = Date.now();
    setMessage(messageTarget, '正在生成竞对动态周报，系统将持续等待结果...', 'warning');

    const heartbeat = setInterval(() => {
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      setMessage(messageTarget, `竞对动态周报生成中，已等待 ${seconds} 秒...`, 'warning');
    }, 8000);

    try {
      await requestJson('/reports/weekly/generate', { method: 'POST', timeoutMs: 720000 });
    } finally {
      clearInterval(heartbeat);
    }

    setMessage(messageTarget, '竞对动态周报生成成功。', 'success');
    if (messageTarget !== 'dashboard-message') {
      setMessage('dashboard-message', '竞对动态周报生成成功。', 'success');
    }

    await refreshActiveData({ silent: true, includeAll: true });
  });
}

async function runTrendReport(messageTarget = 'dashboard-message', buttonId = 'btn-trend') {
  await withAction(buttonId, messageTarget, async () => {
    const startedAt = Date.now();
    setMessage(messageTarget, '正在生成行业趋势研判报告，系统将持续等待结果...', 'warning');

    const heartbeat = setInterval(() => {
      const seconds = Math.round((Date.now() - startedAt) / 1000);
      setMessage(messageTarget, `行业趋势研判报告生成中，已等待 ${seconds} 秒...`, 'warning');
    }, 8000);

    try {
      await requestJson('/reports/trends/generate', { method: 'POST', timeoutMs: 720000 });
    } finally {
      clearInterval(heartbeat);
    }

    setMessage(messageTarget, '行业趋势研判报告生成成功。', 'success');
    if (messageTarget !== 'dashboard-message') {
      setMessage('dashboard-message', '行业趋势研判报告生成成功。', 'success');
    }

    await refreshActiveData({ silent: true, includeAll: true });
  });
}

async function upgradeReportsToFormal() {
  await withAction('btn-reports-upgrade-formal', 'reports-message', async () => {
    setMessage('reports-message', '正在升级历史报告为正式版格式...', 'warning');
    const data = await requestJson('/reports/upgrade-formal', {
      method: 'POST',
      timeoutMs: 180000
    });

    const result = data.result || {};
    const updated = Number(result.updated || 0);
    const skipped = Number(result.skipped || 0);
    setMessage('reports-message', `升级完成：更新 ${updated} 份，跳过 ${skipped} 份。`, 'success');
    setMessage('dashboard-message', `历史报告正式化升级完成（更新 ${updated} 份）。`, 'success');
    await refreshActiveData({ silent: true, includeAll: true });
  });
}

async function exportSelectedReport(format = 'word') {
  const report = state.reports.find((item) => item.id === state.selectedReportId);
  if (!report) {
    setMessage('reports-message', '请先选择一份报告。', 'warning');
    return;
  }

  const safeFormat = format === 'pdf' ? 'pdf' : 'word';
  const ext = safeFormat === 'pdf' ? 'pdf' : 'docx';
  const endpoint = safeFormat === 'pdf'
    ? `/reports/${encodeURIComponent(report.id)}/export/pdf`
    : `/reports/${encodeURIComponent(report.id)}/export/word`;

  setMessage('reports-message', `正在导出 ${ext.toUpperCase()}...`, 'warning');

  try {
    const response = await fetch(`${API_BASE}${endpoint}`, { method: 'GET' });
    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.json();
      } catch {
        payload = null;
      }
      throw new Error(payload?.error || `导出失败：${response.status}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    const suffix = String(report.id || '').slice(-6);
    const baseName = (report.title || 'report').replace(/[\\/:*?"<>|]/g, '_').replace(/\s+/g, '_');
    link.download = `${baseName}_${suffix}.${ext}`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);

    setMessage('reports-message', `导出完成：${ext.toUpperCase()}。`, 'success');
  } catch (error) {
    setMessage('reports-message', error.message, 'error');
  }
}

async function askReportQuestion() {
  const report = state.reports.find((item) => item.id === state.selectedReportId);
  if (!report) {
    setMessage('report-qa-message', '请先在历史报告中选择一份报告。', 'warning');
    return;
  }

  const input = byId('report-qa-question');
  const question = String(input?.value || '').trim();
  if (question.length < 2) {
    setMessage('report-qa-message', '请输入具体问题。', 'warning');
    return;
  }

  await withAction('btn-report-qa-ask', 'report-qa-message', async () => {
    let qa = null;
    state.qaStream = {
      inFlight: true,
      reportId: report.id,
      question,
      answer: '',
      startedAt: new Date().toISOString()
    };
    renderReportQa(report);
    setMessage('report-qa-message', '问答流式生成中...', 'warning');

    try {
      await requestNdjson(`/reports/${encodeURIComponent(report.id)}/qa/stream`, {
        method: 'POST',
        body: JSON.stringify({ question }),
        timeoutMs: 240000
      }, {
        onEvent: (event) => {
          if (!event || typeof event !== 'object') return;

          if (event.type === 'delta') {
            state.qaStream.answer += String(event.text || '');
            renderReportQa(report);
            return;
          }

          if (event.type === 'warning') {
            setMessage('report-qa-message', event.message || '问答已切换为回退模式。', 'warning');
            return;
          }

          if (event.type === 'done') {
            qa = event.qa || null;
          }
        }
      });
    } finally {
      state.qaStream.inFlight = false;
      state.qaStream.reportId = null;
      state.qaStream.question = '';
      state.qaStream.answer = '';
      state.qaStream.startedAt = null;
    }

    if (!qa) {
      throw new Error('问答未完成，请重试。');
    }

    const target = state.reports.find((item) => item.id === report.id);
    if (target) {
      const history = Array.isArray(target.qaHistory) ? target.qaHistory : [];
      target.qaHistory = [qa, ...history].slice(0, 50);
      renderReportQa(target);
    }

    if (input) {
      input.value = '';
    }

    setMessage('report-qa-message', '问答回复已生成。', 'success');
  });
}

async function saveMonitoringConfig() {
  await withAction('btn-config-save', 'config-message', async () => {
    const validationError = validateEditConfig();
    if (validationError) {
      throw new Error(validationError);
    }

    setMessage('config-message', '正在保存监测配置...', 'warning');

    await requestJson('/config/competitors', {
      method: 'PUT',
      body: JSON.stringify({ competitors: state.editConfig })
    });

    await loadConfig();
    await refreshActiveData({ silent: true, includeAll: true });

    setMessage('config-message', '监测配置已保存并生效。', 'success');
    setMessage('dashboard-message', '监测配置更新成功。', 'success');
  });
}

function switchTab(tabName) {
  state.activeTab = tabName;

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('active', tab.dataset.tab === tabName);
  });

  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('active', panel.id === tabName);
  });

  if (tabName === 'findings') {
    loadFindings({ allowConcurrent: true }).catch((error) => setMessage('findings-message', error.message, 'error'));
  }
  if (tabName === 'board') {
    loadCompetitorBoard().catch((error) => setMessage('board-message', error.message, 'error'));
  }
  if (tabName === 'reports') {
    loadReports().catch((error) => setMessage('reports-message', error.message, 'error'));
  }
  if (tabName === 'jobs') {
    loadJobs().catch((error) => setMessage('jobs-message', error.message, 'error'));
  }

  syncFindingsWatcher();
}

function bindEvents() {
  const bind = (id, eventName, handler) => {
    const node = byId(id);
    if (!node) return null;
    node.addEventListener(eventName, handler);
    return node;
  };

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  bind('btn-refresh-all', 'click', async () => {
    try {
      await refreshActiveData({ silent: true, includeAll: true });
      setMessage('dashboard-message', '全部数据已刷新。', 'success');
    } catch (error) {
      setMessage('dashboard-message', error.message, 'error');
    }
  });

  bind('auto-refresh-select', 'change', (event) => {
    const interval = Number(event.target.value || 0);
    applyAutoRefreshInterval(interval);
    const text = interval > 0 ? `已开启自动刷新：${Math.round(interval / 1000)} 秒` : '已关闭自动刷新';
    setMessage('dashboard-message', text, 'success');
  });

  bind('btn-board-refresh', 'click', () => {
    loadCompetitorBoard().catch((error) => setMessage('board-message', error.message, 'error'));
  });

  bind('board-days-select', 'change', () => {
    loadCompetitorBoard().catch((error) => setMessage('board-message', error.message, 'error'));
  });

  const boardPanel = byId('board');
  if (boardPanel) {
    boardPanel.addEventListener('click', (event) => {
      const pickTarget = event.target.closest('[data-board-pick]');
      if (pickTarget) {
        pickBoardCompetitor(pickTarget.getAttribute('data-board-pick') || '');
        return;
      }

      if (event.target.closest('a')) return;
      const rowTarget = event.target.closest('[data-board-competitor]');
      if (rowTarget) {
        pickBoardCompetitor(rowTarget.getAttribute('data-board-competitor') || '');
      }
    });

    boardPanel.addEventListener('keydown', (event) => {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      const target = event.target.closest('[data-board-competitor], [data-board-pick]');
      if (!target) return;
      event.preventDefault();
      if (target.hasAttribute('data-board-pick')) {
        pickBoardCompetitor(target.getAttribute('data-board-pick') || '');
      } else {
        pickBoardCompetitor(target.getAttribute('data-board-competitor') || '');
      }
    });
  }

  bind('btn-scan', 'click', runManualScan);
  bind('btn-scan-stop', 'click', stopManualScan);
  bind('btn-coverage-boost', 'click', runCoverageBoost);
  bind('btn-config-toggle', 'click', () => {
    setConfigPanelCollapsed(!state.ui.configPanelCollapsed);
  });

  bind('btn-weekly', 'click', () => runWeeklyReport('dashboard-message', 'btn-weekly'));
  bind('btn-trend', 'click', () => runTrendReport('dashboard-message', 'btn-trend'));
  bind('btn-weekly-reports', 'click', () => runWeeklyReport('reports-message', 'btn-weekly-reports'));
  bind('btn-trend-reports', 'click', () => runTrendReport('reports-message', 'btn-trend-reports'));

  bind('btn-report-generate', 'click', () => {
    const type = String(byId('report-generate-type')?.value || 'weekly');
    if (type === 'trend') {
      runTrendReport('reports-message', 'btn-report-generate');
      return;
    }
    runWeeklyReport('reports-message', 'btn-report-generate');
  });

  bind('btn-report-export', 'click', () => {
    const format = String(byId('report-export-format')?.value || 'word').toLowerCase();
    exportSelectedReport(format === 'pdf' ? 'pdf' : 'word');
  });

  bind('btn-reports-upgrade-formal', 'click', upgradeReportsToFormal);

  // 兼容历史页面按钮 ID（若存在则继续支持）
  bind('btn-report-export-word', 'click', () => exportSelectedReport('word'));
  bind('btn-report-export-pdf', 'click', () => exportSelectedReport('pdf'));

  bind('btn-heartbeat-save', 'click', saveHeartbeatConfig);
  bind('btn-heartbeat-reload', 'click', () => {
    loadHeartbeat({ silent: false }).catch((error) => setMessage('heartbeat-message', error.message, 'error'));
  });

  bind('hb-scan-enabled', 'change', syncHeartbeatFieldAvailability);
  bind('hb-weekly-enabled', 'change', syncHeartbeatFieldAvailability);
  bind('hb-trend-enabled', 'change', syncHeartbeatFieldAvailability);

  bind('findings-filter-form', 'submit', (event) => {
    event.preventDefault();
    loadFindings({ allowConcurrent: true }).catch((error) => setMessage('findings-message', error.message, 'error'));
  });

  bind('filter-competitor-trigger', 'click', (event) => {
    event.stopPropagation();
    setFindingsCompetitorPanel(!state.findingsFilters.competitorPanelOpen);
  });

  bind('btn-findings-competitor-all', 'click', () => {
    state.findingsFilters.selectedCompetitors = getConfiguredCompetitorNames();
    renderFindingsCompetitorOptions();
    updateFindingsCompetitorSummary();
  });

  bind('btn-findings-competitor-none', 'click', () => {
    state.findingsFilters.selectedCompetitors = [];
    renderFindingsCompetitorOptions();
    updateFindingsCompetitorSummary();
  });

  bind('btn-findings-reset', 'click', () => {
    state.findingsFilters.selectedCompetitors = [];
    renderFindingsCompetitorOptions();
    updateFindingsCompetitorSummary();
    byId('filter-category').value = '';
    byId('filter-keyword').value = '';
    byId('filter-from').value = '';
    byId('filter-to').value = '';
    loadFindings({ allowConcurrent: true }).catch((error) => setMessage('findings-message', error.message, 'error'));
  });

  document.addEventListener('click', (event) => {
    if (!state.findingsFilters.competitorPanelOpen) return;
    const picker = byId('filter-competitor');
    if (!picker || picker.contains(event.target)) return;
    setFindingsCompetitorPanel(false);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!state.findingsFilters.competitorPanelOpen) return;
    setFindingsCompetitorPanel(false);
  });

  bind('btn-report-query', 'click', () => {
    loadReports().catch((error) => setMessage('reports-message', error.message, 'error'));
  });
  bind('report-type-filter', 'change', () => {
    loadReports().catch((error) => setMessage('reports-message', error.message, 'error'));
  });

  bind('btn-report-qa-ask', 'click', () => {
    askReportQuestion().catch((error) => setMessage('report-qa-message', error.message, 'error'));
  });

  bind('report-qa-question', 'keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      askReportQuestion().catch((error) => setMessage('report-qa-message', error.message, 'error'));
    }
  });

  bind('btn-jobs-refresh', 'click', () => {
    loadJobs().catch((error) => setMessage('jobs-message', error.message, 'error'));
  });

  bind('btn-config-add-competitor', 'click', () => {
    state.editConfig.push(getDefaultCompetitor());
    state.editorOpenCompetitor = state.editConfig.length - 1;
    renderConfigEditor();
  });

  bind('btn-config-reload', 'click', async () => {
    try {
      await loadConfig();
      setMessage('config-message', '已重新加载监测配置。', 'success');
    } catch (error) {
      setMessage('config-message', error.message, 'error');
    }
  });

  bind('btn-config-expand-all', 'click', () => {
    setAllConfigOpen(true);
  });

  bind('btn-config-collapse-all', 'click', () => {
    setAllConfigOpen(false);
  });

  bind('btn-config-save', 'click', saveMonitoringConfig);

  const editor = byId('config-editor-list');
  if (editor) {
    editor.addEventListener('input', handleConfigInput);
    editor.addEventListener('click', handleConfigAction);
  }
}

async function initialize() {
  bindEvents();
  setConfigPanelCollapsed(getStoredConfigPanelCollapsed(), { persist: false });
  renderHeartbeatForm();
  renderReportQa(null);

  try {
    await loadConfig();
    await loadHeartbeat({ silent: true });
    await refreshActiveData({ silent: true, includeAll: true });
    applyAutoRefreshInterval(Number(byId('auto-refresh-select').value || 0));
    updateLastRefresh();
    updateScanControls();
    syncScanWatcher();
  } catch (error) {
    setMessage('dashboard-message', error.message, 'error');
    setHeaderStatusTone('error');
  }
}

initialize();
