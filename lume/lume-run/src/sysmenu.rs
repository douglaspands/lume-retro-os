//! The system-drawn Lume menu (lume-hud-actions D14): lume-run starts `lume-menu PGID` only
//! while the menu is open, with the game paused and its group stopped, and sends it one line
//! per change on stdin. "ok" on its stdout means the menu is on the screen; anything else and
//! lume-run falls back to RetroArch's LUME_MENU widget. Closing stdin makes lume-menu give the
//! game's framebuffer back and exit.

use std::io::{BufRead, BufReader, Write};
use std::os::fd::AsRawFd;
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::time::{Duration, Instant};

/// How long lume-menu has to put the menu on the screen
const START_WAIT: Duration = Duration::from_secs(2);
/// How long it has to give the screen back and exit
const CLOSE_WAIT: Duration = Duration::from_secs(1);

pub struct SysMenu {
    child: Child,
    stdin: Option<ChildStdin>,
}

impl SysMenu {
    /// Starts lume-menu on the game's group with the first state; Err(why) when it did not
    /// say "ok" in time (it is killed then).
    pub fn start(bin: &Path, pgid: libc::pid_t, hints: (&str, &str), warn: &str, first: &str) -> Result<SysMenu, String> {
        let mut child = Command::new(bin)
            .arg(pgid.to_string())
            .arg("--hints")
            .arg(format!("{}|{}", hints.0, hints.1))
            .arg("--warn")
            .arg(warn)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("{}: {e}", bin.display()))?;
        let mut stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let sent = stdin.as_mut().map(|s| writeln!(s, "{first}").and_then(|_| s.flush()).is_ok()).unwrap_or(false);
        let mut answer = String::new();
        if let (true, Some(out)) = (sent, stdout) {
            let ready = crate::proc::poll(&[out.as_raw_fd()], Some(START_WAIT));
            if ready.first() == Some(&true) {
                let _ = BufReader::new(out).read_line(&mut answer);
            }
        }
        let answer = answer.trim().to_string();
        if answer == "ok" {
            return Ok(SysMenu { child, stdin });
        }
        let _ = child.kill();
        let _ = child.wait();
        Err(if answer.is_empty() { "no answer".into() } else { answer })
    }

    /// Starts `lume-menu --hud PGID` with the first text of the status bar (D6: drawn by the
    /// system over any game); Err(why) when it did not say "ok" in time.
    pub fn start_hud(bin: &Path, pgid: libc::pid_t, first: &str) -> Result<SysMenu, String> {
        let mut child = Command::new(bin)
            .arg("--hud")
            .arg(pgid.to_string())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .spawn()
            .map_err(|e| format!("{}: {e}", bin.display()))?;
        let mut stdin = child.stdin.take();
        let stdout = child.stdout.take();
        let sent = stdin.as_mut().map(|s| writeln!(s, "{first}").and_then(|_| s.flush()).is_ok()).unwrap_or(false);
        let mut answer = String::new();
        if let (true, Some(out)) = (sent, stdout) {
            let ready = crate::proc::poll(&[out.as_raw_fd()], Some(START_WAIT));
            if ready.first() == Some(&true) {
                let _ = BufReader::new(out).read_line(&mut answer);
            }
        }
        let answer = answer.trim().to_string();
        if answer == "ok" {
            return Ok(SysMenu { child, stdin });
        }
        let _ = child.kill();
        let _ = child.wait();
        Err(if answer.is_empty() { "no answer".into() } else { answer })
    }

    /// The new state; false when lume-menu is gone.
    pub fn update(&mut self, line: &str) -> bool {
        match self.stdin.as_mut() {
            Some(s) => writeln!(s, "{line}").and_then(|_| s.flush()).is_ok(),
            None => false,
        }
    }

    /// Closes stdin and waits for lume-menu to give the screen back; killed after 1 s.
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
}
