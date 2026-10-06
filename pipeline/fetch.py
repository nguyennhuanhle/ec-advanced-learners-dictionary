"""Tải các nguồn trong sources.toml về data/raw và ghi sha256 vào sources.lock (UC-M01).

Dùng: python pipeline/fetch.py [tên_nguồn ...]   (bỏ trống = tất cả)
Nguồn đã có trong sources.lock và file khớp sha256 thì bỏ qua. Lỗi ở một nguồn không làm hỏng bản đã tải trước.
"""
import hashlib
import json
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
LOCK = ROOT / "pipeline" / "sources.lock"


def load_sources():
    with open(ROOT / "pipeline" / "sources.toml", "rb") as f:
        sources = tomllib.load(f)["sources"]
    for key, s in sources.items():
        if not s.get("license"):
            raise SystemExit(f"Nguồn {key} thiếu trường license, không được dùng.")
    return sources


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    part = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": "tu-dien-AAV-pipeline/0.1"})
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as out:
        total = int(r.headers.get("Content-Length") or 0)
        done, last = 0, time.time()
        while chunk := r.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if time.time() - last > 10:
                pct = f"{done * 100 // total}%" if total else f"{done >> 20} MB"
                print(f"  ... {dest.name}: {pct}", flush=True)
                last = time.time()
    if total and part.stat().st_size != total:
        part.unlink()
        raise IOError(f"tải thiếu: {done} / {total} byte")
    part.replace(dest)


def main():
    sources = load_sources()
    wanted = sys.argv[1:] or list(sources)
    unknown = [w for w in wanted if w not in sources]
    if unknown:
        raise SystemExit(f"Nguồn không có trong allowlist: {unknown}")
    lock = json.loads(LOCK.read_text(encoding="utf-8")) if LOCK.exists() else {}
    RAW.mkdir(parents=True, exist_ok=True)
    failed = []
    for key in wanted:
        s = sources[key]
        dest = RAW / s["file"]
        if dest.exists() and lock.get(key, {}).get("sha256") == sha256(dest):
            print(f"[bỏ qua] {key}: đã có, khớp sha256")
            continue
        print(f"[tải] {key} <- {s['url']}", flush=True)
        try:
            download(s["url"], dest)
        except Exception as e:  # giữ bản cũ, báo lỗi, tải tiếp nguồn khác
            print(f"[LỖI] {key}: {e}")
            failed.append(key)
            continue
        lock[key] = {
            "url": s["url"],
            "file": s["file"],
            "bytes": dest.stat().st_size,
            "sha256": sha256(dest),
            "retrieved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "license": s["license"],
        }
        LOCK.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[xong] {key}: {lock[key]['bytes'] >> 20} MB")
    if failed:
        raise SystemExit(f"Lỗi ở: {failed}")


if __name__ == "__main__":
    main()
