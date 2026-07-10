"""
Local JSON persistence layer for Art Criterion Metrics.

The dashboard keeps a full academic year of MYP grade evidence in memory while
running. This module pins that state to disk in a single human-readable file
(:data:`DEFAULT_DB_FILENAME`) so that nothing is lost between sessions, terms,
or accidental browser refreshes: on boot the app loads the file automatically,
and every mutation is mirrored straight back to it.

The persisted payload has two halves:

    {
      "version": 1,
      "saved_at": "<iso timestamp>",
      "gradebook": { students[], assignments[] },   # the durable evidence
      "session":   { teacher-side overrides & UI state }
    }

``serialize_gradebook`` / ``deserialize_gradebook`` handle the durable half and
are deliberately self-contained (no Streamlit, no app imports) so they can be
unit-tested and reused by any front end. The ``session`` half is an opaque,
JSON-safe dict the caller hands in and gets back verbatim.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from typing import Any, Dict, Optional

from .models import (
    Assignment,
    Criterion,
    CriterionScore,
    ExamResult,
    Gradebook,
    Student,
    UnitPlan,
)

# The schema version lets future loaders migrate older files gracefully.
SCHEMA_VERSION = 1

# Default filename, resolved next to the project root by the caller.
DEFAULT_DB_FILENAME = "acm_database.json"


# --------------------------------------------------------------------------
# Gradebook <-> dict
# --------------------------------------------------------------------------

def _score_to_dict(sc: CriterionScore) -> Dict[str, Any]:
    return {
        "criterion": sc.criterion.value,
        "value": sc.value,
        "timestamp": sc.timestamp.isoformat(),
        "source": sc.source,
        "assignment": sc.assignment,
        "keywords": list(sc.keywords),
        "comment": sc.comment,
        "is_valid": sc.is_valid,
        "include_in_report": sc.include_in_report,
        "note": sc.note,
        "late": sc.late,
    }


def _score_from_dict(d: Dict[str, Any]) -> CriterionScore:
    return CriterionScore(
        criterion=Criterion(d["criterion"]),
        value=int(d["value"]),
        timestamp=datetime.fromisoformat(d["timestamp"]),
        source=d.get("source", ""),
        assignment=d.get("assignment", ""),
        keywords=list(d.get("keywords", [])),
        comment=d.get("comment", ""),
        is_valid=bool(d.get("is_valid", True)),
        include_in_report=bool(d.get("include_in_report", True)),
        note=d.get("note", ""),
        late=bool(d.get("late", False)),
    )


def _assignment_to_dict(a: Assignment) -> Dict[str, Any]:
    return {
        "name": a.name,
        "criteria": list(a.criteria),
        "source_file": a.source_file,
        "ingested_at": a.ingested_at.isoformat() if a.ingested_at else None,
        "score_count": a.score_count,
        "note": a.note,
        "class_name": getattr(a, "class_name", ""),
        "term": getattr(a, "term", ""),
        "folder_ref": getattr(a, "folder_ref", ""),
        "grading_complete": bool(getattr(a, "grading_complete", False)),
        "is_exam": bool(getattr(a, "is_exam", False)),
        "max_total": int(getattr(a, "max_total", 0)),
        "question_labels": list(getattr(a, "question_labels", [])),
    }


def _assignment_from_dict(d: Dict[str, Any]) -> Assignment:
    raw = d.get("ingested_at")
    return Assignment(
        name=d["name"],
        criteria=list(d.get("criteria", [])),
        source_file=d.get("source_file", ""),
        ingested_at=datetime.fromisoformat(raw) if raw else None,
        score_count=int(d.get("score_count", 0)),
        note=d.get("note", ""),
        class_name=d.get("class_name", ""),
        term=d.get("term", ""),
        folder_ref=d.get("folder_ref", ""),
        grading_complete=bool(d.get("grading_complete", False)),
        is_exam=bool(d.get("is_exam", False)),
        max_total=int(d.get("max_total", 0)),
        question_labels=list(d.get("question_labels", [])),
    )


def _exam_result_to_dict(r: ExamResult) -> Dict[str, Any]:
    return {
        "assignment": r.assignment,
        "total": r.total,
        "max_total": r.max_total,
        "questions": dict(r.questions),
        "comment": r.comment,
    }


def _exam_result_from_dict(d: Dict[str, Any]) -> ExamResult:
    return ExamResult(
        assignment=d["assignment"],
        total=int(d.get("total", 0)),
        max_total=int(d.get("max_total", 0)),
        questions={str(k): int(v) for k, v in (d.get("questions") or {}).items()},
        comment=d.get("comment", ""),
    )


def unit_plan_to_dict(plan: UnitPlan) -> Dict[str, Any]:
    """Convert a :class:`UnitPlan` into a JSON-safe dict.

    Every field is already a JSON-safe scalar / list / dict; ``source_file`` is
    kept as informational text (which document the plan was parsed from).
    """
    return {
        "unit_title": plan.unit_title,
        "statement_of_inquiry": plan.statement_of_inquiry,
        "target_criteria": dict(plan.target_criteria),
        "key_concepts": list(plan.key_concepts),
        "myp_year": plan.myp_year,
        "source_file": plan.source_file,
    }


# Boilerplate template labels that leaked into some already-persisted plans via
# an older _split_concepts drop-set (fixed in engine/docx_parser.py). Filtered on
# read so old databases stop surfacing "Related concept(s)" as a key concept.
_CONCEPT_BOILERPLATE = {
    "key concept", "key concept(s)", "related concept", "related concepts",
    "related concept(s)", "concepts",
}


def unit_plan_from_dict(d: Dict[str, Any]) -> UnitPlan:
    """Rebuild a :class:`UnitPlan` from a dict produced by
    :func:`unit_plan_to_dict`. Defensive about types so a malformed entry can be
    skipped by the caller rather than crashing the whole load."""
    tc = d.get("target_criteria") or {}
    concepts = [str(c) for c in (d.get("key_concepts") or [])
                if str(c).strip()
                and str(c).strip().lower() not in _CONCEPT_BOILERPLATE]
    myp = d.get("myp_year")
    return UnitPlan(
        unit_title=str(d.get("unit_title", "")),
        statement_of_inquiry=str(d.get("statement_of_inquiry", "")),
        target_criteria={str(k): str(v) for k, v in tc.items()}
        if isinstance(tc, dict) else {},
        key_concepts=concepts,
        myp_year=str(myp) if myp else None,
        source_file=str(d.get("source_file", "")),
    )


def serialize_gradebook(gradebook: Gradebook) -> Dict[str, Any]:
    """Convert a :class:`Gradebook` into a JSON-safe dict."""
    students = []
    for student in gradebook:
        scores = [
            _score_to_dict(sc)
            for bucket in student.scores.values()
            for sc in bucket
        ]
        students.append({
            "student_id": student.student_id,
            "name": student.name,
            "gender": getattr(student, "gender", ""),
            "scores": scores,
            "exam_results": [
                _exam_result_to_dict(r)
                for r in getattr(student, "exam_results", {}).values()
            ],
        })
    assignments = [_assignment_to_dict(a) for a in gradebook.assignments]
    return {"students": students, "assignments": assignments}


def deserialize_gradebook(data: Dict[str, Any]) -> Gradebook:
    """Rebuild a :class:`Gradebook` from a dict produced by
    :func:`serialize_gradebook`. Score buckets are repopulated through
    ``Student.add_score`` so they stay chronologically sorted."""
    gb = Gradebook()
    for sd in data.get("students", []):
        student = Student(student_id=str(sd["student_id"]), name=sd.get("name", ""),
                          gender=sd.get("gender", ""))
        gb.students[student.student_id] = student
        for raw in sd.get("scores", []):
            try:
                student.add_score(_score_from_dict(raw))
            except (KeyError, ValueError, TypeError):
                # Skip a single corrupt score rather than lose the whole file.
                continue
        for raw in sd.get("exam_results", []):
            try:
                result = _exam_result_from_dict(raw)
                student.exam_results[result.assignment] = result
            except (KeyError, ValueError, TypeError):
                continue
    for raw in data.get("assignments", []):
        try:
            gb.register_assignment(_assignment_from_dict(raw))
        except (KeyError, ValueError, TypeError):
            continue
    return gb


# --------------------------------------------------------------------------
# Whole-database file I/O
# --------------------------------------------------------------------------

def build_payload(gradebook: Gradebook, session: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """Assemble the full on-disk payload (gradebook + opaque session dict)."""
    return {
        "version": SCHEMA_VERSION,
        "saved_at": datetime.now().isoformat(),
        "gradebook": serialize_gradebook(gradebook),
        "session": session or {},
    }


def save_database(path: str, gradebook: Gradebook,
                  session: Optional[Dict[str, Any]] = None) -> str:
    """Atomically write the gradebook + session state to ``path``.

    The write goes to a temp file in the same directory and is then renamed
    over the target, so a crash mid-write can never corrupt an existing save.
    Returns the path written.
    """
    payload = build_payload(gradebook, session)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path


def load_database(path: str) -> Optional[Dict[str, Any]]:
    """Load a saved database file.

    Returns a dict ``{"gradebook": Gradebook, "session": {...},
    "saved_at": str}`` or ``None`` when the file is absent or unreadable.
    A malformed file returns ``None`` instead of raising, so a corrupt save
    degrades to "start empty" rather than crashing the app.
    """
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return None
    gb = deserialize_gradebook(payload.get("gradebook", {}))
    return {
        "gradebook": gb,
        "session": payload.get("session", {}),
        "saved_at": payload.get("saved_at", ""),
        "version": payload.get("version", 0),
    }


# --------------------------------------------------------------------------
# Per-class finalized term summaries (cloud "class folder" files)
# --------------------------------------------------------------------------
#
# When a teacher finalizes a term, each student's polished report-card comment
# is snapshotted into a small per-class JSON file that lives alongside the main
# database (typically a OneDrive / Google Drive folder). Keeping summaries in a
# *separate* file per class — rather than inside acm_database.json — means the
# prompt engine can fold a completed term's narrative into the next term's
# context without re-loading the whole gradebook, and a class's history travels
# as its own portable artifact. Shape on disk:
#
#     {
#       "class_name": "1-4",
#       "updated_at": "<iso>",
#       "terms": { "Term 1": { "<student_id>": "<finalized comment>", ... } }
#     }

# Filename prefix for the per-class summary files.
TERM_SUMMARY_PREFIX = "acm_term_summaries_"


def _safe_class_token(class_name: str) -> str:
    """Filesystem-safe token for a class name (keeps alnum, dash, underscore)."""
    token = "".join(
        ch if (ch.isalnum() or ch in "-_") else "_" for ch in (class_name or "")
    ).strip("_")
    return token or "class"


def term_summary_path(folder: str, class_name: str) -> str:
    """Resolve the per-class summary file path inside ``folder``."""
    fname = f"{TERM_SUMMARY_PREFIX}{_safe_class_token(class_name)}.json"
    return os.path.join(folder or ".", fname)


def load_term_summaries(folder: str, class_name: str) -> Dict[str, Dict[str, str]]:
    """Return ``{term: {student_id: comment}}`` for a class (``{}`` if absent).

    Never raises: a missing or malformed file degrades to an empty mapping so a
    sync hiccup never blocks comment generation.
    """
    path = term_summary_path(folder, class_name)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return {}
    terms = payload.get("terms", {})
    if not isinstance(terms, dict):
        return {}
    # Coerce defensively to the documented shape.
    out: Dict[str, Dict[str, str]] = {}
    for term, by_student in terms.items():
        if isinstance(by_student, dict):
            out[str(term)] = {str(k): str(v) for k, v in by_student.items()}
    return out


def save_term_summary(folder: str, class_name: str, term: str,
                      summaries: Dict[str, str]) -> str:
    """Merge ``summaries`` ({student_id: comment}) for ``term`` into the
    class's summary file and write it atomically. Returns the path written.

    Existing terms are preserved; the named term is replaced wholesale with the
    supplied mapping (empty comments are dropped so blanks never overwrite a
    previously finalized narrative).
    """
    os.makedirs(folder or ".", exist_ok=True)
    existing = load_term_summaries(folder, class_name)
    cleaned = {str(sid): str(text) for sid, text in summaries.items()
               if str(text).strip()}
    existing[str(term)] = cleaned
    payload = {
        "class_name": class_name,
        "updated_at": datetime.now().isoformat(),
        "terms": existing,
    }
    path = term_summary_path(folder, class_name)
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path
