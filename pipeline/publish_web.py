"""Đưa bản web lên repo của site từ điển (vòng W5, UC-WM03): https://dictionary.edtechcorner.com (Netlify, repo ecald-web).

Dùng:
  npm --prefix app run build:web         # giao diện web → app/build-web/
  python pipeline/export_web.py          # dữ liệu web → data/build/web/ (manifest.json + v<phiên bản>-<sha8>/)
  python pipeline/publish_web.py [--site D:/GitHub/ecald-web] [--commit]

Bố cục repo site (thư mục publish của Netlify = gốc repo, không có lệnh build):
  index.html, _app/, favicon.png, logo-*.png    ← app/build-web/
  data/manifest.json                            ← data/build/web/manifest.json
  data/v<phiên bản>-<sha8>/                     ← bản dữ liệu hiện hành + giữ MỘT bản liền trước (tab đang mở không lỗi, UC-W10)
  _headers, robots.txt, .gitattributes, README.md, LICENSE

Quy tắc (use case người bảo trì web):
  - repo site có thay đổi chưa commit → dừng, không ghi đè;
  - chỉ chép các loại file trong danh sách cho phép (không bao giờ có khoá, DB, data/work…);
  - quá 10.000 file hoặc có file > 5 MB → dừng.
Không tự push: --commit chỉ tạo commit; người chạy tự `git push` (Netlify deploy khi nhánh main thay đổi).
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "app" / "build-web"
DATA = ROOT / "data" / "build" / "web"
LICENSE = ROOT / "LICENSE"
SOURCE_REPO = "https://github.com/nguyennhuanhle/ec-advanced-learners-dictionary"

ALLOWED_EXT = {".html", ".js", ".css", ".json", ".txt", ".md", ".png", ".webp", ".ico", ".svg", ".woff2"}
ALLOWED_NAMES = {"_headers", "LICENSE", ".gitattributes", "robots.txt", "README.md"}
MAX_FILES = 10_000
MAX_FILE_BYTES = 5 * 1024 * 1024

# Netlify: header cho mọi trang + lưu đệm lâu cho file có tên/thư mục mang mã băm (bất biến).
# CSP chính nằm trong thẻ meta do SvelteKit sinh (có mã băm script khởi động); header chỉ thêm frame-ancestors —
# đặt script-src ở header sẽ chặn chính script đó. manifest.json / index.html giữ mặc định của Netlify
# (max-age=0, must-revalidate = luôn hỏi lại máy chủ), không khớp quy tắc nào bên dưới.
HEADERS = """/*
  Content-Security-Policy: frame-ancestors 'none'
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  Permissions-Policy: camera=(), microphone=(), geolocation=(), interest-cohort=()

/_app/immutable/*
  Cache-Control: public, max-age=31536000, immutable

/data/:version/*
  Cache-Control: public, max-age=31536000, immutable
"""

ROBOTS = """User-agent: *
Allow: /
Disallow: /data/
"""

# mọi file là nhị phân với git: không đổi xuống dòng → byte trên site đúng như bản xuất (thư mục dữ liệu mang mã băm nội dung)
GITATTRIBUTES = "* -text\n"

README = f"""# EC Advanced Learners' Dictionary — web

Built site for **https://dictionary.edtechcorner.com** (Netlify, no build step: the repository root is published as is).
English–English, English–Vietnamese and Vietnamese–English learner's dictionary that runs entirely in the browser.

This repository only holds generated files. Source code, data pipeline and the Windows app (works offline):
{SOURCE_REPO}

- `index.html`, `_app/` — the web interface (SvelteKit, `npm run build:web`).
- `data/manifest.json` + `data/v<version>-<hash>/` — dictionary data exported by `pipeline/export_web.py`.
- Updated by `pipeline/publish_web.py` in the source repository.

Licence: see `LICENSE`. The dictionary data is CC BY-SA 4.0 (Wiktionary and other open sources; attribution on the site's About page).
"""


def stop(msg):
    print(f"DỪNG: {msg}")
    sys.exit(1)


def git(site, *args):
    return subprocess.run(["git", "-C", str(site), *args], capture_output=True, text=True, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=str(ROOT.parent / "ecald-web"), help="bản sao (clone) của repo site")
    ap.add_argument("--commit", action="store_true", help="tạo commit sau khi chép (không push)")
    a = ap.parse_args()
    site = Path(a.site)

    if not (UI / "index.html").is_file():
        stop(f"chưa có {UI} — chạy `npm --prefix app run build:web`")
    if not (DATA / "manifest.json").is_file():
        stop(f"chưa có {DATA} — chạy `python pipeline/export_web.py`")
    if not (site / ".git").is_dir():
        stop(f"{site} không phải repo git (clone ecald-web về đó trước)")
    dirty = git(site, "status", "--porcelain").stdout.strip()
    if dirty:
        stop("repo site có thay đổi chưa commit, không ghi đè:\n" + dirty)

    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    cur = manifest["base"].strip("/")
    if not (DATA / cur).is_dir():
        stop(f"manifest trỏ tới {cur} nhưng không có thư mục đó")

    # bản dữ liệu đang chạy trên site (manifest cũ) → giữ lại một bản liền trước
    old_manifest = site / "data" / "manifest.json"
    prev = json.loads(old_manifest.read_text(encoding="utf-8"))["base"].strip("/") if old_manifest.is_file() else None
    keep = {cur} | ({prev} if prev and prev != cur else set())

    # dọn mọi thứ do script quản lý (trừ .git và các bản dữ liệu giữ lại), rồi chép mới
    for p in site.iterdir():
        if p.name == ".git":
            continue
        if p.name == "data":
            for q in p.iterdir():
                if q.is_dir() and q.name in keep:
                    continue
                shutil.rmtree(q) if q.is_dir() else q.unlink()
            continue
        shutil.rmtree(p) if p.is_dir() else p.unlink()

    shutil.copytree(UI, site, dirs_exist_ok=True)
    (site / "data").mkdir(exist_ok=True)
    if not (site / "data" / cur).is_dir():
        shutil.copytree(DATA / cur, site / "data" / cur)
    shutil.copy2(DATA / "manifest.json", site / "data" / "manifest.json")
    (site / "_headers").write_text(HEADERS, encoding="utf-8", newline="\n")
    (site / "robots.txt").write_text(ROBOTS, encoding="utf-8", newline="\n")
    (site / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8", newline="\n")
    (site / "README.md").write_text(README, encoding="utf-8", newline="\n")
    shutil.copy2(LICENSE, site / "LICENSE")

    # kiểm sau khi chép
    files = [p for p in site.rglob("*") if p.is_file() and ".git" not in p.relative_to(site).parts[:1]]
    bad = [p.relative_to(site).as_posix() for p in files if p.suffix.lower() not in ALLOWED_EXT and p.name not in ALLOWED_NAMES]
    if bad:
        stop(f"có loại file không cho phép: {bad[:10]}")
    big = [(p.relative_to(site).as_posix(), p.stat().st_size) for p in files if p.stat().st_size > MAX_FILE_BYTES]
    if big:
        stop(f"có file > {MAX_FILE_BYTES:,} B: {big}")
    if len(files) > MAX_FILES:
        stop(f"{len(files)} file > ngưỡng {MAX_FILES}")
    total = sum(p.stat().st_size for p in files)
    print(f"Đã chép vào {site}: {len(files)} file, {total / 2**20:.1f} MiB")
    print(f"  dữ liệu hiện hành: data/{cur}/" + (f"; giữ bản trước: data/{prev}/" if prev and prev != cur else ""))
    print(f"  file lớn nhất: {max(files, key=lambda p: p.stat().st_size).relative_to(site).as_posix()}")

    if a.commit:
        git(site, "add", "-A")
        msg = f"Data {manifest['data_version']} ({cur}), UI from {SOURCE_REPO.rsplit('/', 1)[-1]}"
        r = git(site, "commit", "-q", "-m", msg, "-m", "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
        print(r.stdout.strip() or r.stderr.strip() or f"Đã commit: {msg}")
        print("Tiếp: git -C", site, "push")


if __name__ == "__main__":
    main()
