# Criterion Assessment Metrics (CAM)

Guidance for AI coding assistants (and humans) working in this repository.

## Keep real student data out of git

CAM operates on real student grades **at runtime**, but that data must never be
committed. The `acm_database.json` tracked in this repo is **fictional sample
data** (see `tools/generate_sample_data.py`). Real gradebooks and rosters live
**outside** the repo, in a local/cloud folder pointed to by
`local_device_prefs.json` → `db_custom_path` (both that file and any
`credentials.json` are git-ignored).

When adding features, preserve this separation: code and fictional sample data
in git; real data only ever on disk in the user's data folder.

## Safety rules for destructive operations

The database is a teacher's whole year of work. Treat writes to a **real**
database with care:

1. **Never overwrite, migrate, or delete a real database without explicit
   permission** in the current session. "Testing the app" is not permission.
2. **Sandbox test runs.** Before launching the app for any test, redirect the DB
   to a temp folder (temp prefs / temp `db_custom_path`) and confirm the run
   cannot resolve a real data folder. If isolation can't be guaranteed, don't
   launch — say so instead.
3. **Back up before approved writes.** Before any migration or bulk cleanup of a
   real database, create a timestamped backup beside it first
   (`acm_database.json.bak-<purpose>-YYYYMMDD-HHMMSS`). Never prune existing
   `.bak-*` files.

Why this matters: the persistence layer mirrors every in-memory change straight
to disk, and the app can auto-ingest CSVs on startup — so a careless test run
against a real data folder can silently destroy a term's grades. Sandboxing and
backups are what stand between a mistake and lost work.

## Layout

- `app.py` — the Streamlit dashboard (main app).
- `engine/` — framework-free core (models, ingestion, aggregation, persistence).
- `cam_grading_workspace/` — optional Flask grading companion.
- `docs/` — architecture, data dictionary, setup, user manual.
