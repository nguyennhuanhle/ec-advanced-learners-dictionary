// Xuất danh sách từ ra CSV cho bản web (UC-W06) — bản chép của lib.rs::export_csv / csv_rows / csv_field,
// cùng cột, cùng cách gộp nghĩa, để file web và file desktop giống nhau. Trình duyệt tải file (Blob), xem platform.ts.

import type { EnEntry } from "../types";
import { USER_ERR, type StoredItem } from "./user-common";

const HEADER = [
  "Từ", "Từ loại", "IPA (UK)", "IPA (US)", "CEFR", "Từ dẫn nghĩa", "Định nghĩa", "Nghĩa tiếng Việt", "Ví dụ",
  "Ví dụ (tiếng Việt)", "Nguồn",
];

/** (từ dẫn nghĩa, định nghĩa, CEFR, nghĩa Việt, ví dụ, ví dụ Việt) */
type S = [string, string, string, string, string, string];

function csvField(s: string): string {
  return /[,"\n\r]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}

/** trim_end_matches(|c| c == '.' || c.is_ascii_digit() || c == ' ') của Rust */
const trimNumbering = (x: string) => x.replace(/[.0-9 ]+$/, "");

/** Một mục đã lưu → các dòng CSV (= lib.rs::csv_rows). */
function csvRows(e: EnEntry | null, it: StoredItem): string[][] {
  if (!e) return [[it.word, it.pos, "", "", "", "", "(không còn trong bộ dữ liệu hiện tại)", "", "", "", ""]];
  const uk = e.ipa.uk ?? "";
  const us = e.ipa.us ?? "";
  const out: string[][] = [];
  for (const b of e.blocks.filter((b) => !it.pos || b.pos === it.pos)) {
    const src = b.model ? "AI (Gemini) từ Wiktionary" : "Wiktionary";
    const senses: S[] = b.senses.length
      ? b.senses.map((s) => {
          const ex = s.examples[0];
          return [s.guideword ?? "", s.definition, s.cefr ?? "", s.vi ?? "", ex?.en ?? "", ex?.vi ?? ""];
        })
      : b.wiktionary.map((w) => ["", w.gloss, "", w.vi ?? "", w.examples[0] ?? "", ""]);
    let picked: S[];
    if (it.sense === "") picked = senses.slice(0, 8);
    else {
      const raw = it.sense.replace(/^w+/, "");
      const idx = /^\d+$/.test(raw) ? Number(raw) : -1;
      picked = idx >= 0 && idx < senses.length ? [senses[idx]] : [];
    }
    if (!picked.length) continue;
    const viFallback = b.senses.length ? "" : b.vi_block.slice(0, 3).join("; ");
    const join = (f: (s: S) => string, numbered: boolean): string => {
      if (picked.length === 1) return f(picked[0]);
      return picked
        .map((s, i) => (numbered ? `${i + 1}. ${f(s)}` : f(s)))
        .filter((x) => trimNumbering(x) !== "")
        .join(" | ");
    };
    let vi = join((s) => s[3], true);
    if (vi.trim() === "" || /^[0-9 .|]*$/.test(vi)) vi = viFallback;
    out.push([
      e.word,
      b.pos,
      uk,
      us,
      picked.length === 1 ? picked[0][2] : b.cefr ?? "",
      join((s) => s[0], false),
      join((s) => s[1], true),
      vi,
      picked.map((s) => s[4]).find((x) => x !== "") ?? "",
      picked.map((s) => s[5]).find((x) => x !== "") ?? "",
      src,
    ]);
  }
  return out;
}

/** Nội dung CSV (chưa có BOM) + số dòng dữ liệu. `items` theo thứ tự hiển thị (mới trước), như user_db.rs::items. */
export async function buildCsv(
  items: StoredItem[],
  entry: (word: string) => Promise<EnEntry | null>,
): Promise<{ text: string; rows: number }> {
  if (!items.length) throw USER_ERR.emptyList;
  const rows: string[][] = [HEADER];
  for (const it of [...items].reverse()) rows.push(...csvRows(await entry(it.word), it));
  return { text: rows.map((r) => r.map(csvField).join(",")).join("\r\n"), rows: rows.length - 1 };
}
