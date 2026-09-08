/* Report bodies are edited in place, like the R&D report library. */
(() => {
  const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
  let current = null;
  let editing = false;
  let dirty = false;
  let saving = false;
  let request = 0;
  const textOf = node => node.type === 'text' ? node.text || '' : node.type === 'hardBreak' ? '\n' : (node.content || []).map(textOf).join('');
  const blockAt = (doc, path) => path.split('.').reduce((node, index) => node.content[Number(index)], doc);

  function inline(node) {
    if (node.type === 'text') {
      let html = esc(node.text);
      for (const mark of node.marks || []) {
        if (mark.type === 'bold') html = `<strong>${html}</strong>`;
        if (mark.type === 'italic') html = `<em>${html}</em>`;
        if (mark.type === 'underline') html = `<u>${html}</u>`;
        if (mark.type === 'link' && /^(https?:|mailto:)/i.test(mark.attrs?.href || '')) html = `<a href="${esc(mark.attrs.href)}" target="_blank" rel="noopener noreferrer">${html}</a>`;
      }
      return html;
    }
    if (node.type === 'hardBreak') return '<br>';
    if (node.type === 'image' && /^data:image\/(png|jpeg|gif|webp);base64,/i.test(node.attrs?.src || '')) return `<img src="${esc(node.attrs.src)}" alt="${esc(node.attrs.alt || '报告图片')}">`;
    return '';
  }

  function bodyMarkup(doc) {
    const render = (node, path) => {
      if (node.type === 'paragraph' || node.type === 'heading') {
        const text = textOf(node);
        if (!text.trim()) return (node.content || []).map(inline).join('');
        const style = String(node.attrs?.docxStyle || '');
        const tag = /^(Title|标题)$/i.test(style) ? 'h1' : node.type === 'heading' ? `h${Math.min(4, Math.max(2, (Number(node.attrs?.level) || 1) + 1))}` : 'p';
        const editable = editing ? `contenteditable="plaintext-only" role="textbox" aria-label="编辑段落：${esc(text.slice(0,32))}" spellcheck="true"` : '';
        return `<${tag} data-body-block="${path}" ${editable}>${editing ? esc(text) : (node.content || []).map(inline).join('')}</${tag}>`;
      }
      const children = (node.content || []).map((child, i) => render(child, path ? `${path}.${i}` : String(i))).join('');
      const tags = {table:'table',tableRow:'tr',tableCell:'td',tableHeader:'th',bulletList:'ul',orderedList:'ol',listItem:'li',blockquote:'blockquote'};
      const tag = tags[node.type];
      if (!tag) return children || inline(node);
      const span = ['td','th'].includes(tag) ? ` colspan="${Number(node.attrs?.colspan) || 1}" rowspan="${Number(node.attrs?.rowspan) || 1}"` : '';
      return `<${tag}${span}>${children}</${tag}>`;
    };
    return render(doc, '');
  }

  // Preserve unchanged runs and their formatting when a paragraph's text is edited.
  function replaceText(block, next) {
    const old = textOf(block);
    if (old === next) return;
    let a = 0;
    while (a < old.length && a < next.length && old[a] === next[a]) a++;
    let b = old.length, c = next.length;
    while (b > a && c > a && old[b-1] === next[c-1]) { b--; c--; }
    const before = [], after = [];
    let pos = 0, marks;
    for (const node of block.content || []) {
      const text = textOf(node), end = pos + text.length;
      if (!text.length) { (pos < a ? before : after).push(node); continue; }
      if (pos <= a && end >= a) marks = node.marks;
      if (pos < a) before.push(node.type === 'text' ? {...node,text:text.slice(0,a-pos)} : node);
      if (end > b) after.push(node.type === 'text' ? {...node,text:text.slice(Math.max(0,b-pos))} : node);
      pos = end;
    }
    const middle = next.slice(a,c).split('\n').flatMap((text,i) => [...(i ? [{type:'hardBreak'}] : []),...(text ? [{type:'text',text,...(marks ? {marks} : {})}] : [])]);
    block.content = [...before,...middle,...after];
  }

  function render(message = '') {
    if (!current?.host?.isConnected) return;
    const expanded = current.host.querySelector('[data-report-preview]')?.classList.contains('is-maximized');
    const scroll = current.host.querySelector('.simple-report-scroll')?.scrollTop || 0;
    current.host.innerHTML = `<section class="workspace-panel report-preview simple-report-preview ${expanded ? 'is-maximized' : ''}" data-report-preview>
      <header class="report-preview-header"><div><strong title="${esc(current.payload.name)}">${esc(current.payload.name)}</strong><span class="simple-report-state" role="status" aria-live="polite">${esc(message || (editing ? '编辑中' : 'PDF 预览'))}</span></div>
        <div class="report-preview-actions">${editing ? '<button type="button" class="simple-report-action" data-body-cancel>取消</button>' : ''}<button type="button" class="simple-report-action ${editing ? 'primary' : ''}" data-body-toggle>${editing ? '保存正文' : '编辑正文'}</button><button type="button" data-report-preview-expand aria-label="${expanded ? '还原预览' : '放大预览'}" title="${expanded ? '还原预览' : '放大预览'}"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5"/></svg></button></div>
      </header>${editing ? `<div class="simple-report-scroll"><article class="simple-report-paper ${editing ? 'is-editing' : ''}">${bodyMarkup(current.payload.document)}</article></div>` : `<div class="report-preview-viewport">${current.payload.previewUrl ? `<iframe class="report-preview-pdf" src="${esc(current.payload.previewUrl)}#toolbar=0&navpanes=0&view=FitH" title="${esc(current.payload.name)} PDF 预览"></iframe>` : `<div class="simple-report-loading" role="status">${esc(current.payload.warning || '这份报告尚无 PDF 预览，可点击编辑正文。')}</div>`}</div>`}</section>`;
    if (editing) current.host.querySelector('.simple-report-scroll').scrollTop = scroll;
    current.host.querySelector('[data-body-toggle]').addEventListener('click', () => editing ? save() : startEdit());
    current.host.querySelector('[data-body-cancel]')?.addEventListener('click', close);
    current.host.querySelector('.simple-report-paper')?.addEventListener('input', () => {
      dirty = true;
      current.host.querySelector('.simple-report-state').textContent = '未保存';
    });
  }

  function startEdit() {
    if (!current || saving) return;
    editing = true;
    dirty = false;
    render();
    current.host.querySelector('[data-body-block]')?.focus({preventScroll:true});
  }

  async function close() {
    if (saving) return false;
    if (!editing) return true;
    if (dirty) {
      const options = {title:'放弃未保存的修改？',message:'正文还没有保存。',confirmLabel:'放弃修改',cancelLabel:'继续编辑'};
      const confirmed = window.CMHKDialog?.confirm ? await window.CMHKDialog.confirm(options) : window.confirm(options.title);
      if (!confirmed) return false;
    }
    editing = false; dirty = false; render();
    return true;
  }

  async function load(path, host, edit) {
    if (!(await close())) return false;
    const token = ++request;
    host.innerHTML = '<div class="simple-report-loading" role="status">正在读取正文…</div>';
    try {
      const response = await fetch(`/api/report-editor?path=${encodeURIComponent(path)}`, {cache:'no-store'});
      const payload = await response.json();
      if (token !== request) return false;
      if (!response.ok || !payload.ok) throw new Error(payload.error || '正文读取失败');
      current = {host,payload}; editing = edit; dirty = false;
      render();
      return true;
    } catch (error) {
      if (token !== request) return false;
      host.innerHTML = `<div class="simple-report-loading" role="alert">${esc(error.message)}<button type="button">重试</button></div>`;
      host.querySelector('button').addEventListener('click', () => load(path,host,edit));
      return false;
    }
  }

  async function open(path) {
    if (current?.payload.path === path && current.host.isConnected) { startEdit(); return; }
    const kind = path.includes('业绩摘要') ? 'performance' : 'weekly';
    let host = document.querySelector(`#workspaceReportSide-${kind}`);
    if (!host?.getBoundingClientRect().width) {
      if (!(await close())) return;
      document.querySelector(`#workspace-tab-${kind}`)?.click();
      await new Promise(resolve => requestAnimationFrame(resolve));
      host = document.querySelector(`#workspaceReportSide-${kind}`);
    }
    if (host) await load(path,host,true);
  }

  async function save() {
    if (!current || !editing || saving) return false;
    const session = current;
    const documentPayload = structuredClone(session.payload.document);
    session.host.querySelectorAll('[data-body-block]').forEach(element => replaceText(blockAt(documentPayload,element.dataset.bodyBlock),element.innerText.replace(/\r\n/g,'\n')));
    saving = true;
    session.host.querySelectorAll('button').forEach(button => button.disabled = true);
    session.host.querySelectorAll('[contenteditable]').forEach(element => element.contentEditable = 'false');
    const state = session.host.querySelector('.simple-report-state');
    state.textContent = '保存中…';
    try {
      const response = await fetch('/api/report-editor',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:session.payload.path,sourceSha256:session.payload.sourceSha256,bodyOnly:true,saveMode:'update',document:documentPayload})});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error || '保存失败');
      session.payload = {...session.payload,...payload,name:payload.file?.name || session.payload.name,document:documentPayload};
      editing = false; dirty = false;
      window.dispatchEvent(new CustomEvent('cmhk-report-saved',{detail:{...payload,reportType:session.payload.reportType}}));
      render(payload.warning || '正文已保存 · PDF 预览');
      return true;
    } catch (error) {
      state.textContent = `保存失败：${error.message}`;
      session.host.querySelectorAll('[data-body-block]').forEach(element => element.contentEditable = 'plaintext-only');
      return false;
    } finally {
      saving = false;
      session.host.querySelectorAll('button').forEach(button => button.disabled = false);
    }
  }

  document.addEventListener('click',async event => {
    if (!editing && !saving) return;
    if (current?.host.contains(event.target)) return;
    const target = event.target.closest?.('#workspaceTabList [role=tab], .workspace-report-host .file-row, .workspace-report-host button, .workspace-report-host a');
    if (!target) return;
    event.preventDefault();event.stopImmediatePropagation();
    const clicked = event.target.closest('button,a,[role=tab],.file-row') || target;
    if (await close()) clicked.click();
  },true);
  window.addEventListener('beforeunload',event => {if(dirty || saving){event.preventDefault();event.returnValue='';}});
  document.addEventListener('keydown',event => {
    if (!editing) return;
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 's') {event.preventDefault();save();}
    if (event.key === 'Escape') {event.preventDefault();close();}
  });
  window.CMHKReportEditor = {open,preview:(path,host)=>load(path,host,false),save,close,isOpen:()=>editing || saving};
})();
