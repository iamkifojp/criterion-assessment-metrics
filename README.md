# Criterion Assessment Metrics (CAM)

A desktop dashboard for **IB MYP Arts** teachers. CAM tracks each student's
criterion grades (A–D) across a whole school year, turns a term's worth of
evidence into a defensible grade suggestion, and drafts report-card comments —
so grading and reporting take minutes instead of evenings.

> **Note on data:** This repository ships with **fictional sample data only**.
> No real student information is included. See [Sample data](#sample-data).

---

## What it does

- **Multi-class gradebook.** One database holds every class you teach. Ingest
  grades from CSV exports; each score is stamped with a date so recent work can
  be weighted more heavily than older work.
- **Criterion-based aggregation.** MYP criteria A–D are each graded on the 0–8
  band scale. CAM computes a recency-weighted suggestion per criterion and rolls
  them up into an overall **MYP Grade (1–7)** and a configurable **School Grade
  (1–10)** via lookup tables.
- **Report-card comments.** Generate a per-student comment from the evidence,
  either by copying a ready-made prompt to your clipboard or — optionally —
  through the Claude or Gemini API. Comments are pronoun-aware and term-aware.
- **Grading workspace (sub-app).** An optional Flask companion app for grading
  student work synced from a Google Drive / OneDrive folder, including a
  thumbnail-grid matching view, an anonymous grading mode, and PDF exam slicing.
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
