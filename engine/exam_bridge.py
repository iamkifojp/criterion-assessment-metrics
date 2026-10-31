"""Reading CAM2 exam sessions into CAM (CAM2 convergence plan, Stage 2).

CAM2 (vendored unmodified at ``exam_grading/``) keeps each exam in a session
folder: ``cam2_session.json`` (set-up, papers, class list) and ``grades.json``.
CAM only ever **reads** that folder. Totals, choice groups and final levels
are worked out by CAM2's own ``grading_summary``, so CAM's numbers always
match what CAM2 shows (round-half-up, best N, teacher picks).

CAM2's package is also called ``engine``, so it is loaded here under the name
``cam2_engine``. Its modules import each other relatively, so nothing inside
``exam_grading/`` changes.

Two steps, kept apart so Sync (Stage 3) can report a broken folder without
touching the gradebook:

* :func:`read_session` turns a folder into an :class:`ExamSession`, one
  :class:`ExamResult` per paper.
* :func:`route_session` files each paper under a roster key: the
  ``external_id`` CAM handed over in host mode (exact), then the usual
  :func:`resolve_identity` (alias, unambiguous prefix) on the paper's name,
  and otherwise the 🧩 pool.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .ingestion import resolve_identity
from .models import EXAM_NOT_ANSWERED, ExamResult
from .persistence import exam_result_to_dict

CAM2_ENGINE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "exam_grading", "engine")
CAM2_PACKAGE = "cam2_engine"


class ExamSessionError(Exception):
    """A session folder CAM cannot read. ``code`` is CAM2's error code
    (e.g. ``not_a_session_folder``, ``file_damaged``, ``session_files_mismatch``,
    ``file_from_newer_version``)."""

    def __init__(self, folder: str, code: str, detail: str = ""):
        self.folder = folder
        self.code = code
        super().__init__(f"{folder}: {detail or code}")


def cam2_module(name: str):
    """One module of CAM2's engine (``"storage"``, ``"grading_summary"``, ...),
    loading the package as ``cam2_engine`` the first time."""
    if CAM2_PACKAGE not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            CAM2_PACKAGE, os.path.join(CAM2_ENGINE_DIR, "__init__.py"),
            submodule_search_locations=[CAM2_ENGINE_DIR])
        package = importlib.util.module_from_spec(spec)
        sys.modules[CAM2_PACKAGE] = package
        spec.loader.exec_module(package)
    return importlib.import_module(f"{CAM2_PACKAGE}.{name}")


@dataclass
class SessionPaper:
    """One student's paper in a session."""

    student_id: str     # CAM2 paper id ("s001"); name crop: crops/__name__/<id>.png
    external_id: str    # CAM roster key handed over in host mode, "" if none
    name: str           # class-list name, else a typed name, else the scan's name
    result: ExamResult


@dataclass
class ExamSession:
    """What CAM needs from one CAM2 session folder."""

    folder: str
    session_id: str
    exam_name: str
    mode: str                           # "marks" or "rubric" ("" before Step 2)
    ready_at: Optional[str]             # host_ready_at: "Send to CAM" was clicked
    question_labels: List[str]
    rubrics: List[Dict[str, str]]       # [{"id": "r1", "name": "Criterion A"}]
    max_total: int                      # marks mode; 0 in rubric mode
    papers: List[SessionPaper] = field(default_factory=list)


def read_session(folder: str, assignment: Optional[str] = None) -> ExamSession:
    """Read a CAM2 session folder. Writes nothing.

    ``assignment`` names the CAM exam the results belong to (default: the
    exam name in the session)."""
    storage = cam2_module("storage")
    summary_mod = cam2_module("grading_summary")
    workflow = cam2_module("workflow")
    errors = cam2_module("errors")
    try:
        _session, config, grades = storage.open_session(folder)
    except errors.UserError as exc:
        raise ExamSessionError(folder, exc.code, str(exc)) from exc

    mode = config.get("mode") or ""
    questions = config.get("questions") or []
    labels = {q["id"]: q["label"] for q in questions}
    roster = {r["id"]: r for r in config.get("roster") or []}
    summaries = {s["student_id"]: s
                 for s in summary_mod.class_summary(config, grades)["students"]}
    assignment = assignment or config.get("exam_name") or ""
    max_total = summary_mod.marks_maximum(config) if mode != "rubric" else 0

    papers = []
    for student in config.get("students") or []:
        sid = student["id"]
        summary = summaries[sid]
        entries = (grades.get("grades") or {}).get(sid) or {}
        result = ExamResult(
            assignment=assignment, mode=mode,
            session_id=str(config.get("session_id") or ""),
            comment=summary.get("comment") or "",
            complete=bool(summary["complete"]),
            counted=[labels[q["id"]] for q in questions if q["id"] in summary["counted"]],
        )
        for q in questions:
            label = labels[q["id"]]
            values = summary_mod.question_values(config, grades, sid, q)
            given = {rid: v for rid, v in values.items() if v is not None}
            if given and all(v == EXAM_NOT_ANSWERED for v in given.values()):
                result.not_answered.append(label)
            elif mode == "rubric" and given:
                result.levels[label] = given
            elif mode != "rubric" and isinstance(given.get(None), int):
                result.questions[label] = given[None]
            comment = str((entries.get(q["id"]) or {}).get("comment") or "").strip()
            if comment:
                result.question_comments[label] = comment
        if mode == "rubric":
            result.final_levels = {rid: r["final"] for rid, r in summary["rubrics"].items()
                                   if r["final"] is not None}
        elif "marks" in summary:
            result.total = int(summary["marks"]["total"])
            result.max_total = max_total
        external = (roster.get(student.get("roster_id")) or {}).get("external_id") or ""
        papers.append(SessionPaper(student_id=sid, external_id=str(external),
                                   name=workflow.display_name(config, student),
                                   result=result))

    return ExamSession(
        folder=os.path.abspath(folder),
        session_id=str(config.get("session_id") or ""),
        exam_name=str(config.get("exam_name") or ""),
        mode=mode,
        ready_at=config.get("host_ready_at"),
        question_labels=[labels[q["id"]] for q in questions],
        rubrics=[{"id": r["id"], "name": r.get("name", "")}
                 for r in config.get("rubrics") or []],
        max_total=max_total,
        papers=papers,
    )


def route_session(session: ExamSession, roster_keys,
                  aliases: Optional[Dict[str, str]] = None,
                  ) -> Tuple[Dict[str, ExamResult], List[dict], Dict[str, str]]:
    """File each paper under a roster key.

    Returns ``(matched, pool, auto_aliases)``: ``matched`` maps roster key to
    result; ``pool`` holds 🧩 rows (exam-flavoured, as from
    :meth:`IngestionPipeline.ingest_exam_csv`, plus the whole ``result`` for
    :meth:`IngestionPipeline.materialize_exam_row`); ``auto_aliases`` are
    prefix matches to record. A paper is pooled, never guessed, when nothing
    matches, when a second paper resolves to the same student, or when there
    is no roster at all."""
    matched: Dict[str, ExamResult] = {}
    pool: List[dict] = []
    auto_aliases: Dict[str, str] = {}
    for paper in session.papers:
        key = paper.external_id or paper.name
        target, auto = (resolve_identity(key, roster_keys, aliases)
                        if roster_keys else (None, None))
        if target is None or target in matched:
            r = paper.result
            pool.append({
                "csv_key": key, "is_exam": True,
                "questions": dict(r.questions), "total": r.total,
                "max_total": r.max_total, "comment": r.comment,
                "result": exam_result_to_dict(r),
                "session_folder": session.folder,
                "session_student_id": paper.student_id,
            })
            continue
        if auto is not None:
            auto_aliases[key] = auto
        matched[target] = paper.result
    return matched, pool, auto_aliases
