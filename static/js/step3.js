// Step 3: bring in a class list (or type names), then pair each paper with a
// student, using the handwritten name crop.
import { post, upload } from "./api.js";
import { t } from "./i18n.js";
import { goTo } from "./main.js";
import { act, app, config, render } from "./store.js";
import { button, coach, confirmBox, h, modal, toast } from "./ui.js";

// Typed names save without a redraw (so typing keeps its place). These are the
// saves still on their way, and the counter they refresh.
const pendingNames = new Set();
let unmatchedLabel = null;

function countUnmatched() {
  return config().students.filter((s) => !s.roster_id && !(s.name || "").trim()).length;
}

function showUnmatched(label, n) {
  label.className = n ? "warn-text" : "ok-text";
  label.textContent = n ? t("step3.unmatched", { n }) : t("step3.all_matched");
}

export function renderStep3() {
  const c = config();
  const roster = c.roster || [];
  const typing = roster.length === 0 && app.draft.typeNames;
  unmatchedLabel = roster.length || typing ? h("span", {}) : null;
  if (unmatchedLabel) showUnmatched(unmatchedLabel, countUnmatched());

  return h("main", { class: "page wide" },
    h("h1", {}, t("step3.title")),
    coach(c.name_box?.length ? t("step3.coach") : t("step3.coach_no_name_box")),
    app.draft.columnPick ? columnPicker() : classListCard(roster),
    roster.length || typing ? matcher(c, roster) : null,
    h("div", { class: "actions sticky" },
      unmatchedLabel,
      button(t("step3.start_grading"), async () => {
        await Promise.all(pendingNames);  // the name typed last saves as the button is clicked
        const unmatched = countUnmatched();
        if (unmatched && !(await confirmBox(t("step3.unmatched_title"), t("step3.unmatched_confirm", { n: unmatched }), t("step3.continue_anyway")))) return;
        goTo(4, { next: true });
      }, "primary big")));
}

function classListCard(roster) {
  const fileInput = h("input", { type: "file", accept: ".xlsx,.csv,.txt", hidden: true, onchange: async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    try {
      const data = await upload("/api/roster/upload", file);
      app.draft.columnPick = { preview: data.preview, rows: data.rows, hasHeader: data.has_header,
        columns: data.columns, file: file.name };
      render();
    } catch (err) { toast(err.message, "error"); }
  } });

  if (config().host && roster.some((r) => r.external_id)) {
    return h("section", { class: "card" },
      h("p", {}, "📋 ", t("host.class_list", { host: config().host.name, n: roster.length })));
  }
  if (roster.length) {
    return h("section", { class: "card row spread" },
      h("p", {}, "📋 ", t("step3.list_loaded", { n: roster.length })),
      h("div", { class: "row" },
        button(t("step3.change_list"), () => fileInput.click(), "small"), fileInput,
        button(t("step3.paste"), pasteNames, "small"),
        button(t("step3.remove_list"), async () => {
          if (await confirmBox(t("step3.remove_list"), t("step3.remove_list_confirm"), t("common.delete"), undefined, true)) {
            await act(post("/api/roster/clear"));
          }
        }, "small ghost")));
  }
  return h("section", { class: "card" },
    h("h2", {}, t("step3.list_title")),
    h("p", { class: "muted" }, t("step3.list_hint")),
    h("div", { class: "choice-row three" },
      h("button", { type: "button", class: "choice-card", onclick: () => fileInput.click() },
        h("span", { class: "choice-icon" }, "📊"), h("strong", {}, t("step3.upload")), h("span", { class: "muted" }, t("step3.upload_hint"))),
      h("button", { type: "button", class: "choice-card", onclick: pasteNames },
        h("span", { class: "choice-icon" }, "📋"), h("strong", {}, t("step3.paste")), h("span", { class: "muted" }, t("step3.paste_hint"))),
      h("button", { type: "button", class: `choice-card ${app.draft.typeNames ? "selected" : ""}`,
        onclick: () => { app.draft.typeNames = true; render(); } },
      h("span", { class: "choice-icon" }, "✏️"), h("strong", {}, t("step3.type")), h("span", { class: "muted" }, t("step3.type_hint")))),
    fileInput);
}

function pasteNames() {
  const area = h("textarea", { rows: "12", class: "wide-input", placeholder: t("step3.paste_placeholder") });
  modal({
    title: t("step3.paste"), body: h("div", {}, h("p", { class: "muted" }, t("step3.paste_help")), area),
    actions: [{ label: t("common.cancel") },
      { label: t("step3.use_names"), kind: "primary", onClick: () => act(post("/api/roster/paste", { text: area.value })) }],
  });
}

// --- Choosing the name column(s) after an upload ---------------------------------------------

function columnPicker() {
  const pick = app.draft.columnPick;
  const width = Math.max(...pick.preview.map((r) => r.length));
  const toggle = (i) => {
    const at = pick.columns.indexOf(i);
    if (at >= 0) pick.columns.splice(at, 1);
    else if (pick.columns.length < 2) pick.columns.push(i);
    else pick.columns = [i];
    render();
  };
  const head = h("tr", {}, Array.from({ length: width }, (_, i) => {
    const order = pick.columns.indexOf(i);
    return h("th", {}, h("button", { type: "button", class: `col-pick ${order >= 0 ? "on" : ""}`, onclick: () => toggle(i),
      "aria-pressed": order >= 0 ? "true" : "false" },
    order >= 0 ? h("span", { class: "num-badge" }, String(order + 1)) : null, t("step3.column", { n: i + 1 })));
  }));
  return h("section", { class: "card" },
    h("h2", {}, t("step3.pick_title", { file: pick.file })),
    coach(t("step3.pick_coach")),
    h("label", { class: "check" }, h("input", { type: "checkbox", checked: pick.hasHeader,
      onchange: (e) => { pick.hasHeader = e.target.checked; render(); } }), t("step3.has_header")),
    h("div", { class: "table-scroll" }, h("table", { class: "preview" }, h("thead", {}, head),
      h("tbody", {}, pick.preview.map((row, ri) => h("tr", { class: ri === 0 && pick.hasHeader ? "header-row" : "" },
        Array.from({ length: width }, (_, i) => h("td", { class: pick.columns.includes(i) ? "on" : "" }, row[i] || ""))))))),
    h("p", { class: "muted small" }, t("step3.rows_total", { n: pick.rows })),
    h("div", { class: "actions" },
      button(t("common.cancel"), () => { app.draft.columnPick = null; render(); }, "ghost"),
      button(t("step3.use_names"), async () => {
        if (!pick.columns.length) { toast(t("error.no_name_column"), "error"); return; }
        const data = await act(post("/api/roster/columns", { columns: pick.columns, has_header: pick.hasHeader }), { rerender: false });
        if (data) { app.draft.columnPick = null; render(); }
      }, "primary")));
}

// --- Matcher -----------------------------------------------------------------------------

function matcher(c, roster) {
  const owner = new Map(c.students.filter((s) => s.roster_id).map((s, i) => [s.roster_id, s]));
  const indexOf = new Map(c.students.map((s, i) => [s.id, i + 1]));
  const hasNameBox = !!c.name_box?.length;
  const stamp = c.sliced_at || "";

  return h("section", { class: "matcher" }, h("table", { class: "match-table" },
    h("thead", {}, h("tr", {}, h("th", {}, "#"), h("th", {}, t("step3.handwritten")), h("th", {}, t("step3.student")))),
    h("tbody", {}, c.students.map((s, i) => {
      const img = hasNameBox
        ? h("img", { class: "name-crop", src: `/api/crop/__name__/${s.id}?v=${encodeURIComponent(stamp)}`, alt: t("step3.handwritten"), loading: "lazy" })
        : h("img", { class: "name-thumb", src: `/api/thumb/${s.id}`, alt: "", loading: "lazy" });
      const done = !!(s.roster_id || (s.name || "").trim());
      return h("tr", { class: done ? "matched" : "" },
        h("td", { class: "num-cell" }, String(i + 1)),
        h("td", {}, img, h("div", { class: "muted small" }, s.source)),
        h("td", {}, roster.length ? combo(s, roster, owner, indexOf) : typedName(s)));
    }))));
}

function typedName(student) {
  const input = h("input", { type: "text", id: `name-${student.id}`, value: student.name || "",
    placeholder: t("step3.type_placeholder"), "aria-label": t("step3.student"),
    onchange: (e) => {
      e.target.closest("tr")?.classList.toggle("matched", !!e.target.value.trim());
      const saving = act(post(`/api/students/${student.id}/match`, { name: e.target.value }), { rerender: false })
        .then(() => { if (unmatchedLabel?.isConnected) showUnmatched(unmatchedLabel, countUnmatched()); })
        .finally(() => pendingNames.delete(saving));
      pendingNames.add(saving);
    } });
  return input;
}

function combo(student, roster, owner, indexOf) {
  const current = roster.find((r) => r.id === student.roster_id);
  const input = h("input", { type: "text", id: `match-${student.id}`, autocomplete: "off",
    value: current ? current.name : "", placeholder: t("step3.search_placeholder"),
    "aria-label": t("step3.student"), role: "combobox", "aria-expanded": "false" });
  const list = h("ul", { class: "combo-list", role: "listbox", hidden: true });
  const choose = (rid) => act(post(`/api/students/${student.id}/match`, { roster_id: rid }));

  const fill = () => {
    const q = input.value.normalize("NFKC").toLowerCase().replace(/\s+/g, "");
    const matches = roster.filter((r) => !q || r.name.normalize("NFKC").toLowerCase().replace(/\s+/g, "").includes(q));
    list.replaceChildren(...matches.slice(0, 50).map((r) => {
      const takenBy = owner.get(r.id);
      const taken = takenBy && takenBy.id !== student.id;
      return h("li", { role: "option", class: taken ? "taken" : "",
        onpointerdown: (e) => { e.preventDefault(); choose(r.id); } },
      r.name, taken ? h("span", { class: "muted small" }, " ", t("step3.used_by", { n: indexOf.get(takenBy.id) })) : null);
    }));
    if (!matches.length) list.append(h("li", { class: "muted" }, t("step3.no_match")));
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
  };
  input.addEventListener("focus", () => { input.select(); fill(); });
  input.addEventListener("input", fill);
  input.addEventListener("blur", () => { list.hidden = true; input.setAttribute("aria-expanded", "false");
    input.value = current ? current.name : ""; });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const first = list.querySelector("li[role=option]:not(.taken)") || list.querySelector("li[role=option]");
      if (first) first.dispatchEvent(new PointerEvent("pointerdown"));
    }
  });
  return h("div", { class: "combo" }, input, list,
    current ? h("button", { type: "button", class: "icon-btn", title: t("step3.clear"), "aria-label": t("step3.clear"),
      onclick: () => choose(null) }, "✕") : null);
}
