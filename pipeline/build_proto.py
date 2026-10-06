"""Gom dữ liệu cho prototype GUI: các từ đã có bản AI + dữ liệu gốc Wiktionary/CEFR/Tatoeba của chúng.

Dùng: python pipeline/build_proto.py  → data/build/proto-data.json
(trước đây ghi vào app/static/ và bị đóng vào bộ cài; đã chuyển ra ngoài app, 2026-10-06)
Đây là bản thử để xem giao diện. Bản thật đọc SQLite qua Rust (vòng 1).
Thứ tự ưu tiên bản AI: Flash 3.8 medium > Flash 3.8 (thử) > Flash API > Pro.
"""
import bz2
import csv
import glob
import gzip
import json
import re
import sys
import unicodedata
from pathlib import Path

from enrich_sample import SKIP_TAGS, norm_pos

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(1 << 30)
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
OUT = ROOT / "data" / "build" / "proto-data.json"

AI_SOURCES = [  # (nhãn model, mẫu đường dẫn) theo thứ tự ưu tiên
    ("Gemini 3.8 Flash", str(WORK / "ai-sample-agy-gemini-3.8-flash-medium" / "*.json")),
    ("Gemini 3.8 Flash", str(WORK / "agy38-*.json")),
    ("Gemini Flash", str(WORK / "ai-sample" / "*.json")),
    ("Gemini 3.1 Pro", str(WORK / "ai-sample-agy" / "*.json")),
]
UK = {"UK", "Received-Pronunciation", "British"}
US = {"US", "General-American"}
PARTICLES = {"up", "down", "off", "out", "in", "on", "away", "back", "over", "through", "about", "around",
             "along", "by", "for", "with", "into", "across", "after", "apart", "ahead", "forward", "to", "at",
             "behind", "together", "round", "under", "upon", "from", "against", "onto", "aside"}
SKIP_POS = {"name", "character", "symbol", "romanization"}
LEVELS = ["A1", "A2", "B1", "B2", "C1", "C2"]


def no_diacritics(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


def load_ai():
    ai = {}  # word -> {pos: {"model":..., "senses": [...]}}
    for model, pattern in AI_SOURCES:
        for f in sorted(glob.glob(pattern)):
            data = json.loads(Path(f).read_text(encoding="utf-8"))
            for e in data["result"].get("entries", []):
                pos = norm_pos(e["pos"])
                if not e.get("senses"):
                    continue
                slot = ai.setdefault(e["word"], {})
                if pos not in slot:
                    slot[pos] = {"model": model, "senses": e["senses"]}
    return ai


def ranks():
    r, phon = {}, {}
    with open(RAW / "ecdict.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            w = row["word"]
            if row["phonetic"]:
                phon.setdefault(w, row["phonetic"])
            vals = [int(v) for v in (row["bnc"], row["frq"]) if v and v != "0"]
            if vals:
                r[w] = min(vals + [r.get(w, 10**9)])
    return r, phon


def cefr_table():
    t = {}
    for name in ("cefrj-vocabulary-profile-1.5.csv", "octanove-vocabulary-profile-c1c2-1.0.csv"):
        with open(RAW / name, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                pos = {"adjective": "adj", "adverb": "adv", "preposition": "prep", "conjunction": "conj",
                       "pronoun": "pron", "determiner": "det", "interjection": "intj"}.get(row["pos"], row["pos"])
                for w in row["headword"].split("/"):
                    key = (w.strip().lower(), pos)
                    old = t.get(key)
                    if not old or LEVELS.index(row["CEFR"]) < LEVELS.index(old):
                        t[key] = row["CEFR"]
    return t


def clean_etym(text):
    if not text:
        return ""
    lines = [l for l in text.split("\n") if l.strip()]
    if lines and lines[0].startswith("Etymology tree"):  # bỏ phần cây từ nguyên dạng liệt kê
        lines = [l for l in lines if " " in l.strip() and not re.fullmatch(r"[\w\-*ʰ₃ ]+(bor\.|der\.)?", l.strip())]
        lines = [l for l in lines if len(l) > 40] or lines
    return " ".join(lines[:2])


def scan_en(words):
    entries = {w: [] for w in words}
    phrases = {w: [] for w in words}
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code": "en"' not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != "en" or d.get("pos") in SKIP_POS:
                continue
            w = d["word"]
            senses = [s for s in d.get("senses") or []
                      if s.get("glosses") and not (set(s.get("tags") or []) & SKIP_TAGS)]
            if not senses:
                continue
            if w in entries:
                entries[w].append(d)
            toks = w.split()
            if len(toks) > 1:
                for t in set(toks):
                    if t in phrases and t != w:
                        is_pv = d.get("pos") == "verb" and len(toks) <= 3 and all(x in PARTICLES for x in toks[1:]) \
                            and toks[0] == t
                        phrases[t].append({
                            "phrase": w, "pos": d.get("pos"), "kind": "phrasal_verb" if is_pv else "idiom",
                            "gloss": senses[0]["glosses"][-1],
                            "popularity": len(d.get("translations") or []) + 3 * len(senses),
                        })
    return entries, phrases


def ipa_of(dlist, phon):
    uk = us = other = None
    for d in dlist:
        for s in d.get("sounds") or []:
            ipa = s.get("ipa")
            if not ipa or not ipa.startswith("/"):
                continue
            tags = set(s.get("tags") or [])
            if tags & UK and not uk:
                uk = ipa
            if tags & US and not us:
                us = ipa
            if not tags and not other:
                other = ipa
    w = dlist[0]["word"] if dlist else ""
    fallback = other or (f"/{phon[w]}/" if w in phon else None)
    return uk or fallback, us or fallback


def forms_of(d):
    out = []
    for fm in d.get("forms") or []:
        tags = set(fm.get("tags") or [])
        if fm.get("source") or tags & {"table-tags", "inflection-template", "alternative", "obsolete", "archaic",
                                       "dialectal", "nonstandard", "colloquial"}:
            continue
        if fm["form"] not in [x["form"] for x in out]:
            out.append({"form": fm["form"], "tags": sorted(tags)})
    return out[:6]


def tatoeba(words):
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
    pats = {w: re.compile(rf"\b{re.escape(w)}\b", re.I) for w in words}
    out = {w: [] for w in words}
    with bz2.open(RAW / "tatoeba-eng.tsv.bz2", "rt", encoding="utf-8") as f:
        for line in f:
            i, _, text = line.rstrip("\n").split("\t", 2)
            if i not in links or len(text) > 90:
                continue
            for w, p in pats.items():
                if len(out[w]) < 12 and p.search(text):
                    out[w].append({"en": text, "vi": vie[links[i]]})
    return {w: sorted(v, key=lambda x: len(x["en"]))[:4] for w, v in out.items()}


def viwikt(words):
    out = {w: {} for w in words}
    vi_words = {}
    with gzip.open(RAW / "viwikt-raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") == "en" and d.get("word") in out:
                gl = [g for s in d.get("senses") or [] for g in s.get("glosses") or []]
                out[d["word"]].setdefault(norm_pos(d.get("pos")), []).extend(gl)
    return out


def kaikki_vi(keys):
    """Mục Việt-Anh (enwiktionary) cho các từ tiếng Việt xuất hiện trong nghĩa AI."""
    out = {}
    with open(RAW / "kaikki-vi.jsonl", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            w = d["word"]
            if w.lower() not in keys or d.get("pos") in SKIP_POS:
                continue
            gl = [s["glosses"][-1] for s in d.get("senses") or []
                  if s.get("glosses") and "form-of" not in (s.get("tags") or [])]
            if gl:
                out.setdefault(w.lower(), []).append({"pos": norm_pos(d.get("pos")), "glosses": gl[:6]})
    return out


OEWN_POS = {"noun": ["n"], "verb": ["v"], "adj": ["a", "s"], "adv": ["r"]}


def oewn(words):
    """Nhóm đồng nghĩa theo synset (giống khối Thesaurus), trái nghĩa và nhóm cha (hypernym)."""
    import zipfile
    z = zipfile.ZipFile(RAW / "oewn-2025-json.zip")
    synsets, entries = {}, {}
    for n in z.namelist():
        data = json.loads(z.read(n))
        if n.startswith("entries-"):
            entries.update({k: v for k, v in data.items() if k in words})
        elif n.split(".")[0] in ("noun", "verb", "adj", "adv"):
            synsets.update(data)
    out = {}
    for w, by in entries.items():
        for pos, keys in OEWN_POS.items():
            groups, ants = [], []
            for k in keys:
                for sense in (by.get(k) or {}).get("sense", []):
                    ss = synsets.get(sense["synset"], {})
                    members = [m for m in ss.get("members", []) if m != w]
                    hyper = [synsets.get(h, {}).get("members", [None])[0] for h in ss.get("hypernym", [])]
                    ants += [a.split("%")[0].replace("_", " ") for a in sense.get("antonym", [])]
                    if members or hyper:
                        groups.append({"definition": (ss.get("definition") or [""])[0], "members": members[:8],
                                       "hypernym": [h for h in hyper if h][:2]})
            if groups or ants:
                out[(w, pos)] = {"groups": groups[:6], "antonyms": list(dict.fromkeys(ants))[:10]}
    return out


def main():
    ai = load_ai()
    words = sorted(ai)
    print(f"{len(words)} từ có bản AI. Đọc nguồn...", flush=True)
    rank, phon = ranks()
    cefr = cefr_table()
    en, phrases = scan_en(set(words))
    tato = tatoeba(words)
    vw = viwikt(set(words))
    thes = oewn(set(words))

    entries = {}
    vi_index = {}
    for w in words:
        dl = en.get(w, [])
        uk, us = ipa_of(dl, phon)
        r = rank.get(w)
        band = "Top 3000" if r and r <= 3000 else "Top 5000" if r and r <= 5000 else None
        by_pos = {}
        for d in dl:
            pos = norm_pos(d.get("pos"))
            p = by_pos.setdefault(pos, {"forms": [], "wikt": [], "etym": "", "syn": set(), "ant": set(),
                                        "derived": set()})
            p["forms"] = p["forms"] or forms_of(d)
            p["etym"] = p["etym"] or clean_etym(d.get("etymology_text"))
            for s in d.get("senses") or []:
                tags = set(s.get("tags") or [])
                if not s.get("glosses") or tags & SKIP_TAGS:
                    continue
                ex = next((e.get("text") for e in s.get("examples") or []
                           if e.get("text") and e.get("type") != "quotation" and len(e["text"]) <= 160), None)
                p["wikt"].append({"gloss": s["glosses"][-1], "tags": sorted(tags), "ex": ex})
                p["syn"] |= {x["word"] for x in s.get("synonyms") or []}
                p["ant"] |= {x["word"] for x in s.get("antonyms") or []}
            p["syn"] |= {x["word"] for x in d.get("synonyms") or []}
            p["ant"] |= {x["word"] for x in d.get("antonyms") or []}
            p["derived"] |= {x["word"] for x in d.get("derived") or [] if " " not in x.get("word", "")}
        blocks = []
        for pos, a in ai[w].items():
            p = by_pos.get(pos)
            if not p or not p["wikt"]:
                continue
            th = thes.get((w, pos), {"groups": [], "antonyms": []})
            blocks.append({
                "pos": pos, "model": a["model"],
                "cefr": cefr.get((w.lower(), pos)),
                "forms": p["forms"],
                "senses": a["senses"],
                "wiktionary": p["wikt"],
                "vi_block": vw.get(w, {}).get(pos, [])[:12],
                "thesaurus": th["groups"],
                "synonyms": list(dict.fromkeys(m for g in th["groups"] for m in g["members"]))[:12],
                "antonyms": th["antonyms"] or sorted(p["ant"])[:10],
                "etymology": p["etym"],
            })
            for i, s in enumerate(a["senses"]):
                for v in re.split(r"[;,]", s["vi"]):
                    v = re.sub(r"\(.*?\)", "", v).strip().lower()
                    if v:
                        vi_index.setdefault(v, []).append(
                            {"word": w, "pos": pos, "sense": i, "guideword": s["guideword"],
                             "definition": s["definition"]})
        family = sorted((x for x in {x for p in by_pos.values() for x in p["derived"]} - {w}
                         if x in rank and x.isalpha() and x.islower()), key=rank.get)
        seen = set()
        ph = []
        for x in sorted(phrases.get(w, []), key=lambda x: -x["popularity"]):
            if x["phrase"] in seen or (x["kind"] == "idiom" and x["pos"] in ("noun", "name")):
                continue
            seen.add(x["phrase"])
            ph.append(x)
        entries[w] = {
            "word": w, "rank": r, "band": band, "ipa": {"uk": uk, "us": us},
            "blocks": blocks,
            "phrasal_verbs": [x for x in ph if x["kind"] == "phrasal_verb"][:15],
            "idioms": [x for x in ph if x["kind"] == "idiom"][:15],
            "family": family[:24],
            "tatoeba": tato.get(w, []),
        }

    vi_extra = kaikki_vi(set(vi_index))
    vi_entries = {}
    for v, hits in vi_index.items():
        vi_entries[v] = {"word": v, "norm": no_diacritics(v), "en": hits, "wikt": vi_extra.get(v, [])}

    lemma_of = {}  # dạng biến đổi → từ gốc
    for w, e in entries.items():
        for b in e["blocks"]:
            for fm in b["forms"]:
                if fm["form"] != w and " " not in fm["form"]:
                    lemma_of.setdefault(fm["form"], {"lemma": w, "tags": fm["tags"], "pos": b["pos"]})
    nearby = sorted(w for w, r in rank.items() if r <= 20000 and w.isalpha() and w.islower())

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "built": "vòng 0 prototype", "entries": entries, "vi": vi_entries,
        "lemma_of": lemma_of, "nearby": nearby,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"Đã ghi {OUT}: {len(entries)} mục Anh, {len(vi_entries)} mục Việt, "
          f"{len(lemma_of)} dạng biến đổi, {OUT.stat().st_size >> 10} KB")


if __name__ == "__main__":
    main()
