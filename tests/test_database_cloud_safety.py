"""Framework-free Phase-3 cloud-conflict sibling safety tests."""

import json
import os
import tempfile
import unittest

from engine import (
    DatabaseCloudConflictError,
    Gradebook,
    capture_database_snapshot,
    database_write_token,
    find_database_conflict_siblings,
    replace_database_checked,
    save_database,
    save_database_checked,
)


class DatabaseCloudSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "acm_database.json")

    def tearDown(self):
        self.tmp.cleanup()

    def _touch(self, name, content="{}"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return os.path.abspath(path)

    def test_classifier_flags_common_conflict_names_only(self):
        expected = {
            self._touch("acm_database (Laptop conflicted copy).json"),
            self._touch("acm_database-SchoolPC.json"),
            self._touch("ACM_DATABASE_2.JSON"),
            self._touch("acm_database [conflict].json"),
        }
        self._touch("unrelated.json")
        self._touch("acm_databasecopy.json")
        os.mkdir(os.path.join(self.tmp.name, "acm_database (folder).json"))
        self.assertEqual(set(find_database_conflict_siblings(self.path)), expected)
        self.assertEqual(
            find_database_conflict_siblings(self.path),
            find_database_conflict_siblings(self.path))

    def test_classifier_excludes_every_cam_owned_sidecar(self):
        names = (
            "acm_database.json.bak-auto-20260715",
            "acm_database.json.bak-pre-concurrency-upgrade-test",
            "acm_database.json.conflict-recovery-test.json",
            "acm_database.json.blocked-test",
            "acm_database.json.cam-write.lock",
            "acm_database.json.wiped-by-test",
            "acm_database.json.safety-marker",
            "acm_database.json.tmp",
        )
        for name in names:
            self._touch(name)
        self.assertEqual(find_database_conflict_siblings(self.path), ())

    def test_checked_save_blocks_before_creating_primary_or_backup(self):
        token = database_write_token(capture_database_snapshot(self.path))
        sibling = self._touch("acm_database (conflicted copy).json")
        with self.assertRaises(DatabaseCloudConflictError) as caught:
            save_database_checked(self.path, Gradebook(), {}, token)
        self.assertEqual(caught.exception.siblings, (sibling,))
        self.assertFalse(os.path.exists(self.path))
        self.assertFalse(any(".bak-" in name for name in os.listdir(self.tmp.name)))

    def test_explicit_replacement_blocks_before_backup_or_write(self):
        save_database(self.path, Gradebook(), {"marker": "original"})
        with open(self.path, "rb") as handle:
            original = handle.read()
        self._touch("acm_database-OtherPC.json", json.dumps({"version": 2}))
        with self.assertRaises(DatabaseCloudConflictError):
            replace_database_checked(self.path, Gradebook(), {"marker": "new"})
        with open(self.path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertFalse(any(".bak-" in name for name in os.listdir(self.tmp.name)))


if __name__ == "__main__":
    unittest.main()
