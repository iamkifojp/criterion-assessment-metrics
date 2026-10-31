"""Recording grades, totals, choice questions, rubric averages, overrides.

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
        gs.set_report_total(grades, "s1", 22)
        marks = gs.student_summary(config, grades, "s1")["marks"]
        self.assertEqual((marks["total"], marks["report_total"], marks["adjusted"]),
                         (20, 22, True))
        gs.set_report_total(grades, "s1", None)
        self.assertFalse(gs.student_summary(config, grades, "s1")["marks"]["adjusted"])
        gs.set_report_total(grades, "s1", " 21 ")                   # typed in a text box
        self.assertEqual(gs.student_summary(config, grades, "s1")["marks"]["report_total"], 21)
        for bad in ("abc", -1, True):
            with self.assertRaises(UserError, msg=bad):
                gs.set_report_total(grades, "s1", bad)


class RubricTests(unittest.TestCase):
    def test_average_per_criterion_rounds_half_up(self):
        config, grades = rubric_exam()
        for qid, v in (("q1", 5), ("q2", 6), ("q3", NA)):
            gs.set_grade(config, grades, "s1", qid, v)
        result = gs.student_summary(config, grades, "s1")["rubrics"]
        self.assertEqual(result["r1"], {"average": 5.5, "suggested": 6, "final": 6,
                                        "adjusted": False})
        self.assertEqual(result["r2"]["average"], 0.0)

    def test_teacher_final_level(self):
        config, grades = rubric_exam()
        gs.set_grade(config, grades, "s1", "q1", 5)
        gs.set_grade(config, grades, "s1", "q2", 6)
        gs.set_final_level(config, grades, "s1", "r1", 5)
        r1 = gs.student_summary(config, grades, "s1")["rubrics"]["r1"]
        self.assertEqual((r1["suggested"], r1["final"], r1["adjusted"]), (6, 5, True))
        with self.assertRaises(UserError):
            gs.set_final_level(config, grades, "s1", "r1", 9)
        with self.assertRaises(UserError):
            gs.set_final_level(config, grades, "s1", "r9", 1)

    def test_no_grades_yet(self):
        config, grades = rubric_exam()
        r1 = gs.student_summary(config, grades, "s1")["rubrics"]["r1"]
        self.assertIsNone(r1["average"])
        self.assertIsNone(r1["final"])


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

    def test_averages_use_every_criterion(self):
        config, grades = multi_exam()
        gs.set_grade(config, grades, "s1", "q1", 6)
        gs.set_grade(config, grades, "s1", "q2", 7, rubric_id="r2")
        gs.set_grade(config, grades, "s1", "q2", 4, rubric_id="r3")
        gs.set_grade(config, grades, "s1", "q3", 5)
        summary = gs.student_summary(config, grades, "s1")
        self.assertTrue(summary["complete"])
        self.assertEqual({rid: r["average"] for rid, r in summary["rubrics"].items()},
                         {"r1": 6.0, "r2": 7.0, "r3": 4.5})
        self.assertEqual(summary["rubrics"]["r3"]["suggested"], 5)
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
        self.assertFalse(gs.has_grades(grades))
        gs.set_grade(config, grades, "s1", "q2", 3, rubric_id="r3")
        self.assertTrue(gs.has_grades(grades))
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
        self.assertIsNone(result["rubrics"]["r3"]["average"])
        gs.set_choice(config, grades, "s1", "g1", ["q3"])         # the teacher picks Q3
        result = gs.student_summary(config, grades, "s1")
        self.assertEqual(result["rubrics"]["r3"]["average"], 5.0)
        self.assertIsNone(result["rubrics"]["r2"]["average"])

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


if __name__ == "__main__":
    unittest.main()
