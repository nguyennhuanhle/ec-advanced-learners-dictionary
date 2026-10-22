// Lớp cách dùng (UC-U40, U43, U46–U49): nhãn EN/VI, nhóm dữ liệu, chữ để sao chép (thường và đục lỗ).
// Dữ liệu là câu thật lấy tự động từ corpus mở (pipeline/corpus_build.py), không phải AI.
import type { UsageEx } from "./types";
import { t, ui } from "./i18n.svelte";

const esc = (s: string) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

export const SOURCE_SHORT: Record<string, string> = {
  tatoeba: "Tatoeba",
  simplewiki: "Simple English Wikipedia",
  enwiki_p0: "English Wikipedia",
  enwiki_p1: "English Wikipedia",
};
export const sourceName = (id: string) => SOURCE_SHORT[id] ?? id;

/** Vị trí theo từ loại, theo thứ tự hiện (UC-U46). [mã, English, Tiếng Việt] */
export const ROLES: Record<string, [string, string, string][]> = {
  noun: [
    ["subject", "as subject", "làm chủ ngữ"],
    ["object", "as object", "làm tân ngữ"],
    ["after_prep", "after a preposition", "sau giới từ"],
    ["complement", "after be", "sau be"],
    ["noun_mod", "before another noun", "bổ nghĩa cho danh từ"],
    ["plural", "plural", "số nhiều"],
  ],
  verb: [
    ["base", "base form", "nguyên mẫu"],
    ["present", "present", "hiện tại"],
    ["s_form", "-s form", "dạng -s"],
    ["past", "past tense", "quá khứ"],
    ["pp", "past participle", "phân từ II"],
    ["ing", "-ing form", "dạng -ing"],
    ["passive", "passive", "bị động"],
    ["to_inf", "to + verb", "sau to"],
    ["ing_subject", "-ing as subject", "V-ing làm chủ ngữ"],
    ["ing_after_prep", "-ing after a preposition", "V-ing sau giới từ"],
  ],
  adj: [
    ["attributive", "before a noun", "trước danh từ"],
    ["predicative", "after be / seem / become", "sau động từ nối"],
    ["postnominal", "after a noun", "sau danh từ"],
    ["comparative", "comparative", "so sánh hơn"],
    ["superlative", "superlative", "so sánh nhất"],
  ],
  adv: [
    ["initial", "at the start", "đầu câu"],
    ["mid_before", "before the verb", "trước động từ"],
    ["mid_after", "after the verb", "sau động từ"],
    ["final", "at the end", "cuối câu"],
    ["before_adj", "before an adjective / adverb", "trước tính từ / trạng từ"],
    ["comparative", "comparative", "so sánh hơn"],
    ["superlative", "superlative", "so sánh nhất"],
  ],
};

/** Mẫu kết hợp theo từ loại, theo thứ tự hiện (UC-U43). {w} = từ đang tra. */
export const PATTERNS: Record<string, [string, string, string][]> = {
  noun: [
    ["verb_w", "VERB + {w}", "ĐỘNG TỪ + {w}"],
    ["adj_w", "ADJ + {w}", "TÍNH TỪ + {w}"],
    ["noun_noun", "NOUN + {w} / {w} + NOUN", "DANH TỪ + {w} / {w} + DANH TỪ"],
    ["w_verb", "{w} + VERB", "{w} + ĐỘNG TỪ"],
    ["quant_of_w", "QUANTIFIER + of + {w}", "LƯỢNG TỪ + of + {w}"],
  ],
  verb: [
    ["w_noun", "{w} + NOUN", "{w} + DANH TỪ"],
    ["adv_w", "ADV + {w} / {w} + ADV", "TRẠNG TỪ + {w} / {w} + TRẠNG TỪ"],
  ],
  adj: [
    ["adv_w", "ADV + {w}", "TRẠNG TỪ + {w}"],
    ["verb_w", "VERB + {w}", "ĐỘNG TỪ + {w}"],
    ["w_noun", "{w} + NOUN", "{w} + DANH TỪ"],
  ],
  adv: [
    ["verb_w", "VERB + {w}", "ĐỘNG TỪ + {w}"],
    ["w_adj", "{w} + ADJ / ADV", "{w} + TÍNH TỪ / TRẠNG TỪ"],
  ],
};

export const label = (row: [string, string, string], w = "") => (ui.lang === "vi" ? row[2] : row[1]).replaceAll("{w}", w);

/** Cắt câu thành [trước, từ được tô, sau]; a/b đếm theo ký tự Unicode (Python), không theo UTF-16. */
export function split(ex: UsageEx): [string, string, string] {
  const ch = Array.from(ex.text);
  return [ch.slice(0, ex.a).join(""), ch.slice(ex.a, ex.b).join(""), ch.slice(ex.b).join("")];
}

export type LenFilter = "any" | "short" | "mid" | "long";
export const lenOk = (ex: UsageEx, f: LenFilter) =>
  f === "any" || (f === "short" ? ex.n_words <= 12 : f === "mid" ? ex.n_words > 12 && ex.n_words <= 20 : ex.n_words > 20);

/** UC-U48 / U49: chép câu (mỗi câu một dòng, nguồn ở cuối — giấy phép CC BY / CC BY-SA bắt buộc ghi công).
 *  gap = đục lỗ: từ được tô thay bằng "______", đáp án trong ngoặc. */
export function sentencesClip(list: UsageEx[], gap: boolean): { html: string; text: string } {
  const lines = list.map((ex) => {
    const [pre, hit, post] = split(ex);
    const src = sourceName(ex.source);
    if (gap) {
      return {
        text: `${pre}______${post} (${hit}) — ${src}`,
        html: `<p>${esc(pre)}______${esc(post)} <i>(${esc(hit)})</i> <span style="color:#777">— ${esc(src)}</span></p>`,
      };
    }
    return {
      text: `${ex.text} — ${src}`,
      html: `<p>${esc(pre)}<b>${esc(hit)}</b>${esc(post)} <span style="color:#777">— ${esc(src)}</span></p>`,
    };
  });
  const foot = t("usageCopyFoot");
  return {
    html: lines.map((l) => l.html).join("") + `<p style="color:#777;font-size:8pt">${esc(foot)}</p>`,
    text: lines.map((l) => l.text).join("\n") + (list.length > 1 ? `\n\n${foot}` : ""),
  };
}

/** Bỏ câu trùng (một câu có thể ở nhiều vị trí, vd. V3 + bị động). */
export function uniq(list: UsageEx[]): UsageEx[] {
  const seen = new Set<string>();
  return list.filter((x) => !seen.has(x.text) && (seen.add(x.text), true));
}
