"""Reading CAM2 exam sessions into CAM (CAM2 convergence plan, Stage 2).

CAM2 (vendored unmodified at ``exam_grading/``) keeps each exam in a session
folder: ``cam2_session.json`` (set-up, papers, class list) and ``grades.json``.
CAM only ever **reads** that folder. Totals, choice groups and final levels
are worked out by CAM2's own ``grading_summary``, so CAM's numbers always
match what CAM2 shows (round-half-up, best N, teacher picks).

CAM2's package is also called ``engine``, so it is loaded here under the name
``cam2_engine``. Its modules import each other relatively, so nothing inside
``exam_grading/`` changes.

Two steps, kept apart so Sync can report a broken folder without touching
the gradebook:

* :func:`read_session` turns a folder into an :class:`ExamSession`, one
  :class:`ExamResult` per paper.
* :func:`route_session` files each paper under a roster key: the
  ``external_id`` CAM handed over in host mode (exact), then the usual
  :func:`resolve_identity` (alias, unambiguous prefix) on the paper's name,
  and otherwise the 🧩 pool.

Stage 3 adds what CAM needs around those two: where an exam's session lives
(``<class folder>/exams/<exam>/``), the handoff file and command that open it
in CAM2's host mode, finding sessions at Sync, and moving a deleted exam's
folder aside instead of deleting it.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .ingestion import resolve_identity
from .models import EXAM_NOT_ANSWERED, ExamResult
from .persistence import exam_result_to_dict

CAM2_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "exam_grading")
CAM2_ENGINE_DIR = os.path.join(CAM2_DIR, "engine")
CAM2_LAUNCHER = os.path.join(CAM2_DIR, "launcher.py")
CAM2_PACKAGE = "cam2_engine"

EXAMS_DIR = "exams"          # <class folder>/exams/<exam>/ holds each session (D6)
DELETED_DIR = "_deleted"     # exams/_deleted/<stamp> <exam>/: permanently deleted exams
NAME_BOX_ID = "__name__"     # CAM2's handwritten-name box: crops/__name__/<paper id>.png


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
    rubrics: List[dict]                 # [{"id": "r1", "name": "Criterion A", "max": 8}]
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
    rubrics_mod = cam2_module("rubrics")
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
        rubrics=[{"id": r["id"], "name": r.get("name", ""),
                  "max": rubrics_mod.rubric_max(r)}
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


# --------------------------------------------------------------------------
# Stage 3: opening exams in CAM2, finding them at Sync, retiring them
# --------------------------------------------------------------------------

def folder_name(exam_name: str) -> str:
    """The session folder's name for an exam: CAM's class-folder sanitizer,
    with the trailing dots and spaces Windows refuses also removed."""
    name = re.sub(r'[\\/*?:"<>|]', "_", str(exam_name or "").strip())
    return name.rstrip(". ").strip() or "Exam"


def session_folder(class_dir: str, exam_name: str) -> str:
    """``<class folder>/exams/<exam>/``: where CAM hosts an exam's session."""
    return os.path.join(class_dir, EXAMS_DIR, folder_name(exam_name))


def handoff(exam_name: str, class_name: str, folder: str, roster) -> dict:
    """The ``cam2-host`` handoff (format in ``exam_grading/engine/host.py``).
    ``roster`` is CAM's class list, ``[{"key", "name"}]``; the key travels as
    ``external_id`` so Sync files each paper without matching names again."""
    entries = []
    for entry in roster or []:
        key = str(entry.get("key") or "").strip()
        if key:
            entries.append({"external_id": key,
                            "name": str(entry.get("name") or "").strip() or key})
    return {"format": "cam2-host", "version": 1, "host": "CAM",
            "exam_name": exam_name, "class_name": class_name,
            "session_folder": os.path.abspath(folder), "roster": entries}


def write_handoff(directory: str, data: dict) -> str:
    """Write a handoff into ``directory`` (on this computer, never the cloud
    folder: it holds the class list). One file per session folder, replaced
    on every launch. Returns its path."""
    os.makedirs(directory, exist_ok=True)
    digest = hashlib.sha1(os.path.normcase(data["session_folder"]).encode("utf-8")).hexdigest()
    path = os.path.join(directory, f"handoff_{digest[:16]}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
    return path


def launch_command(handoff_path: str, python: Optional[str] = None) -> List[str]:
    """The command that opens one exam in CAM2's host mode. CAM2's launcher
    is single-instance: a running CAM2 is handed the exam and the new process
    exits at once."""
    return [python or sys.executable, CAM2_LAUNCHER, "--host", handoff_path]


def running_url() -> Optional[str]:
    """URL of the CAM2 running on this computer, if any (found the way CAM2's
    own launcher finds it: its ``server.json`` plus a ping)."""
    import urllib.request
    storage = cam2_module("storage")
    try:
        with open(os.path.join(storage.app_data_dir(), "server.json"), encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
        url = f"http://127.0.0.1:{port}/"
        with urllib.request.urlopen(url + "api/ping", timeout=1.5) as resp:
            if json.load(resp).get("app") == "cam2":
                return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def find_sessions(class_dir: str) -> List[str]:
    """Every CAM2 session folder under ``<class folder>/exams/``, by name.
    ``_deleted`` and other ``_`` folders are skipped."""
    root = os.path.join(class_dir, EXAMS_DIR)
    if not os.path.isdir(root):
        return []
    storage = cam2_module("storage")
    out = []
    for entry in sorted(os.scandir(root), key=lambda e: e.name.lower()):
        if entry.is_dir() and not entry.name.startswith("_") \
                and storage.is_session_folder(entry.path):
            out.append(os.path.abspath(entry.path))
    return out


def session_fingerprint(folder: str) -> str:
    """Hash of the two files Sync reads; a session is re-read only when it
    changes. Raises OSError when either file can't be read (mid-sync)."""
    storage = cam2_module("storage")
    digest = hashlib.sha256()
    for name in (storage.SESSION_FILE, storage.GRADES_FILE):
        with open(os.path.join(folder, name), "rb") as fh:
            digest.update(fh.read())
        digest.update(b"\0")
    return digest.hexdigest()


_CRITERION_RE = re.compile(r"(?:criterion|crit|基準|規準)\W*([A-D])(?![A-Za-z])", re.IGNORECASE)


def default_criterion(rubric_name: str) -> Optional[str]:
    """The CAM criterion a CAM2 rubric's name points to ("Criterion B",
    "Crit. B", "基準Ｂ", or just "B" → ``"B"``), else None."""
    text = unicodedata.normalize("NFKC", str(rubric_name or "")).strip()
    m = _CRITERION_RE.search(text)
    if m:
        return m.group(1).upper()
    if len(text) == 1 and text.upper() in "ABCD":
        return text.upper()
    return None


def to_band(level: int, rubric_max: int) -> int:
    """A CAM2 final level on CAM's 0-8 scale. A rubric that goes to 8 maps
    one to one; any other maximum is scaled (round half up)."""
    level = max(0, int(level))
    if rubric_max and rubric_max != 8:
        level = int(cam2_module("grading_summary").round_half_up(level * 8 / rubric_max))
    return max(0, min(8, level))


def name_crop(folder: str, student_id: str) -> str:
    """A paper's handwritten-name crop in its session, or "" when none."""
    if not folder or not student_id:
        return ""
    storage = cam2_module("storage")
    path = os.path.join(folder, storage.CROPS_DIR, NAME_BOX_ID, f"{student_id}.png")
    return path if os.path.isfile(path) else ""


def retire_session(folder: str, when: Optional[datetime] = None) -> Optional[str]:
    """Move a deleted exam's session folder to
    ``exams/_deleted/<YYYYMMDD-HHMMSS> <name>/`` rather than deleting it.

    Only a session folder directly inside an ``exams`` folder is moved.
    Returns the new path, or None when there was nothing to move."""
    folder = os.path.abspath(folder)
    parent = os.path.dirname(folder)
    if os.path.basename(parent) != EXAMS_DIR or not os.path.isdir(folder):
        return None
    if not cam2_module("storage").is_session_folder(folder):
        return None
    stamp = (when or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target_root = os.path.join(parent, DELETED_DIR)
    os.makedirs(target_root, exist_ok=True)
    base = f"{stamp} {os.path.basename(folder)}"
    target, n = os.path.join(target_root, base), 1
    while os.path.exists(target):
        n += 1
        target = os.path.join(target_root, f"{base} ({n})")
    shutil.move(folder, target)
    return target
