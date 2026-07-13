"""
CSV data-ingestion pipeline (hybrid capture).

Reads a grading export (one row per student) into the :class:`Gradebook`,
keyed by Student Name/ID. The capture method is decided from the header row,
so the same method handles both legacy single-grade files and future
multi-criterion files:

1. **Auto** - any column that explicitly names a criterion (e.g.
   ``"Grade (Crit A)"`` or ``"Crit B"``) is ingested into that criterion. One
   file can therefore populate 1-4 criteria at once.
2. **Manual** - if no criterion is named but a generic ``"Grade"`` column
   exists, the caller passes ``manual_criterion_target`` to declare which
   criterion the column belongs to (the legacy-CSV path the upload UI drives).
3. **Formative (0 criteria)** - if there is no criterion column and no generic
   grade column, nothing is scored; the assignment is still registered as a
   placeholder on the timeline (a skipped week or purely formative event).

Timestamp handling
------------------
The export does not contain an explicit assessment date, but the "Files
(newest first)" column frequently embeds one inside the filename, e.g.

    "Changing Views (Crit B) (Apr 28, 2026 at 9:11 AM).jpg"
    "Changing Views (Crit B)（2026年5月10日（19:12））.png"
    "Screenshot 2026-04-27 at 9.19.49.png"

The durable export additionally carries an explicit per-row ``Due Date``
column (ISO-8601) — the assignment's deadline — which is the authoritative date
when present (older exports used ``Assessed Date``, still accepted as a
fallback). Each row's timestamp resolves in priority order:

    1. A per-student override date supplied by the user.
    2. A global override date supplied for the whole import.
    3. The ISO date in the row's ``Due Date`` column (the deadline; durable
       format), falling back to a legacy ``Assessed Date`` column.
    4. A date parsed out of the (newest) filename (legacy fallback).
    5. The ingestion run time (fallback).

Invalid rows (e.g. grade 0 with a "wrong assignment" comment) are still
ingested but flagged ``is_valid=False`` so they are preserved but excluded
from aggregation.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import (
    Assignment,
    Criterion,
    CriterionScore,
    ExamResult,
    Gradebook,
    section_max,
)


# --- header -> criterion detection -----------------------------------------

# Matches a criterion declared inside a column header, e.g.
#   "Grade (Crit A)" -> A   "Crit B" -> B   "Criterion C" -> C
#   "Grade (Criterion D)" -> D
_CRIT_HEADER = re.compile(r"crit(?:erion)?\.?\s*\(?\s*([A-D])\b", re.IGNORECASE)


def detect_criterion_in_header(header: str) -> Optional[Criterion]:
    """Return the Criterion named inside a column header, or None if generic."""
    if not header:
        return None
    m = _CRIT_HEADER.search(header)
    if m:
        return Criterion(m.group(1).upper())
    return None


def map_criterion_columns(fieldnames: List[str]) -> Dict[str, Criterion]:
    """Map each grade-bearing header to the criterion it explicitly names."""
    mapping: Dict[str, Criterion] = {}
    for name in fieldnames or []:
        crit = detect_criterion_in_header(name)
        if crit is not None:
            mapping[name] = crit
    return mapping


# --- assignment-name cleaning (strip export suffixes / deadlines) -----------

# The grading app exports one CSV per assignment, naming the file with the
# assignment, a "Grades" tag, and the deadline/date, e.g.
#   "Artist Looking_Grades_2026-05-10.csv"  -> "Artist Looking"
#   "Changing Views (Crit B)_Grades.csv"    -> "Changing Views (Crit B)"
# We trim those trailing tokens so the timeline shows only the clean assignment
# name, while deliberately preserving an embedded "(Crit X)" hint (criterion
# detection relies on it) and any meaningful name text.

# A date anywhere from the first separator onward: YYYY-MM-DD / YYYY_MM_DD /
# YYYY.MM.DD (and anything trailing it, e.g. a time stamp).
_FNAME_DATE_TAIL = re.compile(
    r"[ _\-]*\d{4}[._\-]\d{1,2}[._\-]\d{1,2}.*$"
)
# A trailing "Grades" tag (with optional leading separator) and anything after.
_GRADES_TAIL = re.compile(r"[ _\-]*grades\b.*$", re.IGNORECASE)


def clean_assignment_name(raw: str) -> str:
    """Trim export suffixes/deadlines from a grading-CSV filename stem.

    Removes a trailing date (``2026-05-10`` and anything after it) and a
    trailing ``Grades`` tag, then strips leftover separators/whitespace, so a
    file named ``"Artist Looking_Grades_2026-05-10"`` yields ``"Artist
    Looking"``. An embedded ``(Crit X)`` marker and the core name are kept. If
    trimming would empty the string, the original (stripped) value is returned
    so an oddly-named file never collapses to "".
    """
    if not raw:
        return ""
    name = str(raw).strip()
    cleaned = _FNAME_DATE_TAIL.sub("", name)
    cleaned = _GRADES_TAIL.sub("", cleaned)
    # Tidy any trailing separators left behind by the trims.
    cleaned = cleaned.strip(" _-\t").strip()
    return cleaned or name


# --- filename date parsing -------------------------------------------------

# "Apr 28, 2026 at 9:11 AM"  /  "May 7, 2026"
_EN_DATE = re.compile(
    r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})"
    r"(?:\s+at\s+(\d{1,2}):(\d{2})\s*([AP]M))?"
)
# "2026-04-27 at 9.19.49"  /  "2026-05-11"
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Japanese: "2026年5月10日（19:12）" or "2026年5月10日"
_JP_DATE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日")

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def parse_iso_date(text: str) -> Optional[datetime]:
    """Parse a value from the durable ``Assessed Date`` CSV column.

    The durable export embeds the assessment date directly in each row as an
    ISO-8601 string, e.g. ``"2026-05-10"`` or ``"2026-05-10T19:12:00"``. This
    is the authoritative date when present, so it is parsed strictly (via
    :func:`datetime.fromisoformat`) and only falls back to the looser
    filename-style ISO matcher if the cell holds a date in some other shape.
    Returns ``None`` for blank or unparseable cells so a legacy file missing
    the column degrades cleanly to the filename/runtime fallbacks.
    """
    if not text:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    # Tolerate a trailing 'Z' (UTC marker) that fromisoformat rejected pre-3.11.
    candidate = raw[:-1] if raw.endswith("Z") else raw
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    # Fall back to a bare YYYY-MM-DD found anywhere in the cell.
    m = _ISO_DATE.search(raw)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def parse_date_from_filename(text: str) -> Optional[datetime]:
    """Best-effort extraction of a datetime from a filename string."""
    if not text:
        return None

    m = _EN_DATE.search(text)
    if m:
        mon, day, year = _MONTHS.get(m.group(1)), int(m.group(2)), int(m.group(3))
        if mon:
            hour, minute = 0, 0
            if m.group(4):
                hour, minute = int(m.group(4)), int(m.group(5))
                if m.group(6) == "PM" and hour != 12:
                    hour += 12
                elif m.group(6) == "AM" and hour == 12:
                    hour = 0
            return datetime(year, mon, day, hour, minute)

    m = _JP_DATE.search(text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _ISO_DATE.search(text)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    return None


def _split_keywords(raw: str) -> List[str]:
    if not raw:
        return []
    return [k.strip() for k in raw.split(";") if k.strip()]


def _looks_invalid(grade: int, comment: str) -> Optional[str]:
    """Return a reason string if a row should be flagged invalid."""
    c = (comment or "").lower()
    if "wrong assignment" in c or "wrong submission" in c:
        return "Flagged: wrong assignment"
    if grade == 0 and not c:
        return "Flagged: zero grade, no comment"
    return None


# --- roster-aware identity routing (optional, backward-compatible) ----------
#
# The grading CSV identifies a student only by the "Student Name" cell — which
# for anonymous/local marking is a filename stem or subfolder name, NOT a roster
# id. Left unrouted, an unmatched cell silently mints a phantom student. When the
# caller supplies the class roster's keys, each row's id is instead *routed*:
#   1. exact roster key         -> ingest under it;
#   2. known alias              -> ingest under aliases[id];
#   3. unambiguous prefix match -> ingest under it + report the auto-alias;
#   4. no match                 -> route the whole row out for visual matching.
# With no roster_keys the whole mechanism is skipped and every row is ingested
# under its raw id (legacy behaviour, byte-identical). Never fuzzy/edit-distance
# (siblings mis-assign eventually and misattribution is expensive to claw back).

_IDENTITY_STRIP = re.compile(r"[\s_\-]+")


def _normalize_identity(key: str) -> str:
    """Casefold + strip spaces / underscores / hyphens, for prefix comparison."""
    return _IDENTITY_STRIP.sub("", str(key or "")).casefold()


def resolve_identity(sid, roster_keys, aliases=None):
    """Route one CSV id to a roster key. Returns ``(target_key, auto_alias)``.

    ``target_key`` is the roster key to ingest under, or ``None`` when the row
    is unmatched (pool it). ``auto_alias`` is the roster key only when the match
    came from the fast *prefix* path (step 3), so the caller records it durably
    and never re-derives it; it is ``None`` for exact/alias hits and misses.

    Prefix matching normalizes both sides (casefold + strip spaces/`_`/`-`) and
    accepts either direction (a roster key that is a prefix of the id, e.g.
    ``0001`` ⊂ ``0001a``, or an id that is a prefix of a roster key, e.g. a
    truncated ``1234`` ⊂ ``12345``). The **longest** normalized candidate wins;
    a tie at that longest length, or any ambiguity between siblings, yields no
    match so the row pools rather than mis-assigns."""
    if not roster_keys:
        return sid, None
    aliases = aliases or {}
    if sid in roster_keys:
        return sid, None
    if sid in aliases:
        return aliases[sid], None
    n_sid = _normalize_identity(sid)
    if not n_sid:
        return None, None
    candidates = []
    for rk in roster_keys:
        n_rk = _normalize_identity(rk)
        if not n_rk:
            continue
        if n_sid.startswith(n_rk) or n_rk.startswith(n_sid):
            candidates.append((rk, n_rk))
    if not candidates:
        return None, None
    longest = max(len(n_rk) for _, n_rk in candidates)
    top = [rk for rk, n_rk in candidates if len(n_rk) == longest]
    if len(top) != 1:
        return None, None          # tie / double-match -> pool it, never guess
    return top[0], top[0]


# --- roster ingestion / fuzzy student-ID matching --------------------------
#
# The grading-app CSVs identify a student only by a bare numeric ID in the
# "Student Name" column (e.g. ``100001``). That number is the *local part* of
# the student's school email address -- the string before the ``@`` -- so the
# Google Classroom roster export, which carries the real display names and the
# email column, is the bridge between the friendly name shown to the teacher
# and the numeric key the gradebook is keyed on.
#
# Matching therefore reduces to: read the roster email, drop everything from
# ``@`` onward, isolate the leading numeric ID, and use that as the join key.

# Leading run of digits in an email local-part, e.g. "100001" in
# "100001.jane" or "100001s".
_LEADING_ID = re.compile(r"^\D*?(\d+)")
# Any run of digits, used as a fallback when the ID is not at the very start.
_ANY_ID = re.compile(r"(\d+)")


def student_id_from_email(email: str) -> str:
    """Resolve the numeric student ID embedded in a school email address.

    The grading sheet's numeric IDs are the email *local part* (the substring
    before ``@``). This strips the domain and isolates the leading numeric ID
    so a roster row resolves onto the matching gradebook record:

        "100001@school.ed.jp"      -> "100001"
        "100001.jane@school.org"   -> "100001"
        "s100001@school.org"       -> "100001"

    Falls back to the first digit run anywhere in the local part, and finally
    to the trimmed local part itself, so a malformed address never crashes the
    import -- it simply may not match.
    """
    if not email:
        return ""
    local = str(email).split("@", 1)[0].strip()
    if not local:
        return ""
    m = _LEADING_ID.match(local)
    if m:
        return m.group(1)
    m = _ANY_ID.search(local)
    if m:
        return m.group(1)
    return local


def _roster_column_index(header: List[str], *names: str) -> Optional[int]:
    lower = [h.strip().lower() for h in header]
    for n in names:
        if n in lower:
            return lower.index(n)
    return None


def parse_classroom_roster(text: str) -> List[Dict[str, str]]:
    """Parse a Google Classroom roster/grade template into matchable entries.

    Returns one dict per student::

        {"key": <numeric id>, "name": <display name>, "email": <raw email>}

    ``key`` is the numeric student ID resolved from the email column (see
    :func:`student_id_from_email`) and is what the gradebook is keyed on, so a
    roster loaded this way lines up directly with ingested grades -- no more
    spurious ``missing`` flags caused by comparing names against numeric IDs.

    The parser is tolerant of the Classroom export's quirks: it locates the
    email column by header name *or* by sniffing which column holds ``@``
    values, and it skips the blank/instruction rows Classroom places under the
    header in its "empty template" download.
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return []

    header = rows[0]
    i_email = _roster_column_index(
        header, "email address", "email", "e-mail", "username", "email_address"
    )
    i_name = _roster_column_index(
        header, "student name", "name", "student", "full name"
    )
    i_first = _roster_column_index(header, "first name", "given name", "first")
    i_last = _roster_column_index(
        header, "last name", "surname", "family name", "last")

    # If no email header was found, sniff for the column most full of '@'.
    if i_email is None:
        best, best_hits = None, 0
        ncols = max((len(r) for r in rows[1:]), default=0)
        for c in range(ncols):
            hits = sum(1 for r in rows[1:] if c < len(r) and "@" in r[c])
            if hits > best_hits:
                best, best_hits = c, hits
        i_email = best

    has_email_col = i_email is not None
    out: List[Dict[str, str]] = []
    seen_keys = set()
    for r in rows[1:]:
        if not any(cell.strip() for cell in r):
            continue  # blank spacer row
        email = r[i_email].strip() if (i_email is not None and i_email < len(r)) else ""

        # Display name as "Surname First" for the roster list. Prefer explicit
        # first/last (incl. "Surname") columns, reordered to surname-first;
        # otherwise use the single name column as-is; finally fall back to the
        # email local part. ``first`` is kept separately so report comments can
        # address the student by first name only.
        first = r[i_first].strip() if (i_first is not None and i_first < len(r)) else ""
        last = r[i_last].strip() if (i_last is not None and i_last < len(r)) else ""
        if first or last:
            name = (f"{last} {first}".strip()) or (last or first)
        elif i_name is not None and i_name < len(r) and r[i_name].strip():
            name = r[i_name].strip()
        else:
            name = email.split("@", 1)[0].strip() if email else ""

        if has_email_col:
            # Real students carry an email; Classroom's instruction / "Points"
            # rows under the header do not, so an address without '@' is skipped.
            if "@" not in email:
                continue
            key = student_id_from_email(email)
        else:
            # No email column anywhere: fall back to a name key (legacy roster).
            key = name
        if not key or key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({"key": key, "name": name or key, "email": email,
                    "first": first, "gender": ""})
    return out


# --- exam (item-level) CSV detection ----------------------------------------
#
# The CAM grading app's Exam Slicing feature exports one column per programmed
# question BEFORE a "Total Score" column:
#
#     Student Name, Q1, Q2, ..., Total Score, Max Total, Due Date, Comment
#
# The total is a raw mark (e.g. 37/45), NOT an MYP 0-8 band, so these files
# must never flow through the criterion-score path. Detection is by header:
# a "Total Score" column marks the file as an exam export.

EXAM_TOTAL_HEADER = "Total Score"
EXAM_MAX_HEADER = "Max Total"

# Headers that are metadata rather than question columns (lowercased).
_EXAM_RESERVED = {
    "student name", "total score", "max total", "due date", "comment",
    "checked keywords", "files (newest first)", "assessed date", "file count",
}


def load_exam_sidecar(csv_path: str) -> Optional[List[Dict[str, Any]]]:
    """Read the ``<csv>.meta.json`` definition sidecar's ``sections`` list.

    Written by CGW beside every routed exam CSV (Phase 4C), the sidecar carries
    the section structure the flat CSV cannot express. Returns the ``sections``
    list (``[{"name", "required", "questions": [{"label", "max"}]}]``) or None
    when the sidecar is absent, unreadable, or shaped wrong — the caller then
    keeps today's sidecar-less behaviour, never erroring.
    """
    meta_path = csv_path + ".meta.json"
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, "r", encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(meta, dict):
        return None
    sections = meta.get("sections")
    if not isinstance(sections, list) or not sections:
        return None
    clean: List[Dict[str, Any]] = []
    for sec in sections:
        if not isinstance(sec, dict) or not sec.get("name"):
            continue
        req = sec.get("required")
        try:
            req = int(req) if req is not None else None
        except (TypeError, ValueError):
            req = None
        questions = []
        for q in (sec.get("questions") or []):
            if isinstance(q, dict) and q.get("label") is not None:
                try:
                    qmax = int(q.get("max", 0) or 0)
                except (TypeError, ValueError):
                    qmax = 0
                questions.append({"label": str(q["label"]), "max": qmax})
        clean.append({"name": str(sec["name"]), "required": req,
                      "questions": questions})
    return clean or None


def is_exam_csv(fieldnames: List[str]) -> bool:
    """True when a header row is a CAM item-level exam export."""
    lower = {(h or "").strip().lower() for h in (fieldnames or [])}
    return "total score" in lower and "student name" in lower


def exam_question_columns(fieldnames: List[str]) -> List[str]:
    """The question-label columns of an exam export, in grading order."""
    out = []
    for h in fieldnames or []:
        name = (h or "").strip()
        if name and name.lower() not in _EXAM_RESERVED:
            out.append(name)
    return out


class IngestionPipeline:
    """Reads grading CSVs into a shared :class:`Gradebook`."""

    def __init__(self, gradebook: Optional[Gradebook] = None):
        self.gradebook = gradebook if gradebook is not None else Gradebook()

    def ingest_csv(
        self,
        path: str,
        assignment: str,
        *,
        manual_criterion_target: Optional[Criterion] = None,
        id_column: str = "Student Name",
        grade_column: str = "Grade",
        keywords_column: str = "Checked Keywords",
        comment_column: str = "Comment",
        files_column: str = "Files (newest first)",
        due_date_column: str = "Due Date",
        late_column: str = "Late",
        global_override_date: Optional[datetime] = None,
        per_student_override: Optional[Dict[str, datetime]] = None,
        ingest_time: Optional[datetime] = None,
        roster_keys: Optional[set] = None,
        aliases: Optional[Dict[str, str]] = None,
        unmatched_out: Optional[List[dict]] = None,
        auto_aliases_out: Optional[Dict[str, str]] = None,
    ) -> List[CriterionScore]:
        """Ingest one CSV export into the gradebook (hybrid mapping).

        Capture method is decided from the header row (see module docstring):
        auto criterion columns, a manually-targeted generic Grade column, or a
        0-criterion formative event. Returns the list of scores created. The
        assignment's metadata (including the criteria it touched) is always
        registered, even when it produces no scores.

        **Roster-aware identity routing (opt-in, backward-compatible).** When
        ``roster_keys`` is a non-empty set, each row's ``Student Name`` id is
        routed through :func:`resolve_identity` (exact → alias → unambiguous
        prefix → unmatched) instead of blindly minting a student:

        * ``aliases`` — a durable ``{csv_key: roster_key}`` map (the caller's
          manual + previously auto-recorded matches) consulted before prefixing.
        * ``unmatched_out`` — if given, every unmatched row that carried grades
          is appended as a self-contained dict (``csv_key``, ``grades`` as
          ``[[letter, band], …]``, ``keywords``, ``comment``, ``files``,
          ``late``, ``timestamp``) so the caller can pool it for visual matching
          and later re-materialize it via :meth:`materialize_row`.
        * ``auto_aliases_out`` — if given, each fast-path prefix match records
          ``{csv_key: roster_key}`` so the caller can persist it and stop
          re-deriving (and re-announcing) it on the next sync.

        With ``roster_keys`` falsy (the default) none of this runs and every row
        is ingested under its raw id exactly as before — every existing caller is
        byte-identical."""
        per_student_override = per_student_override or {}
        ingest_time = ingest_time or datetime.now()
        created: List[CriterionScore] = []

        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = reader.fieldnames or []

            # Decide which columns carry grades and for which criterion.
            column_map = self._resolve_column_map(
                fieldnames, grade_column, manual_criterion_target
            )

            # Durable format: locate the explicit per-row date column (by exact
            # name, else a case-insensitive match) so legacy files without it
            # simply fall through to the filename/runtime fallbacks. The current
            # export carries a "Due Date" (the deadline); older files used
            # "Assessed Date", which is accepted as a fallback.
            date_column = self._resolve_date_column(
                fieldnames, due_date_column, "Assessed Date"
            )

            # Optional lateness column (the durable export's "Late"). Absent in
            # legacy CSVs -> resolves to None and every score defaults late=False.
            # Matched exactly first, then case/whitespace-insensitively so a
            # "late" or " Late " header still resolves.
            late_col = None
            want_late = (late_column or "").strip().lower()
            if want_late:
                for cand in fieldnames:
                    if cand and cand.strip().lower() == want_late:
                        late_col = cand
                        break

            for row in reader:
                sid = (row.get(id_column) or "").strip()
                if not sid:
                    continue

                comment = (row.get(comment_column) or "").strip()
                keywords = _split_keywords(row.get(keywords_column, ""))
                files = (row.get(files_column) or "").strip()
                csv_date = (
                    parse_iso_date(row.get(date_column))
                    if date_column else None
                )
                # Tri-state Late cell -> bool: "1"/"true"/"yes" are late,
                # everything else (incl. "0" and blank/never-assessed "") is not.
                late = False
                if late_col:
                    late = (row.get(late_col) or "").strip().lower() in {
                        "1", "true", "yes"}
                timestamp = self._resolve_timestamp(
                    sid, files, per_student_override,
                    global_override_date, ingest_time,
                    csv_date=csv_date,
                )

                # One row can yield a score per mapped criterion column. Collect
                # them as ordered (criterion, band) pairs first — preserving
                # multiplicity if two columns name the same criterion — so the
                # row can be routed as a unit (byte-identical to the old inline
                # loop when no routing is in play).
                row_grades = []
                for column, criterion in column_map.items():
                    grade = self._coerce_grade(row.get(column))
                    if grade is None:
                        continue
                    row_grades.append((criterion, grade))

                # Identity routing (skipped entirely when roster_keys is falsy →
                # legacy: target is the raw id and nothing pools).
                target = sid
                if roster_keys:
                    target, auto_alias = resolve_identity(sid, roster_keys, aliases)
                    if target is None:
                        # Unmatched → pool the whole row for visual matching, but
                        # only when it carried grades (a grade-less row minted no
                        # student before either, so it pools nothing).
                        if unmatched_out is not None and row_grades:
                            unmatched_out.append({
                                "csv_key": sid,
                                "grades": [[c.value, g] for c, g in row_grades],
                                "keywords": list(keywords),
                                "comment": comment,
                                "files": files,
                                "late": late,
                                "timestamp": timestamp.isoformat(),
                            })
                        continue
                    if auto_alias is not None and auto_aliases_out is not None:
                        auto_aliases_out[sid] = auto_alias

                self._apply_grades(target, assignment, row_grades, comment,
                                   keywords, timestamp, late, created)

        # Register the assignment metadata (0-4 criteria).
        criteria_letters = sorted({c.value for c in column_map.values()})
        self.gradebook.register_assignment(
            Assignment(
                name=assignment,
                criteria=criteria_letters,
                source_file=path,
                ingested_at=ingest_time,
                score_count=len(created),
                note="formative / skipped week - no grades"
                if not criteria_letters
                else "",
            )
        )
        return created

    def _apply_grades(self, target_sid, assignment, row_grades, comment,
                      keywords, timestamp, late, created):
        """Build a CriterionScore per (criterion, band) pair and add it to the
        gradebook under ``target_sid``. The single score-construction path shared
        by ``ingest_csv``'s per-row loop and :meth:`materialize_row`, so a work
        assigned via the Window-2 matcher is scored identically to a re-sync
        routed through the recorded alias. ``get_or_create`` runs only when there
        is a grade to add — a grade-less row mints no student (unchanged)."""
        for criterion, grade in row_grades:
            reason = _looks_invalid(grade, comment)
            score = CriterionScore(
                criterion=criterion,
                value=grade,
                timestamp=timestamp,
                source=f"csv:{assignment}",
                assignment=assignment,
                keywords=keywords,
                comment=comment,
                is_valid=reason is None,
                note=reason or "",
                late=late,
            )
            self.gradebook.get_or_create(target_sid).add_score(score)
            created.append(score)

    def materialize_row(self, assignment: str, target_sid: str,
                        pool_row: dict) -> List[CriterionScore]:
        """Re-create the scores for one pooled *unmatched* row under
        ``target_sid``.

        ``pool_row`` is a dict :meth:`ingest_csv` appended to its
        ``unmatched_out`` collection. Uses the identical score-construction path
        (:meth:`_apply_grades`) as a normal ingest, so a work resolved through
        the Window-2 matcher produces exactly the scores a subsequent re-sync —
        routed through the now-recorded alias — would. Returns the scores
        created."""
        row_grades = [(Criterion(c), int(g))
                      for c, g in (pool_row.get("grades") or [])]
        timestamp = parse_iso_date(pool_row.get("timestamp")) or datetime.now()
        created: List[CriterionScore] = []
        self._apply_grades(
            target_sid, assignment, row_grades,
            pool_row.get("comment", "") or "",
            list(pool_row.get("keywords") or []),
            timestamp, bool(pool_row.get("late")), created)
        return created

    def _carry_forward_chosen(self, target_sid: str,
                              result: ExamResult) -> None:
        """Copy the prior result's teacher choice-section picks onto ``result``.

        Shared by :meth:`ingest_exam_csv`'s per-row loop and
        :meth:`materialize_exam_row` so a re-ingest and a Window-2 match
        preserve resolutions identically. Only picks whose labels the fresh
        result still has a mark for survive."""
        prev = self.gradebook.students.get(target_sid)
        prev_result = (prev.exam_results.get(result.assignment)
                       if prev is not None else None)
        if prev_result is not None and prev_result.chosen:
            for sec_name, picks in prev_result.chosen.items():
                kept = [lbl for lbl in picks if lbl in result.questions]
                if kept:
                    result.chosen[str(sec_name)] = kept

    def materialize_exam_row(self, assignment: str, target_sid: str,
                             pool_row: dict) -> ExamResult:
        """Re-create the :class:`ExamResult` for one pooled *unmatched* exam row
        under ``target_sid``.

        ``pool_row`` is an ``is_exam`` dict :meth:`ingest_exam_csv` appended to
        its ``unmatched_out`` collection — the exam sibling of
        :meth:`materialize_row`. Builds the same result a routed ingest would
        (including the ``chosen`` carry-forward for still-answered labels, so a
        prior resolution made under the roster key survives a re-match) and
        attaches it to the roster student. Returns the result created."""
        questions: Dict[str, int] = {}
        for lbl, val in (pool_row.get("questions") or {}).items():
            try:
                questions[str(lbl)] = max(0, int(val))
            except (TypeError, ValueError):
                continue
        try:
            total = max(0, int(pool_row.get("total")))
        except (TypeError, ValueError):
            total = sum(questions.values())
        try:
            max_total = max(0, int(pool_row.get("max_total") or 0))
        except (TypeError, ValueError):
            max_total = 0
        result = ExamResult(
            assignment=assignment,
            total=total,
            max_total=max_total,
            questions=questions,
            comment=str(pool_row.get("comment") or ""),
        )
        self._carry_forward_chosen(target_sid, result)
        self.gradebook.get_or_create(target_sid).exam_results[assignment] = result
        return result

    def ingest_exam_csv(
        self,
        path: str,
        assignment: str,
        *,
        id_column: str = "Student Name",
        ingest_time: Optional[datetime] = None,
        roster_keys: Optional[set] = None,
        aliases: Optional[Dict[str, str]] = None,
        unmatched_out: Optional[List[dict]] = None,
        auto_aliases_out: Optional[Dict[str, str]] = None,
    ) -> List[ExamResult]:
        """Ingest a CAM item-level exam export (raw marks, off the 0-8 scale).

        Each row becomes an :class:`ExamResult` on the student (per-question
        raw marks + total), and the assignment is registered with
        ``is_exam=True`` and zero criteria: raw exam marks contribute nothing
        to the recency-weighted band math until the teacher assigns each
        student a 0-8 band (the Window 1 exam-banding dropdown), which then
        enters the gradebook as an ordinary ``CriterionScore``. Returns the
        results created.

        **Roster-aware identity routing (opt-in, backward-compatible).** The
        exam CSV's ``Student Name`` cell is a PDF filename stem, not a roster
        id, so an unrouted ingest mints a phantom student per unmatched row.
        When ``roster_keys`` is a non-empty set, each row is routed through the
        same :func:`resolve_identity` pipeline as :meth:`ingest_csv` (exact →
        alias → unambiguous prefix → unmatched) — never a phantom:

        * matched rows attach their :class:`ExamResult` to the *resolved*
          roster student (the ``chosen`` carry-forward is keyed on it too);
        * unmatched rows append an exam-flavoured pool row to
          ``unmatched_out`` — the assignment path's ``csv_key`` field plus
          ``is_exam: True``, ``questions``, ``total``, ``max_total`` and
          ``comment`` (everything :meth:`materialize_exam_row` needs);
        * fast-path prefix matches record ``{csv_key: roster_key}`` into
          ``auto_aliases_out`` for the caller to persist.

        With ``roster_keys`` falsy (the default) none of this runs and every
        row is ingested under its raw id exactly as before."""
        ingest_time = ingest_time or datetime.now()
        created: List[ExamResult] = []
        max_total = 0
        labels: List[str] = []
        exam_date: Optional[datetime] = None
        pool_start = len(unmatched_out) if unmatched_out is not None else 0

        with open(path, "r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fieldnames = [(h or "").strip() for h in (reader.fieldnames or [])]
            if not is_exam_csv(fieldnames):
                raise ValueError(
                    f"{path!r} is not an exam export (no '{EXAM_TOTAL_HEADER}' "
                    f"column)."
                )
            labels = exam_question_columns(fieldnames)
            date_column = self._resolve_date_column(fieldnames, "Due Date")

            for row in reader:
                row = {(k or "").strip(): v for k, v in row.items()}
                sid = (row.get(id_column) or "").strip()
                if not sid:
                    continue
                questions = {}
                for lbl in labels:
                    val = self._coerce_raw_mark(row.get(lbl))
                    if val is not None:
                        questions[lbl] = val
                total = self._coerce_raw_mark(row.get(EXAM_TOTAL_HEADER))
                if total is None:
                    total = sum(questions.values())
                row_max = self._coerce_raw_mark(row.get(EXAM_MAX_HEADER)) or 0
                max_total = max(max_total, row_max)
                if exam_date is None and date_column:
                    exam_date = parse_iso_date(row.get(date_column))
                comment = (row.get("Comment") or "").strip()

                # Identity routing (skipped entirely when roster_keys is falsy →
                # legacy: target is the raw id and nothing pools).
                target = sid
                if roster_keys:
                    target, auto_alias = resolve_identity(sid, roster_keys,
                                                          aliases)
                    if target is None:
                        # Unmatched → pool an exam-flavoured row for visual
                        # matching (never mint a phantom student). Every exam
                        # row is a real script (CGW writes one per student
                        # PDF), so unlike the grade-less assignment rows there
                        # is no "carried nothing" skip.
                        if unmatched_out is not None:
                            unmatched_out.append({
                                "csv_key": sid,
                                "is_exam": True,
                                "questions": dict(questions),
                                "total": total,
                                "max_total": row_max,
                                "comment": comment,
                            })
                        continue
                    if auto_alias is not None and auto_aliases_out is not None:
                        auto_aliases_out[sid] = auto_alias

                result = ExamResult(
                    assignment=assignment,
                    total=total,
                    max_total=row_max,
                    questions=questions,
                    comment=comment,
                )
                # Preserve teacher choice-section resolutions across re-ingest
                # (purge-replace must not wipe them — same spirit as the Late
                # reconcile). Carry forward only picks whose labels the student
                # still has a mark for in the fresh CSV — keyed on the RESOLVED
                # student, so an alias-routed re-sync finds the picks made
                # under the roster key.
                self._carry_forward_chosen(target, result)
                self.gradebook.get_or_create(target).exam_results[assignment] = result
                created.append(result)

        # Backfill the sheet-wide max onto rows whose Max Total cell was blank —
        # pooled unmatched rows included, so a later materialization carries the
        # same max a routed ingest would have.
        new_pool = (unmatched_out[pool_start:]
                    if unmatched_out is not None else [])
        for r in created:
            if not r.max_total:
                r.max_total = max_total
        for pr in new_pool:
            if not pr.get("max_total"):
                pr["max_total"] = max_total

        # Definition sidecar (Phase 5B): when CGW dropped a <csv>.meta.json,
        # attach its section structure and recompute every result's max via the
        # resolved (choice-aware) rule. Absent/corrupt sidecar → sidecar-less
        # behaviour, byte-identical to before this phase.
        sections = load_exam_sidecar(path)
        if sections:
            section_total_max = sum(section_max(s) for s in sections)
            for r in created:
                r.max_total = section_total_max
            for pr in new_pool:
                pr["max_total"] = section_total_max
            max_total = section_total_max

        self.gradebook.register_assignment(
            Assignment(
                name=assignment,
                criteria=[],
                source_file=path,
                ingested_at=exam_date or ingest_time,
                score_count=len(created),
                note="exam — raw item-level marks; assign 0-8 bands in Window 1",
                is_exam=True,
                max_total=max_total,
                question_labels=labels,
                sections=sections,
            )
        )
        return created

    @staticmethod
    def _coerce_raw_mark(raw: Optional[str]) -> Optional[int]:
        """Raw exam marks are unbounded ints (unlike 0-8 band grades)."""
        if raw is None or str(raw).strip() == "":
            return None
        try:
            return max(0, int(float(str(raw).strip())))
        except ValueError:
            return None

    @staticmethod
    def _resolve_column_map(
        fieldnames: List[str],
        grade_column: str,
        manual_criterion_target: Optional[Criterion],
    ) -> Dict[str, Criterion]:
        """Build {column -> Criterion} per the hybrid capture rules."""
        auto = map_criterion_columns(fieldnames)
        if auto:
            # Criterion columns win; a generic "Grade" alongside is ignored.
            return auto
        if grade_column in fieldnames:
            if manual_criterion_target is None:
                raise ValueError(
                    f"Column {grade_column!r} is generic (no criterion named in "
                    f"the headers). Pass manual_criterion_target=Criterion.X to "
                    f"declare which criterion it belongs to."
                )
            return {grade_column: Criterion(manual_criterion_target)}
        # No gradeable columns at all -> 0-criterion (formative) assignment.
        return {}

    # --- helpers -----------------------------------------------------------

    @staticmethod
    def _resolve_date_column(
        fieldnames: List[str], *candidates: str
    ) -> Optional[str]:
        """Return the actual header for the deadline/date column, or None.

        Tries each candidate header in priority order (e.g. ``"Due Date"`` then
        the legacy ``"Assessed Date"``). For each, prefers an exact match, then
        falls back to a case-insensitive / whitespace-tolerant match so
        ``"due date"`` or ``" Due Date "`` still resolve. None means the file
        carries none of the candidate columns and should degrade to the
        filename/runtime fallbacks.
        """
        if not fieldnames:
            return None
        for candidate in candidates:
            if not candidate:
                continue
            if candidate in fieldnames:
                return candidate
            target = candidate.strip().lower()
            for name in fieldnames:
                if (name or "").strip().lower() == target:
                    return name
        return None

    @staticmethod
    def _coerce_grade(raw: Optional[str]) -> Optional[int]:
        if raw is None or str(raw).strip() == "":
            return None
        try:
            value = int(float(str(raw).strip()))
        except ValueError:
            return None
        return max(0, min(8, value))

    @staticmethod
    def _resolve_timestamp(
        sid: str,
        files: str,
        per_student_override: Dict[str, datetime],
        global_override_date: Optional[datetime],
        ingest_time: datetime,
        csv_date: Optional[datetime] = None,
    ) -> datetime:
        """Resolve a row's timestamp by the strict priority order:

        1) per-student override, 2) global override, 3) the durable ``Due Date``
        (deadline) CSV column (legacy ``Assessed Date`` as a fallback),
        4) the filename date, 5) ingest time.
        """
        if sid in per_student_override:
            return per_student_override[sid]
        if global_override_date is not None:
            return global_override_date
        # Durable format: the explicit per-row assessed date outranks anything
        # guessed from a filename.
        if csv_date is not None:
            return csv_date
        # Legacy fallback: the export lists files newest-first; first date wins.
        for token in files.split(";"):
            parsed = parse_date_from_filename(token)
            if parsed:
                return parsed
        return ingest_time
