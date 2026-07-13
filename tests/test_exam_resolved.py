"""Phase 5 (Exam Slicer v2 plan) — section-aware exam scoring (CAM engine half).

Covers docs/EXAM_SLICER_V2_AND_SYNC_PLAN.md Phase 5A/5B:

  * ``section_state`` / ``resolved_total`` / ``resolved_max`` /
    ``exam_is_pending`` over every shape — no sections, all-required, choice
    resolved / unresolved / over-answered, ties, missing answers.
  * The definition sidecar (``<csv>.meta.json``) attaches sections on ingest and
    recomputes each result's max via the resolved rule; a sidecar-less CSV is
    byte-identical to the pre-phase behaviour.
  * ``chosen`` teacher resolutions survive a purge-replace re-ingest.

Framework-free engine only. Run:

    python -m unittest tests.test_exam_resolved
"""

import csv
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ingestion import IngestionPipeline, load_exam_sidecar  # noqa: E402
from engine.models import (  # noqa: E402
    ExamResult,
    exam_is_pending,
    resolved_max,
    resolved_suggested_band,
    resolved_total,
    section_max,
    section_state,
)


def _sec(name, required, *questions):
    """questions: (label, max) tuples."""
    return {"name": name, "required": required,
            "questions": [{"label": lbl, "max": mx} for lbl, mx in questions]}


class TestSectionState(unittest.TestCase):
    def test_all_required_counts_every_answer(self):
        sec = _sec("A", None, ("Q1", 5), ("Q2", 5))
        r = ExamResult("Exam", questions={"Q1": 4, "Q2": 3})
        st = section_state(r, sec)
        self.assertEqual(st.answered, ["Q1", "Q2"])
        self.assertEqual(st.subtotal, 7)
        self.assertEqual(st.section_max, 10)
        self.assertFalse(st.over_answered)
        self.assertTrue(st.resolved)
        self.assertFalse(st.pending)

    def test_missing_answer_lowers_subtotal_not_max(self):
        sec = _sec("A", None, ("Q1", 5), ("Q2", 5))
        r = ExamResult("Exam", questions={"Q1": 4})   # Q2 blank
        st = section_state(r, sec)
        self.assertEqual(st.answered, ["Q1"])
        self.assertEqual(st.subtotal, 4)
        self.assertEqual(st.section_max, 10)
        self.assertFalse(st.pending)

    def test_choice_answered_exactly_required_auto_resolved(self):
        sec = _sec("B", 2, ("Q1", 8), ("Q2", 8), ("Q3", 8))
        r = ExamResult("Exam", questions={"Q1": 6, "Q2": 5})   # answered 2 of 3
        st = section_state(r, sec)
        self.assertFalse(st.over_answered)
        self.assertTrue(st.resolved)
        self.assertEqual(st.subtotal, 11)
        self.assertEqual(st.section_max, 16)   # 2 largest of {8,8,8}

    def test_choice_over_answered_is_pending_until_chosen(self):
        sec = _sec("B", 2, ("Q1", 8), ("Q2", 8), ("Q3", 8))
        r = ExamResult("Exam", questions={"Q1": 6, "Q2": 5, "Q3": 7})
        st = section_state(r, sec)
        self.assertTrue(st.over_answered)
        self.assertFalse(st.resolved)
        self.assertTrue(st.pending)
        self.assertEqual(st.counting, [])
        self.assertEqual(st.subtotal, 0)

    def test_choice_over_answered_resolves_with_chosen(self):
        sec = _sec("B", 2, ("Q1", 8), ("Q2", 8), ("Q3", 8))
        r = ExamResult("Exam", questions={"Q1": 6, "Q2": 5, "Q3": 7},
                       chosen={"B": ["Q1", "Q3"]})
        st = section_state(r, sec)
        self.assertTrue(st.over_answered)
        self.assertTrue(st.resolved)
        self.assertFalse(st.pending)
        self.assertEqual(sorted(st.counting), ["Q1", "Q3"])
        self.assertEqual(st.subtotal, 13)

    def test_wrong_count_chosen_stays_pending(self):
        sec = _sec("B", 2, ("Q1", 8), ("Q2", 8), ("Q3", 8))
        # Only one picked but two required -> still pending.
        r = ExamResult("Exam", questions={"Q1": 6, "Q2": 5, "Q3": 7},
                       chosen={"B": ["Q1"]})
        self.assertTrue(section_state(r, sec).pending)

    def test_chosen_referencing_unanswered_is_ignored(self):
        sec = _sec("B", 2, ("Q1", 8), ("Q2", 8), ("Q3", 8))
        # Q4 isn't answered (nor defined) — it can't count.
        r = ExamResult("Exam", questions={"Q1": 6, "Q2": 5, "Q3": 7},
                       chosen={"B": ["Q1", "Q4"]})
        st = section_state(r, sec)
        self.assertEqual(st.chosen, ["Q1"])
        self.assertTrue(st.pending)

    def test_section_max_ties(self):
        # Ties: required-largest still just sums the top `required` maxes.
        sec = _sec("B", 2, ("Q1", 5), ("Q2", 5), ("Q3", 5))
        self.assertEqual(section_max(sec), 10)


class TestResolvedTotals(unittest.TestCase):
    def test_no_sections_is_todays_numbers(self):
        r = ExamResult("Exam", total=31, max_total=45,
                       questions={"Q1": 10, "Q2": 21})
        self.assertEqual(resolved_total(r, None), 31)
        self.assertEqual(resolved_max(r, None), 45)
        self.assertFalse(exam_is_pending(r, None))

    def test_all_required_sum(self):
        secs = [_sec("A", None, ("Q1", 5), ("Q2", 5)),
                _sec("B", None, ("Q3", 10))]
        r = ExamResult("Exam", questions={"Q1": 4, "Q2": 3, "Q3": 9})
        self.assertEqual(resolved_total(r, secs), 16)
        self.assertEqual(resolved_max(r, secs), 20)
        self.assertFalse(exam_is_pending(r, secs))

    def test_pending_choice_excluded_from_total_and_flags_pending(self):
        secs = [_sec("A", None, ("Q1", 10)),
                _sec("B", 1, ("Q2", 8), ("Q3", 8))]
        r = ExamResult("Exam", questions={"Q1": 9, "Q2": 6, "Q3": 7})  # over-answered B
        self.assertTrue(exam_is_pending(r, secs))
        # A counts (9); B pending -> contributes nothing.
        self.assertEqual(resolved_total(r, secs), 9)
        # Max still counts B's required-largest (8).
        self.assertEqual(resolved_max(r, secs), 18)

    def test_resolved_choice_included(self):
        secs = [_sec("A", None, ("Q1", 10)),
                _sec("B", 1, ("Q2", 8), ("Q3", 8))]
        r = ExamResult("Exam", questions={"Q1": 9, "Q2": 6, "Q3": 7},
                       chosen={"B": ["Q3"]})
        self.assertFalse(exam_is_pending(r, secs))
        self.assertEqual(resolved_total(r, secs), 16)   # 9 + 7
        self.assertEqual(resolved_max(r, secs), 18)

    def test_resolved_suggested_band(self):
        secs = [_sec("A", None, ("Q1", 10))]
        r = ExamResult("Exam", questions={"Q1": 5})
        # 5/10 * 8 = 4
        self.assertEqual(resolved_suggested_band(r, secs), 4)
        self.assertEqual(resolved_suggested_band(ExamResult("E", total=45,
                         max_total=45), None), 8)


def _write_exam_csv(path, header, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for row in rows:
            w.writerow(row)


class TestSidecarIngest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_ingest_")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _csv(self, name="Mid_Grades.csv"):
        path = os.path.join(self.tmp, name)
        header = ["Student Name", "Q1", "Q2", "Q3",
                  "Total Score", "Max Total", "Due Date", "Comment"]
        rows = [
            ["Alice", 9, 6, 7, 22, 26, "2026-06-01", ""],
            ["Bob", 8, 5, "", 13, 26, "2026-06-01", ""],
        ]
        _write_exam_csv(path, header, rows)
        return path

    def _sidecar(self, csv_path):
        meta = {
            "exam": "Mid", "grid": "compact", "paper_size": "A4",
            "has_name_box": False,
            "sections": [
                {"name": "A", "required": None,
                 "questions": [{"label": "Q1", "max": 10}]},
                {"name": "B", "required": 1,
                 "questions": [{"label": "Q2", "max": 8},
                               {"label": "Q3", "max": 8}]},
            ],
        }
        with open(csv_path + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump(meta, fh)

    def test_sidecar_less_is_unchanged(self):
        path = self._csv()
        pipe = IngestionPipeline()
        pipe.ingest_exam_csv(path, "Mid")
        asg = next(a for a in pipe.gradebook.assignments if a.name == "Mid")
        self.assertIsNone(asg.sections)
        alice = pipe.gradebook.students["Alice"].exam_results["Mid"]
        self.assertEqual(alice.max_total, 26)   # naive sheet max
        self.assertEqual(alice.total, 22)

    def test_sidecar_attaches_sections_and_resolved_max(self):
        path = self._csv()
        self._sidecar(path)
        pipe = IngestionPipeline()
        pipe.ingest_exam_csv(path, "Mid")
        asg = next(a for a in pipe.gradebook.assignments if a.name == "Mid")
        self.assertIsNotNone(asg.sections)
        self.assertEqual([s["name"] for s in asg.sections], ["A", "B"])
        # resolved max = 10 (A) + 8 (B, one of two 8s) = 18, not the 26 naive sum
        alice = pipe.gradebook.students["Alice"].exam_results["Mid"]
        self.assertEqual(alice.max_total, 18)
        self.assertEqual(asg.max_total, 18)
        # Alice over-answered B (Q2 and Q3) -> pending
        self.assertTrue(exam_is_pending(alice, asg.sections))
        # Bob answered only Q2 in B -> resolved
        bob = pipe.gradebook.students["Bob"].exam_results["Mid"]
        self.assertFalse(exam_is_pending(bob, asg.sections))
        self.assertEqual(resolved_total(bob, asg.sections), 13)  # 8 + 5

    def test_chosen_survives_reingest(self):
        path = self._csv()
        self._sidecar(path)
        pipe = IngestionPipeline()
        pipe.ingest_exam_csv(path, "Mid")
        alice = pipe.gradebook.students["Alice"].exam_results["Mid"]
        alice.chosen["B"] = ["Q3"]
        # Re-ingest the same CSV (purge-replace) into the same gradebook.
        pipe.ingest_exam_csv(path, "Mid")
        alice2 = pipe.gradebook.students["Alice"].exam_results["Mid"]
        self.assertEqual(alice2.chosen.get("B"), ["Q3"])
        sections = next(a for a in pipe.gradebook.assignments
                        if a.name == "Mid").sections
        self.assertFalse(exam_is_pending(alice2, sections))

    def test_load_sidecar_missing_returns_none(self):
        self.assertIsNone(load_exam_sidecar(os.path.join(self.tmp, "nope.csv")))


class SectionBandsPersistence(unittest.TestCase):
    """Phase 6: ``ExamResult.section_bands`` survives the dict round-trip and
    defaults to ``{}`` for a legacy record with no such key."""

    def test_round_trip(self):
        from engine.persistence import (exam_result_to_dict,
                                         exam_result_from_dict)
        r = ExamResult(assignment="Mid", total=13, max_total=20,
                       questions={"Q1": 8, "Q3": 5},
                       section_bands={"Knowing": 7, "Applying": 5})
        back = exam_result_from_dict(exam_result_to_dict(r))
        self.assertEqual(back.section_bands, {"Knowing": 7, "Applying": 5})

    def test_absent_defaults_empty(self):
        from engine.persistence import exam_result_from_dict
        back = exam_result_from_dict(
            {"assignment": "Mid", "total": 9, "max_total": 20,
             "questions": {"Q1": 9}})
        self.assertEqual(back.section_bands, {})


if __name__ == "__main__":
    unittest.main()
