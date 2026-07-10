"""
Unit-plan .docx parser.

Extracts the three pieces of metadata the app needs from a standard IB MYP
unit-plan document:

    1. Unit Title
    2. Statement of Inquiry
    3. Target MYP Criteria (the criteria letters the unit is assessed against,
       with their objective headings)

The MYP unit-plan template stores almost all content in tables rather than
body paragraphs, so the parser walks the document's tables and matches on the
template's section labels. It is written defensively: if a field is missing it
returns an empty value instead of raising, so a slightly different template
still yields a usable (partial) UnitPlan.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from docx import Document

from .models import UnitPlan, MYP_CRITERIA


# Matches an objective heading line such as "A: Investigating" or "B - Developing".
_CRITERION_HEADING = re.compile(
    r"^\s*([A-D])\s*[:\-–.)]\s*([A-Za-z][A-Za-z /]+)", re.MULTILINE
)


def _iter_table_cells(doc: Document) -> List[List[str]]:
    """Return each table row as a list of de-duplicated cell texts.

    Merged cells repeat their text across the row in python-docx; collapsing
    consecutive duplicates gives the logical columns back.
    """
    rows: List[List[str]] = []
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            collapsed: List[str] = []
            for c in cells:
                if not collapsed or collapsed[-1] != c:
                    collapsed.append(c)
            rows.append(collapsed)
    return rows


def _find_label_value(rows: List[List[str]], label: str) -> Optional[str]:
    """Find a value sitting immediately to the right of a label cell."""
    target = label.strip().lower()
    for row in rows:
        for i, cell in enumerate(row):
            if cell.strip().lower() == target and i + 1 < len(row):
                value = row[i + 1].strip()
                if value:
                    return value
    return None


def _find_block_after(rows: List[List[str]], label: str) -> Optional[str]:
    """Find a block of text that follows a standalone label row.

    Used for the Statement of Inquiry, where the label is on its own row and
    the prose sits in the next row.
    """
    target = label.strip().lower()
    for idx, row in enumerate(rows):
        joined = " ".join(row).strip().lower()
        if joined == target or (row and row[0].strip().lower() == target):
            # Look ahead for the next non-empty row.
            for follow in rows[idx + 1 :]:
                text = " ".join(c for c in follow if c).strip()
                if text:
                    return text
    return None


def _split_concepts(raw: str) -> List[str]:
    """Split a key/related-concepts cell into individual concept tokens."""
    if not raw:
        return []
    # Concepts are separated by commas, slashes, semicolons or newlines.
    parts = re.split(r"[,/;\n]+", raw)
    seen, out = set(), []
    for part in parts:
        token = part.strip(" .\t").strip()
        # Drop boilerplate fragments and over-long sentences (not a concept).
        if not token or len(token) > 40:
            continue
        low = token.lower()
        if low in seen or low in {"key concept", "key concept(s)",
                                  "related concept", "related concepts",
                                  "related concept(s)", "concepts"}:
            continue
        seen.add(low)
        out.append(token)
    return out


def _extract_key_concepts(rows: List[List[str]]) -> List[str]:
    """Best-effort pull of MYP key/related concepts from the unit-plan tables.

    Looks for the value beside a "Key concept" / "Related concept(s)" label and
    also scans any cell that names concepts inline. Returns a de-duplicated,
    order-preserving list; an empty list when nothing recognisable is found.
    """
    concepts: List[str] = []
    seen = set()

    def _add(values: List[str]) -> None:
        for v in values:
            low = v.lower()
            if low not in seen:
                seen.add(low)
                concepts.append(v)

    for label in ("Key concept", "Key concepts", "Related concept",
                  "Related concepts"):
        val = _find_label_value(rows, label) or _find_block_after(rows, label)
        if val:
            _add(_split_concepts(val))
    return concepts


def _extract_target_criteria(rows: List[List[str]]) -> Dict[str, str]:
    """Parse the Objectives cell into {letter: heading} pairs."""
    criteria: Dict[str, str] = {}
    for row in rows:
        for cell in row:
            if "objective" in cell.lower() or _CRITERION_HEADING.search(cell):
                for match in _CRITERION_HEADING.finditer(cell):
                    letter = match.group(1).upper()
                    heading = match.group(2).strip().title()
                    # Prefer the canonical heading when we recognise it.
                    criteria[letter] = MYP_CRITERIA.get(letter, heading)
    return criteria


class UnitPlanParser:
    """Parse an MYP unit-plan .docx into a :class:`UnitPlan`."""

    def __init__(self, path: str):
        self.path = path
        self._doc = Document(path)
        self._rows = _iter_table_cells(self._doc)

    def parse(self) -> UnitPlan:
        unit_title = (
            _find_label_value(self._rows, "Unit title")
            or _find_label_value(self._rows, "Unit Title")
            or ""
        )
        soi = _find_block_after(self._rows, "Statement of inquiry") or ""
        criteria = _extract_target_criteria(self._rows)
        key_concepts = _extract_key_concepts(self._rows)
        myp_year = _find_label_value(self._rows, "MYP year")

        return UnitPlan(
            unit_title=unit_title,
            statement_of_inquiry=soi,
            target_criteria=criteria,
            key_concepts=key_concepts,
            myp_year=myp_year,
            source_file=self.path,
        )


def parse_unit_plan(path: str) -> UnitPlan:
    """Convenience wrapper: parse a unit-plan docx in one call."""
    return UnitPlanParser(path).parse()
