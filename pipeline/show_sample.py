"""In bản xem thử mục từ AI để người duyệt đọc bằng mắt (UC-M04, bản vòng 0).

Dùng: python pipeline/show_sample.py [từ ...]  → ghi _deliverables/vong0-mau-AI.md
Đọc thẳng các lô đã cache (Flash: data/work/ai-sample, Pro: data/work/ai-sample-agy), kiểm lại bằng validate(),
rồi đặt bản Flash và bản Pro của cùng một từ cạnh nhau.
"""
import json
import sys
from pathlib import Path

from enrich_sample import validate

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "work"
OUT = ROOT / "_deliverables" / "vong0-mau-AI.md"
ENGINES = {"Flash (API)": WORK / "ai-sample", "Pro 3.1 (agy)": WORK / "ai-sample-agy"}


def load(cache, en):
    entries = {}
    for f in sorted(cache.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        ok, _ = validate(data["result"], set(data["words"]), en)
        for e in ok:
            entries.setdefault(e["word"], []).append(e)
    return entries


def render(e, n_src):
    lines = [f"**{e['word']}** · *{e['pos']}* — {len(e['senses'])} nghĩa (Wiktionary: {n_src})", ""]
    for i, s in enumerate(e["senses"], 1):
        gw = f"**{s['guideword']}** " if s["guideword"] else ""
        meta = " ".join(x for x in (s["grammar"], f"*{s['labels']}*" if s["labels"] else "") if x)
        lines.append(f"{i}. {gw}`{s['cefr']}` {meta} {s['definition']}  ")
        lines.append(f"   → **{s['vi']}**{'' if s['vi_ok'] else ' _(AI tự dịch)_'}  ")
        for ex in s["examples"]:
            lines.append(f"   - *{ex['en']}* — {ex['vi']}  ")
    return lines


def main():
    en, _vi = json.loads((WORK / "ai-sample-source.json").read_text(encoding="utf-8"))
    by_engine = {name: load(path, en) for name, path in ENGINES.items() if path.exists()}
    words = sys.argv[1:] or list(dict.fromkeys(w for d in by_engine.values() for w in d))
    lines = ["# Vòng 0 — mẫu mục từ do Gemini biên soạn lại từ Wiktionary", "",
             "Mọi định nghĩa, nghĩa tiếng Việt, CEFR và ví dụ dưới đây là nội dung **AI** (sẽ gắn nhãn trong app).",
             "\"AI tự dịch\" = nghĩa tiếng Việt không lấy từ Wiktionary tiếng Việt.", ""]
    for w in words:
        lines.append(f"## {w}")
        lines.append("")
        for name, d in by_engine.items():
            if w not in d:
                continue
            lines.append(f"### {name}")
            lines.append("")
            for e in d[w]:
                n_src = sum(len(x["senses"]) for x in en[w] if x["pos"] == e["pos"])
                lines += render(e, n_src) + [""]
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    counts = {name: len(d) for name, d in by_engine.items()}
    print(f"Đã ghi {OUT}: {len(words)} từ, theo engine: {counts}")


if __name__ == "__main__":
    main()
