"""Streamlit integration tests for Phase-3 expected/cloud database guards."""

import os
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

import app
from engine import Gradebook, capture_database_snapshot, save_database


class AppDatabaseCloudSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        self.env.start()
        self.path = os.path.join(self.tmp.name, "acm_database.json")
        self.original_st = app.st
        app.st = SimpleNamespace(session_state={})
        self.prefs = dict(app.DEFAULT_PREFS)
        self.prefs["database_expectations"] = {}
        self.prefs["setup_done"] = True

    def tearDown(self):
        app.st = self.original_st
        self.env.stop()
        self.tmp.cleanup()

    def _expect(self, state, database_id=""):
        self.prefs["database_expectations"] = {
            app._expectation_key(self.path): {
                "state": state, "database_id": database_id}}

    def _init(self):
        with mock.patch.object(app, "load_prefs", return_value=self.prefs), \
                mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_heal_from_class_mirrors") as heal, \
                mock.patch.object(app, "_seed_mirror_fingerprints"):
            app.init_state()
        return heal

    def test_pending_create_promotes_after_successful_save(self):
        self._expect("pending-create")
        self._init()
        self.assertIsNone(app.st.session_state["db_load_blocked"])
        with mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        snapshot = capture_database_snapshot(self.path)
        expected = app._database_expectation(self.path)
        self.assertEqual(expected["state"], "established")
        self.assertEqual(expected["database_id"], snapshot.database_id)

    def test_legacy_database_binding_gets_uuid_after_upgrade(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1,
                       "gradebook": {"students": [], "assignments": []},
                       "session": {}}, handle)
        self._init()
        expected = app._database_expectation(self.path)
        self.assertEqual(expected, {"state": "established", "database_id": ""})
        with mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        upgraded = capture_database_snapshot(self.path)
        self.assertEqual(upgraded.schema_version, 2)
        self.assertEqual(app._database_expectation(self.path)["database_id"],
                         upgraded.database_id)

    def test_old_completed_setup_missing_file_migrates_to_quarantine(self):
        # Exercise the non-environment production path without consulting any
        # real preference file.
        with mock.patch.dict(os.environ, {}, clear=True):
            self.prefs["db_custom_path"] = self.tmp.name
            app.st.session_state = {"prefs": self.prefs}
            with mock.patch.object(app, "save_prefs"):
                blocked = app.diagnose_expected_database(
                    capture_database_snapshot(self.path), ())
        self.assertEqual(blocked["reason"], "expected-database-missing")
        self.assertEqual(app._database_expectation(self.path)["state"],
                         "established")

    def test_established_missing_quarantines_then_reappears(self):
        self._expect("established", "known-id")
        heal = self._init()
        self.assertEqual(app.st.session_state["db_load_blocked"]["reason"],
                         "expected-database-missing")
        heal.assert_not_called()

        save_database(self.path, Gradebook(), {})
        # Empty ID models a legacy binding whose first readable v2 observation
        # is allowed to establish the concrete identity.
        self._expect("established", "")
        app.st.session_state["db_loaded"] = False
        app.st.session_state["db_load_blocked"] = None
        self._init()
        self.assertIsNone(app.st.session_state["db_load_blocked"])

    def test_identity_mismatch_quarantines_without_healing(self):
        save_database(self.path, Gradebook(), {})
        found = capture_database_snapshot(self.path).database_id
        self._expect("established", "00000000-0000-0000-0000-000000000001")
        heal = self._init()
        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["reason"], "database-identity-mismatch")
        self.assertEqual(blocked["found_database_id"], found)
        heal.assert_not_called()

    def test_sibling_at_boot_quarantines_without_healing(self):
        save_database(self.path, Gradebook(), {})
        found = capture_database_snapshot(self.path).database_id
        self._expect("established", found)
        sibling = os.path.join(self.tmp.name,
                               "acm_database (conflicted copy).json")
        with open(sibling, "w", encoding="utf-8") as handle:
            handle.write("{}")
        heal = self._init()
        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["reason"], "cloud-conflict-sibling")
        self.assertEqual(blocked["siblings"], [os.path.abspath(sibling)])
        heal.assert_not_called()

    def test_sibling_appearing_before_save_preserves_pending_work(self):
        save_database(self.path, Gradebook(), {})
        found = capture_database_snapshot(self.path).database_id
        self._expect("established", found)
        self._init()
        with open(self.path, "rb") as handle:
            original = handle.read()
        app.st.session_state["teacher_remarks"]["alice"] = "Pending"
        sibling = os.path.join(self.tmp.name, "acm_database-Laptop.json")
        with open(sibling, "w", encoding="utf-8") as handle:
            handle.write("{}")
        with mock.patch.object(app, "save_prefs"), \
                mock.patch.object(app, "_mirror_classes_to_cloud") as mirror:
            app.persist()
        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["reason"], "cloud-conflict-sibling")
        self.assertTrue(blocked["recovery"])
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        mirror.assert_not_called()

    def test_sibling_recovery_failure_keeps_memory_and_hides_reload(self):
        save_database(self.path, Gradebook(), {})
        found = capture_database_snapshot(self.path).database_id
        self._expect("established", found)
        self._init()
        app.st.session_state["teacher_remarks"]["alice"] = "Only in memory"
        with open(os.path.join(self.tmp.name, "acm_database-PC.json"),
                  "w", encoding="utf-8") as handle:
            handle.write("{}")
        with mock.patch.object(app, "write_conflict_recovery",
                               side_effect=OSError("disk full")), \
                mock.patch.object(app, "_mirror_classes_to_cloud"):
            app.persist()
        blocked = app.st.session_state["db_load_blocked"]
        self.assertEqual(blocked["recovery"], "")
        self.assertTrue(blocked["recovery_error"])
        self.assertEqual(app.st.session_state["teacher_remarks"]["alice"],
                         "Only in memory")

        keys = []
        state = app.st.session_state
        app.st = SimpleNamespace(
            session_state=state,
            error=lambda *_args, **_kwargs: None,
            button=lambda *_args, **kwargs: keys.append(kwargs.get("key")) or False,
        )
        app._render_db_quarantine_banner()
        self.assertIn("retry_conflict_recovery", keys)
        self.assertNotIn("retry_database_check", keys)

    def test_identity_rebind_requires_exact_typed_confirmation(self):
        expected_id = "00000000-0000-0000-0000-000000000001"
        found_id = "00000000-0000-0000-0000-000000000002"
        self._expect("established", expected_id)
        state = {
            "prefs": self.prefs,
            "db_load_blocked": {
                "reason": "database-identity-mismatch", "path": self.path,
                "expected_database_id": expected_id,
                "found_database_id": found_id, "counts": {}},
            "db_loaded": True, "db_write_token": object(),
            "mirror_ready": True,
        }
        disabled_values = []
        app.st = SimpleNamespace(
            session_state=state,
            error=lambda *_args, **_kwargs: None,
            text_input=lambda *_args, **_kwargs: "USE THIS DATABASE",
            button=lambda *_args, **kwargs: (
                disabled_values.append(kwargs.get("disabled")) or True),
            rerun=lambda: None,
        )
        with mock.patch.object(app, "save_prefs"):
            app._render_db_quarantine_banner()
        self.assertEqual(disabled_values, [False])
        self.assertEqual(
            self.prefs["database_expectations"]
                      [app._expectation_key(self.path)]["database_id"],
            found_id)
        self.assertFalse(state["db_loaded"])

    def test_path_keyed_expectations_do_not_replace_other_bindings(self):
        other = os.path.join(self.tmp.name, "other", "acm_database.json")
        app.st.session_state = {"prefs": self.prefs}
        with mock.patch.object(app, "save_prefs"):
            app._set_database_expectation(self.path, "established", "first")
            app._set_database_expectation(other, "pending-create", "")
        entries = self.prefs["database_expectations"]
        self.assertEqual(entries[app._expectation_key(self.path)]["database_id"],
                         "first")
        self.assertEqual(entries[app._expectation_key(other)]["state"],
                         "pending-create")


if __name__ == "__main__":
    unittest.main()
