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
  webSearchEnabled: true,
  agentSkills: [],
  selectedSkillIds: new Set(),
  expandedSkillIds: new Set(),
  skillSelectionTouched: false,
  agentDatasets: [],
  selectedDatasetIds: new Set(),
  expandedDatasetIds: new Set(),
  datasetSelectionTouched: false,
  knowledgeUploadBusy: false,
  knowledgeUploadOpen: false,
  knowledgeUploadFile: null,
  chatModels: [],
  chatModel: "",
  chatAiConfig: null,
  chatImageAttachment: null,
  chatImageAnalysisBusy: false,
  knowledgeUploadMeta: {
    title: "",
    summary: "",
    scope: "",
    tags: "",
    sourceType: "user_uploaded_file",
    quality: "",
  },
  pendingChatApproval: null,
  chatHistory: [],
  chatThreads: [],
  activeThreadId: null,
  chatQueue: [],
  chatThreadSearch: "",
  chatThreadSearchOpen: false,
  agentContextKey: "",
  loadedSkillIds: new Set(),
  chatAbortController: null,
  chatStopRequested: false,
  chatAutoScroll: true,
  crawlRuns: [],
  activeCrawlRunId: null,
  crawlLogPollTimer: null,
  crawlLogPollBusy: false,
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
  fetchAiModels: document.querySelector("#fetchAiModels"),
  aiModelHint: document.querySelector("#aiModelHint"),
  aiConfigStatus: document.querySelector("#aiConfigStatus"),
  agentMemoryList: document.querySelector("#agentMemoryList"),
  refreshAgentMemory: document.querySelector("#refreshAgentMemory"),
  clearLogButton: document.querySelector("#clearLogButton"),
  refreshCrawlRunsButton: document.querySelector("#refreshCrawlRunsButton"),
  crawlRunList: document.querySelector("#crawlRunList"),
  logRunTitle: document.querySelector("#logRunTitle"),
  clearChatButton: document.querySelector("#clearChatButton"),
  toggleChatThreadsButton: document.querySelector("#toggleChatThreadsButton"),
  collapseChatThreadsButton: document.querySelector("#collapseChatThreadsButton"),
  newChatThreadButton: document.querySelector("#newChatThreadButton"),
  chatWorkspace: document.querySelector("#chatWorkspace"),
  chatThreadSidebar: document.querySelector("#chatThreadSidebar"),
  chatThreadSearchToggle: document.querySelector("#chatThreadSearchToggle"),
  chatThreadSearchInput: document.querySelector("#chatThreadSearchInput"),
  chatThreadList: document.querySelector("#chatThreadList"),
  chatQueueList: document.querySelector("#chatQueueList"),
  chatApprovalBar: document.querySelector("#chatApprovalBar"),
  chatFab: document.querySelector("#chatFab"),
  chatModal: document.querySelector("#chatModal"),
  closeChatButton: document.querySelector("#closeChatButton"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
  composerPlusButton: document.querySelector("#composerPlusButton"),
  composerPlusMenu: document.querySelector("#composerPlusMenu"),
  composerUploadFileButton: document.querySelector("#composerUploadFileButton"),
  composerUploadImageButton: document.querySelector("#composerUploadImageButton"),
  chatImageInput: document.querySelector("#chatImageInput"),
  chatAttachmentPreview: document.querySelector("#chatAttachmentPreview"),
  chatModelPicker: document.querySelector("#chatModelPicker"),
  chatModelButton: document.querySelector("#chatModelButton"),
  chatModelButtonLabel: document.querySelector("#chatModelButtonLabel"),
  chatModelMenu: document.querySelector("#chatModelMenu"),
  chatModelMenuHint: document.querySelector("#chatModelMenuHint"),
  chatModelSearch: document.querySelector("#chatModelSearch"),
  chatModelOptions: document.querySelector("#chatModelOptions"),
  chatModelSelect: document.querySelector("#chatModelSelect"),
  skillToggle: document.querySelector("#skillToggle"),
  skillMenu: document.querySelector("#skillMenu"),
  databaseToggle: document.querySelector("#databaseToggle"),
  databaseMenu: document.querySelector("#databaseMenu"),
  knowledgeUploadButton: document.querySelector("#knowledgeUploadButton"),
  knowledgeUploadInput: document.querySelector("#knowledgeUploadInput"),
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

function showTaskOperationNotice(message) {
  let notice = document.getElementById("taskActionNotice");
  if (!notice) {
    notice = document.createElement("div");
    notice.id = "taskActionNotice";
    notice.className = "task-action-notice";
    notice.setAttribute("role", "alert");
    document.body.appendChild(notice);
  }
  notice.textContent = message;
  notice.classList.add("is-visible");
  clearTimeout(state.taskBusyNoticeTimer);
  state.taskBusyNoticeTimer = setTimeout(() => notice.classList.remove("is-visible"), 3600);
}

function ensureTaskBusyInteraction() {
  if (state.taskBusyInteractionReady) return;
  state.taskBusyInteractionReady = true;
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-blocked-reason]");
    const message = button?.dataset.blockedReason || "";
    if (!message) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    showTaskOperationNotice(message);
  }, true);
}

function setTaskButtonState(button, { active, reason, idleLabel, activeLabel }) {
  if (!button) return;
  button.disabled = false;
  button.dataset.blockedReason = reason || "";
  button.classList.toggle("is-task-loading", active);
  button.classList.toggle("is-task-blocked", Boolean(reason));
  button.setAttribute("aria-disabled", reason ? "true" : "false");
  button.setAttribute("aria-busy", active ? "true" : "false");
  button.title = reason || "";
  button.textContent = active ? activeLabel : idleLabel;
}

function setBusy(value, label = "运行中", action = "all") {
  ensureTaskBusyInteraction();
  state.busyActions ||= { crawl: false, generate: false, performance: false };
  state.busyStartedAt ||= {};
  const normalizedAction = action === "report" ? "generate" : action;
  const actionNames = normalizedAction === "all"
    ? ["crawl", "generate", "performance"]
    : [normalizedAction];
  actionNames.forEach((name) => {
    if (!(name in state.busyActions)) return;
    state.busyActions[name] = value;
    if (value) state.busyStartedAt[name] ||= Date.now();
    else delete state.busyStartedAt[name];
  });

  const crawlBusy = state.busyActions.crawl;
  const weeklyBusy = state.busyActions.generate;
  const performanceBusy = state.busyActions.performance;
  const reportBusy = weeklyBusy || performanceBusy;
  const anyBusy = crawlBusy || reportBusy;
  state.busy = crawlBusy;

  const weeklyReason = weeklyBusy
    ? "周报正在生成，系统已阻止重复启动。"
    : crawlBusy
      ? "爬虫正在运行。周报需等待本轮爬取完成，以免读取正在改写的半成品数据。"
      : "";
  const performanceReason = performanceBusy
    ? "业绩摘要正在生成，系统已阻止重复启动。"
    : crawlBusy
      ? "爬虫正在运行。业绩摘要需等待本轮爬取完成，以免读取正在改写的半成品数据。"
      : "";
  const crawlReason = crawlBusy
    ? "爬虫正在运行，系统已阻止重复启动。"
    : reportBusy
      ? "报告正在生成。为保证报告使用稳定数据，报告完成前不能启动爬虫。"
      : "";

  els.generateButtons.forEach((button) => setTaskButtonState(button, {
    active: weeklyBusy,
    reason: weeklyReason,
    idleLabel: "生成周报",
    activeLabel: "周报生成中",
  }));
  setTaskButtonState(els.generateButtonSecondary, {
    active: weeklyBusy,
    reason: weeklyReason,
    idleLabel: "生成周报",
    activeLabel: "周报生成中",
  });
  setTaskButtonState(els.generatePerformanceButton, {
    active: performanceBusy,
    reason: performanceReason,
    idleLabel: "生成业绩摘要",
    activeLabel: "业绩摘要生成中",
  });
  els.crawlButtons.forEach((button) => setTaskButtonState(button, {
    active: crawlBusy,
    reason: crawlReason,
    idleLabel: "重新爬取",
    activeLabel: "爬虫运行中",
  }));

  if (els.aiSettingsButton) {
    setTaskButtonState(els.aiSettingsButton, {
      active: false,
      reason: anyBusy ? "任务运行中，为避免模型配置中途变化，请在任务完成后修改 AI 设置。" : "",
      idleLabel: els.aiSettingsButton.dataset.idleLabel || els.aiSettingsButton.textContent,
      activeLabel: "",
    });
    els.aiSettingsButton.dataset.idleLabel ||= els.aiSettingsButton.textContent;
  }

  if (crawlBusy) els.runState.textContent = label || "爬虫运行中";
  else if (weeklyBusy && performanceBusy) els.runState.textContent = "周报与业绩摘要并行生成中";
  else if (weeklyBusy) els.runState.textContent = "周报生成中";
  else if (performanceBusy) els.runState.textContent = "业绩摘要生成中";
  else els.runState.textContent = "准备就绪";

  els.logButton.classList.toggle("log-glowing", anyBusy);
}

function setChatBusy(value) {
  state.chatBusy = value;
  els.chatSubmitButton.disabled = false;
  els.chatInput.disabled = false;
  if (els.webSearchToggle) els.webSearchToggle.disabled = false;
  if (els.skillToggle) els.skillToggle.disabled = false;
  if (els.databaseToggle) els.databaseToggle.disabled = false;
  if (els.knowledgeUploadButton) els.knowledgeUploadButton.disabled = state.knowledgeUploadBusy;
  els.chatSubmitButton.classList.toggle("is-pausing", value);
  els.chatSubmitButton.setAttribute("aria-label", value ? "暂停生成" : "发送");
  els.chatSubmitButton.title = value ? "暂停生成" : "发送";
  els.chatSubmitButton.innerHTML = value
    ? `<svg viewBox="0 0 24 24" aria-hidden="true" class="chat-submit-icon"><path d="M7 5h4v14H7z"></path><path d="M13 5h4v14h-4z"></path></svg><span class="sr-only">暂停生成</span>`
    : `<span>发送</span>`;
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

function modelSupportsImages(modelName) {
  return /(?:vision|multimodal|omni|(?:^|[-_.])vl(?:[-_.]|$)|qwen[^/]*vl|internvl|llava|gpt-4o|gpt-4\.1|gemini|claude-3|kimi[-_.]?k2\.5)/i.test(String(modelName || ""));
}

function isConversationalModel(modelName) {
  const value = String(modelName || "").trim().toLowerCase();
  if (!value) return false;
  if (/(?:embedding|rerank|(?:^|[/_.-])bge(?:[/_.-]|$)|ocr|asr|tts|text-to-speech|speech-to-text|deprecated|voxcpm|whisper)/i.test(value)) return false;
  return /(?:deepseek|qwen|glm|kimi|minimax|gpt|claude|gemini|llama|mistral|internlm|baichuan|chat|instruct|thinking|reason|code|omni|(?:^|[/_.-])vl(?:[/_.-]|$))/i.test(value);
}

function visibleChatModels() {
  return state.chatModels.filter(isConversationalModel);
}

function chatModelTags(modelName) {
  const value = String(modelName || "").trim();
  const normalized = value.toLowerCase();
  const tags = [];
  if (modelSupportsImages(value)) tags.push("多模态");
  if (/(?:deepseek-r1|qwen3-[^/]*thinking)/i.test(value)) tags.push("推理");
  if (/(?:deepseek-v4)/i.test(value) || /^dict\/qwen3-(?:1\.7b|4b|14b)$/i.test(value)) tags.push("混合");
  if (/(?:code|coder|coding)/i.test(value) || normalized === "minimax-m2.1") tags.push("编码");
  if (!tags.length) tags.push("文本");
  return tags;
}

function renderChatModelOptions() {
  if (!els.chatModelOptions) return;
  const models = visibleChatModels();
  els.chatModelOptions.innerHTML = models.length ? models.map((model) => {
    const active = model === state.chatModel;
    const tags = chatModelTags(model).map((tag) => `<span class="chat-model-tag" data-tag="${tag}">${tag}</span>`).join("");
    return `<button class="chat-model-option${active ? " active" : ""}" type="button" role="option" aria-selected="${active}" data-model="${escapeHtml(model)}"><strong>${escapeHtml(model)}</strong><span class="chat-model-tags">${tags}</span><span class="chat-model-check">${active ? "✓" : ""}</span></button>`;
  }).join("") : '<div class="chat-model-empty">没有匹配的语言模型</div>';
}

function renderChatModelControls() {
  if (els.chatModelSelect) {
    const models = visibleChatModels().length ? visibleChatModels() : [state.chatModel || "未配置模型"];
    els.chatModelSelect.innerHTML = models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
    els.chatModelSelect.value = models.includes(state.chatModel) ? state.chatModel : models[0];
    if (els.chatModelButtonLabel) els.chatModelButtonLabel.textContent = state.chatModel || models[0];
    renderChatModelOptions();
  }
  const supportsImages = modelSupportsImages(state.chatModel);
  if (els.composerUploadImageButton) {
    els.composerUploadImageButton.disabled = !supportsImages || state.chatImageAnalysisBusy;
    els.composerUploadImageButton.title = supportsImages ? "上传图片并由当前模型理解" : "当前模型未声明视觉能力";
    const hint = els.composerUploadImageButton.querySelector("small");
    if (hint) hint.textContent = supportsImages ? "PNG、JPG、WebP、GIF" : "当前模型不支持";
  }
}

function renderChatAttachment() {
  if (!els.chatAttachmentPreview) return;
  const attachment = state.chatImageAttachment;
  els.chatAttachmentPreview.hidden = !attachment;
  els.chatAttachmentPreview.innerHTML = attachment ? `
    <span class="chat-attachment-chip">
      <img src="${attachment.previewDataUrl || attachment.dataUrl}" alt="待发送图片预览" />
      <span><strong>${escapeHtml(attachment.name)}</strong><small>${formatBytes(attachment.size)}</small></span>
      <button type="button" id="removeChatImage" aria-label="移除图片">&times;</button>
    </span>` : "";
}

function createChatImagePreview(dataUrl, maxEdge = 480) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      const scale = Math.min(1, maxEdge / Math.max(image.naturalWidth || 1, image.naturalHeight || 1));
      const canvas = document.createElement("canvas");
      canvas.width = Math.max(1, Math.round((image.naturalWidth || 1) * scale));
      canvas.height = Math.max(1, Math.round((image.naturalHeight || 1) * scale));
      const context = canvas.getContext("2d");
      if (!context) {
        resolve(dataUrl);
        return;
      }
      context.drawImage(image, 0, 0, canvas.width, canvas.height);
      try {
        resolve(canvas.toDataURL("image/webp", 0.8));
      } catch (_error) {
        resolve(dataUrl);
      }
    };
    image.onerror = () => resolve(dataUrl);
    image.src = dataUrl;
  });
}

async function loadChatModelOptions() {
  const configResponse = await fetch("/api/ai-config", { cache: "no-store" });
  const configData = await configResponse.json();
  if (!configData.ok) throw new Error(configData.error || "AI 设置加载失败");
  state.chatAiConfig = configData.config;
  state.chatModel = String(configData.config.model || "");
  state.chatModels = state.chatModel ? [state.chatModel] : [];
  renderChatModelControls();
  try {
    const response = await fetch("/api/ai-models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: configData.config.base_url, api_key: "" }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "模型列表获取失败");
    state.chatModels = Array.isArray(data.models) ? data.models : state.chatModels;
    if (state.chatModel && !state.chatModels.includes(state.chatModel)) state.chatModels.unshift(state.chatModel);
  } catch (error) {
    console.warn("聊天模型列表加载失败，保留当前模型", error);
  }
  renderChatModelControls();
}

async function switchChatModel(model) {
  if (!model || model === state.chatModel || !state.chatAiConfig) return;
  const response = await fetch("/api/ai-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      provider: state.chatAiConfig.provider,
      base_url: state.chatAiConfig.base_url,
      model,
      api_key: "",
    }),
  });
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "模型切换失败");
  state.chatAiConfig = data.config;
  state.chatModel = model;
  state.chatImageAttachment = modelSupportsImages(model) ? state.chatImageAttachment : null;
  renderChatModelControls();
  renderChatAttachment();
}

async function analyzeChatImage(attachment, question) {
  state.chatImageAnalysisBusy = true;
  renderChatModelControls();
  try {
    const response = await fetch("/api/chat-image-analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image: attachment.dataUrl, filename: attachment.name, question, model: state.chatModel }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "图片理解失败");
    return String(data.description || "").trim();
  } finally {
    state.chatImageAnalysisBusy = false;
    renderChatModelControls();
  }
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
  const uploadMeta = state.knowledgeUploadMeta || {};
  const uploadFileName = state.knowledgeUploadFile ? state.knowledgeUploadFile.name : "";
  const uploadAction = `
    <div class="database-upload-panel ${state.knowledgeUploadOpen ? "is-open" : ""} ${state.knowledgeUploadBusy ? "is-loading" : ""}">
      <button class="database-upload-action" id="knowledgeUploadButton" type="button" ${state.knowledgeUploadBusy ? "disabled" : ""} aria-expanded="${state.knowledgeUploadOpen ? "true" : "false"}">
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 3v12"></path>
          <path d="m7 8 5-5 5 5"></path>
          <path d="M5 21h14"></path>
          <path d="M6 17h12"></path>
        </svg>
        <span>
          <strong>上传文件作为知识库</strong>
          <small>补充名称和说明后上传，AI 才能按正确口径检索</small>
        </span>
        <b>${state.knowledgeUploadOpen ? "▴" : "▾"}</b>
      </button>
      ${state.knowledgeUploadOpen ? `
        <div class="database-upload-form" id="knowledgeUploadForm">
          <label>
            <span>知识库名称 <em>必填</em></span>
            <input data-upload-field="title" type="text" maxlength="80" placeholder="例如：2026年竞对补充数据" value="${escapeHtml(uploadMeta.title || "")}">
          </label>
          <label>
            <span>知识库说明 <em>必填</em></span>
            <textarea data-upload-field="summary" maxlength="600" rows="2" placeholder="说明这批文件覆盖的主体、时间、指标和用途">${escapeHtml(uploadMeta.summary || "")}</textarea>
          </label>
          <label>
            <span>范围/口径 <small>选填</small></span>
            <textarea data-upload-field="scope" maxlength="600" rows="2" placeholder="例如：只含公开披露数据；金额单位为百万元人民币">${escapeHtml(uploadMeta.scope || "")}</textarea>
          </label>
          <div class="database-upload-grid">
            <label>
              <span>标签/关键词 <small>选填</small></span>
              <input data-upload-field="tags" type="text" maxlength="240" placeholder="逗号分隔，例如 CMHK, 5G, 季度收入" value="${escapeHtml(uploadMeta.tags || "")}">
            </label>
            <label>
              <span>来源类型 <small>选填</small></span>
              <select data-upload-field="sourceType">
                <option value="user_uploaded_file" ${(uploadMeta.sourceType || "user_uploaded_file") === "user_uploaded_file" ? "selected" : ""}>用户上传文件</option>
                <option value="official_public" ${uploadMeta.sourceType === "official_public" ? "selected" : ""}>官方/公开来源</option>
                <option value="internal_working_file" ${uploadMeta.sourceType === "internal_working_file" ? "selected" : ""}>内部工作文件</option>
              </select>
            </label>
          </div>
          <label>
            <span>质量/备注 <small>选填</small></span>
            <input data-upload-field="quality" type="text" maxlength="600" placeholder="例如：已人工核验；仍需复核；含估算值" value="${escapeHtml(uploadMeta.quality || "")}">
          </label>
          <div class="database-upload-file">
            <button class="database-upload-file-button" id="knowledgeUploadChooseFile" type="button" ${state.knowledgeUploadBusy ? "disabled" : ""}>选择文件</button>
            <span>${uploadFileName ? escapeHtml(uploadFileName) : "尚未选择文件"}</span>
          </div>
          <div class="database-upload-actions">
            <button class="database-upload-submit" id="knowledgeUploadSubmit" type="button" ${state.knowledgeUploadBusy ? "disabled" : ""}>${state.knowledgeUploadBusy ? "上传中..." : "上传并选中"}</button>
          </div>
        </div>
      ` : ""}
    </div>
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
  if (state.knowledgeUploadBusy) return;
  if (!file) {
    addMessage("assistant", "请先选择要上传的知识库文件。");
    return;
  }
  const meta = state.knowledgeUploadMeta || {};
  const title = String(meta.title || "").trim();
  const summary = String(meta.summary || "").trim();
  if (!title || !summary) {
    addMessage("assistant", "上传知识库前请先填写「知识库名称」和「知识库说明」。");
    return;
  }
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
        title,
        summary,
        scope: String(meta.scope || "").trim(),
        tags: String(meta.tags || "").trim(),
        sourceType: String(meta.sourceType || "user_uploaded_file").trim(),
        quality: String(meta.quality || "").trim(),
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
    state.knowledgeUploadOpen = false;
    state.knowledgeUploadFile = null;
    state.knowledgeUploadMeta = {
      title: "",
      summary: "",
      scope: "",
      tags: "",
      sourceType: "user_uploaded_file",
      quality: "",
    };
    renderDatabaseMenu();
    addMessage("assistant", `已上传「${title}」并作为本轮已选择数据库，可直接向小竞AI提问。`);
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
    trigger_report_generation: "生成报告",
    render_python_chart: "生成图表",
    get_system_status: "系统状态",
    read_agent_skill: "读取 Agent Skill",
    search_chat_history: "搜索历史聊天",
    search_agent_memory: "搜索长期记忆",
    remember_agent_memory: "写入长期记忆",
    list_agent_memory: "查看长期记忆",
    forecast_quarterly_metric: "季度趋势预测",
    list_database_lineage: "查看数据库血缘",
    list_report_outputs: "查看报告输出",
  };
  return labels[name] || name || "工具";
}

function toolNarrationText(toolName) {
  return "";
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
            font: { size: 11, family: 'Inter, sans-serif' },
            generateLabels: (chart) => Chart.defaults.plugins.legend.labels.generateLabels(chart).map((item, index) => {
              const datasetIndex = Number.isInteger(item.datasetIndex) ? item.datasetIndex : index;
              const value = Number(chart.data.datasets[datasetIndex]?.data?.[0] || 0);
              return { ...item, text: `${item.text} ${value}` };
            })
          }
        },
        datalabels: {
          color: '#ffffff',
          anchor: 'center',
          align: 'center',
          font: { weight: '700', size: 11, family: 'Inter, sans-serif' },
          formatter: (value, context) => value > 0 ? `${context.dataset.label} ${value}` : "",
          display: (context) => {
            const value = Number(context.dataset.data[context.dataIndex] || 0);
            const total = context.chart.data.datasets.reduce(
              (sum, dataset) => sum + Number(dataset.data[context.dataIndex] || 0),
              0
            );
            const availableWidth = Number(context.chart.chartArea?.width || context.chart.width || 0);
            return value > 0 && total > 0 && (value / total) * availableWidth >= 88;
          }
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
  // Unified task history is the only log surface while this dialog is open.
  // Streaming text is persisted by the backend and rendered from the selected
  // task, so appending it here would create an orphan block below the archive.
  if (crawlLogModalIsOpen()) return;
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

const TRACE_AUDIT_GUIDE = Object.freeze({
  "多 Agent 编排器": {
    audit: "调度本轮抓取后的完整审核流程，监控工具和模型是否正常返回。",
    next: "继续执行当前审核节点；全部节点完成后汇总发布结果。",
  },
  "证据接收": {
    audit: "核对本轮抓取到的原始指标证据、缓存命中和待审核任务范围。",
    next: "按来源可信度进行分类。",
  },
  "来源分类": {
    audit: "区分官方来源、公开来源、商业来源和缺失来源，确认后续证据等级。",
    next: "从证据原文中抽取公司、指标和具体事实。",
  },
  "事实抽取": {
    audit: "逐条检查公司、指标和值是否能从原文直接提取，并保留支持依据。",
    next: "校验事实是否归属于正确主体和指标。",
  },
  "主体校验": {
    audit: "检查公司主体、指标口径和事实归属，拦截张冠李戴或指标错配。",
    next: "进入质量门禁，决定可发布、待复核或拒绝。",
  },
  "质量审计": {
    audit: "检查证据是否覆盖结论、字段是否完整、质量是否达到发布门槛。",
    next: "检查同一事实是否存在来源冲突。",
  },
  "冲突仲裁": {
    audit: "比较同一主体和指标的多条事实，识别数值、期间或口径冲突。",
    next: "通过联网与多来源多数口径进行复核。",
  },
  "搜索验证": {
    audit: "对已通过的事实进行多来源验证，记录纠正、冲突和待复核项。",
    next: "汇总仍缺少证据的事实并制定补爬计划。",
  },
  "缺口规划": {
    audit: "识别未覆盖字段和证据缺口，判断哪些行值得定向补爬。",
    next: "由编排器决定补爬或直接发布。",
  },
  "编排决策": {
    audit: "综合质量门禁、证据缺口和补爬收益，决定下一步动作。",
    next: "按决定执行定向补爬，或进入发布。",
  },
  "定向补爬": {
    audit: "只重跑被选中的缺口行，检查新增证据是否补齐目标字段。",
    next: "将补爬结果重新送入整理和质量审核。",
  },
  "发布": {
    audit: "汇总最终通过、待复核、拒绝和证据缺口，写入正式发布层。",
    next: "同步审计记录并结束本轮。",
  },
  "飞书审计日志": {
    audit: "把本轮审核步骤、依据和最终结果写入对应飞书日志页并回读校验。",
    next: "本轮结束，可在历史运行中复查。",
  },
});

const TRACE_FIELD_LABELS = Object.freeze({
  tasks: "原始证据",
  task_count: "本批数量",
  cached: "缓存命中",
  cache_reused: "复用判断",
  deterministic: "规则抽取",
  deterministic_extracted: "规则抽取",
  pending: "待模型抽取",
  returned: "返回结果",
  candidates: "候选事实",
  accepted: "可发布",
  review: "待复核",
  rejected: "未发布",
  unpublished: "未发布",
  evidence_gaps: "证据缺口",
  quality_rejected: "质量拒绝",
  pre_rejected: "归属异常",
  gaps: "缺口数量",
  conflicts: "冲突数量",
  checked: "核验数量",
  corrected: "纠正数量",
  online_checked: "联网核验",
  online_votes: "多数口径票数",
  online_search: "联网搜索",
  online_ai: "内部模型",
  online_ai_used: "内部模型已使用",
  online_batches: "在线模型批次",
  fallback_batches: "本地降级批次",
  source_tiers: "来源分级",
  official: "官方来源",
  public: "公开来源",
  commercial: "商业来源",
  missing: "缺失来源",
  batch: "处理批次",
  sample: "抽样明细",
  company: "公司",
  entity: "主体",
  metric: "审核指标",
  value: "提取结果",
  basis: "原文依据",
  note: "备注",
  status: "状态",
  confidence: "置信度",
  entity_supported: "主体有依据",
  metric_supported: "指标有依据",
  value_supported: "结果有依据",
  workers: "并行任务",
  parallel_workers: "并行任务",
  ai_workers: "模型并行数",
  batch_size: "单批数量",
  rows: "目标行",
  selected_rows: "选中行",
  rejected_rows: "未选中行",
  executed_rows: "已补爬行",
  recrawl_tasks: "补爬任务",
  recrawl_rows: "补爬行",
  recrawl_performed: "已执行补爬",
  action: "执行动作",
  reason: "决策原因",
  max_rows: "最多补爬行",
  returncode: "返回码",
  ok: "执行成功",
  targets: "写入位置",
  durationMs: "耗时",
  duration_ms: "耗时",
  workflow: "审核流程",
  limit: "读取上限",
  cache_schema: "缓存版本",
  preserved_previous_facts: "保留历史事实",
  best_accepted_count: "当前最佳通过数",
  completed_at: "完成时间",
  started_at: "开始时间",
  run_id: "审核运行编号",
});

const TRACE_TECHNICAL_FIELDS = new Set([
  "command",
  "processId",
  "stderr_tail",
  "stdout_tail",
  "tool_calls",
  "protected_semantic_keys",
  "node_events",
  "extra",
]);

function traceAuditValue(events, keys) {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const event = events[index] || {};
    for (const payload of [event.output, event.result, event.input]) {
      if (!payload || typeof payload !== "object" || Array.isArray(payload)) continue;
      for (const key of keys) {
        if (payload[key] !== undefined && payload[key] !== null && payload[key] !== "") {
          return payload[key];
        }
      }
    }
  }
  return null;
}

function traceAuditStatus(events) {
  const latest = events[events.length - 1] || {};
  const latestPhase = latest.phase || latest.event_type || "agent";
  const failed = latest.status === "error"
    || latest.status === "failed"
    || latestPhase === "error"
    || /失败|异常|错误/.test(String(latest.message || ""));
  if (failed) return "attention";
  if (latestPhase === "answer" || latestPhase === "decision") return "done";
  const terminalToolNodes = new Set(["多 Agent 编排器", "搜索验证", "定向补爬", "发布", "飞书审计日志"]);
  if (latestPhase === "tool_result" && terminalToolNodes.has(String(latest.node || ""))) return "done";
  return "running";
}

function traceAuditStatusLabel(status) {
  if (status === "done") return "已完成";
  if (status === "attention") return "需处理";
  return "审核中";
}

function traceCountText(value) {
  if (Array.isArray(value)) return value.join("、");
  if (value && typeof value === "object") return Object.values(value).join("、");
  return value === null || value === undefined ? "" : String(value);
}

function traceAuditSubject(events) {
  const latest = events[events.length - 1] || {};
  const node = String(latest.node || "Agent");
  const guide = TRACE_AUDIT_GUIDE[node] || {
    audit: "检查当前步骤输入、处理依据和输出结果。",
    next: "根据本步骤结果继续后续处理。",
  };
  const tasks = traceAuditValue(events, ["tasks", "candidates", "checked"]);
  const pending = traceAuditValue(events, ["pending", "task_count"]);
  const rows = traceAuditValue(events, ["selected_rows", "executed_rows", "rows"]);
  if (node === "证据接收" && tasks !== null) {
    return "核对本轮 " + traceCountText(tasks) + " 条原始指标证据，以及缓存复用和任务完整性。";
  }
  if (node === "来源分类" && tasks !== null) {
    return "对 " + traceCountText(tasks) + " 条证据按官方、公开、商业和缺失来源进行分级。";
  }
  if (node === "事实抽取") {
    const suffix = pending !== null ? "，其中 " + traceCountText(pending) + " 条需要当前批次处理" : "";
    return "逐条核对公司、指标、提取值和原文依据" + suffix + "。";
  }
  if (node === "搜索验证" && tasks !== null) {
    return "对 " + traceCountText(tasks) + " 条候选事实执行多来源多数口径核验。";
  }
  if (node === "定向补爬" && rows !== null) {
    return "重新抓取第 " + traceCountText(rows) + " 行，检查缺口字段能否补齐。";
  }
  return guide.audit;
}

function traceAuditResult(events, status) {
  const latest = events[events.length - 1] || {};
  const terminal = [...events].reverse().find((event) => {
    const phase = event.phase || event.event_type;
    return ["answer", "decision", "tool_result"].includes(phase);
  });
  if (status === "running") {
    return "正在处理，尚未形成最终结论。当前状态：" + traceFriendlyMessage(latest, latest.phase || latest.event_type || "agent");
  }
  const chosen = terminal || latest;
  return traceFriendlyMessage(chosen, chosen.phase || chosen.event_type || "agent");
}

function traceAuditNext(events, status) {
  const latest = events[events.length - 1] || {};
  const node = String(latest.node || "Agent");
  const guide = TRACE_AUDIT_GUIDE[node] || { next: "根据本步骤结果继续后续处理。" };
  if (status === "attention") return "先查看失败依据并修正问题，再重试本步骤。";
  if (status === "running") return "本步骤完成后，" + guide.next;
  const decisionEvent = [...events].reverse().find((event) => event.decision);
  const decision = decisionEvent ? decisionEvent.decision : "";
  if (decision === "recrawl") return "按选中行执行定向补爬，再重新进入审核。";
  if (decision === "publish") return "无需继续补爬，进入正式发布。";
  return guide.next;
}

function traceHumanStatus(value) {
  const raw = String(value ?? "").toLowerCase();
  const labels = {
    ok: "通过",
    success: "成功",
    accepted: "可发布",
    unavailable: "未找到有效数据",
    review: "待复核",
    rejected: "未通过",
    failed: "失败",
    error: "错误",
    true: "是",
    false: "否",
  };
  return labels[raw] || String(value ?? "-");
}

function traceFieldLabel(key) {
  return TRACE_FIELD_LABELS[key] || String(key).replaceAll("_", " ");
}

function renderAuditValue(value, depth = 0) {
  if (value === null || value === undefined || value === "") return '<span class="audit-empty">-</span>';
  if (typeof value === "boolean") return escapeHtml(value ? "是" : "否");
  if (typeof value === "number") return escapeHtml(String(value));
  if (typeof value === "string") {
    const display = value.length > 1200 ? value.slice(0, 1200) + "…" : value;
    return escapeHtml(display).replace(/\n/g, "<br>");
  }
  if (Array.isArray(value)) {
    if (!value.length) return '<span class="audit-empty">无</span>';
    if (value.every((item) => item && typeof item === "object" && !Array.isArray(item))) {
      return '<div class="agent-audit-sample-list">' + value.slice(0, 12).map((item, index) => {
        const title = item.company || item.entity || item.metric || item.id || ("记录 " + (index + 1));
        const metric = item.metric && item.metric !== title ? '<span>' + escapeHtml(String(item.metric)) + '</span>' : "";
        const status = item.status !== undefined
          ? '<em class="sample-status status-' + escapeHtml(String(item.status)) + '">' + escapeHtml(traceHumanStatus(item.status)) + '</em>'
          : "";
        const body = Object.entries(item)
          .filter(([key, itemValue]) => !["company", "entity", "metric", "id", "status"].includes(key)
            && !TRACE_TECHNICAL_FIELDS.has(key)
            && itemValue !== null
            && itemValue !== undefined
            && itemValue !== "")
          .map(([key, itemValue]) => {
            let shown = itemValue;
            if (key === "confidence" && Number.isFinite(Number(itemValue))) shown = Math.round(Number(itemValue) * 100) + "%";
            return '<div><dt>' + escapeHtml(traceFieldLabel(key)) + '</dt><dd>' + renderAuditValue(shown, depth + 1) + '</dd></div>';
          }).join("");
        return '<article class="agent-audit-sample"><header><strong>' + escapeHtml(String(title)) + '</strong>' + metric + status + '</header><dl>' + body + '</dl></article>';
      }).join("") + (value.length > 12 ? '<p class="audit-more">另有 ' + (value.length - 12) + ' 条未展开。</p>' : "") + '</div>';
    }
    const tag = value.every((item) => typeof item === "string") ? "ol" : "ul";
    return '<' + tag + ' class="agent-audit-list">' + value.slice(0, 30).map((item) => '<li>' + renderAuditValue(item, depth + 1) + '</li>').join("") + '</' + tag + '>';
  }
  if (typeof value === "object") {
    if (depth > 2) return '<pre>' + escapeHtml(compactJson(value)) + '</pre>';
    const entries = Object.entries(value).filter(([key, itemValue]) =>
      !TRACE_TECHNICAL_FIELDS.has(key)
      && itemValue !== null
      && itemValue !== undefined
      && itemValue !== ""
    );
    if (!entries.length) return '<span class="audit-empty">无可展示业务字段</span>';
    return '<dl class="agent-audit-kv">' + entries.map(([key, itemValue]) => {
      let shown = itemValue;
      if (["durationMs", "duration_ms"].includes(key) && Number.isFinite(Number(itemValue))) {
        shown = formatAuditDuration(Number(itemValue));
      }
      return '<div><dt>' + escapeHtml(traceFieldLabel(key)) + '</dt><dd>' + renderAuditValue(shown, depth + 1) + '</dd></div>';
    }).join("") + '</dl>';
  }
  return escapeHtml(String(value));
}

function traceEventPayload(event) {
  const phase = event.phase || event.event_type || "agent";
  if (phase === "tool_result") return event.result ?? event.output ?? null;
  if (phase === "answer") return event.output ?? event.result ?? null;
  if (phase === "tool_call") return event.input ?? null;
  if (phase === "decision") return event.output ?? event.result ?? event.input ?? null;
  return event.input ?? event.output ?? event.result ?? null;
}

function renderAuditEventTimeline(events) {
  return '<div class="agent-audit-timeline">' + events.map((event) => {
    const phase = event.phase || event.event_type || "agent";
    const time = String(event.ts || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "").split(" ").pop() || "-";
    const message = traceFriendlyMessage(event, phase);
    const payload = traceEventPayload(event);
    const tool = event.tool ? '<span class="agent-audit-tool">' + escapeHtml(traceFriendlyTool(event.tool)) + '</span>' : "";
    return '<div class="agent-audit-event"><time>' + escapeHtml(time) + '</time><div><div class="agent-audit-event-heading"><span>' + escapeHtml(tracePhaseLabel(phase)) + '</span>' + tool + '</div><strong>' + escapeHtml(message) + '</strong>' + (payload !== null && payload !== undefined ? '<div class="agent-audit-data">' + renderAuditValue(payload) + '</div>' : "") + '</div></div>';
  }).join("") + '</div>';
}

function formatAuditDuration(value) {
  const milliseconds = Number(value || 0);
  if (!milliseconds) return "-";
  const totalSeconds = Math.round(milliseconds / 1000);
  if (totalSeconds < 60) return totalSeconds + " 秒";
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes + " 分 " + seconds + " 秒";
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

/* Per-record quality audit v2 */
const agentQualityRecordCache = new Map();
const agentQualityViewState = new Map();

function isAgentRecordQualityNode(nodeName) {
  return nodeName === "主体校验" || nodeName === "质量审计";
}

function agentQualityEscape(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, function (character) {
    if (character === "&") return "&amp;";
    if (character === "<") return "&lt;";
    if (character === ">") return "&gt;";
    if (character === '"') return "&quot;";
    return "&#39;";
  });
}

function agentQualityNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function agentQualityPercent(value) {
  const number = agentQualityNumber(value);
  if (number == null) return null;
  const percent = Math.abs(number) <= 1 ? number * 100 : number;
  return Math.round(percent * 10) / 10;
}

function agentQualityScoreMeta(value) {
  const percent = agentQualityPercent(value);
  if (percent == null) return { percent: null, label: "未评分", tone: "unknown" };
  if (percent >= 95) return { percent: percent, label: "优秀", tone: "excellent" };
  if (percent >= 85) return { percent: percent, label: "良好", tone: "good" };
  if (percent >= 70) return { percent: percent, label: "待复核", tone: "review" };
  return { percent: percent, label: "不合格", tone: "rejected" };
}

function agentQualityDecisionMeta(decision) {
  const normalized = String(decision || "").toLowerCase();
  if (normalized === "accepted") return { label: "可发布", tone: "accepted" };
  if (normalized === "review") return { label: "待复核", tone: "review" };
  if (normalized === "rejected") return { label: "已拒绝", tone: "rejected" };
  return { label: "未判定", tone: "unknown" };
}

function agentQualityTierLabel(tier) {
  const labels = {
    official: "官方来源",
    public: "公开来源",
    commercial: "商业来源",
    monitoring: "监测来源",
    missing: "缺少来源",
    unknown: "来源未标记"
  };
  return labels[String(tier || "").toLowerCase()] || String(tier || "来源未标记");
}

function agentQualityRowLabel(rowRef) {
  const text = String(rowRef == null ? "" : rowRef).trim();
  if (!text) return "未关联行";
  if (/^第.*行$/.test(text)) return text;
  return "第 " + text + " 行";
}

function agentQualityNextStep(record) {
  const decision = String(record.decision || "").toLowerCase();
  if (decision === "accepted") return "进入发布结果；后续若来源更新则按该行频次重新审核。";
  if (decision === "review") return "人工核对来源、指标口径与数值有效期，确认后再发布。";
  if (!record.entity_supported || !record.metric_supported) return "修正主体或指标归属后重新审核。";
  if (!record.value_supported || String(record.source_tier || "").toLowerCase() === "missing") {
    return "补充能够覆盖结论的公开证据后重新爬取。";
  }
  return "根据拒绝原因修正数据或证据，再进入质量审计。";
}

function agentQualityCheck(label, passed) {
  return '<span class="agent-quality-check ' + (passed ? "is-pass" : "is-fail") + '">'
    + agentQualityEscape(label) + " " + (passed ? "通过" : "异常") + "</span>";
}

function agentQualitySourceHtml(source, index) {
  const url = String(source && source.url || "").trim();
  const title = String(source && source.title || "").trim();
  const type = String(source && source.type || "").trim();
  const label = title || type || (url ? "来源 " + (index + 1) : "未提供链接");
  if (!url) return '<span class="agent-quality-source is-missing">' + agentQualityEscape(label) + "</span>";
  return '<a class="agent-quality-source" href="' + agentQualityEscape(url)
    + '" target="_blank" rel="noopener noreferrer">' + agentQualityEscape(label) + "</a>";
}

function loadAgentQualityRecords(runId) {
  if (agentQualityRecordCache.has(runId)) return agentQualityRecordCache.get(runId);
  const request = fetch("/api/curation-quality-records?runId=" + encodeURIComponent(runId), {
    cache: "no-store"
  }).then(function (response) {
    return response.json().catch(function () {
      return { ok: false, error: "服务返回了无法解析的内容。" };
    }).then(function (payload) {
      if (!payload.ok) throw new Error(payload.error || "逐条质量明细尚未生成。");
      return payload;
    });
  }).catch(function (error) {
    agentQualityRecordCache.delete(runId);
    throw error;
  });
  agentQualityRecordCache.set(runId, request);
  return request;
}

function agentQualityIssuePriority(record) {
  const decision = String(record.decision || "").toLowerCase();
  if (decision === "rejected") return 0;
  if (decision === "review") return 1;
  if (!record.entity_supported || !record.metric_supported || !record.value_supported) return 2;
  return 3;
}

function agentQualityRowOrder(record) {
  const match = String(record.row_ref == null ? "" : record.row_ref).match(/\d+/);
  return match ? Number(match[0]) : Number.MAX_SAFE_INTEGER;
}

function renderAgentQualityRecord(record) {
  const decision = agentQualityDecisionMeta(record.decision);
  const score = agentQualityScoreMeta(record.quality_score);
  const value = String(record.value || record.note || "未提供数值");
  const reasons = Array.isArray(record.reasons) ? record.reasons.filter(Boolean) : [];
  const sources = Array.isArray(record.sources) ? record.sources : [];
  const verification = record.search_verification || {};
  const onlineSearch = verification.online_search || {};
  const confidence = agentQualityPercent(record.confidence);
  const sourceScore = agentQualityPercent(record.source_score);
  const sourceLinks = sources.length
    ? sources.map(agentQualitySourceHtml).join("")
    : '<span class="agent-quality-source is-missing">没有记录可核验来源</span>';
  const reasonHtml = reasons.length
    ? '<ul>' + reasons.map(function (reason) {
        return "<li>" + agentQualityEscape(reason) + "</li>";
      }).join("") + "</ul>"
    : "<p>未记录额外异常原因。</p>";
  const verificationText = [
    verification.vote_count ? verification.vote_count + " 个复核意见" : "",
    verification.majority_count ? verification.majority_count + " 个多数意见" : "",
    verification.conflict_count ? verification.conflict_count + " 个来源冲突" : "无来源冲突",
    onlineSearch.enabled
      ? "联网检索 " + (onlineSearch.result_count || 0) + " 条"
      : "未启用联网检索"
  ].filter(Boolean).join(" · ");

  return '<details class="agent-quality-row agent-quality-row--' + decision.tone + '">'
    + '<summary class="agent-quality-row-summary">'
      + '<span class="agent-quality-cell agent-quality-cell--identity">'
        + '<strong>' + agentQualityEscape(record.company || "未标记主体") + "</strong>"
        + '<span>' + agentQualityEscape(record.metric || "未标记指标") + " · "
        + agentQualityEscape(agentQualityRowLabel(record.row_ref)) + "</span>"
      + "</span>"
      + '<span class="agent-quality-cell agent-quality-cell--value" title="' + agentQualityEscape(value) + '">'
        + agentQualityEscape(value)
      + "</span>"
      + '<span class="agent-quality-cell agent-quality-cell--score">'
        + '<strong class="agent-quality-score agent-quality-score--' + score.tone + '">'
        + (score.percent == null ? "—" : score.percent + " 分") + "</strong>"
        + "<span>" + agentQualityEscape(score.label) + "</span>"
      + "</span>"
      + '<span class="agent-quality-cell agent-quality-cell--checks">'
        + agentQualityCheck("主体", Boolean(record.entity_supported))
        + agentQualityCheck("指标", Boolean(record.metric_supported))
        + agentQualityCheck("数值", Boolean(record.value_supported))
      + "</span>"
      + '<span class="agent-quality-cell agent-quality-cell--source">'
        + "<strong>" + agentQualityEscape(agentQualityTierLabel(record.source_tier)) + "</strong>"
        + "<span>" + sources.length + " 个来源</span>"
      + "</span>"
      + '<span class="agent-quality-decision agent-quality-decision--' + decision.tone + '">'
        + agentQualityEscape(decision.label)
      + "</span>"
    + "</summary>"
    + '<div class="agent-quality-row-body">'
      + '<section><h5>证据与依据</h5><p>' + agentQualityEscape(record.basis || "未记录证据依据。") + "</p>"
        + (record.note ? '<p class="agent-quality-note">' + agentQualityEscape(record.note) + "</p>" : "")
      + "</section>"
      + '<section><h5>审核原因</h5>' + reasonHtml + "</section>"
      + '<section><h5>来源链接</h5><div class="agent-quality-sources">' + sourceLinks + "</div></section>"
      + '<section><h5>质量信号</h5><dl class="agent-quality-metrics">'
        + "<div><dt>质量分</dt><dd>" + (score.percent == null ? "未评分" : score.percent + " 分") + "</dd></div>"
        + "<div><dt>置信度</dt><dd>" + (confidence == null ? "未评分" : confidence + "%") + "</dd></div>"
        + "<div><dt>来源分</dt><dd>" + (sourceScore == null ? "未评分" : sourceScore + "%") + "</dd></div>"
        + "<div><dt>检索复核</dt><dd>" + agentQualityEscape(verificationText) + "</dd></div>"
      + "</dl></section>"
      + '<section class="agent-quality-next"><h5>下一步处置</h5><p>'
        + agentQualityEscape(agentQualityNextStep(record)) + "</p></section>"
    + "</div>"
  + "</details>";
}

function renderAgentQualityWorkspace(details, payload, nodeName) {
  const body = details.querySelector("[data-quality-body]");
  const summaryLabel = details.querySelector("[data-quality-summary]");
  const runId = String(payload.runId || details.dataset.runId || "");
  const records = Array.isArray(payload.records) ? payload.records : [];
  const payloadSummary = payload.summary || {};
  const decisions = payloadSummary.decisions || {};
  const average = agentQualityScoreMeta(payloadSummary.averageQuality);
  const state = agentQualityViewState.get(runId) || {
    query: "",
    decision: "all",
    tier: "all",
    sort: "issues"
  };
  agentQualityViewState.set(runId, state);

  if (summaryLabel) {
    summaryLabel.textContent = records.length + " 条 · 可筛选";
  }

  body.innerHTML = '<div class="agent-quality-overview">'
      + '<div><span>本轮数据</span><strong>' + records.length + "</strong></div>"
      + '<div><span>可发布</span><strong>' + Number(decisions.accepted || 0) + "</strong></div>"
      + '<div><span>待复核</span><strong>' + Number(decisions.review || 0) + "</strong></div>"
      + '<div><span>已拒绝</span><strong>' + Number(decisions.rejected || 0) + "</strong></div>"
      + '<div><span>平均质量</span><strong>' + (average.percent == null ? "—" : average.percent + " 分") + "</strong></div>"
    + "</div>"
    + '<div class="agent-quality-context">'
      + '<strong>' + agentQualityEscape(nodeName) + "逐条明细</strong>"
      + "<span>默认把拒绝、待复核和字段异常排在最前；点击任意数据可查看依据、来源和处置建议。</span>"
    + "</div>"
    + '<div class="agent-quality-toolbar">'
      + '<label class="agent-quality-search"><span>搜索</span><input type="search" data-quality-filter="query" placeholder="公司、指标、数值或飞书行号"></label>'
      + '<label><span>审核结论</span><select data-quality-filter="decision">'
        + '<option value="all">全部结论</option><option value="accepted">可发布</option>'
        + '<option value="review">待复核</option><option value="rejected">已拒绝</option>'
      + "</select></label>"
      + '<label><span>来源等级</span><select data-quality-filter="tier">'
        + '<option value="all">全部来源</option><option value="official">官方来源</option>'
        + '<option value="public">公开来源</option><option value="commercial">商业来源</option>'
        + '<option value="monitoring">监测来源</option><option value="missing">缺少来源</option>'
      + "</select></label>"
      + '<label><span>排序</span><select data-quality-filter="sort">'
        + '<option value="issues">问题优先</option><option value="row">飞书行号</option>'
        + '<option value="quality-asc">质量分由低到高</option><option value="quality-desc">质量分由高到低</option>'
      + "</select></label>"
      + '<div class="agent-quality-visible" data-quality-visible></div>'
    + "</div>"
    + '<div class="agent-quality-table-head" aria-hidden="true">'
      + "<span>主体 / 指标</span><span>数据值</span><span>质量</span><span>字段校验</span><span>证据来源</span><span>结论</span>"
    + "</div>"
    + '<div class="agent-quality-records" data-quality-records></div>';

  const queryInput = body.querySelector('[data-quality-filter="query"]');
  const decisionInput = body.querySelector('[data-quality-filter="decision"]');
  const tierInput = body.querySelector('[data-quality-filter="tier"]');
  const sortInput = body.querySelector('[data-quality-filter="sort"]');
  queryInput.value = state.query;
  decisionInput.value = state.decision;
  tierInput.value = state.tier;
  sortInput.value = state.sort;

  function refreshRecords() {
    const query = String(state.query || "").trim().toLowerCase();
    const filtered = records.filter(function (record) {
      if (state.decision !== "all" && String(record.decision || "").toLowerCase() !== state.decision) return false;
      if (state.tier !== "all" && String(record.source_tier || "").toLowerCase() !== state.tier) return false;
      if (!query) return true;
      const haystack = [
        record.company,
        record.metric,
        record.value,
        record.row_ref,
        record.basis,
        record.note
      ].join(" ").toLowerCase();
      return haystack.indexOf(query) >= 0;
    });

    filtered.sort(function (left, right) {
      if (state.sort === "row") return agentQualityRowOrder(left) - agentQualityRowOrder(right);
      const leftScore = agentQualityPercent(left.quality_score);
      const rightScore = agentQualityPercent(right.quality_score);
      if (state.sort === "quality-asc") return (leftScore == null ? 999 : leftScore) - (rightScore == null ? 999 : rightScore);
      if (state.sort === "quality-desc") return (rightScore == null ? -1 : rightScore) - (leftScore == null ? -1 : leftScore);
      return agentQualityIssuePriority(left) - agentQualityIssuePriority(right)
        || (leftScore == null ? -1 : leftScore) - (rightScore == null ? -1 : rightScore)
        || agentQualityRowOrder(left) - agentQualityRowOrder(right);
    });

    const recordsHost = body.querySelector("[data-quality-records]");
    const visible = body.querySelector("[data-quality-visible]");
    visible.textContent = "显示 " + filtered.length + " / " + records.length + " 条";
    recordsHost.innerHTML = filtered.length
      ? filtered.map(renderAgentQualityRecord).join("")
      : '<div class="agent-quality-empty">没有符合当前筛选条件的数据。</div>';
  }

  body.querySelectorAll("[data-quality-filter]").forEach(function (control) {
    const eventName = control.tagName === "INPUT" ? "input" : "change";
    control.addEventListener(eventName, function () {
      state[control.dataset.qualityFilter] = control.value;
      refreshRecords();
    });
  });
  refreshRecords();
}

function mountAgentRecordQuality(card, options) {
  if (!card || !isAgentRecordQualityNode(options.nodeName)) return;
  const host = card.querySelector(".agent-trace-details") || card;
  const details = document.createElement("details");
  details.className = "agent-quality-details";
  details.dataset.detailKey = options.qualityKey;
  details.dataset.runId = options.runId;
  details.innerHTML = '<summary><span>逐条数据质量</span><span data-quality-summary>展开查看每条结论</span></summary>'
    + '<div class="agent-quality-loading" data-quality-body>展开后加载本轮逐条审核结果。</div>';

  let technicalDetails = null;
  Array.prototype.forEach.call(host.children, function (child) {
    const summary = child.querySelector && child.querySelector(":scope > summary");
    if (!technicalDetails && summary && summary.textContent.indexOf("技术") >= 0) technicalDetails = child;
  });
  if (technicalDetails) host.insertBefore(details, technicalDetails);
  else host.appendChild(details);

  let loaded = false;
  function loadRecords() {
    if (loaded) return;
    const body = details.querySelector("[data-quality-body]");
    if (!options.runId) {
      body.innerHTML = '<div class="agent-quality-empty">这条历史记录没有可关联的运行编号。</div>';
      loaded = true;
      return;
    }
    body.innerHTML = '<div class="agent-quality-loading">正在加载逐条质量明细...</div>';
    loadAgentQualityRecords(options.runId).then(function (payload) {
      loaded = true;
      renderAgentQualityWorkspace(details, payload, options.nodeName);
    }).catch(function (error) {
      body.innerHTML = '<div class="agent-quality-empty">' + agentQualityEscape(error.message || "加载失败") + "</div>";
    });
  }

  details.addEventListener("toggle", function () {
    if (details.open) loadRecords();
  });
  if (options.open) {
    details.open = true;
    loadRecords();
  }
}


function renderAgentTrace(trace, options = {}) {
  if (!els.logBox || !trace) return;
  const nodeName = String(trace.node || "Agent");
  const runKey = String(trace.run_id || state.activeCrawlRunId || "current");
  const traceKey = runKey + "::" + nodeName;
  let card = Array.from(els.logBox.querySelectorAll(".agent-trace-card")).find((item) => item.dataset.traceKey === traceKey);
  if (!card) {
    card = document.createElement("section");
    card.dataset.traceKey = traceKey;
    card._traceEvents = [];
    els.logBox.appendChild(card);
  }

  const events = Array.isArray(card._traceEvents) ? card._traceEvents : [];
  const phase = trace.phase || trace.event_type || "agent";
  const isHeartbeat = nodeName === "多 Agent 编排器"
    && phase === "observe"
    && trace.output
    && trace.output.elapsedSeconds !== undefined;
  if (isHeartbeat) {
    const heartbeatIndex = events.findIndex((event) =>
      event.node === "多 Agent 编排器"
      && (event.phase || event.event_type) === "observe"
      && event.output
      && event.output.elapsedSeconds !== undefined
    );
    if (heartbeatIndex >= 0) events[heartbeatIndex] = trace;
    else events.push(trace);
  } else {
    events.push(trace);
  }
  card._traceEvents = events.slice(-80);

  const latest = card._traceEvents[card._traceEvents.length - 1] || trace;
  const latestPhase = latest.phase || latest.event_type || "agent";
  const status = traceAuditStatus(card._traceEvents);
  const statusText = traceAuditStatusLabel(status);
  const step = TRACE_STEPS[nodeName];
  const stepText = step ? "步骤 " + step : "工作流";
  const time = String(latest.ts || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
  const subject = traceAuditSubject(card._traceEvents);
  const result = traceAuditResult(card._traceEvents, status);
  const next = traceAuditNext(card._traceEvents, status);
  const metricTrace = [...card._traceEvents].reverse().find((event) => traceKeyMetrics(event).length) || latest;
  const metrics = traceKeyMetrics(metricTrace);
  const metricsHtml = metrics.length
    ? '<div class="agent-trace-metrics">' + metrics.map((item) => '<span><b>' + escapeHtml(String(item.value)) + '</b>' + escapeHtml(item.label) + '</span>').join("") + '</div>'
    : "";

  const openKeys = new Set(Array.from(card.querySelectorAll("details[open]")).map((item) => item.dataset.detailKey));
  const businessKey = traceKey + ":business";
  const technicalKey = traceKey + ":technical";
  card.className = "agent-trace-card phase-" + latestPhase + " audit-status-" + status;
  card.innerHTML =
    '<div class="agent-trace-title">'
      + '<span class="agent-trace-step">' + escapeHtml(stepText) + '</span>'
      + '<strong>' + escapeHtml(nodeName) + '</strong>'
      + '<span class="agent-trace-badge audit-status-' + escapeHtml(status) + '">' + escapeHtml(statusText) + '</span>'
      + '<time>' + escapeHtml(time) + '</time>'
    + '</div>'
    + '<div class="agent-audit-grid">'
      + '<section><span class="agent-audit-label">审核内容</span><p>' + escapeHtml(subject) + '</p></section>'
      + '<section><span class="agent-audit-label">审核结果</span><p class="agent-trace-message">' + escapeHtml(result) + '</p></section>'
      + '<section><span class="agent-audit-label">下一步</span><p>' + escapeHtml(next) + '</p></section>'
    + '</div>'
    + metricsHtml
    + '<div class="agent-trace-details">'
      + '<details data-detail-key="' + escapeHtml(businessKey) + '"' + (openKeys.has(businessKey) ? " open" : "") + '>'
        + '<summary><span>展开查看审核依据与抽样结果</span><small>' + card._traceEvents.length + ' 条过程记录</small></summary>'
        + renderAuditEventTimeline(card._traceEvents)
      + '</details>'
      + '<details class="agent-technical-details" data-detail-key="' + escapeHtml(technicalKey) + '"' + (openKeys.has(technicalKey) ? " open" : "") + '>'
        + '<summary><span>技术记录</span><small>仅排障时查看</small></summary>'
        + '<pre>' + escapeHtml(compactJson(card._traceEvents)) + '</pre>'
      + '</details>'
    + '</div>';

  const qualityRunId = String((trace && (trace.run_id || trace.runId)) || (typeof runKey !== "undefined" ? runKey : ""));

  if (isAgentRecordQualityNode(nodeName)) {

    const qualityKey = traceKey + ":quality-records";

    mountAgentRecordQuality(card, {

      runId: qualityRunId,

      nodeName: nodeName,

      qualityKey: qualityKey,

      open: Boolean(typeof openKeys !== "undefined" && openKeys && openKeys.has(qualityKey))

    });

  }


  if (!options.skipScroll) els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

function parseCrawlRunContent(content) {
  const parsed = { traces: [], raw: [], crawlSummary: null, done: null };
  String(content || "").split(/\r?\n/).forEach((line) => {
    if (!line) return;
    const markerIndex = line.indexOf("AGENT_TRACE=");
    if (markerIndex >= 0) {
      try {
        parsed.traces.push(JSON.parse(line.slice(markerIndex + "AGENT_TRACE=".length)));
        return;
      } catch (_) {
        parsed.raw.push(line);
        return;
      }
    }
    if (line.trim().startsWith("{")) {
      try {
        const payload = JSON.parse(line);
        if (payload.type === "agent_trace" && payload.trace) {
          parsed.traces.push(payload.trace);
          return;
        }
        if (payload.type === "crawl_summary") {
          parsed.crawlSummary = payload;
          return;
        }
        if (payload.type === "done") {
          parsed.done = payload;
          return;
        }
      } catch (_) {
      }
    }
    parsed.raw.push(line);
  });
  return parsed;
}

function renderCrawlRunArchive(data) {
  if (!els.logBox) return;
  const run = data.run || {};
  const parsed = parseCrawlRunContent(data.content || "");
  const curation = run.curation || {};
  const runLog = run.run_log || {};
  const summary = parsed.crawlSummary || {};
  const successful = Number(runLog.success_urls ?? (Array.isArray(summary.success) ? summary.success.length : 0));
  const failed = Number(runLog.failed_urls ?? (Array.isArray(summary.failed) ? summary.failed.length : 0));
  const total = Number(runLog.rows ?? summary.total ?? successful + failed);
  const status = crawlRunStatusLabel(run);
  const started = String(run.started_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
  const uniqueSteps = new Set(parsed.traces.map((trace) => String(trace.run_id || run.crawl_run_id || "run") + "::" + String(trace.node || "Agent"))).size;
  const stats = [
    ["抓取链接", total],
    ["抓取成功", successful],
    ["抓取失败", failed],
    ["审核证据", Number(curation.tasks || 0)],
    ["可发布", Number(curation.accepted || 0)],
    ["待复核", Number(curation.review || 0)],
    ["证据缺口", Number(curation.gaps || 0)],
  ];

  els.logBox.innerHTML =
    '<section class="crawl-audit-overview">'
      + '<div class="crawl-audit-heading"><div><span class="run-status status-' + escapeHtml(String(run.run_status || "completed")) + '">' + escapeHtml(status) + '</span><strong>' + escapeHtml(run.trigger || "爬虫运行") + '</strong><span>' + escapeHtml(run.scope || "未记录范围") + '</span></div><time>' + escapeHtml(started || run.crawl_run_id || "") + (run.duration_ms ? " · " + escapeHtml(formatAuditDuration(run.duration_ms)) : "") + '</time></div>'
      + '<div class="crawl-audit-stats">' + stats.map(([label, value]) => '<span><b>' + escapeHtml(String(value)) + '</b>' + escapeHtml(label) + '</span>').join("") + '</div>'
    + '</section>'
    + taskLifecycleMarkup(run)
    + '<div class="agent-audit-list-heading"><div><strong>Agent 审核流程</strong><span>按业务节点合并展示审核内容、结论和下一步；展开可看证据抽样。</span></div><em>' + uniqueSteps + ' 个步骤</em></div>';

  if (parsed.traces.length) {
    parsed.traces.forEach((trace) => renderAgentTrace(trace, { skipScroll: true }));
  } else {
    const empty = document.createElement("div");
    empty.className = "agent-audit-empty";
    empty.textContent = run.run_status === "running" ? "Agent 审核尚未开始，或日志仍在写入。" : "本轮没有可解析的 Agent 审核事件。";
    els.logBox.appendChild(empty);
  }

  if (Array.isArray(summary.failed) && summary.failed.length) {
    const failures = document.createElement("details");
    failures.className = "crawl-raw-log";
    failures.dataset.detailKey = "failed-urls";
    failures.innerHTML = '<summary><span>展开查看失败链接</span><small>' + summary.failed.length + ' 条</small></summary><div class="agent-audit-data">' + renderAuditValue(summary.failed) + '</div>';
    els.logBox.appendChild(failures);
  }

  if (parsed.raw.length) {
    const raw = document.createElement("details");
    raw.className = "crawl-raw-log";
    raw.dataset.detailKey = "raw-log";
    const rawSummary = document.createElement("summary");
    rawSummary.innerHTML = '<span>展开查看原始运行日志</span><small>排障用 · ' + parsed.raw.length + ' 行</small>';
    const pre = document.createElement("pre");
    pre.textContent = parsed.raw.join("\n");
    raw.append(rawSummary, pre);
    els.logBox.appendChild(raw);
  }
}

function renderTaskTrackingPlaceholder(attempt = 0) {
  if (!els.logBox) return;
  const waitingLonger = attempt >= 12;
  const waitingMode = waitingLonger ? "long" : "short";
  if (els.logBox.dataset.waitingForTask === waitingMode) return;
  els.logBox.dataset.waitingForTask = waitingMode;
  els.logBox.innerHTML = '<div class="task-tracking-placeholder">'
    + '<span class="task-tracking-spinner" aria-hidden="true"></span>'
    + '<strong>正在建立并跟踪新任务</strong>'
    + '<p>' + (waitingLonger ? '后台尚未返回任务编号，系统仍在自动重试，不会停止跟踪。' : '任务记录生成后会自动出现在左侧并打开详情。') + '</p>'
    + '</div>';
}

async function selectNewUnifiedTask(previousTaskId, attempt = 0) {
  if (!crawlLogModalIsOpen()) return;
  try {
    await loadCrawlRuns();
  } catch (_) {
  }
  const newestTaskId = String(state.crawlRuns[0]?.task_id || "");
  if (newestTaskId && newestTaskId !== previousTaskId) {
    state.pendingUnifiedTaskTimer = null;
    delete els.logBox.dataset.waitingForTask;
    await loadCrawlRunLog(newestTaskId);
    return;
  }
  renderTaskTrackingPlaceholder(attempt);
  state.pendingUnifiedTaskTimer = window.setTimeout(function () {
    state.pendingUnifiedTaskTimer = null;
    selectNewUnifiedTask(previousTaskId, attempt + 1);
  }, Math.min(1500, 500 + attempt * 50));
}

function setLog(text, appendWithDivider = false) {
  if (appendWithDivider) {
    const previousTaskId = String(state.crawlRuns[0]?.task_id || "");
    if (state.pendingUnifiedTaskTimer) window.clearTimeout(state.pendingUnifiedTaskTimer);
    stopCrawlLogPolling();
    state.activeCrawlRunId = null;
    delete els.logBox.dataset.renderSignature;
    renderTaskTrackingPlaceholder(0);
    localStorage.removeItem("appLogs");
    selectNewUnifiedTask(previousTaskId);
    return;
  }
  const currentText = els.logBox.textContent.trim();
  els.logBox.innerHTML = "";
  els.logBox.appendChild(document.createTextNode(text));
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

function taskLifecycleTime(value) {
  const text = String(value || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
  return text ? text.slice(0, 19) : "尚未记录";
}

function taskLifecycleMarkup(task) {
  const running = String(task?.run_status || "") === "running";
  const interrupted = Boolean(task?.interrupted);
  const phase = String(task?.phase || (running ? "执行中" : interrupted ? "已中断" : "已结束"));
  const detail = String(task?.progress_detail || task?.status_detail || (running ? "后台持续监控中。" : "任务状态已归档。"));
  const heartbeat = taskLifecycleTime(task?.heartbeat_at_hkt || task?.completed_at_hkt || task?.started_at_hkt);
  const stateClass = running ? "is-running" : interrupted ? "is-interrupted" : "is-settled";
  return '<section class="task-lifecycle-monitor ' + stateClass + '">'
    + '<span class="task-lifecycle-signal" aria-hidden="true"></span>'
    + '<strong>当前阶段：' + escapeHtml(phase) + '</strong>'
    + '<span>最近心跳：' + escapeHtml(heartbeat) + '</span>'
    + '<p>' + escapeHtml(detail) + '</p>'
    + '</section>';
}

function taskLifecycleCompact(task) {
  if (String(task?.run_status || "") !== "running" && !task?.interrupted) return "";
  const phase = String(task?.phase || (task?.interrupted ? "已中断" : "执行中"));
  const heartbeat = taskLifecycleTime(task?.heartbeat_at_hkt || task?.completed_at_hkt || task?.started_at_hkt).slice(11, 19);
  const detail = String(task?.progress_detail || task?.status_detail || "持续监控中").slice(0, 68);
  return '<small class="task-live-progress ' + (task?.interrupted ? "is-interrupted" : "is-running") + '">'
    + '<span aria-hidden="true"></span>' + escapeHtml(phase) + ' · ' + escapeHtml(heartbeat) + ' · ' + escapeHtml(detail)
    + '</small>';
}

function crawlRunStatusLabel(run) {
  if (run.run_status === "running") return "运行中";
  if (run.run_status === "failed" || Number(run.crawl_return_code || 0) !== 0) return "失败";
  return "已完成";
}

const CRAWL_LOG_POLL_INTERVAL_MS = 1500;

function crawlLogModalIsOpen() {
  return Boolean(els.logModal && !els.logModal.hidden);
}

function stopCrawlLogPolling() {
  if (state.crawlLogPollTimer) {
    window.clearTimeout(state.crawlLogPollTimer);
    state.crawlLogPollTimer = null;
  }
}

function scheduleCrawlLogPolling(delay = CRAWL_LOG_POLL_INTERVAL_MS) {
  stopCrawlLogPolling();
  if (!crawlLogModalIsOpen() || !state.activeCrawlRunId) return;
  state.crawlLogPollTimer = window.setTimeout(async () => {
    state.crawlLogPollTimer = null;
    if (state.crawlLogPollBusy || !crawlLogModalIsOpen() || !state.activeCrawlRunId) {
      scheduleCrawlLogPolling();
      return;
    }
    const crawlRunId = state.activeCrawlRunId;
    state.crawlLogPollBusy = true;
    let data = null;
    try {
      data = await loadCrawlRunLog(crawlRunId, { silent: true, managePolling: false });
    } finally {
      state.crawlLogPollBusy = false;
    }
    const stillActive = crawlRunId === state.activeCrawlRunId && crawlLogModalIsOpen();
    if (stillActive) {
      scheduleCrawlLogPolling(data?.run?.run_status === "running" ? CRAWL_LOG_POLL_INTERVAL_MS : 5000);
    }
  }, delay);
}

/* Unified task sidebar v144 */
function unifiedTaskId(value) {
  const id = String(value || "");
  return id.indexOf(":") >= 0 ? id : "crawl:" + id;
}

function unifiedTaskKindLabel(task) {
  if (task.kind_label) return String(task.kind_label);
  if (task.kind === "crawl") return "爬虫";
  if (task.kind === "weekly-report") return "周报生成";
  if (task.kind === "carrier-performance") return "业绩摘要";
  if (task.kind === "audio-generation") return "音频生成";
  return "后台任务";
}

function renderUnifiedTaskArchive(data) {
  const task = data.task || {};
  if (task.kind === "crawl") {
    renderCrawlRunArchive({
      run: data.run || {},
      content: data.content || "",
      lines: data.lines || 0,
      bytes: data.bytes || 0
    });
    return;
  }
  const status = crawlRunStatusLabel(task);
  const started = String(task.started_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
  const completed = String(task.completed_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
  const duration = task.duration_ms ? formatAuditDuration(task.duration_ms) : (task.run_status === "running" ? "执行中" : "未记录");
  const content = String(data.content || "");
  els.logBox.innerHTML =
    '<section class="crawl-audit-overview task-audit-overview">'
      + '<div class="crawl-audit-heading"><div><span class="run-status status-' + escapeHtml(task.run_status || "completed") + '">'
      + escapeHtml(status) + '</span><strong>' + escapeHtml(task.title || "后台任务") + '</strong><span>'
      + escapeHtml(task.scope || unifiedTaskKindLabel(task)) + '</span></div><time>'
      + escapeHtml(started || task.task_run_id || "") + (completed ? " 至 " + escapeHtml(completed) : "")
      + '</time></div>'
      + '<div class="task-audit-stats">'
        + '<span><b>' + escapeHtml(unifiedTaskKindLabel(task)) + '</b><small>任务类型</small></span>'
        + '<span><b>' + escapeHtml(String(data.lines || task.lines || 0)) + '</b><small>日志行数</small></span>'
        + '<span><b>' + escapeHtml(duration) + '</b><small>运行耗时</small></span>'
        + '<span><b>' + escapeHtml(status) + '</b><small>当前状态</small></span>'
      + '</div>'
    + '</section>'
    + taskLifecycleMarkup(task);
  const process = document.createElement("section");
  process.className = "task-run-process";
  process.innerHTML = '<header><strong>任务执行过程</strong><span>日志持续归档到该任务</span></header>';
  const pre = document.createElement("pre");
  pre.textContent = content || "任务已创建，正在等待运行日志。";
  process.appendChild(pre);
  els.logBox.appendChild(process);
}

function scheduleUnifiedTaskListRefresh() {
  if (state.taskListPollTimer) {
    window.clearTimeout(state.taskListPollTimer);
    state.taskListPollTimer = null;
  }
  if (!crawlLogModalIsOpen()) return;
  state.taskListPollTimer = window.setTimeout(function () {
    state.taskListPollTimer = null;
    loadCrawlRuns();
  }, 2500);
}

function renderCrawlRunList() {
  if (!els.crawlRunList) return;
  if (!state.crawlRuns.length) {
    els.crawlRunList.textContent = "暂无任务记录。";
    return;
  }
  els.crawlRunList.innerHTML = state.crawlRuns.map(function (task) {
    const id = String(task.task_id || "");
    const time = String(task.completed_at_hkt || task.started_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
    const status = crawlRunStatusLabel(task);
    const count = Number(task.lines || 0);
    const kind = unifiedTaskKindLabel(task);
    const scope = String(task.scope || "未记录任务范围");
    return '<button class="crawl-run-item ' + (id === state.activeCrawlRunId ? "is-active" : "")
      + '" type="button" data-run-id="' + escapeHtml(id) + '">'
      + '<span><strong>' + escapeHtml(task.title || "后台任务") + '</strong><em class="status-'
      + escapeHtml(task.run_status || "completed") + '">' + escapeHtml(status) + '</em></span>'
      + '<time>' + escapeHtml(time || task.task_run_id || id) + '</time>'
      + '<small><i class="task-kind-label">' + escapeHtml(kind) + '</i>' + escapeHtml(scope)
      + (count ? " · " + count + " 行" : "") + '</small>'
      + taskLifecycleCompact(task)
      + '</button>';
  }).join("");
  els.crawlRunList.querySelectorAll("[data-run-id]").forEach(function (button) {
    button.addEventListener("click", function () {
      loadCrawlRunLog(button.dataset.runId);
    });
  });
}

async function loadCrawlRunLog(crawlRunId, { silent = false, managePolling = true } = {}) {
  if (!crawlRunId || !els.logBox) return null;
  const taskId = unifiedTaskId(crawlRunId);
  state.activeCrawlRunId = taskId;
  renderCrawlRunList();
  if (!silent) els.logBox.textContent = "正在读取任务日志...";
  const previousScrollTop = els.logBox.scrollTop;
  const wasNearBottom = els.logBox.scrollHeight - els.logBox.scrollTop - els.logBox.clientHeight < 80;
  try {
    const response = await fetch("/api/task-run-log?id=" + encodeURIComponent(taskId), { cache: "no-store" });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "任务日志不可用");
    const task = Object.assign({}, data.task || {}, {
      lines: Number(data.lines || (data.task || {}).lines || 0),
      bytes: Number(data.bytes || (data.task || {}).bytes || 0)
    });
    const taskIndex = state.crawlRuns.findIndex(function (item) {
      return String(item.task_id || "") === taskId;
    });
    if (taskIndex >= 0) state.crawlRuns[taskIndex] = task;
    else state.crawlRuns.unshift(task);
    renderCrawlRunList();
    const renderSignature = [
      taskId,
      data.lines || 0,
      data.bytes || 0,
      task.run_status || "",
      task.phase || "",
      task.heartbeat_at_hkt || "",
      task.status_detail || ""
    ].join(":");
    if (els.logBox.dataset.renderSignature !== renderSignature) {
      const openDetailKeys = new Set(
        Array.from(els.logBox.querySelectorAll("details[open]")).map(function (item) {
          return item.dataset.detailKey;
        })
      );
      renderUnifiedTaskArchive(Object.assign({}, data, { task: task }));
      Array.from(els.logBox.querySelectorAll("details[data-detail-key]")).forEach(function (item) {
        if (openDetailKeys.has(item.dataset.detailKey)) item.open = true;
      });
      els.logBox.dataset.renderSignature = renderSignature;
    }
    if (els.logRunTitle) {
      const time = String(task.started_at_hkt || "").replace("T", " ").replace(/\+\d{2}:\d{2}$/, "");
      els.logRunTitle.textContent = (task.title || "后台任务") + " · " + (time || task.task_run_id || taskId)
        + " · " + Number(data.lines || 0) + " 行 · " + Number(data.bytes || 0) + " B";
    }
    if (task.run_status === "running") {
      els.logBox.scrollTop = !silent || wasNearBottom ? els.logBox.scrollHeight : previousScrollTop;
    } else {
      els.logBox.scrollTop = silent && wasNearBottom ? els.logBox.scrollHeight : (silent ? previousScrollTop : 0);
    }
    if (managePolling) {
      if (task.run_status === "running" && crawlLogModalIsOpen()) scheduleCrawlLogPolling();
      else stopCrawlLogPolling();
    }
    data.run = data.run || { run_status: task.run_status };
    return data;
  } catch (error) {
    if (!silent) els.logBox.textContent = "无法读取该任务日志：" + error.message;
    if (managePolling && crawlLogModalIsOpen()) scheduleCrawlLogPolling();
    return null;
  }
}

async function loadCrawlRuns({ selectLatest = false, selectRunId = "" } = {}) {
  if (!els.crawlRunList) return;
  try {
    const response = await fetch("/api/task-runs?limit=80", { cache: "no-store" });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "任务记录加载失败");
    state.crawlRuns = Array.isArray(data.tasks) ? data.tasks : [];
    renderCrawlRunList();
    let target = selectRunId || (selectLatest && state.crawlRuns.length ? state.crawlRuns[0].task_id : "");
    if (target) {
      target = unifiedTaskId(target);
      await loadCrawlRunLog(target);
    }
    scheduleUnifiedTaskListRefresh();
  } catch (error) {
    els.crawlRunList.textContent = "任务记录加载失败：" + error.message;
  }
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
  const model = config.model || "deepseek-v4-flash";
  els.aiModel.innerHTML = `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`;
  els.aiModel.value = model;
  els.aiApiKey.value = "";
  els.aiApiKey.placeholder = config.has_api_key ? `已保存：${config.api_key}` : "请输入 API Key";
  els.aiConfigStatus.textContent = `${config.provider} / ${config.model} / ${config.base_url} / ${config.has_api_key ? "API Key 已保存" : "未保存 API Key"}`;
}

async function fetchAiModels() {
  const baseUrl = els.aiBaseUrl.value.trim();
  const apiKey = els.aiApiKey.value.trim();
  if (!/^https?:\/\//i.test(baseUrl)) throw new Error("Base URL 必须以 http:// 或 https:// 开头");
  els.fetchAiModels.disabled = true;
  els.fetchAiModels.textContent = "获取中...";
  if (els.aiModelHint) els.aiModelHint.textContent = "正在连接模型服务...";
  try {
    const response = await fetch("/api/ai-models", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "模型列表获取失败");
    const current = els.aiModel.value;
    els.aiModel.innerHTML = data.models.map((model) => `<option value="${escapeHtml(model)}">${escapeHtml(model)}</option>`).join("");
    els.aiModel.value = data.models.includes(current) ? current : data.models[0];
    if (els.aiModelHint) els.aiModelHint.textContent = `已获取 ${data.models.length} 个模型，选择后点击保存设置。`;
  } finally {
    els.fetchAiModels.disabled = false;
    els.fetchAiModels.textContent = "获取模型列表";
  }
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
  const payload = {
    provider: els.aiProvider.value,
    base_url: els.aiBaseUrl.value.trim(),
    model: els.aiModel.value.trim(),
    api_key: els.aiApiKey.value.trim(),
  };
  if (!/^https?:\/\//i.test(payload.base_url)) {
    throw new Error("Base URL 必须以 http:// 或 https:// 开头");
  }
  if (!payload.model) throw new Error("请选择要测试的模型");

  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 50000);
  els.testAiConfig.disabled = true;
  els.testAiConfig.textContent = "测试中...";
  els.aiConfigStatus.textContent = "正在验证 Base URL、API Key 和模型...";
  try {
    const response = await fetch("/api/ai-test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || data.result?.error || "连接失败");
    els.aiConfigStatus.textContent = `连接成功：${data.result.provider || ""} / ${data.result.model || ""} / ${data.result.latency_ms || 0}ms`;
    return data.result;
  } catch (error) {
    if (error && error.name === "AbortError") {
      throw new Error("连接测试超时，请检查内网连接或稍后重试");
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
    els.testAiConfig.disabled = false;
    els.testAiConfig.textContent = "测试连接";
  }
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
    if (!data.ok) throw new Error(data.error || "音频任务提交失败");
    const taskId = String(data.task?.task_id || "");
    if (!taskId) throw new Error("后端没有返回音频任务编号");
    const submitMessage = data.alreadyRunning
      ? "该文件的音频任务已在运行，继续跟踪现有任务。"
      : "音频生成任务已启动，可在任务与审核记录中查看。";
    appendLog(`${submitMessage}\n`);
    showTaskOperationNotice(submitMessage);
    await loadCrawlRuns({ selectRunId: taskId });

    const deadline = Date.now() + 30 * 60 * 1000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => window.setTimeout(resolve, 2500));
      const taskResponse = await fetch("/api/task-run-log?id=" + encodeURIComponent(taskId), { cache: "no-store" });
      const taskData = await taskResponse.json();
      if (!taskData.ok) throw new Error(taskData.error || "无法读取音频任务状态");
      const task = taskData.task || {};
      if (crawlLogModalIsOpen()) await loadCrawlRuns({ selectRunId: taskId });
      if (task.run_status === "running") continue;
      await loadCrawlRuns({ selectRunId: taskId });
      if (task.run_status !== "completed") {
        throw new Error(task.status_detail || task.progress_detail || "音频生成失败");
      }
      const statusResponse = await fetch("/api/status", { cache: "no-store" });
      const statusData = await statusResponse.json();
      if (statusData.ok && statusData.status) renderStatus(statusData.status);
      appendLog(`${task.status_detail || "音频摘要已生成。"}\n`);
      showTaskOperationNotice("音频摘要已生成，播放按钮已更新。");
      return;
    }
    throw new Error("音频任务仍在后台运行，请在任务与审核记录中继续查看。");
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
  loadCrawlRuns();
  if (els.logRunTitle) els.logRunTitle.textContent = "实时日志（运行开始后即自动归档）";
  setBusy(true, "正在重新爬取", "crawl");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] 开始启动后台爬虫任务...\n`, true);
  try {
    const res = await fetch("/api/crawl-stream?v=12", { method: "POST" });
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}));
      throw new Error(payload.error || `请求失败（HTTP ${res.status}）`);
    }
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
        
        if (event.type === "run_start") {
          state.activeCrawlRunId = event.crawlRunId || null;
          loadCrawlRuns({ selectRunId: state.activeCrawlRunId });
        } else if (event.type === "log") {
          if (event.text) {
            appendLog(event.text + "\n");
          }
        } else if (event.type === "agent_trace") {
          if (!crawlLogModalIsOpen()) renderAgentTrace(event.trace);
        } else if (event.type === "crawl_summary") {
          if (crawlLogModalIsOpen()) continue;
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
          await loadCrawlRuns({ selectRunId: event.crawlRunRegistry?.crawl_run_id || state.activeCrawlRunId });
          setBusy(false, "准备就绪", "crawl");
          return;
        }
      }
    }
  } catch (err) {
    appendLog(`\n\n执行异常：${err.message}`);
    showTaskOperationNotice(`手动全量爬虫未能启动或已中断：${err.message}`);
  }
  setBusy(false, "准备就绪", "crawl");
}

async function generateReport(source = "按钮") {
  if (els.logModal) els.logModal.hidden = false;
  setBusy(true, "正在生成", "generate");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成周报，请稍候...\n`, true);
  try {
    const res = await fetch("/api/generate-stream", { method: "POST" });
    if (!res.ok) throw new Error("网络请求失败");
    loadCrawlRuns();
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
          if (!crawlLogModalIsOpen()) renderAgentTrace(event.trace);
        } else if (event.type === "done") {
          appendLog(`\n[生成结束] 最终状态：${event.ok ? "成功" : "失败"}\n总耗时：${event.durationMs} ms\n`);
          if (event.audio && !event.audio.ok) {
             appendLog(`语音摘要失败：${event.audio.error}\n`);
          }
          renderStatus(event.status);
          await loadCrawlRuns({ selectLatest: true });
          setBusy(false, "准备就绪", "generate");
          return;
        }
      }
    }
  } catch (error) {
    appendLog(`\n生成失败：${error.message}`);
  } finally {
    setBusy(false, "准备就绪", "generate");
  }
}

async function generateCarrierPerformanceReport(source = "按钮") {
  if (els.logModal) els.logModal.hidden = false;
  setBusy(true, "正在生成", "performance");
  setLog(`[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}] ${source}触发生成业绩摘要，请稍候...\n`, true);
  try {
    const response = await fetch(`/api/generate-carrier-performance-stream`, { method: "POST" });
    if (!response.ok) throw new Error("网络请求失败");
    loadCrawlRuns();
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
          if (!crawlLogModalIsOpen()) renderAgentTrace(event.trace);
        } else if (event.type === "done") {
          appendLog(`\n[生成结束] 最终状态：${event.ok ? "成功" : "失败"}\n总耗时：${event.durationMs} ms\n`);
          if (event.audio && !event.audio.ok) appendLog(`语音摘要失败：${event.audio.error}\n`);
          renderStatus(event.status);
          await loadCrawlRuns({ selectLatest: true });
          return;
        }
      }
    }
  } catch (error) {
    appendLog(`\n生成失败：${error.message}`);
  } finally {
    setBusy(false, "准备就绪", "performance");
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
    .replace(/&#42;&#42;(.+?)&#42;&#42;/g, "<strong>$1</strong>")
    .replace(/^\*\*([^*\n]+)$/g, "<strong>$1</strong>")
    .replace(/^&#42;&#42;([^*\n]+)$/g, "<strong>$1</strong>")
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
    if (line.startsWith("|") && line.includes("|", 1)) {
      const expectedCells = tableRows && tableRows.length ? tableRows[0].length : null;
      const completeLine = line.endsWith("|") ? line : `${line}|`;
      const cells = completeLine.split("|").slice(1, -1);
      if (expectedCells && cells.length < expectedCells) {
        continue;
      }
      if (cells.every((cell) => /^:?-{2,}:?$/.test(cell.trim()))) {
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
    const heading = line.match(/^(#{1,6})\s+(.+)$/);
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

const ASSISTANT_PROCESS_MARKERS = "(?:用户问的是|“[^”]{1,20}”通常指|\"[^\"]{1,20}\"通常指|我先|我来|我读取|我确认|我联网|我同步|我打开|我调用|我需要|我继续|我再读取|为了获取|检索到了|检索只返回|联网已搜到|本地检索结果|本地数据已命中|本地数据已经命中|本地数据已确认|数据包摘要显示|数据包显示|实际上，从数据包摘要|但早期的数据|CSV文件|CSV内容太大|包含所有公司的数据|再读取|再读取一下|让我|现在让我|现在我(?:已|来|开始|生成|整理)|现在(?:生成|整理|读取|检索)|我整理一下|数据已经齐全|数据非常清晰|数据充足|搜索高度一致|很好|我已经有了|从JSON中|从数据中我已获取|已获取|需要搜索|需要确认|需要.*数据|从已有的数据|从JSON看到|当前时间为|按当前日期|上一个季度就是|[^。！？\\n]{0,30}最新一个完整季度是)";

function isProcessClause(text) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return false;
  if (/^(?:当前时间|按当前日期|上个完整季度|上一个完整季度)/.test(clean)) return false;
  if (new RegExp(`^${ASSISTANT_PROCESS_MARKERS}`).test(clean)) return true;
  return (
    /(?:检索|搜索|命中|读取|核验|交叉验证|确认口径|确认详细|关键引用|公开来源|数据库原文|摘要片段|CSV文件|CSV内容|数据充足|verification_status|verification_count|official_match)/i.test(clean) &&
    !/(?:营业收入|收入为|同比|亿元|百万元|核心数据|一句话结论|关键数据)/.test(clean)
  );
}

function removeProcessClauses(text, collector = null) {
  return String(text || "")
    .split(/\n+/)
    .map((line) => {
      // Markdown table rows are structured data. Splitting them on commas
      // corrupts values such as 263,707 and can remove the closing pipes when
      // a later cell contains audit terms such as official_match.
      if (line.trimStart().startsWith("|")) return line;
      const parts = line.match(/[^。！？；;]+[。！？；;]?/g) || [line];
      const kept = [];
      parts.forEach((part) => {
        const commaParts = part.match(/[^，,]+[，,]?/g) || [part];
        const keptCommaParts = [];
        commaParts.forEach((piece) => {
          const clean = piece.trim();
          if (!clean) return;
          if (isProcessClause(clean)) {
            if (collector) collector.push(clean.replace(/\s+/g, " "));
            return;
          }
          keptCommaParts.push(piece);
        });
        const joined = keptCommaParts.join("").trim();
        if (joined) kept.push(joined);
      });
      return kept.join("").trim();
    })
    .filter(Boolean)
    .join("\n")
    .trim();
}

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
  answer = removeProcessClauses(answer, processLines);
  return { answer, processLines: [...new Set(processLines)].slice(0, 12) };
}

function stripAssistantControlText(content) {
  let text = content || "";
  // The chart tool renders the actual image as a timeline event. A bare
  // Markdown image label without a URL is only a model placeholder.
  text = text.replace(/!\[[^\]\n]*\](?!\s*\()/g, "").trim();
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
  text = removeProcessClauses(text);
  text = text.replace(/^\s*[-–—]{3,}\s*$/gm, "").trim();
  return text;
}

function expandCitationIndexes(expression) {
  const indexes = [];
  String(expression || "")
    .split(/[，,；;]/)
    .map((part) => part.trim())
    .filter(Boolean)
    .forEach((part) => {
      const range = part.match(/^(\d+)\s*[-–—]\s*(\d+)$/);
      if (range) {
        const start = Number(range[1]);
        const end = Number(range[2]);
        if (!Number.isFinite(start) || !Number.isFinite(end)) return;
        const step = start <= end ? 1 : -1;
        for (let value = start; value !== end + step; value += step) {
          if (indexes.length >= 40) break;
          indexes.push(value);
        }
        return;
      }
      const single = part.match(/^\d+$/);
      if (single && indexes.length < 40) indexes.push(Number(part));
    });
  return [...new Set(indexes)].filter((idx) => idx > 0);
}

function citationMarkerHtml(idx, node) {
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
}

function normalizeCitationLabel(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/&amp;/g, "&")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[\s"'“”‘’`]+/g, "")
    .replace(/[，,。.;；:：()[\]{}<>《》]+/g, "")
    .trim();
}

function citationLabelVariants(value) {
  const raw = String(value || "").trim();
  if (!raw) return [];
  const withoutFragment = raw
    .replace(/\s*·\s*片段\s*\d+\s*$/i, "")
    .replace(/\s+片段\s*\d+\s*$/i, "");
  const strippedRef = withoutFragment
    .replace(/^\/references(?:-raw)?\//, "")
    .replace(/^https?:\/\/[^/]+\/references(?:-raw)?\//i, "");
  let decoded = strippedRef;
  try {
    decoded = decodeURIComponent(strippedRef);
  } catch (e) {}
  const noQuery = decoded.split(/[?#]/, 1)[0];
  const basename = noQuery.split("/").filter(Boolean).pop() || noQuery;
  const noExtension = basename.replace(/\.[a-z0-9]+$/i, "");
  return [...new Set([raw, withoutFragment, strippedRef, decoded, noQuery, basename, noExtension])]
    .filter(Boolean)
    .map(normalizeCitationLabel)
    .filter(Boolean);
}

function citationIndexForSourceLabel(label, node) {
  const targets = citationLabelVariants(label)
    .map((item) => item.replace(/^来源/, "").replace(/^source/, ""))
    .filter(Boolean);
  if (!targets.length || !node.dataset.references) return null;
  try {
    const refs = JSON.parse(node.dataset.references);
    const candidates = refs
      .map((ref) => {
        const rawLabels = [
          ref.source,
          ref.originalIndex,
          ...(Array.isArray(ref.links) ? ref.links.flatMap((link) => [link.label, link.url]) : []),
        ]
          .filter(Boolean);
        const labels = rawLabels.flatMap(citationLabelVariants);
        return { index: Number(ref.index), labels };
      })
      .filter((item) => Number.isFinite(item.index) && item.index > 0);
    const exact = candidates.find((item) =>
      item.labels.some((itemLabel) => targets.some((target) => itemLabel === target))
    );
    if (exact) return exact.index;
    const contains = candidates.find((item) =>
      item.labels.some((itemLabel) =>
        itemLabel && targets.some((target) => itemLabel.includes(target) || target.includes(itemLabel))
      )
    );
    return contains ? contains.index : null;
  } catch (e) {
    return null;
  }
}

function renderCitationMarkers(html, node) {
  const citationPattern = /\[(?:来源\s*)?(\d+(?:\s*[-–—]\s*\d+)?(?:\s*[,，；;]\s*\d+(?:\s*[-–—]\s*\d+)?)*)(?:\s*[,，:：;；]\s*[^\]\n]+)?\]/g;
  let rendered = html.replace(citationPattern, (match, expression) => {
    const indexes = expandCitationIndexes(expression);
    if (!indexes.length) return match;
    return indexes.map((idx) => citationMarkerHtml(idx, node)).join("");
  });
  const namedCitationPattern = /\[来源\s*[:：]\s*([^\]\n]+?)\]/g;
  rendered = rendered.replace(namedCitationPattern, (match, label) => {
    const idx = citationIndexForSourceLabel(label, node);
    return idx ? citationMarkerHtml(idx, node) : match;
  });
  return rendered;
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
  const usedIndexes = new Set();

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
    const requestedIndex = Number(ref.index);
    const index = Number.isFinite(requestedIndex) && requestedIndex > 0 && !usedIndexes.has(requestedIndex)
      ? requestedIndex
      : currentMax + 1;
    usedIndexes.add(index);
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
}

function hideChatApproval(requestId = "") {
  if (!els.chatApprovalBar) return;
  if (requestId && state.pendingChatApproval?.requestId !== requestId) return;
  state.pendingChatApproval = null;
  els.chatApprovalBar.hidden = true;
  els.chatApprovalBar.classList.remove("is-resolving");
  els.chatApprovalBar.innerHTML = "";
}

async function respondToChatApproval(decision, options = {}) {
  const pending = state.pendingChatApproval;
  if (!pending) return false;
  const normalizedDecision = decision === "allow" ? "allow" : "deny";
  if (els.chatApprovalBar) {
    els.chatApprovalBar.classList.add("is-resolving");
    els.chatApprovalBar.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    const status = els.chatApprovalBar.querySelector(".chat-approval-copy strong");
    if (status) status.textContent = normalizedDecision === "allow" ? "已确认，AI 正在继续" : "正在取消操作";
  }
  try {
    const response = await fetch("/api/chat-approval", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: Boolean(options.keepalive),
      body: JSON.stringify({
        requestId: pending.requestId,
        actionId: pending.actionId,
        decision: normalizedDecision,
      }),
    });
    if (!response.ok && response.status !== 404) throw new Error("审批反馈失败");
    return response.ok;
  } catch (error) {
    if (!options.silent && els.chatApprovalBar) {
      els.chatApprovalBar.classList.remove("is-resolving");
      els.chatApprovalBar.querySelectorAll("button").forEach((button) => { button.disabled = false; });
      const status = els.chatApprovalBar.querySelector(".chat-approval-copy strong");
      if (status) status.textContent = "反馈失败，请重试";
    }
    return false;
  }
}

function abandonPendingChatApproval() {
  const requestId = state.pendingChatApproval?.requestId || "";
  if (!requestId) return;
  void respondToChatApproval("deny", { keepalive: true, silent: true });
  hideChatApproval(requestId);
}

function showActionConfirmation(event) {
  if (!els.chatApprovalBar || !event.actionId || !event.requestId) return;
  state.pendingChatApproval = {
    requestId: event.requestId,
    actionId: event.actionId,
  };
  els.chatApprovalBar.hidden = false;
  els.chatApprovalBar.classList.remove("is-resolving");
  els.chatApprovalBar.innerHTML = `
    <div class="chat-approval-copy">
      <strong>需要确认：${escapeHtml(event.label || "执行操作")}</strong>
      <span>${escapeHtml(event.description || event.risk || "该操作会修改数据或触发任务。")}</span>
    </div>
    <div class="chat-approval-actions">
      <button type="button" class="quiet-button small" data-decision="deny">取消</button>
      <button type="button" class="primary-button small" data-decision="allow">确认执行</button>
    </div>
  `;
  els.chatApprovalBar.querySelectorAll("[data-decision]").forEach((button) => {
    button.addEventListener("click", () => respondToChatApproval(button.dataset.decision));
  });
}

function resetAssistantForApprovalResume(node, timeline) {
  const body = messageBody(node);
  if (!body) return;
  timeline.splice(0, timeline.length);
  body.classList.add("is-typing");
  body.innerHTML = `
    <div class="typing-ellipsis" data-placeholder="connecting" role="status" aria-live="polite">
      <span aria-hidden="true"><i>.</i><i>.</i><i>.</i></span><span class="sr-only">正在继续</span>
    </div>
  `;
}

function normalizeStoredChatRole(value) {
  const role = String(value || "").trim().toLowerCase();
  return ["assistant", "ai", "model"].includes(role) ? "assistant" : "user";
}

function normalizeStoredChatContent(value, decodeLegacyNewlines = false) {
  let content = "";
  if (typeof value === "string") {
    content = value;
  } else if (Array.isArray(value)) {
    content = value.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return "";
      return String(item.text ?? item.content ?? "");
    }).join("");
  } else if (value && typeof value === "object") {
    content = String(value.content ?? value.text ?? value.message ?? "");
  } else {
    content = String(value ?? "");
  }
  if (
    decodeLegacyNewlines &&
    !content.includes("\n") &&
    /\\n(?:#{1,6}\s|[-*]\s|\d+[.、]\s|\|)/.test(content)
  ) {
    content = content.replace(/\\r\\n|\\n/g, "\n");
  }
  return content;
}

function setMessageContent(node, content, markdown = false) {
  const text = node.querySelector(".message-text") || node.querySelector(".markdown-body");
  if (!text) return;
  const renderAsMarkdown = Boolean(markdown || node.classList.contains("assistant"));
  if (renderAsMarkdown) {
    if (text.className === "message-text") text.className = "markdown-body";
    text._rawMarkdown = String(content || "");
    const cleaned = stripAssistantControlText(content);
    let html = markdownToHtml(cleaned);
    html = renderCitationMarkers(html, node);
    text.innerHTML = html;
  } else {
    text.textContent = content;
  }
}

function rerenderAssistantMarkdown(node) {
  assistantAnswerNodes(node).forEach((textNode) => {
    if (textNode._rawMarkdown === undefined) return;
    const cleaned = stripAssistantControlText(textNode._rawMarkdown);
    let html = markdownToHtml(cleaned);
    html = renderCitationMarkers(html, node);
    textNode.innerHTML = html;
  });
}

function isMessagesNearBottom(threshold = 96) {
  if (!els.messages) return true;
  return els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight <= threshold;
}

function updateChatAutoScrollFromPosition() {
  state.chatAutoScroll = isMessagesNearBottom();
}

function scrollMessagesToBottom(options = {}) {
  if (!els.messages) return;
  const force = Boolean(options.force);
  if (!force && !state.chatAutoScroll) return;
  state.chatAutoScroll = true;
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
    body.classList.add("is-typing");
    text.className = "typing-ellipsis";
    text.dataset.placeholder = "connecting";
    text.setAttribute("role", "status");
    text.setAttribute("aria-live", "polite");
    text.innerHTML = `<span aria-hidden="true"><i>.</i><i>.</i><i>.</i></span><span class="sr-only">正在回复</span>`;
    body.appendChild(text);
    node.append(avatar, body);
    els.messages.appendChild(node);
    scrollMessagesToBottom({ force: true });
    return node;
  }
  body.appendChild(text);
  node.append(avatar, body);
  els.messages.appendChild(node);
  setMessageContent(node, content, markdown);
  scrollMessagesToBottom({ force: true });
  return node;
}

function appendUserImagePreview(node, imagePreview) {
  const body = messageBody(node);
  const dataUrl = String(imagePreview?.dataUrl || "");
  if (!body || !dataUrl.startsWith("data:image/")) return;
  const figure = document.createElement("figure");
  figure.className = "user-image-attachment";
  const image = document.createElement("img");
  image.className = "chat-user-image-preview";
  image.src = dataUrl;
  image.alt = imagePreview.name ? `已发送图片：${imagePreview.name}` : "已发送图片预览";
  image.tabIndex = 0;
  const caption = document.createElement("figcaption");
  caption.textContent = imagePreview.name || "已发送图片";
  figure.append(image, caption);
  body.insertBefore(figure, body.firstChild);
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
  const renderThreadItems = (items) => items.map((thread) => `
    <div class="chat-thread-item ${thread.id === state.activeThreadId ? "is-active" : ""}" data-thread-id="${escapeHtml(thread.id)}">
      <button class="chat-thread-main" type="button">
        <span class="chat-thread-title">${escapeHtml(thread.title || "未命名对话")}</span>
      </button>
      <button class="chat-thread-pin ${thread.pinned ? "is-pinned" : ""}" type="button" title="${thread.pinned ? "取消置顶" : "置顶"}" aria-label="${thread.pinned ? "取消置顶" : "置顶"}" data-action="pin">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 17v5"></path><path d="M8 3h8l-1 7 3 4H6l3-4z"></path></svg>
      </button>
      <button class="chat-thread-delete" type="button" title="删除" aria-label="删除">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6 6 18"></path><path d="m6 6 12 12"></path></svg>
      </button>
    </div>
  `).join("");
  const pinnedThreads = threads.filter((thread) => thread.pinned);
  const regularThreads = threads.filter((thread) => !thread.pinned);
  const sections = [];
  if (pinnedThreads.length) {
    sections.push(`
      <section class="chat-thread-section">
        <div class="chat-thread-section-title">置顶</div>
        ${renderThreadItems(pinnedThreads)}
      </section>
    `);
  }
  if (regularThreads.length) {
    sections.push(`
      <section class="chat-thread-section">
        ${pinnedThreads.length ? '<div class="chat-thread-section-title">最近</div>' : ""}
        ${renderThreadItems(regularThreads)}
      </section>
    `);
  }
  els.chatThreadList.innerHTML = sections.join("");
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

let chatPersistChain = Promise.resolve();

function persistActiveThread() {
  if (!state.activeThreadId && !state.chatHistory.length) return;
  if (!state.activeThreadId) state.activeThreadId = chatThreadId();
  const snapshotBody = JSON.stringify({
    id: state.activeThreadId,
    messages: state.chatHistory,
    agentContextKey: state.agentContextKey,
    loadedSkillIds: Array.from(state.loadedSkillIds),
  });
  chatPersistChain = chatPersistChain.catch(() => {}).then(async () => {
    try {
      const response = await fetch("/api/chat-threads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: snapshotBody,
      });
      const payload = await response.json();
      if (!payload.ok) throw new Error(payload.error || "保存失败");
      state.activeThreadId = payload.thread && payload.thread.id ? payload.thread.id : state.activeThreadId;
      state.chatThreads = Array.isArray(payload.threads) ? payload.threads : state.chatThreads;
      renderChatThreadList();
    } catch (error) {
      console.warn("保存历史对话失败", error);
    }
  });
  return chatPersistChain;
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
      state.chatHistory.forEach((item) => {
        const role = normalizeStoredChatRole(item && item.role);
        const content = normalizeStoredChatContent(item && item.content, role === "assistant");
        const normalizedItem = { ...(item || {}), role, content };
        const displayContent = role === "user" && item && item.displayContent
          ? normalizeStoredChatContent(item.displayContent)
          : content;
        const node = addMessage(role, displayContent, role === "assistant");
        if (role === "user" && item && item.imagePreview) {
          appendUserImagePreview(node, item.imagePreview);
        }
        restoreAssistantMessageExtras(node, normalizedItem);
      });
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
      <span class="queued-message-text">${item.options && item.options.displayImage ? "[图片] " : ""}${escapeHtml((item.options && item.options.displayMessage) || item.message)}</span>
      <button class="queued-message-action queued-message-steer" type="button" data-action="steer" title="停止当前回答并立即发送这条消息">插队</button>
      <button class="queued-message-action" type="button" data-action="edit">修改</button>
      <button class="queued-message-action" type="button" data-action="remove">撤回</button>
    </div>
  `).join("");
}

function enqueueChatMessage(message, options = {}) {
  state.chatQueue.push({ id: chatThreadId(), message, options });
  renderChatQueue();
}

function processNextQueuedChat() {
  if (state.chatBusy || !state.chatQueue.length) return;
  const next = state.chatQueue.shift();
  renderChatQueue();
  if (next && next.message) sendChat(next.message, next.options || {});
}

function setChatSidebarCollapsed(collapsed) {
  if (!els.chatWorkspace) return;
  els.chatWorkspace.classList.toggle("is-sidebar-collapsed", collapsed);
  if (els.toggleChatThreadsButton) {
    els.toggleChatThreadsButton.title = collapsed ? "展开历史对话" : "收起历史对话";
    els.toggleChatThreadsButton.setAttribute("aria-label", collapsed ? "展开历史对话" : "收起历史对话");
  }
}

function setChatThreadSearchOpen(open, focus = false) {
  state.chatThreadSearchOpen = Boolean(open);
  if (els.chatThreadSidebar) {
    els.chatThreadSidebar.classList.toggle("is-search-open", state.chatThreadSearchOpen);
  }
  if (els.chatThreadSearchToggle) {
    els.chatThreadSearchToggle.classList.toggle("is-active", state.chatThreadSearchOpen);
    els.chatThreadSearchToggle.setAttribute("aria-expanded", state.chatThreadSearchOpen ? "true" : "false");
    els.chatThreadSearchToggle.title = state.chatThreadSearchOpen ? "收起搜索" : "搜索对话";
    els.chatThreadSearchToggle.setAttribute("aria-label", state.chatThreadSearchOpen ? "收起搜索" : "搜索对话");
  }
  if (focus && state.chatThreadSearchOpen && els.chatThreadSearchInput) {
    requestAnimationFrame(() => els.chatThreadSearchInput.focus());
  }
}

function clearConnectingPlaceholder(node) {
  const body = messageBody(node);
  const placeholder = body?.querySelector('[data-placeholder="connecting"]');
  if (placeholder) placeholder.remove();
  if (body) body.classList.remove("is-typing");
}

function messageBody(node) {
  return node.querySelector(".message-body");
}

function collapseLatestModelReasoning(node) {
  const panels = messageBody(node)?.querySelectorAll(".model-reasoning") || [];
  panels.forEach((panel) => {
    panel.open = false;
  });
}

function ensureToolList(node) {
  const body = messageBody(node);
  if (!body) return null;
  let list = body.lastElementChild;
  if (!list || !list.classList.contains("tool-call-list")) {
    list = document.createElement("div");
    list.className = "tool-call-list";
    appendStreamBlock(node, list);
  }
  return list;
}

function appendStreamBlock(node, element) {
  const body = messageBody(node);
  if (!body || !element) return null;
  collapseLatestModelReasoning(node);
  body.appendChild(element);
  return element;
}

function assistantAnswerNodes(node) {
  const body = messageBody(node);
  if (!body) return [];
  return Array.from(body.children).filter(
    (child) => child.classList.contains("message-text") || child.classList.contains("markdown-body")
  );
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
    clearConnectingPlaceholder(node);
    text = document.createElement("div");
    text.className = "message-text";
    text._rawMarkdown = "";
    body.appendChild(text);
  }
  if (node.classList.contains("assistant")) {
    text.dataset.assistantAnswer = "true";
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

function appendStableChartImage(node, chartImage) {
  const body = messageBody(node);
  if (!body || !chartImage || !chartImage.url) return;
  const existing = body.querySelector(`.chart-result-block[data-chart-url="${CSS.escape(chartImage.url)}"]`);
  if (existing) return;
  const block = document.createElement("div");
  block.className = "chart-result-block";
  block.dataset.chartUrl = chartImage.url;
  block.innerHTML = inlineMarkdown(chartImage.markdown);
  appendStreamBlock(node, block);
}

function appendAssistantActionLine(node, event) {
  const body = messageBody(node);
  if (!body || !event || event.type !== "tool_call_start") return;
  const label = event.processText || toolNarrationText(event.name);
  if (!label) return;
  const id = event.id || `${event.name || "tool"}-${node.querySelectorAll(".assistant-action-line").length}`;
  const existing = node.querySelector(`.assistant-action-line[data-tool-id="${CSS.escape(id)}"]`);
  if (existing) return;
  const line = document.createElement("div");
  line.className = "assistant-action-line";
  line.dataset.toolId = id;
  line.dataset.toolName = event.name || "";
  line.innerHTML = inlineMarkdown(label);
  appendStreamBlock(node, line);
}

function appendAssistantProcessLine(node, text, beforeNode = null, preferredToolName = "") {
  const body = messageBody(node);
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!body || !clean) return;
  const key = clean.slice(0, 240);
  const toolName = preferredToolName || processLineToolAnchorName(clean);
  const isModelProcessSentence = /^(?:我先|我来|让我|现在让我|我需要|为了|需要|我读取|我确认|我联网|我同步|我打开|我调用)/.test(clean);
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
  line.innerHTML = inlineMarkdown(clean);
  if (beforeNode && beforeNode.parentNode === body) {
    body.insertBefore(line, beforeNode);
  } else {
    body.appendChild(line);
  }
  dedupeAssistantProcessLines(node);
}

function dedupeAssistantProcessLines(node) {
  const body = messageBody(node);
  if (!body) return;
  const seenTools = new Map();
  [...body.querySelectorAll(".assistant-process-line")].forEach((line) => {
    const toolName = line.dataset.toolName || processLineToolAnchorName(line.textContent || "");
    if (!toolName) return;
    const existing = seenTools.get(toolName);
    if (!existing) {
      seenTools.set(toolName, line);
      return;
    }
    const existingIsTyped = existing.dataset.fromTypedEvent === "true";
    const lineIsTyped = line.dataset.fromTypedEvent === "true";
    if (lineIsTyped && !existingIsTyped) {
      existing.remove();
      seenTools.set(toolName, line);
    } else {
      line.remove();
    }
  });
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
  const { answer: contentWithoutProcess } = extractAssistantProcessLines(rawContent);
  setCurrentMessageContent(node, contentWithoutProcess, markdown, target);
  return contentWithoutProcess;
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
  appendStreamBlock(node, footer);
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

function renderAssistantToolEvent(node, event, insertedChartUrls = null) {
  if (event.type === "tool_call_start") {
    appendAssistantActionLine(node, event);
  }
  appendToolCallCard(node, event);
  if (event.type === "tool_call_result" && event.name === "render_python_chart") {
    const chartImage = extractFirstMarkdownImage(event.content);
    if (chartImage && (!insertedChartUrls || !insertedChartUrls.has(chartImage.url))) {
      if (insertedChartUrls) insertedChartUrls.add(chartImage.url);
      appendStableChartImage(node, chartImage);
    }
  }
}

function appendAssistantTimelineText(timeline, text) {
  const value = String(text || "");
  if (!value) return;
  const last = timeline[timeline.length - 1];
  if (last && last.type === "text") {
    last.text += value;
  } else {
    timeline.push({ type: "text", text: value });
  }
}

function appendAssistantTimelineReasoning(timeline, text) {
  const value = String(text || "");
  if (!value) return;
  const last = timeline[timeline.length - 1];
  if (last && last.type === "reasoning") {
    last.text += value;
  } else {
    timeline.push({ type: "reasoning", text: value });
  }
}

function scrollReasoningToLatest(content) {
  if (!content) return;
  const scroll = () => {
    content.scrollTop = content.scrollHeight;
  };
  scroll();
  requestAnimationFrame(scroll);
}

function appendModelReasoning(node, text) {
  const body = messageBody(node);
  const value = String(text || "");
  if (!body || !value) return;
  clearConnectingPlaceholder(node);
  let panel = body.lastElementChild;
  if (!panel || !panel.classList.contains("model-reasoning")) {
    panel = document.createElement("details");
    panel.className = "model-reasoning";
    panel.open = true;
    panel.innerHTML = `
      <summary><span class="model-reasoning-caret">⌄</span><span>推理过程</span></summary>
      <div class="model-reasoning-content"></div>
    `;
    body.appendChild(panel);
  }
  const content = panel.querySelector(".model-reasoning-content");
  if (!content) return;
  content._rawReasoning = `${content._rawReasoning || ""}${value}`;
  content.innerHTML = markdownToHtml(content._rawReasoning);
  scrollReasoningToLatest(content);
}

function assistantTimelineToolEvent(event) {
  return {
    type: event.type,
    id: event.id || "",
    name: event.name || "",
    processText: event.processText || "",
    args: event.args || "",
    content: event.content || "",
  };
}

function restoreAssistantTimeline(node, timeline) {
  if (!Array.isArray(timeline) || !timeline.length) return false;
  const body = messageBody(node);
  if (!body) return false;
  body.innerHTML = "";
  const insertedChartUrls = new Set();
  timeline.forEach((event) => {
    if (!event || typeof event !== "object") return;
    if (event.type === "reasoning") {
      appendModelReasoning(node, event.text);
      return;
    }
    if (event.type === "text") {
      const textNode = document.createElement("div");
      textNode.className = "markdown-body";
      textNode.dataset.assistantAnswer = "true";
      textNode._rawMarkdown = String(event.text || "");
      appendStreamBlock(node, textNode);
      setCurrentMessageContent(node, textNode._rawMarkdown, true, textNode);
      return;
    }
    if (event.type === "tool_call_start" || event.type === "tool_call_result") {
      renderAssistantToolEvent(node, event, insertedChartUrls);
    }
  });
  collapseLatestModelReasoning(node);
  return body.children.length > 0;
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

function suggestionChipsHtml(items) {
  const arr = normalizeSuggestionList(items);
  if (!arr.length) return "";
  return `<div class="suggestion-chips">` + arr.map((q) => `<button type="button" class="suggestion-chip" onclick="clickSuggestion(this.innerText)">${escapeHtml(q)}</button>`).join("") + `</div>`;
}

function parseSuggestionTag(value) {
  const match = String(value || "").match(/<suggestions>\s*([\s\S]*?)\s*<\/suggestions>/i);
  if (!match) return [];
  try {
    let jsonStr = match[1].trim();
    jsonStr = jsonStr.replace(/^```json/i, "").replace(/^```/i, "").replace(/```$/i, "").trim();
    return normalizeSuggestionList(JSON.parse(jsonStr));
  } catch (e) {
    return [];
  }
}

function estimateChatTokens(value) {
  const text = String(value || "");
  let asciiChars = 0;
  for (const char of text) {
    if (char.codePointAt(0) < 128) asciiChars += 1;
  }
  return Math.max(1, Math.round(asciiChars / 4 + (text.length - asciiChars) * 0.9));
}

function normalizeAssistantMetrics(metrics, fallbackText = "", fallbackDurationMs = 0) {
  const usage = metrics && typeof metrics.usage === "object" ? metrics.usage : metrics || {};
  const inputTokens = Number(usage.inputTokens || 0);
  const outputTokens = Number(usage.outputTokens || 0);
  const reportedTotal = Number(usage.totalTokens || 0);
  const totalTokens = reportedTotal || inputTokens + outputTokens || estimateChatTokens(fallbackText);
  const durationMs = Math.max(0, Number(metrics?.durationMs || fallbackDurationMs || 0));
  return {
    inputTokens,
    outputTokens,
    totalTokens,
    durationMs,
    estimated: Boolean(usage.estimated || !reportedTotal),
  };
}

function formatAssistantDuration(durationMs) {
  const seconds = Math.max(0, Number(durationMs || 0)) / 1000;
  if (seconds < 10) return `${seconds.toFixed(1)} 秒`;
  if (seconds < 60) return `${Math.round(seconds)} 秒`;
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return remaining ? `${minutes} 分 ${remaining} 秒` : `${minutes} 分钟`;
}

function appendAssistantMetrics(node, metrics) {
  const body = messageBody(node);
  if (!body || !metrics) return;
  body.querySelector(".assistant-response-metrics")?.remove();
  const normalized = normalizeAssistantMetrics(metrics);
  const meta = document.createElement("div");
  meta.className = "assistant-response-metrics";
  meta.textContent = `${normalized.estimated ? "约 " : ""}${normalized.totalTokens.toLocaleString("en-US")} tokens · ${formatAssistantDuration(normalized.durationMs)}`;
  if (normalized.inputTokens || normalized.outputTokens) {
    meta.title = `输入 ${normalized.inputTokens.toLocaleString("en-US")} tokens · 输出 ${normalized.outputTokens.toLocaleString("en-US")} tokens`;
  }
  body.appendChild(meta);
}

function restoreAssistantMessageExtras(node, item) {
  if (!node || !item || item.role !== "assistant") return;
  const references = Array.isArray(item.references) ? item.references : [];
  const links = Array.isArray(item.links) ? item.links : [];
  const suggestions = normalizeSuggestionList(item.suggestions || parseSuggestionTag(item.content));
  if (references.length) node.dataset.references = JSON.stringify(references);
  if (links.length) node.dataset.links = JSON.stringify(links);
  restoreAssistantTimeline(node, item.timeline);
  if (references.length || links.length) {
    rerenderAssistantMarkdown(node);
  }
  const answerNodes = assistantAnswerNodes(node);
  const textNode = answerNodes[answerNodes.length - 1] || null;
  const chips = suggestionChipsHtml(suggestions);
  if (textNode && chips && !textNode.querySelector(".suggestion-chips")) {
    textNode.insertAdjacentHTML("beforeend", chips);
  }
  if (references.length || links.length) {
    appendCitationFooter(node, references, links);
  }
  if (item.metrics) appendAssistantMetrics(node, item.metrics);
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
  const chatStartedAt = performance.now();
  const chatRequestId = chatThreadId();
  if (!state.activeThreadId) state.activeThreadId = chatThreadId();
  const conversationHistory = compactChatHistory();
  const displayMessage = options.displayMessage || message;
  const userNode = addMessage("user", displayMessage);
  if (options.displayImage) appendUserImagePreview(userNode, options.displayImage);
  const userHistoryEntry = { role: "user", content: message, displayContent: displayMessage };
  if (options.displayImage) userHistoryEntry.imagePreview = options.displayImage;
  state.chatHistory.push(userHistoryEntry);
  state.chatHistory = state.chatHistory.slice(-80);
  const requestController = new AbortController();
  requestController.requestId = chatRequestId;
  state.chatAbortController = requestController;
  state.chatStopRequested = false;
  setChatBusy(true);
  let chatTurnReleased = false;
  const releaseChatTurn = () => {
    if (chatTurnReleased) return;
    chatTurnReleased = true;
    if (state.chatAbortController !== requestController) return;
    state.chatAbortController = null;
    state.chatStopRequested = false;
    setChatBusy(false);
    els.chatInput.focus();
    processNextQueuedChat();
  };
  let assistantNode = null;
  let assistantHistoryEntry = null;
  let draftPersistTimer = null;
  let assistantDraftRaw = "";
  let stopStreamingRender = null;
  const assistantTimeline = [];
  const setAssistantDraftContent = (content) => {
    if (!assistantHistoryEntry) return;
    const clean = stripAssistantControlText(String(content || "").trim());
    assistantHistoryEntry.content = clean || "正在分析请求，并调用相关工具获取依据。";
    assistantHistoryEntry.partial = true;
  };
  const scheduleDraftPersist = () => {
    if (!assistantHistoryEntry || draftPersistTimer) return;
    draftPersistTimer = window.setTimeout(() => {
      draftPersistTimer = null;
      persistActiveThread();
    }, 1200);
  };
  const flushDraftPersist = async () => {
    if (draftPersistTimer) {
      window.clearTimeout(draftPersistTimer);
      draftPersistTimer = null;
    }
    await persistActiveThread();
  };
  try {
    assistantNode = addMessage("assistant", "正在连接...");
    assistantHistoryEntry = {
      role: "assistant",
      content: "正在分析请求，并调用相关工具获取依据。",
      timeline: assistantTimeline,
      partial: true,
    };
    state.chatHistory.push(assistantHistoryEntry);
    state.chatHistory = state.chatHistory.slice(-80);
    await persistActiveThread();
    const webSearchEnabled = Boolean(state.webSearchEnabled);
    const selectedSkillIds = Array.from(state.selectedSkillIds);
    const selectedDatasetIds = Array.from(state.selectedDatasetIds);
    const contextKey = currentAgentContextKey(selectedSkillIds, selectedDatasetIds);
    const emitContextEvents = false;
    const loadedSkillIds = Array.from(state.loadedSkillIds);
    const approvedActionIds = Array.isArray(options.approvedActionIds) ? options.approvedActionIds : [];
    const response = await fetch("/api/chat-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: requestController.signal,
      body: JSON.stringify({
        requestId: chatRequestId,
        message,
        webSearchEnabled,
        thinkingEnabled: false,
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
    let isDone = false;
    let responseMetrics = null;
    let collapseReasoningOnNextDelta = false;
    let streamQueue = "";
    let streamTimer = null;

    const renderStreamingMarkdown = (textNode) => {
      textNode.classList.remove("message-text");
      textNode.classList.add("markdown-body");
      textNode.dataset.assistantAnswer = "true";
      let displayAnswer = textNode._rawMarkdown || "";
      const parsedSuggestions = parseSuggestionTag(displayAnswer);
      let suggestionsHTML = "";
      if (parsedSuggestions.length) {
        displayAnswer = displayAnswer.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
        suggestionsHTML = suggestionChipsHtml(parsedSuggestions);
      }
      const cleaned = stripAssistantControlText(displayAnswer);
      let html = markdownToHtml(cleaned);
      html = renderCitationMarkers(html, assistantNode);
      textNode.innerHTML = html;
      if (suggestionsHTML) {
        textNode.insertAdjacentHTML("beforeend", suggestionsHTML);
      }
    };

    const flushStreamQueue = (flushAll = false) => {
      if (!streamQueue) return;
      const textNode = currentMessageTextNode(assistantNode);
      if (textNode._rawMarkdown === undefined) textNode._rawMarkdown = "";
      textNode.classList.add("is-streaming-token");
      const sliceSize = flushAll ? streamQueue.length : Math.min(streamQueue.length, Math.max(3, Math.min(18, Math.ceil(streamQueue.length / 4))));
      textNode._rawMarkdown += streamQueue.slice(0, sliceSize);
      streamQueue = streamQueue.slice(sliceSize);
      renderStreamingMarkdown(textNode);
      scrollMessagesToBottom();
      if (streamQueue && !flushAll) {
        streamTimer = window.setTimeout(() => {
          streamTimer = null;
          flushStreamQueue(false);
        }, 24);
      }
    };

    const queueStreamingText = (chunk) => {
      if (!chunk) return;
      streamQueue += chunk;
      const textNode = currentMessageTextNode(assistantNode);
      textNode.classList.add("is-streaming-token");
      if (!streamTimer) {
        streamTimer = window.setTimeout(() => {
          streamTimer = null;
          flushStreamQueue(false);
        }, 8);
      }
    };

    const finishStreamingText = () => {
      if (streamTimer) {
        window.clearTimeout(streamTimer);
        streamTimer = null;
      }
      flushStreamQueue(true);
      assistantAnswerNodes(assistantNode).forEach((textNode) => textNode.classList.remove("is-streaming-token"));
    };
    stopStreamingRender = finishStreamingText;

    const renderToolEvent = (event) => {
      renderAssistantToolEvent(assistantNode, event, insertedChartUrls);
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
        
        if (event.type === "done") {
          isDone = true;
          break;
        } else if (event.type === "run_summary") {
          responseMetrics = normalizeAssistantMetrics(event, `${message}\n${answer}`, performance.now() - chatStartedAt);
        } else if (event.type === "reasoning") {
          clearConnectingPlaceholder(assistantNode);
          collapseReasoningOnNextDelta = true;
          appendAssistantTimelineReasoning(assistantTimeline, event.text);
          assistantHistoryEntry.timeline = assistantTimeline;
          appendModelReasoning(assistantNode, event.text);
          scheduleDraftPersist();
          scrollMessagesToBottom();
        } else if (event.type === "meta") {
          finishStreamingText();
          mergeCitationMeta(assistantNode, event);
          rerenderAssistantMarkdown(assistantNode);
        } else if (event.type === "action_confirmation") {
          finishStreamingText();
          showActionConfirmation(event);
        } else if (event.type === "approval_result") {
          finishStreamingText();
          hideChatApproval(event.requestId);
          resetAssistantForApprovalResume(assistantNode, assistantTimeline);
          answer = "";
          assistantDraftRaw = "";
          responseMetrics = null;
          collapseReasoningOnNextDelta = false;
          insertedChartUrls.clear();
          if (assistantHistoryEntry) {
            assistantHistoryEntry.content = "正在根据您的决定继续处理。";
            assistantHistoryEntry.timeline = assistantTimeline;
            assistantHistoryEntry.partial = true;
          }
          scheduleDraftPersist();
        } else if (event.type === "tool_call_start" || event.type === "tool_call_result") {
          if (event.type === "tool_call_result" && event.name === "read_agent_skill" && event.args) {
            try {
              const parsedArgs = JSON.parse(event.args);
              if (parsedArgs && parsedArgs.skill_id) state.loadedSkillIds.add(String(parsedArgs.skill_id));
            } catch (e) {}
          }
          finishStreamingText();
          clearConnectingPlaceholder(assistantNode);
          assistantTimeline.push(assistantTimelineToolEvent(event));
          assistantHistoryEntry.timeline = assistantTimeline;
          renderToolEvent(event);
          scheduleDraftPersist();
          scrollMessagesToBottom();
        } else if (event.type === "delta" || event.type === "error" || event.type === "tool_start") {
          let textChunk = "";
          if (event.type === "delta") {
            if (collapseReasoningOnNextDelta) {
              collapseLatestModelReasoning(assistantNode);
              collapseReasoningOnNextDelta = false;
            }
            textChunk = event.text;
          } else if (event.type === "error") {
            textChunk = `\n\n**错误：** ${event.text}`;
          } else if (event.type === "tool_start") {
            const label = escapeHtml(toolFriendlyName(event.name));
            const technicalName = escapeHtml(event.name || "tool");
            const icon = iconSvg(toolIconName(event.name));
            textChunk = `\n\n<div class="inline-tool-event"><span class="tool-icon" aria-hidden="true">${icon}</span><strong>${label}</strong><code>${technicalName}</code></div>\n\n`;
          }

          answer += textChunk;
          appendAssistantTimelineText(assistantTimeline, textChunk);
          assistantHistoryEntry.timeline = assistantTimeline;
          assistantDraftRaw = answer;
          setAssistantDraftContent(answer);
          scheduleDraftPersist();
          queueStreamingText(textChunk);
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
    if (!isDone) {
      const streamError = new Error("回答连接意外中断，未收到完成信号，请重新发送。已生成的内容仅供参考。");
      streamError.code = "STREAM_INCOMPLETE";
      throw streamError;
    }
    finishStreamingText();
    collapseLatestModelReasoning(assistantNode);

    if (!answer.trim()) {
      const textNode = currentMessageTextNode(assistantNode);
      textNode.innerHTML = "<p>操作完成。</p>";
      textNode._rawMarkdown = "操作完成。";
      appendAssistantTimelineText(assistantTimeline, "操作完成。");
      if (assistantHistoryEntry) {
        assistantHistoryEntry.content = "操作完成。";
        assistantHistoryEntry.timeline = assistantTimeline;
        delete assistantHistoryEntry.partial;
      }
      state.agentContextKey = contextKey;
    } else {
      const textNodes = assistantAnswerNodes(assistantNode);
      const textNode = textNodes[textNodes.length - 1] || currentMessageTextNode(assistantNode);
      let finalSuggestions = [];
      let suggestionsHTML = "";
      let llmCitationText = null;
      textNodes.forEach((segmentNode, index) => {
        let finalChunk = segmentNode._rawMarkdown || "";
        if (index === textNodes.length - 1) {
          finalSuggestions = parseSuggestionTag(finalChunk);
          if (finalSuggestions.length) {
            finalChunk = finalChunk.replace(/<suggestions>[\s\S]*?<\/suggestions>/i, "").trim();
            suggestionsHTML = suggestionChipsHtml(finalSuggestions);
          }
        }
        const citationTagMatch = finalChunk.match(/<引用来源>([\s\S]*?)<\/引用来源>/i);
        if (citationTagMatch) llmCitationText = citationTagMatch[1].trim();
        finalChunk = finalChunk.replace(/<引用来源>[\s\S]*?<\/引用来源>/gi, "").trim();
        finalChunk = finalChunk.replace(/<引用来源>[\s\S]*$/gi, "").trim();
        finalChunk = finalChunk.replace(/\\<引用来源\\>[\s\S]*$/gi, "").trim();
        finalChunk = finalChunk.replace(/\[引用来源\][\s\S]*$/gi, "").trim();
        segmentNode._rawMarkdown = finalChunk;
        const cleanedChunk = stripAssistantControlText(finalChunk);
        let html = markdownToHtml(cleanedChunk);
        html = renderCitationMarkers(html, assistantNode);
        segmentNode.innerHTML = html;
      });

      // Inject citation footer if we have reference data
      const storedRefs = assistantNode.dataset.references ? JSON.parse(assistantNode.dataset.references) : null;
      const storedLinks = assistantNode.dataset.links ? JSON.parse(assistantNode.dataset.links) : null;
      let persistedRefs = storedRefs || [];
      let persistedLinks = storedLinks || [];
      if (storedRefs || storedLinks) {
        appendCitationFooter(assistantNode, storedRefs, storedLinks);
      } else if (llmCitationText) {
        const fallbackRefs = [];
        const lines = llmCitationText.split(/\n|(?=\[来源\s*\d+\])/g);
        for (const line of lines) {
          const m = line.match(/\[来源\s*(\d+)(?:\s*[,，:：;；]\s*([^\]\n]+))?\]\s*([^—\n]*)/);
          if (m) {
            const idx = parseInt(m[1]);
            const src = (m[3] || m[2] || `来源 ${idx}`).trim();
            fallbackRefs.push({ index: idx, source: src, links: [{ label: src, url: `/references/${src}` }] });
          }
        }
        if (fallbackRefs.length) {
          persistedRefs = fallbackRefs;
          appendCitationFooter(assistantNode, fallbackRefs, null);
        }
      }

      if (suggestionsHTML) {
        textNode.insertAdjacentHTML("beforeend", suggestionsHTML);
      } else {
        finalSuggestions = generateFallbackSuggestions(message);
        const fallbackHTML = suggestionChipsHtml(finalSuggestions);
        textNode.insertAdjacentHTML("beforeend", fallbackHTML);
      }

      if (answer.trim()) {
        if (assistantHistoryEntry) {
          assistantHistoryEntry.content = stripAssistantControlText(answer).trim();
          assistantHistoryEntry.timeline = assistantTimeline;
          assistantHistoryEntry.references = persistedRefs;
          assistantHistoryEntry.links = persistedLinks;
          assistantHistoryEntry.suggestions = finalSuggestions;
          delete assistantHistoryEntry.partial;
        }
      }
      state.agentContextKey = contextKey;
      scrollMessagesToBottom();
    }
    const finalMetrics = responseMetrics || normalizeAssistantMetrics(
      null,
      `${message}\n${assistantTimeline.map((event) => event.text || event.content || "").join("\n")}`,
      performance.now() - chatStartedAt,
    );
    appendAssistantMetrics(assistantNode, finalMetrics);
    if (assistantHistoryEntry) assistantHistoryEntry.metrics = finalMetrics;
    const completionPersist = flushDraftPersist();
    releaseChatTurn();
    await completionPersist;
    fetchStatus().catch((error) => console.warn("回答完成后刷新状态失败", error));
  } catch (error) {
    hideChatApproval(chatRequestId);
    if (stopStreamingRender) stopStreamingRender();
    if (assistantNode) collapseLatestModelReasoning(assistantNode);
    const stopped = state.chatStopRequested || error.name === "AbortError";
    const steered = Boolean(requestController.steerRequested);
    const streamIncomplete = error.code === "STREAM_INCOMPLETE";
    const stoppedText = assistantDraftRaw.trim()
      ? `${stripAssistantControlText(assistantDraftRaw).trim()}\n\n${steered ? "（已收到插队消息，当前回答已停止）" : "（已暂停生成）"}`
      : steered ? "已收到插队消息，当前回答已停止。" : "已暂停生成。";
    const failureText = streamIncomplete && assistantDraftRaw.trim()
      ? `${stripAssistantControlText(assistantDraftRaw).trim()}\n\n（连接意外中断，本次回答未完成，请重新发送。）`
      : `处理失败：${error.message}`;
    if (assistantNode) {
      clearConnectingPlaceholder(assistantNode);
      const textNode = currentMessageTextNode(assistantNode);
      setCurrentMessageContent(assistantNode, stopped ? stoppedText : failureText, stopped, textNode);
    } else {
      addMessage("assistant", stopped ? stoppedText : failureText, stopped);
    }
    if (assistantHistoryEntry) {
      assistantHistoryEntry.content = stopped ? stoppedText : failureText;
      if (stopped) {
        appendAssistantTimelineText(
          assistantTimeline,
          steered ? "\n\n（已收到插队消息，当前回答已停止）" : "\n\n（已暂停生成）",
        );
        assistantHistoryEntry.timeline = assistantTimeline;
      }
      assistantHistoryEntry.metrics = normalizeAssistantMetrics(
        null,
        `${message}\n${assistantDraftRaw}`,
        performance.now() - chatStartedAt,
      );
      appendAssistantMetrics(assistantNode, assistantHistoryEntry.metrics);
      delete assistantHistoryEntry.partial;
    } else {
      state.chatHistory.push({ role: "assistant", content: stopped ? stoppedText : failureText });
      state.chatHistory = state.chatHistory.slice(-80);
    }
    const interruptedPersist = flushDraftPersist();
    releaseChatTurn();
    await interruptedPersist;
  } finally {
    hideChatApproval(chatRequestId);
    releaseChatTurn();
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
      els.aiSettingsModal.hidden = true;
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

if (els.fetchAiModels) {
  els.fetchAiModels.addEventListener("click", () => {
    fetchAiModels().catch((error) => {
      if (els.aiModelHint) els.aiModelHint.textContent = error.message || String(error);
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
  testAiConfig().catch((error) => {
    els.aiConfigStatus.textContent = `连接失败：${error.message || String(error)}`;
  });
});

els.clearLogButton.addEventListener("click", () => {
  state.agentTraceLoaded = false;
  setLog("当前显示已清空；持久化历史日志未删除。");
});

els.logButton.addEventListener("click", () => {
  els.logModal.hidden = false;
  loadCrawlRuns({ selectLatest: !state.activeCrawlRunId, selectRunId: state.activeCrawlRunId || "" });
});

if (els.refreshCrawlRunsButton) {
  els.refreshCrawlRunsButton.addEventListener("click", () => {
    loadCrawlRuns({ selectLatest: !state.activeCrawlRunId, selectRunId: state.activeCrawlRunId || "" });
  });
}

function closeCrawlLogModal() {
  if (els.logModal) els.logModal.hidden = true;
  stopCrawlLogPolling();
}

if (els.closeLogButton) els.closeLogButton.addEventListener("click", closeCrawlLogModal);
if (els.logModal) els.logModal.addEventListener("click", (e) => { if (e.target === els.logModal) closeCrawlLogModal(); });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopCrawlLogPolling();
  } else if (crawlLogModalIsOpen()) {
    loadCrawlRuns({ selectLatest: !state.activeCrawlRunId, selectRunId: state.activeCrawlRunId || "" });
  }
});

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

if (els.messages) {
  els.messages.addEventListener("scroll", updateChatAutoScrollFromPosition, { passive: true });
  els.messages.addEventListener("wheel", () => {
    window.requestAnimationFrame(updateChatAutoScrollFromPosition);
  }, { passive: true });
  els.messages.addEventListener("touchmove", () => {
    window.requestAnimationFrame(updateChatAutoScrollFromPosition);
  }, { passive: true });
}

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

if (els.chatThreadSearchToggle) {
  els.chatThreadSearchToggle.addEventListener("click", () => {
    const nextOpen = !state.chatThreadSearchOpen;
    if (!nextOpen && els.chatThreadSearchInput && els.chatThreadSearchInput.value) {
      els.chatThreadSearchInput.value = "";
      state.chatThreadSearch = "";
      renderChatThreadList();
    }
    setChatThreadSearchOpen(nextOpen, nextOpen);
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
    if (action === "steer") {
      state.chatQueue = state.chatQueue.filter((entry) => entry.id !== queueId);
      state.chatQueue.unshift(queued);
      renderChatQueue();
      if (state.chatBusy && state.chatAbortController) {
        abandonPendingChatApproval();
        state.chatStopRequested = true;
        state.chatAbortController.steerRequested = true;
        state.chatAbortController.abort();
      } else {
        processNextQueuedChat();
      }
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
    state.webSearchEnabled = !state.webSearchEnabled;
    if (els.composerPlusMenu) els.composerPlusMenu.hidden = true;
    els.composerPlusButton?.setAttribute("aria-expanded", "false");
    if (els.skillMenu) els.skillMenu.hidden = true;
    if (els.databaseMenu) els.databaseMenu.hidden = true;
    if (els.chatModelMenu) els.chatModelMenu.hidden = true;
    els.chatModelButton?.setAttribute("aria-expanded", "false");
    renderWebSearchToggle();
    renderSkillToggle();
    renderDatabaseToggle();
    els.chatInput.focus();
  });
}

if (els.skillToggle) {
  renderSkillToggle();
  loadAgentSkills();
  els.skillToggle.addEventListener("click", () => {
    if (!els.skillMenu) return;
    const willOpen = els.skillMenu.hidden;
    els.skillMenu.hidden = !willOpen;
    if (willOpen && els.databaseMenu) els.databaseMenu.hidden = true;
    if (willOpen && els.composerPlusMenu) {
      els.composerPlusMenu.hidden = true;
      els.composerPlusButton?.setAttribute("aria-expanded", "false");
    }
    if (willOpen && els.chatModelMenu) {
      els.chatModelMenu.hidden = true;
      els.chatModelButton?.setAttribute("aria-expanded", "false");
    }
    renderSkillToggle();
    renderDatabaseToggle();
  });
}

if (els.databaseToggle) {
  renderDatabaseToggle();
  loadAgentDatasets();
  els.databaseToggle.addEventListener("click", () => {
    if (!els.databaseMenu) return;
    const willOpen = els.databaseMenu.hidden;
    els.databaseMenu.hidden = !willOpen;
    if (willOpen && els.skillMenu) els.skillMenu.hidden = true;
    if (willOpen && els.composerPlusMenu) {
      els.composerPlusMenu.hidden = true;
      els.composerPlusButton?.setAttribute("aria-expanded", "false");
    }
    if (willOpen && els.chatModelMenu) {
      els.chatModelMenu.hidden = true;
      els.chatModelButton?.setAttribute("aria-expanded", "false");
    }
    renderDatabaseToggle();
    renderSkillToggle();
  });
}

if (els.knowledgeUploadInput) {
  els.knowledgeUploadInput.addEventListener("change", () => {
    const file = els.knowledgeUploadInput.files && els.knowledgeUploadInput.files[0];
    if (!file) return;
    state.knowledgeUploadFile = file;
    state.knowledgeUploadOpen = true;
    if (els.databaseMenu) els.databaseMenu.hidden = false;
    renderDatabaseMenu();
  });
}

if (els.composerPlusButton) {
  els.composerPlusButton.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = els.composerPlusMenu.hidden;
    els.composerPlusMenu.hidden = !willOpen;
    if (willOpen && els.skillMenu) els.skillMenu.hidden = true;
    if (willOpen && els.databaseMenu) els.databaseMenu.hidden = true;
    if (willOpen && els.chatModelMenu) {
      els.chatModelMenu.hidden = true;
      els.chatModelButton?.setAttribute("aria-expanded", "false");
    }
    renderSkillToggle();
    renderDatabaseToggle();
    els.composerPlusButton.setAttribute("aria-expanded", els.composerPlusMenu.hidden ? "false" : "true");
  });
}

if (els.composerUploadFileButton) {
  els.composerUploadFileButton.addEventListener("click", () => els.knowledgeUploadInput && els.knowledgeUploadInput.click());
}

if (els.composerUploadImageButton) {
  els.composerUploadImageButton.addEventListener("click", () => {
    if (!modelSupportsImages(state.chatModel)) return;
    if (els.chatImageInput) els.chatImageInput.click();
  });
}

if (els.chatImageInput) {
  els.chatImageInput.addEventListener("change", () => {
    const file = els.chatImageInput.files && els.chatImageInput.files[0];
    if (!file) return;
    if (!modelSupportsImages(state.chatModel)) {
      showTaskOperationNotice("当前模型不支持图片，请先切换到视觉模型。");
      els.chatImageInput.value = "";
      return;
    }
    if (file.size > 8 * 1024 * 1024) {
      showTaskOperationNotice("图片不能超过 8 MB。");
      els.chatImageInput.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = async () => {
      const dataUrl = String(reader.result || "");
      const previewDataUrl = await createChatImagePreview(dataUrl);
      state.chatImageAttachment = { name: file.name, size: file.size, dataUrl, previewDataUrl };
      renderChatAttachment();
      els.composerPlusMenu.hidden = true;
      els.chatInput.focus();
    };
    reader.readAsDataURL(file);
  });
}

if (els.chatAttachmentPreview) {
  els.chatAttachmentPreview.addEventListener("click", (event) => {
    if (!event.target.closest("#removeChatImage")) return;
    state.chatImageAttachment = null;
    if (els.chatImageInput) els.chatImageInput.value = "";
    renderChatAttachment();
  });
}

if (els.chatModelSelect) {
  els.chatModelSelect.addEventListener("change", async () => {
    els.chatModelSelect.disabled = true;
    try {
      await switchChatModel(els.chatModelSelect.value);
    } catch (error) {
      showTaskOperationNotice(error.message);
      renderChatModelControls();
    } finally {
      els.chatModelSelect.disabled = false;
    }
  });
  loadChatModelOptions().catch((error) => {
    console.warn(error);
    renderChatModelControls();
  });
}

if (els.chatModelButton) {
  els.chatModelButton.addEventListener("click", (event) => {
    event.stopPropagation();
    const willOpen = Boolean(els.chatModelMenu?.hidden);
    if (els.chatModelMenu) els.chatModelMenu.hidden = !willOpen;
    els.chatModelButton.setAttribute("aria-expanded", String(willOpen));
    if (willOpen) {
      if (els.composerPlusMenu) els.composerPlusMenu.hidden = true;
      els.composerPlusButton?.setAttribute("aria-expanded", "false");
      if (els.skillMenu) els.skillMenu.hidden = true;
      if (els.databaseMenu) els.databaseMenu.hidden = true;
      renderSkillToggle();
      renderDatabaseToggle();
      renderChatModelOptions();
      requestAnimationFrame(() => els.chatModelSearch?.focus());
    }
  });
}

if (els.chatModelSearch) els.chatModelSearch.addEventListener("input", renderChatModelOptions);

if (els.chatModelOptions) {
  els.chatModelOptions.addEventListener("click", async (event) => {
    const option = event.target.closest("[data-model]");
    if (!option) return;
    const model = option.dataset.model || "";
    if (model && model !== state.chatModel) {
      const previous = state.chatModel;
      state.chatModel = model;
      renderChatModelControls();
      try {
        await switchChatModel(model);
      } catch (error) {
        state.chatModel = previous;
        renderChatModelControls();
        showTaskOperationNotice(error.message);
      }
    }
    if (els.chatModelMenu) els.chatModelMenu.hidden = true;
    els.chatModelButton?.setAttribute("aria-expanded", "false");
  });
}

document.addEventListener("click", (event) => {
  if (!els.composerPlusMenu || els.composerPlusMenu.hidden) return;
  if (event.target.closest(".composer-plus-picker")) return;
  els.composerPlusMenu.hidden = true;
  els.composerPlusButton.setAttribute("aria-expanded", "false");
});

document.addEventListener("click", (event) => {
  if (!els.chatModelMenu || els.chatModelMenu.hidden) return;
  if (event.target.closest(".chat-model-picker")) return;
  els.chatModelMenu.hidden = true;
  els.chatModelButton?.setAttribute("aria-expanded", "false");
});

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
    if (!option) return;
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
      if (state.knowledgeUploadBusy) return;
      state.knowledgeUploadOpen = !state.knowledgeUploadOpen;
      renderDatabaseMenu();
      return;
    }
    const chooseFile = event.target.closest("#knowledgeUploadChooseFile");
    if (chooseFile) {
      if (state.knowledgeUploadBusy || !els.knowledgeUploadInput) return;
      els.knowledgeUploadInput.click();
      return;
    }
    const submitUpload = event.target.closest("#knowledgeUploadSubmit");
    if (submitUpload) {
      uploadKnowledgeFile(state.knowledgeUploadFile);
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
    if (!option) return;
    const datasetId = option.dataset.datasetId;
    if (!datasetId) return;
    state.datasetSelectionTouched = true;
    if (state.selectedDatasetIds.has(datasetId)) state.selectedDatasetIds.delete(datasetId);
    else state.selectedDatasetIds.add(datasetId);
    renderDatabaseMenu();
    els.chatInput.focus();
  });
  els.databaseMenu.addEventListener("input", (event) => {
    const field = event.target && event.target.dataset ? event.target.dataset.uploadField : "";
    if (!field) return;
    state.knowledgeUploadMeta[field] = event.target.value;
  });
  els.databaseMenu.addEventListener("change", (event) => {
    const field = event.target && event.target.dataset ? event.target.dataset.uploadField : "";
    if (!field) return;
    state.knowledgeUploadMeta[field] = event.target.value;
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

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  const attachment = state.chatImageAttachment;
  if (!message && !attachment) return;
  els.chatInput.value = "";
  resizeChatInput();
  let enrichedMessage = message || "请分析这张图片。";
  if (attachment) {
    try {
      const description = await analyzeChatImage(attachment, enrichedMessage);
      enrichedMessage = `${enrichedMessage}\n\n[图片内容（由 ${state.chatModel} 识别）]\n${description}`;
      state.chatImageAttachment = null;
      if (els.chatImageInput) els.chatImageInput.value = "";
      renderChatAttachment();
    } catch (error) {
      showTaskOperationNotice(error.message);
      els.chatInput.value = message;
      resizeChatInput();
      return;
    }
  }
  const sendOptions = attachment ? {
    displayMessage: message || "请分析这张图片。",
    displayImage: {
      name: attachment.name,
      dataUrl: attachment.previewDataUrl || attachment.dataUrl,
    },
  } : { displayMessage: message };
  if (state.chatBusy) {
    enqueueChatMessage(enrichedMessage, sendOptions);
    els.chatInput.focus();
    return;
  }
  sendChat(enrichedMessage, sendOptions);
});

els.chatSubmitButton.addEventListener("click", (event) => {
  if (!state.chatBusy) return;
  event.preventDefault();
  abandonPendingChatApproval();
  state.chatStopRequested = true;
  if (state.chatAbortController) state.chatAbortController.abort();
});

els.chatInput.addEventListener("input", resizeChatInput);

els.chatInput.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  els.chatForm.requestSubmit();
});

window.addEventListener("beforeunload", abandonPendingChatApproval);

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

// AI message image lightbox
const imageLightbox = document.createElement("div");
imageLightbox.className = "chat-image-lightbox";
imageLightbox.hidden = true;
imageLightbox.innerHTML = `
  <button class="chat-image-lightbox-close" type="button" aria-label="关闭图片预览" title="关闭">
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M18 6 6 18M6 6l12 12"></path>
    </svg>
  </button>
  <img class="chat-image-lightbox-image" src="" alt="" />
`;
document.body.appendChild(imageLightbox);

const imageLightboxImage = imageLightbox.querySelector(".chat-image-lightbox-image");
const imageLightboxClose = imageLightbox.querySelector(".chat-image-lightbox-close");
let imageLightboxTrigger = null;

function openImageLightbox(image) {
  imageLightboxTrigger = image;
  imageLightboxImage.src = image.currentSrc || image.src;
  imageLightboxImage.alt = image.alt || "图片放大预览";
  imageLightbox.hidden = false;
  document.body.classList.add("chat-image-lightbox-open");
  requestAnimationFrame(() => imageLightbox.classList.add("is-visible"));
  imageLightboxClose.focus();
}

function closeImageLightbox() {
  if (imageLightbox.hidden) return;
  imageLightbox.classList.remove("is-visible");
  document.body.classList.remove("chat-image-lightbox-open");
  window.setTimeout(() => {
    imageLightbox.hidden = true;
    imageLightboxImage.removeAttribute("src");
    if (imageLightboxTrigger && document.contains(imageLightboxTrigger)) imageLightboxTrigger.focus();
    imageLightboxTrigger = null;
  }, 160);
}

document.addEventListener("click", (event) => {
  const image = event.target.closest(".message-body img.chat-inline-image, .message-body img.chat-user-image-preview, .chart-result-block img.chat-inline-image");
  if (!image) return;
  event.preventDefault();
  openImageLightbox(image);
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const image = event.target.closest(".message-body img.chat-user-image-preview");
  if (!image) return;
  event.preventDefault();
  openImageLightbox(image);
});

imageLightboxClose.addEventListener("click", closeImageLightbox);
imageLightbox.addEventListener("click", (event) => {
  if (event.target === imageLightbox) closeImageLightbox();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !imageLightbox.hidden) closeImageLightbox();
});

/* Permanently expanded raw run logs v143 */
(function pinRawRunLogsOpen() {
  function normalizeTitle(summary) {
    const walker = document.createTreeWalker(summary, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);
    textNodes.forEach(function (node) {
      node.nodeValue = node.nodeValue.replace("展开查看原始运行日志", "原始运行日志");
    });
  }

  function pinDetails(details) {
    if (!details || details.tagName !== "DETAILS") return;
    const summary = details.querySelector(":scope > summary");
    if (!summary || summary.textContent.indexOf("原始运行日志") < 0) return;

    details.open = true;
    if (details.dataset.rawLogPinned === "true") return;

    details.dataset.rawLogPinned = "true";
    summary.setAttribute("aria-disabled", "true");
    summary.tabIndex = -1;
    normalizeTitle(summary);
    summary.addEventListener("click", function (event) {
      event.preventDefault();
      details.open = true;
    });
    details.addEventListener("toggle", function () {
      if (!details.open) details.open = true;
    });
  }

  function scan(root) {
    if (!root) return;
    if (root.nodeType === Node.ELEMENT_NODE && root.matches("details")) pinDetails(root);
    if (root.querySelectorAll) root.querySelectorAll("details").forEach(pinDetails);
  }

  scan(document);
  const observer = new MutationObserver(function (mutations) {
    mutations.forEach(function (mutation) {
      mutation.addedNodes.forEach(scan);
    });
  });
  observer.observe(document.body, { childList: true, subtree: true });
})();

/* Strategic briefing ticker: only group-approved items are rendered. */
(function initStrategicBriefingTicker() {
  const list = document.getElementById("strategyTickerList");
  const syncStatus = document.getElementById("strategySyncStatus");
  const scheduleText = document.getElementById("strategyScheduleText");
  if (!list || !syncStatus || !scheduleText) return;

  let scrollAnimation = null;
  let resumeTimer = null;
  let pointerPaused = false;
  let focusPaused = false;
  let touchStartY = 0;
  let touchStartTime = 0;
  const autoScrollSpeed = 30;
  list.tabIndex = 0;
  list.setAttribute("aria-label", "战略快讯滚动列表");
  function escapeValue(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function formatTime(value) {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat("zh-HK", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "Asia/Hong_Kong",
    }).format(date);
  }

  function restartScroll() {
    if (scrollAnimation) scrollAnimation.cancel();
    scrollAnimation = null;
    if (resumeTimer) window.clearTimeout(resumeTimer);
    list.scrollTop = 0;
    const items = Array.from(list.querySelectorAll(".strategy-ticker-item"));
    if (!items.length || list.scrollHeight <= list.clientHeight + 2) return;

    const track = document.createElement("div");
    track.className = "strategy-ticker-track";
    items.forEach(function (item) {
      track.appendChild(item);
    });
    const cloneFragment = document.createDocumentFragment();
    items.forEach(function (item) {
      const clone = item.cloneNode(true);
      clone.classList.add("strategy-ticker-clone");
      clone.setAttribute("aria-hidden", "true");
      clone.tabIndex = -1;
      cloneFragment.appendChild(clone);
    });
    track.appendChild(cloneFragment);
    list.replaceChildren(track);

    const firstClone = track.querySelector(".strategy-ticker-clone");
    const cycleHeight = firstClone
      ? firstClone.offsetTop - items[0].offsetTop
      : 0;
    if (cycleHeight <= 1) return;

    scrollAnimation = track.animate(
      [
        { transform: "translate3d(0, 0, 0)" },
        { transform: "translate3d(0, -" + cycleHeight + "px, 0)" }
      ],
      {
        duration: Math.max(12000, (cycleHeight / autoScrollSpeed) * 1000),
        iterations: Infinity,
        easing: "linear"
      }
    );
  }

  function pauseScroll() {
    if (scrollAnimation) scrollAnimation.pause();
  }

  function resumeScroll(delay) {
    if (resumeTimer) window.clearTimeout(resumeTimer);
    resumeTimer = window.setTimeout(function () {
      if (!pointerPaused && !focusPaused && scrollAnimation) {
        scrollAnimation.play();
      }
    }, delay || 0);
  }

  function shiftScroll(deltaY) {
    if (!scrollAnimation) return;
    const current = Number(scrollAnimation.currentTime) || 0;
    scrollAnimation.currentTime = current + (deltaY / autoScrollSpeed) * 1000;
  }

  function render(payload) {
    const items = (Array.isArray(payload.items) ? payload.items : []).filter(function (item) {
      const previewText = [item && item.title, item && item.summary, item && item.category]
        .filter(Boolean)
        .join(" ");
      return !/排版预览|版式预览/.test(previewText);
    });
    const monitor = payload.monitor || {};
    const degraded = monitor.status === "degraded";
    syncStatus.classList.toggle("is-degraded", degraded);
    syncStatus.title = monitor.last_error || "";
    syncStatus.innerHTML =
      '<i aria-hidden="true"></i>' + (degraded ? "同步待恢复" : "每小时同步");
    const scanTimes = Array.isArray(monitor.scan_times) ? monitor.scan_times : [];
    scheduleText.textContent = scanTimes.length
      ? "每日 " + scanTimes.join(" / ") + " 扫描"
      : "每日两次扫描";

    if (!items.length) {
      list.innerHTML =
        '<div class="strategy-ticker-empty">' +
          '<b>等待首条确认快讯</b>' +
          '<span>候选新闻经战略部人工筛选后展示</span>' +
        "</div>";
      restartScroll();
      return;
    }

    const fingerprint = items.map(function (item) {
      return [item.published_at, item.title, item.summary, item.source_url].join("|");
    }).join("||");
    if (
      list.dataset.tickerFingerprint === fingerprint &&
      list.querySelector(".strategy-ticker-track")
    ) {
      return;
    }
    list.dataset.tickerFingerprint = fingerprint;
    list.innerHTML = items.map(function (item) {
      const url = /^https?:\/\//i.test(String(item.source_url || ""))
        ? String(item.source_url)
        : "";
      const tag = url ? "a" : "article";
      const linkAttrs = url
        ? ' href="' + escapeValue(url) + '" target="_blank" rel="noreferrer"'
        : "";
      return (
        "<" + tag + ' class="strategy-ticker-item"' + linkAttrs + ">" +
          '<span class="strategy-ticker-meta">' +
            "<time>" + escapeValue(formatTime(item.published_at)) + "</time>" +
            "<b>" + escapeValue(item.category || "战略动态") + "</b>" +
          "</span>" +
          "<strong>" + escapeValue(item.title || "战略快讯") + "</strong>" +
          "<p>" + escapeValue(item.summary || ("这条" + (item.category || "战略动态") + "涉及“" + (item.title || "该动态") + "”。可点击标题查看原文，关注其产品定位、市场变化及竞争影响。")) + "</p>" +
        "</" + tag + ">"
      );
    }).join("");
    restartScroll();
  }

  async function fetchStrategicBriefs() {
    try {
      const response = await fetch("/api/strategic-briefs", { cache: "no-store" });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "战略快讯同步失败");
      }
      render(payload);
    } catch (error) {
      syncStatus.classList.add("is-degraded");
      syncStatus.innerHTML = '<i aria-hidden="true"></i>同步待恢复';
      syncStatus.title = error && error.message ? error.message : String(error);
      render({ items: sampleItems, monitor: { status: "degraded" } });
    }
  }

  list.addEventListener("pointerenter", function () {
    pointerPaused = true;
    pauseScroll();
  });
  list.addEventListener("pointerleave", function () {
    pointerPaused = false;
    resumeScroll(350);
  });
  list.addEventListener("wheel", function (event) {
    event.preventDefault();
    pauseScroll();
    shiftScroll(event.deltaY);
  }, { passive: false });
  list.addEventListener("touchstart", function (event) {
    const touch = event.touches && event.touches[0];
    if (!touch || !scrollAnimation) return;
    pauseScroll();
    touchStartY = touch.clientY;
    touchStartTime = Number(scrollAnimation.currentTime) || 0;
  }, { passive: true });
  list.addEventListener("touchmove", function (event) {
    const touch = event.touches && event.touches[0];
    if (!touch || !scrollAnimation) return;
    event.preventDefault();
    scrollAnimation.currentTime = touchStartTime + ((touchStartY - touch.clientY) / autoScrollSpeed) * 1000;
  }, { passive: false });
  list.addEventListener("touchend", function () {
    resumeScroll(700);
  }, { passive: true });
  list.addEventListener("pointerdown", function () {
    pauseScroll();
  });
  list.addEventListener("keydown", function () {
    pauseScroll();
  });
  list.addEventListener("focusin", function () {
    focusPaused = true;
    pauseScroll();
  });
  list.addEventListener("focusout", function () {
    focusPaused = false;
    resumeScroll(500);
  });
  fetchStrategicBriefs();
  window.setInterval(fetchStrategicBriefs, 60000);
})();
