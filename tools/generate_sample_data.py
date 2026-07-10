"""
Generate a small, entirely fictional sample gradebook for Criterion Assessment
Metrics.

Running this writes two identical files:

    acm_database.json                     <- picked up automatically on first run
    sample_data/acm_database.sample.json  <- pristine copy to reset from

Nothing here is real student data. The names, IDs, grades and comments are all
invented so the app has something to display out of the box. To reset the demo
to a clean state, re-run this script.

    py tools/generate_sample_data.py

The gradebook is built through the real engine models and written with the real
persistence layer, so the output always matches whatever schema the app expects.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

# Make the engine importable when run from the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.models import Assignment, Criterion, CriterionScore, Gradebook, Student
from engine.persistence import save_database

CLASS_NAME = "Class 1"
TERM = "Term 1"

# (student_id, display name) — all invented.
STUDENTS = [
    ("100001", "Alex Rivera"),
    ("100002", "Sam Chen"),
    ("100003", "Jordan Okafor"),
    ("100004", "Priya Sharma"),
    ("100005", "Liam O'Brien"),
    ("100006", "Mia Tanaka"),
    ("100007", "Noah Williams"),
    ("100008", "Emma Costa"),
]

# Each assignment: (name, criterion letter, source label, [(sid, band, keywords, comment)])
POSITIVE = "Strengths"
DEVELOP = "Areas to develop"


def _comment(strengths: list[str], develop: list[str]) -> str:
    parts = []
    if strengths:
        parts.append(f"{POSITIVE}: {', '.join(strengths)}.")
    if develop:
        parts.append(f"{DEVELOP}: {', '.join(develop)}.")
    return " ".join(parts)


# Assignment plans: name -> (criterion, term, per-student (band, strengths, develop))
ASSIGNMENTS = [
    (
        "Artist Study", Criterion.A, "Investigating",
        {
            "100001": (6, ["Close observation"], ["Research depth"]),
            "100002": (7, ["Research depth", "Close observation"], []),
            "100003": (5, [], ["Close observation", "Research depth"]),
            "100004": (8, ["Research depth", "Insightful analysis"], []),
            "100005": (6, ["Close observation"], []),
            "100006": (7, ["Insightful analysis"], ["Research depth"]),
            "100007": (4, [], ["Research depth", "Analysis"]),
            "100008": (6, ["Close observation"], ["Analysis"]),
        },
    ),
    (
        "Changing Views", Criterion.B, "Developing",
        {
            "100001": (7, ["Line quality", "Accurate proportion"], []),
            "100002": (6, ["Line quality"], ["Tonal range"]),
            "100003": (6, ["Accurate proportion"], ["Line variation"]),
            "100004": (8, ["Tonal range", "Accurate proportion"], []),
            "100005": (5, [], ["Line variation", "Sense of scale"]),
            "100006": (7, ["Line quality", "Highly detailed"], []),
            "100007": (5, ["Accurate proportion"], ["Highly detailed"]),
            "100008": (6, ["Tonal range"], ["Line variation"]),
        },
    ),
    (
        "Final Composition", Criterion.C, "Creating",
        {
            "100001": (7, ["Creative concept", "Media control"], []),
            "100002": (6, ["Media control"], ["Creative concept"]),
            "100003": (7, ["Creative concept"], []),
            "100004": (7, ["Creative concept", "Media control"], []),
            "100005": (6, ["Media control"], ["Refinement"]),
            "100006": (8, ["Creative concept", "Refinement"], []),
            "100007": (5, [], ["Creative concept", "Refinement"]),
            "100008": (6, ["Media control"], ["Refinement"]),
        },
    ),
    (
        "Final Composition", Criterion.D, "Evaluating",
        {
            "100001": (6, ["Thoughtful reflection"], ["Use of art vocabulary"]),
            "100002": (7, ["Use of art vocabulary", "Thoughtful reflection"], []),
            "100003": (5, [], ["Depth of reflection"]),
            "100004": (7, ["Thoughtful reflection"], []),
            "100005": (6, ["Use of art vocabulary"], ["Depth of reflection"]),
            "100006": (7, ["Thoughtful reflection"], []),
            "100007": (5, [], ["Depth of reflection", "Art vocabulary"]),
            "100008": (6, ["Thoughtful reflection"], []),
        },
    ),
]


def build_gradebook() -> Gradebook:
    gb = Gradebook()
    for sid, name in STUDENTS:
        gb.students[sid] = Student(student_id=sid, name=name)

    ts = datetime(2026, 5, 10, 0, 0, 0)
    seen: dict[str, set[str]] = {}
    for name, criterion, obj_label, per_student in ASSIGNMENTS:
        for sid, (band, strengths, develop) in per_student.items():
            gb.students[sid].add_score(CriterionScore(
                criterion=criterion,
                value=band,
                timestamp=ts,
                source=f"sample:{name}",
                assignment=name,
                keywords=list(strengths) + list(develop),
                comment=_comment(strengths, develop),
            ))
        # Register the assignment once per (name), accumulating its criteria.
        seen.setdefault(name, set()).add(criterion.value)

    for name in dict.fromkeys(a[0] for a in ASSIGNMENTS):  # preserve order, unique
        crits = sorted(seen[name])
        gb.register_assignment(Assignment(
            name=name,
            criteria=crits,
            source_file="",
            ingested_at=ts,
            score_count=len(STUDENTS) * len(crits),
            class_name=CLASS_NAME,
            term=TERM,
        ))
    return gb


def build_session() -> dict:
    """The opaque teacher-side session block the app round-trips verbatim."""
    roster = [
        {"key": sid, "name": name, "email": f"{sid}@school.edu"}
        for sid, name in STUDENTS
    ]
    return {
        "classes": [{"name": CLASS_NAME, "grade": "7", "myp_year": "2",
                     "subject": "Visual Arts", "master_dir": ""}],
        "active_class": CLASS_NAME,
        "active_term": TERM,
        "calc_method": "60/40 Recency",
        "rosters": {CLASS_NAME: roster},
    }


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    gb = build_gradebook()
    session = build_session()

    sample_dir = os.path.join(root, "sample_data")
    os.makedirs(sample_dir, exist_ok=True)
    sample_path = os.path.join(sample_dir, "acm_database.sample.json")
    root_path = os.path.join(root, "acm_database.json")

    save_database(sample_path, gb, session)
    save_database(root_path, gb, session)
    print(f"Wrote {len(gb)} students, {len(gb.assignments)} assignments to:")
    print(f"  {sample_path}")
    print(f"  {root_path}")


if __name__ == "__main__":
    main()
