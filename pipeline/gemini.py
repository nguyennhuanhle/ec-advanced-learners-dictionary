"""Gọi Gemini cho pipeline (chỉ chạy lúc build trên máy người bảo trì, app không gọi mạng).

- Khoá đọc từ khoa-api.env (GEMINI_API_KEY_n). Không bao giờ in khoá.
- Chuỗi model theo D:\\GitHub\\GEMINI_MODELS_RUNBOOK.md: 404/429/5xx → model kế ngay; 400 → lỗi yêu cầu, dừng;
  401/403 → khoá hỏng, chuyển khoá kế.
- Chưa xoay khoá để nhân quota free (xem PLAN mục 9.2): hết quota mọi model thì báo QuotaExhausted.
"""
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = [m for m in os.environ.get("GEMINI_MODELS", "").split(",") if m] or [
    "gemini-flash-latest",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
# Cố ý không có model lite: giữ chất lượng đồng đều giữa các mục từ.
API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class QuotaExhausted(Exception):
    pass


class _Overloaded(Exception):
    pass


def load_keys():
    keys = []
    path = ROOT / "khoa-api.env"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("GEMINI_API_KEY_") and "=" in line:
            name, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            if val:
                keys.append((int(name.rsplit("_", 1)[1]), val))
    return [k for _, k in sorted(keys)]


class Gemini:
    def __init__(self, models=None):
        self.keys = load_keys()
        if not self.keys:
            raise SystemExit("Không có GEMINI_API_KEY_n trong khoa-api.env")
        self.key_idx = 0
        self.models = models or MODELS
        self.usage = {"requests": 0, "prompt_tokens": 0, "output_tokens": 0, "thinking_tokens": 0}
        self.model_hits = {}

    def _post(self, model, body):
        req = urllib.request.Request(
            API.format(model=model),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.keys[self.key_idx]},
        )
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.loads(r.read())

    def generate_json(self, prompt, schema, temperature=0.3, rounds=5):
        """Đi hết chuỗi model; nếu mọi model đều quá tải (5xx/timeout) thì chờ giãn cách rồi đi lại chuỗi.
        Pipeline chạy lô nên chờ được, khác với app tương tác trong runbook."""
        errors = []
        for r in range(rounds):
            try:
                return self._chain(prompt, schema, temperature)
            except _Overloaded as e:
                errors.append(str(e))
                wait = 15 * 2 ** r
                print(f"    mọi model quá tải, chờ {wait}s (vòng {r + 1}/{rounds})", flush=True)
                time.sleep(wait)
        raise RuntimeError("Quá tải sau nhiều vòng: " + " || ".join(errors))

    def _chain(self, prompt, schema, temperature):
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": temperature,
            },
        }
        errors = []
        for model in self.models:
            while True:
                try:
                    t0 = time.time()
                    data = self._post(model, body)
                except urllib.error.HTTPError as e:
                    code = e.code
                    msg = e.read().decode("utf-8", "replace")[:300]
                    if code in (401, 403) and self.key_idx + 1 < len(self.keys):
                        errors.append(f"key#{self.key_idx + 1} {code}")
                        self.key_idx += 1  # khoá hỏng/bị thu hồi → khoá kế
                        continue
                    if code == 400:
                        raise RuntimeError(f"{model} 400: {msg}")
                    errors.append(f"{model} {code}")
                    break  # 404/429/5xx → model kế, không backoff
                except (urllib.error.URLError, TimeoutError) as e:
                    errors.append(f"{model} {type(e).__name__}")
                    break
                self.usage["requests"] += 1
                um = data.get("usageMetadata", {})
                self.usage["prompt_tokens"] += um.get("promptTokenCount", 0)
                self.usage["output_tokens"] += um.get("candidatesTokenCount", 0)
                self.usage["thinking_tokens"] += um.get("thoughtsTokenCount", 0)
                self.model_hits[model] = self.model_hits.get(model, 0) + 1
                try:
                    text = data["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text), {"model": model, "seconds": round(time.time() - t0, 1)}
                except (KeyError, IndexError, json.JSONDecodeError) as e:
                    errors.append(f"{model} bad-output {type(e).__name__}")
                    break
        if errors and all(" 429" in e for e in errors):
            raise QuotaExhausted("; ".join(errors))
        if errors and all(e.split()[-1] in ("500", "502", "503", "504", "URLError", "TimeoutError", "429")
                          for e in errors):
            raise _Overloaded("; ".join(errors))
        raise RuntimeError("Mọi model đều lỗi: " + "; ".join(errors))
