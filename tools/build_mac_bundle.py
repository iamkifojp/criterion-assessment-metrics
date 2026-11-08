"""Build a signed Apple Silicon CAM.app ZIP from a Git tag or a test commit."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile

import bundle_licences
from build_mac_gatekeeper_probe import RUNTIME_ASSET, RUNTIME_URL, extract_runtime
from build_windows_bundle import (CACHE_DIR, DEFAULT_OUTPUT_DIR, REPO_ROOT,
                                  audit_bundle, download, stage_head)


PYTHON_VERSION = "3.14.6"
MIN_MACOS = "14.0"  # NumPy's arm64 wheel requires macOS Sonoma.
PINS = Path("tools/bundle-requirements-macos.txt")
LAUNCHER = Path("tools/macos/launcher.m")
SUPERVISOR = Path("tools/start_cam.py")


def run(*command, **kwargs):
    return subprocess.run(command, check=True, **kwargs)


def git(*args: str) -> str:
    return run("git", *args, cwd=REPO_ROOT, capture_output=True, text=True).stdout.strip()


def install_runtime(runtime: Path, source: Path, wheelhouse: Path | None) -> None:
    version_dir = runtime / "lib/python3.14"
    python = runtime / "bin/python3.14"
    site = version_dir / "site-packages"
    options = ["--no-index", "--find-links", wheelhouse] if wheelhouse else []
    run(python, "-I", "-B", "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
        "--only-binary=:all:", "--no-deps", "--no-compile", *options, "-r", source / PINS)
    run(python, "-I", "-B", "-m", "pip", "uninstall", "--quiet", "--yes", "pip")
    for folder in site.rglob("__pycache__"):
        shutil.rmtree(folder)
    # Python is the only entry point the packaged app and its helpers use.
    for shim in (runtime / "bin").iterdir():
        if shim.name not in {"python", "python3", "python3.14"}:
            shim.unlink()
    pins = bundle_licences.read_pins(source / PINS)
    installed = bundle_licences.installed(site, root=source)
    errors = bundle_licences.check(pins, installed)
    if errors:
        raise RuntimeError("Bundle libraries don't match their notices:\n  " + "\n  ".join(errors))
    bundle_licences.write_licences(
        runtime.parent / "CAM/Licences", pins, PYTHON_VERSION, installed,
        (version_dir / "LICENSE.txt").read_text(encoding="utf-8"), root=source,
    )


def place_and_sign_runtime(runtime: Path, contents: Path) -> None:
    """Keep import paths as symlinks and put Mach-O files in code locations."""
    frameworks = contents / "Frameworks"
    frameworks.mkdir()
    executable = runtime / "bin/python3.14"
    libraries = sorted(p for p in runtime.rglob("*")
                       if p.suffix in {".dylib", ".so"} and not p.is_symlink())
    destinations = {}
    for index, path in enumerate(libraries):
        destination = frameworks / path.name
        if destination in destinations.values():
            destination = frameworks / f"{index}-{path.name}"
        destinations[path] = destination

    # Python's executable supplies the Frameworks rpath for the loaded wheels.
    run("/usr/bin/install_name_tool", "-rpath", "@executable_path/../lib",
        "@executable_path/../Frameworks", executable)
    destinations[executable] = contents / "MacOS" / executable.name
    for path in libraries:
        commands = run("/usr/bin/otool", "-arch", "arm64", "-l", path,
                       capture_output=True, text=True).stdout
        dependencies = re.findall(
            r"cmd LC_(?:LOAD|LOAD_WEAK|REEXPORT|LOAD_UPWARD)_DYLIB\s+"
            r"cmdsize \d+\s+name (.+?) \(offset \d+\)", commands,
        )
        changes = []
        for dependency in dependencies:
            if dependency.startswith("@loader_path/"):
                target = (path.parent / dependency.removeprefix("@loader_path/")).resolve()
                replacement = "@rpath/" + destinations[target].name
                changes.extend(["-change", dependency, replacement])
            elif not dependency.startswith(("@rpath/", "/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Nonrelocatable library reference in {path.name}: {dependency}")
        if changes:
            run("/usr/bin/install_name_tool", *changes, path)

    for path, destination in destinations.items():
        path.rename(destination)
        path.symlink_to(os.path.relpath(destination, path.parent))
        run("/usr/bin/codesign", "--force", "--sign", "-", destination,
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def verify_extracted(app: Path, home: Path) -> None:
    contents = app / "Contents"
    payload = contents / "Resources/CAM"
    runtime = contents / "Resources/python"
    audit_bundle(payload)
    for path in contents.rglob("*"):
        if path.is_symlink() and not path.resolve(strict=True).is_relative_to(contents):
            raise RuntimeError(f"Bundle link points outside the app: {path}")
    for path in ("app.py", "acm_database.json", "cam_grading_workspace/app.py",
                 "exam_grading/launcher.py", "Licences/THIRD-PARTY-NOTICES.txt"):
        if not (payload / path).is_file():
            raise RuntimeError(f"Required bundle file missing: {path}")
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    home.mkdir()
    env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "PYTHONHOME": str(runtime),
           "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "MPLCONFIGDIR": str(home / "matplotlib")}
    run(contents / "MacOS/python3.14", "-B", "-c", """
import io
import ssl
import subprocess
import sys
import streamlit
import pymupdf
import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image

doc = pymupdf.open()
doc.new_page().get_pixmap()
buf = io.BytesIO()
pq.write_table(pa.table({"score": [4]}), buf)
assert pq.read_table(io.BytesIO(buf.getvalue())).column("score").to_pylist() == [4]
Image.new("RGB", (1, 1)).save(io.BytesIO(), "JPEG")
subprocess.run([sys.executable, "-B", "-c", "import flask, openpyxl, pymupdf"], check=True)
print(f"Verified Python {sys.version.split()[0]}, Streamlit {streamlit.__version__}, "
      f"PyMuPDF {pymupdf.__version__}, PyArrow {pa.__version__}, Pillow and a child process.")
""", cwd=home, env=env)


def build(output: Path, ref: str, version: str, suffix: str, wheelhouse: Path | None) -> Path:
    year, month, day, *patch = version.split(".")
    # macOS reads three components. Reserve two digits for same-day patches.
    bundle_version = f"{year}.{month}.{int(day) * 100 + int(patch[0] if patch else 0)}"
    archive_path = download(RUNTIME_URL, CACHE_DIR / RUNTIME_ASSET)
    output.mkdir(parents=True, exist_ok=True)
    target = output / f"CAM-Mac-AppleSilicon-{suffix}.zip"
    with tempfile.TemporaryDirectory(prefix="cam-mac-bundle-", dir=output) as temp:
        stage = Path(temp)
        app = stage / "CAM.app"
        contents = app / "Contents"
        macos = contents / "MacOS"
        resources = contents / "Resources"
        payload = resources / "CAM"
        macos.mkdir(parents=True)
        payload.mkdir(parents=True)
        source = stage / "source"
        stage_head(payload, source, ref=ref)
        shutil.copy2(source / SUPERVISOR, resources / "start_cam.py")
        audit_bundle(payload)

        extract_runtime(archive_path, resources)
        runtime = resources / "python"
        install_runtime(runtime, source, wheelhouse)
        place_and_sign_runtime(runtime, contents)

        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleIdentifier": "org.cam-assessment.cam",
            "CFBundleName": "CAM",
            "CFBundleExecutable": "CAM",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": f"{year}.{month}.{day}",
            "CFBundleVersion": bundle_version,
            "CAMReleaseVersion": version,
            "LSMinimumSystemVersion": MIN_MACOS,
            "NSDocumentsFolderUsageDescription": "CAM uses Documents for gradebooks you choose there.",
            "NSDesktopFolderUsageDescription": "CAM reads student work and gradebooks you choose on Desktop.",
            "NSDownloadsFolderUsageDescription": "CAM reads student work you choose from Downloads.",
        }))
        run("/usr/bin/clang", "-arch", "arm64", f"-mmacosx-version-min={MIN_MACOS}",
            "-fobjc-arc", "-framework", "Cocoa", "-o", macos / "CAM", source / LAUNCHER)
        run("/usr/bin/codesign", "--force", "--sign", "-", app)
        archive = stage / target.name
        run("/usr/bin/ditto", "-c", "-k", "--norsrc", "--noextattr", "--noacl",
            "--keepParent", app, archive)
        unpacked = stage / "unpacked"
        run("/usr/bin/ditto", "-x", "-k", archive, unpacked)
        if list(unpacked.iterdir()) != [unpacked / app.name]:
            raise RuntimeError("The ZIP must contain only CAM.app")
        verify_extracted(unpacked / app.name, stage / "smoke-home")
        archive.replace(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--tag", help="release tag vYYYY.MM.DD or vYYYY.MM.DD.N")
    mode.add_argument("--dev", action="store_true", help="build a test ZIP from HEAD")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--wheelhouse", type=Path, help="use a local folder of pinned wheels")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64" or sys.version_info < (3, 12):
        parser.error("Run with native Python 3.12+ and Xcode Command Line Tools on Apple Silicon.")
    if args.tag and not re.fullmatch(r"v[0-9]{4}\.[0-9]{2}\.[0-9]{2}(?:\.[1-9][0-9]?)?", args.tag):
        parser.error("Release tag must have the form vYYYY.MM.DD or vYYYY.MM.DD.N (N from 1 to 99).")
    ref = git("rev-parse", "--verify", f"refs/tags/{args.tag}^{{commit}}" if args.tag else "HEAD")
    version = args.tag[1:] if args.tag else git("show", "-s", "--format=%cs", ref).replace("-", ".")
    wheelhouse = args.wheelhouse.resolve() if args.wheelhouse else None
    archive = build(args.output_dir.resolve(), ref, version, args.tag or f"dev-{ref[:7]}", wheelhouse)
    with archive.open("rb") as file:
        digest = hashlib.file_digest(file, "sha256").hexdigest()
    print(f"Built {archive}\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
