# Upgrading CAM's vendored CAM2 to the latest dev version: assessment and plan

**Status:** v6, 2026-11-05. **Fixed:** the teacher accepted every answer in §5.2 that day.
v6 merges [CAM2_FEEDBACK_FOR_CAM.md](CAM2_FEEDBACK_FOR_CAM.md) into Phases 1 to 6 and
brings the plan up to CAM2 `5931f22`. Decisions D10–D18 (§5) are locked by the teacher.
Q4's trial set the F6 wording in Phase 3. The smaller points
(§5.1) go ahead on the stated default unless the teacher changes them. Phase 0 is done.
Phase 1 is on CAM2's `main`, tagged `v0.3.2-dev` (`4423090`) and published as a pre-release
with both downloads on 2026-11-06, and nothing in it is open: the teacher's Appendix A
trial moved to after the whole upgrade (§6.1). Phases 2, 2W and 3 are on CAM's `main` (see their progress
notes). Phase 4's code is on the `cam2-upgrade-phase4` branch, pinning the Phase 1 tag;
its browser matrix passed on the Mac; the same run on Windows and the Windows build are still
to do (see its progress note). Phases 5
and 6 aren't built yet.

Earlier versions: v3 changed D10, D11 and D13, so a paper's repeated levels stay on the
exam and the teacher decides one grade per criterion in Window 3. v4 corrected D16 and
added D17. v5 added the Apps Script route (Appendix A).

## Picking up on another computer

Written 2026-11-06, for the next session on the Mac. A session's chat and memory stay on the
computer they ran on, so this is what the next session needs. Trust this plan and the repos
over any older memory there.

**Do these first:**

1. **Update both repos.** Run `git status` first, and don't overwrite local changes. Then
   `git switch main` and `git pull --ff-only` in the CAM and CAM2 checkouts. This only updates
   code. Don't launch anything yet.
2. **Add the phase check to the user-level `~/.claude/CLAUDE.md`,** if it isn't there, creating
   the file if needed and keeping what's already in it. Use the text below.
3. **Then run that check on Phase 1,** and report back before building anything.
4. **For Phase 4's browser checks on the Windows Surface** (2026-11-06), follow
   [tools/browser_check/README.md](../tools/browser_check/README.md): it has the sandbox
   start script, the fixtures, each check and the results the Mac run got.

```markdown
## Before starting a new phase, check the earlier phases are finished

Applies to every repository and any work planned in phases, stages or steps.

When I ask to start, plan or build a new phase, or when you are about to move on to the next one yourself, stop before writing any code and do this first:

1. Check every earlier phase for anything still open: unfixed bugs or review findings, open or unmerged pull requests, failing or skipped tests, checks marked "not run" or "still to do", and left-over steps in the plan. Check the code, git and the pull requests as well as the plan, because documents can be out of date.
2. Remind me, even if everything is clear. List what's still open, phase by phase, or say that you found nothing open.
3. If anything is open, recommend finishing it first, and wait for my answer before starting the new phase. If I choose to go ahead anyway, record what's being left open.

**Why:** when I moved on to later phases with issues still open in earlier ones, the problems piled up and took a long review to untangle.
```

**Phase 4 (2026-11-06):** its code is on the `cam2-upgrade-phase4` branch (PR #8). The browser
matrix passed on the Mac. Still to do: the same browser run on the Windows Surface
(`tools/browser_check/README.md`) and the Windows build.

**Where things stand:** Phases 0, 2, 2W and 3 are on CAM's `main`, after a review of each, and
all tests pass on Windows (CAM 473 with 8 skipped until Phase 4, CAM2 216). No new CAM release
(D18). Phase 1 is tagged and out as CAM2's `v0.3.2-dev` pre-release (updated 2026-11-06),
so Phase 4 can start once the rest of Phase 1 is finished or knowingly left open. CAM's tests
also pass on the Mac (473 with 13 skipped: the 8 waiting for Phase 4, and 5 that need Node).

**Still open in Phase 1:**

| Step | Where it can happen |
|---|---|
| ~~Review CAM2 PR #1~~ Done 2026-11-06: two small fixes, then merged | The Mac |
| ~~The teacher tries Appendix A~~ Moved on 2026-11-06, by the teacher's choice, to after the whole upgrade (§6.1) | |
| ~~Retry the level click~~ Done 2026-11-06: explained, not a lost request (Phase 1's progress note) | The Mac |
| ~~Merge the PR, set CAM2's version, cut the tag, build the Mac download~~ Done 2026-11-06: `v0.3.2-dev` at `4423090` | The Mac |
| ~~Build the Windows download~~ Done 2026-11-06 | A Windows computer |
| ~~Check the Windows unblock advice~~ Accepted as done 2026-11-06, on colleagues' use of the test builds. Not tried separately | |
| ~~Make the `v0.3.2-dev` pre-release~~ Done 2026-11-06: both zips, the sample exams and the two source archives | |
| ~~Share the build with colleagues~~ Done: colleagues are using the test builds, largely without problems | |

**Also worth doing on the Mac:** Phase 4M's Gatekeeper check needs a download on a Mac that
didn't build it, and it decides whether the free Mac route works at all.

**The teacher's decisions on what was still open (2026-11-06):**

- **The teacher won't run CAM until this upgrade is released,** and will update every
  computer first. So the interim advice (I5) is no longer needed, and an older CAM or
  workspace on another computer is out of scope.
- **After the release, the teacher tries** the Appendix A route and AI term comments
  (Phase 6, step 7, and §6.1).
- **CAM2's Japanese wording** gets feedback after the public release. No colleague can
  check it before, as none has used a digital grading system in Japanese.
- **The level buttons that move after a grade** are fixed in the next CAM2 update, so
  they reach CAM with the second pull.
- **Browser checks wait until Phase 4's code is in (decided 2026-11-06).** The teacher
  won't run CAM2 again until this upgrade is done, so the checks not yet run, a CAM2 exam's
  row in a downloaded report (Phases 2 and 3) and restoring and linking drafts in the
  browser, with the mouse (Phase 2W), join Phase 4's sandbox browser run, after its code.
- **Older CAM2 comments over the new limits stay as they are (decided 2026-11-06).** Only
  colleagues testing CAM2 have any, and they can shorten them. Nothing in CAM changes:
  the workspace's comments have no limit, and the term comment takes drafts and
  assignments whole (`engine/exam_feedback.py`).
- **Google's 16:10 slide size goes in the next CAM2 update (decided 2026-11-06),** with
  the level buttons (§6.1).

**Decisions made since v6 that later phases rely on:**

- Linked partners share the first graded member's grade, and their comments and ticks combine.
- A keyword list must never shrink on reload.
- Phase 4 has to read CAM2's adjusted report figures (see Phase 3's progress note), and its test
  matrix needs its own sessions, because `make_sample_exam.py` takes only an output folder.

**Testing safely on the Mac:**

- **Its prefs may point at real data,** so never launch the app or run its tests directly in the
  checkout. Copy only `git ls-files -co --exclude-standard` to a temp folder, so no prefs or
  settings come along. Point `CAM_DB_PATH`, `CAM2_APP_DATA`, `CAM2_DOCUMENTS_OVERRIDE`,
  `CAM_DOCUMENTS_OVERRIDE` and `HOME` into temp, unset any `ONEDRIVE*` variables, then run
  `tools/run_all_tests.py` there.
- **Without Node, tests skip that ran on Windows,** including the ones that run the workspace's
  page code, and the skip count will be higher. Those were checked on Windows. Say so when
  reporting a result, and don't count it as a failure.
- **The real database isn't to be touched** without explicit permission (`CLAUDE.md`).

---

**Repos:** CAM = `criterion-assessment-metrics`; CAM2 = `cam2-exam-grading`,
vendored in CAM at `exam_grading/`.
**Depends on:** [CAM2_EXAM_CONVERGENCE_PLAN.md](CAM2_EXAM_CONVERGENCE_PLAN.md). This
plan keeps its numbering and amends its D3 and D4. It also feeds
[SLIDE_DECK_EXAM_PLAN.md](SLIDE_DECK_EXAM_PLAN.md), which is not built yet.
**Colleagues' feedback:** in this upgrade are F2's limits on comment length (Phase 1), F4,
the workspace's comment bug (Phase 2W), F6, exam comments in term comments (Phase 3), and
keeping development documents out of the bundle (Phase 4). The others wait for a later CAM2 update (§6.1). The details stay in
CAM2's `Feedback-and-Upgrades.md`.

Read `CLAUDE.md` first. Phases 0 and 6 touch real data, and the sandbox, backup and
permission rules there apply. Never edit `exam_grading/` in place: change CAM2,
then `git subtree pull`.

Line numbers below refer to CAM `origin/main` at `2554d46`. They still hold at `c40fd93`,
which adds only Phase 0's report and its test.

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
| CAM `origin/main` | `c40fd93` | 2026-11-05 | App code as at `2554d46`; adds Phase 0's report and docs |
| CAM2 pinned in CAM | `1a40845` | 2026-11-01 | Vendored tree is byte-identical to this commit (`f513ea4`) |
| CAM2 `v0.3.1-dev` | `c1a0594` | 2026-11-05 | Latest tag. Has the hand-over fix (I5) and no slide pages (I14) |
| CAM2 `main` | `5931f22` | 2026-11-05 | 29 commits past the pin; only documents differ from the tag |

What the 29 commits add: exam sections, weighting, mixed papers (each question
graded with marks or a rubric), a new student report and gradebook, report options,
packaging, licence notices, sample exams, the hand-over fix and the feedback document.
Session files go to **version 2**.

### What stays compatible

Checked in a sandbox (§7), and the pull and both test suites again at `5931f22`:

- `git subtree pull` onto `origin/main` merges with no conflicts, and the result
  matches CAM2's tree exactly.
- `exam_grading/requirements.txt` is unchanged.
- Every CAM2 function the bridge calls still exists. `engine/host.py` is unchanged,
  and `launcher.py --host` and "Send to CAM" still work.
- Marks-only exams read identically on both engines (15/20 on each).
- Reading is still read-only: a session folder is byte-identical after CAM reads it.
- CAM2's own suite passes in its vendored location (331 tests, 1 skipped).

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
| I5 | Launcher hands exams to whichever version is running | High. Fixed in CAM2 `v0.3.1-dev`, **still live in CAM until the pull** |
| I6 | Weighted exams: CAM and CAM2 disagree | High |
| I7 | Tests don't guard any of this | Medium |
| I8 | Criterion marks are ignored | High (was Medium; D13 needs them) |
| I9 | Licence notices missing from CAM's bundle | High, **live today** (was Medium) |
| I10 | Documents describe the old behaviour | Low |
| I11 | This Mac's `main` is 24 commits behind | Resolved by 2026-11-05 |
| I12 | Several grades on one criterion would break the screens | Avoided by D10 (new) |
| I13 | A student waiting for a grade can count as Missing = 0 | High (new) |
| I14 | CAM2 doesn't recognise slide-shaped pages | Precondition for slide decks; fixed in Phase 1 |
| I15 | The grading workspace overwrites typed comments (CAM2 F4) | High (data loss), **live today** (new in v6) |
| I16 | Exam comments often miss the term comment (CAM2 F6) | High (new in v6) |

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

**Fixed in CAM2 `v0.3.1-dev`, which doesn't reach CAM until the pull.** `running_instance()`
now compares versions and stops any other running version, older or newer
(`launcher.py`). So:

- The launcher inside `v2026.11.01` still has the old behaviour, and the interim advice
  stands until the upgrade is on all three computers.
- After the upgrade, CAM's CAM2 and a standalone CAM2 of another version stop each other
  whenever one is started. Grades are already saved, but a comment still being typed in
  the stopped one's tab could be lost. Building both from one tag (D14, D18) makes this
  rare.

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
  `Exam-Section-Plan.md`, `Feedback-and-Upgrades.md`, `requirements-build.txt` or
  `licences/`, so all four would ship, including that CAM2-only notice. CAM2's code
  doesn't read `licences/` when it runs.
- The same tool removes only `docs/*_PLAN.md` (`build_windows_bundle.py:100`), so CAM's
  own `docs/CAM2_FEEDBACK_FOR_CAM.md` would ship too.
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

Resolved: on 2026-11-05 this checkout was level with `origin/main`. The original finding:

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

### I15. The grading workspace overwrites typed comments (CAM2 F4)

`autoComment` (`cam_grading_workspace/app.py:4453`) rebuilds a comment from its ticks
alone, and three places assign the result over whatever is there:

| Line | What sets it off | Who loses text |
|---|---|---|
| `4430` | Changing a tick | That student |
| `4412` | Changing the Late tick | That student |
| `4711` | Changing the deadline | **Every student in the task**, saved at once by line `4715` |

This comes from reading the code, which has no branch that keeps the text, and hasn't
been run. A draft has no grades, so a deadline change can empty everything a teacher
wrote on it. This is CAM's own code, so the CAM2 pull doesn't fix it.

**It's more than a browser change.** `/api/save` copies only the fields it knows
(`app.py:2445-2465` in the workspace), so a new remembered line is dropped unless the
server carries it. So do linked partners (`1572`), the rebuilt student list (`1401`) and
the student data sent to the page (`757`, `1016`, `1098`). The comment can also change in
two other ways: a comment edited in CAM (`2263`) and a renamed tick (`4597`).

**Workaround until the release:** tick first, then type, and set the deadline before
writing any comments.

### I16. Exam comments often miss the term comment (CAM2 F6)

`compile_prompt` (`app.py:6218`) takes evidence only from `student.scores`
(`_current_term_evidence`, `app.py:6117`), and then only the highest and lowest pieces
(`select_evidence`, `app.py:6342`). The defaults are one of each (`app.py:847-848`). So:

- A question's comment never reaches the prompt. It stays in
  `ExamResult.question_comments`.
- An overall comment reaches it only if a grade was applied and the exam ranks at the
  top or bottom. Draft comments are always included (`app.py:6354`), so exams get less
  than drafts do.

**Applying grades creates a second problem.** Apply copies one overall comment onto
every criterion (`app.py:7671`), and each copy competes in the ranking on its own. Run
against `select_evidence` with fictional data, an exam at A 7, B 7, C 6, D 6 and four
assignments at 4 or 5, with two strengths allowed, gives two strengths that are the same
exam comment. A middling exam still drops out completely.

**Two details the first draft of this plan missed:**

- **A teacher can edit the copy.** Window 3's edit dialog tells the teacher to "Edit or
  clear this to change what feeds the comments log and the generated overall comment"
  (`app.py:8635`). A block that reads only `ExamResult.comment` would break that promise.
- **A re-sent comment can go stale.** Sync replaces the exam result
  (`_ingest_cam2_session`, `app.py:4179`) and leaves the grades alone. Under P6 no Apply
  follows, so a comment corrected in CAM2 would never reach the grade.

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

  F5's direction is agreed (Q6), and D16 stands until F5's last stage.
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
- **D18 · No new release until the upgrade is finished.** Decided by the teacher on
  2026-11-05. There is no separate licence-only release, so the Licences folder promised
  on the `v2026.11.01` release page arrives with the upgrade. That release is then
  published with Mac and Windows binaries of **both CAM and CAM2**.
  - CAM2 already builds both. CAM's bundle is Windows only today
    (`tools/build_windows_bundle.py`), so the teacher's choice of a Mac CAM adds Phase 4M.
  - The July releases were deleted on 2026-11-05 and their tags kept, so `v2026.11.01` is
    the only CAM release until then.

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
  finished and sent again, as today. Sync replaces the exam result, so the old levels
  aren't there to compare with. The flag needs a small record taken at the decision
  (Phase 2).
- **P7 · No average beside the dropdown.** *Default: Window 3 shows the levels and no
  calculated figure*, which keeps D10's "never averages or suggests". An average could
  be added later as a read-only aid if the teacher wants it.
- **P8 · The draft label. Settled in v4:** it stays "Draft — comments only" (D16).
- **P9 · Getting decks into CAM2 as PDFs. Settled in v5:** the teacher's Apps Script
  (Appendix A) saves one PDF per student inside the school's Google account. Classroom
  downloads Google Slides as `.pptx`, which CAM2 can't read, so no converter is needed on
  the laptop, and the slide-deck plan's D2 stands. No CAM or CAM2 code depends on the
  script, and any PDF named with the student's name works the same way.
- **P10 · Saving the workspace's generated line (F4).** *Default: the comment is the
  generated line, then the teacher's text, as in CAM2.* Each student saves the line last
  generated. **Text is never lost, even if that means repeating some.** If the comment
  doesn't start with the remembered line, for example after an edit in CAM, the text
  stays and the new line goes in front. A saved comment with no remembered line is
  compared with the line its ticks would have given before this change.
- **P11 · A deadline change.** *Default: it rewrites and saves only students whose Late
  flag changed.* Everyone else is left alone.
- **P12 · What the exam block holds (F6).** *Default: comments only, with no levels or
  grades,* so it respects **No numbers** and D10, and those already appear in the
  criterion results. It covers every exam on this term, whether or not a grade has been
  decided, and an unfinished paper's comments too, because the teacher sent them. A
  comment on a question not counted because of a choice group stays out.
- **P13 · How the source material is shared out (F6, Q4).** *Default: about 6,000
  characters in all, with up to 4,000 for exams and 2,000 for drafts and assignments.*
  Either side can use what the other leaves. Exams' overall comments always go in whole.
  If it's over, whole question comments are left out, taken evenly across exams and never
  cut mid-sentence, and the teacher is told how many.

### 5.2 Questions settled for v6

The teacher accepted each answer below on 2026-11-05, and Phases 1 to 6 are written on
them. The last column names the phases each answer affects.

| # | Question | Answer | Affects |
|---|---|---|---|
| Q1 | **One CAM2 pull or two?** F1 and F2 raise the session version again, so I4 happens again. More feedback is still to come | **Two.** The Phase 1 tag holds slide pages and comment limits (Q8), and leaves the session at version 2. Waiting has no end date, and it would also hold back the Licences folder and the I5 and F4 fixes (D18). Phase 0 found no real sessions, so a second version costs one more "update every computer first" notice. D18's single release then covers this upgrade only | Phases 1, 2, 4, 5 |
| Q2 | **Should exams still compete for the strength and growth places in the term comment?** | **No.** Since they're always included, exam scores leave the ranking, and the places go to assignments. Otherwise one exam can take every place (I16). The cost: "highest-scoring pieces" no longer includes an exam, so the block's instruction has to cover strengths and growth | Phase 3 |
| Q3 | **Which overall comment does the block use if the teacher edits it in Window 3?** | **The edited one.** If grades exist for the exam, use their comments, each different text once, and otherwise `ExamResult.comment`. Clearing them removes it. A re-send updates only copies the teacher hasn't edited | Phase 3 |
| Q4 | **How large is a "large place"?** One instruction may not do it in a default 100-word comment, and one exam can bring about 5,000 characters of comments | **The teacher's sizes:** a term comment of about 100 words, up to about 150 at the end of the year, from at most 500 to 1,000 words of exams, drafts and assignments together. Below that, the AI tends to copy word for word. **So a limit is needed** (P13): even at CAM2's new limits (Q8), one 15-question exam comes to about 850 words, and drafts and assignments have no limit. A trial on fictional students still sets the wording | Phase 3 |
| Q5 | **Does D18 still hold for F4?** A deadline change can wipe a whole task's comments, and the fix can't reach the teacher's computers before the release | **Yes,** with the workaround, since the teacher has already chosen one release. Do Phase 2W early, so an exception is quick if comments are lost | Phases 2W, 5 |
| Q6 | **Is F5 agreed?** CAM2's table says "Direction agreed", and CAM's note says amend D16 "when F5 is agreed" | **Record it as direction agreed, with D16 standing until F5's last stage.** Nothing in Phases 1 to 6 changes. Build nothing else in the workspace, and Phase 4M only checks that it runs on a Mac from a local folder | Phases 3, 4M |
| Q7 | **Does a student's school email stay the same from year to year?** CAM's student ID comes from it (`student_id_from_email`, `engine/ingestion.py:319`), and exam sessions store that ID. F7 asks for one ID across years before a year's data builds up | **Yes.** The teacher confirms that an address and its number stay the same for a student's whole time at the school, as at most schools. So F7 needs no new ID, and this upgrade builds nothing for it. With letters then a number (`reg1001`), CAM keeps only the number, so that number must be unique across the school | §6.1 only |
| Q8 | **How much can a teacher write on a paper?** | **300 characters on a question (about 50 words) and 600 for the overall comment (about 100 words).** The teacher's point: nobody writes more than that for each of 20 students. These come ahead of the rest of F2, in the Phase 1 tag, so this release has them | Phases 1, 3, 5 |

---

## 6. Phases

Order: 0 → 1, 2 and 2W (independent of each other) → 3 → 4 → 4M → 5 → 6, with 4M's first
step (the Gatekeeper check) worth doing early because it can be done at any time. One
commit per phase,
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

**Result, 2026-11-05:**

- **Exposure: none.** `tools/exam_exposure_report.py` found 0 sessions in the real data
  folder, so 0 are exposed to I1, I2 or I4. A separate search agrees: no
  `cam2_session.json` anywhere under the folder, no exam assignments, exam results or
  exam-sourced grades in the database, and the files read were unchanged afterwards.
- **What that covers.** It's one point in time, and assumes the teacher's other two
  computers use the same synced folder. A real exam opened in CAM before the upgrade
  ships would need the count run again before Phase 6.
- **Computers.** The teacher runs CAM on three computers, all on the current version,
  and each also has CAM2. Colleagues run CAM2 only, so I5 reaches only those three.
- **This checkout (I11).** Already level with `origin/main`, so no update was needed.
- **Release page (P5).** Done for `v2026.11.01`, with the teacher's go-ahead: a Licences
  section, and the zip unchanged. The two July releases have no notice. The teacher is
  considering deleting them while keeping their tags, so I9 still applies to those.
- **Interim advice (I5): no longer needed** (2026-11-06). The teacher won't run CAM until
  this upgrade is released and on every computer, so CAM's old launcher never runs.
- **What the published `v2026.11.01` zip holds.** PyMuPDF 2.0 with MuPDF 1.28.5, Pillow
  12.3.0 and anthropic 2.3.0, 98 packages in all. So real users already run PyMuPDF 2.0,
  while §7's tests ran on 1.28.2. Phase 4's check on 2.0 matters for that reason. Its
  `pymupdf4llm` and `pymupdf_layout` packages are empty placeholders with no licence
  field; that code now sits inside PyMuPDF, under its licence. Phase 4's third-party list
  needs to cover them, and PyMuPDF's bundled `onnxruntime`.

### Phase 1 — CAM2: safe hand-over and slide pages, tagged · M (CAM2 repo)

- **Hand-over: done in `v0.3.1-dev`.** `running_instance()` compares versions and stops
  any other version. What remains is the two-direction test below.
- **What the tag holds (Q1).** Slide pages, comment limits (Q8) and the fixes below. **F1,
  the rest of F2 and F8 to F15 stay out,** so the session stays at version 2. No work on
  them starts in this tag's branch.
- **Slide pages (D17, I14)**, from item 1 of the slide-deck plan's Phase 1:
  - add `Slide 16:9` and `Slide 4:3` to `PAPER_SIZES_MM` and `GRIDS`, at about 5 mm
    cells with the cells square (about 51 × 29 and 51 × 38);
  - detect slides by **aspect ratio**, because PowerPoint and Google decks differ in
    size but not shape, after checking the paper sizes so that A4 and the others are
    never mistaken for slides;
  - add them to the paper choices in `step1.js` and `boxes.js`, and to `i18n/en.json`
    and `ja.json`;
  - leave old sessions untouched.
- **Comment limits (Q8)**, from CAM2's F2, on Step 4's question comment and Step 5's
  overall comment:
  - count characters, because Japanese has no spaces, and show a counter near the limit;
  - refuse a longer comment with a short message, in `i18n/en.json` and `ja.json`, rather
    than using a browser length limit, which silently trims pasted text. Check it when
    saving too, in `set_grade` and `set_overall_comment`;
  - never cut a saved comment. A longer one can be kept or shortened, but can't grow;
  - the line generated from ticks doesn't count, and never stops a tick;
  - change nothing in the session's format;
  - move the agreed design to CAM2's `PLAN.md`.
- **Measure crop size** with a fictional photo-heavy deck. A whole slide is a 2667 × 1500
  PNG. If a class's folder is too big, bring in the slide-deck plan's JPEG crops
  (Phase 1, item 2) too. Its other Phase 1 items stay in that plan.
- Include the other fixes waiting at that point, and check the Windows unblock advice on
  a real computer, as CAM2's `PLAN.md` asks.
- Tests:
  - hand-over in both directions: older launcher with newer server, and newer with older.
    Today's test (`test_another_version_is_stopped_before_the_new_one_starts`) covers one
    case of "different";
  - detection of 13.333 × 7.5 in, 10 × 5.625 in and 10 × 7.5 in, with A4, B5 and A3
    unchanged;
  - grid and range round trips for both slide sizes;
  - an old session opening with its layout unchanged;
  - a browser check of a 12-screen fictional deck, from choosing the file to grading;
  - comment limits: at and over each limit, pasted text, Japanese text, a tick on a comment
    at its limit, and an older session with a longer comment, which opens and saves with
    that comment unchanged.
- **The teacher tries Appendix A on a small real assignment**, in the school account, and
  checks the PDFs' layout, the time a class takes and how large decks behave. Those PDFs
  stay in the teacher's data folder, never in this repository.
- Cut the new CAM2 tag (D14) and build its downloads: Mac here, **Windows on a Windows
  computer**. Share it with colleagues, since they're the ones exposed.

*Done when:* the I5 reproduction, run with launchers at or after `v0.3.1-dev`, no longer
upgrades or misroutes a session, `model.VERSION` is still 2, a 16:9 PDF is recognised
and can be sliced into whole-slide questions and graded, and new comments stop at their
limits with no saved comment cut.

**Progress, 2026-11-05.** Built in CAM2's working tree. The tag isn't cut, so the "done
when" above isn't met in a tagged version yet.

- **Checked here, on fictional data with a throwaway app-data folder:** CAM2's tests (352
  pass, 1 skipped) on both PyMuPDF 1.28.2 with Pillow 12.3 and the pinned PyMuPDF 2.0 with
  Pillow 13; slide detection, grid, crops and reports; comment limits in the browser, in
  English and Japanese, including older longer comments. In the browser, two boxes of the
  12-screen deck were drawn by hand and the other ten entered through the same set-up
  route. On one early try a level click sent no request. It didn't happen again in three
  more tries, so its cause is unknown.
- **The I5 reproduction,** with real launcher processes in both directions: `v0.3.1-dev`
  against this tree with its version changed and `model.VERSION` raised to 3, as the
  second pull will do. Each launcher stopped the other version and was handed its own
  exam. Opened through the server's route, not on screen, the `v0.3.1-dev` exam stayed at
  version 2. The newer launcher's exam went to version 3, as its own engine does (I4), so
  the newer server never touched the older launcher's exam.
- **Crop size.** On a fictional 12-screen deck for 28 students, at PowerPoint's size:

  | Deck | PNG crops | JPEG crops at 85 | The PDFs themselves |
  |---|---|---|---|
  | All photos | 1.62 GB | 0.19 GB | 0.20 GB |
  | A photo and text on each slide | 0.83 GB | 0.11 GB | 0.10 GB |
  | Text only | 0.04 GB | 0.08 GB | under 0.01 GB |

  The photos were synthetic, so real decks will differ. That's too big for a synced
  class folder, so JPEG crops came in as this phase allows, more narrowly than the
  slide-deck plan's item 2. **They're for questions on a slide size only, and the paper
  size says which, so there's no `crop_format` key.** Name crops stay PNG because CAM
  reads them as PNG (`exam_bridge.py:370`), and written papers stay PNG for handwriting.
- **An older version and a slide session.** `v0.3.1-dev` refuses it with `Unknown paper
  size` and leaves the folder unchanged, but its `/api/state` keeps failing until it's
  restarted. CAM's current pin refuses it with `file_from_newer_version`, like any
  version 2 session (I4). Phase 5's notes should say so.
- **Left to do:** see the progress note below.

**Progress, 2026-11-06, on the Mac.** Merged and tagged.

- **Review of CAM2 PR #1.** No blocking bugs. Two small fixes went in before the merge:
  - a PDF page that is only a photo (no text, one picture over 90% or more of it), as some
    phone apps save them, is no longer guessed as a slide size;
  - in Step 1, trying a slide size and going back to a paper size restores the
    *landscape* box.
- **Two design points the teacher may want to revisit, not changed:** an older comment over
  the limit can't grow past its last saved length, so rewording it with a pause in between
  can be refused; and Google's 16:10 slide size isn't detected and has no button (Slide 16:9
  works, with cells that aren't square).
- **The level click that sent no request: explained.** Choosing a level focuses **Next
  paper**, which scrolls the page and the grade column, so the levels move from under the
  pointer and a second click can land on empty space. It's in every CAM2 version so far,
  and CAM2's `PLAN.md` ("Still needed", item 4) records it with a possible fix. In a sandboxed
  browser run of a fictional 12-slide deck, every click on a level that was really under the
  pointer sent its request, and what was saved matched.
- **Tagged `v0.3.2-dev`** at CAM2 `4423090`, the commit that sets the version. CAM2's tests
  pass there, 354 with 1 skipped (it needs Node), on PyMuPDF 1.28.2 with Pillow 12.3 and on
  the pinned PyMuPDF 2.0 with Pillow 13.
- **Mac download built** from that commit:
  `CAM2-exam-grading-Mac-AppleSilicon-v0.3.2-dev.zip`, 40 MB, SHA-256 `8acd06c1…115e5`.
  The builder verified its signature and started it from an unzipped copy with a throwaway
  data folder.
- **Released** as the `v0.3.2-dev` pre-release, with the Windows zip built on Windows, both
  zips, the sample exams and the two source archives. The Mac zip on the release matches the
  one built here, byte for byte.
- **The Appendix A trial moved,** by the teacher's choice: first left open when the tag was
  cut, then moved to after the whole upgrade (§6.1). Anything it finds goes in a later tag.
- **The test builds' checks, accepted as done (2026-11-06, the teacher's decision).**
  Colleagues have used them on their own computers largely without problems, so the
  Windows unblock advice and the rest of CAM2's Phase 5 run-through count as done, though
  they weren't tried item by item. CAM2's `PLAN.md` and README say the same.
- **Left to do:** nothing in Phase 1.

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
- **Record what a decision saw (P6).** Add optional `CriterionScore.exam_basis`, a short
  hash of that criterion's levels and marks. Window 3 compares it with the current result
  to show the flag. An older CAM drops it on save, and then the flag just doesn't show.
- `_validate_exam_result` rejects non-string keys in `levels` and `final_levels`.
- **Fix I13.** A student with an exam result and no grade shows as ⏳ awaiting decision
  and stays out of the calculation, not Missing = 0.
- Tests: turn §3.1 and the I2 table into permanent tests, and add one that nothing ever
  writes a second grade for one student, exam and criterion. Those needing a v2 session
  skip until `model.VERSION >= 2`, then run from Phase 4.

*Done when:* the I2 reproduction keeps both grades, and marks-only and rubric behaviour
on the current pin is otherwise unchanged. The I2 fix can ship by itself.

**Progress, 2026-11-06.** Built on the current pin, fictional data only.

- **Tests on the pin:** CAM 353 (8 skipped, all waiting for a version 2 session), CAM2 216.
- **Those 8 tests, run once outside the repo:** in a throwaway copy with CAM2's
  `phase1-slides-and-comment-limits` branch at `3696d1e` as `exam_grading/`, they all pass.
  Only the two I1 tests fail there (`test_rubric_session_levels_and_final_levels` and
  `test_rubric_exam_confirms_levels_per_mapped_criterion`), as I7 expects. They wait for
  Phase 4, which must run this again on the tag it pins.
- **Older CAM:** the engine at `1c41655` loads what this branch writes and resaves it,
  losing only the new keys, so a grade then counts as the teacher's. The tracked sample
  database saves identically through both.
- **Browser, in a sandbox on Windows:** Apply, a re-send with a new final level, a grade
  edited in Window 3 being kept and listed, ⏳ rows, and adding a criterion on the marks
  panel. Window 2's "awaiting decision" tag and the report pack's row weren't exercised.
- **Choices this phase settled:**
  - **The re-send rule runs at Apply, not at Sync.** On this pin `final_levels` also holds
    CAM2's suggestions, and P2 wants someone to confirm the mapping.
  - **`exam_value` is on the 0–8 scale,** because the rule compares it with the grade.
    The raw level stays in the note.
  - **An update keeps the comment, late flag and report flag.** A blank comment takes the
    new one. Phase 3's re-send handling (Q3) is what brings a corrected comment through.
  - **Changing the marks panel's criterion now adds a grade, not moves it,** and Apply says
    so. The grade pop-up's **No grade** choice (Phase 3) removes one, and D18 means the gap
    before it never reaches a release.
  - **The `ExamResult.percent` property is gone.** Nothing called it, and it clashed with
    the new field.
  - **Window 1's dropdowns follow the grade.** Streamlit keeps a keyed selectbox's old value
    when its `index` changes, so a stale dropdown could have overwritten a newer grade.
  - **In Window 3, ⏳ rows stay clickable.** The dialog starts blank, and a blank save writes
    nothing. A paper not finished in CAM2 can be excused but not given a grade (P6).
- **For Phase 3:** the `exam_basis` flag isn't shown yet, Window 1 and Window 3 still route
  on `mode == "rubric"`, and the panel still blocks two rubrics on one criterion. Apply
  already writes nothing when both have a final level (D11).

### Phase 2W — CAM: the workspace keeps typed comments (F4) · S–M

This doesn't depend on any other phase, and D18 holds its release back with the rest
(Q5). Do it early. It's CAM's own code, so it needs no CAM2 change. It's the one change
to the workspace in this upgrade, as F5's first stage says.

- **Browser:** replace the three assignments (I15) with one function that follows P10,
  using the state from before the change. The deadline handler follows P11.
- **Server:** add one optional per-student field for the remembered line, and carry it
  through `/api/save`, linked partners, the rebuilt student list and the data sent to the
  page. A saved file without it must load unchanged, and an older CAM on another computer
  drops it, which falls back to P10's comparison.
- **Keep the other routes right:** a renamed tick updates the remembered line too
  (`remapKeywordLabel`), and a comment edited in CAM or restored from a draft's published
  feedback follows P10.
- **Change no export.** The CSV's comment column stays the whole comment.
- **Tests.** There's no JavaScript test set-up and no Node on this Mac:
  - server round trips in the workspace's tests, including linked partners;
  - a sandbox browser check on a fictional task (temp prefs, temp `db_custom_path`): each
    of the three triggers with typed text, an older saved comment with no remembered line,
    a comment edited in CAM, linked partners and a renamed tick. **Run the deadline case on
    today's code first,** since it has only been read so far.

*Done when:* in that browser check, no trigger loses typed text, and a deadline change
leaves students whose Late flag didn't change untouched.

**Progress, 2026-11-06.** Built from `main`, on fictional data only. Both "done when" points
were met in the browser check below.

- **The deadline case on the old code, now run:** in a sandbox with a typed comment on a
  student whose Late flag didn't change, a deadline change emptied the comment and saved all
  four students. I15's reading of the code was right.
- **Tests:** CAM 299 and CAM2 216, on this desktop with Node, so none skipped. There's now a
  JavaScript test that runs the real page functions through Node, and it skips where there's no
  Node.
- **Browser, in a sandbox on Windows:** typing then ticking with real clicks and keys, then
  driving the page's own controls by script for the rest: tick and untick, the Late tick,
  a deadline change in both directions (only the students whose flag changed were saved, and a
  waived one stayed put), an older comment with and without its line, comments rewritten and
  extended through CAM's published file, linked partners, a renamed tick, and a reload.
- **Choices this phase settled:**
  - **The line and the text are joined by a space, not a new line as in CAM2.** CAM's
    `clean_comment` doesn't remove a new line, which would show in the comments log, and a
    space leaves the export and CAM's screens as they are today.
  - **A comment a draft takes from its published feedback forgets its remembered line,** so
    it's compared with the line its ticks give. A comment edited in CAM keeps it, so an edit
    that leaves the line in place still has it replaced.
  - **A save's reply no longer overwrites newer text.** It's older than anything typed or
    ticked while it was on its way, and it could otherwise bring old text back.
  - **`comment_line` needs no bump to `CACHE_VERSION`,** since it's optional.
- **Two more problems this phase found, fixed here at the teacher's decision (2026-11-06):**
  - **Linking partners replaced one student's comment, grades and ticks with no warning.**
    Now the grade comes from the first graded member and reaches the group, as before, and
    **every comment combines**, so a group's comment can be longer than one student's. Ticks
    combine too, under one generated line. Linking saves both students first, because the
    server combines what it holds.
    - **There's no record of when a grade was given.** So with two students already graded,
      the one clicked first wins. A new partner joining a group never changes its grade.
    - **A criterion only one member has a grade on is kept,** rather than deleted.
    - **Only a whole comment counts as the same.** So a third partner whose words already sit
      inside the combined text repeats them, which P10 prefers to losing any.
    - **Unlinking leaves each student with the combined result,** and Late stays one flag for
      the group, from the first graded member.
    - **This needs the generated line on the server** (`_generated_line`), a second copy of the
      page's `autoComment`. A test runs both on the same input.
  - **A keyword list never edited came back after a reload with only the ticked keywords,**
    because the default list wasn't saved, and the server rebuilds a missing list from ticks.
    Now the page saves the list as soon as a task opens. A rebuilt list whose ticks are all in
    the default list brings back the whole default list. Otherwise it's a custom list, and
    what was ticked is all that can be recovered.
    - **A task already reloaded before this fix stays short.** Its short list was saved, and it
      can't be told from one the teacher shortened on purpose, so its keywords need adding back
      by hand.
- **A second review found four more, all fixed:**
  - **A Late flag could export as not late.** The page works out a student's flag at load, and
    the old deadline handler happened to save everyone's. Saving only flips (P11) meant a
    flag worked out as late might never reach the server, and a blank Late cell reads as not
    late in CAM. The page now saves a flag it works out as late when the task opens.
  - **Opening a task from CAM replaced text typed here and not yet exported,** for graded tasks
    and drafts, with no warning. CAM publishes its copy at every handoff. Now `cam_comment`
    remembers the copy last seen: an unchanged copy is older than what's here, and a changed
    one replaces a comment left as it was. If both changed, or no copy has been seen, the two
    go together, which can repeat some text once (P10).
  - **A save's reply could overwrite what was being typed in a partner's box.** The reply now
    leaves any student whose comment moved while it was on its way.
  - **Linking carried on after a failed save,** which could lose the text. It now stops and says
    so. A pending keyword save is also cancelled when another task loads.
- **Tests after that review:** CAM 316 and CAM2 216.
- **Checked for those two:** CAM 309 and CAM2 216. In the same sandbox: the keyword list on
  first open, after ticks and reloads, rebuilt from ticks, custom, and shortened on purpose;
  linking with typed and unsaved comments, a graded partner and a grade given after linking;
  a tick and a deadline change after linking; a reload, unlinking and the export. The link
  buttons were pressed by script. The first run of this check lost typed text that hadn't
  been saved, which is why linking now saves first.
- **Not checked:** an older workspace on another computer, which from reading its code drops
  the field on save. Draft restoring ran in a server test only, not in the browser, and linked
  drafts ran in server tests only. Linking wasn't tried with the mouse. **The older
  workspace is out of scope** (2026-11-06): the teacher updates every computer before
  running CAM again.

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
- **Exam comments in the term comment** (F6, I16, P12, Q2 to Q4). The teacher wants these
  to have a large place in a student's term comment.
  - **Keep the comment on a decision.** A Window 3 decision copies the overall comment
    onto its `CriterionScore`, as Apply does today (`comment=r.comment`, `app.py:7546`,
    `7671`), so the edit dialog and comments log keep working.
  - **Add the block.** An always-included `[CURRENT TERM — EXAM FEEDBACK]` block beside
    the draft block (`app.py:6354`). It reads `student.exam_results` for this class's exams
    this term, so it works before any grade is decided. Build it in one function, so the
    second pull can add F2's notes in one place.
  - **Overall comment (Q3).** If the exam has grades for this student, use their comments,
    each different text once. Otherwise use `ExamResult.comment`. Clearing the comments
    in Window 3 removes it from the block.
  - **Re-sends (Q3).** In `_ingest_cam2_session`, a grade whose comment equals the previous
    result's comment takes the new one. An edited comment is kept.
  - **Exams leave the ranking (Q2).** `_current_term_evidence` skips exam scores, which is
    also what stops the comment being sent twice. Grades still count in the criterion
    results and the trend. Assignments stay chosen by ranking.
  - **Leave out** exams excused for that student (`assessment_exclusions_for`). Pass
    comments through `clean_comment`, as evidence is, which drops the `Strengths:` and
    `Areas to develop:` labels from CAM2's comments.
  - **Limit the source material (Q4, P13).** Build this in CAM, because CAM2's limits (Q8)
    don't settle it: two exams at those limits still go over, and an older session can hold
    longer comments. Count characters, not words, because Japanese has no spaces. Drafts
    and assignments have no limit, so they count towards the total. Show the teacher how many comments were left out, beside the
    generated comment.
  - **Ask for a summary, not a copy.** Tell the LLM to summarise in its own words, and not
    to pad when there's little material. Today's prompt doesn't say this, and it shows
    evidence inside quotation marks (`Evidence.as_text`), so leave those off the new block.
  - **Fix the wording from a trial (Q4).** Use fictional students at 100 and 150 words:
    one with little material, one at about 500 words, one at about 1,000, and one over the
    limit with 15 question comments of 300 characters and two exams in one term. The block
    tells the LLM to use this as a main source for both strengths and growth.
  - **End of year:** the existing **Word limit** setting already goes from 40 to 400, so 150
    words needs no new code.
- Round-half-up for any new percentage display, not Python's `round()`.
- Sandbox browser check: temp prefs, temp `db_custom_path`, fictional class. Include
  the 12-screen fixture from the slide-deck plan. Its A 1, B 5, C 2 and D 5 levels must
  end as at most one gradebook grade on each criterion, with the calculated grade the
  same however many slides fed the decision.

*Done when:* a deck's levels show grouped in Window 3, one decision writes one grade, a
blank dropdown can't invent a grade, a re-send can't change a teacher's decision, and
tests show that:

- an exam's overall and question comments are in the prompt whatever its grades, and
  before any grade is decided;
- an excused exam's aren't;
- a comment edited or cleared in Window 3 is respected;
- an exam on four criteria sends its overall comment once and takes no strength or growth
  place;
- a re-sent comment replaces only copies the teacher hasn't edited;
- material over the limit leaves out whole question comments, keeps every overall comment,
  and reports the number left out.

**Progress, 2026-11-06.** Built on the current pin, fictional data only. Every "done when"
above is covered by tests. The Q4 trial ran on fictional students (below), and it improved
the wording without settling everything.

- **The Q4 trial.** Fresh agents on the Sonnet family wrote each comment from the real
  compiled prompt, seeing nothing about the trial. The app's default is `claude-sonnet-4-6`,
  so this isn't exactly that model, and each row is a small sample of synthetic comments.
  "Copied" counts words inside a run of 5 or more that also appears in the exam source.

  | Round | Wording | Comments | Length against target | Copied | Longest run |
  |---|---|---|---|---|---|
  | 1 | "in your own words rather than repeating their phrases" | 8 | 100–110% | 11–29% | 12 words |
  | 2 | "no run of five or more words matches" | 8 | 92–107% | 0–7% | 5 words |
  | 3 | Round 2's, and the word limit as a ceiling | 4 | 88–102% | 0–12% | 9 words |

  - **Copying is much reduced, not gone.** Round 3 kept round 2's wording on copying and still
    gave a 9-word run in three of four comments, so round 2's result was partly chance.
  - **Copying didn't get worse as the source shrank.** The limit (P13) keeps the material in
    reach, but this trial doesn't show it reduces copying.
  - **Padding isn't solved.** A 47-word source gave 89 words against a 100-word limit, but 153
    against a 150-word limit. The ceiling didn't noticeably shorten comments with plenty of
    material (88–98%).
  - **A conflict this exposed is fixed.** The closing "Base the narrative ONLY on…" line left
    out the exam block.
  - **Exam comments did feed both strengths and growth** in every comment read.
  - **Still to check:** real comments on the teacher's usual model, and Japanese text, which
    the trial didn't cover. The teacher tries these after the release (Phase 6, step 7).
- **Tests on the pin, with Phases 2, 2W and 3 together:** CAM 473 (8 skipped, all waiting for a
  version 2 session), CAM2 216.
- **Older CAM, rerun with all three:** the engine at `1c41655` reads a mixed exam with the new
  fields and resaves it, losing only the new keys.
- **Outside the repo,** with CAM2's `phase1-slides-and-comment-limits` branch at `3696d1e`
  as `exam_grading/`: those 8 pass, and only the two I1 tests fail, as I7 expects.
- **Browser, in a sandbox on Windows,** on that branch and then the pin: the 12-screen
  fixture with its A 1, B 5, C 2 and D 5 levels grouped, a decision, blank clearing it, Apply
  with its summary, the changed-levels flag and Keep grade, an unfinished paper, a mixed and
  a weighted exam, the plain marks panel, Add assignment, and the exam block in a compiled
  prompt. Generating a comment through an AI wasn't run. The teacher does that in Phase 6,
  step 7.
- **Choices this phase settled:**
  - **Window 1 has no per-student dropdowns for an exam with rubrics.** P2 keeps the mapping,
    the progress count and one Apply, so the re-send rule no longer has a dropdown to read.
  - **A decision made in Window 3 has no `exam_value`,** even if it equals CAM2's level, so a
    re-send can never change it.
  - **A typed final level is shown and isn't written until Apply,** because someone must
    confirm the mapping (P2). On this pin the suggested levels also arrive as final levels,
    and they show the same way until Phase 4.
  - **Keep grade was added beside the flag.** Without it, the flag could be cleared only by
    changing the grade and changing it back.
  - **P13 in numbers:** exams can always use 4,000 characters, and up to 6,000 less what drafts
    and assignments use. Only question comments can be left out, so very long drafts or
    several overall comments can take the total past 6,000.
  - **`ExamResult.suggested_band` is gone,** since nothing may suggest a grade from marks.
- **Three problems found in review, and fixed (2026-11-06, the teacher's go-ahead):**
  - **A student with no paper counted 0 on every mapped criterion once any classmate had one
    grade.** Now they count 0 only on a criterion where a classmate has a grade (D10). Window
    3 shows the others as `not graded yet`, still clickable, and a report lists only the zeros.
    The row on a manually created exam with no grades yet used to say `0 (missing)` too, though
    the math never counted it, and now says the same.
  - **Some exam grades couldn't be removed:** on a plain marks exam, and on a criterion no
    longer mapped. The grade pop-up now offers **No grade** on any exam's grade. Saving it also
    keeps the exam's mapped criteria listed, which the pop-up used to drop.
  - **A grade decided in the pop-up lost the overall comment,** because the comment box started
    empty, which counts as clearing it (Q3). A new grade on a paper now starts with its overall
    comment, and clearing the box is still respected.
- **A second review found what else assumed a listed criterion means a graded one:**
  - **The automatic calculation method** counted an exam with no grades, so a sync could flip
    it for the class. An exam now counts once it has a grade.
  - **The analytics dialog** said `Graded: Crit A,B,C,D` with no grades. It now names only
    criteria that have grades.
  - **Window 2's list** called an exam nobody has graded plain missing work, beside a caption
    saying it counts as 0. It now says `not graded yet`.
  - **Remapping a rubric** left grades on the old criterion counting with no notice. Window 1
    now names them and says how to take one off.
  - **Evidence for the term comment** dropped an assignment that shared a name with another
    class's exam. It now looks only at the active class's exams.
- **Checked since the first run, in a sandbox on Windows:** the real app on fictional exams,
  partly by mouse and partly by script: the pop-up showing the paper's comment, saving it, a student with no paper showing 0
  on the graded criterion only, and adding then removing a plain marks exam's grade. **Window
  2's `awaiting decision` tag** also showed correctly, which Phase 2 hadn't run. **The report's
  rows** ran in tests, not through a downloaded report.
- **For Phase 4:**
  - update the two I1 tests, and recheck the Window 3 wording once only typed final levels
    arrive;
  - **read CAM2's adjusted figures.** The CAM2 going into the tag lets a teacher type over a
    report's total or percentage (`report_total`, `report_percent`, `adjusted`), and
    `read_session` reads only the calculated `total` and `percent`, so a report could say 18/20
    with CAM showing 15/20. Show the adjusted figure beside the calculated one, read-only, and
    add it to the matrix. This comes from reading the code, and hasn't been run.

### Phase 4 — Pull CAM2, notices, bundle · M–L

- `git subtree pull --prefix exam_grading <cam2> <tag> --squash`, then confirm the
  vendored tree hash equals the tag's.
- Update `test_exam_bridge.py:214` and `test_exam_cam2_host.py:370` to the new rules,
  and un-skip the v2 tests.
- Add `Exam-Section-Plan.md`, `Feedback-and-Upgrades.md`, `requirements-build.txt` and
  `licences` to `EXAM_DEV_PATHS`, since CAM's own `Licences` folder below replaces the last.
  Also remove CAM's `docs/CAM2_FEEDBACK_FOR_CAM.md` from the bundle, and extend
  `test_windows_bundle.py` to cover all five.
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
- Read CAM2's adjusted report figures in `read_session`, and show them beside the calculated
  ones (see Phase 3's progress note).
- `python tools/run_all_tests.py` passes, including with PyMuPDF 2.0.
- **PyMuPDF for the bundle is 2.0,** as CAM2's tag pins and its release's source archive
  matches. 2.1 also installs `pymupdf_layout`, `pymupdf4llm`, onnxruntime, numpy and
  networkx, which nothing in CAM or CAM2 uses, so moving to it is a separate decision
  with its own licence check.
- Sandbox end to end with `exam_grading/tools/make_sample_exam.py` and a real browser:
  marks; rubric with and without final levels; levels on one criterion across many
  questions; marks ticked on a criterion; a 16:9 slide deck; mixed from both starting
  choices; weighted;
  choice groups; and a v1 session upgraded mid-grading. Each must Sync, be decided in
  Window 3 or carried by Apply, and show in Windows 2 and 3, leaving session folders
  byte-identical after Sync. Its comments must reach the term comment prompt. **Also run
  the checks left from earlier phases:** a CAM2 exam's row in a downloaded report, and
  restoring and linking drafts in the workspace with the mouse. This run comes after
  Phase 4's code, since the teacher runs CAM2 only once the upgrade is done.
- **On a Windows computer:** build the bundle and boot it with its embedded Python. CAM
  starts, CAM2 opens in host mode and sends to CAM, and the `Licences` folder is there.

*Done when:* the whole matrix passes. Nothing is released yet.

**Progress, 2026-11-06, on the Mac.** The code is on the `cam2-upgrade-phase4` branch. The
browser matrix and the Windows build are still to do.

- **Pulled:** CAM2 `v0.3.2-dev` (`4423090`) as `exam_grading/`. Its tree hash, `cbf9445`,
  equals the tag's, and the tree before the pull equalled the old pin's, so nothing had been
  edited in place.
- **I1 tests:** the two now expect only typed final levels, and a new test shows a rubric
  exam with no typed level brings Apply nothing. The 8 tests waiting for a version 2
  session now run and pass.
- **Adjusted report figures:** `read_session` keeps `report_total` and `report_percent`
  only when CAM2 marks them `adjusted`, as CAM2 does, so typing the calculated figure
  again isn't an adjustment. They're saved and validated with the exam result. Window 1's
  marks panel and Window 3's total show "report shows 18/20 (typed in CAM2)" beside the
  calculated figure, which stays what CAM shows and works with. The downloaded report pack
  prints only decided grades, so it needed no change.
- **Bundle:** `EXAM_DEV_PATHS` gains the four CAM2 paths, and
  `docs/CAM2_FEEDBACK_FOR_CAM.md` stays out. `test_windows_bundle.py` covers all five.
- **Notices (D15):** `tools/bundle_licences.py` and
  `tools/bundle-requirements-windows.txt`.
  - **87 libraries,** pinned exactly with their licences and installed with `--no-deps`, so
    nothing unpinned arrives. `python tools/bundle_licences.py pin windows` regenerates the
    list from pip's dry run for Windows, keeps licences already checked, and marks a new
    one `?`, which the build refuses.
  - **CAM2's versions win** for the libraries both use (Flask, PyMuPDF 2.0, openpyxl and
    their dependencies), **except Pillow:** CAM's Streamlit 1.58 needs it below 13, so it
    is 12.3, which CAM2's tests also pass on.
  - **PyMuPDF's add-ons stay out,** as CAM2's build does: `pymupdf_layout` and
    `pymupdf4llm` are empty placeholder packages, and onnxruntime (80 MB), networkx,
    psutil, PyYAML, tabulate and flatbuffers are only for PyMuPDF's AI layout. PyMuPDF
    renders and reads text without them (checked with them blocked).
  - **The build checks** that what was installed equals the pins, and that every library has
    a licence and a licence text, then writes `Licences`: `NOTICE.txt` (the AGPL overview,
    where the source is, and the library table), `AGPL-3.0.txt`, `CAM-MIT.txt`,
    `CAM2-MIT.txt`, and `THIRD-PARTY-NOTICES.txt` with the embedded Python's licence and
    each library's own licence files. Streamlit ships none, so its Apache-2.0 text is
    stored in `tools/licence-texts/`. pip is removed after the install.
  - **Where they are:** READ ME FIRST, the README, and a new **About CAM and its licences**
    section at the end of Settings, in English and Japanese, worded like CAM2's.
- **Tests, in a sandbox on the Mac:** CAM 487 (5 skipped, all needing Node) and CAM2 354
  (1 skipped, Node), on the dev venv's PyMuPDF 2.0, and again in a venv with exactly the
  pinned versions (Streamlit 1.58, Pillow 12.3, PyMuPDF 2.0, no add-ons). A stage-only
  build has the `Licences` folder and none of the left-out files.
- **Browser matrix, on the Mac (2026-11-06):** passed, in a sandbox copy of the tracked files
  with every data path in temp, on the exact pinned libraries. The real database's timestamp
  was the same before and after.
  - **Sessions:** nine built with CAM2's engine (marks with a choice group, rubric with typed
    levels for half the class, 12 levels on one criterion, marks ticked on two criteria, mixed
    from both starting choices, weighted with a typed report percentage, an open "teacher
    picks" group, and a version 1 session from the old pin, finished on the new engine), plus
    a **16:9 slide deck through the real CAM2 screens**: started from CAM in host mode, slides
    detected, boxes drawn, sliced, names matched from CAM's class list, graded, a report
    total typed over, and sent.
  - **Checked:** each Synced, with every total matching a hand calculation; session folders
    byte-identical after every Sync (CAM2's own `cam2.lock` heartbeat aside); Apply for plain
    marks and typed levels; decisions in Window 3's pop-up; ⏳ awaiting decision in Windows 2
    and 3, never a 0; Window 3's wording with typed-only levels ("CAM2 final level: 6. Not in
    the gradebook yet…"); the report-figure caption for a typed total, a weighted percentage
    and one typed in CAM2's own screen; the version 1 session arriving with its typed level
    only; exam comments in the term comment prompt, with no scores.
  - **Left from earlier phases, now run:** a CAM2 exam's rows in a downloaded report-card pack
    (decided grades and "awaiting decision"); linking two drafts **with the mouse** in the
    workspace, which combined ticks and comments under one generated line and exported to
    CAM; and **restoring drafts**: with the workspace's own state set aside, reopening from CAM
    brought back every comment and tick from CAM's published copy, and a second export
    duplicated nothing.
  - **Not covered:** CAM2's native folder dialog (its "paste a path" box was used), and
    generating a comment through an AI (Phase 6, step 7).
- **Found in the browser run** (none caused by Phase 4):
  - **Report-card pack: correct as it is (the teacher's decision, 2026-11-06).** Once a student
    has a grade on an exam, the pack lists only the criteria decided. Teachers often assess
    one or two criteria per exam, sometimes one for the whole term, so the report should show
    only what was assessed.
  - **A restored draft loses its partner link.** Links live only in the workspace's own state,
    so on a fresh computer the combined comments come back but the two cards aren't grouped.
    No text is lost.
  - **The level buttons move after a click** in CAM2's grading screen, as already recorded;
    the next CAM2 update fixes it.
  - **Cosmetic:** the report-figure caption wraps onto three lines in Window 1's narrow column,
    and CAM2's Step 1 thumbnails show slides inside portrait cards.
  - **Test setups only:** CAM's automatic exam sync and "Force full re-scan" need
    `db_custom_path` in the prefs, so a harness that sets only `CAM_DB_PATH` never syncs
    exams. Teachers always have the path set.
- **Still to do in Phase 4:**
  - **The same browser run on the Windows Surface** (the teacher's choice), through Claude
    Code there, with the same sandbox rules.
  - **On a Windows computer:** a full build, which runs the pins and licence checks for real,
    then boot it with its embedded Python, CAM2 in host mode, and the `Licences` folder.
- **For the release (Phases 5 and 6):** attach `pymupdf-2.0.tar.gz` and
  `mupdf-1.28.5-source.tar.gz` to CAM's release, as NOTICE.txt says, and mention the licence
  in the release notes.

### Phase 4M — CAM: a Mac binary · M–L (D18)

Scoped from reading the code. None of it has been built or tried. Apple Silicon only, as
CAM2 decided, since there's no Intel Mac to build and test on.

- **Check Gatekeeper first; this is the main risk.** CAM2 needs "Open Anyway" once
  because PyInstaller packs it into one signed app. CAM can't copy that: it starts the
  workspace and CAM2 as separate Python processes through `sys.executable`
  (`app.py:2833`, `exam_bridge.py:280`), so it needs a real Python inside the download,
  as Windows has, along with hundreds of compiled libraries. If a downloaded copy makes
  the Mac object to each of those, the free route won't work. Try it early with a small
  unsigned download on a Mac that didn't build it. If it fails, the choices are Apple's
  paid signing and notarising (US$99 a year, the teacher's decision), or staying on
  running from source.
- **A new `tools/build_mac_bundle.py`**, sharing what it can with the Windows tool. Python
  has no embeddable Mac download, so this needs a relocatable build such as
  python-build-standalone, and `requirements.txt` installed into it. The `._pth` path
  rules become an explicit `sys.path` set-up in the launcher, keeping `exam_grading` off
  the path as today.
- **A Mac launcher**, replacing `Start CAM.vbs` and the troubleshooting `.bat`: start
  Streamlit headless on port 8600, wait for its health check, open the browser, and write
  `logs/cam.log`, plus a READ ME FIRST with Mac steps, modelled on CAM2's.
- **Screens that are Windows only today:**
  - `pick_folder` returns nothing off Windows, and the five 📁 Browse buttons are hidden
    (`app.py:6684`, `6773`, `7728`, `9986`, `10247`). A teacher would have to type every
    path, so add a Mac folder picker, for example through `osascript`.
  - "Start fresh" offers no default folder off Windows (`app.py:10267`).
  - Placeholder paths show only Windows examples.
- **Stop the workspace when CAM stops.** The Windows job object at `app.py:2744` doesn't
  run on a Mac, so a crash could leave the workspace running.
- **Check on a Mac:** file locking already has a Mac path (`persistence.py:1392`), but the
  bundle hasn't run it against OneDrive's Mac folder (`~/Library/CloudStorage`).
- **Licences per platform.** Mac libraries differ, so pin exact versions and keep notices
  for each platform, with Phase 4's build check on both. The Mac runtime needs its own
  entry.
- **Audit and tests.** The same credential and data checks as the Windows zip, including a
  check of the final zip, and a check that links and signatures survive unzipping, as
  CAM2's Mac build does.
- **Sandbox end to end from an unzipped copy:** temp prefs and `db_custom_path`, on a Mac
  account with no developer Python. CAM starts, Browse works, the workspace opens a local
  folder with a subfolder per student and needs no Google sign-in (F5's route), and
  CAM2 opens in host mode and sends to CAM. **This Mac's prefs point at real data, so the
  test must not run under them.**
- **A cross-computer check:** one fictional data folder synced between the Mac bundle and
  the Windows bundle, in both directions.
- Phase 5's guides gain the Mac steps and screenshots.

*Done when:* a downloaded zip runs on a Mac that didn't build it, with the same exam
matrix as Phase 4. Nothing is released yet.

### Phase 5 — Documents and release notes · S–M

- Rewrite the exam parts of `USER_MANUAL.md` and `QUICK_GUIDE.md` (and its PDF),
  `ARCHITECTURE.md` §4 and `DATA_DICTIONARY.md`, and the `app.py:7560` docstring.
- Mark D3 and D4 as amended in the convergence plan. Update `SLIDE_DECK_EXAM_PLAN.md`
  for D10 to D13 and D16, and for D17: slide sizes are done, its Drive phases are
  deferred, so its "Phase 0 comes first" no longer applies, and Appendix A stands in for
  its Fetch from Drive step.
- Update `CAM2_FEEDBACK_FOR_CAM.md`: what shipped, and the second pull's starting point.
  Say in the manual how a term comment now uses exam comments, and how ticks and typed
  comments combine in the workspace.
- Add `CHANGELOG.md` and release notes that say plainly:
  - update **every computer before opening an exam**, because opened exams can't go
    back;
  - exams go through CAM2, and a draft is set up as an assignment with the **Draft —
    comments only** check mark;
  - slide decks can be graded in CAM2 as PDFs, and fetching from Drive isn't included;
  - a paper's levels show in Window 3, and the teacher decides one grade per criterion
    for the assignment, unless a final level was typed in CAM2;
  - marks are never turned into grades by the app, and bands are no longer pre-filled;
  - what `file_from_newer_version` means on a computer not yet updated;
  - in the workspace, ticks and deadline changes no longer overwrite typed comments, so
    the tick-first workaround can stop;
  - linking partners now combines their comments and ticks, and the first graded member's
    grade reaches the group;
  - a keyword list no longer shrinks on reload, and a list that already shrank needs its
    keywords adding back by hand;
  - every exam's overall and question comments now go into the term comment prompt, and
    so to the AI service the teacher has chosen, and exams no longer take the strength
    and growth places;
  - a term with a lot of comments may have some question comments left out of that prompt,
    and CAM says how many;
  - CAM2 now limits a new question comment to 300 characters and an overall comment to 600,
    and comments already saved are never cut;
  - a later CAM2 update will raise the session version again, so the "update every
    computer first" step will come back (Q1).

### Phase 6 — Roll out to real data · S (explicit permission required)

"Testing the app" isn't permission. Each step needs the teacher's go-ahead in that
session.

1. Run `tools/exam_exposure_report.py` again, with permission. Phase 0's count of zero is
   from 2026-11-05, and any real exam opened since changes it.
2. Update every computer, and the standalone CAM2 on each, to the same tag.
3. Back up: `acm_database.json.bak-cam2-upgrade-YYYYMMDD-HHMMSS` beside the database,
   and a dated copy of each class's `exams/` folder **before any exam is opened**.
   Never prune existing `.bak-*` files.
4. Open one low-stakes exam. Check its counts against the step 1 numbers, and that its
   existing gradebook grades are unchanged.
5. Then open the rest as needed. Grades already applied from older rubric exams stay as
   they are, and neither a re-send nor Apply replaces them silently.
6. In the workspace, change one tick on a low-stakes task that already has typed comments,
   and check that the text stays. **Don't try the deadline first on real work.**
7. Generate one term comment on a student with an exam, as the teacher would normally,
   on the usual model, and in Japanese too if used. The teacher judges whether the exam
   has a large enough place (Q4).

**Rollback:** revert CAM to the previous release and restore `exams/` from the step 3
copy. A v2 session can't be opened by older code. CAM2 also leaves a v1 copy in
`backups/` when it upgrades, but that backup is per day, so don't rely on it. Grades
entered after the upgrade would need re-entering. The older workspace ignores the
remembered line, so the F4 bug simply returns.

*Done when:* all computers are updated, every sampled exam matches its numbers from
before the upgrade, and steps 6 and 7 passed.

### 6.1 After this upgrade

These aren't in Phases 1 to 6. The details are in `CAM2_FEEDBACK_FOR_CAM.md` and CAM2's
`Feedback-and-Upgrades.md`. They stay on record here because of what they ask of this
upgrade.

| Entry | What it asks of this upgrade |
|---|---|
| **F1, F2:** session version 3 | Don't let Phase 1's tag raise the version (Q1). F2's comment limits come early (Q8), and its notes, with their own limit of 120 characters, stay here. Keep the bridge routing per question, and the F6 block in one function, so notes are one addition. F1's ceilings need nothing from CAM: `read_session` doesn't read them, and rubrics stay out of 8 |
| **F3** | Nothing. It's on hold, because F5 would replace it |
| **F5:** retire the workspace | D16 stands until its last stage (Q6). Add nothing to the workspace beyond Phase 2W |
| **F7:** a year's work and one student ID | Nothing for the ID itself (Q7). `exam_results` is keyed by exam name alone (`models.py:179`), so one student with a same-named exam in two classes would collide, and that needs fixing before students carry across years. `_walk_class` skips only `exams/`, so a new `assignments/` folder would be scanned for CSVs |
| **F8:** compact and delete | Nothing to read. CAM uses only `crops/__name__/` (`exam_bridge.py:370`), and Sync reads only the session and grades files. Showing or emptying `exams/_deleted/` is separate CAM work |
| **F9 to F15** | Nothing. Comparing exams over time stays in CAM (F14) |
| **The Appendix A trial** (moved from Phase 1, 2026-11-06) | Nothing. The teacher tries the Apps Script route on a small real assignment once this upgrade is released. Anything it needs goes in a later CAM2 tag |
| **Level buttons that move after a grade** (CAM2's `PLAN.md`) | Nothing. The fix goes in the next CAM2 update and reaches CAM with the second pull |
| **Google's 16:10 slide size** (Phase 1's progress note, decided 2026-11-06) | Nothing. CAM2 detects it and gets a button in the next update, and it reaches CAM with the second pull. Until then a 16:10 deck can use Slide 16:9 |
| **Older comments over the new limits** (Phase 1's progress note, decided 2026-11-06) | Nothing. Left as is: only colleagues testing CAM2 have any |

**The second pull:** change CAM2, tag it, and `git subtree pull`. Add the F2 note fields to
`test_exam_bridge.py` with it. Release notes repeat the "update every computer first"
step.

---

## 7. How this was checked, and what wasn't

Everything ran in a throwaway clone with `HOME` and `CAM2_APP_DATA` redirected to a temp
folder, on fictional data. The real prefs and database were checked before and after
and are unchanged, and neither repo's code was modified.

| Suite | Pin `1a40845` | CAM2 `main` `7d34779` | CAM2 `main` `5931f22` (v6) |
|---|---|---|---|
| CAM | 267 pass (1 skipped) | **2 failures**, both I1 | 292 run, **the same 2 failures** (1 skipped) |
| CAM2 | 216 pass (1 skipped) | 328 pass (1 skipped) | 331 pass (1 skipped) |

CAM's count rose because of Phase 0's report tests. The v6 run was a trial pull in a
throwaway clone with `HOME` and `CAM2_APP_DATA` redirected, and its tree matched CAM2's.
It used the same PyMuPDF 1.28.2 and Pillow 12.3.0 as before.

For v6, every line number in the feedback note was checked against the code. I15 comes
from reading the code and hasn't been run. I16's ranking example ran against the real
`select_evidence` with fictional data, and the prompt itself wasn't generated. The rest of
I16 and §6.1's rows come from reading the code. `compile_prompt` wasn't run, and neither
were F1, F2, F7 and F8, which exist only as proposals.

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
- CAM2's I5 fix with real launcher processes. Its own tests pass, but the I5 reproduction
  hasn't been repeated, which Phase 1 does. Everything in Phases 2 to 4 doesn't exist yet.
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
