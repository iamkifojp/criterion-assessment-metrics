"""Engine tests for the Phase-1 immutable database snapshot."""

import hashlib
import json
import os
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from unittest import mock

from engine.persistence import (
    capture_database_snapshot,
    db_file_state,
    load_database,
    load_database_snapshot,
)


def _payload(student_id="alice", assignment="Still Life"):
    return {
        "version": 1,
        "saved_at": "2026-07-15T10:00:00",
        "gradebook": {
            "students": [{
                "student_id": student_id,
                "name": student_id.title(),
                "scores": [{
                    "criterion": "A",
                    "value": 6,
                    "timestamp": "2026-07-15T09:00:00",
                    "assignment": assignment,
                }],
                "exam_results": [],
            }],
            "assignments": [{"name": assignment, "criteria": ["A"]}],
        },
        "session": {
            "classes": [{"name": "Class 1"}],
            "rosters": {"Class 1": [{"key": student_id}, {"key": "bob"}]},
        },
    }


class DatabaseSnapshotTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self._tmp.name})
        self._env.start()
        self.path = os.path.join(self._tmp.name, "acm_database.json")

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, payload):
        with open(self.path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_valid_v1_snapshot_captures_boot_information(self):
        payload = _payload()
        payload["database_id"] = "db-observed-only"
        payload["generation"] = 17
        self._write(payload)

        snapshot = capture_database_snapshot(self.path)

        self.assertEqual(snapshot.state, "ok")
        self.assertEqual(snapshot.schema_version, 1)
        self.assertEqual(snapshot.database_id, "db-observed-only")
        self.assertEqual(snapshot.generation, 17)
        self.assertEqual(snapshot.mass, (1, 4))
        self.assertEqual(snapshot.size, len(snapshot.raw_bytes))
        self.assertEqual(snapshot.content_hash,
                         hashlib.sha256(snapshot.raw_bytes).hexdigest())
        self.assertIsInstance(snapshot.mtime_ns, int)
        self.assertEqual(snapshot.validation_errors, ())
        with self.assertRaises(FrozenInstanceError):
            snapshot.state = "absent"

        loaded = load_database_snapshot(snapshot)
        self.assertEqual(set(loaded["gradebook"].students), {"alice"})
        self.assertEqual(loaded["gradebook"].assignments[0].name, "Still Life")
        self.assertEqual(loaded["session"]["classes"][0]["name"], "Class 1")

    def test_legacy_v1_metadata_is_optional_and_not_created(self):
        self._write(_payload())
        snapshot = capture_database_snapshot(self.path)
        self.assertIsNone(snapshot.database_id)
        self.assertIsNone(snapshot.generation)
        with open(self.path, "r", encoding="utf-8") as fh:
            unchanged = json.load(fh)
        self.assertNotIn("database_id", unchanged)
        self.assertNotIn("generation", unchanged)

    def test_replacement_after_capture_does_not_change_hydration(self):
        self._write(_payload("alice", "Captured Assignment"))
        snapshot = capture_database_snapshot(self.path)
        captured_hash = snapshot.content_hash

        self._write(_payload("zoe", "Replacement Assignment"))
        loaded = load_database_snapshot(snapshot)

        self.assertEqual(set(loaded["gradebook"].students), {"alice"})
        self.assertEqual(loaded["gradebook"].assignments[0].name,
                         "Captured Assignment")
        self.assertEqual(snapshot.content_hash, captured_hash)
        self.assertNotEqual(snapshot.content_hash,
                            capture_database_snapshot(self.path).content_hash)

    def test_capture_reads_database_content_once(self):
        self._write(_payload())
        real_open = open
        reads = []

        def tracked_open(file, mode="r", *args, **kwargs):
            if (os.path.abspath(os.fspath(file)) == os.path.abspath(self.path)
                    and "r" in mode):
                reads.append(mode)
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", side_effect=tracked_open):
            snapshot = capture_database_snapshot(self.path)
            load_database_snapshot(snapshot)
            load_database_snapshot(snapshot)

        self.assertEqual(reads, ["rb"])

    def test_absent_and_unreadable_states(self):
        absent = capture_database_snapshot(self.path)
        self.assertEqual(absent.state, "absent")
        self.assertIsNone(absent.raw_bytes)

        cases = [
            (b"{not json", "invalid-json"),
            (b"[1, 2, 3]", "root-not-object"),
            (b"\xff\xfe", "invalid-utf8"),
        ]
        for raw, error in cases:
            with self.subTest(error=error):
                with open(self.path, "wb") as fh:
                    fh.write(raw)
                snapshot = capture_database_snapshot(self.path)
                self.assertEqual(snapshot.state, "unreadable")
                self.assertEqual(snapshot.validation_errors, (error,))
                self.assertEqual(snapshot.content_hash,
                                 hashlib.sha256(raw).hexdigest())
                self.assertIsNone(load_database_snapshot(snapshot))

    def test_legacy_loader_and_state_contracts_remain(self):
        self.assertEqual(db_file_state(self.path), "absent")
        self.assertIsNone(load_database(self.path))

        self._write(_payload())
        self.assertEqual(db_file_state(self.path), "ok")
        self.assertEqual(set(load_database(self.path)["gradebook"].students),
                         {"alice"})

        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("malformed")
        self.assertEqual(db_file_state(self.path), "unreadable")
        self.assertIsNone(load_database(self.path))


if __name__ == "__main__":
    unittest.main()
