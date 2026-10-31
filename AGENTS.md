# Project Context & Review Rules

## Architecture & Scope
- Lightweight, offline-first local Python desktop application for batch-grading scanned exam PDFs, defining coordinate answer boxes, and exporting student PDF reports.
- Target distribution: Standalone Windows (.exe) and macOS (.app) binaries (PyInstaller / Briefcase / Nuitka).

## Strict Anti-Bloat & Review Philosophy
- **Trusted Local Input:** Assume the user is a teacher supplying valid PDF scans on a local machine. Do NOT suggest input sanitization for adversarial/malicious files, extreme edge-case validation, or enterprise-grade telemetry/logging.
- **No Defensive Over-Engineering:** Do NOT suggest `try/except` wrappers, fallback mechanisms, or schema checks for unlikely scenarios. Let unexpected internal errors fail fast and visibly.
- **Keep It Small:** Do not recommend abstracting simple functions into classes, adding third-party dependencies, or splitting files unless it directly fixes a bug.

## High-Priority Review Targets (ONLY flag these)
1. **Binary Packaging Blockers:** Hardcoded relative paths (`./` or `../`), missing `sys._MEIPASS` / `importlib.resources` handling for bundled assets/fonts, or dynamic imports that break static bundlers.
2. **Cross-Platform Bugs (Windows vs. macOS):** Path separator mismatches (use `pathlib.Path`), file-locking issues on Windows when writing/overwriting temporary PDFs, DPI/coordinate scaling discrepancies across OS displays, and case-sensitivity issues.
3. **Memory & Resource Leaks:** Unclosed PDF file handles or image buffers (`fitz` / `PyMuPDF`, `Pillow`, `ReportLab`) when iterating over a full class set of high-resolution scans.
4. **Data Integrity:** Off-by-one indexing or coordinate math errors that could map a grade or bounding box to the wrong student's PDF report.
