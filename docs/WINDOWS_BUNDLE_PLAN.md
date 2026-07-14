# Windows Portable Bundle, Folder Pickers & Quick Guide — Plan

Goal: let non-technical colleagues run CAM on school laptops (Windows 10/11,
possibly without admin rights) using **local folders only** — no Google Drive
setup, no Python installation, no terminal. Three deliverables:

1. **Folder-picker buttons** replacing type-a-path friction (QoL, ships in the
   app itself).
2. **Portable zip bundle** — extract → double-click `Start CAM` → browser opens.
3. **CAM Quick Guide (PDF)** — task-based, screenshot-per-step, few words.

## Decisions already made (with the author — do not re-litigate)

- Packaging: **portable zip** with embedded Python runtime. No PyInstaller
  (brittle with Streamlit, SmartScreen/AV problems), no installer.
- Manual: **PDF with screenshots**, built from Markdown kept in `docs/`.
- Source: **this repo** (school-specific features stay available).
- AI extras (`anthropic`, `google-genai`): **included** in the bundle.
- Colleagues use local data folders; **no Drive credentials shipped** — the
  workspace already shows a friendly "add credentials.json" notice when absent
  (`cam_grading_workspace/app.py:652`), which is the desired behaviour.

## Safety constraints (CLAUDE.md rules apply throughout)

- **Every test launch is sandboxed**: temp `local_device_prefs.json` /
  `db_custom_path` pointing at a temp folder. The first-boot panel's discovery
  scan may *find* the real OneDrive DB on the dev machine — never adopt it
  during testing; always choose the temp folder.
- The bundle is staged from **`git archive HEAD`**, never from the working
  folder — only tracked files (fictional sample data) can enter the zip;
  untracked `credentials.json`, `token.json`, `local_device_prefs.json`,
  real DBs physically cannot.

---

## Phase 1 — Native folder-picker buttons (CAM)

A "📁 Browse…" button beside each folder-path text input, opening the real
Windows *Select Folder* dialog. The text box stays (editable — network shares,
Drive folder IDs still need typing).

**New module `engine/folder_dialog.py`** — `pick_folder(title, initial=None)
-> str | None`:

- Must run the dialog in a **subprocess** (`[sys.executable, "-m",
  "engine.folder_dialog", …]`, prints the chosen path to stdout) so COM/STA
  requirements never touch Streamlit's script thread.
- Inside the subprocess: **ctypes `IFileOpenDialog`** with `FOS_PICKFOLDERS`,
  forced topmost/foreground (dialogs otherwise open behind the browser).
  Fallback: PowerShell `System.Windows.Forms.FolderBrowserDialog` if COM init
  fails. **Do not use tkinter** — the embedded Python in the bundle has no
  tcl/tk.
- Non-Windows (`os.name != "nt"`): return `None`; call sites hide the button.

**Five call sites in `app.py`** (line numbers as of commit `5c55ec3`):

| Input | Where | Note |
|---|---|---|
| Custom Database Path | `settings_dialog`, ~6236 | ⚠ inside `st.form("settings_form")` — regular buttons are illegal in forms. Restructure: move the DB-path row (input + Browse) *above/outside* the form, keeping Save semantics for the rest. |
| Term backup folder | `~6165` | plain dialog section, button beside works directly |
| Re-link class folder | `~7134` | straightforward |
| Master directory | class dialog, ~9109 | dual-purpose (local path **or** Drive folder ID) — keep text box primary; check whether this sits in a form and restructure like Settings if so |
| First-boot "Use another folder" | `~9323` | straightforward |

Pattern per site: `Browse…` → `pick_folder()` → on success write the path into
the input's `st.session_state` key → `st.rerun()`.

**Boot-panel change (bundle-safe "Start fresh"):** "Start fresh" currently
adopts a blank path → DB beside `app.py` (`~9345`), i.e. *inside* the extracted
bundle folder, which a future "replace the folder" update would destroy.
Change it (decision made with the author): on Windows, "Start fresh" defaults
the database to **`<Documents>\CAM Data\`** — created if absent, adopted via
the normal `_adopt_db_path` flow, with the chosen location named in the
confirmation message. Resolve Documents with **`SHGetKnownFolderPath
(FOLDERID_Documents)`** via ctypes — *not* `%USERPROFILE%\Documents` — because
school laptops often redirect Documents into OneDrive (Known Folder Move), and
the shell API returns the true location (a helper in `engine/folder_dialog.py`
alongside the picker is a natural home). The sample gradebook seeding must
follow the same path (copy the tracked sample DB there on first save, or let
the existing empty-folder-gets-new-DB logic run — keep whichever matches
current "start fresh with sample data" semantics). Fallbacks: if the shell
call fails, fall back to `%USERPROFILE%\Documents`; on non-Windows keep
today's beside-`app.py` behaviour. Option 2 ("Use another folder") plus the
new Browse button remains the path for anyone wanting a different location —
the Quick Guide shows both.

## Phase 2 — Portable bundle build script

**New `tools/build_windows_bundle.py`** (run by the author on the dev machine;
colleagues only ever see the resulting zip):

1. Stage `git archive HEAD` into a temp build dir. Prune dev-only content:
   `.claude/`, `tools/`, `docs/*_PLAN.md` (keep the Quick Guide + USER_MANUAL).
2. Download the official **python-3.14.x embeddable package (amd64)** (cache
   the download under `tools/.cache/`); unzip to `runtime\`.
3. Enable site-packages: edit `runtime\python314._pth` (uncomment
   `import site`), bootstrap pip with `get-pip.py`, then
   `runtime\python.exe -m pip install -r requirements.txt` — this pulls the
   workspace requirements and (per decision) `anthropic` + `google-genai`.
   Respect the existing pin `streamlit==1.58.0` and the **no-kaleido** rule.
4. Prune `__pycache__`, pip caches, `runtime\Scripts\*.exe` shims not needed.
5. Write launchers at bundle root:
   - **`Start CAM.vbs`** — runs `runtime\python.exe -m streamlit run app.py
     --server.port 8600` with a hidden window, output redirected to
     `logs\cam.log`; Streamlit (non-headless) auto-opens the default browser.
   - **`Start CAM (troubleshooting).bat`** — same command with a visible
     console, for the "it won't start" page of the Quick Guide.
6. Write **`READ ME FIRST.txt`**: three steps (Extract All → double-click
   Start CAM → pick a data folder such as `Documents\CAM Data`), plus the
   one-paragraph update procedure (replace the app folder; your data folder is
   untouched).
7. Copy in the built `CAM Quick Guide.pdf` (Phase 3).
8. `shutil.make_archive` → `CAM-portable-vYYYY.MM.DD.zip`.

Notes:
- The workspace launch already uses `sys.executable` (`app.py:2578`) so it
  inherits the bundled runtime with zero changes.
- The tracked `acm_database.json` (fictional) ships as the sample gradebook —
  intentional, powers "Start fresh with sample data".
- Port 8600 stays fixed (matches dev config); the troubleshooting page covers
  the port-in-use case ("close the other CAM window").

## Phase 3 — CAM Quick Guide (PDF)

**New `docs/QUICK_GUIDE.md`** + `docs/quick_guide_images/`. Voice: plain
language, second person, no jargon, ~1 page per task, a screenshot or existing
SVG diagram per step. Pages:

1. **Get started** — extract the zip, double-click Start CAM, click *Start
   fresh* (your gradebook is created in `Documents\CAM Data` automatically) —
   or use *Browse…* to put it somewhere else.
2. **Set up a class** — class, roster, criteria.
3. **Add an assignment & enter marks.**
4. **Grade an exam** — workspace basics (scan → grade → marks appear in CAM).
5. **Reports & exports** — report cards, master Excel.
6. **Back up your term** — the Term backup folder + USB advice.
7. **When something goes wrong** — one page: won't start (use the
   troubleshooting launcher, read `logs\cam.log`), can't find my data folder,
   moved to a new laptop.

Production:
- Screenshots taken from the app running **sandboxed on the sample DB**
  (temp prefs), light theme, fixed browser width (1280 px) for consistency.
- **`tools/build_quick_guide.py`**: Markdown → styled HTML → PDF via Edge
  headless (`msedge --headless --print-to-pdf=…`) — present on every
  Win 10/11 machine, zero new Python dependencies. Output lands in `docs/`
  and is copied into the bundle by Phase 2.

## Phase 4 — Verification & docs

- Build a real zip, extract to a temp dir, launch via `Start CAM.vbs`:
  fresh bundle has no prefs → first-boot panel appears → choose a **temp**
  folder via the new Browse button → confirm DB is created there, classes can
  be added, the grading workspace launches from the bundled runtime, and the
  Drive-less workspace shows its friendly notice.
- Testing the new "Start fresh" default must **not** write to the dev
  machine's real `Documents`: give the Documents-resolution helper a test
  override (e.g. env var `CAM_DOCUMENTS_OVERRIDE` checked before the shell
  call) and point it at a temp dir during verification.
- Confirm the bundle zip contains no `credentials.json` / `token.json` /
  `local_device_prefs.json` / real data (automated check inside the build
  script: fail the build if any of those names appear).
- Update `docs/SETUP.md` (link the bundle path for colleagues vs. the dev
  setup), `docs/USER_MANUAL.md` cross-reference, `docs/CHANGELOG.md`.

## Suggested commit sequence

1. Phase 1 — folder pickers (+ boot-panel caption polish).
2. Phase 2 — bundle build script + launchers.
3. Phase 3 — Quick Guide markdown, images, PDF builder.
4. Phase 4 — docs updates + verification fixes.
