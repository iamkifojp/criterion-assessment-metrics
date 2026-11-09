"""Regression tests for Browse buttons that fill Streamlit text inputs."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import app


class FolderBrowseTests(unittest.TestCase):
    def test_drive_signin_passes_active_db_folder_on_first_click(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.dict(os.environ, {"CAM_DB_PATH": str(Path(root) / "OneDrive" / "custom.json")}), \
                mock.patch.object(app, "_ensure_workspace_running", return_value=True), \
                mock.patch.object(app, "urlopen", return_value=io.BytesIO(b'{"handoff":"test-ticket"}')) as send, \
                mock.patch.object(app.webbrowser, "open") as open_browser:
            at = AppTest.from_string("import app\napp._class_dialog_body(edit=False)").run()
            at.button(key="drive_signin_add").click().run()
            self.assertFalse(at.exception)
            req = send.call_args.args[0]
            self.assertEqual(req.get_method(), "POST")
            self.assertTrue(req.full_url.endswith("/api/signin"))
            self.assertEqual(json.loads(req.data), {"db_folder": str(Path(root) / "OneDrive")})
            open_browser.assert_called_once_with(f"http://127.0.0.1:{app.GRADING_PORT}/signin?handoff=test-ticket")

    def test_class_dialog_applies_a_choice_on_save_and_keeps_it_on_cancel(self):
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(app, "NATIVE_FOLDER_PICKER", True), \
                mock.patch.object(app, "active_class_dict", return_value={
                    "name": "Fictional class", "master_dir": "previous-drive-id",
                }), \
                mock.patch.object(app, "pick_folder", side_effect=[folder, None]) as pick, \
                mock.patch.object(app, "update_class", return_value=True) as update, \
                mock.patch.object(app, "watch_master_directory") as watch:
            at = AppTest.from_string("import app\napp.class_dialog()").run()
            field_key = "clsdlg_master_edit"
            browse_key = "clsdlg_master_browse_edit"
            self.assertEqual(at.text_input(key=field_key).value, "previous-drive-id")

            at.button(key=browse_key).click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_input(key=field_key).value, folder)
            update.assert_not_called()

            at.button(key=browse_key).click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.text_input(key=field_key).value, folder)
            self.assertEqual([call.args[1] for call in pick.call_args_list], [None, folder])

            next(button for button in at.button if button.label == "Save changes").click().run()
            self.assertFalse(at.exception)
            update.assert_called_once_with("Fictional class", "Fictional class", "", "", "", folder)
            watch.assert_called_once_with()

    def test_setup_browse_enables_use_this_folder(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(app, "NATIVE_FOLDER_PICKER", True), \
                mock.patch.object(app, "_cloud_search_roots", return_value=[]):
            folder = str(Path(root) / "fictional data")
            Path(folder).mkdir()
            with mock.patch.object(app, "pick_folder", return_value=folder):
                at = AppTest.from_string("import app\napp._render_first_boot_setup()").run()
                self.assertTrue(at.button(key="boot_manual_use").disabled)
                at.button(key="boot_manual_browse").click().run()
                self.assertFalse(at.exception)
                self.assertEqual(at.text_input(key="boot_manual_path").value, folder)
                self.assertFalse(at.button(key="boot_manual_use").disabled)
