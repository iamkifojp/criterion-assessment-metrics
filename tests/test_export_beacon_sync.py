"""Sync-on-export beacon, scoped exam sync, and old exam CSVs (convergence Stage 4).

  * Sync leaves an old CGW exam CSV (a ``Total Score`` column) in a class
    folder alone: it is neither imported as an exam nor read as a grading CSV.
    The grading CSV beside it still syncs.
  * ``sync_exam`` reads only the exam's CAM2 session, so an old exam CSV of
    the same name brings nothing in.
  * The CGW-side ``_write_export_beacon`` writes the exact JSON shape the CAM
    poller consumes, atomically, and no-ops when no cloud dir is configured.

Same seams as tests/test_app_mirror.py: ``app.st`` is a stand-in whose
``session_state`` is a plain dict, ``app.gb`` a fixture gradebook, and
``app.class_data_dir`` a temp folder per class. Streamlit never runs. The
disk-writing tail helpers (persist / heal / ensure-context) are stubbed so the
test exercises the real fingerprint + ingest path only. Run:

    python -m unittest tests.test_export_beacon_sync
"""

import os
import sys
import json
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (path shim must precede the import)
from engine import Gradebook  # noqa: E402

CLASS = "Test MYP Class"

EXAM_CSV = (
    "﻿Student Name,Q1,Q2,Total Score,Max Total,Due Date,Comment\r\n"
    "Ada,3,5,8,10,2026-06-01,Solid.\r\n"
    "Bob,2,4,6,10,2026-06-01,\r\n"
)

# A plain grading export (no "Total Score" column) — synced as usual.
GRADING_CSV = (
    "﻿Student Name,Grade (Crit A),Comment,Due Date,Late\r\n"
    "Ada,6,Nice,2026-06-01,\r\n"
)


class OldExamCsvSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_beacon_sync_")
        self.class_dir = os.path.join(self.tmp, CLASS)
        os.makedirs(self.class_dir, exist_ok=True)
        self.exam_path = os.path.join(
            self.class_dir, "Final Exam_Grades_2026-06-01.csv")
        with open(self.exam_path, "w", encoding="utf-8", newline="") as f:
            f.write(EXAM_CSV)
        self.grading_path = os.path.join(
            self.class_dir, "Painting_Grades_2026-06-01.csv")
        with open(self.grading_path, "w", encoding="utf-8", newline="") as f:
            f.write(GRADING_CSV)

        self.gb = Gradebook()
        self.ss = {
            "prefs": {"db_custom_path": self.tmp},
            "ingested_files": {},
            "active_class": CLASS,
            "classes": [{"name": CLASS, "grade": "", "myp_year": "",
                         "subject": ""}],
            "rosters": {CLASS: []},          # rosterless -> legacy path
            "work_aliases": {CLASS: {}},
            "unmatched_works": {CLASS: {}},
            "active": {},
            "archived": set(),
            "late_flags": {},
            "late_flags_cleanup_v1": True,
            "exam_sessions": {},
        }
        self._orig = {
            "st": app.st, "gb": app.gb, "cdd": app.class_data_dir,
            "persist": app.persist, "heal": app._heal_score_comments_from_mirrors,
            "ectx": app.ensure_class_context, "dbf": app.db_folder,
        }
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.class_data_dir = lambda name, create=False: (
            self.class_dir if name == CLASS else os.path.join(self.tmp, name))
        # Stub the disk-writing / context tail so the test stays hermetic.
        app.persist = lambda *a, **k: None
        app._heal_score_comments_from_mirrors = lambda *a, **k: None
        app.ensure_class_context = lambda *a, **k: None
        # The global scan walks db_folder(); never let it reach real prefs.
        app.db_folder = lambda: self.tmp

    def tearDown(self):
        app.st = self._orig["st"]
        app.gb = self._orig["gb"]
        app.class_data_dir = self._orig["cdd"]
        app.persist = self._orig["persist"]
        app._heal_score_comments_from_mirrors = self._orig["heal"]
        app.ensure_class_context = self._orig["ectx"]
        app.db_folder = self._orig["dbf"]
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_sync_skips_old_exam_csv(self):
        summary = app.sync_from_cloud()
        names = [a.name for a in self.gb.assignments]
        self.assertIn("Painting", names)          # the grading CSV synced
        self.assertNotIn("Final Exam", names)     # the old exam CSV did not
        self.assertFalse(any(s.exam_results for s in self.gb))
        self.assertNotIn(os.path.abspath(self.exam_path), self.ss["ingested_files"])
        self.assertEqual(summary["errors"], 0)

    def test_sync_exam_ignores_old_exam_csv(self):
        summary = app.sync_exam(CLASS, "Final Exam")
        self.assertEqual(summary["found"], 0)
        self.assertEqual(summary["ingested"], 0)
        self.assertEqual(self.gb.assignments, [])

    def test_sync_exam_quiet_noop_without_db_path(self):
        self.ss["prefs"]["db_custom_path"] = ""
        summary = app.sync_exam(CLASS, "Final Exam")
        self.assertEqual(summary["found"], 0)
        self.assertEqual(summary["ingested"], 0)


class ExportBeaconWriterTest(unittest.TestCase):
    """The CGW-side beacon writer (imported from the Flask sub-app module)."""

    @classmethod
    def setUpClass(cls):
        # CGW's app.py shares the module name "app" with the root CAM app (already
        # imported above), so a plain ``import app`` returns the wrong module.
        # Load it from its file under a distinct name; its own dir goes on the
        # path first so its ``import pdf_view`` resolves to the CGW copy.
        import importlib.util
        cgw_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "cam_grading_workspace")
        sys.path.insert(0, cgw_dir)
        spec = importlib.util.spec_from_file_location(
            "cgw_app_mod", os.path.join(cgw_dir, "app.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cls.cgw = mod

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_beacon_write_")
        self._orig_cloud = self.cgw.SETTINGS.get("cloud_dir", "")

    def tearDown(self):
        self.cgw.SETTINGS["cloud_dir"] = self._orig_cloud
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _beacon(self):
        return os.path.join(self.tmp, "cam_export_beacon.json")

    def test_writes_expected_shape_atomically(self):
        self.cgw.SETTINGS["cloud_dir"] = self.tmp
        self.cgw._write_export_beacon(
            CLASS, "Painting", csv_path="/x/Painting.csv")
        p = self._beacon()
        self.assertTrue(os.path.isfile(p))
        self.assertFalse(os.path.exists(p + ".tmp"))   # no torn temp left behind
        with open(p, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(
            set(data), {"class_name", "assignment", "csv_path", "ts"})
        self.assertEqual(data["class_name"], CLASS)
        self.assertEqual(data["assignment"], "Painting")
        self.assertIsInstance(data["ts"], float)

    def test_overwrite(self):
        self.cgw.SETTINGS["cloud_dir"] = self.tmp
        self.cgw._write_export_beacon(CLASS, "Painting", "/x/a.csv")
        self.cgw._write_export_beacon(CLASS, "Collage", "/x/c.csv")
        with open(self._beacon(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["assignment"], "Collage")

    def test_noop_without_cloud_dir(self):
        self.cgw.SETTINGS["cloud_dir"] = ""
        # Must not raise and must not create a file anywhere.
        self.cgw._write_export_beacon(CLASS, "Painting", "/x/a.csv")
        self.assertFalse(os.path.exists(self._beacon()))


if __name__ == "__main__":
    unittest.main()
