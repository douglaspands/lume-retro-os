//! The runner's actions during a game (lume-hud-actions D3, D10): RetroArch network commands,
//! a key tapped on the virtual device, a signal to the game's group, and the pause.

use std::net::UdpSocket;
use std::os::fd::RawFd;
use std::time::Duration;

use lume_core::runner::ActionForm;

/// How long the pause waits for RetroArch's GET_STATUS (D10)
pub const STATUS_WAIT: Duration = Duration::from_secs(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Status {
    Playing,
    Paused,
    Contentless,
}

/// One UDP command to RetroArch on 127.0.0.1 (the port of QUIT).
pub fn ra_send(port: u16, cmd: &str) {
    if let Ok(s) = UdpSocket::bind("127.0.0.1:0") {
        let _ = s.send_to(cmd.as_bytes(), ("127.0.0.1", port));
    }
}

/// GET_STATUS: "GET_STATUS PLAYING ...", "GET_STATUS PAUSED ..." or "GET_STATUS
/// CONTENTLESS"; None when nothing answers within `wait`.
pub fn ra_status(port: u16, wait: Duration) -> Option<Status> {
    let s = UdpSocket::bind("127.0.0.1:0").ok()?;
    s.set_read_timeout(Some(wait)).ok()?;
    s.send_to(b"GET_STATUS", ("127.0.0.1", port)).ok()?;
    let mut buf = [0u8; 512];
    let (n, _) = s.recv_from(&mut buf).ok()?;
    let reply = String::from_utf8_lossy(&buf[..n]);
    let word = reply.strip_prefix("GET_STATUS")?.split_whitespace().next()?;
    Some(match word {
        "PLAYING" => Status::Playing,
        "PAUSED" => Status::Paused,
        "CONTENTLESS" => Status::Contentless,
        _ => return None,
    })
}

/// Who paused the game for the menu, so the menu undoes only its own pause.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Paused {
    /// the game was already paused (or has no content): nothing to undo
    Already,
    /// PAUSE_TOGGLE by the menu
    Toggle,
    /// SIGSTOP to the game's group (no pause declared, or RetroArch silent)
    Stopped,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PauseResult {
    pub paused: Paused,
    /// the application did not answer its pause: the menu offers "Force close"
    pub unresponsive: bool,
}

/// Pauses the game for the menu (D10). `pause` is the runner's pause action.
pub fn pause(pause: Option<&ActionForm>, port: u16, pgid: libc::pid_t, log: &dyn Fn(&str)) -> PauseResult {
    match pause {
        Some(ActionForm::RetroarchPause) => match ra_status(port, STATUS_WAIT) {
            Some(Status::Playing) => {
                ra_send(port, "PAUSE_TOGGLE");
                if ra_status(port, STATUS_WAIT) != Some(Status::Paused) {
                    log("pause: RetroArch did not report PAUSED after PAUSE_TOGGLE");
                }
                PauseResult { paused: Paused::Toggle, unresponsive: false }
            }
            Some(_) => PauseResult { paused: Paused::Already, unresponsive: false },
            None => {
                log("pause: no answer from RetroArch in 1 s: the game is stopped");
                stop_group(pgid, true);
                PauseResult { paused: Paused::Stopped, unresponsive: true }
            }
        },
        Some(other @ (ActionForm::RetroarchCmd(_) | ActionForm::Key(_) | ActionForm::Signal(_))) => {
            // a pause action of another form toggles; it cannot tell if the game was paused
            log(&format!("pause: {} (no status to check)", other.to_value()));
            PauseResult { paused: Paused::Already, unresponsive: false }
        }
        None => {
            stop_group(pgid, true);
            PauseResult { paused: Paused::Stopped, unresponsive: false }
        }
    }
}

/// Undoes the menu's pause.
pub fn resume(how: Paused, port: u16, pgid: libc::pid_t) {
    match how {
        Paused::Already => {}
        Paused::Toggle => ra_send(port, "PAUSE_TOGGLE"),
        Paused::Stopped => stop_group(pgid, false),
    }
}

fn stop_group(pgid: libc::pid_t, stop: bool) {
    unsafe {
        libc::kill(-pgid, if stop { libc::SIGSTOP } else { libc::SIGCONT });
    }
}

/// Carries out one action by the runner's form; false when the runner does not declare it
/// (the caller logs `action <a> not supported by runner <id>`).
pub fn run(form: Option<&ActionForm>, port: u16, pgid: libc::pid_t, input: Option<RawFd>, log: &dyn Fn(&str)) -> bool {
    match form {
        None => false,
        Some(ActionForm::RetroarchCmd(cmd)) => {
            ra_send(port, cmd);
            true
        }
        Some(ActionForm::Key(key)) => {
            match (input, lume_core::input::tap(key)) {
                (Some(fd), Ok(msg)) => {
                    let sent = unsafe { libc::send(fd, msg.as_ptr().cast(), msg.len(), libc::MSG_NOSIGNAL | libc::MSG_DONTWAIT) };
                    if sent != msg.len() as isize {
                        log(&format!("tap {key} not sent to the input daemon"));
                    }
                }
                (None, _) => log(&format!("tap {key}: no input daemon")),
                (_, Err(e)) => log(&e),
            }
            true
        }
        Some(ActionForm::Signal(name)) => {
            if let Some(sig) = ActionForm::signal_number(name) {
                unsafe { libc::kill(-pgid, sig) };
            }
            true
        }
        Some(ActionForm::RetroarchPause) => {
            // only valid for pause, which goes through pause()
            false
        }
    }
}

/// A message to the input daemon (`capture on`, `capture off`).
pub fn to_daemon(input: Option<RawFd>, msg: &str) {
    if let Some(fd) = input {
        unsafe { libc::send(fd, msg.as_ptr().cast(), msg.len(), libc::MSG_NOSIGNAL | libc::MSG_DONTWAIT) };
    }
}
