"""
Exam Slicing engine for Criterion Assessment Metrics (CAM).

Turns a folder of scanned student exam PDFs into per-question crop images so
the main grading UI can grade one question across every student at a time.

The teacher programs an exam once in the /exam_setup screen: each question is
a label ("Q1"), a grid coordinate range ("page2!A2:C5") and a max score. The
coordinate system is a paper-size-dependent grid laid over the physical page,
tuned so every cell is roughly 2cm x 2cm of real paper: A4 is 10x15, B5 is
9x12 and A3 is 15x21 (columns lettered left to right, rows numbered top to
bottom) — so a range describes a rectangle of the paper independent of scan
resolution.

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

# Grid dimensions per paper size, chosen so one cell is ~2cm x 2cm of paper:
#   A4: 210/10 = 21.0mm x 297/15 = 19.8mm
#   B5: 176/9 ≈ 19.6mm x 250/12 ≈ 20.8mm
#   A3: 297/15 = 19.8mm x 420/21 = 20.0mm
PAPER_GRIDS = {
    "A4": (10, 15),
    "B5": (9, 12),
    "A3": (15, 21),
}

# Column letters sized for the widest grid (A3's 15 columns = A..O).
COL_LETTERS = "ABCDEFGHIJKLMNO"


def grid_for(paper_size):
    """(cols, rows) of the coordinate grid for one paper size (A4 fallback)."""
    return PAPER_GRIDS.get(paper_size, PAPER_GRIDS["A4"])


# DPI used when rasterising a PDF page. Crop geometry is derived from the
# resulting pixel size via the auto-DPI formula, so this only affects quality.
RENDER_DPI = 200

# Accepts "page2!A2:C5", "A2:C5" (page 1 implied) and a single cell "B7".
# The letter class spans the widest grid (A..O); parse_range then validates
# the cell against the actual grid of the exam's paper size.
_RANGE_RE = re.compile(
    r"^\s*(?:page\s*(\d+)\s*!\s*)?"
    r"([A-Oa-o])\s*(\d{1,2})"
    r"(?:\s*:\s*([A-Oa-o])\s*(\d{1,2}))?\s*$"
)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def parse_range(raw, paper_size="A4"):
    """Parse a grid range string into its page + cell rectangle.

    Returns {"page": 1-based page, "c1", "r1", "c2", "r2"} with 0-based
    inclusive column/row indices, normalised so c1<=c2 and r1<=r2.
    Raises ValueError on anything malformed or outside the paper size's grid
    (e.g. A1..J15 for A4, A1..O21 for A3, A1..I12 for B5).
    """
    cols, rows = grid_for(paper_size)
    m = _RANGE_RE.match(str(raw or ""))
    if not m:
        raise ValueError(
            f"Bad coordinate range {raw!r} — expected e.g. 'A2:C5' or 'page2!A2:C5'."
        )
    page = int(m.group(1)) if m.group(1) else 1
    c1 = COL_LETTERS.index(m.group(2).upper())
    r1 = int(m.group(3)) - 1
    if m.group(4):
        c2 = COL_LETTERS.index(m.group(4).upper())
        r2 = int(m.group(5)) - 1
    else:
        c2, r2 = c1, r1
    if not (0 <= c1 < cols and 0 <= c2 < cols):
        raise ValueError(
            f"Column out of range in {raw!r} (columns are A-"
            f"{COL_LETTERS[cols - 1]} on {paper_size}).")
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


def range_to_bbox(img_w, img_h, paper_size, rng):
    """Translate a parsed grid range into a pixel bounding box on one image.

    The physical cell size (paper_mm / grid count) is converted to pixels via
    the per-axis auto-calculated DPI, then the inclusive cell rectangle
    [c1..c2] x [r1..r2] becomes (left, top, right, bottom), clamped to the
    image bounds.
    """
    paper_w_mm, paper_h_mm = PAPER_SIZES_MM.get(paper_size, PAPER_SIZES_MM["A4"])
    grid_cols, grid_rows = grid_for(paper_size)
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
        {"name", "paper_size", "pdf_folder",
         "questions": [{"label", "range", "max"}, ...]}

    Saves crops to  <output_root>/<Exam Name>/<Q label>/<Student>.png  and
    returns a summary {students, questions, crops, errors:[...]}.

    ``progress``, if given, is called ``progress(done, total)`` after each
    student is sliced so a background caller can report incremental progress.
    """
    paper = config.get("paper_size", "A4")
    questions = [(q["label"], parse_range(q["range"], paper))
                 for q in config["questions"]]
    students = list_student_files(config["pdf_folder"])
    if not students:
        raise ValueError(f"No PDF/image files found in {config['pdf_folder']!r}.")

    exam_dir = os.path.join(output_root, _safe_name(config["name"]))
    summary = {"students": len(students), "questions": len(questions),
               "crops": 0, "errors": []}
    total = len(students)

    for done, (student, path) in enumerate(students, 1):
        pages = {}   # page number -> rendered PIL image, per student file
        for label, rng in questions:
            try:
                if rng["page"] not in pages:
                    pages[rng["page"]] = load_page_image(path, rng["page"])
                img = pages[rng["page"]]
                box = range_to_bbox(img.width, img.height, paper, rng)
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
        questions = []
        for q in config.get("questions") or []:
            label = str(q.get("label", "")).strip()
            if not label:
                continue
            # Validate against the paper size's own grid (A4 10x15, B5 9x12,
            # A3 15x21); raises with a clear message.
            parse_range(q.get("range"), config["paper_size"])
            questions.append({
                "label": label,
                "range": str(q.get("range", "")).strip(),
                "max": parse_max_score(q.get("max")),
            })
        if not questions:
            raise ValueError("Program at least one question before saving.")
        clean = {
            "name": name,
            "paper_size": config["paper_size"],
            "pdf_folder": str(config.get("pdf_folder", "")).strip(),
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
