// Phát âm bằng giọng máy (prototype dùng Web Speech API của WebView2, đọc giọng Windows).
// Bản thật gọi Rust crate `tts` (PLAN mục 3); quy tắc giống nhau: thiếu giọng UK thì dùng giọng Mỹ và báo rõ.

import { t } from "./i18n.svelte";

export type Accent = "uk" | "us" | "vi";

function voices(): SpeechSynthesisVoice[] {
  return typeof speechSynthesis === "undefined" ? [] : speechSynthesis.getVoices();
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
  if (accent === "vi") return { voice: null, note: t("voiceNoVi") };
  return { voice: null, note: t("voiceNoEn") };
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
