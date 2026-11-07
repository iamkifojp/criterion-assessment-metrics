"""Build a synthetic Finder launch probe on an Apple Silicon Mac.

Requires native Python 3.12 or newer and the Xcode Command Line Tools.
The probe contains no CAM code, preferences or gradebook.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import platform
import plistlib
import subprocess
import sys
import tarfile
import tempfile

from build_windows_bundle import CACHE_DIR, DEFAULT_OUTPUT_DIR, download


RUNTIME_ASSET = "cpython-3.14.6+20260610-aarch64-apple-darwin-install_only.tar.gz"
RUNTIME_URL = ("https://github.com/astral-sh/python-build-standalone/releases/"
               f"download/20260610/{RUNTIME_ASSET.replace('+', '%2B')}")
RUNTIME_SHA256 = "953db72ff2dea68b5112231b1ba77163ec9114f87c7ece530b3ea742a3b492c5"
APP_NAME = "CAM Runtime Probe.app"
ZIP_NAME = "CAM-macOS-Runtime-Probe.zip"

LAUNCHER = r"""
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <string.h>
#include <limits.h>

int main(int argc, char **argv) {
    char launcher[PATH_MAX], python[PATH_MAX], probe[PATH_MAX];
    if (!realpath(argv[0], launcher)) {
        perror("Finding the probe launcher");
        return 1;
    }
    *strrchr(launcher, '/') = '\0';
    if (snprintf(python, sizeof python, "%s/../Resources/python/bin/python3",
                 launcher) >= sizeof python ||
        snprintf(probe, sizeof probe, "%s/../Resources/probe.py",
                 launcher) >= sizeof probe) {
        fputs("The path to the probe app is too long.\n", stderr);
        return 1;
    }
    char *args[] = {python, "-I", "-B", probe, argc > 1 ? argv[1] : NULL, NULL};
    execv(python, args);
    perror("Launching bundled Python");
    return 1;
}
"""

PROBE = """\
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import subprocess
import sys
import traceback


def check():
    import ssl

    runtime = Path(__file__).resolve().parent / "python"
    if Path(sys.base_prefix).resolve() != runtime:
        raise RuntimeError(f"Unexpected Python prefix: {sys.base_prefix}")
    print(f"Bundled Python {sys.version.split()[0]} loaded {ssl.OPENSSL_VERSION}")
    child = subprocess.run(
        [sys.executable, "-I", "-B", "-c",
         "import ssl, sys; print(sys.base_prefix); print(ssl.OPENSSL_VERSION)"],
        capture_output=True, text=True, check=False,
    )
    print(child.stdout, end="")
    print(child.stderr, end="")
    child.check_returncode()
    if Path(child.stdout.splitlines()[0]).resolve() != runtime:
        raise RuntimeError("The child did not use bundled Python")
    print("PASS: bundled Python and child runtime.")


if "--check" in sys.argv[1:]:
    check()
else:
    log = Path.home() / "Library/Logs/CAM-runtime-probe.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    status = 0
    with log.open("w", encoding="utf-8") as output:
        with redirect_stdout(output), redirect_stderr(output):
            try:
                check()
            except Exception:
                traceback.print_exc()
                status = 1
    subprocess.run(["/usr/bin/open", "-t", log], check=False)
    raise SystemExit(status)
"""


def extract_runtime(archive: Path, destination: Path) -> None:
    with archive.open("rb") as file:
        if hashlib.file_digest(file, "sha256").hexdigest() != RUNTIME_SHA256:
            raise ValueError(f"Runtime checksum mismatch: {archive}")
        file.seek(0)
        with tarfile.open(fileobj=file, mode="r:gz") as runtime:
            runtime.extractall(destination, filter="data")


def build(output_dir: Path) -> Path:
    runtime = download(RUNTIME_URL, CACHE_DIR / RUNTIME_ASSET)
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="cam-mac-probe-", dir=output_dir) as temp:
        staging = Path(temp)
        app = staging / APP_NAME
        contents = app / "Contents"
        launcher = contents / "MacOS" / "probe"
        resources = contents / "Resources"
        launcher.parent.mkdir(parents=True)
        resources.mkdir()
        extract_runtime(runtime, resources)
        (resources / "probe.py").write_text(PROBE, encoding="utf-8")
        (contents / "Info.plist").write_bytes(plistlib.dumps({
            "CFBundleName": "CAM Runtime Probe",
            "CFBundleIdentifier": "org.cam-assessment.runtime-probe",
            "CFBundleExecutable": launcher.name,
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1",
        }))
        subprocess.run(
            ["/usr/bin/clang", "-arch", "arm64", "-x", "c", "-o", launcher, "-"],
            input=LAUNCHER, text=True, check=True,
        )
        subprocess.run(["/usr/bin/codesign", "--sign", "-", app], check=True)
        archive = staging / ZIP_NAME
        subprocess.run(["/usr/bin/ditto", "-c", "-k", "--norsrc", "--noextattr",
                        "--noacl", "--keepParent", app, archive], check=True)
        unpacked = staging / "unpacked"
        subprocess.run(["/usr/bin/ditto", "-x", "-k", archive, unpacked], check=True)
        unpacked_app = unpacked / APP_NAME
        subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict",
                        unpacked_app], check=True)
        subprocess.run([unpacked_app / launcher.relative_to(app), "--check"], check=True)
        return archive.replace(output_dir / ZIP_NAME)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("Run on an Apple Silicon Mac using native ARM64 Python.")
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or newer is required to extract the runtime safely.")
    print(f"Built {build(args.output_dir.resolve())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
