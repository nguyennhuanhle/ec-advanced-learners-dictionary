// Phần dùng chung của dữ liệu cá nhân bản web (vòng W3): quy tắc như app/src-tauri/src/user_db.rs
// (tên danh sách, chuỗi lỗi), giao diện chung cho nơi lưu IndexedDB (store.ts) và bộ nhớ tạm (user-mem.ts),
// định dạng file sao lưu (UC-W07).

import type { HistoryRow, ListInfo, ListItem } from "../types";
import { splitWhitespace } from "./core";

export const DEFAULT_LIST = "Từ của tôi";

/** Chuỗi lỗi (tiếng Việt như lỗi của Rust; bản dịch ở i18n.svelte.ts › RUST_ERRORS). */
export const USER_ERR = {
  emptyName: "Tên danh sách không được để trống",
  longName: "Tên danh sách tối đa 80 ký tự",
  nameTaken: "Đã có danh sách tên này",
  noList: "Danh sách không còn tồn tại",
  dupItem: "Đã có trong danh sách",
  emptyList: "Danh sách đang trống, chưa có gì để xuất",
  noStorage: "Trình duyệt này không cho lưu — lịch sử và danh sách sẽ mất khi đóng trang",
  quota: "Trình duyệt đã hết chỗ lưu dữ liệu cho trang này — hãy xoá bớt lịch sử hoặc sao lưu rồi xoá dữ liệu",
  otherTab: "Từ điển vừa được cập nhật ở một tab khác — hãy tải lại trang",
  backupFormat: "File này không phải file sao lưu của từ điển",
  backupNewer: "File sao lưu này của phiên bản từ điển mới hơn — hãy tải lại trang rồi thử lại",
  backupBroken: "File sao lưu bị hỏng hoặc thiếu dữ liệu",
} as const;

export const now = () => Math.floor(Date.now() / 1000);
/** split_whitespace + join(" ") của Rust */
export const squash = (s: string) => splitWhitespace(s).join(" ");

export function cleanName(name: string): string {
  const n = squash(name);
  if (!n) throw USER_ERR.emptyName;
  if (Array.from(n).length > 80) throw USER_ERR.longName;
  return n;
}

/** So tên không phân biệt hoa/thường theo Unicode ("Từ của tôi" = "từ của TÔI"), như user_db.rs::name_taken. */
export const sameName = (a: string, b: string) => a.toLowerCase() === b.toLowerCase();

export type StoredItem = Omit<ListItem, "exists">;
type Maybe<T> = T | Promise<T>;

/** Các lệnh dữ liệu cá nhân — cùng tên, cùng hình dạng như user_db.rs. */
export interface UserApi {
  readonly kind: "indexeddb" | "memory";
  historyAdd(key: string, label: string, kind: string): Maybe<void>;
  /** ghi một dòng lịch sử giữ nguyên thời điểm (khôi phục sao lưu) */
  historyPut(row: HistoryRow): Maybe<void>;
  history(limit: number): Maybe<HistoryRow[]>;
  historyClear(): Maybe<void>;
  lists(): Maybe<ListInfo[]>;
  listCreate(name: string): Maybe<number>;
  listRename(id: number, name: string): Maybe<void>;
  listDelete(id: number): Maybe<void>;
  items(listId: number): Maybe<StoredItem[]>;
  itemAdd(listId: number, word: string, pos: string, sense: string, label: string, addedAt?: number): Maybe<number>;
  itemRemove(id: number): Maybe<void>;
  savedKeys(listId: number): Maybe<string[]>;
  settings(): Maybe<Record<string, string>>;
  settingSet(key: string, value: string): Maybe<void>;
  /** UC-W08: xoá toàn bộ, còn lại danh sách mặc định trống */
  clearAll(): Maybe<void>;
}

/** = lib.rs::default_export_path (chỉ phần tên file; trình duyệt tự chọn thư mục Tải về). */
export function defaultExportName(name: string): string {
  const safe = Array.from(name, (c) => (/[\p{L}\p{N}]/u.test(c) || c === " " || c === "-" || c === "_" ? c : "_"))
    .join("")
    .trim();
  return `EC Dictionary - ${safe || "word list"}.csv`;
}

// ---------- sao lưu / khôi phục (UC-W07) ----------

export const BACKUP_FORMAT = "ecald-backup";
export const BACKUP_VERSION = 1;

export interface Backup {
  format: typeof BACKUP_FORMAT;
  version: number;
  exported_at: number;
  app_version: string;
  /** theo thứ tự hiển thị (cũ trước) */
  lists: { name: string; items: Omit<StoredItem, "id">[] }[];
  history: HistoryRow[];
  settings: Record<string, string>;
}

export async function makeBackup(u: UserApi, appVersion: string): Promise<Backup> {
  const lists = [];
  for (const l of await u.lists()) {
    const items = (await u.items(l.id)).map(({ word, pos, sense, label, added_at }) => ({ word, pos, sense, label, added_at }));
    lists.push({ name: l.name, items });
  }
  return {
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exported_at: now(),
    app_version: appVersion,
    lists,
    history: await u.history(500),
    settings: await u.settings(),
  };
}

const isStr = (x: unknown): x is string => typeof x === "string";
const isNum = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** Kiểm toàn bộ file trước khi ghi bất cứ gì: sai thì từ chối, dữ liệu hiện có giữ nguyên. */
export function parseBackup(text: string): Backup {
  let d: unknown;
  try {
    d = JSON.parse(text);
  } catch {
    throw USER_ERR.backupFormat;
  }
  const b = d as Partial<Backup>;
  if (!b || typeof b !== "object" || b.format !== BACKUP_FORMAT) throw USER_ERR.backupFormat;
  if (!isNum(b.version) || b.version < 1) throw USER_ERR.backupBroken;
  if (b.version > BACKUP_VERSION) throw USER_ERR.backupNewer;
  if (!Array.isArray(b.lists) || !Array.isArray(b.history) || !b.settings || typeof b.settings !== "object")
    throw USER_ERR.backupBroken;
  for (const l of b.lists) {
    if (!l || !isStr(l.name) || !Array.isArray(l.items)) throw USER_ERR.backupBroken;
    cleanName(l.name); // tên rỗng / quá dài → lỗi rõ ràng
    for (const i of l.items)
      if (!i || !isStr(i.word) || !isStr(i.pos) || !isStr(i.sense) || !isStr(i.label) || !isNum(i.added_at))
        throw USER_ERR.backupBroken;
  }
  for (const h of b.history)
    if (!h || !isStr(h.key) || !isStr(h.label) || (h.kind !== "en" && h.kind !== "vi") || !isNum(h.ts))
      throw USER_ERR.backupBroken;
  for (const [k, v] of Object.entries(b.settings)) if (!isStr(k) || !isStr(v)) throw USER_ERR.backupBroken;
  return b as Backup;
}

/** Gộp sao lưu vào dữ liệu hiện có: danh sách trùng tên (không phân biệt hoa/thường) được gộp, mục trùng bỏ qua;
 *  lịch sử giữ thời điểm của bản mới hơn; cài đặt lấy theo file sao lưu. */
export async function restoreBackup(u: UserApi, b: Backup): Promise<{ lists: number; items: number; history: number }> {
  let nLists = 0;
  let nItems = 0;
  for (const l of b.lists) {
    const name = cleanName(l.name);
    const have = (await u.lists()).find((x) => sameName(x.name, name));
    const id = have ? have.id : await u.listCreate(name);
    if (!have) nLists++;
    // mục cũ nhất trước → thứ tự "mới thêm ở trên" giữ như lúc sao lưu
    for (const i of [...l.items].sort((x, y) => x.added_at - y.added_at)) {
      try {
        await u.itemAdd(id, i.word, i.pos, i.sense, i.label, i.added_at);
        nItems++;
      } catch (e) {
        if (e !== USER_ERR.dupItem) throw e;
      }
    }
  }
  const current = new Map((await u.history(500)).map((h) => [h.key, h.ts]));
  let nHist = 0;
  for (const h of [...b.history].sort((x, y) => x.ts - y.ts)) {
    if ((current.get(h.key) ?? -1) >= h.ts) continue;
    await u.historyPut(h);
    nHist++;
  }
  for (const [k, v] of Object.entries(b.settings)) if (k !== "active_list") await u.settingSet(k, v);
  return { lists: nLists, items: nItems, history: nHist };
}
