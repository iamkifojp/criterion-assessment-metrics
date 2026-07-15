"""App integration tests for Phase-5 validation quarantine messaging."""

import json
import os
import sys
import tempfile
import types
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

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


def _payload(version=2):
    return {
        "version": version,
        "saved_at": "2026-07-15T10:00:00",
        "database_id": str(uuid.uuid4()),
        "generation": 1,
        "gradebook": {
            "students": [{
                "student_id": "private-id",
                "name": "Private Name",
                "scores": [{"criterion": "A", "value": 6,
                            "timestamp": "2026-07-15T09:00:00",
                            "comment": "Private comment"}],
                "exam_results": [],
            }],
            "assignments": [{"name": "Private Assignment", "criteria": ["A"]}],
        },
        "session": {},
    }


class AppDatabaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        self.env.start()
        self.path = os.path.join(self.tmp.name, "acm_database.json")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_future_schema_has_specific_quarantine_reason(self):
        payload = _payload(3)
        self._write(payload)
        blocked = app.diagnose_db_load(capture_database_snapshot(self.path))
        self.assertEqual(blocked["reason"], "unsupported-schema")
        self.assertEqual(blocked["issues"][0]["path"], "version")

    def test_malformed_record_has_validation_quarantine_not_empty_load(self):
        payload = _payload()
        payload["gradebook"]["students"][0]["scores"][0]["value"] = "6"
        self._write(payload)
        blocked = app.diagnose_db_load(capture_database_snapshot(self.path))
        self.assertEqual(blocked["reason"], "database-validation-failed")
        self.assertIn("gradebook.students[0].scores[0].value",
                      {item["path"] for item in blocked["issues"]})

    def test_quarantine_banner_shows_only_safe_bounded_diagnostics(self):
        issues = [
            {"path": f"gradebook.students[{index}].scores[0].value",
             "code": "expected-integer"}
            for index in range(12)
        ]
        messages = []
        original_st = app.st
        app.st = SimpleNamespace(
            session_state={"db_load_blocked": {
                "reason": "database-validation-failed", "path": self.path,
                "issues": issues}},
            error=messages.append,
            button=lambda *args, **kwargs: False,
        )
        try:
            app._render_db_quarantine_banner()
        finally:
            app.st = original_st
        rendered = "\n".join(messages)
        self.assertIn("and 2 more issue(s)", rendered)
        self.assertIn("gradebook.students[0].scores[0].value", rendered)
        for private in ("Private Name", "private-id", "Private Assignment",
                        "Private comment"):
            self.assertNotIn(private, rendered)

    def test_init_state_does_not_hydrate_or_heal_invalid_snapshot(self):
        payload = _payload()
        payload["gradebook"]["assignments"][0]["criteria"] = ["Z"]
        self._write(payload)
        original_st = app.st
        app.st = SimpleNamespace(session_state={})
        prefs = dict(app.DEFAULT_PREFS)
        prefs["setup_done"] = True
        try:
            with mock.patch.object(app, "load_prefs", return_value=prefs), \
                    mock.patch.object(app, "save_prefs"), \
                    mock.patch.object(app, "_heal_from_class_mirrors") as heal, \
                    mock.patch.object(app, "_seed_mirror_fingerprints") as seed:
                app.init_state()
            self.assertEqual(
                app.st.session_state["db_load_blocked"]["reason"],
                "database-validation-failed")
            heal.assert_not_called()
            seed.assert_not_called()
            self.assertNotIn("private-id",
                             app.st.session_state["gradebook"].students)
        finally:
            app.st = original_st


if __name__ == "__main__":
    unittest.main()
