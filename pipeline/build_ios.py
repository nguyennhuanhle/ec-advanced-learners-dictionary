"""Dựng app iOS (PLAN-ios, UC-IM01): giao diện bản iOS + dữ liệu web hiện hành → dự án Capacitor iOS → bản chạy Simulator.
Chỉ chạy trên Mac có Xcode.

Dùng:
  python3 pipeline/build_ios.py --sync-only   # dựng giao diện + chép dữ liệu + `cap sync ios` (mở Xcode: app/ios/App/App.xcodeproj)
  python3 pipeline/build_ios.py               # như trên + build cho iOS Simulator → in đường dẫn .app và kích thước
  python3 pipeline/build_ios.py --bump        # tăng số build (CURRENT_PROJECT_VERSION) trước khi dựng
  (bản ký để tải lên App Store Connect: vòng I4, chưa làm)

Quy tắc (như build_android.py):
  - origin của WebView (hostname "localhost", iosScheme "capacitor") không được đổi — IndexedDB của người dùng gắn với nó;
  - dữ liệu chép vào app/build-ios/data/ (đã .gitignore) rồi `cap sync` chép sang app/ios/App/App/public/ (đã .gitignore) —
    không bao giờ vào repo công khai (UC-M08);
  - bản iOS không được có Google Analytics hay nguồn ngoài.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
UI = APP / "build-ios"
IOS = APP / "ios" / "App"
PBXPROJ = IOS / "App.xcodeproj" / "project.pbxproj"
DATA = ROOT / "data" / "build" / "web"
CAP_CONFIG = APP / "capacitor.config.ts"
DERIVED = APP / "ios" / "DerivedData"  # đã .gitignore (app/ios/.gitignore)


def stop(msg):
    print(f"DỪNG: {msg}")
    sys.exit(1)


def run(cmd, cwd, env=None):
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        stop(f"lệnh lỗi (mã {r.returncode}): {' '.join(str(c) for c in cmd)}")


def check_origin():
    s = CAP_CONFIG.read_text(encoding="utf-8")
    if not re.search(r'hostname:\s*"localhost"', s) or not re.search(r'iosScheme:\s*"capacitor"', s):
        stop('capacitor.config.ts đã đổi hostname/iosScheme — người dùng iOS sẽ mất lịch sử và danh sách (PLAN-ios mục 6). Trả lại '
             'hostname: "localhost", iosScheme: "capacitor".')


def versions():
    s = PBXPROJ.read_text(encoding="utf-8")
    mv = set(re.findall(r"MARKETING_VERSION = ([^;]+);", s))
    bn = set(re.findall(r"CURRENT_PROJECT_VERSION = ([^;]+);", s))
    if len(mv) != 1 or len(bn) != 1:
        stop(f"project.pbxproj có nhiều MARKETING_VERSION/CURRENT_PROJECT_VERSION khác nhau: {mv} {bn}")
    return mv.pop(), int(bn.pop())


def set_build(n):
    s = PBXPROJ.read_text(encoding="utf-8")
    PBXPROJ.write_text(re.sub(r"CURRENT_PROJECT_VERSION = [^;]+;", f"CURRENT_PROJECT_VERSION = {n};", s), encoding="utf-8")


def copy_data():
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    cur = manifest["base"].strip("/")  # "v/v<phiên bản>-<sha8>"
    if not (DATA / cur).is_dir():
        stop(f"manifest trỏ tới {cur} nhưng không có thư mục đó")
    dst = UI / "data"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(DATA / cur, dst / cur)
    shutil.copy2(DATA / "manifest.json", dst / "manifest.json")
    n = sum(1 for p in dst.rglob("*") if p.is_file())
    size = sum(p.stat().st_size for p in dst.rglob("*") if p.is_file())
    print(f"  dữ liệu {manifest['data_version']} ({cur}): {n} file, {size / 2**20:.1f} MiB (chưa nén)")
    return manifest


def dir_size(p):
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync-only", action="store_true", help="không chạy xcodebuild")
    ap.add_argument("--bump", action="store_true", help="tăng số build trước khi dựng")
    a = ap.parse_args()

    if sys.platform != "darwin":
        stop("bản iOS chỉ dựng được trên Mac")
    if not (DATA / "manifest.json").is_file():
        stop(f"chưa có {DATA} — chạy `python pipeline/export_web.py` (hoặc kéo data/build/web từ máy Windows)")
    if not PBXPROJ.is_file():
        stop("chưa có app/ios — chạy `CAP_WEBDIR=build-ios npx cap add ios` trong app/")
    check_origin()

    name, build = versions()
    if a.bump:
        build += 1
        set_build(build)
    print(f"App iOS {name} (build {build})")

    print("1/3 Dựng giao diện bản iOS")
    run(["npm", "run", "build:ios"], APP)
    index = UI / "index.html"
    with open(index, encoding="utf-8", newline="") as f:  # giữ nguyên xuống dòng (script nội tuyến có mã băm CSP)
        html = f.read()
    if "googletagmanager" in html:
        stop("bản iOS có Google Analytics trong CSP/HTML — sai đích build")
    # tràn viền dưới tai thỏ/thanh Home: CSS dùng chung đã đệm bằng env(safe-area-inset-*), chỉ có hiệu lực khi viewport-fit=cover.
    vp = 'content="width=device-width, initial-scale=1"'
    if html.count(vp) != 1:
        stop("index.html không có đúng một thẻ viewport như app.html")
    with open(index, "w", encoding="utf-8", newline="") as f:
        f.write(html.replace(vp, 'content="width=device-width, initial-scale=1, viewport-fit=cover"'))

    print("2/3 Chép dữ liệu + cap sync ios")
    copy_data()
    run(["npx", "cap", "sync", "ios"], APP, env={**os.environ, "CAP_WEBDIR": "build-ios"})
    public = IOS / "App" / "public"
    if not (public / "data" / "manifest.json").is_file():
        stop("cap sync không chép dữ liệu vào app/ios/App/App/public/data — kiểm CAP_WEBDIR")
    if a.sync_only:
        print("Xong (--sync-only). Mở bằng Xcode: open app/ios/App/App.xcodeproj")
        return

    print("3/3 xcodebuild (iOS Simulator)")
    run(["xcodebuild", "-project", "App.xcodeproj", "-scheme", "App", "-configuration", "Debug",
         "-sdk", "iphonesimulator", "-destination", "generic/platform=iOS Simulator",
         "-derivedDataPath", DERIVED, "-quiet", "build"], IOS)
    out = DERIVED / "Build" / "Products" / "Debug-iphonesimulator" / "App.app"
    print(f"App Simulator: {out}  ({dir_size(out) / 2**20:.1f} MiB trên đĩa)")


if __name__ == "__main__":
    main()
