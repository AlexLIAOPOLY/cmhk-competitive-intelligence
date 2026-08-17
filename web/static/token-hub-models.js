/* ═══════════════════════════════════════════════════════════════════
   Token Hub 模型治理
   ═══════════════════════════════════════════════════════════════════ */

const $ = (selector) => document.querySelector(selector);

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
const displayMoney = (value, currency = 'USD') => value == null ? '待录入' : `${currency} ${Number(value).toFixed(4)}`;
const numberOrNull = (value) => String(value ?? '').trim() === '' ? null : Number(value);
const state = { lab: null };

/* ═══════════════════════════════════════════════════════════════════
   1. 侧边栏导航：平滑滚动 + 滚动联动
   ═══════════════════════════════════════════════════════════════════ */

function initSectionNav() {
  const navLinks = document.querySelectorAll('.client-section-nav a');
  const sections = ['routes', 'catalog', 'costs', 'overflow', 'prices', 'economics']
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
  const current = window.location.pathname.split('/').pop() || 'token-hub-models.html';
  document.querySelectorAll('.client-nav a').forEach((link) => {
    const href = link.getAttribute('href') || '';
    const name = href.split('/').pop();
    link.classList.toggle('is-active', name === current);
  });
}

/* ═══════════════════════════════════════════════════════════════════
   3. 数据渲染
   ═══════════════════════════════════════════════════════════════════ */

function enabledModels() {
  return (state.lab?.models || []).filter((model) => model.enabled);
}

function tariffCost(modelId, bandId) {
  return (state.lab?.tariff_costs || []).find((item) => item.model_id === modelId && item.band_id === bandId) || null;
}

function renderSummary() {
  const lab = state.lab || {};
  const currentBand = (lab.tariff_bands || []).find((band) => band.current);
  const policy = lab.overflow_policy || {};
  $('#routeCount').textContent = String((lab.tasks || []).length);
  $('#modelCount').textContent = String(enabledModels().length);
  $('#currentBand').textContent = currentBand?.name || '—';
  $('#externalState').textContent = policy.effective ? '已启用' : policy.enabled ? '待生效' : '已关闭';
}

function renderRoutes() {
  const lab = state.lab;
  const models = enabledModels();
  $('#routeTable').innerHTML = lab.tasks.map((task) => `
    <div class="route-row">
      <div>
        <div class="route-name">${escapeHtml(task.name)}</div>
        <div class="route-desc">${escapeHtml(task.description)}</div>
      </div>
      <select class="route-select" data-task="${escapeHtml(task.id)}" aria-label="${escapeHtml(task.name)} 使用的模型">
        ${models.map((model) => `<option value="${escapeHtml(model.model_id)}" ${model.model_id === task.selected_model_id ? 'selected' : ''}>${escapeHtml(model.display_name)}${model.is_current ? ' · 当前配置' : ''}</option>`).join('')}
      </select>
    </div>`).join('');
  document.querySelectorAll('.route-select').forEach((select) => {
    select.addEventListener('change', async () => {
      select.disabled = true;
      try {
        const result = await api('/api/token-hub/model-lab/routes', {
          method: 'POST', headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({task_id: select.dataset.task, model_id: select.value}),
        });
        $('#labStatus').textContent = `${result.task_name} 已切换至 ${result.model_id}`;
        await loadLab();
      } catch (error) {
        $('#labStatus').textContent = error.message;
        select.disabled = false;
      }
    });
  });
}

function renderPrices() {
  const prices = state.lab.public_api_prices || [];
  $('#priceVerified').textContent = `官方页面核对：${prices[0]?.verified_at || '—'}`;
  $('#priceRows').innerHTML = prices.map((item) => `<tr>
    <td><b>${escapeHtml(item.provider)}</b><small>${escapeHtml(item.model)}</small></td>
    <td>${displayMoney(item.input_usd_per_million)}</td>
    <td>${displayMoney(item.output_usd_per_million)}</td>
    <td>${displayMoney(item.cache_input_usd_per_million)}</td>
    <td class="price-note">${escapeHtml(item.note)}</td>
    <td><a href="${escapeHtml(item.source_url)}" target="_blank" rel="noreferrer">官方价格 ↗</a></td>
  </tr>`).join('');
}

function fillSelect(selector, options, selected) {
  const select = $(selector);
  const previous = selected || select.value;
  select.innerHTML = options.map((item) => `<option value="${escapeHtml(item.value)}">${escapeHtml(item.label)}</option>`).join('');
  if (options.some((item) => item.value === previous)) select.value = previous;
}

function renderTariffs() {
  const lab = state.lab;
  const bands = lab.tariff_bands || [];
  const current = bands.find((band) => band.current);
  $('#currentBandBadge').textContent = current ? `当前：${current.name} · 香港时间` : '时段待读取';
  $('#tariffRows').innerHTML = bands.map((band) => `
    <div class="tariff-row ${band.current ? 'is-current' : ''}">
      <div>
        <div class="tariff-row-name">${escapeHtml(band.name)}</div>
        <div class="tariff-row-window">${escapeHtml(band.windows)}</div>
      </div>
      <div class="tariff-row-note">${band.current ? '当前时段 · ' : ''}${escapeHtml(band.note)}</div>
    </div>`).join('');
  const modelOptions = enabledModels().map((model) => ({value: model.model_id, label: model.display_name}));
  fillSelect('#tariffModel', modelOptions);
  fillSelect('#calcModel', modelOptions);
  fillSelect('#calcBand', bands.map((band) => ({value: band.id, label: `${band.name} · ${band.windows}${band.current ? ' · 当前' : ''}`})), current?.id);
  renderTariffInputs();
}

function renderTariffInputs() {
  const modelId = $('#tariffModel').value;
  const bands = state.lab.tariff_bands || [];
  $('#tariffInputs').innerHTML = bands.map((band) => {
    const row = tariffCost(modelId, band.id) || {};
    return `<div class="band-input">
      <strong>${escapeHtml(band.name)}</strong><span>${escapeHtml(band.windows)}</span>
      <label>输入 <input data-band="${escapeHtml(band.id)}" data-kind="input" type="number" min="0" step="0.000001" value="${row.input_cost_usd_per_million ?? ''}" placeholder="待录入"></label>
      <label>输出 <input data-band="${escapeHtml(band.id)}" data-kind="output" type="number" min="0" step="0.000001" value="${row.output_cost_usd_per_million ?? ''}" placeholder="待录入"></label>
    </div>`;
  }).join('');
}

function renderOverflow() {
  const policy = state.lab.overflow_policy || {};
  const provider = (state.lab.external_providers || [])[0] || {};
  const effective = policy.effective;
  $('#overflowStatus').textContent = effective ? '策略已生效' : policy.enabled ? '已保存但未生效' : '策略已关闭';
  $('#providerStatus').innerHTML = `<div class="provider-line"><b>${escapeHtml(provider.provider || '获批适配器')}</b><span>${escapeHtml(provider.model || '—')}</span><strong class="${provider.configured ? 'is-ready' : 'is-blocked'}">${escapeHtml(provider.status || '未配置')}</strong></div>
    <p>${escapeHtml(provider.reason || policy.effective_reason || '系统不会外发请求。')} ${escapeHtml(provider.pricing_basis || '')}</p>
    ${provider.source_url ? `<a href="${escapeHtml(provider.source_url)}" target="_blank" rel="noreferrer">查看官方价格与条款 ↗</a>` : ''}
    <div class="provider-boundary">${escapeHtml(policy.effective_reason || '系统不会外发请求。')} 服务器端不会把密钥返回浏览器。 本月已用 HKD ${Number(policy.spend_this_month_hkd || 0).toFixed(4)}；预算余额 ${policy.remaining_monthly_hkd == null ? '未设上限' : `HKD ${Number(policy.remaining_monthly_hkd).toFixed(4)}`}。</div>`;
  $('#overflowEnabled').checked = Boolean(policy.enabled);
  $('#queueDepth').value = policy.trigger_queue_depth ?? 20;
  $('#latencyMs').value = policy.trigger_latency_ms ?? 8000;
  $('#monthlyBudget').value = policy.max_monthly_hkd ?? 0;
  $('#requestTokenLimit').value = policy.max_request_tokens ?? 0;
}

function renderCalculator() {
  const lab = state.lab;
  const requests = Math.max(0, Number($('#calcRequests').value) || 0);
  const inputTokens = Math.max(0, Number($('#calcInputTokens').value) || 0);
  const outputTokens = Math.max(0, Number($('#calcOutputTokens').value) || 0);
  const rate = Math.max(0, Number($('#calcRate').value) || 0);
  const modelId = $('#calcModel').value;
  const bandId = $('#calcBand').value;
  const internal = enabledModels().find((model) => model.model_id === modelId);
  const internalCost = tariffCost(modelId, bandId) || internal || {};
  const internalLabel = (internal?.display_name || modelId).replace(/^公司内网\s*·\s*/, '');
  const rows = [{
    provider: '公司内网',
    model: internalLabel,
    input: internalCost.input_cost_usd_per_million,
    output: internalCost.output_cost_usd_per_million,
    note: `分时成本 · ${lab.tariff_bands.find((band) => band.id === bandId)?.name || '—'}`,
  }];
  const emergency = (lab.external_providers || [])[0];
  if (emergency) rows.push({
    provider: '紧急适配器', model: emergency.model,
    input: emergency.input_usd_per_million, output: emergency.output_usd_per_million,
    note: `${emergency.pricing_basis || '官方价格参考'} · ${emergency.configured ? '已配置但仍需策略生效' : '未配置，不可调用'}`,
  });
  (lab.public_api_prices || []).forEach((item) => rows.push({
    provider: item.provider, model: item.model, input: item.input_usd_per_million,
    output: item.output_usd_per_million, note: '公开价格参考',
  }));
  $('#calcResult').innerHTML = rows.map((item) => {
    const usd = item.input == null || item.output == null ? null : requests * ((inputTokens / 1000000) * Number(item.input) + (outputTokens / 1000000) * Number(item.output));
    return `<div class="calc-row"><span><b>${escapeHtml(item.provider)}</b> · ${escapeHtml(item.model)}<small>${escapeHtml(item.note)}</small></span><strong>${usd == null ? '内部成本待录入' : `USD ${usd.toFixed(2)} · HKD ${(usd * rate).toFixed(2)}`}</strong></div>`;
  }).join('');
}

async function loadLab() {
  const payload = await api('/api/token-hub/model-lab');
  state.lab = payload.lab;
  renderSummary();
  renderRoutes();
  renderPrices();
  renderTariffs();
  renderOverflow();
  renderCalculator();
  $('#assumptionText').textContent = `${payload.lab.assumptions.note} 计算公式：${payload.lab.assumptions.formula}`;
  const config = payload.lab.internal_config;
  $('#labStatus').textContent = config.has_api_key && config.base_url_is_internal ? `内网链路已就绪 · ${config.model}` : '内网模型配置待检查';
}

/* ═══════════════════════════════════════════════════════════════════
   4. 事件绑定
   ═══════════════════════════════════════════════════════════════════ */

$('#modelForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector('button');
  button.disabled = true;
  $('#modelFormMessage').textContent = '正在保存……';
  try {
    const valueOrNull = (selector) => $(selector).value.trim() || null;
    await api('/api/token-hub/model-lab/models', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        model_id: $('#modelId').value.trim(), display_name: $('#displayName').value.trim(),
        input_cost_usd_per_million: valueOrNull('#inputCost'), output_cost_usd_per_million: valueOrNull('#outputCost'),
        note: $('#modelNote').value.trim(),
      }),
    });
    $('#modelFormMessage').textContent = '内部模型已登记，可在任务链路中选择。';
    form.reset();
    await loadLab();
  } catch (error) {
    $('#modelFormMessage').textContent = error.message;
  } finally { button.disabled = false; }
});

$('#tariffModel').addEventListener('change', renderTariffInputs);
$('#tariffForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  $('#tariffMessage').textContent = '正在保存……';
  try {
    const costs = {};
    document.querySelectorAll('#tariffInputs input[data-band]').forEach((input) => {
      costs[input.dataset.band] ||= {};
      costs[input.dataset.band][input.dataset.kind === 'input' ? 'input_usd_per_million' : 'output_usd_per_million'] = numberOrNull(input.value);
    });
    await api('/api/token-hub/model-lab/costs', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({model_id: $('#tariffModel').value, costs}),
    });
    $('#tariffMessage').textContent = '峰／平／谷成本已保存，计算器已按新数据刷新。';
    await loadLab();
  } catch (error) {
    $('#tariffMessage').textContent = error.message;
  } finally { button.disabled = false; }
});

$('#overflowForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector('button');
  button.disabled = true;
  $('#overflowMessage').textContent = '正在保存策略……';
  try {
    await api('/api/token-hub/model-lab/overflow', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        enabled: $('#overflowEnabled').checked,
        provider_id: state.lab.overflow_policy.provider_id,
        trigger_queue_depth: Number($('#queueDepth').value),
        trigger_latency_ms: Number($('#latencyMs').value),
        max_monthly_hkd: Number($('#monthlyBudget').value),
        max_request_tokens: Number($('#requestTokenLimit').value),
      }),
    });
    $('#overflowMessage').textContent = '紧急算力策略已保存；页面会显示是否真正生效。';
    await loadLab();
  } catch (error) {
    $('#overflowMessage').textContent = error.message;
  } finally { button.disabled = false; }
});

['#calcRequests', '#calcInputTokens', '#calcOutputTokens', '#calcRate', '#calcModel', '#calcBand'].forEach((selector) => {
  const el = $(selector);
  if (el) el.addEventListener('input', renderCalculator);
});

/* ═══════════════════════════════════════════════════════════════════
   5. 初始化
   ═══════════════════════════════════════════════════════════════════ */

function init() {
  initSectionNav();
  initTopNav();
  loadLab().catch((error) => {
    $('#labStatus').textContent = error.message;
    $('#routeTable').innerHTML = '<p class="panel-desc">链路配置暂时无法读取。</p>';
  });
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
