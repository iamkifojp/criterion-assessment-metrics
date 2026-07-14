"""Unit tests for the dependency-free Windows folder helper."""

import os
import subprocess
import tempfile
import unittest
from unittest import mock

from engine import folder_dialog


class FolderDialogTests(unittest.TestCase):
    def test_documents_override_is_absolute(self):
        with tempfile.TemporaryDirectory() as root:
            relative = os.path.relpath(root)
            with mock.patch.dict(os.environ, {"CAM_DOCUMENTS_OVERRIDE": relative}):
                self.assertEqual(folder_dialog.documents_folder(),
                                 os.path.abspath(relative))

    def test_picker_is_hidden_off_windows(self):
        with mock.patch.object(folder_dialog.os, "name", "posix"):
            with mock.patch.object(folder_dialog.subprocess, "run") as run:
                self.assertIsNone(folder_dialog.pick_folder("Choose"))
                run.assert_not_called()

    def test_picker_returns_child_stdout(self):
        completed = subprocess.CompletedProcess([], 0, stdout="C:\\CAM Data\n",
                                                stderr="")
        with mock.patch.object(folder_dialog.os, "name", "nt"):
            with mock.patch.object(folder_dialog.subprocess, "run",
                                   return_value=completed) as run:
                self.assertEqual(folder_dialog.pick_folder("Choose", r"C:\CAM"),
                                 r"C:\CAM Data")
                command = run.call_args.args[0]
                self.assertEqual(command[1:3], ["-m", "engine.folder_dialog"])
                self.assertIn("--initial", command)

    def test_picker_cancel_returns_none(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(folder_dialog.os, "name", "nt"), \
             mock.patch.object(folder_dialog.subprocess, "run",
                               return_value=completed):
            self.assertIsNone(folder_dialog.pick_folder("Choose"))


if __name__ == "__main__":
    unittest.main()
