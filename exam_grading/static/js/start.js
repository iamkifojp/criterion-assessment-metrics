// Start screen: continue a recent session, open a folder, or start new.
import { post } from "./api.js";
import { t } from "./i18n.js";
import { enterWizard } from "./main.js";
import { app, handleError, render } from "./store.js";
import { button, confirmBox, formatTime, h, pickerWait, toast } from "./ui.js";

export function renderStart() {
  return h("main", { class: "page start" },
    h("h1", {}, t("app.title")),
    h("p", { class: "lead" }, t("start.lead")),
    h("div", { class: "start-grid" },
      h("section", { class: "card" },
        h("h2", {}, "▶ ", t("start.continue")),
        recentList(),
        h("div", { class: "card-actions" }, button(t("start.open_folder"), browseForSession))),
      h("section", { class: "card accent" },
        h("h2", {}, "✨ ", t("start.new")),
        h("p", {}, t("start.new_hint")),
        h("ol", { class: "plain-steps" }, [1, 2, 3, 4, 5].map((n) => h("li", {}, t(`step.${n}.hint`)))),
        h("div", { class: "card-actions" },
          button(t("start.new_button"), () => { app.view = "new"; app.draft = {}; render(); }, "primary big")))),
    scanningGuide(),
    app.version ? h("p", { class: "version muted small" }, `CAM2 ${app.version}`) : null);
}

// How to scan: open on first use (no recent sessions), a click away after that.
const GUIDE_ITEMS = [1, 2, 3, 4, 5, 6, 7, 8, 9];

function scanningGuide() {
  return h("details", { class: "card guide", open: !app.recent.length },
    h("summary", {}, h("strong", {}, t("start.guide_show"))),
    h("p", { class: "lead" }, t("start.guide_lead")),
    h("ul", { class: "guide-list" }, GUIDE_ITEMS.map((n) => h("li", {},
      h("strong", {}, t(`guide.${n}.title`)), h("p", {}, t(`guide.${n}.text`))))));
}

function recentList() {
  if (!app.recent.length) return h("p", { class: "muted" }, t("start.no_recent"));
  return h("ul", { class: "recent" }, app.recent.map((item) => {
    const progress = item.total ? t("start.progress", { done: item.graded, total: item.total }) : "";
    const meta = [t("start.step_label", { step: item.step, name: t(`step.${item.step}`) }),
      progress, item.last_saved ? t("start.last_saved", { time: formatTime(item.last_saved) }) : ""]
      .filter(Boolean).join(" · ");
    if (!item.available) {
      return h("li", { class: "recent-item missing" },
        h("div", {}, h("strong", {}, item.exam_name || "—"), h("p", { class: "path" }, item.folder),
          h("p", { class: "warn-text" }, t("start.folder_missing"))),
        h("div", { class: "row" },
          button(t("start.browse"), browseForSession, "small"),
          button(t("start.remove"), () => forget(item.folder), "small ghost")));
    }
    return h("li", { class: "recent-item" },
      h("button", { type: "button", class: "recent-open", onclick: () => openSession(item.folder) },
        h("strong", {}, item.exam_name || "—"),
        h("span", { class: "meta" }, meta),
        h("span", { class: "path" }, item.folder)));
  }));
}

async function forget(folder) {
  const data = await post("/api/session/forget", { folder });
  app.recent = data.recent;
  render();
}

async function browseForSession() {
  const done = pickerWait();
  let path = null;
  try {
    path = (await post("/api/pick", { kind: "session_folder" })).path;
  } catch (err) {
    toast(err.message, "error");
  } finally {
    done();
  }
  if (path) openSession(path);
}

export async function openSession(folder, force = false) {
  let data;
  try {
    data = await post("/api/session/open", { folder, force });
  } catch (err) {
    await handleError(err);
    return;
  }
  if (!data.ok && data.locked_by) {
    const go = await confirmBox(t("open.locked_title"),
      t("save.locked_elsewhere", { computer: data.locked_by.computer, since: formatTime(data.locked_by.since) }),
      t("open.anyway"));
    if (go) openSession(folder, true);
    return;
  }
  app.session = data.session;
  app.saveError = null;
  enterWizard();
  render();
  if (data.emergency) {
    const when = formatTime(data.emergency.grades || data.emergency.config);
    const restore = await confirmBox(t("open.emergency_title"),
      t("save.emergency_found", { saved_at: when }), t("open.restore"), t("open.keep_folder"));
    if (restore) {
      try {
        const restored = await post("/api/session/restore-emergency");
        app.session = restored.session;
        enterWizard();
        render();
        toast(t("open.restored"), "ok");
      } catch (err) {
        await handleError(err);
      }
    }
  }
}
