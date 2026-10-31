"""Builders for test scans. Nothing here touches real student data."""

import pymupdf as fitz
from PIL import Image

POINTS_PER_MM = 72 / 25.4
A4_POINTS = (210 * POINTS_PER_MM, 297 * POINTS_PER_MM)


def make_pdf(path, pages=1, size=A4_POINTS, fills=None):
    """A PDF whose pages are blank except for coloured grid cells.

    ``fills`` maps page number -> [(layout, col, row, rgb)], painting the cell
    (0-based col/row) of that layout's grid so crops can be checked by colour.
    """
    fills = fills or {}
    doc = fitz.open()
    try:
        for p in range(1, pages + 1):
            page = doc.new_page(width=size[0], height=size[1])
            for layout, col, row, rgb in fills.get(p, []):
                w, h = size[0] / layout.cols, size[1] / layout.rows
                rect = fitz.Rect(col * w, row * h, (col + 1) * w, (row + 1) * h)
                page.draw_rect(rect, color=None, fill=tuple(c / 255 for c in rgb))
        doc.save(path)
    finally:
        doc.close()
    return path


def make_image(path, size_px=(1654, 2339), dpi=None, color="white"):
    img = Image.new("RGB", size_px, color)
    if dpi:
        img.save(path, dpi=(dpi, dpi))
    else:
        img.save(path)
    return path


def center_color(img):
    return img.getpixel((img.width // 2, img.height // 2))
