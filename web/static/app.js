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
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  statusSummary: document.querySelector("#statusSummary"),
  fileList: document.getElementById("fileList"),
  fileCountText: document.querySelector("#fileCountText"),
  multiSelectButton: document.querySelector("#multiSelectButton"),
  deleteSelectedButton: document.querySelector("#deleteSelectedButton"),
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
  crawlButtons: [
    document.querySelector("#crawlButton"),
    document.querySelector("#crawlButtonSecondary"),
  ].filter(Boolean),
  refreshButton: document.querySelector("#refreshButton"),
  logButton: document.querySelector("#logButton"),
  logModal: document.querySelector("#logModal"),
  closeLogButton: document.querySelector("#closeLogButton"),
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

function setBusy(value, label = "运行中") {
  state.busy = value;
  els.generateButtons.forEach((button) => {
    button.disabled = value;
    button.textContent = value ? "生成中..." : "生成周报";
  });
  els.crawlButtons.forEach((button) => {
    button.disabled = value;
    button.textContent = value ? "爬取中..." : "重新爬取";
  });
  els.refreshButton.disabled = value;
  if (els.aiSettingsButton) els.aiSettingsButton.disabled = value;
  els.runState.textContent = value ? label : "准备就绪";
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
  let desc = file.note ? escapeHtml(file.note) : "正式 Word 周报";
  
  if (file.is_archive) {
    desc = `<span class="archive-label">历史归档 ${file.archive_batch}</span> ` + desc;
  }
  return desc;
}

function filteredOutputs() {
  return [...state.outputs].sort((a, b) => b.mtime - a.mtime);
}

function labelSourceType(value) {
  const labels = {
    company_official: "企业官网",
    regulator_official: "监管机构",
    media: "媒体资讯",
    public_database: "公开数据库",
    stock_exchange: "交易所",
    unknown: "未分类",
  };
  return labels[value] || value.replaceAll("_", " ");
}

function sumValues(items = []) {
  return items.reduce((total, item) => total + Number(item.value || 0), 0);
}

function renderMiniBars(container, items, options = {}) {
  if (!container) return;
  const list = Array.isArray(items) ? items.filter((item) => item.value > 0) : [];
  if (!list.length) {
    container.innerHTML = `<div class="chart-empty">暂无可视化数据</div>`;
    return;
  }
  const total = sumValues(list);
  const max = Math.max(...list.map((item) => item.value), 1);
  container.innerHTML = list.slice(0, options.limit || 5).map((item, index) => {
    const width = Math.max(8, Math.round((item.value / max) * 100));
    const share = total ? Math.round((item.value / total) * 100) : 0;
    const label = options.formatLabel ? options.formatLabel(item.label) : item.label;
    return `
      <button type="button" class="mini-bar" data-filter="${escapeHtml(item.label)}" style="--bar:${width};--i:${index}">
        <div class="mini-bar-top">
          <span>${escapeHtml(label)}</span>
          <strong>${item.value}<small>${share}%</small></strong>
        </div>
        <div class="mini-bar-track"><i></i></div>
      </button>
    `;
  }).join("");
  container.querySelectorAll(".mini-bar").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeInsight = button.dataset.filter || "all";
      container.querySelectorAll(".mini-bar").forEach((item) => item.classList.toggle("is-active", item === button));
      appendLog(`\n[看板筛选] 当前关注：${button.dataset.filter || "全部"}\n`);
    });
  });
}

function renderSourceMap(visuals) {
  if (!els.sourceChart) return;
  const sourceTypes = visuals.sourceTypes || [];
  const jurisdictions = visuals.jurisdictions || [];
  const methods = visuals.methods || [];
  const total = sumValues(sourceTypes);
  els.sourceTotal.textContent = total ? `${total} 条` : "--";
  const chips = [
    ...sourceTypes.slice(0, 3).map((item) => ({ ...item, label: labelSourceType(item.label), type: "来源" })),
    ...jurisdictions.slice(0, 3).map((item) => ({ ...item, type: "地域" })),
    ...methods.slice(0, 2).map((item) => ({ ...item, type: "方式" })),
  ];
  if (!chips.length) {
    els.sourceChart.innerHTML = `<div class="chart-empty">暂无来源画像</div>`;
    return;
  }
  const max = Math.max(...chips.map((item) => item.value), 1);
  els.sourceChart.innerHTML = chips.map((item, index) => {
    const width = Math.max(12, Math.round((item.value / max) * 100));
    return `
      <button type="button" class="source-pill" data-label="${escapeHtml(item.label)}" style="--bar:${width};--i:${index}">
        <span>${escapeHtml(item.type)}</span>
        <strong>${escapeHtml(item.label)}</strong>
        <em>${item.value}</em>
        <i></i>
      </button>
    `;
  }).join("");
  els.sourceChart.querySelectorAll(".source-pill").forEach((button) => {
    button.addEventListener("click", () => {
      els.sourceChart.querySelectorAll(".source-pill").forEach((item) => item.classList.toggle("is-active", item === button));
      appendLog(`\n[来源画像] ${button.dataset.label || "来源"}\n`);
    });
  });
}

function renderInsights(status) {
  const visuals = status.visuals || {};
  const quality = visuals.quality || {};
  const totalRows = Number(status.results?.count || 0);
  const ok = Number(quality.ok || 0);
  const partial = Number(quality.partial || 0);
  const failed = Number(quality.failed || 0);
  const score = totalRows ? Math.round(((ok + partial * 0.55) / totalRows) * 100) : 0;
  if (els.qualityRing) els.qualityRing.style.setProperty("--score", score);
  if (els.qualityScore) els.qualityScore.textContent = totalRows ? `${score}%` : "--%";
  if (els.qualityCenter) els.qualityCenter.textContent = totalRows ? `${ok}/${totalRows}` : "--";
  if (els.qualityLegend) {
    els.qualityLegend.innerHTML = `
      <span><i class="ok"></i>完整 ${ok}</span>
      <span><i class="partial"></i>部分 ${partial}</span>
      <span><i class="failed"></i>异常 ${failed}</span>
    `;
  }
  if (els.blockTotal) els.blockTotal.textContent = `${sumValues(visuals.blocks || []) || 0} 行`;
  renderMiniBars(els.blockChart, visuals.blocks || [], { limit: 5 });
  renderSourceMap(visuals);
}

function renderFileList() {
  const files = filteredOutputs();
  const selectedCount = state.selectedFiles.size;
  els.fileCountText.textContent = state.multiSelect ? `选择模式 · 已选 ${selectedCount} / ${files.length}` : `${files.length} 个文件`;
  if (els.multiSelectButton) {
    els.multiSelectButton.classList.toggle("is-active", state.multiSelect);
  }
  if (els.deleteSelectedButton) {
    els.deleteSelectedButton.hidden = !state.multiSelect;
    els.deleteSelectedButton.disabled = selectedCount === 0;
  }
  const selectColumn = state.multiSelect ? "<span></span>" : "";
  if (!state.outputs.length) {
    els.fileList.innerHTML = `
      <div class="file-header">
        ${selectColumn}<span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
      </div>
      <div class="file-row">
        ${selectColumn}<strong>暂无周报</strong><span>请先生成 Word 周报</span><span>-</span><span>-</span>
      </div>
    `;
    return;
  }
  if (!files.length) {
    els.fileList.innerHTML = `
      <div class="file-header">
        ${selectColumn}<span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
      </div>
      <div class="file-row">
        ${selectColumn}<strong>无周报文件</strong><span>请重新生成</span><span>-</span><span>-</span>
      </div>
    `;
    return;
  }

  let html = `
    <div class="file-header ${state.multiSelect ? "with-select" : ""}">
      ${selectColumn}<span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
    </div>
  `;
  files.forEach((file) => {
    const type = fileType(file.name);
    const safePath = escapeHtml(file.path_str);
    const checked = state.selectedFiles.has(file.path_str) ? "checked" : "";
    const audioAction = file.audio && file.audio.exists
      ? `<button type="button" class="row-icon-button audio-play-button" data-audio="${escapeHtml(file.audio.url)}" title="播放音频摘要" aria-label="播放音频摘要">${iconSvg("volume")}</button>`
      : `<button type="button" class="row-icon-button generate-audio-button" data-path="${safePath}" title="生成音频摘要" aria-label="生成音频摘要">${iconSvg("waveform")}</button>`;
    html += `
      <div class="file-row ${type.className} ${state.multiSelect ? "with-select" : ""} ${checked ? "is-selected" : ""}" data-path="${safePath}">
        ${state.multiSelect ? `<span class="select-cell"><input type="checkbox" class="file-checkbox" data-path="${safePath}" ${checked} aria-label="选择 ${escapeHtml(file.name)}"></span>` : ""}
        <span class="file-name-cell" title="${file.name}">${type.icon} ${file.name}</span>
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
  els.fileList.innerHTML = html;
  els.fileList.querySelectorAll(".edit-file-button").forEach((button) => {
    button.addEventListener("click", () => openFileEditor(button.dataset.path));
  });
  els.fileList.querySelectorAll(".delete-file-button").forEach((button) => {
    button.addEventListener("click", () => deleteFiles([button.dataset.path]));
  });
  els.fileList.querySelectorAll(".generate-audio-button").forEach((button) => {
    button.addEventListener("click", () => generateAudio(button.dataset.path, button));
  });
  els.fileList.querySelectorAll(".audio-play-button").forEach((button) => {
    button.addEventListener("click", () => playAudio(button.dataset.audio, button));
  });
  els.fileList.querySelectorAll(".file-checkbox").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedFiles.add(checkbox.dataset.path);
      else state.selectedFiles.delete(checkbox.dataset.path);
      renderFileList();
    });
  });
  els.fileList.querySelectorAll(".file-row.with-select").forEach((row) => {
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

function setLog(text) {
  els.logBox.innerHTML = "";
  els.logBox.appendChild(document.createTextNode(text));
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", text);
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

function playAudio(url, button = null) {
  if (!url) return;
  if (state.currentAudio && state.currentAudio.src.includes(url) && !state.currentAudio.paused) {
    state.currentAudio.pause();
    if (state.currentAudioButton) state.currentAudioButton.classList.remove("is-playing");
    return;
  }
  if (state.currentAudio) {
    state.currentAudio.pause();
    if (state.currentAudioButton) state.currentAudioButton.classList.remove("is-playing");
  }
  state.currentAudio = new Audio(url);
  state.currentAudioButton = button;
  if (button) button.classList.add("is-playing");
  state.currentAudio.addEventListener("ended", () => {
    if (button) button.classList.remove("is-playing");
  });
  state.currentAudio.play().catch((error) => {
    if (button) button.classList.remove("is-playing");
    appendLog(`音频播放失败：${error.message}\n`);
  });
}

async function runCrawl(source = "按钮") {
  setBusy(true, "正在重新爬取");
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
  setBusy(true, "正在生成");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成周报，请稍候...\n`);
  try {
    const response = await fetch("/api/generate", { method: "POST" });
    const data = await response.json();
    renderStatus(data.status);
    appendLog([
      `\n[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 生成完成：${data.ok ? "成功" : "失败"}`,
      `耗时：${data.durationMs} ms`,
      data.audio ? `音频摘要：${data.audio.ok ? `已生成（${data.audio.backend || "cached"}）` : `失败：${data.audio.error || "未知错误"}`}` : "",
      data.stdout ? `输出文件：\n${data.stdout}` : "",
      data.stderr ? `错误信息：\n${data.stderr}` : "",
    ]
      .filter(Boolean)
      .join("\n"));
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

els.multiSelectButton.addEventListener("click", () => {
  state.multiSelect = !state.multiSelect;
  if (!state.multiSelect) state.selectedFiles.clear();
  renderFileList();
});

els.deleteSelectedButton.addEventListener("click", () => {
  deleteFiles(Array.from(state.selectedFiles));
});

els.testAiConfig.addEventListener("click", () => {
  saveAiConfig()
    .then(testAiConfig)
    .catch((error) => {
      els.aiConfigStatus.textContent = error.message;
    });
});

els.clearLogButton.addEventListener("click", () => {
  setLog("执行日志已清空。");
});

els.logButton.addEventListener("click", () => {
  els.logModal.hidden = false;
  setTimeout(() => els.logBox.scrollTop = els.logBox.scrollHeight, 10);
});

els.closeLogButton.addEventListener("click", () => {
  els.logModal.hidden = true;
});

els.logModal.addEventListener("click", (event) => {
  if (event.target === els.logModal) els.logModal.hidden = true;
});

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
