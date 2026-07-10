# CAM Grading Workspace

Flask sub-app of **Criterion Assessment Metrics (CAM)** — formerly
*google-classroom-grading (GCG)*. Visually grades Drive-hosted assignments and
scanned exams (Exam Setup uses a paper-size-aware ~2cm grid: A4 10×15,
B5 9×12, A3 15×21).

Run standalone with `python app.py [--port N]`, or let the CAM dashboard's
"Grade this Assignment/Exam" button spawn it on port 5001 with the target
class/assignment passed as URL query parameters.
