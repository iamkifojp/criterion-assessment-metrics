"""Fictional fixtures for CAM's Phase 4 browser checks. Every name is made up.

Run inside the sandbox, with the sandbox's Python:

    python make_fixtures.py sessions <cam2 folder> <class exams folder> [case ...]
    python make_fixtures.py slides <output folder>
    python make_fixtures.py draft <master folder>

``sessions`` builds CAM2 session folders with CAM2's own engine (from
``<cam2 folder>``), as if a teacher had graded them and clicked Send to CAM.
With no cases it builds every case except ``v1start`` and ``v1finish``:

    marks rubric onecrit critmarks mixed_m mixed_r weighted choice

``v1start`` must use the previous CAM2 (``git archive 1a40845`` of the CAM2
repo) to make a version 1 session; ``v1finish`` then finishes it on the new
CAM2, which upgrades it to version 2.

``slides`` writes a 16:9 deck per student (two slides each) for a real run
through CAM2's screens. ``draft`` writes ``<master>/Poster draft/<student>/``
folders for the grading workspace.

The students match the fictional "Class 1" in the tracked acm_database.json.
See README.md here for the checks and the expected results.
"""

import os
import sys

ROSTER = [("100001", "Alex Rivera"), ("100002", "Sam Chen"), ("100003", "Jordan Okafor"),
          ("100004", "Priya Sharma"), ("100005", "Liam O'Brien"), ("100006", "Mia Tanaka"),
          ("100007", "Noah Williams"), ("100008", "Emma Costa")]
NA = "not_answered"
DEFAULT_CASES = ["marks", "rubric", "onecrit", "critmarks", "mixed_m", "mixed_r",
                 "weighted", "choice"]


# --------------------------------------------------------------------------
# CAM2 sessions


def sessions(cam2, exams, cases):
    sys.path.insert(0, cam2)
    from engine import storage, grading_summary as gs, rubrics as rb  # noqa: E402

    def q(qid, label, mx, rids=None, section=None):
        out = {"id": qid, "label": label, "boxes": [], "max": mx}
        if rids:
            out["rubric_ids"] = rids
        if section:
            out["section_id"] = section
        return out

    def rubric(rid, name, top=8):
        raw = {"id": rid, "name": name, "bands": [{"levels": "0"}, {"levels": f"1–{top}"}]}
        return dict(rb.normalize_rubric(raw), id=rid)

    def make(name, *, mode, questions, rubrics=(), groups=(), grades=(), overall=None,
             extra=None):
        folder = os.path.join(exams, name)
        session, config, data = storage.create_session(folder, name)
        config.update(mode=mode, questions=list(questions), rubrics=list(rubrics),
                      choice_groups=list(groups),
                      roster=[{"id": f"n{i+1:03}", "name": n, "external_id": k}
                              for i, (k, n) in enumerate(ROSTER)],
                      students=[{"id": f"s{i+1:03}", "scan": f"scans/s{i+1:03}.pdf",
                                 "source": f"{ROSTER[i][1]}.pdf", "pages": 1,
                                 "roster_id": f"n{i+1:03}"} for i in range(len(ROSTER))],
                      host_ready_at="2026-11-06T03:00:00+00:00", **(extra or {}))
        for sid, qid, value, *rest in grades:
            gs.set_grade(config, data, sid, qid, value,
                         comment=rest[1] if len(rest) > 1 else None,
                         rubric_id=rest[0] if rest else None)
        for sid, more in (overall or {}).items():
            data.setdefault("overall", {}).setdefault(sid, {}).update(more)
        session.config_file.save(config)
        session.grades_file.save(data)
        print("made", folder)

    def case_marks():
        qs = [q("q1", "Q1", 5), q("q2", "Q2", 5), q("q3", "Q3", 4), q("q4", "Q4", 4)]
        marks = {"s001": (4, NA, 2, 3), "s002": (5, 1, 4, NA), "s003": (3, 4, 1, 2),
                 "s004": (5, 5, 4, 4), "s005": (2, 3, 0, 1), "s006": (4, 4, 3, 2),
                 "s007": (1, 2, 2, 0), "s008": (3, None, None, None)}   # s008 unfinished
        grades = [(sid, qid, v) for sid, row in marks.items()
                  for qid, v in zip(("q1", "q2", "q3", "q4"), row) if v is not None]
        grades.append(("s001", "q1", 4, None, "Clear working, check the units."))
        make("Quiz 1 marks", mode="marks", questions=qs,
             groups=[{"id": "g1", "questions": ["q3", "q4"], "answer": 1, "pick": "best"}],
             grades=grades,
             overall={"s001": {"comment": "Good start; revise question 2."},
                      "s002": {"comment": "Strong on the first two questions.",
                               "report_total": 12}})

    def case_rubric():
        rs = [rubric("r1", "Criterion A"), rubric("r2", "Criterion C")]
        qs = [q("q1", "Q1", 0, ["r1", "r2"]), q("q2", "Q2", 0, ["r1"]), q("q3", "Q3", 0, ["r2"])]
        grades, overall = [], {}
        for i in range(8):
            sid = f"s{i+1:03}"
            grades += [(sid, "q1", 3 + i % 5, "r1"), (sid, "q1", 2 + i % 6, "r2"),
                       (sid, "q2", 4 + i % 4, "r1"),
                       (sid, "q3", 3 + i % 5, "r2", f"Explains the method ({i+1}).")]
            if i < 4:   # half the class has typed final levels
                overall[sid] = {"final_levels": {"r1": 5 + i % 3, "r2": 4 + i % 3},
                                "comment": f"Overall comment for paper {i+1}."}
        make("Unit test rubric", mode="rubric", rubrics=rs, questions=qs, grades=grades,
             overall=overall)

    def case_onecrit():
        qs = [q(f"q{n}", f"Q{n}", 0, ["r1"]) for n in range(1, 13)]
        grades = [(f"s{i+1:03}", f"q{n}", (i + n) % 8 + 1, "r1")
                  for i in range(8) for n in range(1, 13)]
        make("Essay one criterion", mode="rubric", rubrics=[rubric("r1", "Criterion B")],
             questions=qs, grades=grades)

    def case_critmarks():
        rs = [rubric("r1", "Criterion A"), rubric("r2", "Criterion D")]
        qs = [q("q1", "Q1", 10, ["r1"]), q("q2", "Q2", 10, ["r1"]), q("q3", "Q3", 20, ["r2"])]
        grades = [(f"s{i+1:03}", qid, v) for i in range(8)
                  for qid, v in (("q1", 4 + i % 6), ("q2", 3 + i % 7), ("q3", 8 + i))]
        make("Lab practical criterion marks", mode="marks", rubrics=rs, questions=qs,
             grades=grades)

    def mixed(name, mode):
        qs = [q("q1", "Q1", 10), q("q2", "Q2", 0, ["r1"]), q("q3", "Q3", 5)]
        grades = []
        for i in range(8):
            sid = f"s{i+1:03}"
            grades += [(sid, "q1", 5 + i % 5), (sid, "q2", 3 + i % 6, "r1"), (sid, "q3", i % 6)]
        make(name, mode=mode, rubrics=[rubric("r1", "Criterion A")], questions=qs,
             grades=grades, overall={"s001": {"final_levels": {"r1": 6}}})

    def case_weighted():
        qs = [q("q1", "Q1", 10, section="a"), q("q2", "Q2", 40, section="b")]
        grades = [(f"s{i+1:03}", qid, v) for i in range(8)
                  for qid, v in (("q1", 4 + i % 7), ("q2", 15 + 3 * i))]
        make("Weighted final", mode="marks", questions=qs, grades=grades,
             overall={"s003": {"report_percent": 80}},
             extra={"weighted": True, "sections": [
                 {"id": "a", "name": "Part A", "weight": 50, "weight_typed": True},
                 {"id": "b", "name": "Part B", "weight": 50, "weight_typed": False}]})

    def case_choice():
        qs = [q("q1", "Q1", 6), q("q2", "Q2", 6), q("q3", "Q3", 6)]
        grades = [(f"s{i+1:03}", qid, v) for i in range(8)
                  for qid, v in (("q1", 3 + i % 4), ("q2", 2 + i % 5), ("q3", 1 + i % 6))]
        make("Choice open", mode="marks", questions=qs, grades=grades,
             groups=[{"id": "g1", "questions": ["q2", "q3"], "answer": 1, "pick": "teacher"}],
             overall={f"s{i+1:03}": {"chosen": {"g1": ["q2"]}} for i in range(5)})

    def case_v1start():
        # The previous CAM2 sets the mode exam-wide, so this is a plain rubric exam.
        qs = [q("q1", "Q1", 0, ["r1"]), q("q2", "Q2", 0, ["r1"])]
        grades = [(f"s{i+1:03}", "q1", 4 + i % 4, "r1") for i in range(8)]
        grades += [(f"s{i+1:03}", "q2", 3 + i % 5, "r1") for i in range(4)]
        make("V1 upgraded", mode="rubric", rubrics=[rubric("r1", "Criterion C")],
             questions=qs, grades=grades)

    def case_v1finish():
        folder = os.path.join(exams, "V1 upgraded")
        session, config, data = storage.open_session(folder)
        for i in range(4, 8):
            gs.set_grade(config, data, f"s{i+1:03}", "q2", 3 + i % 5, rubric_id="r1",
                         comment="Finished after the update.")
        gs.set_final_level(config, data, "s001", "r1", 6)
        session.config_file.save(config)
        session.grades_file.save(data)
        print("finished", folder, "now version", data.get("version"))

    cases_by_name = {name[5:]: fn for name, fn in locals().items() if name.startswith("case_")}
    cases_by_name["mixed_m"] = lambda: mixed("Mixed started as marks", "marks")
    cases_by_name["mixed_r"] = lambda: mixed("Mixed started as rubric", "rubric")
    for case in cases or DEFAULT_CASES:
        cases_by_name[case]()


# --------------------------------------------------------------------------
# PDFs


def slides(out):
    import pymupdf
    os.makedirs(out, exist_ok=True)
    for i, (_, name) in enumerate(ROSTER):
        doc = pymupdf.open()
        for n, title in enumerate(("My artist", "My response"), 1):
            page = doc.new_page(width=960, height=540)          # 16:9 in points
            page.insert_text((60, 90), f"Slide {n}: {title}", fontsize=40)
            page.insert_text((60, 150), f"{name} (fictional)", fontsize=24)
            page.draw_rect(pymupdf.Rect(60, 200, 900, 480), color=(0.2, 0.3, 0.6), width=3)
            page.insert_text((90, 260 + 30 * (i % 5)),
                             f"Answer text for slide {n}, student {i+1}.", fontsize=22)
        doc.save(os.path.join(out, f"{name}.pdf"))
    print("slides in", out)


def draft(master):
    import pymupdf
    for _, name in ROSTER[:4]:
        folder = os.path.join(master, "Poster draft", name)
        os.makedirs(folder, exist_ok=True)
        doc = pymupdf.open()
        page = doc.new_page()
        page.insert_text((72, 100), f"Poster draft - {name} (fictional)", fontsize=20)
        page.draw_rect(pymupdf.Rect(72, 140, 520, 600), color=(0.3, 0.5, 0.3), width=3)
        doc.save(os.path.join(folder, "poster draft.pdf"))
    print("draft folders in", os.path.join(master, "Poster draft"))


if __name__ == "__main__":
    command, *args = sys.argv[1:]
    if command == "sessions":
        sessions(args[0], args[1], args[2:])
    elif command == "slides":
        slides(args[0])
    elif command == "draft":
        draft(args[0])
    else:
        raise SystemExit(__doc__)
