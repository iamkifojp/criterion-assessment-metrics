# UI polish & deliverables design — plan v1

**Status:** v1, planned 2026-07-12 (Fable 5 orchestration; for Opus 4.8 High to
implement in this public checkout). Four independent phases — 1 and 2 are
small, 3 and 4 are the substance. No phase depends on another; land them in
any order, one commit per phase.

**Read `CLAUDE.md` first** — especially the sandbox rules. Any live test run
must redirect the DB to a temp folder; the teacher's real prefs point at live
OneDrive data. `AppTest` is single-run only in this repo; the console is cp932
(no emoji/unicode in test prints).

---

## Phase 1 — Compact email chip in the Evaluation Cockpit

### Problem

Window 3 renders the focused student's roster email as a full-width
`st.code` block directly under the name heading (`render_window3`,
`app.py:6984–6992`). It gives click-to-copy (useful) but costs a whole row of
an already very long window.

### Change

Put the name and the email on **one line**: name heading left, a **small
code chip** right — keeping `st.code`'s native copy icon.

- Replace the two stacked elements with `st.columns` (e.g. `[3, 2]`,
  `vertical_alignment="bottom"`): col 0 keeps
  `st.markdown(f"### {student_label(student)}")`; col 1 renders the existing
  `st.code(_email, language=None)` inside a keyed container
  (`st.container(key="w3_email_chip")`) so CSS can target it.
- Add to the app's existing CSS layer (`theme_css()`, the big CSS block near
  `app.py:500`): under `.st-key-w3_email_chip`, shrink the code block —
  font-size ≈ 0.72rem, minimal padding (≈ 2px 8px), `width: fit-content`
  pushed right (`margin-left: auto`), and trim the block's top/bottom margin
  so the row hugs the heading baseline.
- No email on the roster → render the heading full-width exactly as today
  (don't leave an empty chip).

### Acceptance

- Name + email share one line in Window 3; copy icon still works on hover.
- Vertical space of the old block is reclaimed (one row, not two).
- Long emails must not wrap under the name on a normal desktop width; if the
  columns fight at narrow widths, prefer letting the chip truncate/scroll —
  never push the heading.

---

## Phase 2 — Stop Chrome offering student names in unrelated fields

### Problem (root cause, confirmed)

The teacher sees previously-typed **student names suggested in the "Grade
level" field** of the class dialog. This is Chrome's form-autofill history,
not CAM state: none of the app's `st.text_input` calls set an `autocomplete`
attribute, so Chrome keys its typed-value history across similar anonymous
fields. The names were typed once into the ➕ Add student dialog
(`app.py:6498–6504`) and now leak into any text box. Any teacher on Chrome
gets their own history leaked across fields the same way.

### Change

- Pass `autocomplete="off"` to **every `st.text_input` in `app.py`** (17 call
  sites at planning time — grep `st.text_input(`). Streamlit 1.58 supports the
  kwarg.
- `st.text_area` has no autocomplete kwarg and Chrome doesn't autofill
  textareas — skip.
- `st.number_input` exposes no autocomplete — skip (Chrome doesn't offer
  history dropdowns on spinner inputs).
- Sweep the grading workspace too: any free-text `<input>` in
  `cam_grading_workspace` templates/JS gets `autocomplete="off"` (search for
  `<input` in its templates/static files). Don't touch type="file"/checkbox.

### Note for the changelog

Chrome sometimes ignores `autocomplete="off"` for fields it heuristically
classifies as address-like; this change kills the common case. Existing
polluted history clears itself as entries expire, or the teacher can delete a
suggestion with Shift+Delete.

### Acceptance

Manual: in a sandboxed run, type a name into ➕ Add student, reopen the class
dialog — the Grade-level field must not offer it (fresh Chrome profile makes
this deterministic). Plus a grep-level check: no `st.text_input(` call site
without `autocomplete=`.

---

## Phase 3 — Per-class roster name order (4 modes)

### Today's terrain

- The stored roster order **is** the display order; everything downstream
  follows it: Window 2's list, `students_for_active_class()` (`app.py:4528`),
  and therefore Excel tabs 1–3, the report-card pack, class comments and the
  mail-merge ZIP.
- Sorting happens **once at upload**: `set_active_roster(sort_roster_gojuon(
  parse_roster(up)))` (`app.py:6823`); `sort_roster_gojuon` (`app.py:6461`)
  sorts by gojūon reading of surname, then given name, using
  `engine.gojuon_sort_key`. ↑/↓ buttons fine-tune the stored order afterwards.
- **The Classroom Entry tab is the deliberate exception**:
  `_append_classroom_entry_sheet` (`app.py:4590`) re-sorts to Latin
  *first-name* order to mirror how Google Classroom lists students, so pasted
  columns line up. **This must stay untouched by the new setting** — the
  teacher confirmed: page 4 always follows Classroom's order.
- Re-ordering the roster is display-only and grade-safe: marks are keyed by
  student ID, never roster position (docstring at `app.py:6469`).

### Change

**A. Per-class setting, stored in the shared database.** Class dicts live in
the DB `classes` registry (`{"name","grade","myp_year","subject","master_dir"}`
— `app.py:655`, `create_class` `app.py:2138`, `update_class` `app.py:2221`).
Add an optional key `roster_order` with values:

| value        | key                                             |
|--------------|--------------------------------------------------|
| `"gojuon"`   | (gojūon(surname), gojūon(given)) — **default**   |
| `"last_first"` | (surname.casefold(), first.casefold())         |
| `"first_last"` | (first.casefold(), surname.casefold())         |
| `"email"`    | email.casefold()                                 |

Absent key → `"gojuon"` (no migration; JSON is additive). Per-class because
the teacher wants the order fixed **for the class**, and DB-stored so it
follows the data across devices (like report-card grades, not device prefs).

**B. Generalise the sorter.** Replace `sort_roster_gojuon` with
`sort_roster(entries, mode)` sharing the existing surname-peeling logic
(`name` is stored "Surname First"; peel `first` off the end — keep that code
exactly, it handles multi-token surnames). Keep a `sort_roster_gojuon` alias
or update the one caller. Email mode sorts on `entry.get("email")`, falling
back to `key` (manual adds always have email; legacy safety only).

**C. Settings-panel UI.** New section "**Roster name order**" in ⚙ Settings
placed **immediately above the "Report-card grades" section**
(`app.py:5723`). Contents:

- Caption naming the active class (the setting edits
  `active_class_dict()["roster_order"]`).
- A radio/selectbox with the 4 modes (human labels: "Hiragana gojūon —
  surname, given name (Japanese register order)", "Surname, First name (A–Z)",
  "First name, Surname (A–Z)", "Email address").
- On save: write the class key, **re-sort the stored roster in place** via
  `set_active_roster(sort_roster(current_roster, mode))`, `persist()`,
  success banner. Keep it in its own form like the report-cfg form, so it
  never rides along with the DB-path flow above it.
- Caption spelling out the semantics: affects Window 2 and every export that
  follows roster order (Excel Final Suggestions, report-card pack, class
  comments, mail-merge); ↑/↓ fine-tuning survives until the next re-sort
  (setting change or roster upload); **the Excel "Classroom Entry" tab always
  keeps Google Classroom's own order** regardless of this setting.

**D. Upload path.** `app.py:6823` uses the active class's mode instead of
hard-coded gojūon.

### Acceptance / tests

Stdlib `unittest`, no app launch needed for the sorter:

- `sort_roster` all 4 modes on names where the orders differ (e.g. Aoki/Iida/
  Shimizu/Chiba/Baba invert between gojūon and Latin; first-name and email
  orders differ again).
- Surname peeling: multi-token surnames, missing `first`, entry with only
  `key`.
- Invariant test: `_append_classroom_entry_sheet` ordering is independent of
  `roster_order` (build a workbook with two different modes, same tab order).

---

## Phase 4 — One design language across the deliverables tray

### Today's terrain

- Excel master (`build_excel_bytes`, `app.py:4690`): tabs 1–3 ("Final
  Suggestions", "Raw Scores", "Assignments") are bare `ws.append` rows — no
  fonts, fills, widths, freeze panes. Tab 4 ("Classroom Entry",
  `_append_classroom_entry_sheet`, `app.py:4590`) is fully styled — Arial,
  navy `1F4E78` merged header band, light-blue `D9E1F2` sub-headers, grey
  `F2F2F2` name column, thin `BFBFBF` borders, freeze panes, gridlines off.
- Word deliverables (report-card pack / single report / mail-merge ZIP share
  the per-student builder near `app.py:4850`; class comments doc separate):
  python-docx defaults, no shared identity.

### Direction (teacher-approved)

Standardise on **the app's own theme**, not the current generic navy. From
`.streamlit/config.toml` (light palette — these are print documents):

| role                     | colour                          |
|--------------------------|---------------------------------|
| header band fill         | `B3554D` (muted brick red), white bold text |
| sub-header fill          | `DDDAD3` / `DEDBD4` warm grey, `9C4A43` bold text |
| name/label column fill   | `E9E7E2` soft warm grey         |
| body text                | `38352F` near-black             |
| borders                  | `C6C2B9` thin                   |

Font: keep Arial (matches tab 4; universally available in Excel/Word).

### Change

**A. Extract a shared openpyxl style kit** (module-level constants + tiny
helpers, e.g. `_style_header_row(ws, row, ncols)`, `_style_body(ws, ...)`,
`_finish_sheet(ws, freeze, widths)`) using the palette above. Restyle
**Classroom Entry** from navy to the brick-red palette using the same kit —
same structure, new colours — so all four tabs match.

**B. Apply to tabs 1–3:**

- *Final Suggestions*: styled header row, name/ID columns on the label fill,
  centred grade cells, borders, freeze `C2` (or `B2`), gridlines off, column
  widths (name wide, crit columns narrow).
- *Raw Scores*: styled header, borders, freeze top row, widths; comment
  column wide + wrap. Zebra striping optional — only if it reads well with
  the warm greys.
- *Assignments*: style the 4-row class/subject/term metadata block as a small
  title card (bold labels on the label fill), blank spacer, then a styled
  table like the others.

**C. Word pass (modest — typography, not layout):** shared helper that sets
the document's base style (Arial, 10.5–11pt, `38352F`) and heading styles
(brick `B3554D`/`9C4A43`, consistent sizes; optionally a thin bottom border
under the page-title heading). Apply to the report-card builders and the
class-comments doc. **Do not** restructure content — same paragraphs, tables
and page breaks as today; the trend PNG (matplotlib, `_trend_png`) stays
as-is.

### Acceptance

- Build all five tray deliverables in a sandboxed run; the four Excel tabs
  share one visual system, and every Word doc opens with the same fonts and
  accent colour.
- Unit-verifiable bits: reload the workbook bytes with openpyxl and assert
  freeze panes, `showGridLines is False`, and header fill `B3554D` on every
  tab; assert docx base font/heading colour via python-docx.
- Excel data values are byte-for-byte what they were (styling only) — the
  Classroom Entry paste-back workflow must not change shape.

---

## Out of scope

- No change to what any deliverable *contains*, to roster ↑/↓ mechanics, to
  the Classroom Entry ordering, or to CGW's grading flow.
- Test fixtures for the "Test MYP Class" (fake roster CSV + local-mode PDF
  folders) are being created separately by the orchestrating session — not
  part of this implementation plan.
