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

Your browser opens to the dashboard. On first run CAM loads the bundled
**fictional sample class** (`acm_database.json`) so you can explore every screen
with realistic-looking (but invented) data. To reset the demo at any time:

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
3. In `cam_grading_workspace/app.py`, fill in the `MY_IDENTITIES` list with the
   account name(s)/email(s) you own, so your own uploads are never mistaken for a
   student's work.

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
