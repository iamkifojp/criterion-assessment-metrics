# CAM2 — Exam Sections & Report Options (Implementation Plan)

> **Status:** agreed design (2026-11-02). Phases 1 to 6, the engine, the screens, the report and the gradebook, are built (2026-11-03). Phase 7, testing, has its sample exams, tried on Windows; the test build for colleagues is `v0.3.2-dev`. It adds to [PLAN.md](PLAN.md), which has been brought into line with it; for the details of sections, mixed papers and the report, this plan is the one to read.

---

## 1. Goal

Many MYP exam papers are divided into sections. A section of multiple-choice questions is marked, its total becomes a percentage, and the teacher uses that to help decide a rubric level. Giving a rubric level to each multiple-choice question makes no sense.

So CAM2 should let a teacher:
- divide a paper into sections;
- grade each question with marks or a rubric, mixed in any way, and go back during set-up to add marks or criteria they left out;
- report each criterion's grades as they were given, and optionally decide an overall level per criterion;
- choose how much each section counts towards the final percentage;
- produce a clearer, shorter report that can leave out answer images.

**CAM2 stays simple.** It grades one exam at a time, with nothing that spans classes or assignments. Prefer what the app can work out for itself over a new setting, and hide anything that does not apply to this exam.

**Marks are the simplest path.** A teacher who only wants marks, or just counts right and wrong with one-mark questions, never has to see a criterion or rubric. They may handle criterion grades outside CAM2.

**Words used in this plan**
- **Criterion:** what is being assessed, such as Criterion B. Each has a rubric.
- **Rubric level:** a number on that rubric's scale, such as 5 in the 5–6 band. Written with its criterion as `B5`.
- **Final level:** an overall level for one criterion, decided by the teacher. Optional.

---

## 2. Teacher Flow

### Step ② Set up the questions
- **Sections are optional.** With none, the whole paper is one section and the screens look as they do today.
- **Adding one:** in the question list, **Start a new section here** adds a divider. Sections follow the order of the paper, so a question always sits inside one section. Moving a question past a divider moves it into that section.
- **A section has only an optional name** (blank shows as `Section 1`). It groups questions for the report and for weightings. It does not decide how they are graded.
- **The first screen still asks Marks or Rubric,** but only as a starting point: it sets what the question card asks for first. Choosing the other card later changes no question and no grade, so "You can change it later" becomes true.
- **Every question card has both:** a **Marks** box and **Criteria** ticks. The ticks appear once the exam has a rubric, and until then a small **Add criteria (optional)** link opens the rubric screen. A marks teacher who ignores it sees no rubric screens anywhere.
- **What is filled in decides how a question is graded:**

| Marks box | Criteria | Graded with | Reported as |
|---|---|---|---|
| Filled in | None | Marks | `6 / 10` |
| Filled in | Ticked | Marks | `6 / 10`, and counted in that criterion's marks total |
| Empty | Ticked | Rubric levels, one per criterion | `B5` |
| Empty | None | Not ready: CAM2 asks for one or the other before slicing | |

An exam with exactly one rubric keeps today's shortcut: a question with an empty marks box and no ticks counts as ticked on that rubric. A question with marks is only ever counted towards a criterion that is really ticked.

- **Each question gets one grade,** so a teacher never grades the same answer twice. On a question with marks, criteria are used only at the reporting stage. A paper with half marks and half rubric needs no extra setting, with or without sections.
- One section can cover several criteria, because criteria are ticked per question.
- **A question is whatever the teacher draws a box around.** A printed "Question 1" of 24 multiple-choice items can be one question worth 24 marks, or 24 questions. A "Question 2" with parts A and B can be two questions. No separate "parts" feature is needed.
- **Choice questions** ("answer 2 of 3") must stay inside one section, because otherwise a section's total has no clear meaning. They must also all grade the same way, because a mark can't be ranked against a level. CAM2 checks this before slicing.

### Going back to fill in what was left out
The exam paper is already set, so this is about finishing set-up in whatever order suits the teacher, not about regrading.

- **Marks first, criteria later:** add the rubric, then tick each question's criteria. Marks and grades are not affected, so ticks can be added or changed at any time, even during grading.
- **Rubric first, marks later:** type marks into the question's box. It then grades with marks, and its criteria stay ticked, so its marks count towards that criterion.
- **One table for all of it:** the Slice screen's question list becomes editable, with one row per question, its **Marks** box, a tick per criterion, and how it will be graded. A teacher can finish in one place instead of opening each question.
- **No re-slicing** is needed for any of this, because the boxes have not changed.
- **A mixed paper gets a check:** before slicing, if some questions have marks and some do not, CAM2 names those graded with rubric levels, so a forgotten marks box is not mistaken for a rubric question.
- **One lock:** once a question has a grade, it cannot change between marks and rubric levels, because the two cannot be converted. A rubric question's marks box is locked with a short note. A marks question stays a marks question, but its number can still be corrected if it was typed wrongly, as long as it stays at or above the highest grade given. Every other question stays open.

### Step ④ Grade
- Each question shows marks buttons or rubric levels, according to the table above. Otherwise this is unchanged.
- A rubric level is reported as given, with its criterion: Q5 is `B5`, Q6 is `A3`. CAM2 does not average them.

### Step ⑤ Review & export

**Overall criterion results** is optional and off by default. It is offered only when the exam uses criteria. Because each question has its own criterion, this gathers a criterion's results however many sections they are spread across, including a few Criterion A questions inside a mostly different section. The teacher then decides the final level:

```text
Student      Criterion A          Final   Criterion B                     Final   Criterion C    Final
Yui Suzuki   Marks 46/55 · 83.6%  [   ]   Marks 6/10 · 60.0%; Grades B6, B5  [   ]   Grades C5, C6  [   ]
```

- **Marks questions:** added together into one total for the criterion, using any section percentages (§3).
- **Rubric questions:** the actual grades achieved, listed separately. They are never added to marks, totalled or averaged.
- A criterion with only marks shows only the total, and one with only rubric questions shows only the grades.
- Choice-group questions that did not count are left out.
- The final level starts blank, and a final level left blank does not print.
- **Export warning:** if a final level is filled in for some students but not others, the teacher is told which before the reports are made.

**Criterion levels are only decided for the whole paper.** A criterion can have questions in several sections, so a level for one section could say 8 while a later Criterion A question scored 1.

**Section weightings** apply to marks only. CAM2 never works out a section total for rubric grades.
- **No weighting** is the default: every question has its own marks, and the total is simply those marks added up.
- **Weighting sections:** each section's marks become a percentage, and that percentage is applied to the section's share of the paper. A student with 24 / 24 in a section worth 20% has 100% of that section, so they get 20 marks out of 100 for it.
- When on, sections with marks questions start with equal shares: 50 and 50, or 34, 33 and 33 for three sections. A section with only rubric questions has none.
- **The shares always add up to exactly 100.** When a teacher types a percentage, that section keeps it and the sections not yet typed share the rest equally, with any leftover going to the first of them. One section always stays automatic, so the teacher never has to do the sum.
- The shares do not stop at 99, because then a student with full marks would get 99%.
- The **Total on report** override then changes the final percentage instead of the marks total.

**Report options:** at most five, each hidden when it does not apply, and saved with the session. They apply to the whole class. An exam with only marks and no sections sees just the last two.

| Option | Shown when | Default |
|---|---|---|
| Section results | the exam has two or more sections | Off |
| Overall criterion results | the exam uses criteria | Off |
| Rubric table | a criterion with descriptors is used | On |
| Overall marks and percentage | the exam has marks questions | On |
| Answer images, one tick per section | always (one tick if there are no sections) | All on |

**See one report first** makes the PDF for the selected student, so the teacher can check it before making the whole class's reports.

---

## 3. Calculations

| Item | Rule |
|---|---|
| Section marks | The counted marks of the section's marks questions over their maximum, added up and never typed in. Choice groups count as they do today, inside their section. |
| Weighted marks for a section | Section percentage × the section's share, shown as `44.0 / 50`. A student with 24 / 24 in a section worth 20 gets `20.0 / 20`. |
| Section percentage | Marks over maximum, shown to 1 decimal place. |
| Total, no weighting | Every marks question added together, shown as `52 / 65 · 80.0%`. |
| Total, with weighting | The sum of (section marks ÷ section maximum × weighting). It is worked out from unrounded figures and **rounded half up only once, at the end**. The report shows only the percentage, because it would not agree with a total out of 65. |
| Equal shares | 100 divided by the number of sections with marks questions. Any leftover goes to the first sections, one point each, so the shares add up to exactly 100. |
| Mixed paper | Rubric levels are never added to marks. The overall line says which sections it covers. |
| Criterion marks, no weighting | The marks of the questions on that criterion, added together: `46 / 55 · 83.6%`. A question on two criteria counts in both. |
| Criterion marks, with weighting | Each question counts as much here as it does in the overall percentage: its share is section weighting × question maximum ÷ section maximum. The criterion's percentage is the sum of (marks ÷ question maximum × share), divided by the sum of those shares, and rounded once at the end. The report shows only the percentage. |
| Incomplete papers | An ungraded question stays in the criterion's maximum, as it does in the overall total, and the student is flagged incomplete. |
| Rubric levels | **Reported as given.** CAM2 no longer averages a student's levels or suggests a final level, and this replaces the rubric rows in PLAN.md §3. Rules for ranking choice-group questions stay as they are. |
| Final level | Optional, and always typed by the teacher. Must be a level in one of the rubric's bands, so the report can always shade the right band. |
| Short form of a grade | The last letter of the criterion's name when that name ends in a single letter (`Criterion B` or `基準B` gives `B5`). Any other name prints in full (`Knowledge 5`). |
| Ungraded question | Not counted, and the student is flagged incomplete, as today. |

**Why no average:** a level should be a best-fit judgement against the descriptors, not arithmetic. See §8.

**Example with weighting:** Section A 22 / 25 (88%) at 50% and Section B 30 / 40 (75%) at 50% gives 81.5%. Simply adding the marks gives 52 / 65, or 80%.

**Example for a criterion:** Criterion A covers all of Section A and 24 / 30 of Section B's 40 marks.
- Without weighting: 22 + 24 = 46 out of 25 + 30 = 55, or 83.6%.
- With 50% on each section: Section A's share is 50, and Section B's Criterion A questions have a share of 50 × 30 ÷ 40 = 37.5. So (88% × 50 + 80% × 37.5) ÷ 87.5 = 84.6%.
- A criterion on only part of the paper still reaches 100% when its questions earn full marks, because the shares are divided by their own sum.

---

## 4. What is Saved

`cam2_session.json` gains:

```json
{
  "sections": [{"id": "sec1", "name": "Scientific knowledge", "weight": 50},
               {"id": "sec2", "name": "", "weight": null}],
  "questions": [{"id": "q1", "section_id": "sec1", "max": 24, "rubric_ids": ["r1"]}],
  "weighted": true,
  "report_options": {"section_results": false, "overall_criteria": false,
                     "rubric_table": true, "overall_marks": true, "no_images_for": ["sec1"]}
}
```

`grades.json` gains, under `overall.<student>`:

```json
{"report_percent": null}
```

- **A question has no separate marks-or-rubric field.** It grades with marks if it has a `max`, and with rubric levels if not. Grade entries keep their current shape.
- **Upgrading old rubric sessions:** a question can still hold a `max` from before the teacher chose Rubric, which would now make it a marks question and read its levels as marks. When an old rubric session opens, those `max` values are cleared before anything else reads them. In the same way, an old marks session loses any criteria left ticked from before the teacher chose Marks, so they don't start counting or printing.
- **`config.mode` stays** as the starting choice only. Grading never reads it.
- **`final_levels` stays** as the overall level for each criterion. Only its meaning changes: blank now means no level, not "use the average".
- **Typed shares:** a section's `weight` holds the share and each section also records whether the teacher typed it (`"weight_typed": true`), so the app knows which ones to rebalance.
- **Grades stay keyed by question and student ids**, so sections can change without a grade moving to another question or student.
- **Old sessions** have no `sections`. They read as one section, every question uses the existing `mode`, and they open and grade as before. A final level the teacher did not type starts blank.
- **`model.VERSION` goes to 2**, so an older CAM2 refuses a session it would misread.
- **The wipe guard** (`model.grades_mass`) also counts final levels, because they are now teacher work that nothing can recalculate.

---

## 5. Code Changes

| File | Change |
|---|---|
| `engine/model.py` | Document the new shapes, bump the version, extend `grades_mass`. |
| `engine/grading_summary.py` | Add `sections()` and `question_mode()`, and use `question_mode()` for every exam-wide `mode` check (`slots`, `set_grade`, `question_values`, `student_summary`, `class_summary`). Add per-section and per-criterion marks, and weighting with equal shares and rebalancing. Remove `average`, `suggested` and the rubric `adjusted`. Choice groups must stay inside a section (`check_choice_groups`). `marks_maximum` works per section. `set_final_level` uses `rubrics.check_level`. |
| `engine/workflow.py` | Save sections and options. `set_mode` no longer locks. `set_questions` refuses to add or remove the `max` of a question that has a grade. `check_ready` asks each question for marks or a criterion, replacing its exam-wide checks. |
| `engine/storage.py` | Clear stale `max` values when an old rubric session opens. |
| `engine/reports.py` | The new order and layout (§6), using a small drawn-table helper: MuPDF's HTML ignores table column widths. A rubric prints if any question ticks it, whether graded by marks or rubric. |
| `engine/gradebook_xlsx.py` | Add section marks, percentages and weighted marks, the final levels, and the overall percentage. Remove the average columns. List sections on the second sheet. Show the class average, maximum and minimum for each section's marks. |
| `app.py` | Routes for sections, final levels, weighting, report options and the one-report preview. |
| `static/js/step2.js`, `boxes.js`, `step4.js`, `step5.js`, `store.js` | The screens in §2. The rubric tab is always available, and the question card always shows the Marks box. |
| `i18n/en.json`, `i18n/ja.json` | Every new string in both languages. Reword `step2.mode.coach`, `step2.mode.rubric_hint` ("Averages are worked out for you") and `step5.coach_rubric`, and replace `error.mode_locked` with the per-question lock. |

Nothing here adds a dependency or a bundled file, so packaging is unaffected.

---

## 6. The Report

Printed in this order:
1. **Header:** exam name, date, student.
2. **Results:** the overall line, with one row per section above it if Section results is on.
   - The format follows the questions: marks questions show a total and percentage (`22 / 25 · 88.0%`), rubric questions list their grades with no total (`Q5 B6 · Q6 B5 C5 · Q7 C6`), and a section with both shows both.
   - The Weighted marks column (`44.0 / 50`) appears only when weighting is on.
   - With no sections, only the overall line prints.
3. **Rubric:** one copy of each table, only for criteria used in this exam, and only if the Rubric table option is on.
   - With Overall criterion results on, **one box per criterion** holds everything together beside its table: the **Final level** if the teacher decided one, the marks total, and the rubric grades (`B6, B5`). The final level's band is shaded.
   - With the table off, the same boxes print on their own.
4. **Overall comment:** below the tables, only if there is one.
5. **Questions, grouped by section:**
   - Each section's heading shows its marks total only if Section results is on.
   - **Images on:** as today, with the label, answer image and grade in a row and the comment below. A question on two criteria shows `B5` and `C5`.
   - **Images off:** a five-column grid of grades, followed by one row for each question that has a comment.

**The rule that keeps options few: what the teacher filled in prints, and what is blank does not.** Levels, final levels and the overall comment need no tick boxes of their own.

**A marks-only exam** prints just the header, the overall marks and percentage, any overall comment and the questions.

Per-section images matter because answer images are capped at 330 points tall (`IMAGE_MAX_H`). A multiple-choice question boxed across several pages would shrink until it can't be read, so a teacher can turn off images for that section and keep the written answers.

---

## 7. Build Phases

Each phase ends with its tests passing, and with `CHANGELOG.md` and `ARCHITECTURE.md` updated.

**Phase 1: Engine**
- Sections, how each question is graded, section totals, weighting, final levels, removing the averages.
- Tests:
  - an old marks session and an old rubric session give the same marks and levels as before;
  - a marks exam with no sections or rubrics needs nothing new;
  - a mixed paper's total ignores rubric levels;
  - the 81.5% example, plus a case where rounding too early would give a different answer;
  - the criterion examples in §3, a criterion spread across sections, one with both marks and rubric grades, and one reaching 100% on full marks;
  - equal shares and rebalancing always add up to exactly 100, for one to seven sections;
  - a choice group across two sections is refused;
  - each row of the question table in §2 grades the right way;
  - adding criteria after marks, or marks after criteria, keeps every box and needs no re-slicing;
  - ticking criteria on a graded marks question leaves its marks alone;
  - a question with a grade cannot gain or lose its `max`, and other questions still can;
  - a mark is never read as a level, or a level as a mark, including in an upgraded old rubric session with a stale `max`;
  - a paper with marks and rubric questions in one section, and with no sections at all.

**Phase 2: Step ② screens**
- Dividers, section names, both fields on every question card, the always-available rubric tab, the editable question table, and the check before slicing a mixed paper.

**Phase 3: Step ④ grading**
- Each question grades the right way, including on a mixed paper.

**Phase 4: Step ⑤**
- Overall criterion results, section percentages, new review columns, report options, the export warning.

**Phase 5: Report**
- The layout in §6 and the one-report preview.
- Tests: each grade and level reaches the right student's report; blanks do not print; only criteria used are printed; the right band is shaded; each image option works.

**Phase 6: Gradebook**
- The columns in §5, with tests.

**Phase 7: Testing**

*Part 1: sample exams, tested here on Windows.* No real exam papers are to hand, so `tools/make_sample_exam.py` makes a made-up exam, whole class, in English and Japanese, with a class list, rubrics and a test guide. The guide's two exams cover what this phase has to try, in English and Japanese:
- **Exam 1:** a marks-only exam with no sections, checking that no rubric screens appear; then one criterion across three marks sections, with marks entered first and criteria added later.
- **Exam 2:** several criteria with a mix of marks and rubric questions, with rubrics entered first and marks added later.

*Part 2: test builds, tested by colleagues.* Make the Windows build here and the Mac build on the MacBook Air, both from one commit, and put them on one release (`v0.3.0-dev`) with the sample exams as a zip, for colleagues on Windows and on a Mac. A real scanned paper is tried when a colleague has one. **Real papers stay out of the repository.**

---

## 8. MYP Notes

These come from school policies and third-party summaries, not the IB's own guide, which was not available when this was written. Check them against *MYP: From Principles into Practice*.

- **Best fit:** teachers judge a student's work against the descriptors as a whole. A level is not a percentage.
- **No mechanical averaging:** a school policy quotes the guide warning teachers not to "mechanically and uncritically average achievement levels".
- **The 1–7 grade** comes from all four criteria, totalled out of 32, so it does not belong on a single exam's report.

Sources: [The Codrington School policy](https://codrington.edu.bb/wp-content/uploads/2024/06/TCS-MYP-Assessment-Policy.pdf), [Sir Geoffrey Leigh Academy policy](https://sirgeoffreyleighacademy.org.uk/wp-content/uploads/2025/07/Assessment-Reporting-Policy-2025-2026.pdf), [IB Mid-Atlantic slides](https://www.ibmidatlantic.org/Math_Presentation_Jan_2020.pdf), [RevisionDojo on final grades](https://www.revisiondojo.com/blog/how-myp-criteria-levels-combined-final-grade).

---

## 9. Deliberately Not Included

- Averages, totals or suggested levels for rubric grades.
- Required rubrics or final levels in a marks exam.
- Criterion levels for a section or a hand-picked group of questions. A level belongs to one question, or to the whole paper as its final level.
- Converting between marks and rubric levels, or changing how a question is graded once it has a grade.
- Giving one question both a mark and a rubric level.
- Automatic conversion from a percentage to a level (`85% = 7`).
- The MYP 1–7 grade.
- A separate strand layer. Teachers type the strands into the criterion's descriptors and can name sections after them.
- Per-section comments.
- Anything spanning several exams, classes or assignments.
