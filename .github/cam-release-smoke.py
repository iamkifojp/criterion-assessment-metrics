import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

source, extraction = map(lambda s: Path(s).resolve(), sys.argv[1:])
windows = sys.platform == "win32"
app = extraction / "CAM.app"
bundle = extraction / ("CAM-portable" if windows else "CAM.app/Contents/Resources/CAM")
python = bundle / "runtime/python.exe" if windows else app / "Contents/MacOS/python3.14"

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

with tempfile.TemporaryDirectory(prefix="cam-release-smoke-", ignore_cleanup_errors=True) as tmp:
    sb = Path(tmp)
    data = sb / "data"
    home = sb / "home"
    local = home / "AppData/Local"
    state = (local / "CAM") if windows else (home / "Library/Application Support/CAM")
    log = (bundle / "logs/cam.log") if windows else (state / "cam.log")
    docs = sb / "Documents"
    master = sb / "scans"
    for path in (data, home, local, docs, state / "cam_grading_workspace", sb / "cache", sb / "tmp"):
        path.mkdir(parents=True, exist_ok=True)
    db = data / "acm_database.json"
    env = {k: v for k, v in os.environ.items() if not k.lower().startswith(("onedrive", "cam_","cam2_"))}
    env.update(HOME=str(home), USERPROFILE=str(home), APPDATA=str(local), LOCALAPPDATA=str(local),
               CAM_DB_PATH=str(db), CAM_DOCUMENTS_OVERRIDE=str(docs), CAM2_DOCUMENTS_OVERRIDE=str(docs),
               CAM_APP_STATE=str(state), CAM_APP_CACHE=str(sb / "cache"), PYTHONUTF8="1",
               PYTHONDONTWRITEBYTECODE="1", TMP=str(sb / "tmp"), TEMP=str(sb / "tmp"),
               TMPDIR=str(sb / "tmp"), CAM_SANDBOX_URL_LOG=str(sb / "opened-urls.txt"))
    if not windows:
        env["PYTHONHOME"] = str(app / "Contents/Resources/python")
    opener = source / "tools/browser_check/log_url.py"
    args = [str(python), str(opener)]
    if windows:
        args = [arg.replace("\\", "/") for arg in args]
    env["BROWSER"] = shlex.join(args) + " %s"
    (state / "local_device_prefs.json").write_text(json.dumps({
        "db_custom_path": str(data), "setup_done": True
    }), encoding="utf-8")
    fixture = source / "tools/browser_check/make_fixtures.py"
    subprocess.run([python, "-B", fixture, "draft", master], env=env, check=True)
    subprocess.run([python, "-B", fixture, "sessions", bundle / "exam_grading",
                    data / "Class 1/exams"], env=env, check=True)
    sample = bundle / "acm_database.json"
    assert sample.read_bytes() == (source / "acm_database.json").read_bytes()
    payload = read(sample)
    local_class = next(c for c in payload["session"]["classes"] if c["name"] == "Class 1")
    local_class["master_dir"] = str(master)
    exam_title = "Quiz 1 marks"
    exam_dir = data / "Class 1/exams" / exam_title
    config_path = exam_dir / "cam2_session.json"
    config = read(config_path)
    config.update(sliced=True, resume={"step": 5, "current": 5})
    config_path.write_text(json.dumps(config), encoding="utf-8")
    original_feedback = read(exam_dir / "grades.json")["overall"]["s001"]["comment"]
    exam_student_id = "100001"
    exam_student = next(s for s in payload["gradebook"]["students"] if s["student_id"] == exam_student_id)
    exam_student["scores"].append({
        "criterion": "A", "value": 5, "timestamp": "2026-05-10T00:00:00",
        "source": f"exam:{exam_title}", "assignment": exam_title, "comment": original_feedback,
    })
    payload["gradebook"]["assignments"].append({
        "name": exam_title, "criteria": ["A"], "source_file": "", "note": "",
        "ingested_at": "2026-05-10T00:00:00", "score_count": 1,
        "class_name": "Class 1", "term": "Term 1", "is_exam": True,
    })
    payload["gradebook"]["assignments"].append({
        "name": "Poster draft", "criteria": ["A"], "source_file": "",
        "ingested_at": "2026-05-10T00:00:00", "score_count": 0, "note": "",
        "class_name": "Class 1", "term": "Term 1",
        "folder_ref": str(master / "Poster draft"), "is_draft": True,
    })
    db.write_text(json.dumps(payload), encoding="utf-8")

    def exam_comment_matches(expected):
        student = next(s for s in read(db)["gradebook"]["students"] if s["student_id"] == exam_student_id)
        result = next((r for r in student.get("exam_results", []) if r["assignment"] == exam_title), None)
        score = next(s for s in student["scores"] if s["assignment"] == exam_title)
        return result is not None and score["value"] == 5 and score.get("comment", "") == result.get("comment", "") == expected

    command = [python, "-B", bundle / "start_cam.py"] if windows else [app / "Contents/MacOS/CAM"]
    proc = subprocess.Popen(command, cwd=bundle, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **({"creationflags": subprocess.CREATE_NO_WINDOW} if windows else {}))
    def wait_for(fn, reason, seconds=60):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            value = fn()
            if value:
                return value
            time.sleep(.15)
        raise AssertionError(reason)

    def get_cam_url():
        if log.exists():
            match = re.search(r"CAM is ready at (http://127\.0\.0\.1:\d+/)", log.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
        return None

    try:
        url = wait_for(get_cam_url, "CAM supervisor did not start")
        with urlopen(url + "_stcore/health", timeout=4) as response:
            assert response.read() == b"ok"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1650, "height": 1050})
            context.route("**/*", lambda r: r.continue_() if r.request.url.startswith("http://127.0.0.1:") else r.abort())
            page = context.new_page()
            api = context.request
            files = list((data / "Class 1/exams").glob("*/*.json"))
            assert len(files) == 16
            baseline = {p: hashlib.sha256(p.read_bytes()).digest() for p in files}
            page.goto(url)
            exam = page.get_by_role("button", name=exam_title, exact=True)
            expect(exam).to_be_visible(timeout=45_000)
            assert all(hashlib.sha256(p.read_bytes()).digest() == h for p, h in baseline.items())
            wait_for(lambda: exam_comment_matches(original_feedback), "CAM did not file the initial fictional exam")
            mirror = data / "Class 1/acm_term_summaries_Class_1.json"
            wait_for(lambda: mirror.is_file() and read(mirror).get("score_comments", {}).get(exam_title, {})
                     .get(exam_student_id, {}).get("A") == original_feedback,
                     "CAM did not mirror the original criterion comment")
            page.get_by_role("button", name="⚙ Settings", exact=True).click()
            expect(page.get_by_text("About CAM and its licences", exact=False)).to_be_visible()
            page.keyboard.press("Escape")
            exam.click()
            page.get_by_role("button", name="Exam setup / Grade").click()
            record = state / "exam_grading/server.json"
            wait_for(record.is_file, "Missing bundled CAM2 server record")
            cam2 = f"http://127.0.0.1:{read(record)['port']}"
            tab = context.new_page()
            tab.goto(cam2)
            assert api.get(cam2 + "/api/ping").json()["version"] == "0.3.2-dev-cam.1"
            session = api.get(cam2 + "/api/state").json()
            assert session["host"]["roster_count"] == 8
            if not session["session"]:
                opened = api.post(cam2 + "/api/session/open", data={"folder": str(exam_dir)})
                assert opened.ok, opened.text()
            invalid = api.post(cam2 + "/api/overall", data={"student_id": "s001", "report_total": 99})
            assert invalid.status == 400 and invalid.json()["error"] == "report_value_out_of_range"
            exam_feedback = "Fictional CAM patch exam feedback."
            edited = api.post(cam2 + "/api/overall", data={
                "student_id": "s001", "comment": exam_feedback, "report_total": 13
            })
            assert edited.ok, edited.text()
            assert api.post(cam2 + "/api/host/ready", data={"ready": True}).ok

            page.keyboard.press("Escape")
            page.get_by_role("button", name="Poster draft", exact=True).click()
            grade_button = page.get_by_role("button", name="Grade this Assignment")
            grade_button.click()
            link = page.locator('a[href^="http://127.0.0.1:"]').filter(has_text="http://127.0.0.1:")
            startup_error = page.get_by_text("Grading workspace did not start on port", exact=False)
            expect(link.or_(startup_error)).to_be_visible(timeout=40_000)
            if startup_error.is_visible():
                print(startup_error.inner_text(), flush=True)
                port = re.search(r"port (\d+)", startup_error.inner_text()).group(1)
                def late_workspace():
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/api/state", timeout=1) as response:
                            return "students" in json.load(response)
                    except OSError:
                        return False
                wait_for(late_workspace, "Workspace did not start after its first timeout", seconds=25)
                grade_button.click()
            expect(link).to_be_visible(timeout=15_000)
            workspace = context.new_page()
            workspace.goto(link.get_attribute("href"))
            origin = re.match(r"http://127\.0\.0\.1:\d+", workspace.url).group()
            def student_list():
                r = api.get(origin + "/api/state")
                if r.ok and len(students := r.json()["students"]) == 4:
                    return students
                return None
            a, b, *_ = wait_for(student_list, "Missing workspace fixture students")
            draft_feedback = "Fictional CAM v2026.11.08 draft feedback."
            assert api.post(origin + "/api/save", data={
                "key": a["key"], "comment": draft_feedback, "keywords": ["Context"]
            }).ok
            linked = api.post(origin + "/api/group/link", data={"a_key": a["key"], "b_key": b["key"]})
            assert linked.ok, linked.text()
            exported = api.get(origin + "/api/export")
            assert exported.ok and exported.json()["saved"], exported.text()
            wait_for(lambda: all(s in db.read_text(encoding="utf-8") for s in (
                exam_feedback, draft_feedback, linked.json()["groups"][0]["id"])),
                "CAM gradebook did not receive the exam and linked draft")
            wait_for(lambda: exam_comment_matches(exam_feedback), "CAM did not update the unedited criterion comment")
            assert api.post(cam2 + "/api/overall", data={"student_id": "s001", "comment": ""}).ok
            assert api.post(cam2 + "/api/host/ready", data={"ready": True}).ok
            wait_for(lambda: exam_comment_matches(""), "CAM restored a cleared exam comment")
            tab.reload()
            send_panel = tab.locator("section").filter(has=tab.get_by_role("heading", name="Send the results to CAM"))
            expect(send_panel.get_by_text("Check Grades and Analysis in CAM", exact=False)).to_be_visible()
            send_panel.get_by_role("button", name="Save & close session", exact=True).click()
            expect(tab.get_by_role("status").filter(has_text="Session saved")).to_contain_text(
                "Return to Grades and Analysis in CAM")
            expect(tab.get_by_role("button", name="Quit CAM2", exact=True)).to_be_visible()
            assert api.get(cam2 + "/api/state").json()["session"] is None
            assert not (exam_dir / "cam2.lock").exists()
            expect(page.get_by_test_id("stException")).to_have_count(0)
            page.keyboard.press("Escape")
            page.get_by_role("button", name="Quit CAM", exact=True).click()
            wait_for(lambda: proc.poll() is not None, "CAM launcher did not quit")
            assert proc.returncode == 0
            wait_for(lambda: not record.exists(), "CAM2 left a server record")
            assert not (data / "Class 1/exams/Quiz 1 marks/cam2.lock").exists()
            browser.close()
        print("Packaged CAM passed both grading handoffs, linked draft export, comment re-send and deletion, save-and-close guidance, and clean shutdown.")
    except Exception:
        if log.exists():
            print(log.read_text(encoding="utf-8")[-8000:])
        workspace_log = state / "cam_grading_workspace/workspace_startup.log"
        if workspace_log.exists():
            print(workspace_log.read_text(encoding="utf-8")[-8000:])
        raise
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.wait(timeout=15)
