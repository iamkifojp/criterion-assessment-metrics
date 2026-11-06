"""Shapes of the two files inside a session folder.

``cam2_session.json`` — the exam set-up (rarely changes once grading starts)::

    {
      "format": "cam2-session", "version": 2,
      "session_id": "<uuid>", "generation": 3, "saved_at": "...", "saved_by": "PC",
      "exam_name": "Y8 Science Midterm", "created_at": "...",
      "layout": {"paper": "A4", "density": "5mm", "landscape": false},
      "mode": "marks" | "rubric" | null,                 # the starting choice only
      "rubrics":  [{"id": "r1", "name": "Criterion A",
                    "bands": [{"levels": "5–6", "descriptor": "..."}]}],
      "name_box": ["page1!A1:E2"] | [],
      "sections": [{"id": "sec1", "name": "Scientific knowledge",
                    "weight": 50, "weight_typed": false}],
      "weighted": false,
      "report_options": {"section_results": false, "overall_criteria": false,
                         "rubric_table": true, "overall_marks": true,
                         "no_images_for": ["sec1"]},
      "questions": [{"id": "q1", "label": "Q1", "boxes": ["page1!A4:J10"],
                     "max": 5, "rubric_ids": ["r1"], "section_id": "sec1"}],
      "keywords": [{"label": "check calculations", "type": "growth" | "strength"}],
      "choice_groups": [{"id": "g1", "questions": ["q4", "q5", "q6"], "answer": 2,
                         "pick": "best" | "teacher"}],
      "students": [{"id": "s001", "scan": "scans/Student_001.pdf",
                    "source": "scan0001.pdf", "pages": 4, "roster_id": null}],
      "roster": [{"id": "n001", "name": "Tanaka Hana", "external_id": "8A-07"}],
      "host": {"name": "CAM", "class_name": "8A"},       # opened from CAM (engine/host.py)
      "host_ready_at": "..." | null,                     # results sent to the host
      "crops_of": {"q1": ["page1!A4:J10"]},              # boxes the crops were cut from
      "sliced": false,
      "resume": {"step": 1, "question_id": null, "student_id": null}
    }

``grades.json`` — written on every click while grading::

    {
      "format": "cam2-grades", "version": 2,
      "session_id": "<uuid>", "generation": 41, "saved_at": "...", "saved_by": "PC",
      "grades":  {"s001": {"q1": {"value": 4, "comment": "Good",
                                  "keywords": [], "keyword_text": ""},
                           "q2": {"value": "not_answered", "comment": ""},
                           "q3": {"value": null, "comment": "",
                                  "levels": {"r2": 5, "r3": 4}}}},
      "overall": {"s001": {"comment": "", "report_total": null, "report_percent": null,
                           "final_levels": {"r1": 6},
                           "chosen": {"g1": ["q4", "q6"]}}}
    }

A question grades with marks if it has a ``max``, and with rubric levels if
not; there is no separate field for it (``grading_summary.question_mode``). A
question with no entry (or ``value`` null) is *ungraded*. A question assessed
on several criteria (``rubric_ids``) keeps one level per criterion in
``levels``; older sessions have a single ``rubric_id``. Sections are optional:
with none, the whole paper is one section. A final level is typed by the
teacher, and blank means no level. Ids, not labels, key everything so a teacher
can rename "Q1" without breaking crops or grades.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from .errors import UserError

SESSION_FORMAT = "cam2-session"
GRADES_FORMAT = "cam2-grades"
VERSION = 2

NOT_ANSWERED = "not_answered"
NAME_BOX_ID = "__name__"
DEFAULT_REPORT_OPTIONS = {"section_results": False, "overall_criteria": False,
                          "rubric_table": True, "overall_marks": True, "no_images_for": []}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_session_id() -> str:
    return uuid.uuid4().hex


def new_session(exam_name: str, session_id: str) -> dict:
    name = str(exam_name or "").strip()
    if not name:
        raise UserError("exam_name_required")
    return {
        "format": SESSION_FORMAT,
        "version": VERSION,
        "session_id": session_id,
        "generation": 0,
        "exam_name": name,
        "created_at": now_iso(),
        "layout": {"paper": "A4", "density": "5mm", "landscape": False},
        "mode": None,
        "rubrics": [],
        "name_box": [],
        "sections": [],
        "weighted": False,
        "questions": [],
        "choice_groups": [],
        "students": [],
        "roster": [],
        "sliced": False,
        "resume": {"step": 1, "question_id": None, "student_id": None},
    }


def new_grades(session_id: str) -> dict:
    return {
        "format": GRADES_FORMAT,
        "version": VERSION,
        "session_id": session_id,
        "generation": 0,
        "grades": {},
        "overall": {},
    }


def check_format(data, expected_format: str) -> dict:
    """Reject files that are not CAM2 files, or are from a newer CAM2."""
    if not isinstance(data, dict) or data.get("format") != expected_format:
        raise UserError("not_a_cam2_file", expected=expected_format)
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise UserError("file_from_newer_version", version=version)
    return data


def grades_mass(data: dict) -> int:
    """How much teacher work a grades file holds (graded cells, comments and
    final levels, none of which anything can recalculate).

    Used by the wipe guard: a save that would drop most of this is refused.
    """
    count = 0
    for per_student in (data.get("grades") or {}).values():
        for entry in (per_student or {}).values():
            if not isinstance(entry, dict):
                continue
            if entry.get("value") is not None:
                count += 1
            count += sum(1 for v in (entry.get("levels") or {}).values() if v is not None)
            if str(entry.get("comment") or "").strip():
                count += 1
    for entry in (data.get("overall") or {}).values():
        if not isinstance(entry, dict):
            continue
        if str(entry.get("comment") or "").strip():
            count += 1
        count += sum(1 for v in (entry.get("final_levels") or {}).values() if v is not None)
    return count


def upgrade_session(config: dict, grades: Optional[dict] = None) -> dict:
    """Bring a session saved by an older CAM2 up to the current version.

    A question now grades with marks if it has a ``max``, so before anything
    reads them: a rubric session's questions lose any ``max`` left from before
    the teacher chose Rubric, and a marks session's lose any criteria left the
    same way. Runs only once, because later a rubric session can gain marks.
    Final levels are now shown only with Overall criterion results on, so a
    session with any typed keeps them on.
    """
    if int(config.get("version") or 1) < 2:
        for q in config.get("questions") or []:
            if config.get("mode") == "rubric":
                q["max"] = None
            elif config.get("mode") == "marks":
                q["rubric_ids"] = []
                q.pop("rubric_id", None)
        if any(v is not None for per in ((grades or {}).get("overall") or {}).values()
               for v in ((per or {}).get("final_levels") or {}).values()):
            config["report_options"] = dict(DEFAULT_REPORT_OPTIONS, overall_criteria=True)
    config["version"] = VERSION
    return config
