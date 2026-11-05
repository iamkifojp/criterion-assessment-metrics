# CAM2 feedback that affects CAM

**Status:** 2026-11-05. Nothing here is built. More feedback from colleagues is still to come, so expect a second CAM2 update after the one in [CAM2_ENGINE_UPGRADE_PLAN.md](CAM2_ENGINE_UPGRADE_PLAN.md).

**The full entries are in CAM2's [Feedback-and-Upgrades.md](https://github.com/iamkifojp/cam2-exam-grading/blob/main/Feedback-and-Upgrades.md).** This note lists only what each one means for CAM, so that the details stay in one place. The F numbers are that document's. Suggesters stay anonymous.

Line numbers refer to CAM `main` at `002ab0c`.

## Where the two repos stand

| | Commit | Notes |
|---|---|---|
| CAM2 pinned in CAM | `1a40845` | 28 commits behind CAM2 `main` |
| CAM2 latest tag | `v0.3.1-dev` | Has the hand-over fix from the upgrade plan's Phase 1 (I5) |
| CAM2 `main` when this was written | `ecd1eb0` | Only documents differ from the tag |

**Phase 1 isn't finished.** CAM2 still has no slide-shaped pages (D17, I14), so the new tag that D14 pins hasn't been cut.

## For this upgrade

| Entry | What CAM needs | Where it is recorded |
|---|---|---|
| **F6:** exam comments should carry weight in term comments | Keep the overall comment when Window 3 decides a grade, and add an always-included exam block to the LLM prompt | Upgrade plan, Phase 3 |
| CAM2's feedback document | Keep it out of CAM's bundle once it arrives in `exam_grading/` | Upgrade plan, Phase 4 |
| **F2's comment limits:** 300 characters on a question, 600 overall | Nothing to read, and the session version doesn't change. CAM still limits what goes into the term comment prompt | Upgrade plan, Phase 1 and Q8 |

**Why F6 can't wait.** The term comment reads only `student.scores` (`_current_term_evidence`, `app.py:6117`):

- **The overall comment** reaches a grade only because Apply copies it there (`comment=r.comment`, `app.py:7546` and `7671`). Phase 3 moves grade decisions to Window 3, so a decision made there has to copy it too, or the comment drops out of the prompt.
- **Even then,** it is used only if that exam ranks among the student's highest or lowest pieces (`select_evidence`, `app.py:6342`).
- **Each question's comment** stays in `ExamResult.question_comments` and never reaches the prompt.

Draft comments are always included (`app.py:6354`), so exams currently get less than drafts do.

## To fix in the same release

**F4: the grading workspace overwrites typed comments.** This is in CAM's own code, so the CAM2 pull won't fix it, and no other work depends on it. It can be fixed at any time, and it reaches teachers with the upgrade release, since D18 holds all releases until then. Planned as Phase 2W of the [upgrade plan](CAM2_ENGINE_UPGRADE_PLAN.md).

`autoComment` rebuilds the whole comment from the ticks, so typed text is lost in three places in `cam_grading_workspace/app.py`:

| Line | What sets it off | Who loses text |
|---|---|---|
| `4430` | Changing a tick | That student |
| `4412` | Changing the Late tick | That student |
| `4711` | Changing the deadline | **Every student in the task.** This hasn't been run, only read from the code |

**Workaround until then:** tick first, then type, and set the deadline before writing any comments.

**Fix:** remember the line last generated and replace only that, as CAM2 does with `keyword_text` in `engine/keywords.py`. Saved comments have no remembered line, so the first change on one needs care not to lose or repeat its text.

## After colleagues' feedback

None of these change the current upgrade.

| Entry | What CAM would need | Notes |
|---|---|---|
| **F1:** highest level for a question | Nothing to read. CAM can ignore the ceilings | Adds to the session file, as F2 does (see below) |
| **F2:** notes and highlights on answers | `engine/exam_bridge.py` reads the note text with each question's comment, and F6's block includes it | Without this, notes never reach CAM's records or term comments |
| **F3:** one comment list in both apps | Nothing while F5 is the plan | On hold. F5 would replace it |
| **F5:** move drafts and assignments into CAM2, and retire the workspace | Tell CAM2 when a task is a whole submission, read the same CSV the workspace writes (still to check), and later remove the workspace, OAuth and Drive code | **Direction agreed; D16 stays as it is for now** (upgrade plan, Q6). The workspace stays in use until CAM2 has proved it can take over, so Phase 3's draft check mark is still right. Amend D16 at F5's last stage |
| **F7:** a permanent place for a year's work | `<class cloud folder>/assignments/<task>/`, chosen once, and later a view of a student's work over time | **No new student ID is needed:** a school email and its number stay the same throughout a student's time at the school (upgrade plan, Q7). Classes are separate for each year today, and exam results are stored by exam name alone, so those need solving first |
| **F8:** compact and delete on CAM2's start screen | Nothing to read: compacting leaves `cam2_session.json` and `grades.json` alone, so Sync won't re-read the session, and name crops stay for Window 2 | Deleting an exam in CAM moves it to `exams/_deleted/` (`exam_bridge.py:376`), which doesn't free space, so CAM may need a way to show or empty that folder |

F9 to F15 are optional ideas from research, and nothing in them needs CAM to change. If F14 is taken up, comparing exams over time still belongs in CAM.

## The second pull

- **Another session version.** F1 and F2 add to the session file and raise its version, so I4 happens again: opening a session upgrades it for good, and a computer on an older CAM reads `file_from_newer_version`. The release notes will need to say again to update every computer first.
- **Same method.** Change CAM2, tag it, and `git subtree pull`. Never edit `exam_grading/` in place.
- **Bridge tests.** Add the F2 note fields to `test_exam_bridge.py` with that pull.
