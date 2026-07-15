"""App integration tests for Phase-2 checked persistence and conflict UX."""

import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import app
from engine import (
    DatabaseWriteToken,
    capture_database_snapshot,
    load_database_snapshot,
    save_database_checked,
)


def _legacy_payload():
    return {
        "version": 1,
        "saved_at": "2026-07-15T10:00:00",
        "gradebook": {
            "students": [{"student_id": "alice", "name": "Alice",
                          "scores": [], "exam_results": []}],
            "assignments": [{"name": "Still Life", "criteria": ["A"]}],
        },
        "session": {
            "classes": [{"name": "Class 1"}],
            "active_class": "Class 1",
            "rosters": {"Class 1": [{"key": "alice", "name": "Alice"}]},
        },
    }


class AppDatabaseConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        self.env.start()
        self.path = os.path.join(self.tmp.name, "acm_database.json")
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(_legacy_payload(), handle)
        self.original_st = app.st
        app.st = SimpleNamespace(session_state={})
        prefs = dict(app.DEFAULT_PREFS)
        prefs["setup_done"] = True
        with mock.patch.object(app, "load_prefs", return_value=prefs), \
                mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_heal_from_class_mirrors"), \
                mock.patch.object(app, "_seed_mirror_fingerprints"):
            app.init_state()

    def tearDown(self):
        app.st = self.original_st
        self.env.stop()
        self.tmp.cleanup()

    def test_boot_retains_only_raw_free_write_token(self):
        token = app.st.session_state["db_write_token"]
        self.assertIsInstance(token, DatabaseWriteToken)
        self.assertEqual(token.schema_version, 1)
        self.assertFalse(hasattr(token, "raw_bytes"))
        self.assertEqual(token.content_hash,
                         capture_database_snapshot(self.path).content_hash)

    def test_successful_persist_updates_token_then_mirrors(self):
        before = app.st.session_state["db_write_token"]
        seen = []

        def mirror_after_save():
            seen.append(app.st.session_state["db_write_token"])

        with mock.patch.object(app, "_mirror_classes_to_cloud",
                               side_effect=mirror_after_save):
            app.persist(show=True)

        after = app.st.session_state["db_write_token"]
        self.assertNotEqual(after, before)
        self.assertEqual(after.generation, 1)
        self.assertEqual(seen, [after])
        self.assertEqual(app.st.session_state["save_status"][0], "ok")

    def test_stale_persist_preserves_recovery_and_skips_mirror(self):
        token = app.st.session_state["db_write_token"]
        loaded = load_database_snapshot(capture_database_snapshot(self.path))
        external = save_database_checked(
            self.path, loaded["gradebook"], {"external": True}, token)
        winner_hash = capture_database_snapshot(self.path).content_hash

        app.st.session_state["teacher_remarks"]["alice"] = "Pending edit"
        with mock.patch.object(app, "_mirror_classes_to_cloud") as mirror:
            app.persist(show=True)

        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["reason"], "concurrency-conflict")
        self.assertTrue(blocked["recovery"])
        self.assertEqual(capture_database_snapshot(self.path).content_hash,
                         winner_hash)
        recovered = load_database_snapshot(
            capture_database_snapshot(blocked["recovery"]))
        self.assertEqual(recovered["session"]["teacher_remarks"]["alice"],
                         "Pending edit")
        self.assertEqual(external.token.generation, 1)
        mirror.assert_not_called()

        with mock.patch.object(app, "save_database_checked") as checked:
            app.persist(show=True)
        checked.assert_not_called()

    def test_conflict_recovery_failure_keeps_memory_and_warns_not_to_close(self):
        token = app.st.session_state["db_write_token"]
        loaded = load_database_snapshot(capture_database_snapshot(self.path))
        save_database_checked(self.path, loaded["gradebook"], {}, token)
        app.st.session_state["teacher_remarks"]["alice"] = "Still in memory"
        with mock.patch.object(
                app, "write_conflict_recovery",
                side_effect=OSError("disk full")), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist(show=True)
        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["recovery"], "")
        self.assertIn("do not close",
                      app.st.session_state["save_status"][1].lower())
        self.assertEqual(app.st.session_state["teacher_remarks"]["alice"],
                         "Still in memory")

    def test_conflict_banner_explains_no_overwrite_or_merge(self):
        messages = []
        app.st = SimpleNamespace(
            session_state={
                "db_load_blocked": {
                    "reason": "concurrency-conflict", "path": self.path,
                    "recovery": self.path + ".conflict-recovery-test.json"}},
            error=messages.append,
            button=lambda *args, **kwargs: False,
        )
        app._render_db_quarantine_banner()
        message = messages[0].lower()
        self.assertIn("left the shared database unchanged", message)
        self.assertIn("did not merge", message)
        self.assertIn("allow cloud synchronization to finish", message)
        self.assertIn("review the shared and recovery versions", message)


if __name__ == "__main__":
    unittest.main()
