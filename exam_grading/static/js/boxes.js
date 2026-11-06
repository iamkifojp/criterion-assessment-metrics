// Step 2C: draw the name box and each question's boxes on a student's page.
// Boxes snap to whole grid cells (same rule as engine/slicer.snap_rect) and are
// stored as ranges like "page2!A4:J10".
import { post, waitForJob } from "./api.js";
import { t } from "./i18n.js";
import { goTo } from "./main.js";
import { nextSub, openRubrics } from "./step2.js";
import { app, config, criteriaOf, gradedWith, handleError, render } from "./store.js";
import { NAME_COLOR, QUESTION_COLORS, button, coach, confirmBox, debounce, formatTime, h, modal, progressOverlay, toast, isSlide, paperLabel, PAPERS } from "./ui.js";

const GRID = "5mm"; // engine/slicer.DENSITY

// --- Grid maths (mirrors engine/slicer.py) ---------------------------------------------

export function colName(index) {
  let i = Number(index), name = "";
  for (;;) {
    name = String.fromCharCode(65 + (i % 26)) + name;
    i = Math.floor(i / 26) - 1;
    if (i < 0) return name;
  }
}

function colIndex(letters) {
  return [...letters.toUpperCase()].reduce((acc, ch) => acc * 26 + (ch.charCodeAt(0) - 64), 0) - 1;
}

export function parseRange(text) {
  const m = String(text || "").normalize("NFKC").replace(/\s+/g, "")
    .match(/^(?:page(\d+)!)?([A-Za-z]{1,2})(\d{1,3})(?::([A-Za-z]{1,2})(\d{1,3}))?$/i);
  if (!m) return null;
  const c1 = colIndex(m[2]), r1 = Number(m[3]) - 1;
  const c2 = m[4] ? colIndex(m[4]) : c1, r2 = m[5] ? Number(m[5]) - 1 : r1;
  return { page: m[1] ? Number(m[1]) : 1, c1: Math.min(c1, c2), r1: Math.min(r1, r2),
    c2: Math.max(c1, c2), r2: Math.max(r1, r2) };
}

export function formatRange(b) {
  return `page${b.page}!${colName(b.c1)}${b.r1 + 1}:${colName(b.c2)}${b.r2 + 1}`;
}

function snap(page, x0, y0, x1, y1, cols, rows) {
  const clamp = (v) => Math.min(Math.max(v, 0), 1);
  [x0, x1] = [clamp(x0), clamp(x1)].sort((a, b) => a - b);
  [y0, y1] = [clamp(y0), clamp(y1)].sort((a, b) => a - b);
  const eps = 1e-9;
  const c1 = Math.min(Math.floor(x0 * cols), cols - 1);
  const r1 = Math.min(Math.floor(y0 * rows), rows - 1);
  const c2 = Math.min(Math.max(Math.floor(x1 * cols - eps), c1), cols - 1);
  const r2 = Math.min(Math.max(Math.floor(y1 * rows - eps), r1), rows - 1);
  return { page, c1, r1, c2, r2 };
}

// --- Draft of the set-up (saved to the server as you go) -----------------------------------

export function questionDraft() {
  if (!app.draft.questions) {
    const c = config();
    app.draft.questions = {
      name_box: [...(c.name_box || [])],
      name_box_skipped: !!c.name_box_skipped,
      sections: structuredClone(c.sections || []),
      questions: structuredClone(c.questions || []),
      choice_groups: structuredClone(c.choice_groups || []),
    };
    app.draft.page = 1;
    app.draft.paperId = c.students[0]?.id;
    app.draft.addMode = false;
    app.draft.current = initialCurrent(app.draft.questions);
    const adjust = app.draft.adjust;              // opened from grading: "Adjust this box"
    const q = adjust && app.draft.questions.questions.find((x) => x.id === adjust.qid);
    if (q) {
      adjust.original = [...q.boxes];
      app.draft.current = q.id;
      app.draft.paperId = adjust.sid;
      app.draft.page = (q.boxes[0] && parseRange(q.boxes[0])?.page) || 1;
    }
  }
  return app.draft.questions;
}

function initialCurrent(d) {
  if (!d.name_box.length && !d.name_box_skipped) return "name";
  const empty = d.questions.find((q) => !q.boxes.length);
  if (empty) return empty.id;
  if (!d.questions.length) return addQuestion(d).id;
  return d.questions[d.questions.length - 1].id;
}

// A deleted question's grades are kept, so its id is never handed out again:
// a new question would inherit them.
function addQuestion(d) {
  const used = new Set([...d.questions.map((q) => q.id),
    ...Object.values(app.session?.grades?.grades || {}).flatMap((per) => Object.keys(per || {}))]);
  let n = 1;
  while (used.has(`q${n}`)) n++;
  const c = config();
  const number = nextQuestionNumber(d);
  // A question with marks counts towards only the criteria really ticked, so
  // only a teacher who started from Rubric gets the one rubric ticked for them.
  const q = { id: `q${n}`, label: `Q${number}`, boxes: [], max: null,
    rubric_ids: c.mode === "rubric" && (c.rubrics || []).length === 1 ? [c.rubrics[0].id] : [] };
  const at = d.questions.findIndex((x) => autoNumber(x) > number);
  const before = at < 0 ? d.questions[d.questions.length - 1] : d.questions[at - 1];
  if (d.sections.length) q.section_id = before?.section_id || d.sections[0].id;
  if (at < 0) d.questions.push(q);
  else d.questions.splice(at, 0, q);
  return q;
}

// Deleting a question leaves its number free (it is often redrawn), so a new
// question takes the lowest free Qn and goes back in that place.
function nextQuestionNumber(d) {
  const taken = new Set(d.questions.map((q) => q.label));
  let n = 1;
  while (taken.has(`Q${n}`)) n++;
  return n;
}

function autoNumber(q) {
  return /^Q\d+$/.test(q.label) ? Number(q.label.slice(1)) : 0;
}

export const saveQuestions = debounce(async () => {
  const d = app.draft.questions;
  if (!d) return;
  try {
    const data = await post("/api/setup/questions", d);
    app.session = data.session;
    app.saveError = null;
    const status = document.querySelector(".save-status");
    if (status && data.session.saved_at) {
      status.className = "save-status ok";
      status.textContent = t("save.saved_at", { time: formatTime(data.session.saved_at) });
    }
  } catch (err) {
    if (err.saveError) await handleError(err);
    else toast(err.message, "error");
  }
}, 500);

// --- Sections --------------------------------------------------------------------------------
//
// Sections follow the order of the paper. A divider always sits directly above
// a question, so a section is never empty, and with one section left the paper
// goes back to having none.

function tidySections(d) {
  d.sections = d.sections.filter((s) => d.questions.some((q) => q.section_id === s.id));
  if (d.sections.length < 2) {
    d.sections = [];
    d.questions.forEach((q) => { delete q.section_id; });
  }
}

function splitsChoiceGroup(d) {
  const section = new Map(d.questions.map((q) => [q.id, q.section_id]));
  return d.choice_groups.some((g) => new Set(g.questions.map((id) => section.get(id))).size > 1);
}

// Change the sections, or undo the change if it would split a choice group.
function changeSections(d, change) {
  const before = { sections: d.sections, placed: d.questions.map((q) => [q, q.section_id]) };
  change();
  if (splitsChoiceGroup(d)) {
    d.sections = before.sections;
    before.placed.forEach(([q, id]) => { q.section_id = id; });
    toast(t("error.choice_group_across_sections"), "error");
    return;
  }
  tidySections(d);
  saveQuestions();
  render();
}

export function firstInSection(d, q) {
  const i = d.questions.indexOf(q);
  return i === 0 || d.questions[i - 1].section_id !== q.section_id;
}

// A divider above this question: it and the questions after it, up to the next
// divider, become a new section.
export function startSection(d, q) {
  changeSections(d, () => {
    const used = new Set([...d.sections, ...(config().sections || [])].map((s) => s.id));
    const newId = () => {
      let n = 1;
      while (used.has(`sec${n}`)) n++;
      used.add(`sec${n}`);
      return `sec${n}`;
    };
    if (!d.sections.length) {
      d.sections = [{ id: newId(), name: "" }];
      d.questions.forEach((x) => { x.section_id = d.sections[0].id; });
    }
    const section = { id: newId(), name: "" };
    const old = q.section_id;
    d.sections = [...d.sections];
    d.sections.splice(d.sections.findIndex((s) => s.id === old) + 1, 0, section);
    d.questions.slice(d.questions.indexOf(q)).filter((x) => x.section_id === old)
      .forEach((x) => { x.section_id = section.id; });
  });
}

// A divider's questions join the section above. The first section has no
// section above it, so its questions join the one below.
function removeSection(d, section) {
  changeSections(d, () => {
    const i = d.sections.indexOf(section);
    const into = d.sections[i === 0 ? 1 : i - 1];
    d.questions.filter((q) => q.section_id === section.id).forEach((q) => { q.section_id = into.id; });
  });
}

// The heading above a section's questions: its optional name, and a way to remove it.
export function sectionHeading(d, section) {
  const n = d.sections.indexOf(section) + 1;
  return h("div", { class: "section-heading" },
    h("input", { type: "text", id: `section-name-${section.id}`, class: "section-name", value: section.name || "",
      maxlength: "60", placeholder: t("step2.sections.default_name", { n }),
      "aria-label": t("step2.sections.name_label", { n }),
      oninput: (e) => { section.name = e.target.value; saveQuestions(); } }),
    h("button", { type: "button", class: "icon-btn", title: t("step2.sections.remove"),
      "aria-label": t("step2.sections.remove"), onclick: () => removeSection(d, section) }, "✕"));
}

// --- How a question is graded ------------------------------------------------------------------

export function isLocked(q) {
  return (app.session.locked_questions || []).includes(q.id);
}

// What the marks and ticks filled in so far mean (grading_summary.question_mode).
export function gradedText(c, q) {
  const how = gradedWith(c, q);
  if (how === "marks" && criteriaOf(c, q).length) {
    return t("step2.graded.marks_on", { criteria: criteriaOf(c, q).map((r) => r.name).join(", ") });
  }
  return t(`step2.graded.${how || "none"}`);
}

// The marks box. A question with grades can't gain or lose its marks, because
// marks and levels can't be converted. A marks question's number can still be
// corrected; emptying the box puts the number back.
export function marksInput(q, id, attrs, onChange) {
  const locked = isLocked(q);
  return h("input", Object.assign({ type: "number", id, min: "1", max: "100", class: "num", value: q.max ?? "",
    disabled: locked && !q.max,
    oninput: (e) => {
      if (e.target.value === "" && locked) return;
      q.max = e.target.value === "" ? null : parseInt(e.target.value, 10);
      saveQuestions();
      onChange();
    },
    onchange: (e) => { if (e.target.value === "") e.target.value = q.max ?? ""; } }, attrs));
}

export function setTick(c, q, rid, on) {
  const chosen = new Set(criteriaOf(c, q).map((r) => r.id));
  if (on) chosen.add(rid); else chosen.delete(rid);
  q.rubric_ids = (c.rubrics || []).map((r) => r.id).filter((id) => chosen.has(id));
  delete q.rubric_id;
  saveQuestions();
}

export function lockNote(q) {
  return t(q.max ? "step2.locked.marks" : "step2.locked.rubric");
}

// --- Adjusting one box from grading ----------------------------------------------------------

function backToGrading(adjust) {
  goTo(4, { draft: { grading: { qid: adjust.qid, rid: adjust.rid, sid: adjust.sid, ungradedOnly: false,
    zoom: 1, wholePage: false, page: 1 } } });
}

function adjustActions(d, item) {
  const adjust = app.draft.adjust;
  const save = async () => {
    if (!item.boxes.length) { toast(t("step2.boxes.draw_first"), "error"); return; }
    await saveQuestions.now();
    let data;
    try {
      data = await post("/api/slice-question", { question_id: item.id });
    } catch (err) {
      await handleError(err);
      return;
    }
    const overlay = progressOverlay(t("step2.adjust.working", { label: item.label }));
    try {
      const job = await waitForJob(data.job, overlay.update);
      app.session = job.session;
    } catch (err) {
      await handleError(err);
      return;
    } finally {
      overlay.close();
    }
    if (config().sliced) { backToGrading(adjust); return; }
    toast(t("step2.adjust.others"), "error");
    app.draft = { sub: "slice" };
    render();
  };
  const cancel = async () => {
    item.boxes = [...adjust.original];
    await saveQuestions.now();
    if (config().sliced) backToGrading(adjust);
  };
  return h("div", { class: "stack" },
    button(t("step2.adjust.save", { label: item.label || "?" }), save, "primary"),
    button(t("step2.adjust.cancel"), cancel, "ghost"));
}

function itemColor(id) {
  if (id === "name") return NAME_COLOR;
  const i = questionDraft().questions.findIndex((q) => q.id === id);
  return QUESTION_COLORS[Math.max(i, 0) % QUESTION_COLORS.length];
}

function currentItem() {
  const d = questionDraft();
  if (app.draft.current === "name") return { id: "name", label: t("step2.boxes.name_item"), boxes: d.name_box };
  return d.questions.find((q) => q.id === app.draft.current) || null;
}

function overlaps(a, b) {
  return a.page === b.page && a.c1 <= b.c2 && b.c1 <= a.c2 && a.r1 <= b.r2 && b.r1 <= a.r2;
}

// The question a "this is the next one" box should go to: the next question
// without a box, or a new one.
function nextTarget(d, afterId) {
  const start = afterId === "name" ? 0 : d.questions.findIndex((q) => q.id === afterId) + 1;
  return d.questions.slice(start).find((q) => !q.boxes.length) || null;
}

// A box drawn somewhere else entirely, while the current item already has a
// box on this page, usually means the teacher forgot to press "next". Ask.
function askNewOrMove(item, nextLabel) {
  const label = item.id === "name" ? t("step2.boxes.name_short") : item.label;
  return new Promise((resolve) => {
    let answered = false;
    const done = (value) => { answered = true; resolve(value); };
    modal({
      title: t("step2.boxes.new_or_move_title"),
      body: h("p", {}, t("step2.boxes.new_or_move", { label })),
      onClose: () => { if (!answered) resolve(null); },
      actions: [
        { label: t("step2.boxes.move_box", { label }), onClick: () => done("move") },
        { label: t("step2.boxes.is_next", { next: nextLabel }), kind: "primary", onClick: () => done("next") },
      ],
    });
  });
}

async function onBox(range) {
  const d = questionDraft();
  const item = currentItem();
  if (!item) return;
  const boxes = item.id === "name" ? d.name_box : item.boxes;
  const drawn = parseRange(range);
  let idx = -1;
  boxes.forEach((b, i) => { if (parseRange(b).page === drawn.page) idx = i; });

  if (!app.draft.adjust && !app.draft.addMode && idx >= 0 && !overlaps(parseRange(boxes[idx]), drawn)) {
    const target = nextTarget(d, item.id);
    const nextLabel = target ? target.label : `Q${nextQuestionNumber(d)}`;
    const answer = await askNewOrMove(item, nextLabel);
    if (answer === null) { render(); return; }
    if (answer === "next") {
      const q = target || addQuestion(d);
      q.boxes.push(range);
      app.draft.current = q.id;
      if (config().mode === "marks" && !q.max) app.draft.focus = "q-max";
      saveQuestions();
      render();
      return;
    }
  }

  if (app.draft.addMode || idx < 0) boxes.push(range);
  else boxes[idx] = range;
  app.draft.addMode = false;
  if (item.id === "name") d.name_box_skipped = false;
  else if (config().mode === "marks" && !item.max) app.draft.focus = "q-max";
  saveQuestions();
  render();
}

// --- Screen -----------------------------------------------------------------------------

export function renderBoxes() {
  const d = questionDraft();
  const c = config();
  // "All done" drops the empty question being drawn; coming back, pick a real one.
  if (app.draft.adjust) app.draft.current = app.draft.adjust.qid;
  if (!currentItem()) app.draft.current = initialCurrent(d);
  const grid = app.session.grid;
  const student = c.students.find((s) => s.id === app.draft.paperId) || c.students[0];
  const pages = student.pages || 1;
  const page = Math.min(app.draft.page, pages);
  const showLabels = !!app.draft.showLabels;

  const sheet = h("div", { class: "sheet" });
  const img = h("img", { src: `/api/page/${student.id}/${page}?w=1400`, alt: t("common.page_of", { page, pages }),
    draggable: "false" });
  const overlay = h("div", { class: "grid-overlay", style: {
    backgroundSize: `calc(100% / ${grid.cols}) calc(100% / ${grid.rows})` } });
  sheet.append(img, overlay);

  // Existing boxes on this page
  const items = [{ id: "name", label: t("step2.boxes.name_short"), boxes: d.name_box },
    ...d.questions.map((q) => ({ id: q.id, label: q.label || "?", boxes: q.boxes }))];
  for (const item of items) {
    for (const r of item.boxes) {
      const b = parseRange(r);
      if (!b || b.page !== page) continue;
      overlay.append(boxDiv(b, grid, itemColor(item.id), item.id === app.draft.current, item.label,
        () => { app.draft.current = item.id; app.draft.addMode = false; render(); }));
    }
  }
  attachDrag(overlay, page, grid);

  // On the 5 mm grid, name every second (or third) cell so the labels stay readable.
  const colStep = Math.ceil(grid.cols / 30), rowStep = Math.ceil(grid.rows / 30);
  const sheetWrap = showLabels ? h("div", { class: "sheet-labels",
    style: { gridTemplateColumns: "1.6em 1fr", gridTemplateRows: "1.4em 1fr" } },
  h("span", {}),
  h("div", { class: "col-labels" }, Array.from({ length: grid.cols }, (_, i) => h("span", {}, i % colStep ? "" : colName(i)))),
  h("div", { class: "row-labels" }, Array.from({ length: grid.rows }, (_, i) => h("span", {}, i % rowStep ? "" : String(i + 1)))),
  sheet) : sheet;

  const toolbar = h("div", { class: "canvas-toolbar" },
    h("div", { class: "row" },
      button("‹", () => { if (page > 1) { app.draft.page = page - 1; render(); } }, "small", { disabled: page <= 1, "aria-label": t("common.prev_page") }),
      h("strong", {}, t("common.page_of", { page, pages })),
      button("›", () => { if (page < pages) { app.draft.page = page + 1; render(); } }, "small", { disabled: page >= pages, "aria-label": t("common.next_page") })),
    // Sessions made before the 5 mm grid keep their coarser grid until the teacher moves them over.
    c.layout.density !== GRID ? h("div", { class: "row" }, h("span", { class: "muted small" }, t("step2.boxes.old_grid")),
      button(t("step2.boxes.use_new_grid"), () => changeLayout({ density: GRID }), "small")) : null,
    h("div", { class: "row" }, h("span", { class: "muted small" }, t("step1.paper")),
      h("div", { class: "seg" }, PAPERS.map((p) => h("button", { type: "button",
        class: c.layout.paper === p ? "on" : "", onclick: () => changeLayout({ paper: p, landscape: landscapeFor(c, p) }) }, paperLabel(p))))),
    h("label", { class: "check small" }, h("input", { type: "checkbox", checked: showLabels,
      onchange: (e) => { app.draft.showLabels = e.target.checked; render(); } }), t("step2.boxes.show_labels")),
    h("label", { class: "inline small" }, t("step2.boxes.draw_on"),
      h("select", { onchange: (e) => { app.draft.paperId = e.target.value; app.draft.page = 1; render(); } },
        c.students.map((s, i) => h("option", { value: s.id, selected: s.id === student.id ? "selected" : null },
          `${i + 1}. ${s.display_name}`)))));

  const view = h("div", { class: "boxes-layout" },
    h("h1", { class: "sr-only" }, t("step2.sub.boxes")),
    h("div", { class: "canvas-col" }, toolbar, h("div", { class: "sheet-scroll" }, sheetWrap)),
    h("aside", { class: "panel-col" }, sidePanel(d, c, student)));

  if (app.draft.focus) {
    const id = app.draft.focus;
    app.draft.focus = null;
    setTimeout(() => document.getElementById(id)?.focus(), 0);
  }
  return view;
}

function boxDiv(b, grid, color, current, label, onSelect) {
  return h("div", { class: `box ${current ? "current" : ""}`, style: {
    left: `${(b.c1 / grid.cols) * 100}%`, top: `${(b.r1 / grid.rows) * 100}%`,
    width: `${((b.c2 - b.c1 + 1) / grid.cols) * 100}%`, height: `${((b.r2 - b.r1 + 1) / grid.rows) * 100}%`,
    borderColor: color, "--box-color": color } },
  h("button", { type: "button", class: "box-tag", style: { background: color }, onclick: onSelect,
    onpointerdown: (e) => e.stopPropagation() }, label));
}

function attachDrag(overlay, page, grid) {
  let start = null, band = null;
  const frac = (e) => {
    const r = overlay.getBoundingClientRect();
    return [(e.clientX - r.left) / r.width, (e.clientY - r.top) / r.height];
  };
  overlay.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault();
    overlay.setPointerCapture(e.pointerId);
    start = frac(e);
    band = h("div", { class: "box drawing", style: { borderColor: itemColor(app.draft.current) } });
    overlay.append(band);
    move(e);
  });
  const move = (e) => {
    if (!start) return;
    const [x, y] = frac(e);
    const b = snap(page, start[0], start[1], x, y, grid.cols, grid.rows);
    Object.assign(band.style, {
      left: `${(b.c1 / grid.cols) * 100}%`, top: `${(b.r1 / grid.rows) * 100}%`,
      width: `${((b.c2 - b.c1 + 1) / grid.cols) * 100}%`, height: `${((b.r2 - b.r1 + 1) / grid.rows) * 100}%` });
    band.dataset.range = formatRange(b);
  };
  overlay.addEventListener("pointermove", move);
  overlay.addEventListener("pointerup", (e) => {
    if (!start) return;
    move(e);
    const range = band.dataset.range;
    start = null;
    band.remove();
    if (range) onBox(range);
  });
}

// --- Side panel: coach, the current item, the list of questions -----------------------------

// One tick box per criterion: an exam question can be assessed on several.
function criteriaPicker(c, item) {
  if (!(c.rubrics || []).length) {
    return h("p", {}, h("button", { type: "button", class: "link-btn", onclick: () => openRubrics("boxes") },
      t("step2.boxes.add_criteria")));
  }
  const chosen = new Set(criteriaOf(c, item).map((r) => r.id));
  const toggle = (id, on) => { setTick(c, item, id, on); render(); };
  return h("fieldset", { class: "criteria-pick" },
    h("legend", { class: "label" }, t("step2.boxes.which_rubric", { label: item.label || "?" })),
    (c.rubrics || []).map((r) => h("label", { class: "check" },
      h("input", { type: "checkbox", value: r.id, class: "q-tick", checked: chosen.has(r.id),
        onchange: (e) => toggle(r.id, e.target.checked) }), r.name)),
    (c.rubrics || []).length > 1 ? h("p", { class: "muted small" }, t("step2.boxes.which_rubric_hint")) : null);
}

// Both fields on every card. Marks or Rubric only decides which comes first.
function gradingFields(c, item) {
  const note = h("p", { id: "q-graded", class: "muted small" }, gradedText(c, item));
  const marks = h("label", {}, h("span", { class: "label" },
    t(c.mode === "rubric" ? "step2.boxes.marks_optional" : "step2.boxes.how_many_marks", { label: item.label || "?" })),
    marksInput(item, "q-max", { class: "num big-num" }, () => {
      note.textContent = gradedText(c, item);
      // In a one-rubric exam, marks can take away a tick that was only assumed.
      const chosen = new Set(criteriaOf(c, item).map((r) => r.id));
      document.querySelectorAll(".q-tick").forEach((box) => { box.checked = chosen.has(box.value); });
    }));
  const criteria = criteriaPicker(c, item);
  return [c.mode === "rubric" ? criteria : marks, c.mode === "rubric" ? marks : criteria, note,
    isLocked(item) ? h("p", { class: "warn-text small" }, lockNote(item)) : null];
}

function sidePanel(d, c, drawingOn) {
  const item = currentItem();
  const parts = [];
  if (!item) return parts;
  const isName = item.id === "name";

  if (app.draft.adjust) {
    parts.push(coach(t("step2.adjust.coach", { label: item.label || "?" })));
  } else if (isName) {
    parts.push(coach(t("step2.boxes.coach_name")));
  } else if (app.draft.addMode) {
    parts.push(coach(t("step2.boxes.coach_add", { label: item.label || "?" })));
  } else {
    parts.push(coach(t("step2.boxes.coach_question", { label: item.label || "?" }),
      h("ul", { class: "coach-tips" }, ["space", "question", "parts", "overlap"].map((k) => h("li", {}, t(`step2.boxes.tip_${k}`))))));
  }

  const card = h("section", { class: "card item-card", style: { borderColor: itemColor(item.id) } });
  if (isName) {
    card.append(h("h2", {}, t("step2.boxes.name_item")));
  } else {
    card.append(
      h("label", {}, h("span", { class: "label" }, t("step2.boxes.label")),
        h("input", { type: "text", id: "q-label", value: item.label, maxlength: "20",
          oninput: (e) => { item.label = e.target.value; saveQuestions(); } })),
      ...gradingFields(c, item).filter(Boolean));
  }

  const boxes = isName ? d.name_box : item.boxes;
  card.append(h("div", { class: "box-chips" },
    boxes.length ? boxes.map((r, i) => h("span", { class: "chip" }, r,
      h("button", { type: "button", class: "icon-btn", "aria-label": t("step2.boxes.remove_box"), title: t("step2.boxes.remove_box"),
        onclick: () => { boxes.splice(i, 1); saveQuestions(); render(); } }, "✕")))
      : h("span", { class: "muted" }, t("step2.boxes.no_box_yet"))));
  if (boxes.length) {
    card.append(button(t("step2.boxes.add_box"), () => { app.draft.addMode = true; render(); },
      app.draft.addMode ? "small on" : "small"));
  }

  const typed = h("input", { type: "text", class: "small-input", placeholder: "A4:J10", "aria-label": t("step2.boxes.type_range") });
  card.append(h("details", { class: "advanced" }, h("summary", {}, t("step2.boxes.type_range")),
    h("div", { class: "row" }, typed, button(t("common.ok"), () => {
      const b = parseRange(typed.value);
      if (!b) { toast(t("step2.boxes.bad_range"), "error"); return; }
      if (!typed.value.toLowerCase().includes("page")) b.page = app.draft.page;
      if (b.c2 >= app.session.grid.cols || b.r2 >= app.session.grid.rows) { toast(t("step2.boxes.bad_range"), "error"); return; }
      onBox(formatRange(b));
    }, "small"))));

  if (boxes.length) card.append(checkStrip(boxes, c, drawingOn));
  parts.push(card);

  // Buttons that move the coach on
  const actions = h("div", { class: "stack" });
  if (isName) {
    if (boxes.length) actions.append(button(t("step2.boxes.name_done"), () => gotoNextQuestion(d), "primary"));
    else actions.append(button(t("step2.boxes.skip_name"), () => { d.name_box_skipped = true; saveQuestions(); gotoNextQuestion(d); }, "ghost"));
  } else {
    const n = nextQuestionNumber(d);
    const addNext = (newSection) => {
      if (!item.boxes.length) { toast(t("step2.boxes.draw_first"), "error"); return; }
      const q = addQuestion(d);
      app.draft.current = q.id;
      app.draft.addMode = false;
      if (newSection) startSection(d, q);
      saveQuestions();
      render();
    };
    actions.append(
      button(t("step2.boxes.save_and_next", { label: item.label || "?", n }), () => addNext(false), "primary"),
      button(t("step2.boxes.save_and_section", { label: item.label || "?", n }), () => addNext(true)),
      button(t("step2.boxes.all_done"), async () => {
        const ready = d.questions.filter((q) => q.boxes.length);
        if (!ready.length) { toast(t("step2.boxes.draw_first"), "error"); return; }
        // Drop a trailing empty question the teacher never drew.
        d.questions = d.questions.filter((q, i) => q.boxes.length || i < d.questions.length - 1);
        tidySections(d);
        await saveQuestions.now();
        nextSub("boxes");
      }));
  }
  parts.push(app.draft.adjust ? adjustActions(d, item) : actions);
  if (app.draft.adjust) return parts;

  // Everything so far
  parts.push(h("section", { class: "item-list" }, h("h3", {}, t("step2.boxes.so_far")),
    d.questions.length > 1 ? h("p", { class: "muted small" }, t("step2.boxes.order_hint")) : null,
    h("ul", {},
      h("li", {}, itemChip("name", t("step2.boxes.name_short"),
        d.name_box.length ? t("step2.boxes.box_count", { n: d.name_box.length })
          : d.name_box_skipped ? t("step2.boxes.skipped") : t("step2.boxes.no_box_yet"))),
      d.questions.map((q) => [
        d.sections.length && firstInSection(d, q)
          ? h("li", {}, sectionHeading(d, d.sections.find((s) => s.id === q.section_id))) : null,
        h("li", {}, itemChip(q.id, q.label || "?",
          [t("step2.boxes.box_count", { n: q.boxes.length }),
            q.max ? t("step2.boxes.marks_count", { n: q.max }) : criteriaOf(c, q).map((r) => r.name).join(", ")]
            .filter(Boolean).join(" · ")),
        q.id === app.draft.current && d.questions.length > 1 ? moveButtons(d, q) : null,
        q.id === app.draft.current && d.questions.length > 1 ? h("button", { type: "button", class: "icon-btn",
          title: t("step2.boxes.delete_question"), "aria-label": t("step2.boxes.delete_question"),
          onclick: async () => {
            if (!(await confirmBox(t("step2.boxes.delete_question"), t("step2.boxes.delete_confirm", { label: q.label }), t("common.delete"), undefined, true))) return;
            d.questions = d.questions.filter((x) => x.id !== q.id);
            d.choice_groups.forEach((g) => { g.questions = g.questions.filter((x) => x !== q.id); });
            tidySections(d);
            app.draft.current = d.questions[d.questions.length - 1].id;
            saveQuestions();
            render();
          } }, "🗑") : null),
        q.id === app.draft.current && !firstInSection(d, q)
          ? h("li", {}, button(t("step2.sections.start"), () => startSection(d, q), "small ghost")) : null]))));
  return parts;
}

function moveButtons(d, q) {
  const i = d.questions.indexOf(q);
  const arrow = (delta, symbol, key) => h("button", { type: "button", class: "icon-btn move",
    title: t(key), "aria-label": t(key), disabled: !d.questions[i + delta],
    onclick: () => moveQuestion(d, i, delta) }, symbol);
  return [arrow(-1, "↑", "step2.boxes.move_up"), arrow(1, "↓", "step2.boxes.move_down")];
}

// Grading, the review table and reports all follow this order. Labels still
// as CAM2 made them (Q1, Q2…) are renumbered to match; typed labels are kept.
function moveQuestion(d, i, delta) {
  const auto = d.questions.every((q) => /^Q\d+$/.test(q.label));
  const neighbour = d.questions[i + delta];
  if (neighbour?.section_id !== d.questions[i].section_id) {     // the next thing along is a divider
    const q = d.questions[i];
    changeSections(d, () => { q.section_id = neighbour.section_id; });
    return;
  }
  const [q] = d.questions.splice(i, 1);
  d.questions.splice(i + delta, 0, q);
  if (auto) d.questions.forEach((x, n) => { x.label = `Q${n + 1}`; });
  saveQuestions();
  render();
}

function itemChip(id, label, detail) {
  return h("button", { type: "button", class: `item-chip ${id === app.draft.current ? "on" : ""}`,
    onclick: () => { app.draft.current = id; app.draft.addMode = false; render(); } },
  h("span", { class: "dot", style: { background: itemColor(id) } }), h("strong", {}, label),
  h("span", { class: "muted small" }, detail));
}

function gotoNextQuestion(d) {
  const next = d.questions.find((q) => !q.boxes.length) || d.questions[0] || addQuestion(d);
  app.draft.current = next.id;
  app.draft.addMode = false;
  saveQuestions();
  render();
}

function checkStrip(boxes, c, drawingOn) {
  const others = c.students.filter((s) => s.id !== drawingOn.id);
  if (!others.length) return null;
  const pick = [...new Set([others[0], others[Math.floor(others.length / 2)], others[others.length - 1]])];
  const q = encodeURIComponent(boxes.join(","));
  return h("div", { class: "check-strip" }, h("h3", {}, t("step2.boxes.check_title")),
    h("p", { class: "muted small" }, t("step2.boxes.check_hint")),
    pick.map((s) => h("figure", {}, h("img", { src: `/api/preview-crop/${s.id}?boxes=${q}`, alt: s.display_name, loading: "lazy" }),
      h("figcaption", {}, s.display_name))));
}

// Slides are landscape. Coming back from a slide size, go by the page on screen.
function landscapeFor(c, paper) {
  if (isSlide(paper)) return true;
  const page = document.querySelector(".sheet img");
  return isSlide(c.layout.paper) && page ? page.naturalWidth > page.naturalHeight : c.layout.landscape;
}

async function changeLayout(change) {
  const c = config();
  const d = questionDraft();
  const next = Object.assign({}, c.layout, change);
  if (next.paper === c.layout.paper && next.density === c.layout.density) return;
  const anyBoxes = d.name_box.length || d.questions.some((q) => q.boxes.length);
  if (anyBoxes && !(await confirmBox(t("step2.boxes.change_grid"), t("step2.boxes.change_grid_confirm"), t("common.continue")))) return;
  await saveQuestions.flush();
  try {
    const data = await post("/api/setup/layout", next);
    app.session = data.session;
    app.draft.questions = null;
    questionDraft();
    render();
  } catch (err) {
    await handleError(err);
  }
}
