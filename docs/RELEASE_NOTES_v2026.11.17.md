# CAM v2026.11.17

**Different classes can use the same assignment or exam name.** One exam sat by
8A and 8B can be called "Drawing" in both. Each class keeps its own grades,
exam results, date, archive and On/Off setting for it, and renaming, archiving
or deleting it in one class leaves the other class's untouched. A name still
has to be unique within a class.

- **A student in both classes.** CAM asks for a different name when the other
  class using it shares a student with this one, because that student's two
  sets of grades could not be told apart.
- **Classes that already share a name.** If imports gave two classes the same
  name before this release, they start with the same settings as now and
  separate when you next change one.
- **Term backups and re-sync.** A term backup no longer files a shared name's
  scores under both classes, and re-syncing one class replaces only that
  class's scores.

## Update every computer first

Install this release on every computer that opens the gradebook **before**
giving two classes the same name. An older CAM can still open the gradebook,
but when it saves, classes sharing a name go back to sharing their date,
archive and On/Off settings. Grades are not affected.

The first save with this release keeps a copy of the gradebook beside it,
named `acm_database.json.bak-pre-class-scoped-names-<date and time>`. CAM never
deletes it.

Quit CAM and let any shared data folder finish syncing. Install the new app
and choose the same gradebook folder when reopening it.

- **Windows:** extract `CAM-portable-v2026.11.17.zip` into a new app folder and
  open **Start CAM.vbs**.
- **Apple Silicon:** extract `CAM-Mac-AppleSilicon-v2026.11.17.zip` in Finder
  and replace **CAM.app** in **Applications**. Requires macOS 14 or later.
  If macOS blocks a trusted download, see [Apple's first-launch instructions](https://support.apple.com/en-gb/102445).

CAM2 and the exam format are unchanged from `v2026.11.10`, so standalone CAM2
needs no update. If you are updating from before `v2026.11.08`, follow the
[shared-data upgrade checklist](RELEASE_NOTES_v2026.11.08.md) before opening
existing exams. See the [setup guide](SETUP.md) for installation details.

Use `SHA256SUMS.txt` to verify the downloads. The release includes the tagged
CAM source and the matching PyMuPDF 2.0 and MuPDF 1.28.5 source archives.
