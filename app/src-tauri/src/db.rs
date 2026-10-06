//! Truy vấn dữ liệu từ điển lõi (dict-core.sqlite), chỉ đọc.
//! Quy tắc CANNOT "người dùng không sửa được dữ liệu lõi": mở bằng SQLITE_OPEN_READ_ONLY + immutable=1,
//! và không có hàm nào trong module này ghi vào DB.

use rusqlite::{params, Connection, OpenFlags, OptionalExtension};
use serde::Serialize;
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use unicode_normalization::char::is_combining_mark;
use unicode_normalization::UnicodeNormalization;

pub const SCHEMA_VERSION: &str = "2";

pub struct Dict {
    conn: Mutex<Connection>,
    #[allow(dead_code)]
    pub path: PathBuf,
    pub meta: HashMap<String, String>,
}

/// Chữ thường, bỏ dấu (café → cafe, nhà → nha), đ → d. Giống hàm norm() của pipeline.
pub fn norm(s: &str) -> String {
    s.to_lowercase()
        .replace('đ', "d")
        .nfd()
        .filter(|c| !is_combining_mark(*c))
        .collect::<String>()
        .trim()
        .to_string()
}

/// Bỏ ký tự lạ, gộp khoảng trắng; giữ chữ, dấu nháy, gạch nối, ? và * (cho tìm theo mẫu sau này).
pub fn clean_query(q: &str) -> String {
    let kept: String = q
        .chars()
        .map(|c| if c.is_alphabetic() || matches!(c, '\'' | '-' | '?' | '*' | '.') || c.is_whitespace() { c } else { ' ' })
        .collect();
    kept.split_whitespace().collect::<Vec<_>>().join(" ")
}

/// Khoảng cách Damerau (OSA): đảo hai chữ cạnh nhau chỉ tính 1 lỗi.
pub fn damerau(a: &str, b: &str) -> usize {
    let a: Vec<char> = a.chars().collect();
    let b: Vec<char> = b.chars().collect();
    let (n, m) = (a.len(), b.len());
    let mut d = vec![vec![0usize; m + 1]; n + 1];
    for i in 0..=n {
        d[i][0] = i;
    }
    for j in 0..=m {
        d[0][j] = j;
    }
    for i in 1..=n {
        for j in 1..=m {
            let cost = usize::from(a[i - 1] != b[j - 1]);
            d[i][j] = (d[i - 1][j] + 1).min(d[i][j - 1] + 1).min(d[i - 1][j - 1] + cost);
            if i > 1 && j > 1 && a[i - 1] == b[j - 2] && a[i - 2] == b[j - 1] {
                d[i][j] = d[i][j].min(d[i - 2][j - 2] + 1);
            }
        }
    }
    d[n][m]
}

/// Mọi chuỗi cách `w` đúng 1 lỗi (xoá, đảo, thay, chèn một chữ a–z).
fn edits1(w: &str) -> Vec<String> {
    let c: Vec<char> = w.chars().collect();
    let letters = "abcdefghijklmnopqrstuvwxyz'-";
    let mut out = HashSet::new();
    for i in 0..=c.len() {
        let (l, r) = c.split_at(i);
        let l: String = l.iter().collect();
        if !r.is_empty() {
            out.insert(format!("{l}{}", r[1..].iter().collect::<String>()));
        }
        if r.len() > 1 {
            out.insert(format!("{l}{}{}{}", r[1], r[0], r[2..].iter().collect::<String>()));
        }
        for ch in letters.chars() {
            if !r.is_empty() {
                out.insert(format!("{l}{ch}{}", r[1..].iter().collect::<String>()));
            }
            out.insert(format!("{l}{ch}{}", r.iter().collect::<String>()));
        }
    }
    out.remove(w);
    out.into_iter().collect()
}

#[derive(Serialize)]
pub struct Suggestion {
    pub label: String,
    pub key: String,
    pub note: Option<String>,
}

#[derive(Serialize)]
pub struct Via {
    pub form: String,
    pub lemma: String,
    pub relation: String,
    pub tags: String,
}

#[derive(Serialize)]
pub struct Candidate {
    pub word: String,
    pub available: bool,
}

#[derive(Serialize)]
#[serde(tag = "kind", rename_all = "lowercase")]
pub enum View {
    En { word: String, via: Option<Via>, also_vi: Option<String> },
    Vi { word: String, also_en: Option<String> },
    Choice { query: String, words: Vec<String>, lang: String },
    None { query: String, suggestions: Vec<Candidate> },
    Empty,
}

/// Có chữ cái riêng của tiếng Việt (có dấu, đ) → coi là tiếng Việt.
pub fn looks_vietnamese(q: &str) -> bool {
    q.chars().any(|c| {
        c == 'đ' || c == 'Đ' || (c.is_alphabetic() && !c.is_ascii() && c.to_string().nfd().any(is_combining_mark))
    })
}

#[derive(Serialize, Default)]
pub struct Ipa {
    pub uk: Option<String>,
    pub us: Option<String>,
}

#[derive(Serialize)]
pub struct Form {
    pub form: String,
    pub tags: Vec<String>,
}

#[derive(Serialize)]
pub struct Example {
    pub en: String,
    pub vi: Option<String>,
}

#[derive(Serialize)]
pub struct LearnerSense {
    pub guideword: Option<String>,
    pub grammar: Option<String>,
    pub labels: Option<String>,
    pub definition: String,
    pub cefr: Option<String>,
    pub vi: Option<String>,
    pub vi_ok: bool,
    pub examples: Vec<Example>,
}

#[derive(Serialize)]
pub struct WiktSense {
    pub gloss: String,
    pub grammar: Option<String>,
    pub labels: Option<String>,
    pub examples: Vec<String>,
    /// bản dịch tiếng Việt theo nghĩa (bảng dịch của Wiktionary EN)
    pub vi: Option<String>,
}

#[derive(Serialize)]
pub struct TrGroup {
    pub header: String,
    pub words: String,
}

#[derive(Serialize)]
pub struct ViHit {
    pub headword: String,
    pub pos: String,
    pub guideword: Option<String>,
    pub definition: String,
    pub source: String,
}

#[derive(Serialize)]
pub struct ViSense {
    pub pos: String,
    pub glosses: Vec<String>,
}

#[derive(Serialize)]
pub struct ViEntry {
    pub word: String,
    pub en: Vec<ViHit>,
    pub wikt: Vec<ViSense>,
    pub tatoeba: Vec<Example>,
}

#[derive(Serialize)]
pub struct ThesGroup {
    pub definition: String,
    pub members: Vec<String>,
    pub hypernym: Vec<String>,
}

#[derive(Serialize)]
pub struct Block {
    pub pos: String,
    pub entry_type: String,
    pub model: Option<String>,
    pub cefr: Option<String>,
    pub forms: Vec<Form>,
    pub senses: Vec<LearnerSense>,
    pub wiktionary: Vec<WiktSense>,
    pub thesaurus: Vec<ThesGroup>,
    pub antonyms: Vec<String>,
    pub etymology: Option<String>,
    /// khối nghĩa tiếng Việt theo từ loại (Wiktionary tiếng Việt), dùng khi chưa có nghĩa Việt theo từng nghĩa
    pub vi_block: Vec<String>,
    /// nhóm bản dịch không gắn được vào nghĩa nào
    pub translations: Vec<TrGroup>,
}

#[derive(Serialize)]
pub struct Phrase {
    pub phrase: String,
    pub gloss: String,
}

#[derive(Serialize)]
pub struct Entry {
    pub word: String,
    pub rank: Option<i64>,
    pub band: Option<String>,
    pub tier: Option<String>,
    pub ipa: Ipa,
    pub blocks: Vec<Block>,
    pub phrasal_verbs: Vec<Phrase>,
    pub idioms: Vec<Phrase>,
    pub family: Vec<String>,
    pub nearby: Vec<String>,
    pub tatoeba: Vec<Example>,
    /// Các từ được nhắc tới trong mục (đồng nghĩa, họ từ, cụm…) có mục riêng trong từ điển → bấm được.
    pub known: Vec<String>,
}

#[derive(Serialize)]
pub struct Source {
    pub id: String,
    pub name: String,
    pub license: String,
    pub attribution: Option<String>,
    pub url: String,
    pub retrieved_at: Option<String>,
}

/// Đổi đường dẫn file thành URI SQLite hợp lệ (https://sqlite.org/uri.html), để mở được kèm `?immutable=1`.
/// - Bỏ tiền tố "verbatim" của Windows: `\\?\C:\…` → `C:/…`, `\\?\UNC\máy\chia-sẻ\…` → `//máy/chia-sẻ/…`.
///   Bản cài nhận đường dẫn kiểu này từ resource_dir(); để nguyên thì thành `file://?/C:/…` và SQLite báo
///   "invalid uri authority: ?" (lỗi 2026-10-06 sau khi cài).
/// - Ổ đĩa → `file:///C:/…`; UNC → `file:////máy/chia-sẻ/…` (authority rỗng); tuyệt đối kiểu Unix → `file:///…`.
/// - Mọi byte ngoài [A-Za-z0-9-._~/:] được mã hoá %XX theo UTF-8 (dấu cách, `’`, `%`, `?`, `#`…); SQLite giải mã lại.
pub fn sqlite_file_uri(path: &Path) -> String {
    let mut p = path.to_string_lossy().replace('\\', "/");
    if let Some(rest) = p.strip_prefix("//?/UNC/").or_else(|| p.strip_prefix("//./UNC/")) {
        p = format!("//{rest}");
    } else if let Some(rest) = p.strip_prefix("//?/").or_else(|| p.strip_prefix("//./")) {
        p = rest.to_string();
    }
    let b = p.as_bytes();
    let drive = b.len() >= 2 && b[0].is_ascii_alphabetic() && b[1] == b':';
    let prefix = if drive {
        "file:///"
    } else if p.starts_with('/') {
        "file://" // "/x" → file:///x ; "//máy/x" → file:////máy/x
    } else {
        "file:" // đường dẫn tương đối
    };
    let mut out = String::with_capacity(prefix.len() + p.len() + 16);
    out.push_str(prefix);
    for &c in p.as_bytes() {
        if c.is_ascii_alphanumeric() || matches!(c, b'-' | b'.' | b'_' | b'~' | b'/' | b':') {
            out.push(c as char);
        } else {
            out.push_str(&format!("%{c:02X}"));
        }
    }
    out
}

fn s(v: Option<String>) -> Option<String> {
    v.filter(|x| !x.is_empty())
}

impl Dict {
    /// Mở dữ liệu lõi chỉ đọc và kiểm tra phiên bản schema (UC-S02).
    pub fn open(path: &Path) -> Result<Dict, String> {
        if !path.exists() {
            return Err(format!("Không tìm thấy file dữ liệu: {}", path.display()));
        }
        let uri = format!("{}?immutable=1", sqlite_file_uri(path));
        let conn = Connection::open_with_flags(
            &uri,
            OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI | OpenFlags::SQLITE_OPEN_NO_MUTEX,
        )
        .map_err(|e| format!("Không mở được dữ liệu ({e})"))?;
        let mut meta = HashMap::new();
        {
            let mut st = conn
                .prepare("SELECT key, value FROM meta")
                .map_err(|e| format!("Dữ liệu hỏng hoặc sai định dạng ({e})"))?;
            let rows = st
                .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
                .map_err(|e| e.to_string())?;
            for r in rows.flatten() {
                meta.insert(r.0, r.1);
            }
        }
        match meta.get("schema_version").map(String::as_str) {
            Some(SCHEMA_VERSION) => {}
            other => {
                return Err(format!(
                    "Dữ liệu dành cho phiên bản khác của app (schema {:?}, app cần {SCHEMA_VERSION})",
                    other
                ))
            }
        }
        Ok(Dict { conn: Mutex::new(conn), path: path.to_path_buf(), meta })
    }

    /// Gợi ý khi gõ (U01). Chế độ Việt–Anh hoặc chuỗi có dấu tiếng Việt → gợi ý tiếng Việt lên trước.
    pub fn suggest(&self, raw: &str, mode: &str) -> Vec<Suggestion> {
        let q = norm(&clean_query(raw));
        if q.is_empty() {
            return vec![];
        }
        let conn = self.conn.lock().unwrap();
        let upper = format!("{q}\u{10FFFF}");
        let mut en: Vec<Suggestion> = vec![];
        if let Ok(mut st) = conn.prepare_cached(
            "SELECT word FROM headword WHERE norm >= ?1 AND norm < ?2
             ORDER BY freq_rank IS NULL, freq_rank, length(word) LIMIT 10",
        ) {
            if let Ok(rows) = st.query_map(params![q, upper], |r| r.get::<_, String>(0)) {
                en.extend(rows.flatten().map(|w| Suggestion { label: w.clone(), key: w, note: None }));
            }
        }
        // dạng biến đổi gõ đủ (went, children) → gợi ý từ gốc ở đầu danh sách
        if let Ok(mut st) = conn.prepare_cached(
            "SELECT DISTINCT l.headword FROM lookup_index l JOIN headword h ON h.word = l.headword
             WHERE l.form_norm = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 3",
        ) {
            if let Ok(rows) = st.query_map(params![q], |r| r.get::<_, String>(0)) {
                let mut front: Vec<Suggestion> = rows
                    .flatten()
                    .filter(|l| norm(l) != q)
                    .map(|l| Suggestion { label: raw.trim().to_lowercase(), key: l.clone(), note: Some(format!("→ {l}")) })
                    .collect();
                front.append(&mut en);
                en = front;
            }
        }
        let mut vi: Vec<Suggestion> = vec![];
        if let Ok(mut st) = conn.prepare_cached(
            "SELECT word FROM vi_headword WHERE norm >= ?1 AND norm < ?2
             ORDER BY (norm = ?1) DESC, n_links + 3 * has_wikt DESC, length(word) LIMIT 8",
        ) {
            if let Ok(rows) = st.query_map(params![q, upper], |r| r.get::<_, String>(0)) {
                vi.extend(rows.flatten().map(|w| Suggestion {
                    label: w.clone(),
                    key: format!("vi:{w}"),
                    note: Some("Việt".into()),
                }));
            }
        }
        let vi_first = mode == "vien" || looks_vietnamese(raw);
        let mut out = if vi_first {
            vi.extend(en);
            vi
        } else {
            en.truncate(7);
            en.extend(vi);
            en
        };
        out.truncate(10);
        out
    }

    /// Tra (U02–U05, U24): khoá "vi:<từ>" hoặc chế độ Việt–Anh / chuỗi có dấu → ưu tiên tiếng Việt.
    pub fn lookup(&self, raw: &str, mode: &str) -> View {
        let forced_vi = raw.starts_with("vi:");
        let raw = raw.strip_prefix("vi:").unwrap_or(raw);
        let q = clean_query(raw);
        if q.is_empty() {
            return View::Empty;
        }
        let conn = self.conn.lock().unwrap();
        let want_vi = forced_vi || mode == "vien" || looks_vietnamese(&q);
        let vi = Self::vi_resolve(&conn, &q);
        // chuỗi có dấu tiếng Việt không đem bỏ dấu để so với từ tiếng Anh (bàn ≠ ban)
        let en = if forced_vi || looks_vietnamese(&q) { None } else { Self::en_resolve(&conn, &q) };
        if want_vi {
            if let Some(mut v) = vi {
                if let (View::Vi { also_en, .. }, Some(View::En { word, .. })) = (&mut v, &en) {
                    *also_en = Some(word.clone());
                }
                return v;
            }
        }
        if let Some(mut e) = en {
            if let View::En { also_vi, .. } = &mut e {
                *also_vi = match &vi {
                    Some(View::Vi { word, .. }) => Some(word.clone()),
                    Some(View::Choice { lang, .. }) if lang == "vi" => Some(q.clone()),
                    _ => None,
                };
            }
            return e;
        }
        if let Some(v) = vi {
            return v;
        }
        let lower = q.to_lowercase();
        let suggestions = if want_vi { vec![] } else { self.fuzzy(&conn, &lower) };
        View::None { query: q.clone(), suggestions }
    }

    fn vi_resolve(conn: &Connection, q: &str) -> Option<View> {
        let lower = q.to_lowercase();
        // gõ không dấu (U04): "nha" → cho chọn nhà, nhá, nhả… kể cả khi có mục "nha"
        if !looks_vietnamese(q) {
            let same: Vec<String> = conn
                .prepare_cached(
                    "SELECT word FROM vi_headword WHERE norm = ?1 ORDER BY n_links + 3 * has_wikt DESC, word LIMIT 16",
                )
                .and_then(|mut st| st.query_map(params![norm(q)], |r| r.get(0)).map(|rows| rows.flatten().collect()))
                .unwrap_or_default();
            if same.len() > 1 {
                return Some(View::Choice { query: q.to_string(), words: same, lang: "vi".into() });
            }
        }
        let exact: Option<String> = conn
            .query_row("SELECT word FROM vi_headword WHERE word = ?1", params![lower], |r| r.get(0))
            .optional()
            .ok()
            .flatten();
        if let Some(word) = exact {
            return Some(View::Vi { word, also_en: None });
        }
        // gõ không dấu (U04): "nha" → nhà, nhá, nhả…
        let same: Vec<String> = conn
            .prepare_cached("SELECT word FROM vi_headword WHERE norm = ?1 ORDER BY n_links + 3 * has_wikt DESC, word LIMIT 16")
            .and_then(|mut st| st.query_map(params![norm(q)], |r| r.get(0)).map(|rows| rows.flatten().collect()))
            .unwrap_or_default();
        match same.len() {
            0 => None,
            1 => Some(View::Vi { word: same[0].clone(), also_en: None }),
            _ => Some(View::Choice { query: q.to_string(), words: same, lang: "vi".into() }),
        }
    }

    fn en_resolve(conn: &Connection, q: &str) -> Option<View> {
        let lower = q.to_lowercase();
        let qn = norm(q);
        let exists = |w: &str| -> bool {
            conn.query_row("SELECT 1 FROM headword WHERE word = ?1", params![w], |_| Ok(()))
                .optional()
                .ok()
                .flatten()
                .is_some()
        };
        if exists(q) {
            return Some(View::En { word: q.to_string(), via: None, also_vi: None });
        }
        if exists(&lower) {
            return Some(View::En { word: lower, via: None, also_vi: None });
        }
        // dạng biến đổi / biến thể chính tả
        let via: Option<(String, String, String)> = conn
            .query_row(
                "SELECT l.headword, l.relation, l.tags FROM lookup_index l JOIN headword h ON h.word = l.headword
                 WHERE l.form_norm = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 1",
                params![qn],
                |r| Ok((r.get(0)?, r.get(1)?, r.get::<_, Option<String>>(2)?.unwrap_or_default())),
            )
            .optional()
            .ok()
            .flatten();
        if let Some((lemma, relation, tags)) = via {
            return Some(View::En {
                word: lemma.clone(),
                via: Some(Via { form: lower, lemma, relation, tags }),
                also_vi: None,
            });
        }
        // khác chữ hoa / dấu (cafe → café, english → English)
        let same: Vec<String> = conn
            .prepare_cached("SELECT word FROM headword WHERE norm = ?1 ORDER BY freq_rank IS NULL, freq_rank LIMIT 6")
            .and_then(|mut st| st.query_map(params![qn], |r| r.get(0)).map(|rows| rows.flatten().collect()))
            .unwrap_or_default();
        match same.len() {
            0 => None,
            1 => Some(View::En { word: same[0].clone(), via: None, also_vi: None }),
            _ => Some(View::Choice { query: q.to_string(), words: same, lang: "en".into() }),
        }
    }

    /// Mục Việt–Anh (U24): từ tiếng Anh tương ứng + nghĩa Wiktionary + câu song ngữ.
    pub fn vi_entry(&self, word: &str) -> Option<ViEntry> {
        let conn = self.conn.lock().unwrap();
        let en: Vec<ViHit> = conn
            .prepare_cached(
                "SELECT headword, pos, guideword, definition, source, max(weight) w, min(freq_rank) r
                 FROM vi_link WHERE vi = ?1 GROUP BY headword, pos, coalesce(guideword, '')
                 ORDER BY w DESC, r IS NULL, r LIMIT 40",
            )
            .ok()?
            .query_map(params![word], |r| {
                Ok(ViHit {
                    headword: r.get(0)?,
                    pos: r.get(1)?,
                    guideword: r.get(2)?,
                    definition: r.get::<_, Option<String>>(3)?.unwrap_or_default(),
                    source: r.get(4)?,
                })
            })
            .ok()?
            .flatten()
            .collect();
        let mut wikt: Vec<ViSense> = vec![];
        if let Ok(mut st) = conn.prepare_cached("SELECT pos, gloss FROM vi_sense WHERE word = ?1 ORDER BY rowid") {
            for (pos, g) in st
                .query_map(params![word], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
                .into_iter()
                .flatten()
                .flatten()
            {
                match wikt.last_mut() {
                    Some(last) if last.pos == pos => last.glosses.push(g),
                    _ => wikt.push(ViSense { pos, glosses: vec![g] }),
                }
            }
        }
        if en.is_empty() && wikt.is_empty() {
            return None;
        }
        // câu song ngữ có chứa đúng từ này (khớp theo ranh giới từ)
        let mut tatoeba = vec![];
        if let Ok(mut st) =
            conn.prepare_cached("SELECT en, vi FROM tatoeba WHERE vi LIKE '%' || ?1 || '%' ORDER BY length(en) LIMIT 80")
        {
            for (en_s, vi_s) in st
                .query_map(params![word], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
                .into_iter()
                .flatten()
                .flatten()
            {
                let v = vi_s.to_lowercase();
                let hit = v.match_indices(word).any(|(i, m)| {
                    let before = v[..i].chars().last().map_or(true, |c| !c.is_alphabetic());
                    let after = v[i + m.len()..].chars().next().map_or(true, |c| !c.is_alphabetic());
                    before && after
                });
                if hit && tatoeba.len() < 5 {
                    tatoeba.push(Example { en: en_s, vi: Some(vi_s) });
                }
            }
        }
        Some(ViEntry { word: word.to_string(), en, wikt, tatoeba })
    }

    /// Gợi ý gần đúng chính tả: lấy ứng viên bằng FTS5 trigram, xếp bằng Damerau + tần suất.
    fn fuzzy(&self, conn: &Connection, q: &str) -> Vec<Candidate> {
        let chars: Vec<char> = q.chars().filter(|c| c.is_alphabetic()).collect();
        if chars.len() < 3 {
            return vec![];
        }
        let grams: Vec<String> = chars
            .windows(3)
            .map(|w| format!("\"{}\"", w.iter().collect::<String>()))
            .collect::<HashSet<_>>()
            .into_iter()
            .collect();
        let sql = "SELECT f.word, h.freq_rank FROM fts_headword f JOIN headword h ON h.word = f.word
                   WHERE fts_headword MATCH ?1 ORDER BY rank LIMIT 600";
        let mut cands: Vec<(usize, i64, String)> = vec![];
        if let Ok(mut st) = conn.prepare(sql) {
            if let Ok(rows) = st.query_map(params![grams.join(" OR ")], |r| {
                Ok((r.get::<_, String>(0)?, r.get::<_, Option<i64>>(1)?))
            }) {
                for (w, rank) in rows.flatten() {
                    let wl = w.to_lowercase();
                    if (wl.chars().count() as i64 - chars.len() as i64).abs() > 2 {
                        continue;
                    }
                    let d = damerau(q, &wl);
                    if d <= 2 {
                        cands.push((d, rank.unwrap_or(i64::MAX), w));
                    }
                }
            }
        }
        // Từ ngắn gõ đảo chữ (bnak) không chung cụm 3 chữ nào với từ đúng (bank) → thêm mọi biến thể sai 1 lỗi.
        let known = edits1(q);
        for chunk in known.chunks(500) {
            let ph = vec!["?"; chunk.len()].join(",");
            let sql = format!("SELECT word, freq_rank FROM headword WHERE word IN ({ph})");
            if let Ok(mut st) = conn.prepare(&sql) {
                if let Ok(rows) = st.query_map(rusqlite::params_from_iter(chunk.iter()), |r| {
                    Ok((r.get::<_, String>(0)?, r.get::<_, Option<i64>>(1)?))
                }) {
                    for (w, rank) in rows.flatten() {
                        cands.push((damerau(q, &w), rank.unwrap_or(i64::MAX), w));
                    }
                }
            }
        }
        cands.sort();
        cands.dedup_by(|a, b| a.2 == b.2);
        cands.into_iter().take(10).map(|(_, _, w)| Candidate { word: w, available: true }).collect()
    }

    pub fn entry(&self, word: &str) -> Option<Entry> {
        let conn = self.conn.lock().unwrap();
        type Row = (i64, String, String, Option<i64>, Option<String>, Option<String>, Option<String>, Option<String>, String);
        let rows: Vec<Row> = conn
            .prepare_cached(
                "SELECT id, pos, entry_type, freq_rank, freq_band, cefr, etymology, ai_model, tier
                 FROM entry WHERE headword = ?1 ORDER BY ai_model IS NULL, ord",
            )
            .ok()?
            .query_map(params![word], |r| {
                Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?, r.get(5)?, r.get(6)?, r.get(7)?, r.get(8)?))
            })
            .ok()?
            .flatten()
            .collect();
        if rows.is_empty() {
            return None;
        }
        let mut ipa = Ipa::default();
        let mut blocks = vec![];
        let mut referenced: HashSet<String> = HashSet::new();
        for (id, pos, entry_type, _, _, cefr, etym, model, _) in &rows {
            if let Ok(mut st) = conn.prepare_cached("SELECT accent, ipa FROM pronunciation WHERE entry_id = ?1") {
                for (acc, p) in st
                    .query_map(params![id], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
                    .into_iter()
                    .flatten()
                    .flatten()
                {
                    if acc == "uk" && ipa.uk.is_none() {
                        ipa.uk = Some(p);
                    } else if acc == "us" && ipa.us.is_none() {
                        ipa.us = Some(p);
                    }
                }
            }
            let forms: Vec<Form> = conn
                .prepare_cached("SELECT form, tags FROM form WHERE entry_id = ?1 ORDER BY ord")
                .and_then(|mut st| {
                    st.query_map(params![id], |r| {
                        Ok(Form {
                            form: r.get(0)?,
                            tags: r
                                .get::<_, Option<String>>(1)?
                                .unwrap_or_default()
                                .split_whitespace()
                                .map(String::from)
                                .collect(),
                        })
                    })
                    .map(|rows| rows.flatten().collect())
                })
                .unwrap_or_default();
            // ví dụ của mọi nghĩa trong mục
            let mut ex_by_sense: HashMap<i64, Vec<(String, Option<String>)>> = HashMap::new();
            if let Ok(mut st) = conn.prepare_cached(
                "SELECT x.sense_id, x.text_en, x.text_vi FROM example x JOIN sense s ON s.id = x.sense_id
                 WHERE s.entry_id = ?1 ORDER BY x.sense_id, x.ord",
            ) {
                for (sid, en, vi) in st
                    .query_map(params![id], |r| Ok((r.get::<_, i64>(0)?, r.get::<_, String>(1)?, r.get::<_, Option<String>>(2)?)))
                    .into_iter()
                    .flatten()
                    .flatten()
                {
                    ex_by_sense.entry(sid).or_default().push((en, vi));
                }
            }
            let mut senses = vec![];
            let mut wikt = vec![];
            if let Ok(mut st) = conn.prepare_cached(
                "SELECT id, layer, guideword, grammar, labels, definition, cefr, vi, vi_from_wikt
                 FROM sense WHERE entry_id = ?1 ORDER BY layer DESC, ord",
            ) {
                let it = st.query_map(params![id], |r| {
                    Ok((
                        r.get::<_, i64>(0)?,
                        r.get::<_, String>(1)?,
                        r.get::<_, Option<String>>(2)?,
                        r.get::<_, Option<String>>(3)?,
                        r.get::<_, Option<String>>(4)?,
                        r.get::<_, String>(5)?,
                        r.get::<_, Option<String>>(6)?,
                        r.get::<_, Option<String>>(7)?,
                        r.get::<_, Option<i64>>(8)?,
                    ))
                });
                for (sid, layer, gw, gram, labels, def, scefr, vi, viok) in it.into_iter().flatten().flatten() {
                    let exs = ex_by_sense.remove(&sid).unwrap_or_default();
                    if layer == "learner" {
                        senses.push(LearnerSense {
                            guideword: s(gw),
                            grammar: s(gram),
                            labels: s(labels),
                            definition: def,
                            cefr: scefr,
                            vi,
                            vi_ok: viok.unwrap_or(0) == 1,
                            examples: exs.into_iter().map(|(en, vi)| Example { en, vi }).collect(),
                        });
                    } else {
                        wikt.push(WiktSense {
                            gloss: def,
                            grammar: s(gram),
                            labels: s(labels),
                            examples: exs.into_iter().map(|(en, _)| en).collect(),
                            vi,
                        });
                    }
                }
            }
            let thesaurus: Vec<ThesGroup> = conn
                .prepare_cached("SELECT definition, members, hypernyms FROM thesaurus WHERE entry_id = ?1 ORDER BY ord")
                .and_then(|mut st| {
                    st.query_map(params![id], |r| {
                        let m: String = r.get(1)?;
                        let h: String = r.get(2)?;
                        Ok(ThesGroup {
                            definition: r.get::<_, Option<String>>(0)?.unwrap_or_default(),
                            members: serde_json::from_str(&m).unwrap_or_default(),
                            hypernym: serde_json::from_str(&h).unwrap_or_default(),
                        })
                    })
                    .map(|rows| rows.flatten().collect())
                })
                .unwrap_or_default();
            let antonyms: Vec<String> = conn
                .prepare_cached("SELECT DISTINCT word FROM antonym WHERE entry_id = ?1")
                .and_then(|mut st| st.query_map(params![id], |r| r.get(0)).map(|rows| rows.flatten().collect()))
                .unwrap_or_default();
            for g in &thesaurus {
                referenced.extend(g.members.iter().cloned());
            }
            let vi_block: Vec<String> = conn
                .prepare_cached("SELECT text FROM vi_block WHERE entry_id = ?1 ORDER BY ord")
                .and_then(|mut st| st.query_map(params![id], |r| r.get(0)).map(|rows| rows.flatten().collect()))
                .unwrap_or_default();
            let translations: Vec<TrGroup> = conn
                .prepare_cached("SELECT header, words FROM translation_group WHERE entry_id = ?1")
                .and_then(|mut st| {
                    st.query_map(params![id], |r| Ok(TrGroup { header: r.get(0)?, words: r.get(1)? }))
                        .map(|rows| rows.flatten().collect())
                })
                .unwrap_or_default();
            referenced.extend(antonyms.iter().cloned());
            blocks.push(Block {
                pos: pos.clone(),
                entry_type: entry_type.clone(),
                model: model.clone(),
                cefr: cefr.clone(),
                forms,
                senses,
                wiktionary: wikt,
                thesaurus,
                antonyms,
                etymology: etym.clone(),
                vi_block,
                translations,
            });
        }

        let mut phrasal_verbs = vec![];
        let mut idioms = vec![];
        if let Ok(mut st) = conn.prepare_cached(
            "SELECT phrase, kind, gloss FROM phrase_link WHERE headword = ?1 AND phrase <> ?1 ORDER BY popularity DESC",
        ) {
            for (p, kind, gloss) in st
                .query_map(params![word.to_lowercase()], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get::<_, String>(2)?)))
                .into_iter()
                .flatten()
                .flatten()
            {
                let target = if kind == "phrasal_verb" { &mut phrasal_verbs } else { &mut idioms };
                if target.len() < 20 {
                    referenced.insert(p.clone());
                    target.push(Phrase { phrase: p, gloss });
                }
            }
        }
        let family: Vec<String> = conn
            .prepare_cached(
                "SELECT DISTINCT f.member FROM family f JOIN headword h ON h.word = f.member
                 WHERE f.headword = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 24",
            )
            .and_then(|mut st| st.query_map(params![word], |r| r.get(0)).map(|rows| rows.flatten().collect()))
            .unwrap_or_default();
        referenced.extend(family.iter().cloned());

        let n = norm(word);
        let mut before: Vec<String> = conn
            .prepare_cached("SELECT word FROM headword WHERE freq_rank IS NOT NULL AND norm < ?1 ORDER BY norm DESC LIMIT 6")
            .and_then(|mut st| st.query_map(params![n], |r| r.get(0)).map(|rows| rows.flatten().collect()))
            .unwrap_or_default();
        before.reverse();
        let after: Vec<String> = conn
            .prepare_cached("SELECT word FROM headword WHERE freq_rank IS NOT NULL AND norm > ?1 ORDER BY norm LIMIT 6")
            .and_then(|mut st| st.query_map(params![n], |r| r.get(0)).map(|rows| rows.flatten().collect()))
            .unwrap_or_default();
        let nearby: Vec<String> = before.into_iter().chain(after).collect();
        referenced.extend(nearby.iter().cloned());

        let mut known = vec![];
        let refs: Vec<String> = referenced.into_iter().collect();
        for chunk in refs.chunks(500) {
            let ph = vec!["?"; chunk.len()].join(",");
            let sql = format!("SELECT word FROM headword WHERE word IN ({ph})");
            if let Ok(mut st) = conn.prepare(&sql) {
                if let Ok(rows) = st.query_map(rusqlite::params_from_iter(chunk.iter()), |r| r.get::<_, String>(0)) {
                    known.extend(rows.flatten());
                }
            }
        }

        let tatoeba: Vec<Example> = conn
            .prepare_cached(
                "SELECT t.en, t.vi FROM tatoeba_word w JOIN tatoeba t ON t.id = w.tid WHERE w.headword = ?1 ORDER BY t.id",
            )
            .and_then(|mut st| {
                st.query_map(params![word], |r| Ok(Example { en: r.get(0)?, vi: r.get(1)? }))
                    .map(|rows| rows.flatten().collect())
            })
            .unwrap_or_default();
        let first = &rows[0];
        Some(Entry {
            word: word.to_string(),
            rank: rows.iter().find_map(|r| r.3),
            band: rows.iter().find_map(|r| r.4.clone()),
            tier: Some(first.8.clone()),
            ipa,
            blocks,
            phrasal_verbs,
            idioms,
            family,
            nearby,
            tatoeba,
            known,
        })
    }

    pub fn exists(&self, word: &str) -> bool {
        let conn = self.conn.lock().unwrap();
        conn.query_row("SELECT 1 FROM headword WHERE word = ?1", params![word], |_| Ok(()))
            .optional()
            .ok()
            .flatten()
            .is_some()
    }

    pub fn sources(&self) -> Vec<Source> {
        let conn = self.conn.lock().unwrap();
        conn.prepare("SELECT id, name, license, attribution, url, retrieved_at FROM source ORDER BY rowid")
            .and_then(|mut st| {
                st.query_map([], |r| {
                    Ok(Source {
                        id: r.get(0)?,
                        name: r.get(1)?,
                        license: r.get(2)?,
                        attribution: r.get(3)?,
                        url: r.get(4)?,
                        retrieved_at: r.get(5)?,
                    })
                })
                .map(|rows| rows.flatten().collect())
            })
            .unwrap_or_default()
    }

    pub fn counts(&self) -> HashMap<String, i64> {
        let conn = self.conn.lock().unwrap();
        let mut m = HashMap::new();
        for (k, sql) in [
            ("headwords", "SELECT count(*) FROM headword"),
            ("entries", "SELECT count(*) FROM entry"),
            ("entries_ai", "SELECT count(*) FROM entry WHERE ai_model IS NOT NULL"),
            ("vi_headwords", "SELECT count(*) FROM vi_headword"),
        ] {
            if let Ok(n) = conn.query_row(sql, [], |r| r.get(0)) {
                m.insert(k.to_string(), n);
            }
        }
        m
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn norm_strips_marks() {
        assert_eq!(norm("Nhà Đẹp"), "nha dep");
        assert_eq!(norm("café"), "cafe");
    }

    #[test]
    fn sqlite_uri_from_paths() {
        let u = |s: &str| sqlite_file_uri(Path::new(s));
        if cfg!(windows) {
            // đúng kiểu đường dẫn bản cài nhận từ resource_dir()
            assert_eq!(
                u(r"\\?\C:\Users\x\AppData\Local\ECALD\dict-core.sqlite"),
                "file:///C:/Users/x/AppData/Local/ECALD/dict-core.sqlite"
            );
            assert_eq!(
                u(r"\\?\C:\Users\x\AppData\Local\EC Advanced Learners’ Dictionary\dict-core.sqlite"),
                "file:///C:/Users/x/AppData/Local/EC%20Advanced%20Learners%E2%80%99%20Dictionary/dict-core.sqlite"
            );
            assert_eq!(u(r"C:\a #1\50% off\b?.sqlite"), "file:///C:/a%20%231/50%25%20off/b%3F.sqlite");
            assert_eq!(u(r"\\?\UNC\server\share\d.sqlite"), "file:////server/share/d.sqlite");
            assert_eq!(u(r"\\server\share\d.sqlite"), "file:////server/share/d.sqlite");
        }
        assert_eq!(u("/home/x/d b.sqlite"), "file:///home/x/d%20b.sqlite");
        assert_eq!(u("data/d.sqlite"), "file:data/d.sqlite");
        // không còn ký tự đặc biệt của URI ngoài phần tiền tố
        let s = u("/a?b#c%d");
        assert!(!s["file:".len()..].contains(['?', '#']) && s.ends_with("a%3Fb%23c%25d"));
    }

    /// Tạo một dict-core.sqlite tí hon trong thư mục có dấu cách, ’, #, % rồi mở qua đường dẫn
    /// đã canonicalize (trên Windows là dạng \\?\C:\…) — đúng đường đi của bản cài.
    #[test]
    fn open_dict_from_verbatim_path_with_special_chars() {
        let stamp = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let dir = std::env::temp_dir().join(format!("tudien-test {stamp} EC Learners’ #1 50%"));
        std::fs::create_dir_all(&dir).unwrap();
        let file = dir.join("dict-core.sqlite");
        {
            let c = Connection::open(&file).unwrap();
            c.execute_batch(
                "CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                 INSERT INTO meta VALUES('schema_version', '2'), ('built_at', 'test');",
            )
            .unwrap();
        }
        let canon = std::fs::canonicalize(&file).unwrap();
        if cfg!(windows) {
            assert!(canon.to_string_lossy().starts_with(r"\\?\"), "{}", canon.display());
            // cách ghép URI cũ đúng là hỏng với đường dẫn này (lỗi người dùng gặp)
            let old = format!("file:{}?immutable=1", canon.display().to_string().replace('\\', "/"));
            assert!(Connection::open_with_flags(&old, OpenFlags::SQLITE_OPEN_READ_ONLY | OpenFlags::SQLITE_OPEN_URI)
                .is_err());
        }
        let r = Dict::open(&canon);
        let d = r.unwrap_or_else(|e| panic!("mở không được: {e}"));
        assert_eq!(d.meta.get("built_at").map(String::as_str), Some("test"));
        {
            // vẫn chỉ đọc (quy tắc CANNOT): ghi phải lỗi
            let c = d.conn.lock().unwrap();
            assert!(c.execute_batch("CREATE TABLE x(a)").is_err());
            let f: String = c.query_row("PRAGMA database_list", [], |r| r.get(2)).unwrap();
            assert!(f.ends_with("dict-core.sqlite") && f.contains("Learners’ #1 50%"), "{f}");
        }
        drop(d);
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn damerau_transposition() {
        assert_eq!(damerau("recieve", "receive"), 1);
        assert_eq!(damerau("bnak", "bank"), 1);
    }
}
