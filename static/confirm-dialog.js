(() => {
  "use strict";

  let activePromise = null;
  let lastFocused = null;

  const icon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3.5 20 8v8l-8 4.5L4 16V8l8-4.5Z"/><path d="m8.5 12 2.2 2.2 4.8-5"/></svg>';

  function ensureDialog() {
    let dialog = document.getElementById("cmhkConfirmDialog");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "cmhkConfirmDialog";
    dialog.className = "cmhk-confirm-dialog";
    dialog.setAttribute("aria-labelledby", "cmhkConfirmTitle");
    dialog.setAttribute("aria-describedby", "cmhkConfirmMessage");
    dialog.innerHTML = `
      <div class="cmhk-confirm-frame">
        <span class="cmhk-confirm-corner is-top" aria-hidden="true"></span>
        <span class="cmhk-confirm-corner is-bottom" aria-hidden="true"></span>
        <header class="cmhk-confirm-header">
          <span class="cmhk-confirm-icon">${icon}</span>
          <span class="cmhk-confirm-heading">
            <small id="cmhkConfirmKicker">SECURE ACTION</small>
            <strong id="cmhkConfirmTitle">确认操作</strong>
          </span>
          <button class="cmhk-confirm-close" type="button" data-dialog-result="false" aria-label="关闭确认弹窗">×</button>
        </header>
        <div class="cmhk-confirm-body">
          <p id="cmhkConfirmMessage"></p>
          <p id="cmhkConfirmDetail" class="cmhk-confirm-detail" hidden></p>
        </div>
        <footer class="cmhk-confirm-actions">
          <button class="cmhk-confirm-button is-secondary" type="button" data-dialog-result="false">取消</button>
          <button class="cmhk-confirm-button is-primary" type="button" data-dialog-result="true">确认</button>
        </footer>
      </div>`;
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      settle(dialog, false);
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      settle(dialog, false);
    });
    document.body.append(dialog);
    return dialog;
  }

  function settle(dialog, value) {
    if (!activePromise) return;
    const resolve = activePromise;
    activePromise = null;
    dialog.classList.add("is-closing");
    window.setTimeout(() => {
      dialog.classList.remove("is-closing");
      if (dialog.open) dialog.close();
      lastFocused?.focus?.({ preventScroll: true });
      lastFocused = null;
      resolve(value);
    }, window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 150);
  }

  function open(options = {}) {
    const dialog = ensureDialog();
    if (activePromise) return Promise.resolve(false);
    const alertMode = options.mode === "alert";
    const tone = options.tone === "danger" ? "danger" : options.tone === "success" ? "success" : "signal";
    dialog.dataset.tone = tone;
    dialog.dataset.mode = alertMode ? "alert" : "confirm";
    dialog.querySelector("#cmhkConfirmKicker").textContent = options.kicker || (tone === "danger" ? "RISK CONTROL" : alertMode ? "SYSTEM NOTICE" : "SECURE ACTION");
    dialog.querySelector("#cmhkConfirmTitle").textContent = options.title || (alertMode ? "操作提示" : "确认操作");
    dialog.querySelector("#cmhkConfirmMessage").textContent = options.message || "是否继续执行当前操作？";
    const detail = dialog.querySelector("#cmhkConfirmDetail");
    detail.textContent = options.detail || "";
    detail.hidden = !options.detail;
    const cancel = dialog.querySelector('.cmhk-confirm-button[data-dialog-result="false"]');
    const confirm = dialog.querySelector('.cmhk-confirm-button[data-dialog-result="true"]');
    cancel.hidden = alertMode;
    cancel.textContent = options.cancelLabel || "取消";
    confirm.textContent = options.confirmLabel || (alertMode ? "知道了" : "确认执行");
    lastFocused = document.activeElement;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
    window.requestAnimationFrame(() => confirm.focus());
    return new Promise((resolve) => { activePromise = resolve; });
  }

  document.addEventListener("click", (event) => {
    const dialog = event.target.closest?.("#cmhkConfirmDialog");
    if (!dialog) return;
    const action = event.target.closest?.("[data-dialog-result]");
    if (action) {
      settle(dialog, action.dataset.dialogResult === "true");
      return;
    }
    if (event.target === dialog) {
      const bounds = dialog.getBoundingClientRect();
      const inside = event.clientX >= bounds.left && event.clientX <= bounds.right && event.clientY >= bounds.top && event.clientY <= bounds.bottom;
      if (!inside) settle(dialog, false);
    }
  });

  window.CMHKDialog = {
    confirm: (options) => open({ ...options, mode: "confirm" }),
    alert: (options) => open({ ...(typeof options === "string" ? { message: options } : options), mode: "alert" }),
  };
})();
