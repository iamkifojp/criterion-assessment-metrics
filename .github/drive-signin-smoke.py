"""Smoke test an extracted CAM package with fictional data and loopback OAuth."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

source, extraction = (Path(p).resolve() for p in sys.argv[1:3])
windows = sys.platform == "win32"
app = extraction / "CAM.app"
bundle = extraction / ("CAM-portable" if windows else "CAM.app/Contents/Resources/CAM")
python = bundle / "runtime/python.exe" if windows else app / "Contents/MacOS/python3.14"

def wait_for(fn, reason, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if result := fn():
            return result
        time.sleep(.15)
    raise AssertionError(reason)

class OAuth(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlsplit(self.path).query)
        callback, = params["redirect_uri"]
        assert urlsplit(callback).hostname in {"localhost", "127.0.0.1"}
        self.send_response(302)
        self.send_header("Location", callback + "?" + urlencode(
            {"code": params["client_id"][0], "state": params["state"][0]}))
        self.end_headers()

    def do_POST(self):
        params = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        body = json.dumps({"access_token": params["code"][0], "refresh_token": "fictional",
                           "token_type": "Bearer", "expires_in": 3600}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

with tempfile.TemporaryDirectory(prefix="cam-signin-smoke-", ignore_cleanup_errors=True) as temp, \
        ThreadingHTTPServer(("127.0.0.1", 0), OAuth) as oauth:
    threading.Thread(target=oauth.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{oauth.server_port}"
    sb = Path(temp)
    data = sb / "Shared gradebook [school]"
    home, docs, tmp = (sb / p for p in ("home", "Documents", "tmp"))
    local = home / "AppData/Local"
    state = local / "CAM" if windows else home / "Library/Application Support/CAM"
    workspace = bundle / "cam_grading_workspace" if windows else state / "cam_grading_workspace"
    log = bundle / "logs/cam.log" if windows else state / "cam.log"
    for path in (data, home, docs, tmp, local, workspace, state):
        path.mkdir(parents=True, exist_ok=True)
    db = data / "acm_database.json"
    sample = bundle / db.name
    assert sample.read_bytes() == (source / db.name).read_bytes()
    shutil.copy2(sample, db)
    token = workspace / "token.json"
    assert not token.exists()
    assert not (workspace / "gcg_settings.json").exists()
    assert not (bundle / "cam_grading_workspace/gcg_settings.json").exists()
    assert not (bundle / "local_device_prefs.json").exists()
    (state / "local_device_prefs.json").write_text(
        json.dumps({"db_custom_path": str(data), "setup_done": True}), encoding="utf-8")
    opened = sb / "opened-urls.txt"
    logger = source / "tools/browser_check/log_url.py"
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith(
        ("onedrive", "cam_", "cam2_", "python", "browser"))}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(local), LOCALAPPDATA=str(local),
               CAM_DB_PATH=str(db), CAM_DOCUMENTS_OVERRIDE=str(docs), CAM2_DOCUMENTS_OVERRIDE=str(docs),
               OAUTHLIB_INSECURE_TRANSPORT="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1",
               TMP=str(tmp), TEMP=str(tmp), TMPDIR=str(tmp), CAM_SANDBOX_URL_LOG=str(opened),
               BROWSER=shlex.join([python.as_posix(), logger.as_posix()]) + " %s")
    if not windows:
        env["PYTHONHOME"] = str(app / "Contents/Resources/python")
    cmd = [python, "-B", bundle / "start_cam.py", "--console"] if windows else [app / "Contents/MacOS/CAM"]

    def client_json(path, label):
        path.write_text(json.dumps({"installed": {
            "client_id": label, "client_secret": "fictional", "auth_uri": origin + "/authorize",
            "token_uri": origin + "/token", "redirect_uris": ["http://localhost"]}}), encoding="utf-8")

    def read_url(pattern):
        if opened.exists():
            for line in reversed(opened.read_text(encoding="utf-8").splitlines()):
                if match := re.search(pattern, line):
                    return match[0]

    shared_client = data / "client_secret_fixture.json"
    client_json(shared_client, "gradebook-client")
    proc = subprocess.Popen(cmd, cwd=bundle, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        url = wait_for(lambda: read_url(r"http://127\.0\.0\.1:\d+/$"), "CAM failed to start")
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=os.environ.get("CAM_SMOKE_CHROME"))
            page = browser.new_page(viewport={"width": 1650, "height": 1050})
            page.route("**/*", lambda r: r.continue_() if r.request.url.startswith("http://127.0.0.1:") else r.abort())
            page.goto(url)
            edit = page.get_by_role("button", name="Add / Edit class")
            expect(edit).to_be_visible(timeout=45_000)
            edit.click()
            page.get_by_role("button", name="Add a class", exact=False).click()
            connect = page.get_by_role("button", name="Connect Google Drive")

            def sign_in(expected):
                opened.write_text("", encoding="utf-8")
                connect.click()
                signin = wait_for(lambda: read_url(r"http://127\.0\.0\.1:\d+/signin\?handoff=\S+"),
                                  "Connect did not open the workspace sign-in link")
                assert str(data) not in signin
                with ThreadPoolExecutor() as pool:
                    sign_in_page = pool.submit(lambda: urlopen(signin, timeout=45).read())
                    auth = wait_for(lambda: read_url(re.escape(origin) + r"/authorize\?\S+"),
                                    "Workspace did not start OAuth", 15)
                    assert parse_qs(urlsplit(auth).query)["client_id"] == [expected]
                    with urlopen(auth, timeout=8) as callback:
                        assert callback.status == 200
                    assert b"Google Drive connected" in sign_in_page.result()
                assert json.loads(token.read_text(encoding="utf-8"))["token"] == expected
                assert not (data / "token.json").exists()
                assert not (workspace / "gcg_settings.json").exists()

            sign_in("gradebook-client")
            print("First click found the OAuth client beside the gradebook; token is local.", flush=True)
            token.unlink()
            client_json(workspace / "credentials.json", "workspace-client")
            sign_in("workspace-client")
            print("An existing workspace client took precedence on a later click.", flush=True)
            page.get_by_role("button", name="Cancel", exact=True).click()
            expect(connect).to_have_count(0)
            page.get_by_role("button", name="Quit CAM", exact=True).press("Enter")
            wait_for(lambda: proc.poll() is not None, "CAM failed to quit")
            assert proc.returncode == 0
            browser.close()
        print("Packaged CAM first-click OAuth, credential precedence and shutdown passed.")
    except Exception:
        for path in (log, workspace / "workspace_startup.log"):
            if path.exists():
                print(path.read_text(encoding="utf-8", errors="replace")[-4000:])
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)
        if windows:
            (workspace / "credentials.json").unlink(missing_ok=True)
            token.unlink(missing_ok=True)
        oauth.shutdown()
