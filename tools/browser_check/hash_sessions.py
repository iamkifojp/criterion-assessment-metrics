"""Hash every file in a class's CAM2 sessions, to prove CAM's Sync writes nothing.

    python hash_sessions.py "<sandbox>/data/Class 1/exams" > before.txt
    ... Sync in CAM ...
    python hash_sessions.py "<sandbox>/data/Class 1/exams" > after.txt

Then compare the two files. Only ``cam2.lock`` may differ, and only while
CAM2 has that session open: it is CAM2's own heartbeat.
"""

import hashlib
import os
import sys

root = sys.argv[1]
for folder, _dirs, files in sorted(os.walk(root)):
    for name in sorted(files):
        path = os.path.join(folder, name)
        with open(path, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
        print(digest, os.path.relpath(path, root).replace(os.sep, "/"))
