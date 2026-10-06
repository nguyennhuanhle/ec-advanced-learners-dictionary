"""In mục từ của bộ từ kiểm tra cố định từ dict-core.sqlite để đọc bằng mắt sau mỗi lần build (UC-M04).

Dùng: python pipeline/show.py [từ ...]   → in ra màn hình và ghi data/build/check.md
Không có assert: người đọc tự đánh giá kết quả thật.
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "build" / "dict-core.sqlite"
OUT = ROOT / "data" / "build" / "check.md"
CHECK = ["run", "set", "bank", "light", "went", "children", "give up", "by the way", "colour", "serendipity", "the"]


def show(con, q):
    lines = [f"## {q}"]
    head = con.execute("SELECT word FROM headword WHERE word = ?", (q,)).fetchone()
    if not head:
        via = con.execute("SELECT headword, relation, tags FROM lookup_index WHERE form_norm = ? LIMIT 1",
                          (q.lower(),)).fetchone()
        if not via:
            return lines + ["(không có trong từ điển)", ""]
        lines.append(f"→ {q} là {via[1]} ({via[2]}) của **{via[0]}**")
        q = via[0]
    for eid, pos, etype, band, cefr, model, tier in con.execute(
            "SELECT id, pos, entry_type, freq_band, cefr, ai_model, tier FROM entry WHERE headword = ? "
            "ORDER BY ai_model IS NULL, ord", (q,)):
        ipa = dict(con.execute("SELECT accent, ipa FROM pronunciation WHERE entry_id = ?", (eid,)).fetchall())
        forms = [f for (f,) in con.execute("SELECT form FROM form WHERE entry_id = ? ORDER BY ord", (eid,))]
        lines.append(f"**{q}** · {pos} ({etype}) · tầng {tier} · {band or '-'} · CEFR {cefr or '-'} · "
                     f"UK {ipa.get('uk', '-')} US {ipa.get('us', '-')} · dạng: {', '.join(forms) or '-'} · "
                     f"{'AI ' + model if model else 'chỉ Wiktionary'}")
        layer = "learner" if model else "full"
        for i, (sid, gw, gram, labels, d, sc, vi) in enumerate(con.execute(
                "SELECT id, guideword, grammar, labels, definition, cefr, vi FROM sense "
                "WHERE entry_id = ? AND layer = ? ORDER BY ord LIMIT 8", (eid, layer)), 1):
            meta = " ".join(x for x in (gw and f"[{gw}]", sc, gram, labels and f"({labels})") if x)
            lines.append(f"  {i}. {meta} {d}" + (f"  → {vi}" if vi else ""))
            for (en,) in con.execute("SELECT text_en FROM example WHERE sense_id = ? ORDER BY ord LIMIT 1", (sid,)):
                lines.append(f"     · {en}")
    pv = [p for (p,) in con.execute("SELECT phrase FROM phrase_link WHERE headword = ? AND kind = 'phrasal_verb' "
                                    "ORDER BY popularity DESC LIMIT 8", (q,))]
    if pv:
        lines.append("  cụm động từ: " + ", ".join(pv))
    return lines + [""]


def main():
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    words = sys.argv[1:] or CHECK
    text = "\n".join(line for w in words for line in show(con, w))
    print(text)
    OUT.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
