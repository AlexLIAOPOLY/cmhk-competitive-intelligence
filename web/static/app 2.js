const state = {
  busy: false,
};

const els = {
  templateStatus: document.querySelector("#templateStatus"),
  templatePath: document.querySelector("#templatePath"),
  resultCount: document.querySelector("#resultCount"),
  resultDetail: document.querySelector("#resultDetail"),
  latestOutput: document.querySelector("#latestOutput"),
  fileList: document.querySelector("#fileList"),
  runState: document.querySelector("#runState"),
  logBox: document.querySelector("#logBox"),
  generateButton: document.querySelector("#generateButton"),
  refreshButton: document.querySelector("#refreshButton"),
  messages: document.querySelector("#messages"),
  chatForm: document.querySelector("#chatForm"),
  chatInput: document.querySelector("#chatInput"),
};

function formatBytes(size) {
  if (!Number.isFinite(size)) return "-";
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size > 1024) return `${Math.round(size / 1024)} KB`;
  return `${size} B`;
}

function setBusy(value, label = "运行中") {
  state.busy = value;
  els.generateButton.disabled = value;
  els.refreshButton.disabled = value;
  els.runState.textContent = value ? label : "准备就绪";
}

function renderStatus(status) {
  els.templateStatus.textContent = status.template.exists ? "已加载" : "未找到";
  els.templatePath.textContent = status.template.path;
  els.resultCount.textContent = `${status.results.count} 个`;
  els.resultDetail.textContent = `ok ${status.results.ok} / partial ${status.results.partial}`;
  els.latestOutput.textContent = status.latestOutputText;

  if (!status.outputs.length) {
    els.fileList.innerHTML = `<div class="file-row"><strong>暂无输出</strong><span>请先生成周报</span><span></span></div>`;
    return;
  }

  els.fileList.innerHTML = status.outputs
    .map(
      (file) => `
        <div class="file-row">
          <strong title="${file.name}">${file.name}</strong>
          <span>${formatBytes(file.size)} · ${file.mtimeText}</span>
          <a href="${file.url}" target="_blank" rel="noopener noreferrer">${file.name.endsWith(".docx") ? "下载" : "打开"}</a>
        </div>
      `,
    )
    .join("");
}

async function refreshStatus() {
  const response = await fetch("/api/status");
  const data = await response.json();
  if (!data.ok) throw new Error(data.error || "状态获取失败");
  renderStatus(data.status);
}

async function generateReport(source = "按钮") {
  setBusy(true, "正在生成周报");
  els.logBox.textContent = `${source}触发生成，等待后端完成...`;
  try {
    const response = await fetch("/api/generate", { method: "POST" });
    const data = await response.json();
    renderStatus(data.status);
    els.logBox.textContent = [
      `完成：${data.ok ? "成功" : "失败"}`,
      `耗时：${data.durationMs} ms`,
      data.stdout ? `stdout:\n${data.stdout}` : "",
      data.stderr ? `stderr:\n${data.stderr}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  } catch (error) {
    els.logBox.textContent = `生成失败：${error.message}`;
  } finally {
    setBusy(false);
  }
}

function addMessage(role, content) {
  const node = document.createElement("div");
  node.className = `message ${role}`;
  node.textContent = content;
  els.messages.appendChild(node);
  els.messages.scrollTop = els.messages.scrollHeight;
}

async function sendChat(message) {
  addMessage("user", message);
  setBusy(true, "AI 正在处理");
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "对话失败");
    addMessage("assistant", data.reply.content);
    renderStatus(data.status);
    if (data.reply.generation) {
      els.logBox.textContent = [
        `AI 对话触发生成：${data.reply.generation.ok ? "成功" : "失败"}`,
        `耗时：${data.reply.generation.durationMs} ms`,
        data.reply.generation.stdout ? `stdout:\n${data.reply.generation.stdout}` : "",
        data.reply.generation.stderr ? `stderr:\n${data.reply.generation.stderr}` : "",
      ]
        .filter(Boolean)
        .join("\n\n");
    }
  } catch (error) {
    addMessage("assistant", `处理失败：${error.message}`);
  } finally {
    setBusy(false);
  }
}

els.generateButton.addEventListener("click", () => generateReport("按钮"));
els.refreshButton.addEventListener("click", () => refreshStatus().catch((error) => {
  els.logBox.textContent = `刷新失败：${error.message}`;
}));

els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.chatInput.value.trim();
  if (!message || state.busy) return;
  els.chatInput.value = "";
  sendChat(message);
});

refreshStatus().catch((error) => {
  els.logBox.textContent = `初始化失败：${error.message}`;
});
