"""CAM2 engine: everything that is not the web UI.

Modules are framework-free so they can be tested on their own:

    slicer           paper sizes, grids, cropping, PDF splitting, previews
    storage          session folders, safe saving, recent sessions, prefs
    model            shapes of cam2_session.json and grades.json
    rubrics          teacher-made rubrics, Excel import, blank template
    roster           class lists and matching papers to names
    tables           reading .xlsx / .csv into rows
    grading_summary  recording grades, totals, averages, overrides
    i18n             English / Japanese text
    pickers          native folder / PDF dialogs (Windows, macOS)
    errors           UserError with translatable codes
"""
