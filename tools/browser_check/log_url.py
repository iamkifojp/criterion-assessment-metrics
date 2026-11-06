"""Stands in for a web browser in the sandbox: records the address CAM, CAM2 or
the workspace would open, so it can be opened in Claude's in-app browser
instead of the computer's own. The start scripts point BROWSER here.
"""

import datetime
import os
import sys

log = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opened-urls.txt")
log = os.environ.get("CAM_SANDBOX_URL_LOG", log)
with open(log, "a", encoding="utf-8") as handle:
    handle.write(f"{datetime.datetime.now():%H:%M:%S} {sys.argv[1]}\n")
