"""Build the Windows download: dist/CAM2-exam-grading-Windows-v<version>.zip

    python tools/build_windows.py

Run it with Python 3.14 on Windows. It makes its own clean environment in
build/venv with the exact versions in requirements-build.txt, because anything
extra installed in a developer's environment could end up in the package. It
then runs PyInstaller (tools/cam2.spec), adds READ ME FIRST and the quick guide,
starts the packaged app once to check that it works, and zips the folder.
"""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
DIST = ROOT / "dist"
VENV_PYTHON = BUILD / "venv" / "Scripts" / "python.exe"
BUNDLE = DIST / "CAM2 Exam Grading"
EXE = BUNDLE / "Start CAM2 Exam Grading.exe"

READ_ME = """\
CAM2 Exam Grading - READ ME FIRST
=================================

1. Unzip the whole download first (right-click the zip > Extract All).
   Running it from inside the zip does not work.
2. Open the unzipped folder and double-click "Start CAM2 Exam Grading".
3. The first time, Windows may say "Windows protected your PC". CAM2 is free
   and not signed with a paid certificate, so Windows does not recognise it.
   Click "More info", then "Run anyway". Windows may also ask this again after
   you move the folder or download a new version.
4. CAM2 opens in your web browser. Nothing is installed and nothing leaves this
   computer: CAM2 only talks to your own browser.

Some school computers have no "More info" or "Run anyway" option. If so, or if
CAM2 won't start, unblock it:
right-click "Start CAM2 Exam Grading" and choose Properties. On the General tab,
tick "Unblock", then click OK. For your next download, do this to the zip before
you unzip it. If there is no "Unblock" tick box, Windows hasn't marked that file.

To stop CAM2, click "Quit CAM2" on the start screen. It also stops by itself
10 minutes after the last CAM2 tab is closed. Your work is saved as you go.

Keep the "_internal" folder next to "Start CAM2 Exam Grading". You can move the
whole folder anywhere. For a new version, unzip it and delete the old folder:
your sessions and recent list are kept, because they are stored elsewhere.
Sessions from an older version open in this one, but once saved here, the older
version can no longer open them.

If something goes wrong, the log is at:
    %LOCALAPPDATA%\\CAM2 Exam Grading\\logs\\cam2.log

See "CAM2 Quick Guide.pdf" for a one-page guide.

CAM2 is free software. This download includes PyMuPDF, so as a whole it is
licensed under the GNU AGPL version 3. CAM2's own code is under the MIT License.
The licences are in the "Licences" folder, and the source code is at:
    https://github.com/iamkifojp/cam2-exam-grading


CAM2 Exam Grading - 最初にお読みください
========================================

1. はじめにダウンロードしたファイルをすべて展開してください（zipを右クリック＞
   「すべて展開」）。zipの中から直接起動することはできません。
2. 展開したフォルダーを開き、「Start CAM2 Exam Grading」をダブルクリックします。
3. 初回は「WindowsによってPCが保護されました」と表示されることがあります。CAM2は
   無料のソフトで、有料の証明書で署名していないため、Windowsが認識できません。
   「詳細情報」をクリックし、「実行」をクリックしてください。フォルダーを移動した
   ときや新しいバージョンをダウンロードしたときにも、再度表示されることがあります。
4. CAM2はWebブラウザーで開きます。インストールは不要で、データがこのコンピューター
   の外に出ることはありません。CAM2はお使いのブラウザーとだけ通信します。

学校のコンピューターなどでは、「詳細情報」や「実行」が表示されないことがあります。
その場合やCAM2が起動しない場合は、ブロックを解除してください。
「Start CAM2 Exam Grading」を右クリックして「プロパティ」を選び、「全般」タブの
「許可する」にチェックを入れて「OK」をクリックします。次回
ダウンロードしたときは、展開する前にzipに対して同じ操作をしてください。チェック欄が
ない場合、そのファイルはブロックされていません。

CAM2を終了するには、スタート画面の「CAM2を終了」をクリックします。CAM2のタブを
すべて閉じてから10分後にも自動で終了します。作業内容はその都度保存されます。

「_internal」フォルダーは「Start CAM2 Exam Grading」と同じ場所に置いたままにして
ください。フォルダーごとであれば、どこへでも移動できます。新しいバージョンにする
ときは、展開してから古いフォルダーを削除してください。採点データと最近の一覧は別の
場所に保存されているため、そのまま残ります。以前のバージョンの採点データもこの
バージョンで開けますが、ここで保存すると以前のバージョンでは開けなくなります。

問題が起きたときのログの場所：
    %LOCALAPPDATA%\\CAM2 Exam Grading\\logs\\cam2.log

1ページの案内は「CAM2 Quick Guide.pdf」をご覧ください。

CAM2は無料のソフトウェアです。このダウンロードにはPyMuPDFが含まれているため、全体と
してGNU AGPLバージョン3のもとで提供しています。CAM2自体のコードはMITライセンスです。
ライセンスは「Licences」フォルダーにあります。ソースコードは次の場所で公開しています：
    https://github.com/iamkifojp/cam2-exam-grading
"""


def run(*command) -> None:
    print(">", *command, flush=True)
    subprocess.run([str(part) for part in command], check=True, cwd=ROOT)


def app_version() -> str:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    return re.search(r'^VERSION = "([^"]+)"', source, re.MULTILINE).group(1)


def make_environment(python: Path = VENV_PYTHON) -> None:
    if not python.exists():
        venv.create(BUILD / "venv", with_pip=True)
    run(python, "-m", "pip", "install", "--quiet", "-r", ROOT / "requirements-build.txt")


def add_licences(bundle: Path) -> None:
    shutil.copytree(ROOT / "licences", bundle / "Licences")
    shutil.copy(ROOT / "LICENSE", bundle / "Licences" / "CAM2-MIT.txt")


def add_documents() -> None:
    # Notepad needs the byte-order mark to read the Japanese half correctly.
    (BUNDLE / "READ ME FIRST.txt").write_text(READ_ME, encoding="utf-8-sig", newline="\r\n")
    run(VENV_PYTHON, ROOT / "tools" / "build_quick_guide.py", BUNDLE / "CAM2 Quick Guide.pdf")
    add_licences(BUNDLE)


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.read()


def check_packaged_app(exe: Path = EXE) -> None:
    """Start the real program and fetch what a browser needs from the bundle."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}/"
    with tempfile.TemporaryDirectory(prefix="cam2-build-") as data_dir:
        process = subprocess.Popen([str(exe), "--no-browser", "--idle", "0",
                                    "--port", str(port), "--data-dir", data_dir])
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    ping = json.loads(_get(url + "api/ping"))
                    break
                except OSError:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise SystemExit("The packaged app did not start.") from None
                    time.sleep(0.5)
            assert ping["app"] == "cam2", ping
            assert b"<html" in _get(url).lower()
            assert _get(url + "static/js/main.js")
            assert _get(url + "static/app.css")
            assert json.loads(_get(url + "api/i18n"))["strings"]
            request = urllib.request.Request(url + "api/quit", method="POST")
            urllib.request.urlopen(request, timeout=5).close()
            process.wait(timeout=30)
            assert not (Path(data_dir) / "server.json").exists()
        finally:
            process.kill()
            process.wait()
    print("The packaged app started and served its pages.")


def main() -> int:
    make_environment()
    shutil.rmtree(BUNDLE, ignore_errors=True)
    run(VENV_PYTHON, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD / "pyinstaller", ROOT / "tools" / "cam2.spec")
    add_documents()
    check_packaged_app()
    archive = DIST / f"CAM2-exam-grading-Windows-v{app_version()}"
    shutil.make_archive(str(archive), "zip", root_dir=DIST, base_dir=BUNDLE.name)
    size = archive.with_suffix(archive.suffix + ".zip").stat().st_size / 1024 / 1024
    print(f"Built {archive.name}.zip ({size:.0f} MB) in {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
