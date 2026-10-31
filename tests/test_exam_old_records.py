"""Exam records from the old CGW exam grader (convergence Stage 4, D2/D3/D5).

CGW's exam code is gone, but a database may still hold its exams: an
``Assignment`` with ``sections`` and ``ExamResult``s with ``chosen`` /
``section_bands``. These must load and save unchanged, and CAM now treats them
like any marks exam (band from the stored total, no ``?``, no strand levels).

Same seams as tests/test_export_beacon_sync.py — ``app.st`` is a
SimpleNamespace over a plain dict, ``app.gb`` a fixture gradebook, ``app.persist``
stubbed. Run:  python -m unittest tests.test_exam_old_records
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
from engine import (  # noqa: E402
    Assignment, ExamResult, Gradebook, IngestionPipeline,
    assignment_from_dict, assignment_to_dict,
    exam_result_from_dict, exam_result_to_dict,
)

CLASS = "Test MYP Class"

# A CGW-era exam: one choice section B (require 1 of Q2/Q3) + an all-required A.
SECTIONS = [
    {"name": "A", "required": None, "questions": [{"label": "Q1", "max": 10}]},
    {"name": "B", "required": 1,
     "questions": [{"label": "Q2", "max": 8}, {"label": "Q3", "max": 8}]},
]


class OldRecordsRoundTrip(unittest.TestCase):
    def test_old_fields_survive_save_and_load(self):
        asg = Assignment(name="Mid", criteria=["A"], class_name=CLASS,
                         is_exam=True, max_total=18,
                         question_labels=["Q1", "Q2", "Q3"], sections=SECTIONS)
        self.assertEqual(assignment_from_dict(assignment_to_dict(asg)).sections,
                         SECTIONS)
        r = ExamResult("Mid", total=17, max_total=18,
                       questions={"Q1": 9, "Q2": 6, "Q3": 8},
                       chosen={"B": ["Q3"]}, section_bands={"A": 7, "B": 8})
        back = exam_result_from_dict(exam_result_to_dict(r))
        self.assertEqual(back.chosen, {"B": ["Q3"]})
        self.assertEqual(back.section_bands, {"A": 7, "B": 8})
        self.assertEqual(back.mode, "")


class _Base(unittest.TestCase):
    def setUp(self):
        self.gb = Gradebook()
        # Ada over-answered B in CGW and never had it resolved; Bob did not.
        ada = self.gb.get_or_create("Ada")
        ada.exam_results["Mid"] = ExamResult(
            "Mid", total=17, max_total=18,
            questions={"Q1": 9, "Q2": 6, "Q3": 8}, section_bands={"A": 7})
        bob = self.gb.get_or_create("Bob")
        bob.exam_results["Mid"] = ExamResult(
            "Mid", total=14, max_total=18, questions={"Q1": 8, "Q2": 6})
        self.gb.register_assignment(Assignment(
            name="Mid", criteria=[], class_name=CLASS, is_exam=True,
            max_total=18, question_labels=["Q1", "Q2", "Q3"], sections=SECTIONS))

        self.ss = {
            "active_class": CLASS,
            "archived": set(),
            "active": {},
            "date_override": {},
        }
        self._orig = {"st": app.st, "gb": app.gb, "persist": app.persist}
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.persist = lambda *a, **k: None

    def tearDown(self):
        app.st = self._orig["st"]
        app.gb = self._orig["gb"]
        app.persist = self._orig["persist"]

    def _results(self):
        return [(self.gb.students[k], self.gb.students[k].exam_results["Mid"])
                for k in ("Ada", "Bob")]


class OldExamBanding(_Base):
    def test_bands_from_stored_total_and_writes_no_strand_levels(self):
        self.ss["band_Mid_Ada"] = 7
        self.ss["band_Mid_Bob"] = 6
        asg = self.gb.assignments[0]
        self.assertEqual(app._apply_exam_bands(asg, "A", self._results()), 2)
        ada = self.gb.students["Ada"]
        self.assertEqual(ada.scores["A"][0].value, 7)
        self.assertEqual(ada.scores["A"][0].note, "banded from raw 17/18")
        # The old strand level is kept as it was, and nothing new is written.
        self.assertEqual(ada.exam_results["Mid"].section_bands, {"A": 7})
        self.assertEqual(self.gb.students["Bob"].exam_results["Mid"].section_bands, {})

    def test_raw_average_uses_stored_totals(self):
        mid = next(r for r in app.assignment_table() if r["name"] == "Mid")
        self.assertEqual(mid["raw_avg"], 15.5)     # (17 + 14) / 2
        self.assertEqual(mid["max_total"], 18)


class OldPoolRows(_Base):
    def test_old_pooled_exam_row_still_assigns(self):
        row = {"csv_key": "scan_007", "is_exam": True, "total": 12,
               "max_total": 18, "questions": {"Q1": 6, "Q2": 6}, "comment": "ok"}
        result = IngestionPipeline(self.gb).materialize_exam_row("Mid", "Cy", row)
        self.assertEqual((result.total, result.max_total), (12, 18))
        self.assertEqual(result.questions, {"Q1": 6, "Q2": 6})
        self.assertIs(self.gb.students["Cy"].exam_results["Mid"], result)

    def test_exam_tile_captions_file_name_and_raw_total(self):
        row = {"csv_key": "scan_0007", "is_exam": True, "total": 31,
               "max_total": 45}
        self.assertEqual(app._work_caption(row), "scan_0007 · 31/45")
        self.assertEqual(app._work_caption({"files": "img_1.jpg; img_0.jpg"}),
                         "img_1.jpg")


if __name__ == "__main__":
    unittest.main()
