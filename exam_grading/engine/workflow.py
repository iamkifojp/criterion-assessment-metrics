"""Steps 1–3 as operations on an open session.

Each function works on a session (``storage.Session``) and its in-memory
config dict; callers save the config afterwards. Nothing here knows about
Flask, so the whole flow can be tested directly.
"""

from __future__ import annotations

import os
import shutil
from typing import Callable, List, Optional

from . import grading_summary, model, pages, rubrics, slicer, storage
from .errors import UserError
from .slicer import Layout

Progress = Optional[Callable[[int, int], None]]
MAX_MARKS = 100
MAX_LABEL = 20


# --- Step 1: scans -------------------------------------------------------------------

def inspect_scans_folder(path: str) -> dict:
    """A folder of scans: one file per student, or one photo per page."""
    if not path or not os.path.isdir(path):
        raise UserError("folder_unreadable", folder=path or "")
    files = slicer.list_scan_files(path)
    if not files:
        raise UserError("no_scans_found", folder=path)
    detected = slicer.detect_paper(files[0])
    return {"path": os.path.abspath(path), "count": len(files),
            "pages": sum(slicer.page_count(f) for f in files),
            "names": [os.path.basename(f) for f in files[:200]],
            "paper": detected[0] if detected else None,
            "landscape": detected[1] if detected else False}


def inspect_combined_pdf(path: str) -> dict:
    if not path or not os.path.isfile(path) or not path.lower().endswith(".pdf"):
        raise UserError("not_a_pdf", file=path or "")
    pages_n = slicer.page_count(path)
    if pages_n < 1:
        raise UserError("pdf_empty", file=os.path.basename(path))
    detected = slicer.detect_paper(path)
    return {"path": os.path.abspath(path), "pages": pages_n,
            "paper": detected[0] if detected else None,
            "landscape": detected[1] if detected else False}


def source_files(source: dict) -> List[str]:
    """The scan files a source names, checked, in order.

    A source is ``{"type": "combined", "paths": [...]}`` (one or more PDFs of
    the class, joined in order), ``{"type": "photos", "path": folder}`` (one
    picture per page) or ``{"type": "folder", "path": folder}`` (one file per
    student), plus ``layout`` ("pages" or "booklet") and, for the first two,
    ``pages_per_student``.
    """
    kind = source.get("type")
    if kind == "combined":
        paths = pages.source_paths(source)
        if not paths:
            raise UserError("scans_not_chosen")
        return [inspect_combined_pdf(p)["path"] for p in paths]
    if kind in ("folder", "photos"):
        return slicer.list_scan_files(inspect_scans_folder(source.get("path"))["path"])
    raise UserError("scans_not_chosen")


def check_source(source: dict) -> List[str]:
    """Everything about a source that can be checked before importing."""
    files = source_files(source)
    if source.get("layout") not in (None, "pages", "booklet"):
        raise UserError("unknown_layout", layout=source.get("layout"))
    if source.get("type") in pages.STREAM_TYPES:
        try:
            per = int(source.get("pages_per_student") or 0)
        except (TypeError, ValueError):
            per = 0
        pages.check_pages_per_student(per, source.get("layout") == "booklet")
    return files


def preview_paper(source: dict) -> dict:
    """The first paper of a source as it will be imported (Step 1 preview)."""
    return pages.preview_first_paper(source, check_source(source))


def choose_session_folder(chosen: str, exam_name: str) -> str:
    """Where the session really goes: the chosen folder if it is empty (or new),
    otherwise a new ``<exam name>`` folder inside it."""
    chosen = os.path.abspath(chosen)
    if not os.path.isdir(chosen) or not os.listdir(chosen):
        return chosen
    if storage.is_session_folder(chosen):
        raise UserError("session_exists", folder=chosen)
    base = slicer.safe_filename(exam_name, "Exam")
    candidate, n = os.path.join(chosen, base), 1
    while os.path.exists(candidate) and (not os.path.isdir(candidate) or os.listdir(candidate)):
        n += 1
        candidate = os.path.join(chosen, f"{base} ({n})")
    return candidate


def _empty_dir(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    os.makedirs(path, exist_ok=True)


SIDES_DIR = "sides"       # scans/sides/: booklet sides as scanned, before unfolding


def _import_record(source: dict, files: List[str]) -> dict:
    kind = source.get("type")
    return {"type": kind, "source": files[0] if kind == "combined" else source.get("path"),
            "sources": files if kind == "combined" else None,
            "layout": source.get("layout") or "pages",
            "pages_per_student": source.get("pages_per_student"),
            "students": source.get("students"),
            "flip_fronts": bool(source.get("flip_fronts")),
            "flip_backs": bool(source.get("flip_backs")),
            "inside_first": bool(source.get("inside_first"))}


def _batch_record(config: dict, batch: int) -> dict:
    """How a batch of papers was brought in: 0 is the class, then each set of
    late papers."""
    if not batch:
        return config.get("import") or {}
    more = config.get("more_imports") or []
    return more[batch - 1] if batch <= len(more) else {}


def _next_number(config: dict) -> int:
    numbers = [int(s["id"][1:]) for s in config.get("students") or []
               if str(s.get("id", ""))[1:].isdigit()]
    return max(numbers, default=0) + 1


def _write_papers(session: storage.Session, source: dict, files: List[str], first: int,
                  batch: int, progress: Progress) -> List[dict]:
    """Bring one source into ``scans/`` as one file per paper. Returns the new
    student entries, numbered from ``first``."""
    scans_dir = session.path(storage.SCANS_DIR)
    os.makedirs(scans_dir, exist_ok=True)
    booklet = source.get("layout") == "booklet"
    if source.get("type") == "folder" and not booklet:
        students = slicer.copy_scans(files, scans_dir, progress)
        for i, s in enumerate(students):
            s["id"] = f"s{first + i:03d}"
            s["batch"] = batch
        return students

    papers = pages.plan_papers(source, files)
    taken = {n.casefold() for n in os.listdir(scans_dir)}
    stream = source.get("type") in pages.STREAM_TYPES
    photo_max = pages.PHOTO_MAX_PX if source.get("type") == "photos" else None
    students = []
    with pages.Sources(photo_max) as sources:
        for i, paper in enumerate(papers):
            number = first + i
            stem = (f"Student_{number:03d}" if stream
                    else slicer.safe_filename(os.path.splitext(paper["source"])[0]))
            name = slicer.unique_name(stem + ".pdf", taken)
            student = {"id": f"s{number:03d}", "file": name, "source": paper["source"],
                       "batch": batch}
            # A booklet keeps its sides as scanned, so a sheet can be turned later.
            dest = (session.path(f"{storage.SCANS_DIR}/{SIDES_DIR}/{name}") if booklet
                    else os.path.join(scans_dir, name))
            doc = pages.build_pages(sources, paper["sides"])
            try:
                pages.save(doc, dest)
            finally:
                doc.close()
            if booklet:
                student.update(sides=name, side_turns=paper["turns"], sheet_swaps=[],
                               sides_reversed=paper["reversed"])
                _write_booklet(session, student)
            students.append(student)
            if progress:
                progress(i + 1, len(papers))
    return students


def _write_booklet(session: storage.Session, student: dict) -> None:
    """(Re)write a booklet paper from its scanned sides and the teacher's fixes."""
    sides_path = session.path(f"{storage.SCANS_DIR}/{SIDES_DIR}/{student['sides']}")
    dest = student_scan_path(session, student)
    tmp = dest + ".new"
    n = slicer.page_count(sides_path)
    turns = (list(student.get("side_turns") or []) + [0] * n)[:n]
    refs = [pages.Ref(sides_path, j, turns[j] % 360) for j in range(n)]
    with pages.Sources() as sources:
        doc = pages.build_booklet(sources, pages.arrange_sides(
            refs, student.get("sides_reversed"), student.get("sheet_swaps") or []))
        try:
            pages.save(doc, tmp)
        finally:
            doc.close()
    os.replace(tmp, dest)


def _finish_students(session: storage.Session, students: List[dict],
                     progress: Progress = None) -> None:
    """Count pages and make thumbnails for new or changed papers."""
    thumbs_dir = session.path(storage.THUMBS_DIR)
    os.makedirs(thumbs_dir, exist_ok=True)
    for i, s in enumerate(students, 1):
        path = student_scan_path(session, s)
        try:
            s["pages"] = slicer.page_count(path)
            slicer.make_thumbnail(path, os.path.join(thumbs_dir, f"{s['id']}.jpg"))
        except Exception:
            s["pages"] = None
        s.setdefault("roster_id", None)
        s.setdefault("name", "")
        if progress:
            progress(i, len(students))


def scan_warnings(config: dict) -> dict:
    """Page-count problems worth showing on the scan-check screen.

    ``leftover`` and ``class_size`` are about the class's own scan (batch 0):
    papers cut from one long stack go wrong after a missing or extra page.
    Counts are of the papers' pages (a booklet's unfolded pages).
    """
    students = config.get("students") or []
    record = config.get("import") or {}
    leftover, class_size = 0, None
    try:
        per = int(record.get("pages_per_student") or 0)
    except (TypeError, ValueError):
        per = 0
    if record.get("type") in pages.STREAM_TYPES and per > 0:
        total = sum(s.get("pages") or 0 for s in students if not s.get("batch"))
        leftover = total % per
        class_size = slicer.check_class_size(total, per, record.get("students"))
    return {"page_counts": slicer.page_count_warnings({s["id"]: s.get("pages") for s in students}),
            "leftover": leftover, "class_size": class_size}


def _scaled(progress: Progress, offset: int, total: int) -> Progress:
    """Report a part of a longer job: ``done`` of this part is shown after
    ``offset`` steps of ``total``."""
    if not progress:
        return None
    return lambda done, _n: progress(offset + done, total)


def import_scans(session: storage.Session, config: dict, source: dict,
                 progress: Progress = None) -> dict:
    """Copy (or cut up) the scans into the session, then count pages and make
    thumbnails. Replaces any earlier import and its crops."""
    files = check_source(source)
    _empty_dir(session.path(storage.SCANS_DIR))
    _empty_dir(session.path(storage.THUMBS_DIR))
    crops_dir = session.path(storage.CROPS_DIR)
    if os.path.isdir(crops_dir):
        shutil.rmtree(crops_dir)

    writing = (lambda done, total: progress(done, total * 2)) if progress else None
    students = _write_papers(session, source, files, 1, 0, writing)
    _finish_students(session, students, _scaled(progress, len(students), len(students) * 2))
    config["students"] = students
    config["import"] = _import_record(source, files)
    config["more_imports"] = []
    config["scan_warnings"] = scan_warnings(config)
    _crops_stale(config)
    return config


def add_papers(session: storage.Session, config: dict, source: dict,
               progress: Progress = None) -> List[str]:
    """Add papers to a session that already has its class, for example a
    student who sat the exam late. Set-up, names and grades are kept. If the
    class has been sliced, the new papers are sliced straight away, so they
    can be graded at once. Returns the new student ids."""
    if not config.get("students"):
        raise UserError("scans_not_chosen")
    files = check_source(source)
    parts = 3 if config.get("sliced") else 2
    writing = (lambda done, total: progress(done, total * parts)) if progress else None
    new = _write_papers(session, source, files, _next_number(config),
                        len(config.get("more_imports") or []) + 1, writing)
    n = len(new)
    _finish_students(session, new, _scaled(progress, n, n * parts))
    config["more_imports"] = list(config.get("more_imports") or []) + [_import_record(source, files)]
    config["students"] = list(config["students"]) + new
    config["scan_warnings"] = scan_warnings(config)
    ids = [s["id"] for s in new]
    if config.get("sliced"):
        slice_students(session, config, ids, _scaled(progress, 2 * n, n * parts))
    else:
        _crops_stale(config)               # the new papers have no crops yet
    return ids


# --- Step 1: fixing pages ------------------------------------------------------------

PAGE_ACTIONS = ("earlier", "later", "turn", "remove", "blank_before", "blank_after")
SHEET_ACTIONS = ("turn_sheet", "swap_sheet", "reverse_sheets")


def _has_work(grades_data: Optional[dict], student_id: str) -> bool:
    per = ((grades_data or {}).get("grades") or {}).get(student_id) or {}
    return any(isinstance(e, dict) and (e.get("value") is not None
                                        or str(e.get("comment") or "").strip())
               for e in per.values())


def _refuse_if_graded(config: dict, grades_data: Optional[dict], students: List[dict]) -> None:
    for s in students:
        if _has_work(grades_data, s["id"]):
            raise UserError("pages_locked_graded", name=display_name(config, s))


def edit_pages(session: storage.Session, config: dict, grades_data: Optional[dict],
               student_id: str, page: int, action: str) -> dict:
    """Fix a page on the scan-check screen and say where it is now.

    Plain papers: move a page earlier or later, give it a quarter turn, remove
    it, or add a blank page where one is missing. Papers cut from one long
    stack (combined PDFs or page photos) share that stack, so moving a page can
    cross into the next paper, and removing or adding a page moves the pages of
    every paper after it, which is exactly how a missing or extra page went
    wrong in the first place.

    Booklet papers: turn a sheet upside down, swap its two faces (a sheet
    that went through face down), or read the whole booklet's sheets in the
    other order (it was stacked inside sheet first); the paper is then
    unfolded again.

    Papers that already have grades or comments are never changed. If the
    class is sliced, changed papers are sliced again straight away.
    Returns ``{"student": id, "page": n}``: where the edited page is now.
    """
    student = find_student(config, student_id)
    page = int(page)
    if action in SHEET_ACTIONS:
        return _edit_sheet(session, config, grades_data, student, page, action)
    if action not in PAGE_ACTIONS:
        raise UserError("unknown_page_action", action=str(action))
    if student.get("sides"):
        raise UserError("booklet_use_sheet_tools")

    batch = student.get("batch") or 0
    record = _batch_record(config, batch)
    try:
        per = int(record.get("pages_per_student") or 0)
    except (TypeError, ValueError):
        per = 0
    stream = record.get("type") in pages.STREAM_TYPES and per > 0
    group = ([s for s in config["students"] if (s.get("batch") or 0) == batch]
             if stream else [student])

    old_refs, flat = [], []
    for s in group:
        path = student_scan_path(session, s)
        refs = [pages.Ref(path, p) for p in range(slicer.page_count(path))]
        if s is student:
            if not 1 <= page <= len(refs):
                raise UserError("page_missing", file=s.get("source") or s["file"],
                                page=page, pages=len(refs))
            g = len(flat) + page - 1
        old_refs.append(refs)
        flat.extend(refs)

    if action == "earlier" and g > 0:
        flat[g - 1], flat[g] = flat[g], flat[g - 1]
        g -= 1
    elif action == "later" and g < len(flat) - 1:
        flat[g], flat[g + 1] = flat[g + 1], flat[g]
        g += 1
    elif action == "turn":
        flat[g] = flat[g].turned(90)
    elif action == "remove":
        if len(flat) == 1 or (not stream and len(old_refs[0]) == 1):
            raise UserError("last_page")
        del flat[g]
        g = min(g, len(flat) - 1)
    elif action in ("blank_before", "blank_after"):
        with pages.Sources() as sources:
            size = pages.visual_size(sources, flat[g])
        if action == "blank_after":
            g += 1
        flat.insert(g, pages.blank_ref(*size))

    new_refs = [flat[i:i + per] for i in range(0, len(flat), per)] if stream else [flat]
    kept, removed = group[:len(new_refs)], group[len(new_refs):]
    changed = [s for i, s in enumerate(kept) if new_refs[i] != old_refs[i]]
    _refuse_if_graded(config, grades_data, changed + removed)

    number = _next_number(config)
    added = []
    for refs in new_refs[len(kept):]:
        added.append({"id": f"s{number:03d}", "file": "", "batch": batch,
                      "source": f"{group[-1].get('source') or ''} +"})
        number += 1
    writes = [(s, new_refs[i]) for i, s in enumerate(kept) if s in changed]
    writes += list(zip(added, new_refs[len(kept):]))
    _rewrite_papers(session, writes, removed)

    for s in changed:
        old = old_refs[group.index(s)]
        new = new_refs[group.index(s)]
        if s.get("roster_id") and new[0][:2] != old[0][:2]:
            s["roster_id"] = None      # the name was read from a page that has moved
    students = [s for s in config["students"] if s not in removed]
    at = students.index(kept[-1]) + 1
    config["students"] = students[:at] + added + students[at:]
    for s in removed:
        _forget_student_files(session, s["id"])
    rewritten = [s for s, _ in writes]
    _finish_students(session, rewritten)
    config["scan_warnings"] = scan_warnings(config)
    if config.get("sliced") and rewritten:
        slice_students(session, config, [s["id"] for s in rewritten])
    elif rewritten:
        _crops_stale(config)

    owners = kept + added
    for i, refs in enumerate(new_refs):
        if g < len(refs):
            return {"student": owners[i]["id"], "page": g + 1}
        g -= len(refs)
    return {"student": student_id, "page": 1}


def _rewrite_papers(session: storage.Session, writes: List[tuple], removed: List[dict]) -> None:
    """Write new versions of papers (``[(student, [Ref])]``) and delete the
    files of removed ones. Every new file is written before any old one is
    replaced, because the new papers are made from the old files."""
    scans_dir = session.path(storage.SCANS_DIR)
    temps = []
    with pages.Sources() as sources:
        for s, refs in writes:
            tmp = os.path.join(scans_dir, f".edit_{s['id']}.pdf")
            doc = pages.build_pages(sources, refs)
            try:
                pages.save(doc, tmp)
            finally:
                doc.close()
            temps.append((s, tmp))
    taken = {n.casefold() for n in os.listdir(scans_dir)}
    old_files = {s["file"] for s, _ in writes if s["file"]} | {s["file"] for s in removed}
    for s, tmp in temps:
        name = s["file"]
        if not name.lower().endswith(".pdf"):      # a picture, or a new paper
            stem = os.path.splitext(name)[0] or f"Student_{int(s['id'][1:]):03d}"
            name = slicer.unique_name(slicer.safe_filename(stem) + ".pdf", taken)
        s["file"] = name
        os.replace(tmp, os.path.join(scans_dir, name))
    for name in old_files - {s["file"] for s, _ in writes}:
        try:
            os.remove(os.path.join(scans_dir, name))
        except OSError:
            pass


def _edit_sheet(session: storage.Session, config: dict, grades_data: Optional[dict],
                student: dict, page: int, action: str) -> dict:
    if not student.get("sides"):
        raise UserError("not_a_booklet")
    _refuse_if_graded(config, grades_data, [student])
    sides_path = session.path(f"{storage.SCANS_DIR}/{SIDES_DIR}/{student['sides']}")
    n = slicer.page_count(sides_path)
    sheet = pages.booklet_side(page, n) // 2
    reverse = bool(student.get("sides_reversed"))
    if action == "turn_sheet":
        turns = (list(student.get("side_turns") or []) + [0] * n)[:n]
        for j in (2 * sheet, 2 * sheet + 1):
            if j < n:
                k = pages.scanned_side(j, n, reverse)
                turns[k] = (turns[k] + 180) % 360
        student["side_turns"] = turns
    elif action == "reverse_sheets":
        # Read backwards, sheet s becomes sheet (last - s), so a sheet already
        # marked as face down stays marked.
        last = (n + 1) // 2 - 1
        student["sides_reversed"] = not reverse
        student["sheet_swaps"] = sorted(last - s for s in student.get("sheet_swaps") or [])
        student["roster_id"] = None
        page = 1
    else:
        student["sheet_swaps"] = sorted(set(student.get("sheet_swaps") or []) ^ {sheet})
        if sheet == 0:
            student["roster_id"] = None     # page 1 is now a different page
    _write_booklet(session, student)
    _finish_students(session, [student])
    config["scan_warnings"] = scan_warnings(config)
    if config.get("sliced"):
        slice_students(session, config, [student["id"]])
    else:
        _crops_stale(config)
    return {"student": student["id"], "page": page}


def _forget_student_files(session: storage.Session, student_id: str) -> None:
    paths = [session.path(f"{storage.THUMBS_DIR}/{student_id}.jpg")]
    crops = session.path(storage.CROPS_DIR)
    if os.path.isdir(crops):
        paths += [os.path.join(crops, r, f"{student_id}.png") for r in os.listdir(crops)]
    for path in paths:
        try:
            os.remove(path)
        except OSError:
            pass


def student_scan_path(session: storage.Session, student: dict) -> str:
    return session.path(f"{storage.SCANS_DIR}/{student['file']}")


def find_student(config: dict, student_id: str) -> dict:
    for s in config.get("students") or []:
        if s["id"] == student_id:
            return s
    raise UserError("unknown_student", student=student_id)


def display_name(config: dict, student: dict) -> str:
    """Matched class-list name, else a typed name, else the scan's name."""
    rid = student.get("roster_id")
    if rid:
        for r in config.get("roster") or []:
            if r["id"] == rid:
                return r["name"]
    if str(student.get("name") or "").strip():
        return student["name"].strip()
    # "Tanaka.pdf" -> "Tanaka", but "class.pdf · 3" (from a combined PDF) stays whole.
    source = student.get("source") or student.get("file") or ""
    stem, ext = os.path.splitext(source)
    return stem if slicer.is_scan_file(source) and ext else source


# --- Step 2: set-up ------------------------------------------------------------------

def set_layout(config: dict, paper: str, density: str, landscape: bool) -> dict:
    """Change paper or grid. Boxes drawn on the old grid no longer fit, so they
    are cleared (labels, marks and rubrics stay). Since the boxes go anyway, an
    older session moves to the current grid at the same time."""
    old = Layout.from_config(config.get("layout"))
    new = Layout(paper, density, bool(landscape))
    if new != old:
        new = Layout(paper, slicer.DENSITY, bool(landscape))
    if new != old:
        config["name_box"] = []
        for q in config.get("questions") or []:
            q["boxes"] = []
        _crops_stale(config)
    config["layout"] = new.to_config()
    return config


def set_mode(config: dict, mode: str, grades_data: Optional[dict] = None) -> dict:
    """Marks or rubric. Once grading has started the mode is fixed, because
    marks and rubric levels cannot be converted into each other."""
    if mode not in ("marks", "rubric"):
        raise UserError("unknown_mode", mode=mode)
    if (config.get("mode") and mode != config["mode"]
            and grading_summary.has_grades(grades_data or {})):
        raise UserError("mode_locked")
    config["mode"] = mode
    return config


def set_rubrics(config: dict, raw_rubrics: List[dict]) -> dict:
    cleaned = []
    used = set()
    for i, raw in enumerate(raw_rubrics or [], 1):
        rubric = rubrics.normalize_rubric(raw)
        rid = rubric["id"] or f"r{i}"
        while rid in used:
            i += 1
            rid = f"r{i}"
        rubric["id"] = rid
        rubric["name"] = rubric["name"] or f"Rubric {len(cleaned) + 1}"
        used.add(rid)
        cleaned.append(rubric)
    config["rubrics"] = cleaned
    for q in config.get("questions") or []:
        q["rubric_ids"] = [rid for rid in _picked_rubrics(q) if rid in used]
        q.pop("rubric_id", None)
    return config


def _picked_rubrics(raw: dict) -> List[str]:
    """The criteria chosen for a question; older sessions kept one ``rubric_id``."""
    picked = raw.get("rubric_ids")
    if picked is None:
        picked = [raw["rubric_id"]] if raw.get("rubric_id") else []
    return [str(rid) for rid in picked if rid]


def _clean_boxes(ranges, layout: Layout) -> List[str]:
    return [slicer.format_range(slicer.parse_range(r, layout)) for r in ranges or []]


def set_questions(config: dict, payload: dict) -> dict:
    """Save the name box, questions and choice groups as drawn so far.

    Drafts may be incomplete (a question without a box yet); everything must
    be complete only when slicing (:func:`check_ready`).
    """
    layout = Layout.from_config(config.get("layout"))
    rubric_ids = [r["id"] for r in config.get("rubrics") or []]
    old = {q["id"]: q for q in config.get("questions") or []}
    crops_known(config)

    questions = []
    seen_ids = set()
    for raw in payload.get("questions") or []:
        qid = str(raw.get("id") or "").strip()
        if not qid or qid in seen_ids or qid == model.NAME_BOX_ID:
            qid = new_question_id(config, seen_ids)
        seen_ids.add(qid)
        label = str(raw.get("label") or "").strip()[:MAX_LABEL]
        max_marks = raw.get("max")
        try:
            max_marks = int(max_marks) if max_marks not in (None, "") else None
        except (TypeError, ValueError):
            raise UserError("question_needs_max", question=label or qid)
        if max_marks is not None and not 1 <= max_marks <= MAX_MARKS:
            raise UserError("question_max_range", question=label or qid, max=MAX_MARKS)
        picked = set(_picked_rubrics(raw))
        questions.append({"id": qid, "label": label,
                          "boxes": _clean_boxes(raw.get("boxes"), layout),
                          "max": max_marks,
                          "rubric_ids": [rid for rid in rubric_ids if rid in picked]})

    groups = []
    known = {q["id"] for q in questions}
    for i, g in enumerate(payload.get("choice_groups") or [], 1):
        qids = [qid for qid in g.get("questions") or [] if qid in known]
        groups.append({"id": str(g.get("id") or f"g{i}"), "questions": qids,
                       "answer": int(g.get("answer") or 0),
                       "pick": grading_summary.group_pick(g)})

    name_box = _clean_boxes(payload.get("name_box"), layout)
    changed = (name_box != config.get("name_box")
               or [q["boxes"] for q in questions]
               != [old.get(q["id"], {}).get("boxes") for q in questions]
               or len(questions) != len(old))
    config["name_box"] = name_box
    config["name_box_skipped"] = bool(payload.get("name_box_skipped")) and not name_box
    config["questions"] = questions
    config["choice_groups"] = groups
    stale = stale_regions(config)
    if stale is not None:
        config["sliced"] = not stale
    elif changed:
        config["sliced"] = False
    return config


# Which boxes each region's crops were cut from is kept in ``crops_of``, so
# moving one question's box only needs that question sliced again. Anything
# that changes the papers while they are not all sliced drops it, and then
# only slicing every paper makes the crops current again.

def _boxes_now(config: dict) -> dict:
    out = {q["id"]: list(q.get("boxes") or []) for q in config.get("questions") or []}
    if config.get("name_box"):
        out[model.NAME_BOX_ID] = list(config["name_box"])
    return out


def crops_known(config: dict) -> bool:
    """True when ``crops_of`` says which boxes each region's crops came from."""
    if config.get("sliced") and "crops_of" not in config:
        config["crops_of"] = _boxes_now(config)      # sliced before crops_of was kept
    return "crops_of" in config


def _crops_stale(config: dict) -> None:
    config["sliced"] = False
    config.pop("crops_of", None)


def stale_regions(config: dict) -> Optional[List[str]]:
    """Regions whose crops don't match their boxes, or None if unknown."""
    crops_of = config.get("crops_of")
    if crops_of is None:
        return None
    return [rid for rid, boxes in _boxes_now(config).items() if crops_of.get(rid) != boxes]


def new_question_id(config: dict, taken=()) -> str:
    used = {q["id"] for q in config.get("questions") or []} | set(taken)
    n = 1
    while f"q{n}" in used:
        n += 1
    return f"q{n}"


def check_ready(config: dict) -> None:
    """Everything needed before slicing; raises the first problem found."""
    if not config.get("students"):
        raise UserError("scans_not_chosen")
    questions = config.get("questions") or []
    if not questions:
        raise UserError("no_questions")
    mode = config.get("mode")
    if mode not in ("marks", "rubric"):
        raise UserError("unknown_mode", mode=mode)
    labels = set()
    for q in questions:
        label = q.get("label") or ""
        if not label:
            raise UserError("question_needs_label")
        if label.casefold() in labels:
            raise UserError("duplicate_label", question=label)
        labels.add(label.casefold())
        if not q.get("boxes"):
            raise UserError("question_needs_box", question=label)
        if mode == "marks" and not q.get("max"):
            raise UserError("question_needs_max", question=label)
        if mode == "rubric" and not grading_summary.question_rubric_ids(config, q):
            raise UserError("question_has_no_rubric", question=label)
    if mode == "rubric" and not config.get("rubrics"):
        raise UserError("rubric_missing")
    groups = [g for g in config.get("choice_groups") or []]
    if groups:
        grading_summary.check_choice_groups(config)


def regions(config: dict) -> list:
    layout = Layout.from_config(config.get("layout"))
    out = [(q["id"], slicer.parse_boxes(q["boxes"], layout)) for q in config["questions"]]
    if config.get("name_box"):
        out.append((model.NAME_BOX_ID, slicer.parse_boxes(config["name_box"], layout)))
    return out


def slice_session(session: storage.Session, config: dict, progress: Progress = None) -> dict:
    check_ready(config)
    crops_dir = session.path(storage.CROPS_DIR)
    if os.path.isdir(crops_dir):
        shutil.rmtree(crops_dir)
    summary = slice_students(session, config, [s["id"] for s in config["students"]], progress)
    config["sliced"] = True
    config["crops_of"] = _boxes_now(config)
    return summary


def slice_students(session: storage.Session, config: dict, student_ids: List[str],
                   progress: Progress = None) -> dict:
    """Crop every question for these papers only (late or fixed papers); the
    rest of the class keeps its crops."""
    check_ready(config)
    wanted = set(student_ids)
    scans = [(s["id"], student_scan_path(session, s)) for s in config["students"]
             if s["id"] in wanted]
    summary = slicer.slice_all(scans, regions(config), Layout.from_config(config["layout"]),
                               session.path(storage.CROPS_DIR), progress)
    return _finish_slicing(config, summary)


def slice_question(session: storage.Session, config: dict, question_id: str,
                   progress: Progress = None) -> dict:
    """Crop one question again for every paper, after its box was adjusted.

    Grades are kept, since they are stored by question. The papers count as
    sliced again once no other region's crops are out of date.
    """
    question = next((q for q in config.get("questions") or [] if q["id"] == question_id), None)
    if question is None:
        raise UserError("unknown_question", question=question_id)
    if not crops_known(config):
        raise UserError("not_sliced")
    check_ready(config)
    layout = Layout.from_config(config["layout"])
    folder = session.path(f"{storage.CROPS_DIR}/{question_id}")
    if os.path.isdir(folder):
        shutil.rmtree(folder)                  # no old crop survives a failed one
    scans = [(s["id"], student_scan_path(session, s)) for s in config["students"]]
    summary = slicer.slice_all(scans, [(question_id, slicer.parse_boxes(question["boxes"], layout))],
                               layout, session.path(storage.CROPS_DIR), progress)
    config["crops_of"][question_id] = list(question["boxes"])
    config["sliced"] = not stale_regions(config)
    return _finish_slicing(config, summary)


def _finish_slicing(config: dict, summary: dict) -> dict:
    names = {s["id"]: display_name(config, s) for s in config["students"]}
    labels = {q["id"]: q["label"] for q in config["questions"]}
    labels[model.NAME_BOX_ID] = "name"
    for e in summary["errors"]:
        e["student_name"] = names.get(e["student"], e["student"])
        e["label"] = labels.get(e["region"], e["region"])
    config["sliced_at"] = model.now_iso()      # lets the browser fetch fresh crops
    return summary


# --- Step 3: names -------------------------------------------------------------------

def set_roster(config: dict, roster_entries: List[dict], auto: bool = True) -> dict:
    """Replace the class list, keep matches that still exist, auto-match the rest."""
    from . import roster as roster_mod
    config["roster"] = roster_entries
    valid = {r["id"] for r in roster_entries}
    for s in config.get("students") or []:
        if s.get("roster_id") not in valid:
            s["roster_id"] = None
    if auto:
        taken = {s["roster_id"] for s in config["students"] if s.get("roster_id")}
        free_students = [s for s in config["students"] if not s.get("roster_id")]
        free_roster = [r for r in roster_entries if r["id"] not in taken]
        for sid, rid in roster_mod.auto_match(free_students, free_roster).items():
            find_student(config, sid)["roster_id"] = rid
    return config


def clear_roster(config: dict) -> dict:
    config["roster"] = []
    for s in config.get("students") or []:
        s["roster_id"] = None
    return config


def match_student(config: dict, student_id: str, roster_id=None, name=None) -> dict:
    """Pair a paper with a class-list entry (or a typed name). A class-list
    entry can belong to one paper only; giving it to another frees it."""
    student = find_student(config, student_id)
    if roster_id:
        if roster_id not in {r["id"] for r in config.get("roster") or []}:
            raise UserError("unknown_student", student=roster_id)
        for other in config["students"]:
            if other is not student and other.get("roster_id") == roster_id:
                other["roster_id"] = None
        student["roster_id"] = roster_id
    else:
        student["roster_id"] = None
    if name is not None:
        student["name"] = str(name).strip()[:100]
    return config
