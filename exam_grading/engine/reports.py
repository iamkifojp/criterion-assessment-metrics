"""One PDF report per student, in English or Japanese.

Each report has:
  * a header: exam name, date, student name, and the result — the total
    (``34 / 40 · 85%``) or the final level for each rubric — with a
    one-line-per-question summary and the overall comment;
  * the rubric(s), once, so descriptors are not repeated under every answer;
  * every question in order, one row each: the label, the answer image and,
    beside it (never on top of the student's writing), the grade — followed
    only by the teacher's comment.

The result shown is the *reported* one: a teacher's override replaces the
calculated total or level here (and only here; see grading_summary).

Layout is drawn with PyMuPDF. Text goes through ``insert_htmlbox`` so long
Japanese or English text wraps properly; Japanese uses MuPDF's built-in CJK
font, and fonts are subset before saving, so a report stays small enough to
email (tens of kB plus the answer images).
"""

from __future__ import annotations

import html
import io
import os
from datetime import date
from typing import Callable, List, Optional

import pymupdf as fitz
from PIL import Image

from . import grading_summary, i18n, model, rubrics, slicer, storage
from .errors import UserError

PAGE = fitz.paper_rect("a4")
MARGIN = 42
CONTENT_W = PAGE.width - 2 * MARGIN
FOOTER_H = 24
IMAGE_MAX_H = 330           # points; taller answers are scaled down
LABEL_W = 44                # question label column, left of the answer
GRADE_W = 76                # grade column, right of the answer
IMAGE_MAX_W = CONTENT_W - LABEL_W - GRADE_W
IMAGE_MAX_PX = 1400         # answer images are resized to this width before embedding
JPEG_QUALITY = 82
GAP = 10

INK = (0.106, 0.133, 0.188)
MUTED = (0.42, 0.45, 0.52)
FRAME = (0.80, 0.82, 0.86)

CSS = """
* { font-family: sans-serif; color: #1b2230; font-size: 10pt; line-height: 1.4; }
h1 { font-size: 17pt; margin: 0; }
h2 { font-size: 13pt; margin: 0; }
.big { font-size: 15pt; font-weight: bold; }
.muted { color: #6b7385; font-size: 9pt; }
.label { color: #6b7385; font-size: 8.5pt; }
p { margin: 0 0 3pt 0; }
"""
GRADE_CSS = CSS + """
.grade { font-size: 18pt; font-weight: bold; color: #14734a; line-height: 1.1; }
.of { font-size: 10pt; color: #6b7385; }
"""


def _e(text) -> str:
    return html.escape(str(text if text is not None else ""))


class _Writer:
    """A cursor that flows blocks down A4 pages, starting new pages as needed."""

    def __init__(self, doc, footer: str):
        self.doc = doc
        self.footer = footer
        self.page = None
        self.y = 0.0
        self.new_page()

    @property
    def bottom(self) -> float:
        return PAGE.height - MARGIN - FOOTER_H

    def new_page(self):
        self.page = self.doc.new_page(width=PAGE.width, height=PAGE.height)
        self.y = MARGIN

    def html(self, text: str, width: float = CONTENT_W, x: float = MARGIN, gap: float = GAP) -> float:
        """Write wrapped HTML at the cursor; returns the height used."""
        for attempt in range(2):
            rect = fitz.Rect(x, self.y, x + width, self.bottom)
            spare, _ = self.page.insert_htmlbox(rect, text, css=CSS, scale_low=1)
            if spare >= 0:
                used = rect.height - spare
                self.y += used + gap
                return used
            if attempt == 0 and self.y > MARGIN + 1:
                self.new_page()                       # try again on a fresh page
        # Longer than a whole page: let it shrink to fit one.
        rect = fitz.Rect(x, self.y, x + width, self.bottom)
        self.page.insert_htmlbox(rect, text, css=CSS, scale_low=0)
        self.y = self.bottom + gap
        return rect.height

    def at(self, rect: fitz.Rect, text: str, css: str = CSS, shrink: bool = False):
        """Write HTML in a fixed box beside the flow; the cursor does not move."""
        self.page.insert_htmlbox(rect, text, css=css, scale_low=0 if shrink else 1)

    def ensure(self, height: float):
        if self.y + height > self.bottom and self.y > MARGIN + 1:
            self.new_page()

    def finish(self):
        total = self.doc.page_count
        for i, page in enumerate(self.doc, 1):
            rect = fitz.Rect(MARGIN, PAGE.height - MARGIN - 12, PAGE.width - MARGIN, PAGE.height - MARGIN + 6)
            page.insert_htmlbox(rect, f"<p class='muted'>{_e(self.footer)} · {i} / {total}</p>",
                                css=CSS + " p { text-align: right; }")


# --- Images --------------------------------------------------------------------------

def _jpeg(path: str):
    """(jpeg bytes, width px, height px) of an image, resized for embedding."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        if im.width > IMAGE_MAX_PX:
            ratio = IMAGE_MAX_PX / im.width
            im = im.resize((IMAGE_MAX_PX, max(1, int(im.height * ratio))), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return buf.getvalue(), im.width, im.height


def _fit(w_px: int, h_px: int, max_w: float, max_h: float):
    scale = min(max_w / w_px, max_h / h_px)
    return w_px * scale, h_px * scale


# --- Words -----------------------------------------------------------------------------

def _value_text(value, out_of, language: str) -> str:
    if value is None:
        return i18n.t("report.not_graded", language)
    if value == model.NOT_ANSWERED:
        return i18n.t("grade.not_answered", language)
    return f"{value} / {out_of}"


def _grades(config: dict, grades: dict, student_id: str, question: dict) -> List[tuple]:
    """(criterion name or None, value, out of) for each grade a question has.

    The name is given only when the question is assessed on several criteria.
    """
    values = grading_summary.question_values(config, grades, student_id, question)
    if config.get("mode") != "rubric":
        return [(None, values[None], question.get("max"))]
    by_id = {r["id"]: r for r in config.get("rubrics") or []}
    named = len(values) > 1
    return [(by_id[rid]["name"] if named else None, value, rubrics.rubric_max(by_id[rid]))
            for rid, value in values.items()]


def _all_not_answered(parts: List[tuple]) -> bool:
    return all(value == model.NOT_ANSWERED for _, value, _ in parts)


def _result_text(parts: List[tuple], language: str) -> str:
    """One question's line in the result box, e.g. ``Criterion B 5 / 8 · Criterion C 4 / 8``."""
    if len(parts) > 1 and _all_not_answered(parts):
        return i18n.t("grade.not_answered", language)
    return " · ".join(f"{name} {_value_text(value, top, language)}" if name
                      else _value_text(value, top, language) for name, value, top in parts)


def _grade_html(config: dict, parts: List[tuple], language: str) -> str:
    """The grade beside an answer: just the level, or marks over the maximum.
    A question assessed on several criteria shows each level under its name."""
    if len(parts) > 1 and _all_not_answered(parts):
        parts = parts[:1]
    out = []
    for name, value, top in parts:
        if name and not (len(parts) == 1 and value == model.NOT_ANSWERED):
            out.append(f"<p class='label'>{_e(name)}</p>")
        if value is None or value == model.NOT_ANSWERED:
            out.append(f"<p class='muted'>{_e(_value_text(value, top, language))}</p>")
        elif config.get("mode") == "rubric":
            out.append(f"<p class='grade'>{_e(value)}</p>")
        else:
            out.append(f"<p class='grade'>{_e(value)}<span class='of'> / {_e(top)}</span></p>")
    return "".join(out)


def _format_date(day: date, language: str) -> str:
    return f"{day.year}年{day.month}月{day.day}日" if language == "ja" else day.strftime("%d %B %Y").lstrip("0")


# --- One student ----------------------------------------------------------------------------

def build_student_pdf(session: storage.Session, config: dict, grades: dict, student: dict,
                      language: str, out_path: str, day: Optional[date] = None) -> str:
    from .workflow import display_name                    # avoid an import cycle
    t = lambda key, **kw: i18n.t(key, language, **kw)     # noqa: E731
    name = display_name(config, student)
    summary = grading_summary.student_summary(config, grades, student["id"])
    entries = (grades.get("grades") or {}).get(student["id"]) or {}
    in_group = {qid for g in config.get("choice_groups") or [] for qid in g["questions"]}

    doc = fitz.open()
    w = _Writer(doc, f"{config['exam_name']} · {name}")

    # Header ---------------------------------------------------------------------------
    w.html(f"<h1>{_e(config['exam_name'])}</h1>"
           f"<p class='muted'>{_e(_format_date(day or date.today(), language))}</p>", gap=4)
    w.html(f"<p class='label'>{_e(t('report.student'))}</p><h2>{_e(name)}</h2>", gap=GAP)

    # Result box
    if config.get("mode") == "rubric":
        lines = []
        for r in config.get("rubrics") or []:
            res = summary["rubrics"][r["id"]]
            top = rubrics.rubric_max(r)
            final = res["final"] if res["final"] is not None else "—"
            lines.append(f"<p><b>{_e(r['name'])}</b>&nbsp;&nbsp;&nbsp;<span class='big'>{_e(final)} / {top}</span></p>")
        result_html = "".join(lines)
    else:
        marks = summary["marks"]
        reported = marks["report_total"]
        percent = (grading_summary.round_half_up(reported * 100 / marks["max"], 1)
                   if marks["max"] else None)
        pct = f" · {percent:g}%" if percent is not None else ""
        result_html = (f"<p class='label'>{_e(t('report.total'))}</p>"
                       f"<p class='big'>{_e(reported)} / {marks['max']}{pct}</p>")
    rows = []
    counted = summary["counted"]
    for q in config.get("questions") or []:
        parts = _grades(config, grades, student["id"], q)
        text = _result_text(parts, language)
        if q["id"] in in_group and q["id"] not in summary["ungraded"] and q["id"] not in counted:
            text += f" ({t('report.not_counted')})"
        # (MuPDF ignores table column widths, so simple lines rather than a table)
        rows.append(f"<p><b>{_e(q['label'])}</b>&nbsp;&nbsp;&nbsp;{_e(text)}</p>")
    box_top, box_page = w.y, w.page
    w.y += 8
    w.html(f"<p class='label'>{_e(t('report.result'))}</p>{result_html}", x=MARGIN + 10, width=CONTENT_W - 20, gap=4)
    w.html("".join(rows), x=MARGIN + 10, width=CONTENT_W - 20, gap=8)
    if w.page is box_page:                  # only frame the box if it stayed on one page
        w.page.draw_rect(fitz.Rect(MARGIN, box_top, PAGE.width - MARGIN, w.y), color=(0.84, 0.86, 0.9),
                         width=0.8, radius=0.04)
    w.y += GAP

    overall = ((grades.get("overall") or {}).get(student["id"]) or {}).get("comment", "").strip()
    if overall:
        w.html(f"<p class='label'>{_e(t('report.overall_comment'))}</p><p>{_e(overall)}</p>", gap=GAP * 1.5)

    # The rubric, once, for the student to refer to -----------------------------------
    if config.get("mode") == "rubric":
        used = {rid for q in config.get("questions") or []
                for rid in grading_summary.question_rubric_ids(config, q)}
        for r in config.get("rubrics") or []:
            bands = [b for b in r.get("bands") or [] if str(b.get("descriptor") or "").strip()]
            if r["id"] not in used or not bands:
                continue
            lines = "".join(f"<p><b>{_e(t('report.descriptor', levels=b['levels']))}</b>&nbsp;&nbsp;"
                            f"{_e(b['descriptor'])}</p>" for b in reversed(bands))
            w.ensure(60)
            w.html(f"<p class='label'>{_e(t('report.rubric'))}</p><h2>{_e(r['name'])}</h2>{lines}",
                   gap=GAP * 1.5)

    # Questions: label | answer | grade, then the comment ------------------------------
    for q in config.get("questions") or []:
        entry = entries.get(q["id"]) or {}
        parts = _grades(config, grades, student["id"], q)
        crop = session.path(f"{storage.CROPS_DIR}/{q['id']}/{student['id']}.png")
        image = _jpeg(crop) if os.path.isfile(crop) else None
        img_w, img_h = _fit(image[1], image[2], IMAGE_MAX_W, IMAGE_MAX_H) if image else (0, 0)
        row_h = max(img_h, 28)
        w.ensure(row_h)
        top, x_img = w.y, MARGIN + LABEL_W
        w.at(fitz.Rect(MARGIN, top, x_img - 6, top + row_h), f"<h2>{_e(q['label'])}</h2>", shrink=True)
        if image:
            rect = fitz.Rect(x_img, top, x_img + img_w, top + img_h)
            w.page.insert_image(rect, stream=image[0])
            w.page.draw_rect(rect, color=FRAME, width=0.8)
        x_grade = x_img + img_w + 10
        w.at(fitz.Rect(x_grade, top, x_grade + GRADE_W, top + row_h),
             _grade_html(config, parts, language), css=GRADE_CSS, shrink=True)
        w.y = top + row_h + 4
        notes = []
        if q["id"] in in_group and q["id"] not in summary["ungraded"] and q["id"] not in counted:
            notes.append(f"<p class='muted'>{_e(t('report.not_counted_long'))}</p>")
        comment = str(entry.get("comment") or "").strip()
        if comment:
            notes.append(f"<p><span class='label'>{_e(t('report.comment'))}{'：' if language == 'ja' else ':'}</span> {_e(comment)}</p>")
        if notes:
            w.html("".join(notes), x=x_img, width=CONTENT_W - LABEL_W, gap=0)
        w.y += GAP * 1.4

    w.finish()
    doc.subset_fonts()
    doc.save(out_path, garbage=4, deflate=True)
    doc.close()
    return out_path


# --- The whole class -------------------------------------------------------------------------

def report_filename(config: dict, student: dict, taken: set) -> str:
    """'<Student Name>_<Exam Name>.pdf'.

    With a class list, a paper not matched to it is marked UNMATCHED_ so it
    is never sent to the wrong person. Without a class list the paper's own
    name is used, since the scans are often already named after students.
    """
    from .workflow import display_name
    exam = slicer.safe_filename(config["exam_name"], "Exam")
    named = bool(student.get("roster_id") or str(student.get("name") or "").strip()
                 or not config.get("roster"))
    if named:
        base = f"{slicer.safe_filename(display_name(config, student))}_{exam}"
    else:
        base = f"UNMATCHED_{slicer.safe_filename(os.path.splitext(student.get('source') or student['file'])[0])}"
    return slicer.unique_name(base[:150] + ".pdf", taken)


def student_pdfs_dir(session: storage.Session) -> str:
    return session.path(f"{storage.REPORTS_DIR}/student_pdfs")


def export_student_pdfs(session: storage.Session, config: dict, grades: dict, language: str,
                        progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Write every student's report into reports/student_pdfs/ (replacing old ones).

    A file that can't be written (e.g. open in a PDF viewer) is reported in
    ``errors`` and the rest of the class still gets their reports.
    """
    out_dir = student_pdfs_dir(session)
    if os.path.isdir(out_dir):
        for name in os.listdir(out_dir):
            if name.lower().endswith(".pdf"):
                try:
                    os.remove(os.path.join(out_dir, name))
                except OSError:
                    pass
    os.makedirs(out_dir, exist_ok=True)
    taken: set = set()
    files: List[str] = []
    errors: List[dict] = []
    students = config.get("students") or []
    for i, student in enumerate(students, 1):
        filename = report_filename(config, student, taken)
        path = os.path.join(out_dir, filename)
        try:
            build_student_pdf(session, config, grades, student, language, path)
            files.append(filename)
        except Exception as exc:                  # keep going for the rest of the class
            errors.append({"student": student["id"], "file": filename, "error": str(exc)})
        if progress:
            progress(i, len(students))
    return {"folder": out_dir, "files": files, "errors": errors}


def check_writable_file(path: str) -> None:
    """Raise a friendly error if a report file is open in another program."""
    if os.path.exists(path):
        try:
            with open(path, "ab"):
                pass
        except PermissionError as exc:
            raise UserError("report_file_open", file=os.path.basename(path)) from exc
