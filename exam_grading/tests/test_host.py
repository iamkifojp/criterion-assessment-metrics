"""Opened from another app (CAM): the handoff file, its class list, Send to CAM.

Run:  python -m unittest tests.test_host
"""

import json
import os
import tempfile
import time
import unittest
from unittest import mock

from app import create_app
from appstate import AppState
from engine import host
from engine.errors import UserError
from engine.slicer import Layout
from tests.helpers import make_pdf

RED = (255, 0, 0)


def handoff(folder, **extra):
    data = {"format": "cam2-host", "version": 1, "host": "CAM", "exam_name": "Y8  Science Midterm",
            "class_name": "8A", "session_folder": folder,
            "roster": [{"external_id": "8A-01", "name": "Tanaka Hana"},
                       {"external_id": "8A-02", "name": "Sato  Ken"},
                       {"external_id": "8A-02", "name": "duplicate id"},
                       {"external_id": "", "name": "no id"}]}
    data.update(extra)
    return data


class HandoffTests(unittest.TestCase):
    def test_normalize(self):
        folder = os.path.abspath("exams/Y8")
        data = host.normalize(handoff(folder))
        self.assertEqual(data["exam_name"], "Y8 Science Midterm")
        self.assertEqual(data["roster"], [{"external_id": "8A-01", "name": "Tanaka Hana"},
                                          {"external_id": "8A-02", "name": "Sato Ken"}])
        for bad in (handoff(folder, format="x"), handoff("relative/folder"), handoff(folder, exam_name=" "),
                    handoff(folder, version=2), "nonsense"):
            with self.assertRaises(UserError):
                host.normalize(bad)

    def test_roster_keeps_ids_by_external_id(self):
        data = host.normalize(handoff(os.path.abspath("x")))
        config = {"students": [{"id": "s001", "source": "Tanaka Hana.pdf", "roster_id": None},
                               {"id": "s002", "source": "scan.pdf", "roster_id": None}], "roster": []}
        host.apply_roster(config, data)
        self.assertEqual([(r["id"], r["external_id"]) for r in config["roster"]],
                         [("n001", "8A-01"), ("n002", "8A-02")])
        self.assertEqual(config["students"][0]["roster_id"], "n001")         # matched by file name
        config["students"][1]["roster_id"] = "n002"
        data["roster"] = [{"external_id": "8A-03", "name": "Ito Mei"},
                          {"external_id": "8A-02", "name": "Satou Ken"}]      # a name corrected in CAM
        host.apply_roster(config, data)
        self.assertEqual([(r["id"], r["name"]) for r in config["roster"]], [("n003", "Ito Mei"), ("n002", "Satou Ken")])
        self.assertEqual([s["roster_id"] for s in config["students"]], [None, "n002"])
        self.assertEqual(config["host"], {"name": "CAM", "class_name": "8A"})


class HostAppTests(unittest.TestCase):
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
        for name in ("Tanaka Hana.pdf", "scan_002.pdf"):
            make_pdf(os.path.join(self.scans, name), pages=1, fills={1: [(Layout("A4"), 1, 1, RED)]})
        self.folder = os.path.join(self.root, "class", "exams", "Y8 Science Midterm")

    def tearDown(self):
        self.state.close_session()
        self.tmp.cleanup()

    def post(self, url, json_body=None, status=200):
        res = self.client.post(url, json=json_body if json_body is not None else {})
        self.assertEqual(res.status_code, status, res.get_json())
        return res.get_json()

    def create(self, folder=None, exam="Y8 Science Midterm"):
        data = self.post("/api/session/create", {
            "exam_name": exam, "paper": "A4", "landscape": False,
            "save_folder": folder or self.folder, "source": {"type": "folder", "path": self.scans}})
        for _ in range(200):
            job = self.client.get(f"/api/job/{data['job']}").get_json()
            if job["status"] != "running":
                self.assertEqual(job["status"], "done", job.get("error"))
                return job
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_handoff_create_send_and_reopen(self):
        self.post("/api/host/handoff", handoff(self.folder))
        state = self.client.get("/api/state").get_json()
        self.assertEqual((state["host"]["exam_name"], state["host"]["session_exists"]),
                         ("Y8 Science Midterm", False))
        session = self.create()["session"]
        self.assertEqual(os.path.normcase(session["folder"]), os.path.normcase(self.folder))   # not a subfolder
        self.assertEqual(len(session["config"]["roster"]), 2)
        matched = {s["source"]: s["roster_id"] for s in session["config"]["students"]}
        self.assertEqual(matched, {"Tanaka Hana.pdf": "n001", "scan_002.pdf": None})   # by file name
        session = self.post("/api/host/ready", {"ready": True})["session"]
        self.assertTrue(session["config"]["host_ready_at"])
        with open(os.path.join(self.folder, "cam2_session.json"), encoding="utf-8") as fh:
            self.assertTrue(json.load(fh)["host_ready_at"])                    # what CAM reads
        self.post("/api/session/close")
        self.assertTrue(self.client.get("/api/state").get_json()["host"]["session_exists"])
        data = handoff(self.folder)
        data["roster"].append({"external_id": "8A-03", "name": "Ito Mei"})
        self.post("/api/host/handoff", data)
        session = self.post("/api/session/open", {"folder": self.folder})["session"]
        self.assertEqual(len(session["config"]["roster"]), 3)                  # CAM's list refreshed

    def test_host_folder_must_be_empty(self):
        os.makedirs(self.folder)
        with open(os.path.join(self.folder, "notes.txt"), "w") as fh:
            fh.write("x")
        self.post("/api/host/handoff", handoff(self.folder))
        res = self.client.post("/api/session/create", json={
            "exam_name": "Y8 Science Midterm", "paper": "A4", "landscape": False,
            "save_folder": self.folder, "source": {"type": "folder", "path": self.scans}})
        self.assertEqual(res.get_json()["error"], "host_folder_not_empty")

    def test_new_handoff_closes_another_session(self):
        self.create(os.path.join(self.root, "other"), "Other")
        self.post("/api/host/handoff", handoff(self.folder))
        self.assertIsNone(self.client.get("/api/state").get_json()["session"])
        self.assertEqual(self.post("/api/host/handoff", {"format": "x"}, status=400)["error"],
                         "host_handoff_invalid")

    def test_standalone_sessions_are_untouched(self):
        self.create(os.path.join(self.root, "mine"), "Mine")
        config = self.client.get("/api/state").get_json()["session"]["config"]
        self.assertNotIn("host", config)
        self.assertEqual(config["roster"], [])


if __name__ == "__main__":
    unittest.main()
