"""Exercise dashboard submission controls without starting Streamlit or using disk."""
import unittest

from engine.models import Assignment, Gradebook
from tests.test_submission_identity import functions_from, ROOT


class RecordingUi:
    def __init__(self, state, clicked=""):
        self.session_state = state
        self.clicked = clicked
        self.messages = []
        self.buttons = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def columns(self, sizes, **kwargs):
        return [self] * (sizes if isinstance(sizes, int) else len(sizes))

    def container(self, **kwargs):
        return self

    def popover(self, label, **kwargs):
        self.messages.append(label)
        return self

    def caption(self, text):
        self.messages.append(text)

    markdown = subheader = write = caption

    def button(self, label, **kwargs):
        self.buttons.append((label, kwargs.get("key")))
        return kwargs.get("key") == self.clicked

    def file_uploader(self, *args, **kwargs):
        return None

    def text_input(self, *args, **kwargs):
        return kwargs["value"]

    def selectbox(self, label, options, index, **kwargs):
        return options[index]


class SubmissionUiTests(unittest.TestCase):
    def setUp(self):
        self.book = Gradebook()
        self.student = self.book.get_or_create("10001")
        self.task = Assignment(name="Draft", class_name="Art", is_draft=True,
                               draft_feedback={"10001": {"files": "named.pdf"}})
        self.book.assignments = [self.task]
        self.ui = RecordingUi({
            "active_class": "Art", "staging": [], "prefs": {}, "focus_sid": "10001",
            "roster": [{"key": "10001", "name": "Rivera Ada", "gender": ""}],
            "unmatched_works": {"Art": {"Draft": [{"csv_key": "unknown"}]}},
        })
        self.matches = []
        self.ns = dict(
            st=self.ui, gb=lambda: self.book,
            assignment_table=lambda: [{"name": "Draft", "is_draft": True, "criteria": "A"}],
            assignment_on=lambda name: True, current_term=lambda: "Term 1",
            active_roster_order=lambda: "default", ROSTER_ORDER_LABELS={"default": "roster"},
            GENDER_OPTIONS=[], scores_for_assignment=lambda name: [],
            match_works_dialog=lambda *args: self.matches.append(args),
            find_student=lambda sid: self.student, student_email_for=lambda student: "",
            student_label=lambda student: student.student_id,
            draft_feedback_for=lambda student: [(self.task, self.task.draft_feedback["10001"])]
                if "10001" in self.task.draft_feedback else [],
        )
        for name in ("_render_exam_sections", "_render_trend", "_render_grade_panel",
                     "_render_comments", "_render_ai_deck"):
            self.ns[name] = lambda student: None
        functions_from(ROOT / "app.py", ["submitter_keys", "render_window2", "render_window3"], self.ns)

    def test_submitted_student_can_match_an_additional_file(self):
        self.ui.clicked = "match_extra_10001_Draft"
        self.ns["render_window2"]()
        self.assertIn("✓", self.ui.messages)
        self.assertEqual(self.matches, [("10001", "Draft")])

    def test_missing_student_can_match_first_file(self):
        self.task.draft_feedback.clear()
        self.ui.clicked = "matchbtn_10001_Draft"
        self.ns.update(is_excused=lambda *args: False)
        self.ns["render_window2"]()
        self.assertIn("⚠1", self.ui.messages)
        self.assertEqual(self.matches, [("10001", "Draft")])

    def test_cockpit_distinguishes_submitted_pending_reviewed_and_missing(self):
        self.ns["render_window3"]()
        self.assertIn("Submitted · awaiting feedback", self.ui.messages)
        self.ui.messages.clear()
        self.task.draft_feedback["10001"]["keywords"] = ["Context"]
        self.ns["render_window3"]()
        self.assertIn("Submitted · feedback recorded", self.ui.messages)
        self.assertIn("Context", self.ui.messages)
        self.ui.messages.clear()
        self.task.draft_feedback.clear()
        self.ns["render_window3"]()
        self.assertTrue(any("No submission recorded" in m for m in self.ui.messages))


if __name__ == "__main__":
    unittest.main()
