"""Cầu nối chỉ dùng khi phát triển: cho giao diện chạy trong trình duyệt thường gọi được lõi Rust.

Mỗi yêu cầu POST /call {"cmd": ..., "args": {...}} được chuyển thành `app.exe --call <cmd> <json>`
(chế độ dòng lệnh của app, dùng cùng bộ điều phối với cửa sổ Tauri) và trả về JSON. App thật (cửa sổ Tauri) không dùng file này. Chỉ nghe ở 127.0.0.1.

Dùng: python app/dev-bridge.py   (cổng 1430)
"""
import json
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EXE = Path(__file__).resolve().parent / "src-tauri" / "target" / "debug" / "app.exe"


class H(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "http://localhost:1420")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path.strip("/") != "call" or not body.get("cmd"):
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        args = json.dumps(body.get("args") or {}, ensure_ascii=False)
        out = subprocess.run([str(EXE), "--call", body["cmd"], args], capture_output=True).stdout or b"null"
        self.send_response(200)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 1430), H).serve_forever()
