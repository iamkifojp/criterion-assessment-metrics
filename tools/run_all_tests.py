"""Run CAM's tests and the vendored CAM2 exam-grading tests.

The two suites run in separate processes: both projects have a top-level
``engine`` package, so importing one would shadow the other. UTF-8 mode is
forced because some CAM tests read UTF-8 files with the default encoding,
which is cp932 on a Japanese Windows console.

Run:  python tools/run_all_tests.py
"""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SUITES = [
    ("CAM", ROOT, ["-m", "unittest", "discover", "-s", "tests"]),
    ("CAM2 exam grading", os.path.join(ROOT, "exam_grading"),
     ["-m", "unittest", "discover", "-s", "tests", "-t", "."]),
]


def main() -> int:
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    failed = []
    for name, cwd, args in SUITES:
        print(f"=== {name} ===", flush=True)
        if subprocess.run([sys.executable, *args], cwd=cwd, env=env).returncode:
            failed.append(name)
    if failed:
        print("FAILED: " + ", ".join(failed))
        return 1
    print("All suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
