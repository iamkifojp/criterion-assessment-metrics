"""Class-list import and matching scan file names to students.

Run:  python -m unittest tests.test_roster
"""

import io
import unicodedata
import unittest

from openpyxl import Workbook

from engine import roster, tables
from engine.errors import UserError


def xlsx_bytes(rows):
    wb = Workbook()
    for row in rows:
        wb.active.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class TableReadingTests(unittest.TestCase):
    def test_csv_encodings(self):
        utf8 = "氏名\n山田 太郎\n".encode("utf-8-sig")
        sjis = "氏名\n山田 太郎\n".encode("cp932")
        self.assertEqual(tables.read_table("a.csv", utf8), [["氏名"], ["山田 太郎"]])
        self.assertEqual(tables.read_table("a.csv", sjis), [["氏名"], ["山田 太郎"]])

    def test_xlsx_drops_empty_rows_and_columns(self):
        raw = xlsx_bytes([["No", None, "Name"], [None, None, None], [1, None, "Tanaka Hana"]])
        self.assertEqual(tables.read_table("c.xlsx", raw),
                         [["No", "Name"], ["1", "Tanaka Hana"]])

    def test_unsupported_files(self):
        with self.assertRaises(UserError) as ctx:
            tables.read_table("old.xls", b"")
        self.assertEqual(ctx.exception.code, "xls_not_supported")
        with self.assertRaises(UserError):
            tables.read_table("photo.png", b"")
        with self.assertRaises(UserError):
            tables.read_table("broken.xlsx", b"not a zip")


class ColumnGuessTests(unittest.TestCase):
    def test_single_name_column(self):
        rows = [["出席番号", "氏名", "メール"], ["1", "山田 太郎", "a@b.jp"]]
        self.assertTrue(roster.guess_header(rows))
        self.assertEqual(roster.guess_name_columns(rows, True), [1])

    def test_family_and_given_columns(self):
        rows = [["ID", "Last Name", "First Name"], ["7", "Tanaka", "Hana"]]
        self.assertEqual(roster.guess_name_columns(rows, True), [1, 2])
        names = roster.extract_names(rows, [1, 2], True)
        self.assertEqual(names, [{"id": "n001", "name": "Tanaka Hana"}])

    def test_japanese_split_columns(self):
        rows = [["姓", "名"], ["山田", "太郎"]]
        self.assertEqual(roster.guess_name_columns(rows, True), [0, 1])

    def test_headerless_list(self):
        rows = [["1", "Tanaka, Hana"], ["2", "Sato, Ken"]]
        self.assertFalse(roster.guess_header(rows))
        self.assertEqual(roster.guess_name_columns(rows, False), [1])
        self.assertEqual([n["name"] for n in roster.extract_names(rows, [1], False)],
                         ["Tanaka, Hana", "Sato, Ken"])

    def test_preview_and_errors(self):
        rows = [[str(i)] for i in range(10)]
        self.assertEqual(len(roster.preview(rows)), roster.PREVIEW_ROWS)
        with self.assertRaises(UserError):
            roster.extract_names(rows, [], False)
        with self.assertRaises(UserError):
            roster.extract_names([["Name"]], [0], True)

    def test_pasted_names(self):
        names = roster.parse_pasted("Tanaka Hana\n\n山田　太郎\nSato\tKen\n")
        self.assertEqual([n["name"] for n in names], ["Tanaka Hana", "山田 太郎", "Sato Ken"])


class MatchingTests(unittest.TestCase):
    roster_list = [{"id": "n001", "name": "Tanaka Hana"},
                   {"id": "n002", "name": "Sato Ken"},
                   {"id": "n003", "name": "山田 太郎"},
                   {"id": "n004", "name": "Ito Mei"}]

    def test_file_names_in_any_form(self):
        students = [{"id": "s001", "source": "hana_tanaka.pdf"},
                    {"id": "s002", "source": "SATO KEN (7B).pdf"},
                    {"id": "s003", "source": unicodedata.normalize("NFD", "山田太郎.pdf")},
                    {"id": "s004", "source": "Student_004.pdf"}]
        self.assertEqual(roster.auto_match(students, self.roster_list),
                         {"s001": "n001", "s002": "n002", "s003": "n003"})

    def test_ambiguous_matches_are_left_for_the_teacher(self):
        students = [{"id": "s001", "source": "Ito Mei.pdf"},
                    {"id": "s002", "source": "Ito Mei copy.pdf"},
                    {"id": "s003", "source": "Tanaka Hana and Sato Ken.pdf"}]
        self.assertEqual(roster.auto_match(students, self.roster_list), {})


if __name__ == "__main__":
    unittest.main()
