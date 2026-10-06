"""Làm giàu tầng A bằng Gemini 3.8 Flash qua agy (UC-M05).

Từ thường (< HARD_SENSES nghĩa nguồn): gemini-3.8-flash-low, tối đa 5 từ / 40 nghĩa mỗi lô.
Từ khó (≥ HARD_SENSES nghĩa):        gemini-3.8-flash-medium, tối đa 2 từ / 40 nghĩa mỗi lô.
Lô đi theo thứ tự tần suất. Mỗi lô ghi một file trong data/work/enrich/ → dừng lúc nào cũng chạy tiếp được.

Dùng:
  python pipeline/enrich.py prepare --top 20000   # gom nguồn → data/work/tierA-source.json, tierA-batches.json
  python pipeline/enrich.py run [--workers 3] [--limit N] [--retry-model gemini-3.8-flash-medium]
      --retry-model: lô từng lỗi (có file trong enrich-fail/) chạy lại bằng model này (vd. medium ít trả JSON hỏng hơn)
  python pipeline/enrich.py status
  python pipeline/enrich.py collect               # gộp kết quả hợp lệ → data/work/tierA-ai.json + rejects

Đợt bổ sung (gaps): (từ, từ loại) bị giới hạn MAX_INPUT_SENSES (tính chung cả từ) cắt mất hoặc cắt dở ở đợt chính,
ví dụ run/noun, go/noun. Mỗi từ loại được tối đa MAX_INPUT_SENSES nghĩa riêng. Từ loại AI đã cố ý bỏ (be/noun) không làm lại.
  python pipeline/enrich.py prepare-gaps          # → data/work/tierA2-source.json, tierA2-batches.json
  python pipeline/enrich.py run --pass gaps [--workers N] [--retry-model M]   # kết quả → data/work/enrich2/
  python pipeline/enrich.py status --pass gaps
build_db.py dùng kết quả gaps thay cho kết quả đợt chính của đúng (từ, từ loại) đó khi có nghĩa.
"""
import argparse
import gzip
import hashlib
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agy_client import Agy
from enrich_sample import PROMPT, RAW, SCHEMA, SKIP_TAGS, norm_pos, payload_for, validate

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "data" / "work"
OUT = WORK / "enrich"
FAIL = WORK / "enrich-fail"
SOURCE = WORK / "tierA-source.json"
PLAN = WORK / "tierA-batches.json"
LOG = WORK / "enrich-run.log"
STOP = WORK / "enrich.STOP"  # tạo file này để dừng êm sau các lô đang chạy
GAP_SOURCE = WORK / "tierA2-source.json"
GAP_PLAN = WORK / "tierA2-batches.json"
GAP_OUT = WORK / "enrich2"
GAP_FAIL = WORK / "enrich2-fail"
TAG = ""  # tiền tố dòng log của đợt đang chạy


def use_pass(name):
    """Đổi bộ file nguồn/kế hoạch/kết quả cho run, status, collect."""
    global SOURCE, PLAN, OUT, FAIL, TAG
    if name == "gaps":
        SOURCE, PLAN, OUT, FAIL, TAG = GAP_SOURCE, GAP_PLAN, GAP_OUT, GAP_FAIL, "[gaps] "

PROMPT_VERSION = "A1"
HARD_SENSES = 10
LOW = ("gemini-3.8-flash-low", 5, 40)
MEDIUM = ("gemini-3.8-flash-medium", 2, 40)
MAX_INPUT_SENSES = 60  # từ quá nhiều nghĩa (run, set...) chỉ đưa 60 nghĩa đầu của Wiktionary
SKIP_POS = {"name", "character", "symbol", "romanization"}
WORD_RE = re.compile(r"^[a-z][a-z'\-]*( [a-z][a-z'\-]*)*$")

PROMPT_A = PROMPT + """
Do not create, read or edit any files and do not run any tools. Reply in the message itself.
"""

QUOTA_HINTS = ("quota", "resource_exhausted", "rate limit", "rate-limit", "429", "usage limit", "too many requests")


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {TAG}{msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------- prepare ----------

def prepare(top):
    ranked = json.loads((WORK / "tier-a-senses.json").read_text(encoding="utf-8"))
    words = [w for w, _ in ranked if WORD_RE.match(w)][:top]
    log(f"prepare: {len(words)} từ, đọc Wiktionary EN...")
    en = read_en(words)
    # cắt bớt từ quá nhiều nghĩa, giữ thứ tự Wiktionary
    for w, entries in en.items():
        budget = MAX_INPUT_SENSES
        for e in entries:
            e["senses"] = e["senses"][:max(budget, 0)]
            budget -= len(e["senses"])
        en[w] = [e for e in entries if e["senses"]]
    log("prepare: đọc Wiktionary VI...")
    vi = {w: [] for w in words}
    with gzip.open(RAW / "viwikt-raw.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if d.get("lang_code") == "en" and d.get("word") in vi:
                vi[d["word"]].append({"pos": norm_pos(d.get("pos")),
                                      "glosses": [g for s in d.get("senses") or [] for g in s.get("glosses") or []]})
    SOURCE.write_text(json.dumps({"en": en, "vi": vi}, ensure_ascii=False), encoding="utf-8")
    make_plan(words, en, top, PROMPT_VERSION)


def read_en(words):
    """Mọi nghĩa dùng được của Wiktionary EN cho các từ, theo thứ tự Wiktionary (chưa cắt)."""
    want = set(words)
    en = {w: [] for w in words}
    with gzip.open(RAW / "kaikki-en.jsonl.gz", "rt", encoding="utf-8") as f:
        for line in f:
            if '"lang_code": "en"' not in line:
                continue
            d = json.loads(line)
            if d.get("lang_code") != "en" or d.get("word") not in want or d.get("pos") in SKIP_POS:
                continue
            senses = []
            for s in d.get("senses") or []:
                tags = set(s.get("tags") or [])
                if not s.get("glosses") or tags & SKIP_TAGS:
                    continue
                ex = next((e.get("text") for e in s.get("examples") or []
                           if e.get("text") and e.get("type") != "quotation" and len(e["text"]) <= 160), None)
                senses.append({"gloss": s["glosses"][-1], "tags": sorted(tags), "ex": ex})
            if senses:
                en[d["word"]].append({"pos": norm_pos(d.get("pos")), "senses": senses})
    return en


def prepare_gaps():
    """(từ, từ loại) mà đợt chính đưa cho AI ít nghĩa hơn mức một từ loại được hưởng (MAX_INPUT_SENSES)."""
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    words = json.loads(PLAN.read_text(encoding="utf-8"))
    order = [w for b in sorted(words["batches"], key=lambda b: b["rank_first"]) for w in b["words"]] + words["skipped"]
    have = {}
    for w, entries in src["en"].items():
        for e in entries:
            have[(w, e["pos"])] = have.get((w, e["pos"]), 0) + len(e["senses"])
    # (từ, từ loại) đã gửi AI nhưng AI không trả về (bỏ sót, hoặc mục bị validate loại) → cũng làm lại.
    # Trả về với danh sách nghĩa rỗng = AI cố ý bỏ từ loại hiếm (be/noun) → không làm lại.
    answered = set()
    for p in OUT.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        ok, _ = validate(d["result"], set(d["batch"]["words"]), src["en"])
        answered |= {(e["word"], e["pos"]) for e in ok}
    missed = {k for k in have if k not in answered}
    log(f"prepare-gaps: {len(missed)} (từ, từ loại) đã gửi nhưng AI không trả về; đọc Wiktionary EN cho {len(order)} từ...")
    full = read_en(order)
    gaps, n_new, n_part = {}, len(missed), 0
    for w in order:
        by_pos = {}
        for e in full[w]:
            by_pos.setdefault(e["pos"], []).append(e)
        for pos, entries in by_pos.items():
            n_full = sum(len(e["senses"]) for e in entries)
            got = have.get((w, pos), 0)
            if (w, pos) not in missed:
                if got >= min(n_full, MAX_INPUT_SENSES):
                    continue
                n_new += got == 0
                n_part += got > 0
            budget = MAX_INPUT_SENSES
            for e in entries:
                cut = e["senses"][:max(budget, 0)]
                budget -= len(cut)
                if cut:
                    gaps.setdefault(w, []).append({"pos": pos, "senses": cut})
    vi = {w: src["vi"].get(w, []) for w in gaps}
    GAP_SOURCE.write_text(json.dumps({"en": gaps, "vi": vi}, ensure_ascii=False), encoding="utf-8")
    log(f"prepare-gaps: {len(gaps)} từ, {n_new} từ loại chưa có AI + {n_part} từ loại bị cắt dở, "
        f"{sum(len(e['senses']) for v in gaps.values() for e in v)} nghĩa nguồn")
    use_pass("gaps")
    make_plan([w for w in order if w in gaps], gaps, len(gaps), "B1")


def make_plan(words, en, top, version):
    batches = []
    cur = {"low": ([], 0), "medium": ([], 0)}

    def flush(kind):
        ws, _ = cur[kind]
        if ws:
            model = (MEDIUM if kind == "medium" else LOW)[0]
            key = hashlib.sha1(f"{version}|{model}|{'|'.join(ws)}".encode()).hexdigest()[:14]
            batches.append({"id": key, "model": model, "words": ws, "rank_first": rank_of[ws[0]]})
        cur[kind] = ([], 0)

    rank_of = {w: i + 1 for i, w in enumerate(words)}
    skipped = []
    for w in words:
        n = sum(len(e["senses"]) for e in en[w])
        if not n:
            skipped.append(w)
            continue
        kind = "medium" if n >= HARD_SENSES else "low"
        _, max_w, max_s = MEDIUM if kind == "medium" else LOW
        ws, s = cur[kind]
        if ws and (len(ws) + 1 > max_w or s + n > max_s):
            flush(kind)
            ws, s = cur[kind]
        cur[kind] = (ws + [w], s + n)
    flush("low")
    flush("medium")
    batches.sort(key=lambda b: b["rank_first"])
    PLAN.write_text(json.dumps({"top": top, "batches": batches, "skipped": skipped}, ensure_ascii=False),
                    encoding="utf-8")
    n_med = sum(b["model"] == MEDIUM[0] for b in batches)
    log(f"prepare: {len(batches)} lô ({n_med} medium, {len(batches) - n_med} low); "
        f"{len(skipped)} từ không có nghĩa dùng được: {skipped[:15]}")


# ---------- run ----------

class Runner:
    def __init__(self, workers):
        src = json.loads(SOURCE.read_text(encoding="utf-8"))
        self.en, self.vi = src["en"], src["vi"]
        self.batches = json.loads(PLAN.read_text(encoding="utf-8"))["batches"]
        self.workers = workers
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.consecutive_fail = 0
        self.done_now = 0

    def fail(self, b, msg):
        FAIL.mkdir(parents=True, exist_ok=True)
        (FAIL / f"{b['id']}.txt").write_text(f"{b}\n\n{msg}", encoding="utf-8")
        with self.lock:
            self.consecutive_fail += 1
            n = self.consecutive_fail
        log(f"LỖI lô {b['id']} ({', '.join(b['words'])}): {msg[:200]}")
        if any(h in msg.lower() for h in QUOTA_HINTS):
            log("Có dấu hiệu hết quota/giới hạn → dừng.")
            self.stop.set()
        elif n >= 6:
            log("6 lô lỗi liên tiếp → dừng để kiểm tra.")
            self.stop.set()

    def one(self, b):
        # lỗi bất ngờ ở một lô (vd. AI trả JSON thiếu trường) chỉ ghi vào enrich-fail/, không làm sập cả đợt
        try:
            self._one(b)
        except Exception as e:  # noqa: BLE001
            self.fail(b, f"lỗi không lường trước: {type(e).__name__}: {e}")

    def _one(self, b):
        if self.stop.is_set() or STOP.exists():
            self.stop.set()
            return
        out = OUT / f"{b['id']}.json"
        if out.exists():
            return
        payload = "\n\n".join(payload_for(w, self.en[w], self.vi.get(w, [])) for w in b["words"])
        agy = Agy(model=b["model"])
        t0 = time.time()
        try:
            result, meta = agy.generate_json(PROMPT_A.format(payload=payload), SCHEMA)
        except RuntimeError as e:
            self.fail(b, str(e))
            return
        ok, rej = validate(result, set(b["words"]), self.en)
        if not ok:  # không có mục nào dùng được → không lưu, để lần chạy sau làm lại
            self.fail(b, f"không có mục hợp lệ; loại: {json.dumps(rej, ensure_ascii=False)[:300]}")
            return
        # ghi file tạm rồi đổi tên: máy tắt giữa chừng không để lại file kết quả dở dang
        tmp = out.with_suffix(".part")
        tmp.write_text(json.dumps({"batch": b, "meta": meta, "result": result, "n_ok": len(ok),
                                   "rejects": rej}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(out)
        with self.lock:
            self.consecutive_fail = 0
            self.done_now += 1
            k = self.done_now
        if k % 10 == 0 or k <= 3:
            log(f"xong {k} lô trong lần chạy này; lô {b['id']} {b['model'][-6:]} {round(time.time() - t0)}s "
                f"[{', '.join(b['words'])}]")

    def run(self, limit=None, retry_model=None):
        OUT.mkdir(parents=True, exist_ok=True)
        # dọn dấu vết của lần chạy bị ngắt (restart máy, mất điện): file tạm và file kết quả không đọc được
        for p in OUT.glob("*.part"):
            p.unlink()
        for p in OUT.glob("*.json"):
            try:
                json.loads(p.read_text(encoding="utf-8"))
            except (ValueError, UnicodeDecodeError):
                log(f"xoá file kết quả hỏng {p.name}, sẽ chạy lại lô này")
                p.unlink()
        todo = [b for b in self.batches if not (OUT / f"{b['id']}.json").exists()]
        if retry_model:  # giữ id lô (tên file kết quả), chỉ đổi model cho lô từng lỗi
            todo = [dict(b, model=retry_model) if (FAIL / f"{b['id']}.txt").exists() else b for b in todo]
        if limit:
            todo = todo[:limit]
        log(f"run: còn {len(todo)} / {len(self.batches)} lô, {self.workers} luồng")
        with ThreadPoolExecutor(self.workers) as ex:
            list(ex.map(self.one, todo))
        log(f"run: kết thúc, xong {self.done_now} lô trong lần chạy này" + (" (đã dừng)" if self.stop.is_set() else ""))


# ---------- status / collect ----------

def status():
    batches = json.loads(PLAN.read_text(encoding="utf-8"))["batches"]
    done = {p.stem for p in OUT.glob("*.json")} if OUT.exists() else set()
    fails = {p.stem for p in FAIL.glob("*.txt")} - done if FAIL.exists() else set()
    words_done = sum(len(b["words"]) for b in batches if b["id"] in done)
    words_all = sum(len(b["words"]) for b in batches)
    remain = len(batches) - len(done)
    # tốc độ thật: số lô xong trong 30 phút gần nhất (đúng với mọi số luồng)
    now = time.time()
    recent = sum(1 for p in OUT.glob("*.json") if now - p.stat().st_mtime < 1800) if OUT.exists() else 0
    print(f"Lô: {len(done)}/{len(batches)} ({len(done) * 100 // max(len(batches), 1)}%) · "
          f"từ: {words_done}/{words_all} · lô lỗi chưa làm lại: {len(fails)}")
    if recent:
        rate = recent * 2  # lô/giờ
        print(f"30 phút qua: {recent} lô ({rate} lô/giờ) → còn khoảng {remain / rate:.1f} giờ")
    else:
        print("30 phút qua không có lô nào xong (đợt đang dừng?)")
    if LOG.exists():
        print("--- log gần nhất ---")
        print("\n".join(LOG.read_text(encoding="utf-8").splitlines()[-5:]))


def collect():
    src = json.loads(SOURCE.read_text(encoding="utf-8"))
    entries, rejects = [], []
    for p in sorted(OUT.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ok, rej = validate(d["result"], set(d["batch"]["words"]), src["en"])
        for e in ok:
            e["model"] = d["meta"]["model"]
        entries += ok
        rejects += rej
    (WORK / "tierA-ai.json").write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    (WORK / "tierA-rejects.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rejects),
                                             encoding="utf-8")
    print(f"{len(entries)} mục hợp lệ, {sum(len(e['senses']) for e in entries)} nghĩa, {len(rejects)} bị loại")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["prepare", "prepare-gaps", "run", "status", "collect"])
    ap.add_argument("--pass", dest="pass_", choices=["main", "gaps"], default="main")
    ap.add_argument("--top", type=int, default=20000)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--retry-model")
    a = ap.parse_args()
    if a.pass_ == "gaps":
        use_pass("gaps")
    if a.cmd == "prepare":
        prepare(a.top)
    elif a.cmd == "prepare-gaps":
        prepare_gaps()
    elif a.cmd == "run":
        if STOP.exists():
            STOP.unlink()
        Runner(a.workers).run(a.limit, a.retry_model)
    elif a.cmd == "status":
        status()
    else:
        collect()


if __name__ == "__main__":
    main()
