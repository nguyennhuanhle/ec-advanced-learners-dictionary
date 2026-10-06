// Kiểm phần dữ liệu cá nhân của bản web (vòng W3) trong Node, so với bản desktop (app.exe --call):
//  1. CSV: cùng một danh sách từ → file CSV của bản web (web/csv.ts) phải BẰNG ĐÚNG từng byte file của app.exe export_csv.
//  2. Quy tắc danh sách/lịch sử của user-mem.ts (= store.ts) khớp user_db.rs: trùng tên không phân biệt hoa/thường, mục trùng.
//  3. Sao lưu → khôi phục (gộp, giữ thời điểm), từ chối file sai định dạng / phiên bản mới hơn / hỏng, dữ liệu giữ nguyên.
// Dùng: node pipeline/web_user_check.mjs   (cần data/build/web/ từ export_web.py và app/src-tauri/target/debug/app.exe)
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { registerHooks } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// các module TS của bản web import nhau không ghi đuôi (kiểu bundler của Vite) → thử thêm ".ts" khi Node không tìm thấy
registerHooks({
  resolve(spec, ctx, next) {
    try {
      return next(spec, ctx);
    } catch (e) {
      if (spec.startsWith(".") && !path.extname(spec)) return next(spec + ".ts", ctx);
      throw e;
    }
  },
});
const web = (m) => import(pathToFileURL(path.join(ROOT, "app", "src", "lib", "web", m + ".ts")).href);
const { DictCore } = await web("core");
const { buildCsv } = await web("csv");
const { UserMem } = await web("user-mem");
const { USER_ERR, makeBackup, parseBackup, restoreBackup } = await web("user-common");
const WEB = path.join(ROOT, "data", "build", "web");
const APP = path.join(ROOT, "app", "src-tauri", "target", "debug", "app.exe");
const manifest = JSON.parse(fs.readFileSync(path.join(WEB, "manifest.json"), "utf8"));
const vdir = path.join(WEB, manifest.base);
const read = (p) => (fs.existsSync(path.join(vdir, p)) ? fs.readFileSync(path.join(vdir, p), "utf8") : null);
const core = new DictCore(manifest, {
  async json(p) {
    const t = read(p);
    return t === null ? null : JSON.parse(t);
  },
  async text(p) {
    return read(p);
  },
});

let fails = 0;
const check = (name, ok, extra = "") => {
  console.log(`${ok ? "ĐẠT " : "SAI "} ${name}${extra ? " — " + extra : ""}`);
  if (!ok) fails++;
};
const throws = (fn, msg) => {
  try {
    fn();
    return false;
  } catch (e) {
    return e === msg;
  }
};

// ---------- 1. CSV: web = desktop ----------
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ecald-w3-"));
const env = { ...process.env, TUDIEN_USER_DB: path.join(tmp, "user.sqlite") };
const desk = (cmd, args) => {
  const out = execFileSync(APP, ["--call", cmd, JSON.stringify(args)], { env, encoding: "utf8" });
  return JSON.parse(out);
};
// (từ, từ loại, nghĩa): cả từ, một từ loại, một nghĩa AI, một nghĩa Wiktionary, cụm từ, từ chỉ Wiktionary, từ đã không còn
const SAVES = [
  ["bank", "", ""],
  ["run", "verb", ""],
  ["set", "noun", "2"],
  ["light", "adj", "w1"],
  ["give up", "", ""],
  ["by the way", "", ""],
  ["serendipity", "", ""],
  ["go", "noun", ""],
  ["children", "", ""],
  ["zzqxw", "noun", ""],
];
const deskList = desk("list_create", { name: "W3 kiểm CSV" });
const mem = new UserMem();
const memList = mem.listCreate("W3 kiểm CSV");
SAVES.forEach(([word, pos, sense], i) => {
  const label = `${word}${pos ? " (" + pos + ")" : ""}`;
  desk("item_add", { list_id: deskList, word, pos, sense, label });
  mem.itemAdd(memList, word, pos, sense, label, 1_700_000_000 + i); // thời điểm tăng dần = thứ tự thêm như desktop
});
const deskFile = path.join(tmp, "desk.csv");
const nDesk = desk("export_csv", { list_id: deskList, path: deskFile });
const r = await buildCsv(mem.items(memList), (w) => core.call("get_entry", { word: w }));
const webBytes = Buffer.from("﻿" + r.text + "\r\n", "utf8");
const deskBytes = fs.readFileSync(deskFile);
const same = Buffer.compare(webBytes, deskBytes) === 0;
check(`CSV ${SAVES.length} mục (${r.rows} dòng): web bằng đúng app.exe`, same && r.rows === nDesk, `desktop ${nDesk} dòng, ${deskBytes.length} B; web ${webBytes.length} B`);
if (!same) {
  const a = webBytes.toString("utf8").split("\r\n");
  const b = deskBytes.toString("utf8").split("\r\n");
  for (let i = 0; i < Math.max(a.length, b.length); i++)
    if (a[i] !== b[i]) {
      console.log(`  dòng ${i + 1}\n   web : ${a[i]}\n   desk: ${b[i]}`);
      break;
    }
}
fs.writeFileSync(path.join(tmp, "web.csv"), webBytes);
check("danh sách trống → báo lỗi như desktop", await buildCsv([], () => null).then(() => false, (e) => e === USER_ERR.emptyList));

// ---------- 2. quy tắc danh sách / lịch sử ----------
const u = new UserMem();
check("danh sách mặc định", u.lists().length === 1 && u.lists()[0].name === "Từ của tôi");
const ielts = u.listCreate("  IELTS   band 7 ");
check("chuẩn hoá khoảng trắng tên", u.lists().some((l) => l.name === "IELTS band 7"));
check("trùng tên không phân biệt hoa/thường (tiếng Việt)", throws(() => u.listCreate("từ của TÔI"), USER_ERR.nameTaken));
check("tên trống", throws(() => u.listCreate("   "), USER_ERR.emptyName));
check("tên > 80 ký tự", throws(() => u.listCreate("ạ".repeat(81)), USER_ERR.longName));
u.itemAdd(ielts, "bank", "noun", "", "bank");
check("mục trùng", throws(() => u.itemAdd(ielts, "bank", "noun", "", "bank"), USER_ERR.dupItem));
u.listDelete(u.lists()[0].id);
u.listDelete(ielts);
check("xoá hết → còn danh sách mặc định", u.lists().length === 1 && u.lists()[0].name === "Từ của tôi");
for (let i = 0; i < 510; i++) u.historyPut({ key: `en:w${i}`, label: `w${i}`, kind: "en", ts: 1000 + i });
check("lịch sử giữ 500 mục mới nhất", u.history(1000).length === 500 && u.history(1)[0].label === "w509");

// ---------- 3. sao lưu / khôi phục ----------
const a = new UserMem();
const la = a.listCreate("IELTS");
a.itemAdd(la, "bank", "noun", "", "bank (noun)", 100);
a.itemAdd(la, "run", "", "", "run", 200);
a.itemAdd(a.lists()[0].id, "nhà", "", "", "nhà", 150);
a.historyPut({ key: "en:bank", label: "bank", kind: "en", ts: 500 });
a.historyPut({ key: "vi:nhà", label: "nhà", kind: "vi", ts: 600 });
a.settingSet("theme", "dark");
const backup = await makeBackup(a, "0.1.0");
const text = JSON.stringify(backup);

const b = new UserMem();
const lb = b.listCreate("ielts"); // trùng tên khác hoa/thường → phải gộp vào đây
b.itemAdd(lb, "bank", "noun", "", "bank (noun)", 50); // mục đã có → bỏ qua
b.historyPut({ key: "en:bank", label: "bank", kind: "en", ts: 900 }); // mới hơn bản sao lưu → giữ
const res = await restoreBackup(b, parseBackup(text));
const items = b.items(lb).map((i) => i.word);
check("khôi phục gộp danh sách trùng tên, bỏ mục trùng", res.lists === 0 && res.items === 2 && items.join(",") === "run,bank", JSON.stringify(res));
check("khôi phục giữ thời điểm thêm", b.items(lb)[0].added_at === 200);
check("lịch sử: giữ bản mới hơn, thêm mục thiếu", b.history(10).map((h) => `${h.key}@${h.ts}`).join(",") === "en:bank@900,vi:nhà@600");
check("cài đặt lấy theo bản sao lưu", b.settings().theme === "dark");
const before = JSON.stringify(b.lists()) + JSON.stringify(b.history(10));
check("từ chối file không phải sao lưu", throws(() => parseBackup('{"hello":1}'), USER_ERR.backupFormat));
check("từ chối JSON hỏng", throws(() => parseBackup("{"), USER_ERR.backupFormat));
check("từ chối bản mới hơn", throws(() => parseBackup(JSON.stringify({ ...backup, version: 99 })), USER_ERR.backupNewer));
check("từ chối dữ liệu thiếu", throws(() => parseBackup(JSON.stringify({ ...backup, lists: [{ name: "x" }] })), USER_ERR.backupBroken));
check("từ chối tên danh sách trống", throws(() => parseBackup(JSON.stringify({ ...backup, lists: [{ name: " ", items: [] }] })), USER_ERR.emptyName));
check("dữ liệu giữ nguyên sau khi từ chối", JSON.stringify(b.lists()) + JSON.stringify(b.history(10)) === before);
b.clearAll();
check("xoá toàn bộ → còn danh sách mặc định trống", b.lists().length === 1 && b.lists()[0].count === 0 && b.history(10).length === 0);

fs.rmSync(tmp, { recursive: true, force: true });
console.log(fails ? `\n${fails} mục SAI` : "\nTất cả ĐẠT");
process.exit(fails ? 1 : 0);
