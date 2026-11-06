"""Steps 1–3 as engine operations: import, set-up, slicing, names.

Run:  python -m unittest tests.test_workflow
"""

import os
import tempfile
import unittest
from unittest import mock

from PIL import Image

from engine import grading_summary, model, storage, workflow
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

    def test_new_question_skips_a_deleted_questions_id(self):
        grades = {"grades": {"s001": {"q1": {"value": 9}}}}       # q1 graded, then deleted
        workflow.set_questions(self.config, {"questions": [
            {"id": "q2", "label": "Q2", "boxes": []}, {"label": "Q3", "boxes": []}]}, grades)
        self.assertEqual([q["id"] for q in self.config["questions"]], ["q2", "q3"])

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
        self.assertEqual(ctx.exception.code, "question_needs_marks_or_criterion")

    def test_check_ready_messages(self):
        cases = [
            ({"questions": []}, "no_questions"),
            ({"questions": [{"id": "q1", "label": "", "boxes": ["B2"], "max": 1}]}, "question_needs_label"),
            ({"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 1},
                            {"id": "q2", "label": "q1", "boxes": ["B3"], "max": 1}]}, "duplicate_label"),
            ({"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"], "max": None}]},
             "question_needs_marks_or_criterion"),
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

    def test_adjusting_one_box_reslices_only_that_question(self):
        q1 = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2}
        q2 = {"id": "q2", "label": "Q2", "boxes": ["B5"], "max": 3}
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": [q1, q2]})
        workflow.slice_session(self.session, self.config)
        q2_crop = self.session.path("crops/q2/s001.png")
        q2_time = os.path.getmtime(q2_crop)
        with Image.open(self.session.path("crops/q1/s001.png")) as im:
            self.assertEqual(center_color(im.convert("RGB")), RED)

        q1["boxes"] = ["B3"]                                  # Q1's box moved off the red cell
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": [q1, q2]})
        self.assertFalse(self.config["sliced"])
        self.assertEqual(workflow.stale_regions(self.config), ["q1"])
        summary = workflow.slice_question(self.session, self.config, "q1")
        self.assertEqual((summary["errors"], summary["crops"]), ([], 3))
        self.assertTrue(self.config["sliced"])
        with Image.open(self.session.path("crops/q1/s001.png")) as im:
            self.assertNotEqual(center_color(im.convert("RGB")), RED)
        self.assertEqual(os.path.getmtime(q2_crop), q2_time)            # Q2 untouched

        # Moving a box back where it was needs no slicing at all
        q2["boxes"] = ["B6"]
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": [q1, q2]})
        self.assertFalse(self.config["sliced"])
        q2["boxes"] = ["B5"]
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": [q1, q2]})
        self.assertTrue(self.config["sliced"])

        # Two boxes moved: re-slicing one leaves the papers unsliced
        q1["boxes"], q2["boxes"] = ["B4"], ["B6"]
        workflow.set_questions(self.config, {"name_box": ["A1"], "questions": [q1, q2]})
        workflow.slice_question(self.session, self.config, "q1")
        self.assertFalse(self.config["sliced"])
        workflow.slice_question(self.session, self.config, "q2")
        self.assertTrue(self.config["sliced"])
        with self.assertRaises(UserError):
            workflow.slice_question(self.session, self.config, "q9")

    def test_reslicing_one_question_needs_current_papers(self):
        q1 = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 2}
        workflow.set_questions(self.config, {"questions": [q1]})
        with self.assertRaises(UserError) as ctx:                       # never sliced
            workflow.slice_question(self.session, self.config, "q1")
        self.assertEqual(ctx.exception.code, "not_sliced")
        workflow.slice_session(self.session, self.config)
        del self.config["crops_of"]                                     # sliced by an older CAM2
        q1["boxes"] = ["B3"]
        workflow.set_questions(self.config, {"questions": [q1]})
        self.assertEqual(workflow.stale_regions(self.config), ["q1"])
        workflow.slice_question(self.session, self.config, "q1")
        self.assertTrue(self.config["sliced"])
        # A late paper added while unsliced has no crops: only slicing everything helps
        q1["boxes"] = ["B4"]
        workflow.set_questions(self.config, {"questions": [q1]})
        workflow.add_papers(self.session, self.config, {"type": "folder", "path": self.scans})
        with self.assertRaises(UserError):
            workflow.slice_question(self.session, self.config, "q1")

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

    def test_changing_the_starting_choice_changes_no_question(self):
        workflow.set_questions(self.config, {"questions": [
            {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 4}]})
        before = [dict(q) for q in self.config["questions"]]
        workflow.set_mode(self.config, "rubric")
        self.assertEqual(self.config["questions"], before)
        self.assertEqual(grading_summary.question_mode(self.config, self.config["questions"][0]), "marks")
        workflow.check_ready(self.config)

    def test_a_graded_question_cannot_gain_or_lose_marks(self):
        rubric = {"name": "Criterion A", "bands": [{"levels": "0-8"}]}
        workflow.set_rubrics(self.config, [rubric, dict(rubric, name="Criterion B")])
        q1 = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 4}
        q2 = {"id": "q2", "label": "Q2", "boxes": ["B3"], "rubric_ids": ["r1"]}
        q3 = {"id": "q3", "label": "Q3", "boxes": ["B4"], "max": 4}
        q4 = {"id": "q4", "label": "Q4", "boxes": ["B5"], "rubric_ids": ["r1"]}
        payload = {"questions": [q1, q2, q3, q4]}
        workflow.set_questions(self.config, payload)
        grades = model.new_grades("x")
        grading_summary.set_grade(self.config, grades, "s001", "q1", 3)
        grading_summary.set_grade(self.config, grades, "s001", "q2", 6)
        grading_summary.set_grade(self.config, grades, "s001", "q3", comment="Only a comment.")
        for question, change in ((q1, {"max": None}), (q2, {"max": 8})):
            with self.assertRaises(UserError) as ctx:
                workflow.set_questions(self.config, {"questions": [
                    dict(q, **change) if q is question else q for q in payload["questions"]]}, grades)
            self.assertEqual(ctx.exception.code, "question_marks_locked")
        # Nothing changed, and every other question stays open: a comment is not a grade.
        self.assertEqual(self.config["questions"][1]["max"], None)
        workflow.set_questions(self.config, {"questions": [
            dict(q1, max=10, rubric_ids=["r1"]), dict(q2, rubric_ids=["r1", "r2"]),
            dict(q3, max=None, rubric_ids=["r2"]), dict(q4, max=8)]}, grades)
        self.assertEqual([grading_summary.question_mode(self.config, q) for q in self.config["questions"]],
                         ["marks", "rubric", "rubric", "marks"])

    def test_going_back_to_fill_in_what_was_left_out_needs_no_slicing(self):
        q1 = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 4}
        q2 = {"id": "q2", "label": "Q2", "boxes": ["B5"], "max": 3}
        workflow.set_questions(self.config, {"questions": [q1, q2]})
        workflow.slice_session(self.session, self.config)
        grades = model.new_grades("x")
        grading_summary.set_grade(self.config, grades, "s001", "q1", 3)
        # Marks first, criteria later, even during grading
        workflow.set_rubrics(self.config, [{"name": "Criterion A", "bands": [{"levels": "0-8"}]}])
        workflow.set_questions(self.config, {"questions": [dict(q1, rubric_ids=["r1"]), dict(q2, rubric_ids=["r1"])]}, grades)
        self.assertTrue(self.config["sliced"])
        self.assertEqual([q["boxes"] for q in self.config["questions"]], [["page1!B2:B2"], ["page1!B5:B5"]])
        self.assertEqual(grades["grades"]["s001"]["q1"]["value"], 3)
        # Rubric first, marks later: Q2 had no grade, loses its marks, then gains them back
        workflow.set_questions(self.config, {"questions": [dict(q1, rubric_ids=["r1"]), dict(q2, max=None, rubric_ids=["r1"])]}, grades)
        self.assertEqual(grading_summary.question_mode(self.config, self.config["questions"][1]), "rubric")
        workflow.set_questions(self.config, {"questions": [dict(q1, rubric_ids=["r1"]), dict(q2, max=6, rubric_ids=["r1"])]}, grades)
        self.assertEqual(self.config["questions"][1]["rubric_ids"], ["r1"])
        self.assertTrue(self.config["sliced"])

    def test_rubric_mode(self):
        workflow.set_mode(self.config, "rubric")
        workflow.set_rubrics(self.config, [{"name": "", "bands": [{"levels": "0"}, {"levels": "1-8"}]}])
        self.assertEqual(self.config["rubrics"][0]["id"], "r1")
        self.assertEqual(self.config["rubrics"][0]["name"], "Rubric 1")
        workflow.set_questions(self.config, {"questions": [{"id": "q1", "label": "Q1", "boxes": ["B2"]}]})
        workflow.check_ready(self.config)          # the only rubric is used automatically
        with self.assertRaises(UserError):
            workflow.set_mode(self.config, "stars")

    def with_sections(self, *groups, **extra):
        """Questions in sections: lists of (question id, max)."""
        sections = [{"id": f"sec{i}", "name": f"Part {i}"} for i in range(1, len(groups) + 1)]
        questions = [{"id": qid, "label": qid.upper(), "boxes": [f"B{qid[1:]}"], "max": top, "section_id": s["id"]}
                     for s, group in zip(sections, groups) for qid, top in group]
        return workflow.set_questions(self.config, dict({"sections": sections, "questions": questions}, **extra))

    def test_sections_are_saved_and_follow_the_paper(self):
        self.with_sections([("q1", 5)], [("q2", 5)])
        self.assertEqual([s["name"] for s in self.config["sections"]], ["Part 1", "Part 2"])
        self.assertEqual([s["weight"] for s in self.config["sections"]], [50, 50])
        q1, q2 = self.config["questions"]
        # A save that doesn't mention sections leaves them all alone
        workflow.set_questions(self.config, {"questions": [dict(q1), dict(q2)]})
        self.assertEqual(len(self.config["sections"]), 2)
        self.assertEqual(self.config["questions"][1]["section_id"], "sec2")
        # A question moved past a divider, a new one, and one naming a lost section
        moved = {"id": "q1", "label": "Q1", "boxes": ["B2"], "max": 5, "section_id": "sec1"}
        workflow.set_questions(self.config, {"questions": [dict(q2), moved, {"id": "q3", "label": "Q3", "section_id": "gone"}]})
        self.assertEqual([q["section_id"] for q in self.config["questions"]], ["sec2", "sec2", "sec2"])
        # Removing every divider
        workflow.set_questions(self.config, {"sections": [], "questions": [{"id": "q1", "label": "Q1", "section_id": "sec1"}]})
        self.assertEqual(self.config["sections"], [])
        self.assertNotIn("section_id", self.config["questions"][0])

    def test_new_sections_get_new_ids(self):
        workflow.set_questions(self.config, {"sections": [{"name": "A"}, {"id": "sec1", "name": "B"}], "questions": []})
        self.assertEqual([s["id"] for s in self.config["sections"]], ["sec2", "sec1"])
        # An id the browser made up is kept, because its questions name it
        workflow.set_questions(self.config, {"sections": [{"id": "sec2", "name": "B"}, {"id": "sec7"}, {"name": " C "}],
                                             "questions": [{"id": "q1", "label": "Q1", "section_id": "sec7"}]})
        self.assertEqual([(s["id"], s["name"]) for s in self.config["sections"]],
                         [("sec2", "B"), ("sec7", ""), ("sec3", "C")])
        self.assertEqual(self.config["questions"][0]["section_id"], "sec7")

    def test_sections_can_change_without_touching_grades_or_slicing(self):
        self.with_sections([("q1", 5), ("q2", 5)])
        workflow.slice_session(self.session, self.config)
        self.with_sections([("q1", 5)], [("q2", 5)])
        self.assertTrue(self.config["sliced"])

    def test_a_choice_group_across_two_sections_is_refused(self):
        group = [{"questions": ["q1", "q2"], "answer": 1}]
        with self.assertRaises(UserError) as ctx:
            self.with_sections([("q1", 5)], [("q2", 5)], choice_groups=group)
        self.assertEqual(ctx.exception.code, "choice_group_across_sections")
        self.assertEqual(self.config["questions"], [])                     # nothing was saved
        self.with_sections([("q1", 5), ("q2", 5)], [("q3", 5)], choice_groups=group)
        workflow.check_ready(self.config)

    def test_typing_shares(self):
        self.with_sections([("q1", 5)], [("q2", 5)], [("q3", 5)])
        self.assertEqual([s["weight"] for s in self.config["sections"]], [34, 33, 33])
        workflow.set_weighted(self.config, True)
        workflow.set_section_weight(self.config, "sec2", "20")
        self.assertEqual([s["weight"] for s in self.config["sections"]], [40, 20, 40])
        workflow.set_section_weight(self.config, "sec1", 50)
        self.assertEqual([s["weight"] for s in self.config["sections"]], [50, 20, 30])
        # Typing the last automatic one: it keeps what was typed and another takes the rest
        workflow.set_section_weight(self.config, "sec3", 45)
        self.assertEqual([s["weight"] for s in self.config["sections"]], [50, 5, 45])
        self.assertEqual([s["weight_typed"] for s in self.config["sections"]], [True, False, True])
        with self.assertRaises(UserError) as ctx:
            workflow.set_section_weight(self.config, "sec3", 51)
        self.assertEqual((ctx.exception.code, ctx.exception.params["max"]), ("section_weight_too_big", 50))
        for bad in (-1, 101, "half", 12.5):
            with self.assertRaises(UserError, msg=bad):
                workflow.set_section_weight(self.config, "sec1", bad)
        with self.assertRaises(UserError):
            workflow.set_section_weight(self.config, "sec9", 10)
        self.assertEqual(sum(s["weight"] for s in self.config["sections"]), 100)
        workflow.set_section_weight(self.config, "sec1", None)                # back to automatic
        self.assertEqual([s["weight"] for s in self.config["sections"]], [28, 27, 45])
        # Typed shares survive weighting being turned off and on
        workflow.set_weighted(self.config, False)
        workflow.set_weighted(self.config, True)
        self.assertEqual(self.config["sections"][2]["weight"], 45)

    def test_a_section_without_marks_has_no_share(self):
        workflow.set_rubrics(self.config, [{"name": "Criterion A", "bands": [{"levels": "0-8"}]}])
        self.with_sections([("q1", 5)], [("q2", None)], [("q3", 5)])
        self.assertEqual([s["weight"] for s in self.config["sections"]], [50, None, 50])
        with self.assertRaises(UserError):
            workflow.set_section_weight(self.config, "sec2", 10)
        workflow.set_section_weight(self.config, "sec1", 70)
        # Section 3 loses its marks: Section 1's typed share no longer has anyone to balance it
        self.with_sections([("q1", 5)], [("q2", None)], [("q3", None)])
        self.assertEqual([s["weight"] for s in self.config["sections"]], [100, None, None])

    def test_report_options(self):
        self.assertEqual(workflow.report_options(self.config), model.DEFAULT_REPORT_OPTIONS)
        self.with_sections([("q1", 5)], [("q2", 5)])
        workflow.set_report_options(self.config, {"section_results": 1, "no_images_for": ["sec1", "gone"]})
        options = workflow.report_options(self.config)
        self.assertEqual((options["section_results"], options["no_images_for"]), (True, ["sec1"]))
        workflow.set_report_options(self.config, {"rubric_table": False})
        options = workflow.report_options(self.config)
        self.assertEqual((options["section_results"], options["rubric_table"], options["overall_marks"]),
                         (True, False, True))
        self.assertEqual(model.DEFAULT_REPORT_OPTIONS["no_images_for"], [])
        # With no sections, the whole paper has one tick
        self.with_sections([("q1", 5)])
        workflow.set_questions(self.config, {"sections": [], "questions": []})
        workflow.set_report_options(self.config, {"no_images_for": [grading_summary.WHOLE_PAPER]})
        self.assertEqual(workflow.report_options(self.config)["no_images_for"], [grading_summary.WHOLE_PAPER])

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
