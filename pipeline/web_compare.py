"""So bộ giải từ của bản web với app desktop (PLAN-web vòng W2, UC-WM02).

Dùng: python pipeline/web_compare.py [--exe app/src-tauri/target/debug/app.exe] [--out _deliverables/web-w2-compare.md]

- ~330 chuỗi tra (từ thường, dạng biến đổi, tiếng Việt không dấu/có dấu, sai chính tả, cụm từ, từ hai chiều,
  chữ hoa/gạch nối/nháy, chuỗi rác, rỗng, rất dài, tiền tố) × chế độ envi, vien × lệnh suggest, lookup.
  (Rust chỉ phân biệt mode == "vien" hay không, nên "en" cho kết quả như "envi".)
- Bên web: app/src/lib/web/core.ts chạy trong Node (pipeline/web_core_cli.mjs) đọc data/build/web/.
  Bên desktop: `app.exe --call suggest|lookup`. So bằng đúng JSON; khác thì in cả hai.
- Thêm: get_entry / get_vi_entry của mọi từ mà lookup trỏ tới; 600 ứng viên FTS mô phỏng (bm25) so với SQLite thật
  cho các chuỗi sai chính tả; thời gian gợi ý chính tả trong Node.
- Ghi bảng song song (để đọc bằng mắt) ra _deliverables/web-w2-compare.md và in tóm tắt.
"""
import argparse
import json
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_web as ew  # noqa: E402
import web_check as wc  # noqa: E402

ROOT = ew.ROOT
NODE_CLI = ROOT / "pipeline" / "web_core_cli.mjs"

TAB, NL = chr(9), chr(10)
GROUPS = [
    ("Từ thường", "run set bank light go take get make do have be time good well the a I can will right book water "
     "beautiful quickly people house school friend love happy work play study teacher student computer phone money "
     "family music movie city country language english word dictionary question answer important different example because".split()),
    ("Dạng biến đổi", "went children better mice was left ran geese feet women best worse eaten written studies studying "
     "cities analyses criteria phenomena bigger happier stopped lying teeth knives wolves men oxen sung swum flew flown "
     "did does has had been taught bought thought caught ate gone seen".split()),
    ("Tiếng Việt không dấu", ["nha", "hoc sinh", "ngan hang", "hoc", "an", "di", "nguoi", "toi", "ban", "cam on", "banh mi",
                              "tieng anh", "dep", "viet nam", "may tinh", "con meo", "nuoc", "yeu", "truong hoc",
                              "giao vien", "thanh pho", "gia dinh", "cong viec", "dien thoai", "sach", "ca phe", "xin chao",
                              "hanh phuc", "mua", "nha hang", "bac si", "hoa", "sang", "chao", "ngu"]),
    ("Tiếng Việt có dấu", ["nhà", "học", "ngân hàng", "đi", "ăn", "người", "tôi", "bạn", "cảm ơn", "bánh mì", "tiếng Anh",
                           "đẹp", "Việt Nam", "máy tính", "con mèo", "nước", "yêu", "học sinh", "trường học", "giáo viên",
                           "thành phố", "gia đình", "công việc", "điện thoại", "sách", "cà phê", "xin chào", "hạnh phúc",
                           "NHÀ", "Hà Nội"]),
    ("Sai chính tả", "recieve bnak definately seperate occured accomodate untill wich teh adress beleive goverment "
     "enviroment tommorow neccessary embarass calender freind wierd thier truely begining existance occurence publically "
     "rythm supercede arguement buisness collegue concious foriegn grammer independant knowlege millenium noticable "
     "recomend refered succesful tounge wether becuase peice diffrent intresting".split()),
    ("Cụm từ", ["give up", "by the way", "look after", "put up with", "take off", "turn on", "kick the bucket",
                "piece of cake", "break the ice", "in spite of", "as well as", "at least", "of course", "in order to",
                "a lot of", "according to", "as soon as", "take care of", "get rid of", "give in", "make up", "run out of",
                "look forward to", "by heart", "on time", "Give Up", "give  up", "gave up", "giving up", "looked after"]),
    ("Từ có ở cả hai chiều", "may an ban me to hoa sang cho the la con so ma hat mat bia ca tin chat nam bo em hay lam tam".split()),
    ("Chữ hoa, dấu, gạch nối, nháy", ["English", "Monday", "ENGLISH", "english", "monday", "café", "cafe", "naïve", "naive",
                                      "résumé", "resume", "e-mail", "email", "don't", "o'clock", "x-ray", "well-known",
                                      "U.S.", "Mr.", "T-shirt", "rock'n'roll", "RUN", "Run", "rUn", "Bank"]),
    ("Chuỗi rác, rỗng, rất dài", ["", "   ", "!!!", "123", "x", "a", "qzx", "zzzzzz", "asdfghjkl", "@#$%", "hello123",
                                  "😀", "日本", "русский", "?", "*", "...", "vi:", "vi:nha", "vi:went", "vi:bank",
                                  "a" * 300, ("word " * 300).strip(), "the quick brown fox jumps over the lazy dog",
                                  f"run{TAB}fast{NL}now", "  run  ", "rừn", "ñandú", "Straße", "-", "'"]),
    ("Tiền tố (ô gợi ý)", ["b", "co", "con", "th", "re", "su", "ng", "kh", "tr", "ch", "nh", "giv", "give u", "s", "q",
                           "học s", "ngân h", "hoc s", "comp", "unbel"]),
]
MODES = ["envi", "vien"]
BENCH = ["recieve", "bnak", "definately", "seperate", "accomodate", "goverment", "neccessary", "intresting"]


def node(jobs):
    r = subprocess.run(["node", str(NODE_CLI)], input=json.dumps(jobs, ensure_ascii=False).encode("utf-8"),
                       capture_output=True)
    if r.returncode != 0:
        raise SystemExit("Node lỗi:\n" + r.stderr.decode("utf-8", "replace"))
    return json.loads(r.stdout.decode("utf-8"))


def app_calls(exe, jobs):
    with ThreadPoolExecutor(8) as ex:
        return list(ex.map(lambda j: wc.cli(exe, j["cmd"], j["args"]), jobs))


def web_value(r):
    return r["value"] if r["ok"] else {"__error__": r["error"]}


# ---------------------------------------------------------------- hiển thị gọn

def esc(s):
    return s.replace("|", "\\|").replace(NL, "⏎").replace(TAB, "⇥")


def show_q(q):
    if q == "":
        return "*(rỗng)*"
    if not q.strip():
        return f"*({len(q)} dấu cách)*"
    if len(q) > 40:
        return f"`{esc(q[:24])}…` *({len(q)} ký tự)*"
    return f"`{esc(q)}`"


def show_view(v):
    if not isinstance(v, dict):
        return esc(json.dumps(v, ensure_ascii=False))
    if "__error__" in v:
        return "LỖI: " + esc(str(v["__error__"])[:120])
    k = v.get("kind")
    if k == "en":
        s = f"**EN** {esc(v['word'])}"
        if v.get("via"):
            s += f" ← {esc(v['via']['form'])} ({v['via']['relation']}{': ' + esc(v['via']['tags']) if v['via']['tags'] else ''})"
        if v.get("also_vi"):
            s += f"; cũng có VI: {esc(v['also_vi'])}"
        return s
    if k == "vi":
        return f"**VI** {esc(v['word'])}" + (f"; cũng có EN: {esc(v['also_en'])}" if v.get("also_en") else "")
    if k == "choice":
        w = v["words"]
        return f"**CHỌN {v['lang'].upper()}** ({len(w)}): " + esc(", ".join(w[:8])) + (" …" if len(w) > 8 else "")
    if k == "none":
        s = [x["word"] for x in v["suggestions"]]
        return "**KHÔNG CÓ**" + (" → " + esc(", ".join(s)) if s else "")
    if k == "empty":
        return "*(rỗng)*"
    return esc(json.dumps(v, ensure_ascii=False)[:120])


def show_sug(lst):
    if not isinstance(lst, list):
        return show_view(lst)
    if not lst:
        return "—"
    out = []
    for s in lst:
        if s.get("note") == "Việt":
            out.append(f"{s['label']}ᵛ")
        elif s.get("note"):
            out.append(f"{s['label']}→{s['key']}")
        else:
            out.append(s["label"])
    return esc(", ".join(out))


# ---------------------------------------------------------------- FTS thật (SQLite) để đối chiếu mô phỏng bm25

def fts_sqlite(con, q):
    chars = [c for c in q if c.isalpha()]
    if len(chars) < 3:
        return []
    grams = {"".join(chars[i:i + 3]) for i in range(len(chars) - 2)}
    sql = ("SELECT f.word, rank FROM fts_headword f JOIN headword h ON h.word = f.word "
           "WHERE fts_headword MATCH ?1 ORDER BY rank LIMIT 600")
    return con.execute(sql, (" OR ".join(f'"{g}"' for g in grams),)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--exe", default=str(wc.EXE))
    ap.add_argument("--out", default=str(ROOT / "_deliverables" / "web-w2-compare.md"))
    a = ap.parse_args()
    exe = Path(a.exe)
    man = json.loads((ew.OUT / "manifest.json").read_text(encoding="utf-8"))
    t0 = time.time()

    # 1) suggest + lookup cho mọi chuỗi × chế độ
    cases = [(g, q, m, cmd) for g, qs in GROUPS for q in qs for m in MODES for cmd in ("lookup", "suggest")]
    jobs = [{"cmd": cmd, "args": {"q": q, "mode": m}} for _, q, m, cmd in cases]
    web = node(jobs)
    ref = app_calls(exe, jobs)
    res = {}
    for (g, q, m, cmd), w, r in zip(cases, web, ref):
        res[(g, q, m, cmd)] = (web_value(w), r, w.get("ms"))

    # 2) mục từ mà lookup trỏ tới (cả hai bên), so get_entry / get_vi_entry
    targets = set()
    for (g, q, m, cmd), (w, r, _) in res.items():
        if cmd != "lookup":
            continue
        for v in (w, r):
            if not isinstance(v, dict):
                continue
            if v.get("kind") == "en":
                targets.add(("get_entry", v["word"]))
            elif v.get("kind") == "vi":
                targets.add(("get_vi_entry", v["word"]))
            elif v.get("kind") == "choice":
                for x in v["words"][:3]:
                    targets.add(("get_entry" if v["lang"] == "en" else "get_vi_entry", x))
    targets = sorted(targets)
    ejobs = [{"cmd": c, "args": {"word": w}} for c, w in targets]
    eweb = node(ejobs)
    eref = app_calls(exe, ejobs)
    entry_bad = [(c, w) for (c, w), x, y in zip(targets, eweb, eref) if web_value(x) != y]

    # 3) 600 ứng viên FTS: mô phỏng bm25 (web) so với SQLite thật, cho nhóm sai chính tả
    con = sqlite3.connect(f"file:{ew.DB.as_posix()}?mode=ro", uri=True)
    miss = dict(GROUPS)["Sai chính tả"]
    fweb = node([{"cmd": "__fts", "args": {"q": q.lower()}} for q in miss])
    fts_rows = []
    for q, fw in zip(miss, fweb):
        mine = [x[0] for x in fw["value"]]
        real = fts_sqlite(con, q.lower())
        rw = [x[0] for x in real]
        maxdiff = max((abs(x[1] - y[1]) for x, y in zip(fw["value"], real)), default=0.0)
        fts_rows.append((q, mine == rw, len(set(mine) & set(rw)), len(rw), maxdiff))

    # 4) thời gian gợi ý chính tả trong Node
    rb = subprocess.run(["node", str(NODE_CLI), "--bench", *BENCH], capture_output=True)
    bench = json.loads(rb.stdout.decode("utf-8"))

    # ---------------------------------------------------------------- báo cáo
    def same(k):
        w, r, _ = res[k]
        return w == r

    total = len(res)
    ok = sum(1 for k in res if same(k))
    lines = [
        "# So sánh bộ giải từ bản web với app desktop — vòng W2",
        "",
        f"Chạy lúc {time.strftime('%Y-%m-%d %H:%M')} · dữ liệu web `{man['base']}` ({man['files']} file) · "
        f"desktop: `{exe.relative_to(ROOT).as_posix() if exe.is_relative_to(ROOT) else exe}` (`--call`).",
        "",
        "Bên **web** là `app/src/lib/web/core.ts` (đúng mã chạy trong Web Worker) chạy trong Node, đọc `data/build/web/`. "
        "Bên **desktop** là `app.exe --call suggest|lookup`. Hai bên được so bằng đúng toàn bộ JSON.",
        "",
        "## Tóm tắt",
        "",
        f"- **suggest + lookup: {ok}/{total} khớp hoàn toàn** ({len(set(q for _, q, _, _ in res))} chuỗi × 2 chế độ × 2 lệnh).",
        f"- **Mục từ** (`get_entry`/`get_vi_entry` của mọi từ mà lookup trỏ tới): "
        f"{len(targets) - len(entry_bad)}/{len(targets)} khớp" + (f" — khác: {entry_bad}" if entry_bad else "") + ".",
        f"- **600 ứng viên FTS** (mô phỏng bm25 + LIMIT 600 thay cho FTS5): {sum(1 for r in fts_rows if r[1])}/{len(fts_rows)} "
        f"chuỗi sai chính tả ra đúng cả danh sách và thứ tự như SQLite; chênh điểm bm25 lớn nhất "
        f"{max(r[4] for r in fts_rows):.1e}.",
        f"- **Thời gian gợi ý chính tả** (Node {sys.platform}, sau khi đã nạp words.txt): "
        + ", ".join(f"{w} {v['median_ms']} ms" for w, v in bench["fuzzy"].items())
        + f". Nạp + phân tích words.txt lần đầu: {bench['load_words_ms']} ms (chưa tính thời gian tải 0,86 MiB gzip).",
        "",
        "| Nhóm | Số chuỗi | lookup khớp | suggest khớp |",
        "|---|---|---|---|",
    ]
    for g, qs in GROUPS:
        lk = [k for k in res if k[0] == g and k[3] == "lookup"]
        sg = [k for k in res if k[0] == g and k[3] == "suggest"]
        lines.append(f"| {g} | {len(qs)} | {sum(map(same, lk))}/{len(lk)} | {sum(map(same, sg))}/{len(sg)} |")
    bad = [k for k in res if not same(k)]
    lines += ["", "## Chỗ khác nhau", ""]
    if not bad:
        lines.append("Không có. Mọi kết quả suggest và lookup của web giống hệt app desktop.")
    for k in bad:
        w, r, _ = res[k]
        lines += [f"- {k[0]} · {show_q(k[1])} · {k[2]} · {k[3]}",
                  f"  - web: `{esc(json.dumps(w, ensure_ascii=False))[:600]}`",
                  f"  - app.exe: `{esc(json.dumps(r, ensure_ascii=False))[:600]}`"]
    lines += ["", "## Bảng song song", "",
              "Cột *app.exe* ghi **= web** khi desktop cho đúng kết quả đó; khác thì ghi kết quả của desktop. "
              "Gợi ý: `từᵛ` = gợi ý tiếng Việt, `went→go` = dạng biến đổi trỏ về từ gốc.", ""]
    for g, qs in GROUPS:
        lines += [f"### {g}", "", "| Chuỗi | Chế độ | Tra (lookup) — web | app.exe | Gợi ý (suggest) — web | app.exe |",
                  "|---|---|---|---|---|---|"]
        for q in qs:
            for m in MODES:
                lw, lr, _ = res[(g, q, m, "lookup")]
                sw, sr, _ = res[(g, q, m, "suggest")]
                lines.append(f"| {show_q(q)} | {m} | {show_view(lw)} | {'= web' if lw == lr else '**KHÁC:** ' + show_view(lr)} | "
                             f"{show_sug(sw)} | {'= web' if sw == sr else '**KHÁC:** ' + show_sug(sr)} |")
        lines.append("")
    lines += ["## 600 ứng viên FTS: mô phỏng (web) và SQLite thật", "",
              "Desktop lấy ứng viên gợi ý chính tả bằng FTS5 trigram (`ORDER BY rank LIMIT 600`). Bản web không có FTS nên "
              "tính lại điểm bm25 trên `words.txt` (xếp theo rowid của `fts_headword`) rồi lấy 600 dòng đầu.", "",
              "| Chuỗi | Danh sách + thứ tự giống hệt | Chung / số dòng SQLite | Chênh điểm lớn nhất |", "|---|---|---|---|"]
    for q, eq, inter, n, md in fts_rows:
        lines.append(f"| `{q}` | {'có' if eq else '**không**'} | {inter}/{n} | {md:.1e} |")
    lines += ["", "## Thời gian gợi ý chính tả (Node, trung vị 7 lần)", "", "| Chuỗi | Trung vị (ms) | Lâu nhất (ms) | 5 gợi ý đầu |",
              "|---|---|---|---|"]
    for w, v in bench["fuzzy"].items():
        lines.append(f"| `{w}` | {v['median_ms']} | {v['max_ms']} | {', '.join(v['first'])} |")
    lines.append(f"\nNạp words.txt (đọc file + tách dòng + gấp chữ cho 136.072 từ): {bench['load_words_ms']} ms.")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(NL.join(lines) + NL, encoding="utf-8")

    print(f"suggest + lookup: {ok}/{total} khớp; mục từ: {len(targets) - len(entry_bad)}/{len(targets)} khớp; "
          f"FTS mô phỏng: {sum(1 for r in fts_rows if r[1])}/{len(fts_rows)} giống hệt")
    for k in bad:
        w, r, _ = res[k]
        print(f"  KHÁC {k}: web={json.dumps(w, ensure_ascii=False)[:300]}")
        print(f"       {' ' * len(str(k))}  app={json.dumps(r, ensure_ascii=False)[:300]}")
    for q, eq, inter, n, md in fts_rows:
        if not eq:
            print(f"  FTS khác: {q} chung {inter}/{n}")
    print("Thời gian gợi ý chính tả (ms):", {w: v["median_ms"] for w, v in bench["fuzzy"].items()},
          "nạp words.txt:", bench["load_words_ms"])
    print(f"Đã ghi {a.out} ({time.time() - t0:.0f} s)")
    sys.exit(1 if bad or entry_bad else 0)


if __name__ == "__main__":
    main()
