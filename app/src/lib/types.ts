// Kiểu dữ liệu trả về từ Rust (src-tauri/src/db.rs). Giữ đồng bộ hai bên.

export interface Example {
  en: string;
  vi: string | null;
}

export interface LearnerSense {
  guideword: string | null;
  grammar: string | null;
  labels: string | null;
  definition: string;
  cefr: string | null;
  vi: string | null;
  vi_ok: boolean;
  examples: Example[];
}

export interface WiktSense {
  gloss: string;
  grammar: string | null;
  labels: string | null;
  examples: string[];
  vi: string | null;
}

export interface ThesGroup {
  definition: string;
  members: string[];
  hypernym: string[];
}

export interface Block {
  pos: string;
  entry_type: string;
  model: string | null;
  cefr: string | null;
  forms: { form: string; tags: string[] }[];
  senses: LearnerSense[];
  wiktionary: WiktSense[];
  thesaurus: ThesGroup[];
  antonyms: string[];
  etymology: string | null;
  vi_block: string[];
  translations: { header: string; words: string }[];
}

export interface Phrase {
  phrase: string;
  gloss: string;
}

export interface EnEntry {
  word: string;
  rank: number | null;
  band: string | null;
  tier: string | null;
  ipa: { uk: string | null; us: string | null };
  blocks: Block[];
  phrasal_verbs: Phrase[];
  idioms: Phrase[];
  family: string[];
  nearby: string[];
  tatoeba: Example[];
  known: string[];
}

export interface ViHit {
  headword: string;
  pos: string;
  guideword: string | null;
  definition: string;
  source: string;
}

export interface ViEntry {
  word: string;
  en: ViHit[];
  wikt: { pos: string; glosses: string[] }[];
  tatoeba: Example[];
}

export interface Suggestion {
  label: string;
  key: string;
  note: string | null;
}

export interface Via {
  form: string;
  lemma: string;
  relation: string;
  tags: string;
}

export type LookupView =
  | { kind: "en"; word: string; via: Via | null; also_vi: string | null }
  | { kind: "vi"; word: string; also_en: string | null }
  | { kind: "choice"; query: string; words: string[]; lang: "en" | "vi" }
  | { kind: "none"; query: string; suggestions: { word: string; available: boolean }[] }
  | { kind: "empty" };

export interface DbStatus {
  ok: boolean;
  app_version?: string;
  error: string | null;
  path: string;
  meta: Record<string, string>;
  counts: Record<string, number>;
  user_ok: boolean;
  user_error: string | null;
  user_path: string | null;
  user_notice: string | null;
}

export interface HistoryRow {
  key: string;
  label: string;
  kind: "en" | "vi";
  ts: number;
}

export interface ListInfo {
  id: number;
  name: string;
  count: number;
}

export interface ListItem {
  id: number;
  word: string;
  pos: string;
  /** "" = cả từ; "3" = nghĩa AI số 3 (đếm từ 0); "w2" = nghĩa Wiktionary số 2 */
  sense: string;
  label: string;
  added_at: number;
  exists: boolean;
}

export interface Source {
  id: string;
  name: string;
  license: string;
  attribution: string | null;
  url: string;
  retrieved_at: string | null;
}

export type Mode = "en" | "envi" | "vien";
