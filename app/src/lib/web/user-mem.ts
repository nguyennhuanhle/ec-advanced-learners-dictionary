// Dữ liệu cá nhân của bản web giữ TRONG BỘ NHỚ của Worker — chỉ dùng khi trình duyệt không cho lưu IndexedDB
// (chế độ ẩn danh chặn, chính sách trình duyệt…): từ điển vẫn tra được, lịch sử/danh sách mất khi đóng trang (UC-W "Khi lỗi").
// Cùng lệnh, cùng thứ tự, cùng chuỗi lỗi như app/src-tauri/src/user_db.rs và store.ts.

import type { HistoryRow, ListInfo } from "../types";
import { DEFAULT_LIST, USER_ERR, cleanName, now, sameName, type StoredItem, type UserApi } from "./user-common";

interface Hist extends HistoryRow {
  id: number;
}
interface List {
  id: number;
  name: string;
  created: number;
}
type Item = StoredItem & { list_id: number };

export class UserMem implements UserApi {
  readonly kind = "memory" as const;
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
    this.historyPut({ key, label, kind: kind as HistoryRow["kind"], ts: now() });
  }
  historyPut(row: HistoryRow) {
    this.hist = this.hist.filter((h) => h.key !== row.key);
    this.hist.push({ ...row, id: ++this.seq });
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
  private nameTaken(name: string, except: number) {
    return this.listsT.some((l) => l.id !== except && sameName(l.name, name));
  }
  listCreate(name: string): number {
    const n = cleanName(name);
    if (this.nameTaken(n, 0)) throw USER_ERR.nameTaken;
    const id = ++this.seq;
    this.listsT.push({ id, name: n, created: now() });
    return id;
  }
  listRename(id: number, name: string) {
    const n = cleanName(name);
    if (this.nameTaken(n, id)) throw USER_ERR.nameTaken;
    const l = this.listsT.find((x) => x.id === id);
    if (!l) throw USER_ERR.noList;
    l.name = n;
  }
  listDelete(id: number) {
    this.listsT = this.listsT.filter((l) => l.id !== id);
    this.itemsT = this.itemsT.filter((i) => i.list_id !== id);
    this.ensureDefaultList();
  }
  items(listId: number): StoredItem[] {
    return this.itemsT
      .filter((i) => i.list_id === listId)
      .sort((a, b) => b.added_at - a.added_at || b.id - a.id)
      .map(({ id, word, pos, sense, label, added_at }) => ({ id, word, pos, sense, label, added_at }));
  }
  itemAdd(listId: number, word: string, pos: string, sense: string, label: string, addedAt?: number): number {
    if (!this.listsT.some((l) => l.id === listId)) throw USER_ERR.noList;
    if (this.itemsT.some((i) => i.list_id === listId && i.word === word && i.pos === pos && i.sense === sense))
      throw USER_ERR.dupItem;
    const id = ++this.seq;
    this.itemsT.push({ id, list_id: listId, word, pos, sense, label, added_at: addedAt ?? now() });
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

  clearAll() {
    this.hist = [];
    this.listsT = [];
    this.itemsT = [];
    this.settingsT.clear();
    this.ensureDefaultList();
  }
}
