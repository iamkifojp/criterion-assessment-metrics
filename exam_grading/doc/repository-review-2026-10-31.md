# Standalone Binary Release Readiness Review

Date: 2026-10-31

Reviewed commit: `c33b965`

Scope: Windows and macOS standalone release readiness, following `AGENTS.md`.

This review records four concrete bugs. Proposed fixes below have not been applied.

**Status (2026-10-31): all four are fixed**, with tests. See the CHANGELOG entry
*Release-readiness fixes*. Two fixes differ from the proposals:

- **#1:** the packaged app starts itself with `--pick` (handled in `launcher.py`)
  rather than always using PowerShell, so the modern Windows dialog is kept.
  The same work found that the picker child wrote its answer in the ANSI code
  page, garbling non-English folder names. That is fixed too.
- **#2:** replacement is refused once any paper has a grade *or a comment*
  (`workflow.class_has_work`), since comments would move as well. The Step 1
  button is disabled with an explanation.
Verification used source inspection and in-memory checks with filesystem operations
mocked where needed. No frozen Windows or macOS binary was built or executed.

## 1. [P1] Frozen Windows executable cannot open file/folder pickers

**Category:** Binary bundling failure.

**File + Line:** `engine/pickers.py:93`

**Concrete Failure Scenario:** In a frozen build, `sys.executable` points to
`CAM2.exe`. Selecting a PDF launches `CAM2.exe -m engine.pickers ...`, but the
launcher accepts no `-m` argument. The child exits and the picker returns `None`,
preventing scan selection. The mocked subprocess check confirmed the generated
command and the `None` result for a child argument-parser failure.

**Minimal Fix:** In `_pick()`'s Windows branch, call the existing PowerShell picker
directly instead of `_pick_windows_child()`:

```python
return _pick_powershell(mode, title, initial)
```

## 2. [P1] Replacing scans transfers existing grades to different students

**Category:** Data integrity.

**File + Line:** `app.py:308`

**Concrete Failure Scenario:** Grade Alice's paper, then use **Replace the scans**
with a differently ordered batch. Import restarts student IDs at `s001` while
retaining `state.grades`. Bob's new `s001` paper consequently receives Alice's
grades in exported reports. An in-memory reproduction retained Alice's total of
9 for Bob after replacement.

**Minimal Fix:** Block replacement after grading has started, before calling
`start_import()` in `scans_replace()`:

```python
if grading_summary.has_grades(state.grades):
    raise UserError("pages_locked_graded",
                    name=state.config["exam_name"])
```

## 3. [P1] Editing an ungraded paper can alter a neighbouring rubric-graded paper

**Category:** Data integrity.

**File + Line:** `engine/workflow.py:310`

**Concrete Failure Scenario:** In a combined scan, grade the second student using
rubric levels without comments. On the first, ungraded student, remove a page or
move its last page later. The operation redistributes pages across students. The
server checks only `value` and `comment`; rubric grades live in `levels`, so it
permits changes to the second student's paper while retaining its original
grades. The browser only locks the currently selected student. An in-memory
check confirmed that `_has_work()` returns `False` for a rubric grade of 6 and
that `_refuse_if_graded()` allows the graded student through.

**Minimal Fix:** Include rubric levels in `_has_work()`:

```python
return any(
    isinstance(e, dict) and (
        e.get("value") is not None
        or str(e.get("comment") or "").strip()
        or any(v is not None for v in (e.get("levels") or {}).values())
    )
    for e in per.values()
)
```

## 4. [P1] A newly added question inherits a deleted question's grades

**Category:** Data integrity.

**File + Line:** `static/js/boxes.js:92`

**Concrete Failure Scenario:** Grade `q1`, delete it while retaining another
question, then add a new question. `addQuestion()` reuses the first unused ID,
`q1`. Deleted questions' grades remain stored, so the new answer box receives
the old question's scores and comments in reports. An in-memory reproduction
using the backend's equivalent ID allocation assigned the new question the
deleted question's score of 9.

**Minimal Fix:** In `addQuestion()`, reserve IDs present in saved grades as well
as current questions:

```javascript
const used = new Set([
  ...d.questions.map((q) => q.id),
  ...Object.values(app.session.grades?.grades || {})
    .flatMap((entries) => Object.keys(entries || {})),
]);
```
