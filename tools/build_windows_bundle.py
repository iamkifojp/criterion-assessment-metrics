"""Build the self-contained CAM portable bundle for 64-bit Windows.

The payload is always sourced from ``git archive HEAD``.  This is deliberate:
local preferences, credentials, and real student data in the working tree can
never leak into a release.
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile


REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / "tools" / ".cache"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "dist"
DEFAULT_PYTHON_VERSION = "3.14.6"
PYTHON_URL = (
    "https://www.python.org/ftp/python/{version}/"
    "python-{version}-embeddable-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
FORBIDDEN_NAMES = {
    "credentials.json",
    "token.json",
    "local_device_prefs.json",
}
REQUIRED_BUNDLE_FILES = {
    "CAM Quick Guide.pdf",
    "READ ME FIRST.txt",
    "Start CAM (troubleshooting).bat",
    "Start CAM.vbs",
    "acm_database.json",
    "app.py",
}


def run(command: list[str | os.PathLike[str]], *, cwd: Path) -> None:
    """Run a build command, displaying it and failing immediately on error."""
    printable = subprocess.list2cmdline([os.fspath(item) for item in command])
    print(f"> {printable}")
    subprocess.run(command, cwd=cwd, check=True)


def download(url: str, destination: Path) -> Path:
    """Download *url* once, using an atomic rename for the persistent cache."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size:
        print(f"Using cached {destination.name}")
        return destination
    partial = destination.with_suffix(destination.suffix + ".part")
    partial.unlink(missing_ok=True)
    print(f"Downloading {url}")
    try:
        with urllib.request.urlopen(url) as response, partial.open("wb") as out:
            shutil.copyfileobj(response, out)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    return destination


def stage_head(destination: Path) -> None:
    """Export committed files only and remove development-only content."""
    archive = subprocess.run(
        ["git", "archive", "--format=zip", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        source.extractall(destination)

    shutil.rmtree(destination / ".claude", ignore_errors=True)
    shutil.rmtree(destination / "tools", ignore_errors=True)
    for plan in (destination / "docs").glob("*_PLAN.md"):
        plan.unlink()


def enable_site_packages(runtime: Path) -> None:
    pth_files = list(runtime.glob("python314._pth"))
    if len(pth_files) != 1:
        raise RuntimeError("Embedded Python did not contain python314._pth")
    pth = pth_files[0]
    lines = pth.read_text(encoding="utf-8").splitlines()
    changed = False
    for index, line in enumerate(lines):
        if line.strip() == "#import site":
            lines[index] = "import site"
            changed = True
    if not changed and not any(line.strip() == "import site" for line in lines):
        raise RuntimeError("Could not enable 'import site' in python314._pth")
    # The embeddable runtime ignores cwd, PYTHONPATH, and the script directory
    # while a ._pth file is present. Streamlit executes app.py rather than
    # invoking it as Python's script, so CAM's root package would otherwise be
    # invisible. The workspace also uses same-folder imports (exam_engine).
    for relative in ("..", r"..\cam_grading_workspace"):
        if relative not in lines:
            lines.insert(1, relative)
    pth.write_text("\n".join(lines) + "\n", encoding="utf-8")


def install_runtime(bundle: Path, python_version: str) -> None:
    runtime = bundle / "runtime"
    runtime.mkdir()
    archive_name = f"python-{python_version}-embeddable-amd64.zip"
    archive = download(
        PYTHON_URL.format(version=python_version), CACHE_DIR / archive_name
    )
    with zipfile.ZipFile(archive) as source:
        source.extractall(runtime)
    enable_site_packages(runtime)

    get_pip = download(GET_PIP_URL, CACHE_DIR / "get-pip.py")
    python = runtime / "python.exe"
    run([python, get_pip, "--no-warn-script-location"], cwd=bundle)
    run(
        [
            python,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-warn-script-location",
            "-r",
            bundle / "requirements.txt",
        ],
        cwd=bundle,
    )


def write_launchers(bundle: Path) -> None:
    # --server.headless true is load-bearing, not cosmetic: without it, a
    # machine that has never run Streamlit gets the interactive "Welcome to
    # Streamlit! Email:" prompt (streamlit/runtime/credentials.py), which
    # blocks forever inside the hidden console — the classic "Start CAM.vbs
    # does nothing" failure on a colleague's laptop. Headless skips the prompt
    # but also disables Streamlit's own browser auto-open, so the VBS polls
    # the health endpoint and opens the browser itself.
    vbs = '''Option Explicit
Dim shell, fso, root, logs, command, waited
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

If Not fso.FileExists(fso.BuildPath(root, "runtime\\python.exe")) Then
    MsgBox "CAM's runtime folder is missing, so CAM cannot start." _
        & vbCrLf & vbCrLf _
        & "This usually means the downloaded zip was not fully extracted." _
        & " Right-click the zip, choose Extract All, and double-click" _
        & " Start CAM.vbs inside the extracted folder.", _
        vbExclamation, "CAM could not start"
    WScript.Quit 1
End If

' A second click while CAM is already running just reopens the browser.
If Not ServerReady() Then
    logs = fso.BuildPath(root, "logs")
    If Not fso.FolderExists(logs) Then fso.CreateFolder(logs)
    shell.CurrentDirectory = root
    command = "cmd.exe /d /c """"runtime\\python.exe"" -m streamlit run app.py" _
        & " --server.port 8600 --server.headless true" _
        & " --browser.gatherUsageStats false" _
        & " >> ""logs\\cam.log"" 2>&1"""
    shell.Run command, 0, False
End If

' Auto-closing toast so the otherwise silent start is visible.
shell.Popup "CAM is starting." & vbCrLf _
    & "Your browser will open when CAM is ready - the first start can" _
    & " take a few minutes on a new laptop.", 4, "CAM", vbInformation

waited = 0
Do Until ServerReady()
    If waited >= 300 Then
        MsgBox "CAM did not start within 5 minutes." & vbCrLf & vbCrLf _
            & "Double-click ""Start CAM (troubleshooting).bat"" to see the" _
            & " error on screen, and check the logs\\cam.log file.", _
            vbExclamation, "CAM could not start"
        WScript.Quit 1
    End If
    WScript.Sleep 1000
    waited = waited + 1
Loop
shell.Run "http://localhost:8600"

Function ServerReady()
    On Error Resume Next
    Dim request
    ServerReady = False
    Set request = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    request.SetTimeouts 1000, 1000, 1000, 1000
    request.Open "GET", "http://localhost:8600/_stcore/health", False
    request.Send
    If Err.Number = 0 Then ServerReady = (request.Status = 200)
End Function
'''
    bat = r'''@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime\python.exe" (
    echo CAM's runtime folder is missing - the downloaded zip was probably not
    echo fully extracted. Right-click the zip, choose Extract All, and run this
    echo file from the extracted folder.
    pause
    exit /b 1
)
if not exist logs mkdir logs
echo CAM is starting. When the "You can now view" lines appear below, open
echo http://localhost:8600 in your browser.
echo Output is also saved in logs\cam.log.
"runtime\python.exe" -m streamlit run app.py --server.port 8600 --server.headless true --browser.gatherUsageStats false 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath 'logs\cam.log' -Append"
echo.
echo CAM stopped. Review the messages above or logs\cam.log.
pause
'''
    # Windows Script Host treats an UTF-8 BOM as an invalid first character on
    # supported school Windows builds. Its Unicode script format is UTF-16LE
    # with a BOM, which ``encoding="utf-16"`` writes portably.
    (bundle / "Start CAM.vbs").write_text(vbs, encoding="utf-16")
    (bundle / "Start CAM (troubleshooting).bat").write_text(
        bat, encoding="utf-8", newline="\r\n"
    )


def write_readme(bundle: Path) -> None:
    text = """CAM PORTABLE - READ ME FIRST
============================

1. Right-click the downloaded zip and choose Extract All.
2. Open the extracted folder and double-click Start CAM.vbs.
3. If Windows asks "Do you want to open this file?", choose Open.
4. A small "CAM is starting" message appears, then your browser opens CAM
   when it is ready. The first start can take a few minutes on a new laptop.
5. In CAM, pick a data folder such as Documents\\CAM Data.

Keep the extracted folder together; do not run CAM from inside the zip. If
CAM reports it could not start, double-click Start CAM (troubleshooting).bat
to see the error on screen, and check logs\\cam.log.

UPDATING CAM
Download and extract the new app folder, then use that folder instead of the
old one. Your gradebook remains in the separate data folder you selected, so
replacing the app folder does not replace your data. Select the same data
folder when the updated app first opens.
"""
    (bundle / "READ ME FIRST.txt").write_text(text, encoding="utf-8-sig")


def copy_quick_guide(bundle: Path, guide: Path | None) -> None:
    guide = guide or REPO_ROOT / "docs" / "CAM Quick Guide.pdf"
    if guide.is_file():
        shutil.copy2(guide, bundle / "CAM Quick Guide.pdf")
    else:
        print("Quick Guide PDF not found (Phase 3); continuing without it.")


def prune_runtime(bundle: Path) -> None:
    for directory in bundle.rglob("__pycache__"):
        if directory.is_dir():
            shutil.rmtree(directory)
    for directory in bundle.rglob(".cache"):
        if directory.is_dir():
            shutil.rmtree(directory)
    scripts = bundle / "runtime" / "Scripts"
    if scripts.is_dir():
        for shim in scripts.glob("*.exe"):
            shim.unlink()


def _unsafe_payload_paths(paths: list[Path]) -> list[Path]:
    """Return paths that could contain device secrets or a real gradebook."""
    unsafe: list[Path] = []
    for path in paths:
        name = path.name.casefold()
        if name in FORBIDDEN_NAMES:
            unsafe.append(path)
        elif name.startswith("client_secret_") and name.endswith(".json"):
            unsafe.append(path)
        elif ".bak-" in name:
            unsafe.append(path)
        elif name == "acm_database.json" and path != Path("acm_database.json"):
            # The one root-level file comes from git archive HEAD and is the
            # fictional sample. A second/nested gradebook is never expected.
            unsafe.append(path)
    return unsafe


def audit_bundle(bundle: Path) -> None:
    """Reject secrets, backups, and any gradebook except the tracked sample."""
    relative_files = [
        path.relative_to(bundle) for path in bundle.rglob("*") if path.is_file()
    ]
    unsafe = _unsafe_payload_paths(relative_files)
    if unsafe:
        joined = ", ".join(map(str, unsafe))
        raise RuntimeError(f"Sensitive or unexpected data files found in bundle: {joined}")


def audit_zip(archive: Path, *, require_runtime: bool) -> None:
    """Audit the actual distributable after compression, not only its stage."""
    with zipfile.ZipFile(archive) as source:
        files = {
            Path(name).relative_to("CAM-portable")
            for name in source.namelist()
            if not name.endswith("/") and Path(name).parts[:1] == ("CAM-portable",)
        }
        foreign = [
            name for name in source.namelist()
            if not name.endswith("/") and Path(name).parts[:1] != ("CAM-portable",)
        ]
    if foreign:
        raise RuntimeError(f"Files outside CAM-portable in archive: {', '.join(foreign)}")
    unsafe = _unsafe_payload_paths(list(files))
    if unsafe:
        joined = ", ".join(map(str, unsafe))
        raise RuntimeError(f"Sensitive or unexpected data files found in zip: {joined}")
    missing = REQUIRED_BUNDLE_FILES - {os.fspath(path) for path in files}
    if require_runtime and Path("runtime/python.exe") not in files:
        missing.add("runtime/python.exe")
    if missing:
        raise RuntimeError(f"Required bundle files missing: {', '.join(sorted(missing))}")


def make_zip(bundle: Path, output_dir: Path, version: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"CAM-portable-v{version}.zip"
    target.unlink(missing_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                out.write(path, Path("CAM-portable") / path.relative_to(bundle))
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION)
    parser.add_argument("--version", default=dt.date.today().strftime("%Y.%m.%d"))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--quick-guide", type=Path)
    parser.add_argument(
        "--stage-only",
        action="store_true",
        help="Skip runtime download/install (for fast structural verification).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if os.name != "nt" and not args.stage_only:
        raise SystemExit("The complete portable bundle must be built on Windows.")
    with tempfile.TemporaryDirectory(prefix="cam-windows-bundle-") as temp:
        bundle = Path(temp) / "CAM-portable"
        bundle.mkdir()
        print("Staging committed files from git archive HEAD...")
        stage_head(bundle)
        if not args.stage_only:
            install_runtime(bundle, args.python_version)
        write_launchers(bundle)
        write_readme(bundle)
        copy_quick_guide(bundle, args.quick_guide)
        prune_runtime(bundle)
        audit_bundle(bundle)
        archive = make_zip(bundle, args.output_dir.resolve(), args.version)
        audit_zip(archive, require_runtime=not args.stage_only)
    print(f"Built {archive}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
