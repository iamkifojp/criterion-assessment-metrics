# CAM — Architecture

Criterion Assessment Metrics (CAM) is a set of **three cooperating Python
programs** that share files on disk, not a single service. This document is the
technical source of truth for how those pieces fit together. It reflects the
code as it actually stands (verified against the repo), including a few places
where the folklore description and the implementation diverge — those are
called out inline as **⚠ Reality check**.

---

## 1. The three engines

| # | Engine | Entry point | Framework | Role |
|---|--------|-------------|-----------|------|
| 1 | **CAM (main app)** | `app.py` | **Streamlit** (`==1.58.0`) | Teacher-facing analytics: gradebook, recency-weighted suggestions, report cards, trend charts. |
| 2 | **CAM Grading Workspace** | `cam_grading_workspace/app.py` | **Flask** (`>=3.0`) | Fast per-assignment marking UI backed by Google Drive/Classroom **or a local class folder** (PDF/local-mode plan, no OAuth); also hosts Exam Slicing, which runs on local folders with no OAuth (§4). |
| 3 | **Backend engine (`engine/`)** | imported as a package | Pure Python (UI-free) | Domain model, CSV ingestion, aggregation math, DOCX parsing, JSON persistence, gojūon name collation. |

`main.py` is **not** a fourth app — it is a UI-free verification harness that
drives the `engine/` pipeline against the sample data (`Y7_Changing_View_Unit_Plan_v2.docx`,
`Changing Views (Crit B)_Grades.csv`) and prints results for sanity-checking
(`py main.py`). `app_broken_backup.py` is a stale snapshot of the Streamlit app,
retained as a backup and not part of the live system.

### How they talk to each other

There is **no network API between engines** — with one deliberate exception,
the launch bridge below. They are coupled through the filesystem:

```
   ┌─────────────────────┐        writes grades_*.json / grading_cache.json
   │ Flask Grading        │───────────────────────────────────────────────┐
   │ Workspace (engine 2) │                                                │
   └─────────┬───────────┘                                                 ▼
             │ OAuth (token.json)                             ┌───────────────────────┐
             ▼                                                │  Class master folders  │
     Google Drive / Classroom                                │  + per-class grading    │
                                                             │  CSVs on disk / OneDrive │
   ┌─────────────────────┐   os.scandir + os.walk over        └───────────┬────────────┘
   │ Streamlit CAM app    │◀──────────────────────────────────────────────┘
   │ (engine 1)           │   imports  ─────▶  engine/  (engine 3)
   └─────────────────────┘   persists ─────▶  acm_database.json
```

- The **Streamlit app imports the `engine/` package directly** (`from engine import …`)
  — engine 3 is a library, engine 1 is one of its front ends (exactly as
  `main.py`'s docstring anticipated).
- The Streamlit app reaches the Flask workspace's world **only through files**:
  it reads the workspace's saved OAuth token (`cam_grading_workspace/token.json`)
  to list Drive subfolders, and it syncs the grading CSVs that ultimately
  originate from marking sessions.

### The launch bridge (CAM → workspace)

Window 1's **Grade this Assignment/Exam** buttons call
`launch_grading_workspace()` / `launch_exam_setup()` (`app.py`). Each spawns
the Flask workspace on **port 5001** if it isn't already listening
(`_ensure_workspace_running()`), then opens a browser URL carrying the target
as query parameters (`class` / `assignment` / `aname`, or `class` / `exam`),
which the workspace's client-side `autoloadFromParams()` resolves into the
right class and assignment.

**⚠ The workspace is a separate process with its own dependencies.** It is
Flask + Pillow + PyMuPDF + the Google client libraries, pinned in
`cam_grading_workspace/requirements.txt`, which the **root `requirements.txt`
pulls in via `-r cam_grading_workspace/requirements.txt`** — so a single
`pip install -r requirements.txt` covers both processes. If a workspace
dependency is missing, `cam_grading_workspace/app.py` crashes on import and
never binds port 5001, so every handoff (Grade, Exam setup, 🔗 Connect Google
Drive) fails with a browser *"connection refused"*. `_ensure_workspace_running()`
guards against this: after spawning the sub-app it captures stdout/stderr to
`cam_grading_workspace/workspace_startup.log`, waits up to ~10 s for the port,
and — if it never opens — returns `False` and surfaces the log's last line
(usually the offending `ImportError`) in CAM's status banner, instead of
silently returning `True` and opening a dead browser tab. The PDF slicer's
`fitz` (PyMuPDF) import is also lazy (§4), so a missing PyMuPDF only breaks
exam slicing, not the whole workspace — including OAuth sign-in, which needs no
PDF handling.

**Process lifecycle — the workspace dies with CAM.** The sub-app is spawned
once (lazily, on the first handoff) and reused for the whole session: cold start
is ~6 s (Flask + Google libs + PyMuPDF + OAuth), so restarting it per assignment
would be a visible drag — it is deliberately kept warm rather than idle-exited.
To stop it outliving CAM as an orphan (it is windowless, and Windows does not
kill `Popen` children with the parent), `_bind_workspace_to_cam()` ties its
lifetime to CAM's two ways: an `atexit` handler for graceful shutdown, and a
Windows **Job Object** with `KILL_ON_JOB_CLOSE` for hard kills where `atexit`
never runs. Consequences worth knowing: CGW runs `debug=False` with no
auto-reloader, so **editing `cam_grading_workspace/app.py` has no effect until
the process restarts** (a full CAM restart now does that); and a pre-existing
orphan already on 5001 when CAM starts is not adopted (CAM did not spawn it, so
it holds no handle to it) and must be killed by hand.

The two apps keep **separate class registries**: CAM stores each class's
master directory (`master_dir`, a local path *or* a Drive folder ID) in
`acm_database.json`, while the workspace keeps its own class → Drive-folder-ID
map in `gcg_settings.json` (`SETTINGS["classes"]`). URL parameters alone can't
cross that gap — the autoloader bails on any class name missing from the
workspace's map. So before opening the URL, both launchers call
`_seed_workspace_class()` (`app.py`), which `GET`s `/api/config`, builds a
minimal patch, and `POST`s it back. It seeds **two** things:

1. **The active class's `name → folder-ID` pair** into `SETTINGS["classes"]`
   (other classes untouched; re-seeding the same pair is a no-op). Drive-backed
   classes only — a local-path master directory is never mapped.
2. **`cloud_dir` = CAM's database folder** (`db_folder()`), so the workspace's
   grade/exam CSV exports route into the per-class subfolder CAM's Sync scans
   (§8). Seeded only when CAM has a custom database path configured; the patch
   is skipped when the workspace already points at the same folder
   (normcase-normalised compare). **This is what closes the round-trip** —
   without it the workspace falls back to its own app root and exports never
   reach CAM.

Going through the workspace's own endpoint — rather than editing
`gcg_settings.json` directly — updates the *running* server's in-memory
`SETTINGS` and persists through its `save_settings()` (root file + cloud
mirror), so the seeded state is durable.

A folder-grading handoff does two more things after seeding. First (Sync/
anonymous plan Phase 1) it **scoped-syncs the target assignment** —
`sync_assignment()` ingests any fresher export sitting on disk *before* CAM
publishes, closing the stale-handoff race where CAM would otherwise publish
values older than the CSV and lose the teacher's newer marks (§8; plan Terrain
§T4). A duplicate-dated group or a parse failure here **cancels the launch**
with the banner, same as a publish failure. Then `_publish_workspace_grades()`
writes CAM's (now-current) grades for the target assignment into the class
folder (`cam_grades_<folderId>.json`), so the workspace opens on CAM's latest
values instead of its own last session. This is the forward half of the grades
round-trip — see §8. A publish failure cancels the launch (a workspace session
that can't see CAM's edits would overwrite them on its next export). A
successful folder launch also records a session-only **active-launch marker**
so the post-session probe can auto-ingest the return export (§8). Exam handoffs
skip all of this: exams don't round-trip through folder grading.

**⚠ The workspace ⚙ Settings is read-only for the CAM-managed fields.** Because
CAM owns `cloud_dir` and the class map, the workspace's Settings dialog displays
them but no longer lets a teacher edit them (no *Save Settings*, *+ Add class*,
*Refresh Classes*, rename, or delete). This removes the failure mode where a
manual edit in the workspace silently misrouted exports or created a class the
dashboard didn't know about. Editable in the dialog are only the fields the
workspace owns: the device-local **Theme**, **Anonymous grading**, and the
**cloud-sign-in seed** toggle (§Phase 5), plus **My identities** — the one
CAM-independent piece of shared config, saved through `POST /api/config` and
mirrored to the cloud so it heals across machines (below). The
`/api/config/refresh` / `/api/config/rename_class` endpoints still exist (CAM's
seeding uses `POST /api/config`); only the workspace's UI controls for the
CAM-owned fields were withdrawn.

**Identities + credentials heal from the cloud (safety plan Phase 5).** A new
machine reaches a working CGW from the shared OneDrive/Drive folder alone:
`gcg_settings.json` now carries `my_identities` alongside the class map (root +
cloud mirror), and `load_settings()` takes the **union** of root and cloud copies
— an identity's *absence* misfiles the teacher's own uploads under a student, so
the allowlist is never narrowed by a sync. `my_identities()` merges the empty
public default + settings + device-local prefs, de-duped case-insensitively.
`find_client_secret()` probes `<cloud_dir>` after the app root, so
`credentials.json` can live in the private cloud folder. An **opt-in**,
one-way `token.json` bootstrap (device pref `token_bootstrap`, default off) seeds
an absent local token from `<cloud_dir>/token.json` on the next sign-in; refreshes
still write locally only — the token is never mirrored back.

**Local-path master directories round-trip end-to-end (PDF/local-mode plan
Phase 4).** Folder grading is no longer Drive-only. The class-folder *browser*
`/api/class` enumerates a **local class-master path** off disk (`local_subfolders()`,
chosen by the `_ref_is_local` seam) as readily as it lists a Drive folder's
subfolders through the Drive API, and `_seed_workspace_class()` seeds a
local-master class into the workspace's class map, so `launch_grading_workspace()`
drives it straight into CGW — no OAuth, no refusal. `POST /api/load` has accepted
a **local assignment-folder path** since **Phase 3** (`LocalProvider`,
storage-provider seam §H of the plan's Terrain notes), grading PDFs + images with
the identical marking viewer and CSV export; Phase 4 wires the CAM *Grade* button
to reach it and keys the `cam_grades_<key>.json` handoff by the same durable
`local-<hash>` slug (`_workspace_state_key()` ↔ `LocalProvider.state_key`) so the
publish→reconcile→export→Sync round-trip works for local classes too. **Exams are exempt by design:** the whole exam
pipeline (setup, question programming, slicing, grading, export) is keyed on
`class_name` and runs on local folders with no OAuth, so `exam::<name>`
launches and `launch_exam_setup()` always proceed; for them the seeding is
best-effort and a local or unset master directory is normal, not an error.
On the workspace side, `autoloadFromParams()` mirrors the split: a class
missing from `SETTINGS["classes"]` gets its locally-stored exams listed
(`/api/exams`) and the matching one opened; only folder targets fall back to
the "add it in ⚙ Settings" hint.

### Running them

| Engine | Command | Port |
|--------|---------|------|
| Streamlit CAM | `py -m streamlit run app.py --server.headless true --server.port 8600` (see `.claude/launch.json`, name `acm`) | 8600 |
| Flask Workspace | `python cam_grading_workspace/app.py` | Flask default (see that module) |

---

## 2. Streamlit layout logic vs. Flask workspace data separation

This is the central design split, and the two halves have **deliberately
different data models.**

### Streamlit side — layout & analytics (`app.py`)

- Single-process Streamlit app; `st.set_page_config(page_title="Criterion
  Assessment Metrics", layout="wide")` at `app.py:4049`.
- State lives in `st.session_state` (the `Gradebook`, ingested-file registry,
  prefs) and is persisted to **`acm_database.json`** via `engine/persistence.py`.
- The unit of organisation is the **term → class → assignment → criterion score**
  hierarchy from `engine/models.py`. Scores are MYP **0–8 bands**.
- **Terminology:** the 0–8 per-criterion score is called *band* internally
  (`rounded_band`, `MIN_BAND`, `_render_exam_banding`, …) but is presented to
  users and to the LLM as **"grade"** — every rendered/prompt string was swept
  band → grade (2026-07-08); the identifiers are unchanged. The IB **1–7**
  result is the **"final grade"**. Where both appear together, disambiguate as
  "grade (0–8)" vs "final grade (1–7)".
- Its job is *reading and presenting*: recency-weighted grade suggestions,
  inclusion toggles, trend charts, report cards.

**⚠ Invariant: the boot load-guard never runs demo state onto a real DB.** The
persistence layer mirrors every in-memory change straight to disk, so if the
app booted the demo gradebook while *pointed at* a real (but momentarily
unreadable) database, the next autosave would overwrite a year of grades. The
guard closes that hole. At boot, `diagnose_db_load(db_path())` (`app.py`)
classifies the configured path via `db_file_state()` (`engine/persistence.py`,
which distinguishes **absent / ok / unreadable** — a distinction the plain
`load_database` `None` contract hides) and refuses to proceed silently when the
file **exists but is unreadable/malformed**, when it **parses but yields no
students/assignments despite carrying real bytes** (`> EMPTY_DB_MAX_BYTES`), or
when it is **absent and its parent folder/volume is itself missing** (an
unplugged drive, an unmounted cloud folder, a disconnected share — *not* a first
run). Any of these sets `st.session_state["db_load_blocked"] = {reason, path}`;
`persist()` then refuses every write and a full-width **read-only quarantine**
banner names the path and the fix (restart after repairing the file/path). Only
an **absent file inside an existing folder** is treated as a legitimate first
run (start empty, create on first save). This is wipe-mechanism 2 in
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

**⚠ Invariant: repointing the database path adopts an existing DB, never
overwrites it.** In **⚙ Settings**, Save writes the device prefs but only calls
`persist()` when it is safe to: for an **unchanged** path (a layout-only Save) or
a **new location with no database** there. When Save changes `db_custom_path` to
a location that **already holds a readable** `acm_database.json`, the settings
form is replaced by an adopt-vs-overwrite panel (`_render_db_switch_panel`,
gated by `st.session_state["db_switch_pending"]`) showing the target file's
assignment/roster/class counts (`_db_file_counts`). **Load** (the default)
clears `db_loaded` and re-runs the boot hydrate so the session *becomes* the
existing database — nothing on disk is written; **Replace** is explicit,
checkbox-gated, and snapshots the target to
`acm_database.json.bak-replaced-<ts>` (`_backup_replaced_db`) before persisting.
**The new `db_custom_path` pref is committed only on Load / Replace** — while
the panel is pending, and if it is dismissed with Cancel or **ESC**, the active
pref stays on the old location (`resolve_db_path()` is a pure resolver so the
*candidate* path can be inspected without moving the pref). Committing the pref
at Save time instead would let an ESC-dismissed panel leave the demo session
pointed at the existing DB, and the next autosave would overwrite it. This is
wipe-mechanism 1 in
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md); with
the Phase-1 boot guard it closes the two paths by which the demo session could
clobber a real database.

**⚠ Invariant: `persist()` refuses a catastrophic mass-loss write (shrink
tripwire) and keeps rotating daily backups.** The last line of defence behind the
two wipe-mechanism guards above: whatever future code path produces a
mass-reducing write, it cannot destroy the only copy. Before each save,
`persist()` (`app.py`) compares a cheap structural **mass** —
`assignments + roster entries + scored students`, read from the file already on
disk via `_ondisk_mass()` (raw JSON, no engine objects, so it is light enough to
run on every autosave) — against the outgoing session (`_outgoing_mass()`). When
the on-disk DB has real substance (`≥ SHRINK_MIN_ASSIGNMENTS`, currently 10) and
the outgoing mass would fall below `SHRINK_KEEP_RATIO` (0.33) of it, the write is
**refused**: the outgoing payload is parked as `acm_database.json.blocked-<ts>`
for inspection and the same `db_load_blocked` read-only quarantine banner is
raised (reason `"shrink-blocked"`). The threshold is deliberately generous —
deleting one class of several still clears it (`delete_class()` uses a plain
`persist()` and passes), while flattening every class to the demo gradebook does
not. Two **deliberate, typed-confirmed** reductions bypass it with
`persist(allow_shrink=True)`: the Danger-zone **Wipe entire database**
(`wipe_database_full()`) and the Phase-2 **Replace** (already checkbox-gated and
`.bak-replaced-` backed-up). Independently, the **first** `persist()` of each
calendar day snapshots the existing on-disk DB to `acm_database.json.bak-auto-
<YYYYMMDD>` *before* it is overwritten (`_rotate_daily_backup()`), pruned to the
newest `AUTO_BACKUP_KEEP` (7) — so any future incident is at most a one-day loss
even without OneDrive version history. Pruning only ever removes `.bak-auto-*`;
manual `.bak-replaced-*` / `.bak-<purpose>-*` snapshots are never touched. This is
Phase 3 in
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

**⚠ A new computer bootstraps to the shared database without ever wiping it.** A
machine that has not chosen a data home — no `CAM_DB_PATH`, a **blank**
`db_custom_path`, and the one-time `setup_done` pref unset (`_needs_first_boot_setup()`,
`app.py`) — gets the first-boot **setup panel** (`_render_first_boot_setup()`)
*instead of* the cockpit: `init_state()` **defers the boot hydrate** and `main()`
returns before any class/term context, sync, dedupe or autosave runs, so nothing
(not even the sample DB) is loaded or persisted before the teacher picks. The
panel offers **discovered databases** (a shallow, depth-≤3, system-dir-pruned
walk of the local OneDrive / Google Drive / Dropbox roots — `discover_db_candidates()`
via `_cloud_search_roots()` + `_scan_for_db_files()` — each shown with its
`_db_file_counts`), a **manual folder/path**, and an explicit **Start fresh**.
Every choice routes through `_adopt_db_path()`, which writes the pref + `setup_done`
and clears `db_loaded` so the hydrate re-runs on the **Phase-2 adopt path**: an
existing database at the chosen location is **loaded, never overwritten**; an
absent one is created on first save. Removable/USB roots are deliberately **not**
auto-scanned (the teacher points at them once via *Use another folder*; Phase 1's
storage-missing quarantine covers a forgotten drive on every later boot). The
**`CAM_DB_PATH`** environment variable overrides the pref in `db_path()` and skips
the panel entirely — a one-liner new-machine setup and the sandbox handle that
lets tests/harnesses force a path which **cannot** fall through to the real device
prefs (closing the `.wiped-by-test` hazard class). Watch folders need no transfer
mechanism: a class's `master_dir` / assignment `folder_ref` are Drive IDs in the
**shared** database (machine-independent), so Drive-backed classes travel with the
DB automatically; a **local-path** master is per-machine by nature and uses the
existing re-link flow (**✎ Add / Edit class**). Layout prefs stay per-device by
design. This is Phase 4 in
[CROSS_DEVICE_AND_DB_SAFETY_PLAN.md](CROSS_DEVICE_AND_DB_SAFETY_PLAN.md).

**⚠ The class *name* is a primary key, spread across many stores.** A class is
identified by its name string, and that same string keys: the class entry in
`classes`, `rosters`, `archived_students`, `unit_plans`, every assignment's
`class_name`, the cloud-sync registry rows (`ingested_files[*]["class"]`), the
`active_class` pointer, and the on-disk data folder (`class_data_dir`). Any
lifecycle operation must move *all* of them together or something is orphaned —
this is why `delete_class()` and `rename_class()` each touch the full set. A new
class-scoped store added later must be wired into both. (Term summaries, exam
scans and grading exports live under the data folder, which is why rename moves
the folder too.) The whole class lifecycle lives in one top-bar dialog,
**✎ Add / Edit class**: a red two-button toggle switches between *Edit current
class* (the default on open — `update_class()` wraps `rename_class()` plus the
descriptive fields: grade level, MYP year, subject, master directory; also
hosts **👁 Watch** and **🔗 Connect Google Drive**) and *Add a class*
(`create_class()`); both modes share one form body (`_class_dialog_body`).
Saving a **new or changed master directory runs a Watch pass automatically in
either mode** — pasting a folder into a brand-new class and onto an existing,
already-graded one behave identically (safe because Watch *adopts* same-name
manual rows instead of duplicating them, §8; the 👁 Watch button remains for
rescans). The Drive sign-in button is offered in both modes (§3).

### Flask side — marking & Drive data (`cam_grading_workspace/app.py`)

- A Flask app (`app = Flask(__name__)` at `cam_grading_workspace/app.py:74`) with
  a JSON REST surface (`/api/load`, `/api/save`, `/api/save_state`,
  `/api/group/link`, `/api/exam/*`, …).
- In-memory `STATE` dict guarded by `STATE_LOCK` (`threading.Lock`); persisted by
  `save_state()`, which writes **both** a per-folder `grades_<folderId>.json`
  **and** the shared multi-folder `grading_cache.json` (`write_cache()`).
- The unit of organisation is the **assignment folder** (one folder = one
  assignment) — a Google Drive folder keyed by Drive folder ID, or a **local
  folder** keyed by a durable `local-<hash>` slug (PDF/local-mode plan). Grades
  here are stored as **strings**
  keyed by criterion, plus keyword checkboxes and free-text comments — the raw
  marking artefact, not the analytical model.

**Separation of concerns:** the Flask workspace owns *how a teacher marks a pile
of student work fast* (Drive thumbnails, checklists, pair-work groups); the
Streamlit app owns *what those marks mean over a term* — and holds the **one
authoritative copy of the grades**. Grading *data* flows only through files,
in both directions: CAM → workspace as the handoff-published
`cam_grades_<folderId>.json` (CAM's current bands, consumed by the workspace
on load — §8), workspace → CAM as the CSV export picked up by Sync. The sole
direct call is the launch bridge's `/api/config` seeding (§1), which carries
configuration, not grades.

For the exact field-level schema of `grading_cache.json` and the ingestion CSV,
see [DATA_DICTIONARY.md](DATA_DICTIONARY.md).

---

## 3. Local directory scanning (`os.scandir`) and the Google-credential boundary

**⚠ Reality check on "scanning without Google credentials":** the Streamlit app
does both — the credential requirement depends on whether the target is a *local
path* or a *Drive folder ID*. `os.scandir` is used specifically on the local
branch; Drive uses OAuth.

Two `os.scandir` sites in `app.py`, both credential-free by design:

1. **Class-master watch** — `_watch_class_master()` (`app.py:745`). If the
   configured reference is a local path (`_master_is_local()`), it enumerates
   subfolders with:
   ```python
   subs = [(e.name, os.path.abspath(e.path))
           for e in sorted(os.scandir(ref), key=lambda e: e.name)
           if e.is_dir()]
   ```
   Each subfolder becomes an Assignment/Exam row, pinned by `folder_ref` so
   re-watching is idempotent (no duplicate rows even after a rename).
   **Only if the reference is *not* local** does it fall through to
   `_drive_list_subfolders()` (`app.py:704`), which loads
   `cam_grading_workspace/token.json` and calls the Drive v3 API. That path
   raises a teacher-readable `RuntimeError` when no token / no Google packages
   are present.

2. **Database sync** — `sync_from_cloud()` (`app.py`, wrapped by `sync_all()`)
   walks the custom database folder purely locally: each immediate subfolder is
   treated as a class, then `os.walk` recurses for `*.csv` grading files. Files
   are fingerprinted (hash + mtime) so unchanged CSVs are skipped on the next
   sync. No Google credentials are involved anywhere in this path. Since the
   Sync/anonymous plan Phase 1 this global scan is no longer a button: it runs
   **once per session automatically** (`_run_session_start_sync`, the
   OneDrive/multi-machine catch-up) and remains available as **⚙ Settings →
   Force full re-scan**; the everyday path is now the assignment-scoped
   `sync_assignment()` fired at grading launch and by the post-session probe
   (§8). See §8 for the full export→ingest round-trip.

The Flask workspace, by contrast, is Drive-first: it uses `os.listdir`
(not `scandir`) for local cloud-mirror directories and `googleapiclient` for
everything else, authenticated via `token.json` obtained through
`InstalledAppFlow` (`google_auth_oauthlib`).

### Sign-in bootstrap (`/signin`)

Obtaining that token used to be circular: `_drive_list_subfolders()` needs
`token.json`, the token is only written by the workspace's OAuth flow, and the
only buttons that launched the workspace lived on assignment rows — rows that
Watch (which needs the token) creates. The workspace therefore exposes a
`GET /signin` route that calls `get_credentials()` directly, running the
`InstalledAppFlow` and writing `token.json` with no assignment involved.
The **✎ Add / Edit class** dialog (top bar) pairs it with a **🔗 Connect
Google Drive** button (`launch_drive_signin()`) that starts the workspace and
opens the route in the browser. The token is device-wide, not class-specific,
so the button appears in *both* modes: always in Add mode (a first-time user
can sign in before creating their first Drive-backed class), and in Edit mode
whenever the saved master directory is a Drive ID (per `_master_is_local()`).
`credentials.json` — the OAuth client secret, type
"Desktop app" — remains a prerequisite; when it is absent, `/signin` renders a
guidance page pointing at the Google Cloud Console instead of raising.

**Takeaway:** local scanning = `os.scandir`/`os.walk`, no credentials. Drive
scanning = OAuth token required. The two are chosen at runtime by inspecting
whether the stored reference looks like a filesystem path or a Drive ID.

---

## 4. Exam Slicing — auto-DPI cropping (Pillow + PyMuPDF)

Implemented in `cam_grading_workspace/exam_engine.py`, exposed through the Flask
`/api/exam/*` routes. It turns a folder of scanned student exam files into
per-question crop images so one question can be graded across the whole class.

**Lazy `fitz` import.** PDF pages are rasterised with PyMuPDF (`fitz`), but the
module imports it lazily through `_fitz()` rather than at top level, so
`exam_engine` — and therefore the whole Flask workspace that imports it at
startup — still boots when PyMuPDF is absent. Only the two PDF paths
(`page_count`, `load_page_image`) then fail, with a `RuntimeError` that names
the fix (`pip install PyMuPDF`); image-only exams and every non-PDF feature
(including Google Drive sign-in) are unaffected.

**No Google account required.** Like local-master folder grading (§1), the
entire exam path is local-first: definitions live in `gcg_exams.json` keyed by
*class name* (not Drive ID), the source is a local folder of student
PDFs/images (`scan_folder`/`preview` gate on `os.path.isdir`), crops go to
`exam_crops/<class>/`, and `/api/exam/load` / `/api/exam/grade` / the CSV
export never touch `googleapiclient`. Drive is purely optional — a teacher
who stores papers on Drive syncs them to a local folder first. This is why a
CAM class with a local-path (or unset) master directory can still launch Exam
Setup and grade its exams through the CAM bridge, while assignment folder
grading demands a Drive folder ID.

**Slicing is a background job (since PDF/local-mode plan Phase 6).**
`POST /api/exam/process` validates the folder, saves the config, then hands the
slicing to a daemon `threading.Thread` (`_run_exam_job` → `process_exam(...,
progress=…)`) and returns a `job_id` immediately — so a large stack can no
longer block the request thread into a browser gateway timeout. The front end
polls `GET /api/exam/status/<job_id>`, which reports `state`
(`running`/`done`/`error`), a `done`/`total` student counter, and the final
`result` summary. Jobs live in the in-memory `EXAM_JOBS` registry (guarded by
`EXAM_JOBS_LOCK`, independent of `STATE_LOCK` because slicing only touches the
filesystem, never `STATE`); they are not persisted, so a restart forgets them.
The exam *definition* JSON store's own `threading.Lock` (in `exam_engine.py`) is
a separate mechanism, as is the **background autosave cache** (`write_cache()` →
`grading_cache.json`) that mirrors marking state on every edit.

### The grid coordinate system

A teacher programs an exam once (`/exam_setup`): each question is a label
(`"Q1"`), a grid range (`"page2!A2:C5"`) and a max score. The grid is a
paper-size-dependent lattice laid over the physical page, tuned so each cell is
~2 cm × 2 cm of real paper:

| Paper | Physical (mm, portrait) | Grid (cols × rows) | Columns |
|-------|------------------------|--------------------|---------|
| A4    | 210 × 297              | 10 × 15            | A–J     |
| B5    | 176 × 250              | 9 × 12             | A–I     |
| A3    | 297 × 420              | 15 × 21            | A–O     |

Because a range describes a rectangle of *paper*, it is independent of scan
resolution. `parse_range()` validates the cell against the chosen paper's grid
and raises a clear `ValueError` on anything out of bounds.

### Auto-DPI

Scans arrive at unknown resolutions, so the pixel size of one grid cell is
derived **per file, per axis**:

```
dpi   = pixel_span / (paper_mm / 25.4)
cell  = (paper_mm / grid_count) / 25.4 * dpi
```

`range_to_bbox()` computes `dpi_x` and `dpi_y` independently from the image's
actual pixel width/height, so a slightly stretched scan still lands on the right
region. The resulting bounding box is clamped to the image bounds.

### Rasterisation vs. cropping — which library does what

- **PyMuPDF (`fitz`, `>=1.24`)** rasterises PDF pages at a fixed `RENDER_DPI = 200`
  (`load_page_image()` → `doc[…].get_pixmap(dpi=RENDER_DPI)`). Render DPI only
  affects quality; crop geometry comes from the auto-DPI formula above.
- **Pillow (`>=10.0`)** owns the image side: single-image exam pages are opened
  directly with `Image.open(...).convert("RGB")`, crops are taken with
  `img.crop(box)`, and browser previews are downscaled with `Image.LANCZOS`.

Crops are written to
`<output_root>/<Exam Name>/<Q label>/<Student>.png`. The filename **stem is the
student identity** (one file per student, named after the student). Per-crop
failures are collected into `summary["errors"]` so one bad file doesn't abort
the whole class.

Exam definitions persist to `gcg_exams.json` (keyed by class name); exam grades
persist to `exam_grades_<exam>.json` in the class output directory. Both writes
are atomic (`.tmp` + `os.replace`).

---

## 5. Charting — matplotlib (Agg), kaleido banned

Report-card and cockpit trend charts render through **matplotlib** with the
headless **Agg** backend (`app.py:1804` — `matplotlib.use("Agg")` before
`import matplotlib.pyplot as plt`), producing PNG bytes in milliseconds.

This deliberately replaced the old Plotly `fig.to_image` path, which required
**kaleido** — the Chromium-based 1.x releases hung for minutes and cropped the
bottom of the chart. **kaleido must not be reintroduced** (`requirements.txt`
carries an explicit "do NOT install kaleido" note, and matplotlib is pinned
`>=3.8` for this purpose). Plotly is still present (`>=5.20`) for *interactive*
in-app figures; matplotlib is exclusively the *static export* path.

---

## 6. Tech-stack summary

**Streamlit app (`requirements.txt`):** `streamlit==1.58.0`, `plotly>=5.20`,
`matplotlib>=3.8`, `openpyxl>=3.1`, `python-docx>=1.1.0`. Optional AI "API call"
mode: `anthropic>=0.39` (Claude), `google-genai>=0.3` (Gemini) — clipboard mode
works without them.

**Flask workspace (`cam_grading_workspace/requirements.txt`):** `Flask>=3.0`,
`google-api-python-client>=2.100`, `google-auth>=2.30`,
`google-auth-oauthlib>=1.2`, plus Exam Slicing's `Pillow>=10.0` and
`PyMuPDF>=1.24`.

**Backend engine:** standard library only (`csv`, `json`, `datetime`,
`dataclasses`) plus `python-docx` for unit-plan parsing.

---

## 7. On-disk artefacts (quick map)

| File / dir | Owner | Purpose |
|------------|-------|---------|
| `acm_database.json` | Streamlit | Serialized `Gradebook` (the analytical DB). |
| `grading_cache.json` | Flask | Multi-folder marking mirror (see DATA_DICTIONARY). |
| `grades_<folderId>.json` | Flask | Per-assignment full `STATE` snapshot. |
| `gcg_exams.json` | Flask/exam_engine | Exam definitions, keyed by class. |
| `exam_grades_<exam>.json` | Flask/exam_engine | Per-exam question scores. |
| `cam_grades_<folderId>.json` | Streamlit writes, Flask consumes | CAM's current grades for one folder-backed assignment, published at handoff into `[db folder]/[class]/`; deleted by the workspace once merged (§8). |
| `token.json`, `client_secret_*.json` | Flask | Google OAuth material (read by Streamlit for Drive listing). `find_client_secret()` also probes `<cloud_dir>` after the app root; `token.json` may be opt-in seeded from `<cloud_dir>` (Phase 5). |
| `gcg_settings.json` | Flask; `cloud_dir` + class map are **CAM-managed** (seeded by the launch bridge via `POST /api/config`, read-only in the workspace). `my_identities` is workspace-owned and editable in Settings. | Cloud-sync dir + class → Drive-folder-ID map + the teacher's own identities. Mirrored into `<cloud_dir>` so identities heal across machines (Phase 5). |
| `local_device_prefs.json` | both (each app keeps its own copy beside its `app.py`) | Device-local UI prefs, never the shared cloud DB. CAM: db path + column widths / scroll heights. CGW: the `anonymous_grading` toggle (§8), the opt-in `token_bootstrap` toggle (Phase 5), and any `my_identities` override. Writers merge, so unknown keys are preserved. |

---

## 8. The grades round-trip (CAM ⇄ workspace)

Grading data leaves the workspace as a **CSV export** and re-enters CAM through
its **sync passes** — automatic since the Sync/anonymous plan Phase 1: an
assignment-scoped `sync_assignment()` at grading launch (§1) and via the
post-session probe, a once-per-session global `sync_all()` at startup, and a
manual **⚙ Settings → Force full re-scan** escape hatch (the old universal 🔄
button is retired). Grading also flows *back* into the workspace at every
handoff. **CAM is the single source of truth**:
whatever it currently holds is, by definition, the latest value the teacher
entered anywhere, and the workspace is brought up to date with it before any
new marking happens. This section documents both halves and the invariants
that keep them from corrupting the timeline.

### CAM → workspace: publish and reconcile

1. **Publish at handoff.** `launch_grading_workspace()` (after
   `_seed_workspace_class`) calls `_publish_workspace_grades()` (`app.py`),
   which writes `cam_grades_<folderId>.json` into `[db folder]/[class]/`:
   CAM's current per-student, per-criterion 0–8 bands + comments for the
   target assignment, keyed by the email-derived student id. Skipped when no
   custom database path is set (no `cloud_dir` routing → no round-trip) and
   for exam targets. A write failure **cancels the launch** — a session blind
   to CAM's edits would clobber them on export. **Alias reverse-map (Phase 3):**
   a student whose scores arrived through a `work_aliases` match is graded in
   CAM under the roster id, but CGW knows that work only by its anonymous
   csv_key (its reconcile computes the work's key as
   `student_id_from_email(email) or name` — for a local/unmatched work, the
   csv_key). So the publish additionally mirrors each aliased student's entry
   under the csv_key, and CGW's reconcile lands on the right work; the roster-id
   key is kept too (harmless — routes to `cam_extra` if no work matches).
2. **Reconcile on load.** The workspace's `api_load` reads the file and
   compares each published band against its own saved state
   (`grades_<id>.json` / `grading_cache.json` — its last-export baseline).
   A differing band was changed in CAM since the last export: the value (and
   any CAM-edited comment) is adopted, and the student is flagged
   **MODIFIED** for those criteria — a loud marker before the work's grades
   in the split-screen, plus an instruction above the checklist to re-check
   it (CAM carries only the final band, not the checklist detail behind it).
   Markers persist across reloads (saved in the cache) until the teacher
   clicks one to dismiss it or exports. CAM-graded students with **no files
   in the folder** can't be shown, so they land in the entry's `cam_extra`
   bucket instead — held solely so exports keep carrying them.
3. **Consume.** Once the merged state is persisted, the published file is
   **deleted**. This is deliberate: the values now live in the workspace's
   own state, and a leftover copy re-read after a later grading session
   would overwrite newer marks with stale ones. CAM rewrites the file fresh
   on every handoff.
4. **Export the full snapshot.** `api_export` therefore writes CAM's carried-
   forward values + the teacher's new re-grades, widens the criterion columns
   to every band actually held (nothing held is ever dropped), and appends
   rows for the `cam_extra` students. A successful routed export clears the
   MODIFIED markers — the snapshot is the new shared baseline.

**Why this makes purge-replace safe:** Sync ingests an assignment by wiping
its prior record + scores and re-reading the whole CSV (below). That used to
be lossy — a workspace session started from *its own* stale state, so its
full-class export silently reverted any student CAM had edited since. Now
every export is a superset built on CAM's latest, so replacing the whole
assignment with it loses nothing.

**Local-master classes round-trip too (PDF/local-mode plan Phase 4).** The
publish step keys `cam_grades_<key>.json` by the workspace's durable state key —
a Drive ID unchanged, or the `local-<hash>` slug `_workspace_state_key()` shares
with `LocalProvider.state_key` — so a local assignment's grades reconcile
(MODIFIED markers), export, and Sync exactly as a Drive assignment's do. The
export is the same `<name>_Grades_<date>.csv` in the class's data folder, so the
late-flag integrity machinery (§8 invariants, keyed on the filename) applies with
no local-specific code.

**Anonymous grading is a display-only layer, orthogonal to the round-trip
(Sync/anonymous plan Phase 2).** An opt-in per-device toggle (⚙ Settings,
persisted in `local_device_prefs.json`, default off) hides student identity from
the marking viewer. When on, CGW's payload builder (`present_students()` /
`present_student()`) returns *copies* of the student dicts with only the display
strings replaced — `name`/`display_id` → `Work NN`, `email` blanked,
`filename` → `Image 1`/`Document 2` — and orders students by a
`random.Random(state_key)` shuffle instead of alphabetically (stable per
assignment, uncorrelated with names). It **never** touches the round-trip
identifiers (`key`, file `id`, `web_view`, grades keyed by `key`) or `STATE`
itself, and `api_export` reads `STATE` directly, so the exported CSV's
`Student Name` / `Files (newest first)` cells stay **real** — Window 2 matching
still keys on them and the export is byte-identical whether the toggle is on or
off. Anonymity is bias-reduction, not blind review: the `key` still embeds the
real id and the "↗ open" link still serves the real file.

### "Awaiting Grade" — a two-state rule on folder-backed work

Window 3 shows every active assignment as editable mark(s) when scores exist.
When the focused student has **no score**, a folder-backed assignment
(`folder_ref` set) is read in one of **two states**, decided by the
assignment's `grading_complete` flag, while a criteria-bearing *non-folder*
task that simply wasn't submitted always shows the editable **0 (missing)**
rows:

- **Not complete → Awaiting Grade.** A read-only **⏳ Awaiting Grade** chip.
  The folder is still being graded, so the work contributes **nothing** to the
  trend, the grade math or the AI prompt — no invented 0. Its grades arrive
  through the round-trip above.
- **Complete → Missing = 0.** The student falls through to the *same* Missing =
  0 policy a non-folder task uses: one editable **"0 (missing)"** row per
  criterion (click to open `edit_grade_dialog` and enter a mark or tick
  Excused), and a **real mathematical 0** injected into the trend, the grade
  calculations and the AI prompt until the teacher acts. The physical zero is a
  deliberate product decision — implemented identically to existing missing
  rows, no softer variant — so unsubmitted folder work is noticed quickly and
  the teacher either excuses the student (mid-year transfer, approved absence)
  or chases the work. Excused students leave the math entirely, as always.

**The single gate.** `awaiting_grade(row)` — `folder_ref set AND NOT
grading_complete` — is the one predicate, used at all four sites so the rule
can never drift: `missing_assignment_rows()` (the gate for the trend, grade
math and AI prompt), the Window 3 cockpit rows, the report export's marks
table, and Window 2's missing-work ⚠ popover. A fifth consumer reads the same
gate: the AI prompt's toggleable **`[MISSING WORK]`** block (`inc_missing`,
default on) surfaces the missing *count* explicitly — `X of Y assessed tasks
(Z%)` plus the unsubmitted names — via `_missing_work_stats()`, which is just
`missing_assignment_rows()` for the numerator and that count plus the submitted
count for the denominator. Because it shares the one gate, it inherits every
exclusion for free; it is not a second notion of "missing".

**Batch AI comments skip students who already have one.** "Generate for whole
class" (`_generate_class_comments`) defaults to leaving any student who already
holds a non-empty overall comment for the current term untouched — controlled by
the default-on `skip_existing` flag in the LLM parameters dialog — so a re-run
after a partial or quota-limited run fills only the gaps rather than redoing (and
possibly overwriting) work that already succeeded. Because a hand-typed and a
generated comment both live in the same `comments_by_term` store, they are
indistinguishable here and one "already has a non-empty comment?" check covers
both. The status banner reports the skipped count; unchecking the toggle restores
the old regenerate-everyone behaviour, and the single-student generate button is
never affected.

**⚠ Reality check — per-student cockpit widgets must carry student-scoped
keys.** Streamlit caches a keyed widget's value in `session_state` and ignores
its `value=` argument on every rerun after the first, so a Window 3 text area
that shows per-student content under a *static* key freezes on the first
focused student's text and only recovers on a full page refresh (and its
write-back guard could persist one student's comment into another's record).
The Overall comment box is therefore keyed per student **and** term
(`resp_box_{sid}_{term}` — `llm_response` is a per-term alias re-pointed by
`ensure_term_context()`), the Remarks box per student (`rem_box_{sid}`), and the
read-only Comments log carries **no** key at all (like the compiled-prompt box)
so `value=` drives it every run. Because the height-override CSS derives its
selector from the widget key, it matches key *prefixes*
(`[class*="st-key-resp_box"]`) rather than the exact class.

**How `grading_complete` is computed — the read-only completeness pass.**
`sync_from_cloud()` computes completeness for **every** CSV it scans — newly
ingested, modified, *and* files skipped as unchanged — and stamps the flag onto
the matching folder-backed assignment (located by cleaned filename + class,
only records with a `folder_ref`). An assignment is *complete* when, in its
most recent synced CSV, **every submitted row is graded**: a row counts as
*submitted* when its **File Count** cell is an int > 0 (falling back to a
non-empty **Files (newest first)** cell, and — for a legacy CSV lacking both
columns — treating every row as submitted), and *graded* when it has at least
one non-blank cell among the `Grade*` columns. Exam CSVs (`is_exam_csv`) are
skipped; they never gate this pill. A later export that adds a new ungraded
submission flips the flag back to `False` on the next Sync, so the pill returns
(self-correcting).

**Why the pass never re-ingests.** The completeness check *opens and parses*
the CSV but never calls `ingest_csv` and never purges an unchanged assignment.
Re-ingesting an old CSV would purge-replace the record and wipe grades the
teacher edited in CAM since the last export — the exact data-loss failure the
round-trip work above fixed. Keeping the pass read-only preserves that
invariant while still letting one press of 🔄 Sync unlock assignments whose
CSVs were synced *before* this feature existed, with no re-export from the
workspace. (Grades that exist without files — e.g. a manually-graded assignment
later adopted by Watch — still survive via the `cam_extra` carry-forward
above.)

### Workspace → CAM: the return path

1. **Export.** In the workspace, *Export CSV* (`GET /api/export`) writes
   `<assignment>_Grades_<due-date>.csv` into `class_output_dir()` =
   `[cloud_dir]/[class]/`. `<assignment>` is CAM's display name (`STATE["cam_name"]`,
   from the handoff) when known, else the physical `folder_name` — this is what
   lets a CAM rename reach Sync (see the rename invariant below). When
   `cloud_dir` is set (CAM seeds it — §1), the file
   is written straight to disk (`routed = out_dir != BASE_DIR`); with no
   `cloud_dir` it degrades to a browser download instead. **CAM seeding
   `cloud_dir` is therefore the precondition for Sync ever seeing the grades.**
   The export header ends with a **`Late`** column (after `Files (newest
   first)`): a tri-state `"1"`/`"0"`/`""` per student from the workspace's
   `late_marked`, which CAM's ingest reads into each score's `late` field
   (DATA_DICTIONARY A.1). `cam_extra` carry-forward rows leave it blank.
2. **Scan.** CAM's `sync_from_cloud()` (`app.py`) walks `db_folder()`'s
   per-class subfolders for `*.csv`, fingerprinting each (`_file_fingerprint`,
   md5 + mtime) against the `ingested_files` registry so unchanged files are
   skipped and re-syncs are idempotent.
3. **Ingest.** `_ingest_cloud_file()` cleans the filename to an assignment name
   (rebinding a filesystem-mangled name back to its existing row — see the
   filesystem-character invariant below), routes exam CSVs (a `Total Score`
   column) to the exam pipeline and everything else to
   `IngestionPipeline.ingest_csv()`, then tags the new assignment with the active
   class + term. **Roster-aware routing (Phase 3):** when the class has a roster,
   it hands `ingest_csv` the roster keys + the durable `work_aliases` map so an
   unmatched `Student Name` cell is **pooled** (`unmatched_works`) rather than
   minting a phantom student; a fast-path prefix match is auto-recorded as an
   alias and announced on the sync banner. See §10 and DATA_DICTIONARY C.6.

### Invariant: one assignment, one CSV — Sync refuses contradictory sources

Because ingest keys every `<assignment>_Grades_<date>.csv` back to a single
assignment via `clean_assignment_name()` (which strips the date tail) and
purge-replaces the whole assignment per file, **two differently-dated exports
of the same assignment in one class folder are a data hazard** — whichever is
(re)ingested last silently wins (the 2026-07-09 late-flag incident; see
[LATE_FLAG_INTEGRITY_PLAN.md](LATE_FLAG_INTEGRITY_PLAN.md)). `sync_from_cloud()`
runs a **pre-pass per class folder** (`_scan_class_duplicate_groups`, grouping
by cleaned name; exam CSVs excluded) and, for any group of two or more, **skips
the entire group** — no ingest, no `ingested_files` registry update, no
completeness stamp for any member — counting it under `summary["duplicates"]`
and raising a prominent (error-styled) alert. The alert identifies the
**canonical** export (its filename date matches its own `Due Date` cell) versus
an **export-date fallback** (they differ — written while the deadline was
missing, likely stale), but **never auto-tiebreaks and never deletes**: the
teacher verifies and removes one, then Syncs again (deliberately re-nagged
every Sync until resolved). Both CGW and CAM enforce this: CGW's *Export CSV*
warns when a differently-dated sibling already sits in the class folder
(`api_export` → `stale_siblings`), and CAM's Sync is the hard gate.

### Invariant: a re-sync that zeroes Late flags is surfaced (tripwire)

Any changed CSV re-ingesting an existing assignment purge-replaces its scores.
`sync_from_cloud()` counts the assignment's **synced-layer** Late flags
(`CriterionScore.late` only — *not* `is_late()`, which folds in the teacher's
manual CAM overrides) immediately before the ingest and again after; a drop
from a non-zero count to a lower one appends an advisory warning to the sync
banner. It is purely advisory — the ingest still happens (a genuine CGW waiver
must flow through) — but a silent wipe becomes visible the instant it occurs.

### Invariant: the synced Late layer reconciles read-only from the export CSV on every Sync

Grades never re-ingest without a byte change (a re-ingest purge-replaces the
assignment and would destroy marks/comments the teacher edited in CAM since the
export); **Late flags always do.** In the unchanged-hash branch of
`sync_from_cloud()`, `_sync_reconcile_late()` re-reads *only* the `Late` column
of the skipped CSV and updates each matching `csv:`-sourced score's
`CriterionScore.late` in place, in **both** directions, counting the changes
into `summary["reconciled"]`. This self-heals the *stale-ingest hole*: a CSV
ingested by a running Streamlit process that predated `Late`-column parsing
(commit `7ae6167`) stored `late=False` on every row, and the unchanged-hash skip
froze those flags forever (the 2026-07-09 incident 2; see
[LATE_FLAG_INTEGRITY_PLAN_V2.md](LATE_FLAG_INTEGRITY_PLAN_V2.md) §1). The pass is
read-only on the CSV, idempotent (a second Sync reconciles 0), and never touches
the manual `late_flags` override layer. A legacy CSV with no `Late` header, an
exam CSV, or an unreadable file reconciles nothing — an existing flag is never
zeroed. Duplicate groups are skipped before this branch runs, so reconciliation
never reads a contradictory source.

### Invariant: one assignment record per (name, class)

The timeline keys each row's Streamlit widgets on the assignment **name**
(`key=f"act_{term}_{name}"`, etc.). Two assignment records sharing a name+class
therefore crash the render with `StreamlitDuplicateElementKey`. Two guards keep
that from happening:

- **Always replace on ingest.** `_ingest_cloud_file()` calls
  `_purge_assignment_in_class(name, class)` **before every ingest** (not only on
  a re-sync). The CAM→workspace handoff typically leaves a manual *placeholder*
  assignment of the same name on the timeline; purging first makes the graded
  import **update that placeholder in place** instead of appending a duplicate.
  (Scores live on students keyed by assignment name, so purging the metadata
  record never double-counts grades.)
- **Self-heal on load.** `_dedupe_assignments()` runs every rerun in `main()`
  and collapses any pre-existing name+class duplicates, keeping the *richest*
  record (`_assignment_richness`: exam > has-scores > has-criteria >
  has-source-file) and persisting the repair once. This recovers a database that
  already picked up a duplicate before the always-replace guard existed.

### Invariant: Watch and CSV-ingest describe ONE assignment, not two

An assignment can arrive by two independent routes that key it differently:

- **Class-folder Watch** (`_watch_class_master`, §3) pins each row to its source
  folder via `folder_ref` (the Drive ID / local path) and creates a bare
  *placeholder* (0 criteria, no scores).
- **CSV ingest** (`ingest_csv`) keys the assignment by cleaned **name** and sets
  **no** `folder_ref`.

Left unreconciled, the same real assignment ends up as two records — the graded
`"X"` (no ref) beside a watched `"X (2)"` (ref set, the collision-rename in
Watch). That split is corrosive: because scores are stored on students **by
name**, a later always-replace purge of `"X"` (a re-sync) can drop the scores
while the `"X (2)"` placeholder lingers, leaving a scoreless row and orphaned
grades. **Watch therefore adopts, rather than duplicates:** when a scanned
subfolder's name matches an existing *unpinned* assignment in the class, it
stamps the `folder_ref` onto that record instead of creating a new row. The
graded assignment and its source folder stay a single record, Watch recognises
it on every later pass (`folder_ref` now known → skipped), and the name-keyed
scores never dangle.

### Invariant: a CAM rename decouples the name from the folder — the display name travels

The whole join above is **name-keyed** and quietly assumed *assignment name ==
physical Drive folder name* (Watch seeds the row from the folder name; export
names the CSV from it; ingest derives the name back from the filename).
`rename_assignment()` breaks that assumption on purpose — it renames the record
everywhere but **never the Drive folder** (renaming cloud folders is slow and
risky; §2). Two mechanisms keep a rename from splitting the assignment in two:

- **The display name rides the handoff to CGW.** CAM's published
  `cam_grades_<folderId>.json` already carries `assignment` (its current name).
  CGW's `load_cam_published_name()` reads it into `STATE["cam_name"]` (persisted
  in the cache entry so it outlives the file's consumption), titles the grading
  header with it, and — crucially — **names the export CSV after it**. So the
  file Sync scans is `<new name>_Grades_*.csv`, and the filename→name derivation
  lands on the renamed record instead of resurrecting the old name. (The Drive
  folder, and thus CGW's assignment *dropdown*, still show the old name — the
  dropdown lists real subfolders and only the loaded one has a known CAM name.)
- **`folder_ref` survives the purge.** `_ingest_cloud_file` captures the prior
  record's `folder_ref` before `_purge_assignment_in_class` and re-stamps it
  onto the re-ingested record. Without this the assignment would come back
  folder-less after every Sync — and because Watch only *adopts* a folder whose
  name matches an unpinned assignment (previous invariant), a renamed row would
  never be re-adopted and Watch would spawn the old-named duplicate instead.

Net effect: rename in CAM → next handoff carries the new name to CGW → CGW
exports under it → Sync updates the one renamed record **in place**, still
folder-backed. (CGW must be restarted to pick up the new name, per §1.)

### Invariant: a filesystem-illegal character in the name survives the round-trip

The name-keyed join has one more failure mode the rename invariant doesn't
cover: a name CGW **cannot** reproduce in a filename. `/ \ : * ? " < > |` are
illegal in filenames, so `api_export` sanitizes them to `_`
(`re.sub(r'[\\/*?:"<>|]', "_", …)`, mirrored by CAM's `_safe_dirname`) before
naming the CSV. `Maquette / Mock Up` therefore returns as
`Maquette _ Mock Up_Grades_<date>.csv`, and the filename→name derivation lands
on `Maquette _ Mock Up`, which no exact `a.name` matches — so, unfixed, ingest
appends a `_`-mangled orphan and leaves the real folder-backed row stale.

- **Rebind on the way in.** `_rebind_import_name(incoming, class)` re-maps the
  filename-derived name to the existing assignment whose name matches it through
  the **same sanitize→clean round-trip**
  (`clean_assignment_name(_safe_dirname(a.name)) == incoming`).
  `_ingest_cloud_file` and `_sync_stamp_completeness` both call it before
  matching, so the graded import updates the real row in place and the
  completeness flag stamps it. A folder-backed original outranks a `_`-mangled
  orphan a past sync left behind; an exact name match wins any remaining tie, so
  an assignment literally named `Maquette _ Mock Up` keeps its own row.
- **Delete releases the file.** Sync dedups on content hash (`_file_fingerprint`,
  step 2), so a byte-identical re-export of an already-registered file is
  skipped. `delete_assignment_permanent` therefore forgets the `ingested_files`
  rows feeding the deleted assignment (matched by the same round-trip key, scoped
  to its class) — otherwise a deleted-then-re-exported assignment's grades sit
  stranded on disk with no row to land on, and no re-export can dislodge them.
  `delete_class` already did this per class.

### ⚠ Stranding when `cloud_dir` changes

Because the workspace stores in-progress marks under `class_output_dir()`,
repointing `cloud_dir` (e.g. the first CAM handoff after the workspace ran
standalone) moves the read/write location. Marks saved under the *old* location
(`grades_*.json` / `grading_cache.json` in the workspace's own folder) are not
auto-migrated — the workspace loads an empty state from the new folder until the
old files are copied across. A future safety net could migrate on `cloud_dir`
change; today it is a manual copy.

---

## 9. School report-card grades (MYP Grade + School Grade)

The two numbers a teacher hand-copies into the school's report-card app every
term are computed by CAM. **These are School-determined lookups, NOT
IB's published grade-boundary method.** Both are banded lookups on the **sum
of a student's final criterion grades**, with the band table chosen by **how
many MYP criteria were assessed this term** (2, 3 or 4).

### The lookup tables (`engine/aggregation.py`)

- `MYP_GRADE_BOUNDS` — criterion-sum → **MYP Grade 1–7**, keyed by criteria
  count. Effort is **not** part of this lookup.
- `SCHOOL_GRADE_BOUNDS` — (criterion-sum + Effort) → **School Grade 1–10**,
  keyed by criteria count.
- `myp_grade(crit_total, n_criteria)` / `school_grade(crit_total, effort,
  n_criteria)` — pure helpers over those tables. A criteria count other than
  2/3/4 returns `None` (rendered as `N/A`); out-of-range totals clamp to the
  lowest/highest band, so an all-missing total of 0 maps to grade 1 rather
  than crashing.

The boundary values themselves are fixed school policy and deliberately
hard-coded. Whether these figures are shown at all is a separate, per-database
config: `st.session_state["report_cfg"]` (`show_myp_grade`, `show_effort`,
`show_school_grade`, plus the configurable `effort_min`/`effort_max` range).
It round-trips in the shared session payload exactly like `llm_cfg` (merge over
defaults on restore), so the choice follows the teacher across devices. **All
three default off** — a fresh or public install reports only the criterion
grades. The toggles gate the Window 3 chips and the student-facing report cards
(individual report, combined pack, mail-merge ZIP), but **not** the CAM master
Excel export, which always carries all three; the LLM comment prompt never
included them. Effort clamps to the configured range in `student_effort`.

### The counting rule + one shared helper (`app.py`)

`student_term_grades(student)` is the **single source of truth** consumed by
Window 3 *and* every export, so they can never disagree. Per criterion it
resolves the final grade exactly as the grade panel does — locked
`final_override` if present, else `aggregate_with_policy(...)`'s
`rounded_band`; a criterion with neither is N/A and doesn't count. Each
included grade is coerced with `int(round(...))` before summing (the tables
index on whole numbers only). `n_criteria` = how many criteria carry a grade;
e.g. A/B/D graded with C unassessed → `n_criteria = 3`.

### The calculation method — per student, per term

Which aggregation algorithm turns a criterion's marks into a band is a
**per-student, per-term** setting, not a single global dropdown value (the old
global `calc_method` is retired and ignored on load). `aggregate_with_policy`
resolves it through `calculation_method(sid)` — required argument, no
zero-argument form — which returns the student's stored pin from
`calc_method_by_term[current_term()]` when present, else `auto_calc_method()`.
The **auto default** sizes the term: **≤ 15 qualifying assignments → `60/40
Recency`, > 15 → `Weighted Median`**, recomputed live (a mid-term flip at the
16th assignment is acceptable — exports run at term end). *Qualifying* = On in
the current term, criteria-bearing (not a formative/unbanded-exam `"—"`), and
not a `(Reflection)` adjunct; banded exams count. Window 3's dropdown gains an
**Auto** option whose label shows the live count and resolved method (e.g.
`Auto — 60/40 Recency (12 assignments this term)`); picking a method pins it,
picking Auto releases the pin. Two students in the same class may now compute
under different methods, so the method is resolved **inside** every per-student
loop (grade panel, report-card pack, mail-merge pack), never cached across
students. See DATA_DICTIONARY C.5 for the store's shape and defensive load.

### Effort / English Use

A per-term teacher-entered filler grade (0–5) feeding only the School lookup:
**4 = normal (the default when unset), 3 = behaviour issues, 5 = exceptional
standout**; 0–2 are effectively unused. Stored in the persisted
`effort_by_term` map (`term -> {sid -> int}`), mirroring `comments_by_term`'s
per-term pattern. Edited via the Effort selectbox on Window 3's grade row.

### Where the grades surface

All of these read `student_term_grades(...)`:

1. **Window 3** — one row under the criterion grade columns:
   Effort selectbox + read-only MYP Grade / School Grade, recomputed live.
2. **Excel master** — Tab 1 "Final Suggestions": `Effort`, `MYP Grade`,
   `School Grade` columns after `Crit A..D`.
3. **Report-card pack & single-student report** — both render through
   `_student_docx()`, which appends the three grades to the "Final criterion
   grades" table, above the term overall comment. Directly under the
   `Report Card - <Name>` title it also prints the student's **school email**,
   looked up from the roster by `student_email_for()` (the email is not on the
   `Student` record — only its email-derived id is); the line is omitted for
   students with no roster email.

The class-comments export is comments-only and does not carry grades. The
mail-merge pack (§10) also renders through `_student_docx()` but withholds
**Effort/English Use** and **School Grade** (keeping the MYP Grade) — see
§10 "Withheld grades".

### DOCX page setup (shared)

All three Word exports — the report-card pack, the single-student report and
the class-comments export — are created through `_new_report_document()`, a
single factory that stamps a fixed page geometry onto every section: **A4
(21 × 29.7 cm) with 2 cm margins on all four sides**, replacing python-docx's
US-Letter default. Any future page-format change is therefore a one-line edit
in that helper rather than a change in each builder.


## 10. Distributing report cards — the mail-merge pack

The combined report-card pack (§9) is one document for the teacher to read;
*distributing* individual reports to students is a separate need with a separate
export.

### The export (`build_reportcards_zip`)

`build_reportcards_zip(students)` returns `(zip_bytes, skipped)`. It walks the
class and, for each student, builds a standalone report through the same
`_student_docx()` the combined pack uses (so the two layouts never diverge),
saving it into a ZIP entry named **`<student-email>.docx`**. The email — from
`student_email_for()` — *is* the filename, so the downstream send step needs no
roster↔filename join.

`skipped` is a list of `(label, reason)` for students the pack cannot safely
include: **no roster email**, a **duplicate email**, or an email containing a
character illegal in a filename. The email is never sanitized — mangling it
would change the very address the file mails itself to — so such students are
left out and surfaced rather than silently mis-sent. The deliverables tray
renders this list full-width below the button row.

Conversion to PDF is deliberately *not* done here: python-docx cannot render PDF
without a Word/LibreOffice dependency (which the lean stack avoids — see §5),
and the send side converts far more faithfully for free. The ZIP therefore
carries `.docx`.

### Withheld grades — Effort/English Use and School

The mail-merge pack reaches students *before* their official report cards, so it
suppresses two figures they are not meant to see yet. `_student_docx()` takes an
`include_effort_school` flag (default `True`); `build_reportcards_zip` passes
`False`, which drops the **Effort/English Use** and **School Grade** rows from
the grades table. School goes with Effort because the School grade folds effort
in and would otherwise leak it. The **MYP Grade** — which students do see —
stays, as do the criterion A–D finals, marks, trend chart and comment. Every
other export (Excel master, combined report-card pack, single-student report)
keeps all three grades, since only the mail-merge builder passes the flag.

### Archived students are excluded (`students_for_active_class`)

`students_for_active_class()` is the single source of "who is in this class" for
every export **and** the sync / LLM-comment passes. It unions roster students
with any student who has a score in a class assignment — the *score-only* path,
which covers folder-graded students before a roster is loaded. Because archiving
removes a student from the roster but **keeps their grades**, that path would
re-admit a departed student; the function now skips any key in
`archived_students[class]`, so archived students appear in no export. Restoring
re-adds them to the roster and everything follows.

**⚠ Since Sync/anonymous plan Phase 3 the score-only union no longer admits
*unmatched* CSV rows when a roster exists.** Ingest used to join the
`Student Name` cell as an exact string key and **silently mint a phantom
student** for every miss — with anonymous grading (no filename discipline) that
meant a phantom per camera-roll stem, each leaking into every export through the
score-only path. `ingest_csv` now routes each row against the roster (exact →
durable alias → unambiguous prefix → **unmatched pool**), so an unmatched row
lands in `unmatched_works[class][assignment]` for visual matching instead of
becoming a score-only student. **Since Phase 4 the teacher resolves the pool
visually:** a student missing that assignment shows a "🧩 `<name>` — N unmatched
work(s)" button in Window 2's ⚠ popover, opening `match_works_dialog` — a
thumbnail grid (first page/image of each pooled work, disk-cached under
`thumb_cache/`) with a one-click "this is theirs" that calls `assign_work`
(write the durable alias, materialise the score, drop from the pool). A
rosterless class is unchanged — routing is skipped and the score-only path is
exactly as before (that "folder-graded before a roster is loaded" behaviour is a
feature). The durable `work_aliases[class]` map records each match and survives
Sync's purge-replace; see DATA_DICTIONARY C.6.

### The send side (Google Apps Script)

Distribution itself is out-of-app: the teacher unzips the pack into a Google
Drive folder and runs a batch-send Apps Script bound to their school Workspace.
The script iterates the folder, derives each recipient from the filename,
converts the `.docx` to PDF, and emails it. The full script — plus the
DOCX→Google-Docs→PDF conversion (the reliable path; a raw `.docx` blob's
`getAs(PDF)` fails), the convert-once/send-later split (to beat the 6-minute
execution cap), and the dry-run + `_sent`-folder idempotency mechanics — is in
[BATCH_SEND_REPORTS.md](BATCH_SEND_REPORTS.md).


## 11. The Excel master's Classroom Entry tab (keying marks back to Google Classroom)

`build_excel_bytes()` produces the Excel master workbook. Its first three tabs
are analytics-facing — **Final Suggestions** (per-student criterion finals +
Effort/MYP/School, §9), **Raw Scores** (the full score ledger), and
**Assignments** (per-assignment analytics headed by class/subject/term). A
fourth tab, **Classroom Entry**, exists purely to close the loop back to Google
Classroom: it lays the grades and comments out so the teacher can copy each
column straight into a Classroom folder assignment without re-matching students
by hand.

### The problem it solves

CAM keys students on the numeric student id (the email local part), and the
grading workspace (CGW) lists them in that numeric/email order. Google
Classroom, by contrast, sorts by surname / first name / status / group — so the
two orders rarely line up, and pasting a column of marks from CAM into Classroom
would mis-file every row. The Classroom Entry tab removes the manual re-matching
by emitting students in **Latin name order (first name, then surname)** to match
Classroom's own list, and pairing each mark with the assignment it belongs to.
(This is a deliberate divergence from the on-screen roster, which is stored in
gojūon order — see "Classroom Entry order" below.)

### Classroom Entry order = Latin (first name, surname), decoupled from the roster

The tab receives `students_for_active_class()` (roster students first, in stored
roster order — §10 "Archived students"), but then **re-sorts them locally** into
**Latin name order: first name, then surname** (`_latin_key` inside
`_append_classroom_entry_sheet`). This deliberately diverges from the on-screen
roster, which since 2026-07-07 is stored in **gojūon** order (Window 2 sorts
every imported Classroom roster by kana reading via `sort_roster_gojuon` →
`engine.gojuon_sort_key`; see §11-ish "Window 2" and the CHANGELOG).

The two orders serve different consumers and must not be conflated:

- **On-screen roster + the other export tabs** (Final Suggestions, Raw Scores) —
  **gojūon**, the order a Japanese classroom register uses.
- **Classroom Entry tab** — **Latin first-name/surname**, because it is pasted
  straight back into Google Classroom, which lists students in that Latin order.
  Keeping this tab in gojūon order would mis-align a pasted mark column.

This is the one place we intentionally sort away from roster order, and it lives
entirely inside `_append_classroom_entry_sheet` so nothing else is affected.
It is purely cosmetic alignment: the mark/comment lookup matches on
`student_id`, never on name or row position (see "Layout and matching" below),
so re-ordering can never mis-file a mark — only shift which row it prints on.

Why the roster itself is gojūon: a Japanese register is read in あいうえお order,
and romaji *alphabetical* order is not the same as gojūon (alphabetically `Sato`
sorts before `Kato`; in gojūon か precedes さ, so it is the reverse). See the
2026-07-07 CHANGELOG entries and `engine/collation.py` for the mora-key
algorithm.

### Which assignments count — "folder" assignments only

`_classroom_folder_assignment_names()` selects the assignments to emit, in
timeline (date) order via `assignment_table()`. An assignment qualifies when it
is one CAM ingested **from Google Classroom** — it carries a CGW grading CSV
(`source_file`) or a watched-folder pin (`folder_ref`) — **and** it is not an
exam **and** it fed at least one criterion score. Crit D `(Reflection)` tasks
are excluded by name: they are graded separately, hold no per-student artwork
comment, and are not the folder submissions the teacher keys back into
Classroom. The set is dynamic — sync a new folder assignment and it appears as
its own column pair on the next export automatically.

### Layout and matching (`_append_classroom_entry_sheet`)

Two frozen header rows: fixed `Name` / `Student ID` columns, then a merged
assignment header over a paired **Mark** / **Comment** sub-header for each
qualifying assignment. One data row per student, in Latin name order (first
name, then surname — see "Classroom Entry order" above). Marks are the
raw 0–8 MYP bands (the number the teacher types into Classroom), and the comment
is the per-submission comment verbatim.

The mark/comment lookup is built once from `all_scores()`, keyed on
`(student_id, assignment)` — matching on the id, never the name, so a
misspelled or lower-cased surname on the roster never breaks alignment. A folder
assignment is single-criterion, so this is one score per student; where two
records exist for a key, a **valid** score is preferred over an invalid one. A
student with no record for an assignment (e.g. a non-submitter) leaves that
Mark/Comment pair blank rather than inventing a 0 — this tab is a transcription
aid, not part of the grade math, so the Missing = 0 policy (§8) does not apply
here.
