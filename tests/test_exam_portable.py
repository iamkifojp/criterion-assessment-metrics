"""Phase 6 (Exam Grading Polish plan) — portable per-class exam definitions.

Covers the engine half of docs/EXAM_GRADING_POLISH_PLAN.md Phase 6 (decision
D5): ``ExamStore`` keeps a cloud-backed class's exams in a portable
``<class folder>/gcg_exams.json`` (shape ``{"exams": {...}}``) while cloud-less
classes keep using the legacy app-local ``gcg_exams.json`` (shape
``{"classes": {...}}``).

Contract:
  * No resolver (``class_dir=None``) → legacy-only, byte-for-byte the old
    behaviour (the backward-compat guarantee for tests + cloud-less setups).
  * A resolver that returns a folder → that class's exams live in the portable
    store; reads prefer it once it exists; saves target it.
  * First save for a cloud-backed class migrates its legacy exams into the
    portable store, without clobbering existing portable entries and without
    ever rewriting the legacy file (frozen fallback).

Only ``cam_grading_workspace/exam_engine.py`` is exercised (no Flask). Run:

    python -m unittest tests.test_exam_portable
"""

import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "cam_grading_workspace"))

import exam_engine as e  # noqa: E402  (path shim must precede the import)


def _one_question(name, label="Q1", rng="A1:C3", mx="0-3"):
    return {"name": name, "paper_size": "A4", "grid": "legacy",
            "questions": [{"label": label, "range": rng, "max": mx}]}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _text(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestPortableExamStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_portable_")
        self.base = os.path.join(self.tmp, "app")
        os.makedirs(self.base)
        self.cloud = os.path.join(self.tmp, "cloud")
        self.legacy_path = os.path.join(self.base, "gcg_exams.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _resolver(self, cloud_classes):
        """A class_dir resolver: names in ``cloud_classes`` get a cloud folder."""
        def resolve(class_name, create=False):
            if class_name not in cloud_classes:
                return None
            d = os.path.join(self.cloud, class_name)
            if create:
                os.makedirs(d, exist_ok=True)
            return d
        return resolve

    def _portable_path(self, class_name):
        return os.path.join(self.cloud, class_name, "gcg_exams.json")

    def _seed_legacy(self, class_name, exam_name):
        """Write one exam straight into the legacy file (pre-Phase-6 state)."""
        store = e.ExamStore(self.base)          # no resolver -> legacy-only
        store.save_exam(class_name, _one_question(exam_name))

    # -- backward compat --------------------------------------------------------
    def test_no_resolver_is_legacy_only(self):
        store = e.ExamStore(self.base)
        store.save_exam("7A", _one_question("Midterm"))
        self.assertTrue(os.path.isfile(self.legacy_path))
        data = _load(self.legacy_path)
        self.assertEqual(sorted(data["classes"]["7A"]), ["Midterm"])
        self.assertEqual(sorted(store.list_exams("7A")), ["Midterm"])

    def test_cloudless_class_stays_in_legacy(self):
        # Resolver knows only '7A'; 'ZZ' has no cloud folder -> legacy store.
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("ZZ", _one_question("Pop Quiz"))
        self.assertIsNone(store._class_store_path("ZZ"))
        data = _load(self.legacy_path)
        self.assertEqual(sorted(data["classes"]["ZZ"]), ["Pop Quiz"])

    # -- portable store ---------------------------------------------------------
    def test_cloud_class_saves_to_portable_store(self):
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("7A", _one_question("Final"))
        port = self._portable_path("7A")
        self.assertTrue(os.path.isfile(port))
        data = _load(port)
        self.assertEqual(sorted(data["exams"]), ["Final"])
        # No stray legacy write for a cloud-backed class.
        self.assertFalse(os.path.isfile(self.legacy_path))

    def test_first_save_migrates_legacy_exams(self):
        self._seed_legacy("7A", "OldExam")
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        # Before any portable save, reads still see the legacy exam.
        self.assertEqual(sorted(store.list_exams("7A")), ["OldExam"])
        # First portable save carries OldExam across alongside the new one.
        store.save_exam("7A", _one_question("NewExam"))
        port = self._portable_path("7A")
        data = _load(port)
        self.assertEqual(sorted(data["exams"]), ["NewExam", "OldExam"])
        self.assertEqual(sorted(store.list_exams("7A")), ["NewExam", "OldExam"])

    def test_legacy_file_untouched_after_migration(self):
        self._seed_legacy("7A", "OldExam")
        before = _text(self.legacy_path)
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("7A", _one_question("NewExam"))
        after = _text(self.legacy_path)
        self.assertEqual(before, after)   # frozen fallback, never rewritten

    def test_portable_is_authoritative_over_legacy(self):
        # Portable store already has the class; a differently-named legacy exam
        # must NOT resurrect via list_exams once the portable store exists.
        self._seed_legacy("7A", "Ghost")
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("7A", _one_question("NewExam"))
        # Simulate the legacy file growing a fresh entry after migration
        # (shouldn't happen in practice, but proves the portable store wins).
        legacy = _load(self.legacy_path)
        legacy["classes"]["7A"]["LateGhost"] = legacy["classes"]["7A"]["Ghost"]
        with open(self.legacy_path, "w", encoding="utf-8") as f:
            json.dump(legacy, f)
        listed = sorted(store.list_exams("7A"))
        self.assertIn("Ghost", listed)        # migrated on first save
        self.assertIn("NewExam", listed)
        self.assertNotIn("LateGhost", listed)  # legacy is frozen, not merged

    def test_migration_does_not_clobber_portable_entry(self):
        # A portable exam with the same name as a legacy one must survive
        # migration (setdefault semantics — portable wins).
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("7A", _one_question("Shared", rng="A1:B2"))
        # Now inject a legacy 'Shared' with different geometry.
        legacy_store = e.ExamStore(self.base)
        legacy_store.save_exam("7A", _one_question("Shared", rng="A1:D4"))
        # Trigger another portable save (migration re-check path is a no-op now,
        # but assert the portable 'Shared' geometry is preserved regardless).
        store.save_exam("7A", _one_question("Another"))
        got = store.get_exam("7A", "Shared")
        self.assertEqual(got["questions"][0]["range"], "A1:B2")

    def test_atomic_write_leaves_no_tmp(self):
        store = e.ExamStore(self.base, class_dir=self._resolver({"7A"}))
        store.save_exam("7A", _one_question("Final"))
        self.assertFalse(os.path.isfile(self._portable_path("7A") + ".tmp"))


if __name__ == "__main__":
    unittest.main()
