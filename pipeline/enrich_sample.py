"""Vòng 0: thử làm giàu bằng Gemini trên mẫu ~200 từ (UC-M05, bản thử).

Bước 1: chọn mẫu (cố định + phân tầng theo tần suất), gom dữ liệu Wiktionary EN + nghĩa tiếng Việt viwiktionary.
Bước 2: gọi Gemini theo lô, cache từng lô vào data/work/ai-sample/, chạy lại thì bỏ qua lô đã có.
Bước 3: in thống kê token/request để ước lượng cho toàn bộ tầng A, và ghi bản xem thử cho người duyệt.

Dùng: python pipeline/enrich_sample.py [--limit-batches N] [--engine api|agy] [--only-fixed]
  --engine api : Gemini Flash qua API key (mặc định)
  --engine agy : Gemini 3.1 Pro qua Antigravity CLI (gói Ultra), để so chất lượng
  --only-fixed : chỉ chạy 40 từ khó cố định
  --model M    : model agy (mặc định theo config skill gemini-rewrite)
  --workers N  : số lệnh agy chạy song song (mặc định 1)
"""
import csv
import gzip
import hashlib
import json
import random
import sys
from pathlib import Path

from gemini import Gemini, QuotaExhausted

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(1 << 30)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
CACHE = WORK / "ai-sample"
DELIV = ROOT / "_deliverables"

FIXED = [
    "run", "set", "get", "take", "make", "bank", "light", "fair", "bear", "mean", "fine", "present", "book",
    "go", "have", "play", "point", "issue", "address", "spring", "match", "subject", "charge", "close",
    "give up", "look forward to", "by the way", "in spite of", "take off", "break down", "carry out",
    "serendipity", "ubiquitous", "mitigate", "nuance", "resilient", "exacerbate", "pragmatic", "scrutiny", "benevolent",
]
BANDS = [(1, 1000, 45), (1001, 3000, 45), (3001, 8000, 40), (8001, 20000, 30)]
SKIP_TAGS = {"obsolete", "archaic", "dialectal", "form-of", "alt-of", "misspelling"}
MAX_SENSES_PER_BATCH = 70
MAX_WORDS_PER_BATCH = 6


def ranks():
    r = {}
    with open(RAW / "ecdict.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = [int(v) for v in (row["bnc"], row["frq"]) if v and v != "0"]
            if vals and row["word"].isalpha() and row["word"].islower():
                r[row["word"]] = min(vals + [r.get(row["word"], 10**9)])
    return r


def collect(words):
    """Gom mục từ EN (lemma) và nghĩa tiếng Việt viwiktionary cho tập từ."""
    en = {w: [] for w in words}
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code": "en"' not in line:
                continue
            d = json.loads(line)  # "word" có thể xuất hiện lồng trong forms/descendants, nên phải parse
            if d.get("lang_code") != "en" or d["word"] not in en:
                continue
            senses = []
            for s in d.get("senses") or []:
                tags = set(s.get("tags") or [])
                if not s.get("glosses") or tags & SKIP_TAGS:
                    continue
                ex = next((e.get("text") for e in s.get("examples") or []
                           if e.get("text") and e.get("type") != "quotation" and len(e["text"]) <= 160), None)
                senses.append({"gloss": "; ".join(s["glosses"][-1:]), "tags": sorted(tags), "ex": ex})
            if senses:
                en[d["word"]].append({"pos": d.get("pos"), "senses": senses})
    vi = {w: [] for w in words}
    with gzip.open(RAW / "viwikt-raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") == "en" and d.get("word") in vi:
                vi[d["word"]].append({"pos": d.get("pos"),
                                      "glosses": [g for s in d.get("senses") or [] for g in s.get("glosses") or []]})
    return en, vi


def pick_sample():
    r = ranks()
    ordered = sorted(r, key=r.get)
    rng = random.Random(20261006)
    sample = list(FIXED)
    for lo, hi, n in BANDS:
        pool = [w for w in ordered[lo - 1:hi] if w not in sample]
        sample += rng.sample(pool, n)
    return sample, {w: i + 1 for i, w in enumerate(ordered)}


PROMPT = """You are a lexicographer building an ORIGINAL learner's dictionary for Vietnamese learners of English,
in the style of a modern advanced learner's dictionary. Source material: Wiktionary senses (CC BY-SA) and
Vietnamese glosses from Vietnamese Wiktionary, given below. For each headword and part of speech:

0. Use exactly these part-of-speech values in "pos": the ones shown in brackets after each headword
   (noun, verb, adj, adv, prep, ...). Sense numbers [n] are unique across the whole word.
1. Select the senses a learner (CEFR A1-C2) needs. Drop archaic, dialectal, highly technical or rare senses unless
   no other sense exists. If NO sense of a part of speech is useful to learners, return that entry with an
   empty "senses" list (do not invent examples for rare senses). Merge near-duplicate senses (list every merged source index in "src"). Max 15 senses.
2. Order senses by how common they are in modern English (most common first).
3. "guideword": if the entry has 2+ senses, a 1-3 word UPPERCASE signpost that tells senses apart (e.g. MONEY,
   RIVER SIDE). Empty string if only one sense.
4. "grammar": learner grammar codes, e.g. "[C]", "[U]", "[C, U]", "[T]", "[I]", "[I, T]", "[T] ~ sb to do sth",
   "[usually passive]". Empty string if none apply.
5. "labels": register/region labels such as "formal", "informal", "British", "US", "old-fashioned", "slang",
   "specialist". Empty string if none.
6. "definition": a NEW definition in simple English (mostly A2-B1 vocabulary, max 25 words). Write your own
   wording. Do NOT reproduce wording from Oxford, Cambridge, Longman, Collins or Merriam-Webster dictionaries.
7. "vi": natural Vietnamese equivalent(s) for THIS sense, 1-4 options separated by "; ". Use the Vietnamese
   Wiktionary glosses as hints when they match the sense; otherwise translate yourself.
8. "cefr": estimated CEFR level of THIS sense for a learner (A1, A2, B1, B2, C1, C2).
9. "examples": 1-2 short, natural, ORIGINAL example sentences (max 15 words) showing typical usage of this sense,
   each with a natural Vietnamese translation.
10. "vi_ok": true if you used a Vietnamese Wiktionary gloss, false if you translated yourself.

Return JSON only.

INPUT:
{payload}
"""

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "entries": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "word": {"type": "STRING"},
                    "pos": {"type": "STRING"},
                    "senses": {
                        "type": "ARRAY",
                        "items": {
                            "type": "OBJECT",
                            "properties": {
                                "src": {"type": "ARRAY", "items": {"type": "INTEGER"}},
                                "guideword": {"type": "STRING"},
                                "grammar": {"type": "STRING"},
                                "labels": {"type": "STRING"},
                                "definition": {"type": "STRING"},
                                "vi": {"type": "STRING"},
                                "cefr": {"type": "STRING", "enum": ["A1", "A2", "B1", "B2", "C1", "C2"]},
                                "examples": {
                                    "type": "ARRAY",
                                    "items": {"type": "OBJECT",
                                              "properties": {"en": {"type": "STRING"}, "vi": {"type": "STRING"}},
                                              "required": ["en", "vi"]},
                                },
                                "vi_ok": {"type": "BOOLEAN"},
                            },
                            "required": ["src", "guideword", "grammar", "labels", "definition", "vi", "cefr",
                                         "examples", "vi_ok"],
                        },
                    },
                },
                "required": ["word", "pos", "senses"],
            },
        }
    },
    "required": ["entries"],
}


def payload_for(word, en_entries, vi_entries):
    lines = []
    i = 0
    for e in en_entries:
        lines.append(f"## {word} ({e['pos']})")
        for s in e["senses"]:
            i += 1
            tag = f" ({', '.join(s['tags'])})" if s["tags"] else ""
            ex = f"  || ex: {s['ex']}" if s["ex"] else ""
            lines.append(f"[{i}]{tag} {s['gloss']}{ex}")
        vis = [v for v in vi_entries if v["pos"] == e["pos"]] or vi_entries
        glosses = [g for v in vis for g in v["glosses"]][:20]
        if glosses:
            lines.append("Vietnamese Wiktionary glosses: " + " | ".join(glosses))
    return "\n".join(lines)


def batches(sample, en):
    cur, n = [], 0
    for w in sample:
        k = sum(len(e["senses"]) for e in en[w])
        if not k:
            continue
        if cur and (n + k > MAX_SENSES_PER_BATCH or len(cur) >= MAX_WORDS_PER_BATCH):
            yield cur
            cur, n = [], 0
        cur.append(w)
        n += k
    if cur:
        yield cur


POS_ALIASES = {"adjective": "adj", "adverb": "adv", "preposition": "prep", "conjunction": "conj",
               "pronoun": "pron", "interjection": "intj", "determiner": "det", "numeral": "num",
               "phrasal verb": "verb", "prepositional phrase": "prep_phrase"}
PROMPT_VERSION = "v3"  # đổi khi đổi PROMPT hoặc cách đánh số, để không dùng nhầm cache cũ


def norm_pos(pos):
    pos = (pos or "").strip().lower()
    return POS_ALIASES.get(pos, pos)


SENSE_DEFAULTS = {"guideword": "", "grammar": "", "labels": "", "vi": "", "cefr": None, "examples": [], "vi_ok": False}


def validate(result, words, en):
    """Loại bản ghi sai: thiếu trường, từ lạ, src trỏ tới nghĩa không tồn tại.
    agy không ép JSON schema như API, nên mọi trường đều có thể thiếu hoặc sai kiểu → không bao giờ để ném lỗi."""
    ok, rejects = [], []
    entries = result.get("entries") if isinstance(result, dict) else None
    if not isinstance(entries, list):
        return [], [{"reason": "kết quả không có danh sách entries", "entry": str(result)[:300]}]
    for e in entries:
        if not isinstance(e, dict) or not isinstance(e.get("word"), str) or not isinstance(e.get("senses"), list) \
                or not e.get("pos"):
            rejects.append({"reason": "mục thiếu word/pos/senses", "entry": e})
            continue
        e["pos"] = norm_pos(e["pos"])
        src_entries = [x for x in en.get(e["word"], []) if x["pos"] == e["pos"]]
        if e["word"] not in words or not src_entries:
            rejects.append({"reason": "word/pos không có trong input", "entry": e})
            continue
        n = sum(len(x["senses"]) for x in en[e["word"]])  # đánh số liên tục theo từ
        good, bad = [], []
        for s in e["senses"]:
            src = s.get("src") if isinstance(s, dict) else None
            if not isinstance(s, dict) or not isinstance(s.get("definition"), str) or not s["definition"].strip() \
                    or not isinstance(src, list) or not src \
                    or not all(isinstance(i, int) and 1 <= i <= n for i in src):
                bad.append(s)
                continue
            for k, v in SENSE_DEFAULTS.items():  # trường phụ thiếu / sai kiểu → giá trị trống, luôn có mặt
                cur = s.get(k)
                if k == "cefr":
                    s[k] = cur if isinstance(cur, str) and cur else None
                elif not isinstance(cur, type(v)):
                    s[k] = [] if isinstance(v, list) else v
            s["examples"] = [x for x in s["examples"] if isinstance(x, dict) and isinstance(x.get("en"), str)]
            for x in s["examples"]:
                x.setdefault("vi", "")
            good.append(s)
        if bad:
            rejects.append({"reason": "nghĩa thiếu trường hoặc src ngoài phạm vi", "entry": e["word"], "senses": bad})
        e["senses"] = good
        ok.append(e)
    return ok, rejects


def main():
    limit = int(sys.argv[sys.argv.index("--limit-batches") + 1]) if "--limit-batches" in sys.argv else None
    engine = sys.argv[sys.argv.index("--engine") + 1] if "--engine" in sys.argv else "api"
    model = sys.argv[sys.argv.index("--model") + 1] if "--model" in sys.argv else None
    workers = int(sys.argv[sys.argv.index("--workers") + 1]) if "--workers" in sys.argv else 1
    tag = engine if not model else f"{engine}-{model}"
    cache = CACHE if engine == "api" else WORK / f"ai-sample-{tag}"
    cache.mkdir(parents=True, exist_ok=True)
    sample, rank = pick_sample()
    if "--only-fixed" in sys.argv:
        sample = list(FIXED)
    print(f"Mẫu: {len(sample)} từ. Gom dữ liệu nguồn...", flush=True)
    src_file = WORK / "ai-sample-source.json"
    if src_file.exists():
        en, vi = json.loads(src_file.read_text(encoding="utf-8"))
    else:
        en, vi = collect(set(sample))
        src_file.write_text(json.dumps([en, vi], ensure_ascii=False), encoding="utf-8")
    missing = [w for w in sample if not en.get(w)]
    print(f"Không có mục Wiktionary dùng được: {missing}")

    if engine == "agy":
        from agy_client import Agy
        g = Agy(model=model)
    else:
        g = Gemini()
    all_ok, all_rej, done, failed = [], [], 0, []
    if workers > 1:
        from concurrent.futures import ThreadPoolExecutor

        def one(words):
            key = hashlib.sha1((PROMPT_VERSION + "|" + "|".join(words)).encode()).hexdigest()[:12]
            out = cache / f"{key}.json"
            if out.exists():
                return
            payload = "\n\n".join(payload_for(w, en[w], vi.get(w, [])) for w in words)
            try:
                result, meta = g.generate_json(PROMPT.format(payload=payload), SCHEMA)
            except RuntimeError as e:
                print(f"  [bỏ qua lô] {', '.join(words)}: {e}", flush=True)
                return
            out.write_text(json.dumps({"words": words, "meta": meta, "result": result}, ensure_ascii=False),
                           encoding="utf-8")
            print(f"  lô: {', '.join(words)} → {meta['model']} {meta['seconds']}s", flush=True)

        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, list(batches(sample, en))))
    for words in batches(sample, en):
        key = hashlib.sha1((PROMPT_VERSION + "|" + "|".join(words)).encode()).hexdigest()[:12]
        out = cache / f"{key}.json"
        if not out.exists():
            if limit is not None and done >= limit:
                break
            payload = "\n\n".join(payload_for(w, en[w], vi.get(w, [])) for w in words)
            try:
                result, meta = g.generate_json(PROMPT.format(payload=payload), SCHEMA)
            except QuotaExhausted as e:
                print(f"Hết quota free ở mọi model của khoá đang dùng: {e}")
                break
            except RuntimeError as e:
                print(f"  [bỏ qua lô] {', '.join(words)}: {e}", flush=True)
                failed.append(words)
                continue
            out.write_text(json.dumps({"words": words, "meta": meta, "result": result}, ensure_ascii=False),
                           encoding="utf-8")
            done += 1
            print(f"  lô {done}: {', '.join(words)} → {meta['model']} {meta['seconds']}s", flush=True)
        data = json.loads(out.read_text(encoding="utf-8"))
        ok, rej = validate(data["result"], set(words), en)
        all_ok += ok
        all_rej += rej

    suffix = "" if engine == "api" else f"-{tag}"
    (WORK / f"ai-sample-entries{suffix}.json").write_text(json.dumps(all_ok, ensure_ascii=False, indent=1), encoding="utf-8")
    (WORK / f"ai_rejects{suffix}.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in all_rej),
                                           encoding="utf-8")
    covered = {e["word"] for e in all_ok}
    print(json.dumps({
        "sample_words": len(sample), "words_enriched": len(covered), "entries": len(all_ok),
        "senses": sum(len(e["senses"]) for e in all_ok), "rejects": len(all_rej),
        "failed_batches": failed, "usage_this_run": getattr(g, "usage", {"agy_calls": getattr(g, "calls", 0)}), "models": getattr(g, "model_hits", None),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
