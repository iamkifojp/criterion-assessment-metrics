"""CAM2 web server: a thin JSON layer between the browser and ``engine/``.

Every route either reads state or calls an engine function and saves. Engine
problems arrive as ``UserError`` and leave as translated JSON::

    {"error": "<code>", "message": "<text in the teacher's language>",
     "save_error": true|false}

Start it with ``python launcher.py`` (opens the browser), not directly.
"""

from __future__ import annotations

import base64
import io
import os
import threading

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from appstate import AppState
from engine import (gradebook_xlsx, grading_summary, host, i18n, keywords, model, reports, roster,
                    rubrics, slicer, storage, tables, workflow)
from engine.errors import SaveError, UserError
from engine.pickers import documents_folder, open_in_file_manager, pick_folder, pick_pdf
from engine.slicer import Layout

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
VERSION = "0.2.0-dev"


def create_app(state: AppState | None = None, shutdown=None) -> Flask:
    app = Flask(__name__, static_folder=os.path.join(APP_ROOT, "static"),
                static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024      # uploads: class lists, rubrics
    state = state or AppState()
    app.extensions["cam2_state"] = state

    def language() -> str:
        lang = storage.get_pref("language", i18n.DEFAULT_LANGUAGE)
        return lang if lang in i18n.LANGUAGES else i18n.DEFAULT_LANGUAGE

    def body() -> dict:
        return request.get_json(silent=True) or {}

    @app.after_request
    def no_stale_files(response):
        # After an upgrade the browser must not keep running old scripts.
        if request.path.startswith("/static/") or request.path == "/":
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.errorhandler(UserError)
    def user_error(err: UserError):
        return jsonify({"error": err.code, "params": {k: str(v) for k, v in err.params.items()},
                        "message": i18n.error_text(err, language()),
                        "save_error": isinstance(err, SaveError)}), 409 if isinstance(err, SaveError) else 400

    # --- Views of the state ---------------------------------------------------------

    def session_view() -> dict | None:
        if state.session is None:
            return None
        config = state.config
        layout = Layout.from_config(config.get("layout"))
        students = [dict(s, display_name=workflow.display_name(config, s))
                    for s in config.get("students") or []]
        grades = state.grades or {}
        return {
            "folder": state.session.folder,
            "config": dict(config, students=students,
                           keywords=keywords.keyword_list(config, language())),
            "grid": {"cols": layout.cols, "rows": layout.rows},
            "grades": {"grades": grades.get("grades") or {}, "overall": grades.get("overall") or {}},
            "progress": grading_summary.progress(config, grades),
            "summary": grading_summary.class_summary(config, grades),
            "saved_at": state.last_saved_at(),
            "save_failed": state.save_failed,
        }

    def host_view() -> dict | None:
        """The app that opened CAM2, and its one exam (None when used on its own)."""
        if not state.host:
            return None
        folder = state.host["session_folder"]
        return {"host": state.host["host"], "exam_name": state.host["exam_name"],
                "class_name": state.host["class_name"], "session_folder": folder,
                "session_exists": storage.is_session_folder(folder),
                "roster_count": len(state.host["roster"])}

    def adopt_host_session(save: bool = True) -> None:
        """The host's own session uses the host's class list (papers are
        matched again once scans come in)."""
        if host.is_host_session(state.host, state.session.folder):
            host.apply_roster(state.config, state.host)
            if save:
                state.save_config()

    def ok(**extra):
        return jsonify(dict({"ok": True, "session": session_view()}, **extra))

    def set_step(step: int) -> None:
        resume = state.config.setdefault("resume", {})
        resume["step"] = max(int(resume.get("step") or 1), step) if step > 1 else 1
        resume["current"] = step

    # --- Shell ----------------------------------------------------------------------

    @app.get("/")
    def index():
        return send_from_directory(os.path.join(APP_ROOT, "templates"), "index.html")

    @app.get("/api/ping")
    def ping():
        return jsonify({"app": "cam2", "version": VERSION})

    @app.get("/api/i18n")
    def strings():
        lang = language()
        return jsonify({"language": lang, "strings": i18n.strings(lang)})

    @app.post("/api/language")
    def set_language():
        lang = body().get("language")
        if lang not in i18n.LANGUAGES:
            raise UserError("unknown_language", language=lang)
        storage.set_pref("language", lang)
        return jsonify({"ok": True, "language": lang})

    @app.post("/api/prefs")
    def set_prefs():
        data = body()
        for key in ("hide_names", "shuffle_papers"):
            if key in data:
                storage.set_pref(key, bool(data[key]))
        return jsonify({"ok": True})

    @app.post("/api/host/handoff")
    def host_handoff():
        """A host (CAM) asks this running CAM2 to open one of its exams."""
        state.host = host.normalize(body())
        if state.session is not None and not host.is_host_session(state.host, state.session.folder):
            try:
                state.save_all()
            finally:
                state.close_session()
        return jsonify({"ok": True})

    @app.post("/api/host/ready")
    def host_ready():
        """Grading finished: the host may read the results (or not yet)."""
        state.require_session()
        host.set_ready(state.config, bool(body().get("ready")))
        state.save_config()
        return ok()

    @app.post("/api/heartbeat")
    def heartbeat():
        other = state.heartbeat()
        return jsonify({"ok": True, "locked_by": other})

    @app.post("/api/quit")
    def quit_app():
        state.close_session()
        if shutdown:
            threading.Timer(0.3, shutdown).start()
        return jsonify({"ok": True})

    @app.get("/api/state")
    def get_state():
        return jsonify({"language": language(), "version": VERSION,
                        "session": session_view(), "recent": storage.list_recent(),
                        "host": host_view(),
                        "prefs": {key: bool(storage.get_pref(key, False))
                                  for key in ("hide_names", "shuffle_papers")}})

    # --- Pickers --------------------------------------------------------------------

    @app.post("/api/pick")
    def pick():
        data = body()
        kind = data.get("kind")
        lang = language()
        initial = data.get("initial") or None
        if kind == "pdf":
            path = pick_pdf(i18n.t("pick.combined_pdf", lang), initial)
        elif kind in ("scans_folder", "photos_folder", "save_folder", "session_folder"):
            path = pick_folder(i18n.t(f"pick.{kind}", lang), initial)
        else:
            raise UserError("unknown_picker")
        return jsonify({"path": path})

    @app.post("/api/inspect")
    def inspect():
        data = body()
        path = str(data.get("path") or "").strip().strip('"')
        if data.get("kind") == "pdf":
            return jsonify(workflow.inspect_combined_pdf(path))
        return jsonify(workflow.inspect_scans_folder(path))

    @app.post("/api/preview-paper")
    def preview_paper():
        """The first paper as it will be imported, as small JPEG data URLs."""
        result = workflow.preview_paper(body().get("source") or {})
        images = ["data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")
                  for b in result.pop("images")]
        return jsonify(dict(result, images=images))

    @app.get("/api/default-folder")
    def default_folder():
        name = request.args.get("exam") or "Exam"
        return jsonify({"path": storage.default_session_folder(name, documents_folder())})

    # --- Opening, creating and closing sessions -------------------------------------

    def open_folder(folder: str, force: bool):
        """Open a session. Returns (None, {"locked_by": …}) instead when another
        computer has it open, unless ``force``."""
        if not force:
            other = storage.other_lock_holder(folder)
            if other:
                storage.open_session(folder)         # still report a non-session folder
                return None, {"locked_by": other}
        session, config, grades = storage.open_session(folder)
        state.set_session(session, config, grades)
        storage.claim_lock(folder, force=True)
        adopt_host_session()
        rescue = {}
        for kind, file in (("config", session.config_file), ("grades", session.grades_file)):
            newer = file.newer_emergency_copy()
            if newer:
                rescue[kind] = newer.get("saved_at")
        state.remember()
        return session, {"emergency": rescue} if rescue else {}

    @app.post("/api/session/open")
    def session_open():
        data = body()
        folder = str(data.get("folder") or "").strip().strip('"')
        session, extra = open_folder(folder, bool(data.get("force")))
        if session is None:
            return jsonify(dict({"ok": False}, **extra))
        return ok(**extra)

    @app.post("/api/session/restore-emergency")
    def restore_emergency():
        session = state.require_session()
        with state.lock:
            newer = session.config_file.newer_emergency_copy()
            if newer:
                state.config = newer
                state.save_config()
            newer = session.grades_file.newer_emergency_copy()
            if newer:
                state.grades = session.grades_file.save(newer, allow_shrink=True)
        return ok()

    @app.post("/api/session/reopen")
    def session_reopen():
        folder = state.require_session().folder
        session, extra = open_folder(folder, True)
        return ok(**extra)

    @app.post("/api/session/create")
    def session_create():
        data = body()
        exam = str(data.get("exam_name") or "").strip()
        if not exam:
            raise UserError("exam_name_required")
        source = data.get("source") or {}
        workflow.check_source(source)
        layout = Layout(str(data.get("paper") or ""), landscape=bool(data.get("landscape")))
        chosen = str(data.get("save_folder") or "").strip().strip('"')
        if not chosen:
            raise UserError("save_folder_required")
        if host.is_host_session(state.host, chosen):
            # The host reads this exact folder, so never a subfolder of it.
            folder = os.path.abspath(chosen)
            if os.path.isdir(folder) and os.listdir(folder):
                raise UserError("host_folder_not_empty", folder=folder)
        else:
            folder = workflow.choose_session_folder(chosen, exam)
        session, config, grades = storage.create_session(folder, exam)
        config["layout"] = layout.to_config()
        state.set_session(session, config, grades)
        storage.claim_lock(folder, force=True)
        state.save_config()
        adopt_host_session()
        return start_import(source)

    def start_import(source: dict):
        session = state.require_session()

        def work(job):
            config = dict(state.config)
            workflow.import_scans(session, config, source, job.progress)
            with state.lock:
                state.config = config
                set_step(1)
                adopt_host_session(save=False)
                state.save_config()
            return {"students": len(config["students"])}

        job = state.start_job("import", work)
        return ok(job=job.id)

    @app.post("/api/scans/replace")
    def scans_replace():
        state.require_session()
        # New papers are numbered from s001 again, so kept grades would land
        # on whichever student is now first, second, ...
        if workflow.class_has_work(state.grades):
            raise UserError("scans_locked_graded")
        source = body().get("source") or {}
        workflow.check_source(source)
        return start_import(source)

    @app.post("/api/scans/add")
    def scans_add():
        """More papers for this exam, e.g. a student who sat it late."""
        session = state.require_session()
        source = body().get("source") or {}
        workflow.check_source(source)

        def work(job):
            config = dict(state.config)
            added = workflow.add_papers(session, config, source, job.progress)
            with state.lock:
                state.config = config
                adopt_host_session(save=False)
                state.save_config()
            return {"added": added}

        job = state.start_job("import", work)
        return ok(job=job.id)

    @app.post("/api/pages/edit")
    def pages_edit():
        """Fix a page on the scan-check screen (move, turn, remove, add blank,
        or turn / swap a booklet sheet)."""
        session = state.require_session()
        data = body()
        with state.lock:
            config = dict(state.config)
            config["students"] = [dict(s) for s in config.get("students") or []]
            where = workflow.edit_pages(session, config, state.grades,
                                        str(data.get("student") or ""),
                                        int(data.get("page") or 1), str(data.get("action") or ""))
            state.config = config
            state.save_config()
        return ok(where=where)

    @app.post("/api/session/close")
    def session_close():
        if state.session is not None:
            try:
                state.save_all()
            finally:
                state.close_session()
        return jsonify({"ok": True, "recent": storage.list_recent()})

    @app.post("/api/session/forget")
    def session_forget():
        storage.forget_session(str(body().get("folder") or ""))
        return jsonify({"ok": True, "recent": storage.list_recent()})

    @app.post("/api/save")
    def save_now():
        state.save_all()
        return ok()

    @app.post("/api/step")
    def goto_step():
        state.require_session()
        step = int(body().get("step") or 1)
        if not 1 <= step <= 5:
            raise UserError("unknown_step")
        if step >= 3 and not state.config.get("sliced"):
            raise UserError("not_sliced")
        set_step(step)
        state.save_config()
        return ok()

    # --- Jobs -------------------------------------------------------------------------

    @app.get("/api/job/<job_id>")
    def job_status(job_id):
        job = state.jobs.get(job_id)
        if job is None:
            abort(404)
        out = {"id": job.id, "kind": job.kind, "status": job.status,
               "done": job.done, "total": job.total, "result": job.result}
        if job.error is not None:
            err = job.error if isinstance(job.error, UserError) else \
                UserError("unexpected", detail=str(job.error))
            out["error"] = {"code": err.code, "message": i18n.error_text(err, language()),
                            "save_error": isinstance(err, SaveError)}
        if job.status != "running":
            out["session"] = session_view()
        return jsonify(out)

    # --- Images -----------------------------------------------------------------------

    def image_cache(response):
        # A URL with ?v=<when the papers were sliced> never changes content, so
        # the browser may keep it (no flicker when the grading screen redraws).
        response.headers["Cache-Control"] = ("private, max-age=86400" if request.args.get("v")
                                             else "no-store")
        return response

    def jpeg(data: bytes):
        return image_cache(send_file(io.BytesIO(data), mimetype="image/jpeg"))

    def session_file(rel: str, mimetype: str):
        path = state.require_session().path(rel)
        if not os.path.isfile(path):
            abort(404)
        return image_cache(send_file(path, mimetype=mimetype))

    @app.get("/api/thumb/<student_id>")
    def thumb(student_id):
        workflow.find_student(state.config or {}, student_id)
        return session_file(f"{storage.THUMBS_DIR}/{student_id}.jpg", "image/jpeg")

    @app.get("/api/crop/<region_id>/<student_id>")
    def crop(region_id, student_id):
        state.require_session()
        workflow.find_student(state.config, student_id)
        known = {q["id"] for q in state.config.get("questions") or []} | {model.NAME_BOX_ID}
        if region_id not in known:
            abort(404)
        return session_file(f"{storage.CROPS_DIR}/{region_id}/{student_id}.png", "image/png")

    @app.get("/api/page/<student_id>/<int:page>")
    def page_image(student_id, page):
        session = state.require_session()
        student = workflow.find_student(state.config, student_id)
        width = min(max(int(request.args.get("w") or 1400), 200), 2400)
        layout = Layout.from_config(state.config.get("layout"))
        outline = []
        for r in request.args.get("boxes", "").split(","):
            if r.strip():
                outline.append(slicer.parse_range(r, layout))
        return jpeg(slicer.page_preview(workflow.student_scan_path(session, student), page,
                                        layout, outline, width))

    @app.get("/api/preview-crop/<student_id>")
    def preview_crop(student_id):
        session = state.require_session()
        student = workflow.find_student(state.config, student_id)
        layout = Layout.from_config(state.config.get("layout"))
        boxes = slicer.parse_boxes([r for r in request.args.get("boxes", "").split(",")
                                    if r.strip()], layout)
        return jpeg(slicer.crop_preview(workflow.student_scan_path(session, student),
                                        boxes, layout))

    # --- Step 2: set-up -----------------------------------------------------------------

    @app.post("/api/setup/layout")
    def setup_layout():
        state.require_session()
        data = body()
        current = Layout.from_config(state.config.get("layout"))
        workflow.set_layout(state.config, data.get("paper") or current.paper,
                            data.get("density") or current.density,
                            data.get("landscape", current.landscape))
        state.save_config()
        return ok()

    @app.post("/api/setup/mode")
    def setup_mode():
        state.require_session()
        workflow.set_mode(state.config, body().get("mode"), state.grades)
        set_step(2)
        state.save_config()
        return ok()

    @app.post("/api/setup/rubrics")
    def setup_rubrics():
        state.require_session()
        workflow.set_rubrics(state.config, body().get("rubrics") or [])
        state.save_config()
        return ok()

    @app.post("/api/setup/keywords")
    def setup_keywords():
        """The exam's quick-comment list: [{label, type: strength|growth}]."""
        state.require_session()
        keywords.set_list(state.config, body().get("keywords") or [])
        state.save_config()
        return ok()

    @app.post("/api/setup/rubrics/check")
    def check_rubric():
        """Validate one rubric card without saving (for inline messages)."""
        rubrics.normalize_rubric(body().get("rubric") or {})
        return jsonify({"ok": True})

    @app.post("/api/setup/rubrics/import")
    def import_rubric_file():
        upload = request.files.get("file")
        if upload is None:
            raise UserError("no_file")
        rows = tables.read_table(upload.filename, upload.read())
        return jsonify({"rubrics": rubrics.import_rubrics(rows)})

    @app.get("/api/setup/rubrics/template")
    def rubric_template():
        lang = request.args.get("lang") or language()
        name = "CAM2_rubric_template.xlsx" if lang != "ja" else "CAM2_ルーブリック_テンプレート.xlsx"
        return send_file(io.BytesIO(rubrics.template_xlsx(lang)), as_attachment=True,
                         download_name=name,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/setup/questions")
    def setup_questions():
        state.require_session()
        workflow.set_questions(state.config, body(), state.grades)
        state.save_config()
        return ok()

    @app.post("/api/slice")
    def slice_papers():
        session = state.require_session()
        workflow.check_ready(state.config)

        def work(job):
            config = dict(state.config)
            summary = workflow.slice_session(session, config, job.progress)
            with state.lock:
                state.config = config
                set_step(2)
                state.save_config()
            return summary

        job = state.start_job("slice", work)
        return ok(job=job.id)

    @app.post("/api/slice-question")
    def slice_one_question():
        """Crop one question again for every paper, after its box was adjusted."""
        session = state.require_session()
        qid = str(body().get("question_id"))

        def work(job):
            config = dict(state.config)
            config["crops_of"] = dict(config.get("crops_of") or {})
            summary = workflow.slice_question(session, config, qid, job.progress)
            with state.lock:
                state.config = config
                state.save_config()
            return summary

        if not workflow.crops_known(state.config):
            raise UserError("not_sliced")
        job = state.start_job("slice", work)
        return ok(job=job.id)

    # --- Step 3: names ------------------------------------------------------------------

    @app.post("/api/roster/upload")
    def roster_upload():
        state.require_session()
        upload = request.files.get("file")
        if upload is None:
            raise UserError("no_file")
        rows = tables.read_table(upload.filename, upload.read())
        if not rows:
            raise UserError("no_names_found")
        state.roster_rows = rows
        has_header = roster.guess_header(rows)
        return jsonify({"preview": roster.preview(rows), "rows": len(rows),
                        "has_header": has_header,
                        "columns": roster.guess_name_columns(rows, has_header)})

    @app.post("/api/roster/columns")
    def roster_columns():
        state.require_session()
        if not state.roster_rows:
            raise UserError("no_file")
        data = body()
        entries = roster.extract_names(state.roster_rows,
                                       [int(c) for c in data.get("columns") or []],
                                       bool(data.get("has_header")))
        workflow.set_roster(state.config, entries)
        state.roster_rows = None
        state.save_config()
        return ok()

    @app.post("/api/roster/paste")
    def roster_paste():
        state.require_session()
        workflow.set_roster(state.config, roster.parse_pasted(body().get("text") or ""))
        state.save_config()
        return ok()

    @app.post("/api/roster/clear")
    def roster_clear():
        state.require_session()
        workflow.clear_roster(state.config)
        state.save_config()
        return ok()

    # --- Step 4: grading -------------------------------------------------------------

    @app.post("/api/grade")
    def grade():
        """Record a grade and/or comment for one paper and question, and save.

        Leave out "value" to change only the comment; "value": null clears it.
        "rubric_id" says which criterion of a question assessed on several.
        "keywords" ticks exactly those quick comments and rebuilds the
        comment's generated line.
        """
        state.require_session()
        data = body()
        value = data["value"] if "value" in data else ...
        with state.lock:
            grading_summary.set_grade(state.config, state.grades, str(data.get("student_id")),
                                      str(data.get("question_id")), value, data.get("comment"),
                                      rubric_id=data.get("rubric_id") or None)
            if "keywords" in data:
                keywords.apply(state.config, state.grades, str(data.get("student_id")),
                               str(data.get("question_id")), data.get("keywords") or [], language())
            state.save_grades()
            state.remember()
        return ok()

    @app.post("/api/position")
    def position():
        """Remember the question and paper on screen, for resuming."""
        state.require_session()
        data = body()
        resume = state.config.setdefault("resume", {})
        qid, sid, rid = data.get("question_id"), data.get("student_id"), data.get("rubric_id") or None
        if qid not in {q["id"] for q in state.config.get("questions") or []}:
            raise UserError("unknown_question", question=qid)
        workflow.find_student(state.config, sid)
        if (resume.get("question_id"), resume.get("student_id"), resume.get("rubric_id")) != (qid, sid, rid):
            resume["question_id"], resume["student_id"], resume["rubric_id"] = qid, sid, rid
            state.save_config()
        return ok()

    # --- Step 5: review and export ----------------------------------------------------

    @app.post("/api/overall")
    def overall():
        """Overall comment, report-only total (marks) or final levels (rubric).

        An empty or null total/level goes back to the calculated value.
        """
        state.require_session()
        data = body()
        sid = str(data.get("student_id"))
        workflow.find_student(state.config, sid)
        with state.lock:
            if "comment" in data:
                grading_summary.set_overall_comment(state.grades, sid, data.get("comment"))
            if "report_total" in data:
                value = data.get("report_total")
                grading_summary.set_report_total(state.grades, sid, None if value in ("", None) else value)
            for rid, level in (data.get("final_levels") or {}).items():
                grading_summary.set_final_level(state.config, state.grades, sid, rid,
                                                None if level in ("", None) else level)
            state.save_grades()
        return ok()

    @app.post("/api/choice")
    def choice():
        """The answers that count in a "teacher picks" choice group for one student."""
        state.require_session()
        data = body()
        sid = str(data.get("student_id"))
        workflow.find_student(state.config, sid)
        with state.lock:
            grading_summary.set_choice(state.config, state.grades, sid,
                                       str(data.get("group_id")), data.get("questions"))
            state.save_grades()
        return ok()

    @app.post("/api/export")
    def export():
        """Make the student PDFs and/or the Excel gradebook in reports/."""
        session = state.require_session()
        data = body()
        lang = data.get("language") or language()
        if lang not in i18n.LANGUAGES:
            raise UserError("unknown_language", language=lang)
        what = data.get("what") or "all"
        if not state.config.get("sliced"):
            raise UserError("not_sliced")

        def work(job):
            with state.lock:
                config, grades = dict(state.config), dict(state.grades)
            result = {"folder": session.path(storage.REPORTS_DIR), "pdfs": 0, "errors": []}
            result["excel"] = os.path.basename(
                gradebook_xlsx.export_gradebook(session, config, grades, lang))
            if what == "all":
                pdfs = reports.export_student_pdfs(session, config, grades, lang, job.progress)
                result["pdfs"] = len(pdfs["files"])
                result["errors"] = pdfs["errors"]
            return result

        job = state.start_job("export", work)
        return ok(job=job.id)

    @app.post("/api/open-folder")
    def open_folder_in_os():
        session = state.require_session()
        folder = session.path(storage.REPORTS_DIR)
        os.makedirs(folder, exist_ok=True)
        if not open_in_file_manager(folder):
            raise UserError("cannot_open_folder", folder=folder)
        return jsonify({"ok": True})

    @app.post("/api/students/<student_id>/match")
    def student_match(student_id):
        state.require_session()
        data = body()
        workflow.match_student(state.config, student_id, data.get("roster_id") or None,
                               data.get("name"))
        state.save_config()
        return ok()

    return app
