# CAM v2026.07.14 — Windows portable release

This is CAM's first self-contained distribution for **64-bit Windows**. It is
designed for teachers who want to download, extract and start CAM without
installing Python, Git or development tools.

## Download and start

1. Download `CAM-portable-v2026.07.14.zip` and `SHA256SUMS.txt` from the
   [GitHub release](https://github.com/iamkifojp/criterion-assessment-metrics/releases/tag/v2026.07.14).
2. Right-click the ZIP, choose **Extract All**, and open the extracted
   `CAM-portable` folder. Do not run CAM from inside the ZIP.
3. Double-click **Start CAM.vbs**. On first start, select an existing CAM data
   folder or choose **Start fresh with sample data**.
4. Open **CAM Quick Guide.pdf** for the illustrated setup, grading, reporting,
   backup and troubleshooting walkthrough.

If the hidden launcher does not open CAM, use
**Start CAM (troubleshooting).bat**. Its messages are also saved in
`logs\cam.log`.

## Highlights

- **Portable Windows app.** The bundle includes a 64-bit embedded Python
  runtime and CAM's dependencies. It does not require an administrator account.
- **Safer first start and updates.** CAM keeps the app and gradebook in separate
  folders, can discover existing cloud-synced databases, and never replaces an
  existing database merely because a folder was selected.
- **Native folder selection.** Browse buttons open the Windows folder picker for
  the database, class directories, assignment relinking and term backups.
- **Term backup and restore.** Teachers can create a portable term snapshot,
  preview a restore, and explicitly confirm before replacing a term.
- **Exam-grading workflow.** Slice scanned papers by question, mark one question
  across the class, use anonymous ordering and feedback keywords, adjust and
  re-slice a question without losing marks, and sync the export back into CAM.
- **Exam identity and banding.** Name-box crops help match scans to the roster;
  page-count warnings catch inconsistent booklet scans; section-level 0–8
  suggestions remain teacher-decided before one final criterion grade is
  applied.
- **Polished deliverables.** CAM generates consistent class workbooks,
  report-card packs, student reports and report comments while keeping the
  evidence behind each grade visible.

## Updating an existing CAM installation

1. Close the old CAM window.
2. Extract the new ZIP into a **new app folder**; do not merge it into the old
   folder.
3. Start the new copy and choose the same existing data folder when prompted.
4. Confirm that the expected classes and students appear before deleting the
   old app folder.

Your gradebook, exam artifacts and backups remain in the separate data folder.
Do not delete or replace that folder during an app update. Existing `.bak-*`
files are safety copies and should be retained.

## Security and verification

The distribution builder exports only committed repository files and audits
both the staged folder and final ZIP. It rejects credentials, OAuth tokens,
local-device preferences, database backups and every database except the
tracked fictional sample at the bundle root. Real student data is not included.

The release ZIP is scanned with Windows Defender before publication. To verify
download integrity yourself, compare the ZIP's hash with `SHA256SUMS.txt`:

```powershell
Get-FileHash .\CAM-portable-v2026.07.14.zip -Algorithm SHA256
```

## Documentation

- [Quick Guide](QUICK_GUIDE.md) — the task-based guide included in the bundle
  as a PDF.
- [Setup guide](SETUP.md) — portable and source installation, data folders and
  optional integrations.
- [User manual](USER_MANUAL.md) — the complete day-to-day workflow.
- [Changelog](CHANGELOG.md) — detailed implementation and behavior history.

## Known boundaries

- The portable bundle is for 64-bit Windows. macOS and Linux users should run
  CAM from source.
- Google Docs grading requires the teacher's own Google OAuth credentials.
  Folder-synced images, video and PDFs can be graded without Google OAuth.
- AI-written report comments are optional. Clipboard mode works without an API
  key; one-click generation requires the teacher's own Claude or Gemini key.
