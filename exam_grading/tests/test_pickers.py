"""Native pickers (ported from CAM's test_folder_dialog.py, plus macOS).

The real dialogs need a person to click them, so these tests check how the
pickers are launched and how their output is read.

Run:  python -m unittest tests.test_pickers
"""

import io
import os
import subprocess
import tempfile
import unittest
from unittest import mock

from engine import pickers


def completed(stdout="", code=0):
    return subprocess.CompletedProcess([], code, stdout=stdout, stderr="")


class PickerTests(unittest.TestCase):
    def test_documents_override_is_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            relative = os.path.relpath(root)
            with mock.patch.dict(os.environ, {"CAM2_DOCUMENTS_OVERRIDE": relative}):
                self.assertEqual(pickers.documents_folder(), os.path.abspath(relative))

    def test_no_picker_on_other_systems(self):
        with mock.patch.object(pickers.os, "name", "posix"), \
             mock.patch.object(pickers.sys, "platform", "linux"), \
             mock.patch.object(pickers.subprocess, "run") as run:
            self.assertIsNone(pickers.pick_folder("Choose"))
            run.assert_not_called()

    def test_windows_runs_a_child_process(self):
        with mock.patch.object(pickers.os, "name", "nt"), \
             mock.patch.object(pickers.subprocess, "run",
                               return_value=completed("C:\\CAM Data\n")) as run:
            self.assertEqual(pickers.pick_pdf("Choose", r"C:\CAM"), r"C:\CAM Data")
            command = run.call_args.args[0]
            self.assertEqual(command[1:5], ["-m", "engine.pickers", "--mode", "pdf"])
            self.assertIn("--initial", command)
            self.assertEqual(run.call_args.kwargs["cwd"], pickers.APP_ROOT)

    def test_packaged_app_runs_itself_with_pick(self):
        with mock.patch.object(pickers.os, "name", "nt"), \
             mock.patch.object(pickers.sys, "frozen", True, create=True), \
             mock.patch.object(pickers.subprocess, "run",
                               return_value=completed("C:\\Scans\n")) as run:
            self.assertEqual(pickers.pick_folder("Choose"), r"C:\Scans")
            command = run.call_args.args[0]
            self.assertEqual(command[1:4], [pickers.PICK_FLAG, "--mode", "folder"])
            self.assertNotIn("-m", command)

    def test_child_writes_utf8(self):
        # A pipe on Japanese Windows is cp932 unless the child says otherwise.
        out = io.TextIOWrapper(io.BytesIO(), encoding="cp932")
        with mock.patch.object(pickers, "_pick_com", return_value="C:\\試験", create=True), \
             mock.patch.object(pickers.sys, "stdout", out):
            self.assertEqual(pickers._main(["--mode", "folder"]), 0)
            self.assertEqual(out.buffer.getvalue(), "C:\\試験\n".encode("utf-8"))

    def test_cancel_returns_none(self):
        with mock.patch.object(pickers.os, "name", "nt"), \
             mock.patch.object(pickers.subprocess, "run", return_value=completed("")):
            self.assertIsNone(pickers.pick_folder("Choose"))

    def test_macos_passes_text_as_arguments(self):
        title = 'Choose "scans"; do shell script "x"'
        with tempfile.TemporaryDirectory() as start, \
             mock.patch.object(pickers.os, "name", "posix"), \
             mock.patch.object(pickers.sys, "platform", "darwin"), \
             mock.patch.object(pickers.subprocess, "run",
                               return_value=completed("/Users/t/Scans/\n")) as run:
            self.assertEqual(pickers.pick_folder(title, start), "/Users/t/Scans")
            command = run.call_args.args[0]
            self.assertEqual(command[0], "osascript")
            self.assertEqual(command[3:], [title, start])
            self.assertNotIn(title, command[2])

    def test_macos_cancel(self):
        with mock.patch.object(pickers.os, "name", "posix"), \
             mock.patch.object(pickers.sys, "platform", "darwin"), \
             mock.patch.object(pickers.subprocess, "run", return_value=completed("", 1)):
            self.assertIsNone(pickers.pick_pdf("Choose"))


if __name__ == "__main__":
    unittest.main()
