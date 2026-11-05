"""Count how many CAM2 exam sessions the engine upgrade would affect.

Phase 0 of docs/CAM2_ENGINE_UPGRADE_PLAN.md. For each class folder under a CAM
data folder (``<data folder>/<class>/exams/<exam>/``) it counts sessions by file
version and grading type, whether they were sent to CAM, and rubric exams that
already have grades in the gradebook. From those it works out how many are
exposed to issues I1, I2 and I4.

    python tools/exam_exposure_report.py <data folder>

This script only reads. It imports nothing from CAM or CAM2, opens files for
reading only, takes no locks, and writes no file anywhere. It prints counts and
class folder names, and never a student's name, an exam's name or a grade.

The data folder is always given by hand and is never taken from
``local_device_prefs.json``, so a test run can't reach real data by accident.
Pointing this at a real data folder needs the teacher's permission (CLAUDE.md).

The rules below for which questions grade with levels mirror CAM2's
``grading_summary`` on both file versions. Run it from a copy if CAM isn't
installed from source: it needs only Python.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, fields
from typing import Dict, List, Optional, Set

EXAMS_DIR = "exams"
SESSION_FILE = "cam2_session.json"
GRADES_FILE = "grades.json"
DATABASE_FILE = "acm_database.json"
SESSION_FORMAT = "cam2-session"
GRADES_FORMAT = "cam2-grades"

DB_READ = "read"
DB_MISSING = "not found"
DB_UNREADABLE = "could not be read"


@dataclass
class Counts:
    """Session counts for one class folder, or for all of them added together."""

    sessions: int = 0
    v1: int = 0
    v2: int = 0
    newer: int = 0
    marks: int = 0
    rubric: int = 0
    mixed: int = 0
    not_set: int = 0
    sent: int = 0
    not_sent: int = 0
    unreadable: int = 0
    # Rubric or mixed exams with at least one grade in the gradebook.
    with_grades: int = 0
    # I1: a paper has levels on a rubric with no final level typed.
    i1_no_final: int = 0
    # I2: has grades, and a paper's final levels cover only some of its rubrics,
    # so Apply on today's CAM can delete a grade.
    i2_can_delete: int = 0
    # I2: has grades and no paper has a typed final level, so Apply keeps the
    # grades but its count of graded students drops to 0.
    i2_count_only: int = 0
    # How many gradebook grades sit on the exams counted in i2_can_delete.
    i2_grades_at_stake: int = 0
    # I4: version 1 sessions, which opening in the new CAM2 upgrades for good.
    i4_upgrades_on_open: int = 0

    def add(self, other: "Counts") -> None:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))


@dataclass
class Report:
    folder: str
    database: str
    classes: Dict[str, Counts]

    @property
    def total(self) -> Counts:
        total = Counts()
        for counts in self.classes.values():
            total.add(counts)
        return total


def _read_json(path: str):
    with open(path, "rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _is_level(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _rubric_ids(config: dict, question: dict) -> List[str]:
    """CAM2's ``question_rubric_ids`` for a question graded with levels."""
    rubrics = config.get("rubrics") or []
    picked = question.get("rubric_ids")
    if picked is None:
        picked = [question["rubric_id"]] if question.get("rubric_id") else []
    wanted = set(picked)
    rids = [r["id"] for r in rubrics if r["id"] in wanted]
    if not rids and len(rubrics) == 1:
        rids = [rubrics[0]["id"]]
    return rids


def _question_shape(config: dict, question: dict, version: int) -> Optional[str]:
    """``"marks"``, ``"rubric"`` or None. In version 1 the exam-wide mode decides
    (a leftover ``max`` or ``rubric_ids`` means nothing); from version 2 the
    question's own shape does."""
    if version < 2:
        mode = config.get("mode")
        if mode == "rubric":
            return "rubric"
        return "marks" if mode == "marks" else None
    if question.get("max"):
        return "marks"
    return "rubric" if _rubric_ids(config, question) else None


def _level_of(config: dict, entry: dict, question: dict, rid: str):
    """CAM2's ``level_of`` for a rubric question."""
    if "levels" in entry:
        return (entry["levels"] or {}).get(rid)
    first = _rubric_ids(config, question)[:1]
    return entry.get("value") if first == [rid] else None


def _grades_by_session(database: dict) -> Dict[str, int]:
    """Session id -> how many gradebook grades belong to that session's exam."""
    out: Dict[str, int] = {}
    for student in (database.get("gradebook") or {}).get("students") or []:
        scores = student.get("scores") or []
        for result in student.get("exam_results") or []:
            session_id = str(result.get("session_id") or "")
            if not session_id:
                continue
            name = result.get("assignment")
            found = sum(1 for sc in scores if sc.get("assignment") == name)
            if found:
                out[session_id] = out.get(session_id, 0) + found
    return out


def _count_session(folder: str, grades_by_session: Dict[str, int], counts: Counts) -> None:
    """Add one session folder to ``counts``. A folder that can't be read counts as
    unreadable and nothing else, so one bad exam can't stop the report."""
    counts.sessions += 1
    try:
        config = _read_json(os.path.join(folder, SESSION_FILE))
        grades = _read_json(os.path.join(folder, GRADES_FILE))
        if config.get("format") != SESSION_FORMAT or grades.get("format") != GRADES_FORMAT:
            raise ValueError("not a CAM2 session")
        version = config.get("version")
        if not _is_level(version) or version < 1:
            raise ValueError("no version")
        if config.get("session_id") != grades.get("session_id"):
            raise ValueError("files from different sessions")
        result = _measure(config, grades, version)
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        counts.unreadable += 1
        return

    if version == 1:
        counts.v1 += 1
        counts.i4_upgrades_on_open += 1
    elif version == 2:
        counts.v2 += 1
    else:
        counts.newer += 1

    shape = result["shape"]
    if shape == "marks":
        counts.marks += 1
    elif shape == "rubric":
        counts.rubric += 1
    elif shape == "mixed":
        counts.mixed += 1
    else:
        counts.not_set += 1

    if config.get("host_ready_at"):
        counts.sent += 1
    else:
        counts.not_sent += 1

    if not result["has_rubric"]:
        return
    if result["gap"]:
        counts.i1_no_final += 1
    found = grades_by_session.get(str(config.get("session_id") or ""), 0)
    if not found:
        return
    counts.with_grades += 1
    if result["partial"]:
        counts.i2_can_delete += 1
        counts.i2_grades_at_stake += found
    elif not result["any_typed"]:
        counts.i2_count_only += 1


def _measure(config: dict, grades: dict, version: int) -> dict:
    """What one session holds, with no names in it."""
    questions = config.get("questions") or []
    shapes = [(q, _question_shape(config, q, version)) for q in questions]
    rubric_questions = [(q, _rubric_ids(config, q)) for q, s in shapes if s == "rubric"]
    has_marks = any(s == "marks" for _, s in shapes)
    has_rubric = bool(rubric_questions)

    if has_marks and has_rubric:
        shape = "mixed"
    elif has_rubric:
        shape = "rubric"
    elif has_marks:
        shape = "marks"
    else:
        # No graded questions yet, so the stored starting choice is all there is.
        shape = config.get("mode") if config.get("mode") in ("marks", "rubric") else None

    used: Set[str] = {rid for _, rids in rubric_questions for rid in rids}
    known = {r["id"] for r in config.get("rubrics") or []}
    gap = partial = any_typed = False
    by_paper = grades.get("grades") or {}
    overall = grades.get("overall") or {}
    papers = {s["id"] for s in config.get("students") or []}
    for sid in papers:
        entries = by_paper.get(sid) or {}
        levelled: Set[str] = set()
        for q, rids in rubric_questions:
            entry = entries.get(q["id"]) or {}
            levelled.update(rid for rid in rids
                            if _is_level(_level_of(config, entry, q, rid)))
        finals = (overall.get(sid) or {}).get("final_levels") or {}
        typed = {rid for rid, v in finals.items() if v is not None and rid in known}
        any_typed = any_typed or bool(typed)
        gap = gap or bool(levelled - typed)
        partial = partial or bool(typed & used and used - typed)

    return {"shape": shape, "has_rubric": has_rubric, "gap": gap,
            "partial": partial, "any_typed": any_typed}


def _session_folders(class_dir: str) -> List[str]:
    """Session folders under ``<class>/exams/``, skipping ``_deleted`` and the like,
    as CAM's ``exam_bridge.find_sessions`` does."""
    root = os.path.join(class_dir, EXAMS_DIR)
    if not os.path.isdir(root):
        return []
    out = []
    for entry in sorted(os.scandir(root), key=lambda e: e.name.lower()):
        if entry.is_dir() and not entry.name.startswith("_") \
                and os.path.isfile(os.path.join(entry.path, SESSION_FILE)):
            out.append(entry.path)
    return out


def build_report(data_folder: str) -> Report:
    """Read a data folder and count what's there. Writes nothing."""
    database_state = DB_MISSING
    grades_by_session: Dict[str, int] = {}
    database_path = os.path.join(data_folder, DATABASE_FILE)
    if os.path.isfile(database_path):
        try:
            grades_by_session = _grades_by_session(_read_json(database_path))
            database_state = DB_READ
        except (OSError, ValueError, AttributeError, KeyError, TypeError):
            database_state = DB_UNREADABLE

    classes: Dict[str, Counts] = {}
    for entry in sorted(os.scandir(data_folder), key=lambda e: e.name.lower()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        folders = _session_folders(entry.path)
        if not folders:
            continue
        counts = Counts()
        for folder in folders:
            _count_session(folder, grades_by_session, counts)
        classes[entry.name] = counts
    return Report(folder=os.path.abspath(data_folder), database=database_state, classes=classes)


_COLUMNS = [
    ("Sessions", "sessions"), ("v1", "v1"), ("v2", "v2"), ("Newer", "newer"),
    ("Marks", "marks"), ("Rubric", "rubric"), ("Mixed", "mixed"), ("Not set", "not_set"),
    ("Sent", "sent"), ("Not sent", "not_sent"), ("With grades", "with_grades"),
    ("Unreadable", "unreadable"),
]


def format_report(report: Report) -> str:
    total = report.total
    rows = [(name, counts) for name, counts in report.classes.items()]
    rows.append(("All classes", total))
    width = max(len(name) for name, _ in rows)
    header = "  ".join([f"{'Class':<{width}}"] + [title for title, _ in _COLUMNS])

    def line(name: str, counts: Counts) -> str:
        cells = [f"{getattr(counts, attr):>{len(title)}}" for title, attr in _COLUMNS]
        return "  ".join([f"{name:<{width}}"] + cells)

    out = [
        "CAM2 exam sessions: counts only, nothing was changed",
        f"Data folder: {report.folder}",
        f"Database:    {report.database}",
        "",
        header,
    ]
    out += [line(name, counts) for name, counts in rows]
    out += [
        "",
        '"With grades" counts rubric and mixed exams that already have gradebook grades.',
        "",
        "Exposure to the engine upgrade (docs/CAM2_ENGINE_UPGRADE_PLAN.md):",
        f"  I1  {total.i1_no_final} session(s) have levels on a paper with no final level typed.",
        "      These reach CAM with nothing to confirm.",
        f"  I2  {total.i2_can_delete} session(s) could lose grades if Apply is pressed again,"
        f" holding {total.i2_grades_at_stake} grade(s) in all.",
        "      Their final levels cover only some of a paper's rubrics. This is an upper limit,",
        "      because Apply only touches rubrics mapped to a criterion.",
        f"      {total.i2_count_only} more keep their grades, but the graded count drops to 0.",
        f"  I4  {total.i4_upgrades_on_open} session(s) are still version 1."
        " Opening one in the new CAM2 upgrades it for good.",
    ]
    if total.v2 or total.newer:
        out += [f"      {total.v2 + total.newer} session(s) are already past version 1."
                " A CAM still on CAM2 version 1 can't read these."]
    if total.unreadable:
        out += ["",
                f"{total.unreadable} session(s) could not be read, and aren't in the exposure counts."]
    if report.database != DB_READ:
        out += ["",
                f"The database {report.database}, so grades already applied are unknown:",
                'the I2 lines and "With grades" read 0 whatever the real figure is.']
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Count CAM2 exam sessions exposed to the engine upgrade. Only reads.")
    parser.add_argument("data_folder", help="the folder holding acm_database.json and class folders")
    args = parser.parse_args(argv)
    if not os.path.isdir(args.data_folder):
        print(f"Not a folder: {args.data_folder}", file=sys.stderr)
        return 2
    print(format_report(build_report(args.data_folder)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
