# Cross-device settings & database-wipe safety — plan v2

**Status:** v2, ready for implementation (target: Opus 4.8 High running Claude
Code). Supersedes the v1 draft briefly placed in the old private repo — **this
public repo (`criterion-assessment-metrics-public` checkout) is the active
codebase and the tree every phase targets.** All anchors below verified against
it on 2026-07-11.
**Prerequisite:** Phase 0 (data recovery) is a **teacher-driven, no-code** step
and must complete before any coding phase.

---

## 1. Incident summary (why this plan exists)

Moving the app to a second computer surfaced what looked like settings-
portability bugs (missing Crit D assignments, folder assignments demoted to
manual, watch folders gone). Diagnosis shows **the shared cloud database
`OneDrive\Documents\Gyoshu\CAM\acm_database.json` was overwritten on
2026-07-10 15:27** and every machine has been reading the damaged file since —
both the old private checkout and this public one point their gitignored
`local_device_prefs.json` at the same OneDrive folder.

Evidence (read-only inspection of the data home):

| File | saved_at | assignments | with `folder_ref` | Crit D | rosters | late_flags | remarks / final_override |
|---|---|---|---|---|---|---|---|
| `acm_database.json` (live) | 2026-07-11 01:31 | 27 | **0** | **0** real | **all empty** | 0 | 0 / 0 |
| `.wiped-by-test-20260710-1527` | 2026-07-10 15:27 | 25 | 1 | 0 | empty + junk `1-4` class | 0 | 0 / 0 |
| `.bak-gojuon-20260707-121222` | 2026-07-07 11:55 | **45** | **12** | **22** | 35/33/24/28 | 667 (pre-cleanup) | 120 / 120 |
| `.bak-20260706-043252` | 2026-07-06 04:24 | 45 | 12 | 22 | populated | populated | 120 / 120 |

The live DB is a **fresh demo session (`Class 1`) + Sync re-ingesting the 24
export CSVs** on top: assignments reappear from CSVs (hence submission counts)
but with no `folder_ref` (Sync never stamps one — Watch does, from `master_dir`,
which is also empty), no Crit D `(Reflection)` rows (marked directly in CAM, no
CSVs exist for them), and duplicate `X (Crit B)` / `X` rows (CSVs exist under
both the physical folder name and CAM's rename; the healthy DB's `cam_name`
data normally collapses these).

### The two wipe mechanisms in the code (both present in this tree)

1. **Settings Save writes instead of loads** — `settings_dialog`,
   `app.py:4169-4170`: changing *Custom Database Path* and pressing Save runs
   `save_prefs(prefs)` then `persist()` — the current in-memory session is
   **written over whatever file already exists at the new path**. The existing
   DB there is never loaded, never backed up. Fresh boot (demo `Class 1`) →
   point Settings at the OneDrive folder → Save = live DB replaced by the demo
   session. This is exactly the cross-device setup flow.
2. **Failed/empty load silently degrades to demo, then autosave clobbers** —
   boot hydrate `app.py:461-466` + `load_database`,
   `engine/persistence.py:277`: `load_database` returns `None` for an
   unreadable file (OneDrive Files-On-Demand placeholder, transient lock,
   malformed JSON) and the app continues on the `init_state` demo gradebook
   **still pointed at the same path**; the next `persist()` (fires after every
   mutation) overwrites the real DB. No caller can distinguish "file absent"
   from "file present but unreadable".

Either path produces the observed wreckage. The `.wiped-by-test` filename
suggests a test/app run with real prefs (the known sandbox hazard) triggered
mechanism 2; the exact trigger doesn't change the fixes.

---

## 2. Terrain notes (verified anchors, public tree, 2026-07-11)

| Thing | Where | Notes |
|---|---|---|
| Device prefs (`db_custom_path` + layout) | `app.py:130-133`, Settings dialog save `app.py:4169` | Per-device by design; gitignored. |
| DB path resolution | `db_path()`, `app.py:162` | Blank pref → the tracked sample `acm_database.json` beside `app.py`. |
| Boot hydrate | `app.py:461-466` | `loaded and (students or assignments)` guard — unreadable and missing files are indistinguishable. |
| Autosave | `persist()`, `app.py:632` | Called after every mutation; swallows failures into `save_status`. |
| Atomic writer / loader | `save_database` / `load_database`, `engine/persistence.py:255` / `:277` | tmp + `os.replace`; crash-safe but overwrite-blind. Loader returns `None` on absent **or** unreadable. |
| Class `master_dir` / assignment `folder_ref` | shared DB (`session.classes[*].master_dir`, assignment records) | **Already machine-independent for Drive IDs** — watch folders need no per-device transfer once the DB is healthy. Local-path masters are per-machine by nature (re-link flow: `app.py:4744`). |
| Watch stamping | `_watch_class_master` `app.py:1045`; `watch_master_directory` `app.py:1104` | Only source of `folder_ref`. |
| CGW settings + cloud mirror | `SETTINGS_FILE` `cam_grading_workspace/app.py:159`, `load_settings` `:221`, class rediscovery `_discover_classes_from_cloud` `:182` | Proven pattern for "config that heals from the cloud folder". |
| CGW teacher identities | `MY_IDENTITIES` (empty in source) + `my_identities()` runtime merge from device-local prefs, `cam_grading_workspace/app.py:95-115` | **Already fixed for privacy** (commit `15073c5`); still device-local → hand-copied per machine. |
| CGW OAuth client secret discovery | `cam_grading_workspace/app.py:486` | Looks only beside `app.py` (`credentials.json` / `client_secret_*.json`). |
| CGW token | `TOKEN_FILE`, `cam_grading_workspace/app.py:64` | Per-device beside `app.py`; scope `drive.readonly`. Absent on the new PC (not yet signed in there). |
| Tracked sample DB | repo-root `acm_database.json` | Confirmed synthetic (generator in `tools/generate_sample_data.py`, documented in `.gitignore:62`). Safe content-wise, but it's what a fresh boot loads — the demo session in mechanism 1. |

Sandbox rules apply to every phase: **never launch the app or tests against
real prefs** — `local_device_prefs.json` points at live OneDrive data. Use a
temp data home. Console is cp932; avoid emoji in script output.

---

## 3. Phase 0 — Recover the database (teacher, no code)

**Goal:** restore `acm_database.json` to the last pre-wipe version. The wipe was
2026-07-10 15:27, so the target is the newest OneDrive version **before that
moment** — it contains everything the 07-07 backup lacks (the 120-student
comment batch run, the late-flag v2 cleanup + 30 healed flags, 07-08→07-10
grading).

1. **Stop every running CAM/CGW process on every machine first.** A live
   Streamlit session autosaves; it would overwrite the restored file with the
   damaged session within seconds.
2. In OneDrive **web** (onedrive.live.com) navigate to
   `Documents/Gyoshu/CAM/acm_database.json` → **Version history** → restore the
   newest version dated **before 2026-07-10 15:27** (expect ~700-800 KB, not
   ~500 KB).
3. Let OneDrive sync the restore down, then run the read-only verification
   script (§3.1) against the file.
4. Start CAM, confirm the UI (Crit D rows back, Grade buttons back, rosters
   populated), then press **🔄 Sync once** — CSVs are unchanged, so expect
   mostly "already in the database" plus the §G Late reconcile pass.

**Fallback** (only if version history is unavailable): copy
`acm_database.json.bak-gojuon-20260707-121222` over `acm_database.json`. Known
losses vs. the ideal restore: comments generated in the 07-08 batch run, the
late-flags v2 cleanup marker (cleanup + reconcile simply re-run on first Sync —
idempotent and marker-guarded), and any 07-08→07-10 grading that lives only in
CAM (CSV-backed marks re-sync from the class folders).

**Do not delete** `.wiped-by-test-20260710-1527`; move the damaged live file
aside as `acm_database.json.damaged-20260711` for forensics.

### 3.1 Verification (read-only script, run before starting the app)

- ≥ 45 assignments total; ≥ 12 with non-empty `folder_ref`; ≥ 22 with `"D"` in
  `criteria` (the `(Reflection)` rows across Y7/Y8/Y9/Y10).
- `session.classes` has `master_dir` set for Year 9 3-4 and Year 10 1Z
  (Drive IDs starting `1XKBJ…` / `1fzrx…`).
- Rosters: Y7=35, Y8=33, Y9=24, Y10=28 (± archived-student moves).
- `teacher_remarks` and `final_override` ≈ 120 each; `late_flags` small
  (~18-30 post-cleanup keys, **not** 667 and **not** 0) if the restored version
  postdates the 07-09 cleanup — 667 means an older version was restored.
- `comments_by_term` non-empty if the version postdates the 07-08 batch run.

---

## 4. Phase 1 — Boot load-guard: never run demo state against a configured path

**Goal:** eliminate wipe mechanism 2.

- In the boot hydrate (`app.py:461-466`): when `db_path()` resolves to a file
  that **exists** but `load_database` returns `None` (unreadable/malformed),
  or the prefs specify a custom path whose file exists (non-trivial size) but
  loads empty, set `st.session_state["db_load_blocked"] = <reason>` instead of
  proceeding silently.
- `persist()` (`app.py:632`) refuses to write while `db_load_blocked` is set,
  surfacing a prominent full-width banner: the DB could not be read, the app is
  in **read-only/demo quarantine**, fix the file or the path and restart.
- The absent-file case **splits in two**:
  - File absent but its **parent folder exists** → legitimate first run at a
    new location: current behaviour (start empty, create on first save).
  - Parent folder or the **volume itself is missing** (unplugged USB drive,
    unmounted cloud drive, disconnected network share) → this is **not** a
    first run: set `db_load_blocked = "storage-missing"` and show the
    quarantine banner naming the configured path ("your database location
    `E:\…` is unavailable — plug in the drive / restore the folder and
    restart"). Never start demo, never create a file — a reassigned drive
    letter must not silently receive a fresh empty DB.
- `load_database` gains an absent-vs-unreadable distinction — a small
  `db_file_state(path) -> "absent" | "ok" | "unreadable"` helper in
  `engine/persistence.py`, keeping the `None` contract for existing callers.

**Verify:** sandbox harness (temp data home): (a) corrupt JSON at the custom
path → quarantine banner, `persist()` refuses, file byte-identical after
interacting; (b) absent file in an existing folder → old behaviour; (c) healthy
file → loads normally; (d) custom path on a nonexistent volume/folder →
storage-missing banner, `persist()` refuses, nothing created anywhere.
`py -m compileall app.py engine` clean.

---

## 5. Phase 2 — Settings path change adopts the existing DB, never overwrites it

**Goal:** eliminate wipe mechanism 1.

- In `settings_dialog` (`app.py:4169`), when Save changes `db_custom_path` and
  the **new resolved path already contains a readable `acm_database.json`**:
  - Default action: **load that file into the session** (reset `db_loaded`,
    rerun through the boot hydrate) instead of calling `persist()`. This is
    what "point my new PC at my cloud DB" means.
  - The reverse ("push my current session over that file") becomes an explicit
    second step: a confirmation dialog stating what will be overwritten
    (assignment/roster counts read from the target file) with a timestamped
    `.bak-replaced-<ts>` written first. Never silent.
- New path with **no** DB file: keep today's behaviour (`persist()` creates it).
- Path **unchanged**: plain `persist()` as today (layout-only saves must not
  trigger any of this).

**Implementation note (landed 2026-07-11):** the new `db_custom_path` pref is
committed **only** when the teacher picks Load or Replace — not at Save time.
While the adopt-vs-overwrite panel is open, and if it is dismissed with Cancel or
**ESC**, the active pref stays on the *old* location. Committing it at Save would
reopen wipe mechanism 1 through the back door: an ESC-dismissed panel would leave
the demo session pointed at the existing DB, and the next autosave (`persist()`
fires after every mutation) would overwrite it. `db_path()` was split into a pure
`resolve_db_path(custom)` resolver + the session-reading wrapper so the panel can
inspect the *candidate* path (counts, `db_file_state`) without moving the pref.

**Verify:** sandbox: repoint a demo session at a temp dir containing a rich DB →
session shows the rich DB, file untouched; explicit-overwrite writes
`.bak-replaced-*` first; unchanged-path Save still persists layout prefs;
Cancel/ESC leave the pref on the old location so no autosave can reach the
existing DB.

---

## 6. Phase 3 — `persist()` shrink tripwire + rotating backups

**Goal:** last line of defence — no future path to a mass-loss write can
destroy the only copy.

- **Shrink tripwire** in `persist()` (keep the engine writer dumb): before
  writing, if the target file exists and its content mass hugely exceeds the
  outgoing payload — cheap structural probe, e.g. `(n_assignments,
  n_roster_entries, n_scored_students)` — refuse the write, park the outgoing
  payload as `acm_database.json.blocked-<ts>`, and raise the Phase-1 quarantine
  banner. Threshold generous (e.g. existing ≥ 10 assignments and payload < 33%
  of existing): deleting one class via the Danger-zone flow must not trip it;
  wiping 4 classes to demo must. Danger-zone wipes may bypass with an explicit
  flag after their own typed confirmation.
- **Rotating backups:** on the first successful persist of each calendar day,
  copy the existing on-disk DB to `acm_database.json.bak-auto-<YYYYMMDD>` in
  the same folder, pruning to the newest 7 (`.gitignore:70` already excludes
  `.bak-*`). Turns any future incident into a ≤1-day loss even without
  OneDrive history.

**Verify:** sandbox: demo-sized payload against a rich on-disk DB → blocked,
`.blocked-*` written, on-disk untouched; normal small edits pass; single-class
deletion passes; day-rollover creates exactly one `.bak-auto-*` and prunes to 7.

---

## 7. Phase 4 — Cross-device bootstrap (question 1: "easier way to bring settings across")

**Status: landed 2026-07-11.** Implemented in `app.py`: `_needs_first_boot_setup()`
gate (blank `db_custom_path` + unset `setup_done` pref + no `CAM_DB_PATH`), the
`_render_first_boot_setup()` panel, cloud discovery (`discover_db_candidates()` /
`_cloud_search_roots()` / `_scan_for_db_files()`), the shared `_adopt_db_path()`
commit-and-rehydrate, the deferred boot hydrate in `init_state()` + the `main()`
gate, and the `CAM_DB_PATH` override in `db_path()`. Docs: CHANGELOG, ARCHITECTURE
invariant, SETUP §4/§5. Verified by a sandboxed harness (discovery against fake
cloud roots, the gate decision table, the env override, and a render smoke test).

**Goal:** a second computer reaches the shared DB without hand-copying
`local_device_prefs.json` — and without ever being able to wipe it (Phases 1-3
are the safety; this is the convenience).

- **First-boot setup prompt (always shown):** when no `local_device_prefs.json`
  exists (or `db_custom_path` is blank), CAM **always** shows a one-time Window
  1 setup panel before loading anything — it never silently boots the sample
  DB on a machine that hasn't chosen yet. The panel offers:
  - **Discovered candidates** (convenience, not a requirement): probe
    well-known cloud-mirror roots for a folder containing `acm_database.json`
    — OneDrive (`%OneDrive%`, `%OneDriveConsumer%`, `%OneDriveCommercial%`),
    Google Drive for Desktop (`%USERPROFILE%\My Drive`,
    `%USERPROFILE%\Google Drive`, and DriveFS mount roots like
    `G:\My Drive`), Dropbox (`%USERPROFILE%\Dropbox`, or the path in
    `%LOCALAPPDATA%\Dropbox\info.json`) — each joined with the documented
    layout plus a shallow scan (depth ≤ 3). Each hit is listed with its
    assignment/roster counts so the teacher can recognise the real one.
  - **"Use another folder"** — paste/browse a path (USB drive, network share,
    any unlisted location). Same adopt-vs-create logic as Phase 2 applies.
  - **"Start fresh"** — explicit demo/sample boot.
  Adopt = write the pref + load via Phase 2's adopt path. Never auto-adopt
  silently; never persist before the choice. (USB/removable locations are
  deliberately *not* auto-scanned — the teacher points at them once via "Use
  another folder", and Phase 1's storage-missing quarantine protects every
  boot after that when the drive is forgotten.)
- **`CAM_DB_PATH` env override** (checked before prefs in `db_path()`,
  `app.py:162`): one-liner new-machine setup, and gives tests/harnesses a way
  to force a sandbox path that **cannot** fall through to real prefs — closing
  the `.wiped-by-test` hazard class. Document that harnesses must set it.
- Layout prefs stay per-device — that separation is correct as designed.
- **Watch folders (question 3): no new mechanism needed.** `master_dir` and
  `folder_ref` live in the shared DB as Drive IDs — never per-device; they
  vanished because the DB was wiped. Document in ARCHITECTURE: Drive-backed
  classes transfer automatically; local-path masters are inherently
  per-machine and use the existing re-link flow (`app.py:4744`).

**Verify:** sandbox with fake `%OneDrive%` / Google Drive / Dropbox roots:
fresh boot shows the setup panel; planted DBs appear as candidates with
counts; adopt loads without writing until the first real mutation; "Use
another folder" with a temp path adopts an existing DB there (and creates one
only when absent); fresh boot with **no** candidates still shows the panel
(manual path + Start fresh only); `CAM_DB_PATH` beats prefs and skips the
panel; established prefs boot exactly as today.

---

## 8. Phase 5 — CGW: identities + credentials heal from the cloud (question 2)

**Context:** commit `15073c5` already moved the teacher identities out of
tracked source into the device-local `cam_grading_workspace/
local_device_prefs.json` (`my_identities()` runtime merge). Privacy is solved;
**portability is not** — a new machine still needs `local_device_prefs.json`,
`credentials.json` and a sign-in (`token.json`) hand-carried. The CGW
`gcg_settings.json` cloud-mirror + order-of-authority load
(`cam_grading_workspace/app.py:221`) is the existing pattern to extend.

- **Identities heal from the cloud mirror:** add `my_identities` to the
  settings dict mirrored into `<cloud_dir>` (like `classes`), merged by
  `load_settings()`'s order of authority; `my_identities()` reads the merged
  settings first, device-local prefs as override. New machine + cloud dir =
  identities present with zero copying. Tracked source stays empty.
- **Editable in the settings panel:** add a *My Identities* field to the CGW
  settings UI (alongside cloud dir + class map, `/api/settings`
  `cam_grading_workspace/app.py:2124`), saving through `save_settings()` so the
  value lands in both the root and cloud `gcg_settings.json` and invalidates
  `_MY_IDENTITIES_CACHE`. No more hand-editing JSON to set who "me" is.
- **Client secret from the cloud dir (question 2: yes):** extend the candidate
  list (`cam_grading_workspace/app.py:486`) to also probe
  `<cloud_dir>/credentials.json` and `<cloud_dir>/client_secret_*.json` after
  the app-root candidates. An installed-app OAuth client secret is
  low-sensitivity (unusable without the teacher consenting in a browser);
  a private OneDrive folder is a fine home for it. `.gitignore:44-45` already
  excludes both name shapes from the repo.
- **`token.json` bootstrap (optional, off by default):** on boot, if the local
  token is absent but `<cloud_dir>/token.json` exists, copy it beside `app.py`
  and proceed; refreshes keep writing locally only. Saves one OAuth round-trip
  per machine. State the tradeoff in the Settings note: the token grants
  `drive.readonly` to anything that can read the OneDrive folder — teacher's
  call; the mirror-to-cloud direction defaults **off**.
- **CGW first-run note:** on this PC, CGW currently has `credentials.json`
  (hand-copied) but no `gcg_settings.json` and no `token.json` — after this
  phase, setting the cloud dir once heals classes + identities, and sign-in
  is the only remaining per-machine step (or zero with the token bootstrap).

**Verify:** CGW sandbox (temp cloud_dir, no real token): identities round-trip
root ↔ cloud settings and `is_me` honours them; secret discovered from cloud
dir when absent locally; token bootstrap copies then proceeds (mocked
`get_credentials`); `grep` of tracked sources shows no personal identifiers.

---

## 9. Phase 6 — Remote-history hygiene (needs the teacher's go-ahead)

The **working tree** of this public repo is clean: identities empty in source,
sample DB synthetic, no student CSVs, gitignore covers secrets/prefs/baks. The
exposure is on **GitHub**:

- The old private history (38 commits, including the real student export
  `Changing Views (Crit B)_Grades.csv` — added in the initial commit — and the
  teacher's personal Gmail in `MY_IDENTITIES`) **was pushed to the same remote
  URL** (`github.com/iamkifojp/criterion-assessment-metrics`) before the
  2-commit public snapshot was force-pushed over it. Force-pushing does not
  delete the old commits from GitHub — they become unreachable but stay
  **fetchable by SHA** (and appear in the events API if the repo was public at
  push time) until GitHub garbage-collects.
- **Fix:** delete the GitHub repository and recreate it, pushing only the clean
  2-commit history (simplest and total), or ask GitHub Support to purge
  unreachable objects. Then verify from a fresh clone:
  `git rev-list --all | xargs -I{} git ls-tree {}` shows no CSV, and
  `git log --all -S turningpoint` is empty.
- **Defuse the local footgun:** the old private checkout
  (`C:\Project\criterion-assessment-metrics`) still has `origin` pointed at the
  **public** GitHub URL and sits 38 commits ahead — one habitual
  `git push --force` from the wrong window republishes everything. Remove or
  repoint that remote (`git remote set-url origin <private-or-none>`), or
  archive the folder.
- Treat the Gmail and the pushed CSV's contents as potentially exposed
  regardless (they were on the remote; visibility history is the teacher's to
  confirm). If the repo was public during those pushes, note it for the
  school's data-handling judgment.

---

## 10. Non-goals / explicitly out of scope

- No multi-writer merge for the DB (two machines editing simultaneously is
  still last-writer-wins at the OneDrive layer; the teacher works on one
  machine at a time — the tripwire now catches the catastrophic case).
- No change to the CSV/Sync contract, `grades_*.json` shapes, or the CGW
  handoff (`cam_grades_*.json`).
- No encryption of the cloud folder; OneDrive account security is the boundary.

## 11. Suggested order & sizing

Phase 0 (teacher, ~15 min) → Phase 6's **defuse-the-footgun bullet + GitHub
delete/recreate** (teacher + 10 min, do it while the repo is days old) →
Phases 1 + 2 + 3 (one sitting, the safety core) → Phase 4 (medium) → Phase 5
(medium).

Each coding phase: byte-compile + sandboxed harness per its Verify block,
CHANGELOG entry in house style, ARCHITECTURE/DATA_DICTIONARY touch-ups where a
contract changed (Phases 1/3 add the quarantine + tripwire invariants to the
integrity section).
