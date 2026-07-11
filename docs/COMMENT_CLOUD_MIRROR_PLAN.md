# Comment & teacher-input cloud mirror — plan v1

**Status:** v1, in progress (target: Opus 4.8 High running Claude Code, this
public checkout). All file/line anchors verified against this tree on
2026-07-11. **Phase 1 landed 2026-07-11** (engine payload v2 + unit tests);
**Phase 2 landed 2026-07-11** (app mirror-on-autosave + `llm_response` drop +
app-level tests); Phases 3–4 pending.
**Companion plan:** `docs/TERM_BACKUP_RESTORE_PLAN.md` (explicit term
backup/restore button — separate, implement after this one).

---

## 1. Why (incident follow-up)

The 2026-07-10 DB wipe (`docs/CROSS_DEVICE_AND_DB_SAFETY_PLAN.md`) destroyed
every AI-generated report comment. Grades self-healed — Sync rebuilds scores
from the export CSVs in each class folder — but **human-typed content that
lives only in the DB session has no cloud twin and cannot be rebuilt**:

| Session state | Shape | Rebuildable after a wipe? |
|---|---|---|
| `comments_by_term` | `{term: {sid: text}}` | ❌ lost 2026-07-10; hand-recovered from docx exports |
| `teacher_remarks` | `{sid: text}` (flat, not per-term) | ❌ |
| `effort_by_term` | `{term: {sid: int}}` | ❌ |
| `final_override` | `{sid: {criterion: band}}` | ❌ |
| Score comments typed in CAM (Edit grade dialog) | `sc.comment` inside gradebook score entries | ⚠️ only if the workspace was re-launched for that assignment afterwards (`_publish_workspace_grades`, `app.py:1824`) so CGW's next export carries them |

Losing `comments_by_term` also breaks a feature: the Term 2/3 comment
generation folds the previous term's comments into the prompt
(`[PREVIOUS TERM FINALIZED SUMMARY]` blocks, `app.py:4515`), so lost Term 1
comments silently degrade every later term's generation.

**Root cause is dead code, not missing architecture.** The per-class cloud
summary system already exists and its *read* path is fully wired; only the
*write* path died when the Finalize button was removed (`app.py:6841`
"No Finalize button any more"). Nothing in the tree calls
`save_term_summary` — hence zero `acm_term_summaries_*.json` files exist in
any teacher data folder.

## 2. Terrain (verified anchors)

| Thing | Where | Notes |
|---|---|---|
| Per-class summary file writer/loader | `save_term_summary` / `load_term_summaries` / `term_summary_path`, `engine/persistence.py:351-423` | Atomic tmp+replace; blanks dropped; term replaced wholesale; **currently never called (writer)** |
| Summary file read path in app | `class_term_summaries`, `app.py:1155` | Reads `class_data_dir(cls)` first, falls back to `db_folder()` |
| Prior-term prompt context | `prior_term_context`, `app.py:1165`; prompt blocks `app.py:4372,4515,4569` | Prefers cloud file, falls back to in-session `comments_by_term` |
| Per-class data folder | `class_data_dir`, `app.py:396` | `[db folder]/[class name]/` — where grade CSVs + grading caches already live |
| Session payload build/restore | `build_session_payload` `app.py:713`; `restore_session` `app.py:751` | `llm_response` (line 724) is a full duplicate of the current term's comment map (~85 KB of the live 770 KB DB) |
| Legacy alias handling on load | `app.py:857-863` | `comments_by_term` wins; `llm_response` only a fallback for pre-multi-term DBs |
| In-app alias repoint | `app.py:2038` | `ss["llm_response"] = ss["comments_by_term"][active term]` on term switch |
| Autosave | `persist`, `app.py:879` | Fires after every mutation; has the Phase-3 shrink tripwire |
| Boot hydrate + load-guard | `app.py:690-702` | `diagnose_db_load` quarantine (`db_load_blocked`) before `restore_session` |
| Comment generation loop | `app.py:6669` | Batch writes into `ss["llm_response"]` (aliased into `comments_by_term`) |
| Edit-grade dialog (score comments) | `app.py:6119` | CAM-side `sc.comment` edits |
| Terms | `TERMS`, `app.py:102` | `["Term 1", "Term 2", "Term 3"]` — every assignment/comment is term-tagged |
| Window 3 header | `render_window3`, `app.py:6027`; name line `app.py:6040` | For Phase 5 (email) |
| Email lookup | `student_email_for`, `app.py:1233` | Roster-backed; Student records carry only the email-derived id |

## 3. Design

One per-class JSON in each class's own subfolder — **reuse
`acm_term_summaries_<class>.json`** (read path, prompt integration and
placement come free) — extended to carry every non-rebuildable teacher input:

```jsonc
{
  "version": 2,
  "class_name": "Year 7 1-4 (2026-27)",
  "updated_at": "<iso>",
  "terms":          { "Term 1": { "<sid>": "<overall comment>" } },   // v1 key, unchanged
  "remarks":        { "<sid>": "<teacher remarks>" },                  // flat, like the session map
  "effort":         { "Term 1": { "<sid>": 3 } },
  "final_override": { "<sid>": { "A": 7 } },
  "score_comments": { "<assignment>": { "<sid>": { "A": "<text>" } } } // non-empty sc.comment only
}
```

Write direction: **mirror on autosave** (piggyback `persist()` — catches every
mutation path). Read direction: **heal on load** (fill blanks only). The DB
session stays the runtime source of truth; the class files are its durable
cloud twin.

### Safety invariants (non-negotiable)

1. **Heal before mirror.** A freshly-wiped or demo session must never push its
   emptiness over good class files. The first mirror in a session may only run
   after the heal pass has completed. If the boot is quarantined
   (`db_load_blocked`), no mirror ever runs.
2. **Mirror shrink tripwire.** Refuse to rewrite a class file when the new
   payload would drop a term's comment count below half of what the file
   holds, unless comments were explicitly deleted in-app during this session
   (track a session flag at the deletion call sites). Refusal surfaces on
   `save_status`, never raises.
3. **No churn.** Skip the file write when the mirrored slice is unchanged
   (per-class fingerprint in session state, seeded after heal). These folders
   are OneDrive-synced; rewriting identical bytes on every grade edit creates
   sync noise and version-history spam.
4. **Never raises.** Like `load_term_summaries`, every mirror/heal failure
   degrades gracefully (status message at most) — a cloud hiccup must not take
   down autosave.

## 4. Phases

### Phase 1 — Engine: payload v2 (`engine/persistence.py`) ✅ done 2026-07-11

- ✅ Extended the summary-file module to read/write the v2 shape. Added
  `load_class_mirror` (full-payload loader, always returns the canonical
  5-section shape; v1 files load transparently with empty new sections) and
  `save_class_mirror` (full-payload writer, cleans + writes `version: 2`).
  `load_term_summaries` is now a thin `{term: {sid: comment}}` view over
  `load_class_mirror`, and `save_term_summary` loads-merges-saves the full
  mirror so it **preserves** the new sections instead of clobbering them — both
  public names still work. Both exported from `engine/__init__.py`.
- ✅ Same atomicity (tmp + `os.replace`) + blank-dropping semantics. Cleaning
  drops blank text leaves and empty containers; `effort`/`final_override`
  coerce to whole ints (bool rejected, numeric strings accepted).
- ✅ Unit tests (`tests/test_class_mirror.py`, stdlib `unittest` — no pytest in
  this env): v2 round-trip, v1-file backward-compat load, malformed/non-dict
  file → `{}`, blank-dropping, atomic replace (no tmp leftovers, original file
  intact on write failure). Run: `python -m unittest tests.test_class_mirror`.

### Phase 2 — App: mirror on autosave (`app.py`) ✅ done 2026-07-11

- ✅ `build_class_mirror(cls)` assembles the v2 slice from session state +
  gradebook (`comments_by_term`/`teacher_remarks`/`effort_by_term`/
  `final_override` filtered to the class's sids; `score_comments` from that
  class's students' score entries, non-empty only). Class sids = the roster
  **plus** the class's archived (departed-but-grades-kept) students, so a
  departed student's typed comment still earns a cloud twin and archiving never
  trips the shrink tripwire.
- ✅ `_mirror_classes_to_cloud()` runs from `persist()` after a successful DB
  write, enforcing all four invariants: heal-before-mirror + no-quarantine
  (`mirror_ready` / `db_load_blocked`, invariant 1), the shrink tripwire
  (`_mirror_shrink_would_lose`, invariant 2), the no-churn per-class fingerprint
  (`mirror_fingerprints`, invariant 3), and never-raises (per-class try, refusal
  surfaces on `save_status`, invariant 4). Deletion tracking
  (`_mark_teacher_input_deleted` → `mirror_deletions_this_session`) fires at the
  overall-comment box, the remarks box, `wipe_database_full`, and `delete_class`.
- ✅ Dropped the `llm_response` duplicate from `build_session_payload` — the
  loader already prefers `comments_by_term` and keeps `llm_response` as a
  read-only legacy fallback; the in-memory alias repoint (`ensure_term_context`)
  is untouched, so the live alias is still rebuilt every rerun. ~11% DB size
  reduction for free.
- ✅ App-level tests (`tests/test_app_mirror.py`, stdlib `unittest`; `app.st` /
  `app.gb` / `app.class_data_dir` swapped for doubles — no Streamlit runtime):
  slice roster-filtering + score-comment scoping + archived capture; first-boot
  backfill; no-churn (file mtime untouched across many passes); not-ready and
  quarantined boot write nothing; shrink tripwire blocks a mass loss and the
  deletion flag lets it through; mirror failure never raises. Run:
  `python -m unittest tests.test_app_mirror`.

### Phase 3 — App: heal on load (`app.py`)

- In the boot hydrate (`app.py:690-702`), after `restore_session`: for each
  class, load its mirror and fill **blank slots only** in
  `comments_by_term`, `teacher_remarks`, `effort_by_term`, `final_override`.
  Session text always wins over file text when both are non-blank.
- Score-comment heal runs after Sync's reconcile pass (Sync purge-replace can
  rebuild scores without CAM-typed comments): fill `sc.comment` when blank.
- Seed the mirror fingerprints from the healed state (so a heal alone doesn't
  immediately trigger a rewrite of identical content).
- One-shot backfill falls out naturally: on the first boot after this lands,
  fingerprints are unseeded → first `persist()` writes all class mirrors,
  giving the 120 restored Term 1 comments their cloud twins. Verify this
  explicitly in tests.

### Phase 4 — Window 3: student email under the name

- `app.py:6040`: below `### {student_label(student)}`, render the roster email
  (`student_email_for`, `app.py:1233`) when non-empty, click-to-copy
  (`st.code(email, language=None)` gives a copy icon; if too tall for the
  dense cockpit, a caption + the existing clipboard-button helper). Blank
  email → render nothing.

## 5. Testing & guardrails (CLAUDE.md rules apply)

- **Never run the app against the real data folder.** All AppTest/manual runs
  use a temp `db_custom_path` (see `cam-test-environment` conventions: real
  prefs point at live data; AppTest single-run only; console is cp932 — set
  `PYTHONIOENCODING=utf-8`).
- Engine tests carry the load; app-level tests simulate: (a) wipe → relaunch →
  comments/effort/remarks/overrides healed from mirrors; (b) fresh empty DB +
  populated class folders → healed; (c) in-app deletion → mirror updated →
  heal does NOT resurrect; (d) unchanged session → class files' mtimes
  untouched across many autosaves; (e) quarantined boot → no mirror writes;
  (f) demo session pointed at a folder with good mirrors → tripwire blocks the
  empty overwrite.
- Acceptance: delete `session.comments_by_term` from a sandbox DB copy,
  relaunch sandboxed app → Window 3 shows every comment; prompt for Term 2
  contains the Term 1 `[PREVIOUS TERM FINALIZED SUMMARY]` block sourced from
  the class file.
