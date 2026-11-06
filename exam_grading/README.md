# CAM2 Exam Grading

CAM2 turns a stack of scanned exam papers into one-question-at-a-time grading,
then produces a PDF report for every student and an Excel gradebook.

It is a standalone, simplified fork of CAM (Criterion Assessment Metrics),
built so that any teacher can use it **without installing anything and without
training**.

## What it does

**Five guided steps,** each showing one instruction at a time:

1. **Exam & scans.** Name the exam and bring in the papers.
2. **Set up the questions.** Draw a box around each question on one paper, then
   slice every paper into answers.
3. **Match names** to your class list.
4. **Grade** one question across every paper.
5. **Review & export.** Check the results, choose what goes on the report, and make
   the student PDFs and the gradebook.

**Grade each question the way that suits it.**
- A question with a marks box filled in is graded with marks. A question with only
  a criterion ticked is graded with levels from your rubric, one per criterion. A
  paper can mix the two freely.
- The first screen only sets where you start, and you can fill in marks and criteria
  in any order. They never need slicing again, and once a question has grades it
  can't switch between marks and levels.
- A teacher who only wants marks never has to see a rubric. CAM2 ships no rubric
  text: you type, paste or upload your own.
- Choice questions ("answer 2 of 3") count a student's best answers, or the ones you
  pick.

**Divide a paper into sections, if you want to.** Add a divider in the question list,
and name the section if you like. Sections can be given different weightings, which
always add up to 100%, so a section of 24 multiple-choice marks can count as much as
a section of 40 written marks.

**You decide the levels.** Marks are added up, but rubric levels are reported as you
gave them (`B5`) and are never averaged or added to marks. With **Overall criterion
results** on, CAM2 gathers each criterion's marks and grades from across the paper,
beside a final level you type yourself.

**Choose what goes on the report.** Section results, the rubric tables, the overall
marks, and answer images section by section, with anything that doesn't apply hidden.
What you left blank does not print. **See one report first** shows you one student's
PDF before you make the whole class's.

**A gradebook that explains itself.** Every grade, comment and section result, the
calculated result beside the one on the report, class statistics, and a second sheet
listing the questions, sections and rubrics.

**Made for real teaching conditions.**
- **Real scans, not perfect ones.** Scan the whole class into one PDF, a few batches,
  one file per student or phone photos. Booklets scanned open on A3 are put back in
  page order, and upside-down, misplaced or missing pages can be fixed on screen.
  Late papers can be added at any time.
- **Stop any time.** Every grade is saved the moment it is given. Next time,
  **Continue** takes you back to the same question and student.
- **Safe on USB sticks and cloud drives** (OneDrive, Google Drive, iCloud Drive,
  Dropbox). CAM2 checks every save, keeps an emergency copy on your computer, and
  warns you before two computers overwrite each other.
- **English and 日本語** for the whole app and for student reports.
- **Unzip and double-click.** The Windows and Mac downloads carry their own Python, so
  nothing has to be installed.
- **Offline.** CAM2 needs no internet and sends nothing over it. If you save to a cloud
  drive, that drive syncs your session as it does any other file.

## Status

**The app is built; testing is the last stage.** Everything above works in English and
Japanese, and is in the test build `v0.3.2-dev`, which colleagues are trying with
made-up sample exams on their own computers.

| Stage | | State |
|---|---|---|
| Phase 1 | Engine and tests | ✅ done |
| Phase 2 | Start screen and Steps ①–③ | ✅ done |
| Phase 3 | Step ④ grading | ✅ done |
| Phase 4 | Step ⑤ review, student PDFs and Excel gradebook | ✅ done |
| Phase 4b | Scanning guide, booklets, page fixes, late papers | ✅ done |
| Phase 4c | Questions assessed on several criteria | ✅ done |
| Phase 5 | No-install Windows and Mac downloads, tested end to end on real computers | ⏳ Built and tested on the computers that made them; tests on other computers next |
| Exam sections | Sections, mixed marks and rubric questions, and report options ([plan](Exam-Section-Plan.md)) | ⏳ Phases 1 to 6 of 7 done. Phase 7: sample exams made and tried on Windows; test build `v0.3.2-dev` with colleagues |

All 354 automated tests pass, and every finished stage was also tried out in a
browser with sample papers. CAM2 can also be run from the source code (see
[For developers](#for-developers)). [PLAN.md](PLAN.md) has the full plan and
[CHANGELOG.md](CHANGELOG.md) the details of each stage.

## For teachers

The downloads are test builds for now, as they are still being tried on other
computers. They are on this repository's
[Releases](https://github.com/iamkifojp/cam2-exam-grading/releases) page. The current
one is `v0.3.2-dev`:

| Computer | Download | First start |
|---|---|---|
| Windows 10 / 11 | `CAM2-exam-grading-Windows-vX.zip` | [Unblock the zip](#windows-unblock-the-download-first), unzip it, then double-click **Start CAM2 Exam Grading**. If Windows still says it protected your PC, click **More info**, then **Run anyway** if it is there |
| Mac with an Apple chip (M1 or later) | `CAM2-exam-grading-Mac-AppleSilicon-vX.zip` | Unzip, double-click **Start CAM2 Exam Grading**, then approve it once in System Settings → Privacy & Security → **Open Anyway** |

### Windows: unblock the download first

Windows marks files that come from the internet, and this can stop CAM2 from starting.
Some school computers have no **More info** or **Run anyway** option, so please don't
skip this step. Before you unzip:

1. Right-click the zip and choose **Properties**.
2. On the **General** tab, tick **Unblock**, next to "This file came from another
   computer and might be blocked to help protect this computer".
3. Click **OK**, then unzip as usual.

- **Already unzipped?** Do the same to **Start CAM2 Exam Grading** in the unzipped
  folder.
- **No Unblock tick box?** Windows hasn't marked that file, so carry on.
- **Windows in Japanese?** The tab is 「全般」, and the tick box is 「許可する」.
- **Still refused after unblocking?** Your school's settings may be blocking CAM2, so
  ask your IT team.

### Before you start

Sessions from `v0.2.0-dev` open in this version, but once saved here, `v0.2.0-dev` can
no longer open them.

**To try CAM2 without your own papers,** the same release has
`CAM2-sample-exam-vX.zip`: a made-up exam in English and Japanese, with a class list,
rubrics and `Test-guide.pdf`, which tells you the grades to give and the results to
expect.

You will need:
- your scanned papers. Nothing has to be set up before the exam: scan the
  whole class at the photocopier into one PDF (or a few batches). Booklets
  can be unstapled and scanned open on A3, and CAM2 puts their pages back in
  order. One file per student and phone scans work too. The start screen's
  **How to scan your papers** has the details;
- the paper size (A4, B5, A3, or a slide size for decks saved as PDFs);
- optionally, your class list in Excel or CSV.

## For developers

Requires Python 3.14 (the version the packages ship).

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -t .
```

The tests use Python's built-in `unittest`, so no test runner needs to be
installed. They create their own test PDFs and temporary folders and never
read real student data.

### Running the app

```bash
python launcher.py
```

This starts CAM2 on `http://127.0.0.1:5182/` and opens the browser. Useful options:

| Option | What it does |
|---|---|
| `--port <number>` | try this port first, instead of 5182 |
| `--no-browser` | don't open a browser tab |
| `--idle 0` | never stop by itself (normally it stops 10 minutes after the last tab closes) |
| `--host <handoff.json>` | open one exam for another app (CAM); see `engine/host.py` |
| `--data-dir <folder>` | keep app data (recent sessions, emergency copies) **and** the default Documents folder inside `<folder>`, so trying things out never touches your real ones |

### Sample papers to try it with

```bash
python tools/make_sample_scans.py <output folder>
```

This makes 8 fake two-page papers (made-up names), the same papers as one
combined PDF, the same again as A3 booklets scanned open (one sheet upside
down and one booklet stacked inside sheet first, to try the page fixes), one late student's paper, and a class list. In Step 1, use **Or paste the path…** if you
would rather not click through the folder picker.

### A sample exam to test with

```bash
python tools/make_sample_exam.py test-folder
```

This makes a whole made-up exam in English and in Japanese, in
`sample-exam-en` and `sample-exam-ja`: 6 students' scanned papers, a class list,
three rubrics to upload, and `Test-guide.pdf`, which walks through two exams with the
grades to give and the results to expect. `test-folder/` is not committed, so testers
get these two folders as a zip on the release.

### Building the downloads

Each download is built on its own system, with Python 3.14. On Windows:

```bash
python tools/build_windows.py
```

On an Apple Silicon Mac:

```bash
python3 tools/build_mac.py
```

These make `dist/CAM2-exam-grading-Windows-v<version>.zip` and
`dist/CAM2-exam-grading-Mac-AppleSilicon-v<version>.zip`, with the version taken
from `VERSION` in `app.py`. Each installs what it needs into its own
`build/venv`, and starts the packaged app once to check that it works. `build/`
and `dist/` are not committed: the zips go on the Releases page, built from one
tagged commit. The notes on the Mac package and the release steps are under Phase 5
in [PLAN.md](PLAN.md).

### More documents

- [ARCHITECTURE.md](ARCHITECTURE.md) explains how the code and the session
  folder are organised.
- [PLAN.md](PLAN.md) is the implementation plan.
- [CHANGELOG.md](CHANGELOG.md) lists changes by phase.
- [Feedback-and-Upgrades.md](Feedback-and-Upgrades.md) collects colleagues' requests
  for future versions.

### Keeping student data out of the repository

`.gitignore` excludes session folders, scans, crops, reports, PDFs and
spreadsheets. Never commit a real session folder; tests must build their own
data (see `tests/helpers.py`).

## Credits

Forked from CAM (`criterion-assessment-metrics`). The grid geometry, the
save-safety rules, the Windows folder picker and the portable-package builder
come from CAM.

## Licence

CAM2's own code is released under the [MIT License](LICENSE), the same licence
as CAM.

The downloads also include PyMuPDF, which CAM2 uses under the GNU AGPL version
3, so each download as a whole is licensed under the
[AGPL](licences/AGPL-3.0.txt). [licences/NOTICE.txt](licences/NOTICE.txt) lists
every library in the downloads, and
[licences/THIRD-PARTY-NOTICES.txt](licences/THIRD-PARTY-NOTICES.txt) has their
licence texts. The zip carries the same files in its `Licences` folder.
