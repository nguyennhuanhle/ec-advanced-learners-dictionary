// Phần gốc của app iOS (Capacitor 8, PLAN-ios vòng I1–I2). Cùng bộ hàm với android.ts (platform.ts › loadNative),
// chỉ được nhập động trong nhánh import.meta.env.VITE_IOS nên bản web/desktop/Android không mang file này.

import { Clipboard } from "@capacitor/clipboard";
import { SystemBars, SystemBarsStyle, SystemBarType } from "@capacitor/core";
import { Directory, Encoding, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { QueueStrategy, TextToSpeech } from "@capacitor-community/text-to-speech";

// ---------- lùi (UC-I02) ----------
// iOS không có nút Back hệ thống: bản iOS hiện nút lùi trên đầu trang (+page.svelte, .app.ios .nav), còn vuốt từ mép trái là
// cử chỉ gốc của WKWebView (ios/App/App/SceneDelegate.swift › MainViewController) — nó lùi theo history.pushState của app,
// rồi "popstate" đưa giao diện về màn trước như nút lùi. Không có gì phải nối ở đây.
export async function initBack(_handler: () => void): Promise<void> {}

export async function setBackEnabled(_on: boolean): Promise<void> {}

/** Android dùng để về app đang đọc sau UC-A08. iOS chưa có tra chữ từ app khác (UC-I12, để sau) nên không làm gì. */
export async function minimizeApp(): Promise<void> {}

/** UC-I12 để sau: chưa nhận chữ từ app khác. */
export async function initTextIntent(_handler: (text: string, self: boolean) => void): Promise<void> {}

// ---------- thanh trạng thái (UC-I05) ----------
/** Thanh trạng thái nằm trên đầu trang màu đậm → chữ sáng (iOS không có thanh điều hướng như Android). */
export async function setBarsStyle(_darkPage: boolean): Promise<void> {
  try {
    await SystemBars.setStyle({ style: SystemBarsStyle.Dark, bar: SystemBarType.StatusBar });
  } catch {
    /* không quan trọng */
  }
}

// ---------- liên kết ngoài (UC-I07): Capacitor iOS tự mở liên kết khác nguồn bằng Safari ----------
export async function openExternal(url: string): Promise<void> {
  window.open(url, "_blank", "noopener");
}

// ---------- clipboard ----------
export async function copyText(text: string): Promise<void> {
  await Clipboard.write({ string: text });
}

// ---------- chia sẻ file / link (UC-I04, UC-I06) ----------
const isCancel = (e: unknown) => /cancel/i.test(String((e as { message?: string })?.message ?? e));

/** Ghi file vào bộ nhớ đệm của app rồi mở bảng chia sẻ của iOS (có "Lưu vào Tệp"). false = người dùng huỷ. */
export async function shareFile(filename: string, content: string, title: string): Promise<boolean> {
  const { uri } = await Filesystem.writeFile({ path: filename, data: content, directory: Directory.Cache, encoding: Encoding.UTF8 });
  try {
    await Share.share({ title, files: [uri], dialogTitle: title });
    return true;
  } catch (e) {
    if (isCancel(e)) return false;
    throw e;
  }
}

export async function shareLink(url: string, title: string): Promise<boolean> {
  try {
    await Share.share({ title, text: title, url, dialogTitle: title });
    return true;
  } catch (e) {
    if (isCancel(e)) return false;
    throw e;
  }
}

// ---------- giọng đọc (UC-I03): AVSpeechSynthesizer qua plugin text-to-speech ----------
export type TtsResult = "ok" | "fallback-us" | "missing" | "no-engine";

type Voice = { voiceURI: string; name: string; lang: string; localService: boolean };
let voices: Voice[] | null = null;

/** Trên iOS getSupportedVoices chỉ liệt kê giọng ĐÃ CÓ trên máy (khác Android) nên không cần plugin kiểm riêng. */
async function loadVoices(): Promise<Voice[]> {
  if (!voices) voices = ((await TextToSpeech.getSupportedVoices()).voices ?? []) as Voice[];
  return voices;
}

/** Đọc `text` bằng giọng `lang` (en-GB / en-US / vi-VN); thiếu en-GB thì đọc bằng en-US (báo "fallback-us"). */
export async function ttsSpeak(text: string, lang: string): Promise<TtsResult> {
  const vs = await loadVoices();
  const norm = (l: string) => l.replace("_", "-").toLowerCase();
  const idx = (l: string) => vs.findIndex((v) => norm(v.lang) === l.toLowerCase());
  let use = lang;
  let res: TtsResult = "ok";
  if (idx(lang) < 0) {
    if (lang === "en-GB" && idx("en-US") >= 0) {
      use = "en-US";
      res = "fallback-us";
    } else return "missing";
  }
  // Không chọn giọng theo chỉ số: danh sách của iOS có cả giọng vui (Bells, Bad News…); chỉ đặt ngôn ngữ thì iOS dùng
  // giọng mặc định người dùng chọn cho ngôn ngữ đó. "playback": vẫn nghe được khi máy gạt sang chế độ im lặng.
  await TextToSpeech.speak({ text, lang: use, rate: 0.9, category: "playback", queueStrategy: QueueStrategy.Flush });
  return res;
}

/** iOS không cho app mở thẳng trang cài giọng; lời nhắn đã chỉ đường (speech.ts không hiện nút này trên iOS). */
export async function ttsOpenInstall(): Promise<void> {}
