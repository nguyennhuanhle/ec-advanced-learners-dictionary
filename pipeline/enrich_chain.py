"""Nối tiếp đợt Gemini: chờ đợt chính kết thúc bình thường rồi làm lại các lô lỗi bằng model khác.

Dùng (chạy ngầm, tách khỏi phiên):
  python pipeline/enrich_chain.py <PID đợt chính> [--model gemini-3.8-flash-medium] [--workers 4] [--rounds 3]

- Chỉ nối tiếp khi dòng "run: kết thúc" cuối log KHÔNG có "(đã dừng)" — tức đợt chính chạy hết, không phải dừng vì
  quota, 6 lô lỗi liên tiếp hay file STOP. Ngược lại: ghi log rồi thoát, để người xem quyết định.
- Mỗi vòng chạy `enrich.py run --retry-model <model>`; dừng khi hết lô lỗi hoặc hết số vòng.
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "work"
LOG = WORK / "enrich-run.log"
OUT = WORK / "enrich"
FAIL = WORK / "enrich-fail"


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [chain] {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def alive(pid):
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True).stdout
    return f" {pid} " in out


def pending_failures():
    done = {p.stem for p in OUT.glob("*.json")}
    return sorted(p.stem for p in FAIL.glob("*.txt") if p.stem not in done) if FAIL.exists() else []


def last_end_line():
    lines = [l for l in LOG.read_text(encoding="utf-8").splitlines() if "run: kết thúc" in l and "[chain]" not in l]
    return lines[-1] if lines else ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pid", type=int)
    ap.add_argument("--model", default="gemini-3.8-flash-medium")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=3)
    a = ap.parse_args()

    log(f"chờ đợt chính (PID {a.pid}) kết thúc, sau đó làm lại lô lỗi bằng {a.model}")
    while alive(a.pid):
        time.sleep(30)
    end = last_end_line()
    if not end or "(đã dừng)" in end:
        log(f"đợt chính không kết thúc bình thường ({end or 'không thấy dòng kết thúc'}) → không tự làm lại, chờ người xem")
        return
    for r in range(1, a.rounds + 1):
        fails = pending_failures()
        if not fails:
            log("không còn lô lỗi → xong toàn bộ")
            return
        log(f"vòng làm lại {r}/{a.rounds}: {len(fails)} lô lỗi, model {a.model}, {a.workers} luồng")
        subprocess.run([sys.executable, "-u", str(ROOT / "pipeline" / "enrich.py"), "run",
                        "--workers", str(a.workers), "--retry-model", a.model], cwd=ROOT)
        end = last_end_line()
        if "(đã dừng)" in end:
            log("vòng làm lại bị dừng (quota / lỗi liên tiếp / STOP) → ngừng nối tiếp")
            return
    left = pending_failures()
    log(f"hết {a.rounds} vòng, còn {len(left)} lô lỗi: {', '.join(left[:10])}")


if __name__ == "__main__":
    main()
