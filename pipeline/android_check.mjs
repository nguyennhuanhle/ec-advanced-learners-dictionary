// Kiểm app Android không cần chuột (UC-AM02): nối DevTools (CDP) vào WebView của app (hoặc một trình duyệt mở bản web),
// tra bộ từ kiểm tra bằng địa chỉ "#/…", in tiêu đề + đoạn đầu mục từ + thời gian, và mã băm nội dung để so với bản web.
//
// Dùng (Node 22+, có sẵn WebSocket):
//   adb forward tcp:9222 localabstract:webview_devtools_remote_<pid>     (pid = adb shell pidof com.edtechcorner.dictionary)
//   node pipeline/android_check.mjs 9222 > a.txt
//   (bản web để so: msedge --headless=new --remote-debugging-port=9333 http://127.0.0.1:4173/ ; node … 9333 > w.txt)
// In ra để đọc bằng mắt, không assert.

import { createHash } from "node:crypto";

const port = process.argv[2] ?? "9222";
const WORDS = [
  ["en", "consider"], ["en", "bank"], ["en", "run"], ["en", "children"], ["en", "went"], ["en", "take off"],
  ["en", "café"], ["en", "con"], ["en", "zeitgeist"], ["en", "recieve"], ["vi", "học"], ["vi", "nha"], ["vi", "máy tính"],
];

const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page" && /localhost|127\.0\.0\.1|edtechcorner/.test(t.url));
if (!page) throw new Error("không thấy trang của app: " + JSON.stringify(targets.map((t) => t.url)));
const ws = new WebSocket(page.webSocketDebuggerUrl);
await new Promise((r, j) => { ws.onopen = r; ws.onerror = j; });
let id = 0;
const waiting = new Map();
ws.onmessage = (e) => {
  const m = JSON.parse(e.data);
  if (m.id && waiting.has(m.id)) { waiting.get(m.id)(m); waiting.delete(m.id); }
};
const send = (method, params = {}) => new Promise((r) => { const i = ++id; waiting.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
async function evaluate(expr) {
  const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(JSON.stringify(r.result.exceptionDetails));
  return r.result?.result?.value;
}

console.log(`# ${page.url}`);
console.log(`# UA: ${await evaluate("navigator.userAgent")}`);
// đo: chờ tới khi tiêu đề mục từ đổi (hoặc hiện "không tìm thấy"/gợi ý), tối đa 15 s
// sẵn sàng = nội dung <main> đã KHÁC lần trước (không đọc nhầm mục cũ) và không còn chữ "đang tải"
const probe = `async (hash) => {
  const main = () => document.querySelector("main") || document.body;
  const prev = main().innerText;
  const t0 = performance.now();
  location.hash = hash;
  for (;;) {
    await new Promise((r) => setTimeout(r, 25));
    const h = document.querySelector("main h1, main h2");
    const txt = main().innerText;
    const ready = h && txt !== prev && !/Loading|Đang tải/.test(txt.slice(0, 200));
    if (ready || performance.now() - t0 > 15000) {
      await new Promise((r) => setTimeout(r, 150));
      // so nội dung, không so nút (Lưu/Sao chép/Chia sẻ khác nhau giữa bản web và app, và đổi theo trạng thái đã lưu)
      const c = main().cloneNode(true);
      c.querySelectorAll("button, select").forEach((b) => b.remove());
      return { ms: Math.round(performance.now() - t0), head: (document.querySelector("main h1, main h2")?.textContent || "").trim(), text: c.textContent.replace(/\\s+/g, " ").trim() };
    }
  }
}`;
for (const [mode, w] of WORDS) {
  const hash = `#/${mode}/${w}`;
  const r = await evaluate(`(${probe})(${JSON.stringify(hash)})`);
  const sha = createHash("sha256").update(r.text).digest("hex").slice(0, 10);
  console.log(`${hash.padEnd(22)} ${String(r.ms).padStart(5)} ms  sha=${sha}  len=${r.text.length}  h="${r.head}"  | ${r.text.replace(/\s+/g, " ").slice(0, 110)}`);
}
// gợi ý khi gõ: đo thời gian tới khi danh sách gợi ý hiện
const sug = await evaluate(`(async () => {
  const inp = document.querySelector('input[type="search"], header input');
  if (!inp) return "không thấy ô tìm";
  const out = [];
  const list = () => [...document.querySelectorAll("ul.sugs[role=listbox] li")];
  for (const q of ["ab", "inter", "nghi"]) {
    const before = list().map((e) => e.textContent).join("|");
    const t0 = performance.now();
    inp.value = q; inp.dispatchEvent(new Event("input", { bubbles: true }));
    for (;;) {
      await new Promise((r) => setTimeout(r, 20));
      const items = list();
      if ((items.length && items.map((e) => e.textContent).join("|") !== before) || performance.now() - t0 > 5000) { out.push(q + ": " + Math.round(performance.now() - t0) + " ms, " + items.length + " gợi ý (" + items.slice(0, 3).map((e) => e.textContent.trim().split(/\\s+/)[0]).join(", ") + ")"); break; }
    }
  }
  inp.value = ""; inp.dispatchEvent(new Event("input", { bubbles: true }));
  return out.join("; ");
})()`);
console.log(`gợi ý: ${sug}`);
ws.close();
