// Dữ liệu cá nhân của bản web — TẠM cho vòng W2: giữ trong bộ nhớ của Worker, mất khi tải lại trang.
// Cùng lệnh, cùng thứ tự, cùng chuỗi lỗi như app/src-tauri/src/user_db.rs để giao diện chạy y như desktop.
// TODO(W3): thay bằng store.ts (IndexedDB "ecdict-user", nâng cấp phiên bản, nhiều tab, dự phòng bộ nhớ tạm — UC-W05, WS02).

import type { HistoryRow, ListInfo, ListItem } from "../types";
import { splitWhitespace } from "./core";

export const DEFAULT_LIST = "Từ của tôi";

const now = () => Math.floor(Date.now() / 1000);
/** split_whitespace + join(" ") của Rust */
const squash = (s: string) => splitWhitespace(s).join(" ");

interface Hist extends HistoryRow {
  id: number;
}
interface List {
  id: number;
  name: string;
  created: number;
}
type Item = Omit<ListItem, "exists"> & { list_id: number };

export class UserMem {
  private seq = 0;
  private hist: Hist[] = [];
  private listsT: List[] = [];
  private itemsT: Item[] = [];
  private settingsT = new Map<string, string>();

  constructor() {
    this.ensureDefaultList();
  }

  private ensureDefaultList() {
    if (!this.listsT.length) this.listsT.push({ id: ++this.seq, name: DEFAULT_LIST, created: now() });
  }

  // ---------- lịch sử (U29) ----------
  historyAdd(key: string, label: string, kind: string) {
    this.hist = this.hist.filter((h) => h.key !== key);
    this.hist.push({ id: ++this.seq, key, label, kind: kind as HistoryRow["kind"], ts: now() });
    this.hist = this.sortedHist().slice(0, 500); // giữ 500 mục gần nhất
  }
  private sortedHist() {
    return [...this.hist].sort((a, b) => b.ts - a.ts || b.id - a.id);
  }
  history(limit: number): HistoryRow[] {
    return this.sortedHist()
      .slice(0, Math.max(0, limit))
      .map(({ key, label, kind, ts }) => ({ key, label, kind, ts }));
  }
  historyClear() {
    this.hist = [];
  }

  // ---------- danh sách từ (U30) ----------
  lists(): ListInfo[] {
    return [...this.listsT]
      .sort((a, b) => a.created - b.created || a.id - b.id)
      .map((l) => ({ id: l.id, name: l.name, count: this.itemsT.filter((i) => i.list_id === l.id).length }));
  }
  private cleanName(name: string): string {
    const n = squash(name);
    if (!n) throw "Tên danh sách không được để trống";
    if (Array.from(n).length > 80) throw "Tên danh sách tối đa 80 ký tự";
    return n;
  }
  /** So tên không phân biệt hoa/thường theo Unicode ("Từ của tôi" = "từ của TÔI"). */
  private nameTaken(name: string, except: number) {
    const n = name.toLowerCase();
    return this.listsT.some((l) => l.id !== except && l.name.toLowerCase() === n);
  }
  listCreate(name: string): number {
    const n = this.cleanName(name);
    if (this.nameTaken(n, 0)) throw "Đã có danh sách tên này";
    const id = ++this.seq;
    this.listsT.push({ id, name: n, created: now() });
    return id;
  }
  listRename(id: number, name: string) {
    const n = this.cleanName(name);
    if (this.nameTaken(n, id)) throw "Đã có danh sách tên này";
    const l = this.listsT.find((x) => x.id === id);
    if (!l) throw "Danh sách không còn tồn tại";
    l.name = n;
  }
  listDelete(id: number) {
    this.listsT = this.listsT.filter((l) => l.id !== id);
    this.itemsT = this.itemsT.filter((i) => i.list_id !== id);
    this.ensureDefaultList();
  }
  items(listId: number): Omit<ListItem, "exists">[] {
    return this.itemsT
      .filter((i) => i.list_id === listId)
      .sort((a, b) => b.added_at - a.added_at || b.id - a.id)
      .map(({ id, word, pos, sense, label, added_at }) => ({ id, word, pos, sense, label, added_at }));
  }
  itemAdd(listId: number, word: string, pos: string, sense: string, label: string): number {
    if (!this.listsT.some((l) => l.id === listId)) throw "Danh sách không còn tồn tại";
    if (this.itemsT.some((i) => i.list_id === listId && i.word === word && i.pos === pos && i.sense === sense))
      throw "Đã có trong danh sách";
    const id = ++this.seq;
    this.itemsT.push({ id, list_id: listId, word, pos, sense, label, added_at: now() });
    return id;
  }
  itemRemove(id: number) {
    this.itemsT = this.itemsT.filter((i) => i.id !== id);
  }
  savedKeys(listId: number): string[] {
    return this.items(listId).map((i) => `${i.word}|${i.pos}|${i.sense}`);
  }

  // ---------- cài đặt (U28, U32) ----------
  settings(): Record<string, string> {
    return Object.fromEntries(this.settingsT);
  }
  settingSet(key: string, value: string) {
    this.settingsT.set(key, value);
  }
}

/** = lib.rs::default_export_path (chỉ phần tên file; trình duyệt tự chọn thư mục Tải về). */
export function defaultExportName(name: string): string {
  const safe = Array.from(name, (c) => (/[\p{L}\p{N}]/u.test(c) || c === " " || c === "-" || c === "_" ? c : "_"))
    .join("")
    .trim();
  return `EC Dictionary - ${safe || "word list"}.csv`;
}
