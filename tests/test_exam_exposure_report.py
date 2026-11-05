"""Phase 0 of the CAM2 engine upgrade: the read-only exposure count.

Sessions and gradebooks here are fictional and live in temp folders. Most are
written by hand so that both file versions can be tested whichever CAM2 is
vendored. One is built with the vendored engine, to prove the hand-written
shapes are the real ones.

Run:  python -m unittest tests.test_exam_exposure_report
"""

import ast
import builtins
import contextlib
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine import exam_bridge  # noqa: E402
from tools import exam_exposure_report as report  # noqa: E402

STUDENT_NAME = "Fictional Aoki Ren"
EXAM_NAME = "Fictional Midterm"


def rubric(rid, name):
    return {"id": rid, "name": name,
            "bands": [{"levels": "0–8", "min": 0, "max": 8, "descriptor": ""}]}


def question(qid, *, mx=None, rubrics=None):
    q = {"id": qid, "label": qid.upper(), "boxes": [], "max": mx}
    if rubrics is not None:
        q["rubric_ids"] = rubrics
    return q


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="cam_exposure_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.students = []

    def session(self, class_name, exam, *, version=1, mode=None, questions=(), rubrics=(),
                grades=None, overall=None, sent=False, papers=("s001",), session_id=None):
        folder = os.path.join(self.root, class_name, "exams", exam)
        os.makedirs(folder)
        session_id = session_id or f"id-{class_name}-{exam}"
        config = {"format": "cam2-session", "version": version, "session_id": session_id,
                  "exam_name": EXAM_NAME, "mode": mode, "rubrics": list(rubrics),
                  "questions": list(questions),
                  "students": [{"id": sid, "source": f"{STUDENT_NAME}.pdf"} for sid in papers],
                  "roster": [{"id": "n001", "name": STUDENT_NAME}],
                  "host_ready_at": "2026-11-01T00:00:00+00:00" if sent else None}
        data = {"format": "cam2-grades", "version": version, "session_id": session_id,
                "grades": grades or {}, "overall": overall or {}}
        with open(os.path.join(folder, "cam2_session.json"), "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        with open(os.path.join(folder, "grades.json"), "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        return folder, session_id

    def graded(self, session_id, assignment, count=1):
        """A fictional student with an exam result and ``count`` gradebook grades."""
        self.students.append({
            "student_id": f"st{len(self.students)}", "name": STUDENT_NAME,
            "exam_results": [{"assignment": assignment, "session_id": session_id}],
            "scores": [{"criterion": "ABCD"[i % 4], "value": 5, "assignment": assignment}
                       for i in range(count)],
        })

    def write_database(self):
        with open(os.path.join(self.root, "acm_database.json"), "w", encoding="utf-8") as fh:
            json.dump({"version": 1, "gradebook": {"students": self.students,
                                                   "assignments": []}}, fh)

    def build(self):
        self.write_database()
        return report.build_report(self.root)


class CountingTests(_Base):
    def test_versions_shapes_and_sent_are_counted_per_class(self):
        self.session("8A", "marks", version=1, mode="marks",
                     questions=[question("q1", mx=10)], sent=True)
        self.session("8A", "rubric", version=1, mode="rubric",
                     questions=[question("q1")], rubrics=[rubric("r1", "Criterion A")])
        self.session("8A", "fresh", version=1)
        self.session("9B", "mixed", version=2,
                     questions=[question("q1", mx=10), question("q2", rubrics=["r1"])],
                     rubrics=[rubric("r1", "Criterion A")], sent=True)
        result = self.build()
        a, b = result.classes["8A"], result.classes["9B"]
        self.assertEqual((a.sessions, a.v1, a.v2), (3, 3, 0))
        self.assertEqual((a.marks, a.rubric, a.mixed, a.not_set), (1, 1, 0, 1))
        self.assertEqual((a.sent, a.not_sent), (1, 2))
        self.assertEqual((b.sessions, b.v1, b.v2, b.mixed, b.sent), (1, 0, 1, 1, 1))
        self.assertEqual(result.total.sessions, 4)
        self.assertEqual(result.database, report.DB_READ)

    def test_version_1_ignores_leftovers_and_version_2_reads_each_question(self):
        # Version 1 rubric: a leftover max means nothing, so it isn't mixed.
        self.session("8A", "v1", version=1, mode="rubric",
                     questions=[question("q1", mx=5), question("q2")],
                     rubrics=[rubric("r1", "Criterion A")])
        # Version 2 that started as Rubric, with a question that gained marks.
        self.session("8A", "v2", version=2, mode="rubric",
                     questions=[question("q1", mx=5), question("q2")],
                     rubrics=[rubric("r1", "Criterion A")])
        a = self.build().classes["8A"]
        self.assertEqual((a.rubric, a.mixed), (1, 1))

    def test_deleted_exams_and_other_folders_are_skipped(self):
        self.session("8A", "real", mode="marks", questions=[question("q1", mx=10)])
        self.session("8A", "_deleted", mode="marks")
        os.makedirs(os.path.join(self.root, "8A", "exams", "no session here"))
        os.makedirs(os.path.join(self.root, "no exams"))
        result = self.build()
        self.assertEqual(result.classes["8A"].sessions, 1)
        self.assertNotIn("no exams", result.classes)

    def test_a_bad_session_counts_as_unreadable_and_the_rest_still_count(self):
        good, _ = self.session("8A", "good", mode="marks", questions=[question("q1", mx=10)])
        for name, damage in (("damaged", "{ not json"), ("other", '{"format": "something"}')):
            folder, _ = self.session("8A", name, mode="marks")
            with open(os.path.join(folder, "cam2_session.json"), "w", encoding="utf-8") as fh:
                fh.write(damage)
        folder, _ = self.session("8A", "no grades", mode="marks")
        os.remove(os.path.join(folder, "grades.json"))
        folder, _ = self.session("8A", "mismatch", mode="marks")
        with open(os.path.join(folder, "grades.json"), "w", encoding="utf-8") as fh:
            json.dump({"format": "cam2-grades", "version": 1, "session_id": "other"}, fh)
        a = self.build().classes["8A"]
        self.assertEqual((a.sessions, a.unreadable, a.marks), (5, 4, 1))

    def test_a_newer_version_is_counted_not_refused(self):
        self.session("8A", "future", version=3, mode="marks", questions=[question("q1", mx=10)])
        a = self.build().classes["8A"]
        self.assertEqual((a.newer, a.unreadable, a.marks), (1, 0, 1))


class ExposureTests(_Base):
    RUBRICS = [rubric("r1", "Criterion A"), rubric("r2", "Criterion C")]
    QUESTIONS = [question("q1", rubrics=["r1"]), question("q2", rubrics=["r2"])]
    LEVELS = {"s001": {"q1": {"value": None, "levels": {"r1": 5}},
                       "q2": {"value": None, "levels": {"r2": 6}}}}

    def rubric_session(self, name="exam", *, overall=None, grades=None, version=1):
        return self.session("8A", name, version=version, mode="rubric",
                            questions=self.QUESTIONS, rubrics=self.RUBRICS,
                            grades=self.LEVELS if grades is None else grades,
                            overall=overall)

    def test_i1_levels_with_no_final_level(self):
        self.rubric_session()
        self.assertEqual(self.build().total.i1_no_final, 1)

    def test_i1_clear_when_every_level_has_a_final(self):
        self.rubric_session(overall={"s001": {"final_levels": {"r1": 6, "r2": 6}}})
        self.assertEqual(self.build().total.i1_no_final, 0)

    def test_i1_ignores_marks_exams_and_ungraded_rubric_exams(self):
        self.session("8A", "marks", mode="marks", questions=[question("q1", mx=10)],
                     grades={"s001": {"q1": {"value": 8}}})
        self.rubric_session("ungraded", grades={})
        self.assertEqual(self.build().total.i1_no_final, 0)

    def test_i1_not_answered_is_not_a_level(self):
        self.rubric_session(grades={"s001": {"q1": {"value": "not_answered"},
                                             "q2": {"value": "not_answered"}}})
        self.assertEqual(self.build().total.i1_no_final, 0)

    def test_i1_reads_older_grades_with_one_value_per_question(self):
        self.session("8A", "old", mode="rubric", rubrics=self.RUBRICS,
                     questions=[{"id": "q1", "label": "Q1", "boxes": [], "rubric_id": "r2"}],
                     grades={"s001": {"q1": {"value": 4}}})
        self.assertEqual(self.build().total.i1_no_final, 1)

    def test_i2_partial_finals_on_an_exam_with_grades_can_delete(self):
        # The plan's I2 table: only C has a typed final level.
        _, sid = self.rubric_session(overall={"s001": {"final_levels": {"r2": 6}}})
        self.graded(sid, EXAM_NAME, count=2)
        total = self.build().total
        self.assertEqual((total.with_grades, total.i2_can_delete, total.i2_grades_at_stake,
                          total.i2_count_only), (1, 1, 2, 0))

    def test_i2_no_finals_keeps_grades_but_loses_the_count(self):
        _, sid = self.rubric_session()
        self.graded(sid, EXAM_NAME, count=2)
        total = self.build().total
        self.assertEqual((total.with_grades, total.i2_can_delete, total.i2_count_only), (1, 0, 1))

    def test_i2_all_finals_typed_is_safe(self):
        _, sid = self.rubric_session(overall={"s001": {"final_levels": {"r1": 6, "r2": 6}}})
        self.graded(sid, EXAM_NAME, count=2)
        total = self.build().total
        self.assertEqual((total.with_grades, total.i2_can_delete, total.i2_count_only), (1, 0, 0))

    def test_i2_one_rubric_can_never_be_partial(self):
        _, sid = self.session("8A", "one", mode="rubric", rubrics=[rubric("r1", "Criterion A")],
                              questions=[question("q1")],
                              grades={"s001": {"q1": {"value": 5}}},
                              overall={"s001": {"final_levels": {"r1": 5}}}, papers=("s001", "s002"))
        self.graded(sid, EXAM_NAME)
        self.assertEqual(self.build().total.i2_can_delete, 0)

    def test_i2_grades_on_another_exam_do_not_count(self):
        _, _sid = self.rubric_session(overall={"s001": {"final_levels": {"r2": 6}}})
        self.graded("some other session", EXAM_NAME, count=4)
        self.students.append({"student_id": "x", "exam_results": [
            {"assignment": EXAM_NAME, "session_id": _sid}],
            "scores": [{"criterion": "A", "value": 5, "assignment": "Another task"}]})
        total = self.build().total
        self.assertEqual((total.with_grades, total.i2_can_delete), (0, 0))

    def test_marks_exams_with_grades_are_not_counted_as_rubric_exams(self):
        _, sid = self.session("8A", "marks", mode="marks", questions=[question("q1", mx=10)])
        self.graded(sid, EXAM_NAME)
        self.assertEqual(self.build().total.with_grades, 0)

    def test_i4_counts_version_1_only(self):
        self.rubric_session("old", version=1)
        self.rubric_session("new", version=2)
        self.assertEqual(self.build().total.i4_upgrades_on_open, 1)

    def test_missing_database_says_so(self):
        self.rubric_session()
        result = report.build_report(self.root)
        self.assertEqual(result.database, report.DB_MISSING)
        self.assertIn("grades already applied are unknown", report.format_report(result))

    def test_damaged_database_says_so_and_sessions_still_count(self):
        self.rubric_session()
        with open(os.path.join(self.root, "acm_database.json"), "w", encoding="utf-8") as fh:
            fh.write("{ not json")
        result = report.build_report(self.root)
        self.assertEqual(result.database, report.DB_UNREADABLE)
        self.assertEqual(result.total.sessions, 1)


class SafetyTests(_Base):
    def tree(self):
        out = {}
        for folder, dirs, files in os.walk(self.root):
            for name in dirs:
                out[os.path.join(folder, name)] = None
            for name in files:
                path = os.path.join(folder, name)
                with open(path, "rb") as fh:
                    digest = hashlib.sha256(fh.read()).hexdigest()
                out[path] = (digest, os.stat(path).st_mtime_ns)
        return out

    def populate(self):
        _, sid = self.session("8A", EXAM_NAME, mode="rubric", questions=[question("q1")],
                              rubrics=[rubric("r1", "Criterion A")],
                              grades={"s001": {"q1": {"value": 5}}})
        self.graded(sid, EXAM_NAME)
        self.write_database()

    def test_nothing_in_the_folder_changes(self):
        self.populate()
        before = self.tree()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(report.main([self.root]), 0)
        self.assertEqual(self.tree(), before)

    def test_files_are_only_ever_opened_for_reading(self):
        self.populate()
        modes = []
        real_open = builtins.open

        def spy(file, mode="r", *args, **kwargs):
            modes.append(mode)
            return real_open(file, mode, *args, **kwargs)

        with mock.patch("builtins.open", spy):
            report.build_report(self.root)
        self.assertTrue(modes)
        self.assertEqual(set(modes), {"rb"})

    def test_output_has_no_student_or_exam_names(self):
        self.populate()
        text = report.format_report(report.build_report(self.root))
        self.assertIn("8A", text)
        for secret in (STUDENT_NAME, EXAM_NAME, "Aoki", "Criterion A"):
            self.assertNotIn(secret, text)

    def test_a_folder_must_be_given_and_must_exist(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            report.main([])
        missing = os.path.join(self.root, "not here")
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(report.main([missing]), 2)

    def test_it_imports_only_the_standard_library_and_never_reads_prefs(self):
        with open(report.__file__, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertEqual(imported - set(sys.stdlib_module_names), set())
        strings = [n.value for n in ast.walk(tree)
                   if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        docstring = ast.get_docstring(tree, clean=False)
        self.assertFalse([s for s in strings
                          if "local_device_prefs" in s and s != docstring])


class RealEngineTests(_Base):
    """A session written by the vendored CAM2 reads the same as a hand-written one."""

    def test_engine_built_rubric_session(self):
        with mock.patch.dict(os.environ, {"CAM2_APP_DATA": os.path.join(self.root, "_appdata")}):
            storage = exam_bridge.cam2_module("storage")
            summary = exam_bridge.cam2_module("grading_summary")
            model = exam_bridge.cam2_module("model")
            folder = os.path.join(self.root, "8A", "exams", "engine")
            os.makedirs(folder)
            session, config, data = storage.create_session(folder, EXAM_NAME)
            config.update(mode="rubric",
                          questions=[question("q1", rubrics=["r1"]), question("q2", rubrics=["r2"])],
                          rubrics=[rubric("r1", "Criterion A"), rubric("r2", "Criterion C")],
                          students=[{"id": "s001", "scan": "scans/s001.pdf", "source": "a.pdf",
                                     "pages": 1, "roster_id": None}])
            summary.set_grade(config, data, "s001", "q1", 5, rubric_id="r1")
            summary.set_grade(config, data, "s001", "q2", 6, rubric_id="r2")
            data.setdefault("overall", {})["s001"] = {"final_levels": {"r2": 6}}
            session.config_file.save(config)
            session.grades_file.save(data)
            self.graded(str(config["session_id"]), EXAM_NAME, count=2)

        counts = self.build().classes["8A"]
        self.assertEqual(counts.sessions, 1)
        self.assertEqual(counts.unreadable, 0)
        self.assertEqual(counts.rubric, 1)
        self.assertEqual(counts.v1 + counts.v2, 1)
        self.assertEqual(counts.v1 == 1, model.VERSION == 1)
        self.assertEqual((counts.i1_no_final, counts.i2_can_delete, counts.i2_grades_at_stake),
                         (1, 1, 2))


if __name__ == "__main__":
    unittest.main()
