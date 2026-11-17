"""Two classes may hold an assignment of the same name without sharing it.

Fictional fixtures only. The database path is forced into a temp folder
(``CAM_DB_PATH``) and ``persist`` is stubbed, so no device preferences or real
database are opened.
"""
from copy import deepcopy
from datetime import date, datetime
import glob
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import app
from engine.models import (Assignment, Criterion, CriterionScore, ExamResult,
                           Gradebook, Student)
from engine.persistence import (ASSIGNMENT_STATE_KEY, capture_database_snapshot,
                                database_write_token, expand_flat_assignment_state,
                                load_database, persistent_content_fingerprint,
                                save_database, save_database_checked,
                                validate_database_payload, build_payload)
from engine.reporting import ReportMember, ReportScope, source_snapshot

A, B = "8A", "8B"
NAME = "Drawing"


class ClassScopedBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        env = mock.patch.dict(os.environ, {"CAM_DB_PATH": self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.original_st = app.st
        app.st = SimpleNamespace(session_state={"db_loaded": True})
        self.addCleanup(setattr, app, "st", self.original_st)
        with mock.patch.object(app, "load_prefs",
                               return_value=dict(app.DEFAULT_PREFS)):
            app.init_state()
        for target in ("persist", "_retire_cam2_sessions"):
            patcher = mock.patch.object(app, target)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.ss = app.st.session_state
        self.term = app.TERMS[0]
        self.ss.update(
            active_class=A, active_term=self.term,
            classes=[dict(name=c, grade="Year 8", myp_year="3", subject="Arts",
                          master_dir="") for c in (A, B)],
            rosters={A: [dict(key="a1", name="Abe Rin")],
                     B: [dict(key="b1", name="Baba Sho")]})
        book = app.gb()
        for cls, sid, value in ((A, "a1", 5), (B, "b1", 7)):
            book.students[sid] = Student(sid, sid)
            book.assignments.append(Assignment(
                NAME, ["A"], class_name=cls, term=self.term,
                ingested_at=datetime(2026, 4, 1)))
            book.students[sid].add_score(CriterionScore(
                Criterion.A, value, datetime(2026, 4, 1), assignment=NAME,
                source=f"csv:{NAME}"))
        app.ensure_class_context()
        app.ensure_term_context()

    def switch(self, cls):
        self.ss["active_class"] = cls
        app.ensure_class_context()
        app.ensure_term_context()

    def values(self, cls):
        return sorted(sc.value for _, sc in app.scores_for_assignment(NAME, cls))

    def records(self, cls):
        return [a for a in app.gb().assignments if a.class_name == cls]


class NameRuleTests(ClassScopedBase):
    def test_same_name_allowed_in_another_class(self):
        app.gb().assignments = self.records(A)
        self.assertEqual(app.assignment_name_problem(NAME, B), "")

    def test_duplicate_within_a_class_refused(self):
        self.assertIn("already exists in this class",
                      app.assignment_name_problem(NAME, A))

    def test_refused_when_a_student_is_in_both_classes(self):
        app.gb().assignments = self.records(A)
        self.ss["rosters"][B].append(dict(key="a1", name="Abe Rin"))
        problem = app.assignment_name_problem(NAME, B)
        self.assertIn(A, problem)
        self.assertIn("both classes", problem)

    def test_rename_onto_another_classes_name(self):
        app.gb().assignments.append(Assignment("Sketch", ["B"], class_name=B,
                                               term=self.term))
        self.switch(B)
        self.assertFalse(app.rename_assignment("Sketch", NAME))  # B has it
        self.switch(A)
        app.gb().assignments.append(Assignment("Collage", ["B"], class_name=A,
                                               term=self.term))
        self.assertTrue(app.rename_assignment("Collage", "Sketch"))  # only B had it
        self.assertEqual({a.class_name for a in app.gb().assignments
                          if a.name == "Sketch"}, {A, B})


class IsolationTests(ClassScopedBase):
    def test_scores_are_split_by_class(self):
        self.assertEqual(self.values(A), [5])
        self.assertEqual(self.values(B), [7])
        rows = app.assignment_table()
        self.assertEqual([r["name"] for r in rows], [NAME])

    def test_archive_and_restore_stay_in_one_class(self):
        app.archive_assignment(NAME)
        self.assertEqual(app.assignment_table(), [])
        self.assertFalse(app.assignment_on(NAME))
        self.switch(B)
        self.assertEqual([r["name"] for r in app.assignment_table()], [NAME])
        self.assertTrue(app.assignment_on(NAME))
        self.assertEqual(app.archived_for_active(), [])
        self.switch(A)
        self.assertEqual(app.archived_for_active(), [NAME])
        app.restore_assignment(NAME)
        self.assertTrue(app.assignment_on(NAME))

    def test_on_off_stays_in_one_class(self):
        app.term_active_map()[NAME] = False
        self.assertFalse(app.assignment_on(NAME))
        self.switch(B)
        self.assertTrue(app.assignment_on(NAME))
        app.sync_active_into_scores()
        self.assertTrue(app.gb().students["b1"].scores["A"][0].include_in_report)

    def test_date_override_stays_in_one_class(self):
        app.apply_date_override(NAME, date(2026, 6, 9))
        self.assertEqual(app.gb().students["a1"].scores["A"][0].timestamp.date(),
                         date(2026, 6, 9))
        self.assertEqual(app.gb().students["b1"].scores["A"][0].timestamp.date(),
                         date(2026, 4, 1))
        self.switch(B)
        self.assertNotIn(NAME, self.ss["date_override"])
        self.assertEqual(app.assignment_table()[0]["date"].date(), date(2026, 4, 1))

    def test_rename_stays_in_one_class(self):
        self.ss["late_flags"].update({f"a1||{NAME}||A": True, f"b1||{NAME}||A": True})
        self.ss["excused_flags"].update({f"a1||{NAME}": True, f"b1||{NAME}": True})
        app.gb().students["a1"].exam_results[NAME] = ExamResult(NAME, 3, 5)
        app.gb().students["b1"].exam_results[NAME] = ExamResult(NAME, 4, 5)
        self.assertTrue(app.rename_assignment(NAME, "Line work"))
        self.assertEqual([a.name for a in self.records(A)], ["Line work"])
        self.assertEqual([a.name for a in self.records(B)], [NAME])
        self.assertEqual(app.gb().students["a1"].scores["A"][0].assignment, "Line work")
        self.assertEqual(app.gb().students["b1"].scores["A"][0].assignment, NAME)
        self.assertEqual(list(app.gb().students["a1"].exam_results), ["Line work"])
        self.assertEqual(list(app.gb().students["b1"].exam_results), [NAME])
        self.assertIn("a1||Line work||A", self.ss["late_flags"])
        self.assertIn(f"b1||{NAME}||A", self.ss["late_flags"])
        self.assertIn("a1||Line work", self.ss["excused_flags"])
        self.assertIn(f"b1||{NAME}", self.ss["excused_flags"])

    def test_permanent_delete_stays_in_one_class(self):
        app.gb().students["b1"].exam_results[NAME] = ExamResult(NAME, 4, 5)
        self.ss["late_flags"][f"b1||{NAME}||A"] = True
        self.switch(B)
        app.archive_assignment(NAME)        # B's own setting must survive A's delete
        self.switch(A)
        app.delete_assignment_permanent(NAME)
        self.assertEqual(self.records(A), [])
        self.assertEqual(len(self.records(B)), 1)
        self.assertEqual(app.gb().students["a1"].scores["A"], [])
        self.assertEqual(self.values(B), [7])
        self.assertIn(NAME, app.gb().students["b1"].exam_results)
        self.assertIn(f"b1||{NAME}||A", self.ss["late_flags"])
        self.switch(B)
        self.assertEqual(app.archived_for_active(), [NAME])

    def test_resync_purge_replaces_one_classes_scores_only(self):
        app._purge_assignment_in_class(NAME, A)
        self.assertEqual(self.records(A), [])
        self.assertEqual(app.gb().students["a1"].scores["A"], [])
        self.assertEqual(self.values(B), [7])

    def test_exam_results_are_split_by_class(self):
        for a in app.gb().assignments:
            a.is_exam = True
        app.gb().students["a1"].exam_results[NAME] = ExamResult(NAME, 3, 5)
        app.gb().students["b1"].exam_results[NAME] = ExamResult(NAME, 4, 5)
        with mock.patch.object(app, "student_label", side_effect=lambda s: s.student_id):
            self.assertEqual([s.student_id for s, _ in app._exam_results_for(NAME)], ["a1"])
            self.switch(B)
            self.assertEqual([s.student_id for s, _ in app._exam_results_for(NAME)], ["b1"])

    def test_sync_writes_to_the_synced_class_not_the_one_on_screen(self):
        app.class_active_map(B)[NAME] = False
        app.class_archived(B).add(NAME)
        self.assertTrue(app.assignment_on(NAME))
        self.assertEqual(app.archived_for_active(), [])
        self.switch(B)
        self.assertFalse(app.assignment_on(NAME))
        self.assertEqual(app.archived_for_active(), [NAME])

    def test_class_rename_and_delete_carry_their_own_settings(self):
        app.archive_assignment(NAME)
        with mock.patch.object(app, "class_data_dir",
                               side_effect=lambda cls: os.path.join(self.tmp.name, cls)), \
                mock.patch.object(app, "_mark_teacher_input_deleted"):
            self.assertTrue(app.rename_class(A, "8C"))
            self.assertEqual(self.ss["active_class"], "8C")
            self.assertEqual(app.archived_for_active(), [NAME])
            self.assertTrue(app.delete_class("8C"))
        self.assertEqual(self.ss["active_class"], B)
        self.assertEqual(set(self.ss["assignment_state"]), {B})
        self.assertEqual(app.archived_for_active(), [])
        self.assertEqual(self.values(B), [7])


class SaveLoadTests(ClassScopedBase):
    def legacy_session(self):
        """A session as CAM saved it before names were class-scoped."""
        session = deepcopy(app.build_session_payload())
        session.pop(ASSIGNMENT_STATE_KEY)
        session["archived"] = [NAME]
        session["date_override"] = {NAME: "2026-06-09"}
        session["active_by_term"] = {self.term: {NAME: False}, app.TERMS[1]: {}}
        session["active"] = {NAME: False}
        return session

    def reload(self, session):
        app.restore_session(deepcopy(session))
        app.ensure_class_context()
        app.ensure_term_context()

    def test_old_database_loads_unchanged_and_is_not_dirty(self):
        legacy = self.legacy_session()
        self.reload(legacy)
        for cls in (A, B):                 # the shared setting reaches both, as before
            self.switch(cls)
            self.assertEqual(app.archived_for_active(), [NAME])
            self.assertFalse(app.assignment_on(NAME))
            self.assertEqual(self.ss["date_override"][NAME], date(2026, 6, 9))
        self.switch(A)
        payload = app.build_session_payload()
        self.assertEqual(payload["archived"], legacy["archived"])
        self.assertEqual(payload["date_override"], legacy["date_override"])
        self.assertEqual(payload["active_by_term"], legacy["active_by_term"])
        self.assertIn(ASSIGNMENT_STATE_KEY, payload)
        self.assertEqual(persistent_content_fingerprint(app.gb(), legacy),
                         persistent_content_fingerprint(app.gb(), payload))

    def test_a_per_class_edit_is_a_real_change_and_round_trips(self):
        self.reload(self.legacy_session())
        before = persistent_content_fingerprint(app.gb(), app.build_session_payload())
        app.restore_assignment(NAME)       # 8A only
        payload = app.build_session_payload()
        self.assertNotEqual(before, persistent_content_fingerprint(app.gb(), payload))
        self.assertEqual(validate_database_payload(build_payload(app.gb(), payload)), ())
        path = os.path.join(self.tmp.name, "acm_database.json")
        save_database(path, app.gb(), payload)
        loaded = load_database(path)
        self.ss["gradebook"] = loaded["gradebook"]
        self.reload(loaded["session"])
        self.assertEqual(app.archived_for_active(), [])
        self.assertTrue(app.assignment_on(NAME))
        self.switch(B)
        self.assertEqual(app.archived_for_active(), [NAME])
        self.assertFalse(app.assignment_on(NAME))
        # Each class's own settings come back exactly as saved.
        self.assertEqual(app.build_session_payload()[ASSIGNMENT_STATE_KEY],
                         payload[ASSIGNMENT_STATE_KEY])

    def test_flat_keys_remain_for_an_older_reader(self):
        app.archive_assignment(NAME)
        payload = app.build_session_payload()
        self.assertEqual(payload["archived"], [NAME])
        self.assertIs(payload["active_by_term"][self.term][NAME], False)
        self.assertEqual(payload[ASSIGNMENT_STATE_KEY][B]["archived"], [])
        self.switch(B)                     # the class on screen decides the flat copy
        self.assertEqual(app.build_session_payload()["archived"], [])

    def test_validator_rejects_malformed_settings(self):
        for bad in ([], {A: []}, {A: {"archived": "x"}},
                    {A: {"date_override": {NAME: "soon"}}},
                    {A: {"active_by_term": {self.term: {NAME: "yes"}}}}):
            payload = build_payload(Gradebook(), {ASSIGNMENT_STATE_KEY: bad})
            self.assertTrue(validate_database_payload(payload), bad)

    def test_expansion_gives_each_holding_class_its_own_copy(self):
        expanded = expand_flat_assignment_state(app.gb(), self.legacy_session())
        self.assertEqual(expanded[A], expanded[B])
        self.assertIsNot(expanded[A]["date_override"], expanded[B]["date_override"])
        self.assertEqual(expanded[A]["archived"], [NAME])

    def test_backup_is_kept_before_the_first_class_scoped_save(self):
        path = os.path.join(self.tmp.name, "acm_database.json")
        save_database(path, app.gb(), self.legacy_session())
        pattern = path + ".bak-pre-class-scoped-names-*"
        for expected in (1, 1):            # made once, not again on the next save
            token = database_write_token(capture_database_snapshot(path))
            save_database_checked(path, app.gb(), app.build_session_payload(), token)
            self.assertEqual(len(glob.glob(pattern)), expected)
        kept = load_database(glob.glob(pattern)[0])
        self.assertNotIn(ASSIGNMENT_STATE_KEY, kept["session"])
        self.assertEqual(kept["session"]["archived"], [NAME])


class ReportingAndBackupTests(ClassScopedBase):
    def test_each_class_reports_with_its_own_settings(self):
        app.archive_assignment(NAME)       # 8A archives; 8B still counts it
        state, book = app.reporting_snapshot()
        included = {}
        for cls, sid in ((A, "a1"), (B, "b1")):
            scope = ReportScope(cls, cls, self.term, (ReportMember(sid, cls),))
            snap = source_snapshot(state, book, scope, cls)
            score = snap["gradebook"].students[sid].scores["A"][0]
            included[cls] = score.include_in_report
            self.assertEqual(NAME in snap["archived"], cls == A)
        self.assertEqual(included, {A: False, B: True})

    def test_term_backup_keeps_each_classes_on_off(self):
        app.term_active_map()[NAME] = False            # 8A off, 8B untouched (on)
        app.class_active_map(B)[NAME] = True
        with mock.patch.object(app, "db_path", return_value="fictional"):
            backup = app.build_term_backup(self.term)
        self.assertEqual(backup["payload"]["active_by_class"],
                         {A: {NAME: False}, B: {NAME: True}})
        app.term_active_map()[NAME] = True             # drift after the backup
        app.class_active_map(B)[NAME] = False
        with mock.patch.object(app, "_pre_restore_backup", return_value=""), \
                mock.patch.object(app, "_mark_teacher_input_deleted"):
            app.restore_term_backup(backup)
        self.assertFalse(app.assignment_on(NAME))
        self.switch(B)
        self.assertTrue(app.assignment_on(NAME))
        self.assertEqual(self.values(A), [5])
        self.assertEqual(self.values(B), [7])


if __name__ == "__main__":
    unittest.main()
