"""Exam comments in a student's term comment (CAM2 engine upgrade, Phase 3: F6).

A teacher's comments on an exam paper are always part of the source material
for the term comment. A comment is about 100 to 150 words, and below about 500
to 1,000 words of source the AI tends to copy word for word, so the material has
a limit (P13):

* about 6,000 characters in all, counted in characters because Japanese has no
  spaces;
* exams can always use up to 4,000, and can use more when drafts and assignments
  leave room. Drafts and assignments have no limit of their own, so they only
  count toward the total;
* every overall comment goes in whole, even over the limit;
* over the limit, whole question comments are left out, taken evenly across the
  exams and never cut mid-sentence, and the teacher is told how many.

No levels or grades appear here, so this respects **No numbers** (P12).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

TOTAL_LIMIT = 6000
EXAM_ALLOWANCE = 4000


@dataclass
class ExamFeedback:
    """One exam's comments for one student, in question order."""

    exam: str
    overall: List[str] = field(default_factory=list)
    questions: List[Tuple[str, str]] = field(default_factory=list)   # (label, comment)

    @property
    def characters(self) -> int:
        return (sum(len(text) for text in self.overall)
                + sum(len(text) for _, text in self.questions))


def exam_allowance(other_characters: int) -> int:
    """What exams may use, given the drafts and assignments going in."""
    return max(EXAM_ALLOWANCE, TOTAL_LIMIT - max(0, other_characters))


def limit_feedback(exams: List[ExamFeedback], other_characters: int = 0
                   ) -> Tuple[List[ExamFeedback], int]:
    """Fit the exams to their allowance. Returns ``(kept, left_out)``, where
    ``left_out`` counts the question comments dropped. The inputs are unchanged.

    While over, the exam with the most question comments left gives up its last
    one, so the loss is shared evenly and the earlier questions stay."""
    kept = [ExamFeedback(e.exam, list(e.overall), list(e.questions)) for e in exams]
    allowance = exam_allowance(other_characters)
    total = sum(e.characters for e in kept)
    left_out = 0
    while total > allowance:
        donor = max(kept, key=lambda e: len(e.questions), default=None)
        if donor is None or not donor.questions:
            break
        _, text = donor.questions.pop()
        total -= len(text)
        left_out += 1
    return [e for e in kept if e.overall or e.questions], left_out


def feedback_lines(exams: List[ExamFeedback]) -> List[str]:
    """The lines of the prompt's exam block. Comments stay out of quotation
    marks, which would invite the AI to repeat them word for word."""
    lines = []
    for exam in exams:
        lines += [f"{exam.exam}, overall: {text}" for text in exam.overall]
        lines += [f"{exam.exam}, {label}: {text}" for label, text in exam.questions]
    return lines
