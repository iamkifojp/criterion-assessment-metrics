# Exam slicer v2, export→CAM push sync, and the comment-box fix — plan v1

**Status:** v1, planned 2026-07-12 (Fable 5 orchestration; for Opus 4.8 High to
implement in this public checkout). Six phases. Phases 1 and 2 are independent
bug fixes — land them first, one commit each. Phases 3→6 build the exam-slicer
overhaul and must land in order (3 → 4 → 5 → 6), one commit per phase.

**Read `CLAUDE.md` first** — especially the sandbox rules. Any live test run
must redirect the DB to a temp folder; the teacher's real prefs point at live
OneDrive data (`local_device_prefs.json` → `db_custom_path`). `AppTest` is
single-run only in this repo; the console is cp932 (no emoji/unicode in test
prints). Test fixtures: the fake "Test MYP Class" data in the OneDrive
"CAM Test Folder" (never real classes). The two apps: CAM = root `app.py`
(Streamlit), CGW = `cam_grading_workspace/app.py` (Flask) — same filename,
different modules; never import one as the other.

**Decisions already made with the teacher (do not re-litigate):**

1. Region adjustment during grading stays on the **spreadsheet method** — the
   grid preview on the left, the question's label + typed coordinate range on
   the right, exactly like Exam Setup. A compact "zoom to selection ± 2 cells"
   view is wanted so the teacher isn't scrolling a full page to tweak one box.
2. Over-answered choice-sections are **strict**: the section shows `?` and is
   excluded from the exam total until the teacher explicitly ticks which
   answers count. The app never auto-picks.
3. Grid densities offered for new exams: **Compact ≈1.4 cm (default)** and
   **Fine ≈1 cm** only. No 2 cm option in the UI — but exams already saved on
   the legacy 2 cm grid must keep parsing, highlighting and slicing correctly
   forever (their stored coordinates are 2 cm-relative).

---

## Phase 1 — "Sync on export": CGW beacon + CAM poller

### Problem

After grading in CGW and clicking Export CSV, the grades do not appear in CAM
Windows 1/2 until the teacher clicks around (and sometimes not even then, for
exams). Root causes, all confirmed in code:

- CAM cannot be pushed by CGW (separate processes) and Streamlit only reruns
  on user interaction. "Sync on export" is only *approximated* by
  `_run_active_launch_probe` (`app.py:4048`): it runs once per rerun, is
  throttled to 30 s (`ACTIVE_LAUNCH_PROBE_INTERVAL`, `app.py:3605`), and only
  watches the one assignment launched via 🖌 Grade This *this session*
  (`active_launch` marker, `app.py:2763–2770`).
- **Exam exports never probe at all** — "Exams don't round-trip, so they get
  no marker" (`app.py:2761–2763`). An exported exam CSV sits unseen until the
  next session-start global scan or a manual re-scan.

### Change

**CGW side — write a beacon on every successful routed export.**

- In `api_export` (`cam_grading_workspace/app.py:2493`, the branch that
  writes into the class subfolder) and `api_exam_export` (`:2926`, same
  `routed` branch), after the CSV write succeeds, atomically write
  `cam_export_beacon.json` into the **root of the cloud dir**
  (`SETTINGS["cloud_dir"]` — the same folder CAM's sync scans; CAM seeds it,
  see `app.py:2562`):

  ```json
  {"class_name": "...", "assignment": "...", "is_exam": false,
   "csv_path": "...", "ts": 1720000000.0}
  ```

  Atomic = write `.tmp` then `os.replace` (same pattern as
  `ExamStore._write`). Failure to write the beacon must never fail the
  export — wrap in try/except, log to stdout.
- Download-only exports (`?download=1`, or no cloud dir) write no beacon —
  nothing routed, nothing for CAM to pick up.

**CAM side — a `run_every` fragment that watches the beacon.**

- New function `_export_beacon_poller()` decorated
  `@st.fragment(run_every=3)` (Streamlit 1.58 supports it), called from
  `main()` right after `_run_active_launch_probe()` (`app.py:8633`). Guard: do
  nothing when no custom DB path is configured (mirror `sync_from_cloud`'s
  guard, `app.py:3832`).
- Each tick: one `os.stat` of `<db folder>/cam_export_beacon.json`. mtime
  unchanged vs `st.session_state["export_beacon_mtime"]` → return. That is
  the entire steady-state cost.
- On change: read the JSON (tolerate torn reads — OSError/ValueError → skip,
  next tick retries), then run a **scoped** sync:
  - `is_exam == False` → existing `sync_assignment(class_name, assignment)`
    (`app.py:3742`).
  - `is_exam == True` → scoped exam sync. `_assignment_csv_paths`
    (`app.py:3608`) deliberately excludes exam CSVs, so add a sibling
    `_exam_csv_paths(class_name, exam_name)` (same walk, *keeps only* files
    where `is_exam_csv(...)` and the cleaned stem maps to the exam name) and a
    thin `sync_exam(class_name, exam_name)` that feeds those paths through the
    shared `_sync_one_csv` (`app.py:3638`) exactly the way `sync_assignment`
    does. Do **not** fall back to a full `sync_all` tree walk.
  - When anything was ingested/updated: `_report_sync(summary)`, persist as
    the sync paths already do, then `st.rerun(scope="app")` so Windows 1–3
    repaint. When nothing changed: no app rerun (never yank the UI while the
    teacher is typing for a no-op).
- Keep `_run_active_launch_probe` as-is (fallback for multi-machine OneDrive
  arrivals where the beacon comes from another device with clock skew — the
  beacon file itself syncs through OneDrive too, so this mostly still works;
  the probe is belt-and-braces).
- The beacon lives in the data folder (outside git); registry/scans only look
  at `*.csv` so it can't be mistaken for a gradebook file.

### Watch out

- **Mid-grading race** (memory: late-flag loss): the scoped sync path is the
  same purge-replace `sync_assignment` used today, including the Late
  reconcile pass (bbd32f5). No new semantics — only a new trigger.
- The fragment must not touch widget state or render anything except via
  `st.rerun(scope="app")` after a real ingest.
- An app rerun *can* drop an uncommitted text edit the teacher was mid-typing
  (same as any click). Acceptable: it only fires when their own export landed.

### Acceptance

Sandboxed run (temp prefs, CAM Test Folder fixtures): grade in CGW → Export
CSV → **without touching CAM**, grades appear in Windows 1/2 within ~5 s, with
the sync banner. Repeat for an exam export — exam appears / updates in
Window 1's exam panel within ~5 s. A no-change tick causes no visible rerun.

---

## Phase 2 — Window 3: generated comment invisible until refocus (+ deletion hazard)

### Problem

With Gemini (any API provider), "Generate for <student>" reports success but
the Overall-comment box stays blank; focusing another student and back reveals
the text. Root cause: the box is a **keyed** `st.text_area`
(`key=f"resp_box_{sid}_{term}"`, `app.py:8043–8050`) whose displayed content
comes from cached widget state; the generate handler (`app.py:7974–7987`)
writes into `st.session_state["llm_response"][sid]` and calls `st.rerun()`
but never updates the widget's own key, so the stale (blank) widget state
wins over `value=`. The whole-class generator (`app.py:7988–8009`) has the
same flaw for the focused student.

**Adjacent data-loss hazard, fix in the same commit:** the change-detector
below the box (`app.py:8051–8058`) compares the widget's (possibly stale)
value against `llm_response` and, on mismatch, writes the stale value back —
a stale *blank* both trips `_mark_teacher_input_deleted()` and can overwrite
a just-generated comment. Given the 2026-07-10 comment-wipe history, this
path must become impossible.

### Change

Make the widget key the single source of truth (standard Streamlit pattern):

- Compute `resp_key = f"resp_box_{sid}_{term...}"` once. Before rendering,
  **seed** `st.session_state[resp_key]` from `llm_response[sid]` *only if the
  key is absent*. Render the `text_area` **without `value=`** (key only).
- Single-student generate: on API success, write the text to **both**
  `llm_response[sid]` and `st.session_state[resp_key]`, then `st.rerun()`.
- Whole-class generate (`_generate_class_comments`, `app.py:7890`): after the
  batch, update `st.session_state[resp_key]` for the focused student (other
  students have no live widget; seeding covers them when focused).
- Sync-back block: `overall = st.session_state[resp_key]`; only when it
  differs from `llm_response[sid]` treat it as a **user edit** (deletion
  tripwire + persist as today). Because generation now updates both sides
  atomically, a mismatch can only originate from typing.
- Check the Teacher-remarks popover box (`rem_box_*`, `app.py:8034–8042`) for
  the same pattern; it has no generator writing behind it, so it likely only
  needs the seed-if-absent treatment if touched at all — don't refactor it
  gratuitously.

### Acceptance

Sandboxed run with a real or stubbed API key (stub `call_llm_api` if no key):
click Generate → the comment appears in the box **on that same repaint**, no
student-switch needed. Generate for whole class → focused student's box
updates. Type an edit → persists; clear the box manually → deletion tripwire
fires exactly once. Generated-then-immediately-rerun flows never blank
`llm_response`.

---

## Phase 3 — Exam Setup: grid legibility + per-exam grid density

### Problem

The coordinate labels (`.glab`, 9 px, `rgba(127,127,127,.75)` —
`cam_grading_workspace/app.py:5234`) and dashed cell borders are too faint to
read against a scanned page. The ~2 cm cell (A4 10×15) is too coarse to frame
answers tightly.

### Change

**A. Legibility (CSS only, `EXAM_SETUP_PAGE`):**

- `.glab`: ~12–13 px, `font-weight:600`, colour `var(--accent)` with a
  contrast halo (`text-shadow: 0 0 3px var(--bg), 0 0 3px var(--bg)` or a
  semi-opaque background chip) so it reads on both light scans and the dark
  theme.
- `.gcell` border: brighter/denser dash (e.g. `rgba(127,127,127,.65)`).
- On Fine grids cells get small — scale the label with cell size (CSS
  `clamp()` or set a smaller class when density == fine) so labels never
  overlap.

**B. Grid density, stored per exam.** New config key `"grid"`:
`"compact"` (≈1.4 cm, **default for new exams**) | `"fine"` (≈1 cm) |
**absent/`"legacy"`** (the old ≈2 cm grid — what every already-saved exam
means). Geometry table (extend `PAPER_GRIDS` in `exam_engine.py:69` into a
two-level map, mirrored in both JS copies):

| paper | legacy 2 cm | compact ~1.4 cm | fine ~1 cm |
|-------|-------------|-----------------|------------|
| A4 (210×297)  | 10×15 | 15×21 | 21×30 |
| B5 (176×250)  | 9×12  | 13×18 | 18×25 |
| A3 (297×420)  | 15×21 | 21×30 | 30×42 |

- `grid_for(paper_size)` → `grid_for(paper_size, grid="legacy")`;
  `parse_range`, `range_to_bbox`, `process_exam`, `ExamStore.save_exam`
  validation all take the exam's grid. **A config without `"grid"` behaves
  byte-identically to today** — that is the backward-compat contract.
- **Column letters past O/Z:** fine-A3 has 30 columns. Replace `COL_LETTERS`
  (`exam_engine.py:76`) with Excel-style names (`A..Z, AA, AB, AC, AD`) via
  small `col_name(i)` / `col_index(s)` helpers; widen `_RANGE_RE`
  (`exam_engine.py:91`) to `[A-Za-z]{1,2}` with the actual bound enforced by
  `parse_range` against the exam's grid (as row bounds already are). Rows
  reach 42 — `\d{1,2}` still fits. Mirror in the JS `parseRange`
  (`app.py:5391`) and `buildGrid`/`applyPaperGrid` (`:5357/:5374`).
- **Setup UI:** a "Grid" control next to Paper size — options **Compact
  (≈1.4 cm)** and **Fine (≈1 cm)** only. Loading a legacy exam shows a third,
  load-only "Standard (legacy 2 cm)" state so its coordinates render on the
  right grid; switching density re-validates every typed range (existing
  `refreshHighlights` red-flags out-of-range ones) — the teacher re-types
  ranges deliberately, no auto-conversion.
- Hint text (`gridHint`) reports the live grid, e.g.
  "Grid for A4: 15×21 (A1–O21), ≈1.4cm cells."

### Acceptance

- A legacy saved exam (no `"grid"` key) loads, highlights and re-slices to
  pixel-identical crops (unit test: `range_to_bbox` old vs new on the same
  legacy inputs).
- New exam defaults to compact; fine toggle gives 1 cm cells; two-letter
  columns (`AA5:AD9`) parse, highlight, slice and round-trip through
  save/load on both Python and JS sides.
- Labels clearly readable over a real scan in light and dark themes.

---

## Phase 4 — Exam Setup: name box + sections (CGW side) + definition sidecar

### Change

**A. Name box.** One optional region per exam capturing the handwritten name
(defaults to nothing; teacher adds it like a question):

- Config: `"name_box": "<range string>" | null`. Setup UI: a dedicated
  "+ Add name box" button that inserts a special pinned row above the
  questions (label fixed "Name", no score cell, distinct swatch, deletable).
  Validated with `parse_range` like any range.
- `process_exam` (`exam_engine.py:248`) slices it to
  `<exam>/__name__/<Student>.png` (reserved dir name; `_safe_name` keeps
  labels from colliding — reject a question literally labelled `__name__` in
  `save_exam`). `/api/exam/crop` (`app.py:2909`) already serves any
  `q=__name__` crop — verify, don't special-case.
- These crops are the raw material for mis-named-script matching in CAM
  Window 2 (Phase 5E).

**B. Sections.** Config grows:

```json
"sections": [{"name": "Section A", "required": null}],   // null = all required
"questions": [{"label": "Q1", "range": "...", "max": 3, "section": "Section A"}]
```

- `save_exam` guarantees ≥1 section (missing/legacy → synthesize one default
  section containing every question, `required: null`) — **every exam
  therefore always has ≥1 section**, per the teacher's requirement. Validate:
  section names unique/non-empty; every question's `section` exists;
  `required` is null ("All") or `1 ≤ required ≤ len(section questions)`.
- Setup UI: "+ Add section" inserts a section header row in the table (name
  input · numeric "required" input · "All" checkbox that greys the numeric
  input, checked by default). Questions belong to the section header above
  them; reorder buttons keep working (a question moved above the first header
  falls into section 1). New exams start with one section header already
  present. Keep it plain HTML/JS in the existing table idiom — no framework.

**C. Definition sidecar — the contract that carries structure to CAM.** The
flat CSV cannot express sections. On every routed exam export
(`api_exam_export`), **before** writing the CSV, write
`<csv filename>.meta.json` beside it:

```json
{"exam": "...", "sections": [{"name": "Section A", "required": 2,
   "questions": [{"label": "Q5", "max": 8}, ...]}, ...],
 "has_name_box": true, "grid": "compact", "paper_size": "A4"}
```

- Written before the CSV so a sync that sees the CSV also sees the sidecar
  (OneDrive orders by mtime closely enough; CAM tolerates absence anyway).
- CSV format itself is **unchanged** (`Student Name, Q1.., Total Score, Max
  Total, Due Date, Comment`) — old CAM builds and the teacher's own tooling
  keep working. `Total Score`/`Max Total` stay the naïve all-questions sums;
  CAM recomputes when the sidecar declares choice sections (Phase 5).

### Acceptance

- Legacy `gcg_exams.json` entries load into the UI with the synthesized
  default section and keep slicing identically.
- A programmed name box produces `__name__` crops for every student and never
  appears as a gradable column in the grading sheet or the CSV.
- Export writes sidecar + CSV; sidecar validates against the saved config.
- Grading screen (exam mode) is untouched by sections except that the
  grading-sheet columns may show a thin section separator (cosmetic only —
  grading stays per-question).

---

## Phase 5 — CAM: section-aware exams, Window 3 sections + `?` resolver, name-crop matching

### Change

**A. Model (`engine/`).**

- `Assignment` gains optional `sections` metadata
  `[{"name", "required" (int|None), "questions": [{"label","max"}]}]`;
  persisted in `persistence.py` next to the existing exam fields
  (`persistence.py:237–264`); absent → `None` (legacy single-section).
- `ExamResult` (`models.py:108`) gains `chosen: Dict[str, List[str]]`
  (section name → labels the teacher picked for an over-answered choice
  section); persisted; default `{}`.
- New pure helpers on/near `ExamResult` (unit-test these hard):
  - `section_state(result, section)` → answered labels, subtotal,
    `over_answered` bool (answered > required), `resolved` bool.
  - `resolved_total(result, sections)` / `resolved_max(sections)`:
    all-required sections sum normally; a choice section counts the `chosen`
    labels once resolved, else contributes **nothing and marks the total
    pending** (strict-`?` decision). Section max for a choice section = sum of
    the `required` largest question maxes in it. No sections metadata →
    exactly today's `total`/`max_total`.

**B. Ingest (`ingestion.py:664 ingest_exam_csv`).** After reading the CSV,
look for `<path>.meta.json`; when present and parseable, attach `sections` to
the registered Assignment and recompute each result's `max_total` via
`resolved_max`. Preserve any existing `chosen` selections across re-ingest
(purge-replace must not wipe teacher resolutions: merge `chosen` from the
pre-purge result when labels still exist — same spirit as the Late
reconcile). Missing/corrupt sidecar → today's behaviour, no error.

**C. Window 3 — sections display + resolver.** In the cockpit's marks list
(`render_window3`, `app.py:7247`, after the criterion rows), for each exam
the focused student has results for: one compact block —
`📝 <exam name>` then per-section rows `Section A · 12/20`, and for a pending
choice section a **`?` button**; the exam-total row shows `?` while any
section is pending. The `?` opens a dialog (`@st.dialog`, same pattern as
`edit_grade_dialog` `app.py:7349`): the section's answered questions with
scores as checkboxes, ticking capped at `required` (disable the rest at the
cap), live subtotal preview, Save writes `result.chosen[section]` + persist.
Teacher can reopen and change any time.

**D. Resolved totals everywhere raw exam numbers surface:** Window 1 banding
panel (`_render_exam_banding` `app.py:6414` — raw score, %, suggested band via
`ExamResult.suggested_band`), the analytics dialog exam view (`app.py:6595`),
timeline raw-average chip (`app.py:6385`). Pending students render `?` and
are **excluded** from class averages; the banding row's Apply for a pending
student is disabled with a caption ("resolve Section B in Window 3 first").

**E. Name-crop matching hook (scoped small).** Exam rows are keyed by PDF
filename stem; a mis-named file mints a wrong student. Full visual matching
belongs to the anonymous-grading plan; here, just make the evidence visible:
in Window 1's exam analytics dialog, when the exam's crop tree has
`__name__` images, show each ingested row's name crop (`st.image` of
`exam_crops/<class>/<exam>/__name__/<student>.png`, resolved via the same
path convention CGW uses — CAM already reads CGW crops for previews, see
`app.py:6867`) next to its student id, so a mis-match is spottable at a
glance. Renaming/re-keying stays the existing manual flow.

### Acceptance

- Unit tests: `resolved_total`/`resolved_max`/`section_state` over: no
  sections, all-required, choice resolved/unresolved/over-answered, ties,
  missing answers; `chosen` survives re-ingest; sidecar-less CSV identical to
  today.
- Cockpit shows per-section marks; `?` flow works end-to-end and the exam
  total flips from `?` to a number once every pending section is resolved.
- Window 1 averages/banding respect resolutions; pending students excluded
  and Apply disabled.
- A legacy exam (no sidecar) renders exactly as before this phase.

---

## Phase 6 — Adjust a question's region during grading (+ re-slice one question)

### Change

Spreadsheet method, per the teacher's decision — reuse Exam Setup, don't build
a new editor:

- **Entry point:** in the grading screen's exam mode, next to each question
  (the grading-sheet column header and/or the current-question selector), a
  small ✎ button → opens `/exam_setup?class=..&exam=..&focus=<label>`.
- **Focus mode in Exam Setup:** when `focus` is present, auto-load that exam
  (existing `loadExamConfig` path, `app.py:5537`), scroll to and highlight the
  question's row, and enable **zoom-to-selection**: crop/zoom the page
  preview to the question's current range **± 2 cells** (CSS
  transform/scale on `#pageWrap` contents, clamped to the page) so the
  teacher edits the same typed coordinates with a close-up view. A "⤢ full
  page" toggle restores the normal view. Zoom is available outside focus mode
  too (click a question's swatch) — cheap once built.
- **Re-slice one question:** new endpoint `POST /api/exam/process_one`
  `{class_name, config, label}` — saves the config (as `processAll` does),
  then a background job (reuse `EXAM_JOBS` machinery, `app.py:2646`) that
  crops **only that question** for every student (factor `process_exam` so a
  `labels=[...]` subset can run). Setup page shows a "⚙ Re-slice this
  question" button in focus mode; on completion, note that the grading screen
  needs its crop images refreshed (cache-bust the `img` URLs with `?t=` —
  they already carry `Date.now()` in setup; do the same in the grading
  roster).
- Scores are keyed by question label (`EXAM_STATE` / `exam_grades_*.json`) —
  re-slicing changes pixels only; entered marks must survive untouched.
  Renaming a label during adjust is out of scope (existing behaviour).

### Acceptance

Sandboxed CGW run on the CAM Test Folder exam: mid-grading, ✎ on Q1 → setup
opens focused + zoomed on Q1's cells ±2; widen the range one column;
re-slice-one completes in seconds (4 fixture students); back in grading the
Q1 crops show the wider framing and all previously entered scores are intact.
Other questions' crops byte-identical (mtime check).

---

## Cross-cutting

- **Changelog:** add a `docs/CHANGELOG.md` entry per phase, matching the
  existing entry style.
- **Docs:** update `docs/USER_MANUAL.md` (exam setup: grid densities, name
  box, sections, adjust-during-grading; cockpit: section `?` resolver) and
  `docs/DATA_DICTIONARY.md` (config keys `grid`/`sections`/`name_box`,
  sidecar `*.meta.json`, `ExamResult.chosen`, `Assignment.sections`,
  `cam_export_beacon.json`).
- **Keep the JS/Python grid mirrors in sync** — `exam_engine.py` is the
  source of truth; both HTML pages carry copies (comment at `app.py:5346`
  already warns about this; extend it to name the new density map).
- **Never test against real data.** Every launch: temp
  `local_device_prefs.json`/`db_custom_path`, CGW `gcg_settings.json` pointed
  at a temp cloud dir, fixtures only.
