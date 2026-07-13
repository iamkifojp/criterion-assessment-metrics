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
from typing import Any, Dict, List, Optional


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
    # section name -> the labels the teacher picked to count for an *over-answered*
    # choice section (Phase 5 strict-`?` resolution). Empty for legacy /
    # all-required exams; a section stays "pending" until its entry here names
    # exactly ``required`` of the answered labels. Preserved across re-ingest.
    chosen: Dict[str, List[str]] = field(default_factory=dict)
    # section name -> teacher-picked 0-8 level for that strand (Phase 6). The
    # real cover sheet has the teacher circle a level per strand (section), then
    # decide one final criterion grade; this holds those per-strand levels. The
    # app only *suggests* them (proportional per section); only the final grade
    # enters the gradebook. Empty for legacy / single-section exams. Preserved
    # across re-ingest exactly like ``chosen``.
    section_bands: Dict[str, int] = field(default_factory=dict)

    @property
    def percent(self) -> float:
        return (self.total / self.max_total * 100.0) if self.max_total else 0.0

    def suggested_band(self) -> int:
        """Proportional 0-8 band suggestion from the raw total."""
        if not self.max_total:
            return 0
        return max(MIN_BAND, min(MAX_BAND, round(self.total / self.max_total * MAX_BAND)))


# --------------------------------------------------------------------------
# Section-aware exam scoring (Phase 5)
# --------------------------------------------------------------------------
#
# An exam may be split into sections (carried by ``Assignment.sections`` and the
# ``*.meta.json`` export sidecar). A section is a plain dict:
#
#     {"name": "Section B", "required": 2 | None,
#      "questions": [{"label": "Q5", "max": 8}, ...]}
#
# ``required`` None means "every question counts" (a normal section). An integer
# means the student need only answer that many — a *choice* section. When a
# student answers MORE than ``required`` the section is **over-answered**: per the
# teacher's strict-`?` decision the app never auto-picks which answers count, so
# the section (and the exam total) reads ``?`` until the teacher resolves it in
# Window 3, recording the picked labels in ``ExamResult.chosen``.
#
# These helpers are deliberately pure (no Streamlit, no persistence) so they are
# unit-testable and shared by every surface that shows a raw exam number.


@dataclass
class SectionState:
    """Computed scoring view of one exam section for one student's result."""

    name: str
    required: Optional[int]     # None = every question counts
    labels: List[str]           # every question label defined in the section
    answered: List[str]         # labels the student has a recorded mark for
    chosen: List[str]           # teacher-picked labels (over-answered sections)
    counting: List[str]         # labels whose marks actually count right now
    subtotal: int               # sum of the counting marks
    section_max: int            # max attainable (the ``required`` largest maxes)
    over_answered: bool         # answered more questions than ``required``
    resolved: bool              # no outstanding teacher choice needed
    pending: bool               # over-answered and not yet resolved


def _coerce_required(section: Dict[str, Any]) -> Optional[int]:
    """A section's ``required`` as an int, or None for 'all questions count'."""
    req = section.get("required")
    if req is None:
        return None
    try:
        return int(req)
    except (TypeError, ValueError):
        return None


def section_max(section: Dict[str, Any]) -> int:
    """Max attainable for one section.

    All-required section (``required`` None) → sum of every question max. Choice
    section → sum of the ``required`` largest question maxes (the best case the
    student can reach by answering ``required`` of them)."""
    maxes = sorted(
        (int(q.get("max", 0) or 0) for q in section.get("questions", [])),
        reverse=True,
    )
    req = _coerce_required(section)
    if req is None:
        return sum(maxes)
    return sum(maxes[:max(0, req)])


def section_state(result: "ExamResult", section: Dict[str, Any]) -> SectionState:
    """Resolve one section against a student's raw marks (see module notes)."""
    name = str(section.get("name", ""))
    required = _coerce_required(section)
    labels = [str(q.get("label")) for q in section.get("questions", [])
              if q.get("label") is not None]
    answered = [lbl for lbl in labels if lbl in result.questions]
    over_answered = required is not None and len(answered) > required
    picked = result.chosen.get(name, []) if isinstance(result.chosen, dict) else []
    # Only picks that are still answered labels count (defends re-ingest churn).
    chosen = [lbl for lbl in picked if lbl in answered]
    if over_answered:
        resolved = len(chosen) == required
        counting = list(chosen) if resolved else []
    else:
        resolved = True
        counting = list(answered)
    subtotal = sum(int(result.questions.get(lbl, 0)) for lbl in counting)
    return SectionState(
        name=name, required=required, labels=labels, answered=answered,
        chosen=chosen, counting=counting, subtotal=subtotal,
        section_max=section_max(section), over_answered=over_answered,
        resolved=resolved, pending=over_answered and not resolved,
    )


def resolved_total(result: "ExamResult",
                   sections: Optional[List[Dict[str, Any]]]) -> int:
    """Exam raw total honouring choice-section resolutions.

    No sections metadata → exactly the stored ``result.total`` (legacy path). A
    pending (unresolved over-answered) section contributes nothing — the total is
    then reported as pending via :func:`exam_is_pending`."""
    if not sections:
        return int(result.total)
    return sum(st.subtotal for st in
               (section_state(result, s) for s in sections) if not st.pending)


def resolved_max(result: "ExamResult",
                 sections: Optional[List[Dict[str, Any]]]) -> int:
    """Exam raw max honouring choice sections (every section always counted).

    No sections metadata → the stored ``result.max_total`` (legacy path). Takes
    ``result`` too (unlike the plan's ``resolved_max(sections)`` sketch) so the
    no-sections fallback can read the stored max."""
    if not sections:
        return int(result.max_total)
    return sum(section_max(s) for s in sections)


def exam_is_pending(result: "ExamResult",
                    sections: Optional[List[Dict[str, Any]]]) -> bool:
    """True when any choice section is over-answered and not yet resolved."""
    if not sections:
        return False
    return any(section_state(result, s).pending for s in sections)


def resolved_suggested_band(result: "ExamResult",
                            sections: Optional[List[Dict[str, Any]]]) -> int:
    """Proportional 0-8 band from the *resolved* total/max (see helpers above)."""
    mx = resolved_max(result, sections)
    if not mx:
        return 0
    tot = resolved_total(result, sections)
    return max(MIN_BAND, min(MAX_BAND, round(tot / mx * MAX_BAND)))


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
    # Section structure carried by the export sidecar (*.meta.json). Each entry:
    # {"name", "required" (int|None), "questions": [{"label", "max"}]}. None ==
    # legacy single-section exam (every question counts); the scoring helpers
    # above collapse to today's total/max in that case.
    sections: Optional[List[dict]] = None

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
