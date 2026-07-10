"""
Criterion D (Evaluating) manual-entry schema.

Criterion D is assessed from ongoing student reflection rather than a single
graded artefact, so there is no CSV to ingest. Instead the engine seeds each
student with a series of placeholder reflection entries (band 0-8) that the
teacher fills in manually later.

The placeholders are spread *chronologically* across the assignment timeline
so that, once scored, they feed straight into the same recency-weighted
aggregation used for the CSV-based criteria. By default each student gets 6-7
entries dated evenly between the earliest and latest assessment dates already
recorded for that student.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from .models import Criterion, CriterionScore, Gradebook, Student


# Default number of reflection placeholders to create per student.
DEFAULT_ENTRY_COUNT = 6
PLACEHOLDER_VALUE = 0  # 0 = "not yet assessed"; teacher overwrites with 1-8.


class CriterionDInitializer:
    """Seeds placeholder Criterion D reflection entries for students."""

    def __init__(self, gradebook: Gradebook):
        self.gradebook = gradebook

    def initialize_all(
        self,
        *,
        entries_per_student: int = DEFAULT_ENTRY_COUNT,
        timeline: Optional[Tuple[datetime, datetime]] = None,
        skip_existing: bool = True,
    ) -> int:
        """Seed every student in the gradebook. Returns total entries created.

        ``entries_per_student`` is clamped to 6-7 to match the spec.
        ``timeline`` optionally fixes a global (start, end) date span; if not
        given, each student's own earliest/latest score dates are used.
        """
        count = max(6, min(7, entries_per_student))
        total = 0
        for student in self.gradebook:
            total += self.initialize_student(
                student,
                entries=count,
                timeline=timeline,
                skip_existing=skip_existing,
            )
        return total

    def initialize_student(
        self,
        student: Student,
        *,
        entries: int = DEFAULT_ENTRY_COUNT,
        timeline: Optional[Tuple[datetime, datetime]] = None,
        skip_existing: bool = True,
    ) -> int:
        """Seed one student. Returns the number of entries created."""
        if skip_existing and student.criterion_scores(Criterion.D, valid_only=False):
            return 0

        start, end = timeline if timeline else self._student_timeline(student)
        dates = self._evenly_spaced(start, end, entries)

        for i, when in enumerate(dates, start=1):
            student.add_score(
                CriterionScore(
                    criterion=Criterion.D,
                    value=PLACEHOLDER_VALUE,
                    timestamp=when,
                    source="manual:reflection",
                    assignment=f"Reflection {i}",
                    is_valid=False,  # placeholder: excluded until teacher scores it
                    note="Placeholder reflection - awaiting teacher entry",
                )
            )
        return len(dates)

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _student_timeline(student: Student) -> Tuple[datetime, datetime]:
        """Derive a (start, end) span from a student's existing scores."""
        stamps: List[datetime] = [
            s.timestamp
            for bucket in student.scores.values()
            for s in bucket
            if s.criterion != Criterion.D
        ]
        if stamps:
            return min(stamps), max(stamps)
        # No prior data: default to a single-term span ending today.
        now = datetime.now()
        return now - timedelta(weeks=10), now

    @staticmethod
    def _evenly_spaced(start: datetime, end: datetime, n: int) -> List[datetime]:
        """Return ``n`` datetimes spread evenly across [start, end]."""
        if n <= 1:
            return [start]
        if end <= start:
            # Degenerate span: stack entries one day apart for stable ordering.
            return [start + timedelta(days=i) for i in range(n)]
        step = (end - start) / (n - 1)
        return [start + step * i for i in range(n)]
