"""
CAM Grading Workspace — local Flask sub-app of Criterion Assessment Metrics
(CAM) for visually grading art assignments stored in a Google Drive folder.

Launched standalone (python app.py) or by the CAM Streamlit dashboard's
"Grade this Assignment/Exam" bridge, which spawns it on a separate port and
passes the target class/assignment via URL query parameters
(?class=..&assignment=..&aname=..) so it opens straight into grading.

Student-grouped edition
-----------------------
- OAuth login using your downloaded Google OAuth client-secret JSON
  (auto-detects `credentials.json` OR `client_secret_*.json`).
- Paste a Drive folder ID -> fetches the folder's real name + every file,
  reading each file's `owners` metadata to map artwork -> student. Because the
  folder is shared via your personal account, files owned by *you* fall back to
  sharingUser / lastModifyingUser / permissions to recover the student.
- Files are GROUPED BY STUDENT (nothing is ever deleted). Each student keeps an
  array of ALL their files, newest first.
- Left panel: a roster of "Student Workspace Cards". Each card shows the
  student's newest submission as a large preview plus an "N Files" badge.
  Clicking a card slides open a mini-gallery of every file that student
  uploaded (final work + older drafts + multiple angles), isolated per student.
- Right panel: a stable grading matrix, one row per student (grade 0-8,
  keyword checklist, auto-composed editable comment). Clicking any image in a
  student's stack highlights that student's row and focuses the grade input.
- Gallery re-sorts highest->lowest grade on save (ungraded last); the matrix
  stays in fixed order. Export CSV named after the Drive folder.

Run:  python app.py [--port 5000]   then open http://127.0.0.1:<port>
"""

import os
import re
import io
import csv
import glob
import json
import random
import shutil
import hashlib
import datetime
import threading
import time
import uuid

from flask import (
    Flask, request, jsonify, Response, send_file, abort
)

import exam_engine

# ---- Google API imports -----------------------------------------------------
from google.auth.transport.requests import Request, AuthorizedSession
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
TOKEN_FILE = os.path.join(BASE_DIR, "token.json")

# On-disk cache for PDFs the focused viewer downloads from Drive. Keyed by
# file id + modifiedTime so a re-upload (new modifiedTime) busts the entry.
# Gitignored (pdf_cache/); safe to delete — it repopulates on next open.
PDF_CACHE_DIR = os.path.join(BASE_DIR, "pdf_cache")

# On-disk cache for LocalProvider thumbnails (PDF first-page / image renders),
# keyed by source path + mtime + width. Kept OUTSIDE the served local folder so
# a rendered thumbnail is never itself served as student work. Gitignored
# (thumb_cache/); safe to delete — it repopulates on next open.
THUMB_CACHE_DIR = os.path.join(BASE_DIR, "thumb_cache")
# Grid thumbnail width (fast whole-class paint) and the hover-enlarge / clamp
# ceiling (the frontend requests ?sz=1600 on mouseenter, exactly like images).
THUMB_GRID_WIDTH = 400
THUMB_MAX_WIDTH = 1600

# Emails / names that belong to YOU (the teacher) and must NEVER be treated as
# the student. Because you typically share the school folder with a personal
# Gmail, Drive may report your school account as the "owner" of every file — so
# without this list every file you uploaded collapses under your own account
# instead of routing to the real student. List every account you own — your
# school login, your display name, and any Gmail the folder is shared through.
# Matched case-insensitively as a substring, so "j.smith" also matches
# "j.smith@school.edu".
#
# Keep this list EMPTY in source (it ships publicly). Put your real identities in
# the device-local, git-ignored local_device_prefs.json instead, e.g.:
#     { "my_identities": ["j.smith", "yourname@gmail.com"] }
# They are merged in at runtime by my_identities() below, so nothing personal is
# ever committed.
MY_IDENTITIES = [
]

_MY_IDENTITIES_CACHE = None


def _dedupe_identities(items):
    """Trim, drop blanks, and de-duplicate identities case-insensitively while
    preserving first-seen order. Identities are matched as case-insensitive
    substrings downstream, so two spellings that differ only in case are the same
    rule; keeping the first spelling the teacher typed is the friendly choice."""
    seen = set()
    out = []
    for x in items or []:
        s = str(x).strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def my_identities():
    """Effective teacher identities, merged from every source and de-duplicated:

      1. the (empty) public default ``MY_IDENTITIES``;
      2. ``SETTINGS["my_identities"]`` — the cloud-healing copy carried in
         gcg_settings.json (root + cloud mirror), so a new machine that only
         knows the cloud dir already has them (Phase 5);
      3. ``my_identities`` in the device-local, git-ignored
         local_device_prefs.json — the pre-Phase-5 home, kept as a per-device
         override/addition.

    Cached for the process; invalidated by load_settings() and by the settings
    panel save. Restart the app after editing prefs by hand."""
    global _MY_IDENTITIES_CACHE
    if _MY_IDENTITIES_CACHE is None:
        merged = list(MY_IDENTITIES)
        s = SETTINGS.get("my_identities")
        if isinstance(s, list):
            merged += [str(x) for x in s]
        try:
            val = load_prefs().get("my_identities")
            if isinstance(val, list):
                merged += [str(x) for x in val]
        except Exception:
            pass
        _MY_IDENTITIES_CACHE = _dedupe_identities(merged)
    return _MY_IDENTITIES_CACHE

app = Flask(__name__)

# MYP assessment criteria. Each is graded 0-8 independently. The teacher picks
# which subset is being assessed for a given assignment via the setup UI.
MYP_CRITERIA = ["A", "B", "C", "D"]

# In-memory state. Persisted to a per-folder JSON file. Grading is per-student.
STATE = {
    "class_folder_id": None,  # parent "class" folder the assignment was chosen from
    "class_name": None,       # active Class label (drives the cloud subfolder)
    "folder_id": None,        # the specific assignment subfolder being graded
    "folder_name": None,
    # CAM's current display name for this assignment (from the handoff /
    # published-grades file). The physical Drive folder is never renamed, so a
    # rename done in CAM Window 1 travels here and becomes the export filename —
    # keeping CAM's name-keyed Sync pointed at ONE assignment instead of
    # spawning a duplicate under the stale folder name. None -> use folder_name.
    "cam_name": None,
    "students": {},         # keyed by student_key
    "groups": [],           # list of {id, members:[student_key], color} pair-work links
    "checklist": [],        # per-folder rubric criteria [{label, type}]; [] = use frontend defaults
    "criteria": [],         # selected MYP criteria, e.g. ["A","C"]; [] = none chosen yet
    "deadline": "",         # official deadline, ISO 8601 (from <input datetime-local>)
    # CAM-graded students with no files in the folder (keyed by CAM student
    # id). Not gradable here, but carried into every CSV export so CAM's
    # whole-assignment purge-replace on Sync never drops their marks.
    "cam_extra": {},
    # Storage backend behind the loaded assignment: "drive" (Google Drive) or
    # "local" (a local folder). Chosen at load time by provider_for() and read
    # by the stateless /api/thumbnail and /api/video routes via current_provider().
    "source": "drive",
}
STATE_LOCK = threading.Lock()

# -----------------------------------------------------------------------------
# App settings (cloud sync directory + Class -> Drive folder-ID map)
# -----------------------------------------------------------------------------
# Persisted to gcg_settings.json in the app root (canonical, always found on
# boot) and mirrored into the cloud directory when one is configured. Lets the
# app remember every class's Drive folder ID and act as a data feeder: exports
# and the live state cache are written into per-class subfolders of the cloud
# directory so a downstream dashboard can pick them up.
SETTINGS_FILE = os.path.join(BASE_DIR, "gcg_settings.json")
SETTINGS = {
    "cloud_dir": "",       # local path to OneDrive/Google Drive sync folder ("" = off)
    "classes": {},         # {"Class 7A": "<driveFolderId>", ...}
    "my_identities": [],   # teacher's own Drive accounts/names — heals from the cloud
}


def _read_settings_file(path):
    """Parse one gcg_settings.json file into {cloud_dir, classes, my_identities},
    or None on read failure."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception as e:
        print(f"Warning: could not read {path}:", e)
        return None
    out = {"cloud_dir": str(data.get("cloud_dir", "") or "").strip(),
           "classes": {}, "my_identities": []}
    classes = data.get("classes") or {}
    if isinstance(classes, dict):
        out["classes"] = {str(k): str(v) for k, v in classes.items()
                          if str(k).strip() and str(v).strip()}
    ids = data.get("my_identities")
    if isinstance(ids, list):
        out["my_identities"] = _dedupe_identities(ids)
    return out


def _discover_classes_from_cloud(cloud_dir):
    """Recover {class_name: Drive folder ID} by scanning the cloud subfolders.

    The class->ID map in gcg_settings.json can go stale: two devices that each
    mirror their own settings into the cloud clobber each other last-writer-wins,
    so a class graded on one machine can vanish from the JSON entirely. But every
    class the app has ever graded leaves its identity behind in the grades_*.json
    files inside its own [cloud_dir]/[Class Name]/ subfolder — each records the
    Drive class_folder_id and the class_name the teacher typed. Scanning those
    lets us rediscover a class from its folder alone, which is exactly what the
    user expects: the class folders in the synced directory ARE the classes.
    """
    found = {}
    try:
        entries = sorted(os.listdir(cloud_dir))
    except Exception as e:
        print("Warning: could not scan cloud directory:", e)
        return found
    for name in entries:
        sub = os.path.join(cloud_dir, name)
        if not os.path.isdir(sub):
            continue
        # The first grades_*.json that records a Drive class_folder_id wins; a
        # class's folder ID is identical across all its assignment files.
        for gp in sorted(glob.glob(os.path.join(sub, "grades_*.json"))):
            try:
                with open(gp, "r", encoding="utf-8") as f:
                    g = json.load(f) or {}
            except Exception:
                continue
            cid = str(g.get("class_folder_id") or "").strip()
            if not cid:
                continue
            cname = str(g.get("class_name") or "").strip() or name
            found.setdefault(cname, cid)
            break
    return found


def load_settings():
    """(Re)build SETTINGS from disk, discarding whatever is cached in memory.

    Order of authority, each filling gaps left by the previous:
      1. The app root gcg_settings.json — read first to learn the cloud dir.
      2. The cloud dir's own gcg_settings.json — the copy OneDrive/Drive syncs
         between devices, so its class map wins over this machine's stale root.
      3. A scan of the cloud dir's per-class subfolders — recovers any class
         that has real graded data on disk but is missing from both JSON maps
         (e.g. clobbered by another device). This is the self-healing step that
         makes a class created on another laptop show up here.

    Called on every startup, and again on demand by the "Force Sync" action.
    """
    fresh = {"cloud_dir": "", "classes": {}, "my_identities": []}

    root = _read_settings_file(SETTINGS_FILE) if os.path.exists(SETTINGS_FILE) else None
    if root:
        fresh.update(root)

    cloud = fresh["cloud_dir"]
    if cloud and os.path.isdir(cloud):
        cloud_settings_path = os.path.join(cloud, "gcg_settings.json")
        if os.path.exists(cloud_settings_path):
            cloud_data = _read_settings_file(cloud_settings_path)
            if cloud_data is not None:
                fresh["classes"] = cloud_data["classes"]
                if cloud_data["cloud_dir"]:
                    fresh["cloud_dir"] = cloud_data["cloud_dir"]
                # Identities are an allowlist, not a map: unlike classes (where the
                # cloud copy wins), take the UNION of root + cloud so an identity
                # added on either machine is never dropped — a missing identity
                # silently misattributes the teacher's own files to a student.
                fresh["my_identities"] = _dedupe_identities(
                    fresh["my_identities"] + cloud_data["my_identities"])

        # Fill in any class present on disk but absent from the JSON maps.
        # setdefault: a name already mapped by the JSON keeps its (authoritative)
        # ID; only genuinely-missing classes are recovered from their folders.
        for cname, cid in _discover_classes_from_cloud(fresh["cloud_dir"]).items():
            fresh["classes"].setdefault(cname, cid)

    SETTINGS.clear()
    SETTINGS.update(fresh)

    # SETTINGS feed my_identities(); drop its cache so the next call rebuilds
    # from the freshly-loaded (possibly cloud-healed) identities.
    global _MY_IDENTITIES_CACHE
    _MY_IDENTITIES_CACHE = None


def save_settings():
    """Write SETTINGS to the app root, then mirror into the cloud dir if set."""
    payload = {"cloud_dir": SETTINGS.get("cloud_dir", ""),
               "classes": SETTINGS.get("classes", {}),
               "my_identities": SETTINGS.get("my_identities", [])}
    targets = [SETTINGS_FILE]
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if cloud and os.path.isdir(cloud):
        targets.append(os.path.join(cloud, "gcg_settings.json"))
    for path in targets:
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: could not write settings to {path}:", e)


# -----------------------------------------------------------------------------
# Device-local UI preferences (local_device_prefs.json)
# -----------------------------------------------------------------------------
# Same filename CAM uses for its per-device UI prefs (column widths, db path):
# a device-local JSON that lives beside the app and is NEVER the shared cloud
# database, so one machine can grade blind while another shows names. This is
# the home for the "Anonymous grading" toggle. save_prefs MERGES (read → update
# → write), so it preserves any key another tool wrote and never clobbers.
PREFS_FILE = os.path.join(BASE_DIR, "local_device_prefs.json")


def load_prefs():
    """Read device-local prefs as a dict (never raises; {} when absent/bad)."""
    try:
        with open(PREFS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_prefs(update):
    """Merge `update` into local_device_prefs.json, preserving other keys."""
    data = load_prefs()
    data.update(update)
    try:
        with open(PREFS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Warning: could not write prefs:", e)


def anonymous_enabled():
    """Whether the marking viewer hides student identity (device pref, default off)."""
    return bool(load_prefs().get("anonymous_grading"))


def _safe_dirname(name):
    """Filesystem-safe folder name for a class label."""
    return re.sub(r'[\\/*?:"<>|]', "_", (name or "").strip()).strip() or "Unsorted"


def class_output_dir(create=False):
    """Directory where this class's exports + state cache belong.

    Returns [cloud_dir]/[class_name]/ when both a cloud directory and an active
    class are set; otherwise falls back to the app root (BASE_DIR) so the app
    keeps working with no cloud configured.
    """
    cloud = SETTINGS.get("cloud_dir", "").strip()
    cls = STATE.get("class_name")
    if cloud and cls and os.path.isdir(cloud):
        d = os.path.join(cloud, _safe_dirname(cls))
        if create:
            try:
                os.makedirs(d, exist_ok=True)
            except Exception as e:
                print("Warning: could not create class subfolder:", e)
                return BASE_DIR
        return d
    return BASE_DIR


def _write_export_beacon(class_name, assignment, is_exam, csv_path):
    """Drop a one-line beacon in the cloud-dir root so CAM syncs on export.

    CAM (Streamlit) and CGW (Flask) are separate processes; CAM only reruns on
    user interaction, so CGW cannot push a fresh export to it. Instead, on every
    *routed* export (one written into the class subfolder CAM watches) we
    atomically rewrite a single ``cam_export_beacon.json`` in the cloud-dir root
    — the same folder CAM's sync scans. CAM's run_every fragment ``os.stat``s
    that file every few seconds and, on an mtime change, runs a *scoped* sync of
    just this class/assignment so the grades surface within seconds.

    Atomic (write ``.tmp`` then ``os.replace``, like ``ExamStore._write``) so a
    concurrent CAM read never sees a torn file. Strictly best-effort: any failure
    is logged to stdout and swallowed — a beacon problem must never fail or
    block the teacher's export. Download-only exports (no cloud dir) route
    nothing, so they write no beacon; the guard below makes that a quiet no-op."""
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if not cloud or not os.path.isdir(cloud):
        return
    dest = os.path.join(cloud, "cam_export_beacon.json")
    tmp = dest + ".tmp"
    payload = {
        "class_name": class_name or "",
        "assignment": assignment or "",
        "is_exam": bool(is_exam),
        "csv_path": csv_path or "",
        "ts": time.time(),
    }
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(tmp, dest)
    except Exception as e:
        print("Warning: could not write export beacon:", e)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def cache_file_path(create=False):
    """Path to the live grading-state cache for the active class/output dir."""
    return os.path.join(class_output_dir(create=create), "grading_cache.json")


# --- Renaming a class (carry its graded data to the new name) ----------------
def _rewrite_class_name_in_grades(folder, new_name):
    """Stamp new_name into "class_name" of every grades_*.json under folder.

    This is the piece that a plain settings-map edit misses: the grades files
    record the class_name the teacher originally typed, and _discover_classes_
    from_cloud() reads it back to reconstruct the class list. Left stale, it
    resurrects the old name as a duplicate class on the next Force Sync.
    Returns the number of files actually changed.
    """
    changed = 0
    for gp in glob.glob(os.path.join(folder, "grades_*.json")):
        try:
            with open(gp, "r", encoding="utf-8") as f:
                g = json.load(f)
        except Exception:
            continue
        if not isinstance(g, dict) or g.get("class_name") == new_name:
            continue
        g["class_name"] = new_name
        try:
            with open(gp, "w", encoding="utf-8") as f:
                json.dump(g, f, ensure_ascii=False, indent=2)
            changed += 1
        except Exception as e:
            print("Warning: could not rewrite class_name in", gp, e)
    return changed


def _merge_cache_files(src_path, dst_path):
    """Merge two grading_cache.json files (keyed by Drive folder ID) into dst.

    The renamed class's cache (src) wins on any overlapping assignment, since
    that is where the teacher was actually grading."""
    def _read(p):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except Exception:
            return {}
    merged = _read(dst_path)
    merged.update(_read(src_path))
    try:
        with open(dst_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Warning: could not merge cache into", dst_path, e)


def _merge_dir(src, dst):
    """Move everything from src into dst without ever losing data.

    grading_cache.json is dict-merged (see _merge_cache_files). Any other file
    that already exists in dst is preserved by backing up dst's copy to
    <name>.replaced-<stamp> before the src copy takes its place. Non-conflicting
    files move straight over; nested folders merge recursively. src is removed
    if it ends up empty.
    """
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    for entry in os.listdir(src):
        sp = os.path.join(src, entry)
        dp = os.path.join(dst, entry)
        if os.path.isdir(sp):
            os.makedirs(dp, exist_ok=True)
            _merge_dir(sp, dp)
            continue
        if entry == "grading_cache.json" and os.path.exists(dp):
            _merge_cache_files(sp, dp)
            try:
                os.remove(sp)
            except Exception:
                pass
            continue
        if os.path.exists(dp):
            try:
                os.replace(dp, dp + f".replaced-{stamp}")
            except Exception as e:
                print("Warning: could not back up", dp, e)
        try:
            os.replace(sp, dp)
        except Exception as e:
            print("Warning: could not move", sp, "->", dp, e)
    try:
        os.rmdir(src)   # only succeeds if nothing was left behind
    except OSError:
        pass


def _migrate_class_folder(old_name, new_name):
    """Move [cloud_dir]/[old]/ to [cloud_dir]/[new]/ and restamp its grades.

    Handles three cases: the target folder doesn't exist (a clean rename), it
    already exists (merge the two, keeping all data), or the two names map to the
    same on-disk folder once made filesystem-safe (restamp only). Returns a small
    summary of what happened.
    """
    summary = {"folder_moved": False, "merged": False, "grades_updated": 0}
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if not (cloud and os.path.isdir(cloud)):
        return summary

    old_dir = os.path.join(cloud, _safe_dirname(old_name))
    new_dir = os.path.join(cloud, _safe_dirname(new_name))

    if os.path.abspath(old_dir) == os.path.abspath(new_dir):
        # Only illegal characters differed -> same folder, just restamp.
        summary["grades_updated"] = _rewrite_class_name_in_grades(new_dir, new_name)
        return summary

    if not os.path.isdir(old_dir):
        # Never graded under the old name -> nothing on disk to carry over.
        if os.path.isdir(new_dir):
            summary["grades_updated"] = _rewrite_class_name_in_grades(new_dir, new_name)
        return summary

    if not os.path.exists(new_dir):
        try:
            os.rename(old_dir, new_dir)
            summary["folder_moved"] = True
        except Exception as e:
            print("Warning: could not move class folder:", e)
            return summary
    else:
        summary["merged"] = True
        _merge_dir(old_dir, new_dir)

    summary["grades_updated"] = _rewrite_class_name_in_grades(new_dir, new_name)
    return summary


# Load persisted settings at import time so they're available to every request
# (including under the Flask test client), not only when run as __main__.
load_settings()


# -----------------------------------------------------------------------------
# Google authentication
# -----------------------------------------------------------------------------
def find_client_secret():
    """Locate the OAuth client-secret file regardless of its exact name.

    Probes the app root first, then the configured cloud dir (Phase 5) so a new
    machine that only has the shared OneDrive/Drive folder can authenticate
    without hand-copying credentials.json. An installed-app client secret is
    low-sensitivity — useless without the teacher consenting in a browser — so a
    private cloud folder is a fine home for it. .gitignore excludes both name
    shapes from the repo regardless."""
    def _probe(folder):
        found = [os.path.join(folder, "credentials.json")]
        found += sorted(glob.glob(os.path.join(folder, "client_secret_*.json")))
        found += sorted(glob.glob(os.path.join(folder, "client_secret*.json")))
        return found

    candidates = _probe(BASE_DIR)
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if cloud and os.path.isdir(cloud):
        candidates += _probe(cloud)
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _maybe_bootstrap_token():
    """Opt-in, one-time seeding of the local OAuth token from the cloud dir.

    Off by default (device pref ``token_bootstrap``). When enabled and the local
    ``token.json`` is absent, copy ``<cloud_dir>/token.json`` beside this app so a
    new machine skips the browser sign-in (Phase 5). This app never mirrors the
    token back to the cloud dir — refreshes keep writing locally only, so the
    cloud copy is a deliberate one-way seed the teacher placed there. Tradeoff:
    the token grants drive.readonly to anyone who can read the cloud folder, which
    is why it is opt-in."""
    if os.path.exists(TOKEN_FILE):
        return
    try:
        if not bool(load_prefs().get("token_bootstrap")):
            return
    except Exception:
        return
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if not (cloud and os.path.isdir(cloud)):
        return
    src = os.path.join(cloud, "token.json")
    if not os.path.exists(src):
        return
    try:
        shutil.copyfile(src, TOKEN_FILE)
        print("Seeded token.json from cloud dir (token_bootstrap).")
    except Exception as e:
        print("Warning: could not seed token from cloud dir:", e)


def get_credentials():
    """Return valid OAuth credentials, running the local-server flow if needed."""
    _maybe_bootstrap_token()
    creds = None
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds or not creds.valid:
            secret = find_client_secret()
            if not secret:
                raise FileNotFoundError(
                    "No OAuth client-secret file found. Place your downloaded "
                    "'credentials.json' (or 'client_secret_*.json') next to app.py."
                )
            flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return creds


def get_service():
    return build("drive", "v3", credentials=get_credentials(), cache_discovery=False)


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------
def state_path(folder_id):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", folder_id or "session")
    return os.path.join(class_output_dir(create=True), f"grades_{safe}.json")


def save_state():
    if not STATE["folder_id"]:
        return
    try:
        with open(state_path(STATE["folder_id"]), "w", encoding="utf-8") as f:
            json.dump(STATE, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Warning: could not save state:", e)
    # Mirror the active state into the shared background cache as well.
    write_cache()


# --- Background autosave cache (grading_cache.json) --------------------------
# Schema version stamped at the top level of grading_cache.json. Unversioned
# legacy files (no "version" key) are treated as v0 and migrated per-entry by
# upgrade_entry() on load. Bump this — and add a v(N-1)->vN branch to
# upgrade_entry — whenever the persisted entry shape changes.
CACHE_VERSION = 1


def load_cache():
    """Return the full multi-folder cache dict, migrated to the current schema.

    Shape is ``{"version": CACHE_VERSION, "<key>": {…entry…}, …}`` keyed by the
    durable assignment key (Drive folder ID or ``local-<hash>`` slug). A missing
    top-level ``version`` means an unversioned legacy file (v0); every entry is
    run through upgrade_entry() and the result stamped v1. The migration is
    in-memory only — the next write_cache() persists it atomically."""
    path = cache_file_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    cache = {"version": CACHE_VERSION}
    for key, val in raw.items():
        if key == "version":
            continue
        cache[key] = upgrade_entry(val) if isinstance(val, dict) else val
    return cache


def write_cache():
    """Silently persist the active folder's grades + groups to grading_cache.json,
    keyed by Drive folder ID. Called on every checkbox / grade / comment change."""
    fid = STATE["folder_id"]
    if not fid:
        return
    try:
        cache = load_cache()
        cache["version"] = CACHE_VERSION   # stamp fresh (empty) files too
        cache[fid] = {
            "folder_name": STATE["folder_name"],
            # CAM's display name for this folder (survives the published-file
            # consumption + later manual reloads, so the export keeps using it).
            "cam_name": STATE.get("cam_name"),
            "class_folder_id": STATE.get("class_folder_id"),
            # Per-folder rubric headers (custom checklist criteria). Stored as
            # full {label, type} objects so the strength/growth styling and the
            # auto-comment grouping survive a reload. Saved ALONGSIDE student
            # data — never in place of it.
            "checklist_headers": STATE.get("checklist", []),
            # Selected MYP criteria + official deadline for this assignment.
            "criteria": STATE.get("criteria", []),
            "deadline": STATE.get("deadline", ""),
            # "students" is the established key and doubles as the student_data
            # bucket: each student's marks (per-criterion grades, keyword
            # checkboxes, comment).
            "students": {
                k: {
                    "grades": st.get("grades", {}),
                    "keywords": st.get("keywords", []),
                    "comment": st.get("comment", ""),
                    "graded": st.get("graded", False),
                    "late_marked": st.get("late_marked"),
                    # True = the teacher set this Late value by hand (tick or
                    # waive); sticky against deadline re-derivation. Absent/false
                    # = auto-derived from the deadline.
                    "late_manual": st.get("late_manual", False),
                    # Criteria whose band CAM changed since our last export;
                    # drives the MODIFIED marker until dismissed/exported.
                    "cam_modified": st.get("cam_modified", []),
                } for k, st in STATE["students"].items()
            },
            # CAM-graded students without files here (see STATE["cam_extra"]).
            "cam_extra": STATE.get("cam_extra", {}),
            "groups": STATE["groups"],
            "updated": datetime.datetime.now().isoformat(timespec="seconds"),
        }
        dest = cache_file_path(create=True)
        tmp = dest + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, dest)              # atomic; never leaves a half-written file
    except Exception as e:
        print("Warning: could not write grading_cache.json:", e)


def _normalize_checklist(raw):
    """Coerce a stored checklist into a clean list of {label, type} dicts.

    Accepts either the rich object form [{"label": ..., "type": ...}] or a
    bare list of strings ["Criteria 1", ...] (defaults those to type
    'positive'). Anything malformed is dropped. Returns [] for empty input so
    callers can fall back to the frontend defaults.
    """
    out = []
    for item in (raw or []):
        if isinstance(item, str):
            label = item.strip()
            if label:
                out.append({"label": label, "type": "positive"})
        elif isinstance(item, dict):
            label = str(item.get("label", "")).strip()
            if label:
                typ = item.get("type")
                out.append({"label": label,
                            "type": "growth" if typ == "growth" else "positive"})
    return out


def _normalize_grades(st):
    """Coerce a stored student record's grades into a {criterion: value} dict.

    Accepts the new per-criterion form {"grades": {"A": "7"}} and transparently
    migrates the legacy single-grade form {"grade": "7"} -> {"A": "7"} so older
    saved files keep their marks.
    """
    grades = st.get("grades")
    if isinstance(grades, dict):
        return {str(k): str(v) for k, v in grades.items() if str(v).strip() != ""}
    legacy = st.get("grade", "")
    if str(legacy).strip() != "":
        return {"A": str(legacy)}
    return {}


def _normalize_cam_modified(raw):
    """Coerce a stored MODIFIED marker into a clean list of criterion letters."""
    return [c for c in (raw or []) if c in MYP_CRITERIA]


def upgrade_entry(entry):
    """Migrate one grading_cache.json entry to the current schema (v1).

    The single per-entry migration routine (load_cache runs it over every
    entry). v0 (unversioned legacy) -> v1 folds in the long-standing read-time
    shims: `_normalize_checklist` coerces bare-string / mixed checklist headers
    to `{label, type}` objects, and `_normalize_grades` promotes a legacy
    single `"grade": "7"` to the per-criterion `{"A": "7"}` dict (the migrated
    `grade` key is then dropped).

    Every other field is carried through untouched — critically the sticky
    `late_manual` flag (defaulted to False = auto-derived only when ABSENT,
    never stripped or forced: doing so would un-stick every hand-set Late tick,
    recreating the 2026-07-09 late-flag incident) plus `cam_modified`
    (re-validated to real criterion letters), `cam_extra`, `cam_name`,
    `criteria`, `deadline` and `groups`. Idempotent on already-v1 entries."""
    if not isinstance(entry, dict):
        return {}
    entry["checklist_headers"] = _normalize_checklist(entry.get("checklist_headers"))
    students = entry.get("students")
    if isinstance(students, dict):
        for st in students.values():
            if not isinstance(st, dict):
                continue
            st["grades"] = _normalize_grades(st)     # legacy "grade" -> {"A": …}
            st.pop("grade", None)                    # obsolete once migrated
            st["late_manual"] = bool(st.get("late_manual", False))
            st["cam_modified"] = _normalize_cam_modified(st.get("cam_modified"))
    return entry


def _normalize_cam_students(raw):
    """Coerce a CAM per-student grade map into {sid: {grades, comment}}.

    Shared by the CAM-published file reader and the cached ``cam_extra``
    passthrough — both cross an app boundary, so bands are validated to whole
    numbers 0-8 (stored as strings, matching the workspace's grade values)
    and unknown criteria are dropped.
    """
    out = {}
    for sid, rec in (raw or {}).items():
        sid = str(sid).strip()
        if not sid or not isinstance(rec, dict):
            continue
        grades = {}
        for c, v in (rec.get("grades") or {}).items():
            if c not in MYP_CRITERIA:
                continue
            try:
                band = int(v)
            except (TypeError, ValueError):
                continue
            if 0 <= band <= 8:
                grades[c] = str(band)
        if grades:
            out[sid] = {"grades": grades,
                        "comment": str(rec.get("comment") or "")}
    return out


# --- CAM-published grades (cam_grades_<folderId>.json) ------------------------
# CAM writes this file into the class folder at every "Grade this Assignment"
# handoff: its current per-student bands + comments for the target folder.
# api_load merges it (CAM's values win — they are the latest the teacher
# entered), flags every band that changed since our last saved state as
# MODIFIED, then CONSUMES the file. Consumption matters: once merged, the
# values live in our own state, and a leftover copy re-read after a later
# grading session would overwrite newer marks with stale ones.

def cam_published_path(folder_id):
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", folder_id or "session")
    return os.path.join(class_output_dir(), f"cam_grades_{safe}.json")


def load_cam_published(folder_id):
    """Return CAM's published {sid: {grades, comment}} for this folder, or
    None when no (readable) file is present."""
    path = cam_published_path(folder_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("Warning: could not read", path, e)
        return None
    if not isinstance(data, dict):
        return None
    return _normalize_cam_students(data.get("students"))


def load_cam_published_name(folder_id):
    """Return the CAM assignment display name from the published file, or None.

    CAM stamps its current name for the target folder into this file at every
    "Grade this Assignment" handoff. Reading it here lets a rename done in CAM
    Window 1 travel to the workspace and drive the export filename, so CAM's
    name-keyed Sync updates the renamed assignment in place instead of creating
    a duplicate under the (never-renamed) physical folder name."""
    path = cam_published_path(folder_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return (str(data.get("assignment") or "").strip() or None)


def consume_cam_published(folder_id):
    """Delete the CAM-published file after its values are merged + persisted."""
    try:
        os.remove(cam_published_path(folder_id))
    except OSError:
        pass


def load_cache_entry(folder_id):
    """Return (grades_dict, groups, checklist, criteria, deadline, cam_extra,
    cam_name) from the cache."""
    entry = load_cache().get(folder_id) or {}
    grades = {}
    for k, st in (entry.get("students") or {}).items():
        grades[k] = {
            "grades": _normalize_grades(st),
            "keywords": st.get("keywords", []),
            "comment": st.get("comment", ""),
            "graded": st.get("graded", False),
            "late_marked": st.get("late_marked"),
            "late_manual": st.get("late_manual", False),
            "cam_modified": _normalize_cam_modified(st.get("cam_modified")),
        }
    groups = entry.get("groups") or []
    checklist = _normalize_checklist(entry.get("checklist_headers"))
    criteria = [c for c in (entry.get("criteria") or []) if c in MYP_CRITERIA]
    deadline = entry.get("deadline", "") or ""
    cam_extra = _normalize_cam_students(entry.get("cam_extra"))
    cam_name = (str(entry.get("cam_name") or "").strip() or None)
    return grades, groups, checklist, criteria, deadline, cam_extra, cam_name


def load_saved_checklist(folder_id):
    """Fallback: read checklist headers from the legacy grades_<id>.json file.

    save_state() dumps the whole STATE (including 'checklist') to that file, so
    it can restore the rubric even if grading_cache.json is missing/cleared.
    """
    path = state_path(folder_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return _normalize_checklist(data.get("checklist"))
        except Exception:
            return []
    return []


def derive_checklist_from_saved(saved):
    """Rebuild a rubric from saved student marks when no checklist was stored.

    Older grading sessions persisted each student's ticked keywords + an
    auto-composed comment, but a lost cache entry could leave the folder with no
    saved checklist headers. We recover the rubric from the union of keywords
    that students were actually marked with, classifying each as a strength or a
    growth area by which section of the saved comment it appears in
    ('Strengths: …' vs 'Areas to develop: …'). Order follows first appearance.
    """
    order = []
    pos, grow = set(), set()
    for st in (saved or {}).values():
        kws = st.get("keywords") or []
        comment = st.get("comment") or ""
        si = comment.find("Strengths:")
        gi = comment.find("Areas to develop:")
        strengths_part = ""
        growth_part = ""
        if si != -1:
            end = gi if (gi != -1 and gi > si) else len(comment)
            strengths_part = comment[si:end]
        if gi != -1:
            growth_part = comment[gi:]
        for w in kws:
            if w not in order:
                order.append(w)
            if w in growth_part:
                grow.add(w)
            elif w in strengths_part:
                pos.add(w)
    out = []
    for w in order:
        typ = "growth" if (w in grow and w not in pos) else "positive"
        out.append({"label": w, "type": typ})
    return out


def load_saved_grades(folder_id):
    """Return saved {student_key: {grade, keywords, comment, graded}} if present."""
    path = state_path(folder_id)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            out = {}
            for k, st in (data.get("students") or {}).items():
                out[k] = {
                    "grades": _normalize_grades(st),
                    "keywords": st.get("keywords", []),
                    "comment": st.get("comment", ""),
                    "graded": st.get("graded", False),
                    "late_marked": st.get("late_marked"),
                    "late_manual": st.get("late_manual", False),
                    "cam_modified": _normalize_cam_modified(st.get("cam_modified")),
                }
            return out
        except Exception:
            return {}
    return {}


# -----------------------------------------------------------------------------
# Drive helpers
# -----------------------------------------------------------------------------
GOOGLE_DOC_TYPES = {
    "application/vnd.google-apps.presentation": "slides",
    "application/vnd.google-apps.document": "doc",
    "application/vnd.google-apps.spreadsheet": "sheet",
    "application/vnd.google-apps.drawing": "drawing",
}


# Video file extensions to recognise even when Drive reports a generic MIME
# type (e.g. application/octet-stream) for a student's stop-motion upload.
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".webm", ".ogv", ".avi", ".mkv"}


def classify(mime, name=""):
    if mime in GOOGLE_DOC_TYPES:
        return GOOGLE_DOC_TYPES[mime]
    if mime and mime.startswith("video/"):
        return "video"
    ext = os.path.splitext(name or "")[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if mime and mime.startswith("image/"):
        return "image"
    if mime == "application/pdf":
        return "pdf"
    return "other"


def is_me(identity):
    """True if a Drive user/permission object refers to the teacher."""
    if not identity:
        return False
    blob = ((identity.get("emailAddress") or "") + " " +
            (identity.get("displayName") or "")).lower()
    return any(tag.lower() in blob for tag in my_identities() if tag.strip())


def student_id_from_email(email):
    """'100004@school...' -> '100004'. Returns email unchanged if no '@'."""
    return email.split("@")[0] if email and "@" in email else (email or "")


def short_id(name, email):
    """Domain-agnostic short identifier for the right-hand matrix.

    Splits on the first '@' of whichever string carries the domain (email
    preferred, else the display name). Works for any school domain, e.g.
    '100002@school.ed.jp' -> '100002'. No domain is ever hardcoded.
    """
    for s in (email, name):
        if s and "@" in s:
            return s.split("@", 1)[0]
    return (name or email or "").strip()


def pick_student(f):
    """Resolve the student identity for a file from its owner metadata.

    Google Classroom assigns each turned-in file an owner whose email prefix is
    the student's numeric ID (e.g. '100004@school.ed.jp'). Normally we take
    owners[0].emailAddress, split on '@', and use the leading prefix as both the
    Student ID and the display name.

    BUT: when the whole assignment is imported via a Class folder that *you*
    (the teacher) shared from your school account to your personal Gmail, Drive
    reports YOU as the owner of every student file. In that case owners[0] is
    useless, so we fall back to the identity of whoever actually uploaded/shared
    the file in the Classroom ecosystem:

        owners[0]  ->  sharingUser  ->  lastModifyingUser  ->  permissions

    skipping any identity that is the teacher (see MY_IDENTITIES / is_me). The
    return signature is unchanged — (student_id, email) — so both the
    per-assignment and the whole-class import paths emit the identical CSV the
    downstream dashboard expects.

    Returns (student_id, email).
    """
    # 1) Authoritative owner — but only if it isn't the teacher.
    for owner in (f.get("owners") or []):
        if owner and not is_me(owner):
            email = owner.get("emailAddress", "") or ""
            sid = student_id_from_email(email)
            if sid:
                return (sid, email)

    # 2) Owner is the teacher (shared-folder import). Recover the real student
    #    from the user who shared the file, then who last modified it.
    for cand in (f.get("sharingUser"), f.get("lastModifyingUser")):
        if cand and not is_me(cand):
            email = cand.get("emailAddress", "") or ""
            sid = student_id_from_email(email)
            if sid:
                return (sid, email)

    # 3) Last resort: scan the file's permission list for a non-teacher member
    #    whose email prefix yields a student ID (e.g. "100004@school...").
    for perm in (f.get("permissions") or []):
        if perm and not is_me(perm):
            email = perm.get("emailAddress", "") or ""
            sid = student_id_from_email(email)
            if sid:
                return (sid, email)

    return ("Unknown student", "")


def student_key(name, email):
    """Stable key for grouping/persisting a student across reloads."""
    if email:
        return "email:" + email.strip().lower()
    return "name:" + (name or "Unknown student").strip().lower()


def parse_time(s):
    """Parse an RFC3339 timestamp ('2024-06-01T12:34:56.789Z') -> datetime."""
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def file_recency(f):
    """Most-recent timestamp for a file (newest of modified/created)."""
    times = [t for t in (parse_time(f.get("modifiedTime")),
                          parse_time(f.get("createdTime"))) if t]
    if times:
        return max(times)
    return datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)


# --- Optional: mark likely older re-uploads within a single student's stack ---
_COPY_SUFFIX_RE = re.compile(
    r"""(?ix)(?:\s*\(\d+\)|\s*-\s*\d+|\s*_v\d+|\s*\bcopy\b|\s*\bdraft\b|\s*\bfinal\b)+$"""
)


def normalized_base(name):
    """Filename reduced to its base structure (extension + re-upload markers
    stripped) — used only to *mark* likely older drafts inside one student's
    stack. Never used to delete or hide anything."""
    base = (name or "").rsplit(".", 1)[0].strip().lower()
    prev = None
    while prev != base:
        prev = base
        base = _COPY_SUFFIX_RE.sub("", base).strip()
    return base or (name or "").strip().lower()


def embed_url_for(file_id, kind):
    if kind == "slides":
        return f"https://docs.google.com/presentation/d/{file_id}/embed"
    if kind == "doc":
        return f"https://docs.google.com/document/d/{file_id}/preview"
    if kind == "sheet":
        return f"https://docs.google.com/spreadsheets/d/{file_id}/preview"
    if kind == "drawing":
        return f"https://docs.google.com/drawings/d/{file_id}/preview"
    return None


def fetch_folder(folder_id):
    """Fetch folder name + all child files with owner/sharing metadata."""
    service = get_service()

    folder_name = "Assignment"
    try:
        meta = service.files().get(
            fileId=folder_id,
            fields="id,name",
            supportsAllDrives=True,
        ).execute()
        folder_name = meta.get("name") or folder_name
    except HttpError as e:
        raise RuntimeError(
            f"Could not open folder '{folder_id}'. Check the ID and that it is "
            f"shared with this Google account. ({e})"
        )

    files = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        resp = service.files().list(
            q=query,
            spaces="drive",
            fields=("nextPageToken, files(id, name, mimeType, thumbnailLink, "
                    "webViewLink, webContentLink, "
                    "owners(displayName, emailAddress), "
                    "sharingUser(displayName, emailAddress), "
                    "lastModifyingUser(displayName, emailAddress), "
                    "permissions(emailAddress, displayName, role), "
                    "imageMediaMetadata(width,height), "
                    "videoMediaMetadata(width,height,durationMillis), "
                    "createdTime, modifiedTime)"),
            pageSize=200,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            orderBy="name_natural",
        ).execute()
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return folder_name, files


def group_by_student(files, saved):
    """Group files by Student Owner into a nested structure.

    Returns an ordered list of student dicts:
        {key, name, email, count, grade, keywords, comment, graded,
         files: [ {id, filename, kind, flagged, has_thumb, web_view,
                   embed_url, time}, ... newest first ]}
    Nothing is dropped; every file is retained under its student.
    """
    # Annotate + bucket by student.
    buckets = {}
    for f in files:
        name, email = pick_student(f)
        f["_student"], f["_email"] = name, email
        f["_kind"] = classify(f.get("mimeType", ""), f.get("name", ""))
        f["_time"] = file_recency(f)
        f["_base"] = normalized_base(f.get("name"))
        buckets.setdefault(student_key(name, email), []).append(f)

    students = {}
    for key, flist in buckets.items():
        flist.sort(key=lambda x: x["_time"], reverse=True)   # newest first

        # Mark likely older re-uploads (same student + same base name as a newer
        # file). Purely informational — shown as a small "draft?" chip.
        seen_base = {}
        for f in flist:                          # already newest-first
            b = f["_base"]
            f["_flagged"] = b in seen_base
            seen_base[b] = True

        name = flist[0]["_student"]
        email = flist[0]["_email"]
        prev = saved.get(key, {})
        students[key] = {
            "key": key,
            "name": name,
            "email": email,
            "display_id": short_id(name, email),
            "count": len(flist),
            # Per-criterion grades, e.g. {"A": "7", "C": "5"}. Empty until graded.
            "grades": dict(prev.get("grades", {})),
            "keywords": prev.get("keywords", []),
            "comment": prev.get("comment", ""),
            "graded": prev.get("graded", False),
            # None = no explicit late decision yet (frontend defaults it from the
            # deadline); True/False = teacher's persisted Late checkbox override.
            "late_marked": prev.get("late_marked", None),
            # True once the teacher hand-set Late (tick/waive): sticky against
            # deadline re-derivation. Absent/false = auto-derived.
            "late_manual": prev.get("late_manual", False),
            # Criteria whose band CAM changed since the last export (MODIFIED
            # marker); api_load extends this after the CAM reconcile.
            "cam_modified": prev.get("cam_modified", []),
            "files": [{
                "id": f["id"],
                "filename": f.get("name", "(unnamed)"),
                "kind": f["_kind"],
                "flagged": f["_flagged"],
                "has_thumb": bool(f.get("thumbnailLink")),
                "web_view": f.get("webViewLink"),
                "embed_url": embed_url_for(f["id"], f["_kind"]),
                # Original upload time — used by the frontend for late detection.
                "created_time": (parse_time(f.get("createdTime")).isoformat()
                                 if parse_time(f.get("createdTime")) else None),
                # Video assets carry BOTH the lightweight static thumbnail
                # (poster, served by /api/thumbnail) AND a stream source. We
                # stream through our own authenticated, Range-capable proxy
                # because the raw webContentLink is not browser-authenticated.
                "is_video": f["_kind"] == "video",
                "video_src": ("/api/video/" + f["id"]) if f["_kind"] == "video" else None,
                "web_content": f.get("webContentLink") if f["_kind"] == "video" else None,
                "time": f["_time"].isoformat(),
            } for f in flist],
        }

    # Stable order for the right-side matrix: by student name.
    ordered = sorted(students.values(), key=lambda s: s["name"].lower())
    return students, ordered


# -----------------------------------------------------------------------------
# Pair-work groups (left-panel partner links; right matrix stays stationary)
# -----------------------------------------------------------------------------
GROUP_COLORS = ["#e0843a", "#3aa0e0", "#37c97a", "#b56ad0",
                "#d0556a", "#caa23a", "#2bb8b0", "#7d8cf0"]


def _gen_group_id():
    return "g" + datetime.datetime.now().strftime("%H%M%S%f")


def _find_group(key):
    for g in STATE["groups"]:
        if key in g.get("members", []):
            return g
    return None


def _group_members(key):
    """All student keys linked to `key` (including itself), or None if ungrouped."""
    g = _find_group(key)
    return list(g["members"]) if g else None


def _ordered_students():
    return sorted(STATE["students"].values(), key=lambda s: s["name"].lower())


# -----------------------------------------------------------------------------
# Anonymous grading — a display-only bias-reduction layer over the payload
# -----------------------------------------------------------------------------
# When the device pref is on, the JSON handed to the front end swaps every
# identity-bearing DISPLAY string — student name / id / email / filename — for
# neutral "Work NN" / "Image N" labels, and orders students by a seeded shuffle
# (seed = the durable state key) so the same student isn't always graded first.
# The ROUND-TRIP identifiers (student key, file id, web_view/embed_url, grades
# keyed by key) are never touched, so save, restart-persistence and export stay
# byte-identical and real — api_export reads STATE directly and never sees this
# layer. Nothing here mutates STATE: each student/file dict is copied before its
# display strings are overwritten. Anonymity is bias-reduction, not blind review
# (the student key still embeds the real id for the round-trip; the "↗ open" link
# still serves the real file) — see the plan's T7.
_ANON_FILE_NOUN = {
    "image": "Image", "video": "Video", "pdf": "Document", "doc": "Document",
    "slides": "Slides", "sheet": "Sheet", "drawing": "Drawing",
}


def _anon_plan(seed):
    """(ordered student keys, {key: "Work NN"}) for a seeded shuffle of the loaded
    assignment. Keys are sorted first so the shuffle is reproducible regardless of
    dict / file iteration order — stable across reloads, different per assignment."""
    order = sorted(STATE["students"].keys())
    random.Random(str(seed)).shuffle(order)
    labels = {k: f"Work {i + 1:02d}" for i, k in enumerate(order)}
    return order, labels


def _anonymize_student(st, label):
    """A display-only copy of a student dict with identity stripped. Copies the
    dict and each file dict so STATE (shared with export/save) is never touched;
    overwrites only the display strings, leaving key / id / web_view / grades."""
    c = dict(st)
    c["name"] = label
    c["display_id"] = label
    c["email"] = ""                       # the email carries the numeric student id
    c["files"] = [
        {**f, "filename": f"{_ANON_FILE_NOUN.get(f.get('kind'), 'File')} {i}"}
        for i, f in enumerate(st.get("files", []), start=1)
    ]
    return c


def present_students():
    """The ordered student list for a payload: seeded-shuffled + anonymized when
    the device pref is on, else today's alphabetical order (byte-identical)."""
    if not anonymous_enabled():
        return sorted(STATE["students"].values(), key=lambda s: s["name"].lower())
    order, labels = _anon_plan(STATE.get("folder_id") or "")
    return [_anonymize_student(STATE["students"][k], labels[k]) for k in order]


def present_student(key):
    """Single-student presentation (the api_save response): an anonymized copy
    when the pref is on, else the real STATE dict (today's behaviour)."""
    st = STATE["students"].get(key)
    if st is None or not anonymous_enabled():
        return st
    _, labels = _anon_plan(STATE.get("folder_id") or "")
    return _anonymize_student(st, labels.get(key, "Work"))


def _sync_group_grades(anchor_key):
    """Make every partner in a group share one grade/keywords/comment.

    Source = the anchor if it's already graded, otherwise the first graded
    member, otherwise the anchor. Keeps newly-linked partners consistent.
    """
    g = _find_group(anchor_key)
    if not g:
        return
    members = [m for m in g["members"] if m in STATE["students"]]
    if not members:
        return
    src_key = anchor_key
    if not STATE["students"][anchor_key].get("graded"):
        graded = next((m for m in members
                       if STATE["students"][m].get("graded")), None)
        if graded:
            src_key = graded
    src = STATE["students"][src_key]
    for m in members:
        tst = STATE["students"][m]
        tst["grades"] = dict(src.get("grades", {}))
        tst["keywords"] = list(src.get("keywords", []))
        tst["comment"] = src.get("comment", "")
        tst["late_marked"] = src.get("late_marked")
        tst["late_manual"] = src.get("late_manual", False)
        tst["graded"] = bool(tst["grades"])


# -----------------------------------------------------------------------------
# Storage providers — the seam between Drive-backed and local-folder assignments
# -----------------------------------------------------------------------------
# The marking viewer sources student files from one of two backends, chosen at
# load time by whether api_load's reference is a Drive folder ID or a local
# filesystem path (mirrors the CAM Streamlit side's _master_is_local()). Both
# return the SAME (folder_name, files) shape fetch_folder returns today, so
# group_by_student and the entire front end stay backend-agnostic. The chosen
# backend is recorded in STATE["source"] so the stateless /api/thumbnail and
# /api/video routes reuse it. Phase 1 wires DriveProvider (no behaviour change)
# and stubs LocalProvider; Phase 3 fills LocalProvider in.
class DriveProvider:
    """Google Drive backend — the original marking-viewer behaviour, unchanged."""
    name = "drive"

    def fetch_folder(self, folder_id):
        """(folder_name, [file-dict]) for an assignment subfolder — see fetch_folder()."""
        return fetch_folder(folder_id)

    def state_key(self, ref):
        """Durable persistence key for the loaded reference. A Drive folder ID is
        already stable, so it IS the key (grades_<id>.json / cache entry)."""
        return ref

    def download(self, file_id):
        """Never used for Drive: Drive tiles carry a real webViewLink, so the
        frontend's "↗ open" link points at Google, not at /api/download."""
        abort(404)

    def thumbnail(self, file_id, sz):
        """Proxy a Drive thumbnail through the authenticated session.

        Optional sz bumps the requested thumbnail size for the zoom overlay.
        """
        try:
            service = get_service()
            meta = service.files().get(
                fileId=file_id,
                fields="thumbnailLink,mimeType",
                supportsAllDrives=True,
            ).execute()
        except HttpError:
            abort(404)

        link = meta.get("thumbnailLink")
        if not link:
            abort(404)

        if sz:
            if re.search(r"=s\d+", link):
                link = re.sub(r"=s\d+", f"=s{sz}", link)
            elif re.search(r"=w\d+-h\d+", link):
                link = re.sub(r"=w\d+-h\d+", f"=s{sz}", link)
            else:
                link = link + f"=s{sz}"

        try:
            session = AuthorizedSession(get_credentials())
            r = session.get(link)
            if r.status_code != 200:
                abort(404)
            ctype = r.headers.get("Content-Type", "image/jpeg")
            return Response(r.content, mimetype=ctype,
                            headers={"Cache-Control": "private, max-age=300"})
        except Exception:
            abort(404)

    def pdf(self, file_id):
        """Download a Drive PDF through the authenticated session and serve it
        inline for the focused viewer's native <iframe> engine.

        Cached to disk keyed by file id + modifiedTime, so re-opening the same
        document is instant and a re-upload (fresh modifiedTime) invalidates the
        stale copy automatically. Credentials never reach the browser.
        """
        try:
            service = get_service()
            meta = service.files().get(
                fileId=file_id,
                fields="modifiedTime,name",
                supportsAllDrives=True,
            ).execute()
        except HttpError:
            abort(404)

        cache_path = _pdf_cache_path(file_id, meta.get("modifiedTime", ""))
        if not os.path.exists(cache_path):
            url = (f"https://www.googleapis.com/drive/v3/files/{file_id}"
                   f"?alt=media&supportsAllDrives=true")
            try:
                session = AuthorizedSession(get_credentials())
                r = session.get(url)
            except Exception:
                abort(502)
            if r.status_code != 200:
                abort(r.status_code
                      if r.status_code in (401, 403, 404) else 502)
            try:
                os.makedirs(PDF_CACHE_DIR, exist_ok=True)
                tmp = cache_path + ".tmp"
                with open(tmp, "wb") as fh:
                    fh.write(r.content)
                os.replace(tmp, cache_path)   # atomic publish
            except Exception:
                # Caching is best-effort — serve the bytes directly if the disk
                # write fails so the viewer still opens.
                return Response(
                    r.content, mimetype="application/pdf",
                    headers={"Content-Disposition": "inline",
                             "Cache-Control": "private, max-age=300"})

        resp = send_file(cache_path, mimetype="application/pdf",
                         conditional=True)
        resp.headers["Content-Disposition"] = "inline"
        resp.headers["Cache-Control"] = "private, max-age=300"
        return resp

    def video(self, file_id, range_header):
        """Stream a Drive video through the authenticated session.

        Forwards the browser's HTTP Range header to Drive and relays the partial
        (206) response, so the native <video> element can play, seek and scrub
        the timeline smoothly without ever exposing credentials to the browser.
        """
        url = (f"https://www.googleapis.com/drive/v3/files/{file_id}"
               f"?alt=media&supportsAllDrives=true")
        fwd = {}
        if range_header:
            fwd["Range"] = range_header

        try:
            session = AuthorizedSession(get_credentials())
            upstream = session.get(url, headers=fwd, stream=True)
        except Exception:
            abort(502)

        if upstream.status_code not in (200, 206):
            # Surface auth/permission/not-found cleanly; otherwise a bad gateway.
            abort(upstream.status_code
                  if upstream.status_code in (401, 403, 404) else 502)

        resp_headers = {
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, max-age=300",
        }
        for h in ("Content-Length", "Content-Range"):
            if h in upstream.headers:
                resp_headers[h] = upstream.headers[h]
        ctype = upstream.headers.get("Content-Type", "video/mp4")

        def generate():
            try:
                for chunk in upstream.iter_content(chunk_size=262144):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        return Response(generate(), status=upstream.status_code,
                        headers=resp_headers, mimetype=ctype)


def _local_mime(path):
    """Best-effort MIME from a file extension, for classify()/has_thumb.

    Only the coarse family matters downstream: classify() keys PDFs off
    'application/pdf', images off 'image/', videos off 'video/' or the name's
    extension, and everything else falls through to the office/other placeholder.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return "application/pdf"
    if ext in exam_engine.IMAGE_EXTS:
        return "image/" + ext.lstrip(".")
    if ext in VIDEO_EXTS:
        return "video/" + ext.lstrip(".")
    return "application/octet-stream"


def _thumb_cache_path(path, width, mtime):
    """Cache filename for one LocalProvider thumbnail, keyed by path + mtime +
    width so a re-saved source (new mtime) or a different requested size never
    reuses a stale render."""
    key = hashlib.sha1(
        os.path.normcase(os.path.abspath(path)).encode("utf-8")).hexdigest()[:16]
    return os.path.join(THUMB_CACHE_DIR, f"{key}__{mtime}__{width}.png")


class LocalProvider:
    """Local-folder backend: a filesystem class-assignment folder graded through
    the exact same marking viewer as a Drive assignment.

    fetch_folder() returns fetch_folder()-shaped file dicts (synthesised owner =
    the student identity, mimeType from the extension, timestamps from the file
    mtime) so group_by_student and the whole front end stay backend-agnostic.
    Per-file IDs are opaque, URL-safe and deterministic (a hash of the absolute
    path); an in-session registry maps id -> absolute path for the stateless
    media routes. The served base is the loaded folder — a containment check
    (os.path.commonpath, not str.startswith) guards every file access. No Google
    import is ever touched on this path, so it works with token.json renamed away.

    Supports PDFs and images (first-page/LANCZOS thumbnails via exam_engine);
    video streams straight from disk (no Drive bandwidth concern locally) and
    office/other files fall back to a placeholder tile plus a download link.
    """
    name = "local"

    def __init__(self):
        self._registry = {}   # opaque file id -> absolute path (rebuilt per load)
        self._base = None     # loaded assignment folder = the containment root

    # --- keys & identity -----------------------------------------------------
    def state_key(self, ref):
        """Durable persistence key: a stable slug of the normalised absolute path
        so grades_<key>.json and the grading_cache.json entry survive restarts
        (and path-normalisation differences). CAM's Phase 4 derives the same
        slug, keeping cam_grades_<key>.json aligned."""
        norm = os.path.normcase(os.path.abspath(ref))
        return "local-" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]

    def _register(self, path):
        ap = os.path.abspath(path)
        fid = "lf-" + hashlib.sha1(
            os.path.normcase(ap).encode("utf-8")).hexdigest()[:16]
        self._registry[fid] = ap
        return fid

    def _contained(self, target):
        """True only if `target` sits inside the loaded folder. Uses commonpath
        (not startswith, which would accept a sibling '..._evil' prefix)."""
        if not self._base:
            return False
        try:
            base = os.path.normcase(os.path.abspath(self._base))
            tgt = os.path.normcase(os.path.abspath(target))
            return os.path.commonpath([base, tgt]) == base
        except (ValueError, TypeError):
            return False   # different drives, or bad input

    def _resolve(self, file_id):
        """Registry lookup + containment guard; None if unknown or escaped."""
        path = self._registry.get(file_id)
        if not path or not self._contained(path) or not os.path.isfile(path):
            return None
        return path

    # --- folder listing ------------------------------------------------------
    def fetch_folder(self, ref):
        """Enumerate a local assignment folder into fetch_folder()-shaped dicts.

        Student identity convention (mirrors Google Classroom's local layout):
        a subfolder per student when the assignment folder contains subfolders
        (subfolder name = student), else the filename stem = student.
        """
        base = os.path.abspath(ref)
        if not os.path.isdir(base):
            raise RuntimeError(f"Local assignment folder not found: {ref}")
        self._base = base
        self._registry = {}
        folder_name = os.path.basename(base.rstrip("\\/")) or base

        try:
            entries = sorted(os.scandir(base), key=lambda e: e.name)
        except OSError as e:
            raise RuntimeError(f"Cannot read local folder {ref!r}: {e}")

        subdirs = [e for e in entries if e.is_dir()]
        files = []
        if subdirs:
            # Subfolder-per-student: each immediate subdirectory is one student;
            # collect every file beneath it (nested submissions kept, not dropped).
            for d in subdirs:
                for path in self._walk_files(d.path):
                    files.append(self._file_dict(path, d.name))
        else:
            # Flat layout: filename stem = student (the exam-engine convention).
            for e in entries:
                if e.is_file() and not e.name.startswith("."):
                    student = os.path.splitext(e.name)[0]
                    files.append(self._file_dict(e.path, student))
        return folder_name, files

    @staticmethod
    def _walk_files(dirpath):
        out = []
        for root, dirs, names in os.walk(dirpath):
            dirs.sort()
            for n in sorted(names):
                if n.startswith("."):
                    continue
                out.append(os.path.join(root, n))
        return out

    def _file_dict(self, path, student):
        """One fetch_folder()-shaped dict for a local file."""
        file_id = self._register(path)
        mime = _local_mime(path)
        try:
            ts = datetime.datetime.fromtimestamp(
                os.path.getmtime(path)).isoformat(timespec="seconds")
        except OSError:
            ts = ""
        kind = classify(mime, os.path.basename(path))
        d = {
            "id": file_id,
            "name": os.path.basename(path),
            "mimeType": mime,
            # Synthesise the owner so pick_student() resolves the student from the
            # subfolder name / filename stem exactly as it reads a Drive owner
            # email — the emitted CSV's Student Name is then shaped identically.
            "owners": [{"displayName": student, "emailAddress": student}],
            # Lateness comes from the file mtime (when the file was saved/copied
            # locally, not necessarily when the student submitted — the teacher
            # corrects with the sticky Late tick). Both timestamps feed the
            # existing late derivation unchanged; naive-local ISO matches the
            # datetime-local deadline.
            "createdTime": ts,
            "modifiedTime": ts,
            # Every local file gets a download/open link (the "↗ open" tile
            # affordance). PDFs/images also open inline; video and office/other
            # rely on it since they carry no inline thumbnail.
            "webViewLink": "/api/download/" + file_id,
        }
        # thumbnailLink only needs to be TRUTHY: group_by_student reads it as
        # has_thumb, and the frontend builds the real src from the file id. Set
        # it for renderable types only, so video/office fall to the placeholder.
        if kind in ("pdf", "image"):
            d["thumbnailLink"] = "/api/thumbnail/" + file_id
        return d

    # --- media routes --------------------------------------------------------
    def _thumb_png(self, path, width):
        """PNG bytes of a PDF first page / image, downscaled to `width`, disk-cached."""
        try:
            mtime = int(os.path.getmtime(path))
        except OSError:
            mtime = 0
        cache_path = _thumb_cache_path(path, width, mtime)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "rb") as fh:
                    return fh.read()
            except OSError:
                pass
        # exam_engine rasterises a PDF's first page (PyMuPDF) or opens an image,
        # then LANCZOS-downscales to max_width — the same pipeline exam slicing
        # uses for its browser previews.
        png = exam_engine.page_png_bytes(path, 1, max_width=width)
        try:
            os.makedirs(THUMB_CACHE_DIR, exist_ok=True)
            tmp = cache_path + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(png)
            os.replace(tmp, cache_path)      # atomic publish
        except OSError:
            pass                             # caching is best-effort
        return png

    def thumbnail(self, file_id, sz):
        path = self._resolve(file_id)
        if not path:
            abort(404)
        width = sz if (sz and sz > 0) else THUMB_GRID_WIDTH
        width = max(64, min(width, THUMB_MAX_WIDTH))
        try:
            png = self._thumb_png(path, width)
        except Exception:
            abort(404)                       # e.g. PyMuPDF missing / unreadable
        return Response(png, mimetype="image/png",
                        headers={"Cache-Control": "private, max-age=300"})

    def pdf(self, file_id):
        path = self._resolve(file_id)
        if not path:
            abort(404)
        resp = send_file(path, mimetype="application/pdf", conditional=True)
        resp.headers["Content-Disposition"] = "inline"
        resp.headers["Cache-Control"] = "private, max-age=300"
        return resp

    def video(self, file_id, range_header):
        path = self._resolve(file_id)
        if not path:
            abort(404)
        # Straight disk stream; send_file(conditional=True) provides HTTP Range so
        # the native <video> element can seek. Local files have no Drive-bandwidth
        # concern, so serving them beats a dead placeholder.
        return send_file(path, conditional=True)

    def download(self, file_id):
        path = self._resolve(file_id)
        if not path:
            abort(404)
        # Inline where the browser can (PDF/image/video); office/other download.
        return send_file(path, as_attachment=False, conditional=True)


DRIVE_PROVIDER = DriveProvider()
LOCAL_PROVIDER = LocalProvider()


def _ref_is_local(ref):
    """Local path when it exists on disk or carries path separators; anything
    else is a Google Drive folder ID. Mirrors CAM's _master_is_local(). The
    reference here has already been through _extract_folder_id, so a Drive URL
    is a bare ID (no separators) by the time we test it."""
    ref = (ref or "").strip()
    if not ref:
        return False
    if os.path.isdir(ref):
        return True
    return any(sep in ref for sep in ("\\", "/", ":"))


def provider_for(ref):
    """Pick the storage backend for a freshly-loaded reference."""
    return LOCAL_PROVIDER if _ref_is_local(ref) else DRIVE_PROVIDER


def current_provider():
    """The backend behind the loaded assignment — for the stateless media routes."""
    return LOCAL_PROVIDER if STATE.get("source") == "local" else DRIVE_PROVIDER


def _pdf_cache_path(file_id, modified_time):
    """Cache filename for a Drive PDF, keyed by file id + modifiedTime.

    Both parts are reduced to a filesystem-safe token; the modifiedTime digits
    make the key change whenever the student re-uploads, so a stale cache never
    shadows a newer submission.
    """
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", file_id or "")
    safe_mt = re.sub(r"[^0-9]", "", modified_time or "") or "0"
    return os.path.join(PDF_CACHE_DIR, f"{safe_id}__{safe_mt}.pdf")


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html")


@app.route("/signin")
def signin():
    """One-time Google sign-in bootstrap (opened by CAM's 🔗 Connect button).

    CAM's Watch needs token.json before any assignment row exists, but the
    OAuth flow otherwise only runs when a grading route first touches Drive —
    and the grading buttons only appear on rows Watch creates. This route
    breaks that loop by running get_credentials() (which writes token.json)
    on demand."""
    if not find_client_secret():
        return Response(
            "<html><body style='font-family:sans-serif;max-width:40em;"
            "margin:4em auto'>"
            "<h2>Google sign-in not ready</h2>"
            "<p>No OAuth client-secret file was found. In the "
            "<a href='https://console.cloud.google.com/apis/credentials'>"
            "Google Cloud Console</a>, create an OAuth client of type "
            "“Desktop app”, download its JSON and save it as "
            "<code>credentials.json</code> (or <code>client_secret_*.json"
            "</code>) in <code>cam_grading_workspace/</code>, then click "
            "\U0001F517 Connect Google Drive in CAM again.</p>"
            "</body></html>",
            mimetype="text/html")
    get_credentials()
    return Response(
        "<html><body style='font-family:sans-serif;max-width:40em;"
        "margin:4em auto'>"
        "<h2>Google Drive connected ✔</h2>"
        "<p>The sign-in token was saved. You can close this tab and return "
        "to CAM — \U0001F441 Watch can now list your Drive class "
        "folders.</p>"
        "</body></html>",
        mimetype="text/html")


def _extract_folder_id(raw):
    """Accept a bare ID or a full Drive URL and return the folder ID."""
    raw = (raw or "").strip()
    m = re.search(r"/folders/([A-Za-z0-9_-]+)", raw)
    return m.group(1) if m else raw


def fetch_subfolders(class_folder_id):
    """Return (class_folder_name, [{id, name}, ...]) of assignment subfolders.

    Lists only child items whose mimeType is a Drive folder, sorted by name, so
    the frontend can present them in an assignment <select>.
    """
    service = get_service()
    try:
        meta = service.files().get(
            fileId=class_folder_id, fields="id,name", supportsAllDrives=True,
        ).execute()
        class_name = meta.get("name") or "Class"
    except HttpError as e:
        raise RuntimeError(
            f"Could not open class folder '{class_folder_id}'. Check the ID and "
            f"that it is shared with this Google account. ({e})"
        )

    subfolders = []
    page_token = None
    query = (f"'{class_folder_id}' in parents and trashed = false "
             f"and mimeType = 'application/vnd.google-apps.folder'")
    while True:
        resp = service.files().list(
            q=query, spaces="drive",
            fields="nextPageToken, files(id, name)",
            pageSize=200, pageToken=page_token,
            includeItemsFromAllDrives=True, supportsAllDrives=True,
            orderBy="name_natural",
        ).execute()
        subfolders.extend({"id": f["id"], "name": f.get("name", "(unnamed)")}
                          for f in resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return class_name, subfolders


def local_subfolders(class_folder_path):
    """Return (class_folder_name, [{id, name}, ...]) of assignment subfolders on
    disk — the local mirror of :func:`fetch_subfolders`.

    Each ``id`` is the subfolder's absolute path, opaque to the client and
    matched verbatim against the CAM-bridge target (CAM stamps the same
    ``os.path.abspath`` folder_ref onto its assignment rows in
    ``_watch_class_master``), so the local class dropdown resolves an assignment
    exactly as the Drive one resolves a folder ID. PDFs/images/video are graded
    once one is opened (LocalProvider); this only enumerates the folder tree.
    """
    base = os.path.abspath(class_folder_path)
    if not os.path.isdir(base):
        raise RuntimeError(f"Local class folder not found: {base}")
    subs = [{"id": os.path.abspath(e.path), "name": e.name}
            for e in sorted(os.scandir(base), key=lambda e: e.name)
            if e.is_dir()]
    return (os.path.basename(base.rstrip("\\/")) or base), subs


@app.route("/api/class", methods=["POST"])
def api_class():
    """List assignment subfolders inside a parent Class Folder.

    Drive class folders list through the Drive API; a **local class master
    path** (mirroring CAM's local-master convention, PDF/local-mode plan
    Phase 4) is enumerated straight off disk with no OAuth, so a teacher with
    no Google Workspace gets the same assignment dropdown."""
    data = request.get_json(force=True, silent=True) or {}
    raw = (data.get("class_folder_id") or "").strip()
    if not raw:
        return jsonify({"error": "Please provide a Class Folder ID."}), 400
    is_local = _ref_is_local(raw)
    class_folder_id = raw if is_local else _extract_folder_id(raw)
    try:
        if is_local:
            class_name, subfolders = local_subfolders(class_folder_id)
        else:
            class_name, subfolders = fetch_subfolders(class_folder_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    if not subfolders:
        return jsonify({
            "error": f"No assignment subfolders found inside '{class_name}'. "
                     f"This folder should contain one subfolder per assignment."
        }), 404
    return jsonify({
        "class_folder_id": class_folder_id,
        "class_folder_name": class_name,
        "assignments": subfolders,
    })


@app.route("/api/load", methods=["POST"])
def api_load():
    data = request.get_json(force=True, silent=True) or {}
    ref = _extract_folder_id(data.get("folder_id"))
    class_folder_id = _extract_folder_id(data.get("class_folder_id"))
    class_name = (data.get("class_name") or "").strip()

    if not ref:
        return jsonify({"error": "Please provide a Google Drive folder ID "
                                 "or a local assignment folder path."}), 400

    # Set the active class up-front so the per-class output dir (and therefore
    # the grades/cache file paths we read below) resolve correctly.
    STATE["class_name"] = class_name or None

    # Pick the storage backend from the reference shape (Drive ID vs local path).
    provider = provider_for(ref)
    try:
        folder_name, files = provider.fetch_folder(ref)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    # Durable persistence key: a Drive folder ID is already stable and IS the
    # key; a local path is reduced to a stable slug so grades_<key>.json and the
    # grading_cache.json entry survive an app restart. Everything below keys on
    # this, so the local and Drive paths persist identically.
    folder_id = provider.state_key(ref)

    if not files:
        return jsonify({
            "error": f"The folder '{folder_name}' is empty (no files found). "
                     f"Make sure it contains the artwork and is shared with you."
        }), 404

    # Restore where you left off: legacy per-folder file first, then the
    # background cache (which wins, as it is the live autosave target).
    saved = load_saved_grades(folder_id)
    (cache_grades, cache_groups, cache_checklist, cache_criteria,
     cache_deadline, cam_extra, cache_cam_name) = load_cache_entry(folder_id)
    saved.update(cache_grades)
    students, ordered = group_by_student(files, saved)

    # Reconcile CAM's published grades (written at every dashboard handoff —
    # CAM is the source of truth, so its values are the latest the teacher
    # entered anywhere). Any band that differs from our saved state was
    # changed in CAM since our last export: adopt it and flag the student
    # MODIFIED so the teacher re-checks the checklist (CAM only carries the
    # final 0-8 band, not the checklist detail behind it). CAM-graded students
    # with no files in this folder become cam_extra — not gradable here, but
    # carried into every export so a Sync can never drop their marks.
    # CAM's current display name for this folder rides in the same published
    # file (written at every handoff). Adopt it as the export name so a rename
    # in CAM propagates here; fall back to the last-known cached name on a plain
    # manual load (no fresh handoff), never clobbering it with None.
    cam_name = load_cam_published_name(folder_id) or cache_cam_name
    cam = load_cam_published(folder_id)
    if cam is not None:
        matched = set()
        for st in students.values():
            sid = student_id_from_email(st.get("email")) or (st.get("name") or "")
            pub = cam.get(sid)
            if not pub:
                continue
            matched.add(sid)
            changed = [c for c in MYP_CRITERIA
                       if c in pub["grades"]
                       and pub["grades"][c] != str(st["grades"].get(c, ""))]
            for c in changed:
                st["grades"][c] = pub["grades"][c]
            if changed:
                st["graded"] = True
                st["cam_modified"] = sorted(set(st["cam_modified"]) | set(changed))
            # A CAM-edited comment is also the newest value; blank means CAM
            # holds none — never an instruction to clear ours.
            if pub["comment"] and pub["comment"] != st.get("comment", ""):
                st["comment"] = pub["comment"]
        # The published file is CAM's full current snapshot for this folder,
        # so the folderless leftovers replace any previously cached extras.
        cam_extra = {sid: rec for sid, rec in cam.items() if sid not in matched}
        # Surface CAM-held bands even if their criterion isn't ticked yet
        # (e.g. the cache was cleared) — the matrix column must exist for the
        # MODIFIED cell to be visible.
        pub_crits = {c for rec in cam.values() for c in rec["grades"]}
        cache_criteria = sorted(set(cache_criteria) | pub_crits)

    # Restore the custom rubric headers: the live cache wins; otherwise fall
    # back to the legacy grades file; otherwise [] tells the frontend to use
    # its built-in default checklist template.
    checklist = cache_checklist or load_saved_checklist(folder_id)
    # Recovery: if no checklist was ever saved but students carry keyword marks,
    # reconstruct the rubric from those marks so a lost cache entry doesn't drop
    # the teacher's custom criteria back to the generic defaults.
    if not checklist:
        derived = derive_checklist_from_saved(saved)
        if derived:
            checklist = derived
    criteria = cache_criteria
    deadline = cache_deadline

    # Keep only cached groups whose members still exist in this folder, and
    # drop any group that no longer has at least two real partners.
    valid = set(students.keys())
    groups = []
    for g in cache_groups:
        members = [m for m in (g.get("members") or []) if m in valid]
        if len(members) >= 2:
            groups.append({"id": g.get("id") or _gen_group_id(),
                           "members": members,
                           "color": g.get("color") or GROUP_COLORS[len(groups) % len(GROUP_COLORS)]})

    with STATE_LOCK:
        STATE["class_folder_id"] = class_folder_id or STATE.get("class_folder_id")
        STATE["class_name"] = class_name or None
        STATE["folder_id"] = folder_id
        STATE["folder_name"] = folder_name
        STATE["source"] = provider.name
        STATE["cam_name"] = cam_name
        STATE["students"] = students
        STATE["groups"] = groups
        STATE["checklist"] = checklist
        STATE["criteria"] = criteria
        STATE["deadline"] = deadline
        STATE["cam_extra"] = cam_extra
        save_state()
        # Only after the merged state is safely persisted: a stale copy
        # re-read later would overwrite newer marking with old CAM values.
        if cam is not None:
            consume_cam_published(folder_id)

    return jsonify({
        "folder_id": folder_id,
        "folder_name": folder_name,
        # CAM's current display name for this assignment (the export name). The
        # frontend titles the grading header with it so a rename done in CAM
        # shows here, instead of the never-renamed physical Drive folder name.
        "cam_name": cam_name,
        "student_count": len(ordered),
        "file_count": sum(s["count"] for s in ordered),
        "unknown_owner_count": sum(1 for s in ordered if s["name"] == "Unknown student"),
        # Anonymized + seeded-shuffled when the device pref is on; else the same
        # alphabetical `ordered` list. Counts above stay derived from the real
        # `ordered` (order-independent), so anonymity never distorts them.
        "students": present_students(),
        "groups": groups,
        # Saved rubric criteria, or [] -> frontend uses its default template.
        "checklist": checklist,
        # Selected MYP criteria + official deadline (restored from cache).
        "criteria": criteria,
        "deadline": deadline,
    })


@app.route("/api/thumbnail/<file_id>")
def api_thumbnail(file_id):
    """Serve a file's thumbnail via the active storage provider.

    Optional ?sz=NNN bumps the requested thumbnail size for the zoom overlay.
    """
    sz = request.args.get("sz", type=int)
    return current_provider().thumbnail(file_id, sz)


@app.route("/api/video/<file_id>")
def api_video(file_id):
    """Stream a file via the active storage provider (Range-forwarding)."""
    return current_provider().video(file_id, request.headers.get("Range"))


@app.route("/api/pdf/<file_id>")
def api_pdf(file_id):
    """Serve a PDF's raw bytes inline (Content-Type application/pdf) via the
    active storage provider, for the focused viewer's native browser engine."""
    return current_provider().pdf(file_id)


@app.route("/api/download/<file_id>")
def api_download(file_id):
    """Serve a raw file for the "↗ open" / download affordance via the active
    provider. Used by local mode (video + office/other tiles carry no inline
    thumbnail); Drive tiles link to their real webViewLink instead."""
    return current_provider().download(file_id)


@app.route("/api/save", methods=["POST"])
def api_save():
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key")
    with STATE_LOCK:
        st = STATE["students"].get(key)
        if not st:
            return jsonify({"error": "Unknown student key"}), 404
        # Mirror the edit across every linked partner (or just this one student
        # if ungrouped). The right matrix order itself never changes.
        targets = _group_members(key) or [key]
        updated = []
        for tkey in targets:
            tst = STATE["students"].get(tkey)
            if not tst:
                continue
            if "grades" in data and isinstance(data["grades"], dict):
                # Keep only non-empty criterion values, e.g. {"A":"7","C":"5"}.
                tst["grades"] = {str(k): str(v) for k, v in data["grades"].items()
                                 if str(v).strip() != ""}
            if "keywords" in data:
                tst["keywords"] = list(data["keywords"])
            if "comment" in data:
                tst["comment"] = data["comment"]
            if "late_marked" in data:
                tst["late_marked"] = data["late_marked"]
            if "late_manual" in data:
                tst["late_manual"] = bool(data["late_manual"])
            tst["graded"] = bool(tst.get("grades"))
            updated.append(tst)
        # MODIFIED marker (CAM-changed criteria): per-student, not mirrored to
        # partners — dismissing it is a review acknowledgement, not a grade.
        if "cam_modified" in data:
            st["cam_modified"] = _normalize_cam_modified(data["cam_modified"])
        save_state()
        # Present (anonymize when the pref is on) so the front end's Object.assign
        # onto its in-memory rows can't overwrite an anonymized tile with a real
        # name. STATE itself keeps the real values (export/save round-trip).
        return jsonify({"ok": True,
                        "student": present_student(key),
                        "students": [present_student(t["key"]) for t in updated]})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    """Persist the assignment-level setup: selected MYP criteria + deadline.

    Stored under the open folder ID alongside (never replacing) student marks,
    so toggling a criterion or editing the deadline can never wipe a score.
    """
    data = request.get_json(force=True, silent=True) or {}
    with STATE_LOCK:
        if not STATE["folder_id"]:
            return jsonify({"error": "No folder is currently loaded."}), 400
        if "criteria" in data:
            STATE["criteria"] = [c for c in (data.get("criteria") or [])
                                 if c in MYP_CRITERIA]
        if "deadline" in data:
            STATE["deadline"] = (data.get("deadline") or "").strip()
        save_state()
        return jsonify({"ok": True,
                        "criteria": STATE["criteria"],
                        "deadline": STATE["deadline"]})


@app.route("/api/prefs", methods=["GET", "POST"])
def api_prefs():
    """Get or set device-local prefs. Currently just the Anonymous-grading toggle.

    GET  -> {anonymous_grading: bool, token_bootstrap: bool}
    POST {anonymous_grading?: bool, token_bootstrap?: bool} -> persists the given
         keys to local_device_prefs.json and returns the new values. The front end
         reloads the open assignment after an anonymous change so the
         anonymized/real payload is rebuilt. token_bootstrap only takes effect on
         the next OAuth sign-in (it seeds an absent token from the cloud dir).
    """
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        if "anonymous_grading" in data:
            save_prefs({"anonymous_grading": bool(data["anonymous_grading"])})
        if "token_bootstrap" in data:
            save_prefs({"token_bootstrap": bool(data["token_bootstrap"])})
    prefs = load_prefs()
    return jsonify({"anonymous_grading": bool(prefs.get("anonymous_grading")),
                    "token_bootstrap": bool(prefs.get("token_bootstrap"))})


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    """Get or update the app settings: cloud sync dir + class->ID map + identities.

    GET  -> {cloud_dir, classes, my_identities, cloud_dir_exists}
    POST -> persists any of {cloud_dir, classes, my_identities} to
            gcg_settings.json (root + cloud mirror) and returns the saved
            settings. cloud_dir + classes are CAM-managed (seeded by the launch
            bridge); my_identities is the one field the workspace's own Settings
            panel edits, so it saves here too and heals to other machines via the
            cloud mirror.
    """
    global _MY_IDENTITIES_CACHE
    if request.method == "POST":
        data = request.get_json(force=True, silent=True) or {}
        with STATE_LOCK:
            if "cloud_dir" in data:
                SETTINGS["cloud_dir"] = str(data.get("cloud_dir", "") or "").strip()
            if "classes" in data and isinstance(data["classes"], dict):
                SETTINGS["classes"] = {
                    str(k).strip(): str(v).strip()
                    for k, v in data["classes"].items()
                    if str(k).strip() and str(v).strip()
                }
            if "my_identities" in data and isinstance(data["my_identities"], list):
                SETTINGS["my_identities"] = _dedupe_identities(data["my_identities"])
                _MY_IDENTITIES_CACHE = None   # rebuild on next my_identities()
            save_settings()
    cloud = SETTINGS.get("cloud_dir", "").strip()
    return jsonify({
        "cloud_dir": cloud,
        "classes": SETTINGS.get("classes", {}),
        "my_identities": SETTINGS.get("my_identities", []),
        "cloud_dir_exists": bool(cloud and os.path.isdir(cloud)),
    })


@app.route("/api/config/refresh", methods=["POST"])
def api_config_refresh():
    """Force Sync: drop the cached SETTINGS and rescan disk from scratch.

    Rereads the cloud directory's gcg_settings.json AND scans its per-class
    subfolders, so a class created on another device — synced in by
    OneDrive/Drive since this app started — is picked up without restarting,
    even if it never made it into the settings JSON. Same response shape as
    GET /api/config.
    """
    with STATE_LOCK:
        load_settings()
    cloud = SETTINGS.get("cloud_dir", "").strip()
    return jsonify({
        "cloud_dir": cloud,
        "classes": SETTINGS.get("classes", {}),
        "my_identities": SETTINGS.get("my_identities", []),
        "cloud_dir_exists": bool(cloud and os.path.isdir(cloud)),
    })


@app.route("/api/config/rename_class", methods=["POST"])
def api_config_rename_class():
    """Rename a class everywhere, carrying its graded data with it.

    Editing a class name in the settings grid and hitting Save only rewrites the
    name->ID map. The class's on-disk home ([cloud_dir]/[old name]/) and the
    class_name stored inside its grades_*.json files still say the old name, so
    the renamed class shows up empty and the next Force Sync rediscovers the old
    name as a second, duplicate class. This endpoint does the full migration:
      * moves [cloud_dir]/[old]/ -> [cloud_dir]/[new]/ (merging if new exists),
      * rewrites "class_name" inside every grades_*.json in that folder,
      * re-keys the settings map and follows the active class,
    so all previous grading travels with the class. Same response shape as
    GET /api/config, plus a summary of what moved.
    """
    data = request.get_json(force=True, silent=True) or {}
    old_name = (data.get("old_name") or "").strip()
    new_name = (data.get("new_name") or "").strip()

    if not old_name or not new_name:
        return jsonify({"error": "Both the current and new class names are required."}), 400
    if new_name == old_name:
        return jsonify({"error": "The new name is the same as the current one."}), 400

    with STATE_LOCK:
        classes = SETTINGS.get("classes", {})
        if old_name not in classes:
            return jsonify({"error": f"No class named '{old_name}' to rename."}), 404
        if new_name in classes and classes[new_name] != classes[old_name]:
            return jsonify({
                "error": f"'{new_name}' already exists and points to a different "
                         f"Drive folder. Pick a different name."
            }), 409

        moved = _migrate_class_folder(old_name, new_name)

        # Re-key the map in place, preserving the original ordering.
        SETTINGS["classes"] = {
            (new_name if k == old_name else k): v for k, v in classes.items()
        }

        if STATE.get("class_name") == old_name:
            STATE["class_name"] = new_name

        save_settings()

    cloud = SETTINGS.get("cloud_dir", "").strip()
    return jsonify({
        "cloud_dir": cloud,
        "classes": SETTINGS.get("classes", {}),
        "my_identities": SETTINGS.get("my_identities", []),
        "cloud_dir_exists": bool(cloud and os.path.isdir(cloud)),
        "renamed": {"from": old_name, "to": new_name, **moved},
    })


@app.route("/api/save_state", methods=["POST"])
def api_save_state():
    """Flush the live grading state cache into the active class's output folder.

    With a cloud directory + active class configured this writes
    grading_cache.json (and the per-folder grades file) into
    [cloud_dir]/[class_name]/; otherwise it falls back to the app root.
    """
    with STATE_LOCK:
        if not STATE["folder_id"]:
            return jsonify({"error": "No folder is currently loaded."}), 400
        save_state()
        out_dir = class_output_dir(create=True)
        return jsonify({
            "ok": True,
            "directory": out_dir,
            "cache_file": cache_file_path(),
            "routed_to_cloud": out_dir != BASE_DIR,
        })


@app.route("/api/checklist", methods=["POST"])
def api_checklist():
    """Persist the custom rubric criteria for the currently-open folder.

    Receives the FULL headers array and merges it under the active folder ID,
    touching only STATE["checklist"]. Student marks (grades, keyword
    checkboxes, comments) live in STATE["students"] and are left untouched, so
    write_cache() re-emits them exactly as they were — autosaving a header edit
    can never reset a score.
    """
    data = request.get_json(force=True, silent=True) or {}
    checklist = _normalize_checklist(data.get("checklist"))
    with STATE_LOCK:
        if not STATE["folder_id"]:
            return jsonify({"error": "No folder is currently loaded."}), 400
        STATE["checklist"] = checklist
        save_state()              # writes grades_<id>.json AND grading_cache.json
        return jsonify({"ok": True, "checklist": checklist})


@app.route("/api/group/link", methods=["POST"])
def api_group_link():
    """Link two students (A then B) into a shared pair-work group."""
    data = request.get_json(force=True, silent=True) or {}
    a, b = data.get("a_key"), data.get("b_key")
    with STATE_LOCK:
        if a not in STATE["students"] or b not in STATE["students"]:
            return jsonify({"error": "Unknown student."}), 404
        if a == b:
            return jsonify({"error": "Pick two different students to link."}), 400

        ga, gb = _find_group(a), _find_group(b)
        if ga and gb and ga is gb:
            pass                                   # already linked together
        elif ga and gb:                            # merge B's group into A's
            for m in gb["members"]:
                if m not in ga["members"]:
                    ga["members"].append(m)
            STATE["groups"].remove(gb)
        elif ga:
            if b not in ga["members"]:
                ga["members"].append(b)
        elif gb:
            if a not in gb["members"]:
                gb["members"].append(a)
        else:
            used = {g["color"] for g in STATE["groups"]}
            color = next((c for c in GROUP_COLORS if c not in used),
                         GROUP_COLORS[len(STATE["groups"]) % len(GROUP_COLORS)])
            STATE["groups"].append(
                {"id": _gen_group_id(), "members": [a, b], "color": color})

        _sync_group_grades(a)                      # partners share one grade
        save_state()
        return jsonify({"ok": True, "groups": STATE["groups"],
                        "students": present_students()})


@app.route("/api/group/unlink", methods=["POST"])
def api_group_unlink():
    """Dissolve a group entirely; members return to the normal roster."""
    data = request.get_json(force=True, silent=True) or {}
    gid = data.get("group_id")
    with STATE_LOCK:
        STATE["groups"] = [g for g in STATE["groups"] if g.get("id") != gid]
        save_state()
        return jsonify({"ok": True, "groups": STATE["groups"]})


@app.route("/api/state")
def api_state():
    with STATE_LOCK:
        return jsonify({
            "folder_id": STATE["folder_id"],
            "folder_name": STATE["folder_name"],
            "students": present_students(),
            "groups": STATE["groups"],
        })


def _deadline_date(deadline):
    """Return the YYYY-MM-DD date portion of a datetime-local deadline string.

    Falls back to today's date if no deadline has been set.
    """
    raw = (deadline or "").strip()
    if raw:
        dt = parse_time(raw)
        if dt:
            return dt.date().isoformat()
        # datetime-local values look like '2026-06-30T15:00' — take the date part.
        return raw.split("T", 1)[0]
    return datetime.date.today().isoformat()


@app.route("/api/export")
def api_export():
    force = request.args.get("force") == "1"
    with STATE_LOCK:
        # Name the export after CAM's current assignment name when known, so a
        # rename done in CAM Window 1 is what Sync reads back (the CSV filename
        # is CAM's only handle on the assignment). Falls back to the physical
        # folder name for plain workspace use with no CAM handoff.
        folder_name = ((STATE.get("cam_name") or "").strip()
                       or STATE["folder_name"] or "Grades")
        criteria = list(STATE.get("criteria") or [])
        deadline = STATE.get("deadline", "")
        out_dir = class_output_dir(create=True)
        class_name = STATE.get("class_name")
        students = sorted(STATE["students"].values(), key=lambda s: s["name"].lower())
        cam_extra = dict(STATE.get("cam_extra") or {})

    if not students:
        return jsonify({"error": "Nothing loaded to export."}), 400

    # If no criteria were explicitly selected, fall back to whatever grades exist
    # so an export is never silently empty.
    if not criteria:
        seen = []
        for s in students:
            for c in (s.get("grades") or {}):
                if c not in seen:
                    seen.append(c)
        criteria = sorted(seen) if seen else ["A"]

    # The export is the FULL snapshot CAM will purge-replace the assignment
    # with, so no held band may be dropped: widen the columns to every
    # criterion that actually carries a grade (CAM-adopted values can sit
    # outside the ticked criteria after a cache loss).
    held = {c for s in students for c in (s.get("grades") or {})}
    held |= {c for rec in cam_extra.values() for c in rec.get("grades", {})}
    extra_cols = sorted(c for c in held if c in MYP_CRITERIA and c not in criteria)
    criteria += extra_cols

    # The official assignment deadline (Due Date), date portion only, so
    # downstream apps can read it and reflect the due date on the dashboard.
    # Left blank when no deadline has been set for the assignment, rather than
    # feeding a placeholder date the dashboard would mistake for a real one.
    due_date = _deadline_date(deadline) if (deadline or "").strip() else ""
    # A date is still needed to name the file; fall back to today only here.
    file_date = due_date or datetime.date.today().isoformat()

    # Explicit, durable headers: one named column per assessed MYP criterion.
    grade_headers = [f"Grade (Crit {c})" for c in criteria]
    header = (["Student Name"] + grade_headers +
              ["Checked Keywords", "Comment", "Due Date",
               "File Count", "Files (newest first)", "Late"])

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for s in students:
        grades = s.get("grades") or {}
        grade_cells = [grades.get(c, "") for c in criteria]
        keywords = "; ".join(s.get("keywords", []))
        filenames = "; ".join(f["filename"] for f in s.get("files", []))
        # Tri-state Late cell: "1" late, "0" explicitly on-time, "" never
        # assessed (None). CAM's ingest parses only "1"/"true"/"yes" as late.
        lm = s.get("late_marked")
        late_cell = "1" if lm else ("0" if lm is False else "")
        writer.writerow(
            [s["name"]] + grade_cells +
            [keywords, s.get("comment", ""), due_date,
             s.get("count", 0), filenames, late_cell]
        )
    # Carry forward CAM-graded students who have no files in this folder —
    # their marks exist only in CAM, and the purge-replace on Sync would
    # silently drop them if this snapshot left them out. The CAM student id
    # doubles as the Student Name (that column already carries the numeric
    # email id for folder students).
    for sid in sorted(cam_extra):
        rec = cam_extra[sid]
        # CAM-only students carry no folder submission, so lateness is unknown:
        # the Late cell stays blank (tri-state None).
        writer.writerow(
            [sid] + [rec.get("grades", {}).get(c, "") for c in criteria] +
            ["", rec.get("comment", ""), due_date, 0, "", ""]
        )

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", folder_name).strip() or "Grades"
    filename = f"{safe_name}_Grades_{file_date}.csv"
    data_bytes = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM for Excel

    # When a cloud directory + active class are configured, write the CSV
    # straight into [cloud_dir]/[class_name]/ (the dashboard feed) instead of
    # streaming a browser download. out_dir falls back to BASE_DIR otherwise.
    routed = out_dir != BASE_DIR
    if routed:
        dest = os.path.join(out_dir, filename)
        # Don't silently clobber an existing export. Ask the frontend to
        # confirm an overwrite, then it re-requests this endpoint with force=1.
        if os.path.exists(dest) and not force:
            return jsonify({
                "needs_confirm": True,
                "path": dest,
                "filename": filename,
            })
        try:
            with open(dest, "wb") as f:
                f.write(data_bytes)
        except Exception as e:
            return jsonify({"error": f"Could not write CSV to {out_dir}: {e}"}), 500
        # The export is the new shared baseline: every CAM change it carries
        # is now accounted for, so the MODIFIED markers are done. cam_extra
        # stays — those students still have no files here, and the NEXT
        # export must keep carrying them until CAM republishes.
        with STATE_LOCK:
            for stu in STATE["students"].values():
                stu["cam_modified"] = []
            save_state()
        # Sync-on-export beacon: tell CAM's poller a fresh grading export for
        # this class/assignment just landed, so it scoped-syncs within seconds
        # instead of waiting for the teacher to click around. Best-effort.
        _write_export_beacon(class_name, folder_name, is_exam=False,
                             csv_path=dest)
        # Warn about differently-dated sibling exports for THIS assignment. CAM
        # maps every "<name>_Grades_<date>.csv" back to one assignment and
        # refuses to sync when it finds more than one, so leaving an older
        # date-named twin behind (e.g. from an export made while the deadline
        # was missing) would block the next Sync. We never delete anything —
        # just surface the stale file(s) for the teacher to verify + remove.
        pattern = os.path.join(out_dir, f"{safe_name}_Grades_*.csv")
        stale_siblings = sorted(
            os.path.basename(p) for p in glob.glob(pattern)
            if os.path.abspath(p) != os.path.abspath(dest)
        )
        return jsonify({
            "saved": True,
            "path": dest,
            "filename": filename,
            "class_name": class_name,
            "student_count": len(students),
            "stale_siblings": stale_siblings,
        })

    # No cloud directory configured -> behave as before and download the file.
    return send_file(io.BytesIO(data_bytes), mimetype="text/csv",
                     as_attachment=True, download_name=filename)


# -----------------------------------------------------------------------------
# Exam Slicing (setup + grading + item-level CSV export)
# -----------------------------------------------------------------------------
# Exam definitions are programmed in /exam_setup, stored in gcg_exams.json per
# class. Processing slices every student PDF into per-question crops; the main
# UI then grades an exam question-by-question. Grades persist to
# exam_grades_<exam>.json inside the class output dir (cloud-synced when
# configured) and export as an item-level CSV (one column per question before
# Total Score) that ACM auto-ingests.
#
# Portable exam data (Phase 6, decision D5): when a class has a cloud folder,
# both the crops and the exam definition live inside it so the exam can be
# graded from any synced device —
#     crops       -> <cloud>/<class>/exam_crops/<exam>/<Q>/<student>.png
#     definitions -> <cloud>/<class>/gcg_exams.json  (via ExamStore)
# Cloud-less classes keep the legacy app-local layout
# (BASE_DIR/exam_crops/<class>/... and BASE_DIR/gcg_exams.json). Reads try the
# cloud root first, then the legacy root, so pre-Phase-6 crops keep serving.
# EXAM_STORE.class_dir is wired below, once exam_output_dir is defined.

EXAM_STORE = exam_engine.ExamStore(BASE_DIR)
EXAM_CROPS_DIR = os.path.join(BASE_DIR, "exam_crops")

# Background exam-slicing jobs. process_exam runs on a daemon thread so large
# student stacks don't hit browser gateway timeouts; the front end polls
# /api/exam/status/<job_id> for progress. Guarded by its own lock (independent
# of STATE_LOCK — process_exam only touches the filesystem, never STATE).
EXAM_JOBS = {}
EXAM_JOBS_LOCK = threading.Lock()

# Active exam grading session (parallel to STATE, which stays Drive-only).
EXAM_STATE = {
    "class_name": None,
    "exam_name": None,
    "config": None,      # the saved exam definition
    "students": {},      # student -> {"scores": {label: int}, "comment", "keywords"}
    "checklist": [],     # editable keyword rubric, persisted with the grades
}


def exam_output_dir(class_name, create=False):
    """Where an exam's grades + CSV belong: the class cloud subfolder, else root."""
    cloud = SETTINGS.get("cloud_dir", "").strip()
    if cloud and class_name and os.path.isdir(cloud):
        d = os.path.join(cloud, _safe_dirname(class_name))
        if create:
            try:
                os.makedirs(d, exist_ok=True)
            except Exception as e:
                print("Warning: could not create class subfolder:", e)
                return BASE_DIR
        return d
    return BASE_DIR


def _exam_class_dir(class_name, create=False):
    """A class's portable cloud folder for exam definitions, or None (cloud-less).

    Wraps ``exam_output_dir`` so ``ExamStore`` can decide between the portable
    per-class ``gcg_exams.json`` and the legacy app-local one without importing
    any app state. ``BASE_DIR`` (the cloud-less fallback) maps to ``None`` so the
    store keeps its legacy behaviour there.
    """
    d = exam_output_dir(class_name, create=create)
    return d if d != BASE_DIR else None


# Wire the portable-store resolver now that exam_output_dir exists (Phase 6).
EXAM_STORE.class_dir = _exam_class_dir


def _legacy_exam_crop_dir(class_name):
    return os.path.join(EXAM_CROPS_DIR, exam_engine._safe_name(class_name or "Unsorted"))


def exam_crop_dir(class_name, create=False):
    """Where slicing WRITES a class's crops (Phase 6, decision D5).

    ``<cloud>/<class>/exam_crops/`` when the class has a cloud folder (so crops
    travel with the synced class folder), else the legacy
    ``BASE_DIR/exam_crops/<class>/`` for cloud-less setups. ``process_exam``
    creates the per-question subdirs, so ``create`` only needs to guarantee the
    root when a fresh cloud class folder is being populated.
    """
    out = exam_output_dir(class_name, create=create)
    if out != BASE_DIR:
        d = os.path.join(out, "exam_crops")
        if create:
            try:
                os.makedirs(d, exist_ok=True)
            except OSError as e:
                print("Warning: could not create exam crop root:", e)
        return d
    return _legacy_exam_crop_dir(class_name)


def exam_crop_roots(class_name):
    """Candidate crop roots for READS: cloud root first, then the legacy root.

    Both are always returned (callers skip the ones that don't exist) so a class
    that has moved to the cloud still serves any crops sliced before Phase 6.
    """
    roots = []
    out = exam_output_dir(class_name)
    if out != BASE_DIR:
        roots.append(os.path.join(out, "exam_crops"))
    legacy = _legacy_exam_crop_dir(class_name)
    if legacy not in roots:
        roots.append(legacy)
    return roots


@app.route("/exam_setup")
def exam_setup():
    return Response(EXAM_SETUP_PAGE, mimetype="text/html")


@app.route("/api/exams")
def api_exams():
    """List saved exam definitions for one class (drives the exam dropdowns)."""
    class_name = (request.args.get("class_name") or "").strip()
    exams = EXAM_STORE.list_exams(class_name)
    return jsonify({"class_name": class_name, "exams": exams})


@app.route("/api/exam/scan_folder", methods=["POST"])
def api_exam_scan_folder():
    """Inspect a student-PDF folder: file count + the first student's pages.

    The setup screen previews the FIRST student's exam while the teacher
    programs the questions; processing later runs over every file found here.
    """
    data = request.get_json(force=True, silent=True) or {}
    folder = (data.get("folder") or "").strip()
    if not folder or not os.path.isdir(folder):
        return jsonify({"error": f"Folder not found: {folder or '(blank)'}"}), 400
    try:
        files = exam_engine.list_student_files(folder)
        if not files:
            return jsonify({"error": "No PDF or image files in that folder."}), 404
        first_name, first_path = files[0]
        pages = exam_engine.page_count(first_path)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({
        "folder": folder,
        "file_count": len(files),
        "students": [n for n, _ in files],
        "first_student": first_name,
        "page_count": pages,
    })


@app.route("/api/exam/preview")
def api_exam_preview():
    """PNG preview of the first student's page N, for the setup grid overlay."""
    folder = (request.args.get("folder") or "").strip()
    page = request.args.get("page", default=1, type=int)
    if not folder or not os.path.isdir(folder):
        abort(404)
    try:
        files = exam_engine.list_student_files(folder)
        if not files:
            abort(404)
        png = exam_engine.page_png_bytes(files[0][1], page)
    except Exception:
        abort(404)
    return Response(png, mimetype="image/png",
                    headers={"Cache-Control": "private, max-age=60"})


@app.route("/api/exam/save", methods=["POST"])
def api_exam_save():
    """Persist one exam definition (name, paper size, folder, questions)."""
    data = request.get_json(force=True, silent=True) or {}
    class_name = (data.get("class_name") or "").strip()
    if not class_name:
        return jsonify({"error": "Pick a class before saving the exam."}), 400
    try:
        clean = EXAM_STORE.save_exam(class_name, data.get("config") or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True, "class_name": class_name, "config": clean})


def _run_exam_job(job_id, config, out_dir, labels=None):
    """Worker body: slice student PDFs, streaming progress into the job.

    ``labels`` (Phase 6) restricts the slice to those question labels — the
    "re-slice one question" path — so only the touched question's crops are
    rewritten; ``None`` slices the whole exam.
    """
    def report(done, total):
        with EXAM_JOBS_LOCK:
            job = EXAM_JOBS.get(job_id)
            if job:
                job["done"], job["total"] = done, total
    try:
        summary = exam_engine.process_exam(config, out_dir, progress=report,
                                           labels=labels)
    except Exception as e:                  # noqa: BLE001 — surface to the poller
        with EXAM_JOBS_LOCK:
            job = EXAM_JOBS.get(job_id)
            if job:
                job["state"], job["error"] = "error", str(e)
        return
    with EXAM_JOBS_LOCK:
        job = EXAM_JOBS.get(job_id)
        if job:
            job["state"] = "done"
            job["result"] = {"exam_name": config["name"], **summary}


@app.route("/api/exam/process", methods=["POST"])
def api_exam_process():
    """Kick off background slicing of every student PDF (saves config first).

    Returns a job id immediately; poll /api/exam/status/<job_id> for progress
    and the final summary. Large stacks used to block the request thread long
    enough to hit browser gateway timeouts (ARCHITECTURE §4)."""
    data = request.get_json(force=True, silent=True) or {}
    class_name = (data.get("class_name") or "").strip()
    if not class_name:
        return jsonify({"error": "Pick a class before processing."}), 400
    try:
        # Saving first means the processed crops always match a stored config.
        config = EXAM_STORE.save_exam(class_name, data.get("config") or {})
        if not config.get("pdf_folder"):
            return jsonify({"error": "Load a student PDF folder first."}), 400
        # pdf_folder is an absolute per-device path (Phase 6 caveat): grading
        # from synced crops works anywhere, but re-slicing needs the scans on
        # THIS device. Say so plainly when the folder isn't here.
        if not os.path.isdir(config["pdf_folder"]):
            return jsonify({"error":
                f"This device can't see the scan folder ({config['pdf_folder']!r}) "
                "— grading still works from the synced crops, but re-slicing "
                "needs the scan PDFs present on this computer."}), 400
        # Validate the folder and learn the class size up front so the initial
        # response seeds a progress total (process_exam re-scans as it works).
        students = exam_engine.list_student_files(config["pdf_folder"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not students:
        return jsonify({"error": f"No PDF/image files found in "
                                 f"{config['pdf_folder']!r}."}), 400

    job_id = uuid.uuid4().hex
    with EXAM_JOBS_LOCK:
        EXAM_JOBS[job_id] = {
            "state": "running", "done": 0, "total": len(students),
            "class_name": class_name, "exam_name": config["name"],
            "result": None, "error": None,
        }
    threading.Thread(target=_run_exam_job,
                     args=(job_id, config, exam_crop_dir(class_name, create=True)),
                     daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "exam_name": config["name"],
                    "students": len(students),
                    "questions": len(config["questions"])})


@app.route("/api/exam/process_one", methods=["POST"])
def api_exam_process_one():
    """Re-slice ONE question for every student, during grading (Phase 6).

    The teacher tweaks a single question's coordinate range in Exam Setup's
    focus mode and re-slices just that question — far faster than re-processing
    the whole stack, and every other question's crops stay byte-identical. Saves
    the (possibly widened) config first, then kicks off a background job that
    crops only ``label``. Entered marks are keyed by label and never touched.
    """
    data = request.get_json(force=True, silent=True) or {}
    class_name = (data.get("class_name") or "").strip()
    label = (data.get("label") or "").strip()
    if not class_name:
        return jsonify({"error": "Pick a class before re-slicing."}), 400
    if not label:
        return jsonify({"error": "No question label to re-slice."}), 400
    try:
        # Saving first keeps the crops matched to a stored config (as /process).
        config = EXAM_STORE.save_exam(class_name, data.get("config") or {})
        if not config.get("pdf_folder"):
            return jsonify({"error": "Load a student PDF folder first."}), 400
        if not os.path.isdir(config["pdf_folder"]):
            return jsonify({"error":
                f"This device can't see the scan folder ({config['pdf_folder']!r}) "
                "— grading still works from the synced crops, but re-slicing "
                "needs the scan PDFs present on this computer."}), 400
        if label not in {q["label"] for q in config["questions"]}:
            return jsonify({"error": f"Question '{label}' is not in this exam."}), 400
        students = exam_engine.list_student_files(config["pdf_folder"])
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not students:
        return jsonify({"error": f"No PDF/image files found in "
                                 f"{config['pdf_folder']!r}."}), 400

    job_id = uuid.uuid4().hex
    with EXAM_JOBS_LOCK:
        EXAM_JOBS[job_id] = {
            "state": "running", "done": 0, "total": len(students),
            "class_name": class_name, "exam_name": config["name"], "label": label,
            "result": None, "error": None,
        }
    threading.Thread(target=_run_exam_job,
                     args=(job_id, config, exam_crop_dir(class_name, create=True)),
                     kwargs={"labels": [label]}, daemon=True).start()
    return jsonify({"ok": True, "job_id": job_id, "exam_name": config["name"],
                    "label": label, "students": len(students)})


@app.route("/api/exam/status/<job_id>")
def api_exam_status(job_id):
    """Poll a background slicing job started by /api/exam/process."""
    with EXAM_JOBS_LOCK:
        job = EXAM_JOBS.get(job_id)
        if not job:
            return jsonify({"error": "Unknown or expired job id."}), 404
        return jsonify(dict(job))


@app.route("/api/exam/load", methods=["POST"])
def api_exam_load():
    """Open an exam for grading: questions + every sliced student + saved marks."""
    data = request.get_json(force=True, silent=True) or {}
    class_name = (data.get("class_name") or "").strip()
    exam_name = (data.get("exam_name") or "").strip()
    config = EXAM_STORE.get_exam(class_name, exam_name)
    if not config:
        return jsonify({"error": f"No exam '{exam_name}' saved for class "
                                 f"'{class_name}'. Run Exam Setup first."}), 404

    # The student list comes from the sliced crops (ground truth of what was
    # processed); fall back to the source folder if slicing hasn't run yet.
    # Scan both crop roots (cloud + legacy) so a class carries its pre-Phase-6
    # crops after moving to the cloud (Phase 6 read fallback).
    students = set()
    for root in exam_crop_roots(class_name):
        exam_dir = os.path.join(root, exam_engine._safe_name(exam_name))
        for q in config["questions"]:
            q_dir = os.path.join(exam_dir, exam_engine._safe_name(q["label"]))
            if os.path.isdir(q_dir):
                for f in os.listdir(q_dir):
                    if f.lower().endswith(".png"):
                        students.add(os.path.splitext(f)[0])
    if not students and config.get("pdf_folder") and os.path.isdir(config["pdf_folder"]):
        try:
            students = {n for n, _ in
                        exam_engine.list_student_files(config["pdf_folder"])}
        except ValueError:
            pass
    if not students:
        return jsonify({"error": "No sliced student answers found — run "
                                 "'Process All PDFs' in Exam Setup first."}), 404

    saved, checklist = exam_engine.load_exam_grades(
        exam_output_dir(class_name), exam_name)
    roster = {}
    for name in sorted(students, key=str.lower):
        prev = saved.get(name) or {}
        roster[name] = {
            "scores": {k: v for k, v in (prev.get("scores") or {}).items()},
            "comment": prev.get("comment", ""),
            "keywords": list(prev.get("keywords") or []),
        }

    with STATE_LOCK:
        EXAM_STATE["class_name"] = class_name
        EXAM_STATE["exam_name"] = exam_name
        EXAM_STATE["config"] = config
        EXAM_STATE["students"] = roster
        EXAM_STATE["checklist"] = checklist

    # Anonymous grading (D6, YouMark-style): blank every display name; the real
    # stem stays in `key` for the round-trip (crops, grades, export all read
    # EXAM_STATE, which stays real). The client re-shuffles + numbers by
    # position per question — see examView(). Same display-only doctrine as the
    # assignment layer's present_students(); EXAM_STATE is never mutated here.
    anon = anonymous_enabled()
    return jsonify({
        "class_name": class_name,
        "exam_name": exam_name,
        "questions": config["questions"],
        "checklist": checklist,
        "anonymous": anon,
        "students": [{"key": k, "name": ("" if anon else k), **v}
                     for k, v in roster.items()],
    })


@app.route("/api/exam/grade", methods=["POST"])
def api_exam_grade():
    """Save one student's per-question scores + comment for the open exam."""
    data = request.get_json(force=True, silent=True) or {}
    key = data.get("key")
    with STATE_LOCK:
        if not EXAM_STATE["exam_name"]:
            return jsonify({"error": "No exam is currently loaded."}), 400
        st = EXAM_STATE["students"].get(key)
        if st is None:
            return jsonify({"error": "Unknown student."}), 404
        if "scores" in data and isinstance(data["scores"], dict):
            valid_labels = {q["label"] for q in EXAM_STATE["config"]["questions"]}
            st["scores"] = {
                str(k): int(v) for k, v in data["scores"].items()
                if str(k) in valid_labels and str(v).strip() != ""
            }
        if "comment" in data:
            st["comment"] = str(data["comment"])
        if "keywords" in data and isinstance(data["keywords"], list):
            st["keywords"] = [str(x) for x in data["keywords"]]
        try:
            exam_engine.save_exam_grades(
                exam_output_dir(EXAM_STATE["class_name"], create=True),
                EXAM_STATE["exam_name"], EXAM_STATE["students"],
                EXAM_STATE["checklist"])
        except OSError as e:
            return jsonify({"error": f"Could not save exam grades: {e}"}), 500
        return jsonify({"ok": True, "student": {"key": key, **st}})


@app.route("/api/exam/checklist", methods=["POST"])
def api_exam_checklist():
    """Persist the keyword rubric for the currently-open exam.

    Receives the FULL checklist array and stores it beside the marks in
    exam_grades_<exam>.json (student scores/keywords/comments are untouched, so
    a header edit can never disturb a saved mark). Mirrors /api/checklist for
    the assignment layer.
    """
    data = request.get_json(force=True, silent=True) or {}
    checklist = _normalize_checklist(data.get("checklist"))
    with STATE_LOCK:
        if not EXAM_STATE["exam_name"]:
            return jsonify({"error": "No exam is currently loaded."}), 400
        EXAM_STATE["checklist"] = checklist
        try:
            exam_engine.save_exam_grades(
                exam_output_dir(EXAM_STATE["class_name"], create=True),
                EXAM_STATE["exam_name"], EXAM_STATE["students"],
                EXAM_STATE["checklist"])
        except OSError as e:
            return jsonify({"error": f"Could not save exam checklist: {e}"}), 500
        return jsonify({"ok": True, "checklist": checklist})


@app.route("/api/exam/crop")
def api_exam_crop():
    """Serve one sliced answer image: ?class=..&exam=..&q=..&student=.."""
    class_name = request.args.get("class", "")
    exam = request.args.get("exam", "")
    q = request.args.get("q", "")
    student = request.args.get("student", "")
    # Try the cloud root first, then the legacy local root (Phase 6 read
    # fallback). _safe_name strips path separators, so the join cannot escape a
    # crops dir.
    rel = os.path.join(exam_engine._safe_name(exam),
                       exam_engine._safe_name(q),
                       exam_engine._safe_name(student) + ".png")
    for root in exam_crop_roots(class_name):
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            return send_file(path, mimetype="image/png")
    abort(404)


@app.route("/api/exam/export")
def api_exam_export():
    """Item-level CSV export of the open exam.

    Headers expand dynamically to one column per programmed question — in the
    teacher's grading order, BEFORE the Total Score column — rather than the
    standard lump-sum format:

        Student Name, Q1, Q2, ..., Total Score, Max Total, Due Date, Comment

    ?download=1 always streams a browser download (the teacher's own backend
    processing); otherwise, like /api/export, the file routes into the class
    cloud subfolder where ACM's watch-folder sync picks it up automatically.
    """
    force = request.args.get("force") == "1"
    download = request.args.get("download") == "1"
    with STATE_LOCK:
        if not EXAM_STATE["exam_name"]:
            return jsonify({"error": "No exam is currently loaded."}), 400
        exam_name = EXAM_STATE["exam_name"]
        class_name = EXAM_STATE["class_name"]
        config = EXAM_STATE["config"]
        students = {k: {"scores": dict(v.get("scores") or {}),
                        "comment": v.get("comment", ""),
                        "keywords": list(v.get("keywords") or [])}
                    for k, v in EXAM_STATE["students"].items()}

    labels = [q["label"] for q in config["questions"]]
    max_total = sum(q["max"] for q in config["questions"])
    today = datetime.date.today().isoformat()

    # "Checked Keywords" (semicolon-joined) sits before Comment, matching the
    # assignment CSV convention; ACM keys columns by header, so the extra column
    # is ignored by its exam ingest until it wants it.
    header = (["Student Name"] + labels +
              ["Total Score", "Max Total", "Due Date", "Checked Keywords", "Comment"])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    for name in sorted(students, key=str.lower):
        st = students[name]
        cells = [st["scores"].get(lbl, "") for lbl in labels]
        nums = [v for v in st["scores"].values() if isinstance(v, int)]
        total = sum(nums) if nums else ""
        keywords = "; ".join(st["keywords"])
        writer.writerow([name] + cells +
                        [total, max_total, today, keywords, st["comment"]])

    safe_name = re.sub(r'[\\/*?:"<>|]', "_", exam_name).strip() or "Exam"
    filename = f"{safe_name}_Grades_{today}.csv"
    data_bytes = ("﻿" + buf.getvalue()).encode("utf-8")   # BOM for Excel

    out_dir = exam_output_dir(class_name, create=True)
    routed = out_dir != BASE_DIR and not download
    if routed:
        dest = os.path.join(out_dir, filename)
        if os.path.exists(dest) and not force:
            return jsonify({"needs_confirm": True, "path": dest,
                            "filename": filename})
        # Definition sidecar (Phase 4C): write <csv>.meta.json BEFORE the CSV so
        # a sync that sees the CSV also sees the structure. Atomic + best-effort;
        # a sidecar failure must never fail the export (CAM tolerates absence).
        try:
            meta = exam_engine.build_sidecar(config)
            meta_path = dest + ".meta.json"
            meta_tmp = meta_path + ".tmp"
            with open(meta_tmp, "w", encoding="utf-8") as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)
            os.replace(meta_tmp, meta_path)
        except Exception as e:
            print("Warning: could not write exam sidecar:", e)
        try:
            with open(dest, "wb") as f:
                f.write(data_bytes)
        except Exception as e:
            return jsonify({"error": f"Could not write CSV to {out_dir}: {e}"}), 500
        # Sync-on-export beacon (exam variant): CAM's poller routes is_exam=True
        # through its scoped exam sync. Best-effort — never fails the export.
        _write_export_beacon(class_name, exam_name, is_exam=True,
                             csv_path=dest)
        return jsonify({"saved": True, "path": dest, "filename": filename,
                        "class_name": class_name,
                        "student_count": len(students)})

    return send_file(io.BytesIO(data_bytes), mimetype="text/csv",
                     as_attachment=True, download_name=filename)


# -----------------------------------------------------------------------------
# Frontend (single-page app)
# -----------------------------------------------------------------------------
HTML_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CAM Grading Workspace</title>
<style>
  /* ACM app palette (art-criterion-metrics/.streamlit/config.toml) — warm grey
     canvas with a muted brick-red accent; light + dark follow the OS setting.
     Keep in sync with ACM if that theme changes. Keyword checklist tints keep
     their own green/orange/red coding, independent of this palette. */
  :root {
    color-scheme: light;
    --bg:#E9E7E2; --panel:#DDDAD3; --panel2:#DFDCD4; --line:#C6C2B9;
    --text:#38352F; --muted:#6E695F; --accent:#B3554D; --green:#37c97a;
    --row-hl:rgba(179,85,77,.16); --amber:#caa23a;
    --surface:#F0EEE9; --btn-hover:#D5D1C7; --imgbg:#CBC7BE;
    --accent-tint:rgba(179,85,77,.06);
    /* Keyword tints: same hues as the dark originals, deepened to stay
       readable on the light canvas */
    --kw-pos:#33714D; --kw-grow:#96591F; --kw-late:#A8434E;
    --kw-pos-bg:rgba(51,113,77,.10); --kw-grow-bg:rgba(150,89,31,.10);
  }
  /* Dark palette. The <head> bootstrap script resolves the saved preference
     (Settings -> Theme: auto/light/dark) to a concrete data-theme attribute
     before first paint; "auto" tracks the OS via a matchMedia listener. */
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg:#252423; --panel:#32312F; --panel2:#3A3835; --line:#4B4945;
    --text:#D8D5CF; --muted:#A19C93; --accent:#C4675F;
    --row-hl:rgba(196,103,95,.22);
    --surface:#2E2D2B; --btn-hover:#454340; --imgbg:#1B1A19;
    --accent-tint:rgba(196,103,95,.08);
    /* Keyword tints: original values, unchanged */
    --kw-pos:#bfe9cf; --kw-grow:#f4c9a0; --kw-late:#f0a0a8;
    --kw-pos-bg:rgba(191,233,207,.14); --kw-grow-bg:rgba(244,201,160,.14);
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; font-family:-apple-system,Segoe UI,Roboto,"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;
              background:var(--bg); color:var(--text); accent-color:var(--accent); }
  #app { display:flex; flex-direction:column; height:100vh; }

  /* Top bar */
  #topbar { display:flex; gap:10px; align-items:center; padding:10px 14px;
            background:var(--panel); border-bottom:1px solid var(--line); flex:none; flex-wrap:wrap; }
  #topbar input[type=text] { flex:1; min-width:240px; padding:8px 10px; border-radius:6px;
            border:1px solid var(--line); background:var(--panel2); color:var(--text); font-size:14px; }
  button { background:var(--accent); color:#fff; border:none; padding:8px 14px; border-radius:6px;
           font-size:14px; cursor:pointer; }
  button.secondary { background:var(--panel2); border:1px solid var(--line); color:var(--text); }
  button:hover { filter:brightness(1.08); }
  button.secondary:hover { background:var(--btn-hover); border-color:var(--accent); filter:none; }
  #folderName { font-weight:600; font-size:15px; }
  #status { color:var(--muted); font-size:13px; }
  .slider-wrap { display:flex; align-items:center; gap:8px; color:var(--muted); font-size:13px; }
  .hidden { display:none !important; }
  select#assignmentSelect, select#classSelect, select#questionSelect { padding:8px 10px;
            border-radius:6px; border:1px solid var(--line); background:var(--panel2);
            color:var(--text); font-size:14px; max-width:280px; }
  select#questionSelect { border-color:var(--accent); font-weight:600; }
  /* Exam grading: current-question column + score chip on answer cards */
  th.qcur, td.qcur { background:var(--row-hl); }
  select.qscore { width:60px; padding:5px; background:var(--panel2); color:var(--text);
                  border:1px solid var(--line); border-radius:5px; font-size:14px; }
  /* ✎ region-adjust button on each exam question column header (Phase 6). */
  button.qadjust { background:transparent; color:var(--muted); border:1px solid transparent;
                   padding:0 4px; font-size:12px; line-height:1.4; border-radius:4px; }
  button.qadjust:hover { background:var(--panel2); color:var(--accent);
                         border-color:var(--line); filter:none; }
  #examAdjustBtn { font-size:14px; line-height:1; padding:8px 11px; }
  .scard .exam-img { width:100%; display:block; background:var(--imgbg); }
  .qchip { position:absolute; top:8px; right:8px; background:var(--accent); color:#fff;
           border-radius:8px; padding:2px 10px; font-size:13px; font-weight:700; }
  #settingsBtn { font-size:16px; line-height:1; padding:8px 11px; }

  /* Settings modal */
  #settingsOverlay { position:fixed; inset:0; background:rgba(0,0,0,.55); z-index:100;
                     display:flex; align-items:flex-start; justify-content:center; padding:60px 16px; }
  #settingsModal { background:var(--surface); border:1px solid var(--line); border-radius:12px;
                   width:min(640px,100%); max-height:80vh; overflow:auto; padding:18px 20px;
                   box-shadow:0 18px 50px rgba(0,0,0,.55); }
  .sm-head { display:flex; align-items:center; margin-bottom:14px; }
  .sm-head h3 { margin:0; font-size:17px; flex:1; }
  .sm-field { display:flex; flex-direction:column; gap:5px; font-size:13px; color:var(--muted); }
  .sm-field input, .sm-field select { padding:8px 10px; border-radius:6px; border:1px solid var(--line);
                    background:var(--panel2); color:var(--text); font-size:13px; }
  .sm-field select { width:max-content; }
  .sm-anon { display:flex; align-items:center; gap:8px; font-size:13px; color:var(--text);
             cursor:pointer; }
  .sm-anon input { width:auto; }
  .sm-note { font-size:12px; color:var(--muted); min-height:16px; margin:4px 0; }
  .sm-classhead { display:flex; align-items:center; gap:10px; margin:16px 0 8px; font-size:13px;
                  color:var(--muted); }
  .sm-classhead span { flex:1; }
  .classrow { display:flex; gap:8px; margin-bottom:8px; }
  .classrow input { flex:1; padding:7px 9px; border-radius:6px; border:1px solid var(--line);
                    background:var(--panel2); color:var(--text); font-size:13px; }
  .classrow input.cname { max-width:200px; }
  .sm-foot { display:flex; align-items:center; gap:10px; margin-top:18px; }
  /* Read-only (CAM-managed) fields: sync dir + linked-class rows are display
     only, so mute them and disable the text cursor to signal "not editable". */
  .sm-field input[readonly], .classrow input[readonly] { opacity:.7; cursor:default; }

  /* Assignment setup bar (deadline + MYP criteria checkboxes) */
  #setupbar { display:flex; gap:14px; align-items:center; padding:8px 14px; flex-wrap:wrap;
              background:var(--panel); border-bottom:1px solid var(--line); flex:none; }
  #setupbar .setup-field { display:flex; align-items:center; gap:6px; font-size:13px; color:var(--muted); }
  #setupbar input[type=datetime-local] { padding:6px 8px; border-radius:6px; border:1px solid var(--line);
              background:var(--panel2); color:var(--text); font-size:13px; }
  #setupbar .setup-sep { width:1px; height:22px; background:var(--line); }
  #setupbar .setup-label { font-size:13px; color:var(--muted); }
  #criteriaBoxes { display:flex; gap:12px; flex-wrap:wrap; }
  #criteriaBoxes label { display:flex; align-items:center; gap:5px; font-size:13px; cursor:pointer; }
  #criteriaBoxes label .cdesc { color:var(--muted); font-size:11px; }

  /* "Late" badge on the workspace card */
  .latebadge { position:absolute; top:8px; right:38px; background:#d0556a; color:#fff;
               border-radius:6px; padding:2px 8px; font-size:11px; font-weight:700;
               letter-spacing:.03em; box-shadow:0 1px 4px rgba(0,0,0,.4); z-index:6; }
  .scard.expanded .latebadge { display:none; }
  .drawer .dhead .dlate { background:#d0556a; color:#fff; border-radius:8px; padding:2px 10px;
                          font-size:13px; font-weight:700; }

  /* MODIFIED marker: this work's grade was changed in CAM since the last
     export. Deliberately loud — the teacher must re-check the checklist. */
  .cam-modified { display:inline-block; background:#d0556a; color:#fff; border-radius:6px;
                  padding:3px 9px; font-size:13px; font-weight:800; letter-spacing:.06em;
                  cursor:pointer; box-shadow:0 1px 4px rgba(0,0,0,.35); }
  .cam-modified:hover { filter:brightness(1.12); }
  .cardmodified { position:absolute; top:40px; left:8px; z-index:6; font-size:12px; }
  #camModNote { display:none; margin:10px 14px 0; padding:8px 12px; border-radius:8px;
                background:#d0556a1c; border:1px solid #d0556a; color:var(--text);
                font-size:13px; line-height:1.45; }
  #camModNote b { color:#d0556a; letter-spacing:.05em; }

  /* Split layout */
  #split { display:flex; flex:1; min-height:0; }
  #left  { position:relative; overflow:auto; background:var(--bg); }
  #divider { width:7px; cursor:col-resize; background:var(--line); flex:none; }
  #divider:hover { background:var(--accent); }
  #right { flex:1; overflow:auto; background:var(--panel); min-width:200px; }

  /* Roster grid */
  #roster { display:grid; gap:14px; padding:14px; align-content:start; align-items:start; }
  .scard { position:relative; background:var(--panel2); border:1px solid var(--line);
           border-radius:12px; overflow:hidden; cursor:pointer; transition:border-color .12s; }
  .scard.selected { border-color:var(--accent); box-shadow:0 0 0 2px var(--accent) inset; }
  .scard.expanded { grid-column:1 / -1; cursor:default; }
  .scard .preview { width:100%; aspect-ratio:1/1; object-fit:cover; display:block; background:var(--imgbg); }
  .scard.expanded .preview { display:none; }
  .scard .ph { width:100%; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center;
               color:var(--muted); font-size:13px; text-align:center; padding:8px; }
  .scard.expanded .ph { display:none; }
  .scard .meta { padding:8px 10px; font-size:13px; line-height:1.35; }
  .scard .meta .nm { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .scard .meta .sub { color:var(--muted); font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .countbadge { position:absolute; top:8px; left:44px; background:rgba(0,0,0,.66); color:#fff;
                border-radius:12px; padding:2px 9px; font-size:12px; font-weight:600; }

  /* Link Partner button (top-left corner of each workspace card) */
  .linkbtn { position:absolute; top:8px; left:8px; width:28px; height:28px; border-radius:8px;
             background:rgba(0,0,0,.62); color:#fff; border:none; font-size:14px; line-height:1;
             cursor:pointer; padding:0; z-index:6; display:flex; align-items:center; justify-content:center;
             transition:background .12s, box-shadow .12s; }
  .linkbtn:hover { background:var(--accent); }
  .linkbtn.arming { background:var(--accent); box-shadow:0 0 0 2px #fff inset; }
  .scard.expanded .linkbtn { display:none; }

  /* Combined "Group Work" bounding box on the left panel */
  .groupbox { grid-column:1 / -1; border:2px dashed var(--accent); border-radius:14px;
              padding:8px 10px 12px; background:var(--accent-tint); }
  .groupbox .ghead { display:flex; align-items:center; gap:8px; padding:2px 4px 9px; font-size:13px; font-weight:700; }
  .groupbox .ghead .gchain { font-size:15px; }
  .groupbox .ghead .gids { color:var(--muted); font-weight:500; font-size:12px;
              white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .groupbox .ghead .gunlink { margin-left:auto; flex:none; background:var(--panel2); color:var(--muted);
              border:1px solid var(--line); border-radius:6px; width:24px; height:24px; padding:0;
              font-size:13px; line-height:1; cursor:pointer; }
  .groupbox .ghead .gunlink:hover { background:#d0556a; color:#fff; border-color:#d0556a; }
  .groupbox .ginner { display:grid; gap:14px; align-items:start; }
  .checkbadge { position:absolute; top:8px; right:8px; width:24px; height:24px; border-radius:50%;
                background:var(--green); color:#fff; display:none; align-items:center; justify-content:center;
                font-size:15px; font-weight:700; box-shadow:0 1px 4px rgba(0,0,0,.4); }
  .scard.graded .checkbadge { display:flex; }
  .gradechip { position:absolute; bottom:46px; right:8px; background:var(--accent); color:#fff;
               border-radius:8px; padding:2px 10px; font-size:14px; font-weight:700; display:none; }
  .scard.graded .gradechip { display:block; }
  .scard.expanded .gradechip, .scard.expanded .checkbadge, .scard.expanded .countbadge { display:none; }

  /* Expanded student drawer (stack of all their files) */
  .drawer { display:none; padding:12px 14px 14px; }
  .scard.expanded .drawer { display:block; }
  .drawer .dhead { display:flex; align-items:center; gap:12px; margin-bottom:10px; flex-wrap:wrap; }
  .drawer .dhead .dn { font-weight:700; font-size:15px; }
  .drawer .dhead .dc { color:var(--muted); font-size:12px; }
  .drawer .dhead .dg { background:var(--accent); color:#fff; border-radius:8px; padding:2px 10px;
                       font-size:13px; font-weight:700; }
  .drawer .collapse { margin-left:auto; }
  .stack { display:grid; grid-template-columns:repeat(auto-fill, minmax(150px,1fr)); gap:10px; }
  .stile { position:relative; background:var(--imgbg); border:1px solid var(--line); border-radius:8px;
           overflow:hidden; cursor:pointer; }
  .stile img { width:100%; aspect-ratio:1/1; object-fit:cover; display:block; }
  .stile .ph2 { width:100%; aspect-ratio:1/1; display:flex; align-items:center; justify-content:center;
                color:var(--muted); font-size:12px; text-align:center; padding:6px; }
  .stile .fn { padding:5px 7px; font-size:11px; color:var(--muted); white-space:nowrap;
               overflow:hidden; text-overflow:ellipsis; }
  .stile .newest { position:absolute; top:5px; left:5px; background:var(--green); color:#fff;
                   border-radius:5px; padding:1px 6px; font-size:10px; font-weight:700; }
  .stile .draft { position:absolute; top:5px; right:5px; background:var(--amber); color:#252423;
                  border-radius:5px; padding:1px 6px; font-size:10px; font-weight:700; }
  .stile .openlink { position:absolute; bottom:24px; right:5px; background:rgba(0,0,0,.6); color:#fff;
                     border-radius:5px; padding:1px 6px; font-size:11px; text-decoration:none; }

  /* Media wrapper (wraps every thumbnail; hosts hover-video + rotate button) */
  .mwrap { position:relative; display:block; width:100%; }
  .mwrap img { transition:transform .18s ease; }
  /* Inline hover-to-play video sits on top of the static thumbnail */
  .inlinevid { position:absolute; inset:0; width:100%; height:100%;
               object-fit:cover; background:var(--imgbg); z-index:2; display:block; }
  .mwrap .playbadge { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                      width:46px; height:46px; border-radius:50%; background:rgba(0,0,0,.55);
                      color:#fff; display:flex; align-items:center; justify-content:center;
                      font-size:18px; pointer-events:none; z-index:3; }
  .mwrap.playing .playbadge { display:none; }
  .mwrap .videotag { position:absolute; top:6px; right:6px; background:rgba(0,0,0,.62); color:#fff;
                     border-radius:5px; padding:1px 6px; font-size:10px; font-weight:700;
                     letter-spacing:.04em; pointer-events:none; z-index:3; }
  .mwrap.playing .videotag { display:none; }

  /* Rotate button (static images only) */
  .rotbtn { position:absolute; bottom:6px; left:6px; width:28px; height:28px; border-radius:7px;
            background:rgba(0,0,0,.6); color:#fff; border:none; font-size:16px; line-height:1;
            cursor:pointer; padding:0; z-index:4; display:flex; align-items:center; justify-content:center;
            opacity:0; transition:opacity .12s; }
  .mwrap:hover .rotbtn { opacity:1; }
  .rotbtn:hover { background:var(--accent); }

  /* Zoom overlay (constrained to the left panel) */
  #overlay { position:absolute; display:none; pointer-events:none; z-index:50;
             border:2px solid var(--accent); border-radius:10px; overflow:hidden;
             background:var(--imgbg); box-shadow:0 8px 30px rgba(0,0,0,.6); }
  #overlay img#overlayImg { width:100%; height:100%; object-fit:contain; display:block;
                            transition:transform .15s ease; }
  /* Video magnification mode: overlay fills the left panel & is interactive */
  #overlay.video-mode { pointer-events:auto; background:#000; }
  #overlay.video-mode #overlayImg { display:none; }
  #overlay .zoomvid { position:absolute; inset:0; width:100%; height:100%;
                      object-fit:contain; background:#000; z-index:1; }
  #overlay .ovclose { position:absolute; top:8px; right:10px; z-index:60; background:rgba(0,0,0,.66);
                      color:#fff; border:none; border-radius:6px; padding:5px 11px; cursor:pointer;
                      font-size:13px; }
  #overlay .ovclose:hover { background:var(--accent); }
  /* Focused document mode: overlay fills the left panel with the browser's
     native PDF engine (or a Google-native embed) — its own toolbar supplies
     scroll/page/zoom; our only chrome is the ✕ close button. */
  #overlay.doc-mode { pointer-events:auto; background:var(--imgbg); }
  #overlay.doc-mode #overlayImg { display:none; }
  #overlay .docframe { position:absolute; inset:0; width:100%; height:100%;
                       border:0; background:#fff; z-index:1; }

  /* Grading matrix */
  #right h2 { margin:0; padding:12px 14px; font-size:15px; border-bottom:1px solid var(--line);
              position:sticky; top:0; background:var(--panel); z-index:5; }
  table { border-collapse:collapse; width:100%; font-size:13px; }
  th,td { border-bottom:1px solid var(--line); padding:8px 10px; vertical-align:top; text-align:left; }
  th { position:sticky; top:48px; background:var(--panel2); z-index:4; font-size:12px; color:var(--muted); }
  tr.selected > td { background:var(--row-hl); }
  td.name { font-weight:600; white-space:nowrap; }
  td.name .sub { display:block; font-weight:400; color:var(--muted); font-size:11px; }
  /* Narrow "ID" column lets the divider slide far right for max art-grid space */
  th.idcol, td.idcol { width:84px; min-width:64px; max-width:120px; }
  td.idcol .sid { font-weight:600; white-space:nowrap; }
  .rowchain { margin-left:5px; cursor:help; font-size:12px; vertical-align:middle; }
  select.grade { width:62px; padding:5px; background:var(--panel2); color:var(--text);
                 border:1px solid var(--line); border-radius:5px; font-size:14px; }
  .kw { display:flex; flex-wrap:wrap; gap:4px 10px; max-width:330px; }
  .kw label { display:flex; align-items:center; gap:4px; font-size:12px; cursor:pointer; white-space:nowrap; }
  .kw .pos { color:var(--kw-pos); } .kw .grow { color:var(--kw-grow); }
  .kw .late-kw { color:var(--kw-late); font-weight:700; }
  textarea.comment { width:240px; min-height:54px; resize:vertical; background:var(--panel2);
                     color:var(--text); border:1px solid var(--line); border-radius:5px; padding:6px; font-size:12px; }
  .row-saved td { animation:flash .6s; }
  @keyframes flash { from{background:rgba(55,201,122,.25);} to{background:transparent;} }

  /* Keyword editor */
  #kwEditor { padding:10px 14px; border-bottom:1px solid var(--line); font-size:12px; color:var(--muted); }
  #kwEditor input { padding:5px 7px; border-radius:5px; border:1px solid var(--line);
                    background:var(--panel2); color:var(--text); }
  .tag { display:inline-flex; align-items:center; gap:5px; background:var(--panel2);
         border:1px solid var(--line); border-radius:12px; padding:2px 8px; margin:2px; font-size:12px; }
  /* Color-coded pills — same green/orange as the checklist next to student IDs */
  .tag.tag-pos  { background:var(--kw-pos-bg); border-color:var(--kw-pos); }
  .tag.tag-grow { background:var(--kw-grow-bg); border-color:var(--kw-grow); }
  .tag b { cursor:pointer; color:var(--muted); }
  /* Inline-editable criteria field inside each tag */
  .tag input.tagedit { border:none; background:transparent; font:inherit; padding:0 2px;
         min-width:40px; outline:none; }
  .tag input.tagedit:focus { background:var(--bg); border-radius:4px;
         box-shadow:0 0 0 1px var(--accent) inset; }
  .tag input.tagedit.pos { color:var(--kw-pos); } .tag input.tagedit.grow { color:var(--kw-grow); }
  .empty { padding:40px; text-align:center; color:var(--muted); }
</style>
<script>
/* Theme bootstrap: must run before <body> paints so a saved Dark/Light choice
   never flashes the other palette. Mirrors applyTheme() in the main script. */
(function(){
  var pref = localStorage.getItem("gcg_theme") || "auto";
  if (pref === "auto")
    pref = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = pref;
})();
</script>
</head>
<body>
<div id="app">
  <div id="topbar">
    <select id="classSelect" title="Pick a saved class to load its Drive folder">
      <option value="">Select class…</option>
    </select>
    <select id="assignmentSelect" class="hidden" title="Choose an assignment to grade">
      <option value="">Choose assignment…</option>
    </select>
    <button id="gradeBtn" class="hidden">Grade This</button>
    <select id="questionSelect" class="hidden" title="Exam question being graded"></select>
    <button id="examAdjustBtn" class="hidden secondary"
            title="Adjust the current question's region during grading">✎ Adjust</button>
    <span id="folderName"></span>
    <span id="status"></span>
    <span style="flex:1"></span>
    <div class="slider-wrap">
      <span>Columns</span>
      <input id="colSlider" type="range" min="2" max="5" value="3">
      <span id="colVal">3</span>
    </div>
    <button id="examSetupBtn" class="secondary"
            title="Program a scanned exam paper for the selected class">📝 Exam Setup</button>
    <button id="settingsBtn" class="secondary" title="Theme &amp; CAM link status">⚙</button>
    <button id="examCsvBtn" class="hidden secondary"
            title="Download this exam's item-level CSV for your own processing">⬇ Download CSV</button>
    <button id="exportBtn" class="secondary">Export CSV</button>
  </div>

  <!-- Settings modal: cloud sync directory + Class -> Drive folder-ID map -->
  <div id="settingsOverlay" class="hidden">
    <div id="settingsModal">
      <div class="sm-head">
        <h3>Settings</h3>
        <button id="settingsClose" class="secondary" title="Close">✕</button>
      </div>
      <label class="sm-field" style="margin-bottom:12px;">
        <span>Theme (this device)</span>
        <select id="themeSelect">
          <option value="auto">Auto — match system</option>
          <option value="light">Light</option>
          <option value="dark">Dark</option>
        </select>
      </label>
      <label class="sm-anon" style="margin-bottom:4px;">
        <input id="anonToggle" type="checkbox">
        <span>Anonymous grading (this device)</span>
      </label>
      <div class="sm-note" style="margin-bottom:12px;">
        Hides student names, IDs and filenames and shuffles the grading order to
        reduce bias. In exam grading, papers are numbered by position (01, 02, …)
        and re-shuffled for every question, so a number never identifies a
        student. It does not stop a student writing their name inside the work,
        and the “↗ open” link still shows the real file. The exported CSV — for
        both assignments and exams — keeps the real names either way. Reload the
        assignment to apply a change.
      </div>
      <label class="sm-field">
        <span>Cloud Sync Directory · managed by CAM</span>
        <input id="cloudDirInput" type="text" readonly tabindex="-1"
               placeholder="(set by CAM when you open a class from the dashboard)">
      </label>
      <div id="cloudDirNote" class="sm-note"></div>
      <div class="sm-classhead">
        <span>Linked classes (name → Drive folder ID) · managed by CAM</span>
      </div>
      <div id="classRows"></div>
      <div class="sm-note">
        The sync directory and class list are configured by the CAM dashboard —
        open a class or assignment from CAM to set them up. They're read-only
        here so the workspace and CAM can't drift out of sync.
      </div>
      <div class="sm-classhead" style="margin-top:14px;">
        <span>My identities (one per line) · your own Drive accounts &amp; names</span>
      </div>
      <textarea id="identitiesInput" rows="3"
                placeholder="j.smith&#10;yourname@gmail.com"
                style="width:100%;box-sizing:border-box;font-family:inherit;"></textarea>
      <div class="sm-note">
        Files you own must never be mistaken for a student's work. List your
        school login, display name, and any Gmail the class folder is shared
        through (matched case-insensitively as a substring). Saved into the cloud
        settings, so other machines pick them up automatically. Reload the
        assignment after saving.
        <div style="margin-top:6px;">
          <button id="identitiesSaveBtn" class="secondary" style="padding:4px 10px;">Save identities</button>
        </div>
      </div>
      <label class="sm-anon" style="margin-top:14px;">
        <input id="tokenBootstrapToggle" type="checkbox">
        <span>Seed sign-in from the cloud folder (this device)</span>
      </label>
      <div class="sm-note">
        When on, and you haven't signed in on this machine yet, the workspace
        copies a <code>token.json</code> you placed in the cloud sync folder so you
        skip the browser sign-in. Off by default. Tradeoff: that token grants
        read-only Drive access to anyone who can read the cloud folder — your call.
        Takes effect on the next sign-in; refreshes are always kept on this device
        only.
      </div>
      <div class="sm-note" style="margin-top:10px;">
        <b>Local-folder assignments</b> (a class whose master directory is a
        local path) grade here too — PDFs and images only. Student identity
        follows Google Classroom's layout: a <b>subfolder per student</b>
        (subfolder name = student) when the assignment folder has subfolders,
        otherwise the <b>filename stem</b> is the student. Lateness is derived
        from each file's saved-on date (not necessarily the true submission
        time) — correct it with the Late tick, which sticks. Video and Office
        files show a download link; export those to PDF to grade them inline.
      </div>
      <div class="sm-foot">
        <span id="settingsStatus" class="sm-note"></span>
        <span style="flex:1"></span>
        <button id="settingsDoneBtn">Close</button>
      </div>
    </div>
  </div>

  <!-- Assignment setup: deadline + which MYP criteria are being assessed -->
  <div id="setupbar" class="hidden">
    <label class="setup-field">
      <span>Deadline</span>
      <input id="deadlineInput" type="datetime-local"
             title="Files created after this are flagged Late">
    </label>
    <span class="setup-sep"></span>
    <span class="setup-label">Assess MYP Criteria:</span>
    <span id="criteriaBoxes"></span>
  </div>

  <div id="split">
    <div id="left">
      <div id="roster"></div>
      <div id="overlay"><img id="overlayImg" alt=""></div>
    </div>
    <div id="divider"></div>
    <div id="right">
      <h2>Grading Sheet</h2>
      <!-- Shown when any work carries a MODIFIED marker (grade changed in
           CAM since the last export) — sits above the keyword checklist. -->
      <div id="camModNote">
        <b>MODIFIED</b> works below had their grade changed in the CAM
        dashboard after your last export. Re-check the keyword checklist for
        each one — CAM only carries the final 0–8 grade, not the checklist
        detail behind it. Click a MODIFIED marker to dismiss it once reviewed;
        exporting clears them all.
      </div>
      <div id="kwEditor">
        <span>Keywords:</span> <span id="tagList"></span>
        <input id="newKw" type="text" placeholder="add keyword…" size="14" autocomplete="off">
        <select id="newKwType">
          <option value="positive">strength</option>
          <option value="growth">growth</option>
        </select>
        <button class="secondary" id="addKwBtn" style="padding:4px 10px;">Add</button>
      </div>
      <div id="tableWrap"><div class="empty">Load a folder to begin grading.</div></div>
    </div>
  </div>
</div>

<script>
const GRADES = ["", "0","1","2","3","4","5","6","7","8"];

// The four MYP assessment criteria. Each is graded 0-8 independently; the
// teacher ticks which subset applies to the current assignment.
const MYP_CRITERIA = [
  {id:"A", desc:"Investigating"},
  {id:"B", desc:"Developing"},
  {id:"C", desc:"Creating"},
  {id:"D", desc:"Evaluating"},
];
let SELECTED_CRITERIA = [];   // e.g. ["A","C"] — drives the matrix grade columns
let DEADLINE = "";            // official deadline (datetime-local string)
let CLASS_FOLDER_ID = "";     // parent class folder currently loaded
let ACTIVE_CLASS_NAME = "";   // selected class label -> cloud subfolder routing

// App settings mirrored from /api/config: cloud sync dir + {className: folderId}
// + the teacher's own identities (editable here; heals across machines).
let SETTINGS = {cloud_dir:"", classes:{}, my_identities:[], cloud_dir_exists:false};

// Default rubric template. Used only as a fallback when a folder has no saved
// checklist yet — never mutated, so we can always restore a clean baseline.
const DEFAULT_KEYWORDS = [
  {label:"Line Quality", type:"positive"},
  {label:"Shading", type:"positive"},
  {label:"Composition", type:"positive"},
  {label:"Color Use", type:"positive"},
  {label:"Creativity", type:"positive"},
  {label:"Craftsmanship", type:"positive"},
  {label:"High Effort", type:"positive"},
  {label:"Areas for Growth", type:"growth"},
  {label:"Needs Refinement", type:"growth"},
  {label:"Incomplete", type:"growth"},
];
let KEYWORDS = DEFAULT_KEYWORDS.map(k => ({...k}));   // live, editable rubric

let STUDENTS = [];                // canonical order (stable for the table)
const byKey = {};                 // key -> student
let selectedKey = null;           // highlighted student
let expandedKey = null;           // student whose stack drawer is open

let GROUPS = [];                  // [{id, members:[key], color}] pair-work links
let linkMode = null;              // key of card awaiting a partner, or null

function groupForKey(key){ return GROUPS.find(g => g.members.includes(key)); }
function shortIdOf(st){
  if (!st) return "";
  if (st.display_id) return st.display_id;        // computed on the backend
  const base = st.email || st.name || "";         // frontend fallback split
  return base.includes("@") ? base.split("@")[0] : base;
}

const ROT = {};                   // fileId -> rotation degrees (0/90/180/270)

// Video magnification state (only one video may be enlarged at a time)
let videoZoomActive = false;
let zoomVideoFid = null;
let zoomVideoEl = null;
let zoomReturnWrap = null;
let docFocusActive = false;   // a PDF / Google-native doc is filling the left panel
let docFrameEl = null;

const $ = sel => document.querySelector(sel);
const roster = $("#roster");
const tableWrap = $("#tableWrap");

/* ---------- Step 1: load the class folder -> list its assignments ----------
   The manual Folder ID box is gone: classes are managed in ⚙ Settings and
   picked from the dropdown, which hands the mapped Drive folder ID here. */
async function loadClass(folderId) {
  const v = (folderId || "").trim();
  if (!v) { alert("Pick a class from the dropdown first (add classes in ⚙ Settings)."); return; }
  // Resolve which saved class this folder ID belongs to (drives cloud routing).
  const idOnly = (v.match(/\/folders\/([A-Za-z0-9_-]+)/) || [,v])[1];
  const match = Object.entries(SETTINGS.classes || {})
    .find(([, id]) => id === idOnly || id === v);
  ACTIVE_CLASS_NAME = match ? match[0] : "";
  $("#classSelect").value = ACTIVE_CLASS_NAME;
  setStatus("Listing assignments… (a browser auth window may open the first time)");
  try {
    const res = await fetch("/api/class", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({class_folder_id:v})
    });
    const data = await res.json();
    if (!res.ok) { setStatus(""); alert(data.error || "Failed to load class."); return; }
    CLASS_FOLDER_ID = data.class_folder_id;
    const sel = $("#assignmentSelect");
    sel.innerHTML = '<option value="">Choose assignment…</option>';
    (data.assignments || []).forEach(a => {
      const o = document.createElement("option");
      o.value = a.id; o.textContent = a.name; sel.appendChild(o);
    });
    sel.classList.remove("hidden");
    $("#gradeBtn").classList.remove("hidden");
    $("#folderName").textContent = data.class_folder_name;
    // Locally-programmed exams for this class join the same dropdown.
    await loadExamOptions(sel);
    setStatus(data.assignments.length + " assignment(s) found — pick one to grade.");
  } catch (e) { setStatus(""); alert("Error: " + e); }
}

/* Append this class's programmed exams (from Exam Setup) to the assignment
   dropdown as an "Exams" group; their values are prefixed "exam::". */
async function loadExamOptions(sel) {
  if (!ACTIVE_CLASS_NAME) return;
  try {
    const res = await fetch("/api/exams?class_name=" + encodeURIComponent(ACTIVE_CLASS_NAME));
    const d = await res.json();
    const names = Object.keys(d.exams || {}).sort();
    if (!names.length) return;
    const og = document.createElement("optgroup"); og.label = "📝 Exams";
    names.forEach(n => {
      const o = document.createElement("option");
      o.value = "exam::" + n; o.textContent = "📝 " + n;
      og.appendChild(o);
    });
    sel.appendChild(og);
  } catch (e) { console.warn("exam list failed", e); }
}

/* Route the dropdown: Drive assignment subfolders vs programmed exams. */
function openSelectedAssignment() {
  const v = $("#assignmentSelect").value;
  if (!v) { alert("Choose an assignment from the dropdown first."); return; }
  if (v.startsWith("exam::")) loadExam(v.slice(6));
  else loadFolder();
}

/* ---------- Step 2: load the chosen assignment subfolder ---------- */
async function loadFolder() {
  const v = $("#assignmentSelect").value;
  if (!v) { alert("Choose an assignment from the dropdown first."); return; }
  exitExamMode();
  setStatus("Loading…");
  try {
    const res = await fetch("/api/load", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({folder_id:v, class_folder_id:CLASS_FOLDER_ID,
                            class_name:ACTIVE_CLASS_NAME})
    });
    const data = await res.json();
    if (!res.ok) { setStatus(""); alert(data.error || "Failed to load."); return; }
    // Title the header with CAM's assignment name when the load came through
    // the CAM bridge (a rename in CAM shows here); the physical Drive folder
    // name — still what the dropdown lists — is the fallback for plain use.
    $("#folderName").textContent = data.cam_name || data.folder_name;
    let s = data.student_count + " student(s) · " + data.file_count + " file(s)";
    if (data.unknown_owner_count) s += " · " + data.unknown_owner_count + " with no owner metadata";
    setStatus(s);
    STUDENTS = data.students;
    GROUPS = data.groups || [];
    // Restore saved assignment setup (criteria + deadline) for this folder.
    SELECTED_CRITERIA = Array.isArray(data.criteria) ? data.criteria.slice() : [];
    DEADLINE = data.deadline || "";
    $("#deadlineInput").value = DEADLINE;
    $("#setupbar").classList.remove("hidden");
    renderCriteriaBoxes();
    // Rebuild the rubric headers from the saved cache for THIS folder. A
    // non-empty list replaces the defaults; an empty/absent list keeps them.
    if (Array.isArray(data.checklist) && data.checklist.length) {
      KEYWORDS = data.checklist.map(k => ({
        label: String(k.label || "").trim(),
        type:  k.type === "growth" ? "growth" : "positive",
      })).filter(k => k.label);
    } else {
      KEYWORDS = DEFAULT_KEYWORDS.map(k => ({...k}));   // restore template
    }
    for (const k in byKey) delete byKey[k];
    STUDENTS.forEach(st => {
      byKey[st.key] = st;
      // Default the Late flag from the deadline the first time (no saved
      // decision). A persisted true/false override always wins.
      if (st.late_marked === null || st.late_marked === undefined) {
        st.late_marked = isLate(st);
      }
    });
    selectedKey = null; expandedKey = null; linkMode = null;
    renderTags();
    renderTable();
    renderRoster();
    updateCamModNote();   // advisory above the checklist when anything is MODIFIED
  } catch (e) { setStatus(""); alert("Error: " + e); }
}
function setStatus(t){ $("#status").textContent = t; }

/* ---------- App settings (cloud dir + class map) ---------- */
async function loadConfig() {
  try {
    const res = await fetch("/api/config");
    SETTINGS = await res.json();
  } catch (e) { console.warn("config load failed", e); SETTINGS = {cloud_dir:"", classes:{}, my_identities:[]}; }
  populateClassSelect();
}

function populateClassSelect() {
  const sel = $("#classSelect");
  const cur = sel.value;
  sel.innerHTML = '<option value="">Select class…</option>';
  Object.keys(SETTINGS.classes || {}).sort().forEach(name => {
    const o = document.createElement("option");
    o.value = name; o.textContent = name; sel.appendChild(o);
  });
  if (cur && SETTINGS.classes && SETTINGS.classes[cur]) sel.value = cur;
}

/* Picking a saved class loads its mapped Drive folder's assignments. */
function onClassPicked() {
  const name = $("#classSelect").value;
  if (!name) { ACTIVE_CLASS_NAME = ""; return; }
  const fid = (SETTINGS.classes || {})[name];
  if (!fid) return;
  ACTIVE_CLASS_NAME = name;
  loadClass(fid);        // lists the assignment subfolders for this class
}

/* ---------- Theme preference (device-local -> localStorage, not synced) ---------- */
const THEME_KEY = "gcg_theme";
const themeMq = window.matchMedia("(prefers-color-scheme: dark)");
function applyTheme() {
  const pref = localStorage.getItem(THEME_KEY) || "auto";
  document.documentElement.dataset.theme =
    pref === "auto" ? (themeMq.matches ? "dark" : "light") : pref;
}
themeMq.addEventListener("change", applyTheme);   // "auto" follows live OS switches
$("#themeSelect").addEventListener("change", () => {
  localStorage.setItem(THEME_KEY, $("#themeSelect").value);
  applyTheme();
});

/* ---------- Settings modal ---------- */
function openSettings() {
  $("#themeSelect").value = localStorage.getItem(THEME_KEY) || "auto";
  $("#cloudDirInput").value = SETTINGS.cloud_dir || "";
  renderCloudNote();
  renderClassRows(SETTINGS.classes || {});
  $("#identitiesInput").value = (SETTINGS.my_identities || []).join("\n");
  $("#settingsStatus").textContent = "";
  $("#settingsOverlay").classList.remove("hidden");
  // Device-local prefs (server-side file): the Anonymous-grading and
  // token-bootstrap toggles. Read their current values fresh each open.
  fetch("/api/prefs").then(r => r.json())
    .then(p => {
      $("#anonToggle").checked = !!p.anonymous_grading;
      $("#tokenBootstrapToggle").checked = !!p.token_bootstrap;
    })
    .catch(() => {});
}

/* Save the editable "My identities" list to /api/config (root + cloud mirror),
   so this device — and every other one reading the cloud folder — stops
   mistaking the teacher's own files for a student's. */
$("#identitiesSaveBtn").addEventListener("click", async () => {
  const ids = $("#identitiesInput").value.split("\n")
    .map(s => s.trim()).filter(Boolean);
  $("#settingsStatus").textContent = "Saving identities…";
  try {
    const res = await fetch("/api/config", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({my_identities: ids})
    });
    SETTINGS = await res.json();
    $("#identitiesInput").value = (SETTINGS.my_identities || []).join("\n");
    $("#settingsStatus").textContent = "Identities saved. Reload the assignment to apply.";
  } catch (e) {
    console.warn("identities save failed", e);
    $("#settingsStatus").textContent = "Could not save identities.";
  }
});

/* Token-bootstrap toggle: a device-local pref, like Anonymous grading. Takes
   effect on the next OAuth sign-in (seeds an absent token from the cloud dir). */
$("#tokenBootstrapToggle").addEventListener("change", async () => {
  const on = $("#tokenBootstrapToggle").checked;
  try {
    await fetch("/api/prefs", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({token_bootstrap: on})
    });
  } catch (e) { console.warn("prefs save failed", e); }
  $("#settingsStatus").textContent = on
    ? "Sign-in will be seeded from the cloud folder on next login."
    : "Cloud sign-in seeding off.";
});

/* Persist the Anonymous-grading toggle, then rebuild the open assignment's
   payload so tiles + matrix switch between "Work NN" and real names at once. */
$("#anonToggle").addEventListener("change", async () => {
  const on = $("#anonToggle").checked;
  try {
    await fetch("/api/prefs", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({anonymous_grading: on})
    });
  } catch (e) { console.warn("prefs save failed", e); }
  $("#settingsStatus").textContent = on ? "Anonymous grading on." : "Anonymous grading off.";
  if (EXAM && EXAM.exam_name) {
    loadExam(EXAM.exam_name);   // re-fetch the exam so names blank/unblank at once
  } else if (STUDENTS.length && $("#assignmentSelect").value &&
      !$("#assignmentSelect").value.startsWith("exam::")) {
    loadFolder();     // re-fetch the assignment so the new payload takes effect
  }
});
function closeSettings() { $("#settingsOverlay").classList.add("hidden"); }

function renderCloudNote() {
  const note = $("#cloudDirNote");
  if (!SETTINGS.cloud_dir) {
    note.textContent = "Not linked yet — open a class or assignment from the CAM dashboard to point the workspace at CAM's data folder.";
  } else if (SETTINGS.cloud_dir_exists) {
    note.textContent = "Exports + state cache route to: " + SETTINGS.cloud_dir + "\\[Class Name]\\";
  } else {
    note.textContent = "⚠ CAM set this path but it was not found on disk. It will be used once it exists.";
  }
}

/* Read-only view of the CAM-managed class map: name -> Drive folder ID. These
   are seeded by the CAM dashboard on every handoff, so the workspace only
   displays them — editing here is gone to keep the two apps from drifting. */
function renderClassRows(classes) {
  const wrap = $("#classRows"); wrap.innerHTML = "";
  const entries = Object.entries(classes || {}).sort((a, b) => a[0].localeCompare(b[0]));
  if (!entries.length) {
    const empty = document.createElement("div");
    empty.className = "sm-note";
    empty.textContent = "No classes linked yet — open a class from the CAM dashboard.";
    wrap.appendChild(empty);
    return;
  }
  entries.forEach(([n, id]) => {
    const row = document.createElement("div"); row.className = "classrow";
    const nm = document.createElement("input");
    nm.className = "cname"; nm.value = n; nm.readOnly = true; nm.tabIndex = -1;
    const cid = document.createElement("input");
    cid.className = "cid"; cid.value = id; cid.readOnly = true; cid.tabIndex = -1;
    row.appendChild(nm); row.appendChild(cid);
    wrap.appendChild(row);
  });
}

/* ---------- Assignment setup: MYP criteria checkboxes + deadline ---------- */
function renderCriteriaBoxes() {
  const wrap = $("#criteriaBoxes"); wrap.innerHTML = "";
  MYP_CRITERIA.forEach(c => {
    const lab = document.createElement("label");
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = c.id;
    cb.checked = SELECTED_CRITERIA.includes(c.id);
    cb.addEventListener("change", () => {
      if (cb.checked) { if (!SELECTED_CRITERIA.includes(c.id)) SELECTED_CRITERIA.push(c.id); }
      else SELECTED_CRITERIA = SELECTED_CRITERIA.filter(x => x !== c.id);
      SELECTED_CRITERIA.sort();
      pushSettings();
      renderTable();          // grade columns follow the selected criteria
    });
    const txt = document.createElement("span");
    txt.innerHTML = "Crit " + c.id + ' <span class="cdesc">' + c.desc + "</span>";
    lab.appendChild(cb); lab.appendChild(txt);
    wrap.appendChild(lab);
  });
}

async function pushSettings() {
  if (!STUDENTS.length) return;     // settings attach to a loaded folder
  try {
    await fetch("/api/settings", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({criteria: SELECTED_CRITERIA, deadline: DEADLINE})
    });
  } catch (e) { console.warn("settings save failed", e); }
}

/* ---------- Late detection ----------
   A student's submission is late when their newest file was created after the
   deadline. Returns false when no deadline is set or no timestamp is known. */
function isLate(st) {
  if (!DEADLINE) return false;
  const due = new Date(DEADLINE);
  if (isNaN(due)) return false;
  const newest = (st.files && st.files[0]) ? st.files[0] : null;
  if (!newest || !newest.created_time) return false;
  const made = new Date(newest.created_time);
  return !isNaN(made) && made > due;
}

/* Sum of a student's selected-criterion grades (numbers only). */
function gradeSum(st) {
  const g = st.grades || {};
  let total = 0, any = false;
  const crits = SELECTED_CRITERIA.length ? SELECTED_CRITERIA : Object.keys(g);
  crits.forEach(c => {
    const v = g[c];
    if (v !== undefined && String(v).trim() !== "") { total += Number(v) || 0; any = true; }
  });
  return any ? total : null;
}

/* Card/drawer grade chip text. With one criterion the sum IS the grade, so we
   show a bare number; with several we prefix Σ to signal it's a total. */
function gradeChipText(st) {
  const sum = gradeSum(st);
  if (sum === null) return "";
  const n = SELECTED_CRITERIA.length || Object.keys(st.grades || {}).length;
  return n > 1 ? ("Σ" + sum) : String(sum);
}

/* ---------- Roster (sorts by grade desc, ungraded last) ---------- */
function rosterSorted() {
  return [...STUDENTS].sort((a,b) => {
    const ag = a.graded ? 1 : 0, bg = b.graded ? 1 : 0;
    if (ag !== bg) return bg - ag;
    if (ag) { const d = (gradeSum(b) || 0) - (gradeSum(a) || 0); if (d) return d; }
    return a.name.localeCompare(b.name);
  });
}

function renderRoster() {
  roster.innerHTML = "";
  if (!STUDENTS.length) return;
  const rendered = new Set();
  rosterSorted().forEach(st => {
    if (rendered.has(st.key)) return;
    const g = groupForKey(st.key);
    if (g) {                                   // render the whole group box once
      roster.appendChild(makeGroupBox(g));
      g.members.forEach(m => rendered.add(m));
    } else {
      roster.appendChild(st.key === expandedKey ? makeExpandedCard(st) : makeCard(st));
      rendered.add(st.key);
    }
  });
}

/* Combined "Group Work" bounding box holding all linked partner cards. */
function makeGroupBox(g) {
  const box = document.createElement("div");
  box.className = "groupbox";
  box.dataset.gid = g.id;
  box.style.borderColor = g.color;

  const head = document.createElement("div"); head.className = "ghead";
  head.style.color = g.color;
  const ids = g.members.map(k => shortIdOf(byKey[k]) || k).join("  +  ");
  const t = document.createElement("span"); t.className = "gchain"; t.textContent = "🔗";
  const ti = document.createElement("span"); ti.textContent = "Group Work";
  const gi = document.createElement("span"); gi.className = "gids"; gi.textContent = ids;
  head.appendChild(t); head.appendChild(ti); head.appendChild(gi);
  const un = document.createElement("button");
  un.className = "gunlink"; un.title = "Unlink this group"; un.textContent = "✕";
  un.addEventListener("click", e => { e.stopPropagation(); unlinkGroup(g.id); });
  head.appendChild(un);
  box.appendChild(head);

  const inner = document.createElement("div"); inner.className = "ginner";
  inner.style.gridTemplateColumns = roster.style.gridTemplateColumns || "repeat(3, 1fr)";
  g.members.forEach(k => {
    const st = byKey[k]; if (!st) return;
    inner.appendChild(st.key === expandedKey ? makeExpandedCard(st) : makeCard(st));
  });
  box.appendChild(inner);
  return box;
}

function makeCard(st) {
  const card = document.createElement("div");
  card.className = "scard" + (st.graded ? " graded" : "") + (st.key===selectedKey ? " selected" : "");
  card.dataset.key = st.key;

  const newest = st.files[0];
  const media = newest ? buildMedia(st, newest, "preview", "preview")
                       : phEl("preview", null);
  card.appendChild(media);

  const link = document.createElement("button");
  link.className = "linkbtn" + (linkMode===st.key ? " arming" : "");
  link.title = linkMode===st.key ? "Click a partner card to link (or click again to cancel)"
                                 : "Link Partner";
  link.textContent = "🔗";
  link.addEventListener("click", (e) => { e.stopPropagation(); onLinkClick(st.key); });
  card.appendChild(link);

  const cb = document.createElement("div"); cb.className="countbadge";
  cb.textContent = st.count + (st.count===1 ? " File" : " Files");
  card.appendChild(cb);
  const chk = document.createElement("div"); chk.className="checkbadge"; chk.textContent="✓"; card.appendChild(chk);
  const sum = gradeSum(st);
  const gc = document.createElement("div"); gc.className="gradechip";
  gc.textContent = gradeChipText(st); card.appendChild(gc);
  if (st.late_marked) {
    const lb = document.createElement("div"); lb.className = "latebadge";
    lb.textContent = "Late"; lb.title = "Marked late (uncheck the Late box to waive)";
    card.appendChild(lb);
  }
  if ((st.cam_modified || []).length) {
    const mb = document.createElement("div"); mb.className = "cam-modified cardmodified";
    mb.textContent = "MODIFIED";
    mb.title = "Grade changed in the CAM dashboard after your last export — " +
               "re-check the checklist (dismiss via the marker in the grading sheet).";
    card.appendChild(mb);
  }

  const meta = document.createElement("div"); meta.className="meta";
  meta.innerHTML = `<div class="nm">${escapeHtml(st.name)}</div>`
                 + `<div class="sub">newest: ${escapeHtml(newest ? newest.filename : "—")}</div>`;
  card.appendChild(meta);

  card.addEventListener("click", () => {
    if (linkMode && linkMode !== st.key) {        // complete a pending link
      const a = linkMode; linkMode = null; linkPartners(a, st.key); return;
    }
    if (linkMode === st.key) {                     // cancel arming
      linkMode = null; setStatus(""); renderRoster(); return;
    }
    expandedKey = st.key; selectStudent(st.key, true); renderRoster();
  });
  return card;
}

/* ---------- Pair-work linking ---------- */
function onLinkClick(key) {
  if (linkMode === null) {                          // arm: wait for a partner
    linkMode = key;
    setStatus("Link mode: click a partner card to link with " + shortIdOf(byKey[key]) + " (click 🔗 again to cancel)");
    renderRoster();
  } else if (linkMode === key) {                    // toggle off
    linkMode = null; setStatus(""); renderRoster();
  } else {                                          // second card -> link them
    const a = linkMode; linkMode = null; linkPartners(a, key);
  }
}

async function linkPartners(a, b) {
  setStatus("Linking…");
  try {
    const res = await fetch("/api/group/link", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({a_key:a, b_key:b})
    });
    const data = await res.json();
    if (!res.ok) { setStatus(""); alert(data.error || "Link failed."); return; }
    GROUPS = data.groups || [];
    (data.students || []).forEach(s => { if (byKey[s.key]) Object.assign(byKey[s.key], s); });
    setStatus("");
    renderTable();       // adds chain badges (matrix stays in fixed order)
    renderRoster();      // draws the combined Group Work box
  } catch (e) { setStatus(""); alert("Link error: " + e); }
}

async function unlinkGroup(gid) {
  try {
    const res = await fetch("/api/group/unlink", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({group_id:gid})
    });
    const data = await res.json();
    GROUPS = data.groups || [];
    renderTable();
    renderRoster();
  } catch (e) { alert("Unlink error: " + e); }
}

function makeExpandedCard(st) {
  const card = document.createElement("div");
  card.className = "scard expanded" + (st.graded ? " graded" : "")
                + (st.key===selectedKey ? " selected" : "");
  card.dataset.key = st.key;

  const drawer = document.createElement("div"); drawer.className = "drawer";

  const head = document.createElement("div"); head.className = "dhead";
  const chip = gradeChipText(st);
  head.innerHTML = `<span class="dn">${escapeHtml(st.name)}</span>`
                 + `<span class="dc">${st.count} file(s)${st.email ? " · " + escapeHtml(st.email) : ""}</span>`
                 + (chip ? `<span class="dg">${chip}</span>` : "")
                 + (st.late_marked ? `<span class="dlate">Late</span>` : "");
  const collapse = document.createElement("button");
  collapse.className = "secondary collapse"; collapse.textContent = "Collapse";
  collapse.style.padding = "4px 10px";
  collapse.addEventListener("click", (e) => { e.stopPropagation(); expandedKey = null; renderRoster(); });
  head.appendChild(collapse);
  drawer.appendChild(head);

  const stack = document.createElement("div"); stack.className = "stack";
  st.files.forEach((f, idx) => stack.appendChild(makeTile(st, f, idx===0)));
  drawer.appendChild(stack);

  card.appendChild(drawer);
  return card;
}

function makeTile(st, f, isNewest) {
  const tile = document.createElement("div"); tile.className = "stile";
  const media = buildMedia(st, f, "", "ph2");
  tile.appendChild(media);

  if (isNewest) { const b=document.createElement("div"); b.className="newest"; b.textContent="NEWEST"; tile.appendChild(b); }
  if (f.flagged) { const b=document.createElement("div"); b.className="draft"; b.textContent="draft?"; b.title="Same name as a newer file"; tile.appendChild(b); }

  if (f.embed_url || f.web_view) {
    const a = document.createElement("a"); a.className="openlink";
    a.href = f.web_view || f.embed_url; a.target="_blank"; a.textContent="↗ open";
    a.addEventListener("click", e => e.stopPropagation());
    tile.appendChild(a);
  }

  const fn = document.createElement("div"); fn.className="fn"; fn.textContent = f.filename; tile.appendChild(fn);

  // Clicking any file highlights/focuses this student's row; a PDF or a
  // Google-native doc also opens the focused viewer over the left panel.
  tile.addEventListener("click", () => {
    selectStudent(st.key, true);
    if (f.kind === "pdf" || f.embed_url) enterDocFocus(f);
  });
  return tile;
}

function phEl(cls, f) {
  const d = document.createElement("div"); d.className = cls;
  if (!f) { d.textContent = "No files"; return d; }
  d.textContent = f.kind==="slides" ? "Google Slides — open ↗"
                : f.kind==="doc" ? "Google Doc — open ↗"
                : f.kind==="pdf" ? "PDF — open ↗"
                : "No preview\n" + f.filename;
  return d;
}

/* ---------- Unified media builder (thumbnail / video / rotate) ----------
   Returns a .mwrap wrapper holding the static thumbnail. For videos it wires
   hover-to-play; for static images it wires the zoom overlay + a rotate button.
   The static thumbnail is ALWAYS what loads on first paint, so initial network
   and memory use stays near-zero even on classes full of stop-motion videos. */
function buildMedia(st, f, imgClass, phClass) {
  const wrap = document.createElement("div");
  wrap.className = "mwrap";

  let base;
  if (f.has_thumb) {
    base = document.createElement("img");
    if (imgClass) base.className = imgClass;
    base.loading = "lazy";
    base.dataset.fid = f.id;
    base.src = "/api/thumbnail/" + f.id;
    base.alt = f.filename;
    applyRotation(base);
    base.onerror = () => base.replaceWith(phEl(phClass, f));
  } else {
    base = phEl(phClass, f);
  }
  wrap.appendChild(base);

  if (f.is_video) {
    wrap.classList.add("is-video");
    const tag = document.createElement("div"); tag.className = "videotag"; tag.textContent = "VIDEO";
    const pb  = document.createElement("div"); pb.className  = "playbadge"; pb.textContent  = "▶";
    wrap.appendChild(tag); wrap.appendChild(pb);
    attachVideoHover(wrap, f);
  } else if (f.has_thumb) {
    attachHoverZoom(base, f.id);
    const rb = document.createElement("button");
    rb.className = "rotbtn"; rb.title = "Rotate 90° clockwise"; rb.textContent = "↻";
    rb.addEventListener("click", (e) => { e.stopPropagation(); rotateFile(f.id); });
    wrap.appendChild(rb);
  }
  return wrap;
}

/* ---------- Image rotation (static thumbnails only) ---------- */
function applyRotation(img) {
  const deg = ROT[img.dataset.fid] || 0;
  img.style.transform = deg ? `rotate(${deg}deg)` : "";
}
function rotateFile(fid) {
  ROT[fid] = ((ROT[fid] || 0) + 90) % 360;   // 0 -> 90 -> 180 -> 270 -> 0
  document.querySelectorAll(`img[data-fid="${cssEsc(fid)}"]`).forEach(applyRotation);
  if (hoverFid === fid && overlay.style.display === "block"
      && !videoZoomActive && !docFocusActive) {
    applyOverlayRotation();
    positionOverlay(hoverEl);
  }
}

/* ---------- Hover + scroll zoom overlay (locked inside #left) ---------- */
const overlay = $("#overlay");
const overlayImg = $("#overlayImg");
const leftPanel = $("#left");
let hoverEl = null, hoverScale = 2, hoverFid = null;

function attachHoverZoom(img, fileId) {
  img.addEventListener("mouseenter", () => {
    if (videoZoomActive || docFocusActive) return;  // a media/doc overlay owns #overlay
    hoverEl = img; hoverScale = 2; hoverFid = fileId;
    overlay.classList.remove("video-mode");
    overlayImg.src = "/api/thumbnail/" + fileId + "?sz=1600";
    overlay.style.display = "block";
    applyOverlayRotation();
    positionOverlay(img);
  });
  img.addEventListener("mousemove", () => { if (hoverEl===img && !docFocusActive) positionOverlay(img); });
  img.addEventListener("mouseleave", () => {
    if (docFocusActive) return;              // don't tear down a focused doc overlay
    if (hoverEl===img) { hoverEl = null; hoverFid = null; overlay.style.display = "none"; }
  });
  img.addEventListener("wheel", (ev) => {
    if (hoverEl !== img || videoZoomActive || docFocusActive) return;
    ev.preventDefault();
    hoverScale += (ev.deltaY < 0 ? 0.35 : -0.35);
    if (hoverScale < 1.2) hoverScale = 1.2;
    positionOverlay(img);
  }, {passive:false});
}

function applyOverlayRotation() {
  const deg = ROT[hoverFid] || 0;            // overlay shows artwork right-side-up
  overlayImg.style.transform = deg ? `rotate(${deg}deg)` : "";
}

function positionOverlay(img) {
  const panel = leftPanel.getBoundingClientRect();
  const pad = 8;
  const maxW = panel.width  - pad*2;
  const maxH = panel.height - pad*2;

  let w = img.clientWidth  * hoverScale;
  let h = img.clientHeight * hoverScale;
  w = Math.min(w, maxW); h = Math.min(h, maxH);

  // When rotated a quarter-turn, use a square box so the rotated (contained)
  // image always fits inside the overlay without spilling.
  if (((ROT[hoverFid] || 0) % 180) === 90) { const s = Math.min(w, h); w = s; h = s; }

  const r = img.getBoundingClientRect();
  let left = (r.right - panel.left) + leftPanel.scrollLeft + 10;
  let top  = (r.top   - panel.top)  + leftPanel.scrollTop;

  const leftMax = leftPanel.scrollLeft + maxW + pad - w;
  const leftMin = leftPanel.scrollLeft + pad;
  if (left > leftMax) left = (r.left - panel.left) + leftPanel.scrollLeft - w - 10; // flip
  if (left < leftMin) left = leftMin;

  const topMax = leftPanel.scrollTop + maxH + pad - h;
  const topMin = leftPanel.scrollTop + pad;
  if (top > topMax) top = topMax;
  if (top < topMin) top = topMin;

  overlay.style.width = w + "px";
  overlay.style.height = h + "px";
  overlay.style.left = left + "px";
  overlay.style.top = top + "px";
}

/* ---------- Hover-to-play video (memory-safe: built on enter, destroyed on
   leave so no stream stays live when the pointer moves away) ---------- */
function attachVideoHover(wrap, f) {
  let video = null;

  function build() {
    const v = document.createElement("video");
    v.src = f.video_src;
    v.muted = true; v.loop = true; v.autoplay = true; v.controls = true;
    v.playsInline = true;
    v.setAttribute("playsinline", "");
    v.setAttribute("webkit-playsinline", "");
    v.preload = "metadata";
    v.className = "inlinevid";
    v.dataset.fid = f.id;
    // Don't let the scrubber/controls bubble a click up to card-expand/select.
    v.addEventListener("click", (e) => e.stopPropagation());
    return v;
  }
  function teardown() {
    if (!video) return;
    try { video.pause(); } catch (e) {}
    video.removeAttribute("src");
    try { video.load(); } catch (e) {}   // forces the browser to drop the stream
    video.remove();
    video = null;
    wrap.classList.remove("playing");
  }

  wrap.addEventListener("mouseenter", () => {
    if (videoZoomActive || docFocusActive) return;
    if (!video) {
      video = build();
      wrap.appendChild(video);
      wrap.classList.add("playing");
      const p = video.play(); if (p && p.catch) p.catch(() => {});
    }
  });
  wrap.addEventListener("mouseleave", () => {
    if (videoZoomActive && zoomVideoFid === f.id) return;  // keep playing while enlarged
    teardown();
  });
  // Scroll up = enlarge into the left-panel overlay (same live node, no reload).
  wrap.addEventListener("wheel", (ev) => {
    if (!video || videoZoomActive) return;
    if (ev.deltaY < 0) { ev.preventDefault(); enterVideoZoom(wrap, video, f); video = null; }
  }, {passive:false});
  // Double-click also enlarges.
  wrap.addEventListener("dblclick", (e) => {
    if (video && !videoZoomActive) { e.preventDefault(); enterVideoZoom(wrap, video, f); video = null; }
  });
}

/* ---------- Video magnification (2x / full left-panel overlay) ---------- */
function enterVideoZoom(wrap, video, f) {
  videoZoomActive = true; zoomVideoFid = f.id; zoomReturnWrap = wrap; zoomVideoEl = video;
  overlay.style.display = "block";
  overlay.classList.add("video-mode");
  overlayImg.style.display = "none";
  // Relocate the SAME element -> playback position, buffering & controls survive.
  video.className = "zoomvid";
  video.controls = true;
  overlay.appendChild(video);
  wrap.classList.remove("playing");
  sizeVideoOverlay();
  ensureCloseBtn();
}
function sizeVideoOverlay() {
  const panel = leftPanel.getBoundingClientRect();
  const pad = 12;
  overlay.style.width  = (panel.width  - pad*2) + "px";
  overlay.style.height = (panel.height - pad*2) + "px";
  overlay.style.left   = (leftPanel.scrollLeft + pad) + "px";
  overlay.style.top    = (leftPanel.scrollTop  + pad) + "px";
}
function ensureCloseBtn() {
  if (overlay.querySelector(".ovclose")) return;
  const b = document.createElement("button");
  b.className = "ovclose"; b.textContent = "✕ Close";
  b.addEventListener("click", (e) => { e.stopPropagation(); closeVideoZoom(); });
  overlay.appendChild(b);
}
function closeVideoZoom() {
  if (!videoZoomActive) return;
  videoZoomActive = false;
  overlay.classList.remove("video-mode");
  overlay.style.display = "none";
  overlayImg.style.display = "";
  const b = overlay.querySelector(".ovclose"); if (b) b.remove();
  if (zoomVideoEl) {
    try { zoomVideoEl.pause(); } catch (e) {}
    zoomVideoEl.removeAttribute("src");
    try { zoomVideoEl.load(); } catch (e) {}
    zoomVideoEl.remove();                 // free the stream entirely
  }
  zoomVideoEl = null; zoomReturnWrap = null; zoomVideoFid = null;
}
// Close the enlarged video by scrolling back down over it, or pressing Esc.
overlay.addEventListener("wheel", (ev) => {
  if (videoZoomActive && ev.deltaY > 0) { ev.preventDefault(); closeVideoZoom(); }
}, {passive:false});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && videoZoomActive) closeVideoZoom();
});
window.addEventListener("resize", () => { if (videoZoomActive) sizeVideoOverlay(); });

/* ---------- Focused document viewer (PDF native engine / Google embed) ----------
   Fills the left panel with the browser's own PDF engine (an <iframe> pointed
   at /api/pdf/<id>) or a Google-native preview embed. The native viewer supplies
   scroll, page navigation and zoom via its built-in toolbar; our only chrome is
   the ✕ close button (Escape also closes). The right-hand grading pane is
   untouched, so every grading tool keeps working while a document is focused.
   Modelled on the video-zoom overlay above, reusing the same #overlay element. */
function enterDocFocus(f) {
  const src = (f.kind === "pdf") ? ("/api/pdf/" + f.id) : f.embed_url;
  if (!src) return;
  if (videoZoomActive) closeVideoZoom();     // never stack two overlays
  if (docFocusActive) closeDocFocus();       // swap to the newly-clicked doc
  docFocusActive = true;
  overlay.classList.remove("video-mode");
  overlay.classList.add("doc-mode");
  overlayImg.style.display = "none";
  overlay.style.display = "block";
  const frame = document.createElement("iframe");
  frame.className = "docframe";
  frame.src = src;
  frame.setAttribute("title", f.filename || "Document");
  docFrameEl = frame;
  overlay.appendChild(frame);
  sizeDocOverlay();
  ensureDocCloseBtn();
}
function sizeDocOverlay() {
  const panel = leftPanel.getBoundingClientRect();
  const pad = 12;
  overlay.style.width  = (panel.width  - pad*2) + "px";
  overlay.style.height = (panel.height - pad*2) + "px";
  overlay.style.left   = (leftPanel.scrollLeft + pad) + "px";
  overlay.style.top    = (leftPanel.scrollTop  + pad) + "px";
}
function ensureDocCloseBtn() {
  if (overlay.querySelector(".ovclose")) return;
  const b = document.createElement("button");
  b.className = "ovclose"; b.textContent = "✕ Close";
  b.addEventListener("click", (e) => { e.stopPropagation(); closeDocFocus(); });
  overlay.appendChild(b);
}
function closeDocFocus() {
  if (!docFocusActive) return;
  docFocusActive = false;
  overlay.classList.remove("doc-mode");
  overlay.style.display = "none";
  overlayImg.style.display = "";
  const b = overlay.querySelector(".ovclose"); if (b) b.remove();
  if (docFrameEl) { docFrameEl.remove(); docFrameEl = null; }
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && docFocusActive) closeDocFocus();
});
window.addEventListener("resize", () => { if (docFocusActive) sizeDocOverlay(); });

/* ---------- Grading matrix (one row per student, stable order) ---------- */
function renderTable() {
  if (!STUDENTS.length) { tableWrap.innerHTML = '<div class="empty">No files.</div>'; return; }
  if (!SELECTED_CRITERIA.length) {
    tableWrap.innerHTML = '<div class="empty">Select one or more MYP criteria above to begin grading.</div>';
    return;
  }
  const t = document.createElement("table");
  const gradeCols = SELECTED_CRITERIA
    .map(c => `<th title="Criterion ${c}">Crit ${c}<br>(0–8)</th>`).join("");
  t.innerHTML = `<thead><tr>
      <th class="idcol">ID</th>${gradeCols}<th>Keywords</th><th>Comment</th>
    </tr></thead>`;
  const tb = document.createElement("tbody");
  STUDENTS.forEach(st => tb.appendChild(makeRow(st)));
  t.appendChild(tb);
  tableWrap.innerHTML = "";
  tableWrap.appendChild(t);
}

function makeRow(st) {
  const tr = document.createElement("tr");
  tr.dataset.key = st.key;
  if (st.key === selectedKey) tr.classList.add("selected");

  const tdN = document.createElement("td"); tdN.className="name idcol";
  let badge = "";
  const g = groupForKey(st.key);
  if (g) {
    const others = g.members.filter(k => k !== st.key).map(k => shortIdOf(byKey[k]) || k);
    const tip = "Linked with " + (others.join(", ") || "partner");
    badge = `<span class="rowchain" style="color:${g.color}" title="${escapeHtml(tip)}">🔗</span>`;
  }
  tdN.innerHTML = `<span class="sid">${escapeHtml(shortIdOf(st))}</span>${badge}`;
  // MODIFIED marker — this work's grade was changed in CAM since the last
  // export. Rendered before the grade cells; click = "reviewed, dismiss".
  if ((st.cam_modified || []).length) {
    const mod = document.createElement("div");
    mod.className = "cam-modified";
    mod.textContent = "MODIFIED";
    mod.title = "Grade changed in the CAM dashboard (Crit " +
                st.cam_modified.join(", ") + ") after your last export — " +
                "re-check the checklist, then click to dismiss.";
    mod.addEventListener("click", (e) => { e.stopPropagation(); dismissCamModified(st); });
    tdN.appendChild(mod);
  }
  tr.appendChild(tdN);

  // One grade selector (0–8) per selected MYP criterion.
  st.grades = st.grades || {};
  SELECTED_CRITERIA.forEach(crit => {
    const tdG = document.createElement("td");
    const sel = document.createElement("select"); sel.className="grade"; sel.dataset.crit = crit;
    GRADES.forEach(g => { const o=document.createElement("option"); o.value=g; o.textContent=g===""?"–":g;
      if (String(st.grades[crit] ?? "")===g) o.selected=true; sel.appendChild(o); });
    sel.addEventListener("change", () => {
      if (sel.value === "") delete st.grades[crit]; else st.grades[crit] = sel.value;
      save(st);
    });
    tdG.appendChild(sel); tr.appendChild(tdG);
  });

  const tdK = document.createElement("td");
  const box = document.createElement("div"); box.className="kw";

  // Special "Late" checkbox: auto-ticked for submissions past the deadline,
  // but the teacher can untick it to waive (e.g. permission granted). Shown
  // whenever the student is late by timestamp or has been marked late.
  if (DEADLINE && (isLate(st) || st.late_marked)) {
    const lab = document.createElement("label");
    const cb = document.createElement("input"); cb.type="checkbox";
    cb.checked = !!st.late_marked;
    cb.title = "Late submission — untick to waive (permission given)";
    cb.addEventListener("change", () => {
      st.late_marked = cb.checked;
      st.late_manual = true;   // hand-set: sticky against deadline re-derivation
      st.comment = autoComment(st);
      const ta = tr.querySelector("textarea.comment"); if (ta) ta.value = st.comment;
      save(st);
      renderRoster();              // late badge on the card follows the checkbox
    });
    const span = document.createElement("span");
    span.className = "late-kw"; span.textContent = "Late";
    lab.appendChild(cb); lab.appendChild(span);
    box.appendChild(lab);
  }

  KEYWORDS.forEach(k => {
    const lab = document.createElement("label");
    const cb = document.createElement("input"); cb.type="checkbox"; cb.value=k.label;
    cb.checked = st.keywords.includes(k.label);
    cb.addEventListener("change", () => {
      if (cb.checked) { if(!st.keywords.includes(k.label)) st.keywords.push(k.label); }
      else st.keywords = st.keywords.filter(x => x!==k.label);
      st.comment = autoComment(st);
      const ta = tr.querySelector("textarea.comment"); if (ta) ta.value = st.comment;
      save(st);
    });
    const span = document.createElement("span");
    span.className = k.type==="growth" ? "grow" : "pos";
    span.textContent = k.label;
    lab.appendChild(cb); lab.appendChild(span);
    box.appendChild(lab);
  });
  tdK.appendChild(box); tr.appendChild(tdK);

  const tdC = document.createElement("td");
  const ta = document.createElement("textarea"); ta.className="comment";
  ta.value = st.comment || "";
  ta.addEventListener("input", () => { st.comment = ta.value; });
  ta.addEventListener("blur", () => save(st));
  tdC.appendChild(ta); tr.appendChild(tdC);

  tr.addEventListener("click", () => selectStudent(st.key, false));
  return tr;
}

function autoComment(st) {
  const pos = st.keywords.filter(k => (KEYWORDS.find(x=>x.label===k)||{}).type !== "growth");
  const grow = st.keywords.filter(k => (KEYWORDS.find(x=>x.label===k)||{}).type === "growth");
  let parts = [];
  if (pos.length)  parts.push("Strengths: " + pos.join(", ") + ".");
  if (grow.length) parts.push("Areas to develop: " + grow.join(", ") + ".");
  if (st.late_marked) parts.push("Late submission.");  // driven by the Late checkbox
  return parts.join(" ");
}

/* ---------- Save -> update state, mirror partners, roster re-sort ---------- */
function refreshRow(st) {
  // Sync a partner's existing row inputs to mirrored values WITHOUT rebuilding
  // the table, so the matrix order and your scroll position never move.
  const tr = tableWrap.querySelector(`tr[data-key="${cssEsc(st.key)}"]`);
  if (!tr) return;
  const grades = st.grades || {};
  tr.querySelectorAll("select.grade").forEach(sel => {
    sel.value = grades[sel.dataset.crit] ?? "";
  });
  tr.querySelectorAll(".kw input[type=checkbox]").forEach(cb => {
    // The valueless checkbox is the special "Late" toggle.
    if (cb.value) cb.checked = st.keywords.includes(cb.value);
    else cb.checked = !!st.late_marked;
  });
  const ta = tr.querySelector("textarea.comment"); if (ta) ta.value = st.comment || "";
}

async function save(st) {
  st.graded = !!gradeSum(st) || (st.grades && Object.keys(st.grades).length > 0);
  let affected = [st];
  try {
    const res = await fetch("/api/save", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({key:st.key, grades:st.grades, keywords:st.keywords,
                            comment:st.comment, late_marked:st.late_marked,
                            late_manual:!!st.late_manual,
                            cam_modified:st.cam_modified || []})
    });
    const data = await res.json();
    const list = (data.students && data.students.length) ? data.students
               : (data.student ? [data.student] : []);
    list.forEach(s2 => {
      const local = byKey[s2.key]; if (!local) return;
      Object.assign(local, s2);
      if (local.key !== st.key) refreshRow(local);   // update mirrored partner rows
    });
    if (list.length) affected = list.map(s2 => byKey[s2.key]).filter(Boolean);
  } catch(err) { console.warn("save failed", err); }

  // Flash every affected row (the edited student + any linked partners).
  affected.forEach(s2 => {
    const tr = tableWrap.querySelector(`tr[data-key="${cssEsc(s2.key)}"]`);
    if (tr) { tr.classList.remove("row-saved"); void tr.offsetWidth; tr.classList.add("row-saved"); }
  });
  renderRoster();   // roster re-sorts; matrix stays put
}

/* ---------- MODIFIED markers (grades changed in CAM since last export) ---- */
function updateCamModNote() {
  const any = !EXAM && STUDENTS.some(s => (s.cam_modified || []).length);
  $("#camModNote").style.display = any ? "block" : "none";
}

/* Teacher clicked a MODIFIED marker: reviewed — clear it for this student. */
async function dismissCamModified(st) {
  st.cam_modified = [];
  try {
    await fetch("/api/save", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({key:st.key, cam_modified:[]})
    });
  } catch (e) { console.warn("could not persist MODIFIED dismissal", e); }
  renderTable();
  renderRoster();
  updateCamModNote();
}

/* ---------- Selection: highlight row + focus grade ---------- */
function selectStudent(key, focusGrade) {
  selectedKey = key;
  // Selecting a grouped card highlights the whole group (cards + matrix rows).
  const g = groupForKey(key);
  const keys = g ? g.members : [key];
  roster.querySelectorAll(".scard").forEach(c =>
    c.classList.toggle("selected", keys.includes(c.dataset.key)));
  let row = null;
  tableWrap.querySelectorAll("tr[data-key]").forEach(r => {
    const on = keys.includes(r.dataset.key); r.classList.toggle("selected", on);
    if (r.dataset.key===key) row=r;
  });
  if (row) {
    row.scrollIntoView({block:"center", behavior:"smooth"});
    if (focusGrade) { const gg = row.querySelector("select.grade"); if (gg) gg.focus(); }
  }
}

/* ---------- Keyword editor (editable rubric headers, auto-saved) ---------- */

/* Debounced + immediate persistence of the whole criteria array to the
   per-folder cache. The backend merges it under the open folder ID and never
   touches student marks. */
let _checklistTimer = null;
function checklistPayload() {
  return KEYWORDS
    .map(k => ({label:(k.label||"").trim(),
                type: k.type==="growth" ? "growth" : "positive"}))
    .filter(k => k.label);
}
async function pushChecklist() {
  // Exam mode stores the rubric with the exam's grades; assignment mode stores
  // it under the loaded folder. Either way the headers need an open target.
  const url = EXAM ? "/api/exam/checklist" : "/api/checklist";
  if (!EXAM && !STUDENTS.length) return;   // headers attach to a loaded folder
  try {
    await fetch(url, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({checklist: checklistPayload()})
    });
  } catch (e) { console.warn("checklist save failed", e); }
}
function scheduleChecklistSave() {     // live typing -> slight debounce
  clearTimeout(_checklistTimer);
  _checklistTimer = setTimeout(pushChecklist, 600);
}
function saveChecklistNow() {          // click-away / add / delete -> immediate
  clearTimeout(_checklistTimer);
  pushChecklist();
}

/* Re-render whichever grading matrix is active so the checkbox column adopts
   the latest rubric labels. */
function rerenderGradingTable() {
  if (EXAM) renderExamTable(); else renderTable();
}

/* When a criteria is renamed, carry every student's existing checkbox mark and
   any comment text over to the new label so nothing is silently dropped. Works
   for both the assignment roster and the exam roster. */
function remapKeywordLabel(oldLabel, newLabel) {
  if (!oldLabel || oldLabel === newLabel) return;
  const roster = EXAM ? EXAM.students : STUDENTS;
  const persist = EXAM ? saveExamStudent : save;
  roster.forEach(st => {
    let touched = false;
    if (Array.isArray(st.keywords) && st.keywords.includes(oldLabel)) {
      st.keywords = st.keywords.map(x => x === oldLabel ? newLabel : x);
      touched = true;
    }
    if (st.comment && st.comment.indexOf(oldLabel) !== -1) {
      st.comment = st.comment.split(oldLabel).join(newLabel);  // literal replace
      touched = true;
    }
    if (touched) persist(st);         // persist the migrated marks for this student
  });
}

function renderTags() {
  const list = $("#tagList"); list.innerHTML = "";
  KEYWORDS.forEach((k, i) => {
    const t = document.createElement("span");
    t.className = "tag " + (k.type === "growth" ? "tag-grow" : "tag-pos");

    // Editable criteria field — typing here IS editing the header.
    const inp = document.createElement("input");
    inp.type = "text";
    inp.className = "tagedit " + (k.type === "growth" ? "grow" : "pos");
    inp.value = k.label;
    inp.size = Math.max(6, k.label.length);
    inp.title = "Edit criteria name — saves automatically when you click away";
    let oldLabel = k.label;

    inp.addEventListener("focus", () => { oldLabel = KEYWORDS[i].label; });

    // Live typing: keep the model current and autosave on a slight debounce.
    inp.addEventListener("input", () => {
      KEYWORDS[i].label = inp.value;
      inp.size = Math.max(6, inp.value.length);
      scheduleChecklistSave();
    });

    // The moment you finish and click away (or press Enter): finalise, migrate
    // any existing marks to the new name, rebuild the matrix, and save now.
    const commit = () => {
      const newLabel = inp.value.trim();
      if (!newLabel) {                       // blank -> revert to the old name
        KEYWORDS[i].label = oldLabel; inp.value = oldLabel;
      } else {
        KEYWORDS[i].label = newLabel; inp.value = newLabel;
        if (newLabel !== oldLabel) remapKeywordLabel(oldLabel, newLabel);
      }
      oldLabel = KEYWORDS[i].label;
      inp.size = Math.max(6, inp.value.length);
      rerenderGradingTable();                // checkbox column adopts final labels
      saveChecklistNow();
    };
    inp.addEventListener("change", commit);
    inp.addEventListener("blur", commit);
    inp.addEventListener("keydown", e => {
      if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    });

    const del = document.createElement("b");
    del.textContent = "×"; del.title = "Remove this criteria";
    del.addEventListener("click", () => {
      KEYWORDS.splice(i, 1);
      renderTags(); rerenderGradingTable(); saveChecklistNow();
    });

    t.appendChild(inp); t.appendChild(del);
    list.appendChild(t);
  });
}

function addKeyword() {
  const v = $("#newKw").value.trim(); if (!v) return;
  KEYWORDS.push({label:v, type: $("#newKwType").value === "growth" ? "growth" : "positive"});
  $("#newKw").value = "";
  renderTags(); rerenderGradingTable(); saveChecklistNow();
}

/* ---------- Exam mode (grading a sliced scanned exam) ----------
   Programmed in /exam_setup, an exam is graded one question at a time: the
   question dropdown picks which sliced answer image every student card shows,
   and the right matrix carries one score column per question, each with its
   own mark range (0..max), so different questions can be worth different
   amounts. Everything autosaves to the per-exam grades file. */
let EXAM = null;            // {exam_name, questions:[{label,range,max}], students:[...]}
let EXAM_BY_KEY = {};
let CURRENT_Q = null;       // label of the question currently on the left screen
let examSelectedKey = null;
let EXAM_ANON = false;      // anonymous grading on for this exam (server pref, D6)

/* Anonymous exam order (decision D6, YouMark-style). The server blanks the
   display names and the client re-orders + numbers per question so the same
   student never carries a stable alias across questions. A deterministic
   mulberry32 PRNG seeded on a string hash of class|exam|question gives an order
   that is stable across reloads but different for every question. */
function examStrHash(s) {
  let h = 1779033703 ^ s.length;
  for (let i = 0; i < s.length; i++) {
    h = Math.imul(h ^ s.charCodeAt(i), 3432918353);
    h = (h << 13) | (h >>> 19);
  }
  return h >>> 0;
}
function examMulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function examSeededShuffle(arr, seedStr) {
  const rng = examMulberry32(examStrHash(seedStr));
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/* The ordered (student, display-label) pairs the roster + sheet both iterate,
   so the two screens always share one order. Anonymous on: shuffle per question
   (seed = class|exam|CURRENT_Q) and label by POSITION — "01", "02", … — which
   is a progress counter, not an identity (the same student gets a different
   number on the next question). Anonymous off: today's order (as the server
   sends it, alphabetical) with real names. */
function examView() {
  if (!EXAM) return [];
  if (!EXAM_ANON) return EXAM.students.map(st => ({st, label: st.name}));
  const seed = (ACTIVE_CLASS_NAME || "") + "|" + (EXAM.exam_name || "")
             + "|" + (CURRENT_Q || "");
  return examSeededShuffle(EXAM.students, seed)
    .map((st, i) => ({st, label: String(i + 1).padStart(2, "0")}));
}

/* Cache-buster bumped when a question is re-sliced in the Exam Setup tab
   (Phase 6). Appended to crop URLs so the browser refetches the new framing
   instead of the cached image; empty until the first re-slice arrives. */
let EXAM_CROP_BUST = "";
function cropUrl(q, student) {
  return "/api/exam/crop?class=" + encodeURIComponent(ACTIVE_CLASS_NAME)
       + "&exam=" + encodeURIComponent(EXAM.exam_name)
       + "&q=" + encodeURIComponent(q)
       + "&student=" + encodeURIComponent(student)
       + (EXAM_CROP_BUST ? "&t=" + encodeURIComponent(EXAM_CROP_BUST) : "");
}

/* Open Exam Setup focused on one question, to adjust its region mid-grading. */
function openExamAdjust(label) {
  if (!EXAM || !ACTIVE_CLASS_NAME) return;
  window.open("/exam_setup?class=" + encodeURIComponent(ACTIVE_CLASS_NAME)
    + "&exam=" + encodeURIComponent(EXAM.exam_name)
    + "&focus=" + encodeURIComponent(label), "_blank");
}

/* The Exam Setup tab writes this localStorage key when a re-slice finishes;
   the write fires a 'storage' event in THIS tab (same origin). Refresh the
   affected exam's crops in place — marks are untouched, only pixels changed. */
window.addEventListener("storage", (e) => {
  if (e.key !== "cam_exam_resliced" || !e.newValue || !EXAM) return;
  let sig;
  try { sig = JSON.parse(e.newValue); } catch (_) { return; }
  if (sig.class === ACTIVE_CLASS_NAME && sig.exam === EXAM.exam_name) {
    EXAM_CROP_BUST = String(sig.ts || Date.now());
    renderExamRoster();
    setStatus("Re-sliced " + (sig.label || "a question") + " — crops refreshed.");
  }
});
// No examTotal/examMaxTotal helpers: decision D3 keeps every running total out
// of the grading UI (they belong only to the CSV export + CAM). Completion is
// tracked per-question instead — see examFullyGraded and the roster progress.
function examFullyGraded(st) {
  return EXAM.questions.every(q => st.scores[q.label] !== undefined);
}

async function loadExam(examName) {
  if (!ACTIVE_CLASS_NAME) {
    alert("Pick a saved class first — exams are stored per class."); return;
  }
  setStatus("Loading exam…");
  try {
    const res = await fetch("/api/exam/load", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({class_name: ACTIVE_CLASS_NAME, exam_name: examName})
    });
    const data = await res.json();
    if (!res.ok) { setStatus(""); alert(data.error || "Failed to load exam."); return; }
    EXAM = data;
    EXAM_ANON = !!data.anonymous;   // server blanked names; client numbers by position
    EXAM_BY_KEY = {};
    EXAM.students.forEach(st => {
      st.scores = st.scores || {};
      st.keywords = st.keywords || [];
      EXAM_BY_KEY[st.key] = st;
    });
    CURRENT_Q = EXAM.questions.length ? EXAM.questions[0].label : null;
    examSelectedKey = null;

    // The exam's own keyword rubric (D4 default when the exam has none saved),
    // editable per exam exactly like the assignment checklist.
    KEYWORDS = (Array.isArray(data.checklist) && data.checklist.length)
      ? data.checklist.map(k => ({
          label: String(k.label || "").trim(),
          type:  k.type === "growth" ? "growth" : "positive",
        })).filter(k => k.label)
      : [];

    // Question selector drives which answer slice the left screen shows.
    const qs = $("#questionSelect");
    qs.innerHTML = "";
    EXAM.questions.forEach(q => {
      const o = document.createElement("option");
      o.value = q.label; o.textContent = q.label;   // D1: bare label — the sheet header's qcol already shows (0–max)
      qs.appendChild(o);
    });
    qs.classList.remove("hidden");
    $("#examAdjustBtn").classList.remove("hidden");
    $("#examCsvBtn").classList.remove("hidden");
    $("#setupbar").classList.add("hidden");     // MYP criteria don't apply here
    $("#kwEditor").classList.remove("hidden");  // keyword checklist works for exams too
    $("#folderName").textContent = "📝 " + EXAM.exam_name;
    // No running total here (decision D3): a visible total while later
    // questions are still ungraded reinforces bias. Totals live only in the CSV.
    setStatus(EXAM.students.length + " student(s) · " + EXAM.questions.length
              + " question(s)");
    renderTags();
    renderExamTable();
    renderExamRoster();
    updateCamModNote();   // exam mode — folder MODIFIED note doesn't apply
  } catch (e) { setStatus(""); alert("Error: " + e); }
}

function exitExamMode() {
  if (!EXAM) return;
  EXAM = null; EXAM_BY_KEY = {}; CURRENT_Q = null; examSelectedKey = null;
  $("#questionSelect").classList.add("hidden");
  $("#examAdjustBtn").classList.add("hidden");
  $("#examCsvBtn").classList.add("hidden");
  $("#kwEditor").classList.remove("hidden");
}

/* Left screen: one card per student showing their sliced answer to CURRENT_Q. */
function renderExamRoster() {
  roster.innerHTML = "";
  if (!EXAM) return;
  examView().forEach(({st, label}) => {
    const card = document.createElement("div");
    card.className = "scard" + (examFullyGraded(st) ? " graded" : "")
                   + (st.key === examSelectedKey ? " selected" : "");
    card.dataset.key = st.key;

    const img = document.createElement("img");
    img.className = "exam-img"; img.loading = "lazy";
    img.src = cropUrl(CURRENT_Q, st.key); img.alt = label;
    img.onerror = () => img.replaceWith(Object.assign(document.createElement("div"),
      {className: "ph", textContent: "No slice for " + CURRENT_Q}));
    attachExamZoom(img, cropUrl(CURRENT_Q, st.key));
    card.appendChild(img);

    const chk = document.createElement("div");
    chk.className = "checkbadge"; chk.textContent = "✓"; card.appendChild(chk);
    const sc = st.scores[CURRENT_Q];
    if (sc !== undefined) {
      const chip = document.createElement("div"); chip.className = "qchip";
      chip.textContent = CURRENT_Q + ": " + sc; card.appendChild(chip);
    }

    const meta = document.createElement("div"); meta.className = "meta";
    // Progress, not a total (decision D3): how many questions are graded, never
    // a running score sum while grading is still in flight.
    const done = EXAM.questions.filter(q => st.scores[q.label] !== undefined).length;
    const nq = EXAM.questions.length;
    meta.innerHTML = `<div class="nm">${escapeHtml(label)}</div>`
      + `<div class="sub">${done ? done + "/" + nq + " questions" : "ungraded"}</div>`;
    card.appendChild(meta);

    card.addEventListener("click", () => selectExamStudent(st.key, true));
    roster.appendChild(card);
  });
}

/* Hover zoom for exam slices — same overlay as artwork thumbnails. */
function attachExamZoom(img, url) {
  img.addEventListener("mouseenter", () => {
    if (videoZoomActive) return;
    hoverEl = img; hoverScale = 2; hoverFid = null;
    overlay.classList.remove("video-mode");
    overlayImg.src = url;
    overlayImg.style.transform = "";
    overlay.style.display = "block";
    positionOverlay(img);
  });
  img.addEventListener("mousemove", () => { if (hoverEl === img) positionOverlay(img); });
  img.addEventListener("mouseleave", () => {
    if (hoverEl === img) { hoverEl = null; overlay.style.display = "none"; }
  });
  img.addEventListener("wheel", (ev) => {
    if (hoverEl !== img) return;
    ev.preventDefault();
    hoverScale += (ev.deltaY < 0 ? 0.35 : -0.35);
    if (hoverScale < 1.2) hoverScale = 1.2;
    positionOverlay(img);
  }, {passive:false});
}

/* Right screen: one column for the CURRENT question only (decision D3) — no
   other questions, and no running Total, so a visible sum can't bias grading
   while later questions are unmarked. Keywords + Comment mirror the assignment
   sheet. Switching #questionSelect re-renders to the next question's column. */
function renderExamTable() {
  if (!EXAM || !EXAM.students.length) {
    tableWrap.innerHTML = '<div class="empty">No sliced students found.</div>';
    return;
  }
  const q = EXAM.questions.find(x => x.label === CURRENT_Q) || EXAM.questions[0];
  const t = document.createElement("table");
  const qcol = q
    ? `<th class="qcur" title="Range ${escapeHtml(q.range)}">`
      + `${escapeHtml(q.label)}<br>(0–${q.max}) `
      + `<button class="qadjust" type="button" data-q="${escapeHtml(q.label)}"`
      + ` title="Adjust this question's region during grading">✎</button></th>`
    : "";
  t.innerHTML = `<thead><tr><th class="idcol">Student</th>${qcol}`
              + `<th>Keywords</th><th>Comment</th></tr></thead>`;
  const tb = document.createElement("tbody");
  examView().forEach(({st, label}) => tb.appendChild(makeExamRow(st, label)));
  t.appendChild(tb);
  // The ✎ opens Exam Setup focused on this question (Phase 6).
  t.querySelectorAll("button.qadjust").forEach(b =>
    b.addEventListener("click", (e) => { e.stopPropagation(); openExamAdjust(b.dataset.q); }));
  tableWrap.innerHTML = "";
  tableWrap.appendChild(t);
}

function makeExamRow(st, label) {
  const tr = document.createElement("tr");
  tr.dataset.key = st.key;
  if (st.key === examSelectedKey) tr.classList.add("selected");

  const tdN = document.createElement("td"); tdN.className = "name idcol";
  tdN.innerHTML = `<span class="sid">${escapeHtml(label != null ? label : st.name)}</span>`;
  tr.appendChild(tdN);

  // Only the current question's score column (D3): no running total anywhere.
  const q = EXAM.questions.find(x => x.label === CURRENT_Q) || EXAM.questions[0];
  if (q) {
    const td = document.createElement("td"); td.classList.add("qcur");
    const sel = document.createElement("select");
    sel.className = "qscore"; sel.dataset.q = q.label;
    const blank = document.createElement("option");
    blank.value = ""; blank.textContent = "–"; sel.appendChild(blank);
    for (let v = 0; v <= q.max; v++) {
      const o = document.createElement("option");
      o.value = String(v); o.textContent = String(v);
      if (st.scores[q.label] !== undefined && String(st.scores[q.label]) === String(v))
        o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener("change", () => {
      if (sel.value === "") delete st.scores[q.label];
      else st.scores[q.label] = Number(sel.value);
      saveExamStudent(st);
    });
    td.appendChild(sel); tr.appendChild(td);
  }

  // Keyword checklist — same checkbox pills as assignment mode; ticking
  // rebuilds the auto part of the comment while keeping any free text.
  st.keywords = st.keywords || [];
  const tdK = document.createElement("td");
  const box = document.createElement("div"); box.className = "kw";
  KEYWORDS.forEach(k => {
    const lab = document.createElement("label");
    const cb = document.createElement("input"); cb.type = "checkbox"; cb.value = k.label;
    cb.checked = st.keywords.includes(k.label);
    cb.addEventListener("change", () => {
      if (cb.checked) { if (!st.keywords.includes(k.label)) st.keywords.push(k.label); }
      else st.keywords = st.keywords.filter(x => x !== k.label);
      st.comment = autoComment(st);
      const ta = tr.querySelector("textarea.comment"); if (ta) ta.value = st.comment;
      saveExamStudent(st);
    });
    const span = document.createElement("span");
    span.className = k.type === "growth" ? "grow" : "pos";
    span.textContent = k.label;
    lab.appendChild(cb); lab.appendChild(span);
    box.appendChild(lab);
  });
  tdK.appendChild(box); tr.appendChild(tdK);

  const tdC = document.createElement("td");
  const ta = document.createElement("textarea"); ta.className = "comment";
  ta.value = st.comment || "";
  ta.addEventListener("input", () => { st.comment = ta.value; });
  ta.addEventListener("blur", () => saveExamStudent(st));
  tdC.appendChild(ta); tr.appendChild(tdC);

  tr.addEventListener("click", () => selectExamStudent(st.key, false));
  return tr;
}

async function saveExamStudent(st) {
  try {
    await fetch("/api/exam/grade", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({key: st.key, scores: st.scores,
                            comment: st.comment || "", keywords: st.keywords || []})
    });
  } catch (e) { console.warn("exam save failed", e); }
  const tr = tableWrap.querySelector(`tr[data-key="${cssEsc(st.key)}"]`);
  if (tr) { tr.classList.remove("row-saved"); void tr.offsetWidth; tr.classList.add("row-saved"); }
  renderExamRoster();       // score chip + graded tick follow the matrix
}

function selectExamStudent(key, focusScore) {
  examSelectedKey = key;
  roster.querySelectorAll(".scard").forEach(c =>
    c.classList.toggle("selected", c.dataset.key === key));
  let row = null;
  tableWrap.querySelectorAll("tr[data-key]").forEach(r => {
    const on = r.dataset.key === key; r.classList.toggle("selected", on);
    if (on) row = r;
  });
  if (row) {
    row.scrollIntoView({block:"center", behavior:"smooth"});
    if (focusScore) {
      const sel = row.querySelector(`select.qscore[data-q="${cssEsc(CURRENT_Q)}"]`)
               || row.querySelector("select.qscore");
      if (sel) sel.focus();
    }
  }
}

/* Exam CSV: routed export (cloud folder -> ACM auto-ingest) + direct download. */
async function exportExamCsv(force = false) {
  setStatus("Exporting exam CSV…");
  try {
    const res = await fetch("/api/exam/export" + (force ? "?force=1" : ""));
    const ct = res.headers.get("Content-Type") || "";
    if (ct.includes("application/json")) {
      const d = await res.json();
      if (!res.ok || d.error) { setStatus(""); alert(d.error || "Export failed."); return; }
      if (d.needs_confirm) {
        setStatus("");
        if (confirm('"' + d.filename + '" already exists in the cloud folder.\n\nOverwrite it?'))
          return exportExamCsv(true);
        setStatus("Export cancelled.");
        return;
      }
      setStatus("Saved exam CSV → " + d.path + "  (ACM will auto-ingest it)");
    } else {
      await streamCsvDownload(res);
    }
  } catch (e) { setStatus(""); alert("Export error: " + e); }
}

async function downloadExamCsv() {
  if (!EXAM) return;
  setStatus("Preparing download…");
  try {
    const res = await fetch("/api/exam/export?download=1");
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      setStatus(""); alert(d.error || "Download failed."); return;
    }
    await streamCsvDownload(res);
  } catch (e) { setStatus(""); alert("Download error: " + e); }
}

async function streamCsvDownload(res) {
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = (m && m[1]) || "Grades.csv";
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(a.href);
  setStatus("CSV downloaded.");
}

/* ---------- Resizable divider ---------- */
(function(){
  const divider = $("#divider"), left = $("#left"), split=$("#split");
  let dragging=false;
  left.style.width = "55%"; left.style.flex = "none";
  divider.addEventListener("mousedown", () => { dragging=true; document.body.style.userSelect="none"; });
  window.addEventListener("mousemove", e => {
    if (!dragging) return;
    const r = split.getBoundingClientRect();
    let w = e.clientX - r.left;
    // Narrow ID matrix needs far less room, so allow the divider much further right.
    w = Math.max(260, Math.min(w, r.width-200));
    left.style.width = w + "px";
  });
  window.addEventListener("mouseup", () => { dragging=false; document.body.style.userSelect=""; });
})();

/* ---------- Column slider ---------- */
function setCols(n){
  roster.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
  $("#colVal").textContent = n;
  if (EXAM) { renderExamRoster(); return; }   // exam cards share the same grid
  // Re-render so any Group Work boxes adopt the same column count internally.
  if (STUDENTS.length) renderRoster();
}

/* ---------- utils ---------- */
function escapeHtml(s){ return (s||"").replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function cssEsc(s){ return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/["\\]/g,"\\$&"); }

/* ---------- wire up ---------- */
$("#gradeBtn").addEventListener("click", openSelectedAssignment);
$("#assignmentSelect").addEventListener("change", () => {
  if ($("#assignmentSelect").value) openSelectedAssignment();
});
/* Exam wiring: setup opens per-class; the question dropdown swaps every
   student card to that question's answer slice and re-highlights the matrix. */
$("#examSetupBtn").addEventListener("click", () => {
  if (!ACTIVE_CLASS_NAME) {
    alert("Select a saved class first — the exam will be added to that class.");
    return;
  }
  window.open("/exam_setup?class=" + encodeURIComponent(ACTIVE_CLASS_NAME), "_blank");
});
$("#questionSelect").addEventListener("change", () => {
  CURRENT_Q = $("#questionSelect").value;
  renderExamRoster();
  renderExamTable();
});
$("#examAdjustBtn").addEventListener("click", () => { if (CURRENT_Q) openExamAdjust(CURRENT_Q); });
$("#examCsvBtn").addEventListener("click", downloadExamCsv);
$("#deadlineInput").addEventListener("change", () => {
  DEADLINE = $("#deadlineInput").value || "";
  pushSettings();
  // The deadline is the ground truth, so re-derive every student's Late flag
  // from it (this resets prior auto-derived flags; manual ticks/waivers
  // (late_manual) are sticky and left untouched) and refresh the auto-comments.
  STUDENTS.forEach(st => {
    if (!st.late_manual) st.late_marked = isLate(st);
    st.comment = autoComment(st);
  });
  renderTable();
  renderRoster();
  STUDENTS.forEach(st => save(st));   // persist the recomputed late flag + comment
});
$("#exportBtn").addEventListener("click", exportCsv);
$("#colSlider").addEventListener("input", e => setCols(e.target.value));
$("#addKwBtn").addEventListener("click", addKeyword);
$("#newKw").addEventListener("keydown", e => { if(e.key==="Enter") addKeyword(); });

/* Class dropdown + settings modal wiring */
$("#classSelect").addEventListener("change", onClassPicked);
$("#settingsBtn").addEventListener("click", openSettings);
$("#settingsClose").addEventListener("click", closeSettings);
$("#settingsDoneBtn").addEventListener("click", closeSettings);
$("#settingsOverlay").addEventListener("click", e => {
  if (e.target === $("#settingsOverlay")) closeSettings();   // click backdrop to dismiss
});

/* ---------- Export: save into the class cloud subfolder, or download ---------- */
async function exportCsv(force = false) {
  if (EXAM) return exportExamCsv(force);          // exam mode -> item-level CSV
  if (!STUDENTS.length) { alert("Load an assignment before exporting."); return; }
  setStatus("Exporting…");
  try {
    const res = await fetch("/api/export" + (force ? "?force=1" : ""));
    const ct = res.headers.get("Content-Type") || "";
    if (ct.includes("application/json")) {
      const d = await res.json();
      if (!res.ok || d.error) { setStatus(""); alert(d.error || "Export failed."); return; }
      // A file with this name already exists in the cloud folder — confirm.
      if (d.needs_confirm) {
        setStatus("");
        if (confirm('"' + d.filename + '" already exists in the cloud folder.\n\nOverwrite it?')) {
          return exportCsv(true);
        }
        setStatus("Export cancelled.");
        return;
      }
      // Saved server-side into the class subfolder. The export is the new
      // shared baseline, so every MODIFIED marker is now accounted for.
      STUDENTS.forEach(s => { s.cam_modified = []; });
      renderTable();
      renderRoster();
      updateCamModNote();
      setStatus("Saved CSV → " + d.path);
      // Older exports for this assignment under a different date block CAM's
      // Sync (it refuses contradictory sources). Alert, but never delete.
      if (d.stale_siblings && d.stale_siblings.length) {
        setStatus("Saved CSV → " + d.path + "  ⚠ stale sibling export(s) present");
        alert("Older export(s) for this assignment exist under a different "
            + "date:\n\n  " + d.stale_siblings.join("\n  ")
            + "\n\nCAM will refuse to sync this assignment until you verify "
            + "which file is correct and delete the stale one. Nothing was "
            + "deleted automatically.");
      }
    } else {
      // No cloud directory configured: stream a normal browser download.
      const blob = await res.blob();
      const cd = res.headers.get("Content-Disposition") || "";
      const m = cd.match(/filename="?([^"]+)"?/);
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = (m && m[1]) || "Grades.csv";
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(a.href);
      setStatus("CSV downloaded.");
    }
  } catch (e) { setStatus(""); alert("Export error: " + e); }
}

/* ---------- CAM bridge: auto-load from URL query parameters ----------
   The CAM dashboard's "Grade this Assignment/Exam" button opens this app at
   /?class=<name>&assignment=<Drive folder ID | exam::Name>&aname=<display name>.
   Once the settings are in, select the class, list its assignments, and open
   the matching one automatically. Matching order: exact option value (Drive
   folder ID / exam:: value), then exam::<target>, then option text against
   the target or display name (📝 prefix ignored).
   A class with no Drive mapping can still open its programmed EXAMS: exams
   are stored locally by class name (no Drive, no OAuth), so only folder
   grading needs the class saved in ⚙ Settings. */
async function autoloadFromParams() {
  const p = new URLSearchParams(location.search);
  const cls = p.get("class") || "";
  const target = (p.get("assignment") || "").trim();
  const aname = (p.get("aname") || "").trim();
  if (!cls) return;
  const norm = s => (s || "").replace(/^📝\s*/, "").trim().toLowerCase();
  const findHit = () => {
    const opts = [...$("#assignmentSelect").options].filter(o => o.value);
    return opts.find(o => o.value === target)
        || opts.find(o => o.value === "exam::" + target)
        || opts.find(o => norm(o.textContent) === norm(target))
        || (aname && opts.find(o => norm(o.textContent) === norm(aname)));
  };
  if (!(SETTINGS.classes || {})[cls]) {
    // Unmapped class: list its locally-stored exams and open the match.
    ACTIVE_CLASS_NAME = cls;
    const sel = $("#assignmentSelect");
    sel.innerHTML = '<option value="">Choose assignment…</option>';
    await loadExamOptions(sel);
    const hit = findHit();
    if (!hit) {
      setStatus('CAM bridge: class "' + cls + '" is not saved here — add it in ⚙ Settings.');
      return;
    }
    sel.classList.remove("hidden");
    $("#gradeBtn").classList.remove("hidden");
    sel.value = hit.value;
    openSelectedAssignment();
    return;
  }
  $("#classSelect").value = cls;
  ACTIVE_CLASS_NAME = cls;
  await loadClass(SETTINGS.classes[cls]);
  if (!target && !aname) return;
  const hit = findHit();
  if (!hit) {
    setStatus('CAM bridge: assignment "' + (aname || target) + '" not found in this class — pick it manually.');
    return;
  }
  $("#assignmentSelect").value = hit.value;
  openSelectedAssignment();
}

setCols(3);
renderTags();
// Populate the class dropdown + settings from gcg_settings.json, then honour
// any CAM-bridge query parameters.
loadConfig().then(autoloadFromParams);
</script>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# Exam Setup page (/exam_setup) — split-screen question programmer
# -----------------------------------------------------------------------------
EXAM_SETUP_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Exam Setup — Criterion Assessment Metrics</title>
<style>
  /* Same CAM palette as the main grading screen. */
  :root {
    color-scheme: light;
    --bg:#E9E7E2; --panel:#DDDAD3; --panel2:#DFDCD4; --line:#C6C2B9;
    --text:#38352F; --muted:#6E695F; --accent:#B3554D; --green:#37c97a;
    --surface:#F0EEE9; --btn-hover:#D5D1C7; --imgbg:#CBC7BE;
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --bg:#252423; --panel:#32312F; --panel2:#3A3835; --line:#4B4945;
    --text:#D8D5CF; --muted:#A19C93; --accent:#C4675F;
    --surface:#2E2D2B; --btn-hover:#454340; --imgbg:#1B1A19;
  }
  * { box-sizing:border-box; }
  html,body { margin:0; height:100%; font-family:-apple-system,Segoe UI,Roboto,"Hiragino Kaku Gothic ProN","Yu Gothic",Meiryo,sans-serif;
              background:var(--bg); color:var(--text); accent-color:var(--accent); }
  #app { display:flex; flex-direction:column; height:100vh; }
  #topbar { display:flex; gap:10px; align-items:center; padding:10px 14px;
            background:var(--panel); border-bottom:1px solid var(--line); flex:none; flex-wrap:wrap; }
  #topbar h1 { font-size:16px; margin:0; }
  #classTag { color:var(--muted); font-size:13px; }
  #status { color:var(--muted); font-size:13px; flex:1; }
  button { background:var(--accent); color:#fff; border:none; padding:8px 14px; border-radius:6px;
           font-size:14px; cursor:pointer; }
  button.secondary { background:var(--panel2); border:1px solid var(--line); color:var(--text); }
  button:hover { filter:brightness(1.08); }
  button.secondary:hover { background:var(--btn-hover); border-color:var(--accent); filter:none; }
  input[type=text], select { padding:7px 9px; border-radius:6px; border:1px solid var(--line);
            background:var(--panel2); color:var(--text); font-size:13px; }
  a.backlink { color:var(--accent); font-size:13px; text-decoration:none; }

  /* Split layout */
  #split { display:flex; flex:1; min-height:0; }
  #left { width:55%; flex:none; overflow:auto; background:var(--bg); padding:12px;
          border-right:1px solid var(--line); }
  #right { flex:1; overflow:auto; background:var(--panel); padding:14px; min-width:340px; }

  /* Left: loader bar + page preview with the paper-size + density coordinate
     grid overlay (legacy ~2cm, compact ~1.4cm, fine ~1cm — set inline by JS). */
  #loaderBar { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
  #folderInput { flex:1; min-width:220px; }
  #pageWrap { position:relative; background:var(--imgbg); border:1px solid var(--line);
              border-radius:8px; overflow:hidden; }
  /* Zoom-to-selection (Phase 6): the img + grid overlay live in this container
     so a single CSS transform frames one question's cells ±2 without touching
     layout (page height stays put, so #pageWrap keeps clipping to the page). */
  #pageZoom { position:relative; transform-origin:0 0; transition:transform .15s ease; }
  #pageImg { width:100%; display:block; }
  /* Fit-page mode (Phase 3): constrain the sheet by height so the whole page is
     visible at once, and centre it horizontally in the pane. #pageWrap goes flex
     so #pageZoom shrink-wraps the image — the inset:0 grid overlay keeps tracking
     the page box. The 150px offset budgets the topbar, loader row and the pane
     padding sitting above the preview. */
  #pageWrap.fitpage { display:flex; justify-content:center; }
  #pageWrap.fitpage #pageImg { width:auto; max-height:calc(100vh - 150px); }
  #gridOverlay { position:absolute; inset:0; display:grid;
                 grid-template-columns:repeat(15,1fr); grid-template-rows:repeat(21,1fr); }
  /* Grid lines take the teacher-chosen colour (--gridcol, set per device by JS)
     at partial alpha — density, not weight, was the legibility complaint. */
  .gcell { position:relative;
           border:1px dashed color-mix(in srgb, var(--gridcol, #39FF14) 65%, transparent);
           background:transparent; transition:background .1s; }
  /* Coordinate labels: bold, centred, filling the cell, in the chosen grid
     colour at ~40% opacity (no halo). Font size is computed from the live cell
     height (JS sets --glabsize) so labels recentre/rescale with density + fit
     mode instead of relying on per-density static rules. */
  .gcell .glab { position:absolute; inset:0; display:flex;
                 align-items:center; justify-content:center;
                 font-size:var(--glabsize, 13px); font-weight:800; line-height:1;
                 color:var(--gridcol, #39FF14); opacity:.4;
                 pointer-events:none; user-select:none; }
  .gcell.hl { outline:2px solid var(--hl, var(--accent)); outline-offset:-2px; }
  #noPage { padding:60px 20px; text-align:center; color:var(--muted); font-size:14px; }

  /* Right: setup form + question table */
  .field { display:flex; align-items:center; gap:8px; margin-bottom:10px; font-size:13px;
           color:var(--muted); flex-wrap:wrap; }
  .field input[type=text] { color:var(--text); }
  #examName { min-width:220px; font-weight:600; color:var(--text); }
  table { border-collapse:collapse; width:100%; font-size:13px; margin-top:6px; }
  th,td { border-bottom:1px solid var(--line); padding:6px 6px; text-align:left; vertical-align:middle; }
  th { font-size:12px; color:var(--muted); }
  td input.qlabel { width:74px; }
  td input.qrange { width:130px; font-family:ui-monospace,Consolas,monospace; }
  td input.qscore { width:64px; }
  td input.bad { border-color:#d0556a; box-shadow:0 0 0 1px #d0556a inset; }
  .swatch { display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:4px;
            vertical-align:-1px; }
  /* Question swatches are clickable to zoom the preview to that question. */
  tr[data-rowtype="question"] .swatch { cursor:zoom-in; }
  tr.focusrow td { background:var(--row-hl, rgba(179,85,77,.14)); }
  tr.focusrow td:first-child { box-shadow:inset 3px 0 0 var(--accent); }
  #focusBar { display:flex; align-items:center; gap:10px; margin-top:12px; padding:10px 12px;
              background:var(--surface); border:1px solid var(--accent); border-radius:8px;
              flex-wrap:wrap; }
  #focusNote { flex:1; font-size:13px; color:var(--text); min-width:180px; }
  .rowbtn { background:var(--panel2); color:var(--muted); border:1px solid var(--line);
            border-radius:5px; width:26px; height:26px; padding:0; font-size:13px; }
  .rowbtn:hover { background:var(--btn-hover); color:var(--text); filter:none; }
  .rowbtn.del:hover { background:#d0556a; color:#fff; border-color:#d0556a; }
  #actions { display:flex; gap:10px; margin-top:14px; flex-wrap:wrap; }
  #addRowBtns { display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
  #procNote { margin-top:10px; font-size:12px; color:var(--muted); white-space:pre-wrap; }
  .hint { font-size:12px; color:var(--muted); margin:4px 0 12px; line-height:1.5; }

  /* Section header rows: a tinted band spanning the label/range/score columns,
     with the section name + how-many-count control. Question rows below one
     belong to it. */
  tr.secrow td { background:var(--surface); border-top:1px solid var(--accent); }
  tr.secrow .seclabel { font-size:12px; font-weight:600; color:var(--muted); margin-right:6px; }
  tr.secrow .secname { width:150px; font-weight:600; color:var(--text); }
  .secreqwrap { font-size:12px; color:var(--muted); margin-left:8px; }
  .secreqwrap input[type=number] { width:52px; padding:5px 6px; border-radius:6px;
            border:1px solid var(--line); background:var(--panel2); color:var(--text); }
  .secreqwrap input:disabled { opacity:.4; }
  .secreqwrap label { cursor:pointer; }
  .swatch.secmark { background:var(--accent); color:#fff; width:14px; height:14px;
            font-size:10px; line-height:14px; text-align:center; border-radius:3px; }
  /* Name-box row: a fixed "Name" label, its own swatch colour, a range only. */
  tr.namerow td { background:var(--accent-tint, rgba(179,85,77,.06)); }
  tr.namerow .namelabel { font-weight:600; color:var(--text); }
  .swatch.namemark { background:#2bb8b0; }
</style>
<script>
(function(){
  var pref = localStorage.getItem("gcg_theme") || "auto";
  if (pref === "auto")
    pref = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  document.documentElement.dataset.theme = pref;
})();
</script>
</head>
<body>
<div id="app">
  <div id="topbar">
    <h1>📝 Exam Setup</h1>
    <span id="classTag"></span>
    <span id="status"></span>
    <a class="backlink" href="/">← back to grading</a>
  </div>

  <div id="split">
    <!-- LEFT: first student's exam page + paper/density coordinate grid -->
    <div id="left">
      <div id="loaderBar">
        <input id="folderInput" type="text" autocomplete="off"
               placeholder="Folder of student exam PDFs, e.g. C:\Scans\7A_Midterm">
        <button id="loadFolderBtn">📂 Load Student Folder</button>
        <select id="pageSelect" title="Page of the first student's PDF">
          <option value="1">Page 1</option>
        </select>
        <button id="fitToggleBtn" class="secondary hidden"
                title="Switch between fitting the page width and the whole page">↔ Fit width</button>
        <button id="zoomToggleBtn" class="secondary hidden"
                title="Clear the zoom-to-question view and return to the fit view">✕ Reset zoom</button>
      </div>
      <div id="pageWrap">
        <div id="noPage">Load a student folder to preview the first exam paper.<br>
          A coordinate grid sized for the selected paper and grid density
          (Compact ≈1.4cm or Fine ≈1cm) is laid over the page; type coordinate
          ranges on the right and the matching cells light up here.
          Click a question's colour swatch to zoom the preview to its cells.</div>
        <div id="pageZoom">
          <img id="pageImg" alt="" style="display:none">
          <div id="gridOverlay" style="display:none"></div>
        </div>
      </div>
    </div>

    <!-- RIGHT: paper size + question programming table -->
    <div id="right">
      <div class="field">
        <span>Exam name</span>
        <input id="examName" type="text" placeholder="e.g. Term 2 Midterm" autocomplete="off">
        <span>Load saved:</span>
        <select id="examLoadSelect"><option value="">— new exam —</option></select>
      </div>
      <div class="field">
        <span>Paper size</span>
        <select id="paperSelect">
          <option value="A4" selected>A4 (210 × 297 mm)</option>
          <option value="A3">A3 (297 × 420 mm)</option>
          <option value="B5">B5 (176 × 250 mm)</option>
        </select>
        <span>Grid</span>
        <select id="gridSelect" title="Cell size of the coordinate grid">
          <option value="compact" selected>Compact (≈1.4 cm)</option>
          <option value="fine">Fine (≈1 cm)</option>
        </select>
        <span>Grid colour</span>
        <select id="gridColorSelect" title="Colour of the coordinate grid and its labels (saved on this device)">
          <option value="#39FF14" selected>Neon green</option>
          <option value="#00BFFF">Bright blue</option>
          <option value="#FF00E5">Bright magenta</option>
        </select>
      </div>
      <div class="hint">
        One row per question, in the order they should be graded. Coordinate
        ranges use the grid on the left: <b>A2:C5</b> (page 1) or
        <b>page2!A2:C5</b>. Max mark is the highest score, e.g. <b>3</b>.
        Use ↑/↓ to reorder. Questions belong to the <b>section header</b> above
        them; an optional <b>name box</b> captures the handwritten name.
        <span id="gridHint"></span>
      </div>
      <table>
        <thead><tr>
          <th></th><th>Question Label</th><th>Coordinate Range</th>
          <th>Max mark</th><th colspan="3">Order</th>
        </tr></thead>
        <tbody id="qRows"></tbody>
      </table>
      <div id="addRowBtns">
        <button id="addQBtn" class="secondary">+ Add question</button>
        <button id="addSectionBtn" class="secondary">+ Add section</button>
        <button id="addNameBtn" class="secondary">+ Add name box</button>
      </div>
      <div id="focusBar" class="hidden">
        <span id="focusNote"></span>
        <button id="resliceBtn">⚙ Re-slice this question</button>
      </div>
      <div id="actions">
        <button id="saveBtn" class="secondary">💾 Save Setup</button>
        <button id="processBtn">⚙ Process All PDFs</button>
      </div>
      <div id="procNote"></div>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const CLASS_NAME = new URLSearchParams(location.search).get("class") || "";
$("#classTag").textContent = CLASS_NAME ? ("Class: " + CLASS_NAME)
                                        : "⚠ no class selected — open this from the main screen";

/* Paper-size + density grids. Mirrors PAPER_GRIDS in exam_engine.py — that
   Python table is the source of truth; keep this copy in sync. "legacy" (~2cm)
   is what every pre-density exam means and the load-only third option; new
   exams default to "compact" (~1.4cm); "fine" is ~1cm. */
const PAPER_GRIDS = {
  A4:{legacy:{cols:10,rows:15}, compact:{cols:15,rows:21}, fine:{cols:21,rows:30}},
  B5:{legacy:{cols:9,rows:12},  compact:{cols:13,rows:18}, fine:{cols:18,rows:25}},
  A3:{legacy:{cols:15,rows:21}, compact:{cols:21,rows:30}, fine:{cols:30,rows:42}},
};
const GRID_CM = { legacy:"≈2cm", compact:"≈1.4cm", fine:"≈1cm" };
let NCOLS = 15, NROWS = 21;   // set from the paper + grid dropdowns below

/* Excel-style column names — fine A3 reaches column AD (30 columns), so single
   letters no longer suffice. Mirrors col_name/col_index in exam_engine.py. */
function colName(i){
  i = i | 0; let s = "";
  while (true) { s = String.fromCharCode(65 + i % 26) + s; i = Math.floor(i / 26) - 1; if (i < 0) return s; }
}
function colIndex(letters){
  const s = String(letters || "").toUpperCase();
  if (!s || !/^[A-Z]+$/.test(s)) return -1;
  let idx = 0;
  for (const ch of s) idx = idx * 26 + (ch.charCodeAt(0) - 64);
  return idx - 1;
}
const Q_COLORS = ["#e0843a","#3aa0e0","#37c97a","#b56ad0","#d0556a","#caa23a",
                  "#2bb8b0","#7d8cf0","#c46fa0","#7fae3d"];
const NAME_COLOR = "#2bb8b0";              // name-box highlight (matches its swatch)
const DEFAULT_SECTION_NAME = "All Questions";  // mirrors exam_engine.DEFAULT_SECTION_NAME
let FOLDER = "", PAGE_COUNT = 1;

function setStatus(t){ $("#status").textContent = t; }

/* The #qRows tbody holds a mix of rows, distinguished by data-rowtype:
   "name" (optional, pinned first), "section" (a header) and "question". */
function allRows(){ return [...$("#qRows").children]; }
function rowType(tr){ return tr.dataset.rowtype; }
function nameRow(){ return $("#qRows tr.namerow"); }

/* The live grid density — mirrors the #gridSelect value, which may be a
   load-only "legacy" state when an old exam is open. */
function currentDensity() { return $("#gridSelect").value || "compact"; }

/* ---------- Grid colour + label sizing (Phase 1) ---------- */
/* The grid colour is a per-device preference (localStorage), not part of the
   exam definition — it only tints the overlay + labels while programming. All
   grid colouring reads the --gridcol CSS variable set here. */
const GRID_COLOR_KEY = "gcg_grid_color";
const GRID_COLOR_DEFAULT = "#39FF14";

function applyGridColor(col) {
  $("#gridOverlay").style.setProperty("--gridcol", col || GRID_COLOR_DEFAULT);
}

/* Size the cell labels from the live cell height so they stay ~55% of a cell in
   any density / window size / fit mode. Clamped to 9px so fine grids on a small
   window stay renderable. Called after the page image lays out, on resize, and
   whenever the grid matrix changes. */
function sizeCellLabels() {
  const ov = $("#gridOverlay");
  const h = ov.clientHeight;
  if (!h || !NROWS || !NCOLS) return;
  // D2: size by BOTH axes so wide labels (D10, fine-A3's AD42) never bleed
  // horizontally into a neighbouring cell.
  const heightPx = (h / NROWS) * 0.55;
  const cellW = ov.clientWidth / NCOLS;
  const maxChars = (colName(NCOLS - 1) + NROWS).length;   // widest label on this grid
  // 0.62 ≈ average glyph width in ems for the 800-weight UI font; 0.85 keeps a margin.
  const widthCap = maxChars ? (cellW * 0.85) / (maxChars * 0.62) : heightPx;
  const px = Math.max(9, Math.round(Math.min(heightPx, widthCap)));
  ov.style.setProperty("--glabsize", px + "px");
}

/* Restore the saved grid colour (or the neon-green default) on load. A stored
   value that isn't one of the three options leaves the select empty — fall back
   so the overlay still colours consistently. */
function initGridColor() {
  let col = GRID_COLOR_DEFAULT;
  try { col = localStorage.getItem(GRID_COLOR_KEY) || GRID_COLOR_DEFAULT; } catch (e) {}
  $("#gridColorSelect").value = col;
  if (!$("#gridColorSelect").value) { col = GRID_COLOR_DEFAULT; $("#gridColorSelect").value = col; }
  applyGridColor(col);
}

/* ---------- Dynamic grid overlay (A1 top-left .. bottom-right) ---------- */
function buildGrid() {
  const ov = $("#gridOverlay"); ov.innerHTML = "";
  for (let r = 1; r <= NROWS; r++) {
    for (let c = 0; c < NCOLS; c++) {
      const cell = document.createElement("div");
      cell.className = "gcell";
      cell.dataset.cell = colName(c) + r;
      const lab = document.createElement("span");
      lab.className = "glab"; lab.textContent = colName(c) + r;
      cell.appendChild(lab);
      ov.appendChild(cell);
    }
  }
}

/* Recompute the grid matrix from the Paper Size + Grid dropdowns, rebuild the
   overlay cells + A1/B2/... labels, and re-validate every typed range. */
function applyPaperGrid() {
  const paper = $("#paperSelect").value;
  const density = currentDensity();
  const g = (PAPER_GRIDS[paper] || PAPER_GRIDS.A4)[density]
         || (PAPER_GRIDS[paper] || PAPER_GRIDS.A4).legacy;
  NCOLS = g.cols;
  NROWS = g.rows;
  const ov = $("#gridOverlay");
  ov.dataset.density = density;
  ov.style.gridTemplateColumns = "repeat(" + g.cols + ",1fr)";
  ov.style.gridTemplateRows = "repeat(" + g.rows + ",1fr)";
  buildGrid();
  $("#gridHint").textContent = "Grid for " + paper + ": "
    + g.cols + "×" + g.rows + " (A1–" + colName(g.cols - 1) + g.rows
    + "), " + (GRID_CM[density] || "") + " cells.";
  refreshHighlights();
  sizeCellLabels();        // NROWS changed — recompute the translucent label size
  applyZoom();             // grid dims changed — re-frame any active zoom
}

/* The load-only "Standard (legacy 2 cm)" density is offered only when an exam
   saved on the old grid is loaded — new exams choose Compact or Fine. */
function ensureLegacyOption() {
  const sel = $("#gridSelect");
  if (![...sel.options].some(o => o.value === "legacy")) {
    const o = document.createElement("option");
    o.value = "legacy"; o.textContent = "Standard (legacy 2 cm)";
    sel.appendChild(o);
  }
}
function dropLegacyOption() {
  [...$("#gridSelect").options].forEach(o => { if (o.value === "legacy") o.remove(); });
}

/* Parse "page2!A2:C5" / "A2:C5" / "B7" / "AA5:AD9" -> {page,c1,r1,c2,r2} or
   null. One or two letters are accepted syntactically; anything outside the
   CURRENT paper + density grid is rejected so a stale range flags red after
   switching paper size or density. */
function parseRange(raw) {
  const m = /^\s*(?:page\s*(\d+)\s*!\s*)?([A-Za-z]{1,2})\s*(\d{1,2})(?:\s*:\s*([A-Za-z]{1,2})\s*(\d{1,2}))?\s*$/.exec(raw || "");
  if (!m) return null;
  const page = m[1] ? parseInt(m[1], 10) : 1;
  let c1 = colIndex(m[2]), r1 = parseInt(m[3], 10);
  let c2 = m[4] ? colIndex(m[4]) : c1;
  let r2 = m[5] ? parseInt(m[5], 10) : r1;
  if (c1 < 0 || c2 < 0 || c1 >= NCOLS || c2 >= NCOLS) return null;
  if (r1 < 1 || r1 > NROWS || r2 < 1 || r2 > NROWS) return null;
  if (c1 > c2) [c1, c2] = [c2, c1];
  if (r1 > r2) [r1, r2] = [r2, r1];
  return {page, c1, r1, c2, r2};
}

/* Every coordinate-bearing row (the name box + each question), with the colour
   it highlights in. Question colours track question index (stable by position);
   the name box uses its own colour. */
function highlightRegions() {
  const out = [];
  let qi = 0;
  allRows().forEach(tr => {
    const t = rowType(tr);
    if (t === "name") {
      out.push({inp: tr.querySelector(".qrange"), color: NAME_COLOR});
    } else if (t === "question") {
      out.push({inp: tr.querySelector(".qrange"), color: Q_COLORS[qi % Q_COLORS.length]});
      qi++;
    }
  });
  return out;
}

/* Re-paint the overlay from every region row's range (instant on typing).
   Only ranges targeting the page currently shown are highlighted. */
function refreshHighlights() {
  const page = parseInt($("#pageSelect").value, 10) || 1;
  const hl = {};                       // "A2" -> color
  highlightRegions().forEach(({inp, color}) => {
    const raw = inp.value.trim();
    const rng = parseRange(raw);
    inp.classList.toggle("bad", !!raw && !rng);
    if (!rng || rng.page !== page) return;
    for (let c = rng.c1; c <= rng.c2; c++)
      for (let r = rng.r1; r <= rng.r2; r++)
        hl[colName(c) + r] = color;
  });
  document.querySelectorAll(".gcell").forEach(cell => {
    const color = hl[cell.dataset.cell];
    cell.classList.toggle("hl", !!color);
    cell.style.setProperty("--hl", color || "");
    cell.style.background = color ? (color + "33") : "";
  });
}

/* ---------- Zoom-to-selection (Phase 6) ---------- */
/* Frame the preview on one range's cells ±2, so the teacher tweaks a single
   question's coordinates up close. Pure CSS transform on #pageZoom; the page's
   laid-out height is unchanged, so #pageWrap keeps clipping to the page box. */
const ZOOM_PAD = 2;          // cells of margin kept around the framed range
let ZOOM_RANGE = null;       // the range currently framed, or null (full page)
// Focus-adjust state (Phase 6): the question opened from grading's ✎, its row,
// and the preview page to land on once the folder loads.
let FOCUS_LABEL = "", FOCUS_ROW = null, FOCUS_PAGE = 1;

function clamp01(v){ return Math.max(0, Math.min(1, v)); }

function applyZoom() {
  const zoom = $("#pageZoom");
  if (!ZOOM_RANGE) { zoom.style.transform = ""; $("#zoomToggleBtn").classList.add("hidden"); return; }
  const img = $("#pageImg");
  const W = img.clientWidth, H = img.clientHeight;   // laid-out (unscaled) page box
  if (!W || !H) return;                              // image not ready yet
  const rng = ZOOM_RANGE;
  // parseRange carries 0-based columns but 1-based rows (the highlight
  // convention: cell labels run 1..NROWS), so shift rows to 0-based here.
  const r1 = rng.r1 - 1, r2 = rng.r2 - 1;
  const fx0 = clamp01((rng.c1 - ZOOM_PAD) / NCOLS);
  const fx1 = clamp01((rng.c2 + 1 + ZOOM_PAD) / NCOLS);
  const fy0 = clamp01((r1 - ZOOM_PAD) / NROWS);
  const fy1 = clamp01((r2 + 1 + ZOOM_PAD) / NROWS);
  const regW = Math.max(1, (fx1 - fx0) * W), regH = Math.max(1, (fy1 - fy0) * H);
  let s = Math.min(W / regW, H / regH);
  s = Math.max(1, Math.min(s, 8));                   // never zoom out, cap zoom-in
  const offX = (W - s * regW) / 2, offY = (H - s * regH) / 2;
  const tx = -s * fx0 * W + offX, ty = -s * fy0 * H + offY;
  zoom.style.transform = `translate(${tx}px, ${ty}px) scale(${s})`;
  $("#zoomToggleBtn").classList.remove("hidden");
}

/* Zoom the preview to a typed range string; switches to its page first. */
function zoomToRangeStr(raw) {
  const rng = parseRange(raw);
  if (!rng) return;
  ZOOM_RANGE = rng;
  if ((parseInt($("#pageSelect").value, 10) || 1) !== rng.page && rng.page <= PAGE_COUNT)
    showPage(rng.page);       // showPage's onload re-runs applyZoom via refreshHighlights
  applyZoom();
}

function clearZoom() { ZOOM_RANGE = null; applyZoom(); }

/* ---------- Fit width / fit page (Phase 3) ---------- */
/* The left pane defaults to fitting the page WIDTH (the img is 100% wide, i.e.
   today's behaviour). "Fit page" instead constrains the height so the whole
   sheet is visible at once. A per-device preference; toggling it also clears any
   active zoom-to-question, which lives independently on #pageZoom's transform. */
const FIT_MODE_KEY = "gcg_fit_mode";
let FIT_MODE = "width";     // "width" | "page"

function applyFitMode() {
  $("#pageWrap").classList.toggle("fitpage", FIT_MODE === "page");
  $("#fitToggleBtn").textContent = FIT_MODE === "page" ? "⤢ Fit page" : "↔ Fit width";
  sizeCellLabels();   // the cell pixel height changes with the fit mode
  applyZoom();        // re-frame any active zoom to the new page box
}

function initFitMode() {
  try { FIT_MODE = localStorage.getItem(FIT_MODE_KEY) === "page" ? "page" : "width"; } catch (e) {}
  applyFitMode();
}

function toggleFitMode() {
  FIT_MODE = (FIT_MODE === "page") ? "width" : "page";
  try { localStorage.setItem(FIT_MODE_KEY, FIT_MODE); } catch (e) {}
  clearZoom();        // the fit toggle also drops any zoom-to-question (Phase 3)
  applyFitMode();
}

/* ---------- Row table (name box · sections · questions, reorderable) ------- */
/* Reorder respects the pin: the name box stays first, so nothing moves above it
   and the name row carries no ↑/↓. */
function moveUp(tr) {
  const prev = tr.previousElementSibling;
  if (prev && rowType(prev) !== "name") tr.parentNode.insertBefore(tr, prev);
  renumber();
}
function moveDown(tr) {
  const next = tr.nextElementSibling;
  if (next) tr.parentNode.insertBefore(next, tr);
  renumber();
}

function addRow(label = "", range = "", score = "") {
  const tb = $("#qRows");
  const tr = document.createElement("tr");
  tr.dataset.rowtype = "question";
  tr.innerHTML = `
    <td><span class="swatch"></span></td>
    <td><input class="qlabel" type="text" placeholder="Q?" value="" autocomplete="off"></td>
    <td><input class="qrange" type="text" placeholder="page1!A2:C5" value="" autocomplete="off"></td>
    <td><input class="qscore" type="text" placeholder="3" value="" autocomplete="off"></td>
    <td><button class="rowbtn up" title="Move up">↑</button></td>
    <td><button class="rowbtn dn" title="Move down">↓</button></td>
    <td><button class="rowbtn del" title="Remove">✕</button></td>`;
  tr.querySelector(".qlabel").value = label;
  tr.querySelector(".qrange").value = range;
  tr.querySelector(".qscore").value = score;
  tr.querySelectorAll("input").forEach(i => i.addEventListener("input", refreshHighlights));
  tr.querySelector(".up").addEventListener("click", () => moveUp(tr));
  tr.querySelector(".dn").addEventListener("click", () => moveDown(tr));
  tr.querySelector(".del").addEventListener("click", () => { tr.remove(); renumber(); });
  // Clicking the colour swatch zooms the preview to this question's cells.
  tr.querySelector(".swatch").addEventListener("click", () =>
    zoomToRangeStr(tr.querySelector(".qrange").value.trim()));
  tb.appendChild(tr);
  renumber();
}

/* A section header. Questions below it (until the next header) belong to it.
   "All required" (checked) means every question counts; unchecking reveals a
   numeric "choose N of them" for an over-answered choice section. */
function addSectionRow(name = "", required = null) {
  const tb = $("#qRows");
  const tr = document.createElement("tr");
  tr.dataset.rowtype = "section";
  tr.className = "secrow";
  tr.innerHTML = `
    <td><span class="swatch secmark">§</span></td>
    <td colspan="3">
      <span class="seclabel">Section:</span>
      <input class="secname" type="text" placeholder="Section name" autocomplete="off">
      <span class="secreqwrap">· choose
        <input class="secrequired" type="number" min="1" step="1">
        <label><input type="checkbox" class="secall" checked> all required</label>
      </span>
    </td>
    <td><button class="rowbtn up" title="Move up">↑</button></td>
    <td><button class="rowbtn dn" title="Move down">↓</button></td>
    <td><button class="rowbtn del" title="Remove">✕</button></td>`;
  tr.querySelector(".secname").value = name;
  const reqInp = tr.querySelector(".secrequired");
  const allChk = tr.querySelector(".secall");
  const hasReq = (required !== null && required !== undefined && required !== "");
  allChk.checked = !hasReq;
  reqInp.value = hasReq ? required : "";
  reqInp.disabled = allChk.checked;
  allChk.addEventListener("change", () => {
    reqInp.disabled = allChk.checked;
    if (allChk.checked) reqInp.value = "";
    refreshHighlights();
  });
  tr.querySelector(".up").addEventListener("click", () => moveUp(tr));
  tr.querySelector(".dn").addEventListener("click", () => moveDown(tr));
  tr.querySelector(".del").addEventListener("click", () => { tr.remove(); renumber(); });
  tb.appendChild(tr);
  renumber();
}

/* The optional handwritten-name region — one per exam, pinned above everything.
   No score, no reorder; deletable. */
function addNameBoxRow(range = "") {
  if (nameRow()) return;                    // only one name box
  const tb = $("#qRows");
  const tr = document.createElement("tr");
  tr.dataset.rowtype = "name";
  tr.className = "namerow";
  tr.innerHTML = `
    <td><span class="swatch namemark"></span></td>
    <td class="namelabel">Name</td>
    <td><input class="qrange" type="text" placeholder="page1!A1:E2" value="" autocomplete="off"></td>
    <td></td><td></td><td></td>
    <td><button class="rowbtn del" title="Remove name box">✕</button></td>`;
  tr.querySelector(".qrange").value = range;
  tr.querySelector(".qrange").addEventListener("input", refreshHighlights);
  tr.querySelector(".del").addEventListener("click", () => {
    tr.remove(); updateNameBtn(); renumber();
  });
  tb.insertBefore(tr, tb.firstChild);       // pinned first
  updateNameBtn();
  renumber();
}

function updateNameBtn() {
  const btn = $("#addNameBtn");
  if (btn) btn.disabled = !!nameRow();
}

function renumber() {                       // colour question swatches by q-index
  let qi = 0;
  allRows().forEach(tr => {
    if (rowType(tr) !== "question") return;
    tr.querySelector(".swatch").style.background = Q_COLORS[qi % Q_COLORS.length];
    tr.querySelector(".qlabel").placeholder = "Q" + (qi + 1);
    qi++;
  });
  refreshHighlights();
}

/* Walk the mixed row list into the saved config shape: name_box (or null),
   sections [{name,required}], and questions [{label,range,max,section}] with
   each question pinned to the most recent section header above it. */
function configPayload() {
  const sections = [];
  const questions = [];
  let nameBox = null, curSection = "";
  allRows().forEach(tr => {
    const t = rowType(tr);
    if (t === "name") {
      const r = tr.querySelector(".qrange").value.trim();
      if (r) nameBox = r;
    } else if (t === "section") {
      const nm = tr.querySelector(".secname").value.trim();
      const all = tr.querySelector(".secall").checked;
      const reqv = tr.querySelector(".secrequired").value.trim();
      const required = (all || !reqv) ? null : parseInt(reqv, 10);
      sections.push({name: nm, required});
      curSection = nm;
    } else if (t === "question") {
      const label = tr.querySelector(".qlabel").value.trim();
      const range = tr.querySelector(".qrange").value.trim();
      const max = tr.querySelector(".qscore").value.trim();
      if (label && range)
        questions.push({label, range, max: max || "0-1", section: curSection});
    }
  });
  return {
    name: $("#examName").value.trim(),
    paper_size: $("#paperSelect").value,
    grid: currentDensity(),
    pdf_folder: FOLDER,
    name_box: nameBox,
    sections,
    questions,
  };
}

/* ---------- Left panel: folder loading + page preview ---------- */
async function loadFolder() {
  const folder = $("#folderInput").value.trim();
  if (!folder) { alert("Paste the folder path holding the student PDFs."); return; }
  setStatus("Scanning folder…");
  try {
    const res = await fetch("/api/exam/scan_folder", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({folder})
    });
    const d = await res.json();
    if (!res.ok) { setStatus(""); alert(d.error || "Could not read folder."); return; }
    FOLDER = d.folder; PAGE_COUNT = d.page_count || 1;
    const sel = $("#pageSelect"); sel.innerHTML = "";
    for (let p = 1; p <= PAGE_COUNT; p++) {
      const o = document.createElement("option");
      o.value = p; o.textContent = "Page " + p; sel.appendChild(o);
    }
    setStatus(d.file_count + " student file(s) — previewing " + d.first_student);
    // Focus-adjust (Phase 6) may want a later page; default to page 1 otherwise.
    showPage(FOCUS_PAGE <= PAGE_COUNT ? FOCUS_PAGE : 1);
  } catch (e) { setStatus(""); alert("Error: " + e); }
}

function showPage(p) {
  $("#pageSelect").value = String(p);
  const img = $("#pageImg");
  img.src = "/api/exam/preview?folder=" + encodeURIComponent(FOLDER) + "&page=" + p
          + "&t=" + Date.now();
  img.onload = () => {
    $("#noPage").style.display = "none";
    img.style.display = "block";
    $("#gridOverlay").style.display = "grid";
    $("#fitToggleBtn").classList.remove("hidden");   // fit toggle lives whenever a page is loaded
    refreshHighlights();
    sizeCellLabels();      // cell pixels are laid out now — size the labels to them
    applyZoom();           // re-frame once the new page's pixels are laid out
  };
}

/* ---------- Saved exams: load an existing definition for editing ---------- */
async function refreshExamList() {
  if (!CLASS_NAME) return;
  try {
    const res = await fetch("/api/exams?class_name=" + encodeURIComponent(CLASS_NAME));
    const d = await res.json();
    const sel = $("#examLoadSelect");
    sel.innerHTML = '<option value="">— new exam —</option>';
    Object.keys(d.exams || {}).sort().forEach(n => {
      const o = document.createElement("option"); o.value = n; o.textContent = n;
      sel.appendChild(o);
    });
    sel.dataset.exams = JSON.stringify(d.exams || {});
  } catch (e) { console.warn("exam list failed", e); }
}

function loadExamConfig() {
  const name = $("#examLoadSelect").value;
  if (!name) return;
  const cfg = (JSON.parse($("#examLoadSelect").dataset.exams || "{}"))[name];
  if (!cfg) return;
  resetFocus();               // dropping any prior focus/zoom before rebuilding
  $("#examName").value = cfg.name;
  $("#paperSelect").value = cfg.paper_size || "A4";
  // Density follows the saved config; a missing/legacy "grid" reveals the
  // load-only "Standard (legacy 2 cm)" option so the coordinates render on the
  // right grid. Compact/fine drop that option — new exams never see it.
  const density = ["compact", "fine"].includes(cfg.grid) ? cfg.grid : "legacy";
  if (density === "legacy") { ensureLegacyOption(); $("#gridSelect").value = "legacy"; }
  else { dropLegacyOption(); $("#gridSelect").value = density; }
  applyPaperGrid();                       // grid matrix follows the saved paper + density
  $("#qRows").innerHTML = "";
  // Name box (optional, pinned first).
  if (cfg.name_box) addNameBoxRow(cfg.name_box);
  // Sections then their questions, in stored order. A legacy config with no
  // sections synthesizes one default section holding every question.
  const sections = (cfg.sections && cfg.sections.length)
      ? cfg.sections : [{name: DEFAULT_SECTION_NAME, required: null}];
  const validNames = new Set(sections.map(s => s.name));
  const byS = {};
  (cfg.questions || []).forEach(q => {
    const s = validNames.has(q.section) ? q.section : sections[0].name;
    (byS[s] = byS[s] || []).push(q);
  });
  sections.forEach(s => {
    addSectionRow(s.name, s.required);
    (byS[s.name] || []).forEach(q => addRow(q.label, q.range, String(q.max)));
  });
  updateNameBtn();
  if (cfg.pdf_folder) { $("#folderInput").value = cfg.pdf_folder; loadFolder(); }
}

/* ---------- Focus-adjust one question mid-grading (Phase 6) ---------- */
/* Clear any active focus + zoom (called before loading a different exam). */
function resetFocus() {
  FOCUS_LABEL = ""; FOCUS_ROW = null; FOCUS_PAGE = 1;
  $("#focusBar").classList.add("hidden");
  allRows().forEach(tr => tr.classList.remove("focusrow"));
  clearZoom();
}

function findQuestionRow(label) {
  return allRows().find(tr => rowType(tr) === "question"
    && tr.querySelector(".qlabel").value.trim() === label) || null;
}

/* Land on one question: highlight + scroll to its row, zoom the preview to its
   cells, and reveal the "re-slice this question" action. Called after the exam
   is loaded (from grading's ✎ deep-link, ?exam=..&focus=<label>). */
function enterFocusMode(label) {
  const row = findQuestionRow(label);
  if (!row) { setStatus("Question '" + label + "' not found in this exam."); return; }
  FOCUS_LABEL = label; FOCUS_ROW = row;
  allRows().forEach(tr => tr.classList.remove("focusrow"));
  row.classList.add("focusrow");
  row.scrollIntoView({block: "center", behavior: "smooth"});
  $("#focusBar").classList.remove("hidden");
  $("#focusNote").textContent = "Adjusting " + label + " — tweak its coordinate "
    + "range on the right (zoomed in on the left), then re-slice just this "
    + "question. Entered marks are kept.";
  const rng = parseRange(row.querySelector(".qrange").value.trim());
  if (rng) { ZOOM_RANGE = rng; FOCUS_PAGE = rng.page; applyZoom(); }
}

/* Re-slice ONLY the focused question for every student, then signal the grading
   tab to refresh its crops. Saves the (possibly widened) config first. */
async function resliceOne() {
  const label = FOCUS_ROW ? FOCUS_ROW.querySelector(".qlabel").value.trim() : FOCUS_LABEL;
  if (!label) { alert("Open a question to adjust first."); return; }
  const cfg = configPayload();
  if (!cfg.pdf_folder) { alert("Load the student PDF folder first."); return; }
  const saved = await saveSetup(true);
  if (!saved) return;
  $("#resliceBtn").disabled = true;
  setStatus("Re-slicing " + label + "…");
  try {
    const res = await fetch("/api/exam/process_one", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({class_name: CLASS_NAME, config: cfg, label})
    });
    const d = await res.json();
    if (!res.ok) { setStatus(""); alert(d.error || "Re-slice failed."); return; }
    await pollResliceJob(d.job_id, label);
  } catch (e) { setStatus(""); alert("Re-slice error: " + e); }
  finally { $("#resliceBtn").disabled = false; }
}

async function pollResliceJob(jobId, label) {
  while (true) {
    let d;
    try {
      const res = await fetch("/api/exam/status/" + encodeURIComponent(jobId));
      d = await res.json();
      if (!res.ok) { setStatus(""); alert(d.error || "Lost track of the re-slice job."); return; }
    } catch (e) { setStatus(""); alert("Status check failed: " + e); return; }
    if (d.state === "running") {
      setStatus("Re-slicing " + label + " — " + d.done + " / " + (d.total || "?") + "…");
      await new Promise(r => setTimeout(r, 800));
      continue;
    }
    if (d.state === "error") { setStatus(""); alert(d.error || "Re-slice failed."); return; }
    const r = d.result || {};                       // state === "done"
    setStatus("Re-sliced " + label + " for " + r.students + " student(s).");
    let note = "✅ Re-sliced '" + label + "' — " + r.crops + " crop(s) across "
             + r.students + " student(s). Back in the grading tab, " + label
             + "'s answers now show the new framing.";
    if ((r.errors || []).length)
      note += "\n⚠ " + r.errors.length + " problem(s):\n  " + r.errors.slice(0, 12).join("\n  ");
    $("#procNote").textContent = note;
    // Same-origin ping to the grading tab: bump its crop cache-buster (Phase 6).
    try {
      localStorage.setItem("cam_exam_resliced", JSON.stringify({
        class: CLASS_NAME, exam: $("#examName").value.trim(), label, ts: Date.now()
      }));
    } catch (_) {}
    return;
  }
}

/* ---------- Save + Process ---------- */
async function saveSetup(silent) {
  const cfg = configPayload();
  if (!CLASS_NAME) { alert("Open Exam Setup from the main screen with a class selected."); return null; }
  if (!cfg.name) { alert("Give the exam a name."); return null; }
  if (!cfg.questions.length) { alert("Program at least one question (label + range)."); return null; }
  try {
    const res = await fetch("/api/exam/save", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({class_name: CLASS_NAME, config: cfg})
    });
    const d = await res.json();
    if (!res.ok) { alert(d.error || "Save failed."); return null; }
    if (!silent) setStatus("Saved '" + d.config.name + "' (" + d.config.questions.length + " questions).");
    refreshExamList();
    return d.config;
  } catch (e) { alert("Save error: " + e); return null; }
}

async function processAll() {
  const cfg = configPayload();
  if (!cfg.pdf_folder) { alert("Load the student PDF folder first."); return; }
  const saved = await saveSetup(true);
  if (!saved) return;
  setStatus("Starting…");
  $("#processBtn").disabled = true;
  try {
    const res = await fetch("/api/exam/process", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({class_name: CLASS_NAME, config: cfg})
    });
    const d = await res.json();
    if (!res.ok) { setStatus(""); alert(d.error || "Processing failed."); return; }
    await pollExamJob(d.job_id);
  } catch (e) { setStatus(""); alert("Processing error: " + e); }
  finally { $("#processBtn").disabled = false; }
}

// Slicing now runs on a background thread server-side; poll for progress.
async function pollExamJob(jobId) {
  while (true) {
    let d;
    try {
      const res = await fetch("/api/exam/status/" + encodeURIComponent(jobId));
      d = await res.json();
      if (!res.ok) { setStatus(""); alert(d.error || "Lost track of the slicing job."); return; }
    } catch (e) { setStatus(""); alert("Status check failed: " + e); return; }
    if (d.state === "running") {
      setStatus("Slicing student PDFs — " + d.done + " / " + (d.total || "?") + " done…");
      await new Promise(r => setTimeout(r, 1000));
      continue;
    }
    if (d.state === "error") { setStatus(""); alert(d.error || "Processing failed."); return; }
    const r = d.result || {};                       // state === "done"
    setStatus("Done — " + r.crops + " crops from " + r.students + " student(s).");
    let note = "✅ Sliced " + r.crops + " answer image(s) across " + r.students +
               " student(s) × " + r.questions + " question(s).\n" +
               "'" + r.exam_name + "' now appears under Exams in the main " +
               "grading screen's assignment dropdown.";
    if ((r.errors || []).length)
      note += "\n⚠ " + r.errors.length + " problem(s):\n  " + r.errors.slice(0, 12).join("\n  ");
    $("#procNote").textContent = note;
    return;
  }
}

/* ---------- wire up ---------- */
$("#loadFolderBtn").addEventListener("click", loadFolder);
$("#folderInput").addEventListener("keydown", e => { if (e.key === "Enter") loadFolder(); });
$("#pageSelect").addEventListener("change", () => showPage(parseInt($("#pageSelect").value, 10)));
$("#addQBtn").addEventListener("click", () => addRow());
$("#addSectionBtn").addEventListener("click", () => addSectionRow());
$("#addNameBtn").addEventListener("click", () => addNameBoxRow());
$("#saveBtn").addEventListener("click", () => saveSetup(false));
$("#processBtn").addEventListener("click", processAll);
$("#zoomToggleBtn").addEventListener("click", clearZoom);
$("#fitToggleBtn").addEventListener("click", toggleFitMode);
$("#resliceBtn").addEventListener("click", resliceOne);
$("#examLoadSelect").addEventListener("change", loadExamConfig);
$("#paperSelect").addEventListener("change", applyPaperGrid);
$("#gridSelect").addEventListener("change", () => {
  // Choosing a real density retires the load-only legacy option; the teacher
  // then re-types any ranges that fall outside the new grid (flagged red).
  if ($("#gridSelect").value !== "legacy") dropLegacyOption();
  applyPaperGrid();
});
$("#gridColorSelect").addEventListener("change", () => {
  const col = $("#gridColorSelect").value || GRID_COLOR_DEFAULT;
  try { localStorage.setItem(GRID_COLOR_KEY, col); } catch (e) {}
  applyGridColor(col);
});
window.addEventListener("resize", sizeCellLabels);  // labels track the cell size

initGridColor();            // restore the per-device grid colour before building
initFitMode();              // restore the per-device fit-width/fit-page choice
applyPaperGrid();           // build the initial (A4 compact 15×21) overlay + labels
addSectionRow(DEFAULT_SECTION_NAME);  // new exams start with one section header
addRow("Q1", "", "3");      // start with one empty question row ready to fill
updateNameBtn();

/* Deep-links into this page:
   ?exam=<name>              — CAM bridge: pre-fill a new exam's name, OR load
                               an existing one for editing.
   ?exam=<name>&focus=<label> — grading's ✎: load the exam and land focused on
                               one question to adjust + re-slice it (Phase 6). */
const _params = new URLSearchParams(location.search);
const EXAM_PREFILL = _params.get("exam") || "";
const FOCUS_PARAM = _params.get("focus") || "";
refreshExamList().then(() => {
  const exams = JSON.parse($("#examLoadSelect").dataset.exams || "{}");
  if (EXAM_PREFILL && exams[EXAM_PREFILL]) {
    $("#examLoadSelect").value = EXAM_PREFILL;
    loadExamConfig();                       // load the saved definition
    if (FOCUS_PARAM) enterFocusMode(FOCUS_PARAM);
  } else if (EXAM_PREFILL && !$("#examName").value.trim()) {
    $("#examName").value = EXAM_PREFILL;     // brand-new exam handed over from CAM
    setStatus('Exam "' + EXAM_PREFILL + '" (from CAM) — load the PDF folder, ' +
              'program the questions, then Save & Process.');
  }
});
</script>
</body>
</html>
"""


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="CAM Grading Workspace — Flask sub-app of Criterion "
                    "Assessment Metrics.")
    parser.add_argument("--port", type=int, default=5000,
                        help="Port to serve on (the CAM bridge uses a separate "
                             "port so Streamlit is never blocked).")
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    print("=" * 64)
    print(" CAM Grading Workspace  (student-grouped)")
    secret = find_client_secret()
    print(" Client secret:", os.path.basename(secret) if secret else "NOT FOUND (add credentials.json)")
    print(f" Open: http://{args.host}:{args.port}")
    print("=" * 64)
    app.run(host=args.host, port=args.port, debug=False)
