// English / Japanese text. Strings come from the server (i18n/*.json) so the
// browser and the engine always use the same wording.
import { get } from "./api.js";

let strings = {};
export let language = "en";

export async function loadStrings() {
  const data = await get("/api/i18n");
  strings = data.strings;
  language = data.language;
  document.documentElement.lang = language;
  document.title = t("app.title");
}

export function t(key, params = {}) {
  const text = strings[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (m, k) => (k in params ? String(params[k]) : m));
}
