"""Joined PDFs, page photos, open-scanned booklets, page fixes and late papers.

Run:  python -m unittest tests.test_pages

Test papers mark each page with a dark square whose position along the top
says the page number, and one along the bottom for the student, so page order
and orientation can be read back from the rendered result.
"""

import os
import tempfile
import unittest
from unittest import mock

import pymupdf as fitz
from PIL import Image

from engine import pages, slicer, storage, workflow
from engine.errors import UserError
from tests.helpers import A4_POINTS

W, H = A4_POINTS
SLOT = 28


def draw_page(page, number, student, x0=0.0, flipped=False, size=(W, H)):
    """Draw booklet page ``number`` of ``student`` at x offset ``x0``."""
    pw, ph = page.rect.width, page.rect.height

    def block(x, y):
        rect = fitz.Rect(x0 + x, y, x0 + x + SLOT - 6, y + SLOT - 6)
        if flipped:
            rect = fitz.Rect(pw - rect.x1, ph - rect.y1, pw - rect.x0, ph - rect.y0)
        page.draw_rect(rect, color=None, fill=(0, 0, 0))

    block(20 + (number - 1) * SLOT, 20)
    block(20 + (student - 1) * SLOT, size[1] - 50)


def make_pages_pdf(path, students, per, start_student=1):
    doc = fitz.open()
    for s in range(start_student, start_student + students):
        for p in range(1, per + 1):
            draw_page(doc.new_page(width=W, height=H), p, s)
    doc.save(path)
    doc.close()
    return path


def make_booklet_pdf(path, students, n, upside_down=(), back_flipped=False, inside_first=()):
    """A3 sides of ``students`` booklets of ``n`` pages, scanned open.
    ``upside_down`` holds (student, sheet) pairs that went in upside down;
    ``inside_first`` the students whose booklet was stacked as it lay open."""
    doc = fitz.open()
    for s in range(1, students + 1):
        sides = []
        for i in range(n // 4):
            for left, right in ((n - 2 * i, 2 * i + 1), (2 * i + 2, n - 2 * i - 1)):
                sides.append((i, left, right))
        if s in inside_first:
            sides.reverse()
        for k, (i, left, right) in enumerate(sides):
            flipped = (s, i) in upside_down or (back_flipped and k % 2 == 1)
            page = doc.new_page(width=2 * W, height=H)
            draw_page(page, left, s, 0, flipped)
            draw_page(page, right, s, W, flipped)
    doc.save(path)
    doc.close()
    return path


def read_page(pdf_page):
    """(page number, student) read back from the marks, or None if unreadable."""
    pix = pdf_page.get_pixmap(dpi=36)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
    scale = 36 / 72

    def dark(x, y):
        box = (int((x + 4) * scale), int((y + 4) * scale), int((x + SLOT - 10) * scale), int((y + SLOT - 10) * scale))
        return min(img.crop(box).getextrema()) < 80

    rect = pdf_page.rect
    if rect.width > rect.height:
        return None
    number = [k + 1 for k in range(16) if dark(20 + k * SLOT, 20)]
    student = [k + 1 for k in range(16) if dark(20 + k * SLOT, rect.height - 50)]
    return (number[0], student[0]) if len(number) == 1 and len(student) == 1 else None


def read_paper(path):
    with fitz.open(path) as doc:
        return [read_page(p) for p in doc]


class BookletLayoutTests(unittest.TestCase):
    def test_eight_page_booklet(self):
        # sides: 8|1, 2|7, 6|3, 4|5
        self.assertEqual(pages.booklet_layout(4), [
            (0, "right"), (1, "left"), (2, "right"), (3, "left"),
            (3, "right"), (2, "left"), (1, "right"), (0, "left")])

    def test_short_paper_skips_missing_sides(self):
        self.assertEqual(len(pages.booklet_layout(3)), 6)
        self.assertEqual(pages.booklet_side(1, 4), 0)
        self.assertEqual(pages.booklet_side(5, 4), 3)


class PagesTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        patcher = mock.patch.dict(os.environ, {"CAM2_APP_DATA": os.path.join(self.root, "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.session, self.config, self.grades = storage.create_session(
            os.path.join(self.root, "session"), "Y9 Test")

    def tearDown(self):
        self.tmp.cleanup()

    def path(self, name):
        return os.path.join(self.root, name)

    def papers(self):
        return [read_paper(workflow.student_scan_path(self.session, s)) for s in self.config["students"]]


class ImportTests(PagesTestCase):
    def test_joined_pdfs_split_as_one_stack(self):
        # Three students of 2 pages, scanned in two batches that split student 2.
        whole = make_pages_pdf(self.path("whole.pdf"), 3, 2)
        with fitz.open(whole) as doc:
            for name, (a, b) in (("batch1.pdf", (0, 2)), ("batch2.pdf", (3, 5))):
                part = fitz.open()
                part.insert_pdf(doc, from_page=a, to_page=b)
                part.save(self.path(name))
                part.close()
        workflow.import_scans(self.session, self.config, {
            "type": "combined", "paths": [self.path("batch1.pdf"), self.path("batch2.pdf")],
            "pages_per_student": 2, "students": 3})
        self.assertEqual(self.papers(), [[(1, 1), (2, 1)], [(1, 2), (2, 2)], [(1, 3), (2, 3)]])
        self.assertEqual(self.config["scan_warnings"]["class_size"], None)
        self.assertEqual(len(self.config["import"]["sources"]), 2)

    def test_old_single_path_source_still_works(self):
        make_pages_pdf(self.path("class.pdf"), 2, 2)
        workflow.import_scans(self.session, self.config,
                              {"type": "combined", "path": self.path("class.pdf"), "pages_per_student": 2})
        self.assertEqual(len(self.config["students"]), 2)

    def test_booklets_are_unfolded_in_reading_order(self):
        make_booklet_pdf(self.path("booklets.pdf"), 2, 8)
        workflow.import_scans(self.session, self.config, {
            "type": "combined", "paths": [self.path("booklets.pdf")], "layout": "booklet",
            "pages_per_student": 8, "students": 2})
        self.assertEqual(self.papers(), [[(p, s) for p in range(1, 9)] for s in (1, 2)])
        self.assertEqual([s["pages"] for s in self.config["students"]], [8, 8])
        self.assertIsNone(self.config["scan_warnings"]["class_size"])
        self.assertEqual(slicer.detect_paper(workflow.student_scan_path(
            self.session, self.config["students"][0])), ("A4", False))

    def test_back_sides_upside_down(self):
        make_booklet_pdf(self.path("booklets.pdf"), 1, 8, back_flipped=True)
        source = {"type": "combined", "paths": [self.path("booklets.pdf")], "layout": "booklet",
                  "pages_per_student": 8}
        workflow.import_scans(self.session, self.config, source)
        self.assertNotEqual(self.papers()[0], [(p, 1) for p in range(1, 9)])
        workflow.import_scans(self.session, self.config, dict(source, flip_backs=True))
        self.assertEqual(self.papers()[0], [(p, 1) for p in range(1, 9)])

    def test_booklets_stacked_inside_sheet_first(self):
        make_booklet_pdf(self.path("booklets.pdf"), 2, 12, inside_first={1, 2})
        workflow.import_scans(self.session, self.config, {
            "type": "combined", "paths": [self.path("booklets.pdf")], "layout": "booklet",
            "pages_per_student": 12, "inside_first": True})
        self.assertEqual(self.papers(), [[(p, s) for p in range(1, 13)] for s in (1, 2)])
        self.assertTrue(self.config["import"]["inside_first"])

    def test_booklet_pages_must_be_a_multiple_of_four(self):
        make_booklet_pdf(self.path("booklets.pdf"), 1, 8)
        with self.assertRaises(UserError) as ctx:
            workflow.check_source({"type": "combined", "paths": [self.path("booklets.pdf")],
                                   "layout": "booklet", "pages_per_student": 6})
        self.assertEqual(ctx.exception.code, "booklet_pages_invalid")

    def test_preview_shows_the_first_paper_unfolded(self):
        make_booklet_pdf(self.path("booklets.pdf"), 3, 8)
        result = workflow.preview_paper({"type": "combined", "paths": [self.path("booklets.pdf")],
                                         "layout": "booklet", "pages_per_student": 8})
        self.assertEqual((result["pages"], result["papers"], result["paper"]), (8, 3, "A4"))
        self.assertTrue(result["images"][0].startswith(b"\xff\xd8"))

    def test_photos_of_pages(self):
        folder = self.path("photos")
        os.makedirs(folder)
        with fitz.open(make_pages_pdf(self.path("p.pdf"), 2, 2)) as doc:
            for i, page in enumerate(doc, 1):
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                img.save(os.path.join(folder, f"IMG_{i}.jpg"), quality=90, dpi=(150, 150))
        workflow.import_scans(self.session, self.config,
                              {"type": "photos", "path": folder, "pages_per_student": 2})
        self.assertEqual(self.papers(), [[(1, 1), (2, 1)], [(1, 2), (2, 2)]])
        self.assertTrue(all(s["file"].endswith(".pdf") for s in self.config["students"]))


class PageFixTests(PagesTestCase):
    def stack(self, pdf_maker, per=2, **extra):
        workflow.import_scans(self.session, self.config, dict(
            {"type": "combined", "paths": [pdf_maker], "pages_per_student": per}, **extra))

    def edit(self, index, page, action):
        sid = self.config["students"][index]["id"]
        return workflow.edit_pages(self.session, self.config, self.grades, sid, page, action)

    def test_removing_a_double_fed_page_moves_the_rest_back(self):
        whole = make_pages_pdf(self.path("whole.pdf"), 3, 2)
        with fitz.open(whole) as doc, fitz.open(whole) as copy:   # student 1's page 2 went through twice
            doc.insert_pdf(copy, from_page=1, to_page=1, start_at=2)
            doc.save(self.path("double.pdf"))
        self.stack(self.path("double.pdf"))
        self.assertEqual(self.config["scan_warnings"]["leftover"], 1)
        where = self.edit(1, 1, "remove")
        self.assertEqual(self.papers(), [[(1, 1), (2, 1)], [(1, 2), (2, 2)], [(1, 3), (2, 3)]])
        self.assertEqual(self.config["scan_warnings"]["leftover"], 0)
        self.assertEqual(where, {"student": self.config["students"][1]["id"], "page": 1})

    def test_blank_page_for_a_missing_page(self):
        whole = make_pages_pdf(self.path("whole.pdf"), 3, 2)
        with fitz.open(whole) as doc:            # student 2's page 1 is missing
            doc.delete_page(2)
            doc.save(self.path("missing.pdf"))
        self.stack(self.path("missing.pdf"))
        self.assertEqual(len(self.config["students"]), 3)
        self.edit(1, 1, "blank_before")
        papers = self.papers()
        self.assertEqual(papers[1], [None, (2, 2)])
        self.assertEqual(papers[2], [(1, 3), (2, 3)])

    def test_moving_a_page_across_papers(self):
        whole = make_pages_pdf(self.path("whole.pdf"), 2, 2)
        with fitz.open(whole) as doc:            # pages 2 and 3 swapped
            doc.move_page(2, 1)
            doc.save(self.path("swapped.pdf"))
        self.stack(self.path("swapped.pdf"))
        where = self.edit(0, 2, "later")
        self.assertEqual(self.papers(), [[(1, 1), (2, 1)], [(1, 2), (2, 2)]])
        self.assertEqual(where["page"], 1)

    def test_turning_an_upside_down_page(self):
        self.stack(make_pages_pdf(self.path("whole.pdf"), 1, 2))
        self.edit(0, 2, "turn")
        self.edit(0, 2, "turn")
        with fitz.open(workflow.student_scan_path(self.session, self.config["students"][0])) as doc:
            self.assertEqual(doc[1].rotation, 180)

    def test_turning_an_upside_down_booklet_sheet(self):
        make_booklet_pdf(self.path("booklets.pdf"), 2, 8, upside_down={(2, 1)})
        self.stack(self.path("booklets.pdf"), per=8, layout="booklet")
        right = [[(p, s) for p in range(1, 9)] for s in (1, 2)]
        self.assertNotEqual(self.papers()[1], right[1])
        self.edit(1, 3, "turn_sheet")             # page 3 is on the second sheet
        self.assertEqual(self.papers(), right)

    def test_swapping_a_sheet_scanned_face_down(self):
        make_booklet_pdf(self.path("booklets.pdf"), 1, 8)
        with fitz.open(self.path("booklets.pdf")) as doc:
            doc.move_page(3, 2)                   # sheet 2's faces in the wrong order
            doc.save(self.path("face_down.pdf"))
        self.stack(self.path("face_down.pdf"), per=8, layout="booklet")
        self.edit(0, 4, "swap_sheet")
        self.assertEqual(self.papers()[0], [(p, 1) for p in range(1, 9)])

    def test_one_booklet_stacked_the_other_way(self):
        # Student 2's booklet went in inside sheet first, and its outside sheet upside down.
        make_booklet_pdf(self.path("booklets.pdf"), 3, 12, inside_first={2}, upside_down={(2, 0)})
        self.stack(self.path("booklets.pdf"), per=12, layout="booklet")
        right = [[(p, s) for p in range(1, 13)] for s in (1, 2, 3)]
        self.config["students"][1]["roster_id"] = "r1"
        where = self.edit(1, 5, "reverse_sheets")
        self.assertEqual(where["page"], 1)
        self.assertIsNone(self.config["students"][1]["roster_id"])
        self.edit(1, 1, "turn_sheet")             # page 1 is on the outside sheet
        self.assertEqual(self.papers(), right)

    def test_reversing_keeps_a_face_down_sheet_marked(self):
        # Stacked inside sheet first, and the innermost sheet (scanned first) face down.
        make_booklet_pdf(self.path("booklets.pdf"), 1, 12, inside_first={1})
        with fitz.open(self.path("booklets.pdf")) as doc:
            doc.move_page(1, 0)
            doc.save(self.path("face_down.pdf"))
        self.stack(self.path("face_down.pdf"), per=12, layout="booklet")
        self.edit(0, 1, "swap_sheet")             # marked before the order was noticed
        self.edit(0, 1, "reverse_sheets")
        self.assertEqual(self.papers()[0], [(p, 1) for p in range(1, 13)])

    def test_graded_papers_are_not_changed(self):
        self.stack(make_pages_pdf(self.path("whole.pdf"), 2, 2))
        self.grades["grades"] = {self.config["students"][1]["id"]: {"q1": {"value": 3}}}
        with self.assertRaises(UserError) as ctx:
            self.edit(0, 2, "later")              # would move a page into student 2
        self.assertEqual(ctx.exception.code, "pages_locked_graded")
        self.edit(0, 1, "turn")                   # student 1 alone is fine

    def test_folder_picture_becomes_a_pdf_when_fixed(self):
        folder = self.path("one per student")
        os.makedirs(folder)
        Image.new("RGB", (400, 566), "white").save(os.path.join(folder, "Tanaka.jpg"))
        workflow.import_scans(self.session, self.config, {"type": "folder", "path": folder})
        self.edit(0, 1, "blank_after")
        student = self.config["students"][0]
        self.assertEqual((student["file"], student["pages"]), ("Tanaka.pdf", 2))
        self.assertEqual(sorted(os.listdir(self.session.path(storage.SCANS_DIR))), ["Tanaka.pdf"])


class LatePaperTests(PagesTestCase):
    def setUp(self):
        super().setUp()
        make_pages_pdf(self.path("class.pdf"), 3, 2)
        workflow.import_scans(self.session, self.config, {
            "type": "combined", "paths": [self.path("class.pdf")], "pages_per_student": 2, "students": 3})
        self.config["layout"] = {"paper": "A4", "density": "normal", "landscape": False}
        self.config["mode"] = "marks"
        self.config["questions"] = [{"id": "q1", "label": "Q1", "boxes": ["page1!A1:C3"], "max": 5,
                                     "rubric_id": None}]

    def test_late_student_is_added_and_sliced(self):
        workflow.slice_session(self.session, self.config)
        self.grades["grades"] = {"s001": {"q1": {"value": 4}}}
        make_pages_pdf(self.path("late.pdf"), 1, 2, start_student=4)
        added = workflow.add_papers(self.session, self.config,
                                    {"type": "combined", "paths": [self.path("late.pdf")],
                                     "pages_per_student": 2})
        self.assertEqual(added, ["s004"])
        self.assertEqual([s["id"] for s in self.config["students"]], ["s001", "s002", "s003", "s004"])
        self.assertEqual(self.papers()[3], [(1, 4), (2, 4)])
        self.assertTrue(self.config["sliced"])
        self.assertTrue(os.path.isfile(self.session.path("crops/q1/s004.png")))
        self.assertEqual(self.config["students"][3]["batch"], 1)
        # The class's own stack checks are not upset by the late paper.
        self.assertIsNone(self.config["scan_warnings"]["class_size"])

    def test_late_paper_page_fixes_stay_in_its_own_batch(self):
        make_pages_pdf(self.path("late.pdf"), 1, 2, start_student=4)
        workflow.add_papers(self.session, self.config, {
            "type": "combined", "paths": [self.path("late.pdf")], "pages_per_student": 2})
        workflow.edit_pages(self.session, self.config, self.grades, "s004", 1, "earlier")
        self.assertEqual(self.papers()[2], [(1, 3), (2, 3)])


if __name__ == "__main__":
    unittest.main()
