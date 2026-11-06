"""The master Excel gradebook: the teacher's permanent record of the exam.

Sheet 1, "Grades & Comments": one row per paper with every question's grade
and comment, each section's marks and percentage when two or more sections have
marks (and its weighted marks with weighting on), the calculated result *and*
the result on the report (with an "adjusted" flag where the teacher overrode
it), final levels with Overall criterion results on, the overall comment, and
class average / highest / lowest rows at the bottom. Rubric levels are never
added to marks. With weighting on, only percentages are given overall, because a
total out of the paper's marks would not agree with them.

Sheet 2, "Questions & Rubrics": each question's boxes, marks or rubric and
choice group, then the sections, then every rubric's levels and descriptors, so
the file explains itself years later.

All numbers are values worked out by grading_summary (no Excel formulas), so
the file always matches what CAM2 showed, including its rounding.
"""

from __future__ import annotations

import os

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import grading_summary, i18n, model, rubrics, slicer, storage
from .errors import UserError

HEADER_FILL = PatternFill("solid", fgColor="DCE6FA")
ADJUSTED_FILL = PatternFill("solid", fgColor="FFF2C2")
UNGRADED_FILL = PatternFill("solid", fgColor="FDE2E0")
SUMMARY_FILL = PatternFill("solid", fgColor="EEF1F6")
BOLD = Font(bold=True)
WRAP = Alignment(wrap_text=True, vertical="top")
TOP = Alignment(vertical="top")
STATS = (("average", "average"), ("max_row", "max"), ("min_row", "min"))


def gradebook_path(session: storage.Session, config: dict) -> str:
    name = f"{slicer.safe_filename(config['exam_name'], 'Exam')}_Master_Grades.xlsx"
    return session.path(f"{storage.REPORTS_DIR}/{name}")


def build_workbook(config: dict, grades: dict, language: str) -> Workbook:
    from .workflow import display_name, report_options     # avoid an import cycle
    t = lambda key, **kw: i18n.t(key, language, **kw)      # noqa: E731
    summary = grading_summary.class_summary(config, grades)
    questions = config.get("questions") or []
    rubric_list = config.get("rubrics") or []
    rubric_names = {r["id"]: r["name"] for r in rubric_list}
    na_text = t("grade.not_answered")
    # Per question: its grade columns (one per criterion it is assessed on), then its comment.
    marks_q = {q["id"] for q in questions if grading_summary.question_mode(config, q) == "marks"}
    q_rids = {q["id"]: ([None] if q["id"] in marks_q
                        else grading_summary.question_rubric_ids(config, q)) for q in questions}
    used = {rid for q in questions for rid in grading_summary.question_rubric_ids(config, q)}
    used_rubrics = [r for r in rubric_list if r["id"] in used]
    final_rubrics = used_rubrics if report_options(config)["overall_criteria"] else []
    weighted = grading_summary.weighting_on(config)
    with_marks = grading_summary.sections_with_marks(config)
    section_cols = with_marks if len(with_marks) >= 2 else []
    stored_ids = [s["id"] for s in config.get("sections") or []]

    def section_name(section):
        return section["name"] or t("step2.sections.default_name", n=stored_ids.index(section["id"]) + 1)

    wb = Workbook()
    ws = wb.active
    ws.title = t("xlsx.sheet_grades")[:31]

    header = [t("xlsx.no"), t("xlsx.student"), t("xlsx.scan_file")]
    comment_cols = set()
    for q in questions:
        rids = q_rids[q["id"]]
        header += [q["label"] if len(rids) < 2 else t("xlsx.criterion_for", label=q["label"],
                                                        name=rubric_names[rid]) for rid in rids]
        header.append(t("xlsx.comment_for", label=q["label"]))
        comment_cols.add(len(header))
    for section in section_cols:
        name = section_name(section)
        header += [t("xlsx.section_marks", name=name), t("xlsx.section_percent", name=name)]
        if weighted:
            header.append(t("xlsx.section_weighted", name=name))
    if marks_q:
        header += ([] if weighted else [t("xlsx.total"), t("xlsx.max")]) + [t("xlsx.percent")]
        header += ([] if weighted else [t("xlsx.report_total")]) + [t("xlsx.report_percent"), t("xlsx.adjusted")]
    header += [t("xlsx.final_for", name=r["name"]) for r in final_rubrics]
    header += [t("xlsx.overall_comment"), t("xlsx.complete")]
    ws.append(header)
    for cell in ws[1]:
        cell.font = BOLD
        cell.fill = HEADER_FILL
        cell.alignment = WRAP

    entries_all = grades.get("grades") or {}
    for i, (student, res) in enumerate(zip(config.get("students") or [], summary["students"]), 1):
        entries = entries_all.get(student["id"]) or {}
        row = [i, display_name(config, student), student.get("source") or student.get("file")]
        ungraded_cols = []
        for q in questions:
            entry = entries.get(q["id"]) or {}
            for rid in q_rids[q["id"]]:
                value = grading_summary.level_of(config, entry, q, rid)
                if value is None:
                    ungraded_cols.append(len(row) + 1)
                row.append(na_text if value == model.NOT_ANSWERED else value)
            row.append(entry.get("comment") or None)
        by_section = {s["id"]: s for s in res["sections"]}
        for section in section_cols:
            result = by_section[section["id"]]
            row += [result["total"], result["percent"]] + ([result["weighted_marks"]] if weighted else [])
        adjusted_cols = []
        if marks_q:
            m = res["marks"]
            row += ([] if weighted else [m["total"], m["max"]]) + [m["percent"]]
            row += ([] if weighted else [m["report_total"]]) + [m["report_percent"]]
            if m["adjusted"]:
                adjusted_cols = [len(row)] if weighted else [len(row) - 1, len(row)]
            row.append(t("xlsx.yes") if m["adjusted"] else None)
        row += [res["rubrics"][r["id"]]["final"] for r in final_rubrics]
        row += [res["comment"] or None, t("xlsx.yes") if res["complete"] else t("xlsx.no_answer")]
        ws.append(row)
        r_idx = ws.max_row
        for col in ungraded_cols:
            ws.cell(r_idx, col).fill = UNGRADED_FILL
        for col in adjusted_cols:
            ws.cell(r_idx, col).fill = ADJUSTED_FILL
        for cell in ws[r_idx]:
            cell.alignment = WRAP if isinstance(cell.value, str) and len(cell.value) > 20 else TOP

    # Class average / highest / lowest
    ws.append([])
    stats_rows = {key: [None, t(f"xlsx.{key}"), None] for key, _ in STATS}

    def add_stats(st, blanks=0):
        """One statistics cell in each row, then empty cells for the columns beside it."""
        for key, field in STATS:
            stats_rows[key] += [st[field] if st else None] + [None] * blanks

    for q in questions:
        for rid in q_rids[q["id"]]:
            add_stats(summary["questions"].get(grading_summary.slot_key(q["id"], rid)))
        add_stats(None)                                    # its comment
    for section in section_cols:
        add_stats(summary["sections"].get(section["id"]), blanks=2 if weighted else 1)
    if marks_q:
        if weighted:
            add_stats(summary["overall"].get("percent"), blanks=2)
        else:
            add_stats(summary["overall"].get("total"), blanks=5)
    for r in final_rubrics:
        add_stats(summary["overall"].get(r["id"]))
    for key, _ in STATS:
        ws.append(stats_rows[key])
        for cell in ws[ws.max_row]:
            cell.fill = SUMMARY_FILL
            cell.font = BOLD

    widths = {1: 5, 2: 24, 3: 20}
    for col in range(1, ws.max_column + 1):
        title = str(ws.cell(1, col).value or "")
        is_comment = col in comment_cols
        ws.column_dimensions[get_column_letter(col)].width = widths.get(
            col, 36 if is_comment or col == ws.max_column - 1 else max(10, min(len(title) + 2, 22)))
    ws.freeze_panes = "C2"

    # Sheet 2: questions and rubrics --------------------------------------------------------
    ref = wb.create_sheet(t("xlsx.sheet_reference")[:31])
    rubric_q = any(q["id"] not in marks_q for q in questions)
    third_title = " / ".join(([t("xlsx.max")] if marks_q else []) + ([t("xlsx.rubric")] if rubric_q else []))
    ref.append([t("xlsx.question"), t("xlsx.boxes"), third_title, t("xlsx.choice")])
    groups = {qid: g for g in config.get("choice_groups") or [] for qid in g["questions"]}
    labels = {q["id"]: q["label"] for q in questions}
    for q in questions:
        g = groups.get(q["id"])
        choice = (t("xlsx.choice_text" if grading_summary.group_pick(g) == grading_summary.PICK_BEST
                    else "xlsx.choice_text_teacher", answer=g["answer"],
                    questions=", ".join(labels.get(x, x) for x in g["questions"])) if g else None)
        if q["id"] in marks_q:
            third = q.get("max")
        else:
            third = ", ".join(rubric_names[rid] for rid in q_rids[q["id"]]) or None
        ref.append([q["label"], ", ".join(q.get("boxes") or []), third, choice])
    for cell in ref[1]:
        cell.font = BOLD
        cell.fill = HEADER_FILL
    if stored_ids:
        ref.append([])
        ref.append([t("xlsx.section"), t("xlsx.questions"), t("xlsx.max")] + ([t("xlsx.share")] if weighted else []))
        for cell in ref[ref.max_row]:
            cell.font = BOLD
            cell.fill = HEADER_FILL
        for section in grading_summary.sections(config):
            maximum = grading_summary.marks_maximum(config, section["questions"]) or None
            ref.append([section_name(section), ", ".join(q["label"] for q in section["questions"]), maximum]
                       + ([section["weight"]] if weighted else []))
    if used_rubrics:
        ref.append([])
        ref.append([t("xlsx.rubric"), t("xlsx.levels"), t("xlsx.descriptor")])
        for cell in ref[ref.max_row]:
            cell.font = BOLD
            cell.fill = HEADER_FILL
        for r in used_rubrics:
            for band in r["bands"]:
                ref.append([r["name"], band["levels"], band.get("descriptor") or None])
                ref.cell(ref.max_row, 3).alignment = WRAP
            ref.append([t("xlsx.rubric_max", name=r["name"], max=rubrics.rubric_max(r))])
    ref.column_dimensions["A"].width = 24
    ref.column_dimensions["B"].width = 34
    ref.column_dimensions["C"].width = 60
    ref.column_dimensions["D"].width = 34
    return wb


def export_gradebook(session: storage.Session, config: dict, grades: dict, language: str) -> str:
    path = gradebook_path(session, config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wb = build_workbook(config, grades, language)
    tmp = path + ".tmp"
    try:
        wb.save(tmp)
        os.replace(tmp, path)
    except PermissionError as exc:      # the gradebook is open in Excel
        raise UserError("report_file_open", file=os.path.basename(path)) from exc
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return path
