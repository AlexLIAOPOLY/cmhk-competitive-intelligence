const settingsState = {
  rows: [],
  busy: false,
  filter: "",
};

const els = {
  headerTime: document.querySelector("#headerTime"),
  saveButton: document.querySelector("#saveButton"),
  resetButton: document.querySelector("#resetButton"),
  crawlButton: document.querySelector("#crawlButton"),
  filterInput: document.querySelector("#filterInput"),
  summary: document.querySelector("#settingsSummary"),
  list: document.querySelector("#settingsList"),
  logBox: document.querySelector("#logBox"),
};

function setClock() {
  els.headerTime.textContent = `${new Date().toLocaleString("zh-CN", { hour12: false })} · Asia/Hong_Kong`;
}

function setBusy(value, label = "处理中") {
  settingsState.busy = value;
  [els.saveButton, els.resetButton, els.crawlButton, els.filterInput].forEach((item) => {
    item.disabled = value;
  });
  if (value) els.summary.textContent = label;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function setRowEnabled(rowNo, enabled) {
  const row = settingsState.rows.find((item) => item.row === rowNo);
  if (!row) return;
  row.enabled = enabled;
  render();
}

function toggleValue(rowNo, key, value, checked) {
  const row = settingsState.rows.find((item) => item.row === rowNo);
  if (!row) return;
  const values = new Set(row[key]);
  if (checked) values.add(value);
  else values.delete(value);
  row[key] = Array.from(values);
  render();
}

function toggleAll(rowNo, key, values, checked) {
  const row = settingsState.rows.find((item) => item.row === rowNo);
  if (!row) return;
  row[key] = checked ? [...values] : [];
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
  ]
    .join(" ")
    .toLowerCase()
    .includes(query);
}

function renderOptionList(row, key, allValues, selectedValues) {
  if (!allValues.length) return '<span class="empty-note">暂无可配置字段</span>';
  return allValues
    .map((value) => {
      const id = `${key}-${row.row}-${value}`.replace(/[^\w\u4e00-\u9fa5-]+/g, "-");
      const checked = selectedValues.includes(value) ? "checked" : "";
      return `
        <label class="check-chip" for="${escapeHtml(id)}">
          <input id="${escapeHtml(id)}" type="checkbox" ${checked}
            data-row="${escapeHtml(row.row)}" data-key="${escapeHtml(key)}" data-value="${escapeHtml(value)}" />
          <span>${escapeHtml(value)}</span>
        </label>
      `;
    })
    .join("");
}

function render() {
  const rows = settingsState.rows.filter(rowMatches);
  const enabledRows = settingsState.rows.filter((row) => row.enabled);
  const selectedEntityCount = enabledRows.reduce((total, row) => total + row.selectedEntities.length, 0);
  const selectedFieldCount = enabledRows.reduce((total, row) => total + row.selectedFields.length, 0);
  els.summary.textContent = `启用 ${enabledRows.length} / ${settingsState.rows.length} 行，${selectedEntityCount} 个主体，${selectedFieldCount} 个字段`;

  if (!rows.length) {
    els.list.innerHTML = '<div class="settings-empty">没有匹配的爬取项。</div>';
    return;
  }

  els.list.innerHTML = rows
    .map((row) => {
      const enabled = row.enabled ? "checked" : "";
      return `
        <article class="setting-row ${row.enabled ? "" : "is-disabled"}">
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
                <strong>公司 / 主体</strong>
                <button type="button" class="inline-button" data-row="${escapeHtml(row.row)}" data-key="selectedEntities" data-action="all-entities">全选</button>
              </div>
              <div class="chip-grid">${renderOptionList(row, "selectedEntities", row.entities, row.selectedEntities)}</div>
            </section>
            <section>
              <div class="setting-subhead">
                <strong>具体数据内容</strong>
                <button type="button" class="inline-button" data-row="${escapeHtml(row.row)}" data-key="selectedFields" data-action="all-fields">全选</button>
              </div>
              <div class="chip-grid">${renderOptionList(row, "selectedFields", row.fields, row.selectedFields)}</div>
            </section>
          </div>
        </article>
      `;
    })
    .join("");
}

async function loadSettings() {
  setBusy(true, "加载设置");
  try {
    const response = await fetch("/api/settings");
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "设置加载失败");
    settingsState.rows = data.settings.rows;
    render();
  } catch (error) {
    els.logBox.textContent = `加载失败：${error.message}`;
  } finally {
    setBusy(false);
    render();
  }
}

async function saveSettings() {
  setBusy(true, "保存设置");
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        rows: settingsState.rows.map((row) => ({
          row: row.row,
          enabled: row.enabled,
          selectedEntities: row.selectedEntities,
          selectedFields: row.selectedFields,
        })),
      }),
    });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "保存失败");
    settingsState.rows = data.settings.rows;
    els.logBox.textContent = `保存完成：${data.settings.path}`;
    render();
  } catch (error) {
    els.logBox.textContent = `保存失败：${error.message}`;
  } finally {
    setBusy(false);
  }
}

async function resetSettings() {
  setBusy(true, "恢复全量");
  try {
    const response = await fetch("/api/settings/reset", { method: "POST" });
    const data = await response.json();
    if (!data.ok) throw new Error(data.error || "恢复失败");
    settingsState.rows = data.settings.rows;
    els.logBox.textContent = "已恢复为全量爬取范围。";
    render();
  } catch (error) {
    els.logBox.textContent = `恢复失败：${error.message}`;
  } finally {
    setBusy(false);
  }
}

async function runCrawl() {
  setBusy(true, "正在按设置爬取");
  els.logBox.textContent = "开始按当前设置执行爬虫...";
  try {
    const response = await fetch("/api/crawl", { method: "POST" });
    const data = await response.json();
    if (!data.ok) throw new Error(data.stderr || data.error || "爬取失败");
    els.logBox.textContent = [
      `爬取完成：${data.durationMs} ms`,
      data.stdout ? `执行输出：\n${data.stdout}` : "",
    ]
      .filter(Boolean)
      .join("\n\n");
  } catch (error) {
    els.logBox.textContent = `爬取失败：${error.message}`;
  } finally {
    setBusy(false);
    render();
  }
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

els.list.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLButtonElement)) return;
  const row = settingsState.rows.find((item) => item.row === target.dataset.row);
  if (!row) return;
  if (target.dataset.action === "all-entities") {
    const allSelected = row.selectedEntities.length === row.entities.length;
    toggleAll(row.row, "selectedEntities", row.entities, !allSelected);
  }
  if (target.dataset.action === "all-fields") {
    const allSelected = row.selectedFields.length === row.fields.length;
    toggleAll(row.row, "selectedFields", row.fields, !allSelected);
  }
});

els.filterInput.addEventListener("input", () => {
  settingsState.filter = els.filterInput.value;
  render();
});

els.saveButton.addEventListener("click", saveSettings);
els.resetButton.addEventListener("click", resetSettings);
els.crawlButton.addEventListener("click", runCrawl);

setClock();
setInterval(setClock, 30000);
loadSettings();
