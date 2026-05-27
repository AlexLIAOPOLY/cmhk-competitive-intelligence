const state = {
  busy: false,
  chatBusy: false,
  outputs: [],
  selectedFiles: new Set(),
  fileType: "all",
  fileSearch: "",
  fileSort: "mtime-desc",
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  statusSummary: document.querySelector("#statusSummary"),
  fileList: document.getElementById("fileList"),
  deleteSelectedButton: document.getElementById("deleteSelectedButton"),
  typeFilter: document.getElementById("typeFilter"),
  fileSearchInput: document.querySelector("#fileSearchInput"),
  fileSortSelect: document.querySelector("#fileSortSelect"),
  fileCountText: document.querySelector("#fileCountText"),
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
  const htmlSvg = base + '<polyline points="10 13 8 15 10 17"></polyline><polyline points="14 13 16 15 14 17"></polyline>';
  const mdSvg = base + '<line x1="12" y1="11" x2="12" y2="17"></line><polyline points="9 14 12 17 15 14"></polyline>';

  if (fileName.endsWith(".docx")) return { label: "Word 文档", icon: getIcon(wordSvg), className: "type-docx" };
  if (fileName.endsWith(".html")) return { label: "HTML 报告", icon: getIcon(htmlSvg), className: "type-html" };
  return { label: "Markdown", icon: getIcon(mdSvg), className: "type-md" };
}

function fileDescription(file) {
  let desc = "";
  if (file.name === "weekly_report.docx") desc = "周报（Word 正式版）";
  else if (file.name === "weekly_report_from_word_template.docx") desc = "周报（Word 模板版）";
  else if (file.name === "weekly_report.html") desc = "周报（HTML 预览）";
  else desc = "周报（Markdown 版本）";
  
  if (file.is_archive) {
    desc = `<span style="color:var(--orange)">[历史归档: ${file.archive_batch}]</span> ` + desc;
  }
  return desc;
}

function filteredOutputs() {
  const query = state.fileSearch.trim().toLowerCase();
  const files = state.outputs
    .filter((file) => {
      if (state.fileType !== "all" && !file.name.endsWith(`.${state.fileType}`)) return false;
      if (!query) return true;
      return `${file.name} ${fileDescription(file)}`.toLowerCase().includes(query);
    })
    .sort((a, b) => {
      if (state.fileSort === "mtime-asc") return a.mtime - b.mtime;
      if (state.fileSort === "name-asc") return a.name.localeCompare(b.name);
      return b.mtime - a.mtime;
    });
  return files;
}

function renderFileList() {
  const files = filteredOutputs();
  els.fileCountText.textContent = `${files.length} / ${state.outputs.length} 个文件`;
  if (!state.outputs.length) {
    els.fileList.innerHTML = `
      <div class="file-header">
        <span style="flex:0 0 40px;text-align:center;"><input type="checkbox" disabled></span>
        <span>文件类型</span><span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
      </div>
      <div class="file-row">
        <span style="flex:0 0 40px;"></span>
        <strong>暂无输出</strong><span>请先生成周报</span><span>-</span><span>-</span><span>-</span>
      </div>
    `;
    return;
  }
  if (!files.length) {
    els.fileList.innerHTML = `
      <div class="file-header">
        <span style="flex:0 0 40px;text-align:center;"><input type="checkbox" disabled></span>
        <span>文件类型</span><span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
      </div>
      <div class="file-row">
        <span style="flex:0 0 40px;"></span>
        <strong>无匹配结果</strong><span>请尝试更改过滤条件</span><span>-</span><span>-</span><span>-</span>
      </div>
    `;
    return;
  }

  let html = `
    <div class="file-header">
      <span style="flex:0 0 40px;text-align:center;"><input type="checkbox" id="selectAllCheckbox"></span>
      <span>文件类型</span><span>文件名</span><span>说明</span><span>更新时间</span><span>操作</span>
    </div>
  `;
  files.forEach((file) => {
    const type = fileType(file.name);
    const checked = state.selectedFiles.has(file.path_str) ? "checked" : "";
    html += `
      <div class="file-row ${type.className}">
        <span style="flex:0 0 40px;text-align:center;"><input type="checkbox" class="file-checkbox" data-path="${file.path_str}" ${checked}></span>
        <span class="file-type-cell">${type.icon} ${type.label}</span>
        <span class="file-name-cell" title="${file.name}">${file.name}</span>
        <span>${fileDescription(file)}</span>
        <span class="time-cell">${file.mtimeText}</span>
        <span class="action-cell">
          <a href="${file.url}" download class="quiet-button small" style="text-decoration:none;">下载</a>
        </span>
      </div>
    `;
  });
  els.fileList.innerHTML = html;
  
  const selectAll = document.getElementById("selectAllCheckbox");
  const checkboxes = document.querySelectorAll(".file-checkbox");
  
  const updateDeleteBtn = () => {
    els.deleteSelectedButton.disabled = state.selectedFiles.size === 0;
    els.deleteSelectedButton.textContent = state.selectedFiles.size > 0 ? `批量删除 (${state.selectedFiles.size})` : "批量删除";
  };
  
  if (selectAll) {
    selectAll.checked = files.length > 0 && files.every(f => state.selectedFiles.has(f.path_str));
    selectAll.addEventListener("change", (e) => {
      files.forEach(f => {
        if (e.target.checked) state.selectedFiles.add(f.path_str);
        else state.selectedFiles.delete(f.path_str);
      });
      renderFileList();
    });
  }
  
  checkboxes.forEach(cb => {
    cb.addEventListener("change", (e) => {
      if (e.target.checked) state.selectedFiles.add(e.target.dataset.path);
      else state.selectedFiles.delete(e.target.dataset.path);
      updateDeleteBtn();
      if (selectAll) selectAll.checked = files.length > 0 && files.every(f => state.selectedFiles.has(f.path_str));
    });
  });
  
  updateDeleteBtn();
}

function renderStatus(status) {
  els.statusSummary.textContent = `数据 ${status.results.count} 个 · 范围 ${status.settings.enabledRows}/${status.settings.totalRows} 行 · 输出 ${status.latestOutputText}`;
  if (status.ai && els.aiConfigStatus) {
    els.aiConfigStatus.textContent = `${status.ai.provider} / ${status.ai.model} / ${status.ai.base_url} / ${status.ai.has_api_key ? "API Key 已保存" : "未保存 API Key"}`;
  }
  state.outputs = status.outputs || [];
  
  const existingPaths = new Set(state.outputs.map(o => o.path_str));
  for (const p of state.selectedFiles) {
    if (!existingPaths.has(p)) state.selectedFiles.delete(p);
  }
  
  renderFileList();
}

function appendLog(text) {
  els.logBox.textContent += text;
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", els.logBox.textContent);
}

function setLog(text) {
  els.logBox.textContent = text;
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

async function deleteSelectedFiles() {
  if (state.selectedFiles.size === 0) return;
  if (!confirm(`确定要彻底删除选中的 ${state.selectedFiles.size} 个文件吗？此操作不可恢复。`)) return;
  
  setBusy(true, "正在删除");
  try {
    const response = await fetch("/api/delete-files", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: Array.from(state.selectedFiles) })
    });
    const data = await response.json();
    if (data.ok) {
      state.selectedFiles.clear();
      renderStatus(data.status);
    } else {
      alert("删除失败: " + data.error);
    }
  } catch (err) {
    alert("请求异常: " + err.message);
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
  const text = node.querySelector(".message-text");
  if (markdown) {
    let html = markdownToHtml(content);
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
          setMessageContent(assistantNode, answer, true);
          els.messages.scrollTop = els.messages.scrollHeight;
        } else if (event.type === "error") {
          answer += `\n\n**错误：** ${event.text}`;
          setMessageContent(assistantNode, answer, true);
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

if (els.deleteSelectedButton) {
  els.deleteSelectedButton.addEventListener("click", deleteSelectedFiles);
}

els.typeFilter.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-type]");
  if (!button) return;
  state.fileType = button.dataset.type;
  els.typeFilter.querySelectorAll("button").forEach((item) => item.classList.toggle("is-active", item === button));
  renderFileList();
});

els.fileSearchInput.addEventListener("input", () => {
  state.fileSearch = els.fileSearchInput.value;
  renderFileList();
});

els.fileSortSelect.addEventListener("change", (e) => {
  state.fileSort = e.target.value;
  renderFileList();
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
        <div class="message-text">您好，我会先检索本地周报和爬取结果，再调用 LLM 总结内容、分析风险并给出建议。</div>
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
