# Custom reporting classes

Status: implemented 2026-10-09; fictional tests only; no real database changes.
Prepared: 2026-10-09.
Implementation record follows below; the original agreed scope is retained for reference.

## Implementation record — 2026-10-09

All five phases are complete:

1. Added optional validated shared definitions, explicit member/source
   resolution, legacy compatibility and lifecycle preservation.
2. Added detached source contexts using the existing grading/export helper
   graph. Numerical policy remains shared; live grading context and score flags
   are unchanged on export success or failure.
3. Added Report for and the save/cancel management dialog, source selection,
   searchable member table, group-wide selection, five sort modes, position
   numbers/arrows and explicit list deletion.
4. Connected Excel, combined DOCX, email ZIP, saved comments and restricted
   single-student reports to the same ordered scope, with provenance, filenames
   and content-based cache invalidation. Custom Excel excludes Classroom Entry.
5. Added fictional acceptance coverage and an isolated Streamlit tray/dialog
   smoke test; updated the manual, data dictionary, architecture and changelog.

Implementation details: `engine/reporting.py` binds the transitive existing
read-only report/calculation helpers to detached session snapshots rather than
temporarily switching the live Streamlit session or duplicating grading math.
Source-group grading eligibility and selected-subset workbook statistics use
separate detached contexts. Same-title tasks stay separate by source group.

Deliberate release boundaries remain as agreed: manual membership setup only;
no school-workbook import, historical transfers or multi-year rollover. Legacy
scores that cannot be assigned unambiguously to a selected source group block
that report for teacher repair. All writing devices must be updated. Term
backups do not restore year-wide definitions; whole-database backups do.

Verification: 323 tests run, 322 pass and one existing Node.js-dependent check
is skipped. `git diff --check` passes. Workbook and DOCX/ZIP contents and styles
were checked through fictional round trips; UI verification used in-process
Streamlit AppTest rather than a full cloud-connected app launch.

Validation uses invented students and temporary database/preferences/workspace
paths, with Drive/cloud access disabled. No real roster, workbook, report or
student database was imported, migrated, populated or changed.

## Agreed workflow

Keep CAM's existing classes as **teaching groups**: 8.1, 8.2 and 8.3. Each
continues to own its roster, assignment folders, grading, draft feedback and
comment-generation context. Downloaded submissions stay in their group folders.

Add **custom reporting classes** in System deliverables. These are saved lists
of existing students drawn from teaching groups, with independent ordering.
For example, the teacher can assemble 8 Rocky and 8 Andes, then export their
final grades and already-saved comments. No student, grade or comment is copied
into a second gradebook record.

Decisions confirmed by the teacher:

- All three groups will be graded before final homeroom grades are submitted.
- Groups usually have similar assignments, but scheduling can leave one group
  with fewer assignments. Do not require equal counts, aligned dates or identical
  assignment titles across groups.
- A student is evaluated against work assigned to their own teaching group.
  Missing = 0 remains applicable to a genuine non-submission under CAM's existing
  policy. Work assigned only to another group is not applicable.
- Comments continue to be generated at teaching-group level. Reporting classes
  collect saved comments; they do not generate or rewrite them, introduce a
  homeroom comparison, or change the grading calculation method.
- Implement the feature later. This planning request does not authorize a real
  database migration, roster import or population of the reporting classes.

## User experience

At the top of System deliverables, add:

1. **Report for** selector: `Current teaching group — <active class>`, followed
   by saved entries such as `Custom — 8 Rocky` and `Custom — 8 Andes`.
2. **Manage reporting classes** button, opening a create/edit dialog.
3. A concise scope summary: reporting name, member count, contributing teaching
   groups and selected term. Display any unresolved members before export.

Keep the main Class/Level selector and the grading windows operating on teaching
groups. Changing Report for must not switch the grading class, focused student,
roster alias, unit plan, term, assignment On settings or comment-generation scope.

The management dialog should support:

- Create, rename and delete a reporting class. Delete removes the saved list
  only. Use explicit wording that its students and grades remain available.
- Choose source teaching groups, then search/select existing students in a table
  showing name, ID/email and source group. Allow group-wide selection followed
  by individual deselection. Support roster students without grades or with
  draft feedback only.
- A student appears once within a reporting class. The same student can belong
  to multiple reporting classes, allowing other legitimate report subsets.
- If an ID belongs to several source rosters, require an explicit source-group
  choice; never select the first matching class silently.
- Independently save ordering: manual/register order, surname A–Z, given name
  A–Z, gojuon using existing CAM behavior, or email. Provide editable unique
  position numbers plus move-up/down controls for exact school register order.
  Applying a sort must never change the source group's roster order.
- Save or cancel the complete edit. Unsaved dialog edits must not leak into
  durable state or existing download artifacts.

Use readable saved names instead of `custom class 1/2`. Default to the current
teaching group on a fresh session. Keep report selection ephemeral; persist the
saved definitions and ordering in the shared database.

For the first release, require source groups to have compatible subject, school
year level and MYP year metadata. Ask the teacher to resolve conflicting values
in class settings; do not guess a combined subject or grading context.

## Findings in the current code

These are implementation anchors, not a request for a broad architecture rewrite:

| Area | Existing behavior and implication |
| --- | --- |
| `engine/models.py` | `Gradebook.students` uses student ID as the key; `Assignment.class_name` owns the teaching-group link. Preserve both. |
| `app.py`: `render_tray` | All export buttons currently use `active_class` and `students_for_active_class`. Add a separate reporting selection. |
| `students_for_active_class` | Combines roster and score-derived membership with archive handling. Retain legacy behavior for default reports; custom lists use explicit membership. |
| `student_email_for`, `first_name_for` | Read only the active roster. Cross-group reports need explicit source-roster lookup. |
| `assignment_table`, term helpers, `missing_assignment_rows` | Depend on active class. Passing a mixed list of students alone cannot produce correct reports. |
| `aggregate_with_policy`, `student_term_grades`, trend helpers | Need the correct source-group and term context for every student. |
| `sync_active_into_scores` | Mutates `include_in_report` across scores using assignment names. A report build must not call this to change context. |
| `build_excel_bytes`, `_student_docx`, report-card/ZIP/comment builders | Read active metadata and other implicit context. Pass resolved reporting data explicitly. |
| `comments_by_term` and `teacher_remarks` | Store saved comments by student ID. Reuse these directly; group-level generation remains unchanged. |
| `Assignment.draft_feedback` | Holds assignment-specific draft comments, distinct from overall report comments. Preserve this distinction and existing export behavior. |
| `_export_slot` and mail-merge cache | Context keys are currently too small to detect membership/order/content changes. Add a report-content fingerprint. |
| `build_session_payload`, `restore_session`, `init_state` | Explicitly select durable session fields. Register the new store in all relevant paths. |
| `engine/persistence.py`: `_validate_session` | Validate new stored definitions using the existing privacy-preserving issue format. |

## Data contract

Add an optional `session.reporting_classes` store, defaulting to an empty list
when absent. Use a stable UUID for each reporting class, distinct from its label.
Proposed shape (fictional placeholders only):

```json
{
  "reporting_classes": [
    {
      "id": "<uuid>",
      "name": "Example homeroom",
      "sort_mode": "manual",
      "members": [
        {"student_id": "fictional-001", "source_class": "Example group"}
      ]
    }
  ]
}
```

The member-list order is the saved manual/register order. Other sort modes
derive output order without rewriting the manual order. Do not duplicate names,
emails, scores, draft feedback, overall comments or whole roster rows in this
store. Resolve current display details from the referenced student and source
roster at report time. Require unique IDs per reporting class and nonempty,
case-insensitively unique reporting names. Reject invalid sort modes and shapes.

Definitions are year-wide within the current database, rather than term-specific
membership histories. Changing a list changes subsequent exports for any term;
existing downloaded reports remain snapshots. Historical group transfers and
automatic multi-year rollover are outside this release.

Compatibility and lifecycle:

- Old databases load without this key. Do not perform a startup write merely to
  insert it. Use existing checked saves and snapshots when the teacher saves a
  real edit. Keep the current envelope version if additive compatibility permits.
- Whole-database save/load, dirty fingerprinting, conflict recovery and full
  replacement must preserve the store. Older app versions may drop an unknown
  session field when saving; document that all writing devices must be updated.
- Source-class rename must update member references in the same existing rename
  operation. Reporting-class rename changes no folders or assignments.
- Source-class deletion, student removal/archive or broken references must leave
  a visible unresolved-member entry. Do not silently delete the reference,
  include an archived student, pick another source or omit someone from a final
  report. Require the teacher to repair/remove that entry before building the
  affected custom report. Unaffected reports remain available.
- Full database wipe clears the new store. Term-only restore leaves definitions
  untouched; document that term backups do not recover year-wide custom lists.
- Do not create custom-class folders or include reporting classes in grading
  workspace seeding, cloud assignment scans, ownership indexes or class mirrors.
  Whole-database backups retain the definitions.

## Report computation and assignment boundaries

Introduce a small, UI-free reporting module, for example `engine/reporting.py`,
with data structures/helpers for `ReportScope`, resolved members and student
report data. The app adapter builds an immutable snapshot of the required
gradebook/session state. Existing UI helpers may retain default wrappers, but
the underlying report calculation must accept explicit context.

For each member, resolve:

- Student identity and roster metadata from the selected source group.
- That group's assignments, selected term, On choices, archival state and unit
  plan. Preserve each assignment's actual date and grading status.
- Existing calculation method, final overrides, effort, valid-score handling,
  late/excused state and numerical aggregation rules.
- Saved per-term comments and teacher remarks by student ID.
- Group-specific draft feedback as qualitative evidence only; never turn a
  draft or comment-only submission into zero or count it numerically.

The reporting class controls **membership, ordering and report labels**. It must
not control which assignments a student was expected to submit. A synthetic
union of the three groups' assignments must never become every student's
expected-work list. Use existing awaiting-grade behavior when work is unfinished.
Do not add a mandatory assignment-parity or all-groups-finished gate; the teacher
decides when to submit final reports.

Do not temporarily rewrite `st.session_state.active_class`, roster/unit-plan
aliases, score flags or saved comments while iterating students. Export must be
read-only, including when a builder fails halfway through. Avoid duplicating
grading policy in a second exporter implementation; share explicit-context
helpers with the existing default path.

Current assignment identity needs care: assignment objects carry a class, but
several score/session lookups use assignment name alone. In reporting, retain
`(source_class, assignment_name)` identity, restrict analytics to members of that
source group and do not merge same-title assignments from different groups.
Resolve existing name-keyed settings according to their current persisted
semantics. Explicitly filter copied report evidence by source group and term so
it cannot inherit another active class's report flags. If a student's legacy
evidence cannot be assigned unambiguously, surface the ambiguity rather than
guessing. A global assignment-ID or subject-scoped student-data migration is a
separate project, not part of this feature.

## Deliverable behavior

| Deliverable | Custom reporting-class behavior |
| --- | --- |
| Excel: Final Suggestions | Selected members in saved output order; each student's grades use their source group. Include source-group provenance. |
| Excel: Raw Scores | Selected members and their source-group evidence only. Preserve the existing history-oriented coverage and label it clearly; this is not automatically a current-term-only ledger. |
| Excel: Assignments | Separate rows for source-group assignments; include source group and compute statistics over selected members from that group. Same-title tasks remain separate. |
| Excel: Classroom Entry | Keep this a teaching-group tool. Omit it from custom-class workbooks with an explanatory caption in the tray; default teaching-group Excel retains its existing sheet and Latin name order. Homeroom subsets are unsuitable for direct Classroom column pasting. |
| Combined report-card DOCX | One student report at a time in saved order; show reporting class and teaching group. Use the student's source unit plan, marks, graph and saved term comment. |
| Mail-merge ZIP | Same selected members and source context; retain email filenames, duplicate/invalid email checks and existing grade visibility rules. ZIP entry order follows the selected order, though ZIP viewers may sort filenames. |
| Class comments DOCX | Collect the same saved all-term comments and teacher remarks currently exported, in custom order. No LLM call or regeneration. Label the report class. |
| Single-student report | In custom mode, offer a student selector restricted to resolved custom members. Default mode continues to use the focused student. Do not export an unrelated focused student under a homeroom label. |

Preserve draft feedback in the original assignment/workspace. Do not silently
reinterpret it as an overall term comment. Adding new draft-feedback sections to
deliverables is outside this change unless separately requested.

All titles, scope captions and filenames must reflect the chosen reporting
class. Include term in filenames and disambiguate sanitized-name collisions.
Keep current report styles and export-on-click behavior.

Fingerprint cached output using the resolved scope ID/label, ordered members,
source contexts, selected term, relevant grades/assignments/comments/roster data,
report settings and calculation options. This must detect unsaved in-memory
edits too; database generation or member count alone is insufficient. Apply the
same invalidation rule to every export, including ZIP and single-student output.

## Initial setup and the supplied workbook

Manual selection from the existing CAM rosters is required in the first release.
The school workbook can be consulted locally to identify homeroom membership and
exact register order. The teacher should confirm active membership before setup:
the reference includes formatted status cues and some summary labels may be stale.
No automatic deletion, merging or creation of students from this document.

Optional follow-up: a preview-only spreadsheet mapping assistant, committed only
after teacher review. Use the current-year Year 8 homeroom and teaching-group
blocks, not legacy sheets. Prefer ID/email matches where available; this reference
uses names and register numbers, so name matches need confirmation against CAM
IDs. Register numbers are local list positions, not unique student IDs. Surface
struck-through rows and ambiguous/unmatched names explicitly. Import only approved
membership/order, never grades or duplicate student records. This assistant is
not necessary to ship custom reporting classes.

## Implementation sequence

Complete these phases in order, with focused checks after each. Re-read repository
instructions and current code before starting because the code may have changed.

1. **Scope and persistence.** Add validated definitions, member resolution,
   lifecycle behavior and round-trip coverage. Preserve legacy loading and all
   database safety mechanisms.
2. **Explicit report context.** Extract shared context-dependent calculation and
   roster lookup helpers. Prove same-student default/custom grade equivalence
   and no state mutation before wiring the UI. Cover unequal assignment counts
   and same-title assignments across groups at this stage.
3. **Management UI.** Add selector, member picker, independent sorting/manual
   ordering, save/cancel, rename/delete and unresolved-member feedback.
4. **All deliverables.** Wire Excel, combined DOCX, ZIP, comments and single report
   to resolved report data; update labels, subset analytics and cache invalidation.
5. **Verification and documentation.** Run focused and relevant existing tests,
   inspect fictional exports and perform an isolated UI smoke test. Update the
   user manual, data dictionary, architecture notes and changelog. Record completed
   phases and any remaining limitations in this plan.

Do not finish after merely adding the dropdown: all listed outputs must use the
same resolved membership and appropriate per-student source context.

## Acceptance tests

Use fictional fixtures only, including three teaching groups with deliberately
different assignment counts, dates and one repeated assignment title. Include
students with no grades, draft-only feedback, true missing work, excused work,
unfinished grading, exams, saved comments and final overrides.

- A student's numerical results match between the source-group and custom-class
  exports. Fewer assigned tasks alone create no zeros. A true missing eligible
  task retains CAM's current zero policy.
- Other groups' tasks, dates, comments and unit plans never leak into that
  student's report. Same-title tasks have separate analytics by source group.
- Custom comments exactly preserve the saved text. No LLM call occurs, and
  comment-generation buttons still use the main teaching group.
- Manual and each supported sort order persist through reload and apply across
  every relevant output. Changing order preserves all student-to-data mappings.
- Default exports retain their membership and Classroom Entry behavior. Custom
  Excel omits Classroom Entry and reports the selected subset accurately.
- Source-roster email lookup works when the grading UI is focused on a different
  group. Mail-merge warnings and grade visibility restrictions remain intact.
- Duplicate IDs, ambiguous source membership, archives and missing references
  follow the defined validation/resolution behavior, without silent data loss.
- Scope, term, membership, order, name, grade, draft status, saved-comment and
  settings changes invalidate affected downloads, including equal-count swaps.
- Export success and injected failure leave durable content, active grading
  context and score inclusion flags unchanged. Selecting a report scope alone
  does not trigger a database save.
- Old database loads, save/reload, source rename, term restore, conflict recovery,
  full replacement and wipe preserve the documented lifecycle contract.

Relevant existing suites include roster order, deliverable style, draft
assessments, exam reports, term backup, database validation, dirty persistence,
snapshots/concurrency/cloud safety, and class mirrors. Prefer existing mocked
session and temporary-directory patterns. Audit setup isolation before running
tests that initialize the app. Do not add tests that merely mirror field setters.

For an app launch, set `CAM_DB_PATH` to a fresh temporary folder, use temporary
device preferences and fictional rosters, and ensure every master directory,
mirror, watch folder and grading-workspace path also resolves inside the sandbox.
Disable real Drive/OAuth access. If isolation cannot be verified, do not launch.

No implementation test may write, migrate or clean up the real database. A later
approved real-data operation requires a timestamped backup beside the database
per AGENTS.md, without pruning existing backups. Keep the supplied workbook,
roster mappings, student identities and generated real reports outside git.

## Prompt for the later implementation session

> Implement `docs/CUSTOM_REPORTING_CLASSES_PLAN.md`, using its agreed workflow
> and acceptance criteria. Read AGENTS.md first. Keep 8.1/8.2/8.3 as teaching
> groups; custom reporting classes select and order existing students for all
> System deliverables. Each student retains their own group's assignment and
> grading context even when groups have different amounts of work. Keep comment
> generation at teaching-group level and export saved comments unchanged. Work
> through the phases, test with fictional data in an isolated temporary database,
> and update documentation. Do not migrate or populate my real database or copy
> my roster into git. Report the implemented behavior, checks and limitations.
