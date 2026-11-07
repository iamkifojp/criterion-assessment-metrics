"""Regression tests for Browse buttons that fill Streamlit text inputs."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

import app


class FolderBrowseTests(unittest.TestCase):
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
