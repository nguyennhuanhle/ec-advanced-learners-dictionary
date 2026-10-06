// Phía giao diện của bản web: gửi lệnh `call(cmd, args)` vào Web Worker (worker.ts) và nhận kết quả.
// Chỉ được nạp khi build web (api.ts nhập động trong nhánh VITE_TARGET === "web").
import type { DbStatus } from "../types";
import { WEB_ERR, type FromWorker, type ToWorker } from "./protocol";

/** Thư mục dữ liệu trên site (chứa manifest.json và v<phiên bản>/), cùng nguồn với trang. */
const DATA_BASE: string = import.meta.env.VITE_DATA_BASE || "/data/";
const APP_VERSION: string = import.meta.env.VITE_APP_VERSION || "0.0.0";

/** Sự kiện trên window khi Worker báo điều cần hiện cho người dùng (UC-W10: đã có bản dữ liệu mới). */
export const NOTICE_EVENT = "ecald-notice";
export interface WebNotice {
  code: "stale";
  message: string;
}

type Pending = { resolve: (v: unknown) => void; reject: (e: unknown) => void; cmd: string };

let worker: Worker | null = null;
let seq = 0;
const pending = new Map<number, Pending>();
/** id của lệnh suggest / lookup mới nhất: kết quả về muộn của lệnh cũ không được ghi đè kết quả mới (UC-W "Khi lỗi") */
const latest: Record<string, number> = { suggest: 0, lookup: 0 };
/** giá trị "không làm gì" cho kết quả đã lỗi thời: gợi ý rỗng; tra rỗng (giao diện bỏ qua kind "empty") */
const SUPERSEDED: Record<string, unknown> = { suggest: [], lookup: { kind: "empty" } };

function failAll(msg: string) {
  for (const [, p] of pending) p.reject(msg);
  pending.clear();
}

function getWorker(): Worker {
  if (worker) return worker;
  worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module", name: "ecald-dict" });
  worker.onmessage = (e: MessageEvent<FromWorker>) => {
    const m = e.data;
    if (m.type === "notice") {
      window.dispatchEvent(new CustomEvent<WebNotice>(NOTICE_EVENT, { detail: { code: m.code, message: m.message } }));
      return;
    }
    const p = pending.get(m.id);
    if (!p) return;
    pending.delete(m.id);
    if (p.cmd in latest && latest[p.cmd] !== m.id) return p.resolve(SUPERSEDED[p.cmd]);
    if (m.ok) p.resolve(m.value);
    else p.reject(m.error);
  };
  worker.onerror = () => {
    // Worker không chạy được (trình duyệt quá cũ, CSP chặn…): báo lỗi cho mọi lệnh đang chờ, lần sau tạo lại
    worker = null;
    failAll(WEB_ERR.oldBrowser);
  };
  const init: ToWorker = { type: "init", base: new URL(DATA_BASE, location.href).href, appVersion: APP_VERSION };
  worker.postMessage(init);
  return worker;
}

export function webCall<T>(cmd: string, args: Record<string, unknown> = {}): Promise<T> {
  if (typeof Worker === "undefined" || typeof fetch === "undefined") {
    if (cmd === "db_status") {
      // UC-WS01: trình duyệt thiếu tính năng → màn hình báo lỗi thay vì trang trắng
      const st: DbStatus = {
        ok: false, app_version: APP_VERSION, error: WEB_ERR.oldBrowser, path: "", meta: {}, counts: {},
        user_ok: false, user_error: WEB_ERR.oldBrowser, user_path: null, user_notice: null,
      };
      return Promise.resolve(st as T);
    }
    return Promise.reject(WEB_ERR.oldBrowser);
  }
  const w = getWorker();
  const id = ++seq;
  if (cmd in latest) latest[cmd] = id;
  return new Promise<T>((resolve, reject) => {
    pending.set(id, { resolve: resolve as (v: unknown) => void, reject, cmd });
    const msg: ToWorker = { type: "call", id, cmd, args };
    w.postMessage(msg);
  });
}
