# CAM — UI Style Guide

Sizing and alignment rules for every interactive control in the app. The CSS
that enforces them lives in `DENSE_CSS` and `theme_css()` at the top of
`app.py` — keep this file and those blocks in sync.

---

## Two-tier control sizing

Every control in the app belongs to one of two height tiers. When adding a new
widget, pick its tier from the table below — do not invent a third size.

### SHORT tier (~28 px) — command buttons (the default)

Anything the teacher clicks to *do something now*: run an action, open a
dialog, commit, save, build, download.

| Control | Streamlit widget |
|---|---|
| ⬆ Upload & stage files · 🔄 Sync · 🗃 Archived | `st.button` |
| Focus · ↑ · ↓ · mark-cell chips (`B: 7`) | `st.button` |
| 💾 Save now · Build/⬇ deliverable buttons | `st.button` / `st.download_button` |
| Save settings · Save changes · Create · Apply | `st.form_submit_button` |
| ✎ Add / Edit class · ⚙ Settings (top bar) | `st.button` |
| Dialog buttons (Done, Close, Cancel, Watch, …) | `st.button` |
| Compile prompt to clipboard · Generate for whole class | `st.button` |

Enforced by one rule in `DENSE_CSS`:

```css
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
    padding: 0.12rem 0.55rem; margin: 0; min-height: 0;
}
```

**Why a descendant selector (space), not a child selector (`>`):** a button
created with `help="..."` is wrapped in a tooltip container, so
`.stButton > button` never matches it. That is exactly how the deliverable
Build buttons, 🔄 Sync, 👁 Watch and "Generate for whole class" drifted to a
taller size than their neighbours before this rule was fixed.

### TALL tier (~40 px / 2.5 rem) — fields, pickers and read-targets

Anything that opens a picker, takes typed input, or is meant to be selected
and copied. These keep Streamlit's default field height:

- **Dropdowns** — class/term selectors, gender, criterion grade, calculation
  method, Effort/English Use (`st.selectbox`).
- **Text / number / date inputs** — student names, custom DB path, staging
  fields.
- **Popover triggers** — Remarks, ⚠ missing-work (they open a dropdown-like
  panel, so they read as pickers, not commands).
- **File-uploader buttons** — the ⬆ Upload button inside every dropzone.
- **MYP / School grade chips** (`.cam-grade-box`, in `theme_css()`) —
  read-only, but deliberately big (`min-height: 2.5rem`, matching the Effort
  selectbox beside them) so the value is easy to select and copy/paste.
  Border only, no fill, so they read as display-only.

No override needed for most of these — the tall tier *is* Streamlit's
default; only `.cam-grade-box` sets it explicitly.

## File-upload dropzones

All dropzones (Upload & stage files modal, Window 2 roster intake) share one
grey container style, pinned globally in `DENSE_CSS`:

```css
[data-testid="stFileUploaderDropzone"] {
    min-height: 4.25rem; padding: 0.75rem;
    align-items: center; justify-content: flex-start;
}
```

- `min-height: 4.25rem` is Streamlit's own default — pinned so a keyed
  override can never shrink one dropzone out of step with the others (the
  roster dropzone used to be compacted to 2.2 rem and looked squashed next to
  the modal's).
- The ⬆ Upload button sits **flush left** and **vertically centered**
  (`align-items: center`; the Streamlit default is `flex-start`, which leaves
  the button hugging the top).
- The roster dropzone additionally hides its drag-and-drop instruction text
  (the format hint lives in the caption below the box).

## Row alignment

When several controls share a row (`st.columns`), pass
`vertical_alignment="center"` so mixed heights (28 px buttons next to 40 px
fields) line up on their midlines — the roster rows (↑ ↓ · name · gender ·
⚠ · Focus) are the reference example. Rows already doing this: top bar,
Window 1 action bar, assignment rows, exam grading, roster rows and intake,
archived-students and archived-assignments rows, mark-cell rows, LLM
parameter/generate rows, Save-now row.

Two deliberate exceptions:

- **System deliverables** uses `vertical_alignment="top"` — each column
  stacks a Build button above its ⬇ download button, so top alignment keeps
  the four columns' first rows level.
- **Overall comment header** uses `vertical_alignment="bottom"` — the
  Remarks popover trigger aligns to the label's baseline.
