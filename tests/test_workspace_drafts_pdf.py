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


def fitz_open():
    """A new PDF, imported late so a computer without PyMuPDF still skips cleanly."""
    import fitz
    return fitz.open()


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

    def test_generated_line_never_loses_typed_text(self):
        node = shutil.which(os.environ.get("CAM_TEST_NODE", "node"))
        if not node:
            self.skipTest("Node.js is required for workspace UI checks")
        source = (ROOT / "cam_grading_workspace/app.py").read_text(encoding="utf-8")
        functions = []
        for start in ("function isLate(", "function autoComment(", "function generatedLine(",
                      "function applyGeneratedLine(", "function applyDeadlineToLate(",
                      "function deriveLateFlags(",
                      "function remapKeywordLabel(", "async function save("):
            begin = source.index(start)
            functions.append(source[begin:source.index("\n}\n", begin) + 2])
        script = r"""
const assert = require('node:assert/strict');
let DEADLINE = '', IS_DRAFT = false, STUDENTS = [];
const KEYWORDS = [{label: 'Shading', type: 'positive'}, {label: 'Colour', type: 'positive'},
                  {label: 'Detail', type: 'growth'}];
const byKey = {};
const gradeSum = () => 0, renderRoster = () => {}, refreshRow = () => {}, cssEsc = s => s;
const tableWrap = {querySelector: () => null};
let saves = [];
""" + "\n".join(functions).replace("async function save(", "async function realSave(") + r"""
const save = st => saves.push(st.key);
const student = fields => ({key: 'k', keywords: [], comment: '', files: [], ...fields});
const tick = (st, ...labels) => {
  const before = generatedLine(st);
  st.keywords = labels;
  applyGeneratedLine(st, before);
};

// Tick first, then type, then tick again: only the line changes.
let st = student();
tick(st, 'Shading');
assert.equal(st.comment, 'Strengths: Shading.');
st.comment += ' Typed text.';
tick(st, 'Shading', 'Detail');
assert.equal(st.comment, 'Strengths: Shading. Areas to develop: Detail. Typed text.');
tick(st);
assert.equal(st.comment, 'Typed text.');
assert.equal(st.comment_line, '');

// Type first, then tick.
st = student({comment: 'Typed first.', comment_line: ''});
tick(st, 'Colour');
assert.equal(st.comment, 'Strengths: Colour. Typed first.');

// An older saved comment has no remembered line: compare with its ticks.
st = student({comment: 'Strengths: Shading. Older text.', keywords: ['Shading']});
tick(st, 'Colour');
assert.equal(st.comment, 'Strengths: Colour. Older text.');
assert.equal(st.comment_line, 'Strengths: Colour.');
st = student({comment: 'Strengths: Shading.', keywords: ['Shading'], comment_line: null});
tick(st, 'Colour');
assert.equal(st.comment, 'Strengths: Colour.');

// A comment that doesn't start with the line stays whole, with the line in front.
st = student({comment: 'No line here.', keywords: ['Shading']});
tick(st, 'Colour');
assert.equal(st.comment, 'Strengths: Colour. No line here.');
st = student({comment: 'Edited in CAM.', keywords: ['Shading'], comment_line: 'Strengths: Shading.'});
tick(st, 'Colour');
assert.equal(st.comment, 'Strengths: Colour. Edited in CAM.');

// The Late tick replaces the line the same way.
st = student({comment: 'Strengths: Shading. Typed.', keywords: ['Shading'],
              comment_line: 'Strengths: Shading.', late_marked: false});
let before = generatedLine(st);
st.late_marked = true;
applyGeneratedLine(st, before);
assert.equal(st.comment, 'Strengths: Shading. Late submission. Typed.');

// A deadline change touches only students whose Late flag changed.
const late = student({key: 'late', comment: 'Typed.', late_marked: false,
                      files: [{created_time: '2026-10-10T09:00:00'}]});
const same = student({key: 'same', comment: 'Left alone.', keywords: ['Shading'], late_marked: false,
                      files: [{created_time: '2026-10-01T09:00:00'}]});
const waived = student({key: 'waived', comment: 'Waived.', late_marked: false, late_manual: true,
                        files: [{created_time: '2026-10-10T09:00:00'}]});
STUDENTS = [late, same, waived];
DEADLINE = '2026-10-05T12:00';
assert.deepEqual(applyDeadlineToLate().map(s => s.key), ['late']);
assert.equal(late.comment, 'Late submission. Typed.');
assert.equal(same.comment, 'Left alone.');
assert.equal(same.comment_line, undefined);
assert.equal(waived.comment, 'Waived.');
DEADLINE = '2026-10-20T12:00';
assert.deepEqual(applyDeadlineToLate().map(s => s.key), ['late']);
assert.equal(late.comment, 'Typed.');

// A renamed tick updates the comment and the remembered line together.
st = student({comment: 'Strengths: Shading. Typed.', keywords: ['Shading'],
              comment_line: 'Strengths: Shading.'});
STUDENTS = [st];
saves = [];
remapKeywordLabel('Shading', 'Tone');
assert.equal(st.comment_line, 'Strengths: Tone.');
assert.equal(saves.length, 1);
tick(st, 'Tone');
assert.equal(st.comment, 'Strengths: Tone. Typed.');

// A flag worked out from the deadline is returned for saving only if it's late.
DEADLINE = '2026-10-05T12:00';
const unset = student({key: 'u', late_marked: null, files: [{created_time: '2026-10-10T09:00:00'}]});
const onTime = student({key: 'o', files: [{created_time: '2026-10-01T09:00:00'}]});
const decided = student({key: 'd', late_marked: false, files: [{created_time: '2026-10-10T09:00:00'}]});
STUDENTS = [unset, onTime, decided];
assert.deepEqual(deriveLateFlags().map(s => s.key), ['u']);
assert.equal(unset.late_marked, true);
assert.equal(onTime.late_marked, false);
assert.equal(decided.late_marked, false);
assert.equal(unset.comment, '');

// A save's reply can't undo typing that happened while it was on its way.
(async () => {
  const typing = student({comment: 'Before.', comment_line: ''});
  const partner = student({key: 'p', comment: 'Before.', comment_line: ''});
  byKey.k = typing;
  byKey.p = partner;
  STUDENTS = [typing, partner];
  let reply;
  global.fetch = (url, options) => {
    assert.equal(JSON.parse(options.body).comment_line, '');
    return new Promise(resolve => { reply = resolve; });
  };
  const pending = realSave(typing);
  typing.comment = 'Before. And more.';
  reply({json: async () => ({students: [{key: 'k', comment: 'Before.', comment_line: '', graded: true}]})});
  await pending;
  assert.equal(typing.comment, 'Before. And more.');
  assert.equal(typing.graded, true);
  const settled = realSave(typing);
  reply({json: async () => ({students: [{key: 'k', comment: 'From the server.', comment_line: ''}]})});
  assert.equal(await settled, true);
  assert.equal(typing.comment, 'From the server.');

  // Nor what's being typed in a partner's box, while a partner left alone follows.
  const mirrored = {students: [{key: 'k', comment: 'Mirrored.', comment_line: ''},
                               {key: 'p', comment: 'Mirrored.', comment_line: ''}]};
  let pendingSave = realSave(typing);
  partner.comment = 'Typing in the partner.';
  reply({json: async () => mirrored});
  await pendingSave;
  assert.equal(partner.comment, 'Typing in the partner.');
  assert.equal(typing.comment, 'Mirrored.');
  pendingSave = realSave(typing);
  reply({json: async () => mirrored});
  await pendingSave;
  assert.equal(partner.comment, 'Mirrored.');

  // A failed save says so, for linking to stop.
  pendingSave = realSave(typing);
  reply({json: async () => ({error: 'Unknown student key'})});
  assert.equal(await pendingSave, false);
  global.fetch = async () => { throw new Error('offline'); };
  assert.equal(await realSave(typing), false);
})().catch(error => { console.error(error); process.exit(1); });
"""
        result = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


    def test_linking_saves_unsaved_comments_first(self):
        node = shutil.which(os.environ.get("CAM_TEST_NODE", "node"))
        if not node:
            self.skipTest("Node.js is required for workspace UI checks")
        source = (ROOT / "cam_grading_workspace/app.py").read_text(encoding="utf-8")
        begin = source.index("async function linkPartners(")
        function = source[begin:source.index("\n}\n", begin) + 2]
        script = function + r"""
const assert = require('node:assert/strict');
let GROUPS = [];
const byKey = {a: {key: 'a', comment: 'Unsaved.'}, b: {key: 'b', comment: ''}};
const order = [];
const setStatus = () => {}, renderTable = () => {}, renderRoster = () => {}, alert = fail => { throw new Error(fail); };
let saveWorks = true;
const save = async st => { await null; order.push('save ' + st.key + ': ' + st.comment); return saveWorks; };
global.fetch = async url => {
  order.push(url);
  return {ok: true, json: async () => ({groups: [{id: 1}], students: [{key: 'b', comment: 'Unsaved.'}]})};
};
linkPartners('a', 'b').then(() => {
  assert.deepEqual(order, ['save a: Unsaved.', 'save b: ', '/api/group/link']);
  assert.equal(byKey.b.comment, 'Unsaved.');
  assert.equal(GROUPS.length, 1);
  // A failed save stops the link, so the reply can't replace unsaved text.
  order.length = 0;
  saveWorks = false;
  return linkPartners('a', 'b').then(
    () => { throw new Error('should have alerted'); },
    error => {
      assert.ok(!order.includes('/api/group/link'));
      assert.match(error.message, /weren't linked/);
    });
}).catch(error => { console.error(error); process.exit(1); });
"""
        result = subprocess.run([node, "-e", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_keyword_list_stays_whole_on_load(self):
        node = shutil.which(os.environ.get("CAM_TEST_NODE", "node"))
        if not node:
            self.skipTest("Node.js is required for workspace UI checks")
        source = (ROOT / "cam_grading_workspace/app.py").read_text(encoding="utf-8")
        begin = source.index("function restoreKeywords(")
        function = source[begin:source.index("\n}\n", begin) + 2]
        begin = source.index("const DEFAULT_KEYWORDS = [")
        template = source[begin:source.index("];", begin) + 2]
        script = template + "\n" + function + r"""
const assert = require('node:assert/strict');
const labels = list => list.map(k => k.label);
const whole = labels(DEFAULT_KEYWORDS);
assert.ok(whole.length > 3);
// Nothing saved: the whole template, as a copy that can be edited safely.
assert.deepEqual(labels(restoreKeywords({checklist: []})), whole);
assert.deepEqual(labels(restoreKeywords({})), whole);
restoreKeywords({checklist: []})[0].label = 'Changed';
assert.notEqual(DEFAULT_KEYWORDS[0].label, 'Changed');
// Rebuilt from ticks that are all in the template: the template was in use.
const ticked = [{label: whole[1], type: 'positive'}];
assert.deepEqual(labels(restoreKeywords({checklist: ticked, checklist_recovered: true})), whole);
// Rebuilt from ticks outside the template: a custom list, so keep what's there.
const custom = [{label: 'Own words', type: 'positive'}, {label: whole[1], type: 'positive'}];
assert.deepEqual(labels(restoreKeywords({checklist: custom, checklist_recovered: true})),
                 ['Own words', whole[1]]);
// A saved list is the teacher's, even when it's shorter than the template.
assert.deepEqual(labels(restoreKeywords({checklist: ticked, checklist_recovered: false})), [whole[1]]);
// Types come through, and blank labels go.
assert.deepEqual(restoreKeywords({checklist: [{label: ' A ', type: 'growth'}, {label: ' ', type: 'x'}]}),
                 [{label: 'A', type: 'growth'}]);
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
        for name in ("submission_identity", "pdf_view"):
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

    def save_comment(self, key, comment, line):
        response = self.client.post("/api/save", json={
            "key": key, "comment": comment, "comment_line": line, "keywords": ["Context"]})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_comment_line_survives_save_and_reload(self):
        key = self.student["key"]
        saved = self.save_comment(key, "Strengths: Context. Typed.", "Strengths: Context.")
        self.assertEqual(saved["student"]["comment_line"], "Strengths: Context.")
        self.load()
        self.assertEqual(self.student["comment"], "Strengths: Context. Typed.")
        self.assertEqual(self.student["comment_line"], "Strengths: Context.")
        self.assertEqual(self.loaded["students"][0]["comment_line"], "Strengths: Context.")
        # A save that doesn't mention it, as an older page's wouldn't, keeps it.
        self.client.post("/api/save", json={"key": key, "comment": "Strengths: Context. More."})
        self.assertEqual(self.student["comment_line"], "Strengths: Context.")
        # Anything but text means no remembered line.
        self.save_comment(key, "Typed.", {"not": "text"})
        self.assertIsNone(self.student["comment_line"])

    def test_saved_file_without_comment_line_loads_unchanged(self):
        key = self.student["key"]
        self.save_comment(key, "Strengths: Context. Typed.", "Strengths: Context.")
        path = Path(self.ws.cache_file_path())
        cache = json.loads(path.read_text(encoding="utf-8"))
        entry = next(v for v in cache.values()
                     if isinstance(v, dict) and key in (v.get("students") or {}))
        del entry["students"][key]["comment_line"]
        path.write_text(json.dumps(cache), encoding="utf-8")
        self.load()
        self.assertEqual(self.student["comment"], "Strengths: Context. Typed.")
        self.assertEqual(self.student["keywords"], ["Context"])
        self.assertIsNone(self.student["comment_line"])

    def test_linked_partners_share_the_comment_line(self):
        with fitz_open() as doc:
            doc.new_page().insert_text((60, 60), "Fictional partner work")
            doc.save(self.folder / "Ben Okafor.pdf")
        self.load()
        ada, ben = sorted(self.ws.STATE["students"])
        self.save_comment(ada, "Strengths: Context. Typed.", "Strengths: Context.")
        # Linking copies it to a partner who hasn't been graded.
        response = self.client.post("/api/group/link", json={"a_key": ada, "b_key": ben})
        self.assertEqual(response.status_code, 200, response.get_json())
        students = self.ws.STATE["students"]
        self.assertEqual(students[ben]["comment"], "Strengths: Context. Typed.")
        self.assertEqual(students[ben]["comment_line"], "Strengths: Context.")
        # A save on either one reaches both, and comes back for the partner's row.
        saved = self.save_comment(ben, "Strengths: Colour. Typed.", "Strengths: Colour.")
        self.assertEqual(students[ada]["comment_line"], "Strengths: Colour.")
        self.assertEqual({s["comment_line"] for s in saved["students"]}, {"Strengths: Colour."})
        self.load()
        self.assertEqual(self.ws.STATE["students"][ben]["comment_line"], "Strengths: Colour.")

    def link_fixture(self, *names):
        """Fictional partners, returned as {first name: student}."""
        for name in names:
            with fitz_open() as doc:
                doc.new_page().insert_text((60, 60), f"Fictional work by {name}")
                doc.save(self.folder / f"{name}.pdf")
        self.load()
        return {st["key"].split(":")[-1].split()[0]: st for st in self.ws.STATE["students"].values()}

    def mark(self, st, **fields):
        response = self.client.post("/api/save", json={"key": st["key"], **fields})
        self.assertEqual(response.status_code, 200)

    def link(self, a, b):
        response = self.client.post("/api/group/link", json={"a_key": a["key"], "b_key": b["key"]})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_linking_combines_comments_and_ticks(self):
        s = self.link_fixture("Ben Okafor")
        self.mark(s["ada"], keywords=["Shading"], comment="Strengths: Shading. Typed for Ada.",
                  comment_line="Strengths: Shading.")
        self.mark(s["ben"], keywords=["Colour"], comment="Strengths: Colour. Typed for Ben.",
                  comment_line="Strengths: Colour.")
        self.link(s["ada"], s["ben"])
        for st in s.values():
            self.assertEqual(st["keywords"], ["Shading", "Colour"])
            self.assertEqual(st["comment_line"], "Strengths: Shading, Colour.")
            self.assertEqual(st["comment"],
                             "Strengths: Shading, Colour. Typed for Ada. Typed for Ben.")
        # Still combined after a reload, and linking again repeats nothing.
        self.load()
        ada, ben = sorted(self.ws.STATE["students"])
        self.client.post("/api/group/link", json={"a_key": ben, "b_key": ada})
        self.assertEqual(self.ws.STATE["students"][ada]["comment"],
                         "Strengths: Shading, Colour. Typed for Ada. Typed for Ben.")

    def test_linking_handles_older_and_identical_comments(self):
        s = self.link_fixture("Ben Okafor", "Chie Sato")
        # No remembered line: the ticks' line comes off. Unrelated text stays whole.
        self.mark(s["ada"], keywords=["Shading"], comment="Strengths: Shading. Older text.")
        self.mark(s["ben"], keywords=[], comment="Same words.")
        self.mark(s["chie"], keywords=[], comment="Same words.")
        self.link(s["ben"], s["chie"])
        self.assertEqual(s["ben"]["comment"], "Same words.")
        self.link(s["ada"], s["ben"])
        for st in s.values():
            self.assertEqual(st["comment"], "Strengths: Shading. Older text. Same words.")

    def test_linking_repeats_text_rather_than_risk_losing_it(self):
        s = self.link_fixture("Ben Okafor", "Chie Sato")
        self.mark(s["ada"], comment="Typed for Ada.")
        self.mark(s["ben"], comment="Same words.")
        self.mark(s["chie"], comment="Same words.")
        self.link(s["ada"], s["ben"])
        self.link(s["ada"], s["chie"])
        # Only a whole comment counts as the same, so these words appear twice.
        self.assertEqual(s["chie"]["comment"], "Typed for Ada. Same words. Same words.")

    def test_linking_shares_the_first_graded_members_grades(self):
        s = self.link_fixture("Ben Okafor", "Chie Sato")
        # Clicked first with no grade: the partner's grade reaches both, and the
        # first student's typed comment is kept.
        self.mark(s["ada"], comment="Typed for Ada.")
        self.mark(s["ben"], grades={"A": "6"}, comment="Typed for Ben.")
        self.link(s["ada"], s["ben"])
        self.assertEqual(s["ada"]["grades"], {"A": "6"})
        self.assertEqual(s["ada"]["comment"], "Typed for Ben. Typed for Ada.")
        self.assertTrue(s["ada"]["graded"])
        # A new partner joining doesn't change the group's grade, even clicked first.
        # A grade only the new partner has on another criterion is kept.
        self.mark(s["chie"], grades={"A": "2", "C": "4"}, comment="Typed for Chie.")
        self.link(s["chie"], s["ada"])
        for st in s.values():
            self.assertEqual(st["grades"], {"A": "6", "C": "4"})
            self.assertEqual(st["comment"], "Typed for Ben. Typed for Ada. Typed for Chie.")

    def test_linking_two_graded_students_keeps_the_first_clicked(self):
        s = self.link_fixture("Ben Okafor")
        self.mark(s["ada"], grades={"A": "3"}, late_marked=True, comment="Late submission.",
                  comment_line="Late submission.")
        self.mark(s["ben"], grades={"A": "7"}, late_marked=False)
        self.link(s["ben"], s["ada"])
        for st in s.values():
            self.assertEqual(st["grades"], {"A": "7"})
            self.assertFalse(st["late_marked"])
            self.assertEqual(st["comment"], "")

    def test_generated_line_matches_the_page(self):
        node = shutil.which(os.environ.get("CAM_TEST_NODE", "node"))
        if not node:
            self.skipTest("Node.js is required for workspace UI checks")
        source = (ROOT / "cam_grading_workspace/app.py").read_text(encoding="utf-8")
        begin = source.index("function autoComment(")
        page = source[begin:source.index("\n}\n", begin) + 2]
        checklist = [{"label": "Shading", "type": "positive"}, {"label": "Detail", "type": "growth"}]
        self.ws.STATE["checklist"] = checklist
        for keywords, late in ((["Shading", "Detail"], True), (["Detail"], False), (["Gone"], False),
                               ([], True), ([], False)):
            with self.subTest(keywords=keywords, late=late):
                student = {"keywords": keywords, "late_marked": late}
                script = (f"const KEYWORDS = {json.dumps(checklist)};\n{page}\n"
                          f"process.stdout.write(autoComment({json.dumps(student)}));")
                result = subprocess.run([node, "-e", script], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.ws._generated_line(student), result.stdout)

    def test_keyword_list_is_saved_whole_and_stays_on_reload(self):
        whole = [{"label": "Shading", "type": "positive"}, {"label": "Colour", "type": "positive"},
                 {"label": "Detail", "type": "growth"}]
        self.assertEqual(self.loaded["checklist"], [])
        self.assertFalse(self.loaded["checklist_recovered"])
        # What the page does on load when no list is saved.
        self.client.post("/api/checklist", json={"checklist": whole})
        self.mark(self.student, keywords=["Shading"], comment="Strengths: Shading.")
        self.load()
        self.assertEqual(self.loaded["checklist"], whole)
        self.assertFalse(self.loaded["checklist_recovered"])

    def test_keyword_list_rebuilt_from_ticks_says_so(self):
        self.mark(self.student, keywords=["Shading"], comment="Strengths: Shading.")
        self.load()
        self.assertEqual(self.loaded["checklist"], [{"label": "Shading", "type": "positive"}])
        self.assertTrue(self.loaded["checklist_recovered"])

    def test_comment_edited_in_cam_keeps_the_remembered_line(self):
        key = self.student["key"]
        self.save_comment(key, "Strengths: Context. Typed.", "Strengths: Context.")
        # CAM's copy last seen, then the same comment edited in CAM.
        self.handoff("Strengths: Context. Typed.")
        self.handoff("Edited in CAM.")
        self.assertEqual(self.student["comment"], "Edited in CAM.")
        # The page sees it no longer starts with the line, so the text stays whole.
        self.assertEqual(self.student["comment_line"], "Strengths: Context.")

    def handoff(self, comment):
        """Open the task from CAM, with CAM holding this comment."""
        published = {self.student["name"]: {"grades": {}, "comment": comment}}
        with patch.object(self.ws, "load_cam_published", return_value=published):
            self.load()

    def test_a_handoff_keeps_text_typed_since_cam_last_saw_the_comment(self):
        key = self.student["key"]
        self.save_comment(key, "From CAM.", "")
        self.handoff("From CAM.")
        self.save_comment(key, "From CAM. Typed here, not exported.", "")
        # CAM publishes its older copy at every handoff.
        self.handoff("From CAM.")
        self.assertEqual(self.student["comment"], "From CAM. Typed here, not exported.")
        self.load()
        self.handoff("From CAM.")
        self.assertEqual(self.student["comment"], "From CAM. Typed here, not exported.")

    def test_a_handoff_combines_when_both_sides_changed(self):
        key = self.student["key"]
        self.save_comment(key, "From CAM.", "")
        self.handoff("From CAM.")
        self.save_comment(key, "Rewritten here.", "")
        self.handoff("Rewritten in CAM.")
        self.assertEqual(self.student["comment"], "Rewritten here. Rewritten in CAM.")
        # That copy has now been seen, so the next handoff doesn't repeat it.
        self.handoff("Rewritten in CAM.")
        self.assertEqual(self.student["comment"], "Rewritten here. Rewritten in CAM.")

    def test_a_handoff_with_no_copy_seen_yet_loses_nothing(self):
        key = self.student["key"]
        self.save_comment(key, "Typed here.", "")
        self.handoff("Older in CAM.")
        self.assertEqual(self.student["comment"], "Typed here. Older in CAM.")

    def test_a_handoff_without_repeating_text_already_here(self):
        key = self.student["key"]
        self.save_comment(key, "From CAM. And more.", "")
        self.handoff("From CAM.")
        self.assertEqual(self.student["comment"], "From CAM. And more.")
        self.handoff("From CAM. And more. Added in CAM.")
        self.assertEqual(self.student["comment"], "From CAM. And more. Added in CAM.")

    def test_a_blank_comment_from_cam_clears_nothing(self):
        key = self.student["key"]
        self.save_comment(key, "Typed here.", "")
        self.handoff("")
        self.assertEqual(self.student["comment"], "Typed here.")

    def test_an_export_after_a_handoff_doesnt_trip_the_next_one(self):
        key = self.student["key"]
        self.save_comment(key, "From CAM.", "")
        self.handoff("From CAM.")
        self.save_comment(key, "From CAM. Added.", "")
        # Exported and synced, so CAM now publishes the longer comment.
        self.handoff("From CAM. Added.")
        self.assertEqual(self.student["comment"], "From CAM. Added.")
        self.assertEqual(self.student["cam_comment"], "From CAM. Added.")

    def test_linked_partners_keep_their_combined_comment_through_a_handoff(self):
        s = self.link_fixture("Ben Okafor")
        self.mark(s["ada"], comment="Typed for Ada.")
        self.mark(s["ben"], comment="Typed for Ben.")
        names = {st["name"]: st["comment"] for st in s.values()}
        with patch.object(self.ws, "load_cam_published", return_value={
                name: {"grades": {}, "comment": comment} for name, comment in names.items()}):
            self.load()
        self.link(*sorted(self.ws.STATE["students"].values(), key=lambda st: st["key"]))
        combined = "Typed for Ada. Typed for Ben."
        with patch.object(self.ws, "load_cam_published", return_value={
                name: {"grades": {}, "comment": comment} for name, comment in names.items()}):
            self.load()
        for st in self.ws.STATE["students"].values():
            self.assertEqual(st["comment"], combined)

    def test_restored_draft_feedback_forgets_the_remembered_line(self):
        key = self.student["key"]
        self.save_comment(key, "Strengths: Context. Typed.", "Strengths: Context.")
        restored = {"is_draft": True, "published_feedback": {self.student["name"]: {
            "comment": "Strengths: Colour. Restored.", "keywords": ["Colour"]}}}
        real = self.ws.load_assignment_options
        with patch.object(self.ws, "load_assignment_options",
                          side_effect=lambda folder: {**real(folder), **restored}):
            self.load()
        # No copy seen yet, so both comments stay, and both sets of ticks.
        self.assertEqual(self.student["comment"],
                         "Strengths: Context. Typed. Strengths: Colour. Restored.")
        self.assertEqual(self.student["keywords"], ["Context", "Colour"])
        self.assertEqual(self.student["comment_line"], "Strengths: Context.")
        # A copy CAM has changed replaces a comment left as it was, and its ticks with it.
        self.assertEqual(self.student["cam_comment"], "Strengths: Colour. Restored.")
        self.save_comment(key, "Strengths: Colour. Restored.", "Strengths: Colour.")
        restored["published_feedback"][self.student["name"]] = {
            "comment": "Rewritten in CAM.", "keywords": ["Sources"]}
        with patch.object(self.ws, "load_assignment_options",
                          side_effect=lambda folder: {**real(folder), **restored}):
            self.load()
        self.assertEqual(self.student["comment"], "Rewritten in CAM.")
        self.assertEqual(self.student["keywords"], ["Sources"])
        self.assertIsNone(self.student["comment_line"])
        # An unchanged copy leaves what's here alone, typed text and ticks.
        self.save_comment(key, "Rewritten in CAM. Typed since.", "")
        with patch.object(self.ws, "load_assignment_options",
                          side_effect=lambda folder: {**real(folder), **restored}):
            self.load()
        self.assertEqual(self.student["comment"], "Rewritten in CAM. Typed since.")

    def test_export_holds_the_whole_comment_and_no_new_column(self):
        self.save_comment(self.student["key"], "Strengths: Context. Typed.", "Strengths: Context.")
        path = Path(self.client.get("/api/export").get_json()["path"])
        text = path.read_text(encoding="utf-8-sig")
        self.assertIn("Strengths: Context. Typed.", text)
        self.assertNotIn("comment_line", text)

    def test_no_deadline_export_reuses_existing_file_date(self):
        self.ws.STATE["deadline"] = ""
        first = Path(self.client.get("/api/export").get_json()["path"])
        # Pretend that first export was made on an earlier day.
        older = first.with_name("Investigation_Grades_2026-01-01.csv")
        first.rename(older)
        again = self.client.get("/api/export").get_json()
        self.assertTrue(again.get("needs_confirm"), again)   # overwrite, not a twin
        self.assertEqual(again["filename"], older.name)
        saved = self.client.get("/api/export?force=1").get_json()
        self.assertEqual(saved["stale_siblings"], [])
        self.assertEqual(sorted(p.name for p in older.parent.glob("*_Grades_*.csv")),
                         [older.name])
        # A real deadline still names the file by its due date.
        self.ws.STATE["deadline"] = "2026-03-05T15:00"
        dated = self.client.get("/api/export").get_json()
        self.assertEqual(dated["filename"], "Investigation_Grades_2026-03-05.csv")
        self.assertEqual(dated["stale_siblings"], [older.name])

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
