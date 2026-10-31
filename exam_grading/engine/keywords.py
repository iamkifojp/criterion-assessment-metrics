"""Quick comments: a per-exam list of keywords the teacher ticks while grading.

Ticking keywords on an answer writes one generated line at the top of that
answer's comment ("Areas to develop: check calculations."). Ticking again
rebuilds that line and keeps whatever the teacher typed below it. The line
last written is kept in the grade entry (``keyword_text``), so it can be
replaced exactly even after the list or the app language changes.

``cam2_session.json`` holds the list as ``"keywords": [{"label", "type"}]``
with type ``"strength"`` or ``"growth"``. A session without the key uses the
default list in the app's language.
"""

from __future__ import annotations

from typing import List

from . import grading_summary, i18n
from .errors import UserError

STRENGTH = "strength"
GROWTH = "growth"
DEFAULT_COUNT = 5
MAX_KEYWORDS = 30
MAX_LABEL = 60


def normalize(raw) -> List[dict]:
    """A clean [{label, type}] list: no blanks, no repeats, at most 30."""
    out, seen = [], set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        label = " ".join(str(item.get("label") or "").split())[:MAX_LABEL]
        if not label or label.casefold() in seen:
            continue
        seen.add(label.casefold())
        out.append({"label": label, "type": STRENGTH if item.get("type") == STRENGTH else GROWTH})
    return out[:MAX_KEYWORDS]


def keyword_list(config: dict, language: str) -> List[dict]:
    if "keywords" in config:
        return normalize(config["keywords"])
    return [{"label": i18n.t(f"keywords.default_{n}", language), "type": GROWTH}
            for n in range(1, DEFAULT_COUNT + 1)]


def set_list(config: dict, raw) -> dict:
    config["keywords"] = normalize(raw)
    return config


def comment_line(kw_list: List[dict], picked: List[str], language: str) -> str:
    """The generated line for the ticked keywords, strengths first."""
    kinds = {k["label"]: k["type"] for k in kw_list}
    sep = i18n.t("keywords.separator", language)
    parts = []
    for kind, key in ((STRENGTH, "keywords.strengths"), (GROWTH, "keywords.growth")):
        labels = [label for label in picked if kinds.get(label) == kind]
        if labels:
            parts.append(i18n.t(key, language, list=sep.join(labels)))
    return " ".join(parts)


def apply(config: dict, grades_data: dict, student_id: str, question_id: str,
          picked, language: str) -> dict:
    """Tick exactly ``picked`` on one answer and rebuild its comment's generated line."""
    kw_list = keyword_list(config, language)
    known = [k["label"] for k in kw_list]
    for label in picked or []:
        if label not in known:
            raise UserError("unknown_keyword", label=label)
    picked = [label for label in known if label in set(picked or [])]
    grading_summary.set_grade(config, grades_data, student_id, question_id)   # checks ids
    entry = grades_data["grades"][student_id][question_id]
    comment = str(entry.get("comment") or "")
    old_line = str(entry.get("keyword_text") or "")
    if old_line and comment.startswith(old_line):
        comment = comment[len(old_line):].lstrip("\n")
    line = comment_line(kw_list, picked, language)
    entry["comment"] = "\n".join(part for part in (line, comment) if part)
    entry["keywords"] = picked
    entry["keyword_text"] = line
    return grades_data
