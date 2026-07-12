"""Phase 6 (Exam Slicer v2 plan) — re-slice ONE question during grading.

Covers the engine half of docs/EXAM_SLICER_V2_AND_SYNC_PLAN.md Phase 6: the
``labels=[...]`` subset argument to ``process_exam`` used by /api/exam/process_one
to re-crop a single question after the teacher tweaks its range mid-grading.

The contract:

  * ``labels=[label]`` crops ONLY that question — every other question's crop on
    disk is left byte-identical (re-slicing changes pixels of one question, and
    entered marks, keyed by label, are never touched).
  * A widened range produces a bigger crop for the touched question while the
    others stay exactly as a full run left them.
  * The name box is included only when its reserved label is in ``labels``.
  * ``labels=None`` (or absent) slices everything, unchanged from before.
  * An unknown label subset raises rather than silently doing nothing.

Only the framework-free engine is exercised. Run:

    python -m unittest tests.test_exam_reslice
"""

import os
import sys
import tempfile
import unittest

from PIL import Image

_CGW = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "cam_grading_workspace")
sys.path.insert(0, _CGW)

import exam_engine as e  # noqa: E402  (path shim must precede the import)


def _write_png(path, w=1000, h=1500, color=(255, 255, 255)):
    Image.new("RGB", (w, h), color).save(path, "PNG")


class TestResliceOneQuestion(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_reslice_")
        self.pdfs = os.path.join(self.tmp, "scans")
        os.makedirs(self.pdfs)
        for stu in ("Alice", "Bob"):
            _write_png(os.path.join(self.pdfs, stu + ".png"))
        self.out = os.path.join(self.tmp, "crops")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, q1_range="A3:C5"):
        return {
            "name": "Exam", "paper_size": "A4", "grid": "compact",
            "pdf_folder": self.pdfs, "name_box": "A1:E2",
            "sections": [{"name": e.DEFAULT_SECTION_NAME, "required": None}],
            "questions": [
                {"label": "Q1", "range": q1_range, "max": 3,
                 "section": e.DEFAULT_SECTION_NAME},
                {"label": "Q2", "range": "A7:C9", "max": 3,
                 "section": e.DEFAULT_SECTION_NAME},
            ],
        }

    def _crop_path(self, label, student="Alice"):
        return os.path.join(self.out, "Exam", label, student + ".png")

    def _size(self, label, student="Alice"):
        with Image.open(self._crop_path(label, student)) as im:
            return im.size

    def test_labels_subset_crops_only_that_question(self):
        # Fresh output: slice only Q2. Q1 / name box never get written.
        summary = e.process_exam(self._config(), self.out, labels=["Q2"])
        self.assertTrue(os.path.isfile(self._crop_path("Q2")))
        self.assertFalse(os.path.exists(self._crop_path("Q1")))
        self.assertFalse(os.path.exists(
            os.path.join(self.out, "Exam", e.NAME_BOX_DIR)))
        # summary counts only the sliced gradable question and its crops.
        self.assertEqual(summary["questions"], 1)
        self.assertEqual(summary["crops"], 2)          # 2 students * 1 question

    def test_reslice_touches_only_target_others_byte_identical(self):
        # Full run first.
        e.process_exam(self._config(), self.out)
        q2_before = os.path.getmtime(self._crop_path("Q2"))
        name_before = os.path.getmtime(self._crop_path(e.NAME_BOX_DIR))
        q1_size_before = self._size("Q1")

        # Widen Q1 by a column and re-slice ONLY Q1.
        e.process_exam(self._config(q1_range="A3:D5"), self.out, labels=["Q1"])

        # Q1's crop grew (wider framing); Q2 + name box untouched on disk.
        q1_size_after = self._size("Q1")
        self.assertGreater(q1_size_after[0], q1_size_before[0])
        self.assertEqual(q2_before, os.path.getmtime(self._crop_path("Q2")))
        self.assertEqual(name_before,
                         os.path.getmtime(self._crop_path(e.NAME_BOX_DIR)))

    def test_name_box_only_when_its_label_requested(self):
        e.process_exam(self._config(), self.out, labels=[e.NAME_BOX_DIR])
        self.assertTrue(os.path.isfile(self._crop_path(e.NAME_BOX_DIR)))
        self.assertFalse(os.path.exists(self._crop_path("Q1")))
        self.assertFalse(os.path.exists(self._crop_path("Q2")))

    def test_labels_none_slices_everything(self):
        summary = e.process_exam(self._config(), self.out, labels=None)
        self.assertTrue(os.path.isfile(self._crop_path("Q1")))
        self.assertTrue(os.path.isfile(self._crop_path("Q2")))
        self.assertTrue(os.path.isfile(self._crop_path(e.NAME_BOX_DIR)))
        self.assertEqual(summary["questions"], 2)
        self.assertEqual(summary["crops"], 6)          # 2 students * (2 q + name)

    def test_unknown_label_subset_raises(self):
        with self.assertRaises(ValueError):
            e.process_exam(self._config(), self.out, labels=["Nope"])


if __name__ == "__main__":
    unittest.main()
