const $ = (selector) => document.querySelector(selector);

// 动态检测 API 基础路径，兼容本地文件、子目录部署和根目录部署
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
    const msg = payload.error || payload.message || ('HTTP ' + response.status);
    throw new Error(msg);
  }
  return payload;
};

const escapeHtml = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]));
const state = { lab: null };

/* ═══════════════════════════════════════════════════════════════════
   1. 侧边栏导航：平滑滚动 + 滚动联动
   ═══════════════════════════════════════════════════════════════════ */

function initSectionNav() {
  const navLinks = document.querySelectorAll('.client-section-nav a');
  const sections = ['assistant', 'plans', 'trust'].map(id => document.getElementById(id)).filter(Boolean);

  // 点击导航：平滑滚动到对应区域，并更新高亮
  navLinks.forEach((link) => {
    link.addEventListener('click', (event) => {
      event.preventDefault();
      const href = link.getAttribute('href');
      const targetId = href ? href.replace('#', '') : '';
      const target = document.getElementById(targetId);
      if (!target) return;

      // 平滑滚动，偏移量避免被 sticky header 遮挡
      const offset = 90;
      const top = target.getBoundingClientRect().top + window.scrollY - offset;
      window.scrollTo({ top, behavior: 'smooth' });

      // 更新高亮（滚动联动也会处理，这里先立即反馈）
      navLinks.forEach((item) => item.classList.remove('is-active'));
      link.classList.add('is-active');
    });
  });

  // 滚动联动：用 Intersection Observer 自动高亮当前可视区域
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
   2. 顶部导航：当前页面高亮自动同步
   ═══════════════════════════════════════════════════════════════════ */

function initTopNav() {
  const current = window.location.pathname.split('/').pop() || 'token-hub.html';
  document.querySelectorAll('.client-nav a').forEach((link) => {
    const href = link.getAttribute('href') || '';
    const name = href.split('/').pop();
    link.classList.toggle('is-active', name === current);
  });
}

/* ═══════════════════════════════════════════════════════════════════
   3. 业务逻辑（模型路由、套餐、对话）
   ═══════════════════════════════════════════════════════════════════ */

function currentTask() {
  return (state.lab?.tasks || []).find((task) => task.id === $('#taskId').value);
}

function updateRouteMeta() {
  const task = currentTask();
  $('#routeMeta').textContent = task
    ? `${task.name} · ${task.selected_model_id} · ${task.route_source === 'manual' ? '手动路由' : '系统路由'}`
    : '选择任务后会使用对应的内部模型';
}

function updateExternalPolicy() {
  const policy = state.lab?.overflow_policy || {};
  const effective = Boolean(policy.effective);
  const checkbox = $('#allowExternal');
  checkbox.disabled = !effective;
  checkbox.checked = false;
  $('#externalState').textContent = effective ? '策略已生效' : '策略已关闭';
  $('#externalState').classList.toggle('is-ready', effective);
  checkbox.title = effective
    ? '仅公开或已脱敏内容可以尝试外部故障转移'
    : '当前没有可用的服务器端外部供应商配置';
}

function renderPlans(plans) {
  const container = $('#plansList');
  if (!plans || !plans.length) {
    container.innerHTML = '<div class="plans-intro">暂无可用套餐。</div>';
    return;
  }

  container.innerHTML = plans.map((plan) => `<div class="plan">
    <b>${escapeHtml(plan.name)}</b>
    <strong>${plan.price_hkd ? `HK$${Number(plan.price_hkd).toLocaleString()}` : '免费'}</strong>
    <p>${escapeHtml(plan.description)}</p>
    <small>${Number(plan.credits).toLocaleString()} tokens</small>
    <button type="button" data-plan="${escapeHtml(plan.id)}">${plan.price_hkd ? '创建演示订单' : '领取试用额度'}</button>
  </div>`).join('');

  document.querySelectorAll('[data-plan]').forEach((button) => button.addEventListener('click', async () => {
    const original = button.textContent;
    button.disabled = true;
    button.textContent = '正在建立……';
    try {
      const result = await api('/api/token-hub/subscribe', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({user_id: 'demo-user', plan_id: button.dataset.plan}),
      });
      $('#credits').textContent = Number(result.user.credits || 0).toLocaleString();
      $('#usage').textContent = `订单 ${result.order.id} 已建立（演示支付已完成），到账 ${Number(result.order.credits).toLocaleString()} tokens。`;
      button.textContent = '订单已建立';
    } catch (error) {
      $('#usage').textContent = `套餐操作失败：${error.message}`;
      button.textContent = original;
    } finally {
      button.disabled = false;
    }
  }));
}

/* ═══════════════════════════════════════════════════════════════════
   4. 加载数据
   ═══════════════════════════════════════════════════════════════════ */

async function load() {
  // 先显示加载状态
  $('#credits').textContent = '—';
  $('#routeStatus').textContent = '正在连接服务…';
  $('#routeStatus').className = 'client-status is-loading';

  try {
    const [userPayload, plansPayload] = await Promise.all([
      api('/api/token-hub/user?id=demo-user'),
      api('/api/token-hub/plans'),
    ]);
    $('#credits').textContent = Number(userPayload.user.credits || 0).toLocaleString();
    renderPlans(plansPayload.plans);
  } catch (error) {
    $('#routeStatus').textContent = '账户数据读取失败';
    $('#routeStatus').className = 'client-status is-blocked';
    $('#answer').dataset.state = 'error';
    $('#answer').innerHTML = `服务入口暂时无法读取账户状态。<br><small style="color:#888">${escapeHtml(error.message)}</small>`;
    $('#usage').textContent = '请检查网络连接或稍后重试。';
    // 显示重试按钮
    showRetryButton();
    return;
  }

  try {
    const modelPayload = await api('/api/token-hub/model-lab');
    state.lab = modelPayload.lab;
    $('#routeStatus').textContent = '内网模型已连接';
    $('#routeStatus').className = 'client-status is-ready';
  } catch (error) {
    state.lab = null;
    $('#routeStatus').textContent = '模型路由读取失败';
    $('#routeStatus').className = 'client-status is-blocked';
  }
  updateRouteMeta();
  updateExternalPolicy();
}

function showRetryButton() {
  const answer = $('#answer');
  if (answer.querySelector('.retry-btn')) return;
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'retry-btn';
  btn.textContent = '重新加载';
  btn.addEventListener('click', () => {
    btn.textContent = '加载中…';
    btn.disabled = true;
    load().finally(() => {
      btn.remove();
    });
  });
  answer.appendChild(document.createElement('br'));
  answer.appendChild(btn);
}

/* ═══════════════════════════════════════════════════════════════════
   5. 表单与对话交互
   ═══════════════════════════════════════════════════════════════════ */

function initChatForm() {
  const form = $('#chatForm');
  const textarea = $('#question');
  const button = form.querySelector('button');

  // Ctrl+Enter / Cmd+Enter 快速提交
  textarea.addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      event.preventDefault();
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = textarea.value.trim();
    if (!question) {
      $('#answer').dataset.state = 'error';
      $('#answer').textContent = '请先输入一个工作问题。';
      $('#usage').textContent = '本次未运行：请先输入一个工作问题。';
      textarea.focus();
      return;
    }

    const allowExternal = $('#allowExternal').checked;
    $('#emptyPrompt').hidden = true;
    $('#questionPreview').hidden = false;
    $('#questionPreview').textContent = question;
    $('#answer').dataset.state = 'loading';
    $('#answer').textContent = allowExternal
      ? '正在调用内网模型；仅在失败时检查紧急外部算力……'
      : '正在调用内网模型……';
    $('#usage').textContent = '正在记录本次任务的实际用量……';

    button.disabled = true;
    button.classList.add('is-loading');
    const originalBtnSpan = button.querySelector('span').textContent;
    button.querySelector('span').textContent = '运行中…';

    try {
      const result = await api('/api/token-hub/chat', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          user_id: 'demo-user',
          task_id: $('#taskId').value,
          question,
          allow_external: allowExternal,
          data_classification: allowExternal ? 'sanitized' : 'internal',
        }),
      });
      $('#answer').dataset.state = 'success';
      $('#answer').textContent = result.answer;
      const cost = result.cost_hkd == null
        ? '内部成本待录入'
        : `估算成本 HKD ${Number(result.cost_hkd).toFixed(4)}`;
      const route = result.route_type === 'external'
        ? `紧急外部算力 · ${result.provider}`
        : `内网 · ${result.model}`;
      $('#usage').textContent = `本次消耗 ${Number(result.consumed).toLocaleString()} tokens · ${result.task_id} · ${route} · ${cost}`;
      $('#credits').textContent = Number(result.user.credits || 0).toLocaleString();
      $('#routeStatus').textContent = result.route_type === 'external' ? '已使用紧急外部算力' : '内网模型已完成';
      $('#routeStatus').className = `client-status ${result.route_type === 'external' ? 'is-blocked' : 'is-ready'}`;

      // 清空输入框，方便继续提问
      textarea.value = '';
      $('#questionPreview').hidden = true;
      $('#emptyPrompt').hidden = false;

    } catch (error) {
      $('#answer').dataset.state = 'error';
      $('#answer').textContent = error.message;
      $('#usage').textContent = '任务未完成；请检查账户额度、模型服务或外部算力策略。';
    } finally {
      button.disabled = false;
      button.classList.remove('is-loading');
      button.querySelector('span').textContent = originalBtnSpan;
      textarea.focus();
    }
  });
}

/* ═══════════════════════════════════════════════════════════════════
   6. 初始化
   ═══════════════════════════════════════════════════════════════════ */

function init() {
  initSectionNav();
  initTopNav();
  initChatForm();

  $('#taskId').addEventListener('change', updateRouteMeta);

  document.querySelectorAll('.starter').forEach((button) => button.addEventListener('click', () => {
    $('#question').value = button.dataset.prompt || '';
    $('#question').focus();
  }));

  load().catch((error) => {
    $('#routeStatus').textContent = '初始化失败';
    $('#routeStatus').className = 'client-status is-blocked';
    $('#answer').dataset.state = 'error';
    $('#answer').innerHTML = `服务入口暂时无法读取账户状态。<br><small style="color:#888">${escapeHtml(error.message)}</small>`;
    showRetryButton();
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
