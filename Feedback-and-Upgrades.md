# CAM2 Feedback and Upgrades

What colleagues have asked for, optional ideas from research, what each would take, and what was decided. Read this when planning a new version. Once something is agreed for a version, its design moves to [PLAN.md](PLAN.md), and what shipped goes in [CHANGELOG.md](CHANGELOG.md).

**Suggesters stay anonymous: entries give a subject or role, never a name.**

**Nothing here is being built yet, and no new build is planned until the new CAM2 release is ready.** The exception is the limits on comment length from [F2](#f2-notes-drawn-on-the-answer-image), which are agreed for that release. More feedback is still to come (2026-11-05).

## Requests

| # | Request | From | Size | Status |
|---|---|---|---|---|
| [F1](#f1-highest-level-for-a-question-or-section) | Highest level for a question or section, for banded papers | Several colleagues | Small | Proposed |
| [F2](#f2-notes-drawn-on-the-answer-image) | Notes drawn on the answer image | Biology colleague | Medium | Proposed; main design choices agreed |
| [F3](#f3-one-comment-list-across-cam2-and-cam) | One comment list across CAM2 and CAM's grading workspace, with stamps in both | Project lead | Medium, mostly in CAM | On hold; F5 would replace it |
| [F4](#f4-bug-ticking-in-cam-wipes-typed-comments) | Bug: ticking in CAM wipes typed comments | Project lead | Small | To fix with the new CAM2 release |
| [F5](#f5-move-drafts-and-assignments-into-cam2-and-retire-the-workspace) | Move drafts and assignments into CAM2, and retire CAM's grading workspace | Project lead | Large, in stages | Direction agreed; not being built yet |
| [F6](#f6-exam-comments-should-carry-weight-in-cams-term-comments) | Exam comments should carry weight in CAM's term comments | Project lead | Small, in CAM | Gap confirmed; to plan |
| [F7](#f7-a-permanent-place-for-a-years-work) | A permanent place for a year's work | Project lead | Medium | Direction agreed; not being built yet |
| [F8](#f8-compact-and-delete-finished-sessions) | Compact and delete finished sessions on CAM2's start screen | Project lead | Small to medium | Proposed; not being built yet |
| [F9](#f9-grading-from-the-keyboard) | Grading from the keyboard | Research | Small | Optional; recommended |
| [F10](#f10-the-spread-of-grades-while-grading) | The spread of grades while grading, and clicking a band to review it | Research | Small to medium | Optional; recommended |
| [F11](#f11-gallery-of-one-question) | Gallery of one question across the class | Research | Small to medium | Optional; recommended |
| [F12](#f12-calibration-mode) | Calibration mode: trial changes, comparison and audit | Research | Large | Optional; recommended only in part |
| [F13](#f13-straightening-crooked-scans) | Straightening crooked scans | Research | Medium | Optional; check the need first |
| [F14](#f14-class-analysis) | Class analysis and exports | Research | Small to medium | Optional; recommended only in part |
| [F15](#f15-rubric-points-that-update-totals) | Rubric points that update totals everywhere | Research | Large | Optional; mostly works already |

**Size** is a rough guess at the work, including tests and the English and Japanese text. Small is about half a day (around 100 lines). Medium is a few days (around 500 lines), plus time for a teacher to try it.

**Status** is one of: Proposed, Optional (an idea to consider, which nobody has asked for yet), Agreed for a version, Done, or Not doing (with the reason).

### Checking a new request

Before agreeing to anything, check it against what CAM2 is:

- It grades one exam at a time, so nothing should span classes, assignments or the school year.
- Few options. Prefer something the app can work out for itself over a new setting, and hide what doesn't apply.
- Marks stay the simplest path. A marks exam never needs criteria, rubrics or final levels.
- It works offline, with no accounts and no services.

### Adding an entry

Copy this under [Details](#details), and add a row to the table above.

```markdown
### F3: Short name

**From:** subject or role, date. **Size:** ... **Status:** Proposed

**What they asked:** in their terms, with the example they gave.

**What it means:** the actual need, if it differs from the words.

**Proposal:** what the teacher would see, and what would change.

**Still to decide:** anything that needs a person's answer.
```

## Details

### F1: Highest level for a question or section

**From:** several colleagues, 2026-11-05. **Size:** Small. **Status:** Proposed

**What they asked:** many papers are banded or tiered. Section 1 targets Criterion A levels 1–2, section 2 targets 3–4, and so on. This already works in CAM2, but nothing stops a teacher giving a level above what the question could earn.

**What it means:** this is a ceiling, not a restriction to one band. A question targeted at 5–6 can still earn 0–4, because a student may fall short, but it can never earn 7–8. So one number is enough, the highest level allowed, and there is no lowest level to set.

**Proposal:**

- **Set-up (Step 2 question table):** each ticked criterion gets a small choice beside its tick: *All levels*, *up to 2*, *up to 4*, *up to 6*. The choices come from the tops of that rubric's bands, so they follow the MYP pairs without any special rule. The default is *All levels*, so nothing changes for anyone who doesn't use it.
- **A section shortcut:** on a paper with sections, the same choice on the section's heading row fills in all its questions. This saves setting it 20 times, while a single question can still differ.
- **Grading (Step 4):** bands above the ceiling aren't shown, so a 5–6 question shows the 0, 1–2, 3–4 and 5–6 cards. A short line on the card says *Up to 5–6*.
- **Saving:** a level above the ceiling is refused when saved, so a wrong grade can't get in from anywhere.
- **Changing it later:** a ceiling can't go below a level already given. This is the same rule as lowering a question's marks below its highest mark (`question_max_below_grade`).

**Why it is small:** CAM2 reports levels as given (`B5`) and never averages them, so no calculation changes. Reports stay as they are, and the final level stays the teacher's own for the whole paper.

**What changes:**

| Where | Change |
|---|---|
| `engine/workflow.py` `set_questions` | Keep `level_caps: {"r1": 6}` on the question, one per criterion. Check it against grades already given |
| `engine/grading_summary.py` `set_grade` | Refuse a level above the ceiling |
| `static/js/step2.js` `questionTable` | The choice beside each tick, and the section shortcut |
| `static/js/step4.js` `gradeCard` | Leave out bands above the ceiling |
| `engine/gradebook_xlsx.py` | Optional: show the ceiling on the reference sheet |
| `engine/model.py` | Bump the session version, so an older CAM2 can't open the session and lose the ceilings |

**Still to decide:**

1. Keep the Step 4 badge on the criterion's scale? Recommended yes: `6 / 8 · 5–6`, not `6 / 6`, because the level is still a level out of 8.
2. Should the student's report say a question was capped, for example `Q3 (up to 5–6)`? Recommended not until someone asks.

### F2: Notes drawn on the answer image

**From:** biology colleague, 2026-11-05. **Size:** Medium. **Status:** Proposed; main design choices agreed

**What they asked:** to mark up the student's answer image with comments, as in the Kami app. Kami also has OCR, which is out of scope. They mainly want to highlight a line in the answer.

**What can be drawn:** none of these need OCR, because they sit on the image by position. Only selecting or searching the student's text would.

| Overlay | Extra work | Worth it? |
|---|---|---|
| **Comment stamp** (a distinctive numbered icon at one spot) | Medium; this builds the layer everything else uses | **Yes, first.** It points at part of a diagram, which is the biology need, and uses the comment list |
| **Highlight** (see-through box, in a few colours) | Small, once the stamp layer exists; needs its own drawing mode | **Yes, first.** It marks a line of the answer, and teachers can use it without any comment |
| Box with a comment attached to it | Medium | No. A highlight with a stamp dropped beside it does the same job, with no link to manage |
| Tick and cross stamps | Small, once stamps exist | Yes, if asked; handy for labelled diagrams |
| Arrow | Small | Later |
| Text typed directly on the image | Medium; it needs moving and resizing, and covers the writing | Probably not |
| Freehand pen | Medium; needs undo, and is hard to use with a mouse | Only with a stylus user asking |
| OCR, or selecting handwritten text | Very large | No |

**Proposal: numbered notes dragged from the comment list, with their text listed under the answer.** Numbering the notes is agreed.

1. **Drag a quick comment onto the answer in Step 4.** A distinctive numbered stamp lands at that spot, and the comment joins this answer's numbered list.
2. **Edit a note in the numbered list.** Its text is a copy, so changing it affects this student only, not the comment list.
3. **Drag a stamp to move it, or remove its note from the list.** Notes are numbered in the order they were placed, and removing one renumbers the rest.
4. **On the report** the stamp prints with its number, and the notes print under the answer, after the teacher's comment:

```
 Q3  ┌───────────────────────────────┐   B5
     │  student's diagram            │
     │          ①                    │
     │                               │
     │                     ②         │
     └───────────────────────────────┘
     Comment: Good use of terms. Check your scale.
     ① Label the cell membrane, not the cell wall.
     ② Units missing.
```

**Why not float the comment beside its spot on the PDF?** The answer image there is at most about 390 points wide, between the question label and the grade. Text at a readable size would cover the student's writing or run off the image, and every note would need its own placement. Numbers avoid all of that.

**Merging with the existing comment: keep them separate (agreed).** Mixed together, they could confuse, would be hard to format, and would be harder for students to read. The comment is also one free-text field, and CAM2 already rewrites its first line for ticked quick comments, so lines for notes mixed into that text would be hard to keep right when a note is removed or the comment is edited. Notes get their own list, and they appear together only where they are read:

- on the report, as above;
- in the gradebook, added to that question's comment cell;
- in the review table, where a note counts as a comment for the "has a comment" marker.

#### Highlights

Highlights and comment stamps are two separate tools, because teachers will use them separately. Neither depends on the other.

- **Drawing:** a **Highlight** button in Step 4 turns on drawing, because dragging on the answer otherwise moves it around when zoomed. Pick a colour and drag over the line. Several lines take several highlights.
- **Colours:** a few see-through colours with no fixed meaning. Suggested: yellow, blue and pink, which stay easier to tell apart for colour-blind readers than green and pink.
- **No numbers or text:** a highlight doesn't appear in the numbered list. To comment on a highlighted line, the teacher drops a stamp beside it.
- **Removing:** click a highlight while the tool is on.
- **On the report:** drawn over the answer image with the same colour and transparency. It still shows as a grey band if the report is printed in black and white.

#### The quick comment list

**Notes draw on the comment list (agreed).** Otherwise the list becomes even more superfluous. The list changes from tick boxes to drag and drop only.

- **It starts short and teachers grow it.** It starts with 4 comments, so teachers are encouraged to write their own. They can add and remove comments right there in Step 4, up to 8.
- **Added comments stay for the whole exam.** The list already works this way, so a comment added on Q2 is there for Q3. A new exam starts again from the 4.
- **Changing the list doesn't change notes already placed,** because each note holds its own copy of the text.
- **Tick boxes go.** One list with one meaning is simpler, and drag and drop no longer has to share the pills with ticking. Comments already written by ticks stay in saved sessions as ordinary comment text.
- **Strengths and Areas to develop stay, as the stamp's colour (recommended, see [F3](#f3-one-comment-list-across-cam2-and-cam)).** The generated line goes, but CAM's list has the same two types, so keeping them means one list in both apps. A strength's stamp could be green, and an area to develop's amber.
- **The default comments need rewriting.** They are fragments written to fit "Areas to develop: …" (`illegible handwriting`), and they would now stand alone as notes. All five are also critical. A suggested 4, in English and Japanese: *Well explained.* as a strength, and *More explanation needed.*, *Incomplete answer.* and *Hard to read.* as areas to develop.

**What dropping the tick boxes costs:**

- Dragging is slower than ticking, and it adds up over a whole class. It is worth trying on a school laptop's trackpad, especially when zoomed in.
- A note always has a stamp on the image, even when the comment is about the whole answer. The teacher just drops it anywhere on the answer.

**Limits:**

| What | Limit | Why |
|---|---|---|
| Comments the list starts with | 4 | Encourages teachers to write their own |
| Comments in the list | 8 | Stays short enough to scan while grading |
| Notes on one answer | 8 | Keeps feedback readable. This needs its own check (see below) |
| One list comment or note | 120 characters, about 20 words (agreed) | Room for one clear point, and no essays. It is about two lines on the report in English and about three in Japanese |
| The question's comment | 300 characters, about 50 words | Room for a few sentences, not an essay |
| The overall comment | 600 characters, about 100 words | The one place for a longer message, and still reasonable to write for a whole class |

**The question and overall comment limits are agreed and come first (2026-11-05).** They're built for the next CAM2 release, ahead of the rest of F2, and don't change the session's format (CAM's upgrade plan, Phase 1 and Q8). The design is in [PLAN.md](PLAN.md). The other limits come with notes.

Three examples, with their length in characters:

- *Label the cell membrane, not the cell wall.* (43)
- *Your graph needs a title, labelled axes with units, and a line of best fit.* (75)
- *Your conclusion should refer back to the hypothesis and use your data as evidence for why it was or wasn't supported.* (117)

Details of the limits:

- **The limit of 8 per answer isn't automatic.** A list of 8 doesn't guarantee it, because the same comment can be dragged twice and the list can change between drags. So CAM2 checks it directly and refuses a ninth, with a short message. The same comment may be used twice on one answer, since *Units missing.* can apply in two places.
- **Limits apply to new typing only.** A longer comment in a saved session is never cut, and neither is a list longer than 8. It just can't grow until it is back under the limit. A character counter shows near the limit, because a browser's length limit silently trims pasted text.
- **Counted in characters,** because Japanese has no spaces between words.
- **Where 120 comes from:** it was chosen to fit the report, not from research into ideal comment length.
- **Worst case for one answer:** 8 notes of 120 characters take about a quarter of an A4 page on the report. This is an estimate from the report's 10pt text, not a test print.

**How it would work:**

- **Stored** in `grades.json`, on that student's answer next to the comment: `annotations: [{"page", "x", "y", "text"}]` and `highlights: [{"page", "x", "y", "w", "h", "colour"}]`. They are shared across a question's criteria, as the comment is.
- **Positions are fractions of the scanned page (0–1), not pixels or crop positions.** That makes them independent of zoom, screen DPI and the report's image resizing, on Windows and Mac alike. One engine function turns a page position into a position on the current crop, for both the screen and the report. It has to allow for the way a question with several boxes stacks them with a divider line.
- **Dragging uses pointer events, not the browser's built-in drag and drop.** The built-in kind generally doesn't work on touchscreens or with a stylus. Step 4's pan and `boxes.js` already use pointer events.
- **The crop files are never changed.** The stamps are drawn over the image on screen and in the PDF, so the existing rule holds and the PDF stamps stay sharp.

**When a box is adjusted:** the notes follow the student's writing, because their page positions don't change. **✎ Adjust this box** needs no conversion, and nothing is removed.

- **Still inside the new crop:** the note stays on exactly the same writing.
- **Now outside the crop:** it shows at the nearest place inside. On a question with several boxes, that means the nearest box on the same page. If no box is on that page any more, it goes to the top of the crop.
- **Moved notes are flagged:** a moved note no longer points at what it marked, so Step 4 marks it to check, and **✎ Adjust this box** says how many moved. Dragging it into place, or clicking to confirm, clears the flag.
- **Only what is shown moves:** the saved position stays as drawn, so widening the box again puts a note back where it was. Dragging a note saves its new position.
- **Highlights** work the same way, and are cut to fit the new crop.

**What changes:**

| Where | Change |
|---|---|
| `static/js/step4.js` `viewer`, `gradeCard` | A layer over the image that follows zoom, dragging from the list onto the answer, and moving stamps without panning the answer (`attachZoomAndPan`). The numbered list, and adding and removing list comments in place. The card is 400px wide and already long, so it needs a look with 8 comments and 8 notes on it. List comments may need clipping to a line or two |
| `engine/keywords.py`, `app.py`, `static/js/step4.js` `editKeywords` | Remove ticking, the generated line and the two types. Set the limits and the new defaults in `i18n/en.json` and `i18n/ja.json` |
| `engine/grading_summary.py`, `app.py` | Save, edit and remove notes, with the limit of 8 per answer |
| `engine/reports.py` `_question_with_image`, `_question_notes` | Draw the numbered stamps and print the list. With images off for a section, print the note text alone |
| `engine/gradebook_xlsx.py`, `static/js/step5.js` | The comment cell and the review table marker |
| `engine/model.py` `grades_mass`, `engine/workflow.py` `_has_work` | Count notes and highlights as teacher work, so the wipe guard protects them and page fixes don't move pages under them |
| CAM `engine/exam_bridge.py` (in CAM's repo) | CAM reads each question's `comment` and the overall comment from CAM2, so notes won't reach CAM's records or its reports unless this also reads them |
| `engine/slicer.py` | Turn a page position into a crop position and back, keeping it inside the crop (about 50 lines plus tests, using the same grid math as `range_to_bbox` and `stitch_vertical`) |

**Still to decide:**

1. **Whole page view.** Recommended: notes only on the answer view in the first version, because that is the image the report prints, so the list can't be dragged from while the whole page is showing. Page positions make it easy to show them there later.
2. **Try it with the biology colleague before building the extras.** Ask whether they would use tick and cross stamps.

### F3: One comment list across CAM2 and CAM

**From:** project lead, 2026-11-05. **Size:** Medium, mostly in CAM. **Status:** On hold. If [F5](#f5-move-drafts-and-assignments-into-cam2-and-retire-the-workspace) is agreed, this work isn't needed, because the workspace's list goes with it and stamps are built only in CAM2.

**What was asked:** CAM's assignment grading (`cam_grading_workspace/`) has its own Strengths and Areas to develop list. CAM2 is vendored inside CAM at `exam_grading/`, so a teacher using CAM meets both. Having two comment systems in one app is too many.

Stamps are also wanted in CAM, for grading drafts of art portfolios, where marking a spot on an image is very useful. There are no boxes in art evaluation, because overlapping square boxes are hard to read. CAM doesn't need numbers, but everything stamped must be collated for the final comment the LLM generates.

**How they compare today:** they are already close.

| | CAM2 Step 4 | CAM grading workspace |
|---|---|---|
| The list | Editable, per exam | Editable, per assignment folder |
| Types | Strength, growth | Positive, growth |
| Ticking | Writes `Strengths: …` and `Areas to develop: …` | Writes the same two lines |
| Text the teacher typed | **Kept** below the generated line | **Lost** when a tick changes ([F4](#f4-bug-ticking-in-cam-wipes-typed-comments)) |
| Starts with | 5 general comments, all areas to develop | 10 art comments: 7 strengths and 3 areas to develop |
| Where it is used | Beside one answer image | A row per student, next to a work gallery that can hold several files |

**Proposal: one comment list and one stamp in both apps, differing only where their jobs differ.** The list, the two types, the 120-character limit, the wording and the stamp's look are shared.

| | CAM2 | CAM workspace |
|---|---|---|
| Comment stamps | Yes, on the answer image | Yes, on images and PDFs |
| Highlights | Yes, as a separate tool | No |
| Numbers on stamps | Yes, to match the list on the report | No. Pointing at a stamp shows its text |
| Tick boxes | No | Yes, for general comments and for work that can't be stamped |
| Where the text goes | The numbered list on the student's report | The final comment the LLM generates |

**How a stamp works in CAM (recommended): stamping a comment also ticks it.** A stamp is a tick plus a place on the image.

- **Collating comes almost for free.** A ticked comment is already written into the generated comment, and that already travels through the CSV into CAM and on to the LLM. Nothing needs numbering.
- **It has to be in the comment.** The LLM prompt uses a record's keywords only when its comment is empty (`as_text` in `engine/aggregation.py`, `draft_lines` in `app.py`). So a stamp kept apart from the comment could be dropped silently. This also makes [F4](#f4-bug-ticking-in-cam-wipes-typed-comments) essential, or every stamp would wipe the typed comment.
- **One comment stamped several times reaches the LLM once.** Removing its last stamp unticks it. Unticking it removes its stamps.
- **Stored** per student in the workspace's saved data: `stamps: [{"label", "file_id", "page", "x", "y"}]`, with positions as fractions of the image or page.

**What can be stamped in CAM:**

- **Images and PDFs** can, because CAM draws them itself. Images need a new larger view for stamping, because today's zoom overlay ignores the mouse.
- **Slides, Docs and Word files** can't, because they show inside Google's preview frame. **Videos** can't either. These use ticks.

**What changes in CAM:**

| Where | Change |
|---|---|
| `cam_grading_workspace/app.py` page script | The stamping view, dragging from the list, showing stamps over images and PDFs, and the shared wording and limits |
| `cam_grading_workspace/static/pdf_viewer.js` | Stamps on PDF pages |
| `cam_grading_workspace/app.py` saving | Save stamps, share them between linked partners, and follow renamed comments (`remapKeywordLabel`) |

The list rules could live in CAM2's `engine/keywords.py`, for CAM's workspace to use from the vendored copy. Whether it can import them there still needs checking. The types are stored as `strength` in CAM2 and `positive` in CAM, so one name has to be chosen.

**Things to know:**

- **CAM isn't affected by CAM2 dropping ticks.** It doesn't read CAM2's `keywords`, only each question's `comment`. Notes do need adding to what it reads (see F2).
- **Changes reach CAM through `git subtree pull`,** never by editing `exam_grading/` in place. CAM is pinned to an older CAM2 commit, and its upgrade plan (`docs/CAM2_ENGINE_UPGRADE_PLAN.md`) has to cover any new session version.
- **CAM's reports don't depend on the type labels.** They choose evidence by score, and they strip the `Strengths:` and `Areas to develop:` labels from comments.

**Still to decide:**

1. **Do students need to see the stamped images?** I found no per-student PDF of submitted work in the workspace; it exports a CSV. If stamps are for the teacher's marking and the LLM, the size above holds. If students should see them, CAM also needs a way to produce the stamped images, which is a larger job.
2. Should CAM's list also start at 4 and stop at 8? Its defaults are art-specific, and existing folders must keep their lists.

### F4: Bug: ticking in CAM wipes typed comments

**From:** project lead, 2026-11-05. **Size:** Small. **Status:** To fix with the new CAM2 release

**What happens:** in CAM's grading workspace, changing a tick replaces the whole comment with the generated lines, so anything typed is lost. The project lead has hit this too. It is meant to keep the teacher's text.

**Workaround for now:** tick the comments first, then type the custom comment. Set the deadline before writing any comments.

**Cause:** `st.comment = autoComment(st)` in `cam_grading_workspace/app.py` rebuilds the comment from the ticks alone. The Late checkbox does the same. So does changing the deadline, for every student in the task; this comes from reading the code and hasn't been run.

**Fix:** remember the line last generated and replace only that, as CAM2 does with `keyword_text` in `engine/keywords.py`. Saved comments have no remembered line, so the first change on one needs care not to lose or repeat its text.

**Why it matters:** teachers lose typed comments for as long as the workspace is in use, even if [F5](#f5-move-drafts-and-assignments-into-cam2-and-retire-the-workspace) retires it later. Under F3, stamping would also tick a comment, so this would have to be fixed first.

### F5: Move drafts and assignments into CAM2, and retire the workspace

**From:** project lead, 2026-11-05. **Size:** Large, in stages. **Status:** Direction agreed; not being built yet

**Why:**

- **Google access:** the workspace was designed around Drive access through Google's API, and most schools won't allow the OAuth set-up that needs. Work now has to be downloaded anyway.
- **Images:** CAM's output is an Excel file whose comments are pasted back into Google Classroom. It was never meant to output images, and CAM2 already does.
- **Maintenance:** the workspace is the hardest engine in CAM to look after, and retiring it leaves one grading engine.

**Proposal: retire it in stages, keeping the workspace running until CAM2 has proved it can take over.**

| Stage | What happens | Size |
|---|---|---|
| 0. Now | Grade from downloaded folders in the workspace, which can already open a local folder with a subfolder per student. Fix [F4](#f4-bug-ticking-in-cam-wipes-typed-comments). Build nothing else in it | Small |
| 1. Finish first | The new CAM2 release and CAM's upgrade plan, as already planned (`docs/CAM2_ENGINE_UPGRADE_PLAN.md`). Its slide-shaped pages help here | Already planned |
| 2. Whole submissions in CAM2 | A paper with no boxes: the whole submission is graded as one item, page by page, with stamps and highlights from [F2](#f2-notes-drawn-on-the-answer-image) | Medium, on top of F2 |
| 3. Drafts | Comments with no grade, and results sent to CAM. Try one real draft in both apps and compare | Small to medium |
| 4. Normal assignments | One grade per criterion, using CAM2's rubric levels. Try one real assignment the same way | Small to medium |
| 5. Retire | Remove the workspace, OAuth and the Drive code from CAM. Marks and comments already stored in CAM stay | Medium |

**Why drafts go first:** they have no grades, so a mistake can't touch a student's marks.

**Sending results to CAM: write the same CSV the workspace writes (recommended, still to check).** For anything that isn't an exam, CAM2 would export a CSV in the workspace's format. CAM's sync, the Classroom Entry tab and the LLM would then work as they do today, so the paste-into-Classroom routine doesn't change. The other route is much bigger, because of how CAM treats CAM2 sessions today:

- It files every CAM2 session as an exam (`_ingest_cam2_session` sets `is_exam`).
- The Classroom Entry tab leaves exams out.
- The LLM reads draft comments from `draft_feedback`, which CAM2 sessions don't fill.

**What this settles:**

- **Stamps for art drafts** are built once, in CAM2. Highlights are a separate tool, so nobody has to draw a box on art.
- **Students can see stamped images** if the teacher wants, through CAM2's student PDFs. Pasting comments into Classroom stays the main route.
- **The LLM gets everything:** the CSV's comment column holds the typed comment and every note's text, without numbers.
- **The Google-free rule holds:** CAM2 never touches Google, as already decided (D17 in CAM's upgrade plan). The teacher's Apps Script or a plain download supplies the files.

**What CAM2 would need to learn:**

- **Papers of any length.** It warns when page counts differ, and it would stop doing that for whole submissions.
- **Several files per student,** in a mix of PDFs and images of different sizes, joined into one paper. It can already match one file per student by the name in the file name.
- **A question with no marks or criteria,** which it refuses today, for comments-only drafts.
- **A report layout for whole pages.** Answer images are limited to about 330 points high today.
- **No new choice for teachers using it on its own, at least at first.** CAM tells CAM2 when a task is a whole submission, so the standalone start screen stays as it is, and an exam works as it does now.

**What the workspace does that CAM2 doesn't, so each needs a decision before Stage 5:**

| Workspace feature | Suggested answer |
|---|---|
| Videos | **Decided:** teachers watch them online, outside CAM and CAM2. Any in-app route would need an API that schools won't allow. The teacher sets up an assignment with no files in CAM and enters the grade and comment in Window 3, which CAM already allows. CAM2 gets no empty submissions, which would confuse teachers using it on its own |
| Slides, Docs and Word previews | **Decided:** the teacher's Google Script turns them into PDFs first, so it needs to cover Docs and Word as well as Slides and PowerPoint |
| Partners sharing one grade and comment | Decide from how often group work happens. Could be copied across in CAM afterwards |
| Late marking | A Late tick in CAM2, or set in CAM. Downloaded files may not show when they were handed in |
| Gallery of all students' work at a glance | Keep the paper strip, and add thumbnails only if teachers miss it |
| Older drafts of the same work | Use the newest file. Earlier ones are a separate draft task |

**Things to change if this is agreed:**

- **CAM's locked decision D16** says drafts and normal assignments are graded in the workspace, so it needs amending.
- **CAM2's scope** grows from exams to any one task at a time. It still grades one task at a time, so the single-task rule holds, but the name *CAM2 Exam Grading* may need another look.

**Still to decide:**

1. **Teachers using CAM2 on its own:** should they ever get whole submissions? CAM2 must stay a standalone grader for single exams. Recommended: only when opened from CAM at first, then look again once it has been used for real.

### F6: Exam comments should carry weight in CAM's term comments

**From:** project lead, 2026-11-05. **Size:** Small, in CAM. **Status:** Gap confirmed from the code, not yet run; to plan

**What was asked:** the comments teachers give on an exam should have a large place in the final comment a student gets for the term.

**What happens today:**

| Comment from CAM2 | Reaches CAM? | Reaches the term comment? |
|---|---|---|
| Overall comment | Yes | **Only sometimes.** It is copied onto the student's scores when the teacher applies grades in Window 1. It is then used only if that exam ranks among the student's highest or lowest pieces, up to a set number of each (`select_evidence`) |
| Each question's comment | Yes, and shown on the student's page | **Never.** The term comment reads only `student.scores`, and these stay in `exam_results` |
| Numbered notes ([F2](#f2-notes-drawn-on-the-answer-image)) | Not yet | Not yet |

**Why this is a gap:** an exam with a middling grade can drop out of the term comment completely, however much the teacher wrote. Draft comments are always included, so exams currently get less than drafts do.

**Proposal:** add an always-included exam block to the prompt, as the draft block already is: `[CURRENT TERM — EXAM FEEDBACK]`, with the overall comment, each question's comment and the note text for every exam this term. Tell the LLM to give it particular weight.

**To watch:**

- **Prompt length:** 15 question comments of up to 300 characters can get long, so it may need a limit per exam.
- **Timing:** Phase 3 of CAM's upgrade plan changes how exam grades are decided in Window 3, so this should be planned alongside it, and the overall comment must still carry over.
- **Assignments:** their comments are also chosen by ranking. Should they stay that way, with only exams always included? Recommended yes, or the prompt grows too long.

### F7: A permanent place for a year's work

**From:** project lead, 2026-11-05. **Size:** Medium. **Status:** Direction agreed; not being built yet

**What was asked:** all of a student's work should build up across a year and from year to year (Year 7, 8, 9), with students promoted between years. A teacher should be able to select a student and see their work over time. Files must live in one fixed place that doesn't change from task to task, on a cloud drive so they don't fill the teacher's hard disk.

**Division of work (agreed):** CAM holds the whole year's record for each class. CAM2 always stays a standalone grader.

| | CAM | CAM2 |
|---|---|---|
| Job | The teacher's home for the whole year: classes, terms, grades, term comments, and progress over time | The grader for one exam, assignment or draft at a time |
| Used on its own? | No | Yes, by any teacher, with or without CAM |
| Where files go | Decides this once, for every task | Through CAM: where CAM says. On its own: wherever the teacher chooses |

CAM already covers the whole school year, with classes such as `Year 7 A (2026-27)`. This keeps CAM2 simple for teachers who only want to grade one exam.

**The fixed place mostly exists already.** When CAM opens an exam, it tells CAM2 the folder: `<class cloud folder>/exams/<exam name>/`, with the scans included. The teacher doesn't choose it for each exam. The proposal:

- **Do the same for assignments and drafts,** for example `<class cloud folder>/assignments/<task name>/`.
- **Teachers choose the cloud folder once,** in CAM, so it never varies between tasks.
- **Use the cloud drive's own desktop app,** which shows it as an ordinary folder. This needs no Google API or OAuth, so it avoids the problem in [F5](#f5-move-drafts-and-assignments-into-cam2-and-retire-the-workspace). Drive and OneDrive can also keep files online until they are opened. School rules on these apps still need checking.

**Saving space: treat crops as disposable.** Crops can be rebuilt from the scans at any time, so they don't need keeping permanently. File count may be a bigger problem than size:

| Rough example, to measure on a real session | Crop files | Crop size |
|---|---|---|
| One exam: 25 students, 15 questions | 375 | About 190 MB |
| A year: 6 classes, 6 exams each | 13,500 | About 7 GB |

Thousands of small files sync slowly. So:

- [F8](#f8-compact-and-delete-finished-sessions)'s **Compact** button removes a finished task's crops and keeps everything else. Opening the task again rebuilds them. CAM could also do this by itself when a task is finished, which is still to decide.
- Whole submissions have no crops at all.
- Stamps and highlights aren't affected, because they are saved as positions on the scanned page.

**Seeing a student's work over time** would come later, as a CAM feature reading from this fixed place. This is another reason to keep the folder layout fixed from the start.

**Promoting students between years** isn't in CAM yet, as far as I could find. It needs each student to keep one ID across years, because classes today are separate for each year. This should be designed before the first year's data builds up.

### F8: Compact and delete finished sessions

**From:** project lead, 2026-11-05. **Size:** Small to medium. **Status:** Proposed; not being built yet

**What was asked:** finished exams pile up on CAM2's start screen and take up disk space. Teachers should see how much space each one uses, and be able to shrink it or remove it completely.

**Proposal:** each session on the start screen shows its size, with two buttons:

```
Y8 Science Midterm                          2.1 GB   [Compact?]  [Delete]
Step 5 · 25 / 25 graded · Saved 3 Nov
```

After clicking **Compact?**:

```
Y8 Science Midterm    Freed 1.6 GB · 0.5 GB left     Compacted   [Delete]
Step 5 · 25 / 25 graded · Saved 3 Nov
```

**Compact** removes the answer images cut from the scans.

| Removed | Kept |
|---|---|
| `crops/`, except the handwritten-name crops | Scans, grades and comments, backups, thumbnails, student PDFs and the gradebook |

- **It loses nothing,** because the crops can be rebuilt from the scans. So it needs no warning.
- **Offered** once every paper is graded, and only when all the scans are there and no other computer has the session open.
- **Opening a compacted session rebuilds its crops first,** with a progress bar, and the label returns to **Compact?**. This rebuild is essential: today a report with a missing crop prints with no image and no error (`_question_with_image`).
- **It doesn't touch the session or grades files.** CAM only re-reads a session when those two files change, so compacting won't trigger a re-read. CAM2 tells a session is compacted by looking at the folder.
- **Name crops stay,** because CAM's Window 2 shows them.

**Delete** removes the session completely, including its entry on the list.

- **Confirm first,** naming the exam, and say plainly that the grades and comments, student PDFs and gradebook all go, and that this can't be undone.
- **Only CAM2's own files go.** A teacher can choose an existing folder for a session, so CAM2 removes the files and folders it made, then the folder itself only if nothing else is left in it. It also clears the session's emergency copy on this computer.
- **Not while another computer has it open.**
- **The existing Remove stays,** for a session whose folder can't be found. It only takes the entry off the list.

**Sessions linked to CAM:** a session opened from CAM shows the label **Linked to CAM** where others show **Delete**. CAM owns that exam's folder and record, so the label also tells the teacher that removing it starts in CAM. Compact still works.

```
Y8 Science Midterm                          2.1 GB   [Compact?]  Linked to CAM
```

- **How CAM2 knows:** CAM marks the session when it opens it (`config["host"]`), so the label needs no connection to CAM. That mark also stays if the session is later opened with **Open folder**.
- **After the exam is deleted in CAM:** CAM moves the session folder to `exams/_deleted/`, so CAM2 finds the folder gone and shows its existing "folder can't be found" entry with **Remove**. No new link between the apps is needed.
- **Deleting in CAM doesn't free the space yet.** The folder stays in `exams/_deleted/` until the teacher removes it by hand. CAM may need a way to show or empty that folder.

**A longer list (agreed in principle):** the 10-session limit (`RECENT_MAX`) would be reached within months. The limit is a single number, so raising it is easy. What needs care is showing a long list:

- **Keep the list in its own scrolling box,** newest first, so the rest of the start screen stays in place.
- **Allow about 200 sessions.** That is many years of grading, while still keeping a limit on the list file.
- **Sizes and the Linked to CAM label load after the screen appears, as the teacher scrolls to them.** Reading 200 folders on a cloud drive at once could be slow, and neither appears until it is known.
- **The list belongs to each computer.** Sessions that already dropped off won't come back by themselves, only when opened with **Open folder**.

**Showing the size:**

- **It loads after the screen appears,** so a slow cloud drive or USB stick never holds up the start screen.
- **Reading sizes doesn't download anything** from a cloud drive.
- **Say "folder size", not "space on this disk".** A cloud drive may keep files online only, and may hold deleted files in its own trash for a while, so the freed space may not appear on the disk straight away.

**What changes:**

| Where | Change |
|---|---|
| `static/js/start.js` `recentList`, `static/app.css` | The size, the buttons and labels, and the scrolling list |
| `engine/storage.py`, `app.py` | Folder size, compact and delete routes, whether a session is linked to CAM, and the longer list |
| `engine/workflow.py`, `app.py` | Rebuild crops when a compacted session opens (`slice_session` removes the whole `crops/` folder, name crops included, then rebuilds them all) |
| `i18n/en.json`, `i18n/ja.json`, `tests/` | The wording, and tests that reports keep their images after compacting and that Delete leaves other files alone |

### Ideas from research (F9 to F15)

**From:** project lead, from research into digital grading software using Gemini, 2026-11-05. These are optional ideas to consider for the next build. No colleague has asked for them yet.

**Where the research places CAM2:** a small offline download for one teacher, between cloud subscriptions (Gradescope, Crowdmark), institutional servers (Plom, Submitty), bubble-sheet readers, and closed Japanese products (EdLog Clip, リアテンダント). These comparisons haven't been checked. Its claim that the 3–4 band gets overcrowded in MYP grading also hasn't been checked against real class data.

**The research's suggested order, and what these notes suggest instead:**

| Research's version | What it holds | Suggestion |
|---|---|---|
| v0.4.0 | Keyboard ([F9](#f9-grading-from-the-keyboard)), spread of grades ([F10](#f10-the-spread-of-grades-while-grading)), gallery ([F11](#f11-gallery-of-one-question)) | Best value of the set. They add no new kind of saved data, so the session file and what CAM reads stay as they are |
| v0.5.0 | Calibration ([F12](#f12-calibration-mode)), rubric structure ([F15](#f15-rubric-points-that-update-totals)), straightening ([F13](#f13-straightening-crooked-scans)) | Take only the parts recommended below, once colleagues have tried the first group |
| v1.0.0 | Class list, analysis and return slips ([F14](#f14-class-analysis)) | The class list and a form of slip already exist. Add the analysis sheet when convenient |

### F9: Grading from the keyboard

**From:** research, 2026-11-05. **Size:** Small. **Status:** Optional; recommended

**The idea:** grade a whole question without touching the mouse.

**What CAM2 does today:** Step 4 has no keyboard shortcuts. After a grade, the cursor moves to **Next paper**, so pressing Enter already moves on. Choosing the grade still takes the mouse, or Tab.

**Proposal:**

| Key | Action |
|---|---|
| `0`–`9` | Give that level or mark, on questions with grade buttons |
| `←` `→` | Previous or next paper |
| `N` | Not answered |
| `C` | Go to the comment box |
| `Esc` | Leave the comment box |

- **Keys do nothing while the teacher is typing,** including during Japanese input, so a comment can't change a grade.
- **Questions with many marks already have a number box,** which keeps working as it does.
- **A short line under the card lists the keys,** with no setting to turn them on.

**Not quite "no mouse":** under [F2](#f2-notes-drawn-on-the-answer-image), comment stamps and highlights are dragged onto the answer. So the keyboard covers grades and moving between papers, and comments stay typed or dragged.

**Still to decide:**

1. **Can a number key change a grade already given?** One stray key could silently change a paper's grade. Recommended: on a graded paper, the key shows a short "Change 4 to 5?" that Enter confirms.
2. **Trying it:** does this feel faster than clicking on a school laptop?

### F10: The spread of grades while grading

**From:** research, 2026-11-05. **Size:** Small to medium. **Status:** Optional; recommended

**The idea:** show how grades are spreading across the bands while the teacher grades, as a prompt when standards start to drift. Clicking a band reviews only those papers.

**What CAM2 does today:** Step 5 and the gradebook show each question's average, highest and lowest, but no counts per band. Step 4 can already narrow the papers with **Show ungraded only** (`visibleStudents`), so a band filter fits beside it.

**Proposal:**

```
Q3 · Criterion B    0: 1   1–2: 3   3–4: 12   5–6: 6   7–8: 2   Ungraded: 1
```

- **One line above the paper strip,** with a small bar for each count, for the current question and criterion. The whole paper's results stay in Step 5.
- **The bands are the teacher's own,** from the rubric (`band_for_level`), so nothing here is specific to MYP. A marks question shows each mark, or ranges if there are many. **Not answered** gets its own count.
- **Clicking a band** narrows the strip and ◀ ▶ to those papers, in an amber frame with a **Show all** button.
- **The list is fixed on entry.** A paper moved from 3–4 to 5–6 stays in the list until the teacher leaves, so it doesn't vanish on screen.
- **Grades save as usual,** straight away. See [F12](#f12-calibration-mode) on why there is no trial copy.

**To watch:** criterion grading compares work with the descriptors, not with other students. A live spread could push a teacher towards an expected shape. It is worth asking colleagues whether it helps or distracts before it becomes permanent.

**What changes:** `static/js/step4.js` and `static/app.css` mainly, with the counts worked out from the grades already in the browser, or added to `engine/grading_summary.py` so that [F14](#f14-class-analysis) can share them.

### F11: Gallery of one question

**From:** research, 2026-11-05. **Size:** Small to medium. **Status:** Optional; recommended

**The idea:** a full-screen grid showing every student's answer to the current question, opened with a button or `G`. It is for comparing answers, and grading stays in the normal view.

**What CAM2 does today:** the paper strip shows who is graded, but only one answer can be seen at a time. [F5](#f5-move-drafts-and-assignments-into-cam2-and-retire-the-workspace) also lists a gallery as something the workspace has and CAM2 lacks.

**Proposal:**

- **Each card shows** the answer image, with its grade or **Ungraded**, in colour as well as words. Clicking a card goes to that paper and closes the gallery. `Esc` closes it.
- **Sort by grade,** so that all the 3–4s sit together. This is where the comparison pays off, and it pairs well with [F10](#f10-the-spread-of-grades-while-grading).
- **Names stay hidden** when **Hide student names** is on.
- **Images load as they scroll into view,** because the crops are full-size files and a cloud drive may have to download them. A question with tall answers may need a size limit on each card.
- **Enlarge on hover** could come later, after trying it on a trackpad.

**Left out:** the research's **Flagged for review** colour, because CAM2 has no flag for review. Adding one would be a separate request.

### F12: Calibration mode

**From:** research, 2026-11-05. **Size:** Large. **Status:** Optional; recommended only in part

**The idea:** a separate mode for re-judging a crowded band, with trial changes that can be applied or discarded, a checklist for separating levels, a comparison against a benchmark paper, and an audit on leaving.

| Part | Suggestion | Why |
|---|---|---|
| Review only one band | **Yes,** as [F10](#f10-the-spread-of-grades-while-grading) | Most of the benefit, for little work |
| Trial changes in a separate copy, then **Apply** or **Discard** | **No** | Every grade is saved at once, with save checks, an emergency copy and warnings about a second computer. A separate copy of grades sits outside all of that, so a crash could lose a review. It also raises the question of which grades reports and CAM should read |
| Summary on leaving a review | **Later, if wanted** | When a band review ends: *22 reviewed, 15 unchanged, 4 raised, 3 lowered*, with a **Put these back** button. The start grades are kept only for that review, so there is still one set of grades and no new mode. This gives most of what the trial copy was for |
| Temporary checklist for separating levels | **No** | A new thing to set up and explain. The band's descriptor is already on the card, and the teacher can note a rule elsewhere |
| Benchmark paper beside the current one | **Later, if wanted** | A real help for consistency, but medium work on a screen already split in two. Try it after [F11](#f11-gallery-of-one-question), which may cover the need |

**Why not the whole mode:** CAM2 aims to have few options and no training, and a mode with its own rules is the opposite. This should only come back if teachers ask for it after using [F10](#f10-the-spread-of-grades-while-grading).

### F13: Straightening crooked scans

**From:** research, 2026-11-05. **Size:** Medium. **Status:** Optional; check the need first

**The idea:** document feeders can turn pages by about 0.5° to 3°, so the handwriting near a box's edge can be cut off. Straighten each page before cropping.

**Why it could matter:** **✎ Adjust this box** re-crops that question for every paper. One crooked paper therefore means widening the box for the whole class. **See whole page** still shows clipped writing on screen, but the report prints only the crop.

**First, check the need:** look at real class scans from school photocopiers and count how many answers get clipped. Paper shifting sideways or up and down may be as common as turning, and straightening doesn't fix that. Nor does it fix the perspective in phone photos.

**Don't use the code in the research as written:**

- **It adds OpenCV and NumPy,** which CAM2 doesn't otherwise use, and would add tens of megabytes to each download. The project's rule is to avoid new dependencies unless they fix a bug.
- **It measures the wrong thing.** `minAreaRect` fits a rectangle around all the ink on the page, not the lines of text. A scanner's dark edge, a margin note or a page's uneven writing can change the angle it finds.
- **Its angle rule may be out of date.** As far as I know, `minAreaRect` changed how it reports angles from OpenCV 4.5. The code's `angle < -45` check would then be wrong for some pages, and they would stay crooked with no warning. This hasn't been tested.

**If real scans show the need:**

- **Find the angle with Pillow,** which CAM2 already ships. Shrink a copy of the page, try small angles, and choose the one that gives the sharpest rows of text. This should take about 50 lines, and needs trying on real scans, including handwriting and Japanese vertical text.
- **Find the angle when scans come in, and save it per page.** Crops rebuilt later ([F8](#f8-compact-and-delete-finished-sessions)) then come out identical.
- **Never change the scan file.** Turn the page in `load_page_image`, which serves the crops and the page previews, so the box drawing, **See whole page** and the crops all agree.
- **Stay inside 0.2° to about 5°,** and leave other pages alone. Tiny turns only blur the writing. Page fixes for booklets and upside-down pages come first.
- **Don't change sessions that are already sliced,** because their crops, and [F2](#f2-notes-drawn-on-the-answer-image)'s note positions, must stay on the same writing.

### F14: Class analysis

**From:** research, 2026-11-05. **Size:** Small to medium. **Status:** Optional; recommended only in part

**The idea:** the class statistics schools expect, as exports.

| Part | Today | Suggestion |
|---|---|---|
| Class list matched to papers | **Already there** (Step 3) | Nothing to do |
| Average, highest and lowest | **Already there,** per question, section and total, in Step 5 and the gradebook | Nothing to do |
| Spread across bands | Not there | **Yes,** as a sheet in the gradebook, sharing [F10](#f10-the-spread-of-grades-while-grading)'s counts. Also shows each question's average as a percentage of its maximum, which shows which questions the class found hard |
| Standard deviation | Not there | **Add to that sheet if wanted.** One extra column, though many teachers won't use it |
| Discrimination index (top 27% against bottom 27%) | Not there | **Later, and only for marks.** It ranks students by total, and a levels paper has no total because levels are never added. In a class of 25 it compares about 7 students with 7, so a single answer can swing it, and it would need a note saying it is rough. Choice questions need their own rule too |
| `Class_Criterion_Summary.csv` | Excel gradebook | **Not needed yet.** Add a CSV when a real system needs one. CAM already reads the session itself |
| One-page return slips | **Mostly there.** Reports can already leave out images by section, rubric tables and section results | **Nothing to do** unless teachers ask. A report with images off is close to a slip |

**Scope:** all of this stays within one exam. Comparing exams or classes over time belongs in CAM ([F7](#f7-a-permanent-place-for-a-years-work)).

### F15: Rubric points that update totals

**From:** research, 2026-11-05. **Size:** Large. **Status:** Optional; mostly works already

**The idea:** store each rubric item's points apart from what each student was given, so that changing an item's points updates every student's total.

**What CAM2 does today:** the useful part already works. Grades store only each student's mark or level. Totals, percentages and section results are worked out when they are shown or exported (`student_summary`), so changing a question's maximum or a section's weighting updates everyone. Rubric wording is also kept apart from the grades.

**Why not the research's structure:** it turns each level into points that are added up. CAM2 deliberately reports levels as given (`B5`) and never adds them, or adds them to marks. So this would change what a level means, for no gain.

**Two things that remain:**

- **Count beside each band:** this is [F10](#f10-the-spread-of-grades-while-grading).
- **Reusable marking items** (for example *-1, units missing*, where changing it to *-2* updates everyone who has it) would be a real new feature. It is a different way of grading from CAM2's single mark per question, as used in Gradescope. It should wait until a colleague asks for it, and needs its own design.

## Done

From colleagues trying the test builds. Details are in [PLAN.md](PLAN.md) §8.

| Request | Version |
|---|---|
| School laptops have no **Run anyway**, so say how to unblock CAM2 on Windows | `v0.3.1-dev` |
| A new version opened an older CAM2 that was still running | `v0.3.1-dev` |
| Limits on the length of a question's comment and the overall comment (F2's first part) | `v0.3.2-dev` |
