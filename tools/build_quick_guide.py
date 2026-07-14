"""Build ``docs/CAM Quick Guide.pdf`` with Microsoft Edge.

The source deliberately uses a small, documented Markdown subset so the
portable-bundle build needs no extra Python package.  Each level-two heading
starts a new PDF page.
"""

from __future__ import annotations

import argparse
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = REPO_ROOT / "docs" / "QUICK_GUIDE.md"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "CAM Quick Guide.pdf"


CSS = r"""
@page { size: A4 portrait; margin: 11mm 13mm 12mm; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  color: #233044;
  font-family: "Segoe UI", Arial, sans-serif;
  font-size: 10.2pt;
  line-height: 1.36;
  background: white;
}
.task {
  height: 274mm;
  overflow: hidden;
  page-break-after: always;
  position: relative;
  padding-bottom: 11mm;
}
.task:last-child { page-break-after: auto; }
.guide-name {
  color: #7b8798;
  font-size: 9pt;
  font-weight: 650;
  letter-spacing: .08em;
  margin: 0 0 2mm;
  text-transform: uppercase;
}
.task-label {
  color: #b24d45;
  font-size: 8.5pt;
  font-weight: 750;
  letter-spacing: .09em;
  margin: 0 0 1mm;
  text-transform: uppercase;
}
h1 { display: none; }
h2 {
  color: #1e4f70;
  font-size: 24pt;
  line-height: 1.08;
  margin: 0 0 2mm;
}
h3 {
  color: #1e4f70;
  font-size: 12pt;
  margin: 3mm 0 1mm;
}
p { margin: 1.5mm 0 2mm; }
ol, ul { margin: 1.5mm 0 2.5mm; padding-left: 6mm; }
li { margin: 0 0 1.3mm; padding-left: 1mm; }
li::marker { color: #b24d45; font-weight: 700; }
strong { color: #172a3a; }
code {
  background: #edf2f5;
  border-radius: 3px;
  font-family: Consolas, monospace;
  font-size: 9pt;
  padding: .2mm 1mm;
}
a { color: #1e628f; text-decoration: none; }
blockquote {
  background: #f3f7f8;
  border-left: 3px solid #4e8891;
  border-radius: 0 5px 5px 0;
  color: #34495a;
  margin: 2.5mm 0;
  padding: 2mm 3mm;
}
blockquote p { margin: 0; }
figure {
  background: #f7f9fa;
  border: 1px solid #dbe3e8;
  border-radius: 7px;
  margin: 3mm 0 2.5mm;
  padding: 2mm;
  text-align: center;
}
figure img {
  display: block;
  height: auto;
  margin: 0 auto;
  max-height: 98mm;
  max-width: 100%;
}
figcaption {
  color: #69798a;
  font-size: 8.5pt;
  margin-top: 1mm;
}
.page-footer {
  bottom: 0;
  color: #85919f;
  font-size: 8pt;
  left: 0;
  position: absolute;
  right: 0;
  text-align: right;
}
"""


INLINE_TOKEN = re.compile(
    r"(!\[[^]]*\]\([^)]+\)|\[[^]]+\]\([^)]+\)|\*\*[^*]+\*\*|`[^`]+`)"
)


def _inline(text: str, source_dir: Path) -> str:
    """Render the guide's small inline-Markdown subset."""
    parts: list[str] = []
    for part in INLINE_TOKEN.split(text):
        if not part:
            continue
        image_match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", part)
        link_match = re.fullmatch(r"\[([^]]+)\]\(([^)]+)\)", part)
        if image_match:
            alt, target = image_match.groups()
            uri = (source_dir / target).resolve().as_uri()
            parts.append(
                f'<img src="{html.escape(uri, quote=True)}" '
                f'alt="{html.escape(alt, quote=True)}">'
            )
        elif link_match:
            label, target = link_match.groups()
            parts.append(
                f'<a href="{html.escape(target, quote=True)}">'
                f'{html.escape(label)}</a>'
            )
        elif part.startswith("**"):
            parts.append(f"<strong>{html.escape(part[2:-2])}</strong>")
        elif part.startswith("`"):
            parts.append(f"<code>{html.escape(part[1:-1])}</code>")
        else:
            parts.append(html.escape(part))
    return "".join(parts)


def render_markdown(source: Path) -> tuple[str, int]:
    """Return printable HTML and the number of task pages found."""
    lines = source.read_text(encoding="utf-8").splitlines()
    title = "CAM Quick Guide"
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_lines: list[str] = []

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            if current_title:
                sections.append((current_title, current_lines))
            current_title = line[3:].strip()
            current_lines = []
        elif current_title:
            current_lines.append(line)
    if current_title:
        sections.append((current_title, current_lines))
    if not sections:
        raise ValueError("Quick Guide needs at least one level-two task heading")

    body = []
    total = len(sections)
    for index, (heading, content) in enumerate(sections, 1):
        body.append('<section class="task">')
        body.append(f'<div class="guide-name">{html.escape(title)}</div>')
        body.append(f'<div class="task-label">Task {index} of {total}</div>')
        body.append(f"<h2>{html.escape(heading)}</h2>")
        body.extend(_render_blocks(content, source.parent))
        body.append(
            f'<div class="page-footer">CAM Quick Guide &nbsp; {index} / {total}</div>'
        )
        body.append("</section>")

    document = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title><style>{css}</style></head>
<body>{body}</body></html>
""".format(title=html.escape(title), css=CSS, body="\n".join(body))
    return document, total


def _render_blocks(lines: list[str], source_dir: Path) -> list[str]:
    output: list[str] = []
    paragraph: list[str] = []
    list_kind = ""

    def flush_paragraph() -> None:
        if paragraph:
            output.append(f"<p>{_inline(' '.join(paragraph), source_dir)}</p>")
            paragraph.clear()

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            output.append(f"</{list_kind}>")
            list_kind = ""

    for raw in [*lines, ""]:
        line = raw.strip()
        if not line:
            flush_paragraph()
            close_list()
            continue
        if line.startswith("### "):
            flush_paragraph()
            close_list()
            output.append(f"<h3>{html.escape(line[4:].strip())}</h3>")
            continue
        image_match = re.fullmatch(r"!\[([^]]*)\]\(([^)]+)\)", line)
        if image_match:
            flush_paragraph()
            close_list()
            alt, target = image_match.groups()
            uri = (source_dir / target).resolve().as_uri()
            output.append(
                f'<figure><img src="{html.escape(uri, quote=True)}" '
                f'alt="{html.escape(alt, quote=True)}">'
                f"<figcaption>{html.escape(alt)}</figcaption></figure>"
            )
            continue
        ordered = re.match(r"^\d+\.\s+(.+)$", line)
        unordered = re.match(r"^-\s+(.+)$", line)
        if ordered or unordered:
            flush_paragraph()
            wanted = "ol" if ordered else "ul"
            if list_kind != wanted:
                close_list()
                output.append(f"<{wanted}>")
                list_kind = wanted
            item = (ordered or unordered).group(1)
            output.append(f"<li>{_inline(item, source_dir)}</li>")
            continue
        if line.startswith("> "):
            flush_paragraph()
            close_list()
            output.append(
                f"<blockquote><p>{_inline(line[2:], source_dir)}</p></blockquote>"
            )
            continue
        close_list()
        paragraph.append(line)
    return output


def find_edge(explicit: Path | None = None) -> Path:
    """Find Microsoft Edge without assuming a particular Windows install root."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    if os.environ.get("EDGE_PATH"):
        candidates.append(Path(os.environ["EDGE_PATH"]))
    found = shutil.which("msedge")
    if found:
        candidates.append(Path(found))
    for variable in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(variable)
        if root:
            candidates.append(Path(root) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    if sys.platform == "win32":
        try:
            import winreg

            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(
                        hive,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe",
                    ) as key:
                        candidates.append(Path(winreg.QueryValue(key, None)))
                except OSError:
                    pass
        except ImportError:
            pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "Microsoft Edge was not found. Pass --edge C:\\path\\to\\msedge.exe."
    )


def build_pdf(source: Path, output: Path, edge: Path, html_output: Path | None = None) -> int:
    document, page_count = render_markdown(source)
    if html_output:
        html_output.parent.mkdir(parents=True, exist_ok=True)
        html_output.write_text(document, encoding="utf-8")
        html_path = html_output
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="cam-quick-guide-")
        html_path = Path(temporary.name) / "quick-guide.html"
        html_path.write_text(document, encoding="utf-8")

    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    command = [
        os.fspath(edge),
        "--headless",
        "--disable-gpu",
        "--no-pdf-header-footer",
        f"--print-to-pdf={output.resolve()}",
        html_path.resolve().as_uri(),
    ]
    try:
        subprocess.run(command, check=True)
    finally:
        if temporary:
            temporary.cleanup()
    if not output.is_file() or output.stat().st_size < 1000:
        raise RuntimeError(f"Edge did not create a usable PDF at {output}")
    if output.read_bytes()[:5] != b"%PDF-":
        raise RuntimeError(f"Edge output is not a PDF: {output}")
    return page_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--edge", type=Path)
    parser.add_argument("--html-output", type=Path, help="Keep the intermediate HTML here")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    edge = find_edge(args.edge)
    pages = build_pdf(source, output, edge, args.html_output)
    print(f"Built {output} ({pages} task pages) with {edge}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
