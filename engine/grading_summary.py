"""Recording grades and working out totals and averages.

Rules (see PLAN.md §3):

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
* Rubric: a question is assessed on one or more criteria (rubrics) and gets
  one level for each. Per rubric, the average of its counted levels; the
  suggested final level is that average **rounded half up** (4.5 -> 5).
  Python's ``round()`` rounds halves to even and must not be used.
* A question is graded once every criterion it is assessed on has a level. In
  a choice group, questions are ranked by the sum of their levels.
* Ungraded questions are left out and the student is marked incomplete.
* A teacher's "total on report" or final level overrides only the report; the
  calculated value is always kept beside it.

All averages use ``Decimal`` so 4.5 really is 4.5 when it is rounded.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, List, Optional

from . import model, rubrics
from .errors import UserError

NOT_ANSWERED = model.NOT_ANSWERED
PICK_BEST = "best"
PICK_TEACHER = "teacher"


def round_half_up(value, places: int = 0) -> Decimal:
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


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

    Falls back to the only rubric when none was picked. Older sessions stored
    a single ``rubric_id``.
    """
    rubric_list = config.get("rubrics") or []
    picked = question.get("rubric_ids")
    if picked is None:
        picked = [question["rubric_id"]] if question.get("rubric_id") else []
    rids = [r["id"] for r in rubric_list if r["id"] in set(picked)]
    if not rids and len(rubric_list) == 1:
        rids = [rubric_list[0]["id"]]
    return rids


def slots(config: dict) -> List[tuple]:
    """Every grade given on one paper, in order, as (question, rubric id).

    Marks mode has one slot per question (rubric id None); rubric mode has one
    per criterion the question is assessed on.
    """
    if config.get("mode") != "rubric":
        return [(q, None) for q in config.get("questions") or []]
    return [(q, rid) for q in config.get("questions") or []
            for rid in question_rubric_ids(config, q)]


def slot_key(question_id: str, rubric_id: Optional[str]) -> str:
    """A slot's key in summaries: ``q1`` in marks mode, ``q1/r2`` in rubric mode."""
    return question_id if rubric_id is None else f"{question_id}/{rubric_id}"


def group_pick(group: dict) -> str:
    """How a choice group counts an over-answered paper: best N, or teacher picks."""
    return PICK_TEACHER if group.get("pick") == PICK_TEACHER else PICK_BEST


def check_choice_groups(config: dict) -> None:
    """Every group names known questions, none twice, and 1 <= answer < size."""
    known = {q["id"] for q in config.get("questions") or []}
    seen = set()
    for g in config.get("choice_groups") or []:
        qids = list(g.get("questions") or [])
        answer = g.get("answer")
        if (len(qids) < 2 or len(set(qids)) != len(qids)
                or not set(qids) <= known or seen & set(qids)
                or not isinstance(answer, int) or not 1 <= answer < len(qids)
                or g.get("pick", PICK_BEST) not in (PICK_BEST, PICK_TEACHER)):
            raise UserError("choice_group_invalid", group=g.get("id", "?"))
        seen |= set(qids)


# --- Recording a grade -------------------------------------------------------------
#
# A grade entry is {"value": ..., "comment": ...}. In rubric mode the levels
# are kept per criterion in "levels": {rubric id: level}, with "value" None,
# so criteria can be added to or taken off a question after grading starts
# without a level moving to another criterion. Reading goes through level_of().

def set_grade(config: dict, grades_data: dict, student_id: str, question_id: str,
              value=..., comment=None, rubric_id: Optional[str] = None) -> dict:
    """Validate and store a value and/or comment. ``value=None`` clears the grade.

    Leave ``value`` out to change only the comment. For a question assessed
    on several criteria, ``rubric_id`` says which one is graded; without it,
    *Not answered* or None applies to all of them. Mutates and returns
    ``grades_data``.
    """
    if student_id not in {s["id"] for s in config.get("students") or []}:
        raise UserError("unknown_student", student=student_id)
    question = _question(config, question_id)
    rubric_mode = config.get("mode") == "rubric"
    rids = question_rubric_ids(config, question) if rubric_mode else []
    if rubric_mode and value is not ...:
        if not rids:
            raise UserError("question_has_no_rubric", question=question["label"])
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
    ({None: value} in marks mode)."""
    entry = _entry(grades_data, student_id, question["id"])
    if config.get("mode") != "rubric":
        return {None: entry.get("value")}
    return {rid: level_of(config, entry, question, rid)
            for rid in question_rubric_ids(config, question)}


# --- One student -------------------------------------------------------------------

def counted_questions(config: dict, grades_data: dict, student_id: str):
    """(counted, ungraded [qid], choices) after resolving choice groups.

    ``counted`` is {qid: number} in marks mode and {qid: {rubric id: level}}
    in rubric mode. A question is ungraded while any of its slots is; outside
    a choice group its graded slots still count.

    ``choices`` has an entry for each "teacher picks" group this student
    answered more of than needed: {group id: {"answered": [qid],
    "chosen": [qid], "pending": bool}}. A pending group counts nothing.
    """
    rubric_mode = config.get("mode") == "rubric"
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
            counted[qid] = n if rubric_mode else n[None]

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


def marks_maximum(config: dict) -> int:
    questions = {q["id"]: int(q.get("max") or 0) for q in config.get("questions") or []}
    in_group = set()
    total = 0
    for g in config.get("choice_groups") or []:
        maxes = sorted((questions[qid] for qid in g["questions"] if qid in questions),
                       reverse=True)
        total += sum(maxes[:int(g["answer"])])
        in_group |= set(g["questions"])
    return total + sum(m for qid, m in questions.items() if qid not in in_group)


def student_summary(config: dict, grades_data: dict, student_id: str) -> dict:
    counted, ungraded, choices = counted_questions(config, grades_data, student_id)
    overall = (grades_data.get("overall") or {}).get(student_id) or {}
    pending = [gid for gid, c in choices.items() if c["pending"]]
    result = {"student_id": student_id, "ungraded": ungraded, "pending": pending,
              "choices": choices, "complete": not ungraded and not pending,
              "counted": counted, "comment": overall.get("comment", "")}

    if config.get("mode") == "rubric":
        by_rubric: Dict[str, List[int]] = {}
        for levels in counted.values():
            for rid, level in levels.items():
                by_rubric.setdefault(rid, []).append(level)
        result["levels"] = {q["id"]: question_values(config, grades_data, student_id, q)
                            for q in config.get("questions") or []}
        finals = overall.get("final_levels") or {}
        result["rubrics"] = {}
        for r in config.get("rubrics") or []:
            levels = by_rubric.get(r["id"], [])
            if levels:
                avg = Decimal(sum(levels)) / Decimal(len(levels))
                average = float(round_half_up(avg, 1))
                suggested = int(round_half_up(avg))
            else:
                average = suggested = None
            chosen = finals.get(r["id"])
            final = chosen if chosen is not None else suggested
            result["rubrics"][r["id"]] = {
                "average": average, "suggested": suggested, "final": final,
                "adjusted": chosen is not None and chosen != suggested}
    else:
        total = sum(counted.values())
        maximum = marks_maximum(config)
        percent = (float(round_half_up(Decimal(total) * 100 / Decimal(maximum), 1))
                   if maximum else None)
        reported = overall.get("report_total")
        result["marks"] = {
            "total": total, "max": maximum, "percent": percent,
            "report_total": reported if reported is not None else total,
            "adjusted": reported is not None and reported != total}
    return result


def set_report_total(grades_data: dict, student_id: str, value) -> dict:
    """Total printed on this student's report (None = use the calculated one)."""
    if value is not None:
        if isinstance(value, str):
            try:
                value = float(value.strip())
            except ValueError:
                raise UserError("report_total_invalid", value=value)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise UserError("report_total_invalid", value=value)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
    grades_data.setdefault("overall", {}).setdefault(student_id, {})["report_total"] = value
    return grades_data


def set_final_level(config: dict, grades_data: dict, student_id: str,
                    rubric_id: str, level) -> dict:
    """Teacher's final level for one rubric (None = use the suggestion)."""
    rubric = _rubric_by_id(config).get(rubric_id)
    if rubric is None:
        raise UserError("unknown_rubric", rubric=rubric_id)
    if isinstance(level, str):
        try:
            level = int(level.strip())
        except ValueError:
            raise UserError("level_not_in_rubric", level=level, rubric=rubric["name"])
    if level is not None:
        if isinstance(level, bool) or not isinstance(level, int) \
                or not 0 <= level <= rubrics.rubric_max(rubric):
            raise UserError("level_not_in_rubric", level=level, rubric=rubric["name"])
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
    group, where an unanswered question was simply not chosen.
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
    if config.get("mode") == "rubric":
        for r in config.get("rubrics") or []:
            overall[r["id"]] = _stats([s["rubrics"][r["id"]]["final"] for s in started
                                       if s["rubrics"][r["id"]]["final"] is not None])
    else:
        overall["total"] = _stats([s["marks"]["total"] for s in started])
    return {"students": students, "questions": per_question, "overall": overall}


def has_grades(grades_data: dict) -> bool:
    """True once any paper has a grade (comments alone don't count)."""
    return any(isinstance(e, dict) and (
        e.get("value") is not None
        or any(v is not None for v in (e.get("levels") or {}).values()))
        for per in (grades_data.get("grades") or {}).values()
        for e in (per or {}).values())


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
