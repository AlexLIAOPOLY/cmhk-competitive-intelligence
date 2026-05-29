const els = {
  headerTime: document.getElementById("headerTime"),
  filterInput: document.getElementById("filterInput"),
  scheduleList: document.getElementById("scheduleList"),
  settingsSummary: document.getElementById("settingsSummary"),
  saveButton: document.getElementById("saveButton"), // keep or remove, but if they don't exist it might be null
  logBox: document.getElementById("logBox"),
  logButton: document.querySelector("button[onclick='openLogModal()']"),
  logModal: document.getElementById("logModal"),
};

let rawRows = [];

function setLog(text) {
  const timeStr = new Date().toLocaleTimeString();
  const savedLogs = localStorage.getItem("appLogs") || "";
  let newLog = `[${timeStr}] ${text}`;
  
  if (!savedLogs || savedLogs === "等待操作...") {
    els.logBox.textContent = newLog;
  } else {
    els.logBox.textContent = savedLogs + `\n` + newLog;
  }
  
  localStorage.setItem("appLogs", els.logBox.textContent);
  els.logBox.scrollTop = els.logBox.scrollHeight;
}

// Load logs on startup
const savedLogs = localStorage.getItem("appLogs");
if (savedLogs) {
  els.logBox.textContent = savedLogs;
  setTimeout(() => els.logBox.scrollTop = els.logBox.scrollHeight, 100);
}

function updateTime() {
  els.headerTime.textContent = new Date().toLocaleString("zh-CN", { timeZone: "Asia/Hong_Kong" }) + " · Asia/Hong_Kong";
}
setInterval(updateTime, 1000);
updateTime();

const freqOptions = ["每1小时", "每6小时", "每天 (03:00)", "每周一", "每月1号", "📅 指定具体日期...", "手动不自动"];

function calculateNextTime(lastFetched, freq) {
  if (!lastFetched || !freq || freq === "手动不自动") return "无自动排期";
  
  // 检查是否为绝对日期
  const isDate = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(freq);
  let next;
  if (isDate) {
    next = new Date(freq);
  } else {
    const last = new Date(lastFetched);
    if (isNaN(last)) return "等待首次运行";
    next = new Date(last);
  if (freq === "每1小时") {
    next.setHours(next.getHours() + 1);
  } else if (freq === "每6小时") {
    next.setHours(next.getHours() + 6);
  } else if (freq === "每天 (03:00)") {
    next.setDate(next.getDate() + 1);
    next.setHours(3, 0, 0, 0);
  } else if (freq === "每周一") {
    next.setDate(next.getDate() + ((7 - next.getDay() + 1) % 7 || 7));
    next.setHours(3, 0, 0, 0);
  } else if (freq === "每月1号") {
    next.setMonth(next.getMonth() + 1, 1);
    next.setHours(3, 0, 0, 0);
  } else {
    // 启发式解析飞书里的各种复杂中文字符串
    if (freq.includes("小时")) {
      const match = freq.match(/(\d+)小时/);
      const h = match ? parseInt(match[1]) : 1;
      next.setHours(next.getHours() + h);
    } else if (freq.includes("天") || freq.includes("日")) {
      next.setDate(next.getDate() + 1);
    } else if (freq.includes("周") || freq.includes("星期")) {
      next.setDate(next.getDate() + 7);
    } else if (freq.includes("半月")) {
      next.setDate(next.getDate() + 15);
    } else if (freq.includes("月")) {
      next.setMonth(next.getMonth() + 1);
    } else if (freq.includes("季")) {
      next.setMonth(next.getMonth() + 3);
    } else if (freq.includes("半年")) {
      next.setMonth(next.getMonth() + 6);
    } else if (freq.includes("年")) {
      next.setFullYear(next.getFullYear() + 1);
    } else {
      return "请选择标准频率";
    }
  }
  }
  
  const diffMs = next - new Date();
  if (diffMs <= 0) return { date: next, text: "即将执行" };
  
  const diffHours = diffMs / (1000 * 60 * 60);
  let text = "";
  if (diffHours < 24) {
    const h = Math.floor(diffHours);
    const m = Math.floor((diffHours - h) * 60);
    text = `约 ${h} 小时 ${m} 分钟后`;
  } else {
    text = `约 ${Math.floor(diffHours / 24)} 天后`;
  }
  return { date: next, text: text };
}

async function fetchSchedule() {
  try {
    setLog("正在从后台读取最新调度配置与运行状态...");
    const res = await fetch("/api/schedule");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    rawRows = data.rows || [];
    setLog(`成功读取 ${rawRows.length} 行配置。`);
    renderList();
  } catch (error) {
    setLog(`读取失败：${error.message}`);
    els.settingsSummary.textContent = "加载失败";
  }
}

function renderList() {
  const filterText = els.filterInput.value.toLowerCase().trim();
  els.scheduleList.innerHTML = "";
  let visibleCount = 0;

  for (const row of rawRows) {
    const searchString = `${row.row} ${row.object} ${row.frequency}`.toLowerCase();
    if (filterText && !searchString.includes(filterText)) {
      continue;
    }
    visibleCount++;

    const card = document.createElement("div");
    card.className = "settings-card";
    
    const headerDiv = document.createElement("div");
    headerDiv.className = "card-header";
    headerDiv.style.display = "flex";
    headerDiv.style.alignItems = "baseline";
    headerDiv.innerHTML = `<span class="row-badge">Row ${row.row}</span> <span class="object-badge" style="margin-right: 12px;">${row.object}</span> <span style="color:var(--text-secondary);font-size:12px;">[${row.block || "无分类"}]</span>`;

    const dataNeedsDiv = document.createElement("div");
    dataNeedsDiv.style.marginTop = "8px";
    dataNeedsDiv.style.fontSize = "13px";
    dataNeedsDiv.style.color = "var(--text)";
    dataNeedsDiv.style.background = "rgba(0,0,0,0.03)";
    dataNeedsDiv.style.padding = "8px";
    dataNeedsDiv.style.borderRadius = "4px";
    dataNeedsDiv.innerHTML = `<strong>监控数据要求：</strong> ${row.need || "未指定具体数据"}`;

    const inputDiv = document.createElement("div");
    inputDiv.style.marginTop = "12px";
    
    const selectField = document.createElement("select");
    selectField.className = "form-input freq-select";
    selectField.dataset.row = row.row;
    selectField.style.width = "100%";
    selectField.style.padding = "6px 12px";
    selectField.style.border = "1px solid var(--border)";
    selectField.style.borderRadius = "4px";
    selectField.style.fontSize = "14px";
    selectField.style.background = "rgba(255, 255, 255, 0.7)";
    
    const matchedOption = freqOptions.find(o => row.frequency && row.frequency.includes(o));
    const currentVal = matchedOption || row.frequency || "";
    
    const emptyOpt = document.createElement("option");
    emptyOpt.value = "";
    emptyOpt.text = "未设置";
    selectField.appendChild(emptyOpt);
    
    for (const opt of freqOptions) {
      const option = document.createElement("option");
      option.value = opt;
      option.text = opt;
      selectField.appendChild(option);
    }
    
    // Add custom current val if it's not in our list
    if (currentVal && !freqOptions.includes(currentVal)) {
      const customOpt = document.createElement("option");
      customOpt.value = currentVal;
      customOpt.text = currentVal;
      selectField.appendChild(customOpt);
    }
    selectField.value = currentVal;
    
    
    const dateField = document.createElement("input");
    dateField.type = "datetime-local";
    dateField.className = "form-input freq-date";
    dateField.style.width = "100%";
    dateField.style.padding = "6px 12px";
    dateField.style.border = "1px solid var(--border)";
    dateField.style.borderRadius = "4px";
    dateField.style.fontSize = "14px";
    dateField.style.background = "rgba(255, 255, 255, 0.7)";
    dateField.style.marginTop = "8px";
    dateField.style.display = "none";
    
    // Check if current value is a date
    const isDateVal = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(currentVal);
    if (isDateVal) {
      selectField.value = "📅 指定具体日期...";
      dateField.value = currentVal;
      dateField.style.display = "block";
    }
    
    selectField.addEventListener("change", (e) => {
      if (e.target.value === "📅 指定具体日期...") {
        dateField.style.display = "block";
        row.frequency = dateField.value || "";
      } else {
        dateField.style.display = "none";
        row.frequency = e.target.value;
      }
      renderList(); // re-render to update countdown
    });
    
    dateField.addEventListener("change", (e) => {
      row.frequency = e.target.value;
      renderList();
    });
    
    inputDiv.appendChild(selectField);
    inputDiv.appendChild(dateField);
    card.appendChild(headerDiv);
    card.appendChild(dataNeedsDiv);
    card.appendChild(inputDiv);
    
    // Footer with countdown and run button
    const footerDiv = document.createElement("div");
    footerDiv.style.marginTop = "12px";
    footerDiv.style.paddingTop = "12px";
    footerDiv.style.borderTop = "1px solid var(--border)";
    footerDiv.style.display = "flex";
    footerDiv.style.justifyContent = "space-between";
    footerDiv.style.alignItems = "center";
    
    const timeSpan = document.createElement("div");
    timeSpan.style.fontSize = "12px";
    timeSpan.style.color = "var(--text-secondary)";
    
    const lastTimeStr = row.last_fetched ? new Date(row.last_fetched).toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute:'2-digit'}) : "从未";
    const nextResult = calculateNextTime(row.last_fetched, row.frequency);
    
    let nextStr = "";
    if (typeof nextResult === "string") {
      nextStr = nextResult;
    } else if (nextResult && nextResult.date) {
      const nextDateStr = nextResult.date.toLocaleString('zh-CN', {year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute:'2-digit'});
      nextStr = `${nextDateStr} <span style="font-size: 11px; padding: 2px 6px; background: rgba(37, 99, 235, 0.1); border-radius: 4px; margin-left: 6px;">(${nextResult.text})</span>`;
    } else {
      nextStr = "无自动排期";
    }
    
    timeSpan.innerHTML = `上次: <strong>${lastTimeStr}</strong><br/>下次: <span style="color:var(--primary);font-weight:600;">${nextStr}</span>`;
    
    const runBtn = document.createElement("button");
    runBtn.className = "quiet-button";
    runBtn.style.padding = "4px 8px";
    runBtn.style.fontSize = "12px";
    runBtn.innerHTML = "▶ 运行该行";
    
    runBtn.addEventListener("click", async () => {
      try {
        runBtn.disabled = true;
        runBtn.innerHTML = "运行中...";
        if (els.logModal.style.display === "none" && els.logButton) els.logButton.classList.add("log-glowing");
        setLog(`正在运行单行爬虫 (Row ${row.row})... 这可能需要十几秒。`);
        
        const res = await fetch("/api/crawl-row", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ row: row.row })
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        setLog(`单行 (Row ${row.row}) 爬取完成！\n${data.result_text || ""}`);
        // refresh data
        fetchSchedule();
      } catch (err) {
        setLog(`单行运行失败: ${err.message}`);
        runBtn.disabled = false;
        runBtn.innerHTML = "▶ 运行该行";
      } finally {
        if (els.logButton) els.logButton.classList.remove("log-glowing");
      }
    });
    
    const saveRowBtn = document.createElement("button");
    saveRowBtn.className = "quiet-button";
    saveRowBtn.style.padding = "4px 8px";
    saveRowBtn.style.fontSize = "12px";
    saveRowBtn.style.marginRight = "8px";
    saveRowBtn.style.color = "#10b981"; // distinct color for save
    saveRowBtn.innerHTML = "💾 保存该行排期";
    
    saveRowBtn.addEventListener("click", async () => {
      try {
        saveRowBtn.disabled = true;
        saveRowBtn.innerHTML = "保存中...";
        if (els.logModal.style.display === "none" && els.logButton) els.logButton.classList.add("log-glowing");
        const res = await fetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rows: rawRows })
        });
        if (!res.ok) throw new Error(await res.text());
        setLog(`Row ${row.row} 排期保存成功！`);
        saveRowBtn.innerHTML = "已保存 ✔";
        setTimeout(() => {
          saveRowBtn.innerHTML = "💾 保存该行排期";
          saveRowBtn.disabled = false;
        }, 2000);
      } catch (err) {
        setLog(`Row ${row.row} 保存失败: ${err.message}`);
        saveRowBtn.disabled = false;
        saveRowBtn.innerHTML = "💾 保存该行排期";
      } finally {
        if (els.logButton) els.logButton.classList.remove("log-glowing");
      }
    });

    const btnGroup = document.createElement("div");
    btnGroup.style.display = "flex";
    btnGroup.appendChild(saveRowBtn);
    btnGroup.appendChild(runBtn);
    
    footerDiv.appendChild(timeSpan);
    footerDiv.appendChild(btnGroup);
    card.appendChild(footerDiv);

    els.scheduleList.appendChild(card);
  }

  els.settingsSummary.textContent = `共显示 ${visibleCount} / ${rawRows.length} 行`;
}

els.filterInput.addEventListener("input", renderList);



// Init
fetchSchedule();
