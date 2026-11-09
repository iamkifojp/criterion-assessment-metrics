# CAM v2026.11.10

**Connect Google Drive works on the first click with a shared CAM data folder.**
Put your Google Desktop OAuth `credentials.json` or `client_secret*.json`
beside the active gradebook in your private data folder. Open **Add / Edit class**
and click **Connect Google Drive**. CAM finds the file even before the grading
workspace is configured. Existing credential locations still take precedence.
Each computer authorizes separately and saves its token locally by default.

## Update

Quit CAM and let any shared data folder finish syncing. Install the new app
and choose the same gradebook folder when reopening it.

- **Windows:** extract `CAM-portable-v2026.11.10.zip` into a new app folder and
  open **Start CAM.vbs**.
- **Apple Silicon:** extract `CAM-Mac-AppleSilicon-v2026.11.10.zip` in Finder
  and replace **CAM.app** in **Applications**. Requires macOS 14 or later.
  If macOS blocks a trusted download, see [Apple's first-launch instructions](https://support.apple.com/en-gb/102445).

The gradebook and CAM2 exam formats are unchanged from `v2026.11.08.1`. If you
are updating from before `v2026.11.08`, follow the
[shared-data upgrade checklist](RELEASE_NOTES_v2026.11.08.md) before opening
existing exams. See the [setup guide](SETUP.md) for Google Drive configuration.

Use `SHA256SUMS.txt` to verify the downloads. The release includes the tagged
CAM source and the matching PyMuPDF 2.0 and MuPDF 1.28.5 source archives.
