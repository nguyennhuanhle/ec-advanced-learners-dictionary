// Tin nhắn giữa giao diện (client.ts) và Web Worker (worker.ts) của bản web.

export type ToWorker =
  /** gửi một lần khi tạo Worker: `base` = URL thư mục dữ liệu (chứa manifest.json), `appVersion` = bản giao diện */
  | { type: "init"; base: string; appVersion: string }
  /** một lệnh như `call(cmd, args)` của bản desktop (lib.rs::Core::call) */
  | { type: "call"; id: number; cmd: string; args: Record<string, unknown> };

export type FromWorker =
  | { type: "result"; id: number; ok: true; value: unknown }
  /** `error` là chuỗi tiếng Việt như lỗi của Rust, để tErr() dịch được */
  | { type: "result"; id: number; ok: false; error: string }
  /** UC-W10: site đã đổi bản dữ liệu trong lúc trang đang mở; "user-closed": tab khác nâng cấp dữ liệu cá nhân */
  | { type: "notice"; code: "stale" | "user-closed"; message: string; version: string };

/** Thông báo lỗi của bản web (tiếng Việt, có bản dịch trong i18n.svelte.ts › RUST_ERRORS). */
export const WEB_ERR = {
  net: "Không tải được dữ liệu (lỗi mạng). Thử lại",
  manifest: "Không tải được từ điển (lỗi mạng hoặc máy chủ)",
  stale: "Đã có bản dữ liệu mới — tải lại trang",
  corrupt: "Dữ liệu của mục này bị lỗi, hãy tải lại trang",
  oldBrowser: "Trình duyệt này quá cũ (thiếu Web Worker hoặc fetch) — hãy dùng trình duyệt mới hơn",
} as const;

/** Khi bản dữ liệu hoặc giao diện không hợp nhau (manifest.schema_web / min_ui). */
export const webSchemaError = (have: string, need: string) =>
  `Dữ liệu web dành cho phiên bản khác của giao diện (định dạng ${have}, giao diện cần ${need}) — hãy tải lại trang`;
