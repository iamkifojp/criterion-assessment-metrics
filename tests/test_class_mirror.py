"""Unit tests for the per-class teacher-input cloud mirror (v2).

Framework-free (stdlib ``unittest``) so they run without the app's Streamlit
stack:

    python -m unittest tests.test_class_mirror

Covers Phase 1 of docs/COMMENT_CLOUD_MIRROR_PLAN.md: v2 round-trip, v1-file
backward-compat load, malformed/absent file degradation, blank-dropping, and
atomic replace.
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from engine.persistence import (
    load_class_mirror,
    save_class_mirror,
    load_term_summaries,
    save_term_summary,
    term_summary_path,
)

CLASS = "Year 7 1-4 (2026-27)"


def _full_mirror():
    return {
        "terms": {
            "Term 1": {"alice": "Strong term.", "bob": "Improving."},
            "Term 2": {"alice": "Excellent."},
        },
        "remarks": {"alice": "Keep it up.", "bob": "See me."},
        "effort": {"Term 1": {"alice": 4, "bob": 3}},
        "final_override": {"alice": {"A": 7, "B": 6}},
        "score_comments": {
            "Still Life": {"alice": {"A": "Great composition."}},
        },
    }


class ClassMirrorRoundTripTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_absent_file_returns_empty_shape(self):
        mirror = load_class_mirror(self.folder, CLASS)
        self.assertEqual(
            mirror,
            {"terms": {}, "remarks": {}, "effort": {},
             "final_override": {}, "score_comments": {}},
        )
        # load_term_summaries view is also empty, never None.
        self.assertEqual(load_term_summaries(self.folder, CLASS), {})

    def test_v2_round_trip(self):
        original = _full_mirror()
        path = save_class_mirror(self.folder, CLASS, original)
        self.assertTrue(os.path.exists(path))

        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded, original)

        # File carries the v2 metadata.
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        self.assertEqual(raw["version"], 2)
        self.assertEqual(raw["class_name"], CLASS)
        self.assertIn("updated_at", raw)

    def test_effort_and_override_are_ints_after_round_trip(self):
        save_class_mirror(self.folder, CLASS, _full_mirror())
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertIsInstance(loaded["effort"]["Term 1"]["alice"], int)
        self.assertIsInstance(loaded["final_override"]["alice"]["A"], int)

    def test_partial_mirror_fills_missing_sections(self):
        path = save_class_mirror(self.folder, CLASS,
                                 {"remarks": {"alice": "Only remarks."}})
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for section in ("terms", "remarks", "effort",
                        "final_override", "score_comments"):
            self.assertIn(section, raw)
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["remarks"], {"alice": "Only remarks."})
        self.assertEqual(loaded["terms"], {})


class BackwardCompatTests(unittest.TestCase):
    """A v1 file (only ``terms``) must still load through the v2 path."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def _write_raw(self, payload):
        path = term_summary_path(self.folder, CLASS)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        return path

    def test_v1_file_loads_terms_and_empty_new_sections(self):
        self._write_raw({
            "class_name": CLASS,
            "updated_at": "2026-07-01T00:00:00",
            "terms": {"Term 1": {"alice": "v1 comment"}},
        })
        mirror = load_class_mirror(self.folder, CLASS)
        self.assertEqual(mirror["terms"], {"Term 1": {"alice": "v1 comment"}})
        self.assertEqual(mirror["remarks"], {})
        self.assertEqual(mirror["effort"], {})
        self.assertEqual(mirror["final_override"], {})
        self.assertEqual(mirror["score_comments"], {})
        # v1-shaped view still works.
        self.assertEqual(load_term_summaries(self.folder, CLASS),
                         {"Term 1": {"alice": "v1 comment"}})

    def test_save_term_summary_preserves_other_sections(self):
        # Start with a full v2 mirror, then use the legacy writer to replace
        # one term. All other sections must survive.
        save_class_mirror(self.folder, CLASS, _full_mirror())
        save_term_summary(self.folder, CLASS, "Term 1",
                          {"alice": "Rewritten.", "carol": "New."})
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["terms"]["Term 1"],
                         {"alice": "Rewritten.", "carol": "New."})
        # Term 2 untouched, other sections intact.
        self.assertEqual(loaded["terms"]["Term 2"], {"alice": "Excellent."})
        self.assertEqual(loaded["remarks"], {"alice": "Keep it up.",
                                             "bob": "See me."})
        self.assertEqual(loaded["final_override"], {"alice": {"A": 7, "B": 6}})

    def test_malformed_file_degrades_to_empty(self):
        path = term_summary_path(self.folder, CLASS)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{ this is not valid json ")
        self.assertEqual(
            load_class_mirror(self.folder, CLASS),
            {"terms": {}, "remarks": {}, "effort": {},
             "final_override": {}, "score_comments": {}},
        )
        self.assertEqual(load_term_summaries(self.folder, CLASS), {})

    def test_non_dict_json_degrades_to_empty(self):
        path = term_summary_path(self.folder, CLASS)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(["not", "a", "dict"], fh)
        self.assertEqual(load_term_summaries(self.folder, CLASS), {})


class BlankDroppingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_blank_leaves_and_empty_containers_dropped(self):
        save_class_mirror(self.folder, CLASS, {
            "terms": {
                "Term 1": {"alice": "keep", "bob": "   ", "carol": ""},
                "Term 2": {"dave": "  \n "},  # whole term becomes empty
            },
            "remarks": {"alice": "keep", "bob": None, "carol": ""},
            "effort": {"Term 1": {"alice": 3, "bob": None}},
            "final_override": {"alice": {"A": 7, "B": None}},
            "score_comments": {
                "A1": {"alice": {"A": "keep", "B": " "}},
                "A2": {"bob": {"A": ""}},  # whole assignment empty
            },
        })
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["terms"], {"Term 1": {"alice": "keep"}})
        self.assertEqual(loaded["remarks"], {"alice": "keep"})
        self.assertEqual(loaded["effort"], {"Term 1": {"alice": 3}})
        self.assertEqual(loaded["final_override"], {"alice": {"A": 7}})
        self.assertEqual(loaded["score_comments"],
                         {"A1": {"alice": {"A": "keep"}}})

    def test_bool_is_not_a_valid_int(self):
        save_class_mirror(self.folder, CLASS,
                          {"effort": {"Term 1": {"alice": True}}})
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["effort"], {})

    def test_numeric_string_effort_coerced(self):
        save_class_mirror(self.folder, CLASS,
                          {"effort": {"Term 1": {"alice": "4"}}})
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["effort"], {"Term 1": {"alice": 4}})

    def test_save_term_summary_drops_blanks(self):
        save_term_summary(self.folder, CLASS, "Term 1",
                          {"alice": "keep", "bob": "  "})
        self.assertEqual(load_term_summaries(self.folder, CLASS),
                         {"Term 1": {"alice": "keep"}})


class AtomicReplaceTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.folder = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_no_tmp_files_left_behind(self):
        save_class_mirror(self.folder, CLASS, _full_mirror())
        save_class_mirror(self.folder, CLASS, {"remarks": {"x": "y"}})
        leftovers = [f for f in os.listdir(self.folder) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_second_write_replaces_wholesale(self):
        save_class_mirror(self.folder, CLASS, _full_mirror())
        save_class_mirror(self.folder, CLASS, {"remarks": {"x": "y"}})
        loaded = load_class_mirror(self.folder, CLASS)
        self.assertEqual(loaded["remarks"], {"x": "y"})
        self.assertEqual(loaded["terms"], {})  # gone — wholesale replace
        self.assertEqual(loaded["final_override"], {})

    def test_existing_file_intact_if_write_body_fails(self):
        # A failure mid-write must leave the good file in place and drop no tmp
        # turd (os.replace only swaps in a fully-written tmp file). Cleaning
        # coerces every leaf to str/int so json.dump can't fail on its own —
        # force the failure to prove the tmp+replace ordering is sound.
        save_class_mirror(self.folder, CLASS, _full_mirror())
        path = term_summary_path(self.folder, CLASS)
        with open(path, "r", encoding="utf-8") as fh:
            before = fh.read()

        with mock.patch("engine.persistence.json.dump",
                        side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                save_class_mirror(self.folder, CLASS, {"remarks": {"x": "y"}})

        with open(path, "r", encoding="utf-8") as fh:
            after = fh.read()
        self.assertEqual(before, after)
        leftovers = [f for f in os.listdir(self.folder) if f.endswith(".tmp")]
        self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
