//! What the system draws over a game (lume-hud-actions D14, D6; device-fixes 9.14): one
//! `lume-menu --serve PGID` per game, started with the game. It makes its buffers once, as
//! soon as the game has a screen, then waits on its stdin, so nothing runs while the menu,
//! the bar and the hint are off.
//!
//! lume-run writes one line per change ("menu TITLE|...|FOCUS", "menu -", "bar TEXT",
//! "bar -", "hint TEXT", "hint -"). Only the menu answers: "menu ok" once its first picture
//! is on the screen ("menu fail WHY": lume-run falls back to RetroArch's LUME_MENU widget),
//! "menu closed" once the game's picture is back. The end of stdin gives everything back.

use std::os::fd::AsRawFd;
use std::path::Path;
use std::process::{Child, ChildStdin, ChildStdout, Command, Stdio};
use std::time::{Duration, Instant};

/// How long lume-menu has to put the menu on the screen
pub const OPEN_WAIT: Duration = Duration::from_secs(2);
/// How long it has to give the screen back
pub const CLOSE_WAIT: Duration = Duration::from_secs(1);

pub struct SysMenu {
    child: Child,
    stdin: Option<ChildStdin>,
    stdout: Option<ChildStdout>,
    /// bytes read from stdout that do not make a whole line yet
    pending: Vec<u8>,
}

impl SysMenu {
    /// Starts `lume-menu --serve PGID` without waiting for anything.
    pub fn serve(bin: &Path, pgid: libc::pid_t, hints: (&str, &str), warn: &str) -> Result<SysMenu, String> {
        let mut child = Command::new(bin)
            .arg("--serve")
            .arg(pgid.to_string())
            .arg("--hints")
            .arg(format!("{}|{}", hints.0, hints.1))
            .arg("--warn")
            .arg(warn)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("{}: {e}", bin.display()))?;
        let stdin = child.stdin.take();
        let stdout = child.stdout.take();
        Ok(SysMenu { child, stdin, stdout, pending: Vec::new() })
    }

    /// One line to lume-menu; false when it is gone.
    pub fn send(&mut self, line: &str) -> bool {
        use std::io::Write;
        match self.stdin.as_mut() {
            Some(s) => writeln!(s, "{line}").and_then(|_| s.flush()).is_ok(),
            None => false,
        }
    }

    /// Sends `line` and waits up to `wait` for the answer that starts with `tag` (the other
    /// lines are skipped); Err(why) when it does not come.
    pub fn ask(&mut self, line: &str, tag: &str, wait: Duration) -> Result<String, String> {
        if !self.send(line) {
            return Err("lume-menu is gone".into());
        }
        let end = Instant::now() + wait;
        let Some(out) = self.stdout.as_ref().map(|o| o.as_raw_fd()) else { return Err("no answer".into()) };
        loop {
            while let Some(i) = self.pending.iter().position(|&b| b == b'\n') {
                let l: Vec<u8> = self.pending.drain(..=i).collect();
                let l = String::from_utf8_lossy(&l).trim_end().to_string();
                if let Some(rest) = l.strip_prefix(tag) {
                    return Ok(rest.trim_start().to_string());
                }
            }
            let left = end.saturating_duration_since(Instant::now());
            if left.is_zero() || crate::proc::poll(&[out], Some(left)).first() != Some(&true) {
                return Err("no answer".into());
            }
            let mut buf = [0u8; 512];
            let n = unsafe { libc::read(out, buf.as_mut_ptr().cast(), buf.len()) };
            if n <= 0 {
                return Err("lume-menu is gone".into());
            }
            self.pending.extend_from_slice(&buf[..n as usize]);
        }
    }

    /// Closes stdin and waits for lume-menu to give the screen back and end; killed after 1 s.
    pub fn close(mut self) {
        drop(self.stdin.take());
        let end = Instant::now() + CLOSE_WAIT;
        while Instant::now() < end {
            if let Ok(Some(_)) = self.child.try_wait() {
                return;
            }
            std::thread::sleep(Duration::from_millis(10));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
    }

    /// True while the process runs.
    pub fn alive(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(None))
    }
}
