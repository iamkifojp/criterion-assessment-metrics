# CAM — Data Dictionary

Field-level source of truth for CAM's most schema-sensitive artefacts:

1. the **grading CSV** the ingestion pipeline reads (`engine/ingestion.py`),
2. the **`grading_cache.json`** the Flask workspace writes
   (`cam_grading_workspace/app.py`) and the **`cam_grades_<folderId>.json`**
   handoff file CAM publishes for it (§B.6), and
3. the **report-card grade state** persisted in `acm_database.json`'s session
   payload (Effort/English use + the two derived School grades).

All claims below are verified against the code and the live sample files. Where
the on-disk data shows **schema drift** (older vs. newer shapes coexisting in one
file), that is documented explicitly — readers must handle both.

---

## Part A — Grading CSV ingestion

Entry point: `IngestionPipeline.ingest_csv()` (`engine/ingestion.py:395`). Files
are opened with `encoding="utf-8-sig"` (tolerates a BOM) and read via
`csv.DictReader`.

### A.1 Recognised columns

Column names are the pipeline's `ingest_csv` keyword defaults; all are
overridable per call.

| Logical field | Default header | Notes |
|---------------|----------------|-------|
| Student ID | `Student Name` | `id_column`. Blank rows are skipped. **The join is no longer an unconditional exact-string `get_or_create`.** When the caller supplies the class roster (`roster_keys`), each id is routed through `resolve_identity()` (exact → durable alias → unambiguous longest-prefix → **unmatched pool**), so an anonymous/renamed stem no longer mints a phantom student — see C.6. With no `roster_keys` (rosterless class, or any non-Sync caller) the legacy exact-key mint is unchanged. |
| Grade | `Grade` | `grade_column`. Coerced by `_coerce_grade` → int clamped to **0–8**; non-numeric/blank → `None`. |
| Keywords | `Checked Keywords` | `keywords_column`. Split by `_split_keywords`. |
| Comment | `Comment` | `comment_column`. Stripped. |
| Files | `Files (newest first)` | `files_column`. Semicolon-separated; used for the filename date fallback **and** the completeness pass (A.5). |
| **Due Date** | `Due Date` | `due_date_column`. The deadline; the authoritative row date when present. |
| File Count | `File Count` | Not read by `ingest_csv`; consumed only by CAM's read-only completeness pass (A.5). |
| **Late** | `Late` | `late_column`. **Tri-state** cell: `"1"` late, `"0"` on-time, `""` never assessed. Parsed truthy as `cell.strip().lower() in {"1","true","yes"}` and stamped onto every `CriterionScore` from the row as its `late` field; absent in legacy CSVs → all scores default `late=False`. Matched exactly first, then case/whitespace-insensitively. Feeds the two-layer `is_late()` read (a manual CAM `late_flags` override wins when present — see A.7, which also covers the read-only self-heal of this field on every Sync). **CGW side:** a deadline change re-derives `late_marked` from submission timestamps for *auto-derived* students only — a hand-set tick or waiver (`late_manual=true`, Part B) is now sticky and survives the change (fixes the 2026-07-09 incident; before this, restoring a lost deadline silently zeroed manual ticks). CAM ingest is unchanged: it never sees `late_manual`. |

### A.2 Criterion column detection (which column is which criterion)

`_resolve_column_map` decides whether grade columns name a criterion:

- Headers that explicitly name a criterion (e.g. `Grade (Crit A)`,
  `Grade (Crit C)`) are auto-routed to those criteria — **one CSV can populate
  multiple criteria.**
- A generic `Grade` column with **no** criterion in any header requires the
  caller to pass `manual_criterion_target=Criterion.X`, else `ValueError`.
- **No** gradeable column at all → a **0-criterion formative** assignment
  (logged, not scored).

### A.3 Due Date column parsing & fallbacks — the critical path

Two independent resolution steps: **which column** holds the date, then **what
date** each row gets.

#### Step 1 — column resolution (`_resolve_date_column`, `ingestion.py:613`)

Candidates are tried **in priority order**, and for each candidate an exact
header match is preferred before a case-insensitive / whitespace-tolerant match:

```
_resolve_date_column(fieldnames, "Due Date", "Assessed Date")
```

1. `"Due Date"` — the **current durable export** column (the deadline).
2. `"Assessed Date"` — **legacy** column name, accepted as a fallback.
3. For each: exact match first, then `name.strip().lower() == candidate.strip().lower()`
   so `"due date"` or `" Due Date "` still resolve.
4. If neither column exists → returns `None`; the file degrades cleanly to the
   filename/runtime fallbacks below.

#### Step 2 — the cell value (`parse_iso_date`, `ingestion.py:141`)

The resolved column's cell is parsed strictly, because the durable export embeds
an ISO-8601 date directly in the row:

1. Strip; empty → `None`.
2. Tolerate a trailing `Z` (UTC marker that `fromisoformat` rejected pre-3.11),
   then `datetime.fromisoformat(candidate)` — handles `"2026-05-10"` and
   `"2026-05-10T19:12:00"`.
3. On failure, loosen to a bare `YYYY-MM-DD` matched **anywhere** in the cell
   (`_ISO_DATE`).
4. Still nothing → `None` (row falls through to Step 3).

#### Step 3 — per-row timestamp priority (`_resolve_timestamp`, `ingestion.py:649`)

The final timestamp for a row is chosen by this **strict priority ladder** —
this is the full fallback chain the request refers to:

| Priority | Source | When it wins |
|----------|--------|--------------|
| 1 | **Per-student override** | `sid in per_student_override` (teacher pinned a date for this student). |
| 2 | **Global override** | `global_override_date` set for the whole ingest. |
| 3 | **CSV Due Date** (`csv_date`) | The durable per-row date from Steps 1–2. Outranks anything guessed from a filename. |
| 4 | **Filename date** | `parse_date_from_filename` over each `;`-split token in the Files column; first parseable date wins (files listed newest-first). Supports English `Mon DD, YYYY [h:mm AM/PM]`, Japanese `YYYY年MM月DD日`, and ISO `YYYY-MM-DD` shapes. |
| 5 | **Ingest time** | `ingest_time` (defaults to `datetime.now()`) when everything else is absent. |

So a legacy file with no date column and no dated filenames still ingests
cleanly — it simply lands at ingest time.

### A.4 Exam-export CSVs are a different animal (do not confuse)

A CSV is an **item-level exam export**, not a criterion grading file, when its
header contains both `Total Score` and `Student Name`
(`is_exam_csv`, `ingestion.py:373`). Shape:

```
Student Name, Q1, Q2, …, Total Score, Max Total, Due Date, Comment
```

`Total Score` is a **raw mark** (e.g. 37/45), *not* an MYP 0–8 band, so these
files **must never flow through the criterion-score path.** Reserved (non-question)
headers are: `student name, total score, max total, due date, comment,
checked keywords, files (newest first), assessed date, file count`. Everything
else is treated as a question-label column by `exam_question_columns`.

### A.5 File Count / Files — read-only completeness pass (the "Awaiting Grade" gate)

Separate from ingestion, CAM's `sync_from_cloud()` reads each grading CSV a
second time — **read-only, never through `ingest_csv`** — to decide whether a
folder-backed assignment's grading is *complete*, which gates Window 3's
**⏳ Awaiting Grade** pill (ARCHITECTURE §8). This is the only consumer of the
**File Count** column, and a second consumer of **Files (newest first)**.

The rule (`_csv_grading_complete`): an assignment is complete when **every
submitted row is graded**.

- A row is **submitted** when its `File Count` cell parses to an int > 0.
  - If the `File Count` column is **absent**, fall back to a non-empty
    `Files (newest first)` cell.
  - If **both** columns are absent (a legacy CSV), every row is treated as
    submitted.
- A submitted row is **graded** when at least one cell is non-blank among the
  columns whose header **starts with `Grade`** (so `Grade`, `Grade (Crit A)`,
  … all count; a `0` is non-blank and counts as graded).
- **Exam CSVs** (`is_exam_csv`, A.4) are skipped entirely — they never gate the
  pill.

Because a blank `Grade` cell on a submitted row is what ingestion drops to
`None` and skips, this pass is how CAM recovers the "submitted but not yet
graded" signal that the score path alone loses. The result is stamped onto the
Assignment record's `grading_complete` field (below); the pass runs on
unchanged (already-ingested) files too, so one 🔄 Sync can unlock assignments
whose CSVs predate the feature without a re-export.

### A.6 `grading_complete` on the Assignment record

The completeness result is persisted in `acm_database.json` as a boolean
`grading_complete` field on each **Assignment** record (serialized by
`engine/persistence.py`, defaulting to `False` — old databases without the key
load cleanly). It is only meaningful for folder-backed rows (`folder_ref` set):
`False` → the folder is still being graded (Awaiting Grade); `True` → grading
finished, so a scoreless student falls through to the standard Missing = 0
policy. See ARCHITECTURE §8 and §7's `acm_database.json` row.

### A.7 Lateness — the two layers (`CriterionScore.late` + `late_flags`)

CAM reads lateness through `is_late(sid, asg, crit, score)` (`app.py`), which
folds two independent layers:

- **Synced layer — `CriterionScore.late`** (a `bool` on the score). Populated
  from the CSV `Late` column at ingest (A.1). This layer **self-heals on every
  Sync**: `_sync_reconcile_late()` re-reads *only* the `Late` column of any CSV
  Sync skips as unchanged and rewrites `late` in place, in **both** directions,
  so a flag an older ingest dropped (the *stale-ingest hole*) is repaired
  without a byte change and without re-ingesting (which would purge-replace
  grades edited in CAM since the export). Legacy CSVs (no `Late` header), exam
  CSVs, and unreadable files reconcile nothing — an existing flag is never
  zeroed. Idempotent: a second Sync reconciles 0.
- **Manual override layer — `late_flags`** (`"sid||assignment||crit" → bool`,
  persisted in the `acm_database.json` session payload). When a key is
  **present** it wins over the synced layer — the teacher's CAM-side
  waive (`False`) / force (`True`). Semantics: **once manual, always manual.** A
  key is created *only* when the edit-dialog Save runs with the Late checkbox
  moved off its current effective value; a Save with an untouched checkbox is a
  no-op, so routine grade/comment edits no longer leave a redundant override.
  Once a key exists it is updated on later Saves (including a toggle back to the
  synced value) but **never auto-deleted** — there is no UI to revert a cell to
  auto (mirrors CGW's `late_manual` stickiness, Part A.1). A one-time,
  marker-guarded cleanup (`late_flags_cleanup_v1`) purged the *redundant* keys
  the old always-write dialog had materialised, keeping only keys that differ
  from the synced value (real waives/forces).

See [LATE_FLAG_INTEGRITY_PLAN_V2.md](LATE_FLAG_INTEGRITY_PLAN_V2.md) and
ARCHITECTURE §8 ("the synced Late layer reconciles read-only …").

---

## Part B — `grading_cache.json` schema

Written by `write_cache()` (`cam_grading_workspace/app.py:467`), read by
`load_cache()` / `load_cache_entry()`. Writes are **atomic** (`.tmp` +
`os.replace`, never a half-written file). It is a *mirror* of live marking state
— "saved alongside student data, never in place of it."

### B.1 Top-level shape

```jsonc
{
  "version":         1,                // schema version (CACHE_VERSION); see B.7
  "<driveFolderId>": { …entry… },      // Drive-backed assignment folder
  "local-<hash>":    { …entry… }       // local-folder assignment (Phase 3)
}
```

A top-level **`"version"`** key (int, = `CACHE_VERSION`) records the schema
version; every other key is an assignment entry. A file with **no** `version`
key is a pre-versioning **v0** legacy file and still loads — `load_cache()`
migrates it entry-by-entry through `upgrade_entry()` on read and re-stamps it v1
(§B.7). All other consumers read entries by `.get(<key>)`, so the reserved
`version` key never collides with a Drive ID / `local-<hash>` slug.

The remaining keys are keyed by the assignment's **durable persistence key**
(one key = one assignment). For a Drive-backed assignment this is the **Google
Drive folder ID** (unchanged). For a **local-folder assignment** (CGW
`LocalProvider`, Phase 3) it is a **stable slug** `"local-" + sha1(normcased
absolute path)[:16]` derived from the assignment folder path, so the entry
survives an app restart and path-normalisation differences. The same slug names
the per-folder `grades_<key>.json` and (Phase 4) `cam_grades_<key>.json`, so the
whole round-trip keys on it identically to a Drive ID. The key is produced by
`provider.state_key(ref)` in `api_load`; everything downstream is
backend-agnostic. Local per-file IDs (in `students[*].files[*].id`) are opaque
`"lf-<hash>"` tokens resolved to absolute paths through an in-session registry —
never persisted, rebuilt on each load.

### B.2 Entry schema (current)

```jsonc
{
  "folder_name":       "Artist Looking",          // physical Drive subfolder name
  "cam_name":          "Artist Looking",          // CAM's display name (export name); null until a CAM handoff
  "class_folder_id":   "18IKEh3hYGP…",            // parent Drive folder (the class)
  "checklist_headers": [                            // per-folder rubric checklist
    { "label": "Clear explanation", "type": "positive" },
    { "label": "Deepen the analysis", "type": "growth" }
  ],
  "criteria":          ["A"],                       // selected MYP criteria (subset of A–D)
  "deadline":          "2026-05-10T23:59",          // ISO, or "" if unset
  "students":          { "<studentKey>": { …record… } },
  "cam_extra":         { "<camStudentId>": { …CAM record… } },  // see B.6
  "groups":            [ …group… ],                 // pair-work groups
  "updated":           "2026-06-30T14:40:35"        // ISO, timespec=seconds
}
```

- **`cam_name`** — CAM's display name for the assignment, captured from the
  handoff file (`cam_grades_<folderId>.json` → `assignment`, §B.6). Drives the
  export filename and the grading header so a rename in CAM propagates to CGW
  and Sync (ARCHITECTURE §8 rename invariant). `null`/absent until the first CAM
  handoff, in which case `folder_name` is used instead. Distinct from
  `folder_name`, which is always the never-renamed physical Drive subfolder.
  Filesystem-illegal characters (`/ \ : * ? " < > |`) are flattened to `_` when
  naming the CSV; Sync's `_rebind_import_name` reverses that on ingest so a name
  like `Maquette / Mock Up` still lands on its own row (ARCHITECTURE §8
  filesystem-character invariant).
- **`checklist_headers`** — full `{label, type}` objects (not bare strings) so
  strength/growth styling and auto-comment grouping survive a reload. `type` is
  one of exactly **`"positive"`** or **`"growth"`** (`_normalize_checklist`
  coerces anything else, and bare-string legacy items, to `"positive"`).
- **`criteria`** — list of MYP criterion letters; on read, filtered to valid
  `MYP_CRITERIA` members.
- **`groups`** — normally `[]`. When populated, each element is:
  ```jsonc
  { "id": "<groupId>", "members": ["<studentKey>", …], "color": "<hex/name>" }
  ```
  Linked partners **share one grade** (`_sync_group_grades`). Colours are
  allocated from `GROUP_COLORS`, avoiding collisions.

### B.3 Student record — ⚠ two coexisting shapes

Student keys are typically `"email:<addr>"` (e.g. `"email:100010@school.ed.jp"`).
**Both of the following record shapes exist in live cache files** and must be
handled on read:

**Current shape** (written by `write_cache`):

```jsonc
"email:100003@school.ed.jp": {
  "grades":       { "A": "7" },   // per-criterion, values are STRINGS
  "keywords":     ["Accurate Proportion"],
  "comment":      "Strengths: Accurate Proportion.",
  "graded":       true,
  "late_marked":  null,           // true | false | null (null = never assessed)
  "late_manual":  false,          // true = teacher hand-set late_marked (tick or
                                  // waive); sticky against deadline re-derivation.
                                  // absent/false = auto-derived from the deadline.
  "cam_modified": ["A"]           // criteria whose band CAM changed since the
                                  // last export (the MODIFIED marker); [] when
                                  // clear. Cleared on dismissal or export.
}
```

`late_manual` is **CGW-internal**: it decides whether the deadline-change
handler may re-derive a student's `late_marked` (it may not, once the teacher
has hand-set it — see A.1). It is **not** written to the export CSV and does
**not** reach CAM; the tri-state `Late` export column carries only
`late_marked`. Absent on legacy/older entries → treated as auto-derived (i.e.
today's behaviour) until the teacher next toggles a Late checkbox. The schema
migration (`upgrade_entry`, §B.7) **defaults `late_manual` to `false` only when
the key is absent** and otherwise carries a hand-set value through verbatim — it
must never strip or force it (that would silently un-stick every teacher-set
Late tick, the 2026-07-09 late-flag incident).

**Legacy shape** (older entries, still present):

```jsonc
"email:100010@school.ed.jp": {
  "grade":   "5",   // single string, no criterion key, no grades{} dict
  "keywords": [...],
  "comment":  "...",
  "graded":   true
  // no late_marked
}
```

`_normalize_grades()` (`app.py:533`) is the migration shim: it prefers a
`grades` dict, and otherwise promotes a legacy `"grade": "7"` to
`{"A": "7"}`. Empty-string grade values are dropped. **Grade values are strings
throughout the cache** (contrast the CSV path, which coerces to clamped ints).

### B.4 Entry-level schema drift

The five live entries in the sample `grading_cache.json` span two entry shapes:

| Keys present | Meaning |
|--------------|---------|
| `folder_name, checklist_headers, students, groups, updated` | Older entry (no criteria/deadline/class link). |
| `+ class_folder_id, criteria, deadline` | Current entry. |

Consumers should treat `class_folder_id`, `criteria`, `deadline`,
`cam_extra`, `cam_name` and the per-student `cam_modified` / `late_manual` as
**optional** (missing `late_manual` → `false`, i.e. auto-derived) —
`load_cache_entry` defaults them (`criteria → []`, `deadline → ""`,
`cam_extra → {}`, `cam_name → None`, `cam_modified → []`) so an older entry
loads without error.

### B.5 Related files (not the cache, but adjacent)

- **`grades_<folderId>.json`** — full `STATE` snapshot for one folder (a
  superset of the cache entry, including the `checklist`). `<folderId>` is the
  durable persistence key (a Drive folder ID, or a `local-<hash>` slug for a
  local-folder assignment — §B.1). Used as a fallback source for checklist
  headers when the cache lacks them. Since the storage-
  provider seam (PDF/local-mode plan Phase 1) the snapshot also carries a
  transient **`source`** field (`"drive"` | `"local"`) — the backend behind the
  loaded assignment. It is **re-derived from the reference on every load**
  (`provider_for`), never authoritative, so it needs no migration and is absent
  from `grading_cache.json`.
- **`acm_database.json`** — the Streamlit engine's serialized `Gradebook`; a
  *separate* schema owned by `engine/persistence.py`, not covered here.

### B.6 `cam_grades_<folderId>.json` — CAM's published grades (handoff file)

Written by CAM's `_publish_workspace_grades()` (`app.py`) into
`[db folder]/[class]/` at every folder-grading handoff; read, merged and then
**deleted** by the workspace's `api_load` (consumption prevents a stale copy
overwriting newer marking later — see [ARCHITECTURE.md §8](ARCHITECTURE.md)).
Write is atomic (`.tmp` + `os.replace`).

`<folderId>` is the **durable state key** the workspace derives (§B.1), not the
raw ref: a Drive folder ID unchanged, or — for a **local-master class**
(PDF/local-mode plan Phase 4) — the same `local-<hash>` slug
`_workspace_state_key()` shares with the workspace's `LocalProvider.state_key`.
CAM and CGW must agree on this slug or the handoff file is never found.

```jsonc
{
  "assignment": "Artist Looking",       // CAM assignment name
  "class":      "Year 7 1-4 (2026-27)", // CAM class name
  "folder_ref": "18IKEh3hYGP…",         // Drive folder ID or local folder path
  "published":  "2026-07-05T14:32:00",  // ISO, timespec=seconds
  "students": {
    "100003": {                          // CAM student id (email-derived)
      "grades":  { "A": 7 },             // 0-8 band per criterion, INTS
      "comment": "Reworked after feedback."  // CAM-side comment, may be ""
    }
  }
}
```

- **`assignment`** is CAM's current display name and is now consumed for more
  than provenance: `load_cam_published_name()` reads it into the cache entry's
  `cam_name` (§B.2), which drives CGW's export filename and grading header so a
  CAM rename reaches Sync (ARCHITECTURE §8 rename invariant).
- Only students holding at least one **valid** score on the assignment are
  included; a student/criterion absent from the file means *CAM holds
  nothing* — never an instruction to clear a workspace value.
- Crossing the app boundary, the workspace validates on read
  (`_normalize_cam_students`): criteria outside A–D and non-integer or
  out-of-range bands are dropped; bands become **strings** internally to
  match the cache convention (contrast the ints here).
- Students in the file with no files in the Drive folder become the cache
  entry's `cam_extra` bucket (same `{grades, comment}` shape, string bands)
  and are appended to every CSV export — their CAM student id doubles as the
  `Student Name` cell.

### B.7 Schema versioning & migration

`grading_cache.json` carries a top-level **`"version"`** int (§B.1) equal to
`CACHE_VERSION` (currently **1**). `load_cache()` reads the raw file and, for
every non-`version` key holding a dict, runs it through the single per-entry
migration routine **`upgrade_entry()`**, then stamps the result `version = 1`.
The migration is **in-memory on read**; the next `write_cache()` persists it
atomically (`.tmp` + `os.replace`), so after one load-and-save the file is v1.
`write_cache()` also stamps `version` directly, so a brand-new (empty) cache is
written versioned.

- **v0 → v1** (a file with **no** `version` key is v0): fold in the two
  long-standing read-time shims as the migration step —
  `_normalize_checklist()` coerces bare-string / mixed `checklist_headers` to
  `{label, type}` objects, and `_normalize_grades()` promotes a legacy single
  `"grade": "7"` to the per-criterion `{"A": "7"}` dict (the obsolete `grade`
  key is then dropped; empty-string bands are dropped).
- **Carried through untouched:** `cam_extra`, `cam_name`, `criteria`,
  `deadline`, `groups`, and each student's `keywords` / `comment` / `graded` /
  `late_marked`. `late_manual` is defaulted to `false` **only when absent**
  (never stripped/forced — §B.3); `cam_modified` is re-validated to real
  criterion letters.
- `upgrade_entry()` is **idempotent** on an already-v1 entry, so repeated loads
  are safe. Bump `CACHE_VERSION` and add a `v(N-1)→vN` branch whenever the
  persisted entry shape changes; unversioned legacy files must keep loading.

---

## Part C — Report-card grade state (`acm_database.json` session payload)

`acm_database.json`'s session payload is otherwise out of scope here, but the
report-card grade state added for the School MYP/School grades is recorded
because report cards depend on it.

### C.1 `effort_by_term` (persisted)

```jsonc
"effort_by_term": {
  "Term 1": { "<studentId>": 4 },   // int 0-5, Effort / English Use
  "Term 2": { "<studentId>": 5 }
}
```

- **Per-term**, mirroring `comments_by_term`: `term -> {sid -> int}`. Written
  by the Effort selectbox on Window 3's grade row; round-trips through
  `build_session_payload()` / `restore_session()` and is cleared by the full
  database wipe.
- A student with no stored value for the current term defaults to **4**
  (normal). Values are whole numbers 0–5; anything else read back is treated
  as unset (default 4).

### C.2 Derived grades (NOT persisted — recomputed on every read)

`student_term_grades()` (`app.py`) derives, for the current term:

| Value | Range | Derivation |
|-------|-------|------------|
| `n_criteria` | 2/3/4 (else grades are N/A) | Count of criteria with a final grade (override or auto band). |
| `crit_total` | int | Sum of those final grades, each `int(round(...))`-coerced — **always whole numbers**. |
| **MYP Grade** | int 1–7 or N/A | `myp_grade(crit_total, n_criteria)` — School's `MYP_GRADE_BOUNDS` lookup (no Effort). |
| **School Grade** | int 1–10 or N/A | `school_grade(crit_total, effort, n_criteria)` — `SCHOOL_GRADE_BOUNDS` on `crit_total + effort`. |

Both grades are whole numbers, shown identically in Window 3, the Excel
master's *Final Suggestions* tab, and the DOCX report exports — all read the
one shared helper. See [ARCHITECTURE.md §9](ARCHITECTURE.md).

### C.3 `unit_plans` (persisted) — parsed unit plans per class

Previously session-only, now round-tripped through `build_session_payload()` /
`restore_session()` (via `engine.persistence.unit_plan_to_dict` /
`unit_plan_from_dict`) so an uploaded plan survives a restart. Keyed by **class
name**; every value is a JSON-safe scalar/list/dict:

```jsonc
"unit_plans": {
  "Year 7 1-4 (2026-27)": {
    "unit_title":           "Changing Views",
    "statement_of_inquiry": "Perspective shapes meaning.",
    "target_criteria":      { "B": "Developing", "D": "Evaluating" },
    "key_concepts":         ["Communication", "Composition"],
    "myp_year":             "2",          // string or null
    "source_file":          "Y7_unit.docx" // informational only
  }
}
```

- Restore is defensive: a malformed entry is skipped rather than aborting the
  load, and `key_concepts` is filtered on read against a boilerplate drop-set
  (`key concept(s)`, `related concept(s)`, …) so plans persisted before the
  `_split_concepts` fix stop surfacing the leaked template label. Uploading a
  plan now also calls `persist()` immediately (durable without a later
  mutation).

### C.4 `llm_cfg` (persisted, minus the API key)

The LLM comment-generation parameters (`app.py::init_state`) now round-trip in
the session payload so tuned choices survive restarts. The **API key is never
persisted** — it lives only in `st.session_state["llm_api_key"]` (memory-only).
Restore **merges saved keys over the `init_state` defaults**, so a key added in
a future release keeps its default rather than being dropped by an older saved
file. Current defaults: `word_limit: 100`, `n_strengths: 1`, `n_growth: 1`,
`inc_trend: True`, `inc_late: True`, `inc_missing: True`, `no_numbers: False`,
`skip_existing: True`.

`skip_existing` (bool, default `True`, batch-only) controls the **"Generate for
whole class"** button: when set, students who already hold a non-empty overall
comment for the current term are skipped, so a re-run fills only the gaps. It has
no effect on the single-student generate button. Additive — old databases missing
the key default to skipping via `lc.get("skip_existing", True)`.

`no_numbers` (bool, default `False`) controls the **"Never mention numeric grades
in the comment"** toggle. When set, `compile_prompt()` appends an instruction to
`[OUTPUT REQUIREMENTS]` telling the model to describe achievement qualitatively
and to state no criterion grades, scores, marks, percentages or counts in the
comment body (the numeric evidence stays in the prompt for the model's
understanding). Additive — old databases missing the key default off via
`cfg.get("no_numbers", False)`.

`inc_missing` gates the `[MISSING WORK]` prompt block — the share of this term's
*assessed* tasks (submitted + missing) the student did not submit, plus the
unsubmitted task names. The count comes solely from `missing_assignment_rows()`
(Window 3's structural indicators), so Excused, ⏳ Awaiting Grade, formative and
unbanded-exam work are excluded; stored band-0 scores are never scanned. The
block is omitted entirely at 0 missing. Its OFF state removes *all* missing-work
signal from the prompt — the unsubmitted task names, formerly always appended
inside `[CURRICULUM CONTEXT]`, now live only in this block.

### C.5 `calc_method_by_term` (persisted)

```jsonc
"calc_method_by_term": {
  "Term 1": { "<studentId>": "Weighted Median" },  // an explicit per-student pin
  "Term 2": { }                                     // empty -> everyone on auto
}
```

- **Per-term, per-student** grading-method pins: `term -> {sid -> method-name}`,
  mirroring `effort_by_term` at all four sites (`init_state`,
  `build_session_payload()`, `restore_session()`, the full wipe). `method-name`
  is one of `CALCULATION_METHODS`; on load, unknown/renamed methods are dropped
  (that student silently reverts to auto).
- **Resolution order** (`calculation_method(sid)`): the student's stored pin for
  the current term when present and still a known method, **else the auto
  default**. There is no zero-argument form — every caller passes a student id.
- **Auto default** (`auto_calc_method()`): counts this term's *qualifying*
  assignments and picks **≤ 15 → `60/40 Recency`, > 15 → `Weighted Median`**.
  Recomputed live, so the 16th qualifying assignment flips auto students on the
  spot. *Qualifying* = On in the current term, criteria-bearing
  (assignment-table `criteria != "—"`, so formative events and still-unbanded
  exams are out), and **not** a `(Reflection)` task (an adjunct of its parent);
  banded exams count; counted overall, never per criterion.
- A **new term opens empty**, so everyone starts on auto — the "reset at a term
  boundary" falls out of the data shape for free.
- The legacy top-level **`calc_method`** key (the retired single global
  dropdown) is **ignored on load** — no migration. A teacher who had a global
  method re-pins it per student once.

### C.6 `work_aliases` + `unmatched_works` (persisted) — roster-aware identity routing

Two class-keyed stores added by Sync/anonymous plan Phase 3 (both in the
`acm_database.json` session payload; both wired through `init_state`,
`build_session_payload`, `restore_session`, `wipe_database_full`). They are the
identity analogue of the two-layer late-flags pattern (A.7): a **durable manual
layer** applied over **purge-replace** ingest.

```jsonc
"work_aliases": {
  "Y7 Art": { "0001a": "0001", "IMG0004050": "0002" }   // csv_key -> roster_key
},
"unmatched_works": {
  "Y7 Art": {
    "Essay 1": [                                          // assignment -> pool rows
      { "csv_key": "IMG0004050",
        "grades": [["A", 7]],                             // [[criterion, band], ...]
        "keywords": [], "comment": "", "files": "IMG0004050.jpg",
        "late": false, "timestamp": "2026-05-10T00:00:00" }
    ]
  }
}
```

- **`work_aliases[class] = {csv_key → roster_key}`** — the **durable** map of
  which anonymous work-key belongs to which roster student. Populated two ways:
  a **manual** match (`assign_work`, the Window-2 grid) and an **auto-recorded**
  fast-path **prefix** match at ingest (e.g. `0001a → 0001`, announced on the
  sync banner). **Never rebuilt** — it is the layer that must survive Sync's
  purge-replace, so a teacher's "this is theirs" call sticks across every later
  re-sync. Consulted by `ingest_csv` (step 2, before prefixing),
  `_sync_reconcile_late` (heal an aliased row's `Late` under the roster id), and
  `_publish_workspace_grades` (mirror the entry under the csv_key so CGW's
  reconcile finds the work).
- **`unmatched_works[class][assignment] = [pool-row dicts]`** — CSV rows that
  matched no roster student (ambiguous prefix or camera-roll garbage), each a
  self-contained dict carrying everything needed to re-materialize the score
  (`csv_key`, `grades` as `[[letter, band], …]`, `keywords`, `comment`, `files`,
  `late`, ISO `timestamp`). **Rebuilt** every time the assignment's CSV is
  (re)ingested — purge-replace applies to the pool exactly as it does to scores,
  and the CSV remains the durable source (losing a pool row never loses a grade;
  a re-sync re-derives it). Only rows that carried grades are pooled (a
  grade-less row minted no student before either). `materialize_row()` /
  `assign_work()` drain a row out of the pool into a real score under the roster
  id; the recorded alias then routes that csv_key automatically on the next sync.
- **Rosterless classes** never populate either store — `ingest_csv` skips routing
  when `roster_keys` is empty, and the score-only "folder-graded before a roster"
  path (ARCHITECTURE §10) stays intact. **Pre-Phase-3 phantom students** from
  past syncs are left as-is (routing only runs on a fresh (re)ingest with a
  roster present); the teacher archives them.

---

## Change discipline

When the CSV export or the cache schema changes, update this file **in the same
change** and keep the migration shims (`_normalize_grades`,
`_normalize_checklist`, the `Due Date`→`Assessed Date` fallback) working — old
files in the field are expected to keep loading.
