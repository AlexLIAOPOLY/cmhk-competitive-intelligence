/* ═══════════════════════════════════════════════════════════════════
   Token Hub 运营管理
   ═══════════════════════════════════════════════════════════════════ */

// 动态检测 API 基础路径
function detectApiBase() {
  const path = window.location.pathname;
  if (path.includes('/static/')) {
    return path.replace(/\/static\/.*/, '');
  }
  if (path.endsWith('.html')) {
    return path.replace(/\/[^/]*$/, '') || '';
  }
  return '';
}
const API_BASE = detectApiBase();

const api = async (path, options) => {
  const url = path.startsWith('http') ? path : (API_BASE + path);
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || payload.message || ('HTTP ' + response.status));
  }
  return payload;
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const formatNumber = (value) => Number(value || 0).toLocaleString();
const leadStatuses = ['新线索', '已联系', '试用中', '已转化', '已忽略'];

/* ═══════════════════════════════════════════════════════════════════
   1. 侧边栏导航：平滑滚动 + 滚动联动
   ═══════════════════════════════════════════════════════════════════ */

function initSectionNav() {
  const navLinks = document.querySelectorAll('.client-section-nav a');
  const sections = ['overview', 'leadsPanel', 'ordersPanel', 'runsPanel']
    .map(id => document.getElementById(id))
    .filter(Boolean);

  navLinks.forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const href = link.getAttribute('href');
      const targetId = href ? href.replace('#', '') : '';
      const target = document.getElementById(targetId);
      if (!target) return;

      const offset = 80;
      const top = target.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });

      navLinks.forEach((item) => item.classList.remove('is-active'));
      link.classList.add('is-active');
    });
  });

  if ('IntersectionObserver' in window && sections.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const id = entry.target.id;
          navLinks.forEach((link) => {
            const isMatch = link.getAttribute('href') === '#' + id;
            link.classList.toggle('is-active', isMatch);
          });
        }
      });
    }, {
      rootMargin: '-80px 0px -60% 0px',
      threshold: 0
    });
    sections.forEach((section) => observer.observe(section));
  }
}

/* ═══════════════════════════════════════════════════════════════════
   2. 顶部导航高亮
   ═══════════════════════════════════════════════════════════════════ */

function initTopNav() {
  const current = window.location.pathname.split('/').pop() || 'token-hub-admin.html';
  document.querySelectorAll('.client-nav a').forEach((link) => {
    const href = link.getAttribute('href') || '';
    const name = href.split('/').pop();
    link.classList.toggle('is-active', name === current);
  });
}

/* ═══════════════════════════════════════════════════════════════════
   3. 数据渲染
   ═══════════════════════════════════════════════════════════════════ */

function setMessage(message, tone) {
  const node = document.querySelector('#adminMessage');
  if (!node) return;
  node.textContent = message;
  node.dataset.tone = tone || '';
}

function renderSummary(summary) {
  const cards = [
    ['客户线索', formatNumber(summary.lead_count)],
    ['有效线索', formatNumber(summary.active_leads)],
    ['今日 Token 消耗', formatNumber(summary.usage_today)],
    ['演示订单', formatNumber(summary.order_count)],
  ];
  document.querySelector('#stats').innerHTML = cards.map(([label, value]) =>
    `<div class="stat-card"><div class="stat-card-label">${label}</div><div class="stat-card-value">${value}</div></div>`
  ).join('');

  const nextCrawl = document.querySelector('#nextCrawl');
  if (nextCrawl) {
    nextCrawl.textContent = (summary.next_crawl_at || '—').replace('T', ' ').replace('+08:00', '');
  }
}

function renderLeads(leads) {
  const target = document.querySelector('#leads');
  if (!target) return;
  if (!leads.length) {
    target.innerHTML = '<tr><td colspan="5" class="empty-state">暂无客户线索。</td></tr>';
    return;
  }
  target.innerHTML = leads.map((lead) => `<tr>
    <td><b>${escapeHtml(lead.company_name)}</b></td>
    <td>${escapeHtml(lead.industry || '—')}</td>
    <td>${escapeHtml(lead.source || '—')}</td>
    <td class="score">${escapeHtml(lead.score)}</td>
    <td><select class="lead-status" data-id="${escapeHtml(lead.id)}" aria-label="${escapeHtml(lead.company_name)} 状态">
      ${leadStatuses.map((status) => `<option value="${escapeHtml(status)}" ${status === lead.status ? 'selected' : ''}>${status}</option>`).join('')}
    </select></td>
  </tr>`).join('');

  document.querySelectorAll('.lead-status').forEach((select) => {
    select.addEventListener('change', async () => {
      const original = select.dataset.previous || select.value;
      select.disabled = true;
      setMessage('正在保存线索状态……');
      try {
        await api('/api/token-hub/leads/status', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({lead_id: select.dataset.id, status: select.value}),
        });
        select.dataset.previous = select.value;
        setMessage(`线索状态已更新为「${select.value}」。`, 'success');
      } catch (error) {
        select.value = original;
        setMessage(`状态更新失败：${error.message}`, 'error');
      } finally {
        select.disabled = false;
      }
    });
  });
}

function renderOrders(orders) {
  const target = document.querySelector('#orders');
  if (!target) return;
  target.innerHTML = orders.length ? orders.map((order) => `<tr>
    <td><b>${escapeHtml(order.id)}</b></td>
    <td>${escapeHtml(order.plan_id)}</td>
    <td>HK$${escapeHtml(order.amount_hkd)}</td>
    <td>${escapeHtml(order.status)}</td>
  </tr>`).join('') : '<tr><td colspan="4" class="empty-state">暂无订单。</td></tr>';
}

function renderRuns(runs) {
  const target = document.querySelector('#runs');
  if (!target) return;
  target.innerHTML = runs.length ? runs.map((run) => `<div class="run-item">
    <b>${escapeHtml(run.source)}</b> · ${escapeHtml(run.status)}
    <small>${escapeHtml(run.records)} records · ${escapeHtml(run.started_at)}</small>
  </div>`).join('') : '<div class="empty-state">暂无运行记录。隔离线索爬虫会按计划运行。</div>';
}

/* ═══════════════════════════════════════════════════════════════════
   4. 加载数据
   ═══════════════════════════════════════════════════════════════════ */

async function load() {
  const refresh = document.querySelector('#refresh');
  if (refresh) refresh.disabled = true;
  setMessage('正在读取运营数据……');

  try {
    const [summaryPayload, leadsPayload, runsPayload, ordersPayload] = await Promise.all([
      api('/api/token-hub/summary'),
      api('/api/token-hub/leads?limit=100'),
      api('/api/token-hub/crawl-runs'),
      api('/api/token-hub/orders'),
    ]);
    renderSummary(summaryPayload.summary);
    renderLeads(leadsPayload.leads);
    renderOrders(ordersPayload.orders);
    renderRuns(runsPayload.runs);
    setMessage(`已更新 · ${new Date().toLocaleTimeString('zh-HK', {hour: '2-digit', minute: '2-digit', second: '2-digit'})}`, 'success');
  } catch (error) {
    setMessage(`读取失败：${error.message}`, 'error');
  } finally {
    if (refresh) refresh.disabled = false;
  }
}

/* ═══════════════════════════════════════════════════════════════════
   5. 初始化
   ═══════════════════════════════════════════════════════════════════ */

function init() {
  initSectionNav();
  initTopNav();

  const refreshBtn = document.querySelector('#refresh');
  if (refreshBtn) refreshBtn.addEventListener('click', load);

  load();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
