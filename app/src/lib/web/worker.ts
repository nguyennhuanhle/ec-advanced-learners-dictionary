// Web Worker của bản web (PLAN-web mục 5, vòng W2): chạy bộ giải từ core.ts, tải file dữ liệu tĩnh CÙNG NGUỒN
// (manifest.json + v<phiên bản>/…), giữ bộ đệm trong bộ nhớ, thử lại một lần khi lỗi mạng, phát hiện site đã đổi
// bản dữ liệu (UC-W10). Nhận/gửi tin nhắn theo protocol.ts; mỗi lệnh = một lệnh `call(cmd, args)` của bản desktop.
import { DictCore, versionLess, type DataSource, type Manifest } from "./core";
import { WEB_ERR, webSchemaError, type FromWorker, type ToWorker } from "./protocol";
import { UserMem, defaultExportName } from "./user-mem";

const SCHEMA_WEB = 1; // định dạng dữ liệu web mà giao diện này đọc được (export_web.SCHEMA_WEB)
const TIMEOUT_MS = 20_000;
const SHARD_CACHE = 48; // số shard mục từ giữ trong bộ nhớ (mỗi shard ~100–180 KB JSON)
const RECHECK_MS = 30_000; // file tiền tố không có: đọc lại manifest tối đa mỗi 30 giây

const ctx = self as unknown as {
  postMessage(m: FromWorker): void;
  onmessage: ((e: MessageEvent<ToWorker>) => void) | null;
};

let base = ""; // URL thư mục chứa manifest.json (kết thúc bằng "/")
let appVersion = "0.0.0";
let manifest: Manifest | null = null;
let core: DictCore | null = null;
let initError: string | null = null;
let ready: Promise<void> | null = null;
let stale = false;
let lastManifestCheck = 0;
const user = new UserMem();
const shardCache = new Map<string, Promise<unknown>>();

class WebError extends Error {}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** fetch có hết giờ chờ; lỗi mạng / 5xx / 408 / 429 → thử lại một lần (UC-W "Khi lỗi"). 404 trả về cho bên gọi xử lý. */
async function fetchRetry(url: string, init: RequestInit = {}): Promise<Response> {
  for (let attempt = 0; ; attempt++) {
    const ctl = new AbortController();
    const timer = setTimeout(() => ctl.abort(), TIMEOUT_MS);
    try {
      const r = await fetch(url, { ...init, credentials: "same-origin", signal: ctl.signal });
      if (r.status >= 500 || r.status === 408 || r.status === 429) throw new Error(`HTTP ${r.status}`);
      return r;
    } catch {
      if (attempt >= 1) throw new WebError(WEB_ERR.net);
      await sleep(600);
    } finally {
      clearTimeout(timer);
    }
  }
}

/** manifest.json luôn hỏi lại máy chủ (no-cache): là nơi duy nhất biết bản dữ liệu hiện hành. */
async function fetchManifest(): Promise<Manifest> {
  const r = await fetchRetry(base + "manifest.json", { cache: "no-cache" });
  if (!r.ok) throw new WebError(WEB_ERR.manifest);
  try {
    return (await r.json()) as Manifest;
  } catch {
    throw new WebError(WEB_ERR.manifest);
  }
}

function markStale(version: string) {
  if (stale) return;
  stale = true;
  ctx.postMessage({ type: "notice", code: "stale", message: WEB_ERR.stale, version });
}

/** File của bản dữ liệu bị 404: đọc lại manifest. Bản đã đổi → báo "tải lại trang" (UC-W10).
 *  Cùng bản: file tiền tố không có là bình thường (không từ nào bắt đầu như vậy); file khác thiếu = dữ liệu hỏng. */
async function onMissing(kind: "prefix" | "shard" | "other") {
  if (stale) throw new WebError(WEB_ERR.stale);
  if (kind === "prefix" && Date.now() - lastManifestCheck < RECHECK_MS) return;
  lastManifestCheck = Date.now();
  let m: Manifest;
  try {
    m = await fetchManifest();
  } catch {
    throw new WebError(WEB_ERR.net);
  }
  if (m.data_version !== manifest!.data_version) {
    markStale(m.data_version);
    throw new WebError(WEB_ERR.stale);
  }
  if (kind !== "prefix") throw new WebError(WEB_ERR.corrupt);
}

async function getText(path: string, kind: "prefix" | "shard" | "other"): Promise<string | null> {
  const r = await fetchRetry(base + manifest!.base + path);
  if (r.status === 404) {
    await onMissing(kind);
    return null;
  }
  if (!r.ok) throw new WebError(WEB_ERR.net);
  try {
    return await r.text();
  } catch {
    throw new WebError(WEB_ERR.net); // đứt mạng giữa chừng
  }
}

const source: DataSource = {
  async json<T>(path: string, kind: "prefix" | "shard" | "other"): Promise<T | null> {
    // shard mục từ: bộ đệm LRU (core.ts tự giữ file tiền tố và words.txt)
    const cached = kind === "shard" ? shardCache.get(path) : undefined;
    if (cached) {
      shardCache.delete(path);
      shardCache.set(path, cached);
      return cached as Promise<T | null>;
    }
    const p = getText(path, kind).then((t) => {
      if (t === null) return null;
      try {
        return JSON.parse(t) as T;
      } catch {
        throw new WebError(WEB_ERR.corrupt);
      }
    });
    if (kind === "shard") {
      shardCache.set(path, p);
      p.catch(() => shardCache.delete(path));
      while (shardCache.size > SHARD_CACHE) shardCache.delete(shardCache.keys().next().value as string);
    }
    return p;
  },
  text(path: string) {
    return getText(path, "other");
  },
};

/** UC-WS01: đọc manifest, kiểm định dạng/phiên bản trước khi cho tra. Lỗi thì giữ thông báo cho db_status. */
let initRunning = false;
async function init(): Promise<void> {
  initRunning = true;
  try {
    const m = await fetchManifest();
    if (m.schema_web !== SCHEMA_WEB) throw new WebError(webSchemaError(String(m.schema_web), String(SCHEMA_WEB)));
    if (m.min_ui && versionLess(appVersion, m.min_ui)) throw new WebError(webSchemaError(`≥ ${m.min_ui}`, appVersion));
    manifest = m;
    core = new DictCore(m, source);
    initError = null;
  } catch (e) {
    initError = e instanceof WebError ? e.message : WEB_ERR.manifest;
  } finally {
    initRunning = false;
  }
}

function dict(): DictCore {
  if (!core) throw new WebError(initError ?? WEB_ERR.manifest);
  return core;
}

const str = (a: Record<string, unknown>, k: string) => (typeof a[k] === "string" ? (a[k] as string) : "");
const int = (a: Record<string, unknown>, k: string) => (typeof a[k] === "number" ? Math.trunc(a[k] as number) : 0);

async function handle(cmd: string, a: Record<string, unknown>): Promise<unknown> {
  // mở lại sau lỗi lúc đầu (mất mạng khi vừa mở trang): lần gọi db_status sau sẽ thử đọc manifest lần nữa
  if (!ready || (cmd === "db_status" && !core && !initRunning)) ready = init();
  await ready;
  switch (cmd) {
    case "db_status":
      return {
        ok: !!core,
        app_version: appVersion,
        error: initError,
        path: base + "manifest.json",
        meta: manifest?.meta ?? (manifest ? { data_version: manifest.data_version, build_date: manifest.build_date ?? "" } : {}),
        counts: manifest?.db_counts ?? {},
        user_ok: true,
        user_error: null,
        // TODO(W3): IndexedDB; W2 chỉ giữ trong bộ nhớ của trang
        user_path: "bộ nhớ tạm của trang (W2 — mất khi tải lại)",
        user_notice: null,
      };
    case "suggest":
    case "lookup":
    case "get_entry":
    case "get_vi_entry":
    case "sources": {
      const v = await dict().call(cmd, a);
      dict().trimCache();
      return v;
    }

    case "history":
      return user.history(typeof a.limit === "number" ? a.limit : 200);
    case "history_add":
      user.historyAdd(str(a, "key"), str(a, "label"), str(a, "kind"));
      return null;
    case "history_clear":
      user.historyClear();
      return null;
    case "lists":
      return user.lists();
    case "list_create":
      return user.listCreate(str(a, "name"));
    case "list_rename":
      user.listRename(int(a, "id"), str(a, "name"));
      return null;
    case "list_delete":
      user.listDelete(int(a, "id"));
      return null;
    case "list_items": {
      // + cờ "còn có trong dữ liệu hiện tại" như lib.rs::items_checked
      const items = user.items(int(a, "id"));
      return Promise.all(items.map(async (i) => ({ ...i, exists: core ? await core.exists(i.word).catch(() => true) : false })));
    }
    case "saved_keys":
      return user.savedKeys(int(a, "id"));
    case "item_add":
      return user.itemAdd(int(a, "list_id"), str(a, "word"), str(a, "pos"), str(a, "sense"), str(a, "label"));
    case "item_remove":
      user.itemRemove(int(a, "id"));
      return null;
    case "settings":
      return user.settings();
    case "setting_set":
      user.settingSet(str(a, "key"), str(a, "value"));
      return null;
    case "default_export_path":
      return defaultExportName(str(a, "name"));
    case "export_csv":
      throw new WebError(WEB_ERR.csv); // TODO(W3): csv.ts → Blob + <a download>
    default:
      throw new WebError(`Lệnh không tồn tại: ${cmd}`);
  }
}

ctx.onmessage = (e: MessageEvent<ToWorker>) => {
  const m = e.data;
  if (m.type === "init") {
    base = m.base.endsWith("/") ? m.base : m.base + "/";
    appVersion = m.appVersion || appVersion;
    ready = init();
    return;
  }
  if (m.type !== "call") return;
  handle(m.cmd, m.args ?? {}).then(
    (value) => ctx.postMessage({ type: "result", id: m.id, ok: true, value: value ?? null }),
    (err) =>
      ctx.postMessage({
        type: "result",
        id: m.id,
        ok: false,
        // lỗi của user-mem là chuỗi (như Err(String) của Rust); lỗi khác lấy message
        error: typeof err === "string" ? err : err instanceof Error ? err.message : String(err),
      }),
  );
};
