# Phase 4 browser checks (CAM2 engine upgrade)

How to run the browser checks from `docs/CAM2_ENGINE_UPGRADE_PLAN.md`, Phase 4, on a
computer of your own. They passed on the Mac and on the Windows Surface on 2026-11-06.
Development only: `tools/` never goes into the bundle.

**Read `CLAUDE.md` first.** Every step runs in a sandbox. Never launch CAM in the real
checkout, whose `local_device_prefs.json` points at real data, and never touch the real
database.

## For Claude Code on that computer

1. **Update the repos.** In the CAM checkout, run `git status` (keep any local changes),
   then `git fetch` and `git switch cam2-upgrade-phase4 && git pull --ff-only`. If PR #8 is
   already merged, use `main`. In the CAM2 checkout, `git fetch --tags`.
2. **Run the phase check** from `~/.claude/CLAUDE.md` on Phases 0 to 3 and Phase 4 so far,
   and report back before running anything.
3. **Run the tests in a sandbox,** as the plan's "Testing safely" section says. Without
   Node: CAM 487 with 5 skipped, CAM2 354 with 1 skipped (the Surface has no Node either).
   With Node, the skip count drops.
4. **Start the sandboxed CAM.** Add this to `.claude/launch.json` (don't commit it):

   ```json
   {
     "name": "cam-sandbox",
     "runtimeExecutable": "powershell",
     "runtimeArgs": ["-ExecutionPolicy", "Bypass", "-File", "tools\\browser_check\\start_sandbox.ps1"],
     "port": 8611
   }
   ```

   On a Mac, use `"runtimeExecutable": "zsh"` and `["tools/browser_check/start_sandbox.sh"]`.
   Then open it in the in-app browser with `preview_start`.

   **`start_sandbox.ps1` ran on the Windows Surface on 2026-11-06,** after one fix: it now
   writes the sandbox prefs without a byte-order mark, which CAM can't read. Still check its
   first output line and the sandbox prefs it writes before clicking anything.

   The script copies only tracked files to `%TEMP%\cam-browser-sb`, and makes a venv there
   with exactly `tools/bundle-requirements-windows.txt`. Making that venv is itself a check
   that the Windows pins install. It sets every data path into the sandbox, and writes the
   addresses that CAM, CAM2 and the workspace would open to `opened-urls.txt` instead of
   opening the normal browser.
5. **Confirm the isolation before clicking anything.** The log's first line says
   `sandbox DB: …\cam-browser-sb\data\acm_database.json`. Note the real database's
   last-modified time, and compare it again at the end.
6. **Make the fixtures** with the sandbox's Python (`<sb>` is the sandbox folder):

   ```
   <sb>\venv\Scripts\python tools\browser_check\make_fixtures.py sessions <sb>\repo\exam_grading "<sb>\data\Class 1\exams"
   git -C <CAM2 checkout> archive 1a40845 -o <sb>\cam2-old.zip   (then extract it to <sb>\cam2-old)
   <sb>\venv\Scripts\python tools\browser_check\make_fixtures.py sessions <sb>\cam2-old "<sb>\data\Class 1\exams" v1start
   <sb>\venv\Scripts\python tools\browser_check\make_fixtures.py slides <sb>\scans\slide-deck
   <sb>\venv\Scripts\python tools\browser_check\make_fixtures.py draft <sb>\scans\master
   ```

   Run them with `CAM2_APP_DATA` set to `<sb>\cam2data`, and `HOME` and `USERPROFILE` set
   to `<sb>\home`.
7. **Hash the sessions** (`hash_sessions.py`) before and after every Sync, and compare.
8. **Work through the checks below,** then write the results into the plan's Phase 4
   progress note, as the Mac's are, and push them to the branch.
9. **Clean up:** stop the servers, remove the `launch.json` entry, and confirm the real
   database's time is unchanged.

**Using the in-app browser:** set the viewport to 1600×1000. Window 1 scrolls inside its own
frame. Streamlit dropdowns: click, type the option, press Return. Element references go
stale after every rerun, so look them up again. Streamlit download buttons: catch the link
(patch `HTMLAnchorElement.prototype.click` to record `href`), then fetch it into the
sandbox with `curl`, so nothing lands in the real Downloads folder.

## The checks and what to expect

The fixtures are fictional "Class 1" students. Numbers are from the Mac run.

| Case | Do | Expect |
|---|---|---|
| All nine sessions | Wait for Sync (or Settings → Force full re-scan) | Window 1 lists them all; session hashes unchanged |
| Window 2 | Open any student's ⚠ list | Each exam "awaiting decision", never a 0 |
| Quiz 1 marks | Grades and Analysis | Alex 7, Sam 10 with "report shows 12/14 (typed in CAM2)", Jordan 9, Priya 14, Liam 6, Mia 11, Noah 5, Emma "not finished" |
| | Grade Alex 4 and Sam 6, Apply | "Graded 2 student(s)… 1 paper(s) not finished in CAM2 skipped" |
| Choice open | Grades and Analysis | Mia, Noah and Emma "not finished"; Sam 7/12 with Q3 not counted |
| Weighted final | Grades and Analysis | Alex 38.8% weighted; Jordan 56.3% with "report shows 80.0% (typed in CAM2)"; Sam 47.5% |
| Unit test rubric | Grades and Analysis, Apply | "Apply will fill 8 empty grade(s)", then 4 of 8 decided on A and on C; Sam A 6, C 5 |
| | Window 3 for Sam | "CAM2 final level: 6. Not in the gradebook yet. Apply it in Grades and Analysis in Window 1, or choose here." before Apply |
| Essay one criterion | Window 3, Sam: choose 5 | "Your decision." and B: 5 in the marks table |
| Lab practical | Window 3, Sam | A 9/20 (45.0%) and D 9/20; choose A 4 |
| Mixed (both) | Window 3, Sam | Q2 level 4; total 7/15 under "Every question and comment" for both |
| Term comment | Window 3, Sam: Compile prompt to clipboard | Exam comments listed with no scores (Quiz overall, Unit test overall and Q3) |
| V1 upgraded | Before `v1start`'s finish | Every student "⏳ Awaiting your decision", no suggested level |
| | Run `sessions … v1finish` with the new CAM2, wait for Sync | "1 updated"; Alex's typed level 6 only; no grades written; hashes unchanged |
| Slide deck | Add an Exam "Slide deck project", 🛠 Exam setup / Grade, open the logged address | CAM2 in host mode; paste `<sb>\scans\slide-deck` as one file per student; "Slide 16:9 found"; boxes, slice (24 pictures), names matched from CAM's class list; grade; type a "Total on report" for Emma; Send to CAM |
| | Back in CAM | Totals as graded; Emma "report shows …/20 (typed in CAM2)"; hashes unchanged except `cam2.lock` |
| Report-card pack | Build it, fetch the file | Decided exam grades, other exams "awaiting decision". Only decided criteria are listed for a partly decided exam (correct, the teacher's decision) |
| Workspace drafts | Settings → Add / Edit class: master directory `<sb>\scans\master`; make "Poster draft" a Draft (⋯ menu), 🖌 Grade this Assignment, open the logged address | 4 students; type comments; link 100001 and 100002 **with the mouse** (link icon, then the partner card): ticks and comments combine under one line; Export CSV; CAM shows the feedback in Window 3 |
| Draft restore | Rename the class folder's `grading_cache.json` and `grades_local-*.json`, reopen from CAM | Every comment and tick comes back from CAM's `cam_grades_*.json`; a second export duplicates nothing. The partner link doesn't come back (known) |

**On Windows also check:** the 📁 Browse buttons open a folder dialog. Choose only folders
inside the sandbox.

**Known and not to report again:** CAM2's level buttons move after a click (fixed in the
next CAM2 update); CAM2's
thumbnails show slides in portrait cards.
