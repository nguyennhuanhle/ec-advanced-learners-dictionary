"""Icon + màn hình khởi động cho app iOS (PLAN-ios I2) từ logo gốc 1024 px của bản desktop (như android_icons.py).

  .venv/bin/python pipeline/ios_icons.py

Ghi vào app/ios/App/App/Assets.xcassets/:
  AppIcon.appiconset/AppIcon-512@2x.png   1024×1024, KHÔNG có kênh trong suốt (App Store từ chối icon có alpha);
                                          góc trong suốt của logo lấp bằng màu xanh của logo, iOS tự bo góc
  Splash.imageset/splash-2732x2732*.png    nền màu đầu trang + logo giữa (cùng màu màn hình khởi động Android)
"""
import sys
from pathlib import Path

from PIL import Image

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "src-tauri" / "icons" / "logo-classic-1024.png"
ASSETS = ROOT / "app" / "ios" / "App" / "App" / "Assets.xcassets"
BG = (11, 91, 211)  # như android_icons.BG
SPLASH_BG = (11, 61, 184)  # #0B3DB8, như android_icons.SPLASH_BG
SPLASH = 2732
SPLASH_LOGO = 400  # logo nhỏ ở giữa; màn hình khởi động co ảnh theo kiểu "aspect fill"


def main():
    logo = Image.open(SRC).convert("RGBA")
    icon = Image.new("RGBA", logo.size, BG + (255,))
    icon.alpha_composite(logo)
    out = ASSETS / "AppIcon.appiconset" / "AppIcon-512@2x.png"
    icon.convert("RGB").resize((1024, 1024), Image.LANCZOS).save(out, optimize=True)
    print(f"  {out.relative_to(ROOT)}")

    splash = Image.new("RGBA", (SPLASH, SPLASH), SPLASH_BG + (255,))
    small = logo.resize((SPLASH_LOGO, SPLASH_LOGO), Image.LANCZOS)
    splash.alpha_composite(small, ((SPLASH - SPLASH_LOGO) // 2, (SPLASH - SPLASH_LOGO) // 2))
    for name in ("splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"):
        p = ASSETS / "Splash.imageset" / name
        splash.convert("RGB").save(p, optimize=True)
        print(f"  {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
