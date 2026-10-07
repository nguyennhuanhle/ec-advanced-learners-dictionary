"""Icon + màn hình khởi động cho app Android (PLAN-android A2) từ logo gốc 1024 px của bản desktop.

  python pipeline/android_icons.py

Ghi vào app/android/app/src/main/res/:
  mipmap-*/ic_launcher.png         icon kiểu cũ (Android 7): nguyên logo (góc đã trong suốt)
  mipmap-*/ic_launcher_round.png   icon tròn kiểu cũ
  mipmap-*/ic_launcher_foreground.png  lớp trước của icon thích ứng (Android 8+): logo 78/108 khung, phần còn lại trong suốt
  values/ic_launcher_background.xml    lớp nền icon thích ứng = màu xanh của logo
  drawable-(port|land)-*/splash.png    màn hình khởi động Android ≤ 11: nền màu đầu trang + logo giữa
Android 12+ dùng SplashScreen của hệ thống: icon app trên nền @color/ecald_splash (styles.xml).
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "src-tauri" / "icons" / "logo-classic-1024.png"
RES = ROOT / "app" / "android" / "app" / "src" / "main" / "res"
DENS = {"mdpi": 1, "hdpi": 1.5, "xhdpi": 2, "xxhdpi": 3, "xxxhdpi": 4}
BG = (11, 91, 211)  # màu giữa dải màu của logo — lộ ra quanh logo khi launcher dùng mặt nạ vuông bo góc
SPLASH_BG = (11, 61, 184)  # #0B3DB8, như @color/ecald_splash


def main():
    logo = Image.open(SRC).convert("RGBA")
    for d, k in DENS.items():
        mip = RES / f"mipmap-{d}"
        mip.mkdir(parents=True, exist_ok=True)
        n = round(48 * k)
        logo.resize((n, n), Image.LANCZOS).save(mip / "ic_launcher.png")
        # tròn: cắt phần giữa logo (bỏ viền) theo hình tròn
        inner = logo.crop((70, 70, 954, 954)).resize((n, n), Image.LANCZOS)
        mask = Image.new("L", (n * 4, n * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, n * 4 - 1, n * 4 - 1), fill=255)
        rnd = Image.new("RGBA", (n, n), (0, 0, 0, 0))
        rnd.paste(inner, (0, 0), mask.resize((n, n), Image.LANCZOS))
        rnd.save(mip / "ic_launcher_round.png")
        # icon thích ứng: khung 108 dp, logo 78 dp ở giữa (mặt nạ tròn 72 dp cắt trong vùng logo, sách nằm gần vùng an toàn 66 dp)
        c = round(108 * k)
        s = round(78 * k)
        fg = Image.new("RGBA", (c, c), (0, 0, 0, 0))
        fg.paste(logo.resize((s, s), Image.LANCZOS), ((c - s) // 2, (c - s) // 2))
        fg.save(mip / "ic_launcher_foreground.png")
    (RES / "values" / "ic_launcher_background.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
        f'    <color name="ic_launcher_background">#{BG[0]:02X}{BG[1]:02X}{BG[2]:02X}</color>\n</resources>\n',
        encoding="utf-8",
    )
    n_splash = 0
    for f in sorted(RES.glob("drawable*/splash.png")):
        w, h = Image.open(f).size
        im = Image.new("RGB", (w, h), SPLASH_BG)
        s = round(min(w, h) * 0.36)
        im.paste(logo.resize((s, s), Image.LANCZOS), ((w - s) // 2, (h - s) // 2), logo.resize((s, s), Image.LANCZOS))
        im.save(f, optimize=True)
        n_splash += 1
    print(f"icon: {len(DENS)} mật độ × 3 loại; splash: {n_splash} file")


if __name__ == "__main__":
    main()
