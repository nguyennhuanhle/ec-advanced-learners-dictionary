// UC-U36: sao chép mục từ / một nghĩa thành văn bản có định dạng (HTML) + bản chữ thường, để dán vào Word.
import type { Block, EnEntry, LearnerSense, WiktSense } from "./types";
import { t } from "./i18n.svelte";
import { writeHtmlNative } from "./platform";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function senseHtml(s: LearnerSense | WiktSense, n: number, showVi: boolean): string {
  if ("definition" in s) {
    const head = [s.guideword && `<b style="color:#8a4b0f">${esc(s.guideword)}</b>`, s.cefr && `[${esc(s.cefr)}]`, s.grammar && esc(s.grammar), s.labels && `<i>${esc(s.labels)}</i>`]
      .filter(Boolean)
      .join(" ");
    const ex = s.examples
      .map((x) => `<br>&nbsp;&nbsp;• <i>${esc(x.en)}</i>${showVi && x.vi ? ` — ${esc(x.vi)}` : ""}`)
      .join("");
    return `<p><b>${n}.</b> ${head} ${esc(s.definition)}${showVi && s.vi ? `<br>&nbsp;&nbsp;<span style="color:#2f6b2f">${esc(s.vi)}</span>` : ""}${ex}</p>`;
  }
  const head = [s.grammar && esc(s.grammar), s.labels && `<i>${esc(s.labels)}</i>`].filter(Boolean).join(" ");
  const ex = s.examples.map((x) => `<br>&nbsp;&nbsp;• <i>${esc(x)}</i>`).join("");
  return `<p><b>${n}.</b> ${head} ${esc(s.gloss)}${showVi && s.vi ? `<br>&nbsp;&nbsp;<span style="color:#2f6b2f">${esc(s.vi)}</span>` : ""}${ex}</p>`;
}

function senseText(s: LearnerSense | WiktSense, n: number, showVi: boolean): string {
  if ("definition" in s) {
    const head = [s.guideword, s.cefr && `[${s.cefr}]`, s.grammar, s.labels].filter(Boolean).join(" ");
    const lines = [`${n}. ${head ? head + " " : ""}${s.definition}`];
    if (showVi && s.vi) lines.push(`   ${s.vi}`);
    for (const x of s.examples) lines.push(`   • ${x.en}${showVi && x.vi ? " — " + x.vi : ""}`);
    return lines.join("\n");
  }
  const lines = [`${n}. ${[s.grammar, s.labels].filter(Boolean).join(" ")} ${s.gloss}`.replace(/\s+/g, " ")];
  if (showVi && s.vi) lines.push(`   ${s.vi}`);
  for (const x of s.examples) lines.push(`   • ${x}`);
  return lines.join("\n");
}

function blockSenses(b: Block): (LearnerSense | WiktSense)[] {
  return b.senses.length ? b.senses : b.wiktionary.slice(0, 12);
}

function headHtml(e: EnEntry): string {
  const ipa = [e.ipa.uk && `UK ${esc(e.ipa.uk)}`, e.ipa.us && `US ${esc(e.ipa.us)}`].filter(Boolean).join("  ");
  return `<p><span style="font-size:16pt"><b>${esc(e.word)}</b></span>${ipa ? `&nbsp;&nbsp;${ipa}` : ""}</p>`;
}

export function entryClip(e: EnEntry, showVi: boolean): { html: string; text: string } {
  let html = headHtml(e);
  let text = `${e.word}  ${[e.ipa.uk && "UK " + e.ipa.uk, e.ipa.us && "US " + e.ipa.us].filter(Boolean).join("  ")}`;
  for (const b of e.blocks) {
    html += `<p><i>${esc(b.pos)}</i>${b.cefr ? ` [${esc(b.cefr)}]` : ""}</p>`;
    text += `\n\n${b.pos}${b.cefr ? ` [${b.cefr}]` : ""}`;
    blockSenses(b).forEach((s, i) => {
      html += senseHtml(s, i + 1, showVi);
      text += "\n" + senseText(s, i + 1, showVi);
    });
  }
  html += `<p style="color:#777;font-size:8pt">${esc(t("copyFoot"))}${e.blocks.some((b) => b.model) ? esc(t("copyFootAi")) : ""}.</p>`;
  return { html, text };
}

export function senseClip(e: EnEntry, b: Block, s: LearnerSense | WiktSense, n: number, showVi: boolean) {
  return {
    html: headHtml(e) + `<p><i>${esc(b.pos)}</i></p>` + senseHtml(s, n, showVi),
    text: `${e.word} (${b.pos})\n${senseText(s, n, showVi)}`,
  };
}

export async function writeClipboard(html: string, text: string): Promise<void> {
  // App thật: plugin clipboard của Tauri (giữ định dạng HTML khi dán vào Word) — xem platform.ts.
  if (await writeHtmlNative(html, text)) return;
  // Trình duyệt (bản web, chế độ dev): thử Clipboard API, không được thì chọn vùng HTML ẩn rồi copy.
  try {
    await navigator.clipboard.write([
      new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([text], { type: "text/plain" }),
      }),
    ]);
    return;
  } catch {
    const box = document.createElement("div");
    box.contentEditable = "true";
    box.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
    box.innerHTML = html;
    document.body.appendChild(box);
    const range = document.createRange();
    range.selectNodeContents(box);
    const sel = window.getSelection();
    sel?.removeAllRanges();
    sel?.addRange(range);
    const ok = document.execCommand("copy");
    sel?.removeAllRanges();
    box.remove();
    if (!ok) throw new Error("trình xem không cho phép ghi clipboard");
  }
}
