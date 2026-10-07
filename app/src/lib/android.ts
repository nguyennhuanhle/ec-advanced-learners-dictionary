// Phần gốc của app Android (Capacitor 8, PLAN-android vòng A2). Chỉ được nhập động trong nhánh import.meta.env.VITE_ANDROID,
// nên bản web và bản desktop không mang code Capacitor.

import { App } from "@capacitor/app";
import { Browser } from "@capacitor/browser";
import { Clipboard } from "@capacitor/clipboard";
import { SystemBars, SystemBarsStyle, SystemBarType, registerPlugin } from "@capacitor/core";
import { Directory, Encoding, Filesystem } from "@capacitor/filesystem";
import { Share } from "@capacitor/share";
import { QueueStrategy, TextToSpeech } from "@capacitor-community/text-to-speech";

// ---------- nút Back / cử chỉ vuốt lùi (UC-A02, PLAN-android mục 7) ----------
// Android 16 + target 36: hệ thống không gọi onBackPressed nữa. Handler của @capacitor/app mặc định TẮT
// (capacitor.config.ts: disableBackButtonHandler) để predictive back chạy; giao diện chỉ BẬT khi có chỗ để lùi/đóng.
let backOn = false;
let backHandler: (() => void) | null = null;

export async function initBack(handler: () => void): Promise<void> {
  backHandler = handler;
  await App.addListener("backButton", () => backHandler?.());
}

export async function setBackEnabled(on: boolean): Promise<void> {
  if (on === backOn) return;
  backOn = on;
  try {
    await App.toggleBackButtonHandler({ enabled: on });
  } catch {
    /* plugin chưa sẵn sàng: lần đổi trạng thái sau thử lại */
    backOn = !on;
  }
}

// ---------- thanh trạng thái / thanh điều hướng (tràn viền, PLAN-android mục 8) ----------
/** Thanh trạng thái nằm trên đầu trang màu đậm → chữ/biểu tượng sáng. Thanh điều hướng nằm trên nền trang → theo sáng/tối. */
export async function setBarsStyle(darkPage: boolean): Promise<void> {
  try {
    await SystemBars.setStyle({ style: SystemBarsStyle.Dark, bar: SystemBarType.StatusBar });
    await SystemBars.setStyle({ style: darkPage ? SystemBarsStyle.Dark : SystemBarsStyle.Light, bar: SystemBarType.NavigationBar });
  } catch {
    /* không quan trọng */
  }
}

// ---------- liên kết ngoài (UC-A07): mở bằng trình duyệt của máy; app không có quyền INTERNET ----------
export async function openExternal(url: string): Promise<void> {
  await Browser.open({ url });
}

// ---------- clipboard (U36) ----------
export async function copyText(text: string): Promise<void> {
  await Clipboard.write({ string: text });
}

// ---------- chia sẻ file / link (UC-A04, UC-A06) ----------
const isCancel = (e: unknown) => /cancel/i.test(String((e as { message?: string })?.message ?? e));

/** Ghi file vào bộ nhớ đệm của app rồi mở bảng chia sẻ của Android. false = người dùng huỷ (không phải lỗi). */
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

// ---------- giọng đọc của Android (UC-A03): WebView không có speechSynthesis ----------
export type TtsResult = "ok" | "fallback-us" | "missing" | "no-engine";

/** Plugin riêng của app (android/…/VoiceCheckPlugin.java): giọng nào đã CÀI thật. isLanguageSupported của plugin TTS trả
 *  "có" cả khi dữ liệu giọng chưa tải (Google TTS lặng lẽ đọc bằng giọng khác — đã thấy: bấm UK nghe giọng Mỹ). */
type InstalledVoice = { name: string; lang: string; network: boolean };
const VoiceCheck = registerPlugin<{
  installed(): Promise<{ engine: boolean; langs: string[]; voices: InstalledVoice[] }>;
  openInstall(): Promise<void>;
}>("VoiceCheck");

/** Danh sách giọng theo thứ tự của plugin TTS (tham số `voice` của speak là chỉ số trong danh sách này). */
let ttsVoices: string[] | null = null;
async function voiceIndex(name: string): Promise<number> {
  if (!ttsVoices) ttsVoices = (await TextToSpeech.getSupportedVoices()).voices.map((v) => v.voiceURI);
  return ttsVoices.indexOf(name);
}

/** Chọn đích danh một giọng ĐÃ CÀI của đúng ngôn ngữ: ưu tiên giọng chạy trên máy, bỏ giọng chung "…-language"
 *  (Google TTS có thể đổi giọng chung en-GB sang giọng Mỹ). Không có thì -1 (chỉ đặt ngôn ngữ). */
async function pickVoice(voices: InstalledVoice[], lang: string): Promise<number> {
  const same = voices.filter((v) => v.lang.toLowerCase() === lang.toLowerCase() && !v.name.endsWith("-language"));
  same.sort((a, b) => Number(a.network) - Number(b.network) || a.name.localeCompare(b.name));
  for (const v of same) {
    const i = await voiceIndex(v.name);
    if (i >= 0) return i;
  }
  return -1;
}

/** Đọc `text` bằng giọng `lang` (en-GB / en-US / vi-VN); thiếu en-GB thì đọc bằng en-US (báo "fallback-us"). */
export async function ttsSpeak(text: string, lang: string): Promise<TtsResult> {
  const v = await VoiceCheck.installed();
  if (!v.engine) return "no-engine";
  const has = (l: string) => v.langs.some((x) => x.toLowerCase() === l.toLowerCase());
  let use = lang;
  let res: TtsResult = "ok";
  if (!has(lang)) {
    if (lang === "en-GB" && has("en-US")) {
      use = "en-US";
      res = "fallback-us";
    } else return "missing";
  }
  const voice = await pickVoice(v.voices ?? [], use);
  await TextToSpeech.speak({ text, lang: use, rate: 0.9, queueStrategy: QueueStrategy.Flush, ...(voice >= 0 ? { voice } : {}) });
  return res;
}

/** Mở màn hình tải giọng của engine mặc định (hoặc Cài đặt › Chuyển văn bản thành giọng nói). */
export async function ttsOpenInstall(): Promise<void> {
  await VoiceCheck.openInstall();
}
