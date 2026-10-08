# CAM Grading Workspace

## Draft submissions and PDF page controls

In CAM Module 1, open an assignment's **Manage** dialog, enable **Draft —
comments only**, choose feedback criterion **A**, and click **Apply assessment
type**. Reopen the grading workspace from CAM. Grade inputs are hidden; write
comments/use keywords and export as usual. Saving a comment or keyword marks
the artwork **SEEN** on its thumbnail and expanded card, including after reload.
Drafts without feedback have no review badge. Module 2 retains submission matching;
Module 3 shows the feedback without zeros or a contribution to final grades.
New assignments can also be created directly as drafts.

Open a PDF by clicking its thumbnail. **Omit pages** accepts ranges such as
`1-9` (start at original page 10), `1-10` (start at page 11), or `1-9, 12`.
**Apply to assignment** remembers the selection for every PDF in that assignment.
Original documents remain intact. **Page thumbnails** switches to a grid;
click a page to return to single-page viewing. Zoom only changes page size.
Different document layouts may need different ranges, so check original page
numbers before applying a shared range.

Drive-hosted DOCX files support matching and draft comments, and open in Drive's
embedded Word preview. Use **Open in Drive** if sign-in or browser cookie rules
prevent the embed from loading. CAM cannot filter pages in Google's viewer:
upload a PDF copy to use CAM's omitted-page and page-thumbnail controls. Keep
the same student ID/name in the filename. Native Docs/Slides embeds have the
same limitation. No automatic conversion or Drive write access is added.

PDFs are downloaded on demand using the existing Drive connection. CAM prunes
older downloaded PDF copies to a 256 MiB budget, keeping the currently opened
file even if it is larger. Page thumbnails are generated on demand rather than
stored on disk. Restart CAM and its grading workspace after updating the code.

Flask sub-app of **Criterion Assessment Metrics (CAM)** — formerly
*google-classroom-grading (GCG)*. Visually grades Drive-hosted assignments and
scanned exams (Exam Setup uses a paper-size-aware ~2cm grid: A4 10×15,
B5 9×12, A3 15×21).

Run standalone with `python app.py [--port N]`, or let the CAM dashboard's
"Grade this Assignment/Exam" button spawn it on port 5001 with the target
class/assignment passed as URL query parameters.

### Matching downloaded or re-uploaded submissions

Upload the Classroom namelist in CAM's middle module for the correct class,
then open the assignment using **Grade this Assignment**. CAM supplies that
class's roster to the workspace. Later manual workspace loads read it from the
configured CAM data folder or saved assignment state.

Older versions could shorten alphanumeric school IDs to their initial digits,
collapsing several students into one roster entry. Re-upload the namelist after
updating if the workspace reports shortened IDs. Existing marks are not
automatically migrated from those ambiguous older keys.

Files match by roster email/student ID or a unique full name in the filename
(surname-first or first-name-first). Case, accents, spaces, underscores and
punctuation are normalized. A local student subfolder can supply the identity
too. Partial names, spelling mistakes, duplicate full names and conflicting
identities need manual review. Teacher-owned re-uploaded files therefore do not
all become one student when a roster is available. Matched cards show roster
names; exports retain CAM's student IDs.

Unmatched files remain individual cards, even with identical filenames. Grade
them, export/sync, then use **Match unmatched works** in Module 2 for the student
missing that assignment. Those decisions are reused on the next CAM handoff.
Already-saved marks under older identities stay there for review; automatic
matching never redistributes them to newly inferred students.

**Unzip downloaded Classroom folders first.** CAM can use a local class folder
containing one folder per assignment, without re-uploading to Drive. For
personal Drive, upload the extracted files/folders; a ZIP uploaded as one file
is not an assignment folder. Re-uploading creates new ownership metadata.
Local copy times also do not establish the original submission time; review
automatic Late flags. Office files have download links; PDFs/images preview
inline.

For future submissions, use **studentID_FirstName_SURNAME_Assignment** as the
filename convention. IDs make matching reliable even when names collide.
Keep real rosters and submissions in your runtime data folder, outside git.

### OAuth client setup

Place your downloaded `credentials.json` or `client_secret*.json` in the project
root or `cam_grading_workspace/`. Discovery checks the workspace, then the
project root, then the configured cloud folder. All these credential filenames
are git-ignored. See [setup guidance](../docs/SETUP.md).
