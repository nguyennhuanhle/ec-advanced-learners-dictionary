// Chạy bộ giải từ của bản web (app/src/lib/web/core.ts) trong Node, đọc thẳng data/build/web/ — cho pipeline/web_compare.py.
// Cần Node ≥ 22.18 (tự bỏ kiểu TypeScript khi import file .ts; Node 24 bật sẵn).
//
// Dùng: node pipeline/web_core_cli.mjs < jobs.json > results.json
//   jobs.json  = [{"cmd": "lookup", "args": {"q": "went", "mode": "envi"}}, …]
//   results    = [{"ok": true, "value": …, "ms": 1.2} | {"ok": false, "error": "…"}, …]
//   (thêm hai lệnh chỉ để kiểm: "__fts" {q} → 600 ứng viên FTS mô phỏng [[từ, rank]…]; "__exists" {word})
//       node pipeline/web_core_cli.mjs --bench recieve bnak …   → đo thời gian gợi ý chính tả (ms)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DictCore } from "../app/src/lib/web/core.ts";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "data", "build", "web");
const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "manifest.json"), "utf8"));
const vdir = path.join(ROOT, manifest.base);

function read(p) {
  try {
    return fs.readFileSync(path.join(vdir, p), "utf8");
  } catch (e) {
    if (e.code === "ENOENT") return null;
    throw e;
  }
}

const src = {
  async json(p) {
    const t = read(p);
    return t === null ? null : JSON.parse(t);
  },
  async text(p) {
    return read(p);
  },
};

const core = new DictCore(manifest, src);
const args = process.argv.slice(2);

if (args[0] === "--bench") {
  const out = {};
  const t0 = performance.now();
  await core.loadWords();
  out.load_words_ms = +(performance.now() - t0).toFixed(1);
  out.words_parse_ms = +core.wordsLoadMs.toFixed(1);
  out.fuzzy = {};
  for (const w of args.slice(1)) {
    const times = [];
    let res;
    for (let i = 0; i < 7; i++) {
      const t = performance.now();
      res = await core.fuzzy(w.toLowerCase());
      times.push(performance.now() - t);
    }
    times.sort((a, b) => a - b);
    out.fuzzy[w] = { median_ms: +times[3].toFixed(1), max_ms: +times[6].toFixed(1), first: res.slice(0, 5).map((x) => x.word) };
  }
  process.stdout.write(JSON.stringify(out, null, 1));
} else {
  const jobs = JSON.parse(fs.readFileSync(0, "utf8"));
  const results = [];
  for (const j of jobs) {
    const t = performance.now();
    try {
      // "__fts": 600 ứng viên FTS mô phỏng (để so với SQLite thật); "__exists": như Dict::exists
      const value =
        j.cmd === "__fts"
          ? await core.ftsTop(j.args.q)
          : j.cmd === "__exists"
            ? await core.exists(j.args.word)
            : await core.call(j.cmd, j.args ?? {});
      results.push({ ok: true, value: value ?? null, ms: +(performance.now() - t).toFixed(2) });
    } catch (e) {
      results.push({ ok: false, error: String(e?.message ?? e) });
    }
  }
  process.stdout.write(JSON.stringify(results));
}
