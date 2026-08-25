(function () {
  "use strict";

  const enhanced = new WeakMap();
  let active = null;
  let serial = 0;

  function selectableOptions(select) {
    return Array.from(select.options).filter((option) => !option.hidden);
  }

  function selectedOption(select) {
    return selectableOptions(select).find((option) => option.selected) || selectableOptions(select)[0] || null;
  }

  function close(entry, restoreFocus = false) {
    if (!entry || entry.list.hidden) return;
    entry.list.hidden = true;
    entry.wrapper.classList.remove("is-open");
    entry.trigger.setAttribute("aria-expanded", "false");
    if (active === entry) active = null;
    if (restoreFocus) entry.trigger.focus({ preventScroll: true });
  }

  function closeActive(restoreFocus = false) {
    close(active, restoreFocus);
  }

  function destroy(select) {
    const entry = enhanced.get(select);
    if (!entry || select.isConnected) return;
    close(entry);
    entry.list.remove();
    enhanced.delete(select);
  }

  function position(entry) {
    const rect = entry.trigger.getBoundingClientRect();
    const gutter = 8;
    const availableBelow = window.innerHeight - rect.bottom - gutter;
    const availableAbove = rect.top - gutter;
    const maxHeight = Math.max(128, Math.min(320, Math.max(availableBelow, availableAbove) - 8));
    const opensAbove = availableBelow < 180 && availableAbove > availableBelow;
    const width = Math.min(Math.max(rect.width, 180), window.innerWidth - gutter * 2);
    const left = Math.min(Math.max(gutter, rect.left), window.innerWidth - width - gutter);

    entry.list.style.width = `${width}px`;
    entry.list.style.maxHeight = `${maxHeight}px`;
    entry.list.style.left = `${left}px`;
    entry.list.style.top = opensAbove ? "auto" : `${Math.min(rect.bottom + 6, window.innerHeight - gutter)}px`;
    entry.list.style.bottom = opensAbove ? `${window.innerHeight - rect.top + 6}px` : "auto";
    entry.list.classList.toggle("opens-above", opensAbove);
  }

  function focusOption(entry, index) {
    const options = Array.from(entry.list.querySelectorAll('[role="option"]:not([aria-disabled="true"])'));
    if (!options.length) return;
    const bounded = Math.max(0, Math.min(index, options.length - 1));
    options[bounded].focus({ preventScroll: true });
    options[bounded].scrollIntoView({ block: "nearest" });
  }

  function choose(entry, option) {
    if (!option || option.disabled || entry.select.disabled) return;
    const changed = entry.select.value !== option.value;
    entry.select.value = option.value;
    sync(entry);
    close(entry, true);
    if (changed) {
      entry.select.dispatchEvent(new Event("input", { bubbles: true }));
      entry.select.dispatchEvent(new Event("change", { bubbles: true }));
    }
  }

  function optionButton(entry, option) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cmhk-select-option";
    button.setAttribute("role", "option");
    button.setAttribute("aria-selected", option.selected ? "true" : "false");
    button.setAttribute("aria-disabled", option.disabled ? "true" : "false");
    button.tabIndex = -1;
    button.dataset.value = option.value;
    button.innerHTML = `<span>${escapeHtml(option.textContent.trim())}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m4.5 10.2 3.2 3.2 7.8-7.8"/></svg>`;
    button.addEventListener("click", () => choose(entry, option));
    button.addEventListener("pointermove", () => {
      if (!option.disabled && document.activeElement !== button) button.focus({ preventScroll: true });
    });
    return button;
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function rebuild(entry) {
    const fragment = document.createDocumentFragment();
    Array.from(entry.select.children).forEach((child) => {
      if (child instanceof HTMLOptGroupElement) {
        const heading = document.createElement("div");
        heading.className = "cmhk-select-group";
        heading.textContent = child.label;
        fragment.appendChild(heading);
        Array.from(child.children).filter((option) => !option.hidden).forEach((option) => fragment.appendChild(optionButton(entry, option)));
      } else if (child instanceof HTMLOptionElement && !child.hidden) {
        fragment.appendChild(optionButton(entry, child));
      }
    });
    entry.list.replaceChildren(fragment);
  }

  function sync(entry) {
    const option = selectedOption(entry.select);
    entry.value.textContent = option ? option.textContent.trim() : "请选择";
    entry.trigger.disabled = entry.select.disabled;
    entry.wrapper.classList.toggle("is-disabled", entry.select.disabled);
    entry.wrapper.classList.toggle("is-placeholder", !option || option.value === "");
    entry.trigger.setAttribute("aria-label", entry.select.getAttribute("aria-label") || option?.textContent.trim() || "选择选项");
    rebuild(entry);
  }

  function open(entry, direction = 0) {
    if (entry.select.disabled) return;
    if (active && active !== entry) close(active);
    sync(entry);
    entry.list.hidden = false;
    entry.wrapper.classList.add("is-open");
    entry.trigger.setAttribute("aria-expanded", "true");
    active = entry;
    position(entry);
    const options = Array.from(entry.list.querySelectorAll('[role="option"]:not([aria-disabled="true"])'));
    const current = options.findIndex((item) => item.getAttribute("aria-selected") === "true");
    const next = direction > 0 ? Math.min(current + 1, options.length - 1) : direction < 0 ? Math.max(current - 1, 0) : Math.max(current, 0);
    window.requestAnimationFrame(() => focusOption(entry, next));
  }

  function onListKeydown(entry, event) {
    const options = Array.from(entry.list.querySelectorAll('[role="option"]:not([aria-disabled="true"])'));
    const index = options.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusOption(entry, index + (event.key === "ArrowDown" ? 1 : -1));
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      focusOption(entry, event.key === "Home" ? 0 : options.length - 1);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      document.activeElement?.click();
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(entry, true);
    } else if (event.key === "Tab") {
      close(entry);
    } else if (event.key.length === 1 && /\S/.test(event.key)) {
      const query = event.key.toLocaleLowerCase();
      const match = options.find((item, itemIndex) => itemIndex > index && item.textContent.trim().toLocaleLowerCase().startsWith(query))
        || options.find((item) => item.textContent.trim().toLocaleLowerCase().startsWith(query));
      if (match) {
        event.preventDefault();
        match.focus({ preventScroll: true });
      }
    }
  }

  function enhance(select) {
    if (enhanced.has(select) || select.multiple || Number(select.size) > 1 || select.classList.contains("sr-only") || select.dataset.customSelect === "native") return;

    const id = `cmhk-select-${++serial}`;
    const wrapper = document.createElement("span");
    wrapper.className = "cmhk-select";
    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "cmhk-select-trigger";
    trigger.setAttribute("role", "combobox");
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.setAttribute("aria-controls", id);
    trigger.innerHTML = '<span class="cmhk-select-value"></span><svg class="cmhk-select-chevron" viewBox="0 0 20 20" aria-hidden="true"><path d="m5.5 7.5 4.5 4.5 4.5-4.5"/></svg>';
    const list = document.createElement("div");
    list.id = id;
    list.className = "cmhk-select-list";
    list.setAttribute("role", "listbox");
    list.hidden = true;

    select.before(wrapper);
    wrapper.append(trigger, select);
    document.body.appendChild(list);
    select.classList.add("cmhk-select-source");
    select.setAttribute("aria-hidden", "true");
    select.tabIndex = -1;

    const entry = { select, wrapper, trigger, value: trigger.querySelector(".cmhk-select-value"), list };
    enhanced.set(select, entry);
    sync(entry);

    trigger.addEventListener("click", () => entry.list.hidden ? open(entry) : close(entry));
    trigger.addEventListener("keydown", (event) => {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) {
        event.preventDefault();
        open(entry, event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0);
      }
    });
    list.addEventListener("keydown", (event) => onListKeydown(entry, event));
    select.addEventListener("focus", () => trigger.focus({ preventScroll: true }));
    select.addEventListener("change", () => sync(entry));
    select.form?.addEventListener("reset", () => window.setTimeout(() => sync(entry)));
    const label = wrapper.closest("label");
    label?.addEventListener("click", (event) => {
      if (event.target === trigger || trigger.contains(event.target) || event.target.closest?.("button, input, textarea, a")) return;
      event.preventDefault();
      entry.list.hidden ? open(entry) : trigger.focus({ preventScroll: true });
    });
  }

  function scan(root) {
    if (root instanceof HTMLSelectElement) enhance(root);
    root.querySelectorAll?.("select").forEach(enhance);
  }

  document.addEventListener("pointerdown", (event) => {
    if (active && !active.wrapper.contains(event.target) && !active.list.contains(event.target)) closeActive();
  }, true);
  document.addEventListener("focusin", (event) => {
    if (active && !active.wrapper.contains(event.target) && !active.list.contains(event.target)) closeActive();
  });
  window.addEventListener("resize", () => active && position(active), { passive: true });
  window.addEventListener("scroll", () => active && position(active), { passive: true, capture: true });

  const observer = new MutationObserver((records) => {
    const touched = new Set();
    records.forEach((record) => {
      if (record.type === "childList") {
        record.addedNodes.forEach((node) => node.nodeType === Node.ELEMENT_NODE && scan(node));
        record.removedNodes.forEach((node) => {
          if (node.nodeType !== Node.ELEMENT_NODE) return;
          if (node instanceof HTMLSelectElement) destroy(node);
          node.querySelectorAll?.("select").forEach(destroy);
        });
        const select = record.target.closest?.("select");
        if (select && enhanced.has(select)) touched.add(select);
      } else if (record.target instanceof HTMLSelectElement && enhanced.has(record.target)) {
        touched.add(record.target);
      } else if (record.target instanceof HTMLOptionElement) {
        const select = record.target.closest("select");
        if (select && enhanced.has(select)) touched.add(select);
      }
    });
    touched.forEach((select) => sync(enhanced.get(select)));
  });

  function start() {
    scan(document);
    observer.observe(document.documentElement, { subtree: true, childList: true, attributes: true, attributeFilter: ["disabled", "selected", "label", "hidden"] });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();

  window.CMHKSelect = {
    refresh(select) {
      const entry = enhanced.get(select);
      if (entry) sync(entry);
      else enhance(select);
    },
  };
})();
