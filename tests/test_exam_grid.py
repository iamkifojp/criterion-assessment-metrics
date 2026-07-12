"""Phase 3 (Exam Slicer v2 plan) — per-exam grid density + legibility.

Covers the engine half of docs/EXAM_SLICER_V2_AND_SYNC_PLAN.md Phase 3:

  * The legacy grid is byte-identical to the pre-density behaviour — a saved
    exam with no "grid" key parses, validates and slices to pixel-identical
    crops (``range_to_bbox`` old geometry vs new). This is the backward-compat
    contract.
  * The two denser grids (compact ~1.4cm, fine ~1cm) produce their own,
    tighter geometry, and two-letter Excel columns (fine A3 reaches AD) parse,
    round-trip and bound-check on the Python side.
  * ``ExamStore.save_exam`` persists the density and defaults a config with no
    "grid" key to "legacy".

Only ``cam_grading_workspace/exam_engine.py`` is exercised (no Flask, no
Streamlit). Run:

    python -m unittest tests.test_exam_grid
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "cam_grading_workspace"))

import exam_engine as e  # noqa: E402  (path shim must precede the import)


# The historical grid geometry, reproduced here independently of the engine so
# the "legacy == old behaviour" assertion cannot silently drift with the code.
LEGACY_GRIDS = {"A4": (10, 15), "B5": (9, 12), "A3": (15, 21)}


def old_range_to_bbox(img_w, img_h, paper_size, rng):
    """The pre-density range_to_bbox, inlined with the fixed legacy grid."""
    paper_w_mm, paper_h_mm = e.PAPER_SIZES_MM[paper_size]
    grid_cols, grid_rows = LEGACY_GRIDS[paper_size]
    dpi_x = img_w / (paper_w_mm / 25.4)
    dpi_y = img_h / (paper_h_mm / 25.4)
    cell_w_px = (paper_w_mm / grid_cols) / 25.4 * dpi_x
    cell_h_px = (paper_h_mm / grid_rows) / 25.4 * dpi_y
    left = int(round(rng["c1"] * cell_w_px))
    top = int(round(rng["r1"] * cell_h_px))
    right = int(round((rng["c2"] + 1) * cell_w_px))
    bottom = int(round((rng["r2"] + 1) * cell_h_px))
    left = max(0, min(left, img_w - 1))
    top = max(0, min(top, img_h - 1))
    right = max(left + 1, min(right, img_w))
    bottom = max(top + 1, min(bottom, img_h))
    return (left, top, right, bottom)


class TestColumnHelpers(unittest.TestCase):
    def test_col_name_excel_style(self):
        self.assertEqual([e.col_name(i) for i in (0, 25, 26, 27, 29)],
                         ["A", "Z", "AA", "AB", "AD"])

    def test_col_index_inverse(self):
        for i in range(0, 42):
            self.assertEqual(e.col_index(e.col_name(i)), i)

    def test_col_index_case_insensitive(self):
        self.assertEqual(e.col_index("aa"), 26)

    def test_col_index_rejects_non_letters(self):
        for bad in ("", "5", "A1", " "):
            with self.assertRaises(ValueError):
                e.col_index(bad)


class TestGridResolution(unittest.TestCase):
    def test_grid_for_all_paper_densities(self):
        self.assertEqual(e.grid_for("A4", "legacy"), (10, 15))
        self.assertEqual(e.grid_for("A4", "compact"), (15, 21))
        self.assertEqual(e.grid_for("A4", "fine"), (21, 30))
        self.assertEqual(e.grid_for("A3", "fine"), (30, 42))
        self.assertEqual(e.grid_for("B5", "compact"), (13, 18))

    def test_grid_for_defaults_to_legacy(self):
        # No density argument, and an unknown density, both fall back to legacy.
        self.assertEqual(e.grid_for("A4"), (10, 15))
        self.assertEqual(e.grid_for("A4", "bogus"), (10, 15))

    def test_grid_of_config(self):
        self.assertEqual(e.grid_of({"paper_size": "A4"}), "legacy")   # absent
        self.assertEqual(e.grid_of({"grid": None}), "legacy")
        self.assertEqual(e.grid_of({"grid": "junk"}), "legacy")
        self.assertEqual(e.grid_of({"grid": "FINE"}), "fine")         # normalised
        self.assertEqual(e.grid_of({"grid": "compact"}), "compact")


class TestLegacyIdentity(unittest.TestCase):
    """A legacy exam must slice to pixel-identical crops vs the old code."""

    # Ranges that were valid on the legacy grids of each paper size.
    CASES = [
        ("A4", "A1"),
        ("A4", "A1:J15"),
        ("A4", "C3:E7"),
        ("A4", "page2!B2:D4"),
        ("B5", "A1:I12"),
        ("A3", "A1:O21"),
        ("A3", "G8:K13"),
    ]
    SIZES = [(1000, 1500), (1240, 1754), (827, 1169), (2000, 2828)]

    def test_range_to_bbox_matches_old_geometry(self):
        for paper, raw in self.CASES:
            rng_new = e.parse_range(raw, paper, "legacy")
            rng_def = e.parse_range(raw, paper)          # default == legacy
            self.assertEqual(rng_new, rng_def)
            for w, h in self.SIZES:
                new_box = e.range_to_bbox(w, h, paper, rng_new, "legacy")
                def_box = e.range_to_bbox(w, h, paper, rng_new)   # default grid
                old_box = old_range_to_bbox(w, h, paper, rng_new)
                self.assertEqual(new_box, old_box,
                                 f"{paper} {raw} @ {w}x{h}")
                self.assertEqual(def_box, old_box)

    def test_known_clean_bbox(self):
        # A4 legacy on a 1000x1500 scan: exactly 10x15 cells of 100x100 px.
        rng = e.parse_range("A1", "A4", "legacy")
        self.assertEqual(e.range_to_bbox(1000, 1500, "A4", rng, "legacy"),
                         (0, 0, 100, 100))


class TestDenseGrids(unittest.TestCase):
    def test_compact_differs_from_legacy(self):
        legacy = e.range_to_bbox(1000, 1500, "A4",
                                 e.parse_range("A1", "A4", "legacy"), "legacy")
        compact = e.range_to_bbox(1000, 1500, "A4",
                                  e.parse_range("A1", "A4", "compact"), "compact")
        self.assertNotEqual(legacy, compact)
        # Compact A4 is 15x21: 1000/15 -> 67px wide, 1500/21 -> 71px tall.
        self.assertEqual(compact, (0, 0, 67, 71))

    def test_two_letter_columns_parse_on_fine_a3(self):
        rng = e.parse_range("AA5:AD9", "A3", "fine")
        self.assertEqual(rng, {"page": 1, "c1": 26, "r1": 4, "c2": 29, "r2": 8})

    def test_two_letter_columns_round_trip(self):
        # label -> index -> label is stable across the widest grid.
        self.assertEqual(e.col_name(e.col_index("AD")), "AD")

    def test_column_out_of_grid_rejected(self):
        # AA (index 26) is past A4-compact's 15 columns, and past fine A4's 21.
        for grid in ("legacy", "compact", "fine"):
            with self.assertRaises(ValueError):
                e.parse_range("AA5", "A4", grid)
        # AE (index 30) is one past fine A3's last column AD (29).
        with self.assertRaises(ValueError):
            e.parse_range("AE5", "A3", "fine")

    def test_row_out_of_grid_rejected(self):
        # Fine A3 has 42 rows; row 43 is out.
        with self.assertRaises(ValueError):
            e.parse_range("A43", "A3", "fine")
        # But 42 is fine.
        self.assertEqual(e.parse_range("A42", "A3", "fine")["r1"], 41)


class TestSaveExamPersistsGrid(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_exam_grid_")
        self.store = e.ExamStore(self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_new_compact_exam_round_trips(self):
        clean = self.store.save_exam("7A", {
            "name": "Midterm", "paper_size": "A4", "grid": "compact",
            "questions": [{"label": "Q1", "range": "A1:C3", "max": "0-3"}],
        })
        self.assertEqual(clean["grid"], "compact")
        self.assertEqual(self.store.get_exam("7A", "Midterm")["grid"], "compact")

    def test_fine_exam_two_letter_range(self):
        clean = self.store.save_exam("7A", {
            "name": "Big", "paper_size": "A3", "grid": "fine",
            "questions": [{"label": "Q1", "range": "AA5:AD9", "max": "0-8"}],
        })
        self.assertEqual(clean["grid"], "fine")
        self.assertEqual(clean["questions"][0]["range"], "AA5:AD9")

    def test_missing_grid_defaults_to_legacy(self):
        clean = self.store.save_exam("7A", {
            "name": "Old", "paper_size": "A4",
            "questions": [{"label": "Q1", "range": "A1:C3", "max": "0-3"}],
        })
        self.assertEqual(clean["grid"], "legacy")

    def test_range_validated_against_saved_density(self):
        # A1:U30 fits fine A4 (21x30) but not legacy A4 (10x15).
        self.store.save_exam("7A", {
            "name": "Fits", "paper_size": "A4", "grid": "fine",
            "questions": [{"label": "Q1", "range": "A1:U30", "max": "0-3"}],
        })
        with self.assertRaises(ValueError):
            self.store.save_exam("7A", {
                "name": "Overflow", "paper_size": "A4", "grid": "legacy",
                "questions": [{"label": "Q1", "range": "A1:U30", "max": "0-3"}],
            })


if __name__ == "__main__":
    unittest.main()
