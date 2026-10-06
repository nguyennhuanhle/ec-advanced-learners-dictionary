// Gọi lõi qua một lệnh duy nhất `call(cmd, args)`: bản desktop → Rust (src-tauri/src/lib.rs);
// bản web (VITE_TARGET === "web", chọn lúc build) → Web Worker (web/worker.ts, cùng tên lệnh, cùng hình dạng kết quả).
import { invoke as tauriInvoke } from "@tauri-apps/api/core";
import { inTauri } from "./platform";
import type {
  DbStatus,
  EnEntry,
  HistoryRow,
  ListInfo,
  ListItem,
  LookupView,
  Mode,
  Source,
  Suggestion,
  Via,
  ViEntry,
} from "./types";
import { t } from "./i18n.svelte";

export { inTauri };

async function call<T>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  if (import.meta.env.VITE_TARGET === "web") {
    // nhập động: bản desktop không mang theo Worker và bộ giải từ web
    const { webCall } = await import("./web/client");
    return webCall<T>(cmd, args);
  }
  // Trong cửa sổ Tauri: gọi Rust trực tiếp. Chỉ khi chạy dev trong trình duyệt thường thì đi qua app/dev-bridge.py.
  if (inTauri || !import.meta.env.DEV) return tauriInvoke<T>("call", { cmd, args });
  const r = await fetch("http://127.0.0.1:1430/call", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cmd, args }),
  });
  const v = await r.json();
  if (v && typeof v === "object" && "error" in v && Object.keys(v).length === 1) throw v.error;
  return v as T;
}

export const dbStatus = () => call<DbStatus>("db_status");
export const suggest = (q: string, mode: Mode) => call<Suggestion[]>("suggest", { q, mode });
export const lookup = (q: string, mode: Mode) => call<LookupView>("lookup", { q, mode });
export const getEntry = (word: string) => call<EnEntry | null>("get_entry", { word });
export const getViEntry = (word: string) => call<ViEntry | null>("get_vi_entry", { word });
export const sources = () => call<Source[]>("sources");

export const history = (limit = 200) => call<HistoryRow[]>("history", { limit });
export const historyAdd = (key: string, label: string, kind: "en" | "vi") => call<null>("history_add", { key, label, kind });
export const historyClear = () => call<null>("history_clear");

export const lists = () => call<ListInfo[]>("lists");
export const listCreate = (name: string) => call<number>("list_create", { name });
export const listRename = (id: number, name: string) => call<null>("list_rename", { id, name });
export const listDelete = (id: number) => call<null>("list_delete", { id });
export const listItems = (id: number) => call<ListItem[]>("list_items", { id });
export const savedKeys = (id: number) => call<string[]>("saved_keys", { id });
export const itemAdd = (list_id: number, word: string, pos: string, sense: string, label: string) =>
  call<number>("item_add", { list_id, word, pos, sense, label });
export const itemRemove = (id: number) => call<null>("item_remove", { id });

export const settings = () => call<Record<string, string>>("settings");
export const settingSet = (key: string, value: string) => call<null>("setting_set", { key, value });

export const defaultExportPath = (name: string) => call<string>("default_export_path", { name });
export const exportCsv = (list_id: number, path: string) => call<number>("export_csv", { list_id, path });

export function cleanQuery(q: string): string {
  return q.replace(/[^\p{L}\p{M}\s'\-?*.]/gu, " ").replace(/\s+/g, " ").trim();
}

/** "went is the past tense of go" / "went là quá khứ của go" */
export function describeVia(v: Via): string {
  if (v.relation === "variant") return t("viaVariant", { form: v.form, lemma: v.lemma });
  const tags = new Set(v.tags.split(" "));
  let what = t("formOther");
  if (tags.has("plural")) what = t("formPlural");
  else if (tags.has("past") && tags.has("participle")) what = t("formPastPart");
  else if (tags.has("past")) what = t("formPast");
  else if (tags.has("participle") && tags.has("present")) what = t("formPresPart");
  else if (tags.has("third-person")) what = t("formThird");
  else if (tags.has("comparative")) what = t("formComparative");
  else if (tags.has("superlative")) what = t("formSuperlative");
  return t("viaForm", { form: v.form, what, lemma: v.lemma });
}
