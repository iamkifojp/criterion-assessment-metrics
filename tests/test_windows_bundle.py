"""Structural tests for the Windows portable bundle builder."""

import tempfile
import unittest
from pathlib import Path

from tools import build_windows_bundle as builder


class WindowsBundleTests(unittest.TestCase):
    def test_enable_site_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp)
            pth = runtime / "python314._pth"
            pth.write_text("python314.zip\n.\n#import site\n", encoding="utf-8")
            builder.enable_site_packages(runtime)
            contents = pth.read_text(encoding="utf-8")
            self.assertIn("\nimport site\n", contents)
            self.assertIn("\n..\n", contents)
            self.assertIn("\n..\\cam_grading_workspace\n", contents)
            # CAM2's own `engine` / `app` would clash with CAM's.
            self.assertNotIn("exam_grading", contents)

    def test_launchers_and_readme_are_written(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            builder.write_launchers(bundle)
            builder.write_readme(bundle)
            vbs_path = bundle / "Start CAM.vbs"
            self.assertTrue(vbs_path.read_bytes().startswith(b"\xff\xfe"))
            vbs = vbs_path.read_text(encoding="utf-16")
            bat = (bundle / "Start CAM (troubleshooting).bat").read_text()
            self.assertIn('shell.Run """runtime\\python.exe"" -B ""start_cam.py""", 0, False', vbs)
            self.assertIn('fso.FileExists(fso.BuildPath(root, "runtime\\python.exe"))', vbs)
            self.assertIn('fso.FileExists(fso.BuildPath(root, "start_cam.py"))', vbs)
            self.assertIn("MsgBox", vbs)
            self.assertIn('"runtime\\python.exe" -B "start_cam.py" --console', bat)
            readme = (bundle / "READ ME FIRST.txt").read_text(encoding="utf-8-sig")
            self.assertIn("Extract All", readme)
            self.assertIn("Quit CAM beside Settings", readme)
            # The licence line, in English and Japanese (D15).
            self.assertIn("GNU AGPL version 3", readme)
            self.assertIn("GNU AGPLバージョン3", readme)
            self.assertIn('"Licences" folder', readme)

    def test_audit_rejects_sensitive_file_at_any_depth(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            nested = bundle / "nested"
            nested.mkdir()
            (nested / "Credentials.json").write_text("secret")
            with self.assertRaisesRegex(RuntimeError, "Sensitive or unexpected"):
                builder.audit_bundle(bundle)

    def test_audit_rejects_nested_gradebook_and_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            (bundle / "acm_database.json").write_text("fictional sample")
            nested = bundle / "class"
            nested.mkdir()
            (nested / "acm_database.json").write_text("unexpected")
            (bundle / "acm_database.json.bak-term-20260714-120000").write_text(
                "backup"
            )
            with self.assertRaisesRegex(RuntimeError, "class.*acm_database.json"):
                builder.audit_bundle(bundle)

    def test_final_zip_audit_checks_payload_and_runtime(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            bundle.mkdir()
            for name in builder.REQUIRED_BUNDLE_FILES:
                (bundle / name).write_bytes(b"sample")
            runtime = bundle / "runtime"
            runtime.mkdir()
            (runtime / "python.exe").write_bytes(b"runtime")
            archive = builder.make_zip(bundle, root, "test")
            with self.assertRaisesRegex(RuntimeError, "exam_grading/launcher.py"):
                builder.audit_zip(archive, require_runtime=True)

            for path in builder.REQUIRED_EXAM_PATHS | builder.LICENCE_PATHS:
                (bundle / path).parent.mkdir(parents=True, exist_ok=True)
                (bundle / path).write_bytes(b"sample")
            archive = builder.make_zip(bundle, root, "test")
            with self.assertRaisesRegex(RuntimeError, "THIRD-PARTY-NOTICES"):
                builder.audit_zip(archive, require_runtime=True)
            builder.audit_zip(archive, require_runtime=False)

            (bundle / builder.THIRD_PARTY_PATH).write_bytes(b"sample")
            archive = builder.make_zip(bundle, root, "test")
            builder.audit_zip(archive, require_runtime=True)

    def test_dev_files_are_removed_including_cam2s(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            for rel in ("tools/build.py", "docs/X_PLAN.md", "docs/USER_MANUAL.md",
                        "exam_grading/tests/test_a.py", "exam_grading/tools/scans.py",
                        "exam_grading/doc/review.md", "exam_grading/PLAN.md",
                        "exam_grading/AGENTS.md", "exam_grading/launcher.py",
                        "exam_grading/engine/__init__.py", "exam_grading/README.md",
                        "exam_grading/Exam-Section-Plan.md",
                        "exam_grading/Feedback-and-Upgrades.md",
                        "exam_grading/requirements-build.txt",
                        "exam_grading/licences/NOTICE.txt",
                        "exam_grading/licences/AGPL-3.0.txt",
                        "exam_grading/LICENSE",
                        "exam_grading/.gitattributes", "exam_grading/.gitignore",
                        "docs/CAM2_FEEDBACK_FOR_CAM.md",
                        "tests/test_a.py", ".gitattributes", ".gitignore",
                        "AGENTS.md", "CLAUDE.md", "app.py",
                        ".streamlit/config.toml", "README.md"):
                (bundle / rel).parent.mkdir(parents=True, exist_ok=True)
                (bundle / rel).write_text("x")
            builder.remove_dev_files(bundle)
            left = sorted(p.relative_to(bundle).as_posix()
                          for p in bundle.rglob("*") if p.is_file())
            self.assertEqual(left, [".streamlit/config.toml", "README.md", "app.py",
                                    "docs/USER_MANUAL.md", "exam_grading/LICENSE",
                                    "exam_grading/README.md",
                                    "exam_grading/engine/__init__.py",
                                    "exam_grading/launcher.py"])

    def test_prune_removes_caches_and_script_shims(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            cache = bundle / "package" / "__pycache__"
            scripts = bundle / "runtime" / "Scripts"
            cache.mkdir(parents=True)
            scripts.mkdir(parents=True)
            (cache / "module.pyc").write_bytes(b"x")
            (scripts / "streamlit.exe").write_bytes(b"x")
            (scripts / "helper.py").write_text("pass")
            builder.prune_runtime(bundle)
            self.assertFalse(cache.exists())
            self.assertFalse((scripts / "streamlit.exe").exists())
            self.assertTrue((scripts / "helper.py").exists())

    def test_quick_guide_is_copied_to_bundle_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / "bundle"
            bundle.mkdir()
            guide = root / "guide.pdf"
            guide.write_bytes(b"%PDF-1.4\nfictional guide")

            builder.copy_quick_guide(bundle, guide)

            self.assertEqual(
                (bundle / "CAM Quick Guide.pdf").read_bytes(),
                guide.read_bytes(),
            )


if __name__ == "__main__":
    unittest.main()
