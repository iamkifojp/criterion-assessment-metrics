"""App-level tests for the teacher-input cloud mirror — Phase 3 (heal on load).

Covers docs/COMMENT_CLOUD_MIRROR_PLAN.md Phase 3: refilling a wiped session
from the per-class cloud twins written by Phase 2, without ever clobbering a
value the session still holds, plus the fingerprint seeding that lets a pure
heal avoid churn while an unhealed backfill still writes.

Same seams as tests/test_app_mirror.py: ``app.st`` is a stand-in whose
``session_state`` is a plain dict, ``app.gb`` a fixture gradebook, and
``app.class_data_dir`` a temp folder per class. Streamlit never runs. Run:

    python -m unittest tests.test_app_heal
"""

import os
import sys
import tempfile
import unittest
from datetime import datetime
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app  # noqa: E402  (path shim must precede the import)
from engine import (  # noqa: E402
    Gradebook,
    CriterionScore,
    Assignment,
    load_class_mirror,
    save_class_mirror,
    term_summary_path,
)

CLASS = "Year 7 1-4"
OTHER = "Year 8 2-1"


def _make_gradebook():
    """Two classes' assignments; alice (CLASS) carries a score whose comment
    was dropped (blank) as if a Sync purge-replace had just rebuilt it."""
    gb = Gradebook()
    gb.assignments = [
        Assignment(name="Still Life", criteria=["A", "B"], class_name=CLASS,
                   term="Term 1"),
        Assignment(name="Portrait", criteria=["A"], class_name=OTHER,
                   term="Term 1"),
    ]
    alice = gb.get_or_create("alice", "Ada")
    alice.add_score(CriterionScore(
        criterion="A", value=6, timestamp=datetime(2026, 5, 1),
        assignment="Still Life", comment=""))       # blank -> heal target
    alice.add_score(CriterionScore(
        criterion="B", value=5, timestamp=datetime(2026, 5, 1),
        assignment="Still Life", comment="CSV kept this."))  # non-blank -> wins
    return gb


class HealTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.gb = _make_gradebook()
        # A "wiped" session: classes/rosters survive (as after the incident),
        # but every teacher-input map is empty.
        self.ss = {
            "classes": [{"name": CLASS}, {"name": OTHER}],
            "rosters": {
                CLASS: [{"key": "alice"}, {"key": "bob"}],
                OTHER: [{"key": "zoe"}],
            },
            "archived_students": {},
            "comments_by_term": {},
            "teacher_remarks": {},
            "effort_by_term": {},
            "final_override": {},
            "mirror_ready": True,
            "mirror_fingerprints": {},
            "mirror_deletions_this_session": False,
            "db_load_blocked": None,
            "save_status": ("", ""),
        }
        self._orig_st = app.st
        self._orig_gb = app.gb
        self._orig_cdd = app.class_data_dir
        app.st = SimpleNamespace(session_state=self.ss)
        app.gb = lambda: self.gb
        app.class_data_dir = self._class_dir

    def tearDown(self):
        app.st = self._orig_st
        app.gb = self._orig_gb
        app.class_data_dir = self._orig_cdd

    def _class_dir(self, class_name, create=False):
        d = os.path.join(self.tmp, app._safe_dirname(class_name))
        if create:
            os.makedirs(d, exist_ok=True)
        return d

    def _write_twin(self, cls, mirror):
        save_class_mirror(self._class_dir(cls, create=True), cls, mirror)


class HealFromMirrorsTests(HealTestBase):
    def test_wiped_maps_refilled_from_twin(self):
        # A rich twin for CLASS; a relaunch with empty maps must come back full.
        self._write_twin(CLASS, {
            "terms": {"Term 1": {"alice": "Strong term.", "bob": "Improving."}},
            "remarks": {"alice": "Chatty."},
            "effort": {"Term 1": {"alice": 4, "bob": 0}},
            "final_override": {"alice": {"A": 7}},
        })
        app._heal_from_class_mirrors()
        self.assertEqual(self.ss["comments_by_term"]["Term 1"],
                         {"alice": "Strong term.", "bob": "Improving."})
        self.assertEqual(self.ss["teacher_remarks"], {"alice": "Chatty."})
        # Effort 0 is a real score and must land (presence, not truthiness).
        self.assertEqual(self.ss["effort_by_term"]["Term 1"], {"alice": 4, "bob": 0})
        self.assertEqual(self.ss["final_override"], {"alice": {"A": 7}})

    def test_session_text_wins_over_twin(self):
        # The teacher has already typed a fresh comment this session -> keep it.
        self.ss["comments_by_term"] = {"Term 1": {"alice": "Live edit."}}
        self.ss["final_override"] = {"alice": {"A": 3}}
        self._write_twin(CLASS, {
            "terms": {"Term 1": {"alice": "Stale twin.", "bob": "From twin."}},
            "final_override": {"alice": {"A": 7, "B": 5}},
        })
        app._heal_from_class_mirrors()
        # alice's live comment survives; bob's blank slot is filled.
        self.assertEqual(self.ss["comments_by_term"]["Term 1"]["alice"], "Live edit.")
        self.assertEqual(self.ss["comments_by_term"]["Term 1"]["bob"], "From twin.")
        # alice's set criterion wins; only the missing criterion is healed.
        self.assertEqual(self.ss["final_override"]["alice"], {"A": 3, "B": 5})

    def test_deletion_not_resurrected(self):
        # The teacher cleared alice's comment in-app; the mirror-on-persist has
        # already dropped it from the twin, so the heal has nothing to restore.
        self.ss["comments_by_term"] = {"Term 1": {"alice": ""}}  # blank = cleared
        self._write_twin(CLASS, {"terms": {"Term 1": {"bob": "Only bob."}}})
        app._heal_from_class_mirrors()
        self.assertEqual(self.ss["comments_by_term"]["Term 1"].get("alice", ""), "")
        self.assertEqual(self.ss["comments_by_term"]["Term 1"]["bob"], "Only bob.")

    def test_no_twin_is_a_quiet_noop(self):
        # No class file on disk -> nothing to heal, no error.
        app._heal_from_class_mirrors()
        self.assertEqual(self.ss["comments_by_term"], {})
        self.assertEqual(self.ss["teacher_remarks"], {})

    def test_heal_never_raises(self):
        app.class_data_dir = lambda cls, create=False: (_ for _ in ()).throw(
            OSError("boom"))
        try:
            app._heal_from_class_mirrors()
        except Exception as exc:  # pragma: no cover
            self.fail(f"heal raised: {exc}")


class HealScoreCommentsTests(HealTestBase):
    def test_blank_score_comment_refilled(self):
        self._write_twin(CLASS, {
            "score_comments": {"Still Life": {"alice": {"A": "Careful obs."}}}})
        app._heal_score_comments_from_mirrors()
        a_scores = self.gb.students["alice"].scores["A"]
        self.assertEqual(a_scores[0].comment, "Careful obs.")

    def test_nonblank_score_comment_not_overwritten(self):
        # The CSV kept crit B's comment; the twin's stale text must not win.
        self._write_twin(CLASS, {
            "score_comments": {"Still Life": {"alice": {"B": "Stale twin."}}}})
        app._heal_score_comments_from_mirrors()
        b_scores = self.gb.students["alice"].scores["B"]
        self.assertEqual(b_scores[0].comment, "CSV kept this.")

    def test_score_comment_heal_never_raises(self):
        app.class_data_dir = lambda cls, create=False: (_ for _ in ()).throw(
            OSError("boom"))
        try:
            app._heal_score_comments_from_mirrors()
        except Exception as exc:  # pragma: no cover
            self.fail(f"score-comment heal raised: {exc}")


class SeedAndBackfillTests(HealTestBase):
    def test_matching_twin_seeded_no_rewrite_on_persist(self):
        # A twin byte-identical to the built session slice must be seeded, so the
        # first persist recognises it as unchanged and does NOT rewrite the file.
        self.ss["comments_by_term"] = {
            "Term 1": {"alice": "Strong term.", "bob": "Improving."}}
        # The twin is exactly what the session would mirror (terms + alice's
        # non-blank crit-B score comment from the fixture gradebook).
        self._write_twin(CLASS, app.build_class_mirror(CLASS))
        app._heal_from_class_mirrors()   # no-op: session already holds the text
        app._seed_mirror_fingerprints()
        self.assertIn(CLASS, self.ss["mirror_fingerprints"])
        path = term_summary_path(self._class_dir(CLASS), CLASS)
        before = os.stat(path).st_mtime_ns
        app._mirror_classes_to_cloud()
        self.assertEqual(os.stat(path).st_mtime_ns, before)  # no churn

    def test_missing_twin_unseeded_backfills_on_persist(self):
        # DB restored 2 comments but the class never had a twin (the incident's
        # root cause). Heal fills nothing (no file); seed leaves it unseeded;
        # the first persist backfills the twin.
        self.ss["comments_by_term"] = {"Term 1": {"alice": "A.", "bob": "B."}}
        app._heal_from_class_mirrors()
        app._seed_mirror_fingerprints()
        self.assertNotIn(CLASS, self.ss["mirror_fingerprints"])
        app._mirror_classes_to_cloud()
        on_disk = load_class_mirror(self._class_dir(CLASS), CLASS)
        self.assertEqual(on_disk["terms"]["Term 1"], {"alice": "A.", "bob": "B."})
        self.assertIn(CLASS, self.ss["mirror_fingerprints"])

    def test_session_richer_than_twin_rewrites_on_persist(self):
        # Twin has 1 comment; the session healed to 2 (a new student typed one
        # after the last mirror). Seed must NOT mark it clean -> persist writes.
        self._write_twin(CLASS, {"terms": {"Term 1": {"alice": "A."}}})
        self.ss["comments_by_term"] = {"Term 1": {"bob": "New one."}}
        app._heal_from_class_mirrors()   # -> alice healed in, bob kept
        app._seed_mirror_fingerprints()
        self.assertNotIn(CLASS, self.ss["mirror_fingerprints"])
        app._mirror_classes_to_cloud()
        on_disk = load_class_mirror(self._class_dir(CLASS), CLASS)
        self.assertEqual(on_disk["terms"]["Term 1"],
                         {"alice": "A.", "bob": "New one."})


if __name__ == "__main__":
    unittest.main()
