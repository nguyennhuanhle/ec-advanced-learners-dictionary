"""Đóng gói dữ liệu thành .tdpack (UC-M07), chỉ khi qua cổng chất lượng (PLAN mục 6).

Dùng: python pipeline/pack.py   → data/build/dict-core-<phiên bản>.tdpack
     python pipeline/pack.py --license-txt   → app/src-tauri/LICENSE.txt (trang giấy phép của bộ cài)
.tdpack = zip gồm dict-core.sqlite, manifest.json (phiên bản, schema, app tối thiểu, sha256), LICENSES.md.
Không có cờ bỏ qua cổng: thiếu ngưỡng thì dừng (quy tắc CANNOT của người bảo trì).
"""
import hashlib
import json
import sqlite3
import sys
import tomllib
import zipfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "data" / "build"
DB = BUILD / "dict-core.sqlite"

GATE = {  # top 20.000 từ, phần trăm tối thiểu
    "has_entry": 98, "has_definition": 98, "has_ipa": 95, "has_example": 90, "has_vi_any": 85,
}


def licenses_md():
    with open(ROOT / "pipeline" / "sources.toml", "rb") as f:
        sources = tomllib.load(f)["sources"]
    lock = json.loads((ROOT / "pipeline" / "sources.lock").read_text(encoding="utf-8"))
    lines = ["# Nguồn dữ liệu và giấy phép", "",
             "Gói dữ liệu này phát hành theo CC BY-SA 4.0 (do phần lớn dữ liệu nguồn dùng giấy phép này).",
             "Nội dung gắn nhãn AI do Gemini biên soạn lại từ Wiktionary.", "",
             "| Nguồn | Giấy phép | Ghi công | Tải ngày | sha256 |", "|---|---|---|---|---|"]
    for sid, s in sources.items():
        if not s.get("license"):
            raise SystemExit(f"Nguồn {sid} thiếu giấy phép → không đóng gói.")
        lk = lock.get(sid, {})
        lines.append(f"| {s['name']} | {s['license']} | {s.get('attribution', '')} | "
                     f"{lk.get('retrieved_at', '')[:10]} | `{lk.get('sha256', '')[:12]}` |")
    return "\n".join(lines) + "\n"


def license_txt():
    """Văn bản giấy phép cho trang giấy phép của bộ cài (UTF-8 có BOM để NSIS hiện đúng tiếng Việt)."""
    with open(ROOT / "pipeline" / "sources.toml", "rb") as f:
        sources = tomllib.load(f)["sources"]
    lines = [
        "EC ADVANCED LEARNERS' DICTIONARY (internal use / bản dùng nội bộ)",
        "English–English · English–Vietnamese · Vietnamese–English",
        "",
        "Ứng dụng chạy hoàn toàn offline, không gửi dữ liệu ra Internet.",
        "",
        "TÁC GIẢ / AUTHOR",
        "Lê Nguyễn Như Anh (Le Nguyen Nhu Anh), Edtech Corner (founder) — ý tưởng, định hướng biên soạn, thiết kế.",
        "Liên hệ / Contact: https://edtechcorner.com/contact",
        "",
        "GIẤY PHÉP ỨNG DỤNG (MIỄN PHÍ) / APP LICENCE (FREE)",
        "© 2026 Lê Nguyễn Như Anh, Edtech Corner. Ứng dụng được cung cấp miễn phí.",
        "- Được cài đặt và sử dụng miễn phí để tự học, giảng dạy và dùng trong tổ chức.",
        "- Được chia sẻ miễn phí bản cài đặt nguyên vẹn cho người khác.",
        "- Không được bán hay thu phí, gỡ phần ghi công/thông báo bản quyền, hay phát hành bản sửa đổi khi chưa có sự đồng ý của tác giả.",
        "- Cung cấp \"nguyên trạng\", không kèm bảo đảm; tác giả không chịu trách nhiệm về thiệt hại phát sinh khi sử dụng hay do sai sót nội dung.",
        "- Tên và logo thuộc về Edtech Corner.",
        "Free of charge: you may install, use and share the unmodified installer free of charge; you may not sell it,",
        "remove credits or distribute modified versions without permission. Provided \"as is\", without warranty.",
        "Giấy phép ứng dụng không hạn chế quyền của bạn theo giấy phép dữ liệu dưới đây.",
        "",
        "DỮ LIỆU TỪ ĐIỂN",
        "Gói dữ liệu phát hành theo giấy phép Creative Commons Attribution-ShareAlike 4.0 (CC BY-SA 4.0),",
        "vì phần lớn dữ liệu nguồn dùng giấy phép này: https://creativecommons.org/licenses/by-sa/4.0/",
        "Không chứa nội dung của Oxford, Cambridge, Longman, Collins, Merriam-Webster hay English Vocabulary Profile.",
        "Nội dung gắn nhãn AI do Gemini biên soạn lại từ Wiktionary.",
        "",
        "NGUỒN VÀ GHI CÔNG",
    ]
    for s in sources.values():
        lines.append(f"- {s['name']}")
        lines.append(f"  Giấy phép: {s['license']}")
        if s.get("attribution"):
            lines.append(f"  Ghi công: {s['attribution']}")
    lines += ["", "Bấm \"Tôi đồng ý\" để tiếp tục cài đặt."]
    return "\n".join(lines) + "\n"


def main():
    if "--license-txt" in sys.argv:
        out = ROOT / "app" / "src-tauri" / "LICENSE.txt"
        out.write_text(license_txt(), encoding="utf-8-sig", newline="\r\n")
        print(f"Đã ghi {out}")
        return
    report = json.loads((BUILD / "report.json").read_text(encoding="utf-8"))
    top = report["top20k"]
    fails = [f"{k}: {top.get(k)}% < {v}%" for k, v in GATE.items() if top.get(k, 0) < v]
    print("Cổng chất lượng (top 20.000):")
    for k, v in GATE.items():
        print(f"  {'ĐẠT ' if top.get(k, 0) >= v else 'TRƯỢT'} {k}: {top.get(k)}% (ngưỡng {v}%)")
    if fails:
        raise SystemExit("Không đóng gói: " + "; ".join(fails))
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    meta = dict(con.execute("SELECT key, value FROM meta"))
    con.close()
    sha = hashlib.sha256(DB.read_bytes()).hexdigest()
    manifest = {"kind": "dict-core", "data_version": meta["data_version"], "schema_version": meta["schema_version"],
                "min_app_version": meta["min_app_version"], "sha256": sha, "bytes": DB.stat().st_size}
    out = BUILD / f"dict-core-{meta['data_version']}.tdpack"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(DB, "dict-core.sqlite")
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        z.writestr("LICENSES.md", licenses_md())
    print(f"Đã đóng gói {out} ({out.stat().st_size >> 20} MB)")


if __name__ == "__main__":
    main()
