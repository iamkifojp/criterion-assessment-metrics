// Talking to the CAM2 server. Every call returns parsed JSON or throws an
// Error carrying the server's translated message, its code and whether it was
// a save problem (which the app shows as a red banner, not a toast).
import { t } from "./i18n.js";

const OFFLINE = "CAM2 is not running. Start it again with “Start CAM2 Exam Grading”.";

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    // The server translates every other message, but it is gone: use the
    // strings loaded at start (English if even those never arrived).
    const text = t("error.offline");
    const err = new Error(text === "error.offline" ? OFFLINE : text);
    err.code = "offline";
    throw err;
  }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const err = new Error((data && data.message) || res.statusText);
    err.code = data && data.error;
    err.saveError = !!(data && data.save_error);
    err.data = data;
    throw err;
  }
  return data;
}

export const get = (path) => api(path);
export const post = (path, body) => api(path, { method: "POST", body: body ?? {} });
export const upload = (path, file) => {
  const form = new FormData();
  form.append("file", file);
  return api(path, { method: "POST", form });
};

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Poll a background job until it finishes. Resolves with the final status
// (including the refreshed session); rejects with the job's error.
export async function waitForJob(id, onProgress) {
  for (;;) {
    const job = await get(`/api/job/${id}`);
    if (onProgress) onProgress(job.done, job.total);
    if (job.status === "done") return job;
    if (job.status === "error") {
      const err = new Error(job.error.message);
      err.code = job.error.code;
      err.saveError = job.error.save_error;
      err.job = job;
      throw err;
    }
    await sleep(350);
  }
}
