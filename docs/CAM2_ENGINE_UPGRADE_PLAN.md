# Upgrading CAM's vendored CAM2 to the latest dev version: assessment and plan

**Status:** v3, 2026-11-05. Decisions D10–D16 (§5) are locked by the teacher. v3
changes D10, D11 and D13: a paper's repeated levels stay on the exam, and the teacher
decides one grade per criterion for the assignment in Window 3. It also adds D16: an
exam is whatever goes through CAM2, and a draft is a normal assignment without grades.
The smaller points
(§5.1) go ahead on the stated default unless the teacher changes them. Nothing is
built yet.
**Repos:** CAM = `criterion-assessment-metrics`; CAM2 = `cam2-exam-grading`,
vendored in CAM at `exam_grading/`.
**Depends on:** [CAM2_EXAM_CONVERGENCE_PLAN.md](CAM2_EXAM_CONVERGENCE_PLAN.md). This
plan keeps its numbering and amends its D3 and D4. It also feeds
[SLIDE_DECK_EXAM_PLAN.md](SLIDE_DECK_EXAM_PLAN.md), which is not built yet.

Read `CLAUDE.md` first. Phases 0 and 6 touch real data, and the sandbox, backup and
permission rules there apply. Never edit `exam_grading/` in place: change CAM2,
then `git subtree pull`.

Line numbers below refer to CAM `origin/main` at `2554d46`.

---

## 1. Verdict

**The code can be pulled cleanly, but it must not ship without CAM changes.**

The pull itself is easy: no conflicts, no local edits to lose, no new runtime
libraries. The problem is that CAM2 `v0.3.0-dev` changed what a rubric level and an
exam's `mode` mean, and `engine/exam_bridge.py` relies on the old meanings. Without
changes:

- rubric exams reach CAM with no grades to confirm;
- a teacher can lose a grade already in the gradebook, with no warning;
- mixed papers lose marks or levels;
- a session can't go back once CAM2 has opened it.

CAM's test suite catches only the first of these, so a green-looking run would be
misleading. Marks-only exams without weighting read correctly.

The teacher's decisions add one new piece of work. Window 3 has to show every level
and criterion mark on a paper, grouped by criterion, and let the teacher decide one
grade per criterion for that assignment. This is the core of Phase 3. The gradebook
keeps one grade per criterion per assignment, so the overall grade isn't worked out
from dozens of slide levels.

## 2. Where things stand

| | Commit | Date | Notes |
|---|---|---|---|
| CAM `origin/main` | `2554d46` | 2026-11-01 | Release `v2026.11.01` plus docs and one CAM2 test-fixture pull |
| CAM2 pinned in CAM | `1a40845` | 2026-11-01 | Vendored tree is byte-identical to this commit (`f513ea4`) |
| CAM2 `v0.3.0-dev` | `0555e7c` | 2026-11-03 | Test build with colleagues now |
| CAM2 `main` | `7d34779` | 2026-11-04 | 21 commits past the pin; only docs differ from the tag |

What the 21 commits add: exam sections, weighting, mixed papers (each question
graded with marks or a rubric), a new student report and gradebook, report options,
packaging, licence notices and sample exams. Session files go to **version 2**.

### What stays compatible

Checked in a sandbox (§7):

- `git subtree pull` onto `origin/main` merges with no conflicts, and the result
  matches CAM2's tree exactly.
- `exam_grading/requirements.txt` is unchanged.
- Every CAM2 function the bridge calls still exists. `engine/host.py` is unchanged,
  and `launcher.py --host` and "Send to CAM" still work.
- Marks-only exams read identically on both engines (15/20 on each).
- Reading is still read-only: a session folder is byte-identical after CAM reads it.
- CAM2's own suite passes in its vendored location (328 tests, 1 skipped).

## 3. What CAM can do today

### 3.1 What CAM reads from a new session

Each row is a fictional session built with CAM2's engine and read by today's
`exam_bridge.read_session`.

| Exam | What CAM2 holds | What CAM gets |
|---|---|---|
| Marks only | 15/20 | 15/20, correct |
| Rubric, final level typed | Levels 5 and 6, final 7 | `final_levels {r1: 7}`, correct |
| Rubric, no final level typed | Levels 5 and 6 | `final_levels {}`: nothing to confirm |
| Mixed, started as Rubric | Q1 level 5, Q2 8/10 | Total 0/0; Q2 filed as `levels {"null": 8}` |
| Mixed, started as Marks | Q1 8/10, Q2 level 6, final 6 | 8/10; the level and the final are dropped |
| Mixed, no starting choice | Q1 9/10, Q2 level 4 | 9/10; the level is dropped |
| Weighted 50/50, 10/10 and 0/40 | 50.0% | 10/50, so CAM works from 20% |

### 3.2 What the gradebook can hold

These answer the teacher's questions of 2026-11-04.

| Question | Today | Needed |
|---|---|---|
| Can one exam have grades on Criteria A, B, C and D? | **Yes, from the rubric panel.** It writes one grade per mapped criterion, and a test covers it (`test_exam_cam2_host.py:361`). Window 3 then shows one row per criterion | Nothing |
| Is Window 3's grade entry limited to one criterion? | **No.** Each criterion listed on the exam gets its own row and edit dialog. It can only offer criteria already on the exam, though | Criteria arrive from CAM2 (Phase 3) |
| Is Window 1 limited to one criterion? | **The marks panel is.** "Counts toward criterion" takes one letter, and Apply deletes the exam's grades on every other criterion (`app.py:7540-7541`). The rubric panel isn't | Fix (I2) |
| Can one exam have several grades on one criterion? | **No.** They save and load (5 of 5 kept), but the screens break (I12) | Not needed: each criterion gets one decided grade (D10) |
| Can CAM keep every level on a paper? | **Yes.** `ExamResult.levels` holds each question's levels, and Window 3 lists them question by question (`app.py:8740`). They aren't grouped by criterion, and no grade can be decided from them there | Phase 3 |
| Can marks sit on a criterion? | **No.** A gradebook grade must be a whole number from 0 to 8 (`models.py:53-61`), so 15/20 can't be one. Marks stay on the exam record, which has no per-criterion marks | New field (D13) |

## 4. Issues

| # | Issue | Severity |
|---|---|---|
| I1 | Rubric exams arrive with no levels | Blocker |
| I2 | Apply can delete a grade with no warning | Blocker (data loss) |
| I3 | Mixed papers lose or misfile results | Blocker (data integrity) |
| I4 | Opening a session upgrades it for good | Blocker for rollout |
| I5 | Launcher hands exams to whichever version is running | High, **live today** |
| I6 | Weighted exams: CAM and CAM2 disagree | High |
| I7 | Tests don't guard any of this | Medium |
| I8 | Criterion marks are ignored | High (was Medium; D13 needs them) |
| I9 | Licence notices missing from CAM's bundle | High, **live today** (was Medium) |
| I10 | Documents describe the old behaviour | Low |
| I11 | This Mac's `main` is 24 commits behind | Precondition |
| I12 | Several grades on one criterion would break the screens | Avoided by D10 (new) |
| I13 | A student waiting for a grade can count as Missing = 0 | High (new) |
| I14 | CAM2 can't take slide-shaped pages yet | Precondition for slide decks (new) |

### I1. Rubric exams arrive with no levels

CAM2 no longer averages levels or suggests a final level. This is deliberate:
"a level should be a best-fit judgement against the descriptors, not arithmetic"
(CAM2 `Exam-Section-Plan.md`). `final` is now only what the teacher typed. **Overall
criterion results**, the option that shows the final-level column in Step 5, is off
by default.

CAM's D4 assumed a suggested level always exists. So with an ordinary rubric exam:

- the Window 1 panel shows `—` for every student (`app.py:7624-7627`);
- Apply reports "Graded 0 student(s)".

Old sessions behave the same once re-read: a v1 session that gave
`final_levels {r1: 6}` on the pinned engine gives `{}` on the new one, unless the
teacher had typed the level.

### I2. Apply can delete a grade with no warning

`_apply_exam_rubric_levels` removes all of this exam's scores for a student
(`app.py:7665-7666`), then adds back only the rubrics found in `final_levels`
(`app.py:7659-7662`). That was safe while every rubric had a level. It isn't now.

Reproduced through CAM's own test harness:

| Step | Pinned engine | New engine |
|---|---|---|
| Apply A and C | A 6, C 6 | A 6, C 6 |
| Re-send; only C has a typed final level | `final_levels {r1, r2}` | `final_levels {r2}` |
| Apply again | A 6, C 6 | **C 6 only; A's grade is gone**, reported as `applied=1` |

With no final levels at all, the scores survive, but `score_count` drops to 0
while the grades remain. This is the most serious issue, because the teacher sees a
success message.

### I3. Mixed papers lose or misfile results

`mode` is now only the "starting choice" and says nothing about any one question; a
question grades with marks if it has a `max`. `read_session` still branches on the
exam-wide mode (`engine/exam_bridge.py:135-178`). See the mixed rows in §3.1.

The `{None: 8}` case is the worst. `_validate_exam_result` only checks the values in
`levels`, not the keys, so the mark passes validation and is saved under a rubric
called `"null"`. The panel and Window 3 also choose their layout from the exam-wide
`r.mode` (`app.py:3588`, `7454`, `8771`).

### I4. Opening a session upgrades it for good

Run with real launcher processes: opening a v1 session in new CAM2 rewrites
`cam2_session.json` to version 2 at once, with no grading and no clicks beyond
opening it. After that:

- the pinned CAM reads `file_from_newer_version`;
- Sync's fingerprint changes, so an upgraded CAM re-reads it and hits I1.

The failure is safe: on a read error Sync skips the folder and changes nothing
(`app.py:4282-4287`). But another computer on an older CAM can't read that exam until
it's updated, and all it shows is the code `file_from_newer_version`.

### I5. The launcher hands exams to whichever version is running

CAM and the standalone download share one app-data folder (`CAM2 Exam Grading`), so
they share one `server.json`. `running_instance()` checks that a CAM2 answers, not
which version.

Reproduced: the launcher from the pin handed its exam to a running `0.3.0-dev`,
which opened it and upgraded it, so that CAM could no longer read its own exam. CAM2's
`PLAN.md` lists this as "not yet reproduced"; it is now.

**This doesn't wait for the upgrade.** Any computer with `v2026.11.01` and a
standalone `v0.3.0-dev` running can hit it today. Colleagues are trying that build
now. See the interim advice in Phase 0.

### I6. Weighted exams: CAM and CAM2 disagree

With weighting on, CAM2's result is a percentage from section shares. CAM still
suggests a band from the raw total (`ExamResult.suggested_band`), so the example in
§3.1 is 50% on the student's report and 20% in CAM. This breaks the convergence
plan's rule that CAM's numbers always match CAM2's. D12 removes the suggestion.

### I7. Tests don't guard any of this

At CAM2 `main`, 2 of CAM's 267 tests fail (`test_exam_bridge.py:214`,
`test_exam_cam2_host.py:370`), and both are I1. Nothing covers I2, I3, I5, I6 or
I13. Updating those two tests would turn the suite green with every other issue still
in place.

### I8. Criterion marks are ignored

Marks questions can be ticked on a criterion, and CAM2 reports marks per criterion
(`rubrics[id].marks`, with weighted shares when weighting is on). CAM ignores this.
D13 now carries them over.

### I9. Licence notices missing from CAM's bundle

- **All three published CAM releases (`v2026.07.14`, `v2026.07.14.1`, `v2026.11.01`)
  install PyMuPDF.** It's in `cam_grading_workspace/requirements.txt`, and since
  `v2026.11.01` in `exam_grading/requirements.txt` too. CAM2's notice says PyMuPDF is
  available under the AGPL or a paid licence from Artifex, and CAM2 therefore licenses
  its download as a whole under the AGPL.
- CAM's bundle contains only the two MIT `LICENSE` files. It has no AGPL text, no
  list of third-party libraries, and no pointer to the source for PyMuPDF and MuPDF.
  The release notes don't mention it either. CAM2's own downloads do all of this.
- `exam_grading/licences/NOTICE.txt` describes CAM2's own download, with its zip
  names and tags, so it can't ship unchanged inside CAM's bundle.
- `EXAM_DEV_PATHS` (`tools/build_windows_bundle.py:53`) doesn't cover the new
  `Exam-Section-Plan.md` or `requirements-build.txt`, so both would ship.
- CAM's `>=` ranges resolve to whatever is current when the bundle is built, so a
  notice listing exact versions wouldn't stay true. CAM2 solves this by pinning exact
  versions for its builds in `requirements-build.txt`.

D15 and Phase 4 fix this for new releases. §5.1 P5 covers the published ones.

### I10. Documents describe the old behaviour

- `USER_MANUAL.md` and `QUICK_GUIDE.md` (and its PDF): the exam flow.
- `DATA_DICTIONARY.md:150`: `final_levels` as "teacher's, else CAM2's round-half-up
  suggestion".
- `ARCHITECTURE.md` §4.
- The docstring at `app.py:7560`.
- The convergence plan's D3 and D4, which D10 and D11 amend.
- `SLIDE_DECK_EXAM_PLAN.md` was written against the pinned CAM2. Its step 6 and D6
  need rereading against D10 to D13, and its Phase 3 grade-owner lock moves from the
  Window 1 panel to the Window 3 decision. Its D10 and D13 use the old draft label (P8).

### I11. This Mac's `main` is 24 commits behind

Local `main` (`6f4f39d`, 2026-10-29) has no `exam_grading/` or `exam_bridge.py`.
All 24 missing commits are the convergence work, which also changes CAM's database
handling. Updating is a real step if this checkout runs against real data, so it's
in Phase 0 and not done casually.

### I12. Several grades on one criterion would break the screens

v2 of this plan carried each slide level into the gradebook as its own grade. D10 no
longer does, so none of this needs fixing. It's kept as the reason for that decision.

The data layer copes: five grades on B from one exam save and load, and the
calculation counts all five. Everything keyed on (student, exam, criterion) doesn't.
The first three rows were checked with fictional data, and the others come from the
code:

| Where | What happens with B 3, 4, 4, 5, 4 from one exam |
|---|---|
| Window 3 grade rows (`app.py:8585`) | **The whole window crashes.** Every row uses the key `cell_<exam>_<crit>`, and Streamlit raises `StreamlitDuplicateElementKey` |
| Window 3 edit dialog (`find_score`, `app.py:8508`) | Opens the first grade (3), whichever row was clicked |
| Excel "Classroom Entry" (`app.py:5544`) | **Shows 3 only**, with no sign that there are four more |
| Rubric panel (`app.py:7608`) | Keeps one grade per criterion, then Apply deletes the rest |
| Marks panel (`app.py:7540`) | Apply deletes all of them |

Repeated grades would also swamp the year. With two earlier assignments at 7 and a
deck on Criterion B:

| Deck | Simple average | 60/40 recency | Weighted median | EMA |
|---|---|---|---|---|
| One grade, 4 | 6.00 | 5.80 | 7.00 | 6.10 |
| Five slide levels, all 4 | 4.86 | 4.71 | 4.00 | 4.50 |

### I13. A student waiting for a grade can count as Missing = 0

`missing_assignment_rows` (`app.py:3414`) treats an exam as Missing = 0 for a student
with no grade on it, once any classmate has one. A paper not yet finished in CAM2 is
already caught by this. It matters much more under D10: a student waiting for the
teacher's decision would count as 0 on every criterion listed on the exam. Once one
criterion is decided, the student stops counting as missing, so any undecided criterion
just stays out of the calculation.

### I14. CAM2 can't take slide-shaped pages yet

CAM2 `main` has no 16:9 or 4:3 page sizes and no `papers_folder` hand-off. Both are
Phase 1 of the slide-deck plan, not part of the 21 commits. This upgrade gets a deck's
results into CAM correctly, but the Y8 and Y9 portfolios also need that plan's CAM2
and Drive phases, or PDFs prepared by hand.

---

## 5. Decisions

Numbering continues from the convergence plan. D10–D15 were locked by the teacher on
2026-11-04. On 2026-11-05 the teacher changed D10, D11 and D13 and added D16.

- **D16 · An exam is whatever goes through CAM2.** This is the difference between the
  types in Window 1:

  | Type | What it is | Graded in | Grades |
  |---|---|---|---|
  | Assignment | Normal assignment | Grading workspace | Yes |
  | Assignment without grades | Normal assignment, such as an art lesson draft | Grading workspace | No, comments only |
  | Exam | Any exam, including a visual art final report imported from Google Drive | CAM2 | Yes, per D10 |

  A visual art final report is an exam, even though it's a slide deck and not a written
  paper. Today every exam already opens in CAM2 (`app.py:7701`, `7755`). A folder watched
  on Drive can't yet be made an exam, which the slide-deck plan's D13 and Phase 2 add.
- **D10 · The teacher decides each criterion's grade for the assignment, in Window 3.**
  (amends D4) The teacher using CAM2 chooses the criterion rubrics option, and records
  marks or levels on the paper.
  - **The paper's levels stay on the exam record.** They're evidence for the decision,
    not gradebook grades, and they never enter the overall calculation.
  - **Window 3 groups them by criterion** for the student in focus, then asks for one
    decision: `Criterion B · Screen 01: 5 · Screen 02: 4 · Screen 03: 5 · Screen 06: 4 ·
    Screen 07: 6`, then a 0–8 dropdown for this assignment's Criterion B.
  - **That decision is the one gradebook grade** for that student, assignment and
    criterion. The later overall grade works from these, as with any other assignment.
  - **A final level typed in CAM2** is already a decision, so it carries over as that
    grade. Window 3 shows it, and the teacher can change it there.
  - **Nothing decided:** nothing is written, the criterion stays out of the calculation,
    and an existing grade stays as it is.

  CAM never averages or suggests. A question marked Not answered, or not counted because
  of a choice group, stays visible in Window 3 and isn't part of the decision.
- **D11 · A paper can carry everything at once.** (amends D3) Marks and any number of
  levels on any criteria can sit on one paper, and all of it reaches CAM. Marks ticked
  on a criterion show under that same criterion in Window 3, next to its levels. Marks
  and levels are never converted into each other. Several rubrics or marks may map to
  one criterion, so the "two rubrics" check goes: they share one group and one decision.
  If two rubrics on one criterion both have a typed final level, neither is written.
  Window 3 shows both, and the teacher decides.
- **D12 · Weighted marks are never converted by the app.** Weighting belongs to CAM2's
  sections. CAM shows CAM2's weighted result beside the raw total
  (`weighted 50.0% · raw 10/50`) and never bands from either. A teacher may add
  weighted marks into a final mark for a criterion, then set the level by hand, either
  as a final level in CAM2 or in Window 3. In CAM2, weighting is switched on for a paper and
  shared across at least two sections with marks (`weighting_on`), so the rule applies
  to that paper's marks whenever it's on. This replaces the earlier recommendation to
  band from the percentage.
- **D13 · Criterion marks carry over.** This is the teacher's main use: rubric grading
  across the slides of Y8 and Y9 final-report portfolios, as well as written papers. A
  new optional `ExamResult.criterion_marks` holds each criterion's marks as CAM2
  reports them. They show in Window 3 in that criterion's group, next to any levels.
  They aren't gradebook grades. Only the teacher's 0–8 decision enters the calculation.
- **D14 · Pin the CAM2 version with all the fixes applied.** That is the new tag from
  Phase 1, not `7d34779`.
  - CAM's bundle runs CAM2 from source under its own Python, so it needs **no compiled
    CAM2**. CAM2 is built only for its own standalone downloads.
  - **Windows is needed for three steps:** building CAM's bundle
    (`tools/build_windows_bundle.py` refuses to do a full build anywhere else), booting
    that bundle, and building CAM2's Windows download. Mac builds can run on this Mac.
    Whoever is doing the work tells the teacher when a Windows step is reached.
- **D15 · Include every legal statement and licence notice needed.** Phase 4 gives
  CAM's bundle its own `Licences` folder, modelled on CAM2's. This is engineering work
  following CAM2's existing approach, not legal advice. The paid licence from Artifex
  remains the alternative if the AGPL ever becomes unsuitable.

### 5.1 Points that go ahead on a default

These came up while working through the decisions. Each default stands unless the
teacher changes it.

- **P1 · How repeated levels count. Settled in v3:** they don't count directly. The
  teacher's decision is the only grade per criterion (D10), so a deck counts as one
  assignment, however many slides it has.
- **P2 · What stays in Window 1.** *Default: the rubric-to-criterion mapping, a progress
  count per criterion ("18 of 28 decided"), and one Apply button for final levels typed
  in CAM2.* Rubrics named `Criterion A` to `Criterion D` map by themselves, so a deck
  graded only with levels needs nothing here. A fully automatic write of typed levels
  isn't safe, because someone must confirm the mapping.
- **P3 · Plain marks exams.** *Default: an exam with no marks on any criterion keeps
  Window 1's class-wide marks panel, but without the pre-filled band.* Today each
  dropdown starts at `suggested_band()`, and Apply writes it even if the teacher never
  touched it. That is the app converting marks into a grade. The dropdown starts blank,
  and blank writes nothing. This is the one change for marks-only exams.
- **P4 · Rubrics that don't go to 8.** *Default: Window 3 lists their levels as given
  (`Screen 03: 5/6`), and the teacher decides on 0–8, so nothing is scaled.* Only a
  final level typed in CAM2 on such a rubric is still scaled, as today
  (`exam_bridge.to_band`), and the panel shows it. The teacher may prefer a refusal.
- **P5 · Published releases.** *Default: no change until the teacher agrees.* Phase 0
  proposes adding the notices to the `v2026.11.01` release page, and the zip stays as
  it is until the next release. Editing a public release needs the teacher's go-ahead.
- **P6 · Changes after a decision.** *Default: the decision stays, and Window 3 flags it
  ("levels changed since you decided").* A re-send never changes a grade the teacher set
  in CAM. A paper not finished in CAM2 shows its levels, but can't be decided until it's
  finished and sent again, as today.
- **P7 · No average beside the dropdown.** *Default: Window 3 shows the levels and no
  calculated figure*, which keeps D10's "never averages or suggests". An average could
  be added later as a read-only aid if the teacher wants it.
- **P8 · The draft label.** *Default: "Draft — comments only" becomes "Assignment —
  no grades" in Add assignment and ⋯ Manage (`app.py:7119`, `7313`), to match D16.* Only
  the wording changes. Existing drafts keep working, because the stored `is_draft` flag
  stays the same.

---

## 6. Phases

Order: 0 → 1 and 2 (independent of each other) → 3 → 4 → 5 → 6. One commit per phase,
with tests. Phases 2 and 3 land on the **current pin** so the reader is right before
anything new arrives, the same order the convergence plan used.

### Phase 0 — Prepare and take stock · S

- Give the interim advice now (I5): close standalone CAM2 before using CAM's exam
  button, and don't open CAM-hosted exams in standalone `v0.3.0-dev`.
- List every computer that uses CAM, with its CAM and standalone CAM2 versions.
- Update this checkout to `origin/main`, once it's confirmed what it runs against.
  With real data, this needs the teacher's go-ahead and a backup first (`CLAUDE.md`).
- Add a read-only `tools/` script that counts, per class folder: sessions by version
  and mode, sent or not, and rubric exams with grades already applied. It reports
  counts only, no names. Test it on fictional data. Running it on real folders needs
  explicit permission.
- With the teacher's go-ahead (P5), add the notices to the `v2026.11.01` release page.

*Done when:* we know how many real sessions are exposed to I1, I2 and I4.

### Phase 1 — CAM2: safe hand-over, tagged · S–M (CAM2 repo)

- Fix the first "next build" item in CAM2's `PLAN.md`: `running_instance()` compares
  versions through `/api/ping`, and a different running version is stopped and
  replaced after saving, or refuses the hand-over with a clear message.
- Include the other fixes waiting at that point. If the teacher wants slide decks in
  the same CAM2 version, add the slide-deck plan's Phase 1 here (I14).
- Tests for both directions: older launcher with newer server, and newer with older.
- Cut the new CAM2 tag (D14) and build its downloads: Mac here, **Windows on a Windows
  computer**. Share it with colleagues, since they're the ones exposed.

*Done when:* the I5 reproduction no longer upgrades or misroutes a session.

### Phase 2 — CAM: correct Apply, bridge and storage, on the current pin · M

- **Fix I2 first.** Apply replaces a student's grades only on criteria with a new
  decision, and leaves the others alone. `score_count` counts real grades. The marks
  panel stops deleting other criteria.
- **Fix I3.** `read_session` routes per question from the shape of `question_values`
  (a `None` key means marks), not from `mode`, and reads marks and final levels
  whenever they exist. This works on both engines.
- Report the exam's mode as `marks`, `rubric` or `mixed`. An older CAM treats
  anything but `rubric` as marks, which is safe.
- **Say where a grade came from.** Add optional `CriterionScore.exam_value` (the final
  level CAM2 sent, if any). An older CAM ignores it on load and drops it on save, so a
  grade without it counts as the teacher's.
- **Re-send rule.** For each student and mapped criterion:
  - a typed final level fills an empty grade, or updates one CAM2 sent earlier
    (`value` equals `exam_value`);
  - a grade the teacher set or edited in CAM is kept and listed, never overwritten
    silently;
  - levels and marks never write a grade;
  - nothing new changes nothing.
- Add optional fields to `ExamResult`: `percent`, `weighted` and `criterion_marks`
  (D12, D13). Records already in a database must load unchanged, and an older CAM must
  still load new ones.
- `_validate_exam_result` rejects non-string keys in `levels` and `final_levels`.
- **Fix I13.** A student with an exam result and no grade shows as ⏳ awaiting decision
  and stays out of the calculation, not Missing = 0.
- Tests: turn §3.1 and the I2 table into permanent tests, and add one that nothing ever
  writes a second grade for one student, exam and criterion. Those needing a v2 session
  skip until `model.VERSION >= 2`, then run from Phase 4.

*Done when:* the I2 reproduction keeps both grades, and marks-only and rubric behaviour
on the current pin is otherwise unchanged. The I2 fix can ship by itself.

### Phase 3 — CAM: decide per criterion in Window 3 · M–L

- **Window 3 exam block** (D10, D11, D13, P4, P6, P7). Under `📝 <exam>`, one group per
  mapped criterion:
  - each question's level or mark, by its label, plus criterion marks and the weighted
    result, all read-only;
  - one 0–8 dropdown for this assignment's grade on that criterion, blank until decided,
    with no suggestion. Choosing a level writes the one `CriterionScore`. Choosing blank
    clears it;
  - a final level typed in CAM2 shown as the current decision, labelled as from CAM2;
  - the "levels changed since you decided" flag.

  Levels on a rubric mapped to no criterion are listed apart, with a pointer to Window
  1. The existing rows with each question's comment stay available below the groups.
- **Keep everything in step.** A decision updates `asg.criteria` and `score_count`, so
  the grade rows above, Window 2 and the exports agree. No other screen changes, because
  the gradebook still holds one grade per criterion.
- **Window 1 panel** (P2, P3). The mapping, with several rubrics allowed on one
  criterion; the progress count; and Apply for typed final levels, with a summary of what
  it will change before it writes. An exam with no marks on any criterion keeps the
  class-wide marks panel, with blank dropdowns.
- Route from the Phase 2 mode (`app.py:3588`, `7454`, `8771`). Show ⏳ awaiting decision
  (I13).
- Rename the draft type (P8), including Window 3's `· Draft ·` caption and the message
  at `app.py:8644`.
- Round-half-up for any new percentage display, not Python's `round()`.
- Sandbox browser check: temp prefs, temp `db_custom_path`, fictional class. Include
  the 12-screen fixture from the slide-deck plan. Its A 1, B 5, C 2 and D 5 levels must
  end as at most one gradebook grade on each criterion, with the calculated grade the
  same however many slides fed the decision.

*Done when:* a deck's levels show grouped in Window 3, one decision writes one grade, a
blank dropdown can't invent a grade, and a re-send can't change a teacher's decision.

### Phase 4 — Pull CAM2, notices, bundle · M–L

- `git subtree pull --prefix exam_grading <cam2> <tag> --squash`, then confirm the
  vendored tree hash equals the tag's.
- Update `test_exam_bridge.py:214` and `test_exam_cam2_host.py:370` to the new rules,
  and un-skip the v2 tests.
- Add `Exam-Section-Plan.md` and `requirements-build.txt` to `EXAM_DEV_PATHS`, and
  extend `test_windows_bundle.py`.
- **Notices (D15).** The bundle gains a `Licences` folder, with:
  - a notice written for CAM's bundle: CAM and CAM2 are MIT, PyMuPDF is used under the
    AGPL, and so the bundle as a whole is under the AGPL;
  - `AGPL-3.0.txt`, and CAM's and CAM2's MIT licences;
  - third-party notices for **everything in the bundle**, including CAM's own
    libraries (Streamlit, Plotly, Matplotlib, the AI clients and so on) and the embedded
    Python, not only the CAM2 list;
  - where the source is: CAM and CAM2 are public, each release has a matching tag, and
    the PyMuPDF and MuPDF source archives are attached to the release, as CAM2 does.
- **Keep the notices true.** Pin exact versions for the bundle build, as CAM2's
  `requirements-build.txt` does. The build fails if any bundled package has no licence
  entry, or if the versions in the notice don't match what's installed. A test covers
  this.
- **Say where they are.** Add a short line in English and Japanese in the README, the
  bundle's start-up instructions and CAM's About or Help area, with the same wording
  approach as CAM2's READ ME FIRST. Release notes mention the licence.
- `python tools/run_all_tests.py` passes, including with PyMuPDF 2.0.
- Sandbox end to end with `exam_grading/tools/make_sample_exam.py` and a real browser:
  marks; rubric with and without final levels; levels on one criterion across many
  questions; marks ticked on a criterion; mixed from both starting choices; weighted;
  choice groups; and a v1 session upgraded mid-grading. Each must Sync, be decided in
  Window 3 or carried by Apply, and show in Windows 2 and 3, leaving session folders
  byte-identical after Sync.
- **On a Windows computer:** build the bundle and boot it with its embedded Python. CAM
  starts, CAM2 opens in host mode and sends to CAM, and the `Licences` folder is there.

*Done when:* the whole matrix passes. Nothing is released yet.

### Phase 5 — Documents and release notes · S–M

- Rewrite the exam parts of `USER_MANUAL.md` and `QUICK_GUIDE.md` (and its PDF),
  `ARCHITECTURE.md` §4 and `DATA_DICTIONARY.md`, and the `app.py:7560` docstring.
- Mark D3 and D4 as amended in the convergence plan. Update `SLIDE_DECK_EXAM_PLAN.md`
  for D10 to D13.
- Add `CHANGELOG.md` and release notes that say plainly:
  - update **every computer before opening an exam**, because opened exams can't go
    back;
  - exams go through CAM2, and "Draft — comments only" is now "Assignment — no grades";
  - a paper's levels show in Window 3, and the teacher decides one grade per criterion
    for the assignment, unless a final level was typed in CAM2;
  - marks are never turned into grades by the app, and bands are no longer pre-filled;
  - what `file_from_newer_version` means on a computer not yet updated.

### Phase 6 — Roll out to real data · S (explicit permission required)

"Testing the app" isn't permission. Each step needs the teacher's go-ahead in that
session.

1. Update every computer, and the standalone CAM2 on each.
2. Back up: `acm_database.json.bak-cam2-upgrade-YYYYMMDD-HHMMSS` beside the database,
   and a dated copy of each class's `exams/` folder **before any exam is opened**.
   Never prune existing `.bak-*` files.
3. Open one low-stakes exam. Check its counts against the Phase 0 numbers, and that its
   existing gradebook grades are unchanged.
4. Then open the rest as needed. Grades already applied from older rubric exams stay as
   they are, and neither a re-send nor Apply replaces them silently.

**Rollback:** revert CAM to the previous release and restore `exams/` from the step 2
copy. A v2 session can't be opened by older code. CAM2 also leaves a v1 copy in
`backups/` when it upgrades, but that backup is per day, so don't rely on it. Grades
entered after the upgrade would need re-entering.

*Done when:* all computers are updated and every sampled exam matches its numbers from
before the upgrade.

---

## 7. How this was checked, and what wasn't

Everything ran in a throwaway clone with `HOME` and `CAM2_APP_DATA` redirected to a temp
folder, on fictional data. The real prefs and database were checked before and after
and are unchanged, and neither repo's code was modified.

| Suite | Pin `1a40845` | CAM2 `main` `7d34779` |
|---|---|---|
| CAM | 267 pass (1 skipped) | **2 failures**, both I1 |
| CAM2 | 216 pass (1 skipped) | 328 pass (1 skipped) |

I2 was reproduced through CAM's test harness with saving stubbed out. I4 and I5 were
reproduced with real launcher processes. §3.1 came from probes against the real bridge.
For I12:

- The save format, calculation methods and Classroom Entry and `find_score` selection
  rules were run with fictional grades, using copies of the last two.
- The crash was confirmed with Streamlit's test runner on the same key pattern, not by
  opening the full app.

I13 and the other rows in the I12 table come from reading the code. Licence findings
come from each release's tagged `requirements.txt` and file list and from the bundle
tool's source. The published zips themselves weren't opened.

**Not checked:**

- The Windows bundle or Windows itself. All of this ran on macOS with Python 3.14.8;
  the bundle uses 3.14.6.
- PyMuPDF 2.0 and Pillow 13.0. The test environment has 1.28.2 and 12.3.0.
- The Streamlit panels and CAM2's screens in a browser. Panel behaviour above comes
  from reading the code and calling the functions behind it.
- Any real session or database, so how many real exams are exposed is unknown until
  Phase 0.
- The Japanese screens.
- CAM2's I5 fix, and everything in Phases 2 to 4, none of which exists yet.
- Whether the licence approach is legally sufficient. D15 follows what CAM2 already does.
