//! Game lines of the events log (lume-launcher D10), in the format of `event` in logs.sh:
//! `<time> <boot> game <OK|FAIL> <detail>`, appended to `$R36OS_RUN/logs/events.pending`
//! (copied in batches to `ROMS/logs/events.log`). The detail has the system, the runner, the
//! core, the exit code, how it ended and the duration; never the game name or the ROM path.
//!
//! ```text
//! 2026-11-14T18:30:05 44 game OK snes retroarch snes9x start
//! 2026-11-14T18:43:37 44 game OK snes retroarch snes9x exit=0 end=quit-combo secs=812
//! ```

use std::io::Write;
use std::path::{Path, PathBuf};

use crate::launch::Launch;

pub struct Events {
    dir: PathBuf,
}

/// Local time as `YYYY-MM-DDTHH:MM:SS` (what `date '+%Y-%m-%dT%H:%M:%S'` prints).
fn now() -> String {
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

/// A word of the detail: no spaces, never empty.
fn word(s: &str) -> String {
    let w: String = s.chars().map(|c| if c.is_whitespace() { '_' } else { c }).collect();
    if w.is_empty() {
        "-".into()
    } else {
        w
    }
}

pub fn detail_start(l: &Launch) -> String {
    let what = if l.menu { "menu" } else { "start" };
    format!("{} {} {} {what}", word(&l.system), word(&l.runner), word(&l.core))
}

pub fn detail_end(l: &Launch, end: &str, exit: &str, secs: u64) -> String {
    let menu = if l.menu { " menu" } else { "" };
    format!("{} {} {}{menu} exit={exit} end={end} secs={secs}", word(&l.system), word(&l.runner), word(&l.core))
}

impl Events {
    pub fn new(run: &Path) -> Events {
        Events { dir: run.join("logs") }
    }

    fn write(&self, ok: bool, detail: &str) {
        let boot = std::fs::read_to_string(self.dir.join("boot-n")).map(|s| s.trim().to_string()).unwrap_or_else(|_| "0".into());
        let line = format!("{} {} game {} {detail}\n", now(), if boot.is_empty() { "0" } else { &boot }, if ok { "OK" } else { "FAIL" });
        let _ = std::fs::create_dir_all(&self.dir);
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(self.dir.join("events.pending")) {
            let _ = f.write_all(line.as_bytes());
        }
    }

    pub fn game_start(&self, l: &Launch) {
        self.write(true, &detail_start(l));
    }

    pub fn game(&self, ok: bool, l: &Launch, end: &str, exit: &str, secs: u64) {
        self.write(ok, &detail_end(l, end, exit, secs));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::launch::parse;

    #[test]
    fn line_has_no_game_name() {
        let l = parse("system=snes\nrunner=retroarch\ncore=snes9x\npath=Secret Game (USA).sfc\nstates=/storage/states/snes/Secret Game (USA)\narg=/bin/ra\narg=/storage/roms/snes/Secret Game (USA).sfc\n").unwrap();
        let d = detail_end(&l, "quit-combo", "0", 812);
        assert_eq!(d, "snes retroarch snes9x exit=0 end=quit-combo secs=812");
        assert_eq!(detail_start(&l), "snes retroarch snes9x start");
        let native = parse("system=ports\nrunner=sh\narg=/bin/sh\n").unwrap();
        assert_eq!(detail_end(&native, "normal", "sig11", 3), "ports sh - exit=sig11 end=normal secs=3");
    }

    #[test]
    fn appends_in_logs_sh_format() {
        let run = std::env::temp_dir().join(format!("lume-events-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&run);
        std::fs::create_dir_all(run.join("logs")).unwrap();
        std::fs::write(run.join("logs/boot-n"), "44\n").unwrap();
        let ev = Events::new(&run);
        let l = parse("system=nes\nrunner=retroarch\ncore=fceumm\narg=/bin/ra\n").unwrap();
        ev.game_start(&l);
        ev.game(false, &l, "normal", "1", 5);
        let text = std::fs::read_to_string(run.join("logs/events.pending")).unwrap();
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2);
        let f: Vec<&str> = lines[1].splitn(5, ' ').collect();
        assert_eq!(f[0].len(), 19);
        assert_eq!(&f[1..4], ["44", "game", "FAIL"]);
        assert_eq!(f[4], "nes retroarch fceumm exit=1 end=normal secs=5");
    }
}
