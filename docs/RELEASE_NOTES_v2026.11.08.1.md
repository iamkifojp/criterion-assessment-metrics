# CAM v2026.11.08.1

- **Exam comments stay cleared.** After clearing a comment in CAM2 and
  sending again, CAM clears any unedited copy attached to a criterion grade.
  Comments edited directly in CAM are preserved. If the previous version
  already restored an old comment, clear it once in CAM's grade editor to
  remove that copy.
- **Close an exam after sending.** CAM2 now offers **Save & close session** in
  **Review & export** after sending. The start screen directs you back to
  **Grades and Analysis** in CAM and shows where to quit CAM2.

## Update

Quit CAM and let any shared data folder finish syncing. Install the patch on
each computer using that folder. Use the same gradebook and class folders
when opening CAM again.

- **Windows.** Extract `CAM-portable-v2026.11.08.1.zip` into a new app folder
  and open **Start CAM.vbs**.
- **Apple Silicon.** Extract `CAM-Mac-AppleSilicon-v2026.11.08.1.zip` in Finder
  and replace **CAM.app** in **Applications**. The app requires macOS 14 or
  later. For a trusted download blocked on first launch, use Apple's
  app-specific approval. [Apple's first-launch instructions](https://support.apple.com/en-gb/102445)

This patch uses the same gradebook and exam formats as `v2026.11.08`. If
you are updating from an earlier release, follow the original shared-data
upgrade checklist. [Setup guide](SETUP.md) · [Original upgrade notes](RELEASE_NOTES_v2026.11.08.md)

Use `SHA256SUMS.txt` to verify the downloads. The release includes the tagged
CAM source and the matching PyMuPDF 2.0 and MuPDF 1.28.5 source archives for
the bundled AGPL-licensed components.
