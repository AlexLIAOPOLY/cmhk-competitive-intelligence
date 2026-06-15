const companyState = {
  rows: [],
  companies: [],
  metrics: [],
  sourceTypes: [],
  groups: [],
  metricCategories: [],
  companySummary: [],
  query: "",
  company: "",
  metric: "",
  sourceType: "verified-performance",
  group: "",
  category: "",
  valueType: "",
  sourceOnly: true,
  sort: "company",
  view: "matrix",
  transpose: false,
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  stats: document.querySelector("#companyDataStats"),
  search: document.querySelector("#metricSearch"),
  companyFilter: document.querySelector("#companyFilter"),
  metricFilter: document.querySelector("#metricFilter"),
  sourceTypeFilter: document.querySelector("#sourceTypeFilter"),
  groupFilter: document.querySelector("#groupFilter"),
  categoryFilter: document.querySelector("#categoryFilter"),
  valueTypeFilter: document.querySelector("#valueTypeFilter"),
  sourceOnlyFilter: document.querySelector("#sourceOnlyFilter"),
  sortFilter: document.querySelector("#sortFilter"),
  resetFilters: document.querySelector("#resetFilters"),
  matrixViewButton: document.querySelector("#matrixViewButton"),
  detailViewButton: document.querySelector("#detailViewButton"),
  transposeButton: document.querySelector("#transposeButton"),
  overview: document.querySelector("#companyOverview"),
  matrixCard: document.querySelector("#companyMatrixCard"),
  matrixHead: document.querySelector("#companyMatrixHead"),
  matrixBody: document.querySelector("#companyMatrixBody"),
  matrixCount: document.querySelector("#companyMatrixCount"),
  detailCard: document.querySelector("#companyDetailCard"),
  count: document.querySelector("#companyTableCount"),
  body: document.querySelector("#companyMetricsBody"),
  metricModal: document.querySelector("#metricModal"),
  metricModalCompany: document.querySelector("#metricModalCompany"),
  metricModalTitle: document.querySelector("#metricModalTitle"),
  metricModalContent: document.querySelector("#metricModalContent"),
  metricModalClose: document.querySelector("#metricModalClose"),
};

const MATRIX_METRICS = [
  "披露日期",
  "最新披露",
  "收益",
  "EBITDA / 利润",
  "派息",
  "资本开支",
  "战略升级",
  "券商观点",
  "市场反应",
];

function setClock() {
  els.headerTime.textContent = `${new Date().toLocaleString("zh-CN", { hour12: false })} · Asia/Hong_Kong`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function highlightNumbers(value) {
  const escaped = escapeHtml(value || "-");
  const pattern = /(?:20\d{2}(?:\/\d{2})?(?:Q[1-4])?|20\d{2}年(?:\d{1,2}月(?:\d{1,2}日)?)?|\d+(?:,\d{3})*(?:\.\d+)?(?:亿港元|亿元|万港元|万元|百万港元|百万|十亿|港元|元|港仙|美元|%|个百分点|户|个|条|年|月|日)?)/g;
  return escaped.replace(pattern, (match) => `<strong class="numeric-emphasis">${match}</strong>`);
}

function sourceTypeLabel(value) {
  if (value === "verified-performance") return "核验业绩";
  if (value === "public-crawl") return "公开监测";
  return value || "-";
}

function confidenceText(value) {
  if (value === null || value === undefined || value === "") return "";
  const number = Number(value);
  if (!Number.isFinite(number)) return "";
  return ` · 置信度 ${Math.round(number * 100)}%`;
}

function rowQualityText(row) {
  return `${sourceTypeLabel(row.sourceType)}${row.aiCleaned ? " · AI整理" : ""}${confidenceText(row.confidence)}`;
}

function fillSelect(select, values, allLabel) {
  select.innerHTML = `<option value="">${allLabel}</option>`;
  values.forEach((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function hydrateFilters(data) {
  fillSelect(els.companyFilter, data.companies || [], "全部公司");
  fillSelect(els.metricFilter, data.metrics || [], "全部指标");
  fillSelect(els.groupFilter, data.groups || [], "全部范围");
  fillSelect(els.categoryFilter, data.metricCategories || [], "全部分类");
  els.sourceTypeFilter.value = companyState.sourceType;
}

function rowMatches(row) {
  if (companyState.company && row.company !== companyState.company) return false;
  if (companyState.metric && row.metric !== companyState.metric) return false;
  if (companyState.sourceType && row.sourceType !== companyState.sourceType) return false;
  if (companyState.group && row.group !== companyState.group) return false;
  if (companyState.category && row.metricCategory !== companyState.category) return false;
  if (companyState.valueType && row.valueType !== companyState.valueType) return false;
  if (companyState.sourceOnly && !(row.sources || []).length) return false;
  const terms = companyState.query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!terms.length) return true;
  const sourceText = (row.sources || []).map((source) => `${source.label} ${source.url}`).join(" ");
  const haystack = [
    row.company,
    row.metric,
    row.value,
    row.group,
    row.disclosure,
    row.disclosureDate,
    row.stockCode,
    sourceText,
  ]
    .join(" ")
    .toLowerCase();
  return terms.every((term) => haystack.includes(term));
}

function renderStats(data) {
  if (!els.stats) return;
  const summary = data.summary || {};
  els.stats.innerHTML = `
    <span><strong>${summary.companies || 0}</strong> 家公司</span>
    <span><strong>${summary.metrics || 0}</strong> 类指标</span>
    <span><strong>${summary.verifiedRecords || 0}</strong> 条核验字段</span>
    <span><strong>${summary.crawlRecords || 0}</strong> 条公开监测</span>
    <span><strong>${summary.suppressedRecords || 0}</strong> 条已拦截</span>
    <span>更新于 ${escapeHtml(data.generatedAt || "-")}</span>
  `;
}

function renderOverview() {
  const cards = [...companyState.companySummary]
    .sort((a, b) => b.metricCount - a.metricCount || a.company.localeCompare(b.company, "zh-CN"))
    .slice(0, 12);
  els.overview.innerHTML = cards
    .map((item) => `
      <button class="company-overview-card ${companyState.company === item.company ? "is-active" : ""}" type="button" data-company="${escapeHtml(item.company)}">
        <strong>${escapeHtml(item.company)}</strong>
        <span>${item.metricCount} 类指标 · ${item.sourceCount} 个来源</span>
      </button>
    `)
    .join("");
  els.overview.querySelectorAll(".company-overview-card").forEach((button) => {
    button.addEventListener("click", () => {
      companyState.company = companyState.company === button.dataset.company ? "" : button.dataset.company;
      els.companyFilter.value = companyState.company;
      render();
    });
  });
}

function renderSources(row) {
  const sources = row.sources || [];
  if (!sources.length) {
    return `<span class="source-empty">无可点击来源</span>`;
  }
  return sources
    .slice(0, 4)
    .map((source, index) => {
      const title = source.label || source.url || `来源${index + 1}`;
      return `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer" title="${escapeHtml(source.url)}">${escapeHtml(title)}</a>`;
    })
    .join("");
}

function sourceLinksHtml(row) {
  return (row?.sources || [])
    .slice(0, 6)
    .map((source) => `<a href="${escapeHtml(source.url)}" target="_blank" rel="noreferrer">${escapeHtml(source.label || source.url)}</a>`)
    .join("");
}

function openMetricModal(row) {
  if (!row) return;
  els.metricModalCompany.textContent = row.company;
  els.metricModalTitle.textContent = row.metric;
  els.metricModalContent.innerHTML = `
    <p class="metric-modal-value">${highlightNumbers(row.detail || row.value || "-")}</p>
    <dl>
      <div><dt>披露口径</dt><dd>${escapeHtml(row.disclosure || row.rowRef || "-")}</dd></div>
      <div><dt>披露日期</dt><dd>${escapeHtml(row.disclosureDate || "-")}</dd></div>
      <div><dt>数据状态</dt><dd>${escapeHtml(rowQualityText(row))}</dd></div>
    </dl>
    <div class="metric-modal-sources">
      <strong>来源</strong>
      ${sourceLinksHtml(row) || "<span>无可点击来源</span>"}
    </div>
  `;
  els.metricModal.hidden = false;
}

function closeMetricModal() {
  els.metricModal.hidden = true;
}

function renderMetricValue(row) {
  const detail = row.detail && row.detail !== row.value
    ? `<details class="metric-detail"><summary>依据片段</summary><p>${escapeHtml(row.detail)}</p></details>`
    : "";
  return `
    <span class="metric-direct-value">${highlightNumbers(row.value || "-")}</span>
    ${detail}
  `;
}

function renderTable() {
  const rows = companyState.rows.filter(rowMatches).sort((a, b) => {
    if (companyState.sort === "metric") {
      return a.metric.localeCompare(b.metric, "zh-CN") || a.company.localeCompare(b.company, "zh-CN");
    }
    if (companyState.sort === "confidence") {
      const confidenceA = a.sourceType === "verified-performance" ? 1 : Number(a.aiConfidence || a.confidence || 0);
      const confidenceB = b.sourceType === "verified-performance" ? 1 : Number(b.aiConfidence || b.confidence || 0);
      return confidenceB - confidenceA || a.company.localeCompare(b.company, "zh-CN");
    }
    return a.company.localeCompare(b.company, "zh-CN") || a.metric.localeCompare(b.metric, "zh-CN");
  });
  els.count.textContent = `${rows.length} 条`;
  if (!rows.length) {
    els.body.innerHTML = `<tr><td colspan="5" class="empty-company-data">没有匹配的公司指标。</td></tr>`;
    return;
  }
  els.body.innerHTML = rows
    .map((row) => `
      <tr>
        <td>
          <strong>${escapeHtml(row.company)}</strong>
          <span class="company-row-meta">${escapeHtml(row.stockCode || row.group || "")}</span>
        </td>
        <td>
          <span class="metric-badge">${escapeHtml(row.metric)}</span>
          <small>${escapeHtml(rowQualityText(row))}</small>
        </td>
        <td class="metric-value">${renderMetricValue(row)}</td>
        <td>
          <span>${escapeHtml(row.disclosure || row.rowRef || "-")}</span>
          <small>${escapeHtml(row.disclosureDate || "")}</small>
        </td>
        <td class="source-links">${renderSources(row)}</td>
      </tr>
    `)
    .join("");
}

function filteredRows() {
  return companyState.rows.filter(rowMatches);
}

function renderMatrix() {
  const rows = filteredRows();
  const companies = [...new Set(rows.map((row) => row.company))].sort((a, b) => a.localeCompare(b, "zh-CN"));
  const metrics = companyState.metric ? [companyState.metric] : MATRIX_METRICS;
  const rowLookup = new Map(rows.map((row) => [`${row.company}::${row.metric}`, row]));
  els.matrixCount.textContent = `${companies.length} 家公司 · ${metrics.length} 项指标`;
  
  if (!companies.length) {
    els.matrixHead.innerHTML = `
      <tr>
        <th>公司</th>
        ${metrics.map((metric) => `<th>${escapeHtml(metric)}</th>`).join("")}
      </tr>
    `;
    els.matrixBody.innerHTML = `<tr><td colspan="${metrics.length + 1}" class="empty-company-data">没有匹配的公司指标。</td></tr>`;
    return;
  }

  if (companyState.transpose) {
    els.matrixHead.innerHTML = `
      <tr>
        <th>指标</th>
        ${companies.map((company) => `<th>${escapeHtml(company)}</th>`).join("")}
      </tr>
    `;
    els.matrixBody.innerHTML = metrics.map((metric) => {
      return `
        <tr>
          <th scope="row"><strong>${escapeHtml(metric)}</strong></th>
          ${companies.map((company) => {
            const row = rowLookup.get(`${company}::${metric}`);
            if (!row) return `<td class="matrix-empty">-</td>`;
            return `
              <td>
                <button class="matrix-value-button" type="button" data-row-id="${escapeHtml(row.id)}" title="查看${escapeHtml(company)}的${escapeHtml(metric)}详情">
                  <span>${highlightNumbers(row.value || "-")}</span>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>
                </button>
              </td>
            `;
          }).join("")}
        </tr>
      `;
    }).join("");
  } else {
    els.matrixHead.innerHTML = `
      <tr>
        <th>公司</th>
        ${metrics.map((metric) => `<th>${escapeHtml(metric)}</th>`).join("")}
      </tr>
    `;
    els.matrixBody.innerHTML = companies.map((company) => {
      const companyRows = rows.filter((row) => row.company === company);
      const meta = companyRows.find((row) => row.stockCode)?.stockCode || companyRows[0]?.group || "";
      return `
        <tr>
          <th scope="row"><strong>${escapeHtml(company)}</strong><small>${escapeHtml(meta)}</small></th>
          ${metrics.map((metric) => {
            const row = rowLookup.get(`${company}::${metric}`);
            if (!row) return `<td class="matrix-empty">-</td>`;
            return `
              <td>
                <button class="matrix-value-button" type="button" data-row-id="${escapeHtml(row.id)}" title="查看${escapeHtml(company)}的${escapeHtml(metric)}详情">
                  <span>${highlightNumbers(row.value || "-")}</span>
                  <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18l6-6-6-6"/></svg>
                </button>
              </td>
            `;
          }).join("")}
        </tr>
      `;
    }).join("");
  }
  els.matrixBody.querySelectorAll("[data-row-id]").forEach((button) => {
    button.addEventListener("click", () => {
      openMetricModal(companyState.rows.find((row) => row.id === button.dataset.rowId));
    });
  });
}

function renderViewState() {
  const isMatrix = companyState.view === "matrix";
  els.matrixCard.hidden = !isMatrix;
  els.detailCard.hidden = isMatrix;
  els.overview.hidden = isMatrix;
  els.matrixViewButton.classList.toggle("is-active", isMatrix);
  els.detailViewButton.classList.toggle("is-active", !isMatrix);
  els.matrixViewButton.setAttribute("aria-pressed", String(isMatrix));
  els.detailViewButton.setAttribute("aria-pressed", String(!isMatrix));
  document.body.classList.toggle("company-matrix-mode", isMatrix);
}

function render() {
  renderViewState();
  renderOverview();
  renderTable();
  renderMatrix();
}

async function loadCompanyMetrics() {
  const response = await fetch("/api/company-metrics");
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "公司指标加载失败");
  }
  const data = payload.data || {};
  companyState.rows = data.rows || [];
  companyState.companies = data.companies || [];
  companyState.metrics = data.metrics || [];
  companyState.sourceTypes = data.sourceTypes || [];
  companyState.groups = data.groups || [];
  companyState.metricCategories = data.metricCategories || [];
  companyState.companySummary = data.companySummary || [];
  hydrateFilters(data);
  renderStats(data);
  render();
}

async function refreshCompanyMetrics() {
  const response = await fetch(`/api/company-metrics?t=${Date.now()}`);
  const payload = await response.json();
  if (!response.ok || !payload.ok) return;
  const data = payload.data || {};
  companyState.rows = data.rows || [];
  companyState.companySummary = data.companySummary || [];
  renderStats(data);
  render();
}

els.search.addEventListener("input", () => {
  companyState.query = els.search.value;
  render();
});

els.companyFilter.addEventListener("change", () => {
  companyState.company = els.companyFilter.value;
  render();
});

els.metricFilter.addEventListener("change", () => {
  companyState.metric = els.metricFilter.value;
  render();
});

els.sourceTypeFilter.addEventListener("change", () => {
  companyState.sourceType = els.sourceTypeFilter.value;
  render();
});

els.groupFilter.addEventListener("change", () => {
  companyState.group = els.groupFilter.value;
  render();
});

els.categoryFilter.addEventListener("change", () => {
  companyState.category = els.categoryFilter.value;
  render();
});

els.valueTypeFilter.addEventListener("change", () => {
  companyState.valueType = els.valueTypeFilter.value;
  render();
});

els.sourceOnlyFilter.addEventListener("change", () => {
  companyState.sourceOnly = els.sourceOnlyFilter.checked;
  render();
});

els.sortFilter.addEventListener("change", () => {
  companyState.sort = els.sortFilter.value;
  render();
});

els.resetFilters.addEventListener("click", () => {
  Object.assign(companyState, {
    query: "",
    company: "",
    metric: "",
    sourceType: "verified-performance",
    group: "",
    category: "",
    valueType: "",
    sourceOnly: true,
    sort: "company",
  });
  els.search.value = "";
  els.companyFilter.value = "";
  els.metricFilter.value = "";
  els.sourceTypeFilter.value = "verified-performance";
  els.groupFilter.value = "";
  els.categoryFilter.value = "";
  els.valueTypeFilter.value = "";
  els.sourceOnlyFilter.checked = true;
  els.sortFilter.value = "company";
  render();
});

els.matrixViewButton.addEventListener("click", () => {
  companyState.view = "matrix";
  render();
});

els.detailViewButton.addEventListener("click", () => {
  companyState.view = "detail";
  render();
});

if (els.transposeButton) {
  els.transposeButton.addEventListener("click", () => {
    companyState.transpose = !companyState.transpose;
    renderMatrix();
  });
}

els.metricModalClose.addEventListener("click", closeMetricModal);
els.metricModal.addEventListener("click", (event) => {
  if (event.target === els.metricModal) closeMetricModal();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !els.metricModal.hidden) closeMetricModal();
});

setClock();
setInterval(setClock, 30000);
loadCompanyMetrics().catch((error) => {
  els.body.innerHTML = `<tr><td colspan="5" class="empty-company-data">${escapeHtml(error.message)}</td></tr>`;
  els.stats.innerHTML = `<span>加载失败</span>`;
});
setInterval(refreshCompanyMetrics, 30000);
