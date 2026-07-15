"""Engine tests for Phase-5 fail-closed database validation."""

import copy
import json
import os
import tempfile
import unittest
import uuid
from unittest import mock

from engine import (
    Assignment,
    DatabaseConcurrencyError,
    DatabaseValidationError,
    Gradebook,
    capture_database_snapshot,
    database_write_token,
    load_database_snapshot,
    save_database_checked,
    validate_database_payload,
    write_conflict_recovery,
)


def _payload(version=1):
    payload = {
        "version": version,
        "saved_at": "2026-07-15T10:00:00",
        "gradebook": {
            "students": [{
                "student_id": "private-student-id",
                "name": "Private Student Name",
                "scores": [{
                    "criterion": "A",
                    "value": 6,
                    "timestamp": "2026-07-15T09:00:00",
                    "assignment": "Private Assignment",
                    "comment": "Private teacher comment",
                }],
                "exam_results": [],
            }],
            "assignments": [{"name": "Private Assignment", "criteria": ["A"]}],
        },
        "session": {
            "rosters": {"Private Class": [{"key": "private-student-id"}]},
            "comments_by_term": {
                "Term 1": {"private-student-id": "Private overall comment"}},
        },
    }
    if version == 2:
        payload.update({"database_id": str(uuid.uuid4()), "generation": 3})
    return payload


class DatabaseValidationTests(unittest.TestCase):
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

    def test_supported_versions_optional_fields_and_additive_fields_load(self):
        for version in (1, 2):
            with self.subTest(version=version):
                payload = _payload(version)
                payload["future_addition"] = {"kept_opaque": True}
                payload["gradebook"]["students"][0].pop("exam_results")
                self._write(payload)
                snapshot = capture_database_snapshot(self.path)
                self.assertEqual(snapshot.state, "ok")
                self.assertEqual(snapshot.validation_issues, ())
                loaded = load_database_snapshot(snapshot)
                self.assertIn("private-student-id", loaded["gradebook"].students)

    def test_invalid_and_future_versions_are_distinct_invalid_snapshots(self):
        cases = [
            (None, "invalid-schema-version"),
            (True, "invalid-schema-version"),
            (0, "unsupported-schema-version"),
            (3, "unsupported-schema-version"),
        ]
        for version, code in cases:
            with self.subTest(version=version):
                payload = _payload()
                payload["version"] = version
                self._write(payload)
                snapshot = capture_database_snapshot(self.path)
                self.assertEqual(snapshot.state, "invalid")
                self.assertIn(code, snapshot.validation_errors)
                self.assertIsNone(snapshot.mass)
                self.assertIsNone(load_database_snapshot(snapshot))

        missing_timestamp = _payload(2)
        missing_timestamp.pop("saved_at")
        self.assertIn("missing-required-field",
                      {issue.code for issue in
                       validate_database_payload(missing_timestamp)})

    def test_malformed_loss_critical_records_report_structural_paths(self):
        mutations = [
            (lambda p: p["gradebook"]["students"][0].update(
                {"scores": [{"criterion": "A", "value": "6",
                             "timestamp": "not-a-date"}]}),
             {"gradebook.students[0].scores[0].value",
              "gradebook.students[0].scores[0].timestamp"}),
            (lambda p: p["gradebook"]["assignments"][0].update(
                {"criteria": ["Z"]}),
             {"gradebook.assignments[0].criteria[0]"}),
            (lambda p: p["session"].update(
                {"comments_by_term": {"Term 1": {"student": 17}}}),
             {"session.comments_by_term.*.*"}),
            (lambda p: p["session"].update(
                {"rosters": {"Class": [{"key": 17}]}}),
             {"session.rosters.*[0].key"}),
        ]
        for mutate, expected_paths in mutations:
            payload = _payload(2)
            mutate(payload)
            issues = validate_database_payload(payload)
            self.assertTrue(expected_paths.issubset({issue.path for issue in issues}))

    def test_duplicate_lossy_identities_are_rejected(self):
        payload = _payload(2)
        payload["gradebook"]["students"].append(
            copy.deepcopy(payload["gradebook"]["students"][0]))
        payload["gradebook"]["students"][0]["exam_results"] = [
            {"assignment": "Exam", "questions": {}},
            {"assignment": "Exam", "questions": {}},
        ]
        codes = {issue.code for issue in validate_database_payload(payload)}
        self.assertIn("duplicate-student-id", codes)
        self.assertIn("duplicate-exam-result", codes)

    def test_invalid_neighbor_prevents_any_partial_hydration(self):
        payload = _payload(2)
        payload["gradebook"]["students"].append({
            "student_id": "other", "scores": [{"criterion": "A"}]})
        self._write(payload)
        snapshot = capture_database_snapshot(self.path)
        self.assertEqual(snapshot.state, "invalid")
        self.assertIsNone(load_database_snapshot(snapshot))

    def test_diagnostics_never_contain_record_values(self):
        payload = _payload(2)
        payload["gradebook"]["students"][0]["scores"][0]["value"] = \
            "Private invalid grade value"
        issues = validate_database_payload(payload)
        rendered = " ".join(f"{issue.path}:{issue.code}" for issue in issues)
        for private in ("Private Student Name", "private-student-id",
                        "Private Assignment", "Private teacher comment",
                        "Private invalid grade value"):
            self.assertNotIn(private, rendered)

    def test_captured_validation_and_hydration_ignore_live_replacement(self):
        invalid = _payload(2)
        invalid["gradebook"]["students"][0]["scores"][0]["value"] = "6"
        self._write(invalid)
        captured = capture_database_snapshot(self.path)
        self._write(_payload(2))
        self.assertEqual(captured.state, "invalid")
        self.assertIsNone(load_database_snapshot(captured))

    def test_invalid_observed_file_blocks_write_and_pending_recovery_is_valid(self):
        absent = database_write_token(capture_database_snapshot(self.path))
        gradebook = Gradebook()
        gradebook.get_or_create("student", "Student")
        gradebook.assignments.append(Assignment("Assignment", ["A"]))
        created = save_database_checked(self.path, gradebook, {}, absent)
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["gradebook"]["students"][0]["scores"] = [{"criterion": "A"}]
        self._write(payload)
        invalid_bytes = capture_database_snapshot(self.path).raw_bytes

        with self.assertRaises(DatabaseConcurrencyError) as caught:
            save_database_checked(self.path, gradebook, {}, created.token)
        self.assertEqual(caught.exception.observed.state, "invalid")
        recovery = write_conflict_recovery(
            self.path, gradebook, {}, caught.exception.expected,
            caught.exception.observed, reason="database-validation-failed")
        self.assertEqual(capture_database_snapshot(self.path).raw_bytes,
                         invalid_bytes)
        self.assertIsNotNone(load_database_snapshot(
            capture_database_snapshot(recovery.path)))

    def test_invalid_outgoing_session_changes_no_shared_file_or_backup(self):
        token = database_write_token(capture_database_snapshot(self.path))
        gradebook = Gradebook()
        created = save_database_checked(self.path, gradebook, {}, token)
        before = capture_database_snapshot(self.path).raw_bytes
        before_names = set(os.listdir(self.tmp.name))
        with self.assertRaises(DatabaseValidationError):
            save_database_checked(
                self.path, gradebook,
                {"comments_by_term": {"Term 1": {"student": 123}}},
                created.token, require_session_snapshot=True)
        self.assertEqual(capture_database_snapshot(self.path).raw_bytes, before)
        self.assertEqual(set(os.listdir(self.tmp.name)), before_names)


if __name__ == "__main__":
    unittest.main()
