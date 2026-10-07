"""Dựng cơ sở dữ liệu từ điển lõi dict-core.sqlite (UC-M02, vòng 1: phần tiếng Anh).

Dùng: python pipeline/build_db.py   → data/build/dict-core.sqlite + data/build/report.json

Phạm vi mục từ (headword, từ loại):
  tầng A = 20.000 từ thông dụng (có bản AI khi lô đã chạy xong ở data/work/enrich/)
  tầng B = từ có thứ hạng tần suất, hoặc có nghĩa trong Wiktionary tiếng Việt, hoặc là cụm động từ / thành ngữ
           chứa một từ tầng A, hoặc được dịch sang ≥ 5 ngôn ngữ (đại diện cho mức phổ biến)
Nội dung AI luôn ở dòng riêng (is_ai=1), không ghi đè nghĩa Wiktionary (layer 'full').
"""
import csv
import gzip
import json
import re
import sqlite3
import sys
import time
import tomllib
import unicodedata
from collections import defaultdict
from pathlib import Path

from build_proto import cefr_table, clean_etym, oewn
from enrich_sample import SKIP_TAGS, norm_pos, validate
import vi_layer
from ipa_ecdict import ecdict_to_ipa

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(1 << 30)
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
BUILD = ROOT / "data" / "build"
DB = BUILD / "dict-core.sqlite"
SCHEMA_VERSION = 2  # 2: thêm lớp tiếng Việt (vòng 2)

SKIP_POS = {"name", "character", "symbol", "romanization", "punct"}
PHRASE_POS = {"verb", "phrase", "prep_phrase", "adv", "adj", "intj", "proverb", "conj", "prep"}
PARTICLES = {"up", "down", "off", "out", "in", "on", "away", "back", "over", "through", "about", "around",
             "along", "by", "for", "with", "into", "across", "after", "apart", "ahead", "forward", "to", "at",
             "behind", "together", "round", "under", "upon", "from", "against", "onto", "aside"}
UK = {"UK", "Received-Pronunciation", "British"}
US = {"US", "General-American"}
GRAMMAR = {"countable": "C", "uncountable": "U", "transitive": "T", "intransitive": "I", "plural": "pl.",
           "singular": "sing.", "ditransitive": "T", "ergative": "I, T", "usually-plural": "usually pl.",
           "attributive": "only before noun", "predicative": "not before noun"}
LABELS = {"formal", "informal", "slang", "colloquial", "dated", "rare", "figuratively", "humorous", "derogatory",
          "offensive", "vulgar", "literary", "poetic", "British", "UK", "US", "Australia", "Canada", "Ireland",
          "Scotland", "India", "New-Zealand", "South-Africa", "Internet", "euphemistic", "nonstandard",
          "childish", "law", "medicine", "mathematics", "computing", "business", "sports", "music", "biology",
          "chemistry", "physics", "finance", "military", "nautical", "religion", "technical"}
WORD_RE = re.compile(r"^[A-Za-z][A-Za-z'\-\.]*( [A-Za-z][A-Za-z'\-\.]*)*$")


def norm(s):
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn").strip()


def ipa_clean(s):
    # ɹ → r như từ điển người học; vài phiên âm Wiktionary gõ dấu nhấn/trường âm bằng ký tự ASCII ' và :
    return s.replace("ɹ", "r").replace("'", "ˈ").replace(":", "ː") if s else s


def load_ranks():
    rank, phon = {}, {}
    with open(RAW / "ecdict.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):  # chỉ đọc word, phonetic, bnc, frq (các cột khác bị cấm, xem sources.toml)
            w = row["word"]
            if row["phonetic"]:
                phon.setdefault(w, row["phonetic"])
            vals = [int(v) for v in (row["bnc"], row["frq"]) if v and v != "0"]
            if vals:
                rank[w] = min(vals + [rank.get(w, 10**9)])
    ordered = sorted(rank, key=rank.get)
    return {w: i + 1 for i, w in enumerate(ordered)}, phon


def tier_a_words():
    plan = json.loads((WORK / "tierA-batches.json").read_text(encoding="utf-8"))
    return [w for b in sorted(plan["batches"], key=lambda b: b["rank_first"]) for w in b["words"]]


def load_ai():
    """Kết quả AI đã có (lô đã chạy xong), kiểm lại bằng validate()."""
    src_file = WORK / "tierA-source.json"
    if not src_file.exists():
        return {}
    en_src = json.loads(src_file.read_text(encoding="utf-8"))["en"]
    ai = {}
    for p in sorted((WORK / "enrich").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ok, _ = validate(d["result"], set(d["batch"]["words"]), en_src)
        for e in ok:
            if e["senses"]:
                ai[(e["word"], e["pos"])] = {"model": d["meta"]["model"], "senses": e["senses"]}
    # đợt bổ sung (enrich.py --pass gaps): từ loại bị cắt ở đợt chính → thay kết quả của đúng (từ, từ loại) đó
    gap_src = WORK / "tierA2-source.json"
    if gap_src.exists():
        gap_en = json.loads(gap_src.read_text(encoding="utf-8"))["en"]
        for p in sorted((WORK / "enrich2").glob("*.json")):
            d = json.loads(p.read_text(encoding="utf-8"))
            ok, _ = validate(d["result"], set(d["batch"]["words"]), gap_en)
            for e in ok:
                if e["senses"]:
                    ai[(e["word"], e["pos"])] = {"model": d["meta"]["model"], "senses": e["senses"]}
    return ai


def sense_codes(tags):
    gram = [GRAMMAR[t] for t in tags if t in GRAMMAR]
    labels = [t.replace("-", " ") for t in tags if t in LABELS]
    return (f"[{', '.join(dict.fromkeys(gram))}]" if gram else ""), ", ".join(labels)


def keep_form(fm):
    tags = set(fm.get("tags") or [])
    if tags & {"table-tags", "inflection-template", "obsolete", "archaic", "dialectal", "nonstandard",
               "alternative", "romanization"}:
        return False
    return fm.get("form") not in (None, "", "-", "—")


def scan(tier_a, rank, viwikt_en):
    """Đọc Wiktionary EN một lượt: chọn mục, gom nghĩa, dạng, IPA, quan hệ."""
    tier_a_set = set(tier_a)
    entries = {}  # (word, pos) → dict
    form_of = []  # (form, target, tags, relation)
    phrases = []
    order = 0
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code": "en"' not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != "en" or d.get("pos") in SKIP_POS:
                continue
            w = d["word"]
            if not WORD_RE.match(w):
                continue
            pos = norm_pos(d.get("pos"))
            raw_senses = d.get("senses") or []
            # dạng biến đổi / biến thể chính tả → chỉ mục tra
            for s in raw_senses:
                tags = set(s.get("tags") or [])
                for key, rel in (("form_of", "inflection"), ("alt_of", "variant")):
                    for t in s.get(key) or []:
                        if t.get("word") and t["word"] != w and not tags & {"obsolete", "archaic", "misspelling"}:
                            form_of.append((w, t["word"], sorted(tags - {"form-of", "alt-of"}), rel))
            senses = [s for s in raw_senses if s.get("glosses")
                      and not (set(s.get("tags") or []) & (SKIP_TAGS | {"form-of", "alt-of"}))]
            if not senses:
                continue
            toks = w.split()
            n_tr = len(d.get("translations") or []) + sum(len(s.get("translations") or []) for s in raw_senses)
            is_phrase = len(toks) > 1 and pos in PHRASE_POS and any(t.lower() in tier_a_set for t in toks)
            wanted = (w in tier_a_set or w in rank or w in viwikt_en or is_phrase or n_tr >= 5)
            if not wanted:
                continue
            if is_phrase:
                kind = "phrasal_verb" if (pos == "verb" and len(toks) <= 3 and toks[0].lower() in tier_a_set
                                          and all(t in PARTICLES for t in toks[1:])) else "idiom"
                for t in set(x.lower() for x in toks):
                    if t in tier_a_set:
                        phrases.append((t, w, kind, senses[0]["glosses"][-1], n_tr + 3 * len(senses)))
            key = (w, pos)
            e = entries.get(key)
            if e is None:
                order += 1
                e = entries[key] = {"word": w, "pos": pos, "ord": order, "senses": [], "forms": [], "ipa_uk": None,
                                    "ipa_us": None, "ipa_any": None, "etym": "", "derived": set(), "vi_tr": [],
                                    "entry_type": ("phrasal_verb" if is_phrase and kind == "phrasal_verb"
                                                   else "idiom" if is_phrase else "phrase" if len(toks) > 1
                                                   else "word")}
            for s in senses:
                tags = s.get("tags") or []
                exs = [x["text"] for x in s.get("examples") or []
                       if x.get("text") and x.get("type") != "quotation" and len(x["text"]) <= 200][:2]
                e["senses"].append({"gloss": s["glosses"][-1], "tags": tags, "examples": exs,
                                    "etym": d.get("etymology_number")})
            for fm in d.get("forms") or []:
                if keep_form(fm) and fm["form"] != w and fm["form"] not in [x["form"] for x in e["forms"]]:
                    e["forms"].append({"form": fm["form"], "tags": sorted(set(fm.get("tags") or []) - {"table-tags"}),
                                       "conj": bool(fm.get("source"))})
            for snd in d.get("sounds") or []:
                ipa = snd.get("ipa")
                if not ipa or not ipa.startswith("/"):
                    continue
                tags = set(snd.get("tags") or [])
                if tags & UK and not e["ipa_uk"]:
                    e["ipa_uk"] = ipa
                if tags & US and not e["ipa_us"]:
                    e["ipa_us"] = ipa
                if not tags and not e["ipa_any"]:
                    e["ipa_any"] = ipa
            e["etym"] = e["etym"] or clean_etym(d.get("etymology_text"))
            e["derived"] |= {x["word"] for x in d.get("derived") or [] if x.get("word") and " " not in x["word"]}
            e["vi_tr"] += vi_layer.vi_translations(d, raw_senses)
    return entries, form_of, phrases


SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE source(id TEXT PRIMARY KEY, name TEXT, license TEXT, attribution TEXT, url TEXT, retrieved_at TEXT);
CREATE TABLE entry(id INTEGER PRIMARY KEY, entry_key TEXT UNIQUE, headword TEXT, headword_norm TEXT, pos TEXT,
  ord INTEGER, entry_type TEXT, freq_rank INTEGER, freq_band TEXT, cefr TEXT, cefr_source TEXT, tier TEXT,
  etymology TEXT, ai_model TEXT);
CREATE TABLE headword(word TEXT PRIMARY KEY, norm TEXT, freq_rank INTEGER, tier TEXT) WITHOUT ROWID;
CREATE TABLE pronunciation(entry_id INTEGER, accent TEXT, ipa TEXT, source TEXT);
CREATE TABLE form(entry_id INTEGER, ord INTEGER, form TEXT, tags TEXT);
CREATE TABLE lookup_index(form_norm TEXT, headword TEXT, relation TEXT, tags TEXT);
CREATE TABLE sense(id INTEGER PRIMARY KEY, entry_id INTEGER, layer TEXT, ord INTEGER, guideword TEXT, grammar TEXT,
  labels TEXT, definition TEXT, cefr TEXT, vi TEXT, vi_from_wikt INTEGER, src TEXT, is_ai INTEGER, source TEXT);
CREATE TABLE example(sense_id INTEGER, ord INTEGER, text_en TEXT, text_vi TEXT, is_ai INTEGER, source TEXT);
CREATE TABLE thesaurus(entry_id INTEGER, ord INTEGER, definition TEXT, members TEXT, hypernyms TEXT);
CREATE TABLE antonym(entry_id INTEGER, word TEXT);
CREATE TABLE family(headword TEXT, member TEXT);
CREATE TABLE phrase_link(headword TEXT, phrase TEXT, kind TEXT, gloss TEXT, popularity INTEGER);
CREATE VIRTUAL TABLE fts_headword USING fts5(word, tokenize='trigram remove_diacritics 1');
""" + vi_layer.SCHEMA

INDEXES = """
CREATE INDEX entry_head ON entry(headword);
CREATE INDEX headword_norm ON headword(norm);
CREATE INDEX headword_rank ON headword(freq_rank);
CREATE INDEX pron_entry ON pronunciation(entry_id);
CREATE INDEX form_entry ON form(entry_id);
CREATE INDEX lookup_form ON lookup_index(form_norm);
CREATE INDEX sense_entry ON sense(entry_id);
CREATE INDEX example_sense ON example(sense_id);
CREATE INDEX thes_entry ON thesaurus(entry_id);
CREATE INDEX ant_entry ON antonym(entry_id);
CREATE INDEX family_head ON family(headword);
CREATE INDEX phrase_head ON phrase_link(headword);
""" + vi_layer.INDEXES


def main():
    t0 = time.time()
    BUILD.mkdir(parents=True, exist_ok=True)
    rank, phon = load_ranks()
    tier_a = tier_a_words()
    tier_a_rank = {w: i + 1 for i, w in enumerate(tier_a)}
    cefr = cefr_table()
    print("Đọc Wiktionary tiếng Việt...", flush=True)
    viwikt_en, viwikt_blocks = vi_layer.load_viwikt()
    print("Đọc Wiktionary tiếng Anh...", flush=True)
    entries, form_of, phrases = scan(tier_a, rank, viwikt_en)
    words = {w for w, _ in entries}
    print(f"  {len(entries)} mục (từ + từ loại), {len(words)} từ đầu mục", flush=True)
    ai = load_ai()
    print(f"  bản AI đã có cho {len(ai)} mục", flush=True)
    print("Đọc Open English WordNet...", flush=True)
    thes = oewn(words)

    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.executescript("PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA page_size=4096;" + SCHEMA)

    with open(ROOT / "pipeline" / "sources.toml", "rb") as f:
        sources = tomllib.load(f)["sources"]
    lock = json.loads((ROOT / "pipeline" / "sources.lock").read_text(encoding="utf-8"))
    for sid, s in sources.items():
        con.execute("INSERT INTO source VALUES(?,?,?,?,?,?)", (sid, s["name"], s["license"], s.get("attribution"),
                                                                s["url"], lock.get(sid, {}).get("retrieved_at")))
    con.execute("INSERT INTO source VALUES(?,?,?,?,?,?)", ("gemini", "Gemini 3.8 Flash (qua Antigravity CLI)",
                                                          "Nội dung do AI sinh, gắn nhãn AI", "Google Gemini",
                                                          "", time.strftime("%Y-%m-%d")))

    stats = defaultdict(int)
    vi_links = []
    eid = sid = 0
    head_rank = {}
    for (w, pos), e in sorted(entries.items(), key=lambda kv: kv[1]["ord"]):
        eid += 1
        tier = "A" if w in tier_a_rank else "B"
        r = rank.get(w)
        band = "Top 3000" if r and r <= 3000 else "Top 5000" if r and r <= 5000 else None
        lvl = cefr.get((w.lower(), pos))
        a = ai.get((w, pos))
        con.execute("INSERT INTO entry VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (eid, f"{w}|{pos}", w, norm(w), pos, e["ord"], e["entry_type"], r, band, lvl,
                     "CEFR-J/Octanove" if lvl else None, tier, e["etym"] or None, a["model"] if a else None))
        head_rank.setdefault(w, (r, tier))
        # Wiktionary trước. ECDICT chỉ dự phòng cho UK: phiên âm ECDICT theo kiểu Anh (không gắn nhãn US), chuẩn hoá sang IPA
        # bằng ipa_ecdict (chuỗi hỏng → không có phiên âm). Nguồn ghi theo TỪNG giọng (trước đây cả hai ghi "wiktionary"
        # dù giọng thiếu lấy từ ECDICT — người dùng thấy "verbally /'v\\:bәli/", 2026-10-07).
        wk_uk = e["ipa_uk"] or e["ipa_any"]
        wk_us = e["ipa_us"] or e["ipa_any"]
        ec_uk = None if wk_uk else ecdict_to_ipa(phon.get(w))
        for acc, ipa, src_ipa in (("uk", wk_uk or ec_uk, "wiktionary" if wk_uk else "ecdict"), ("us", wk_us, "wiktionary")):
            if ipa:
                con.execute("INSERT INTO pronunciation VALUES(?,?,?,?)", (eid, acc, ipa_clean(ipa), src_ipa))
        uk, us = wk_uk or ec_uk, wk_us
        stats["ipa"] += bool(uk or us)
        main_forms = [f for f in e["forms"] if not f["conj"]] or [f for f in e["forms"] if f["conj"]]
        for i, fm in enumerate(main_forms[:6]):
            con.execute("INSERT INTO form VALUES(?,?,?,?)", (eid, i, fm["form"], " ".join(fm["tags"])))
        for fm in e["forms"]:
            if " " not in fm["form"] or " " in w:
                con.execute("INSERT INTO lookup_index VALUES(?,?,?,?)",
                            (norm(fm["form"]), w, "inflection", " ".join(fm["tags"])))
        # nghĩa Wiktionary (layer full), kèm bản dịch tiếng Việt theo nghĩa nếu khớp được
        sense_vi, unmatched = vi_layer.match_translations(e["senses"], e["vi_tr"])
        for header, ws in unmatched:
            con.execute("INSERT INTO translation_group VALUES(?,?,?)", (eid, header, "; ".join(dict.fromkeys(ws))))
        for i, s in enumerate(e["senses"]):
            sid += 1
            gram, labels = sense_codes(s["tags"])
            con.execute("INSERT INTO sense VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (sid, eid, "full", i, None, gram, labels, s["gloss"], None, sense_vi[i],
                         1 if sense_vi[i] else None, None, 0, "wiktionary"))
            if sense_vi[i]:
                for v in vi_layer.vi_terms(sense_vi[i]):
                    vi_links.append((v, w, pos, None, s["gloss"], "wiktionary"))
            for j, x in enumerate(s["examples"]):
                con.execute("INSERT INTO example VALUES(?,?,?,?,?,?)", (sid, j, x, None, 0, "wiktionary"))
        for i, g in enumerate(viwikt_blocks.get((w, pos), [])[:20]):
            con.execute("INSERT INTO vi_block VALUES(?,?,?)", (eid, i, g))
            if i < 6:
                for v in vi_layer.vi_terms(g, max_words=3):
                    vi_links.append((v, w, pos, None, e["senses"][0]["gloss"] if e["senses"] else "", "viwikt"))
        stats["vi_any"] += bool(a or any(sense_vi) or viwikt_blocks.get((w, pos)))
        stats["senses_full"] += len(e["senses"])
        stats["entries_with_example"] += any(s["examples"] for s in e["senses"])
        # nghĩa AI (layer learner)
        if a:
            stats["entries_ai"] += 1
            for i, s in enumerate(a["senses"]):
                sid += 1
                con.execute("INSERT INTO sense VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (sid, eid, "learner", i, s["guideword"] or None, s["grammar"] or None,
                             s["labels"] or None, s["definition"], s["cefr"], s["vi"], int(bool(s["vi_ok"])),
                             json.dumps(s["src"]), 1, "gemini"))
                for j, x in enumerate(s["examples"]):
                    con.execute("INSERT INTO example VALUES(?,?,?,?,?,?)", (sid, j, x["en"], x["vi"], 1, "gemini"))
                stats["senses_ai"] += 1
                for v in vi_layer.vi_terms(s["vi"] or ""):
                    vi_links.append((v, w, pos, s["guideword"] or None, s["definition"], "ai"))
        th = thes.get((w, pos))
        if th:
            for i, g in enumerate(th["groups"]):
                con.execute("INSERT INTO thesaurus VALUES(?,?,?,?,?)",
                            (eid, i, g["definition"], json.dumps(g["members"]), json.dumps(g["hypernym"])))
            for x in th["antonyms"]:
                con.execute("INSERT INTO antonym VALUES(?,?)", (eid, x))
        for m in e["derived"]:
            if m in words and m != w:
                con.execute("INSERT INTO family VALUES(?,?)", (w, m))

    for w, (r, tier) in head_rank.items():
        con.execute("INSERT INTO headword VALUES(?,?,?,?)", (w, norm(w), r, tier))
        con.execute("INSERT INTO fts_headword(word) VALUES(?)", (w,))
    n_form_of = 0
    for form, target, tags, rel in form_of:
        if target in words and form not in words:
            con.execute("INSERT INTO lookup_index VALUES(?,?,?,?)", (norm(form), target, rel, " ".join(tags)))
            n_form_of += 1
    seen = set()
    for head, phrase, kind, gloss, pop in phrases:
        if (head, phrase) not in seen:
            seen.add((head, phrase))
            con.execute("INSERT INTO phrase_link VALUES(?,?,?,?,?)", (head, phrase, kind, gloss, pop))

    print("Lớp tiếng Việt: Việt–Anh và Tatoeba...", flush=True)
    lemma_of = {}
    for (form_n, hw) in con.execute("SELECT form_norm, headword FROM lookup_index"):
        lemma_of.setdefault(form_n, hw)
    n_vi = vi_layer.write(con, vi_links, vi_layer.load_kaikki_vi(), vi_layer.tatoeba_pairs(), lemma_of,
                          set(head_rank), rank)
    stats["vi_headwords"] = n_vi
    stats["vi_links"] = len(vi_links)
    con.executescript(INDEXES)
    meta = {"schema_version": str(SCHEMA_VERSION), "data_version": time.strftime("%Y.%m.%d"),
            "build_date": time.strftime("%Y-%m-%dT%H:%M:%S"), "min_app_version": "0.1.0", "lang": "en"}
    con.executemany("INSERT INTO meta VALUES(?,?)", meta.items())
    con.commit()
    con.execute("ANALYZE")
    con.execute("VACUUM")
    con.close()

    report = coverage_report(tier_a, stats, len(entries), len(head_rank), n_form_of, len(seen))
    report["build_seconds"] = round(time.time() - t0)
    report["db_mb"] = round(DB.stat().st_size / 2**20, 1)
    (BUILD / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


def coverage_report(tier_a, stats, n_entries, n_heads, n_form_of, n_phrases):
    con = sqlite3.connect(DB)
    top = tier_a[:20000]
    con.execute("CREATE TEMP TABLE top(w TEXT PRIMARY KEY)")
    con.executemany("INSERT INTO top VALUES(?)", [(w,) for w in top])

    def pct(sql):
        n = con.execute(sql).fetchone()[0]
        return round(n * 100 / len(top), 1)

    rep = {
        "entries": n_entries, "headwords": n_heads, "lookup_forms": n_form_of, "phrase_links": n_phrases,
        "senses_full": stats["senses_full"], "senses_ai": stats["senses_ai"], "entries_ai": stats["entries_ai"],
        "vi_headwords": stats["vi_headwords"], "vi_links": stats["vi_links"],
        "top20k": {
            "has_entry": pct("SELECT count(*) FROM top WHERE w IN (SELECT headword FROM entry)"),
            "has_ipa": pct("SELECT count(DISTINCT e.headword) FROM entry e JOIN pronunciation p ON p.entry_id=e.id "
                           "WHERE e.headword IN (SELECT w FROM top)"),
            "has_definition": pct("SELECT count(DISTINCT e.headword) FROM entry e JOIN sense s ON s.entry_id=e.id "
                                  "WHERE e.headword IN (SELECT w FROM top)"),
            "has_example": pct("SELECT count(DISTINCT e.headword) FROM entry e JOIN sense s ON s.entry_id=e.id "
                               "JOIN example x ON x.sense_id=s.id WHERE e.headword IN (SELECT w FROM top)"),
            "has_ai": pct("SELECT count(DISTINCT headword) FROM entry WHERE ai_model IS NOT NULL "
                          "AND headword IN (SELECT w FROM top)"),
            "has_vi_per_sense": pct("SELECT count(DISTINCT e.headword) FROM entry e JOIN sense s ON s.entry_id=e.id "
                                    "WHERE s.vi IS NOT NULL AND e.headword IN (SELECT w FROM top)"),
            "has_vi_any": pct("SELECT count(DISTINCT e.headword) FROM entry e WHERE e.headword IN (SELECT w FROM top) "
                              "AND (e.ai_model IS NOT NULL OR EXISTS(SELECT 1 FROM vi_block b WHERE b.entry_id=e.id) "
                              "OR EXISTS(SELECT 1 FROM sense s WHERE s.entry_id=e.id AND s.vi IS NOT NULL))"),
            "has_tatoeba": pct("SELECT count(DISTINCT headword) FROM tatoeba_word WHERE headword IN (SELECT w FROM top)"),
            "has_cefr": pct("SELECT count(DISTINCT headword) FROM entry WHERE cefr IS NOT NULL "
                            "AND headword IN (SELECT w FROM top)"),
        },
    }
    con.close()
    return rep


if __name__ == "__main__":
    main()
