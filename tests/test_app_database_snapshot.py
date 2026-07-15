"""App integration tests for single-read snapshot boot and quarantine."""

import json
import os
import sys
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest import mock

# Importing app.py does not run CAM, load preferences, or touch the database.
# The bundled test runtime used by Codex does not include Streamlit, so provide
# only the two import-time decorators when that optional UI dependency is absent.
try:
    import streamlit  # noqa: F401
except ModuleNotFoundError:
    streamlit_stub = types.ModuleType("streamlit")

    def _passthrough_decorator(*args, **kwargs):
        if len(args) == 1 and callable(args[0]) and not kwargs:
            return args[0]
        return lambda fn: fn

    streamlit_stub.dialog = _passthrough_decorator
    streamlit_stub.fragment = _passthrough_decorator
    streamlit_stub.session_state = {}
    sys.modules["streamlit"] = streamlit_stub

import app
from engine import capture_database_snapshot


def _payload(student_id="alice", assignment="Still Life"):
    return {
        "version": 1,
        "saved_at": "2026-07-15T10:00:00",
        "gradebook": {
            "students": [{
                "student_id": student_id,
                "name": student_id.title(),
                "scores": [],
                "exam_results": [],
            }],
            "assignments": [{"name": assignment, "criteria": ["A"]}],
        },
        "session": {
            "classes": [{"name": "Class 1"}],
            "active_class": "Class 1",
            "rosters": {"Class 1": [{"key": student_id}]},
        },
    }


class AppDatabaseSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self._tmp.name})
        self._env.start()
        self.path = os.path.join(self._tmp.name, "acm_database.json")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, payload):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_diagnosis_preserves_existing_quarantine_states(self):
        self.assertIsNone(app.diagnose_db_load(
            capture_database_snapshot(self.path)))

        missing = os.path.join(self._tmp.name, "missing", "acm_database.json")
        self.assertEqual(app.diagnose_db_load(
            capture_database_snapshot(missing))["reason"], "storage-missing")

        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("malformed")
        self.assertEqual(app.diagnose_db_load(
            capture_database_snapshot(self.path))["reason"], "unreadable")

        small_empty = {
            "version": 1,
            "gradebook": {"students": [], "assignments": []},
            "session": {},
        }
        self._write(small_empty)
        self.assertIsNone(app.diagnose_db_load(
            capture_database_snapshot(self.path)))

        heavy_empty = dict(small_empty)
        heavy_empty["padding"] = "x" * (app.EMPTY_DB_MAX_BYTES + 1)
        self._write(heavy_empty)
        self.assertEqual(app.diagnose_db_load(
            capture_database_snapshot(self.path))["reason"], "empty-load")

    def test_diagnosis_uses_captured_bytes_after_disk_replacement(self):
        heavy_empty = {
            "version": 1,
            "gradebook": {"students": [], "assignments": []},
            "session": {},
            "padding": "x" * (app.EMPTY_DB_MAX_BYTES + 1),
        }
        self._write(heavy_empty)
        snapshot = capture_database_snapshot(self.path)
        self._write(_payload("zoe", "Replacement"))

        blocked = app.diagnose_db_load(snapshot)
        self.assertEqual(blocked["reason"], "empty-load")

    def test_init_state_reads_active_database_once_and_only_hydrates(self):
        self._write(_payload())
        original_st = app.st
        app.st = SimpleNamespace(session_state={})
        prefs = dict(app.DEFAULT_PREFS)
        prefs["setup_done"] = True
        real_open = open
        reads = []

        def tracked_open(file, mode="r", *args, **kwargs):
            if (os.path.abspath(os.fspath(file)) == os.path.abspath(self.path)
                    and "r" in mode):
                reads.append(mode)
            return real_open(file, mode, *args, **kwargs)

        try:
            with mock.patch("builtins.open", side_effect=tracked_open), \
                    mock.patch.object(app, "load_prefs", return_value=prefs), \
                    mock.patch.object(app, "save_prefs"), \
                    mock.patch.object(app, "_heal_from_class_mirrors"), \
                    mock.patch.object(app, "_seed_mirror_fingerprints"), \
                    mock.patch.object(app, "save_database") as save_db, \
                    mock.patch.object(app, "_rotate_daily_backup") as backup, \
                    mock.patch.object(app, "_park_blocked_payload") as park, \
                    mock.patch.object(app, "_mirror_classes_to_cloud") as mirror:
                app.init_state()

            self.assertEqual(reads, ["rb"])
            self.assertEqual(set(app.st.session_state["gradebook"].students),
                             {"alice"})
            self.assertEqual(
                app.st.session_state["gradebook"].assignments[0].name,
                "Still Life")
            self.assertTrue(app.st.session_state["db_loaded"])
            self.assertIsNone(app.st.session_state["db_load_blocked"])
            save_db.assert_not_called()
            backup.assert_not_called()
            park.assert_not_called()
            mirror.assert_not_called()
        finally:
            app.st = original_st


if __name__ == "__main__":
    unittest.main()
