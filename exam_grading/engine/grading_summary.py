"""Recording grades and working out totals.

Rules (see Exam-Section-Plan.md §3, which replaces the rubric rows in PLAN.md §3):

* A question grades with marks if it has a ``max``, and with rubric levels if
  it has none but is assessed on a criterion (:func:`question_mode`). Marks and
  levels are never added together or converted.

* A question's value is a whole number, ``"not_answered"`` or missing
  (ungraded). *Not answered* counts as 0.
* In a choice group ("answer N of M") N questions count. With the group's
  ``pick`` set to ``"best"`` (the default) the best N count, and a question
  the student answered always ranks above one they did not. With ``"teacher"``
  a student who answered more than N waits (the group is *pending*) until the
  teacher picks which N count; the picks are kept per student in
  ``overall[sid]["chosen"][group id]``. A student who answered N or fewer is
  counted exactly as with ``"best"``.
* Marks: total = counted marks; maximum = ordinary maximums plus, per choice
  group, the N largest maximums in it.
* Sections: a section's marks are its counted marks over its maximum. With
  weighting on, the overall percentage is the sum of (section marks / section
  maximum x section share), and the shares add up to exactly 100.
* Criterion marks: the marks of the questions on that criterion. With
  weighting on, each question counts as much as it does overall (see
  :func:`_criterion_marks`).
* Rubric levels are reported as given, one for each criterion a question is
  assessed on. A final level is optional and only ever typed by the teacher.
* A question is graded once every criterion it is assessed on has a level. In
  a choice group, questions are ranked by the sum of their levels.
* Ungraded questions are left out and the student is marked incomplete.
* A teacher's "total on report" overrides only the report; the calculated
  value is always kept beside it.

Percentages are worked out exactly (``Fraction``) and rounded half up only
once, at the end. Python's ``round()`` rounds halves to even and must not be
used.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Dict, List, Optional

from . import model, rubrics
from .errors import UserError

NOT_ANSWERED = model.NOT_ANSWERED
PICK_BEST = "best"
PICK_TEACHER = "teacher"
WHOLE_PAPER = "sec1"        # the id of the one section a paper without dividers has


def round_half_up(value, places: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


def _percent(exact: Fraction) -> float:
    """A percentage to 1 decimal place. This is the only rounding it ever gets."""
    return float(round_half_up(Decimal(exact.numerator) / Decimal(exact.denominator), 1))


# --- Lookups ---------------------------------------------------------------------

def _question(config: dict, question_id: str) -> dict:
    for q in config.get("questions") or []:
        if q["id"] == question_id:
            return q
    raise UserError("unknown_question", question=question_id)


def _rubric_by_id(config: dict) -> Dict[str, dict]:
    return {r["id"]: r for r in config.get("rubrics") or []}


def question_rubric_ids(config: dict, question: dict) -> List[str]:
    """The criteria (rubrics) a question is assessed on, in rubric order.

    Without marks, falls back to the only rubric when none was picked; a marks
    question counts towards a criterion only if it is ticked. Older sessions
    stored a single ``rubric_id``.
    """
    rubric_list = config.get("rubrics") or []
    picked = question.get("rubric_ids")
    if picked is None:
        picked = [question["rubric_id"]] if question.get("rubric_id") else []
    rids = [r["id"] for r in rubric_list if r["id"] in set(picked)]
    if not rids and len(rubric_list) == 1 and not question.get("max"):
        rids = [rubric_list[0]["id"]]
    return rids


def question_mode(config: dict, question: dict) -> Optional[str]:
    """How a question is graded: ``"marks"`` if it has a maximum, ``"rubric"`` if
    it has none but has a criterion, and None while it has neither."""
    if question.get("max"):
        return "marks"
    return "rubric" if question_rubric_ids(config, question) else None


def sections(config: dict) -> List[dict]:
    """The paper's sections in order, each with its ``questions``.

    With no dividers the whole paper is one section. A question that doesn't
    name a known section is in the same one as the question before it.
    """
    questions = config.get("questions") or []
    stored = config.get("sections") or []
    if not stored:
        return [{"id": WHOLE_PAPER, "name": "", "weight": None, "weight_typed": False,
                 "questions": list(questions)}]
    out = [dict(s, questions=[]) for s in stored]
    by_id = {s["id"]: s for s in out}
    current = out[0]
    for q in questions:
        current = by_id.get(q.get("section_id"), current)
        current["questions"].append(q)
    return out


def slots(config: dict) -> List[tuple]:
    """Every grade given on one paper, in order, as (question, rubric id).

    A marks question has one slot (rubric id None); a rubric question has one
    per criterion it is assessed on.
    """
    out = []
    for q in config.get("questions") or []:
        if question_mode(config, q) == "marks":
            out.append((q, None))
        else:
            out += [(q, rid) for rid in question_rubric_ids(config, q)]
    return out


def slot_key(question_id: str, rubric_id: Optional[str]) -> str:
    """A slot's key in summaries: ``q1`` for marks, ``q1/r2`` for a rubric level."""
    return question_id if rubric_id is None else f"{question_id}/{rubric_id}"


def group_pick(group: dict) -> str:
    """How a choice group counts an over-answered paper: best N, or teacher picks."""
    return PICK_TEACHER if group.get("pick") == PICK_TEACHER else PICK_BEST


def check_groups_in_sections(config: dict) -> None:
    """A choice group stays inside one section, or that section's total would
    have no clear meaning."""
    section_of = {q["id"]: s["id"] for s in sections(config) for q in s["questions"]}
    for g in config.get("choice_groups") or []:
        if len({section_of.get(qid) for qid in g.get("questions") or []}) > 1:
            raise UserError("choice_group_across_sections", group=g.get("id", "?"))


def check_choice_groups(config: dict) -> None:
    """Every group names known questions, none twice, and 1 <= answer < size.
    All its questions are in one section and are graded the same way, because
    a mark can't be ranked against a level."""
    questions = {q["id"]: q for q in config.get("questions") or []}
    known = set(questions)
    seen = set()
    for g in config.get("choice_groups") or []:
        qids = list(g.get("questions") or [])
        answer = g.get("answer")
        if (len(qids) < 2 or len(set(qids)) != len(qids)
                or not set(qids) <= known or seen & set(qids)
                or not isinstance(answer, int) or not 1 <= answer < len(qids)
                or g.get("pick", PICK_BEST) not in (PICK_BEST, PICK_TEACHER)):
            raise UserError("choice_group_invalid", group=g.get("id", "?"))
        if len({question_mode(config, questions[qid]) for qid in qids}) > 1:
            raise UserError("choice_group_mixed", group=g.get("id", "?"))
        seen |= set(qids)
    check_groups_in_sections(config)


# --- Recording a grade -------------------------------------------------------------
#
# How long a comment may be, in characters, because Japanese has no spaces. A limit
# stops new typing only. A longer comment already saved is never cut, and can be
# kept or shortened but can't grow.
MAX_QUESTION_COMMENT = 300
MAX_OVERALL_COMMENT = 600


def typed_comment(comment, generated_line: str = "") -> str:
    """A comment without the line generated from quick comments (keywords.py)."""
    text = str(comment or "")
    if generated_line and text.startswith(generated_line):
        return text[len(generated_line):].lstrip("\n")
    return text


def _check_comment_length(new, old, limit: int, generated_line: str = "") -> None:
    length = len(typed_comment(new, generated_line))
    if length > limit and length > len(typed_comment(old, generated_line)):
        raise UserError("comment_too_long", limit=limit)


# A grade entry is {"value": ..., "comment": ...}. On a rubric question the levels
# are kept per criterion in "levels": {rubric id: level}, with "value" None,
# so criteria can be added to or taken off a question after grading starts
# without a level moving to another criterion. Reading goes through level_of().

def set_grade(config: dict, grades_data: dict, student_id: str, question_id: str,
              value=..., comment=None, rubric_id: Optional[str] = None) -> dict:
    """Validate and store a value and/or comment. ``value=None`` clears the grade.

    Leave ``value`` out to change only the comment. For a question assessed
    on several criteria, ``rubric_id`` says which one is graded; without it,
    *Not answered* or None applies to all of them. A marks question takes no
    ``rubric_id``, so a level can't be stored as a mark. Mutates and returns
    ``grades_data``.
    """
    if student_id not in {s["id"] for s in config.get("students") or []}:
        raise UserError("unknown_student", student=student_id)
    question = _question(config, question_id)
    mode = question_mode(config, question)
    rubric_mode = mode == "rubric"
    rids = question_rubric_ids(config, question) if rubric_mode else []
    if value is not ...:
        if mode is None:
            raise UserError("question_needs_marks_or_criterion", question=question["label"])
        if rubric_id is not None and rubric_id not in rids:
            raise UserError("unknown_rubric", rubric=rubric_id)
        if rubric_id is None and len(rids) > 1 and value not in (None, NOT_ANSWERED):
            raise UserError("unknown_rubric", rubric="")
    if value is not ... and value is not None and value != NOT_ANSWERED:
        if isinstance(value, bool) or not isinstance(value, int):
            raise UserError("mark_out_of_range", value=value, max=question.get("max"))
        if rubric_mode:
            rubrics.check_level(_rubric_by_id(config)[rubric_id or rids[0]], value)
        elif not 0 <= value <= int(question.get("max") or 0):
            raise UserError("mark_out_of_range", value=value, max=question.get("max"))
    if comment is not None:
        saved = _entry(grades_data, student_id, question_id)
        _check_comment_length(comment, saved.get("comment"), MAX_QUESTION_COMMENT,
                              str(saved.get("keyword_text") or ""))
    entry = grades_data.setdefault("grades", {}).setdefault(student_id, {}).setdefault(
        question_id, {"value": None, "comment": ""})
    if value is not ...:
        if rubric_mode:
            if "levels" in entry:
                levels = dict(entry["levels"])
            else:
                levels = {rids[0]: entry.get("value")}
            for rid in [rubric_id] if rubric_id else rids:
                levels[rid] = value
            entry["levels"] = levels
            entry["value"] = None
        else:
            entry["value"] = value
    if comment is not None:
        entry["comment"] = str(comment)
    return grades_data


def _entry(grades_data: dict, student_id: str, question_id: str) -> dict:
    return (grades_data.get("grades") or {}).get(student_id, {}).get(question_id) or {}


def level_of(config: dict, entry: dict, question: dict, rubric_id: Optional[str]):
    """One slot's value in a grade entry (None = ungraded)."""
    entry = entry or {}
    if rubric_id is None:
        return entry.get("value")
    if "levels" in entry:
        return entry["levels"].get(rubric_id)
    # Graded before levels were kept per criterion: one value, for one criterion.
    return entry.get("value") if question_rubric_ids(config, question)[:1] == [rubric_id] else None


def question_values(config: dict, grades_data: dict, student_id: str, question: dict) -> dict:
    """{rubric id: value} for each criterion of one question on one paper
    ({None: value} for a marks question)."""
    entry = _entry(grades_data, student_id, question["id"])
    if question_mode(config, question) == "marks":
        return {None: entry.get("value")}
    return {rid: level_of(config, entry, question, rid)
            for rid in question_rubric_ids(config, question)}


# --- One student -------------------------------------------------------------------

def counted_questions(config: dict, grades_data: dict, student_id: str):
    """(counted, ungraded [qid], choices) after resolving choice groups.

    ``counted`` is {qid: number} for a marks question and {qid: {rubric id:
    level}} for a rubric one. A question is ungraded while any of its slots is;
    outside a choice group its graded slots still count.

    ``choices`` has an entry for each "teacher picks" group this student
    answered more of than needed: {group id: {"answered": [qid],
    "chosen": [qid], "pending": bool}}. A pending group counts nothing.
    """
    questions = config.get("questions") or []
    order = {q["id"]: i for i, q in enumerate(questions)}
    values = {q["id"]: question_values(config, grades_data, student_id, q) for q in questions}
    ungraded = [qid for qid, v in values.items() if not v or None in v.values()]

    def numbers(qid):
        return {rid: 0 if v == NOT_ANSWERED else v
                for rid, v in values[qid].items() if v is not None}

    def count(qid):
        n = numbers(qid)
        if n:
            counted[qid] = n[None] if None in n else n

    def answered(qid):
        return not all(v == NOT_ANSWERED for v in values[qid].values())

    picks = ((grades_data.get("overall") or {}).get(student_id) or {}).get("chosen") or {}
    in_group = set()
    counted: Dict[str, object] = {}
    choices: Dict[str, dict] = {}
    for g in config.get("choice_groups") or []:
        qids = [qid for qid in g["questions"] if qid in values]
        in_group |= set(qids)
        graded = [qid for qid in qids if qid not in ungraded]
        given = [qid for qid in graded if answered(qid)]
        if group_pick(g) == PICK_TEACHER and len(given) > int(g["answer"]):
            chosen = [qid for qid in qids if qid in set(picks.get(g["id"]) or []) and qid in given]
            pending = len(chosen) != int(g["answer"])
            choices[g["id"]] = {"answered": given, "chosen": chosen, "pending": pending}
            if not pending:
                for qid in chosen:
                    count(qid)
            continue
        graded.sort(key=lambda qid: (all(v == NOT_ANSWERED for v in values[qid].values()),
                                     -sum(numbers(qid).values()), order[qid]))
        for qid in graded[:int(g["answer"])]:
            count(qid)
    for qid in values:
        if qid not in in_group:
            count(qid)
    return counted, ungraded, choices


def marks_maximum(config: dict, questions: Optional[List[dict]] = None) -> int:
    """The most marks available on the paper, or on just these questions (one
    section): ordinary maximums plus, per choice group, the N largest in it."""
    if questions is None:
        questions = config.get("questions") or []
    maxes = {q["id"]: int(q.get("max") or 0) for q in questions}
    in_group = set()
    total = 0
    for g in config.get("choice_groups") or []:
        in_here = sorted((maxes[qid] for qid in g["questions"] if qid in maxes), reverse=True)
        total += sum(in_here[:int(g["answer"])])
        in_group |= set(g["questions"])
    return total + sum(m for qid, m in maxes.items() if qid not in in_group)


# --- Section shares ------------------------------------------------------------------

def sections_with_marks(config: dict) -> List[dict]:
    return [s for s in sections(config) if marks_maximum(config, s["questions"])]


def weighting_on(config: dict) -> bool:
    """Weighting means nothing unless two sections have marks to share between."""
    return bool(config.get("weighted")) and len(sections_with_marks(config)) >= 2


def rebalance_shares(config: dict) -> None:
    """Give every section with marks questions its share of the paper.

    A share the teacher typed stays. The sections not typed split the rest
    equally, any leftover going to the first of them one point each, so the
    shares always add up to exactly 100. One section always stays automatic. A
    section with no marks questions has no share.
    """
    stored = {s["id"]: s for s in config.get("sections") or []}
    if not stored:
        return
    sharing = [stored[s["id"]] for s in sections_with_marks(config)]
    for s in stored.values():
        if s not in sharing:
            s["weight"], s["weight_typed"] = None, False
    if not sharing:
        return
    if all(s.get("weight_typed") for s in sharing):
        sharing[-1]["weight_typed"] = False
    automatic = [s for s in sharing if not s.get("weight_typed")]
    typed = sum(s["weight"] for s in sharing if s.get("weight_typed"))
    each, leftover = divmod(100 - typed, len(automatic))
    for i, s in enumerate(automatic):
        s["weight"] = each + (1 if i < leftover else 0)
        s["weight_typed"] = False


# --- One student -------------------------------------------------------------------

def _section_results(config: dict, counted: dict, weighted: bool) -> List[dict]:
    """Each section's marks. Only marks questions count, so a section with only
    rubric questions has no total. ``weighted_marks`` is for showing (``44.0 / 50``);
    the overall percentage is worked out from unrounded figures instead."""
    results = []
    for s in sections(config):
        total = sum(counted[q["id"]] for q in s["questions"]
                    if q["id"] in counted and question_mode(config, q) == "marks")
        maximum = marks_maximum(config, s["questions"])
        row = {"id": s["id"], "name": s["name"], "total": total, "max": maximum,
               "percent": _percent(Fraction(total * 100, maximum)) if maximum else None,
               "share": None, "weighted_marks": None}
        if weighted and maximum:
            row["share"] = s["weight"]
            row["weighted_marks"] = _percent(Fraction(total * s["weight"], maximum))
        results.append(row)
    return results


def _criterion_marks(config: dict, rubric_id: str, counted: dict, weighted: bool) -> Optional[dict]:
    """The marks of the questions on one criterion, or None if it has none.

    An ungraded question stays in the maximum, as it does in the overall total,
    and a choice-group question that did not count is left out. With weighting
    on, each question counts as much here as it does overall: its share is
    section share x question maximum / section maximum, and the percentage is
    the sum of (marks / question maximum x share) over the sum of those shares.
    """
    in_group = {qid for g in config.get("choice_groups") or [] for qid in g["questions"]}
    total = maximum = 0
    earned = shares = Fraction(0)
    for s in sections(config):
        section_max = marks_maximum(config, s["questions"])
        for q in s["questions"]:
            if (question_mode(config, q) != "marks" or rubric_id not in question_rubric_ids(config, q)
                    or (q["id"] in in_group and q["id"] not in counted)):
                continue
            mark, top = counted.get(q["id"], 0), int(q["max"])
            total += mark
            maximum += top
            if weighted:
                share = Fraction(int(s["weight"]) * top, section_max)
                earned += Fraction(mark, top) * share
                shares += share
    if not maximum:
        return None
    if not weighted:
        percent = _percent(Fraction(total * 100, maximum))
    else:
        percent = _percent(earned * 100 / shares) if shares else None
    return {"total": total, "max": maximum, "percent": percent}


def student_summary(config: dict, grades_data: dict, student_id: str) -> dict:
    counted, ungraded, choices = counted_questions(config, grades_data, student_id)
    overall = (grades_data.get("overall") or {}).get(student_id) or {}
    pending = [gid for gid, c in choices.items() if c["pending"]]
    questions = config.get("questions") or []
    weighted = weighting_on(config)
    section_results = _section_results(config, counted, weighted)
    levels = {q["id"]: question_values(config, grades_data, student_id, q) for q in questions
              if question_mode(config, q) == "rubric"}
    result = {"student_id": student_id, "ungraded": ungraded, "pending": pending,
              "choices": choices, "complete": not ungraded and not pending,
              "counted": counted, "comment": overall.get("comment", ""),
              "levels": levels, "sections": section_results}

    finals = overall.get("final_levels") or {}
    result["rubrics"] = {}
    for r in config.get("rubrics") or []:
        # The grades as given, never totalled. Only those that count are listed.
        grades = [{"question": q["id"], "level": levels[q["id"]][r["id"]]} for q in questions
                  if q["id"] in levels and r["id"] in (counted.get(q["id"]) or {})]
        result["rubrics"][r["id"]] = {"final": finals.get(r["id"]), "grades": grades,
                                      "marks": _criterion_marks(config, r["id"], counted, weighted)}

    total = sum(s["total"] for s in section_results)
    maximum = sum(s["max"] for s in section_results)
    reported = overall.get("report_total")
    report_total = reported if reported is not None else total
    if weighted:
        percent = _percent(sum(Fraction(s["total"], s["max"]) * s["share"]
                               for s in section_results if s["max"]))
        typed = overall.get("report_percent")
        report_percent = typed if typed is not None else percent
        adjusted = typed is not None and typed != percent
    else:
        percent = _percent(Fraction(total * 100, maximum)) if maximum else None
        report_percent = _percent(Fraction(str(report_total)) * 100 / maximum) if maximum else None
        adjusted = reported is not None and reported != total
    result["marks"] = {"total": total, "max": maximum, "percent": percent, "weighted": weighted,
                       "report_total": report_total, "report_percent": report_percent,
                       "adjusted": adjusted}
    return result


def _override_number(value, maximum):
    """A number a teacher typed over a calculated one (None = no override)."""
    if value is not None:
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                raise UserError("report_total_invalid", value=value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UserError("report_total_invalid", value=value)
        if not 0 <= value <= maximum:
            raise UserError("report_value_out_of_range", max=maximum)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
    return value


def set_report_total(config: dict, grades_data: dict, student_id: str, value) -> dict:
    """Total printed on this student's report (None = use the calculated one)."""
    total = _override_number(value, marks_maximum(config))
    grades_data.setdefault("overall", {}).setdefault(student_id, {})["report_total"] = total
    return grades_data


def set_report_percent(grades_data: dict, student_id: str, value) -> dict:
    """With weighting on, the percentage printed on this student's report takes
    the place of the total (None = use the calculated one)."""
    percent = _override_number(value, 100)
    grades_data.setdefault("overall", {}).setdefault(student_id, {})["report_percent"] = percent
    return grades_data


def set_final_level(config: dict, grades_data: dict, student_id: str,
                    rubric_id: str, level) -> dict:
    """Teacher's final level for one rubric (None = no final level). It must be
    a level in one of the rubric's bands, so the report can shade that band."""
    rubric = _rubric_by_id(config).get(rubric_id)
    if rubric is None:
        raise UserError("unknown_rubric", rubric=rubric_id)
    if isinstance(level, str):
        try:
            level = int(level.strip())
        except ValueError:
            raise UserError("level_not_in_rubric", level=level, rubric=rubric["name"])
    if level is not None:
        rubrics.check_level(rubric, level)
    finals = grades_data.setdefault("overall", {}).setdefault(student_id, {}) \
        .setdefault("final_levels", {})
    finals[rubric_id] = level
    return grades_data


def set_choice(config: dict, grades_data: dict, student_id: str, group_id: str, questions) -> dict:
    """The questions a teacher picked to count in one choice group for one student.

    ``questions`` lists at most ``answer`` of the group's questions; None or an
    empty list clears the pick. Picks are stored in the group's order.
    """
    group = next((g for g in config.get("choice_groups") or [] if g["id"] == group_id), None)
    if group is None:
        raise UserError("choice_group_invalid", group=group_id)
    picked = list(questions or [])
    if (len(set(picked)) != len(picked) or not set(picked) <= set(group["questions"])
            or len(picked) > int(group["answer"])):
        raise UserError("choice_pick_invalid", answer=group["answer"])
    chosen = grades_data.setdefault("overall", {}).setdefault(student_id, {}).setdefault("chosen", {})
    if picked:
        chosen[group_id] = [qid for qid in group["questions"] if qid in set(picked)]
    else:
        chosen.pop(group_id, None)
    return grades_data


def set_overall_comment(grades_data: dict, student_id: str, comment: str) -> dict:
    saved = (grades_data.get("overall") or {}).get(student_id) or {}
    _check_comment_length(comment, saved.get("comment"), MAX_OVERALL_COMMENT)
    grades_data.setdefault("overall", {}).setdefault(student_id, {})["comment"] = str(comment or "")
    return grades_data


# --- Whole class ----------------------------------------------------------------------

def _stats(numbers: List) -> Optional[dict]:
    if not numbers:
        return None
    avg = Decimal(str(sum(numbers))) / Decimal(len(numbers))
    return {"average": float(round_half_up(avg, 1)), "max": max(numbers),
            "min": min(numbers), "count": len(numbers)}


def class_summary(config: dict, grades_data: dict) -> dict:
    """Every student's summary plus class average / max / min.

    Per-question statistics are keyed by :func:`slot_key` and count *Not answered* as 0, except inside a choice
    group, where an unanswered question was simply not chosen. ``sections`` has the marks of each section with
    marks questions, by section id.
    """
    students = [student_summary(config, grades_data, s["id"])
                for s in config.get("students") or []]
    in_group = {qid for g in config.get("choice_groups") or [] for qid in g["questions"]}

    per_question = {}
    for q, rid in slots(config):
        nums = []
        for s in config.get("students") or []:
            v = level_of(config, _entry(grades_data, s["id"], q["id"]), q, rid)
            if v == NOT_ANSWERED:
                if q["id"] not in in_group:
                    nums.append(0)
            elif v is not None:
                nums.append(v)
        per_question[slot_key(q["id"], rid)] = _stats(nums)

    started = [s for s in students if s["counted"]]
    overall = {}
    for r in config.get("rubrics") or []:
        overall[r["id"]] = _stats([s["rubrics"][r["id"]]["final"] for s in started
                                   if s["rubrics"][r["id"]]["final"] is not None])
    if marks_maximum(config):
        overall["total"] = _stats([s["marks"]["total"] for s in started])
    if weighting_on(config):
        overall["percent"] = _stats([s["marks"]["percent"] for s in started])
    section_stats = {}
    for i, section in enumerate(sections(config)):
        if marks_maximum(config, section["questions"]):
            section_stats[section["id"]] = _stats([s["sections"][i]["total"] for s in started])
    return {"students": students, "questions": per_question, "overall": overall, "sections": section_stats}


def question_has_grade(grades_data: dict, question_id: str) -> bool:
    """True once any paper has a grade on this question (comments alone don't count)."""
    entries = ((per or {}).get(question_id) for per in (grades_data.get("grades") or {}).values())
    return any(isinstance(e, dict) and (
        e.get("value") is not None
        or any(v is not None for v in (e.get("levels") or {}).values()))
        for e in entries)


def highest_mark(grades_data: dict, question_id: str) -> int:
    """The highest mark any paper has on this question (0 if none)."""
    entries = ((per or {}).get(question_id) or {} for per in (grades_data.get("grades") or {}).values())
    return max((e["value"] for e in entries if isinstance(e.get("value"), int)), default=0)


def progress(config: dict, grades_data: dict) -> dict:
    """Slots graded across the class, and papers with every slot graded."""
    all_slots = slots(config)
    students = [s["id"] for s in config.get("students") or []]
    graded = done = 0
    for sid in students:
        n = sum(1 for q, rid in all_slots
                if level_of(config, _entry(grades_data, sid, q["id"]), q, rid) is not None)
        graded += n
        done += bool(all_slots) and n == len(all_slots)
    return {"graded": graded, "total": len(all_slots) * len(students),
            "students_done": done, "students_total": len(students)}
