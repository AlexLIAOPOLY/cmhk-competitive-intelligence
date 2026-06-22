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
  webSearchEnabled: false,
  thinkingEnabled: false,
  agentSkills: [],
  selectedSkillIds: new Set(),
  expandedSkillIds: new Set(),
  skillSelectionTouched: false,
  agentDatasets: [],
  selectedDatasetIds: new Set(),
  expandedDatasetIds: new Set(),
  datasetSelectionTouched: false,
  knowledgeUploadBusy: false,
  pendingConfirmedActions: new Set(),
  chatHistory: [],
  chatThreads: [],
  activeThreadId: null,
  chatQueue: [],
  chatThreadSearch: "",
  agentContextKey: "",
  loadedSkillIds: new Set(),
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
  agentMemoryList: document.querySelector("#agentMemoryList"),
  refreshAgentMemory: document.querySelector("#refreshAgentMemory"),
  clearLogButton: document.querySelector("#clearLogButton"),
  clearChatButton: document.querySelector("#clearChatButton"),
  toggleChatThreadsButton: document.querySelector("#toggleChatThreadsButton"),
  collapseChatThreadsButton: document.querySelector("#collapseChatThreadsButton"),
  newChatThreadButton: document.querySelector("#newChatThreadButton"),
  chatWorkspace: document.querySelector("#chatWorkspace"),
  chatThreadSidebar: document.querySelector("#chatThreadSidebar"),
  chatThreadSearchInput: document.querySelector("#chatThreadSearchInput"),
  chatThreadList: document.querySelector("#chatThreadList"),
  chatQueueList: document.querySelector("#chatQueueList"),
  chatFab: document.querySelector("#chatFab"),
  chatModal: document.querySelector("#chatModal"),
  closeChatButton: document.querySelector("#closeChatButton"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  skillToggle: document.querySelector("#skillToggle"),
  skillMenu: document.querySelector("#skillMenu"),
  databaseToggle: document.querySelector("#databaseToggle"),
  databaseMenu: document.querySelector("#databaseMenu"),
  knowledgeUploadButton: document.querySelector("#knowledgeUploadButton"),
  knowledgeUploadInput: document.querySelector("#knowledgeUploadInput"),
  thinkingToggle: document.querySelector("#thinkingToggle"),
  webSearchToggle: document.querySelector("#webSearchToggle"),
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
  els.chatSubmitButton.disabled = false;
  els.chatInput.disabled = false;
  if (els.webSearchToggle) els.webSearchToggle.disabled = false;
  if (els.thinkingToggle) els.thinkingToggle.disabled = false;
  if (els.skillToggle) els.skillToggle.disabled = false;
  if (els.databaseToggle) els.databaseToggle.disabled = false;
  if (els.knowledgeUploadButton) els.knowledgeUploadButton.disabled = value || state.knowledgeUploadBusy;
  els.chatSubmitButton.textContent = value ? "排队" : "发送";
}

function renderWebSearchToggle() {
  const button = els.webSearchToggle;
  if (!button) return;
  button.classList.toggle("is-active", state.webSearchEnabled);
  button.setAttribute("aria-pressed", state.webSearchEnabled ? "true" : "false");
  button.title = state.webSearchEnabled ? "本轮使用网页来源" : "本轮只用本地来源";
  const label = button.querySelector("span");
  if (label) label.textContent = "联网搜索";
}

function renderThinkingToggle() {
  const button = els.thinkingToggle;
  if (!button) return;
  button.classList.toggle("is-active", state.thinkingEnabled);
  button.setAttribute("aria-pressed", state.thinkingEnabled ? "true" : "false");
  button.title = state.thinkingEnabled
    ? "深度思考已开启：使用 reasoning 模型；显示可审计思考轨迹，不展示原始思维链"
    : "打开深度思考";
  const label = button.querySelector("span");
  if (label) label.textContent = state.thinkingEnabled ? "深思" : "思考";
}

function renderSkillToggle() {
  const button = els.skillToggle;
  if (!button) return;
  const count = state.selectedSkillIds.size;
  button.classList.toggle("is-active", count > 0);
  button.setAttribute("aria-pressed", count > 0 ? "true" : "false");
  button.setAttribute("aria-expanded", els.skillMenu && !els.skillMenu.hidden ? "true" : "false");
  const label = button.querySelector("span");
  if (label) label.textContent = count ? `能力 ${count}` : "能力";
  const selectedTitles = state.agentSkills
    .filter((skill) => state.selectedSkillIds.has(skill.id))
    .map((skill) => skill.title);
  button.title = selectedTitles.length ? `已载入 Agent Skill: ${selectedTitles.join("、")}` : "选择 Agent Skill";
}

function renderSkillMenu() {
  const menu = els.skillMenu;
  if (!menu) return;
  if (!state.agentSkills.length) {
    menu.innerHTML = `<div class="skill-menu-empty">暂无可用 Agent Skill</div>`;
    renderSkillToggle();
    return;
  }
  const items = state.agentSkills.map((skill) => {
    const active = state.selectedSkillIds.has(skill.id);
    const expanded = state.expandedSkillIds.has(skill.id);
    const tags = Array.isArray(skill.tags) ? skill.tags : [];
    const description = skill.description || skill.summary || skill.path || "";
    const detailRows = [
      description ? `<p class="option-detail-text">${escapeHtml(description)}</p>` : "",
      skill.data ? `<p class="option-detail-row"><b>数据</b><span>${escapeHtml(skill.data)}</span></p>` : "",
      skill.path ? `<p class="option-detail-row"><b>路径</b><span>${escapeHtml(skill.path)}</span></p>` : "",
    ].filter(Boolean).join("");
    return `
      <button class="skill-option ${active ? "is-active" : ""}" type="button" data-skill-id="${escapeHtml(skill.id)}">
        <span class="skill-option-check">${active ? "✓" : ""}</span>
        <span class="skill-option-main">
          <span class="skill-option-top">
            <strong>${escapeHtml(skill.title)}</strong>
            <em>${active ? "已选" : "可选"}</em>
          </span>
          <small>${escapeHtml(description)}</small>
          ${tags.length ? `<span class="skill-tags">${tags.slice(0, 4).map((tag) => `<b>${escapeHtml(tag)}</b>`).join("")}</span>` : ""}
          ${expanded && detailRows ? `<span class="option-detail">${detailRows}</span>` : ""}
        </span>
        <span class="option-expand" data-expand-kind="skill" title="${expanded ? "收起完整描述" : "展开完整描述"}">${expanded ? "▴" : "▾"}</span>
      </button>
    `;
  }).join("");
  menu.innerHTML = items || `<div class="skill-menu-empty">暂无可用能力</div>`;
  renderSkillToggle();
}

function renderDatabaseToggle() {
  const button = els.databaseToggle;
  if (!button) return;
  const count = state.selectedDatasetIds.size;
  button.classList.toggle("is-active", count > 0);
  button.setAttribute("aria-pressed", count > 0 ? "true" : "false");
  button.setAttribute("aria-expanded", els.databaseMenu && !els.databaseMenu.hidden ? "true" : "false");
  const label = button.querySelector("span");
  if (label) label.textContent = count ? `数据库 ${count}` : "数据库";
  const selectedTitles = state.agentDatasets
    .filter((dataset) => state.selectedDatasetIds.has(dataset.id))
    .map((dataset) => dataset.title || dataset.id);
  button.title = selectedTitles.length ? `已选择数据库: ${selectedTitles.join("、")}` : "选择发送给 AI 的数据库";
}

function renderDatabaseMenu() {
  const menu = els.databaseMenu;
  if (!menu) return;
  const uploadAction = `
    <button class="database-upload-action ${state.knowledgeUploadBusy ? "is-loading" : ""}" id="knowledgeUploadButton" type="button" ${state.chatBusy || state.knowledgeUploadBusy ? "disabled" : ""}>
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M12 3v12"></path>
        <path d="m7 8 5-5 5 5"></path>
        <path d="M5 21h14"></path>
        <path d="M6 17h12"></path>
      </svg>
      <span>
        <strong>上传文件作为知识库</strong>
        <small>支持 txt、md、csv、tsv、json、docx、pdf；上传后自动选中</small>
      </span>
    </button>
  `;
  const items = state.agentDatasets.map((dataset) => {
    const active = state.selectedDatasetIds.has(dataset.id);
    const expanded = state.expandedDatasetIds.has(dataset.id);
    const tags = Array.isArray(dataset.tags) ? dataset.tags : [];
    const fileCount = Array.isArray(dataset.files) ? dataset.files.length : 0;
    const summary = dataset.summary || dataset.scope || dataset.folder || "";
    const detailRows = [
      summary ? `<p class="option-detail-text">${escapeHtml(summary)}</p>` : "",
      dataset.scope ? `<p class="option-detail-row"><b>范围</b><span>${escapeHtml(dataset.scope)}</span></p>` : "",
      dataset.id ? `<p class="option-detail-row"><b>ID</b><span>${escapeHtml(dataset.id)}</span></p>` : "",
      dataset.folder ? `<p class="option-detail-row"><b>路径</b><span>${escapeHtml(dataset.folder)}</span></p>` : "",
      `<p class="option-detail-row"><b>文件</b><span>${fileCount} 个</span></p>`,
    ].filter(Boolean).join("");
    return `
      <button class="database-option ${active ? "is-active" : ""}" type="button" data-dataset-id="${escapeHtml(dataset.id)}">
        <span class="database-option-check">${active ? "✓" : ""}</span>
        <span class="database-option-main">
          <span class="database-option-top">
            <strong>${escapeHtml(dataset.title || dataset.id)}</strong>
          </span>
          <small>${escapeHtml(summary)}</small>
          ${tags.length ? `<span class="database-tags">${tags.slice(0, 4).map((tag) => `<b>${escapeHtml(tag)}</b>`).join("")}</span>` : ""}
          <span class="database-data">${escapeHtml(dataset.id)} · ${fileCount} 个文件</span>
          ${expanded && detailRows ? `<span class="option-detail">${detailRows}</span>` : ""}
        </span>
        <span class="option-expand" data-expand-kind="dataset" title="${expanded ? "收起完整描述" : "展开完整描述"}">${expanded ? "▴" : "▾"}</span>
      </button>
    `;
  }).join("");
  menu.innerHTML = uploadAction + (items || `<div class="database-menu-empty">暂无可用数据库</div>`);
  renderDatabaseToggle();
}

async function loadAgentDatasets() {
  try {
    const response = await fetch("/api/agent-datasets");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "加载数据库失败");
    state.agentDatasets = Array.isArray(data.datasets) ? data.datasets : [];
    if (!state.datasetSelectionTouched) {
      state.selectedDatasetIds = new Set(state.agentDatasets.map((dataset) => dataset.id).filter(Boolean));
    }
    renderDatabaseMenu();
  } catch (error) {
    state.agentDatasets = [];
    if (els.databaseMenu) {
      els.databaseMenu.innerHTML = `<div class="database-menu-empty">${escapeHtml(error.message)}</div>`;
    }
    renderDatabaseToggle();
  }
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = String(reader.result || "");
      resolve(result.includes(",") ? result.split(",", 2)[1] : result);
    };
    reader.onerror = () => reject(reader.error || new Error("读取文件失败"));
    reader.readAsDataURL(file);
  });
}

async function uploadKnowledgeFile(file) {
  if (!file || state.knowledgeUploadBusy) return;
  const maxBytes = 8 * 1024 * 1024;
  if (file.size > maxBytes) {
    addMessage("assistant", "文件过大，当前单文件上限为 8MB。");
    return;
  }
  state.knowledgeUploadBusy = true;
  renderDatabaseMenu();
  try {
    const contentBase64 = await fileToBase64(file);
    const response = await fetch("/api/agent-datasets/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: file.name,
        contentType: file.type || "",
        size: file.size,
        contentBase64,
      }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "上传失败");
    state.agentDatasets = Array.isArray(data.datasets) ? data.datasets : state.agentDatasets;
    const datasetId = data.dataset && data.dataset.id;
    if (datasetId) {
      state.selectedDatasetIds.add(datasetId);
      state.datasetSelectionTouched = true;
    }
    renderDatabaseMenu();
    addMessage("assistant", `已上传「${file.name}」并作为本轮已选择数据库，可直接向小竞AI提问。`);
  } catch (error) {
    addMessage("assistant", `上传知识库失败：${error.message || String(error)}`);
  } finally {
    state.knowledgeUploadBusy = false;
    renderDatabaseMenu();
    if (els.knowledgeUploadInput) els.knowledgeUploadInput.value = "";
  }
}

async function loadAgentSkills() {
  try {
    const response = await fetch("/api/agent-skills");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "加载 Agent Skill 失败");
    state.agentSkills = Array.isArray(data.skills) ? data.skills : [];
    if (!state.skillSelectionTouched && state.selectedSkillIds.size === 0) {
      state.agentSkills.forEach((skill) => {
        if (skill && skill.id) state.selectedSkillIds.add(skill.id);
      });
    }
    renderSkillMenu();
  } catch (error) {
    state.agentSkills = [];
    if (els.skillMenu) {
      els.skillMenu.innerHTML = `<div class="skill-menu-empty">${escapeHtml(error.message)}</div>`;
    }
    renderSkillToggle();
  }
}

async function loadAgentMemory() {
  if (!els.agentMemoryList) return;
  els.agentMemoryList.textContent = "加载中...";
  try {
    const response = await fetch("/api/agent-memory?limit=50");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "读取记忆失败");
    const memories = Array.isArray(data.memories) ? data.memories : [];
    if (!memories.length) {
      els.agentMemoryList.innerHTML = `<div class="agent-memory-empty">暂无长期记忆</div>`;
      return;
    }
    els.agentMemoryList.innerHTML = memories.map((item) => `
      <article class="agent-memory-item" data-memory-id="${escapeHtml(item.id || "")}">
        <div>
          <strong>${escapeHtml(item.content || "")}</strong>
          <small>${escapeHtml(item.created_date || "")}${item.tags && item.tags.length ? ` · ${escapeHtml(item.tags.join("、"))}` : ""}</small>
        </div>
        <button type="button" class="quiet-button small" data-delete-memory="${escapeHtml(item.id || "")}">删除</button>
      </article>
    `).join("");
  } catch (error) {
    els.agentMemoryList.textContent = error.message || String(error);
  }
}

async function deleteAgentMemory(memoryId) {
  if (!memoryId) return;
  const response = await fetch("/api/agent-memory/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id: memoryId }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "删除失败");
  await loadAgentMemory();
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
    download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 0 20"/><path d="M12 2a15.3 15.3 0 0 0 0 20"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
    fileSearch: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h7"/><path d="M14 2v6h6"/><circle cx="16" cy="16" r="3"/><path d="M21 21l-2.8-2.8"/>',
    fileText: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M8 13h8"/><path d="M8 17h6"/>',
    database: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    chartLine: '<path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-7"/><path d="M18 7h1v1"/>',
    table: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M9 4v16"/><path d="M15 4v16"/>',
    crawler: '<rect x="5" y="8" width="14" height="10" rx="3"/><path d="M12 8V4"/><path d="M8 13h.01"/><path d="M16 13h.01"/><path d="M9 18l-2 3"/><path d="M15 18l2 3"/>',
    terminal: '<path d="M4 17l6-6-6-6"/><path d="M12 19h8"/>',
    status: '<path d="M12 2v4"/><path d="M12 18v4"/><path d="M4.93 4.93l2.83 2.83"/><path d="M16.24 16.24l2.83 2.83"/><path d="M2 12h4"/><path d="M18 12h4"/><path d="M4.93 19.07l2.83-2.83"/><path d="M16.24 7.76l2.83-2.83"/>',
  };
  return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
}

function toolIconName(toolName) {
  const name = String(toolName || "").toLowerCase();
  if (name.includes("agent_skills")) return "terminal";
  if (name.includes("read_agent_skill")) return "terminal";
  if (name.includes("agent_databases")) return "database";
  if (name.includes("web_search") || name.includes("read_webpage")) return "globe";
  if (name.includes("search_local_reports")) return "fileSearch";
  if (name.includes("read_local_reference")) return "fileText";
  if (name.includes("list_local_datasets") || name.includes("list_crawl_runs")) return "database";
  if (name.includes("render_python_chart")) return "chartLine";
  if (name.includes("feishu")) return "table";
  if (name.includes("crawl") || name.includes("recrawl")) return "crawler";
  if (name.includes("system_status")) return "status";
  if (name.includes("cli") || name.includes("trigger_")) return "terminal";
  return "search";
}

function toolFriendlyName(toolName) {
  const name = String(toolName || "");
  const labels = {
    list_local_datasets: "读取数据库列表",
    search_local_reports: "读取数据库摘要",
    read_local_reference: "读取数据库原文",
    web_search: "联网搜索",
    read_webpage: "读取网页",
    trigger_crawl: "触发爬虫",
    list_crawl_runs: "爬虫日志",
    feishu_cli: "飞书表格",
    trigger_report_generation: "生成报告",
    render_python_chart: "生成图表",
    get_system_status: "系统状态",
    load_agent_skills: "载入 Agent Skill",
    read_agent_skill: "读取 Agent Skill",
    select_agent_databases: "确认数据库选择",
  };
  return labels[name] || name || "工具";
}

function toolNarrationText(toolName) {
  const name = String(toolName || "");
  const labels = {
    load_agent_skills: "我先载入本轮需要的 Agent Skill。",
    read_agent_skill: "我读取相关 Agent Skill 的完整指令。",
    select_agent_databases: "我确认本轮数据库选择。",
    list_local_datasets: "我读取本轮已选数据库列表。",
    search_local_reports: "我读取已选数据库并检索摘要片段。",
    read_local_reference: "我读取命中的数据库原文。",
    web_search: "我同步联网检索公开来源。",
    read_webpage: "我打开关键网页核对原文。",
    render_python_chart: "我把核验后的数据生成图表。",
    get_system_status: "我先读取系统当前状态。",
    list_report_outputs: "我先查看已有报告输出。",
    list_crawl_runs: "我先读取爬虫运行日志。",
    trigger_crawl: "我开始触发爬虫任务。",
    trigger_report_generation: "我开始触发报告生成。",
    forecast_quarterly_metric: "我调用趋势预测工具生成预测结果。",
  };
  return labels[name] || `我调用 ${toolFriendlyName(name)} 工具。`;
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
if (typeof Chart !== "undefined" && typeof ChartDataLabels !== 'undefined') {
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
  if (typeof Chart === "undefined") return;
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
  const fallbackUrls = Number(crawl.fallback || 0);
  const successRate = Number(crawl.successRate || 0);
  
  if (els.qualityScore) {
    els.qualityScore.textContent = totalUrls ? `成功 ${successRate}%` : "--";
    els.qualityScore.title = totalUrls
      ? `本轮共抓取 ${totalUrls} 个 URL：实时成功 ${successUrls} 个，实时失败 ${failedUrls} 个，其中历史证据回退 ${fallbackUrls} 个`
      : "暂无本轮 URL 抓取结果";
  }

  // 1. The first chart reflects the latest URL-level crawl, not retained row data.
  initOrUpdateChart('qualityCanvas', {
    type: 'doughnut',
    data: {
      labels: ['实时成功', '实时失败', '历史证据回退'],
      datasets: [{
        data: [successUrls, Math.max(0, failedUrls - fallbackUrls), fallbackUrls],
        backgroundColor: [
          'rgba(16, 185, 129, 0.95)', // emerald
          'rgba(239, 68, 68, 0.95)',  // red
          'rgba(245, 158, 11, 0.95)'  // amber
        ],
        hoverBackgroundColor: [
          'rgba(52, 211, 153, 1)',
          'rgba(248, 113, 113, 1)',
          'rgba(251, 191, 36, 1)'
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

  const hasUnpublishedReasons = evidenceGaps > 0 || rejected > 0 || rejectReasons.length > 0;
  const chips = (hasUnpublishedReasons
    ? [
        ...(evidenceGaps ? [{ label: "证据未覆盖，需补爬", value: evidenceGaps, kind: "gap" }] : []),
        ...rejectReasons.slice(0, evidenceGaps ? 5 : 6),
      ]
    : [{ label: "无缺口或质量拦截，本轮状态正常", value: Math.max(accepted, 1), kind: "clean" }]
  ).map((item) => ({
    ...item,
    label: String(item.label || "").replace("未通过指标格式与单位门禁", "格式/单位未过")
      .replace("数值或事实依据不足", "依据不足")
      .replace("置信度低于80%", "置信度低")
      .replace("模型未确认主体归属", "主体未确认")
      .replace("来源域名或证据文本不支持该主体", "来源不匹配")
      .replace("指标名疑似串入公司名称", "指标名异常")
      .replace("抽取结果不可用", "抽取不可用")
  }));
  const sourceColors = chips.map((chip, index) => {
    if (chip.kind === "clean") return 'rgba(16, 185, 129, 0.88)';
    if (chip.kind === "gap") return 'rgba(59, 130, 246, 0.85)';
    return [
      'rgba(16, 185, 129, 0.85)',
      'rgba(245, 158, 11, 0.85)',
      'rgba(239, 68, 68, 0.85)',
      'rgba(139, 92, 246, 0.85)',
      'rgba(14, 165, 233, 0.85)',
      'rgba(236, 72, 153, 0.85)'
    ][index % 6];
  });
  const sourceHoverColors = chips.map((chip, index) => {
    if (chip.kind === "clean") return 'rgba(5, 150, 105, 1)';
    if (chip.kind === "gap") return 'rgba(96, 165, 250, 1)';
    return [
      'rgba(52, 211, 153, 1)',
      'rgba(251, 191, 36, 1)',
      'rgba(248, 113, 113, 1)',
      'rgba(167, 139, 250, 1)',
      'rgba(56, 189, 248, 1)',
      'rgba(244, 114, 182, 1)'
    ][index % 6];
  });
  
  initOrUpdateChart('sourceCanvas', {
    type: 'bar',
    data: {
      labels: chips.map(c => c.label),
      datasets: [{
        data: chips.map(c => c.value),
        backgroundColor: sourceColors,
        hoverBackgroundColor: sourceHoverColors,
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
          formatter: (value, context) => chips[context.dataIndex]?.kind === "clean" ? `已发布 ${accepted} 条` : value,
          display: function(context) { return context.dataset.data[context.dataIndex] > 0; }
        },
        tooltip: {
          backgroundColor: 'rgba(17, 24, 39, 0.85)',
          cornerRadius: 8,
          displayColors: false,
          callbacks: {
            title: (items) => items?.[0]?.label || "",
            label: (item) => chips[item.dataIndex]?.kind === "clean"
              ? `未发现证据缺口或质量拦截；本轮发布 ${accepted} 条`
              : `${item.label}：${item.formattedValue} 条；本轮发布 ${accepted} 条`
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
    const subtitleCues = file.audio && Array.isArray(file.audio.subtitleCues)
      ? JSON.stringify(file.audio.subtitleCues)
      : "";
    const audioAction = file.audio && file.audio.exists
      ? `<button type="button" class="row-icon-button audio-play-button" data-audio="${escapeHtml(file.audio.url)}" data-name="${escapeHtml(file.name)}" data-summary="${escapeHtml(file.audio.spokenText || file.audio.summary || '')}" data-subtitle-cues="${escapeHtml(subtitleCues)}" title="播放音频摘要" aria-label="播放音频摘要">${iconSvg("volume")}</button>`
      : `<button type="button" class="row-icon-button generate-audio-button" data-path="${safePath}" title="生成音频摘要" aria-label="生成音频摘要">${iconSvg("waveform")}</button>`;
    html += `
      <div class="file-row ${typeInfo.className} ${tableTone} ${state.multiSelect ? "with-select" : ""} ${checked ? "is-selected" : ""}" data-path="${safePath}">
        ${state.multiSelect ? `<span class="select-cell"><input type="checkbox" class="file-checkbox" data-path="${safePath}" ${checked} aria-label="选择 ${escapeHtml(file.name)}"></span>` : ""}
        <span class="file-name-cell file-name-editable" data-path="${safePath}" title="点击编辑文件名与备注">${typeInfo.icon} ${file.name}</span>
        <span>${fileDescription(file)}</span>
        <span class="time-cell">${file.mtimeText}</span>
        <span class="action-cell">
          ${audioAction}
          <button type="button" class="row-icon-button danger delete-file-button" data-path="${safePath}" title="删除" aria-label="删除">${iconSvg("trash")}</button>
          <a href="${file.url}" download class="row-icon-button download-icon-button" title="下载" aria-label="下载" style="text-decoration:none;display:inline-grid;place-items:center;">${iconSvg("download")}</a>
        </span>
      </div>
    `;
  });
  target.innerHTML = html;
}

function bindOutputTableEvents(target) {
  if (!target) return;
  target.querySelectorAll(".file-name-editable").forEach((cell) => {
    cell.addEventListener("click", () => openFileEditor(cell.dataset.path));
  });
  target.querySelectorAll(".delete-file-button").forEach((button) => {
    button.addEventListener("click", () => deleteFiles([button.dataset.path]));
  });
  target.querySelectorAll(".generate-audio-button").forEach((button) => {
    button.addEventListener("click", () => generateAudio(button.dataset.path, button));
  });
  target.querySelectorAll(".audio-play-button").forEach((button) => {
    button.addEventListener("click", () => {
      let subtitleCues = [];
      try {
        subtitleCues = JSON.parse(button.dataset.subtitleCues || "[]");
      } catch (_error) {
        subtitleCues = [];
      }
      playAudio(button.dataset.audio, button, button.dataset.name, button.dataset.summary, subtitleCues);
    });
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
    thinking: "Agent 判断",
    decision: "执行决定",
    answer: "本步结论",
    tool_call: "工具执行",
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
  "编排决策": 8,
  "定向补爬": 8,
  "发布": 9,
};

function traceFriendlyTool(tool) {
  const text = String(tool || "");
  if (!text) return "";
  if (text.includes("DeepSeek")) return "DeepSeek 事实清洗模型";
  if (text.includes("inspect_evidence_gaps")) return "证据缺口检查器";
  if (text.includes("schedule_targeted_recrawl")) return "定向补爬调度器";
  if (text.includes("publish_without_recrawl")) return "直接发布决策器";
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
    "编排决策": "Supervisor 正在读取缺口证据，并通过工具决定补爬还是发布。",
    "定向补爬": "只重抓缺少关键事实的行，并重新进入整理流程。",
    "发布": "写入可供页面、周报和业绩摘要使用的已验证事实。",
  };
  if (phase === "observe" && messages[node]) return messages[node];
  return humanizeAgentText(trace.message || messages[node] || "");
}

function humanizeAgentText(value) {
  return String(value || "")
    .replace(/#{1,6}\s*/g, "")
    .replace(/\*\*/g, "")
    .replace(/`/g, "")
    .replace(/\|\s*:?-{3,}:?\s*/g, "")
    .replace(/\s*\|\s*/g, " · ")
    .replace(/\s+/g, " ")
    .trim();
}

function traceKeyMetrics(trace) {
  const payload = trace.result && typeof trace.result === "object"
    ? trace.result
    : trace.output && typeof trace.output === "object"
      ? trace.output
      : {};
  const data = { ...payload, duration_ms: trace.duration_ms ?? payload.duration_ms };
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
    ["online_batches", "在线模型批次"],
    ["fallback_batches", "本地降级批次"],
    ["preserved_previous_facts", "保留历史事实"],
    ["durationMs", "耗时"],
    ["duration_ms", "耗时"],
  ];
  return fields
    .filter(([key]) => data[key] !== undefined && data[key] !== null)
    .map(([key, label]) => {
      const value = ["durationMs", "duration_ms"].includes(key)
        ? `${(Number(data[key]) / 1000).toFixed(1)} 秒`
        : data[key];
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
  const stepText = step ? `第 ${step}/9 步` : "工作流";
  const label = escapeHtml(tracePhaseLabel(phase));
  const time = escapeHtml((trace.ts || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, ""));
  title.innerHTML = `<span class="agent-trace-step">${stepText}</span><strong>${node}</strong><span class="agent-trace-badge">${label}</span><time>${time}</time>`;
  card.appendChild(title);

  const message = document.createElement("p");
  message.className = "agent-trace-message";
  message.textContent = traceFriendlyMessage(trace, phase);
  card.appendChild(message);

  if (trace.decision) {
    const decision = document.createElement("div");
    decision.className = "agent-trace-decision";
    const decisionText = trace.decision === "recrawl" ? "定向补爬" : "进入发布";
    decision.innerHTML = `<span>执行决定</span><strong>${escapeHtml(decisionText)}</strong>`;
    card.appendChild(decision);
  }

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

function setLog(text, appendWithDivider = false) {
  const currentText = els.logBox.textContent.trim();
  if (appendWithDivider && els.logBox.innerHTML.trim() !== "" && currentText !== "等待操作。" && currentText !== "执行日志已清空。") {
    const divider = document.createElement("div");
    divider.className = "log-divider";
    divider.innerHTML = "<span>新任务启动</span>";
    els.logBox.appendChild(divider);
  } else {
    els.logBox.innerHTML = "";
  }
  els.logBox.appendChild(document.createTextNode(text));
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

async function loadLatestAgentTrace() {
  if (!els.logBox) return;
  if (state.agentTraceLoaded) return;
  try {
    const response = await fetch("/api/agent-trace?limit=250");
    const data = await response.json();
    if (!data.ok || !Array.isArray(data.trace) || !data.trace.length) return;
    state.agentTraceLoaded = true;
    // The structured trace is the source of truth. Do not mix it with stale
    // plain-text logs left by a previous browser session.
    els.logBox.innerHTML = "";
    localStorage.removeItem("appLogs");
    renderAgentRunSummary(data.summary);
    data.trace.forEach((trace) => renderAgentTrace(trace, { skipScroll: true }));
    els.logBox.scrollTop = els.logBox.scrollHeight;
  } catch (error) {
    appendLog(`\nAgent 轨迹加载失败：${error.message}\n`);
  }
}

// Old versions persisted the entire log as unstructured text. Keeping that
// cache would duplicate and degrade the current human-readable Agent trace.
localStorage.removeItem("appLogs");

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
  
  // Toggle play/pause icons via class instead of style.display to avoid conflicts
  if (els.audioPlayPauseBtn) {
    els.audioPlayPauseBtn.classList.toggle("is-playing", isPlaying);
  }
  
  const soundwave = document.getElementById("audioSoundwave");
  if (soundwave) {
    soundwave.hidden = !isPlaying;
  }
  
  if (state.currentAudioButton) {
    state.currentAudioButton.classList.toggle("is-playing", isPlaying);
  }
}

function updateProgressFill() {
  if (!els.audioProgressBar) return;
  const bar = els.audioProgressBar;
  const min = parseFloat(bar.min) || 0;
  const max = parseFloat(bar.max) || 100;
  const val = parseFloat(bar.value) || 0;
  const pct = max > min ? ((val - min) / (max - min)) * 100 : 0;
  bar.style.background = `linear-gradient(to right, var(--blue) ${pct}%, #dde3ea ${pct}%)`;
}

function updateSubtitles() {
  const subtitleDiv = document.getElementById("audioSubtitle");
  if (!subtitleDiv || !state.currentAudio || !state.currentAudio.duration || !subtitleDiv.dataset.fullText) return;
  
  const progress = state.currentAudio.currentTime / state.currentAudio.duration;
  if (isNaN(progress)) return;

  let cues = [];
  try {
    cues = JSON.parse(subtitleDiv.dataset.cues || "[]");
  } catch (_error) {
    cues = [];
  }
  const hasTimedCues = Array.isArray(cues) && cues.length > 0;
  let sentences;
  let activeIndex = 0;
  let activeProgress = 0;
  if (hasTimedCues) {
    sentences = cues.map((cue) => String(cue.text || "")).filter(Boolean);
    const currentTime = state.currentAudio.currentTime;
    activeIndex = cues.findIndex((cue) => currentTime < Number(cue.end || 0));
    if (activeIndex < 0) activeIndex = cues.length - 1;
    const cue = cues[activeIndex] || {};
    const start = Number(cue.start || 0);
    const end = Math.max(Number(cue.end || start), start + 0.05);
    activeProgress = Math.max(0, Math.min(1, (currentTime - start) / (end - start)));
  } else {
    if (!subtitleDiv.dataset.sentences) {
      const text = subtitleDiv.dataset.fullText;
      sentences = (text.match(/[^。！？\n]+[。！？\n]*/g) || [text]).map((item) => item.trim()).filter(Boolean);
      if (!sentences.length) sentences = [text];
      subtitleDiv.dataset.sentences = JSON.stringify(sentences);
    } else {
      sentences = JSON.parse(subtitleDiv.dataset.sentences);
    }
    const totalChars = subtitleDiv.dataset.fullText.length;
    const currentChars = progress * totalChars;
    let charSum = 0;
    let sentenceStart = 0;
    for (let i = 0; i < sentences.length; i++) {
      const nextCharSum = charSum + sentences[i].length;
      if (currentChars <= nextCharSum || i === sentences.length - 1) {
        activeIndex = i;
        sentenceStart = charSum;
        break;
      }
      charSum = nextCharSum;
    }
    const activeSentenceLength = Math.max(sentences[activeIndex]?.length || 1, 1);
    activeProgress = Math.max(0, Math.min(1, (currentChars - sentenceStart) / activeSentenceLength));
  }

  const renderedKey = JSON.stringify(sentences);
  if (subtitleDiv.dataset.renderedSentences !== renderedKey) {
    const html = sentences.map((sentence, index) => `
      <div class="subtitle-line" data-subtitle-index="${index}">
        <span class="subtitle-line-fill">${escapeHtml(sentence)}</span>
        <span class="subtitle-line-text">${escapeHtml(sentence)}</span>
      </div>
    `).join("");
    subtitleDiv.innerHTML = `<div class="subtitle-spacer"></div>${html}<div class="subtitle-spacer"></div>`;
    subtitleDiv.dataset.renderedSentences = renderedKey;
    subtitleDiv.dataset.activeIndex = "";
  }

  const activeChanged = subtitleDiv.dataset.activeIndex !== String(activeIndex);
  subtitleDiv.dataset.activeIndex = String(activeIndex);

  subtitleDiv.querySelectorAll(".subtitle-line").forEach((line) => {
    const index = Number(line.dataset.subtitleIndex || 0);
    line.classList.toggle("is-past", index < activeIndex);
    line.classList.toggle("is-active", index === activeIndex);
    line.classList.toggle("is-future", index > activeIndex);
    line.style.setProperty("--subtitle-progress", index < activeIndex ? "100%" : index === activeIndex ? `${activeProgress * 100}%` : "0%");
  });

  const activeEl = subtitleDiv.querySelector(`.subtitle-line[data-subtitle-index="${activeIndex}"]`);
  if (activeEl && activeChanged && subtitleDiv.style.display !== "none") {
    const scrollTarget = activeEl.offsetTop - subtitleDiv.clientHeight / 2 + activeEl.clientHeight / 2;
    subtitleDiv.scrollTo({ top: scrollTarget, behavior: "smooth" });
  }
}

function playAudio(url, button = null, fileName = "音频摘要", summary = "", subtitleCues = []) {
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
      subtitleDiv.dataset.cues = "";
      subtitleDiv.dataset.activeIndex = "";
      subtitleDiv.dataset.renderedSentences = "";
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
      subtitleDiv.dataset.cues = JSON.stringify(Array.isArray(subtitleCues) ? subtitleCues : []);
      subtitleDiv.dataset.activeIndex = "";
      subtitleDiv.dataset.renderedSentences = "";
      subtitleDiv.hidden = false;
      subtitleDiv.style.display = "none"; // Hide by default until user clicks expand
      els.subtitleToggleBtn.hidden = false;
      els.subtitleToggleBtn.classList.remove("is-expanded");
      updateSubtitles();
    } else {
      subtitleDiv.dataset.fullText = "";
      subtitleDiv.dataset.sentences = "";
      subtitleDiv.dataset.cues = "";
      subtitleDiv.dataset.activeIndex = "";
      subtitleDiv.dataset.renderedSentences = "";
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
    els.audioProgressBar.value = 0;
    updateProgressFill();
  });
  
  state.currentAudio.addEventListener("timeupdate", () => {
    els.audioCurrentTime.textContent = formatTime(state.currentAudio.currentTime);
    if (!state.isScrubbing) {
      els.audioProgressBar.value = state.currentAudio.currentTime || 0;
      updateProgressFill();
    }
    updateSubtitles();
  });
  
  state.currentAudio.addEventListener("play", updateAudioPlayerUI);
  state.currentAudio.addEventListener("pause", updateAudioPlayerUI);
  state.currentAudio.addEventListener("ended", () => {
    updateAudioPlayerUI();
    els.audioProgressBar.value = 0;
    els.audioCurrentTime.textContent = "00:00";
    updateSubtitles();
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
    updateProgressFill();
    if (state.currentAudio) {
      state.currentAudio.currentTime = e.target.value;
      updateSubtitles();
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
  if (els.logModal) els.logModal.hidden = false;
  setBusy(true, "正在重新爬取", "crawl");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 开始启动后台爬虫任务...\n`, true);
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
  if (els.logModal) els.logModal.hidden = false;
  setBusy(true, "正在生成", "generate");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成周报，请稍候...\n`, true);
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
  if (els.logModal) els.logModal.hidden = false;
  setBusy(true, "正在生成", "performance");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成业绩摘要，请稍候...\n`, true);
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
    .replace(/!\[([^\]]*)\]\((https?:\/\/[^)\s]+|\/[^)\s]+)\)/g, '<div class="chat-image-wrapper"><img src="$2" alt="$1" class="chat-inline-image" loading="lazy" /><a href="$2" download class="chat-image-download-btn" target="_blank"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg></a></div>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function extractFirstMarkdownImage(value) {
  const match = String(value || "").match(/!\[([^\]]*)\]\((https?:\/\/[^)\s]+|\/[^)\s]+)\)/);
  if (!match) return null;
  return { markdown: match[0], alt: match[1] || "图表", url: match[2] };
}

function markdownToHtml(markdown) {
  const chartBlocks = [];
  const source = String(markdown || "").replace(/<chart>\s*([\s\S]*?)\s*<\/chart>/gi, (_match, jsonText) => {
    const index = chartBlocks.length;
    chartBlocks.push(jsonText);
    return `\n\n@@CHART_BLOCK_${index}@@\n\n`;
  });
  const lines = source.split(/\r?\n/);
  const html = [];
  let listType = null;
  let tableRows = null;

  function closeList() {
    if (listType) {
      html.push(`</${listType}>`);
      listType = null;
    }
  }

  function closeTable() {
    if (!tableRows) return;
    const rows = tableRows;
    tableRows = null;
    if (!rows.length) return;
    html.push('<div class="chat-table-wrap"><table class="chat-data-table">');
    rows.forEach((cells, rowIndex) => {
      const tag = rowIndex === 0 ? "th" : "td";
      html.push("<tr>");
      cells.forEach((cell) => html.push(`<${tag}>${inlineMarkdown(cell.trim())}</${tag}>`));
      html.push("</tr>");
    });
    html.push("</table></div>");
  }

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) {
      closeList();
      closeTable();
      continue;
    }
    const chartMatch = line.match(/^@@CHART_BLOCK_(\d+)@@$/);
    if (chartMatch) {
      closeList();
      closeTable();
      const chartIndex = Number(chartMatch[1]);
      html.push(`<div class="chart-placeholder" data-chart-index="${chartIndex}"></div>`);
      continue;
    }
    if (/^\|.+\|$/.test(line)) {
      const cells = line.split("|").slice(1, -1);
      if (cells.every((cell) => /^:?-{3,}:?$/.test(cell.trim()))) {
        continue;
      }
      closeList();
      if (!tableRows) tableRows = [];
      tableRows.push(cells);
      continue;
    } else {
      closeTable();
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
  closeTable();
  let rendered = html.join("");
  chartBlocks.forEach((jsonText, index) => {
    rendered = rendered.replace(
      `<div class="chart-placeholder" data-chart-index="${index}"></div>`,
      renderChartBlock(jsonText)
    );
  });
  return rendered;
}

function parseChartNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const num = Number(String(value).replace(/,/g, ""));
  return Number.isFinite(num) ? num : null;
}

function chartTickStep(count) {
  if (count <= 10) return 1;
  if (count <= 20) return 2;
  if (count <= 32) return 3;
  return Math.max(4, Math.round(count / 10));
}

function parseLegacyChartJson(jsonText) {
  const raw = String(jsonText || "").trim();
  if (!raw) return null;
  const candidates = [raw];
  const fenced = raw.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/i, "").trim();
  if (fenced !== raw) candidates.push(fenced);
  const unescaped = fenced
    .replace(/\\"/g, '"')
    .replace(/\\n/g, "\n")
    .replace(/\\t/g, "\t");
  if (unescaped !== fenced) candidates.push(unescaped);
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate);
      const chart = parsed && typeof parsed === "object" && parsed.chart_spec ? parsed.chart_spec : parsed;
      if (!chart || typeof chart !== "object") continue;
      if (typeof chart.series === "string") {
        try {
          chart.series = JSON.parse(chart.series);
        } catch (_error) {
          // Keep trying other candidates; this chart is not renderable as SVG.
        }
      }
      if (Array.isArray(chart.series)) {
        chart.series = chart.series
          .filter((item) => item && typeof item === "object")
          .map((item) => ({
            ...item,
            data: Array.isArray(item.data) ? item.data : (Array.isArray(item.values) ? item.values : []),
          }));
      }
      return chart;
    } catch (_error) {
      // Try the next tolerated shape.
    }
  }
  return null;
}

function renderChartBlock(jsonText) {
  const chart = parseLegacyChartJson(jsonText);
  if (!chart) return "";
  const x = Array.isArray(chart.x) ? chart.x.map(String) : [];
  const series = Array.isArray(chart.series) ? chart.series : [];
  if (!x.length || !series.length) return "";
  const width = 720;
  const height = 300;
  const pad = { left: 58, right: 22, top: 42, bottom: 48 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = [];
  series.forEach((item) => (Array.isArray(item.data) ? item.data : []).forEach((value) => {
    const num = parseChartNumber(value);
    if (num !== null) values.push(num);
  }));
  if (!values.length) return "";
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (min === max) {
    min = min > 0 ? 0 : min - 1;
    max = max + 1;
  } else if (min > 0) {
    min = 0;
  }
  const scaleY = (value) => pad.top + (max - value) / (max - min) * plotH;
  const scaleX = (index) => pad.left + (x.length === 1 ? plotW / 2 : index / (x.length - 1) * plotW);
  const colors = ["#0077c8", "#16a34a", "#f59e0b", "#dc2626", "#7c3aed", "#0891b2"];
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => min + (max - min) * ratio);
  const fmt = (value) => {
    const abs = Math.abs(value);
    if (abs >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
    if (abs >= 1000) return `${Math.round(value / 1000)}k`;
    if (abs >= 100) return String(Math.round(value));
    return String(Math.round(value * 100) / 100);
  };
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(chart.title || "趋势图")}">`;
  svg += `<text x="${pad.left}" y="22" class="chart-title">${escapeHtml(chart.title || "趋势图")}</text>`;
  if (chart.unit) svg += `<text x="${width - pad.right}" y="22" text-anchor="end" class="chart-unit">${escapeHtml(chart.unit)}</text>`;
  ticks.forEach((tick) => {
    const y = scaleY(tick);
    svg += `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" class="chart-grid"></line>`;
    svg += `<text x="${pad.left - 8}" y="${y + 4}" text-anchor="end" class="chart-axis">${escapeHtml(fmt(tick))}</text>`;
  });
  const tickStep = chartTickStep(x.length);
  const tickIndexes = x.map((_label, index) => index).filter((index) => index % tickStep === 0 || index === x.length - 1);
  const rotateLabels = tickIndexes.length > 10;
  tickIndexes.forEach((index) => {
    const label = x[index];
    const xPos = scaleX(index);
    if (rotateLabels) {
      svg += `<text x="${xPos}" y="${height - 18}" text-anchor="end" transform="rotate(-35 ${xPos} ${height - 18})" class="chart-axis">${escapeHtml(label)}</text>`;
    } else {
      svg += `<text x="${xPos}" y="${height - 18}" text-anchor="middle" class="chart-axis">${escapeHtml(label)}</text>`;
    }
  });
  if (chart.type === "bar") {
    const groupW = plotW / Math.max(x.length, 1);
    const barW = Math.max(10, Math.min(26, groupW / Math.max(series.length + 1, 2)));
    series.forEach((item, sIndex) => {
      const color = colors[sIndex % colors.length];
      (item.data || []).forEach((value, index) => {
        const num = parseChartNumber(value);
        if (num === null) return;
        const xPos = pad.left + index * groupW + groupW / 2 + (sIndex - (series.length - 1) / 2) * barW;
        const y = scaleY(num);
        const zeroY = scaleY(0);
        svg += `<rect x="${xPos - barW / 2}" y="${Math.min(y, zeroY)}" width="${barW}" height="${Math.abs(zeroY - y)}" rx="3" fill="${color}"></rect>`;
      });
    });
  } else {
    series.forEach((item, sIndex) => {
      const color = colors[sIndex % colors.length];
      const points = (item.data || []).map((value, index) => {
        const num = parseChartNumber(value);
        return num === null ? null : `${scaleX(index)},${scaleY(num)}`;
      }).filter(Boolean);
      if (points.length) svg += `<polyline points="${points.join(" ")}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>`;
      (item.data || []).forEach((value, index) => {
        const num = parseChartNumber(value);
        if (num === null) return;
        svg += `<circle cx="${scaleX(index)}" cy="${scaleY(num)}" r="4" fill="${color}"></circle>`;
      });
    });
  }
  svg += "</svg>";
  const legend = series.map((item, index) => `<span><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(item.name || `系列 ${index + 1}`)}</span>`).join("");
  const notes = Array.isArray(chart.notes) && chart.notes.length
    ? `<ul>${chart.notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("")}</ul>`
    : "";
  return `<div class="chat-chart-card">${svg}<div class="chart-legend">${legend}</div>${notes}</div>`;
}

const ASSISTANT_PROCESS_MARKERS = "(?:用户问的是|“[^”]{1,20}”通常指|\"[^\"]{1,20}\"通常指|我先|我来|我需要|为了获取|检索到了|检索只返回|数据包摘要显示|数据包显示|实际上，从数据包摘要|但早期的数据|CSV内容太大|让我|现在让我|现在我(?:已|来|开始|生成|整理)|现在(?:生成|整理|读取|检索)|我整理一下|数据已经齐全|数据非常清晰|很好|我已经有了|从JSON中|从数据中我已获取|需要搜索|需要确认|需要.*数据|从已有的数据|从JSON看到|当前时间为|按当前日期|上一个季度就是|[^。！？\\n]{0,30}最新一个完整季度是)";

function extractAssistantProcessLines(content) {
  const original = content || "";
  if (!original.trim()) return { answer: original, processLines: [] };
  const processSentencePattern = new RegExp(`(^|[。！？]\\s*)(${ASSISTANT_PROCESS_MARKERS}[^。！？]*(?:[。！？]|$))`, "g");
  const processLines = [];
  let answer = original.replace(processSentencePattern, (match, prefix, sentence) => {
    const clean = sentence.replace(/\s+/g, " ").trim();
    if (clean) processLines.push(clean);
    return prefix && prefix.trim() ? prefix.trim() : "";
  });
  const processLinePattern = new RegExp(`^\\s*${ASSISTANT_PROCESS_MARKERS}[\\s\\S]*?(?:。|！|？|$)\\s*$`);
  answer = answer
    .split(/\n+/)
    .filter((line) => {
      const clean = line.trim();
      if (!clean) return false;
      if (processLinePattern.test(clean)) {
        processLines.push(clean.replace(/\s+/g, " "));
        return false;
      }
      if (/需要(?:搜索|确认|补充|获取|读取|更多).*数据/.test(clean)) {
        processLines.push(clean.replace(/\s+/g, " "));
        return false;
      }
      return true;
    })
    .join("\n")
    .trim();
  return { answer, processLines: [...new Set(processLines)].slice(0, 12) };
}

function stripAssistantControlText(content) {
  let text = content || "";
  text = text.replace(/<suggestions>[\s\S]*?<\/suggestions>/gi, "").trim();
  text = text.replace(/<suggestions>[\s\S]*$/gi, "").trim();
  text = text.replace(/^\s*\[\s*["“][\s\S]*?["”]\s*(?:,\s*["“][\s\S]*?["”]\s*){1,}\]\s*$/m, "").trim();
  text = text.replace(/\n\s*\[\s*["“][\s\S]*?["”]\s*(?:,\s*["“][\s\S]*?["”]\s*){1,}\]\s*$/m, "").trim();
  text = text.replace(/<引用来源>[\s\S]*?<\/引用来源>/gi, "").trim();
  text = text.replace(/<引用来源>[\s\S]*$/gi, "").trim();
  text = text.replace(/\\<引用来源\\>[\s\S]*$/gi, "").trim();
  text = text.replace(/\[引用来源\][\s\S]*$/gi, "").trim();
  text = text.replace(/^\s*(?:联网搜索已关闭|当前联网搜索已关闭|已关闭联网搜索|由于联网搜索|因为联网搜索|本轮不会调用|我不能联网|当前不能联网)[^\n。！？]*(?:[。！？]|\n|$)/gmi, "").trim();
  const processMarkers = ASSISTANT_PROCESS_MARKERS;
  const processSentencePattern = new RegExp(`(^|[。！？]\\s*)${processMarkers}[^。！？]*(?:[。！？]|$)`, "g");
  text = text.replace(processSentencePattern, (match, prefix) => (prefix && prefix.trim() ? prefix.trim() : "")).trim();
  const formalStart = text.search(/\n?\s*(?:数据汇总（自然年收入|##\s*中国铁塔|中国铁塔6年收入趋势|结论[：:])/);
  if (formalStart > 0 && new RegExp(processMarkers).test(text.slice(0, formalStart))) {
    text = text.slice(formalStart).trim();
  }
  const processLinePattern = new RegExp(`^\\s*${processMarkers}[\\s\\S]*?(?:。|$)\\s*$`);
  text = text
    .split(/\n+/)
    .filter((line) => {
      const clean = line.trim();
      if (!clean) return false;
      if (processLinePattern.test(clean)) return false;
      if (/需要(?:搜索|确认|补充|获取|读取|更多).*数据/.test(clean)) return false;
      if (/^(?:各年收入|从已有的数据|从JSON看到|我需要确认)/.test(clean)) return false;
      return true;
    })
    .join("\n")
    .trim();
  text = text.replace(new RegExp(`^\\s*${processMarkers}[\\s\\S]*?(?=\\n\\s*(?:#{1,3}\\s+|[一二三四五六七八九十\\d]+[、.]\\s+|[^\\n：:]{2,18}[：:]|$))`, "g"), "").trim();
  text = text.replace(/^\s*[-–—]{3,}\s*$/gm, "").trim();
  return text;
}

function renderCitationMarkers(html, node) {
  return html.replace(/\[(?:来源\s*)?(\d+)\]/g, (match, p1) => {
    const idx = parseInt(p1, 10);
    let href = null;
    let label = `来源 ${idx}`;
    if (node.dataset.references) {
      try {
        const refs = JSON.parse(node.dataset.references);
        const ref = refs.find(r => r.index === idx);
        if (ref && ref.links && ref.links.length > 0 && ref.links[0].url) {
          href = ref.links[0].url;
          label = ref.links[0].label || ref.source || label;
        } else if (ref) {
          label = ref.source || label;
        }
      } catch(e) {}
    }
    if (href) {
      return `<a href="${href}" target="_blank" rel="noopener noreferrer" class="citation-marker" data-ref-id="${idx}" title="${escapeHtml(label)}" style="text-decoration:none;">${idx}</a>`;
    }
    return `<sup class="citation-marker" data-ref-id="${idx}" title="${escapeHtml(label)}">${idx}</sup>`;
  });
}

function readStoredJson(node, key, fallback = []) {
  if (!node.dataset[key]) return fallback;
  try {
    const value = JSON.parse(node.dataset[key]);
    return Array.isArray(value) ? value : fallback;
  } catch (e) {
    return fallback;
  }
}

function mergeCitationMeta(node, event) {
  const existingRefs = readStoredJson(node, "references");
  const incomingRefs = Array.isArray(event.references) ? event.references : [];
  const incomingLinks = Array.isArray(event.links) ? event.links : [];
  const mergedRefs = [];
  const mergedLinks = [];
  const seenRefs = new Set();

  const sourceType = event.provider ? "网络" : "本地";
  const addLink = (link) => {
    if (!link || !link.url) return;
    if (!mergedLinks.some((item) => item.url === link.url)) {
      mergedLinks.push({
        label: link.label || link.url,
        url: link.url,
      });
    }
  };
  const addRef = (ref, fallbackType) => {
    const links = Array.isArray(ref.links) ? ref.links.filter((link) => link && link.url) : [];
    const refKey = links.length
      ? links.map((link) => `${link.url}|${link.label || ""}`).join("||")
      : `${ref.source || ""}|${ref.index || ""}`;
    if (seenRefs.has(refKey)) return;
    seenRefs.add(refKey);
    const currentMax = mergedRefs.reduce((max, item) => Math.max(max, Number(item.index) || 0), 0);
    const index = Number(ref.index) || currentMax + 1;
    const normalizedLinks = links.map((link) => ({
      label: link.label || ref.source || `来源 ${index}`,
      url: link.url,
    }));
    const normalizedRef = {
      index,
      originalIndex: ref.originalIndex || ref.index,
      source: ref.source || (normalizedLinks[0] && normalizedLinks[0].label) || `来源 ${index}`,
      sourceType: ref.sourceType || fallbackType,
      links: normalizedLinks,
    };
    mergedRefs.push(normalizedRef);
    normalizedLinks.forEach(addLink);
  };

  existingRefs.forEach((ref) => addRef(ref, ref.sourceType || "来源"));
  incomingRefs.forEach((ref) => addRef(ref, sourceType));
  if (!incomingRefs.length) {
    incomingLinks.forEach((link) => addRef({ source: link.label, links: [link] }, sourceType));
  }

  node.dataset.references = JSON.stringify(mergedRefs);
  node.dataset.links = JSON.stringify(mergedLinks);
  if (event.contextAudit) {
    const audit = event.contextAudit;
    const retained = Number(audit.retained_chunks || 0);
    const input = Number(audit.input_chunks || 0);
    const tokens = Number(audit.token_estimate || 0);
    const budget = Number(audit.token_budget || 0);
    const compressed = Number(audit.compressed_chunks || 0);
    const skipped = Number(audit.skipped_chunks || 0);
    appendRagProcess(
      node,
      `上下文预算：保留 ${retained}/${input} 个片段，估算 ${tokens}/${budget} tokens，压缩 ${compressed} 个，跳过 ${skipped} 个。`
    );
  }
  if (event.retrievalQuality) {
    const quality = event.retrievalQuality;
    const score = Number(quality.score || 0);
    appendRagProcess(
      node,
      `检索质量：${quality.status || "unknown"}，评分 ${score}/100，官方命中 ${Number(quality.official_hits || 0)} 个，来源 ${Number(quality.unique_sources || 0)} 个。`
    );
  }
}

function appendActionConfirmation(node, event, originalMessage) {
  const body = node.querySelector(".message-body");
  if (!body || !event.actionId) return;
  const existing = body.querySelector(`[data-action-id="${CSS.escape(event.actionId)}"]`);
  if (existing) return;
  const card = document.createElement("div");
  card.className = "action-confirm-card";
  card.dataset.actionId = event.actionId;
  card.innerHTML = `
    <strong>需要确认：${escapeHtml(event.label || "执行操作")}</strong>
    <p>${escapeHtml(event.description || event.risk || "该操作会修改数据或触发任务。")}</p>
    <button type="button" class="primary-button small">确认执行</button>
  `;
  const button = card.querySelector("button");
  button.addEventListener("click", () => {
    state.pendingConfirmedActions.add(event.actionId);
    button.disabled = true;
    button.textContent = "已确认，正在执行";
    sendChat(originalMessage, { approvedActionIds: [event.actionId] });
  });
  body.appendChild(card);
}

function appendRunSummary(node, event) {
  const ms = Number(event.durationMs || 0);
  const seconds = ms ? `${(ms / 1000).toFixed(1)}s` : "-";
  appendRagProcess(node, `本轮完成：${event.status || "ok"}，工具 ${Number(event.toolCount || 0)} 次，用时 ${seconds}。`);
}

function setMessageContent(node, content, markdown = false) {
  const text = node.querySelector(".message-text") || node.querySelector(".markdown-body");
  if (markdown) {
    if (text.className === "message-text") text.className = "markdown-body";
    const cleaned = stripAssistantControlText(content);
    let html = markdownToHtml(cleaned);
    html = renderCitationMarkers(html, node);
    text.innerHTML = html;
  } else {
    text.textContent = content;
  }
}

function scrollMessagesToBottom() {
  if (!els.messages) return;
  const scroll = () => {
    els.messages.scrollTop = els.messages.scrollHeight;
  };
  scroll();
  requestAnimationFrame(scroll);
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
  if (role === "assistant" && content === "正在连接...") {
    text.dataset.placeholder = "connecting";
  }
  body.appendChild(text);
  node.append(avatar, body);
  els.messages.appendChild(node);
  setMessageContent(node, content, markdown);
  scrollMessagesToBottom();
  return node;
}

function chatThreadId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID().replace(/-/g, "").slice(0, 12);
  }
  return `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function initialAssistantText() {
  return "您好！我是小竞AI，面向 CMHK 竞对、云厂商和宏观政策数据的分析型 Agent。我可以帮您：<br>1. <b>查数据</b>：检索本地三类数据库，说明覆盖主体、期间、指标口径和来源。<br>2. <b>核来源</b>：优先使用官方值，标明 verification_count、source-gap 和冲突状态。<br>3. <b>看趋势</b>：基于季度、半年度和年度历史数据做趋势判断与预测边界说明。<br>4. <b>找外部信息</b>：需要时联网检索公开网页，并把来源带回回答。<br>请问今天需要分析什么？";
}

function resetChatMessages() {
  els.messages.innerHTML = `
    <div class="message assistant">
      <span class="avatar">AI</span>
      <div class="message-body">
        <div class="message-text">${initialAssistantText()}</div>
      </div>
    </div>
  `;
}

function renderChatThreadList() {
  if (!els.chatThreadList) return;
  const query = String(state.chatThreadSearch || "").trim().toLowerCase();
  const threads = state.chatThreads.filter((thread) => {
    if (!query) return true;
    return [thread.title, thread.preview]
      .map((item) => String(item || "").toLowerCase())
      .some((text) => text.includes(query));
  });
  if (!state.chatThreads.length) {
    els.chatThreadList.innerHTML = `<div class="agent-memory-empty">暂无历史对话</div>`;
    return;
  }
  if (!threads.length) {
    els.chatThreadList.innerHTML = `<div class="agent-memory-empty">没有匹配的对话</div>`;
    return;
  }
  els.chatThreadList.innerHTML = threads.map((thread) => `
    <div class="chat-thread-item ${thread.id === state.activeThreadId ? "is-active" : ""}" data-thread-id="${escapeHtml(thread.id)}">
      <button class="chat-thread-main" type="button">
        <span class="chat-thread-title">${thread.pinned ? "置顶 · " : ""}${escapeHtml(thread.title || "未命名对话")}</span>
        <span class="chat-thread-preview">${escapeHtml(thread.preview || `${thread.messageCount || 0} 条消息`)}</span>
      </button>
      <button class="chat-thread-pin ${thread.pinned ? "is-pinned" : ""}" type="button" title="${thread.pinned ? "取消置顶" : "置顶"}" aria-label="${thread.pinned ? "取消置顶" : "置顶"}" data-action="pin">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5"></path><path d="M8 3h8l-1 7 3 4H6l3-4z"></path></svg>
      </button>
      <button class="chat-thread-delete" type="button" title="删除" aria-label="删除">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
      </button>
    </div>
  `).join("");
}

async function loadChatThreads() {
  if (!els.chatThreadList) return;
  try {
    const response = await fetch("/api/chat-threads");
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "历史对话加载失败");
    state.chatThreads = Array.isArray(payload.threads) ? payload.threads : [];
    renderChatThreadList();
  } catch (error) {
    els.chatThreadList.innerHTML = `<div class="agent-memory-empty">${escapeHtml(error.message || String(error))}</div>`;
  }
}

async function persistActiveThread() {
  if (!state.activeThreadId && !state.chatHistory.length) return;
  if (!state.activeThreadId) state.activeThreadId = chatThreadId();
  try {
    const response = await fetch("/api/chat-threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id: state.activeThreadId,
        messages: state.chatHistory,
        agentContextKey: state.agentContextKey,
        loadedSkillIds: Array.from(state.loadedSkillIds),
      }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "保存失败");
    state.activeThreadId = payload.thread && payload.thread.id ? payload.thread.id : state.activeThreadId;
    state.chatThreads = Array.isArray(payload.threads) ? payload.threads : state.chatThreads;
    renderChatThreadList();
  } catch (error) {
    console.warn("保存历史对话失败", error);
  }
}

function startNewChatThread() {
  state.activeThreadId = chatThreadId();
  state.chatHistory = [];
  state.agentContextKey = "";
  state.loadedSkillIds = new Set();
  state.chatQueue = [];
  resetChatMessages();
  renderChatQueue();
  renderChatThreadList();
  els.chatInput.focus();
}

async function openChatThread(threadId) {
  if (!threadId) return;
  try {
    const response = await fetch(`/api/chat-threads?id=${encodeURIComponent(threadId)}`);
    const payload = await response.json();
    if (!payload.ok || !payload.thread) throw new Error(payload.error || "对话不存在");
    const thread = payload.thread;
    state.activeThreadId = thread.id;
    state.chatHistory = Array.isArray(thread.messages) ? thread.messages : [];
    state.agentContextKey = String(thread.agentContextKey || "");
    state.loadedSkillIds = new Set(Array.isArray(thread.loadedSkillIds) ? thread.loadedSkillIds : []);
    els.messages.innerHTML = "";
    if (!state.chatHistory.length) {
      resetChatMessages();
    } else {
      state.chatHistory.forEach((item) => addMessage(item.role, item.content, item.role === "assistant"));
    }
    renderChatThreadList();
  } catch (error) {
    addMessage("assistant", `打开历史对话失败：${error.message || String(error)}`);
  }
}

async function deleteChatThread(threadId) {
  if (!threadId) return;
  try {
    const response = await fetch("/api/chat-threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "delete", id: threadId }),
    });
    const payload = await response.json();
    state.chatThreads = Array.isArray(payload.threads) ? payload.threads : state.chatThreads;
    if (state.activeThreadId === threadId) startNewChatThread();
    renderChatThreadList();
  } catch (error) {
    console.warn("删除历史对话失败", error);
  }
}

async function pinChatThread(threadId, pinned) {
  if (!threadId) return;
  try {
    const response = await fetch("/api/chat-threads", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "pin", id: threadId, pinned }),
    });
    const payload = await response.json();
    if (!payload.ok) throw new Error(payload.error || "置顶失败");
    state.chatThreads = Array.isArray(payload.threads) ? payload.threads : state.chatThreads;
    renderChatThreadList();
  } catch (error) {
    addMessage("assistant", `置顶对话失败：${error.message || String(error)}`);
  }
}

function renderChatQueue() {
  if (!els.chatQueueList) return;
  if (!state.chatQueue.length) {
    els.chatQueueList.hidden = true;
    els.chatQueueList.innerHTML = "";
    return;
  }
  els.chatQueueList.hidden = false;
  els.chatQueueList.innerHTML = state.chatQueue.map((item, index) => `
    <div class="queued-message-item" data-queue-id="${escapeHtml(item.id)}">
      <strong>等待 ${index + 1}</strong>
      <span class="queued-message-text">${escapeHtml(item.message)}</span>
      <button class="queued-message-action" type="button" data-action="edit">修改</button>
      <button class="queued-message-action" type="button" data-action="remove">撤回</button>
    </div>
  `).join("");
}

function enqueueChatMessage(message) {
  state.chatQueue.push({ id: chatThreadId(), message });
  renderChatQueue();
}

function processNextQueuedChat() {
  if (state.chatBusy || !state.chatQueue.length) return;
  const next = state.chatQueue.shift();
  renderChatQueue();
  if (next && next.message) sendChat(next.message);
}

function setChatSidebarCollapsed(collapsed) {
  if (!els.chatWorkspace) return;
  els.chatWorkspace.classList.toggle("is-sidebar-collapsed", collapsed);
  if (els.toggleChatThreadsButton) {
    els.toggleChatThreadsButton.title = collapsed ? "展开历史对话" : "收起历史对话";
    els.toggleChatThreadsButton.setAttribute("aria-label", collapsed ? "展开历史对话" : "收起历史对话");
  }
}

function clearConnectingPlaceholder(node) {
  const placeholder = node.querySelector('.message-body > [data-placeholder="connecting"]');
  if (placeholder) placeholder.remove();
}

function messageBody(node) {
  return node.querySelector(".message-body");
}

function ensureToolList(node) {
  const body = messageBody(node);
  if (!body) return null;
  let list = body.lastElementChild;
  if (!list || !list.classList.contains("tool-call-list")) {
    list = document.createElement("div");
    list.className = "tool-call-list";
    body.appendChild(list);
  }
  return list;
}

function appendStreamBlock(node, element) {
  const body = messageBody(node);
  if (!body || !element) return null;
  body.appendChild(element);
  return element;
}

function currentMessageTextNode(node) {
  const body = messageBody(node);
  let text = body.lastElementChild;
  if (
    !text ||
    text.classList.contains("assistant-status-line") ||
    text.classList.contains("assistant-action-line") ||
    (!text.classList.contains("message-text") && !text.classList.contains("markdown-body"))
  ) {
    text = document.createElement("div");
    text.className = "message-text";
    text._rawMarkdown = "";
    body.appendChild(text);
  }
  return text;
}

function setCurrentMessageContent(node, content, markdown = false, textNode = null) {
  const text = textNode || currentMessageTextNode(node);
  if (markdown) {
    if (text.className === "message-text") text.className = "markdown-body";
    const cleaned = stripAssistantControlText(content);
    let html = markdownToHtml(cleaned);
    html = renderCitationMarkers(html, node);
    text.innerHTML = html;
  } else {
    text.textContent = content;
  }
}

function dedupeAssistantTextBlocks(node) {
  const body = messageBody(node);
  if (!body) return;
  const blocks = [...body.querySelectorAll(":scope > .message-text, :scope > .markdown-body")]
    .filter((item) => !item.classList.contains("assistant-status-line") && item.textContent.trim().length > 80);
  const seen = new Map();
  blocks.forEach((block) => {
    const normalized = block.textContent.replace(/\s+/g, " ").trim();
    const key = /中国铁塔/.test(normalized) && /2017/.test(normalized) && /2025/.test(normalized) && /Q1=/.test(normalized)
      ? "china-tower-quarterly-revenue-list"
      : normalized.slice(0, 120);
    if (!key) return;
    const earlier = seen.get(key);
    if (earlier && earlier.isConnected) {
      earlier.remove();
    }
    seen.set(key, block);
  });
}

function appendStableChartImage(node, chartImage) {
  const body = messageBody(node);
  if (!body || !chartImage || !chartImage.url) return;
  const existing = body.querySelector(`.chart-result-block[data-chart-url="${CSS.escape(chartImage.url)}"]`);
  if (existing) return;
  const block = document.createElement("div");
  block.className = "chart-result-block";
  block.dataset.chartUrl = chartImage.url;
  block.innerHTML = inlineMarkdown(chartImage.markdown);
  body.appendChild(block);
}

function appendAssistantActionLine(node, event) {
  const body = messageBody(node);
  if (!body || !event || event.type !== "tool_call_start") return;
  const id = event.id || `${event.name || "tool"}-${node.querySelectorAll(".assistant-action-line").length}`;
  const existing = node.querySelector(`.assistant-action-line[data-tool-id="${CSS.escape(id)}"]`);
  if (existing) return;
  const line = document.createElement("div");
  line.className = "assistant-action-line";
  line.dataset.toolId = id;
  line.dataset.toolName = event.name || "";
  line.textContent = toolNarrationText(event.name);
  appendStreamBlock(node, line);
}

function appendAssistantProcessLine(node, text, beforeNode = null, preferredToolName = "") {
  const body = messageBody(node);
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!body || !clean) return;
  const key = clean.slice(0, 240);
  const toolName = preferredToolName || processLineToolAnchorName(clean);
  const isModelProcessSentence = /^(?:我先|我来|让我|现在让我|我需要|为了|需要)/.test(clean);
  const existingForTool = toolName
    ? [...body.querySelectorAll(".assistant-process-line")].find((item) => item.dataset.toolName === toolName)
    : null;
  if (existingForTool) {
    if (!existingForTool.dataset.fromTypedEvent || isModelProcessSentence) return;
    existingForTool.remove();
  }
  const exists = [...body.querySelectorAll(".assistant-process-line")].some((item) => item.dataset.processKey === key);
  if (exists) return;
  const line = document.createElement("div");
  line.className = "assistant-process-line";
  line.dataset.processKey = key;
  if (toolName) line.dataset.toolName = toolName;
  line.textContent = clean;
  if (beforeNode && beforeNode.parentNode === body) {
    body.insertBefore(line, beforeNode);
  } else {
    body.appendChild(line);
  }
}

function processLineToolAnchorName(text) {
  const clean = String(text || "");
  if (/Agent Skill|Skill|完整指令|完整 SKILL/i.test(clean)) return "read_agent_skill";
  if (/数据库|数据集|可用的数据集|已选数据库/.test(clean)) return "list_local_datasets";
  if (/长期记忆|记忆|相关规则/.test(clean)) return "search_agent_memory";
  if (/官方核验|原文|核验文件|确认细节|确认口径|具体行数据|行数据|查询一下/.test(clean)) return "read_local_reference";
  if (/检索|摘要片段|查找|搜索|查询/.test(clean)) return "search_local_reports";
  if (/当前时间|按当前日期|上一个季度|完整季度|最新一个完整季度/.test(clean)) return "search_local_reports";
  return "";
}

function findProcessInsertionAnchor(node, text, fallbackNode = null, preferredToolName = "") {
  const body = messageBody(node);
  if (!body) return fallbackNode;
  const toolName = preferredToolName || processLineToolAnchorName(text);
  if (toolName) {
    const actionLine = [...body.querySelectorAll(".assistant-action-line")].find((item) => item.dataset.toolName === toolName);
    if (actionLine) return actionLine;
    const toolCard = [...body.querySelectorAll(".tool-details")].find((item) => item.dataset.toolName === toolName);
    if (toolCard) return toolCard;
  }
  return fallbackNode;
}

function renderAssistantTextWithProcess(node, rawContent, markdown = true, textNode = null) {
  const target = textNode || currentMessageTextNode(node);
  const { answer: contentWithoutProcess, processLines } = extractAssistantProcessLines(rawContent);
  processLines.forEach((line) => {
    const toolName = processLineToolAnchorName(line);
    appendAssistantProcessLine(node, line, findProcessInsertionAnchor(node, line, target, toolName), toolName);
  });
  setCurrentMessageContent(node, contentWithoutProcess, markdown, target);
  return contentWithoutProcess;
}

function appendRagProcess(node, text) {
  if (!node || node.dataset.showThinkingPanel !== "true") return;
  let processNode = node.querySelector(".rag-process");
  if (!processNode) {
    processNode = document.createElement("details");
    processNode.className = "rag-process";
    const title = document.createElement("summary");
    title.className = "rag-process-title";
    title.innerHTML = `<span class="rag-process-caret" aria-hidden="true">▾</span><span>Thinking</span><span class="thinking-dots" aria-hidden="true"><i>.</i><i>.</i><i>.</i></span>`;
    title.setAttribute("aria-label", "Thinking");
    processNode.appendChild(title);
    const steps = document.createElement("div");
    steps.className = "rag-process-steps";
    processNode.appendChild(steps);
    const body = node.querySelector(".message-body");
    body.insertBefore(processNode, body.firstChild);
  }
  const steps = processNode.querySelector(".rag-process-steps");
  if (!steps) return;
  const exists = [...steps.querySelectorAll(".rag-step")].some((item) => item.textContent === text);
  if (exists) return;
  const step = document.createElement("div");
  step.className = "rag-step";
  step.textContent = text;
  steps.appendChild(step);
}

function appendRagSources(node, sources, links) {
  // No-op for the top process display - we now show sources in the footer instead
  // (kept for compatibility)
}

function appendCitationFooter(node, references, links) {
  // Remove any existing citation footer
  const existing = node.querySelector(".citation-footer");
  if (existing) existing.remove();

  // Build the list of links to display
  let refList = [];
  if (references && references.length) {
    refList = references;
  } else if (links && links.length) {
    // fallback: build pseudo-references from flat links
    refList = links.map((l, i) => ({ index: i + 1, source: l.label, links: [l] }));
  }
  if (!refList.length) return;

  const footer = document.createElement("div");
  footer.className = "citation-footer";
  const header = document.createElement("div");
  header.className = "citation-footer-header";
  header.textContent = "引用来源";

  const list = document.createElement("div");
  list.className = "citation-footer-list";

  refList.slice(0, 12).forEach(ref => {
    const refLinks = ref.links || [];
    refLinks.forEach(link => {
      const a = document.createElement("a");
      a.href = link.url;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.className = "citation-footer-link";
      const num = document.createElement("span");
      num.className = "citation-footer-num";
      num.textContent = `[${ref.index}]`;
      const type = document.createElement("span");
      type.className = "citation-footer-type";
      type.textContent = ref.sourceType || "";
      const label = document.createElement("span");
      label.className = "citation-footer-label";
      label.textContent = link.label || ref.source || link.url;
      a.title = label.textContent;
      a.append(num);
      if (ref.sourceType) a.append(type);
      a.append(label);
      list.appendChild(a);
    });
  });

  footer.append(header, list);
  const body = node.querySelector(".message-body");
  body.appendChild(footer);
}

function appendToolCallCard(node, event) {
  const body = messageBody(node);
  if (!body) return;
  const id = event.id || `${event.name || "tool"}-${node.querySelectorAll(".tool-details").length}`;
  let card = node.querySelector(`.tool-details[data-tool-id="${CSS.escape(id)}"]`);
  if (!card) {
    card = document.createElement("details");
    card.className = "tool-details";
    card.open = false;
    card.dataset.toolId = id;
    card.innerHTML = `
      <summary class="tool-summary">
        <span class="tool-icon" aria-hidden="true"></span>
        <span class="tool-label"></span>
        <span class="tool-name"></span>
      </summary>
      <div class="tool-body">处理中...</div>
    `;
    appendStreamBlock(node, card);
  }
  card.dataset.toolName = event.name || technicalName;
  const iconNode = card.querySelector(".tool-icon");
  const labelNode = card.querySelector(".tool-label");
  const nameNode = card.querySelector(".tool-name");
  const bodyNode = card.querySelector(".tool-body");
  const technicalName = event.name || "tool";
  if (iconNode) iconNode.innerHTML = iconSvg(toolIconName(technicalName));
  if (labelNode) labelNode.textContent = toolFriendlyName(technicalName);
  if (nameNode) nameNode.textContent = technicalName;
  card.classList.toggle("is-done", event.type === "tool_call_result");
  if (bodyNode && event.type === "tool_call_result") {
    const args = event.args ? `参数:\n${event.args}\n\n` : "";
    const result = event.content ? `结果:\n${event.content}` : "";
    if (event.name === "render_python_chart") {
      bodyNode.classList.add("markdown-body");
      bodyNode.innerHTML = markdownToHtml(`${args}${result}`);
    } else {
      bodyNode.classList.remove("markdown-body");
      bodyNode.textContent = `${args}${result}`;
    }
    bodyNode.hidden = !args && !event.content;
  }
}

function resizeChatInput() {
  const value = els.chatInput.value || "";
  const isSingleLine = !value.includes("\n");
  if (isSingleLine) {
    els.chatInput.style.height = "30px";
    return;
  }
  els.chatInput.style.height = "auto";
  els.chatInput.style.height = `${Math.min(120, Math.max(30, els.chatInput.scrollHeight))}px`;
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

function normalizeSuggestionList(items) {
  if (!Array.isArray(items)) return [];
  const blocked = /(联网搜索|打开.*搜索|搜索.*开关|前端开关|工具配置|web_search|read_webpage)/i;
  return items
    .map((item) => String(item || "").trim())
    .filter((item) => item && !blocked.test(item))
    .slice(0, 3);
}

function currentAgentContextKey(skillIds, datasetIds) {
  return JSON.stringify({
    skills: [...skillIds].sort(),
    datasets: [...datasetIds].sort(),
  });
}

function compactChatHistory() {
  return state.chatHistory
    .slice(-8)
    .map((item) => ({
      role: item.role === "assistant" ? "assistant" : "user",
      content: String(item.content || "").replace(/\s+/g, " ").trim().slice(0, 1800),
    }))
    .filter((item) => item.content);
}

async function sendChat(message, options = {}) {
  if (!state.activeThreadId) state.activeThreadId = chatThreadId();
  const conversationHistory = compactChatHistory();
  addMessage("user", message);
  state.chatHistory.push({ role: "user", content: message });
  state.chatHistory = state.chatHistory.slice(-80);
  persistActiveThread();
  setChatBusy(true);
  try {
    const assistantNode = addMessage("assistant", "正在连接...");
    const webSearchEnabled = Boolean(state.webSearchEnabled);
    const thinkingEnabled = Boolean(state.thinkingEnabled);
    assistantNode.dataset.showThinkingPanel = thinkingEnabled ? "true" : "false";
    const selectedSkillIds = Array.from(state.selectedSkillIds);
    const selectedDatasetIds = Array.from(state.selectedDatasetIds);
    const contextKey = currentAgentContextKey(selectedSkillIds, selectedDatasetIds);
    const emitContextEvents = contextKey !== state.agentContextKey;
    const loadedSkillIds = Array.from(state.loadedSkillIds);
    const approvedActionIds = Array.isArray(options.approvedActionIds) ? options.approvedActionIds : [];
    const response = await fetch("/api/chat-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        webSearchEnabled,
        thinkingEnabled,
        selectedSkillIds,
        selectedDatasetIds,
        approvedActionIds,
        conversationHistory,
        emitContextEvents,
        loadedSkillIds,
      }),
    });
    if (!response.ok || !response.body) throw new Error("对话请求失败");
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let answer = "";
    const insertedChartUrls = new Set();
    let hasVisibleAssistantText = false;
    let isDone = false;

    const showImmediateStatus = () => {
      if (hasVisibleAssistantText) return;
      if (!assistantNode.querySelector(".assistant-status-line")) {
        const statusNode = document.createElement("div");
        statusNode.className = "assistant-status-line";
        statusNode.textContent = "正在分析请求，并调用相关工具获取依据。";
        const body = messageBody(assistantNode);
        if (body) body.appendChild(statusNode);
      }
      hasVisibleAssistantText = true;
      scrollMessagesToBottom();
    };

    const renderToolEvent = (event) => {
      if (event.type === "tool_call_start") {
        appendAssistantActionLine(assistantNode, event);
      }
      if (event.type === "tool_call_result" && event.name === "read_agent_skill" && event.args) {
        try {
          const parsedArgs = JSON.parse(event.args);
          if (parsedArgs && parsedArgs.skill_id) state.loadedSkillIds.add(String(parsedArgs.skill_id));
        } catch (e) {
          // Ignore malformed tool args; the visible tool card still shows the call.
        }
      }
      appendToolCallCard(assistantNode, event);
      if (event.type === "tool_call_result" && event.name === "render_python_chart") {
        const chartImage = extractFirstMarkdownImage(event.content);
        if (chartImage && !insertedChartUrls.has(chartImage.url)) {
          insertedChartUrls.add(chartImage.url);
          appendStableChartImage(assistantNode, chartImage);
        }
      }
    };

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
        if (event.type !== "done") clearConnectingPlaceholder(assistantNode);
        
        if (event.type === "done") {
          isDone = true;
          break;
        } else if (event.type === "thinking_status") {
          if (thinkingEnabled) appendRagProcess(assistantNode, event.text);
        } else if (event.type === "process") {
          if (thinkingEnabled) appendRagProcess(assistantNode, event.text);
        } else if (event.type === "meta") {
          mergeCitationMeta(assistantNode, event);
        } else if (event.type === "process_line") {
          const anchor = findProcessInsertionAnchor(assistantNode, event.text, null, event.toolName || "");
          appendAssistantProcessLine(assistantNode, event.text, anchor, event.toolName || "");
          const toolName = event.toolName || processLineToolAnchorName(event.text);
          if (toolName) {
            const line = [...assistantNode.querySelectorAll(".assistant-process-line")].find((item) => item.dataset.toolName === toolName);
            if (line) line.dataset.fromTypedEvent = "true";
          }
          hasVisibleAssistantText = true;
          scrollMessagesToBottom();
        } else if (event.type === "action_confirmation") {
          appendActionConfirmation(assistantNode, event, message);
        } else if (event.type === "run_summary") {
          if (thinkingEnabled) appendRunSummary(assistantNode, event);
        } else if (event.type === "tool_call_start" || event.type === "tool_call_result") {
          if (!hasVisibleAssistantText) {
            showImmediateStatus();
          }
          renderToolEvent(event);
          scrollMessagesToBottom();
        } else if (event.type === "delta") {
          answer += event.text;
          const textNode = currentMessageTextNode(assistantNode);
          if (textNode._rawMarkdown === undefined) textNode._rawMarkdown = "";
          textNode._rawMarkdown += event.text;

          let displayAnswer = textNode._rawMarkdown;
          const sugMatch = answer.match(/<suggestions>\s*([\s\S]*?)\s*<\/suggestions>/i);
          let suggestionsHTML = "";
          if (sugMatch) {
            try {
              let jsonStr = sugMatch[1].trim();
              jsonStr = jsonStr.replace(/^```json/i, "").replace(/^```/i, "").replace(/```$/i, "").trim();
              const arr = normalizeSuggestionList(JSON.parse(jsonStr));
              displayAnswer = displayAnswer.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
              if (arr && arr.length > 0) {
                suggestionsHTML = `<div class="suggestion-chips">` + arr.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${escapeHtml(q)}</button>`).join('') + `</div>`;
              }
            } catch (e) {
               console.error("Suggestion parse error:", e, sugMatch[1]);
            }
          }
          const renderedAnswer = renderAssistantTextWithProcess(assistantNode, displayAnswer, true, textNode);
          if (renderedAnswer.trim()) {
            hasVisibleAssistantText = true;
          }
          dedupeAssistantTextBlocks(assistantNode);
          if (suggestionsHTML) {
            textNode.insertAdjacentHTML("beforeend", suggestionsHTML);
          }
          scrollMessagesToBottom();
        } else if (event.type === "error") {
          answer += `\n\n**错误：** ${event.text}`;
          const errTextNode = currentMessageTextNode(assistantNode);
          if (errTextNode._rawMarkdown === undefined) errTextNode._rawMarkdown = "";
          errTextNode._rawMarkdown += `\n\n**错误：** ${event.text}`;
          let displayAnswer = errTextNode._rawMarkdown.replace(/<suggestions>[\s\S]*$/, "");
          setCurrentMessageContent(assistantNode, displayAnswer, true, errTextNode);
          hasVisibleAssistantText = true;
          dedupeAssistantTextBlocks(assistantNode);
        } else if (event.type === "tool_start") {
          const label = escapeHtml(toolFriendlyName(event.name));
          const technicalName = escapeHtml(event.name || "tool");
          const icon = iconSvg(toolIconName(event.name));
          const toolHtml = `<div class="inline-tool-event"><span class="tool-icon" aria-hidden="true">${icon}</span><strong>${label}</strong><code>${technicalName}</code></div>`;
          answer += `\n\n${toolHtml}\n\n`;
          const toolTextNode = currentMessageTextNode(assistantNode);
          if (toolTextNode._rawMarkdown === undefined) toolTextNode._rawMarkdown = "";
          toolTextNode._rawMarkdown += `\n\n${toolHtml}\n\n`;
          setCurrentMessageContent(assistantNode, toolTextNode._rawMarkdown, true, toolTextNode);
          scrollMessagesToBottom();
        } else if (event.type === "tool_end") {
          // Tool result cards handle completion state; do not add a separate completion line.
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
    if (!answer.trim()) {
      setCurrentMessageContent(assistantNode, "操作完成。", true);
      state.chatHistory.push({ role: "assistant", content: "操作完成。" });
      state.chatHistory = state.chatHistory.slice(-80);
      state.agentContextKey = contextKey;
      await persistActiveThread();
    } else {
      let finalAnswer = answer;
      const sugMatch = finalAnswer.match(/<suggestions>\s*([\s\S]*?)\s*<\/suggestions>/i);
      let suggestionsHTML = "";
      if (sugMatch) {
        try {
          let jsonStr = sugMatch[1].trim();
          jsonStr = jsonStr.replace(/^```json/i, "").replace(/^```/i, "").replace(/```$/i, "").trim();
          const arr = normalizeSuggestionList(JSON.parse(jsonStr));
          finalAnswer = finalAnswer.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
          if (arr && arr.length > 0) {
            suggestionsHTML = `<div class="suggestion-chips">` + arr.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${escapeHtml(q)}</button>`).join('') + `</div>`;
          }
        } catch (e) {
            console.error("Suggestion parse error final:", e, sugMatch[1]);
        }
      }
      // Strip <引用来源> tag from final answer (LLM sometimes outputs it despite instructions)
      const citationTagMatch = finalAnswer.match(/<引用来源>([\s\S]*?)<\/引用来源>/i);
      let llmCitationText = citationTagMatch ? citationTagMatch[1].trim() : null;
      finalAnswer = finalAnswer.replace(/<引用来源>[\s\S]*?<\/引用来源>/gi, "").trim();
      finalAnswer = finalAnswer.replace(/<引用来源>[\s\S]*$/gi, "").trim();
      finalAnswer = finalAnswer.replace(/\\<引用来源\\>[\s\S]*$/gi, "").trim();
      finalAnswer = finalAnswer.replace(/\[引用来源\][\s\S]*$/gi, "").trim();
      finalAnswer = stripAssistantControlText(finalAnswer);

          finalAnswer = renderAssistantTextWithProcess(assistantNode, finalAnswer, true);
      // Inject citation footer if we have reference data
      const storedRefs = assistantNode.dataset.references ? JSON.parse(assistantNode.dataset.references) : null;
      const storedLinks = assistantNode.dataset.links ? JSON.parse(assistantNode.dataset.links) : null;
      if (storedRefs || storedLinks) {
        appendCitationFooter(assistantNode, storedRefs, storedLinks);
      } else if (llmCitationText) {
        // Fallback: parse LLM's own citation text into simple link items
        // e.g. "[来源 1] weekly_report.md — 政治资讯\n[来源 2] final_audit.md — ..."
        const fallbackRefs = [];
        const lines = llmCitationText.split(/\n|(?=\[来源\s*\d+\])/g);
        for (const line of lines) {
          const m = line.match(/\[来源\s*(\d+)\]\s*([^—\n]+)/);
          if (m) {
            const idx = parseInt(m[1]);
            const src = m[2].trim();
            fallbackRefs.push({ index: idx, source: src, links: [{ label: src, url: `/references/${src}` }] });
          }
        }
        if (fallbackRefs.length) appendCitationFooter(assistantNode, fallbackRefs, null);
      }
      if (suggestionsHTML) {
        const b = currentMessageTextNode(assistantNode);
        b.insertAdjacentHTML("beforeend", suggestionsHTML);
      } else {
        // Fallback: AI didn't output suggestions, generate defaults based on the user message
        const fallback = generateFallbackSuggestions(message);
        const fallbackHTML = `<div class="suggestion-chips">` + fallback.map(q => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${q}</button>`).join('') + `</div>`;
        const b = currentMessageTextNode(assistantNode);
        b.insertAdjacentHTML("beforeend", fallbackHTML);
      }
      if (finalAnswer.trim()) {
        state.chatHistory.push({ role: "assistant", content: finalAnswer });
        state.chatHistory = state.chatHistory.slice(-80);
      }
      state.agentContextKey = contextKey;
      await persistActiveThread();
      scrollMessagesToBottom();
    }
    await fetchStatus();
  } catch (error) {
    addMessage("assistant", `处理失败：${error.message}`);
    state.chatHistory.push({ role: "assistant", content: `处理失败：${error.message}` });
    state.chatHistory = state.chatHistory.slice(-80);
    await persistActiveThread();
  } finally {
    setChatBusy(false);
    els.chatInput.focus();
    processNextQueuedChat();
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
  loadAgentMemory().catch(() => {});
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

if (els.refreshAgentMemory) {
  els.refreshAgentMemory.addEventListener("click", () => {
    loadAgentMemory().catch((error) => {
      if (els.agentMemoryList) els.agentMemoryList.textContent = error.message || String(error);
    });
  });
}

if (els.agentMemoryList) {
  els.agentMemoryList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-delete-memory]");
    if (!button) return;
    button.disabled = true;
    deleteAgentMemory(button.dataset.deleteMemory).catch((error) => {
      button.disabled = false;
      if (els.aiConfigStatus) els.aiConfigStatus.textContent = error.message || String(error);
    });
  });
}

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
            <p style="color: #10b981; font-weight: bold; font-size: 16px; margin-bottom: 16px;">飞书表格子表已成功生成！</p>
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
  if (state.chatBusy) {
    enqueueChatMessage(text);
    return;
  }
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
  startNewChatThread();
});

if (els.toggleChatThreadsButton && els.chatWorkspace) {
  els.toggleChatThreadsButton.addEventListener("click", () => {
    setChatSidebarCollapsed(!els.chatWorkspace.classList.contains("is-sidebar-collapsed"));
  });
}

if (els.collapseChatThreadsButton) {
  els.collapseChatThreadsButton.addEventListener("click", () => {
    setChatSidebarCollapsed(true);
  });
}

if (els.newChatThreadButton) {
  els.newChatThreadButton.addEventListener("click", startNewChatThread);
}

if (els.chatThreadList) {
  els.chatThreadList.addEventListener("click", (event) => {
    const item = event.target.closest(".chat-thread-item");
    if (!item) return;
    const threadId = item.dataset.threadId;
    if (event.target.closest(".chat-thread-pin")) {
      event.preventDefault();
      const thread = state.chatThreads.find((entry) => entry.id === threadId);
      pinChatThread(threadId, !(thread && thread.pinned));
      return;
    }
    if (event.target.closest(".chat-thread-delete")) {
      event.preventDefault();
      deleteChatThread(threadId);
      return;
    }
    openChatThread(threadId);
    if (window.matchMedia("(max-width: 720px)").matches) setChatSidebarCollapsed(true);
  });
}

if (els.chatThreadSearchInput) {
  els.chatThreadSearchInput.addEventListener("input", () => {
    state.chatThreadSearch = els.chatThreadSearchInput.value;
    renderChatThreadList();
  });
}

if (els.chatQueueList) {
  els.chatQueueList.addEventListener("click", (event) => {
    const action = event.target.dataset.action;
    const item = event.target.closest(".queued-message-item");
    if (!action || !item) return;
    const queueId = item.dataset.queueId;
    const queued = state.chatQueue.find((entry) => entry.id === queueId);
    if (!queued) return;
    if (action === "remove") {
      state.chatQueue = state.chatQueue.filter((entry) => entry.id !== queueId);
      renderChatQueue();
      return;
    }
    if (action === "edit") {
      els.chatInput.value = queued.message;
      state.chatQueue = state.chatQueue.filter((entry) => entry.id !== queueId);
      renderChatQueue();
      resizeChatInput();
      els.chatInput.focus();
    }
  });
}

if (els.webSearchToggle) {
  renderWebSearchToggle();
  els.webSearchToggle.addEventListener("click", () => {
    if (state.chatBusy) return;
    state.webSearchEnabled = !state.webSearchEnabled;
    renderWebSearchToggle();
    els.chatInput.focus();
  });
}

if (els.thinkingToggle) {
  renderThinkingToggle();
  els.thinkingToggle.addEventListener("click", () => {
    if (state.chatBusy) return;
    state.thinkingEnabled = !state.thinkingEnabled;
    renderThinkingToggle();
    els.chatInput.focus();
  });
}

if (els.skillToggle) {
  renderSkillToggle();
  loadAgentSkills();
  els.skillToggle.addEventListener("click", () => {
    if (state.chatBusy || !els.skillMenu) return;
    els.skillMenu.hidden = !els.skillMenu.hidden;
    renderSkillToggle();
  });
}

if (els.databaseToggle) {
  renderDatabaseToggle();
  loadAgentDatasets();
  els.databaseToggle.addEventListener("click", () => {
    if (state.chatBusy || !els.databaseMenu) return;
    els.databaseMenu.hidden = !els.databaseMenu.hidden;
    renderDatabaseToggle();
  });
}

if (els.knowledgeUploadInput) {
  els.knowledgeUploadInput.addEventListener("change", () => {
    const file = els.knowledgeUploadInput.files && els.knowledgeUploadInput.files[0];
    uploadKnowledgeFile(file);
  });
}

if (els.skillMenu) {
  els.skillMenu.addEventListener("click", (event) => {
    event.stopPropagation();
    const expand = event.target.closest(".option-expand");
    if (expand) {
      const option = expand.closest(".skill-option");
      const skillId = option && option.dataset.skillId;
      if (!skillId) return;
      if (state.expandedSkillIds.has(skillId)) state.expandedSkillIds.delete(skillId);
      else state.expandedSkillIds.add(skillId);
      renderSkillMenu();
      return;
    }
    const option = event.target.closest(".skill-option");
    if (!option || state.chatBusy) return;
    const skillId = option.dataset.skillId;
    if (!skillId) return;
    state.skillSelectionTouched = true;
    if (state.selectedSkillIds.has(skillId)) state.selectedSkillIds.delete(skillId);
    else state.selectedSkillIds.add(skillId);
    renderSkillMenu();
    els.chatInput.focus();
  });
}

if (els.databaseMenu) {
  els.databaseMenu.addEventListener("click", (event) => {
    event.stopPropagation();
    const uploadAction = event.target.closest(".database-upload-action");
    if (uploadAction) {
      if (state.chatBusy || state.knowledgeUploadBusy || !els.knowledgeUploadInput) return;
      els.knowledgeUploadInput.click();
      return;
    }
    const expand = event.target.closest(".option-expand");
    if (expand) {
      const option = expand.closest(".database-option");
      const datasetId = option && option.dataset.datasetId;
      if (!datasetId) return;
      if (state.expandedDatasetIds.has(datasetId)) state.expandedDatasetIds.delete(datasetId);
      else state.expandedDatasetIds.add(datasetId);
      renderDatabaseMenu();
      return;
    }
    const option = event.target.closest(".database-option");
    if (!option || state.chatBusy) return;
    const datasetId = option.dataset.datasetId;
    if (!datasetId) return;
    state.datasetSelectionTouched = true;
    if (state.selectedDatasetIds.has(datasetId)) state.selectedDatasetIds.delete(datasetId);
    else state.selectedDatasetIds.add(datasetId);
    renderDatabaseMenu();
    els.chatInput.focus();
  });
}

document.addEventListener("click", (event) => {
  if (!els.skillMenu || els.skillMenu.hidden) return;
  if (event.target.closest(".skill-picker")) return;
  els.skillMenu.hidden = true;
  renderSkillToggle();
});

document.addEventListener("click", (event) => {
  if (!els.databaseMenu || els.databaseMenu.hidden) return;
  if (event.target.closest(".database-picker")) return;
  els.databaseMenu.hidden = true;
  renderDatabaseToggle();
});

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message) return;
  els.chatInput.value = "";
  resizeChatInput();
  if (state.chatBusy) {
    enqueueChatMessage(message);
    els.chatInput.focus();
    return;
  }
  sendChat(message);
});

els.chatInput.addEventListener("input", resizeChatInput);

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  els.chatForm.requestSubmit();
});

setClock();
setInterval(setClock, 30000);
loadChatThreads();
fetchStatus().catch((error) => {
  setLog(`初始化失败：${error.message}`);
});
setInterval(() => fetchStatus().catch(console.error), 10000);

// Citation Popover Logic
let citationPopover = document.createElement("div");
citationPopover.className = "citation-popover";
document.body.appendChild(citationPopover);
