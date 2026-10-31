"""English and Japanese text stay in step, and every error has a message.

Run:  python -m unittest tests.test_i18n
"""

import os
import re
import unittest

from engine import i18n
from engine.errors import UserError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_DIR = os.path.join(ROOT, "engine")
JS_DIR = os.path.join(ROOT, "static", "js")

# Keys built at run time in the UI, e.g. t(`step.${n}`)
DYNAMIC_KEYS = (
    [f"step.{n}" for n in range(1, 6)] + [f"step.{n}.hint" for n in range(1, 6)]
    + [f"step2.sub.{s}" for s in ("mode", "rubric", "boxes", "choice", "slice")]
    + ["step2.mode.marks", "step2.mode.marks_hint", "step2.mode.rubric", "step2.mode.rubric_hint"]
    + [f"step2.boxes.tip_{k}" for k in ("space", "question", "parts", "overlap")]
    + [f"pick.{k}" for k in ("scans_folder", "save_folder", "session_folder", "combined_pdf")])


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def error_codes_in_engine():
    """Error codes raised by the engine and the server."""
    pattern = re.compile(r'(?:UserError|super\(\)\.__init__)\(\s*"([a-z_]+)"')
    files = [os.path.join(ENGINE_DIR, n) for n in os.listdir(ENGINE_DIR) if n.endswith(".py")]
    files += [os.path.join(ROOT, "app.py"), os.path.join(ROOT, "appstate.py")]
    codes = set()
    for path in files:
        codes |= set(pattern.findall(_read(path)))
    return codes


def keys_in_ui():
    pattern = re.compile(r'\bt\(\s*"([a-z0-9_.]+)"')
    keys = set()
    for name in os.listdir(JS_DIR):
        if name.endswith(".js"):
            keys |= set(pattern.findall(_read(os.path.join(JS_DIR, name))))
    return keys | set(DYNAMIC_KEYS)


class I18nTests(unittest.TestCase):
    def test_languages_have_the_same_keys(self):
        self.assertEqual(set(i18n.strings("en")), set(i18n.strings("ja")))

    def test_placeholders_match(self):
        field = re.compile(r"{(\w+)}")
        for key, en in i18n.strings("en").items():
            ja = i18n.strings("ja")[key]
            self.assertEqual(set(field.findall(en)), set(field.findall(ja)), key)

    def test_every_engine_error_has_text(self):
        codes = error_codes_in_engine()
        self.assertIn("range_off_grid", codes)
        missing = [c for c in codes if "error." + c not in i18n.strings("en")]
        self.assertEqual(missing, [])

    def test_every_ui_key_has_text(self):
        keys = keys_in_ui()
        self.assertIn("step2.boxes.coach_question", keys)
        missing = sorted(k for k in keys if k not in i18n.strings("en"))
        self.assertEqual(missing, [])

    def test_translation_and_fallbacks(self):
        err = UserError("mark_out_of_range", value=7, max=5)
        self.assertIn("0 から 5", i18n.error_text(err, "ja"))
        self.assertIn("0 to 5", i18n.error_text(err, "en"))
        self.assertEqual(i18n.t("no.such.key", "ja"), "no.such.key")
        self.assertEqual(i18n.t("save.saved_at", "fr", time="10:00"), "Saved ✓ 10:00")
        self.assertIn("{time}", i18n.t("save.saved_at", "en"))
        # An error may have a parameter called "language" without clashing.
        self.assertEqual(i18n.error_text(UserError("unknown_language", language="fr"), "en"),
                         "Unknown language.")


if __name__ == "__main__":
    unittest.main()
