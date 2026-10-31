"""Make fake scanned exam papers for trying CAM2 out. All names are made up.

    python tools/make_sample_scans.py <output folder> [--students 8] [--paper A4]

Creates in the output folder:
    papers/          one PDF per student (2 pages each), named like a scanner would
    combined.pdf     the same papers in one PDF, as from a photocopier
    booklets_A3.pdf  the papers as 4-page booklets printed on A3, unstapled and
                     scanned open, 2-sided; the third student's sheet went
                     through upside down and the fifth student's inside first
    late_student.pdf one more paper, from a student who sat the exam late
    class_list.xlsx  a class list with separate family / given name columns

Each paper has a name box, three answer boxes and a page-2 question. Every
paper is shifted by a few millimetres, like real scans, so the "check on
other papers" strip has something to show.
"""

from __future__ import annotations

import argparse
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pymupdf as fitz  # noqa: E402
from openpyxl import Workbook  # noqa: E402

from engine.slicer import PAPER_SIZES_MM  # noqa: E402

NAMES = [("Tanaka", "Hana"), ("Sato", "Ken"), ("Suzuki", "Yui"), ("Ito", "Mei"),
         ("Watanabe", "Sora"), ("Yamamoto", "Riku"), ("Nakamura", "Aoi"), ("Kobayashi", "Haruto"),
         ("Kato", "Rin"), ("Yoshida", "Daiki"), ("Yamada", "Mio"), ("Sasaki", "Yuto")]
ANSWERS = ["Photosynthesis makes glucose.", "The moon reflects sunlight.", "Water boils at 100 C.",
           "Plants need light, water and CO2.", "Gravity pulls objects down.", "I am not sure."]
MM = 72 / 25.4


def draw_paper(doc, size_mm, family, given, rng):
    w, h = size_mm[0] * MM, size_mm[1] * MM
    dx, dy = rng.uniform(-3, 3) * MM, rng.uniform(-3, 3) * MM     # scan offset

    def rect(x0, y0, x1, y1):
        return fitz.Rect(x0 * MM + dx, y0 * MM + dy, x1 * MM + dx, y1 * MM + dy)

    page = doc.new_page(width=w, height=h)
    page.insert_text((20 * MM + dx, 18 * MM + dy), "Y8 Science Midterm", fontsize=16)
    page.draw_rect(rect(20, 24, 100, 38), color=(0, 0, 0), width=0.8)
    page.insert_text((22 * MM + dx, 28 * MM + dy), "Name:", fontsize=8)
    page.insert_text((36 * MM + dx, 34 * MM + dy), f"{given} {family}", fontsize=15, fontname="tiro",
                     color=(0.1, 0.1, 0.5))
    for i, top in enumerate((50, 110, 170), 1):
        page.insert_text((20 * MM + dx, (top - 3) * MM + dy), f"Q{i}. Explain your answer.", fontsize=11)
        page.draw_rect(rect(20, top, 190, top + 45), color=(0.4, 0.4, 0.4), width=0.6)
        page.insert_text((25 * MM + dx, (top + 12) * MM + dy), rng.choice(ANSWERS), fontsize=13,
                         fontname="tiro", color=(0.1, 0.1, 0.5))
    page2 = doc.new_page(width=w, height=h)
    page2.insert_text((20 * MM + dx, 18 * MM + dy), "Q4. Draw and label a cell.", fontsize=11)
    page2.draw_rect(rect(20, 24, 190, 140), color=(0.4, 0.4, 0.4), width=0.6)
    page2.draw_circle(fitz.Point(100 * MM + dx, 80 * MM + dy), rng.uniform(25, 40) * MM, color=(0.1, 0.1, 0.5))


def booklet_sides(out, paper, flipped=False, inside_first=False):
    """Add a 2-page paper as a 4-page booklet (back pages blank) printed on
    one sheet of twice the size, scanned open: outside 4|1, inside 2|3
    (the other way round if ``inside_first``)."""
    w, h = paper[0].rect.width, paper[0].rect.height
    blank = fitz.open()
    blank.new_page(width=w, height=h)
    faces = ((None, 0), (1, None))
    for left, right in (faces[::-1] if inside_first else faces):
        side = out.new_page(width=2 * w, height=h)
        for x, pno in ((0, left), (w, right)):
            if flipped:          # upside down: the halves change places too
                x = w - x
            rect = fitz.Rect(x, 0, x + w, h)
            src, n = (paper, pno) if pno is not None else (blank, 0)
            side.show_pdf_page(rect, src, n, rotate=180 if flipped else 0)
    blank.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--students", type=int, default=8)
    parser.add_argument("--paper", default="A4", choices=sorted(PAPER_SIZES_MM))
    args = parser.parse_args(argv)
    rng = random.Random(7)
    size = PAPER_SIZES_MM[args.paper]
    papers = os.path.join(args.out, "papers")
    os.makedirs(papers, exist_ok=True)
    combined, booklets = fitz.open(), fitz.open()
    chosen = NAMES[:args.students]
    for i, (family, given) in enumerate(chosen, 1):
        doc = fitz.open()
        draw_paper(doc, size, family, given, rng)
        # Some files are named after the student, some like a scanner would
        name = f"{given}_{family}.pdf" if i % 3 else f"SCAN_{i:04d}.pdf"
        doc.save(os.path.join(papers, name))
        combined.insert_pdf(doc)
        booklet_sides(booklets, doc, flipped=(i == 3), inside_first=(i == 5))
        doc.close()
    combined.save(os.path.join(args.out, "combined.pdf"))
    combined.close()
    booklets.save(os.path.join(args.out, "booklets_A3.pdf"))
    booklets.close()
    late = fitz.open()
    family, given = NAMES[len(chosen) % len(NAMES)]
    draw_paper(late, size, family, given, rng)
    late.save(os.path.join(args.out, "late_student.pdf"))
    late.close()
    wb = Workbook()
    wb.active.append(["No.", "Family name", "Given name", "Email"])
    for i, (family, given) in enumerate(chosen, 1):
        wb.active.append([i, family, given, f"{given.lower()}@example.com"])
    wb.save(os.path.join(args.out, "class_list.xlsx"))
    print(f"Made {len(chosen)} papers in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
