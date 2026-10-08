"""Filename matching and CAM handoff/export checks using fictional students.

Extract only the exercised app functions, avoiding UI imports, startup settings
discovery, OAuth, or any access to real preferences/data. All I/O is in temp dirs.
"""
import ast
import csv
import datetime
import glob
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest

from cam_grading_workspace.submission_identity import (
    match_submission, unmatched_identity, has_shortened_school_ids)
from engine.ingestion import parse_classroom_roster, resolve_identity, student_id_from_email

ROOT = Path(__file__).resolve().parents[1]
ROSTER = parse_classroom_roster(
    "Last Name,First Name,Email Address\n"
    "Rivera,Ada,10001@example.test\n"
    "Rivera,Ben,10002@example.test\n"
    "Van Der Berg,Zoë,10003@example.test\n")


def file(name, fid="file-1", **kwargs):
    return {"id": fid, "name": name, "mimeType": "application/pdf",
            "owners": [{"emailAddress": "teacher@example.test"}], **kwargs}


def functions_from(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef))
             and node.name in names]
    assert {n.name for n in nodes} == set(names)
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def workspace(tmp):
    ns = dict(os=os, re=re, io=io, csv=csv, json=json, glob=glob,
              hashlib=hashlib, datetime=datetime, STATE_LOCK=threading.Lock(),
              BASE_DIR=tmp, SETTINGS={"cloud_dir": tmp}, STATE={"class_name": "Art"},
              match_submission=match_submission, unmatched_identity=unmatched_identity,
              has_shortened_school_ids=has_shortened_school_ids,
              MYP_CRITERIA=["A", "B", "C", "D"], jsonify=lambda data: data,
              is_me=lambda person: False, classify=lambda *args: "pdf",
              normalized_base=lambda name: name.casefold(),
              embed_url_for=lambda *args: None, save_state=lambda: None,
              load_cache=lambda: {},
              send_file=lambda buf, **kwargs: buf.getvalue())
    return functions_from(ROOT / "cam_grading_workspace/app.py", [
        "student_id_from_email", "short_id", "student_key", "pick_student",
        "parse_time", "file_recency", "group_by_student", "class_output_dir",
        "_safe_dirname", "cam_published_path", "state_path", "load_matching_context",
        "find_client_secret", "api_export", "_anonymize_student", "LocalProvider",
        "api_load", "_extract_folder_id", "consume_cam_published",
        "load_assignment_options",
    ], ns)


class MatchTests(unittest.TestCase):
    def match_key(self, name, roster=ROSTER, **kwargs):
        entry, reason = match_submission(file(name, **kwargs), roster)
        return entry["key"] if entry else None, reason

    def test_full_name_in_both_orders_and_normalization(self):
        for name in ["Ada RIVERA - Art Unit 02.docx", "rivera_ada_final.pdf",
                     "Copy of ADA, RIVERA (1).pdf", "Ａｄａ Ｒｉｖｅｒａ.pdf"]:
            self.assertEqual(self.match_key(name), ("10001", "filename"))
        self.assertEqual(self.match_key("Zoe VAN DER BERG final.pdf"),
                         ("10003", "filename"))

    def test_id_and_email_with_boundaries(self):
        for name in ["10001_Ada_Art.pdf", "10001@example.test.pdf"]:
            self.assertEqual(self.match_key(name), ("10001", "filename"))
        for name in ["110001.pdf", "100010.pdf", "x10001.pdf"]:
            self.assertEqual(self.match_key(name), (None, "unmatched"))

    def test_partial_names_and_typos_do_not_assign(self):
        for name in ["Rivera.pdf", "Ada.pdf", "Adaa Rivera.pdf", "Adam Rivera.pdf"]:
            self.assertEqual(self.match_key(name), (None, "unmatched"))
        single = [{"key": "Ada", "name": "Ada", "first": "Ada"}]
        self.assertEqual(self.match_key("Ada art.pdf", single), (None, "unmatched"))

    def test_duplicates_and_multiple_names_need_review(self):
        duplicated = ROSTER + [{**ROSTER[0], "key": "10004", "email": "10004@example.test"}]
        self.assertEqual(self.match_key("Ada Rivera.pdf", duplicated), (None, "ambiguous"))
        self.assertEqual(self.match_key("10001_Ada_Rivera.pdf", duplicated), ("10001", "filename"))
        self.assertEqual(self.match_key("Ada Rivera and Ben Rivera.pdf"), (None, "ambiguous"))
        self.assertEqual(self.match_key("10001_Ada Rivera and Ben Rivera.pdf"), (None, "ambiguous"))

    def test_unknown_reuploaded_owner_does_not_block_filename(self):
        self.assertEqual(self.match_key("Ada Rivera.pdf"), ("10001", "filename"))

    def test_roster_metadata_and_conflicts(self):
        self.assertEqual(self.match_key("scan.pdf", owners=[{"emailAddress": "10001@example.test"}]),
                         ("10001", "metadata"))
        self.assertEqual(self.match_key("Ben Rivera.pdf", owners=[{"emailAddress": "10001@example.test"}]),
                         (None, "ambiguous"))
        self.assertEqual(self.match_key("scan.pdf", permissions=[
            {"emailAddress": "10001@example.test"}, {"emailAddress": "10002@example.test"}]),
                         (None, "ambiguous"))

    def test_student_subfolder_and_manual_alias(self):
        self.assertEqual(self.match_key("scan.pdf", local_student="Rivera Ada"),
                         ("10001", "filename"))
        f = file("scan.pdf")
        entry, reason = match_submission(f, ROSTER, {unmatched_identity(f): "10002"})
        self.assertEqual((entry["key"], reason), ("10002", "manual"))
        entry, reason = match_submission(f, ROSTER, {unmatched_identity(f): "not-on-roster"})
        self.assertEqual((entry, reason), (None, "unmatched"))

    def test_alphanumeric_school_ids_do_not_collapse_classmates(self):
        roster = parse_classroom_roster(
            "Last Name,First Name,Email Address\n"
            "Rivera,Ada,26b1001@example.test\n"
            "Rivera,Ben,26b1002@example.test\n"
            "Berg,Zoe,26c1001@example.test\n")
        self.assertEqual([e["key"] for e in roster], ["26b1001", "26b1002", "26c1001"])
        for e in roster:
            actual, reason = match_submission(file(e["key"] + "_art.pdf"), roster)
            self.assertEqual((actual["key"], reason), (e["key"], "filename"))
        self.assertEqual(student_id_from_email("s100001@example.test"), "100001")
        self.assertEqual(student_id_from_email("100001.jane@example.test"), "100001")
        self.assertFalse(has_shortened_school_ids(roster))
        self.assertTrue(has_shortened_school_ids([{**roster[0], "key": "26"}]))


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="cam_match_test_")
        self.ns = workspace(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reuploaded_files_group_by_roster_and_keep_existing_grades(self):
        saved = {"email:10001@example.test": {"grades": {"A": "7"}, "comment": "Good"}}
        students, ordered = self.ns["group_by_student"]([
            file("Ada Rivera art.pdf", "a"), file("Rivera Ada draft.pdf", "b"),
            file("Ben Rivera.pdf", "c"), file("scan.pdf", "d"), file("scan.pdf", "e"),
        ], saved, ROSTER)
        self.assertEqual(len(students), 4)
        ada = students["email:10001@example.test"]
        self.assertEqual((ada["name"], ada["count"], ada["roster_label"]),
                         ("10001", 2, "Rivera Ada"))
        self.assertEqual(ada["grades"], {"A": "7"})
        self.assertEqual(ada["comment"], "Good")
        unmatched = [s for s in ordered if s["name"].startswith("Unmatched ")]
        self.assertEqual(len(unmatched), 2)
        for s in unmatched:
            self.assertIsNone(resolve_identity(s["name"], {e["key"] for e in ROSTER})[0])

    def test_legacy_saved_teacher_marks_are_not_redistributed(self):
        saved = {"email:teacher@example.test": {"grades": {"A": "6"}, "graded": True}}
        students, _ = self.ns["group_by_student"]([
            file("Ada Rivera.pdf", "a"), file("Ben Rivera.pdf", "b")], saved, ROSTER)
        self.assertEqual(list(students), ["email:teacher@example.test"])
        st = next(iter(students.values()))
        self.assertEqual(st["grades"], {"A": "6"})
        self.assertTrue(all(f["identity_reason"] == "saved_identity" for f in st["files"]))

    def test_manual_alias_preserves_unmatched_marking(self):
        f = file("scan.pdf")
        key = unmatched_identity(f)
        saved = {self.ns["student_key"](key, ""): {
            "grades": {"B": "5"}, "keywords": ["Shape"], "graded": True}}
        students, _ = self.ns["group_by_student"]([f], saved, ROSTER, {key: "10002"})
        ben = students["email:10002@example.test"]
        self.assertEqual(ben["grades"], {"B": "5"})
        self.assertEqual(ben["keywords"], ["Shape"])

    def test_no_roster_preserves_existing_metadata_behavior(self):
        students, _ = self.ns["group_by_student"]([file("Ada Rivera.pdf")], {})
        self.assertEqual(list(students), ["email:teacher@example.test"])

    def test_anonymous_presentation_removes_roster_name(self):
        students, _ = self.ns["group_by_student"]([file("Ada Rivera.pdf")], {}, ROSTER)
        self.ns["_ANON_FILE_NOUN"] = {"pdf": "PDF"}
        st = next(iter(students.values()))
        anon = self.ns["_anonymize_student"](st, "Work 01")
        self.assertEqual(anon["roster_label"], "")
        self.assertNotIn("Ada", json.dumps(anon))
        self.assertEqual(st["roster_label"], "Rivera Ada")

    def write(self, path, data):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(data), encoding="utf-8")

    def test_context_handoff_wins_then_database_then_saved_state(self):
        fid = "assignment"
        published = self.ns["cam_published_path"](fid)
        saved = self.ns["state_path"](fid)
        db = Path(self.tmp.name) / "acm_database.json"
        self.write(published, {"class": "Art", "matching_roster": ROSTER,
                               "work_aliases": {"scan": "10001"}})
        self.write(db, {"session": {"rosters": {"Art": ROSTER[1:]}}})
        self.write(saved, {"class_name": "Art", "matching_roster": ROSTER[:1]})
        load = self.ns["load_matching_context"]
        self.assertEqual(load(fid, "Art"), (ROSTER, {"scan": "10001"}))
        Path(published).unlink()
        before = db.read_bytes()
        self.assertEqual(load(fid, "Art"), (ROSTER[1:], {}))
        self.assertEqual(db.read_bytes(), before)
        db.unlink()
        self.assertEqual(load(fid, "Art"), (ROSTER[:1], {}))
        self.assertEqual(load(fid, "Other class"), ([], {}))
        self.assertEqual(load(fid, ""), ([], {}))

    def test_bad_context_and_explicit_empty_roster(self):
        path = self.ns["cam_published_path"]("a")
        self.write(path, {"class": "Art", "matching_roster": []})
        self.assertEqual(self.ns["load_matching_context"]("a", "Art"), ([], {}))
        Path(path).write_text("broken", encoding="utf-8")
        self.assertEqual(self.ns["load_matching_context"]("a", "Art"), ([], {}))

    def test_credentials_discovery_order_and_cloud_fallback(self):
        project = Path(self.tmp.name) / "project"
        workspace = project / "cam_grading_workspace"
        cloud = Path(self.tmp.name) / "cloud"
        for folder in (project, workspace, cloud):
            folder.mkdir(parents=True, exist_ok=True)
        self.ns.update(BASE_DIR=str(workspace), SETTINGS={"cloud_dir": str(cloud)})
        paths = [workspace / "credentials.json", project / "client_secret-test.json",
                 cloud / "credentials.json"]
        for path in paths:
            path.write_text("{}", encoding="utf-8")
        find = self.ns["find_client_secret"]
        for path in paths:
            self.assertEqual(find(), str(path))
            path.unlink()
        self.assertIsNone(find())

    def test_local_mixed_folder_keeps_flat_and_nested_submissions(self):
        root = Path(self.tmp.name) / "submissions"
        (root / "Rivera Ada").mkdir(parents=True)
        (root / "Rivera Ada" / "scan.pdf").write_bytes(b"test")
        (root / "Ben Rivera.pdf").write_bytes(b"test")
        provider = self.ns["LocalProvider"]()
        provider._file_dict = lambda p, s: file(Path(p).name, p, local_student=s)
        _, files = provider.fetch_folder(str(root))
        self.assertEqual(len(files), 2)
        students, _ = self.ns["group_by_student"](files, {}, ROSTER)
        self.assertEqual(set(students), {"email:10001@example.test", "email:10002@example.test"})

    def test_export_retains_student_id_and_unmatched_file_keys(self):
        students, _ = self.ns["group_by_student"]([
            file("Ada Rivera.pdf", "a"), file("scan.pdf", "b")], {}, ROSTER)
        for st in students.values():
            st["grades"] = {"A": "6"}
        self.ns["STATE"].update(students=students, folder_name="Painting", criteria=["A"],
                                deadline="", cam_extra={})
        self.ns["request"] = SimpleNamespace(args={})
        self.ns["class_output_dir"] = lambda **kwargs: self.tmp.name
        data = self.ns["api_export"]()
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
        self.assertEqual({r["Student Name"] for r in rows}, {"10001", unmatched_identity(file("scan.pdf", "b"))})
        self.assertTrue(all(r["Grade (Crit A)"] == "6" for r in rows))

    def prepare_load(self, roster):
        self.write(self.ns["cam_published_path"]("folder"),
                   {"class": "Art", "matching_roster": roster})
        files = [file("Ada Rivera.pdf", "a"), file("scan.pdf", "b")]
        provider = SimpleNamespace(name="drive", state_key=lambda ref: ref,
                                   fetch_folder=lambda ref: ("Painting", files))
        self.ns.update(
            request=SimpleNamespace(get_json=lambda **kwargs: {
                "folder_id": "folder", "class_name": "Art"}),
            provider_for=lambda ref: provider,
            load_saved_grades=lambda ref: {},
            load_cache_entry=lambda ref: ({}, [], [], [], "", {}, None),
            load_cam_published_name=lambda ref: None,
            load_cam_published=lambda ref: None,
            load_saved_checklist=lambda ref: [],
            derive_checklist_from_saved=lambda saved: [],
            present_students=lambda: list(self.ns["STATE"]["students"].values()))
        return files

    def test_assignment_load_matches_and_saves_roster_context(self):
        self.prepare_load(ROSTER)
        saved = []
        self.ns["save_state"] = lambda: saved.append(dict(self.ns["STATE"]))
        response = self.ns["api_load"]()
        self.assertEqual((response["student_count"], response["file_count"],
                          response["filename_match_count"], response["review_file_count"]),
                         (2, 2, 1, 1))
        self.assertEqual(saved[0]["matching_roster"], ROSTER)
        self.assertEqual(saved[0]["work_aliases"], {})

    def test_shortened_legacy_roster_blocks_load_before_any_grading_write(self):
        self.prepare_load([{**ROSTER[0], "key": "26", "email": "26b1001@example.test"}])
        saved = []
        self.ns["save_state"] = lambda: saved.append(True)
        response, code = self.ns["api_load"]()
        self.assertEqual(code, 409)
        self.assertIn("Re-upload", response["error"])
        self.assertEqual(saved, [])
        self.assertTrue(Path(self.ns["cam_published_path"]("folder")).exists())


class HandoffTests(unittest.TestCase):
    def test_dashboard_publishes_only_active_class_roster_and_aliases(self):
        with tempfile.TemporaryDirectory(prefix="cam_handoff_test_") as tmp:
            ns = dict(os=os, json=json, datetime=datetime.datetime,
                      st=SimpleNamespace(session_state={
                          "prefs": {"db_custom_path": tmp}, "active_class": "Art",
                          "rosters": {"Art": ROSTER, "Other": [{"key": "private-other"}]},
                          "work_aliases": {"Art": {"scan": "10001"}}}),
                      students_for_active_class=lambda: [], CRIT_ORDER=["A"],
                      gb=lambda: SimpleNamespace(assignments=[]),
                      class_data_dir=lambda *args, **kwargs: tmp,
                      _workspace_state_key=lambda ref: ref)
            functions_from(ROOT / "app.py", ["_publish_workspace_grades"], ns)
            ns["_publish_workspace_grades"]("Painting", "folder")
            data = json.loads((Path(tmp) / "cam_grades_folder.json").read_text())
            self.assertEqual(data["matching_roster"], ROSTER)
            self.assertEqual(data["work_aliases"], {"scan": "10001"})
            self.assertNotIn("private-other", json.dumps(data))


if __name__ == "__main__":
    unittest.main()
