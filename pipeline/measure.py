"""Vòng 0: đo quy mô và độ phủ của các nguồn để chốt ngưỡng chất lượng (UC-M03, bản thô).

Dùng: python pipeline/measure.py  → in báo cáo và ghi data/work/measure.json
"""
import bz2
import csv
import gzip
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(1 << 30)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
TOP_N = (3000, 5000, 20000, 30000)

UK_TAGS = {"UK", "Received-Pronunciation", "British"}
US_TAGS = {"US", "General-American"}


def freq_ranks():
    """Thứ hạng tần suất từ ECDICT: lấy min(bnc, frq) khác 0. Chỉ đọc 3 cột được phép."""
    ranks = {}
    with open(RAW / "ecdict.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = [int(v) for v in (row["bnc"], row["frq"]) if v and v != "0"]
            if vals:
                w = row["word"]
                ranks[w] = min(vals + [ranks.get(w, 10**9)])
    ordered = sorted(ranks, key=ranks.get)
    return {w: i + 1 for i, w in enumerate(ordered)}


def is_lemma_entry(d):
    senses = d.get("senses") or []
    real = [s for s in senses if "form-of" not in (s.get("tags") or []) and s.get("glosses")]
    return bool(real)


def measure_en(rank):
    stats = Counter()
    pos_counter = Counter()
    per_word = {}  # word -> dict các cờ, chỉ cho từ có thứ hạng
    form_of = 0
    lemma_words, formof_words = set(), set()
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") != "en":
                continue
            stats["entries"] += 1
            w = d["word"]
            if not is_lemma_entry(d):
                form_of += 1
                formof_words.add(w)
                continue
            lemma_words.add(w)
            stats["lemma_entries"] += 1
            pos_counter[d.get("pos")] += 1
            senses = [s for s in d["senses"] if s.get("glosses") and "form-of" not in (s.get("tags") or [])]
            stats["senses"] += len(senses)
            if " " in w:
                stats["multiword_entries"] += 1
            if w not in rank:
                continue
            flags = per_word.setdefault(w, Counter())
            flags["senses"] += len(senses)
            ex = sum(1 for s in senses if s.get("examples"))
            flags["senses_with_example"] += ex
            # ví dụ ngắn kiểu học thuật (không phải trích dẫn văn học dài)
            flags["senses_with_short_example"] += sum(
                1 for s in senses
                if any(len(e.get("text", "")) <= 160 and e.get("type") != "quotation" for e in s.get("examples") or [])
            )
            tags = [set(s.get("tags") or []) for s in d.get("sounds") or [] if s.get("ipa")]
            flags["ipa_uk"] |= any(t & UK_TAGS for t in tags)
            flags["ipa_us"] |= any(t & US_TAGS for t in tags)
            flags["ipa_any"] |= bool(tags)
            flags["audio"] |= any(s.get("audio") for s in d.get("sounds") or [])
            vi = [t for t in d.get("translations") or [] if t.get("code") == "vi"]
            for s in senses:
                vi += [t for t in s.get("translations") or [] if t.get("code") == "vi"]
            flags["vi_translations"] += len(vi)
            flags["vi_translation_senses"] += len({t.get("sense") for t in vi})
            flags["etymology"] |= bool(d.get("etymology_text"))
            flags["synonyms"] |= bool(d.get("synonyms") or any(s.get("synonyms") for s in senses))
            flags["derived"] |= bool(d.get("derived"))
    stats["form_of_entries"] = form_of
    return stats, pos_counter, per_word, formof_words - lemma_words


def coverage(per_word, rank, extra=None):
    out = {}
    for n in TOP_N:
        words = [w for w, r in rank.items() if r <= n]
        have = [w for w in words if w in per_word]
        c = Counter()
        for w in have:
            f = per_word[w]
            c["has_entry"] += 1
            c["ipa_uk"] += bool(f["ipa_uk"])
            c["ipa_us"] += bool(f["ipa_us"])
            c["audio"] += bool(f["audio"])
            c["any_example"] += f["senses_with_example"] > 0
            c["short_example"] += f["senses_with_short_example"] > 0
            c["vi_translation"] += f["vi_translations"] > 0
            c["etymology"] += bool(f["etymology"])
            c["synonyms"] += bool(f["synonyms"])
            if extra:
                for k, s in extra.items():
                    c[k] += w in s
        out[n] = {k: f"{v * 100 / len(words):.1f}%" for k, v in c.items()}
        out[n]["_words"] = len(words)
        out[n]["_avg_senses"] = round(sum(per_word[w]["senses"] for w in have) / max(len(have), 1), 1)
    return out


def measure_viwikt():
    """Wiktionary tiếng Việt: từ tiếng Anh có nghĩa tiếng Việt, và từ tiếng Việt."""
    en_words, vi_words = set(), set()
    en_senses = vi_senses = 0
    sample = None
    with gzip.open(RAW / "viwikt-raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            lc = d.get("lang_code")
            senses = [s for s in d.get("senses") or [] if s.get("glosses")]
            if lc == "en" and senses:
                en_words.add(d["word"])
                en_senses += len(senses)
                if d["word"] == "bank" and sample is None:
                    sample = d
            elif lc == "vi" and senses:
                vi_words.add(d["word"])
                vi_senses += len(senses)
    return en_words, en_senses, vi_words, vi_senses, sample


HAN = re.compile(r"[㐀-鿿\U00020000-\U0002ffff]")


def measure_kaikki_vi():
    words, senses, pos = set(), 0, Counter()
    with open(RAW / "kaikki-vi.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if HAN.search(d["word"]) or d.get("pos") == "character":
                continue
            ss = [s for s in d.get("senses") or [] if s.get("glosses") and "form-of" not in (s.get("tags") or [])]
            if ss:
                words.add(d["word"])
                senses += len(ss)
                pos[d.get("pos")] += 1
    return words, senses, pos


def measure_tatoeba():
    vie = {}
    with bz2.open(RAW / "tatoeba-vie.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            i, _, text = line.rstrip("\n").split("\t", 2)
            vie[i] = text
    pairs = set()
    with bz2.open(RAW / "tatoeba-vie-eng-links.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            a, b = line.split()[:2]
            if a in vie:
                pairs.add((a, b))
    return len(vie), len(pairs)


def measure_cefr():
    out = {}
    for name in ("cefrj-vocabulary-profile-1.5.csv", "octanove-vocabulary-profile-c1c2-1.0.csv"):
        with open(RAW / name, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        out[name] = {"rows": len(rows), "columns": list(rows[0].keys()),
                     "levels": dict(Counter(r.get("CEFR") for r in rows))}
    return out


def cefr_words():
    words = set()
    for name in ("cefrj-vocabulary-profile-1.5.csv", "octanove-vocabulary-profile-c1c2-1.0.csv"):
        with open(RAW / name, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                for w in (r.get("headword") or "").split("/"):
                    words.add(w.strip())
    return words


def measure_oewn():
    with zipfile.ZipFile(RAW / "oewn-2025-json.zip") as z:
        names = z.namelist()
    return {"files": len(names), "sample": names[:5]}


def no_diacritics(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    report = {}
    print("Đọc ECDICT (thứ hạng tần suất)...", flush=True)
    rank = freq_ranks()
    report["ranked_words"] = len(rank)

    print("Đọc Wiktionary tiếng Việt...", flush=True)
    vw_en, vw_en_senses, vw_vi, vw_vi_senses, sample = measure_viwikt()
    report["viwikt"] = {"en_words": len(vw_en), "en_senses": vw_en_senses,
                        "vi_words": len(vw_vi), "vi_senses": vw_vi_senses}
    if sample:
        (WORK / "sample-viwikt-bank.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")

    print("Đọc kaikki tiếng Việt (enwiktionary)...", flush=True)
    kv_words, kv_senses, kv_pos = measure_kaikki_vi()
    report["kaikki_vi"] = {"words": len(kv_words), "senses": kv_senses, "pos_top": kv_pos.most_common(8)}
    vi_union = kv_words | vw_vi
    report["vi_headwords_union"] = len(vi_union)
    report["vi_no_diacritics_keys"] = len({no_diacritics(w).lower() for w in vi_union})

    print("Đọc Tatoeba...", flush=True)
    n_vie, n_pairs = measure_tatoeba()
    report["tatoeba"] = {"vie_sentences": n_vie, "vie_eng_pairs": n_pairs}

    report["cefr"] = measure_cefr()
    report["oewn"] = measure_oewn()

    print("Đọc Wiktionary tiếng Anh (lâu, ~3 GB JSON)...", flush=True)
    stats, pos, per_word, only_forms = measure_en(rank)
    # bỏ các dạng biến đổi thuần (went, children) khỏi bảng xếp hạng rồi đánh số lại
    ordered = sorted((w for w in rank if w not in only_forms), key=rank.get)
    rank = {w: i + 1 for i, w in enumerate(ordered)}
    report["pure_inflected_forms_removed_from_rank"] = len(only_forms)
    report["en"] = dict(stats)
    report["en_pos_top"] = pos.most_common(12)
    report["coverage"] = coverage(per_word, rank, extra={"viwikt_vi_gloss": vw_en, "cefr": cefr_words()})

    (WORK / "measure.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
