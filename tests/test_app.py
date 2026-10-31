"""The web server, driven through Flask's test client: start screen, Step 1
(create + import job), Step 2 (set-up + slice job), Step 3 (class list, matching),
errors, save failures and file-serving safety.

Run:  python -m unittest tests.test_app
"""

import io
import os
import tempfile
import time
import unittest
from unittest import mock

from openpyxl import Workbook

from app import create_app
from appstate import AppState
from engine import storage
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

    def test_mode_is_fixed_once_grading_starts(self):
        self.grade({"student_id": "s001", "question_id": "q1", "value": 2})
        err = self.post("/api/setup/mode", {"mode": "rubric"}, status=400)
        self.assertEqual(err["error"], "mode_locked")
        self.post("/api/setup/mode", {"mode": "marks"})              # same mode is fine

    def test_rubric_levels_are_checked(self):
        self.post("/api/setup/mode", {"mode": "rubric"})
        self.post("/api/setup/rubrics", {"rubrics": [{"name": "A", "bands": [
            {"levels": "0"}, {"levels": "1-2"}, {"levels": "3-4"}]}]})
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

    def test_files_cannot_be_fetched_from_outside(self):
        self.create()
        self.assertEqual(self.fetch("/api/crop/..%2F..%2Fsecret/s001").status_code, 404)
        self.assertIn(self.fetch("/api/crop/q1/..%2Fx").status_code, (400, 404))
        self.assertEqual(self.fetch("/api/thumb/nobody").status_code, 400)

    def test_no_session_is_explained(self):
        err = self.post("/api/setup/mode", {"mode": "marks"}, status=400)
        self.assertEqual(err["error"], "no_open_session")


if __name__ == "__main__":
    unittest.main()
