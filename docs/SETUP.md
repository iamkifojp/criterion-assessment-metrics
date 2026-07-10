# Setup guide

This guide gets Criterion Assessment Metrics (CAM) running on your machine and
connected to your own data. It assumes you are comfortable running a couple of
commands in a terminal, but not much more.

- [1. Install Python](#1-install-python)
- [2. Get the code](#2-get-the-code)
- [3. Install dependencies](#3-install-dependencies)
- [4. Run the app](#4-run-the-app)
- [5. Point CAM at your own data](#5-point-cam-at-your-own-data)
- [6. Optional: report-comment AI](#6-optional-report-comment-ai)
- [7. Optional: the grading workspace + Google Drive](#7-optional-the-grading-workspace--google-drive)
- [Troubleshooting](#troubleshooting)

---

## 1. Install Python

CAM needs **Python 3.11 or newer**.

- **Windows:** install from [python.org](https://www.python.org/downloads/) and
  tick *"Add Python to PATH"*. The examples below use the `py` launcher that
  ships with the Windows installer.
- **macOS / Linux:** use your package manager or python.org. Replace `py` with
  `python3` in the commands below.

Check it:

```bash
py --version        # Windows
python3 --version   # macOS / Linux
```

## 2. Get the code

```bash
git clone https://github.com/iamkifojp/criterion-assessment-metrics.git
cd criterion-assessment-metrics
```

(Or download the ZIP from GitHub and unzip it.)

## 3. Install dependencies

Optionally create a virtual environment first (recommended):

```bash
py -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

Then install:

```bash
pip install -r requirements.txt
```

This installs Streamlit (the dashboard), plotting and document libraries, and
the grading-workspace dependencies. The AI client libraries (`anthropic`,
`google-genai`) are included but only used if you enable API mode later.

## 4. Run the app

```bash
py -m streamlit run app.py
```

Your browser opens to the dashboard. On the **first run on a new computer** CAM
shows a one-time **setup panel** (it never silently boots the sample data on a
machine that has not chosen where its gradebook lives — see §5). It offers to:

- **Use an existing database** it discovered in your OneDrive / Google Drive /
  Dropbox folders (each shown with its class/assignment counts so you recognise
  the real one),
- **Use another folder** you type in (a USB drive, a network share, or any
  unlisted cloud path), or
- **Start fresh** with the bundled **fictional sample class** so you can explore
  every screen with realistic-looking (but invented) data.

Your choice is remembered on that device; you can change it later in
**⚙ Settings**. To regenerate the sample data at any time:

```bash
py tools/generate_sample_data.py
```

## 5. Point CAM at your own data

**Your real gradebook never goes in the repo.** It lives in a folder of your
choosing — ideally a cloud-synced one (OneDrive, Google Drive, Dropbox) so it is
backed up and available on every device you teach from.

CAM decides where to read/write using a small, **device-local** preferences file
called `local_device_prefs.json` (this file is git-ignored and stays on your
machine). The key that matters is `db_custom_path`:

| `db_custom_path` value | What CAM does |
|---|---|
| blank / not set | Uses `acm_database.json` beside `app.py` (the sample). |
| a **folder** path | Places/reads `acm_database.json` **inside that folder**. |
| a path ending in `.json` | Uses that exact file. |

You can set it two ways:

- **In the app:** open **⚙ Settings → Custom database location** and paste your
  folder path. CAM writes it to `local_device_prefs.json` for you.
- **By hand:** create `local_device_prefs.json` next to `app.py`:

  ```json
  {
    "db_custom_path": "C:\\Users\\you\\OneDrive\\CAM"
  }
  ```

Once set, CAM creates `acm_database.json` in that folder and keeps every class's
data (grade exports, exam scans, caches, finalized term summaries) in per-class
subfolders beside it. Because the folder is cloud-synced, all your devices share
one database.

### Adding a second computer

You do **not** need to hand-copy `local_device_prefs.json`. On a new machine,
just launch CAM and use the first-run **setup panel** (§4): pick the database it
finds in your cloud folder, or paste the folder path under *Use another folder*.
CAM **adopts** the existing database (loads it — never overwrites it); layout
preferences stay per-device by design. Classes whose watch folder is a Google
Drive folder travel automatically (their Drive IDs live in the shared database);
a class whose master directory is a **local path** is inherently per-machine and
is re-linked once via **✎ Add / Edit class** on the new computer.

For scripted or one-liner setups, the **`CAM_DB_PATH`** environment variable
overrides the pref entirely and skips the setup panel:

```bash
# Windows PowerShell
$env:CAM_DB_PATH = "C:\Users\you\OneDrive\CAM"; py -m streamlit run app.py
```

`CAM_DB_PATH` accepts the same folder-or-`.json` value as `db_custom_path`.
Because it cannot fall through to the device prefs, it is also the safe way for
tests and harnesses to pin a sandbox path that can never reach your real data.

> **Back up before big changes.** Before any migration or bulk cleanup, copy
> your `acm_database.json` to a timestamped `.bak-*` file first. CAM is designed
> so a real database is never touched by a test run — keep it that way.

## 6. Optional: report-comment AI

Comment generation works with **no setup** in *clipboard mode*: CAM builds the
prompt, you paste it into any chatbot, and paste the result back.

For one-click generation you can enable **API mode** for either provider:

- **Claude (Anthropic):** get an API key from the Anthropic Console and set it in
  the app's comment settings (or the `ANTHROPIC_API_KEY` environment variable).
- **Gemini (Google):** get an API key from Google AI Studio and set it likewise
  (or `GOOGLE_API_KEY`).

Keys are read at runtime and are **never** committed. Do not paste keys into any
tracked file.

## 7. Optional: the grading workspace + Google Drive

`cam_grading_workspace/` is a separate Flask app for grading student work that is
synced into a folder from Google Drive / OneDrive. The dashboard launches it on
demand, or you can run it directly:

```bash
py cam_grading_workspace/app.py --port 5050
```

If you use Google Drive sync, you supply your own Google OAuth client:

1. In the [Google Cloud Console](https://console.cloud.google.com/), create an
   OAuth 2.0 **Desktop app** client and download its JSON.
2. Save it as `credentials.json` in the repo root (it is git-ignored). On first
   connect, a browser window authorizes access and a local `token.json` is
   cached.
3. Tell the workspace which Drive accounts are **yours**, so files you upload
   are never mistaken for a student's work. When you share a class folder from
   your school account to a personal Gmail, Drive reports *you* as the owner of
   every file; the workspace needs to know that so it can re-route each file to
   the real student instead of bucketing them all under your account. The
   easiest way is the workspace's **⚙ Settings → My identities** box (one per
   line): it saves them into `gcg_settings.json` and mirrors them to your cloud
   sync folder, so every other machine picks them up automatically. List your
   school login, display name, and any Gmail the folder is shared through
   (matched case-insensitively as a substring); reload the assignment after
   saving. (You can still set them per-device by hand in a git-ignored
   `local_device_prefs.json` inside `cam_grading_workspace/` —
   `{ "my_identities": ["j.smith", "yourname@gmail.com"] }` — which is merged in
   as an override.) Either way nothing personal is ever committed: both files are
   git-ignored, and the tracked source ships empty.

**Bringing CGW to a second computer.** Once your cloud sync folder is set, most
of the per-machine setup heals from it:

- **Identities** already travel in `gcg_settings.json` (above) — nothing to copy.
- **Client secret**: you can drop `credentials.json` (or `client_secret_*.json`)
  into the cloud sync folder instead of each repo root; the workspace probes it
  there after the app root. An installed-app secret is unusable without your
  browser consent, so a private cloud folder is a fine home for it.
- **Sign-in**: signing in once per machine is the only remaining step. To skip
  even that, place your `token.json` in the cloud folder and turn on **⚙ Settings
  → Seed sign-in from the cloud folder** (off by default). It is a one-way seed —
  token refreshes stay on the local machine and are never written back to the
  cloud. Tradeoff: that token grants read-only Drive access to anyone who can
  read the cloud folder, so leave it off unless the folder is yours alone.

Folder-sync grading also works **without** any Google setup: point it at a local
folder that OneDrive/Drive already syncs to disk.

## Troubleshooting

- **`streamlit: command not found`** — use `py -m streamlit run app.py` instead
  of a bare `streamlit`.
- **The app shows no students** — check **⚙ Settings**: if `db_custom_path`
  points at an empty folder, CAM starts a fresh empty database there. Clear it to
  fall back to the sample, or ingest a CSV.
- **Grading workspace won't start** — make sure `pip install -r requirements.txt`
  completed; it pulls in the workspace's own dependencies (e.g. PyMuPDF).
- **Reset the demo** — `py tools/generate_sample_data.py` rewrites the sample
  `acm_database.json`.
