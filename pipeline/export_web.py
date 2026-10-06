"""Xuất dữ liệu cho bản web (UC-WM01, PLAN-web mục 4).

Dùng: python pipeline/export_web.py [--jobs N]   → data/build/web/manifest.json + data/build/web/v<data_version>/

- Đọc data/build/dict-core.sqlite CHỈ ĐỌC (file:…?mode=ro), đọc report.json và DỪNG nếu cổng chất lượng trượt
  (dùng lại GATE của pack.py).
- Dựng sẵn mọi mục từ đúng hình dạng db.rs::entry() (EnEntry) và db.rs::vi_entry() (ViEntry), cùng truy vấn,
  cùng thứ tự, cùng giới hạn như Rust (kể cả nearby, known, tatoeba). Kiểm bằng pipeline/web_check.py.
- Tất định: json.dumps(sort_keys, ensure_ascii=False, separators gọn); cùng DB → cùng byte.
- Quy tắc CANNOT của người bảo trì: thiếu manifest/nguồn/giấy phép/nhãn AI → dừng; > 10.000 file mỗi bản hoặc
  file > 5 MB → dừng, in ngưỡng + số đo + file vi phạm; thư mục xuất chỉ có .json/.txt/.md.

Bố cục (PLAN-web 4.2):
  manifest.json
  v<ver>/e/NNNN.json   {"<từ đầu mục>": EnEntry}   shard = fnv1a32(UTF-8 của từ đầu mục, đúng như trong DB) mod 2048
  v<ver>/v/NNNN.json   {"<từ Việt>": ViEntry}       shard = fnv1a32(UTF-8 của từ Việt) mod 1024
  v<ver>/p/<k>.json    chỉ mục tiền tố theo norm (xem bucket(); dấu cách → "_", chữ ngoài a–z → "~"):
        "h": [[từ, thứ hạng|null(, norm nếu khác norm tính lại)]…]   sắp theo (rank null sau, rank, độ dài, norm, từ)
        "f": [[form_norm, lemma, "i"|"v", tags(, [≤3 lemma cho gợi ý nếu khác [lemma]])]…]  lemma = đúng lựa chọn của en_resolve
        "v": [[từ Việt, trọng số(, norm)]…]                          sắp theo (trọng số giảm, độ dài, norm, từ)
        "top": {"en": [10 từ], "vi": [8 từ]}  = đúng kết quả SQL của suggest() (xem has_top())
  v<ver>/words.txt     từ\tthứ hạng (gợi ý chính tả), theo thứ tự rowid của fts_headword (để mô phỏng bm25 + LIMIT 600)
  v<ver>/sources.json  bảng source (= lệnh "sources")
  v<ver>/LICENSES.md   như gói .tdpack (pack.licenses_md())
"""
import argparse
import gzip
import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics
import sys
import time
import unicodedata
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pack  # noqa: E402  (GATE, licenses_md; pack tự đặt stdout UTF-8)

ROOT = pack.ROOT
BUILD = pack.BUILD
DB = pack.DB
OUT = BUILD / "web"
STAGE = BUILD / "web.tmp"

SCHEMA_WEB = 1
MIN_UI = "0.1.0"          # phiên bản giao diện web tối thiểu đọc được định dạng này
DB_SCHEMA = "2"           # = db.rs::SCHEMA_VERSION
EN_SHARDS = 2048
VI_SHARDS = 1024
SPLIT_BYTES = 128 * 1024  # tiền tố chưa nén lớn hơn → tách thêm một chữ (người dùng chọn 128 KiB ở W2; W1 dùng 64 KiB)
MAX_FILES = 10_000        # ngưỡng hosting (use-cases: lỗi người bảo trì)
MAX_FILE_BYTES = 5 * 1000 * 1000
ALLOWED_EXT = {".json", ".txt", ".md"}
REL = {"inflection": "i", "variant": "v"}

# Rust char::is_whitespace / str::trim dùng thuộc tính White_Space (khác str.strip() của Python ở \x1c–\x1f)
WHITE_SPACE = "\t\n\x0b\x0c\r \x85\xa0 " + "".join(chr(c) for c in range(0x2000, 0x200B)) + \
    "    　"


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")


def fnv1a32(s):
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def is_mark(c):  # unicode_normalization::char::is_combining_mark = Mn | Mc | Me
    return unicodedata.category(c) in ("Mn", "Mc", "Me")


def rnorm(s):
    """Bản Python của db.rs::norm(): chữ thường, đ → d, NFD, bỏ dấu kết hợp, trim."""
    s = s.lower().replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if not is_mark(c)).strip(WHITE_SPACE)


def ralpha(c):  # gần đúng char::is_alphabetic của Rust (thuộc tính Alphabetic)
    return c.isalpha() or unicodedata.category(c) == "Nl"


def typed(row, spec):
    """rusqlite bỏ dòng khi kiểu không khớp (query_map(...).flatten()): s=String, S=Option<String>, i=i64, I=Option<i64>."""
    for v, t in zip(row, spec):
        if t == "s":
            ok = type(v) is str
        elif t == "S":
            ok = v is None or type(v) is str
        elif t == "i":
            ok = type(v) is int
        else:
            ok = v is None or type(v) is int
        if not ok:
            return False
    return True


def q(con, sql, params, spec):
    return [r for r in con.execute(sql, params).fetchall() if typed(r, spec)]


def nonempty(v):  # db.rs::s()
    return v if v else None


def str_list(text):  # serde_json::from_str::<Vec<String>>(…).unwrap_or_default()
    try:
        v = json.loads(text)
    except ValueError:
        return []
    return v if isinstance(v, list) and all(type(x) is str for x in v) else []


def open_ro():
    return sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)


# ---------------------------------------------------------------- mục Anh (db.rs::entry)

SQL_ENTRY = """SELECT id, pos, entry_type, freq_rank, freq_band, cefr, etymology, ai_model, tier
                 FROM entry WHERE headword = ?1 ORDER BY ai_model IS NULL, ord"""
SQL_PRON = "SELECT accent, ipa FROM pronunciation WHERE entry_id = ?1"
SQL_FORM = "SELECT form, tags FROM form WHERE entry_id = ?1 ORDER BY ord"
SQL_EX = """SELECT x.sense_id, x.text_en, x.text_vi FROM example x JOIN sense s ON s.id = x.sense_id
                 WHERE s.entry_id = ?1 ORDER BY x.sense_id, x.ord"""
SQL_SENSE = """SELECT id, layer, guideword, grammar, labels, definition, cefr, vi, vi_from_wikt
                 FROM sense WHERE entry_id = ?1 ORDER BY layer DESC, ord"""
SQL_THES = "SELECT definition, members, hypernyms FROM thesaurus WHERE entry_id = ?1 ORDER BY ord"
SQL_ANT = "SELECT DISTINCT word FROM antonym WHERE entry_id = ?1"
SQL_VIBLOCK = "SELECT text FROM vi_block WHERE entry_id = ?1 ORDER BY ord"
SQL_TRG = "SELECT header, words FROM translation_group WHERE entry_id = ?1"
SQL_PHRASE = "SELECT phrase, kind, gloss FROM phrase_link WHERE headword = ?1 AND phrase <> ?1 ORDER BY popularity DESC"
SQL_FAMILY = """SELECT DISTINCT f.member FROM family f JOIN headword h ON h.word = f.member
                 WHERE f.headword = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 24"""
SQL_BEFORE = "SELECT word FROM headword WHERE freq_rank IS NOT NULL AND norm < ?1 ORDER BY norm DESC LIMIT 6"
SQL_AFTER = "SELECT word FROM headword WHERE freq_rank IS NOT NULL AND norm > ?1 ORDER BY norm LIMIT 6"
SQL_TATO = """SELECT t.en, t.vi FROM tatoeba_word w JOIN tatoeba t ON t.id = w.tid WHERE w.headword = ?1 ORDER BY t.id"""


def en_entry(con, headwords, word):
    rows = q(con, SQL_ENTRY, (word,), "issISSSSs")
    if not rows:
        return None
    ipa = {"uk": None, "us": None}
    blocks = []
    referenced = set()
    for (eid, pos, entry_type, _r, _b, cefr, etym, model, _t) in rows:
        for acc, p in q(con, SQL_PRON, (eid,), "ss"):
            if acc == "uk" and ipa["uk"] is None:
                ipa["uk"] = p
            elif acc == "us" and ipa["us"] is None:
                ipa["us"] = p
        forms = [{"form": f, "tags": (t or "").split()} for f, t in q(con, SQL_FORM, (eid,), "sS")]
        ex_by_sense = {}
        for sid, en, vi in q(con, SQL_EX, (eid,), "isS"):
            ex_by_sense.setdefault(sid, []).append((en, vi))
        senses, wikt = [], []
        for sid, layer, gw, gram, labels, d, scefr, vi, viok in q(con, SQL_SENSE, (eid,), "isSSSsSSI"):
            exs = ex_by_sense.pop(sid, [])
            if layer == "learner":
                senses.append({"guideword": nonempty(gw), "grammar": nonempty(gram), "labels": nonempty(labels),
                               "definition": d, "cefr": scefr, "vi": vi, "vi_ok": (viok or 0) == 1,
                               "examples": [{"en": en, "vi": v} for en, v in exs]})
            else:
                wikt.append({"gloss": d, "grammar": nonempty(gram), "labels": nonempty(labels),
                             "examples": [en for en, _ in exs], "vi": vi})
        thesaurus = [{"definition": d or "", "members": str_list(m), "hypernym": str_list(h)}
                     for d, m, h in q(con, SQL_THES, (eid,), "Sss")]
        antonyms = [r[0] for r in q(con, SQL_ANT, (eid,), "s")]
        for g in thesaurus:
            referenced.update(g["members"])
        vi_block = [r[0] for r in q(con, SQL_VIBLOCK, (eid,), "s")]
        translations = [{"header": h, "words": w} for h, w in q(con, SQL_TRG, (eid,), "ss")]
        referenced.update(antonyms)
        blocks.append({"pos": pos, "entry_type": entry_type, "model": model, "cefr": cefr, "forms": forms,
                       "senses": senses, "wiktionary": wikt, "thesaurus": thesaurus, "antonyms": antonyms,
                       "etymology": etym, "vi_block": vi_block, "translations": translations})
    phrasal_verbs, idioms = [], []
    lw = word.lower()
    for p, kind, gloss in q(con, SQL_PHRASE, (lw,), "sss"):
        target = phrasal_verbs if kind == "phrasal_verb" else idioms
        if len(target) < 20:
            referenced.add(p)
            target.append({"phrase": p, "gloss": gloss})
    family = [r[0] for r in q(con, SQL_FAMILY, (word,), "s")]
    referenced.update(family)
    n = rnorm(word)
    before = [r[0] for r in q(con, SQL_BEFORE, (n,), "s")]
    before.reverse()
    after = [r[0] for r in q(con, SQL_AFTER, (n,), "s")]
    nearby = before + after
    referenced.update(nearby)
    # Rust: HashSet → "WHERE word IN (…)" theo khúc 500 → thứ tự BINARY trong mỗi khúc. Ở đây sắp toàn bộ
    # (giống hệt Rust khi ≤ 500 từ được nhắc; giao diện chỉ dùng known như một Set).
    known = sorted(w for w in referenced if w in headwords)
    tatoeba = [{"en": en, "vi": vi} for en, vi in q(con, SQL_TATO, (word,), "sS")]
    return {"word": word, "rank": next((r[3] for r in rows if r[3] is not None), None),
            "band": next((r[4] for r in rows if r[4] is not None), None), "tier": rows[0][8], "ipa": ipa,
            "blocks": blocks, "phrasal_verbs": phrasal_verbs, "idioms": idioms, "family": family,
            "nearby": nearby, "tatoeba": tatoeba, "known": known}


# ---------------------------------------------------------------- mục Việt (db.rs::vi_entry)

SQL_VILINK = """SELECT headword, pos, guideword, definition, source, max(weight) w, min(freq_rank) r
                 FROM vi_link WHERE vi = ?1 GROUP BY headword, pos, coalesce(guideword, '')
                 ORDER BY w DESC, r IS NULL, r LIMIT 40"""
SQL_VISENSE = "SELECT pos, gloss FROM vi_sense WHERE word = ?1 ORDER BY rowid"
SQL_VITATO = "SELECT en, vi FROM tatoeba WHERE vi LIKE '%' || ?1 || '%' ORDER BY length(en) LIMIT 80"


def rust_hit(v, w):
    """v.match_indices(w) (không chồng lấn) có lần nào nằm giữa hai ranh giới không phải chữ cái."""
    i = v.find(w)
    while i != -1:
        j = i + len(w)
        if (i == 0 or not ralpha(v[i - 1])) and (j == len(v) or not ralpha(v[j])):
            return True
        i = v.find(w, j if w else j + 1)
    return False


def vi_tatoeba_sql(con, word):
    """Đúng đoạn tatoeba của db.rs::vi_entry (chạy SQL thật) — dùng cho từ có % hoặc _ và để đối chiếu."""
    out = []
    for en_s, vi_s in q(con, SQL_VITATO, (word,), "ss"):
        if rust_hit(vi_s.lower(), word) and len(out) < 5:
            out.append({"en": en_s, "vi": vi_s})
    return out


ASCII_FOLD = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def vi_tatoeba_all(con, words):
    """Tính sẵn câu Tatoeba cho mọi từ Việt, cho cùng kết quả với truy vấn LIKE của db.rs (PLAN-web 4.3):
    1) ứng viên = từ Việt xuất hiện giữa hai ranh giới không-phải-chữ trong câu (đã chữ thường) — điều kiện cần của Rust;
    2) với mỗi ứng viên: 80 câu đầu theo (length(en), id) có chứa từ theo LIKE (chỉ gộp hoa/thường ASCII),
       rồi lọc ranh giới như Rust, lấy tối đa 5."""
    rows = con.execute("SELECT id, en, vi FROM tatoeba").fetchall()
    if any(type(en) is not str or type(vi) is not str for _, en, vi in rows):
        raise SystemExit("Bảng tatoeba có en/vi không phải chuỗi — export_web chưa mô phỏng trường hợp này.")
    rows.sort(key=lambda r: (len(r[1]), r[0]))   # ORDER BY length(en); hoà thì theo thứ tự quét (rowid)
    lowered = [r[2].lower() for r in rows]
    folded = [r[2].translate(ASCII_FOLD) for r in rows]
    wordset = set(words)
    maxlen = max(len(w) for w in words)
    cand = set()
    for v in lowered:
        n = len(v)
        starts = [i for i in range(n) if i == 0 or not ralpha(v[i - 1])]
        ends = [e for e in range(1, n + 1) if e == n or not ralpha(v[e])]
        for i in starts:
            for e in ends:
                if e > i and e - i <= maxlen and v[i:e] in wordset:
                    cand.add(v[i:e])
    big = "\x00".join(folded)
    offs, p = [], 0
    for f in folded:
        offs.append(p)
        p += len(f) + 1
    from bisect import bisect_right
    out = {}
    for w in sorted(cand):
        if "%" in w or "_" in w:
            res = vi_tatoeba_sql(con, w)
        else:
            fw = w.translate(ASCII_FOLD)
            res, seen, pos = [], 0, 0
            while seen < 80:
                i = big.find(fw, pos)
                if i == -1:
                    break
                k = bisect_right(offs, i) - 1
                seen += 1
                if len(res) < 5 and rust_hit(lowered[k], w):
                    res.append({"en": rows[k][1], "vi": rows[k][2]})
                pos = offs[k + 1] if k + 1 < len(offs) else len(big)
        if res:
            out[w] = res
    return out, len(cand)


def vi_entry(con, word, tato):
    en = [{"headword": h, "pos": p, "guideword": g, "definition": d or "", "source": s}
          for h, p, g, d, s, _w, _r in q(con, SQL_VILINK, (word,), "ssSSs")]
    wikt = []
    for pos, g in q(con, SQL_VISENSE, (word,), "ss"):
        if wikt and wikt[-1]["pos"] == pos:
            wikt[-1]["glosses"].append(g)
        else:
            wikt.append({"pos": pos, "glosses": [g]})
    if not en and not wikt:
        return None
    return {"word": word, "en": en, "wikt": wikt, "tatoeba": tato}


# ---------------------------------------------------------------- tiến trình con (dựng shard song song)

_CON = None
_HW = None


def _init():
    global _CON, _HW
    sys.stdout.reconfigure(encoding="utf-8")
    _CON = open_ro()
    _HW = {r[0] for r in _CON.execute("SELECT word FROM headword")}


def _gz(b):
    return len(gzip.compress(b, 9, mtime=0))


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def job_en(args):
    path, words = args
    shard, no_label, n = {}, 0, 0
    for w in words:
        e = en_entry(_CON, _HW, w)
        if e is None:
            continue
        n += 1
        no_label += sum(1 for b in e["blocks"] if b["senses"] and not b["model"])
        shard[w] = e
    data = dumps(shard)
    _write(Path(path), data)
    return path, len(data), _gz(data), n, no_label


def job_vi(args):
    path, words, tato = args
    shard = {}
    for w in words:
        e = vi_entry(_CON, w, tato.get(w, []))
        if e is not None:
            shard[w] = e
    data = dumps(shard)
    _write(Path(path), data)
    return path, len(data), _gz(data), len(shard), 0


SQL_VIA = """SELECT l.headword, l.relation, l.tags FROM lookup_index l JOIN headword h ON h.word = l.headword
                 WHERE l.form_norm = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 1"""
SQL_FRONT = """SELECT DISTINCT l.headword FROM lookup_index l JOIN headword h ON h.word = l.headword
             WHERE l.form_norm = ?1 ORDER BY h.freq_rank IS NULL, h.freq_rank LIMIT 3"""


def job_forms(forms):
    """Dạng biến đổi: lemma/relation/tags đúng như en_resolve; danh sách ≤3 lemma đúng như suggest()."""
    out = []
    for fn in forms:
        r = _CON.execute(SQL_VIA, (fn,)).fetchone()
        if r is None or not typed(r, "ssS"):   # Rust: query_row lỗi kiểu → coi như không có
            continue
        lemma, rel, tags = r
        if rel not in REL:
            raise SystemExit(f"relation lạ trong lookup_index: {rel!r}")
        item = [fn, lemma, REL[rel], tags or ""]
        front = [x[0] for x in q(_CON, SQL_FRONT, (fn,), "s")]
        if front != [lemma]:
            item.append(front)
        out.append(item)
    return out


# ---------------------------------------------------------------- chỉ mục tiền tố

SPACE, OTHER = "_", "~"
MAX_KEY = 4   # tiền tố dài nhất khi tách


def _m(c):
    return c if "a" <= c <= "z" else (SPACE if c == " " else OTHER)


def bucket(n, split):
    """Tên file tiền tố của một norm (= tên file p/<khoá>.json, phía web tính y hệt):
    - norm rỗng hoặc bắt đầu bằng chữ ngoài a–z → "~" (p/~.json: số, ký hiệu, chữ ngoài a–z);
    - còn lại: 1–2 chữ đầu, dấu cách → "_", chữ khác ngoài a–z → "~";
    - khi khoá nằm trong `split` và norm còn dài hơn khoá → thêm một chữ nữa (lặp, tối đa MAX_KEY chữ)."""
    if not n or not ("a" <= n[0] <= "z"):
        return OTHER
    k = "".join(_m(c) for c in n[:2])
    while k in split and len(n) > len(k):
        k += _m(n[len(k)])
    return k


def has_top(k, split):
    """File có "top" (kết quả suggest() dựng sẵn) khi các từ bắt đầu bằng đúng tiền tố này có thể nằm ở nhiều file:
    khoá 1 chữ, khoá 2 chữ a–z, và mọi khoá đã tách. Khoá kết thúc bằng dấu cách / có "~" thì không (chuỗi tra
    đã chuẩn hoá không bao giờ kết thúc bằng dấu cách; "~" gộp nhiều chữ khác nhau)."""
    if OTHER in k or k.endswith(SPACE):
        return False
    return len(k) <= 2 or k in split


SQL_TOP_EN = """SELECT word FROM headword WHERE norm >= ?1 AND norm < ?2
             ORDER BY freq_rank IS NULL, freq_rank, length(word) LIMIT 10"""
SQL_TOP_VI = """SELECT word FROM vi_headword WHERE norm >= ?1 AND norm < ?2
             ORDER BY (norm = ?1) DESC, n_links + 3 * has_wikt DESC, length(word) LIMIT 8"""


def build_prefix(con, forms):
    hw = [r for r in con.execute("SELECT word, norm, freq_rank FROM headword ORDER BY norm, word")]
    hw.sort(key=lambda r: (r[2] is None, r[2] or 0, len(r[0])))       # ổn định: hoà thì theo (norm, từ)
    vi = [r for r in con.execute("SELECT word, norm, n_links + 3 * has_wikt FROM vi_headword ORDER BY norm, word")]
    vi.sort(key=lambda r: (-r[2], len(r[0])))
    h_items = [(n, [w, r] if rnorm(w) == n else [w, r, n]) for w, n, r in hw]
    v_items = [(n, [w, wt] if rnorm(w) == n else [w, wt, n]) for w, n, wt in vi]
    f_items = [(f[0], f) for f in sorted(forms)]
    norm_diff = sum(1 for _, x in h_items if len(x) == 3) + sum(1 for _, x in v_items if len(x) == 3)
    cache = {}

    def top(k):
        if k not in cache:
            p = k.replace(SPACE, " ")
            up = p + "\U0010FFFF"
            cache[k] = {"en": [r[0] for r in con.execute(SQL_TOP_EN, (p, up))],
                        "vi": [r[0] for r in con.execute(SQL_TOP_VI, (p, up))]}
        return cache[k]

    def group(split):
        g = {}
        for kind, items in (("h", h_items), ("f", f_items), ("v", v_items)):
            for n, x in items:
                g.setdefault(bucket(n, split), {"h": [], "f": [], "v": []})[kind].append(x)
        keys = set(g) | {k[0] for k in g if k != OTHER} | set(split)
        for k in keys:
            if has_top(k, split):
                g.setdefault(k, {"h": [], "f": [], "v": []})["top"] = top(k)
        return {k: d for k, d in g.items() if d["h"] or d["f"] or d["v"] or "top" in d}

    split = set()
    while True:   # tách dần: file nào > SPLIT_BYTES (chưa nén) thì tách thêm một chữ
        g = group(split)
        new = {k for k, d in g.items() if 2 <= len(k) < MAX_KEY and OTHER not in k and k not in split
               and len(dumps(d)) > SPLIT_BYTES}
        if not new:
            break
        split |= new

    # kiểm giả thuyết thứ tự cho vòng W2: lọc danh sách đã sắp theo tiền tố = đúng kết quả SQL của suggest()
    by1, by2 = {}, {}
    for items, tag in ((h_items, "h"), (v_items, "v")):
        for n, x in items:
            by1.setdefault((tag, n[:1]), []).append((n, x))
            by2.setdefault((tag, n[:2]), []).append((n, x))
    miss = []
    tops = {k: d["top"] for k, d in g.items() if "top" in d}
    for k, t in tops.items():
        p = k.replace(SPACE, " ")
        src = (lambda tag: by1.get((tag, p), [])) if len(p) == 1 else (lambda tag: by2.get((tag, p[:2]), []))
        en = [x[0] for n, x in src("h") if n.startswith(p)][:10]
        vv = [(n, x[0]) for n, x in src("v") if n.startswith(p)]
        vv = ([w for n, w in vv if n == p] + [w for n, w in vv if n != p])[:8]
        if en != t["en"] or vv != t["vi"]:
            miss.append(k)
    return g, sorted(split), norm_diff, (len(tops) - len(miss), len(tops), miss[:10])


# ---------------------------------------------------------------- đo, kiểm, ghi

def pct(xs, p):
    xs = sorted(xs)
    return xs[max(0, math.ceil(p * len(xs)) - 1)] if xs else 0


def _measure_one(path):
    b = Path(path).read_bytes()
    return len(b), _gz(b)


def measure(vdir, jobs=8):
    """{loại: [(đường dẫn tương đối, byte, byte gzip -9)]} — loại = e, v, p hoặc tên file."""
    paths = sorted(p for p in vdir.rglob("*") if p.is_file())
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        sizes = list(ex.map(_measure_one, [str(p) for p in paths], chunksize=32))
    out = {}
    for p, (raw, gz) in zip(paths, sizes):
        rel = p.relative_to(vdir).as_posix()
        kind = rel.split("/")[0] if "/" in rel else rel
        out.setdefault(kind, []).append((rel, raw, gz))
    return out


def print_stats(stats):
    KiB, MiB = 1024, 1024 * 1024
    print(f"{'loại':<14}{'số file':>8}{'chưa nén':>12}{'gzip':>11}   gzip mỗi file: trung vị / p95 / lớn nhất   chưa nén lớn nhất")
    tot_n = tot_raw = tot_gz = 0
    for kind, rows in sorted(stats.items()):
        raw = [r[1] for r in rows]
        gz = [r[2] for r in rows]
        big = max(rows, key=lambda r: r[1])
        tot_n += len(rows); tot_raw += sum(raw); tot_gz += sum(gz)
        print(f"{kind:<14}{len(rows):>8}{sum(raw) / MiB:>10.2f}Mi{sum(gz) / MiB:>9.2f}Mi   "
              f"{statistics.median(gz) / KiB:>7.1f} / {pct(gz, .95) / KiB:.1f} / {max(gz) / KiB:.1f} KiB"
              f"        {big[1] / KiB:.0f} KiB ({big[0]})")
    print(f"{'TỔNG':<14}{tot_n:>8}{tot_raw / MiB:>10.2f}Mi{tot_gz / MiB:>9.2f}Mi")
    return tot_n, tot_raw, tot_gz


def stop(msg):
    if STAGE.exists():
        shutil.rmtree(STAGE)
    raise SystemExit("DỪNG: " + msg)


def gate():
    report = json.loads((BUILD / "report.json").read_text(encoding="utf-8"))
    top = report["top20k"]
    print("Cổng chất lượng (top 20.000, ngưỡng của pack.py):")
    for k, v in pack.GATE.items():
        print(f"  {'ĐẠT ' if top.get(k, 0) >= v else 'TRƯỢT'} {k}: {top.get(k)}% (ngưỡng {v}%)")
    fails = [f"{k}: {top.get(k)}% < {v}%" for k, v in pack.GATE.items() if top.get(k, 0) < v]
    if fails:
        raise SystemExit("Không xuất bản web: " + "; ".join(fails))


def main():
    ap = argparse.ArgumentParser(description="Xuất dữ liệu bản web (PLAN-web mục 4)")
    ap.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 4))
    args = ap.parse_args()
    t0 = time.time()
    gate()
    con = open_ro()
    meta = dict(con.execute("SELECT key, value FROM meta"))
    if meta.get("schema_version") != DB_SCHEMA:
        raise SystemExit(f"DB schema {meta.get('schema_version')!r}, export_web cần {DB_SCHEMA} (như db.rs).")
    ver = meta["data_version"]
    # nhãn AI: nghĩa lớp người học phải thuộc mục có ai_model; ví dụ AI chỉ nằm ở nghĩa lớp người học
    bad = con.execute("""SELECT count(*) FROM sense s JOIN entry e ON e.id = s.entry_id
                         WHERE s.layer = 'learner' AND (e.ai_model IS NULL OR e.ai_model = '')""").fetchone()[0]
    bad_ex = con.execute("""SELECT count(*) FROM example x JOIN sense s ON s.id = x.sense_id
                            WHERE x.is_ai = 1 AND s.layer <> 'learner'""").fetchone()[0]
    if bad or bad_ex:
        raise SystemExit(f"Thiếu nhãn AI: {bad} nghĩa AI không có ai_model, {bad_ex} ví dụ AI nằm ngoài lớp người học.")
    sources = [{"id": i, "name": n, "license": l, "attribution": a, "url": u, "retrieved_at": r}
               for i, n, l, a, u, r in q(con, "SELECT id, name, license, attribution, url, retrieved_at FROM source ORDER BY rowid",
                                         (), "ssssSS")]
    if not sources or any(not s["license"] for s in sources):
        raise SystemExit("Bảng source trống hoặc có nguồn thiếu giấy phép → không xuất.")
    if not any(s["id"] == "gemini" for s in sources):
        raise SystemExit("Bảng source thiếu nguồn AI (gemini) → nhãn AI không có ghi công.")
    lic = pack.licenses_md()   # tự dừng nếu nguồn trong sources.toml thiếu giấy phép

    if STAGE.exists():
        shutil.rmtree(STAGE)
    vdir = STAGE / f"v{ver}"
    vdir.mkdir(parents=True)

    hw = [r[0] for r in con.execute("SELECT word FROM headword ORDER BY word")]
    if any(("\t" in w or "\n" in w or "\r" in w) for w in hw):
        stop("có từ đầu mục chứa tab/xuống dòng → words.txt sẽ hỏng.")
    viw = [r[0] for r in con.execute("SELECT word FROM vi_headword ORDER BY word")]
    if any(not w for w in viw):
        stop("vi_headword có từ rỗng.")
    t1 = time.time()
    tato, n_cand = vi_tatoeba_all(con, viw)
    print(f"Tatoeba cho từ Việt: {n_cand} từ ứng viên, {len(tato)} từ có câu ({time.time() - t1:.1f} s)")

    en_groups = [[] for _ in range(EN_SHARDS)]
    for w in hw:
        en_groups[fnv1a32(w) % EN_SHARDS].append(w)
    vi_groups = [[] for _ in range(VI_SHARDS)]
    for w in viw:
        vi_groups[fnv1a32(w) % VI_SHARDS].append(w)
    forms = [r[0] for r in con.execute("SELECT DISTINCT form_norm FROM lookup_index WHERE form_norm IS NOT NULL ORDER BY form_norm")]
    fchunks = [forms[i::64] for i in range(64)]

    t1 = time.time()
    with ProcessPoolExecutor(max_workers=args.jobs, initializer=_init) as ex:
        en_res = list(ex.map(job_en, [(str(vdir / "e" / f"{i:04d}.json"), g) for i, g in enumerate(en_groups)], chunksize=8))
        vi_res = list(ex.map(job_vi, [(str(vdir / "v" / f"{i:04d}.json"), g, {w: tato[w] for w in g if w in tato})
                                      for i, g in enumerate(vi_groups)], chunksize=8))
        form_items = [x for part in ex.map(job_forms, fchunks) for x in part]
    print(f"Dựng mục từ + dạng biến đổi: {time.time() - t1:.1f} s ({args.jobs} tiến trình)")
    n_en = sum(r[3] for r in en_res)
    n_vi = sum(r[3] for r in vi_res)
    no_label = sum(r[4] for r in en_res)
    if no_label:
        stop(f"{no_label} khối có nghĩa AI nhưng thiếu `model` (nhãn AI).")

    t1 = time.time()
    groups, split, norm_diff, (top_ok, top_n, top_miss) = build_prefix(con, form_items)
    for k, d in groups.items():
        _write(vdir / "p" / f"{k}.json", dumps(d))
    print(f"Chỉ mục tiền tố: {len(groups)} file, tách thêm chữ: {len(split)} khoá, "
          f"norm DB ≠ norm tính lại: {norm_diff} từ, top khớp thứ tự lọc+sắp: {top_ok}/{top_n} {top_miss or ''}({time.time() - t1:.1f} s)")

    db_counts = {k: con.execute(sql).fetchone()[0] for k, sql in (
        ("headwords", "SELECT count(*) FROM headword"), ("entries", "SELECT count(*) FROM entry"),
        ("entries_ai", "SELECT count(*) FROM entry WHERE ai_model IS NOT NULL"),
        ("vi_headwords", "SELECT count(*) FROM vi_headword"))}
    n_entries = con.execute("SELECT count(*) FROM entry").fetchone()[0]
    n_entries_ai = con.execute("SELECT count(*) FROM entry WHERE ai_model IS NOT NULL").fetchone()[0]
    rank = dict(con.execute("SELECT word, freq_rank FROM headword"))
    # words.txt theo đúng thứ tự rowid của fts_headword: bản web mô phỏng "ORDER BY rank LIMIT 600" của db.rs::fuzzy
    # (bm25 của FTS5); khi hoà điểm FTS5 trả theo rowid → cần cùng thứ tự để chọn đúng 600 ứng viên như desktop.
    fts_order = [r[0] for r in con.execute("SELECT word FROM fts_headword ORDER BY rowid")]
    if sorted(fts_order) != hw:
        stop("fts_headword không khớp bảng headword → words.txt không mô phỏng được gợi ý chính tả.")
    _write(vdir / "words.txt", "".join(f"{w}\t{'' if rank[w] is None else rank[w]}\n" for w in fts_order).encode("utf-8"))
    _write(vdir / "sources.json", dumps(sources))
    _write(vdir / "LICENSES.md", lic.encode("utf-8"))
    con.close()

    # ---- kiểm trước khi đưa ra thư mục xuất (CANNOT + ngưỡng hosting)
    bad_ext = [p.relative_to(STAGE).as_posix() for p in STAGE.rglob("*") if p.is_file() and p.suffix not in ALLOWED_EXT]
    if bad_ext:
        stop(f"thư mục xuất có loại file không cho phép ({sorted(ALLOWED_EXT)}): {bad_ext[:10]}")
    for need in ("sources.json", "LICENSES.md", "words.txt"):
        if not (vdir / need).is_file() or (vdir / need).stat().st_size == 0:
            stop(f"thiếu {need}")
    files = sorted((p for p in vdir.rglob("*") if p.is_file()), key=lambda p: p.relative_to(vdir).as_posix())
    total = sum(p.stat().st_size for p in files)
    # Tên thư mục = phiên bản dữ liệu + mã băm nội dung: thư mục được lưu đệm "bất biến" 1 năm, nên xuất lại cùng
    # phiên bản dữ liệu mà nội dung/cách chia file đổi (vd. đổi ngưỡng tách tiền tố) vẫn ra thư mục mới, trình duyệt
    # không bao giờ ghép file cũ trong bộ đệm với manifest mới. Cùng nội dung → cùng tên (tất định).
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(vdir).as_posix().encode("utf-8") + b"\0" + f.read_bytes() + b"\0")
    vname = f"v{ver}-{h.hexdigest()[:8]}"
    vdir = vdir.rename(STAGE / vname)
    files = [vdir / f.relative_to(STAGE / f"v{ver}") for f in files]
    manifest = {
        "schema_web": SCHEMA_WEB, "data_version": ver, "build_date": meta.get("build_date"), "min_ui": MIN_UI,
        "base": f"{vname}/", "en_shards": EN_SHARDS, "vi_shards": VI_SHARDS, "hash": "fnv1a32",
        "prefix": {"len": 2, "max_len": MAX_KEY, "space": SPACE, "other": OTHER, "split": split,
                   "split_bytes": SPLIT_BYTES},
        "relations": {v: k for k, v in REL.items()},
        "counts": {"en_headwords": n_en, "entries": n_entries, "entries_ai": n_entries_ai, "vi_words": n_vi,
                   "forms": len(form_items), "prefix_files": len(groups), "sources": len(sources)},
        "words_order": "fts_rowid",
        "files": len(files), "bytes": total,
        # cho lệnh db_status của bản web (= db.rs Dict::meta và Dict::counts())
        "meta": meta, "db_counts": db_counts,
    }
    _write(STAGE / "manifest.json", dumps(manifest))
    if len(files) > MAX_FILES:
        stop(f"số file của bản {vname} = {len(files)} > ngưỡng {MAX_FILES}.")
    big = [(p.relative_to(STAGE).as_posix(), p.stat().st_size) for p in STAGE.rglob("*")
           if p.is_file() and p.stat().st_size > MAX_FILE_BYTES]
    if big:
        stop(f"có file > {MAX_FILE_BYTES:,} byte: " + ", ".join(f"{p} ({n:,} B)" for p, n in big))

    if OUT.exists():
        shutil.rmtree(OUT)
    STAGE.rename(OUT)
    print(f"\nĐã xuất {OUT} — {n_en} mục Anh, {n_vi} mục Việt, {len(files)} file, {total / 2**20:.1f} MiB chưa nén "
          f"(thời gian dựng {time.time() - t0:.1f} s)\n")
    print_stats(measure(OUT / vname, args.jobs))
    print(f"\nTổng thời gian: {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
