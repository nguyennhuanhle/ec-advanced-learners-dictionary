"""Lớp "cách dùng" cho build_db.py (UC-U40, U43, U46; PLAN-colloc R2): giới từ đi kèm, kết hợp từ, câu ví dụ theo vị trí.

Nguồn: data/work/corpus/corpus.sqlite do `pipeline/corpus_build.py merge` dựng (câu thật từ Tatoeba / Wikipedia, không phải AI).
Nhãn vị trí và mẫu kết hợp đổi từ chữ tiếng Việt của bước corpus sang mã ngắn; giao diện tự dịch EN/VI.

Dùng riêng (thử nhanh, không dựng lại cả DB): python pipeline/usage_layer.py  → thay các bảng usage_* trong
data/build/dict-core.sqlite. Bản phát hành phải dựng bằng build_db.py (gọi write()).
"""
import sqlite3
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "work" / "corpus" / "corpus.sqlite"
DB = ROOT / "data" / "build" / "dict-core.sqlite"

POS = {"NOUN": "noun", "VERB": "verb", "ADJ": "adj", "ADV": "adv"}
ROLE = {
    "làm chủ ngữ": "subject", "làm tân ngữ": "object", "sau giới từ": "after_prep", "bổ nghĩa cho danh từ": "noun_mod",
    "sau be (bổ ngữ)": "complement", "số nhiều": "plural",
    "V (nguyên mẫu)": "base", "V (hiện tại)": "present", "V-s": "s_form", "V-ed (quá khứ)": "past", "V-ing": "ing",
    "V3 (phân từ II)": "pp", "bị động": "passive", "sau to (to V)": "to_inf", "V-ing làm chủ ngữ": "ing_subject",
    "V-ing sau giới từ": "ing_after_prep",
    "trước danh từ": "attributive", "sau danh từ": "postnominal", "sau động từ nối": "predicative",
    "so sánh hơn": "comparative", "so sánh nhất": "superlative",
    "đầu câu": "initial", "giữa câu (trước động từ)": "mid_before", "giữa câu (sau động từ)": "mid_after",
    "cuối câu": "final", "trước tính từ/trạng từ": "before_adj",
}
# (từ loại, mẫu ở bước corpus) → mã mẫu; giao diện hiện kiểu từ điển kết hợp từ: "VERB + decision", "decision + VERB"…
PATTERN = {
    ("NOUN", "V + N"): "verb_w", ("NOUN", "ADJ + N"): "adj_w", ("NOUN", "N + N"): "noun_noun",
    ("NOUN", "N + V"): "w_verb", ("NOUN", "lượng từ + of + N"): "quant_of_w",
    ("VERB", "V + N"): "w_noun", ("VERB", "V + ADV (trước/sau)"): "adv_w",
    ("ADJ", "ADV + ADJ"): "adv_w", ("ADJ", "V + ADJ"): "verb_w", ("ADJ", "ADJ + N"): "w_noun",
    ("ADV", "V + ADV"): "verb_w", ("ADV", "ADV + ADJ"): "w_adj",
}
COLL_PER_PATTERN = 12   # UC-U43: tối đa 12 cụm mỗi mẫu

SCHEMA = """
CREATE TABLE usage_prep(headword TEXT, pos TEXT, prep TEXT, obj TEXT, n INTEGER, ratio REAL, common INTEGER);
CREATE TABLE usage_prep_seq(headword TEXT, pos TEXT, seq TEXT, n INTEGER);
CREATE TABLE usage_coll(headword TEXT, pos TEXT, pattern TEXT, display TEXT, n INTEGER, rank INTEGER);
CREATE TABLE usage_example(headword TEXT, pos TEXT, kind TEXT, key TEXT, text TEXT, source TEXT, hl_start INTEGER,
  hl_end INTEGER, n_words INTEGER, score REAL);
CREATE TABLE usage_role(headword TEXT, pos TEXT, role TEXT, n INTEGER);
"""
INDEXES = """
CREATE INDEX usage_prep_hw ON usage_prep(headword);
CREATE INDEX usage_prep_seq_hw ON usage_prep_seq(headword);
CREATE INDEX usage_coll_hw ON usage_coll(headword);
CREATE INDEX usage_example_hw ON usage_example(headword);
CREATE INDEX usage_role_hw ON usage_role(headword);
"""


def write(con, words):
    """Chép phần đã chọn của corpus.sqlite vào DB đang dựng; chỉ các từ có trong `words`. Trả số dòng mỗi bảng."""
    if not CORPUS.exists():
        print(f"  (không có {CORPUS.name} — bỏ qua lớp cách dùng; chạy pipeline/corpus_build.py parse + merge)")
        return {}
    src = sqlite3.connect(f"file:{CORPUS.as_posix()}?mode=ro", uri=True)
    n = {}
    rows = [(w, POS[p], prep, obj, c, ratio, int(label == "thường gặp"))
            for w, p, prep, obj, c, ratio, label in src.execute(
                "SELECT headword, pos, prep, obj, n, ratio, label FROM prep_pattern WHERE pass = 1")
            if w in words]
    con.executemany("INSERT INTO usage_prep VALUES (?,?,?,?,?,?,?)", rows)
    n["usage_prep"] = len(rows)
    rows = [(w, POS[p], s, c) for w, p, s, c in src.execute("SELECT headword, pos, seq, n FROM prep_seq") if w in words]
    con.executemany("INSERT INTO usage_prep_seq VALUES (?,?,?,?)", rows)
    n["usage_prep_seq"] = len(rows)
    rows, coll_keys = [], set()
    for w, p, pat, disp, c, rank in src.execute(
            "SELECT headword, pos, pattern, display, n, rank FROM collocation WHERE rank <= ?", (COLL_PER_PATTERN,)):
        code = PATTERN.get((p, pat))
        if w in words and code:
            rows.append((w, POS[p], code, disp, c, rank))
            coll_keys.add((w, p, f"{pat}|{disp}"))
    con.executemany("INSERT INTO usage_coll VALUES (?,?,?,?,?,?)", rows)
    n["usage_coll"] = len(rows)
    rows = []
    for w, p, kind, key, text, source, a, b, nw, score in src.execute(
            "SELECT headword, pos, kind, key, text, source, hl_start, hl_end, n_words, score FROM usage_example"):
        if w not in words:
            continue
        if kind == "role":
            key = ROLE.get(key)
            if not key:
                continue
        elif kind == "coll":
            if (w, p, key) not in coll_keys:
                continue
            pat, disp = key.split("|", 1)
            key = f"{PATTERN[(p, pat)]}|{disp}"
        rows.append((w, POS[p], kind, key, text, source, a, b, nw, score))
    con.executemany("INSERT INTO usage_example VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    n["usage_example"] = len(rows)
    rows = [(w, POS[p], ROLE[r], c) for w, p, r, c in src.execute("SELECT headword, pos, role, n FROM role_count")
            if w in words and r in ROLE]
    con.executemany("INSERT INTO usage_role VALUES (?,?,?,?)", rows)
    n["usage_role"] = len(rows)
    built = src.execute("SELECT value FROM meta WHERE key = 'built_at'").fetchone()
    con.execute("INSERT OR REPLACE INTO meta VALUES ('usage_built', ?)", (built[0] if built else "",))
    src.close()
    return n


def main():
    """Thay các bảng usage_* trong DB đã dựng (để thử giao diện nhanh)."""
    t0 = time.time()
    con = sqlite3.connect(DB)
    for t in ("usage_prep", "usage_prep_seq", "usage_coll", "usage_example", "usage_role"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    con.executescript(SCHEMA)
    words = {w for (w,) in con.execute("SELECT word FROM headword")}
    n = write(con, words)
    # nguồn corpus mới (sources.toml) vào bảng source như build_db.py làm, để trang Giới thiệu liệt kê đủ
    import json
    import tomllib
    with open(ROOT / "pipeline" / "sources.toml", "rb") as f:
        sources = tomllib.load(f)["sources"]
    lock = json.loads((ROOT / "pipeline" / "sources.lock").read_text(encoding="utf-8"))
    for sid, s in sources.items():
        con.execute("INSERT OR IGNORE INTO source VALUES(?,?,?,?,?,?)", (sid, s["name"], s["license"], s.get("attribution"),
                                                                         s["url"], lock.get(sid, {}).get("retrieved_at")))
    con.executescript(INDEXES)
    con.commit()
    con.execute("VACUUM")
    con.close()
    print(f"[usage] {n} — {DB.stat().st_size / 2**20:.0f} MiB, {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
