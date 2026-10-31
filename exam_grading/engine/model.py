"""Shapes of the two files inside a session folder.

``cam2_session.json`` — the exam set-up (rarely changes once grading starts)::

    {
      "format": "cam2-session", "version": 1,
      "session_id": "<uuid>", "generation": 3, "saved_at": "...", "saved_by": "PC",
      "exam_name": "Y8 Science Midterm", "created_at": "...",
      "layout": {"paper": "A4", "density": "5mm", "landscape": false},
      "mode": "marks" | "rubric" | null,
      "rubrics":  [{"id": "r1", "name": "Criterion A",
                    "bands": [{"levels": "5–6", "descriptor": "..."}]}],
      "name_box": ["page1!A1:E2"] | [],
      "questions": [{"id": "q1", "label": "Q1", "boxes": ["page1!A4:J10"],
                     "max": 5, "rubric_ids": ["r1"]}],
      "choice_groups": [{"id": "g1", "questions": ["q4", "q5", "q6"], "answer": 2}],
      "students": [{"id": "s001", "scan": "scans/Student_001.pdf",
                    "source": "scan0001.pdf", "pages": 4, "roster_id": null}],
      "roster": [{"id": "n001", "name": "Tanaka Hana"}],
      "sliced": false,
      "resume": {"step": 1, "question_id": null, "student_id": null}
    }

``grades.json`` — written on every click while grading::

    {
      "format": "cam2-grades", "version": 1,
      "session_id": "<uuid>", "generation": 41, "saved_at": "...", "saved_by": "PC",
      "grades":  {"s001": {"q1": {"value": 4, "comment": "Good"},
                           "q2": {"value": "not_answered", "comment": ""},
                           "q3": {"value": null, "comment": "",
                                  "levels": {"r2": 5, "r3": 4}}}},
      "overall": {"s001": {"comment": "", "report_total": null,
                           "final_levels": {"r1": 6}}}
    }

A question with no entry (or ``value`` null) is *ungraded*. A question
assessed on several criteria (``rubric_ids``) keeps one level per criterion
in ``levels``; older sessions have a single ``rubric_id``. Ids, not labels,
key everything so a teacher can rename "Q1" without breaking crops or grades.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .errors import UserError

SESSION_FORMAT = "cam2-session"
GRADES_FORMAT = "cam2-grades"
VERSION = 1

NOT_ANSWERED = "not_answered"
NAME_BOX_ID = "__name__"


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
    """How much teacher work a grades file holds (graded cells + comments).

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
        if isinstance(entry, dict) and str(entry.get("comment") or "").strip():
            count += 1
    return count
