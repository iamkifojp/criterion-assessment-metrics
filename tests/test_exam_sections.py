"""Phase 4 (Exam Slicer v2 plan) — name box, sections, and the export sidecar.

Covers the CGW half of docs/EXAM_SLICER_V2_AND_SYNC_PLAN.md Phase 4:

  * ``normalize_sections`` — a config with no sections synthesizes exactly one
    default section holding every question; names must be unique/non-empty;
    ``required`` is validated against the number of questions in the section;
    a question naming an unknown section falls into the first.
  * ``ExamStore.save_exam`` grows the config with ``name_box`` (validated like a
    range, or null) and ``sections`` (always ≥1), rejects a question labelled
    with the reserved ``__name__``, and a *legacy* config still round-trips and
    slices identically.
  * ``process_exam`` crops the name box to ``<exam>/__name__/<Student>.png`` and
    never counts it as a gradable question; without a name box, behaviour is
    unchanged.
  * ``build_sidecar`` builds the ``*.meta.json`` structure, synthesizing a
    default section for legacy configs so CAM always sees ≥1 section.

Only the framework-free engine is exercised. Run:

    python -m unittest tests.test_exam_sections
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


class TestNormalizeSections(unittest.TestCase):
    def test_missing_sections_synthesizes_one_default(self):
        qs = [{"label": "Q1", "section": ""}, {"label": "Q2", "section": ""}]
        secs = e.normalize_sections(None, qs)
        self.assertEqual(len(secs), 1)
        self.assertEqual(secs[0]["name"], e.DEFAULT_SECTION_NAME)
        self.assertIsNone(secs[0]["required"])
        # every question pinned to the synthesized section
        self.assertTrue(all(q["section"] == e.DEFAULT_SECTION_NAME for q in qs))

    def test_unknown_question_section_falls_into_first(self):
        qs = [{"label": "Q1", "section": "Nope"}]
        secs = e.normalize_sections([{"name": "A", "required": None},
                                     {"name": "B", "required": None}], qs)
        self.assertEqual(qs[0]["section"], "A")
        self.assertEqual([s["name"] for s in secs], ["A", "B"])

    def test_duplicate_names_rejected(self):
        with self.assertRaises(ValueError):
            e.normalize_sections([{"name": "A"}, {"name": "A"}], [])

    def test_blank_section_names_dropped_then_default(self):
        # A single blank-named section is dropped, leaving nothing -> default.
        secs = e.normalize_sections([{"name": "   "}], [{"label": "Q1"}])
        self.assertEqual([s["name"] for s in secs], [e.DEFAULT_SECTION_NAME])

    def test_required_in_range_kept(self):
        qs = [{"label": "Q%d" % i, "section": "A"} for i in range(4)]
        secs = e.normalize_sections([{"name": "A", "required": 2}], qs)
        self.assertEqual(secs[0]["required"], 2)

    def test_required_out_of_range_rejected(self):
        qs = [{"label": "Q1", "section": "A"}, {"label": "Q2", "section": "A"}]
        for bad in (0, 3, -1):
            with self.assertRaises(ValueError):
                e.normalize_sections([{"name": "A", "required": bad}], list(qs))

    def test_required_blank_or_none_is_all(self):
        qs = [{"label": "Q1", "section": "A"}]
        for none_ish in (None, "", "  "):
            secs = e.normalize_sections([{"name": "A", "required": none_ish}], list(qs))
            self.assertIsNone(secs[0]["required"])

    def test_required_non_numeric_rejected(self):
        with self.assertRaises(ValueError):
            e.normalize_sections([{"name": "A", "required": "two"}],
                                 [{"label": "Q1", "section": "A"}])

    def test_empty_section_forces_required_none(self):
        # A section header with no questions under it can't require a count.
        qs = [{"label": "Q1", "section": "A"}]
        secs = e.normalize_sections([{"name": "A", "required": None},
                                     {"name": "B", "required": 2}], qs)
        self.assertIsNone(secs[1]["required"])   # B is empty -> None


class TestSaveExamSections(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_sec_")
        self.store = e.ExamStore(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_legacy_config_synthesizes_section_and_keeps_questions(self):
        clean = self.store.save_exam("7A", {
            "name": "Old", "paper_size": "A4",
            "questions": [{"label": "Q1", "range": "A1:C3", "max": "0-3"}],
        })
        self.assertEqual(clean["grid"], "legacy")           # unchanged
        self.assertEqual(len(clean["sections"]), 1)
        self.assertEqual(clean["sections"][0]["name"], e.DEFAULT_SECTION_NAME)
        self.assertEqual(clean["questions"][0]["section"], e.DEFAULT_SECTION_NAME)
        self.assertIsNone(clean["name_box"])

    def test_name_box_validated_and_stored(self):
        clean = self.store.save_exam("7A", {
            "name": "Named", "paper_size": "A4", "grid": "compact",
            "name_box": "A1:E2",
            "questions": [{"label": "Q1", "range": "A3:C5", "max": "0-3"}],
        })
        self.assertEqual(clean["name_box"], "A1:E2")

    def test_bad_name_box_range_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_exam("7A", {
                "name": "Bad", "paper_size": "A4", "grid": "compact",
                "name_box": "ZZ99",
                "questions": [{"label": "Q1", "range": "A1:C3", "max": "0-3"}],
            })

    def test_reserved_name_label_rejected(self):
        with self.assertRaises(ValueError):
            self.store.save_exam("7A", {
                "name": "Reserve", "paper_size": "A4", "grid": "compact",
                "questions": [{"label": e.NAME_BOX_DIR, "range": "A1:C3", "max": "0-3"}],
            })

    def test_sections_round_trip(self):
        clean = self.store.save_exam("7A", {
            "name": "Split", "paper_size": "A4", "grid": "compact",
            "sections": [{"name": "A", "required": None},
                         {"name": "B", "required": 1}],
            "questions": [
                {"label": "Q1", "range": "A1:C3", "max": "0-3", "section": "A"},
                {"label": "Q2", "range": "A4:C6", "max": "0-3", "section": "B"},
                {"label": "Q3", "range": "A7:C9", "max": "0-3", "section": "B"},
            ],
        })
        got = self.store.get_exam("7A", "Split")
        self.assertEqual([s["name"] for s in got["sections"]], ["A", "B"])
        self.assertEqual(got["sections"][1]["required"], 1)
        by = {q["label"]: q["section"] for q in got["questions"]}
        self.assertEqual(by, {"Q1": "A", "Q2": "B", "Q3": "B"})


def _write_png(path, w=1000, h=1500, color=(255, 255, 255)):
    Image.new("RGB", (w, h), color).save(path, "PNG")


class TestProcessExamNameBox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_proc_")
        self.pdfs = os.path.join(self.tmp, "scans")
        os.makedirs(self.pdfs)
        for stu in ("Alice", "Bob"):
            _write_png(os.path.join(self.pdfs, stu + ".png"))
        self.out = os.path.join(self.tmp, "crops")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _config(self, with_name_box):
        cfg = {
            "name": "Exam", "paper_size": "A4", "grid": "compact",
            "pdf_folder": self.pdfs,
            "sections": [{"name": e.DEFAULT_SECTION_NAME, "required": None}],
            "questions": [{"label": "Q1", "range": "A3:C5", "max": 3,
                           "section": e.DEFAULT_SECTION_NAME}],
        }
        if with_name_box:
            cfg["name_box"] = "A1:E2"
        return cfg

    def test_name_box_crops_to_reserved_dir(self):
        summary = e.process_exam(self._config(True), self.out)
        exam_dir = os.path.join(self.out, "Exam")
        name_dir = os.path.join(exam_dir, e.NAME_BOX_DIR)
        self.assertTrue(os.path.isfile(os.path.join(name_dir, "Alice.png")))
        self.assertTrue(os.path.isfile(os.path.join(name_dir, "Bob.png")))
        # The name box is not counted as a gradable question.
        self.assertEqual(summary["questions"], 1)
        # crops = 2 students * (1 question + 1 name box)
        self.assertEqual(summary["crops"], 4)

    def test_no_name_box_means_no_reserved_dir(self):
        e.process_exam(self._config(False), self.out)
        name_dir = os.path.join(self.out, "Exam", e.NAME_BOX_DIR)
        self.assertFalse(os.path.exists(name_dir))


class TestExamSidecar(unittest.TestCase):
    """build_sidecar is a pure engine function (no Flask state)."""

    def setUp(self):
        self.sidecar = e.build_sidecar

    def test_sidecar_from_full_config(self):
        cfg = {
            "name": "Split", "paper_size": "A4", "grid": "compact",
            "name_box": "A1:E2",
            "sections": [{"name": "A", "required": None},
                         {"name": "B", "required": 1}],
            "questions": [
                {"label": "Q1", "max": 3, "section": "A"},
                {"label": "Q2", "max": 8, "section": "B"},
            ],
        }
        meta = self.sidecar(cfg)
        self.assertEqual(meta["exam"], "Split")
        self.assertTrue(meta["has_name_box"])
        self.assertEqual(meta["grid"], "compact")
        self.assertEqual(meta["paper_size"], "A4")
        names = [s["name"] for s in meta["sections"]]
        self.assertEqual(names, ["A", "B"])
        b = next(s for s in meta["sections"] if s["name"] == "B")
        self.assertEqual(b["required"], 1)
        self.assertEqual([q["label"] for q in b["questions"]], ["Q2"])
        self.assertEqual(b["questions"][0]["max"], 8)

    def test_sidecar_legacy_config_synthesizes_section(self):
        cfg = {
            "name": "Old", "paper_size": "A4",
            "questions": [{"label": "Q1", "max": 3}, {"label": "Q2", "max": 4}],
        }
        meta = self.sidecar(cfg)
        self.assertFalse(meta["has_name_box"])
        self.assertEqual(meta["grid"], "legacy")
        self.assertEqual(len(meta["sections"]), 1)
        self.assertEqual(meta["sections"][0]["name"], e.DEFAULT_SECTION_NAME)
        self.assertEqual([q["label"] for q in meta["sections"][0]["questions"]],
                         ["Q1", "Q2"])


if __name__ == "__main__":
    unittest.main()
