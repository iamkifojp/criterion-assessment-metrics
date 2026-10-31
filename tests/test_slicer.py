"""Grid geometry, paper detection, splitting and cropping.

Run:  python -m unittest tests.test_slicer
"""

import os
import tempfile
import unittest

from PIL import Image

from engine import slicer
from engine.errors import UserError
from engine.slicer import Box, Layout
from tests.helpers import POINTS_PER_MM, center_color, make_image, make_pdf

RED, BLUE = (255, 0, 0), (0, 0, 255)


class GridTests(unittest.TestCase):
    def test_grid_sizes(self):
        expected = {("A4", "5mm"): (42, 60), ("B5", "5mm"): (36, 51), ("A3", "5mm"): (60, 84),
                    # CAM's "compact" and "fine", still read from older sessions
                    ("A4", "normal"): (15, 21), ("A4", "fine"): (21, 30),
                    ("B5", "normal"): (13, 18), ("B5", "fine"): (18, 25),
                    ("A3", "normal"): (21, 30), ("A3", "fine"): (30, 42)}
        for (paper, density), (cols, rows) in expected.items():
            layout = Layout(paper, density)
            self.assertEqual((layout.cols, layout.rows), (cols, rows))
            turned = Layout(paper, density, landscape=True)
            self.assertEqual((turned.cols, turned.rows), (rows, cols))

    def test_new_grid_cells_are_about_5_mm(self):
        for paper, (w_mm, h_mm) in slicer.PAPER_SIZES_MM.items():
            layout = Layout(paper)
            self.assertEqual(layout.density, "5mm")
            self.assertAlmostEqual(w_mm / layout.cols, 5.0, delta=0.15, msg=paper)
            self.assertAlmostEqual(h_mm / layout.rows, 5.0, delta=0.15, msg=paper)

    def test_last_cells(self):
        self.assertEqual(slicer.col_name(Layout("A4").cols - 1), "AP")
        self.assertEqual(slicer.col_name(Layout("A3", landscape=True).cols - 1), "CF")
        self.assertEqual(slicer.col_name(Layout("A4", "normal").cols - 1), "O")
        self.assertEqual(slicer.col_name(Layout("A4", "fine").cols - 1), "U")
        self.assertEqual(slicer.col_name(Layout("A3", "fine").cols - 1), "AD")

    def test_unknown_layout_values_are_rejected(self):
        with self.assertRaises(UserError):
            Layout("Letter")
        with self.assertRaises(UserError):
            Layout("A4", "legacy")

    def test_layout_config_round_trip(self):
        layout = Layout("B5", "fine", True)
        self.assertEqual(Layout.from_config(layout.to_config()), layout)
        self.assertEqual(Layout.from_config(None), Layout())

    def test_column_letters_round_trip(self):
        for i in range(80):
            self.assertEqual(slicer.col_index(slicer.col_name(i)), i)
        self.assertEqual(slicer.col_name(26), "AA")
        with self.assertRaises(ValueError):
            slicer.col_index("A1")


class RangeTests(unittest.TestCase):
    layout = Layout("A4")

    def test_forms_teachers_type(self):
        self.assertEqual(slicer.parse_range("A4:J10", self.layout), Box(1, 0, 3, 9, 9))
        self.assertEqual(slicer.parse_range(" page2 ! a4 : j10 ", self.layout),
                         Box(2, 0, 3, 9, 9))
        self.assertEqual(slicer.parse_range("J10:A4", self.layout), Box(1, 0, 3, 9, 9))
        self.assertEqual(slicer.parse_range("B7", self.layout), Box(1, 1, 6, 1, 6))

    def test_full_width_input_is_accepted(self):
        self.assertEqual(slicer.parse_range("Ａ４：Ｊ１０", self.layout), Box(1, 0, 3, 9, 9))

    def test_off_grid_reports_the_last_cell(self):
        with self.assertRaises(UserError) as ctx:
            slicer.parse_range("A1:AQ1", self.layout)
        self.assertEqual(ctx.exception.code, "range_off_grid")
        self.assertEqual(ctx.exception.params["last"], "AP60")
        slicer.parse_range("AD42", Layout("A3", "fine"))

    def test_nonsense_is_rejected(self):
        for raw in ("", "hello", "page0!A1", "A0"):
            with self.assertRaises(UserError, msg=raw):
                slicer.parse_range(raw, self.layout)

    def test_format_round_trip(self):
        box = Box(3, 2, 4, 10, 12)
        self.assertEqual(slicer.format_range(box), "page3!C5:K13")
        self.assertEqual(slicer.parse_range(slicer.format_range(box), self.layout), box)


class GeometryTests(unittest.TestCase):
    def test_matches_cams_auto_dpi_formula(self):
        """CAM computed cells via an effective DPI; the mm cancel out exactly."""
        for paper, (w_mm, h_mm) in slicer.PAPER_SIZES_MM.items():
            for density in slicer.DENSITIES:
                layout = Layout(paper, density)
                for img_w, img_h in ((1654, 2339), (2480, 3508), (1240, 1754)):
                    dpi_x, dpi_y = img_w / (w_mm / 25.4), img_h / (h_mm / 25.4)
                    cw = (w_mm / layout.cols) / 25.4 * dpi_x
                    ch = (h_mm / layout.rows) / 25.4 * dpi_y
                    box = Box(1, 2, 3, layout.cols - 2, layout.rows - 1)
                    cam = (int(round(2 * cw)), int(round(3 * ch)),
                           int(round((layout.cols - 1) * cw)),
                           int(round(layout.rows * ch)))
                    cam = (cam[0], cam[1], min(cam[2], img_w), min(cam[3], img_h))
                    self.assertEqual(slicer.range_to_bbox(img_w, img_h, box, layout), cam)

    def test_bbox_is_clamped_to_the_image(self):
        layout = Layout("A4")
        left, top, right, bottom = slicer.range_to_bbox(
            100, 100, Box(1, 0, 0, layout.cols - 1, layout.rows - 1), layout)
        self.assertEqual((left, top, right, bottom), (0, 0, 100, 100))

    def test_snap_rect_covers_every_touched_cell(self):
        layout = Layout("A4")
        self.assertEqual(slicer.snap_rect(1, 0, 0, 1, 1, layout),
                         Box(1, 0, 0, layout.cols - 1, layout.rows - 1))
        # Inside one cell
        self.assertEqual(slicer.snap_rect(2, 0.005, 0.005, 0.01, 0.01, layout),
                         Box(2, 0, 0, 0, 0))
        # Ending exactly on a cell edge does not spill into the next cell
        edge = 3 / layout.cols
        self.assertEqual(slicer.snap_rect(1, 0, 0, edge, 0.01, layout).c2, 2)
        # Dragged right-to-left
        self.assertEqual(slicer.snap_rect(1, 0.5, 0.5, 0.1, 0.1, layout),
                         slicer.snap_rect(1, 0.1, 0.1, 0.5, 0.5, layout))


class PaperDetectionTests(unittest.TestCase):
    def test_sizes_in_mm(self):
        self.assertEqual(slicer.detect_paper_mm(210, 297), ("A4", False))
        self.assertEqual(slicer.detect_paper_mm(297, 210), ("A4", True))
        self.assertEqual(slicer.detect_paper_mm(176, 250), ("B5", False))
        self.assertEqual(slicer.detect_paper_mm(182, 257), ("B5", False))   # JIS
        self.assertEqual(slicer.detect_paper_mm(420, 297), ("A3", True))
        self.assertIsNone(slicer.detect_paper_mm(215.9, 279.4))           # US Letter

    def test_detects_from_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            jis_b5 = make_pdf(os.path.join(tmp, "b5.pdf"),
                              size=(182 * POINTS_PER_MM, 257 * POINTS_PER_MM))
            self.assertEqual(slicer.detect_paper(jis_b5), ("B5", False))
            a4_image = make_image(os.path.join(tmp, "a4.png"), (2480, 3508), dpi=300)
            self.assertEqual(slicer.detect_paper(a4_image), ("A4", False))
            no_dpi = make_image(os.path.join(tmp, "x.jpg"), (100, 100))
            self.assertIsNone(slicer.detect_paper(no_dpi))


class ScanFileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def test_listing_skips_hidden_and_sorts_naturally(self):
        for name in ("scan10.pdf", "scan2.pdf", "._scan2.pdf", ".DS_Store",
                     "notes.txt", "photo.JPG"):
            open(os.path.join(self.dir, name), "wb").close()
        names = [os.path.basename(p) for p in slicer.list_scan_files(self.dir)]
        self.assertEqual(names, ["photo.JPG", "scan2.pdf", "scan10.pdf"])

    def test_split_combined_pdf_with_leftover(self):
        src = make_pdf(os.path.join(self.dir, "class.pdf"), pages=7)
        result = slicer.split_combined_pdf(src, 2, os.path.join(self.dir, "out"))
        self.assertEqual(len(result["files"]), 4)
        self.assertEqual(result["leftover"], 1)
        self.assertEqual([slicer.page_count(f) for f in result["files"]], [2, 2, 2, 1])
        self.assertEqual(os.path.basename(result["files"][0]), "Student_001.pdf")
        self.assertEqual(slicer.check_split(8, 2), (4, 0))
        with self.assertRaises(UserError):
            slicer.check_split(8, 0)

    def test_class_size_catches_what_leftover_cannot(self):
        # Two missing pages: 46 pages at 2 per student divide evenly into 23
        self.assertEqual(slicer.check_split(46, 2), (23, 0))
        self.assertEqual(slicer.check_class_size(46, 2, 24),
                         {"students": 24, "expected_pages": 48, "pages": 46, "diff": -2})
        self.assertEqual(slicer.check_class_size(49, 2, 24)["diff"], 1)
        self.assertIsNone(slicer.check_class_size(48, 2, 24))
        for blank in (None, "", 0, "abc"):
            self.assertIsNone(slicer.check_class_size(46, 2, blank))

    def test_page_count_warnings_flag_the_odd_one_out(self):
        warnings = slicer.page_count_warnings({"s001": 4, "s002": 4, "s003": 3, "s004": None})
        self.assertEqual(warnings, [{"student": "s003", "pages": 3, "expected": 4}])
        self.assertEqual(slicer.page_count_warnings({"s001": 4}), [])

    def test_copy_scans_makes_safe_unique_names(self):
        src_dir = os.path.join(self.dir, "src")
        os.makedirs(os.path.join(src_dir, "a"))
        first = make_pdf(os.path.join(src_dir, "Tanaka.pdf"))
        second = make_pdf(os.path.join(src_dir, "a", "TANAKA.pdf"))
        third = make_pdf(os.path.join(src_dir, "山田 太郎.pdf"))
        students = slicer.copy_scans([first, second, third], os.path.join(self.dir, "scans"))
        self.assertEqual([s["id"] for s in students], ["s001", "s002", "s003"])
        self.assertEqual([s["file"] for s in students],
                         ["Tanaka.pdf", "TANAKA (2).pdf", "山田 太郎.pdf"])
        self.assertTrue(os.path.isfile(os.path.join(self.dir, "scans", "TANAKA (2).pdf")))

    def test_safe_filename(self):
        self.assertEqual(slicer.safe_filename('a/b:c*?"<>|'), "a_b_c______")
        self.assertEqual(slicer.safe_filename("CON"), "_CON")
        self.assertEqual(slicer.safe_filename("  ...  "), "Unnamed")
        self.assertEqual(slicer.safe_filename("山田　花子"), "山田　花子")
        taken = set()
        self.assertEqual(slicer.unique_name("A.pdf", taken), "A.pdf")
        self.assertEqual(slicer.unique_name("a.pdf", taken), "a (2).pdf")


class SlicingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.layout = Layout("A4")

    def tearDown(self):
        self.tmp.cleanup()

    def _student(self, name, pages=2):
        fills = {1: [(self.layout, 2, 2, RED)], 2: [(self.layout, 4, 4, BLUE)]}
        return make_pdf(os.path.join(self.dir, name), pages=pages, fills=fills)

    def test_one_question_across_two_pages_is_stitched(self):
        path = self._student("s001.pdf")
        boxes = slicer.parse_boxes(["page1!C3", "page2!E5"], self.layout)
        image = slicer.crop_boxes(path, boxes, self.layout)
        cell_h = 297 / 25.4 * slicer.RENDER_DPI / self.layout.rows
        self.assertAlmostEqual(image.height, 2 * cell_h + slicer.DIVIDER_PX, delta=3)
        top = image.getpixel((image.width // 2, int(cell_h / 2)))
        bottom = image.getpixel((image.width // 2, image.height - int(cell_h / 2)))
        self.assertEqual(top, RED)
        self.assertEqual(bottom, BLUE)

    def test_slice_all_keeps_going_after_a_bad_paper(self):
        scans = [("s001", self._student("a.pdf")), ("s002", self._student("b.pdf", pages=1))]
        regions = [("q1", slicer.parse_boxes(["page1!C3"], self.layout)),
                   ("q2", slicer.parse_boxes(["page2!E5"], self.layout))]
        crops = os.path.join(self.dir, "crops")
        seen = []
        summary = slicer.slice_all(scans, regions, self.layout, crops,
                                   progress=lambda d, t: seen.append((d, t)))
        self.assertEqual(summary["crops"], 3)
        self.assertEqual(len(summary["errors"]), 1)
        self.assertEqual(summary["errors"][0]["student"], "s002")
        self.assertEqual(seen, [(1, 2), (2, 2)])
        with Image.open(os.path.join(crops, "q1", "s001.png")) as im:
            self.assertEqual(center_color(im.convert("RGB")), RED)
        with Image.open(os.path.join(crops, "q2", "s001.png")) as im:
            self.assertEqual(center_color(im.convert("RGB")), BLUE)

    def test_previews_and_thumbnails(self):
        path = self._student("a.pdf")
        jpeg = slicer.page_preview(path, 1, self.layout,
                                   [Box(1, 2, 2, 2, 2)], max_width=600)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        thumb = slicer.make_thumbnail(path, os.path.join(self.dir, "t", "a.jpg"))
        with Image.open(thumb) as im:
            self.assertLessEqual(im.width, 240)
        crop = slicer.crop_preview(path, [Box(1, 2, 2, 2, 2)], self.layout)
        self.assertTrue(crop.startswith(b"\xff\xd8"))

    def test_missing_page_is_a_user_error(self):
        path = self._student("a.pdf", pages=1)
        with self.assertRaises(UserError) as ctx:
            slicer.load_page_image(path, 3)
        self.assertEqual(ctx.exception.code, "page_missing")


if __name__ == "__main__":
    unittest.main()
