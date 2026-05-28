const settingsState = {
  rows: [],
  busyRows: new Set(),
  filter: "",
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  filterInput: document.querySelector("#filterInput"),
  summary: document.querySelector("#settingsSummary"),
  list: document.querySelector("#settingsList"),
  logButton: document.querySelector("#logButton"),
  logModal: document.querySelector("#logModal"),
  closeLogButton: document.querySelector("#closeLogButton"),
  clearLogButton: document.querySelector("#clearLogButton"),
  logBox: document.querySelector("#logBox"),
};

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

function setLog(text) {
  els.logBox.textContent = text;
  els.logBox.scrollTop = els.logBox.scrollHeight;
  localStorage.setItem("appLogs", text);
}

function appendLog(text) {
  const current = localStorage.getItem("appLogs") || els.logBox.textContent || "";
  const next = current && current !== "等待操作。" ? `${current}\n${text}` : text;
  setLog(next);
}

function timePrefix() {
  return `[${new Date().toLocaleTimeString("zh-CN", { hour12: false })}]`;
}

function hydrateLogs() {
  const saved = localStorage.getItem("appLogs");
  if (saved) els.logBox.textContent = saved;
}

function normalizeList(values) {
  return Array.from(new Set((values || []).map((value) => String(value).trim()).filter(Boolean)));
}

function findRow(rowNo) {
  return settingsState.rows.find((item) => String(item.row) === String(rowNo));
}

function setRowEnabled(rowNo, enabled) {
  const row = findRow(rowNo);
  if (!row) return;
  row.enabled = enabled;
  render();
}

function addValue(rowNo, collectionKey, selectedKey, rawValue) {
  const row = findRow(rowNo);
  const value = String(rawValue || "").trim();
  if (!row || !value) return false;
  row[collectionKey] = normalizeList([...(row[collectionKey] || []), value]);
  row[selectedKey] = normalizeList([...(row[selectedKey] || []), value]);
  render();
  return true;
}

function removeValue(rowNo, collectionKey, selectedKey, value) {
  const row = findRow(rowNo);
  if (!row) return;
  row[collectionKey] = normalizeList(row[collectionKey]).filter((item) => item !== value);
  row[selectedKey] = normalizeList(row[selectedKey]).filter((item) => item !== value);
  render();
}

function toggleValue(rowNo, key, value, checked) {
  const row = findRow(rowNo);
  if (!row) return;
  const values = new Set(row[key]);
  if (checked) values.add(value);
  else values.delete(value);
  row[key] = Array.from(values);
  render();
}

function toggleAll(rowNo, key, values, checked) {
  const row = findRow(rowNo);
  if (!row) return;
  row[key] = checked ? [...values] : [];
  render();
}

function addSourceUrl(rowNo, rawUrl) {
  const row = findRow(rowNo);
  const url = String(rawUrl || "").trim();
  if (!row || !url) return false;
  if (!/^https?:\/\//i.test(url)) {
    appendLog(`${timePrefix()} 目标链接未添加：${url}，必须以 http:// 或 https:// 开头。`);
    return false;
  }
  row.sourceUrls = normalizeList([...(row.sourceUrls || []), url]);
  render();
  return true;
}

function removeSourceUrl(rowNo, url) {
  const row = findRow(rowNo);
  if (!row) return;
  row.sourceUrls = normalizeList(row.sourceUrls).filter((item) => item !== url);
  render();
}

function rowMatches(row) {
  const query = settingsState.filter.trim().toLowerCase();
  if (!query) return true;
  return [
    row.row,
    row.block,
    row.object,
    row.package,
    row.need,
    row.entities.join(" "),
    row.fields.join(" "),
    row.sourceUrls.join(" "),
  ]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function renderOptionList(row, key, allValues, selectedValues) {
  if (!allValues.length) return '<span class="empty-note">暂无可配置项</span>';
  const removeAction = key === "selectedEntities" ? "remove-entity" : "remove-field";
  return allValues
    .map((value) => {
      const id = `${key}-${row.row}-${value}`.replace(/[^\w\u4e00-\u9fa5-]+/g, "-");
      const checked = selectedValues.includes(value) ? "checked" : "";
      return `
        <label class="check-chip" for="${escapeHtml(id)}">
          <input id="${escapeHtml(id)}" type="checkbox" ${checked}
            data-row="${escapeHtml(row.row)}" data-key="${escapeHtml(key)}" data-value="${escapeHtml(value)}" />
          <span>${escapeHtml(value)}</span>
          <button class="chip-remove" type="button" data-action="${removeAction}" data-row="${escapeHtml(row.row)}" data-value="${escapeHtml(value)}" aria-label="删除 ${escapeHtml(value)}">×</button>
        </label>
      `;
    })
    .join("");
}

function renderSourceUrls(row) {
  const links = normalizeList(row.sourceUrls || []);
  if (!links.length) return '<span class="empty-note">未添加额外目标链接，将使用飞书原始来源。</span>';
  return links
    .map(
      (url) => `
        <span class="url-chip">
          <a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(url)}</a>
          <button type="button" class="chip-remove" data-action="remove-url" data-row="${escapeHtml(row.row)}" data-value="${escapeHtml(url)}" aria-label="删除链接">×</button>
        </span>
      `
    )
    .join("");
}

function render() {
  const rows = settingsState.rows.filter(rowMatches);
  const enabledRows = settingsState.rows.filter((row) => row.enabled);
  const selectedEntityCount = enabledRows.reduce((total, row) => total + row.selectedEntities.length, 0);
  const selectedFieldCount = enabledRows.reduce((total, row) => total + row.selectedFields.length, 0);
  const sourceUrlCount = enabledRows.reduce((total, row) => total + normalizeList(row.sourceUrls).length, 0);
  els.summary.textContent = `启用 ${enabledRows.length} / ${settingsState.rows.length} 行，${selectedEntityCount} 个主体，${selectedFieldCount} 个字段，${sourceUrlCount} 个额外链接`;

  if (!rows.length) {
    els.list.innerHTML = '<div class="settings-empty">没有匹配的爬取项。</div>';
    return;
  }

  els.list.innerHTML = rows
    .map((row) => {
      const enabled = row.enabled ? "checked" : "";
      const busy = settingsState.busyRows.has(String(row.row));
      return `
        <article class="setting-row ${row.enabled ? "" : "is-disabled"}" data-row="${escapeHtml(row.row)}">
          <div class="setting-main">
            <label class="switch-line">
              <input class="row-enabled" type="checkbox" data-row="${escapeHtml(row.row)}" ${enabled} />
              <span>启用</span>
            </label>
            <div>
              <h2>第 ${escapeHtml(row.row)} 行 · ${escapeHtml(row.package || row.object || "公开信息")}</h2>
              <p>${escapeHtml(row.object)} · ${escapeHtml(row.block)}</p>
              <small>${escapeHtml(row.need)}</small>
            </div>
          </div>

          <div class="setting-columns">
            <section>
              <div class="setting-subhead">
                <strong>主体 / 公司</strong>
                <button type="button" class="inline-button" data-row="${escapeHtml(row.row)}" data-key="selectedEntities" data-action="all-entities">全选</button>
              </div>
              <div class="add-line">
                <input type="text" data-role="entity-input" data-row="${escapeHtml(row.row)}" placeholder="添加主体或公司" />
                <button type="button" class="inline-icon-button" data-action="add-entity" data-row="${escapeHtml(row.row)}" aria-label="添加主体">＋</button>
              </div>
              <div class="chip-grid">${renderOptionList(row, "selectedEntities", row.entities, row.selectedEntities)}</div>
            </section>

            <section>
              <div class="setting-subhead">
                <strong>具体数据内容</strong>
                <button type="button" class="inline-button" data-row="${escapeHtml(row.row)}" data-key="selectedFields" data-action="all-fields">全选</button>
              </div>
              <div class="add-line">
                <input type="text" data-role="field-input" data-row="${escapeHtml(row.row)}" placeholder="添加字段或数据项" />
                <button type="button" class="inline-icon-button" data-action="add-field" data-row="${escapeHtml(row.row)}" aria-label="添加字段">＋</button>
              </div>
              <div class="chip-grid">${renderOptionList(row, "selectedFields", row.fields, row.selectedFields)}</div>
            </section>
          </div>

          <div class="target-link-panel">
            <div class="setting-subhead">
              <strong>目标链接（可选）</strong>
              <span>额外链接会并入该行下一次爬虫抓取范围。</span>
            </div>
            <div class="add-line wide">
              <input type="url" data-role="url-input" data-row="${escapeHtml(row.row)}" placeholder="https://example.com/news-or-report" />
              <button type="button" class="inline-icon-button" data-action="add-url" data-row="${escapeHtml(row.row)}" aria-label="添加链接">＋</button>
            </div>
            <div class="url-list">${renderSourceUrls(row)}</div>
          </div>

          <footer class="row-save-bar">
            <span class="row-save-status" data-status-row="${escapeHtml(row.row)}">${busy ? "正在保存..." : ""}</span>
            <button type="button" class="row-save-button" data-action="save-row" data-row="${escapeHtml(row.row)}" title="保存本行" aria-label="保存本行" ${busy ? "disabled" : ""}>
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z"/><path d="M17 21v-8H7v8"/><path d="M7 3v5h8"/></svg>
            </button>
          </footer>
        </article>
      `;
    })
    .join("");
}

async function loadSettings() {
  els.summary.textContent = "加载设置";
  try {
    const response = await fetch("/api/settings");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "设置加载失败");
    settingsState.rows = data.settings.rows.map((row) => ({
      ...row,
      entities: normalizeList(row.entities),
      fields: normalizeList(row.fields),
      selectedEntities: normalizeList(row.selectedEntities),
      selectedFields: normalizeList(row.selectedFields),
      sourceUrls: normalizeList(row.sourceUrls),
    }));
    render();
  } catch (error) {
    appendLog(`${timePrefix()} 加载失败：${error.message}`);
  }
}

function rowPayload(row) {
  return {
    row: row.row,
    enabled: row.enabled,
    selectedEntities: normalizeList(row.selectedEntities),
    selectedFields: normalizeList(row.selectedFields),
    sourceUrls: normalizeList(row.sourceUrls),
  };
}

async function saveRow(rowNo) {
  const row = findRow(rowNo);
  if (!row) return;
  settingsState.busyRows.add(String(rowNo));
  render();
  try {
    const response = await fetch("/api/settings/row", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rowPayload(row)),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "保存失败");
    settingsState.rows = data.settings.rows.map((item) => ({
      ...item,
      entities: normalizeList(item.entities),
      fields: normalizeList(item.fields),
      selectedEntities: normalizeList(item.selectedEntities),
      selectedFields: normalizeList(item.selectedFields),
      sourceUrls: normalizeList(item.sourceUrls),
    }));
    appendLog(`${timePrefix()} 第 ${rowNo} 行设置已保存。`);
  } catch (error) {
    appendLog(`${timePrefix()} 第 ${rowNo} 行保存失败：${error.message}`);
  } finally {
    settingsState.busyRows.delete(String(rowNo));
    render();
  }
}

function valueFromRowInput(rowNo, role) {
  return els.list.querySelector(`[data-role="${role}"][data-row="${CSS.escape(String(rowNo))}"]`)?.value || "";
}

els.list.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement)) return;
  const rowNo = target.dataset.row;
  if (!rowNo) return;
  if (target.classList.contains("row-enabled")) {
    setRowEnabled(rowNo, target.checked);
    return;
  }
  toggleValue(rowNo, target.dataset.key, target.dataset.value, target.checked);
});

els.list.addEventListener("keydown", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLInputElement) || event.key !== "Enter") return;
  const rowNo = target.dataset.row;
  if (!rowNo) return;
  event.preventDefault();
  if (target.dataset.role === "entity-input" && addValue(rowNo, "entities", "selectedEntities", target.value)) return;
  if (target.dataset.role === "field-input" && addValue(rowNo, "fields", "selectedFields", target.value)) return;
  if (target.dataset.role === "url-input" && addSourceUrl(rowNo, target.value)) return;
});

els.list.addEventListener("click", (event) => {
  const target = event.target.closest("button");
  if (!(target instanceof HTMLButtonElement)) return;
  const row = findRow(target.dataset.row);
  if (!row) return;
  if (target.dataset.action === "all-entities") {
    const allSelected = row.selectedEntities.length === row.entities.length;
    toggleAll(row.row, "selectedEntities", row.entities, !allSelected);
  }
  if (target.dataset.action === "all-fields") {
    const allSelected = row.selectedFields.length === row.fields.length;
    toggleAll(row.row, "selectedFields", row.fields, !allSelected);
  }
  if (target.dataset.action === "add-entity") addValue(row.row, "entities", "selectedEntities", valueFromRowInput(row.row, "entity-input"));
  if (target.dataset.action === "add-field") addValue(row.row, "fields", "selectedFields", valueFromRowInput(row.row, "field-input"));
  if (target.dataset.action === "add-url") addSourceUrl(row.row, valueFromRowInput(row.row, "url-input"));
  if (target.dataset.action === "remove-entity") removeValue(row.row, "entities", "selectedEntities", target.dataset.value);
  if (target.dataset.action === "remove-field") removeValue(row.row, "fields", "selectedFields", target.dataset.value);
  if (target.dataset.action === "remove-url") removeSourceUrl(row.row, target.dataset.value);
  if (target.dataset.action === "save-row") saveRow(row.row);
});

els.filterInput.addEventListener("input", () => {
  settingsState.filter = els.filterInput.value;
  render();
});

els.logButton.addEventListener("click", () => {
  hydrateLogs();
  els.logModal.hidden = false;
  setTimeout(() => els.logBox.scrollTop = els.logBox.scrollHeight, 0);
});

els.closeLogButton.addEventListener("click", () => {
  els.logModal.hidden = true;
});

els.clearLogButton.addEventListener("click", () => {
  setLog("执行日志已清空。");
});

els.logModal.addEventListener("click", (event) => {
  if (event.target === els.logModal) els.logModal.hidden = true;
});

hydrateLogs();
setClock();
setInterval(setClock, 30000);
loadSettings();
