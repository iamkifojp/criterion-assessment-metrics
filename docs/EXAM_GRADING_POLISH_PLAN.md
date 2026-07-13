# Exam Grading Polish Plan — v1

**Implementer:** Claude Opus 4.8 on High reasoning.
**Scope:** `cam_grading_workspace/app.py` (Flask CGW) + `cam_grading_workspace/exam_engine.py`; Phase 7 touches CAM's root `app.py`; Phase 8 touches `docs/USER_MANUAL.md`.
**Origin:** 8 teacher feedback items from live-testing the exam slicer (2026-07-13,
Test MYP Class, smiletutor sample PDF).

Read `CLAUDE.md` first. The CGW writes exam grades into the **class cloud
folder** — test only against the Test MYP Class / CAM Test Folder sandbox, never
a real class. Follow the sandbox rules before launching anything.

---

## Teacher decisions (locked defaults — change only if the teacher says so)

| # | Decision | Default |
|---|----------|---------|
| D1 | Grid colour choices | Neon green `#39FF14` (default), bright blue `#00BFFF`, bright magenta `#FF00E5`; stored **per device** (`localStorage`, key `gcg_grid_color`) |
| D2 | Cell-label look | Bold, centred in the cell, ~40% opacity, no text-shadow, sized ≥50% of cell height |
| D3 | Single-question grading sheet | Show only the current question's score column, plus Keywords and Comment. **No running totals anywhere in the exam grading UI** (roster cards included) — a visible total reinforces bias while later questions are still being graded. Totals live only in the export/CAM. Completion shows as "N of M questions" / the graded tick |
| D4 | Exam keyword template | `illegible handwriting`, `more explanation needed`, `wrong format`, `incomplete answer`, `check calculations` — all type "growth"; editable per exam like the assignment checklist |
| D5 | Portable exam data layout | Crops → `<cloud>/<class>/exam_crops/<exam>/<Q>/<student>.png`; definitions → `<cloud>/<class>/gcg_exams.json`. Legacy local paths remain a read fallback; never delete legacy data on migration (deletion happens only via Phase 7's explicit purge) |
| D6 | Anonymous exam display (YouMark style) | **No stable per-student alias.** Cards/rows are numbered by *position* — `01`, `02`, … (a progress counter, not an identity) — and the order is **re-shuffled per question** (seed = class+exam+question label, so stable on reload, different across questions). A teacher never meets "student 3" twice, so no prejudice can accumulate across questions |
| D7 | Exam permanent delete scope | "Delete permanently" on an **exam** assignment in Window 1's Archived dialog also deletes: crop tree (new + legacy roots), the exam definition entry, `exam_grades_<exam>.json`, and the exported CSV + `.meta.json`. The CSV must go or watch-folder sync resurrects the assignment. All behind the existing Confirm checkbox, with the dialog text listing what will be removed |

---

## Phase 1 — Grid legibility: colour picker + big translucent cell labels (item 1)

All in `EXAM_SETUP_PAGE` (HTML/CSS/JS string in `app.py`).

1. **Colour selector.** Add a `<select id="gridColorSelect">` immediately right of
   `#gridSelect` in the Paper size / Grid field row, with the three D1 options
   (labels "Neon green", "Bright blue", "Bright magenta"). Persist to
   `localStorage["gcg_grid_color"]`; default neon green. On change, set a CSS
   variable `--gridcol` on `#gridOverlay` (or `:root`) and nothing else — all
   colouring below reads that variable.
2. **Grid lines.** `.gcell` border becomes the chosen colour at partial alpha
   (e.g. `color-mix(in srgb, var(--gridcol) 65%, transparent)` or an rgba built
   in JS). Keep `1px dashed` — density, not weight, was the complaint.
3. **Cell labels.** Rework `.glab`:
   - `inset:0; display:flex; align-items:center; justify-content:center;`
     (centred, filling the cell), `font-weight:800`, `color:var(--gridcol)`,
     `opacity:.4`, **no text-shadow**.
   - Size dynamically: after the page image loads (and on window resize /
     density change / fit-mode change), compute
     `cellH = overlay.clientHeight / NROWS` and set
     `overlay.style.setProperty("--glabsize", Math.round(cellH * 0.55) + "px")`;
     `.glab { font-size: var(--glabsize); }`. Drop the per-density static
     font-size rules — the computed size replaces them. Clamp to a minimum of
     9px so fine grids on small windows stay renderable.
4. Question-range highlight tints (`Q_COLORS` backgrounds) are untouched — they
   must stay distinguishable from the grid colour.

**Verify:** load the sample folder, switch density and colour, confirm labels
recentre/rescale and the choice survives a reload.

## Phase 2 — Setup form ergonomics (items 2 & 3) — ✅ Done

Implemented in `EXAM_SETUP_PAGE` (`cam_grading_workspace/app.py`): `Section:`
label + `.seclabel` style on section rows; question column header `Score` →
`Max mark`, placeholder/default `0-3` → `3`, `loadExamConfig` now fills the raw
`q.max`, and the hint reads "Max mark is the highest score, e.g. **3**." Backend
`parse_max_score` was left untouched (still accepts both `3` and `0-3`).

1. **Section rows** (`addSectionRow`): add a visible text label `Section:`
   before the name input (the pre-filled "All Questions" default hides the
   placeholder, so teachers don't know what the box is). Keep the `§` swatch.
2. **Score entry**: teachers type just the max mark.
   - Placeholder `0-3` → `3`; column header `Score` → `Max mark`.
   - `loadExamConfig` fills the field with `q.max` (not `"0-" + q.max`).
   - Hint text: "Max mark is the highest score, e.g. **3**."
   - Backend `parse_max_score` already accepts both `3` and `0-3` — do not
     change it; old-style typing keeps working.
   - Displays elsewhere (question dropdown "(0–3)", sheet header) are
     unchanged — they show the range, which is fine.

## Phase 3 — Fit width / fit page toggle (item 4) — ✅ Done

Implemented in `EXAM_SETUP_PAGE` (`cam_grading_workspace/app.py`). A persistent
`#fitToggleBtn` (revealed once a page loads) cycles `↔ Fit width` / `⤢ Fit page`;
the choice is stored per device in `localStorage["gcg_fit_mode"]`. Fit-page adds
`.fitpage` to `#pageWrap` (flex-centred) with `#pageImg { width:auto;
max-height:calc(100vh - 150px) }`, and re-runs the Phase 1 label sizing +
`applyZoom` on toggle. The old restore-view button was repurposed into a separate
`✕ Reset zoom` button (still `#zoomToggleBtn`, shown only while a `ZOOM_RANGE` is
active); the fit toggle also clears any active zoom.

Left pane of Exam Setup. Today `#zoomToggleBtn` appears only while a
swatch-zoom is active and merely clears it.

1. Add a persistent two-state toggle (one button cycling `↔ Fit width` /
   `⤢ Fit page`), visible whenever a page is loaded. Default: fit width
   (today's behaviour).
2. **Fit page:** constrain the page box so the whole page is visible in the
   left pane: put a class on `#pageWrap` (e.g. `.fitpage`) under which
   `#pageImg { width:auto; max-height: calc(100vh - <topbar+loader offset>); }`
   and the wrap centres the image horizontally. The grid overlay is
   `inset:0` on `#pageZoom`, so it follows automatically. Re-run the Phase 1
   label-size computation after toggling (cell pixel size changes).
3. **Interaction with zoom-to-selection:** swatch-zoom / focus-adjust zoom
   still works in either fit mode (it's a transform on `#pageZoom`). While a
   `ZOOM_RANGE` is active, show a separate small `✕ Reset zoom` button (the
   old restore behaviour); the fit toggle itself also clears `ZOOM_RANGE`
   when clicked.
4. Persist the fit mode in `localStorage` (nice-to-have, cheap).

## Phase 4 — Grading sheet: current question only + keyword checklist (items 7 & 8) — ✅ Done

Implemented in `cam_grading_workspace/app.py` + `exam_engine.py`.

**Single-question sheet, no totals (D3).** `renderExamTable`/`makeExamRow` now
render only `Student | <current question> | Keywords | Comment`; the ✎ adjust
button stays in the question header. Every running total is gone from the
grading UI: the sheet's Total column, the roster-card "total X/M" sub-line (now
"N/M questions" progress, or "ungraded"), and the "N marks total" in the status
line. `examTotal`/`examMaxTotal` (and their `td.qtotal` CSS) were deleted —
totals live only in the CSV export + CAM. Saved-grades shape is unchanged
(scores still keyed per label; the sheet just shows one column at a time).

**Keyword checklist in exam mode (item 8).** `#kwEditor` is no longer hidden in
`loadExam`; the editable pill editor drives exams too. Persistence lives in the
exam grades file (new shape `{"checklist":[{label,type},…], "students":{…}}` in
`exam_grades_<exam>.json`); `load_exam_grades` now returns `(students,
checklist)` and `save_exam_grades` round-trips the checklist (missing key → the
D4 default template via `default_exam_checklist`; `normalize_exam_checklist`
mirrors `_normalize_checklist`). Each exam student gained `keywords` beside
`scores`/`comment` (defaults `[]`). Comment composition reuses the assignment
`autoComment` helper verbatim. `/api/exam/grade` accepts + persists `keywords`;
new `/api/exam/checklist` persists checklist edits (frontend `pushChecklist`
routes there when EXAM is active; `remapKeywordLabel` + table re-renders branch
on EXAM). Exam CSV export appends a `Checked Keywords` column (semicolon-joined)
before `Comment` — confirmed ACM's exam ingest already reserves that header
(`engine/ingestion.py` `_EXAM_RESERVED`), so questions still resolve to Q-cols
only.

Main page, exam mode (`renderExamTable`, `makeExamRow`, `loadExam`).

1. **Single-question sheet, no totals (D3).** Render only: Student |
   *current question* score | Keywords | Comment. The `✎` adjust button stays
   in the question column header. Switching `#questionSelect` re-renders
   (already wired). Nothing changes in the saved grades shape — all scores
   stay keyed per label; the sheet just shows one column at a time.
   - **Remove every running total from the exam grading UI**: the sheet's
     Total column, `examTotal`'s "total X/31" sub-line on roster cards, and
     the "31 marks total" in the status line. Replace the card sub-line with
     progress ("3/21 questions") or just the graded tick. Totals still appear
     in the CSV export and CAM — grading-time display only.
2. **Keyword checklist in exam mode (item 8).**
   - Stop hiding `#kwEditor` in `loadExam`; the editable pill editor works for
     exams too.
   - **Persistence:** per exam, inside the exam grades file so it syncs across
     devices with the marks. New shape:
     `{"checklist": [{label,type},...], "students": {...}}` in
     `exam_grades_<exam>.json`. `load_exam_grades`/`save_exam_grades` grow a
     checklist round-trip (backward compatible: missing key → the D4 default
     template). Reuse `_normalize_checklist`.
   - **Per-student keywords:** each exam student gains
     `"keywords": [...]` beside `scores`/`comment` (persisted; valid old files
     without it default to `[]`). The sheet's Keywords cell renders the same
     checkbox pills as assignment mode.
   - **Comment composition:** mirror assignment mode's `autoComment`
     behaviour — ticking/unticking rebuilds the auto-generated part of the
     comment while preserving the teacher's free text, exactly like the
     assignment flow (reuse the same helper if practical rather than forking
     it).
   - `/api/exam/grade` accepts and persists `keywords`; a new
     `/api/exam/checklist` (or a reused `/api/checklist` branch when EXAM is
     active) persists checklist edits.
   - Exam CSV export: append a `Checked Keywords` column (semicolon-joined)
     before `Comment`, matching the assignment CSV convention. Confirm ACM's
     exam ingest tolerates the extra column before shipping (it keys columns
     by header).

## Phase 5 — Anonymous exam grading (item 6) — ✅ Done

Implemented in `cam_grading_workspace/app.py` (frontend + `/api/exam/load`).

**Server (D6, display-only).** When `anonymous_enabled()`, `/api/exam/load`
blanks every display name (`name: ""`) and adds an `anonymous: true` flag to the
payload; `key` stays the real stem. `EXAM_STATE` is never mutated (same doctrine
as `present_students()`), so `/api/exam/grade`, crop serving and the CSV export
all read real identifiers unchanged. `/api/exam/grade`'s response carries no name
field, so nothing leaks there.

**Client (YouMark-style numbering).** New `EXAM_ANON` global (set from
`data.anonymous` in `loadExam`) plus a deterministic mulberry32 PRNG over a
string hash (`examStrHash`/`examMulberry32`/`examSeededShuffle`). A single
`examView()` returns the ordered `{st,label}` pairs both the roster and the sheet
iterate, so the two screens always share one order. Anonymous on: shuffle with
seed `class|exam|CURRENT_Q` and label by position (`01`, `02`, …) — stable on
reload, re-shuffled per question, so no number ever tracks a student across
questions. Anonymous off: today's order (server-alphabetical) with real names.
`renderExamRoster`/`renderExamTable`/`makeExamRow` now take the label from
`examView()`. Toggling the pref reloads an open exam (`loadExam`) as well as an
open assignment. The settings-modal note now covers exams (positional numbering
+ real-name exports). Residue is unchanged from the assignment layer: real keys
still ride the DOM/network and handwriting can identify a student — bias
reduction, not blind review.

The device pref (`anonymous_grading`) must cover exam mode; today
`/api/exam/load` returns raw filename stems. Design is **YouMark-style
(D6)**: positional numbers, not stable aliases, re-shuffled per question.

1. **Server side** — when the pref is on, `/api/exam/load` and
   `/api/exam/grade` responses blank every display name (`name: ""`); `key`
   stays the real stem (round-trip identifiers untouched, same doctrine as
   the assignment layer — display-only copies, never mutate `EXAM_STATE`).
2. **Client side** — per-question order + numbering:
   - A deterministic seeded PRNG (e.g. mulberry32 over a string hash) shuffles
     the student key list with seed = `class|exam|CURRENT_Q`. Stable across
     reloads, **different for every question** — switching `#questionSelect`
     re-shuffles the roster and the sheet rows together (they must always
     share one order).
   - Display label = position in the current order, zero-padded (`01`,
     `02`, …). It is a progress counter, not an identity — the same student
     gets a different number on the next question, by design.
   - When the pref is off: today's behaviour (real names, alphabetical,
     no per-question shuffle).
3. Crops are served by `key`, so images still load. The `__name__` name-box
   crop is not shown in the exam roster today — nothing to hide there.
4. Grades file and CSV export keep real names (read from `EXAM_STATE`
   directly, which stays real). The settings-modal note already says exports
   stay real — extend it to mention exams.
5. Toggling the pref reloads the open assignment today; make it also reload an
   open exam.
6. Note the residue honestly (as the assignment layer does): real keys still
   ride the DOM/network and handwriting can identify a student — this is
   bias reduction, not blind review.

## Phase 6 — Portable exam data: crops + definitions into the class folder (item 5)

The structural phase — do it last, alone, with the most care. Goal: a class
whose folder is cloud-synced can be exam-graded from any device.

1. **New crop root.** `exam_crop_dir(class_name)` resolves to
   `exam_output_dir(class_name)/exam_crops` (i.e.
   `<cloud>/<class>/exam_crops/`) when the class has a cloud folder, else the
   legacy `BASE_DIR/exam_crops/<class>/` (unchanged for cloud-less setups).
   Slicing (`/api/exam/process`, `/process_one`) always **writes** the
   resolved root.
2. **Read fallback.** Crop serving (`api_exam_crop`) and the student-discovery
   scan in `/api/exam/load` try the new root first, then the legacy local
   root. Never delete or move legacy crops automatically.
3. **Exam definitions.** `ExamStore` grows a per-class portable store:
   `<cloud>/<class>/gcg_exams.json` holding `{"exams": {...}}` for that class
   only. Resolution order: class-folder store first, then the legacy
   app-local `gcg_exams.json`. Saves go to the class-folder store when a
   cloud folder exists (and continue mirroring into the legacy file is NOT
   needed — one write target; the legacy file stays as a frozen fallback).
   On first save for a class, migrate: copy that class's exams from the
   legacy store into the new file if absent there.
4. **Cross-device caveats** (document in the code + USER_MANUAL):
   - `pdf_folder` is an absolute per-device path. Grading from synced crops
     works anywhere; **re-slicing** needs the scans present at that path.
     When `/api/exam/process*` finds `pdf_folder` missing, the error message
     must say exactly that ("this device can't see the scan folder — grading
     still works from the synced crops").
   - Crop volume: ~`students × (questions+1)` PNGs per exam land in the
     cloud folder (e.g. 30 × 22 ≈ 660 files). Acceptable, but note it.
5. **Concurrency doctrine:** same as exam grades — last-writer-wins per file,
   atomic `.tmp`+`os.replace` writes for the new `gcg_exams.json`.

## Phase 7 — Permanent delete of an exam purges its CGW artifacts (D7)

Observed: deleting an exam assignment in Window 1 and purging it from the
Archived dialog left the crop images sitting under
`cam_grading_workspace/exam_crops/` — and, worse, left the exported CSV in the
class folder, which the watch-folder sync can re-ingest, resurrecting the
"deleted" assignment.

In **CAM's `app.py`** (Streamlit, repo root), extend
`delete_assignment_permanent(name)`:

1. Only for assignments with `is_exam=True` (skip everything below for normal
   assignments).
2. **Resolve the exam name.** The assignment name derives from the CSV
   filename via the sanitize→clean round-trip already used at the bottom of
   `delete_assignment_permanent` (`clean_assignment_name(_safe_dirname(name))`).
   Match against the exam names in the definition store(s) the same way; if
   nothing matches, delete nothing file-side (log it) — never guess.
3. **Delete, per class the assignment belonged to** (the `classes` set is
   already computed at the top of the function), tolerating missing paths:
   - crop tree: `<cloud>/<class>/exam_crops/<exam>/` (post-Phase 6) **and**
     the legacy `cam_grading_workspace/exam_crops/<class>/<exam>/`;
   - the exam's entry in the per-class `<cloud>/<class>/gcg_exams.json` and
     in the legacy `cam_grading_workspace/gcg_exams.json` (rewrite the JSON
     without the entry — atomic tmp+replace; delete only the one exam's
     entry, never the whole file);
   - `exam_grades_<exam>.json` in the class folder;
   - the exported `<exam>_Grades_*.csv` **and its `.meta.json` sidecar** in
     the class folder (glob on the safe-name prefix, exact suffix pattern —
     no broad wildcards).
4. **Confirmation UX:** the Archived dialog already gates on a Confirm
   checkbox. For exam assignments, the row must say what the purge includes,
   e.g. "Deletes the sliced answer images, exam definition, grading file and
   exported CSV for this exam." Build the exact path list before deleting;
   if a path is outside the expected roots, abort that path and log.
5. Restore ("Restore" button) is unaffected — archiving stays soft;
   only "Delete permanently" triggers the purge.

## Phase 8 — User manual: a real "Grading exam papers" section

`docs/USER_MANUAL.md` mentions exam grading only in passing. Add a dedicated
section walking the full loop:

1. Create the exam in Window 1 (Add assignment / exam) → 🛠 Exam setup.
2. Exam Setup: load the scan folder, grid + colour picker, sections, name
   box, max marks, Save + Process All PDFs.
3. Grading: question dropdown, one-question-at-a-time sheet, keywords
   checklist, comments, ✎ region adjust + re-slice, anonymous mode
   (YouMark-style numbering — what the numbers mean and why they change
   between questions).
4. Export CSV → CAM auto-ingest → Window 1 exam grading panel.
5. **Cloud-folder subsection (from the teacher's decision):** grading a class
   whose folder is cloud-synced makes exams portable across computers, at the
   cost of (a) sync lag after slicing — hundreds of small PNGs
   (~students × questions per exam) must upload before another device sees
   them, and (b) the disk/cloud space they occupy. Re-slicing still needs the
   scan PDFs present on that device; grading alone doesn't.
6. Deleting an exam permanently (Archived dialog) also deletes its crops,
   definition, grading file and exported CSV (Phase 7).

---

## Testing / safety notes for every phase

- Sandbox: point the CGW at the Test MYP Class only (its watch folder is the
  OneDrive **CAM Test Folder**). Never launch against a real class folder.
- The Exam Setup page and main page are giant Python string literals — keep
  the `r"""` raw-string escaping intact; no stray `"""` inside.
- After each phase, re-run the manual smoke: load sample folder → program a
  question → save → process → grade one student → export CSV → confirm ACM
  ingest still parses (phases 4+).
- `git commit` per phase, message style matching the existing history
  ("Phase N: <summary>").
