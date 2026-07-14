# Database Concurrency Safety Plan

## Status

Proposed implementation plan. This document describes the work required to
protect the CAM database from stale writes and cloud-synchronization conflicts.
It does not indicate that the safeguards have already been implemented.

## Purpose

CAM is commonly used on a school laptop, on a school network, and occasionally
from a second computer at home. The database may be stored in a folder managed
by OneDrive or another file synchronization service. In that environment, two
valid application sessions can independently load the same database and later
attempt to save different versions of it.

The existing backup, quarantine, shrink-detection, and mirror safeguards protect
against several destructive failures. They do not fully prevent a valid but
stale session from overwriting newer work when the stale copy has a plausible
size and valid structure. This plan addresses that risk first, without
attempting an automatic data merge.

## Primary failure scenario

1. Session A and session B both load database revision N.
2. Session A records new grading work and saves revision N+1.
3. Session B still contains the older revision N in memory.
4. Session B makes a different change and attempts to save.
5. Without a concurrency check, session B can replace revision N+1 with a
   structurally valid database derived from revision N.

The existing shrink tripwire may not detect this. The stale database can contain
the same number of records as the current database, or even more records, while
still losing newer scores, comments, or configuration changes.

## Safety invariants

The implementation must preserve the following invariants:

1. A session may overwrite the shared database only when the database is still
   the exact generation that the session loaded or most recently saved.
2. A concurrency conflict must preserve both the current shared database and
   the session's pending changes.
3. CAM must never silently merge conflicting score or comment data.
4. Boot diagnosis, validation, mass calculation, and hydration must operate on
   the same immutable database snapshot.
5. Once an installation expects an established database, a temporarily missing
   cloud file must not be treated as a legitimate first run.
6. Unchanged Streamlit reruns must not rewrite the database.
7. Malformed records and unsupported future schemas must never be silently
   skipped and then replaced by a reduced database.
8. Existing shrink, backup, quarantine, and mirror protections must remain in
   force unless a reviewed replacement provides equivalent or stronger safety.
9. Tests and development runs must never use a teacher's real database.
10. Existing backup files must never be pruned as part of this work.

## Scope

The first implementation release covers:

- a single-read immutable boot snapshot;
- persistent database identity and generation metadata;
- optimistic concurrency checks before every shared-database write;
- safe conflict recovery that preserves both versions;
- expected-database and cloud-conflict detection;
- dirty-only persistence;
- verified session safety snapshots;
- strict schema and record validation;
- isolated concurrency and recovery tests; and
- corresponding architecture and data-dictionary updates.

The following work should be handled separately after the first release:

- stable UUIDs for classes and assignments;
- migration away from assignment-name identity;
- comprehensive mirror identity and sanitized-directory collision changes;
- finer-grained mirror shrink protection; and
- concurrency protection for every CAM Grading Workspace state file.

These structural migrations should not be combined with the immediate stale
writer fix. Keeping them separate reduces migration, review, and recovery risk.

## Design requirements

### 1. Immutable database snapshot

The persistence layer should expose a snapshot operation that reads the
database bytes once and derives all boot information from those exact bytes.
The snapshot should contain, at minimum:

- raw or canonicalized content used for deserialization;
- database identity;
- schema version;
- generation or revision token;
- a strong content hash;
- file metadata useful for diagnostics, but not used as the sole concurrency
  token; and
- validation results.

Boot diagnosis must not inspect the file, read it again for validation, and read
it a third time for hydration. A cloud client can replace the file between
those operations. The validated object graph must be derived from the captured
snapshot.

### 2. Database identity and generation

Each established database should contain a stable, randomly generated database
identifier. It should also contain a monotonically changing generation value or
an equivalent canonical content-generation token.

The implementation plan must define:

- how an existing version-1 database without this metadata is recognized;
- when the identifier is created;
- whether the schema version changes;
- how the first upgraded write is protected;
- how future schema versions are rejected safely; and
- how metadata is included in backups and restored databases.

An upgrade must not be run against a real database during development. When the
feature is eventually used with a real database, any format migration must first
create and read-back verify a timestamped pre-upgrade backup.

### 3. Optimistic concurrency check

Every session should retain the database identifier, generation, and content
hash it loaded or most recently saved. Immediately before a write, CAM should
capture a fresh on-disk snapshot and compare it with the expected token.

The write may proceed only when:

- the on-disk database identifier matches the session's database identifier;
- the generation or expected content hash matches;
- the on-disk database passes validation; and
- all existing shrink and storage-safety checks pass.

If the comparison succeeds, CAM may write the next generation using the
existing atomic replacement mechanism. A lock file may be used as an additional
local coordination aid, but it must not be the sole protection. Cloud services
do not guarantee that a lock observed on one device is immediately observed on
another.

### 4. Conflict behavior

If the on-disk database differs from the session's expected generation, CAM
must not overwrite it. Instead, it should:

1. leave the shared database unchanged;
2. serialize the session's pending state to a timestamped, collision-proof
   conflict-recovery file;
3. read-back verify that recovery file;
4. put the session into a safe read-only or conflict state;
5. display a plain-language explanation that another device or tab saved newer
   work; and
6. provide recovery instructions without claiming that the two versions were
   merged.

The message should be suitable for a teacher rather than a database specialist.
It should identify the recovery file and advise closing other CAM sessions,
allowing cloud synchronization to finish, and reviewing both versions before
choosing a recovery action.

Automatic last-writer-wins behavior and automatic record-level merging are out
of scope.

### 5. Expected database and missing cloud files

CAM must distinguish between:

- a genuine first run where no database has ever been created or adopted; and
- an established installation whose expected database is temporarily absent.

After a database has been created or adopted, local device state should retain
the expected database identifier and location. If that database later appears
missing, CAM must enter quarantine rather than create a new empty database in
the same folder. Recovery should require the expected database to reappear or
an explicit teacher action to adopt or create a database.

### 6. Cloud conflict siblings

At boot and before a write, CAM should inspect the configured database directory
for likely synchronization conflict copies. Detection should be conservative
and should exclude recognized CAM files such as:

- timestamped backups;
- conflict-recovery files created by CAM;
- intentional safety or block-marker files; and
- other documented CAM sidecars.

If an unrecognized database-like sibling is present, CAM should enter a warning
or quarantine state. It must not automatically select, merge, rename, or delete
the file.

### 7. Dirty-only persistence

Application reruns that have not changed persistent state must not rewrite the
database. Mutating operations should mark the appropriate state dirty. The dirty
flag should clear only after a successful, concurrency-checked, atomic save.

Failed saves, blocked saves, and recovery-file saves must not incorrectly mark
the shared database as current.

### 8. Verified session safety snapshot

Before the first database-changing save in an application session, CAM should
create a timestamped and collision-proof snapshot of the current shared
database. The snapshot must be read back and validated before the changing save
can proceed.

This complements the daily rotating backup. A once-per-day backup may predate
substantial grading work performed earlier on the same day. Failure to create a
required safety snapshot must block the changing save and show a recoverable
error; it must not be treated as best effort.

### 9. Strict schema validation

Database deserialization must explicitly recognize supported schema versions.
It must quarantine unsupported future versions rather than attempting a partial
load.

Malformed records must be reported as validation failures with their structural
paths. CAM must not silently skip malformed students, assignments, scores, or
comments and then autosave the reduced in-memory result. Diagnostic messages
must avoid exposing student data unnecessarily.

Any migration mechanism must be explicit, tested, backward-compatible where
documented, and protected by a verified pre-migration backup.

## Implementation phases

### Phase 0: detailed design

Review the current persistence implementation and tests, then record:

- the proposed snapshot API;
- database metadata and schema changes;
- backward-compatibility behavior;
- conflict and recovery filenames;
- teacher-facing states and messages;
- test fixtures and two-session simulation strategy;
- exact files expected to change; and
- one commit boundary per phase.

No production implementation should occur until this design is reviewed.

### Phase 1: single-read boot snapshot

Implement the immutable snapshot abstraction and change boot diagnosis,
validation, mass calculation, and hydration to use it. Preserve current behavior
apart from eliminating repeated reads of the live cloud file.

Completion criteria:

- boot reads the database content once;
- tests demonstrate that all decisions use the captured bytes;
- an on-disk replacement after capture cannot change the object hydrated from
  that snapshot; and
- existing isolated persistence tests continue to pass.

### Phase 2: stale-writer protection

Implement database identity/generation handling and the compare-before-write
protocol. Add safe conflict-recovery output and the teacher-facing conflict
state.

Completion criteria:

- sessions A and B both load generation N;
- A saves generation N+1;
- B's later save is rejected;
- the N+1 shared database remains unchanged;
- B's pending version is preserved in a verified recovery file;
- a same-sized or larger stale database is still rejected; and
- the shrink tripwire remains active.

### Phase 3: missing and conflicted cloud files

Add expected-database state and conservative detection of database-like cloud
conflict siblings.

Completion criteria:

- a genuine first run is still supported;
- an established but temporarily missing database enters quarantine;
- CAM does not create an empty replacement automatically;
- explicit adoption of an existing database remains possible;
- an unexpected conflict sibling produces a safe state; and
- the expected database can recover normally after synchronization completes.

### Phase 4: dirty persistence and session snapshots

Track persistent mutations and avoid saves during unchanged application reruns.
Create and verify the session safety snapshot before the first changing save.

Completion criteria:

- unchanged reruns perform no shared-database write;
- mutations remain dirty until a successful shared save;
- failure to create or verify the required snapshot blocks the changing save;
- snapshot names cannot collide during rapid consecutive sessions; and
- no existing backup is deleted or pruned.

### Phase 5: validation, documentation, and final review

Implement strict version and record validation, then update:

- `docs/ARCHITECTURE.md`;
- `docs/DATA_DICTIONARY.md`;
- this plan if the reviewed implementation differs; and
- relevant user or recovery documentation.

Review the complete change specifically for stale writes, time-of-check versus
time-of-use errors, accidental first-run initialization, partial database
acceptance, failed backup paths, Windows/OneDrive filename behavior, and student
data exposure.

## Test plan

All tests must set `CAM_DB_PATH` to a temporary directory and must not load the
user's saved preferences. The application must not be launched unless isolation
from real data is guaranteed.

Required automated scenarios include:

1. Two sessions load the same generation and only the first can save.
2. The second session's unsaved state is recoverable after rejection.
3. Equal-sized and larger stale databases are rejected.
4. A database changed between boot snapshot capture and later hydration does
   not alter the captured result.
5. A database changed between load and save blocks the save.
6. A genuine first run can explicitly create a new database.
7. An established database that is temporarily absent enters quarantine.
8. The expected database can reappear and be loaded safely.
9. A likely cloud conflict sibling is detected without being modified.
10. Recognized CAM backups and sidecars do not create false conflict warnings.
11. An unchanged Streamlit rerun does not write the database.
12. A failed shared save leaves the session dirty.
13. Failure to create or validate the session snapshot blocks the changing
    save.
14. A malformed record prevents a destructive partial load/save cycle.
15. An unsupported future schema enters quarantine.
16. A supported legacy database follows the documented upgrade path.
17. A successful save remains atomic and advances the generation exactly once.

## Release gate

The build must not be used with school data until, at minimum, the following
behaviors are demonstrated by automated tests and a code review:

1. Two sessions load the same revision, and only the first can save to the
   shared database.
2. A temporarily missing cloud file never causes CAM to create a replacement
   empty database automatically.
3. A malformed or future-version database is never silently rewritten.
4. Every rejected concurrency save leaves both the current shared database and
   the teacher's pending changes recoverable.

Before release, run the complete test suite in an isolated temporary database
environment. Record any test modules that cannot run because of missing
dependencies; do not compensate by launching CAM against real preferences.

## Suggested Codex execution workflow

Use GPT-5.6 Sol with Medium reasoning in one implementation branch, for example
`codex/db-concurrency-safety`. Work through one phase at a time and stop for
review after each phase. Each task should restate the database safety rules,
required tests, and completion criteria rather than asking Codex to implement
the entire plan in one pass.

Recommended commit boundaries are:

1. immutable snapshot and boot tests;
2. revision comparison, conflict recovery, and two-session tests;
3. expected-database and conflict-sibling detection;
4. dirty-only persistence and verified session snapshots; and
5. strict validation, documentation, and final regression fixes.

Run a focused review before every commit and a branch-wide concurrency and data
integrity review before release.
