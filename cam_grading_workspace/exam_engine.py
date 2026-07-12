"""
Exam Slicing engine for Criterion Assessment Metrics (CAM).

Turns a folder of scanned student exam PDFs into per-question crop images so
the main grading UI can grade one question across every student at a time.

The teacher programs an exam once in the /exam_setup screen: each question is
a label ("Q1"), a grid coordinate range ("page2!A2:C5") and a max score. The
coordinate system is a paper-size-dependent grid laid over the physical page,
so a range describes a rectangle of the paper independent of scan resolution.

The grid comes at three densities, stored per exam under the config's "grid"
key: "legacy" (~2cm cells — A4 10x15, B5 9x12, A3 15x21; what every exam saved
before the density feature means, and the fallback for any config with no
"grid" key), "compact" (~1.4cm, the default for new exams) and "fine" (~1cm).
Columns are lettered left to right Excel-style (A..Z, AA, AB, …), rows numbered
top to bottom. A config without a "grid" key resolves to "legacy" and behaves
byte-identically to before the feature existed.

Auto-DPI: scans arrive at unknown resolutions, so the pixel size of one grid
cell is derived per file. Knowing the paper's physical size (A4/A3/B5) and the
image's pixel width, the effective DPI is

    dpi = pixel_width / (paper_width_mm / 25.4)

and one grid cell spans (paper_width_mm / n_cols) mm — i.e. cell_px = mm * dpi/25.4.
This is computed per axis so a slightly stretched scan still lands on the
right region of the page.

Crops are written to  <output_root>/<Exam Name>/<Q label>/<Student>.png .

PDF pages are rasterised with PyMuPDF (fitz) at a fixed render DPI; plain
image files (a photographed exam page) are opened directly with Pillow.
"""

from __future__ import annotations

import io
import json
import os
import re
import threading

from PIL import Image


# PyMuPDF (fitz) is only needed to rasterise PDF exam scans. Import it lazily so
# the whole grading workspace — including Google Drive sign-in, which needs no
# PDF handling — still boots when PyMuPDF isn't installed. Only the PDF code
# paths below then fail, and with a message that names the fix.
def _fitz():
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to read PDF exam scans but is not installed — "
            "run: pip install PyMuPDF"
        ) from exc
    return fitz

# --- Grid geometry -----------------------------------------------------------

# Physical paper sizes, portrait, in millimetres (width, height).
PAPER_SIZES_MM = {
    "A4": (210.0, 297.0),
    "A3": (297.0, 420.0),
    "B5": (176.0, 250.0),
}

# Grid dimensions per paper size AND density. Each density's (cols, rows) is
# chosen so one cell is roughly the named physical size:
#   legacy  ~2cm   (A4: 210/10=21.0 × 297/15=19.8 mm — the original grid)
#   compact ~1.4cm (A4: 210/15=14.0 × 297/21=14.1 mm — default for new exams)
#   fine    ~1cm   (A4: 210/21=10.0 × 297/30= 9.9 mm)
# Mirrored verbatim in the JS PAPER_GRIDS of EXAM_SETUP_PAGE (app.py) — this
# table is the source of truth; keep the two in sync.
PAPER_GRIDS = {
    "A4": {"legacy": (10, 15), "compact": (15, 21), "fine": (21, 30)},
    "B5": {"legacy": (9, 12),  "compact": (13, 18), "fine": (18, 25)},
    "A3": {"legacy": (15, 21), "compact": (21, 30), "fine": (30, 42)},
}

# Valid density keys. "legacy" is the backward-compatible default (an exam
# config with no "grid" key means "legacy"); "compact" is the UI default for
# new exams.
GRID_DENSITIES = ("legacy", "compact", "fine")

# Reserved crop-dir (and question-label) name for the optional handwritten-name
# region. process_exam slices the name box to <exam>/__name__/<Student>.png so
# CAM Window 2 can eyeball a mis-named script; save_exam rejects a real question
# labelled this so nothing collides with the reserved dir.
NAME_BOX_DIR = "__name__"

# Synthesized when an exam config carries no explicit sections (every legacy
# exam, and any new exam the teacher never split). Guarantees ≥1 section so the
# rest of the pipeline — and CAM — can always assume at least one.
DEFAULT_SECTION_NAME = "All Questions"


def grid_of(config):
    """The density key stored on an exam config; absent/unknown -> 'legacy'.

    "legacy" is the backward-compat default: a config with no (or a garbage)
    "grid" key describes the original ~2cm grid, so it parses and slices exactly
    as it did before per-exam density existed.
    """
    g = str((config or {}).get("grid") or "").strip().lower()
    return g if g in GRID_DENSITIES else "legacy"


def grid_for(paper_size, grid="legacy"):
    """(cols, rows) of the coordinate grid for one paper size + density.

    ``grid`` is one of GRID_DENSITIES; unknown paper size falls back to A4 and
    an unknown density falls back to that paper's legacy grid, so a malformed
    config still yields a usable (and backward-compatible) grid.
    """
    per_paper = PAPER_GRIDS.get(paper_size, PAPER_GRIDS["A4"])
    return per_paper.get(grid, per_paper["legacy"])


def col_name(index):
    """0-based column index -> Excel-style letters (0->A, 25->Z, 26->AA)."""
    i = int(index)
    if i < 0:
        raise ValueError(f"Column index {index!r} must be >= 0.")
    name = ""
    while True:
        name = chr(ord("A") + i % 26) + name
        i = i // 26 - 1
        if i < 0:
            return name


def col_index(letters):
    """Excel-style column letters -> 0-based index (A->0, Z->25, AA->26).

    Raises ValueError on anything that isn't one or more ASCII letters.
    """
    s = str(letters or "").strip().upper()
    if not s or not all("A" <= ch <= "Z" for ch in s):
        raise ValueError(f"Bad column letters {letters!r}.")
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


# DPI used when rasterising a PDF page. Crop geometry is derived from the
# resulting pixel size via the auto-DPI formula, so this only affects quality.
RENDER_DPI = 200

# Accepts "page2!A2:C5", "A2:C5" (page 1 implied) and a single cell "B7".
# One or two letters are accepted syntactically (fine A3 reaches column AD);
# parse_range then validates the cell against the actual grid of the exam's
# paper size + density.
_RANGE_RE = re.compile(
    r"^\s*(?:page\s*(\d+)\s*!\s*)?"
    r"([A-Za-z]{1,2})\s*(\d{1,2})"
    r"(?:\s*:\s*([A-Za-z]{1,2})\s*(\d{1,2}))?\s*$"
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def parse_range(raw, paper_size="A4", grid="legacy"):
    """Parse a grid range string into its page + cell rectangle.

    Returns {"page": 1-based page, "c1", "r1", "c2", "r2"} with 0-based
    inclusive column/row indices, normalised so c1<=c2 and r1<=r2.
    Raises ValueError on anything malformed or outside the paper size + density
    grid (e.g. A1..J15 for legacy A4, A1..U30 for fine A4, A1..AD42 for fine A3).
    """
    cols, rows = grid_for(paper_size, grid)
    m = _RANGE_RE.match(str(raw or ""))
    if not m:
        raise ValueError(
            f"Bad coordinate range {raw!r} — expected e.g. 'A2:C5' or 'page2!A2:C5'."
        )
    page = int(m.group(1)) if m.group(1) else 1
    c1 = col_index(m.group(2))
    r1 = int(m.group(3)) - 1
    if m.group(4):
        c2 = col_index(m.group(4))
        r2 = int(m.group(5)) - 1
    else:
        c2, r2 = c1, r1
    if not (0 <= c1 < cols and 0 <= c2 < cols):
        raise ValueError(
            f"Column out of range in {raw!r} (columns are A-"
            f"{col_name(cols - 1)} on {paper_size}).")
    if not (0 <= r1 < rows and 0 <= r2 < rows):
        raise ValueError(
            f"Row out of range in {raw!r} (rows are 1-{rows} on {paper_size}).")
    if c1 > c2:
        c1, c2 = c2, c1
    if r1 > r2:
        r1, r2 = r2, r1
    return {"page": page, "c1": c1, "r1": r1, "c2": c2, "r2": r2}


def parse_max_score(raw):
    """Coerce a score spec into an int max: '0-3' -> 3, '5' -> 5."""
    s = str(raw or "").strip()
    m = re.match(r"^\s*\d+\s*[-–~]\s*(\d+)\s*$", s)
    if m:
        return int(m.group(1))
    try:
        return max(0, int(float(s)))
    except ValueError:
        raise ValueError(f"Bad score range {raw!r} — use e.g. '0-3' or '3'.")


def auto_dpi(pixels, paper_mm):
    """Effective scan DPI from a pixel span covering ``paper_mm`` millimetres."""
    return pixels / (paper_mm / 25.4)


def range_to_bbox(img_w, img_h, paper_size, rng, grid="legacy"):
    """Translate a parsed grid range into a pixel bounding box on one image.

    The physical cell size (paper_mm / grid count) is converted to pixels via
    the per-axis auto-calculated DPI, then the inclusive cell rectangle
    [c1..c2] x [r1..r2] becomes (left, top, right, bottom), clamped to the
    image bounds. ``grid`` selects the density (default "legacy" so existing
    callers keep the original geometry).
    """
    paper_w_mm, paper_h_mm = PAPER_SIZES_MM.get(paper_size, PAPER_SIZES_MM["A4"])
    grid_cols, grid_rows = grid_for(paper_size, grid)
    dpi_x = auto_dpi(img_w, paper_w_mm)
    dpi_y = auto_dpi(img_h, paper_h_mm)
    cell_w_px = (paper_w_mm / grid_cols) / 25.4 * dpi_x
    cell_h_px = (paper_h_mm / grid_rows) / 25.4 * dpi_y
    left = int(round(rng["c1"] * cell_w_px))
    top = int(round(rng["r1"] * cell_h_px))
    right = int(round((rng["c2"] + 1) * cell_w_px))
    bottom = int(round((rng["r2"] + 1) * cell_h_px))
    left = max(0, min(left, img_w - 1))
    top = max(0, min(top, img_h - 1))
    right = max(left + 1, min(right, img_w))
    bottom = max(top + 1, min(bottom, img_h))
    return (left, top, right, bottom)


# --- Student file discovery + page rendering ----------------------------------

def list_student_files(folder):
    """Sorted [(student_name, abs_path)] of PDFs/images directly in ``folder``.

    The filename stem (minus extension) is the student identity — scans are
    expected to be saved one file per student, named after the student.
    """
    out = []
    try:
        entries = sorted(os.listdir(folder))
    except OSError as e:
        raise ValueError(f"Cannot read folder {folder!r}: {e}")
    for name in entries:
        path = os.path.join(folder, name)
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == ".pdf" or ext in IMAGE_EXTS:
            out.append((os.path.splitext(name)[0], path))
    return out


def page_count(path):
    """Number of grid-addressable pages in one student file (images have 1)."""
    if os.path.splitext(path)[1].lower() == ".pdf":
        with _fitz().open(path) as doc:
            return doc.page_count
    return 1


def load_page_image(path, page_number):
    """Return one page of a student file as a Pillow RGB image (1-based page).

    PDFs are rasterised at RENDER_DPI; image files ignore the page number
    beyond page 1. Raises ValueError for a page that doesn't exist.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        with _fitz().open(path) as doc:
            if not (1 <= page_number <= doc.page_count):
                raise ValueError(
                    f"{os.path.basename(path)} has {doc.page_count} page(s); "
                    f"page {page_number} was requested."
                )
            pix = doc[page_number - 1].get_pixmap(dpi=RENDER_DPI)
            return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    if page_number != 1:
        raise ValueError(f"{os.path.basename(path)} is a single image (page 1 only).")
    with Image.open(path) as im:
        return im.convert("RGB")


def page_png_bytes(path, page_number, max_width=1400):
    """PNG bytes of one page, downscaled for browser preview."""
    img = load_page_image(path, page_number)
    if img.width > max_width:
        ratio = max_width / img.width
        img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


# --- Cropping pipeline ---------------------------------------------------------

def _safe_name(name):
    return re.sub(r'[\\/*?:"<>|]', "_", str(name or "").strip()).strip() or "Unnamed"


def process_exam(config, output_root, progress=None):
    """Crop every question region out of every student file.

    ``config`` is one saved exam definition:
        {"name", "paper_size", "pdf_folder", "name_box": "<range>"|None,
         "sections": [{"name", "required"}, ...],
         "questions": [{"label", "range", "max", "section"}, ...]}

    Saves crops to  <output_root>/<Exam Name>/<Q label>/<Student>.png  and
    returns a summary {students, questions, crops, errors:[...]}. When a
    ``name_box`` range is present its crop lands under the reserved
    ``__name__`` label; sections carry no pixels and don't affect slicing.

    ``progress``, if given, is called ``progress(done, total)`` after each
    student is sliced so a background caller can report incremental progress.
    """
    paper = config.get("paper_size", "A4")
    grid = grid_of(config)
    # Regions to crop per student: every question, plus the optional name box
    # under the reserved __name__ label (never a gradable question, so it stays
    # out of the question count but is sliced the same way).
    regions = [(q["label"], parse_range(q["range"], paper, grid))
               for q in config["questions"]]
    name_box = config.get("name_box")
    if name_box:
        regions.append((NAME_BOX_DIR, parse_range(name_box, paper, grid)))
    students = list_student_files(config["pdf_folder"])
    if not students:
        raise ValueError(f"No PDF/image files found in {config['pdf_folder']!r}.")

    exam_dir = os.path.join(output_root, _safe_name(config["name"]))
    summary = {"students": len(students), "questions": len(config["questions"]),
               "crops": 0, "errors": []}
    total = len(students)

    for done, (student, path) in enumerate(students, 1):
        pages = {}   # page number -> rendered PIL image, per student file
        for label, rng in regions:
            try:
                if rng["page"] not in pages:
                    pages[rng["page"]] = load_page_image(path, rng["page"])
                img = pages[rng["page"]]
                box = range_to_bbox(img.width, img.height, paper, rng, grid)
                q_dir = os.path.join(exam_dir, _safe_name(label))
                os.makedirs(q_dir, exist_ok=True)
                img.crop(box).save(
                    os.path.join(q_dir, _safe_name(student) + ".png"), "PNG")
                summary["crops"] += 1
            except Exception as e:      # keep slicing the rest of the class
                summary["errors"].append(f"{student} / {label}: {e}")
        pages.clear()
        if progress:
            progress(done, total)
    return summary


# --- Exam config + grade persistence -------------------------------------------
#
# Exam definitions live in gcg_exams.json beside app.py, keyed by class name:
#     {"classes": {"7A": {"Physics Midterm": {<config>}, ...}}}
# Grades for an exam live in exam_grades_<exam>.json inside the class output
# directory (the cloud-synced class folder when configured), shaped like:
#     {"students": {"Tanaka": {"scores": {"Q1": 2}, "comment": ""}}, ...}

_LOCK = threading.Lock()


def normalize_sections(raw_sections, questions):
    """Validate an exam's sections and pin every question to exactly one.

    ``questions`` is the already-cleaned question list; each may carry a
    ``"section"`` (a section name). Returns the cleaned ``[{"name", "required"}]``
    list and mutates each question's ``"section"`` in place to a valid name.

    Rules (Phase 4B):
      * Missing/empty sections -> one synthesized DEFAULT_SECTION_NAME section
        holding every question (``required`` None = all count). So **every exam
        always has ≥1 section.**
      * Section names must be unique and non-empty.
      * A question whose ``section`` is blank or names no known section falls
        into the first section (e.g. a question dragged above the first header).
      * ``required`` is None ("All") or an int with 1 ≤ required ≤ (number of
        questions actually in that section). An empty section forces None.
    """
    cleaned = []
    seen = set()
    for s in (raw_sections or []):
        name = str((s or {}).get("name", "")).strip()
        if not name:
            continue
        if name in seen:
            raise ValueError(f"Duplicate section name {name!r} — names must be unique.")
        seen.add(name)
        cleaned.append({"name": name, "required": (s or {}).get("required")})
    if not cleaned:
        cleaned = [{"name": DEFAULT_SECTION_NAME, "required": None}]

    valid_names = {s["name"] for s in cleaned}
    first = cleaned[0]["name"]
    for q in questions:
        if q.get("section") not in valid_names:
            q["section"] = first

    for s in cleaned:
        count = sum(1 for q in questions if q.get("section") == s["name"])
        req = s["required"]
        if req is None or (isinstance(req, str) and not req.strip()):
            s["required"] = None
            continue
        try:
            req = int(req)
        except (TypeError, ValueError):
            raise ValueError(
                f"Section {s['name']!r}: 'required' must be a whole number or blank.")
        if count == 0:
            s["required"] = None            # nothing to choose from -> all (none)
        elif not (1 <= req <= count):
            raise ValueError(
                f"Section {s['name']!r}: 'choose' must be between 1 and {count} "
                f"(it has {count} question(s)).")
        else:
            s["required"] = req
    return cleaned


def build_sidecar(config):
    """Build the definition sidecar (Phase 4C) written beside a routed exam CSV.

    The flat CSV can't express sections, so each routed exam export drops a
    ``<csv filename>.meta.json`` carrying the section structure, name-box flag,
    grid density and paper size. CAM reads it to recompute choice-section totals
    (Phase 5); its absence is tolerated (old all-questions-sum behaviour).

    Legacy configs saved before Phase 4 have no ``sections`` — synthesize a
    single DEFAULT_SECTION_NAME section holding every question so CAM always sees
    ≥1 section, mirroring ``normalize_sections``.
    """
    questions = config.get("questions") or []
    sections_cfg = config.get("sections") or []
    if not sections_cfg:
        sections_cfg = [{"name": DEFAULT_SECTION_NAME, "required": None}]
    valid = {s["name"] for s in sections_cfg}
    first = sections_cfg[0]["name"]
    by_section = {}
    for q in questions:
        sec = q.get("section")
        if sec not in valid:
            sec = first
        by_section.setdefault(sec, []).append(
            {"label": q["label"], "max": q["max"]})
    sections = [{"name": s["name"], "required": s.get("required"),
                 "questions": by_section.get(s["name"], [])}
                for s in sections_cfg]
    return {
        "exam": config.get("name", ""),
        "sections": sections,
        "has_name_box": bool(config.get("name_box")),
        "grid": grid_of(config),
        "paper_size": config.get("paper_size", "A4"),
    }


class ExamStore:
    """Owns gcg_exams.json (definitions) and per-exam grade files."""

    def __init__(self, base_dir):
        self.path = os.path.join(base_dir, "gcg_exams.json")

    def _read(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except (OSError, ValueError):
            data = {}
        classes = data.get("classes")
        return {"classes": classes if isinstance(classes, dict) else {}}

    def _write(self, data):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def list_exams(self, class_name):
        with _LOCK:
            return dict(self._read()["classes"].get(class_name or "", {}))

    def get_exam(self, class_name, exam_name):
        return self.list_exams(class_name).get(exam_name)

    def save_exam(self, class_name, config):
        """Validate + persist one exam definition under its class."""
        name = str(config.get("name", "")).strip()
        if not name:
            raise ValueError("The exam needs a name.")
        if config.get("paper_size") not in PAPER_SIZES_MM:
            raise ValueError("Paper size must be one of A4, A3, B5.")
        # Normalise the density (absent/garbage -> "legacy"); ranges are
        # validated against this paper size + density.
        grid = grid_of(config)
        # Optional handwritten-name capture region (Phase 4A). null/absent -> no
        # name box; a non-empty value is validated like any range.
        name_box_raw = config.get("name_box")
        name_box = None
        if name_box_raw not in (None, ""):
            name_box = str(name_box_raw).strip()
            parse_range(name_box, config["paper_size"], grid)
        questions = []
        for q in config.get("questions") or []:
            label = str(q.get("label", "")).strip()
            if not label:
                continue
            if label == NAME_BOX_DIR:
                raise ValueError(
                    f"{NAME_BOX_DIR!r} is a reserved name — pick another question label.")
            # Validate against the paper size + density grid (e.g. legacy A4
            # 10x15, compact A4 15x21, fine A3 30x42); raises a clear message.
            parse_range(q.get("range"), config["paper_size"], grid)
            questions.append({
                "label": label,
                "range": str(q.get("range", "")).strip(),
                "max": parse_max_score(q.get("max")),
                "section": str(q.get("section", "")).strip(),
            })
        if not questions:
            raise ValueError("Program at least one question before saving.")
        # Every exam ends up with ≥1 section; questions get pinned to one (Phase 4B).
        sections = normalize_sections(config.get("sections"), questions)
        clean = {
            "name": name,
            "paper_size": config["paper_size"],
            "grid": grid,
            "pdf_folder": str(config.get("pdf_folder", "")).strip(),
            "name_box": name_box,
            "sections": sections,
            "questions": questions,
        }
        with _LOCK:
            data = self._read()
            data["classes"].setdefault(class_name or "Unsorted", {})[name] = clean
            self._write(data)
        return clean


def exam_grades_path(output_dir, exam_name):
    return os.path.join(output_dir, f"exam_grades_{_safe_name(exam_name)}.json")


def load_exam_grades(output_dir, exam_name):
    """{student: {"scores": {label: int}, "comment": str}} or {}."""
    path = exam_grades_path(output_dir, exam_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
    except (OSError, ValueError):
        return {}
    students = data.get("students")
    return students if isinstance(students, dict) else {}


def save_exam_grades(output_dir, exam_name, students):
    os.makedirs(output_dir, exist_ok=True)
    path = exam_grades_path(output_dir, exam_name)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"students": students}, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)
