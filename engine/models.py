"""
Domain models for the Art Criterion Metrics engine.

IB MYP Arts is assessed against four criteria, each on a 0-8 band scale:

    A - Investigating  (Knowing and understanding)
    B - Developing     (Developing skills)
    C - Creating       (Creating / Thinking creatively)
    D - Evaluating     (Responding / Reflection)

A student accumulates several *CriterionScore* records per criterion over a
school year. Each score is stamped with a timestamp so that the aggregation
layer can weight recent work more heavily than older work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional


# Valid MYP band range. Scores must fall within [MIN_BAND, MAX_BAND].
MIN_BAND = 0
MAX_BAND = 8


class Criterion(str, Enum):
    """The four MYP Arts assessment criteria."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"

    @property
    def label(self) -> str:
        return MYP_CRITERIA[self.value]


# Human-readable names for the criteria (used in reports / UI later).
MYP_CRITERIA: Dict[str, str] = {
    "A": "Investigating",
    "B": "Developing",
    "C": "Creating",
    "D": "Evaluating",
}


def _validate_band(value: int) -> int:
    """Raise if a score is outside the legal MYP band range."""
    if not isinstance(value, int):
        raise TypeError(f"Band score must be an int, got {type(value).__name__}")
    if value < MIN_BAND or value > MAX_BAND:
        raise ValueError(
            f"Band score {value} out of range [{MIN_BAND}, {MAX_BAND}]"
        )
    return value


@dataclass
class CriterionScore:
    """
    A single graded data point for one criterion at one point in time.

    Attributes
    ----------
    criterion   : which MYP criterion this score belongs to.
    value       : the 0-8 band awarded.
    timestamp   : when the assessed work is dated (parsed, overridden, or
                  ingestion time). Drives recency weighting.
    source      : free-text origin ("csv:Changing Views", "manual", ...).
    assignment  : short label for the assignment/unit this score came from.
    keywords    : optional rubric keywords logged with the score.
    comment     : optional teacher comment.
    is_valid    : False marks a flagged/excluded entry (e.g. "wrong
                  assignment") so aggregation can skip it without data loss.
    include_in_report : teacher-facing balancing toggle. When False the score
                  is kept on record but completely ignored by the recency-
                  weighted calculation, letting the teacher tune which pieces
                  of evidence count toward the final suggestion.
    note        : reason a score is flagged or otherwise annotated.
    late        : True when this piece was submitted late, as synced from the
                  grading workspace's Late column. This is the *data* layer of
                  lateness; the app keeps a separate manual override map
                  (``late_flags``) that a teacher can use to waive or force it.
    """

    criterion: Criterion
    value: int
    timestamp: datetime
    source: str = ""
    assignment: str = ""
    keywords: List[str] = field(default_factory=list)
    comment: str = ""
    is_valid: bool = True
    include_in_report: bool = True
    note: str = ""
    late: bool = False

    def __post_init__(self) -> None:
        self.criterion = Criterion(self.criterion)
        _validate_band(self.value)


@dataclass
class ExamResult:
    """One student's raw item-level result for one exam assignment.

    Exams arrive from the CAM grading app with per-question raw marks whose
    total is NOT on the MYP 0-8 band scale (e.g. 37/45), so they are kept in
    this separate container instead of :class:`CriterionScore`. The teacher
    later assigns a 0-8 band to the exam (Window 1 dropdown), which is what
    enters the gradebook as a normal ``CriterionScore``.
    """

    assignment: str
    total: int = 0
    max_total: int = 0
    # question label -> raw mark, in the teacher's grading order
    questions: Dict[str, int] = field(default_factory=dict)
    comment: str = ""

    @property
    def percent(self) -> float:
        return (self.total / self.max_total * 100.0) if self.max_total else 0.0

    def suggested_band(self) -> int:
        """Proportional 0-8 band suggestion from the raw total."""
        if not self.max_total:
            return 0
        return max(MIN_BAND, min(MAX_BAND, round(self.total / self.max_total * MAX_BAND)))


@dataclass
class Student:
    """A student and all of their criterion scores across the year."""

    student_id: str
    name: str = ""
    # Optional gender selection ("Male" / "Female" / "Non-Binary" / ""). Used to
    # derive report-comment pronouns; blank means "unspecified" (-> they/them).
    gender: str = ""
    # criterion letter -> chronological list of scores
    scores: Dict[str, List[CriterionScore]] = field(default_factory=dict)
    # exam assignment name -> raw item-level result (kept off the 0-8 scale)
    exam_results: Dict[str, "ExamResult"] = field(default_factory=dict)

    def add_score(self, score: CriterionScore) -> None:
        bucket = self.scores.setdefault(score.criterion.value, [])
        bucket.append(score)
        # Keep each criterion bucket sorted oldest -> newest.
        bucket.sort(key=lambda s: s.timestamp)

    def criterion_scores(
        self, criterion: Criterion, valid_only: bool = True
    ) -> List[CriterionScore]:
        """Chronological scores for one criterion (oldest first)."""
        crit = Criterion(criterion).value
        bucket = self.scores.get(crit, [])
        if valid_only:
            return [s for s in bucket if s.is_valid]
        return list(bucket)

    @property
    def display_name(self) -> str:
        return self.name or self.student_id


@dataclass
class Assignment:
    """Metadata for one assessment event (an ingested file or a logged task).

    An assignment can assess anywhere from 0 to all 4 criteria. A formative or
    skipped-week event assesses 0 criteria: it is still recorded here so it
    appears on the timeline, but it contributes no numerical scores to any
    student.

    Attributes
    ----------
    name        : human label for the assignment ("Changing Views (Crit B)").
    criteria    : criterion letters this assignment fed scores into (0-4).
    source_file : originating CSV path, if any.
    ingested_at : when the assignment was ingested/logged.
    score_count : how many numerical scores it produced across all students.
    note        : free-text annotation (e.g. "formative - no grades").
    class_name  : the class/level this assignment belongs to (e.g. "1-4"), so a
                  single gradebook can hold every class taught across the year.
    term        : the school term this assignment belongs to (e.g. "Term 1").
                  Drives multi-term context compression in the prompt engine:
                  assignments in *past* terms are summarised rather than passed
                  as raw evidence. Blank means "untagged" and is treated as the
                  active term by the front end for backward compatibility.
    folder_ref  : the on-disk subfolder path or Google Drive folder ID this
                  assignment was discovered from by the class master-directory
                  "Watch" scan. The display ``name`` can be edited freely
                  without renaming the physical folder — this ref stays pinned
                  to the real folder so re-scans never duplicate a renamed
                  assignment, and the grading-workspace bridge can target it.
    grading_complete : True once every submitted work in this assignment's
                  folder has been graded, computed read-only from the most
                  recent synced CSV (File Count / Files columns identify
                  submissions; a "Grade*" cell marks them graded). Only
                  meaningful for folder-backed rows (``folder_ref`` set); it
                  gates the Window 3 "Awaiting Grade" pill — while False a
                  scoreless student is still awaiting the folder's grades, once
                  True they fall through to the standard Missing = 0 policy.
    """

    name: str
    criteria: List[str] = field(default_factory=list)
    source_file: str = ""
    ingested_at: Optional[datetime] = None
    score_count: int = 0
    note: str = ""
    class_name: str = ""
    term: str = ""
    folder_ref: str = ""
    grading_complete: bool = False
    # Exam (item-level) imports from the CAM grading app. Raw totals live in
    # each Student.exam_results[name]; ``criteria`` stays empty until the
    # teacher assigns 0-8 bands, at which point normal CriterionScores appear.
    is_exam: bool = False
    max_total: int = 0
    question_labels: List[str] = field(default_factory=list)

    @property
    def is_formative(self) -> bool:
        """True when the assignment assessed no criteria (0-criterion event)."""
        return len(self.criteria) == 0 and not self.is_exam


@dataclass
class Gradebook:
    """Container for all students and the assignments behind their scores."""

    students: Dict[str, Student] = field(default_factory=dict)
    assignments: List[Assignment] = field(default_factory=list)

    def get_or_create(self, student_id: str, name: str = "") -> Student:
        sid = str(student_id).strip()
        student = self.students.get(sid)
        if student is None:
            student = Student(student_id=sid, name=name)
            self.students[sid] = student
        elif name and not student.name:
            student.name = name
        return student

    def register_assignment(self, assignment: Assignment) -> Assignment:
        """Record an assignment's metadata (including 0-criterion events)."""
        self.assignments.append(assignment)
        return assignment

    def __len__(self) -> int:
        return len(self.students)

    def __iter__(self):
        return iter(self.students.values())


@dataclass
class UnitPlan:
    """Metadata extracted from an MYP unit-plan document."""

    unit_title: str = ""
    statement_of_inquiry: str = ""
    # criterion letter -> objective heading (e.g. "A" -> "Investigating")
    target_criteria: Dict[str, str] = field(default_factory=dict)
    # MYP key/related concepts driving the unit (e.g. ["Communication",
    # "Composition"]). Surfaced in the prompt engine's curriculum-context block.
    key_concepts: List[str] = field(default_factory=list)
    myp_year: Optional[str] = None
    source_file: str = ""

    @property
    def criteria_letters(self) -> List[str]:
        return sorted(self.target_criteria.keys())

    @property
    def concepts_text(self) -> str:
        """Comma-joined concepts for compact display / prompt injection."""
        return ", ".join(c for c in self.key_concepts if c)
