// Step 5: check every student's results, adjust what goes on the report,
// write overall comments, then make the student PDFs and the Excel gradebook.
import { post, waitForJob } from "./api.js";
import { t, language } from "./i18n.js";
import { goTo } from "./main.js";
import { openAddPapers } from "./step1.js";
import { act, app, config, criteriaOf, gradeOf, gradedWith, handleError, render, usedCriteria } from "./store.js";
import { button, coach, commentField, confirmBox, debounce, formatTime, h, modal, progressOverlay, toast } from "./ui.js";

const NA = "not_answered";

function exportDraft() {
  if (!app.draft.export) app.draft.export = { language, result: null };
  return app.draft.export;
}

// Jump to Step 4 on one paper, question and criterion; Step 4 offers "Back to review".
function gradeThis(qid, sid, rid = null) {
  goTo(4, { draft: { grading: { qid, rid, sid, ungradedOnly: false, zoom: 1, wholePage: false, page: 1, fromReview: true } } });
}

// One column per grade: one for a marks question, and one per criterion on a
// rubric question. The key matches grading_summary.slot_key.
function columns(c) {
  return c.questions.flatMap((q) => {
    if (gradedWith(c, q) === "marks") return [{ q, r: null, key: q.id, multi: false }];
    const crit = criteriaOf(c, q);
    return crit.map((r) => ({ q, r, key: `${q.id}/${r.id}`, multi: crit.length > 1 }));
  });
}

const saveComment = debounce(async (sid, text) => {
  try {
    const data = await post("/api/overall", { student_id: sid, comment: text });
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

function valueText(c, q, value) {
  if (value === null || value === undefined) return "";
  if (value === NA) return t("step5.na_short");
  return String(value);
}

const oneDecimal = (n) => (n === null || n === undefined ? "—" : n.toFixed(1));

function sectionName(c, sid) {
  const i = (c.sections || []).findIndex((s) => s.id === sid);
  return c.sections?.[i]?.name || t("step2.sections.default_name", { n: i + 1 });
}

// A grade with its criterion: B5 when the name ends in one letter (Criterion B,
// 基準B), otherwise the name in full (Knowledge 5).
function gradeShort(r, value) {
  const letter = r.name.trim().match(/(?:^|[^A-Za-z])([A-Za-z])$/)?.[1];
  const shown = value === NA ? t("step5.na_short") : value;
  return letter && value !== NA ? `${letter}${shown}` : `${letter || r.name} ${shown}`;
}

// One criterion's results on one paper: its marks total, and the grades as given.
function criterionResults(r, rr, weighted) {
  const lines = [];
  if (rr.marks) {
    lines.push(weighted ? t("step5.marks_percent", { percent: oneDecimal(rr.marks.percent) })
      : t("step5.marks_total", { total: rr.marks.total, max: rr.marks.max, percent: oneDecimal(rr.marks.percent) }));
  }
  if (rr.grades.length) {
    lines.push(t("step5.grades_list", { grades: rr.grades.map((g) => gradeShort(r, g.level)).join(", ") }));
  }
  return lines.map((line) => h("div", {}, line));
}

function groupName(c, gid) {
  return t("step2.choice.group", { n: (c.choice_groups || []).findIndex((g) => g.id === gid) + 1 });
}

// "Teacher picks" choice groups this student answered too many of: one
// button each, amber until the teacher has chosen which answers count.
function choiceButtons(c, s, res) {
  const labelOf = new Map(c.questions.map((q) => [q.id, q.label]));
  return Object.entries(res.choices || {}).map(([gid, ch]) => {
    const group = groupName(c, gid);
    const label = ch.pending ? t("step5.choice_pending", { group })
      : `${t("step5.choice_chosen", { group, questions: ch.chosen.map((qid) => labelOf.get(qid)).join(", ") })} ✎`;
    return h("div", {}, button(label, () => chooseAnswers(c, s, gid, ch), `small ${ch.pending ? "warn" : "ghost"}`));
  });
}

function chooseAnswers(c, s, gid, ch) {
  const g = c.choice_groups.find((x) => x.id === gid);
  const picked = new Set(ch.chosen);
  const boxes = [];
  const sync = () => boxes.forEach(({ input, qid }) => { input.disabled = picked.size >= g.answer && !picked.has(qid); });
  const shown = (q) => (gradedWith(c, q) === "marks"
    ? `${valueText(c, q, gradeOf(s.id, q.id))} / ${q.max}`
    : criteriaOf(c, q).map((r) => `${r.name} ${valueText(c, q, gradeOf(s.id, q.id, r.id))}`).join(", "));
  const list = ch.answered.map((qid) => {
    const q = c.questions.find((x) => x.id === qid);
    const input = h("input", { type: "checkbox", checked: picked.has(qid), onchange: (e) => {
      if (e.target.checked) picked.add(qid); else picked.delete(qid);
      sync();
    } });
    boxes.push({ input, qid });
    return h("label", { class: "check" }, input, `${q.label} · ${shown(q)}`);
  });
  sync();
  modal({
    title: t("step5.choose_title", { group: groupName(c, gid), name: s.display_name }),
    body: h("div", {}, h("p", {}, t("step5.choose_hint", { answered: ch.answered.length, answer: g.answer })),
      h("div", { class: "tick-list" }, list)),
    actions: [
      { label: t("common.cancel") },
      { label: t("common.save"), kind: "primary",
        onClick: () => act(post("/api/choice", { student_id: s.id, group_id: gid, questions: [...picked] })) },
    ],
  });
}

export function renderStep5() {
  const c = config();
  const summary = app.session.summary;
  const grades = app.session.grades.grades || {};
  const byId = new Map(summary.students.map((s) => [s.student_id, s]));
  const inGroup = new Set((c.choice_groups || []).flatMap((g) => g.questions));
  const incomplete = summary.students.filter((s) => !s.complete).length;
  const ungraded = summary.students.filter((s) => s.ungraded.length).length;
  const pending = summary.students.filter((s) => (s.pending || []).length).length;
  const hasMarks = c.questions.some((q) => gradedWith(c, q) === "marks");
  const hasLevels = c.questions.some((q) => gradedWith(c, q) === "rubric");
  const used = usedCriteria(c);
  const criteria = c.report_options.overall_criteria ? used : [];
  const sharing = (c.sections || []).filter((s) => s.weight !== null && s.weight !== undefined);
  const sectionCols = sharing.length >= 2 ? sharing : [];
  const weighted = !!c.weighted && sharing.length >= 2;
  const anyComment = Object.values(grades).some((per) => Object.values(per || {}).some((e) => (e?.comment || "").trim()));
  const cols = columns(c);

  // What the teacher decides comes first, beside the name; each question's grade
  // is at the far end. The head, the rows and the class statistics share this order.
  const head = h("tr", {},
    h("th", {}, "#"), h("th", { class: "sticky-col" }, t("step5.student")),
    hasMarks ? [h("th", { class: "num-col" }, t("step5.calculated")),
      h("th", { class: "num-col" }, t(weighted ? "step5.on_report_percent" : "step5.on_report"))] : null,
    criteria.map((r) => [h("th", {}, r.name), h("th", { class: "num-col" }, t("step5.final", { name: r.name }))]),
    h("th", {}, t("step5.overall_comment")),
    sectionCols.map((sec) => h("th", { class: "num-col" }, sectionName(c, sec.id))),
    cols.map(({ q, r, multi }) => h("th", { class: "num-col" }, q.label,
      r ? h("div", { class: "muted small" }, multi || used.length > 1 ? r.name : "")
        : h("span", { class: "muted small" }, ` /${q.max}`))));

  const rows = c.students.map((s, i) => {
    const res = byId.get(s.id);
    const waiting = new Set((c.choice_groups || []).filter((g) => (res.pending || []).includes(g.id))
      .flatMap((g) => g.questions));
    const cells = cols.map(({ q, r, multi }) => {
      const value = gradeOf(s.id, q.id, r?.id);
      const note = (grades[s.id]?.[q.id]?.comment || "").trim();
      const notCounted = inGroup.has(q.id) && !waiting.has(q.id) && value !== null && !(q.id in res.counted);
      const cls = ["num-col", "grade-cell", value === null ? "missing" : "", notCounted ? "not-counted" : "",
        note ? "has-comment" : ""].join(" ");
      const action = value === null ? t("step5.click_to_grade") : t("step5.click_to_change");
      const label = multi ? `${q.label} · ${r.name}` : q.label;
      return h("td", { class: cls },
        h("button", { type: "button", onclick: () => gradeThis(q.id, s.id, r?.id),
          title: note ? `💬 ${note}

${action}` : action,
          "aria-label": `${label} · ${s.display_name}: ${value === null ? t("report.not_graded") : valueText(c, q, value)}${note ? ` · ${note}` : ""}` },
        value === null ? "?" : valueText(c, q, value)));
    });
    const sectionCells = sectionCols.map((sec) => {
      const row = res.sections.find((x) => x.id === sec.id);
      return h("td", { class: "num-col muted" }, `${row.total} / ${row.max}`,
        h("div", { class: "small" }, `${oneDecimal(row.percent)}%`),
        weighted ? h("div", { class: "small" }, `${oneDecimal(row.weighted_marks)} / ${row.share}`) : null);
    });
    // With weighting on, a total out of the paper's marks would not agree with
    // the percentage, so only the percentage is shown.
    const total = !hasMarks ? null : [
      h("td", { class: "num-col muted" }, weighted ? `${oneDecimal(res.marks.percent)}%`
        : [`${res.marks.total} / ${res.marks.max}`,
          h("div", { class: "small" }, `${oneDecimal(res.marks.percent)}%`)]),
      h("td", { class: `num-col ${res.marks.adjusted ? "adjusted" : ""}` }, weighted
        ? overrideInput(`percent-${s.id}`, res.marks.report_percent, res.marks.percent, 100,
          (v) => ({ student_id: s.id, report_percent: v }), res.marks.adjusted, t("step5.on_report_percent"))
        : overrideInput(`total-${s.id}`, res.marks.report_total, res.marks.total, res.marks.max,
          (v) => ({ student_id: s.id, report_total: v }), res.marks.adjusted, t("step5.on_report")))];
    const criterionCells = criteria.map((r) => {
      const rr = res.rubrics[r.id];
      const top = Math.max(...r.bands.map((b) => b.max));
      return [h("td", { class: "criterion-cell small" }, criterionResults(r, rr, weighted)),
        h("td", { class: "num-col" }, overrideInput(`final-${s.id}-${r.id}`, rr.final, null, top,
          (v) => ({ student_id: s.id, final_levels: { [r.id]: v } }), false, t("step5.final", { name: r.name })))];
    });
    const comment = commentField({ key: `overall/${s.id}`, limit: app.session.comment_limits.overall,
      saved: () => app.session.grades.overall?.[s.id]?.comment || "",
      save: (text) => saveComment(s.id, text), flush: saveComment.flush,
      attrs: { id: `overall-${s.id}`, rows: "2", class: "overall-comment",
        placeholder: t("step5.comment_placeholder"), "aria-label": t("step5.overall_comment") } });
    return h("tr", { class: res.complete ? "" : "incomplete" },
      h("td", { class: "num-cell" }, String(i + 1)),
      h("td", { class: "sticky-col" }, h("strong", {}, s.display_name), choiceButtons(c, s, res)),
      total, criterionCells, h("td", {}, comment), sectionCells, cells);
  });

  const stat = (key) => {
    const label = { average: t("xlsx.average"), max: t("xlsx.max_row"), min: t("xlsx.min_row") }[key];
    const qCells = cols.map((col) => h("td", { class: "num-col" }, summary.questions[col.key]?.[key] ?? ""));
    const sectionStats = sectionCols.map((sec) => h("td", { class: "num-col" }, summary.sections[sec.id]?.[key] ?? ""));
    const totalStats = hasMarks
      ? [h("td", { class: "num-col" }, summary.overall[weighted ? "percent" : "total"]?.[key] ?? ""), h("td", {})] : null;
    const finalStats = criteria.map((r) => [h("td", {}), h("td", { class: "num-col" }, summary.overall[r.id]?.[key] ?? "")]);
    return h("tr", { class: "stat-row" }, h("td", {}), h("td", { class: "sticky-col" }, label),
      totalStats, finalStats, h("td", {}), sectionStats, qCells);
  };

  return h("main", { class: "page full review" },
    h("h1", {}, t("step5.title")),
    coach(t(hasMarks && hasLevels ? "step5.coach_mixed" : hasMarks ? "step5.coach_marks" : "step5.coach_rubric")),
    resultsPanel(c, used, sharing, weighted),
    ungraded ? h("div", { class: "banner warn" }, h("p", {}, t("step5.incomplete", { n: ungraded }))) : null,
    pending ? h("div", { class: "banner warn" }, h("p", {}, t("step5.pending", { n: pending }))) : null,
    anyComment ? h("p", { class: "muted small" }, h("span", { class: "comment-dot" }), t("step5.comment_legend")) : null,
    h("div", { class: "table-scroll review-scroll" },
      h("table", { class: "review-table" }, h("thead", {}, head),
        h("tbody", {}, rows), h("tfoot", {}, stat("average"), stat("max"), stat("min")))),
    c.host ? hostPanel(c, incomplete) : null,
    exportPanel(c, incomplete, used, hasMarks));
}

// --- How results are worked out --------------------------------------------------------------

function resultsPanel(c, used, sharing, weighted) {
  if (!used.length && sharing.length < 2) return null;
  const tick = (checked, label, hint, onchange) => h("div", {},
    h("label", { class: "check" }, h("input", { type: "checkbox", checked, onchange }), label),
    h("p", { class: "muted small tick-hint" }, hint));
  const shareRow = (s) => h("label", { class: "inline share-row" },
    h("span", { class: "share-name" }, sectionName(c, s.id)),
    h("input", { type: "number", id: `share-${s.id}`, class: "num", min: "0", max: "100", value: s.weight,
      onchange: (e) => keepingPlace(post("/api/section-weight", { section_id: s.id, value: e.target.value.trim() })) }),
    "%",
    s.weight_typed ? h("button", { type: "button", class: "icon-btn", title: t("step5.share_auto"), "aria-label": t("step5.share_auto"),
      onclick: () => keepingPlace(post("/api/section-weight", { section_id: s.id, value: null })) }, "↺")
      : h("span", { class: "muted small" }, t("step5.share_automatic")));
  return h("section", { class: "card results-card" },
    used.length ? tick(c.report_options.overall_criteria, t("step5.option.overall_criteria"), t("step5.option.overall_criteria_hint"),
      (e) => act(post("/api/report-options", { overall_criteria: e.target.checked }))) : null,
    sharing.length >= 2 ? tick(!!c.weighted, t("step5.weighting"), t("step5.weighting_hint"),
      (e) => act(post("/api/weighting", { on: e.target.checked }))) : null,
    weighted ? h("div", { class: "shares" }, sharing.map(shareRow),
      h("p", { class: "muted small" }, t("step5.shares_note"))) : null);
}

// Save and redraw without losing the teacher's place, so a column of final
// levels can be typed in one go with the Tab key.
async function keepingPlace(promise) {
  const data = await act(promise, { rerender: false });
  const focused = document.activeElement?.id;
  const left = document.querySelector(".review-scroll")?.scrollLeft;
  render();
  if (focused) document.getElementById(focused)?.focus();
  const table = document.querySelector(".review-scroll");
  if (table && left !== undefined) table.scrollLeft = left;
  return data;
}

// Opened from CAM: CAM reads the results only once the teacher sends them.
function hostPanel(c, incomplete) {
  const sent = c.host_ready_at;
  const send = async () => {
    if (incomplete && !(await confirmBox(t("host.send_incomplete_title"),
      t("host.send_incomplete", { n: incomplete, host: c.host.name }), t("host.send_anyway")))) return;
    act(post("/api/host/ready", { ready: true }));
  };
  return h("section", { class: `card ${sent ? "" : "accent"}` },
    h("h2", {}, t("host.send_title", { host: c.host.name })),
    sent
      ? [h("p", { class: "ok-text" }, t("host.sent", { time: formatTime(sent), host: c.host.name })),
        h("div", { class: "actions left" },
          button(t("host.send_again"), send),
          button(t("host.unsend"), () => act(post("/api/host/ready", { ready: false })), "ghost"))]
      : [h("p", { class: "muted" }, t("host.send_hint", { host: c.host.name })),
        h("div", { class: "actions left" }, button(t("host.send", { host: c.host.name }), send, "primary big"))]);
}

// A number box for "Total on report" / "Final level". Empty, or the calculated
// value, means "use the calculated value"; a final level has none, so empty
// means no final level.
function overrideInput(id, current, calculated, max, payload, adjusted, label) {
  const reportValue = calculated !== null;
  const value = reportValue && current === calculated ? "" : current ?? "";
  const input = h("input", { type: "number", id, class: "num override", min: "0", step: "any",
    max, value, placeholder: reportValue ? calculated : null,
    "aria-label": label,
    onfocus: reportValue ? (e) => e.target.select() : null,
    onchange: (e) => {
      const raw = e.target.value.trim();
      if (reportValue && !e.target.validity.valid) {
        const message = e.target.validity.badInput ? t("error.report_total_invalid")
          : t("error.report_value_out_of_range", { max });
        toast(message, "error");
        e.target.value = value;
        return;
      }
      const v = raw === "" || Number(raw) === calculated ? null : Number(raw);
      keepingPlace(post("/api/overall", payload(v)));
    } });
  return h("div", { class: "override-wrap" }, input,
    adjusted ? h("button", { type: "button", class: "icon-btn", title: t("step5.reset"), "aria-label": t("step5.reset"),
      onclick: () => keepingPlace(post("/api/overall", payload(null))) }, "↺") : null,
    adjusted ? h("div", { class: "small warn-text" }, t("step5.adjusted", { calculated: calculated ?? "—" })) : null);
}

// --- Making the reports ---------------------------------------------------------------------

// At most five options, each hidden when it does not apply to this exam. The
// one that also adds columns to the review table sits above that table.
function reportOptions(c, used, hasMarks) {
  const options = c.report_options;
  const set = (change) => act(post("/api/report-options", change));
  const tick = (key, label) => h("label", { class: "check" }, h("input", { type: "checkbox", checked: options[key],
    onchange: (e) => set({ [key]: e.target.checked }) }), label);
  const sections = c.sections?.length ? c.sections : null;
  const imageTick = (sid, label) => h("label", { class: "check" },
    h("input", { type: "checkbox", checked: !options.no_images_for.includes(sid),
      onchange: (e) => set({ no_images_for: e.target.checked ? options.no_images_for.filter((x) => x !== sid)
        : [...options.no_images_for, sid] }) }), label);
  return h("div", { class: "report-options" },
    h("h3", {}, t("step5.options_title")),
    h("div", {},
      sections ? tick("section_results", t("step5.option.section_results")) : null,
      used.some((r) => r.bands.some((b) => b.descriptor)) ? tick("rubric_table", t("step5.option.rubric_table")) : null,
      hasMarks ? tick("overall_marks", t("step5.option.overall_marks")) : null,
      sections ? null : imageTick("sec1", t("step5.option.images"))),
    sections ? h("div", {}, h("span", { class: "label" }, t("step5.option.images_for")),
      sections.map((s) => imageTick(s.id, sectionName(c, s.id)))) : null);
}

function exportPanel(c, incomplete, used, hasMarks) {
  const d = exportDraft();
  const result = d.result;
  const previewId = d.previewId || c.students[0].id;
  return h("section", { class: "card export-card" },
    h("h2", {}, t("step5.export_title")),
    h("p", { class: "muted" }, t("step5.export_hint")),
    reportOptions(c, used, hasMarks),
    h("div", { class: "row" }, h("span", { class: "label" }, t("step5.report_language")),
      h("div", { class: "seg" }, ["en", "ja"].map((lang) => h("button", {
        type: "button", class: d.language === lang ? "on" : "", "aria-pressed": d.language === lang ? "true" : "false",
        onclick: () => { d.language = lang; render(); } }, lang === "en" ? "🇬🇧 English" : "🇯🇵 日本語")))),
    h("div", { class: "row preview-row" },
      h("label", { class: "inline" }, t("step5.preview_label"),
        h("select", { id: "preview-student", onchange: (e) => { d.previewId = e.target.value; render(); } },
          c.students.map((s) => h("option", { value: s.id, selected: s.id === previewId ? "selected" : null }, s.display_name)))),
      h("a", { class: "btn", target: "_blank", rel: "noopener",
        href: `/api/report-preview/${encodeURIComponent(previewId)}?lang=${d.language}` }, t("step5.preview"))),
    h("div", { class: "banner warn" }, h("p", {}, "⚠ ", t("step5.replace_warning"))),
    h("div", { class: "actions left" },
      button(t("step5.make_all"), () => runExport("all", incomplete), "primary big"),
      button(t("step5.make_excel"), () => runExport("excel", incomplete)),
      button(t("step5.add_papers"), async () => { await goTo(1); openAddPapers(); }, "ghost")),
    result ? h("div", { class: result.errors.length ? "banner warn" : "banner ok" },
      h("div", {},
        h("strong", {}, result.pdfs ? t("step5.done_all", { n: result.pdfs }) : t("step5.done_excel")),
        h("p", { class: "path" }, result.folder),
        result.errors.length ? h("ul", {}, result.errors.map((e) => h("li", {}, `${e.file}: ${e.error}`))) : null),
      button(t("step5.open_folder"), async () => {
        try { await post("/api/open-folder"); } catch (err) { toast(err.message, "error"); }
      })) : null);
}

// Final levels typed for some students and not others: who is missing, per criterion.
function missingFinals(c) {
  if (!c.report_options.overall_criteria) return [];
  const results = new Map(app.session.summary.students.map((s) => [s.student_id, s]));
  return usedCriteria(c).flatMap((r) => {
    const lacking = c.students.filter((s) => (results.get(s.id).rubrics[r.id].final ?? null) === null);
    return lacking.length && lacking.length < c.students.length
      ? [`${r.name}: ${lacking.map((s) => s.display_name).join(", ")}`] : [];
  });
}

async function runExport(what, incomplete) {
  const d = exportDraft();
  if (incomplete && !(await confirmBox(t("step5.incomplete_title"), t("step5.incomplete_confirm", { n: incomplete }),
    t("step5.make_anyway")))) return;
  const missing = what === "all" ? missingFinals(config()) : [];
  if (missing.length && !(await confirmBox(t("step5.finals_title"), t("step5.finals_confirm", { list: missing.join(" / ") }),
    t("step5.make_anyway")))) return;
  let data;
  try {
    data = await post("/api/export", { language: d.language, what });
  } catch (err) {
    await handleError(err);
    return;
  }
  const overlay = progressOverlay(t("step5.working"), what === "all" ? t("step5.working_note") : "");
  try {
    const job = await waitForJob(data.job, overlay.update);
    d.result = job.result;
    app.session = job.session;
  } catch (err) {
    await handleError(err);
  } finally {
    overlay.close();
    render();
  }
}
