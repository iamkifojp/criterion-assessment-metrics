"""App-level tests for term backup & restore (docs/TERM_BACKUP_RESTORE_PLAN.md).

Covers the third line of defence behind the cloud mirror: a deliberate,
teacher-initiated snapshot of one whole term written outside the database, and
the disaster-recovery loader that replaces that term's slice wholesale.

Streamlit is never run: ``app.st`` is swapped for a stand-in whose
``session_state`` is a plain dict, ``app.gb`` for a fixture gradebook,
``app.db_path`` / ``app.class_data_dir`` for temp paths, and the heavy tail of
``restore_term_backup`` (``persist`` + the alias re-point helpers) for recording
no-ops so a test exercises the pure slice-replace logic. Run:

    python -m unittest tests.test_term_backup
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (path shim must precede the import)
from engine import (  # noqa: E402
    Gradebook,
    CriterionScore,
    ExamResult,
    Assignment,
    CALCULATION_METHODS,
    serialize_gradebook,
    save_database,
)

CLASS_A = "Year 7 1-4"
CLASS_B = "Year 8 2-1"
METHOD = next(iter(CALCULATION_METHODS))


def _make_gradebook():
    gb = Gradebook()
    gb.assignments = [
        Assignment(name="Still Life", criteria=["A"], class_name=CLASS_A,
                   term="Term 1"),
        Assignment(name="Portrait", criteria=["A"], class_name=CLASS_B,
                   term="Term 1"),
        Assignment(name="Exam 1", criteria=[], class_name=CLASS_A, term="Term 1",
                   is_exam=True, max_total=45),
        Assignment(name="Landscape", criteria=["A"], class_name=CLASS_A,
                   term="Term 2"),
    ]
    alice = gb.get_or_create("alice", "Ada")
    alice.add_score(CriterionScore(criterion="A", value=6,
                                   timestamp=datetime(2026, 5, 1),
                                   assignment="Still Life", comment="Careful."))
    alice.add_score(CriterionScore(criterion="A", value=7,
                                   timestamp=datetime(2026, 9, 1),
                                   assignment="Landscape"))   # Term 2
    alice.exam_results["Exam 1"] = ExamResult(assignment="Exam 1", total=37,
                                              max_total=45)
    zoe = gb.get_or_create("zoe", "Zoe")
    zoe.add_score(CriterionScore(criterion="A", value=7,
                                 timestamp=datetime(2026, 5, 1),
                                 assignment="Portrait"))
    return gb


def _make_ss():
    return {
        "classes": [{"name": CLASS_A}, {"name": CLASS_B}],
        "active_class": CLASS_A,
        "active_term": "Term 1",
        "rosters": {CLASS_A: [{"key": "alice"}], CLASS_B: [{"key": "zoe"}]},
        "archived_students": {},
        "comments_by_term": {
            "Term 1": {"alice": "T1 Ada strong.", "zoe": "T1 Zoe bold."},
            "Term 2": {"alice": "T2 Ada developing."},
        },
        "effort_by_term": {"Term 1": {"alice": 4, "zoe": 3},
                           "Term 2": {"alice": 5}},
        "teacher_remarks": {"alice": "Chatty."},
        "final_override": {"alice": {"A": 7}},
        "active_by_term": {
            "Term 1": {"Still Life": True, "Portrait": True, "Exam 1": False},
            "Term 2": {"Landscape": True},
        },
        "calc_method_by_term": {"Term 1": {"alice": METHOD}},
        "late_flags": {"alice||Still Life||A": True, "alice||Landscape||A": True},
        "excused_flags": {"zoe||Portrait": True},
        "mirror_fingerprints": {"seed": "x"},
        "mirror_deletions_this_session": False,
        "save_status": ("", ""),
    }


class TermBackupBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "acm_database.json")
        self.gb = _make_gradebook()
        self.ss = _make_ss()
        self.persist_calls = []

        self._orig = {
            "st": app.st, "gb": app.gb, "cdd": app.class_data_dir,
            "dbp": app.db_path, "persist": app.persist,
            "ecc": app.ensure_class_context, "etc": app.ensure_term_context,
        }
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.class_data_dir = self._class_dir
        app.db_path = lambda: self.db
        app.persist = self._fake_persist
        app.ensure_class_context = lambda: None
        app.ensure_term_context = lambda: None

    def tearDown(self):
        app.st = self._orig["st"]
        app.gb = self._orig["gb"]
        app.class_data_dir = self._orig["cdd"]
        app.db_path = self._orig["dbp"]
        app.persist = self._orig["persist"]
        app.ensure_class_context = self._orig["ecc"]
        app.ensure_term_context = self._orig["etc"]

    def _class_dir(self, class_name, create=False):
        d = os.path.join(self.tmp, app._safe_dirname(class_name))
        if create:
            os.makedirs(d, exist_ok=True)
        return d

    def _fake_persist(self, show=False, allow_shrink=False):
        self.persist_calls.append(allow_shrink)


class BuildTests(TermBackupBase):
    def test_header_and_scope(self):
        b = app.build_term_backup("Term 1")
        self.assertEqual(b["kind"], "cam_term_backup")
        self.assertEqual(b["version"], 1)
        self.assertEqual(b["term"], "Term 1")
        self.assertEqual(set(b["classes"]), {CLASS_A, CLASS_B})
        # Only Term-1 assignments captured (Landscape is Term 2).
        names = {a["name"] for a in b["payload"]["assignments"]}
        self.assertEqual(names, {"Still Life", "Portrait", "Exam 1"})

    def test_scores_and_exam_scoped_by_term_and_class(self):
        p = app.build_term_backup("Term 1")["payload"]
        # alice's Still Life score is under CLASS_A; her Landscape (Term 2) is not.
        a_scores = p["scores"][CLASS_A]["alice"]
        self.assertEqual([s["assignment"] for s in a_scores], ["Still Life"])
        # zoe's Portrait under CLASS_B.
        self.assertEqual(p["scores"][CLASS_B]["zoe"][0]["assignment"], "Portrait")
        # Exam result captured for its term.
        self.assertEqual(p["exam_results"][CLASS_A]["alice"][0]["assignment"],
                         "Exam 1")

    def test_term_scoped_maps_only_this_term(self):
        p = app.build_term_backup("Term 1")["payload"]
        self.assertEqual(p["comments"][CLASS_A], {"alice": "T1 Ada strong."})
        self.assertEqual(p["comments"][CLASS_B], {"zoe": "T1 Zoe bold."})
        self.assertEqual(p["effort"][CLASS_A], {"alice": 4})
        self.assertEqual(p["calc_method"], {"alice": METHOD})
        # active filtered to this term's assignment names only.
        self.assertEqual(set(p["active"]), {"Still Life", "Portrait", "Exam 1"})
        # late/excused only for this term's assignments (Landscape excluded).
        self.assertEqual(p["late_flags"], {"alice||Still Life||A": True})
        self.assertEqual(p["excused"], {"zoe||Portrait": True})

    def test_nonterm_maps_captured_whole(self):
        p = app.build_term_backup("Term 1")["payload"]
        self.assertEqual(p["remarks"][CLASS_A], {"alice": "Chatty."})
        self.assertEqual(p["final_override"][CLASS_A], {"alice": {"A": 7}})


class ValidateTests(TermBackupBase):
    def test_accepts_well_formed(self):
        b = app.build_term_backup("Term 1")
        term, err = app.validate_term_backup(b)
        self.assertEqual(term, "Term 1")
        self.assertEqual(err, "")

    def test_rejects_wrong_kind(self):
        term, err = app.validate_term_backup({"kind": "something_else"})
        self.assertIsNone(term)
        self.assertIn("not a CAM term backup", err)

    def test_rejects_bad_version(self):
        b = app.build_term_backup("Term 1")
        b["version"] = 999
        term, err = app.validate_term_backup(b)
        self.assertIsNone(term)
        self.assertIn("version", err)

    def test_rejects_unknown_term(self):
        b = app.build_term_backup("Term 1")
        b["term"] = "Term 9"
        term, err = app.validate_term_backup(b)
        self.assertIsNone(term)

    def test_rejects_non_dict(self):
        term, err = app.validate_term_backup([1, 2, 3])
        self.assertIsNone(term)


class RestoreRoundTripTests(TermBackupBase):
    def test_round_trip_lossless(self):
        backup = app.build_term_backup("Term 1")
        # Snapshot Term-2 state to prove invariance later.
        t2_comment = self.ss["comments_by_term"]["Term 2"]["alice"]
        t2_effort = dict(self.ss["effort_by_term"]["Term 2"])

        # Simulate a Term-1 wipe (grades self-heal; typed content is gone).
        self.ss["comments_by_term"]["Term 1"] = {}
        self.ss["effort_by_term"]["Term 1"] = {}
        self.ss["calc_method_by_term"]["Term 1"] = {}
        self.ss["active_by_term"]["Term 1"] = {}
        self.ss["late_flags"].pop("alice||Still Life||A", None)
        self.ss["excused_flags"].pop("zoe||Portrait", None)
        self.gb.assignments = [a for a in self.gb.assignments
                               if app._term_of_assignment(a) != "Term 1"]
        for stu in self.gb.students.values():
            for crit, bucket in list(stu.scores.items()):
                stu.scores[crit] = [sc for sc in bucket
                                    if sc.assignment != "Still Life"
                                    and sc.assignment != "Portrait"]
            stu.exam_results.pop("Exam 1", None)

        app.restore_term_backup(backup)

        # Term-1 grades back.
        alice = self.gb.students["alice"]
        self.assertEqual([sc.assignment for sc in alice.scores["A"]],
                         ["Still Life", "Landscape"])
        self.assertIn("Exam 1", alice.exam_results)
        self.assertEqual(self.gb.students["zoe"].scores["A"][0].assignment,
                         "Portrait")
        # Term-1 assignments back (all three).
        t1_names = {a.name for a in self.gb.assignments
                    if app._term_of_assignment(a) == "Term 1"}
        self.assertEqual(t1_names, {"Still Life", "Portrait", "Exam 1"})
        # Term-1 maps back.
        self.assertEqual(self.ss["comments_by_term"]["Term 1"],
                         {"alice": "T1 Ada strong.", "zoe": "T1 Zoe bold."})
        self.assertEqual(self.ss["effort_by_term"]["Term 1"],
                         {"alice": 4, "zoe": 3})
        self.assertEqual(self.ss["calc_method_by_term"]["Term 1"],
                         {"alice": METHOD})
        self.assertTrue(self.ss["late_flags"]["alice||Still Life||A"])
        self.assertTrue(self.ss["excused_flags"]["zoe||Portrait"])
        # Restore is a typed-confirmed shrink-exempt write.
        self.assertEqual(self.persist_calls, [True])
        self.assertTrue(self.ss["mirror_deletions_this_session"])
        self.assertEqual(self.ss["mirror_fingerprints"], {})

    def test_other_terms_untouched(self):
        backup = app.build_term_backup("Term 1")
        before_landscape = [a for a in self.gb.assignments if a.name == "Landscape"][0]
        app.restore_term_backup(backup)
        # Term-2 comment/effort byte-identical.
        self.assertEqual(self.ss["comments_by_term"]["Term 2"],
                         {"alice": "T2 Ada developing."})
        self.assertEqual(self.ss["effort_by_term"]["Term 2"], {"alice": 5})
        # Landscape (Term 2) still present, and alice's Term-2 score survives.
        self.assertIn("Landscape", {a.name for a in self.gb.assignments})
        self.assertIn("Landscape",
                      {sc.assignment for sc in self.gb.students["alice"].scores["A"]})
        # No duplicate Landscape assignment created.
        self.assertEqual(sum(1 for a in self.gb.assignments if a.name == "Landscape"), 1)

    def test_no_duplicate_scores_on_restore_over_live(self):
        # Restore straight over live (unwiped) data must not double the scores.
        backup = app.build_term_backup("Term 1")
        app.restore_term_backup(backup)
        still_life = [sc for sc in self.gb.students["alice"].scores["A"]
                      if sc.assignment == "Still Life"]
        self.assertEqual(len(still_life), 1)

    def test_live_only_assignment_removed(self):
        # A Term-1 assignment that postdates the backup is removed on restore.
        backup = app.build_term_backup("Term 1")
        self.gb.assignments.append(
            Assignment(name="Extra T1", criteria=["A"], class_name=CLASS_A,
                       term="Term 1"))
        self.gb.students["alice"].add_score(CriterionScore(
            criterion="A", value=5, timestamp=datetime(2026, 6, 1),
            assignment="Extra T1"))
        app.restore_term_backup(backup)
        self.assertNotIn("Extra T1", {a.name for a in self.gb.assignments})
        self.assertNotIn("Extra T1",
                         {sc.assignment for sc in self.gb.students["alice"].scores["A"]})

    def test_remarks_and_override_fill_blanks_only(self):
        backup = app.build_term_backup("Term 1")
        # A live remark for alice must survive (not be clobbered); a blank one
        # for a new student is filled; a live override criterion is kept.
        self.ss["teacher_remarks"] = {"alice": "LIVE remark wins."}
        self.ss["final_override"] = {"alice": {"A": 3}}   # differs from backup's 7
        app.restore_term_backup(backup)
        self.assertEqual(self.ss["teacher_remarks"]["alice"], "LIVE remark wins.")
        # alice already had an A override -> backup's 7 does NOT overwrite it.
        self.assertEqual(self.ss["final_override"]["alice"]["A"], 3)


class DiffTests(TermBackupBase):
    def test_diff_reports_new_and_removed(self):
        backup = app.build_term_backup("Term 1")
        # Wipe alice's comment (so it's "new") and add a live-only assignment.
        self.ss["comments_by_term"]["Term 1"] = {"zoe": "T1 Zoe bold."}
        self.gb.assignments.append(
            Assignment(name="Extra T1", criteria=["A"], class_name=CLASS_A,
                       term="Term 1"))
        diff = app.diff_term_backup(backup)
        self.assertEqual(diff["term"], "Term 1")
        self.assertIn("alice", diff["per_class"][CLASS_A]["new_comments"])
        self.assertIn("Extra T1", diff["per_class"][CLASS_A]["assignments_removed"])

    def test_diff_flags_changed_comment(self):
        backup = app.build_term_backup("Term 1")
        self.ss["comments_by_term"]["Term 1"]["alice"] = "DIFFERENT now."
        diff = app.diff_term_backup(backup)
        self.assertIn("alice", diff["per_class"][CLASS_A]["changed_comments"])


class PreRestoreBackupTests(TermBackupBase):
    def test_pre_restore_bak_equals_predisaster_db(self):
        # Write the live DB to disk (as persist would have), snapshot its bytes.
        save_database(self.db, self.gb, {})
        with open(self.db, "rb") as fh:
            pre_bytes = fh.read()
        backup = app.build_term_backup("Term 1")
        app.restore_term_backup(backup)
        baks = [f for f in os.listdir(self.tmp)
                if f.startswith("acm_database.json.bak-pre-term-restore-")]
        self.assertEqual(len(baks), 1)
        with open(os.path.join(self.tmp, baks[0]), "rb") as fh:
            self.assertEqual(fh.read(), pre_bytes)


if __name__ == "__main__":
    unittest.main()
