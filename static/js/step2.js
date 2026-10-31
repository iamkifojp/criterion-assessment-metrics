// Step 2: marks or rubric → rubric builder → draw boxes → choice questions → slice.
import { post, upload, waitForJob } from "./api.js";
import { t, language } from "./i18n.js";
import { goTo } from "./main.js";
import { renderBoxes, questionDraft, saveQuestions } from "./boxes.js";
import { act, app, config, criteriaOf, handleError, render } from "./store.js";
import { button, coach, debounce, h, progressOverlay, toast } from "./ui.js";

const SUBSTEPS = ["mode", "rubric", "boxes", "choice", "slice"];

function defaultSub(c) {
  if (!c.mode) return "mode";
  if (c.mode === "rubric" && !(c.rubrics || []).length) return "rubric";
  return "boxes";
}

export function renderStep2() {
  const c = config();
  if (!app.draft.sub) app.draft.sub = defaultSub(c);
  const subs = SUBSTEPS.filter((s) => s !== "rubric" || c.mode === "rubric");
  const tabs = h("nav", { class: "subtabs", "aria-label": t("step2.parts") }, subs.map((s, i) => h("button", {
    type: "button", class: s === app.draft.sub ? "on" : "",
    disabled: s !== "mode" && !c.mode,
    onclick: () => { app.draft.sub = s; render(); },
  }, `${String.fromCharCode(65 + i)}. ${t(`step2.sub.${s}`)}`)));
  const screen = { mode: modeScreen, rubric: rubricScreen, boxes: renderBoxes,
    choice: choiceScreen, slice: sliceScreen }[app.draft.sub]();
  return h("main", { class: `page ${app.draft.sub === "boxes" ? "full" : "wide"}` }, tabs, screen);
}

export function nextSub(after) {
  const c = config();
  const order = SUBSTEPS.filter((s) => s !== "rubric" || c.mode === "rubric");
  app.draft.sub = order[Math.min(order.indexOf(after) + 1, order.length - 1)];
  window.scrollTo(0, 0);
  render();
}

// --- A. Marks or rubric -------------------------------------------------------------

function modeScreen() {
  const c = config();
  const card = (mode, icon) => h("button", {
    type: "button", class: `choice-card tall ${c.mode === mode ? "selected" : ""}`,
    onclick: async () => {
      const data = await act(post("/api/setup/mode", { mode }), { rerender: false });
      if (data) nextSub("mode");
    },
  }, h("span", { class: "choice-icon" }, icon), h("strong", {}, t(`step2.mode.${mode}`)),
  h("span", {}, t(`step2.mode.${mode}_hint`)));
  return h("section", {},
    h("h1", {}, t("step2.mode.title")),
    coach(t("step2.mode.coach")),
    h("div", { class: "choice-row" }, card("marks", "🔢"), card("rubric", "📋")));
}

// --- B. Rubrics -------------------------------------------------------------------------

const DEFAULT_LEVELS = ["0", "1–2", "3–4", "5–6", "7–8"];

function rubricDraft() {
  if (!app.draft.rubrics) {
    const saved = config().rubrics || [];
    app.draft.rubrics = saved.length ? structuredClone(saved).map((r) => ({
      id: r.id, name: r.name, bands: r.bands.map((b) => ({ levels: b.levels, descriptor: b.descriptor })) }))
      : [newRubric(1)];
  }
  return app.draft.rubrics;
}

function newRubric(n) {
  return { id: "", name: language === "ja" ? `基準${String.fromCharCode(64 + n)}` : `Criterion ${String.fromCharCode(64 + n)}`,
    bands: DEFAULT_LEVELS.map((levels) => ({ levels, descriptor: "" })) };
}

const saveRubrics = debounce(async () => {
  const msg = document.getElementById("rubric-error");
  try {
    const data = await post("/api/setup/rubrics", { rubrics: app.draft.rubrics });
    app.session = data.session;
    app.saveError = null;
    // Keep the ids the server assigned so later saves match.
    data.session.config.rubrics.forEach((r, i) => { if (app.draft.rubrics[i]) app.draft.rubrics[i].id = r.id; });
    if (msg) { msg.textContent = ""; msg.hidden = true; }
    const status = document.querySelector(".save-status");
    if (status) status.classList.add("ok");
  } catch (err) {
    if (err.saveError) { await handleError(err); return; }
    if (msg) { msg.textContent = err.message; msg.hidden = false; }
  }
}, 600);

function rubricScreen() {
  const list = rubricDraft();
  const fileInput = h("input", { type: "file", accept: ".xlsx,.csv", hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const data = await upload("/api/setup/rubrics/import", file);
      const empty = list.every((r) => r.bands.every((b) => !b.descriptor.trim()));
      const imported = data.rubrics.map((r) => ({ id: "", name: r.name,
        bands: r.bands.map((b) => ({ levels: b.levels, descriptor: b.descriptor })) }));
      app.draft.rubrics = empty ? imported : list.concat(imported);
      saveRubrics.now();
      toast(t("step2.rubric.imported", { count: imported.length }), "ok");
      render();
    } catch (err) { toast(err.message, "error"); }
    e.target.value = "";
  } });

  const cards = list.map((rubric, ri) => h("section", { class: "card rubric-card" },
    h("div", { class: "row" },
      h("label", { class: "grow" }, h("span", { class: "label" }, t("step2.rubric.name")),
        h("input", { type: "text", id: `rubric-name-${ri}`, value: rubric.name,
          oninput: (e) => { rubric.name = e.target.value; saveRubrics(); } })),
      list.length > 1 ? button(t("step2.rubric.remove"), () => { list.splice(ri, 1); saveRubrics(); render(); }, "small ghost") : null),
    h("table", { class: "bands" },
      h("thead", {}, h("tr", {}, h("th", {}, t("step2.rubric.levels")), h("th", {}, t("step2.rubric.descriptor")), h("th", {}, ""))),
      h("tbody", {}, rubric.bands.map((band, bi) => h("tr", {},
        h("td", { class: "levels" }, h("input", { type: "text", id: `levels-${ri}-${bi}`, value: band.levels,
          "aria-label": t("step2.rubric.levels"), oninput: (e) => { band.levels = e.target.value; saveRubrics(); } })),
        h("td", {}, h("textarea", { rows: "2", id: `desc-${ri}-${bi}`, "aria-label": t("step2.rubric.descriptor"),
          placeholder: t("step2.rubric.descriptor_placeholder"),
          oninput: (e) => { band.descriptor = e.target.value; saveRubrics(); } }, band.descriptor)),
        h("td", {}, h("button", { type: "button", class: "icon-btn", title: t("step2.rubric.remove_row"),
          "aria-label": t("step2.rubric.remove_row"),
          onclick: () => { rubric.bands.splice(bi, 1); saveRubrics(); render(); } }, "✕")))))),
    button(t("step2.rubric.add_row"), () => { rubric.bands.push({ levels: "", descriptor: "" }); render(); }, "small")));

  return h("section", {},
    h("h1", {}, t("step2.rubric.title")),
    coach(t("step2.rubric.coach")),
    h("div", { class: "row toolbar" },
      h("a", { class: "btn", href: `/api/setup/rubrics/template?lang=${language}`, download: "" }, "📥 ", t("step2.rubric.template")),
      button(["📤 ", t("step2.rubric.upload")], () => fileInput.click()), fileInput),
    h("p", { id: "rubric-error", class: "banner warn", hidden: true }),
    cards,
    button(t("step2.rubric.add"), () => { list.push(newRubric(list.length + 1)); saveRubrics(); render(); }),
    h("div", { class: "actions" }, button(t("step2.rubric.done"), async () => {
      await saveRubrics.flush();
      const msg = document.getElementById("rubric-error");
      if (msg && !msg.hidden) return;
      if (!(config().rubrics || []).length) return;
      nextSub("rubric");
    }, "primary big")));
}

// --- D. Choice questions --------------------------------------------------------------

function choiceScreen() {
  const draft = questionDraft();
  const questions = draft.questions;
  if (app.draft.choiceOn === undefined) app.draft.choiceOn = draft.choice_groups.length > 0;
  const save = () => saveQuestions.now();

  const groupsView = draft.choice_groups.map((g, gi) => h("section", { class: "card" },
    h("h3", {}, t("step2.choice.group", { n: gi + 1 })),
    h("p", { class: "muted" }, t("step2.choice.tick")),
    h("div", { class: "tick-list" }, questions.map((q) => {
      const elsewhere = draft.choice_groups.some((o, oi) => oi !== gi && o.questions.includes(q.id));
      return h("label", { class: `check ${elsewhere ? "disabled" : ""}` },
        h("input", { type: "checkbox", checked: g.questions.includes(q.id), disabled: elsewhere,
          onchange: (e) => {
            g.questions = e.target.checked ? [...g.questions, q.id] : g.questions.filter((x) => x !== q.id);
            save(); render();
          } }), q.label || "?");
    })),
    h("label", { class: "inline" }, t("step2.choice.answer_before", { count: g.questions.length }),
      h("input", { type: "number", min: "1", class: "num", value: g.answer || "", id: `group-answer-${gi}`,
        oninput: (e) => {
          g.answer = parseInt(e.target.value, 10) || 0;
          const best = document.getElementById(`group-best-${gi}`);
          if (best) best.textContent = t("step2.choice.pick_best", { n: g.answer || "N" });
          saveQuestions();
        } }),
      t("step2.choice.answer_after")),
    h("div", { class: "row" }, h("span", { class: "label" }, t("step2.choice.pick_label")),
      h("div", { class: "seg" }, [["best", t("step2.choice.pick_best", { n: g.answer || "N" }), `group-best-${gi}`],
        ["teacher", t("step2.choice.pick_teacher"), null]].map(([pick, label, id]) => {
        const on = (g.pick || "best") === pick;
        return h("button", { type: "button", id, class: on ? "on" : "", "aria-pressed": on ? "true" : "false",
          onclick: () => { g.pick = pick; save(); render(); } }, label);
      }))),
    g.pick === "teacher" ? h("p", { class: "muted small" }, t("step2.choice.pick_teacher_hint")) : null,
    button(t("step2.choice.remove"), () => { draft.choice_groups.splice(gi, 1); save(); render(); }, "small ghost")));

  return h("section", {},
    h("h1", {}, t("step2.choice.title")),
    coach(t("step2.choice.coach")),
    h("div", { class: "seg big" },
      h("button", { type: "button", class: app.draft.choiceOn ? "" : "on", onclick: () => {
        app.draft.choiceOn = false; draft.choice_groups = []; save(); render(); } }, t("step2.choice.no")),
      h("button", { type: "button", class: app.draft.choiceOn ? "on" : "", onclick: () => {
        app.draft.choiceOn = true;
        if (!draft.choice_groups.length) draft.choice_groups.push({ id: "g1", questions: [], answer: 1 });
        render(); } }, t("step2.choice.yes"))),
    app.draft.choiceOn ? [groupsView, button(t("step2.choice.add"), () => {
      draft.choice_groups.push({ id: `g${draft.choice_groups.length + 1}`, questions: [], answer: 1 }); render(); })] : null,
    h("div", { class: "actions" }, button(t("common.continue"), async () => {
      await saveQuestions.flush();
      nextSub("choice");
    }, "primary big")));
}

// --- E. Slice -----------------------------------------------------------------------------

function sliceScreen() {
  const c = config();
  const result = app.draft.sliceResult;
  const rubricName = (q) => criteriaOf(c, q).map((r) => r.name).join(", ") || "—";
  const summary = h("table", { class: "summary" },
    h("thead", {}, h("tr", {}, h("th", {}, t("step2.slice.question")), h("th", {}, t("step2.slice.boxes")),
      h("th", {}, c.mode === "rubric" ? t("step2.slice.rubric") : t("step2.slice.marks")))),
    h("tbody", {}, (c.questions || []).map((q) => h("tr", {}, h("td", {}, q.label || "?"),
      h("td", {}, q.boxes.join(", ") || "—"),
      h("td", {}, c.mode === "rubric" ? rubricName(q) : (q.max ?? "—"))))));

  const parts = [h("h1", {}, t("step2.slice.title")),
    coach(t("step2.slice.coach", { questions: (c.questions || []).length, students: c.students.length })),
    h("p", {}, c.name_box?.length ? t("step2.slice.name_box_yes") : t("step2.slice.name_box_no")),
    summary];

  if (result) {
    parts.push(h("div", { class: result.errors.length ? "banner warn" : "banner ok" },
      h("div", {}, h("strong", {}, t("step2.slice.done", { crops: result.crops })),
        result.errors.length ? h("ul", {}, result.errors.slice(0, 20).map((e) =>
          h("li", {}, t("step2.slice.error_line", { name: e.student_name, label: e.label, error: e.error })))) : null)));
  } else if (c.sliced) {
    parts.push(h("div", { class: "banner ok" }, t("step2.slice.already")));
  }
  parts.push(h("div", { class: "actions" },
    button(c.sliced ? t("step2.slice.again") : t("step2.slice.go"), slice, c.sliced ? "" : "primary big"),
    c.sliced ? button(t("step2.slice.continue"), () => goTo(3, { next: true }), "primary big") : null));
  return h("section", {}, parts);
}

async function slice() {
  await saveQuestions.flush();
  let data;
  try {
    data = await post("/api/slice");
  } catch (err) {
    await handleError(err);
    return;
  }
  app.session = data.session;
  const overlay = progressOverlay(t("step2.slice.working"), t("step2.slice.working_note"));
  try {
    const job = await waitForJob(data.job, overlay.update);
    app.session = job.session;
    app.draft.sliceResult = job.result;
  } catch (err) {
    if (err.job?.session) app.session = err.job.session;
    await handleError(err);
  } finally {
    overlay.close();
    render();
  }
}
