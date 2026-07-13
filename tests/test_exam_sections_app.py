"""Phase 5 (Exam Slicer v2 plan) — CAM app-side section logic.

Exercises the non-rendering app.py logic added in Phase 5D/5E without booting
Streamlit (same seams as tests/test_export_beacon_sync.py — ``app.st`` is a
SimpleNamespace over a plain dict, ``app.gb`` a fixture gradebook, ``app.persist``
stubbed):

  * ``_apply_exam_bands`` skips students whose choice section is still pending
    (`?`) and bands the resolved ones from their *resolved* total.
  * ``assignment_table`` raw average excludes pending students and uses resolved
    totals.
  * The name-crop path helpers resolve CGW's on-disk convention.

Run:  python -m unittest tests.test_exam_sections_app
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402
from engine import Assignment, ExamResult, Gradebook  # noqa: E402

CLASS = "Test MYP Class"

# One choice section B (require 1 of Q2/Q3) + an all-required A (Q1).
SECTIONS = [
    {"name": "A", "required": None, "questions": [{"label": "Q1", "max": 10}]},
    {"name": "B", "required": 1,
     "questions": [{"label": "Q2", "max": 8}, {"label": "Q3", "max": 8}]},
]


class _Base(unittest.TestCase):
    def setUp(self):
        self.gb = Gradebook()
        # Ada over-answered B (Q2 + Q3) -> pending. Bob answered only Q2 -> ok.
        ada = self.gb.get_or_create("Ada")
        ada.exam_results["Mid"] = ExamResult(
            "Mid", total=23, max_total=18,
            questions={"Q1": 9, "Q2": 6, "Q3": 8})
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


class ApplyBandsPendingSkip(_Base):
    def test_pending_student_skipped_resolved_banded(self):
        asg = self.gb.assignments[0]
        results = [(self.gb.students["Ada"], self.gb.students["Ada"].exam_results["Mid"]),
                   (self.gb.students["Bob"], self.gb.students["Bob"].exam_results["Mid"])]
        # Both have a band widget value, but Ada is pending -> must be skipped.
        self.ss["band_Mid_Ada"] = 7
        self.ss["band_Mid_Bob"] = 5
        applied = app._apply_exam_bands(asg, "A", results)
        self.assertEqual(applied, 1)
        # Bob got a score; Ada got none (pending).
        self.assertTrue(self.gb.students["Bob"].scores.get("A"))
        self.assertFalse(self.gb.students["Ada"].scores.get("A"))
        # Bob's note reflects his resolved total 14/18 (Q1 8 + Q2 6).
        note = self.gb.students["Bob"].scores["A"][0].note
        self.assertIn("14/18", note)

    def test_resolving_ada_then_bands_her(self):
        asg = self.gb.assignments[0]
        # Teacher resolves B by choosing Q3 (the 8).
        self.gb.students["Ada"].exam_results["Mid"].chosen["B"] = ["Q3"]
        results = [(self.gb.students["Ada"], self.gb.students["Ada"].exam_results["Mid"])]
        self.ss["band_Mid_Ada"] = 8
        applied = app._apply_exam_bands(asg, "A", results)
        self.assertEqual(applied, 1)
        note = self.gb.students["Ada"].scores["A"][0].note
        self.assertIn("17/18", note)   # Q1 9 + Q3 8


class SectionBandsApply(_Base):
    """Phase 6: applying persists per-strand levels from the section widgets and
    folds them into the score note; the panel-shape helper flags real sections."""

    def test_persists_section_bands_and_note(self):
        asg = self.gb.assignments[0]
        bob = self.gb.students["Bob"]
        results = [(bob, bob.exam_results["Mid"])]
        self.ss["band_Mid_Bob"] = 5
        self.ss["seclvl_Mid_Bob_A"] = 6
        self.ss["seclvl_Mid_Bob_B"] = 4
        app._apply_exam_bands(asg, "A", results)
        self.assertEqual(bob.exam_results["Mid"].section_bands, {"A": 6, "B": 4})
        note = bob.scores["A"][0].note
        self.assertIn("sections: A 6, B 4", note)

    def test_pending_section_omitted_from_note(self):
        # Ada is pending in B until resolved; resolve so she can band, but her
        # B level widget is unset -> B is simply omitted, A still recorded.
        asg = self.gb.assignments[0]
        ada = self.gb.students["Ada"]
        ada.exam_results["Mid"].chosen["B"] = ["Q3"]
        results = [(ada, ada.exam_results["Mid"])]
        self.ss["band_Mid_Ada"] = 8
        self.ss["seclvl_Mid_Ada_A"] = 8
        app._apply_exam_bands(asg, "A", results)
        self.assertEqual(ada.exam_results["Mid"].section_bands, {"A": 8})
        self.assertIn("sections: A 8", ada.scores["A"][0].note)

    def test_has_real_sections_helper(self):
        self.assertTrue(app._exam_has_real_sections(SECTIONS))
        self.assertFalse(app._exam_has_real_sections(None))
        self.assertFalse(app._exam_has_real_sections([]))
        # A lone synthesized default section is not "real" strand structure.
        default = [{"name": "All Questions", "required": None,
                    "questions": [{"label": "Q1", "max": 10}]}]
        self.assertFalse(app._exam_has_real_sections(default))
        # A single *renamed* section is real.
        renamed = [{"name": "Knowing", "required": None,
                    "questions": [{"label": "Q1", "max": 10}]}]
        self.assertTrue(app._exam_has_real_sections(renamed))


class AssignmentTableRawAvg(_Base):
    def test_raw_avg_excludes_pending(self):
        # Only Bob (resolved, total 14) counts; Ada pending -> excluded.
        rows = app.assignment_table()
        mid = next(r for r in rows if r["name"] == "Mid")
        self.assertEqual(mid["raw_avg"], 14.0)
        self.assertEqual(mid["max_total"], 18)

    def test_raw_avg_includes_ada_once_resolved(self):
        self.gb.students["Ada"].exam_results["Mid"].chosen["B"] = ["Q3"]
        rows = app.assignment_table()
        mid = next(r for r in rows if r["name"] == "Mid")
        # Ada 17 + Bob 14 -> mean 15.5
        self.assertEqual(mid["raw_avg"], 15.5)


class NameCropPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_namecrop_")
        self._orig_dir = app.EXAM_CROPS_DIR
        app.EXAM_CROPS_DIR = self.tmp

    def tearDown(self):
        app.EXAM_CROPS_DIR = self._orig_dir
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resolves_existing_crop(self):
        d = os.path.join(self.tmp, CLASS, "Mid", "__name__")
        os.makedirs(d)
        crop = os.path.join(d, "Ada.png")
        with open(crop, "wb") as f:
            f.write(b"\x89PNG\r\n")
        self.assertTrue(app.exam_has_name_crops(CLASS, "Mid"))
        self.assertEqual(app.exam_name_crop_path(CLASS, "Mid", "Ada"), crop)
        # A student with no crop resolves to "".
        self.assertEqual(app.exam_name_crop_path(CLASS, "Mid", "Nobody"), "")

    def test_absent_tree_is_falsey(self):
        self.assertFalse(app.exam_has_name_crops(CLASS, "Nope"))
        self.assertEqual(app.exam_name_crop_path(CLASS, "Nope", "Ada"), "")


if __name__ == "__main__":
    unittest.main()
