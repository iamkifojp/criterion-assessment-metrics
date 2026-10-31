// Step 4: grade one question across every paper. In Rubric mode a question
// assessed on several criteria is graded one criterion at a time: each
// (question, criterion) pair is its own item, with tabs to switch criterion.
// Left: the answer (zoomable) with the grade badge, or the whole page.
// Right: the grading card — grade, Not answered, comment, Next paper.
import { post } from "./api.js";
import { t } from "./i18n.js";
import { goTo } from "./main.js";
import { act, app, config, criteriaOf, gradeOf, handleError, render } from "./store.js";
import { button, debounce, formatTime, h } from "./ui.js";
import { parseRange } from "./boxes.js";

const NA = "not_answered";
const MAX_BUTTONS = 15;          // above this, a number box with − / +
const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3];

// --- State helpers ------------------------------------------------------------------

function entry(sid, qid) {
  return app.session.grades.grades?.[sid]?.[qid] || null;
}

// Every item graded across the class, in order: { q, r } (r null in Marks mode).
function items(c) {
  return c.questions.flatMap((q) => (c.mode === "rubric"
    ? criteriaOf(c, q).map((r) => ({ q, r }))
    : [{ q, r: null }]));
}

const itemKey = (qid, rid) => `${qid}|${rid || ""}`;

function itemIndex(c, d) {
  const i = items(c).findIndex((it) => it.q.id === d.qid && (it.r?.id || null) === (d.rid || null));
  return i < 0 ? 0 : i;
}

function itemLabel(it) {
  return it.r && criteriaOf(config(), it.q).length > 1 ? `${it.q.label} · ${it.r.name}` : it.q.label;
}

const valueOf = (sid, qid, rid) => gradeOf(sid, qid, rid);
const isGraded = (sid, qid, rid) => valueOf(sid, qid, rid) !== null;

function draft() {
  const c = config();
  if (!app.draft.grading) {
    const list = items(c);
    const resume = c.resume || {};
    const it = list.find((x) => x.q.id === resume.question_id && (!x.r || !resume.rubric_id || x.r.id === resume.rubric_id))
      || list[0];
    const rid = it.r?.id || null;
    const sids = c.students.map((s) => s.id);
    const anyGraded = sids.some((sid) => list.some((x) => isGraded(sid, x.q.id, x.r?.id)));
    const sid = sids.includes(resume.student_id) ? resume.student_id
      : (sids.find((s) => !isGraded(s, it.q.id, rid)) || sids[0]);
    app.draft.grading = { qid: it.q.id, rid, sid, ungradedOnly: anyGraded, zoom: 1, wholePage: false, page: 1 };
  }
  const d = app.draft.grading;
  // Coming from the review table (no criterion given), or the criteria changed.
  const list = items(c);
  if (!list.some((x) => x.q.id === d.qid && (x.r?.id || null) === (d.rid || null))) {
    const it = list.find((x) => x.q.id === d.qid) || list[0];
    d.qid = it.q.id;
    d.rid = it.r?.id || null;
  }
  return d;
}

const savePosition = debounce((qid, sid, rid) => {
  post("/api/position", { question_id: qid, student_id: sid, rubric_id: rid })
    .then((data) => { app.session = data.session; })
    .catch((err) => handleError(err, true));
}, 800);

// The page a question's first box is on (where "See whole page" opens).
function firstPage(qid) {
  const q = config().questions.find((x) => x.id === qid);
  return (q && parseRange(q.boxes[0])?.page) || 1;
}

// Moving to another paper or question keeps the whole-page view if the
// teacher chose it, opened at the question's page.
function moveTo(changes) {
  const d = draft();
  Object.assign(d, changes);
  d.revealed = null;
  d.page = firstPage(d.qid);
  savePosition(d.qid, d.sid, d.rid);
  render();
}

// Papers shown in the strip and stepped through by ◀ ▶.
function visibleStudents(c, d) {
  if (!d.ungradedOnly) return c.students;
  return c.students.filter((s) => s.id === d.sid || !isGraded(s.id, d.qid, d.rid));
}

function nextStudentId(c, d, step = 1) {
  const list = visibleStudents(c, d);
  const at = list.findIndex((s) => s.id === d.sid);
  if (d.ungradedOnly) {
    // Next ungraded paper after this one, wrapping round.
    for (let i = 1; i < list.length; i++) {
      const s = list[(at + step * i + list.length) % list.length];
      if (!isGraded(s.id, d.qid, d.rid)) return s.id;
    }
    return null;
  }
  const target = at + step;
  return target >= 0 && target < list.length ? list[target].id : null;
}

function levelText(r, value) {
  const max = Math.max(...r.bands.map((b) => b.max));
  const band = r.bands.find((b) => b.min <= value && value <= b.max);
  return band && band.min !== band.max ? `${value} / ${max} · ${band.levels}` : `${value} / ${max}`;
}

// The badge over the answer. A question on several criteria lists each one.
function badgeText(c, q, sid) {
  if (c.mode !== "rubric") {
    const value = valueOf(sid, q.id);
    if (value === null) return null;
    return value === NA ? t("step4.badge_na") : `${value} / ${q.max}`;
  }
  const crit = criteriaOf(c, q);
  const values = crit.map((r) => valueOf(sid, q.id, r.id));
  if (values.every((v) => v === null)) return null;
  if (values.every((v) => v === NA)) return t("step4.badge_na");
  if (crit.length === 1) return levelText(crit[0], values[0]);
  return crit.map((r, i) => `${r.name}: ${values[i] === null ? "—"
    : values[i] === NA ? t("step4.badge_na") : levelText(r, values[i])}`).join("\n");
}

// --- Saving ------------------------------------------------------------------------------

async function setGrade(sid, qid, value, rid = null) {
  const data = await act(post("/api/grade", { student_id: sid, question_id: qid, value, rubric_id: rid }));
  if (data) setTimeout(() => document.getElementById("next-paper")?.focus(), 0);
}

const saveComment = debounce(async (sid, qid, text) => {
  try {
    const data = await post("/api/grade", { student_id: sid, question_id: qid, comment: text });
    app.session = data.session;
    app.saveError = null;
    const status = document.querySelector(".save-status");
    if (status && data.session.saved_at) {
      status.className = "save-status ok";
      status.textContent = t("save.saved_at", { time: formatTime(data.session.saved_at) });
    }
  } catch (err) {
    await handleError(err);
  }
}, 700);

// Hiding names while grading avoids bias; remembered on this computer.
const hideNames = () => !!app.prefs.hide_names;

// With names hidden, one paper's name can be shown on purpose; it hides again
// on the next paper.
function nameOrReveal(d, student) {
  if (!hideNames() || d.revealed === student.id) return h("span", { class: "student-name" }, student.display_name);
  return button(["👁 ", t("step4.show_name")], () => { d.revealed = student.id; render(); }, "small ghost");
}

function setHideNames(on) {
  app.prefs.hide_names = on;
  post("/api/prefs", { hide_names: on }).catch((err) => handleError(err, true));
  render();
}

// --- Screen -------------------------------------------------------------------------------

export function renderStep4() {
  const c = config();
  const d = draft();
  const list = items(c);
  const at = itemIndex(c, d);
  const item = list[at];
  const q = item.q;
  const rid = item.r?.id || null;
  const student = c.students.find((s) => s.id === d.sid) || c.students[0];
  const gradedHere = c.students.filter((s) => isGraded(s.id, q.id, rid)).length;
  const go = (it) => moveTo({ qid: it.q.id, rid: it.r?.id || null, sid: firstFor(c, d, it) });

  const questionBar = h("div", { class: "grade-bar" },
    h("div", { class: "row" },
      button(["◀ ", t("step4.prev_question")], () => go(list[at - 1]), "small", { disabled: at === 0 }),
      h("label", { class: "inline" }, h("span", { class: "sr-only" }, t("step4.question")),
        h("select", { class: "question-select", id: "question-select",
          onchange: (e) => go(list.find((x) => itemKey(x.q.id, x.r?.id) === e.target.value)) },
        list.map((x, i) => h("option", { value: itemKey(x.q.id, x.r?.id), selected: i === at ? "selected" : null },
          t("step4.question_of", { label: itemLabel(x), n: i + 1, total: list.length }))))),
      button([t("step4.next_question"), " ▶"], () => go(list[at + 1]), "small", { disabled: at === list.length - 1 })),
    h("div", { class: "grade-progress" },
      h("span", {}, t("step4.graded_count", { done: gradedHere, total: c.students.length })),
      h("div", { class: "progress small" }, h("div", { class: "progress-fill",
        style: { width: `${(gradedHere / c.students.length) * 100}%` } }))),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.ungradedOnly,
      onchange: (e) => { d.ungradedOnly = e.target.checked; render(); } }), t("step4.ungraded_only")),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: hideNames(),
      onchange: (e) => setHideNames(e.target.checked) }), t("step4.hide_names")),
    d.fromReview
      ? button(t("step4.back_to_review"), () => goTo(5, { next: true }), "primary")
      : button(t("step4.to_review"), () => goTo(5, { next: true }), "ghost"));

  const strip = h("nav", { class: "paper-strip", "aria-label": t("step4.papers") },
    h("span", { class: "strip-label" }, t("step4.papers")),
    c.students.map((s, i) => {
      const hidden = d.ungradedOnly && s.id !== d.sid && isGraded(s.id, q.id, rid);
      if (hidden) return null;
      const v = valueOf(s.id, q.id, rid);
      return h("button", { type: "button", class: `paper-chip ${v !== null ? "graded" : ""} ${s.id === d.sid ? "on" : ""}`,
        title: hideNames() ? null : s.display_name, "aria-current": s.id === d.sid ? "true" : null,
        onclick: () => moveTo({ sid: s.id }) }, String(i + 1));
    }));

  const allDone = d.ungradedOnly && gradedHere === c.students.length;

  return h("main", { class: "page full grading" },
    questionBar,
    strip,
    h("div", { class: "grade-layout" },
      viewer(c, d, item, student),
      h("aside", { class: "grade-card-col" }, allDone ? doneCard(c, item) : gradeCard(c, d, item, student))));
}

// A new question starts from paper 1 (or its first ungraded paper), not from
// the paper you happened to be on.
function firstFor(c, d, it) {
  const first = d.ungradedOnly ? c.students.find((s) => !isGraded(s.id, it.q.id, it.r?.id)) : null;
  return (first || c.students[0]).id;
}

// --- Left: the answer or the whole page -------------------------------------------------------

function viewer(c, d, item, student) {
  const q = item.q;
  const value = valueOf(student.id, q.id, item.r?.id);
  const index = c.students.indexOf(student);
  const stamp = encodeURIComponent(c.sliced_at || "");
  const badge = badgeText(c, q, student.id);

  const prevId = nextStudentId(c, d, -1);
  const nextId = nextStudentId(c, d, 1);
  const head = h("div", { class: "viewer-head" },
    h("div", { class: "row" },
      button(["◀ ", t("step4.prev_paper")], () => moveTo({ sid: prevId }), "small", { disabled: !prevId }),
      h("strong", {}, t("step4.paper_of", { n: index + 1, total: c.students.length })),
      nameOrReveal(d, student),
      button([t("step4.next_paper"), " ▶"], () => moveTo({ sid: nextId }), "small", { disabled: !nextId })),
    h("div", { class: "row" },
      d.wholePage ? null : [
        button("−", () => zoom(d, -1), "small", { "aria-label": t("step4.zoom_out"), title: t("step4.zoom_out") }),
        button(t("step4.fit"), () => { d.zoom = 1; render(); }, "small"),
        button("+", () => zoom(d, 1), "small", { "aria-label": t("step4.zoom_in"), title: t("step4.zoom_in") })],
      d.wholePage
        ? button(t("step4.back_to_answer"), () => { d.wholePage = false; render(); }, "small on")
        : button(["🔍 ", t("grade.see_whole_page")], () => {
          d.wholePage = true;
          d.page = firstPage(q.id);
          render();
        }, "small")));

  let body;
  let pageNav = null;
  if (d.wholePage) {
    const pages = student.pages || 1;
    const boxes = encodeURIComponent(q.boxes.join(","));
    pageNav = h("div", { class: "page-nav" },
      h("div", { class: "row center" },
        button("‹", () => { if (d.page > 1) { d.page--; render(); } }, "small", { disabled: d.page <= 1, "aria-label": t("common.prev_page") }),
        h("span", {}, t("common.page_of", { page: d.page, pages })),
        button("›", () => { if (d.page < pages) { d.page++; render(); } }, "small", { disabled: d.page >= pages, "aria-label": t("common.next_page") })),
      h("p", { class: "muted small center" }, t("step4.whole_page_hint")));
    body = h("div", { class: "whole-page" },
      h("img", { src: `/api/page/${student.id}/${d.page}?w=1400&boxes=${boxes}&v=${stamp}`, alt: t("common.page_of", { page: d.page, pages }) }));
  } else {
    const img = h("img", { src: `/api/crop/${q.id}/${student.id}?v=${stamp}`, alt: t("step4.answer_alt", { label: q.label,
        name: hideNames() ? t("step4.paper_of", { n: index + 1, total: c.students.length }) : student.display_name }),
      draggable: "false", style: { width: `${d.zoom * 100}%` } });
    const scroller = h("div", { class: "answer-scroll" }, img);
    attachZoomAndPan(scroller, d);
    body = scroller;
    if (nextId) new Image().src = `/api/crop/${q.id}/${nextId}?v=${stamp}`;    // preload
  }

  return h("section", { class: `viewer ${value !== null ? "graded" : ""}` }, head, pageNav,
    h("div", { class: "viewer-frame" }, body,
      badge ? h("div", { class: `grade-badge ${badge === t("step4.badge_na") ? "na" : ""} ${badge.includes("\n") ? "multi" : ""}`,
        role: "status" }, badge) : null));
}

function zoom(d, dir) {
  const i = ZOOMS.findIndex((z) => z >= d.zoom);
  d.zoom = ZOOMS[Math.min(Math.max((i < 0 ? ZOOMS.length - 1 : i) + dir, 0), ZOOMS.length - 1)];
  render();
}

// Mouse wheel zooms the answer; dragging moves it around when zoomed in.
function attachZoomAndPan(scroller, d) {
  scroller.addEventListener("wheel", (e) => {
    e.preventDefault();
    const next = Math.min(Math.max(d.zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15), ZOOMS[0]), ZOOMS[ZOOMS.length - 1]);
    d.zoom = Math.round(next * 100) / 100;
    scroller.querySelector("img").style.width = `${d.zoom * 100}%`;
  }, { passive: false });
  let start = null;
  scroller.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    start = { x: e.clientX, y: e.clientY, left: scroller.scrollLeft, top: scroller.scrollTop };
    scroller.setPointerCapture(e.pointerId);
    scroller.classList.add("panning");
  });
  scroller.addEventListener("pointermove", (e) => {
    if (!start) return;
    scroller.scrollLeft = start.left - (e.clientX - start.x);
    scroller.scrollTop = start.top - (e.clientY - start.y);
  });
  const stop = () => { start = null; scroller.classList.remove("panning"); };
  scroller.addEventListener("pointerup", stop);
  scroller.addEventListener("pointercancel", stop);
}

// --- Right: the grading card ----------------------------------------------------------------

function gradeCard(c, d, item, student) {
  const q = item.q;
  const r = item.r;
  const value = valueOf(student.id, q.id, r?.id);
  const comment = entry(student.id, q.id)?.comment || "";
  const choose = (v) => setGrade(student.id, q.id, v, r?.id);
  // Not answered is about the student's answer, so it covers every criterion.
  const notAnswered = () => setGrade(student.id, q.id, NA);
  const clear = () => setGrade(student.id, q.id, null, value === NA ? null : r?.id);
  const crit = c.mode === "rubric" ? criteriaOf(c, q) : [];

  let grading;
  if (c.mode === "rubric") {
    grading = r ? h("div", { class: "bands-grade" },
      crit.length > 1 ? criterionTabs(crit, q, student, r) : h("p", { class: "muted small" }, r.name),
      r.bands.map((band) => {
        const inBand = typeof value === "number" && band.min <= value && value <= band.max;
        const levels = [];
        for (let l = band.min; l <= band.max; l++) levels.push(l);
        return h("div", { class: `band-card ${inBand ? "on" : ""}` },
          h("div", { class: "band-head" }, h("strong", {}, band.levels),
            h("div", { class: "row" }, levels.map((l) => h("button", {
              type: "button", class: `level-btn ${value === l ? "on" : ""}`, "aria-pressed": value === l ? "true" : "false",
              onclick: () => choose(l) }, String(l))))),
          band.descriptor ? h("p", { class: "descriptor" }, band.descriptor) : null);
      })) : h("p", { class: "warn-text" }, t("error.question_has_no_rubric", { question: q.label }));
  } else if ((q.max || 0) <= MAX_BUTTONS) {
    const marks = [];
    for (let m = 0; m <= q.max; m++) marks.push(m);
    grading = h("div", { class: "mark-buttons" }, marks.map((m) => h("button", {
      type: "button", class: `mark-btn ${value === m ? "on" : ""}`, "aria-pressed": value === m ? "true" : "false",
      onclick: () => choose(m) }, String(m))));
  } else {
    const current = typeof value === "number" ? value : "";
    const input = h("input", { type: "number", id: "mark-input", class: "num big-num", min: "0", max: String(q.max),
      value: current, "aria-label": t("step4.marks_out_of", { max: q.max }),
      onchange: (e) => { if (e.target.value !== "") choose(parseInt(e.target.value, 10)); } });
    const bump = (by) => {
      const now = typeof value === "number" ? value : 0;
      choose(Math.min(Math.max(now + by, 0), q.max));
    };
    grading = h("div", { class: "row mark-input" },
      button("−", () => bump(-1), "big", { "aria-label": t("step4.one_less") }), input,
      button("+", () => bump(1), "big", { "aria-label": t("step4.one_more") }),
      h("span", { class: "muted" }, `/ ${q.max}`));
  }

  const commentBox = h("textarea", { id: "comment-box", rows: "3", placeholder: t("grade.comment_placeholder"),
    "aria-label": t("grade.comment_placeholder"),
    oninput: (e) => saveComment(student.id, q.id, e.target.value),
    onblur: () => saveComment.flush() }, comment);

  const nextId = nextStudentId(c, d, 1);
  const outOf = c.mode === "rubric" ? "" : t("step4.out_of", { max: q.max });
  return h("section", { class: `card grade-card ${value !== null ? "graded" : ""}` },
    h("h2", {}, itemLabel(item), outOf ? h("span", { class: "muted" }, " · ", outOf) : null),
    hideNames() && d.revealed !== student.id ? null : h("p", { class: "muted small" }, student.display_name),
    grading,
    h("div", { class: "row" },
      button(t("grade.not_answered"), notAnswered, value === NA ? "small on" : "small", { "aria-pressed": value === NA ? "true" : "false" }),
      value !== null ? button(t("step4.clear"), clear, "small ghost") : null),
    h("label", { class: "comment" }, h("span", { class: "label" }, t("step4.comment")), commentBox),
    nextId
      ? button(t("step4.next_paper_button"), () => { saveComment.flush(); moveTo({ sid: nextId }); },
        "primary big", { id: "next-paper" })
      : lastPaperActions(c, d, item));
}

// Tabs for a question on several criteria; each shows its level on this paper.
function criterionTabs(crit, q, student, current) {
  return h("div", { class: "seg criterion-tabs", role: "tablist", "aria-label": t("step4.criteria") },
    crit.map((x) => {
      const v = valueOf(student.id, q.id, x.id);
      const shown = v === null ? "—" : v === NA ? t("step5.na_short") : String(v);
      return h("button", { type: "button", role: "tab", class: x.id === current.id ? "on" : "",
        "aria-selected": x.id === current.id ? "true" : "false",
        onclick: () => { saveComment.flush(); moveTo({ rid: x.id }); } },
      x.name, h("span", { class: `tab-level ${v === null ? "muted" : ""}` }, shown));
    }));
}

// On the last paper, carry straight on to the next item's first paper.
function lastPaperActions(c, d, item) {
  const list = items(c);
  const next = list[list.findIndex((x) => x.q === item.q && x.r === item.r) + 1];
  return [h("p", { class: "muted" }, t("step4.last_paper")),
    next
      ? button(t("step4.go_to_question", { label: itemLabel(next) }), () => {
        saveComment.flush();
        moveTo({ qid: next.q.id, rid: next.r?.id || null, sid: firstFor(c, d, next) });
      }, "primary big", { id: "next-paper" })
      : button(t("step4.to_review"), () => { saveComment.flush(); goTo(5, { next: true }); }, "primary big", { id: "next-paper" })];
}

function doneCard(c, item) {
  const remaining = items(c).find((x) => c.students.some((s) => !isGraded(s.id, x.q.id, x.r?.id)));
  return h("section", { class: "card grade-card graded" },
    h("h2", {}, "✓ ", t("step4.all_done", { label: itemLabel(item) })),
    remaining
      ? [h("p", {}, t("step4.next_question_hint", { label: itemLabel(remaining) })),
        button(t("step4.go_to_question", { label: itemLabel(remaining) }), () => moveTo({ qid: remaining.q.id,
          rid: remaining.r?.id || null,
          sid: (c.students.find((s) => !isGraded(s.id, remaining.q.id, remaining.r?.id)) || c.students[0]).id }),
        "primary big", { id: "next-paper" })]
      : [h("p", {}, t("step4.everything_done")),
        button(t("step4.to_review"), () => goTo(5, { next: true }), "primary big", { id: "next-paper" })],
    h("p", { class: "muted small" }, t("step4.show_all_hint")));
}
