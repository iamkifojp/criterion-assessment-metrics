"""The bundle's licence notices stay true (CAM2 engine upgrade, D15, Phase 4)."""

import re
import tempfile
import unittest
from pathlib import Path

from tools import bundle_licences as lic

ROOT = Path(__file__).resolve().parents[1]
ADDONS = {"pymupdf-layout", "pymupdf4llm", "onnxruntime", "flatbuffers",
          "networkx", "psutil", "pyyaml", "tabulate"}


def _requirement_names(path: Path) -> set:
    """Top-level names in a requirements file, following ``-r``."""
    names = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#")[0].strip()
        if line.startswith("-r"):
            names |= _requirement_names(path.parent / line[2:].strip())
        elif line:
            names.add(lic.canonical(re.split(r"[<>=!~\[; ]", line)[0]))
    return names


def _dist(site: Path, name: str, version: str, licence_text=None):
    info = site / f"{name}-{version}.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n")
    record = [f"{info.name}/METADATA,,"]
    if licence_text is not None:
        (info / "licenses").mkdir()
        (info / "licenses" / "LICENSE").write_text(licence_text)
        record.append(f"{info.name}/licenses/LICENSE,,")
    (info / "RECORD").write_text("\n".join(record) + "\n")


class WindowsPinsTests(unittest.TestCase):
    def setUp(self):
        self.pins = lic.read_pins(lic.pins_path("windows"))

    def test_every_pin_has_a_checked_licence(self):
        unchecked = [p.name for p in self.pins.values()
                     if not p.licence or p.licence == lic.UNCHECKED]
        self.assertEqual(unchecked, [])

    def test_pymupdf_is_2_0_under_the_agpl_without_its_addons(self):
        self.assertEqual(self.pins["pymupdf"].version, "2.0")
        self.assertIn("AGPL-3.0", self.pins["pymupdf"].licence)
        self.assertEqual(ADDONS & set(self.pins), set())

    def test_libraries_shared_with_cam2_follow_cam2s_pins(self):
        for spec in lic.cam2_constraints():
            name, _, version = spec.partition("==")
            key = lic.canonical(name)
            if key in self.pins:
                self.assertEqual(self.pins[key].version, version, name)
        self.assertIn("pillow", lic.NOT_FROM_CAM2)
        self.assertTrue(self.pins["pillow"].version.startswith("12."))

    def test_everything_cam_asks_for_is_pinned(self):
        names = _requirement_names(ROOT / "requirements.txt")
        self.assertEqual(names - set(self.pins), set())

    def test_streamlit_has_a_stored_licence_text(self):
        text = (lic.LICENCE_TEXTS / "streamlit.txt").read_text(encoding="utf-8")
        self.assertIn("Apache License", text)
        self.assertIn("Snowflake", text)


class CheckTests(unittest.TestCase):
    def test_check_lists_every_way_the_notice_could_be_untrue(self):
        with tempfile.TemporaryDirectory() as temp:
            site = Path(temp)
            _dist(site, "good", "1.0", "MIT text")
            _dist(site, "drifted", "2.1", "BSD text")
            _dist(site, "bare", "1.0")
            _dist(site, "stray", "0.1", "text")
            pins = {lic.canonical(p.name): p for p in (
                lic.Pin("good", "1.0", "MIT"), lic.Pin("drifted", "2.0", "BSD-3-Clause"),
                lic.Pin("bare", "1.0", "MIT"), lic.Pin("absent", "3.0", "MIT"),
                lic.Pin("vague", "1.0", lic.UNCHECKED))}
            problems = "\n".join(lic.check(pins, lic.installed(site, root=Path(temp))))
        for expected in ("drifted: installed 2.1, pinned 2.0",
                         "bare: carries no licence text",
                         "absent 3.0 is pinned but not installed",
                         "vague: no licence written",
                         "stray 0.1 is installed but not pinned"):
            self.assertIn(expected, problems)
        self.assertNotIn("good", problems)

    def test_a_stored_text_stands_in_for_a_missing_one(self):
        with tempfile.TemporaryDirectory() as temp:
            root, site = Path(temp) / "root", Path(temp) / "site"
            stored = root / "tools" / "licence-texts"
            stored.mkdir(parents=True)
            (stored / "bare.txt").write_text("Apache License text")
            _dist(site, "bare", "1.0")
            found = lic.installed(site, root=root)
        self.assertEqual(found["bare"].texts,
                         (("tools/licence-texts/bare.txt", "Apache License text"),))
        self.assertEqual(lic.check({"bare": lic.Pin("bare", "1.0", "Apache-2.0")}, found), [])


class WriteLicencesTests(unittest.TestCase):
    def test_folder_holds_the_notice_texts_and_both_mit_licences(self):
        pins = {"pymupdf": lic.Pin("PyMuPDF", "2.0", "AGPL-3.0"),
                "good": lic.Pin("good", "1.0", "MIT")}
        with tempfile.TemporaryDirectory() as temp:
            site, folder = Path(temp) / "site", Path(temp) / "Licences"
            _dist(site, "good", "1.0", "Permission is hereby granted (good)")
            _dist(site, "PyMuPDF", "2.0", "AGPL text")
            lic.write_licences(folder, pins, "3.14.6", lic.installed(site),
                               "PSF LICENSE AGREEMENT")
            notice = (folder / "NOTICE.txt").read_text(encoding="utf-8")
            third = (folder / lic.THIRD_PARTY).read_text(encoding="utf-8")
            names = sorted(p.name for p in folder.iterdir())
            agpl = (folder / "AGPL-3.0.txt").read_text(encoding="utf-8")
        self.assertEqual(names, sorted(lic.LICENCE_FILES + (lic.THIRD_PARTY,)))
        self.assertIn("GNU AFFERO GENERAL PUBLIC LICENSE", agpl)
        self.assertRegex(notice, r"good\s+1\.0\s+MIT")
        self.assertRegex(notice, r"Python\s+3\.14\.6")
        self.assertIn("pymupdf-2.0.tar.gz", notice)
        self.assertIn(lic.CAM_SOURCE, notice)
        self.assertIn("PSF LICENSE AGREEMENT", third)
        self.assertIn("good 1.0 (MIT) - licenses/LICENSE", third)
        self.assertNotIn("AGPL text", third)     # PyMuPDF's is AGPL-3.0.txt

    def test_without_a_runtime_only_the_third_party_texts_are_left_out(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "Licences"
            lic.write_licences(folder, {"good": lic.Pin("good", "1.0", "MIT")}, "3.14.6")
            self.assertEqual(sorted(p.name for p in folder.iterdir()),
                             sorted(lic.LICENCE_FILES))


if __name__ == "__main__":
    unittest.main()
