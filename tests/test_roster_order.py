"""Tests for per-class roster name order — UI polish plan Phase 3.

Covers docs/UI_AND_DELIVERABLES_POLISH_PLAN.md Phase 3: the generalised
:func:`app.sort_roster` (4 modes sharing the surname-peeling logic), and the
invariant that the Excel "Classroom Entry" tab keeps Google Classroom's own
Latin order regardless of the class's ``roster_order`` setting.

Pure stdlib ``unittest``; no Streamlit run, no app launch. Run:

    python -m unittest tests.test_roster_order
"""

import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (path shim must precede the import)


# A handful of students whose four orderings genuinely differ. Names are stored
# "Surname First"; ``first`` is the given name; ``email`` local part is the ID.
# Surnames chosen so gojūon and Latin A–Z disagree: Baba(ば)/Aoki(あ) invert.
ROSTER = [
    {"key": "1", "name": "Shimizu Emi",  "first": "Emi",  "email": "300@s.jp"},
    {"key": "2", "name": "Aoki Daichi",  "first": "Daichi", "email": "100@s.jp"},
    {"key": "3", "name": "Iida Bob",     "first": "Bob",  "email": "400@s.jp"},
    {"key": "4", "name": "Chiba Akira",  "first": "Akira", "email": "200@s.jp"},
    {"key": "5", "name": "Baba Chiaki",  "first": "Chiaki", "email": "500@s.jp"},
]


def _names(entries):
    return [e["name"] for e in entries]


class SortRosterModeTests(unittest.TestCase):
    def test_last_first_latin(self):
        got = _names(app.sort_roster(ROSTER, "last_first"))
        # Alphabetical by surname: Aoki, Baba, Chiba, Iida, Shimizu.
        self.assertEqual(
            got, ["Aoki Daichi", "Baba Chiaki", "Chiba Akira",
                  "Iida Bob", "Shimizu Emi"])

    def test_first_last_latin(self):
        got = _names(app.sort_roster(ROSTER, "first_last"))
        # Alphabetical by given name: Akira, Bob, Chiaki, Daichi, Emi.
        self.assertEqual(
            got, ["Chiba Akira", "Iida Bob", "Baba Chiaki",
                  "Aoki Daichi", "Shimizu Emi"])

    def test_email(self):
        got = _names(app.sort_roster(ROSTER, "email"))
        # By email local part 100..500: Aoki, Chiba, Shimizu, Iida, Baba.
        self.assertEqual(
            got, ["Aoki Daichi", "Chiba Akira", "Shimizu Emi",
                  "Iida Bob", "Baba Chiaki"])

    def test_gojuon_differs_from_latin(self):
        got = _names(app.sort_roster(ROSTER, "gojuon"))
        # Gojūon reads the surname kana: あ(Aoki) お(Ooki?) — here surnames map
        # Aoki<Iida<Shimizu<Chiba<Baba by reading; the key assertion is that it
        # is NOT the Latin surname order, and Baba(ば) sinks below Chiba(ち).
        self.assertNotEqual(got, _names(app.sort_roster(ROSTER, "last_first")))
        self.assertLess(got.index("Chiba Akira"), got.index("Baba Chiaki"))

    def test_default_is_gojuon(self):
        self.assertEqual(app.sort_roster(ROSTER),
                         app.sort_roster(ROSTER, "gojuon"))

    def test_unknown_mode_falls_back_to_gojuon(self):
        self.assertEqual(app.sort_roster(ROSTER, "nonsense"),
                         app.sort_roster(ROSTER, "gojuon"))

    def test_stable_within_equal_keys(self):
        # Sorting is order-preserving for entries with equal keys.
        dup = [{"key": "a", "name": "Sato Ken", "first": "Ken",
                "email": "1@s.jp"},
               {"key": "b", "name": "Sato Ken", "first": "Ken",
                "email": "1@s.jp"}]
        self.assertEqual([e["key"] for e in app.sort_roster(dup, "email")],
                         ["a", "b"])


class SurnamePeelingTests(unittest.TestCase):
    def test_multi_token_surname(self):
        # "Van Der Berg Anna": given name Anna peels off the end, leaving the
        # three-token surname intact.
        last, given = app._split_surname_given(
            {"name": "Van Der Berg Anna", "first": "Anna"})
        self.assertEqual((last, given), ("Van Der Berg", "Anna"))

    def test_missing_first_falls_back_to_trailing_token(self):
        last, given = app._split_surname_given({"name": "Tanaka Yuki"})
        self.assertEqual((last, given), ("Tanaka", "Yuki"))

    def test_single_token_name(self):
        last, given = app._split_surname_given({"name": "Madonna"})
        self.assertEqual((last, given), ("Madonna", "Madonna"))

    def test_key_only_entry(self):
        # No display name at all: fall back to the match key, never crash.
        last, given = app._split_surname_given({"key": "700900"})
        self.assertEqual((last, given), ("700900", "700900"))

    def test_email_mode_key_fallback(self):
        # Legacy safety: an entry with no email sorts on its key.
        entries = [{"key": "b", "name": "B"}, {"key": "a", "name": "A"}]
        self.assertEqual([e["key"] for e in app.sort_roster(entries, "email")],
                         ["a", "b"])


class ClassroomEntryOrderInvariantTests(unittest.TestCase):
    """The Classroom Entry tab must keep its own Latin (first-name) order no
    matter what ``roster_order`` the class uses upstream."""

    def setUp(self):
        from openpyxl import Workbook
        self.Workbook = Workbook
        self._orig_st = app.st
        self._orig_gb = app.gb
        self._orig_names = app._classroom_folder_assignment_names
        self._orig_scores = app.all_scores
        # first_name_for() reads the live roster from session_state.
        self.ss = {"roster": list(ROSTER)}
        app.st = SimpleNamespace(session_state=self.ss)
        students = [SimpleNamespace(student_id=e["key"], name=e["name"])
                    for e in ROSTER]
        self.students = students
        app.gb = lambda: SimpleNamespace(
            students={s.student_id: s for s in students})
        app._classroom_folder_assignment_names = lambda: []
        app.all_scores = lambda: []

    def tearDown(self):
        app.st = self._orig_st
        app.gb = self._orig_gb
        app._classroom_folder_assignment_names = self._orig_names
        app.all_scores = self._orig_scores

    def _entry_tab_names(self, students_in):
        wb = self.Workbook()
        app._append_classroom_entry_sheet(wb, students_in)
        ws = wb["Classroom Entry"]
        # Data rows start at row 3, column A holds the display name.
        return [ws.cell(row=r, column=1).value
                for r in range(3, 3 + len(students_in))]

    def _students_in_mode(self, mode):
        by_id = {s.student_id: s for s in self.students}
        return [by_id[e["key"]] for e in app.sort_roster(ROSTER, mode)]

    def test_order_independent_of_input_order(self):
        # Feed the students pre-sorted two different ways (as different
        # roster_order modes would): the tab order must be identical.
        a = self._entry_tab_names(self._students_in_mode("gojuon"))
        b = self._entry_tab_names(self._students_in_mode("email"))
        self.assertEqual(a, b)

    def test_order_is_latin_first_name(self):
        got = self._entry_tab_names(list(self.students))
        # first-name A–Z: Akira, Bob, Chiaki, Daichi, Emi.
        self.assertEqual(
            got, ["Chiba Akira", "Iida Bob", "Baba Chiaki",
                  "Aoki Daichi", "Shimizu Emi"])


if __name__ == "__main__":
    unittest.main()
