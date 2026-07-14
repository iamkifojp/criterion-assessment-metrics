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
            self.assertIn("\nimport site\n", pth.read_text(encoding="utf-8"))

    def test_launchers_and_readme_are_written(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp)
            builder.write_launchers(bundle)
            builder.write_readme(bundle)
            vbs = (bundle / "Start CAM.vbs").read_text(encoding="utf-8-sig")
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
            with self.assertRaisesRegex(RuntimeError, "Sensitive files"):
                builder.audit_bundle(bundle)

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


if __name__ == "__main__":
    unittest.main()
