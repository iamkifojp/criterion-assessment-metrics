"""PDF display selections and bounded cache housekeeping (originals stay intact)."""
from pathlib import Path
import re


def page_ranges(text):
    text = str(text or "").strip()
    if not text:
        return []
    ranges = []
    for part in text.split(","):
        match = re.fullmatch(r"\s*([1-9]\d*)\s*(?:[-–]\s*([1-9]\d*)\s*)?", part)
        if not match:
            raise ValueError("Use page numbers or ranges, such as 1-9, 12, 15-17.")
        first, last = int(match[1]), int(match[2] or match[1])
        if last < first:
            raise ValueError("Page ranges must run forwards, such as 1-9.")
        ranges.append((first, last))
    return ranges


def visible_pages(count, omitted):
    ranges = page_ranges(omitted)
    return [p for p in range(1, count + 1)
            if not any(first <= p <= last for first, last in ranges)]


def prune_pdf_cache(folder, keep, budget=256 * 1024 * 1024):
    """Cap downloaded copies; retain the active PDF even if it alone exceeds cap.

    Only our cache's PDFs are removed, never submissions or backup files.
    """
    try:
        files = sorted(Path(folder).glob("*.pdf"), key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        for path in files:
            if total <= budget:
                break
            if path == Path(keep):
                continue
            size = path.stat().st_size
            path.unlink()
            total -= size
    except OSError:
        pass  # concurrent cache readers/deletions must not block the viewer
