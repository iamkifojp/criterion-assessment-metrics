"""Exam Identity & Section Banding plan — Phase 5 (CGW student naming, D5).

Covers the engine half of docs/EXAM_IDENTITY_AND_BANDING_PLAN.md Phase 5:

  * ``ExamStore.save_exam`` persists a display-only ``student_names`` map
    ({file stem -> real name}), cleaned to str->str with values stripped and
    empties dropped; absent or malformed -> ``{}`` (backward compatible). The
    map round-trips through both the legacy and the portable stores.
  * ``page_counts`` / ``scan_page_warnings`` implement the booklet-scan guard:
    students whose page count is off the class majority are flagged; a single
    readable file or a class that all agrees yields no warnings.
  * ``process_exam`` surfaces those warnings under a ``warnings`` summary key on
    a full run, and leaves it empty on a single-question re-slice.

Only ``cam_grading_workspace/exam_engine.py`` is exercised (no Flask). Run:

    python -m unittest tests.test_exam_naming
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "cam_grading_workspace"))

import exam_engine as e  # noqa: E402  (path shim must precede the import)

from PIL import Image  # noqa: E402


def _cfg(name="Ex", folder="", **extra):
    cfg = {"name": name, "paper_size": "A4", "grid": "compact", "pdf_folder": folder,
           "questions": [{"label": "Q1", "range": "A3:C5", "max": "3", "section": ""}]}
    cfg.update(extra)
    return cfg


class StudentNamesPersistence(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.store = e.ExamStore(self.d)          # legacy-only (no resolver)

    def test_cleaned_and_round_tripped(self):
        cfg = _cfg(student_names={" scan_01 ": " Alice ", "scan_02": "",
                                  "scan_03": "Bob", 7: "Num"})
        clean = self.store.save_exam("7A", cfg)
        # values stripped, empty dropped, keys coerced to str
        self.assertEqual(clean["student_names"],
                         {"scan_01": "Alice", "scan_03": "Bob", "7": "Num"})
        # survives a reload
        self.assertEqual(self.store.get_exam("7A", "Ex")["student_names"],
                         {"scan_01": "Alice", "scan_03": "Bob", "7": "Num"})

    def test_absent_defaults_to_empty(self):
        clean = self.store.save_exam("7A", _cfg())
        self.assertEqual(clean["student_names"], {})

    def test_malformed_defaults_to_empty(self):
        clean = self.store.save_exam("7A", _cfg(student_names="garbage"))
        self.assertEqual(clean["student_names"], {})

    def test_round_trip_through_portable_store(self):
        # A resolver that returns a per-class folder routes to the portable store.
        cloud = tempfile.mkdtemp()
        store = e.ExamStore(self.d, class_dir=lambda c, create=False: cloud)
        store.save_exam("7A", _cfg(student_names={"s1": "Ann"}))
        self.assertEqual(store.get_exam("7A", "Ex")["student_names"], {"s1": "Ann"})


class ScanPageGuard(unittest.TestCase):
    def test_flags_the_outlier_against_majority(self):
        warns = e.scan_page_warnings({"A": 12, "B": 12, "C": 11, "D": 12})
        self.assertEqual(len(warns), 1)
        self.assertIn("C", warns[0])
        self.assertIn("11", warns[0])
        self.assertIn("12", warns[0])

    def test_none_counts_are_ignored(self):
        self.assertEqual(e.scan_page_warnings({"A": 3, "B": 3, "C": None}), [])

    def test_single_file_never_warns(self):
        self.assertEqual(e.scan_page_warnings({"A": 5}), [])

    def test_all_agree_never_warns(self):
        self.assertEqual(e.scan_page_warnings({"A": 4, "B": 4, "C": 4}), [])

    def test_tie_resolves_to_larger_count(self):
        # 10 and 12 each appear twice; the larger (12) wins, so the 10s flag.
        warns = e.scan_page_warnings({"A": 12, "B": 12, "C": 10, "D": 10})
        self.assertEqual(len(warns), 2)
        self.assertTrue(all("10 page" in w and "12" in w for w in warns))


class ProcessExamWarnings(unittest.TestCase):
    def _make_folder(self, names):
        src = tempfile.mkdtemp()
        for nm in names:
            Image.new("RGB", (800, 1100), "white").save(os.path.join(src, nm + ".png"))
        return src

    def test_summary_has_warnings_key(self):
        out = tempfile.mkdtemp()
        cfg = _cfg(folder=self._make_folder(["s1", "s2"]))
        summary = e.process_exam(cfg, out)
        self.assertIn("warnings", summary)
        # single-page images all agree -> no warnings
        self.assertEqual(summary["warnings"], [])

    def test_reslice_one_skips_the_guard(self):
        out = tempfile.mkdtemp()
        cfg = _cfg(folder=self._make_folder(["s1", "s2"]))
        summary = e.process_exam(cfg, out, labels=["Q1"])
        self.assertEqual(summary["warnings"], [])


if __name__ == "__main__":
    unittest.main()
