# Upgrading CAM's vendored CAM2 to the latest dev version: assessment and plan

**Status:** v5, 2026-11-05. Decisions D10–D17 (§5) are locked by the teacher. v5 adds
the Google Apps Script route that turns Classroom submissions into PDFs (Appendix A). v3
changed D10, D11 and D13: a paper's repeated levels stay on the exam, and the teacher
decides one grade per criterion for the assignment in Window 3. v4 corrects D16: a
draft keeps the label "Draft — comments only" and is set up from a normal assignment.
It also adds D17: CAM2 learns slide-shaped pages first, and fetching from Drive waits.
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
| I14 | CAM2 doesn't recognise slide-shaped pages | Precondition for slide decks; fixed in Phase 1 (new) |

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
  Window 1 panel to the Window 3 decision. Its D13 offers Draft as a third type, which
  D16 changes, and its order changes with D17.

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

### I14. CAM2 doesn't recognise slide-shaped pages

CAM2 `main` knows only A4, B5 and A3, and it reads PDFs and images, not `.pptx` files.
Tested with fictional PDFs at 13.333 × 7.5 in, 10 × 5.625 in and 10 × 7.5 in:

- **None of them is detected.** `detect_paper` returns nothing, so the teacher has to
  pick a paper size that isn't true.
- **Cropping does work.** With A4 landscape chosen, a whole-page box gives the whole
  slide at the right shape (2667 × 1500 for PowerPoint's 16:9). So a deck can be sliced
  today as a stop-gap, though this was tested in the engine and not on CAM2's screens.
- **The grid is the wrong shape.** On a 16:9 page, A4's cells come out 1.24 times wider
  than they are tall, so boxes don't line up with the slide's own layout.

Phase 1 fixes this (D17).

---

## 5. Decisions

Numbering continues from the convergence plan. D10–D15 were locked by the teacher on
2026-11-04. On 2026-11-05 the teacher changed D10, D11 and D13 and added D16 and D17.

- **D16 · An exam is whatever goes through CAM2.** This is the difference between
  exams and assignments in Window 1:

  | What it is | Set up as | Graded in | Grades |
  |---|---|---|---|
  | Normal assignment | Assignment | Grading workspace | Yes |
  | Draft, such as an art lesson draft | Assignment, with **Draft — comments only** ticked | Grading workspace | No, comments only |
  | Any exam, including a visual art final report | Exam | CAM2 | Yes, per D10 |

  - **A draft is a normal assignment with a check mark, not a type of its own.** The
    teacher creates a new assignment, or uses a row from auto-sync, and ticks **Draft —
    comments only**. That wording stays. The stored `is_draft` flag doesn't change.
  - **A visual art final report is an exam**, even though it's a slide deck and not a
    written paper. Today every exam already opens in CAM2 (`app.py:7701`, `7755`).

  ⋯ Manage already has this check mark for auto-sync rows (`app.py:7313`). Add assignment
  doesn't: it offers Draft as a third option beside Assignment and Exam (`app.py:7119`).
  Phase 3 changes that to Assignment or Exam, plus the check mark. Add assignment is a
  form, so the check mark can't appear only for Assignment. It stays visible and has no
  effect on an exam.
- **D17 · CAM2 learns slide-shaped pages first, and fetching from Drive waits.** CAM2
  doesn't read from Google Drive, and that's fine for now: school network restrictions
  block sharing to a personal account, so fetching directly isn't possible anyway. CAM2
  stays Google-free, as the slide-deck plan's D1 says. 16:9 and 4:3 pages go into the
  CAM2 version that CAM pins (Phase 1). The slide-deck plan's Drive work, its Phase 0 and
  Phase 2, is deferred. For now, decks reach CAM2 as PDFs through the teacher's Apps
  Script in the school account (Appendix A).
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
- **P8 · The draft label. Settled in v4:** it stays "Draft — comments only" (D16).
- **P9 · Getting decks into CAM2 as PDFs. Settled in v5:** the teacher's Apps Script
  (Appendix A) saves one PDF per student inside the school's Google account. Classroom
  downloads Google Slides as `.pptx`, which CAM2 can't read, so no converter is needed on
  the laptop, and the slide-deck plan's D2 stands. No CAM or CAM2 code depends on the
  script, and any PDF named with the student's name works the same way.

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

### Phase 1 — CAM2: safe hand-over and slide pages, tagged · M (CAM2 repo)

- Fix the first "next build" item in CAM2's `PLAN.md`: `running_instance()` compares
  versions through `/api/ping`, and a different running version is stopped and
  replaced after saving, or refuses the hand-over with a clear message.
- **Slide pages (D17, I14)**, from item 1 of the slide-deck plan's Phase 1:
  - add `Slide 16:9` and `Slide 4:3` to `PAPER_SIZES_MM` and `GRIDS`, at about 5 mm
    cells with the cells square (about 51 × 29 and 51 × 38);
  - detect slides by **aspect ratio**, because PowerPoint and Google decks differ in
    size but not shape, after checking the paper sizes so that A4 and the others are
    never mistaken for slides;
  - add them to the paper choices in `step1.js` and `boxes.js`, and to `i18n/en.json`
    and `ja.json`;
  - leave old sessions untouched.
- **Measure crop size** with a fictional photo-heavy deck. A whole slide is a 2667 × 1500
  PNG. If a class's folder is too big, bring in the slide-deck plan's JPEG crops
  (Phase 1, item 2) too. Its other Phase 1 items stay in that plan.
- Include the other fixes waiting at that point.
- Tests:
  - hand-over in both directions: older launcher with newer server, and newer with older;
  - detection of 13.333 × 7.5 in, 10 × 5.625 in and 10 × 7.5 in, with A4, B5 and A3
    unchanged;
  - grid and range round trips for both slide sizes;
  - an old session opening with its layout unchanged;
  - a browser check of a 12-screen fictional deck, from choosing the file to grading.
- **The teacher tries Appendix A on a small real assignment**, in the school account, and
  checks the PDFs' layout, the time a class takes and how large decks behave. Those PDFs
  stay in the teacher's data folder, never in this repository.
- Cut the new CAM2 tag (D14) and build its downloads: Mac here, **Windows on a Windows
  computer**. Share it with colleagues, since they're the ones exposed.

*Done when:* the I5 reproduction no longer upgrades or misroutes a session, and a 16:9
PDF is recognised and can be sliced into whole-slide questions and graded.

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
- **Add assignment** (D16). Type becomes Assignment or Exam, with a **Draft — comments
  only** check mark, replacing the third option at `app.py:7119`. ⋯ Manage keeps its
  check mark. Existing drafts are unaffected.
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
  questions; marks ticked on a criterion; a 16:9 slide deck; mixed from both starting
  choices; weighted;
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
  for D10 to D13 and D16, and for D17: slide sizes are done, its Drive phases are
  deferred, so its "Phase 0 comes first" no longer applies, and Appendix A stands in for
  its Fetch from Drive step.
- Add `CHANGELOG.md` and release notes that say plainly:
  - update **every computer before opening an exam**, because opened exams can't go
    back;
  - exams go through CAM2, and a draft is set up as an assignment with the **Draft —
    comments only** check mark;
  - slide decks can be graded in CAM2 as PDFs, and fetching from Drive isn't included;
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

I14 was tested with fictional PDFs against CAM2's slicer, not on its screens. Appendix
A's script was tested against fake Google services and CAM2's name matching with
fictional names, not on Google itself. I13 and
the other rows in the I12 table come from reading the code. Licence findings
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

---

## Appendix A. From Google Classroom to PDFs with Apps Script

The teacher's Google Apps Script runs inside the school's Google Workspace account. It
saves each student's submitted deck as a PDF, so nothing is shared to a personal account.
It isn't part of CAM or CAM2. Other teachers can copy it, and any PDF with the student's
name in its file name works the same way.

**This copy holds placeholders only.** Never commit a filled-in copy: real course and
assignment IDs belong in the script editor, and the PDFs belong in the teacher's data
folder, outside this repository.

### Setting it up

1. Create a project at script.google.com under the school account, and paste the script.
2. Under **Services**, add the Google Classroom API. Add the Drive API (v3) too if
   students may hand in PowerPoint files. Without it, those files show as failed and
   everything else still works.
3. On the first run, Google asks for permission to use Classroom, Drive and Slides, and
   to make external requests for the large-deck fallback. A school's settings could block
   this.

### The routine

1. Run `listMyCoursesAndAssignments`, and copy the IDs from the log into `BATCH_LIST` in
   `prepareSubmissionsForDownload`.
2. Run `prepareSubmissionsForDownload`. If the log says `NOT FINISHED`, run it again. It
   carries on in the same folder and skips finished files. If you abandon a batch, run
   `startFreshBatch`.
3. Read the end of the log for each class. It lists students with no file, failed decks,
   students with more than one PDF, and decks with an unusual number of slides.
4. Download the class folder from Drive and unzip it. PDFs stay PDFs in Drive's zip.
5. In CAM, set up an **Exam** and open it in CAM2. Choose the folder as one file per
   student. CAM2 matches each file to the class list by the name in it, for example
   `[Class A] Student Name - Final Report.pdf`, in either name order. CAM2 ignores
   `_report.txt` and the `Other files` subfolder.

For drafts, set `SAVE_AS_PDF` to `false` to get renamed copies of the original files.

### Limits

- **Added or deleted slides.** CAM2 finds each task by page number, so later slides won't
  line up with their boxes on that paper. The log flags these decks, and CAM2's page-check
  screen can fix them. Automatic correction was part of the deferred Drive work.
- **Files not turned in, on purpose.** The script copies whatever is attached, whether or
  not the student has turned it in. This shows what each student had done by the deadline.
- **A class that can't be read.** The log shows `[!] Error processing courseId` and ends
  with `NOT FINISHED`. Fix the problem and run it again: it carries on in the same folder.
- **Not yet confirmed on Google itself:** how large a deck converts, including whether the
  10 MB limit named in the script's comments applies to `getAs`, whether the export
  fallback keeps working, since it isn't an official API, how long a class takes, and how
  faithful Google's PDFs are.

### The script

```javascript
/**
 * STEP 1: Lists ALL of your active courses (and prints a summary list of all classes at the top).
 */
function listMyCoursesAndAssignments() {
  // === FILTER CONFIGURATION ===
  // Leave empty [] to show ALL your active courses!
  // If you want to hide specific courses (like 'Club'), add them to EXCLUDE_KEYWORDS: e.g. ['Club']
  const COURSE_NAME_FILTERS = [];
  const EXCLUDE_KEYWORDS = [];
  // ============================

  // Fetch all active courses (with pagination so none are ever missed)
  let courses = [];
  let pageToken = null;
  do {
    const response = Classroom.Courses.list({
      teacherId: 'me',
      courseStates: ['ACTIVE'],
      pageToken: pageToken,
    });
    if (response.courses) {
      courses = courses.concat(response.courses);
    }
    pageToken = response.nextPageToken;
  } while (pageToken);

  // Filter courses if any filters are configured
  const filteredCourses = courses.filter(course => {
    const fullTitle = `${course.name} ${course.section || ''}`.toLowerCase();
    const matchesInclude = COURSE_NAME_FILTERS.every(kw => fullTitle.includes(kw.toLowerCase()));
    const matchesExclude = EXCLUDE_KEYWORDS.some(kw => fullTitle.includes(kw.toLowerCase()));
    return matchesInclude && !matchesExclude;
  });

  // 1. Print a quick Master Summary of all courses first so nothing gets lost!
  let summary = `\n📋 FOUND ${filteredCourses.length} ACTIVE CLASSES:\n`;
  filteredCourses.forEach((c, idx) => {
    summary += `   ${idx + 1}. "${c.name}" (Section: ${c.section || 'N/A'})  -->  COURSE_ID: '${c.id}'\n`;
  });
  Logger.log(summary);

  // 2. Print each course's assignments in its own block (with pagination)
  for (const course of filteredCourses) {
    let report = `\n============================================================\n`;
    report += `🏫 CLASS: ${course.name} (Section: ${course.section || 'N/A'})\n`;
    report += `🔑 COURSE_ID: '${course.id}'\n`;
    report += `============================================================\n`;
    try {
      let courseWork = [];
      let cwPageToken = null;
      do {
        const cwResponse = Classroom.Courses.CourseWork.list(course.id, {
          pageToken: cwPageToken,
        });
        if (cwResponse.courseWork) {
          courseWork = courseWork.concat(cwResponse.courseWork);
        }
        cwPageToken = cwResponse.nextPageToken;
      } while (cwPageToken);

      if (courseWork.length === 0) {
        report += `   (No assignments found)\n`;
      } else {
        for (const work of courseWork) {
          report += `   • "${work.title}"\n     COURSEWORK_ID: '${work.id}'\n`;
        }
      }
    } catch (e) {
      report += `   [!] Could not list assignments: ${e.message}\n`;
    }
    Logger.log(report);
  }
}

/**
 * STEP 2: Batch-prepare multiple classes/assignments at once!
 * Creates ONE master folder in your "My Drive" with one PDF per submitted deck.
 * Students and co-teachers will NOT see any changes or receive any notifications.
 *
 * Google stops a script after about 6 minutes. If the log says "NOT FINISHED",
 * just press Run again: it carries on in the same folder and skips finished files.
 */
function prepareSubmissionsForDownload() {
  // === CONFIGURATION ===
  // 1. Name for the master folder that will be created in your "My Drive"
  const BATCH_FOLDER_NAME = 'Download Ready - CAM Grading Batch';

  // 2. true = put each class into its own subfolder inside the master folder
  //    false = put all files from all classes flat inside the master folder
  const CREATE_CLASS_SUBFOLDERS = true;

  // 3. true = save decks as PDFs, for grading in CAM2 (exams)
  //    false = make renamed copies of the original files, as before (drafts)
  const SAVE_AS_PDF = true;

  // 4. Stop starting new files after this long, so the run ends cleanly
  const MAX_RUN_MINUTES = 5;

  // 5. Add as many { courseId, courseworkId } pairs as you want to download together!
  //    (Optional: you can also add a custom 'label' if you want a shorter class prefix like 'Class A')
  const BATCH_LIST = [
    // Paste the IDs that Step 1 lists for the classes you want to download today. Rows left as PASTE_ or '' are skipped.
    { courseId: 'PASTE_COURSE_ID', courseworkId: 'PASTE_COURSEWORK_ID', label: 'Class A' },
    { courseId: 'PASTE_COURSE_ID', courseworkId: 'PASTE_COURSEWORK_ID', label: 'Class B' },
  ];
  // =====================

  const activeItems = BATCH_LIST.filter(item =>
    item.courseId &&
    item.courseworkId &&
    item.courseId.trim() !== '' &&
    item.courseworkId.trim() !== '' &&
    !item.courseId.startsWith('PASTE_') &&
    !item.courseworkId.startsWith('PASTE_')
  );

  if (activeItems.length === 0) {
    Logger.log('⚠️ No active { courseId, courseworkId } pairs configured in BATCH_LIST.');
    return;
  }

  const stopAt = Date.now() + MAX_RUN_MINUTES * 60 * 1000;
  const batchSig = activeItems
    .map(i => `${i.courseId.trim()}:${i.courseworkId.trim()}:${SAVE_AS_PDF}`)
    .join('|');
  const masterFolder = openBatchFolder_(BATCH_FOLDER_NAME, batchSig);

  let totalDoneCount = 0;
  let ranOutOfTime = false;
  let classErrorCount = 0;

  for (const item of activeItems) {
    if (ranOutOfTime) break;

    try {
      const course = Classroom.Courses.get(item.courseId);
      const work = Classroom.Courses.CourseWork.get(item.courseId, item.courseworkId);

      // Use custom short label if provided, otherwise Course Name
      const classLabel = item.label || course.name;

      Logger.log(`\n--- Processing: [${classLabel}] "${work.title}" ---`);

      // Decide target folder (either a class subfolder or the master folder)
      const targetFolder = CREATE_CLASS_SUBFOLDERS
        ? folderNamed_(masterFolder, safeFolderName_(`[${classLabel}] ${work.title}`))
        : masterFolder;

      // Clean up any leftover temp Google Slides file if a previous run was hard-killed by Google
      cleanTempFiles_(targetFolder);

      // Build map of Student User ID -> Official Classroom Full Name
      const studentMap = {};
      let pageToken = null;
      do {
        const roster = Classroom.Courses.Students.list(item.courseId, { pageToken: pageToken });
        if (roster.students) {
          for (const s of roster.students) {
            studentMap[s.userId] = s.profile.name.fullName;
          }
        }
        pageToken = roster.nextPageToken;
      } while (pageToken);

      // Fetch all student submissions for this assignment (with pagination)
      let submissions = [];
      let subPageToken = null;
      do {
        const subResponse = Classroom.Courses.CourseWork.StudentSubmissions.list(
          item.courseId,
          item.courseworkId,
          { pageToken: subPageToken }
        );
        if (subResponse.studentSubmissions) {
          submissions = submissions.concat(subResponse.studentSubmissions);
        }
        subPageToken = subResponse.nextPageToken;
      } while (subPageToken);

      const reportName = CREATE_CLASS_SUBFOLDERS
        ? REPORT_NAME_
        : `_report_${safeFolderName_(classLabel)}_${item.courseworkId}.txt`;
      const report = openReport_(targetFolder, reportName);
      const noFile = [];

      for (const sub of submissions) {
        const studentName = studentMap[sub.userId] || sub.userId;
        const attachments = (sub.assignmentSubmission && sub.assignmentSubmission.attachments) || [];
        const driveFiles = attachments.filter(att => att.driveFile && att.driveFile.id);

        if (driveFiles.length === 0) {
          noFile.push(studentName);
          continue;
        }

        for (const att of driveFiles) {
          const fileId = att.driveFile.id;
          if (report.isDone(fileId)) continue;

          if (Date.now() >= stopAt) {
            ranOutOfTime = true;
            break;
          }

          try {
            const originalFile = DriveApp.getFileById(fileId);
            const newName = `[${classLabel}] ${studentName} - ${originalFile.getName()}`;
            const result = SAVE_AS_PDF
              ? savePdf_(originalFile, newName, targetFolder)
              : copyOriginal_(originalFile, newName, targetFolder);

            report.add(fileId, result.status, result.slides, studentName, result.savedName);
            Logger.log(`   ${result.status}: "${result.savedName}"`);
            totalDoneCount++;
          } catch (err) {
            report.add(fileId, 'FAILED', '', studentName, err.message);
            Logger.log(`   [!] Could not prepare file for ${studentName}: ${err.message}`);
          }
        }
        if (ranOutOfTime) break;
      }

      if (!ranOutOfTime) logClassSummary_(classLabel, report, noFile);
    } catch (courseErr) {
      classErrorCount++;
      Logger.log(`[!] Error processing courseId ${item.courseId}: ${courseErr.message}`);
    }
  }

  Logger.log(`\n============================================================`);
  if (ranOutOfTime) {
    Logger.log(`⏳ NOT FINISHED: ${totalDoneCount} files done in this run. Press Run again to carry on.`);
  } else if (classErrorCount > 0) {
    Logger.log(`⚠️ NOT FINISHED: ${classErrorCount} class(es) could not be read. See the [!] lines above, fix the problem and press Run again.`);
  } else {
    const props = PropertiesService.getUserProperties();
    props.deleteProperty(BATCH_FOLDER_KEY_);
    props.deleteProperty(BATCH_SIG_KEY_);
    Logger.log(`✅ ALL DONE! Files prepared in this run: ${totalDoneCount}`);
  }
  Logger.log(`📁 Master Folder Name: "${masterFolder.getName()}"`);
  Logger.log(`🔗 Click to open & download: ${masterFolder.getUrl()}`);
  Logger.log(`============================================================`);
}

/**
 * Run this only if you abandon an unfinished batch, so the next run starts a new folder.
 */
function startFreshBatch() {
  const props = PropertiesService.getUserProperties();
  props.deleteProperty(BATCH_FOLDER_KEY_);
  props.deleteProperty(BATCH_SIG_KEY_);
  Logger.log('The next run will start a new master folder.');
}

const BATCH_FOLDER_KEY_ = 'CAM_BATCH_FOLDER_ID';
const BATCH_SIG_KEY_ = 'CAM_BATCH_SIGNATURE';
const REPORT_NAME_ = '_report.txt';
const OTHER_FILES_FOLDER_ = 'Other files';
const TEMP_PREFIX_ = '__cam_temp__ ';
const POWERPOINT_TYPES_ = [
  'application/vnd.openxmlformats-officedocument.presentationml.presentation',
  'application/vnd.ms-powerpoint',
];

// Carry on in an unfinished batch's folder (if BATCH_LIST hasn't changed), or start a new dated one.
function openBatchFolder_(batchName, batchSig) {
  const props = PropertiesService.getUserProperties();
  const savedId = props.getProperty(BATCH_FOLDER_KEY_);
  const savedSig = props.getProperty(BATCH_SIG_KEY_);
  if (savedId && savedSig === batchSig) {
    try {
      const saved = DriveApp.getFolderById(savedId);
      if (!saved.isTrashed()) {
        Logger.log(`Carrying on in "${saved.getName()}"`);
        return saved;
      }
    } catch (err) {
      // The saved folder is gone, so start a new one below.
    }
  }
  const dateStr = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm');
  const folder = DriveApp.getRootFolder().createFolder(`${batchName} (${dateStr})`);
  props.setProperty(BATCH_FOLDER_KEY_, folder.getId());
  props.setProperty(BATCH_SIG_KEY_, batchSig);
  return folder;
}

function safeFolderName_(name) {
  return String(name || '').replace(/[\\/]+/g, '-').trim();
}

function folderNamed_(parent, name) {
  const found = parent.getFoldersByName(name);
  return found.hasNext() ? found.next() : parent.createFolder(name);
}

// Avoid duplicate filenames in the same folder when a student submits multiple files with the same base name.
function uniqueName_(folder, desiredName) {
  if (!folder.getFilesByName(desiredName).hasNext()) return desiredName;
  const dot = desiredName.lastIndexOf('.');
  const stem = dot !== -1 ? desiredName.slice(0, dot) : desiredName;
  const ext = dot !== -1 ? desiredName.slice(dot) : '';
  let n = 2;
  while (folder.getFilesByName(`${stem} (${n})${ext}`).hasNext()) {
    n++;
  }
  return `${stem} (${n})${ext}`;
}

// Trash any leftover temporary Google Slides decks if a previous run was hard-stopped by Google.
function cleanTempFiles_(folder) {
  const files = folder.getFiles();
  while (files.hasNext()) {
    const f = files.next();
    if (f.getName().indexOf(TEMP_PREFIX_) === 0) {
      try {
        f.setTrashed(true);
      } catch (err) {
        // Ignore cleanup errors
      }
    }
  }
}

// Google Slides and PowerPoint become PDFs, and PDFs are copied. Anything else goes in
// "Other files", because CAM2 would treat a photo beside the PDFs as a student's paper.
function savePdf_(file, name, folder) {
  const type = file.getMimeType();
  const basePdfName = name.replace(/\.(pptx?|pdf)$/i, '') + '.pdf';

  if (type === MimeType.PDF) {
    const pdfName = uniqueName_(folder, basePdfName);
    file.makeCopy(pdfName, folder);
    return { status: 'PDF copied', slides: '', savedName: pdfName };
  }
  if (type === MimeType.GOOGLE_SLIDES) {
    const pdfName = uniqueName_(folder, basePdfName);
    return slidesToPdf_(file, pdfName, folder);
  }
  if (POWERPOINT_TYPES_.indexOf(type) !== -1) {
    if (typeof Drive === 'undefined' || !Drive.Files) {
      throw new Error('Enable "Drive API" (v3) under Services (+) in the Apps Script sidebar to convert PowerPoint files.');
    }
    const pdfName = uniqueName_(folder, basePdfName);
    // PowerPoint has to become Google Slides first. Needs the Drive API service (v3).
    const temp = Drive.Files.copy(
      { name: `${TEMP_PREFIX_}${pdfName}`, mimeType: MimeType.GOOGLE_SLIDES, parents: [folder.getId()] },
      file.getId(),
      { supportsAllDrives: true }
    );
    const tempFile = DriveApp.getFileById(temp.id);
    try {
      return slidesToPdf_(tempFile, pdfName, folder);
    } finally {
      tempFile.setTrashed(true);
    }
  }
  const otherFolder = folderNamed_(folder, OTHER_FILES_FOLDER_);
  const otherName = uniqueName_(otherFolder, name);
  file.makeCopy(otherName, otherFolder);
  return { status: 'Other file', slides: '', savedName: otherName };
}

function slidesToPdf_(file, pdfName, folder) {
  let slides = '';
  try {
    slides = SlidesApp.openById(file.getId()).getSlides().length;
  } catch (err) {
    // The count is only a check, so a failure here mustn't stop the PDF.
  }

  let pdfBlob;
  try {
    pdfBlob = file.getAs(MimeType.PDF).setName(pdfName);
  } catch (exportErr) {
    // Fallback for photo-heavy decks that exceed Drive's 10 MB getAs() export cap
    const url = `https://docs.google.com/presentation/d/${file.getId()}/export/pdf`;
    const res = UrlFetchApp.fetch(url, {
      headers: { Authorization: `Bearer ${ScriptApp.getOAuthToken()}` },
      muteHttpExceptions: true,
    });
    if (res.getResponseCode() !== 200) {
      throw exportErr;
    }
    pdfBlob = res.getBlob().setName(pdfName);
  }

  folder.createFile(pdfBlob);
  return { status: 'PDF saved', slides: slides, savedName: pdfName };
}

function copyOriginal_(file, name, folder) {
  const savedName = uniqueName_(folder, name);
  file.makeCopy(savedName, folder);
  return { status: 'Copied', slides: '', savedName: savedName };
}

// A small text file in the class folder records what's done, across runs.
function openReport_(folder, reportFileName) {
  const targetReportName = reportFileName || REPORT_NAME_;
  const found = folder.getFilesByName(targetReportName);
  const file = found.hasNext() ? found.next() : folder.createFile(targetReportName, '\n');
  const lines = file.getBlob().getDataAsString().split('\n').filter(line => line.trim());
  const latest = {};
  const clean = v => String(v ?? '').replace(/[\r\n\t]+/g, ' ').trim();
  const read = line => {
    const [fileId, status, slides, student, name] = line.split('\t');
    if (!fileId || !status) return;
    latest[fileId] = { status, slides: slides || '', student: student || '', name: name || '' };
  };
  lines.forEach(read);

  return {
    latest,
    isDone: fileId => !!latest[fileId] && latest[fileId].status !== 'FAILED',
    add: (fileId, status, slides, student, name) => {
      const line = [fileId, status, slides, student, name].map(clean).join('\t');
      lines.push(line);
      read(line);
      file.setContent(lines.join('\n') + '\n');
    },
  };
}

// Point out anything the teacher should look at before grading.
function logClassSummary_(classLabel, report, noFile) {
  const rows = Object.keys(report.latest).map(id => report.latest[id]);
  const papers = rows.filter(r => r.status && r.status.indexOf('PDF') === 0);
  Logger.log(`   -> [${classLabel}]: ${rows.filter(r => r.status !== 'FAILED').length} files prepared.`);

  if (noFile.length) Logger.log(`   No file from: ${noFile.join(', ')}`);

  rows.filter(r => r.status === 'FAILED').forEach(r =>
    Logger.log(`   [!] FAILED, save this one by hand: ${r.student} (${r.name})`));
  rows.filter(r => r.status === 'Other file').forEach(r =>
    Logger.log(`   Not a deck, in "${OTHER_FILES_FOLDER_}": ${r.name}`));

  // More than one PDF for a student: CAM2 leaves these for you to match.
  const perStudent = {};
  papers.forEach(r => { perStudent[r.student] = (perStudent[r.student] || 0) + 1; });
  Object.keys(perStudent).filter(s => perStudent[s] > 1).forEach(s =>
    Logger.log(`   ${s} has ${perStudent[s]} PDFs. Keep the right one before adding them to CAM2.`));

  // A different slide count moves later slides off their boxes in CAM2.
  const counts = {};
  papers.filter(r => r.slides).forEach(r => { counts[r.slides] = (counts[r.slides] || 0) + 1; });
  const usual = Object.keys(counts).sort((a, b) => counts[b] - counts[a])[0];
  if (usual) {
    Logger.log(`   Usual deck length: ${usual} slides.`);
    papers.filter(r => r.slides && r.slides !== usual).forEach(r =>
      Logger.log(`   ${r.student} has ${r.slides} slides. Check this paper's pages in CAM2.`));
  }
  papers.filter(r => !r.slides).forEach(r =>
    Logger.log(`   Slide count unknown, check this paper's pages in CAM2: ${r.student}`));
}
```
