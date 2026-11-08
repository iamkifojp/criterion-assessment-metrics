# CAM v2026.11.08

CAM runs on 64-bit Windows and Apple Silicon Macs. Both bundles include the
grading workspace and the CAM2 engine that CAM uses to grade exams.

## Update every computer before opening an existing exam

1. Quit CAM and its grading helpers on every computer. Let the shared data
   folder finish syncing.
2. Back up `acm_database.json` and each class's `exams/` folder before opening
   an exam with this release.
3. Install this CAM version on every computer that uses the data. Keep the
   existing data folder separate from the app and select it again if asked.
4. Open the shared gradebook or exam on one computer at a time. Quit CAM
   and let the folder sync before switching computers.

Opening an older CAM2 exam upgrades its session to version 2. Older software
that reports `file_from_newer_version` is telling you it cannot read that
session. Update CAM on that computer before trying again. When the later
CAM2 upgrade raises the session version again, update every computer first
then too.

## Install

- **Windows.** Extract `CAM-portable-v2026.11.08.zip` into a new app folder
  and open **Start CAM.vbs**. If CAM fails to start, use the troubleshooting
  batch file and check `logs/cam.log`.
- **Apple Silicon.** Extract `CAM-Mac-AppleSilicon-v2026.11.08.zip` in Finder
  and move **CAM.app** to **Applications**. The app requires macOS 14
  (Sonoma) or newer. If macOS blocks a trusted first download, try opening
  it once, then use **System Settings → Privacy & Security → Open Anyway**.
  Managed Macs may restrict that option. [Apple's first-launch instructions](https://support.apple.com/en-gb/102445)

**Quit CAM** beside **Settings** stops CAM and both bundled grading helpers.
Use the release's `SHA256SUMS.txt` to verify your ZIP. [Setup guide](SETUP.md)

On the hosted Mac used for the release smoke test, the grading workspace took
longer than CAM's first wait. If you see that startup message, wait a few
seconds and click **Grade this Assignment** again.

## Grading and reporting

- **Exams open in CAM2.** Import paper scans or slide decks exported to PDF.
  Prepare slide PDFs before importing them. Direct fetching from Drive is
  deferred. Set up a draft as an assignment with **Draft — comments only**
  and grade it in the workspace.
- **You decide each 0–8 criterion grade.** Window 3 groups the paper's
  question levels, marks and comments by criterion. Choose one grade for
  each criterion you assessed, or apply a final level you explicitly typed
  in CAM2. CAM keeps marks as reference evidence and leaves new bands blank.
- **Report totals and percentages have range checks.** CAM2 rejects a report
  total above the paper maximum or a weighted percentage outside 0–100.
- **Workspace comments survive tick and deadline changes.** You can type or
  tick in either order. Linking partners combines their comments and ticks
  and gives the group the first graded member's grade. Export and sync a
  linked draft so CAM can recover the link if the workspace files are lost.
  Keyword lists keep their entries on reload. Add back any keywords an
  older version already lost.
- **Exam feedback feeds term comments.** CAM puts overall and question
  comments in a separate section of the term prompt, so exams leave the
  strength and growth evidence slots available for other work. When you
  send the prompt, those comments go to the AI service you selected. CAM
  keeps the overall comments and tells you how many whole question
  comments it left out of a long prompt.
- **New CAM2 comments have limits.** Question comments allow 300 characters
  and overall comments allow 600. CAM2 preserves previously saved text.

## Licences and source

CAM and CAM2 source code use the MIT licence. The Windows and Mac bundles
include PyMuPDF and are distributed under GNU AGPL version 3. The included
`Licences` folder identifies the bundled libraries and notices. The release
includes the tagged CAM source and the matching PyMuPDF 2.0 and MuPDF 1.28.5
source archives.
