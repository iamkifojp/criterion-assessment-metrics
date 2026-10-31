"""PDF display selections, page rendering and bounded cache housekeeping
(originals stay intact)."""
from pathlib import Path
import io
import os
import re

from PIL import Image

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}

# DPI used when rasterising a PDF page before it is downscaled for display.
RENDER_DPI = 200


# PyMuPDF (fitz) is only needed to rasterise PDFs. Import it lazily so the whole
# grading workspace — including Google Drive sign-in, which needs no PDF
# handling — still boots when PyMuPDF isn't installed. Only the PDF code paths
# then fail, and with a message that names the fix.
def fitz_module():
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        raise RuntimeError(
            "PyMuPDF is required to read PDF files but is not installed — "
            "run: pip install PyMuPDF"
        ) from exc
    return fitz


def load_page_image(path, page_number):
    """Return one page of a PDF or image file as a Pillow RGB image (1-based).

    PDFs are rasterised at RENDER_DPI; image files ignore the page number
    beyond page 1. Raises ValueError for a page that doesn't exist.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        with fitz_module().open(path) as doc:
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


def page_ranges(text):
    text = str(text or "").strip()
    if not text:
        return []
    ranges = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*([1-9]\d*)\s*(?:[-–]\s*([1-9]\d*)\s*)?", part)
        if not match:
            raise ValueError("Use page numbers or ranges, such as 1-9, 12, 15-17.")
        first, last = int(match[1]), int(match[2] or match[1])
        if last < first:
            raise ValueError("Page ranges must run forwards, such as 1-9.")
        ranges.append((first, last))
    return ranges


def visible_pages(count, omitted):
    ranges = page_ranges(omitted)
    return [p for p in range(1, count + 1)
            if not any(first <= p <= last for first, last in ranges)]


def prune_pdf_cache(folder, keep, budget=256 * 1024 * 1024):
    """Cap downloaded copies; retain the active PDF even if it alone exceeds cap.

    Only our cache's PDFs are removed, never submissions or backup files.
    """
    try:
        files = sorted(Path(folder).glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= budget:
                break
            if path == Path(keep):
                continue
            size = path.stat().st_size
            path.unlink()
            total -= size
    except OSError:
        pass  # concurrent cache readers/deletions must not block the viewer
