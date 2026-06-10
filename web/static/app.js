const state = {
  busy: false,
  chatBusy: false,
  outputs: [],
  status: null,
  activeInsight: "all",
  editingFile: null,
  multiSelect: false,
  selectedFiles: new Set(),
  currentAudio: null,
  currentAudioButton: null,
  isScrubbing: false,
  agentTraceLoaded: false,
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  statusSummary: document.querySelector("#statusSummary"),
  fileList: document.getElementById("fileList"),
  weeklyFileList: document.getElementById("weeklyFileList"),
  performanceFileList: document.getElementById("performanceFileList"),
  fileCountText: document.querySelector("#fileCountText"),
  weeklyFileCountText: document.querySelector("#weeklyFileCountText"),
  performanceFileCountText: document.querySelector("#performanceFileCountText"),
  multiSelectButton: document.querySelector("#multiSelectButton"),
  multiSelectTriggers: document.querySelectorAll(".multi-select-trigger"),
  deleteSelectedButton: document.querySelector("#deleteSelectedButton"),
  deleteSelectedTriggers: document.querySelectorAll(".delete-selected-trigger"),
  outputTabs: document.querySelectorAll(".output-tab"),
  weeklyOutputBlock: document.querySelector("#weeklyOutputBlock"),
  performanceOutputBlock: document.querySelector("#performanceOutputBlock"),
  fileEditModal: document.querySelector("#fileEditModal"),
  fileEditForm: document.querySelector("#fileEditForm"),
  closeFileEdit: document.querySelector("#closeFileEdit"),
  cancelFileEdit: document.querySelector("#cancelFileEdit"),
  editFileName: document.querySelector("#editFileName"),
  editFileNote: document.querySelector("#editFileNote"),
  fileEditStatus: document.querySelector("#fileEditStatus"),
  logBox: document.querySelector("#logBox"),
  generateButtons: [
    document.querySelector("#generateButton"),
    document.querySelector("#generateButtonSecondary"),
  ].filter(Boolean),
  generatePerformanceButton: document.querySelector("#generatePerformanceButton"),
  generateButtonSecondary: document.querySelector("#generateButtonSecondary"),
  crawlButtons: [
    document.querySelector("#crawlButton"),
    document.querySelector("#crawlButtonSecondary"),
  ].filter(Boolean),
  refreshButton: document.querySelector("#refreshButton"),
  logButton: document.querySelector("#logButton"),
  logModal: document.querySelector("#logModal"),
  closeLogButton: document.querySelector("#closeLogButton"),
  dashboardBtn: document.querySelector("#dashboardBtn"),
  dashboardModal: document.querySelector("#dashboardModal"),
  closeDashboardBtn: document.querySelector("#closeDashboardBtn"),
  aiSettingsButton: document.querySelector("#aiSettingsButton"),
  aiSettingsModal: document.querySelector("#aiSettingsModal"),
  aiSettingsForm: document.querySelector("#aiSettingsForm"),
  closeAiSettings: document.querySelector("#closeAiSettings"),
  testAiConfig: document.querySelector("#testAiConfig"),
  aiProvider: document.querySelector("#aiProvider"),
  aiBaseUrl: document.querySelector("#aiBaseUrl"),
  aiModel: document.querySelector("#aiModel"),
  aiApiKey: document.querySelector("#aiApiKey"),
  aiConfigStatus: document.querySelector("#aiConfigStatus"),
  clearLogButton: document.querySelector("#clearLogButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  chatFab: document.querySelector("#chatFab"),
  chatModal: document.querySelector("#chatModal"),
  closeChatButton: document.querySelector("#closeChatButton"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  chatSubmitButton: document.querySelector("#chatSubmitButton"),
  runState: document.querySelector("#runState"),
  qualityScore: document.querySelector("#qualityScore"),
  qualityRing: document.querySelector("#qualityRing"),
  qualityCenter: document.querySelector("#qualityCenter"),
  audioPlayer: document.getElementById("globalAudioPlayer"),
  audioPlayPauseBtn: document.getElementById("audioPlayPauseBtn"),
  audioCurrentTime: document.getElementById("audioCurrentTime"),
  audioDuration: document.getElementById("audioDuration"),
  audioProgressBar: document.getElementById("audioProgressBar"),
  audioCloseBtn: document.getElementById("audioCloseBtn"),
  audioFileName: document.getElementById("audioFileName"),
  subtitleToggleBtn: document.getElementById("subtitleToggleBtn"),
  qualityLegend: document.querySelector("#qualityLegend"),
  blockTotal: document.querySelector("#blockTotal"),
  blockChart: document.querySelector("#blockChart"),
  sourceTotal: document.querySelector("#sourceTotal"),
  sourceChart: document.querySelector("#sourceChart"),
};

function formatBytes(size) {
  if (!Number.isFinite(size)) return "-";
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size > 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

function setClock() {
  const now = new Date();
  els.headerTime.textContent = `${now.toLocaleString("zh-CN", { hour12: false })} · Asia/Hong_Kong`;
}

function setBusy(value, label = "运行中", action = "all") {
  state.busy = value;
  
  els.generateButtons.forEach((button) => {
    button.disabled = value;
    if (value) {
      button.textContent = (action === "all" || action === "generate") ? "生成中..." : "生成周报";
    } else {
      button.textContent = "生成周报";
    }
  });
  if (els.generateButtonSecondary) {
    els.generateButtonSecondary.disabled = value;
    els.generateButtonSecondary.textContent = value && action === "report" ? "生成中..." : "生成周报";
  }
  if (els.generatePerformanceButton) {
    els.generatePerformanceButton.disabled = value;
    els.generatePerformanceButton.textContent = value && action === "performance" ? "生成中..." : "生成业绩摘要";
  }
  
  els.crawlButtons.forEach((button) => {
    button.disabled = value;
    if (value) {
      button.textContent = (action === "all" || action === "crawl") ? "爬取中..." : "重新爬取";
    } else {
      button.textContent = "重新爬取";
    }
  });

  els.refreshButton.disabled = value;
  if (els.aiSettingsButton) els.aiSettingsButton.disabled = value;
  els.runState.textContent = value ? label : "准备就绪";
  
  if (value) {
    els.logButton.classList.add("log-glowing");
  } else {
    els.logButton.classList.remove("log-glowing");
  }
}

function setChatBusy(value) {
  state.chatBusy = value;
  els.chatSubmitButton.disabled = value;
  els.chatInput.disabled = value;
  els.chatSubmitButton.textContent = value ? "生成中" : "发送";
}

function fileType(fileName) {
  const getIcon = (paths) => `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">${paths}</svg>`;
  const base = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline>';
  const wordSvg = base + '<line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><line x1="10" y1="9" x2="8" y2="9"></line>';

  return { label: "Word 文档", icon: getIcon(wordSvg), className: "type-docx" };
}

function iconSvg(name) {
  const icons = {
    edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4 12.5-12.5z"/>',
    trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 15H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
    waveform: '<path d="M2 12h2"/><path d="M6 8v8"/><path d="M10 4v16"/><path d="M14 9v6"/><path d="M18 7v10"/><path d="M22 12h-2"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
}

function fileDescription(file) {
  const defaultDescription = file.reportType === "carrier-performance" ? "运营商业绩对标摘要" : "正式 Word 周报";
  let desc = file.note ? escapeHtml(file.note) : defaultDescription;
  
  if (file.is_archive) {
    desc = `<span class="archive-label">历史归档 ${file.archive_batch}</span> ` + desc;
  }
  return desc;
}

function filteredOutputs() {
  return [...state.outputs].sort((a, b) => b.mtime - a.mtime);
}

function outputsByType(type) {
  return filteredOutputs().filter((file) => {
    const isPerformance = file.reportType === "carrier-performance";
    return type === "performance" ? isPerformance : !isPerformance;
  });
}

function labelSourceType(value) {
  const labels = {
    company_official: "企业官网",
    regulator_official: "监管机构",
    media: "媒体资讯",
    public_database: "公开数据库",
    stock_exchange: "交易所",
    commercial_data: "商业数据",
    exchange_public_disclosure: "交易所公开披露",
    government_api_docs: "政府 API 文档",
    government_open_data: "政府开放数据",
    government_public_info: "政府公开信息",
    government_statistics: "政府统计数据",
    industry_association: "行业协会",
    international_org: "国际组织",
    public_api: "公开 API",
    regulator_public_info: "监管机构公开信息",
    unregistered: "未注册来源",
    unknown: "未分类",
  };
  return labels[value] || value.replaceAll("_", " ");
}

function sumValues(items = []) {
  return items.reduce((total, item) => total + Number(item.value || 0), 0);
}

// Register datalabels globally
if (typeof ChartDataLabels !== 'undefined') {
  Chart.register(ChartDataLabels);
}

let chartInstances = {};

function withoutChartAnimation(options = {}) {
  return {
    ...options,
    animation: false,
    animations: false,
    transitions: {
      ...options.transitions,
      active: { animation: { duration: 0 } },
      resize: { animation: { duration: 0 } },
      show: { animations: {} },
      hide: { animations: {} },
    },
  };
}

function initOrUpdateChart(id, config) {
  const canvas = document.getElementById(id);
  if (!canvas) return;
  const existingChart = chartInstances[id];
  if (existingChart && existingChart.config.type === config.type) {
    existingChart.data = config.data;
    existingChart.options = withoutChartAnimation(config.options);
    existingChart.update("none");
    return;
  }
  if (existingChart) existingChart.destroy();
  chartInstances[id] = new Chart(canvas, config);
}

function renderInsights(status) {
  const visuals = status.visuals || {};
  const crawl = visuals.crawl || {};
  const totalUrls = Number(crawl.total || 0);
  const successUrls = Number(crawl.success || 0);
  const failedUrls = Number(crawl.failed || 0);
  const successRate = Number(crawl.successRate || 0);
  
  if (els.qualityScore) {
    els.qualityScore.textContent = totalUrls ? `成功 ${successRate}%` : "--";
    els.qualityScore.title = totalUrls
      ? `本轮共抓取 ${totalUrls} 个 URL：成功 ${successUrls} 个，失败 ${failedUrls} 个`
      : "暂无本轮 URL 抓取结果";
  }

  // 1. The first chart reflects the latest URL-level crawl, not retained row data.
  initOrUpdateChart('qualityCanvas', {
    type: 'doughnut',
    data: {
      labels: ['抓取成功', '抓取失败'],
      datasets: [{
        data: [successUrls, failedUrls],
        backgroundColor: [
          'rgba(16, 185, 129, 0.95)', // emerald
          'rgba(239, 68, 68, 0.95)'   // red
        ],
        hoverBackgroundColor: [
          'rgba(52, 211, 153, 1)',
          'rgba(248, 113, 113, 1)'
        ],
        borderWidth: 3,
        borderColor: '#ffffff',
        hoverBorderWidth: 0,
        borderRadius: 8,
        hoverOffset: 6
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '75%',
      plugins: {
        legend: { position: 'right', labels: { usePointStyle: true, boxWidth: 10, font: { size: 11, family: 'Inter, sans-serif' } } },
        datalabels: {
          color: '#ffffff',
          font: { weight: '600', size: 13, family: 'Inter, sans-serif' },
          display: function(context) { return context.dataset.data[context.dataIndex] > 0; }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.85)',
          titleFont: { size: 13, family: 'Inter, sans-serif' },
          bodyFont: { size: 12, family: 'Inter, sans-serif' },
          padding: 12,
          cornerRadius: 8,
          displayColors: false
        }
      },
      animation: { animateScale: true, animateRotate: true }
    }
  });

  const rejection = visuals.rejection || {};
  const rejectReasons = rejection.reasons || [];
  const rejected = Number(rejection.qualityRejected ?? rejection.rejected ?? 0);
  const evidenceGaps = Number(rejection.evidenceGaps || 0);
  const review = Number(rejection.review || 0);
  const accepted = Number(rejection.accepted || 0);
  const gateTotal = Number(rejection.qualityTotal || accepted + rejected + review);
  const allCandidates = Number(rejection.total || gateTotal + evidenceGaps);
  const publishRate = allCandidates ? Math.round((accepted / allCandidates) * 100) : 0;
  const rejectRate = Number(rejection.rejectRate || 0);

  // 2. Quality gate: connects crawler output to the Agent curation result.
  if (els.blockTotal) {
    els.blockTotal.textContent = allCandidates ? `发布 ${publishRate}%` : "--";
    els.blockTotal.title = allCandidates
      ? `全部候选 ${allCandidates} 条：发布 ${accepted} 条，证据缺口 ${evidenceGaps} 条，质量拒绝 ${rejected} 条，待复核 ${review} 条`
      : "暂无质量门禁数据";
  }
  
  initOrUpdateChart('blockCanvas', {
    type: 'bar',
    data: {
      labels: ['候选事实'],
      datasets: [
        {
          label: '通过发布',
          data: [accepted],
          backgroundColor: 'rgba(16, 185, 129, 0.92)',
          hoverBackgroundColor: 'rgba(5, 150, 105, 1)',
          borderRadius: 7,
          barThickness: 28
        },
        {
          label: '证据缺口',
          data: [evidenceGaps],
          backgroundColor: 'rgba(148, 163, 184, 0.9)',
          hoverBackgroundColor: 'rgba(100, 116, 139, 1)',
          borderRadius: 7,
          barThickness: 28
        },
        {
          label: '质量拒绝',
          data: [rejected],
          backgroundColor: 'rgba(239, 68, 68, 0.88)',
          hoverBackgroundColor: 'rgba(220, 38, 38, 1)',
          borderRadius: 7,
          barThickness: 28
        },
        {
          label: '待复核',
          data: [review],
          backgroundColor: 'rgba(245, 158, 11, 0.9)',
          hoverBackgroundColor: 'rgba(217, 119, 6, 1)',
          borderRadius: 7,
          barThickness: 28
        }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      layout: {
        padding: { left: 8, right: 8, top: 10, bottom: 2 }
      },
      plugins: {
        legend: {
          display: allCandidates > 0,
          position: 'bottom',
          labels: {
            usePointStyle: true,
            boxWidth: 8,
            padding: 14,
            font: { size: 11, family: 'Inter, sans-serif' }
          }
        },
        datalabels: {
          color: '#ffffff',
          anchor: 'center',
          align: 'center',
          font: { weight: '700', size: 11, family: 'Inter, sans-serif' },
          formatter: (value, context) => value > 0 ? `${context.dataset.label} ${value}` : "",
          display: (context) => Number(context.dataset.data[context.dataIndex]) > 0
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.85)',
          cornerRadius: 8,
          callbacks: {
            label: (item) => `${item.dataset.label}：${item.formattedValue} 条`
          }
        }
      },
      scales: {
        x: { display: false, stacked: true, max: allCandidates || 1 },
        y: { display: false, stacked: true }
      }
    }
  });

  // 3. Unpublished analysis: distinguish missing evidence from actual quality rejection.
  if (els.sourceTotal) {
    els.sourceTotal.textContent = allCandidates ? `缺口 ${evidenceGaps} · 拦截 ${rejected}` : "--";
    els.sourceTotal.title = allCandidates
      ? `共 ${allCandidates} 条：发布 ${accepted} 条，证据缺口 ${evidenceGaps} 条，质量拦截 ${rejected} 条`
      : "暂无清洗拦截数据";
  }

  const chips = [
    ...(evidenceGaps ? [{ label: "证据未覆盖，需补爬", value: evidenceGaps, kind: "gap" }] : []),
    ...rejectReasons.slice(0, evidenceGaps ? 5 : 6),
  ].map((item) => ({
    ...item,
    label: String(item.label || "").replace("未通过指标格式与单位门禁", "格式/单位未过")
      .replace("数值或事实依据不足", "依据不足")
      .replace("置信度低于80%", "置信度低")
      .replace("模型未确认主体归属", "主体未确认")
      .replace("来源域名或证据文本不支持该主体", "来源不匹配")
      .replace("指标名疑似串入公司名称", "指标名异常")
      .replace("抽取结果不可用", "抽取不可用")
  }));
  
  initOrUpdateChart('sourceCanvas', {
    type: 'bar',
    data: {
      labels: chips.map(c => c.label),
      datasets: [{
        data: chips.map(c => c.value),
        backgroundColor: [
          'rgba(59, 130, 246, 0.85)',
          'rgba(16, 185, 129, 0.85)',
          'rgba(245, 158, 11, 0.85)',
          'rgba(239, 68, 68, 0.85)',
          'rgba(139, 92, 246, 0.85)',
          'rgba(14, 165, 233, 0.85)',
          'rgba(236, 72, 153, 0.85)'
        ],
        hoverBackgroundColor: [
          'rgba(96, 165, 250, 1)',
          'rgba(52, 211, 153, 1)',
          'rgba(251, 191, 36, 1)',
          'rgba(248, 113, 113, 1)',
          'rgba(167, 139, 250, 1)',
          'rgba(56, 189, 248, 1)',
          'rgba(244, 114, 182, 1)'
        ],
        borderRadius: 6,
        barThickness: 10
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      layout: {
        padding: { right: 40 }
      },
      plugins: {
        legend: { display: false },
        datalabels: {
          color: '#475569',
          anchor: 'end',
          align: 'right',
          font: { weight: '600', size: 12, family: 'Inter, sans-serif' },
          display: function(context) { return context.dataset.data[context.dataIndex] > 0; }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.85)',
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            title: (items) => items?.[0]?.label || "",
            label: (item) => `${item.label}：${item.formattedValue} 条；本轮发布 ${accepted} 条`
          }
        }
      },
      scales: {
        x: { display: false },
        y: { 
          grid: { display: false }, 
          border: { display: false }, 
          ticks: { font: { size: 11, family: 'Inter, sans-serif' }, color: '#475569' } 
        }
      }
    }
  });
}

function renderOutputTable(target, files, emptyTitle, emptyHint, type) {
  if (!target) return;
  const selectColumn = state.multiSelect ? "<span></span>" : "";
  const tableTone = type === "performance" ? "performance-tone" : "weekly-tone";
  if (!files.length) {
    target.innerHTML = `
      <div class="file-header ${state.multiSelect ? "with-select" : ""} ${tableTone}">
        ${selectColumn}<span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
      </div>
      <div class="file-row ${state.multiSelect ? "with-select" : ""} empty-row ${tableTone}">
        ${selectColumn}<strong>${emptyTitle}</strong><span>${emptyHint}</span><span>-</span><span>-</span>
      </div>
    `;
    return;
  }

  let html = `
    <div class="file-header ${state.multiSelect ? "with-select" : ""} ${tableTone}">
      ${selectColumn}<span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
    </div>
  `;
  files.forEach((file) => {
    const typeInfo = fileType(file.name);
    const safePath = escapeHtml(file.path_str);
    const checked = state.selectedFiles.has(file.path_str) ? "checked" : "";
    const audioAction = file.audio && file.audio.exists
      ? `<button type="button" class="row-icon-button audio-play-button" data-audio="${escapeHtml(file.audio.url)}" data-name="${escapeHtml(file.name)}" data-summary="${escapeHtml(file.audio.summary || '')}" title="播放音频摘要" aria-label="播放音频摘要">${iconSvg("volume")}</button>`
      : `<button type="button" class="row-icon-button generate-audio-button" data-path="${safePath}" title="生成音频摘要" aria-label="生成音频摘要">${iconSvg("waveform")}</button>`;
    html += `
      <div class="file-row ${typeInfo.className} ${tableTone} ${state.multiSelect ? "with-select" : ""} ${checked ? "is-selected" : ""}" data-path="${safePath}">
        ${state.multiSelect ? `<span class="select-cell"><input type="checkbox" class="file-checkbox" data-path="${safePath}" ${checked} aria-label="选择 ${escapeHtml(file.name)}"></span>` : ""}
        <span class="file-name-cell" title="${file.name}">${typeInfo.icon} ${file.name}</span>
        <span>${fileDescription(file)}</span>
        <span class="time-cell">${file.mtimeText}</span>
        <span class="action-cell">
          ${audioAction}
          <button type="button" class="row-icon-button edit-file-button" data-path="${safePath}" title="编辑" aria-label="编辑">${iconSvg("edit")}</button>
          <button type="button" class="row-icon-button danger delete-file-button" data-path="${safePath}" title="删除" aria-label="删除">${iconSvg("trash")}</button>
          <a href="${file.url}" download class="quiet-button small" style="text-decoration:none;">下载</a>
        </span>
      </div>
    `;
  });
  target.innerHTML = html;
}

function bindOutputTableEvents(target) {
  if (!target) return;
  target.querySelectorAll(".edit-file-button").forEach((button) => {
    button.addEventListener("click", () => openFileEditor(button.dataset.path));
  });
  target.querySelectorAll(".delete-file-button").forEach((button) => {
    button.addEventListener("click", () => deleteFiles([button.dataset.path]));
  });
  target.querySelectorAll(".generate-audio-button").forEach((button) => {
    button.addEventListener("click", () => generateAudio(button.dataset.path, button));
  });
  target.querySelectorAll(".audio-play-button").forEach((button) => {
    button.addEventListener("click", () => playAudio(button.dataset.audio, button, button.dataset.name, button.dataset.summary));
  });
  target.querySelectorAll(".file-checkbox").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedFiles.add(checkbox.dataset.path);
      else state.selectedFiles.delete(checkbox.dataset.path);
      renderFileList();
    });
  });
  target.querySelectorAll(".file-row.with-select").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (event.target.closest("button, a, input")) return;
      const path = row.dataset.path;
      if (!path) return;
      if (state.selectedFiles.has(path)) state.selectedFiles.delete(path);
      else state.selectedFiles.add(path);
      renderFileList();
    });
  });
}

function renderFileList() {
  const weeklyFiles = outputsByType("weekly");
  const performanceFiles = outputsByType("performance");
  const files = [...weeklyFiles, ...performanceFiles];
  const selectedCount = state.selectedFiles.size;

  if (els.fileCountText) els.fileCountText.textContent = state.multiSelect ? `选择模式 · 已选 ${selectedCount} / ${files.length}` : `${files.length} 个文件`;
  if (els.weeklyFileCountText) els.weeklyFileCountText.textContent = state.multiSelect ? `已选 ${selectedCount} / ${weeklyFiles.length}` : `${weeklyFiles.length} 个文件`;
  if (els.performanceFileCountText) els.performanceFileCountText.textContent = state.multiSelect ? `已选 ${selectedCount} / ${performanceFiles.length}` : `${performanceFiles.length} 个文件`;
  els.multiSelectTriggers.forEach((button) => {
    button.classList.toggle("is-active", state.multiSelect);
  });
  els.deleteSelectedTriggers.forEach((button) => {
    button.hidden = !state.multiSelect;
    button.disabled = selectedCount === 0;
  });

  renderOutputTable(els.weeklyFileList || els.fileList, weeklyFiles, "暂无周报", "请先生成 Word 周报", "weekly");
  renderOutputTable(els.performanceFileList, performanceFiles, "暂无业绩摘要", "请先生成业绩摘要", "performance");
  bindOutputTableEvents(els.weeklyFileList || els.fileList);
  bindOutputTableEvents(els.performanceFileList);
}

function renderStatus(status) {
  state.status = status;
  els.statusSummary.textContent = `数据 ${status.results.count} 个 · 范围 ${status.settings.enabledRows}/${status.settings.totalRows} 行 · 输出 ${status.latestOutputText}`;
  if (status.ai && els.aiConfigStatus) {
    els.aiConfigStatus.textContent = `${status.ai.provider} / ${status.ai.model} / ${status.ai.base_url} / ${status.ai.has_api_key ? "API Key 已保存" : "未保存 API Key"}`;
  }
  renderInsights(status);
  state.outputs = status.outputs || [];
  const existing = new Set(state.outputs.map((item) => item.path_str));
  for (const path of state.selectedFiles) {
    if (!existing.has(path)) state.selectedFiles.delete(path);
  }
  renderFileList();
}

function appendLog(text) {
  els.logBox.appendChild(document.createTextNode(text));
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

function compactJson(value) {
  if (value === undefined || value === null || value === "") return "";
  try {
    return JSON.stringify(value, null, 2);
  } catch (error) {
    return String(value);
  }
}

function tracePhaseLabel(phase) {
  const labels = {
    observe: "正在分析",
    answer: "本步结论",
    tool_call: "调用工具",
    tool_result: "工具返回",
  };
  return labels[phase] || phase || "事件";
}

const TRACE_STEPS = {
  "证据接收": 1,
  "来源分类": 2,
  "事实抽取": 3,
  "主体校验": 4,
  "质量审计": 5,
  "冲突仲裁": 6,
  "缺口规划": 7,
  "定向补爬": 7,
  "发布": 8,
};

function traceFriendlyTool(tool) {
  const text = String(tool || "");
  if (!text) return "";
  if (text.includes("DeepSeek")) return "DeepSeek 事实清洗模型";
  if (text.includes("fallback_clean_batch")) return "本地严格校验器";
  if (text.includes("atomic_write")) return "事实发布与审计文件写入";
  if (text.includes("run_data_curation")) return "LangGraph 多 Agent 工作流";
  if (text.includes("daily_crawl_and_write")) return "飞书日志同步器";
  if (text.includes("subprocess")) return "定向补爬器";
  return text;
}

function traceFriendlyMessage(trace, phase) {
  const node = trace.node || "Agent";
  const messages = {
    "证据接收": "读取本轮爬取证据，并检查是否有可复用的历史高质量结果。",
    "来源分类": "按官网、政府、交易所、公共来源和商业数据源评估证据可信度。",
    "事实抽取": "从原始网页片段中提取公司、指标、数值、单位和依据。",
    "主体校验": "确认每条事实确实属于对应公司和指标，避免串行、串公司。",
    "质量审计": "检查数值、单位、来源、置信度和网页噪声，决定发布、拦截或补爬。",
    "冲突仲裁": "比较同一公司同一指标的多个结果，保留证据更强的版本。",
    "缺口规划": "把没有足够证据的指标整理为补爬任务。",
    "定向补爬": "只重抓缺少关键事实的行，并重新进入整理流程。",
    "发布": "写入可供页面、周报和业绩摘要使用的已验证事实。",
  };
  if (phase === "observe" && messages[node]) return messages[node];
  return trace.message || messages[node] || "";
}

function traceKeyMetrics(trace) {
  const data = trace.result && typeof trace.result === "object"
    ? trace.result
    : trace.output && typeof trace.output === "object"
      ? trace.output
      : {};
  const fields = [
    ["tasks", "证据"],
    ["task_count", "本批"],
    ["cached", "缓存"],
    ["cache_reused", "复用"],
    ["pending", "待处理"],
    ["returned", "返回"],
    ["candidates", "候选事实"],
    ["accepted", "可发布"],
    ["review", "待复核"],
    ["rejected", "未发布"],
    ["unpublished", "未发布"],
    ["evidence_gaps", "证据缺口"],
    ["quality_rejected", "质量拒绝"],
    ["pre_rejected", "归属异常"],
    ["gaps", "证据缺口"],
    ["conflicts", "冲突"],
    ["preserved_previous_facts", "保留历史事实"],
    ["durationMs", "耗时"],
  ];
  return fields
    .filter(([key]) => data[key] !== undefined && data[key] !== null)
    .map(([key, label]) => {
      const value = key === "durationMs" ? `${(Number(data[key]) / 1000).toFixed(1)} 秒` : data[key];
      return { label, value };
    });
}

function renderAgentRunSummary(summary) {
  if (!els.logBox || !summary || !summary.run_id) return;
  const panel = document.createElement("section");
  panel.className = "agent-run-summary";
  const total = Number(summary.tasks || 0);
  const accepted = Number(summary.accepted || 0);
  const rejected = Number(summary.rejected || 0);
  const gaps = Number(summary.gaps || 0);
  panel.innerHTML = `
    <div>
      <strong>最近一次 Agent 整理结果</strong>
      <span>${escapeHtml(String(summary.completed_at || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, ""))}</span>
    </div>
    <ul>
      <li><b>${total}</b><span>原始证据</span></li>
      <li><b>${accepted}</b><span>可发布事实</span></li>
      <li><b>${gaps}</b><span>待补爬缺口</span></li>
      <li><b>${rejected}</b><span>未发布总数</span></li>
    </ul>
  `;
  els.logBox.appendChild(panel);
}

function renderAgentTrace(trace, options = {}) {
  if (!els.logBox || !trace) return;
  const card = document.createElement("section");
  const phase = trace.phase || trace.event_type || "agent";
  card.className = `agent-trace-card phase-${phase}`;
  const title = document.createElement("div");
  title.className = "agent-trace-title";
  const node = escapeHtml(trace.node || "Agent");
  const step = TRACE_STEPS[trace.node];
  const stepText = step ? `第 ${step}/8 步` : "工作流";
  const label = escapeHtml(tracePhaseLabel(phase));
  const time = escapeHtml((trace.ts || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, ""));
  title.innerHTML = `<span class="agent-trace-step">${stepText}</span><strong>${node}</strong><span class="agent-trace-badge">${label}</span><time>${time}</time>`;
  card.appendChild(title);

  const message = document.createElement("p");
  message.className = "agent-trace-message";
  message.textContent = traceFriendlyMessage(trace, phase);
  card.appendChild(message);

  const metrics = traceKeyMetrics(trace);
  if (metrics.length) {
    const metricBox = document.createElement("div");
    metricBox.className = "agent-trace-metrics";
    metricBox.innerHTML = metrics.map((item) =>
      `<span><b>${escapeHtml(String(item.value))}</b>${escapeHtml(item.label)}</span>`
    ).join("");
    card.appendChild(metricBox);
  }

  const details = [
    ["输入", trace.input],
    ["工具", traceFriendlyTool(trace.tool)],
    ["结果", trace.result],
    ["输出", trace.output],
  ].filter(([, value]) => value !== undefined && value !== null && value !== "");
  if (details.length) {
    const box = document.createElement("div");
    box.className = "agent-trace-details";
    details.forEach(([name, value]) => {
      const item = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = name === "工具" ? "使用的工具" : `查看${name}技术详情`;
      const pre = document.createElement("pre");
      pre.textContent = compactJson(value);
      item.append(summary, pre);
      box.appendChild(item);
    });
    card.appendChild(box);
  }
  els.logBox.appendChild(card);
  if (!options.skipScroll) els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

function setLog(text) {
  els.logBox.innerHTML = "";
  els.logBox.appendChild(document.createTextNode(text));
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", text);
}

async function loadLatestAgentTrace() {
  if (!els.logBox) return;
  if (state.agentTraceLoaded) return;
  try {
    const response = await fetch("/api/agent-trace?limit=250");
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.trace) || !data.trace.length) return;
    state.agentTraceLoaded = true;
    renderAgentRunSummary(data.summary);
    data.trace.forEach((trace) => renderAgentTrace(trace, { skipScroll: true }));
    els.logBox.scrollTop = els.logBox.scrollHeight;
  } catch (error) {
    appendLog(`\nAgent 轨迹加载失败：${error.message}\n`);
  }
}

// Load logs on startup
const savedLogs = localStorage.getItem("appLogs");
if (savedLogs) {
  els.logBox.textContent = savedLogs;
  setTimeout(() => els.logBox.scrollTop = els.logBox.scrollHeight, 100);
}

function fillAiConfig(config) {
  els.aiProvider.value = config.provider || "deepseek";
  els.aiBaseUrl.value = config.base_url || "https://api.deepseek.com";
  els.aiModel.value = config.model || "deepseek-v4-flash";
  els.aiApiKey.value = "";
  els.aiApiKey.placeholder = config.has_api_key ? `已保存：${config.api_key}` : "请输入 API Key";
  els.aiConfigStatus.textContent = `${config.provider} / ${config.model} / ${config.base_url} / ${config.has_api_key ? "API Key 已保存" : "未保存 API Key"}`;
}

async function loadAiConfig() {
  const response = await fetch("/api/ai-config");
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "AI 设置加载失败");
  fillAiConfig(data.config);
}

async function saveAiConfig() {
  const payload = {
    provider: els.aiProvider.value,
    base_url: els.aiBaseUrl.value.trim(),
    model: els.aiModel.value.trim(),
    api_key: els.aiApiKey.value.trim(),
  };
  const response = await fetch("/api/ai-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "AI 设置保存失败");
  fillAiConfig(data.config);
  renderStatus(data.status);
  return data.config;
}

async function testAiConfig() {
  els.aiConfigStatus.textContent = "正在测试 LLM + RAG 连接...";
  const response = await fetch("/api/ai-test", { method: "POST" });
  const data = await response.json();
  if (data.ok) {
    els.aiConfigStatus.textContent = `连接成功：${data.result.provider || ""} ${data.result.model || ""}`;
  } else {
    els.aiConfigStatus.textContent = data.result?.error || data.error || "连接失败";
  }
  if (data.status) renderStatus(data.status);
}

async function fetchStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "状态获取失败");
  renderStatus(data.status);
}

function openFileEditor(pathStr) {
  const file = state.outputs.find((item) => item.path_str === pathStr);
  if (!file) return;
  state.editingFile = file;
  els.editFileName.value = file.name;
  els.editFileNote.value = file.note || "";
  els.fileEditStatus.textContent = "";
  els.fileEditModal.hidden = false;
  setTimeout(() => els.editFileName.focus(), 0);
}

function closeFileEditor() {
  els.fileEditModal.hidden = true;
  state.editingFile = null;
}

async function saveFileEdit() {
  if (!state.editingFile) return;
  els.fileEditStatus.textContent = "正在保存...";
  const response = await fetch("/api/report-file", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      path: state.editingFile.path_str,
      name: els.editFileName.value.trim(),
      note: els.editFileNote.value.trim(),
    }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "保存失败");
  renderStatus(data.status);
  closeFileEditor();
}

async function deleteFiles(paths) {
  const list = paths.filter(Boolean);
  if (!list.length) return;
  if (!confirm(`确定删除选中的 ${list.length} 个周报文件吗？此操作不可恢复。`)) return;
  const response = await fetch("/api/delete-files", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paths: list }),
  });
  const data = await response.json();
  if (!data.ok) {
    alert(data.error || "删除失败");
    return;
  }
  list.forEach((path) => state.selectedFiles.delete(path));
  if (!state.selectedFiles.size) state.multiSelect = false;
  renderStatus(data.status);
}

async function generateAudio(pathStr, button = null) {
  if (!pathStr) return;
  if (button) {
    button.disabled = true;
    button.classList.add("is-loading");
  }
  appendLog(`\n[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 开始生成音频摘要...\n`);
  try {
    const response = await fetch("/api/audio/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: pathStr, force: true }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.result?.error || data.error || "音频生成失败");
    renderStatus(data.status);
    appendLog(`音频摘要已生成：${data.result.audio?.name || ""}（${data.result.backend || "unknown"}）\n`);
  } catch (error) {
    appendLog(`音频生成失败：${error.message}\n`);
    alert(error.message);
  } finally {
    if (button) {
      button.disabled = false;
      button.classList.remove("is-loading");
    }
  }
}

function formatTime(seconds) {
  if (isNaN(seconds)) return "00:00";
  const m = Math.floor(seconds / 60).toString().padStart(2, "0");
  const s = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function updateAudioPlayerUI() {
  if (!state.currentAudio) return;
  const isPlaying = !state.currentAudio.paused;
  
  const playIcon = els.audioPlayPauseBtn.querySelector(".icon-play");
  const pauseIcon = els.audioPlayPauseBtn.querySelector(".icon-pause");
  if (playIcon) playIcon.style.display = isPlaying ? "none" : "block";
  if (pauseIcon) pauseIcon.style.display = isPlaying ? "block" : "none";
  
  const soundwave = document.getElementById("audioSoundwave");
  if (soundwave) {
    soundwave.hidden = !isPlaying;
  }
  
  if (state.currentAudioButton) {
    state.currentAudioButton.classList.toggle("is-playing", isPlaying);
  }
}

function updateSubtitles() {
  const subtitleDiv = document.getElementById("audioSubtitle");
  if (!subtitleDiv || !state.currentAudio || !state.currentAudio.duration || !subtitleDiv.dataset.fullText) return;
  
  const progress = state.currentAudio.currentTime / state.currentAudio.duration;
  if (isNaN(progress)) return;
  
  let sentences;
  if (!subtitleDiv.dataset.sentences) {
    const text = subtitleDiv.dataset.fullText;
    sentences = text.match(/[^。！？\n]+[。！？\n]*/g) || [text];
    subtitleDiv.dataset.sentences = JSON.stringify(sentences);
  } else {
    sentences = JSON.parse(subtitleDiv.dataset.sentences);
  }
  
  const totalChars = subtitleDiv.dataset.fullText.length;
  const currentChars = progress * totalChars;
  
  let charSum = 0;
  let activeIndex = 0;
  for (let i = 0; i < sentences.length; i++) {
    charSum += sentences[i].length;
    if (currentChars <= charSum) {
      activeIndex = i;
      break;
    }
  }
  
  if (subtitleDiv.dataset.activeIndex === String(activeIndex)) return;
  subtitleDiv.dataset.activeIndex = activeIndex;
  
  let html = "";
  sentences.forEach((s, i) => {
    if (i < activeIndex) {
      html += `<div style="color: rgba(255,255,255,0.4); font-size: 13px; transition: all 0.3s; margin-bottom: 8px;">${escapeHtml(s)}</div>`;
    } else if (i === activeIndex) {
      html += `<div style="color: #fff; font-size: 15px; font-weight: bold; transition: all 0.3s; margin-bottom: 8px; text-shadow: 0 1px 2px rgba(0,0,0,0.5);">${escapeHtml(s)}</div>`;
    } else {
      html += `<div style="color: rgba(255,255,255,0.15); font-size: 13px; transition: all 0.3s; margin-bottom: 8px;">${escapeHtml(s)}</div>`;
    }
  });
  
  // Add padding elements so the active text stays near the center
  subtitleDiv.innerHTML = `<div style="height: 30px;"></div>` + html + `<div style="height: 30px;"></div>`;
  
  // smooth scrolling
  const activeEl = subtitleDiv.children[activeIndex + 1]; // +1 because of the top padding div
  if (activeEl) {
    const scrollTarget = activeEl.offsetTop - subtitleDiv.clientHeight / 2 + activeEl.clientHeight / 2;
    subtitleDiv.scrollTo({ top: scrollTarget, behavior: 'smooth' });
  }
}

function playAudio(url, button = null, fileName = "音频摘要", summary = "") {
  if (!url) return;
  
  // Toggle pause if clicking the same active audio
  if (state.currentAudio && state.currentAudio.src.includes(url)) {
    if (!state.currentAudio.paused) {
      state.currentAudio.pause();
    } else {
      state.currentAudio.play();
    }
    updateAudioPlayerUI();
    return;
  }
  
  // Stop previous audio
  if (state.currentAudio) {
    state.currentAudio.pause();
    if (state.currentAudioButton) state.currentAudioButton.classList.remove("is-playing");
    state.currentAudio.src = "";
    const subtitleDiv = document.getElementById("audioSubtitle");
    if (subtitleDiv) {
      subtitleDiv.dataset.fullText = "";
      subtitleDiv.dataset.sentences = "";
      subtitleDiv.dataset.activeIndex = "";
    }
  }
  
  // Initialize new audio
  state.currentAudio = new Audio(url);
  const audioSpeedBtn = document.getElementById("audioSpeedBtn");
  if (audioSpeedBtn) {
    state.currentAudio.playbackRate = parseFloat(audioSpeedBtn.textContent) || 1.0;
  }
  state.currentAudioButton = button;
  els.audioFileName.textContent = fileName || "音频摘要";
  const subtitleDiv = document.getElementById("audioSubtitle");
  if (subtitleDiv) {
    if (summary) {
      subtitleDiv.dataset.fullText = summary;
      subtitleDiv.dataset.sentences = "";
      subtitleDiv.dataset.activeIndex = "";
      subtitleDiv.hidden = false;
      subtitleDiv.style.display = "none"; // Hide by default until user clicks expand
      els.subtitleToggleBtn.hidden = false;
      els.subtitleToggleBtn.classList.remove("is-expanded");
      updateSubtitles();
    } else {
      subtitleDiv.dataset.fullText = "";
      subtitleDiv.hidden = true;
      subtitleDiv.style.display = "none";
      els.subtitleToggleBtn.hidden = true;
    }
  }
  
  // Show global player
  els.audioPlayer.hidden = false;
  
  // Bind events
  state.currentAudio.addEventListener("loadedmetadata", () => {
    els.audioDuration.textContent = formatTime(state.currentAudio.duration);
    els.audioProgressBar.max = state.currentAudio.duration;
  });
  
  state.currentAudio.addEventListener("timeupdate", () => {
    els.audioCurrentTime.textContent = formatTime(state.currentAudio.currentTime);
    if (!state.isScrubbing) {
      els.audioProgressBar.value = state.currentAudio.currentTime || 0;
    }
    updateSubtitles();
  });
  
  state.currentAudio.addEventListener("play", updateAudioPlayerUI);
  state.currentAudio.addEventListener("pause", updateAudioPlayerUI);
  state.currentAudio.addEventListener("ended", () => {
    updateAudioPlayerUI();
    els.audioProgressBar.value = 0;
    els.audioCurrentTime.textContent = "00:00";
  });
  
  if (els.subtitleToggleBtn) {
    els.subtitleToggleBtn.onclick = () => {
      const subtitleDiv = document.getElementById("audioSubtitle");
      if (!subtitleDiv) return;
      const isExpanded = els.subtitleToggleBtn.classList.toggle("is-expanded");
      subtitleDiv.style.display = isExpanded ? "block" : "none";
      if (isExpanded) updateSubtitles();
    };
  }
  
  state.currentAudio.play().catch((error) => {
    updateAudioPlayerUI();
    appendLog(`音频播放失败：${error.message}\n`);
  });
}

// Global Audio Player Events
if (els.audioPlayPauseBtn) {
  els.audioPlayPauseBtn.addEventListener("click", () => {
    if (!state.currentAudio) return;
    if (state.currentAudio.paused) {
      state.currentAudio.play();
    } else {
      state.currentAudio.pause();
    }
  });
}

if (els.audioProgressBar) {
  els.audioProgressBar.addEventListener("mousedown", () => state.isScrubbing = true);
  els.audioProgressBar.addEventListener("touchstart", () => state.isScrubbing = true);
  
  els.audioProgressBar.addEventListener("input", (e) => {
    state.isScrubbing = true;
    els.audioCurrentTime.textContent = formatTime(e.target.value);
    if (state.currentAudio) {
      state.currentAudio.currentTime = e.target.value;
    }
  });
  
  els.audioProgressBar.addEventListener("change", (e) => {
    state.isScrubbing = false;
  });
  
  els.audioProgressBar.addEventListener("mouseup", () => state.isScrubbing = false);
  els.audioProgressBar.addEventListener("touchend", () => {
    state.isScrubbing = false;
  });
}

const audioSpeedBtn = document.getElementById("audioSpeedBtn");
if (audioSpeedBtn) {
  const speeds = [1.0, 1.25, 1.5, 2.0];
  let currentSpeedIdx = 0;
  audioSpeedBtn.addEventListener("click", () => {
    currentSpeedIdx = (currentSpeedIdx + 1) % speeds.length;
    const newSpeed = speeds[currentSpeedIdx];
    audioSpeedBtn.textContent = newSpeed.toFixed(1) + "x";
    if (state.currentAudio) {
      state.currentAudio.playbackRate = newSpeed;
    }
  });
}

if (els.audioCloseBtn) {
  els.audioCloseBtn.addEventListener("click", () => {
    if (state.currentAudio) {
      state.currentAudio.pause();
      if (state.currentAudioButton) state.currentAudioButton.classList.remove("is-playing");
    }
    els.audioPlayer.hidden = true;
  });
}

async function runCrawl(source = "按钮") {
  setBusy(true, "正在重新爬取", "crawl");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 开始启动后台爬虫任务...\n`);
  try {
    const res = await fetch("/api/crawl-stream?v=12", { method: "POST" });
    if (!res.ok) throw new Error("网络请求失败");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.replace(/^data:\s*/, ""));
        
        if (event.type === "log") {
          if (event.text) {
            appendLog(event.text + "\n");
          }
        } else if (event.type === "agent_trace") {
          renderAgentTrace(event.trace);
        } else if (event.type === "crawl_summary") {
          const successCount = event.success ? event.success.length : 0;
          const failedCount = event.failed ? event.failed.length : 0;
          let html = `<div class="crawl-summary-card">
            <div class="summary-header">
              <span class="summary-title">爬取报告汇总</span>
              <div class="summary-stats">
                <span class="stat-success">成功: ${successCount}</span>
                <span class="stat-failed">失败: ${failedCount}</span>
              </div>
            </div>`;
            
          html += `<details class="summary-details"><summary>查看失败明细 (${failedCount})</summary><div class="details-content">`;
          if (failedCount > 0) {
            html += `<table class="summary-table"><tr><th>拦截原因/错误</th><th>URL</th></tr>`;
            event.failed.forEach(item => {
              let extraLink = '';
              if (item.reason.includes('robots.txt')) {
                try {
                  const urlObj = new URL(item.url);
                  const robotsUrl = urlObj.origin + '/robots.txt';
                  extraLink = `<br><a href="${escapeHtml(robotsUrl)}" target="_blank" style="font-size: 11px; color: #5f6368; margin-top: 4px; display: inline-block;">查看该站点的 robots.txt</a>`;
                } catch (e) {}
              }
              html += `<tr><td><span class="tag-error">${escapeHtml(item.reason)}</span>${extraLink}</td><td><a href="${escapeHtml(item.url)}" target="_blank">${escapeHtml(item.url)}</a></td></tr>`;
            });
            html += `</table>`;
          } else {
            html += `<p class="empty-msg">所有链接均抓取成功。</p>`;
          }
          html += `</div></details>`;
          
          html += `<details class="summary-details"><summary>查看成功明细 (${successCount})</summary><div class="details-content">`;
          if (successCount > 0) {
            html += `<table class="summary-table"><tr><th>状态</th><th>URL</th></tr>`;
            event.success.forEach(item => {
              html += `<tr><td><span class="tag-success">OK</span></td><td><a href="${escapeHtml(item.url)}" target="_blank">${escapeHtml(item.url)}</a></td></tr>`;
            });
            html += `</table>`;
          } else {
            html += `<p class="empty-msg">未找到成功的链接。</p>`;
          }
          html += `</div></details></div>\n`;
          
          // Append raw HTML safely since we are creating it
          const div = document.createElement('div');
          div.innerHTML = html;
          els.logBox.appendChild(div);
          els.logBox.scrollTop = els.logBox.scrollHeight;
        } else if (event.type === "done") {
          appendLog(`\n[爬取结束] 最终状态：${event.ok ? "成功" : "失败"}\n总耗时：${event.durationMs} ms\n`);
          renderStatus(event.status);
          await fetchStatus();
          setBusy(false);
          return;
        }
      }
    }
  } catch (err) {
    appendLog(`\n\n执行异常：${err.message}`);
  }
  setBusy(false);
}

async function generateReport(source = "按钮") {
  setBusy(true, "正在生成", "generate");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成周报，请稍候...\n`);
  try {
    const res = await fetch("/api/generate-stream", { method: "POST" });
    if (!res.ok) throw new Error("网络请求失败");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.replace(/^data:\s*/, ""));
        
        if (event.type === "log") {
          if (event.text) {
            appendLog(event.text + "\n");
          }
        } else if (event.type === "agent_trace") {
          renderAgentTrace(event.trace);
        } else if (event.type === "done") {
          appendLog(`\n[生成结束] 最终状态：${event.ok ? "成功" : "失败"}\n总耗时：${event.durationMs} ms\n`);
          if (event.audio && !event.audio.ok) {
             appendLog(`语音摘要失败：${event.audio.error}\n`);
          }
          renderStatus(event.status);
          setBusy(false);
          return;
        }
      }
    }
  } catch (error) {
    appendLog(`\n生成失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

async function generateCarrierPerformanceReport(source = "按钮") {
  setBusy(true, "正在生成", "performance");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成业绩摘要，请稍候...\n`);
  try {
    const response = await fetch(`/api/generate-carrier-performance-stream`, { method: "POST" });
    if (!response.ok) throw new Error("网络请求失败");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.replace(/^data:\s*/, ""));
        if (event.type === "log") {
          if (event.text) appendLog(event.text + "\n");
        } else if (event.type === "agent_trace") {
          renderAgentTrace(event.trace);
        } else if (event.type === "done") {
          appendLog(`\n[生成结束] 最终状态：${event.ok ? "成功" : "失败"}\n总耗时：${event.durationMs} ms\n`);
          if (event.audio && !event.audio.ok) appendLog(`语音摘要失败：${event.audio.error}\n`);
          renderStatus(event.status);
          return;
        }
      }
    }
  } catch (error) {
    appendLog(`\n生成失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let listType = null;

  function closeList() {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      continue;
    }
    if (/^[-*_]{3,}$/.test(line)) {
      closeList();
      html.push("<hr />");
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 2, 5);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const plainHeading =
      line.length <= 18 &&
      !/[。；;，,]/.test(line) &&
      !/^\d+[.、]/.test(line) &&
      !/^[-*]\s+/.test(line);
    if (plainHeading || /^[一二三四五六七八九十]+[、.]\s*.+/.test(line)) {
      closeList();
      html.push(`<h3>${inlineMarkdown(line.replace(/^[一二三四五六七八九十]+[、.]\s*/, ""))}</h3>`);
      continue;
    }
    if (/^[^：:]{2,18}[：:]$/.test(line)) {
      closeList();
      html.push(`<h3>${inlineMarkdown(line.replace(/[：:]$/, ""))}</h3>`);
      continue;
    }
    const ordered = line.match(/^\d+[.、]\s*(.+)$/);
    if (ordered) {
      if (listType !== "ol") {
        closeList();
        listType = "ol";
        html.push("<ol>");
      }
      html.push(`<li>${inlineMarkdown(ordered[1])}</li>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (listType !== "ul") {
        closeList();
        listType = "ul";
        html.push("<ul>");
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  return html.join("");
}

function setMessageContent(node, content, markdown = false) {
  const text = node.querySelector(".message-text") || node.querySelector(".markdown-body");
  if (markdown) {
    if (text.className === "message-text") text.className = "markdown-body";
    let html = typeof marked !== 'undefined' ? marked.parse(content) : content;
    html = html.replace(/\[(\d+)\]/g, '<sup class="citation-link">[$1]</sup>');
    text.innerHTML = html;
  } else {
    text.textContent = content;
  }
}

function addMessage(role, content, markdown = false) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  avatar.textContent = role === "user" ? "您" : "AI";
  const body = document.createElement("div");
  body.className = "message-body";
  const text = document.createElement("div");
  text.className = "message-text";
  body.appendChild(text);
  node.append(avatar, body);
  els.messages.appendChild(node);
  setMessageContent(node, content, markdown);
  els.messages.scrollTop = els.messages.scrollHeight;
  return node;
}

function appendRagProcess(node, text) {
  let processNode = node.querySelector(".rag-process");
  if (!processNode) {
    processNode = document.createElement("div");
    processNode.className = "rag-process";
    const body = node.querySelector(".message-body");
    body.insertBefore(processNode, body.firstChild);
  }
  const step = document.createElement("div");
  step.className = "rag-step";
  step.textContent = text;
  processNode.appendChild(step);
}

function appendRagSources(node, sources, links) {
  let processNode = node.querySelector(".rag-process");
  if (!processNode) {
    processNode = document.createElement("div");
    processNode.className = "rag-process";
    const body = node.querySelector(".message-body");
    body.insertBefore(processNode, body.firstChild);
  }
  const step = document.createElement("div");
  step.className = "rag-sources";
  if (links && links.length) {
    const htmlLinks = links.map((l, i) => `<a href="${l.url}" target="_blank" style="color:var(--blue);text-decoration:none;">[${i+1}] ${l.label}</a>`).join(", ");
    step.innerHTML = `检索来源: ${htmlLinks}`;
  } else if (sources && sources.length) {
    step.textContent = `检索来源: ${sources.join(", ")}`;
  } else {
    return;
  }
  processNode.appendChild(step);
}

function resizeChatInput() {
  els.chatInput.style.height = "auto";
  els.chatInput.style.height = `${Math.min(120, Math.max(42, els.chatInput.scrollHeight))}px`;
}

function generateFallbackSuggestions(userMessage) {
  const msg = userMessage || "";
  const suggestions = [];

  // Context-aware suggestions based on keywords in the user's message
  if (/HKT|csl|1O1O|和电/i.test(msg)) {
    suggestions.push("帮我对比 HKT 和 3HK 的最新财报数据");
    suggestions.push("HKT 最近有什么 5G 相关动态？");
    suggestions.push("触发爬虫更新 HKT 的最新数据");
  } else if (/3HK|Hutchison|和记/i.test(msg)) {
    suggestions.push("3HK 最近的用户增长情况如何？");
    suggestions.push("对比 3HK 和 SmarTone 的套餐价格");
    suggestions.push("搜索 3HK 最新的企业合作动态");
  } else if (/SmarTone|数码通/i.test(msg)) {
    suggestions.push("SmarTone 最新的 5G 覆盖情况如何？");
    suggestions.push("对比 SmarTone 和竞争对手的 ARPU");
    suggestions.push("搜索 SmarTone 最近的战略合作");
  } else if (/HKBN|香港宽频/i.test(msg)) {
    suggestions.push("HKBN 的企业 ICT 业务发展如何？");
    suggestions.push("HKBN 最新的宽带套餐有哪些变化？");
    suggestions.push("搜索 HKBN 最近的并购动态");
  } else if (/周报|报告|总结/i.test(msg)) {
    suggestions.push("帮我分析本周最重要的 3 个竞争情报");
    suggestions.push("对比最近两周的竞对动态变化");
    suggestions.push("触发全量爬虫更新所有数据源");
  } else if (/爬虫|爬取|抓取/i.test(msg)) {
    suggestions.push("查看最近一次爬虫的执行日志");
    suggestions.push("哪些数据源爬取失败了？");
    suggestions.push("帮我重新生成本周周报");
  } else if (/飞书|主表|表格/i.test(msg)) {
    suggestions.push("帮我读取主表前10行的数据");
    suggestions.push("主表中哪些行的数据需要更新？");
    suggestions.push("搜索本地最新的爬取结果");
  } else {
    // Generic fallback
    suggestions.push("帮我总结一下本周竞对的关键动态");
    suggestions.push("搜索最近关于 5G 和 AI 的行业趋势");
    suggestions.push("查看所有竞对的最新财报数据对比");
  }

  return suggestions.slice(0, 3);
}

async function sendChat(message) {
  addMessage("user", message);
  setChatBusy(true);
  try {
    const assistantNode = addMessage("assistant", "正在连接...");
    const response = await fetch("/api/chat-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    if (!response.ok || !response.body) throw new Error("对话请求失败");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    let isDone = false;
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const line = part.split("\n").find((item) => item.startsWith("data:"));
        if (!line) continue;
        const event = JSON.parse(line.replace(/^data:\s*/, ""));
        
        if (event.type === "done") {
          isDone = true;
          break;
        } else if (event.type === "process") {
          appendRagProcess(assistantNode, event.text);
        } else if (event.type === "meta") {
          appendRagSources(assistantNode, event.sources, event.links);
        } else if (event.type === "delta") {
          answer += event.text;
          let displayAnswer = answer;
          const sugMatch = displayAnswer.match(/<suggestions>\s*([\s\S]*?)\s*<\/suggestions>/i);
          let suggestionsHTML = "";
          if (sugMatch) {
            try {
              let jsonStr = sugMatch[1].trim();
              jsonStr = jsonStr.replace(/^```json/i, "").replace(/^```/i, "").replace(/```$/i, "").trim();
              const arr = JSON.parse(jsonStr);
              displayAnswer = displayAnswer.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
              if (arr && arr.length > 0) {
                suggestionsHTML = `<div class="suggestion-chips">` + arr.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${q}</button>`).join('') + `</div>`;
              }
            } catch (e) {
               console.error("Suggestion parse error:", e, sugMatch[1]);
            }
          }
          displayAnswer = displayAnswer.replace(/<suggestions>[\s\S]*$/i, ""); // hide incomplete tags
          
          setMessageContent(assistantNode, displayAnswer, true);
          if (suggestionsHTML) {
            const b = assistantNode.querySelector(".message-text") || assistantNode.querySelector(".markdown-body");
            b.insertAdjacentHTML("beforeend", suggestionsHTML);
          }
          els.messages.scrollTop = els.messages.scrollHeight;
        } else if (event.type === "error") {
          answer += `\n\n**错误：** ${event.text}`;
          let displayAnswer = answer.replace(/<suggestions>[\s\S]*$/, "");
          setMessageContent(assistantNode, displayAnswer, true);
        } else if (event.type === "tool_start") {
          answer += `\n\n> ⏳ **正在运行工具**: \`${event.name}\`\n> 参数: \`${event.input}\`\n\n`;
          setMessageContent(assistantNode, answer, true);
          els.messages.scrollTop = els.messages.scrollHeight;
        } else if (event.type === "tool_end") {
          answer += `\n\n> ✅ **工具返回结果**:\n> \`\`\`\n> ${event.output}\n> \`\`\`\n\n`;
          setMessageContent(assistantNode, answer, true);
          els.messages.scrollTop = els.messages.scrollHeight;
        } else if (event.type === "action_result") {
          if (event.generation) {
            appendLog([
              `\n[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 触发生成：${event.generation.ok ? "成功" : "失败"}`,
              `耗时：${event.generation.durationMs} ms`,
              event.generation.stdout ? `输出文件：\n${event.generation.stdout}` : "",
              event.generation.stderr ? `错误信息：\n${event.generation.stderr}` : "",
            ].join("\n"));
          }
          if (event.crawl) {
            appendLog([
              `\n[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 触发爬取：${event.crawl.ok ? "成功" : "失败"}`,
              `耗时：${event.crawl.durationMs} ms`,
              event.crawl.stdout ? `执行输出：\n${event.crawl.stdout}` : "",
              event.crawl.stderr ? `错误信息：\n${event.crawl.stderr}` : "",
            ].join("\n"));
          }
        }
      }
      if (isDone) break;
    }
    if (!answer.trim()) setMessageContent(assistantNode, "操作完成。", true);
    else {
      let finalAnswer = answer;
      const sugMatch = finalAnswer.match(/<suggestions>\s*([\s\S]*?)\s*<\/suggestions>/i);
      let suggestionsHTML = "";
      if (sugMatch) {
        try {
          let jsonStr = sugMatch[1].trim();
          jsonStr = jsonStr.replace(/^```json/i, "").replace(/^```/i, "").replace(/```$/i, "").trim();
          const arr = JSON.parse(jsonStr);
          finalAnswer = finalAnswer.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
          if (arr && arr.length > 0) {
            suggestionsHTML = `<div class="suggestion-chips">` + arr.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${q}</button>`).join('') + `</div>`;
          }
        } catch (e) {
            console.error("Suggestion parse error final:", e, sugMatch[1]);
        }
      }
      finalAnswer = finalAnswer.replace(/<suggestions>[\s\S]*$/i, "");
      setMessageContent(assistantNode, finalAnswer, true);
      if (suggestionsHTML) {
        const b = assistantNode.querySelector(".message-text") || assistantNode.querySelector(".markdown-body");
        b.insertAdjacentHTML("beforeend", suggestionsHTML);
      } else {
        // Fallback: AI didn't output suggestions, generate defaults based on the user message
        const fallback = generateFallbackSuggestions(message);
        const fallbackHTML = `<div class="suggestion-chips">` + fallback.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${q}</button>`).join('') + `</div>`;
        const b = assistantNode.querySelector(".message-text") || assistantNode.querySelector(".markdown-body");
        b.insertAdjacentHTML("beforeend", fallbackHTML);
      }
    }
    await fetchStatus();
  } catch (error) {
    addMessage("assistant", `处理失败：${error.message}`);
  } finally {
    setChatBusy(false);
    els.chatInput.focus();
  }
}

els.generateButtons.forEach((button) => {
  button.addEventListener("click", () => generateReport("页面按钮"));
});

if (els.generatePerformanceButton) {
  els.generatePerformanceButton.addEventListener("click", () => generateCarrierPerformanceReport("页面按钮"));
}

els.crawlButtons.forEach((button) => {
  button.addEventListener("click", () => runCrawl("页面按钮"));
});

els.refreshButton.addEventListener("click", () => {
  fetchStatus().catch((error) => {
    appendLog(`刷新失败：${error.message}`);
  });
});

els.aiSettingsButton.addEventListener("click", () => {
  els.aiSettingsModal.hidden = false;
  loadAiConfig().catch((error) => {
    els.aiConfigStatus.textContent = error.message;
  });
});

els.closeAiSettings.addEventListener("click", () => {
  els.aiSettingsModal.hidden = true;
});

els.aiSettingsModal.addEventListener("click", (event) => {
  if (event.target === els.aiSettingsModal) els.aiSettingsModal.hidden = true;
});

els.aiSettingsForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveAiConfig()
    .then(() => {
      els.aiConfigStatus.textContent = "AI 设置已保存。";
    })
    .catch((error) => {
      els.aiConfigStatus.textContent = error.message;
    });
});

els.fileEditForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveFileEdit().catch((error) => {
    els.fileEditStatus.textContent = error.message;
  });
});

els.closeFileEdit.addEventListener("click", closeFileEditor);
els.cancelFileEdit.addEventListener("click", closeFileEditor);
els.fileEditModal.addEventListener("click", (event) => {
  if (event.target === els.fileEditModal) closeFileEditor();
});

els.multiSelectTriggers.forEach((button) => {
  button.addEventListener("click", () => {
    state.multiSelect = !state.multiSelect;
    if (!state.multiSelect) state.selectedFiles.clear();
    renderFileList();
  });
});

els.deleteSelectedTriggers.forEach((button) => {
  button.addEventListener("click", () => {
    deleteFiles(Array.from(state.selectedFiles));
  });
});

els.outputTabs.forEach((button) => {
  button.addEventListener("click", () => {
    const reportType = button.dataset.scrollReport;
    
    els.outputTabs.forEach((item) => {
      item.classList.toggle("is-active", item.dataset.scrollReport === reportType);
    });
    
    if (reportType === "performance") {
      els.weeklyOutputBlock.hidden = true;
      els.performanceOutputBlock.hidden = false;
    } else {
      els.weeklyOutputBlock.hidden = false;
      els.performanceOutputBlock.hidden = true;
    }
  });
});

els.testAiConfig.addEventListener("click", () => {
  saveAiConfig()
    .then(testAiConfig)
    .catch((error) => {
      els.aiConfigStatus.textContent = error.message;
    });
});

els.clearLogButton.addEventListener("click", () => {
  state.agentTraceLoaded = false;
  setLog("执行日志已清空。");
});

els.logButton.addEventListener("click", () => {
  els.logModal.hidden = false;
  loadLatestAgentTrace();
  setTimeout(() => els.logBox.scrollTop = els.logBox.scrollHeight, 10);
});

if (els.closeLogButton) els.closeLogButton.addEventListener("click", () => { els.logModal.hidden = true; });
if (els.logModal) els.logModal.addEventListener("click", (e) => { if (e.target === els.logModal) els.logModal.hidden = true; });

// Dashboard Modal
if (els.dashboardBtn) els.dashboardBtn.addEventListener("click", openDashboard);
if (els.closeDashboardBtn) els.closeDashboardBtn.addEventListener("click", () => { els.dashboardModal.hidden = true; });
if (els.dashboardModal) els.dashboardModal.addEventListener("click", (e) => { if (e.target === els.dashboardModal) els.dashboardModal.hidden = true; });

// Dashboard Logic
// Dashboard Logic
async function openDashboard() {
  if (els.dashboardModal) els.dashboardModal.hidden = false;
  const container = document.getElementById("dashboardCardGrid");
  if (container) {
    container.className = "dashboard-table-container";
    container.innerHTML = `
      <div class="dashboard-loading">
        <div class="spinner"></div>
        <p>正在生成飞书表格中...</p>
      </div>
    `;
  }
  try {
    const response = await fetch("/api/dashboard");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "获取看板数据失败");
    
    if (data.url) {
      if (container) {
        container.innerHTML = `
          <div class="dashboard-loading" style="text-align: center; padding: 40px;">
            <p style="color: #10b981; font-weight: bold; font-size: 16px; margin-bottom: 16px;">✅ 飞书表格子表已成功生成！</p>
            <a href="${data.url}" target="_blank" style="display: inline-block; padding: 10px 20px; background: #2563eb; color: white; text-decoration: none; border-radius: 6px; font-weight: 500;">点击跳转到飞书查看</a>
          </div>
        `;
      }
    }
  } catch (err) {
    console.error(err);
    if (container) {
      container.innerHTML = "<p style='text-align:center;color:#ef4444;padding:40px 0;'>生成飞书表格失败</p>";
    } else {
      alert("加载看板数据失败");
    }
  }
}

// Global UI handling
els.chatFab.addEventListener("click", () => {
  els.chatModal.hidden = false;
  setTimeout(() => els.chatInput.focus(), 0);
});

window.clickSuggestion = function(text) {
  if (state.chatBusy) return;
  els.chatInput.value = text;
  resizeChatInput();
  els.chatForm.requestSubmit();
};

els.closeChatButton.addEventListener("click", () => {
  els.chatModal.hidden = true;
});

els.chatModal.addEventListener("click", (event) => {
  if (event.target === els.chatModal) els.chatModal.hidden = true;
});

els.clearChatButton.addEventListener("click", () => {
  els.messages.innerHTML = `
    <div class="message assistant">
      <span class="avatar">AI</span>
      <div class="message-body">
        <div class="message-text">您好！我是一个不仅能分析信息，还能主动执行任务的 AI 智能体 (Agent)。我可以帮您：<br>1. <b>深度查阅</b>：运用 RAG 随时翻阅底层爬取数据、历史周报与审计日志。<br>2. <b>精准抓取</b>：一键触发定向爬虫，自动去前线获取最新情报。<br>3. <b>飞书互通</b>：通过指令直连飞书，无缝同步与更新云端表格记录。<br>请问今天有什么我可以帮您的？</div>
      </div>
    </div>
  `;
});

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message || state.chatBusy) return;
  els.chatInput.value = "";
  resizeChatInput();
  sendChat(message);
});

els.chatInput.addEventListener("input", resizeChatInput);

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  if (state.chatBusy) return;
  els.chatForm.requestSubmit();
});

setClock();
setInterval(setClock, 30000);
fetchStatus().catch((error) => {
  setLog(`初始化失败：${error.message}`);
});
setInterval(() => fetchStatus().catch(console.error), 10000);
