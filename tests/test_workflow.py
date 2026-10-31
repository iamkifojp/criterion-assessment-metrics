"""Steps 1–3 as engine operations: import, set-up, slicing, names.

Run:  python -m unittest tests.test_workflow
"""

import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

from engine import model, storage, workflow
from engine.errors import UserError
from engine.slicer import Layout
from tests.helpers import center_color, make_pdf

RED = (255, 0, 0)


class WorkflowTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        patcher = mock.patch.dict(os.environ, {"CAM2_APP_DATA": os.path.join(self.root, "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.layout = Layout("A4")
        self.scans = os.path.join(self.root, "scans in")
        os.makedirs(self.scans)
        for name in ("Tanaka Hana.pdf", "Sato Ken.pdf", "scan_003.pdf"):
            make_pdf(os.path.join(self.scans, name), pages=2,
                     fills={1: [(self.layout, 1, 1, RED)]})
        self.session, self.config, _ = storage.create_session(
            os.path.join(self.root, "session"), "Y8 Test")

    def tearDown(self):
        self.tmp.cleanup()

    def imported(self):
        return workflow.import_scans(self.session, self.config,
                                     {"type": "folder", "path": self.scans})


class ImportTests(WorkflowTestCase):
    def test_inspect(self):
        info = workflow.inspect_scans_folder(self.scans)
        self.assertEqual((info["count"], info["paper"], info["landscape"]), (3, "A4", False))
        with self.assertRaises(UserError):
            workflow.inspect_scans_folder(os.path.join(self.root, "nope"))
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        with self.assertRaises(UserError) as ctx:
            workflow.inspect_scans_folder(empty)
        self.assertEqual(ctx.exception.code, "no_scans_found")

    def test_folder_import_copies_and_thumbnails(self):
        seen = []
        config = workflow.import_scans(self.session, self.config,
                                       {"type": "folder", "path": self.scans},
                                       lambda d, t: seen.append((d, t)))
        self.assertEqual([s["id"] for s in config["students"]], ["s001", "s002", "s003"])
        self.assertEqual(config["students"][0]["pages"], 2)
        self.assertTrue(os.path.isfile(self.session.path("thumbs/s001.jpg")))
        self.assertTrue(os.path.isfile(self.session.path("scans/Sato Ken.pdf")))
        self.assertEqual(seen[-1], (6, 6))
        self.assertEqual(config["scan_warnings"], {"page_counts": [], "leftover": 0, "class_size": None})

    def test_combined_import_checks_class_size(self):
        combined = make_pdf(os.path.join(self.root, "class.pdf"), pages=4)
        config = workflow.import_scans(self.session, self.config,
                                       {"type": "combined", "path": combined,
                                        "pages_per_student": 2, "students": 3})
        self.assertEqual(config["scan_warnings"]["leftover"], 0)
        self.assertEqual(config["scan_warnings"]["class_size"]["diff"], -2)
        self.assertEqual(config["import"]["students"], 3)

    def test_combined_import_and_reimport(self):
        combined = make_pdf(os.path.join(self.root, "class.pdf"), pages=5)
        config = workflow.import_scans(self.session, self.config,
                                       {"type": "combined", "path": combined, "pages_per_student": 2})
        self.assertEqual(len(config["students"]), 3)
        self.assertEqual(config["scan_warnings"]["leftover"], 1)
        self.assertIsNone(config["scan_warnings"]["class_size"])
        self.assertEqual(config["students"][0]["source"], "class.pdf · 1")
        self.assertEqual(workflow.display_name(config, config["students"][2]), "class.pdf · 3")
        # Choosing different scans replaces the first import entirely
        config = self.imported()
        self.assertEqual(sorted(os.listdir(self.session.path("scans"))),
                         ["Sato Ken.pdf", "Tanaka Hana.pdf", "scan_003.pdf"])

    def test_session_folder_choice(self):
        empty = os.path.join(self.root, "empty")
        self.assertEqual(workflow.choose_session_folder(empty, "Exam"), empty)
        busy = os.path.join(self.root, "busy")
        os.makedirs(busy)
        open(os.path.join(busy, "notes.txt"), "w").close()
        self.assertEqual(workflow.choose_session_folder(busy, "Y8: Test"),
                         os.path.join(busy, "Y8_ Test"))
        with self.assertRaises(UserError):
            workflow.choose_session_folder(self.session.folder, "Exam")


class SetupTests(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.imported()
        workflow.set_mode(self.config, "marks")

    def test_drafts_may_be_incomplete_but_slicing_may_not(self):
        workflow.set_questions(self.config, {"name_box": ["a1:c2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2"], "max": "4"},
            {"id": "q2", "label": "Q2", "boxes": [], "max": None}]})
        self.assertEqual(self.config["name_box"], ["page1!A1:C2"])
        self.assertEqual(self.config["questions"][0]["max"], 4)
        with self.assertRaises(UserError) as ctx:
            workflow.check_ready(self.config)
        self.assertEqual(ctx.exception.code, "question_needs_box")

    def test_questions_assessed_on_several_criteria(self):
        workflow.set_mode(self.config, "rubric")
        workflow.set_rubrics(self.config, [{"name": n, "bands": [{"levels": "0-8"}]}
                                           for n in ("Criterion A", "Criterion B", "Criterion C")])
        workflow.set_questions(self.config, {"questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2"], "rubric_ids": ["r3", "r9", "r2"]},
            {"id": "q2", "label": "Q2", "boxes": ["page1!B3"], "rubric_id": "r1"}]})   # older browser
        self.assertEqual([q["rubric_ids"] for q in self.config["questions"]], [["r2", "r3"], ["r1"]])
        workflow.check_ready(self.config)
        workflow.set_rubrics(self.config, self.config["rubrics"][:2])     # Criterion C deleted
        self.assertEqual(self.config["questions"][0]["rubric_ids"], ["r2"])
        workflow.set_rubrics(self.config, self.config["rubrics"][1:] + [{"name": "Criterion D", "bands": [{"levels": "0-8"}]}])
        self.assertEqual(self.config["questions"][1]["rubric_ids"], [])      # Criterion A deleted
        with self.assertRaises(UserError) as ctx:
            workflow.check_ready(self.config)
        self.assertEqual(ctx.exception.code, "question_has_no_rubric")

    def test_check_ready_messages(self):
        cases = [
            ({"questions": []}, "no_questions"),
            ({"questions": [{"id": "q1", "label": "", "boxes": ["B2"], "max": 1}]}, "question_needs_label"),
            ({"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 1},
                            {"id": "q2", "label": "q1", "boxes": ["B3"], "max": 1}]}, "duplicate_label"),
            ({"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": None}]}, "question_needs_max"),
        ]
        for payload, code in cases:
            workflow.set_questions(self.config, payload)
            with self.assertRaises(UserError, msg=code) as ctx:
                workflow.check_ready(self.config)
            self.assertEqual(ctx.exception.code, code)

    def test_bad_values_are_rejected_at_once(self):
        with self.assertRaises(UserError):
            workflow.set_questions(self.config, {"questions": [{"label": "Q1", "boxes": ["Z99"]}]})
        with self.assertRaises(UserError):
            workflow.set_questions(self.config, {"questions": [{"label": "Q1", "max": 500}]})

    def test_editing_boxes_marks_papers_unsliced(self):
        payload = {"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2}]}
        workflow.set_questions(self.config, payload)
        workflow.slice_session(self.session, self.config)
        self.assertTrue(self.config["sliced"])
        payload["questions"][0]["max"] = 3                 # marks only: still sliced
        workflow.set_questions(self.config, payload)
        self.assertTrue(self.config["sliced"])
        payload["questions"][0]["boxes"] = ["B2:C3"]
        workflow.set_questions(self.config, payload)
        self.assertFalse(self.config["sliced"])

    def test_reordering_questions_keeps_papers_sliced(self):
        q1 = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2}
        q2 = {"id": "q2", "label": "Q2", "boxes": ["B5"], "max": 3}
        workflow.set_questions(self.config, {"questions": [q1, q2]})
        workflow.slice_session(self.session, self.config)
        workflow.set_questions(self.config, {"questions": [q2, q1]})
        self.assertTrue(self.config["sliced"])
        self.assertEqual([q["id"] for q in self.config["questions"]], ["q2", "q1"])

    def test_layout_change_clears_boxes(self):
        workflow.set_questions(self.config, {"name_box": ["A1"],
                                             "questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2}]})
        workflow.set_layout(self.config, "B5", "5mm", False)
        self.assertEqual(self.config["name_box"], [])
        self.assertEqual(self.config["questions"][0]["boxes"], [])
        self.assertEqual(self.config["questions"][0]["max"], 2)

    def test_new_sessions_use_the_5mm_grid_only(self):
        self.assertEqual(self.config["layout"]["density"], "5mm")
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": []})
        workflow.set_layout(self.config, "A4", "fine", False)        # not offered any more
        self.assertEqual(self.config["layout"]["density"], "5mm")
        self.assertEqual(self.config["name_box"], ["page1!A1:A1"])

    def test_old_grid_session_moves_to_5mm_when_layout_changes(self):
        self.config["layout"] = {"paper": "A4", "density": "normal", "landscape": False}
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": []})
        workflow.set_layout(self.config, "A4", "normal", False)      # unchanged: boxes kept
        self.assertEqual(self.config["name_box"], ["page1!A1:A1"])
        workflow.set_layout(self.config, "B5", "normal", False)
        self.assertEqual(self.config["layout"], {"paper": "B5", "density": "5mm", "landscape": False})
        self.assertEqual(self.config["name_box"], [])

    def test_mode_is_fixed_after_grading(self):
        grades = model.new_grades("x")
        workflow.set_mode(self.config, "rubric", grades)             # nothing graded yet
        workflow.set_mode(self.config, "marks", grades)
        grades["grades"] = {"s001": {"q1": {"value": None, "comment": "only a comment"}}}
        workflow.set_mode(self.config, "rubric", grades)             # comments don't count
        grades["grades"]["s001"]["q1"]["value"] = 2
        with self.assertRaises(UserError) as ctx:
            workflow.set_mode(self.config, "marks", grades)
        self.assertEqual(ctx.exception.code, "mode_locked")

    def test_rubric_mode(self):
        workflow.set_mode(self.config, "rubric")
        workflow.set_rubrics(self.config, [{"name": "", "bands": [{"levels": "0"}, {"levels": "1-8"}]}])
        self.assertEqual(self.config["rubrics"][0]["id"], "r1")
        self.assertEqual(self.config["rubrics"][0]["name"], "Rubric 1")
        workflow.set_questions(self.config, {"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"]}]})
        workflow.check_ready(self.config)          # the only rubric is used automatically
        with self.assertRaises(UserError):
            workflow.set_mode(self.config, "stars")

    def test_slice_two_page_question_and_name_box(self):
        workflow.set_questions(self.config, {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2", "page2!A1"], "max": 5}]})
        summary = workflow.slice_session(self.session, self.config)
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["crops"], 6)
        with Image.open(self.session.path(f"crops/{model.NAME_BOX_ID}/s001.png")) as im:
            self.assertEqual(center_color(im.convert("RGB")), RED)
        with Image.open(self.session.path("crops/q1/s002.png")) as im:
            self.assertGreater(im.height, im.width / 2)          # two cells stacked

    def test_choice_groups_are_checked_before_slicing(self):
        workflow.set_questions(self.config, {
            "questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2},
                          {"id": "q2", "label": "Q2", "boxes": ["B3"], "max": 2}],
            "choice_groups": [{"questions": ["q1", "q2"], "answer": 2}]})
        with self.assertRaises(UserError) as ctx:
            workflow.check_ready(self.config)
        self.assertEqual(ctx.exception.code, "choice_group_invalid")


class NameTests(WorkflowTestCase):
    def setUp(self):
        super().setUp()
        self.imported()

    def test_roster_auto_matches_file_names(self):
        roster = [{"id": "n001", "name": "Hana Tanaka"}, {"id": "n002", "name": "Ken Sato"},
                  {"id": "n003", "name": "Mei Ito"}]
        workflow.set_roster(self.config, roster)
        # Papers sort as "Sato Ken", "scan_003", "Tanaka Hana"
        matched = {s["id"]: s["roster_id"] for s in self.config["students"]}
        self.assertEqual(matched, {"s001": "n002", "s002": None, "s003": "n001"})
        self.assertEqual(workflow.display_name(self.config, self.config["students"][0]), "Ken Sato")
        self.assertEqual(workflow.display_name(self.config, self.config["students"][1]), "scan_003")

    def test_a_name_belongs_to_one_paper(self):
        workflow.set_roster(self.config, [{"id": "n001", "name": "Mei Ito"}], auto=False)
        workflow.match_student(self.config, "s001", "n001")
        workflow.match_student(self.config, "s003", "n001")
        self.assertIsNone(self.config["students"][0]["roster_id"])
        self.assertEqual(self.config["students"][2]["roster_id"], "n001")
        workflow.match_student(self.config, "s003", None, name="Typed Name")
        self.assertEqual(workflow.display_name(self.config, self.config["students"][2]), "Typed Name")
        workflow.clear_roster(self.config)
        self.assertEqual(self.config["roster"], [])


if __name__ == "__main__":
    unittest.main()
