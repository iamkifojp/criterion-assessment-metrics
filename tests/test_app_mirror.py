"""App-level tests for the teacher-input cloud mirror (Phase 2).

Covers docs/COMMENT_CLOUD_MIRROR_PLAN.md Phase 2: building a per-class slice
from live session state, and the three write gates enforced by
``_mirror_classes_to_cloud`` — heal-before-mirror (invariant 1), the shrink
tripwire (invariant 2) and the no-churn fingerprint (invariant 3).

Streamlit is never actually run: ``app.st`` is swapped for a stand-in whose
``session_state`` is a plain dict, ``app.gb`` for a fixture gradebook, and
``app.class_data_dir`` for a temp folder per class. Run:

    python -m unittest tests.test_app_mirror
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
    term_summary_path,
)

CLASS = "Year 7 1-4"
OTHER = "Year 8 2-1"


def _make_gradebook():
    """A gradebook with two classes' assignments and score comments."""
    gb = Gradebook()
    gb.assignments = [
        Assignment(name="Still Life", criteria=["A", "B"], class_name=CLASS,
                   term="Term 1"),
        Assignment(name="Portrait", criteria=["A"], class_name=OTHER,
                   term="Term 1"),
    ]
    # alice (CLASS): a score comment on Still Life / Crit A.
    alice = gb.get_or_create("alice", "Ada")
    alice.add_score(CriterionScore(
        criterion="A", value=6, timestamp=datetime(2026, 5, 1),
        assignment="Still Life", comment="Careful observation."))
    alice.add_score(CriterionScore(
        criterion="B", value=5, timestamp=datetime(2026, 5, 1),
        assignment="Still Life", comment=""))   # blank -> dropped
    # zoe (OTHER): a score comment on an OTHER-class assignment.
    zoe = gb.get_or_create("zoe", "Zoe")
    zoe.add_score(CriterionScore(
        criterion="A", value=7, timestamp=datetime(2026, 5, 1),
        assignment="Portrait", comment="Bold work."))
    return gb


class MirrorTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.gb = _make_gradebook()
        self.ss = {
            "classes": [{"name": CLASS}, {"name": OTHER}],
            "rosters": {
                CLASS: [{"key": "alice"}, {"key": "bob"}],
                OTHER: [{"key": "zoe"}],
            },
            "archived_students": {},
            "comments_by_term": {
                "Term 1": {"alice": "Strong term.", "bob": "Improving.",
                           "zoe": "Not this class."},
            },
            "teacher_remarks": {"alice": "Chatty.", "zoe": "Other class."},
            "effort_by_term": {"Term 1": {"alice": 4, "zoe": 3}},
            "final_override": {"alice": {"A": 7}, "zoe": {"A": 5}},
            "mirror_ready": True,
            "mirror_fingerprints": {},
            "mirror_deletions_this_session": False,
            "db_load_blocked": None,
            "save_status": ("", ""),
        }
        # Swap the Streamlit + data-folder seams for test doubles.
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


class BuildSliceTests(MirrorTestBase):
    def test_slice_filters_to_class_roster(self):
        mirror = app.build_class_mirror(CLASS)
        # alice + bob belong to CLASS; zoe (OTHER) must never appear.
        self.assertEqual(mirror["terms"]["Term 1"],
                         {"alice": "Strong term.", "bob": "Improving."})
        self.assertEqual(mirror["remarks"], {"alice": "Chatty."})
        self.assertEqual(mirror["effort"]["Term 1"], {"alice": 4})
        self.assertEqual(mirror["final_override"], {"alice": {"A": 7}})

    def test_score_comments_scoped_by_class_and_nonblank(self):
        mirror = app.build_class_mirror(CLASS)
        # Only alice's non-blank Still Life / A comment; the blank B is dropped,
        # and zoe's Portrait comment belongs to OTHER.
        self.assertEqual(mirror["score_comments"],
                         {"Still Life": {"alice": {"A": "Careful observation."}}})

    def test_archived_student_still_mirrored(self):
        # bob departs the roster but keeps his comment -> still captured.
        self.ss["rosters"][CLASS] = [{"key": "alice"}]
        self.ss["archived_students"][CLASS] = [{"key": "bob"}]
        mirror = app.build_class_mirror(CLASS)
        self.assertIn("bob", mirror["terms"]["Term 1"])


class WriteGateTests(MirrorTestBase):
    def test_backfill_writes_every_class_on_first_persist(self):
        app._mirror_classes_to_cloud()
        cls_mirror = load_class_mirror(self._class_dir(CLASS), CLASS)
        other_mirror = load_class_mirror(self._class_dir(OTHER), OTHER)
        self.assertEqual(cls_mirror["terms"]["Term 1"],
                         {"alice": "Strong term.", "bob": "Improving."})
        self.assertEqual(other_mirror["terms"]["Term 1"], {"zoe": "Not this class."})
        # Fingerprints now seeded for both classes.
        self.assertEqual(set(self.ss["mirror_fingerprints"]), {CLASS, OTHER})

    def test_no_churn_second_pass_leaves_file_untouched(self):
        app._mirror_classes_to_cloud()
        path = term_summary_path(self._class_dir(CLASS), CLASS)
        before = os.stat(path).st_mtime_ns
        # Re-run many times with unchanged session state -> no rewrite.
        for _ in range(5):
            app._mirror_classes_to_cloud()
        self.assertEqual(os.stat(path).st_mtime_ns, before)

    def test_not_ready_writes_nothing(self):
        self.ss["mirror_ready"] = False
        app._mirror_classes_to_cloud()
        self.assertFalse(os.path.exists(
            term_summary_path(self._class_dir(CLASS), CLASS)))

    def test_quarantined_boot_writes_nothing(self):
        self.ss["db_load_blocked"] = {"reason": "unreadable"}
        app._mirror_classes_to_cloud()
        self.assertFalse(os.path.exists(
            term_summary_path(self._class_dir(CLASS), CLASS)))

    def test_shrink_tripwire_blocks_mass_loss(self):
        # Seed a rich file (6 Term-1 comments) then present a near-empty session.
        rich = {"terms": {"Term 1": {f"s{i}": "c" for i in range(6)}}}
        app.save_class_mirror(self._class_dir(CLASS, create=True), CLASS, rich)
        self.ss["rosters"][CLASS] = [{"key": "s0"}]   # only 1 survives
        self.ss["comments_by_term"] = {"Term 1": {"s0": "kept"}}
        self.ss["mirror_fingerprints"] = {}
        app._mirror_classes_to_cloud()
        # File untouched (still 6), and an error surfaced.
        on_disk = load_class_mirror(self._class_dir(CLASS), CLASS)
        self.assertEqual(len(on_disk["terms"]["Term 1"]), 6)
        self.assertEqual(self.ss["save_status"][0], "error")

    def test_deletion_flag_lets_mass_loss_through(self):
        rich = {"terms": {"Term 1": {f"s{i}": "c" for i in range(6)}}}
        app.save_class_mirror(self._class_dir(CLASS, create=True), CLASS, rich)
        self.ss["rosters"][CLASS] = [{"key": "s0"}]
        self.ss["comments_by_term"] = {"Term 1": {"s0": "kept"}}
        self.ss["mirror_fingerprints"] = {}
        self.ss["mirror_deletions_this_session"] = True   # deliberate deletion
        app._mirror_classes_to_cloud()
        on_disk = load_class_mirror(self._class_dir(CLASS), CLASS)
        self.assertEqual(on_disk["terms"]["Term 1"], {"s0": "kept"})

    def test_mirror_failure_never_raises(self):
        # A class whose folder can't be created must not take the pass down.
        app.class_data_dir = lambda cls, create=False: (_ for _ in ()).throw(
            OSError("boom"))
        try:
            app._mirror_classes_to_cloud()   # must swallow the error
        except Exception as exc:   # pragma: no cover
            self.fail(f"mirror raised: {exc}")


if __name__ == "__main__":
    unittest.main()
