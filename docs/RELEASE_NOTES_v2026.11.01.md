# CAM v2026.11.01 — Windows portable release

The first release since v2026.07.14.1. The biggest change is exam grading:
scanned exams are now graded in **CAM2 Exam Grading**, which is included in the
download and opens from CAM. This release also adds comment-only drafts and
custom reporting classes, makes the database much harder to damage when
several computers share it, and fixes several crashes.

## ⚠ Before you update: every computer that shares your data folder

If you use CAM on more than one computer with the same (cloud-synced) data
folder, **update all of them** and stop using the old version.

This version saves the database in a newer format (with a database identity
and revision number that protect against one computer overwriting another's
work). The first save makes a verified backup beside the database before
upgrading it. The July version can still open the upgraded file, but when it
saves, it keeps only what it knows about: it writes the old format back and
drops draft feedback, custom reporting classes and the CAM2 exam links. The new
version then stops with "Database not loaded — read-only quarantine" until the
file is sorted out. So once one computer runs v2026.11.01, run only
v2026.11.01 on that data folder.

## Download and start

1. Download `CAM-portable-v2026.11.01.zip` and `SHA256SUMS.txt` from the
   [GitHub release](https://github.com/iamkifojp/criterion-assessment-metrics/releases/tag/v2026.11.01).
2. Right-click the ZIP, choose **Extract All**, and open the extracted
   `CAM-portable` folder. Do not run CAM from inside the ZIP.
3. Double-click **Start CAM.vbs**. If Windows asks "Do you want to open this
   file?", choose **Open**. Your browser opens CAM when it is ready; the first
   start can take a few minutes on a new laptop.
4. On first start, select your existing CAM data folder or choose
   **Start fresh with sample data**.

If CAM does not open, use **Start CAM (troubleshooting).bat**, which shows the
messages on screen; they are also saved in `logs\cam.log`.

## What's new

### Exams are graded in CAM2 Exam Grading

In Window 1, create an exam, click it and choose **🛠 Exam setup / Grade**.
CAM2 opens in its own browser tab with your class list already in it:

- **Real scans.** The whole class in one PDF from the photocopier (or a few
  batches), one file per student, or phone photos. Booklets scanned open on A3
  are put back in page order; turned, missing or extra pages can be fixed on
  screen; late papers can be added at any time.
- **Draw a box around each answer** on the first paper, several boxes per
  question if an answer runs over. **✎ Adjust this box** while grading fixes a
  box and slices only that question again; every grade is kept.
- **Marks or rubric levels.** Points per question, or a level from your own
  rubric (for example MYP 0–8). One exam, or even one question, can be assessed
  on several criteria.
- **Choice questions** ("answer 2 of 3"): count the best answers automatically,
  or choose which count.
- **Fair grading.** One question at a time across the class, *Not answered*
  kept apart from ungraded, quick comments, **Hide student names** and
  **Shuffle papers** (a new order for every question).
- **Reports for one test.** A PDF for every student and an Excel gradebook, in
  English or 日本語.

When grading is finished, click **✓ Grading finished — send to CAM**. The
results appear in Window 1's **📝 Exam grading** panel a few seconds later,
also if CAM was closed or on another class at the time (CAM compares each exam
folder with what it last read). Marks exams are turned into a 0–8 grade there;
rubric exams map each rubric to a criterion. The panel shows when the exam was
last sent and has a **🔄 Check CAM2 now** button.

The exam, scans included, is saved in the class folder, so you can carry on
grading on any computer that syncs it. The grading workspace's old exam screens
are gone. Exams graded with them keep their results and grades in CAM; an old
exam export CSV left in a class folder is ignored.

### Comment-only drafts

Mark an assignment **Draft — comments only** with the criteria you are giving
feedback on. Drafts have no grades: they never count as missing work, trends or
final grades, but their comments appear in Window 3, the Excel master's
Classroom Entry tab and the class comments document. Reviewed drafts show
**SEEN** in the grading workspace.

### Grading workspace

- **Copied submissions are matched** to the class namelist by full name,
  student ID or email in the file name, so re-uploaded or downloaded files no
  longer arrive as unknown students.
- **Student IDs instead of names** on grading cards, with numbered labels for
  unidentified work; anonymous grading also hides IDs and shuffles the order.
- **PDFs and documents** open in the viewer, with pages you can leave out.

### Reports

- **Custom reporting classes.** Report on a homeroom or any saved mix of
  students from several teaching groups, in the order you choose, without
  changing the class you grade.

### A safer shared database

- CAM reads the database once per start, so a cloud client changing the file
  mid-start cannot mix two versions.
- A computer with an older copy can no longer save over newer work from
  another computer; CAM saves your work to a recovery file instead.
- A database file that has gone missing or has a cloud "conflicted copy" beside
  it stops CAM safely instead of starting an empty gradebook.
- A file with a damaged record is refused as a whole rather than loaded with
  parts missing.

## Fixes

- **Build Excel master** no longer crashes when an assignment's date was set by
  hand.
- The Excel master's **Classroom Entry** tab is no longer empty for a class
  whose only work is a draft.
- Exporting an assignment with no deadline on a second day no longer creates a
  second CSV that blocks Sync.
- **⚙ Settings → 📁 Browse…** for the data folder no longer crashes.
- The class selector no longer logs a Session State warning when another
  computer's database is loaded.

## Updating from v2026.07.14 or v2026.07.14.1

Your gradebook lives in a separate data folder, so updating only replaces the
app:

1. Close the old CAM window.
2. Extract this ZIP into a **new app folder**; do not merge it into the old one.
3. Start the new copy and choose the same existing data folder when prompted.
4. Confirm the expected classes and students appear before deleting the old app
   folder.
5. Do the same on **every other computer** that uses this data folder (see the
   warning above).

Existing `.bak-*` files in the data folder are safety copies; keep them.

## Security and verification

The distribution builder exports only committed repository files and audits
both the staged folder and the final ZIP, rejecting credentials, OAuth tokens,
local-device preferences, database backups and every database except the
tracked fictional sample. Real student data is not included.

The release ZIP is scanned with Windows Defender before publication. To verify
the download, compare the ZIP's hash with `SHA256SUMS.txt`:

```powershell
Get-FileHash .\CAM-portable-v2026.11.01.zip -Algorithm SHA256
```

## Documentation

- [Quick Guide](QUICK_GUIDE.md) — the task-based guide, included in the bundle
  as a PDF.
- [Setup guide](SETUP.md) — portable and source installation, data folders and
  optional integrations.
- [User manual](USER_MANUAL.md) — the complete day-to-day workflow, including
  [Grading exam papers](USER_MANUAL.md#grading-exam-papers).
- [Changelog](CHANGELOG.md) — detailed history of every change in this release.
