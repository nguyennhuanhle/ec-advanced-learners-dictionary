"""Chuẩn hoá phiên âm ECDICT (cột `phonetic`) sang IPA — dùng khi Wiktionary không có phiên âm (build_db.py).

ECDICT ghi phiên âm kiểu Anh cũ, một phần còn mã hoá theo font phiên âm cũ (đối chiếu với Wiktionary trên ~40.000 từ có cả hai,
2026-10-07 — người dùng báo "verbally" hiện /'v\\\\\\\\:bәli/):
  '  ˊ → ˈ        ,  . (giữa/đầu chuỗi) → ˌ        :  → ː
  ә (Kirin U+04D9) → ə      є (Kirin) / ε (Hy Lạp) → ɛ      \\\\ (chuỗi gạch chéo ngược) → ɜ      ^ → ɡ      g → ɡ
  j: trước nguyên âm là /j/ (few 'fju:'), còn lại là ʊ (browbeat 'brajbi:t → ˈbraʊbiːt, stood 'stjd → stʊd)
  əː → ɜː, ɒː → ɔː (ký hiệu Anh cũ)
Nhiều cách đọc ("minute 'minit. mai'nju:t", "...; -ʒən", "trans'kʌltʃәrәl,trænz-") → chỉ giữ cách đầu.
Chuỗi còn ký tự lạ sau khi đổi (?, @, й, chữ Latin không thuộc IPA tiếng Anh…) → bỏ (trả None): thà không có phiên âm còn hơn sai.
"""
import re

VOWELS = set("aeiouæɑɒɔəɛɜɪʊʌɚɝɐɵ")
# ký tự được phép trong kết quả (IPA cho tiếng Anh + dấu nhấn, trường âm, ngoặc âm tuỳ chọn, khoảng trắng, gạch nối)
ALLOWED = set("abdefhijklmnprstuvwxzæɑɒɔəɛɜɪʊʌŋθðʃʒɡɚɝɐɵˈˌː()- ")

_SUBS = [
    ("ә", "ə"), ("є", "ɛ"), ("ε", "ɛ"), ("ˊ", "ˈ"), ("'", "ˈ"), (":", "ː"), ("^", "ɡ"), ("g", "ɡ"),
    (" ", " "), ("[", ""), ("]", ""), ("ʤ", "dʒ"), ("ʧ", "tʃ"),
]


def _first_variant(s: str) -> str:
    # các cách đọc khác nhau: "; " "；" "，" ". " (chấm + cách)
    s = re.split(r"\s*[;；，]\s*|\.\s+", s, maxsplit=1)[0]
    # ",trænz-,trɑ:n-" (phần thay thế có gạch nối sau dấu phẩy) → cắt ở dấu phẩy đó
    m = re.search(r",[^,]*-", s)
    if m and "-" not in s[: m.start()]:
        s = s[: m.start()]
    return s.strip()


def ecdict_to_ipa(raw: str | None) -> str | None:
    if not raw:
        return None
    s = _first_variant(raw.strip().strip("/").strip())
    if not s:
        return None
    s = re.sub(r"\\+", "ɜ", s)
    for a, b in _SUBS:
        s = s.replace(a, b)
    # dấu nhấn phụ: "," hoặc "." còn lại (sau khi đã tách các cách đọc)
    s = s.replace(",", "ˌ").replace(".", "ˌ")
    # j: trước nguyên âm (hoặc trước ː) là /j/, còn lại là ʊ
    out = []
    for i, ch in enumerate(s):
        if ch == "j":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            # "jj" (absolutory æb'sɔljjtәri = æbˈsɒljʊtəri): j thứ nhất là /j/, j thứ hai là ʊ
            out.append("j" if nxt in VOWELS or nxt == "j" else "ʊ")
        else:
            out.append(ch)
    s = "".join(out)
    # ký hiệu kiểu Anh cũ của ECDICT → IPA hiện hành (cùng cách Wiktionary ghi): əː → ɜː (merchandise), ɒː → ɔː (sport)
    s = s.replace("əː", "ɜː").replace("ɒː", "ɔː")
    s = re.sub(r"\s+", " ", s).strip()
    if not s or any(ch not in ALLOWED for ch in s):
        return None
    if not any(ch in VOWELS for ch in s):
        return None
    return f"/{s}/"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    for w in sys.argv[1:]:
        print(w, "→", ecdict_to_ipa(w))
