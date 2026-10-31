"""Session folders and safe saving.

A session folder may sit on a local disk, a USB stick, OneDrive or Google
Drive. The rules below are ported from CAM's ``engine/persistence.py``:

* **Safe write** — write a temp file, flush it to disk, rename it over the
  real file, then read it back and compare a SHA-256 hash. A brief lock by a
  sync program is retried before it counts as a failure.
* **Emergency copy first** — every save is also written to this computer's
  app-data folder *before* the session folder is touched, so a pulled USB
  stick or a failed write never loses work.
* **Changed elsewhere** — each file carries a ``session_id`` and a
  ``generation`` counter. If the file on disk is no longer the one we loaded
  (another computer saved), the save stops instead of overwriting it.
* **Cloud conflict copies** — files such as ``grades-LAPTOP.json`` (OneDrive),
  ``grades (1).json`` (Google Drive) or ``grades (… conflicted copy).json``
  (Dropbox) stop the save until the teacher has looked at them.
* **Wipe guard** — a save that would remove most existing grades is refused
  unless explicitly allowed.
* **Daily backups** — the previous version is copied to
  ``backups/<file>.bak-YYYYMMDD`` once a day; the newest 14 are kept.

Per-computer data (recent sessions, language, emergency copies) lives in the
app-data folder, never in the app folder, so it survives a new version.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from . import model
from .errors import SaveError, UserError
from .slicer import safe_filename

SESSION_FILE = "cam2_session.json"
GRADES_FILE = "grades.json"
LOCK_FILE = "cam2.lock"
BACKUP_DIR = "backups"
BACKUP_KEEP = 14
SCANS_DIR = "scans"
CROPS_DIR = "crops"
THUMBS_DIR = "thumbs"
REPORTS_DIR = "reports"

RECENT_FILE = "recent_sessions.json"
PREFS_FILE = "prefs.json"
EMERGENCY_DIR = "emergency"
RECENT_MAX = 10

LOCK_STALE_SECONDS = 10 * 60
SHRINK_MIN_MASS = 10
SHRINK_KEEP_RATIO = 0.33
WRITE_ATTEMPTS = 6
WRITE_RETRY_SECONDS = 0.25

# Folder names teachers may see: app data, and the default home for sessions.
APP_FOLDER = "CAM2 Exam Grading"
SESSIONS_FOLDER = "CAM2 Exam Grading Sessions"

# Identifies this running copy of CAM2 in lock files.
INSTANCE_ID = uuid.uuid4().hex


# --- Save errors (each has an i18n message) -----------------------------------------

class FolderUnavailable(SaveError):
    def __init__(self, folder):
        super().__init__("save_folder_unavailable", folder=folder)


class ConflictCopiesFound(SaveError):
    def __init__(self, files):
        self.files = tuple(files)
        super().__init__("save_conflict_copies",
                         files=", ".join(os.path.basename(f) for f in files))


class ChangedElsewhere(SaveError):
    def __init__(self, saved_by, saved_at):
        super().__init__("save_changed_elsewhere", saved_by=saved_by or "?",
                         saved_at=saved_at or "?")


class FileMissing(SaveError):
    def __init__(self, file):
        super().__init__("save_file_missing", file=file)


class WipeBlocked(SaveError):
    def __init__(self, before, after):
        super().__init__("save_wipe_blocked", before=before, after=after)


class WriteNotVerified(SaveError):
    def __init__(self, file):
        super().__init__("save_not_verified", file=file)


class WriteFailed(SaveError):
    def __init__(self, file, reason):
        super().__init__("save_write_failed", file=file, reason=reason)


# --- Small helpers -------------------------------------------------------------------

def computer_name() -> str:
    return platform.node() or "this computer"


def app_data_dir() -> str:
    """Per-user folder for CAM2's own data on this computer."""
    override = os.environ.get("CAM2_APP_DATA", "").strip()
    if override:
        path = os.path.abspath(os.path.expanduser(override))
    elif os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        path = os.path.join(base, APP_FOLDER)
    elif sys.platform == "darwin":
        path = os.path.expanduser(f"~/Library/Application Support/{APP_FOLDER}")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        path = os.path.join(base, APP_FOLDER)
    os.makedirs(path, exist_ok=True)
    return path


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _to_bytes(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _read_bytes(path: str) -> Optional[bytes]:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None


def _retry(action: Callable[[], None], what: str) -> None:
    """Run a file action, retrying while a sync program briefly holds the file."""
    last = None
    for attempt in range(WRITE_ATTEMPTS):
        try:
            action()
            return
        except PermissionError as exc:        # typically a sync client's lock
            last = exc
        except OSError as exc:
            # ERROR_SHARING_VIOLATION (32) / ERROR_LOCK_VIOLATION (33) on Windows
            if getattr(exc, "winerror", None) not in (32, 33):
                raise WriteFailed(what, str(exc)) from exc
            last = exc
        time.sleep(WRITE_RETRY_SECONDS * (attempt + 1))
    raise WriteFailed(what, str(last))


def atomic_write(path: str, raw: bytes) -> None:
    """Temp file + fsync + rename, so a crash never leaves a half-written file."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".cam2-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        _retry(lambda: os.replace(tmp, path), os.path.basename(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


def find_conflict_copies(path: str) -> tuple:
    """Likely cloud-sync conflict copies sitting beside ``path``.

    Matches ``<stem><sep>…<ext>`` where sep is one of `` ([{-_`` — the forms
    OneDrive, Google Drive, Dropbox and iCloud use. CAM2's own temp files end
    in ``.tmp`` and its backups live in ``backups/``, so neither matches.
    """
    absolute = os.path.abspath(path)
    directory = os.path.dirname(absolute)
    stem, ext = os.path.splitext(os.path.basename(absolute))
    stem_l, ext_l = stem.lower(), ext.lower()
    found = []
    try:
        entries = list(os.scandir(directory))
    except OSError:
        return ()
    for entry in entries:
        name_l = entry.name.lower()
        if not name_l.endswith(ext_l) or name_l == stem_l + ext_l:
            continue
        candidate = name_l[:-len(ext_l)]
        rest = candidate[len(stem_l):]
        if not candidate.startswith(stem_l) or not rest or rest[0] not in " ([{-_":
            continue
        try:
            if entry.is_file(follow_symlinks=False):
                found.append(os.path.abspath(entry.path))
        except OSError:
            continue
    return tuple(sorted(found, key=os.path.normcase))


def check_writable(folder: str) -> None:
    """Raise UserError unless ``folder`` exists (or can be made) and accepts files."""
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, f".cam2-write-test-{uuid.uuid4().hex[:8]}")
        with open(probe, "wb") as fh:
            fh.write(b"ok")
        os.remove(probe)
    except OSError as exc:
        raise UserError("folder_not_writable", folder=folder) from exc


def default_session_folder(exam_name: str, documents: str) -> str:
    """``<Documents>/CAM2 Exam Grading Sessions/<Exam name>``, avoiding a folder already in use."""
    parent = os.path.join(documents, SESSIONS_FOLDER)
    base = safe_filename(exam_name, "Exam")
    candidate, n = os.path.join(parent, base), 1
    while os.path.isdir(candidate) and os.listdir(candidate):
        n += 1
        candidate = os.path.join(parent, f"{base} ({n})")
    return candidate


def relative_path(folder: str, path: str) -> str:
    """Path of ``path`` inside the session folder, with forward slashes."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    if rel == os.pardir or rel.startswith(os.pardir + os.sep) or os.path.isabs(rel):
        raise UserError("path_outside_session", path=path)
    return rel.replace(os.sep, "/")


def resolve_path(folder: str, rel: str) -> str:
    """Absolute path for a session-relative path; refuses to leave the folder."""
    root = os.path.abspath(folder)
    full = os.path.abspath(os.path.join(root, *str(rel).split("/")))
    if os.path.commonpath([root, full]) != root:
        raise UserError("path_outside_session", path=rel)
    return full


# --- One safety-checked JSON file ------------------------------------------------------

class SafeJsonFile:
    """``cam2_session.json`` or ``grades.json`` inside a session folder.

    Call :meth:`load` (or :meth:`create`) first; :meth:`save` then refuses to
    overwrite a version it has not seen.
    """

    def __init__(self, folder: str, filename: str, expected_format: str,
                 mass: Optional[Callable[[dict], int]] = None):
        self.folder = os.path.abspath(folder)
        self.filename = filename
        self.path = os.path.join(self.folder, filename)
        self.expected_format = expected_format
        self.mass = mass
        self.session_id: Optional[str] = None
        self.generation = 0
        self.content_hash: Optional[str] = None
        self.last_saved_at: Optional[str] = None
        self._lock = threading.Lock()

    # Loading -------------------------------------------------------------------

    def load(self) -> dict:
        raw = _read_bytes(self.path)
        if raw is None:
            raise FileMissing(self.filename)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise UserError("file_damaged", file=self.filename) from exc
        model.check_format(data, self.expected_format)
        self.session_id = str(data.get("session_id") or "")
        self.generation = int(data.get("generation") or 0)
        self.content_hash = _sha256(raw)
        self.last_saved_at = data.get("saved_at")
        return data

    def create(self, data: dict) -> dict:
        """Write the first version of this file. Refuses to replace an existing one."""
        if os.path.exists(self.path):
            raise UserError("session_exists", folder=self.folder)
        self.session_id = str(data["session_id"])
        self.generation = 0
        self.content_hash = None
        return self.save(data)

    # Saving --------------------------------------------------------------------

    def save(self, data: dict, *, allow_shrink: bool = False) -> dict:
        with self._lock:
            payload = dict(data)
            payload["session_id"] = self.session_id
            payload["generation"] = self.generation + 1
            payload["saved_at"] = model.now_iso()
            payload["saved_by"] = computer_name()
            raw = _to_bytes(payload)

            self._write_emergency(raw)
            if not os.path.isdir(self.folder):
                raise FolderUnavailable(self.folder)
            copies = find_conflict_copies(self.path)
            if copies:
                raise ConflictCopiesFound(copies)

            observed = _read_bytes(self.path)
            if observed is None:
                if self.content_hash is not None:
                    raise FileMissing(self.filename)
            elif _sha256(observed) != self.content_hash:
                other = _parse_or_empty(observed)
                raise ChangedElsewhere(other.get("saved_by"), other.get("saved_at"))

            if observed is not None and self.mass and not allow_shrink:
                before = self.mass(_parse_or_empty(observed))
                after = self.mass(payload)
                if before >= SHRINK_MIN_MASS and after < before * SHRINK_KEEP_RATIO:
                    raise WipeBlocked(before, after)

            if observed is not None:
                self._daily_backup(observed)

            atomic_write(self.path, raw)
            written = _read_bytes(self.path)
            if written is None or _sha256(written) != _sha256(raw):
                raise WriteNotVerified(self.filename)

            self.generation = payload["generation"]
            self.content_hash = _sha256(raw)
            self.last_saved_at = payload["saved_at"]
            return payload

    def _daily_backup(self, raw: bytes) -> None:
        backups = os.path.join(self.folder, BACKUP_DIR)
        stamp = datetime.now().strftime("%Y%m%d")
        target = os.path.join(backups, f"{self.filename}.bak-{stamp}")
        if os.path.exists(target):
            return
        try:
            atomic_write(target, raw)
        except (OSError, SaveError):
            return          # a missed backup must never block a save
        prefix = self.filename + ".bak-"
        try:
            mine = sorted(n for n in os.listdir(backups) if n.startswith(prefix))
            for old in mine[:-BACKUP_KEEP]:
                os.remove(os.path.join(backups, old))
        except OSError:
            pass

    # Emergency copy on this computer --------------------------------------------

    def emergency_path(self) -> str:
        return os.path.join(app_data_dir(), EMERGENCY_DIR,
                            safe_filename(self.session_id or "unknown"), self.filename)

    def _write_emergency(self, raw: bytes) -> None:
        try:
            atomic_write(self.emergency_path(), raw)
        except (OSError, SaveError):
            pass            # best effort; the real save still runs

    def newer_emergency_copy(self) -> Optional[dict]:
        """The emergency copy, if it holds work the session folder is missing."""
        raw = _read_bytes(self.emergency_path())
        if raw is None:
            return None
        data = _parse_or_empty(raw)
        if (data.get("format") == self.expected_format
                and data.get("session_id") == self.session_id
                and int(data.get("generation") or 0) > self.generation):
            return data
        return None


def _parse_or_empty(raw: bytes) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}
    except (UnicodeDecodeError, ValueError):
        return {}


# --- Opening and creating sessions ------------------------------------------------------

class Session:
    """The two files of one open session folder."""

    def __init__(self, folder: str):
        self.folder = os.path.abspath(folder)
        self.config_file = SafeJsonFile(self.folder, SESSION_FILE, model.SESSION_FORMAT)
        self.grades_file = SafeJsonFile(self.folder, GRADES_FILE, model.GRADES_FORMAT,
                                        mass=model.grades_mass)

    def path(self, rel: str) -> str:
        return resolve_path(self.folder, rel)


def is_session_folder(folder: str) -> bool:
    return os.path.isfile(os.path.join(folder, SESSION_FILE))


def create_session(folder: str, exam_name: str):
    """Start a new session in ``folder``. Returns (Session, config, grades)."""
    check_writable(folder)
    if is_session_folder(folder):
        raise UserError("session_exists", folder=folder)
    session_id = model.new_session_id()
    config = model.new_session(exam_name, session_id)
    session = Session(folder)
    config = session.config_file.create(config)
    grades = session.grades_file.create(model.new_grades(session_id))
    return session, config, grades


def open_session(folder: str):
    """Open an existing session. Returns (Session, config, grades)."""
    if not os.path.isdir(folder):
        raise FolderUnavailable(folder)
    if not is_session_folder(folder):
        raise UserError("not_a_session_folder", folder=folder)
    session = Session(folder)
    config = session.config_file.load()
    grades = session.grades_file.load()
    if config.get("session_id") != grades.get("session_id"):
        raise UserError("session_files_mismatch", folder=folder)
    return session, config, grades


# --- "Open on another computer" lock -----------------------------------------------------

def _lock_path(folder: str) -> str:
    return os.path.join(folder, LOCK_FILE)


def read_lock(folder: str) -> Optional[dict]:
    raw = _read_bytes(_lock_path(folder))
    return _parse_or_empty(raw) if raw is not None else None


def _held_elsewhere(lock: Optional[dict], now: datetime) -> bool:
    """A recent lock from another computer. A lock left by this computer is
    always stale (one CAM2 runs per computer), e.g. after a crash."""
    return bool(lock and lock.get("instance") != INSTANCE_ID
                and lock.get("computer") != computer_name()
                and _lock_is_fresh(lock, now))


def _lock_is_fresh(lock: dict, now: datetime) -> bool:
    try:
        beat = datetime.fromisoformat(str(lock.get("heartbeat")))
    except ValueError:
        return False
    return now - beat < timedelta(seconds=LOCK_STALE_SECONDS)


def claim_lock(folder: str, force: bool = False, now: Optional[datetime] = None
               ) -> Optional[dict]:
    """Mark the session as open here.

    Returns the other holder's lock (and leaves it alone) when another copy of
    CAM2 refreshed it recently, unless ``force``. Returns None once claimed.
    This is advisory only: cloud folders cannot do real file locking.
    """
    now = now or datetime.now(timezone.utc)
    current = read_lock(folder)
    if not force and _held_elsewhere(current, now):
        return current
    stamp = now.isoformat(timespec="seconds")
    lock = {"computer": computer_name(), "instance": INSTANCE_ID,
            "since": stamp, "heartbeat": stamp}
    if current and current.get("instance") == INSTANCE_ID:
        lock["since"] = current.get("since", stamp)
    try:
        atomic_write(_lock_path(folder), _to_bytes(lock))
    except (OSError, SaveError):
        pass
    return None


def other_lock_holder(folder: str, now: Optional[datetime] = None) -> Optional[dict]:
    """Another running CAM2's fresh lock on this folder, without claiming it."""
    current = read_lock(folder) if os.path.isdir(folder) else None
    return current if _held_elsewhere(current, now or datetime.now(timezone.utc)) else None


def release_lock(folder: str) -> None:
    current = read_lock(folder)
    if current and current.get("instance") == INSTANCE_ID:
        try:
            os.remove(_lock_path(folder))
        except OSError:
            pass


# --- Per-computer data: recent sessions and preferences -----------------------------------

def _read_app_json(name: str, default):
    raw = _read_bytes(os.path.join(app_data_dir(), name))
    if raw is None:
        return default
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _write_app_json(name: str, data) -> None:
    atomic_write(os.path.join(app_data_dir(), name),
                 json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def list_recent() -> list:
    """Recent sessions, newest first, each with ``available`` (folder found)."""
    items = _read_app_json(RECENT_FILE, [])
    out = []
    for item in items:
        if not isinstance(item, dict) or not item.get("folder"):
            continue
        entry = dict(item)
        entry["available"] = is_session_folder(entry["folder"])
        out.append(entry)
    return out


def remember_session(folder: str, exam_name: str, step: int = 1,
                     graded: int = 0, total: int = 0) -> None:
    folder = os.path.abspath(folder)
    key = os.path.normcase(folder)
    items = [i for i in _read_app_json(RECENT_FILE, [])
             if isinstance(i, dict) and os.path.normcase(str(i.get("folder"))) != key]
    items.insert(0, {"folder": folder, "exam_name": exam_name, "step": step,
                     "graded": graded, "total": total, "last_saved": model.now_iso()})
    _write_app_json(RECENT_FILE, items[:RECENT_MAX])


def forget_session(folder: str) -> None:
    key = os.path.normcase(os.path.abspath(folder))
    items = [i for i in _read_app_json(RECENT_FILE, [])
             if isinstance(i, dict) and os.path.normcase(str(i.get("folder"))) != key]
    _write_app_json(RECENT_FILE, items)


def get_pref(key: str, default=None):
    return _read_app_json(PREFS_FILE, {}).get(key, default)


def set_pref(key: str, value) -> None:
    prefs = _read_app_json(PREFS_FILE, {})
    prefs[key] = value
    _write_app_json(PREFS_FILE, prefs)
