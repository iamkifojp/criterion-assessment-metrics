"""CAM2 engine upgrade, Phase 3 — decide per criterion in Window 3.

Covers docs/CAM2_ENGINE_UPGRADE_PLAN.md Phase 3:

  * A paper's levels and marks grouped by criterion (D10, D11, D13, P4).
  * One decision writes one grade, blank clears it, and a blank dropdown can't
    invent one. A re-send can't change a teacher's decision (P6).
  * The 12-screen deck: however many slides fed the decision, it counts as one
    grade per criterion.
  * Window 1: the mapping, typed final levels applied with a summary first, and a
    plain marks exam with blank dropdowns (P2, P3).
  * Exam comments in the term comment (F6, P12, P13, Q2, Q3).

Sessions are fictional, built with CAM2's own engine in temp folders.

Run:  python -m unittest tests.test_exam_upgrade_phase3
"""

import os
import sys
import unittest
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import app  # noqa: E402
from engine import Criterion, exam_bridge, exam_feedback  # noqa: E402
from engine.exam_feedback import ExamFeedback, feedback_lines, limit_feedback  # noqa: E402
from engine.models import Assignment, CriterionScore, ExamResult  # noqa: E402
from test_exam_bridge import _questions  # noqa: E402
from test_exam_cam2_host import CLASS, EXAM, _AppBase  # noqa: E402

AOKI, BABA = "100001", "100002"
ROSTER = [{"id": "n001", "name": "Aoki Ren", "external_id": AOKI},
          {"id": "n002", "name": "Baba Mio", "external_id": BABA}]
STUDENTS = [("s001", "Aoki.pdf", "n001"), ("s002", "Baba.pdf", "n002")]

# The final-report deck in docs/SLIDE_DECK_EXAM_PLAN.md: which criteria each screen
# assesses, so A has 1 level, B 5, C 2 and D 5.
SCREENS = [("B",), ("B",), ("B",), ("D",), ("A",), ("B",), ("B",), ("D",),
           ("C", "D"), ("C",), ("D",), ("D",)]


class FakeColumn:
    def __init__(self, ui):
        self.ui = ui

    def caption(self, text):
        self.ui.captions.append(text)

    def selectbox(self, label, options, key=None, **kw):
        self.ui.selects[key] = kw
        return self.ui.session_state.get(key)

    def button(self, label, key=None, **kw):
        self.ui.buttons.append(key)
        return self.ui.pressed == key


class FakeStreamlit:
    """Just enough of Streamlit to drive Window 3's group without a server."""

    class Rerun(Exception):
        pass

    def __init__(self, session_state):
        self.session_state = session_state
        self.captions = []
        self.selects = {}
        self.buttons = []
        self.pressed = None

    def caption(self, text):
        self.captions.append(text)

    def columns(self, spec, **kw):
        return [FakeColumn(self) for _ in spec]

    def rerun(self):
        raise self.Rerun()


class _DeckBase(_AppBase):
    """A 12-screen deck graded with levels, as a final report is."""

    LEVELS = {"A": 5, "B": 4, "C": 6, "D": 3}

    def rubric(self, rid, name, top=8):
        rubrics = exam_bridge.cam2_module("rubrics")
        return dict(rubrics.normalize_rubric(
            {"id": rid, "name": name, "bands": [{"levels": "0"}, {"levels": f"1–{top}"}]}), id=rid)

    def deck(self, **kw):
        ids = {"A": "r1", "B": "r2", "C": "r3", "D": "r4"}
        questions, grades = [], []
        for i, letters in enumerate(SCREENS, 1):
            qid = f"q{i:02}"
            questions += _questions((qid, f"Screen {i:02}", 0, [ids[c] for c in letters]))
            for sid in ("s001", "s002"):
                grades += [(sid, qid, self.LEVELS[c], ids[c]) for c in letters]
        kw.setdefault("grades", grades)
        return self.make_session(
            "deck", mode="rubric", questions=questions, students=STUDENTS, roster=ROSTER,
            rubrics=[self.rubric(ids[c], f"Criterion {c}") for c in "ABCD"], **kw)

    def setUp(self):
        super().setUp()
        self.folder = self.hosted(self.deck)
        self.sync()
        self.asg = self.gb.assignments[0]
        self.meta = self.ss["exam_sessions"][CLASS][EXAM]
        self.aoki = self.gb.students[AOKI]
        # No final level typed. The pin also reports its own suggestion here, which
        # newer CAM2 doesn't, and these tests hold on both.
        for student in (self.aoki, self.gb.students[BABA]):
            student.exam_results[EXAM].final_levels.clear()

    def result(self, key=AOKI):
        return self.gb.students[key].exam_results[EXAM]

    def groups(self, key=AOKI):
        rubrics = self.meta["rubrics"]
        mapping = exam_bridge.rubric_mapping(rubrics, self.meta["criteria"])
        return exam_bridge.criterion_groups(
            self.result(key), rubrics, mapping, self.meta["questions"])

    def decide(self, letter, value, student=None):
        student = student or self.aoki
        group = next(g for g in self.groups(student.student_id)[0] if g["letter"] == letter)
        app._decide_exam_grade(student, self.asg, letter, value,
                               student.exam_results[EXAM], group["rubric_ids"], list("ABCD"))

    def grade(self, letter, student=None):
        return app.find_score(student or self.aoki, EXAM, letter)

    def exam_scores(self, student=None):
        student = student or self.aoki
        return [sc for bucket in student.scores.values() for sc in bucket
                if sc.assignment == EXAM]


class DialogColumn:
    def __init__(self, ui):
        self.ui = ui

    def caption(self, text):
        self.ui.captions.append(text)

    def checkbox(self, label, value=False, **kw):
        return self.ui.excused if label == "Excused" else value

    def button(self, label, **kw):
        return label == "Save"


class DialogStreamlit:
    """Just enough of Streamlit to open the grade pop-up and press Save."""

    class Rerun(Exception):
        pass

    def __init__(self, session_state, grade=None, comment=None, excused=False):
        self.session_state = session_state
        self.grade, self.comment, self.excused = grade, comment, excused
        self.markdowns = []
        self.captions = []
        self.expanders = []
        self.select = {}
        self.area = {}

    def markdown(self, text):
        self.markdowns.append(text)

    def caption(self, text):
        self.captions.append(text)

    def expander(self, label):
        self.expanders.append(label)
        return nullcontext()

    def columns(self, spec, **kw):
        return [DialogColumn(self) for _ in range(spec if isinstance(spec, int) else len(spec))]

    def selectbox(self, label, options, **kw):
        self.select = dict(kw, options=options)
        return self.grade

    def text_area(self, label, value="", **kw):
        self.area = dict(kw, value=value)
        return value if self.comment is None else self.comment

    def rerun(self):
        raise self.Rerun()


class _DialogBase(_DeckBase):
    def open_dialog(self, letter, student=None, **choices):
        """Open the pop-up, press Save with ``grade`` and ``comment``, return it."""
        student = student or self.aoki
        fake = DialogStreamlit(self.ss, **choices)
        with mock.patch.object(app, "st", fake):
            try:
                app.edit_grade_dialog.__wrapped__(student.student_id, EXAM, letter)
            except fake.Rerun:
                pass
        return fake


class AbsentStudentTests(_DialogBase):
    """A student with no paper counts 0 only where a classmate has a grade (D10)."""

    def setUp(self):
        super().setUp()
        self.absent = self.gb.get_or_create("100099")

    def zeros(self):
        return {c: len(app.missing_zero_points(self.absent, c)) for c in "ABCD"}

    def row(self):
        return next(r for r in app.assignment_table() if r["name"] == EXAM)

    def test_no_grade_yet_means_no_zero(self):
        self.assertEqual(self.zeros(), {"A": 0, "B": 0, "C": 0, "D": 0})

    def test_one_grade_brings_a_zero_on_that_criterion_only(self):
        self.decide("B", 5)
        self.assertEqual(self.zeros(), {"A": 0, "B": 1, "C": 0, "D": 0})
        self.assertEqual(app.zero_criteria(self.row()), ["B"])

    def test_each_criterion_joins_as_it_gets_its_first_grade(self):
        self.decide("B", 5)
        self.decide("D", 3, self.gb.students[BABA])
        self.assertEqual(self.zeros(), {"A": 0, "B": 1, "C": 0, "D": 1})

    def test_clearing_the_only_grade_takes_the_zero_away(self):
        self.decide("B", 5)
        self.decide("B", None)
        self.assertEqual(self.zeros(), {"A": 0, "B": 0, "C": 0, "D": 0})

    def test_an_excused_or_awaiting_student_still_has_no_zero(self):
        self.decide("B", 5)
        self.assertEqual(app.missing_zero_points(self.gb.students[BABA], "B"), [])
        self.ss["excused_flags"][app.excused_key(self.absent.student_id, EXAM)] = True
        self.assertEqual(self.zeros(), {"A": 0, "B": 0, "C": 0, "D": 0})

    def test_other_assignments_still_count_every_listed_criterion(self):
        row = {"criteria": "A,C", "is_exam": False}
        self.assertEqual(app.zero_criteria(row), ["A", "C"])

    def test_the_pop_up_doesnt_call_an_ungraded_criterion_missing(self):
        self.decide("B", 5)
        fake = self.open_dialog("C", self.absent, grade=None)
        self.assertIn("not graded yet", fake.markdowns[0])
        self.assertIsNone(fake.select["index"])
        self.assertIsNone(app.find_score(self.absent, EXAM, "C"))
        fake = self.open_dialog("B", self.absent, grade=0)
        self.assertIn("missing (counts as 0)", fake.markdowns[0])
        self.assertIsNone(app.find_score(self.absent, EXAM, "B"))

    def test_a_first_grade_can_be_entered_on_an_ungraded_criterion(self):
        self.open_dialog("C", self.absent, grade=0)
        self.assertEqual(app.find_score(self.absent, EXAM, "C").value, 0)
        self.assertEqual(self.asg.criteria, ["A", "B", "C", "D"])


class ExamCriteriaAreNotGradesTests(_DeckBase):
    """An exam lists its criteria from Sync, so that doesn't mean it has grades."""

    def test_an_ungraded_exam_doesnt_count_toward_the_auto_method(self):
        before = app.qualifying_assignment_count()
        self.decide("B", 5)
        self.assertEqual(app.qualifying_assignment_count(), before + 1)

    def test_a_remap_leaves_grades_that_are_named_as_still_counting(self):
        self.decide("B", 5)
        self.decide("D", 4)
        self.assertEqual(app._exam_orphan_letters(self.asg, {"r1": "A", "r2": "B", "r4": "D"}), [])
        self.assertEqual(app._exam_orphan_letters(self.asg, {"r1": "A"}), ["B", "D"])

    def test_a_grade_no_longer_valid_isnt_named(self):
        self.decide("B", 5)
        self.grade("B").is_valid = False
        self.assertEqual(app._exam_orphan_letters(self.asg, {}), [])

    def test_an_assignment_named_like_another_classs_exam_stays_in_the_evidence(self):
        self.gb.assignments[0].class_name = "Another class"
        self.gb.assignments.append(Assignment(name=EXAM, class_name=CLASS, criteria=["A"]))
        self.ss["active"][EXAM] = True
        self.aoki.scores[Criterion.A] = [CriterionScore(
            Criterion.A, 6, datetime(2026, 11, 1), assignment=EXAM, comment="Ordinary work.")]
        with mock.patch.object(app, "current_term_assignment_names", lambda: {EXAM}), \
                mock.patch.object(app, "assessment_exclusions_for", lambda sid: set()):
            evidence = app._current_term_evidence(self.aoki)
        self.assertEqual(len(evidence), 1)


class ReportRowTests(_DeckBase):
    """The report's marks table says the same as Window 3."""

    def rows(self, student):
        from docx import Document
        document = Document()
        self.ss.update(unit_plan=None, final_override={}, llm_response={})
        # Only the marks table is under test.
        stubs = {"_trend_png": lambda s: None, "student_email_for": lambda s: "",
                 "active_class_dict": lambda: {}, "subject_label": lambda: "",
                 "aggregate_with_policy": lambda s, c: None, "report_cfg": lambda: {},
                 "student_term_grades": lambda s: (0, 0, 0, None, None)}
        with mock.patch.multiple(app, **stubs):
            app._student_docx(document, student, "Weighted Median")
        return [[cell.text for cell in row.cells] for table in document.tables
                for row in table.rows if row.cells[0].text == EXAM]

    def test_a_paper_with_no_grade_is_awaiting_decision_with_no_zero(self):
        self.decide("B", 5)
        rows = self.rows(self.gb.students[BABA])
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][2], rows[0][4]), ("—", "awaiting decision"))

    def test_no_paper_shows_zero_only_where_a_classmate_has_a_grade(self):
        self.decide("B", 5)
        rows = self.rows(self.gb.get_or_create("100099"))
        self.assertEqual([(r[1], r[2], r[4]) for r in rows], [("B", "0", "missing = 0")])

    def test_excused_lists_every_criterion(self):
        self.decide("B", 5)
        absent = self.gb.get_or_create("100099")
        self.ss["excused_flags"][app.excused_key(absent.student_id, EXAM)] = True
        rows = self.rows(absent)
        self.assertEqual([r[1] for r in rows], list("ABCD"))
        self.assertTrue(all(r[4] == "excused" for r in rows))


class RemoveExamGradeTests(_DialogBase):
    def test_an_exam_grade_offers_no_grade(self):
        self.decide("B", 5)
        fake = self.open_dialog("B", grade=5)
        self.assertEqual(fake.select["options"][0], None)
        self.assertEqual(fake.select["options"][fake.select["index"]], 5)
        self.assertEqual(app._exam_grade_label(None), "No grade")

    def test_choosing_it_removes_only_that_grade(self):
        self.decide("B", 5)
        self.decide("D", 4)
        self.open_dialog("B", grade=None)
        self.assertIsNone(self.grade("B"))
        self.assertEqual(self.grade("D").value, 4)
        self.assertEqual(self.asg.score_count, 1)
        self.assertEqual(self.asg.criteria, ["A", "B", "C", "D"])

    def test_a_grade_on_a_criterion_no_longer_mapped_can_go(self):
        self.decide("B", 5)
        self.meta["criteria"]["r2"] = "—"
        self.open_dialog("B", grade=None)
        self.assertIsNone(self.grade("B"))
        self.assertEqual(self.asg.criteria, ["A", "C", "D"])

    def test_a_plain_marks_exam_keeps_its_criterion_when_the_last_grade_goes(self):
        self.meta["rubrics"] = []
        self.meta["criteria"] = {}
        app._write_exam_grade(self.aoki, self.asg, "A", 6, datetime(2026, 11, 1), "", "banded")
        app._refresh_exam_counts(self.asg, ["A"])
        paper = self.result()
        paper.mode = "marks"
        paper.total, paper.max_total = 2, 2
        paper.questions = {"Q1": 2}
        paper.levels = {}
        paper.counted = ["Q1"]
        self.asg.question_labels = ["Q1"]
        fake = self.open_dialog("A", grade=None)
        self.assertIn("Exam reference · 2/2", fake.expanders)
        self.assertIn("Q1", fake.captions)
        self.assertIn("2", fake.captions)
        self.assertIsNone(self.grade("A"))
        self.assertEqual(self.asg.criteria, ["A"])
        self.assertEqual(self.asg.score_count, 0)

    def test_it_returns_to_awaiting_when_it_was_the_last_one(self):
        self.decide("B", 5)
        self.open_dialog("B", grade=None)
        row = next(r for r in app.assignment_table() if r["name"] == EXAM)
        self.assertTrue(app.awaiting_exam_decision(self.aoki, row))

    def test_a_normal_assignment_offers_no_such_choice(self):
        self.assertEqual(app._exam_grade_label(3), "3")
        self.gb.assignments.append(Assignment(name="Plain", class_name=CLASS, criteria=["A"]))
        self.aoki.add_score(CriterionScore(Criterion.A, 4, datetime(2026, 11, 1), assignment="Plain"))
        fake = DialogStreamlit(self.ss, grade=4)
        with mock.patch.object(app, "st", fake):
            with self.assertRaises(fake.Rerun):
                app.edit_grade_dialog.__wrapped__(AOKI, "Plain", "A")
        self.assertEqual(fake.select["options"], list(range(9)))
        self.assertEqual(fake.select["index"], 4)


class PopUpCommentTests(_DialogBase):
    def setUp(self):
        super().setUp()
        self.result().comment = "Strong overall composition."
        self.ss.update(unit_plan=None, teacher_remarks={}, final_override={},
                       effort_by_term={}, report_cfg={})

    def in_term_comment(self):
        return app._exam_feedback_for(self.aoki)[0].overall

    def test_a_new_grade_starts_with_the_papers_comment(self):
        fake = self.open_dialog("B", grade=5)
        self.assertEqual(fake.area["value"], "Strong overall composition.")
        self.assertEqual(self.grade("B").comment, "Strong overall composition.")
        self.assertEqual(self.in_term_comment(), ["Strong overall composition"])

    def test_clearing_the_box_is_still_respected(self):
        self.open_dialog("B", grade=5, comment="")
        self.assertEqual(self.grade("B").comment, "")
        self.assertEqual(app._exam_feedback_for(self.aoki), [])

    def test_an_edit_is_what_goes_in(self):
        self.open_dialog("B", grade=5, comment="My own words.")
        self.assertEqual(self.in_term_comment(), ["My own words"])

    def test_an_existing_grade_keeps_its_own_comment(self):
        self.decide("B", 5)
        self.grade("B").comment = "Edited before."
        fake = self.open_dialog("B", grade=5)
        self.assertEqual(fake.area["value"], "Edited before.")


class GroupingTests(_DeckBase):
    def test_levels_group_under_their_criterion(self):
        groups, unmapped = self.groups()
        self.assertEqual([g["letter"] for g in groups], ["A", "B", "C", "D"])
        self.assertEqual(unmapped, [])
        b = groups[1]["rubrics"][0]
        self.assertEqual(b["items"], ["Screen 01: 4", "Screen 02: 4", "Screen 03: 4",
                                      "Screen 06: 4", "Screen 07: 4"])
        self.assertEqual([len(g["rubrics"][0]["items"]) for g in groups], [1, 5, 2, 5])

    def test_a_screen_on_two_criteria_shows_under_both(self):
        groups, _ = self.groups()
        self.assertIn("Screen 09: 6", groups[2]["rubrics"][0]["items"])
        self.assertIn("Screen 09: 3", groups[3]["rubrics"][0]["items"])

    def test_criteria_arrive_from_cam2(self):
        self.assertEqual(self.asg.criteria, ["A", "B", "C", "D"])

    def test_sync_records_each_questions_rubrics(self):
        self.assertEqual(self.meta["questions"]["Screen 09"], {"rubrics": ["r3", "r4"], "max": 0})

    def test_a_question_not_answered_shows_under_its_own_criterion(self):
        session, config, grades = self.storage.open_session(self.folder)
        self.gs.set_grade(config, grades, "s001", "q05", "not_answered", rubric_id="r1")
        session.grades_file.save(grades)
        self.sync()
        groups, _ = self.groups()
        self.assertEqual(groups[0]["rubrics"][0]["items"], ["Screen 05: not answered"])
        self.assertNotIn("Screen 05: not answered", groups[1]["rubrics"][0]["items"])

    def test_a_chosen_mapping_beats_the_name_and_a_dash_unmaps(self):
        rubrics = [{"id": "r1", "name": "Criterion A"}, {"id": "r2", "name": "Effort"},
                   {"id": "r3", "name": "Criterion C"}]
        self.assertEqual(exam_bridge.rubric_mapping(rubrics), {"r1": "A", "r3": "C"})
        self.assertEqual(exam_bridge.rubric_mapping(rubrics, {"r1": "B", "r3": "—", "r2": "D"}),
                         {"r1": "B", "r2": "D"})

    def paper(self, **kw):
        return ExamResult(assignment=EXAM, mode="mixed", **kw)

    def test_a_rubric_that_doesnt_go_to_8_is_listed_as_given(self):
        result = self.paper(levels={"S1": {"r1": 5}}, final_levels={"r1": 3})
        groups, _ = exam_bridge.criterion_groups(
            result, [{"id": "r1", "name": "Criterion A", "max": 6}], {"r1": "A"},
            {"S1": {"rubrics": ["r1"], "max": 0}})
        row = groups[0]["rubrics"][0]
        self.assertEqual(row["items"], ["S1: 5/6"])
        self.assertEqual((row["final"], row["band"]), (3, 4))

    def test_not_answered_and_not_counted_stay_visible(self):
        result = self.paper(levels={"S1": {"r1": 5}, "S2": {"r1": 4}}, not_answered=["S3"],
                            counted=["S1", "S3"])
        questions = {label: {"rubrics": ["r1"], "max": 0} for label in ("S1", "S2", "S3", "S4")}
        groups, _ = exam_bridge.criterion_groups(
            result, [{"id": "r1", "name": "Criterion A", "max": 8}], {"r1": "A"}, questions)
        self.assertEqual(groups[0]["rubrics"][0]["items"],
                         ["S1: 5", "S2: 4 (not counted)", "S3: not answered", "S4: —"])

    def test_marks_ticked_on_a_criterion_sit_beside_its_levels(self):
        marks = {"total": 8, "max": 10, "percent": 80.0}
        result = self.paper(levels={"S1": {"r1": 5}}, questions={"Q2": 8},
                            criterion_marks={"r1": marks})
        questions = {"S1": {"rubrics": ["r1"], "max": 0}, "Q2": {"rubrics": ["r1"], "max": 10}}
        groups, _ = exam_bridge.criterion_groups(
            result, [{"id": "r1", "name": "Criterion A", "max": 8}], {"r1": "A"}, questions)
        row = groups[0]["rubrics"][0]
        self.assertEqual(row["items"], ["S1: 5", "Q2: 8/10"])
        self.assertEqual(row["marks"], marks)

    def test_several_rubrics_share_one_group(self):
        result = self.paper(levels={"S1": {"r1": 5, "r2": 3}})
        rubrics = [{"id": "r1", "name": "Ideas", "max": 8}, {"id": "r2", "name": "Skills", "max": 8}]
        groups, _ = exam_bridge.criterion_groups(
            result, rubrics, {"r1": "B", "r2": "B"}, {"S1": {"rubrics": ["r1", "r2"], "max": 0}})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["rubric_ids"], ["r1", "r2"])

    def test_an_unmapped_rubric_is_listed_apart_only_if_it_has_something(self):
        result = self.paper(levels={"S1": {"r1": 5}})
        rubrics = [{"id": "r1", "name": "Effort", "max": 8}, {"id": "r2", "name": "Spare", "max": 8}]
        questions = {"S1": {"rubrics": ["r1"], "max": 0}, "S2": {"rubrics": ["r2"], "max": 0}}
        groups, unmapped = exam_bridge.criterion_groups(result, rubrics, {}, questions)
        self.assertEqual(groups, [])
        self.assertEqual([row["name"] for row in unmapped], ["Effort"])

    def test_it_works_before_a_resync_records_the_questions(self):
        result = self.paper(levels={"S1": {"r1": 5}})
        groups, _ = exam_bridge.criterion_groups(
            result, [{"id": "r1", "name": "Criterion A", "max": 8}], {"r1": "A"})
        self.assertEqual(groups[0]["rubrics"][0]["items"], ["S1: 5"])


class DecisionTests(_DeckBase):
    def test_a_decision_writes_the_one_grade_and_keeps_things_in_step(self):
        self.decide("B", 5)
        sc = self.grade("B")
        self.assertEqual((sc.value, sc.exam_value), (5, None))
        self.assertEqual(sc.exam_basis, exam_bridge.exam_basis(self.result(), ["r2"]))
        self.assertEqual(self.asg.score_count, 1)
        self.assertEqual(self.asg.criteria, ["A", "B", "C", "D"])

    def test_changing_it_keeps_one_grade(self):
        self.decide("B", 5)
        self.decide("B", 6)
        self.decide("B", 2)
        self.assertEqual([sc.value for sc in self.exam_scores()], [2])
        self.assertEqual(self.asg.score_count, 1)

    def test_blank_clears_only_that_criterion(self):
        self.decide("B", 5)
        self.decide("D", 4)
        self.decide("B", None)
        self.assertIsNone(self.grade("B"))
        self.assertEqual(self.grade("D").value, 4)
        self.assertEqual(self.asg.score_count, 1)

    def test_blank_with_nothing_there_writes_nothing(self):
        self.decide("B", None)
        self.assertEqual(self.exam_scores(), [])

    def test_a_decision_copies_the_overall_comment_and_keeps_an_edit(self):
        self.result().comment = "Overall from CAM2"
        self.decide("B", 5)
        self.assertEqual(self.grade("B").comment, "Overall from CAM2")
        self.grade("B").comment = "edited"
        self.decide("B", 6)
        self.assertEqual(self.grade("B").comment, "edited")

    def test_a_re_send_cant_change_a_decision(self):
        self.decide("B", 5)
        session, _config, grades = self.storage.open_session(self.folder)
        grades.setdefault("overall", {}).setdefault("s001", {})["final_levels"] = {"r2": 7}
        session.grades_file.save(grades)
        self.sync()
        self.assertEqual(self.result().final_levels["r2"], 7)
        self.assertEqual(self.grade("B").value, 5)
        plan = app._final_level_plan(self.asg, {"r2": "B"}, app._exam_results_for(EXAM))
        self.assertEqual([(row["current"], row["sent"]) for row in plan["keep"]], [(5, 7)])
        app._apply_exam_rubric_levels(self.asg, {"r2": "B"}, app._exam_results_for(EXAM))
        self.assertEqual(self.grade("B").value, 5)

    def test_a_grade_cam2_sent_becomes_the_teachers_once_changed_here(self):
        self.result().final_levels["r2"] = 6
        app._apply_exam_rubric_levels(self.asg, {"r2": "B"}, app._exam_results_for(EXAM))
        self.assertEqual(self.grade("B").exam_value, 6)
        self.decide("B", 6)     # the same value, but the teacher chose it here
        self.assertIsNone(self.grade("B").exam_value)
        self.result().final_levels["r2"] = 8
        app._apply_exam_rubric_levels(self.asg, {"r2": "B"}, app._exam_results_for(EXAM))
        self.assertEqual(self.grade("B").value, 6)


class DeckCountsOnceTests(_DeckBase):
    def test_levels_alone_write_no_grade(self):
        self.assertEqual(self.exam_scores(), [])
        self.assertEqual(self.asg.score_count, 0)

    def test_at_most_one_grade_per_criterion_on_twelve_screens(self):
        for letter, value in self.LEVELS.items():
            self.decide(letter, value)
            self.decide(letter, value)
        self.assertEqual(sorted(sc.criterion.value for sc in self.exam_scores()), list("ABCD"))
        self.assertEqual(self.asg.score_count, 4)

    def test_the_calculated_grade_doesnt_depend_on_how_many_slides_fed_it(self):
        # One grade on B from five slide levels, against one from a single task.
        when = datetime(2026, 11, 1)
        with mock.patch.object(app, "calculation_method", lambda sid: "Weighted Median"):
            self.decide("B", 4)
            baba = self.gb.students[BABA]
            baba.add_score(CriterionScore(Criterion.B, 4, when, assignment=EXAM))
            self.assertEqual(len([sc for sc in self.aoki.scores[Criterion.B]]), 1)
            mine = app.aggregate_with_policy(self.aoki, "B")
            theirs = app.aggregate_with_policy(baba, "B")
        self.assertEqual(mine.n, 1)
        self.assertEqual(mine.rounded_band, theirs.rounded_band)
        self.assertEqual(mine.rounded_band, 4)


class Window3GroupTests(_DeckBase):
    """The group as rendered, with the dropdown driven through session state."""

    def render(self, choice=..., letter="B", key=AOKI, pressed=None):
        student = self.gb.students[key]
        group = next(g for g in self.groups(key)[0] if g["letter"] == letter)
        ui = FakeStreamlit(self.ss)
        ui.pressed = pressed
        widget = f"decide_{EXAM}_{key}_{letter}"
        result = student.exam_results[EXAM]

        def seed(k, value):
            app_seed(k, value)
            if choice is not ...:
                self.ss[widget] = choice

        app_seed = app._seed_dropdown
        with mock.patch.object(app, "st", ui), mock.patch.object(app, "_seed_dropdown", seed):
            try:
                app._render_criterion_group(self.asg, student, result, group, list("ABCD"))
            except ui.Rerun:
                ui.reran = True
        return ui

    def text(self, ui):
        return "\n".join(ui.captions)

    def test_blank_is_the_starting_point_and_writes_nothing(self):
        ui = self.render()
        self.assertEqual(self.exam_scores(), [])
        self.assertIn("Screen 01: 4 · Screen 02: 4", self.text(ui))
        self.assertIn("Awaiting your decision", self.text(ui))
        select = ui.selects[f"decide_{EXAM}_{AOKI}_B"]
        self.assertIsNone(select["index"])
        self.assertFalse(select["disabled"])

    def test_no_average_or_suggestion_beside_the_dropdown(self):
        # B's levels are all 4, so a suggestion would have to say so as a figure
        # of its own; the only numbers are the screens' levels and labels.
        text = self.text(self.render())
        for word in ("average", "suggest", "mean", "4.0"):
            self.assertNotIn(word, text.lower())

    def test_choosing_a_level_writes_it(self):
        self.render(choice=7)
        self.assertEqual(self.grade("B").value, 7)

    def test_choosing_blank_clears_it(self):
        self.decide("B", 5)
        self.render(choice=None)
        self.assertIsNone(self.grade("B"))

    def test_an_unfinished_paper_shows_its_levels_and_cant_be_decided(self):
        self.result().complete = False
        ui = self.render(choice=7)
        self.assertEqual(self.exam_scores(), [])
        self.assertIn("Screen 01: 4", self.text(ui))
        self.assertIn("Not finished in CAM2", self.text(ui))
        self.assertTrue(ui.selects[f"decide_{EXAM}_{AOKI}_B"]["disabled"])

    def test_a_typed_final_is_labelled_and_written_by_nothing_here(self):
        self.result().final_levels["r2"] = 6
        ui = self.render()
        self.assertIn("CAM2 final level: 6", self.text(ui))
        self.assertIsNone(self.grade("B"))

    def test_an_applied_final_is_labelled_as_from_cam2(self):
        self.result().final_levels["r2"] = 6
        app._apply_exam_rubric_levels(self.asg, {"r2": "B"}, app._exam_results_for(EXAM))
        self.assertIn("From CAM2", self.text(self.render()))

    def test_two_finals_on_one_criterion_show_both_and_write_neither(self):
        self.meta["criteria"] = {"r1": "B", "r2": "B"}
        self.result().final_levels.update(r1=5, r2=6)
        text = self.text(self.render())
        self.assertIn("Two final levels", text)
        self.assertIn("Criterion A 5", text)
        self.assertIn("Criterion B 6", text)
        self.assertIsNone(self.grade("B"))

    def change_a_level(self, value=1):
        session, config, grades = self.storage.open_session(self.folder)
        self.gs.set_grade(config, grades, "s001", "q01", value, rubric_id="r2")
        session.grades_file.save(grades)
        self.sync()

    def test_levels_changed_flag_shows_and_the_decision_stays(self):
        self.decide("B", 5)
        self.assertNotIn("Levels changed", self.text(self.render()))
        self.change_a_level()
        self.assertIn("Levels changed", self.text(self.render()))
        self.assertEqual(self.grade("B").value, 5)

    def test_the_flag_ignores_another_criterions_levels(self):
        self.decide("A", 5)
        self.change_a_level()
        self.assertNotIn("Levels changed", self.text(self.render(letter="A")))

    def test_keep_grade_settles_the_flag(self):
        self.decide("B", 5)
        self.change_a_level()
        self.render(pressed=f"decide_{EXAM}_{AOKI}_B_keep")
        self.assertNotIn("Levels changed", self.text(self.render()))
        self.assertEqual(self.grade("B").value, 5)


class Window1Tests(_DeckBase):
    def plan(self, mapping=None):
        return app._final_level_plan(self.asg, mapping or {"r1": "A", "r2": "B"},
                                     app._exam_results_for(EXAM))

    def test_summary_describes_without_changing_anything(self):
        self.result().final_levels["r1"] = 6
        plan = self.plan()
        self.assertEqual(len(plan["fill"]), 1)
        self.assertEqual(self.exam_scores(), [])

    def test_no_typed_finals_means_nothing_to_apply(self):
        plan = self.plan()
        self.assertFalse(any(plan[k] for k in ("fill", "update", "same", "keep", "both")))
        self.assertEqual(app._apply_exam_rubric_levels(
            self.asg, {"r1": "A"}, app._exam_results_for(EXAM)), 0)
        self.assertEqual(self.exam_scores(), [])

    def test_two_finals_on_one_criterion_are_reported_and_not_written(self):
        self.result().final_levels.update(r1=5, r2=6)
        plan = self.plan({"r1": "B", "r2": "B"})
        self.assertEqual([row["letter"] for row in plan["both"] if row["student"] is self.aoki],
                         ["B"])
        app._apply_exam_rubric_levels(self.asg, {"r1": "B", "r2": "B"}, app._exam_results_for(EXAM))
        self.assertIsNone(self.grade("B"))

    def test_routing_comes_from_the_mode_and_criterion_marks(self):
        uses = app._exam_uses_criteria
        paper = ExamResult
        self.assertTrue(uses(self.asg, [(None, paper(assignment=EXAM, mode="rubric"))]))
        self.assertTrue(uses(self.asg, [(None, paper(assignment=EXAM, mode="mixed"))]))
        self.assertTrue(uses(self.asg, [(None, paper(
            assignment=EXAM, mode="marks", criterion_marks={"r1": {"total": 1, "max": 2}}))]))
        self.assertFalse(uses(self.asg, [(None, paper(assignment=EXAM, mode="marks"))]))


class PlainMarksExamTests(_AppBase):
    def setUp(self):
        super().setUp()
        self.hosted(self.marks_session)
        self.sync()
        self.asg = self.gb.assignments[0]
        self.results = app._exam_results_for(EXAM)

    def test_blank_dropdowns_write_nothing(self):
        self.assertEqual(app._apply_exam_bands(self.asg, "A", self.results), 0)
        self.assertEqual(self.asg.score_count, 0)
        self.assertEqual(self.gb.students[AOKI].scores.get(Criterion.A, []), [])

    def test_only_the_chosen_student_gets_a_grade(self):
        self.ss[f"band_{EXAM}_{AOKI}"] = 5
        self.assertEqual(app._apply_exam_bands(self.asg, "A", self.results), 1)
        self.assertEqual(self.gb.students[BABA].scores.get(Criterion.A, []), [])

    def test_marks_never_suggest_a_grade(self):
        self.assertFalse(hasattr(ExamResult(assignment=EXAM), "suggested_band"))
        self.assertNotIn("suggested_band", Path(app.__file__).read_text(encoding="utf-8"))

    def test_weighted_text_shows_cam2s_result_beside_the_raw_total(self):
        paper = ExamResult(assignment=EXAM, total=10, max_total=50, percent=50.0, weighted=True)
        self.assertEqual(app._exam_marks_text(self.asg, paper), "weighted 50.0% · raw 10/50")
        paper.weighted = False
        self.assertEqual(app._exam_marks_text(self.asg, paper), "10/50")


class AddAssignmentTests(unittest.TestCase):
    def test_type_is_assignment_or_exam_with_a_draft_check_mark(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        self.assertIn('st.radio("Type", ["Assignment", "Exam"]', source)
        self.assertIn('st.checkbox("Draft — comments only", key="add_asg_draft"', source)
        self.assertIn("is_draft = bool(draft) and not is_exam", source)


class SourceLimitTests(unittest.TestCase):
    def q(self, n, prefix="Q", size=300):
        return [(f"{prefix}{i}", "x" * size) for i in range(1, n + 1)]

    def test_under_the_limit_everything_stays(self):
        exams = [ExamFeedback("E", ["overall"], self.q(3))]
        kept, left_out = limit_feedback(exams)
        self.assertEqual(left_out, 0)
        self.assertEqual(kept[0].questions, exams[0].questions)

    def test_exams_may_use_what_drafts_and_assignments_leave(self):
        self.assertEqual(exam_feedback.exam_allowance(0), 6000)
        self.assertEqual(exam_feedback.exam_allowance(500), 5500)
        self.assertEqual(exam_feedback.exam_allowance(2000), 4000)
        self.assertEqual(exam_feedback.exam_allowance(3000), 4000)

    def test_two_full_exams_lose_whole_question_comments_evenly(self):
        exams = [ExamFeedback("One", ["o" * 600], self.q(15)),
                 ExamFeedback("Two", ["t" * 600], self.q(15))]
        kept, left_out = limit_feedback(exams, other_characters=2000)
        self.assertGreater(left_out, 0)
        self.assertLessEqual(abs(len(kept[0].questions) - len(kept[1].questions)), 1)
        self.assertEqual(30 - sum(len(e.questions) for e in kept), left_out)
        self.assertLessEqual(sum(e.characters for e in kept), 4000)
        for exam in kept:
            self.assertEqual(exam.overall, [exam.overall[0][0] * 600])
            self.assertTrue(all(len(text) == 300 for _, text in exam.questions))

    def test_earlier_questions_stay(self):
        kept, _ = limit_feedback([ExamFeedback("E", [], self.q(30))])
        self.assertEqual([label for label, _ in kept[0].questions],
                         [f"Q{i}" for i in range(1, 21)])

    def test_overall_comments_stay_whole_even_over_the_limit(self):
        exams = [ExamFeedback(f"E{i}", ["o" * 2000], self.q(2)) for i in range(4)]
        kept, left_out = limit_feedback(exams)
        self.assertEqual(left_out, 8)
        self.assertTrue(all(len(e.overall[0]) == 2000 for e in kept))

    def test_it_counts_characters_so_japanese_counts_properly(self):
        exams = [ExamFeedback("E", [], [("Q1", "あ" * 4000), ("Q2", "い" * 2001)])]
        kept, left_out = limit_feedback(exams)
        self.assertEqual(left_out, 1)
        self.assertEqual([label for label, _ in kept[0].questions], ["Q1"])

    def test_inputs_are_unchanged(self):
        exams = [ExamFeedback("E", [], self.q(30))]
        limit_feedback(exams)
        self.assertEqual(len(exams[0].questions), 30)

    def test_lines_have_no_quotation_marks(self):
        lines = feedback_lines([ExamFeedback("Mid", ["good"], [("Q1", "better")])])
        self.assertEqual(lines, ["Mid, overall: good", "Mid, Q1: better"])


class _PromptBase(_DeckBase):
    CFG = {"name_mode": "first", "word_limit": 100, "provider": "Claude",
           "inc_strengths": True, "n_strengths": 2,
           "inc_growth": True, "n_growth": 2, "inc_trend": False, "inc_late": False,
           "inc_missing": False}

    def setUp(self):
        super().setUp()
        self.ss.update(unit_plan=None, teacher_remarks={}, final_override={},
                       effort_by_term={}, report_cfg={})
        self.patchers = [
            mock.patch.object(app, "pronouns_for", lambda s: "they/them"),
            mock.patch.object(app, "active_subject", lambda: "Visual Arts"),
            mock.patch.object(app, "active_myp_year", lambda: ""),
            mock.patch.object(app, "active_class_dict", lambda: {}),
            mock.patch.object(app, "first_name_for", lambda s: "Aoki"),
            mock.patch.object(app, "calculation_method", lambda sid: "Weighted Median"),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.result().comment = "Strong overall composition."
        self.result().question_comments["Screen 01"] = "Clear thesis on the painting."

    def prompt(self, student=None):
        return app.compile_prompt(student or self.aoki, dict(self.CFG))

    def block(self, student=None):
        text = self.prompt(student)
        start = text.find("[CURRENT TERM — EXAM FEEDBACK]")
        if start < 0:
            return ""
        end = text.find("\n\n[", start + 1)
        return text[start:end if end > 0 else len(text)]


class ExamCommentTests(_PromptBase):
    def test_in_the_prompt_before_any_grade_is_decided(self):
        self.assertEqual(self.exam_scores(), [])
        block = self.block()
        self.assertIn("Strong overall composition", block)
        self.assertIn("Screen 01: Clear thesis on the painting", block)

    def test_in_the_prompt_whatever_the_grades(self):
        for value in (0, 8):
            self.decide("B", value)
            block = self.block()
            self.assertIn("Strong overall composition", block)
            self.assertIn("Clear thesis", block)

    def test_an_unfinished_papers_comments_go_in_too(self):
        self.result().complete = False
        self.assertIn("Clear thesis", self.block())

    def test_an_excused_exam_stays_out(self):
        self.ss["excused_flags"][app.excused_key(AOKI, EXAM)] = True
        self.assertEqual(self.block(), "")
        self.assertNotIn("Clear thesis", self.prompt())

    def test_a_comment_on_a_question_not_counted_stays_out(self):
        self.result().counted = ["Screen 02"]
        self.assertNotIn("Clear thesis", self.block())

    def test_a_comment_on_a_question_not_graded_yet_goes_in(self):
        # It's missing from "counted" because it has no level yet, not because a
        # choice group left it out, and the teacher sent that comment (P12).
        self.result().counted = ["Screen 02"]
        self.result().complete = False
        del self.result().levels["Screen 01"]
        self.assertIn("Clear thesis", self.block())

    def test_an_edited_comment_is_what_goes_in(self):
        self.decide("B", 5)
        self.grade("B").comment = "Edited in Window 3."
        block = self.block()
        self.assertIn("Edited in Window 3", block)
        self.assertNotIn("Strong overall composition", block)

    def test_a_cleared_comment_goes_nowhere(self):
        self.decide("B", 5)
        self.grade("B").comment = ""
        self.assertNotIn("Strong overall composition", self.block())
        self.assertIn("Clear thesis", self.block())

    def test_different_edits_each_go_in_once(self):
        self.decide("A", 5)
        self.decide("B", 5)
        self.decide("C", 5)
        self.grade("B").comment = "Edited."
        block = self.block()
        self.assertEqual(block.count("Strong overall composition"), 1)
        self.assertEqual(block.count("Edited"), 1)

    def test_four_criteria_send_the_overall_comment_once_and_take_no_place(self):
        for letter in "ABCD":
            self.decide(letter, 7)
        self.assertEqual(self.prompt().count("Strong overall composition"), 1)
        self.assertEqual(app._current_term_evidence(self.aoki), [])
        material = app._prompt_material(self.aoki, self.CFG)
        self.assertEqual((material["strengths"], material["growths"]), ([], []))

    def test_assignments_keep_the_strength_and_growth_places(self):
        for letter in "ABCD":
            self.decide(letter, 8)
        self.gb.assignments.append(Assignment(name="Task", class_name=CLASS, criteria=["A"]))
        self.ss["active"]["Task"] = True
        self.aoki.add_score(CriterionScore(Criterion.A, 3, datetime(2026, 11, 1),
                                           assignment="Task", comment="Needs more depth"))
        material = app._prompt_material(self.aoki, self.CFG)
        self.assertEqual([e.assignment for e in material["strengths"]], ["Task"])

    def test_exam_grades_still_count_in_the_criterion_results(self):
        self.decide("B", 7)
        self.assertIn("B Developing: grade 7", self.prompt())

    def test_no_levels_or_grades_in_the_block(self):
        self.decide("B", 7)
        self.result().final_levels["r2"] = 7
        block = self.block()
        for line in block.splitlines():
            if line.startswith("  - "):
                self.assertNotRegex(line, r"\b[0-8]\b(?! )|grade|level")

    def test_with_an_exam_block_the_word_limit_is_a_ceiling(self):
        self.assertIn("Use up to about 100 words, and fewer when", self.prompt())

    def test_with_no_exam_block_the_word_limit_reads_as_before(self):
        self.ss["excused_flags"][app.excused_key(AOKI, EXAM)] = True
        self.assertIn("Keep it to about 100 words, warm and professional", self.prompt())

    def test_the_closing_instruction_allows_the_exam_block(self):
        # It lists what the comment may draw on, and must not rule the block out.
        self.assertRegex(self.prompt(), r"Base the narrative ONLY on [^.]*exam feedback")

    def test_the_block_asks_for_a_summary_and_no_quotation_marks_on_the_comments(self):
        block = self.block()
        self.assertIn("main source", block)
        self.assertIn("own words", block)
        self.assertIn("no run of five or more words", block)
        self.assertIn("shorter comment", block)
        self.assertNotIn("“", block)

    def test_over_the_limit_keeps_overall_and_reports_the_number(self):
        labels = [f"Screen {i:02}" for i in range(1, 13)]
        for label in labels:
            self.result().question_comments[label] = "c" * 500
        material = app._prompt_material(self.aoki, self.CFG)
        self.assertGreater(material["left_out"], 0)
        block = self.block()
        self.assertIn("Strong overall composition", block)
        self.assertEqual(block.count("c" * 500), 12 - material["left_out"])
        self.assertNotIn("c" * 501, block)

    def test_a_manual_exam_with_grades_and_no_result_still_sends_its_comment(self):
        self.gb.assignments.append(Assignment(name="Manual", class_name=CLASS, criteria=["A"],
                                              is_exam=True))
        self.ss["active"]["Manual"] = True
        self.aoki.add_score(CriterionScore(Criterion.A, 5, datetime(2026, 11, 1),
                                           assignment="Manual", comment="Typed by hand"))
        self.assertIn("Manual, overall: Typed by hand", self.block())


class ResendCommentTests(_DeckBase):
    def setUp(self):
        super().setUp()
        self.ss["unit_plans"] = {}

    def resend(self, comment):
        session, _config, grades = self.storage.open_session(self.folder)
        grades.setdefault("overall", {}).setdefault("s001", {})["comment"] = comment
        session.grades_file.save(grades)
        app.sync_exam(CLASS, EXAM)

    def test_a_re_sent_comment_replaces_a_copy_not_edited(self):
        self.resend("First")
        self.decide("A", 5)
        self.decide("B", 5)
        self.resend("Corrected")
        self.assertEqual(self.grade("A").comment, "Corrected")
        self.assertEqual(self.grade("B").comment, "Corrected")

    def test_an_edited_copy_is_kept(self):
        self.resend("First")
        self.decide("A", 5)
        self.decide("B", 5)
        self.grade("A").comment = "Edited"
        self.resend("Corrected")
        self.assertEqual(self.grade("A").comment, "Edited")
        self.assertEqual(self.grade("B").comment, "Corrected")

    def test_a_cleared_copy_stays_clear(self):
        self.resend("First")
        self.decide("A", 5)
        self.grade("A").comment = ""
        self.resend("Corrected")
        self.assertEqual(self.grade("A").comment, "")

    def test_cam2_comment_clear_survives_the_cloud_mirror(self):
        self.resend("Original exam comment.")
        self.decide("A", 5)
        self.decide("B", 4)
        self.grade("B").comment = "Edited in CAM."
        app.save_class_mirror(self.class_dir, CLASS, {
            "score_comments": {EXAM: {AOKI: {
                "A": self.grade("A").comment, "B": self.grade("B").comment,
            }}},
        })

        self.resend("")

        self.assertEqual(self.result().comment, "")
        self.assertEqual(self.grade("A").comment, "")
        self.assertEqual(self.grade("A").value, 5)
        self.assertEqual(self.grade("B").value, 4)
        self.assertEqual(app._exam_feedback_for(self.aoki), [
            ExamFeedback(EXAM, ["Edited in CAM"]),
        ])

    def test_a_re_send_changes_no_grade(self):
        self.resend("First")
        self.decide("A", 5)
        self.resend("Corrected")
        self.assertEqual(self.grade("A").value, 5)

    def test_another_exams_comment_is_left_alone(self):
        self.resend("First")
        self.decide("A", 5)
        self.aoki.add_score(CriterionScore(Criterion.A, 2, datetime(2026, 11, 1),
                                           assignment="Other", comment="First"))
        self.resend("Corrected")
        self.assertEqual(app.find_score(self.aoki, "Other", "A").comment, "First")


if __name__ == "__main__":
    unittest.main()
