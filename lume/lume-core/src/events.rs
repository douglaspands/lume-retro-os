//! Lines of the events log in the format of `event` in logs.sh (docs/LOGS.md):
//! `<time> <boot> <category> <OK|FAIL> <detail>`, appended to
//! `$LUME_RUN/logs/events.pending` (the session creates it writable by the game user).
//! English only, and never a game name or path.

use std::io::Write;
use std::path::PathBuf;

fn logs_dir() -> PathBuf {
    std::env::var_os("LUME_RUN").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/run/lume")).join("logs")
}

/// Local time as `YYYY-MM-DDTHH:MM:SS`.
pub fn now() -> String {
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!(
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
            tm.tm_year + 1900,
            tm.tm_mon + 1,
            tm.tm_mday,
            tm.tm_hour,
            tm.tm_min,
            tm.tm_sec
        )
    }
}

/// Appends one event; errors are ignored (logs never stop the launcher).
pub fn append(category: &str, ok: bool, detail: &str) {
    let dir = logs_dir();
    let boot = std::fs::read_to_string(dir.join("boot-n")).map(|s| s.trim().to_string()).unwrap_or_default();
    let boot = if boot.is_empty() { "0".to_string() } else { boot };
    let line = format!("{} {boot} {category} {} {detail}\n", now(), if ok { "OK" } else { "FAIL" });
    let _ = std::fs::create_dir_all(&dir);
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(dir.join("events.pending")) {
        let _ = f.write_all(line.as_bytes());
    }
}
