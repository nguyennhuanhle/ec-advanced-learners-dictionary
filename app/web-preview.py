"""Xem thử bản web trên máy (PLAN-web vòng W2): phục vụ app/build-web/ ở gốc "/" và data/build/web/ ở "/data/",
đúng bố cục của site dictionary.edtechcorner.com (repo ecald-web: index.html + _app/ + data/manifest.json + data/v<ver>/).

Dùng:  npm --prefix app run build:web      (dựng giao diện web → app/build-web/)
       python pipeline/export_web.py         (nếu chưa có data/build/web/)
       python app/web-preview.py [--port 4173]  → mở http://127.0.0.1:4173/

Chỉ nghe ở 127.0.0.1. Header giống kế hoạch _headers của Netlify (PLAN-web mục 6): manifest.json và index.html no-cache,
dữ liệu có phiên bản và _app/immutable/ lưu đệm lâu. CSP nằm trong thẻ meta của index.html (SvelteKit, chế độ hash).
"""
import argparse
import posixpath
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
SITE = HERE / "build-web"
DATA = HERE.parent / "data" / "build" / "web"

# Windows lấy kiểu MIME từ registry (có máy ghi .js là text/plain) → Worker dạng module bị chặn. Đặt cố định.
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8",
    ".png": "image/png", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".webp": "image/webp", ".woff2": "font/woff2",
}


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        p = posixpath.normpath(unquote(urlsplit(path).path))
        parts = [x for x in p.split("/") if x and x not in (".", "..")]
        if parts[:1] == ["data"]:
            return str(DATA.joinpath(*parts[1:]))
        target = SITE.joinpath(*parts)
        # định tuyến bằng "#": mọi đường dẫn không phải file → index.html (như fallback của adapter-static)
        return str(target if target.exists() else SITE / "index.html")

    def guess_type(self, path):
        return TYPES.get(Path(path).suffix.lower(), "application/octet-stream")

    def end_headers(self):
        p = urlsplit(self.path).path
        if p.endswith("manifest.json") or p in ("/", "/index.html"):
            self.send_header("Cache-Control", "no-cache")
        elif p.startswith("/data/v") or p.startswith("/_app/immutable/"):
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} {fmt % args}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)  # bảng mã cp1252 của console không in được tiếng Việt
    ap = argparse.ArgumentParser(description="Xem thử bản web: build-web/ + data/build/web/")
    ap.add_argument("--port", type=int, default=4173)
    a = ap.parse_args()
    if not (SITE / "index.html").is_file():
        raise SystemExit(f"Chưa có {SITE} — chạy: npm --prefix app run build:web")
    if not (DATA / "manifest.json").is_file():
        raise SystemExit(f"Chưa có {DATA / 'manifest.json'} — chạy: python pipeline/export_web.py")
    print(f"Bản web: http://127.0.0.1:{a.port}/   (giao diện {SITE}, dữ liệu {DATA} ở /data/)")
    ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
