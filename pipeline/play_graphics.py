"""Hình cho trang Google Play (PLAN-android A4) → _deliverables/play/

  python pipeline/play_graphics.py

  icon-512.png              icon trên Play: 512×512, PNG 32-bit (Play tự bo góc) — nền dải màu của logo + logo gốc
  feature-vi.png / -en.png  ảnh nổi bật 1024×500, PNG 24-bit (không kênh alpha) — logo + tên app + dòng giới thiệu
Ảnh chụp màn hình (1080×1920) chụp từ máy ảo/điện thoại bằng DevTools + adb (xem PLAN-android A4), không do script này tạo.
"""
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / "app" / "src-tauri" / "icons" / "logo-classic-1024.png"
OUT = ROOT / "_deliverables" / "play"
FONT_B = r"C:\Windows\Fonts\segoeuib.ttf"
FONT_R = r"C:\Windows\Fonts\segoeui.ttf"
STOPS = [(0.0, (11, 61, 184)), (0.55, (10, 116, 216)), (1.0, (11, 191, 207))]  # app.css --brand-bg


def grad(w, h):
    """Dải màu chéo như đầu trang của app."""
    im = Image.new("RGB", (w, h))
    px = im.load()
    for x in range(w):
        for y in range(h):
            t = (x / w) * 0.8 + (y / h) * 0.2
            for (a, ca), (b, cb) in zip(STOPS, STOPS[1:]):
                if a <= t <= b:
                    k = (t - a) / (b - a)
                    px[x, y] = tuple(round(ca[i] + (cb[i] - ca[i]) * k) for i in range(3))
                    break
    return im


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logo = Image.open(LOGO).convert("RGBA")

    # icon 512: bỏ viền trắng của logo, phủ kín khung (Play tự bo góc ~20%)
    icon = grad(512, 512).convert("RGBA")
    inner = logo.crop((60, 60, 964, 964)).resize((512, 512), Image.LANCZOS)
    icon.alpha_composite(inner)
    icon.save(OUT / "icon-512.png")

    texts = {
        "vi": ("EC Eng-Vie Dictionary", "Từ điển Anh–Anh · Anh–Việt · Việt–Anh", "Dùng offline · IPA · CEFR · hơn 136.000 từ và cụm từ"),
        "en": ("EC Eng-Vie Dictionary", "English–English · English–Vietnamese · Vietnamese–English", "Works offline · IPA · CEFR levels · 136,000+ words and phrases"),
    }
    for lang, (title, line1, line2) in texts.items():
        im = grad(1024, 500).convert("RGBA")
        s = 330
        im.alpha_composite(logo.resize((s, s), Image.LANCZOS), (56, (500 - s) // 2))
        d = ImageDraw.Draw(im)
        x = 56 + s + 40
        maxw = 1024 - x - 40

        def fit(text, path, size):
            while size > 12:
                f = ImageFont.truetype(path, size)
                if d.textlength(text, font=f) <= maxw:
                    return f
                size -= 1
            return ImageFont.truetype(path, size)

        f1, f2, f3 = fit(title, FONT_B, 56), fit(line1, FONT_R, 30), fit(line2, FONT_R, 26)
        d.text((x, 150), title, font=f1, fill="white")
        d.text((x, 240), line1, font=f2, fill=(235, 245, 255))
        d.text((x, 292), line2, font=f3, fill=(215, 235, 255))
        im.convert("RGB").save(OUT / f"feature-{lang}.png")
    print(f"Đã ghi: {OUT / 'icon-512.png'}, feature-vi.png, feature-en.png")


if __name__ == "__main__":
    main()
