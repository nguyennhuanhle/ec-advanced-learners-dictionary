// Bộ giải từ của bản web (PLAN-web mục 5, vòng W2): port phần "giải từ" của app/src-tauri/src/db.rs sang TypeScript.
// Mục từ đã dựng sẵn lúc xuất (pipeline/export_web.py), nên ở đây chỉ còn: norm, clean_query, looks_vietnamese,
// damerau, edits1, suggest, lookup (en_resolve, vi_resolve, also_vi/also_en, Choice), fuzzy (gợi ý chính tả).
// Giữ ĐÚNG thứ tự, giới hạn và chuỗi trả về như Rust; so sánh bằng pipeline/web_compare.py.
//
// File này không phụ thuộc trình duyệt hay Vite: chỉ dùng một DataSource để đọc file dữ liệu,
// nên chạy được trong Web Worker (worker.ts) lẫn trong Node (pipeline/web_core_cli.mjs, node có bỏ kiểu TS).
import type { EnEntry, LookupView, Source, Suggestion, ViEntry } from "../types";

// ---------------------------------------------------------------- định dạng dữ liệu xuất (export_web.py)

export interface Manifest {
  schema_web: number;
  data_version: string;
  build_date: string | null;
  min_ui: string;
  base: string;
  en_shards: number;
  vi_shards: number;
  hash: string;
  prefix: { len: number; max_len: number; space: string; other: string; split: string[]; split_bytes: number };
  relations: Record<string, string>;
  counts: Record<string, number>;
  files: number;
  bytes: number;
  /** bảng meta của dict-core.sqlite (= Dict::meta của Rust) */
  meta?: Record<string, string>;
  /** = Dict::counts() của Rust */
  db_counts?: Record<string, number>;
}

/** [từ, thứ hạng | null, norm nếu khác norm() tính lại] */
type HItem = [string, number | null, string?];
/** [form_norm, lemma, "i" | "v", tags, ≤3 lemma cho gợi ý nếu khác [lemma]] */
type FItem = [string, string, string, string, string[]?];
/** [từ Việt, trọng số = n_links + 3 * has_wikt, norm nếu khác] */
type VItem = [string, number, string?];

interface PrefixFile {
  h: HItem[];
  f: FItem[];
  v: VItem[];
  top?: { en: string[]; vi: string[] };
}

/** Một file tiền tố đã nạp, kèm norm tính sẵn cho từng dòng. */
interface Prefix {
  h: { word: string; rank: number | null; norm: string }[];
  f: FItem[];
  v: { word: string; weight: number; norm: string }[];
  top?: { en: string[]; vi: string[] };
}

/** Nơi đọc file dữ liệu (đường dẫn tương đối với thư mục v<phiên bản>/). Trả null khi file không có. */
export interface DataSource {
  json<T>(path: string, kind: "prefix" | "shard" | "other"): Promise<T | null>;
  text(path: string): Promise<string | null>;
}

// ---------------------------------------------------------------- hàm chữ (giống Rust)

/** char::is_whitespace của Rust (thuộc tính White_Space) — khác \s của JS ở \x85 và \uFEFF. */
const WS = /[\t-\r \x85\xA0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]/u;
const WS_RUN = /[\t-\r \x85\xA0\u1680\u2000-\u200A\u2028\u2029\u202F\u205F\u3000]+/u;
const ALPHA = /\p{Alphabetic}/u;
const MARKS = /\p{M}/gu; // unicode_normalization::char::is_combining_mark = Mn | Mc | Me
const HAS_MARK = /\p{M}/u;

/** str::trim của Rust (White_Space). */
export function rustTrim(s: string): string {
  const cps = Array.from(s);
  let a = 0;
  let b = cps.length;
  while (a < b && WS.test(cps[a])) a++;
  while (b > a && WS.test(cps[b - 1])) b--;
  return cps.slice(a, b).join("");
}

/** str::split_whitespace của Rust. */
export function splitWhitespace(s: string): string[] {
  return s.split(WS_RUN).filter((x) => x !== "");
}

/** Chữ thường, bỏ dấu (café → cafe, nhà → nha), đ → d. = db.rs::norm */
export function norm(s: string): string {
  return rustTrim(s.toLowerCase().replaceAll("đ", "d").normalize("NFD").replace(MARKS, ""));
}

/** Bỏ ký tự lạ, gộp khoảng trắng; giữ chữ, dấu nháy, gạch nối, ?, *, . = db.rs::clean_query */
export function cleanQuery(q: string): string {
  let kept = "";
  for (const c of q) {
    kept += ALPHA.test(c) || c === "'" || c === "-" || c === "?" || c === "*" || c === "." || WS.test(c) ? c : " ";
  }
  return kept.split(WS_RUN).filter((x) => x !== "").join(" ");
}

/** Có chữ cái riêng của tiếng Việt (có dấu, đ) → coi là tiếng Việt. = db.rs::looks_vietnamese */
export function looksVietnamese(q: string): boolean {
  for (const c of q) {
    if (c === "đ" || c === "Đ") return true;
    if (c.codePointAt(0)! > 0x7f && ALPHA.test(c) && HAS_MARK.test(c.normalize("NFD"))) return true;
  }
  return false;
}

/** Khoảng cách Damerau (OSA): đảo hai chữ cạnh nhau chỉ tính 1 lỗi. = db.rs::damerau (đếm theo ký tự Unicode). */
export function damerau(a: string, b: string): number {
  return damerauCps(Array.from(a), Array.from(b), Infinity);
}

/** Như damerau; dừng sớm và trả `limit + 1` khi chắc chắn vượt `limit` (hai hàng liên tiếp đều > limit). */
function damerauCps(a: string[], b: string[], limit: number): number {
  const n = a.length;
  const m = b.length;
  let prev2 = new Array<number>(m + 1).fill(0);
  let prev = new Array<number>(m + 1);
  let cur = new Array<number>(m + 1);
  for (let j = 0; j <= m; j++) prev[j] = j;
  let prevMin = 0;
  for (let i = 1; i <= n; i++) {
    cur[0] = i;
    let rowMin = i;
    for (let j = 1; j <= m; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let d = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) d = Math.min(d, prev2[j - 2] + 1);
      cur[j] = d;
      if (d < rowMin) rowMin = d;
    }
    // hàng i+1 chỉ nhỏ được từ hàng i (+0/+1) hoặc hàng i-1 (+1, phép đảo) → cả hai > limit thì kết quả > limit
    if (rowMin > limit && prevMin > limit) return limit + 1;
    prevMin = rowMin;
    [prev2, prev, cur] = [prev, cur, prev2];
  }
  return prev[m];
}

const EDIT_LETTERS = Array.from("abcdefghijklmnopqrstuvwxyz'-");

/** Mọi chuỗi cách `w` đúng 1 lỗi (xoá, đảo, thay, chèn một chữ a–z, ' hoặc -). = db.rs::edits1 */
export function edits1(w: string): Set<string> {
  const c = Array.from(w);
  const out = new Set<string>();
  for (let i = 0; i <= c.length; i++) {
    const l = c.slice(0, i).join("");
    const r = c.slice(i);
    const r1 = r.slice(1).join("");
    if (r.length) out.add(l + r1);
    if (r.length > 1) out.add(l + r[1] + r[0] + r.slice(2).join(""));
    const rAll = r.join("");
    for (const ch of EDIT_LETTERS) {
      if (r.length) out.add(l + ch + r1);
      out.add(l + ch + rAll);
    }
  }
  out.delete(w);
  return out;
}

/** So chuỗi theo điểm mã (= so byte UTF-8 của SQLite BINARY / String của Rust), không theo đơn vị UTF-16. */
export function cmpCp(a: string, b: string): number {
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    let x = a.charCodeAt(i);
    let y = b.charCodeAt(i);
    if (x !== y) {
      if (x >= 0xd800 && y >= 0xd800) {
        // nửa cặp thay thế (U+D800–DFFF) đứng cho ký tự > U+FFFF → phải lớn hơn U+E000–FFFF
        x = x >= 0xe000 ? x - 0x800 : x + 0x2000;
        y = y >= 0xe000 ? y - 0x800 : y + 0x2000;
      }
      return x - y;
    }
  }
  return a.length - b.length;
}

/** fnv1a32 trên UTF-8 (= export_web.fnv1a32), chọn shard. */
export function fnv1a32(s: string): number {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(s)) h = Math.imul(h ^ b, 0x01000193) >>> 0;
  return h;
}

const rankKey = (r: number | null) => (r === null ? Number.POSITIVE_INFINITY : r);

// ---------------------------------------------------------------- bộ giải từ

interface WordList {
  words: string[]; // theo thứ tự rowid của fts_headword (manifest.words_order = "fts_rowid")
  ranks: (number | null)[];
  lower: string[][]; // w.to_lowercase() tách theo ký tự
  folded: string[]; // văn bản FTS5 trigram đã gấp (chữ thường, bỏ dấu kiểu remove_diacritics 1)
  ntok: Int32Array; // số token trigram của mỗi dòng FTS (= số ký tự - 2)
  avgdl: number; // tổng token / số dòng (như FTS5)
  index: Map<string, number>; // từ → vị trí (cho edits1)
}

/** Gấp một ký tự như tokenizer trigram của FTS5 với remove_diacritics 1: chữ thường; chữ Latin có đúng một dấu → chữ gốc. */
function foldChar(c: string): string {
  const l = c.toLowerCase();
  const cp = l.codePointAt(0)!;
  if (l.length !== c.length || cp < 0xc0 || cp > 0x1eff) return l;
  const d = Array.from(l.normalize("NFD"));
  return d.length === 2 && HAS_MARK.test(d[1]) && d[0].codePointAt(0)! < 0x250 ? d[0] : l;
}
const foldStr = (s: string) => Array.from(s, foldChar).join("");

/** Số lần (chồng lấn) `g` xuất hiện trong `s` = số token trigram bằng g. */
function countOcc(s: string, g: string): number {
  let n = 0;
  for (let i = s.indexOf(g); i !== -1; i = s.indexOf(g, i + 1)) n++;
  return n;
}

export class DictCore {
  readonly manifest: Manifest;
  private src: DataSource;
  private split: Set<string>;
  private prefixCache = new Map<string, Promise<Prefix | null>>();
  private wordList: Promise<WordList> | null = null;
  /** thời gian nạp words.txt (ms), để đo */
  wordsLoadMs = 0;

  constructor(manifest: Manifest, src: DataSource) {
    this.manifest = manifest;
    this.src = src;
    this.split = new Set(manifest.prefix.split);
  }

  /** Tên file tiền tố của một norm (= export_web.bucket). */
  bucket(n: string): string {
    const { space, other, max_len } = this.manifest.prefix;
    const cps = Array.from(n);
    if (!cps.length || !(cps[0] >= "a" && cps[0] <= "z")) return other;
    const m = (c: string) => (c >= "a" && c <= "z" && c.length === 1 ? c : c === " " ? space : other);
    let k = cps.slice(0, 2).map(m).join("");
    while (this.split.has(k) && cps.length > k.length && k.length < max_len) k += m(cps[k.length]);
    return k;
  }

  private prefix(key: string): Promise<Prefix | null> {
    let p = this.prefixCache.get(key);
    if (!p) {
      p = this.src.json<PrefixFile>(`p/${key}.json`, "prefix").then((raw) =>
        raw
          ? {
              h: raw.h.map((x) => ({ word: x[0], rank: x[1], norm: x[2] ?? norm(x[0]) })),
              f: raw.f,
              v: raw.v.map((x) => ({ word: x[0], weight: x[1], norm: x[2] ?? norm(x[0]) })),
              top: raw.top,
            }
          : null,
      );
      p.catch(() => this.prefixCache.delete(key)); // lỗi mạng: lần sau thử lại
      this.prefixCache.set(key, p);
    }
    return p;
  }

  /** Bỏ bộ đệm tiền tố (giữ bộ nhớ vừa phải trong Worker). */
  trimCache(max = 400) {
    while (this.prefixCache.size > max) {
      const k = this.prefixCache.keys().next().value as string;
      this.prefixCache.delete(k);
    }
  }

  /** Gợi ý khi gõ (U01). = Dict::suggest */
  async suggest(raw: string, mode: string): Promise<Suggestion[]> {
    const q = norm(cleanQuery(raw));
    if (!q) return [];
    const k = this.bucket(q);
    const pf = await this.prefix(k);
    let enWords: string[];
    let viWords: string[];
    if (pf?.top && Array.from(q).length === k.length) {
      // chuỗi gõ = đúng khoá file: kết quả SQL đã dựng sẵn (từ có thể nằm ở nhiều file con)
      enWords = pf.top.en;
      viWords = pf.top.vi;
    } else {
      // mọi norm bắt đầu bằng q nằm trong file này; h, v đã sắp đúng thứ tự ORDER BY của Rust
      enWords = (pf?.h ?? []).filter((x) => x.norm.startsWith(q)).slice(0, 10).map((x) => x.word);
      const vv = (pf?.v ?? []).filter((x) => x.norm.startsWith(q));
      viWords = [...vv.filter((x) => x.norm === q), ...vv.filter((x) => x.norm !== q)].slice(0, 8).map((x) => x.word);
    }
    let en: Suggestion[] = enWords.map((w) => ({ label: w, key: w, note: null }));
    // dạng biến đổi gõ đủ (went, children) → gợi ý từ gốc ở đầu danh sách
    const f = pf?.f.find((x) => x[0] === q);
    if (f) {
      const label = rustTrim(raw).toLowerCase();
      const front = (f[4] ?? [f[1]]).filter((l) => norm(l) !== q).map((l) => ({ label, key: l, note: `→ ${l}` }));
      en = [...front, ...en];
    }
    const vi: Suggestion[] = viWords.map((w) => ({ label: w, key: `vi:${w}`, note: "Việt" }));
    const viFirst = mode === "vien" || looksVietnamese(raw);
    const out = viFirst ? [...vi, ...en] : [...en.slice(0, 7), ...vi];
    return out.slice(0, 10);
  }

  /** Tra (U02–U05, U24). = Dict::lookup */
  async lookup(raw0: string, mode: string): Promise<LookupView> {
    const forcedVi = raw0.startsWith("vi:");
    const raw = forcedVi ? raw0.slice(3) : raw0;
    const q = cleanQuery(raw);
    if (!q) return { kind: "empty" };
    const lv = looksVietnamese(q);
    const wantVi = forcedVi || mode === "vien" || lv;
    const vi = await this.viResolve(q);
    // chuỗi có dấu tiếng Việt không đem bỏ dấu để so với từ tiếng Anh (bàn ≠ ban)
    const en = forcedVi || lv ? null : await this.enResolve(q);
    if (wantVi && vi) {
      if (vi.kind === "vi" && en?.kind === "en") vi.also_en = en.word;
      return vi;
    }
    if (en) {
      if (en.kind === "en") {
        en.also_vi = vi?.kind === "vi" ? vi.word : vi?.kind === "choice" && vi.lang === "vi" ? q : null;
      }
      return en;
    }
    if (vi) return vi;
    const lower = q.toLowerCase();
    const suggestions = wantVi ? [] : await this.fuzzy(lower);
    return { kind: "none", query: q, suggestions };
  }

  private async viResolve(q: string): Promise<LookupView | null> {
    const lower = q.toLowerCase();
    const nq = norm(q);
    const pf = await this.prefix(this.bucket(nq));
    const items = pf?.v ?? [];
    // ORDER BY n_links + 3 * has_wikt DESC, word LIMIT 16
    const same = items
      .filter((x) => x.norm === nq)
      .sort((a, b) => b.weight - a.weight || cmpCp(a.word, b.word))
      .slice(0, 16)
      .map((x) => x.word);
    // gõ không dấu (U04): "nha" → cho chọn nhà, nhá, nhả… kể cả khi có mục "nha"
    if (!looksVietnamese(q) && same.length > 1) return { kind: "choice", query: q, words: same, lang: "vi" };
    if (items.some((x) => x.word === lower)) return { kind: "vi", word: lower, also_en: null };
    if (same.length === 0) return null;
    if (same.length === 1) return { kind: "vi", word: same[0], also_en: null };
    return { kind: "choice", query: q, words: same, lang: "vi" };
  }

  private async enResolve(q: string): Promise<LookupView | null> {
    const lower = q.toLowerCase();
    const qn = norm(q);
    const pf = await this.prefix(this.bucket(qn));
    const h = pf?.h ?? [];
    const exists = (w: string) => h.some((x) => x.word === w);
    if (exists(q)) return { kind: "en", word: q, via: null, also_vi: null };
    if (exists(lower)) return { kind: "en", word: lower, via: null, also_vi: null };
    // dạng biến đổi / biến thể chính tả (lemma đã chọn sẵn đúng như truy vấn của en_resolve)
    const f = pf?.f.find((x) => x[0] === qn);
    if (f) {
      const relation = this.manifest.relations[f[2]] ?? f[2];
      return { kind: "en", word: f[1], via: { form: lower, lemma: f[1], relation, tags: f[3] }, also_vi: null };
    }
    // khác chữ hoa / dấu (cafe → café, english → English): ORDER BY freq_rank IS NULL, freq_rank LIMIT 6,
    // hoà thì theo thứ tự quét chỉ mục (norm, word)
    const same = h
      .filter((x) => x.norm === qn)
      .sort((a, b) => rankKey(a.rank) - rankKey(b.rank) || cmpCp(a.word, b.word))
      .slice(0, 6)
      .map((x) => x.word);
    if (same.length === 0) return null;
    if (same.length === 1) return { kind: "en", word: same[0], via: null, also_vi: null };
    return { kind: "choice", query: q, words: same, lang: "en" };
  }

  /** Có mục Anh tên đúng `word` không (= Dict::exists). */
  async exists(word: string): Promise<boolean> {
    const pf = await this.prefix(this.bucket(norm(word)));
    return !!pf?.h.some((x) => x.word === word);
  }

  /** Nạp words.txt (chỉ khi lần đầu cần gợi ý chính tả). */
  loadWords(): Promise<WordList> {
    if (!this.wordList) {
      const t0 = now();
      this.wordList = this.src.text("words.txt").then((txt) => {
        if (txt === null) throw new Error("Dữ liệu của mục này bị lỗi, hãy tải lại trang");
        const words: string[] = [];
        const ranks: (number | null)[] = [];
        for (const line of txt.split("\n")) {
          if (!line) continue;
          const tab = line.lastIndexOf("\t");
          words.push(line.slice(0, tab));
          const r = line.slice(tab + 1);
          ranks.push(r === "" ? null : Number(r));
        }
        const lower = words.map((w) => Array.from(w.toLowerCase()));
        const folded = words.map(foldStr);
        const ntok = new Int32Array(words.length);
        let total = 0;
        for (let i = 0; i < words.length; i++) {
          ntok[i] = Math.max(0, Array.from(folded[i]).length - 2);
          total += ntok[i];
        }
        this.wordsLoadMs = now() - t0;
        return { words, ranks, lower, folded, ntok, avgdl: total / words.length, index: new Map(words.map((w, i) => [w, i])) };
      });
      this.wordList.catch(() => (this.wordList = null));
    }
    return this.wordList;
  }

  /** 600 ứng viên của `fts_headword MATCH "g1" OR "g2" … ORDER BY rank LIMIT 600` (db.rs::fuzzy), tính lại không cần FTS:
   *  rank = -bm25 như FTS5 (k1 = 1,2; b = 0,75; idf = ln((N − n + 0,5)/(n + 0,5)), ≤ 0 thì 1e-6; avgdl = tổng token / N),
   *  token = mọi cụm 3 ký tự của văn bản đã gấp; hoà điểm thì theo rowid (words.txt đã theo thứ tự rowid). */
  private ftsCandidates(wl: WordList, chars: string[]): { i: number; rank: number }[] {
    const grams = [...new Set(Array.from({ length: chars.length - 2 }, (_, i) => foldStr(chars.slice(i, i + 3).join(""))))];
    const n = wl.words.length;
    const hits: { i: number; tf: number[] }[] = [];
    const nHit = new Array<number>(grams.length).fill(0);
    for (let i = 0; i < n; i++) {
      const fw = wl.folded[i];
      let tf: number[] | null = null;
      for (let g = 0; g < grams.length; g++) {
        if (fw.includes(grams[g])) {
          tf ??= new Array<number>(grams.length).fill(0);
          tf[g] = countOcc(fw, grams[g]);
          nHit[g]++;
        }
      }
      if (tf) hits.push({ i, tf });
    }
    const idf = nHit.map((h) => {
      const v = Math.log((n - h + 0.5) / (h + 0.5));
      return v <= 0 ? 1e-6 : v;
    });
    const k1 = 1.2;
    const b = 0.75;
    const scored = hits.map(({ i, tf }) => {
      const D = wl.ntok[i];
      let score = 0;
      for (let g = 0; g < grams.length; g++) score += idf[g] * ((tf[g] * (k1 + 1.0)) / (tf[g] + k1 * (1 - b + (b * D) / wl.avgdl)));
      return { i, rank: -1.0 * score };
    });
    scored.sort((x, y) => x.rank - y.rank || x.i - y.i);
    return scored.slice(0, 600);
  }

  /** Gợi ý gần đúng chính tả. = Dict::fuzzy: 600 ứng viên FTS (mô phỏng, xem ftsCandidates) → lọc độ dài ±2 và
   *  Damerau ≤ 2, cộng mọi biến thể sai 1 lỗi (edits1) có trong từ điển; xếp theo (khoảng cách, thứ hạng, từ). */
  async fuzzy(q: string): Promise<{ word: string; available: boolean }[]> {
    const chars = Array.from(q).filter((c) => ALPHA.test(c));
    if (chars.length < 3) return [];
    const wl = await this.loadWords();
    const qc = Array.from(q);
    const cands: [number, number, string][] = [];
    for (const { i } of this.ftsCandidates(wl, chars)) {
      const lw = wl.lower[i];
      if (Math.abs(lw.length - chars.length) > 2) continue;
      const d = damerauCps(qc, lw, 2);
      if (d <= 2) cands.push([d, rankKey(wl.ranks[i]), wl.words[i]]);
    }
    // Từ ngắn gõ đảo chữ (bnak) không chung cụm 3 chữ nào với từ đúng (bank) → thêm mọi biến thể sai 1 lỗi.
    for (const e of edits1(q)) {
      const i = wl.index.get(e);
      if (i !== undefined) cands.push([damerau(q, e), rankKey(wl.ranks[i]), e]);
    }
    cands.sort((x, y) => x[0] - y[0] || x[1] - y[1] || cmpCp(x[2], y[2]));
    const out: string[] = [];
    for (const c of cands) if (out[out.length - 1] !== c[2]) out.push(c[2]);
    return out.slice(0, 10).map((word) => ({ word, available: true }));
  }

  /** Cho kiểm tra (web_compare.py): 600 ứng viên FTS mô phỏng, để so với SQLite thật. */
  async ftsTop(q: string): Promise<[string, number][]> {
    const chars = Array.from(q).filter((c) => ALPHA.test(c));
    if (chars.length < 3) return [];
    const wl = await this.loadWords();
    return this.ftsCandidates(wl, chars).map((x) => [wl.words[x.i], x.rank]);
  }

  async getEntry(word: string): Promise<EnEntry | null> {
    const n = this.manifest.en_shards;
    const shard = await this.src.json<Record<string, EnEntry>>(`e/${pad4(fnv1a32(word) % n)}.json`, "shard");
    if (!shard) throw new Error("Dữ liệu của mục này bị lỗi, hãy tải lại trang");
    return Object.hasOwn(shard, word) ? shard[word] : null;
  }

  async getViEntry(word: string): Promise<ViEntry | null> {
    const n = this.manifest.vi_shards;
    const shard = await this.src.json<Record<string, ViEntry>>(`v/${pad4(fnv1a32(word) % n)}.json`, "shard");
    if (!shard) throw new Error("Dữ liệu của mục này bị lỗi, hãy tải lại trang");
    return Object.hasOwn(shard, word) ? shard[word] : null;
  }

  async sources(): Promise<Source[]> {
    return (await this.src.json<Source[]>("sources.json", "other")) ?? [];
  }

  /** Một cửa vào cho các lệnh dữ liệu từ điển (cùng tên, cùng tham số như lib.rs::Core::call). */
  async call(cmd: string, a: Record<string, unknown>): Promise<unknown> {
    const s = (k: string) => (typeof a[k] === "string" ? (a[k] as string) : "");
    switch (cmd) {
      case "suggest":
        return this.suggest(s("q"), s("mode"));
      case "lookup":
        return this.lookup(s("q"), s("mode"));
      case "get_entry":
        return this.getEntry(s("word"));
      case "get_vi_entry":
        return this.getViEntry(s("word"));
      case "sources":
        return this.sources();
      default:
        throw new Error(`Lệnh không tồn tại: ${cmd}`);
    }
  }
}

const pad4 = (n: number) => String(n).padStart(4, "0");
const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

/** So phiên bản dạng a.b.c (cho manifest.min_ui). */
export function versionLess(a: string, b: string): boolean {
  const pa = a.split(".").map((x) => parseInt(x, 10) || 0);
  const pb = b.split(".").map((x) => parseInt(x, 10) || 0);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    if ((pa[i] ?? 0) !== (pb[i] ?? 0)) return (pa[i] ?? 0) < (pb[i] ?? 0);
  }
  return false;
}
