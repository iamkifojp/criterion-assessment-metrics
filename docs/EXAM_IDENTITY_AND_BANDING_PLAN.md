# Exam Identity & Section Banding Plan — v1

**Implementer:** Claude Opus 4.8 on High reasoning.
**Scope:** Phases 1–3 + 5 in `cam_grading_workspace/app.py` (+ `exam_engine.py`);
Phases 4 + 6 in CAM's root `app.py` + `engine/` (models, ingestion,
persistence); Phase 7 in `docs/`.
**Origin:** teacher feedback from live-testing the exam loop end-to-end
(2026-07-14, Test MYP Class, smiletutor sample PDF) plus a real Year 7 Sciences
end-of-term paper whose cover sheet shows the school's actual grading scheme
(sections = strands of ONE criterion; teacher circles a level per strand, then
decides one final criterion grade).

Read `CLAUDE.md` first. CGW writes exam grades into the **class cloud folder**
and CAM's repo prefs point at the **live OneDrive database** — test only against
the Test MYP Class / CAM Test Folder sandbox with a redirected `db_custom_path`,
never a real class or the live DB. Follow the sandbox rules before launching
anything.

---

## Teacher decisions (locked defaults — change only if the teacher says so)

| # | Decision | Default |
|---|----------|---------|
| D1 | Question dropdown text | Label only (`1`, `2ap`, …) — no mark range. The range still shows in the grading sheet's question column header (`(0–2)`), which sits right next to the dropdown |
| D2 | Cell-label sizing | Sized by **both** axes: ~55% of cell height, capped so the longest possible label on the current grid (`colName(NCOLS-1) + NROWS`, e.g. `AD42`) fits inside one cell width. Labels must never bleed into neighbouring cells at any density / fit mode / window size |
| D3 | Tab discipline | All routes into Exam Setup (`#examSetupBtn`, `#examAdjustBtn`, per-question ✎) open **one named tab** (`window.open(url, "cam_exam_setup")` + `.focus()`), never `_blank`. "← back to grading" focuses the opener and closes the setup tab when it was script-opened; plain navigation to `/` only as the no-opener fallback |
| D4 | Re-slice semantics | Unchanged and now documented: re-slice **and** Process All both save the setup first (no separate Save click needed). Process All re-slices every question but never touches marks (grades live in a separate label-keyed file). Both paths must ping the grading tab's crop cache-buster |
| D5 | Student identity | The **filename stem stays the storage key everywhere** (crop filenames, grades file, alias csv_key). Real names are display + export only: a `student_names` map in the exam config, edited in the Exam Setup naming panel — no inline rename in the grading sheet |
| D6 | Exam CSV identity routing | Exam CSVs route through the same roster identity pipeline as assignment CSVs (exact → durable alias → unambiguous prefix → unmatched pool). **Never mint a phantom student from a "Student Name" cell.** Unmatched exam rows are matched visually in the Window 2/3 matcher using the **name-box crop** as the thumbnail (fallback: first question's crop); matching records the durable alias |
| D7 | Sections and criteria | Sections are **strands of ONE criterion** (per the real cover sheet) — no per-section criterion mapping (deferred; nothing in this design may preclude adding it later). The exam keeps its single "Counts toward criterion" dropdown |
| D8 | Who decides grades | The teacher. Per-section 0–8 levels AND the final grade are all teacher-set dropdowns; the app only **suggests** (proportional % per section; rounded mean of section levels for the final). Only the **final** grade enters the gradebook as a `CriterionScore` |
| D9 | Pending `?` at section granularity | An unresolved over-answered choice section shows `?` for its subtotal and disables **its own** level dropdown and the final-grade dropdown ("resolve first", resolved in Window 3 as today). Other sections' level dropdowns stay editable |

---

## Phase 1 — CGW cosmetics: dropdown de-clutter + width-aware cell labels

Both in `cam_grading_workspace/app.py`.

1. **Question dropdown (D1).** In `loadExam`, the option text
   `q.label + "  (0–" + q.max + ")"` becomes just `q.label`. Nothing else —
   the sheet header (`renderExamTable`'s `qcol`) already shows `(0–max)`.
2. **Cell labels (D2).** In `EXAM_SETUP_PAGE`'s `sizeCellLabels()`: today
   `px = max(9, round((h / NROWS) * 0.55))` uses height only, so wide labels
   (`D10`, fine-A3's `AD42`) overflow horizontally. Add a width cap:
   - `cellW = ov.clientWidth / NCOLS`;
   - `maxChars = (colName(NCOLS - 1) + NROWS).length` (the widest label on
     this grid);
   - cap ≈ `cellW * 0.85 / (maxChars * 0.62)` (0.62 ≈ average glyph width in
     ems for the 800-weight UI font — tune visually, don't over-engineer);
   - `px = max(9, min(heightPx, widthCap))`.
   `sizeCellLabels` is already called on image load, resize, density change
   and fit-mode change — no new call sites needed.

**Verify:** load the sample folder; A4 compact, A4 fine and A3 fine (widest
labels) at both fit modes — no label crosses a cell border; dropdown shows bare
labels; the sheet header still shows the range.

## Phase 2 — CGW tab discipline (D3) + Process-All crop ping (D4)

All in `cam_grading_workspace/app.py`.

1. **Named setup tab.** Replace the three `window.open(..., "_blank")` calls
   (`openExamAdjust`, the `#examSetupBtn` handler) with
   `const w = window.open(url, "cam_exam_setup"); if (w) w.focus();`.
   Repeat clicks now re-navigate the one setup tab instead of stacking tabs;
   re-navigation re-runs the deep-link (`?exam=..&focus=..`) so focus-adjust
   still lands on the right question.
2. **Smart back-link.** In `EXAM_SETUP_PAGE`, the `← back to grading`
   anchor gets a click handler: if `window.opener && !window.opener.closed`,
   `window.opener.focus(); window.close();` else `location.href = "/"`.
   Keep the `href="/"` so middle-click / no-JS still works.
3. **Process All pings the grading tab.** `pollExamJob` (the Process-All
   poller) must write the same `localStorage["cam_exam_resliced"]` signal
   `pollResliceJob` writes on completion — with no single label (e.g.
   `label: ""` and the grading tab's status message saying "re-processed");
   the grading tab's `storage` listener already bumps `EXAM_CROP_BUST` and
   re-renders, which refetches every crop. Today only single-question
   re-slices refresh an open grading tab; a full re-process leaves it stale.

**Verify:** from the grading tab click Adjust twice and Exam Setup once —
exactly one setup tab exists. Back-link returns to (and focuses) the original
grading tab and closes setup. Open Exam Setup directly by URL — back-link
navigates instead of closing. Run Process All with the grading tab open —
crops refresh in place without a manual reload.

## Phase 3 — CGW: focus-adjust any question from inside Exam Setup

In `EXAM_SETUP_PAGE`. Today `enterFocusMode(label)` fires only from the
`?focus=` deep-link; inside the tab there is no way to move the focus.

1. Each **question** row in `addRow` gains a small ✎ button (reuse `.rowbtn`
   styling; title "Adjust & re-slice this question") that calls
   `enterFocusMode(label)` with the row's current label. Clicking it while
   another question is focused simply moves the focus (existing
   `enterFocusMode` already clears `.focusrow` from all rows).
2. The colour swatch keeps its current zoom-only behaviour — do not overload
   it.
3. `resliceOne` already reads the focused row's label and saves first (D4) —
   no backend change.
4. Section and name-box rows get no ✎ (only questions are re-sliceable
   one-at-a-time; the name box's reserved label is an internal detail).

**Verify:** open Exam Setup fresh (no deep-link), click ✎ on Q3 — row
highlights, preview zooms, focus bar appears; re-slice runs and the grading tab
refreshes. Click ✎ on another question — focus moves cleanly.

## Phase 4 — CAM: exam identity routing + name-crop matcher (D6)

The correctness phase — do it before Phase 5/6. Today
`IngestionPipeline.ingest_exam_csv` does `gradebook.get_or_create(sid)` with
the raw "Student Name" cell ("Exam CSVs never route" — `sync_ingest_csv`'s
docstring), minting a phantom student per unmatched row. Real roster students
then show the exam as missing, and the missing-popup's 🧩 matcher never offers
the row because the unmatched pool is only filled by the assignment path.

1. **Route the exam ingest** (`engine/ingestion.py`). `ingest_exam_csv` gains
   the same optional routing parameters as `ingest_csv` (`roster_keys`,
   `aliases`, `unmatched_out`, `auto_aliases_out`) and routes each row's sid
   through the same resolution (exact → alias → unambiguous prefix → pool).
   Reuse the existing resolution helper — do not fork it. Matched rows attach
   the `ExamResult` to the roster student (preserving the existing
   `chosen`-carry-forward logic keyed on the *resolved* student). Unmatched
   rows append an **exam-flavoured pool row** to `unmatched_out`: keep the
   same `csv_key` field, plus `is_exam: True`, `questions`, `total`,
   `max_total`, `comment` (mirror what a matched row would need to
   materialize). No roster (`roster_keys` falsy) → today's behaviour exactly
   (rosterless classes keep working).
2. **Caller** (`sync_ingest_csv` in CAM `app.py`): pass the routing inputs to
   the exam branch too, and let the existing pool-rebuild block after the
   ingest handle exam pools (it is keyed on `unmatched`, so it mostly already
   does — confirm the purge-replace of `unmatched_works[class][assignment]`
   fires for exams).
3. **Materializing a match** (`assign_work` in CAM `app.py` +
   `IngestionPipeline`). When the pool row has `is_exam`, record the durable
   alias exactly as today, then materialize an `ExamResult` under the roster
   student (a small `materialize_exam_row` beside `materialize_row`,
   preserving any prior `chosen` picks for still-answered labels) instead of
   `CriterionScore`s. Re-syncs then route via the alias — the pool row never
   comes back.
4. **Matcher visuals** (`match_works_dialog` in CAM `app.py`). For exam pool
   rows the thumbnail is the **name-box crop**: `exam_name_crop_path(class,
   exam, csv_key)`. Fallback when the exam has no name box: the first
   question's crop (same directory layout, first `question_labels` entry);
   final fallback the filename-only tile. Show the raw total (`31/45`) in the
   tile caption where assignment tiles show grades.
5. **Fix `exam_name_crop_path` / `exam_has_name_crops` (bug).** They only
   check the legacy root `cam_grading_workspace/exam_crops/…`. Phase 6 of the
   previous plan moved crops into `<cloud>/<class>/exam_crops/…`, and the
   Phase 7 purge already checks **both** roots — mirror that here (cloud root
   first, legacy fallback) so name crops work for cloud-backed classes. Every
   caller benefits (Phase 5E analytics preview included).
6. **Missing popup**: no code change expected — the 🧩 button keys off
   `unmatched_works[class][assignment]`, which exams now populate. Confirm it
   appears for a roster student missing the exam, and that `match_works_dialog`
   handles the exam rows.
7. **Phantom cleanup.** Existing phantoms (e.g. `https___smiletutor.sg…`)
   were minted by earlier exam ingests. On exam ingest with a roster, after
   purge-replace: remove students whose id is not a roster key and who hold
   **no remaining scores and no exam_results**. Do not touch rosterless
   classes. Log what was removed into the sync summary.
8. **Persistence:** exam pool rows ride the existing `unmatched_works`
   session persistence — confirm the new fields survive a save/load
   round-trip (they are plain JSON).

**Verify (sandboxed DB + Test MYP Class):** ingest an exam CSV whose names
don't match the roster → no new student appears in Window 2; the banding panel
lists no phantom; each roster student's missing popup offers "🧩 <exam> — 1
unmatched work"; the matcher shows the name-box crop; assigning moves the raw
result to the student, the banding row appears, and a re-sync of the same CSV
routes silently via the alias. Run once against a class with no roster —
behaviour identical to today.

## Phase 5 — CGW: student naming panel (D5)

`cam_grading_workspace/app.py` + `exam_engine.py`. Complementary to Phase 4:
naming at the source means the CSV arrives roster-matchable and the matcher is
never needed; Phase 4 remains the safety net.

1. **Config field.** Exam configs gain `student_names`: `{stem: display
   name}`. `save_exam` validates it (dict of str→str, strip values, drop
   empties) and persists it through both stores (portable + legacy). Absent →
   `{}` (full backward compatibility).
2. **Naming panel** in `EXAM_SETUP_PAGE`: after a folder is loaded (and when
   a saved exam with a `pdf_folder` loads), a collapsible "Students (N)"
   block below the question table lists every file stem with a text input
   for the real name. When the exam has been processed with a name box, show
   the `__name__` crop beside each row (`/api/exam/crop?...&q=__name__`) so
   the teacher reads the handwriting while typing. Values save with Save
   Setup / Process All (they ride `configPayload()`).
   - The scan-folder endpoint (`/api/exam/scan_folder`) must return the stem
     list for the panel (extend its JSON; it already walks the folder).
3. **Display plumbing.** `/api/exam/load` returns `name` =
   `student_names.get(stem, stem)` (still blanked when anonymous — D6 of the
   previous plan is untouched). `key` stays the stem everywhere: crops,
   `/api/exam/grade`, the grades file.
4. **Export plumbing.** `/api/exam/export` writes the mapped name into
   "Student Name". Note the identity contract this creates: once mapped names
   flow, CAM matches those (Phase 4 aliases handle any earlier stem-keyed
   matches — both can coexist because aliases are per-csv_key).
5. Docs note in the code where `student_names` is read, mirroring the
   "display-only doctrine" comments.

**Verify:** name two students in the panel, save, reload setup — names
persist. Grading tab shows real names (and positional numbers when anonymous).
Export CSV — "Student Name" carries the mapped names; grades file on disk still
keys by stem.

## Phase 6 — CAM: section-level banding, teacher-decided (D7, D8, D9)

The real Year 7 paper's cover sheet is the model: raw marks inform, the teacher
sets a level per section (strand), then one final criterion grade. Files:
`engine/models.py`, `engine/persistence.py`, CAM `app.py`
(`_render_exam_banding`, `_apply_exam_bands`, `_render_exam_sections`).

1. **Model.** `ExamResult` gains `section_bands: Dict[str, int]` (section
   name → teacher-picked 0–8 level), beside `chosen`. Serialize/deserialize
   in `engine/persistence.py` exactly as `chosen` is handled (absent → `{}`;
   round-trip test). Carry it forward across re-ingest the same way `chosen`
   is carried (picks survive purge-replace).
2. **Banding panel layout** (`_render_exam_banding`). When the exam has more
   than one section, or one real (non-synthesized) section — i.e. skip all of
   this when sections is the single default "All Questions" section, which
   renders exactly as today — each student renders as a bordered container
   with two lines:
   - line 1 (as today): student label · resolved total `/` max · % · **final
     grade** dropdown;
   - line 2 (small captions + narrow selects): per section, `<name>
     <subtotal>/<max>` and a 0–8 **level** dropdown.
   This two-line shape is the locked layout (Window 1 is narrow; one wide row
   per student does not fit 3+ sections).
3. **Suggestions, not decisions (D8).**
   - Section level dropdown default: saved `section_bands` value if present,
     else the proportional suggestion
     `round(subtotal / section_max * 8)` clamped to 0–8.
   - Final grade default: saved band if already applied (existing behaviour),
     else the **rounded mean of the current section level widgets**, else
     (single-section / legacy) today's `resolved_suggested_band`.
   - Everything stays a dropdown the teacher can override.
4. **Pending (D9).** A pending section shows `? /max` and a disabled level
   dropdown ("resolve first" tooltip pointing at Window 3, as the total does
   today); the final-grade dropdown is disabled while any section is pending.
   Non-pending sections stay editable.
5. **Apply** (`_apply_exam_bands`). Unchanged in what enters the gradebook:
   one `CriterionScore` per student under the chosen criterion (final grade
   only). Additionally persist each student's `section_bands` from the level
   widgets. The score `note` gains the strand levels for the record, e.g.
   `"banded from raw 31/45 · sections: Knowing 7, Applying 7, Interpreting 5"`.
6. **Window 3** (`_render_exam_sections`): a section row with a recorded
   level appends `· level N` to its subtotal caption — the digital cover
   sheet.
7. **Nothing else moves:** class average, `?` exclusion, one-band-per-exam
   replacement semantics, `asg.criteria = [crit]` — all as today.

**Verify (sandboxed):** exam with 3 sections incl. one choice section —
per-section subtotals match hand-added marks; suggestions appear; overriding a
section level updates the suggested final on rerun; over-answered student shows
`?` on that section + disabled final until resolved in Window 3; Apply writes
one CriterionScore, note carries the levels; reload — levels persist; legacy
single-section exam renders byte-identical to today.

## Phase 7 — Docs

1. **CHANGELOG:** one entry per phase, as each phase lands (repo convention).
2. **ARCHITECTURE.md:** update the exam pipeline section — exam CSVs now
   route through roster identity (the "Exam CSVs never route" note dies);
   `student_names` display-only map; `section_bands` on `ExamResult`;
   name-crop dual-root resolution.
3. **USER_MANUAL.md** ("Grading exam papers" section): naming students in
   Exam Setup (with the name-box workflow), matching leftover papers via the
   missing popup's 🧩, section levels + final grade in the Window 1 panel
   (mirroring the paper cover sheet), and a warning that blank leading scan
   pages shift every `pageN!` coordinate.
4. **DATA_DICTIONARY.md:** `student_names` (exam config), `section_bands`
   (ExamResult), exam-flavoured unmatched pool rows.

---

## Testing / safety notes for every phase

- **Sandbox first, every launch.** CAM's repo prefs point at the live OneDrive
  DB — redirect `db_custom_path` to a temp folder before any Streamlit run
  (standing rule; a 2026-07-10 test run wiped the live DB). CGW: Test MYP
  Class / CAM Test Folder only.
- Back up before any approved write to a real database
  (`acm_database.json.bak-<purpose>-YYYYMMDD-HHMMSS`).
- The CGW pages are giant `r"""` string literals — keep escaping intact.
- Phase 4 touches ingestion shared with assignments: re-run the existing
  engine tests plus a manual assignment-CSV sync to prove no regression.
- Smoke loop after each CGW phase: load folder → program → save → process →
  grade one student → export → CAM ingest parses.
- `git commit` per phase, message style "Phase N: <summary> (CGW|CAM)".
