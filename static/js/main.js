// App shell: header with step bar and save status, banners, routing between
// the start screen and the five wizard steps, heartbeat.
import { get, post } from "./api.js";
import { loadStrings, t, language } from "./i18n.js";
import { act, app, config, handleError, onRender, render } from "./store.js";
import { button, confirmBox, formatTime, h } from "./ui.js";
import { renderStart, openSession } from "./start.js";
import { renderNewSession, renderScanCheck } from "./step1.js";
import { renderStep2 } from "./step2.js";
import { renderStep3 } from "./step3.js";
import { renderStep4 } from "./step4.js";
import { renderStep5 } from "./step5.js";

const STEPS = [1, 2, 3, 4, 5];
const HEARTBEAT_MS = 60 * 1000;

export function furthestStep() {
  const c = config();
  if (!c) return 1;
  const furthest = Number(c.resume?.step || 1);
  return c.sliced ? Math.max(furthest, 3) : Math.min(furthest, 2);
}

// Step-bar buttons only reach steps already visited; "Continue" buttons pass
// `next` to move one step further (the server still checks the papers are sliced).
export function canGoTo(step) {
  const c = config();
  if (!c || !c.students?.length) return step === 1;
  if (step <= 2) return true;
  if (!c.sliced) return false;
  return step <= Math.max(furthestStep(), 3);
}

export async function goTo(step, { next = false, draft = null } = {}) {
  if (!next && !canGoTo(step)) return;
  const data = await act(post("/api/step", { step }), { rerender: false });
  if (data) {
    app.step = step;
    app.draft = draft || {};
    window.scrollTo(0, 0);
    render();
  }
}

function header() {
  const c = config();
  const right = h("div", { class: "header-right" });
  if (c) {
    const status = app.saveError
      ? h("span", { class: "save-status bad" }, "⚠ ", t("save.not_saved"))
      : app.session.saved_at
        ? h("span", { class: "save-status ok" }, t("save.saved_at", { time: formatTime(app.session.saved_at) }))
        : null;
    right.append(status || "",
      button(t("save.button"), saveNow, "small"),
      button(t("save.close"), closeSession, "small ghost"));
  }
  right.append(languageSwitch());
  if (!c) right.append(button(t("app.quit"), quitApp, "small ghost"));

  const brand = h("div", { class: "brand" }, h("strong", {}, "CAM2"),
    c ? h("span", { class: "exam-name", title: app.session.folder }, c.exam_name) : null);
  const steps = c ? h("nav", { class: "stepbar", "aria-label": t("step.nav") },
    STEPS.map((n) => {
      const reachable = canGoTo(n);
      const cls = ["step", n === app.step ? "current" : "", n < app.step ? "done" : "", reachable ? "" : "locked"].join(" ");
      return h("button", { type: "button", class: cls, disabled: !reachable || n === app.step,
        onclick: () => goTo(n), "aria-current": n === app.step ? "step" : null },
      h("span", { class: "step-num" }, String(n)), h("span", { class: "step-label" }, t(`step.${n}`)));
    })) : null;
  return h("header", { class: "topbar" }, brand, steps, right);
}

function languageSwitch() {
  return h("div", { class: "lang-switch", role: "group", "aria-label": t("app.language") },
    ["en", "ja"].map((lang) => h("button", {
      type: "button", class: lang === language ? "on" : "", "aria-pressed": lang === language ? "true" : "false",
      onclick: async () => {
        if (lang === language) return;
        await post("/api/language", { language: lang });
        await loadStrings();
        render();
      },
    }, lang === "en" ? "English" : "日本語")));
}

function banners() {
  const out = [];
  if (app.saveError) {
    const reopen = app.saveError.code === "save_changed_elsewhere";
    out.push(h("div", { class: "banner danger", role: "alert" },
      h("div", {}, h("strong", {}, t("save.not_saved_title")), h("p", {}, app.saveError.message),
        h("p", { class: "small" }, t("save.not_saved_banner"))),
      reopen ? button(t("save.reopen"), reopenSession, "danger")
        : button(t("save.button"), saveNow, "danger")));
  }
  if (app.lockWarning) {
    out.push(h("div", { class: "banner warn", role: "alert" },
      h("p", {}, t("save.locked_elsewhere", { computer: app.lockWarning.computer, since: formatTime(app.lockWarning.since) }))));
  }
  return out;
}

async function saveNow() {
  const data = await act(post("/api/save"));
  if (data) app.saveError = null;
  render();
}

async function reopenSession() {
  const data = await act(post("/api/session/reopen"), { rerender: false });
  if (data) { app.saveError = null; app.draft = {}; render(); }
}

async function closeSession() {
  try {
    const data = await post("/api/session/close");
    app.session = null;
    app.recent = data.recent;
    app.saveError = null;
    app.view = "start";
    app.draft = {};
    render();
  } catch (err) {
    await handleError(err);
  }
}

async function quitApp() {
  if (!(await confirmBox(t("app.quit"), t("app.quit_confirm"), t("app.quit")))) return;
  await post("/api/quit");
  document.body.replaceChildren(h("main", { class: "page narrow" }, h("h1", {}, t("app.quit_done"))));
}

function body() {
  if (!app.session) return app.view === "new" ? renderNewSession() : renderStart();
  switch (app.step) {
    case 1: return renderScanCheck();
    case 2: return renderStep2();
    case 3: return renderStep3();
    case 4: return renderStep4();
    default: return renderStep5();
  }
}


function draw() {
  const root = document.getElementById("app");
  const scrollY = window.scrollY;
  const focusedId = document.activeElement?.id;
  root.replaceChildren(header(), ...banners(), body());
  if (focusedId) document.getElementById(focusedId)?.focus();
  window.scrollTo(0, scrollY);
}

async function heartbeat() {
  try {
    const data = await post("/api/heartbeat");
    const before = JSON.stringify(app.lockWarning);
    app.lockWarning = data.locked_by || null;
    if (JSON.stringify(app.lockWarning) !== before) render();
  } catch { /* server stopped */ }
}

export function enterWizard() {
  app.view = "wizard";
  const c = config();
  app.step = Math.min(Number(c.resume?.current || c.resume?.step || 1), 5);
  if (app.step >= 3 && !c.sliced) app.step = 2;
  app.draft = {};
}

async function boot() {
  onRender(draw);
  try {
    await loadStrings();
    const state = await get("/api/state");
    app.session = state.session;
    app.recent = state.recent;
    app.version = state.version;
    app.prefs = state.prefs || {};
    if (app.session) enterWizard();
  } catch (err) {
    document.getElementById("app").textContent = err.message;
    return;
  }
  render();
  heartbeat();
  setInterval(heartbeat, HEARTBEAT_MS);
}

export { openSession };
boot();
