"""Unit tests for the dependency-free native folder helper."""

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

    def test_picker_is_hidden_on_linux(self):
        with mock.patch.object(folder_dialog.sys, "platform", "linux"), \
             mock.patch.object(folder_dialog.os, "name", "posix"):
            with mock.patch.object(folder_dialog.subprocess, "run") as run:
                self.assertIsNone(folder_dialog.pick_folder("Choose"))
                run.assert_not_called()

    def test_picker_returns_child_stdout(self):
        completed = subprocess.CompletedProcess([], 0, stdout="C:\\CAM Data\n",
                                                stderr="")
        with mock.patch.object(folder_dialog.sys, "platform", "win32"), \
             mock.patch.object(folder_dialog.os, "name", "nt"):
            with mock.patch.object(folder_dialog.subprocess, "run",
                                   return_value=completed) as run:
                self.assertEqual(folder_dialog.pick_folder("Choose", r"C:\CAM"),
                                 r"C:\CAM Data")
                command = run.call_args.args[0]
                self.assertEqual(command[1:3], ["-m", "engine.folder_dialog"])
                self.assertIn("--initial", command)

    def test_picker_cancel_returns_none(self):
        completed = subprocess.CompletedProcess([], 0, stdout="", stderr="")
        with mock.patch.object(folder_dialog.sys, "platform", "win32"), \
             mock.patch.object(folder_dialog.os, "name", "nt"), \
             mock.patch.object(folder_dialog.subprocess, "run",
                               return_value=completed):
            self.assertIsNone(folder_dialog.pick_folder("Choose"))


    def test_mac_picker_passes_title_and_folder_as_arguments(self):
        completed = subprocess.CompletedProcess([], 0, stdout="/tmp/架空の採点資料/\n", stderr="")
        with tempfile.TemporaryDirectory(prefix="CAM data ") as root, \
             mock.patch.object(folder_dialog.sys, "platform", "darwin"), \
             mock.patch.object(folder_dialog.subprocess, "run", return_value=completed) as run:
            title = 'Choose "CAM data"'
            self.assertEqual(folder_dialog.pick_folder(title, root), "/tmp/架空の採点資料")
            command = run.call_args.args[0]
            self.assertEqual(command[:2], ["/usr/bin/osascript", "-e"])
            self.assertEqual(command[3:], [title, root])

    def test_mac_picker_handles_cancel(self):
        cancelled = subprocess.CompletedProcess([], 1, stdout="", stderr="User canceled")
        with mock.patch.object(folder_dialog.sys, "platform", "darwin"), \
             mock.patch.object(folder_dialog.subprocess, "run", return_value=cancelled):
            self.assertIsNone(folder_dialog.pick_folder("Choose"))


if __name__ == "__main__":
    unittest.main()
