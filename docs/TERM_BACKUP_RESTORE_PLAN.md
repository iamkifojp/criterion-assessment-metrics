# Term backup & restore — plan v1

**Status:** v1, **implemented 2026-07-12** (Opus 4.8, this public checkout). The
prerequisite `docs/COMMENT_CLOUD_MIRROR_PLAN.md` landed first; this feature is
the *third* line of defense behind mirror-heal and the rotating `.bak` files.

**What landed:**

- Engine (`engine/persistence.py`): public per-record serializers
  `score_to_dict`/`from_dict`, `assignment_to_dict`/`from_dict`,
  `exam_result_to_dict`/`from_dict` (exported from `engine/__init__.py`) so the
  backup can store per-class, per-student score lists in the exact on-disk shape.
- App (`app.py`): `TERM_BACKUP_VERSION`/`KIND` constants; a stable term
  predicate `_term_of_assignment` (blank/legacy → `TERMS[0]`, independent of the
  active term so backup and restore always agree); `build_term_backup` /
  `write_term_backup` (atomic tmp+replace); `validate_term_backup`;
  `diff_term_backup` (dry-run, writes nothing); `restore_term_backup`
  (`.bak-pre-term-restore-<stamp>` first, wholesale term-slice replace,
  fill-blanks-only remarks/overrides, seeds the mirror-deletion flag + clears
  fingerprints, single `persist(allow_shrink=True)`). `term_backup_folder` added
  to device prefs.
- UI: `⚙ Settings → 🗄 Term backup & restore` — folder input, term dropdown +
  ⬇ Back up term, and ⬆ Restore-from-backup file uploader → dry-run diff →
  `RESTORE {term}` typed confirmation.
- Tests: `tests/test_term_backup.py` (stdlib `unittest`, 17 cases) — build
  scoping, validation refusals, lossless round-trip, other-term invariance,
  live-only-assignment removal, no-duplicate restore-over-live, fill-blanks-only
  remarks/overrides, and the pre-restore `.bak` equals the pre-restore DB. Run:
  `python -m unittest tests.test_term_backup`.

**Note:** the file/line anchors below are from planning time and have since
drifted (the Settings dialog and Finalize references moved); the intent is
unchanged.

---

## 1. What & why

A deliberate, teacher-initiated snapshot of one term — everything CAM knows
for that term, in one self-describing JSON in a folder the teacher chooses —
plus a loader that can put that term back after a database disaster.

Positioning (from discussion with the teacher, 2026-07-11):

- **Backup** is peace-of-mind: an end-of-term artifact the teacher created on
  purpose, in a folder they control (may be outside OneDrive). Zero risk — it
  only ever writes *outside* the DB.
- **Restore is a disaster tool, not an editing tool.** If a teacher reaches
  for it, their DB is corrupted; otherwise they'd just edit the data directly.
  Therefore restore **replaces the term's slice wholesale** — no fill-blanks
  mode, no merge ambiguity — behind a dry-run diff, a typed confirmation, and
  an automatic DB backup.
- **Loud staleness warning, always:** anything entered for that term *after*
  the backup was created is not in the file and will be lost on restore. Show
  the backup's `created_at` and the warning in the confirmation step itself.

Scope is by **term tag, never by dates.** Every assignment, exam and comment
already carries its term (`TERMS`, `app.py:102`; per-term maps throughout the
session payload) — that is exactly why the old Finalize button could be
removed (`app.py:6841`). Date-range scoping would require maintaining term
dates in Settings and inherit the known date-edge hazard class (dup-dated
export CSVs etc.). The backup file records which term it covers; the loader
touches only rows tagged with that term.

## 2. Backup file

`cam_term_backup_<term-slug>_<YYYYMMDD-HHMMSS>.json`, written atomically to
the teacher-specified folder:

```jsonc
{
  "version": 1,
  "kind": "cam_term_backup",
  "term": "Term 1",
  "created_at": "<iso>",
  "db_path": "<source db>",             // provenance only
  "classes": ["Year 7 1-4 (2026-27)", ...],
  "counts": { "students": 120, "assignments": 21, "comments": 120, ... },
  "payload": {
    "assignments": [ /* full records for assignments tagged this term */ ],
    "scores":      { "<class>": { "<sid>": [ /* score entries for those assignments */ ] } },
    "exam_results":{ /* same filter */ },
    "comments":    { "<class>": { "<sid>": "<text>" } },      // comments_by_term[term]
    "effort":      { "<class>": { "<sid>": 3 } },             // effort_by_term[term]
    "active":      { /* active_by_term[term] */ },
    "calc_method": { /* calc_method_by_term[term] */ },
    "late_flags":  { /* entries for this term's assignments */ },
    "excused":     { /* same */ },
    "remarks":        { "<class>": { "<sid>": "<text>" } },   // NOT term-scoped — see §4
    "final_override": { "<class>": { "<sid>": {"A": 7} } }    // NOT term-scoped — see §4
  }
}
```

Counts in the header let the restore dialog present the dry-run diff without
parsing the whole payload twice, and let a human sanity-check the file in a
text editor.

## 3. UI (Settings dialog, `app.py:4691`)

New "Term backup" section:

- **Folder** text input (persisted in `local_device_prefs.json` — per-device
  by design, like every path pref).
- **⬇ Back up term** — dropdown of `TERMS` defaulting to the active term +
  button. Writes the file, reports path + counts on `save_status`.
- **⬆ Restore from backup…** — file picker (`st.file_uploader`, matches the
  existing staging-upload pattern, `app.py:4887`). Flow:
  1. Parse + validate (`kind`, `version`, term present). Malformed → error
     banner, nothing else happens.
  2. **Dry-run diff** rendered in the dialog: per class — comments to restore
     / that differ from current, scores that differ, assignments in the backup
     but missing live (and vice versa). Nothing written at this step.
  3. **Warning + typed confirmation** (same pattern as the Danger-zone wipe):
     banner shows `created_at` and "changes made to {term} after this backup
     are NOT in this file and will be lost"; teacher must type
     `RESTORE {term}` exactly.
  4. Timestamped safety backup beside the DB
     (`acm_database.json.bak-pre-term-restore-<stamp>` — never pruned), then
     replace the term slice, `persist(allow_shrink=True)` (the deliberate,
     typed-confirmed path the tripwire already exempts), rerun.

## 4. Restore semantics

- **Term-tagged data** (assignments, their scores/exam results, comments,
  effort, active/calc-method maps, late/excused flags for those assignments):
  the live term slice is **deleted, then replaced** with the backup's —
  including removing term-tagged rows that exist live but not in the backup
  (they postdate the backup; the warning covers this).
- **Non-term-scoped maps** (`teacher_remarks`, `final_override`): restore
  **only for students with no live entry** (a wholesale replace would clobber
  Term-2 remarks while restoring Term 1). State this in the dry-run output.
- Data for other terms is never touched — assert this in tests.
- After restore, the cloud mirrors (companion plan) refresh on the next
  `persist()`; the restored comments regain their per-class cloud twins
  automatically. Restore must seed the mirror-deletion flag/fingerprints so
  the mirror tripwire does not mistake the restore for a mass deletion.

## 5. Danger analysis (the teacher's own question: "will this cause more corruption?")

| Risk | Mitigation |
|---|---|
| Restore onto a half-broken DB compounds damage | Restore is only reachable when boot passed the load-guard (`db_load_blocked` boots quarantine `persist()` already); a corrupted-file disaster is first fixed by file-level recovery (`.bak` / OneDrive version history), *then* term-restore covers finer-grained loss |
| Teacher restores a stale file over newer work | `created_at` + explicit staleness warning + dry-run diff + typed confirm |
| Bug in slice-replace deletes the wrong term | Term-tag filter is a single shared predicate used by both backup and restore; tests assert other-term invariance |
| Crash mid-restore | Single `persist()` at the end (atomic tmp+replace); the pre-restore `.bak` exists before any mutation |
| Backup file itself malformed/truncated | `kind`/`version`/term validation + counts cross-check before the confirm step is even offered |

Residual risk is acceptable: every destructive step is behind an explicit
typed confirmation and an automatic backup, matching the app's existing
Danger-zone conventions.

## 6. Testing (CLAUDE.md rules apply)

Sandboxed only (temp `db_custom_path`; never the real folder). Cases:
backup→wipe term→restore round-trip is lossless; restore leaves other terms
byte-identical; remarks/overrides fill-blanks-only behavior; live-only
assignments in the restored term are removed (with the warning shown);
malformed/wrong-kind file refused before the confirm step; typed confirmation
mismatch does nothing; pre-restore `.bak` exists and equals the pre-restore DB.
