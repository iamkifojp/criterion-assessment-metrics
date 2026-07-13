# CAM — Changelog

A maintenance log of notable fixes and behaviour changes. Architectural detail
lives in [ARCHITECTURE.md](ARCHITECTURE.md); this file records *what changed and
why*, symptom-first, so a future maintainer can trace a regression quickly.

---

## 2026-07-14 — CGW student naming panel + booklet-scan guard

**What this changes** (Phase 5 of
[EXAM_IDENTITY_AND_BANDING_PLAN.md](EXAM_IDENTITY_AND_BANDING_PLAN.md), D5) — the
grading workspace's exam side, in `cam_grading_workspace/app.py` +
`exam_engine.py`. Complements Phase 4: naming students at the source means the
exported CSV arrives roster-matchable, so CAM's 🧩 matcher is the safety net
rather than the norm.

- **Display-only `student_names` (engine).** Exam configs gain a
  `student_names` map (`{file stem -> real name}`). `save_exam` cleans it to
  str→str, trims values, drops empties, and persists it through both the legacy
  and portable stores; absent/malformed → `{}` (backward compatible). The stem
  stays the storage key everywhere — crops, the grades file and the export
  `csv_key` all key by stem — so these names are display + export only.
- **Naming panel (CGW setup).** A collapsible "Students (N)" block below the
  question table lists every scanned file stem with a real-name input, prefilled
  from the saved map. When a name box is programmed and processed, each row
  shows its `__name__` crop so the teacher reads the handwriting while typing.
  Values ride `configPayload()`, saving with Save Setup / Process All. The panel
  keeps its state in a live `STUDENT_NAMES` object so a resave never drops names
  even when the scan folder isn't on the current device.
- **Display + export plumbing.** `/api/exam/load` returns
  `name = student_names.get(stem, stem)` (still blanked under anonymous
  grading); `/api/exam/export` writes the mapped name into the "Student Name"
  column while the on-disk grades file stays stem-keyed.
- **Booklet-scan consistency guard.** Booklet scans routinely start with a
  blank back-cover page — harmless when every student is scanned the same way,
  silently catastrophic (shifted crops, no error) when one isn't. Page-count
  mismatch is the cheap signal: `/api/exam/scan_folder` now returns per-file
  page counts, the Students panel flags outliers against the class majority
  ("Scan_0003 · 11 pages ⚠ others have 12"), and `process_exam` appends a
  `warnings` list (beside `errors`) surfaced in the process note on a full run.
  New `exam_engine.page_counts` / `scan_page_warnings` helpers; the JS majority
  logic mirrors them (mode, ties → larger count).

## 2026-07-14 — Exam CSVs route through roster identity + name-crop matcher

**What this changes** (Phase 4 of
[EXAM_IDENTITY_AND_BANDING_PLAN.md](EXAM_IDENTITY_AND_BANDING_PLAN.md)) — the
correctness half of the exam identity work, in `engine/ingestion.py` + CAM
`app.py` (D6).

- **Exam ingest routes (engine).** `ingest_exam_csv` treated the "Student Name"
  cell (a PDF filename stem) as a student id, minting a phantom student per
  unmatched row — the roster student then showed the exam as missing forever.
  It now takes the same optional routing inputs as `ingest_csv` (`roster_keys`,
  `aliases`, `unmatched_out`, `auto_aliases_out`) and routes every row through
  the shared `resolve_identity` pipeline (exact → durable alias → unambiguous
  prefix → pool). Matched rows attach their `ExamResult` to the roster student
  (the `chosen` carry-forward is keyed on the *resolved* student, so
  alias-routed re-syncs keep teacher resolutions); unmatched rows pool as
  exam-flavoured rows (`is_exam: True` + `questions`/`total`/`max_total`/
  `comment`, sheet-wide and sidecar max backfilled). No roster → byte-identical
  legacy behaviour.
- **Sync caller (CAM).** `_ingest_cloud_file` passes the routing inputs to the
  exam branch too; the existing purge-replace pool rebuild and auto-alias
  recording fire for exams unchanged. The "Exam CSVs never route" note dies.
- **Visual matching.** A pooled exam row surfaces in the same Window-2 missing
  popup 🧩 matcher as assignment works. Its tile shows the script's
  handwritten **name-box crop** (fallback: the first question crop found on
  disk; final fallback a filename tile) captioned `stem · 31/45` (raw total).
  Assigning writes the durable alias and materialises an `ExamResult` under the
  roster student via the new `materialize_exam_row` (the exam sibling of
  `materialize_row`, preserving prior `chosen` picks) — re-syncs then route
  silently via the alias.
- **Name-crop dual-root fix.** `exam_name_crop_path` / `exam_has_name_crops`
  only checked the legacy app-local `cam_grading_workspace/exam_crops/…` root,
  so cloud-backed classes (crops under `<class folder>/exam_crops/…` since the
  slicer-v2 plan's Phase 6) lost the Window-1 mis-named-script preview. Both
  helpers (and the new `exam_crop_path`) now resolve cloud-root-first with the
  legacy root as fallback, mirroring the exam-delete purge. Also fixed
  `_cgw_safe_name`'s sanitizer drift (it was missing `\` and `/` versus CGW's
  `_safe_name`).
- **Phantom cleanup.** On a routed exam ingest (roster classes only), students
  who are on no class's roster (active or archived) and hold no scores and no
  exam results — the phantoms earlier unrouted exam ingests minted — are
  removed and reported in the sync summary.
- Covered by `tests/test_exam_identity.py` (routing, pooling, materialise,
  phantom sweep, dual-root crops, end-to-end scoped sync).

---

## 2026-07-14 — CGW exam tab discipline + Process-All crop refresh

**What this changes** (Phase 2 of
[EXAM_IDENTITY_AND_BANDING_PLAN.md](EXAM_IDENTITY_AND_BANDING_PLAN.md)) — all in
`cam_grading_workspace/app.py`.

- **One named setup tab (D3).** The grading tab opened Exam Setup with
  `window.open(url, "_blank")`, so every Adjust / Exam Setup click stacked a new
  tab. Both routes (`openExamAdjust`, the `#examSetupBtn` handler) now target the
  named `"cam_exam_setup"` window and `.focus()` it — repeat clicks re-navigate
  the single setup tab (re-running the `?exam=&focus=` deep-link so focus-adjust
  still lands on the right question).
- **Smart back-link (D3).** The `← back to grading` link, when the setup tab was
  script-opened from a grading tab, now focuses that opener and closes itself;
  otherwise (direct URL / middle-click / no-JS) it falls through to `href="/"`.
- **Process All refreshes the grading tab (D4).** Only single-question re-slices
  pinged an open grading tab, so a full Process-All left its crops stale.
  `pollExamJob` now writes the same `localStorage["cam_exam_resliced"]` signal
  (with an empty label = whole exam) that a single re-slice writes; the grading
  tab's `storage` listener bumps its crop cache-buster and refetches every crop
  in place, showing "Exam re-processed — crops refreshed."
- Behaviour-only; no data, config, or grade-file changes.

---

## 2026-07-14 — CGW exam cosmetics: bare question dropdown + width-aware cell labels

**What this changes** (Phase 1 of
[EXAM_IDENTITY_AND_BANDING_PLAN.md](EXAM_IDENTITY_AND_BANDING_PLAN.md)) — two
small Exam-grading readability fixes in `cam_grading_workspace/app.py`.

- **Question dropdown de-clutter (D1).** The single-question picker (`loadExam`)
  showed each option as `2ap  (0–2)`. The `(0–max)` range is already printed in
  the grading sheet's question-column header right beside the dropdown, so the
  option text is now the bare label (`2ap`) — less visual noise, no lost info.
- **Width-aware cell labels (D2).** `sizeCellLabels()` sized the translucent
  grid-cell labels by cell **height** only (`(h/NROWS)*0.55`), so wide labels
  (`D10`, or fine-A3's `AD42`) overflowed horizontally into neighbouring cells.
  It now also caps by width: it computes the widest possible label on the current
  grid (`colName(NCOLS-1)+NROWS`) and shrinks the font so that label fits inside
  one cell width, taking `min(height, width)` cap. Labels no longer bleed across
  a cell border at any paper size / density / fit mode / window size.
- Cosmetic-only; no data, config, or grade-file changes.

---

## 2026-07-13 — User manual: a dedicated "Grading exam papers" section

**What this adds** (Phase 8 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md)) —
[USER_MANUAL.md](USER_MANUAL.md) mentioned exam grading only in scattered notes
under "The grading workspace"; there was no walkthrough of the full loop and none
of the Phase 1–7 polish was documented for the teacher.

- **New "Grading exam papers" section** walks the whole loop as numbered steps:
  create the exam in Window 1 → Exam Setup (scan folder, grid density + colour
  picker, fit width/page, name box, sections, max marks, Save + Process All PDFs)
  → grade one question at a time (question dropdown, single-question sheet with
  **no running totals**, keyword checklist, comments, ✎ adjust + re-slice,
  anonymous positional numbering) → Export CSV → CAM auto-ingest → cockpit
  (including resolving a `?` choice section) → permanent-delete purge.
- **Explains the anonymous numbering** the way the teacher experiences it — papers
  numbered by *position* (`01`, `02`, …) and **re-shuffled per question**, so a
  number is a progress counter, not an identity, and no impression accumulates
  across questions. Notes it's bias reduction, not blind review.
- **New cloud-folder subsection** documents the portability trade-offs from
  decision D5/D6: sync lag after slicing (hundreds of PNGs, ~students × questions
  per exam), the space they occupy, and that *re-slicing* still needs the scan
  PDFs present on that device while grading alone doesn't.
- The pre-existing exam-setup notes (grid density, name box, sections, resolving a
  choice, adjusting a question's box) were folded into the new section's steps
  rather than left as loose paragraphs — no content dropped, deduplicated.
- Docs-only; no code changes.

---

## 2026-07-13 — Permanent delete of an exam purges its grading-workspace artifacts

**Symptom** (Phase 7 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md), decision D7) —
deleting an exam assignment in Window 1 and purging it from the Archived dialog
left its sliced crops on disk and, worse, left the exported `*_Grades_*.csv` in
the class folder, which the watch-folder sync would re-ingest — resurrecting the
"deleted" exam on the next sync.

- **`delete_assignment_permanent(name)`** now checks `is_exam` (before the
  records are dropped) and, for an exam, calls the new
  **`_purge_exam_cgw_artifacts(name, classes)`**. Normal assignments carry no
  such artifacts and skip it entirely.
- **What it removes, per class the exam belonged to:** the sliced crop tree
  (`<cloud>/<class>/exam_crops/<exam>/` **and** the legacy
  `cam_grading_workspace/exam_crops/<class>/<exam>/`), the exam's definition
  entry in both the portable per-class `<cloud>/<class>/gcg_exams.json` and the
  legacy app-local `gcg_exams.json` (rewritten without that one entry — never
  the whole file), the `exam_grades_<exam>.json` grading file, and the exported
  `<exam>_Grades_*.csv` **plus its `.meta.json` sidecar**.
- **Never guesses.** The exam's real name is recovered by matching the
  assignment name (itself derived from the CSV filename) against the stored exam
  names via the same sanitize→clean round-trip the importer uses
  (`clean_assignment_name(_safe_dirname(...))`). No stored exam matches → nothing
  is deleted file-side (logged).
- **Guarded + tolerant.** Every delete is scoped to its expected root
  (`_path_within`, realpath-normalised) so a mangled slug can never escape, and
  missing paths are skipped — a half-migrated class simply cleans up whatever is
  present. Definition rewrites are atomic (`.tmp`+`os.replace`).
- **UX.** The Archived dialog now captions exam rows: "Also deletes the sliced
  answer images, exam definition, grading file and exported CSV for this exam."
  Restore is unaffected — only "Delete permanently" triggers the purge.

---

## 2026-07-13 — Portable exam data: crops + definitions into the class folder

**What this adds** (Phase 6 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md), decision D5) — an exam
used to be pinned to the machine that sliced it: crops lived under
`cam_grading_workspace/exam_crops/<class>/…` and definitions in the app-local
`gcg_exams.json`. Both now live *inside a cloud-synced class folder* when the
class has one, so the exam can be graded from any synced device.

- **Crop root.** New `exam_crop_dir(class_name, create=True)` writes to
  `<cloud>/<class>/exam_crops/<exam>/<Q>/<student>.png` for a cloud-backed class,
  else the legacy `BASE_DIR/exam_crops/<class>/…`. Both slicing paths
  (`/api/exam/process`, `/api/exam/process_one`) write the resolved root.
- **Read fallback.** New `exam_crop_roots(class_name)` returns the cloud root
  first, then the legacy root; the student-discovery scan in `/api/exam/load` and
  crop serving (`/api/exam/crop`) try each in order, so crops sliced before a
  class moved to the cloud keep serving. Legacy crops are never moved or deleted.
- **Portable definition store.** `ExamStore` grows a per-class
  `<cloud>/<class>/gcg_exams.json` shaped `{"exams": {…}}`. Reads prefer it once
  it exists; saves target it when the class has a cloud folder; the **first save
  migrates** that class's legacy exams into it (never clobbering, never rewriting
  the legacy file, which stays as a frozen fallback). Wired via
  `EXAM_STORE.class_dir = _exam_class_dir` (resolver → the class cloud folder or
  `None`); cloud-less classes keep the legacy app-local store unchanged.
- **Cross-device caveat.** `pdf_folder` is an absolute per-device path: grading
  from synced crops works anywhere, but *re-slicing* needs the scans present on
  that device. `/api/exam/process*` now detects a missing scan folder and says
  exactly that ("This device can't see the scan folder … grading still works
  from the synced crops"). Volume note: ~`students × (questions+1)` PNGs per exam
  land in the cloud folder and must sync before another device sees them.

**Concurrency/backward-compat:** atomic `.tmp`+`os.replace` per file,
last-writer-wins (same doctrine as exam grades). `ExamStore(base_dir)` with no
resolver stays legacy-only, so existing tests and cloud-less setups are
unaffected; migration is one-directional and additive.

---

## 2026-07-13 — Exam grading: anonymous mode (YouMark-style positional numbering)

**What this adds** (Phase 5 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md), decision D6) — the
device-local **Anonymous grading** toggle now covers exam mode, which previously
always showed the raw filename stems. Papers are numbered by *position* and
re-shuffled for every question, so a teacher never meets "student 3" twice and no
prejudice can accumulate across a multi-question paper.

- **Server (display-only, `/api/exam/load`).** When `anonymous_enabled()`, the
  payload blanks every display `name` (`name: ""`) and adds an `anonymous: true`
  flag; `key` stays the real stem. `EXAM_STATE` is never mutated (same doctrine
  as the assignment layer's `present_students()`), so `/api/exam/grade`, crop
  serving and the CSV export all keep real identifiers. The grade response
  carries no name field, so nothing leaks there.
- **Client (per-question numbering).** New `EXAM_ANON` flag (from
  `data.anonymous`) plus a deterministic mulberry32 PRNG over a string hash
  (`examStrHash`/`examMulberry32`/`examSeededShuffle`). A single `examView()`
  returns the ordered `{st,label}` pairs that **both** the roster cards and the
  sheet rows iterate, so the two screens always share one order. Anonymous on:
  shuffle with seed `class|exam|CURRENT_Q` and label by position (`01`, `02`, …)
  — stable on reload, different every question, so the same student gets a
  different number each time (a progress counter, not an identity). Anonymous
  off: today's order (server-alphabetical) with real names.
- **Toggle reload.** Flipping the pref now reloads an open exam (`loadExam`) as
  well as an open assignment. The ⚙ Settings note was extended to cover exams
  (positional numbering + real-name exports).

**Backward-compat:** purely a display layer over the existing payload — no change
to `exam_grades_<exam>.json`, crops, or the exported CSV, all of which stay keyed
by the real stem. Residue is unchanged from the assignment layer: the real `key`
still rides the DOM/network and handwriting can identify a student — bias
reduction, not blind review.

---

## 2026-07-13 — Exam grading sheet: current question only + keyword checklist

**What this adds** (Phase 4 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md), decisions D3/D4) — the
exam grading sheet was a wide matrix with a running Total; a teacher live-testing
it noted the visible total biases grading while later questions are still
unmarked, and that exams had no keyword shortcuts the way assignments do. The
sheet is now one question at a time with **no running totals anywhere in the
grading UI**, and the keyword checklist works in exam mode.

- **Single-question sheet, no totals (D3).** `renderExamTable`/`makeExamRow`
  render only `Student | <current question> | Keywords | Comment`; the ✎ adjust
  button stays in the question header, and switching `#questionSelect`
  re-renders. Every running total is gone: the sheet's Total column, the
  roster-card "total X/M" sub-line (now "N/M questions" progress, or
  "ungraded"), and the "N marks total" status line. `examTotal`/`examMaxTotal`
  and their `td.qtotal` CSS were deleted — totals live only in the CSV export +
  CAM. The saved-grades shape is unchanged (scores still keyed per label; the
  sheet just shows one column at a time).
- **Keyword checklist in exam mode (D4).** `#kwEditor` is no longer hidden in
  `loadExam`; the editable pill editor drives exams too. Persistence rides the
  exam grades file — new shape `{"checklist":[{label,type},…], "students":{…}}`
  in `exam_grades_<exam>.json`: `load_exam_grades` now returns
  `(students, checklist)` and `save_exam_grades` round-trips the checklist
  (missing key → the D4 default template via `default_exam_checklist`;
  `normalize_exam_checklist` mirrors `_normalize_checklist`). Each exam student
  gained `keywords` beside `scores`/`comment` (default `[]`). Comment
  composition reuses the assignment `autoComment` helper verbatim.
  `/api/exam/grade` accepts + persists `keywords`; new `/api/exam/checklist`
  persists rubric edits.
- **CSV export.** Appends a `Checked Keywords` column (semicolon-joined) before
  `Comment`, matching the assignment CSV convention. ACM's exam ingest already
  reserves that header (`engine/ingestion.py` `_EXAM_RESERVED`), so questions
  still resolve to Q-columns only.

**Backward-compat:** old `exam_grades_<exam>.json` files without a `checklist`
key load fine (default template) and without per-student `keywords` default to
`[]`; scores are untouched. The D4 default template is `illegible handwriting`,
`more explanation needed`, `wrong format`, `incomplete answer`,
`check calculations` (all type "growth"), editable per exam.

---

## 2026-07-13 — Exam Setup: fit-width / fit-page toggle

**What this adds** (Phase 3 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md)) — the Exam Setup left
pane only ever fit the page to the pane *width*, so a tall scanned page ran off
the bottom and the teacher had to scroll to place the grid. A persistent toggle
now switches between fit-width and whole-page-visible.

- **Fit toggle.** A persistent `#fitToggleBtn` (revealed once a page loads)
  cycles `↔ Fit width` / `⤢ Fit page`; the choice is stored per device in
  `localStorage["gcg_fit_mode"]` (default fit-width, today's behaviour).
- **Fit page.** Adds `.fitpage` to `#pageWrap` (flex-centred) under which
  `#pageImg { width:auto; max-height:calc(100vh - 150px) }`, so the whole page
  is visible in the pane. The grid overlay is `inset:0`, so it follows
  automatically; the Phase 1 label sizing + `applyZoom` re-run on toggle because
  the cell pixel size changes.
- **Zoom interaction.** Swatch-/focus-zoom still works in either fit mode (it's
  a transform on `#pageZoom`). The old restore-view button was repurposed into a
  separate `✕ Reset zoom` button (still `#zoomToggleBtn`, shown only while a
  `ZOOM_RANGE` is active); the fit toggle also clears any active zoom.

**Backward-compat:** purely a programming-time view preference — no change to
saved exam definitions, crops, or grades.

---

## 2026-07-13 — Exam Setup: form ergonomics (Section: label + Max mark entry)

**What this adds** (Phase 2 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md)) — two small setup-form
snags from live testing: the pre-filled "All Questions" default hid the section
box's placeholder so teachers didn't know what it was for, and the `0-3` score
placeholder invited teachers to type a range when only the max mark is needed.

- **Section rows.** `addSectionRow` now shows a visible `Section:` text label
  (new `.seclabel` style) before the name input; the `§` swatch is kept.
- **Max mark entry.** The question column header `Score` → `Max mark`, the
  placeholder/default `0-3` → `3`, `loadExamConfig` fills the raw `q.max` (not
  `"0-" + q.max`), and the hint reads "Max mark is the highest score, e.g. **3**."

**Backward-compat:** the backend `parse_max_score` is untouched — it still
accepts both `3` and `0-3`, so old-style typing keeps working. Displays that
legitimately show a range (the question dropdown's "(0–3)", the sheet header)
are unchanged.

---

## 2026-07-13 — Exam Setup: grid colour picker + big translucent cell labels

**What this adds** (Phase 1 of
[EXAM_GRADING_POLISH_PLAN.md](EXAM_GRADING_POLISH_PLAN.md)) — a teacher
live-testing the slicer couldn't read the coordinate grid over a scanned page:
the muted grey lines and small corner labels washed out. The grid is now
brightly recolourable and its labels are large, centred and translucent.

- **Grid colour picker (per device).** A new `#gridColorSelect` sits beside the
  Grid density dropdown with three high-contrast choices — Neon green `#39FF14`
  (default), Bright blue `#00BFFF`, Bright magenta `#FF00E5`. The choice persists
  in `localStorage["gcg_grid_color"]` (a device preference, *not* part of the
  exam definition) and drives a single `--gridcol` CSS variable on `#gridOverlay`
  that all grid colouring reads.
- **Grid lines.** `.gcell` borders switch from fixed grey to
  `color-mix(in srgb, var(--gridcol) 65%, transparent)` — still `1px dashed`
  (density, not weight, was the complaint).
- **Cell labels.** `.glab` is reworked to fill the cell (`inset:0`, flex-centred),
  `font-weight:800`, `color:var(--gridcol)`, `opacity:.4`, no text-shadow. Size
  is computed from the live cell height by `sizeCellLabels()`
  (`max(9px, round(cellH × 0.55))` → `--glabsize`), replacing the old
  per-density static font-size rules, and recomputed after the page image loads,
  on window resize, and on any paper/density change.

**Backward-compat:** purely a programming-time visual change in the Exam Setup
page — no change to saved exam definitions, crops, or grades. Question-range
highlight tints (`Q_COLORS`) are untouched and stay distinguishable from the
grid colour.

---

## 2026-07-13 — Exam: adjust a question's region during grading + re-slice one

**What this adds** (Phase 6 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)) — mid-grading,
the teacher can nudge one question's coordinate box and re-crop just that
question, without re-processing the whole stack or losing any entered marks.
Reuses Exam Setup (the spreadsheet method) rather than a new editor.

- **✎ entry points (CGW grading screen).** Each exam question column header
  carries a small ✎, and an **✎ Adjust** button sits next to the question
  selector. Both open `/exam_setup?class=..&exam=..&focus=<label>` in a new tab.
- **Focus mode (Exam Setup).** With `?focus=<label>` the page auto-loads the
  exam, scrolls to + highlights that question's row, and **zooms the page
  preview to its cells ±2** (a CSS transform on the new `#pageZoom` wrapper — the
  page's laid-out height is untouched, so `#pageWrap` keeps clipping cleanly). A
  **⤢ Full page** button restores the normal view. Zoom is also available
  outside focus mode by clicking any question's colour swatch.
- **Re-slice one question.** New `POST /api/exam/process_one`
  `{class_name, config, label}` saves the (possibly widened) config, then runs a
  background job — reusing the `EXAM_JOBS` machinery — that crops **only** that
  label for every student. `exam_engine.process_exam` gained a `labels=[...]`
  subset argument; every other question's crops on disk stay byte-identical, and
  scores (keyed by label) are never touched. A **⚙ Re-slice this question**
  button drives it in focus mode.
- **Live crop refresh across tabs.** On completion the setup tab writes a
  `cam_exam_resliced` `localStorage` signal `{class, exam, label, ts}`; the
  grading tab (same origin) hears the `storage` event, bumps a crop-URL
  cache-buster (`&t=<ts>`), and re-renders the roster so the new framing shows
  without a manual reload.

**Backward-compat:** `process_exam(labels=None)` slices everything exactly as
before; renaming a label during adjust stays out of scope. Covered by
`tests/test_exam_reslice.py` (subset slicing, others byte-identical, error paths).

---

## 2026-07-13 — CAM: section-aware exams, Window 3 `?` resolver, name-crop check

**What this adds** (Phase 5 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)) — the CAM
side that consumes the Phase 4 sidecar. An exam can now be split into sections,
including *choice* sections ("answer 2 of 3"), and the raw totals everywhere in
CAM honour the teacher's choice resolutions.

- **Model + persistence.** `Assignment.sections` carries the sidecar structure
  (`[{name, required, questions:[{label, max}]}]`; `None` = legacy
  single-section). `ExamResult.chosen` (`{section: [labels]}`) records which
  answers the teacher picked for an over-answered choice section. Both persist;
  absent → exactly today's behaviour. New pure, unit-tested helpers on the model
  — `section_state`, `resolved_total`, `resolved_max`, `resolved_suggested_band`,
  `exam_is_pending` — compute every section-aware number.
- **Ingest.** `ingest_exam_csv` reads `<csv>.meta.json` (via
  `load_exam_sidecar`), attaches the sections and recomputes each result's
  `max_total` via the resolved rule (a choice section's max = the `required`
  largest question maxes). Re-ingest **preserves** existing `chosen`
  resolutions for labels the student still answered (same spirit as the Late
  reconcile). Missing/corrupt sidecar → unchanged all-questions behaviour.
- **Strict `?` resolution.** An **over-answered** choice section (student
  answered more than `required`) reads `?` and contributes **nothing** to the
  exam total until the teacher resolves it — the app never auto-picks. Window 3
  shows a per-section marks block (`📝 <exam>` → `Section A · 12/20`) with a
  **`?` resolve** button that opens a dialog: tick which answers count (capped
  at `required`), live subtotal, Save writes `ExamResult.chosen`. Re-openable
  any time.
- **Resolved totals everywhere.** Window 1's exam-banding panel, the assignment
  table's `raw ø` chip, and the analytics dialog all use the *resolved* total /
  max and *exclude* pending (`?`) students from class averages; a pending
  student's Apply-band control is disabled until they're resolved in Window 3.
- **Name-crop check (5E).** When CGW sliced a name box, the exam analytics
  dialog shows each ingested row's `__name__` crop beside its student id (read
  read-only from `cam_grading_workspace/exam_crops/<class>/<exam>/__name__/`) so
  a mis-named script is spottable at a glance. Re-keying stays the manual flow.

**Backward-compat:** a legacy exam with no sidecar renders exactly as before —
`resolved_total`/`resolved_max` fall back to the stored `total`/`max_total`.
Covered by `tests/test_exam_resolved.py` and `tests/test_exam_sections_app.py`.

---

## 2026-07-12 — Exam Setup: name box + sections + export definition sidecar

**What this adds** (Phase 4 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)) — the CGW
side of section-aware exams; CAM consumes it in Phase 5:

- **Name box.** An optional per-exam region (`"name_box": "<range>" | null`)
  capturing the handwritten student name. A **+ Add name box** button pins a
  special "Name" row above the questions (its own swatch, a range, no score,
  deletable). `process_exam` slices it to the reserved
  `<exam>/__name__/<Student>.png`; it is **never** a gradable column (it stays
  out of the question list, the grading sheet and the CSV). `save_exam` rejects
  a real question literally labelled `__name__`. These crops are the raw
  material for CAM's mis-named-script check (Phase 5E).
- **Sections.** The config grows `"sections": [{"name", "required"}]` and each
  question gains a `"section"`. A **+ Add section** button inserts a section
  header row (name · numeric "choose N of them" · an "all required" checkbox,
  checked by default, that greys the number); questions belong to the header
  above them and reorder freely. `save_exam` (via `normalize_sections`)
  **guarantees ≥1 section** — a legacy exam with no sections synthesizes one
  default `All Questions` section holding every question — and validates unique
  non-empty names and `required` (null = all, else `1 ≤ required ≤` the section's
  question count).
- **Definition sidecar.** Because the flat CSV can't express sections, every
  routed exam export writes `<csv filename>.meta.json` **before** the CSV, atomic
  and best-effort (a sidecar failure never fails the export). It carries
  `{exam, sections:[{name, required, questions:[{label, max}]}], has_name_box,
  grid, paper_size}`. The **CSV shape is unchanged** — old CAM builds and the
  teacher's own tooling keep working; CAM recomputes choice-section totals from
  the sidecar in Phase 5.

**Backward-compat:** a legacy `gcg_exams.json` entry loads into the setup UI
with the synthesized default section and slices **identically** (sections carry
no pixels; the name box is opt-in). Covered by `tests/test_exam_sections.py`.

---

## 2026-07-12 — Exam Setup: legible grid + per-exam grid density

**Symptom it addresses:** the coordinate grid in **📝 Exam Setup** was hard to
work with. Its cell labels (`.glab`, 9 px, faint grey) and dashed borders were
almost unreadable over a scanned page, and the single ~2 cm cell size (A4
10×15) was too coarse to frame small answers tightly — a two-line answer often
had to spill a whole extra cell in each direction.

**What this change does** (Phase 3 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)):

- **Legibility (CSS only).** Grid labels are now accent-coloured, `600` weight,
  with a two-layer `text-shadow` halo in the page background colour so they read
  on both light scans and the dark theme; the label size scales with cell size
  (13 / 11 / 9 px for legacy / compact / fine) so denser grids never overlap.
  The dashed cell border is denser (`rgba(127,127,127,.65)`).
- **Per-exam grid density.** A new config key `"grid"` selects the grid's cell
  size: `legacy` (~2 cm — the original grid), `compact` (~1.4 cm, the **default
  for new exams**) or `fine` (~1 cm). `PAPER_GRIDS` (`exam_engine.py`) became a
  two-level *paper → density → (cols, rows)* table, mirrored verbatim in the
  Exam Setup JS. `grid_for`, `parse_range`, `range_to_bbox`, `process_exam` and
  `ExamStore.save_exam` all thread the exam's density through.
- **Wider columns.** The densest grid (fine A3) is 30 columns, past the old
  single-letter `A–O` cap, so column names are now Excel-style
  (`col_name`/`col_index`: A…Z, AA, AB, …) and `_RANGE_RE` accepts one or two
  letters, with the real bound enforced by `parse_range` against the grid.
- **Setup UI.** A **Grid** control (Compact / Fine) sits next to Paper size;
  loading a legacy exam reveals a load-only **Standard (legacy 2 cm)** option so
  its coordinates render on the right grid. Switching density re-validates every
  typed range (out-of-range ones flag red) — no silent auto-conversion.

**Backward-compat contract (the important part):** an exam saved before this —
with **no `"grid"` key** — resolves to `legacy` and parses, highlights and
slices to **pixel-identical** crops. `grid_for(paper, grid)` returns the legacy
tuple for it and every threaded call defaults to `legacy`, so nothing about an
old exam's geometry moves. Covered by `tests/test_exam_grid.py`, which pins the
legacy geometry independently and asserts new-vs-old `range_to_bbox` equality.

**Deliberately unchanged:** the exported CSV shape (§A.4) — density affects only
where crops are cut, not the numbers CAM ingests, so CAM needs no change this
phase.

---

## 2026-07-12 — Window 3: generated comment now shows on the same repaint

**Symptom it addresses:** in Window 3's AI comment deck, clicking **Generate
for &lt;student&gt;** (with any API provider) reported success but the
Overall-comment box stayed **blank** — the text only appeared after focusing a
different student and coming back. Worse, on that stale-blank repaint the box's
change-detector saw a mismatch (widget blank vs a just-generated
`llm_response`), treated the blank as a deliberate edit, tripped
`_mark_teacher_input_deleted()`, and wrote the blank back over the generated
comment — a silent wipe, exactly the class of loss the 2026-07-10 comment-wipe
history warns about.

**Root cause:** the box is a keyed `st.text_area`
(`key=resp_box_<sid>_<term>`). Its displayed content comes from the cached
**widget state**, but the generate handler wrote only into
`st.session_state["llm_response"][sid]` and called `st.rerun()` — it never
updated the widget's own key. Streamlit's cached (blank) widget state then won
over the `value=` argument, so the box rendered empty until the key was
re-instantiated by a student switch.

**What this change does** (Phase 2 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)): make the
widget key the single source of truth (the standard Streamlit pattern).

- The `resp_box_<sid>_<term>` key is **seeded once** from `llm_response[sid]`
  only when absent, and the `text_area` renders with **no `value=`** — key
  only. Thereafter the key is authoritative.
- Both generators write the key directly and atomically alongside
  `llm_response[sid]`: the single-student handler on API success (and now
  `persist()`s, since the sync-back no longer fires for a generated comment),
  and the whole-class handler pushes the **focused** student's fresh comment
  into the live widget (other students seed-in when next focused).
- The box's sync-back reads the key; because generation keeps both sides in
  step, a mismatch can now originate **only** from the teacher typing — so the
  deletion tripwire fires only on a genuine manual clear, never on a
  stale-blank rerun.

**Deliberately unchanged:** the Teacher-remarks popover box (`rem_box_<sid>`)
has no generator writing behind it — its `value=`/key pair only ever reflects
the teacher's own typing — so it was left as-is rather than refactored
gratuitously.

---

## 2026-07-12 — sync on export: CGW beacon + CAM poller

**Symptom it addresses:** after grading in CGW and clicking **Export CSV**, the
grades did not appear in CAM Windows 1/2 until the teacher clicked around — and
for exams, often not even then. CAM (Streamlit) only reruns on interaction and
cannot be pushed by CGW (a separate process). The old "sync on export" was only
approximated by `_run_active_launch_probe`: once per rerun, throttled to 30 s,
and watching only the one assignment launched via 🖌 Grade This *this session*.
Exam exports never round-trip, so they got no probe marker at all — an exported
exam CSV sat unseen until the next session-start global scan.

**What this change does** (Phase 1 of
[EXAM_SLICER_V2_AND_SYNC_PLAN.md](EXAM_SLICER_V2_AND_SYNC_PLAN.md)): make a
routed export announce itself, and have CAM listen.

- **CGW writes a beacon on every routed export.** `api_export` and
  `api_exam_export`, in the branch that writes the CSV into the class subfolder,
  now atomically rewrite one `cam_export_beacon.json` in the **root of the cloud
  dir** (`.tmp` + `os.replace`, the `ExamStore._write` pattern) carrying
  `{class_name, assignment, is_exam, csv_path, ts}`. Best-effort: any failure is
  logged and swallowed so a beacon problem never fails the export.
  Download-only exports (`?download=1`, or no cloud dir) route nothing and write
  no beacon.
- **CAM polls the beacon with a `run_every` fragment.** New
  `_export_beacon_poller()` (`@st.fragment(run_every=3)`, called from `main()`
  right after `_run_active_launch_probe()`) does ONE `os.stat` of the beacon
  each tick; an unchanged mtime returns immediately — that stat is the entire
  steady-state cost, and no app rerun ever fires on a no-op. On a change it reads
  the JSON (tolerating torn reads) and runs a **scoped** sync keyed to the
  beacon: `sync_assignment` for grading exports, the new `sync_exam` for exam
  exports — never a full `sync_all` tree walk. Only a real ingest/update (or a
  duplicate refusal) surfaces the banner and `st.rerun(scope="app")`.
- **Scoped exam sync.** New `_exam_csv_paths(class, exam)` mirrors
  `_assignment_csv_paths` but inverts the filter to keep *only* item-level exam
  CSVs; `sync_exam` feeds them through the shared `_sync_one_csv`, so no ingest
  semantics are duplicated (the Late reconcile and purge-replace safety all come
  along unchanged — a new trigger, not new behaviour).

**Deliberately unchanged:** `_run_active_launch_probe` stays as belt-and-braces
for multi-machine OneDrive arrivals (the beacon file syncs through OneDrive too,
but with cross-device clock skew). The beacon lives in the data folder (outside
git); registry/scans only look at `*.csv`, so it can never be mistaken for a
gradebook file.

Covered by `tests/test_export_beacon_sync.py` (7 tests): `_exam_csv_paths`
keeps only the matching exam and hides grading exports; `sync_exam` ingests one
exam's results and is idempotent on re-run; the quiet no-op with no DB path; and
the CGW beacon writer's exact JSON shape, atomicity, exam flag, and no-cloud-dir
guard.

---

## 2026-07-12 — one design language across the deliverables tray

**Symptom it addresses:** the five tray deliverables looked like they came from
different apps. The Excel master's tabs 1–3 ("Final Suggestions", "Raw Scores",
"Assignments") were bare `ws.append` rows — no fonts, fills, widths, or freeze
panes — while tab 4 ("Classroom Entry") was fully styled in a standalone office
**navy** (`1F4E78`) that matched neither the others nor the app. The Word
reports used python-docx defaults with no shared identity.

**What this change does** (Phase 4 of
[UI_AND_DELIVERABLES_POLISH_PLAN.md](UI_AND_DELIVERABLES_POLISH_PLAN.md)):
standardise every deliverable on the app's **own brick-red light theme**
(`.streamlit/config.toml`), not the generic navy.

- **Shared openpyxl style kit.** New module-level palette constants plus
  `_xl_style_kit()` (reusable Fonts/Fills/Borders/Alignments) and helpers
  `_style_header_row()` / `_finish_sheet()`, keyed to the theme: `B3554D` brick
  header band with white bold text, `DDDAD3` warm-grey sub-header with `9C4A43`
  bold text, `E9E7E2` label-column fill, `C6C2B9` thin borders, Arial throughout
  (matches tab 4, universally available in Excel/Word).
- **All four Excel tabs now share the system.** Classroom Entry is restyled from
  navy to the kit (same structure, new colours). Final Suggestions gets a header
  band, ID/Name on the label fill, centred grade cells, and freeze `C2`; Raw
  Scores gets a header band, a wide wrapped Comment column, soft warm-grey zebra
  striping, and freeze `A2`; Assignments styles its 4-row class/subject/term
  block as a title card, then a header band + table with freeze `A7`. Gridlines
  off and column widths on all.
- **Word pass (typography, not layout).** `_apply_report_styles()` — called from
  `_new_report_document()`, so the report-card pack, single report, mail-merge
  ZIP, and class-comments doc all inherit it — sets the base style (Arial
  10.5 pt, `38352F`) and brick heading styles (`B3554D` H1 / Title, `9C4A43`
  H2/H3), with a thin warm-grey rule under the H1 page title.

**Deliberately unchanged:** styling only — no deliverable's *content* changes.
Excel data values are byte-for-byte what they were, so the Classroom Entry
paste-back workflow keeps its exact shape and its Latin first-name ordering; the
report documents keep the same paragraphs, tables, and page breaks; the
matplotlib trend PNG (`_trend_png`) is untouched.

Covered by `tests/test_deliverable_style.py` (10 tests): the kit palette,
save/reload round-trips of the two helpers, the tab-4 restyle with paste-back
data left intact, and the docx base font / heading colour. A sandboxed build of
all five deliverables confirms every Excel tab reloads with header fill
`B3554D`, gridlines off, and freeze panes set, and every Word doc opens with
Arial body text and the brick accent.

---

## 2026-07-12 — per-class roster name order (4 modes)

**Symptom it addresses:** the roster was always sorted one way — hiragana
gojūon order, applied once at upload. A teacher who wanted their class list in
plain A–Z (by surname or by first name) or by email had no way to ask for it;
the stored roster order *is* the display order, so it also fixed the ordering of
Window 2 and every export that follows the roster.

**What this change does** (Phase 3 of
[UI_AND_DELIVERABLES_POLISH_PLAN.md](UI_AND_DELIVERABLES_POLISH_PLAN.md)):

- **New per-class setting `roster_order`** stored in the shared database class
  dict, with four values: `"gojuon"` (surname→given reading; the historical
  default), `"last_first"` (Latin surname, then first name), `"first_last"`
  (Latin first name, then surname), and `"email"`. The key is additive — absent
  → `"gojuon"`, so no migration and old databases keep behaving as before. It is
  DB-stored (not a device pref) so the choice follows the data across machines.
- **Generalised sorter.** `sort_roster_gojuon` is replaced by
  `sort_roster(entries, mode)`, which shares the surname-peeling logic (the
  stored name is "Surname First"; the given name is peeled off the end, keeping
  multi-token surnames intact) via a new `_split_surname_given` helper. Email
  mode sorts on the roster email, falling back to the match key for legacy
  safety. `sort_roster_gojuon` remains as a back-compat alias; a new
  `active_roster_order()` reads the active class's mode.
- **Settings UI.** ⚙ Settings gains a "**Roster name order**" section (its own
  form, immediately above "Report-card grades") naming the active class and the
  four modes. Saving writes the class key, re-sorts the stored roster in place,
  and persists.
- **Upload path.** Applying a Google Classroom roster now sorts by the active
  class's mode instead of hard-coded gojūon; the uploader caption names the
  current order.

**Deliberately unchanged:** the Excel **Classroom Entry** tab still re-sorts to
Google Classroom's own Latin first-name order regardless of this setting, so a
pasted column still lines up row-for-row. Re-ordering the roster is display-only
and grade-safe — every mark is keyed by student ID, never roster position, so a
re-sort never disturbs anyone's grades. ↑/↓ fine-tuning survives until the next
re-sort (a setting change here or a fresh roster upload).

Covered by `tests/test_roster_order.py` (14 tests): all four modes on names
whose orderings diverge, surname-peeling edge cases, and an invariant that the
Classroom Entry tab order is independent of `roster_order`.

---

## 2026-07-12 — stop Chrome offering student names in unrelated fields

**Symptom it addresses:** the teacher saw previously-typed **student names
suggested in the "Grade level" field** of the class dialog. This was Chrome's
own form-autofill history, not CAM state: none of the app's `st.text_input`
calls set an `autocomplete` attribute, so Chrome keyed its typed-value history
across similar anonymous fields. Names typed once into the ➕ Add student dialog
then leaked into any text box. Any teacher on Chrome could get their own history
leaked across fields the same way.

**What this change does** (Phase 2 of
[UI_AND_DELIVERABLES_POLISH_PLAN.md](UI_AND_DELIVERABLES_POLISH_PLAN.md)):

- Every `st.text_input` in `app.py` (14 call sites) now passes
  `autocomplete="off"` (Streamlit 1.58 supports the kwarg). `st.text_area` and
  `st.number_input` are left alone — Chrome doesn't offer history dropdowns on
  textareas or spinner inputs.
- Free-text `<input>` fields in the grading workspace
  (`cam_grading_workspace/app.py`: `newKw`, `folderInput`, `examName`, and the
  dynamically-built `qlabel`/`qrange`/`qscore` cells) also get
  `autocomplete="off"`. `type="file"`/`checkbox`/`range`/`datetime-local` and
  the read-only `cloudDirInput` are untouched.

**Caveat:** Chrome sometimes ignores `autocomplete="off"` for fields it
heuristically classifies as address-like; this change kills the common case.
Existing polluted history clears itself as entries expire, or the teacher can
delete a stray suggestion with **Shift+Delete** while it's highlighted.

Attribute-only change; nothing about CAM state or what any deliverable contains
changed.

---

## 2026-07-12 — compact email chip in the Evaluation Cockpit (Window 3)

**Symptom it addresses:** Window 3 rendered the focused student's roster email as
a full-width `st.code` block stacked directly under the name heading. The
click-to-copy was useful, but it cost a whole extra row in an already very long
window.

**What this change does** (Phase 1 of
[UI_AND_DELIVERABLES_POLISH_PLAN.md](UI_AND_DELIVERABLES_POLISH_PLAN.md)):

- `render_window3` (`app.py`) now puts the name heading and the email on **one
  line**: `st.columns([3, 2], vertical_alignment="bottom")` with the
  `### name` heading in the left column and the existing
  `st.code(_email, language=None)` in the right, wrapped in a keyed
  `st.container(key="w3_email_chip")` so CSS can target it. The native copy icon
  is preserved.
- The static CSS block (`theme_css` neighbourhood, `app.py`) gains
  `.st-key-w3_email_chip` rules that shrink the code block into a compact pill:
  `font-size 0.72rem`, `padding 2px 8px`, zeroed margins, `width: fit-content`
  pushed right with `margin-left: auto`. `max-width: 100%` lets a long email
  truncate/scroll inside its column rather than pushing the heading.
- **No email on the roster → the heading renders full-width exactly as before**
  (no empty chip).

Layout/CSS only; nothing about what any deliverable contains changed.

---

## 2026-07-12 — explicit term backup & restore (disaster-recovery for one whole term)

**Symptom it addresses:** the cloud mirror (below) gives every human-typed input
a durable twin that self-heals on load, and the rotating `.bak-auto` snapshots
guard the file itself — but neither is a snapshot the *teacher* deliberately
made and controls. A teacher wanted an end-of-term artifact they could keep in a
folder of their choosing (a USB stick or a non-cloud folder for an off-site
copy) and, after a database disaster, put one term's data back wholesale. This
is the **third line of defence** behind mirror-heal and the `.bak` files.

**What this change does** (full plan in
[TERM_BACKUP_RESTORE_PLAN.md](TERM_BACKUP_RESTORE_PLAN.md)):

- **Scope is by term tag, never by dates.** Every assignment already carries its
  term, so a single stable predicate (`_term_of_assignment` — blank/legacy tags
  resolve to `TERMS[0]`, independent of the active term so a backup and a later
  restore always agree) partitions the gradebook. The loader touches only rows
  tagged with the backup's term and leaves every other term byte-identical
  (asserted in tests). Date-range scoping was rejected — it would inherit the
  known dup-dated-CSV / deadline-edge hazard class.
- **Backup is zero-risk** (`build_term_backup` / `write_term_backup`, `app.py`).
  ⚙ Settings → **🗄 Term backup & restore** → pick a folder + term → writes one
  self-describing `cam_term_backup_<term-slug>_<YYYYMMDD-HHMMSS>.json` (atomic
  tmp + `os.replace`) containing that term's assignments, scores, exam results,
  overall comments, effort, active-map, calc-method pins and late/excused flags,
  plus the (not-term-scoped) teacher remarks and final overrides for reference.
  A `counts` header lets the restore dialog show its dry-run diff without parsing
  the payload twice. It only ever writes **outside** the database.
- **Restore is a disaster tool, not an editing tool** (`restore_term_backup`).
  It **replaces the term's slice wholesale** behind three gates: a **dry-run
  diff** (`diff_term_backup`, writes nothing — per class: comments newly filled
  vs. those that would overwrite a *different* current comment, assignments the
  backup adds vs. live ones it would remove, and backup-vs-live score counts), a
  **loud staleness warning** showing the backup's `created_at` ("changes made to
  {term} after this are NOT in the file and will be lost"), and a **typed
  confirmation** (`RESTORE {term}` exactly, matching the Danger-zone wipe
  pattern). An automatic `acm_database.json.bak-pre-term-restore-<stamp>` (never
  pruned) is written **before** any mutation.
- **Restore semantics** (§4 of the plan): term-tagged data is deleted then
  replaced — *including removing term-tagged rows that exist live but not in the
  backup* (they postdate it; the warning and diff cover this). The two
  non-term-scoped maps (`teacher_remarks`, `final_override`) are **filled for
  blank slots only**, so restoring Term 1 never clobbers a Term 2 remark. Other
  terms are never touched. The single closing `persist(allow_shrink=True)` is the
  shrink-tripwire's exempt, typed-confirmed path; it seeds the mirror-deletion
  flag and clears the per-class fingerprints so the restored comments re-mirror
  to their cloud twins and the tripwire doesn't mistake the restore for a mass
  deletion.
- **Engine** (`engine/persistence.py`): added public per-record serializers
  `score_to_dict`/`from_dict`, `assignment_to_dict`/`from_dict`,
  `exam_result_to_dict`/`from_dict` (exported from `engine/__init__.py`) so the
  backup stores per-class, per-student score lists in the exact on-disk shape
  `serialize_gradebook` produces, instead of re-deriving it.

**Verified:** stdlib `unittest`, all green — `tests/test_term_backup.py`
(17 cases: build scoping incl. exam results, validation refusals for
malformed/wrong-kind/wrong-version/unknown-term, lossless backup→wipe→restore
round-trip, other-term byte-invariance, live-only-assignment removal, no
duplicate scores on restore-over-live, fill-blanks-only remarks/overrides, and
the pre-restore `.bak` bytewise-equals the pre-restore DB). The existing suite
(`test_class_mirror`, `test_app_mirror`, `test_app_heal`) stays green. All runs
sandboxed to a temp folder — no real data folder is ever touched
([CLAUDE.md](../CLAUDE.md) rules). Run: `python -m unittest tests.test_term_backup`.
The backup file holds the teacher's own gradebook slice; like the cloud mirror
it is written only to disk, never committed — the git separation is preserved.

## 2026-07-11 — comment & teacher-input cloud mirror (durable twin of human-typed content)

**Symptom it addresses:** the 2026-07-10 DB wipe
([CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md))
destroyed every AI-generated report comment and every other human-typed input.
Grades self-heal — Sync rebuilds scores from each class folder's export CSVs —
but content that lives only in the DB session had **no cloud twin and could not
be rebuilt**: `comments_by_term`, `teacher_remarks`, `effort_by_term`,
`final_override`, and CAM-side score comments. Losing Term 1 comments also
silently degraded later terms, whose prompts fold in the previous term's
`[PREVIOUS TERM FINALIZED SUMMARY]` blocks. Root cause was **dead code, not
missing architecture**: the per-class cloud-summary read path was fully wired,
but the write path died when the Finalize button was removed, so nothing ever
called `save_term_summary` and no `acm_term_summaries_*.json` files existed.

**What this change does** (full plan + verified anchors in
[COMMENT_CLOUD_MIRROR_PLAN.md](COMMENT_CLOUD_MIRROR_PLAN.md)):

- **Engine — payload v2** (`engine/persistence.py`). Extended the per-class
  summary file into a full teacher-input mirror with five sections (`terms`,
  `remarks`, `effort`, `final_override`, `score_comments`). New
  `load_class_mirror` / `save_class_mirror` (canonical 5-section shape; v1 files
  load transparently with the new sections empty). `load_term_summaries` is now
  a thin `{term: {sid: comment}}` view over the full loader, and
  `save_term_summary` loads-merges-saves so it **preserves** the new sections
  instead of clobbering them — public names unchanged. Same atomicity
  (tmp + `os.replace`) + blank-dropping; `effort`/`final_override` coerce to
  whole ints. Never raises; malformed/non-dict → all-empty mirror.
- **Write path — mirror on autosave** (`app.py`). `build_class_mirror(cls)`
  assembles the v2 slice from session state + gradebook scoped to that class's
  sids (roster **plus** archived students, so a departed student's comment still
  earns a twin and archiving never trips the tripwire).
  `_mirror_classes_to_cloud()` runs from `persist()` after a successful DB write
  under four non-negotiable invariants: **heal-before-mirror + no-quarantine**
  (a wiped/demo session can't push its emptiness over good files),
  **shrink tripwire** (refuse a rewrite that would halve a term's comment count
  unless comments were explicitly deleted in-app this session),
  **no-churn per-class fingerprint** (skip identical rewrites — these folders are
  OneDrive-synced), and **never-raises** (per-class try; refusal surfaces on
  `save_status`). Also dropped the `llm_response` duplicate from the session
  payload (~11% DB size cut) since the loader already prefers `comments_by_term`.
- **Read path — heal on load** (`app.py`). `_heal_from_class_mirrors()` runs in
  boot hydrate right after `restore_session` (before the first mirror write),
  filling **blank slots only** — session text always wins where both are
  non-blank; effort heals on presence so a set `0` is never re-healed away.
  `_heal_score_comments_from_mirrors()` runs after Sync's purge-replace to refill
  blank `sc.comment` slots. `_seed_mirror_fingerprints()` seeds the no-churn
  fingerprint for classes whose twin already matches, so a pure heal doesn't
  rewrite an identical file — while a class with a missing/staler twin (the
  incident's root cause) is left unseeded, so the first `persist()` backfills its
  first-ever cloud twin.
- **Window 3 — student email under the name** (`app.py`, `render_window3`).
  Below the student name, the roster email now renders via
  `st.code(email, language=None)` — a compact single line with a native copy icon
  for pasting into report tools or an email client. Blank email (not on the
  roster) renders nothing.

**Verified:** engine + app-level unit tests, stdlib `unittest` (no pytest in this
env), all green — `tests/test_class_mirror.py` (v2 round-trip, v1 back-compat,
malformed→`{}`, blank-dropping, atomic replace), `tests/test_app_mirror.py`
(slice scoping + archived capture, first-boot backfill, no-churn mtime untouched,
not-ready/quarantined writes nothing, shrink tripwire blocks mass loss / deletion
flag lets it through, never-raises), `tests/test_app_heal.py` (wiped maps refilled
incl. effort-0, session text wins, in-app deletion not resurrected, score-comment
refill, matching-twin seeded→no churn, missing/richer→backfill). Run:
`python -m unittest tests.test_class_mirror tests.test_app_mirror tests.test_app_heal`.
The teacher-input mirror is session-only human-typed content, never real student
identity data — the git separation in [CLAUDE.md](../CLAUDE.md) is preserved.

## 2026-07-11 — audience reframe + Gyoshu-specific report grades made optional

**Symptom it addresses:** two things blocked a clean public release. (1) The docs
pitched CAM as a tool "for IB MYP **Arts** teachers," which undersells it — the
app grew from artwork grading into a Google-Classroom grading + reporting toolkit
useful to any MYP teacher, and the exam-slicing workflow helps any subject. (2)
Three report-card figures — **MYP Grade (1–7)**, **Effort / English-use**, and
**School Grade (1–10)** — are Gyoshu report-card conventions, not universal, yet
were always shown, so every public user saw school-specific fields they don't use.

**What this change does:**

- **Docs reframed** (`README.md`, `docs/USER_MANUAL.md`, `docs/ARCHITECTURE.md`).
  CAM is now described as being for **IB MYP teachers who use Google Classroom**,
  with the origin story (artwork grading of images/video → PDFs and Google Docs →
  exam slicing for all subjects) and the OAuth caveat spelled out: Google Docs
  grading needs OAuth, so a plain local folder grades PDFs. The `engine/`
  docstrings ("MYP Arts criteria A–D") were left as-is — they describe the grading
  model CAM actually computes, not the audience.
- **The three report grades are now opt-in**, gated by a new shared config
  `st.session_state["report_cfg"]` (`show_myp_grade`, `show_effort`,
  `show_school_grade`, plus a configurable `effort_min`/`effort_max` range). It
  round-trips in the DB session payload exactly like `llm_cfg` (merge over defaults
  on restore), so the choice follows the teacher across devices. **All three
  default OFF** — a fresh/public install reports only the criterion A–D grades.
- **New ⚙ Settings → Report-card grades panel** (own form, `persist()` on save)
  holds the three toggles and the Effort range.
- **Scope of an OFF toggle:** the figure is still computed, stored, and kept in the
  **CAM master Excel export** (unchanged). It is withheld only from the
  student-facing surfaces — the Window 3 chips and every DOCX report (individual,
  combined pack, mail-merge ZIP), all gated at the one `_student_docx` chokepoint.
  The LLM comment prompt never injected these figures, so it needed no change.
- **Effort range plumbing:** `effort_bounds()` + `student_effort()` clamp the score
  into the configured range; the Window 3 selectbox offers `range(min, max+1)`. The
  banded lookup tables (`MYP_GRADE_BOUNDS` / `SCHOOL_GRADE_BOUNDS`) stay hard-coded
  school policy — only visibility and the Effort range are user-configurable.

Verified with a `CAM_DB_PATH`-sandboxed launch on the fictional sample: default
boot showed no report-grade chips; with `report_cfg` all-on (effort 1–8) the
sample student showed Effort 4 / MYP 6 / School 8, confirming persist → restore →
display and the lookup math.

## 2026-07-11 — remote-history hygiene: verified clean + footgun defused (safety plan Phase 6)

**Symptom it addresses:** the old *private* history (real student export
`Changing Views (Crit B)_Grades.csv` and the teacher's Gmail in `MY_IDENTITIES`)
was once pushed to the same GitHub URL now used by the public repo; force-pushing
the clean snapshot over it leaves those old objects unreachable but fetchable by
SHA until GitHub garbage-collects. A second hazard was a local footgun: the old
checkout pointing `origin` at the public URL, one stray `git push --force` from
republishing everything.

**What this change does (no app code — repo/history hygiene + verification):**

- **Verified the public history is clean.** Across all 8 commits: no `.csv`,
  `credentials.json`, `client_secret_*.json`, `token.json`, or
  `local_device_prefs.json` in any tree; `MY_IDENTITIES` empty in source; and no
  match for the teacher's Gmail address anywhere in history.
- **Removed a self-defeating verification.** The plan doc's own check
  (`git log -S <local-part>`) previously embedded the raw search token, so the
  document was the sole match forever. The token is now referenced indirectly, so
  a non-empty result again means a real leak.
- **Confirmed the local footgun is already defused.** The old private checkout
  `C:\Project\criterion-assessment-metrics` now has **no git remote or upstream**
  — a stray push there fails with no destination. No repoint needed; it stays
  remote-less.
- **Left the one remaining step to the teacher.** Deleting/recreating the GitHub
  repository requires the teacher's GitHub account and is a destructive,
  outward-facing action an assistant must not perform; the plan's Phase 6 §
  carries the exact handoff steps and post-recreate verification.

## 2026-07-11 — CGW: identities + credentials heal from the cloud (safety plan Phase 5)

**Symptom it removes:** bringing the grading workspace (CGW) to a second computer
still meant hand-carrying three device-local files — `local_device_prefs.json`
(so the app knows which Drive accounts are *yours* and doesn't file your own
uploads under a student), `credentials.json` (the OAuth client secret), and a
fresh browser sign-in (`token.json`). Commit `15073c5` had already moved the
teacher identities out of tracked source into device-local prefs for privacy, but
portability was untouched: a new machine with only the shared OneDrive/Drive
folder still misattributed the teacher's files and couldn't authenticate.

**Fix (CGW `cam_grading_workspace/app.py`), extending the existing
`gcg_settings.json` cloud-mirror + order-of-authority load:**

- **Identities heal from the cloud mirror.** `my_identities` is now a third field
  in `SETTINGS` (`_read_settings_file` parses it, `save_settings` mirrors it into
  `<cloud_dir>/gcg_settings.json` alongside the class map). `load_settings()`
  takes the **union** of the root and cloud copies — unlike the class map (where
  the cloud copy wins), an identity is an allowlist entry whose *absence*
  misattributes the teacher's own work, so neither machine's list is ever dropped.
  `my_identities()` merges the (empty) public default + `SETTINGS["my_identities"]`
  + the device-local prefs list, de-duplicated case-insensitively
  (`_dedupe_identities`). A new machine that only knows the cloud dir already has
  the identities — zero copying. Tracked source stays empty.

- **Editable in the Settings panel.** The workspace's ⚙ Settings dialog gains a
  *My identities* textarea (one per line) with a **Save identities** button that
  POSTs to `/api/config` (`my_identities` accepted + de-duped there, cache
  invalidated), so the value lands in both the root and cloud `gcg_settings.json`.
  No more hand-editing JSON to set who "me" is. `cloud_dir` + the class map stay
  read-only (CAM-managed) — only identities became editable.

- **Client secret from the cloud dir.** `find_client_secret()` now probes
  `<cloud_dir>/credentials.json` / `client_secret_*.json` **after** the app-root
  candidates, so a machine with only the shared folder can authenticate. An
  installed-app client secret is low-sensitivity (useless without a browser
  consent); `.gitignore` excludes both name shapes regardless.

- **Opt-in `token.json` bootstrap (off by default).** New device pref
  `token_bootstrap`: when on and the local token is absent, `get_credentials()`
  seeds it once from `<cloud_dir>/token.json` (`_maybe_bootstrap_token()`), saving
  a browser round-trip on a new machine. It is a **one-way** seed — refreshes keep
  writing locally only; this app never mirrors the token back to the cloud. A
  Settings toggle exposes it with the tradeoff stated (the token grants
  `drive.readonly` to anyone who can read the cloud folder — the teacher's call).

New keys: `my_identities` in `gcg_settings.json` (root + cloud, both git-ignored);
`token_bootstrap` (bool) in CGW `local_device_prefs.json`. Verified by a sandboxed
harness (temp cloud dir, no real token/OAuth): identity union + `is_me`, client
secret discovery order, one-way token seed + idempotency, and the `/api/config`
identity round-trip through root + cloud mirror.

## 2026-07-11 — cross-device bootstrap: first-boot setup panel + CAM_DB_PATH (safety plan Phase 4)

**Symptom it removes:** bringing CAM to a second computer meant hand-copying the
device-local `local_device_prefs.json` to point the new machine at the shared
cloud database — and if you launched without it, CAM silently booted the sample
gradebook while pointed at (blank →) the repo path, exactly the kind of "fresh
demo session pointed at real data" that the wipe incident grew from. There was
also no override a test/harness could set that was *guaranteed* not to fall
through to the real prefs.

**Fix (CAM `app.py`), two convenience mechanisms sitting on top of the Phase 1–3
safety guards:**

- **First-boot setup panel.** A machine that has not chosen a data home — no
  `CAM_DB_PATH`, a **blank** `db_custom_path`, and the new one-time `setup_done`
  pref unset (`_needs_first_boot_setup()`) — now gets a one-time **setup panel**
  (`_render_first_boot_setup()`) *instead of* the cockpit. `init_state()` defers
  the boot hydrate and `main()` returns before any class/term context, sync,
  dedupe or autosave runs, so **nothing is loaded or persisted before the teacher
  picks** (it can never boot the sample DB onto an unchosen machine). The panel
  offers: **discovered databases** — a shallow (depth ≤ 3), system-dir-pruned
  walk of the local OneDrive / Google Drive / Dropbox roots
  (`discover_db_candidates()` → `_cloud_search_roots()` + `_scan_for_db_files()`),
  each listed with its assignment/roster/class counts (`_db_file_counts`) so the
  real one is recognisable; a **manual folder/path** (USB, network share, any
  unlisted location); and an explicit **Start fresh** (sample data). Every choice
  routes through `_adopt_db_path()`, which commits the pref + `setup_done` and
  clears `db_loaded` so the hydrate re-runs on **Phase 2's adopt path** — an
  existing DB at the chosen location is **loaded, never overwritten**; an absent
  one is created on first save. Removable/USB roots are deliberately **not**
  auto-scanned; they are pointed at once via *Use another folder*, and Phase 1's
  storage-missing quarantine protects every later boot when the drive is gone.

- **`CAM_DB_PATH` environment override.** Checked before the pref in `db_path()`
  (same folder-or-`.json` resolution). A one-liner new-machine setup, and — because
  it **cannot** fall through to the real device prefs — the safe way for tests and
  harnesses to pin a sandbox path that can never resolve the teacher's real data
  folder. This closes the `.wiped-by-test` hazard class.

**Watch folders need no new transfer mechanism.** A class's `master_dir` /
assignment `folder_ref` are Google Drive IDs stored in the **shared** database, so
Drive-backed classes travel with it automatically; a **local-path** master is
per-machine by nature and uses the existing re-link flow (**✎ Add / Edit class**).
Layout prefs stay per-device by design. New pref key: `setup_done` (bool) in
`local_device_prefs.json`; "Start fresh" sets it while keeping `db_custom_path`
blank, so the panel never reappears. Established machines (a non-blank
`db_custom_path`) boot exactly as before.

## 2026-07-11 — persist() shrink tripwire + rotating daily backups (safety plan Phase 3)

**Symptom it prevents:** the persistence layer mirrors every in-memory change
straight to disk after each mutation, so *any* future path that leaves the
session holding far less than the database on disk — a demo/quarantine session, a
half-loaded state, a bug in a bulk operation — would silently overwrite a whole
year of grades with a fraction of it. Phases 1–2 close the two known wipe
mechanisms; this is the catch-all behind them so a *novel* mass-loss write can
never destroy the only copy.

**Fix (CAM `app.py`), two independent guards in `persist()`:**

- **Shrink tripwire.** Before each write, a cheap structural **mass** —
  `assignments + roster entries + scored students` — of the outgoing session is
  compared against the file already on disk (`_ondisk_mass()` reads it straight
  from the raw JSON, no engine-object rebuild, so it is light enough to run on
  every autosave). When the on-disk DB has real substance
  (`≥ SHRINK_MIN_ASSIGNMENTS` = 10 assignments) **and** the outgoing mass would
  fall below `SHRINK_KEEP_RATIO` (33%) of it, the write is **refused**: the
  outgoing payload is parked as `acm_database.json.blocked-<ts>`
  (`_park_blocked_payload`, via the engine's atomic writer) and the same
  `db_load_blocked` read-only quarantine banner Phase 1 raises is shown (new
  reason `"shrink-blocked"`). The threshold is deliberately generous — deleting
  one class of several still clears it (`delete_class()` uses a plain `persist()`
  and passes), while flattening every class to the demo gradebook does not.
- **Rotating daily backups.** The **first** successful persist of each calendar
  day copies the existing on-disk DB to `acm_database.json.bak-auto-<YYYYMMDD>`
  **before** it is overwritten (`_rotate_daily_backup`), keyed by today's date so
  it fires once per day and survives restarts, pruned to the newest
  `AUTO_BACKUP_KEEP` (7). Turns any future incident into a ≤1-day loss even
  without OneDrive version history. Pruning only ever removes `.bak-auto-*`;
  manual `.bak-replaced-*` / `.bak-<purpose>-*` snapshots are never touched.

**Deliberate reductions bypass the tripwire** via a new
`persist(allow_shrink=True)` — the Danger-zone **Wipe entire database**
(`wipe_database_full()`) and the Phase-2 **Replace** button (already checkbox-
gated and `.bak-replaced-` backed-up); both are exactly the mass loss the
tripwire exists to catch, so they opt out after their own typed confirmation. The
daily `.bak-auto` snapshot inside `persist()` still captures the pre-wipe DB.
Every other caller (autosave included) leaves `allow_shrink` False.

Once the tripwire fires, `persist()` refuses every subsequent write (the
`db_load_blocked` guard) until the teacher restarts — on restart the healthy
on-disk DB reloads untouched. `.gitignore` gains `acm_database.json.blocked-*`
(the `.bak-*` pattern already covers the auto backups).

Sandbox-verified (23-check harness, fake Streamlit + temp data home, never real
prefs): mass math and the shrink decision (demo-over-rich trips, rich-over-rich
and a 75%-mass single-class deletion pass, a `<10`-assignment DB is never
guarded, an absent target creates freely); `persist()` blocks the demo-over-rich
overwrite leaving the on-disk file byte-identical, parks a `.blocked-*`, sets the
quarantine flag, and refuses follow-up writes; `allow_shrink=True` writes the
reduction through with no quarantine; a normal growth edit persists; and the
daily backup creates exactly one dated `.bak-auto-*`, is a no-op on the same-day
second call, prunes to 7 keeping the newest, and never removes a manual `.bak-*`.
Byte-compiled clean. This completes the safety core (Phases 1–3); Phases 4–5
(cross-device bootstrap, CGW cloud-healing) remain — see
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

## 2026-07-11 — Settings path change adopts the existing database, never overwrites it (safety plan Phase 2)

**Symptom:** the cross-device setup flow — fresh boot (demo `Class 1`) → open
**⚙ Settings**, point *Custom Database Path* at the OneDrive folder → **Save** —
silently replaced the real cloud `acm_database.json` with the demo session. The
existing database at the new path was never loaded and never backed up.

**Cause (wipe mechanism 1).** On Save, `settings_dialog` (`app.py`) wrote the
device prefs and then called `persist()` unconditionally — mirroring the current
in-memory session to whatever file already sat at the new path. Pointing at an
existing database therefore *overwrote* it instead of *adopting* it.

**Fix.** Save now distinguishes adopt from overwrite:

- When Save **changes** `db_custom_path` and the new resolved path **already
  holds a readable** `acm_database.json`, CAM no longer persists. It shows an
  adopt-vs-overwrite panel (`_render_db_switch_panel`) reporting the target
  file's assignment / roster / class counts (`_db_file_counts`):
  - **📥 Load** (default) — reset `db_loaded` and re-run the boot hydrate so the
    session becomes the existing database. Nothing on disk is written. This is
    what "point my new PC at my cloud DB" means.
  - **♻ Replace** (explicit, gated by a confirm checkbox) — snapshot the target
    to `acm_database.json.bak-replaced-<YYYYMMDD-HHMMSS>` (`_backup_replaced_db`)
    **first**, then persist the current session. Never silent.
  - **Cancel** — clear the decision and close; nothing is loaded or written.
- **Unchanged path** (layout-only Save) or a **new location with no database
  there** keep today's behaviour: `persist()` saves / creates the file.

**Extra hardening beyond the plan — the deferred path-pref commit.** The new
`db_custom_path` is written to `local_device_prefs.json` **only** when the
teacher chooses **Load** or **Replace**. While the switch panel is open — and if
it is dismissed with **Cancel** or **ESC** — the active pref stays on the *old*
location, so `db_path()` still resolves there. This closes an otherwise-subtle
hole: had the pref been committed at Save time, an ESC-dismissed panel would
leave the demo session pointed at the existing database, and the next autosave
(`persist()` fires after every mutation) would overwrite it — reopening wipe
mechanism 1 through the back door. `resolve_db_path()` was split out of
`db_path()` so the panel can resolve and inspect the *candidate* path without
mutating the active pref.

Sandbox-verified (rich DB adopted read-only and byte-identical after; explicit
overwrite writes exactly one `.bak-replaced-*` preserving the rich content
before the demo session lands; unchanged-path and absent-file paths bypass the
panel) and byte-compiled clean. Phase 3 (`persist()` shrink tripwire + rotating
backups) is the remaining safety-core piece — see
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

## 2026-07-11 — Boot load-guard: never run demo state against a real database (safety plan Phase 1)

**Symptom:** moving CAM to a second computer left the shared cloud database
`acm_database.json` overwritten — Crit D rows gone, folder assignments demoted
to manual, watch folders missing. The file had been silently replaced by a
fresh demo session that then autosaved on top of the real data.

**Cause (wipe mechanism 2).** `load_database()` returns `None` for an **absent**
file *and* for a **present-but-unreadable** one (a malformed JSON save, a
transient lock, or a OneDrive Files-On-Demand placeholder that hasn't finished
downloading). The boot hydrate (`app.py`) could not tell the two apart, so an
unreadable real database looked like "no database yet": the app started on the
`init_state` demo gradebook **still pointed at the same path**, and the next
`persist()` — which fires after every mutation — clobbered the real file. A
configured path on missing storage (unplugged USB, unmounted cloud folder,
reassigned drive letter) hit the same path and could receive a fresh empty DB.

**Fix.** A boot load-guard that refuses to run demo state onto a real DB:

- New `db_file_state(path) -> "absent" | "ok" | "unreadable"` in
  `engine/persistence.py` restores the absent-vs-unreadable distinction
  (`load_database`'s `None` contract is unchanged for existing callers).
- `diagnose_db_load()` (`app.py`) runs at boot: **unreadable**, **empty-but-
  heavy** (parses to zero students/assignments yet `> EMPTY_DB_MAX_BYTES`), or
  **absent-with-missing-parent-folder/volume** each set
  `st.session_state["db_load_blocked"] = {reason, path}` instead of proceeding.
  Only an absent file inside an **existing** folder is treated as a legitimate
  first run (start empty, create on save).
- While quarantined, `persist()` **refuses every write** and a full-width
  read-only banner names the path and the fix (repair the file/path, restart).
  Real data on disk is never touched.

Sandbox-verified (corrupt JSON, empty-but-heavy file, absent-in-existing-folder,
nonexistent volume/subfolder) and byte-compiled clean. Phase 2 (Settings path
change adopts vs. overwrites) and Phase 3 (`persist()` shrink tripwire +
rotating backups) close the remaining wipe paths — see
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

## 2026-07-10 — Grading workspace: teacher identities move to local prefs (public-release fix)

**Symptom:** after the repo was prepared for public release, opening an
assignment in the grading workspace bucketed every teacher-uploaded file under a
single phantom **teacher-owner** student instead of routing each to its real
student — only files a student genuinely owned in Drive attributed correctly.
No grades
were lost: attribution is a *live Drive-read* concern, and saved grades are
keyed by student ID in the database (verified intact — 121 students, 1262
scores, 120 remarks/overrides).

**Cause:** preparing the public repo emptied the hard-coded `MY_IDENTITIES`
list (which must not ship real names/emails). With it empty, `is_me()` no longer
recognised the teacher's own Drive account, so `pick_student()` — which normally
*skips* the teacher-owner and recovers the student from `sharingUser` /
`lastModifyingUser` — instead accepted the teacher account as the "owner" and
grouped all shared-folder uploads under it.

**Fix (`cam_grading_workspace/app.py`).** `MY_IDENTITIES` now stays **empty in
tracked source** (it ships publicly) and real identities are merged in at
runtime from the device-local, **git-ignored** `local_device_prefs.json` via a
new cached `my_identities()` helper:

```json
{ "my_identities": ["j.smith", "yourname@gmail.com"] }
```

So the teacher's identity works locally but is never committed. Restart the
workspace after editing the file (the list is cached per process); reopen /
re-scan the assignment to re-attribute the pooled files.

## 2026-07-10 — Window 2: thumbnail-grid matching dialog (Sync/anonymous plan Phase 4)

Per [SYNC_AND_ANONYMOUS_GRADING_PLAN.md](SYNC_AND_ANONYMOUS_GRADING_PLAN.md)
Phase 4 — the teacher-facing face of Phase 3. Phase 3 pooled every unmatched
graded work in `unmatched_works[class][assignment]` instead of minting a
phantom student; Phase 4 lets the teacher resolve those visually, entered from
the student who is missing the work. **CAM `app.py` only** (additive UI + a
render helper; no schema, no engine change).

- **Entry point in the Window-2 ⚠ missing-work popover (`render_window2`).** A
  missing assignment whose class+assignment has a non-empty `unmatched_works`
  pool now renders as a button — "🧩 `<name>` — N unmatched work(s)" — instead
  of a dead "missing" line; it opens `match_works_dialog(student_key,
  assignment)`. An assignment with an **empty** pool keeps today's plain text +
  tags (excused / awaiting grade) unchanged — the change is purely additive.
- **`match_works_dialog` (`@st.dialog(width="large")`).** Scoped to one student
  missing one assignment, so matching is a single click — no dropdown. It shows
  a scrollable grid (`st.columns`, 3 per row) of the assignment's pooled works:
  thumbnail, filename caption (secondary — the *image* is the identification
  channel), a **⤢ Enlarge** toggle, and a **"✓ ⟨first name⟩'s work"** button
  that calls Phase 3's `assign_work` (write the durable alias, materialise the
  score, drop from the pool) and reruns the whole app so the ⚠ count and Window
  3 score refresh. **⤢ Enlarge** re-renders that one work full-width (~1600px)
  to read a handwritten name; **⤡ Shrink** returns to the grid — both toggles
  `st.rerun(scope="fragment")` so the dialog stays open. No hover, no JS.
- **Thumbnails (`_work_thumbnail` → `_render_work_png` → `_work_page_png_bytes`,
  `_find_work_file`).** The pooled row's `files` cell (the export's `"; "`-joined
  basenames) is resolved to a file under the assignment's `folder_ref`, walking
  **both** layouts (flat stem-per-student and subfolder-per-student). First
  page / image is rasterised through the same PyMuPDF/Pillow pipeline the
  grading workspace uses (`exam_engine.page_png_bytes`), downscaled to 400px
  (grid) / 1600px (enlarged), and **disk-cached** under `thumb_cache/` keyed by
  path+mtime+width — gitignored and beside `app.py`, deliberately **never** in
  the (possibly OneDrive-synced) db folder. Reopening the dialog is a cache hit.
  Both imports (`fitz`, `PIL`) are lazy, so a missing PyMuPDF only degrades this
  one feature (filename-only tiles), never boot.
- **Graceful fallbacks.** A pooled work whose source file was deleted after
  export (a sanctioned workflow — the grade lives in the CSV/pool, not the file)
  shows a filename-only tile ("source file no longer on disk") and **still
  assigns**. Drive-backed pools (rare — a transfer student off the roster) get a
  filename-only tile too: no Drive thumbnail fetch in this phase.
- **Verified (sandboxed, synthetic CSVs/rosters — never live prefs):**
  `_find_work_file` locates by basename in flat + subfolder layouts and returns
  None for a missing file; `_render_work_png` renders image + PDF-first-page,
  downscales to the requested width, writes one cache file, and second call is a
  cache hit; `_work_thumbnail` returns a PNG for a present local file and the
  right note for missing-file / Drive / missing-folder cases; an AppTest of the
  real Window 2 renders the "🧩 Essay 1 — 2 unmatched works" button with the
  correct count; a single-run harness renders the dialog (an Enlarge + assign
  button per pooled work, no exception) and `assign_work` shrinks the pool,
  records the durable alias, and materialises the score (A=6) under the student.

## 2026-07-10 — Ingest: roster-aware routing + unmatched-works pool + durable alias layer (Sync/anonymous plan Phase 3)

Per [SYNC_AND_ANONYMOUS_GRADING_PLAN.md](SYNC_AND_ANONYMOUS_GRADING_PLAN.md)
Phase 3. **What it addresses:** with anonymity (Phase 2) removing any filename
discipline, graded works arrive in CAM keyed by camera-roll noise
(`IMG0004050`) instead of a roster id. `ingest_csv` used to join the
`Student Name` cell as an exact string key and **silently mint a phantom
student** for every miss — those leaked into every export through
`students_for_active_class`'s score-only union. Phase 3 stops the minting, pools
the unmatched rows for visual matching (Phase 4), and makes a teacher's match
survive Sync's purge-replace. This is the two-layer late-flags pattern applied
to identity.

- **`ingest_csv` grows opt-in identity routing (`engine/ingestion.py`).** New
  optional params `roster_keys`, `aliases` (`{csv_key → roster_key}`),
  `unmatched_out`, `auto_aliases_out`. Per row, `resolve_identity()` resolves in
  order: (1) exact roster key → ingest under it; (2) known alias → ingest under
  `aliases[sid]`; (3) **unambiguous longest-prefix** match (normalize: casefold,
  strip spaces/`_`/`-`; longest candidate wins; any tie/double-match → no match)
  → ingest under it **and** record the auto-alias; (4) else → append the whole
  row (grades + keywords + comment + files + late + timestamp) to `unmatched_out`
  instead of `get_or_create`. **Never fuzzy/edit-distance** (siblings mis-assign
  eventually). With `roster_keys` falsy the whole mechanism is skipped —
  **byte-identical** for every existing caller (a rosterless class keeps its
  legacy score-only behaviour by design). New `materialize_row()` re-creates a
  pooled row's scores under a roster id through the identical construction path
  (`_apply_grades`), so a manual match scores exactly as a routed re-sync would.
- **CAM persists two class-keyed stores (`app.py`, `acm_database.json` session
  payload).** `work_aliases[class] = {csv_key → roster_key}` — the **durable**
  manual + auto-recorded map, **never rebuilt** (survives purge-replace). And
  `unmatched_works[class][assignment] = [pool-row dicts]` — **rebuilt** every
  time the assignment's CSV is (re)ingested, exactly as scores are. Both wired
  through the four sites (`init_state`, `build_session_payload`,
  `restore_session`, `wipe_database_full`).
- **Sync passes roster + aliases at the shared ingest site.**
  `_ingest_cloud_file` reads the target class's roster keys + `work_aliases`,
  hands them to `ingest_csv`, rebuilds that assignment's pool from the returned
  unmatched rows, merges any new prefix auto-alias into the durable map, and
  surfaces it on the sync banner (`🔗 <asg>: matched \`0001a\` → 0001 by prefix`).
  Exam CSVs never route.
- **`assign_work(class, assignment, csv_key, roster_key)`** — Phase 4's action:
  writes the durable alias, immediately re-materializes the pooled row under the
  roster student (`materialize_row`), removes it from the pool, persists. Works
  even when the source file was deleted after export (the grade lives in the
  pool/CSV, not the file).
- **Late machinery under aliases.** `_sync_reconcile_late` now resolves each CSV
  id through `work_aliases` before matching, so an aliased row's `Late` heals the
  score living under the **roster** id. The Late-count tripwire and manual
  `late_flags` (both keyed by roster id) are unaffected.
- **Publish reverse-map.** `_publish_workspace_grades` additionally mirrors each
  aliased student's entry under the **csv_key** (verified against CGW `api_load`:
  a local/unmatched work's key is `student_id_from_email(email) or name` = the
  csv_key), so CGW's reconcile lands on the right work; the roster-id key is kept
  too (harmless — routes to `cam_extra` if no work matches).
- **Ambient visibility.** Window 1's assignment-analytics dialog shows a
  `🧩 N unmatched work(s)` warning for a folder assignment with a non-empty pool.
- **Existing phantom students from past syncs are left alone** (the teacher
  archives them) — routing only runs when a CSV is (re)ingested with a roster
  present; a one-time cleanup sweep is deferred.

## 2026-07-10 — Anonymous grading mode in CGW (Sync/anonymous plan Phase 2)

Per [SYNC_AND_ANONYMOUS_GRADING_PLAN.md](SYNC_AND_ANONYMOUS_GRADING_PLAN.md)
Phase 2. **What it addresses:** the marking viewer always showed student names,
IDs and filenames and always graded the same (alphabetically first) student
first — so grading order and name/filename recognition (a student who renames
their file `AbeJohn_Essay.pdf` gets recognition one submitting `IMG0004050.jpg`
does not) biased scores. CGW gains an opt-in per-device toggle that strips
identity from the *display* while leaving state, save, export and the CSV
round-trip byte-identical.

- **"Anonymous grading" toggle (CGW `app.py`)** — a checkbox in the ⚙ Settings
  modal, persisted in `local_device_prefs.json` (CGW's device-local prefs; same
  filename CAM uses for its own UI prefs), default **off**. New `load_prefs()` /
  `save_prefs()` (save **merges**, never clobbering another tool's keys) and
  `anonymous_enabled()`; new `GET/POST /api/prefs` route. Flipping it reloads the
  open assignment so tiles + matrix switch at once.
- **Display-only anonymization, in the payload where it is built.** A new
  presentation layer (`present_students()` / `present_student()` /
  `_anonymize_student()` / `_anon_plan()`) returns *copies* of the student dicts
  with only the display strings overwritten: student `name` + `display_id` →
  `Work 01`…`Work NN`, `email` blanked, `files[].filename` → `Image 1` /
  `Document 2` (kind/draft-chip/Late/MODIFIED/count all preserved). Wired into
  `api_load`, `api_state`, `api_group_link` and `api_save`. **Never touched:** the
  round-trip identifiers (`key`, file `id`, `web_view`/`embed_url`, grades keyed
  by `key`), saved state, `grading_cache.json`, and `api_export`'s CSV cells —
  `api_export` reads `STATE` directly and never sees this layer, so the exported
  `Student Name` / `Files (newest first)` stay **real** (Window 2 matching keys
  on them). Nothing here mutates `STATE`.
- **Seeded shuffle:** with the toggle on, order is `random.Random(state_key)`
  over the sorted student keys instead of alphabetical — stable across reloads of
  the same assignment, different between assignments, uncorrelated with names.
  Off → today's alphabetical order is byte-identical.
- **Honesty (plan T7):** anonymity is bias-reduction, not blind review — the
  round-trip `key` still embeds the real id, the "↗ open" link still serves the
  real file, and a student can write their name inside the work. One line in the
  settings note says so.
- **Verified (sandboxed, no OAuth/live data):** off → payload byte-identical to
  today (Drive-shaped + local synthetic); on → every tile/matrix cell is
  `Work NN`, no real name/id/filename in any display field (email blanked,
  filenames neutral), order differs from alphabetical, is stable across a reload
  and differs between two assignments; grade round-trips by key across an
  anon↔plain reload; and the exported CSV is **byte-identical on-vs-off** and
  carries real stems/filenames. Browser spot-check of the two layouts remains a
  manual look (port 5001).

---

## 2026-07-10 — Sync decomposition: scoped sync + lifecycle triggers (Sync/anonymous plan Phase 1)

Per [SYNC_AND_ANONYMOUS_GRADING_PLAN.md](SYNC_AND_ANONYMOUS_GRADING_PLAN.md)
Phase 1. **Symptom it prevents:** the universal 🔄 Sync button was the only way
grades re-entered CAM, so a teacher who forgot to press it before re-opening an
assignment in CGW re-published CAM's *stale* values — CGW's reconcile then
adopted the stale value and flagged the teacher's newer marks MODIFIED, losing
them (the launch-time stale-handoff race, plan Terrain §T4). Sync is now
automatic and mostly assignment-scoped, tied to the moments that actually
produce/consume CSVs.

- **`sync_assignment(class, assignment)` (CAM `app.py`)** — an assignment-scoped
  sync that reuses the *identical* per-CSV machinery as the global scan: the new
  shared `_sync_one_csv()` helper (extracted from `sync_from_cloud`'s inner loop)
  carries the duplicate guard, purge-replace ingest, the Late-count tripwire, the
  read-only completeness stamp + Late reconcile, and the graceful parse-failure
  branch, so scoped and global passes can never diverge. `_assignment_csv_paths()`
  finds the target's CSV(s) by the same cleaned-name + rebind round-trip ingest
  uses (exam CSVs excluded).
- **Launch-time sync closes §T4:** `launch_grading_workspace()` now scoped-syncs
  the target assignment **before** `_publish_workspace_grades`, so CAM publishes
  its *latest* values, not ones older than the CSV on disk. A duplicate-dated
  group or a parse failure **cancels the launch** with the banner — a session
  started on an ambiguous/stale baseline clobbers marks.
- **Post-session probe:** a successful folder launch records a session-only
  `active_launch` marker; on each rerun, throttled to ~30 s
  (`ACTIVE_LAUNCH_PROBE_INTERVAL`), `_run_active_launch_probe()` cheaply
  `os.stat`s just that assignment's export CSV(s) and, on a change,
  scoped-syncs + banners, clearing the marker once the newer export ingests.
- **Session-start global pass:** `_run_session_start_sync()` runs one `sync_all()`
  automatically after the DB loads (once-per-session guard `session_sync_done`);
  the OneDrive/multi-machine catch-up. Unconfigured installs (no Custom Database
  Path) stay a quiet no-op — no error banner.
- **Active-launch guard:** the global scan (`sync_from_cloud`) **skips** the
  CSV(s) of an assignment with a live `active_launch` marker, so the scoped probe
  owns that file mid-grading and the two never race.
- **Button demoted, not deleted:** the main-bar 🔄 Sync button is gone; **"Force
  full re-scan"** (the same `sync_all`) now lives in ⚙ Settings for the manual
  escape hatch. Class-add / 👁 Watch keep their existing automatic passes.
- **No schema change:** `ingested_files` is untouched; `active_launch` /
  `session_sync_done` are session-only and never persisted. Purge-replace,
  duplicate-refusal and Late-tripwire semantics are unchanged — every new trigger
  surfaces them through the same `_report_sync` banner as the old button.
- **Verified (sandboxed):** a 20-check harness (temp db folder + synthetic CSVs,
  no live prefs, no CGW process) confirms all six plan Done-when items — launch
  ingests-before-publish (published `cam_grades` shows the newer band); a
  duplicate pair blocks the launch; the probe auto-ingests a fresh export past
  the throttle (and respects the throttle otherwise); the session-start pass
  picks up an unrelated changed CSV; a full re-scan of an unchanged sandbox
  ingests nothing; and an unparseable CSV errors gracefully (counted, left out of
  the registry) then re-ingests once fixed.

## 2026-07-10 — Threaded exam-slicing worker (PDF/local-mode plan Phase 6)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 6. **Symptom
it prevents:** a class with many student PDFs made `POST /api/exam/process`
sit for the whole slice before responding, long enough to hit a browser gateway
timeout even though the crops were being written fine. Slicing now runs off the
request thread.

- **Background job + polling:** `api_exam_process` validates the folder, saves
  the exam config, then launches `process_exam` on a daemon
  `threading.Thread` (`_run_exam_job`) and returns a `job_id` immediately. The
  Exam Setup UI (`processAll` → new `pollExamJob`) polls the new
  `GET /api/exam/status/<job_id>` once a second, showing a live `done / total`
  student counter and, on completion, the same "✅ Sliced N images…" summary as
  before.
- **`process_exam` gained an optional `progress(done, total)` callback**
  (`exam_engine.py`), invoked after each student. Default callers (none passed)
  behave exactly as before — no schema or output change; crops still land at
  `<crops>/<Class>/<Exam>/<Q>/<Student>.png`.
- **Locking:** jobs live in an in-memory `EXAM_JOBS` registry guarded by its own
  `EXAM_JOBS_LOCK`, deliberately independent of `STATE_LOCK` — slicing only
  touches the filesystem, never `STATE`. The exam-definition store's atomic
  writes and `threading.Lock` are untouched. Jobs aren't persisted; a restart
  forgets in-flight/finished jobs (the crops on disk are the durable artifact).
- **Empty/invalid folder still fails fast** synchronously with a 400 (validated
  before the thread starts), so the teacher gets the same immediate error.

## 2026-07-10 — grading_cache.json schema versioning (PDF/local-mode plan Phase 5)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 5. Independent
hardening: the workspace's background autosave cache
(`cam_grading_workspace/app.py` → `grading_cache.json`) is now schema-versioned,
so future entry-shape changes have a single, safe migration seam instead of an
ever-growing pile of read-time coercions.

- **Top-level `"version"` key + `CACHE_VERSION` (= 1):** `load_cache()` now
  reads the raw file, migrates every entry through one routine, and stamps
  `version`. `write_cache()` stamps it too, so even a brand-new (empty) cache is
  written versioned. Writes stay atomic (`.tmp` + `os.replace`) as before.
- **Single `upgrade_entry()` migration routine:** the long-standing read-time
  shims `_normalize_checklist()` (bare-string / mixed headers →
  `{label, type}`) and `_normalize_grades()` (legacy `"grade": "7"` →
  `{"A": "7"}`, obsolete `grade` key dropped) are folded in as the **v0 → v1**
  step. Idempotent on already-v1 entries.
- **Late-flag integrity preserved (map §G):** `late_manual` is carried through
  verbatim and defaulted to `false` **only when absent** — never stripped or
  forced, which would have silently un-stuck every teacher-set Late tick
  (the 2026-07-09 incident). `cam_modified` is re-validated to real criterion
  letters; `cam_extra` / `cam_name` / `criteria` / `deadline` / `groups` pass
  through untouched.
- **Legacy files still load:** an unversioned (v0) mixed-shape `grading_cache.json`
  loads cleanly; after one load-and-save every entry is v1 and the file carries
  `version`. Missing / non-dict cache files degrade to `{}`.
- **Verified** with a sandboxed harness (temp `cloud_dir`, no real data): a
  hand-crafted v0 cache mixing the legacy single-`grade` shape, a bare-string
  checklist header, and a hand-set `late_manual: true` migrates correctly —
  legacy grade promoted, header coerced, `late_manual` preserved across the
  in-memory migration, the idempotent second pass, and a real `write_cache()`
  round-trip to disk (19/19 checks pass). App boots clean (`/api/state` → 200).
- Docs: `DATA_DICTIONARY.md` Part B gains the `version` key in B.1, a migration
  note in B.3, and a new **B.7 Schema versioning & migration**.

## 2026-07-09 — CAM bridge: local classes flow end-to-end (PDF/local-mode plan Phase 4)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 4. A CAM class
whose `master_dir` is a **local path** now flows through folder grading exactly
like a Drive class — Watch → 🖌 Grade → CGW marking → CSV export → 🔄 Sync →
Awaiting-Grade unlock — with no Google account. The CGW marking viewer already
graded a local folder since Phase 3; this lifts the CAM-side handoff that still
refused local masters.

- **Refusal lifted (CAM `app.py`):** `_seed_workspace_class()` no longer returns
  a teacher-facing refusal for a local-master class; it now seeds the class map
  with the local master path (Drive IDs unchanged), so `launch_grading_workspace()`
  drives a local class straight into CGW. The `cloud_dir` seeding is unchanged.
- **Local class browser (CGW `cam_grading_workspace/app.py`):** `POST /api/class`
  now enumerates a **local class-master path** off disk (new `local_subfolders()`,
  chosen by the Phase-1 `_ref_is_local` seam) — no OAuth — returning the same
  `{class_folder_name, assignments:[{id, name}]}` shape the Drive path returns,
  with each `id` the subfolder's absolute path. The CAM-bridge autoloader
  (`autoloadFromParams` → `loadClass` → `/api/class` → `openSelectedAssignment`)
  and every front-end path are **byte-for-byte unchanged**: the local subfolder
  ids match the `folder_ref` CAM stamps in `_watch_class_master`, so the dropdown
  resolves the assignment exactly as a Drive folder ID does.
- **Round-trip key aligned (CAM `app.py`):** `_publish_workspace_grades()` now
  keys the handoff file by the workspace's **durable state key** (new
  `_workspace_state_key()`) — a Drive ID unchanged, or the same `local-<hash>`
  slug `LocalProvider.state_key` derives (sha1 of the normcased absolute path) —
  so `cam_grades_<key>.json` lands under the exact name CGW reads. Publish →
  reconcile (MODIFIED markers) → export → Sync now round-trips for local classes.
- **Missing-folder re-link (CAM Window 1 analytics dialog):** deleting a local
  assignment folder after its CSV is exported is a sanctioned workflow (the marks
  live in CAM). When a Grade button's local `folder_ref` no longer exists on disk,
  the dialog now shows a "folder missing — grades are safe; re-link to regrade"
  banner with a re-link input that updates just that assignment's `folder_ref`,
  and suppresses the dead-launch Grade button. Watch never drops or duplicates a
  row whose folder vanished (rows are pinned by `folder_ref`, never re-scanned for
  existence).
- **Capability hint (✎ Add / Edit class dialog):** the master-directory expander
  now states what each master type grades — local = PDFs, images, video (export
  Office docs to PDF first); Drive = those plus Google-native Docs/Sheets/Slides —
  and that work graded elsewhere can always be entered by hand.
- **§G late-flag machinery inherited, not re-implemented:** a local export writes
  the identical `<name>_Grades_<date>.csv` with the tri-state `Late` column into
  the class's data folder, so CAM Sync's duplicate-export guard, read-only Late
  reconcile, and Late-count tripwire apply unchanged (they key on the filename,
  not on Drive IDs). Verified, not touched.
- **Verified** (CGW started with a local test class, no `token.json` used on the
  local path): `/api/class` listed the assignment subfolder; the CAM-bridge
  autoload URL opened straight into it (class + assignment dropdowns pre-selected,
  both students grouped with PDF thumbnails, **no console errors**); a
  `cam_grades_local-<hash>.json` written by hand (CAM's exact slug — confirmed
  equal to `LocalProvider.state_key`) was **reconciled** (grade adopted, `A`
  flagged `cam_modified`, comment adopted) and **consumed**; `/api/export` wrote a
  CSV with the identical Drive header + tri-state `Late` column into the class
  folder alongside the slug-keyed `grades_<slug>.json` / `grading_cache.json`.

## 2026-07-09 — LocalProvider: grade a local folder in CGW (PDF/local-mode plan Phase 3)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 3. Fills in the
`LocalProvider` stub so the marking viewer can grade a **local assignment folder**
(no `token.json` needed) through the exact same pipeline as a Drive assignment —
students grouped, thumbnails, hover-enlarge, focused PDF viewer, grading, save,
export — **indistinguishable once loaded**. Google support is untouched.

- **New behaviour (CGW `cam_grading_workspace/app.py`):** `POST /api/load` pointed
  at a filesystem path now succeeds via `LocalProvider` (chosen by the Phase-1
  `_ref_is_local` seam). It enumerates the folder into `fetch_folder`-shaped file
  dicts so `group_by_student` and the **entire front end stay byte-for-byte
  unchanged**. Student identity mirrors Google Classroom's local layout:
  **subfolder-per-student** when the assignment folder has subdirectories
  (subfolder name = student), else **filename stem = student**. The synthesised
  owner lets `pick_student` resolve identity exactly as it reads a Drive owner
  email, so the exported CSV is shaped identically.
- **Media routes, now backend-aware:** `/api/thumbnail`, `/api/pdf`, `/api/video`
  and a new **`/api/download/<file_id>`** all dispatch through `current_provider()`.
  `LocalProvider` renders **PDF first-page / image thumbnails** via `exam_engine`
  (PyMuPDF rasterise → Pillow LANCZOS, grid ~400px + hover 1600px honouring `?sz=`),
  disk-cached under `thumb_cache/` keyed by source path + mtime + width (gitignored,
  **outside the served tree**). PDFs serve inline via `send_file`; video streams
  from disk (`conditional=True` → HTTP Range, no Drive-bandwidth concern locally);
  office/other files fall back to a placeholder tile plus the download link. Per-file
  IDs are opaque `lf-<hash>` tokens resolved through an in-session **id→path
  registry**; every file access is guarded by an `os.path.commonpath` containment
  check against the loaded folder (not `startswith`), so an unknown/escaped id 404s.
- **Durable key:** `api_load` now persists under `provider.state_key(ref)` — a
  Drive ID unchanged, or a stable `local-<hash>` slug of the normalised absolute
  path for a local folder — so `grades_<key>.json` and the `grading_cache.json`
  entry (DATA_DICTIONARY §B.1) survive an app restart. Lateness is synthesised from
  file mtimes into `createdTime`/`modifiedTime`, feeding the existing `Late`
  derivation + the sticky `late_manual` tick unchanged (Terrain §G intact).
- **No token, no Google import on the local path:** the whole flow runs with
  `token.json` renamed away — `LocalProvider` touches only `exam_engine`, Pillow and
  the filesystem. A short **local-mode note** was added to CGW's ⚙ Settings modal
  documenting the identity convention, the PDFs-and-images scope, and the mtime
  lateness caveat.
- **Verified** with `token.json` renamed away: loaded both layout conventions
  (subfolder + flat) — students group correctly; PDF thumbnails render (grid 6.3 KB,
  hover `?sz=1600` 39.5 KB) and image thumbnails serve; `/api/pdf` returns inline
  `application/pdf`; `/api/download` serves; an unknown id 404s (containment holds);
  a grade + criteria + deadline **survive a full process restart** (reloaded the
  slug-keyed state) ; the exported CSV header/columns are identical to a Drive
  export. In a real browser (unchanged front end): the roster shows student cards
  with PDF thumbnails and **Late badges** (mtime 2026 vs a 2020 deadline → `isLate`
  true), clicking a PDF fills the left panel with the native engine + ✕ Close,
  **Escape** closes it, and no console errors. `thumb_cache/` added to `.gitignore`.

## 2026-07-09 — Click-to-focus document viewer in CGW (PDF/local-mode plan Phase 2)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 2. First
user-visible feature of the plan: a **focused document viewer** in the marking
workspace. Drive-only for now; local mode still arrives in Phase 3.

- **New behaviour (CGW `cam_grading_workspace/app.py`):** clicking a **PDF** tile
  in a student's file stack now fills the left panel with the browser's own PDF
  engine (an `<iframe>` at the new `/api/pdf/<file_id>` route) — scroll, page
  navigation and zoom come from the native toolbar; our only chrome is an
  **✕ Close** button, and **Escape** also closes. Clicking a **Google-native**
  tile (`slides|doc|sheet|drawing`) opens the same overlay against the file's
  existing `embed_url`. The overlay reuses the `#overlay` element behind the
  video-zoom pattern (new `doc-mode` class); the right-hand grading pane is
  untouched, so grades/keywords/comments stay fully usable while a document is
  focused.
- **New route + provider method:** `GET /api/pdf/<file_id>` delegates to
  `current_provider().pdf(...)`. `DriveProvider.pdf` downloads the PDF through
  the authenticated session and serves it inline (`Content-Type: application/pdf`,
  `Content-Disposition: inline`), **caching to disk** under `pdf_cache/` keyed by
  file id + `modifiedTime` (a re-upload's fresh `modifiedTime` busts the entry;
  disk-write failures fall back to serving the bytes directly). `LocalProvider.pdf`
  is a stub raising `NotImplementedError` until Phase 3. `pdf_cache/` is
  gitignored.
- **No regressions:** the PDF/image hover-enlarge overlay, video hover-zoom, and
  rotate button are unchanged; the hover handlers gained a `docFocusActive` guard
  so a focused document isn't torn down by a stray hover. `buildMedia`,
  `group_by_student`, the file-dict shape, and every other route are untouched.
- **Verified:** booted CGW with a synthetic assignment (a real 3-page PDF, an
  image, a Google-doc tile) and mocked media routes, then drove it in a browser:
  the PDF tile's first page renders as its thumbnail and hover shows the 1600px
  enlarge overlay; clicking fills the left panel with Chrome's PDFium engine
  (`/api/pdf/PDF1` → 200, native `pdf_embedder` loads); the overlay stays clear
  of the grading pane (overlay right edge 285px < right panel 304px); ✕ and
  Escape both close and remove the iframe; the Google-doc tile focuses via its
  `embed_url`. Server-side unit checks confirm the route is registered, serves
  inline `application/pdf`, caches as `<id>__<modifiedTimeDigits>.pdf`, serves the
  second hit from cache without re-downloading, and the Local stub raises. No
  console errors.

---

## 2026-07-09 — Storage-provider seam in CGW (PDF/local-mode plan Phase 1)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 1. Groundwork
only — **no user-visible behaviour change.** Introduces the seam that will let
the marking viewer source files from either Google Drive or a local folder,
without yet enabling local mode.

- **Change (CGW `cam_grading_workspace/app.py`):** the Drive-coupled marking
  logic (`fetch_folder`, the thumbnail proxy, the video Range-stream) now lives
  behind a **`DriveProvider`** class; a **`LocalProvider`** stub sits beside it
  (every operation raises a teacher-readable `NotImplementedError` until Phase 3
  fills it in). `provider_for(ref)` picks the backend at load time by whether
  `api_load`'s (already `_extract_folder_id`-normalised) reference is a Drive
  folder ID or a local filesystem path — `_ref_is_local()` mirrors CAM's
  `_master_is_local()`. The chosen backend is recorded in the new
  `STATE["source"]` (`"drive"` | `"local"`), which the stateless
  `/api/thumbnail` / `/api/video` routes read via `current_provider()` so they
  dispatch to the same backend that loaded the assignment.
- **No behaviour change on the Drive path:** the thumbnail/video route bodies
  moved verbatim into `DriveProvider` methods; the routes now delegate. Route
  shapes (`/api/thumbnail/<id>`, `/api/video/<id>`), the `fetch_folder`-shaped
  file dicts, `group_by_student`, and the entire `HTML_PAGE` front end are
  untouched. Because `LocalProvider.fetch_folder` raises, `STATE["source"]`
  never flips to `"local"` in this phase, so the media routes only ever hit
  `DriveProvider`.
- **Verified:** against a real Drive assignment (`Silent Storytelling (Crit A)`,
  44 files) via the provider + Flask test client — `fetch_folder` returns the
  identical file-dict shape; `/api/thumbnail/<id>` returns 200 `image/jpeg` and
  the `?sz=1600` zoom variant rewrites the size (8 KB → 252 KB); `/api/video/<id>`
  returns 206 with `Accept-Ranges` + `Content-Range` and streams exactly the
  requested Range. `provider_for` routes bare IDs → Drive, `C:\…` and `/home/…`
  paths → Local; the Local stub raises as designed.
- **Schema note:** `STATE["source"]` is transient — re-derived from the
  reference on every load — and appears only in the full-STATE snapshot
  `grades_<folderId>.json`, never in `grading_cache.json` (`write_cache` does
  not emit it). No migration needed (DATA_DICTIONARY B.5).

## 2026-07-09 — Window 3 grade-button tooltips → static caption (PDF/local-mode plan Phase 0)

Per [PDF_AND_LOCAL_MODE_PLAN.md](PDF_AND_LOCAL_MODE_PLAN.md) Phase 0. Symptom:
the per-cell grade buttons in Window 3 (the "⏳ Awaiting Grade" button and the
"Missing/Excused" `cell_missing_*` buttons) carried `help=` tooltips. Streamlit
wraps `help=` buttons in a tooltip container that intercepts hover, so the popup
appeared over the button and blocked the first click; the messages were also
identical row to row.

- **Fix (CAM `app.py`, `student_cockpit` marks list):** removed `help=` from the
  `cell_await_*` and `cell_missing_*` per-cell buttons and rendered the guidance
  once as a single `st.caption` directly above the marks list (Missing = counts
  as a mathematical 0, click to mark/excuse; ⏳ Awaiting Grade = folder still
  being graded, excluded from the trend and grade math). `edit_grade_dialog`
  internals and every other `help=` in the app are untouched.

## 2026-07-09 — Late-flag integrity v2 (the stale-ingest hole + sticky CAM overrides)

Per [LATE_FLAG_INTEGRITY_PLAN_V2.md](LATE_FLAG_INTEGRITY_PLAN_V2.md), the
incident-2 post-mortem. Follow-up to the v1 entry below: v1's fixes work as
designed; these two holes were **pre-existing**, exposed but not caused by v1.
Symptom: Year 10 1Z student 101109's *Launch and Material Shift* (Crit B) was
`Late=1` in the export CSV and marked Late in CGW, but showed no Late pill in
CAM Window 3 — and 27 other works across Year 9 / Year 10 shared the hole.

- **Hole 1 — the stale-ingest hole (`CriterionScore.late` frozen at False).**
  CSVs ingested by a Streamlit process that predated `Late`-column parsing
  (commit `7ae6167`) stored `late=False` on every row; the unchanged-hash Sync
  skip then refused to ever re-read them, freezing the flags forever.
  **Fix (Phase A, CAM `app.py`):** `_sync_reconcile_late()` — a **read-only**
  Late reconciliation in the skipped-as-unchanged branch of
  `sync_from_cloud()`. It re-reads *only* the `Late` column and rewrites each
  matching `csv:`-sourced score's `late` in place (both directions), counting
  changes into `summary["reconciled"]` and surfacing a 🩹 message. Never
  re-ingests (which would purge-replace CAM-side edits), never touches
  `late_flags`. Idempotent; legacy/exam/unreadable CSVs reconcile nothing.
- **Hole 2 — the edit dialog materialised overrides.** The Save handler wrote
  `late_flags[key]` on **every** Save, so hundreds of "overrides" merely echoed
  the effective value; each redundant `False` permanently suppressed a future
  CSV-synced Late.
  **Fix (Phase B, CAM `app.py`):** sticky-manual write — create a `late_flags`
  key *only* when the checkbox actually moved off the pre-save effective value
  (`if key in lf or late != is_late(...)`). Once manual, always manual: updated
  on later Saves, never auto-deleted.
- **One-time cleanup (Phase C, CAM `app.py`).** A marker-guarded
  (`late_flags_cleanup_v1`, persisted in the session payload) purge at the start
  of the first Sync deletes every `late_flags` key redundant against the synced
  value, keeping only real waives/forces. Runs **before** Phase A reconciliation
  (so a redundant `False` on a still-stale cell is deleted while still
  redundant, not frozen as a phantom waive). Deliberate keys kept: 101092 /
  101114 Feature Studies (v1 Phase 6) and 111102 Concept planning (B).
- **Verified:** `app.py` byte-compiles; a sandbox harness driving
  `sync_from_cloud()` on a temp data home asserts all 23 cases from the plan's
  §7 — reconcile heals exactly the stale flag and is idempotent; legacy/exam/
  manual-source rows are untouched; cleanup deletes only redundant keys and the
  marker round-trips through save/load; the sticky-write guard creates no key on
  an untouched Save. Docs: ARCHITECTURE §8 (new reconciliation invariant),
  DATA_DICTIONARY A.7 (the two lateness layers). Live-data acceptance (press 🔄
  Sync once on the restarted app; ~28 flags reconciled, 101109 pill appears) is
  the teacher's step per the plan's §6.

## 2026-07-09 — Late-flag integrity (deadline resets + duplicate exports)

Per [LATE_FLAG_INTEGRITY_PLAN.md](LATE_FLAG_INTEGRITY_PLAN.md), which also
serves as the incident post-mortem. Symptom: late works flagged in the grading
workspace stopped showing the Late marker in CAM Window 3 for Year 10 1Z
(2026-27). Not a code regression — a data-flow wipe from two interacting design
flaws. Phases 1–4 below; Phase 5 is this entry plus the ARCHITECTURE §8 /
DATA_DICTIONARY A.1 + B.3 updates.

- **Flaw A — deadline changes clobbered manual Late ticks (CGW).** The
  `#deadlineInput` change handler re-derived *every* student's `late_marked`
  from timestamps, so restoring a lost deadline silently zeroed hand-set flags.
  **Fix:** a new per-student `late_manual` flag (`cam_grading_workspace/app.py`)
  set whenever the teacher toggles the Late checkbox; the deadline handler now
  re-derives **only** non-manual students (`if (!st.late_manual) …`). Manual
  ticks *and* waivers are sticky. `late_manual` is CGW-internal — persisted in
  `grading_cache.json`, absent → auto-derived (no migration), and **not** added
  to the export CSV (CAM's tri-state `Late` contract is untouched).
- **Flaw B — duplicate-dated exports + purge-replace Sync (CGW + CAM).** One
  assignment could accumulate two `*_Grades_<date>.csv` files (a due-date name
  and an export-date fallback); Sync mapped both to the same assignment and
  purge-replaced per file, so whichever ingested last silently won.
  **Fix (CAM `app.py`):** `sync_from_cloud()` runs a per-class pre-pass
  (`_scan_class_duplicate_groups`) and **skips any group of 2+ entirely** — no
  ingest, no registry row, no completeness stamp — counting them under
  `summary["duplicates"]` and raising a prominent alert that names the canonical
  export (filename date == its `Due Date`) vs. the likely-stale fallback. Never
  auto-tiebreaks, never deletes; re-nagged every Sync until resolved.
  **Fix (CGW `api_export`):** a routed export now scans for differently-dated
  sibling files and warns the teacher (`stale_siblings`) so the duplicate is
  caught at export time too.
- **Late-count tripwire (CAM).** On a re-ingest, `sync_from_cloud()` compares
  the assignment's synced-layer Late count (`CriterionScore.late`, not
  `is_late()`) before vs. after the purge-replace and appends an advisory
  warning if it dropped from non-zero. Advisory only — the ingest still happens
  (legitimate waivers must flow through) — but a silent wipe is now visible.
- **Verified:** both apps byte-compile; sandbox `sync_from_cloud()` run asserts
  a duplicate pair ingests neither file, adds no registry rows, counts the
  duplicate and names the canonical file, and a re-exported singleton with
  zeroed lates fires the tripwire.
- **Phase 6 data repair (executed 2026-07-09).** Restored the Year 10 1Z
  (2026-27) flags lost in the incident. **Correction to the plan:** CGW's Late
  checkbox is waive-only (it only shows for auto-detected lateness), so the
  two Feature Studies flags (students 101092, 101114 — not timestamp-late)
  were restored via the **CAM Window 3** `late_flags` override, which wins over
  the synced value and survives re-syncs — *not* by re-ticking in CGW as the
  draft plan assumed. The three stale `_2026-07-08.csv` duplicate exports were
  **moved** (not deleted) to `OneDrive\Documents\School\_stale_export_backup_2026-07-09\`,
  outside the CAM tree; zero duplicate groups now remain in the class folder.
  See [LATE_FLAG_INTEGRITY_PLAN.md](LATE_FLAG_INTEGRITY_PLAN.md) §8 for the
  full record.

## 2026-07-08 — "Grade" terminology + numberless-comment toggle

Per `docs/GRADE_TERMINOLOGY_AND_NO_NUMBERS_PLAN.md`. Streamlit (`app.py`) plus
the prompt-feeding strings in `engine/aggregation.py` and their verify scripts;
additive and backward-compatible. No Python identifiers, session keys, persisted
JSON fields, or the CGW handoff format were renamed.

### 1 — New "Never mention numeric grades" toggle in the LLM parameters dialog

- **Fix:** the ⚙ LLM parameters dialog gained a **Never mention numeric grades
  in the comment** checkbox (`no_numbers`, default **off**). When on, the
  compiled prompt instructs the model to describe achievement qualitatively
  ('excellent', 'strong', 'developing', 'has room to improve') and to state no
  criterion grades, scores, marks, percentages or counts in the comment body.
- **Why:** some report cards should read as prose with no numbers quoted, even
  though the prompt still carries the numeric evidence (criterion results, late
  and missing-work rates) for the model's understanding.
- **How:** additive `no_numbers` key in the `llm_cfg` defaults (persisted, merged
  over defaults on load, so old databases need no migration); a checkbox in
  `llm_params_dialog()` that writes it back on Apply; an instruction appended to
  the `[OUTPUT REQUIREMENTS]` list in `compile_prompt()` when the flag is set;
  and a `· no numbers` fragment in the cockpit prompt-status caption so the
  teacher can see it is live. Default off preserves current output. Percentages
  and counts are covered deliberately (the timeliness/missing-work blocks feed
  "3 of 10 tasks (30%)"); dates and MYP year are not grades and are not carved
  out.
- **Verified:** `python extras/verify_llm_params.py` and `verify_refactor.py`
  pass; `app.py` parses clean.

### 2 — "Band" → "grade" in every user-visible and LLM-visible string

- **Fix:** every string a user or the LLM sees now says "grade" instead of
  "band": the Exam grading panel (was "Exam banding"), its "Grade (0–8)" column,
  "Apply grades to gradebook" button and "Graded N student(s)" toast; the
  assignment-metrics dialog ("Graded", "Avg grade", "Grade distribution", "Grade
  (0–8)" axis); the student progression chart y-axis; the XLSX "Grade" / "Avg
  grade" headers; the upload/sync captions ("Exam grading panel", "raw ·
  ungraded", "Grade it in Window 1"); and the LLM prompt (criterion-results
  header "MYP criterion grade 0-8", the `grade N` evidence lines, "counts as
  grade 0", "the grade results above", and the trend narration from
  `aggregation.py`, e.g. "started at grade 6 … finished at grade 5").
- **Why:** students and the teacher UI have never heard the per-criterion 0–8
  score called a "band"; a report or screen saying "band" confuses them. The
  LLM prompt matters as much as the UI because the model echoes the prompt's
  vocabulary into the student-facing comment.
- **How:** only quoted strings shown to a user or sent to the LLM changed.
  Internal identifiers stay put — `rounded_band`, `MIN_BAND`/`MAX_BAND`,
  `_render_exam_banding`, `_apply_exam_bands`, `suggested_band()`, widget/session
  keys like `band_{sel}_{sid}`, the `_banded_grade()` 1–7 boundary tables, the
  `note="banded from raw …"` audit strings already in databases, and the CGW
  interchange JSON are load-bearing or persisted and were left alone. The two
  senses of "grade" are disambiguated where they collide: per-criterion 0–8 is
  "grade (0–8)", the final IB score is "final grade (1–7)".
- **Verified:** `grep -in "band" app.py engine/aggregation.py` shows only
  identifiers, comments, docstrings and the persisted `note` string — no rendered
  or prompt string survives; both verify scripts pass with the updated
  expectations.

---

## 2026-07-08 — Window 3 comment boxes follow the focused student

Per `docs/STALE_COMMENT_BOX_FIX_PLAN.md`. Streamlit-side (`app.py`) only; bug
fix, no data-model change.

### 1 — Overall comment / Remarks / Comments log no longer show the previous student

- **Fix:** switching the focused student in Window 3 (Evaluation Cockpit) now
  updates the Overall comment box, the Remarks popover, and the Comments log
  immediately; previously they kept showing the previous student's text until a
  full browser refresh (which starts a fresh Streamlit session).
- **Why:** the three text areas used static widget keys (`resp_box`, `rem_box`,
  `cmt_box`). Streamlit caches a keyed widget's value in `session_state` and
  ignores `value=` on every rerun after the first, so a focus (or term) change
  re-rendered the same widget with the previous student's cached text. The
  write-back guard under the Overall comment box could in principle have
  persisted one student's comment into another's record — a latent
  data-corruption hazard.
- **How:** the Overall comment box is now keyed per student+term
  (`resp_box_{sid}_{term}`) and the Remarks box per student (`rem_box_{sid}`),
  so a focus/term change creates a fresh widget initialised from that student's
  stored value; the read-only Comments log dropped its key entirely (same
  pattern as the compiled-prompt box). The Settings height-override CSS moved
  from exact `.st-key-rem_box` / `.st-key-resp_box` classes to
  `[class*="st-key-rem_box"]` / `[class*="st-key-resp_box"]` substring selectors
  so it keeps matching the now-dynamic keys.
- **Verified:** `py -m compileall app.py` clean; `grep -n "resp_box\|rem_box\|cmt_box"`
  shows only dynamic keys (Overall/Remarks) and substring CSS selectors, and no
  remaining `cmt_box` key. Live app (OneDrive database, Year 7 class): focusing a
  student rebuilds the box under a per-student class (`st-key-resp_box_131079_Term_1`)
  and the height-override CSS still applies (box resized to the slider value),
  and the focus switch performed no spurious save (write-back guard saw equal
  values). Note: the fix prevents *new* cross-writes but does not repair data a
  prior session's static-key code already corrupted on disk.

---

## 2026-07-08 — Batch AI comments skip students who already have one

Per `docs/SKIP_EXISTING_COMMENTS_PLAN.md`. Streamlit-side (`app.py`) only;
additive and backward-compatible.

### 1 — "Generate for whole class" now fills only the gaps

- **Fix:** "Generate for whole class" now skips students who already have a
  non-empty comment for the current term (generated earlier or hand-typed),
  controlled by a default-on **Skip students who already have a comment** toggle
  in the LLM parameters dialog; the status banner reports the skipped count.
- **Why:** a partial batch run (e.g. the Gemini free tier's 5-requests/minute cap
  aborting after 6 of 35) previously could only be completed by regenerating the
  whole class, redoing — and potentially overwriting — the comments that already
  succeeded, and burning quota on them.
- **How:** `_generate_class_comments()` gained a `skip_existing` guard
  (`lc.get("skip_existing", True)`) that `continue`s past any student whose
  current-term `llm_response` entry is non-blank, counts skips, and returns a
  4-tuple `(n_ok, n_fail, n_skipped, first_error)`; the caller folds the skip
  count into the banner. Because manual and generated comments share the
  `comments_by_term` store, one check covers both. The single-student generate
  button is unaffected. The new `skip_existing` key is additive and defaults on
  for old databases.
- **Verified:** `py -m compileall app.py` clean; `grep "_generate_class_comments"`
  — one definition + one caller, both on the 4-tuple; live app — toggle persists
  across Apply/reopen; batch run reports a non-zero Skipped count and leaves
  existing comments intact; unchecking regenerates all.

---

## 2026-07-08 — Per-student, per-term calculation method with auto default

Per `docs/MISSING_WORK_AND_CALC_METHOD_PLAN.md`, Workstream 2. Streamlit-side
only; the new persisted store is additive and backward-compatible.

### 1 — The grade-calculation method is now per student, per term

- **Fix:** the calculation method (which algorithm turns marks into a band) is
  a **per-student, per-term** setting with a live **Auto** default, replacing
  the single global dropdown value. Window 3's dropdown gains an Auto option
  labelled with the live context (e.g. `Auto — 60/40 Recency (12 assignments
  this term)`); picking a method pins it for that (term, student), picking Auto
  releases the pin. Pins persist across restarts in a new `calc_method_by_term`
  store (`term -> {sid -> method}`), mirroring `effort_by_term`.
- **Why:** the old Window 3 dropdown *looked* per-student but wrote one global
  `calc_method`, so changing it for one student changed every student, class and
  term at once; nothing reset at term boundaries, and the default never adapted
  to how much work a term held.
- **How:** `calculation_method(sid)` (now a **required** arg — no zero-argument
  form, so a missed call site fails loudly) returns the stored pin when present
  and still a known method, else `auto_calc_method()`, which counts the term's
  *qualifying* assignments (On, criteria-bearing, not a `(Reflection)` adjunct;
  banded exams count) and picks **≤ 15 → 60/40 Recency, > 15 → Weighted
  Median**, recomputed live. Method resolution moved **inside** every per-student
  loop (`aggregate_with_policy`, the report-card and mail-merge packs, the
  single report), so two students in one class can compute under different
  methods. A new term opens empty → everyone on Auto. **Old databases fall back
  to Auto** — the legacy top-level `calc_method` (and `w_new`) keys are ignored
  on load, no migration, so a teacher who had hand-picked a global method
  re-pins it per student once.
- Verified: `py -m compileall app.py engine cam_grading_workspace` clean;
  `grep "calculation_method("` — every call passes a student id; live app on the
  4-class DB — Auto label shows the right count (excluding `(Reflection)` and
  formatives), pinning student A leaves student B's bands unchanged, a new term
  opens on Auto for everyone, and a pin survives save→reload while the
  pre-change DB (legacy `calc_method` present, new key absent) still loads.

---

## 2026-07-08 — `[MISSING WORK]` prompt block (toggleable)

Per `docs/MISSING_WORK_AND_CALC_METHOD_PLAN.md`, Workstream 1. Streamlit-side
only; the config change is additive and backward-compatible (saved LLM configs
merge over defaults, so `inc_missing` arrives as `True` with no migration).

### 1 — The LLM now receives an explicit missing-submission count

- **Fix:** a new toggleable **`[MISSING WORK]`** prompt block reports the share
  of this term's *assessed* tasks (submitted + missing) the student did not
  submit — `X of Y (Z%)` plus the unsubmitted task names — with a matching
  `[OUTPUT REQUIREMENTS]` line asking the model to note the habit once, briefly,
  without double-penalizing (the synthetic zeros have already dragged the bands
  down). New "Inject missing-work rate" checkbox (`inc_missing`, default on).
- **Why:** the prompt carried no explicit missing-work *count*, yet it *leaked*
  the info in a place no toggle controlled — `[CURRICULUM CONTEXT]`
  unconditionally appended an "Unsubmitted tasks…" line. So the teacher could
  not actually suppress the signal (e.g. when a zero was an academic-dishonesty
  penalty, not a non-submission).
- **How:** new `_missing_work_stats()` reuses `missing_assignment_rows()` (the
  single Missing = 0 / Awaiting-Grade gate — now its fifth consumer) for the
  numerator and adds `_late_submission_stats()`'s *submitted* count for the
  denominator, so Excused, ⏳ Awaiting Grade, formative and unbanded-exam work
  are all excluded for free; stored band-0 scores are never scanned (a stored 0
  means something *was* submitted). Counted per distinct assignment. The block
  is **omitted entirely at 0 missing**. The always-on `[CURRICULUM CONTEXT]`
  unsubmitted line was **moved into** the block, so OFF removes every
  missing-work signal from the prompt.
- Verified: `py -m compileall app.py` clean; live app — block shows the right
  `X of Y (Z%)` and names for a student with missing work, is gone (names too)
  when the toggle is off, and absent for a student with nothing missing; an
  excused assignment leaves both numerator and denominator.

---

## 2026-07-08 — LLM comment-generation hardening (pre-batch-run)

Seven fixes to the comment pipeline before the term's 120+-student batch run,
per `docs/LLM_PARAMS_IMPROVEMENT_PLAN.md`. All persistence changes are additive
and backward-compatible (old DBs load unchanged via the `d.get(key, default)`
pattern).

### 1 — Late submissions now travel CGW → CAM → LLM

- **Fix:** CGW's Late checkbox now reaches CAM as data. The workspace CSV export
  gained a tri-state **`Late`** column (`"1"`/`"0"`/`""` from each student's
  `late_marked`); `ingest_csv` reads it (new `late_column="Late"` kwarg) into a
  new `CriterionScore.late` field, purge-replace re-ingest refreshing it each
  Sync.
- **Why:** previously lateness lived only in CGW's auto-comment text and CAM's
  manual `late_flags`; nothing populated the flag from a sync, so the prompt
  carried no timeliness signal.
- **How:** `is_late()` became a **two-layer read** — a manual `late_flags`
  override wins *when its key is present* (the teacher's CAM-side waive/force
  layer, persisted, survives re-syncs), else it falls back to the synced
  `score.late`. All four call sites pass the score object. A new toggleable
  `[SUBMISSION TIMELINESS]` prompt block reports the share of this term's graded
  tasks submitted late (distinct-assignment ratio, non-excused, ≥1 valid
  included score), **omitted entirely at 0%**; a matching `[OUTPUT
  REQUIREMENTS]` line asks the model to acknowledge habits briefly. New
  "Inject late-submission rate" checkbox (default on).
- Verified: CSV round-trip unit checks (`extras/verify_llm_params.py`);
  persist round-trip of `late`; live app — block correctly absent for a student
  with no late work.

### 2 — Unit plans persist across restarts

- **Fix:** uploaded unit plans no longer vanish on restart. `unit_plans` is now
  in `build_session_payload()` / `restore_session()` (new
  `engine.persistence.unit_plan_to_dict` / `unit_plan_from_dict`), and
  `ingest_unit_plan()` calls `persist()` immediately.
- **Why:** the map was explicitly session-only and never serialized, so the
  prompt silently lost its `[CURRICULUM CONTEXT]` plan lines after any restart.
- **How:** restore is defensive (a malformed entry is skipped). **Bonus:**
  `_split_concepts` now also drops `related concept(s)` / `key concept(s)`, and
  `unit_plan_from_dict` filters that boilerplate on read — so plans persisted
  before the fix stop surfacing the leaked literal label
  `Core/Key Concepts: Related concept(s)` (teachers may re-upload to be clean).
- Verified: unit-plan round-trip + concept-filter unit checks; live DB-copy
  round-trip.

### 3 — Streamlit `st.components.v1.html` deprecation removed

- **Fix:** the copy-to-clipboard button (`clipboard_button`) renders through
  **`st.iframe`** (raw-HTML mode) instead of the deprecated
  `st.components.v1.html`; the now-unused import was dropped.
- **Why:** `st.components.v1.html` is slated for removal after 2026-06-01 and
  logged a deprecation line on every render.
- Verified: live app — no deprecation line on stderr, and the copy button still
  copies (iframe script runs; "copied" confirmation appears).

### 4 + 5 — New comment defaults, and `llm_cfg` persists

- **Fix:** default `word_limit 120→100`, `n_strengths 2→1`, `n_growth 2→1`. The
  whole `llm_cfg` now round-trips in the session payload (**excluding the API
  key**, which stays memory-only), restored by **merging saved keys over the
  `init_state` defaults** so a future new key keeps its default.
- **Why:** the teacher's tuned dialog choices silently reverted on every
  restart — annoying mid-batch-run.
- Verified: live app — dialog reads 100 / 1 / 1; DB-copy round-trip preserves
  `llm_cfg`.

### 6 — Richer, word-budget-aware trend narrative

- **Fix:** `TrendInfo` gained spread/shape fields (`vmin`, `vmax`, `range`,
  `typical` modal band, interior `min_pos`/`max_pos`, `recovery`).
  `format_trend_sentence(..., detail=)` renders **compact** (today's sentence +
  a spread clause when the swing exceeds the net move) or **detailed** (narrates
  a mid-term dip/peak and the modal band). `_trend_lines` picks detail from the
  word budget: **≥130 words → detailed**, else compact.
- **Why:** a whole term was reduced to first-vs-last, hiding dips/recoveries
  (e.g. B = 6,3,6,6,5 read as a plain "decline").
- **How:** all phrasing is deterministic template text from the math — the model
  paraphrases, the engine never speculates.
- Verified: unit checks against the screenshot shapes (B, D), a steady series, a
  2-point series and a monotonic rise; live prompt carries `[TREND SUMMARY]`.

### 7 — Evidence lines stop echoing themselves

- **Fix:** `Evidence.as_text()` now emits **only** the quoted comment when
  present, falling back to the keyword list only when the comment is blank.
- **Why:** CGW auto-builds each comment *from* the checked keywords, so printing
  both halves near-duplicated the content
  (`… Zoom in Closer, … — "Zoom in Closer, …"`). `has_qualitative` /
  `select_evidence` are unchanged — keywords still qualify a piece for
  selection.
- Verified: unit checks (comment-only, keyword fallback, bare header).

Verified overall: `py -m compileall app.py engine cam_grading_workspace` clean;
`extras/main.py` harness passes; new `extras/verify_llm_params.py` all-pass;
live-DB-copy load→save→reload preserved unit plans / `llm_cfg` / `late` and the
pre-change DB still loaded. CGW→Sync round-trip not exercised end-to-end here
(needs the Flask workspace + Drive) but both code paths are unit-covered.

---

## 2026-07-07 — Classroom Entry export tab stays in Latin (first-name/surname) order

- **Fix (follow-up to the gojūon roster sort below):** the Excel master's
  **Classroom Entry** tab is once again ordered in **Latin name order — first
  name, then surname** — matching how Google Classroom lists students, so a
  copied mark column pastes back row-for-row. The gojūon roster sort had carried
  through to this tab and mis-aligned it.
- **Why:** the on-screen roster is now gojūon (see below), but that is the wrong
  order for the paste-back workflow — Google Classroom orders by Latin first
  name / surname. The two consumers need different orders.
- **How:** `_append_classroom_entry_sheet()` now re-sorts its incoming students
  locally via `_latin_key` (`(first_name, surname)`, casefolded) before emitting
  rows. The sort is scoped to this one tab; the on-screen roster and the other
  export tabs (Final Suggestions, Raw Scores) keep gojūon order. Purely cosmetic:
  the mark/comment lookup matches on `student_id`, never row position, so no mark
  can be mis-filed — only the print row shifts.
- Verified: `app.py` compiles; Latin ordering simulated against the live Year 9
  roster (rows run Aira, Ange, Coen, Dylan … by first name).

---

## 2026-07-07 — Roster imports auto-sort into gojūon (hiragana あいうえお) order

- **New behaviour:** applying a Google Classroom CSV in Window 2 now orders the
  roster by gojūon reading — **surname first, then given name** — instead of
  leaving it in the export's Latin-alphabet order. The intake note says so, and
  the ↑/↓ buttons still let a teacher fine-tune.
- **Why:** a Japanese classroom register is read in あいうえお order, and romaji
  *alphabetical* order is not the same as gojūon (alphabetically `Sato` < `Kato`;
  in gojūon か precedes さ, so it is the reverse). Sorting the Latin spelling
  directly produces the wrong register order.
- **How:**
  - **New module `engine/collation.py`** — `gojuon_sort_key()` reads a romaji
    string into a list of `(row, vowel, voicing)` kana-mora tuples (a pragmatic
    Hepburn/Kunrei mapping; foreign names degrade gracefully). Comparing the
    lists yields gojūon order, with vowel outranking voicing so か→が→き→ぎ
    interleave as a dictionary does.
  - **`sort_roster_gojuon()` in `app.py`** peels the given name off the stored
    "Surname First" display name to isolate the (possibly multi-token) surname,
    then sorts by `(surname_key, given_key)`. Wired into the Window 2 import
    apply path only.
  - **Existing rosters migrated once.** Year 7–10 in the live DB were re-sorted
    in place. Re-ordering is display-only: marks live in the gradebook keyed by
    `student_id`, independent of roster position (same reason ↑/↓ is safe), so
    the migration left `gradebook` byte-identical and only permuted each roster
    list. A timestamped `.bak-gojuon-*` backup was written first.
- Verified: `engine`/`app.py` import clean; gojūon order eyeballed across all
  four live classes (e.g. Ishii → Ito → Irukuvarjula = し<と<る); migration
  asserted each class's student set unchanged and confirmed `gradebook` identical
  to the pre-sort backup. Not yet runtime-checked in a live Streamlit session.

---

## 2026-07-06 — Excel master gains a "Classroom Entry" tab for keying marks back to Google Classroom

- **New export tab:** `build_excel_bytes()` now appends a fourth sheet,
  **Classroom Entry**, after Final Suggestions / Raw Scores / Assignments. It
  lists every student with a paired **Mark / Comment** column per folder
  assignment, so the teacher copy-pastes each column straight into Google
  Classroom.
- **Why:** CAM/CGW order students by numeric id (email local part); Google
  Classroom orders by surname / first name / status / group. The two never line
  up, so pasting a mark column from CAM into Classroom mis-filed every row and
  forced a manual student-by-student re-match.
- **How:**
  - **Order = Classroom order.** Rows follow `students_for_active_class()`,
    which yields roster students in stored roster order — and the roster is
    saved in the exact order Window 2 ingested it from the Classroom roster
    export. Marks match on `student_id`, never the name, so a misspelled surname
    never breaks alignment.
  - **Folder assignments only.** `_classroom_folder_assignment_names()` picks
    assignments CAM ingested from Classroom (a CGW `source_file` or a watched
    `folder_ref`), non-exam, with ≥1 criterion, in date order. Crit D
    `(Reflection)` tasks are excluded by name — graded separately, no artwork
    comment. The set is dynamic: sync a new folder assignment and its column
    pair appears on the next export.
  - **Blanks, not zeros.** A student with no record for an assignment leaves
    that pair blank — the tab is a transcription aid, outside the grade math, so
    Missing = 0 does not apply.
- Verified: `app.py` parses clean; selection + matching logic simulated against
  the live database (correct folder assignments, Classroom order, marks/comments
  matched) and the openpyxl sheet built + reloaded standalone (merged headers,
  paired columns, frozen panes render with no errors). Not runtime-checked
  through the live Streamlit session — glance at the tab after the next export.

Detail in [ARCHITECTURE.md §11 "The Excel master's Classroom Entry tab"](ARCHITECTURE.md).

---

## 2026-07-06 — Mail-merge pack withholds Effort/English Use and School Grade

- **Change:** the mail-merge pack (`build_reportcards_zip`) no longer prints the
  **Effort / English Use** or **School Grade** rows. The **MYP Grade** and
  everything else (criterion A–D finals, marks, trend chart, comment) stay.
- **Why:** these reports go to students *before* their official report cards, so
  those two figures must stay withheld until then. School is dropped alongside
  Effort because the School grade folds effort in and would otherwise leak it.
- **How:** `_student_docx()` gained an `include_effort_school` flag (default
  `True`); only `build_reportcards_zip` passes `False`. Every other deliverable
  (Excel master, combined report-card pack, single-student report) is unchanged
  and still carries all three grades.
- Verified: `app.py` parses clean. Not runtime-checked (live-data prefs) — glance
  at one drafted PDF after rebuilding to confirm the two rows are gone.

Detail in [ARCHITECTURE.md §10 "Withheld grades"](ARCHITECTURE.md).

---

## 2026-07-06 — Mail-merge report pack (per-student DOCX named by email); archived students no longer leak into exports

- **New export — "Build mail-merge pack":** alongside the combined report-card
  pack, CAM can now emit a **ZIP of one `.docx` per student, each named
  `<student-email>.docx`** (`build_reportcards_zip`). It reuses the same
  `_student_docx` builder as the combined pack, so every file is byte-for-byte
  the same layout — just split per student and named by send address. Built for
  batch emailing: unzip into a Google Drive folder and a mail-merge script mails
  each file to the address in its own filename (see
  [BATCH_SEND_REPORTS.md](BATCH_SEND_REPORTS.md)).
- **Why the email is the filename:** it makes the filename the single source of
  truth for *who a file goes to*, removing the filename↔roster matching step
  (and its mis-send risk) from the send script entirely.
- **Safety:** a student with **no roster email**, a **duplicate email**, or an
  email containing a filename-illegal character is **left out and listed** in a
  full-width warning under the export row — never silently mis-filed. The email
  is never sanitized, since altering it would change who the file mails itself
  to.
- **Symptom that surfaced a deeper bug:** building the Y9 mail-merge pack warned
  that an archived (left-school) student was "left out — no email." He should
  not have been in the pack at all.
  - **Root cause:** `students_for_active_class()` unions roster students with
    any student who has a score in a class assignment. Archiving removes a
    student from the roster but *keeps their grades*, so the score-only path
    silently re-added them — leaking archived students into **every** export
    (Excel master, both DOCX packs, class comments) and the grade-sync / LLM
    comment-generation passes.
  - **Fix:** the score-only path now skips any key in
    `archived_students[class]`. Archived students are excluded everywhere;
    **Restore** brings them (and their grades) back unchanged.
- **UI:** the deliverable row is now five buttons — **Excel master ·
  Report-card pack · Mail-merge pack · Class comments · Single report** — so the
  mail-merge button sits with the other report-card deliverable instead of
  stranded at the page bottom. The skipped-student note renders full-width below
  the row (it lists names and would overflow the narrow column).
- Verified: `app.py` parses clean. Not runtime-checked — the app's prefs point
  at live data, so placement is eyeballed on next launch.

Detail in [ARCHITECTURE.md §10](ARCHITECTURE.md).

---

## 2026-07-06 — DOCX exports get a fixed A4 page setup; report cards show the student email

- **Change:** every Word document the app builds now has a consistent page
  geometry — **A4 paper (21 × 29.7 cm) with 2 cm margins on all four sides** —
  instead of python-docx's US-Letter default. Applies to all three DOCX
  builders: the report-card pack (`build_reportcards_docx`), the single-student
  report (`build_single_docx`) and the class-comments export
  (`build_class_comments_docx`).
- **Why:** the school prints on A4, so the Letter default left an oversized
  right/bottom margin and risked reflowing tables when opened. Centralising the
  setup also means a future page-format change is a one-line edit.
- **How:** a shared `_new_report_document()` factory creates the `Document` and
  stamps the A4 size + 2 cm margins onto every section; the three builders call
  it instead of `Document()` directly.
- **Report-card email line:** the report-card pack and single-student report now
  print the student's **school email address** as a line directly under the
  `Report Card - <Name>` title. The email is not stored on the `Student` record
  (only its email-derived numeric id is), so `_student_docx` looks it up from
  the roster via a new `student_email_for()` helper — mirroring `roster_gender`
  / `first_name_for`. Folder-derived students with no roster email get no blank
  line (the paragraph is only added when an email is on file). The class-comments
  export is unaffected (it carries no per-student title).
- Verified: python-docx reports 210 × 297 mm and 2 cm margins for the shared
  factory (isolated check); `app.py` parses clean.

Detail in [ARCHITECTURE.md §9](ARCHITECTURE.md).

---

## 2026-07-06 — A `/` or `\` in an assignment name no longer orphans its marks on the round-trip

- **Symptom:** an assignment whose name contains a slash or other
  filesystem-illegal character — e.g. `Maquette / Mock Up` — graded fine in CGW
  but its marks never synced back. Instead of updating the folder-backed row,
  Sync spawned a **duplicate** with the character flattened to `_`
  (`Maquette _ Mock Up`), which absorbed the marks while the original kept its
  stale grades (its count stuck at 0). Deleting the duplicate and re-exporting
  didn't help — the marks still wouldn't appear.
- **Root cause — two independent gaps:**
  1. **The CAM⇄CGW join is name-keyed, but the round-trip can't preserve this
     name.** CGW names each export CSV after CAM's assignment name, first running
     it through a filesystem-safe sanitizer (`re.sub(r'[\\/*?:"<>|]', "_", …)`,
     mirrored by CAM's `_safe_dirname`). So `Maquette / Mock Up` leaves as
     `Maquette _ Mock Up_Grades_<date>.csv`. Sync derives the assignment name
     back from that filename (`clean_assignment_name`) and matched on an exact
     `a.name` — which no longer equalled the original — so `_ingest_cloud_file`
     purge-replaced *nothing* and appended a fresh `_`-mangled orphan with no
     `folder_ref`. (Same failure class as the 2026-07-05 rename work below, but
     that fix carried the *unchanged* name across; here the filesystem mangles
     it, so carrying it isn't enough.)
  2. **Deleting an assignment didn't forget its Sync registry rows.**
     `delete_assignment_permanent()` dropped the record and scores but left the
     file's `ingested_files` entry intact. Because Sync dedups on **content
     hash** (`_file_fingerprint`, md5), a byte-identical re-export of an
     already-registered file is skipped ("already in the database") — so the
     ingest, and any fix, never runs. This is why deleting the duplicate and
     re-exporting did nothing: the file was permanently "already ingested".
- **Fix:**
  - **Round-trip rebind (`_rebind_import_name`).** Before the purge/ingest,
    `_ingest_cloud_file` re-maps the filename-derived name back to the existing
    assignment whose name matches it *through the same sanitize→clean round-trip*
    (`clean_assignment_name(_safe_dirname(a.name)) == incoming`). A folder-backed
    original outranks a `_`-mangled orphan a past sync left behind, and an exact
    name match breaks any tie (an assignment literally named `Maquette _ Mock Up`
    keeps its own row). The graded import then updates the real folder-backed
    assignment **in place**, `folder_ref` and all. `_sync_stamp_completeness`
    uses the same rebind so the Awaiting-Grade flag stamps the right row too.
  - **Delete now releases the file.** `delete_assignment_permanent()` forgets the
    `ingested_files` rows feeding the deleted assignment (matched by the same
    round-trip key, scoped to the assignment's class), so a later re-export/Sync
    re-ingests instead of skipping the file as unchanged — mirroring what
    `delete_class()` already did per class.
- **One-off remediation for an already-stranded file:** because the stale
  registry row predated the delete-fix, the code fix alone couldn't re-ingest
  it. The single `ingested_files` entry for the affected CSV was removed by hand
  (database backed up first), CAM restarted onto the fixed code, and one 🔄 Sync
  then landed the marks on the original row. Going forward the delete-fix makes
  this automatic.
- Verified: the sanitize→clean round-trip is symmetric for `/`, `\` and `:`
  (isolated check); the rebind selects the folder-backed original over an orphan
  and respects an exact match; live fix confirmed — 18 marks moved onto
  `Maquette / Mock Up` (count 0 → 18) with its folder pin intact, and the
  separate `Maquette/Mock Up (Reflection)` sibling untouched.

Detail in [ARCHITECTURE.md §8](ARCHITECTURE.md) (new "filesystem-illegal
character" invariant beside the rename invariant) and
[DATA_DICTIONARY.md §B.2](DATA_DICTIONARY.md) (`cam_name` → sanitized export
filename).

---

## 2026-07-06 — "Awaiting Grade" unlocks once folder grading is complete (missing folder work now counts as 0)

- **Symptom:** Window 3 showed a permanently disabled **⏳ Awaiting Grade**
  pill for *any* folder-backed assignment (`folder_ref` set) where the focused
  student had no score. A teacher could never open the edit dialog to excuse a
  student who never submitted — a mid-year transfer, a school-approved absence —
  because the locked pill was the only row that work ever produced. The pill
  also couldn't tell "this folder is still being graded" apart from "grading is
  finished and this student simply handed nothing in": both looked identical and
  both stayed locked forever.
- **Root cause:** when CGW's export CSV was synced into CAM, rows with files but
  a blank grade produced no score at all (`_coerce_grade` returns `None`, the
  row is skipped), so CAM never learned which students had submitted or whether
  grading was finished. That information was sitting unused in the CSV's
  **File Count** and **Files (newest first)** columns. With no signal, the only
  safe behaviour was to keep every scoreless folder row awaiting — the fix
  behind the 2026-07-05 *"never a fake 0"* entry — which correctly stopped
  inventing 0s but left the excuse path permanently blocked.
- **Fix — a two-state rule driven by a new `grading_complete` flag:**
  - **New field.** `Assignment.grading_complete` (`engine/models.py`,
    serialized/deserialized in `engine/persistence.py` exactly like
    `folder_ref`, defaulting to `False` so old databases load unchanged).
  - **Read-only completeness pass in Sync.** `sync_from_cloud()` now computes
    completeness for **every** CSV it encounters — newly ingested, modified,
    *and* files skipped as unchanged — and stamps the flag onto the matching
    folder-backed assignment (located by cleaned filename + class). An
    assignment is *complete* when, in its most recent CSV, every **submitted**
    row (File Count > 0, or a non-empty Files cell, or — for a legacy CSV
    lacking both columns — every row) has at least one non-blank cell among the
    `Grade*` columns. The pass is **strictly read-only on the CSV**: it parses
    the rows but never calls `ingest_csv` and never purges an unchanged
    assignment — re-ingesting an old CSV would purge-replace the record and
    destroy grades the teacher edited in CAM since the last export, the exact
    data-loss bug the 2026-07-05 round-trip work fixed. Running the pass on
    already-synced files means one press of 🔄 Sync unlocks assignments whose
    CSVs predate this fix, with no re-export from the workspace. Exam CSVs are
    skipped — they never gate this pill.
  - **The gate moves from `folder_ref` to `folder_ref AND NOT grading_complete`.**
    A single helper `awaiting_grade(row)` is the one predicate, used at all four
    sites so it can never drift: `missing_assignment_rows()` (the gate for the
    trend, grade math and AI prompt), the Window 3 cockpit rows, the report
    export's marks table, and Window 2's missing-work ⚠ popover.
  - **Physical-zero decision.** Once grading of a folder completes, a scoreless
    student falls through to the **same Missing = 0 policy** non-folder tasks
    already use: one editable **"0 (missing)"** row per criterion in Window 3
    (click to enter a mark or tick Excused), and a **real mathematical 0**
    injected into the trend, the grade calculations and the AI prompt until the
    teacher acts. This is deliberate, implemented identically to existing
    missing rows with no softer variant, so unsubmitted folder work is noticed
    quickly — the teacher then either excuses the student or chases the work.
    Excused students leave the math entirely, as before.
  - **Self-correcting.** A later export that adds a new ungraded submission (a
    late submitter) flips `grading_complete` back to `False` on the next Sync,
    and scoreless students show the Awaiting pill again.
- Verified with 22 automated checks (sandboxed temp DB + synthetic CSVs, no
  live data touched): incomplete → awaiting + excluded from the math; complete →
  clickable 0 (missing) + 0 injected + Excused removes it; unchanged-file stamp
  without re-ingest (a CAM-edited band absent from the CSV survives); regression
  flip on a new ungraded row; legacy-CSV fallback; exam CSV never stamps;
  old-format database loads with the field defaulting to `False`.

Detail in [ARCHITECTURE.md §8](ARCHITECTURE.md) (rewritten "Awaiting Grade"
subsection: the two-state rule and the read-only completeness pass) and
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) (Part A: File Count / Files now consumed
for completeness; the new `grading_complete` field on the Assignment record).

---

## 2026-07-05 — Renaming a folder-backed assignment survives the round-trip; workspace no longer orphans

Follow-ups to the same-day round-trip work below. Two independent fixes.

### 1. Renaming an assignment in CAM now propagates to CGW and Sync

- **Symptom:** teacher renames a folder-backed assignment in Window 1's Manage
  menu (e.g. `Technique Studies (Crit B)` → `Technique Studies`, dropping the
  redundant criterion tag). Grading in CGW still shows the *old* name and
  exports `Technique Studies (Crit B)_Grades_<date>.csv`. Sync then ingests a
  **second** assignment under the old name — the renamed one gets no scores,
  and the new one is "not a folder assignment" (no `folder_ref`).
- **Root cause:** the CAM⇄CGW join is **name-keyed** and assumed *assignment
  name == physical Drive folder name*. `rename_assignment()` deliberately never
  renames the Drive folder (see ARCHITECTURE §2), so a rename broke that
  assumption in two places: (a) CGW named its export CSV from the physical
  `folder_name`, so Sync's filename→name derivation landed on the old name;
  and (b) even had the name matched, Sync's purge-and-reingest
  (`_ingest_cloud_file` → `_purge_assignment_in_class` → `ingest_csv`) dropped
  the record's `folder_ref`, and Watch only re-adopts a folder when
  `folder_name == assignment name` — which the rename broke — so it stayed
  scoreless *and* respawned the old-named duplicate.
- **Fix — carry CAM's display name across, and keep the folder pin welded on:**
  - **CGW adopts CAM's name.** CAM already stamps its current assignment name
    into the `cam_grades_<folderId>.json` handoff file (DATA_DICTIONARY §B.6).
    `load_cam_published_name()` reads it; `api_load` stores it as
    `STATE["cam_name"]` and persists it in the cache entry (`cam_name`, §B.2)
    so it survives the handoff file's consumption and later manual reloads.
    `api_export` names the CSV after `cam_name` when set (falling back to
    `folder_name` for non-CAM use), so a rename flows straight into Sync and
    updates the renamed assignment **in place**.
  - **CGW header shows the CAM name.** `api_load` returns `cam_name`; the
    frontend titles the grading header with it. The assignment **dropdown**
    stays folder-named on purpose — it lists the real Drive subfolders, and
    only the loaded one has a known CAM name.
  - **CAM preserves `folder_ref` through Sync.** `_ingest_cloud_file` now
    captures the prior copy's `folder_ref` *before* the purge and re-stamps it
    onto the freshly-ingested record, so a graded folder assignment stays
    folder-backed across every round-trip and Watch never spawns a parallel
    row (ARCHITECTURE §8 invariant).
- **Note:** CGW is a long-lived `debug=False` process with no auto-reload, so
  the CGW-side changes only take effect after the workspace is restarted (see
  fix 2 — a full CAM restart now does this for you).

### 2. The Flask workspace no longer lingers as an orphan process

- **Symptom:** CGW runs as a windowless background `python.exe` on port 5001,
  spawned by CAM. Closing its Chrome tab (only a viewer) left the server
  running; Ctrl-C on CAM's terminal orphaned it too (Windows does not kill
  `subprocess.Popen` children with the parent). Orphans accumulated across CAM
  restarts and, being stale code, silently served old behaviour.
- **Fix:** `_bind_workspace_to_cam()` ties the child's lifetime to CAM's with
  two layers — an `atexit` handler for graceful shutdown (Ctrl-C / normal
  exit), and a **Windows Job Object** with `KILL_ON_JOB_CLOSE` for hard kills
  where `atexit` never runs (`taskkill /F`, closing the terminal). Verified in
  isolation: hard-killing the parent takes the child with it.
- **Deliberately kept warm, not per-assignment.** Cold start is ~6 s (Flask +
  Google libs + PyMuPDF + OAuth). CGW is spawned lazily on the first handoff
  and then reused across assignments in the session, so each subsequent *Grade
  This* is instant; an idle-exit timeout was considered and rejected to avoid a
  mid-session teacher returning to a cold app. A pre-existing orphan already on
  5001 when CAM starts is **not** adopted (CAM didn't spawn it) and needs a
  one-time manual kill.

---

## 2026-07-05 — CAM is the single source of truth: two-way grade round-trip + "Awaiting Grade" in Window 3

Two related data-integrity fixes to how grades move between the dashboard
(CAM) and the grading workspace (CGW).

### 1. Partial re-grades in CGW no longer wipe grades edited in CAM

- **Symptom:** teacher grades a class in CGW, exports, Syncs into CAM, then
  fixes a couple of students' bands in CAM Window 3. Later they re-grade a
  *different* student in CGW and export again — and the CAM edits are gone.
- **Root cause:** grades flowed one way. CGW never read what CAM held, so a
  re-export was built on CGW's own stale state; Sync's whole-assignment
  purge-replace (`_ingest_cloud_file` → `_purge_assignment_in_class`) then
  faithfully replaced CAM's newer values with it.
- **Fix — close the loop, CAM's copy is authoritative:**
  - **CAM publishes at handoff.** `launch_grading_workspace()` now calls
    `_publish_workspace_grades()` after `_seed_workspace_class()`: CAM's
    current bands + comments for the target assignment go into
    `[db folder]/[class]/cam_grades_<folderId>.json` (schema:
    DATA_DICTIONARY §B.6). A publish failure cancels the launch.
  - **CGW reconciles on load.** `api_load` merges the file over its own
    saved state: any band that differs from its last-export baseline was
    changed in CAM → the value (and comment) is adopted and the work is
    flagged **MODIFIED** — a large marker before its grades in the matrix
    and on its card, plus an instruction above the checklist to re-check it
    (CAM carries only the final 0–8 band, not the checklist detail).
    Markers persist (cached per student as `cam_modified`) until clicked
    away or exported. The file is **consumed** (deleted) once the merged
    state is persisted, so a stale copy can never overwrite later marking.
  - **CGW exports the full snapshot.** `api_export` carries every held band
    forward: columns widen to all criteria that actually hold grades, and
    CAM-graded students with no files in the folder (`cam_extra`, e.g. after
    Watch adopts a manually-graded assignment) are appended as extra rows —
    so purge-replace on Sync loses nothing. A successful routed export
    clears all MODIFIED markers.
- Verified end-to-end (Flask test client + engine ingest, 31 checks): grade
  → export → sync → edit two students in CAM → relaunch shows exactly those
  two MODIFIED with CAM's values → re-grade a third in CGW → export → CAM
  holds the new grade AND both CAM edits.

### 2. Window 3 "⏳ Awaiting Grade" — folder-backed work is visible, and never a fake 0

- **Symptom:** Window 1 listed every assignment but Window 3 silently
  omitted any assignment with no score for the focused student and no
  criteria — exactly what Watch creates from a work folder. The teacher saw
  a full list in one window and a partial list in the other.
- **Change:** Window 3 rows now have three states: editable mark(s) as
  before; a read-only **⏳ Awaiting Grade** chip for a folder-backed
  (`folder_ref` set) assignment with no score; and the editable
  **0 (missing)** rows only for criteria-bearing tasks with no work folder.
  The math matches the display: `missing_assignment_rows()` skips
  `folder_ref` rows, so awaiting work injects no 0 into the trend, the
  grade panel, the AI prompt or the report exports (the report's marks
  table shows an *awaiting grade* row; Window 2's ⚠ popover tags such items
  *(awaiting grade)*). Grades for folder-backed work arrive only through
  the round-trip above.

Detail in [ARCHITECTURE.md §8](ARCHITECTURE.md) (rewritten: publish →
reconcile → export loop, Awaiting Grade) and
[DATA_DICTIONARY.md](DATA_DICTIONARY.md) (§B.2/B.3 cache additions, new
§B.6).

---

## 2026-07-05 — Grading-workspace startup: missing dependency no longer masquerades as a Drive/OAuth failure

**Symptom:** clicking 🔗 Connect Google Drive (or any Grade/Exam handoff)
opened `http://127.0.0.1:5001/signin` in the browser and showed
*"This site can't be reached — ERR_CONNECTION_REFUSED"*. It looked like an
OAuth/credentials problem, but the credentials were fine.

**Root cause:** the Flask grading workspace crashed on startup because
**PyMuPDF (`fitz`) wasn't installed** — `cam_grading_workspace/app.py` imports
`exam_engine`, which imported `fitz` at module top level. The port therefore
never opened. Two things then hid the real error: `exam_engine` needed `fitz`
just to *load* (even for the OAuth path, which uses no PDF handling), and
`_ensure_workspace_running()` returned `True` regardless of whether the port
came up, so CAM opened a browser tab to a server that wasn't there. The root
`requirements.txt` also never pulled in the workspace's own deps, so a fresh
install (here, a Python 3.14 env) silently lacked PyMuPDF.

**Fixes:**
- **Lazy `fitz` import** (`cam_grading_workspace/exam_engine.py`): PyMuPDF is
  now imported on demand via `_fitz()`. A missing PyMuPDF breaks only the two
  PDF paths (`page_count`, `load_page_image`) with a `RuntimeError` naming the
  fix — the workspace, and OAuth sign-in, boot fine without it.
- **Honest startup check** (`_ensure_workspace_running()` in `app.py`): the
  spawned sub-app's output is captured to
  `cam_grading_workspace/workspace_startup.log`; if the port never opens within
  ~10 s the function returns `False` and the status banner shows the log's last
  line (usually the `ImportError`) plus the log path — instead of silently
  returning `True`.
- **Dependency install unified**: root `requirements.txt` now includes
  `-r cam_grading_workspace/requirements.txt` (which already pins
  `PyMuPDF>=1.24`), so one `pip install -r requirements.txt` covers both
  processes. `workspace_startup.log` added to `.gitignore`.

Detail in [ARCHITECTURE.md](ARCHITECTURE.md) §1 (launch bridge) and §4 (Exam
Slicing).

---

## 2026-07-04 — App-wide button-size standardization (two-tier control sizing)

UI only; no schema or data-flow changes. Rules documented in
[UI_STYLE_GUIDE.md](UI_STYLE_GUIDE.md).

- **Every command button now shares one SHORT height (~28 px).** Buttons had
  drifted into two sizes: `st.button`s rendered compact, but any button given
  a `help=` tooltip (deliverable **Build** buttons, 🔄 Sync, 👁 Watch,
  🔗 Connect Google Drive, ✎ Add / Edit class, "Generate for whole class",
  missing-mark cells), every `st.download_button` (the ⬇ deliverable
  downloads) and every `st.form_submit_button` (**Save settings**, **Save
  changes**, **Create**, **Apply**) rendered at the taller default (~40 px).
  Root cause for the tooltip case: `help=` wraps the button in a tooltip
  container, so `DENSE_CSS`'s `.stButton > button` (direct-child) rule never
  matched. Fix: one grouped descendant rule sizes `.stButton`,
  `.stDownloadButton` and `.stFormSubmitButton` buttons identically.
- **TALL tier (~40 px) reserved for fields and pickers.** Dropdowns, text
  inputs, popover triggers (Remarks, ⚠ missing-work) and uploader buttons
  keep Streamlit's default field height. The read-only **MYP / School grade
  chips** are bumped `2rem → 2.5rem` to exactly match the Effort selectbox in
  their row — kept deliberately big for easy copy/paste.
- **All file-upload dropzones now share one grey container.** The Window 2
  roster dropzone was compacted (`min-height: 2.2rem`) and looked squashed
  next to the Upload & stage files modal's default-height ones. A single
  global rule now pins every dropzone to the default `4.25rem` box with the
  ⬆ Upload button flush left and vertically centered (Streamlit's default is
  top-aligned); the roster-specific compaction rule is gone.
- **Mixed-height rows center on their midlines.** Added
  `vertical_alignment="center"` to the rows that lacked it: archived-
  assignments (Restore / Confirm / Delete), Window 3 mark-cell rows
  (caption + mark chip), and the AI deck's LLM-parameters and generate rows.

## 2026-07-04 — ✎ Add / Edit class dialog + roster-upload centering (supersedes parts of the entry below)

Two teacher-facing UI changes; no schema or data-flow changes.

- **Roster upload chip now truly vertically centred (Window 2).** The earlier
  fix (below) set `justify-content: center` on the dropzone but the chip still
  hugged the top of the grey box. Two causes, both DOM drift in the current
  Streamlit build: (1) the uploaded file renders inside a
  `[data-testid="stFileChips"]` container — the old `stFileUploaderFile`
  selectors matched nothing, so the redundant **"+" add-another** button
  (`stBaseButton-borderlessIcon`) stayed visible under the chip and pushed it
  up; (2) hiding only the *inner* div of the drag-drop instructions left a
  zero-height flex item that skewed the centring. Fix: hide the whole
  instructions node and the "+" button, and stretch `stFileChips` full-width.
  The chip's own ✕ remove button is a different button kind and is untouched.
  Verified in-browser: equal gaps above/below the chip in both empty and
  file-chosen states, matching the Upload modal's alignment.
- **Class lifecycle consolidated into one ✎ Add / Edit class dialog (top
  bar).** The ⚙ Settings **Class name** rename section (added below) let a
  teacher rename a class but not touch its other fields (grade level, MYP
  year, subject, master directory). It is removed, and the separate **➕ Add
  class** button is gone too: one top-bar button opens a single dialog
  (`class_dialog`) with a two-button mode toggle at the top — **✎ Edit
  current class** (the default every time it opens) or **➕ Add a class** —
  where the selected mode's button renders red (`type="primary"`) so the
  active mode is unmistakable. Both modes share one form body
  (`_class_dialog_body(edit=...)`, per-mode widget keys so flipping the
  toggle never carries half-typed values across). Edit mode pre-fills every
  field from the *active* class and saves through `update_class()` —
  `rename_class()` (so a rename still moves every name-keyed store together)
  plus the descriptive fields. Window 1's **📁 Class folder** expander is
  gone too: **👁 Watch**, the **🔗 Connect Google Drive** sign-in button and
  the long master-directory / Google-setup instructions (now an `ℹ` expander)
  all live in the dialog. **Saving a new or changed master directory runs
  Watch automatically in both modes** — pasting a folder into a brand-new
  class and adding one to an existing, already-graded class behave
  identically; Watch's adoption rule (see 2026-07-03 §3) stamps the folder
  onto same-name rows created via ➕ Add assignment/exam instead of
  duplicating them. On a failed scan (e.g. a Drive ID before the one-time
  sign-in) the save still stands and the status banner names the fix. The
  👁 Watch button (Edit mode, acting on the *saved* directory, outside the
  form) remains for rescanning after new subfolders appear. **Connect Google
  Drive shows
  in both modes** — the sign-in writes a device-wide `token.json` and is not
  class-specific, so a first-time user can sign in *before* creating their
  first Drive-backed class (in Edit mode it appears when the saved master
  directory is a Drive ID; in Add mode always, with a caption noting it's
  only needed for Drive folder IDs). A legacy class with no MYP year shows
  **(not set)**
  and keeps it on Save — the rubric phase keeps falling back to the unit plan
  instead of being silently stamped MYP 1. The now-orphaned
  `set_class_master_dir()` helper was removed (master-dir edits flow through
  `update_class`).

---

## 2026-07-04 — Window UI polish (rename class, Manage modal, roster upload, grade chips)

Four small teacher-facing UI improvements; no schema or data-flow changes.

- **Editable class name.** The ⚙ Settings dialog now has a **Class name**
  section that renames the *active* class in place. New helper
  `rename_class(old, new)` (`app.py`, beside `create_class` / `delete_class`)
  moves **every reference keyed by the class name together** — the class entry,
  its roster, archived students, unit plan, each assignment's `class_name`, the
  cloud-sync registry rows (`ingested_files[*]["class"]`), the `active_class`
  pointer, and the on-disk data folder (`class_data_dir`, best-effort
  `os.rename`; recreated empty if the move fails). Blank or duplicate names are
  rejected. Previously a class name was fixed at creation with no rename path.
- **Manage menu is now a centered modal, not a row popover.** Window 1's per-row
  **⋯ Manage** control was a `st.popover` anchored to the narrow Manage column;
  on a small screen BaseWeb positioned it partly off-screen (negative `left`)
  and it clipped. It is now a proper `@st.dialog` (`manage_assignment_dialog`),
  centred and width-independent of Window 1, so rename / due-date / term-inclusion
  / archive are always fully reachable. (A CSS `min-width` on the popover body was
  tried first but fought the popover's own positioning — the dialog is the clean
  fix, and it leaves the other two popovers untouched.)
- **Roster upload tidy-up (Window 2).** A small reminder caption under the
  uploader states the file must be a Google Classroom CSV export (roster *or*
  assignment grades), matched by the numeric ID in each email. The uploader is
  a single-file input (now `accept_multiple_files=False` explicitly — it was
  already the default), and its content is **left-aligned and vertically
  centred** against the **Apply** button. The Streamlit dropzone is a flex
  *column*, so the alignment is set with `align-items: flex-start` (left) +
  `justify-content: center` (vertical) — an earlier pass used
  `align-items: center`, which on a column axis centred it *horizontally* by
  mistake. Once a file is chosen its name fills the grey box: the chip is
  stretched full-width and the now-redundant browse button is hidden
  (`dropzone:has(…File) > button`), so the file is swapped via its ✕ then a
  fresh upload rather than a misleading "add another" control.
- **MYP / School grade chips (Window 3).** The read-only **MYP Grade** and
  **School Grade** numbers, previously bare bold text hard against the column's
  left edge, now render in a rounded bordered box (`.cam-grade-box`, helper
  `_grade_chip`) matching the criterion selectboxes above them — but with **no
  fill** so they read as display-only, not editable.

---

## 2026-07-04 — Automatic MYP Grade & School Grade on Window 3 + exports

- **Symptom:** Every term the two report-card numbers — the **MYP Grade** and
  the **School Grade** — had to be worked out by hand from each student's
  final criterion grades and copied into the school's report-card app, a slow
  and error-prone manual lookup.
- **Change:** CAM now computes both. The School lookup tables
  (`MYP_GRADE_BOUNDS`, `SCHOOL_GRADE_BOUNDS` — fixed school policy, not IB's
  method) plus pure helpers `myp_grade()` / `school_grade()` live in
  `engine/aggregation.py`. Both are banded lookups on the sum of the term's
  final criterion grades, table chosen by how many criteria were assessed
  (2/3/4; anything else shows N/A). A new per-term **Effort / English Use**
  score (0–5, default 4, persisted as `effort_by_term` alongside
  `comments_by_term`) feeds the School lookup only. One shared helper —
  `student_term_grades()` in `app.py`, resolving each criterion exactly as
  the grade panel (override if locked, else auto band, rounded to ints) —
  drives **Window 3** (new one-line row: Effort selectbox + read-only
  MYP/School grades), the **Excel master** Tab 1 (three new columns after
  `Crit A..D`), and the **report-card pack / single report** (three rows
  appended to the "Final criterion grades" table), so UI and exports can
  never disagree. Out-of-range totals clamp to the lowest/highest band, so an
  all-missing 0 maps to grade 1 rather than crashing. See
  [ARCHITECTURE.md §9](ARCHITECTURE.md) and
  [DATA_DICTIONARY.md Part C](DATA_DICTIONARY.md).
- **Also:** the calculation-method dropdown labels now carry usage hints
  (e.g. *"60/40 Recency (Best for < 10 assignments)"*) via a display-only
  `format_func` + `METHOD_LABELS`; the stored `calc_method` values and
  dropdown order are unchanged.

---

## 2026-07-03 — CAM ↔ Grading Workspace round-trip

A cluster of fixes to the handoff between the Streamlit dashboard (CAM) and the
Flask grading workspace (CGW). All relate to grades marked in CGW failing to
reach CAM, or corrupting the timeline once they did.

### 1. Grades marked in CGW never reached CAM's Sync

- **Symptom:** After grading in CGW and clicking **🔄 Sync** in CAM, the
  dashboard reported *"All N file(s) already in the database — nothing new to
  sync."* Grades, deadline and submission counts never appeared.
- **Root cause:** CGW writes its CSV exports into `class_output_dir()` =
  `[cloud_dir]/[class]/`. CAM's Sync scans `db_folder()/[class]/`. The launch
  bridge (`_seed_workspace_class`) seeded only the class → Drive-folder-ID map,
  never `cloud_dir`, so CGW fell back to its own app root and exports landed
  somewhere CAM never scanned (or streamed as a browser download).
- **Fix:** `_seed_workspace_class` (`app.py`) now also seeds
  `cloud_dir = db_folder()` on every handoff (skipped only when no custom
  database path is set, and when the workspace already points at the same
  folder). Exports now route into the folder Sync scans.

### 2. Sync appended a duplicate assignment → render crash

- **Symptom:** `StreamlitDuplicateElementKey: key='act_Term 1_<name>'` crashing
  Window 1.
- **Root cause:** The CAM→CGW handoff leaves a manual *placeholder* assignment
  on the timeline. A first-time sync of that assignment's CSV **appended a
  second record** of the same name+class; the timeline keys per-row widgets on
  the name, so two records collide.
- **Fix (two guards):**
  - `_ingest_cloud_file` now **always** purges a prior same-name assignment in
    the class before ingesting (not only on a file re-sync), so the graded
    import updates the placeholder in place.
  - `_dedupe_assignments()` runs every rerun in `main()`, collapsing any
    pre-existing name+class duplicates (keeping the richest record) and
    persisting once — self-healing databases that already picked one up.

### 3. Ingested grades silently vanished (scoreless placeholder)

- **Symptom:** A synced assignment showed **Subs 0** with no grades even though
  the CSV had marks and the sync registry recorded it as ingested; re-syncing
  did nothing (the registry hash matched, so the file was skipped).
- **Root cause:** Class-folder **Watch** (`_watch_class_master`) pins
  assignments by `folder_ref`; **CSV ingest** keys by name with no `folder_ref`.
  The same real assignment became two records — graded `"X"` (no ref) beside a
  watched `"X (2)"` placeholder. Because scores are stored on students **by
  name**, a later always-replace purge of `"X"` dropped the scores while the
  placeholder lingered, leaving a scoreless row and orphaned grades.
- **Fix:** Watch now **adopts** — when a scanned subfolder's name matches an
  existing *unpinned* assignment in the class, it stamps `folder_ref` onto that
  record instead of creating a parallel `"X (2)"`. Graded assignment and source
  folder stay one record; Watch skips it on every later pass. See
  [ARCHITECTURE.md §8](ARCHITECTURE.md) → *"Watch and CSV-ingest describe ONE
  assignment"*.
- **Data repair:** affected databases need the lost scores re-ingested once
  (re-run the CSV through `ingest_csv`, pin the resulting assignment's
  `folder_ref`); the always-adopt guard prevents recurrence.

### 4. CGW Settings hardened to read-only

- **Change:** Now that CAM manages `cloud_dir` and the class map (§1), the CGW ⚙
  Settings dialog **displays** them read-only rather than letting a teacher edit
  them. Removed: *Save Settings*, *+ Add class*, *Refresh Classes*, rename,
  delete. Kept editable: device-local **Theme**.
- **Why:** A manual edit in CGW could silently misroute exports or invent a
  class the dashboard didn't know about — the exact drift the seeding is meant
  to prevent. The `POST /api/config` endpoints remain (CAM's seeding uses them);
  only the workspace's own editing controls were withdrawn.
