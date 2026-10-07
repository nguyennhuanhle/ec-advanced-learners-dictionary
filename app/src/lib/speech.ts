// Phát âm bằng giọng máy (Web Speech API: WebView2 đọc giọng Windows ở bản desktop, trình duyệt/thiết bị ở bản web).
// Quy tắc chung: thiếu giọng UK thì dùng giọng Mỹ và báo rõ.
// Bản web (UC-W11): giọng CHẠY TRÊN MÁY (localService) xếp trước; giọng trực tuyến của trình duyệt (gửi chữ cần đọc tới máy chủ
// của hãng) mặc định bật, người dùng tắt được trong Cài đặt (setOnlineVoices) — tắt rồi thì chỉ dùng giọng trên máy.

import { t } from "./i18n.svelte";
import { IS_WEB, devicePlatform, loadAndroid } from "./platform";

export type Accent = "uk" | "us" | "vi";

let allowOnline = IS_WEB;
export function setOnlineVoices(on: boolean) {
  allowOnline = on;
}

function allVoices(): SpeechSynthesisVoice[] {
  return typeof speechSynthesis === "undefined" ? [] : speechSynthesis.getVoices();
}

/** Giọng được phép dùng, giọng trên máy xếp trước. */
function voices(): SpeechSynthesisVoice[] {
  const all = allVoices();
  if (!IS_WEB) return all;
  const local = all.filter((v) => v.localService);
  return allowOnline ? [...local, ...all.filter((v) => !v.localService)] : local;
}

/** Hướng dẫn cài giọng đọc theo nền tảng (bản web chạy trên nhiều loại máy). */
function voiceHelp(): string {
  switch (devicePlatform()) {
    case "android":
      return t("voiceHelpAndroid");
    case "ios":
      return t("voiceHelpIos");
    case "mac":
      return t("voiceHelpMac");
    case "windows":
      return t("voiceHelpWindows");
    default:
      return t("voiceHelpOther");
  }
}

export function pickVoice(accent: Accent): { voice: SpeechSynthesisVoice | null; note: string | null } {
  const vs = voices();
  const lang = accent === "uk" ? "en-GB" : accent === "us" ? "en-US" : "vi-VN";
  const exact = vs.find((v) => v.lang.replace("_", "-") === lang);
  if (exact) return { voice: exact, note: null };
  if (accent === "uk") {
    const us = vs.find((v) => v.lang.startsWith("en"));
    if (us) return { voice: us, note: t("voiceUkFallback") };
  }
  // bản web: có giọng trực tuyến hợp ngôn ngữ nhưng người dùng chưa bật → nói rõ thay vì "máy chưa có giọng"
  const prefix = accent === "vi" ? "vi" : "en";
  if (IS_WEB && !allowOnline && allVoices().some((v) => !v.localService && v.lang.replace("_", "-").startsWith(prefix)))
    return { voice: null, note: t("voiceOnlineOff") };
  // bản desktop giữ nguyên câu cũ (luôn là Windows); bản web hướng dẫn theo nền tảng của thiết bị
  if (!IS_WEB) return { voice: null, note: t(accent === "vi" ? "voiceNoVi" : "voiceNoEn") };
  return { voice: null, note: t(accent === "vi" ? "voiceNoViWeb" : "voiceNoEnWeb", { help: voiceHelp() }) };
}

/** App Android (UC-A03): WebView không có speechSynthesis → TextToSpeech của Android.
 *  Trả lời nhắn cần hiện (hoặc null) và có cần nút "mở cài đặt giọng nói" không. */
export async function speakAndroid(text: string, accent: Accent): Promise<{ note: string | null; install: boolean }> {
  const { ttsSpeak } = await loadAndroid();
  const lang = accent === "uk" ? "en-GB" : accent === "us" ? "en-US" : "vi-VN";
  try {
    const r = await ttsSpeak(text, lang);
    if (r === "ok") return { note: null, install: false };
    if (r === "fallback-us") return { note: t("voiceUkFallbackAndroid"), install: true };
    if (r === "no-engine") return { note: t("voiceNoEngineAndroid"), install: true };
    return { note: t(accent === "vi" ? "voiceNoViAndroid" : "voiceNoEnAndroid"), install: true };
  } catch (e) {
    return { note: t("voiceErrorAndroid", { e: String((e as { message?: string })?.message ?? e) }), install: false };
  }
}

export function speak(text: string, accent: Accent): string | null {
  if (typeof speechSynthesis === "undefined") return t("voiceUnsupported");
  const { voice, note } = pickVoice(accent);
  if (!voice) return note;
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.voice = voice;
  u.lang = voice.lang;
  u.rate = 0.9;
  speechSynthesis.speak(u);
  return note;
}
