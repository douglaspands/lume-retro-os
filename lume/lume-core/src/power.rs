//! Writer of the power FIFO `/run/r36os/power` (openspec game-governor, D1/D2).
//!
//! Protocol: one message per line, `menu`, `idle`, `game <system> <core> [<key>]`, `end` or
//! `reload`. `<key>` is [`game_key`] of the ROM (D18): a per-game profile without the name.
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
    /// `key` is [`game_key`] of the ROM; empty = no per-game profile (3-word line).
    Game { system: String, core: String, key: String },
    End,
    /// Read the profile files again and reapply the profile of the current scenario.
    Reload,
}

impl Message {
    /// The wire line, with the final newline. Whitespace inside `system` and `core` becomes `_`
    /// (an empty value becomes `-`), so a message is always exactly one line of 1, 3 or 4 words
    /// (the key is only sent when it is a valid one).
    pub fn line(&self) -> String {
        fn word(s: &str) -> String {
            let w: String = s.chars().map(|c| if c.is_whitespace() || c.is_control() { '_' } else { c }).collect();
            if w.is_empty() { "-".to_string() } else { w }
        }
        match self {
            Message::Menu => "menu\n".to_string(),
            Message::Idle => "idle\n".to_string(),
            Message::Game { system, core, key } if is_game_key(key) => {
                format!("game {} {} {}\n", word(system), word(core), key)
            }
            Message::Game { system, core, .. } => format!("game {} {}\n", word(system), word(core)),
            Message::End => "end\n".to_string(),
            Message::Reload => "reload\n".to_string(),
        }
    }
}

/// The roms root that per-game keys are relative to (`ROMS/roms/`).
pub const ROMS_ROOT: &str = "/storage/roms/";

/// Key of one game for a per-game power profile (openspec game-governor D18): FNV-1a 64 of the
/// ROM path relative to `ROMS/roms/` (the whole path when it is elsewhere), as 16 lowercase hex
/// digits. Stable across boots and builds, and it never carries the game's name.
pub fn game_key(rom_path: &str) -> String {
    let rel = rom_path.strip_prefix(ROMS_ROOT).unwrap_or(rom_path);
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    for b in rel.as_bytes() {
        h ^= u64::from(*b);
        h = h.wrapping_mul(0x0000_0100_0000_01b3);
    }
    format!("{h:016x}")
}

/// `true` for exactly 16 lowercase hex digits (the shell side checks the same).
pub fn is_game_key(s: &str) -> bool {
    s.len() == 16 && s.bytes().all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
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
        assert_eq!(
            Message::Game { system: "snes".into(), core: "snes9x2005_plus".into(), key: String::new() }.line(),
            "game snes snes9x2005_plus\n"
        );
        let key = game_key("/storage/roms/snes/x.sfc");
        assert_eq!(
            Message::Game { system: "snes".into(), core: "snes9x2005_plus".into(), key: key.clone() }.line(),
            format!("game snes snes9x2005_plus {key}\n")
        );
    }

    #[test]
    fn game_line_is_always_three_or_four_words() {
        let m = Message::Game { system: "a b\n".into(), core: String::new(), key: "not a key".into() };
        assert_eq!(m.line(), "game a_b_ -\n");
    }

    #[test]
    fn game_key_is_stable_relative_and_nameless() {
        // FNV-1a 64 reference values
        assert_eq!(game_key(""), "cbf29ce484222325");
        assert_eq!(game_key("a"), "af63dc4c8601ec8c");
        // relative to ROMS/roms/: the same game gives the same key from either form
        assert_eq!(game_key("/storage/roms/gba/Some Game.gba"), game_key("gba/Some Game.gba"));
        assert_ne!(game_key("gba/a.gba"), game_key("gba/b.gba"));
        let k = game_key("/storage/roms/gba/Some Game.gba");
        assert!(is_game_key(&k) && !k.contains("Some"));
        assert!(!is_game_key("0123456789ABCDEF") && !is_game_key("0123") && is_game_key("0123456789abcdef"));
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
        send_to(&p, &Message::Game { system: "nes".into(), core: "fceumm".into(), key: String::new() }).unwrap();
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
