"""Class lists and matching papers to students.

Class lists come in every shape, so CAM2 does not guess silently: it shows the
first rows and the teacher clicks the column (or the family + given name
columns) holding the names. :func:`guess_header` and :func:`guess_name_columns`
only pre-select that choice.
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Dict, List, Sequence

from .errors import UserError

PREVIEW_ROWS = 5

_NAME_WORDS = ("name", "student", "氏名", "名前", "生徒", "児童", "fullname")
_FAMILY_WORDS = ("last", "family", "surname", "姓", "苗字", "名字")
_GIVEN_WORDS = ("first", "given", "forename", "名")
_OTHER_WORDS = ("id", "no", "no.", "number", "番号", "出席番号", "class", "クラス",
                "email", "mail", "gender", "性別", "grade", "学年", "組")


def _header_word(cell: str) -> str:
    return re.sub(r"[\s_]+", " ", unicodedata.normalize("NFKC", cell).casefold()).strip()


def _matches(cell: str, words) -> bool:
    text = _header_word(cell)
    # Single CJK characters such as 姓 / 名 must match the whole cell.
    return any(text == w or (len(w) > 1 and w in text) for w in words)


def guess_header(rows: List[List[str]]) -> bool:
    if not rows:
        return False
    first = rows[0]
    return any(_matches(c, _NAME_WORDS + _FAMILY_WORDS + _GIVEN_WORDS + _OTHER_WORDS)
               for c in first if c)


def _looks_like_name(value: str) -> bool:
    v = value.strip()
    if not v or "@" in v:
        return False
    return any(ch.isalpha() for ch in v) and not re.fullmatch(r"[\d\s\-./]+", v)


def guess_name_columns(rows: List[List[str]], has_header: bool) -> List[int]:
    """Pre-selected name column(s): [full] or [family, given]."""
    if not rows:
        return []
    if has_header:
        header = rows[0]
        family = [i for i, c in enumerate(header) if _matches(c, _FAMILY_WORDS)]
        given = [i for i, c in enumerate(header)
                 if _matches(c, _GIVEN_WORDS) and i not in family]
        full = [i for i, c in enumerate(header)
                if _matches(c, _NAME_WORDS) and i not in family and i not in given]
        if full:
            return [full[0]]
        if family and given:
            return [family[0], given[0]]
    body = rows[1:] if has_header else rows
    width = max(len(r) for r in rows)
    best, best_score = None, 0.0
    for i in range(width):
        values = [r[i] for r in body if i < len(r) and r[i]]
        if not values:
            continue
        score = sum(_looks_like_name(v) for v in values) / len(values)
        if score > best_score:
            best, best_score = i, score
    return [best] if best is not None and best_score >= 0.5 else []


def preview(rows: List[List[str]]) -> List[List[str]]:
    return rows[:PREVIEW_ROWS]


def _roster(names: Sequence[str]) -> List[dict]:
    out = [{"id": f"n{i:03d}", "name": n} for i, n in enumerate(names, 1)]
    if not out:
        raise UserError("no_names_found")
    return out


def extract_names(rows: List[List[str]], columns: Sequence[int],
                  has_header: bool) -> List[dict]:
    """Roster entries from the chosen column(s), joined in the order clicked."""
    if not columns:
        raise UserError("no_name_column")
    names = []
    for row in rows[1:] if has_header else rows:
        parts = [row[i].strip() for i in columns if i < len(row) and row[i].strip()]
        if parts:
            names.append(" ".join(parts))
    return _roster(names)


def parse_pasted(text: str) -> List[dict]:
    """One name per line (cells pasted from Excel are joined with a space)."""
    names = []
    for line in str(text or "").splitlines():
        name = " ".join(p.strip() for p in line.split("\t") if p.strip())
        name = re.sub(r"\s+", " ", name).strip()    # \s includes the full-width space
        if name:
            names.append(name)
    return _roster(names)


# --- Matching scan file names to the roster ----------------------------------------

_SEPARATORS = re.compile(r"[\s_\-.,・·()（）\[\]]+")


def normalize_for_match(text: str) -> str:
    """Case, width, spacing and macOS-decomposed characters made comparable."""
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", str(text or "")).casefold())


def _name_keys(name: str) -> set:
    """Both 'Tanaka Hana' and 'Hana Tanaka' forms, without separators."""
    text = unicodedata.normalize("NFKC", name).casefold()
    tokens = [t for t in _SEPARATORS.split(text) if t]
    keys = {"".join(tokens)}
    if len(tokens) > 1:
        keys.add("".join(reversed(tokens)))
    return {k for k in keys if len(k) >= 2}


def auto_match(students: Sequence[dict], roster: Sequence[dict]) -> Dict[str, str]:
    """{student_id: roster_id} for papers whose file name contains a student's name.

    Only certain matches are made: one name per file, one file per name.
    Everything else is left for the teacher.
    """
    keys = {r["id"]: _name_keys(r["name"]) for r in roster}
    candidates: Dict[str, List[str]] = {}
    for s in students:
        stem = normalize_for_match(os.path.splitext(s.get("source") or s.get("file") or "")[0])
        hits = [rid for rid, ks in keys.items() if any(k in stem for k in ks)]
        if len(hits) == 1:
            candidates[s["id"]] = hits
    claimed: Dict[str, int] = {}
    for hits in candidates.values():
        claimed[hits[0]] = claimed.get(hits[0], 0) + 1
    return {sid: hits[0] for sid, hits in candidates.items() if claimed[hits[0]] == 1}
