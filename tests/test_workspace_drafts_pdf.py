"""Exercise the real Flask routes in an isolated copy with fictional work.

Copy only source files BEFORE import: settings, credentials, cache and every
runtime path resolve into TemporaryDirectory, never the user's data folder.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from engine.ingestion import IngestionPipeline
from cam_grading_workspace.pdf_view import visible_pages, prune_pdf_cache

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceUiTests(unittest.TestCase):
    def test_draft_badges_and_grade_columns(self):
        node = shutil.which(os.environ.get("CAM_TEST_NODE", "node"))
        if not node:
            self.skipTest("Node.js is required for workspace UI checks")
        source = (ROOT / "cam_grading_workspace/app.py").read_text()
        # Run the actual UI functions without starting an app or accessing data.
        functions = []
        for name in ("gradeSum", "gradeChipText", "renderTable", "makeRow"):
            start = source.index(f"function {name}(")
            end = re.search(r"^function ", source[start + 1:], re.MULTILINE)
            functions.append(source[start:start + 1 + end.start()])
        script = r"""
const assert = require('node:assert/strict');
class Element {
  constructor(tag) {
    this.tag = tag; this.children = []; this.dataset = {};
    this.classList = {add() {}}; this.innerHTML = '';
  }
  appendChild(child) { this.children.push(child); }
  addEventListener() {}
}
const document = {createElement: tag => new Element(tag)};
let IS_DRAFT = true, SELECTED_CRITERIA = ['A', 'B'];
const tableWrap = new Element('div');
let STUDENTS = [];
const selectedKey = null, DEADLINE = '', KEYWORDS = [];
const GRADES = ['', '0', '1', '8'];
const groupForKey = () => null;
const shortIdOf = st => st.key;
const escapeHtml = text => text;
const st = {key: 'fictional', keywords: [], comment: '', grades: {A: '8'}};
STUDENTS = [st];
""" + "\n".join(functions) + r"""
const descendants = el => [el, ...el.children.flatMap(descendants)];
function checkColumns(expected) {
  tableWrap.children = [];
  renderTable();
  const table = tableWrap.children[0];
  const selectors = descendants(table).filter(el => el.tag === 'select');
  assert.deepEqual(selectors.map(el => el.dataset.crit), expected);
  assert.equal(table.innerHTML.includes('Crit A'), expected.includes('A'));
  assert.equal(table.innerHTML.includes('Crit B'), expected.includes('B'));
}
assert.equal(gradeChipText(st), ''); // Old marks never imply draft review.
checkColumns([]);
st.comment = 'Explain your artist choice.';
assert.equal(gradeChipText(st), 'SEEN');
st.comment = ''; st.keywords = ['Context'];
assert.equal(gradeChipText(st), 'SEEN');
st.keywords = [];
assert.equal(gradeChipText(st), '');
SELECTED_CRITERIA = [];
checkColumns([]); // Draft feedback works without a grading criterion.
IS_DRAFT = false; SELECTED_CRITERIA = ['A', 'B'];
st.grades = {A: '0', B: '8'};
checkColumns(['A', 'B']);
assert.equal(gradeChipText(st), 'Σ8');
SELECTED_CRITERIA = ['A'];
assert.equal(gradeChipText(st), '0');
"""
        result = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class PdfSelectionTests(unittest.TestCase):
    def test_ranges_original_numbering_and_invalid_input(self):
        self.assertEqual(visible_pages(12, "1-9, 11"), [10, 12])
        self.assertEqual(visible_pages(3, "1-999999999999"), [])
        for text in ("0", "9-1", "1,,2", "hello", "-1"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                visible_pages(12, text)

    def test_cache_eviction_keeps_current_file_and_non_pdf_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("old.pdf", "current.pdf", "old.pdf.bak-test"):
                (root / name).write_bytes(b"x" * 100)
            prune_pdf_cache(root, root / "current.pdf", budget=150)
            self.assertFalse((root / "old.pdf").exists())
            self.assertTrue((root / "current.pdf").exists())
            self.assertTrue((root / "old.pdf.bak-test").exists())


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        try:
            import flask
            import fitz
            import google_auth_oauthlib
            import googleapiclient
        except ImportError as exc:
            self.skipTest(f"Workspace requirements not installed: {exc}")
        self.tmp = tempfile.TemporaryDirectory(prefix="cam-draft-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source = self.root / "cam_grading_workspace"
        source.mkdir()
        for path in (ROOT / "cam_grading_workspace").glob("*.py"):
            shutil.copy2(path, source / path.name)
        shutil.copytree(ROOT / "cam_grading_workspace/static", source / "static")
        self.data = self.root / "data"
        self.data.mkdir()
        (source / "gcg_settings.json").write_text(json.dumps({"cloud_dir": str(self.data)}))
        self.env = patch.dict(os.environ, {"CAM_DB_PATH": str(self.data)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.path_patch = patch.object(sys, "path", [str(source)] + sys.path)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        # Avoid reusing a companion imported from a previous temporary copy.
        self.module_patch = patch.dict(sys.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        for name in ("exam_engine", "submission_identity", "pdf_view"):
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location("sandbox_workspace", source / "app.py")
        self.ws = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = self.ws
        spec.loader.exec_module(self.ws)
        self.ws.app.config.update(TESTING=True)
        self.assertEqual(Path(self.ws.BASE_DIR), source)
        self.assertEqual(Path(self.ws.SETTINGS["cloud_dir"]), self.data)
        self.assertTrue(Path(self.ws.PREFS_FILE).is_relative_to(self.root))
        self.client = self.ws.app.test_client()
        self.folder = self.root / "Investigation"
        self.folder.mkdir()
        self.pdf = self.folder / "Ada Rivera.pdf"
        with fitz.open() as doc:
            for number in range(1, 13):
                page = doc.new_page()
                page.insert_text((60, 60), f"Fictional investigation page {number}")
            doc.save(self.pdf)
        self.original_hash = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.load()

    def load(self):
        response = self.client.post("/api/load", json={"folder_id": str(self.folder), "class_name": "Art"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.loaded = response.get_json()
        self.student = next(iter(self.ws.STATE["students"].values()))
        self.file_id = self.student["files"][0]["id"]

    def test_pdf_filter_render_and_reload_preserve_source(self):
        route = f"/api/pdf/{self.file_id}/pages"
        response = self.client.post("/api/settings", json={"pdf_omit_pages": "1-9"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get(route).get_json(), {"page_count": 12, "pages": [10, 11, 12]})
        self.assertEqual(self.client.get(route + "/1").status_code, 404)
        png = self.client.get(route + "/10?width=320")
        self.assertEqual(png.status_code, 200)
        self.assertTrue(png.data.startswith(b"\x89PNG"))
        self.assertEqual(self.client.post("/api/settings", json={"pdf_omit_pages": "9-1"}).status_code, 400)
        self.load()
        self.assertEqual(self.loaded["pdf_omit_pages"], "1-9")
        self.client.post("/api/settings", json={"pdf_omit_pages": "1-12"})
        self.assertEqual(self.client.get(route).get_json()["pages"], [])
        self.assertEqual(hashlib.sha256(self.pdf.read_bytes()).hexdigest(), self.original_hash)
        self.assertEqual(self.client.get("/api/pdf/not-in-assignment/pages").status_code, 404)

    def test_draft_save_export_ingest_reload(self):
        self.ws.STATE.update(is_draft=True, criteria=["A"], draft_extra={
            "10002": {"comment": "Feedback without an available file.", "keywords": [], "files": ""}})
        self.student["grades"] = {"A": "8"}  # previous marks must not leak into draft export
        response = self.client.post("/api/save", json={"key": self.student["key"],
            "grades": {"A": "0"}, "comment": "Explain your artist choice.", "keywords": ["Context"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.student["grades"], {"A": "8"})
        self.assertTrue(response.get_json()["student"]["graded"])
        exported = self.client.get("/api/export").get_json()
        path = Path(exported["path"])
        self.assertTrue(path.is_relative_to(self.data))
        self.assertNotIn("Grade (Crit", path.read_text())
        pipeline = IngestionPipeline()
        self.assertEqual(pipeline.ingest_csv(str(path), "Investigation"), [])
        task = pipeline.gradebook.assignments[0]
        self.assertTrue(task.is_draft)
        self.assertEqual(task.criteria, ["A"])
        self.assertEqual(task.draft_feedback[self.student["name"]]["comment"], "Explain your artist choice.")
        self.assertIn("10002", task.draft_feedback)
        self.load()
        self.assertTrue(self.loaded["is_draft"])
        self.assertEqual(self.student["comment"], "Explain your artist choice.")
        self.assertTrue(self.student["graded"])

    def test_draft_review_requires_feedback_and_clears_when_removed(self):
        self.ws.STATE["is_draft"] = True
        self.student.update(grades={"A": "8"}, graded=True)
        self.ws.save_state()
        self.load()
        self.assertFalse(self.student["graded"])
        response = self.client.post("/api/save", json={"key": self.student["key"],
            "keywords": ["Context"], "comment": ""})
        self.assertTrue(response.get_json()["student"]["graded"])
        self.load()
        self.assertTrue(self.student["graded"])
        response = self.client.post("/api/save", json={"key": self.student["key"],
            "keywords": [], "comment": ""})
        self.assertFalse(response.get_json()["student"]["graded"])
        self.load()
        self.assertFalse(self.student["graded"])

    def test_linked_drafts_share_feedback_and_review_status(self):
        shutil.copy2(self.pdf, self.folder / "Sam Chen.pdf")
        self.load()
        self.ws.STATE["is_draft"] = True
        students = list(self.ws.STATE["students"].values())
        first, second = students
        self.client.post("/api/save", json={"key": first["key"],
            "comment": "Name your sources."})
        # Linking from the unseen partner should adopt the reviewed feedback.
        response = self.client.post("/api/group/link", json={"a_key": second["key"], "b_key": first["key"]})
        self.assertEqual(response.status_code, 200, response.get_json())
        for student in students:
            self.assertEqual(student["comment"], "Name your sources.")
            self.assertTrue(student["graded"])
        self.load()
        self.assertTrue(all(student["graded"] for student in self.ws.STATE["students"].values()))

    def test_oauth_discovery_supports_both_local_locations_and_cloud_fallback(self):
        workspace = Path(self.ws.BASE_DIR)
        for folder in (workspace, self.root, self.data):
            for name in ("credentials.json", "client_secret_fixture.json", "client_secretFixture.json"):
                with self.subTest(folder=folder.name, name=name):
                    path = folder / name
                    path.write_text('{}')
                    self.assertEqual(Path(self.ws.find_client_secret()), path)
                    path.unlink()

    def test_word_uses_drive_preview_but_never_treats_it_as_a_pdf(self):
        self.assertEqual(self.client.get('/static/pdf_viewer.js').status_code, 200)
        kind = self.ws.classify("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "Ada.docx")
        self.assertEqual(kind, "word")
        self.assertEqual(self.ws.embed_url_for("drive-file-id", kind),
                         "https://drive.google.com/file/d/drive-file-id/preview")
        word = self.folder / "Ada Rivera.docx"
        word.write_bytes(b"fictional fixture, not opened")
        self.load()
        files = [f for s in self.ws.STATE["students"].values() for f in s["files"]]
        local_word = next(f for f in files if f["kind"] == "word")
        self.assertIsNone(local_word["embed_url"])
        self.assertEqual(self.client.get(f'/api/pdf/{local_word["id"]}/pages').status_code, 404)

    def test_cam_handoff_and_cache_recovery_preserve_draft_feedback(self):
        path = Path(self.ws.cam_published_path(self.ws.STATE["folder_id"]))
        path.write_text(json.dumps({"class": "Art", "assignment": "Investigation",
            "students": {}, "is_draft": True, "criteria": ["A"],
            "matching_roster": [{"key": "10001", "name": "Ada Rivera", "first": "Ada",
                                  "last": "Rivera", "email": "10001@example.test"}],
            "draft_feedback": {"10001": {"comment": "Name your sources.", "keywords": []}}}))
        self.load()
        self.assertEqual(self.student["name"], "10001")
        self.assertEqual(self.student["comment"], "Name your sources.")
        self.assertTrue(self.student["graded"])
        self.assertTrue(self.loaded["is_draft"])
        self.assertEqual(self.loaded["criteria"], ["A"])
        self.assertFalse(path.exists())  # handoff consumed only after saving
        self.client.post("/api/settings", json={"pdf_omit_pages": "1-9"})
        Path(self.ws.state_path(self.ws.STATE["folder_id"])).unlink()
        options = self.ws.load_assignment_options(self.ws.STATE["folder_id"])
        self.assertTrue(options["is_draft"])
        self.assertEqual(options["pdf_omit_pages"], "1-9")


if __name__ == "__main__":
    unittest.main()
