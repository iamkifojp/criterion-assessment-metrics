"""Recording grades, totals, choice questions, sections, weighting, overrides.

Run:  python -m unittest tests.test_grading_summary
"""

import unittest
from decimal import Decimal

from engine import grading_summary as gs
from engine import model, rubrics
from engine.errors import UserError

NA = model.NOT_ANSWERED


def marks_exam(choice=None):
    config = {
        "mode": "marks",
        "students": [{"id": "s1"}, {"id": "s2"}],
        "questions": [{"id": "q1", "label": "Q1", "max": 5},
                      {"id": "q2", "label": "Q2", "max": 10},
                      {"id": "q3", "label": "Q3", "max": 10},
                      {"id": "q4", "label": "Q4", "max": 8}],
        "choice_groups": choice or [],
    }
    return config, model.new_grades("x")


def rubric_exam():
    a = rubrics.normalize_rubric(rubrics.new_rubric("r1", "Criterion A"))
    b = rubrics.normalize_rubric(rubrics.new_rubric("r2", "Criterion B"))
    config = {
        "mode": "rubric", "rubrics": [a, b],
        "students": [{"id": "s1"}],
        "questions": [{"id": "q1", "label": "Q1", "rubric_id": "r1"},
                      {"id": "q2", "label": "Q2", "rubric_id": "r1"},
                      {"id": "q3", "label": "Q3", "rubric_id": "r2"}],
        "choice_groups": [],
    }
    return config, model.new_grades("x")


class RoundingTests(unittest.TestCase):
    def test_halves_round_up(self):
        self.assertEqual(round(4.5), 4)                     # why we don't use round()
        self.assertEqual(gs.round_half_up(4.5), Decimal(5))
        self.assertEqual(gs.round_half_up(5.5), Decimal(6))
        self.assertEqual(gs.round_half_up(5.49), Decimal(5))
        self.assertEqual(gs.round_half_up(Decimal("5.65"), 1), Decimal("5.7"))


class RecordingTests(unittest.TestCase):
    def test_marks_are_checked(self):
        config, grades = marks_exam()
        gs.set_grade(config, grades, "s1", "q1", 5, "Good")
        gs.set_grade(config, grades, "s1", "q1", comment="Better")
        self.assertEqual(grades["grades"]["s1"]["q1"], {"value": 5, "comment": "Better"})
        for bad in (6, -1, 2.5, True, "3"):
            with self.assertRaises(UserError, msg=bad):
                gs.set_grade(config, grades, "s1", "q1", bad)
        gs.set_grade(config, grades, "s1", "q1", NA)
        gs.set_grade(config, grades, "s1", "q1", None)
        self.assertIsNone(grades["grades"]["s1"]["q1"]["value"])
        with self.assertRaises(UserError):
            gs.set_grade(config, grades, "nobody", "q1", 1)
        with self.assertRaises(UserError):
            gs.set_grade(config, grades, "s1", "q99", 1)

    def test_rubric_levels_are_checked(self):
        config, grades = rubric_exam()
        gs.set_grade(config, grades, "s1", "q1", 6)
        with self.assertRaises(UserError):
            gs.set_grade(config, grades, "s1", "q1", 9)

    def test_single_rubric_is_used_when_none_picked(self):
        config, grades = rubric_exam()
        config["rubrics"] = config["rubrics"][:1]
        config["questions"][2]["rubric_id"] = None
        gs.set_grade(config, grades, "s1", "q3", 7)
        config["rubrics"] = []
        with self.assertRaises(UserError):
            gs.set_grade(config, grades, "s1", "q3", 7)


class MarksTests(unittest.TestCase):
    def test_total_percent_and_not_answered(self):
        config, grades = marks_exam()
        for qid, v in (("q1", 4), ("q2", 7), ("q3", NA), ("q4", 8)):
            gs.set_grade(config, grades, "s1", qid, v)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["marks"]["total"], 19)
        self.assertEqual(result["marks"]["max"], 33)
        self.assertEqual(result["marks"]["percent"], 57.6)
        self.assertTrue(result["complete"])

    def test_ungraded_is_flagged(self):
        config, grades = marks_exam()
        gs.set_grade(config, grades, "s1", "q1", 4)
        result = gs.student_summary(config, grades, "s1")
        self.assertFalse(result["complete"])
        self.assertEqual(result["ungraded"], ["q2", "q3", "q4"])
        self.assertEqual(result["marks"]["total"], 4)

    def test_choice_group_counts_best_answers(self):
        group = [{"id": "g1", "questions": ["q2", "q3", "q4"], "answer": 2}]
        config, grades = marks_exam(group)
        gs.check_choice_groups(config)
        self.assertEqual(gs.marks_maximum(config), 25)      # 5 + (10 + 10)
        # Answered all three: best two count
        for qid, v in (("q1", 5), ("q2", 3), ("q3", 9), ("q4", 6)):
            gs.set_grade(config, grades, "s1", qid, v)
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["total"], 20)
        # Answered only one of the choice: the missing slot counts 0
        for qid, v in (("q1", 5), ("q2", NA), ("q3", 9), ("q4", NA)):
            gs.set_grade(config, grades, "s2", qid, v)
        result = gs.student_summary(config, grades, "s2")
        self.assertEqual(result["marks"]["total"], 14)
        self.assertEqual(set(result["counted"]), {"q1", "q3", "q2"})

    def test_teacher_picks_which_answers_count(self):
        group = [{"id": "g1", "questions": ["q2", "q3", "q4"], "answer": 2, "pick": "teacher"}]
        config, grades = marks_exam(group)
        gs.check_choice_groups(config)
        for qid, v in (("q1", 5), ("q2", 3), ("q3", 9), ("q4", 6)):
            gs.set_grade(config, grades, "s1", qid, v)
        # Answered all three: nothing from the group counts until the teacher picks
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["pending"], ["g1"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["marks"]["total"], 5)
        self.assertEqual(result["choices"]["g1"],
                         {"answered": ["q2", "q3", "q4"], "chosen": [], "pending": True})
        # A pick of fewer than N is kept but still waits
        gs.set_choice(config, grades, "s1", "g1", ["q4"])
        self.assertEqual(gs.student_summary(config, grades, "s1")["pending"], ["g1"])
        # The teacher's pick counts even when it isn't the best two; stored in group order
        gs.set_choice(config, grades, "s1", "g1", ["q4", "q2"])
        self.assertEqual(grades["overall"]["s1"]["chosen"]["g1"], ["q2", "q4"])
        result = gs.student_summary(config, grades, "s1")
        self.assertTrue(result["complete"])
        self.assertEqual(result["marks"]["total"], 14)          # 5 + 3 + 6
        self.assertEqual(set(result["counted"]), {"q1", "q2", "q4"})
        # A picked answer later marked Not answered no longer over-answers the group
        gs.set_grade(config, grades, "s1", "q2", NA)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["choices"], {})
        self.assertEqual(result["marks"]["total"], 20)          # 5 + 9 + 6, as with best N
        # Answering N or fewer never needs a pick
        for qid, v in (("q1", 5), ("q2", NA), ("q3", 9), ("q4", NA)):
            gs.set_grade(config, grades, "s2", qid, v)
        result = gs.student_summary(config, grades, "s2")
        self.assertTrue(result["complete"])
        self.assertEqual(result["marks"]["total"], 14)

    def test_bad_choice_picks(self):
        group = [{"id": "g1", "questions": ["q2", "q3", "q4"], "answer": 2, "pick": "teacher"}]
        config, grades = marks_exam(group)
        for bad in (["q2", "q3", "q4"], ["q1"], ["q2", "q2"]):
            with self.assertRaises(UserError, msg=bad):
                gs.set_choice(config, grades, "s1", "g1", bad)
        with self.assertRaises(UserError):
            gs.set_choice(config, grades, "s1", "g9", ["q2"])
        gs.set_choice(config, grades, "s1", "g1", ["q2"])
        gs.set_choice(config, grades, "s1", "g1", None)
        self.assertEqual(grades["overall"]["s1"]["chosen"], {})

    def test_bad_choice_groups(self):
        for group in ({"id": "g", "questions": ["q1"], "answer": 1},
                      {"id": "g", "questions": ["q1", "q2"], "answer": 2},
                      {"id": "g", "questions": ["q1", "q9"], "answer": 1},
                      {"id": "g", "questions": ["q1", "q2"], "answer": 1, "pick": "first"}):
            config, _ = marks_exam([group])
            with self.assertRaises(UserError):
                gs.check_choice_groups(config)
        config, _ = marks_exam([{"id": "a", "questions": ["q1", "q2"], "answer": 1},
                                {"id": "b", "questions": ["q2", "q3"], "answer": 1}])
        with self.assertRaises(UserError):
            gs.check_choice_groups(config)

    def test_report_total_overrides_only_the_report(self):
        config, grades = marks_exam()
        for qid in ("q1", "q2", "q3", "q4"):
            gs.set_grade(config, grades, "s1", qid, 5)
        gs.set_report_total(config, grades, "s1", 22)
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["total"], marks["report_total"], marks["adjusted"]),
                         (20, 22, True))
        gs.set_report_total(config, grades, "s1", None)
        self.assertFalse(gs.student_summary(config, grades, "s1")["marks"]["adjusted"])
        gs.set_report_total(config, grades, "s1", " 21 ")           # typed in a text box
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["report_total"], 21)
        for bad in ("abc", -1, True, "nan", 34):
            with self.assertRaises(UserError, msg=bad):
                gs.set_report_total(config, grades, "s1", bad)


class RubricTests(unittest.TestCase):
    def test_levels_are_reported_as_given_and_never_averaged(self):
        config, grades = rubric_exam()
        for qid, v in (("q1", 5), ("q2", 6), ("q3", NA)):
            gs.set_grade(config, grades, "s1", qid, v)
        result = gs.student_summary(config, grades, "s1")["rubrics"]
        self.assertEqual(result["r1"], {"final": None, "marks": None, "grades": [
            {"question": "q1", "level": 5}, {"question": "q2", "level": 6}]})
        self.assertEqual(result["r2"]["grades"], [{"question": "q3", "level": NA}])

    def test_final_level_is_only_ever_typed(self):
        config, grades = rubric_exam()
        gs.set_grade(config, grades, "s1", "q1", 5)
        self.assertIsNone(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["final"])
        gs.set_final_level(config, grades, "s1", "r1", 5)
        self.assertEqual(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["final"], 5)
        gs.set_final_level(config, grades, "s1", "r1", " 6 ")          # typed in a text box
        self.assertEqual(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["final"], 6)
        gs.set_final_level(config, grades, "s1", "r1", None)
        self.assertIsNone(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["final"])
        with self.assertRaises(UserError):
            gs.set_final_level(config, grades, "s1", "r1", 9)
        with self.assertRaises(UserError):
            gs.set_final_level(config, grades, "s1", "r9", 1)

    def test_final_level_must_be_in_a_band(self):
        config, grades = rubric_exam()
        config["rubrics"][0] = rubrics.normalize_rubric(
            {"id": "r1", "name": "Criterion A", "bands": [{"levels": "0"}, {"levels": "5-6"}]})
        gs.set_final_level(config, grades, "s1", "r1", 5)
        with self.assertRaises(UserError):             # under the maximum, but in no band
            gs.set_final_level(config, grades, "s1", "r1", 3)

    def test_final_levels_count_for_the_wipe_guard(self):
        config, grades = rubric_exam()
        gs.set_final_level(config, grades, "s1", "r1", 5)
        gs.set_final_level(config, grades, "s1", "r2", None)
        self.assertEqual(model.grades_mass(grades), 1)

    def test_no_grades_yet(self):
        config, grades = rubric_exam()
        r1 = gs.student_summary(config, grades, "s1")["rubrics"]["r1"]
        self.assertEqual((r1["grades"], r1["final"]), ([], None))


def multi_exam(choice=None):
    """Q1 on A; Q2 on B and C; Q3 on C (as on an MYP science paper)."""
    rs = [rubrics.normalize_rubric(rubrics.new_rubric(rid, name))
          for rid, name in (("r1", "Criterion A"), ("r2", "Criterion B"), ("r3", "Criterion C"))]
    config = {
        "mode": "rubric", "rubrics": rs,
        "students": [{"id": "s1"}, {"id": "s2"}],
        "questions": [{"id": "q1", "label": "Q1", "rubric_ids": ["r1"]},
                      {"id": "q2", "label": "Q2", "rubric_ids": ["r3", "r2"]},
                      {"id": "q3", "label": "Q3", "rubric_ids": ["r3"]}],
        "choice_groups": choice or [],
    }
    return config, model.new_grades("x")


class MultiCriterionTests(unittest.TestCase):
    def test_criteria_follow_rubric_order_and_old_sessions(self):
        config, _ = multi_exam()
        self.assertEqual(gs.question_rubric_ids(config, config["questions"][1]), ["r2", "r3"])
        self.assertEqual(gs.question_rubric_ids(config, {"rubric_id": "r3"}), ["r3"])
        self.assertEqual([gs.slot_key(q["id"], rid) for q, rid in gs.slots(config)],
                         ["q1/r1", "q2/r2", "q2/r3", "q3/r3"])

    def test_one_level_per_criterion(self):
        config, grades = multi_exam()
        gs.set_grade(config, grades, "s1", "q2", 7, "Clear method.", rubric_id="r2")
        entry = grades["grades"]["s1"]["q2"]
        self.assertEqual(entry["levels"], {"r2": 7})
        self.assertIn("q2", gs.student_summary(config, grades, "s1")["ungraded"])
        gs.set_grade(config, grades, "s1", "q2", 4, rubric_id="r3")
        self.assertEqual(entry, {"value": None, "comment": "Clear method.",
                                 "levels": {"r2": 7, "r3": 4}})
        with self.assertRaises(UserError):                 # which criterion?
            gs.set_grade(config, grades, "s1", "q2", 4)
        with self.assertRaises(UserError):                 # Q2 is not assessed on A
            gs.set_grade(config, grades, "s1", "q2", 4, rubric_id="r1")
        with self.assertRaises(UserError):                 # checked against B's levels
            gs.set_grade(config, grades, "s1", "q2", 9, rubric_id="r2")

    def test_each_criterion_lists_its_own_grades(self):
        config, grades = multi_exam()
        gs.set_grade(config, grades, "s1", "q1", 6)
        gs.set_grade(config, grades, "s1", "q2", 7, rubric_id="r2")
        gs.set_grade(config, grades, "s1", "q2", 4, rubric_id="r3")
        gs.set_grade(config, grades, "s1", "q3", 5)
        summary = gs.student_summary(config, grades, "s1")
        self.assertTrue(summary["complete"])
        self.assertEqual({rid: [g["level"] for g in r["grades"]] for rid, r in summary["rubrics"].items()},
                         {"r1": [6], "r2": [7], "r3": [4, 5]})
        self.assertEqual(summary["levels"]["q2"], {"r2": 7, "r3": 4})
        stats = gs.class_summary(config, grades)["questions"]
        self.assertEqual(stats["q2/r3"]["average"], 4.0)
        self.assertEqual(gs.progress(config, grades)["graded"], 4)
        self.assertEqual(gs.progress(config, grades)["total"], 8)

    def test_not_answered_and_clear_apply_to_the_whole_question(self):
        config, grades = multi_exam()
        gs.set_grade(config, grades, "s1", "q2", NA)
        self.assertEqual(grades["grades"]["s1"]["q2"]["levels"], {"r2": NA, "r3": NA})
        self.assertEqual(gs.student_summary(config, grades, "s1")["counted"]["q2"],
                         {"r2": 0, "r3": 0})
        gs.set_grade(config, grades, "s1", "q2", None)
        self.assertEqual(grades["grades"]["s1"]["q2"]["levels"], {"r2": None, "r3": None})
        self.assertFalse(gs.question_has_grade(grades, "q2"))
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r3")
        self.assertTrue(gs.question_has_grade(grades, "q2"))
        self.assertFalse(gs.question_has_grade(grades, "q1"))
        self.assertEqual(model.grades_mass(grades), 1)

    def test_choice_group_ranks_by_sum_of_levels(self):
        config, grades = multi_exam([{"id": "g1", "questions": ["q2", "q3"], "answer": 1}])
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r2")
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r3")
        gs.set_grade(config, grades, "s1", "q3", 5)
        counted = gs.student_summary(config, grades, "s1")["counted"]
        self.assertIn("q2", counted)                           # 3 + 3 beats 5
        self.assertNotIn("q3", counted)

    def test_teacher_picks_in_rubric_mode(self):
        config, grades = multi_exam([{"id": "g1", "questions": ["q2", "q3"], "answer": 1,
                                      "pick": "teacher"}])
        gs.set_grade(config, grades, "s1", "q1", 4)
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r2")
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r3")
        gs.set_grade(config, grades, "s1", "q3", 5)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["pending"], ["g1"])
        self.assertEqual(result["rubrics"]["r3"]["grades"], [])
        gs.set_choice(config, grades, "s1", "g1", ["q3"])         # the teacher picks Q3
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["rubrics"]["r3"]["grades"], [{"question": "q3", "level": 5}])
        self.assertEqual(result["rubrics"]["r2"]["grades"], [])   # Q2 did not count

    def test_criteria_changed_after_grading(self):
        config, grades = multi_exam()
        gs.set_grade(config, grades, "s1", "q3", 5)              # Q3 on C only
        q3 = config["questions"][2]
        q3["rubric_ids"] = ["r3", "r2"]                          # ...then B added
        self.assertEqual(gs.question_values(config, grades, "s1", q3), {"r2": None, "r3": 5})
        gs.set_grade(config, grades, "s1", "q3", 6, rubric_id="r2")
        q3["rubric_ids"] = ["r2"]                                # ...and C taken off
        self.assertEqual(gs.question_values(config, grades, "s1", q3), {"r2": 6})
        q3["rubric_ids"] = ["r3"]
        self.assertEqual(gs.question_values(config, grades, "s1", q3), {"r3": 5})

    def test_sessions_graded_before_levels_per_criterion(self):
        config, grades = multi_exam()
        grades["grades"] = {"s1": {"q3": {"value": 5, "comment": ""}}}
        q3 = config["questions"][2]
        self.assertEqual(gs.question_values(config, grades, "s1", q3), {"r3": 5})
        gs.set_grade(config, grades, "s1", "q3", 6)
        self.assertEqual(grades["grades"]["s1"]["q3"]["levels"], {"r3": 6})


def paper(*sections, weighted=False, rubric_names=("Criterion A", "Criterion B"), choice=None):
    """An exam from sections of questions, each (id, max, [rubric ids]); Max None
    means no marks. Section shares are worked out as the app does."""
    questions = []
    stored = []
    for i, (qs, weight) in enumerate(sections, 1):
        stored.append({"id": f"sec{i}", "name": "", "weight": weight, "weight_typed": weight is not None})
        for qid, top, rids in qs:
            questions.append({"id": qid, "label": qid.upper(), "max": top, "rubric_ids": rids,
                              "section_id": f"sec{i}"})
    config = {"mode": "marks", "students": [{"id": "s1"}], "questions": questions,
              "sections": stored if len(stored) > 1 else [], "weighted": weighted,
              "choice_groups": choice or [],
              "rubrics": [rubrics.normalize_rubric(rubrics.new_rubric(f"r{i}", name))
                          for i, name in enumerate(rubric_names, 1)]}
    gs.rebalance_shares(config)
    return config, model.new_grades("x")


def give(config, grades, **values):
    for qid, value in values.items():
        gs.set_grade(config, grades, "s1", qid, value)


class HowAQuestionIsGradedTests(unittest.TestCase):
    """Each row of the question table in Exam-Section-Plan.md §2."""

    def setUp(self):
        self.config, self.grades = paper(([("q1", 10, []), ("q2", 10, ["r2"]),
                                           ("q3", None, ["r2"]), ("q4", None, [])], None))
        self.q1, self.q2, self.q3, self.q4 = self.config["questions"]

    def test_marks_filled_in_and_no_criteria(self):
        self.assertEqual(gs.question_mode(self.config, self.q1), "marks")
        give(self.config, self.grades, q1=6)
        self.assertEqual(self.grades["grades"]["s1"]["q1"]["value"], 6)

    def test_marks_filled_in_and_ticked(self):
        self.assertEqual(gs.question_mode(self.config, self.q2), "marks")
        give(self.config, self.grades, q2=6)
        result = gs.student_summary(self.config, self.grades, "s1")
        self.assertEqual(result["rubrics"]["r2"]["marks"]["total"], 6)
        self.assertEqual(result["rubrics"]["r2"]["grades"], [])

    def test_empty_and_ticked(self):
        self.assertEqual(gs.question_mode(self.config, self.q3), "rubric")
        give(self.config, self.grades, q3=5)
        self.assertEqual(self.grades["grades"]["s1"]["q3"]["levels"], {"r2": 5})
        self.assertEqual(gs.student_summary(self.config, self.grades, "s1")["marks"]["total"], 0)

    def test_empty_with_no_criteria_is_not_ready(self):
        self.assertIsNone(gs.question_mode(self.config, self.q4))
        self.assertEqual([gs.slot_key(q["id"], r) for q, r in gs.slots(self.config)],
                         ["q1", "q2", "q3/r2"])
        with self.assertRaises(UserError) as ctx:
            give(self.config, self.grades, q4=1)
        self.assertEqual(ctx.exception.code, "question_needs_marks_or_criterion")
        gs.set_grade(self.config, self.grades, "s1", "q4", comment="Comments are fine.")
        self.assertIn("q4", gs.student_summary(self.config, self.grades, "s1")["ungraded"])

    def test_a_marks_question_is_not_put_on_the_only_rubric(self):
        config, grades = paper(([("q1", 10, []), ("q2", None, [])], None), rubric_names=("Criterion A",))
        self.assertEqual(gs.question_rubric_ids(config, config["questions"][0]), [])
        self.assertEqual(gs.question_mode(config, config["questions"][1]), "rubric")
        give(config, grades, q1=6)
        self.assertIsNone(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["marks"])


class NeverMixingMarksAndLevelsTests(unittest.TestCase):
    def test_a_level_is_not_stored_as_a_mark(self):
        config, grades = paper(([("q1", 8, ["r1"])], None))
        with self.assertRaises(UserError) as ctx:
            gs.set_grade(config, grades, "s1", "q1", 5, rubric_id="r1")
        self.assertEqual(ctx.exception.code, "unknown_rubric")
        self.assertFalse(gs.question_has_grade(grades, "q1"))

    def test_a_mixed_papers_total_ignores_levels(self):
        config, grades = paper(([("q1", 10, []), ("q2", None, ["r1"]), ("q3", 5, ["r1"])], None))
        give(config, grades, q1=7, q2=8, q3=3)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual((result["marks"]["total"], result["marks"]["max"], result["marks"]["percent"]),
                         (10, 15, 66.7))
        self.assertEqual(result["counted"], {"q1": 7, "q2": {"r1": 8}, "q3": 3})
        self.assertEqual(result["levels"], {"q2": {"r1": 8}})
        self.assertEqual(result["rubrics"]["r1"]["marks"], {"total": 3, "max": 5, "percent": 60.0})
        self.assertEqual(result["rubrics"]["r1"]["grades"], [{"question": "q2", "level": 8}])
        stats = gs.class_summary(config, grades)
        self.assertEqual(sorted(stats["questions"]), ["q1", "q2/r1", "q3"])
        self.assertEqual(stats["overall"]["total"]["max"], 10)

    def test_mixed_paper_in_one_section_and_with_sections(self):
        flat, grades = paper(([("q1", 10, []), ("q2", None, ["r1"])], None))
        give(flat, grades, q1=5, q2=4)
        self.assertEqual(gs.student_summary(flat, grades, "s1")["marks"]["percent"], 50.0)
        split, grades = paper(([("q1", 10, [])], None), ([("q2", None, ["r1"])], None))
        give(split, grades, q1=5, q2=4)
        result = gs.student_summary(split, grades, "s1")
        self.assertEqual(result["marks"]["percent"], 50.0)
        self.assertEqual([(s["total"], s["max"], s["percent"]) for s in result["sections"]],
                         [(5, 10, 50.0), (0, 0, None)])

    def test_choice_group_cannot_mix_marks_and_levels(self):
        config, _ = paper(([("q1", 10, []), ("q2", None, ["r1"])], None),
                          choice=[{"id": "g1", "questions": ["q1", "q2"], "answer": 1}])
        with self.assertRaises(UserError) as ctx:
            gs.check_choice_groups(config)
        self.assertEqual(ctx.exception.code, "choice_group_mixed")


class SectionTests(unittest.TestCase):
    def test_a_paper_without_sections_is_one_section(self):
        config, grades = marks_exam()
        for qid, v in (("q1", 4), ("q2", 7), ("q3", NA), ("q4", 8)):
            gs.set_grade(config, grades, "s1", qid, v)
        self.assertEqual([len(s["questions"]) for s in gs.sections(config)], [4])
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["sections"], [{"id": gs.WHOLE_PAPER, "name": "", "total": 19, "max": 33,
                                               "percent": 57.6, "share": None, "weighted_marks": None}])
        self.assertFalse(result["marks"]["weighted"])

    def test_a_marks_only_exam_needs_nothing_new(self):
        config = {"students": [{"id": "s1"}], "questions": [{"id": "q1", "label": "Q1", "max": 4}]}
        grades = model.new_grades("x")
        give(config, grades, q1=3)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual((result["marks"]["total"], result["marks"]["percent"], result["rubrics"]),
                         (3, 75.0, {}))
        self.assertEqual(gs.class_summary(config, grades)["overall"]["total"]["max"], 3)

    def test_section_totals_keep_choice_groups_inside(self):
        group = [{"id": "g1", "questions": ["q2", "q3"], "answer": 1}]
        config, grades = paper(([("q1", 5, [])], None), ([("q2", 10, []), ("q3", 8, [])], None), choice=group)
        gs.check_choice_groups(config)
        give(config, grades, q1=5, q2=3, q3=6)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual([(s["total"], s["max"]) for s in result["sections"]], [(5, 5), (6, 10)])
        self.assertEqual((result["marks"]["total"], result["marks"]["max"]), (11, 15))

    def test_a_choice_group_across_two_sections_is_refused(self):
        group = [{"id": "g1", "questions": ["q1", "q2"], "answer": 1}]
        config, _ = paper(([("q1", 5, [])], None), ([("q2", 5, [])], None), choice=group)
        with self.assertRaises(UserError) as ctx:
            gs.check_choice_groups(config)
        self.assertEqual(ctx.exception.code, "choice_group_across_sections")


class WeightingTests(unittest.TestCase):
    def test_the_plans_example(self):
        config, grades = paper(([("a", 25, [])], 50), ([("b", 40, [])], 50), weighted=True)
        give(config, grades, a=22, b=30)
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual(marks["percent"], 81.5)                    # not 80%, as adding would give
        self.assertEqual((marks["total"], marks["max"], marks["weighted"]), (52, 65, True))
        config["weighted"] = False
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["percent"], 80.0)

    def test_weighted_marks_for_a_section(self):
        config, grades = paper(([("a", 24, [])], 20), ([("b", 50, [])], 80), weighted=True)
        give(config, grades, a=24, b=25)
        rows = gs.student_summary(config, grades, "s1")["sections"]
        self.assertEqual([(r["share"], r["percent"], r["weighted_marks"]) for r in rows],
                         [(20, 100.0, 20.0), (80, 50.0, 40.0)])

    def test_rounds_only_once_at_the_end(self):
        config, grades = paper(([("a", 3, [])], 50), ([("b", 9, [])], 50), weighted=True)
        give(config, grades, a=1, b=5)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual([s["percent"] for s in result["sections"]], [33.3, 55.6])
        self.assertEqual(result["marks"]["percent"], 44.4)          # the rounded figures give 44.45

    def test_rounds_half_up(self):
        config, grades = paper(([("a", 16, [])], 50), ([("b", 16, [])], 50), weighted=True)
        give(config, grades, a=13, b=12)
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["percent"], 78.1)    # 78.125
        config, grades = paper(([("a", 16, [])], 50), ([("b", 8, [])], 50), weighted=True)
        give(config, grades, a=9, b=3)
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["percent"], 46.9)    # 46.875

    def test_full_marks_is_exactly_100(self):
        config, grades = paper(*[([(f"q{i}", 7, [])], None) for i in range(1, 8)], weighted=True)
        give(config, grades, **{f"q{i}": 7 for i in range(1, 8)})
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["percent"], 100.0)

    def test_needs_two_sections_with_marks(self):
        config, grades = paper(([("a", 10, [])], None), ([("b", None, ["r1"])], None), weighted=True)
        self.assertFalse(gs.weighting_on(config))
        self.assertEqual(config["sections"][0]["weight"], 100)
        self.assertIsNone(config["sections"][1]["weight"])
        give(config, grades, a=5)
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["weighted"], marks["percent"]), (False, 50.0))

    def test_report_percent_replaces_the_total_override(self):
        config, grades = paper(([("a", 25, [])], 50), ([("b", 40, [])], 50), weighted=True)
        give(config, grades, a=22, b=30)
        gs.set_report_total(config, grades, "s1", 60)               # no effect with weighting on
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["report_percent"], marks["adjusted"]), (81.5, False))
        gs.set_report_percent(grades, "s1", "85")
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["percent"], marks["report_percent"], marks["adjusted"]), (81.5, 85, True))
        config["weighted"] = False                                  # the total override is back
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["report_total"], marks["report_percent"], marks["adjusted"]), (60, 92.3, True))
        with self.assertRaises(UserError):
            gs.set_report_percent(grades, "s1", "lots")

    def test_shares_add_up_to_100_for_one_to_seven_sections(self):
        for n in range(1, 8):
            config, _ = paper(*[([(f"q{i}", 5, [])], None) for i in range(n)])
            shares = [s["weight"] for s in config["sections"]] or [100]
            self.assertEqual(sum(shares), 100, n)
            self.assertLessEqual(max(shares) - min(shares), 1, n)
            self.assertEqual(shares, sorted(shares, reverse=True), n)    # the leftover goes first
        config, _ = paper(*[([(f"q{i}", 5, [])], None) for i in range(3)])
        self.assertEqual([s["weight"] for s in config["sections"]], [34, 33, 33])

    def test_typed_shares_stay_and_the_rest_rebalance(self):
        for n in range(2, 8):
            for typed in range(0, n):
                config, _ = paper(*[([(f"q{i}", 5, [])], 10 if i < typed else None) for i in range(n)])
                shares = [s["weight"] for s in config["sections"]]
                self.assertEqual(sum(shares), 100, (n, typed))
                self.assertEqual(shares[:typed], [10] * typed, (n, typed))

    def test_one_section_always_stays_automatic(self):
        config, _ = paper(([("a", 5, [])], 30), ([("b", 5, [])], 30))
        self.assertEqual([(s["weight"], s["weight_typed"]) for s in config["sections"]],
                         [(30, True), (70, False)])


class CriterionMarksTests(unittest.TestCase):
    """The example in Exam-Section-Plan.md §3: Criterion A has all of Section A
    and 24 / 30 of Section B's 40 marks."""

    def exam(self, weighted):
        config, grades = paper(([("a", 25, ["r1"])], 50 if weighted else None),
                               ([("b1", 30, ["r1"]), ("b2", 10, ["r2"])], 50 if weighted else None),
                               weighted=weighted)
        give(config, grades, a=22, b1=24, b2=6)
        return config, grades

    def test_without_weighting(self):
        r1 = gs.student_summary(*self.exam(False), "s1")["rubrics"]["r1"]
        self.assertEqual(r1["marks"], {"total": 46, "max": 55, "percent": 83.6})

    def test_with_weighting(self):
        r1 = gs.student_summary(*self.exam(True), "s1")["rubrics"]["r1"]
        self.assertEqual(r1["marks"]["percent"], 84.6)

    def test_a_question_on_two_criteria_counts_in_both(self):
        config, grades = paper(([("q1", 10, ["r1", "r2"])], None))
        give(config, grades, q1=7)
        result = gs.student_summary(config, grades, "s1")["rubrics"]
        self.assertEqual(result["r1"]["marks"], result["r2"]["marks"])
        self.assertEqual(result["r1"]["marks"]["total"], 7)

    def test_full_marks_on_part_of_the_paper_reaches_100(self):
        for weighted in (False, True):
            config, grades = paper(([("a", 25, ["r1"]), ("x", 15, [])], 30 if weighted else None),
                                   ([("b", 10, ["r1"]), ("y", 30, [])], 70 if weighted else None),
                                   weighted=weighted)
            give(config, grades, a=25, b=10, x=0, y=0)
            self.assertEqual(gs.student_summary(config, grades, "s1")["rubrics"]["r1"]["marks"]["percent"],
                             100.0, weighted)

    def test_one_criterion_with_both_marks_and_grades_spread_across_sections(self):
        config, grades = paper(([("q1", 10, ["r2"]), ("q2", None, ["r2"])], None),
                               ([("q3", None, ["r2"]), ("q4", None, ["r1"]), ("q5", 5, ["r2"])], None))
        give(config, grades, q1=6, q2=6, q3=5, q4=3, q5=5)
        r2 = gs.student_summary(config, grades, "s1")["rubrics"]["r2"]
        self.assertEqual(r2["marks"], {"total": 11, "max": 15, "percent": 73.3})
        self.assertEqual([g["level"] for g in r2["grades"]], [6, 5])

    def test_ungraded_stays_in_the_maximum(self):
        config, grades = paper(([("q1", 10, ["r1"]), ("q2", 10, ["r1"])], None))
        give(config, grades, q1=5)
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["rubrics"]["r1"]["marks"], {"total": 5, "max": 20, "percent": 25.0})
        self.assertFalse(result["complete"])

    def test_a_choice_question_that_did_not_count_is_left_out(self):
        group = [{"id": "g1", "questions": ["q1", "q2"], "answer": 1}]
        config, grades = paper(([("q1", 10, ["r1"]), ("q2", 10, ["r2"]), ("q3", 10, ["r1"])], None), choice=group)
        give(config, grades, q1=8, q2=3, q3=5)
        result = gs.student_summary(config, grades, "s1")["rubrics"]
        self.assertEqual(result["r1"]["marks"], {"total": 13, "max": 20, "percent": 65.0})
        self.assertIsNone(result["r2"]["marks"])

    def test_ticks_can_change_after_grading_without_touching_marks(self):
        config, grades = paper(([("q1", 10, [])], None))
        give(config, grades, q1=7)
        config["questions"][0]["rubric_ids"] = ["r1"]
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(grades["grades"]["s1"]["q1"]["value"], 7)
        self.assertEqual((result["marks"]["total"], result["rubrics"]["r1"]["marks"]["total"]), (7, 7))


class ClassTests(unittest.TestCase):
    def test_class_summary_and_progress(self):
        group = [{"id": "g1", "questions": ["q3", "q4"], "answer": 1}]
        config, grades = marks_exam(group)
        for sid, values in (("s1", (5, 10, 8, NA)), ("s2", (3, NA, NA, 6))):
            for qid, v in zip(("q1", "q2", "q3", "q4"), values):
                gs.set_grade(config, grades, sid, qid, v)
        gs.set_overall_comment(grades, "s1", "Well done")
        summary = gs.class_summary(config, grades)
        self.assertEqual(summary["questions"]["q1"],
                         {"average": 4.0, "max": 5, "min": 3, "count": 2})
        self.assertEqual(summary["questions"]["q2"]["min"], 0)        # NA counts 0
        self.assertEqual(summary["questions"]["q3"]["count"], 1)      # NA not chosen
        self.assertEqual(summary["overall"]["total"]["max"], 23)
        self.assertEqual(summary["students"][0]["comment"], "Well done")
        self.assertEqual(gs.progress(config, grades),
                         {"graded": 8, "total": 8, "students_done": 2, "students_total": 2})



class CommentLimitTests(unittest.TestCase):
    def setUp(self):
        self.config, self.grades = marks_exam()

    def question(self, comment):
        gs.set_grade(self.config, self.grades, "s1", "q1", comment=comment)

    def refused(self, call, limit):
        with self.assertRaises(UserError) as ctx:
            call()
        self.assertEqual((ctx.exception.code, ctx.exception.params["limit"]), ("comment_too_long", limit))

    def test_question_comment_stops_at_300(self):
        self.question("x" * 300)
        self.refused(lambda: self.question("x" * 301), 300)
        self.assertEqual(self.grades["grades"]["s1"]["q1"]["comment"], "x" * 300)

    def test_overall_comment_stops_at_600(self):
        gs.set_overall_comment(self.grades, "s1", "x" * 600)
        self.refused(lambda: gs.set_overall_comment(self.grades, "s1", "x" * 601), 600)
        self.assertEqual(self.grades["overall"]["s1"]["comment"], "x" * 600)

    def test_japanese_is_counted_in_characters(self):
        self.question("字" * 300)
        self.refused(lambda: self.question("字" * 301), 300)

    def test_a_refused_comment_changes_nothing_else(self):
        self.refused(lambda: gs.set_grade(self.config, self.grades, "s1", "q1", value=4, comment="x" * 301), 300)
        self.assertEqual(self.grades["grades"], {})

    def test_a_saved_longer_comment_is_kept_or_shortened_but_cannot_grow(self):
        long_ = "x" * 400
        self.grades["grades"] = {"s1": {"q1": {"value": 3, "comment": long_}}}
        self.grades["overall"] = {"s1": {"comment": "y" * 700}}
        gs.set_grade(self.config, self.grades, "s1", "q1", value=4)            # a grade alone leaves it
        self.assertEqual(self.grades["grades"]["s1"]["q1"]["comment"], long_)
        self.question(long_)                                                    # saving it unchanged
        self.question("z" * 400)                                                # the same length, reworded
        self.refused(lambda: self.question("x" * 401), 300)
        self.question("x" * 350)
        self.refused(lambda: self.question("x" * 351), 300)
        gs.set_overall_comment(self.grades, "s1", "y" * 700)
        self.refused(lambda: gs.set_overall_comment(self.grades, "s1", "y" * 701), 600)
        gs.set_overall_comment(self.grades, "s1", "y" * 10)

    def test_the_generated_line_does_not_count(self):
        line = "Areas to develop: check calculations."
        self.grades["grades"] = {"s1": {"q1": {"value": None, "comment": line, "keyword_text": line}}}
        self.question(f"{line}\n{'x' * 300}")
        self.refused(lambda: self.question(f"{line}\n{'x' * 301}"), 300)

if __name__ == "__main__":
    unittest.main()
