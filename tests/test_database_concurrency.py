"""Isolated Phase-2 optimistic-concurrency and recovery tests."""

import json
import os
import tempfile
import unittest
from unittest import mock

from engine import (
    Assignment,
    DatabaseConcurrencyError,
    DatabaseLockTimeout,
    DatabaseShrinkError,
    DatabaseWriteVerificationError,
    Gradebook,
    capture_database_snapshot,
    database_write_token,
    load_database_snapshot,
    replace_database_checked,
    save_database_checked,
    write_conflict_recovery,
)
from engine.persistence import database_write_lock


def _gradebook(count=1):
    gradebook = Gradebook()
    gradebook.assignments = [
        Assignment(name=f"Assignment {index}", criteria=["A"])
        for index in range(count)
    ]
    gradebook.get_or_create("student", "Student")
    return gradebook


def _legacy_payload(count=1):
    return {
        "version": 1,
        "saved_at": "2026-07-15T10:00:00",
        "gradebook": {
            "students": [{"student_id": "student", "name": "Student",
                          "scores": [], "exam_results": []}],
            "assignments": [
                {"name": f"Assignment {index}", "criteria": ["A"]}
                for index in range(count)
            ],
        },
        "session": {"rosters": {"Class": [{"key": "student"}]}},
    }


class DatabaseConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        self.env.start()
        self.path = os.path.join(self.tmp.name, "acm_database.json")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def _write_json(self, payload):
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)

    def test_legacy_upgrade_is_backed_up_verified_and_only_one_writer_wins(self):
        self._write_json(_legacy_payload())
        loaded = capture_database_snapshot(self.path)
        token_a = database_write_token(loaded)
        token_b = database_write_token(loaded)

        result = save_database_checked(
            self.path, _gradebook(), {"rosters": {}}, token_a)

        self.assertEqual(result.token.schema_version, 2)
        self.assertEqual(result.token.generation, 1)
        self.assertTrue(result.pre_upgrade_backup)
        backup = capture_database_snapshot(result.pre_upgrade_backup)
        self.assertEqual(backup.content_hash, loaded.content_hash)
        with self.assertRaises(DatabaseConcurrencyError):
            save_database_checked(
                self.path, _gradebook(2), {"rosters": {}}, token_b)

    def test_two_sessions_preserve_winner_and_verify_loser_recovery(self):
        absent = database_write_token(capture_database_snapshot(self.path))
        first = save_database_checked(
            self.path, _gradebook(), {"marker": "initial"}, absent)
        token_a = first.token
        token_b = first.token

        winner = save_database_checked(
            self.path, _gradebook(2), {"marker": "winner"}, token_a)
        winner_bytes = capture_database_snapshot(self.path).raw_bytes
        pending = _gradebook(4)  # larger stale payload must still be rejected
        with self.assertRaises(DatabaseConcurrencyError) as caught:
            save_database_checked(
                self.path, pending, {"marker": "pending"}, token_b)

        recovery = write_conflict_recovery(
            self.path, pending, {"marker": "pending"},
            caught.exception.expected, caught.exception.observed)
        self.assertEqual(capture_database_snapshot(self.path).raw_bytes,
                         winner_bytes)
        recovered = load_database_snapshot(
            capture_database_snapshot(recovery.path))
        self.assertEqual(len(recovered["gradebook"].assignments), 4)
        self.assertEqual(recovered["session"]["marker"], "pending")
        self.assertEqual(winner.token.generation, 2)

    def test_same_generation_with_changed_hash_and_changed_identity_conflict(self):
        absent = database_write_token(capture_database_snapshot(self.path))
        result = save_database_checked(
            self.path, _gradebook(), {}, absent)
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["session"]["tampered"] = True
        self._write_json(payload)
        with self.assertRaises(DatabaseConcurrencyError) as caught:
            save_database_checked(self.path, _gradebook(), {}, result.token)
        self.assertEqual(caught.exception.reason,
                         "database-content-changed-without-generation")

        payload["database_id"] = "00000000-0000-4000-8000-000000000001"
        self._write_json(payload)
        with self.assertRaises(DatabaseConcurrencyError) as caught:
            save_database_checked(self.path, _gradebook(), {}, result.token)
        self.assertEqual(caught.exception.reason, "database-identity-changed")

    def test_repeated_session_saves_advance_exactly_once(self):
        token = database_write_token(capture_database_snapshot(self.path))
        generations = []
        for count in (1, 2, 3):
            result = save_database_checked(
                self.path, _gradebook(count), {}, token)
            token = result.token
            generations.append(token.generation)
        self.assertEqual(generations, [1, 2, 3])

    def test_two_absent_tokens_cannot_both_create(self):
        token_a = database_write_token(capture_database_snapshot(self.path))
        token_b = database_write_token(capture_database_snapshot(self.path))
        save_database_checked(self.path, _gradebook(), {}, token_a)
        with self.assertRaises(DatabaseConcurrencyError):
            save_database_checked(self.path, _gradebook(), {}, token_b)

    def test_missing_unreadable_and_invalid_v2_metadata_are_conflicts(self):
        token = database_write_token(capture_database_snapshot(self.path))
        created = save_database_checked(self.path, _gradebook(), {}, token)
        os.remove(self.path)
        with self.assertRaises(DatabaseConcurrencyError):
            save_database_checked(self.path, _gradebook(), {}, created.token)

        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("malformed")
        with self.assertRaises(DatabaseConcurrencyError):
            save_database_checked(self.path, _gradebook(), {}, created.token)

        invalid = _legacy_payload()
        invalid.update({"version": 2, "database_id": "bad", "generation": 1})
        self._write_json(invalid)
        with self.assertRaises(DatabaseConcurrencyError) as caught:
            save_database_checked(self.path, _gradebook(), {}, created.token)
        self.assertEqual(caught.exception.reason,
                         "invalid-concurrency-metadata")

    def test_shrink_tripwire_and_allow_shrink_do_not_bypass_concurrency(self):
        token = database_write_token(capture_database_snapshot(self.path))
        rich = save_database_checked(self.path, _gradebook(12), {}, token)
        with self.assertRaises(DatabaseShrinkError):
            save_database_checked(self.path, _gradebook(1), {}, rich.token)
        shrunk = save_database_checked(
            self.path, _gradebook(1), {}, rich.token, allow_shrink=True)
        stale = rich.token
        with self.assertRaises(DatabaseConcurrencyError):
            save_database_checked(
                self.path, _gradebook(20), {}, stale, allow_shrink=True)
        self.assertEqual(shrunk.token.generation, 2)

    def test_local_lock_times_out_and_releases(self):
        token = database_write_token(capture_database_snapshot(self.path))
        with database_write_lock(self.path):
            with self.assertRaises(DatabaseLockTimeout):
                save_database_checked(
                    self.path, _gradebook(), {}, token, lock_timeout=0.05)
        result = save_database_checked(self.path, _gradebook(), {}, token)
        self.assertEqual(result.token.generation, 1)

    def test_failed_write_verification_does_not_return_a_new_token(self):
        token = database_write_token(capture_database_snapshot(self.path))
        with mock.patch("engine.persistence._atomic_write_bytes"):
            with self.assertRaises(DatabaseWriteVerificationError):
                save_database_checked(self.path, _gradebook(), {}, token)
        self.assertEqual(capture_database_snapshot(self.path).state, "absent")

    def test_recovery_verification_failure_is_reported(self):
        token = database_write_token(capture_database_snapshot(self.path))
        observed = capture_database_snapshot(self.path)
        with mock.patch("engine.persistence.load_database_snapshot",
                        return_value=None):
            with self.assertRaises(DatabaseWriteVerificationError):
                write_conflict_recovery(
                    self.path, _gradebook(), {}, token, observed)

    def test_explicit_replacement_uses_new_identity_and_verified_backup(self):
        token = database_write_token(capture_database_snapshot(self.path))
        original = save_database_checked(self.path, _gradebook(), {}, token)
        original_bytes = capture_database_snapshot(self.path).raw_bytes
        replacement = replace_database_checked(
            self.path, _gradebook(3), {"replacement": True})
        self.assertNotEqual(replacement.token.database_id,
                            original.token.database_id)
        self.assertEqual(replacement.token.generation, 1)
        self.assertEqual(
            capture_database_snapshot(replacement.pre_upgrade_backup).raw_bytes,
            original_bytes)


if __name__ == "__main__":
    unittest.main()
