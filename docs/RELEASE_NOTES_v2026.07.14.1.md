# CAM v2026.07.14.1 — Windows portable release

A point release that fixes a first-start failure in the portable launcher. The
application itself is unchanged from
[v2026.07.14](RELEASE_NOTES_v2026.07.14.md); only the launcher and its
onboarding text differ. If v2026.07.14 already starts correctly for you, this
update is optional but recommended.

## What was fixed

On a computer that had **never run Streamlit before**, double-clicking
**Start CAM.vbs** appeared to do nothing — no window, no browser, no error.

The bundled Streamlit still shows a one-time interactive prompt
(`Welcome to Streamlit! … Email:`) the first time it runs on a machine with no
Streamlit profile. Because the launcher starts CAM in a hidden console, that
prompt waited for a keypress that never came: its text went only to
`logs\cam.log`, and nothing reached the screen. Machines that had run Streamlit
during development never saw this, which is why earlier testing missed it.

## What changed in the launcher

- **Runs headless.** Both **Start CAM.vbs** and
  **Start CAM (troubleshooting).bat** now start Streamlit with
  `--server.headless true`, which skips the first-run email prompt entirely.
- **Opens the browser itself.** Headless mode disables Streamlit's own
  browser launch, so **Start CAM.vbs** polls the server's health endpoint and
  opens `http://localhost:8600` once CAM is ready.
- **No more silent failures.** The launcher shows a brief "CAM is starting"
  message, a clear error if the `runtime` folder is missing (which happens when
  the ZIP was opened without extracting), and a pointer to the troubleshooting
  launcher if CAM does not come up within five minutes.
- **Second click is safe.** Double-clicking the launcher while CAM is already
  running now simply reopens the browser instead of failing on the busy port.
- **Clearer READ ME.** `READ ME FIRST.txt` now walks through the Windows
  "Open file" security prompt shown for downloaded scripts.

## Download and start

1. Download `CAM-portable-v2026.07.14.1.zip` and `SHA256SUMS.txt` from the
   [GitHub release](https://github.com/iamkifojp/criterion-assessment-metrics/releases/tag/v2026.07.14.1).
2. Right-click the ZIP, choose **Extract All**, and open the extracted
   `CAM-portable` folder. Do not run CAM from inside the ZIP.
3. Double-click **Start CAM.vbs**. If Windows asks "Do you want to open this
   file?", choose **Open**. A short "CAM is starting" message appears, then your
   browser opens CAM when it is ready — the first start can take a few minutes
   on a new laptop.
4. On first start, select an existing CAM data folder or choose
   **Start fresh with sample data**.

If CAM reports that it could not start, use
**Start CAM (troubleshooting).bat**, which runs the same CAM in a visible
window. Its messages are also saved in `logs\cam.log`.

## Updating from v2026.07.14

Because your gradebook lives in a separate data folder, updating only replaces
the app:

1. Close the old CAM window.
2. Extract this ZIP into a **new app folder**; do not merge it into the old one.
3. Start the new copy and choose the same existing data folder when prompted.
4. Confirm the expected classes and students appear before deleting the old app
   folder.

Existing `.bak-*` files in the data folder are safety copies and should be kept.

## Security and verification

The distribution builder exports only committed repository files and audits
both the staged folder and final ZIP, rejecting credentials, OAuth tokens,
local-device preferences, database backups and every database except the
tracked fictional sample. Real student data is not included.

The release ZIP is scanned with Windows Defender before publication. To verify
download integrity, compare the ZIP's hash with `SHA256SUMS.txt`:

```powershell
Get-FileHash .\CAM-portable-v2026.07.14.1.zip -Algorithm SHA256
```

## Documentation

- [Changelog](CHANGELOG.md) — symptom-first history, including this fix.
- [v2026.07.14 release notes](RELEASE_NOTES_v2026.07.14.md) — the full feature
  summary this point release inherits.
- [Quick Guide](QUICK_GUIDE.md), [Setup guide](SETUP.md) and
  [User manual](USER_MANUAL.md) — the day-to-day documentation.
