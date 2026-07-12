# User manual

A short, illustrated tour of Criterion Assessment Metrics (CAM) for the teacher
using it day to day. If you haven't installed it yet, start with the
[Setup guide](SETUP.md).

> Everything shown below runs on the bundled **fictional sample class** — the
> students, grades and comments are invented.

---

## The three-window cockpit

CAM lays the whole grading job out on one screen, in three panels that read left
to right — the same order you actually work in: **pick the work → score it →
write the report.**

![The three-window cockpit layout](images/cockpit-layout.svg)

| Window | You use it to… |
|---|---|
| **1 · Classes & Assignments** | Switch between the classes you teach, import grade CSVs, watch a synced folder for new work, and see the timeline of assessed assignments. |
| **2 · Students & Evidence** | See every student's Criterion A–D scores, flag or exclude a piece, mark work late, and set the weighting method. Each student's gender (optional) sets the pronouns used in their comment. |
| **3 · Report & Comment** | Read the final criterion grades — plus, if you switch them on in Settings, the school-specific **MYP Grade** / **Effort** / **School Grade** — jot teacher remarks, and generate the report-card comment. |

You can drag the column widths and panel heights to suit your screen; those
preferences are saved to your device only.

---

## The daily workflow

![The five-step grading workflow](images/workflow.svg)

1. **Ingest.** In Window 1, import a grade CSV (or point CAM at a folder it
   watches). Scores are matched to students and dated automatically.
2. **Review.** In Window 2, glance over the evidence. Exclude a piece that
   shouldn't count, flag a "wrong assignment" upload, or mark something late —
   without deleting anything.
3. **Grade.** CAM computes a recency-weighted suggestion for each criterion and
   rolls them into the report grades (see below).
4. **Comment.** In Window 3, generate a report-card comment. With no setup this
   copies a ready-made prompt to your clipboard; with an API key it writes the
   comment in place.
5. **Finalize.** Export the mail-merge pack and snapshot the term so next term's
   comments can build on this one.

---

## How a grade is worked out

Each MYP criterion is scored **0–8**, and a student collects several scores per
criterion across the term. CAM weights **recent** work more heavily and sums the
per-criterion results — that criterion picture is always the core of the grade.

![Criteria roll up into the MYP grade and School grade](images/grade-rollup.svg)

- The **weighting method** (for example *"60/40 Recency"*) is yours to choose in
  Window 2.
- **Optional school-specific roll-ups.** Some schools also report banded grades
  on top of the criteria. These are **off by default**; turn on the ones you use
  in **⚙ Settings → Report-card grades**:
  - **MYP Grade (1–7)** — looked up straight from the criterion sum.
  - **Effort / English-use** — a per-student, per-term score you set (its range
    is configurable in the same settings section).
  - **School Grade (1–10)** — folds the Effort/English-use score in with the
    criterion sum through a lookup table.

  When enabled they appear in Window 3 and in the report cards; when off, CAM
  reports the criterion grades alone.

Nothing here is a black box: every score that feeds a grade is visible in Window
2, and you can exclude or re-weight any of it.

---

## Report-card comments

CAM drafts a comment from the same evidence you can see on screen — it is
pronoun-aware (from the optional gender field) and term-aware (it can build on a
previous term's finalized comment).

- **Clipboard mode (no setup).** CAM assembles the prompt; you paste it into any
  chatbot and paste the result back. Nothing leaves your machine automatically.
- **API mode (optional).** Add a Claude or Gemini API key in the comment
  settings and CAM writes the comment in one click. See
  [Setup · report-comment AI](SETUP.md#6-optional-report-comment-ai).

Always read and adjust a generated comment before it goes on a report — it is a
first draft built from your grades, not a replacement for your judgement.

---

## The grading workspace (optional)

For grading student work that syncs in from Google Drive / OneDrive, CAM can
launch a companion **grading workspace**: a thumbnail grid of a whole class's
submissions, an anonymous grading mode (grade without seeing names to reduce
bias), and PDF exam slicing for marking scanned papers. It hands finished grades
back to the dashboard automatically. Setup is in
[Setup · the grading workspace](SETUP.md#7-optional-the-grading-workspace--google-drive).

**Exam setup — grid density.** In **📝 Exam Setup** you frame each question by
typing a coordinate range (like `A1:C3`) against a grid drawn over the scanned
page. Next to **Paper size** is a **Grid** control that sets how fine that grid
is: **Compact (≈1.4 cm cells)** is the default and suits most papers; **Fine
(≈1 cm cells)** lets you frame small answers tightly (its columns run past Z into
AA, AB, … for the densest pages). Pick the density *before* you type the ranges
— switching it afterwards re-checks every range against the new grid and
red-flags any that no longer fit, so you'd re-type them. Older exams you saved
before this option keep their original grid: loading one shows a **Standard
(legacy 2 cm)** state so its coordinates still line up, and you only move to
Compact/Fine when you choose to.

**Exam setup — name box.** Click **+ Add name box** to frame the region where
students write their name. It appears as a pinned **Name** row above your
questions — give it a coordinate range like any question, but it has no score
and never becomes a graded column. CAM uses these name crops later to help you
spot a script saved under the wrong student's name. The name box is optional;
delete the row to remove it.

**Exam setup — sections.** Questions are grouped into **sections**. A new exam
starts with one section holding everything; click **+ Add section** to add more
(each section header has a name and sits above the questions that belong to it —
drag questions with ↑/↓ to move them between sections). By default every
question in a section counts. If a section is a **choice** — students answer,
say, 2 of 4 questions — untick **all required** on its header and type how many
**choose N** count. When a student answers more than that, CAM shows the section
as unresolved (`?`) and you pick which answers count from the cockpit (Window 3);
it never guesses. Older exams with no sections load as a single default section
and grade exactly as before.

**Resolving a choice (`?`) in the cockpit.** Once a section exam is synced back
into CAM, focus a student in Window 2 and look in Window 3's marks list: each
exam shows a **📝** block with a row per section (`Section A · 12/20`) and a
running exam total. A section a student *over-answered* shows a **? resolve**
button and the exam total reads **?** until you deal with it. Click it, tick the
answers that should count (you can pick up to the section's *choose N* — the rest
grey out), and Save. The total flips from `?` to a number, and you can reopen and
change your picks any time. Until you resolve it, that student is **left out of
the exam's class average** and can't be given a 0–8 grade in Window 1's **📝 Exam
grading** panel (their row there is disabled with a nudge to resolve first). The
name crops you framed at setup show up in the exam's analytics dialog (click the
exam in Window 1) next to each student id, so a script filed under the wrong name
is easy to catch.

**Adjusting a question's box while grading.** If a question's crop is cutting off
an answer, you don't have to re-process the whole exam. In the grading screen's
exam mode, click the **✎** on that question's column (or **✎ Adjust** next to the
question selector) — Exam Setup opens focused on that question, scrolled to its
row with the page preview **zoomed in** on its cells so you can see exactly what's
being framed. Widen or shift its coordinate range, then click **⚙ Re-slice this
question**: only that question is re-cropped for every student (it takes seconds),
and every mark you've already entered stays put. Back in the grading tab the
question's answer images refresh to the new framing on their own. Use **⤢ Full
page** to zoom back out; you can also click any question's colour swatch in setup
to zoom straight to it.

---

## Where your data lives

Your real gradebook is a single `acm_database.json` in a folder **you** choose —
ideally a cloud-synced one so every device shares it and it's backed up. CAM
never stores real student data inside the program folder. To change the
location, open **⚙ Settings → Custom database location**
([details](SETUP.md#5-point-cam-at-your-own-data)).

## Backing up and restoring a term

Under **⚙ Settings → 🗄 Term backup & restore** you can take a deliberate,
end-of-term snapshot of one whole term and, if disaster strikes, put it back.

**Back up a term.** Pick a **backup folder** (anywhere you like — a USB stick or
a non-cloud folder is fine, for an off-site copy) and a **term**, then press
**⬇ Back up term**. CAM writes one self-describing file,
`cam_term_backup_<term>_<date-time>.json`, holding everything it knows for that
term: assignments, grades, exam results, overall comments, effort scores and the
On/late/excused settings. It only ever writes *outside* your database, so
backing up can never harm your live data. Do this at the end of each term.

**Restore a term** — a rescue tool, not an editing tool. Reach for it only if
your database has been damaged: normally you'd just edit the data directly.
First recover the file itself if needed (from your cloud's version history or a
`.bak` beside it), *then* use restore to recover a term's finer detail. Press
**⬆ Restore from backup…**, choose a backup file, and CAM shows a **preview** of
exactly what would change — class by class — plus the date the backup was made.

> ⚠ Restore **replaces that whole term**. Anything you entered for that term
> *after* the backup was made is **not** in the file and will be lost. Every
> other term is left untouched.

To go ahead you type `RESTORE Term 1` (matching the term) to confirm. CAM writes
an automatic safety copy of your current database first, then restores. Your
teacher remarks and final-grade overrides are only *filled in where blank*, so
restoring one term never overwrites another term's remarks.
