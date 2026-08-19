(() => {
  "use strict";

  const workspace = document.getElementById("newsReviewWorkspace");
  const openButton = document.getElementById("openNewsReviewSheetButton");
  if (!workspace || !openButton) return;

  const nodes = {
    close: document.getElementById("closeNewsReviewSheetButton"),
    feishu: document.getElementById("newsReviewFeishuLink"),
    search: document.getElementById("newsReviewSearchInput"),
    count: document.getElementById("newsReviewCountText"),
    selection: document.getElementById("newsReviewSelectionText"),
    clearFilters: document.getElementById("newsReviewClearFilters"),
    cellName: document.getElementById("newsReviewCellName"),
    cellValue: document.getElementById("newsReviewCellValue"),
    syncText: document.getElementById("newsReviewSyncText"),
    saveStatus: document.getElementById("newsReviewSaveStatus"),
    loading: document.getElementById("newsReviewLoading"),
    grid: document.getElementById("newsReviewGrid"),
    colgroup: document.getElementById("newsReviewColgroup"),
    head: document.getElementById("newsReviewHead"),
    body: document.getElementById("newsReviewBody"),
    shell: document.getElementById("newsReviewGridShell"),
    filterMenu: document.getElementById("newsReviewFilterMenu"),
  };

  const columnWidths = [120, 120, 116, 120, 120, 135, 410, 470, 150, 150, 285, 230, 285, 285];
  const model = {
    headers: [],
    rows: [],
    visibleRows: [],
    editableColumns: new Set(),
    statusOptions: ["待审核", "接受", "不接受", "暂缓"],
    filters: new Map(),
    sort: null,
    selectionAnchor: null,
    selectionFocus: null,
    dragging: false,
    loading: false,
    saving: false,
    activeEditor: null,
    cancelEditor: null,
  };
  const SNAPSHOT_CACHE_KEY = "cmhk-news-review-snapshot-v1";
  const SHEET_READ_TIMEOUT_MS = 30000;

  const escapeHtml = (value) => String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");

  const columnName = (index) => String.fromCharCode(65 + index);

  function setSaveStatus(text, tone = "") {
    nodes.saveStatus.textContent = text;
    nodes.saveStatus.className = tone ? `is-${tone}` : "";
  }

  function statusClass(value) {
    if (value === "接受") return "status-accepted";
    if (value === "不接受") return "status-rejected";
    if (value === "暂缓") return "status-deferred";
    return "status-pending";
  }

  function syncClass(value) {
    if (value === "已纳入") return "is-synced";
    if (value === "同步失败") return "is-failed";
    return "";
  }

  function updateVisibleRows() {
    const query = nodes.search.value.trim().toLocaleLowerCase("zh-Hans");
    model.visibleRows = model.rows.filter((row) => {
      if (query && !row.values.some((value) => String(value).toLocaleLowerCase("zh-Hans").includes(query))) {
        return false;
      }
      for (const [columnIndex, expected] of model.filters) {
        if (String(row.values[columnIndex] || "") !== expected) return false;
      }
      return true;
    });
    if (model.sort) {
      const { columnIndex, direction } = model.sort;
      model.visibleRows.sort((left, right) => String(left.values[columnIndex] || "").localeCompare(
        String(right.values[columnIndex] || ""),
        "zh-Hans",
        { numeric: true, sensitivity: "base" },
      ) * direction);
    }
  }

  function selectionBounds() {
    if (!model.selectionAnchor || !model.selectionFocus) return null;
    return {
      rowStart: Math.min(model.selectionAnchor.rowIndex, model.selectionFocus.rowIndex),
      rowEnd: Math.max(model.selectionAnchor.rowIndex, model.selectionFocus.rowIndex),
      columnStart: Math.min(model.selectionAnchor.columnIndex, model.selectionFocus.columnIndex),
      columnEnd: Math.max(model.selectionAnchor.columnIndex, model.selectionFocus.columnIndex),
    };
  }

  function updateSelectionDisplay() {
    const bounds = selectionBounds();
    nodes.body.querySelectorAll("td.is-selected, td.is-active").forEach((cell) => {
      cell.classList.remove("is-selected", "is-active");
    });
    if (!bounds) {
      nodes.selection.textContent = "选择单元格后可复制";
      nodes.cellName.textContent = "—";
      nodes.cellValue.textContent = "请选择单元格";
      return;
    }
    nodes.body.querySelectorAll("td[data-row-index][data-column-index]").forEach((cell) => {
      const rowIndex = Number(cell.dataset.rowIndex);
      const columnIndex = Number(cell.dataset.columnIndex);
      if (
        rowIndex >= bounds.rowStart && rowIndex <= bounds.rowEnd
        && columnIndex >= bounds.columnStart && columnIndex <= bounds.columnEnd
      ) cell.classList.add("is-selected");
      if (
        rowIndex === model.selectionFocus.rowIndex
        && columnIndex === model.selectionFocus.columnIndex
      ) cell.classList.add("is-active");
    });
    const cellCount = (bounds.rowEnd - bounds.rowStart + 1) * (bounds.columnEnd - bounds.columnStart + 1);
    nodes.selection.textContent = `${cellCount} 个单元格`;
    const activeRow = model.visibleRows[model.selectionFocus.rowIndex];
    if (activeRow) {
      nodes.cellName.textContent = `${columnName(model.selectionFocus.columnIndex)}${activeRow.rowNumber}`;
      nodes.cellValue.textContent = activeRow.values[model.selectionFocus.columnIndex] || "（空白）";
    }
  }

  function buildCell(row, rowIndex, columnIndex) {
    const value = String(row.values[columnIndex] || "");
    const cell = document.createElement("td");
    cell.dataset.rowIndex = String(rowIndex);
    cell.dataset.rowNumber = String(row.rowNumber);
    cell.dataset.columnIndex = String(columnIndex);
    cell.tabIndex = -1;
    cell.title = value;
    if (columnIndex === 0 || columnIndex === 1) {
      const select = document.createElement("select");
      select.className = `news-review-status-select ${statusClass(value)}`;
      select.setAttribute("aria-label", `${model.headers[columnIndex]}，第 ${row.rowNumber} 行`);
      model.statusOptions.forEach((optionValue) => {
        const option = document.createElement("option");
        option.value = optionValue;
        option.textContent = optionValue;
        option.selected = optionValue === value;
        select.appendChild(option);
      });
      select.addEventListener("pointerdown", (event) => event.stopPropagation());
      select.addEventListener("change", async () => {
        const next = select.value;
        select.className = `news-review-status-select ${statusClass(next)}`;
        await saveChanges([{
          rowNumber: row.rowNumber,
          columnIndex,
          before: value,
          value: next,
        }], [cell]);
      });
      cell.appendChild(select);
    } else if (columnIndex === 2) {
      const chip = document.createElement("span");
      chip.className = `news-review-sync-chip ${syncClass(value)}`;
      chip.textContent = value || "未同步";
      cell.appendChild(chip);
    } else if (columnIndex === 10 && /^https?:\/\//i.test(value)) {
      const link = document.createElement("a");
      link.href = value;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = value;
      link.addEventListener("pointerdown", (event) => event.stopPropagation());
      cell.appendChild(link);
    } else {
      const text = document.createElement("span");
      text.className = "news-review-cell-text";
      text.textContent = value || "-";
      cell.appendChild(text);
    }
    return cell;
  }

  function renderHead() {
    nodes.colgroup.replaceChildren();
    const rowNumberCol = document.createElement("col");
    rowNumberCol.style.width = "46px";
    nodes.colgroup.appendChild(rowNumberCol);
    model.headers.forEach((_header, index) => {
      const col = document.createElement("col");
      col.style.width = `${columnWidths[index] || 160}px`;
      nodes.colgroup.appendChild(col);
    });

    const letters = document.createElement("tr");
    const letterCorner = document.createElement("th");
    letterCorner.className = "news-review-corner";
    letters.appendChild(letterCorner);
    model.headers.forEach((_header, index) => {
      const th = document.createElement("th");
      th.textContent = columnName(index);
      letters.appendChild(th);
    });

    const labels = document.createElement("tr");
    const labelCorner = document.createElement("th");
    labelCorner.className = "news-review-corner";
    labelCorner.textContent = "1";
    labels.appendChild(labelCorner);
    model.headers.forEach((header, columnIndex) => {
      const th = document.createElement("th");
      const content = document.createElement("div");
      content.className = "news-review-header-cell";
      const sort = document.createElement("button");
      sort.type = "button";
      sort.className = "news-review-sort-button";
      sort.textContent = model.sort?.columnIndex === columnIndex
        ? `${header} ${model.sort.direction > 0 ? "↑" : "↓"}`
        : header;
      sort.title = `按“${header}”排序`;
      sort.addEventListener("click", () => {
        model.sort = model.sort?.columnIndex === columnIndex
          ? { columnIndex, direction: model.sort.direction * -1 }
          : { columnIndex, direction: 1 };
        render();
      });
      const filter = document.createElement("button");
      filter.type = "button";
      filter.className = `news-review-filter-button${model.filters.has(columnIndex) ? " is-active" : ""}`;
      filter.textContent = "▾";
      filter.title = `筛选“${header}”`;
      filter.setAttribute("aria-label", `筛选“${header}”`);
      filter.addEventListener("click", (event) => {
        event.stopPropagation();
        openFilterMenu(columnIndex, filter);
      });
      content.append(sort, filter);
      th.appendChild(content);
      labels.appendChild(th);
    });
    nodes.head.replaceChildren(letters, labels);
  }

  function renderBody() {
    const fragment = document.createDocumentFragment();
    model.visibleRows.forEach((row, rowIndex) => {
      const tr = document.createElement("tr");
      tr.dataset.rowNumber = String(row.rowNumber);
      const rowNumber = document.createElement("th");
      rowNumber.scope = "row";
      rowNumber.className = "news-review-row-number";
      rowNumber.textContent = String(row.rowNumber);
      tr.appendChild(rowNumber);
      row.values.forEach((_value, columnIndex) => tr.appendChild(buildCell(row, rowIndex, columnIndex)));
      fragment.appendChild(tr);
    });
    nodes.body.replaceChildren(fragment);
  }

  function render() {
    updateVisibleRows();
    renderHead();
    renderBody();
    nodes.count.textContent = model.visibleRows.length === model.rows.length
      ? `${model.rows.length} 条记录`
      : `${model.visibleRows.length} / ${model.rows.length} 条记录`;
    nodes.clearFilters.hidden = model.filters.size === 0 && !nodes.search.value;
    nodes.grid.hidden = false;
    nodes.loading.hidden = true;
    updateSelectionDisplay();
  }

  function applySnapshot(payload) {
    model.headers = Array.isArray(payload.headers) ? payload.headers.map(String) : [];
    model.rows = Array.isArray(payload.rows)
      ? payload.rows.map((row) => ({
        rowNumber: Number(row.rowNumber),
        values: model.headers.map((_header, index) => String(row.values?.[index] || "")),
      }))
      : [];
    model.editableColumns = new Set((payload.editableColumns || []).map(Number));
    if (Array.isArray(payload.statusOptions) && payload.statusOptions.length) {
      model.statusOptions = payload.statusOptions.map(String);
    }
    nodes.syncText.textContent = payload.updatedAt
      ? `已连接飞书 · ${new Date(payload.updatedAt).toLocaleString("zh-HK", { hour12: false })}`
      : "已连接飞书审核表";
    if (payload.sheetUrl) {
      nodes.feishu.href = payload.sheetUrl;
      nodes.feishu.hidden = false;
    }
    render();
  }

  function readCachedSnapshot() {
    try {
      const cached = JSON.parse(localStorage.getItem(SNAPSHOT_CACHE_KEY) || "null");
      if (!cached || !Array.isArray(cached.rows) || !Array.isArray(cached.headers)) return false;
      applySnapshot(cached);
      nodes.syncText.textContent = "正在后台更新 · 已显示上次审核表";
      return true;
    } catch (_error) {
      localStorage.removeItem(SNAPSHOT_CACHE_KEY);
      return false;
    }
  }

  async function loadSheet() {
    if (model.loading) return;
    model.loading = true;
    const hasRows = model.rows.length > 0;
    nodes.grid.hidden = !hasRows;
    nodes.loading.hidden = hasRows;
    nodes.loading.classList.remove("is-error");
    nodes.loading.textContent = "正在读取飞书审核表…";
    nodes.syncText.textContent = "正在连接飞书审核表";
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), SHEET_READ_TIMEOUT_MS);
    try {
      const response = await fetch("/api/news-review-sheet", {
        cache: "no-store",
        signal: controller.signal,
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "审核表读取失败");
      applySnapshot(payload);
      try { localStorage.setItem(SNAPSHOT_CACHE_KEY, JSON.stringify(payload)); } catch (_error) { /* cache is optional */ }
      setSaveStatus("实时回写飞书 · 修改后自动保存并回读");
    } catch (error) {
      const errorMessage = error?.name === "AbortError"
        ? "实时刷新超过 30 秒，已停止等待"
        : (error.message || String(error));
      if (!hasRows) {
        nodes.loading.hidden = false;
        nodes.loading.classList.add("is-error");
        nodes.loading.textContent = `读取失败：${errorMessage}`;
        setSaveStatus("尚未读取到可编辑数据", "error");
      } else {
        setSaveStatus(`${errorMessage}；当前显示上次成功读取的数据`, "error");
      }
      nodes.syncText.textContent = hasRows ? "显示缓存 · 实时刷新暂不可用" : "飞书连接失败";
    } finally {
      window.clearTimeout(timeoutId);
      model.loading = false;
    }
  }

  async function saveChanges(changes, cells = []) {
    if (!changes.length) return true;
    if (model.saving) {
      setSaveStatus("上一项修改仍在保存，请稍后再试", "saving");
      return false;
    }
    model.saving = true;
    cells.forEach((cell) => cell?.classList.add("is-saving"));
    nodes.body.querySelectorAll("select").forEach((select) => { select.disabled = true; });
    setSaveStatus(`正在保存 ${changes.length} 个单元格…`, "saving");
    try {
      const response = await fetch("/api/news-review-sheet/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ changes }),
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || "保存失败");
      applySnapshot(payload);
      setSaveStatus(`已保存 ${payload.changedCount || 0} 个单元格，并通过飞书回读`, "success");
      window.setTimeout(() => setSaveStatus("实时回写飞书 · 修改后自动保存并回读"), 3200);
      return true;
    } catch (error) {
      cells.forEach((cell) => cell?.classList.add("is-error"));
      setSaveStatus(`保存失败：${error.message || String(error)}`, "error");
      render();
      return false;
    } finally {
      model.saving = false;
      cells.forEach((cell) => cell?.classList.remove("is-saving"));
      nodes.body.querySelectorAll("select").forEach((select) => { select.disabled = false; });
    }
  }

  function openFilterMenu(columnIndex, trigger) {
    const selected = model.filters.get(columnIndex);
    const values = [...new Set(model.rows.map((row) => String(row.values[columnIndex] || "")))]
      .sort((a, b) => a.localeCompare(b, "zh-Hans", { numeric: true }))
      .slice(0, 300);
    nodes.filterMenu.replaceChildren();
    const addOption = (label, value) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = label;
      button.className = selected === value || (value === null && selected === undefined) ? "is-active" : "";
      button.addEventListener("click", () => {
        if (value === null) model.filters.delete(columnIndex);
        else model.filters.set(columnIndex, value);
        nodes.filterMenu.hidden = true;
        model.selectionAnchor = null;
        model.selectionFocus = null;
        render();
      });
      nodes.filterMenu.appendChild(button);
    };
    addOption("全部", null);
    values.forEach((value) => addOption(value || "（空白）", value));
    const rect = trigger.getBoundingClientRect();
    nodes.filterMenu.style.left = `${Math.min(rect.left, window.innerWidth - 242)}px`;
    nodes.filterMenu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 350)}px`;
    nodes.filterMenu.hidden = false;
  }

  function selectedMatrix() {
    const bounds = selectionBounds();
    if (!bounds) return [];
    return model.visibleRows.slice(bounds.rowStart, bounds.rowEnd + 1).map((row) =>
      row.values.slice(bounds.columnStart, bounds.columnEnd + 1));
  }

  function excelHtml(matrix, columnOffset = 0, includeHeaders = false) {
    const headerStyle = "font-weight:700;color:#ffffff;background:#205784;border:1px solid #dfe5e9;padding:6px;";
    const bodyStyle = "color:#28333b;background:#ffffff;border:1px solid #dfe5e9;padding:6px;vertical-align:top;";
    const rows = [];
    if (includeHeaders) {
      rows.push(`<tr>${model.headers.slice(columnOffset, columnOffset + (matrix[0]?.length || model.headers.length)).map((header) => `<th style="${headerStyle}">${escapeHtml(header)}</th>`).join("")}</tr>`);
    }
    matrix.forEach((row) => {
      rows.push(`<tr>${row.map((value, index) => {
        const columnIndex = columnOffset + index;
        let style = bodyStyle;
        if (columnIndex <= 2) style += "background:#f3f8fb;";
        if (columnIndex === 0 || columnIndex === 1) {
          if (value === "接受") style += "background:#28bd6a;color:#083b21;font-weight:700;";
          else if (value === "不接受") style += "background:#f0a6a6;color:#5b1717;font-weight:700;";
          else if (value === "暂缓") style += "background:#f0c36a;color:#4d3400;font-weight:700;";
          else style += "background:#aeb6bc;color:#28333b;font-weight:700;";
        } else if (columnIndex === 2) {
          if (value === "已纳入") style += "background:#0f6fe8;color:#ffffff;font-weight:700;";
          else if (value === "同步失败") style += "background:#d94b4b;color:#ffffff;font-weight:700;";
          else style += "background:#aeb6bc;color:#28333b;font-weight:700;";
        }
        return `<td style="${style}">${escapeHtml(value)}</td>`;
      }).join("")}</tr>`);
    });
    return `<html><head><meta charset="utf-8"></head><body><table style="border-collapse:collapse;font-family:Arial,'Microsoft YaHei',sans-serif;font-size:11pt;">${rows.join("")}</table></body></html>`;
  }

  function clipboardPayload() {
    const matrix = selectedMatrix();
    if (!matrix.length) return null;
    const bounds = selectionBounds();
    return {
      text: matrix.map((row) => row.join("\t")).join("\n"),
      html: excelHtml(matrix, bounds.columnStart, false),
    };
  }

  function startCellEditor(cell) {
    if (!cell || model.activeEditor) return;
    if (model.saving) {
      setSaveStatus("上一项修改仍在保存，请稍后再编辑", "saving");
      return;
    }
    const columnIndex = Number(cell.dataset.columnIndex);
    const rowIndex = Number(cell.dataset.rowIndex);
    if (!model.editableColumns.has(columnIndex) || columnIndex <= 2) return;
    const row = model.visibleRows[rowIndex];
    if (!row) return;
    const before = String(row.values[columnIndex] || "");
    const editor = document.createElement("textarea");
    editor.className = "news-review-cell-editor";
    editor.value = before;
    cell.appendChild(editor);
    model.activeEditor = editor;
    editor.focus();
    editor.select();
    let finished = false;
    const finish = async (save) => {
      if (finished) return;
      finished = true;
      const value = editor.value;
      model.activeEditor = null;
      model.cancelEditor = null;
      editor.remove();
      if (save && value !== before) {
        await saveChanges([{ rowNumber: row.rowNumber, columnIndex, before, value }], [cell]);
      }
    };
    model.cancelEditor = () => finish(false);
    editor.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      } else if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        finish(true);
      }
    });
    editor.addEventListener("blur", () => finish(true));
  }

  async function pasteAtSelection(event) {
    if (!model.selectionFocus) return;
    const text = event.clipboardData?.getData("text/plain") || "";
    if (!text) return;
    event.preventDefault();
    const inputRows = text.replace(/\r/g, "").split("\n");
    if (inputRows.at(-1) === "") inputRows.pop();
    const matrix = inputRows.map((line) => line.split("\t"));
    const changes = [];
    const cells = [];
    matrix.forEach((values, rowOffset) => {
      const targetRowIndex = model.selectionFocus.rowIndex + rowOffset;
      const targetRow = model.visibleRows[targetRowIndex];
      if (!targetRow) return;
      values.forEach((value, columnOffset) => {
        const columnIndex = model.selectionFocus.columnIndex + columnOffset;
        if (!model.editableColumns.has(columnIndex)) return;
        changes.push({
          rowNumber: targetRow.rowNumber,
          columnIndex,
          before: targetRow.values[columnIndex],
          value,
        });
        cells.push(nodes.body.querySelector(`td[data-row-index="${targetRowIndex}"][data-column-index="${columnIndex}"]`));
      });
    });
    if (changes.length > 200) {
      setSaveStatus("单次粘贴最多 200 个可编辑单元格", "error");
      return;
    }
    await saveChanges(changes, cells);
  }

  function openWorkspace() {
    workspace.hidden = false;
    document.body.classList.add("news-review-open");
    nodes.close.focus();
    if (!model.rows.length) readCachedSnapshot();
    loadSheet();
  }

  function closeWorkspace() {
    if (workspace.classList.contains("workspace-inline-review")) return;
    model.cancelEditor?.();
    workspace.hidden = true;
    nodes.filterMenu.hidden = true;
    document.body.classList.remove("news-review-open");
    openButton.focus();
  }

  openButton.addEventListener("click", openWorkspace);
  nodes.close.addEventListener("click", closeWorkspace);
  nodes.search.addEventListener("input", () => {
    model.selectionAnchor = null;
    model.selectionFocus = null;
    render();
  });
  nodes.clearFilters.addEventListener("click", () => {
    model.filters.clear();
    nodes.search.value = "";
    render();
  });

  nodes.body.addEventListener("pointerdown", (event) => {
    const cell = event.target.closest("td[data-row-index][data-column-index]");
    if (!cell || event.target.closest("select, a, textarea")) return;
    event.preventDefault();
    const point = { rowIndex: Number(cell.dataset.rowIndex), columnIndex: Number(cell.dataset.columnIndex) };
    if (event.shiftKey && model.selectionAnchor) model.selectionFocus = point;
    else model.selectionAnchor = model.selectionFocus = point;
    model.dragging = true;
    updateSelectionDisplay();
  });

  nodes.body.addEventListener("pointerover", (event) => {
    if (!model.dragging) return;
    const cell = event.target.closest("td[data-row-index][data-column-index]");
    if (!cell) return;
    model.selectionFocus = { rowIndex: Number(cell.dataset.rowIndex), columnIndex: Number(cell.dataset.columnIndex) };
    updateSelectionDisplay();
  });

  nodes.body.addEventListener("dblclick", (event) => {
    const cell = event.target.closest("td[data-row-index][data-column-index]");
    if (cell && !event.target.closest("select")) startCellEditor(cell);
  });

  document.addEventListener("pointerup", () => { model.dragging = false; });
  document.addEventListener("click", (event) => {
    if (!event.target.closest("#newsReviewFilterMenu, .news-review-filter-button")) nodes.filterMenu.hidden = true;
  });

  workspace.addEventListener("copy", (event) => {
    if (event.target.matches("input, textarea")) return;
    const payload = clipboardPayload();
    if (!payload || !event.clipboardData) return;
    event.preventDefault();
    event.clipboardData.setData("text/plain", payload.text);
    event.clipboardData.setData("text/html", payload.html);
    setSaveStatus("已复制所选区域，可直接粘贴到 Excel", "success");
  });
  workspace.addEventListener("paste", (event) => {
    if (event.target.matches("input, textarea")) return;
    pasteAtSelection(event);
  });

  document.addEventListener("keydown", (event) => {
    if (workspace.hidden) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopImmediatePropagation();
      if (!nodes.filterMenu.hidden) nodes.filterMenu.hidden = true;
      else if (model.cancelEditor) model.cancelEditor();
      else if (!workspace.classList.contains("workspace-inline-review")) closeWorkspace();
      return;
    }
    if (event.target.matches("input, textarea, select") || !model.selectionFocus) return;
    const deltas = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (deltas[event.key]) {
      event.preventDefault();
      const [rowDelta, columnDelta] = deltas[event.key];
      const point = {
        rowIndex: Math.max(0, Math.min(model.visibleRows.length - 1, model.selectionFocus.rowIndex + rowDelta)),
        columnIndex: Math.max(0, Math.min(model.headers.length - 1, model.selectionFocus.columnIndex + columnDelta)),
      };
      if (event.shiftKey) model.selectionFocus = point;
      else model.selectionAnchor = model.selectionFocus = point;
      updateSelectionDisplay();
      nodes.body.querySelector(`td[data-row-index="${point.rowIndex}"][data-column-index="${point.columnIndex}"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
    } else if (event.key === "Enter") {
      event.preventDefault();
      const cell = nodes.body.querySelector(`td[data-row-index="${model.selectionFocus.rowIndex}"][data-column-index="${model.selectionFocus.columnIndex}"]`);
      startCellEditor(cell);
    }
  }, true);
})();
