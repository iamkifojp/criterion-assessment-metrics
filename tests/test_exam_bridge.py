"""CAM2 convergence Stage 2 — CAM reads CAM2 sessions (reader only).

Covers docs/CAM2_EXAM_CONVERGENCE_PLAN.md Stage 2:

  * ``ExamResult`` gains optional CAM2 fields (mode, session id, Not
    answered, counted, complete, rubric levels, final levels, question
    comments). CGW-era records load and save byte-for-byte as before, and the
    new fields round-trip through the database file.
  * ``engine.exam_bridge.read_session`` reads a session folder with the
    vendored CAM2 engine (loaded as ``cam2_engine``), totals from CAM2's
    ``grading_summary`` (best N, teacher picks, round-half-up), and writes
    nothing.
  * ``route_session`` files papers by ``external_id``, then
    ``resolve_identity``, else the 🧩 pool; a pooled paper materializes with
    its full result.

Sessions are fictional, built with CAM2's own engine in temp folders.

Run:  python -m unittest tests.test_exam_bridge
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import exam_bridge  # noqa: E402
from engine.exam_bridge import ExamSessionError, read_session, route_session  # noqa: E402
from engine.ingestion import IngestionPipeline  # noqa: E402
from engine.models import ExamResult, Gradebook  # noqa: E402
from engine.persistence import (  # noqa: E402
    exam_result_from_dict,
    exam_result_to_dict,
    load_database,
    save_database,
    validate_database_payload,
)

EXAM = "Fictional Midterm"
NA = "not_answered"


def _questions(*specs):
    """specs: (id, label, max, rubric_ids)."""
    return [{"id": qid, "label": label, "boxes": [], "max": mx,
             **({"rubric_ids": rids} if rids else {})}
            for qid, label, mx, rids in specs]


class _SessionBase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cam_bridge_")
        patcher = mock.patch.dict(os.environ, {"CAM2_APP_DATA": os.path.join(self.root, "appdata")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.storage = exam_bridge.cam2_module("storage")
        self.gs = exam_bridge.cam2_module("grading_summary")

    def make_session(self, name, *, mode, questions, students, roster=(),
                     rubrics=(), groups=(), grades=(), overall=None, ready=True):
        """grades: (sid, qid, value[, rubric_id]) or (sid, qid, value, rid, comment)."""
        folder = os.path.join(self.root, name)
        os.makedirs(folder)
        session, config, data = self.storage.create_session(folder, EXAM)
        config.update(mode=mode, questions=list(questions), rubrics=list(rubrics),
                      choice_groups=list(groups), roster=list(roster),
                      students=[{"id": sid, "scan": f"scans/{sid}.pdf", "source": src,
                                 "pages": 1, "roster_id": rid}
                                for sid, src, rid in students],
                      host_ready_at="2026-11-01T00:00:00+00:00" if ready else None)
        for sid, qid, value, *rest in grades:
            rid = rest[0] if rest else None
            comment = rest[1] if len(rest) > 1 else None
            self.gs.set_grade(config, data, sid, qid, value, comment=comment, rubric_id=rid)
        for sid, extra in (overall or {}).items():
            data.setdefault("overall", {})[sid] = extra
        session.config_file.save(config)
        session.grades_file.save(data)
        return folder

    def marks_session(self, **kw):
        """Q1 (5), Q2 (5), choice group of Q3/Q4 (4 each, answer 1)."""
        kw.setdefault("groups", [{"id": "g1", "questions": ["q3", "q4"], "answer": 1,
                                  "pick": "best"}])
        overall = {"s001": {"comment": "Revise Q2", **kw.pop("overall", {}).get("s001", {})}}
        return self.make_session(
            "marks", mode="marks",
            questions=_questions(("q1", "Q1", 5, None), ("q2", "Q2", 5, None),
                                 ("q3", "Q3", 4, None), ("q4", "Q4", 4, None)),
            students=[("s001", "Aoki.pdf", "n001"), ("s002", "Baba.pdf", "n002"),
                      ("s003", "Chiba.pdf", None)],
            roster=[{"id": "n001", "name": "Aoki Ren", "external_id": "100001"},
                    {"id": "n002", "name": "Baba Mio", "external_id": "100002"}],
            grades=[("s001", "q1", 4, None, "Good start"), ("s001", "q2", NA),
                    ("s001", "q3", 2), ("s001", "q4", 3),
                    ("s002", "q1", 5), ("s002", "q2", 1), ("s002", "q3", 4), ("s002", "q4", NA),
                    ("s003", "q1", 3)],
            overall=overall, **kw)


class LegacyRecordTests(unittest.TestCase):
    LEGACY = {"assignment": "Mid", "total": 7, "max_total": 10,
              "questions": {"Q1": 3, "Q2": 4}, "comment": "ok",
              "chosen": {"B": ["Q2"]}, "section_bands": {"A": 6}}

    def test_cgw_record_round_trips_unchanged(self):
        result = exam_result_from_dict(dict(self.LEGACY))
        self.assertEqual(result.mode, "")
        self.assertTrue(result.complete)
        self.assertEqual(exam_result_to_dict(result), self.LEGACY)

    def test_old_minimal_record_still_loads(self):
        result = exam_result_from_dict({"assignment": "Mid", "total": 3})
        self.assertEqual((result.total, result.levels, result.not_answered), (3, {}, []))


class NewFieldsPersistenceTests(unittest.TestCase):
    def _payload(self, result_dict):
        gb = Gradebook()
        gb.get_or_create("100001").exam_results["Mid"] = exam_result_from_dict(result_dict)
        tmp = tempfile.mkdtemp(prefix="cam_bridge_db_")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        path = os.path.join(tmp, "acm_database.json")
        save_database(path, gb, {})
        with open(path, encoding="utf-8") as fh:
            return path, json.load(fh)

    def test_cam2_fields_survive_save_and_load(self):
        record = {"assignment": "Mid", "total": 0, "max_total": 0, "questions": {},
                  "comment": "", "chosen": {}, "section_bands": {},
                  "mode": "rubric", "session_id": "abc", "not_answered": ["Q3"],
                  "counted": ["Q1", "Q2"], "complete": False,
                  "levels": {"Q1": {"r1": 6, "r2": NA}, "Q2": {"r1": 5}},
                  "final_levels": {"r1": 6, "r2": 10},
                  "question_comments": {"Q1": "Clear method"}}
        path, payload = self._payload(record)
        self.assertEqual(validate_database_payload(payload), ())
        loaded = load_database(path)["gradebook"].students["100001"].exam_results["Mid"]
        self.assertEqual(exam_result_to_dict(loaded), record)

    def test_validator_flags_wrong_types_in_new_fields(self):
        _, payload = self._payload({"assignment": "Mid"})
        result = payload["gradebook"]["students"][0]["exam_results"][0]
        result.update(complete="yes", not_answered="Q1", final_levels={"r1": "6"},
                      levels={"Q1": {"r1": 2.5}}, question_comments={"Q1": 3})
        codes = {(i.path.rsplit(".", 1)[-1], i.code) for i in validate_database_payload(payload)}
        for expected in [("complete", "expected-boolean"), ("not_answered", "expected-array"),
                         ("*", "expected-integer"), ("*", "expected-string")]:
            self.assertIn(expected, codes)


class ReadSessionTests(_SessionBase):
    def test_marks_session_totals_match_cam2(self):
        folder = self.marks_session()
        session = read_session(folder)
        self.assertEqual((session.exam_name, session.mode, session.max_total),
                         (EXAM, "marks", 14))
        self.assertEqual(session.question_labels, ["Q1", "Q2", "Q3", "Q4"])
        self.assertTrue(session.ready_at)
        aoki, baba, chiba = (p.result for p in session.papers)
        # Not answered counts as 0 and stays out of questions; best 1 of Q3/Q4.
        self.assertEqual(aoki.questions, {"Q1": 4, "Q3": 2, "Q4": 3})
        self.assertEqual(aoki.not_answered, ["Q2"])
        self.assertEqual(aoki.counted, ["Q1", "Q2", "Q4"])
        self.assertEqual((aoki.total, aoki.max_total, aoki.complete), (7, 14, True))
        self.assertEqual(aoki.comment, "Revise Q2")
        self.assertEqual(aoki.question_comments, {"Q1": "Good start"})
        self.assertEqual((baba.total, baba.not_answered), (10, ["Q4"]))
        self.assertFalse(chiba.complete)           # Q2-Q4 ungraded
        self.assertEqual(chiba.total, 3)
        self.assertEqual([p.external_id for p in session.papers], ["100001", "100002", ""])
        self.assertEqual([p.name for p in session.papers], ["Aoki Ren", "Baba Mio", "Chiba"])
        self.assertEqual({p.result.session_id for p in session.papers}, {session.session_id})

    def test_teacher_picks_stays_incomplete_until_chosen(self):
        group = [{"id": "g1", "questions": ["q3", "q4"], "answer": 1, "pick": "teacher"}]
        folder = self.marks_session(groups=group)
        aoki = read_session(folder).papers[0].result
        self.assertFalse(aoki.complete)
        self.assertEqual(aoki.total, 4)             # the open group counts nothing yet
        shutil.rmtree(folder)
        folder = self.marks_session(groups=group, overall={"s001": {"chosen": {"g1": ["q3"]}}})
        aoki = read_session(folder).papers[0].result
        self.assertTrue(aoki.complete)
        self.assertEqual((aoki.total, aoki.counted), (6, ["Q1", "Q2", "Q3"]))

    def test_rubric_session_levels_and_final_levels(self):
        bands = [{"min": 0, "max": 0, "descriptor": ""}, {"min": 1, "max": 8, "descriptor": ""}]
        folder = self.make_session(
            "rubric", mode="rubric",
            rubrics=[{"id": "r1", "name": "Criterion A", "bands": bands},
                     {"id": "r2", "name": "Criterion B", "bands": bands}],
            questions=_questions(("q1", "Q1", 0, ["r1", "r2"]), ("q2", "Q2", 0, ["r1"]),
                                 ("q3", "Q3", 0, ["r2"])),
            students=[("s001", "Aoki.pdf", None)],
            grades=[("s001", "q1", 5, "r1"), ("s001", "q1", 3, "r2"),
                    ("s001", "q2", 6, "r1"), ("s001", "q3", NA)],
            overall={"s001": {"final_levels": {"r2": 4}}})
        session = read_session(folder)
        self.assertEqual(session.rubrics, [{"id": "r1", "name": "Criterion A", "max": 8},
                                           {"id": "r2", "name": "Criterion B", "max": 8}])
        r = session.papers[0].result
        self.assertEqual((r.mode, r.total, r.max_total, r.questions), ("rubric", 0, 0, {}))
        self.assertEqual(r.levels, {"Q1": {"r1": 5, "r2": 3}, "Q2": {"r1": 6}})
        self.assertEqual(r.not_answered, ["Q3"])
        # r1: (5+6)/2 = 5.5 -> 6 (half up, not Python's round-to-even).
        # r2: teacher's 4 beats the suggested (3+0)/2 = 1.5 -> 2.
        self.assertEqual(r.final_levels, {"r1": 6, "r2": 4})

    def test_reading_writes_nothing(self):
        folder = self.marks_session()
        before = {n: os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder)}
        read_session(folder)
        after = {n: os.path.getmtime(os.path.join(folder, n)) for n in os.listdir(folder)}
        self.assertEqual(before, after)

    def test_unreadable_folders_raise_session_error(self):
        empty = os.path.join(self.root, "empty")
        os.makedirs(empty)
        with self.assertRaises(ExamSessionError) as ctx:
            read_session(empty)
        self.assertEqual(ctx.exception.code, "not_a_session_folder")
        folder = self.marks_session()
        with open(os.path.join(folder, "grades.json"), "w", encoding="utf-8") as fh:
            fh.write("{broken")
        with self.assertRaises(ExamSessionError) as ctx:
            read_session(folder)
        self.assertEqual(ctx.exception.code, "file_damaged")

    def test_cam2_engine_does_not_shadow_cams(self):
        import engine
        self.assertTrue(engine.__file__.startswith(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.assertNotIn("exam_grading", engine.__file__)
        self.assertIn("exam_grading", sys.modules["cam2_engine"].__file__)


class RouteSessionTests(_SessionBase):
    def test_external_id_then_name_prefix_then_pool(self):
        session = read_session(self.marks_session())
        matched, pool, auto = route_session(session, {"100001", "100002", "Chiba Sora"})
        self.assertEqual(set(matched), {"100001", "100002", "Chiba Sora"})
        self.assertEqual(matched["100001"].total, 7)
        self.assertEqual(auto, {"Chiba": "Chiba Sora"})   # prefix of the scan name
        self.assertEqual(pool, [])

    def test_unmatched_paper_pools_and_materializes_whole(self):
        session = read_session(self.marks_session())
        matched, pool, _ = route_session(session, {"100001", "100002", "100003"})
        self.assertEqual(set(matched), {"100001", "100002"})
        self.assertEqual(len(pool), 1)
        row = pool[0]
        self.assertEqual((row["csv_key"], row["is_exam"], row["session_student_id"]),
                         ("Chiba", True, "s003"))
        json.dumps(row)                                    # pool rows persist as JSON
        gb = Gradebook()
        result = IngestionPipeline(gb).materialize_exam_row(EXAM, "100003", row)
        self.assertIs(gb.students["100003"].exam_results[EXAM], result)
        self.assertEqual((result.mode, result.complete, result.total), ("marks", False, 3))

    def test_two_papers_for_one_student_never_overwrite(self):
        session = read_session(self.marks_session())
        session.papers[2].external_id = "100001"
        matched, pool, _ = route_session(session, {"100001", "100002"})
        self.assertEqual(matched["100001"].total, 7)       # the first paper keeps the slot
        self.assertEqual([r["session_student_id"] for r in pool], ["s003"])

    def test_no_roster_pools_everything(self):
        session = read_session(self.marks_session())
        matched, pool, _ = route_session(session, set())
        self.assertEqual((matched, len(pool)), ({}, 3))


if __name__ == "__main__":
    unittest.main()
