// Những gì khác nhau giữa bản desktop (Tauri) và bản web, chọn LÚC BUILD qua import.meta.env.VITE_TARGET
// (vite.config.js đặt "web" khi `npm run build:web`, "desktop" khi build thường).
// Plugin Tauri chỉ được nhập động trong nhánh desktop, nên bản web không mang code @tauri-apps/plugin-*.

/** Bản build này chạy bằng code web (Worker + IndexedDB): bản web (dictionary.edtechcorner.com) VÀ app Android (Capacitor). */
export const IS_WEB = import.meta.env.VITE_TARGET === "web";

/** App Android (Capacitor, PLAN-android). Luôn kèm IS_WEB; dùng cho phần khác bản web (không GA, giọng đọc gốc, nút Back…). */
export const IS_ANDROID = import.meta.env.VITE_ANDROID === true;

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

/** Mở liên kết ngoài: desktop mở bằng trình duyệt mặc định (cửa sổ app không tự điều hướng); web mở tab mới. */
export async function openExternalUrl(url: string): Promise<void> {
  if (import.meta.env.VITE_TARGET !== "web" && inTauri) {
    const { openUrl } = await import("@tauri-apps/plugin-opener");
    await openUrl(url);
    return;
  }
  window.open(url, "_blank", "noopener");
}

/** Ghi clipboard có định dạng bằng plugin của Tauri (giữ HTML khi dán vào Word). Trả false khi không phải desktop. */
export async function writeHtmlNative(html: string, text: string): Promise<boolean> {
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
export const DESKTOP_DOWNLOAD = "https://github.com/nguyennhuanhle/ec-advanced-learners-dictionary/releases/latest";
/** Trang chủ Edtech Corner (bản web có liên kết về, UC-W04). */
export const SITE_HOME = "https://edtechcorner.com";
