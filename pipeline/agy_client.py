"""Gọi Gemini Pro qua Antigravity CLI (agy, gói Ultra của người dùng) cho pipeline.

Dùng lại hàm call_agy của skill gemini-rewrite (agy chạy trong thư mục tạm, --sandbox, prompt qua stdin).
agy không ép JSON schema như API, nên prompt phải yêu cầu JSON và kết quả được parse + kiểm lại ở phía pipeline.
"""
import json
import sys
from pathlib import Path

SKILL = Path.home() / ".claude" / "skills" / "gemini-rewrite"
sys.path.insert(0, str(SKILL / "scripts"))
import gemini_write  # noqa: E402

CFG = json.loads((SKILL / "config.json").read_text(encoding="utf-8"))


class Agy:
    def __init__(self, model=None, effort=None):
        self.agy = gemini_write.find_agy(CFG)
        self.models = [model or CFG["model"]] + ([CFG["fallback_model"]] if not model and CFG.get("fallback_model") else [])
        self.effort = effort
        self.calls = 0

    def generate_json(self, prompt, schema=None, temperature=None):
        shape = f"\n\nThe JSON must follow this schema (OpenAPI subset):\n{json.dumps(schema)}" if schema else ""
        full = prompt + shape + "\n\nOutput ONLY the JSON object, no prose, no code fences."
        errors = []
        for model in self.models:
            for attempt in (1, 2):  # agy đôi khi trả rỗng hoặc kèm lời dẫn → tách JSON, không được thì thử lại 1 lần
                text = ""
                try:
                    text, meta = gemini_write.call_agy(self.agy, full, model, self.effort,
                                                       CFG.get("timeout_seconds", 600))
                    self.calls += 1
                    return json.loads(extract_json(text)), meta
                except json.JSONDecodeError as e:
                    errors.append(f"{model}#{attempt}: JSON lỗi ({e}); phản hồi: {text[:300]!r}")
                except RuntimeError as e:
                    errors.append(f"{model}#{attempt}: {str(e)[:300]}")
        raise RuntimeError("agy lỗi: " + " | ".join(errors))


def extract_json(text):
    i, j = text.find("{"), text.rfind("}")
    return text[i:j + 1] if i >= 0 and j > i else text
