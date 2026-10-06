// Những gì khác nhau giữa bản desktop (Tauri) và bản web, chọn LÚC BUILD qua import.meta.env.VITE_TARGET
// (vite.config.js đặt "web" khi `npm run build:web`, "desktop" khi build thường).
// Plugin Tauri chỉ được nhập động trong nhánh desktop, nên bản web không mang code @tauri-apps/plugin-*.

/** Bản build này là bản web (dictionary.edtechcorner.com)? */
export const IS_WEB = import.meta.env.VITE_TARGET === "web";

/** Đang chạy trong cửa sổ Tauri (desktop). Bản web luôn false. */
export const inTauri =
  import.meta.env.VITE_TARGET !== "web" && typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

/** Chọn nơi lưu file CSV. Desktop trong Tauri: hộp thoại Lưu của hệ điều hành; còn lại: trả về đường dẫn gợi ý.
 *  TODO(W3): bản web tải file qua trình duyệt (Blob + <a download>), không cần chọn đường dẫn. */
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
