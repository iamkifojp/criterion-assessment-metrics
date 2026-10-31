// The browser's copy of the app state, and `act()`, which every button uses
// to call the server: it updates the session, re-renders, and routes errors
// (save problems become the red banner; anything else a toast).
import { get } from "./api.js";
import { toast } from "./ui.js";

export const app = {
  view: "start",          // start | new | wizard
  step: 1,                // wizard step shown (1–5)
  session: null,          // server's session view (config, grid, saved_at, …)
  recent: [],
  saveError: null,        // { message, code } while saving is failing
  lockWarning: null,      // another computer's lock seen by the heartbeat
  version: "",
  draft: {},              // per-screen scratch state, keyed by screen
  prefs: {},              // per-computer settings: { hide_names, shuffle_papers }
  host: null,             // the app that opened CAM2 (CAM) and its exam, or null
};

let renderFn = () => {};
export function onRender(fn) { renderFn = fn; }
export function render() { renderFn(); }

export function config() { return app.session?.config; }

// The criteria (rubrics) a question is assessed on, in rubric order, or the
// only rubric when none was picked (as grading_summary.question_rubric_ids).
export function criteriaOf(c, q) {
  const list = c.rubrics || [];
  const picked = new Set(q.rubric_ids ?? (q.rubric_id ? [q.rubric_id] : []));
  const found = list.filter((r) => picked.has(r.id));
  return found.length || list.length !== 1 ? found : [list[0]];
}

// One grade on one paper: marks or a level, "not_answered", or null (ungraded).
// Pass the criterion in Rubric mode; levels come from the server's summary.
export function gradeOf(sid, qid, rid = null) {
  if (!rid) return app.session.grades.grades?.[sid]?.[qid]?.value ?? null;
  const s = app.session.summary.students.find((x) => x.student_id === sid);
  return s?.levels?.[qid]?.[rid] ?? null;
}

export async function act(promise, { rerender = true, quiet = false } = {}) {
  try {
    const data = await promise;
    if (data && "session" in data) app.session = data.session;
    if (data && data.session !== undefined) app.saveError = null;
    if (rerender) render();
    return data;
  } catch (err) {
    await handleError(err, quiet);
    return null;
  }
}

export async function handleError(err, quiet = false) {
  if (err.saveError) {
    app.saveError = { message: err.message, code: err.code };
    try {                         // the server kept the change in memory: resync
      const state = await get("/api/state");
      app.session = state.session;
    } catch { /* offline */ }
    render();
  } else if (!quiet) {
    toast(err.message, "error");
  }
}
