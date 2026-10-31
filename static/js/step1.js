// Step 1: name the exam, choose the scans, paper size and save folder; then
// check the scans as thumbnails, fix pages and add late papers.
import { get, post, waitForJob } from "./api.js";
import { t } from "./i18n.js";
import { enterWizard, goTo } from "./main.js";
import { act, app, config, handleError, render } from "./store.js";
import { button, coach, confirmBox, debounce, h, modal, pickerWait, progressOverlay, toast } from "./ui.js";

const PAPERS = ["A4", "B5", "A3"];
const STREAM = ["combined", "photos"];

function draft() {
  if (!app.draft.newSession) {
    app.draft.newSession = { exam: "", src: newSource(), paper: null, landscape: false, detected: null,
      saveFolder: "", saveFolderChosen: false };
  }
  return app.draft.newSession;
}

// --- Choosing scans (shared by "new session", "choose different scans" and "add papers") --

// kind: "combined" (one or more PDFs of the class), "folder" (one file per
// student) or "photos" (one picture per page). layout: "pages" or "booklet".
function newSource(defaults = {}) {
  return { kind: null, pdfs: [], folder: null, layout: "pages", pagesPerStudent: "", students: "",
    flipFronts: false, flipBacks: false, insideFirst: false, preview: null, ...defaults };
}

function isStream(s) { return STREAM.includes(s.kind); }

function scanInfo(s) {
  if (s.kind === "combined") {
    const first = s.pdfs[0] || {};
    return { pages: s.pdfs.reduce((n, p) => n + p.pages, 0), paper: first.paper, landscape: !!first.landscape };
  }
  return s.folder || { pages: 0 };
}

function perValue(s) {
  const per = parseInt(s.pagesPerStudent, 10);
  if (!(per > 0)) return null;
  return s.layout === "booklet" && per % 4 ? null : per;
}

function classSize(text) {
  const n = parseInt(text, 10);
  return n > 0 ? n : null;
}

function sourceReady(s) {
  if (s.kind === "combined" ? !s.pdfs.length : !s.folder) return false;
  return !isStream(s) || perValue(s) !== null;
}

function sourcePayload(s) {
  return { type: s.kind, paths: s.kind === "combined" ? s.pdfs.map((p) => p.path) : undefined,
    path: s.kind === "combined" ? undefined : s.folder?.path, layout: s.layout,
    pages_per_student: isStream(s) ? perValue(s) : null, students: isStream(s) ? classSize(s.students) : null,
    flip_fronts: s.layout === "booklet" && s.flipFronts, flip_backs: s.layout === "booklet" && s.flipBacks,
    inside_first: s.layout === "booklet" && s.insideFirst };
}

// What a long stack will become, checked against the class size when given.
// A booklet takes half as many scanned pages as it has pages.
function describeSplit(s) {
  const per = perValue(s);
  if (per === null) return { text: "", warn: false };
  const pages = scanInfo(s).pages;
  const scanned = s.layout === "booklet" ? per / 2 : per;
  const n = Math.ceil(pages / scanned), left = pages % scanned;
  const students = classSize(s.students);
  if (students) {
    const expected = students * scanned, diff = pages - expected;
    if (diff === 0) return { text: t("step1.split_class_ok", { students }), warn: false };
    const key = diff < 0 ? "step1.split_missing" : "step1.split_extra";
    return { text: t(key, { students, per: scanned, expected, pages, n: Math.abs(diff) }), warn: true };
  }
  if (left) return { text: t("step1.split_leftover", { students: n, left }), warn: true };
  return { text: s.layout === "booklet" ? t("step1.booklet_split_ok", { students: n, per })
    : t("step1.split_ok", { students: n }), warn: false };
}

async function pick(kind) {
  const done = pickerWait();
  try {
    return (await post("/api/pick", { kind: { pdf: "pdf", folder: "scans_folder", photos: "photos_folder" }[kind] })).path;
  } catch (err) {
    toast(err.message, "error");
    return null;
  } finally {
    done();
  }
}

async function inspect(kind, path) {
  try {
    return await post("/api/inspect", { kind: kind === "pdf" ? "pdf" : "folder", path });
  } catch (err) {
    toast(err.message, "error");
    return null;
  }
}

// The scans part of the form. It redraws itself; onChange(what) tells the
// owner that the source ("source") or the preview ("preview") changed, or
// that a number was typed ("typed").
function sourceChooser(s, onChange, { forAdd = false } = {}) {
  const holder = h("div", { class: "source-chooser" });
  const previewBox = h("div", { class: "preview-box" });
  let previewRun = 0;

  const refreshPreview = async () => {
    const run = ++previewRun;
    if (!sourceReady(s)) { s.preview = null; drawPreview(); return; }
    previewBox.replaceChildren(h("p", { class: "muted" }, t("step1.preview_loading")));
    try {
      const result = await post("/api/preview-paper", { source: sourcePayload(s) });
      if (run !== previewRun) return;
      s.preview = result;
    } catch (err) {
      if (run !== previewRun) return;
      s.preview = null;
      previewBox.replaceChildren(h("p", { class: "warn-text" }, err.message));
      return;
    }
    drawPreview();
    onChange("preview");
  };
  const schedulePreview = debounce(refreshPreview, 450);

  const drawPreview = () => {
    const p = s.preview;
    if (!p) { previewBox.replaceChildren(); return; }
    previewBox.replaceChildren(
      h("p", {}, h("strong", {}, t("step1.preview_title")), " ",
        h("span", { class: "muted" }, t("step1.preview_papers", { papers: p.papers }))),
      h("div", { class: "preview-strip" }, p.images.map((src, i) => h("figure", {},
        h("img", { src, alt: String(i + 1) }), h("figcaption", {}, String(i + 1))))));
  };

  const changed = (what = "source") => { s.preview = null; draw(); schedulePreview(); onChange(what); };

  const choose = async (kind) => {
    const path = await pick(kind === "combined" ? "pdf" : kind);
    if (!path) return;
    const info = await inspect(kind === "combined" ? "pdf" : "folder", path);
    if (!info) return;
    if (kind === "combined") {
      if (s.kind !== "combined") s.pdfs = [];
      s.pdfs.push(info);
    } else {
      s.folder = info;
    }
    s.kind = kind;
    changed();
  };

  const draw = () => {
    const pathInput = h("input", { type: "text", class: "path-input", placeholder: t("step1.paste_path_placeholder"),
      "aria-label": t("step1.paste_path") });
    const typed = async (kind) => {
      const info = await inspect(kind === "combined" ? "pdf" : "folder", pathInput.value);
      if (!info) return;
      if (kind === "combined") { if (s.kind !== "combined") s.pdfs = []; s.pdfs.push(info); } else s.folder = info;
      s.kind = kind;
      changed();
    };
    const card = (kind, icon, title, hint, extra = null) => h("button", {
      type: "button", class: `choice-card ${s.kind === kind ? "selected" : ""}`, onclick: () => choose(kind),
    }, h("span", { class: "choice-icon" }, icon), h("strong", {}, title, extra), h("span", { class: "muted" }, hint));

    const parts = [h("div", { class: "choice-row three" },
      card("combined", "📄", t("step1.combined"), t("step1.combined_hint"),
        h("span", { class: "badge" }, t("step1.recommended"))),
      card("folder", "📁", t("step1.folder"), t("step1.folder_hint")),
      card("photos", "📷", t("step1.photos"), t("step1.photos_hint"))),
      h("details", { class: "advanced" }, h("summary", {}, t("step1.paste_path")),
        h("div", { class: "row" }, pathInput,
          button(t("step1.use_folder"), () => typed("folder"), "small"),
          button(t("step1.use_pdf"), () => typed("combined"), "small")))];

    if (s.kind === "combined" && s.pdfs.length) {
      parts.push(h("div", { class: "chosen ok" },
        h("ol", { class: "pdf-list" }, s.pdfs.map((p, i) => h("li", {},
          h("span", { class: "path" }, p.path), " ",
          h("span", { class: "muted small" }, t("step1.page_count", { pages: p.pages })), " ",
          button(t("step1.remove_pdf"), () => { s.pdfs.splice(i, 1); if (!s.pdfs.length) s.kind = null; changed(); },
            "small ghost")))),
        s.pdfs.length > 1 ? h("p", {}, t("step1.pdf_total", { files: s.pdfs.length, pages: scanInfo(s).pages }))
          : h("p", {}, t("step1.pages_found", { pages: scanInfo(s).pages })),
        button(t("step1.add_pdf"), () => choose("combined"), "small")));
    } else if (s.kind === "folder" && s.folder) {
      parts.push(h("div", { class: "chosen ok" }, h("strong", {}, s.folder.path),
        h("p", {}, t("step1.files_found", { count: s.folder.count }))));
    } else if (s.kind === "photos" && s.folder) {
      parts.push(h("div", { class: "chosen ok" }, h("strong", {}, s.folder.path),
        h("p", {}, t("step1.photos_found", { count: s.folder.count, pages: s.folder.pages }))));
    }

    if (s.kind) {
      const layoutCard = (layout, icon, title, hint) => h("button", {
        type: "button", class: `choice-card ${s.layout === layout ? "selected" : ""}`,
        onclick: () => { s.layout = layout; changed(); },
      }, h("span", { class: "choice-icon" }, icon), h("strong", {}, title), h("span", { class: "muted" }, hint));
      parts.push(h("h3", {}, t("step1.layout")),
        h("div", { class: "choice-row" },
          layoutCard("pages", "📃", t("step1.layout_pages"), t("step1.layout_pages_hint")),
          layoutCard("booklet", "📖", t("step1.layout_booklet"), t("step1.layout_booklet_hint"))));
      if (s.layout === "pages" && scanInfo(s).landscape) {
        parts.push(h("p", { class: "warn-text" }, t("step1.layout_landscape_hint")));
      }
    }

    if (isStream(s) && (s.pdfs.length || s.folder)) {
      const booklet = s.layout === "booklet";
      const result = h("p", {});
      const showSplit = () => {
        const { text, warn } = describeSplit(s);
        result.className = warn ? "warn-text" : "";
        result.textContent = text;
      };
      const number = (id, key, value, set) => h("input", { type: "number", min: "1", step: booklet && key === "per" ? "4" : "1",
        id, class: "num", value, oninput: (e) => { set(e.target.value); showSplit(); schedulePreview(); onChange("typed"); } });
      const perInput = number("pages-per-student", "per", s.pagesPerStudent, (v) => { s.pagesPerStudent = v; });
      const rows = [h("label", { class: "inline", for: "pages-per-student" },
        t(booklet ? "step1.booklet_pages" : "step1.pages_per_student"), perInput,
        booklet ? h("span", { class: "muted small" }, t("step1.booklet_pages_hint")) : null)];
      if (!forAdd) {
        rows.push(h("label", { class: "inline", for: "class-size" }, t("step1.class_size"),
          number("class-size", "class", s.students, (v) => { s.students = v; })));
      }
      parts.push(h("div", { class: "stack numbers" }, ...rows), result);
      showSplit();
    }

    if (s.kind && s.layout === "booklet") {
      const flip = (key, label) => h("label", { class: "check" },
        h("input", { type: "checkbox", checked: s[key], onchange: (e) => { s[key] = e.target.checked; schedulePreview(); } }),
        label);
      parts.push(h("div", {}, flip("insideFirst", t("step1.booklet_inside_first")),
        flip("flipFronts", t("step1.booklet_fronts")), flip("flipBacks", t("step1.booklet_backs")),
        h("p", { class: "muted small" }, t("step1.booklet_flip_hint"))));
    }
    parts.push(previewBox);
    holder.replaceChildren(...parts);
    drawPreview();
  };

  draw();
  if (!s.preview && sourceReady(s)) schedulePreview();
  return holder;
}

// --- New session form ----------------------------------------------------------------

const loadDefaultFolder = debounce(async (exam) => {
  const d = draft();
  if (d.saveFolderChosen) return;
  try {
    d.saveFolder = (await get(`/api/default-folder?exam=${encodeURIComponent(exam || "Exam")}`)).path;
    const shown = document.getElementById("save-folder-path");
    if (shown) shown.textContent = d.saveFolder;
  } catch { /* leave as is */ }
}, 300);

export function renderNewSession() {
  const d = draft();
  if (!d.saveFolder) loadDefaultFolder(d.exam);

  const examInput = h("input", { type: "text", id: "exam-name", class: "big-input", value: d.exam,
    placeholder: t("step1.exam_placeholder"), maxlength: "80",
    oninput: (e) => { d.exam = e.target.value; loadDefaultFolder(d.exam); updateCreate(); } });

  // Paper size: a booklet's pages are half a scanned page, so the preview
  // (which is unfolded) is the better guess for booklets.
  const paperHolder = h("div", {});
  const drawPaper = () => paperHolder.replaceChildren(
    h("div", { class: "seg big" }, PAPERS.map((p) => h("button", {
      type: "button", class: d.paper === p ? "on" : "", "aria-pressed": d.paper === p ? "true" : "false",
      onclick: () => { d.paper = p; drawPaper(); updateCreate(); },
    }, p, d.detected === p ? h("span", { class: "badge" }, t("step1.detected")) : null))),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: d.landscape,
      onchange: (e) => { d.landscape = e.target.checked; } }), t("step1.landscape")));
  drawPaper();

  const onSource = (what) => {
    const s = d.src;
    const guess = s.layout === "booklet" ? s.preview : (what === "preview" ? s.preview : scanInfo(s));
    if ((what === "source" || what === "preview") && guess?.paper) {
      d.paper = guess.paper;
      d.landscape = !!guess.landscape;
      d.detected = guess.paper;
      drawPaper();
    }
    updateCreate();
  };

  const createBtn = button(t("step1.create"), createSession, "primary big", { id: "create-session" });
  const updateCreate = () => { createBtn.disabled = !ready(d); };
  updateCreate();

  return h("main", { class: "page narrow" },
    h("h1", {}, t("step1.title")),
    coach(t("step1.coach")),
    h("section", { class: "form-step" }, h("h2", {}, h("span", { class: "num-badge" }, "1"), t("step1.exam_name")), examInput),
    h("section", { class: "form-step" }, h("h2", {}, h("span", { class: "num-badge" }, "2"), t("step1.where_scans")),
      sourceChooser(d.src, onSource)),
    h("section", { class: "form-step" }, h("h2", {}, h("span", { class: "num-badge" }, "3"), t("step1.paper")),
      h("p", { class: "muted" }, t("step1.paper_hint")), paperHolder),
    h("section", { class: "form-step" }, h("h2", {}, h("span", { class: "num-badge" }, "4"), t("step1.save_folder")),
      h("p", { class: "muted" }, t("step1.save_folder_hint")),
      h("p", { class: "muted small" }, t("step1.save_folder_cloud_note")),
      h("div", { class: "chosen" }, h("strong", { id: "save-folder-path" }, d.saveFolder || "…")),
      button(t("step1.choose_folder"), async () => {
        const done = pickerWait();
        try {
          const res = await post("/api/pick", { kind: "save_folder" });
          if (res.path) { d.saveFolder = res.path; d.saveFolderChosen = true; render(); }
        } catch (err) { toast(err.message, "error"); } finally { done(); }
      })),
    h("div", { class: "actions" },
      button(t("common.back_to_start"), () => { app.view = "start"; app.draft = {}; render(); }, "ghost"),
      createBtn));
}

function ready(d) {
  return !!(d.exam.trim() && sourceReady(d.src) && d.paper && d.saveFolder);
}

async function createSession() {
  const d = draft();
  if (!ready(d)) return;
  let data;
  try {
    data = await post("/api/session/create", { exam_name: d.exam.trim(), source: sourcePayload(d.src),
      paper: d.paper, landscape: d.landscape, save_folder: d.saveFolder });
  } catch (err) {
    await handleError(err);
    return;
  }
  app.session = data.session;
  await runImport(data.job);
  enterWizard();
  app.step = 1;
  render();
}

async function runImport(jobId, title = t("step1.importing")) {
  const overlay = progressOverlay(title, t("step1.importing_note"));
  try {
    const job = await waitForJob(jobId, overlay.update);
    app.session = job.session;
    return job;
  } catch (err) {
    if (err.job?.session) app.session = err.job.session;
    await handleError(err);
    return null;
  } finally {
    overlay.close();
  }
}

// --- Scan check (wizard step 1) --------------------------------------------------------

export function renderScanCheck() {
  const c = config();
  if (!c.students?.length) {
    return h("main", { class: "page narrow" }, h("h1", {}, t("step1.check_title")),
      coach(t("step1.no_students")), button(t("step1.choose_again"), chooseAgain, "primary"));
  }
  const warnings = c.scan_warnings || {};
  const flagged = new Map((warnings.page_counts || []).map((w) => [w.student, w]));
  const list = [];
  const size = warnings.class_size;
  if (size) {
    list.push(h("li", {}, t(size.diff < 0 ? "step1.warn_class_missing" : "step1.warn_class_extra",
      { students: size.students, expected: size.expected_pages, pages: size.pages, n: Math.abs(size.diff) })));
  } else if (warnings.leftover) {
    list.push(h("li", {}, t("step1.warn_leftover", { left: warnings.leftover })));
  }
  for (const w of warnings.page_counts || []) {
    const s = c.students.find((x) => x.id === w.student);
    list.push(h("li", {}, t("step1.warn_pages", { name: s ? s.display_name : w.student, pages: w.pages, expected: w.expected })));
  }
  const stamp = Date.now();
  return h("main", { class: "page wide" },
    h("h1", {}, t("step1.check_title")),
    coach(t("step1.check_coach", { count: c.students.length })),
    list.length ? h("div", { class: "banner warn" }, h("div", {}, h("strong", {}, t("step1.warn_title")),
      h("ul", {}, list), h("p", { class: "small" }, t("step1.warn_advice")))) : null,
    h("div", { class: "thumbs" }, c.students.map((s, i) => h("button", {
      type: "button", class: `thumb ${flagged.has(s.id) ? "flagged" : ""}`, onclick: () => showPages(s.id),
      title: t("step1.see_pages"),
    }, h("span", { class: "thumb-num" }, String(i + 1)),
    h("img", { src: `/api/thumb/${s.id}?v=${stamp}`, alt: s.display_name, loading: "lazy" }),
    h("span", { class: "thumb-name" }, s.display_name),
    h("span", { class: "muted small" }, t("step1.page_count", { pages: s.pages ?? "?" }))))),
    h("div", { class: "actions sticky" },
      button(t("step1.choose_again"), chooseAgain, "ghost"),
      button(t("step1.add_papers"), openAddPapers),
      button(t("step1.looks_right"), () => goTo(2, { next: true }), "primary big")));
}

function hasWork(studentId) {
  const per = app.session?.grades?.grades?.[studentId] || {};
  return Object.values(per).some((e) => e && (e.value != null || String(e.comment || "").trim()
    || Object.values(e.levels || {}).some((v) => v != null)));
}

// Which sheet of an open-scanned booklet a page is on (mirrors pages.booklet_layout).
function bookletSheet(page, pages) {
  const n = Math.ceil(pages / 4) * 4;
  for (let i = 0; i < n / 4; i++) {
    if ([n - 2 * i, 2 * i + 1, 2 * i + 2, n - 2 * i - 1].includes(page)) return i + 1;
  }
  return 1;
}

function isStreamPaper(student) {
  const c = config();
  const batch = student.batch || 0;
  const record = batch ? (c.more_imports || [])[batch - 1] : c.import;
  return !!record && STREAM.includes(record.type) && !student.sides;
}

function showPages(studentId, startPage = 1) {
  let student = config().students.find((s) => s.id === studentId);
  if (!student) return;
  let page = Math.min(startPage, student.pages || 1);
  const img = h("img", { class: "page-view", alt: student.display_name });
  const label = h("span", {});
  const tools = h("div", { class: "page-tools" });
  const title = h("span", {}, student.display_name);

  const show = () => {
    img.src = `/api/page/${student.id}/${page}?w=1000&r=${Date.now()}`;
    label.textContent = t("common.page_of", { page, pages: student.pages || 1 });
    title.textContent = student.display_name;
    drawTools();
  };

  const edit = async (action) => {
    if (action === "remove" && !await confirmBox(t("pages.remove_title"), t("pages.remove_message"),
      t("pages.remove"), t("common.cancel"), true)) return;
    const data = await act(post("/api/pages/edit", { student: student.id, page, action }), { rerender: false });
    if (!data) return;
    render();
    const next = config().students.find((s) => s.id === data.where.student);
    if (next) { student = next; page = data.where.page; }
    show();
  };

  const drawTools = () => {
    if (hasWork(student.id)) {
      tools.replaceChildren(h("p", { class: "muted small" }, t("pages.locked")));
      return;
    }
    if (student.sides) {
      tools.replaceChildren(h("h3", {}, t("pages.tools")),
        h("div", { class: "row" },
          button(t("pages.turn_sheet"), () => edit("turn_sheet"), "small"),
          button(t("pages.swap_sheet"), () => edit("swap_sheet"), "small"),
          button(t("pages.reverse_sheets"), () => edit("reverse_sheets"), "small")),
        h("p", { class: "muted small" }, t("pages.sheet_note", { page, sheet: bookletSheet(page, student.pages || 1) })));
      return;
    }
    tools.replaceChildren(h("h3", {}, t("pages.tools")),
      h("div", { class: "row" },
        button(t("pages.earlier"), () => edit("earlier"), "small"),
        button(t("pages.later"), () => edit("later"), "small"),
        button(t("pages.turn"), () => edit("turn"), "small"),
        button(t("pages.blank_before"), () => edit("blank_before"), "small"),
        button(t("pages.blank_after"), () => edit("blank_after"), "small"),
        button(t("pages.remove"), () => edit("remove"), "small danger")),
      isStreamPaper(student) ? h("p", { class: "muted small" }, t("pages.stream_note")) : null);
  };

  const nav = h("div", { class: "row center" },
    button("‹", () => { if (page > 1) { page--; show(); } }, "small"),
    label,
    button("›", () => { if (page < (student.pages || 1)) { page++; show(); } }, "small"));
  show();
  modal({ title: student.display_name, body: h("div", {}, nav, tools, img), wide: true,
    actions: [{ label: t("common.close") }] });
}

function chooseAgain() {
  const s = newSource();
  modal({
    title: t("step1.choose_again"), wide: true,
    body: h("div", {}, h("p", { class: "muted" }, t("step1.choose_again_hint")), sourceChooser(s, () => {})),
    actions: [
      { label: t("common.cancel") },
      { label: t("step1.replace_scans"), kind: "primary", keepOpen: true, onClick: async (close) => {
        if (!sourceReady(s)) return;
        close();
        const data = await act(post("/api/scans/replace", { source: sourcePayload(s) }), { rerender: false });
        if (data?.job) { await runImport(data.job); app.step = 1; render(); }
      } },
    ],
  });
}

// More papers for this exam, e.g. a student who sat it late. Starts with the
// class's own layout and page count, since late papers usually match.
export function openAddPapers() {
  const record = config()?.import || {};
  const s = newSource({ layout: record.layout || "pages",
    pagesPerStudent: record.pages_per_student ? String(record.pages_per_student) : "",
    flipFronts: !!record.flip_fronts, flipBacks: !!record.flip_backs, insideFirst: !!record.inside_first });
  modal({
    title: t("step1.add_papers"), wide: true,
    body: h("div", {}, h("p", { class: "muted" }, t("step1.add_papers_hint")),
      sourceChooser(s, () => {}, { forAdd: true })),
    actions: [
      { label: t("common.cancel") },
      { label: t("step1.add_papers_button"), kind: "primary", keepOpen: true, onClick: async (close) => {
        if (!sourceReady(s)) return;
        close();
        const data = await act(post("/api/scans/add", { source: sourcePayload(s) }), { rerender: false });
        if (!data?.job) return;
        const job = await runImport(data.job, t("step1.adding"));
        render();
        if (job) toast(t("step1.added", { n: job.result?.added?.length || 0 }), "ok");
      } },
    ],
  });
}
