"""Phase 4 (Exam Identity & Banding plan) — exam CSV identity routing (D6).

Covers docs/EXAM_IDENTITY_AND_BANDING_PLAN.md Phase 4:

  * ``ingest_exam_csv`` routes each row through the shared
    :func:`resolve_identity` pipeline (exact → alias → unambiguous prefix →
    pool) when ``roster_keys`` is supplied — never minting a phantom student —
    and is byte-identical to the legacy behaviour without a roster.
  * Unmatched rows pool as exam-flavoured dicts (``is_exam: True`` +
    ``questions``/``total``/``max_total``/``comment``), plain-JSON safe, with
    the sheet-wide / sidecar max backfilled like a matched row.
  * ``materialize_exam_row`` re-creates the ExamResult under the roster
    student, preserving prior ``chosen`` picks for still-answered labels.
  * App side: ``assign_work`` routes ``is_exam`` pool rows to
    ``materialize_exam_row``; the crop-path helpers resolve the cloud root
    first with the legacy root as fallback; exam tiles caption stem + raw
    total.

Run:  python -m unittest tests.test_exam_identity
"""

import csv
import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.ingestion import IngestionPipeline  # noqa: E402
from engine.models import Gradebook  # noqa: E402

CLASS = "Test MYP Class"
EXAM = "Mid"


def _write_exam_csv(path, rows, labels=("Q1", "Q2"), sidecar=None):
    """rows: [(sid, q1, q2, total, max_total, comment)] — "" cells allowed."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Student Name", *labels, "Total Score", "Max Total",
                    "Due Date", "Comment"])
        for sid, q1, q2, total, mx, comment in rows:
            w.writerow([sid, q1, q2, total, mx, "2026-07-01", comment])
    if sidecar is not None:
        with open(path + ".meta.json", "w", encoding="utf-8") as fh:
            json.dump({"sections": sidecar}, fh)


class _EngineBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_examid_")
        self.csv = os.path.join(self.tmp, f"{EXAM}_Grades_2026-07-01.csv")
        self.gb = Gradebook()
        self.pipe = IngestionPipeline(self.gb)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class RosterlessLegacy(_EngineBase):
    def test_no_roster_ingests_raw_ids(self):
        _write_exam_csv(self.csv, [("scan_0001", 4, 5, 9, 20, "")])
        created = self.pipe.ingest_exam_csv(self.csv, assignment=EXAM)
        self.assertEqual(len(created), 1)
        self.assertIn("scan_0001", self.gb.students)
        self.assertEqual(
            self.gb.students["scan_0001"].exam_results[EXAM].total, 9)


class RoutedIngest(_EngineBase):
    def test_exact_and_alias_and_prefix_routing(self):
        _write_exam_csv(self.csv, [
            ("100001", 4, 5, 9, 20, ""),          # exact roster key
            ("weird_stem", 3, 3, 6, 20, ""),      # durable alias
            ("100002a", 8, 8, 16, 20, ""),        # unambiguous prefix
        ])
        unmatched, auto = [], {}
        created = self.pipe.ingest_exam_csv(
            self.csv, assignment=EXAM,
            roster_keys={"100001", "100002", "100003"},
            aliases={"weird_stem": "100003"},
            unmatched_out=unmatched, auto_aliases_out=auto)
        self.assertEqual(len(created), 3)
        self.assertEqual(unmatched, [])
        self.assertEqual(set(self.gb.students), {"100001", "100002", "100003"})
        self.assertEqual(self.gb.students["100003"].exam_results[EXAM].total, 6)
        self.assertEqual(self.gb.students["100002"].exam_results[EXAM].total, 16)
        # The prefix fast path reports its match for durable recording.
        self.assertEqual(auto, {"100002a": "100002"})

    def test_unmatched_pools_exam_row_and_mints_nothing(self):
        _write_exam_csv(self.csv, [
            ("100001", 4, 5, 9, 20, ""),
            ("scan_0007", 2, 7, 9, "", "messy handwriting"),  # blank Max Total
        ])
        unmatched = []
        self.pipe.ingest_exam_csv(
            self.csv, assignment=EXAM, roster_keys={"100001"},
            unmatched_out=unmatched)
        self.assertEqual(set(self.gb.students), {"100001"})   # no phantom
        self.assertEqual(len(unmatched), 1)
        row = unmatched[0]
        self.assertEqual(row["csv_key"], "scan_0007")
        self.assertTrue(row["is_exam"])
        self.assertEqual(row["questions"], {"Q1": 2, "Q2": 7})
        self.assertEqual(row["total"], 9)
        self.assertEqual(row["comment"], "messy handwriting")
        # Sheet-wide max backfilled onto the pooled row, like a matched one.
        self.assertEqual(row["max_total"], 20)
        # Pool rows must survive the session save/load round-trip as-is.
        self.assertEqual(json.loads(json.dumps(row)), row)

    def test_sidecar_max_applies_to_pool_rows_too(self):
        sidecar = [{"name": "A", "required": None,
                    "questions": [{"label": "Q1", "max": 10},
                                  {"label": "Q2", "max": 5}]}]
        _write_exam_csv(self.csv, [("scan_0001", 4, 5, 9, 20, "")],
                        sidecar=sidecar)
        unmatched = []
        self.pipe.ingest_exam_csv(
            self.csv, assignment=EXAM, roster_keys={"100001"},
            unmatched_out=unmatched)
        self.assertEqual(unmatched[0]["max_total"], 15)

    def test_alias_routed_reingest_keeps_chosen(self):
        _write_exam_csv(self.csv, [("weird_stem", 4, 5, 9, 20, "")])
        aliases = {"weird_stem": "100001"}
        self.pipe.ingest_exam_csv(
            self.csv, assignment=EXAM, roster_keys={"100001"}, aliases=aliases)
        self.gb.students["100001"].exam_results[EXAM].chosen["B"] = ["Q2"]
        # Re-sync of the same CSV routes via the alias and carries the pick.
        self.pipe.ingest_exam_csv(
            self.csv, assignment=EXAM, roster_keys={"100001"}, aliases=aliases)
        self.assertEqual(
            self.gb.students["100001"].exam_results[EXAM].chosen, {"B": ["Q2"]})


class MaterializeExamRow(_EngineBase):
    ROW = {"csv_key": "scan_0007", "is_exam": True,
           "questions": {"Q1": 2, "Q2": 7}, "total": 9, "max_total": 20,
           "comment": "messy"}

    def test_materializes_under_roster_student(self):
        result = self.pipe.materialize_exam_row(EXAM, "100001", dict(self.ROW))
        self.assertIn("100001", self.gb.students)
        self.assertIs(self.gb.students["100001"].exam_results[EXAM], result)
        self.assertEqual(result.total, 9)
        self.assertEqual(result.max_total, 20)
        self.assertEqual(result.questions, {"Q1": 2, "Q2": 7})
        self.assertEqual(result.comment, "messy")

    def test_preserves_prior_chosen_for_still_answered_labels(self):
        first = self.pipe.materialize_exam_row(EXAM, "100001", dict(self.ROW))
        first.chosen["B"] = ["Q2", "Q9"]   # Q9 no longer answered
        again = self.pipe.materialize_exam_row(EXAM, "100001", dict(self.ROW))
        self.assertEqual(again.chosen, {"B": ["Q2"]})


# --------------------------------------------------------------------------
# App side (same seams as tests/test_exam_sections_app.py — no Streamlit boot)
# --------------------------------------------------------------------------

import app  # noqa: E402
from engine import Assignment, Gradebook as _GB  # noqa: E402


class _AppBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_examid_app_")
        # CAM_DB_PATH pins db_folder() to the sandbox (and keeps these tests
        # independent of Streamlit bare-mode session state).
        self._orig_env = os.environ.get("CAM_DB_PATH")
        os.environ["CAM_DB_PATH"] = self.tmp
        self._orig_crops = app.EXAM_CROPS_DIR
        app.EXAM_CROPS_DIR = os.path.join(self.tmp, "legacy_crops")

    def tearDown(self):
        if self._orig_env is None:
            os.environ.pop("CAM_DB_PATH", None)
        else:
            os.environ["CAM_DB_PATH"] = self._orig_env
        app.EXAM_CROPS_DIR = self._orig_crops
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _touch_crop(self, root_dir, label, student):
        d = os.path.join(root_dir, label)
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, f"{student}.png")
        with open(p, "wb") as f:
            f.write(b"\x89PNG\r\n")
        return p

    @property
    def cloud_exam_dir(self):
        return os.path.join(self.tmp, app._safe_dirname(CLASS),
                            "exam_crops", EXAM)

    @property
    def legacy_exam_dir(self):
        return os.path.join(app.EXAM_CROPS_DIR, app._safe_dirname(CLASS), EXAM)


class DualRootCropPaths(_AppBase):
    def test_cloud_root_wins(self):
        cloud = self._touch_crop(self.cloud_exam_dir, "__name__", "Ada")
        self._touch_crop(self.legacy_exam_dir, "__name__", "Ada")
        self.assertEqual(app.exam_name_crop_path(CLASS, EXAM, "Ada"), cloud)
        self.assertTrue(app.exam_has_name_crops(CLASS, EXAM))

    def test_legacy_root_is_the_fallback(self):
        legacy = self._touch_crop(self.legacy_exam_dir, "__name__", "Ada")
        self.assertEqual(app.exam_name_crop_path(CLASS, EXAM, "Ada"), legacy)
        self.assertTrue(app.exam_has_name_crops(CLASS, EXAM))

    def test_question_crop_and_absent_tree(self):
        q1 = self._touch_crop(self.cloud_exam_dir, "Q1", "Ada")
        self.assertEqual(app.exam_crop_path(CLASS, EXAM, "Q1", "Ada"), q1)
        self.assertEqual(app.exam_name_crop_path(CLASS, EXAM, "Ada"), "")
        self.assertFalse(app.exam_has_name_crops(CLASS, EXAM))


class AssignWorkExamRow(_AppBase):
    POOL_ROW = {"csv_key": "scan_0007", "is_exam": True,
                "questions": {"Q1": 2, "Q2": 7}, "total": 9, "max_total": 20,
                "comment": ""}

    def setUp(self):
        super().setUp()
        self.gb = _GB()
        self.gb.register_assignment(Assignment(
            name=EXAM, criteria=[], class_name=CLASS, is_exam=True,
            max_total=20, question_labels=["Q1", "Q2"]))
        self.ss = {
            "unmatched_works": {CLASS: {EXAM: [dict(self.POOL_ROW)]}},
            "work_aliases": {},
        }
        self._orig = {"st": app.st, "gb": app.gb, "persist": app.persist}
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.persist = lambda *a, **k: None

    def tearDown(self):
        app.st = self._orig["st"]
        app.gb = self._orig["gb"]
        app.persist = self._orig["persist"]
        super().tearDown()

    def test_assign_materializes_exam_result_and_records_alias(self):
        ok = app.assign_work(CLASS, EXAM, "scan_0007", "100001")
        self.assertTrue(ok)
        self.assertEqual(self.ss["work_aliases"][CLASS],
                         {"scan_0007": "100001"})
        r = self.gb.students["100001"].exam_results[EXAM]
        self.assertEqual((r.total, r.max_total), (9, 20))
        self.assertEqual(r.questions, {"Q1": 2, "Q2": 7})
        # No CriterionScores were minted — exams band later, in Window 1.
        self.assertFalse(any(self.gb.students["100001"].scores.values()))
        # Pool emptied and pruned.
        self.assertEqual(self.ss["unmatched_works"], {})

    def test_assign_missing_row_returns_false(self):
        self.assertFalse(app.assign_work(CLASS, EXAM, "nope", "100001"))


class RoutedExamSyncTest(unittest.TestCase):
    """End-to-end scoped sync of a rostered exam CSV — the ``sync_exam`` →
    ``_sync_one_csv`` → ``_ingest_cloud_file`` path with routing, pool rebuild,
    phantom cleanup and the assign → alias → re-sync loop. Same seams as
    tests/test_export_beacon_sync.py."""

    EXAM_CSV = (
        "﻿Student Name,Q1,Q2,Total Score,Max Total,Due Date,Comment\r\n"
        "100001,3,5,8,10,2026-06-01,Solid.\r\n"
        "scan_0007,2,4,6,10,2026-06-01,\r\n"
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="cam_examid_sync_")
        self.class_dir = os.path.join(self.tmp, CLASS)
        os.makedirs(self.class_dir, exist_ok=True)
        self.exam_path = os.path.join(
            self.class_dir, "Final Exam_Grades_2026-06-01.csv")
        with open(self.exam_path, "w", encoding="utf-8", newline="") as f:
            f.write(self.EXAM_CSV)

        self.gb = _GB()
        # A phantom an earlier UNROUTED ingest of this exam minted: its only
        # data is this exam's result, which the purge-replace strips.
        from engine import ExamResult
        phantom = self.gb.get_or_create("https___smiletutor_sg_old")
        phantom.exam_results["Final Exam"] = ExamResult(
            "Final Exam", total=6, max_total=10, questions={"Q1": 2, "Q2": 4})

        self.ss = {
            "prefs": {"db_custom_path": self.tmp},
            "ingested_files": {},
            "active_class": CLASS,
            "classes": [{"name": CLASS, "grade": "", "myp_year": "",
                         "subject": ""}],
            "rosters": {CLASS: [{"key": "100001"}, {"key": "100002"}]},
            "archived_students": {},
            "work_aliases": {CLASS: {}},
            "unmatched_works": {CLASS: {}},
            "active": {},
            "archived": set(),
        }
        self._orig = {
            "st": app.st, "gb": app.gb, "cdd": app.class_data_dir,
            "persist": app.persist,
            "heal": app._heal_score_comments_from_mirrors,
            "ectx": app.ensure_class_context,
        }
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.class_data_dir = lambda name, create=False: (
            self.class_dir if name == CLASS else os.path.join(self.tmp, name))
        app.persist = lambda *a, **k: None
        app._heal_score_comments_from_mirrors = lambda *a, **k: None
        app.ensure_class_context = lambda *a, **k: None

    def tearDown(self):
        app.st = self._orig["st"]
        app.gb = self._orig["gb"]
        app.class_data_dir = self._orig["cdd"]
        app.persist = self._orig["persist"]
        app._heal_score_comments_from_mirrors = self._orig["heal"]
        app.ensure_class_context = self._orig["ectx"]
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_routed_sync_pools_unmatched_and_sweeps_phantoms(self):
        summary = app.sync_exam(CLASS, "Final Exam")
        self.assertEqual(summary["ingested"], 1)
        # Matched row landed on the roster student.
        self.assertEqual(
            self.gb.students["100001"].exam_results["Final Exam"].total, 8)
        # Unmatched row pooled instead of minting a student.
        pool = self.ss["unmatched_works"][CLASS]["Final Exam"]
        self.assertEqual([r["csv_key"] for r in pool], ["scan_0007"])
        self.assertTrue(pool[0]["is_exam"])
        self.assertNotIn("scan_0007", self.gb.students)
        # The pre-existing phantom (emptied by the purge-replace) was swept.
        self.assertNotIn("https___smiletutor_sg_old", self.gb.students)
        self.assertTrue(any("phantom" in m for m in summary["messages"]))

    def test_assign_then_resync_routes_via_alias(self):
        app.sync_exam(CLASS, "Final Exam")
        self.assertTrue(
            app.assign_work(CLASS, "Final Exam", "scan_0007", "100002"))
        r = self.gb.students["100002"].exam_results["Final Exam"]
        self.assertEqual((r.total, r.max_total), (6, 10))
        self.assertEqual(self.ss["unmatched_works"], {})
        # Re-sync of the same CSV (registry cleared to force a re-ingest):
        # the durable alias routes the row silently — the pool stays empty.
        self.ss["ingested_files"] = {}
        summary = app.sync_exam(CLASS, "Final Exam")
        self.assertEqual(summary["ingested"], 1)   # forced re-ingest ran
        self.assertEqual(
            self.ss["unmatched_works"].get(CLASS, {}).get("Final Exam", []),
            [])
        self.assertEqual(
            self.gb.students["100002"].exam_results["Final Exam"].total, 6)


class ExamTileCaption(unittest.TestCase):
    def test_exam_row_captions_stem_and_raw_total(self):
        row = {"csv_key": "scan_0007", "is_exam": True, "total": 31,
               "max_total": 45}
        self.assertEqual(app._work_caption(row), "scan_0007 · 31/45")

    def test_assignment_row_keeps_filename_caption(self):
        self.assertEqual(app._work_caption({"files": "img_1.jpg; img_0.jpg"}),
                         "img_1.jpg")


if __name__ == "__main__":
    unittest.main()
