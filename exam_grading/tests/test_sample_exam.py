"""The sample exam's guide tells testers what to expect, so it must be right.

Run:  python -m unittest tests.test_sample_exam
"""

import os
import tempfile
import unittest

from engine import grading_summary as gs, roster, rubrics, tables, workflow
from tools import make_sample_exam as sample


def paper(mixed: bool = False, sections=(), weighted: bool = False) -> dict:
    """The exam set up as the guide says, with no scans: only grades matter here."""
    tops = sample.OUT_OF
    on_rubric = {"Q4": ["r2"], "Q5": ["r2", "r3"], "Q6": ["r3"], "Q7": ["r3"]}
    config = {"students": [{"id": f"s{i}"} for i in range(len(sample.GRADES))],
              "rubrics": [rubrics.normalize_rubric({"id": f"r{i}", "name": name, "bands": [
                  {"levels": levels, "descriptor": words} for levels, words in bands]})
                  for i, (name, bands) in enumerate(sample.RUBRICS["en"], 1)],
              "questions": [{"id": q, "label": q, "boxes": ["page1!A1"],
                             "max": None if mixed and q in on_rubric else tops[q],
                             "rubric_ids": on_rubric.get(q, ["r1"])} for q in tops],
              "choice_groups": [{"id": "g1", "questions": ["Q6", "Q7"], "answer": 1}],
              "sections": [dict(id=f"sec{i}", name="", weight=None, weight_typed=False)
                           for i in range(1, len(sections) + 1)],
              "weighted": weighted}
    for i, members in enumerate(sections, 1):
        for q in config["questions"]:
            if q["id"] in members:
                q["section_id"] = f"sec{i}"
    gs.rebalance_shares(config)
    return config


def graded(config: dict, mixed: bool = False) -> dict:
    grades = {"grades": {}, "overall": {}}
    for i, plan in enumerate(sample.GRADES):
        sid = f"s{i}"
        for qid, grade in plan.items():
            if grade is sample.NA:
                gs.set_grade(config, grades, sid, qid, gs.NOT_ANSWERED)
            elif isinstance(grade, tuple) and mixed:
                gs.set_grade(config, grades, sid, qid, grade[0], rubric_id="r2")
                gs.set_grade(config, grades, sid, qid, grade[1], rubric_id="r3")
            else:
                gs.set_grade(config, grades, sid, qid, sample.number(grade))
    return grades


class ExpectedResultsTests(unittest.TestCase):
    def results(self, config, grades):
        return [gs.student_summary(config, grades, s["id"]) for s in config["students"]]

    def test_exam_1_total(self):
        config = paper()
        for plan, result in zip(sample.GRADES, self.results(config, graded(config))):
            want = sample.expected_results(plan)
            self.assertEqual(result["marks"]["max"], 48)
            self.assertEqual(result["marks"]["total"], want["all_marks"])
            self.assertEqual(str(result["marks"]["percent"]), str(want["all_percent"]))

    def test_exam_1_weighted(self):
        config = paper(sections=(("Q1",), ("Q2", "Q3"), ("Q4", "Q5", "Q6", "Q7")), weighted=True)
        self.assertEqual([s["weight"] for s in config["sections"]], list(sample.SHARES))
        for plan, result in zip(sample.GRADES, self.results(config, graded(config))):
            self.assertEqual(str(result["marks"]["percent"]), str(sample.expected_results(plan)["weighted"]))

    def test_exam_2_marks_ignore_the_levels(self):
        config = paper(mixed=True, sections=(("Q1", "Q2", "Q3"), ("Q4", "Q5", "Q6", "Q7")))
        for plan, result in zip(sample.GRADES, self.results(config, graded(config, mixed=True))):
            want = sample.expected_results(plan)
            self.assertEqual(result["marks"]["max"], 24)
            self.assertEqual(result["marks"]["total"], want["mixed_marks"])
            self.assertEqual(str(result["marks"]["percent"]), str(want["mixed_percent"]))
            self.assertEqual(result["rubrics"]["r1"]["marks"]["total"], want["mixed_marks"])

    def test_the_best_of_q6_and_q7_counts(self):
        third = sample.expected_results(sample.GRADES[2])
        self.assertEqual(third["all_marks"], 48)       # 8 on Q6 and 3 on Q7


class SampleFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def rows(self, path):
        with open(path, "rb") as fh:
            return tables.read_table(os.path.basename(path), fh.read())

    def test_the_rubric_file_can_be_uploaded(self):
        for language in sample.LANGUAGES:
            path = os.path.join(self.tmp.name, f"rubrics-{language}.xlsx")
            sample.make_rubrics(language, path)
            config = {}
            workflow.set_rubrics(config, rubrics.import_rubrics(self.rows(path)))
            self.assertEqual([r["name"] for r in config["rubrics"]], [name for name, _ in sample.RUBRICS[language]])
            self.assertEqual(rubrics.rubric_max(config["rubrics"][0]), 8)

    def test_the_class_list_finds_family_and_given_names(self):
        for language in sample.LANGUAGES:
            path = os.path.join(self.tmp.name, f"class-{language}.xlsx")
            sample.make_class_list(language, path)
            rows = self.rows(path)
            self.assertTrue(roster.guess_header(rows))
            self.assertEqual(roster.guess_name_columns(rows, True), [1, 2])
            self.assertEqual(len(roster.extract_names(rows, [1, 2], True)), len(sample.GRADES))

    def test_there_are_grades_for_every_student_and_question(self):
        for plan in sample.GRADES:
            self.assertEqual(set(plan), set(sample.OUT_OF))
        for language in sample.LANGUAGES:
            self.assertEqual(len(sample.STUDENTS[language]), len(sample.GRADES))
            self.assertEqual(set(sample.WRITTEN[language]), set(sample.OUT_OF) - {"Q1"})


if __name__ == "__main__":
    unittest.main()
