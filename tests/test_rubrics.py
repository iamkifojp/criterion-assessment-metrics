"""Teacher-made rubrics, Excel/CSV import and the blank template.

Run:  python -m unittest tests.test_rubrics
"""

import unittest

from engine import rubrics, tables
from engine.errors import UserError


class LevelTests(unittest.TestCase):
    def test_level_forms(self):
        self.assertEqual(rubrics.parse_levels("3"), (3, 3))
        for text in ("5-6", "5–6", "5 ~ 6", "5〜6", "５－６", "５～６", "5ー6"):
            self.assertEqual(rubrics.parse_levels(text), (5, 6), text)

    def test_bad_levels(self):
        for text in ("", "a", "6-5", "1-2-3", "101"):
            with self.assertRaises(UserError, msg=text):
                rubrics.parse_levels(text)

    def test_new_rubric_starts_with_myp_rows(self):
        rubric = rubrics.normalize_rubric(rubrics.new_rubric("r1", "Criterion A"))
        self.assertEqual([b["levels"] for b in rubric["bands"]],
                         ["0", "1–2", "3–4", "5–6", "7–8"])
        self.assertEqual(rubrics.rubric_max(rubric), 8)

    def test_teachers_may_use_their_own_bands(self):
        rubric = rubrics.normalize_rubric({"id": "r1", "name": "Simple", "bands": [
            {"levels": "1", "descriptor": "a"}, {"levels": "2", "descriptor": "b"},
            {"levels": "3", "descriptor": "c"}, {"levels": "4", "descriptor": "d"},
            {"levels": "", "descriptor": ""}]})
        self.assertEqual(len(rubric["bands"]), 4)
        self.assertEqual(rubrics.rubric_max(rubric), 4)
        self.assertEqual(rubrics.check_level(rubric, 2), 2)
        with self.assertRaises(UserError):
            rubrics.check_level(rubric, 0)

    def test_overlap_and_empty_are_rejected(self):
        with self.assertRaises(UserError) as ctx:
            rubrics.normalize_rubric({"name": "X", "bands": [
                {"levels": "1-3"}, {"levels": "3-4"}]})
        self.assertEqual(ctx.exception.code, "rubric_levels_overlap")
        with self.assertRaises(UserError) as ctx:
            rubrics.normalize_rubric({"name": "X", "bands": []})
        self.assertEqual(ctx.exception.code, "rubric_no_bands")

    def test_band_for_level(self):
        rubric = rubrics.normalize_rubric(rubrics.new_rubric("r1", "A"))
        self.assertEqual(rubrics.band_for_level(rubric, 6)["levels"], "5–6")
        self.assertIsNone(rubrics.band_for_level(rubric, 9))


class ImportTests(unittest.TestCase):
    def test_english_header(self):
        rows = [["Criterion", "Grade / Band", "Level descriptor"],
                ["Criterion A", "0", "nothing"], ["", "1-2", "some"],
                ["Criterion B", "0", "none"], ["Criterion B", "1-8", "all"]]
        result = rubrics.import_rubrics(rows)
        self.assertEqual([r["name"] for r in result], ["Criterion A", "Criterion B"])
        self.assertEqual([r["id"] for r in result], ["r1", "r2"])
        self.assertEqual(result[0]["bands"][1]["levels"], "1–2")
        self.assertEqual(result[1]["bands"][1]["descriptor"], "all")

    def test_japanese_header_in_other_column_order(self):
        rows = [["記述", "レベル", "基準"], ["説明", "７－８", "基準A"]]
        result = rubrics.import_rubrics(rows)
        self.assertEqual(result[0]["name"], "基準A")
        self.assertEqual(result[0]["bands"][0]["levels"], "7–8")

    def test_no_header(self):
        self.assertEqual(rubrics.import_rubrics([["1-2", "x"], ["3-4", "y"]])[0]["name"],
                         "Rubric 1")
        with self.assertRaises(UserError):
            rubrics.import_rubrics([["only one column"]])

    def test_template_round_trip(self):
        for language in ("en", "ja"):
            rows = tables.read_table("t.xlsx", rubrics.template_xlsx(language))
            self.assertEqual(rows[0], list(rubrics.TEMPLATE_HEADERS[language]))
            # Descriptors are blank, so give them text as a teacher would.
            filled = [rows[0]] + [r[:2] + ["text"] for r in rows[1:]]
            result = rubrics.import_rubrics(filled)
            self.assertEqual(len(result), 1)
            self.assertEqual(len(result[0]["bands"]), 5)

    def test_csv_in_shift_jis(self):
        raw = "基準,レベル,記述\n基準A,1-2,説明です\n".encode("cp932")
        result = rubrics.import_rubrics(tables.read_table("r.csv", raw))
        self.assertEqual(result[0]["bands"][0]["descriptor"], "説明です")


if __name__ == "__main__":
    unittest.main()
