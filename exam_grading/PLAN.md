# CAM2 — Standalone Exam Slicing & Grading App (Implementation Plan)

> **Working Directory:** `C:\Project\cam2-exam-grading` (GitHub: `iamkifojp/cam2-exam-grading`)
> **Forked From:** `C:\Project\criterion-assessment-metrics-public` — grid maths and slicing (`cam_grading_workspace/exam_engine.py`), the save-safety layer (`engine/persistence.py`), the native folder picker (`engine/folder_dialog.py`) and the portable bundle builder (`tools/build_windows_bundle.py`).
> **Status:** v7. Revised after a review. Adds Windows and Mac packages, A4/B5/A3 paper sizes with a 5 mm grid, a "see whole page" viewer, answer boxes that span several pages, choice questions ("answer 2 of 3"), rubric levels you can set yourself, report-only totals, a fully bilingual app (EN/日本語) and CAM's save-safety checks.

---

## 1. Goal

A teacher who has never seen CAM2 can grade a stack of scanned exams:
- **Nothing to install.** Download one zip (Windows or Mac), unzip it, double-click **Start CAM2 Exam Grading**.
- **One step at a time.** Five guided steps. Each step shows one plain-language instruction at the top and hides everything else.
- **Stop and come back.** Every grade is saved as it is given. Next time, the start screen offers **Continue** and puts the teacher back on the same question and student.
- **English or Japanese.** The whole app and the student reports can be switched between EN and 日本語.

```
 Start screen:  ▶ Continue a session  |  ✨ Start a new session
                                   │
 ① Exam & scans ─▶ ② Set up questions ─▶ ③ Match names ─▶ ④ Grade ─▶ ⑤ Review & export
   name, paper size,   marks or rubric,      name crops +       overlay,      totals/averages,
   save folder,        drag boxes, choice    class list         whole-page    student PDFs +
   thumbnails check    questions                                viewer        Excel gradebook
```

---

## 2. Teacher Flow

### Start Screen
- **Language switch** (English / 日本語) in the top corner. It is remembered on this computer.
- **▶ Continue a previous session:** a list of up to 10 recent sessions, each showing the exam name, the folder, when it was last saved and its progress (e.g. *"Grading · 14 / 24 students"*). One click opens it at the exact step, question and student. If the folder can't be found (USB unplugged, OneDrive not synced yet), the card says so plainly and offers **Browse…**.
- **📂 Open a session folder…:** a native folder picker for any folder that contains `cam2_session.json`.
- **✨ Start a new session** goes to Step ①.
- **📖 How to scan your papers:** a short guide, open by itself the first time (no recent sessions) and one click away after that. The message is that **no preparation is needed in CAM2**: give the exam as usual and scan the papers to PDF. Its points:
  - **Scan the whole class in one go** through the document feeder. CAM2 cuts it into each student's paper, which saves time at the copier. Papers don't need to be in class-list order.
  - **Too many sheets for the feeder** (usually 50–100)? Scan in batches; CAM2 joins the PDFs.
  - **Take staples out** rather than scanning page by page on the glass.
  - **Booklets printed on A3** (as IB papers are): unstaple, keep each student's sheets together, and scan the whole class at A3, 2-sided. CAM2 unfolds them. Don't cut along the fold. The copier's own booklet-scan mode isn't needed, and the guide doesn't ask for a sheet order: Step ① handles booklets stacked either way.
  - **Sheets upside down or in the wrong order** can be fixed in CAM2.
  - **Scanner settings:** PDF, 200–300 dpi, 2-sided when printed on both sides. Greyscale scans are clearer.
  - **Using photos:** use a scanning app on the phone; it straightens each page.
  - **Late students** can be added at any time.
  - **Quickest set-up for next time:** question booklets plus separate answer sheets; scan only the answer sheets.
  - The guide is kept short and plain: one or two sentences per point, no product names.

### Step ① Exam, Scans & Save Folder
Everything that decides where files live is settled here, before anything is written.
1. **Exam name:** e.g. `Y8 Science Midterm`. It is used for the session folder, the recent list, report headers and file names.
2. **Where are the scans?**
   - **📄 PDF of the whole class** *(recommended)*: one PDF from the photocopier, or several batches joined in the order they are added (**＋ Add the next batch**). It asks *"How many pages is one student's paper?"* and cuts the stack into papers. An optional *"How many students?"* box cross-checks the page count, because two missing pages (or one missing and one double-fed) still divide evenly.
   - **📁 One file per student:** a folder with one PDF or picture per student.
   - **📷 Photos of each page:** a folder with one picture per page, in file-name order, cut into papers like the PDF of the whole class.
   - **How is each paper laid out?**
     - **Pages in order:** loose or stapled sheets, or answer sheets.
     - **Folded booklet, scanned open:** each scanned page holds two booklet pages side by side. The teacher gives the booklet's page count (4, 8, 12 …), and CAM2 cuts every side in half and puts the pages in reading order (for 8 pages the sides hold 8|1, 2|7, 6|3, 4|5). Two boxes fix copiers that turn every front or every back upside down. A third, *Inside sheets first*, is for booklets that were opened, unstapled and stacked as they lay, so each one's inside sheet came first, inner face up (the sides are then read backwards). When the scans are landscape, CAM2 suggests this layout.
   - **Preview:** paper 1 appears exactly as it will be imported, with the number of papers, so a wrong page count or upside-down backs show before anything is copied.
3. **Paper size:** three big buttons, **A4 / B5 / A3**, pre-selected from the PDF's page size (for a booklet, from the unfolded page). The teacher confirms.
   - B5 matches both the ISO size (176×250 mm) and the Japanese JIS size (182×257 mm).
   - Landscape pages, such as a folded A3 sheet scanned flat, get the grid turned to match.
4. **Where should this grading session be saved?** A native folder picker. The default is `Documents/CAM2 Exam Grading Sessions/<Exam name>`. CAM2 checks that the folder can be written to before continuing. If the chosen folder already has other files in it, CAM2 makes an `<Exam name>` folder inside it rather than scattering files.
   - **Create session & bring in the scans →** creates the session and copies the scans in (step 6 below happens here, with a progress bar), then shows the check screen.
5. **Check the scans (thumbnails):** a grid showing page 1 of every student, numbered.
   - **Folder of scans:** any paper with a different page count from the rest of the class is highlighted in amber.
   - **Combined PDF:** a warning appears if the total page count doesn't divide evenly by the pages per student, or, when the class size is given, if it isn't students × pages (saying how many pages are missing or extra). The thumbnails make a missed or double-fed page easy to spot, because from that student on, page 1 no longer looks like a cover page. Clicking a thumbnail shows all of that student's pages, with tools to fix them:
     - **Pages in order:** *Move earlier / later*, *Turn* (a quarter turn), *Remove page* (a double-fed or empty page) and *Blank page before / after* (for a missing page). Papers cut from one stack share it, so removing or adding a page moves every later paper back into place, and moving a first or last page crosses into the neighbouring paper.
     - **Booklets:** *This sheet is upside down* and *This sheet's front and back are swapped* fix the whole sheet and unfold it again (an upside-down sheet also swaps its left and right halves, so turning single pages would not be enough). *This booklet's sheets are in reverse order* fixes one booklet that was stacked the other way from the rest, so nobody has to re-scan.
     - A paper with grades or comments can't be changed. If the papers are already sliced, the changed ones are sliced again at once.
     - Re-scanning from the first wrong paper is still offered.
6. **Copying the scans** puts them into the session folder under `scans/`, or saves the split PDFs there. This makes the session complete in itself: it can be moved to another computer, and the whole-page viewer always works. From the check screen the teacher continues with **Looks right — continue →**, or chooses **Choose different scans**, which replaces them.
7. **＋ Add more papers** (also **Add a late student's paper** in Step ⑤): for a student who sat the exam later. It can be used at any time, even after grading has started. New papers go after the others and start from the class's layout and page count. If the class is sliced, the new papers are sliced at once, so they can be graded straight away. Set-up, names and grades are kept. Page fixes on late papers never reach into the class's stack.

### Step ② Set Up the Questions (on the first student's paper)

**2A — How will you grade this exam?** Two big cards:
- **🔢 Marks:** each question is worth points; totals add up automatically.
- **📋 Rubric:** each question gets a level from a rubric, for example 0–8.

**2B — Rubric (only in Rubric mode).** CAM2 ships **no built-in rubrics**. The teacher either types or pastes their own, or uploads an Excel file.
- **Type or paste:** one card per criterion or rubric, with a *Criterion name* box (e.g. `Criterion A` or `基準A`).
  - The card starts with five rows, `0`, `1–2`, `3–4`, `5–6` and `7–8`, each with a **Levels** box and a **Descriptor** box. All of it can be edited, and rows can be added or removed, so a teacher can use `1`, `2`, `3`, `4`, or `0–8` as single numbers, or any bands they like.
  - A **Levels** entry must be one number (`3`) or a range (`5-6`, `5–6`, `5〜6`; full-width digits are accepted). The highest number becomes that rubric's maximum, so a rubric can run 0–8, 0–4 or whatever the teacher needs.
  - **+ Add another criterion** if different questions use different rubrics. An MYP exam usually assesses several criteria on one paper.
- **Upload Excel / CSV**, with a **📥 Download blank template** button. The template has the columns `Criterion | Levels | Descriptor`.

**2C — Draw the boxes.** The first student's page appears with a grid on it. There is one grid of ≈5 mm cells; boxes are dragged, so the cell size only decides how closely a box can follow the paper:

| Paper | Grid (≈5 mm cells) |
|---|---|
| A4 | 42 × 60 (A1–AP60) |
| B5 | 36 × 51 (A1–AJ51) |
| A3 | 60 × 84 (A1–BH84) |

*(Earlier versions offered CAM's "compact" (≈1.4 cm) and "fine" (≈1 cm) grids. Sessions made with them still open, and offer **Switch to the 5 mm grid**.)*

The teacher **drags a rectangle** over the page, and it snaps to the grid cells. Cell labels are hidden unless **Show grid labels** is ticked; typing a range such as `A4:J10` is still possible in a small "advanced" box. The coach prompt walks through, in order:
1. *"Drag a box around where students write their **name** (page 1). Leave space around it — names often run past the line."* A **Skip — no name box** option is available.
2. *"Drag a box around **Q1**: the question and its whole answer space."* Under it, four short tips:
   - Be generous: leave room on every side for crossed-out work and answers that run outside the printed box. (Scans also sit a few mm differently.)
   - Include the question text, so it can be seen while grading.
   - Question text somewhere else, such as one stem for parts a, b and c? Box it first, then **+ Add another box** for the answer.
   - Boxes may overlap the next question; that's fine.
   - Use **‹ Page 1 / Page 2 ›** to move between pages.
   - **+ Add another box** for an answer that continues on another page or in another area. The boxes are stacked top-to-bottom into one image, with a thin divider line between them.
   - The **question card** beside the page shows:
     - **Label:** `Q1`, editable.
     - **Marks mode:** *"How many marks is Q1 worth?"* The cursor is already in this box.
     - **Rubric mode:** *"Which criteria does Q1 assess?"*, a tick box per criterion. Ticked already when there is only one. One question can be assessed on several criteria (e.g. B and C) and then gets a level for each.
   - **Check on other papers:** a strip showing this box cropped from three other students' papers, so a box that is too tight is obvious right away.
   - **+ Save Q1 & add Question 2** or **✓ All questions added**.
   - **Forgot to press "next"?** If a box is drawn somewhere that doesn't overlap the current item's box on that page, CAM2 asks *"A new question, or move the box?"*. This was added after browser testing showed how easily a box got replaced by mistake.
   - **Question order:** the selected question in the *So far* list has **↑ ↓** buttons. A question missed and added later can be moved back into place. Grading, the review table, the student PDFs and the gradebook all follow this order. Grades are stored per question, not per position, so moving is safe at any time, even after grading, and does not need re-slicing. Labels that are all CAM2's own (`Q1`, `Q2`…) are renumbered to match; if any label was typed by the teacher, labels are left alone.

**2D — Choice questions (optional).** *"Do students choose which questions to answer (e.g. answer 2 of 3)?"* The answer defaults to **No**. **Yes** lets the teacher tick the questions in the group and enter how many students must answer. Several groups are allowed. Each group also says what happens when a student answers more than that: **Count the best N** (default) or **I choose which count**, which puts an amber **choose which count** button under that student's name in Step ⑤.

**2E — Slice.** **Slice all papers →** shows a progress bar. Crops are saved into the session folder.

### Step ③ Match Student Names
- **Class list (optional):** upload `.xlsx` or `.csv`, or paste names one per line.
  - After an upload, CAM2 shows the first 5 rows and asks *"Click the column with the names"*. Two columns can be clicked for family and given name, and a *"First row is a header"* tick box is pre-guessed.
  - CSV files are read as UTF-8 or Shift-JIS (Excel's Japanese default).
  - Old `.xls` files get a plain message: *"Please save as .xlsx"*.
- **Matcher:** one row per paper, with the **handwritten name crop** beside a type-to-search name box.
  - Names already used are greyed out.
  - Names found in file names are matched automatically. Comparison ignores spaces, case and full-/half-width differences, and copes with how macOS stores Japanese file names.
  - With no class list, the teacher simply types the names.
  - Unmatched papers are allowed and keep their scan file name.
  - There is no "papers are in class-list order" shortcut: papers are often collected out of order, and the grading teacher may not have invigilated.
- **Save & start grading →**

### Step ④ Grade
- **Top bar:**
  - **◀ Question 1 of 8 ▶** and a student switcher.
  - Progress, e.g. **18 / 24 graded**.
  - A **Show ungraded only** toggle, on by default when resuming.
  - A **Hide student names** toggle for anonymous grading, remembered on this computer. While it is on, each paper has a **👁 Show name** button that reveals only that paper's name; the name is hidden again on the next paper.
  - A separate **Shuffle papers** toggle, also remembered: a different paper order for each question (stable when the question is reopened). With names hidden too, a paper's number is a different student on each question.
  - Navigation buttons say what they do (**◀ Previous question / Next question ▶**, **◀ Previous paper / Next paper ▶**), and the numbered strip is labelled **Papers**.
  - **💾 Save** with *"Saved ✓ 15:42"* beside it.
  - **Save & close session**, which returns to the start screen.
- **Left: the answer image** for this student and question, with mouse-wheel zoom.
  - **Grade overlay:** once a grade is given, a bold badge sits over the top-right corner of the image and the card border turns green. The badge shows `4 / 5` in Marks mode, `6 / 8 · 5–6` in Rubric mode, or `—` for *Not answered*. For a question on several criteria it lists each one (`Criterion B: 6 / 8 · 5–6`, `Criterion C: —`). The overlay is drawn on screen only; the crop files are never changed.
  - **🔍 See whole page:** opens the student's full page with this question's box outlined, with page arrows. The grading card stays usable, so a badly cropped answer can be graded straight from the full page.
- **Right: the grading card** has three controls and nothing else:
  1. **Grade:**
     - **Marks mode:** big buttons `0 … max`. For maximums above 15, a number box with **–** and **+** buttons instead.
     - **Rubric mode:** one card per band showing its descriptor. Inside each card is a button for every level in that band; for example, the `5–6` card has `[5]` and `[6]`.
     - **A question on several criteria** is graded one criterion at a time: the question list has `Q2 · Criterion B` and `Q2 · Criterion C` as separate items, so the teacher grades B across the class and then C. Tabs at the top of the card switch criterion on the same paper and show each criterion's level. *Not answered* applies to every criterion of the question, and the comment is shared.
  2. **Not answered:** counts as 0, except in a choice group, where the question is left out (see §3).
  3. **Comment (optional):** one text box, with **quick comments** above it: tick boxes for common feedback (*Strengths* and *Areas to develop*) that write one generated line at the top of the comment and keep the teacher's own text. **✎ Edit list** sets the exam's list.
- **No keyboard shortcuts.**
- **Moving on:** **Next paper →** sits under the comment box. After a grade,
  keyboard focus moves to it, but CAM2 doesn't move on by itself, so there's
  still time to add a comment. When every paper has a grade for a question,
  the card offers **Go to Q2 →**.
- **Marks or rubric is fixed** once any paper has a grade.
- **Next: Review & export →**

### Step ⑤ Review & Export
**Review table**, one row per student. Any ungraded cell is amber; clicking it jumps back to grading.
- **Marks:** `Name | Q1 | Q2 | … | Calculated total (34 / 40 · 85%) | Total on report | Overall comment`
- **Rubric:** `Name | Q1 | Q2 | … | Average (5.7) | Final level (editable, pre-filled 6) | Overall comment`
  - With more than one criterion, the table has an **Average** and **Final** pair per criterion.
  - A question on several criteria has one column per criterion (`Q2 / Criterion B`, `Q2 / Criterion C`).
- Editing a **question** cell changes that grade, exactly as in Step ④.
- **Total on report** and **Final level** start as the calculated values. If the teacher changes one, the change appears **only on the student PDF**, and the cell is marked "adjusted". CAM2 always keeps the calculated value as well, and both are stored in the Excel gradebook.

**Export:**
- **Report language:** English or 日本語. The default is the app's language.
- **📄 One PDF per student** goes into `reports/student_pdfs/`.
  - **Header:** exam name, date, student name, and the total (`34 / 40`) or final level(s), with one line per question and the overall comment. No handwritten name crop.
  - **Rubric (Rubric mode):** each rubric's levels and descriptors, printed **once** under the header, so students can look up their level themselves instead of the same descriptor repeating under every answer.
  - **Body:** one row per question: the label, the answer image, and the grade **beside** it (never over the student's writing). Rubric mode shows just the level (`6`); Marks mode shows `4 / 5`. Below the row, only the teacher's comment.
  - **File name:** `<Student Name>_<Exam Name>.pdf`, so the teacher can see at once who to send it to.
    - Characters that file names can't contain are replaced.
    - A duplicate name gets ` (2)`.
    - When a class list is in use, papers not matched to it are named `UNMATCHED_<scan file name>.pdf`, so they're never sent to the wrong person. Without a class list, the paper's own name is used, because scans are often already named after students.
- **📊 Master Excel gradebook** `reports/<Exam Name>_Master_Grades.xlsx`:
  - **Sheet 1, Grades & Comments:**
    - Frozen header, wrapped comments.
    - Per question: grade and comment (a question on several criteria has a grade column per criterion, `Q2 · Criterion B`). Then the calculated total or average, the reported total or final level (with an "adjusted" flag) and the overall comment.
    - Class average, maximum and minimum rows at the bottom.
  - **Sheet 2, Questions & Rubrics:** each question's maximum, its choice groups, and every rubric with its levels and descriptors.

---

## 3. Calculations

| Item | Rule |
|---|---|
| Marks: question score | A whole number from 0 to the question's maximum. *Not answered* = 0. |
| Marks: choice group "answer N of M" | N scores count. The group's maximum is the sum of the N largest question maximums. A student who answers more than N gets the best N, or, when the choice is set to **I choose which count**, the N the teacher ticks in Step ⑤ (until then the choice counts nothing and the student is incomplete). |
| Marks: total | Ordinary questions plus each choice group's contribution. Percentage to 1 decimal place. |
| Rubric: criterion average | Average of every level given for that criterion, including from questions assessed on several criteria. *Not answered* = 0, but in a choice group only the best N count (questions on several criteria rank by the sum of their levels). Shown to 1 decimal place. |
| Rubric: suggested final | Average **rounded half up**, so 4.5 → 5 and 5.5 → 6. Python's `round()` must not be used, because it rounds halves to even (`round(4.5) == 4`). |
| Ungraded question | Not counted. The student is flagged *incomplete* in Step ⑤ and in Excel. |
| Report override | Changes only the student PDF. The calculated value is kept and exported alongside it. |

---

## 4. Saving & Safety

The session folder may live on a local disk, a USB stick, or any synced cloud folder (OneDrive, Google Drive, iCloud Drive, Dropbox). These rules are ported from CAM's `engine/persistence.py` and its tests.
- **Every grade, comment and position change saves at once**, using the same write as **💾 Save**:
  - **Safe write:** the data goes to a temporary file first, is flushed to disk, then renamed over `grades.json`. The file is read back afterwards to confirm it was written correctly.
  - **Retry:** a brief lock by a sync program (OneDrive, Google Drive) is retried for a few seconds before it counts as a failure.
- **A failed save is never hidden.** If the folder disappears (USB pulled out) or the write fails, a red banner stays up: *"Not saved — your work is kept safe on this computer. Reconnect the folder and click Save."*
  - Every save also writes an **emergency copy** to the app's own data folder on this computer. Nothing is lost while the session folder is away.
  - "Saved ✓" is only shown after the read-back check passes.
- **Opened on two computers:** `grades.json` carries a session ID and a save counter, and CAM2 remembers the counter it loaded. If another computer has saved since, CAM2 stops and asks the teacher instead of overwriting.
  - A `cam2.lock` file (computer name and time, refreshed while the session is open) gives an early warning: *"This session looks open on LAPTOP-123."*
- **Cloud conflict copies:** files such as `grades-LAPTOP.json` (OneDrive), `grades (1).json` (Google Drive) and `grades (conflicted copy).json` are detected, and the teacher is told before any save.
- **Wipe guard:** a save that would remove most existing grades is refused unless the teacher confirms it.
- **Daily backups:** `backups/grades.json.bak-YYYYMMDD` is written inside the session folder, and the last 14 are kept.
- **Paths inside the session are relative**, so a moved or copied session folder still opens.
- **Recent-sessions list** lives in the app data folder: `%LOCALAPPDATA%\CAM2 Exam Grading\` on Windows and `~/Library/Application Support/CAM2 Exam Grading/` on Mac. It is never in the app folder, so it survives a new version being unzipped.

---

## 5. Packaging: No Install, Windows & Mac

The app is a small local web server (Flask) plus the teacher's browser, so the same code runs on both systems. Each package carries its own private Python, so nothing has to be installed.

| | **Windows** `CAM2-exam-grading-Windows-vX.zip` | **Mac** `CAM2-exam-grading-Mac-vX.zip` |
|---|---|---|
| Python | python.org's "embeddable" Python, the same version as CAM (3.14.x). The builder is ported from `tools/build_windows_bundle.py`. | `python-build-standalone`, the same version. **Both Apple Silicon and Intel runtimes are inside one zip**; the launcher picks the right one, so the teacher never has to know which Mac they have. |
| Libraries | Flask, Pillow, PyMuPDF and openpyxl, pre-installed into the bundle by the builder. | The same. The builder can fetch the Mac wheels from Windows with `pip --platform … --only-binary=:all:`, but it **must be tested on a real Mac**. |
| Start | `Start CAM2 Exam Grading.bat`: starts the server hidden and opens the browser. `Start CAM2 Exam Grading (troubleshooting).bat` shows the log. | `Start CAM2 Exam Grading.command`: opens a small Terminal window ("CAM2 is running. Close this window to quit."). |
| First-run warnings | Windows may show *"Open File – Security Warning"* for files from a downloaded zip. The READ ME says to click **Run**, or right-click the zip → Properties → **Unblock** before extracting. | The package is unsigned (decided, see §8), so macOS blocks it at first. The teacher approves it **once** in System Settings → Privacy & Security → **Open Anyway**. The launcher then clears the download flag from the rest of the folder (`xattr -dr com.apple.quarantine`), so there is only one approval. macOS will also ask once to allow access to Documents/Desktop. |
| File & folder pickers | Native picker, ported from `engine/folder_dialog.py` and extended to pick a single PDF. | `osascript` (`choose folder` / `choose file of type pdf`). |

**Both systems:**
- The server listens on `127.0.0.1` only, so nothing is visible on the school network.
- Starting CAM2 a second time just opens the browser on the one already running.
- A **Quit CAM2** button is on the start screen. The server also shuts itself down 10 minutes after the last CAM2 tab closes; open tabs send a heartbeat every minute.
- Each zip contains `READ ME FIRST` (EN and JA) and a one-page quick guide PDF.
- Small Excel and CSV files (class list, rubric) are chosen through the browser's own upload button. Native pickers are used only for folders and the combined PDF.

**Japanese text in PDFs:** reports use the Japanese font built into PyMuPDF (Droid Sans Fallback), so they look the same on every computer with no font file to ship. The earlier plan to bundle Noto Sans JP was dropped in Phase 4 after testing showed the built-in font renders Japanese correctly. Reports are laid out with PyMuPDF's `insert_htmlbox`, which handles line wrapping. Fonts are subset, which takes a Japanese report from 3.6 MB to tens of kB, and answer images are embedded as JPEG, so each student PDF (about 100–150 kB) is small enough to email.

---

## 6. Code & Folder Structure

### App code
```text
cam2-exam-grading\
├── PLAN.md
├── README.md
├── requirements.txt            # Flask, Pillow, PyMuPDF, openpyxl  (no python-docx)
├── app.py                      # Flask server & REST API
├── appstate.py                 # the open session + background jobs (import, slicing)
├── launcher.py                 # single-instance check, free port, open browser, idle shutdown
├── engine\
│   ├── workflow.py             # Steps 1–3 as testable operations (import, set-up, slice, names)
│   ├── slicer.py               # paper detection, the 5 mm grid, multi-box crops, PDF split, thumbnails
│   ├── pages.py                # joined PDFs, page photos, booklet unfolding, page fixes, paper-1 preview
│   ├── pickers.py              # native folder/PDF pickers: Windows (from folder_dialog.py) + macOS (osascript)
│   ├── storage.py              # session folder, safe save, conflicts, lock, backups, recent list (from persistence.py)
│   ├── rubrics.py              # teacher rubrics: level parsing, Excel import, blank template
│   ├── roster.py               # class list import (xlsx/csv/paste, column picker) & name matching
│   ├── grading_summary.py      # totals, choice groups, averages, round-half-up, report overrides
│   ├── reports.py              # per-student PDFs (PyMuPDF, built-in CJK font, subset)
│   ├── gradebook_xlsx.py       # Master Excel gradebook (openpyxl)
│   ├── i18n.py                 # loads i18n/en.json, i18n/ja.json
│   ├── model.py                # shapes of cam2_session.json / grades.json
│   ├── tables.py               # reads .xlsx / .csv (UTF-8 or Shift-JIS) into rows
│   └── errors.py               # UserError with translatable codes
├── i18n\                       # every UI and report string, EN and JA
├── static\  templates\         # single-page wizard UI
├── tests\
└── tools\
    ├── build_windows.py        # ported from build_windows_bundle.py
    ├── build_mac.py
    └── make_sample_scans.py    # fake papers + class list for trying CAM2 out
```

### Session folder (chosen by the teacher in Step ①)
```text
<Session folder>\
├── cam2_session.json     # exam name, paper/grid, questions + boxes, choice groups, rubrics,
│                         # class list, name matches, resume position (relative paths only)
├── grades.json           # per student × question: value | "not_answered", comment;
│                         # overall comment, report overrides, session ID + save counter
├── cam2.lock             # "open on <computer> since <time>"
├── scans\                # copied scans or split PDFs (needed for "See whole page")
├── crops\                # __name__\s001.png, q1\s001.png … (ids, so renaming Q1 breaks nothing)
├── thumbs\               # page-1 thumbnails for Step ①
├── backups\              # daily grades.json backups (last 14)
└── reports\
    ├── <Exam>_Master_Grades.xlsx
    └── student_pdfs\     # <Student Name>_<Exam Name>.pdf
```

---

## 7. Build Phases

**Phase 1: Engine and tests** ✅ done 2026-10-30 (97 tests; see CHANGELOG.md and ARCHITECTURE.md)
- `slicer.py`, `storage.py`, `rubrics.py`, `roster.py`, `grading_summary.py` and `i18n.py`.
- Port CAM's tests:
  - grid maths: `test_exam_grid.py`
  - choice sections: `test_exam_sections.py`
  - cloud safety and concurrency: `test_database_cloud_safety.py`, `test_database_concurrency.py`
  - folder picker: `test_folder_dialog.py`
- Add new tests:
  - B5 ISO/JIS detection and landscape pages
  - multi-box stitching
  - round-half-up
  - best-N choice totals
  - Shift-JIS CSV
  - safe and unique report file names

**Phase 2: Start screen and Steps ①–③** ✅ done 2026-10-30 (130 tests; clicked through in a browser with sample papers)
- Language switch, recent sessions, scans and thumbnails, save folder, paper size.
- Marks/rubric setup and rubric builder.
- Drag-box selection on the 5 mm grid, multi-box questions and the "check on other papers" strip.
- Choice groups and slicing.
- Class list column picker and name matcher.

**Phase 3: Step ④ grading** ✅ done 2026-10-30 (137 tests; graded sample papers in marks and rubric mode, in English and Japanese, including a pulled-out session folder)
- Grading card, overlay badges and *Not answered*.
- Whole-page viewer.
- Ungraded-only filter, save indicator, red failure banner and emergency copy.

**Phase 4: Step ⑤ review and export** ✅ done 2026-10-30 (146 tests; reports made from the sample papers in English and Japanese and checked page by page)
- Review table with report-only overrides.
- EN/JA student PDFs and the Excel gradebook.

**Phase 4b: Scanning guide, booklets, page fixes, late papers** ✅ done 2026-10-31 (174 tests, with the booklet stack order added the same day; a booklet class with an upside-down sheet, fixed in the browser, plus a late student added)
- Start-screen guide, several PDFs per class, page photos, booklet unfolding and the paper-1 preview.
- Page fixes on the scan check (move, turn, remove, blank page; booklet sheet turn and swap).
- Adding late papers at any time.

**Phase 4c: Questions assessed on several criteria** ✅ done 2026-10-31 (184 tests; a rubric exam with Q2 on Criteria B and C graded in the browser, reviewed, and exported to PDF and Excel)
- Criteria tick boxes in Step 2, per-criterion grading items and tabs in Step 4, per-criterion columns in Step 5, the reports and the gradebook.

**Phase 5: Packaging and end-to-end testing**
- `build_windows.py`, `build_mac.py`, launchers, READ ME FIRST (EN/JA) and the quick guide.
- Full run-through on Windows and on a Mac (Apple Silicon, plus Intel if one is available):
  - pause and resume across two sittings
  - session folder on USB and on OneDrive
  - A4, B5 and A3 papers
  - a combined PDF with a missing page, fixed with a blank page
  - a real A3 booklet scan from the school copier (front/back orientation)
  - Japanese report output

---

## 8. Decisions

**Decided**
- **Mac signing:** the Mac package ships **unsigned**. Teachers approve it once with **Open Anyway** (§5), and the launcher clears the download flag from the rest of the folder.
  - The `READ ME FIRST` and the quick guide show this step with screenshots, in EN and JA.
  - Signing and notarising (Apple Developer account, US$99/year) can be added later without changing the app.

**Still needed**
1. **Mac testing:** a Mac (ideally Apple Silicon) is needed for Phase 5. The Mac package can be built from Windows but not tested there. The test must include the first-launch Open Anyway step on a freshly downloaded zip.
2. **Japanese UI wording:** a native check of `i18n/ja.json` before release.

## 9. Deliberately Not Included
- Built-in MYP rubrics: teachers bring their own.
- Keyboard shortcuts.
- ~~Re-slicing a question after slicing: replaced by **See whole page**.~~ Added back (2026-10-31) as **✎ Adjust this box** in Step ④, for a box drawn in the wrong place early on: it opens Step 2 on that question and re-slices only that question, keeping every grade.
- Matching names by paper order.
- Half marks.
- Google Drive API sync: a synced folder works through the normal save-folder rules.
- Word (`.docx`) import.
