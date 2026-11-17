//! Writer of the power FIFO `/run/r36os/power` (openspec game-governor, D1/D2).
//!
//! Protocol: one message per line, `menu`, `idle`, `game <system> <core>`, `end` or `reload`.
//! The writer opens the FIFO with `O_NONBLOCK` and never creates it: without the service (no
//! reader, no FIFO, full pipe) the message is dropped and the caller goes on. A game or the
//! launcher never waits for the power service. English only, and never a game name or path.

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;
use std::path::PathBuf;

/// One scenario change.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Message {
    Menu,
    Idle,
    Game { system: String, core: String },
    End,
    /// Read the profile files again and reapply the profile of the current scenario.
    Reload,
}

impl Message {
    /// The wire line, with the final newline. Whitespace inside `system` and `core` becomes `_`
    /// (an empty value becomes `-`), so a message is always exactly one line of 1 or 3 words.
    pub fn line(&self) -> String {
        fn word(s: &str) -> String {
            let w: String = s.chars().map(|c| if c.is_whitespace() || c.is_control() { '_' } else { c }).collect();
            if w.is_empty() { "-".to_string() } else { w }
        }
        match self {
            Message::Menu => "menu\n".to_string(),
            Message::Idle => "idle\n".to_string(),
            Message::Game { system, core } => format!("game {} {}\n", word(system), word(core)),
            Message::End => "end\n".to_string(),
            Message::Reload => "reload\n".to_string(),
        }
    }
}

/// Path of the FIFO: `$R36OS_RUN/power` (default `/run/r36os/power`).
pub fn fifo_path() -> PathBuf {
    std::env::var_os("R36OS_RUN").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/run/r36os")).join("power")
}

/// Writes the message to `path` without blocking. Errors mean "not delivered" (no FIFO, no
/// reader, full pipe); they are returned only so tests can tell.
pub fn send_to(path: &std::path::Path, msg: &Message) -> std::io::Result<()> {
    let mut f = std::fs::OpenOptions::new().write(true).custom_flags(libc::O_NONBLOCK).open(path)?;
    // one write of at most PIPE_BUF bytes is atomic: lines of concurrent writers never mix
    f.write_all(msg.line().as_bytes())
}

/// Tells the power service the scenario changed; every failure is ignored.
pub fn notify(msg: &Message) {
    let _ = send_to(&fifo_path(), msg);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CString;
    use std::io::Read;
    use std::os::unix::ffi::OsStrExt;
    use std::path::Path;
    use std::time::{Duration, Instant};

    fn mkfifo(p: &Path) {
        let c = CString::new(p.as_os_str().as_bytes()).unwrap();
        assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o660) }, 0);
    }

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-power-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn lines_follow_the_protocol() {
        assert_eq!(Message::Menu.line(), "menu\n");
        assert_eq!(Message::Idle.line(), "idle\n");
        assert_eq!(Message::End.line(), "end\n");
        assert_eq!(Message::Reload.line(), "reload\n");
        assert_eq!(Message::Game { system: "snes".into(), core: "snes9x2005_plus".into() }.line(), "game snes snes9x2005_plus\n");
    }

    #[test]
    fn game_line_is_always_three_words() {
        let m = Message::Game { system: "a b\n".into(), core: String::new() };
        assert_eq!(m.line(), "game a_b_ -\n");
    }

    #[test]
    fn fifo_without_reader_neither_blocks_nor_fails_the_caller() {
        let d = tmpdir("noreader");
        let p = d.join("power");
        mkfifo(&p);
        let t = Instant::now();
        assert!(send_to(&p, &Message::Menu).is_err()); // ENXIO: reported, not blocked
        assert!(t.elapsed() < Duration::from_secs(1));
        // notify() through the environment-less default path must not panic either
        notify(&Message::End);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn missing_fifo_is_ignored_and_not_created() {
        let d = tmpdir("missing");
        let p = d.join("power");
        assert!(send_to(&p, &Message::Idle).is_err());
        assert!(!p.exists());
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn message_reaches_a_reader() {
        let d = tmpdir("reader");
        let p = d.join("power");
        mkfifo(&p);
        let mut r = std::fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK).open(&p).unwrap();
        send_to(&p, &Message::Game { system: "nes".into(), core: "fceumm".into() }).unwrap();
        send_to(&p, &Message::End).unwrap();
        let mut s = String::new();
        r.read_to_string(&mut s).ok();
        assert_eq!(s, "game nes fceumm\nend\n");
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn full_pipe_does_not_block() {
        let d = tmpdir("full");
        let p = d.join("power");
        mkfifo(&p);
        let _r = std::fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK).open(&p).unwrap();
        let t = Instant::now();
        for _ in 0..100_000 {
            if send_to(&p, &Message::Idle).is_err() {
                break;
            }
        }
        assert!(t.elapsed() < Duration::from_secs(5));
        let _ = std::fs::remove_dir_all(&d);
    }
}
