"""Chuẩn bị logo app từ ảnh gốc của người dùng.

- Cắt bỏ nền trắng quanh khối vuông bo góc, làm trong suốt phần ngoài góc bo.
- Bản "classic" giữ màu gốc (xanh dương → xanh ngọc); bản "rose" đổi màu các mảng xanh sang hồng → tím,
  giữ nguyên trang sách trắng (độ bão hoà thấp) để chữ A·V vẫn rõ.

Dùng: python pipeline/make_logo.py "<ảnh gốc>.png"
  → app/src-tauri/icons/logo-classic-1024.png, logo-rose-1024.png (nguồn cho `npx tauri icon`)
  → app/static/logo-classic.png, logo-rose.png (256 px, cho thanh trên cùng)
"""
import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
ICONS = ROOT / "app" / "src-tauri" / "icons"
STATIC = ROOT / "app" / "static"


def crop_rounded(img):
    rgb = np.asarray(img.convert("RGB")).astype(int)
    # nền: gần trắng và gần xám (bóng đổ rất nhạt) → bỏ
    not_bg = (rgb.min(axis=2) < 235)
    ys, xs = np.where(not_bg)
    top, bottom, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    side = max(bottom - top, right - left) + 1
    cy, cx = (top + bottom) // 2, (left + right) // 2
    box = (cx - side // 2, cy - side // 2, cx - side // 2 + side, cy - side // 2 + side)
    sq = img.convert("RGBA").crop(box)
    # mặt nạ bo góc (bán kính ~22% cạnh, khớp hình gốc), khử răng cưa bằng vẽ to rồi thu nhỏ
    big = 4
    mask = Image.new("L", (side * big, side * big), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, side * big - 1, side * big - 1), radius=int(side * big * 0.22), fill=255)
    mask = mask.resize((side, side), Image.LANCZOS)
    sq.putalpha(mask)
    return sq


def to_rose(img):
    """Đổi sắc: xanh dương (~220°) → hồng (~330°), xanh ngọc (~180°) → tím (~285°), xanh lá → tím xanh."""
    arr = np.asarray(img).astype(float) / 255.0
    rgb, alpha = arr[..., :3], arr[..., 3:]
    out = np.empty_like(rgb)
    h_, w_ = rgb.shape[:2]
    flat = rgb.reshape(-1, 3)
    res = np.empty_like(flat)
    for i, (r, g, b) in enumerate(flat):
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        if s > 0.18:  # chỉ đổi các mảng có màu; trang sách trắng / xám giữ nguyên
            deg = h * 360
            if deg >= 200 and v < 0.62:   # chữ A·V và bóng xanh đậm → tím đậm (dễ đọc trên trang trắng)
                nd = 284
            elif deg >= 200:              # xanh dương → hồng
                nd = 324 + (deg - 220) * 0.5
            elif deg >= 150:              # xanh ngọc → tím
                nd = 266 + (deg - 180) * 1.2
            else:                         # xanh lá (tab) → tím chàm
                nd = 252
            h = (nd % 360) / 360
            s = min(1.0, s * 0.95)
        res[i] = colorsys.hsv_to_rgb(h, s, v)
    out = res.reshape(h_, w_, 3)
    return Image.fromarray((np.concatenate([out, alpha], axis=2) * 255).astype("uint8"), "RGBA")


def main():
    src = Path(sys.argv[1])
    img = crop_rounded(Image.open(src))
    classic = img.resize((1024, 1024), Image.LANCZOS)
    # bản hồng tím tính trên ảnh 512 rồi phóng lại cho nhanh (vòng lặp Python theo điểm ảnh)
    rose = to_rose(img.resize((512, 512), Image.LANCZOS)).resize((1024, 1024), Image.LANCZOS)
    rose = rose.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    ICONS.mkdir(parents=True, exist_ok=True)
    classic.save(ICONS / "logo-classic-1024.png")
    rose.save(ICONS / "logo-rose-1024.png")
    for name, im in (("classic", classic), ("rose", rose)):
        im.resize((256, 256), Image.LANCZOS).save(STATIC / f"logo-{name}.png", optimize=True)
    classic.resize((64, 64), Image.LANCZOS).save(STATIC / "favicon.png")
    print("ok")


if __name__ == "__main__":
    main()
