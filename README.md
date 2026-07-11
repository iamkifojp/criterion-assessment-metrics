# Criterion Assessment Metrics (CAM)

A desktop grading-and-reporting toolkit for **IB MYP** teachers who work in
**Google Classroom**. CAM tracks each student's criterion grades (A–D) across a
whole school year, turns a term's worth of evidence into a defensible grade
suggestion, and drafts report-card comments — so grading and reporting take
minutes instead of evenings.

CAM started life as a tool for grading **artworks** — images and video handed in
through Google Classroom and its Drive folders — and has since grown to assess
PDFs and Google Docs as well, and to slice and mark scanned exam papers. It now
suits any MYP teacher who collects and grades student work in Google Classroom.
In particular, the **exam-slicing** workflow is immediately useful to anyone who
sets and marks exam papers, whatever their subject.

> **Note on data:** This repository ships with **fictional sample data only**.
> No real student information is included. See [Sample data](#sample-data).

---

## What it does

- **Multi-class gradebook.** One database holds every class you teach. Ingest
  grades from CSV exports; each score is stamped with a date so recent work can
  be weighted more heavily than older work.
- **Criterion-based aggregation.** MYP criteria A–D are each graded on the 0–8
  band scale, and CAM computes a recency-weighted suggestion per criterion.
  Optional school-specific roll-ups — an overall **MYP Grade (1–7)**, an
  **Effort / English-use** score, and a **School Grade (1–10)** via lookup
  tables — can be switched on in **⚙ Settings → Report-card grades** (all off by
  default, so a fresh install reports just the criterion grades).
- **Report-card comments.** Generate a per-student comment from the evidence,
  either by copying a ready-made prompt to your clipboard or — optionally —
  through the Claude or Gemini API. Comments are pronoun-aware and term-aware.
- **Grading workspace (sub-app).** An optional Flask companion app for marking
  student work synced from Google Classroom / a Google Drive (or OneDrive)
  folder: images and video (the original artwork use case), PDFs, and Google
  Docs — with a thumbnail-grid matching view and an anonymous grading mode. It
  also hosts **exam slicing**, which cuts a scanned exam PDF into per-student,
  per-question pieces for fast marking — handy for any teacher who sets exam
  papers, not just art teachers. Google Docs grading requires OAuth; pointed at
  a plain local folder (no OAuth) the workspace grades PDFs.
- **Calm, dense UI.** A three-window "cockpit" layout (roster → evidence →
  report) built on Streamlit, themed for long grading sessions.

## Screenshots & manual

See the illustrated **[User Manual](docs/USER_MANUAL.md)** for a walkthrough of
the three-window layout and the ingest → grade → report workflow.

## Quickstart

```bash
# 1. Install dependencies (Python 3.11+ recommended)
pip install -r requirements.txt

# 2. (Optional) regenerate the fictional sample gradebook
py tools/generate_sample_data.py

# 3. Launch the dashboard
py -m streamlit run app.py
```

The app opens in your browser and loads the bundled sample class so you can
click around immediately. Full instructions — including how to point CAM at your
own data folder and set up the optional Google Drive / AI integrations — are in
**[docs/SETUP.md](docs/SETUP.md)**.

## Sample data

`acm_database.json` in the repo root is invented demo data (8 fictional
students, one class). Real gradebooks are **never** stored in the repo — they
live in a local or cloud folder you point CAM at via
`local_device_prefs.json` → `db_custom_path` (see the setup guide). Re-run
`py tools/generate_sample_data.py` any time to reset the demo.

## Project layout

| Path | What it is |
|---|---|
| `app.py` | The Streamlit dashboard (the main app). |
| `engine/` | Framework-free core: models, ingestion, aggregation, persistence. |
| `cam_grading_workspace/` | Optional Flask grading companion (Google Drive sync, PDF exams). |
| `tools/generate_sample_data.py` | Rebuilds the fictional sample gradebook. |
| `docs/` | Architecture, data dictionary, setup, and the user manual. |

## Documentation

- [Setup guide](docs/SETUP.md) — install, run, connect your data and API keys.
- [User manual](docs/USER_MANUAL.md) — illustrated walkthrough of daily use.
- [Architecture](docs/ARCHITECTURE.md) — how the pieces fit together.
- [Data dictionary](docs/DATA_DICTIONARY.md) — the database schema.

## License

Released under the [MIT License](LICENSE).
