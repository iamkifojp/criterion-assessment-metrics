"""Engine coverage for Phase-4 dirty fingerprints and safety snapshots."""

import os
import tempfile
import unittest
from unittest import mock

from engine import (
    Assignment,
    DatabaseWriteVerificationError,
    Gradebook,
    capture_database_snapshot,
    database_write_token,
    find_database_conflict_siblings,
    persistent_content_fingerprint,
    save_database_checked,
)


def _gradebook(count=1):
    gradebook = Gradebook()
    gradebook.assignments = [
        Assignment(name=f"Assignment {index}", criteria=["A"])
        for index in range(count)
    ]
    gradebook.get_or_create("student", "Student")
    return gradebook


class DatabaseDirtyPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "acm_database.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _create(self):
        absent = database_write_token(capture_database_snapshot(self.path))
        return save_database_checked(
            self.path, _gradebook(), {"settings": {"b": 2, "a": 1}}, absent)

    def test_logical_fingerprint_is_stable_and_detects_content_changes(self):
        first = persistent_content_fingerprint(
            _gradebook(), {"settings": {"b": 2, "a": 1}})
        reordered = persistent_content_fingerprint(
            _gradebook(), {"settings": {"a": 1, "b": 2}})
        changed = persistent_content_fingerprint(
            _gradebook(2), {"settings": {"a": 1, "b": 2}})
        self.assertEqual(first, reordered)
        self.assertNotEqual(first, changed)

    def test_required_snapshot_exactly_preserves_pre_save_generation(self):
        initial = self._create()
        before = capture_database_snapshot(self.path)
        result = save_database_checked(
            self.path, _gradebook(2), {"changed": True}, initial.token,
            require_session_snapshot=True)

        self.assertTrue(result.session_snapshot)
        copied = capture_database_snapshot(result.session_snapshot)
        self.assertEqual(copied.raw_bytes, before.raw_bytes)
        self.assertEqual(copied.content_hash, before.content_hash)
        self.assertEqual(copied.generation, before.generation)
        self.assertEqual(result.token.generation, before.generation + 1)

    def test_snapshot_verification_failure_leaves_primary_unchanged(self):
        initial = self._create()
        before = capture_database_snapshot(self.path).raw_bytes
        real_loader = __import__(
            "engine.persistence", fromlist=["load_database_snapshot"]
        ).load_database_snapshot

        def fail_only_for_session_snapshot(snapshot):
            if ".bak-session-" in snapshot.path:
                return None
            return real_loader(snapshot)

        with mock.patch("engine.persistence.load_database_snapshot",
                        side_effect=fail_only_for_session_snapshot):
            with self.assertRaises(DatabaseWriteVerificationError):
                save_database_checked(
                    self.path, _gradebook(2), {}, initial.token,
                    require_session_snapshot=True)
        self.assertEqual(capture_database_snapshot(self.path).raw_bytes, before)
        self.assertEqual(capture_database_snapshot(self.path).generation, 1)

    def test_snapshot_creation_failure_leaves_primary_unchanged(self):
        initial = self._create()
        before = capture_database_snapshot(self.path)
        with mock.patch("engine.persistence._write_sidecar_exclusive",
                        side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                save_database_checked(
                    self.path, _gradebook(2), {}, initial.token,
                    require_session_snapshot=True)
        after = capture_database_snapshot(self.path)
        self.assertEqual(after.raw_bytes, before.raw_bytes)
        self.assertEqual(after.generation, before.generation)

    def test_rapid_independent_session_snapshots_do_not_collide(self):
        initial = self._create()
        first = save_database_checked(
            self.path, _gradebook(2), {}, initial.token,
            require_session_snapshot=True)
        second = save_database_checked(
            self.path, _gradebook(3), {}, first.token,
            require_session_snapshot=True)
        self.assertNotEqual(first.session_snapshot, second.session_snapshot)
        self.assertTrue(os.path.exists(first.session_snapshot))
        self.assertTrue(os.path.exists(second.session_snapshot))

    def test_absent_target_has_no_snapshot_and_owned_sidecars_are_ignored(self):
        absent = database_write_token(capture_database_snapshot(self.path))
        created = save_database_checked(
            self.path, _gradebook(), {}, absent,
            require_session_snapshot=True)
        self.assertEqual(created.session_snapshot, "")

        snapshot_name = self.path + ".bak-session-test"
        with open(snapshot_name, "wb") as handle:
            handle.write(b"existing backup")
        self.assertEqual(find_database_conflict_siblings(self.path), ())

    def test_existing_backups_are_never_changed_or_pruned(self):
        initial = self._create()
        old_backup = self.path + ".bak-manual-keep"
        old_bytes = b"keep this exact backup"
        with open(old_backup, "wb") as handle:
            handle.write(old_bytes)

        result = save_database_checked(
            self.path, _gradebook(2), {}, initial.token,
            require_session_snapshot=True)
        self.assertTrue(result.session_snapshot)
        with open(old_backup, "rb") as handle:
            self.assertEqual(handle.read(), old_bytes)


if __name__ == "__main__":
    unittest.main()
