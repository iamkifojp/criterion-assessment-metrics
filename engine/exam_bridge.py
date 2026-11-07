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

# Runs CAM2's launcher with its own folder first on sys.path. Plain
# ``python launcher.py`` relies on Python putting the script's folder first,
# but the portable bundle's embedded Python ignores the script folder (its
# ``._pth`` file fixes the path) and lists CAM's root and the grading
# workspace instead, so CAM2's ``import engine`` / ``from app import ...``
# would load CAM's engine and the workspace's app.py.
_LAUNCH_BOOT = (
    "import os, runpy, signal, sys; launcher = sys.argv[1]; sys.argv = sys.argv[1:]; "
    "signal.signal(signal.SIGBREAK, signal.default_int_handler) "
    "if sys.platform == 'win32' and os.environ.get('CAM_QUIT_FILE') else None; "
    "sys.path.insert(0, os.path.dirname(launcher)); "
    "runpy.run_path(launcher, run_name='__main__')"
)

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
    mode: str                           # "marks", "rubric" or "mixed" ("" before Step 2)
    ready_at: Optional[str]             # host_ready_at: "Send to CAM" was clicked
    question_labels: List[str]
    rubrics: List[dict]                 # [{"id": "r1", "name": "Criterion A", "max": 8}]
    max_total: int                      # of the marks questions; 0 when there are none
    papers: List[SessionPaper] = field(default_factory=list)
    # label -> {"rubrics": [rubric id], "max": marks maximum, 0 for a level}
    question_info: Dict[str, dict] = field(default_factory=dict)


def _exam_mode(shapes: List[dict], started_as: str) -> str:
    """What a paper's questions are, from the shape of ``question_values``: a
    ``None`` key is a marks question, any other key a rubric. CAM2's own
    ``mode`` is only the teacher's starting choice, so it decides only when no
    question has a shape yet. An older CAM treats anything but ``"rubric"`` as
    marks, which is safe for ``"mixed"``."""
    marks = any(None in shape for shape in shapes)
    rubric = any(key is not None for shape in shapes for key in shape)
    if marks and rubric:
        return "mixed"
    if rubric:
        return "rubric"
    return "marks" if marks else started_as


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

    questions = config.get("questions") or []
    labels = {q["id"]: q["label"] for q in questions}
    roster = {r["id"]: r for r in config.get("roster") or []}
    summaries = {s["student_id"]: s
                 for s in summary_mod.class_summary(config, grades)["students"]}
    assignment = assignment or config.get("exam_name") or ""
    # A question's keys don't depend on the student, so an empty id gives them.
    mode = _exam_mode([summary_mod.question_values(config, grades, "", q) for q in questions],
                      config.get("mode") or "")
    has_marks = mode in ("marks", "mixed")
    max_total = summary_mod.marks_maximum(config) if has_marks else 0

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
            elif None in values:
                if isinstance(given.get(None), int):
                    result.questions[label] = given[None]
            elif given:
                result.levels[label] = given
            comment = str((entries.get(q["id"]) or {}).get("comment") or "").strip()
            if comment:
                result.question_comments[label] = comment
        for rid, rubric in (summary.get("rubrics") or {}).items():
            if rubric.get("final") is not None:
                result.final_levels[rid] = rubric["final"]
            if rubric.get("marks"):
                result.criterion_marks[rid] = dict(rubric["marks"])
        marks = summary.get("marks")
        if has_marks and marks:
            result.total = int(marks["total"])
            result.max_total = max_total
            result.percent = marks.get("percent")
            result.weighted = bool(marks.get("weighted"))
            if marks.get("adjusted"):
                # The teacher typed over CAM2's figure for the report: a total,
                # or the percentage when weighted. Kept beside the calculated
                # one, which stays what CAM shows and works with.
                if not result.weighted and marks.get("report_total") is not None:
                    result.report_total = float(marks["report_total"])
                if marks.get("report_percent") is not None:
                    result.report_percent = float(marks["report_percent"])
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
        question_info={labels[q["id"]]: {
            "rubrics": list(summary_mod.question_rubric_ids(config, q)),
            "max": int(q.get("max") or 0)} for q in questions},
    )


def route_session(session: ExamSession, roster_keys,
                  aliases: Optional[Dict[str, str]] = None,
                  ) -> Tuple[Dict[str, ExamResult], List[dict], Dict[str, str]]:
    """File each paper under a roster key.

    Returns ``(matched, pool, auto_aliases)``: ``matched`` maps roster key to
    result; ``pool`` holds 🧩 rows (``is_exam`` rows carrying the whole
    ``result`` for :meth:`IngestionPipeline.materialize_exam_row`);
    ``auto_aliases`` are prefix matches to record. A paper is pooled, never
    guessed, when nothing matches, when a second paper resolves to the same
    student, or when there is no roster at all."""
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
    exits at once. The launcher runs through :data:`_LAUNCH_BOOT`, so CAM2
    imports its own modules in the portable bundle too."""
    return [python or sys.executable, "-c", _LAUNCH_BOOT, CAM2_LAUNCHER,
            "--host", handoff_path]


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


def session_stamp(folder: str) -> List[int]:
    """Cheap change marker for the two files Sync reads: ``[mtime_ns, size]``
    of each, from ``os.stat`` alone. A list, so it compares equal after a JSON
    round trip in the ``ingested_files`` registry. Raises OSError when either
    file is missing."""
    storage = cam2_module("storage")
    stamp: List[int] = []
    for name in (storage.SESSION_FILE, storage.GRADES_FILE):
        info = os.stat(os.path.join(folder, name))
        stamp += [info.st_mtime_ns, info.st_size]
    return stamp


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


def final_level_action(current: Optional[int], exam_value: Optional[int], sent: int) -> str:
    """What Apply does with one student's mapped final level (the re-send rule,
    which runs here and never at Sync). All values are on the 0-8 scale.

    ``current`` and ``exam_value`` come from the existing grade (None when there
    is none, or when it has no record of CAM2's value), and ``sent`` is CAM2's
    level.

    * ``"fill"``: nothing is there yet.
    * ``"update"``: the grade is still what CAM2 sent, and CAM2 now sends another.
    * ``"same"``: the grade already equals CAM2's.
    * ``"keep"``: the teacher set or edited the grade. It stays, and the caller
      lists it."""
    if current is None:
        return "fill"
    if current == sent:
        return "same"
    if current == exam_value:
        return "update"
    return "keep"


def rubric_mapping(rubrics: List[dict], saved: Optional[dict] = None) -> Dict[str, str]:
    """Which CAM criterion each rubric counts toward: {rubric id: letter}.

    The teacher's choice in ``saved`` wins ("—" means not counted). Otherwise a
    rubric maps by its name, so "Criterion A" to "Criterion D" need nothing set
    (P2). Several rubrics may share a letter (D11)."""
    saved = saved or {}
    mapping = {}
    for rubric in rubrics or []:
        rid = rubric.get("id")
        letter = saved[rid] if rid in saved else default_criterion(rubric.get("name", ""))
        if letter in ("A", "B", "C", "D"):
            mapping[rid] = letter
    return mapping


def _level_text(label: str, value, top: int, counted: list) -> str:
    """One question's evidence: ``Screen 03: 5``, or ``5/6`` when ``top`` is
    given, for marks and for a rubric that doesn't go to 8, since nothing is
    scaled here (P4). A question not counted because of a choice group is still
    shown, and says so. One not graded yet has nothing to count."""
    if value is None:
        return f"{label}: —"
    if value == EXAM_NOT_ANSWERED:
        text = f"{label}: not answered"
    elif top:
        text = f"{label}: {value}/{top}"
    else:
        text = f"{label}: {value}"
    return text + " (not counted)" if counted and label not in counted else text


def _rubric_items(result: ExamResult, rid: str, top: int, questions: dict) -> List[str]:
    """Everything on this paper about one rubric, in question order: each level,
    and each mark ticked on it (D11)."""
    labels = list(questions) or list(result.levels)
    items = []
    for label in labels:
        info = questions.get(label) or {}
        on_rubric = rid in (info.get("rubrics") or []) or rid in result.levels.get(label, {})
        if not on_rubric:
            continue
        marks_max = int(info.get("max") or 0)
        if label in result.not_answered:
            items.append(_level_text(label, EXAM_NOT_ANSWERED, 0, result.counted))
        elif marks_max:
            items.append(_level_text(label, result.questions.get(label), marks_max,
                                     result.counted))
        else:
            items.append(_level_text(label, result.levels.get(label, {}).get(rid),
                                     0 if top == 8 else top, result.counted))
    return items


def criterion_groups(result: ExamResult, rubrics: List[dict], mapping: Dict[str, str],
                     questions: Optional[dict] = None) -> Tuple[List[dict], List[dict]]:
    """A paper's evidence grouped by criterion, for Window 3 (D10, D11, D13).

    Returns ``(groups, unmapped)``. Each group is ``{"letter", "rubric_ids",
    "rubrics": [{"id", "name", "items", "marks", "final", "max", "band"}]}``, in
    A to D order. ``unmapped`` holds the same rubric rows for rubrics that count
    toward no criterion and have something on this paper. This only arranges what
    CAM2 sent: it never averages, suggests or converts, except that ``band`` puts
    a typed final level on the 0-8 scale (P4)."""
    questions = questions or {}

    def row(rubric: dict) -> dict:
        rid = rubric.get("id")
        top = int(rubric.get("max") or 8)
        final = result.final_levels.get(rid)
        return {"id": rid, "name": rubric.get("name") or rid, "max": top,
                "items": _rubric_items(result, rid, top, questions),
                "marks": result.criterion_marks.get(rid),
                "final": final,
                "band": to_band(final, top) if final is not None else None}

    by_letter: Dict[str, List[dict]] = {}
    unmapped = []
    for rubric in rubrics or []:
        rid = rubric.get("id")
        if rid in mapping:
            by_letter.setdefault(mapping[rid], []).append(row(rubric))
        else:
            one = row(rubric)
            if any(not item.endswith(": —") for item in one["items"]) or one["marks"]:
                unmapped.append(one)
    groups = [{"letter": letter, "rubrics": by_letter[letter],
               "rubric_ids": [r["id"] for r in by_letter[letter]]}
              for letter in sorted(by_letter)]
    return groups, unmapped


def exam_basis(result: ExamResult, rubric_ids=()) -> str:
    """Short hash of the levels and marks a decision on one criterion sees, so
    Window 3 can later say "levels changed since you decided" (P6). Sync
    replaces the result, so this is all that remains of the earlier one.

    ``rubric_ids`` are the rubrics mapped to that criterion. With none, the
    decision came from the whole paper's marks, so those are the basis."""
    rubric_ids = sorted(str(rid) for rid in rubric_ids)
    if rubric_ids:
        basis = {
            "levels": {label: {rid: per[rid] for rid in rubric_ids if rid in per}
                       for label, per in result.levels.items()
                       if any(rid in per for rid in rubric_ids)},
            "marks": {rid: result.criterion_marks[rid] for rid in rubric_ids
                      if rid in result.criterion_marks},
        }
    else:
        basis = {"questions": result.questions, "total": result.total,
                 "max_total": result.max_total}
    text = json.dumps(basis, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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
