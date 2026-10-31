"""Quick comments: the per-exam list and rebuilding a comment's generated line.

Run:  python -m unittest tests.test_keywords
"""

import unittest

from engine import keywords, model
from engine.errors import UserError


def exam():
    config = {"mode": "marks", "students": [{"id": "s1"}],
              "questions": [{"id": "q1", "label": "Q1", "max": 5}], "choice_groups": []}
    return config, model.new_grades("x")


class ListTests(unittest.TestCase):
    def test_default_list_follows_the_language(self):
        config, _ = exam()
        en = keywords.keyword_list(config, "en")
        self.assertEqual(len(en), keywords.DEFAULT_COUNT)
        self.assertEqual(en[4], {"label": "check calculations", "type": "growth"})
        self.assertEqual(keywords.keyword_list(config, "ja")[4]["label"], "計算を見直そう")

    def test_set_list_cleans_up(self):
        config, _ = exam()
        keywords.set_list(config, [{"label": "  clear   working ", "type": "strength"},
                                   {"label": "Clear working"}, {"label": ""}, "junk",
                                   {"label": "units missing", "type": "other"}])
        self.assertEqual(config["keywords"], [{"label": "clear working", "type": "strength"},
                                              {"label": "units missing", "type": "growth"}])
        keywords.set_list(config, [])
        self.assertEqual(keywords.keyword_list(config, "en"), [])     # an emptied list stays empty


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.config, self.grades = exam()
        keywords.set_list(self.config, [{"label": "clear working", "type": "strength"},
                                        {"label": "units missing", "type": "growth"},
                                        {"label": "check calculations", "type": "growth"}])

    def entry(self):
        return self.grades["grades"]["s1"]["q1"]

    def test_ticking_rebuilds_the_line_and_keeps_typed_text(self):
        keywords.apply(self.config, self.grades, "s1", "q1", ["units missing", "clear working"], "en")
        self.assertEqual(self.entry()["comment"], "Strengths: clear working. Areas to develop: units missing.")
        self.entry()["comment"] += "\nGood diagram."                     # typed by the teacher
        keywords.apply(self.config, self.grades, "s1", "q1",
                       ["clear working", "units missing", "check calculations"], "en")
        self.assertEqual(self.entry()["comment"],
                         "Strengths: clear working. Areas to develop: units missing, check calculations.\n"
                         "Good diagram.")
        self.assertEqual(self.entry()["keywords"], ["clear working", "units missing", "check calculations"])
        keywords.apply(self.config, self.grades, "s1", "q1", [], "en")
        self.assertEqual(self.entry()["comment"], "Good diagram.")
        self.assertIsNone(self.entry()["value"])                         # the grade is untouched

    def test_language_change_still_replaces_the_line(self):
        keywords.apply(self.config, self.grades, "s1", "q1", ["units missing"], "en")
        keywords.apply(self.config, self.grades, "s1", "q1", ["units missing"], "ja")
        self.assertEqual(self.entry()["comment"], "改善点：units missing。")

    def test_edited_line_is_kept_as_typed_text(self):
        keywords.apply(self.config, self.grades, "s1", "q1", ["units missing"], "en")
        self.entry()["comment"] = "Mostly fine."
        keywords.apply(self.config, self.grades, "s1", "q1", ["clear working"], "en")
        self.assertEqual(self.entry()["comment"], "Strengths: clear working.\nMostly fine.")

    def test_unknown_keyword_or_ids(self):
        with self.assertRaises(UserError) as ctx:
            keywords.apply(self.config, self.grades, "s1", "q1", ["nope"], "en")
        self.assertEqual(ctx.exception.code, "unknown_keyword")
        with self.assertRaises(UserError):
            keywords.apply(self.config, self.grades, "s9", "q1", [], "en")


if __name__ == "__main__":
    unittest.main()
