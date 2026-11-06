"""Student PDF reports and the Excel gradebook.

Run:  python -m unittest tests.test_reports
"""

import os
import tempfile
import unittest
from datetime import date
from unittest import mock

import pymupdf as fitz
from openpyxl import load_workbook

from engine import gradebook_xlsx, grading_summary as gs, model, reports, storage, workflow
from engine.errors import UserError
from engine.slicer import Layout
from tests.helpers import make_pdf

RED = (255, 0, 0)


class ReportTestCase(unittest.TestCase):
    mode = "marks"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        env = mock.patch.dict(os.environ, {"CAM2_APP_DATA": os.path.join(self.root, "appdata")})
        env.start()
        self.addCleanup(env.stop)
        scans = os.path.join(self.root, "scans")
        os.makedirs(scans)
        for name in ("Tanaka Hana.pdf", "Sato Ken.pdf", "scan_003.pdf", "scan_004.pdf"):
            make_pdf(os.path.join(scans, name), pages=2, fills={1: [(Layout("A4"), 2, 3, RED)]})
        self.session, self.config, self.grades = storage.create_session(
            os.path.join(self.root, "session"), "Y8: Science / Test")
        workflow.import_scans(self.session, self.config, {"type": "folder", "path": scans})
        workflow.set_mode(self.config, self.mode)
        if self.mode == "rubric":
            workflow.set_rubrics(self.config, [{"name": "Criterion A", "bands": [
                {"levels": "0", "descriptor": "Nothing yet."},
                {"levels": "1-2", "descriptor": "States facts."},
                {"levels": "3-4", "descriptor": "Explains with examples."}]}])
            questions = [{"id": "q1", "label": "Q1", "boxes": ["page1!C4"]},
                         {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"]}]
        else:
            questions = [{"id": "q1", "label": "Q1", "boxes": ["page1!C4"], "max": 5},
                         {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"], "max": 3},
                         {"id": "q3", "label": "Q3", "boxes": ["page2!C3"], "max": 3}]
        workflow.set_questions(self.config, {"name_box": ["page1!A1:B2"], "questions": questions,
                                             "choice_groups": [{"questions": ["q2", "q3"], "answer": 1}]
                                             if self.mode == "marks" else []})
        workflow.slice_session(self.session, self.config)
        # Papers sort as: Sato Ken, scan_003, scan_004, Tanaka Hana
        workflow.set_roster(self.config, [{"id": "n1", "name": "Hana Tanaka"},
                                          {"id": "n2", "name": "Ken Sato"}])

    def tearDown(self):
        self.tmp.cleanup()

    def text_of(self, path):
        with fitz.open(path) as doc:
            return "\n".join(page.get_text() for page in doc)


class MarksReportTests(ReportTestCase):
    def setUp(self):
        super().setUp()
        g = lambda sid, qid, v, c=None: gs.set_grade(self.config, self.grades, sid, qid, v, c)  # noqa: E731
        g("s001", "q1", 4, "Good use of evidence.")
        g("s001", "q2", 2)
        g("s001", "q3", 3)                         # choice: q3 counts, q2 doesn't
        g("s002", "q1", model.NOT_ANSWERED)
        gs.set_report_total(self.grades, "s001", 8)
        gs.set_overall_comment(self.grades, "s001", "A strong paper. 次も頑張りましょう。")

    def test_report_content(self):
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0],
                                  "en", path, day=date(2026, 10, 30))
        text = self.text_of(path)
        for expected in ("Y8: Science / Test", "Ken Sato", "30 October 2026", "8 / 8 · 100.0%",   # reported total
                         "Good use of evidence.", "A strong paper.", "次も頑張りましょう", "Not counted"):
            self.assertIn(expected, text)
        self.assertLess(os.path.getsize(path), 400_000)
        with fitz.open(path) as doc:          # one image per answer; no handwritten name crop
            self.assertEqual(sum(len(page.get_images()) for page in doc), 3)

    def test_teacher_picked_choice(self):
        self.config["choice_groups"][0]["pick"] = "teacher"
        path = os.path.join(self.root, "pick.pdf")

        def text():
            reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0],
                                      "en", path, day=date(2026, 10, 30))
            return " ".join(self.text_of(path).split())

        self.assertNotIn("Not counted", text())             # both answered: waiting for a pick
        gs.set_choice(self.config, self.grades, "s001", self.config["choice_groups"][0]["id"], ["q2"])
        self.assertIn("your teacher chose which answers count", text())

    def test_japanese_report(self):
        path = os.path.join(self.root, "ja.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][1],
                                  "ja", path, day=date(2026, 10, 30))
        text = self.text_of(path)
        for expected in ("2026年10月30日", "全体", "無回答", "未採点"):
            self.assertIn(expected, text)

    def test_export_names_and_errors(self):
        self.config["students"][2]["name"] = "Ken Sato"          # a second student with the same name
        real = reports.build_student_pdf

        def flaky(session, config, grades, student, language, out_path, day=None):
            if student["id"] == "s004":
                raise PermissionError("open in a PDF viewer")
            return real(session, config, grades, student, language, out_path, day)

        with mock.patch.object(reports, "build_student_pdf", side_effect=flaky):
            result = reports.export_student_pdfs(self.session, self.config, self.grades, "en")
        # s001 Sato Ken (class list), s002 scan_003 (no name), s003 typed "Ken Sato", s004 fails
        self.assertEqual(result["files"], ["Ken Sato_Y8_ Science _ Test.pdf",
                                           "UNMATCHED_scan_003.pdf",
                                           "Ken Sato_Y8_ Science _ Test (2).pdf"])
        self.assertEqual([e["student"] for e in result["errors"]], ["s004"])
        self.assertTrue(all(os.path.isfile(os.path.join(result["folder"], f)) for f in result["files"]))
        # Making them again replaces the old files rather than adding to them
        again = reports.export_student_pdfs(self.session, self.config, self.grades, "en")
        self.assertEqual(sorted(os.listdir(again["folder"])), sorted(again["files"]))
        self.assertIn("Hana Tanaka_Y8_ Science _ Test.pdf", again["files"])

    def test_gradebook(self):
        path = gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, "en")
        self.assertTrue(path.endswith("Y8_ Science _ Test_Master_Grades.xlsx"))
        wb = load_workbook(path)
        ws = wb["Grades & Comments"]
        header = [c.value for c in ws[1]]
        self.assertEqual(header[:5], ["No.", "Student", "Scan file", "Q1", "Q1 comment"])
        row = {h: c.value for h, c in zip(header, ws[2])}
        self.assertEqual((row["Student"], row["Q1"], row["Q1 comment"]), ("Ken Sato", 4, "Good use of evidence."))
        self.assertEqual((row["Calculated total"], row["Out of"], row["Total on report"]), (7, 8, 8))
        self.assertEqual((row["%"], row["% on report"]), (87.5, 100.0))
        self.assertEqual(row["Adjusted by teacher"], "Yes")
        for adjusted in ("Total on report", "% on report"):
            self.assertEqual(ws.cell(2, header.index(adjusted) + 1).fill.fgColor.rgb[-6:], "FFF2C2")
        self.assertFalse(any("marks" in str(h) or "weighted" in str(h) for h in header))     # one section: no columns
        row2 = {h: c.value for h, c in zip(header, ws[3])}
        self.assertEqual(row2["Q1"], "Not answered")
        labels = [ws.cell(r, 2).value for r in range(1, ws.max_row + 1)]
        self.assertIn("Class average", labels)
        ref = wb["Questions & Rubrics"]
        self.assertEqual(ref.cell(3, 4).value, "Answer 1 of Q2, Q3")

    def test_gradebook_open_in_excel(self):
        with mock.patch("openpyxl.Workbook.save", side_effect=PermissionError("locked")):
            with self.assertRaises(UserError) as ctx:
                gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, "en")
        self.assertEqual(ctx.exception.code, "report_file_open")


class RubricReportTests(ReportTestCase):
    mode = "rubric"

    def test_descriptor_final_level_and_japanese_gradebook(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 3, "Nice example.")
        gs.set_grade(self.config, self.grades, "s001", "q2", 4)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 3)
        workflow.set_report_options(self.config, {"overall_criteria": True})
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = self.text_of(path)
        for expected in ("Criterion A", "A3", "Explains with examples.", "Nice example.",
                         "States facts.", "Nothing yet."):           # the whole rubric, once
            self.assertIn(expected, text)
        self.assertEqual(text.count("Explains with examples."), 1)
        self.assertNotIn("· 3–4", text)
        wb = load_workbook(gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, "ja"))
        self.assertEqual(wb.sheetnames, ["成績・コメント一覧", "設問配点・ルーブリック基準"])
        ws = wb["成績・コメント一覧"]
        header = [c.value for c in ws[1]]
        row = {h: c.value for h, c in zip(header, ws[2])}
        self.assertEqual(row["Criterion A 最終レベル"], 3)
        self.assertNotIn("Criterion A 平均", header)
        for absent in ("計算上の合計", "レポートの%", "先生が調整"):     # no marks on this paper
            self.assertNotIn(absent, header)

    def test_a_final_level_prints_only_with_overall_criterion_results_on(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 3)
        gs.set_grade(self.config, self.grades, "s001", "q2", 3)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 2)
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        self.assertNotIn("2 / 4", self.text_of(path))
        workflow.set_report_options(self.config, {"overall_criteria": True})
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        self.assertIn("2 / 4", self.text_of(path))

    def test_a_final_level_left_blank_does_not_print(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 3)
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        self.assertNotIn("/ 4", self.text_of(path))
        self.assertNotIn("Final level", self.text_of(path))
        self.assertNotIn("—", self.text_of(path))


class MixedPaperReportTests(ReportTestCase):
    """Question by question, whatever was chosen first."""

    def setUp(self):
        super().setUp()
        workflow.set_rubrics(self.config, [{"name": "Criterion A", "bands": [
            {"levels": "0"}, {"levels": "1-4", "descriptor": "Explains with examples."}]}])
        self.config["questions"][1]["rubric_ids"] = ["r1"]
        self.config["questions"][1]["max"] = None
        self.config["questions"][2]["rubric_ids"] = ["r1"]
        self.config["choice_groups"] = []
        gs.set_grade(self.config, self.grades, "s001", "q1", 4)
        gs.set_grade(self.config, self.grades, "s001", "q2", 3)
        gs.set_grade(self.config, self.grades, "s001", "q3", 2)

    def test_report(self):
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = " ".join(self.text_of(path).split())
        for expected in ("Overall (marks questions)", "6 / 8", "75.0%", "Q1 4 / 5", "Q2 A3", "Q3 2 / 3",
                         "Explains with examples."):
            self.assertIn(expected, text)

    def test_gradebook(self):
        wb = load_workbook(gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, "en"))
        ws = wb["Grades & Comments"]
        row = {c.value: v.value for c, v in zip(ws[1], ws[2])}
        self.assertEqual((row["Q1"], row["Q2"], row["Q3"]), (4, 3, 2))
        self.assertEqual((row["Calculated total"], row["Out of"]), (6, 8))
        ref = wb["Questions & Rubrics"]
        self.assertEqual([ref.cell(r, 3).value for r in range(2, 5)], [5, "Criterion A", 3])

    def test_weighted_report_shows_only_the_percentage(self):
        self.config["sections"] = [{"id": "sec1", "name": ""}, {"id": "sec2", "name": ""}]
        self.config["questions"][0]["section_id"] = "sec1"
        self.config["questions"][1]["section_id"] = "sec2"
        self.config["questions"][2]["section_id"] = "sec2"
        workflow.set_weighted(self.config, True)
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = " ".join(self.text_of(path).split())
        self.assertIn("73.3%", text)                 # 4/5 at 50 + 2/3 at 50
        self.assertNotIn("6 / 8", text)


class MultiCriterionReportTests(ReportTestCase):
    mode = "rubric"

    def setUp(self):
        super().setUp()
        workflow.set_rubrics(self.config, self.config["rubrics"] + [{"name": "Criterion B", "bands": [
            {"levels": "0"}, {"levels": "1-8", "descriptor": "Designs a method."}]}])
        for q in self.config["questions"]:
            q["rubric_ids"] = ["r1", "r2"] if q["id"] == "q2" else ["r1"]
        g = lambda qid, v, rid=None: gs.set_grade(self.config, self.grades, "s001", qid, v, rubric_id=rid)  # noqa: E731
        g("q1", 2)
        g("q2", 4, "r1")
        g("q2", 7, "r2")
        gs.set_grade(self.config, self.grades, "s002", "q2", model.NOT_ANSWERED)

    def test_report_shows_each_criterion(self):
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = self.text_of(path)
        self.assertIn("A4 B7", " ".join(text.split()))
        self.assertIn("Designs a method.", text)
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][1], "en", path)
        text = self.text_of(path)
        self.assertIn("Not answered", text)
        self.assertNotIn("A Not answered", " ".join(text.split()))

    def test_gradebook_has_a_column_per_criterion(self):
        wb = load_workbook(gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, "en"))
        ws = wb["Grades & Comments"]
        header = [c.value for c in ws[1]]
        self.assertEqual(header[3:8], ["Q1", "Q1 comment", "Q2 · Criterion A", "Q2 · Criterion B", "Q2 comment"])
        row = {h: c.value for h, c in zip(header, ws[2])}
        self.assertEqual((row["Q2 · Criterion A"], row["Q2 · Criterion B"]), (4, 7))
        self.assertNotIn("Criterion A average", header)
        row2 = {h: c.value for h, c in zip(header, ws[3])}
        self.assertEqual(row2["Q2 · Criterion B"], "Not answered")
        averages = next(r for r in ws.iter_rows(values_only=True) if r[1] == "Class average")
        self.assertEqual(averages[header.index("Q2 · Criterion B")], 3.5)
        ref = wb["Questions & Rubrics"]
        self.assertEqual(ref.cell(3, 3).value, "Criterion A, Criterion B")


class SectionPaperTestCase(ReportTestCase):
    """A paper with two sections: q1 marks on Criterion A; q3 marks with no
    criterion; then q2 rubric on A and B."""

    BANDS = {"A": [("0", "A nothing."), ("1-4", "A some."), ("5-8", "A strong.")],
             "B": [("0", "B nothing."), ("1-8", "B method.")],
             "C": [("0", "C nothing."), ("1-8", "C never used.")]}

    def setUp(self):
        super().setUp()
        workflow.set_rubrics(self.config, [
            {"name": f"Criterion {name}", "bands": [{"levels": lv, "descriptor": d} for lv, d in bands]}
            for name, bands in self.BANDS.items()])
        workflow.set_questions(self.config, {
            "name_box": ["page1!A1:B2"],
            "sections": [{"id": "sec1", "name": "Knowledge"}, {"id": "sec2", "name": ""}],
            "questions": [
                {"id": "q1", "label": "Q1", "boxes": ["page1!C4"], "max": 5, "rubric_ids": ["r1"], "section_id": "sec1"},
                {"id": "q3", "label": "Q3", "boxes": ["page2!C3"], "max": 3, "section_id": "sec1"},
                {"id": "q2", "label": "Q2", "boxes": ["page2!A1:B2"], "rubric_ids": ["r1", "r2"], "section_id": "sec2"}]})
        self.give("s001", 4, 2, 6, 3)
        self.give("s002", 1, 3, 2, 7)

    def give(self, sid, q1, q3, q2a, q2b):
        gs.set_grade(self.config, self.grades, sid, "q1", q1)
        gs.set_grade(self.config, self.grades, sid, "q3", q3)
        gs.set_grade(self.config, self.grades, sid, "q2", q2a, rubric_id="r1")
        gs.set_grade(self.config, self.grades, sid, "q2", q2b, rubric_id="r2")

    def options(self, **change):
        workflow.set_report_options(self.config, change)

    def report(self, student=0, language="en"):
        path = os.path.join(self.root, f"report-{student}.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][student], language, path)
        return path

    def text(self, student=0, language="en"):
        return " ".join(self.text_of(self.report(student, language)).split())

    def images(self):
        with fitz.open(self.report()) as doc:
            return sum(len(page.get_images()) for page in doc)

    def shaded(self, path):
        """The text of every shaded band."""
        found = []
        with fitz.open(path) as doc:
            for page in doc:
                for drawing in page.get_drawings():
                    if drawing.get("fill") and all(abs(a - b) < 0.01 for a, b in zip(drawing["fill"], reports.AWARDED)):
                        found.append(page.get_textbox(drawing["rect"]).strip())
        return found


class ReportLayoutTests(SectionPaperTestCase):
    """The layout in Exam-Section-Plan.md section 6."""

    def test_each_grade_reaches_the_right_students_report(self):
        self.options(section_results=True, overall_criteria=True)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        gs.set_final_level(self.config, self.grades, "s002", "r1", 2)
        gs.set_overall_comment(self.grades, "s002", "Comment for the second paper.")
        first, second = self.text(0), self.text(1)
        self.assertIn("A6 B3", first)
        self.assertIn("A2 B7", second)
        self.assertIn("6 / 8 · 75.0%", first)
        self.assertIn("4 / 8 · 50.0%", second)
        self.assertIn("7 / 8", first.replace("6 / 8", ""))
        self.assertIn("2 / 8", second)
        self.assertNotIn("Comment for the second paper.", first)
        self.assertIn("Comment for the second paper.", second)

    def test_the_results_table_lists_sections_and_what_the_overall_covers(self):
        self.options(section_results=True)
        text = self.text()
        for expected in ("Results", "Section Result", "Knowledge 6 / 8 · 75.0%", "Section 2 Q2 A6 B3",
                         "Overall (Knowledge) 6 / 8 · 75.0%"):
            self.assertIn(expected, text)
        self.assertNotIn("Weighted marks", text)

    def test_without_section_results_only_the_overall_line_prints(self):
        text = self.text()
        self.assertIn("Overall (Knowledge) 6 / 8 · 75.0%", text)
        self.assertNotIn("Results", text)
        self.assertNotIn("Section Result", text)
        self.assertNotIn("Knowledge 6 / 8", text)      # not on the section heading either
        self.assertIn("Section 2", text)               # questions stay grouped

    def test_overall_marks_can_be_left_out(self):
        self.options(overall_marks=False)
        self.assertNotIn("6 / 8", self.text())

    def test_weighted_marks_print_only_with_weighting_on(self):
        self.give("s001", 5, 3, 6, 3)
        self.config["questions"].append({"id": "q9", "label": "Q9", "boxes": ["page1!C4"], "max": 10, "section_id": "sec2"})
        gs.set_grade(self.config, self.grades, "s001", "q9", 5)
        workflow.set_weighted(self.config, True)
        self.options(section_results=True)
        text = self.text()
        self.assertIn("Weighted marks", text)
        self.assertIn("50.0 / 50", text)               # all of Knowledge
        self.assertIn("25.0 / 50", text)               # half of the other section
        self.assertIn("75.0 / 100", text)
        self.assertNotIn("13 / 18", text)              # no total out of the paper's marks

    def test_only_criteria_this_exam_uses_are_printed(self):
        text = self.text()
        self.assertIn("A strong.", text)
        self.assertIn("B method.", text)
        self.assertNotIn("Criterion C", text)
        self.assertNotIn("C never used.", text)

    def test_blanks_do_not_print(self):
        self.options(overall_criteria=True)
        text = self.text()
        self.assertNotIn("Final level", text)
        self.assertNotIn("Overall comment", text)
        self.assertNotIn("Teacher’s comment", text)
        self.assertEqual(self.shaded(self.report()), [])

    def test_the_right_band_is_shaded(self):
        self.options(overall_criteria=True)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 3)
        gs.set_final_level(self.config, self.grades, "s001", "r2", 8)
        shaded = self.shaded(self.report())
        self.assertEqual(len(shaded), 4)                 # the levels cell and the words cell of each band
        self.assertTrue(any("A some." in text for text in shaded))
        self.assertTrue(any("B method." in text for text in shaded))
        self.assertFalse(any("A strong." in text for text in shaded))

    def test_a_final_level_needs_overall_criterion_results_on(self):
        gs.set_final_level(self.config, self.grades, "s001", "r1", 3)
        self.assertNotIn("Final level", self.text())
        self.assertEqual(self.shaded(self.report()), [])

    def test_the_criterion_box_gathers_marks_and_grades(self):
        self.options(overall_criteria=True)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        text = self.text()
        self.assertIn("Final level", text)
        self.assertIn("Marks: 4 / 5 · 80.0%", text)
        self.assertIn("Grades: A6", text)
        self.assertIn("Grades: B3", text)
        self.assertLess(text.index("Marks: 4 / 5"), text.index("Questions"))

    def test_the_boxes_print_on_their_own_with_the_table_off(self):
        self.options(overall_criteria=True, rubric_table=False)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        text = self.text()
        self.assertIn("Final level", text)
        self.assertIn("Grades: A6", text)
        self.assertNotIn("A strong.", text)

    def test_the_rubric_table_can_be_left_out(self):
        self.options(rubric_table=False)
        text = self.text()
        self.assertNotIn("A strong.", text)
        self.assertNotIn("Criterion A", text)

    def test_the_overall_comment_comes_after_the_rubrics(self):
        gs.set_overall_comment(self.grades, "s001", "Well done.")
        text = self.text()
        self.assertLess(text.index("A strong."), text.index("Well done."))
        self.assertLess(text.index("Well done."), text.index("Questions"))

    def test_images_can_be_turned_off_per_section(self):
        self.assertEqual(self.images(), 3)
        self.options(no_images_for=["sec1"])
        self.assertEqual(self.images(), 1)
        self.options(no_images_for=["sec1", "sec2"])
        self.assertEqual(self.images(), 0)
        text = self.text()
        self.assertIn("Q1 4 / 5", text)
        self.assertIn("Q3 2 / 3", text)
        self.assertIn("Q2 A6 B3", text)

    def test_images_off_on_a_paper_with_no_sections(self):
        workflow.set_questions(self.config, {"name_box": ["page1!A1:B2"], "sections": [], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!C4"], "max": 5}]})
        self.options(no_images_for=["sec1"])
        self.assertEqual(self.images(), 0)
        self.assertIn("Q1 4 / 5", self.text())

    def test_the_grid_gives_a_comment_its_own_row(self):
        self.options(no_images_for=["sec1", "sec2"])
        gs.set_grade(self.config, self.grades, "s001", "q3", 2, "Show your working.")
        text = self.text()
        self.assertIn("Q3 2 / 3", text)
        self.assertIn("Show your working.", text)

    def test_section_marks_show_on_the_heading_only_with_section_results_on(self):
        self.options(section_results=True)
        heading = self.text().split("Questions", 1)[1]
        self.assertIn("Knowledge", heading)
        self.assertIn("6 / 8 · 75.0%", heading)

    def test_japanese(self):
        self.options(section_results=True, overall_criteria=True)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        text = self.text(language="ja")
        for expected in ("結果", "セクション2", "全体（Knowledge）", "最終レベル", "設問"):
            self.assertIn(expected, text)

    def test_how_a_grade_names_its_criterion(self):
        for name, value, shown in (("Criterion B", 5, "B5"), ("基準B", 5, "B5"), ("B", 5, "B5"),
                                   ("Knowledge", 5, "Knowledge 5"), ("Plan A2", 5, "Plan A2 5")):
            self.assertEqual(reports._level_text({"name": name}, value, "en"), shown)
        self.assertEqual(reports._level_text({"name": "Criterion B"}, model.NOT_ANSWERED, "en"), "B Not answered")

    def test_a_rubric_too_long_for_one_page_still_prints_whole(self):
        long_words = "A long descriptor that carries on and on. " * 12
        workflow.set_rubrics(self.config, [{"name": "Criterion A", "bands": [
            {"levels": str(n), "descriptor": f"Band {n}. {long_words}"} for n in range(9)]}])
        self.options(overall_criteria=True)
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        path = self.report()
        with fitz.open(path) as doc:
            self.assertGreater(doc.page_count, 1)
            for page in doc:
                self.assertLessEqual(max(d["rect"].y1 for d in page.get_drawings()), reports.PAGE.height)
        text = " ".join(self.text_of(path).split())
        for n in range(9):
            self.assertIn(f"Band {n}.", text)
        self.assertIn("Final level", text)


class SectionGradebookTests(SectionPaperTestCase):
    """The gradebook on the same paper, with marks in both sections."""

    def setUp(self):
        super().setUp()
        self.config["questions"].append({"id": "q9", "label": "Q9", "boxes": ["page1!C4"], "max": 10, "section_id": "sec2"})
        workflow.set_weighted(self.config, False)
        gs.set_grade(self.config, self.grades, "s001", "q9", 5)
        gs.set_grade(self.config, self.grades, "s002", "q9", 10)

    def sheets(self, language="en"):
        wb = load_workbook(gradebook_xlsx.export_gradebook(self.session, self.config, self.grades, language))
        return wb.worksheets

    def rows(self, ws):
        """{student or statistic: {heading: value}} from the first sheet."""
        header = [c.value for c in ws[1]]
        return {row[1]: dict(zip(header, row)) for row in ws.iter_rows(min_row=2, values_only=True) if row[1]}

    def test_section_columns(self):
        rows = self.rows(self.sheets()[0])
        ken, other = rows["Ken Sato"], rows["scan_003"]
        self.assertEqual((ken["Knowledge marks"], ken["Knowledge %"]), (6, 75.0))
        self.assertEqual((ken["Section 2 marks"], ken["Section 2 %"]), (5, 50.0))
        self.assertEqual((other["Knowledge marks"], other["Section 2 marks"]), (4, 10))
        self.assertEqual((ken["Calculated total"], ken["Out of"], ken["%"], ken["% on report"]), (11, 18, 61.1, 61.1))
        self.assertNotIn("Knowledge weighted marks", ken)

    def test_class_statistics_for_each_section(self):
        rows = self.rows(self.sheets()[0])
        self.assertEqual(rows["Class average"]["Knowledge marks"], 5.0)
        self.assertEqual(rows["Highest"]["Knowledge marks"], 6)
        self.assertEqual(rows["Lowest"]["Knowledge marks"], 4)
        self.assertEqual(rows["Class average"]["Section 2 marks"], 7.5)
        self.assertEqual(rows["Highest"]["Calculated total"], 14)
        self.assertIsNone(rows["Highest"]["Out of"])
        self.assertIsNone(rows["Highest"]["Overall comment"])

    def test_weighted_columns_give_only_percentages_overall(self):
        workflow.set_weighted(self.config, True)
        ws = self.sheets()[0]
        rows = self.rows(ws)
        ken = rows["Ken Sato"]
        self.assertEqual((ken["Knowledge weighted marks"], ken["Section 2 weighted marks"]), (37.5, 25.0))
        self.assertEqual((ken["%"], ken["% on report"]), (62.5, 62.5))
        self.assertNotIn("Calculated total", ken)
        self.assertNotIn("Total on report", ken)
        self.assertEqual(rows["Highest"]["%"], 75.0)
        self.assertIsNone(rows["Highest"]["Adjusted by teacher"])
        gs.set_report_percent(self.grades, "s001", 70)
        ws = self.sheets()[0]
        header = [c.value for c in ws[1]]
        self.assertEqual(self.rows(ws)["Ken Sato"]["Adjusted by teacher"], "Yes")
        self.assertEqual(ws.cell(2, header.index("% on report") + 1).fill.fgColor.rgb[-6:], "FFF2C2")
        self.assertNotEqual(ws.cell(2, header.index("%") + 1).fill.fgColor.rgb[-6:], "FFF2C2")

    def test_final_levels_only_with_overall_criterion_results_on(self):
        gs.set_final_level(self.config, self.grades, "s001", "r1", 7)
        self.assertNotIn("Criterion A final level", self.rows(self.sheets()[0])["Ken Sato"])
        self.options(overall_criteria=True)
        rows = self.rows(self.sheets()[0])
        self.assertEqual(rows["Ken Sato"]["Criterion A final level"], 7)
        self.assertIsNone(rows["Ken Sato"]["Criterion B final level"])
        self.assertIsNone(rows["scan_003"]["Criterion A final level"])
        self.assertEqual(rows["Highest"]["Criterion A final level"], 7)
        self.assertNotIn("Criterion C final level", rows["Ken Sato"])     # not used on this paper

    def test_levels_stay_in_their_own_columns(self):
        rows = self.rows(self.sheets()[0])
        self.assertEqual((rows["Ken Sato"]["Q2 · Criterion A"], rows["Ken Sato"]["Q2 · Criterion B"]), (6, 3))
        self.assertEqual((rows["scan_003"]["Q2 · Criterion A"], rows["scan_003"]["Q2 · Criterion B"]), (2, 7))
        self.assertEqual(rows["Ken Sato"]["Section 2 marks"], 5)      # the Q2 levels aren't added

    def test_a_section_with_only_rubric_questions_gets_no_columns(self):
        self.config["questions"].pop()
        header = [c.value for c in self.sheets()[0][1]]
        self.assertNotIn("Knowledge marks", header)
        self.assertNotIn("Section 2 marks", header)
        self.assertIn("Calculated total", header)

    def test_the_second_sheet_lists_the_sections(self):
        workflow.set_section_weight(self.config, "sec1", 30)
        workflow.set_weighted(self.config, True)
        ref = self.sheets()[1]
        rows = [list(r) for r in ref.iter_rows(values_only=True)]
        at = rows.index(["Section", "Questions", "Out of", "Share of the paper (%)"])
        self.assertEqual(rows[at + 1], ["Knowledge", "Q1, Q3", 8, 30])
        self.assertEqual(rows[at + 2], ["Section 2", "Q2, Q9", 10, 70])

    def test_the_second_sheet_without_weighting_or_sections(self):
        rows = [list(r) for r in self.sheets()[1].iter_rows(values_only=True)]
        self.assertTrue(any(r[:3] == ["Section", "Questions", "Out of"] and r[3] is None for r in rows))
        workflow.set_questions(self.config, {"name_box": ["page1!A1:B2"], "sections": [], "questions": [
            {"id": "q1", "label": "Q1", "boxes": ["page1!C4"], "max": 5}]})
        rows = [list(r) for r in self.sheets()[1].iter_rows(values_only=True)]
        self.assertFalse(any(r[0] == "Section" for r in rows))

    def test_japanese_headings(self):
        workflow.set_weighted(self.config, True)
        header = [c.value for c in self.sheets("ja")[0][1]]
        for heading in ("Knowledge 点数", "セクション2 点数", "セクション2 比重をかけた点数", "レポートの%"):
            self.assertIn(heading, header)


class ReportKindsTests(ReportTestCase):
    def test_a_marks_exam_prints_no_rubric_or_section_parts(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 4)
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = " ".join(self.text_of(path).split())
        self.assertIn("Overall 4 / 8 · 50.0%", text)
        for absent in ("Results", "Section", "Final level", "Rubric", "Overall comment"):
            self.assertNotIn(absent, text)

    def test_a_preview_is_the_same_report_and_leaves_no_file(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 4)
        data = reports.preview_pdf(self.session, self.config, self.grades, self.config["students"][0], "en")
        self.assertTrue(data.startswith(b"%PDF"))
        with fitz.open(stream=data, filetype="pdf") as doc:
            self.assertIn("Ken Sato", doc[0].get_text())
        self.assertFalse(os.path.exists(self.session.path(storage.REPORTS_DIR)))


class RubricOnlyReportTests(ReportTestCase):
    mode = "rubric"

    def test_a_rubric_exam_has_no_overall_line(self):
        gs.set_grade(self.config, self.grades, "s001", "q1", 3)
        path = os.path.join(self.root, "r.pdf")
        reports.build_student_pdf(self.session, self.config, self.grades, self.config["students"][0], "en", path)
        text = " ".join(self.text_of(path).split())
        self.assertNotIn("Overall", text)
        self.assertIn("A3", text)


if __name__ == "__main__":
    unittest.main()
