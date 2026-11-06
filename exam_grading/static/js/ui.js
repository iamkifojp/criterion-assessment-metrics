// Small DOM helpers: an element builder, modals, toasts and a progress overlay.
import { t, language } from "./i18n.js";

// h("button", {class: "btn", onclick: fn}, "Text", child, ...)
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "value") el.value = value;
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, value);
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(el, child);
    else el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function button(label, onclick, kind = "", extra = {}) {
  return h("button", Object.assign({ type: "button", class: `btn ${kind}`.trim(), onclick }, extra), label);
}

export function coach(text, ...extra) {
  return h("div", { class: "coach", role: "status" }, h("span", { class: "coach-icon" }, "👉"),
    h("div", {}, h("p", {}, text), ...extra));
}

// --- Modals -------------------------------------------------------------------

export function modal({ title, body, actions = [], wide = false, onClose }) {
  const backdrop = h("div", { class: "modal-backdrop" });
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    backdrop.remove();
    document.removeEventListener("keydown", onKey);
    if (onClose) onClose();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const box = h("div", { class: `modal ${wide ? "wide" : ""}`, role: "dialog", "aria-modal": "true" },
    title ? h("h2", {}, title) : null,
    h("div", { class: "modal-body" }, body),
    actions.length ? h("div", { class: "modal-actions" },
      // Run the action first, so onClose can tell an answer from a dismissal.
      actions.map((a) => button(a.label, () => { a.onClick?.(close); if (a.keepOpen !== true) close(); }, a.kind || ""))) : null);
  backdrop.append(box);
  backdrop.addEventListener("click", (e) => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", onKey);
  document.body.append(backdrop);
  const focusable = box.querySelector("input, textarea, .btn.primary");
  if (focusable) focusable.focus();
  return close;
}

export function confirmBox(title, message, okLabel, cancelLabel = t("common.cancel"), danger = false) {
  return new Promise((resolve) => {
    let answered = false;
    modal({
      title, body: h("p", {}, message),
      onClose: () => { if (!answered) resolve(false); },
      actions: [
        { label: cancelLabel, onClick: () => { answered = true; resolve(false); } },
        { label: okLabel, kind: danger ? "danger" : "primary", onClick: () => { answered = true; resolve(true); } },
      ],
    });
  });
}

// --- Toasts and progress ---------------------------------------------------------

export function toast(message, kind = "info") {
  let host = document.querySelector(".toasts");
  if (!host) { host = h("div", { class: "toasts", "aria-live": "polite" }); document.body.append(host); }
  const item = h("div", { class: `toast ${kind}` }, message);
  host.append(item);
  setTimeout(() => item.remove(), kind === "error" ? 9000 : 4000);
}

export function progressOverlay(title, note = "") {
  const bar = h("div", { class: "progress-fill" });
  const count = h("p", { class: "muted" }, "");
  const backdrop = h("div", { class: "modal-backdrop" },
    h("div", { class: "modal progress-modal" }, h("h2", {}, title), note ? h("p", {}, note) : null,
      h("div", { class: "progress" }, bar), count));
  document.body.append(backdrop);
  return {
    update(done, total) {
      if (!total) return;
      bar.style.width = `${Math.round((done / total) * 100)}%`;
      count.textContent = t("common.progress", { done, total });
    },
    close() { backdrop.remove(); },
  };
}

// A message shown while a native Windows/Mac dialog is open (it can open
// behind the browser).
export function pickerWait() {
  const backdrop = h("div", { class: "modal-backdrop" },
    h("div", { class: "modal" }, h("h2", {}, t("pick.waiting_title")), h("p", {}, t("pick.waiting"))));
  document.body.append(backdrop);
  return () => backdrop.remove();
}

// --- Formatting ---------------------------------------------------------------------

export function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const locale = language === "ja" ? "ja-JP" : undefined;
  const time = d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (d.toDateString() === today.toDateString()) return time;
  return `${d.toLocaleDateString(locale, { month: "short", day: "numeric" })} ${time}`;
}

// Run fn after `ms` without further calls. `.flush()` runs a waiting call now
// (and does nothing if none is waiting); `.now(...args)` cancels any wait and
// runs straight away.
export function debounce(fn, ms) {
  let timer = null;
  let pending = null;
  const run = () => { const args = pending; pending = null; return fn(...args); };
  const wrapped = (...args) => { pending = args; clearTimeout(timer); timer = setTimeout(run, ms); };
  wrapped.flush = () => { clearTimeout(timer); return pending ? run() : Promise.resolve(); };
  wrapped.now = (...args) => { clearTimeout(timer); pending = null; return fn(...args); };
  return wrapped;
}

export const QUESTION_COLORS = ["#e4572e", "#17a2b8", "#8e44ad", "#2e8b57", "#d4a017",
  "#c2185b", "#1f6feb", "#6d4c41", "#00897b", "#7b8794"];
export const NAME_COLOR = "#2563eb";

// --- Paper sizes -----------------------------------------------------------------------------

export const PAPERS = ["A4", "B5", "A3", "Slide 16:9", "Slide 4:3"];
export const isSlide = (paper) => paper === "Slide 16:9" || paper === "Slide 4:3";
export const paperLabel = (paper) => (paper === "Slide 16:9" ? t("paper.slide_16_9")
  : paper === "Slide 4:3" ? t("paper.slide_4_3") : paper);

// --- Comment boxes ---------------------------------------------------------------------------

// A comment over its limit is refused, not trimmed, as a browser's maxlength would
// trim pasted text. It stays in the box, unsaved, until it is short enough. The same
// rule is checked on the server (grading_summary), which also counts code points.
const COUNT_FROM = 0.8;           // the counter appears at this share of the limit
const refused = new Map();        // box key -> the refused text, kept across redraws

function typedPart(text, line) {
  return line && text.startsWith(line) ? text.slice(line.length).replace(/^\n+/, "") : text;
}

// saved() gives the comment now saved; save(text) and flush() go to a debounced saver.
// line is the part generated from quick comments, which doesn't count.
export function commentField({ key, limit, saved, line = "", save, flush, attrs = {} }) {
  const length = (text) => [...typedPart(text, line)].length;
  const note = h("p", { class: "comment-note small", "aria-live": "polite" });
  const check = () => {
    const n = length(box.value);
    const over = n > limit && n > length(saved());
    if (over) refused.set(key, typedPart(box.value, line)); else refused.delete(key);
    box.classList.toggle("too-long", over);
    note.classList.toggle("warn-text", over);
    note.textContent = over ? t("comment.too_long", { count: n, limit })
      : n > limit ? t("comment.saved_longer", { count: n, limit })
        : n >= limit * COUNT_FROM ? `${n} / ${limit}` : "";
    return over;
  };
  const box = h("textarea", { ...attrs,
    oninput: () => { if (check()) flush(); else save(box.value); },
    onblur: () => flush() },
  refused.has(key) ? [line, refused.get(key)].filter(Boolean).join("\n") : saved());
  check();
  return [box, note];
}

// True, and says so, if a refused comment needs shortening before leaving this screen.
export function commentRefused() {
  const box = document.querySelector("textarea.too-long");
  if (!box) { refused.clear(); return false; }
  toast(t("comment.shorten_first"), "error");
  box.focus();
  return true;
}
