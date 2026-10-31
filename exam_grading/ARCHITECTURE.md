# CAM2 Architecture

This describes how CAM2 is built. For what it should do and why, see
[PLAN.md](PLAN.md).

## The big picture

```
 Teacher's browser  ──HTTP (127.0.0.1 only)──▶  app.py (Flask)  ──▶  engine/  ──▶  Session folder
 (static/, templates/)                         thin REST layer       all logic      (disk, USB,
                                                                                     OneDrive, …)
                                                     │
                                                     └──▶  App-data folder (this computer only)
```

- **The browser is only the screen.** Everything that matters — cropping,
  saving, calculations, reports — happens in Python, in `engine/`.
- **`app.py` is thin.** It turns HTTP requests into engine calls and turns
  `UserError`s into translated messages.
- **`engine/` has no Flask imports.** Every module can be tested on its own.
- **One session folder per exam.** It holds everything for that exam, so it
  can be moved, copied or opened on another computer.
- **The app-data folder** (`%LOCALAPPDATA%\CAM2 Exam Grading` on Windows,
  `~/Library/Application Support/CAM2 Exam Grading` on Mac) holds only per-computer things: the recent-sessions
  list, the language preference and emergency copies.

## Engine modules

| Module | Job |
|---|---|
| `errors.py` | `UserError(code, **params)`: the only way the engine reports problems to teachers. `code` is an i18n key (`error.<code>`). |
| `model.py` | Shapes of `cam2_session.json` and `grades.json`, new-file builders, format/version check, `grades_mass()` for the wipe guard. |
| `slicer.py` | Paper sizes and grids, range parsing, drag-to-cell snapping, paper detection, copying scans in, splitting a combined PDF, page-count checks, cropping (several boxes stitched into one image), previews, thumbnails, safe file names. |
| `storage.py` | Session folders, `SafeJsonFile` (all save-safety rules), the advisory lock, recent sessions, preferences, app-data location, relative paths. |
| `rubrics.py` | Teacher rubrics: level parsing (`3`, `5–6`, `５～６`), validation, Excel/CSV import, blank template. |
| `roster.py` | Class lists: header and name-column guesses, name extraction, pasted names, file-name auto-matching. |
| `tables.py` | Reads `.xlsx` and `.csv` (UTF-8 or Shift-JIS) into rows of text. |
| `grading_summary.py` | Recording a grade (with validation), choice groups (best N, or the teacher's pick per student: `pick`, `set_choice`, a *pending* group counts nothing), totals, rubric averages, round-half-up, report overrides, class statistics, progress. In Rubric mode a question can be assessed on several criteria (`rubric_ids`); each (question, criterion) pair is a *slot* with its own level, stored in the grade entry's `levels` and read through `level_of()`, which also reads sessions saved with one `rubric_id`. Summaries key per-slot statistics as `q2/r3` (`slot_key`). |
| `keywords.py` | Quick comments: the exam's list (`keywords` in the config, or five defaults in the app language), and `apply()`, which ticks keywords on one answer and rebuilds the generated first line of its comment. The line last written is kept as `keyword_text`, so it is replaced exactly and the teacher's own text below it is kept. |
| `host.py` | Host mode (CAM opening one of its exams): reads and checks the handoff file, gives the session the host's class list keyed by `external_id` (ids stay put when a name changes), and stamps `host_ready_at` when the teacher sends the results. |
| `i18n.py` | Looks up text in `i18n/en.json` / `i18n/ja.json`; translates `UserError`s. |
| `pickers.py` | Native folder / PDF dialogs: Windows IFileOpenDialog (in a child process: `python -m engine.pickers`, or `CAM2.exe --pick` when packaged) with a PowerShell fallback, macOS `osascript`. Finds the Documents folder. |
| `pages.py` | Turning scans into one PDF per paper: a page is a `Ref` (file, page, turn). It joins several PDFs or page photos into one stack and groups it into papers. It also unfolds booklets scanned open: each side is cut in half with `show_pdf_page(clip=…)`, so quality is kept, and pages are put in reading order by `booklet_layout`. A page with a stored rotation is first baked upright with `remove_rotation`. Photos are turned upright from their phone orientation and reduced to about 200 dpi. Also makes the Step 1 preview of paper 1. |
| `workflow.py` | Steps 1–3 as operations on an open session: check and import scans (`check_source`, `import_scans`), late papers (`add_papers`), page fixes (`edit_pages`), choose the real session folder, layout/mode/rubric/question set-up, `check_ready`, slicing (all papers, or `slice_students` for some), class list and matching, display names. |

| `reports.py` | One PDF per student. A cursor flows blocks down A4 pages with PyMuPDF. Text goes through `insert_htmlbox` (wrapping, and Japanese through MuPDF's built-in CJK font), answer images are re-encoded as JPEG, and fonts are subset before saving. Each question is one row (label · answer · grade beside it, then the comment); in Rubric mode the rubric's descriptors are printed once under the header rather than under each answer. It shows the *reported* total or final level. File names are `<Student>_<Exam>.pdf`, or `UNMATCHED_<scan>.pdf` for a paper not matched to the class list. Old reports are replaced on each export. |
| `gradebook_xlsx.py` | Master Excel gradebook (openpyxl), with sheet names and headings in the report language. Values come from `grading_summary`, not Excel formulas, so they match CAM2's rounding. Adjusted cells are yellow and ungraded cells red. An open file gives `report_file_open`. |

Phase 5 adds the package builders.

## Server and browser

| File | Job |
|---|---|
| `launcher.py` | `--host <handoff.json>`: opened by CAM for one exam (a running CAM2 is handed it through `POST /api/host/handoff`). **Single instance:** if CAM2 is already running on this computer, it just opens the browser on it (`server.json` in app data records the port). Otherwise it serves on `127.0.0.1`, on the first free port from 5182. It stops 10 minutes after the last heartbeat, or on **Quit**; after the computer wakes from sleep the 10 minutes start again, so an open tab can check in first. Without a console (`pythonw`), output goes to `<app data>/logs/cam2.log`. |
| `appstate.py` | **What the server remembers:** the one open session (config, grades, save-failure flag) and background **jobs** for importing and slicing (one at a time; the browser polls their progress). `save_config()` keeps a change in memory even when the save fails, so the browser can show the red banner and retry. |
| `app.py` | **JSON routes**, grouped by screen (see below). Errors come back as `{"error", "message", "params", "save_error"}`, with status 400, or 409 for save problems. It also stops the browser keeping old scripts after an upgrade (`Cache-Control: no-cache`). |
| `templates/index.html`, `static/app.css` | **The page:** one HTML shell and one stylesheet. Light and dark themes, large click targets, and the Japanese system fonts listed first. |
| `static/js/*.js` | **The screens:** plain ES modules with no framework, no build step and no CDN, so it works offline. |

### JavaScript modules

| Module | Job |
|---|---|
| `api.js` | `fetch` wrapper and job polling |
| `i18n.js` | `t()` with text loaded from the server |
| `ui.js` | the `h()` element builder, modals, toasts, progress overlay, picker-wait message |
| `store.js` | the browser's state and `act()`, which runs a server call, updates the session and sends errors to a toast or the red banner; `criteriaOf()` (a question's criteria) and `gradeOf()` (one grade on one paper; Rubric-mode levels come from the server's summary, so old and new grade layouts read the same) |
| `main.js` | header, step bar, banners, routing, heartbeat |
| `start.js` | start screen: recent sessions, open a folder, "open on another computer?", emergency restore |
| `step1.js` | new-session form: the source (joined PDFs, one file per student, page photos), layout (pages or booklet) and live preview of paper 1. Also the thumbnail check, with the page-fix tools in each paper's viewer and **Add more papers** |
| `step2.js` | marks or rubric, rubric builder, choice questions, slicing |
| `boxes.js` | box drawing: grid maths that mirrors `slicer.py`, drag-to-snap, multi-box questions, the check strip, and the "new question or move the box?" prompt |
| `step3.js` | class-list upload with the column picker, paste, typed names, and the matcher combobox |
| `step5.js` | review table, one column per question (and criterion): click any grade (or an amber "?") to open it in Step 4, which then offers "Back to review"; report-total or final-level overrides with ↺ reset; overall comments; class statistics; report language, export, and "Open the reports folder" |
| `step4.js` | grading screen (paper order is the class order, or with **Shuffle papers** a seeded shuffle per question: `papers()`): one item per question, or per question and criterion in Rubric mode (tabs switch criterion on the same paper); question and paper navigation, paper strip, "Show ungraded only", the zoomable answer (wheel zooms, drag pans) or the whole page with the box outlined, the grade badge, and the grading card (mark buttons, a number box above 15 marks, or rubric bands with a button per level; Not answered; comment) |

### Routes

| Area | Routes |
|---|---|
| Host | `POST /api/host/handoff` (from `launcher.py --host`), `POST /api/host/ready` (`ready`: send the results to CAM, or take them back) |
| Shell | `GET /`, `GET /api/ping`, `GET /api/i18n`, `POST /api/language`, `GET /api/state`, `POST /api/heartbeat`, `POST /api/quit` |
| Sessions | `POST /api/session/{open,create,close,reopen,forget,restore-emergency}`, `POST /api/save`, `POST /api/step`, `GET /api/job/<id>` |
| Step 1 | `POST /api/pick`, `POST /api/inspect`, `POST /api/preview-paper` (paper 1 as JPEG data URLs, no session needed), `GET /api/default-folder`, `POST /api/scans/replace`, `POST /api/scans/add` (a job: late papers), `POST /api/pages/edit` (`student`, `page`, `action`; returns `where` the page is now), `GET /api/thumb/<student>` |
| Step 2 | `POST /api/setup/{layout,mode,rubrics,rubrics/check,rubrics/import,questions}`, `GET /api/setup/rubrics/template`, `POST /api/slice`, `POST /api/slice-question` (a job: one question for every paper), `GET /api/page/<student>/<page>`, `GET /api/preview-crop/<student>` |
| Step 3 | `POST /api/roster/{upload,columns,paste,clear}`, `POST /api/students/<student>/match`, `GET /api/crop/<region>/<student>` |
| Step 4 | `POST /api/grade` (value and/or comment and/or `keywords`; saves `grades.json` at once), `POST /api/setup/keywords` (the quick-comment list), `POST /api/position` (the question and paper on screen, for resuming) |
| Step 5 | `POST /api/overall` (overall comment, report-only total or final levels; empty means "use the calculated value"), `POST /api/choice` (`student_id`, `group_id`, `questions`: the answers that count in a "teacher picks" choice), `POST /api/export` (a job: `what` is `all` or `excel`, plus `language`), `POST /api/open-folder` (shows `reports/` in Explorer or Finder) |

**The session view** sent to the browser includes the grades, progress
counts and the class summary, so every screen draws from one object.

**Image caching.** Image URLs carry `?v=<sliced_at>`. With it the browser may
keep the image for a day, so the grading screen doesn't flicker when it
redraws after each click. Re-slicing changes `sliced_at`, so new crops are
always fetched. Without `v`, images are never kept.

**Files are only served from inside the open session.** Image routes take
ids, which are looked up in the session, never paths, and every path goes
through `storage.resolve_path()`.

### Rules the UI follows

- **Every change is saved straight away**, with typing debounced. There is no
  "unsaved" state in the browser.
- **The step bar** only reaches steps already visited. "Continue" buttons move
  one step on, and the server checks that the papers are sliced before Step 3.
- **Editing boxes after slicing** marks the papers as needing slicing again,
  and Step 3 stays locked until they are re-sliced. Changing only labels,
  marks or rubrics does not. `crops_of` in the config records the boxes each
  region's crops were cut from, so a box moved back needs no slicing, and
  **✎ Adjust this box** in Step 4 re-slices only that question
  (`workflow.slice_question`, `POST /api/slice-question`) before returning to
  the same paper. Anything that changes the papers while they are not all
  sliced (new scans, late papers, page fixes, a layout change) drops
  `crops_of`, so only slicing everything makes them current again.
- **Changing paper size or grid density** clears the boxes after asking, since
  they no longer fit the new grid. Labels and marks are kept.
- **A box drawn where it doesn't overlap the current item's box** on that page
  makes CAM2 ask: is it the next question, or a move? It does this because
  teachers forget to press "next".
- **If the save folder is not empty** and is not a session, CAM2 creates
  `<exam name>` inside it instead of scattering files.
- **Grading:**
  - Every click saves. A comment saves 0.7 s after typing stops and when
    the box loses focus, without redrawing the screen, so typing is never
    interrupted.
  - After a grade, keyboard focus moves to **Next paper**. There is no
    automatic advance, so a comment can still be added.
  - **Show ungraded only** is on when resuming a session that already has
    grades. The paper on screen stays visible after it is graded.
  - The whole-page view stays on as the teacher moves between papers.
- **Marks or rubric is fixed once any paper has a grade** (`mode_locked`),
  since marks and levels can't be converted into each other.

## The session folder

```text
<Session folder>/
├── cam2_session.json     exam set-up and resume position
├── grades.json           every grade and comment (saved on each click)
├── cam2.lock             "open on <computer>" (advisory)
├── scans/                copies of the scans, or one PDF per paper cut from a stack
│   └── sides/            booklets only: each paper's sides as scanned, before unfolding
├── crops/<id>/<student>.png   one image per question per student
├── thumbs/               page-1 thumbnails for the Step 1 check
├── backups/              daily copies of the two JSON files (newest 14)
└── reports/              Excel gradebook and student_pdfs/
```

- **How papers came in.** `config["import"]` records the class's scan:
  `type` (`combined`, `folder` or `photos`), `sources`, `layout` (`pages` or
  `booklet`), `pages_per_student` (a booklet's page count) and the
  front/back flips and `inside_first`. Each later set of papers adds an entry to
  `more_imports`, and each student has a `batch` (0 for the class). Page
  fixes that shift pages stay inside one batch: a late paper is never pulled
  into the class's stack. A booklet student also has `sides` (its file in
  `scans/sides/`), `side_turns` (by scanned side), `sides_reversed` and
  `sheet_swaps` (by sheet, counted from the outside), from which its paper
  is unfolded again after a sheet fix.
- **Ids, not names, key everything.** Questions are `q1`, `q2` …, students
  `s001` …, rubrics `r1` …, roster entries `n001` … The name box uses the
  reserved id `__name__`. A teacher can rename "Q1" or fix a student's name
  without breaking crops or grades.
- **Paths inside the session are relative**, with forward slashes (for example
  `scans/Student_001.pdf`). `storage.resolve_path()` refuses anything that
  would leave the folder.
- **The full JSON shapes** are documented at the top of `engine/model.py`.

### Grade values

| In `grades.json` | Meaning | Counts as |
|---|---|---|
| a whole number | the mark or level given | itself |
| `"not_answered"` | the student left it blank | 0, except a choice-group question that was not chosen |
| missing or `null` | not graded yet | nothing; the student is flagged incomplete |

## Saving safely (`storage.SafeJsonFile.save`)

Every save of either JSON file runs these steps, in this order:

1. **Stamp the file** with `session_id`, `generation + 1`, `saved_at` and
   `saved_by` (the computer's name).
2. **Write the emergency copy** to `<app data>/emergency/<session_id>/`. This
   happens first, so nothing is lost if anything below fails.
3. **Check the folder can be reached** (USB stick plugged in, network drive
   connected). If not: `FolderUnavailable`.
4. **Check for cloud conflict copies** such as `grades-PC.json`,
   `grades (1).json` or `grades … conflicted copy.json`. If any: `ConflictCopiesFound`.
5. **Check nobody else has saved.** The file on disk must have the same hash
   as the one we loaded or last saved. If not: `ChangedElsewhere`. If it has
   vanished: `FileMissing`.
6. **Wipe guard** (grades only): a save that would drop the file's work
   (graded cells plus comments) from 10 or more to under a third is refused
   with `WipeBlocked`, unless `allow_shrink=True`.
7. **Daily backup:** the first save each day copies the previous version to
   `backups/` and trims old backups to the newest 14.
8. **Atomic write:** temp file, `fsync`, `os.replace`. A rename blocked by a
   sync program's brief lock is retried with back-off; if it never succeeds:
   `WriteFailed`.
9. **Read back** the written file and compare its hash. If it differs:
   `WriteNotVerified`.

**Recovery:** when a session is opened, `newer_emergency_copy()` returns the
emergency copy if it holds a later generation than the session folder. The UI
then offers to restore it.

**The lock file** (`cam2.lock`) only warns. Cloud folders cannot do real file
locking, so the generation check in step 5 is what actually prevents
overwrites. A lock counts as stale if it wasn't refreshed in the last 10
minutes, or if it came from this same computer: only one CAM2 runs per
computer, so such a lock was left by a crash or a forced stop.

These rules are ported from CAM's `engine/persistence.py`. CAM2 keeps the
same ideas in a simpler form, because each session has its own small files
instead of one big database.

## Grid geometry

- **Grid sizes.** New sessions use one grid of ~5 mm cells (density
  `"5mm"`: A4 42 × 60, B5 36 × 51, A3 60 × 84). Teachers drag boxes rather
  than type cell names, so the grid only sets how finely a box can follow the
  paper. Older sessions keep CAM's `"normal"` (compact, ~1.4 cm) or `"fine"`
  (~1 cm) grid, because their saved ranges name those cells; any layout
  change moves them to `"5mm"`. Landscape pages swap columns and rows.
- **Margins are the teacher's.** Snapping only rounds outward to whole cells
  (at most ~5 mm). Room for scan drift and for writing outside the printed
  box comes from drawing the box generously, which the Step 2C coach asks for,
  checked with the "Check on other papers" strip.
- **Cell size.** One cell is simply `image_width / cols` by
  `image_height / rows` pixels. CAM's auto-DPI formula reduces to exactly
  this, and `tests/test_slicer.py` checks that the two agree.
- **Ranges.** A box is written `page2!A4:J10` and stored as text in
  `cam2_session.json`. It is parsed against the exam's layout when needed.
- **Dragged boxes.** `snap_rect()` turns a box dragged in the UI (as fractions
  of the page) into whole cells, never smaller than what was dragged.
- **Rendering.** Pages are rendered at 200 DPI, so every student's crop of a
  question comes out the same size.

## Text and errors (i18n)

- **One place for text.** Every string a teacher sees is in `i18n/en.json`
  and `i18n/ja.json`, under the same keys.
- **Errors are codes.** Engine code never writes sentences. It raises
  `UserError("bad_range", range=...)`, and the UI shows
  `i18n.error_text(err, language)`.
- **Tests keep the two files in step.** `tests/test_i18n.py` fails if:
  - a key is missing in one language,
  - the `{placeholders}` differ between languages,
  - or the engine raises an error code that has no text.
- **The Japanese text needs a check by a native speaker** before release.

## Tests

```bash
python -m unittest discover -s tests -t .
```

| File | Covers |
|---|---|
| `test_slicer.py` | Grids (ported from CAM's `test_exam_grid.py`), detection, splitting, stitching, slicing |
| `test_pages.py` | Booklet page order, joined PDFs, page photos, unfolding (including upside-down backs), preview, page fixes that shift a stack, sheet turns and swaps, the graded-paper lock, late papers |
| `test_storage.py` | Every save-safety rule (ported from CAM's cloud-safety and concurrency tests), the lock, recent sessions, paths |
| `test_rubrics.py` | Level parsing, overlaps, imports, template round trip, Shift-JIS |
| `test_roster.py` | Spreadsheet reading, column guesses, pasted names, auto-matching (including macOS-decomposed names) |
| `test_grading_summary.py` | Validation, round-half-up, choice groups (ported from CAM's `test_exam_sections.py`) with best N and teacher picks, rubric averages, overrides, class statistics |
| `test_keywords.py` | Quick-comment list defaults and clean-up, rebuilding the generated line while keeping typed text, language changes |
| `test_i18n.py` | Key and placeholder parity, error coverage |
| `test_pickers.py` | Picker launching on Windows and macOS (ported from CAM's `test_folder_dialog.py`), the packaged app's `--pick`, UTF-8 output |
| `test_launcher.py` | The idle watchdog: stopping with no tab open, and starting the wait again after the computer sleeps |
| `test_workflow.py` | Import from a folder and a combined PDF, re-import, set-up drafts vs. `check_ready`, layout changes, slicing a two-page question, matching names |
| `test_app.py` | The server through Flask's test client: the whole Steps 1–3 flow, translated errors, a save failure kept in memory and then retried, the other-computer prompt, emergency restore, file-serving safety |

`test_i18n.py` also checks that every `t("…")` key in `static/js/` exists in
both languages.

`test_reports.py` covers report content in English and Japanese (dates, totals, overrides, not answered, not graded, choice questions not counted, descriptors), file names (duplicates, unmatched papers, unsafe characters), replacing old reports, one failing report not stopping the rest, the gradebook's values and highlighting, Japanese sheet names, and a gradebook left open in Excel.

`test_ui_syntax.py` parses every browser module with Node.js, and is skipped
if Node isn't installed. A syntax error in any one module stops the whole app
loading, and no other test would notice.

`tools/make_sample_scans.py` makes fake papers for trying the app by hand.

`tests/helpers.py` builds test PDFs and images with coloured grid cells, so
crop positions can be checked by colour. No real student data is used.

## Packaging (Phase 5)

| | Windows | Mac |
|---|---|---|
| Python runtime | python.org's embeddable Python 3.14 | `python-build-standalone`, both Apple Silicon and Intel |
| Builder | `tools/build_windows.py`, ported from CAM's `build_windows_bundle.py` | `tools/build_mac.py` |
| Launcher | `Start CAM2 Exam Grading.bat` | `Start CAM2 Exam Grading.command`, which picks the runtime with `uname -m` and clears the quarantine flag after the one-time **Open Anyway** |

Each package ships its libraries pre-installed. The server only listens on
`127.0.0.1`.
