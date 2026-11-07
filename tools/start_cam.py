"""Start a packaged CAM on loopback and supervise its grading helpers."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
import argparse
import errno
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.request import ProxyHandler, build_opener
import webbrowser

WINDOWS = sys.platform == "win32"
WINDOWS_PORT = 8600


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


@contextmanager
def claim_launch(path: Path):
    with path.open("a+b") as lock:
        try:
            if WINDOWS:
                import msvcrt

                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in (errno.EACCES, errno.EAGAIN):
                raise
            yield False
        else:
            yield True


def stop_group(process: subprocess.Popen) -> None:
    if WINDOWS:
        if process.poll() is None:
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
                process.wait(timeout=8)
            except (OSError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, check=False)
                    if process.poll() is None:
                        process.kill()
        process.wait()
        return

    # SIGINT lets CAM2 release its active exam lock before it exits.
    try:
        os.killpg(process.pid, signal.SIGINT)
        for _ in range(20):
            exited = process.poll() is not None
            try:
                os.killpg(process.pid, 0)
            except ProcessLookupError:
                break
            except PermissionError:
                # The group ID can outlast the last process we can signal.
                if not exited:
                    raise
                break
            time.sleep(0.1)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def copy_console_output(pipe, log, console) -> None:
    with pipe:
        for line in pipe:
            log.write(line)
            console.write(line)
            console.flush()


def serve(state: Path, log, quit_file: Path, console=None) -> int:
    parent = os.getppid()
    stopping = False
    reopen = True

    def handle_signal(signum, _frame):
        nonlocal stopping, reopen
        if not WINDOWS and signum == signal.SIGUSR1:
            reopen = True
        else:
            stopping = True

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGBREAK if WINDOWS else signal.SIGUSR1):
        signal.signal(signum, handle_signal)

    port = WINDOWS_PORT if WINDOWS else free_port()
    workspace_port = free_port()
    while workspace_port == port:
        workspace_port = free_port()
    url = f"http://127.0.0.1:{port}/"
    if WINDOWS and healthy(url):
        print(f"Another CAM is already using port {port}. Close it before starting this copy.")
        return 1

    env = dict(os.environ, CAM2_APP_DATA=str(state / "exam_grading"),
               CAM_WORKSPACE_PORT=str(workspace_port), CAM_QUIT_FILE=str(quit_file),
               STREAMLIT_BROWSER_GATHER_USAGE_STATS="false", PYTHONIOENCODING="utf-8")
    if not WINDOWS:
        cache = Path.home() / "Library" / "Caches" / "CAM"
        (cache / "cam_grading_workspace").mkdir(parents=True, exist_ok=True)
        env.update(CAM_APP_STATE=str(state), CAM_APP_CACHE=str(cache),
                   MPLCONFIGDIR=str(cache / "matplotlib"))

    process = subprocess.Popen(
        [sys.executable, "-B", "-u", "-m", "streamlit", "run", "app.py",
         "--server.address=127.0.0.1", f"--server.port={port}",
         "--server.headless=true", "--server.fileWatcherType=none"],
        env=env, start_new_session=not WINDOWS,
        creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if WINDOWS else 0,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE if console else log,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
    )
    reader = None
    if console:
        reader = threading.Thread(target=copy_console_output, args=(process.stdout, log, console),
                                  daemon=True)
        reader.start()
    try:
        deadline = time.monotonic() + (300 if WINDOWS else 45)
        ready = False
        while not stopping and not quit_file.exists() and (WINDOWS or os.getppid() == parent):
            if process.poll() is not None:
                print(f"Streamlit stopped with status {process.returncode}.")
                return 1
            if not ready:
                ready = healthy(url)
                if not ready and time.monotonic() >= deadline:
                    print("CAM did not become ready.")
                    return 1
            if ready and reopen:
                reopen = False
                print(f"CAM is ready at {url}", flush=True)
                webbrowser.open(url)
            time.sleep(0.25)
        return 0
    finally:
        stop_group(process)
        if reader:
            reader.join(timeout=2)


def reopen_windows() -> int:
    url = f"http://127.0.0.1:{WINDOWS_PORT}/"
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        if healthy(url):
            webbrowser.open(url)
            return 0
        time.sleep(0.5)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--console", action="store_true", help="Show server output as it arrives")
    args = parser.parse_args()
    if WINDOWS:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        state = local / "CAM"
        logs = Path.cwd() / "logs"
    else:
        os.umask(0o077)
        state = Path.home() / "Library" / "Application Support" / "CAM"
        (state / "cam_grading_workspace").mkdir(parents=True, exist_ok=True)
        logs = state
    state.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)

    log_path = logs / "cam.log"
    console = sys.stdout if args.console else None
    with claim_launch(state / "launch.lock") as claimed:
        if not claimed:
            result = reopen_windows() if WINDOWS else 0
        else:
            with tempfile.TemporaryDirectory(prefix="cam-run-") as run_dir, \
                    log_path.open("w", encoding="utf-8", buffering=1) as log, \
                    redirect_stdout(log), redirect_stderr(log):
                try:
                    result = serve(state, log, Path(run_dir) / "quit", console)
                except Exception:
                    traceback.print_exc()
                    result = 1
    if WINDOWS and result:
        detail = f"CAM could not start or stopped unexpectedly. See the log at:\n{log_path}"
        if args.console:
            print(detail, file=sys.stderr)
        else:
            from ctypes import windll

            windll.user32.MessageBoxW(None, detail, "CAM", 0x10)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
