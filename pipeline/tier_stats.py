"""Đếm số nghĩa (sau lọc) của các từ tầng A và mô phỏng cách chia lô, để tính số lệnh AI và thời gian.

Dùng: python pipeline/tier_stats.py  → data/work/tier-a-senses.json (word → số nghĩa theo từng từ loại)
"""
import csv
import gzip
import json
import sys
from pathlib import Path

from enrich_sample import SKIP_TAGS

sys.stdout.reconfigure(encoding="utf-8")
csv.field_size_limit(1 << 30)
ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
WORK = ROOT / "data" / "work"
SKIP_POS = {"name", "character", "symbol", "romanization"}


def main():
    rank = {}
    with open(RAW / "ecdict.csv", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            vals = [int(v) for v in (row["bnc"], row["frq"]) if v and v != "0"]
            if vals:
                rank[row["word"]] = min(vals + [rank.get(row["word"], 10**9)])
    senses = {}
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code": "en"' not in line:
                continue
            d = json.loads(line)
            w = d.get("word")
            if d.get("lang_code") != "en" or w not in rank or d.get("pos") in SKIP_POS:
                continue
            n = sum(1 for s in d.get("senses") or []
                    if s.get("glosses") and not (set(s.get("tags") or []) & SKIP_TAGS))
            if n:
                senses.setdefault(w, 0)
                senses[w] += n
    ordered = sorted(senses, key=rank.get)  # chỉ từ có nghĩa thật (đã bỏ dạng biến đổi thuần)
    out = [[w, senses[w]] for w in ordered]
    (WORK / "tier-a-senses.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} từ có thứ hạng và có nghĩa thật")


if __name__ == "__main__":
    main()
