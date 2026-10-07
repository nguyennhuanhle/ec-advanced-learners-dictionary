"""Dựng app Android (PLAN-android, UC-AM01): giao diện bản Android + dữ liệu web hiện hành → dự án Capacitor → APK/AAB.

Dùng:
  python pipeline/export_web.py                  # (nếu chưa có) dữ liệu web → data/build/web/
  python pipeline/build_android.py --sync-only   # dựng giao diện + chép dữ liệu + `cap sync` (không cần Android SDK)
  python pipeline/build_android.py               # như trên + APK debug (cần Android SDK + JDK 21) → in đường dẫn APK
  python pipeline/build_android.py --release     # AAB đã ký để đưa lên Play (cần app/android/keystore.properties)
  python pipeline/build_android.py --release --bump   # tăng versionCode trước khi dựng

Quy tắc (use case người bảo trì Android):
  - origin của WebView (hostname "localhost", androidScheme "https") không được đổi — IndexedDB của người dùng gắn với nó;
  - bản release: versionCode phải lớn hơn bản release trước (version.properties); thiếu keystore thì dừng;
  - dữ liệu chép vào build-android/data/ (đã .gitignore) — không bao giờ vào repo công khai (UC-M08);
  - AAB > 190 MB thì dừng (Play: phần cài đặt chính ≤ 200 MB nén).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
UI = APP / "build-android"
ANDROID = APP / "android"
DATA = ROOT / "data" / "build" / "web"
CAP_CONFIG = APP / "capacitor.config.ts"
VERSION = ANDROID / "version.properties"
KEYSTORE_PROPS = ANDROID / "keystore.properties"
MAX_AAB = 190 * 1024 * 1024
NPM = "npm.cmd" if os.name == "nt" else "npm"
NPX = "npx.cmd" if os.name == "nt" else "npx"


def stop(msg):
    print(f"DỪNG: {msg}")
    sys.exit(1)


def run(cmd, cwd, env=None):
    print("  $", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env)
    if r.returncode != 0:
        stop(f"lệnh lỗi (mã {r.returncode}): {' '.join(str(c) for c in cmd)}")


def read_props(p):
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def write_prop(p, key, value):
    s = p.read_text(encoding="utf-8")
    s2, n = re.subn(rf"(?m)^{re.escape(key)}=.*$", f"{key}={value}", s)
    if n != 1:
        stop(f"{p.name} không có đúng một dòng {key}=")
    p.write_text(s2, encoding="utf-8")


def check_origin():
    s = CAP_CONFIG.read_text(encoding="utf-8")
    if not re.search(r'hostname:\s*"localhost"', s) or not re.search(r'androidScheme:\s*"https"', s):
        stop("capacitor.config.ts đã đổi hostname/androidScheme — người dùng sẽ mất lịch sử và danh sách (PLAN-android mục 6). Trả lại "
             'hostname: "localhost", androidScheme: "https".')


def find_sdk():
    for k in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(k) and Path(os.environ[k]).is_dir():
            return Path(os.environ[k])
    p = Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk"
    return p if p.is_dir() else None


# Gradle 8.14.3 (Capacitor 8) chạy trên Java 21–24; Java 25 (JDK đi kèm Android Studio mới) báo
# "Unsupported class file major version 69" (đã gặp 2026-10-07).
JDK_MIN, JDK_MAX = 21, 24


def jdk_version(home):
    rel = home / "release"
    if not ((home / "bin" / "java.exe").is_file() or (home / "bin" / "java").is_file()) or not rel.is_file():
        return None
    m = re.search(r'JAVA_VERSION="(\d+)', rel.read_text(encoding="utf-8", errors="replace"))
    return int(m.group(1)) if m else None


def find_jdk():
    """JDK cho Gradle: JAVA_HOME, JDK Android Studio tải về (~/.jdks), JDK đi kèm Android Studio (jbr), Temurin trong Program Files."""
    cands = []
    if os.environ.get("JAVA_HOME"):
        cands.append(Path(os.environ["JAVA_HOME"]))
    cands += sorted((Path.home() / ".jdks").glob("*"), reverse=True)
    cands += [Path(r"C:\Program Files\Android\Android Studio\jbr"), Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Android Studio" / "jbr"]
    cands += sorted(Path(r"C:\Program Files\Eclipse Adoptium").glob("jdk-*"), reverse=True)
    seen = []
    for c in cands:
        v = jdk_version(c)
        if v is not None:
            seen.append(f"{c} (Java {v})")
            if JDK_MIN <= v <= JDK_MAX:
                return c
    if seen:
        print("  JDK tìm thấy nhưng không hợp (cần Java 21–24): " + "; ".join(seen))
    return None


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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sync-only", action="store_true", help="không chạy Gradle (chưa cần Android SDK)")
    ap.add_argument("--release", action="store_true", help="dựng AAB đã ký cho Play")
    ap.add_argument("--bump", action="store_true", help="tăng versionCode trước khi dựng")
    a = ap.parse_args()

    if not (DATA / "manifest.json").is_file():
        stop(f"chưa có {DATA} — chạy `python pipeline/export_web.py`")
    if not (ANDROID / "app").is_dir():
        stop("chưa có app/android — chạy `npx cap add android` trong app/")
    check_origin()

    ver = read_props(VERSION)
    if a.bump:
        write_prop(VERSION, "versionCode", int(ver["versionCode"]) + 1)
        ver = read_props(VERSION)
    code, last = int(ver["versionCode"]), int(ver["lastReleasedVersionCode"])
    if a.release:
        if code <= last:
            stop(f"versionCode {code} không lớn hơn bản release trước ({last}) — thêm --bump")
        if not KEYSTORE_PROPS.is_file():
            stop("thiếu app/android/keystore.properties (khoá upload) — xem hướng dẫn tạo khoá trong PLAN-android")
    print(f"App {ver['versionName']} (versionCode {code})")

    print("1/3 Dựng giao diện bản Android")
    run([NPM, "run", "build:android"], APP)
    index = UI / "index.html"
    with open(index, encoding="utf-8", newline="") as f:  # giữ nguyên xuống dòng (script nội tuyến có mã băm CSP)
        html = f.read()
    if "googletagmanager" in html:
        stop("bản Android có Google Analytics trong CSP/HTML — sai đích build")
    # tràn viền (PLAN-android mục 8): WebView ≥ 140 chỉ vẽ dưới thanh hệ thống khi trang khai viewport-fit=cover;
    # CSS dùng chung đã đệm bằng env(safe-area-inset-*). Chỉ bản Android — app.html dùng chung với web/desktop.
    vp = 'content="width=device-width, initial-scale=1"'
    if html.count(vp) != 1:
        stop("index.html không có đúng một thẻ viewport như app.html")
    with open(index, "w", encoding="utf-8", newline="") as f:
        f.write(html.replace(vp, 'content="width=device-width, initial-scale=1, viewport-fit=cover"'))
    print("2/3 Chép dữ liệu + cap sync")
    copy_data()
    run([NPX, "cap", "sync", "android"], APP)
    if a.sync_only:
        print("Xong (--sync-only). Mở bằng Android Studio: app/android")
        return

    sdk, jdk = find_sdk(), find_jdk()
    if not sdk:
        stop("không thấy Android SDK (ANDROID_HOME hoặc %LOCALAPPDATA%\\Android\\Sdk) — cài Android Studio trước")
    if not jdk:
        stop("không thấy JDK 21–24 — trong Android Studio: Settings › Build Tools › Gradle › Gradle JDK › Download JDK… (bản 21)")
    local = ANDROID / "local.properties"  # đã .gitignore
    if not local.is_file():
        local.write_text(f"sdk.dir={sdk.as_posix()}\n", encoding="utf-8")
    env = dict(os.environ, JAVA_HOME=str(jdk), ANDROID_HOME=str(sdk))
    gradlew = ANDROID / ("gradlew.bat" if os.name == "nt" else "gradlew")

    print("3/3 Gradle")
    if a.release:
        run([gradlew, "bundleRelease"], ANDROID, env)
        out = ANDROID / "app" / "build" / "outputs" / "bundle" / "release" / "app-release.aab"
        size = out.stat().st_size
        print(f"AAB: {out}  ({size / 2**20:.1f} MiB)")
        if size > MAX_AAB:
            stop(f"AAB {size / 2**20:.1f} MiB > {MAX_AAB / 2**20:.0f} MiB — phải chuyển dữ liệu sang asset pack")
        write_prop(VERSION, "lastReleasedVersionCode", code)
        print("Đã ghi lastReleasedVersionCode — nhớ commit app/android/version.properties")
    else:
        run([gradlew, "assembleDebug"], ANDROID, env)
        out = ANDROID / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
        print(f"APK debug: {out}  ({out.stat().st_size / 2**20:.1f} MiB)")


if __name__ == "__main__":
    main()
