"""Bước corpus: giới từ đi kèm, kết hợp từ, câu ví dụ theo vị trí (UC-M06; PLAN-colloc).

Vòng R0 (thử nhỏ): chỉ chạy cho bộ từ thử TARGETS, in kết quả ra _deliverables/colloc-r0/ để đọc bằng mắt.
Không ghi vào DB.

Dùng: python pipeline/corpus.py r0 [--cap 3000] [--jobs 4]
     python pipeline/corpus.py collect   (chỉ đọc corpus + lọc ứng viên vào cache, không cần spaCy)
Cần spaCy + en_core_web_sm (người dùng tự cài, pipeline không tự cài).

Cách làm:
  1. Đọc câu từ Tatoeba (eng) và Simple English Wikipedia (bản CirrusSearch, đã là chữ thuần), tách câu bằng regex.
  2. Lọc nhanh câu có dạng biến đổi của từ thử; mỗi (từ, nguồn) giữ ngẫu nhiên tối đa `cap` câu (reservoir) để không lệch
     về đầu file. Lấy thêm một mẫu ngẫu nhiên câu bất kỳ làm nền (tần suất lemma, tỉ lệ giới từ nền).
  3. spaCy phân tích cú pháp → mẫu giới từ (giới từ con trực tiếp của từ, so với tỉ lệ nền của từ loại),
     cụm kết hợp theo quan hệ phụ thuộc (logDice), vai trò/dạng của từ trong từng câu, điểm "câu tốt".
"""
import argparse
import bz2
import json
import math
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
DB = ROOT / "data" / "build" / "dict-core.sqlite"
WORK = ROOT / "data" / "work" / "colloc-r0"
OUT = ROOT / "_deliverables" / "colloc-r0"

SOURCES = {
    "tatoeba": RAW / "tatoeba-eng.tsv.bz2",
    "simplewiki": RAW / "simplewiki-cirrus-20261018.json.bz2",
}
SOURCE_NAME = {"tatoeba": "Tatoeba", "simplewiki": "Simple English Wikipedia"}

# Bộ từ thử R0: (lemma, từ loại spaCy). Chọn để có đủ loại giới từ (depend on, responsible for/to, interested in,
# arrive at/in), cụm V+N (decision, advice), trạng từ (quickly) và vài từ hay ra đề.
TARGETS = [
    ("depend", "VERB"), ("rely", "VERB"), ("arrive", "VERB"), ("succeed", "VERB"), ("insist", "VERB"),
    ("prevent", "VERB"), ("contribute", "VERB"), ("complain", "VERB"), ("apologize", "VERB"), ("accuse", "VERB"),
    ("increase", "VERB"), ("increase", "NOUN"), ("decide", "VERB"), ("make", "VERB"),
    ("decision", "NOUN"), ("advice", "NOUN"), ("research", "NOUN"), ("impact", "NOUN"), ("effect", "NOUN"),
    ("access", "NOUN"), ("attention", "NOUN"), ("opportunity", "NOUN"), ("solution", "NOUN"), ("reason", "NOUN"),
    ("responsible", "ADJ"), ("interested", "ADJ"), ("afraid", "ADJ"), ("aware", "ADJ"), ("capable", "ADJ"),
    ("similar", "ADJ"), ("different", "ADJ"), ("good", "ADJ"), ("important", "ADJ"),
    ("quickly", "ADV"), ("carefully", "ADV"), ("recently", "ADV"),
]

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“])")
BAD_CHARS = re.compile(r"[()\[\]{}|=<>@#/\\_*~^]|https?:|www\.")
PERSONAL = re.compile(r"\S+@\S+|\+?\d[\d\s().-]{7,}\d")
# Lọc nội dung cho câu dùng làm đề (UC CANNOT). BLOCK: loại hẳn. SOFT (R1): không loại — sách sử, khoa học hay có
# "killed in the war", "drug" (thuốc) — nhưng trừ điểm để chỉ được chọn khi không có câu khác.
BLOCK = {
    "fuck", "fucking", "fucked", "shit", "bitch", "bastard", "cunt", "dick", "cock", "pussy", "asshole", "whore", "slut",
    "nigger", "faggot", "retard", "rape", "raped", "rapist", "porn", "pornography", "pornographic", "sex", "sexual",
    "sexually", "naked", "nude", "masturbate", "orgasm", "penis", "vagina", "erotic", "prostitute", "prostitution",
    "suicide", "behead", "beheaded", "torture", "tortured", "massacre", "genocide", "goddamn", "cocaine", "heroin",
    "molest", "molested", "incest", "pedophile", "terrorist", "terrorism", "slaughter", "slaughtered",
}
SOFT = {"kill", "killed", "killing", "kills", "murder", "murdered", "corpse", "drug", "drugs", "damn", "hell", "crap",
        "blood", "bloody", "gun", "shoot", "shot", "dead", "die", "died", "death", "war", "bomb", "weapon", "alcohol",
        "drunk", "beer", "wine", "cigarette", "smoke", "divorce", "religion", "god"}
OPENING_PRON = {"he", "she", "it", "they", "this", "that", "these", "those", "him", "her", "them", "his", "its", "their"}
SB_WORDS = {
    "me", "you", "him", "her", "us", "them", "someone", "somebody", "anyone", "anybody", "everyone", "everybody",
    "nobody", "people", "person", "man", "woman", "men", "women", "child", "children", "parent", "friend", "teacher",
    "family", "student", "doctor", "who", "whom", "mother", "father", "boss", "government", "team", "customer",
    "other", "others", "parents", "husband", "wife", "son", "daughter", "brother", "sister", "colleague",
    "friends", "students", "teachers", "kids", "kid", "boy", "girl", "boys", "girls", "baby", "guest", "guests",
    "neighbour", "neighbor", "neighbours", "neighbors", "staff", "employee", "employees", "worker", "workers", "public",
    "audience", "user", "users", "patient", "patients", "client", "clients", "member", "members", "leader", "leaders",
    "partner", "partners", "relative", "relatives", "anyone", "parent", "adult", "adults", "citizen", "citizens",
    "officer", "police", "king", "queen", "god", "himself", "herself", "themselves", "myself", "yourself", "ourselves",
}
# Giới từ không tính là "giới từ đi kèm" (so sánh): more quickly than, as quickly as.
PREP_SKIP = {"than", "as"}
# Danh từ chỉ lượng cho mẫu "a piece of advice".
QUANT = {"piece", "bit", "word", "item", "lot", "number", "couple", "deal", "amount", "series", "kind", "sort", "type",
         "range", "variety", "set", "pair", "sheet", "slice", "cup", "glass", "bottle", "loaf", "bar", "drop", "grain",
         "handful", "flash", "stroke", "gust", "burst", "fit", "round", "spell", "source", "lack", "wealth"}
COLL_SKIP_LEMMA = {"not", "so", "very", "too", "also", "just", "then", "only", "even", "still", "there", "here",
                   "as", "how", "when", "why", "where", "more", "most", "be", "have", "do", "-PRON-"}


# ---------- đọc corpus ----------

def iter_tatoeba(path):
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) == 3 and parts[1] == "eng":
                yield parts[2]


def iter_cirrus(path):
    """Bản xuất CirrusSearch: mỗi dòng một JSON; dòng tài liệu có trường "text" (chữ thuần, các đoạn nối bằng dấu cách).
    Dòng {"index": …} (định dạng cũ) không có "text" nên tự bị bỏ."""
    with bz2.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            try:
                doc = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = doc.get("text") if isinstance(doc, dict) else None
            if not text or doc.get("namespace", 0) != 0:
                continue
            for s in SENT_SPLIT.split(text):
                s = s.strip()
                if 20 <= len(s) <= 300:
                    yield s


def iter_source(key):
    path = SOURCES[key]
    if not path.exists():
        raise SystemExit(f"Thiếu {path.name} — chạy: python pipeline/fetch.py {key}")
    return iter_tatoeba(path) if key == "tatoeba" else iter_cirrus(path)


def surface_forms(con, lemmas):
    """Dạng biến đổi của mỗi lemma (bảng lookup_index, chỉ quan hệ inflection, bỏ dạng 'nonstandard/humorous')."""
    forms = defaultdict(set)
    for lem in lemmas:
        forms[lem].add(lem)
    q = ("SELECT form_norm, headword, tags FROM lookup_index WHERE relation='inflection' AND headword IN (%s)"
         % ",".join("?" * len(lemmas)))
    for form, head, tags in con.execute(q, list(lemmas)):
        if tags and any(x in tags for x in ("nonstandard", "humorous", "obsolete", "archaic", "dialect")):
            continue
        if form and form.isalpha():
            forms[head].add(form.lower())
    if "apologize" in forms:
        forms["apologize"] |= {"apologise", "apologises", "apologised", "apologising"}
    return forms


def collect(cap, bg_size, seed=1):
    """Đọc mọi câu, giữ reservoir theo (lemma, nguồn) + mẫu nền. Cache ở data/work/colloc-r0/cand.json."""
    cache = WORK / f"cand-{cap}-{bg_size}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    lemmas = sorted({l for l, _ in TARGETS})
    forms = surface_forms(con, lemmas)
    form2lem = defaultdict(set)
    for lem, fs in forms.items():
        for f in fs:
            form2lem[f].add(lem)
    rx = re.compile(r"\b(" + "|".join(sorted(map(re.escape, form2lem), key=len, reverse=True)) + r")\b", re.I)
    rnd = random.Random(seed)
    res = defaultdict(list)          # "lemma|src" -> câu
    seen = Counter()                 # số câu có lemma (theo bề mặt) mỗi "lemma|src"
    bg, n_sent, n_tok = {}, Counter(), Counter()
    for src in SOURCES:
        t0 = time.time()
        bgl = []
        for i, s in enumerate(iter_source(src)):
            n_sent[src] += 1
            n_tok[src] += s.count(" ") + 1
            # mẫu nền: reservoir câu bất kỳ
            if len(bgl) < bg_size:
                bgl.append(s)
            else:
                j = rnd.randrange(n_sent[src])
                if j < bg_size:
                    bgl[j] = s
            hit = {lem for m in rx.finditer(s) for lem in form2lem[m.group(1).lower()]}
            for lem in hit:
                k = f"{lem}|{src}"
                seen[k] += 1
                if len(res[k]) < cap:
                    res[k].append(s)
                else:
                    j = rnd.randrange(seen[k])
                    if j < cap:
                        res[k][j] = s
            if i and i % 500_000 == 0:
                print(f"  {src}: {i:,} câu ({time.time() - t0:.0f} s)", flush=True)
        bg[src] = bgl
        print(f"[đọc] {src}: {n_sent[src]:,} câu, ~{n_tok[src]:,} từ ({time.time() - t0:.0f} s)", flush=True)
    data = {"cand": res, "seen": seen, "bg": bg, "n_sent": n_sent, "n_tok": n_tok}
    WORK.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return json.loads(json.dumps(data))


# ---------- phân tích một câu ----------

def obj_type(prep):
    """Kiểu bổ ngữ sau giới từ: sb / sth / doing sth / wh-."""
    kids = [c for c in prep.children if c.dep_ in ("pobj", "pcomp")]
    if not kids:
        return None
    o = kids[0]
    if o.tag_ == "VBG":
        return "doing sth"
    if o.dep_ == "pcomp" and any(c.tag_ in ("WDT", "WP", "WRB") or c.lower_ == "whether" for c in o.subtree):
        return "wh-"
    if o.lower_ in ("what", "how", "whether", "who", "where", "when", "why"):
        return "wh-"
    if o.lower_ in SB_WORDS or o.lemma_.lower() in SB_WORDS or o.ent_type_ == "PERSON":
        return "sb"
    if o.pos_ == "PROPN":
        return None   # tên riêng: không đoán người hay vật (R1 tắt NER cho nhanh)
    return "sth"


def prep_children(t):
    """Giới từ là con trực tiếp của từ. spaCy gắn 'upon' là SCONJ nên nhận cả SCONJ khi quan hệ là prep."""
    return [c for c in t.children if c.dep_ in ("prep", "dative") and c.pos_ in ("ADP", "SCONJ")
            and c.lower_ not in PREP_SKIP]


def roles(t):
    """Nhãn vị trí/dạng của từ trong câu (UC-U46). Một lần xuất hiện có thể có nhiều nhãn."""
    out = []
    pos = t.pos_
    if pos == "NOUN":
        d = t.dep_
        if d in ("nsubj", "nsubjpass"):
            out.append("làm chủ ngữ")
        elif d in ("dobj",):
            out.append("làm tân ngữ")
        elif d == "pobj":
            out.append("sau giới từ")
        elif d == "compound":
            out.append("bổ nghĩa cho danh từ")
        elif d in ("attr",):
            out.append("sau be (bổ ngữ)")
        if t.tag_ == "NNS":
            out.append("số nhiều")
    elif pos == "VERB":
        out.append({"VB": "V (nguyên mẫu)", "VBP": "V (hiện tại)", "VBZ": "V-s", "VBD": "V-ed (quá khứ)",
                    "VBG": "V-ing", "VBN": "V3 (phân từ II)"}.get(t.tag_, t.tag_))
        if any(c.dep_ in ("auxpass", "nsubjpass") for c in t.children):
            out.append("bị động")
        if any(c.dep_ == "aux" and c.tag_ == "TO" for c in t.children):
            out.append("sau to (to V)")
        if t.tag_ == "VBG" and t.dep_ in ("csubj", "nsubj"):
            out.append("V-ing làm chủ ngữ")
        if t.tag_ == "VBG" and t.dep_ == "pcomp":
            out.append("V-ing sau giới từ")
    elif pos == "ADJ":
        if t.dep_ == "amod":
            # "the person responsible for…": amod nhưng đứng sau danh từ
            out.append("trước danh từ" if t.i < t.head.i else "sau danh từ")
        elif t.dep_ in ("acomp", "attr") or t.head.lemma_ in ("be", "seem", "become", "feel", "look", "remain", "get"):
            out.append("sau động từ nối")
        if t.tag_ == "JJR" or any(c.lower_ in ("more", "less") for c in t.children):
            out.append("so sánh hơn")
        if t.tag_ == "JJS" or any(c.lower_ in ("most", "least") for c in t.children):
            out.append("so sánh nhất")
    elif pos == "ADV":
        words = [w for w in t.sent if not w.is_punct]
        if words and words[0] == t:
            out.append("đầu câu")
        elif all(w.is_punct for w in t.doc[t.i + 1:t.sent.end]):
            out.append("cuối câu")
        elif t.head.pos_ in ("ADJ", "ADV") and t.i < t.head.i:
            out.append("trước tính từ/trạng từ")
        elif t.head.pos_ in ("VERB", "AUX") and t.i < t.head.i:
            out.append("giữa câu (trước động từ)")
        else:
            out.append("giữa câu (sau động từ)")
        if t.tag_ == "RBR" or any(c.lower_ in ("more", "less") for c in t.children):
            out.append("so sánh hơn")
        if t.tag_ == "RBS" or any(c.lower_ in ("most", "least") for c in t.children):
            out.append("so sánh nhất")
    return out


def collocates(t):
    """Cặp (mẫu, cụm hiển thị, lemma đi kèm) theo quan hệ phụ thuộc (UC-U43)."""
    out = []
    pos, h = t.pos_, t.head

    def ok(w):
        if not w.is_alpha or w.pos_ in ("PROPN", "PRON", "NUM") or w.lemma_.lower() in COLL_SKIP_LEMMA:
            return False
        return w.pos_ == "VERB" or not w.is_stop   # spaCy coi make/take/give là stop word (chỉ dạng nguyên mẫu)

    def verb_phrase(v):
        prt = [c.lower_ for c in v.children if c.dep_ == "prt"]
        return " ".join([v.lemma_.lower()] + prt)

    if pos == "NOUN":
        for c in t.children:
            if c.dep_ == "amod" and c.pos_ == "ADJ" and c.i < t.i and ok(c):
                out.append(("ADJ + N", c.lemma_.lower(), c.lemma_.lower()))
            elif c.dep_ == "compound" and c.pos_ == "NOUN" and ok(c):
                out.append(("N + N", f"{c.lemma_.lower()} {t.lemma_.lower()}", c.lemma_.lower()))
        if t.dep_ == "compound" and h.pos_ == "NOUN" and ok(h):
            out.append(("N + N", f"{t.lemma_.lower()} {h.lemma_.lower()}", h.lemma_.lower()))
        if t.dep_ in ("dobj", "nsubjpass") and h.pos_ == "VERB" and ok(h):
            out.append(("V + N", verb_phrase(h), h.lemma_.lower()))
        if t.dep_ == "nsubj" and h.pos_ == "VERB" and ok(h):
            out.append(("N + V", h.lemma_.lower(), h.lemma_.lower()))
        if t.dep_ == "pobj" and h.dep_ == "prep" and h.lower_ == "of" and h.head.lemma_.lower() in QUANT:
            q = h.head.lemma_.lower()
            out.append(("lượng từ + of + N", f"{'an' if q[0] in 'aeiou' else 'a'} {q} of", q))
    elif pos == "VERB":
        for c in t.children:
            if c.dep_ in ("dobj", "nsubjpass") and c.pos_ == "NOUN" and ok(c):
                out.append(("V + N", c.lemma_.lower(), c.lemma_.lower()))
            elif c.dep_ == "advmod" and c.pos_ == "ADV" and ok(c):
                out.append(("V + ADV (trước/sau)", c.lemma_.lower(), c.lemma_.lower()))
    elif pos == "ADJ":
        for c in t.children:
            if c.dep_ == "advmod" and c.pos_ == "ADV" and ok(c):
                out.append(("ADV + ADJ", c.lemma_.lower(), c.lemma_.lower()))
        if t.dep_ == "amod" and h.pos_ == "NOUN" and t.i < h.i and ok(h):
            out.append(("ADJ + N", h.lemma_.lower(), h.lemma_.lower()))
        if t.dep_ in ("acomp", "oprd") and h.pos_ in ("VERB", "AUX") and h.lemma_ != "be" and ok(h):
            out.append(("V + ADJ", h.lemma_.lower(), h.lemma_.lower()))
    elif pos == "ADV":
        if t.dep_ == "advmod" and h.pos_ == "VERB" and ok(h):
            out.append(("V + ADV", h.lemma_.lower(), h.lemma_.lower()))
        if t.dep_ == "advmod" and h.pos_ in ("ADJ", "ADV") and t.i < h.i and ok(h):
            out.append(("ADV + ADJ", h.lemma_.lower(), h.lemma_.lower()))
    return out


def quality(sent, top):
    """Điểm câu tốt kiểu GDEX (cao = tốt) hoặc None nếu loại. Trả cả lý do loại để thống kê."""
    text = sent.text.strip()
    words = [w for w in sent if not w.is_punct and not w.is_space]
    n = len(words)
    if n < 5 or n > 35:
        return None, "độ dài"
    if not text[0].isupper() or text[-1] not in ".!?":
        return None, "không trọn câu"
    if BAD_CHARS.search(text) or text.count('"') % 2:
        return None, "ký tự lạ"
    if PERSONAL.search(text) or sum(ch.isdigit() for ch in text) > 4:
        return None, "số/thông tin cá nhân"
    if any(w.lower_ in BLOCK or w.lemma_.lower() in BLOCK for w in words):
        return None, "nội dung nhạy cảm"
    soft = sum(w.lower_ in SOFT for w in words)
    propn = sum(w.pos_ == "PROPN" for w in words) / n
    if propn > 0.3:
        return None, "nhiều tên riêng"
    common = sum(w.lemma_.lower() in top or w.lower_ in top for w in words if w.is_alpha) / max(1, sum(w.is_alpha for w in words))
    score = 2.0 * common - 0.4 * sum(w.pos_ == "PROPN" for w in words) - 1.0 * soft
    if 8 <= n <= 20:
        score += 1.0
    if words[0].lower_ in OPENING_PRON:
        score -= 0.6
    return round(score, 3), None


# ---------- chạy R0 ----------

def run_r0(cap, bg_size, jobs):
    try:
        import spacy
    except ImportError:
        raise SystemExit("Thiếu spaCy. Hãy tự cài rồi chạy lại:\n  python -m pip install spacy\n"
                         "  python -m spacy download en_core_web_sm")
    try:
        nlp = spacy.load("en_core_web_sm")
    except OSError:
        raise SystemExit("Thiếu model en_core_web_sm. Hãy tự cài: python -m spacy download en_core_web_sm")
    t_start = time.time()
    data = collect(cap, bg_size)
    con = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    top = {w for (w,) in con.execute("SELECT word FROM headword WHERE freq_rank <= 20000")}
    want = defaultdict(set)
    for lem, pos in TARGETS:
        want[lem].add(pos)

    # câu duy nhất cần phân tích + nguồn
    texts = {}
    for k, sents in data["cand"].items():
        src = k.split("|")[1]
        for s in sents:
            texts.setdefault(s, src)
    bg_texts = [(s, src) for src, ss in data["bg"].items() for s in ss]
    print(f"[spaCy] phân tích {len(texts):,} câu ứng viên + {len(bg_texts):,} câu nền (jobs={jobs})", flush=True)

    # --- nền: tần suất lemma (theo từ loại) và tỉ lệ giới từ con theo từ loại ---
    t0 = time.time()
    bg_lemma = Counter()
    bg_pos_tok = Counter()
    bg_pos_prep = Counter()
    bg_tokens = 0
    for doc in nlp.pipe((s for s, _ in bg_texts), batch_size=500, n_process=jobs):
        for w in doc:
            if w.is_alpha:
                bg_tokens += 1
                bg_lemma[w.lemma_.lower()] += 1
                if w.pos_ in ("NOUN", "VERB", "ADJ", "ADV"):
                    bg_pos_tok[w.pos_] += 1
                    for c in prep_children(w):
                        bg_pos_prep[(w.pos_, c.lower_)] += 1
    print(f"  nền xong ({time.time() - t0:.0f} s, {bg_tokens:,} từ)", flush=True)
    total_tok = sum(data["n_tok"].values())

    # --- ứng viên ---
    t0 = time.time()
    occ = Counter()                      # (lem,pos) -> số lần phân tích được
    prep_cnt = defaultdict(Counter)      # (lem,pos) -> (prep, obj) -> n
    prep_seq = defaultdict(Counter)      # (lem,pos) -> "on sb for sth" -> n
    prep_ex = defaultdict(lambda: defaultdict(list))
    coll_cnt = defaultdict(Counter)      # (lem,pos) -> (pattern, display, lemma) -> n
    coll_ex = defaultdict(lambda: defaultdict(list))
    role_ex = defaultdict(lambda: defaultdict(list))   # (lem,pos) -> role -> [(score, text, src, i0, i1)]
    rejects = Counter()
    audit = defaultdict(list)
    items = list(texts.items())
    for (s, src), doc in zip(items, nlp.pipe((s for s, _ in items), batch_size=500, n_process=jobs)):
        for sent in doc.sents:
            q, why = None, "chưa chấm"
            for t in sent:
                lem = t.lemma_.lower()
                if lem not in want or t.pos_ not in want[lem]:
                    continue
                key = (lem, t.pos_)
                if why == "chưa chấm":
                    q, why = quality(sent, top)
                    if q is None:
                        rejects[why] += 1
                occ[key] += 1
                ex = None
                if q is not None:
                    ex = (q, sent.text.strip(), src, t.idx - sent.start_char, t.idx - sent.start_char + len(t.text))
                # giới từ
                preps = prep_children(t)
                for p in preps:
                    pk = (p.lower_, obj_type(p) or "")
                    prep_cnt[key][pk] += 1
                    if ex and len(prep_ex[key][pk]) < 40:
                        prep_ex[key][pk].append(ex)
                if len({p.lower_ for p in preps}) >= 2:   # hai giới từ khác nhau (bỏ "not on X but on Y")
                    seq = " ".join(f"{p.lower_} {obj_type(p) or ''}".strip() for p in sorted(preps, key=lambda x: x.i))
                    prep_seq[key][seq] += 1
                    if ex and len(prep_ex[key][("SEQ", seq)]) < 40:
                        prep_ex[key][("SEQ", seq)].append(ex)
                # kết hợp từ
                for c in collocates(t):
                    coll_cnt[key][c] += 1
                    if ex and len(coll_ex[key][c]) < 40:
                        coll_ex[key][c].append(ex)
                # vị trí
                rs = roles(t)
                if ex:
                    for r in rs:
                        role_ex[key][r].append(ex)
                    if len(audit[key]) < 200:
                        audit[key].append((key, rs, ex))
    print(f"  ứng viên xong ({time.time() - t0:.0f} s)", flush=True)

    report(data, total_tok, bg_tokens, bg_lemma, bg_pos_tok, bg_pos_prep, occ, prep_cnt, prep_seq, prep_ex,
           coll_cnt, coll_ex, role_ex, rejects, audit, cap, time.time() - t_start)


# Ngưỡng mẫu giới từ theo từ loại (R1): danh từ đi với nhiều giới từ rải rác nên ngưỡng thấp hơn.
PREP_MIN = {"NOUN": (8, 0.010, 2.0), "VERB": (8, 0.015, 2.5), "ADJ": (8, 0.015, 2.5), "ADV": (8, 0.02, 3.0)}


def prep_pass(c, ratio, lift, pos="VERB"):
    n_min, r_min, l_min = PREP_MIN[pos]
    return c >= n_min and ratio >= r_min and lift >= l_min


def bold(ex):
    _, text, src, a, b = ex
    return f"{text[:a]}**{text[a:b]}**{text[b:]} — *{SOURCE_NAME[src]}*"


def best(exs, k):
    seen, out = set(), []
    for e in sorted(exs, key=lambda e: -e[0]):
        if e[1].lower() not in seen:
            seen.add(e[1].lower())
            out.append(e)
        if len(out) == k:
            break
    return out


def report(data, total_tok, bg_tokens, bg_lemma, bg_pos_tok, bg_pos_prep, occ, prep_cnt, prep_seq, prep_ex,
           coll_cnt, coll_ex, role_ex, rejects, audit, cap, secs):
    OUT.mkdir(parents=True, exist_ok=True)
    L = []
    L.append("# Vòng R0 — thử giới từ đi kèm, kết hợp từ, ví dụ theo vị trí\n")
    L.append(f"Chạy {time.strftime('%Y-%m-%d %H:%M')}, {secs / 60:.1f} phút. Corpus: "
             + ", ".join(f"{SOURCE_NAME[s]} {data['n_sent'][s]:,} câu (~{data['n_tok'][s]:,} từ)" for s in SOURCES)
             + f". Mỗi (từ, nguồn) phân tích tối đa {cap:,} câu chọn ngẫu nhiên.\n")
    L.append("Đây là **dữ liệu máy rút ra, chưa qua AI**, để đọc bằng mắt và chốt ngưỡng. Chưa vào DB/app.\n")
    L.append("Ngưỡng R0: mẫu giới từ cần n ≥ 8, tỉ lệ ≥ 1,5% và ×nền ≥ 2,5 (in đậm = đạt); \"thường gặp\" khi tỉ lệ ≥ 20%. "
             "Cụm kết hợp cần ≥ 3 lần và logDice ≥ 3.\n")
    L.append("Cách đọc: *n* = số lần gặp trong câu đã phân tích; *tỉ lệ* = n / số lần gặp từ; *×nền* = tỉ lệ này gấp mấy lần "
             "tỉ lệ giới từ đó đi sau một từ cùng từ loại bất kỳ (cao = đặc trưng của từ); *logDice* = độ gắn kết (≥ 7 thường là cụm thật).\n")
    L.append("Câu bị loại khỏi phần ví dụ (vẫn dùng để đếm giới từ/cụm): "
             + ", ".join(f"{k} {v:,}" for k, v in rejects.most_common()) + ".\n")
    sizes = []
    for lem, pos in TARGETS:
        key = (lem, pos)
        n = occ[key]
        seen = sum(data["seen"].get(f"{lem}|{s}", 0) for s in SOURCES)
        scale = seen / max(1, sum(min(cap, data["seen"].get(f"{lem}|{s}", 0)) for s in SOURCES))
        L.append(f"\n---\n\n## {lem} ({pos.lower()})\n")
        L.append(f"Câu có dạng của từ trong corpus: {seen:,}; đã phân tích: {n:,} lần gặp đúng từ loại.\n")
        # giới từ
        L.append("### Đi với giới từ\n")
        base_n = bg_pos_tok[pos] or 1
        rows = []
        by_prep = Counter()
        for (p, o), c in prep_cnt[key].items():
            by_prep[p] += c
        for p, c in by_prep.most_common(8):
            ratio = c / max(1, n)
            lift = ratio / max(1e-6, bg_pos_prep[(pos, p)] / base_n)
            objs = Counter({o: v for (pp, o), v in prep_cnt[key].items() if pp == p and o})
            objs_s = " / ".join(o for o, v in objs.most_common(3) if v >= max(2, 0.15 * c))
            passed = prep_pass(c, ratio, lift, pos)
            label = ("thường gặp" if ratio >= 0.2 else "ít gặp") if passed else "— (dưới ngưỡng)"
            exs = best([e for (pp, o), es in prep_ex[key].items() if pp == p for e in es], 1)
            rows.append(f"| {'**' if passed else ''}{lem} {p} {objs_s}{'**' if passed else ''} | {c} | {ratio:.0%} | "
                        f"{lift:.1f} | {label} | {bold(exs[0]) if exs else ''} |")
        if rows:
            L.append("| mẫu | n | tỉ lệ | ×nền | nhãn | ví dụ |\n|---|---|---|---|---|---|")
            L.extend(rows)
        else:
            L.append("(không có)")
        ok_preps = {p for p, c in by_prep.items()
                    if prep_pass(c, c / max(1, n), (c / max(1, n)) / max(1e-6, bg_pos_prep[(pos, p)] / base_n), pos)}
        seqs = [(s, c) for s, c in prep_seq[key].most_common(10)
                if c >= 5 and any(w in ok_preps for w in s.split() if w not in ("sb", "sth", "doing", "wh-"))][:3]
        if seqs:
            L.append("\nHai giới từ cùng lúc: " + "; ".join(
                f"{lem} {s} ({c})" + (f" — {bold(best(prep_ex[key][('SEQ', s)], 1)[0])}" if prep_ex[key][('SEQ', s)] else "")
                for s, c in seqs))
        # kết hợp từ
        L.append("\n### Kết hợp từ\n")
        fx = seen   # số câu có từ ≈ tần suất của từ trong toàn corpus
        groups = defaultdict(list)
        for (pat, disp, clem), c in coll_cnt[key].items():
            if c < 3:
                continue
            fxy = c * scale
            fy = bg_lemma[clem] / max(1, bg_tokens) * total_tok
            ld = 14 + math.log2(2 * fxy / (fx + fy)) if fy else 0
            if ld >= 3:
                groups[pat].append((ld, c, disp, (pat, disp, clem)))
        if not groups:
            L.append("(không có cụm đủ 3 lần)")
        for pat, items in sorted(groups.items(), key=lambda kv: -sum(x[1] for x in kv[1])):
            items.sort(key=lambda x: (-x[0], -x[1]))
            shown = items[:12]
            L.append(f"- **{pat}**: " + " · ".join(
                f"{d} ({c}; {ld:.1f})" for ld, c, d, _ in shown))
            if shown:
                exs = best(coll_ex[key][shown[0][3]], 1)
                if exs:
                    L.append(f"  - ví dụ cho *{shown[0][2]}*: {bold(exs[0])}")
        # vị trí
        L.append("\n### Ví dụ theo vị trí\n")
        nbytes = 0
        for role, exs in sorted(role_ex[key].items(), key=lambda kv: -len(kv[1])):
            top3 = best(exs, 3)
            nbytes += sum(len(e[1]) + 40 for e in best(exs, 5))
            L.append(f"- **{role}** ({len(exs):,} câu đạt): ")
            for e in top3:
                L.append(f"  - {bold(e)}")
        sizes.append(nbytes + 60 * len(by_prep) + 30 * sum(len(v[:12]) for v in groups.values()))
    # kiểm mắt độ đúng
    rnd = random.Random(7)
    pools = [rnd.sample(v, len(v)) for v in audit.values()]   # chia đều theo từ, không lệch về từ phân tích trước
    sample = []
    while len(sample) < 50 and any(pools):
        for pl in pools:
            if pl and len(sample) < 50:
                sample.append(pl.pop())
    L.append("\n---\n\n## 50 câu ngẫu nhiên kèm nhãn máy gắn (để kiểm độ đúng)\n")
    L.append("Đánh dấu câu gắn sai để chỉnh luật ở R1.\n")
    for i, (key, rs, ex) in enumerate(sample, 1):
        L.append(f"{i}. [{key[0]} {key[1].lower()} → {', '.join(rs) or '(không nhãn)'}] {bold(ex)}")
    avg = sum(sizes) / max(1, len(sizes))
    L.append(f"\n---\n\n## Ước lượng dung lượng\n\nTrung bình ~{avg / 1024:.1f} KB/từ (5 câu mỗi vị trí, ≤ 12 cụm mỗi mẫu, mẫu giới từ) "
             f"→ ~{avg * 20000 / 1e6:.0f} MB thô cho 20.000 từ, ~{avg * 20000 / 3.5e6:.0f} MB nén gzip (ước 3,5×). "
             "Corpus R1 sẽ lớn hơn (thêm một phần English Wikipedia) nên từ ít gặp sẽ có thêm câu.\n")
    path = OUT / "R0-mau.md"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"[xong] {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["r0", "collect"])
    ap.add_argument("--cap", type=int, default=3000)
    ap.add_argument("--bg", type=int, default=40000, help="số câu nền mỗi nguồn")
    ap.add_argument("--jobs", type=int, default=4)
    a = ap.parse_args()
    if a.mode == "collect":
        collect(a.cap, a.bg)
    else:
        run_r0(a.cap, a.bg, a.jobs)


if __name__ == "__main__":
    main()
