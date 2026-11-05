"""CAM2 engine upgrade, Phase 2 — Apply, the bridge and storage on the current pin.

Covers docs/CAM2_ENGINE_UPGRADE_PLAN.md Phase 2:

  * I2: Apply replaces a grade only on a criterion with a new decision, the marks
    panel leaves other criteria alone, and ``score_count`` counts real grades.
  * The re-send rule, which runs at Apply and never at Sync.
  * Nothing ever writes a second grade for one student, exam and criterion.
  * I3 and §3.1: each question is read by its own shape. Rows that need a
    version 2 session skip until ``model.VERSION >= 2``, then run from Phase 4.
  * Optional fields load and save without changing older records, and
    ``_validate_exam_result`` rejects non-string keys.
  * P6: the record of what a decision saw.
  * I13: a student with a result and no grade is awaiting a decision, not 0.

Sessions are fictional, built with CAM2's own engine in temp folders.

Run:  python -m unittest tests.test_exam_upgrade_phase2
"""

import hashlib
import os
import sys
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import app  # noqa: E402
from engine import Criterion, exam_bridge  # noqa: E402
from engine.models import CriterionScore, ExamResult  # noqa: E402
from engine.persistence import (  # noqa: E402
    _score_from_dict,
    _score_to_dict,
    _validate_exam_result,
    exam_result_from_dict,
    exam_result_to_dict,
)
from test_exam_bridge import _questions, _SessionBase  # noqa: E402
from test_exam_cam2_host import CLASS, EXAM, _AppBase  # noqa: E402

MAPPING = {"r1": "A", "r2": "C"}
AOKI, BABA, CHIBA = "100001", "100002", "100003"
ROSTER = [{"id": "n001", "name": "Aoki Ren", "external_id": AOKI},
          {"id": "n002", "name": "Baba Mio", "external_id": BABA}]
STUDENTS = [("s001", "Aoki.pdf", "n001"), ("s002", "Baba.pdf", "n002")]

needs_version_2 = unittest.skipUnless(
    exam_bridge.cam2_module("model").VERSION >= 2,
    "needs a version 2 session: runs from Phase 4")


def _folder_hash(folder):
    digest = hashlib.sha256()
    for root, dirs, files in os.walk(folder):
        dirs.sort()
        for name in sorted(files):
            with open(os.path.join(root, name), "rb") as fh:
                digest.update(name.encode() + fh.read())
    return digest.hexdigest()


class _GradeBase(_AppBase):
    """A rubric exam read into CAM, plus what Window 1's panel would do."""

    def setUp(self):
        super().setUp()
        self.gb.get_or_create(AOKI)
        # Typed final levels, so these tests hold on the pin, which also gives
        # suggested ones, and from Phase 4, when only typed ones arrive.
        self.folder = self.hosted(
            self.rubric_session, overall={"s001": {"final_levels": {"r1": 6, "r2": 3}}})
        self.sync()
        self.asg = self.gb.assignments[0]

    def aoki(self):
        return self.gb.students[AOKI]

    def result(self, key=AOKI):
        return self.gb.students[key].exam_results[EXAM]

    def apply(self, mapping=MAPPING, kept=None):
        results = app._exam_results_for(EXAM)
        if kept is not None:
            kept.extend((row["student"], row["letter"], row["current"], row["sent"])
                        for row in app._final_level_plan(self.asg, mapping, results)["keep"])
        return app._apply_exam_rubric_levels(self.asg, mapping, results)

    def grades(self, key=AOKI):
        student = self.gb.students[key]
        return {Criterion(c).value: [sc.value for sc in bucket if sc.assignment == EXAM]
                for c, bucket in student.scores.items()
                if any(sc.assignment == EXAM for sc in bucket)}

    def assert_one_grade_each(self):
        counts = Counter((s.student_id, sc.assignment, sc.criterion.value)
                         for s, sc in app.all_scores())
        self.assertEqual([k for k, n in counts.items() if n > 1], [])


class ApplyKeepsGradesTests(_GradeBase):
    """The I2 table, kept as a test."""

    def test_i2_reproduction_keeps_both_grades(self):
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.grades(), {"A": [6], "C": [6]})
        # What a re-send gives on the new engine: only C has a typed final level.
        del self.result().final_levels["r1"]
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.grades(), {"A": [6], "C": [6]})

    def test_no_final_levels_leaves_grades_and_the_count(self):
        self.apply()
        self.assertEqual(self.asg.score_count, 2)
        self.result().final_levels.clear()
        self.assertEqual(self.apply(), 0)
        self.assertEqual(self.grades(), {"A": [6], "C": [6]})
        self.assertEqual(self.asg.score_count, 2)
        self.assertEqual(self.asg.criteria, ["A", "C"])

    def test_unmapping_a_rubric_keeps_its_criterion_and_grade(self):
        self.apply()
        self.apply({"r2": "C"})
        self.assertEqual(self.grades(), {"A": [6], "C": [6]})
        self.assertEqual(self.asg.criteria, ["A", "C"])

    def test_count_is_grades_not_students(self):
        self.apply()
        self.assertEqual(self.asg.score_count, 2)

    def test_unfinished_paper_is_still_held_back(self):
        self.apply()
        self.assertFalse(self.result(BABA).complete)
        self.assertEqual(self.grades(BABA), {})


class MarksPanelTests(_AppBase):
    def setUp(self):
        super().setUp()
        self.hosted(self.marks_session)
        self.sync()
        self.asg = self.gb.assignments[0]
        self.results = app._exam_results_for(EXAM)

    def band(self, value, letter):
        for s, _r in self.results:
            self.ss[f"band_{EXAM}_{s.student_id}"] = value
        return app._apply_exam_bands(self.asg, letter, self.results)

    def values(self, letter):
        return [sc.value for sc in self.gb.students[AOKI].scores.get(Criterion(letter), [])
                if sc.assignment == EXAM]

    def test_a_new_criterion_leaves_the_other_grade(self):
        self.band(5, "B")
        self.band(7, "C")
        self.assertEqual((self.values("B"), self.values("C")), ([5], [7]))
        self.assertEqual(self.asg.criteria, ["B", "C"])
        self.assertEqual(self.asg.score_count, 4)

    def test_same_criterion_replaces_only_itself(self):
        self.band(5, "B")
        self.band(7, "C")
        self.band(3, "B")
        self.assertEqual((self.values("B"), self.values("C")), ([3], [7]))
        self.assertEqual(self.asg.score_count, 4)

    def test_it_writes_no_cam2_value_so_the_grade_is_the_teachers(self):
        self.band(5, "B")
        sc = app.find_score(self.gb.students[AOKI], EXAM, "B")
        self.assertIsNone(sc.exam_value)
        self.assertEqual(sc.exam_basis, exam_bridge.exam_basis(self.results[0][1]))


class ResendRuleTests(_GradeBase):
    def test_action_table(self):
        action = exam_bridge.final_level_action
        cases = [
            # current, exam_value, sent -> action
            (None, None, 6, "fill"),        # an empty grade
            (6, 6, 7, "update"),            # still CAM2's, and CAM2 changed it
            (6, 6, 6, "same"),              # nothing new
            (6, None, 6, "same"),           # the teacher's, and it matches
            (5, 6, 7, "keep"),              # edited in CAM
            (5, None, 7, "keep"),           # no record of CAM2: the teacher's
        ]
        for current, exam_value, sent, expected in cases:
            with self.subTest(current=current, exam_value=exam_value, sent=sent):
                self.assertEqual(action(current, exam_value, sent), expected)

    def test_fills_empty_and_records_the_grade_cam2_sent(self):
        self.apply()
        self.assertEqual(app.find_score(self.aoki(), EXAM, "A").exam_value, 6)

    def test_exam_value_is_on_the_0_to_8_scale(self):
        # r2 goes to 4: level 3 is grade 6, and the rule compares it with the grade.
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "C")
        self.assertEqual((sc.value, sc.exam_value), (6, 6))
        self.assertIn("final level 3", sc.note)

    def test_updates_a_grade_cam2_sent_earlier(self):
        self.apply()
        self.result().final_levels["r1"] = 8
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        self.assertEqual((sc.value, sc.exam_value), (8, 8))

    def test_a_grade_edited_in_cam_is_kept_and_listed(self):
        self.apply()
        app.find_score(self.aoki(), EXAM, "A").value = 3
        self.result().final_levels["r1"] = 8
        kept = []
        self.assertEqual(self.apply(kept=kept), 1)    # C still follows
        self.assertEqual(self.grades()["A"], [3])
        self.assertEqual(kept, [(self.aoki(), "A", 3, 8)])

    def test_a_grade_from_before_this_change_counts_as_the_teachers(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        sc.exam_value = None
        self.result().final_levels["r1"] = 8
        kept = []
        self.apply(kept=kept)
        self.assertEqual(self.grades()["A"], [6])
        self.assertEqual(len(kept), 1)

    def test_nothing_new_changes_nothing(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        before = (sc.value, sc.exam_value, sc.note, sc.comment, sc.timestamp)
        sc_c = app.find_score(self.aoki(), EXAM, "C")
        del self.result().final_levels["r1"]
        self.apply()
        self.assertIs(app.find_score(self.aoki(), EXAM, "A"), sc)
        self.assertIs(app.find_score(self.aoki(), EXAM, "C"), sc_c)
        self.assertEqual((sc.value, sc.exam_value, sc.note, sc.comment, sc.timestamp), before)

    def test_sync_never_writes_a_grade(self):
        self.assertEqual(self.grades(), {})
        self.apply()
        session, _config, grades = self.storage.open_session(self.folder)
        grades["overall"]["s001"]["final_levels"]["r1"] = 3
        session.grades_file.save(grades)
        summary, _ = self.sync()
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(self.result().final_levels["r1"], 3)   # CAM2's new level...
        self.assertEqual(self.grades(), {"A": [6], "C": [6]})   # ...doesn't reach the grade

    def test_update_keeps_the_teachers_comment_and_flags(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        sc.comment = "edited in Window 3"
        sc.late = True
        self.result().final_levels["r1"] = 8
        self.result().comment = "re-sent"
        self.apply()
        self.assertIs(app.find_score(self.aoki(), EXAM, "A"), sc)
        self.assertEqual((sc.value, sc.comment, sc.late), (8, "edited in Window 3", True))

    def test_update_fills_a_blank_comment(self):
        self.apply()
        self.result().final_levels["r1"] = 8
        self.result().comment = "from CAM2"
        self.apply()
        self.assertEqual(app.find_score(self.aoki(), EXAM, "A").comment, "from CAM2")


class OneGradeOnlyTests(_GradeBase):
    def test_no_sequence_writes_a_second_grade(self):
        results = app._exam_results_for(EXAM)
        for final in (6, 7, 2):
            self.result().final_levels["r1"] = final
            self.apply()
            self.assert_one_grade_each()
        app.find_score(self.aoki(), EXAM, "A").value = 1
        self.apply()
        self.assert_one_grade_each()
        for s, _r in results:
            self.ss[f"band_{EXAM}_{s.student_id}"] = 4
        for letter in ("A", "B", "A"):
            app._apply_exam_bands(self.asg, letter, results)
            self.assert_one_grade_each()
        self.sync()
        self.apply()
        self.assert_one_grade_each()

    def test_a_write_removes_duplicates_already_there(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        self.aoki().add_score(CriterionScore(
            criterion=Criterion.A, value=1, timestamp=sc.timestamp, assignment=EXAM))
        self.result().final_levels["r1"] = 8
        self.apply()
        self.assert_one_grade_each()
        self.assertEqual(self.grades()["A"], [8])

    def test_another_exams_grade_is_left_alone(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        self.aoki().add_score(CriterionScore(
            criterion=Criterion.A, value=1, timestamp=sc.timestamp, assignment="Other"))
        self.result().final_levels["r1"] = 8
        self.apply()
        self.assertEqual(app.find_score(self.aoki(), "Other", "A").value, 1)

    def test_two_rubrics_on_one_criterion_write_nothing(self):
        # D11: both have a final level, so the teacher decides. The panel still
        # blocks this mapping until Phase 3.
        self.assertEqual(self.apply({"r1": "A", "r2": "A"}), 0)
        self.assertEqual(self.grades(), {})

    def test_a_grade_stays_when_two_rubrics_land_on_its_criterion(self):
        self.apply({"r1": "A"})
        self.apply({"r1": "A", "r2": "A"})
        self.assertEqual(self.grades(), {"A": [6]})


class SeedDropdownTests(unittest.TestCase):
    """A keyed selectbox ignores a changed ``index``, so the panel seeds it."""

    def setUp(self):
        self.ss = {}
        patch = mock.patch.object(app, "st", SimpleNamespace(session_state=self.ss))
        patch.start()
        self.addCleanup(patch.stop)

    def test_first_time_shows_the_value(self):
        app._seed_dropdown("k", 6)
        self.assertEqual(self.ss["k"], 6)

    def test_the_teachers_change_stays_while_the_value_stands(self):
        app._seed_dropdown("k", 6)
        self.ss["k"] = 2
        app._seed_dropdown("k", 6)
        self.assertEqual(self.ss["k"], 2)

    def test_a_new_value_replaces_a_stale_dropdown(self):
        app._seed_dropdown("k", 6)
        self.ss["k"] = 2
        app._seed_dropdown("k", 5)
        self.assertEqual(self.ss["k"], 5)

    def test_a_dropdown_not_rendered_last_run_is_seeded_again(self):
        app._seed_dropdown("k", 6)
        del self.ss["k"]    # Streamlit drops an unrendered widget's state
        app._seed_dropdown("k", 6)
        self.assertEqual(self.ss["k"], 6)


class BasisTests(_GradeBase):
    def paper(self, **kw):
        kw.setdefault("levels", {"Q1": {"r1": 5, "r2": 3}, "Q2": {"r1": 7}})
        return ExamResult(assignment=EXAM, mode="rubric", **kw)

    def test_same_levels_give_the_same_hash_in_any_order(self):
        other = self.paper(levels={"Q2": {"r1": 7}, "Q1": {"r2": 3, "r1": 5}})
        self.assertEqual(exam_bridge.exam_basis(self.paper(), ["r1", "r2"]),
                         exam_bridge.exam_basis(other, ["r2", "r1"]))
        self.assertEqual(len(exam_bridge.exam_basis(self.paper(), ["r1"])), 16)

    def test_only_that_criterions_levels_count(self):
        base = exam_bridge.exam_basis(self.paper(), ["r1"])
        changed = self.paper(levels={"Q1": {"r1": 5, "r2": 1}, "Q2": {"r1": 7}})
        self.assertEqual(exam_bridge.exam_basis(changed, ["r1"]), base)
        changed = self.paper(levels={"Q1": {"r1": 4, "r2": 3}, "Q2": {"r1": 7}})
        self.assertNotEqual(exam_bridge.exam_basis(changed, ["r1"]), base)

    def test_that_criterions_marks_count(self):
        base = exam_bridge.exam_basis(self.paper(), ["r1"])
        marked = self.paper(criterion_marks={"r1": {"total": 15, "max": 20, "percent": 75.0}})
        self.assertNotEqual(exam_bridge.exam_basis(marked, ["r1"]), base)
        self.assertEqual(exam_bridge.exam_basis(marked, ["r2"]),
                         exam_bridge.exam_basis(self.paper(), ["r2"]))

    def test_with_no_rubric_the_whole_papers_marks_are_the_basis(self):
        one = ExamResult(assignment=EXAM, total=5, max_total=10, questions={"Q1": 5})
        two = ExamResult(assignment=EXAM, total=6, max_total=10, questions={"Q1": 6})
        self.assertNotEqual(exam_bridge.exam_basis(one), exam_bridge.exam_basis(two))

    def test_apply_records_what_the_decision_saw(self):
        self.apply()
        self.assertEqual(app.find_score(self.aoki(), EXAM, "A").exam_basis,
                         exam_bridge.exam_basis(self.result(), ["r1"]))

    def test_a_kept_grade_keeps_its_basis_so_phase_3_can_flag_it(self):
        self.apply()
        sc = app.find_score(self.aoki(), EXAM, "A")
        sc.value = 3
        before = sc.exam_basis
        session, config, grades = self.storage.open_session(self.folder)
        self.gs.set_grade(config, grades, "s001", "q2", 1, rubric_id="r1")
        session.grades_file.save(grades)
        self.sync()
        self.apply()
        self.assertEqual(sc.exam_basis, before)
        self.assertNotEqual(exam_bridge.exam_basis(self.result(), ["r1"]), before)

    def test_decision_basis_uses_the_saved_mapping(self):
        self.ss["exam_sessions"][CLASS][EXAM]["criteria"] = {"r1": "A", "r2": "—"}
        self.assertEqual(app._exam_decision_basis(self.aoki(), EXAM, "A"),
                         exam_bridge.exam_basis(self.result(), ["r1"]))
        self.assertEqual(app._exam_decision_basis(self.aoki(), "Not an exam", "A"), "")


class AwaitingDecisionTests(_GradeBase):
    """I13. Aoki has a grade, Baba a paper and no grade, Chiba no paper at all."""

    def setUp(self):
        super().setUp()
        self.ss["rosters"][CLASS].append({"key": CHIBA, "name": "Chiba"})
        self.gb.get_or_create(CHIBA)
        self.apply()
        self.row = next(r for r in app.assignment_table() if r["name"] == EXAM)

    def names(self, key):
        return [r["name"] for r in app.missing_assignment_rows(self.gb.students[key])]

    def test_a_paper_with_no_grade_is_not_missing(self):
        self.assertTrue(app.awaiting_exam_decision(self.gb.students[BABA], self.row))
        self.assertEqual(self.names(BABA), [])
        self.assertEqual(app.missing_zero_points(self.gb.students[BABA], "A"), [])

    def test_a_finished_paper_with_no_grade_is_not_missing_either(self):
        self.result(BABA).complete = True
        self.assertEqual(self.names(BABA), [])

    def test_no_paper_at_all_is_still_missing(self):
        self.assertFalse(app.awaiting_exam_decision(self.gb.students[CHIBA], self.row))
        self.assertEqual(self.names(CHIBA), [EXAM])
        self.assertEqual(len(app.missing_zero_points(self.gb.students[CHIBA], "A")), 1)

    def test_one_grade_ends_the_wait_and_other_criteria_stay_out(self):
        self.assertFalse(app.awaiting_exam_decision(self.aoki(), self.row))
        app.find_score(self.aoki(), EXAM, "C")
        self.aoki().scores[Criterion.C] = []
        self.assertEqual(self.names(AOKI), [])
        self.assertEqual(app.missing_zero_points(self.aoki(), "C"), [])

    def test_other_assignments_are_unaffected(self):
        self.assertFalse(app.awaiting_exam_decision(
            self.gb.students[BABA], dict(self.row, is_exam=False)))


class _BridgeBase(_SessionBase):
    def rubric(self, rid="r1", name="Criterion A", top=8):
        rubrics = exam_bridge.cam2_module("rubrics")
        return dict(rubrics.normalize_rubric(
            {"id": rid, "name": name, "bands": [{"levels": "0"}, {"levels": f"1–{top}"}]}), id=rid)

    def read_one(self, **kw):
        kw.setdefault("students", STUDENTS[:1])
        kw.setdefault("roster", ROSTER[:1])
        folder = self.make_session("s", **kw)
        before = _folder_hash(folder)
        session = exam_bridge.read_session(folder)
        self.assertEqual(_folder_hash(folder), before)
        return session, session.papers[0].result


class BridgeOnThisPinTests(_BridgeBase):
    def test_mode_comes_from_the_shape_of_each_question(self):
        mode = exam_bridge._exam_mode
        self.assertEqual(mode([{None: 1}, {None: None}], "rubric"), "marks")
        self.assertEqual(mode([{"r1": 1}, {"r1": None, "r2": 2}], "marks"), "rubric")
        self.assertEqual(mode([{None: 1}, {"r1": 2}], "rubric"), "mixed")
        self.assertEqual(mode([{None: 1}, {"r1": 2}], ""), "mixed")
        self.assertEqual(mode([{}], "rubric"), "rubric")
        self.assertEqual(mode([], ""), "")

    def test_marks_only_reads_as_before(self):
        session, result = self.read_one(
            mode="marks", questions=_questions(("q1", "Q1", 10, None), ("q2", "Q2", 10, None)),
            grades=[("s001", "q1", 8), ("s001", "q2", 7)])
        self.assertEqual((session.mode, session.max_total), ("marks", 20))
        self.assertEqual((result.mode, result.total, result.max_total), ("marks", 15, 20))
        self.assertEqual(result.questions, {"Q1": 8, "Q2": 7})
        self.assertEqual((result.levels, result.final_levels), ({}, {}))
        self.assertEqual((result.percent, result.weighted), (75.0, False))

    def test_rubric_with_a_typed_final_reads_as_before(self):
        session, result = self.read_one(
            mode="rubric", rubrics=[self.rubric()],
            questions=_questions(("q1", "Q1", 0, ["r1"]), ("q2", "Q2", 0, ["r1"])),
            grades=[("s001", "q1", 5, "r1"), ("s001", "q2", 6, "r1")],
            overall={"s001": {"final_levels": {"r1": 7}}})
        self.assertEqual((session.mode, session.max_total), ("rubric", 0))
        self.assertEqual(result.levels, {"Q1": {"r1": 5}, "Q2": {"r1": 6}})
        self.assertEqual(result.final_levels, {"r1": 7})
        self.assertEqual((result.total, result.max_total, result.questions), (0, 0, {}))
        self.assertIsNone(result.percent)


class BridgeOnVersion2Tests(_BridgeBase):
    """§3.1's rows only a version 2 session can show. They skip on this pin."""

    def mixed(self, mode, first_max, second_max, grades, **kw):
        rid_q1 = None if first_max else ["r1"]
        rid_q2 = None if second_max else ["r1"]
        return self.read_one(
            mode=mode, rubrics=[self.rubric()],
            questions=_questions(("q1", "Q1", first_max, rid_q1), ("q2", "Q2", second_max, rid_q2)),
            grades=grades, **kw)

    @needs_version_2
    def test_rubric_with_no_final_typed_has_levels_and_nothing_to_confirm(self):
        _, result = self.read_one(
            mode="rubric", rubrics=[self.rubric()],
            questions=_questions(("q1", "Q1", 0, ["r1"]), ("q2", "Q2", 0, ["r1"])),
            grades=[("s001", "q1", 5, "r1"), ("s001", "q2", 6, "r1")])
        self.assertEqual(result.levels, {"Q1": {"r1": 5}, "Q2": {"r1": 6}})
        self.assertEqual(result.final_levels, {})

    @needs_version_2
    def test_mixed_started_as_rubric_keeps_marks_and_files_no_null_rubric(self):
        session, result = self.mixed("rubric", 0, 10, [("s001", "q1", 5, "r1"), ("s001", "q2", 8)])
        self.assertEqual((session.mode, result.mode), ("mixed", "mixed"))
        self.assertEqual(result.levels, {"Q1": {"r1": 5}})
        self.assertEqual(result.questions, {"Q2": 8})
        self.assertEqual((result.total, result.max_total), (8, 10))
        issues = []
        _validate_exam_result(exam_result_to_dict(result), "r", issues)
        self.assertEqual(issues, [])

    @needs_version_2
    def test_mixed_started_as_marks_keeps_the_level_and_final(self):
        _, result = self.mixed("marks", 10, 0, [("s001", "q1", 8), ("s001", "q2", 6, "r1")],
                               overall={"s001": {"final_levels": {"r1": 6}}})
        self.assertEqual(result.mode, "mixed")
        self.assertEqual((result.questions, result.levels), ({"Q1": 8}, {"Q2": {"r1": 6}}))
        self.assertEqual(result.final_levels, {"r1": 6})
        self.assertEqual((result.total, result.max_total), (8, 10))

    @needs_version_2
    def test_mixed_with_no_starting_choice_keeps_the_level(self):
        _, result = self.mixed("", 10, 0, [("s001", "q1", 9), ("s001", "q2", 4, "r1")])
        self.assertEqual(result.mode, "mixed")
        self.assertEqual((result.questions, result.levels), ({"Q1": 9}, {"Q2": {"r1": 4}}))
        self.assertEqual((result.total, result.max_total), (9, 10))

    @needs_version_2
    def test_weighted_reports_cam2s_percentage_beside_the_raw_total(self):
        folder = self.make_session(
            "w", mode="marks", students=STUDENTS[:1], roster=ROSTER[:1],
            questions=[dict(q, section_id=sid) for q, sid in zip(
                _questions(("q1", "Q1", 10, None), ("q2", "Q2", 40, None)), ("a", "b"))],
            grades=[("s001", "q1", 10), ("s001", "q2", 0)])
        session, config, _grades = self.storage.open_session(folder)
        config.update(weighted=True, sections=[
            {"id": "a", "name": "A", "weight": 50, "weight_typed": True},
            {"id": "b", "name": "B", "weight": 50, "weight_typed": False}])
        session.config_file.save(config)
        result = exam_bridge.read_session(folder).papers[0].result
        self.assertEqual((result.total, result.max_total), (10, 50))
        self.assertEqual((result.percent, result.weighted), (50.0, True))

    @needs_version_2
    def test_criterion_marks_carry_over_and_write_no_level(self):
        _, result = self.read_one(
            mode="marks", rubrics=[self.rubric()],
            questions=_questions(("q1", "Q1", 20, ["r1"])), grades=[("s001", "q1", 15)])
        self.assertEqual(result.criterion_marks, {"r1": {"total": 15, "max": 20, "percent": 75.0}})
        self.assertEqual((result.levels, result.final_levels), ({}, {}))


class ApplyOnVersion2Tests(_AppBase):
    """The I2 table's right-hand column, from a real version 2 session."""

    def session(self, finals):
        rubrics = exam_bridge.cam2_module("rubrics")

        def rubric(rid, name):
            return dict(rubrics.normalize_rubric(
                {"id": rid, "name": name, "bands": [{"levels": "0"}, {"levels": "1–8"}]}), id=rid)

        return self.make_session(
            "v2", mode="rubric", rubrics=[rubric("r1", "Criterion A"), rubric("r2", "Criterion C")],
            questions=_questions(("q1", "Q1", 0, ["r1", "r2"])),
            students=STUDENTS[:1], roster=ROSTER[:1],
            grades=[("s001", "q1", 5, "r1"), ("s001", "q1", 4, "r2")],
            overall={"s001": {"final_levels": finals}})

    def apply(self):
        return app._apply_exam_rubric_levels(
            self.gb.assignments[0], MAPPING, app._exam_results_for(EXAM))

    def values(self):
        return {letter: app.find_score(self.gb.students[AOKI], EXAM, letter).value
                for letter in ("A", "C") if app.find_score(self.gb.students[AOKI], EXAM, letter)}

    @needs_version_2
    def test_levels_with_no_final_write_no_grade(self):
        self.hosted(self.session, finals={})
        self.sync()
        self.assertEqual(self.apply(), 0)
        self.assertEqual(self.values(), {})

    @needs_version_2
    def test_clearing_one_typed_final_keeps_both_grades(self):
        folder = self.hosted(self.session, finals={"r1": 6, "r2": 6})
        self.sync()
        self.apply()
        self.assertEqual(self.values(), {"A": 6, "C": 6})
        session, config, grades = self.storage.open_session(folder)
        grades["overall"]["s001"]["final_levels"] = {"r2": 6}
        session.grades_file.save(grades)
        self.sync()
        self.assertEqual(self.gb.students[AOKI].exam_results[EXAM].final_levels, {"r2": 6})
        self.assertEqual(self.apply(), 1)
        self.assertEqual(self.values(), {"A": 6, "C": 6})
        self.assertEqual(self.gb.assignments[0].score_count, 2)


class StorageTests(unittest.TestCase):
    def score(self, **kw):
        from datetime import datetime
        return CriterionScore(criterion=Criterion.A, value=6,
                              timestamp=datetime(2026, 11, 1), assignment=EXAM, **kw)

    def test_a_score_without_exam_fields_saves_as_before(self):
        saved = _score_to_dict(self.score())
        self.assertNotIn("exam_value", saved)
        self.assertNotIn("exam_basis", saved)

    def test_exam_fields_round_trip(self):
        loaded = _score_from_dict(_score_to_dict(self.score(exam_value=0, exam_basis="ab12")))
        self.assertEqual((loaded.exam_value, loaded.exam_basis), (0, "ab12"))

    def test_an_older_score_loads_as_the_teachers(self):
        saved = _score_to_dict(self.score())
        loaded = _score_from_dict(saved)
        self.assertEqual((loaded.exam_value, loaded.exam_basis), (None, ""))

    def test_an_older_exam_record_is_unchanged(self):
        old = {"assignment": EXAM, "total": 7, "max_total": 10, "questions": {"Q1": 7},
               "comment": "", "chosen": {}, "section_bands": {}, "mode": "marks",
               "session_id": "s", "final_levels": {"r1": 6}}
        result = exam_result_from_dict(dict(old))
        self.assertEqual((result.percent, result.weighted, result.criterion_marks),
                         (None, False, {}))
        self.assertEqual(exam_result_to_dict(result), old)

    def test_new_exam_fields_round_trip(self):
        marks = {"r1": {"total": 15, "max": 20, "percent": 75.0}}
        result = ExamResult(assignment=EXAM, mode="mixed", percent=50.0, weighted=True,
                            criterion_marks=marks)
        saved = exam_result_to_dict(result)
        self.assertEqual((saved["percent"], saved["weighted"], saved["criterion_marks"]),
                         (50.0, True, marks))
        loaded = exam_result_from_dict(saved)
        self.assertEqual((loaded.mode, loaded.percent, loaded.weighted, loaded.criterion_marks),
                         ("mixed", 50.0, True, marks))
        issues = []
        _validate_exam_result(saved, "r", issues)
        self.assertEqual(issues, [])

    def test_validator_rejects_non_string_keys(self):
        for field, value in (("levels", {"Q1": {None: 8}}),
                             ("levels", {None: {"r1": 8}}),
                             ("final_levels", {None: 8})):
            issues = []
            _validate_exam_result({"assignment": EXAM, field: value}, "r", issues)
            self.assertEqual([i.code for i in issues], ["expected-string-key"], (field, value))

    def test_a_string_null_key_already_on_disk_still_loads(self):
        issues = []
        _validate_exam_result({"assignment": EXAM, "levels": {"Q2": {"null": 8}}}, "r", issues)
        self.assertEqual(issues, [])

    def test_validator_rejects_wrong_shapes_in_the_new_fields(self):
        for value in ({"percent": "50"}, {"weighted": 1}, {"criterion_marks": []},
                      {"criterion_marks": {"r1": 3}}):
            issues = []
            _validate_exam_result(dict({"assignment": EXAM}, **value), "r", issues)
            self.assertTrue(issues, value)


if __name__ == "__main__":
    unittest.main()
