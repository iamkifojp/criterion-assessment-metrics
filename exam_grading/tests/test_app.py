"""The web server, driven through Flask's test client: start screen, Step 1
(create + import job), Step 2 (set-up + slice job), Step 3 (class list, matching),
errors, save failures and file-serving safety.

Run:  python -m unittest tests.test_app
"""

import io
import json
import os
import tempfile
import time
import unittest
from unittest import mock

import pymupdf as fitz
from openpyxl import Workbook
from PIL import Image

from app import create_app
from appstate import AppState
from engine import model, storage
from engine.slicer import Layout
from tests.helpers import make_pdf

RED = (255, 0, 0)


def xlsx(rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        env = mock.patch.dict(os.environ, {
            "CAM2_APP_DATA": os.path.join(self.root, "appdata"),
            "CAM2_DOCUMENTS_OVERRIDE": os.path.join(self.root, "Documents")})
        env.start()
        self.addCleanup(env.stop)
        self.state = AppState()
        self.client = create_app(self.state).test_client()
        self.scans = os.path.join(self.root, "scans")
        os.makedirs(self.scans)
        layout = Layout("A4")
        for name in ("Tanaka Hana.pdf", "Sato Ken.pdf"):
            make_pdf(os.path.join(self.scans, name), pages=2, fills={1: [(layout, 1, 1, RED)]})

    def tearDown(self):
        self.state.close_session()
        self.tmp.cleanup()

    def post(self, url, json=None, status=200):
        res = self.client.post(url, json=json if json is not None else {})
        self.assertEqual(res.status_code, status, res.get_json())
        return res.get_json()

    def fetch(self, url):
        """GET a file response and close it (send_file keeps the file open)."""
        res = self.client.get(url)
        res.get_data()
        res.close()
        return res

    def wait(self, job_id):
        for _ in range(200):
            job = self.client.get(f"/api/job/{job_id}").get_json()
            if job["status"] != "running":
                return job
            time.sleep(0.05)
        self.fail("job did not finish")

    def create(self, exam="Y8 Test"):
        data = self.post("/api/session/create", {
            "exam_name": exam, "paper": "A4", "landscape": False,
            "save_folder": os.path.join(self.root, "sessions"),
            "source": {"type": "folder", "path": self.scans}})
        job = self.wait(data["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        return job["session"]

    def set_up_questions(self):
        self.post("/api/setup/mode", {"mode": "marks"})
        self.post("/api/setup/questions", {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2:C3"], "max": 5},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1"], "max": 3}]})
        job = self.wait(self.post("/api/slice")["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        return job


class ScanToolTests(AppTestCase):
    def test_preview_paper(self):
        data = self.post("/api/preview-paper", {"source": {
            "type": "combined", "paths": [os.path.join(self.scans, "Sato Ken.pdf")],
            "pages_per_student": 1}})
        self.assertEqual((data["pages"], data["papers"], data["paper"]), (1, 2, "A4"))
        self.assertTrue(data["images"][0].startswith("data:image/jpeg;base64,"))
        data = self.post("/api/preview-paper", {"source": {
            "type": "combined", "paths": [os.path.join(self.scans, "Sato Ken.pdf")],
            "layout": "booklet", "pages_per_student": 6}}, status=400)
        self.assertEqual(data["error"], "booklet_pages_invalid")

    def test_page_fix_and_late_paper(self):
        self.create()
        data = self.post("/api/pages/edit", {"student": "s001", "page": 2, "action": "blank_after"})
        self.assertEqual(data["where"], {"student": "s001", "page": 3})
        self.assertEqual(data["session"]["config"]["students"][0]["pages"], 3)
        self.set_up_questions()
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "value": 4})
        data = self.post("/api/pages/edit", {"student": "s001", "page": 1, "action": "turn"}, status=400)
        self.assertEqual(data["error"], "pages_locked_graded")
        # New papers restart at s001, so replacing would hand these grades to someone else.
        data = self.post("/api/scans/replace", {"source": {"type": "folder", "path": self.scans}},
                         status=400)
        self.assertEqual(data["error"], "scans_locked_graded")

        late = os.path.join(self.root, "late")
        os.makedirs(late)
        make_pdf(os.path.join(late, "Ito Mei.pdf"), pages=2)
        job = self.wait(self.post("/api/scans/add", {"source": {"type": "folder", "path": late}})["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["result"]["added"], ["s003"])
        session = job["session"]
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["value"], 4)
        self.assertTrue(session["config"]["sliced"])
        self.assertEqual(self.fetch("/api/crop/q1/s003").status_code, 200)


class ShellTests(AppTestCase):
    def test_index_and_ping(self):
        self.assertIn(b"main.js", self.fetch("/").data)
        self.assertEqual(self.client.get("/api/ping").get_json()["app"], "cam2")
        self.assertIn(b"export", self.fetch("/static/js/main.js").data)

    def test_hide_names_preference(self):
        self.assertFalse(self.client.get("/api/state").get_json()["prefs"]["hide_names"])
        self.post("/api/prefs", {"hide_names": True})
        self.assertTrue(self.client.get("/api/state").get_json()["prefs"]["hide_names"])

    def test_shuffle_papers_preference(self):
        self.assertFalse(self.client.get("/api/state").get_json()["prefs"]["shuffle_papers"])
        self.post("/api/prefs", {"shuffle_papers": True})
        prefs = self.client.get("/api/state").get_json()["prefs"]
        self.assertEqual(prefs, {"hide_names": False, "shuffle_papers": True})   # independent of hiding

    def test_language_switch(self):
        self.assertEqual(self.client.get("/api/i18n").get_json()["language"], "en")
        self.post("/api/language", {"language": "ja"})
        data = self.client.get("/api/i18n").get_json()
        self.assertEqual(data["strings"]["save.button"], "💾 保存")
        err = self.post("/api/language", {"language": "fr"}, status=400)
        self.assertEqual(err["error"], "unknown_language")

    def test_errors_are_translated(self):
        self.post("/api/language", {"language": "ja"})
        err = self.post("/api/session/create", {"exam_name": ""}, status=400)
        self.assertEqual(err["error"], "exam_name_required")
        self.assertEqual(err["message"], "試験名を入力してください。")
        self.assertFalse(err["save_error"])

    def test_pickers_are_called_with_translated_titles(self):
        with mock.patch("app.pick_folder", return_value=r"C:\Scans") as picker:
            self.assertEqual(self.post("/api/pick", {"kind": "scans_folder"})["path"], r"C:\Scans")
            self.assertIn("folder", picker.call_args.args[0])
        with mock.patch("app.pick_pdf", return_value=None):
            self.assertIsNone(self.post("/api/pick", {"kind": "pdf"})["path"])
        self.post("/api/pick", {"kind": "virus"}, status=400)

    def test_default_folder_is_in_documents(self):
        path = self.client.get("/api/default-folder?exam=Y8 Test").get_json()["path"]
        self.assertEqual(path, os.path.join(self.root, "Documents", "CAM2 Exam Grading Sessions", "Y8 Test"))

    def test_inspect(self):
        info = self.post("/api/inspect", {"kind": "folder", "path": f'"{self.scans}"'})
        self.assertEqual(info["count"], 2)
        self.post("/api/inspect", {"kind": "pdf", "path": self.scans}, status=400)


class FlowTests(AppTestCase):
    def test_create_import_and_thumbnails(self):
        session = self.create()
        config = session["config"]
        self.assertEqual(len(config["students"]), 2)
        self.assertEqual(config["students"][0]["display_name"], "Sato Ken")
        self.assertEqual(session["grid"], {"cols": 42, "rows": 60})
        self.assertTrue(session["folder"].endswith("sessions"))
        res = self.fetch("/api/thumb/s001")
        self.assertEqual(res.mimetype, "image/jpeg")
        page = self.fetch("/api/page/s001/1?w=400&boxes=page1!B2")
        self.assertEqual(page.mimetype, "image/jpeg")
        recent = self.client.get("/api/state").get_json()["recent"]
        self.assertEqual(recent[0]["exam_name"], "Y8 Test")

    def test_creating_in_a_busy_folder_makes_a_subfolder(self):
        busy = os.path.join(self.root, "sessions")
        os.makedirs(busy)
        open(os.path.join(busy, "notes.txt"), "w").close()
        session = self.create()
        self.assertEqual(session["folder"], os.path.join(busy, "Y8 Test"))

    def test_setup_slice_and_names(self):
        self.create()
        job = self.set_up_questions()
        self.assertEqual(job["result"]["crops"], 6)
        self.assertTrue(job["session"]["config"]["sliced"])
        self.assertEqual(self.fetch("/api/crop/q1/s001").mimetype, "image/png")
        self.assertEqual(self.fetch("/api/crop/__name__/s002").mimetype, "image/png")
        preview = self.fetch("/api/preview-crop/s002?boxes=page1!B2,page2!A1")
        self.assertEqual(preview.mimetype, "image/jpeg")

        self.post("/api/step", {"step": 3})
        res = self.client.post("/api/roster/upload", data={
            "file": (io.BytesIO(xlsx([["No", "Family", "Given"], [1, "Sato", "Ken"], [2, "Tanaka", "Hana"]])),
                     "class.xlsx")}, content_type="multipart/form-data")
        upload = res.get_json()
        self.assertEqual(upload["columns"], [1, 2])
        self.assertTrue(upload["has_header"])
        session = self.post("/api/roster/columns", {"columns": [1, 2], "has_header": True})["session"]
        names = [s["display_name"] for s in session["config"]["students"]]
        self.assertEqual(names, ["Sato Ken", "Tanaka Hana"])

        session = self.post("/api/students/s001/match", {"roster_id": "n002"})["session"]
        students = session["config"]["students"]
        self.assertEqual(students[0]["roster_id"], "n002")
        self.assertIsNone(students[1]["roster_id"])            # moved to paper 1

        self.post("/api/step", {"step": 4})
        _, config, _ = storage.open_session(session["folder"])
        self.assertEqual(config["resume"]["step"], 4)

    def test_step_three_needs_slicing(self):
        self.create()
        err = self.post("/api/step", {"step": 3}, status=400)
        self.assertEqual(err["error"], "not_sliced")
        err = self.post("/api/slice", status=400)
        self.assertEqual(err["error"], "no_questions")

    def test_rubric_endpoints(self):
        self.create()
        self.post("/api/setup/mode", {"mode": "rubric"})
        err = self.post("/api/setup/rubrics", {"rubrics": [{"name": "A", "bands": [
            {"levels": "1-3"}, {"levels": "3-4"}]}]}, status=400)
        self.assertEqual(err["error"], "rubric_levels_overlap")
        template = self.fetch("/api/setup/rubrics/template?lang=en")
        res = self.client.post("/api/setup/rubrics/import", data={
            "file": (io.BytesIO(template.data), "t.xlsx")}, content_type="multipart/form-data")
        rubrics = res.get_json()["rubrics"]
        self.assertEqual(len(rubrics[0]["bands"]), 5)
        session = self.post("/api/setup/rubrics", {"rubrics": rubrics})["session"]
        self.assertEqual(session["config"]["rubrics"][0]["id"], "r1")

    def test_close_and_reopen(self):
        session = self.create()
        self.post("/api/session/close")
        self.assertIsNone(self.client.get("/api/state").get_json()["session"])
        data = self.post("/api/session/open", {"folder": session["folder"]})
        self.assertEqual(data["session"]["config"]["exam_name"], "Y8 Test")
        err = self.post("/api/session/open", {"folder": self.scans}, status=400)
        self.assertEqual(err["error"], "not_a_session_folder")


class GradingTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.folder = self.create()["folder"]
        self.set_up_questions()

    def grade(self, json, status=200):
        return self.post("/api/grade", json, status)

    def test_grades_comments_and_progress(self):
        session = self.grade({"student_id": "s001", "question_id": "q1", "value": 4})["session"]
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["value"], 4)
        self.grade({"student_id": "s001", "question_id": "q1", "comment": "Good start"})
        session = self.grade({"student_id": "s002", "question_id": "q1", "value": "not_answered"})["session"]
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"],
                         {"value": 4, "comment": "Good start"})     # comment kept the value
        self.assertEqual(session["progress"], {"graded": 2, "total": 4, "students_done": 0,
                                               "students_total": 2})
        err = self.grade({"student_id": "s001", "question_id": "q1", "value": 6}, status=400)
        self.assertEqual(err["error"], "mark_out_of_range")
        self.grade({"student_id": "s001", "question_id": "q2", "value": 3})
        self.assertEqual(self.client.get("/api/state").get_json()["recent"][0]["graded"], 1)

        # Everything is on disk: close, reopen, still there.
        self.post("/api/session/close")
        reopened = self.post("/api/session/open", {"folder": self.folder})["session"]
        self.assertEqual(reopened["grades"]["grades"]["s002"]["q1"]["value"], "not_answered")
        session = self.grade({"student_id": "s001", "question_id": "q1", "value": None})["session"]
        self.assertIsNone(session["grades"]["grades"]["s001"]["q1"]["value"])

    def test_quick_comments(self):
        session = self.client.get("/api/state").get_json()["session"]
        self.assertEqual(len(session["config"]["keywords"]), 5)          # defaults, in English
        self.post("/api/setup/keywords", {"keywords": [{"label": "neat", "type": "strength"}]})
        self.grade({"student_id": "s001", "question_id": "q1", "comment": "Typed."})
        session = self.grade({"student_id": "s001", "question_id": "q1", "keywords": ["neat"]})["session"]
        self.assertEqual(session["config"]["keywords"], [{"label": "neat", "type": "strength"}])
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["comment"], "Strengths: neat.\nTyped.")
        err = self.grade({"student_id": "s001", "question_id": "q1", "keywords": ["gone"]}, status=400)
        self.assertEqual(err["error"], "unknown_keyword")

    def test_adjust_one_box_after_grading(self):
        self.grade({"student_id": "s001", "question_id": "q2", "value": 2})
        session = self.post("/api/setup/questions", {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2:C3"], "max": 5},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"], "max": 3}]})["session"]
        self.assertFalse(session["config"]["sliced"])
        self.post("/api/step", {"step": 4}, status=400)                  # not until it is sliced
        job = self.wait(self.post("/api/slice-question", {"question_id": "q2"})["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertTrue(job["session"]["config"]["sliced"])
        self.assertEqual(job["session"]["grades"]["grades"]["s001"]["q2"]["value"], 2)
        self.post("/api/step", {"step": 4})

    def test_position_is_remembered(self):
        self.post("/api/position", {"question_id": "q2", "student_id": "s002"})
        self.post("/api/session/close")
        config = self.post("/api/session/open", {"folder": self.folder})["session"]["config"]
        self.assertEqual((config["resume"]["question_id"], config["resume"]["student_id"]), ("q2", "s002"))
        self.post("/api/position", {"question_id": "nope", "student_id": "s002"}, status=400)

    def test_starting_choice_can_change_but_a_graded_question_cannot(self):
        self.grade({"student_id": "s001", "question_id": "q1", "value": 2})
        session = self.post("/api/setup/mode", {"mode": "rubric"})["session"]
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["value"], 2)
        self.assertEqual(session["summary"]["students"][0]["marks"]["total"], 2)
        err = self.post("/api/setup/questions", {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!A1:B2"], "max": None},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"], "max": 3}]}, status=400)
        self.assertEqual(err["error"], "question_marks_locked")

    def question_payload(self, q1=None, q2=None, **extra):
        return dict({"name_box": ["page1!B2"], "questions": [
            dict({"id": "q1", "label": "Q1", "boxes": ["page1!B2:C3"], "max": 5}, **(q1 or {})),
            dict({"id": "q2", "label": "Q2", "boxes": ["page2!A1"], "max": 3}, **(q2 or {}))]}, **extra)

    def test_screens_are_told_which_questions_are_locked(self):
        session = self.grade({"student_id": "s001", "question_id": "q1", "value": 2})["session"]
        self.assertEqual(session["locked_questions"], ["q1"])
        session = self.grade({"student_id": "s001", "question_id": "q1", "value": None})["session"]
        self.assertEqual(session["locked_questions"], [])
        session = self.grade({"student_id": "s001", "question_id": "q2", "comment": "neat"})["session"]
        self.assertEqual(session["locked_questions"], [])

    def test_a_locked_marks_question_can_correct_its_number(self):
        self.grade({"student_id": "s001", "question_id": "q1", "value": 2})
        session = self.post("/api/setup/questions", self.question_payload({"max": 6}))["session"]
        self.assertEqual(session["config"]["questions"][0]["max"], 6)
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["value"], 2)

    def test_marks_and_criteria_filled_in_after_slicing_need_no_slicing(self):
        rubric = {"name": "A", "bands": [{"levels": "0"}, {"levels": "1-2"}]}
        rid = self.post("/api/setup/rubrics", {"rubrics": [rubric]})["session"]["config"]["rubrics"][0]["id"]
        session = self.post("/api/setup/questions", self.question_payload(
            {"rubric_ids": [rid]}, {"max": None, "rubric_ids": [rid]}))["session"]
        self.assertTrue(session["config"]["sliced"])
        self.assertTrue(session["config"]["crops_of"])
        session = self.post("/api/setup/questions", self.question_payload({"max": 7}, {"max": 4}))["session"]
        self.assertTrue(session["config"]["sliced"])

    def test_sections_from_the_question_list_are_saved(self):
        session = self.post("/api/setup/questions", self.question_payload(
            {"section_id": "sec1"}, {"section_id": "sec2"},
            sections=[{"id": "sec1", "name": "Knowledge"}, {"id": "sec2", "name": ""}]))["session"]
        config = session["config"]
        self.assertTrue(config["sliced"])                          # sections don't move a box
        self.assertEqual([s["id"] for s in config["sections"]], ["sec1", "sec2"])
        self.assertEqual(config["sections"][0]["name"], "Knowledge")
        self.assertEqual([q["section_id"] for q in config["questions"]], ["sec1", "sec2"])
        self.post("/api/session/close")
        config = self.post("/api/session/open", {"folder": self.folder})["session"]["config"]
        self.assertEqual([q["section_id"] for q in config["questions"]], ["sec1", "sec2"])
        session = self.post("/api/setup/questions", self.question_payload(sections=[]))["session"]
        self.assertEqual(session["config"]["sections"], [])
        self.assertNotIn("section_id", session["config"]["questions"][0])

    def test_a_divider_cannot_split_a_choice_group(self):
        groups = [{"id": "g1", "questions": ["q1", "q2"], "answer": 1}]
        err = self.post("/api/setup/questions", self.question_payload(
            {"section_id": "sec1"}, {"section_id": "sec2"}, choice_groups=groups,
            sections=[{"id": "sec1", "name": ""}, {"id": "sec2", "name": ""}]), status=400)
        self.assertEqual(err["error"], "choice_group_across_sections")

    def mixed_paper(self):
        rubric = {"name": "A", "bands": [{"levels": "0"}, {"levels": "1-2"}, {"levels": "3-4"}]}
        rid = self.post("/api/setup/rubrics", {"rubrics": [rubric]})["session"]["config"]["rubrics"][0]["id"]
        self.post("/api/setup/questions", self.question_payload(
            {"rubric_ids": [rid]}, {"max": None, "rubric_ids": [rid]}))
        return rid

    def test_a_mixed_paper_grades_each_question_its_own_way(self):
        rid = self.mixed_paper()
        self.post("/api/step", {"step": 4})
        self.grade({"student_id": "s001", "question_id": "q1", "value": 4})
        session = self.grade({"student_id": "s001", "question_id": "q2", "value": 3, "rubric_id": rid})["session"]
        student = session["summary"]["students"][0]
        self.assertEqual(session["grades"]["grades"]["s001"]["q1"]["value"], 4)
        self.assertEqual(student["levels"]["q2"][rid], 3)
        self.assertNotIn("q1", student["levels"])
        self.assertEqual((student["marks"]["total"], student["marks"]["percent"]), (4, 80.0))    # the level isn't added
        self.assertEqual(student["rubrics"][rid]["marks"]["total"], 4)
        self.assertEqual(student["rubrics"][rid]["grades"], [{"question": "q2", "level": 3}])
        self.assertEqual(session["progress"]["graded"], 2)
        # A level is refused on the marks question, and a mark too big for the rubric on the other.
        err = self.grade({"student_id": "s002", "question_id": "q1", "value": 3, "rubric_id": rid}, status=400)
        self.assertEqual(err["error"], "unknown_rubric")
        err = self.grade({"student_id": "s002", "question_id": "q2", "value": 5, "rubric_id": rid}, status=400)
        self.assertEqual(err["error"], "level_not_in_rubric")

    def test_not_answered_on_a_mixed_paper(self):
        rid = self.mixed_paper()
        self.grade({"student_id": "s001", "question_id": "q1", "value": "not_answered"})
        session = self.grade({"student_id": "s001", "question_id": "q2", "value": "not_answered"})["session"]
        student = session["summary"]["students"][0]
        self.assertEqual(student["marks"]["total"], 0)
        self.assertEqual(student["levels"]["q2"][rid], "not_answered")
        self.assertEqual(session["locked_questions"], ["q1", "q2"])

    def test_grading_waits_for_a_choice_group_graded_one_way(self):
        rid = self.mixed_paper()
        groups = [{"id": "g1", "questions": ["q1", "q2"], "answer": 1}]
        session = self.post("/api/setup/questions", self.question_payload(
            {"rubric_ids": [rid]}, {"max": None, "rubric_ids": [rid]}, choice_groups=groups))["session"]
        self.assertTrue(session["config"]["sliced"])                # no box moved
        for step in (3, 4, 5):
            err = self.post("/api/step", {"step": step}, status=400)
            self.assertEqual(err["error"], "choice_group_mixed")
        self.post("/api/step", {"step": 2})
        self.post("/api/setup/questions", self.question_payload(
            {"rubric_ids": [rid]}, {"max": 3, "rubric_ids": [rid]}, choice_groups=groups))
        self.post("/api/step", {"step": 4})

    def test_grading_waits_for_marks_or_a_criterion(self):
        self.post("/api/setup/questions", self.question_payload({}, {"max": None}))
        err = self.post("/api/step", {"step": 4}, status=400)
        self.assertEqual(err["error"], "question_needs_marks_or_criterion")
        self.post("/api/setup/questions", self.question_payload())
        self.post("/api/step", {"step": 4})

    def test_a_maximum_cannot_go_below_a_grade_already_given(self):
        self.grade({"student_id": "s001", "question_id": "q1", "value": 4})
        err = self.post("/api/setup/questions", self.question_payload({"max": 3}), status=400)
        self.assertEqual(err["error"], "question_max_below_grade")
        self.assertIn("4", err["message"])
        session = self.post("/api/setup/questions", self.question_payload({"max": 4}))["session"]
        self.assertEqual(session["config"]["questions"][0]["max"], 4)
        session = self.grade({"student_id": "s002", "question_id": "q2", "value": "not_answered"})["session"]
        session = self.post("/api/setup/questions", self.question_payload({"max": 4}, {"max": 1}))["session"]
        self.assertEqual(session["config"]["questions"][1]["max"], 1)    # Not answered isn't a mark

    def test_a_second_rubric_keeps_a_tick_that_was_only_assumed(self):
        rubric = {"name": "A", "bands": [{"levels": "0"}, {"levels": "1-2"}]}
        rid = self.post("/api/setup/rubrics", {"rubrics": [rubric]})["session"]["config"]["rubrics"][0]["id"]
        self.post("/api/setup/questions", self.question_payload({}, {"max": None}))     # q2 has no ticks
        self.grade({"student_id": "s001", "question_id": "q2", "value": 2})
        session = self.post("/api/setup/rubrics", {"rubrics": [dict(rubric, id=rid), dict(rubric, name="B")]})["session"]
        q1, q2 = session["config"]["questions"]
        self.assertEqual((q1["rubric_ids"], q2["rubric_ids"]), ([], [rid]))             # marks stay unticked
        self.assertEqual(session["summary"]["students"][0]["levels"]["q2"][rid], 2)
        self.post("/api/step", {"step": 4})

    def test_rubric_levels_are_checked(self):
        self.post("/api/setup/mode", {"mode": "rubric"})
        self.post("/api/setup/rubrics", {"rubrics": [{"name": "A", "bands": [
            {"levels": "0"}, {"levels": "1-2"}, {"levels": "3-4"}]}]})
        self.post("/api/setup/questions", {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!A1:B2"]},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"]}]})
        self.grade({"student_id": "s001", "question_id": "q1", "value": 3})
        err = self.grade({"student_id": "s001", "question_id": "q1", "value": 5}, status=400)
        self.assertEqual(err["error"], "level_not_in_rubric")

    def test_grade_survives_a_failed_save(self):
        moved = self.folder + " (unplugged)"
        os.rename(self.folder, moved)
        err = self.grade({"student_id": "s002", "question_id": "q2", "value": 1}, status=409)
        self.assertEqual(err["error"], "save_folder_unavailable")
        state = self.client.get("/api/state").get_json()["session"]
        self.assertEqual(state["grades"]["grades"]["s002"]["q2"]["value"], 1)    # kept in memory
        session = self.state.session
        self.assertEqual(session.grades_file.newer_emergency_copy()["grades"]["s002"]["q2"]["value"], 1)
        os.rename(moved, self.folder)
        self.post("/api/save")
        self.post("/api/session/close")
        reopened = self.post("/api/session/open", {"folder": self.folder})["session"]
        self.assertEqual(reopened["grades"]["grades"]["s002"]["q2"]["value"], 1)


class ReviewTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.folder = self.create()["folder"]
        self.set_up_questions()
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "value": 4})
        self.post("/api/grade", {"student_id": "s001", "question_id": "q2", "value": 3})

    def test_summary_and_overrides(self):
        session = self.post("/api/overall", {"student_id": "s001", "comment": "Well done",
                                             "report_total": "8"})["session"]
        marks = session["summary"]["students"][0]["marks"]
        self.assertEqual((marks["total"], marks["report_total"], marks["adjusted"]), (7, 8, True))
        self.assertEqual(session["summary"]["students"][0]["comment"], "Well done")
        session = self.post("/api/overall", {"student_id": "s001", "report_total": ""})["session"]
        self.assertFalse(session["summary"]["students"][0]["marks"]["adjusted"])
        err = self.post("/api/overall", {"student_id": "s001", "report_total": "lots"}, status=400)
        self.assertEqual(err["error"], "report_total_invalid")
        self.post("/api/overall", {"student_id": "nobody", "comment": "x"}, status=400)

    def two_sections(self):
        return self.post("/api/setup/questions", {"name_box": ["page1!B2"], "sections": [
            {"id": "sec1", "name": "Knowledge"}, {"id": "sec2", "name": ""}], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2:C3"], "max": 5, "section_id": "sec1"},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1"], "max": 3, "section_id": "sec2"}]})["session"]

    def test_weighting_and_typed_shares(self):
        session = self.two_sections()
        self.assertEqual([s["weight"] for s in session["config"]["sections"]], [50, 50])
        marks = session["summary"]["students"][0]["marks"]
        self.assertEqual((marks["weighted"], marks["total"]), (False, 7))

        session = self.post("/api/weighting", {"on": True})["session"]
        student = session["summary"]["students"][0]
        self.assertEqual((student["marks"]["weighted"], student["marks"]["percent"]), (True, 90.0))     # 4/5 and 3/3
        self.assertEqual(student["sections"][0]["weighted_marks"], 40.0)

        session = self.post("/api/section-weight", {"section_id": "sec1", "value": "20"})["session"]
        sections = session["config"]["sections"]
        self.assertEqual([(s["weight"], s["weight_typed"]) for s in sections], [(20, True), (80, False)])
        self.assertEqual(session["summary"]["students"][0]["marks"]["percent"], 96.0)
        err = self.post("/api/section-weight", {"section_id": "sec1", "value": "101"}, status=400)
        self.assertEqual(err["error"], "section_weight_invalid")
        err = self.post("/api/section-weight", {"section_id": "nope", "value": "10"}, status=400)
        self.assertEqual(err["error"], "unknown_section")

        session = self.post("/api/section-weight", {"section_id": "sec1", "value": None})["session"]
        self.assertEqual([s["weight"] for s in session["config"]["sections"]], [50, 50])
        session = self.post("/api/weighting", {"on": False})["session"]
        self.assertEqual(session["summary"]["students"][0]["marks"]["percent"], 87.5)

    def test_percentage_on_the_report_with_weighting_on(self):
        self.two_sections()
        self.post("/api/weighting", {"on": True})
        marks = self.post("/api/overall", {"student_id": "s001", "report_percent": "85"})["session"]["summary"]["students"][0]["marks"]
        self.assertEqual((marks["percent"], marks["report_percent"], marks["adjusted"]), (90.0, 85, True))
        marks = self.post("/api/overall", {"student_id": "s001", "report_percent": ""})["session"]["summary"]["students"][0]["marks"]
        self.assertEqual((marks["report_percent"], marks["adjusted"]), (90.0, False))

    def test_class_statistics_for_sections(self):
        self.post("/api/grade", {"student_id": "s002", "question_id": "q1", "value": 2})
        self.post("/api/grade", {"student_id": "s002", "question_id": "q2", "value": 1})
        summary = self.two_sections()["summary"]
        self.assertEqual(summary["sections"]["sec1"], {"average": 3.0, "max": 4, "min": 2, "count": 2})
        self.assertEqual(summary["sections"]["sec2"], {"average": 2.0, "max": 3, "min": 1, "count": 2})
        self.assertNotIn("percent", summary["overall"])
        summary = self.post("/api/weighting", {"on": True})["session"]["summary"]
        self.assertEqual(summary["overall"]["percent"]["max"], 90.0)     # 4/5 and 3/3 at 50% each

    def test_a_section_with_only_rubric_questions_has_no_statistics(self):
        self.post("/api/setup/rubrics", {"rubrics": [{"name": "A", "bands": [{"levels": "0-4"}]}]})
        session = self.post("/api/setup/questions", {"name_box": ["page1!B2"], "sections": [
            {"id": "sec1", "name": ""}, {"id": "sec2", "name": ""}], "questions": [
            {"id": "q3", "label": "Q3", "boxes": ["page1!B2:C3"], "max": 5, "section_id": "sec1"},
            {"id": "q4", "label": "Q4", "boxes": ["page2!A1"], "rubric_ids": ["r1"], "section_id": "sec2"}]})["session"]
        self.assertEqual([s["weight"] for s in session["config"]["sections"]], [100, None])
        self.assertEqual(list(session["summary"]["sections"]), ["sec1"])

    def test_report_options_are_saved_and_start_from_the_defaults(self):
        session = self.post("/api/step", {"step": 5})["session"]
        self.assertEqual(session["config"]["report_options"], {
            "section_results": False, "overall_criteria": False, "rubric_table": True,
            "overall_marks": True, "no_images_for": []})
        self.two_sections()
        session = self.post("/api/report-options", {"section_results": True, "no_images_for": ["sec2", "gone"]})["session"]
        options = session["config"]["report_options"]
        self.assertEqual((options["section_results"], options["no_images_for"]), (True, ["sec2"]))
        self.assertTrue(options["overall_marks"])
        self.post("/api/session/close")
        options = self.post("/api/session/open", {"folder": self.folder})["session"]["config"]["report_options"]
        self.assertEqual((options["section_results"], options["no_images_for"]), (True, ["sec2"]))

    def test_one_report_can_be_seen_first(self):
        res = self.fetch("/api/report-preview/s001?lang=en")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.mimetype, "application/pdf")
        self.assertTrue(res.get_data().startswith(b"%PDF"))
        self.assertNotIn("attachment", res.headers.get("Content-Disposition", ""))     # opens in the browser
        self.assertFalse(os.path.exists(os.path.join(self.folder, "reports")))
        self.assertEqual(self.fetch("/api/report-preview/nobody").status_code, 400)
        self.assertEqual(self.fetch("/api/report-preview/s001?lang=xx").status_code, 400)

    def test_teacher_picks_a_choice(self):
        self.post("/api/setup/questions", {"name_box": ["page1!B2"], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!B2:C3"], "max": 5},
            {"id": "q2", "label": "Q2", "boxes": ["page2!A1"], "max": 3}],
            "choice_groups": [{"id": "g1", "questions": ["q1", "q2"], "answer": 1, "pick": "teacher"}]})
        session = self.client.get("/api/state").get_json()["session"]
        self.assertEqual(session["config"]["choice_groups"][0]["pick"], "teacher")
        student = session["summary"]["students"][0]
        self.assertEqual((student["pending"], student["complete"]), (["g1"], False))
        session = self.post("/api/choice", {"student_id": "s001", "group_id": "g1",
                                            "questions": ["q2"]})["session"]
        student = session["summary"]["students"][0]
        self.assertEqual((student["pending"], student["marks"]["total"]), ([], 3))
        err = self.post("/api/choice", {"student_id": "s001", "group_id": "g1",
                                        "questions": ["q1", "q2"]}, status=400)
        self.assertEqual(err["error"], "choice_pick_invalid")

    def test_export_makes_pdfs_and_gradebook(self):
        job = self.wait(self.post("/api/export", {"language": "ja", "what": "all"})["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["result"]["pdfs"], 2)
        folder = job["result"]["folder"]
        self.assertTrue(os.path.isfile(os.path.join(folder, job["result"]["excel"])))
        pdfs = sorted(os.listdir(os.path.join(folder, "student_pdfs")))
        self.assertEqual(pdfs, ["Sato Ken_Y8 Test.pdf", "Tanaka Hana_Y8 Test.pdf"])
        job = self.wait(self.post("/api/export", {"what": "excel"})["job"])
        self.assertEqual(job["result"]["pdfs"], 0)
        self.post("/api/export", {"language": "fr"}, status=400)

    def test_open_reports_folder(self):
        with mock.patch("app.open_in_file_manager", return_value=True) as opener:
            self.post("/api/open-folder")
            self.assertTrue(opener.call_args.args[0].endswith("reports"))
        with mock.patch("app.open_in_file_manager", return_value=False):
            err = self.post("/api/open-folder", status=400)
        self.assertEqual(err["error"], "cannot_open_folder")


class SafetyTests(AppTestCase):
    def test_save_failure_is_a_save_error_and_work_is_kept(self):
        session = self.create()
        moved = session["folder"] + " (unplugged)"
        os.rename(session["folder"], moved)
        err = self.post("/api/setup/mode", {"mode": "marks"}, status=409)
        self.assertTrue(err["save_error"])
        self.assertEqual(err["error"], "save_folder_unavailable")
        state = self.client.get("/api/state").get_json()["session"]
        self.assertTrue(state["save_failed"])
        self.assertEqual(state["config"]["mode"], "marks")       # kept in memory
        os.rename(moved, session["folder"])
        self.post("/api/save")
        self.assertFalse(self.client.get("/api/state").get_json()["session"]["save_failed"])

    def test_session_open_elsewhere_asks_first(self):
        session = self.create()
        self.post("/api/session/close")
        with mock.patch.object(storage, "INSTANCE_ID", "another-computer"), \
             mock.patch.object(storage, "computer_name", return_value="LAPTOP-123"):
            storage.claim_lock(session["folder"], force=True)
        data = self.post("/api/session/open", {"folder": session["folder"]})
        self.assertFalse(data["ok"])
        self.assertIn("computer", data["locked_by"])
        self.assertTrue(self.post("/api/session/open", {"folder": session["folder"], "force": True})["ok"])

    def test_emergency_copy_is_offered(self):
        session = self.create()
        moved = session["folder"] + " (away)"
        os.rename(session["folder"], moved)
        self.post("/api/setup/mode", {"mode": "rubric"}, status=409)
        os.rename(moved, session["folder"])
        self.state.close_session()
        data = self.post("/api/session/open", {"folder": session["folder"]})
        self.assertIn("config", data["emergency"])
        restored = self.post("/api/session/restore-emergency")["session"]
        self.assertEqual(restored["config"]["mode"], "rubric")

    def test_old_emergency_copy_is_upgraded_when_restored(self):
        session = self.create()
        self.post("/api/setup/mode", {"mode": "rubric"})
        self.post("/api/setup/rubrics", {"rubrics": [{"name": "A", "bands": [{"levels": "0-8"}]}]})
        file = self.state.session.config_file
        old = dict(self.state.config, version=1, generation=file.generation + 1,
                   questions=[{"id": "q1", "label": "Q1", "boxes": [], "max": 5, "rubric_ids": ["r1"]}])
        storage.atomic_write(file.emergency_path(), json.dumps(old).encode("utf-8"))
        self.state.close_session()
        data = self.post("/api/session/open", {"folder": session["folder"]})
        self.assertIn("config", data["emergency"])
        restored = self.post("/api/session/restore-emergency")["session"]["config"]
        self.assertIsNone(restored["questions"][0]["max"])
        self.assertEqual(restored["version"], model.VERSION)

    def test_files_cannot_be_fetched_from_outside(self):
        self.create()
        self.assertEqual(self.fetch("/api/crop/..%2F..%2Fsecret/s001").status_code, 404)
        self.assertIn(self.fetch("/api/crop/q1/..%2Fx").status_code, (400, 404))
        self.assertEqual(self.fetch("/api/thumb/nobody").status_code, 400)

    def test_no_session_is_explained(self):
        err = self.post("/api/setup/mode", {"mode": "marks"}, status=400)
        self.assertEqual(err["error"], "no_open_session")



class SlideDeckTests(AppTestCase):
    """From choosing a 12-screen deck to a report."""

    SCREENS = 12

    def setUp(self):
        super().setUp()
        self.decks = os.path.join(self.root, "decks")
        os.makedirs(self.decks)
        layout = Layout("Slide 16:9", landscape=True)
        for name in ("Tanaka Hana.pdf", "Sato Ken.pdf"):
            make_pdf(os.path.join(self.decks, name), pages=self.SCREENS, size=(13.333 * 72, 7.5 * 72),
                     fills={p: [(layout, 25, 14, RED)] for p in range(1, self.SCREENS + 1)})

    def test_a_deck_goes_from_choosing_the_file_to_a_report(self):
        info = self.post("/api/inspect", {"kind": "folder", "path": self.decks})
        self.assertEqual((info["paper"], info["landscape"]), ("Slide 16:9", True))
        data = self.post("/api/session/create", {
            "exam_name": "Final report", "paper": info["paper"], "landscape": info["landscape"],
            "save_folder": os.path.join(self.root, "sessions"),
            "source": {"type": "folder", "path": self.decks}})
        job = self.wait(data["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual(job["session"]["grid"], {"cols": 51, "rows": 29})
        self.assertEqual(job["session"]["config"]["version"], model.VERSION)

        self.post("/api/setup/mode", {"mode": "marks"})
        questions = [{"id": f"q{n}", "label": f"Screen {n:02d}", "boxes": [f"page{n}!A1:AY29"], "max": 8}
                     for n in range(1, self.SCREENS + 1)]
        self.post("/api/setup/questions", {"name_box": ["page1!A1:J3"], "questions": questions})
        job = self.wait(self.post("/api/slice")["job"])
        self.assertEqual((job["status"], job["result"]["errors"]), ("done", []))
        self.assertEqual(job["result"]["crops"], (self.SCREENS + 1) * 2)

        res = self.client.get("/api/crop/q12/s001")
        self.assertEqual(res.mimetype, "image/jpeg")
        with Image.open(io.BytesIO(res.data)) as im:
            self.assertEqual(im.size, (2667, 1500))
        res.close()
        res = self.client.get(f"/api/crop/{model.NAME_BOX_ID}/s001")
        self.assertEqual(res.mimetype, "image/png")
        res.close()

        for question in questions:
            self.post("/api/grade", {"student_id": "s001", "question_id": question["id"], "value": 5})
        self.post("/api/overall", {"student_id": "s001", "comment": "A strong portfolio."})
        job = self.wait(self.post("/api/export", {"language": "en"})["job"])
        self.assertEqual(job["status"], "done", job.get("error"))
        self.assertEqual((job["result"]["pdfs"], job["result"]["errors"]), (2, []))
        folder = os.path.join(job["result"]["folder"], "student_pdfs")
        pictures = []
        for name in os.listdir(folder):
            with fitz.open(os.path.join(folder, name)) as doc:
                pictures.append(sum(len(p.get_images()) for p in doc))
        self.assertEqual(max(pictures), self.SCREENS)        # a report shows every screen

    def test_a_session_on_paper_keeps_its_layout_and_png_crops(self):
        self.create()
        self.set_up_questions()
        res = self.client.get("/api/crop/q1/s001")
        self.assertEqual(res.mimetype, "image/png")
        res.close()
        config = self.client.get("/api/state").get_json()["session"]["config"]
        self.assertEqual(config["layout"], {"paper": "A4", "density": "5mm", "landscape": False})


class CommentLimitRouteTests(AppTestCase):
    def setUp(self):
        super().setUp()
        self.session = self.create()
        self.set_up_questions()

    def test_limits_are_told_to_the_page(self):
        session = self.client.get("/api/state").get_json()["session"]
        self.assertEqual(session["comment_limits"], {"question": 300, "overall": 600})

    def test_a_long_comment_is_refused_and_nothing_is_lost(self):
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "comment": "x" * 300})
        err = self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "comment": "x" * 301}, status=400)
        self.assertEqual(err["error"], "comment_too_long")
        self.assertIn("300", err["message"])
        self.post("/api/overall", {"student_id": "s001", "comment": "y" * 600})
        err = self.post("/api/overall", {"student_id": "s001", "comment": "y" * 601}, status=400)
        self.assertEqual(err["error"], "comment_too_long")
        grades = self.client.get("/api/state").get_json()["session"]["grades"]
        self.assertEqual(grades["grades"]["s001"]["q1"]["comment"], "x" * 300)
        self.assertEqual(grades["overall"]["s001"]["comment"], "y" * 600)

    def test_a_session_with_a_longer_comment_opens_and_saves_with_it_unchanged(self):
        folder = self.session["folder"]
        path = os.path.join(folder, "grades.json")
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "value": 3})
        self.post("/api/session/close")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["grades"]["s001"]["q1"]["comment"] = "長" * 500
        data["overall"] = {"s001": {"comment": "y" * 900}}
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        self.post("/api/session/open", {"folder": folder})
        self.post("/api/grade", {"student_id": "s001", "question_id": "q2", "value": 2})
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "value": 4})
        self.post("/api/grade", {"student_id": "s001", "question_id": "q1", "comment": "長" * 500})
        with open(path, encoding="utf-8") as fh:
            saved = json.load(fh)
        self.assertEqual(saved["grades"]["s001"]["q1"]["comment"], "長" * 500)
        self.assertEqual(saved["overall"]["s001"]["comment"], "y" * 900)
        self.assertEqual(saved["version"], model.VERSION)

if __name__ == "__main__":
    unittest.main()
