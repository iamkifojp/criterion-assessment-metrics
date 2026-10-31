# Changelog

All notable changes to CAM2 are listed here, newest first. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Dates are
year-month-day.

## [Unreleased]

### Opened from CAM (2026-10-31)

#### Added
- **Host mode** for running CAM2 inside CAM. CAM starts CAM2 with
  `launcher.py --host <handoff.json>`, naming one exam, the folder its session
  lives in (inside CAM's class folder) and the class list. A CAM2 that is
  already running is handed the exam instead (`POST /api/host/handoff`), and
  closes any other session first.
- In host mode CAM2 opens that exam straight away, or starts it on the Step 1
  form with the exam name and save folder fixed (the folder must be empty, and
  the session goes in it, never in a subfolder). CAM's class list replaces the
  upload in Step 3; papers are matched from file names as usual, and each
  entry keeps CAM's `external_id` and its id even if CAM corrects a name. The
  header shows *CAM · <class>*.
- **✓ Grading finished — send to CAM** in Step 5 stamps `host_ready_at` in
  `cam2_session.json` (with a check if anything is ungraded); *Not finished
  after all* clears it. CAM reads the session folder and never writes to it.
  Student PDFs and the gradebook are made exactly as before.
- `engine/host.py`; `POST /api/host/ready`; `/api/state` has `host`. Used on
  its own, CAM2 is unchanged.

### Adjust a box while grading (2026-10-31)

#### Added
- **✎ Adjust this box** in Step 4, beside *See whole page*, for a box drawn
  in the wrong place and only noticed while grading. It opens Step 2 on that
  question and paper. Drag a new box (no "new question or move?" prompt
  here), then **Save & slice Q2 again → back to grading**: only that question
  is cropped again, for every paper, and CAM2 returns to the same question
  and paper. Every grade and comment is kept. **Cancel** puts the box back.
- The config now records which boxes each question's crops were cut from
  (`crops_of`). Moving a box and then back needs no slicing, and sessions
  sliced by an earlier CAM2 pick this up on their next edit.
- `workflow.slice_question`, `workflow.stale_regions`; `POST /api/slice-question`.

### Shuffle papers while grading (2026-10-31)

#### Added
- **Shuffle papers** tick box in Step 4, beside *Hide student names* and
  separate from it, remembered on this computer (`shuffle_papers` in
  `prefs.json`). Papers come in a different order for every question, the
  same each time that question is opened (seeded by session and question).
  With names hidden as well, *Paper 3 of 24* is a different student on each
  question, so no impression of one student builds up across questions. The
  strip numbers, ◀ ▶, "Show ungraded only" and *Go to Q2* all follow the
  shuffled order. Ported from CAM's grading workspace (`examSeededShuffle`).

### Quick comments while grading (2026-10-31)

#### Added
- **Quick comments** on the Step 4 grading card: tick boxes for common
  feedback. Ticking one writes a line at the top of that answer's comment
  (*Areas to develop: check calculations.*); ticking more, or unticking,
  rebuilds that line and keeps anything typed below it. The line is in the
  app's language and appears on the student PDF with the rest of the comment.
- Each exam starts with five *Areas to develop* (illegible handwriting, more
  explanation needed, wrong format, incomplete answer, check calculations;
  the same as CAM's grading workspace). **✎ Edit list** sets the exam's own
  list, one per line, under *Strengths* and *Areas to develop*.
- `engine/keywords.py`; `POST /api/setup/keywords`; `POST /api/grade` takes
  `keywords`. The list is `keywords` in `cam2_session.json`; each grade entry
  keeps its ticked `keywords` and the generated `keyword_text`.

### Choice questions: best N or teacher picks (2026-10-31)

#### Added
- **How an over-answered choice counts.** Each choice in Step 2 has a new
  setting, *If a student answers more than that*: **Count the best N** (the
  default, as before) or **I choose which count**. With the second, a student
  who answered more than N gets an amber **Choice 1: choose which count**
  button under their name in Step 5. It opens a list of the answers they gave
  with their marks or levels; tick the N that count and Save. Until then the
  student is incomplete and the choice adds nothing to the total or average.
  The button then reads *Choice 1: Q2, Q3 count ✎*, so the pick can be
  changed. A student who answered N or fewer is counted as before.
- Student PDFs say *your teacher chose which answers count* beside an answer
  that was not picked, and the gradebook's Questions sheet says *(teacher
  chooses)* for such a choice.
- `grading_summary.set_choice`, `group_pick`; `POST /api/choice`. The choice's
  setting is stored as `pick` (`"best"` or `"teacher"`) and the picks in
  `grades.json` under `overall[<student>]["chosen"][<choice id>]`.
  `student_summary` gains `pending` and `choices`.

### Repository and licence (2026-10-31)

#### Added
- **MIT licence** (`LICENSE`), the same as CAM. The README has a Licence
  section.
- **README status.** A Status section shows every stage with its state
  (Phases 1–4c done, Phase 5 packaging next), says the downloads are not
  available yet and will be on the Releases page, and adds a feature line on
  real-world scans (booklets, page fixes, late papers).
- **`.gitattributes`** keeps line endings consistent between Windows and Mac
  (CRLF for `.bat`/`.cmd`, LF for `.sh`/`.command`) and marks images, PDFs,
  spreadsheets and zips as binary.

### One 5 mm grid and better box-drawing advice (2026-10-31)

#### Changed
- **One grid instead of Normal/Fine.** New sessions use a single grid of
  ~5 mm cells (A4 42 × 60, B5 36 × 51, A3 60 × 84). Teachers drag boxes and
  rarely see cell names, so the coarser grids only added a random 0–14 mm to
  each edge and made boxes of neighbouring questions overlap on dense papers.
  The **Grid: Normal | Fine** switch is gone.
- **Box-drawing advice.** The coach for each question now says to box the
  question together with its answer space, with tips: be generous so
  crossed-out work and answers that run outside the printed box are kept,
  include the question text so it can be seen while grading, use
  **+ Add another box** for question text that sits elsewhere (such as a stem
  shared by parts a, b and c), and overlapping the next question is fine.
  The name-box coach and the "Check on other papers" hint say the same.
- Grid lines on the page are lighter, since there are more of them.

#### Kept
- Sessions made with the Normal or Fine grid open unchanged, with their
  boxes. Step 2C shows *This exam uses the older, coarser grid* and a
  **Switch to the 5 mm grid** button (boxes are cleared after asking).
  Changing paper size or orientation also moves such a session to the new
  grid, since its boxes are cleared anyway.

### Questions assessed on several criteria (2026-10-31)

#### Added
- **One question, several criteria.** In Rubric mode a question can be
  assessed on more than one criterion, as on an MYP science paper where one
  answer is marked on both B and C. The question card in Step 2 has a tick
  box for each criterion ("Which criteria does Q2 assess?") instead of a
  single dropdown.
- **Grading one criterion at a time.** Step 4 lists each question and
  criterion pair as its own item (`Q2 · Criterion B`, `Q2 · Criterion C`).
  Tabs on the grading card switch criterion on the same paper and show the
  level already given for each. The badge over the answer lists every
  criterion's level. *Not answered* applies to all of a question's criteria;
  the comment is shared.
- **Review table and gradebook** have one column per question and criterion,
  with class statistics for each. Each criterion's average uses every level
  given for it, wherever it appears in the exam.
- **Student PDFs** show each criterion's level under its name beside the
  answer, and `Criterion B 6 / 8 · Criterion C 4 / 8` in the result box.

#### Changed
- Questions store `rubric_ids` (a list) instead of `rubric_id`. In Rubric
  mode a grade is stored per criterion in `levels`, so a level stays with its
  criterion when criteria are added to or taken off a question after grading
  has started. Sessions saved earlier still open and keep their grades.
- In a choice group, questions on several criteria are ranked by the sum of
  their levels. A question counts as graded once every criterion has a level.

### Scanning: guide, booklets, page fixes and late papers (2026-10-31)

#### Added
- **"How to scan your papers" guide on the start screen.** It opens by
  itself the first time (no recent sessions) and is one click away after
  that. It reassures teachers that nothing needs setting up before the exam,
  and recommends scanning the whole class in one go, in batches if the feeder
  is too small. It also covers taking staples out, booklets on A3, scanner
  settings, phone scanning apps, late students, and a
  separate answer sheet as the quickest set-up for next time.
- **Several PDFs for one class.** "PDF of the whole class" (now marked
  Recommended) takes one PDF or several batches, joined in the order they
  are added (**＋ Add the next batch**).
- **Photos of each page.** A third source: a folder with one picture per page
  in file-name order, cut into papers like a combined PDF. Phone orientation
  is applied and photos are reduced to about 200 dpi.
- **Folded booklets scanned open.** Step 1 asks how each paper is laid out:
  *Pages in order* or *Folded booklet, scanned open*. For a booklet the
  teacher enters its page count (4, 8, 12 …). CAM2 cuts every scanned side in
  half and puts the pages in reading order (8|1, 2|7, 6|3, 4|5 for 8 pages),
  so Steps 2–5 see ordinary A4 pages. Sideways scans and scanner rotation are
  handled. Two boxes cover copiers that print every front or every back
  upside down, and a third, *Inside sheets first*, for booklets that were
  opened and stacked as they lay instead of being turned over. CAM2 suggests
  the booklet layout when the scans are landscape.
- **Preview of paper 1** in Step 1, exactly as it will be imported, with the
  number of papers. The paper size is guessed from the unfolded pages.
- **Page fixes on the scan check.** Each paper's page viewer has *Move
  earlier / later*, *Turn*, *Remove page* and *Blank page before / after*.
  Papers cut from one stack share it, so removing a double-fed page or adding
  a blank for a missing one moves every later paper back into place, and
  moving a first or last page crosses into the next paper. Booklets get
  *This sheet is upside down* and *This sheet's front and back are swapped*,
  which fix the whole sheet and unfold it again, and *This booklet's sheets
  are in reverse order* for one booklet stacked the other way from the rest.
  Papers with grades or
  comments are never changed. Already-sliced papers are re-sliced at once.
- **Add more papers** (Step 1 check screen, and "Add a late student's paper"
  in Step 5) for a student who sat the exam later, even after grading has
  started. New papers go after the others, keep the class's layout and page
  count as the starting point, and are sliced straight away. Set-up, names
  and grades are kept.
- `tools/make_sample_scans.py` also makes `booklets_A3.pdf` (one sheet
  upside down, one booklet stacked inside sheet first) and `late_student.pdf`.

#### Changed
- Step 1's sources are now *PDF of the whole class*, *One file per student*
  and *Photos of each page*.
- The scan-check advice now points to the page fixes before re-scanning.
- The scanning guide was shortened and rewritten in plainer words. It no
  longer asks for a sheet order in booklets, and no longer names scanning
  apps.

### Pre-packaging review (2026-10-31)

#### Changed
- **New name: CAM2 Exam Grading.** It names the launcher (**Start CAM2 Exam
  Grading**), the download zips (`CAM2-exam-grading-Windows-vX.zip`,
  `CAM2-exam-grading-Mac-vX.zip`) and the start-screen title. Inside the app
  the header and running text keep the short "CAM2". File formats are
  unchanged, so existing session folders open as before.
- **Folders renamed:** new sessions default to
  `Documents/CAM2 Exam Grading Sessions/<Exam name>`, and per-computer data
  (recent sessions, preferences, emergency copies, logs) moves to a
  `CAM2 Exam Grading` app-data folder. The recent-sessions list starts empty
  once; sessions themselves are not moved.
- The Step 1 save-folder hint now says any cloud drive folder works, with a
  small note that cloud folders can take a while to sync.
- The scan check button reads "Looks okay — continue →" instead of "Looks
  right", which could be read as "look to the right".
- `test-folder/` (local test papers) is git-ignored.

#### Added
- **Class-size check for a combined PDF.** Step 1 has an optional "How many
  students?" box beside the pages per student. When it is filled in, CAM2
  compares students × pages with the PDF and says how many pages are missing
  or extra, as you type and again on the scan check page. This catches two
  missing pages, or a missing page plus a double-fed one, which the "doesn't
  divide evenly" warning cannot (`slicer.check_class_size`,
  `scan_warnings.class_size`).

- **Move questions up and down** (Step 2, Draw boxes). The selected question
  in the "So far" list has ↑ ↓ buttons, so a question missed and added later
  can go back into place. Grading, the review table, the student PDFs and the
  gradebook follow the new order. Grades are stored per question, so this is
  safe even after grading has started, and papers don't need slicing again.
  CAM2's own labels (Q1, Q2…) are renumbered to match; typed labels are kept.

- **Hide student names while grading** (Step 4). Remembered on this computer
  (`/api/prefs`, `hide_names` in `prefs.json`). A **👁 Show name** button
  reveals one paper's name when you need to know whose answer it is; it hides
  again on the next paper. Names still show in Step 5 and in reports.
- **Clearer grading navigation:** the ◀ ▶ buttons now read "Previous / Next
  question" and "Previous / Next paper", and the numbered strip is labelled
  "Papers".

- **Question comments in the review table** (Step 5). A grade with a comment
  has a small blue dot; pointing at it shows the comment above "Click to
  change". A one-line legend appears when any comment exists.

#### Fixed
- **No more "fitz API is deprecated" warning** when starting
  `launcher.py`: PyMuPDF is now imported by its current name (`pymupdf`).
- **Step 4, moving to the next question:** "Next question" (and the question
  menu) kept you on the same paper, so finishing paper 8 of Q1 opened paper 8
  of Q2. A new question now starts at paper 1, or at its first ungraded paper
  when "Show ungraded only" is on. The last paper of a question also shows a
  **Go to Q2 →** button in the grading card (or **Next: Review & export →** on
  the last question), so grading can carry straight on.
- **Step 2, Draw boxes:** going back to Draw boxes after "All questions
  added" (for example from Slice papers, to add a missed question) showed an
  empty side panel. "All questions added" removes the empty question that was
  waiting to be drawn, but the panel still pointed at it. It now falls back to
  the last question, so "+ Save … & add question …" is there again.
- **Step 3, typed names:** after typing every name, "Save & start grading"
  still warned that all papers had no name, and the counter stayed at
  "8 paper(s) not matched yet". The count was only worked out when the page
  was drawn, and typed names save without redrawing. It now updates as each
  name is saved, and the button waits for the name typed last to be saved
  before checking.

#### Changed (student PDF reports)
- **No handwritten name crop** in the header; the typed name is enough.
- **Grade beside the answer, not on it.** Each question is one row: label,
  answer image, then the grade to its right, so it never covers the
  student's writing. Rubric mode shows just the level (`6`, not
  `6 / 8 · 5–6`); Marks mode shows `4 / 5`.
- **Rubric printed once** under the result, with every level and descriptor,
  instead of repeating the descriptor under each answer. Under each answer
  there is now only the teacher's comment. Reports are shorter as a result.

### Phase 4 — Review & export (2026-10-30)

#### Added
- **Step 5 review table:** one row per student.
  - Every grade is shown; click it, or an amber "?", to open that paper and
    question in Step 4, which then offers "← Back to review".
  - Marks: the calculated total and % beside an editable **Total on report**.
  - Rubric: each criterion's average beside an editable **final level**.
  - Overrides are highlighted with "adjusted (calculated: …)" and a ↺ reset;
    the calculated value is always kept.
  - Overall comments, and class average / highest / lowest rows.
  - A warning, and a confirmation before export, while any question is ungraded.
- **Student PDF reports** (`engine/reports.py`), in English or Japanese.
  - **Header:** exam, date, student name, the handwritten name crop, the
    total or final levels, a line per question and the overall comment.
  - **Every answer** with its grade badge, the rubric descriptor for the
    level given, and the teacher's comment.
  - Choice questions that didn't count are marked "not counted".
  - Japanese uses the PDF library's built-in font, subset per file, so
    reports are about 100–150 kB each. No font file needs to ship.
  - **Files:** `<Student>_<Exam>.pdf`; duplicate names get " (2)". A paper
    not matched to the class list is `UNMATCHED_<scan>.pdf`.
  - Re-exporting replaces the old reports, and one failed report doesn't
    stop the rest of the class.
- **Excel gradebook** (`engine/gradebook_xlsx.py`), with sheet names and
  headings in the report language.
  - **Sheet 1:** grades and comments per question, calculated and reported
    results with an "adjusted" flag, overall comment, "all graded", and
    class statistics.
  - **Sheet 2:** questions, boxes, marks or rubric, choice groups, and the
    full rubric text.
  - A gradebook left open in Excel gives a clear message.
- **Routes:** `POST /api/overall`, `POST /api/export` (a background job)
  and `POST /api/open-folder` (Explorer or Finder). The browser now also
  receives the class summary.
- About 70 new strings in both languages, and 9 new tests (146 in total).

#### Changed
- Reports use PyMuPDF's built-in Japanese font instead of shipping Noto
  Sans JP; testing showed it renders correctly.
- `UNMATCHED_` is used only when a class list is in use. Without one, scans
  named after students keep their names.
- Report totals and final levels typed as text ("21") are accepted;
  negative or non-numbers are rejected.
- The "coming soon" placeholder screen is gone, since all five steps now exist.

#### Fixed (found while checking the reports)
- Question labels and results overprinted each other in the report header,
  because PyMuPDF ignores table column widths; the header now uses plain lines.
- A marks exam's gradebook listed a rubric left over from when the exam was
  briefly in rubric mode.

### Phase 3 — Grading (2026-10-30)

#### Added
- **Step 4 grading screen**, grading one question across every paper.
  - **Navigation:** question selector with ◀ ▶, "N of M papers graded"
    progress, a numbered paper strip (graded papers in green) and paper ◀ ▶.
  - **Show ungraded only** is on when resuming a session that already has grades.
  - **The answer:** mouse-wheel zoom, drag to move around, − / Fit / +.
    The next paper's answer is loaded in advance.
  - **Grade badge** over the answer: `4 / 5`, `6 / 8 · 5–6` or `— Not answered`.
    The frame and paper chip turn green once graded. The crop files are never changed.
  - **🔍 See whole page:** the full page with the question's box outlined in
    red, with page arrows. You can keep grading from it, and it stays on as
    you move between papers.
  - **Grading card**
    - Large mark buttons, or a number box with − / + above 15 marks.
    - In rubric mode, every band with its descriptor and a button for each level.
    - Not answered, Clear grade, and a comment that saves as you type.
    - **Next paper →** (keyboard focus moves to it after a grade) and an
      "All papers graded for Q1 → Go to Q2" card.
- `POST /api/grade` and `POST /api/position`. The browser now receives
  grades and progress with the session.
- Once any paper has a grade, the exam can no longer switch between marks
  and rubric.
- `sliced_at` stamp on slicing; images with it may be kept by the browser,
  so the screen doesn't flicker after each click.
- `tests/test_ui_syntax.py` parses every browser module with Node.js.
- 7 new tests (137 in total): grading, comments, progress, persistence after
  reopening, the resume position, the mode lock, rubric level checks, and a
  failed save while grading.

#### Fixed (found by grading the sample papers in a browser)
- A syntax error in the new grading module stopped the whole app loading.
  The new syntax test now catches this.
- The answer picture flickered or vanished after every click, because images
  were never kept by the browser.
- Papers from a combined PDF were all named "combined"; they are now
  "combined.pdf · 1", "· 2", …
- The rubric bands scrolled in a small inner box; now the whole grading card
  scrolls, and the bands are more compact.
- The grade badge overlapped the whole-page hint.
- `debounce().flush()` re-sent a save even when nothing was waiting (each
  blur of the comment box saved again). `.flush()` now runs only pending
  work, and `.now()` saves at once.

### Phase 2 — The app: start screen and Steps 1–3 (2026-10-30)

#### Added
- **`launcher.py`**: starts CAM2 on `127.0.0.1` and opens the browser.
  - If CAM2 is already running, it opens that one instead of starting another.
  - It stops 10 minutes after the last CAM2 tab closes, or on **Quit**.
  - Developer option `--data-dir` keeps test data away from the real app
    data and Documents folders.
- **`app.py`** (JSON routes), **`appstate.py`** (the open session and
  background jobs) and **`engine/workflow.py`** (Steps 1–3 as testable
  operations).
- **Start screen**
  - Recent sessions showing step, progress and when they were last saved.
    A missing folder gets plain advice.
  - **Open a session folder…**, **Start a new session** and **Quit**.
  - An "open on another computer?" question, and an offer to restore newer
    work from this computer's emergency copy.
- **Step 1**
  - Exam name and scans (a folder, or a combined PDF split by pages per
    student). There's also a paste-a-path option for when the file picker
    is awkward.
  - Paper size pre-selected from the scans, with a landscape option.
  - A save folder that defaults to `Documents/CAM2 Sessions/<exam>`.
  - A progress bar while scans are copied in.
  - A thumbnail check with page-count and leftover-page warnings, a viewer
    for all of a paper's pages, and **Choose different scans**.
- **Step 2**
  - **Marks or rubric.**
  - **Rubric builder:** editable levels, add or remove rows and criteria,
    inline overlap messages, Excel/CSV upload and a blank template download.
  - **Box drawing**
    - Drag rectangles that snap to the Normal or Fine grid; optional grid
      labels; choice of which paper to draw on.
    - Paper size and grid can be changed (boxes are cleared after asking).
    - Several boxes per question, across pages ("+ Add another box").
    - Typed ranges as a fallback.
    - The cursor jumps straight to "How many marks?".
    - **Check on other papers** shows the box on three other students' papers.
  - **Choice questions** ("answer N of M").
  - **Slicing**, with a progress bar and a list of any papers that failed.
- **Step 3**
  - Class list upload with a column picker (pre-selected, family and given
    names in click order), pasted names, or typed names.
  - Automatic matching from file names.
  - A type-to-search name box that shows names already used on other papers.
  - An unmatched-papers count and confirmation.
- **Header:** step bar, "Saved ✓ time", **💾 Save**, **Save & close
  session** and the English / 日本語 switch.
  - A red banner whenever a save fails, with **Save** to retry, or **Reopen**
    if another computer changed the session.
  - Every screen is translated (about 230 new strings, in English and Japanese).
- **`tools/make_sample_scans.py`**: fake papers, a combined PDF and a class
  list for trying CAM2 out.
- **33 new tests** (130 in total), including the whole Steps 1–3 flow through
  the server. A new test checks that every key the UI uses exists in both
  languages.

#### Fixed (found by clicking through in a browser)
- Dialog buttons reported "cancelled" whichever button was clicked, so
  confirmations such as "Open it here anyway" and "Delete question" did
  nothing.
- A lock left behind by a crash or forced stop on the same computer warned
  "open on another computer". Locks from this computer are now treated as stale.
- Drawing a box somewhere else while still on the name box (or a question)
  silently replaced that box. CAM2 now asks: "A new question, or move the box?"
- An error with a `{language}` placeholder crashed the error handler.
- The step bar made the header very tall on narrower screens; it now sits on
  its own row.
- After an upgrade the browser could have kept running old scripts; app
  files are now always checked for changes.

### Phase 1 — Engine and tests (2026-10-30)

#### Added
- **`engine/slicer.py`**
  - A4, B5 and A3 paper, each with a Normal (~1.4 cm) and a Fine (~1 cm) grid.
    These are CAM's "compact" and "fine" grids.
  - Landscape pages turn the grid to match.
  - Paper size is detected from the PDF's page size. Both B5 sizes (ISO and
    Japanese JIS) count as B5.
  - Ranges such as `page2!A4:J10`; full-width input (`Ａ４：Ｊ１０`) is accepted.
  - Dragged boxes snap to whole grid cells.
  - **One question can use several boxes**, even on different pages. They are
    stacked into one image with a thin divider.
  - Scans are copied into the session folder with safe, unique file names.
  - A combined photocopier PDF can be split, with a warning when the pages
    don't divide evenly.
  - Papers whose page count differs from the rest of the class are flagged.
  - Page previews with question boxes outlined (for "See whole page"), crop
    previews and page-1 thumbnails.
  - Hidden files, including macOS `._` files on USB sticks, are ignored.
- **`engine/storage.py`**: session folders with CAM's save-safety rules.
  - Verified atomic writes, retried while a sync program briefly holds the file.
  - An emergency copy on this computer, written before every save.
  - A "changed on another computer" check, using a session id, a save counter
    and a content hash.
  - Detection of OneDrive, Google Drive, Dropbox and iCloud conflict copies.
  - A wipe guard against saves that would remove most of the grades.
  - Daily backups, keeping the newest 14.
  - An advisory "open on another computer" lock.
  - A recent-sessions list and preferences in the per-user app-data folder.
- **`engine/rubrics.py`**: teacher-made rubrics.
  - Default rows 0, 1–2, 3–4, 5–6, 7–8, all editable.
  - Levels such as `3`, `5–6` or `５～６`; overlapping levels are rejected.
  - Import from Excel or CSV (English or Japanese headers), and a blank
    template in English or Japanese.
- **`engine/roster.py`** and **`engine/tables.py`**: class lists.
  - Reads `.xlsx` and `.csv` (UTF-8 or Shift-JIS); a clear message for old `.xls` files.
  - Pre-selects the header row and the name column(s); family and given name
    columns can be joined.
  - Pasted names.
  - Careful auto-matching of file names to students, which copes with
    Japanese names saved on a Mac.
- **`engine/grading_summary.py`**: recording grades and working out results.
  - Marks and levels are checked when recorded; *Not answered* is supported.
  - Choice questions ("answer N of M"): the best N count.
  - Marks totals and percentages.
  - Rubric averages per criterion; the suggested final level is the average
    **rounded half up**.
  - A report-only total and final-level override that keeps the calculated value.
  - Class average, maximum and minimum, and progress counts.
- **`engine/i18n.py`**, `i18n/en.json`, `i18n/ja.json`: English and Japanese
  text, and translated error messages.
- **`engine/pickers.py`**: native folder and PDF pickers for Windows (ported
  from CAM) and macOS (new).
- **`engine/errors.py`**: `UserError` with translatable codes.
- **`engine/model.py`**: the formats of `cam2_session.json` and `grades.json`.
- **97 unit tests** (`python -m unittest discover -s tests -t .`), including
  tests ported from CAM's grid, choice-section, cloud-safety and folder-dialog
  tests.
- `README.md`, `ARCHITECTURE.md`, this changelog, `requirements.txt`, and a
  `.gitignore` that keeps student data out of the repository.

#### Changed compared with CAM
- CAM's old ~2 cm "legacy" grid is dropped.
- The Word (`.docx`) unit-plan parser and `python-docx` are dropped.
- The built-in Arts Criterion D rubric text is dropped; teachers bring their own.
- Crops are stored by question id and student id
  (`crops/q1/s001.png`), not by label and file name.
