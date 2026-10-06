// Dữ liệu cá nhân của bản web lưu trong IndexedDB của trình duyệt (vòng W3: UC-W05, W08, WS02).
// Chạy trong Web Worker. Cùng lệnh, cùng thứ tự, cùng chuỗi lỗi như app/src-tauri/src/user_db.rs.
//
// Mỗi lệnh là MỘT giao dịch IndexedDB và luôn đọc lại từ đĩa (không giữ bản sao trong bộ nhớ), nên hai tab mở cùng lúc
// không ghi đè mất thay đổi của nhau: giao dịch đọc-ghi được trình duyệt xếp hàng tuần tự (UC-W "hai tab").
// Nâng cấp cấu trúc: thêm bước vào UPGRADES (không sửa bước cũ); nâng cấp lỗi → IndexedDB tự huỷ, dữ liệu cũ còn nguyên (WS02).

import type { HistoryRow, ListInfo } from "../types";
import { DEFAULT_LIST, USER_ERR, cleanName, now, sameName, type StoredItem, type UserApi } from "./user-common";

export const DB_NAME = "ecdict-user";
const OPEN_TIMEOUT_MS = 8000;

/** UPGRADES[i] đưa cơ sở dữ liệu từ phiên bản i lên i+1. */
const UPGRADES: ((db: IDBDatabase, tx: IDBTransaction) => void)[] = [
  // v1
  (db) => {
    const h = db.createObjectStore("history", { keyPath: "key" });
    h.createIndex("order", ["ts", "n"]);
    db.createObjectStore("lists", { keyPath: "id", autoIncrement: true });
    const it = db.createObjectStore("items", { keyPath: "id", autoIncrement: true });
    it.createIndex("list", "list_id");
    it.createIndex("uniq", ["list_id", "word", "pos", "sense"], { unique: true });
    db.createObjectStore("settings", { keyPath: "key" });
    db.createObjectStore("meta", { keyPath: "k" });
  },
];
const DB_VERSION = UPGRADES.length;

interface HistRec extends HistoryRow {
  n: number;
}
interface ListRec {
  id: number;
  name: string;
  created: number;
}
type ItemRec = StoredItem & { list_id: number };

const req = <T>(r: IDBRequest<T>) =>
  new Promise<T>((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });

/** Lỗi của trình duyệt → chuỗi lỗi cho người dùng. */
function mapError(e: unknown): unknown {
  const name = (e as DOMException | null)?.name;
  if (name === "QuotaExceededError") return USER_ERR.quota;
  if (name === "InvalidStateError" || name === "TransactionInactiveError") return USER_ERR.otherTab;
  return e;
}

export class UserStore implements UserApi {
  readonly kind = "indexeddb" as const;
  private closed = false;

  private constructor(private db: IDBDatabase, onClosed: () => void) {
    // tab khác mở bản giao diện mới hơn và cần nâng cấp: đóng lại để không chặn nó, báo người dùng tải lại
    db.onversionchange = () => {
      db.close();
      this.closed = true;
      onClosed();
    };
  }

  /** Mở (tạo nếu chưa có) và nâng cấp. Lỗi / bị chặn quá lâu → reject, bên gọi chuyển sang bộ nhớ tạm. */
  static open(onClosed: () => void): Promise<UserStore> {
    return new Promise((resolve, reject) => {
      if (typeof indexedDB === "undefined") return reject(new Error("no indexedDB"));
      let r: IDBOpenDBRequest;
      try {
        r = indexedDB.open(DB_NAME, DB_VERSION);
      } catch (e) {
        return reject(e);
      }
      // onblocked: một tab cũ đang giữ phiên bản trước và chưa đóng → chờ, quá giờ thì dùng bộ nhớ tạm
      const timer = setTimeout(() => reject(new Error("blocked")), OPEN_TIMEOUT_MS);
      r.onupgradeneeded = (ev) => {
        const db = r.result;
        const tx = r.transaction!;
        for (let v = ev.oldVersion; v < DB_VERSION; v++) UPGRADES[v](db, tx);
      };
      r.onsuccess = async () => {
        clearTimeout(timer);
        const s = new UserStore(r.result, onClosed);
        try {
          await s.ensureDefaultList();
          resolve(s);
        } catch (e) {
          reject(e);
        }
      };
      r.onerror = () => {
        clearTimeout(timer);
        reject(r.error);
      };
    });
  }

  /** Một giao dịch: chạy fn, đợi giao dịch ghi xong hẳn (lỗi hết chỗ chỉ hiện lúc này). */
  private async run<T>(stores: string[], mode: IDBTransactionMode, fn: (tx: IDBTransaction) => Promise<T>): Promise<T> {
    if (this.closed) throw USER_ERR.otherTab;
    let tx: IDBTransaction;
    try {
      tx = this.db.transaction(stores, mode);
    } catch (e) {
      throw mapError(e);
    }
    const done = new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onabort = () => reject(tx.error);
    });
    let out: T;
    try {
      out = await fn(tx);
    } catch (e) {
      done.catch(() => {});
      try {
        tx.abort();
      } catch {
        /* giao dịch đã tự huỷ */
      }
      throw mapError(e);
    }
    try {
      await done;
    } catch (e) {
      throw mapError(e);
    }
    return out;
  }

  private async ensureDefaultList() {
    await this.run(["lists"], "readwrite", async (tx) => {
      const s = tx.objectStore("lists");
      if ((await req(s.count())) === 0) await req(s.add({ name: DEFAULT_LIST, created: now() }));
    });
  }

  // ---------- lịch sử (U29) ----------
  historyAdd(key: string, label: string, kind: string) {
    return this.historyPut({ key, label, kind: kind as HistoryRow["kind"], ts: now() });
  }
  historyPut(row: HistoryRow) {
    return this.run(["history", "meta"], "readwrite", async (tx) => {
      const meta = tx.objectStore("meta");
      const n = (((await req(meta.get("hseq"))) as { v: number } | undefined)?.v ?? 0) + 1;
      await req(meta.put({ k: "hseq", v: n }));
      const h = tx.objectStore("history");
      await req(h.put({ key: row.key, label: row.label, kind: row.kind, ts: row.ts, n } satisfies HistRec));
      // giữ 500 mục gần nhất: xoá các mục cũ nhất (thứ tự ts, n tăng dần)
      let extra = (await req(h.count())) - 500;
      if (extra > 0) {
        await new Promise<void>((resolve, reject) => {
          const c = h.index("order").openCursor();
          c.onerror = () => reject(c.error);
          c.onsuccess = () => {
            const cur = c.result;
            if (!cur || extra <= 0) return resolve();
            cur.delete();
            extra--;
            cur.continue();
          };
        });
      }
    });
  }
  history(limit: number) {
    return this.run(["history"], "readonly", async (tx) => {
      const all = (await req(tx.objectStore("history").getAll())) as HistRec[];
      return all
        .sort((a, b) => b.ts - a.ts || b.n - a.n)
        .slice(0, Math.max(0, limit))
        .map(({ key, label, kind, ts }) => ({ key, label, kind, ts }));
    });
  }
  historyClear() {
    return this.run(["history"], "readwrite", async (tx) => {
      await req(tx.objectStore("history").clear());
    });
  }

  // ---------- danh sách từ (U30) ----------
  private static sortLists(ls: ListRec[]) {
    return ls.sort((a, b) => a.created - b.created || a.id - b.id);
  }
  lists() {
    return this.run(["lists", "items"], "readonly", async (tx) => {
      const ls = UserStore.sortLists((await req(tx.objectStore("lists").getAll())) as ListRec[]);
      const byList = tx.objectStore("items").index("list");
      const out: ListInfo[] = [];
      for (const l of ls) out.push({ id: l.id, name: l.name, count: await req(byList.count(l.id)) });
      return out;
    });
  }
  listCreate(name: string) {
    const n = cleanName(name);
    return this.run(["lists"], "readwrite", async (tx) => {
      const s = tx.objectStore("lists");
      const all = (await req(s.getAll())) as ListRec[];
      if (all.some((l) => sameName(l.name, n))) throw USER_ERR.nameTaken;
      return (await req(s.add({ name: n, created: now() }))) as number;
    });
  }
  listRename(id: number, name: string) {
    const n = cleanName(name);
    return this.run(["lists"], "readwrite", async (tx) => {
      const s = tx.objectStore("lists");
      const all = (await req(s.getAll())) as ListRec[];
      if (all.some((l) => l.id !== id && sameName(l.name, n))) throw USER_ERR.nameTaken;
      const l = all.find((x) => x.id === id);
      if (!l) throw USER_ERR.noList;
      await req(s.put({ ...l, name: n }));
    });
  }
  listDelete(id: number) {
    return this.run(["lists", "items"], "readwrite", async (tx) => {
      const ls = tx.objectStore("lists");
      await req(ls.delete(id));
      const items = tx.objectStore("items");
      const keys = await req(items.index("list").getAllKeys(id));
      for (const k of keys) await req(items.delete(k));
      if ((await req(ls.count())) === 0) await req(ls.add({ name: DEFAULT_LIST, created: now() }));
    });
  }
  items(listId: number) {
    return this.run(["items"], "readonly", async (tx) => {
      const all = (await req(tx.objectStore("items").index("list").getAll(listId))) as ItemRec[];
      return all
        .sort((a, b) => b.added_at - a.added_at || b.id - a.id)
        .map(({ id, word, pos, sense, label, added_at }) => ({ id, word, pos, sense, label, added_at }));
    });
  }
  itemAdd(listId: number, word: string, pos: string, sense: string, label: string, addedAt?: number) {
    return this.run(["lists", "items"], "readwrite", async (tx) => {
      if (!(await req(tx.objectStore("lists").get(listId)))) throw USER_ERR.noList;
      try {
        return (await req(
          tx.objectStore("items").add({ list_id: listId, word, pos, sense, label, added_at: addedAt ?? now() }),
        )) as number;
      } catch (e) {
        if ((e as DOMException | null)?.name === "ConstraintError") throw USER_ERR.dupItem;
        throw e;
      }
    });
  }
  itemRemove(id: number) {
    return this.run(["items"], "readwrite", async (tx) => {
      await req(tx.objectStore("items").delete(id));
    });
  }
  async savedKeys(listId: number) {
    return (await this.items(listId)).map((i) => `${i.word}|${i.pos}|${i.sense}`);
  }

  // ---------- cài đặt (U28, U32) ----------
  settings() {
    return this.run(["settings"], "readonly", async (tx) => {
      const all = (await req(tx.objectStore("settings").getAll())) as { key: string; value: string }[];
      return Object.fromEntries(all.map((r) => [r.key, r.value]));
    });
  }
  settingSet(key: string, value: string) {
    return this.run(["settings"], "readwrite", async (tx) => {
      await req(tx.objectStore("settings").put({ key, value }));
    });
  }

  /** UC-W08: xoá toàn bộ dữ liệu cá nhân của từ điển trong trình duyệt, còn lại danh sách mặc định trống. */
  clearAll() {
    return this.run(["history", "lists", "items", "settings", "meta"], "readwrite", async (tx) => {
      for (const s of ["history", "lists", "items", "settings", "meta"]) await req(tx.objectStore(s).clear());
      await req(tx.objectStore("lists").add({ name: DEFAULT_LIST, created: now() }));
    });
  }
}
