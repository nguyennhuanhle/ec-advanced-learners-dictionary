"""Bước corpus đầy đủ: giới từ đi kèm, kết hợp từ, câu ví dụ theo vị trí cho mọi từ (UC-M06, M10; PLAN-colloc vòng R1).

Dùng:
  python pipeline/corpus_build.py parse [--jobs 12]   phân tích toàn bộ corpus theo khối 100.000 câu (chạy tiếp được:
                                                      khối đã có file trong data/work/corpus/chunks/ thì bỏ qua)
  python pipeline/corpus_build.py report              chỉ dựng lại báo cáo từ corpus.sqlite
  python pipeline/corpus_build.py merge               gộp các khối → data/work/corpus/corpus.sqlite + báo cáo
                                                      _deliverables/colloc-r1/R1-bao-cao.md (chạy lại bao nhiêu lần cũng được)

Luật phân tích (giới từ, cụm, vai trò, điểm câu tốt, lọc nội dung) dùng chung với corpus.py (vòng R0).
Khác R0: phân tích MỌI câu sạch (không lấy mẫu), tắt NER của spaCy cho nhanh, bỏ câu trùng giữa các nguồn (giữ bản
của nguồn đứng trước: Tatoeba CC BY trước Wikipedia CC BY-SA), từ được theo dõi = mục từ một chữ trong DB (danh/động/
tính/trạng từ), từ đi kèm phải là mục từ trong DB. Cần spaCy + en_core_web_sm (người dùng tự cài).
"""
import argparse
import gzip
import hashlib
import json
import math
import multiprocessing as mp
import pickle
import random
import sqlite3
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import corpus as C  # noqa: E402  (luật dùng chung với R0)

sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

ROOT = C.ROOT
WORK = ROOT / "data" / "work" / "corpus"
CHUNKS = WORK / "chunks"
OUT_DB = WORK / "corpus.sqlite"
REPORT = ROOT / "_deliverables" / "colloc-r1"
CHUNK = 100_000

SOURCES = {
    "tatoeba": C.RAW / "tatoeba-eng.tsv.bz2",
    "simplewiki": C.RAW / "simplewiki-cirrus-20261018.json.bz2",
    "enwiki_p0": C.RAW / "enwiki-cirrus-20261018-00000.json.bz2",
    "enwiki_p1": C.RAW / "enwiki-cirrus-20261018-00001.json.bz2",
}
SOURCE_NAME = dict(C.SOURCE_NAME, enwiki_p0="English Wikipedia", enwiki_p1="English Wikipedia")
SOURCE_FAMILY = {"tatoeba": "tatoeba", "simplewiki": "wiki", "enwiki_p0": "wiki", "enwiki_p1": "wiki"}
POSMAP = {"noun": "NOUN", "verb": "VERB", "adj": "ADJ", "adv": "ADV"}
POS4 = set(POSMAP.values())

# Vị trí chính theo từ loại — dùng cho báo cáo độ phủ (UC-U46: mục tiêu ≥ 2 câu mỗi vị trí chính).
MAIN_ROLES = {
    "NOUN": ["làm chủ ngữ", "làm tân ngữ", "sau giới từ"],
    "VERB": ["V-ed (quá khứ)", "V-ing", "sau to (to V)", "bị động"],
    "ADJ": ["trước danh từ", "sau động từ nối"],
    "ADV": ["giữa câu (trước động từ)", "giữa câu (sau động từ)", "cuối câu"],
}
K_ROLE, K_PREP, K_SEQ = 8, 3, 1          # số câu giữ lại khi gộp (trước khi chọn cuối)
OUT_ROLE, OUT_PREP = 5, 2                 # số câu ghi ra mỗi vị trí / mỗi mẫu giới từ
COLL_MIN_N, COLL_MIN_LD, COLL_TOP = 5, 3.0, 20
SEQ_MIN_N = 5
# Từ loại hiếm của một từ (vd. "diamond" động từ, "think" danh từ) chủ yếu là lỗi đoán từ loại của spaCy:
# bỏ (từ, từ loại) chiếm < POS_SHARE_MIN số lần gặp của từ đó (khi từ gặp ≥ POS_SHARE_N lần).
POS_SHARE_MIN, POS_SHARE_N = 0.05, 50


def stable_hash(s):
    return int.from_bytes(hashlib.blake2b(s.lower().encode("utf-8"), digest_size=8).digest(), "little")


def cheap_ok(s):
    """Lọc rẻ trước khi phân tích: câu 5–40 từ, viết hoa đầu câu, kết thúc bằng dấu câu."""
    n = s.count(" ") + 1
    return 5 <= n <= 40 and s[0].isupper() and s[-1] in ".!?\"”"


def iter_chunks():
    """(mã khối, nguồn, câu) theo thứ tự cố định → mã khối giống nhau giữa các lần chạy (để chạy tiếp)."""
    seen = set()
    for src, path in SOURCES.items():
        if not path.exists():
            raise SystemExit(f"Thiếu {path.name} — chạy: python pipeline/fetch.py {src}")
        it = C.iter_tatoeba(path) if src == "tatoeba" else C.iter_cirrus(path)
        buf, k = [], 0
        for s in it:
            s = s.strip()
            if not cheap_ok(s):
                continue
            h = stable_hash(s)
            if h in seen:
                continue
            seen.add(h)
            buf.append(s)
            if len(buf) == CHUNK:
                yield f"{src}-{k:04d}", src, buf
                buf, k = [], k + 1
        if buf:
            yield f"{src}-{k:04d}", src, buf


# ---------- tiến trình con ----------

_nlp = _nodes = _heads = _top = None


def _init():
    global _nlp, _nodes, _heads, _top
    import spacy
    _nlp = spacy.load("en_core_web_sm", exclude=["ner"])
    con = sqlite3.connect(f"file:{C.DB.as_posix()}?mode=ro", uri=True)
    _nodes, _heads = set(), set()
    for hw, pos in con.execute("SELECT DISTINCT headword, pos FROM entry WHERE entry_type='word'"):
        if hw and hw.isalpha() and hw.islower():
            _heads.add(hw)
            if pos in POSMAP:
                _nodes.add((hw, POSMAP[pos]))
    _top = {w for (w,) in con.execute("SELECT word FROM headword WHERE freq_rank <= 20000")}
    con.close()


def _keep(d, key, item, k):
    """Giữ k phần tử điểm cao nhất (item[0] = điểm)."""
    lst = d.get(key)
    if lst is None:
        d[key] = [item]
    elif len(lst) < k:
        lst.append(item)
    else:
        m = min(range(len(lst)), key=lambda i: lst[i][0])
        if item[0] > lst[m][0]:
            lst[m] = item


def _work(args):
    cid, src, sents = args
    t0 = time.time()
    occ, lemf, postok, posprep = Counter(), Counter(), Counter(), Counter()
    prep, seq, coll, rolecnt, rejects = Counter(), Counter(), Counter(), Counter(), Counter()
    ex_role, ex_prep, ex_seq, ex_coll = {}, {}, {}, {}
    texts, n_tok = [], 0
    for doc in _nlp.pipe(sents, batch_size=256):
        for sent in doc.sents:
            scored, q, sid = False, None, None
            for t in sent:
                if not t.is_alpha:
                    continue
                n_tok += 1
                lem = t.lemma_.lower()
                lemf[lem] += 1
                preps = []
                if t.pos_ in POS4:
                    postok[t.pos_] += 1
                    preps = C.prep_children(t)
                    for p in preps:
                        posprep[(t.pos_, p.lower_)] += 1
                key = (lem, t.pos_)
                if key not in _nodes:
                    continue
                occ[key] += 1
                if not scored:
                    q, why = C.quality(sent, _top)
                    scored = True
                    if q is None:
                        rejects[why] += 1
                ex = None
                if q is not None:
                    if sid is None:
                        sid = len(texts)
                        texts.append(sent.text.strip())
                    a = t.idx - sent.start_char
                    ex = (q, sid, a, a + len(t.text))
                for p in preps:
                    pk = key + (p.lower_, C.obj_type(p) or "")
                    prep[pk] += 1
                    if ex:
                        _keep(ex_prep, pk, ex, K_PREP)
                if len({p.lower_ for p in preps}) >= 2:
                    sk = key + (" ".join(f"{p.lower_} {C.obj_type(p) or ''}".strip()
                                         for p in sorted(preps, key=lambda x: x.i)),)
                    seq[sk] += 1
                    if ex:
                        _keep(ex_seq, sk, ex, K_SEQ)
                for pat, disp, cl in C.collocates(t):
                    if cl in _heads:
                        ck = key + (pat, disp, cl)
                        coll[ck] += 1
                        if ex:
                            _keep(ex_coll, ck, ex, 1)
                if ex:
                    for r in C.roles(t):
                        rk = key + (r,)
                        rolecnt[rk] += 1
                        _keep(ex_role, rk, ex, K_ROLE)
    res = {"cid": cid, "src": src, "n_sent": len(sents), "n_tok": n_tok, "occ": occ, "lemf": lemf,
           "postok": postok, "posprep": posprep, "prep": prep, "seq": seq, "coll": coll, "rolecnt": rolecnt,
           "rejects": rejects, "ex_role": ex_role, "ex_prep": ex_prep, "ex_seq": ex_seq, "ex_coll": ex_coll,
           "texts": texts}
    path = CHUNKS / f"{cid}.pkl.gz"
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wb", compresslevel=3) as f:
        pickle.dump(res, f, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    return cid, time.time() - t0, len(sents)


def parse(jobs):
    try:
        import spacy
        spacy.load("en_core_web_sm", exclude=["ner"])
    except ImportError:
        raise SystemExit("Thiếu spaCy. Hãy tự cài: python -m pip install spacy")
    except OSError:
        raise SystemExit("Thiếu model en_core_web_sm. Hãy tự cài: python -m spacy download en_core_web_sm")
    CHUNKS.mkdir(parents=True, exist_ok=True)
    for p in CHUNKS.glob("*.tmp"):
        p.unlink()   # khối dở dang của lần chạy bị ngắt
    done = {p.name.split(".")[0] for p in CHUNKS.glob("*.pkl.gz")}
    print(f"[parse] đã có {len(done)} khối, chạy tiếp với {jobs} tiến trình", flush=True)
    gate = threading.BoundedSemaphore(jobs * 2)   # không nạp cả corpus vào hàng đợi

    def todo():
        for cid, src, sents in iter_chunks():
            if cid in done:
                continue
            gate.acquire()
            yield cid, src, sents

    t0, n_done, n_sent = time.time(), 0, 0
    with mp.Pool(jobs, initializer=_init, maxtasksperchild=20) as pool:
        for cid, secs, n in pool.imap_unordered(_work, todo(), chunksize=1):
            gate.release()
            n_done += 1
            n_sent += n
            rate = n_sent / max(1, time.time() - t0)
            print(f"  {cid}: {n:,} câu, {secs:.0f} s | tổng {n_done} khối mới, {n_sent:,} câu, {rate:,.0f} câu/s",
                  flush=True)
    print(f"[parse] xong {n_done} khối mới trong {(time.time() - t0) / 60:.1f} phút", flush=True)


# ---------- gộp ----------

def merge():
    files = sorted(CHUNKS.glob("*.pkl.gz"))
    if not files:
        raise SystemExit("Chưa có khối nào — chạy: python pipeline/corpus_build.py parse")
    t0 = time.time()
    n_sent, n_tok, rejects = Counter(), Counter(), Counter()
    occ, lemf, postok, posprep = Counter(), Counter(), Counter(), Counter()
    prep, seq, rolecnt = Counter(), Counter(), Counter()
    coll = {}                                   # key -> [n, ví dụ tốt nhất]
    ex_role, ex_prep, ex_seq = {}, {}, {}
    for fi, f in enumerate(files):
        with gzip.open(f, "rb") as fh:
            d = pickle.load(fh)
        src = d["src"]
        n_sent[src] += d["n_sent"]
        n_tok[src] += d["n_tok"]
        for name, tot in (("rejects", rejects), ("occ", occ), ("lemf", lemf), ("postok", postok),
                          ("posprep", posprep), ("prep", prep), ("seq", seq), ("rolecnt", rolecnt)):
            tot.update(d[name])
        for k, n in d["coll"].items():
            e = coll.get(k)
            ex = d["ex_coll"].get(k)
            ex = (ex[0][0], fi, src) + ex[0][1:] if ex else None
            if e is None:
                coll[k] = [n, ex]
            else:
                e[0] += n
                if ex and (e[1] is None or ex[0] > e[1][0]):
                    e[1] = ex
        for dst, srcd, k_keep in ((ex_role, d["ex_role"], K_ROLE), (ex_prep, d["ex_prep"], K_PREP),
                                  (ex_seq, d["ex_seq"], K_SEQ)):
            for k, lst in srcd.items():
                for it in lst:
                    _keep(dst, k, (it[0], fi, src) + it[1:], k_keep)
        if fi % 30 == 29:   # bỏ cặp chỉ gặp 1 lần sau mỗi ~3 triệu câu cho nhẹ bộ nhớ
            for k in [k for k, e in coll.items() if e[0] == 1]:
                del coll[k]
        if fi % 10 == 0:
            print(f"  gộp {fi + 1}/{len(files)} khối, {len(coll):,} cặp ({time.time() - t0:.0f} s)", flush=True)

    total_tok = sum(n_tok.values())
    lem_tot = Counter()
    for (lem, pos), n in occ.items():
        lem_tot[lem] += n
    lowconf = {(lem, pos) for (lem, pos), n in occ.items()
               if lem_tot[lem] >= POS_SHARE_N and n / lem_tot[lem] < POS_SHARE_MIN}
    print(f"[merge] bỏ {len(lowconf):,} cặp (từ, từ loại) hiếm, nghi spaCy đoán sai từ loại", flush=True)
    # --- chọn mẫu giới từ ---
    prep_rows = []
    by_node = defaultdict(Counter)
    objs = defaultdict(Counter)
    for (lem, pos, p, o), n in prep.items():
        by_node[(lem, pos)][p] += n
        if o:
            objs[(lem, pos, p)][o] += n
    for node, cnt in by_node.items():
        if node in lowconf:
            continue
        lem, pos = node
        occ_n = max(1, occ[node])
        for p, n in cnt.items():
            if n < 5:
                continue
            ratio = n / occ_n
            lift = ratio / max(1e-9, posprep[(pos, p)] / max(1, postok[pos]))
            ok = C.prep_pass(n, ratio, lift, pos)
            ob = objs[(lem, pos, p)]
            obj_s = " / ".join(o for o, v in ob.most_common(3) if v >= max(2, 0.15 * n))
            label = ("thường gặp" if ratio >= 0.2 else "ít gặp") if ok else ""
            prep_rows.append((lem, pos, p, obj_s, n, round(ratio, 4), round(lift, 2), int(ok), label))
    passed = {(r[0], r[1], r[2]) for r in prep_rows if r[7]}
    seq_rows = []
    for (lem, pos, sq), n in seq.items():
        ps = [w for w in sq.split() if w not in ("sb", "sth", "doing", "wh-")]
        if n >= SEQ_MIN_N and any((lem, pos, p) in passed for p in ps):
            seq_rows.append((lem, pos, sq, n))
    # --- chọn cụm kết hợp ---
    groups = defaultdict(list)
    for (lem, pos, pat, disp, cl), (n, ex) in coll.items():
        if n < COLL_MIN_N or (lem, pos) in lowconf:
            continue
        fy = lemf[cl]
        ld = 14 + math.log2(2 * n / (occ[(lem, pos)] + fy)) if fy else 0
        if ld >= COLL_MIN_LD:
            groups[(lem, pos, pat)].append((round(ld, 2), n, disp, cl, ex))
    coll_rows = []
    for (lem, pos, pat), items in groups.items():
        items.sort(key=lambda x: (-x[0], -x[1]))
        for rank, (ld, n, disp, cl, ex) in enumerate(items[:COLL_TOP], 1):
            coll_rows.append((lem, pos, pat, disp, cl, n, ld, rank, ex))
    print(f"[merge] {len(prep_rows):,} mẫu giới từ ứng viên ({len(passed):,} đạt), {len(seq_rows):,} mẫu hai giới từ, "
          f"{len(coll_rows):,} cụm ({time.time() - t0:.0f} s)", flush=True)

    # --- lấy chữ của câu ví dụ cần dùng ---
    need = defaultdict(set)
    for lst in list(ex_role.values()) + list(ex_prep.values()) + list(ex_seq.values()):
        for it in lst:
            need[it[1]].add(it[3])
    for r in coll_rows:
        if r[8]:
            need[r[8][1]].add(r[8][3])
    text = {}
    for fi, f in enumerate(files):
        if fi not in need:
            continue
        with gzip.open(f, "rb") as fh:
            tx = pickle.load(fh)["texts"]
        for sid in need[fi]:
            text[(fi, sid)] = tx[sid]
    print(f"[merge] lấy {len(text):,} câu ví dụ ({time.time() - t0:.0f} s)", flush=True)

    def usable(e):
        """Bỏ câu mà từ được tô viết hoa giữa câu (thường là tên riêng: Canning, Gouges) hoặc câu viết hoa kiểu tên
        tác phẩm (Ladies Be Seated)."""
        t = text[(e[1], e[3])]
        if e[4] > 0 and t[e[4]].isupper():
            return False
        if t[e[4] - 1:e[4]] == "-" or t[e[5]:e[5] + 1] == "-":   # nằm trong từ ghép: pre-painted, re-seated
            return False
        words = [w for w in t.split() if w[:1].isalpha()]
        return sum(w[0].isupper() for w in words) <= 0.4 * len(words)

    def pick(lst, k):
        """Chọn k câu điểm cao, bỏ câu trùng, cân nguồn: một họ nguồn tối đa ceil(k*0.6) câu nếu còn câu khác."""
        cands = sorted((e for e in lst if usable(e)), key=lambda e: -e[0])
        out, seen, fam = [], set(), Counter()
        cap = math.ceil(k * 0.6)
        for strict in (True, False):
            for e in cands:
                t = text[(e[1], e[3])]
                if t.lower() in seen:
                    continue
                if strict and fam[SOURCE_FAMILY[e[2]]] >= cap:
                    continue
                seen.add(t.lower())
                fam[SOURCE_FAMILY[e[2]]] += 1
                out.append((e, t))
                if len(out) == k:
                    return out
        return out

    ex_rows = []

    def add_ex(lem, pos, kind, key, e, t):
        ex_rows.append((lem, pos, kind, key, t, e[2], e[4], e[5], len(t.split()), round(e[0], 3)))

    for (lem, pos, role), lst in ex_role.items():
        if (lem, pos) in lowconf:
            continue
        for e, t in pick(lst, OUT_ROLE):
            add_ex(lem, pos, "role", role, e, t)
    for (lem, pos, p, o), lst in ex_prep.items():
        if (lem, pos, p) in passed:
            for e, t in pick(lst, OUT_PREP):
                add_ex(lem, pos, "prep", f"{p}|{o}", e, t)
    seq_keys = {(r[0], r[1], r[2]) for r in seq_rows}
    for k, lst in ex_seq.items():
        if k in seq_keys:
            for e, t in pick(lst, 1):
                add_ex(k[0], k[1], "seq", k[2], e, t)
    for r in coll_rows:
        if r[8] and usable(r[8]):
            add_ex(r[0], r[1], "coll", f"{r[2]}|{r[3]}", r[8], text[(r[8][1], r[8][3])])

    rolecnt = Counter({k: n for k, n in rolecnt.items() if k[:2] not in lowconf})
    write_db(n_sent, n_tok, rejects, prep_rows, seq_rows, coll_rows, ex_rows, rolecnt,
             [k + (n,) for k, n in occ.items() if k not in lowconf])
    report(time.time() - t0)


def write_db(n_sent, n_tok, rejects, prep_rows, seq_rows, coll_rows, ex_rows, rolecnt, node_rows):
    tmp = OUT_DB.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.executescript("""
    CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE prep_pattern(headword TEXT, pos TEXT, prep TEXT, obj TEXT, n INTEGER, ratio REAL, lift REAL,
      pass INTEGER, label TEXT);
    CREATE TABLE prep_seq(headword TEXT, pos TEXT, seq TEXT, n INTEGER);
    CREATE TABLE collocation(headword TEXT, pos TEXT, pattern TEXT, display TEXT, collocate TEXT, n INTEGER,
      logdice REAL, rank INTEGER);
    CREATE TABLE usage_example(headword TEXT, pos TEXT, kind TEXT, key TEXT, text TEXT, source TEXT,
      hl_start INTEGER, hl_end INTEGER, n_words INTEGER, score REAL);
    CREATE TABLE role_count(headword TEXT, pos TEXT, role TEXT, n INTEGER);
    CREATE TABLE node_count(headword TEXT, pos TEXT, n INTEGER);
    """)
    meta = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "n_sent": json.dumps(n_sent), "n_tok": json.dumps(n_tok),
            "rejects": json.dumps(rejects, ensure_ascii=False), "chunk": str(CHUNK)}
    con.executemany("INSERT INTO meta VALUES (?,?)", meta.items())
    con.executemany("INSERT INTO prep_pattern VALUES (?,?,?,?,?,?,?,?,?)", prep_rows)
    con.executemany("INSERT INTO prep_seq VALUES (?,?,?,?)", seq_rows)
    con.executemany("INSERT INTO collocation VALUES (?,?,?,?,?,?,?,?)", [r[:8] for r in coll_rows])
    con.executemany("INSERT INTO usage_example VALUES (?,?,?,?,?,?,?,?,?,?)", ex_rows)
    con.executemany("INSERT INTO role_count VALUES (?,?,?,?)", [k + (n,) for k, n in rolecnt.items()])
    con.executemany("INSERT INTO node_count VALUES (?,?,?)", node_rows)
    for t in ("prep_pattern", "prep_seq", "collocation", "usage_example", "role_count", "node_count"):
        con.execute(f"CREATE INDEX {t}_hw ON {t}(headword, pos)")
    con.commit()
    con.close()
    tmp.replace(OUT_DB)
    print(f"[merge] ghi {OUT_DB} ({OUT_DB.stat().st_size / 1e6:.0f} MB)", flush=True)


# ---------- báo cáo (UC-M10) ----------

def report(secs=0.0):
    REPORT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OUT_DB)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    n_sent, n_tok = Counter(json.loads(meta["n_sent"])), Counter(json.loads(meta["n_tok"]))
    rejects = Counter(json.loads(meta["rejects"]))
    occ = Counter({(a, b): n for a, b, n in con.execute("SELECT headword, pos, n FROM node_count")})
    dct = sqlite3.connect(f"file:{C.DB.as_posix()}?mode=ro", uri=True)
    top = [(w, POSMAP[p]) for w, p in dct.execute(
        "SELECT DISTINCT e.headword, e.pos FROM entry e JOIN headword h ON h.word = e.headword "
        "WHERE h.freq_rank <= 20000 AND e.entry_type = 'word' AND e.pos IN ('noun','verb','adj','adv')")
        if w.isalpha() and w.islower()]
    has_prep = {(a, b) for a, b in con.execute("SELECT DISTINCT headword, pos FROM prep_pattern WHERE pass=1")}
    has_coll = {(a, b) for a, b in con.execute("SELECT DISTINCT headword, pos FROM collocation")}
    ex_n = Counter({(a, b, c): n for a, b, c, n in con.execute(
        "SELECT headword, pos, key, count(*) FROM usage_example WHERE kind='role' GROUP BY 1,2,3")})
    L = ["# Vòng R1 — giới từ đi kèm, kết hợp từ, ví dụ theo vị trí (toàn bộ corpus)\n"]
    L.append(f"Gộp lúc {meta['built_at']} ({secs / 60:.1f} phút). Corpus sau khi lọc rẻ và bỏ câu trùng: "
             + ", ".join(f"{SOURCE_NAME[s]} ({s}) {n_sent[s]:,} câu / {n_tok[s]:,} từ" for s in SOURCES if n_sent[s])
             + f". Tổng {sum(n_sent.values()):,} câu, {sum(n_tok.values()):,} từ.\n")
    L.append("Dữ liệu máy rút ra, **chưa qua AI** (bước M09 sẽ gắn nghĩa, lọc cụm sai, viết bù câu). Chưa vào DB của app.\n")
    L.append("Câu loại khỏi phần ví dụ: " + ", ".join(f"{k} {v:,}" for k, v in rejects.most_common()) + ".\n")
    # độ phủ
    L.append("## Độ phủ trong nhóm từ thông dụng (top 20.000, theo từ loại)\n")
    L.append("| từ loại | số mục | có mẫu giới từ đạt | có kết hợp từ | " + "có ≥ 2 câu ở mọi vị trí chính |")
    L.append("|---|---|---|---|---|")
    for pos in ("NOUN", "VERB", "ADJ", "ADV"):
        ws = [x for x in top if x[1] == pos]
        if not ws:
            continue
        full = sum(all(ex_n[(w, p, r)] >= 2 for r in MAIN_ROLES[pos]) for w, p in ws)
        L.append(f"| {pos.lower()} | {len(ws):,} | {sum(x in has_prep for x in ws) / len(ws):.0%} | "
                 f"{sum(x in has_coll for x in ws) / len(ws):.0%} | {full / len(ws):.0%} |")
    L.append("\nBảng trên tính cả các mục từ loại hiếm hầu như không ai dùng (vd. *diamond* động từ). Chỉ tính mục gặp "
             "≥ 100 lần trong corpus:\n")
    L.append("| từ loại | số mục | có mẫu giới từ đạt | có kết hợp từ | có ≥ 2 câu ở mọi vị trí chính |")
    L.append("|---|---|---|---|---|")
    for pos in ("NOUN", "VERB", "ADJ", "ADV"):
        ws = [x for x in top if x[1] == pos and occ[x] >= 100]
        if not ws:
            continue
        full = sum(all(ex_n[(w, p, r)] >= 2 for r in MAIN_ROLES[pos]) for w, p in ws)
        L.append(f"| {pos.lower()} | {len(ws):,} | {sum(x in has_prep for x in ws) / len(ws):.0%} | "
                 f"{sum(x in has_coll for x in ws) / len(ws):.0%} | {full / len(ws):.0%} |")
    L.append("\nTừng vị trí chính (tỉ lệ mục có ≥ 2 câu, tính mọi mục):\n")
    for pos in ("NOUN", "VERB", "ADJ", "ADV"):
        ws = [x for x in top if x[1] == pos]
        if ws:
            L.append(f"- {pos.lower()}: " + " · ".join(
                f"{r} {sum(ex_n[(w, p, r)] >= 2 for w, p in ws) / len(ws):.0%}" for r in MAIN_ROLES[pos]))
    # bộ từ kiểm tra
    L.append("\n---\n\n## Bộ từ kiểm tra\n")
    for lem, pos in C.TARGETS:
        L.append(f"\n### {lem} ({pos.lower()}) — gặp {occ[(lem, pos)]:,} lần\n")
        rows = con.execute("SELECT prep, obj, n, ratio, lift, label FROM prep_pattern WHERE headword=? AND pos=? "
                           "AND pass=1 ORDER BY n DESC", (lem, pos)).fetchall()
        cand = con.execute("SELECT prep, n, ratio, lift FROM prep_pattern WHERE headword=? AND pos=? AND pass=0 "
                           "ORDER BY n DESC LIMIT 5", (lem, pos)).fetchall()
        L.append("**Đi với giới từ**: " + ("; ".join(
            f"**{lem} {p} {o}** ({lb}, {n:,}, {r:.0%}, ×{lf:.1f})" for p, o, n, r, lf, lb in rows) or "(không có)"))
        if cand:
            L.append("  - dưới ngưỡng (ứng viên cho AI): " + ", ".join(f"{p} ({n:,}, {r:.1%}, ×{lf:.1f})"
                                                                       for p, n, r, lf in cand))
        sq = con.execute("SELECT seq, n FROM prep_seq WHERE headword=? AND pos=? ORDER BY n DESC LIMIT 3",
                         (lem, pos)).fetchall()
        if sq:
            L.append("  - hai giới từ: " + "; ".join(f"{lem} {s} ({n})" for s, n in sq))
        for p, o, *_ in rows[:2]:
            for t, src in con.execute("SELECT text, source FROM usage_example WHERE headword=? AND pos=? AND kind='prep' "
                                      "AND key=? LIMIT 1", (lem, pos, f"{p}|{o}")):
                L.append(f"  - *{p}*: {t} — {SOURCE_NAME[src]}")
        L.append("\n**Kết hợp từ**:")
        for (pat,) in con.execute("SELECT pattern FROM collocation WHERE headword=? AND pos=? GROUP BY pattern "
                                  "ORDER BY sum(n) DESC", (lem, pos)).fetchall():
            items = con.execute("SELECT display, n, logdice FROM collocation WHERE headword=? AND pos=? AND pattern=? "
                                "ORDER BY rank LIMIT 10", (lem, pos, pat)).fetchall()
            L.append(f"- {pat}: " + " · ".join(f"{d} ({n:,}; {ld:.1f})" for d, n, ld in items))
        L.append("\n**Ví dụ theo vị trí** (số câu đạt / 2 câu đầu):")
        for role, n in con.execute("SELECT role, n FROM role_count WHERE headword=? AND pos=? ORDER BY n DESC",
                                   (lem, pos)).fetchall():
            exs = con.execute("SELECT text, source, hl_start, hl_end FROM usage_example WHERE headword=? AND pos=? "
                              "AND kind='role' AND key=? ORDER BY score DESC LIMIT 2", (lem, pos, role)).fetchall()
            L.append(f"- **{role}** ({n:,}): " + " | ".join(
                f"{t[:a]}**{t[a:b]}**{t[b:]} — *{SOURCE_NAME[s]}*" for t, s, a, b in exs))
    # kiểm mắt
    rnd = random.Random(11)
    words = rnd.sample(top, min(400, len(top)))
    sample = []
    for w, p in words:
        r = con.execute("SELECT key, text, source, hl_start, hl_end FROM usage_example WHERE headword=? AND pos=? "
                        "AND kind='role' ORDER BY random() LIMIT 1", (w, p)).fetchone()
        if r:
            sample.append((w, p) + r)
        if len(sample) == 50:
            break
    L.append("\n---\n\n## 50 câu ngẫu nhiên (từ ngẫu nhiên trong top 20.000) kèm nhãn vị trí máy gắn\n")
    for i, (w, p, role, t, s, a, b) in enumerate(sample, 1):
        L.append(f"{i}. [{w} {p.lower()} → {role}] {t[:a]}**{t[a:b]}**{t[b:]} — *{SOURCE_NAME[s]}*")
    # dung lượng
    topset = set(top)
    nbytes = 0
    for hw, pos, txt in con.execute("SELECT headword, pos, text FROM usage_example"):
        if (hw, pos) in topset:
            nbytes += len(txt.encode()) + 30
    for hw, pos, disp in con.execute("SELECT headword, pos, display FROM collocation"):
        if (hw, pos) in topset:
            nbytes += len(disp) + 20
    L.append(f"\n---\n\n## Dung lượng\n\nPhần của top 20.000 (câu + cụm, chưa nén): ~{nbytes / 1e6:.0f} MB "
             f"→ ước ~{nbytes / 3.5e6:.0f} MB gzip. `corpus.sqlite` (mọi từ, có chỉ mục): "
             f"{OUT_DB.stat().st_size / 1e6:.0f} MB.\n")
    path = REPORT / "R1-bao-cao.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[xong] {path}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["parse", "merge", "report"])
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--only", help="chỉ dùng các nguồn này (cách nhau bởi dấu phẩy) — để thử nhanh")
    a = ap.parse_args()
    if a.only:
        for k in list(SOURCES):
            if k not in a.only.split(","):
                del SOURCES[k]
    if a.mode == "parse":
        parse(a.jobs)
    elif a.mode == "report":
        report()
    else:
        merge()


if __name__ == "__main__":
    main()
