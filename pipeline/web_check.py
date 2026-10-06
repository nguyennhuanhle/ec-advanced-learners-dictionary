"""Kiểm tra bản xuất web (UC-WM02, PLAN-web vòng W1): so JSON mục từ đã xuất với đầu ra của app desktop.

Dùng: python pipeline/web_check.py [--random 100] [--seed 1] [--exe app/src-tauri/target/debug/app.exe] [--diffs 12]

- Bộ từ kiểm tra cố định (CHECK_EN, CHECK_VI) + `--random` từ Anh và từ Việt chọn ngẫu nhiên (có hạt giống).
- Mỗi từ: đọc shard của bản xuất (fnv1a32 như export_web) và gọi `app.exe --call get_entry|get_vi_entry`,
  so bằng đúng toàn bộ JSON. Khác thì in đường dẫn trường khác + hai giá trị (không chỉ báo đạt/trượt).
- `known`: Rust lấy từ HashSet theo khúc 500 nên thứ tự có thể khác giữa hai lần chạy khi > 500 từ được nhắc;
  bản xuất sắp toàn bộ. Khác CHỈ ở thứ tự `known` được đếm riêng.
- Cũng so `sources.json` với lệnh `sources`, và in tóm tắt manifest (số file, dung lượng, file lớn nhất).
"""
import argparse
import json
import random
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_web as ew  # noqa: E402

EXE = ew.ROOT / "app" / "src-tauri" / "target" / "debug" / "app.exe"

CHECK_EN = [
    # tầng A, từ rất thường gặp / nhiều nghĩa
    "run", "set", "bank", "light", "go", "take", "get", "make", "do", "have", "be", "time", "good", "well",
    "the", "a", "I", "may", "an", "can", "will", "right", "book", "water", "beautiful", "quickly",
    # dạng biến đổi có mục riêng / ít gặp hơn
    "went", "children", "better", "mice", "was", "left",
    # cụm động từ, thành ngữ, cụm từ
    "give up", "look after", "put up with", "take off", "turn on", "by the way", "kick the bucket",
    "piece of cake", "break the ice", "in spite of", "as well as",
    # tầng B, chữ hoa, dấu, gạch nối, nháy
    # (café/naïve/résumé: desktop coi là chuỗi tiếng Việt vì có dấu → "none"; giữ lại để thấy hành vi đó)
    "English", "Monday", "café", "cafe", "naïve", "naive", "résumé", "resume", "well-known", "e-mail",
    "don't", "o'clock", "x-ray", "serendipity", "quixotic", "sesquipedalian", "zeitgeist", "aardvark",
]
CHECK_VI = [
    "nhà", "học", "đi", "ăn", "người", "tôi", "là", "có", "không", "của", "bạn", "anh", "nước", "yêu",
    "học sinh", "cảm ơn", "bánh mì", "tiếng Anh", "đẹp", "nha", "hoc", "Việt Nam", "máy tính", "con mèo",
]


def exported(vdir, word, vi):
    n = 1024 if vi else 2048
    path = vdir / ("v" if vi else "e") / f"{ew.fnv1a32(word) % n:04d}.json"
    return json.loads(path.read_text(encoding="utf-8")).get(word)


def cli(exe, cmd, args):
    r = subprocess.run([str(exe), "--call", cmd, json.dumps(args, ensure_ascii=False)], capture_output=True)
    if r.returncode != 0:
        return {"__error__": r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")}
    return json.loads(r.stdout.decode("utf-8"))


def diffs(a, b, path="", out=None):
    out = [] if out is None else out
    if type(a) is not type(b):
        out.append((path, a, b))
    elif isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                out.append((f"{path}.{k}", a.get(k, "<thiếu>"), b.get(k, "<thiếu>")))
            else:
                diffs(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append((f"{path} (độ dài {len(a)} ≠ {len(b)})", a, b))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append((path, a, b))
    return out


def short(v, n=140):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--random", type=int, default=100)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--exe", default=str(EXE))
    ap.add_argument("--diffs", type=int, default=12)
    a = ap.parse_args()
    exe = Path(a.exe)
    man = json.loads((ew.OUT / "manifest.json").read_text(encoding="utf-8"))
    vdir = ew.OUT / man["base"]
    print(f"Bản xuất: {vdir}  (data_version {man['data_version']}, {man['files']} file, {man['bytes'] / 2**20:.1f} MiB chưa nén)")
    biggest = sorted(((p.stat().st_size, p.relative_to(vdir).as_posix()) for p in vdir.rglob("*") if p.is_file()), reverse=True)[:3]
    print("File lớn nhất: " + ", ".join(f"{n} ({s / 1024:.0f} KiB)" for s, n in biggest))

    con = sqlite3.connect(f"file:{ew.DB.as_posix()}?mode=ro", uri=True)
    rnd = random.Random(a.seed)
    all_en = [r[0] for r in con.execute("SELECT word FROM headword ORDER BY word")]
    all_vi = [r[0] for r in con.execute("SELECT word FROM vi_headword ORDER BY word")]
    # từ Việt có câu Tatoeba (phần khó nhất của vi_entry) được lấy mẫu riêng
    tato_vi = sorted({w for w in all_vi if len(w) > 1} & {t for (v,) in con.execute("SELECT vi FROM tatoeba")
                                                          for t in v.lower().split()})
    con.close()
    # Bộ cố định đi qua lệnh lookup như giao diện (went → go, hoc → học/hóc…), rồi so mục từ của từ được chọn.
    split = set(man["prefix"]["split"])
    resolved, via_bad = [], 0
    with ThreadPoolExecutor(8) as ex:
        views = list(ex.map(lambda j: (j, cli(exe, "lookup", {"q": j[1], "mode": "en" if j[0] == "en" else "vien"})),
                            [("en", w) for w in CHECK_EN] + [("vi", w) for w in CHECK_VI]))
    print("\nTra (lookup) bộ cố định → từ đem so:")
    for (kind, w), v in views:
        k = v.get("kind")
        targets = [("en", v["word"])] if k == "en" else [("vi", v["word"])] if k == "vi" else \
            [(v["lang"], x) for x in v["words"][:3]] if k == "choice" else []
        resolved += targets
        note = ""
        if k == "en" and v.get("via"):   # dạng biến đổi: chỉ mục tiền tố "f" phải chọn đúng lemma như en_resolve
            fn = ew.rnorm(v["via"]["form"])
            pf = json.loads((vdir / "p" / f"{ew.bucket(fn, split)}.json").read_text(encoding="utf-8"))
            item = next((x for x in pf["f"] if x[0] == fn), None)
            want = [fn, v["via"]["lemma"], {"inflection": "i", "variant": "v"}[v["via"]["relation"]], v["via"]["tags"]]
            ok = item is not None and item[:4] == want
            via_bad += not ok
            note = f"  [via {v['via']['relation']} {v['via']['tags']!r}; p/…\"f\" {'ĐÚNG' if ok else 'KHÁC: ' + short(item)}]"
        print(f"  {kind} {w!r} → {k} {[t[1] for t in targets]}{note}")
    en = list(dict.fromkeys([t for k, t in resolved if k == "en"] +
                            rnd.sample([w for w in all_en if w not in CHECK_EN], a.random)))
    vi = list(dict.fromkeys([t for k, t in resolved if k == "vi"] +
                            rnd.sample([w for w in all_vi if w not in CHECK_VI], a.random) +
                            rnd.sample([w for w in tato_vi if w not in CHECK_VI], min(a.random // 2, len(tato_vi)))))
    fixed = {t for _, t in resolved}
    jobs = [("en", w) for w in en] + [("vi", w) for w in vi]

    def run(job):
        kind, w = job
        mine = exported(vdir, w, kind == "vi")
        ref = cli(exe, "get_vi_entry" if kind == "vi" else "get_entry", {"word": w})
        return kind, w, mine, ref

    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(run, jobs))

    stat = {"en": [0, 0, 0, 0], "vi": [0, 0, 0, 0]}   # [đúng hệt, chỉ khác thứ tự known, khác, cả hai null]
    for kind, w, mine, ref in results:
        tag = "[cố định]" if w in fixed else "[ngẫu nhiên]"
        if mine == ref:
            if mine is None:
                stat[kind][3] += 1
                print(f"  NULL  {kind} {w!r} {tag}: không có ở cả hai bên")
            else:
                stat[kind][0] += 1
            continue
        if mine and ref and kind == "en" and isinstance(ref, dict) and \
                {**mine, "known": sorted(mine["known"])} == {**ref, "known": sorted(ref.get("known", []))}:
            stat[kind][1] += 1
            print(f"  ~     en {w!r} {tag}: chỉ khác thứ tự `known` ({len(ref['known'])} từ, HashSet của Rust)")
            continue
        stat[kind][2] += 1
        d = diffs(mine, ref)
        print(f"  KHÁC  {kind} {w!r} {tag}: {len(d)} chỗ khác (trái = bản xuất, phải = app.exe)")
        for p, x, y in d[:a.diffs]:
            print(f"        {p or '<gốc>'}: {short(x)}  ≠  {short(y)}")

    src_mine = json.loads((vdir / "sources.json").read_text(encoding="utf-8"))
    src_ref = cli(exe, "sources", {})
    print(f"\nsources.json = lệnh sources: {'ĐÚNG' if src_mine == src_ref else 'KHÁC'}")
    for kind, (ok, kn, bad, nul) in stat.items():
        n = ok + kn + bad + nul
        print(f"{kind}: {ok + nul}/{n} bằng đúng" + (f" (trong đó {nul} cả hai null)" if nul else "") +
              (f", {kn} chỉ khác thứ tự known" if kn else "") + f", {bad} khác")
    fixed_en = sum(1 for k, w, *_ in results if k == "en" and w in fixed)
    fixed_vi = sum(1 for k, w, *_ in results if k == "vi" and w in fixed)
    print(f"(bộ cố định: {len(CHECK_EN)} + {len(CHECK_VI)} chuỗi tra → {fixed_en} mục Anh + {fixed_vi} mục Việt; "
          f"ngẫu nhiên hạt giống {a.seed}; dạng biến đổi sai lemma trong p/…\"f\": {via_bad})")
    sys.exit(1 if any(s[2] for s in stat.values()) or src_mine != src_ref or via_bad else 0)


if __name__ == "__main__":
    main()
