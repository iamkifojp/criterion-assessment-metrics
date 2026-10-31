"""What the running server remembers: the open session and background jobs.

CAM2 serves one teacher on one computer, so there is at most one open session
per server. Long tasks (copying scans, slicing) run as :class:`Job`s in a
background thread; the browser polls their progress.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Callable, Optional

from engine import grading_summary, storage
from engine.errors import UserError


class Job:
    def __init__(self, kind: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.done = 0
        self.total = 0
        self.status = "running"          # running | done | error
        self.result = None
        self.error: Optional[Exception] = None

    def progress(self, done: int, total: int) -> None:
        self.done, self.total = done, total


class AppState:
    def __init__(self):
        self.lock = threading.RLock()
        self.session: Optional[storage.Session] = None
        self.config: Optional[dict] = None
        self.grades: Optional[dict] = None
        self.jobs: dict = {}
        self.last_heartbeat = time.monotonic()
        self.roster_rows: Optional[list] = None      # uploaded class list awaiting a column choice
        self.save_failed = False
        self.host: Optional[dict] = None             # set when another app (CAM) opened CAM2

    # Session ---------------------------------------------------------------------

    def require_session(self) -> storage.Session:
        if self.session is None:
            raise UserError("no_open_session")
        return self.session

    def set_session(self, session, config, grades) -> None:
        with self.lock:
            if self.session is not None and self.session.folder != session.folder:
                storage.release_lock(self.session.folder)
            self.session, self.config, self.grades = session, config, grades
            self.roster_rows = None
            self.save_failed = False

    def close_session(self) -> None:
        with self.lock:
            if self.session is not None:
                storage.release_lock(self.session.folder)
            self.session = self.config = self.grades = None
            self.roster_rows = None
            self.save_failed = False

    def save_config(self) -> dict:
        """Save the in-memory exam set-up. On failure the change stays in memory
        (and in the emergency copy) and the error goes to the browser."""
        with self.lock:
            session = self.require_session()
            try:
                self.config = session.config_file.save(self.config)
                self.save_failed = False
            except UserError:
                self.save_failed = True
                raise
            self.remember()
            return self.config

    def save_grades(self) -> dict:
        with self.lock:
            session = self.require_session()
            try:
                self.grades = session.grades_file.save(self.grades)
                self.save_failed = False
            except UserError:
                self.save_failed = True
                raise
            return self.grades

    def save_all(self) -> None:
        self.save_config()
        self.save_grades()

    def remember(self) -> None:
        """Update this session's card on the start screen."""
        if self.session is None or self.config is None:
            return
        prog = grading_summary.progress(self.config, self.grades or {})
        try:
            storage.remember_session(
                self.session.folder, self.config.get("exam_name", ""),
                step=int((self.config.get("resume") or {}).get("step") or 1),
                graded=prog["students_done"], total=prog["students_total"])
        except (OSError, UserError):
            pass

    def last_saved_at(self) -> Optional[str]:
        if self.session is None:
            return None
        stamps = [self.session.config_file.last_saved_at,
                  self.session.grades_file.last_saved_at]
        stamps = [s for s in stamps if s]
        return max(stamps) if stamps else None

    # Jobs ------------------------------------------------------------------------

    def start_job(self, kind: str, work: Callable[[Job], object]) -> Job:
        with self.lock:
            busy = [j for j in self.jobs.values() if j.status == "running"]
            if busy:
                raise UserError("busy")
            job = Job(kind)
            self.jobs = {job.id: job}           # keep only the latest job

        def run():
            try:
                job.result = work(job)
                job.status = "done"
            except Exception as exc:               # reported to the browser
                if not isinstance(exc, UserError):
                    traceback.print_exc()
                job.error = exc
                job.status = "error"

        threading.Thread(target=run, name=f"cam2-{kind}", daemon=True).start()
        return job

    def heartbeat(self) -> Optional[dict]:
        """Note that a CAM2 tab is still open and refresh the session lock.

        Returns another computer's lock if one has taken the session over.
        """
        self.last_heartbeat = time.monotonic()
        if self.session is not None and self.config is not None:
            return storage.claim_lock(self.session.folder)
        return None
