"""Start CAM2 Exam Grading.

* If CAM2 is already running on this computer, just open the browser on it.
* Otherwise start the server on 127.0.0.1 only (nothing is visible on the
  school network), on the first free port from 5182, and open the browser.
* Stop by itself once no CAM2 tab has sent a heartbeat for 10 minutes
  (open tabs send one every minute), or when the teacher clicks Quit.

Usage:  python launcher.py [--port 5182] [--no-browser] [--idle 600] [--host handoff.json]

``--pick`` is only for the packaged app opening its own Windows file dialog
(see ``engine/pickers.py``).

``--host`` is for another app (CAM) opening one of its exams in CAM2; see
``engine/host.py``. A CAM2 that is already running is handed the exam.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

from werkzeug.serving import make_server

from app import create_app
from appstate import AppState
from engine import host, pickers, storage
from engine.errors import UserError

DEFAULT_PORT = 5182
IDLE_SECONDS = 10 * 60
CHECK_SECONDS = 30
SERVER_FILE = "server.json"


def _server_file() -> str:
    return os.path.join(storage.app_data_dir(), SERVER_FILE)


def watch_idle(state: AppState, idle: int, shutdown, clock=time.monotonic, sleep=time.sleep) -> None:
    """Stop once no CAM2 tab has sent a heartbeat for ``idle`` seconds.

    A check that comes far later than planned means the computer was asleep
    (Windows' clock keeps counting through sleep). Open tabs have had no chance
    to send a heartbeat yet, so the wait starts again rather than stopping
    CAM2 under a teacher who has just opened the lid.
    """
    last_check = clock()
    while True:
        sleep(CHECK_SECONDS)
        now = clock()
        if now - last_check > 3 * CHECK_SECONDS:
            state.last_heartbeat = now
        last_check = now
        if now - state.last_heartbeat > idle:
            print("No CAM2 tab open for a while; stopping.")
            shutdown()
            return


def running_instance() -> str | None:
    """URL of a CAM2 server already running on this computer, if any."""
    try:
        with open(_server_file(), encoding="utf-8") as fh:
            port = int(json.load(fh)["port"])
        url = f"http://127.0.0.1:{port}/"
        with urllib.request.urlopen(url + "api/ping", timeout=1.5) as resp:
            if json.load(resp).get("app") == "cam2":
                return url
    except (OSError, ValueError, KeyError):
        pass
    return None


def free_port(start: int) -> int:
    for port in range(start, start + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port for CAM2.")


def _log_to_file_if_windowless() -> None:
    """pythonw has no console: send output to the app-data log instead."""
    if sys.stdout is None or sys.stderr is None:
        logs = os.path.join(storage.app_data_dir(), "logs")
        os.makedirs(logs, exist_ok=True)
        log = open(os.path.join(logs, "cam2.log"), "a", encoding="utf-8", buffering=1)
        sys.stdout = sys.stderr = log


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Start CAM2 Exam Grading")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--idle", type=int, default=IDLE_SECONDS,
                        help="seconds without an open CAM2 tab before stopping (0 = never)")
    parser.add_argument("--data-dir", help="developers: keep app data and the default "
                        "Documents folder here, away from the real ones")
    parser.add_argument("--host", help="handoff file from the app that opened CAM2 (CAM)")
    args = parser.parse_args(argv)
    if args.data_dir:
        data_dir = os.path.abspath(args.data_dir)
        os.environ["CAM2_APP_DATA"] = data_dir
        os.environ["CAM2_DOCUMENTS_OVERRIDE"] = os.path.join(data_dir, "Documents")
    _log_to_file_if_windowless()
    handoff = None
    if args.host:
        try:
            handoff = host.load(args.host)
        except UserError as err:
            print(f"CAM2: cannot use the handoff file {args.host!r} ({err.code})")
            return 2

    existing = running_instance()
    if existing:
        if handoff:
            request = urllib.request.Request(
                existing + "api/host/handoff", method="POST",
                data=json.dumps(dict(handoff, format=host.FORMAT, version=host.VERSION)).encode("utf-8"),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=10):
                pass
        if not args.no_browser:
            webbrowser.open(existing)
        print(f"CAM2 is already running at {existing}")
        return 0

    state = AppState()
    state.host = handoff
    holder = {}

    def shutdown():
        state.close_session()
        threading.Thread(target=holder["server"].shutdown, daemon=True).start()

    app = create_app(state, shutdown=shutdown)
    port = free_port(args.port)
    server = make_server("127.0.0.1", port, app, threaded=True)
    holder["server"] = server
    url = f"http://127.0.0.1:{port}/"
    with open(_server_file(), "w", encoding="utf-8") as fh:
        json.dump({"port": port, "pid": os.getpid()}, fh)

    if args.idle > 0:
        threading.Thread(target=watch_idle, args=(state, args.idle, shutdown), daemon=True).start()

    if not args.no_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    print(f"CAM2 is running at {url}  (close this window or click Quit to stop)")
    try:
        server.serve_forever()
    finally:
        state.close_session()
        try:
            with open(_server_file(), encoding="utf-8") as fh:
                if json.load(fh).get("pid") == os.getpid():
                    os.remove(_server_file())
        except (OSError, ValueError):
            pass
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == [pickers.PICK_FLAG]:      # packaged app: a Windows file dialog
        raise SystemExit(pickers._main(sys.argv[2:]))
    raise SystemExit(main())
