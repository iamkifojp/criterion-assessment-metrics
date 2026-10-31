"""CAM2 convergence Stage 3 — exams open in CAM2, Sync reads the sessions.

Covers docs/CAM2_EXAM_CONVERGENCE_PLAN.md Stage 3:

  * ``engine.exam_bridge`` helpers: the session folder
    ``<class>/exams/<exam>/``, a handoff CAM2's own ``host.load`` accepts, the
    launch command, finding sessions (``_deleted`` skipped), the change
    fingerprint, rubric name → criterion, scaling to 0-8, name crops and
    moving a deleted exam's folder aside.
  * App side (no Streamlit server; ``app.st`` is a SimpleNamespace over a
    dict, as in tests/test_export_beacon_sync.py): ``launch_exam_setup`` writes the
    handoff and starts CAM2's launcher; Sync reads only sessions sent to CAM,
    files papers by ``external_id``, pools the rest, skips unchanged ones;
    marks and rubric exams band/confirm into CriterionScores, unfinished
    papers held back; permanent delete moves the folder to
    ``exams/_deleted/`` and Sync does not bring it back; rename keeps the
    folder; class-folder CSV walks skip ``exams/``.

Sessions are fictional, built with CAM2's own engine in temp folders.

Run:  python -m unittest tests.test_exam_cam2_host
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import app  # noqa: E402
from engine import Criterion, Gradebook, exam_bridge  # noqa: E402
from test_exam_bridge import NA, _SessionBase, _questions  # noqa: E402

CLASS = "Test MYP Class"
EXAM = "Fictional Midterm"     # the exam name test_exam_bridge sessions carry


class BridgeHelperTests(_SessionBase):
    def test_session_folder_and_folder_name(self):
        self.assertEqual(exam_bridge.folder_name('Y8: Mid / "1". '), 'Y8_ Mid _ _1_')
        self.assertEqual(exam_bridge.folder_name("  "), "Exam")
        self.assertEqual(exam_bridge.session_folder(self.root, "Unit 2 test"),
                         os.path.join(self.root, "exams", "Unit 2 test"))

    def test_handoff_is_what_cam2_accepts(self):
        folder = exam_bridge.session_folder(self.root, EXAM)
        data = exam_bridge.handoff(EXAM, CLASS, folder,
                                   [{"key": "100001", "name": "Aoki Ren"},
                                    {"key": "", "name": "no key"},
                                    {"key": "100002"}])
        path = exam_bridge.write_handoff(os.path.join(self.root, "handoffs"), data)
        # One file per session folder, replaced on the next launch.
        self.assertEqual(path, exam_bridge.write_handoff(
            os.path.join(self.root, "handoffs"), data))
        loaded = exam_bridge.cam2_module("host").load(path)
        self.assertEqual(loaded["exam_name"], EXAM)
        self.assertEqual(loaded["class_name"], CLASS)
        self.assertEqual(os.path.normcase(loaded["session_folder"]),
                         os.path.normcase(os.path.abspath(folder)))
        self.assertEqual(loaded["roster"], [
            {"external_id": "100001", "name": "Aoki Ren"},
            {"external_id": "100002", "name": "100002"}])
        cmd = exam_bridge.launch_command(path, python="py")
        self.assertEqual(cmd, ["py", "-c", exam_bridge._LAUNCH_BOOT,
                               exam_bridge.CAM2_LAUNCHER, "--host", path])
        self.assertTrue(os.path.isfile(exam_bridge.CAM2_LAUNCHER))

    def test_launch_command_loads_cam2_not_a_clashing_engine(self):
        # The portable bundle's embedded Python puts CAM's root (its own
        # `engine`) and the workspace (its own `app.py`) on sys.path and never
        # the script's folder. `-P` (no script folder or working folder on
        # sys.path) plus a decoy folder on PYTHONPATH stands in for that;
        # CAM2's imports must win.
        decoy = os.path.join(self.root, "decoy")
        os.makedirs(os.path.join(decoy, "engine"))
        for rel in (os.path.join("engine", "__init__.py"), "app.py"):
            with open(os.path.join(decoy, rel), "w", encoding="utf-8") as fh:
                fh.write("raise ImportError('decoy module imported')\n")
        env = dict(os.environ, PYTHONPATH=decoy,
                   CAM2_APP_DATA=os.path.join(self.root, "appdata"))

        def run(cmd):
            return subprocess.run([cmd[0], "-P", *cmd[1:]], cwd=decoy, env=env,
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")

        plain = run([sys.executable, exam_bridge.CAM2_LAUNCHER, "--help"])
        self.assertIn("decoy module imported", plain.stderr)   # the hazard
        cmd = exam_bridge.launch_command("unused.json")
        cmd[cmd.index("--host"):] = ["--help"]
        result = run(cmd)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Start CAM2 Exam Grading", result.stdout)

    def test_find_sessions_and_fingerprint(self):
        exams = os.path.join(self.root, "class", "exams")
        os.makedirs(os.path.join(exams, "not a session"))
        os.makedirs(os.path.join(exams, "_deleted"))
        self.root_backup = self.root
        self.root = exams
        folder = self.marks_session()
        self.root = self.root_backup
        os.rename(folder, os.path.join(exams, "Mid"))
        folder = os.path.join(exams, "Mid")
        self.assertEqual(exam_bridge.find_sessions(os.path.join(self.root, "class")),
                         [os.path.abspath(folder)])
        self.assertEqual(exam_bridge.find_sessions(self.root), [])
        before = exam_bridge.session_fingerprint(folder)
        self.assertEqual(before, exam_bridge.session_fingerprint(folder))
        session, config, grades = self.storage.open_session(folder)
        self.gs.set_grade(config, grades, "s003", "q2", 2)
        session.grades_file.save(grades)
        self.assertNotEqual(before, exam_bridge.session_fingerprint(folder))

    def test_default_criterion(self):
        cases = {"Criterion B": "B", "criterion d": "D", "Crit. A": "A",
                 "基準Ｃ": "C", "基準 B: 知識": "B", "B": "B",
                 "Critical thinking": None, "Knowing": None, "": None}
        for name, want in cases.items():
            self.assertEqual(exam_bridge.default_criterion(name), want, name)

    def test_to_band(self):
        self.assertEqual(exam_bridge.to_band(6, 8), 6)
        self.assertEqual(exam_bridge.to_band(75, 100), 6)
        self.assertEqual(exam_bridge.to_band(3, 4), 6)
        self.assertEqual(exam_bridge.to_band(1, 16), 1)     # 0.5 rounds half up
        self.assertEqual(exam_bridge.to_band(12, 8), 8)

    def test_name_crop(self):
        folder = os.path.join(self.root, "s")
        os.makedirs(os.path.join(folder, "crops", "__name__"))
        with open(os.path.join(folder, "crops", "__name__", "s001.png"), "wb") as fh:
            fh.write(b"png")
        self.assertTrue(exam_bridge.name_crop(folder, "s001").endswith("s001.png"))
        self.assertEqual(exam_bridge.name_crop(folder, "s002"), "")
        self.assertEqual(exam_bridge.name_crop("", "s001"), "")

    def test_retire_session_moves_only_session_folders_in_exams(self):
        exams = os.path.join(self.root, "class", "exams")
        os.makedirs(exams)
        folder = self.marks_session()
        self.assertIsNone(exam_bridge.retire_session(folder))      # not in exams/
        target = os.path.join(exams, "Mid")
        os.rename(folder, target)
        when = datetime(2026, 11, 1, 9, 30, 0)
        moved = exam_bridge.retire_session(target, when)
        self.assertEqual(moved, os.path.join(exams, "_deleted", "20261101-093000 Mid"))
        self.assertFalse(os.path.exists(target))
        self.assertTrue(self.storage.is_session_folder(moved))
        os.makedirs(os.path.join(exams, "plain"))
        self.assertIsNone(exam_bridge.retire_session(os.path.join(exams, "plain")))


class _AppBase(_SessionBase):
    """A sandboxed CAM: temp class folder, fixture gradebook, persist stubbed."""

    ROSTER = [{"key": "100001", "name": "Aoki Ren"}, {"key": "100002", "name": "Baba Mio"}]

    def setUp(self):
        super().setUp()
        self.class_dir = os.path.join(self.root, "db", CLASS)
        os.makedirs(self.class_dir)
        self.gb = Gradebook()
        self.ss = {
            "prefs": {"db_custom_path": os.path.join(self.root, "db")},
            "ingested_files": {},
            "active_class": CLASS,
            "active_term": app.TERMS[0],
            "classes": [{"name": CLASS, "grade": "", "myp_year": "", "subject": ""}],
            "rosters": {CLASS: [dict(e) for e in self.ROSTER]},
            "archived_students": {},
            "work_aliases": {CLASS: {}},
            "unmatched_works": {CLASS: {}},
            "exam_sessions": {},
            "active": {},
            "active_by_term": {},
            "archived": set(),
            "date_override": {},
            "late_flags": {},
            "excused_flags": {},
            "sel_assignment": None,
        }
        patches = [
            mock.patch.object(app, "st", SimpleNamespace(session_state=self.ss)),
            mock.patch.object(app, "gb", lambda: self.gb),
            mock.patch.object(app, "class_data_dir", lambda name, create=False: (
                self.class_dir if name == CLASS else os.path.join(self.root, "db", name))),
            mock.patch.object(app, "persist", lambda *a, **k: None),
            mock.patch.object(app, "CAM2_HANDOFF_DIR", os.path.join(self.root, "handoffs")),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def hosted(self, maker, folder_name=EXAM, **kw):
        """Build a session with ``maker`` and put it where CAM hosts it."""
        folder = maker(**kw)
        target = os.path.join(self.class_dir, "exams", folder_name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.rename(folder, target)
        return target

    def rubric_session(self, **kw):
        kw.setdefault("grades", [("s001", "q1", 5, "r1"), ("s001", "q1", 3, "r2"),
                                 ("s001", "q2", 7, "r1"),
                                 ("s002", "q1", 6, "r1")])   # s002 has no r2 level
        rubrics_mod = exam_bridge.cam2_module("rubrics")

        def norm(raw):
            return dict(rubrics_mod.normalize_rubric(raw), id=raw["id"])

        return self.make_session(
            "rubric", mode="rubric",
            questions=_questions(("q1", "Q1", 0, ["r1", "r2"]), ("q2", "Q2", 0, ["r1"])),
            rubrics=[norm({"id": "r1", "name": "Criterion A",
                           "bands": [{"levels": "0"}, {"levels": "1–8"}]}),
                     norm({"id": "r2", "name": "基準Ｃ",
                           "bands": [{"levels": "0"}, {"levels": "1–4"}]})],
            students=[("s001", "Aoki.pdf", "n001"), ("s002", "Baba.pdf", "n002")],
            roster=[{"id": "n001", "name": "Aoki Ren", "external_id": "100001"},
                    {"id": "n002", "name": "Baba Mio", "external_id": "100002"}],
            **kw)

    def sync(self):
        summary = {"found": 0, "ingested": 0, "updated": 0, "skipped": 0,
                   "errors": 0, "scores": 0, "classes": set(), "messages": []}
        changed = app._sync_cam2_sessions(CLASS, self.ss["ingested_files"], summary)
        return summary, changed


class LaunchTests(_AppBase):
    def test_launch_writes_handoff_and_starts_cam2(self):
        started = {}

        def fake_popen(cmd, **kw):
            started["cmd"], started["kw"] = cmd, kw
            return SimpleNamespace(poll=lambda: 0)

        with mock.patch.object(app.subprocess, "Popen", fake_popen):
            msg = app.launch_exam_setup("Unit: 3 test")
        self.assertIn("opened in CAM2", msg)
        cmd = started["cmd"]
        self.assertEqual(cmd[3:5], [exam_bridge.CAM2_LAUNCHER, "--host"])
        self.assertEqual(started["kw"]["cwd"], exam_bridge.CAM2_DIR)
        handoff = exam_bridge.cam2_module("host").load(cmd[5])
        folder = os.path.join(self.class_dir, "exams", "Unit_ 3 test")
        self.assertEqual(os.path.normcase(handoff["session_folder"]), os.path.normcase(folder))
        self.assertEqual([r["external_id"] for r in handoff["roster"]], ["100001", "100002"])
        # The exams/ folder exists; the session folder is CAM2's to create.
        self.assertTrue(os.path.isdir(os.path.dirname(folder)))
        self.assertFalse(os.path.exists(folder))
        self.assertEqual(self.ss["exam_sessions"][CLASS]["Unit: 3 test"]["folder"], "Unit_ 3 test")
        # The handoff (it holds the class list) is not in the cloud folder.
        self.assertFalse(cmd[5].startswith(self.class_dir))

    def test_second_exam_with_same_folder_name_gets_its_own(self):
        self.ss["exam_sessions"][CLASS] = {"Mid:1": {"folder": "Mid_1"}}
        with mock.patch.object(app.subprocess, "Popen",
                               lambda cmd, **kw: SimpleNamespace(poll=lambda: 0)):
            app.launch_exam_setup("Mid_1")
        self.assertEqual(self.ss["exam_sessions"][CLASS]["Mid_1"]["folder"], "Mid_1 (2)")

    def test_failed_start_reports_the_log(self):
        def fake_popen(cmd, stdout=None, **kw):
            stdout.write("ModuleNotFoundError: No module named 'flask'\n")
            stdout.flush()
            return SimpleNamespace(poll=lambda: 1)

        with mock.patch.object(app.subprocess, "Popen", fake_popen):
            self.assertEqual(app.launch_exam_setup("Mid"), "")
        kind, text = self.ss["save_status"]
        self.assertEqual(kind, "error")
        self.assertIn("No module named 'flask'", text)


class SyncTests(_AppBase):
    def test_session_not_sent_to_cam_is_left_alone(self):
        self.hosted(self.marks_session, ready=False)
        summary, changed = self.sync()
        self.assertEqual((summary["found"], changed), (0, (False, False)))
        self.assertEqual(self.gb.assignments, [])
        self.assertEqual(self.ss["ingested_files"], {})

    def test_marks_session_files_papers_and_pools_the_rest(self):
        folder = self.hosted(self.marks_session)
        open(self._crop(folder, "s003"), "wb").close()
        summary, changed = self.sync()
        self.assertEqual((summary["ingested"], changed), (1, (True, True)))
        asg = self.gb.assignments[0]
        self.assertEqual((asg.name, asg.class_name, asg.is_exam, asg.max_total),
                         (EXAM, CLASS, True, 14))
        self.assertEqual(asg.question_labels, ["Q1", "Q2", "Q3", "Q4"])
        aoki = self.gb.students["100001"].exam_results[EXAM]
        self.assertEqual((aoki.mode, aoki.total, aoki.not_answered), ("marks", 7, ["Q2"]))
        self.assertIn("100002", self.gb.students)
        pool = self.ss["unmatched_works"][CLASS][EXAM]
        self.assertEqual([r["session_student_id"] for r in pool], ["s003"])
        meta = self.ss["exam_sessions"][CLASS][EXAM]
        self.assertEqual((meta["folder"], meta["mode"]), (EXAM, "marks"))
        self.assertEqual(meta["papers"], {"100001": "s001", "100002": "s002"})
        rec = self.ss["ingested_files"][folder]
        self.assertEqual((rec["kind"], rec["assignment"], rec["class"]), ("cam2", EXAM, CLASS))
        # The 🧩 tile shows the pooled paper's name crop from the session.
        with mock.patch.object(app, "_render_work_png", lambda path, width: path.encode()):
            png, note = app._exam_pool_thumbnail(CLASS, EXAM, pool[0], 400)
        self.assertTrue(png.decode().endswith("s003.png"), note)
        # Matching it in Window 2 files CAM2's result, as read, and an alias.
        self.assertTrue(app.assign_work(CLASS, EXAM, pool[0]["csv_key"], "100003"))
        matched = self.gb.students["100003"].exam_results[EXAM]
        self.assertEqual((matched.mode, matched.session_id), ("marks", aoki.session_id))
        self.assertEqual(self.ss["work_aliases"][CLASS], {pool[0]["csv_key"]: "100003"})
        self.assertNotIn(CLASS, self.ss["unmatched_works"])
        # Unchanged: skipped, nothing re-filed.
        summary, changed = self.sync()
        self.assertEqual((summary["skipped"], summary["ingested"], changed),
                         (1, 0, (False, False)))

    def _crop(self, folder, sid):
        os.makedirs(os.path.join(folder, "crops", "__name__"), exist_ok=True)
        return os.path.join(folder, "crops", "__name__", f"{sid}.png")

    def test_changed_session_updates_and_keeps_applied_grades(self):
        folder = self.hosted(self.marks_session)
        self.sync()
        asg = self.gb.assignments[0]
        results = app._exam_results_for(EXAM)
        for s, _r in results:
            self.ss[f"band_{EXAM}_{s.student_id}"] = 5
        self.assertEqual(app._apply_exam_bands(asg, "B", results), 2)
        session, config, grades = self.storage.open_session(folder)
        self.gs.set_grade(config, grades, "s001", "q2", 5)
        session.grades_file.save(grades)
        summary, _ = self.sync()
        self.assertEqual(summary["updated"], 1)
        self.assertEqual(self.gb.students["100001"].exam_results[EXAM].total, 12)
        self.assertEqual(len(self.gb.assignments), 1)
        self.assertEqual([sc.value for sc in self.gb.students["100001"].scores[Criterion.B]], [5])

    def test_unfinished_marks_paper_is_not_banded(self):
        self.ROSTER = self.ROSTER + [{"key": "100003", "name": "Chiba"}]
        self.ss["rosters"][CLASS].append({"key": "100003", "name": "Chiba"})
        self.ss["work_aliases"][CLASS] = {"Chiba.pdf": "100003", "Chiba": "100003"}
        self.hosted(self.marks_session)
        self.sync()
        chiba = self.gb.students["100003"].exam_results[EXAM]
        self.assertFalse(chiba.complete)
        results = app._exam_results_for(EXAM)
        for s, _r in results:
            self.ss[f"band_{EXAM}_{s.student_id}"] = 4
        self.assertEqual(app._apply_exam_bands(self.gb.assignments[0], "A", results), 2)
        self.assertEqual(self.gb.students["100003"].scores.get(Criterion.A, []), [])

    def test_rubric_exam_confirms_levels_per_mapped_criterion(self):
        self.hosted(self.rubric_session)
        self.sync()
        asg = self.gb.assignments[0]
        meta = self.ss["exam_sessions"][CLASS][EXAM]
        self.assertEqual([(r["id"], r["max"]) for r in meta["rubrics"]], [("r1", 8), ("r2", 4)])
        self.assertEqual([exam_bridge.default_criterion(r["name"]) for r in meta["rubrics"]],
                         ["A", "C"])
        aoki = self.gb.students["100001"].exam_results[EXAM]
        self.assertEqual(aoki.final_levels, {"r1": 6, "r2": 3})
        results = app._exam_results_for(EXAM)
        # What the panel's dropdowns hold: CAM2's levels, r2 scaled 0-4 → 0-8.
        self.ss[f"rband_{EXAM}_100001_r1"] = 6
        self.ss[f"rband_{EXAM}_100001_r2"] = exam_bridge.to_band(3, 4)
        self.ss[f"rband_{EXAM}_100002_r1"] = 6
        applied = app._apply_exam_rubric_levels(asg, {"r1": "A", "r2": "C"}, results)
        # Baba's Q2 has no level yet: not finished in CAM2, so held back.
        self.assertFalse(self.gb.students["100002"].exam_results[EXAM].complete)
        self.assertEqual(applied, 1)
        self.assertEqual(self.gb.students["100002"].scores.get(Criterion.A, []), [])
        self.assertEqual([sc.value for sc in self.gb.students["100001"].scores[Criterion.A]], [6])
        self.assertEqual([sc.value for sc in self.gb.students["100001"].scores[Criterion.C]], [6])
        self.assertEqual(asg.criteria, ["A", "C"])

    def test_permanent_delete_moves_folder_aside_and_sync_leaves_it(self):
        folder = self.hosted(self.marks_session)
        self.sync()
        app.delete_assignment_permanent(EXAM)
        self.assertFalse(os.path.exists(folder))
        deleted = os.listdir(os.path.join(self.class_dir, "exams", "_deleted"))
        self.assertEqual(len(deleted), 1)
        self.assertTrue(deleted[0].endswith(" " + EXAM))
        self.assertNotIn(EXAM, self.ss["exam_sessions"].get(CLASS, {}))
        self.assertNotIn(EXAM, self.ss["unmatched_works"][CLASS])
        self.assertEqual(self.ss["ingested_files"], {})
        summary, changed = self.sync()
        self.assertEqual((summary["found"], changed), (0, (False, False)))
        self.assertEqual(self.gb.assignments, [])

    def test_rename_keeps_the_session_folder(self):
        self.hosted(self.marks_session)
        self.sync()
        self.assertTrue(app.rename_assignment(EXAM, "Midterm (renamed)"))
        self.assertEqual(self.ss["exam_sessions"][CLASS]["Midterm (renamed)"]["folder"], EXAM)
        self.assertIn("Midterm (renamed)", self.ss["unmatched_works"][CLASS])
        folder = app.cam2_session_dir(CLASS, "Midterm (renamed)")
        session, config, grades = self.storage.open_session(folder)
        self.gs.set_grade(config, grades, "s001", "q2", 5)
        session.grades_file.save(grades)
        self.sync()
        self.assertEqual([a.name for a in self.gb.assignments], ["Midterm (renamed)"])
        self.assertEqual(
            self.gb.students["100001"].exam_results["Midterm (renamed)"].total, 12)

    def test_class_csv_walk_skips_exams_folder(self):
        os.makedirs(os.path.join(self.class_dir, "exams", "Mid", "reports"))
        os.makedirs(os.path.join(self.class_dir, "sub"))
        seen = [os.path.relpath(d, self.class_dir) for d, _dirs, _f in app._walk_class(self.class_dir)]
        self.assertEqual(sorted(seen), [".", "sub"])

    def test_broken_session_is_reported_not_filed(self):
        folder = self.hosted(self.marks_session)
        with open(os.path.join(folder, "grades.json"), "w", encoding="utf-8") as fh:
            json.dump({"format": "cam2-grades", "session_id": "someone-else"}, fh)
        summary, _ = self.sync()
        self.assertEqual(summary["errors"], 1)
        self.assertEqual(self.gb.assignments, [])


class SendPickupTests(_AppBase):
    """CAM2 sends are found by comparing each exam folder with CAM's record,
    so nothing depends on CAM having been open, awake or on that class."""

    def setUp(self):
        super().setUp()
        self.rerun = mock.Mock()
        for p in (mock.patch.object(app.st, "rerun", self.rerun, create=True),
                  mock.patch.object(app, "_report_sync", lambda summary: None),
                  mock.patch.object(app, "ensure_class_context", lambda: None),
                  mock.patch.object(app, "_heal_score_comments_from_mirrors", lambda: None)):
            p.start()
            self.addCleanup(p.stop)
        self.poll = app._cam2_send_poller.__wrapped__   # the fragment body

    def _bump(self, folder):
        """Move both session files' times on, as a later save would."""
        for name in (self.storage.SESSION_FILE, self.storage.GRADES_FILE):
            path = os.path.join(folder, name)
            info = os.stat(path)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))

    def send(self, folder, when="2026-11-01T10:00:00+00:00", grade=None):
        """CAM2's "Send to CAM" (optionally after changing one grade)."""
        session, config, grades = self.storage.open_session(folder)
        if grade:
            self.gs.set_grade(config, grades, *grade)
            session.grades_file.save(grades)
        config["host_ready_at"] = when
        session.config_file.save(config)
        self._bump(folder)

    def reads(self):
        return mock.patch.object(app.exam_bridge, "read_session",
                                 wraps=app.exam_bridge.read_session)

    def test_send_for_a_class_not_on_screen(self):
        self.ss["classes"].append({"name": "Other", "grade": "", "myp_year": "",
                                   "subject": ""})
        self.ss["active_class"] = "Other"
        self.hosted(self.marks_session)              # sent before CAM looked
        self.poll()
        self.assertEqual([a.name for a in self.gb.assignments], [EXAM])
        self.rerun.assert_called_once()

    def test_send_and_resend_found_after_a_restart(self):
        folder = self.hosted(self.marks_session, ready=False)
        self.poll()
        self.poll()
        self.assertEqual(self.gb.assignments, [])
        self.send(folder)
        self.poll()
        self.assertEqual(self.gb.students["100001"].exam_results[EXAM].total, 7)
        # CAM restarts: session-only state is gone, the registry (saved in the
        # database) is not.
        self.ss.pop("cam2_checked", None)
        with self.reads() as read:
            self.poll()
            read.assert_not_called()                 # unchanged: stats only
            self.send(folder, "2026-11-01T11:00:00+00:00", grade=("s001", "q1", 5))
            self.poll()
            read.assert_called_once()
        self.assertEqual(self.gb.students["100001"].exam_results[EXAM].total, 8)
        self.assertEqual(self.ss["ingested_files"][folder]["ready_at"],
                         "2026-11-01T11:00:00+00:00")
        self.assertEqual(self.rerun.call_count, 2)

    def test_unsent_session_is_read_once_per_change(self):
        folder = self.hosted(self.marks_session, ready=False)
        with self.reads() as read:
            for _ in range(3):
                self.poll()
            self.assertEqual(read.call_count, 1)
            session, config, grades = self.storage.open_session(folder)
            self.gs.set_grade(config, grades, "s002", "q1", 2)
            session.grades_file.save(grades)
            self._bump(folder)
            self.poll()
            self.poll()
            self.assertEqual(read.call_count, 2)
        self.assertEqual(self.gb.assignments, [])
        self.rerun.assert_not_called()

    def test_broken_session_is_reported_once(self):
        folder = self.hosted(self.marks_session)
        with open(os.path.join(folder, "grades.json"), "w", encoding="utf-8") as fh:
            json.dump({"format": "cam2-grades", "session_id": "someone-else"}, fh)
        self.poll()
        self.poll()
        self.rerun.assert_called_once()
        self.assertIn("could not be read", app._cam2_status(CLASS, EXAM))

    def test_status_line(self):
        self.assertEqual(app._cam2_status(CLASS, EXAM), "Not opened in CAM2 yet.")
        folder = self.hosted(self.marks_session, ready=False)
        self.poll()
        self.assertEqual(app._cam2_status(CLASS, EXAM), "Not sent from CAM2 yet.")
        self.send(folder)
        self.poll()
        line = app._cam2_status(CLASS, EXAM)
        self.assertIn("Sent from CAM2 Nov 01", line)
        self.assertIn("in CAM since", line)
        # "Not finished after all" in CAM2: the last results sent stay.
        session, config, _ = self.storage.open_session(folder)
        config["host_ready_at"] = None
        session.config_file.save(config)
        self._bump(folder)
        self.poll()
        self.assertIn("Marked not finished in CAM2", app._cam2_status(CLASS, EXAM))
        self.assertIn(EXAM, self.gb.students["100001"].exam_results)


if __name__ == "__main__":
    unittest.main()
