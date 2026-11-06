"""Licences for CAM's portable bundle (CAM2 engine upgrade, D15 and Phase 4).

The bundle is CAM, CAM2 and every library they need, inside an embedded
Python. CAM and CAM2 are MIT, PyMuPDF is used under the AGPL, so the bundle as
a whole is under the AGPL. This module keeps what the bundle says about that
true:

* ``bundle-requirements-<platform>.txt`` pins every library at an exact
  version with its licence, one ``name==version  # licence`` per line. The
  build installs exactly that list (``--no-deps``), so a build on another day
  or computer holds the same libraries.
* :func:`check` fails the build if what was installed differs from the pins,
  if a pin has no licence, or if a library carries no licence text.
* :func:`write_licences` writes the bundle's ``Licences`` folder, taking each
  library's licence text from the library itself.

Refresh the pins after changing ``requirements.txt``::

    python tools/bundle_licences.py pin windows

It asks pip which packages a fresh install would bring, without installing
anything, keeps the licences already written, and marks a new library's
licence ``?`` until someone checks it, which the build refuses.

PyMuPDF 2.0 also asks for add-ons that nothing in CAM or CAM2 uses: two empty
placeholder packages, and onnxruntime, numpy, networkx and others for its AI
page layout. PyMuPDF imports them only if they're there. CAM2's own build
leaves them out (``exam_grading/tools/cam2.spec``) and so does this one, which
is why the pins skip whatever only those add-ons need.
"""

from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import tempfile

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS = REPO_ROOT / "tools"
LICENCE_TEXTS = TOOLS / "licence-texts"
AGPL_TEXT = REPO_ROOT / "exam_grading" / "licences" / "AGPL-3.0.txt"
# CAM2's own exact versions. CAM2 runs inside CAM's bundle, so the libraries
# both use stay at the versions CAM2 was tested and released with.
CAM2_PINS = REPO_ROOT / "exam_grading" / "requirements-build.txt"
PLATFORMS = {"windows": "win_amd64"}
PYTHON_TARGET = "3.14"
CAM_SOURCE = "https://github.com/iamkifojp/criterion-assessment-metrics"
CAM2_SOURCE = "https://github.com/iamkifojp/cam2-exam-grading"
MUPDF_VERSION = "1.28.5"           # the MuPDF inside PyMuPDF 2.0
LICENCE_FILE = re.compile(r"(LICEN[CS]E|COPYING|NOTICE)", re.IGNORECASE)
UNCHECKED = "?"


def pins_path(platform: str) -> Path:
    return TOOLS / f"bundle-requirements-{platform}.txt"


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass(frozen=True)
class Pin:
    name: str
    version: str
    licence: str


@dataclass(frozen=True)
class Installed:
    name: str
    version: str
    texts: tuple                    # ((file name, text), ...)


# --------------------------------------------------------------------------
# The pins file


def read_pins(path: Path) -> dict:
    """``{canonical name: Pin}`` from a pins file."""
    pins = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        spec, _, licence = line.partition("#")
        name, sep, version = spec.strip().partition("==")
        if not sep or not name or not version:
            raise ValueError(f"{path.name}: not name==version: {raw!r}")
        pins[canonical(name)] = Pin(name.strip(), version.strip(), licence.strip())
    return pins


def write_pins(path: Path, pins, platform: str) -> None:
    header = (
        f"# Exact libraries for CAM's {platform} bundle, with their licences\n"
        "# (tools/build_windows_bundle.py installs exactly these, --no-deps).\n"
        "# Teachers never see this. Regenerate with\n"
        f"#   python tools/bundle_licences.py pin {platform}\n"
        "# after changing requirements.txt, then check any licence shown as ?.\n"
        "# PyMuPDF's unused add-ons are left out on purpose (see\n"
        "# tools/bundle_licences.py).\n"
    )
    width = max(len(f"{p.name}=={p.version}") for p in pins)
    body = "".join(f"{p.name}=={p.version}".ljust(width + 2) + f"# {p.licence}\n"
                   for p in sorted(pins, key=lambda p: canonical(p.name)))
    path.write_text(header + body, encoding="utf-8")


def _licence_label(meta: dict) -> str:
    """A short licence name from a package's metadata, or ``?``."""
    expression = (meta.get("license_expression") or "").strip()
    if expression:
        return expression
    licence = (meta.get("license") or "").strip()
    if licence and "\n" not in licence and len(licence) <= 40:
        return licence
    classifiers = [c.split("::")[-1].strip() for c in meta.get("classifier") or []
                   if c.startswith("License ::") and "OSI Approved" != c.split("::")[-1].strip()]
    return " / ".join(classifiers) or UNCHECKED


# Left out of CAM2's pins: its build tool, and Pillow, because CAM's
# Streamlit 1.58 needs Pillow below 13. CAM2's tests also pass on Pillow 12.3.
NOT_FROM_CAM2 = ("pyinstaller", "pillow")


def cam2_constraints(path: Path = CAM2_PINS) -> list:
    """CAM2's pins that CAM's bundle follows."""
    specs = [line.split("#")[0].strip()
             for line in path.read_text(encoding="utf-8").splitlines()]
    return [spec for spec in specs
            if spec and canonical(spec.split("==")[0]) not in NOT_FROM_CAM2]


def resolve(platform: str, requirements: Path = REPO_ROOT / "requirements.txt") -> list:
    """Ask pip what a fresh install of ``requirements`` brings on ``platform``,
    held to CAM2's versions, without installing anything. Returns the Pins
    CAM needs."""
    from packaging.requirements import Requirement

    with tempfile.TemporaryDirectory(prefix="cam-pins-") as temp:
        report = Path(temp) / "report.json"
        constraints = Path(temp) / "cam2-constraints.txt"
        constraints.write_text("\n".join(cam2_constraints()) + "\n", encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--dry-run", "--quiet",
             "--ignore-installed", "--report", report, "--target", Path(temp) / "t",
             "--platform", PLATFORMS[platform], "--python-version", PYTHON_TARGET,
             "--implementation", "cp", "--only-binary=:all:", "-r", requirements,
             "-c", constraints],
            check=True, cwd=REPO_ROOT)
        data = json.loads(report.read_text(encoding="utf-8"))
    env = data["environment"]
    found = {canonical(i["metadata"]["name"]): i["metadata"] for i in data["install"]}
    needed, stack = set(), [canonical(i["metadata"]["name"])
                            for i in data["install"] if i.get("requested")]
    while stack:
        name = stack.pop()
        if name in needed:
            continue
        needed.add(name)
        if name == "pymupdf":           # its add-ons stay out (see module docs)
            continue
        for spec in found[name].get("requires_dist") or []:
            req = Requirement(spec)
            if req.marker is None or req.marker.evaluate(dict(env, extra="")):
                stack.append(canonical(req.name))
    return [Pin(found[n]["name"], found[n]["version"], _licence_label(found[n]))
            for n in sorted(needed)]


def pin(platform: str) -> list:
    """Rewrite the platform's pins file, keeping licences already checked.
    Returns the names whose licence still needs checking."""
    path = pins_path(platform)
    old = read_pins(path) if path.is_file() else {}
    pins = []
    for p in resolve(platform):
        kept = old.get(canonical(p.name))
        licence = kept.licence if kept and kept.licence != UNCHECKED else p.licence
        pins.append(Pin(p.name, p.version, licence))
    write_pins(path, pins, platform)
    return [p.name for p in pins if p.licence == UNCHECKED]


# --------------------------------------------------------------------------
# What was installed, checked against the pins


def installed(site_packages: Path, root: Path = REPO_ROOT) -> dict:
    """``{canonical name: Installed}`` for the libraries in ``site_packages``.
    A library with no licence file of its own takes the one stored under
    ``root``'s ``tools/licence-texts``."""
    out = {}
    for dist in metadata.distributions(path=[str(site_packages)]):
        name = dist.metadata["Name"]
        texts = []
        for f in dist.files or []:
            parts = Path(str(f)).parts
            if parts and parts[0].endswith(".dist-info") and LICENCE_FILE.search(parts[-1]):
                texts.append(("/".join(parts[1:]), Path(dist.locate_file(f)).read_text(
                    encoding="utf-8", errors="replace")))
        stored = root / LICENCE_TEXTS.relative_to(REPO_ROOT) / f"{canonical(name)}.txt"
        if not texts and stored.is_file():
            texts.append((f"tools/licence-texts/{stored.name}",
                          stored.read_text(encoding="utf-8")))
        out[canonical(name)] = Installed(name, dist.version, tuple(sorted(texts)))
    return out


def check(pins: dict, found: dict) -> list:
    """Every problem that would make the bundle's notices untrue."""
    problems = []
    for key, p in sorted(pins.items()):
        got = found.get(key)
        if got is None:
            problems.append(f"{p.name} {p.version} is pinned but not installed")
        elif got.version != p.version:
            problems.append(f"{p.name}: installed {got.version}, pinned {p.version}")
        if not p.licence or p.licence == UNCHECKED:
            problems.append(f"{p.name}: no licence written in the pins file")
        if got is not None and not got.texts:
            problems.append(f"{p.name}: carries no licence text; add one to "
                            f"tools/licence-texts/{key}.txt")
    for key, got in sorted(found.items()):
        if key not in pins:
            problems.append(f"{got.name} {got.version} is installed but not pinned")
    return problems


# --------------------------------------------------------------------------
# The Licences folder


def notice_text(pins: dict, python_version: str) -> str:
    rows = [("Library", "Version", "Licence")]
    rows += [(p.name, p.version, p.licence)
             for p in sorted(pins.values(), key=lambda p: canonical(p.name))]
    rows.append(("Python", python_version, "PSF-2.0, with the software it includes"))
    width = [max(len(r[i]) for r in rows) + 2 for i in range(2)]
    table = "\n".join(f"    {r[0].ljust(width[0])}{r[1].ljust(width[1])}{r[2]}" for r in rows)
    pymupdf = pins.get("pymupdf")
    pymupdf_version = pymupdf.version if pymupdf else "?"
    return f"""CAM (Criterion Assessment Metrics) - licence notice
===================================================

CAM's own code is under the MIT License (CAM-MIT.txt). So is CAM2 Exam
Grading, which CAM includes in its exam_grading folder (CAM2-MIT.txt).

The bundle also includes PyMuPDF, which is available under the GNU Affero
General Public License version 3 (AGPL) or a paid licence from Artifex. CAM
uses it under the AGPL, so the bundle as a whole is licensed under the AGPL.
The full text is in AGPL-3.0.txt.

The source code of CAM and of CAM2 is at:

    {CAM_SOURCE}
    {CAM2_SOURCE}

Each CAM bundle has a matching tag in CAM's repository, named after the
version in the zip's file name. For example, CAM-portable-v2026.11.20.zip
matches the tag v2026.11.20. CAM's tag holds the CAM2 code it includes, and
the build scripts are in tools/ there.

The source code of PyMuPDF {pymupdf_version} and of MuPDF {MUPDF_VERSION}, the library inside
it, is attached to the same release as each bundle on the Releases list of
CAM's repository, as pymupdf-{pymupdf_version}.tar.gz and mupdf-{MUPDF_VERSION}-source.tar.gz.
The original copies are at:

    https://pypi.org/project/pymupdf/{pymupdf_version}/
    https://mupdf.com/downloads/archive/mupdf-{MUPDF_VERSION}-source.tar.gz

CAM comes with no warranty, as these licences explain.


Libraries in the bundle
-----------------------

{table}

The licence text for each of these, except PyMuPDF, is in
THIRD-PARTY-NOTICES.txt.
"""


def third_party_text(pins: dict, found: dict, python_version: str,
                     python_licence: str) -> str:
    rule = "=" * 78
    parts = ["Licence texts for the libraries in the CAM bundle.\n"
             "PyMuPDF's licence is in AGPL-3.0.txt. See NOTICE.txt for the overview.\n",
             f"\n{rule}\nPython {python_version}\n{rule}\n\n{python_licence.strip()}\n"]
    for key in sorted(pins, key=lambda k: canonical(pins[k].name)):
        p = pins[key]
        if key == "pymupdf":
            continue
        for file_name, text in found[key].texts:
            parts.append(f"\n{rule}\n{p.name} {p.version} ({p.licence}) - {file_name}\n"
                         f"{rule}\n\n{text.strip()}\n")
    return "".join(parts)


LICENCE_FILES = ("NOTICE.txt", "AGPL-3.0.txt", "CAM-MIT.txt", "CAM2-MIT.txt")
THIRD_PARTY = "THIRD-PARTY-NOTICES.txt"


def write_licences(folder: Path, pins: dict, python_version: str,
                   found: dict | None = None, python_licence: str | None = None,
                   root: Path = REPO_ROOT) -> None:
    """Write the bundle's ``Licences`` folder from the sources under ``root``.
    Without ``found`` (a build with no runtime), THIRD-PARTY-NOTICES.txt is
    left out."""
    folder.mkdir(parents=True, exist_ok=True)
    copies = {"AGPL-3.0.txt": AGPL_TEXT.relative_to(REPO_ROOT),
              "CAM-MIT.txt": Path("LICENSE"),
              "CAM2-MIT.txt": Path("exam_grading/LICENSE")}
    (folder / "NOTICE.txt").write_text(notice_text(pins, python_version), encoding="utf-8")
    for name, source in copies.items():
        (folder / name).write_text((root / source).read_text(encoding="utf-8"),
                                   encoding="utf-8")
    if found is not None:
        (folder / THIRD_PARTY).write_text(
            third_party_text(pins, found, python_version, python_licence or ""),
            encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    pin_cmd = sub.add_parser("pin", help="rewrite a platform's pins file")
    pin_cmd.add_argument("platform", choices=sorted(PLATFORMS))
    args = parser.parse_args()
    unchecked = pin(args.platform)
    print(f"Wrote {pins_path(args.platform).relative_to(REPO_ROOT)}")
    if unchecked:
        print("Check and write the licence for: " + ", ".join(unchecked))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
