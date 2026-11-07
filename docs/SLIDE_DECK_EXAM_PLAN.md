# Grading Google Slides final reports in CAM2: plan

**Status:** v1.1, 2026-11-01. All decisions (D1–D13, §3) are locked by the teacher.
v1.1 adds D13 (the teacher picks each folder's type) and Phase 1W (identifying
re-uploaded files by name, which drafts need too).
The [CAM2 engine upgrade](CAM2_ENGINE_UPGRADE_PLAN.md) added slide-shaped PDFs
to CAM2 and changed how CAM records one teacher decision per criterion
(D10–D13). Its D16 keeps drafts in the grading workspace. D17 defers the Drive
integration below. Use PDFs exported from slides for this release. Appendix A
of the upgrade plan describes the Apps Script route for a later classroom trial.
**Repos:** CAM = `C:\Project\criterion-assessment-metrics-public`;
CAM2 = `C:\Project\cam2-exam-grading`, vendored in CAM at `exam_grading/`.
Never edit `exam_grading/` in place: change CAM2, then
`git subtree pull --prefix exam_grading C:/Project/cam2-exam-grading main --squash`.

Read `CLAUDE.md` first. Phases 2–4 write into the **class cloud folder** and
change what CAM stores per exam. Every phase that touches real data follows
the sandbox, backup and permission rules there. Test decks hold fictional
names only, and no real student files are ever committed.

---

## 1. What we are grading

Some teachers assess a unit through one large end-of-unit submission instead
of many small assignments. Students get a slide-deck "final report" as a
Google Classroom assignment (*make a copy for each student*). They fill it in
as the unit goes on, hand in drafts part-way through, and turn in the whole
deck at the end.

The first example is a 19-slide final-report template:

| Slide | Content | Graded? |
|---|---|---|
| 1 | Cover: name, class, the place, painting title, rules, drafts | No (name only) |
| 2–13 | **Screens 01–12**, headed `SCREEN nn / 12 · STAGE … · TASK … · FILL IN …`, with strand labels | Yes |
| 14 | Sources | Evidence for Screen 05 |
| 15 | Checklist and word-total table | No |
| 16–19 | Task-specific clarifications (TSC) for Criteria A–D: the level descriptors | No (the rubric) |

The strand labels on each screen, merged per criterion as D5 says:

| Screen | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | 10 | 11 | 12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Labels | B i | B i | B i, B ii | D i | A i, A ii | B i | B i, B ii | D ii | C i, D i | C i | D i, D ii | D ii |
| Criteria | B | B | B | D | A (+ Sources) | B | B | D | C, D | C | D | D |

Other units and year groups use other templates and rubrics. Nothing in this
plan is specific to this deck except the test fixtures: screens are
found by their `SCREEN nn / NN` header, whatever NN is.

## 2. The teacher's routine (target)

1. **Classroom → personal Drive.** Where the school's Google Workspace blocks
   sharing to a personal account, the teacher downloads the Classroom
   assignment folder (Google Slides arrive as `.pptx`) and uploads it to a
   subfolder of the class's Drive `master_dir` on their personal Drive. Drive's
   **"Convert uploads to Google Docs editor format"** setting is on, so each
   upload becomes Google Slides again (D2).
2. **CAM picks up the folder.** The automatic Sync, run at start-up, on
   return from grading, and on class add or watch (`sync_all`), includes a
   Watch pass. That pass turns every new `master_dir` subfolder into an
   **ordinary** row with `folder_ref` set. Each Classroom assignment (Draft A,
   Draft B, the final report) is its own folder, so each becomes its own row.
3. **The teacher chooses each row's type** in its ⋯ Manage (D13):
   **Draft — comments only** (graded in the workspace, as today) or
   **Exam (CAM2)**. This is never automatic. Draft and final folders hold the
   same deck, so CAM cannot tell them apart.
4. **CAM fetches.** On an Exam (CAM2) row, the teacher presses **Fetch from
   Drive** in the exam panel. CAM:
   - exports each deck to PDF
   - puts its pages in template order
   - checks the format
   - matches students by file name
   - writes one compact slide-image PDF per student
   - then opens CAM2.
5. **CAM2.** The papers are already waiting in Step 1, named so CAM2 matches
   them to the class list automatically. The teacher sets up 12 whole-slide
   questions (rubrics imported from a spreadsheet) and grades screen by screen.
   A paper that doesn't fit gets **Not standard — grade in CAM**. Then
   **Send to CAM**.
6. **CAM.** The rubric→criterion panel applies the levels. Flagged papers,
   extra files and decks that failed the format check appear on a
   **follow-up list** with **Grade in workspace**.
7. **Workspace (follow-up mode).** Only the follow-up students are shown, with
   all of each student's files, the task rubric, and their CAM2 levels and
   comments as a starting point. The workspace grade is the student's final
   grade for that exam.
8. **Late work.** The teacher downloads and uploads it to the same Drive
   folder. The next automatic Sync sees no new *row* (the folder is already
   known), but CAM's exam panel shows **N new files on Drive → Add to CAM2**.
   Lateness itself is just a Window 3 comment (D7).

## 3. Decisions (locked 2026-11-01)

- **D1 – CAM2 stays Google-free.** All Drive work happens in CAM. CAM2 only
  ever sees local PDFs, and the standalone app works offline as before.
- **D2 – Google converts.** Uploads are converted to Google Slides by Drive's
  setting. CAM exports PDF with the existing `drive.readonly` token. No
  PowerPoint automation and no `.pptx` rendering on the laptop.
- **D3 – Keep only compact images.** The exported PDF is temporary. CAM
  renders each kept slide to a JPEG, builds an image-only PDF per student, and
  deletes the export. Originals stay on Drive.
- **D4 – One home.** The compact PDFs and crops live in the normal CAM2
  session folder `<CAM data folder>/<class>/exams/<exam>/` (the convergence
  plan's D6). There is no separate cache.
- **D5 – Grade by screen, in order.** One CAM2 question per screen, so
  grading follows the deck's own order. No strand-based questions.
- **D6 – One rubric per criterion.** Rubrics are named `Criterion A` to
  `Criterion D`, so CAM's `default_criterion` maps them automatically. Both
  strands' descriptors go in the same band, as in the IB subject guide.
  Strands are never stored separately. Reuse across classes that share a template is by
  CAM2's existing rubric spreadsheet import; there is no set-up template
  feature.
- **D7 – No lateness feature.** Downloading and uploading destroys the
  submission timestamps. The teacher notes lateness as a Window 3 comment.
  CAM derives no late flags for these exams.
- **D8 – Students are identified by file name.** After re-upload, the teacher
  owns every file, so CAM and the workspace match on the file name ("Tanaka
  Hana - Final Report Template", or the student's own "Family Given Final
  Report"). Anything unmatched goes to the 🧩 pool.
- **D9 – Late arrivals take one click.** CAM reports new files and the teacher
  presses **Add to CAM2**. A second file for a student already in CAM2 is
  either **replace** (only while that paper is ungraded) or **extra**, which
  puts the student on the follow-up list.
- **D10 – Drafts stay out of CAM2.** Drafts use CAM's existing
  "Draft — comments only" type in the workspace.
- **D11 – CAM2 changes stay minimal.** The changes are:
  - slide page sizes 16:9 and 4:3
  - JPEG crops
  - a host-mode-only "Not standard — grade in CAM" paper marker
  - an optional papers folder in the host handoff
  
  All further accommodation is on the CAM side.
- **D12 – One grade owner per student.** For each student on each such exam,
  CAM records who owns the grade: CAM2, or the workspace after a follow-up.
  CAM never applies a grade from the side that doesn't own it, so a paper can
  never be graded twice.
- **D13 – The teacher picks each folder's type, by hand (added 2026-11-01).**
  A watched folder arrives as an ordinary row. In its ⋯ Manage, the teacher
  chooses **Assignment**, **Draft — comments only** or **Exam (CAM2)**. CAM
  never guesses, so the same deck in a draft folder and a final folder can't
  end up graded in the wrong app. Once an Exam (CAM2) row has a CAM2 session,
  CAM refuses to switch its type. Retiring the exam (its folder goes to
  `exams/_deleted/`) is the only way back.

## 4. What exists, and what is missing

| Need | Exists | Missing |
|---|---|---|
| Drive access | `app.py` `_drive_list_subfolders` (token from the workspace's `token.json`, `drive.readonly`); workspace `fetch_folder`, `pdf_path` (download with `alt=media`) | Listing files in an exam folder from CAM; `files.export` to PDF for Google Slides |
| Exam ↔ Drive folder | `_watch_class_master` sets `Assignment.folder_ref` | Using `folder_ref` for an Exam row's fetch |
| Student matching | `engine/ingestion.py` `resolve_identity` (alias, prefix), 🧩 pool; CAM2 `roster.auto_match` (roster name contained in the file name) | Stripping template titles and class prefixes from Drive names before matching |
| Page shape | CAM2 `slicer.py` `PAPER_SIZES_MM` / `GRIDS` / `_DETECT_SIZES_MM` (A4, B5, A3 only); `static/js/boxes.js` mirrors the grids | 16:9 and 4:3 slide sizes, detected by aspect ratio |
| Crop size | `slice_all` saves `crops/<q>/<s>.png` at 200 dpi (`slicer.py:510`); read at `app.py:432`, `reports.py:278`, `workflow.py:513` | JPEG crops for new sessions |
| Handoff | CAM2 `engine/host.py` (`exam_name`, `class_name`, `session_folder`, `roster`); CAM `exam_bridge.handoff`, `launch_exam_setup` | Optional `papers_folder` |
| Results | `exam_bridge.read_session` → `ExamResult`; `_sync_cam2_sessions`, `_pull_cam2_sends`; `_render_cam2_rubric_banding` | Paper marker on `ExamResult`; follow-up list; grade owner |
| Rubric reuse | CAM2 `rubrics.import_rubrics` + `template_xlsx` | Nothing (D6) |
| Workspace hand-off | `_publish_workspace_grades` → `cam_grades_<folder>.json`, read by the workspace's `load_cam_published` | Follow-up payload (rubric bands, CAM2 levels and comments, locked students); identifying students by file name |
| Drafts | "Draft — comments only" assignment type | Nothing (D10), except identifying re-uploaded files (Phase 1W) |
| Choosing CAM2 for a watched row | ⋯ Manage (`manage_assignment_dialog`) offers the Draft checkbox and criteria on non-exam rows only; exams today are made by hand (Add assignment → Exam) | An **Exam (CAM2)** type for watched rows (D13, Phase 2) |

## 5. Phases

Sizes: S ≈ an afternoon, M ≈ a day, L ≈ several days. Phases land in order,
except that Phase 1 (CAM2) can run alongside Phase 0, and Phase 1W stands
alone: it can land first, because drafts need it now.

### Phase 1W — Workspace: identify re-uploaded files by name · S–M (CAM repo)

Drafts are graded in the workspace today (D10). After a download and
re-upload, the teacher owns every file. `pick_student` (owner → sharer → last
modifier → permissions) then finds only the teacher and returns "Unknown
student" for every file.

1. **Name helper.** One function strips a Drive file name to a student name:
   it removes the template title (" - Final Report Template"), a class prefix
   (`9.1`), words such as "Final Report", and the extension. It then matches
   the result against the class roster and aliases with `resolve_identity`,
   making only certain matches. Put it in `engine/` if the workspace can import
   it there (check how `load_matching_context` reaches CAM's data), otherwise in
   the workspace. Phase 2 reuses it.
2. **Fallback in `pick_student`.** When every identity source is the teacher,
   use the helper on the file name. Files that still can't be matched stay
   visible as unassigned, never guessed.
3. **Tests:** Classroom's "Name - Title" form, a student-renamed file, a
   reversed name order, Japanese names, and an ambiguous name that stays
   unassigned.

### Phase 0 — Prove the Drive route (sandbox; no product code) · S–M

Build fictional decks from the template. Fill some with photos, give some
deleted slides, extra slides or a renamed file, and include one big
photo-heavy deck. Run them through the real routine on a **test** folder in the
personal Drive, with Convert uploads on. Use a throwaway script in the
scratchpad (not the repo) and the existing token. Record:

1. **Export limit.** `files.export` has a 10 MB cap. Find the largest deck
   size that exports. Check that the `exportLinks["application/pdf"]` URL
   (via `AuthorizedSession`) works beyond it. That decides the fallback.
2. **Page size and ratio** of the exported PDF: a template that started in
   PowerPoint is 13.333 × 7.5 in, while Google's own 16:9 is 10 × 5.625 in.
   Both are 16:9.
3. **Conversion fidelity.** Compare `.pptx` → Google Slides → PDF with the
   original. Look for text boxes moving, photos cropping and fonts changing.
4. **Header text.** Check that PyMuPDF `get_text` finds `SCREEN nn / 12` and
   `SOURCES` on the right pages.
5. **Image size and quality.** Find the JPEG dpi and quality that keep
   brushwork readable when zoomed in CAM2's grading view, and the resulting MB
   per student. This sets the defaults in Phase 2.
6. **Drive metadata after upload:** mimeType, the name with `.pptx` dropped,
   owner = teacher, and whether a second upload of the same name gets a new
   file id.

**Done when** each of the six has a written answer in this doc (§7). If (1) or
(3) fails, stop and return to the teacher before Phase 2.

### Phase 1 — CAM2: slides, light crops, the marker, the folder · M (CAM2 repo)

1. **Slide sizes.** Add `Slide 16:9` and `Slide 4:3` to `PAPER_SIZES_MM`
   (portrait order, so `landscape` is true) and to `GRIDS`, at about 5 mm
   cells: about 51 × 29 for 16:9 and 51 × 38 for 4:3. The cells should be
   square. Detect slides by **aspect ratio**, not millimetres, because
   PowerPoint-origin and Google-origin decks differ in size but not shape.
   Mirror the grids in `boxes.js`, and add the names to `i18n/en.json` and
   `ja.json`. Old sessions are untouched.
2. **JPEG crops.** New sessions write `crops/<q>/<s>.jpg` (quality from
   Phase 0, about 85). The session config records `"crop_format": "jpg"`.
   Sessions without that key keep `.png`, so nothing old moves. One helper
   gives the crop path, used by the three readers above and by
   `_forget_student_files`.
3. **Paper marker (host mode only).** Add a **Not standard — grade in CAM**
   toggle on the grading card or the paper strip, stored as
   `overall[<paper>]["not_standard"] = true` in `grades.json`. A marked paper:
   - counts as finished for progress and `complete`
   - is left out of class statistics and reports
   - shows "Grade in CAM" in Step 5 and the Excel gradebook
   - counts toward `grades_mass`.
   
   The standalone app never shows it.
4. **Papers folder in the handoff.** An optional `papers_folder` (absolute
   path) pre-selects Step 1's "one file per student" source, and pre-fills
   **Add more papers**. `host.normalize` keeps it only when it is an existing
   folder. Older CAM2 versions ignore it.
5. **Removing an ungraded paper.** Check that `edit_pages` can remove a paper
   with no grades, which D9's *replace* needs. If it can't, add the smallest
   removal that refuses graded papers.

**Tests** (CAM2 `tests/`):
- grid and range round-trips for both slide sizes
- detection of 13.333×7.5 in, 10×5.625 in and 10×7.5 in
- JPEG and PNG crop paths, with old sessions unchanged
- the marker's effect on summary, reports and gradebook
- handoff with and without `papers_folder`

`PYTHONUTF8=1`; `test_ui_syntax` needs Node. Then pull the subtree into CAM
and run `tools/run_all_tests.py`.

### Phase 2 — CAM: Fetch from Drive · L (CAM repo)

A new framework-free module, `engine/slide_decks.py`, holds the logic. Drive
calls are passed in, so tests use fakes.

0. **Exam (CAM2) type in ⋯ Manage** (D13). For a watched row (`folder_ref`
   set) that isn't an exam yet, offer **Assignment**, **Draft — comments
   only** and **Exam (CAM2)** in `manage_assignment_dialog`, where only the
   Draft checkbox exists today. Choosing Exam (CAM2) sets `is_exam` and records
   in the row's `exam_sessions` entry that its papers come from Drive. It
   refuses the switch if the row already has grades. Once a CAM2 session exists
   for the row, the type control is replaced by a note pointing to Retire
   exam. Only Exam (CAM2) rows show the Fetch from Drive panel below.
1. **List** the exam's `folder_ref` with `id, name, mimeType, size,
   modifiedTime`. Sort the files into decks (Google Slides) and everything
   else (extras).
2. **Match** each file to a student with the Phase 1W name helper.
   Ambiguous or missing matches go to the 🧩 pool and are never guessed.
3. **Export** each deck to PDF in a temporary folder, using the Phase 0
   fallback for large decks.
4. **Normalise.** Read each page's header. Keep the cover, Screens 01–NN in
   order, and Sources, and drop the checklist and TSC slides. Render each kept
   page to a JPEG at the Phase 0 settings, write one image-only PDF named by
   the student's **roster display name** (so CAM2's `auto_match` matches it),
   then delete the export.
   
   The normalised layout is always: page 1 = cover, pages 2…NN+1 = Screens
   01…NN, last page = Sources. A screen that is missing becomes a blank page
   with "Screen nn missing" printed on it.
5. **Format check.** Each student is classed as one of:
   - **ok**
   - **needs follow-up**: screens missing or repeated, extra slides, or no
     deck at all, only other files
   - **has extras**: other files alongside a good deck
   - **unmatched**
   
   A student with a usable deck is still sent to CAM2 even when they have
   extras or follow-up reasons.
6. **Staging.** The PDFs are written to `exams/_incoming/<exam folder>/`, a
   sibling of the session folder, and passed to CAM2 as `papers_folder`. They
   can't go inside the session folder, because CAM2's host mode refuses to
   start a session in a folder that isn't empty (`host_folder_not_empty`,
   `exam_grading/app.py`). `exam_bridge.find_sessions` already skips `_`
   folders. Once CAM2 has imported a file (its name appears in
   `cam2_session.json` `students[].source`), CAM deletes it from staging at the
   next sync, so scans aren't stored twice.
7. **Fetch record.** Persist it in the exam's `exam_sessions` entry
   (DATA_DICTIONARY C.8): per Drive file id, the student key, modifiedTime,
   status (`sent` / `extra` / `unmatched` / `follow_up` / `replaced`) and when
   it was fetched. "New files" means file ids not in the record. Update
   DATA_DICTIONARY.
8. **UI** (Window 1 exam panel, next to the CAM2 status line):
   - **Fetch from Drive**, with a progress bar and a summary of how many
     students are ready, need follow-up, have extras or are unmatched
   - **N new files on Drive → Add to CAM2**, checked when the panel opens and
     at Sync, never polled
   - for a second file, **Replace** (ungraded only) or **Extra**
   - then the usual **Open in CAM2**, with the handoff carrying
     `papers_folder`.
9. **No lateness.** These exams derive no late flags (D7).

**Tests:**
- the type switch: offered on watched non-exam rows, refused once graded,
  locked once a CAM2 session exists
- Drive files routed to the 🧩 pool by the Phase 1W helper
- header mapping, including missing, repeated and extra slides, and a 4:3 deck
- normalised page order
- the record and new-file detection
- the staging clean-up rule

All with fake Drive responses and fictional PDFs made in the test.

### Phase 3 — CAM: follow-up list and grade owner · M (CAM repo)

1. `exam_bridge.read_session` reads `not_standard` into a new optional
   `ExamResult.not_standard` field. Older databases still load.
2. The **follow-up list** joins CAM2's marked papers with the Phase 2
   follow-up, extra and unmatched students. It is shown in the exam panel with
   the reason and **Grade in workspace**.
3. **Grade owner** per student, kept in the exam's `exam_sessions` entry as
   `owner[<student key>] = "cam2" | "workspace"`. The default is `cam2`. It
   becomes `workspace` when the teacher sends that student to the workspace.
   It is shown, and can be reversed, on the follow-up list.
4. `_render_cam2_rubric_banding` locks workspace-owned rows ("graded in
   workspace"). When CAM2 later changes a workspace-owned student, CAM shows a
   notice and never applies the change.
5. Workspace results for this exam are applied only for workspace-owned
   students; any other rows are ignored with a notice. Check the Stage 4
   `is_exam_csv` skip guard, so a workspace export for an exam row is neither
   skipped nor mistaken for an old exam CSV.

**Tests:** owner defaults, flips and locks in both directions; a CAM2 re-send
after a workspace grade; the CSV guard.

### Phase 4 — Workspace: follow-up mode · M–L (CAM repo, `cam_grading_workspace/`)

1. **Identity by file name** is already in place from Phase 1W.
2. **Follow-up payload.** CAM's handoff for the exam folder carries:
   - the CAM2 rubric bands (one per criterion, D6)
   - each follow-up student's CAM2 levels per screen, final levels and
     comments
   - the follow-up reason
   - the list of CAM2-owned students
   
   It uses the existing `cam_grades_<folder>.json` route, extended, or a
   sibling file, and is consumed the same way.
3. **The screen.** Only follow-up students are gradable. Others are greyed
   out as "Graded in CAM2". Each student shows all their files (deck and
   extras) through the existing viewers, the task rubric beside the band
   picker, and CAM2's levels and comments as starting values. The export
   goes back to CAM and lands under Phase 3's owner rule.

**Tests:** payload round-trip; that locked students can't be exported.

### Phase 5 — Optional: word counts · S (CAM repo)

From the PDF text CAM already reads in Phase 2: typed words per screen and in
total, against the cover's limits (for example, 180 per screen and 2,000 in
total). Words inside photos aren't text, so they never count, as the rules
say. Shown in the fetch summary and on the follow-up list. CAM2 doesn't
change.

## 6. Risks

| Risk | Handling |
|---|---|
| A photo-heavy deck goes over the 10 MB export cap | Phase 0 proves the `exportLinks` fallback; a deck that still fails goes on the follow-up list, never silently dropped |
| Google's conversion shifts layouts | Phase 0 compares; screens are grabbed as whole slides, so small shifts don't move a crop |
| A wrong student match | Only certain matches are made (resolve_identity, `auto_match`); everything else goes to 🧩 and is never guessed |
| Two classes have students with the same name | Each class's own roster and folder; no cross-class matching |
| Storage | No PDF kept, JPEG pages and crops, staging cleared after import; Phase 0 measures MB per student |
| Writing into the real class folder | `CLAUDE.md` sandbox for every run; a fetch only ever adds files under `exams/<exam>/`, and the follow-up owner map never deletes grades |
| An older CAM on another computer drops new `exam_sessions` keys | Same warning as the v2026.11.01 release notes: every computer on the data folder must update |
| OneDrive syncing while CAM2 writes | CAM2's existing save-safety (`SafeJsonFile`, lock); staging files are written atomically |

## 7. Phase 0 results

*(To be filled in by Phase 0.)*

## 8. Out of scope

- Classroom API, turn-in times and late flags (D7).
- Grading by strand, or storing strand levels (D5, D6).
- Saved set-up templates in CAM2 (D6).
- Grading drafts in CAM2 (D10).
- Rendering `.pptx` on the laptop (D2).
