"""Turning scans into one PDF per paper, in reading order.

Scans arrive as one or more PDFs of the whole class, a folder of page photos,
or one file per student. Each may hold plain pages, or folded booklets scanned
open (two booklet pages side by side on every scanned side). This module plans
how the scanned pages become papers, writes one PDF per paper, previews the
first paper, and rewrites papers when the teacher fixes pages on the
scan-check screen.

A page is described by a :class:`Ref` (which file, which page, how far to turn
it), so a whole class can be planned and checked before anything is written.
"""

from __future__ import annotations

import io
import os
from typing import Iterable, List, NamedTuple, Optional, Sequence, Tuple

from PIL import Image, ImageOps

from .errors import UserError
from .slicer import PDF_EXT, _fitz, page_count

PHOTO_MAX_PX = 2400       # phone photos are cut down to about 200 dpi on A4
ASSUMED_DPI = 200         # for pictures that don't say
BOOKLET_STEP = 4          # a folded sheet carries four booklet pages


class Ref(NamedTuple):
    """One page to put into a paper.

    ``path`` is the source file ("" for a blank page of ``size`` points),
    ``page`` is 0-based, and ``turn`` is an extra clockwise turn in degrees.
    """

    path: str
    page: int = 0
    turn: int = 0
    size: Optional[Tuple[float, float]] = None

    def turned(self, degrees: int) -> "Ref":
        return self._replace(turn=(self.turn + degrees) % 360)


def blank_ref(width: float, height: float) -> Ref:
    return Ref("", 0, 0, (float(width), float(height)))


# --- Opening sources ---------------------------------------------------------------

def _image_pdf(path: str, max_px: Optional[int]):
    """A picture as a one-page PDF, upright (phone orientation applied)."""
    fitz = _fitz()
    with Image.open(path) as im:
        dpi = im.info.get("dpi") or (0, 0)
        im = ImageOps.exif_transpose(im)
        im = im.convert("L" if im.mode in ("1", "L", "LA") else "RGB")
    try:
        dpi = float(dpi[0]) if float(dpi[0]) >= 50 else ASSUMED_DPI
    except (TypeError, ValueError, IndexError):
        dpi = ASSUMED_DPI
    if max_px and max(im.size) > max_px:
        scale = max_px / max(im.size)
        im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                       Image.LANCZOS)
        dpi *= scale
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85, optimize=True)
    doc = fitz.open()
    page = doc.new_page(width=im.width * 72 / dpi, height=im.height * 72 / dpi)
    page.insert_image(page.rect, stream=buf.getvalue())
    return doc


class Sources:
    """Open source files once and close them all at the end (``with``)."""

    def __init__(self, photo_max: Optional[int] = None):
        self.photo_max = photo_max
        self._docs: dict = {}

    def get(self, path: str):
        if path not in self._docs:
            if os.path.splitext(path)[1].lower() == PDF_EXT:
                self._docs[path] = _fitz().open(path)
            else:
                self._docs[path] = _image_pdf(path, self.photo_max)
        return self._docs[path]

    def upright(self, path: str, page: int):
        """A one-page copy with the page's rotation baked into its content, so
        it can be clipped in the coordinates it is seen in."""
        key = (path, page)
        if key not in self._docs:
            doc = _fitz().open()
            doc.insert_pdf(self.get(path), from_page=page, to_page=page)
            doc[0].remove_rotation()
            self._docs[key] = doc
        return self._docs[key]

    def close(self) -> None:
        for doc in self._docs.values():
            doc.close()
        self._docs.clear()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def stream_refs(paths: Sequence[str]) -> List[Ref]:
    """Every page of every file, in order, as one long stack."""
    refs = []
    for path in paths:
        n = page_count(path)
        if n < 1:
            raise UserError("pdf_empty", file=os.path.basename(path))
        refs.extend(Ref(path, p) for p in range(n))
    return refs


def visual_size(sources: Sources, ref: Ref) -> Tuple[float, float]:
    """Width and height (points) of a page as it will be shown."""
    if not ref.path:
        w, h = ref.size
    else:
        rect = sources.get(ref.path)[ref.page].rect      # rotation applied
        w, h = rect.width, rect.height
    return (h, w) if ref.turn % 180 else (w, h)


# --- Booklets ----------------------------------------------------------------------

def booklet_layout(sides: int) -> List[Tuple[int, str]]:
    """Reading order of a booklet scanned open, one (side, half) per page.

    Sides are scanned sheet by sheet, outside then inside. For an 8-page
    booklet (2 sheets) the sides hold 8|1, 2|7, 6|3 and 4|5. A short last
    paper (``sides`` not a whole number of sheets) simply skips what is missing.
    """
    sheets = (int(sides) + 1) // 2
    n = sheets * BOOKLET_STEP
    where = {}
    for i in range(sheets):
        outside, inside = 2 * i, 2 * i + 1
        where[n - 2 * i] = (outside, "left")
        where[2 * i + 1] = (outside, "right")
        where[2 * i + 2] = (inside, "left")
        where[n - 2 * i - 1] = (inside, "right")
    return [where[p] for p in range(1, n + 1) if where[p][0] < sides]


def booklet_side(page: int, sides: int) -> int:
    """Which scanned side (0-based) a booklet page (1-based) came from."""
    layout = booklet_layout(sides)
    if not 1 <= page <= len(layout):
        raise UserError("page_missing", file="", page=page, pages=len(layout))
    return layout[page - 1][0]


def swap_sheets(sides: Sequence[Ref], swapped: Iterable[int]) -> List[Ref]:
    """Sides with the two faces of each listed sheet exchanged (a sheet that
    went through the scanner face down)."""
    out = list(sides)
    for sheet in swapped:
        a, b = 2 * int(sheet), 2 * int(sheet) + 1
        if b < len(out):
            out[a], out[b] = out[b], out[a]
    return out


def arrange_sides(sides: Sequence[Ref], reverse: bool = False,
                  swapped: Iterable[int] = ()) -> List[Ref]:
    """Scanned sides in booklet order (outside sheet first, outer face first).

    ``reverse``: the booklet was opened and stacked as it lay, so its inside
    sheet came first, inner face up; reading the sides backwards undoes that.
    ``swapped``: sheets (counted from the outside) whose faces are exchanged.
    """
    return swap_sheets(list(sides)[::-1] if reverse else list(sides), swapped)


def scanned_side(index: int, sides: int, reverse: bool) -> int:
    """Where side ``index`` of the arranged booklet sits in the scan."""
    return sides - 1 - index if reverse else index


def _half_clip(w: float, h: float, k: int, half: str):
    """Where one half of the open sheet is on the stored (unrotated) page,
    when the sheet is stored turned ``k`` degrees clockwise."""
    fitz = _fitz()
    first, second = ((fitz.Rect(0, 0, w / 2, h), fitz.Rect(w / 2, 0, w, h)) if k % 180 == 0
                     else (fitz.Rect(0, 0, w, h / 2), fitz.Rect(0, h / 2, w, h)))
    if k in (180, 270):
        first, second = second, first
    return first if half == "left" else second


def _add_half(out, sources: Sources, ref: Ref, half: str) -> None:
    """Add one half of an open sheet as an upright page."""
    doc, pno = sources.get(ref.path), ref.page
    if doc[pno].rotation:
        doc, pno = sources.upright(ref.path, ref.page), 0
    w, h = doc[pno].rect.width, doc[pno].rect.height
    # How far the sheet is turned as it appears: a sideways (portrait) scan is
    # taken as a quarter turn; the teacher's turn is added on top.
    k = ((0 if w >= h else 90) + ref.turn) % 360
    sw, sh = (w, h) if k % 180 == 0 else (h, w)
    new = out.new_page(width=sw / 2, height=sh)
    new.show_pdf_page(new.rect, doc, pno, clip=_half_clip(w, h, k, half), rotate=k)


# --- Writing papers ----------------------------------------------------------------

def _add_page(out, sources: Sources, ref: Ref) -> None:
    if not ref.path:
        out.new_page(width=ref.size[0], height=ref.size[1])
        return
    out.insert_pdf(sources.get(ref.path), from_page=ref.page, to_page=ref.page)
    if ref.turn:
        page = out[-1]
        page.set_rotation((page.rotation + ref.turn) % 360)


def build_pages(sources: Sources, refs: Sequence[Ref]):
    """A new PDF (in memory) holding these pages."""
    out = _fitz().open()
    for ref in refs:
        _add_page(out, sources, ref)
    return out


def build_booklet(sources: Sources, sides: Sequence[Ref]):
    """A new PDF (in memory) with an open-scanned booklet's pages in order."""
    out = _fitz().open()
    for side, half in booklet_layout(len(sides)):
        _add_half(out, sources, sides[side], half)
    return out


def save(doc, dest: str) -> str:
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    doc.save(dest, garbage=3, deflate=True)
    return dest


# --- Planning an import ---------------------------------------------------------------

STREAM_TYPES = ("combined", "photos")


def source_paths(source: dict) -> List[str]:
    """The files a source names: ``paths`` (or the older single ``path``)."""
    paths = source.get("paths")
    if not paths:
        paths = [source.get("path")] if source.get("path") else []
    return [str(p) for p in paths if p]


def plan_papers(source: dict, files: Sequence[str]) -> List[dict]:
    """Group the scanned pages into papers.

    ``files`` are the source files in order (the PDFs of a combined scan, the
    photos, or one file per student). Returns ``[{"sides": [Ref], "source":
    label}]``; for a booklet the refs are scanned sides, otherwise pages.
    """
    booklet = source.get("layout") == "booklet"
    if source.get("type") in STREAM_TYPES:
        per = int(source.get("pages_per_student") or 0)
        check_pages_per_student(per, booklet)
        size = per // 2 if booklet else per
        refs = stream_refs(files)
        label = os.path.basename(files[0]) if files else ""
        groups = [refs[i:i + size] for i in range(0, len(refs), size)]
        papers = [{"sides": g, "source": f"{label} · {i}"} for i, g in enumerate(groups, 1)]
    else:
        papers = [{"sides": stream_refs([f]), "source": os.path.basename(f)} for f in files]
    if booklet:
        fronts, backs = bool(source.get("flip_fronts")), bool(source.get("flip_backs"))
        for paper in papers:
            paper["turns"] = [180 if (fronts if i % 2 == 0 else backs) else 0
                              for i in range(len(paper["sides"]))]
            paper["reversed"] = bool(source.get("inside_first"))
    return papers


def check_pages_per_student(per: int, booklet: bool) -> None:
    if per < 1:
        raise UserError("pages_per_student_invalid")
    if booklet and per % BOOKLET_STEP:
        raise UserError("booklet_pages_invalid", pages=per)


def paper_pages(source: dict, sides: int) -> int:
    """Pages a paper of ``sides`` scanned pages becomes."""
    return len(booklet_layout(sides)) if source.get("layout") == "booklet" else sides


def build_paper(sources: Sources, source: dict, paper: dict):
    """One planned paper as an in-memory PDF, as it will be imported."""
    if source.get("layout") == "booklet":
        sides = [ref.turned(t) for ref, t in zip(paper["sides"], paper.get("turns") or [])]
        return build_booklet(sources, arrange_sides(sides, paper.get("reversed")))
    return build_pages(sources, paper["sides"])


def preview_first_paper(source: dict, files: Sequence[str], width: int = 180,
                        max_pages: int = 32) -> dict:
    """Small pictures of the first paper as it will be imported, so the
    teacher can see that pages are in order and the right way up."""
    from .slicer import detect_paper_mm
    papers = plan_papers(source, files)
    if not papers:
        raise UserError("no_scans_found", folder="")
    photo_max = PHOTO_MAX_PX if source.get("type") == "photos" else None
    images = []
    with Sources(photo_max) as sources:
        doc = build_paper(sources, source, papers[0])
        try:
            rect = doc[0].rect
            detected = detect_paper_mm(rect.width * 25.4 / 72, rect.height * 25.4 / 72)
            for page in list(doc)[:max_pages]:
                zoom = width / max(page.rect.width, 1)
                pix = page.get_pixmap(matrix=_fitz().Matrix(zoom, zoom))
                images.append(pix.tobytes("jpeg", jpg_quality=75))
            pages = doc.page_count
        finally:
            doc.close()
    return {"images": images, "pages": pages, "papers": len(papers),
            "paper": detected[0] if detected else None,
            "landscape": detected[1] if detected else False}
