"""Run CAM and its grading helpers in a process group owned by the Mac app."""

from contextlib import redirect_stderr, redirect_stdout
import fcntl
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import traceback
from urllib.request import ProxyHandler, build_opener
import webbrowser


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def healthy(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(url + "_stcore/health", timeout=0.5) as response:
            return response.read() == b"ok"
    except OSError:
        return False


def stop_group(process: subprocess.Popen) -> None:
    # SIGINT lets CAM2 release its active exam lock before it exits.
    try:
        os.killpg(process.pid, signal.SIGINT)
        # The workspace and CAM2 may still be exiting after Streamlit has stopped.
        for _ in range(20):
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            process.poll()
            time.sleep(0.1)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def serve(state: Path, cache: Path, log) -> int:
    parent = os.getppid()
    stopping = False
    reopen = True

    def handle_signal(signum, _frame):
        nonlocal stopping, reopen
        if signum == signal.SIGUSR1:
            reopen = True
        else:
            stopping = True

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGUSR1):
        signal.signal(signum, handle_signal)

    port, workspace_port = free_port(), free_port()
    while workspace_port == port:
        workspace_port = free_port()
    url = f"http://127.0.0.1:{port}/"
    env = dict(os.environ, CAM_APP_STATE=str(state), CAM_APP_CACHE=str(cache),
               CAM2_APP_DATA=str(state / "exam_grading"), CAM_WORKSPACE_PORT=str(workspace_port),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false",
               MPLCONFIGDIR=str(cache / "matplotlib"))
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "streamlit", "run", "app.py",
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.headless=true", "--server.fileWatcherType=none"],
        env=env, start_new_session=True, stdin=subprocess.DEVNULL, stdout=log,
        stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.monotonic() + 45
        ready = False
        while not stopping and os.getppid() == parent:
            if process.poll() is not None:
                print(f"Streamlit stopped with status {process.returncode}.")
                return 1
            if not ready:
                ready = healthy(url)
                if not ready and time.monotonic() >= deadline:
                    print("CAM did not become ready within 45 seconds.")
                    return 1
            if ready and reopen:
                reopen = False
                print(f"CAM is ready at {url}", flush=True)
                webbrowser.open(url)
            time.sleep(0.25)
        return 0
    finally:
        stop_group(process)


def main() -> int:
    os.umask(0o077)
    library = Path.home() / "Library"
    state = library / "Application Support" / "CAM"
    cache = library / "Caches" / "CAM"
    (state / "cam_grading_workspace").mkdir(parents=True, exist_ok=True)
    (cache / "cam_grading_workspace").mkdir(parents=True, exist_ok=True)

    with (state / "launch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        with (state / "cam.log").open("w", encoding="utf-8", buffering=1) as log:
            with redirect_stdout(log), redirect_stderr(log):
                try:
                    return serve(state, cache, log)
                except Exception:
                    traceback.print_exc()
                    return 1


if __name__ == "__main__":
    raise SystemExit(main())
