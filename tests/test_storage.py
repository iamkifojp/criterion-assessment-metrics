"""Session folders and the save-safety rules (PLAN.md §4).

Every test runs with CAM2_APP_DATA pointing at a temp folder, so nothing is
written to the real app-data folder.

Run:  python -m unittest tests.test_storage
"""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from engine import grading_summary, model, storage
from engine.errors import UserError


class StorageTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.app_data = os.path.join(self.root, "appdata")
        patcher = mock.patch.dict(os.environ, {"CAM2_APP_DATA": self.app_data})
        patcher.start()
        self.addCleanup(patcher.stop)
        sleeper = mock.patch.object(storage.time, "sleep")
        sleeper.start()
        self.addCleanup(sleeper.stop)
        self.folder = os.path.join(self.root, "Y8 Midterm")

    def tearDown(self):
        self.tmp.cleanup()

    def new_session(self):
        session, config, grades = storage.create_session(self.folder, "Y8 Midterm")
        config["students"] = [{"id": f"s{i:03d}"} for i in range(1, 13)]
        config["questions"] = [{"id": "q1", "label": "Q1", "max": 5},
                               {"id": "q2", "label": "Q2", "max": 5}]
        config["mode"] = "marks"
        config = session.config_file.save(config)
        return session, config, grades

    def fill(self, config, grades):
        for s in config["students"]:
            for q in config["questions"]:
                grading_summary.set_grade(config, grades, s["id"], q["id"], 3, "ok")
        return grades


class SessionLifecycleTests(StorageTestCase):
    def test_create_and_reopen(self):
        session, config, grades = self.new_session()
        self.assertEqual(config["generation"], 2)
        self.assertEqual(config["session_id"], grades["session_id"])
        _, config2, grades2 = storage.open_session(self.folder)
        self.assertEqual(config2["exam_name"], "Y8 Midterm")
        self.assertEqual(grades2["generation"], 1)
        self.assertTrue(config2["saved_by"])

    def test_refuses_to_start_over_an_existing_session(self):
        self.new_session()
        with self.assertRaises(UserError) as ctx:
            storage.create_session(self.folder, "Again")
        self.assertEqual(ctx.exception.code, "session_exists")

    def test_open_errors_are_specific(self):
        os.makedirs(os.path.join(self.root, "empty"))
        with self.assertRaises(UserError) as ctx:
            storage.open_session(os.path.join(self.root, "empty"))
        self.assertEqual(ctx.exception.code, "not_a_session_folder")
        with self.assertRaises(storage.FolderUnavailable):
            storage.open_session(os.path.join(self.root, "missing"))

    def test_damaged_and_newer_files(self):
        self.new_session()
        path = os.path.join(self.folder, storage.GRADES_FILE)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        with self.assertRaises(UserError) as ctx:
            storage.open_session(self.folder)
        self.assertEqual(ctx.exception.code, "file_damaged")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"format": model.GRADES_FORMAT, "version": 99}, fh)
        with self.assertRaises(UserError) as ctx:
            storage.open_session(self.folder)
        self.assertEqual(ctx.exception.code, "file_from_newer_version")

    def test_exam_name_is_required(self):
        with self.assertRaises(UserError):
            storage.create_session(self.folder, "  ")


class SafeSaveTests(StorageTestCase):
    def test_save_increments_generation_and_verifies(self):
        session, config, grades = self.new_session()
        saved = session.grades_file.save(self.fill(config, grades))
        self.assertEqual(saved["generation"], 2)
        with open(session.grades_file.path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["generation"], 2)

    def test_changed_on_another_computer_is_not_overwritten(self):
        self.new_session()
        here, _, grades_here = storage.open_session(self.folder)
        there, config_there, grades_there = storage.open_session(self.folder)
        there.grades_file.save(self.fill(config_there, grades_there))
        with self.assertRaises(storage.ChangedElsewhere):
            here.grades_file.save(grades_here)

    def test_cloud_conflict_copies_stop_the_save(self):
        session, config, grades = self.new_session()
        for name in ("grades-LAPTOP-123.json", "grades (1).json",
                     "grades (Kim's conflicted copy 2026-10-30).json", "grades 2.json"):
            path = os.path.join(self.folder, name)
            with open(path, "w") as fh:
                fh.write("{}")
            with self.assertRaises(storage.ConflictCopiesFound) as ctx:
                session.grades_file.save(grades)
            self.assertEqual(ctx.exception.files, (os.path.abspath(path),))
            os.remove(path)
        session.grades_file.save(grades)

    def test_own_files_are_not_conflicts(self):
        session, config, grades = self.new_session()
        for name in ("gradesheet.json", ".cam2-abc.tmp", "grades.json.tmp"):
            open(os.path.join(self.folder, name), "w").close()
        session.grades_file.save(grades)
        session.grades_file.save(grades)          # second save makes a backup
        self.assertEqual(storage.find_conflict_copies(session.grades_file.path), ())

    def test_wipe_guard(self):
        session, config, grades = self.new_session()
        session.grades_file.save(self.fill(config, grades))
        wiped = dict(grades, grades={})
        with self.assertRaises(storage.WipeBlocked):
            session.grades_file.save(wiped)
        session.grades_file.save(wiped, allow_shrink=True)

    def test_daily_backup_keeps_fourteen(self):
        session, config, grades = self.new_session()
        backups = os.path.join(self.folder, storage.BACKUP_DIR)
        os.makedirs(backups, exist_ok=True)
        for day in range(1, 21):
            with open(os.path.join(backups, f"grades.json.bak-202601{day:02d}"), "w") as fh:
                fh.write("{}")
        session.grades_file.save(grades)
        names = sorted(os.listdir(backups))
        today = f"grades.json.bak-{datetime.now():%Y%m%d}"
        mine = [n for n in names if n.startswith("grades.json.bak-")]
        self.assertIn(today, mine)
        self.assertEqual(len(mine), storage.BACKUP_KEEP)

    def test_file_deleted_under_us(self):
        session, config, grades = self.new_session()
        os.remove(session.grades_file.path)
        with self.assertRaises(storage.FileMissing):
            session.grades_file.save(grades)

    def test_sync_lock_is_retried(self):
        session, config, grades = self.new_session()
        real_replace = os.replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] <= 2 and dst == session.grades_file.path:
                raise PermissionError("locked by OneDrive")
            return real_replace(src, dst)

        with mock.patch.object(storage.os, "replace", side_effect=flaky):
            session.grades_file.save(grades)
        self.assertGreaterEqual(calls["n"], 3)

    def test_permanent_lock_fails_loudly(self):
        session, config, grades = self.new_session()
        with mock.patch.object(storage.os, "replace",
                               side_effect=PermissionError("locked")):
            with self.assertRaises(storage.WriteFailed):
                session.grades_file.save(grades)

    def test_unverified_write_is_reported(self):
        session, config, grades = self.new_session()
        real = storage.atomic_write

        def corrupting(path, raw):
            real(path, raw + b" " if path == session.grades_file.path else raw)

        with mock.patch.object(storage, "atomic_write", side_effect=corrupting):
            with self.assertRaises(storage.WriteNotVerified):
                session.grades_file.save(grades)


class EmergencyCopyTests(StorageTestCase):
    def test_work_survives_a_pulled_usb_stick(self):
        session, config, grades = self.new_session()
        grading_summary.set_grade(config, grades, "s001", "q1", 4)
        moved = self.folder + " (unplugged)"
        os.rename(self.folder, moved)
        with self.assertRaises(storage.FolderUnavailable):
            session.grades_file.save(grades)
        os.rename(moved, self.folder)

        reopened, _, _ = storage.open_session(self.folder)
        rescued = reopened.grades_file.newer_emergency_copy()
        self.assertIsNotNone(rescued)
        self.assertEqual(rescued["grades"]["s001"]["q1"]["value"], 4)
        reopened.grades_file.save(rescued)
        self.assertIsNone(reopened.grades_file.newer_emergency_copy())

    def test_emergency_copy_lives_in_app_data(self):
        session, config, grades = self.new_session()
        self.assertTrue(session.grades_file.emergency_path().startswith(self.app_data))
        self.assertTrue(os.path.isfile(session.grades_file.emergency_path()))


class LockTests(StorageTestCase):
    def test_claim_and_release(self):
        os.makedirs(self.folder)
        self.assertIsNone(storage.claim_lock(self.folder))
        self.assertEqual(storage.read_lock(self.folder)["instance"], storage.INSTANCE_ID)
        storage.release_lock(self.folder)
        self.assertIsNone(storage.read_lock(self.folder))

    def test_fresh_lock_from_another_computer_is_reported(self):
        os.makedirs(self.folder)
        now = datetime.now(timezone.utc)
        other = {"computer": "LAPTOP-123", "instance": "other",
                 "since": now.isoformat(), "heartbeat": now.isoformat()}
        with open(os.path.join(self.folder, storage.LOCK_FILE), "w") as fh:
            json.dump(other, fh)
        self.assertEqual(storage.claim_lock(self.folder)["computer"], "LAPTOP-123")
        storage.release_lock(self.folder)                 # not ours: left alone
        self.assertIsNotNone(storage.read_lock(self.folder))
        self.assertIsNone(storage.claim_lock(self.folder, force=True))

    def test_lock_left_by_this_computer_is_stale(self):
        """E.g. CAM2 crashed or was stopped: one CAM2 runs per computer."""
        os.makedirs(self.folder)
        now = datetime.now(timezone.utc).isoformat()
        with open(os.path.join(self.folder, storage.LOCK_FILE), "w") as fh:
            json.dump({"computer": storage.computer_name(), "instance": "crashed",
                       "since": now, "heartbeat": now}, fh)
        self.assertIsNone(storage.other_lock_holder(self.folder))
        self.assertIsNone(storage.claim_lock(self.folder))
        self.assertEqual(storage.read_lock(self.folder)["instance"], storage.INSTANCE_ID)

    def test_stale_lock_is_taken_over(self):
        os.makedirs(self.folder)
        old = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        with open(os.path.join(self.folder, storage.LOCK_FILE), "w") as fh:
            json.dump({"computer": "X", "instance": "other", "heartbeat": old}, fh)
        self.assertIsNone(storage.claim_lock(self.folder))


class AppDataTests(StorageTestCase):
    def test_recent_sessions(self):
        for i in range(12):
            folder = os.path.join(self.root, f"exam{i}")
            storage.remember_session(folder, f"Exam {i}")
        recent = storage.list_recent()
        self.assertEqual(len(recent), storage.RECENT_MAX)
        self.assertEqual(recent[0]["exam_name"], "Exam 11")
        self.assertFalse(recent[0]["available"])
        storage.remember_session(os.path.join(self.root, "exam5"), "Exam 5", graded=3, total=10)
        recent = storage.list_recent()
        self.assertEqual(recent[0]["exam_name"], "Exam 5")
        self.assertEqual(sum(r["exam_name"] == "Exam 5" for r in recent), 1)
        storage.forget_session(os.path.join(self.root, "exam5"))
        self.assertNotIn("Exam 5", [r["exam_name"] for r in storage.list_recent()])

    def test_recent_marks_available_sessions(self):
        self.new_session()
        storage.remember_session(self.folder, "Y8 Midterm")
        self.assertTrue(storage.list_recent()[0]["available"])

    def test_prefs(self):
        self.assertEqual(storage.get_pref("language", "en"), "en")
        storage.set_pref("language", "ja")
        self.assertEqual(storage.get_pref("language"), "ja")

    def test_app_data_override(self):
        self.assertEqual(storage.app_data_dir(), os.path.abspath(self.app_data))


class PathTests(StorageTestCase):
    def test_relative_paths_stay_inside(self):
        os.makedirs(self.folder)
        inside = os.path.join(self.folder, "scans", "a.pdf")
        self.assertEqual(storage.relative_path(self.folder, inside), "scans/a.pdf")
        self.assertEqual(storage.resolve_path(self.folder, "scans/a.pdf"),
                         os.path.abspath(inside))
        with self.assertRaises(UserError):
            storage.relative_path(self.folder, os.path.join(self.root, "x.pdf"))
        with self.assertRaises(UserError):
            storage.resolve_path(self.folder, "../x.pdf")

    def test_moved_session_still_opens(self):
        self.new_session()
        moved = os.path.join(self.root, "elsewhere")
        shutil.move(self.folder, moved)
        session, config, _ = storage.open_session(moved)
        self.assertEqual(config["exam_name"], "Y8 Midterm")
        self.assertEqual(session.path("scans/a.pdf"), os.path.join(moved, "scans", "a.pdf"))

    def test_default_session_folder(self):
        docs = os.path.join(self.root, "Documents")
        first = storage.default_session_folder("Y8: Science?", docs)
        self.assertEqual(first, os.path.join(docs, "CAM2 Exam Grading Sessions", "Y8_ Science_"))
        os.makedirs(first)
        open(os.path.join(first, "x"), "w").close()
        self.assertTrue(storage.default_session_folder("Y8: Science?", docs).endswith("(2)"))

    def test_unwritable_folder(self):
        blocker = os.path.join(self.root, "file")
        open(blocker, "w").close()
        with self.assertRaises(UserError) as ctx:
            storage.check_writable(os.path.join(blocker, "sub"))
        self.assertEqual(ctx.exception.code, "folder_not_writable")


if __name__ == "__main__":
    unittest.main()
