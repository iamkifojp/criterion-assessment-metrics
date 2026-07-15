"""
Local JSON persistence layer for Art Criterion Metrics.

The dashboard keeps a full academic year of MYP grade evidence in memory while
running. This module pins that state to disk in a single human-readable file
(:data:`DEFAULT_DB_FILENAME`) so that nothing is lost between sessions, terms,
or accidental browser refreshes: on boot the app loads the file automatically,
and every mutation is mirrored straight back to it.

The persisted payload has two halves:

    {
      "version": 2,
      "saved_at": "<iso timestamp>",
      "database_id": "<stable UUID>",
      "generation": 1,
      "gradebook": { students[], assignments[] },   # the durable evidence
      "session":   { teacher-side overrides & UI state }
    }

``serialize_gradebook`` / ``deserialize_gradebook`` handle the durable half and
are deliberately self-contained (no Streamlit, no app imports) so they can be
unit-tested and reused by any front end. The ``session`` half is an opaque,
JSON-safe dict the caller hands in and gets back verbatim.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

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
SCHEMA_VERSION = 2

# Default filename, resolved next to the project root by the caller.
DEFAULT_DB_FILENAME = "acm_database.json"


@dataclass(frozen=True)
class DatabaseSnapshot:
    """Immutable capture of one database file generation.

    ``raw_bytes`` is the only content source used by snapshot deserialization;
    callers can therefore continue diagnosing and hydrating the captured
    generation even if a cloud client replaces the live file afterward.

    Identity and generation are absent only for legacy version-1 databases.
    Checked writes upgrade those databases after an exact-hash comparison and
    a verified pre-upgrade backup.
    """

    path: str
    state: str
    raw_bytes: Optional[bytes]
    content_hash: Optional[str]
    size: int
    mtime_ns: Optional[int]
    schema_version: Any
    database_id: Any
    generation: Any
    mass: Optional[Tuple[int, int]]
    validation_errors: Tuple[str, ...]


@dataclass(frozen=True)
class DatabaseWriteToken:
    """Small, raw-data-free token retained by one application session."""

    path: str
    state: str
    schema_version: Any
    database_id: Any
    generation: Any
    content_hash: Optional[str]


@dataclass(frozen=True)
class DatabaseSaveResult:
    """Result of a verified shared-database write."""

    path: str
    token: DatabaseWriteToken
    pre_upgrade_backup: str = ""


@dataclass(frozen=True)
class ConflictRecoveryResult:
    """A read-back-verified file containing one session's pending state."""

    path: str
    token: DatabaseWriteToken


class DatabaseConcurrencyError(RuntimeError):
    """The shared database no longer matches the session's expected token."""

    def __init__(self, expected: DatabaseWriteToken,
                 observed: DatabaseSnapshot, reason: str):
        super().__init__(reason)
        self.expected = expected
        self.observed = observed
        self.reason = reason


class DatabaseCloudConflictError(RuntimeError):
    """A likely cloud-conflict copy exists beside the shared database."""

    def __init__(self, path: str, observed: DatabaseSnapshot,
                 siblings: Tuple[str, ...]):
        super().__init__(
            "Likely cloud-conflict database copies require review before saving.")
        self.path = os.path.abspath(path)
        self.observed = observed
        self.siblings = siblings


class DatabaseLockTimeout(RuntimeError):
    """Another local CAM process held the database write lock too long."""


class DatabaseShrinkError(RuntimeError):
    """The existing structural shrink tripwire refused a checked save."""


class DatabaseWriteVerificationError(RuntimeError):
    """A file write could not be read back as the exact intended payload."""


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
        "sections": getattr(a, "sections", None),
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
        sections=d.get("sections") if isinstance(d.get("sections"), list) else None,
    )


def _exam_result_to_dict(r: ExamResult) -> Dict[str, Any]:
    return {
        "assignment": r.assignment,
        "total": r.total,
        "max_total": r.max_total,
        "questions": dict(r.questions),
        "comment": r.comment,
        "chosen": {str(k): list(v) for k, v in (r.chosen or {}).items()},
        "section_bands": {str(k): int(v)
                          for k, v in (r.section_bands or {}).items()},
    }


def _exam_result_from_dict(d: Dict[str, Any]) -> ExamResult:
    raw_chosen = d.get("chosen") or {}
    chosen = {str(k): [str(x) for x in v]
              for k, v in raw_chosen.items() if isinstance(v, list)} \
        if isinstance(raw_chosen, dict) else {}
    raw_bands = d.get("section_bands") or {}
    section_bands: Dict[str, int] = {}
    if isinstance(raw_bands, dict):
        for k, v in raw_bands.items():
            try:
                section_bands[str(k)] = int(v)
            except (TypeError, ValueError):
                continue
    return ExamResult(
        assignment=d["assignment"],
        total=int(d.get("total", 0)),
        max_total=int(d.get("max_total", 0)),
        questions={str(k): int(v) for k, v in (d.get("questions") or {}).items()},
        comment=d.get("comment", ""),
        chosen=chosen,
        section_bands=section_bands,
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

def build_payload(gradebook: Gradebook, session: Optional[Dict[str, Any]] = None,
                  *, database_id: Optional[str] = None,
                  generation: Optional[int] = None,
                  recovery: Optional[Dict[str, Any]] = None
                  ) -> Dict[str, Any]:
    """Assemble the full on-disk payload (gradebook + opaque session dict)."""
    payload = {
        "version": SCHEMA_VERSION,
        "saved_at": datetime.now().isoformat(),
        "database_id": database_id or str(uuid.uuid4()),
        "generation": generation if generation is not None else 1,
        "gradebook": serialize_gradebook(gradebook),
        "session": session or {},
    }
    if recovery is not None:
        payload["recovery"] = recovery
    return payload


def _payload_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _atomic_write_bytes(path: str, raw: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def save_database(path: str, gradebook: Gradebook,
                  session: Optional[Dict[str, Any]] = None) -> str:
    """Atomically write the gradebook + session state to ``path``.

    The write goes to a temp file in the same directory and is then renamed
    over the target, so a crash mid-write can never corrupt an existing save.
    Returns the path written.
    """
    _atomic_write_bytes(path, _payload_bytes(build_payload(gradebook, session)))
    return path


def _raw_payload_mass(payload: Dict[str, Any]) -> Tuple[int, int]:
    """Return the existing shrink-tripwire mass dimensions from raw JSON."""
    gradebook = payload.get("gradebook", {}) or {}
    if not isinstance(gradebook, dict):
        gradebook = {}
    students = gradebook.get("students", []) or []
    assignments = gradebook.get("assignments", []) or []
    n_assignments = len(assignments) if isinstance(assignments, list) else 0
    n_scored = sum(
        1 for student in students
        if isinstance(student, dict) and student.get("scores")
    ) if isinstance(students, list) else 0

    session = payload.get("session", {}) or {}
    rosters = session.get("rosters", {}) if isinstance(session, dict) else {}
    n_roster = sum(
        len(entries) for entries in rosters.values()
        if isinstance(entries, list)
    ) if isinstance(rosters, dict) else 0
    return n_assignments, n_assignments + n_roster + n_scored


def _empty_snapshot(path: str, state: str, error: str = "") -> DatabaseSnapshot:
    """Build an absent/read-error snapshot without captured content."""
    return DatabaseSnapshot(
        path=path,
        state=state,
        raw_bytes=None,
        content_hash=None,
        size=0,
        mtime_ns=None,
        schema_version=0,
        database_id=None,
        generation=None,
        mass=None,
        validation_errors=(error,) if error else (),
    )


def capture_database_snapshot(path: str) -> DatabaseSnapshot:
    """Read ``path`` once and capture all boot-time database information.

    The returned object never consults the live path again. Validation errors
    are deliberately coarse codes so diagnostics do not expose student data or
    raw parser messages.
    """
    if not path or not os.path.exists(path):
        return _empty_snapshot(path, "absent")

    try:
        with open(path, "rb") as fh:
            raw = fh.read()
            stat = os.fstat(fh.fileno())
    except OSError:
        return _empty_snapshot(path, "unreadable", "read-error")

    digest = hashlib.sha256(raw).hexdigest()
    mtime_ns = getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))
    common = {
        "path": path,
        "raw_bytes": raw,
        "content_hash": digest,
        "size": len(raw),
        "mtime_ns": mtime_ns,
    }
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return DatabaseSnapshot(
            state="unreadable", schema_version=0, database_id=None,
            generation=None, mass=None,
            validation_errors=("invalid-utf8",), **common)
    try:
        payload = json.loads(text)
    except ValueError:
        return DatabaseSnapshot(
            state="unreadable", schema_version=0, database_id=None,
            generation=None, mass=None,
            validation_errors=("invalid-json",), **common)
    if not isinstance(payload, dict):
        return DatabaseSnapshot(
            state="unreadable", schema_version=0, database_id=None,
            generation=None, mass=None,
            validation_errors=("root-not-object",), **common)

    return DatabaseSnapshot(
        state="ok",
        schema_version=payload.get("version", 0),
        database_id=payload.get("database_id"),
        generation=payload.get("generation"),
        mass=_raw_payload_mass(payload),
        validation_errors=(),
        **common,
    )


def database_write_token(snapshot: DatabaseSnapshot) -> DatabaseWriteToken:
    """Drop raw bytes and diagnostics from a snapshot for session retention."""
    return DatabaseWriteToken(
        path=os.path.abspath(snapshot.path),
        state=snapshot.state,
        schema_version=snapshot.schema_version,
        database_id=snapshot.database_id,
        generation=snapshot.generation,
        content_hash=snapshot.content_hash,
    )


def find_database_conflict_siblings(path: str) -> Tuple[str, ...]:
    """Return likely cloud-conflict copies beside ``path`` without opening them.

    Cloud clients commonly insert a device/conflict label before the final
    ``.json`` extension. CAM's own sidecars instead append a documented suffix
    to the complete primary filename; those files are explicitly excluded.
    """
    absolute = os.path.abspath(path)
    directory = os.path.dirname(absolute) or "."
    primary = os.path.basename(absolute)
    stem, extension = os.path.splitext(primary)
    primary_lower = primary.lower()
    stem_lower = stem.lower()
    extension_lower = extension.lower()
    if extension_lower != ".json" or not os.path.isdir(directory):
        return ()

    owned_prefixes = (
        primary_lower + ".bak-",
        primary_lower + ".conflict-recovery-",
        primary_lower + ".blocked-",
        primary_lower + ".cam-write.lock",
        primary_lower + ".wiped-",
        primary_lower + ".safety-",
    )
    found = set()
    try:
        entries = os.scandir(directory)
    except OSError:
        return ()
    with entries:
        for entry in entries:
            name_lower = entry.name.lower()
            if name_lower == primary_lower:
                continue
            if any(name_lower.startswith(prefix) for prefix in owned_prefixes):
                continue
            if not name_lower.endswith(extension_lower):
                continue
            candidate_stem = name_lower[:-len(extension_lower)]
            remainder = candidate_stem[len(stem_lower):]
            if (not candidate_stem.startswith(stem_lower) or not remainder
                    or remainder[0] not in " ([{-_"):
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            found.add(os.path.abspath(entry.path))
    return tuple(sorted(found, key=lambda item: (os.path.normcase(item), item)))


def _valid_v2_snapshot(snapshot: DatabaseSnapshot) -> bool:
    if snapshot.state != "ok" or snapshot.schema_version != SCHEMA_VERSION:
        return False
    try:
        uuid.UUID(str(snapshot.database_id))
    except (ValueError, TypeError, AttributeError):
        return False
    return (isinstance(snapshot.generation, int)
            and not isinstance(snapshot.generation, bool)
            and snapshot.generation >= 1
            and bool(snapshot.content_hash))


def _tokens_match(expected: DatabaseWriteToken,
                  observed: DatabaseSnapshot) -> Tuple[bool, str]:
    if os.path.abspath(observed.path) != os.path.abspath(expected.path):
        return False, "database-path-changed"
    if expected.state == "absent":
        return (observed.state == "absent",
                "database-created-by-another-session")
    if expected.state != "ok" or observed.state != "ok":
        return False, "database-missing-or-unreadable"
    if expected.schema_version == 1:
        ok = (expected.database_id is None and expected.generation is None
              and observed.schema_version == 1
              and observed.database_id is None and observed.generation is None
              and observed.content_hash == expected.content_hash)
        return ok, "legacy-database-changed"
    if expected.schema_version != SCHEMA_VERSION or not _valid_v2_snapshot(observed):
        return False, "invalid-concurrency-metadata"
    if observed.database_id != expected.database_id:
        return False, "database-identity-changed"
    if observed.generation != expected.generation:
        return False, "database-generation-changed"
    if observed.content_hash != expected.content_hash:
        return False, "database-content-changed-without-generation"
    return True, ""


def _lock_file(file_obj, blocking: bool) -> None:
    if os.name == "nt":
        import msvcrt
        file_obj.seek(0)
        mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
        msvcrt.locking(file_obj.fileno(), mode, 1)
    else:
        import fcntl
        mode = fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB)
        fcntl.flock(file_obj.fileno(), mode)


def _unlock_file(file_obj) -> None:
    if os.name == "nt":
        import msvcrt
        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)


@contextmanager
def database_write_lock(path: str, timeout: float = 5.0):
    """Serialize local writers without treating the cloud-visible lock as CAS."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(directory):
        raise OSError(f"Database folder is unavailable: {directory}")
    lock_path = path + ".cam-write.lock"
    with open(lock_path, "a+b") as lock_file:
        if os.path.getsize(lock_path) == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock_file(lock_file, blocking=False)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= deadline:
                    raise DatabaseLockTimeout(
                        "Another local CAM save is still in progress; retry.")
                time.sleep(0.05)
        try:
            yield
        finally:
            _unlock_file(lock_file)


def _write_sidecar_exclusive(path: str, raw: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            os.remove(path)
        except OSError:
            pass
        raise


def _verified_snapshot_copy(path: str, snapshot: DatabaseSnapshot) -> str:
    if snapshot.raw_bytes is None or snapshot.content_hash is None:
        raise DatabaseWriteVerificationError("No database bytes to back up.")
    _write_sidecar_exclusive(path, snapshot.raw_bytes)
    copied = capture_database_snapshot(path)
    if (copied.state != "ok"
            or copied.content_hash != snapshot.content_hash
            or copied.raw_bytes != snapshot.raw_bytes):
        raise DatabaseWriteVerificationError("Database backup verification failed.")
    return path


def _backup_name(path: str, purpose: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{path}.bak-{purpose}-{stamp}-{uuid.uuid4().hex[:8]}"


def _rotate_daily_backup_from_snapshot(path: str,
                                       snapshot: DatabaseSnapshot) -> None:
    if snapshot.state != "ok" or snapshot.raw_bytes is None:
        return
    backup = f"{path}.bak-auto-{datetime.now().strftime('%Y%m%d')}"
    if os.path.exists(backup):
        return
    try:
        _verified_snapshot_copy(backup, snapshot)
    except (OSError, DatabaseWriteVerificationError):
        pass


def _outgoing_mass(gradebook: Gradebook, session: Dict[str, Any]) -> int:
    assignments = len(gradebook.assignments)
    scored = sum(1 for student in gradebook.students.values()
                 if any(student.scores.get(c) for c in student.scores))
    rosters = session.get("rosters", {}) if isinstance(session, dict) else {}
    roster_count = sum(len(rows) for rows in rosters.values()
                       if isinstance(rows, list)) if isinstance(rosters, dict) else 0
    return assignments + scored + roster_count


def save_database_checked(path: str, gradebook: Gradebook,
                          session: Optional[Dict[str, Any]],
                          expected: DatabaseWriteToken, *,
                          allow_shrink: bool = False,
                          shrink_min_assignments: int = 10,
                          shrink_keep_ratio: float = 0.33,
                          lock_timeout: float = 5.0) -> DatabaseSaveResult:
    """Compare, protect, atomically replace, and verify one shared database."""
    session = session or {}
    with database_write_lock(path, lock_timeout):
        observed = capture_database_snapshot(path)
        siblings = find_database_conflict_siblings(path)
        if siblings:
            raise DatabaseCloudConflictError(path, observed, siblings)
        matches, reason = _tokens_match(expected, observed)
        if not matches:
            raise DatabaseConcurrencyError(expected, observed, reason)

        if (not allow_shrink and observed.mass is not None
                and observed.mass[0] >= shrink_min_assignments
                and observed.mass[1] > 0
                and _outgoing_mass(gradebook, session)
                    < shrink_keep_ratio * observed.mass[1]):
            raise DatabaseShrinkError(
                "Save blocked because it would erase most database records.")

        pre_upgrade = ""
        if observed.state == "ok" and observed.schema_version == 1:
            pre_upgrade = _verified_snapshot_copy(
                _backup_name(path, "pre-concurrency-upgrade"), observed)

        _rotate_daily_backup_from_snapshot(path, observed)
        if observed.state == "ok" and observed.schema_version == SCHEMA_VERSION:
            database_id = str(observed.database_id)
            generation = int(observed.generation) + 1
        else:
            database_id = str(uuid.uuid4())
            generation = 1
        payload = build_payload(
            gradebook, session, database_id=database_id, generation=generation)
        raw = _payload_bytes(payload)
        intended_hash = hashlib.sha256(raw).hexdigest()
        _atomic_write_bytes(path, raw)
        written = capture_database_snapshot(path)
        if (not _valid_v2_snapshot(written)
                or written.database_id != database_id
                or written.generation != generation
                or written.content_hash != intended_hash):
            raise DatabaseWriteVerificationError(
                "The database write could not be verified after saving.")
        return DatabaseSaveResult(
            path=path, token=database_write_token(written),
            pre_upgrade_backup=pre_upgrade)


def replace_database_checked(path: str, gradebook: Gradebook,
                             session: Optional[Dict[str, Any]], *,
                             lock_timeout: float = 5.0) -> DatabaseSaveResult:
    """Explicitly replace a reviewed target after a mandatory verified backup."""
    with database_write_lock(path, lock_timeout):
        observed = capture_database_snapshot(path)
        siblings = find_database_conflict_siblings(path)
        if siblings:
            raise DatabaseCloudConflictError(path, observed, siblings)
        if observed.state not in ("ok", "absent"):
            raise DatabaseWriteVerificationError(
                "The database selected for replacement is not readable.")
        backup = ""
        if observed.state == "ok":
            backup = _verified_snapshot_copy(
                _backup_name(path, "replaced"), observed)
        database_id = str(uuid.uuid4())
        payload = build_payload(gradebook, session, database_id=database_id,
                                generation=1)
        raw = _payload_bytes(payload)
        intended_hash = hashlib.sha256(raw).hexdigest()
        _atomic_write_bytes(path, raw)
        written = capture_database_snapshot(path)
        if (not _valid_v2_snapshot(written)
                or written.database_id != database_id
                or written.generation != 1
                or written.content_hash != intended_hash):
            raise DatabaseWriteVerificationError(
                "The replacement database could not be verified.")
        return DatabaseSaveResult(path, database_write_token(written), backup)


def write_conflict_recovery(path: str, gradebook: Gradebook,
                            session: Optional[Dict[str, Any]],
                            expected: DatabaseWriteToken,
                            observed: DatabaseSnapshot, *,
                            reason: str = "concurrency-conflict"
                            ) -> ConflictRecoveryResult:
    """Preserve pending state in a unique, self-contained, verified database."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery_path = (f"{path}.conflict-recovery-{stamp}-"
                     f"{uuid.uuid4().hex[:8]}.json")
    recovery = {
        "kind": reason,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_database_id": expected.database_id,
        "expected_generation": expected.generation,
        "expected_content_hash": expected.content_hash,
        "observed_database_id": observed.database_id,
        "observed_generation": observed.generation,
        "observed_content_hash": observed.content_hash,
        "observed_state": observed.state,
    }
    payload = build_payload(gradebook, session, database_id=str(uuid.uuid4()),
                            generation=1, recovery=recovery)
    raw = _payload_bytes(payload)
    _write_sidecar_exclusive(recovery_path, raw)
    captured = capture_database_snapshot(recovery_path)
    loaded = load_database_snapshot(captured)
    if (not _valid_v2_snapshot(captured)
            or captured.content_hash != hashlib.sha256(raw).hexdigest()
            or loaded is None):
        raise DatabaseWriteVerificationError(
            "The conflict recovery file could not be verified.")
    return ConflictRecoveryResult(recovery_path,
                                  database_write_token(captured))


def load_database_snapshot(snapshot: DatabaseSnapshot
                           ) -> Optional[Dict[str, Any]]:
    """Deserialize a database solely from ``snapshot``'s captured bytes."""
    if snapshot.state != "ok" or snapshot.raw_bytes is None:
        return None
    try:
        payload = json.loads(snapshot.raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    gb = deserialize_gradebook(payload.get("gradebook", {}))
    return {
        "gradebook": gb,
        "session": payload.get("session", {}),
        "saved_at": payload.get("saved_at", ""),
        "version": payload.get("version", 0),
    }


def load_database(path: str) -> Optional[Dict[str, Any]]:
    """Load a saved database file through a single immutable snapshot.

    The public return contract is unchanged: absent or unreadable files return
    ``None``; valid files return the hydrated gradebook and session mapping.
    """
    return load_database_snapshot(capture_database_snapshot(path))


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
    return capture_database_snapshot(path).state


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
