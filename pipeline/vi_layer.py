"""Lớp tiếng Việt cho build_db.py (vòng 2: UC-U22, U24, U25, U04).

Nguồn nghĩa Việt của một mục tiếng Anh, theo thứ tự ưu tiên:
  1. AI gắn cho từng nghĩa (sense.vi, layer learner)
  2. bảng dịch theo nghĩa của Wiktionary tiếng Anh → gắn vào nghĩa Wiktionary khớp nhất (sense.vi, layer full)
  3. khối nghĩa theo từ loại của Wiktionary tiếng Việt (bảng vi_block)
Việt–Anh = mục tiếng Việt của Wiktionary tiếng Anh (vi_sense) + chỉ mục đảo ngược từ 3 nguồn trên (vi_link).
"""
import bz2
import gzip
import json
import re
import unicodedata
from pathlib import Path

from enrich_sample import norm_pos

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff]")
SKIP_VI_POS = {"name", "character", "romanization", "symbol", "punct", "affix", "suffix", "prefix"}
STOP = {"a", "an", "the", "of", "to", "in", "on", "or", "and", "for", "with", "by", "at", "as", "from", "that",
        "which", "who", "something", "someone", "one", "be", "is", "used", "etc"}
WEIGHT = {"ai": 3, "wiktionary": 2, "viwikt": 1}

SCHEMA = """
CREATE TABLE vi_block(entry_id INTEGER, ord INTEGER, text TEXT);
CREATE TABLE translation_group(entry_id INTEGER, header TEXT, words TEXT);
CREATE TABLE vi_headword(word TEXT PRIMARY KEY, norm TEXT, n_links INTEGER, has_wikt INTEGER) WITHOUT ROWID;
CREATE TABLE vi_sense(word TEXT, ord INTEGER, pos TEXT, gloss TEXT);
CREATE TABLE vi_link(vi TEXT, headword TEXT, pos TEXT, guideword TEXT, definition TEXT, source TEXT, weight INTEGER,
  freq_rank INTEGER);
CREATE TABLE tatoeba(id INTEGER PRIMARY KEY, en TEXT, vi TEXT);
CREATE TABLE tatoeba_word(headword TEXT, tid INTEGER);
"""
INDEXES = """
CREATE INDEX vi_block_entry ON vi_block(entry_id);
CREATE INDEX trg_entry ON translation_group(entry_id);
CREATE INDEX vi_head_norm ON vi_headword(norm);
CREATE INDEX vi_sense_word ON vi_sense(word);
CREATE INDEX vi_link_vi ON vi_link(vi);
CREATE INDEX tatoeba_head ON tatoeba_word(headword);
"""


def vnorm(s):
    s = s.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").strip()


def vi_terms(text, max_words=4):
    """Tách một nghĩa tiếng Việt kiểu từ điển ("Bờ (sông, hồ...)."; "ngân hàng; nhà băng") thành các từ ngắn."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    out = []
    for part in re.split(r"[;,/]| hoặc ", text):
        t = re.sub(r"[.…!?:\"“”'‘’\-–~]+", " ", part).strip().lower()
        t = re.sub(r"\s+", " ", t)
        # chỉ giữ cụm ngắn toàn chữ cái (tiếng Việt), bỏ câu giải thích dài và mảnh có số / ký hiệu
        if t and 1 <= len(t.split()) <= max_words and re.fullmatch(r"[^\W\d_]+( [^\W\d_]+)*", t):
            out.append(t)
    return list(dict.fromkeys(out))


def load_viwikt():
    """→ (tập từ tiếng Anh có nghĩa Việt, {(từ, từ loại): [nghĩa Việt]})."""
    words, blocks = set(), {}
    with gzip.open(RAW / "viwikt-raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") != "en" or not d.get("senses"):
                continue
            words.add(d["word"])
            gl = [g.strip() for s in d["senses"] for g in s.get("glosses") or [] if g.strip()]
            if gl:
                blocks.setdefault((d["word"], norm_pos(d.get("pos"))), []).extend(gl)
    return words, blocks


def vi_translations(d, raw_senses):
    """Bản dịch tiếng Việt (code vi) trong bảng dịch của Wiktionary EN: [(tiêu đề nghĩa, từ Việt)]."""
    out = [(t.get("sense") or "", t["word"]) for t in d.get("translations") or []
           if t.get("code") == "vi" and t.get("word")]
    for s in raw_senses:
        out += [(t.get("sense") or s["glosses"][-1], t["word"]) for t in s.get("translations") or []
                if t.get("code") == "vi" and t.get("word") and s.get("glosses")]
    return out


def _toks(s):
    return {w for w in re.findall(r"[a-z]+", s.lower()) if w not in STOP and len(w) > 2}


def match_translations(senses, tr):
    """Gắn nhóm bản dịch vào nghĩa Wiktionary có nhiều từ chung nhất với tiêu đề nhóm.
    → (danh sách nghĩa Việt theo chỉ số nghĩa, các nhóm không khớp [(tiêu đề, [từ])])."""
    groups = {}
    for header, word in tr:
        groups.setdefault(header, []).append(word)
    per_sense = [[] for _ in senses]
    unmatched = []
    sense_toks = [_toks(s["gloss"]) for s in senses]
    for header, ws in groups.items():
        h = _toks(header)
        best, score = None, 0.0
        for i, st in enumerate(sense_toks):
            if h and st:
                j = len(h & st) / len(h | st)
                if j > score:
                    best, score = i, j
        if best is not None and score >= 0.25:
            per_sense[best] += ws
        else:
            unmatched.append((header, ws))
    return ["; ".join(dict.fromkeys(x)) or None for x in per_sense], unmatched


def load_kaikki_vi():
    out = []
    with open(RAW / "kaikki-vi.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            w = d.get("word", "")
            if not w or HAN.search(w) or d.get("pos") in SKIP_VI_POS:
                continue
            gl = [s["glosses"][-1] for s in d.get("senses") or []
                  if s.get("glosses") and not ({"form-of", "alt-of", "obsolete"} & set(s.get("tags") or []))]
            if gl:
                out.append((w.lower(), norm_pos(d.get("pos")), gl[:8]))
    return out


def tatoeba_pairs():
    vie = {}
    with bz2.open(RAW / "tatoeba-vie.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            i, _, text = line.rstrip("\n").split("\t", 2)
            vie[i] = text
    links = {}
    with bz2.open(RAW / "tatoeba-vie-eng-links.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            a, b = line.split()[:2]
            if a in vie:
                links.setdefault(b, a)
    pairs = []
    with bz2.open(RAW / "tatoeba-eng.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            i, _, text = line.rstrip("\n").split("\t", 2)
            if i in links and len(text) <= 120:
                pairs.append((text, vie[links[i]]))
    return pairs


def write(con, links, kaikki_vi, pairs, lemma_of, headwords, rank, max_per_word=6):
    """Ghi bảng Việt–Anh và Tatoeba. links: [(vi, headword, pos, guideword, definition, source)]."""
    n_links = {}
    for vi, hw, pos, gw, d, src in links:
        con.execute("INSERT INTO vi_link VALUES(?,?,?,?,?,?,?,?)",
                    (vi, hw, pos, gw, d, src, WEIGHT[src], rank.get(hw)))
        n_links[vi] = n_links.get(vi, 0) + 1
    wikt_words = set()
    for w, pos, gl in kaikki_vi:
        wikt_words.add(w)
        for i, g in enumerate(gl):
            con.execute("INSERT INTO vi_sense VALUES(?,?,?,?)", (w, i, pos, g))
    for w in set(n_links) | wikt_words:
        con.execute("INSERT INTO vi_headword VALUES(?,?,?,?)", (w, vnorm(w), n_links.get(w, 0), int(w in wikt_words)))
    # Tatoeba: gắn câu vào từ tiếng Anh (cả dạng biến đổi → từ gốc), giữ các câu ngắn nhất
    by_word = {}
    for tid, (en, vi) in enumerate(sorted(pairs, key=lambda p: len(p[0])), 1):
        con.execute("INSERT INTO tatoeba VALUES(?,?,?)", (tid, en, vi))
        for tok in set(re.findall(r"[a-z][a-z']*", en.lower())):
            hw = tok if tok in headwords else lemma_of.get(tok)
            if hw and len(by_word.setdefault(hw, [])) < max_per_word:
                by_word[hw].append(tid)
    for hw, tids in by_word.items():
        for t in tids:
            con.execute("INSERT INTO tatoeba_word VALUES(?,?)", (hw, t))
    return len(set(n_links) | wikt_words)
