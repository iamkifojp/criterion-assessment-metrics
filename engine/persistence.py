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


# Public wrappers over the per-record (de)serializers, so a caller that needs to
# persist an individual score / assignment / exam result (e.g. the term backup,
# which stores per-class, per-student score lists) can reuse the exact on-disk
# shape ``serialize_gradebook`` produces instead of re-deriving it.

def score_to_dict(sc: CriterionScore) -> Dict[str, Any]:
    """JSON-safe dict for one :class:`CriterionScore` (see ``_score_to_dict``)."""
    return _score_to_dict(sc)


def score_from_dict(d: Dict[str, Any]) -> CriterionScore:
    """Rebuild a :class:`CriterionScore` from :func:`score_to_dict` output."""
    return _score_from_dict(d)


def assignment_to_dict(a: Assignment) -> Dict[str, Any]:
    """JSON-safe dict for one :class:`Assignment` (see ``_assignment_to_dict``)."""
    return _assignment_to_dict(a)


def assignment_from_dict(d: Dict[str, Any]) -> Assignment:
    """Rebuild an :class:`Assignment` from :func:`assignment_to_dict` output."""
    return _assignment_from_dict(d)


def exam_result_to_dict(r: ExamResult) -> Dict[str, Any]:
    """JSON-safe dict for one :class:`ExamResult` (see ``_exam_result_to_dict``)."""
    return _exam_result_to_dict(r)


def exam_result_from_dict(d: Dict[str, Any]) -> ExamResult:
    """Rebuild an :class:`ExamResult` from :func:`exam_result_to_dict` output."""
    return _exam_result_from_dict(d)


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


def db_file_state(path: str) -> str:
    """Classify a database path *without* committing to a full load.

    Returns one of:

    - ``"absent"``     — nothing exists at ``path``.
    - ``"unreadable"`` — a file is present but cannot be opened or parsed as a
      JSON object (a malformed save, a transient lock, or a cloud
      Files-On-Demand placeholder that has not finished downloading).
    - ``"ok"``         — a file is present and parses as a JSON object.

    ``load_database`` deliberately collapses "absent" and "unreadable" into a
    single ``None`` return, which makes it impossible for a caller to tell "no
    database here yet" (a legitimate first run) from "a database is here but we
    could not read it" (do **not** overwrite it with demo state). This helper
    restores that distinction for callers that need it — chiefly the boot
    load-guard — while leaving the ``None`` contract of ``load_database``
    untouched for everyone else.
    """
    if not path or not os.path.exists(path):
        return "absent"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return "unreadable"
    if not isinstance(payload, dict):
        return "unreadable"
    return "ok"


# --------------------------------------------------------------------------
# Per-class teacher-input cloud mirror (cloud "class folder" files)
# --------------------------------------------------------------------------
#
# Each class keeps a small per-class JSON file alongside the main database
# (typically a OneDrive / Google Drive folder) that mirrors every teacher-typed
# input that the app cannot otherwise rebuild from the export CSVs. Keeping this
# in a *separate* file per class — rather than inside acm_database.json — means
# the prompt engine can fold a completed term's narrative into the next term's
# context without re-loading the whole gradebook, a class's history travels as
# its own portable artifact, and (crucially) a DB wipe leaves a durable cloud
# twin of the human-typed content behind for the heal-on-load pass to restore.
#
# The file grew from a v1 "term summaries only" shape into the v2 shape below.
# v1 files (only ``terms``) still load: the extra sections simply come back
# empty. Shape on disk (v2):
#
#     {
#       "version": 2,
#       "class_name": "1-4",
#       "updated_at": "<iso>",
#       "terms":          { "Term 1": { "<sid>": "<overall comment>" } },
#       "remarks":        { "<sid>": "<teacher remarks>" },
#       "effort":         { "Term 1": { "<sid>": 3 } },
#       "final_override": { "<sid>": { "A": 7 } },
#       "score_comments": { "<assignment>": { "<sid>": { "A": "<text>" } } }
#     }
#
# ``load_class_mirror`` / ``save_class_mirror`` are the full-payload accessors;
# ``load_term_summaries`` / ``save_term_summary`` keep their v1 public shape
# (``{term: {sid: comment}}``) by delegating to the full-payload path so the two
# never diverge on disk.

# Filename prefix for the per-class mirror files (kept for on-disk compat).
TERM_SUMMARY_PREFIX = "acm_term_summaries_"

# The five teacher-input sections carried in a v2 mirror:
#   terms          {term: {sid: text}}
#   remarks        {sid: text}
#   effort         {term: {sid: int}}
#   final_override {sid: {crit: int}}
#   score_comments {assignment: {sid: {crit: text}}}
_MIRROR_SECTIONS = (
    "terms", "remarks", "effort", "final_override", "score_comments",
)


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


def _empty_mirror() -> Dict[str, dict]:
    """A fresh, fully-shaped (all sections present, all empty) mirror."""
    return {section: {} for section in _MIRROR_SECTIONS}


def _coerce_int(value: Any) -> Optional[int]:
    """Best-effort int coercion; ``None`` when the value isn't a whole number."""
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_text_by_key(raw: Any) -> Dict[str, str]:
    """``{key: text}`` keeping only non-blank text values (coerced to str)."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in raw.items():
        text = "" if v is None else str(v)
        if text.strip():
            out[str(k)] = text
    return out


def _clean_int_by_key(raw: Any) -> Dict[str, int]:
    """``{key: int}`` dropping values that don't coerce to a whole number."""
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, int] = {}
    for k, v in raw.items():
        num = _coerce_int(v)
        if num is not None:
            out[str(k)] = num
    return out


def _clean_mirror(mirror: Dict[str, Any]) -> Dict[str, dict]:
    """Normalise a (possibly partial/malformed) mirror to the canonical v2
    shape, dropping blank leaves and empty containers so blanks never overwrite
    good data and the files stay churn-free.
    """
    src = mirror if isinstance(mirror, dict) else {}
    out = _empty_mirror()

    # terms: {term: {sid: text}}
    raw_terms = src.get("terms")
    if isinstance(raw_terms, dict):
        for term, by_sid in raw_terms.items():
            cleaned = _clean_text_by_key(by_sid)
            if cleaned:
                out["terms"][str(term)] = cleaned

    # remarks: {sid: text}
    out["remarks"] = _clean_text_by_key(src.get("remarks"))

    # effort: {term: {sid: int}}
    raw_effort = src.get("effort")
    if isinstance(raw_effort, dict):
        for term, by_sid in raw_effort.items():
            cleaned = _clean_int_by_key(by_sid)
            if cleaned:
                out["effort"][str(term)] = cleaned

    # final_override: {sid: {crit: int}}
    raw_fo = src.get("final_override")
    if isinstance(raw_fo, dict):
        for sid, by_crit in raw_fo.items():
            cleaned = _clean_int_by_key(by_crit)
            if cleaned:
                out["final_override"][str(sid)] = cleaned

    # score_comments: {assignment: {sid: {crit: text}}}
    raw_sc = src.get("score_comments")
    if isinstance(raw_sc, dict):
        for assignment, by_sid in raw_sc.items():
            if not isinstance(by_sid, dict):
                continue
            per_student: Dict[str, Dict[str, str]] = {}
            for sid, by_crit in by_sid.items():
                cleaned = _clean_text_by_key(by_crit)
                if cleaned:
                    per_student[str(sid)] = cleaned
            if per_student:
                out["score_comments"][str(assignment)] = per_student

    return out


def load_class_mirror(folder: str, class_name: str) -> Dict[str, dict]:
    """Return the full v2 teacher-input mirror for a class.

    Always returns the canonical shape (all five sections present) with empty
    sections when absent. v1 files (only ``terms``) load transparently — the
    other sections simply come back empty. Never raises: a missing or malformed
    file degrades to an all-empty mirror so a sync hiccup never blocks the app.
    """
    path = term_summary_path(folder, class_name)
    if not os.path.exists(path):
        return _empty_mirror()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError):
        return _empty_mirror()
    if not isinstance(payload, dict):
        return _empty_mirror()
    return _clean_mirror(payload)


def save_class_mirror(folder: str, class_name: str,
                      mirror: Dict[str, Any]) -> str:
    """Write the full v2 mirror for a class atomically. Returns the path.

    ``mirror`` is the complete desired state (any subset of the five sections);
    it is cleaned to the canonical shape — blank leaves and empty containers
    dropped — and written wholesale, replacing the file's previous contents.
    """
    payload = {
        "version": 2,
        "class_name": class_name,
        "updated_at": datetime.now().isoformat(),
        **_clean_mirror(mirror),
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


def load_term_summaries(folder: str, class_name: str) -> Dict[str, Dict[str, str]]:
    """Return ``{term: {student_id: comment}}`` for a class (``{}`` if absent).

    Thin v1-shaped view over :func:`load_class_mirror`. Never raises: a missing
    or malformed file degrades to an empty mapping so a sync hiccup never blocks
    comment generation.
    """
    return load_class_mirror(folder, class_name).get("terms", {})


def save_term_summary(folder: str, class_name: str, term: str,
                      summaries: Dict[str, str]) -> str:
    """Merge ``summaries`` ({student_id: comment}) for ``term`` into the
    class's mirror file and write it atomically. Returns the path written.

    Every other section (remarks, effort, overrides, score comments) and every
    other term is preserved; the named term is replaced wholesale with the
    supplied mapping (empty comments are dropped so blanks never overwrite a
    previously finalized narrative).
    """
    mirror = load_class_mirror(folder, class_name)
    mirror.setdefault("terms", {})[str(term)] = {
        str(sid): str(text) for sid, text in summaries.items()
        if str(text).strip()
    }
    return save_class_mirror(folder, class_name, mirror)
