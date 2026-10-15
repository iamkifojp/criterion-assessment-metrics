"""Comments-only data must survive ingestion without becoming grade zero.

Fictional fixtures only; extracts dashboard policy functions without starting
Streamlit or opening any device preferences or databases.
"""
import csv
from datetime import datetime
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from engine.models import Assignment, Criterion, CriterionScore, Gradebook
from engine.ingestion import IngestionPipeline
from engine.aggregation import aggregate_student_criterion
from engine.persistence import serialize_gradebook, deserialize_gradebook, DatabaseValidationError
from tests.test_submission_identity import functions_from, ROOT


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.book = Gradebook()
        self.pipeline = IngestionPipeline(self.book)

    def ingest(self, rows, **kwargs):
        path = Path(self.tmp.name) / "Draft.csv"
        with path.open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        return self.pipeline.ingest_csv(str(path), "Investigation", **kwargs)

    def test_draft_discards_stale_marks_but_keeps_feedback_and_focus(self):
        rows = [{"Student Name": "10001", "Assessment Mode": "draft",
                 "Focus Criteria": "A", "Grade (Crit A)": "0",
                 "Comment": "Explain the artist's context.",
                 "Checked Keywords": "Context", "Files (newest first)": "Ada Rivera.docx"}]
        self.assertEqual(self.ingest(rows), [])
        task = self.book.assignments[0]
        self.assertTrue(task.is_draft)
        self.assertTrue(task.is_formative)
        self.assertEqual(task.criteria, ["A"])
        self.assertEqual(task.draft_feedback["10001"]["comment"], rows[0]["Comment"])
        self.assertIsNone(aggregate_student_criterion(self.book.students["10001"], Criterion.A))
        rebuilt = deserialize_gradebook(serialize_gradebook(self.book))
        self.assertEqual(rebuilt.assignments[0].draft_feedback, task.draft_feedback)
        self.assertTrue(rebuilt.assignments[0].is_draft)

    def test_explicit_mode_overrides_legacy_csv_and_preserves_blank_submission(self):
        self.ingest([{"Student Name": "10001", "Grade (Crit A)": "8",
                      "Files (newest first)": "Ada Rivera.docx", "Comment": ""}],
                    is_draft=True, draft_criteria=["A"])
        self.assertIn("10001", self.book.assignments[0].draft_feedback)
        self.assertEqual(self.book.assignments[0].score_count, 0)

    def test_regular_zero_remains_a_real_score(self):
        scores = self.ingest([{"Student Name": "10001", "Grade (Crit A)": "0"}])
        self.assertEqual([s.value for s in scores], [0])
        self.assertFalse(self.book.assignments[0].is_draft)

    def test_draft_legacy_generic_grade_needs_no_numeric_criterion_mapping(self):
        self.assertEqual(self.ingest([{"Student Name": "10001", "Grade": "0",
                                      "Comment": "Explain the context."}],
                                     is_draft=True, draft_criteria=["A"]), [])
        self.assertEqual(self.book.assignments[0].criteria, ["A"])

    def test_unmatched_feedback_can_be_assigned_without_minting_a_mark(self):
        pool = []
        self.ingest([{"Student Name": "unmatched_scan", "Assessment Mode": "draft",
                      "Focus Criteria": "A", "Comment": "Add sources."}],
                    roster_keys={"10001"}, unmatched_out=pool)
        self.assertEqual(len(pool), 1)
        self.assertEqual(pool[0]["grades"], [])
        self.book.assignments[0].class_name = "Art"
        other = Assignment(name="Investigation", class_name="Other", is_draft=True)
        self.book.assignments.append(other)
        self.assertEqual(self.pipeline.materialize_row("Investigation", "10001", pool[0], "Art"), [])
        self.assertEqual(self.book.assignments[0].draft_feedback["10001"]["comment"], "Add sources.")
        self.assertEqual(other.draft_feedback, {})

    def test_exported_unnamed_extra_file_preserves_feedback_through_assign_and_resync(self):
        rows = [
            {"Student Name": "10001", "Assessment Mode": "draft", "Focus Criteria": "A",
             "Files (newest first)": "Ada Rivera.pdf", "Comment": "Explain the context.",
             "Checked Keywords": "Context"},
            {"Student Name": "Unmatched scan: unnamed.pdf", "Assessment Mode": "draft", "Focus Criteria": "A",
             "Files (newest first)": "unnamed.pdf", "Comment": "", "Checked Keywords": ""},
        ]
        pool = []
        self.ingest(rows, roster_keys={"10001", "10002"}, unmatched_out=pool)
        self.assertEqual(len(pool), 1)  # Even an unreviewed draft is matchable.
        task = self.book.assignments[0]
        task.class_name = "Art"
        self.pipeline.materialize_row("Investigation", "10001", pool[0], "Art")
        expected = dict(task.draft_feedback["10001"])
        self.assertEqual(expected["comment"], "Explain the context.")
        self.assertEqual(expected["keywords"], ["Context"])
        self.assertEqual(expected["files"], "Ada Rivera.pdf; unnamed.pdf")
        self.book.assignments.clear()
        self.ingest(rows, roster_keys={"10001", "10002"},
                    aliases={rows[1]["Student Name"]: "10001"})
        resynced = self.book.assignments[0].draft_feedback["10001"]
        for field in ("comment", "keywords", "files", "late"):
            self.assertEqual(resynced[field], expected[field])
        self.assertFalse(any(self.book.students["10001"].scores.values()))

    def test_assigning_second_reviewed_file_combines_feedback(self):
        pool = []
        self.ingest([
            {"Student Name": "10001", "Assessment Mode": "draft", "Comment": "Context.",
             "Files (newest first)": "named.pdf", "Checked Keywords": "Context"},
            {"Student Name": "unknown", "Assessment Mode": "draft", "Comment": "Sources.",
             "Files (newest first)": "scan.pdf", "Checked Keywords": "Context; Sources"},
        ], roster_keys={"10001"}, unmatched_out=pool)
        self.pipeline.materialize_row("Investigation", "10001", pool[0])
        feedback = self.book.assignments[0].draft_feedback["10001"]
        self.assertEqual(feedback["comment"], "Context.\n\nSources.")
        self.assertEqual(feedback["keywords"], ["Context", "Sources"])

    def test_invalid_feedback_is_rejected_and_legacy_assignments_default_to_graded(self):
        payload = {"students": [], "assignments": [{"name": "Old", "criteria": ["A"]}]}
        self.assertFalse(deserialize_gradebook(payload).assignments[0].is_draft)
        payload["assignments"][0]["draft_feedback"] = {"10001": {"comment": 7}}
        with self.assertRaises(DatabaseValidationError):
            deserialize_gradebook(payload)

    def test_module_three_never_injects_zero_or_uses_retained_draft_marks(self):
        self.book.assignments = [Assignment(name="Draft", class_name="Art", is_draft=True),
                                 Assignment(name="Final", class_name="Art", criteria=["A"])]
        student = self.book.get_or_create("10001")
        student.add_score(CriterionScore(Criterion.A, 0, datetime.now(), assignment="Draft"))
        student.add_score(CriterionScore(Criterion.A, 6, datetime.now(), assignment="Final"))
        rows = [{"name": a.name, "criteria": "A", "is_draft": a.is_draft,
                 "is_exam": False, "avg": None, "date": datetime.now()} for a in self.book.assignments]
        ns = dict(st=SimpleNamespace(session_state={"active_class": "Art", "excused_flags": {}}),
                  gb=lambda: self.book, assignment_table=lambda: rows,
                  assignment_on=lambda name: True, awaiting_grade=lambda row: False,
                  is_excused=lambda *args: False, current_term_assignment_names=lambda: {"Draft", "Final"},
                  calculation_method=lambda sid: "Weighted Median", Criterion=Criterion,
                  aggregate_student_criterion=aggregate_student_criterion)
        functions_from(ROOT / "app.py", ["excused_assignments_for", "draft_assignment_names",
            "assessment_exclusions_for", "missing_assignment_rows", "missing_zero_points",
            "aggregate_with_policy", "qualifying_assignment_count", "draft_feedback_for"], ns)
        empty = self.book.get_or_create("10002")
        self.assertEqual([r["name"] for r in ns["missing_assignment_rows"](empty)], ["Final"])
        self.assertEqual(ns["qualifying_assignment_count"](), 1)
        result = ns["aggregate_with_policy"](student, "A")
        self.assertEqual(result.rounded_band, 6)


if __name__ == "__main__":
    unittest.main()
