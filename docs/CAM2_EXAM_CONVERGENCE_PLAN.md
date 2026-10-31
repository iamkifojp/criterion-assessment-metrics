# Bringing CAM2's exam grading back into CAM: assessment and staged plan

**Status:** v3, 2026-10-31. All decisions (D1–D9, §4) are locked.
**Stages 0–2 are done** (see the ✅ notes in §5); Stage 3 is next, once
every computer runs the Stage 2 build.
**Repos:** CAM = `C:\Project\criterion-assessment-metrics-public`;
CAM2 = `C:\Project\cam2-exam-grading` (`iamkifojp/cam2-exam-grading`, 4 commits,
187 tests, Phases 1–4c done, Phase 5 packaging next).

Read `CLAUDE.md` first. Exams write into the **class cloud folder**, and Stage 2
changes the database schema. Every stage that touches real data follows the
sandbox, backup and permission rules there.

---

## 1. Where things stand

CAM2 started as a copy of CAM's exam slicer and became a separate, more
complete exam app. Most of what it added is the "new thinking" worth bringing
back. It also dropped several things CAM depends on.

### What CAM's exam grading is today

- **Code:** spread across the Flask grading workspace (CGW):
  `cam_grading_workspace/exam_engine.py` (794 lines), about 530 lines of
  `/api/exam/*` routes, the `EXAM_SETUP_PAGE` inline HTML/JS (about 1,150 lines)
  and the exam mode in `HTML_PAGE`, all inside a 7,060-line `app.py`. In total
  about 2,500 lines of exam code, much of it inline JavaScript in Python strings.
- **Data:** definitions in `gcg_exams.json` (keyed by class), grades in
  `exam_grades_<exam>.json`, crops in `exam_crops/<class>/<exam>/<Q>/<stem>.png`.
  The scan's **file name stem is the student's identity**.
- **Flow:** typed grid ranges → Process All → grade one question across the
  class (marks only) → Export CSV + `.meta.json` sidecar → CAM Sync ingests it
  as an `ExamResult` → the Window 1 panel turns raw marks into one 0–8 band
  (with optional per-section strand levels, dropped by D3) → one
  `CriterionScore`.
- **Saving:** `save_exam_grades` is a plain `.tmp` + `os.replace`. It has none
  of the generation, conflict-copy or wipe checks that protect the main
  database, although these files sit in a cloud-synced class folder.

### What CAM2 does differently

| Area | CAM (CGW) today | CAM2 |
|---|---|---|
| Bringing in scans | One file per student, named after the student; every student must be scanned the same way (a page-count warning only) | Whole class in one PDF (split by pages per student, with a class-size check), several batches, one file per student, or phone photos; **A3 booklets unfolded** into page order; on-screen fixes (move, turn, remove, blank page; booklet sheet turned or swapped); **late papers** added any time; scans copied into the session |
| Defining questions | Type ranges like `page2!A2:C5` on a compact or fine grid | **Drag a box** that snaps to a 5 mm grid; **several boxes per question** stitched into one image; "Check on other papers" strip; "new question or move the box?" prompt; reorder questions safely |
| Identity | File name stem, plus a display-name map; leftovers go to CAM's 🧩 pool | Ids (`s001`, `q1`, `n001`) for everything; class list matched to **handwritten name crops** at the source; auto-match from file names (full/half width, macOS-safe) |
| Grading screen | Sheet with one score column, keyword pills, comment | Large mark buttons, or **rubric band cards with descriptors**; **Not answered** separate from ungraded; grade badge on the image; **whole page with the box outlined**; zoom and pan; "Show ungraded only"; resume at the exact question and paper |
| Grading model | Marks only; banding to 0–8 happens later in CAM | **Marks or Rubric** mode. In Rubric mode one question can assess **several criteria**, with a level for each, averaged with round-half-up into a suggested final level per criterion |
| Choice questions | Sections with "choose N"; an over-answered section shows `?` in CAM until the teacher picks | Choice groups counted **best N automatically**, made unambiguous by the explicit Not answered |
| Review & outputs | CSV export for CAM | Review table with report-only overrides; **one feedback PDF per student** (answer images, grades, comments, rubric printed once); per-exam Excel gradebook; **EN/日本語** |
| Saving | Atomic rename only | `SafeJsonFile`: emergency copy first, folder check, cloud conflict copies, **generation/hash check against another computer**, wipe guard, daily backups, read-back check; recovery offer on open |
| Code shape | Inline HTML/JS in one Python file | Framework-free `engine/` with `UserError` codes; thin Flask `app.py`; plain ES-module screens; i18n parity tests |

### What CAM has that CAM2 lacks

These must exist before CAM's exam code can be retired:

1. **Keyword checklist** of comment pills per exam.
2. **Shuffled anonymity**: papers numbered by position and reshuffled for each
   question. CAM2 only has "Hide student names".
3. **Teacher-picked answers** for an over-answered choice group (D2).
4. **Correcting a box after grading has started** and re-slicing just that
   question. CAM2 dropped this in favour of "See whole page". Boxes can still be
   edited in Step 2, but that re-slices every paper.
5. **The CAM link:** roster, criteria, result ingest, banding into the
   gradebook, sync, and clean-up on permanent delete.

CAM's strand levels for marks exams are not on this list: D3 drops them in
favour of Rubric mode.

---

## 2. Approach: one exam codebase, two hosts (D1)

CAM2 becomes **the** exam app and CAM hosts it, instead of features being
ported into the CGW one at a time.

- **Why not port feature by feature:** porting booklets, page fixes, drag
  boxes, rubric mode, safe saving and reports into CGW's inline pages means
  writing CAM2 a second time inside a 7,000-line file. After that the two would
  drift apart for good.
- **Why not a shared pip package:** for one developer, the versioning and the
  changes to the Windows bundle are not worth it.
- **What to do:** vendor CAM2 into CAM with `git subtree` at `exam_grading/`,
  unmodified. CAM's own glue lives **outside** that folder, in
  `engine/exam_bridge.py` plus a small launch helper. Exam features are always
  built in the CAM2 repo first, then brought in with `git subtree pull`, so the
  standalone download and CAM always run the same exam code.
- **Grading decisions are made in CAM2.** Anything about how an exam is scored
  (choice groups, teacher-picked answers, final levels) is decided and stored
  in CAM2, so the standalone app has it too and CAM imports the settled result
  rather than asking again.
- **How it runs:** CAM2 keeps its own small local server (`launcher.py`,
  single instance, port from 5182, idle shutdown). CAM launches it the way it
  launches CGW today. CGW goes back to grading assignments only.
- **The session folder is the contract.** In CAM-hosted mode an exam's session
  lives at `<class cloud folder>/exams/<exam name>/`, scans included (D6). CAM
  never writes to it. At Sync it **reads** `cam2_session.json` + `grades.json`
  and computes totals with the vendored `grading_summary`, so CAM's numbers
  always match CAM2's (round-half-up, best N, teacher picks). This replaces the
  CSV + sidecar + beacon chain. No third file format is needed.

What this gives CAM: booklets and messy scans, drag boxes, rubric-mode exams
graded straight onto MYP criteria, per-student feedback PDFs, Japanese reports,
and CAM2's save safety on the exam files that live in the cloud folder.

---

## 3. What not to bring

- **Old CGW exams (D5).** No migration, importer or dual path. Once the new
  path works, CGW's exam code is removed outright. Existing `ExamResult`
  records in a database must still load.
- CAM2's **start screen and recent-sessions list** in hosted mode: CAM opens
  the exact session. The standalone app keeps both.
- CAM2's **class-list upload** in hosted mode: CAM supplies the roster. Typing
  a name for an unmatched paper stays.
- CAM's **strand levels** for marks exams (D3).

CAM2's **Step 5 export stays in hosted mode** (D9): student PDFs and the Excel
gradebook, written to the session's `reports/` folder.
- CAM2's **packaging and Mac build** (Phase 5). CAM keeps its own Windows bundle
  and only adds the `exam_grading/` folder to it.
- **App-wide Japanese for CAM.** Only the exam screens and the student PDFs come
  bilingual, because they come from CAM2.
- CGW's **grid colour picker, fit width/page toggle and typed ranges**: drag
  boxes on a light 5 mm grid replace them.

---

## 4. Decisions

### Locked (2026-10-31)

- **D1 · Architecture:** CAM2 vendored into CAM and hosted by it (§2).
- **D2 · Over-answered choice groups:** each choice group has a policy, set in
  CAM2 Step 2D: **Best N** (the default; the highest-scoring N count
  automatically) or **Teacher picks** (the teacher chooses which N count).
  With Teacher picks, an over-answered group shows `?` in CAM2's Step 5 review
  until the teacher ticks the answers that count; the total stays incomplete
  until then. The student PDF and gradebook show which answers counted. CAM
  imports the settled result and no longer has its own `?` resolver.
  *(Read from "best N or fix questions": "fix" taken to mean the teacher fixes
  which questions count. Correct this if a fixed rule such as "first N
  answered" was meant.)*
- **D3 · No strand levels; criteria come from Rubric mode** (option C).
  An exam that assesses several criteria is set up in CAM2's Rubric mode, with
  each question (or group of questions) assigned to Criterion A, B, C or D,
  and graded with the teacher's full rubrics. CAM2's review step and student
  PDFs report a level per criterion, and CAM imports those levels (D4). A
  marks-mode exam is banded from its total onto one criterion in the Window 1
  panel, without sections. CAM's per-section strand dropdowns and
  `section_bands` are removed in Stage 4.
  - *For reference, what is being dropped:* a marks exam counted toward one
    criterion, and each section was a strand of it (for example Knowing /
    Applying / Interpreting). The Window 1 panel showed each section's
    subtotal with a 0–8 level dropdown and a final grade suggested as the
    rounded average; only the final grade entered the gradebook.
- **D4 · Rubric-mode exams:** CAM2's suggested (or teacher-adjusted) final
  level per criterion becomes that criterion's `CriterionScore`, confirmed in
  the Window 1 panel, with no raw-mark banding step.
- **D5 · Old exams:** dropped completely (§3).
- **D6 · Scans in the cloud folder:** the session folder, scans included, lives
  in the class cloud folder. Re-slicing and the whole-page view then work on
  any computer that syncs it.
- **D7 · Correcting a box during grading:** an "Adjust this box" link on the
  grading card opens Step 2 on that question. Saving re-slices only that
  question for every paper, keeps every grade, and returns to the same paper.
  This covers a box drawn wrongly early on and noticed only while grading.
- **D8 · Anonymity:** two separate tick boxes in Step 4, both remembered on
  this computer: **Hide student names** (exists) and **Shuffle papers** (a new
  order for every question, seeded per exam and question so it is stable on
  reload). With both on, papers are shown as `01`, `02`, … by position, so the
  same number is a different student on each question.
- **D9 · Exam reports from CAM2 inside CAM:** hosted mode keeps CAM2's Step 5
  export, so a teacher can hand out a report for one test (student PDFs, plus
  the Excel gradebook) separately from CAM's end-of-term report.

---

## 5. Stages

One commit per phase, tests with every phase. Stage 1 happens in the **CAM2
repo**; the other stages happen in CAM. The order matters: CAM2 parity first,
then CAM's **reader** before anything writes the new shapes (an older CAM on
another computer must not choke on a newer database; see
`CROSS_DEVICE_AND_DB_SAFETY_PLAN.md`), then the switch, then the clean-up.

### Stage 0 — Groundwork (CAM; no behaviour change) · S — ✅ done
*CAM `ee29083` (subtree add) and `d470e44` (`tools/run_all_tests.py`, ARCHITECTURE note).*
- `git subtree add --prefix exam_grading <cam2 remote> main --squash`.
- Make CAM's test run also discover `exam_grading/tests`. Both suites must pass.
- Add to `docs/ARCHITECTURE.md`: `exam_grading/` is upstream code. Change it
  in the CAM2 repo, never in place.

### Stage 1 — CAM2 features (CAM2 repo; also improve the standalone app) · M–L — ✅ done
*CAM2 `bcd6eb0` (1a), `ee9ab6c` (1b), `ea66d13` + `c21f16e` (1c), `b146d25` (1d),
`6ca9891` (1e); 209 tests; each checked in a browser with sample papers. Pulled
into CAM as `84002e4`.*

Each is a CAM2 phase with its own tests and a browser check, in this order:
- **1a · Choice-group policy** (D2): Best N or Teacher picks per group, the
  Step 5 `?` and tick-to-choose, `grading_summary` totals, reports and the
  gradebook.
- **1b · Keyword checklist:** per-exam comment pills in the Step 4 card.
  Ticking them rebuilds the generated part of the comment and keeps typed text
  (the CGW behaviour).
- **1c · Shuffle papers** (D8): the second tick box, seeded per exam and
  question, as in CGW's `examSeededShuffle`.
- **1d · Adjust this box** (D7): re-slice one question (`slice_students`
  already exists; add a per-question variant) and return to the same paper.
- **1e · Host hook:** `launcher.py --host <handoff.json>` with exam name, class
  name, session folder and roster `[{external_id, name}]` (format in
  `exam_grading/engine/host.py`). In host mode: the exam opens straight away
  (or the Step 1 form opens with the exam name and folder fixed), the matcher
  uses the given roster and stores `external_id` on roster entries, the header
  shows *CAM · <class>*, and a "Grading finished — send to CAM" action writes
  `host_ready_at` into `cam2_session.json`. Step 5 export stays available (D9).
  Without `--host`, nothing changes.
  - *Changed while building:* no "Back to CAM" button, because CAM runs in its
    own browser tab and a link would open a second CAM session. The handoff
    carries no criterion names: CAM maps each CAM2 rubric to a criterion
    itself (Stage 3).

### Stage 2 — CAM reads sessions (CAM; reader only) · M — ✅ done
*CAM `exam_bridge.py` + tolerant `ExamResult`; 14 tests in `test_exam_bridge.py`.
Changed while building: Not answered is a separate `not_answered` list rather
than a value inside `questions`, so `questions` keeps its old label → whole-mark
shape and even a pre-Stage-2 CAM still loads the file. Fields Stage 3 will show
(`counted`, `complete`, `question_comments`) were added now, so Stage 3 needs no
second schema change. `final_levels` is keyed by CAM2 rubric id and not limited
to 0–8. Fields are listed in DATA_DICTIONARY.md.*

- Extend `ExamResult` in a tolerant way: per-question values that can be
  `not_answered`; per-question criterion `levels`; `final_levels` per
  criterion; `mode`; `session_id`. Records already
  in a database load unchanged. Update `_validate_exam_result` and the to/from
  dict code.
- `engine/exam_bridge.py`: `read_session(folder)` → per-student results via the
  vendored `grading_summary`, routed by `external_id` (exact), then the
  existing `resolve_identity` / 🧩 pool as the fallback. CAM and CAM2 both
  have a top-level `engine` package, so the bridge loads CAM2's under another
  module name (`importlib`, e.g. `cam2_engine`); CAM2's engine modules import
  each other relatively, so this works without changing CAM2.
- Tests use fictional sessions built with CAM2's own test helpers. No real data.
- Ship this stage, and let the other computers update, **before** Stage 3 writes
  anything new.

### Stage 3 — Exams open in CAM2 (CAM) · M–L
- Window 1 **🛠 Exam setup / Grade** writes the handoff, starts CAM2 in host
  mode at `<class folder>/exams/<exam>/` and opens the browser. Every exam goes
  this way; there is no CGW fallback (D5).
- **Sync** reads every hosted session that has `host_ready_at`, read only. It
  ingests or updates the `ExamResult`s.
- **Window 1 panel:** rubric exams show the imported final level per
  criterion to confirm (D4). Each CAM2 rubric is mapped to a CAM criterion by
  a dropdown, defaulted from its name ("Criterion B", "基準B" → B) and
  remembered per exam. Marks exams band from the total onto one criterion,
  with no sections (D3).
- **Window 2/3:** name crops and the 🧩 thumbnails come from
  `crops/__name__/<sid>.png`; Window 3 shows each question's value,
  Not answered, which choice answers counted, and the comment.
- **Permanent delete** of an exam: move the session folder into a dated
  `exams/_deleted/` folder rather than deleting it. Hard delete stays a
  separate, explicit action.
- Sandbox end to end: temp prefs, temp `db_custom_path`, a fake class folder,
  `tools/make_sample_scans.py` papers. Grade in both modes, Sync, band, report.

### Stage 4 — Retire CGW exam code (CAM) · M
- Delete `exam_engine.py`, the `/api/exam/*` routes, `EXAM_SETUP_PAGE`, exam
  mode in `HTML_PAGE`, the exam export beacon, and CGW-only tests
  (`test_exam_grid`, `test_exam_naming`, `test_exam_portable`,
  `test_exam_reslice`, `test_exam_sections`). CAM2's suite covers what they
  tested.
- Remove CAM's exam-CSV ingest path (`is_exam_csv`, `ingest_exam_csv`,
  `load_exam_sidecar`), its `?` resolver dialog (D2, D5), and the sectioned
  banding panel with `section_bands` (D3). `chosen` and `section_bands` stay
  readable on old records but are no longer written. Update the
  CAM-side tests (`test_exam_identity`, `test_exam_resolved`,
  `test_exam_sections_app`) to the session reader, or retire the parts that
  only tested the CSV path.
- Rewrite the USER_MANUAL "Grading exam papers" section and ARCHITECTURE §4.
  Expected result: CGW `app.py` loses roughly 2,000 lines.

### Stage 5 — Bundle (CAM) · S
- `tools/build_windows_bundle.py` copies `exam_grading/` and starts it from the
  bridge. Extend `test_windows_bundle.py`. The dependencies are the same
  (Flask, Pillow, PyMuPDF, openpyxl), so nothing new is installed.

---

## 6. Risks and how each is handled

- **Two copies drift:** the subtree rule (Stage 0). CAM-specific code never
  goes inside `exam_grading/`.
- **Database schema change on a real database:** tolerant reader first
  (Stage 2), backup before the first write, and the teacher's explicit
  go-ahead before a real Sync with the new code.
- **Cloud sync of large session folders:** scans make each exam folder roughly
  20–100 MB (D6). CAM2 already detects conflict copies and saves from another
  computer.
- **Two local servers (CGW + CAM2):** both are single-instance, local-only and
  idle-stopping. The bridge checks the port the same way as
  `_ensure_workspace_running`.
- **CAM2 Phase 5 timing:** Stage 1 doesn't block CAM2's first release.
  Landing 1a–1d before it saves teachers a second download.
