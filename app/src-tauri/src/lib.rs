mod db;
mod user_db;

use db::Dict;
use serde_json::{json, Value};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use tauri::Manager;
use user_db::{Item, UserDb};

const APP_ID: &str = "vn.edtechcorner.tudien";

/// Toàn bộ trạng thái lõi: dữ liệu từ điển (chỉ đọc) + dữ liệu cá nhân (đọc-ghi).
/// Mở được thì có `dict` / `user`, không thì có thông báo lỗi để giao diện hiện màn hình khôi phục (UC-S02).
struct Core {
    dict: Option<Dict>,
    dict_error: Option<String>,
    dict_path: PathBuf,
    user: Option<UserDb>,
    user_error: Option<String>,
    user_notice: Mutex<Option<String>>,
}

/// Thứ tự tìm file dữ liệu lõi: biến môi trường TUDIEN_DB → thư mục resource của bản cài → data/build khi phát triển.
fn locate_db(app: Option<&tauri::App>) -> PathBuf {
    if let Ok(p) = std::env::var("TUDIEN_DB") {
        return PathBuf::from(p);
    }
    if let Some(app) = app {
        if let Ok(dir) = app.path().resource_dir() {
            let p = dir.join("dict-core.sqlite");
            if p.exists() {
                return p;
            }
        }
    }
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../data/build/dict-core.sqlite")
}

/// Dữ liệu cá nhân: %APPDATA%\<app id>\user.sqlite (cùng chỗ cho app thật và chế độ dòng lệnh).
fn locate_user_db(app: Option<&tauri::App>) -> PathBuf {
    if let Ok(p) = std::env::var("TUDIEN_USER_DB") {
        return PathBuf::from(p);
    }
    if let Some(app) = app {
        if let Ok(dir) = app.path().app_data_dir() {
            return dir.join("user.sqlite");
        }
    }
    let base = std::env::var("APPDATA").map(PathBuf::from).unwrap_or_else(|_| std::env::temp_dir());
    base.join(APP_ID).join("user.sqlite")
}

fn arg_str<'a>(a: &'a Value, k: &str) -> &'a str {
    a.get(k).and_then(Value::as_str).unwrap_or("")
}

fn arg_i64(a: &Value, k: &str) -> i64 {
    a.get(k).and_then(Value::as_i64).unwrap_or(0)
}

fn to_value<T: serde::Serialize>(v: T) -> Result<Value, String> {
    serde_json::to_value(v).map_err(|e| e.to_string())
}

impl Core {
    fn open(dict_path: PathBuf, user_path: PathBuf) -> Core {
        let (dict, dict_error) = match Dict::open(&dict_path) {
            Ok(d) => (Some(d), None),
            Err(e) => (None, Some(e)),
        };
        let (user, user_error, notice) = match UserDb::open(&user_path) {
            Ok((u, n)) => (Some(u), None, n),
            Err(e) => (None, Some(e), None),
        };
        Core { dict, dict_error, dict_path, user, user_error, user_notice: Mutex::new(notice) }
    }

    fn dict(&self) -> Result<&Dict, String> {
        self.dict.as_ref().ok_or_else(|| self.dict_error.clone().unwrap_or_else(|| "Chưa mở được dữ liệu".into()))
    }

    fn user(&self) -> Result<&UserDb, String> {
        self.user.as_ref().ok_or_else(|| self.user_error.clone().unwrap_or_else(|| "Chưa mở được dữ liệu cá nhân".into()))
    }

    /// Một cửa vào cho mọi lệnh của giao diện (Tauri) và của chế độ dòng lệnh `--call`.
    fn call(&self, cmd: &str, a: &Value) -> Result<Value, String> {
        match cmd {
            "db_status" => Ok(json!({
                "ok": self.dict.is_some(),
                "app_version": env!("CARGO_PKG_VERSION"),
                "error": self.dict_error,
                "path": self.dict_path.display().to_string(),
                "meta": self.dict.as_ref().map(|d| d.meta.clone()).unwrap_or_default(),
                "counts": self.dict.as_ref().map(|d| d.counts()).unwrap_or_default(),
                "user_ok": self.user.is_some(),
                "user_error": self.user_error,
                "user_path": self.user.as_ref().map(|u| u.path.display().to_string()),
                // thông báo (vd. đã khôi phục file hỏng) chỉ trả về một lần
                "user_notice": self.user_notice.lock().unwrap().take(),
            })),
            "suggest" => to_value(self.dict()?.suggest(arg_str(a, "q"), arg_str(a, "mode"))),
            "lookup" => to_value(self.dict()?.lookup(arg_str(a, "q"), arg_str(a, "mode"))),
            "get_entry" => to_value(self.dict()?.entry(arg_str(a, "word"))),
            "get_vi_entry" => to_value(self.dict()?.vi_entry(arg_str(a, "word"))),
            "sources" => to_value(self.dict()?.sources()),

            "history" => to_value(self.user()?.history(a.get("limit").and_then(Value::as_i64).unwrap_or(200))),
            "history_add" => {
                self.user()?.history_add(arg_str(a, "key"), arg_str(a, "label"), arg_str(a, "kind"))?;
                Ok(Value::Null)
            }
            "history_clear" => self.user()?.history_clear().map(|_| Value::Null),

            "lists" => to_value(self.user()?.lists()),
            "list_create" => to_value(self.user()?.list_create(arg_str(a, "name"))?),
            "list_rename" => self.user()?.list_rename(arg_i64(a, "id"), arg_str(a, "name")).map(|_| Value::Null),
            "list_delete" => self.user()?.list_delete(arg_i64(a, "id")).map(|_| Value::Null),
            "list_items" => to_value(self.items_checked(arg_i64(a, "id"))?),
            "saved_keys" => to_value(self.user()?.saved_keys(arg_i64(a, "id"))),
            "item_add" => to_value(self.user()?.item_add(
                arg_i64(a, "list_id"),
                arg_str(a, "word"),
                arg_str(a, "pos"),
                arg_str(a, "sense"),
                arg_str(a, "label"),
            )?),
            "item_remove" => self.user()?.item_remove(arg_i64(a, "id")).map(|_| Value::Null),

            "settings" => to_value(self.user()?.settings()),
            "setting_set" => self.user()?.setting_set(arg_str(a, "key"), arg_str(a, "value")).map(|_| Value::Null),

            "default_export_path" => Ok(json!(default_export_path(arg_str(a, "name")).display().to_string())),
            "export_csv" => self.export_csv(arg_i64(a, "list_id"), arg_str(a, "path")).map(|n| json!(n)),
            _ => Err(format!("Lệnh không tồn tại: {cmd}")),
        }
    }

    /// Mục trong danh sách + cờ "còn có trong dữ liệu hiện tại" (lỗi: từ đã lưu không còn sau khi cập nhật dữ liệu).
    fn items_checked(&self, list_id: i64) -> Result<Vec<Item>, String> {
        let user = self.user()?;
        let dict = self.dict.as_ref();
        Ok(user
            .items(list_id)
            .into_iter()
            .map(|mut i| {
                i.exists = dict.map(|d| d.exists(&i.word)).unwrap_or(false);
                i
            })
            .collect())
    }

    /// UC-U35: xuất CSV (UTF-8 có BOM để Excel đọc đúng tiếng Việt). Ghi file tạm cùng thư mục rồi mới đổi tên,
    /// lỗi giữa chừng (đĩa đầy, không có quyền) thì xoá file tạm, không để lại file dở dang.
    fn export_csv(&self, list_id: i64, path: &str) -> Result<usize, String> {
        if path.trim().is_empty() {
            return Err("Chưa chọn nơi lưu file".into());
        }
        let items = self.items_checked(list_id)?;
        if items.is_empty() {
            return Err("Danh sách đang trống, chưa có gì để xuất".into());
        }
        let dict = self.dict()?;
        let mut rows: Vec<Vec<String>> = vec![[
            "Từ", "Từ loại", "IPA (UK)", "IPA (US)", "CEFR", "Từ dẫn nghĩa", "Định nghĩa", "Nghĩa tiếng Việt", "Ví dụ",
            "Ví dụ (tiếng Việt)", "Nguồn",
        ]
        .iter()
        .map(|s| s.to_string())
        .collect()];
        for it in items.iter().rev() {
            rows.extend(csv_rows(dict, it));
        }
        let text: String = rows.iter().map(|r| r.iter().map(|c| csv_field(c)).collect::<Vec<_>>().join(",")).collect::<Vec<_>>().join("\r\n");
        let target = Path::new(path);
        let tmp = target.with_extension("csv.part");
        let write = || -> std::io::Result<()> {
            let mut f = std::fs::File::create(&tmp)?;
            f.write_all("\u{feff}".as_bytes())?;
            f.write_all(text.as_bytes())?;
            f.write_all(b"\r\n")?;
            f.sync_all()?;
            if target.exists() {
                std::fs::remove_file(target)?;
            }
            std::fs::rename(&tmp, target)
        };
        write().map_err(|e| {
            let _ = std::fs::remove_file(&tmp);
            format!("Không ghi được {}: {e}", target.display())
        })?;
        Ok(rows.len() - 1)
    }
}

fn csv_field(s: &str) -> String {
    if s.contains([',', '"', '\n', '\r']) {
        format!("\"{}\"", s.replace('"', "\"\""))
    } else {
        s.to_string()
    }
}

/// Một mục đã lưu → các dòng CSV. Cả từ: mỗi từ loại một dòng, các nghĩa đánh số trong một ô. Một nghĩa: một dòng.
fn csv_rows(dict: &Dict, it: &Item) -> Vec<Vec<String>> {
    let Some(e) = dict.entry(&it.word) else {
        return vec![vec![it.word.clone(), it.pos.clone(), "".into(), "".into(), "".into(), "".into(),
            "(không còn trong bộ dữ liệu hiện tại)".into(), "".into(), "".into(), "".into(), "".into()]];
    };
    let uk = e.ipa.uk.clone().unwrap_or_default();
    let us = e.ipa.us.clone().unwrap_or_default();
    let mut out = vec![];
    for b in e.blocks.iter().filter(|b| it.pos.is_empty() || b.pos == it.pos) {
        let src = if b.model.is_some() { "AI (Gemini) từ Wiktionary" } else { "Wiktionary" };
        // (từ dẫn nghĩa, định nghĩa, CEFR, nghĩa Việt, ví dụ, ví dụ Việt)
        let senses: Vec<(String, String, String, String, String, String)> = if !b.senses.is_empty() {
            b.senses
                .iter()
                .map(|s| {
                    let ex = s.examples.first();
                    (
                        s.guideword.clone().unwrap_or_default(),
                        s.definition.clone(),
                        s.cefr.clone().unwrap_or_default(),
                        s.vi.clone().unwrap_or_default(),
                        ex.map(|x| x.en.clone()).unwrap_or_default(),
                        ex.and_then(|x| x.vi.clone()).unwrap_or_default(),
                    )
                })
                .collect()
        } else {
            b.wiktionary
                .iter()
                .map(|w| {
                    (String::new(), w.gloss.clone(), String::new(), w.vi.clone().unwrap_or_default(),
                     w.examples.first().cloned().unwrap_or_default(), String::new())
                })
                .collect()
        };
        let picked: Vec<_> = match it.sense.as_str() {
            "" => senses.iter().take(8).collect(),
            s => {
                let idx = s.trim_start_matches('w').parse::<usize>().unwrap_or(usize::MAX);
                senses.get(idx).into_iter().collect()
            }
        };
        if picked.is_empty() {
            continue;
        }
        let vi_fallback = if b.senses.is_empty() { b.vi_block.iter().take(3).cloned().collect::<Vec<_>>().join("; ") } else { String::new() };
        let join = |f: &dyn Fn(&(String, String, String, String, String, String)) -> String, numbered: bool| -> String {
            if picked.len() == 1 {
                return f(picked[0]);
            }
            picked
                .iter()
                .enumerate()
                .map(|(i, s)| if numbered { format!("{}. {}", i + 1, f(s)) } else { f(s) })
                .filter(|x| !x.trim_end_matches(|c: char| c == '.' || c.is_ascii_digit() || c == ' ').is_empty())
                .collect::<Vec<_>>()
                .join(" | ")
        };
        let mut vi = join(&|s| s.3.clone(), true);
        if vi.trim().is_empty() || vi.chars().all(|c| c.is_ascii_digit() || " .|".contains(c)) {
            vi = vi_fallback;
        }
        out.push(vec![
            e.word.clone(),
            b.pos.clone(),
            uk.clone(),
            us.clone(),
            if picked.len() == 1 { picked[0].2.clone() } else { b.cefr.clone().unwrap_or_default() },
            join(&|s| s.0.clone(), false),
            join(&|s| s.1.clone(), true),
            vi,
            picked.iter().map(|s| s.4.clone()).find(|x| !x.is_empty()).unwrap_or_default(),
            picked.iter().map(|s| s.5.clone()).find(|x| !x.is_empty()).unwrap_or_default(),
            src.into(),
        ]);
    }
    out
}

fn default_export_path(name: &str) -> PathBuf {
    let safe: String = name
        .chars()
        .map(|c| if c.is_alphanumeric() || c == ' ' || c == '-' || c == '_' { c } else { '_' })
        .collect::<String>()
        .trim()
        .to_string();
    let dir = std::env::var("USERPROFILE").map(|h| PathBuf::from(h).join("Documents")).unwrap_or_else(|_| std::env::temp_dir());
    dir.join(format!("EC Dictionary - {}.csv", if safe.is_empty() { "word list" } else { &safe }))
}

#[tauri::command(async)]
fn call(state: tauri::State<Core>, cmd: String, args: Value) -> Result<Value, String> {
    state.call(&cmd, &args)
}

/// Chế độ dòng lệnh để kiểm tra không cần mở cửa sổ (PLAN mục 11):
///   app.exe --call <lệnh> '<json>'     gọi đúng lệnh giao diện dùng, in JSON kết quả
///   app.exe --dump <từ> | --dump-vi <từ> | --lookup [--mode=vien] <chuỗi> | --suggest <chuỗi> | --status | --sources
pub fn cli(args: &[String]) -> Option<i32> {
    let flag = args.get(1)?.as_str();
    let (cmd, a): (String, Value) = match flag {
        "--call" => {
            let a = args.get(3).map(|s| serde_json::from_str(s).unwrap_or(Value::Null)).unwrap_or(json!({}));
            (args.get(2).cloned().unwrap_or_default(), a)
        }
        "--dump" | "--dump-vi" | "--lookup" | "--suggest" | "--status" | "--sources" => {
            let (mode, rest) = match args.get(2) {
                Some(m) if m.starts_with("--mode=") => (m.trim_start_matches("--mode=").to_string(), &args[3..]),
                _ => ("envi".to_string(), &args[2..]),
            };
            let q = rest.join(" ");
            let cmd = match flag {
                "--dump" => "get_entry",
                "--dump-vi" => "get_vi_entry",
                "--lookup" => "lookup",
                "--suggest" => "suggest",
                "--status" => "db_status",
                _ => "sources",
            };
            (cmd.to_string(), json!({"q": q, "word": q, "mode": mode}))
        }
        _ => return None,
    };
    let core = Core::open(locate_db(None), locate_user_db(None));
    match core.call(&cmd, &a) {
        Ok(v) => {
            println!("{}", serde_json::to_string_pretty(&v).unwrap_or_default());
            Some(0)
        }
        Err(e) => {
            println!("{}", json!({ "error": e }));
            Some(1)
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            let core = Core::open(locate_db(Some(app)), locate_user_db(Some(app)));
            app.manage(core);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![call])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
