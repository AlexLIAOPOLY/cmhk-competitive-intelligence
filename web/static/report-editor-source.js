import { Editor, Extension, Node, mergeAttributes } from "@tiptap/core";
import { StarterKit } from "@tiptap/starter-kit";
import { TextAlign } from "@tiptap/extension-text-align";
import { TextStyleKit } from "@tiptap/extension-text-style";
import { Highlight } from "@tiptap/extension-highlight";
import { Image } from "@tiptap/extension-image";
import { Table, TableCell, TableHeader, TableRow } from "@tiptap/extension-table";
import { Subscript } from "@tiptap/extension-subscript";
import { Superscript } from "@tiptap/extension-superscript";
import { Placeholder } from "@tiptap/extension-placeholder";
import { TextSelection } from "@tiptap/pm/state";

const BLOCK_ATTRS = {
  docxStyle: { default: null, parseHTML: (element) => element.dataset.docxStyle || null, renderHTML: (attrs) => attrs.docxStyle ? { "data-docx-style": attrs.docxStyle } : {} },
  spaceBefore: { default: null },
  spaceAfter: { default: null },
  firstLineIndent: { default: null },
  leftIndent: { default: null },
  rightIndent: { default: null },
  keepWithNext: { default: null },
  keepTogether: { default: null },
  pageBreakBefore: { default: null },
  widowControl: { default: null },
  paragraphMark: { default: null },
  docxDrawingIds: { default: null },
  tabStops: { default: null },
};

function blockStyle(attrs) {
  const css = [];
  const point = (name, property) => {
    const value = Number(attrs[name]);
    if (Number.isFinite(value)) css.push(`${property}:${Math.max(-360, Math.min(720, value))}pt`);
  };
  point("spaceBefore", "margin-top");
  point("spaceAfter", "margin-bottom");
  point("firstLineIndent", "text-indent");
  point("leftIndent", "margin-left");
  point("rightIndent", "margin-right");
  if (attrs.keepTogether) css.push("break-inside:avoid");
  if (attrs.pageBreakBefore) css.push("break-before:page");
  return css.join(";");
}

const DocxBlockAttributes = Extension.create({
  name: "docxBlockAttributes",
  addGlobalAttributes() {
    return [{
      types: ["paragraph", "heading"],
      attributes: Object.fromEntries(Object.entries(BLOCK_ATTRS).map(([name, config]) => [name, {
        ...config,
        renderHTML: name === "docxStyle"
          ? config.renderHTML
          : (attrs) => blockStyle(attrs) ? { style: blockStyle(attrs) } : {},
      }])),
    }];
  },
});

const DocxTextAttributes = Extension.create({
  name: "docxTextAttributes",
  addGlobalAttributes() {
    return [{
      types: ["textStyle"],
      attributes: {
        docxFontHint: { default: null },
        docxCharacterSpacing: {
          default: null,
          renderHTML: (attrs) => Number.isFinite(Number(attrs.docxCharacterSpacing))
            ? { style: `letter-spacing:${Number(attrs.docxCharacterSpacing) / 20}pt` }
            : {},
        },
        docxPosition: {
          default: null,
          renderHTML: (attrs) => Number.isFinite(Number(attrs.docxPosition))
            ? { style: `position:relative;top:${-Number(attrs.docxPosition) / 2}pt` }
            : {},
        },
      },
    }];
  },
});

const PageBreak = Node.create({
  name: "pageBreak",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  parseHTML: () => [{ tag: "span[data-page-break]" }],
  renderHTML: () => ["span", { "data-page-break": "", contenteditable: "false", title: "分页符" }, "分页符"],
  addCommands() {
    return { insertPageBreak: () => ({ commands }) => commands.insertContent({ type: this.name }) };
  },
});

const EditorImage = Image.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      width: { default: null, parseHTML: (element) => element.getAttribute("width"), renderHTML: (attrs) => attrs.width ? { width: attrs.width } : {} },
      height: { default: null, parseHTML: (element) => element.getAttribute("height"), renderHTML: (attrs) => attrs.height ? { height: attrs.height } : {} },
      docxDrawingId: { default: null },
    };
  },
}).configure({ inline: true, allowBase64: true });

const EditorTable = Table.extend({
  addAttributes() {
    return {
      ...this.parent?.(),
      docxStyle: { default: null, parseHTML: (element) => element.dataset.docxStyle || null, renderHTML: (attrs) => attrs.docxStyle ? { "data-docx-style": attrs.docxStyle } : {} },
    };
  },
}).configure({ resizable: true, lastColumnResizable: false });

function cellExtension(base) {
  return base.extend({
    addAttributes() {
      return {
        ...this.parent?.(),
        backgroundColor: {
          default: null,
          parseHTML: (element) => element.style.backgroundColor || null,
          renderHTML: (attrs) => attrs.backgroundColor ? { style: `background-color:${attrs.backgroundColor}` } : {},
        },
      };
    },
  });
}

const EditorTableCell = cellExtension(TableCell);
const EditorTableHeader = cellExtension(TableHeader);
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
const icon = (name) => ({
  undo: '<svg viewBox="0 0 24 24"><path d="M9 7 4 12l5 5M5 12h8a6 6 0 0 1 6 6"/></svg>',
  redo: '<svg viewBox="0 0 24 24"><path d="m15 7 5 5-5 5m4-5h-8a6 6 0 0 0-6 6"/></svg>',
  bold: '<b>B</b>', italic: '<i>I</i>', underline: '<u>U</u>', strike: '<s>ab</s>',
  alignLeft: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 10h11M4 14h16M4 18h11"/></svg>',
  alignCenter: '<svg viewBox="0 0 24 24"><path d="M4 6h16M7 10h10M4 14h16M7 18h10"/></svg>',
  alignRight: '<svg viewBox="0 0 24 24"><path d="M4 6h16M9 10h11M4 14h16M9 18h11"/></svg>',
  justify: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>',
  bullet: '<svg viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1"/><circle cx="4.5" cy="12" r="1"/><circle cx="4.5" cy="18" r="1"/></svg>',
  ordered: '<svg viewBox="0 0 24 24"><path d="M9 6h11M9 12h11M9 18h11M3 5h2v3M3 11h2l-2 3h2M3 17h2v3H3"/></svg>',
  outdent: '<svg viewBox="0 0 24 24"><path d="M10 6h10M10 12h10M10 18h10M7 9l-3 3 3 3"/></svg>',
  indent: '<svg viewBox="0 0 24 24"><path d="M10 6h10M10 12h10M10 18h10M4 9l3 3-3 3"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M9 15 15 9M8 7H7a5 5 0 0 0 0 10h3M16 7h1a5 5 0 0 1 0 10h-3"/></svg>',
  image: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8" cy="9" r="1.5"/><path d="m4 17 5-5 4 4 3-3 4 4"/></svg>',
  table: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="1"/><path d="M3 10h18M3 15h18M10 4v16M16 4v16"/></svg>',
  page: '<svg viewBox="0 0 24 24"><path d="M6 3h9l3 3v5M6 3v7M5 14h14M5 18h14"/></svg>',
  rule: '<svg viewBox="0 0 24 24"><path d="M3 12h18"/></svg>',
  clear: '<svg viewBox="0 0 24 24"><path d="m5 16 8-10 6 5-7 9H7zM3 21h18"/></svg>',
  close: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
}[name] || "");

const shell = document.querySelector("#reportEditorModal");
const mount = document.querySelector("#reportEditorMount");
const workspace = document.querySelector("#reportEditorWorkspace");
const editPane = document.querySelector(".report-editor-edit-pane");
const proofPane = document.querySelector("#reportEditorProofPane");
const proofMount = document.querySelector("#reportEditorProofMount");
const proofState = document.querySelector("#reportEditorProofState");
const proofToggle = document.querySelector("#reportEditorProofToggle");
const ribbon = document.querySelector("#reportEditorRibbon");
const status = document.querySelector("#reportEditorStatus");
const fileName = document.querySelector("#reportEditorFileName");
const wordCount = document.querySelector("#reportEditorWordCount");
const saveButton = document.querySelector("#reportEditorSave");
const copyButton = document.querySelector("#reportEditorSaveCopy");
const closeButton = document.querySelector("#reportEditorClose");
const zoomInput = document.querySelector("#reportEditorZoom");
const imageInput = document.querySelector("#reportEditorImageInput");
const linkDialog = document.querySelector("#reportEditorLinkDialog");
let editor = null;
let current = null;
let dirty = false;
let saving = false;
let draftTimer = 0;
let proofRequest = 0;

function button(command, label, symbol, title = label) {
  return `<button type="button" class="report-editor-tool" data-editor-command="${command}" title="${esc(title)}" aria-label="${esc(title)}">${symbol}<span>${esc(label)}</span></button>`;
}

function ribbonMarkup() {
  return `<div class="report-editor-ribbon-row">
    <div class="report-editor-group compact" aria-label="撤销与恢复">${button("undo", "撤销", icon("undo"), "撤销 ⌘Z")}${button("redo", "恢复", icon("redo"), "恢复 ⇧⌘Z")}</div>
    <div class="report-editor-group font-group" aria-label="字体">
      <label><span class="sr-only">段落样式</span><select data-editor-select="block" data-custom-select="native" title="段落样式"><option value="paragraph">正文</option><option value="heading-1">标题 1</option><option value="heading-2">标题 2</option><option value="heading-3">标题 3</option><option value="heading-4">标题 4</option></select></label>
      <label><span class="sr-only">字体</span><select data-editor-select="font" data-custom-select="native" title="字体"><option value="">沿用原字体</option><option value="Arial">Arial</option><option value="Calibri">Calibri</option><option value="DengXian">等线</option><option value="FangSong">仿宋</option><option value="Microsoft YaHei">微软雅黑</option><option value="SimSun">宋体</option><option value="SimHei">黑体</option><option value="PingFang SC">苹方</option></select></label>
      <label><span class="sr-only">字号</span><select data-editor-select="size" data-custom-select="native" title="字号"><option value="">字号</option>${[9,10,10.5,11,12,14,16,18,22,26,32,36,48].map((size) => `<option value="${size}pt">${size}</option>`).join("")}</select></label>
      ${button("bold", "加粗", icon("bold"))}${button("italic", "斜体", icon("italic"))}${button("underline", "下划线", icon("underline"))}${button("strike", "删除线", icon("strike"))}
      ${button("subscript", "下标", "X<sub>2</sub>")}${button("superscript", "上标", "X<sup>2</sup>")}
      <label class="report-editor-color" title="字体颜色"><input type="color" value="#111111" data-editor-color="text" aria-label="字体颜色"><span>A</span></label>
      <label class="report-editor-color highlight" title="突出显示"><input type="color" value="#ffff00" data-editor-color="highlight" aria-label="突出显示颜色"><span>ab</span></label>
    </div>
    <div class="report-editor-group paragraph-group" aria-label="段落">
      ${button("align-left", "左对齐", icon("alignLeft"))}${button("align-center", "居中", icon("alignCenter"))}${button("align-right", "右对齐", icon("alignRight"))}${button("align-justify", "两端", icon("justify"))}
      ${button("bullet", "项目", icon("bullet"))}${button("ordered", "编号", icon("ordered"))}${button("outdent", "减少缩进", icon("outdent"))}${button("indent", "增加缩进", icon("indent"))}
      <label><span class="sr-only">行距</span><select data-editor-select="line-height" data-custom-select="native" title="行距"><option value="">行距</option><option value="1">1.0</option><option value="1.15">1.15</option><option value="1.5">1.5</option><option value="2">2.0</option></select></label>
    </div>
    <div class="report-editor-group insert-group" aria-label="插入">
      ${button("link", "链接", icon("link"))}${button("image", "图片", icon("image"))}${button("table", "表格", icon("table"))}${button("page-break", "分页", icon("page"))}${button("horizontal-rule", "分隔线", icon("rule"))}${button("clear", "清除格式", icon("clear"))}
    </div>
  </div>
  <div class="report-editor-ribbon-row secondary">
    <div class="report-editor-group table-tools" aria-label="表格工具">
      <span>表格</span>${button("row-after", "下方加行", "+行")}${button("column-after", "右侧加列", "+列")}${button("delete-row", "删行", "−行")}${button("delete-column", "删列", "−列")}${button("delete-table", "删表", "×表")}
    </div>
    <div class="report-editor-search" role="search"><input type="search" id="reportEditorSearch" placeholder="查找" aria-label="查找文字"><input type="text" id="reportEditorReplace" placeholder="替换为" aria-label="替换文字"><button type="button" data-editor-find>下一个</button><button type="button" data-editor-replace>替换</button><button type="button" data-editor-replace-all>全部替换</button></div>
  </div>`;
}

function setStatus(message, tone = "") {
  if (!status) return;
  status.textContent = message;
  status.dataset.tone = tone;
}

function draftKey() {
  return current ? `cmhk-report-editor-draft:${current.path}:${current.sourceSha256}` : "";
}

function clearDraft() {
  try { if (draftKey()) localStorage.removeItem(draftKey()); } catch (_error) { /* Storage may be disabled. */ }
}

function persistDraft() {
  if (!dirty || !editor || !current) return;
  try {
    localStorage.setItem(draftKey(), JSON.stringify({ at: Date.now(), document: editor.getJSON() }));
    setStatus("草稿已在此浏览器临时保存", "draft");
  } catch (_error) {
    setStatus("有未保存修改", "dirty");
  }
}

function saveDraftSoon() {
  window.clearTimeout(draftTimer);
  draftTimer = window.setTimeout(() => {
    persistDraft();
  }, 900);
}

function updateCounts() {
  if (!editor || !wordCount) return;
  const text = editor.getText({ blockSeparator: "\n" });
  const latinWords = text.trim().match(/[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*/g) || [];
  const cjk = text.match(/[\u3400-\u9fff\uf900-\ufaff]/g) || [];
  wordCount.textContent = `${cjk.length + latinWords.length} 字词 · ${text.replace(/\s/g, "").length} 字符`;
}

function updateToolbar() {
  if (!editor || !ribbon) return;
  const active = {
    bold: editor.isActive("bold"), italic: editor.isActive("italic"), underline: editor.isActive("underline"), strike: editor.isActive("strike"),
    subscript: editor.isActive("subscript"), superscript: editor.isActive("superscript"), bullet: editor.isActive("bulletList"), ordered: editor.isActive("orderedList"),
    "align-left": editor.isActive({ textAlign: "left" }), "align-center": editor.isActive({ textAlign: "center" }), "align-right": editor.isActive({ textAlign: "right" }), "align-justify": editor.isActive({ textAlign: "justify" }),
  };
  ribbon.querySelectorAll("[data-editor-command]").forEach((item) => item.classList.toggle("is-active", Boolean(active[item.dataset.editorCommand])));
  const block = ribbon.querySelector('[data-editor-select="block"]');
  if (block) block.value = [1,2,3,4,5,6].find((level) => editor.isActive("heading", { level })) ? `heading-${[1,2,3,4,5,6].find((level) => editor.isActive("heading", { level }))}` : "paragraph";
}

function editorExtensions() {
  return [
    StarterKit.configure({ link: { openOnClick: false, autolink: true, defaultProtocol: "https" } }),
    DocxBlockAttributes,
    DocxTextAttributes,
    TextAlign.configure({ types: ["heading", "paragraph"] }),
    TextStyleKit,
    Highlight.configure({ multicolor: true }),
    EditorImage,
    EditorTable,
    TableRow,
    EditorTableHeader,
    EditorTableCell,
    Subscript,
    Superscript,
    PageBreak,
    Placeholder.configure({ placeholder: "开始撰写报告…" }),
  ];
}

function renderPage(page = {}) {
  const width = Number(page.widthIn) || 8.27;
  const height = Number(page.heightIn) || 11.69;
  const top = Number(page.topMarginIn) || 0.8;
  const right = Number(page.rightMarginIn) || 0.8;
  const bottom = Number(page.bottomMarginIn) || 0.8;
  const left = Number(page.leftMarginIn) || 0.8;
  mount.innerHTML = `<div class="report-editor-ruler" aria-hidden="true"><span>0</span><i></i><span>2</span><i></i><span>4</span><i></i><span>6</span><i></i><span>8</span></div><div class="report-editor-page" style="--page-width:${width}in;--page-height:${height}in;--page-top:${top}in;--page-right:${right}in;--page-bottom:${bottom}in;--page-left:${left}in"><div id="reportEditorContent"></div></div>`;
  return mount.querySelector("#reportEditorContent");
}

function setProofState(text, tone = "ready") {
  if (!proofState) return;
  proofState.textContent = text;
  proofState.dataset.tone = tone;
}

function setProofVisible(visible) {
  const next = Boolean(visible);
  workspace?.classList.toggle("is-proof-open", next);
  if (proofPane) proofPane.hidden = !next;
  if (proofToggle) {
    proofToggle.setAttribute("aria-pressed", String(next));
    proofToggle.textContent = next ? "关闭对照" : "最终版式";
  }
  if (current?.page) window.requestAnimationFrame(() => applyZoom(preferredZoom(current.page)));
}

async function renderProof(url, name) {
  const requestId = ++proofRequest;
  if (!proofMount) return;
  if (!url) {
    proofMount.innerHTML = '<div class="report-editor-proof-empty"><strong>尚无最终版式</strong><small>保存后会自动生成 PDF 并显示在这里。</small></div>';
    setProofState("尚未生成 PDF", "warning");
    return;
  }
  proofMount.innerHTML = '<div class="report-editor-proof-loading"><span></span><small>正在读取最终版式…</small></div>';
  setProofState("正在读取 PDF", "loading");
  try {
    const response = await fetch(url, { method: "HEAD", cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    if (requestId !== proofRequest) return;
    proofMount.innerHTML = `<iframe src="${esc(url)}#toolbar=0&navpanes=0&view=FitH" title="${esc(name || "报告")} 最终 PDF 版式"></iframe>`;
    setProofState(dirty ? "右侧为最近保存版" : "最近保存的 PDF", dirty ? "dirty" : "ready");
  } catch (_error) {
    if (requestId !== proofRequest) return;
    proofMount.innerHTML = '<div class="report-editor-proof-empty"><strong>PDF 暂时无法读取</strong><small>内容仍可编辑，保存时会重新生成。</small></div>';
    setProofState("待重新生成", "warning");
  }
}

function applyZoom(value) {
  const minimum = Number(zoomInput?.min) || 35;
  const maximum = Number(zoomInput?.max) || 150;
  const safeValue = Math.max(minimum, Math.min(maximum, Number(value) || 100));
  if (zoomInput) zoomInput.value = String(safeValue);
  shell?.style.setProperty("--report-editor-zoom", String(safeValue / 100));
  const output = zoomInput?.closest("label")?.querySelector("output");
  if (output) output.textContent = `${safeValue}%`;
}

function preferredZoom(page = {}) {
  const pageWidthPixels = (Number(page.widthIn) || 8.27) * 96;
  const availableWidth = Math.max(240, (editPane?.clientWidth || window.innerWidth) - (window.innerWidth > 760 ? 72 : 24));
  return Math.max(35, Math.min(100, Math.floor((availableWidth / pageWidthPixels) * 20) * 5));
}

async function confirmAction(options) {
  if (window.CMHKDialog?.confirm) return window.CMHKDialog.confirm(options);
  return window.confirm(`${options.title}\n\n${options.message || ""}\n${options.detail || ""}`);
}

async function restoreDraftIfWanted(payload) {
  try {
    const stored = JSON.parse(localStorage.getItem(`cmhk-report-editor-draft:${payload.path}:${payload.sourceSha256}`) || "null");
    if (!stored?.document) return payload.document;
    const restore = await confirmAction({ title: "恢复浏览器草稿？", message: "检测到这份报告有尚未保存的页面编辑草稿。", detail: "恢复后可继续编辑；不恢复会清除该草稿。", confirmLabel: "恢复草稿", cancelLabel: "放弃草稿" });
    if (restore) { dirty = true; return stored.document; }
    localStorage.removeItem(`cmhk-report-editor-draft:${payload.path}:${payload.sourceSha256}`);
  } catch (_error) { /* Ignore malformed or unavailable browser storage. */ }
  return payload.document;
}

async function open(path) {
  if (!shell || !mount || !path) return;
  if (editor && current?.path === path) { shell.hidden = false; return; }
  if (dirty && !(await close())) return;
  shell.hidden = false;
  shell.setAttribute("aria-busy", "true");
  document.body.classList.add("report-editor-open");
  fileName.textContent = "正在打开 Word 报告…";
  setStatus("正在解析文档结构、样式与图片…");
  mount.innerHTML = '<div class="report-editor-loading"><span></span><strong>正在打开全屏编辑器</strong><small>保留原 Word 的页眉、页脚、页面设置与品牌资源</small></div>';
  try {
    const response = await fetch(`/api/report-editor?path=${encodeURIComponent(path)}`, { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    editor?.destroy();
    current = payload;
    dirty = false;
    const content = await restoreDraftIfWanted(payload);
    setProofVisible(window.innerWidth > 760);
    renderProof(payload.previewUrl, payload.name);
    const element = renderPage(payload.page);
    applyZoom(preferredZoom(payload.page));
    editor = new Editor({
      element,
      extensions: editorExtensions(),
      content,
      autofocus: "start",
      editorProps: { attributes: { class: "cmhk-word-editor", role: "textbox", "aria-label": `${payload.name} 正文编辑区`, spellcheck: "true" } },
      onUpdate: () => { dirty = true; setStatus("有未保存修改", "dirty"); setProofState("右侧为最近保存版", "dirty"); updateCounts(); saveDraftSoon(); },
      onSelectionUpdate: updateToolbar,
      onTransaction: updateToolbar,
    });
    fileName.textContent = payload.name;
    fileName.title = payload.path;
    shell.dataset.reportType = payload.reportType || "weekly";
    copyButton.textContent = payload.isEdited ? "另存新编辑稿" : "另存编辑稿";
    saveButton.textContent = payload.isEdited ? "保存" : "保存为编辑稿";
    setStatus(dirty ? "已恢复浏览器草稿，尚未保存到 Word" : "已打开 · 修改后保存为真实 Word 文件", dirty ? "dirty" : "ready");
    updateCounts();
    updateToolbar();
    shell.removeAttribute("aria-busy");
  } catch (error) {
    setStatus(`打开失败：${error.message}`, "error");
    mount.innerHTML = `<div class="report-editor-loading is-error"><strong>无法打开这份报告</strong><small>${esc(error.message)}</small><button type="button" data-report-editor-retry>重新尝试</button></div>`;
    mount.querySelector("[data-report-editor-retry]")?.addEventListener("click", () => open(path));
    shell.removeAttribute("aria-busy");
  }
}

async function save(saveMode = "update") {
  if (!editor || !current || saving) return false;
  saving = true;
  saveButton.disabled = true;
  copyButton.disabled = true;
  setStatus("正在写入 Word、生成新版式预览…", "saving");
  try {
    const response = await fetch("/api/report-editor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: current.path, sourceSha256: current.sourceSha256, saveMode, document: editor.getJSON() }),
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      const error = new Error(payload.error || `HTTP ${response.status}`);
      error.conflict = Boolean(payload.conflict);
      throw error;
    }
    clearDraft();
    current = { ...current, ...payload, name: payload.file?.name || current.name, path: payload.path, isEdited: true, document: editor.getJSON() };
    dirty = false;
    fileName.textContent = current.name;
    fileName.title = current.path;
    saveButton.textContent = "保存";
    copyButton.textContent = "另存新编辑稿";
    setStatus(payload.warning ? `已保存 Word；${payload.warning}` : `已保存 · ${current.name}`, payload.warning ? "warning" : "saved");
    renderProof(payload.previewUrl, current.name);
    window.dispatchEvent(new CustomEvent("cmhk-report-saved", { detail: { ...payload, reportType: payload.file?.reportType || current.reportType } }));
    return true;
  } catch (error) {
    setStatus(`${error.conflict ? "保存冲突" : "保存失败"}：${error.message}`, "error");
    return false;
  } finally {
    saving = false;
    saveButton.disabled = false;
    copyButton.disabled = false;
  }
}

async function close() {
  if (!shell || shell.hidden) return true;
  if (dirty) {
    persistDraft();
    const discard = await confirmAction({ title: "关闭并放弃未保存修改？", message: "当前修改还没有写入 Word 文件。", detail: "浏览器临时草稿会保留，稍后重新打开可恢复。", confirmLabel: "关闭编辑器", cancelLabel: "继续编辑", danger: true });
    if (!discard) return false;
  }
  window.clearTimeout(draftTimer);
  editor?.destroy();
  editor = null;
  current = null;
  proofRequest += 1;
  if (proofMount) proofMount.innerHTML = "";
  dirty = false;
  shell.hidden = true;
  document.body.classList.remove("report-editor-open");
  document.body.classList.remove("has-maximized-report-preview");
  return true;
}

function adjustIndent(delta) {
  if (!editor) return;
  if (editor.isActive("listItem")) {
    (delta > 0 ? editor.chain().focus().sinkListItem("listItem") : editor.chain().focus().liftListItem("listItem")).run();
    return;
  }
  const type = editor.isActive("heading") ? "heading" : "paragraph";
  const currentIndent = Number(editor.getAttributes(type).leftIndent) || 0;
  editor.chain().focus().updateAttributes(type, { leftIndent: Math.max(0, currentIndent + delta) }).run();
}

function showLinkDialog() {
  if (!editor || !linkDialog) return;
  const href = editor.getAttributes("link").href || "";
  linkDialog.querySelector("input").value = href;
  if (typeof linkDialog.showModal === "function") linkDialog.showModal();
  else linkDialog.setAttribute("open", "");
  linkDialog.querySelector("input").focus();
}

function runCommand(name) {
  if (!editor) return;
  const chain = editor.chain().focus();
  const commands = {
    undo: () => chain.undo().run(), redo: () => chain.redo().run(), bold: () => chain.toggleBold().run(), italic: () => chain.toggleItalic().run(), underline: () => chain.toggleUnderline().run(), strike: () => chain.toggleStrike().run(),
    subscript: () => chain.toggleSubscript().run(), superscript: () => chain.toggleSuperscript().run(), bullet: () => chain.toggleBulletList().run(), ordered: () => chain.toggleOrderedList().run(),
    "align-left": () => chain.setTextAlign("left").run(), "align-center": () => chain.setTextAlign("center").run(), "align-right": () => chain.setTextAlign("right").run(), "align-justify": () => chain.setTextAlign("justify").run(),
    indent: () => adjustIndent(18), outdent: () => adjustIndent(-18), link: showLinkDialog, image: () => imageInput.click(), table: () => chain.insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run(),
    "page-break": () => chain.insertPageBreak().run(), "horizontal-rule": () => chain.setHorizontalRule().run(), clear: () => chain.unsetAllMarks().clearNodes().run(),
    "row-after": () => chain.addRowAfter().run(), "column-after": () => chain.addColumnAfter().run(), "delete-row": () => chain.deleteRow().run(), "delete-column": () => chain.deleteColumn().run(), "delete-table": () => chain.deleteTable().run(),
  };
  commands[name]?.();
  updateToolbar();
}

function findNext(query, { replace = "" } = {}) {
  if (!editor || !query) return false;
  const matches = [];
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText) return;
    const haystack = node.text || "";
    let offset = haystack.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
    while (offset >= 0) {
      matches.push({ from: pos + offset, to: pos + offset + query.length });
      offset = haystack.toLocaleLowerCase().indexOf(query.toLocaleLowerCase(), offset + Math.max(1, query.length));
    }
  });
  if (!matches.length) { setStatus(`未找到“${query}”`, "warning"); return false; }
  const next = matches.find((item) => item.from >= editor.state.selection.to) || matches[0];
  let transaction = editor.state.tr.setSelection(TextSelection.create(editor.state.doc, next.from, next.to)).scrollIntoView();
  if (replace !== "") transaction = transaction.insertText(replace, next.from, next.to);
  editor.view.dispatch(transaction);
  editor.view.focus();
  setStatus(replace !== "" ? "已替换 1 处" : `找到 ${matches.length} 处`, "ready");
  return true;
}

function replaceAll(query, replacement) {
  if (!editor || !query) return;
  const matches = [];
  editor.state.doc.descendants((node, pos) => {
    if (!node.isText) return;
    const text = node.text || "";
    let offset = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase());
    while (offset >= 0) { matches.push({ from: pos + offset, to: pos + offset + query.length }); offset = text.toLocaleLowerCase().indexOf(query.toLocaleLowerCase(), offset + Math.max(1, query.length)); }
  });
  let transaction = editor.state.tr;
  matches.reverse().forEach((match) => { transaction = transaction.insertText(replacement, match.from, match.to); });
  if (matches.length) editor.view.dispatch(transaction);
  setStatus(matches.length ? `已替换 ${matches.length} 处` : `未找到“${query}”`, matches.length ? "saved" : "warning");
}

if (ribbon) {
  ribbon.innerHTML = ribbonMarkup();
  ribbon.addEventListener("click", (event) => {
    const command = event.target.closest("[data-editor-command]");
    if (command) runCommand(command.dataset.editorCommand);
    const query = ribbon.querySelector("#reportEditorSearch")?.value || "";
    const replacement = ribbon.querySelector("#reportEditorReplace")?.value || "";
    if (event.target.closest("[data-editor-find]")) findNext(query);
    if (event.target.closest("[data-editor-replace]")) findNext(query, { replace: replacement });
    if (event.target.closest("[data-editor-replace-all]")) replaceAll(query, replacement);
  });
  ribbon.addEventListener("change", (event) => {
    if (!editor) return;
    const select = event.target.closest("[data-editor-select]");
    if (select) {
      const chain = editor.chain().focus();
      if (select.dataset.editorSelect === "block") select.value === "paragraph" ? chain.setParagraph().run() : chain.toggleHeading({ level: Number(select.value.split("-")[1]) }).run();
      if (select.dataset.editorSelect === "font") select.value ? chain.setFontFamily(select.value).run() : chain.unsetFontFamily().run();
      if (select.dataset.editorSelect === "size") select.value ? chain.setFontSize(select.value).run() : chain.unsetFontSize().run();
      if (select.dataset.editorSelect === "line-height") select.value ? chain.setLineHeight(select.value).run() : chain.unsetLineHeight().run();
    }
    const color = event.target.closest("[data-editor-color]");
    if (color?.dataset.editorColor === "text") editor.chain().focus().setColor(color.value).run();
    if (color?.dataset.editorColor === "highlight") editor.chain().focus().toggleHighlight({ color: color.value }).run();
  });
}

saveButton?.addEventListener("click", () => save("update"));
copyButton?.addEventListener("click", () => save("copy"));
closeButton?.addEventListener("click", close);
proofToggle?.addEventListener("click", () => setProofVisible(!workspace?.classList.contains("is-proof-open")));
zoomInput?.addEventListener("input", () => {
  applyZoom(zoomInput.value);
});
imageInput?.addEventListener("change", () => {
  const file = imageInput.files?.[0];
  imageInput.value = "";
  if (!file || !editor) return;
  if (file.size > 8 * 1024 * 1024) { setStatus("图片超过 8 MB，未插入", "error"); return; }
  const reader = new FileReader();
  reader.onload = () => editor.chain().focus().setImage({ src: String(reader.result || ""), alt: file.name }).run();
  reader.readAsDataURL(file);
});
linkDialog?.addEventListener("submit", (event) => {
  event.preventDefault();
  const href = new FormData(linkDialog.querySelector("form")).get("href")?.toString().trim() || "";
  if (!href) editor?.chain().focus().unsetLink().run();
  else editor?.chain().focus().extendMarkRange("link").setLink({ href: /^(https?:|mailto:)/i.test(href) ? href : `https://${href}` }).run();
  linkDialog.close();
});
linkDialog?.querySelector("[data-link-remove]")?.addEventListener("click", () => { editor?.chain().focus().unsetLink().run(); linkDialog.close(); });
linkDialog?.querySelector("[data-link-cancel]")?.addEventListener("click", () => linkDialog.close());

document.addEventListener("keydown", (event) => {
  if (!shell || shell.hidden) return;
  const command = event.metaKey || event.ctrlKey;
  if (command && event.key.toLowerCase() === "s") { event.preventDefault(); event.stopImmediatePropagation(); save(event.shiftKey ? "copy" : "update"); }
  if (command && event.key.toLowerCase() === "f") { event.preventDefault(); event.stopImmediatePropagation(); ribbon?.querySelector("#reportEditorSearch")?.focus(); }
  if (event.key === "Escape" && !linkDialog?.open) { event.preventDefault(); event.stopImmediatePropagation(); close(); }
});

window.CMHKReportEditor = { open, close, save, isOpen: () => Boolean(shell && !shell.hidden), getState: () => ({ path: current?.path || "", dirty, saving }) };
