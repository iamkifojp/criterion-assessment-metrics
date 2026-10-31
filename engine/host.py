"""Running CAM2 from another app (a *host*, such as CAM).

The host starts CAM2 with ``launcher.py --host <handoff.json>``. The handoff
names one exam and where its session lives, and brings the class list::

    {"format": "cam2-host", "version": 1, "host": "CAM",
     "exam_name": "Y8 Science Midterm", "class_name": "8A",
     "session_folder": "D:/OneDrive/CAM/8A/exams/Y8 Science Midterm",
     "roster": [{"external_id": "8A-07", "name": "Tanaka Hana"}]}

CAM2 then opens that session (or starts it in that folder), uses the host's
class list for matching names and keeps each entry's ``external_id``, so the
host can file results without matching names again. When grading is done the
teacher clicks *Send to CAM*, which stamps ``host_ready_at`` in
``cam2_session.json``; the host only reads the session folder.

Nothing here changes how CAM2 works on its own.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from . import model, workflow
from .errors import UserError

FORMAT = "cam2-host"
VERSION = 1
MAX_ROSTER = 500


def normalize(data) -> dict:
    """Check a handoff and keep only what CAM2 uses."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise UserError("host_handoff_invalid")
    version = data.get("version")
    if not isinstance(version, int) or version > VERSION:
        raise UserError("file_from_newer_version", version=version)
    exam = " ".join(str(data.get("exam_name") or "").split())[:80]
    folder = str(data.get("session_folder") or "").strip()
    if not exam or not folder or not os.path.isabs(folder):
        raise UserError("host_handoff_invalid")
    roster, seen = [], set()
    for entry in data.get("roster") or []:
        if not isinstance(entry, dict):
            continue
        ext = str(entry.get("external_id") or "").strip()
        name = " ".join(str(entry.get("name") or "").split())[:100]
        if ext and name and ext not in seen:
            seen.add(ext)
            roster.append({"external_id": ext, "name": name})
    return {"host": " ".join(str(data.get("host") or "CAM").split())[:40] or "CAM",
            "exam_name": exam,
            "class_name": " ".join(str(data.get("class_name") or "").split())[:80],
            "session_folder": os.path.normpath(folder),
            "roster": roster[:MAX_ROSTER]}


def load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        raise UserError("host_handoff_invalid")
    return normalize(data)


def same_folder(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def is_host_session(handoff: Optional[dict], folder: str) -> bool:
    return bool(handoff) and same_folder(handoff["session_folder"], folder)


def apply_roster(config: dict, handoff: dict) -> dict:
    """Use the host's class list. An entry keeps its id while its
    ``external_id`` stays, so papers stay matched when a name is corrected."""
    by_ext = {r.get("external_id"): r["id"] for r in config.get("roster") or [] if r.get("external_id")}
    used = set(by_ext.values())
    entries, n = [], 0
    for person in handoff["roster"]:
        rid = by_ext.get(person["external_id"])
        if rid is None:
            n += 1
            while f"n{n:03d}" in used:
                n += 1
            rid = f"n{n:03d}"
            used.add(rid)
        entries.append({"id": rid, "name": person["name"], "external_id": person["external_id"]})
    workflow.set_roster(config, entries)
    config["host"] = {"name": handoff["host"], "class_name": handoff["class_name"]}
    return config


def set_ready(config: dict, ready: bool) -> dict:
    """Grading finished (or not): the host reads results only when stamped."""
    config["host_ready_at"] = model.now_iso() if ready else None
    return config
