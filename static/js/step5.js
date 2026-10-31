// Step 5: check every student's results, adjust what goes on the report,
// write overall comments, then make the student PDFs and the Excel gradebook.
import { post, waitForJob } from "./api.js";
import { t, language } from "./i18n.js";
import { goTo } from "./main.js";
import { openAddPapers } from "./step1.js";
import { act, app, config, criteriaOf, gradeOf, handleError, render } from "./store.js";
import { button, coach, confirmBox, debounce, formatTime, h, modal, progressOverlay, toast } from "./ui.js";

const NA = "not_answered";

function exportDraft() {
  if (!app.draft.export) app.draft.export = { language, result: null };
  return app.draft.export;
}

// Jump to Step 4 on one paper, question and criterion; Step 4 offers "Back to review".
function gradeThis(qid, sid, rid = null) {
  goTo(4, { draft: { grading: { qid, rid, sid, ungradedOnly: false, zoom: 1, wholePage: false, page: 1, fromReview: true } } });
}

// One column per grade: per question in Marks mode, per question and
// criterion in Rubric mode. The key matches grading_summary.slot_key.
function columns(c) {
  return c.questions.flatMap((q) => {
    if (c.mode !== "rubric") return [{ q, r: null, key: q.id, multi: false }];
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
  const shown = (q) => (c.mode === "rubric"
    ? criteriaOf(c, q).map((r) => `${r.name} ${valueText(c, q, gradeOf(s.id, q.id, r.id))}`).join(", ")
    : `${valueText(c, q, gradeOf(s.id, q.id))} / ${q.max}`);
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
  const rubricMode = c.mode === "rubric";
  const anyComment = Object.values(grades).some((per) => Object.values(per || {}).some((e) => (e?.comment || "").trim()));
  const cols = columns(c);

  const head = h("tr", {},
    h("th", {}, "#"), h("th", { class: "sticky-col" }, t("step5.student")),
    cols.map(({ q, r, multi }) => h("th", { class: "num-col" }, q.label,
      multi ? h("div", { class: "muted small" }, r.name)
        : h("span", { class: "muted small" }, rubricMode ? "" : ` /${q.max}`))),
    rubricMode
      ? (c.rubrics || []).map((r) => [h("th", { class: "num-col" }, t("step5.average", { name: r.name })),
        h("th", { class: "num-col" }, t("step5.final", { name: r.name }))])
      : [h("th", { class: "num-col" }, t("step5.calculated")), h("th", { class: "num-col" }, t("step5.on_report"))],
    h("th", {}, t("step5.overall_comment")));

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
    const result = rubricMode
      ? (c.rubrics || []).map((r) => {
        const rr = res.rubrics[r.id];
        const top = Math.max(...r.bands.map((b) => b.max));
        return [h("td", { class: "num-col muted" }, rr.average ?? "—"),
          h("td", { class: `num-col ${rr.adjusted ? "adjusted" : ""}` },
            overrideInput(`final-${s.id}-${r.id}`, rr.final, rr.suggested, top,
              (v) => ({ student_id: s.id, final_levels: { [r.id]: v } }), rr.adjusted))];
      })
      : [h("td", { class: "num-col muted" }, `${res.marks.total} / ${res.marks.max}`,
        h("div", { class: "small" }, res.marks.percent !== null ? `${res.marks.percent}%` : "")),
      h("td", { class: `num-col ${res.marks.adjusted ? "adjusted" : ""}` },
        overrideInput(`total-${s.id}`, res.marks.report_total, res.marks.total, null,
          (v) => ({ student_id: s.id, report_total: v }), res.marks.adjusted))];
    const comment = h("textarea", { id: `overall-${s.id}`, rows: "2", class: "overall-comment",
      placeholder: t("step5.comment_placeholder"), "aria-label": t("step5.overall_comment"),
      oninput: (e) => saveComment(s.id, e.target.value), onblur: () => saveComment.flush() }, res.comment || "");
    return h("tr", { class: res.complete ? "" : "incomplete" },
      h("td", { class: "num-cell" }, String(i + 1)),
      h("td", { class: "sticky-col" }, h("strong", {}, s.display_name), choiceButtons(c, s, res)),
      cells, result, h("td", {}, comment));
  });

  const stat = (key) => {
    const label = { average: t("xlsx.average"), max: t("xlsx.max_row"), min: t("xlsx.min_row") }[key];
    const qCells = cols.map((col) => h("td", { class: "num-col" }, summary.questions[col.key]?.[key] ?? ""));
    const rest = rubricMode
      ? (c.rubrics || []).map((r) => [h("td", {}), h("td", { class: "num-col" }, summary.overall[r.id]?.[key] ?? "")])
      : [h("td", { class: "num-col" }, summary.overall.total?.[key] ?? ""), h("td", {})];
    return h("tr", { class: "stat-row" }, h("td", {}), h("td", { class: "sticky-col" }, label), qCells, rest, h("td", {}));
  };

  return h("main", { class: "page full review" },
    h("h1", {}, t("step5.title")),
    coach(t(rubricMode ? "step5.coach_rubric" : "step5.coach_marks")),
    ungraded ? h("div", { class: "banner warn" }, h("p", {}, t("step5.incomplete", { n: ungraded }))) : null,
    pending ? h("div", { class: "banner warn" }, h("p", {}, t("step5.pending", { n: pending }))) : null,
    anyComment ? h("p", { class: "muted small" }, h("span", { class: "comment-dot" }), t("step5.comment_legend")) : null,
    h("div", { class: "table-scroll review-scroll" },
      h("table", { class: "review-table" }, h("thead", {}, head),
        h("tbody", {}, rows), h("tfoot", {}, stat("average"), stat("max"), stat("min")))),
    c.host ? hostPanel(c, incomplete) : null,
    exportPanel(incomplete));
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
// value, means "use the calculated value".
function overrideInput(id, current, calculated, max, payload, adjusted) {
  const input = h("input", { type: "number", id, class: "num override", min: "0", step: "any",
    max: max === null ? null : String(max), value: current ?? "",
    "aria-label": t("step5.on_report"),
    onchange: (e) => {
      const raw = e.target.value.trim();
      const v = raw === "" || Number(raw) === calculated ? null : Number(raw);
      act(post("/api/overall", payload(v)));
    } });
  return h("div", { class: "override-wrap" }, input,
    adjusted ? h("button", { type: "button", class: "icon-btn", title: t("step5.reset"), "aria-label": t("step5.reset"),
      onclick: () => act(post("/api/overall", payload(null))) }, "↺") : null,
    adjusted ? h("div", { class: "small warn-text" }, t("step5.adjusted", { calculated: calculated ?? "—" })) : null);
}

// --- Making the reports ---------------------------------------------------------------------

function exportPanel(incomplete) {
  const d = exportDraft();
  const result = d.result;
  return h("section", { class: "card export-card" },
    h("h2", {}, t("step5.export_title")),
    h("p", { class: "muted" }, t("step5.export_hint")),
    h("div", { class: "row" }, h("span", { class: "label" }, t("step5.report_language")),
      h("div", { class: "seg" }, ["en", "ja"].map((lang) => h("button", {
        type: "button", class: d.language === lang ? "on" : "", "aria-pressed": d.language === lang ? "true" : "false",
        onclick: () => { d.language = lang; render(); } }, lang === "en" ? "🇬🇧 English" : "🇯🇵 日本語")))),
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

async function runExport(what, incomplete) {
  const d = exportDraft();
  if (incomplete && !(await confirmBox(t("step5.incomplete_title"), t("step5.incomplete_confirm", { n: incomplete }),
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
