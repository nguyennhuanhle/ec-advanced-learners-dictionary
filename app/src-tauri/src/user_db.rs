//! Dữ liệu cá nhân (user.sqlite, đọc-ghi): lịch sử, danh sách từ, cài đặt (UC-U29, U30, U32, S03).
//! Nằm ở thư mục dữ liệu của người dùng, tách khỏi dữ liệu lõi → cập nhật gói dữ liệu không làm mất (CANNOT).
//! Mục đã lưu trỏ tới (từ, từ loại) chứ không trỏ id số, để sống sót qua các bản dữ liệu mới.

use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

pub const DEFAULT_LIST: &str = "Từ của tôi";

/// Mỗi phần tử là một bước nâng cấp; chỉ thêm vào cuối, không sửa bước cũ.
const MIGRATIONS: &[&str] = &[
    // v1
    "CREATE TABLE history(id INTEGER PRIMARY KEY, key TEXT NOT NULL, label TEXT NOT NULL, kind TEXT NOT NULL, ts INTEGER NOT NULL);
     CREATE INDEX history_ts ON history(ts);
     CREATE TABLE wordlist(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, created INTEGER NOT NULL);
     CREATE TABLE wordlist_item(id INTEGER PRIMARY KEY, list_id INTEGER NOT NULL REFERENCES wordlist(id) ON DELETE CASCADE,
       word TEXT NOT NULL, pos TEXT NOT NULL DEFAULT '', sense TEXT NOT NULL DEFAULT '', label TEXT NOT NULL,
       added_at INTEGER NOT NULL, UNIQUE(list_id, word, pos, sense));
     CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);",
];

pub struct UserDb {
    conn: Mutex<Connection>,
    pub path: PathBuf,
}

#[derive(Serialize)]
pub struct HistoryRow {
    pub key: String,
    pub label: String,
    pub kind: String,
    pub ts: i64,
}

#[derive(Serialize)]
pub struct ListInfo {
    pub id: i64,
    pub name: String,
    pub count: i64,
}

#[derive(Serialize, Clone)]
pub struct Item {
    pub id: i64,
    pub word: String,
    pub pos: String,
    /// "" = cả từ; "3" = nghĩa AI số 3; "w2" = nghĩa Wiktionary số 2
    pub sense: String,
    pub label: String,
    pub added_at: i64,
    /// còn có trong dữ liệu lõi hiện tại không (do lib.rs điền)
    pub exists: bool,
}

pub fn now() -> i64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0)
}

fn stamp() -> String {
    // yyyymmdd-hhmmss theo giờ UTC, đủ để phân biệt các bản sao lưu
    let t = now();
    let (d, s) = (t / 86400, t % 86400);
    let (y, m, day) = civil_from_days(d);
    format!("{y:04}{m:02}{day:02}-{:02}{:02}{:02}", s / 3600, (s % 3600) / 60, s % 60)
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (yoe + era * 400 + i64::from(m <= 2), m, d)
}

fn healthy(path: &Path) -> bool {
    Connection::open(path)
        .and_then(|c| c.query_row("PRAGMA quick_check", [], |r| r.get::<_, String>(0)))
        .map(|s| s == "ok")
        .unwrap_or(false)
}

impl UserDb {
    /// Mở (tạo nếu chưa có). File hỏng → đổi tên .bak-<thời điểm>, tạo file mới, trả về thông báo cho người dùng.
    pub fn open(path: &Path) -> Result<(UserDb, Option<String>), String> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| format!("Không tạo được thư mục {} ({e})", dir.display()))?;
        }
        let mut notice = None;
        if path.exists() && !healthy(path) {
            let bak = path.with_extension(format!("sqlite.bak-{}", stamp()));
            std::fs::rename(path, &bak).map_err(|e| format!("Dữ liệu cá nhân hỏng và không đổi tên được ({e})"))?;
            notice = Some(format!(
                "Dữ liệu cá nhân bị hỏng nên app đã tạo bản mới. Bản cũ được giữ ở: {}",
                bak.display()
            ));
        }
        let conn = Connection::open(path).map_err(|e| format!("Không mở được dữ liệu cá nhân ({e})"))?;
        conn.execute_batch("PRAGMA foreign_keys = ON; PRAGMA journal_mode = WAL;").map_err(|e| e.to_string())?;
        let db = UserDb { conn: Mutex::new(conn), path: path.to_path_buf() };
        db.migrate()?;
        db.ensure_default_list()?;
        Ok((db, notice))
    }

    /// UC-S03: nâng cấp schema trong transaction; sao lưu file trước khi nâng cấp một bản đã có dữ liệu.
    fn migrate(&self) -> Result<(), String> {
        let mut conn = self.conn.lock().unwrap();
        conn.execute_batch("CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at INTEGER)")
            .map_err(|e| e.to_string())?;
        let current: i64 = conn
            .query_row("SELECT coalesce(max(version), 0) FROM schema_migrations", [], |r| r.get(0))
            .map_err(|e| e.to_string())?;
        let target = MIGRATIONS.len() as i64;
        if current >= target {
            return Ok(());
        }
        if current > 0 {
            let bak = self.path.with_extension(format!("sqlite.pre-v{target}-{}", stamp()));
            conn.execute("VACUUM INTO ?1", params![bak.display().to_string()])
                .map_err(|e| format!("Không sao lưu được trước khi nâng cấp ({e})"))?;
        }
        let tx = conn.transaction().map_err(|e| e.to_string())?;
        for (i, sql) in MIGRATIONS.iter().enumerate().skip(current as usize) {
            tx.execute_batch(sql).map_err(|e| format!("Nâng cấp dữ liệu cá nhân lên v{} lỗi ({e})", i + 1))?;
            tx.execute("INSERT INTO schema_migrations VALUES(?1, ?2)", params![i as i64 + 1, now()])
                .map_err(|e| e.to_string())?;
        }
        tx.commit().map_err(|e| e.to_string())
    }

    fn ensure_default_list(&self) -> Result<(), String> {
        let conn = self.conn.lock().unwrap();
        let n: i64 = conn.query_row("SELECT count(*) FROM wordlist", [], |r| r.get(0)).map_err(|e| e.to_string())?;
        if n == 0 {
            conn.execute("INSERT INTO wordlist(name, created) VALUES(?1, ?2)", params![DEFAULT_LIST, now()])
                .map_err(|e| e.to_string())?;
        }
        Ok(())
    }

    // ---------- lịch sử (U29) ----------

    pub fn history_add(&self, key: &str, label: &str, kind: &str) -> Result<(), String> {
        let conn = self.conn.lock().unwrap();
        conn.execute("DELETE FROM history WHERE key = ?1", params![key]).map_err(|e| e.to_string())?;
        conn.execute(
            "INSERT INTO history(key, label, kind, ts) VALUES(?1, ?2, ?3, ?4)",
            params![key, label, kind, now()],
        )
        .map_err(|e| e.to_string())?;
        // giữ 500 mục gần nhất
        conn.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY ts DESC, id DESC LIMIT 500)", [])
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn history(&self, limit: i64) -> Vec<HistoryRow> {
        let conn = self.conn.lock().unwrap();
        conn.prepare("SELECT key, label, kind, ts FROM history ORDER BY ts DESC, id DESC LIMIT ?1")
            .and_then(|mut st| {
                st.query_map(params![limit], |r| {
                    Ok(HistoryRow { key: r.get(0)?, label: r.get(1)?, kind: r.get(2)?, ts: r.get(3)? })
                })
                .map(|rows| rows.flatten().collect())
            })
            .unwrap_or_default()
    }

    pub fn history_clear(&self) -> Result<(), String> {
        self.conn.lock().unwrap().execute("DELETE FROM history", []).map(|_| ()).map_err(|e| e.to_string())
    }

    // ---------- danh sách từ (U30) ----------

    pub fn lists(&self) -> Vec<ListInfo> {
        let conn = self.conn.lock().unwrap();
        conn.prepare(
            "SELECT l.id, l.name, count(i.id) FROM wordlist l LEFT JOIN wordlist_item i ON i.list_id = l.id
             GROUP BY l.id ORDER BY l.created, l.id",
        )
        .and_then(|mut st| {
            st.query_map([], |r| Ok(ListInfo { id: r.get(0)?, name: r.get(1)?, count: r.get(2)? }))
                .map(|rows| rows.flatten().collect())
        })
        .unwrap_or_default()
    }

    fn clean_name(name: &str) -> Result<String, String> {
        let n = name.split_whitespace().collect::<Vec<_>>().join(" ");
        if n.is_empty() {
            return Err("Tên danh sách không được để trống".into());
        }
        if n.chars().count() > 80 {
            return Err("Tên danh sách tối đa 80 ký tự".into());
        }
        Ok(n)
    }

    /// So tên không phân biệt hoa/thường theo Unicode ("Từ của tôi" = "từ của TÔI");
    /// COLLATE NOCASE của SQLite chỉ gộp chữ ASCII nên không đủ cho tiếng Việt.
    fn name_taken(&self, name: &str, except: i64) -> bool {
        let n = name.to_lowercase();
        self.lists().iter().any(|l| l.id != except && l.name.to_lowercase() == n)
    }

    pub fn list_create(&self, name: &str) -> Result<i64, String> {
        let name = Self::clean_name(name)?;
        if self.name_taken(&name, 0) {
            return Err("Đã có danh sách tên này".into());
        }
        let conn = self.conn.lock().unwrap();
        match conn.execute("INSERT INTO wordlist(name, created) VALUES(?1, ?2)", params![name, now()]) {
            Ok(_) => Ok(conn.last_insert_rowid()),
            Err(rusqlite::Error::SqliteFailure(e, _)) if e.code == rusqlite::ErrorCode::ConstraintViolation => {
                Err("Đã có danh sách tên này".into())
            }
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn list_rename(&self, id: i64, name: &str) -> Result<(), String> {
        let name = Self::clean_name(name)?;
        if self.name_taken(&name, id) {
            return Err("Đã có danh sách tên này".into());
        }
        let conn = self.conn.lock().unwrap();
        match conn.execute("UPDATE wordlist SET name = ?2 WHERE id = ?1", params![id, name]) {
            Ok(0) => Err("Danh sách không còn tồn tại".into()),
            Ok(_) => Ok(()),
            Err(rusqlite::Error::SqliteFailure(e, _)) if e.code == rusqlite::ErrorCode::ConstraintViolation => {
                Err("Đã có danh sách tên này".into())
            }
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn list_delete(&self, id: i64) -> Result<(), String> {
        {
            let conn = self.conn.lock().unwrap();
            conn.execute("DELETE FROM wordlist WHERE id = ?1", params![id]).map_err(|e| e.to_string())?;
        }
        self.ensure_default_list()
    }

    pub fn items(&self, list_id: i64) -> Vec<Item> {
        let conn = self.conn.lock().unwrap();
        conn.prepare(
            "SELECT id, word, pos, sense, label, added_at FROM wordlist_item WHERE list_id = ?1 ORDER BY added_at DESC, id DESC",
        )
        .and_then(|mut st| {
            st.query_map(params![list_id], |r| {
                Ok(Item {
                    id: r.get(0)?,
                    word: r.get(1)?,
                    pos: r.get(2)?,
                    sense: r.get(3)?,
                    label: r.get(4)?,
                    added_at: r.get(5)?,
                    exists: true,
                })
            })
            .map(|rows| rows.flatten().collect())
        })
        .unwrap_or_default()
    }

    pub fn item_add(&self, list_id: i64, word: &str, pos: &str, sense: &str, label: &str) -> Result<i64, String> {
        let conn = self.conn.lock().unwrap();
        let exists: Option<i64> = conn
            .query_row("SELECT id FROM wordlist WHERE id = ?1", params![list_id], |r| r.get(0))
            .optional()
            .map_err(|e| e.to_string())?;
        if exists.is_none() {
            return Err("Danh sách không còn tồn tại".into());
        }
        match conn.execute(
            "INSERT INTO wordlist_item(list_id, word, pos, sense, label, added_at) VALUES(?1, ?2, ?3, ?4, ?5, ?6)",
            params![list_id, word, pos, sense, label, now()],
        ) {
            Ok(_) => Ok(conn.last_insert_rowid()),
            Err(rusqlite::Error::SqliteFailure(e, _)) if e.code == rusqlite::ErrorCode::ConstraintViolation => {
                Err("Đã có trong danh sách".into())
            }
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn item_remove(&self, item_id: i64) -> Result<(), String> {
        self.conn
            .lock()
            .unwrap()
            .execute("DELETE FROM wordlist_item WHERE id = ?1", params![item_id])
            .map(|_| ())
            .map_err(|e| e.to_string())
    }

    /// Các khoá "từ|từ loại|nghĩa" đã lưu trong một danh sách (để tô sao trong mục từ).
    pub fn saved_keys(&self, list_id: i64) -> Vec<String> {
        self.items(list_id).into_iter().map(|i| format!("{}|{}|{}", i.word, i.pos, i.sense)).collect()
    }

    // ---------- cài đặt (U28, U32) ----------

    pub fn settings(&self) -> HashMap<String, String> {
        let conn = self.conn.lock().unwrap();
        conn.prepare("SELECT key, value FROM settings")
            .and_then(|mut st| {
                st.query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
                    .map(|rows| rows.flatten().collect())
            })
            .unwrap_or_default()
    }

    pub fn setting_set(&self, key: &str, value: &str) -> Result<(), String> {
        self.conn
            .lock()
            .unwrap()
            .execute(
                "INSERT INTO settings(key, value) VALUES(?1, ?2) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                params![key, value],
            )
            .map(|_| ())
            .map_err(|e| e.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tmp(name: &str) -> PathBuf {
        let p = std::env::temp_dir().join(format!("tudien-test-{name}-{}.sqlite", now()));
        let _ = std::fs::remove_file(&p);
        p
    }

    #[test]
    fn lists_and_duplicates() {
        let p = tmp("lists");
        let (db, notice) = UserDb::open(&p).unwrap();
        assert!(notice.is_none());
        assert_eq!(db.lists().len(), 1);
        let id = db.list_create("IELTS").unwrap();
        assert_eq!(db.list_create("ielts").unwrap_err(), "Đã có danh sách tên này");
        assert_eq!(db.list_create("từ của TÔI").unwrap_err(), "Đã có danh sách tên này");
        db.item_add(id, "bank", "noun", "", "bank").unwrap();
        assert_eq!(db.item_add(id, "bank", "noun", "", "bank").unwrap_err(), "Đã có trong danh sách");
        db.list_delete(id).unwrap();
        assert_eq!(db.lists().len(), 1);
    }

    /// Dữ liệu cá nhân mở bằng đường dẫn thường (không qua URI): phải chạy được cả với dạng \\?\ và
    /// thư mục có dấu cách, ’, #, %; VACUUM INTO (sao lưu trước khi nâng cấp) cũng vậy.
    #[test]
    fn open_from_verbatim_path_with_special_chars() {
        let dir = std::env::temp_dir().join(format!("tudien-test {} user’ #1 50%", now()));
        std::fs::create_dir_all(&dir).unwrap();
        let dir = std::fs::canonicalize(&dir).unwrap();
        let p = dir.join("user.sqlite");
        {
            let (db, notice) = UserDb::open(&p).unwrap();
            assert!(notice.is_none());
            db.list_create("IELTS").unwrap();
            let bak = p.with_extension("sqlite.pre-v9-test");
            db.conn.lock().unwrap().execute("VACUUM INTO ?1", params![bak.display().to_string()]).unwrap();
            assert!(bak.exists());
        }
        let (db, _) = UserDb::open(&p).unwrap();
        assert_eq!(db.lists().len(), 2);
        drop(db);
        assert!(p.exists());
        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn corrupt_file_is_backed_up() {
        let p = tmp("corrupt");
        std::fs::write(&p, b"day khong phai sqlite").unwrap();
        let (db, notice) = UserDb::open(&p).unwrap();
        assert!(notice.unwrap().contains(".bak-"));
        assert_eq!(db.lists().len(), 1);
    }
}
