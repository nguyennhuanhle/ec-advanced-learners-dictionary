// Những gì khác nhau giữa bản desktop (Tauri) và bản web, chọn LÚC BUILD qua import.meta.env.VITE_TARGET
// (vite.config.js đặt "web" khi `npm run build:web`, "desktop" khi build thường).
// Plugin Tauri chỉ được nhập động trong nhánh desktop, nên bản web không mang code @tauri-apps/plugin-*.

/** Bản build này chạy bằng code web (Worker + IndexedDB): bản web (dictionary.edtechcorner.com) VÀ app Android (Capacitor). */
export const IS_WEB = import.meta.env.VITE_TARGET === "web";

/** App Android (Capacitor, PLAN-android). Luôn kèm IS_WEB; dùng cho phần khác bản web (không GA, giọng đọc gốc, nút Back…). */
export const IS_ANDROID = import.meta.env.VITE_ANDROID === true;

/** App iOS (Capacitor, PLAN-ios). Luôn kèm IS_WEB. */
export const IS_IOS = import.meta.env.VITE_IOS === true;

/** App cài từ kho (Android hoặc iOS): không GA, dữ liệu trong app, thanh điều hướng dưới, chia sẻ bằng bảng chia sẻ của máy… */
export const IS_NATIVE = IS_ANDROID || IS_IOS;

/** Đang chạy trong cửa sổ Tauri (desktop). Bản web luôn false. */
export const inTauri =
  import.meta.env.VITE_TARGET !== "web" && typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Chọn nơi lưu file CSV. Desktop trong Tauri: hộp thoại Lưu của hệ điều hành; còn lại: trả về đường dẫn gợi ý.
 *  Bản web không dùng hàm này: tải file qua trình duyệt (downloadText). */
export async function pickSavePath(suggested: string): Promise<string | null> {
  if (import.meta.env.VITE_TARGET !== "web" && inTauri) {
    const { save } = await import("@tauri-apps/plugin-dialog");
    return save({ defaultPath: suggested, filters: [{ name: "CSV (Excel, Anki, Quizlet)", extensions: ["csv"] }] });
  }
  return suggested;
}

/** Phần gốc của app (lib/android.ts hoặc lib/ios.ts — cùng bộ hàm). Chỉ gọi khi IS_NATIVE; nhánh này bị loại khỏi
 *  bản web/desktop lúc build, và bản Android không mang ios.ts (ngược lại cũng vậy). */
export type NativeModule = typeof import("./android");
export function loadNative(): Promise<NativeModule> {
  if (import.meta.env.VITE_ANDROID) return import("./android");
  if (import.meta.env.VITE_IOS) return import("./ios");
  return Promise.reject(new Error("not a native app"));
}

/** Mở liên kết ngoài: desktop mở bằng trình duyệt mặc định (cửa sổ app không tự điều hướng); web mở tab mới;
 *  Android mở bằng trình duyệt của máy (app không có quyền INTERNET). */
export async function openExternalUrl(url: string): Promise<void> {
  if (import.meta.env.VITE_ANDROID || import.meta.env.VITE_IOS) {
    await (await loadNative()).openExternal(url);
    return;
  }
  if (import.meta.env.VITE_TARGET !== "web" && inTauri) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** Ghi clipboard có định dạng bằng plugin của Tauri (giữ HTML khi dán vào Word). Trả false khi không phải desktop.
 *  Android: clipboard của hệ thống (chữ thường — WebView không chắc cho Clipboard API). */
export async function writeHtmlNative(html: string, text: string): Promise<boolean> {
  if (import.meta.env.VITE_ANDROID || import.meta.env.VITE_IOS) {
    await (await loadNative()).copyText(text);
    return true;
  }
  if (import.meta.env.VITE_TARGET !== "web" && inTauri) {
    const { writeHtml } = await import("@tauri-apps/plugin-clipboard-manager");
    await writeHtml(html, text);
    return true;
  }
  return false;
}

/** Trình duyệt nhúng trong app khác (Zalo, Facebook, Messenger, Instagram, LINE, TikTok…) thường không tải được file. */
export function inAppBrowser(): boolean {
  if (typeof navigator === "undefined") return false;
  return /FBAN|FBAV|FB_IAB|Messenger|Instagram|Zalo|Line\/|TikTok|musical_ly|BytedanceWebview/i.test(navigator.userAgent);
}

/** Bản web: tải một file văn bản qua trình duyệt (UC-W06, W07). Trả false khi trình duyệt không tải được file. */
export function downloadText(filename: string, content: string, mime: string): boolean {
  if (inAppBrowser()) return false;
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.rel = "noopener";
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
  return true;
}

/** Bản web: xin trình duyệt đừng tự xoá dữ liệu của trang khi thiếu chỗ (không phải trình duyệt nào cũng đồng ý). */
export async function persistStorage(): Promise<void> {
  try {
    if (navigator.storage?.persisted && !(await navigator.storage.persisted())) await navigator.storage.persist?.();
  } catch {
    /* không hỗ trợ: bỏ qua */
  }
}

/** Nền tảng của thiết bị, để hướng dẫn cài giọng đọc cho đúng (UC-W "Khi lỗi": thiếu giọng). */
export function devicePlatform(): "windows" | "mac" | "android" | "ios" | "other" {
  if (typeof navigator === "undefined") return "other";
  const ua = navigator.userAgent;
  if (/Android/i.test(ua)) return "android";
  if (/iPhone|iPad|iPod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "ios";
  if (/Mac OS X|Macintosh/.test(ua)) return "mac";
  if (/Windows/.test(ua)) return "windows";
  return "other";
}

/** Bộ cài bản desktop (dùng offline) — bản Release mới nhất trên GitHub (UC-M08). */
export const DESKTOP_RELEASES = "https://github.com/nguyennhuanhle/ec-advanced-learners-dictionary/releases";
export const DESKTOP_DOWNLOAD = `${DESKTOP_RELEASES}/latest`;
/** Kích thước bộ cài của bản Release hiện hành (thẻ tải ở Giới thiệu, UC-W09) — cập nhật khi đăng bản mới. */
export const SETUP_SIZE = "314 MB";
export const DMG_SIZE = "167 MB";
/** Trang chủ Edtech Corner (bản web có liên kết về, UC-W04). */
export const SITE_HOME = "https://edtechcorner.com";
/** Trang app iPhone/iPad trên App Store (Apple ID 6838543796; phát hành 2026-11-25) — thẻ tải ở Giới thiệu (UC-I13). */
export const APP_STORE_URL = "https://apps.apple.com/app/ec-eng-vie-dictionary/id6838543796";
