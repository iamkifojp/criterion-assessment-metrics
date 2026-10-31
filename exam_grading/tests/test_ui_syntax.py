"""Every browser module parses. A syntax error in one module stops the whole
app from loading, and nothing else in the test suite would notice.

Needs Node.js; the test is skipped on computers without it.

Run:  python -m unittest tests.test_ui_syntax
"""

import os
import shutil
import subprocess
import unittest

JS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js")
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "Node.js is not installed")
class UiSyntaxTests(unittest.TestCase):
    def test_every_module_parses(self):
        names = sorted(n for n in os.listdir(JS_DIR) if n.endswith(".js"))
        self.assertIn("main.js", names)
        for name in names:
            with open(os.path.join(JS_DIR, name), encoding="utf-8") as fh:
                source = fh.read()
            result = subprocess.run([NODE, "--input-type=module", "--check"], input=source,
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, f"{name}:\n{result.stderr}")


if __name__ == "__main__":
    unittest.main()
