"""Build the Mac download: dist/CAM2-exam-grading-Mac-AppleSilicon-v<version>.zip

    python tools/build_mac.py

Run it with Python 3.14 on an Apple Silicon Mac, as PyInstaller builds for the
Mac it runs on. Like build_windows.py, it makes its own clean environment in
build/venv and runs PyInstaller (tools/cam2.spec). It then adds READ ME FIRST
and the quick guide, zips the folder, and checks the app from a copy unzipped
again, because a careless zip breaks a Mac app's links and signature.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from build_windows import (BUILD, DIST, ROOT, add_licences, app_version, check_packaged_app,
                           make_environment, run)

VENV_PYTHON = BUILD / "venv" / "bin" / "python"
BUNDLE = DIST / "CAM2 Exam Grading"
APP_NAME = "Start CAM2 Exam Grading.app"
EXE_IN_BUNDLE = Path(APP_NAME) / "Contents" / "MacOS" / "Start CAM2 Exam Grading"

READ_ME = """\
CAM2 Exam Grading - READ ME FIRST
=================================

This download is for Macs with an Apple chip (M1 or later).

1. Double-click the zip to unzip it.
2. Open the unzipped folder and double-click "Start CAM2 Exam Grading".
3. The first time, your Mac says it could not verify that CAM2 is free of
   malware. It says this because CAM2 is free and not signed with a paid Apple
   certificate, so Apple has not checked it. Click "Done", not "Move to Trash".
   (If you did click "Move to Trash", just unzip the download again.) Then:
     a. Open System Settings > Privacy & Security.
     b. Scroll down to Security and click "Open Anyway" beside CAM2.
     c. In the message that appears, click "Open Anyway".
     d. Enter your password and click "OK".
   You only do this once. Moving the folder or downloading a new version may
   bring it back. The quick guide has pictures of these steps.
   If nothing happens after your password, or an error appears with only an "OK"
   button, restart your Mac and open CAM2 again. Your approval is kept.
4. If your Mac asks whether CAM2 may use a folder such as Documents, click
   "Allow". CAM2 needs this to read your scans and save your work there.
5. CAM2 opens in your web browser. Nothing is installed and nothing leaves this
   computer: CAM2 only talks to your own browser.

To stop CAM2, click "Quit CAM2" on the start screen. It also stops by itself
10 minutes after the last CAM2 tab is closed. Your work is saved as you go. If
you close the tab by accident, double-click "Start CAM2 Exam Grading" again.

You can move the whole folder anywhere. For a new version, unzip it and delete
the old folder: your sessions and recent list are kept, because they are stored
elsewhere. Sessions from an older version open in this one, but once saved here,
the older version can no longer open them.

If something goes wrong, the log is at:
    ~/Library/Application Support/CAM2 Exam Grading/logs/cam2.log

See "CAM2 Quick Guide.pdf" for a one-page guide.

CAM2 is free software. This download includes PyMuPDF, so as a whole it is
licensed under the GNU AGPL version 3. CAM2's own code is under the MIT License.
The licences are in the "Licences" folder, and the source code is at:
    https://github.com/iamkifojp/cam2-exam-grading


CAM2 Exam Grading - 最初にお読みください
========================================

このダウンロードは、Appleチップ（M1以降）を搭載したMac用です。

1. zipをダブルクリックして展開します。
2. 展開したフォルダーを開き、「Start CAM2 Exam Grading」をダブルクリックします。
3. 初回は、CAM2にマルウェアが含まれていないことを検証できなかった、という
   メッセージが表示されます。CAM2は無料のソフトで、Appleの有料の証明書で署名して
   おらず、Appleの確認を受けていないためです。「ゴミ箱に入れる」ではなく「完了」を
   クリックしてください（「ゴミ箱に入れる」をクリックした場合は、ダウンロードした
   zipをもう一度展開してください）。続いて、次の操作をします。
     a. 「システム設定」＞「プライバシーとセキュリティ」を開きます。
     b. 「セキュリティ」まで下へスクロールし、CAM2の横の「このまま開く」を
        クリックします。
     c. 表示されたメッセージで「このまま開く」をクリックします。
     d. パスワードを入力し、「OK」をクリックします。
   これは最初の1回だけです。フォルダーを移動したときや新しいバージョンをダウン
   ロードしたときには、再度必要になることがあります。手順の画像はクイックガイドに
   あります。
   パスワードを入力しても何も起こらないときや、「OK」ボタンだけのエラーが表示される
   ときは、Macを再起動してからCAM2をもう一度開いてください。許可は保持されています。
4. 書類フォルダーなどへのアクセスを求められたら、「許可」をクリックしてください。
   スキャンを読み込み、作業内容をそこへ保存するために必要です。
5. CAM2はWebブラウザーで開きます。インストールは不要で、データがこのコンピューター
   の外に出ることはありません。CAM2はお使いのブラウザーとだけ通信します。

CAM2を終了するには、スタート画面の「CAM2を終了」をクリックします。CAM2のタブを
すべて閉じてから10分後にも自動で終了します。作業内容はその都度保存されます。
誤ってタブを閉じたときは、「Start CAM2 Exam Grading」をもう一度ダブルクリックして
ください。

フォルダーごとであれば、どこへでも移動できます。新しいバージョンにするときは、
展開してから古いフォルダーを削除してください。採点データと最近の一覧は別の場所に
保存されているため、そのまま残ります。以前のバージョンの採点データもこのバージョン
で開けますが、ここで保存すると以前のバージョンでは開けなくなります。

問題が起きたときのログの場所：
    ~/Library/Application Support/CAM2 Exam Grading/logs/cam2.log

1ページの案内は「CAM2 Quick Guide.pdf」をご覧ください。

CAM2は無料のソフトウェアです。このダウンロードにはPyMuPDFが含まれているため、全体と
してGNU AGPLバージョン3のもとで提供しています。CAM2自体のコードはMITライセンスです。
ライセンスは「Licences」フォルダーにあります。ソースコードは次の場所で公開しています：
    https://github.com/iamkifojp/cam2-exam-grading
"""


def make_bundle() -> None:
    """Put the .app, which PyInstaller leaves in dist/, into the folder teachers see."""
    shutil.rmtree(BUNDLE, ignore_errors=True)
    run(VENV_PYTHON, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--distpath", DIST, "--workpath", BUILD / "pyinstaller", ROOT / "tools" / "cam2.spec")
    shutil.rmtree(BUNDLE)       # PyInstaller's working copy; the .app has its own
    BUNDLE.mkdir()
    shutil.move(DIST / APP_NAME, BUNDLE / APP_NAME)


def add_documents() -> None:
    # Quick Look only reads the Japanese half correctly with the byte-order mark.
    (BUNDLE / "READ ME FIRST.txt").write_text(READ_ME, encoding="utf-8-sig", newline="\n")
    run(VENV_PYTHON, ROOT / "tools" / "build_quick_guide.py", BUNDLE / "CAM2 Quick Guide.pdf", "mac")
    add_licences(BUNDLE)


def make_zip(archive: Path) -> None:
    # ditto keeps the links inside the .app, which shutil.make_archive does not.
    run("ditto", "-c", "-k", "--norsrc", "--noextattr", "--noacl", "--keepParent", BUNDLE, archive)


def check_zip(archive: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="cam2-build-") as unzipped:
        subprocess.run(["ditto", "-x", "-k", str(archive), unzipped], check=True)
        bundle = Path(unzipped) / BUNDLE.name
        run("codesign", "--verify", "--deep", "--strict", bundle / APP_NAME)
        check_packaged_app(bundle / EXE_IN_BUNDLE)


def main() -> int:
    assert platform.machine() == "arm64", "this build is for Apple Silicon Macs"
    make_environment(VENV_PYTHON)
    make_bundle()
    add_documents()
    archive = DIST / f"CAM2-exam-grading-Mac-AppleSilicon-v{app_version()}.zip"
    make_zip(archive)
    check_zip(archive)
    size = archive.stat().st_size / 1024 / 1024
    print(f"Built {archive.name} ({size:.0f} MB) in {DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
