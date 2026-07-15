"""App integration coverage for Phase-4 dirty-only checked persistence."""

import os
import shutil
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import app
from engine import capture_database_snapshot


class AppDatabaseDirtyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        self.env.start()
        self.path = os.path.join(self.tmp.name, "acm_database.json")
        self.original_st = app.st
        self.prefs = dict(app.DEFAULT_PREFS)
        self.prefs["setup_done"] = True
        self.prefs["database_expectations"] = {}

        # Create an isolated current-format file through the real app payload,
        # then start a fresh application session against it.
        self._fresh_session()
        with mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        app.st = SimpleNamespace(session_state={})
        self._fresh_session()

    def tearDown(self):
        app.st = self.original_st
        self.env.stop()
        self.tmp.cleanup()

    def _fresh_session(self):
        app.st = SimpleNamespace(session_state={})
        with mock.patch.object(app, "load_prefs", return_value=self.prefs), \
                mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_heal_from_class_mirrors"), \
                mock.patch.object(app, "_seed_mirror_fingerprints"):
            app.init_state()

    def test_unchanged_persist_skips_shared_write_but_reconciles_mirrors(self):
        before = capture_database_snapshot(self.path)
        with mock.patch.object(app, "save_database_checked") as checked, \
                mock.patch.object(app, "_mirror_classes_to_cloud") as mirror:
            app.persist(show=True)
            app.persist()
        after = capture_database_snapshot(self.path)
        checked.assert_not_called()
        self.assertEqual(mirror.call_count, 2)
        self.assertEqual(after.content_hash, before.content_hash)
        self.assertEqual(after.generation, before.generation)
        self.assertFalse(app.st.session_state["db_dirty"])
        self.assertEqual(app.st.session_state["save_status"],
                         ("ok", "No changes to save."))

    def test_success_clears_dirty_and_only_first_change_requests_snapshot(self):
        calls = []
        real_save = app.save_database_checked

        def recording_save(*args, **kwargs):
            calls.append(kwargs["require_session_snapshot"])
            return real_save(*args, **kwargs)

        with mock.patch.object(app, "save_database_checked",
                               side_effect=recording_save), \
                mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.st.session_state["teacher_remarks"]["student"] = "First"
            app.persist()
            self.assertFalse(app.st.session_state["db_dirty"])
            app.st.session_state["teacher_remarks"]["student"] = "Second"
            app.persist()

        self.assertEqual(calls, [True, False])
        snapshots = [name for name in os.listdir(self.tmp.name)
                     if ".bak-session-" in name]
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(app.st.session_state["db_dirty"])

    def test_failed_save_and_recovery_do_not_clear_dirty(self):
        app.st.session_state["teacher_remarks"]["student"] = "Pending"
        with mock.patch.object(app, "save_database_checked",
                               side_effect=OSError("disk full")), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        self.assertTrue(app.st.session_state["db_dirty"])
        self.assertIn("disk full", app.st.session_state["save_status"][1])

        # A later concurrency failure may preserve a recovery file, but that is
        # not a successful write to the shared database.
        app.st.session_state["db_load_blocked"] = None
        observed = capture_database_snapshot(self.path)
        concurrency = app.DatabaseConcurrencyError(
            app.st.session_state["db_write_token"], observed, "changed")
        recovery = SimpleNamespace(path=self.path + ".conflict-recovery-test.json")
        with mock.patch.object(app, "save_database_checked",
                               side_effect=concurrency), \
                mock.patch.object(app, "write_conflict_recovery",
                                  return_value=recovery), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        self.assertTrue(app.st.session_state["db_dirty"])
        self.assertEqual(app.st.session_state["db_load_blocked"]["recovery"],
                         recovery.path)

    def test_switching_database_paths_requires_an_independent_snapshot(self):
        real_save = app.save_database_checked
        requirements = []

        def recording_save(*args, **kwargs):
            requirements.append(kwargs["require_session_snapshot"])
            return real_save(*args, **kwargs)

        with mock.patch.object(app, "save_database_checked",
                               side_effect=recording_save), \
                mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.st.session_state["teacher_remarks"]["student"] = "Old path"
            app.persist()

            second_dir = os.path.join(self.tmp.name, "second")
            os.makedirs(second_dir)
            second_path = os.path.join(second_dir, "acm_database.json")
            shutil.copy2(self.path, second_path)
            app.st.session_state["db_write_token"] = app.database_write_token(
                capture_database_snapshot(second_path))
            app.st.session_state["teacher_remarks"]["student"] = "New path"
            with mock.patch.dict(os.environ, {"CAM_DB_PATH": second_dir}):
                app.persist()

        self.assertEqual(requirements, [True, True])
        self.assertTrue(any(".bak-session-" in name
                            for name in os.listdir(self.tmp.name)))
        self.assertTrue(any(".bak-session-" in name
                            for name in os.listdir(second_dir)))


if __name__ == "__main__":
    unittest.main()
