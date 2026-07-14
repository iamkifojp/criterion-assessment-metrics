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

    def test_launchers_and_readme_are_written(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            builder.write_launchers(bundle)
            builder.write_readme(bundle)
            vbs_path = bundle / "Start CAM.vbs"
            self.assertTrue(vbs_path.read_bytes().startswith(b"\xff\xfe"))
            vbs = vbs_path.read_text(encoding="utf-16")
            bat = (bundle / "Start CAM (troubleshooting).bat").read_text()
            self.assertIn("--server.port 8600", vbs)
            self.assertIn("logs\\cam.log", vbs)
            self.assertIn("--server.port 8600", bat)
            self.assertIn("Extract All", (bundle / "READ ME FIRST.txt").read_text(encoding="utf-8-sig"))

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

            builder.audit_zip(archive, require_runtime=True)

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
