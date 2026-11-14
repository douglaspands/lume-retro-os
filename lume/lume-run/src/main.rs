//! lume-run: the supervisor of the lume-launcher (lume-launcher D1, D9, D10).
//!
//! ```text
//! loop:
//!   run lume-ui      exit 0  -> exit 0 (the session powers off)
//!                    exit 64 -> run the game of $XDG_RUNTIME_DIR/lume/launch, then loop
//!                    exit 65 -> same, the RetroArch menu without a game
//!                    other   -> exit 1 (a frontend failure for the session)
//! ```
//!
//! A game runs in its own cgroup and session. Fn+Start reaches lume-run as `quit` on the
//! input daemon socket: first the polite request of the runner (RetroArch's network QUIT, or
//! SIGTERM to the game's process group), then, after the runner timeout, `cgroup.kill`. A
//! game that ends in any way never ends lume-run.
//!
//! Environment (defaults in parentheses): LUME_UI (/usr/bin/lume-ui), LUME_INDEX
//! (/usr/bin/lume-index), LUME_CGROUP (/sys/fs/cgroup/lume), LUME_INPUT_SOCK
//! (/run/r36os/input.sock), LUME_RA_PORT (55355), R36OS_RUN (/run/r36os), XDG_RUNTIME_DIR.

mod events;
mod launch;
mod proc;
mod states;

use std::net::UdpSocket;
use std::os::fd::{AsRawFd, OwnedFd};
use std::path::PathBuf;
use std::process::ExitCode;
use std::time::{Duration, Instant};

use launch::{Launch, Quit};
use proc::Exit;

const PROG: &str = "lume-run";
const EXIT_LAUNCH: i32 = 64;
const EXIT_MENU: i32 = 65;
/// After cgroup.kill, how long the cgroup may take to empty
const KILL_GRACE: Duration = Duration::from_secs(2);
/// Gap between the two QUIT commands (RetroArch's quit_press_twice wants a second one)
const QUIT_GAP: Duration = Duration::from_millis(200);

fn log(msg: &str) {
    eprintln!("{PROG}: {msg}");
}

fn env_path(var: &str, default: &str) -> PathBuf {
    std::env::var_os(var).map(PathBuf::from).unwrap_or_else(|| PathBuf::from(default))
}

struct Run {
    ui: PathBuf,
    index: PathBuf,
    cgroup_base: PathBuf,
    input_sock: PathBuf,
    ra_port: u16,
    runtime: PathBuf,
    events: events::Events,
    sig: OwnedFd,
    games: u64,
    helpers: Vec<libc::pid_t>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum End {
    Normal,
    QuitCombo,
    Killed,
    Session,
}

impl End {
    fn as_str(self) -> &'static str {
        match self {
            End::Normal => "normal",
            End::QuitCombo => "quit-combo",
            End::Killed => "killed",
            End::Session => "session",
        }
    }
}

fn polite_quit(l: &Launch, pid: libc::pid_t, port: u16) {
    match l.quit {
        Quit::RetroarchCmd => {
            // QUIT goes through RetroArch's quit hotkey path, so with quit_press_twice the
            // first one only shows "press again" (design, checks of task 1.2)
            if let Ok(s) = UdpSocket::bind("127.0.0.1:0") {
                let _ = s.send_to(b"QUIT", ("127.0.0.1", port));
                std::thread::sleep(QUIT_GAP);
                let _ = s.send_to(b"QUIT", ("127.0.0.1", port));
            }
        }
        Quit::Sigterm => proc::kill_group(pid, libc::SIGTERM),
    }
}

impl Run {
    fn from_env() -> std::io::Result<Run> {
        let runtime = match std::env::var_os("XDG_RUNTIME_DIR") {
            Some(d) => PathBuf::from(d).join("lume"),
            None => PathBuf::from("/tmp/lume"),
        };
        std::fs::create_dir_all(&runtime)?;
        // every child knows it was opened by the launcher: the RetroArch frontend script
        // then labels "Quit" as going back to the game list (aports/retroarch patch 0010).
        // Set before any thread or child exists.
        std::env::set_var("LUME_LAUNCHER", "1");
        Ok(Run {
            ui: env_path("LUME_UI", "/usr/bin/lume-ui"),
            index: env_path("LUME_INDEX", "/usr/bin/lume-index"),
            cgroup_base: env_path("LUME_CGROUP", "/sys/fs/cgroup/lume"),
            input_sock: env_path("LUME_INPUT_SOCK", "/run/r36os/input.sock"),
            ra_port: std::env::var("LUME_RA_PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(55355),
            events: events::Events::new(&env_path("R36OS_RUN", "/run/r36os")),
            sig: proc::signal_fd()?,
            games: 0,
            helpers: Vec::new(),
            runtime,
        })
    }

    fn status(&self, s: &str) {
        // read by r36os-logd for the frontend state (ui, game:<runner>)
        let _ = std::fs::write(self.runtime.join("status"), format!("{s}\n"));
    }

    fn signalled(&self) -> bool {
        let mut buf = [0u8; 128];
        unsafe { libc::read(self.sig.as_raw_fd(), buf.as_mut_ptr().cast(), buf.len()) > 0 }
    }

    /// Runs the interface; None when the session asked us to stop.
    fn run_ui(&mut self) -> Option<Exit> {
        self.status("ui");
        let child = match proc::spawn(&[self.ui.to_string_lossy().into_owned()]) {
            Ok(c) => c,
            Err(e) => {
                log(&format!("interface not started: {e}"));
                return Some(Exit::Code(127));
            }
        };
        loop {
            proc::reap_some(&mut self.helpers);
            let r = proc::poll(&[child.pidfd.as_raw_fd(), self.sig.as_raw_fd()], None);
            if r[0] {
                return Some(proc::reap(child.pid));
            }
            if r[1] && self.signalled() {
                unsafe { libc::kill(child.pid, libc::SIGTERM) };
                let _ = proc::poll(&[child.pidfd.as_raw_fd()], Some(Duration::from_secs(3)));
                unsafe { libc::kill(child.pid, libc::SIGKILL) };
                proc::reap(child.pid);
                return None;
            }
        }
    }

    /// Runs one game to its end; false when the session asked us to stop.
    fn run_game(&mut self, l: &Launch) -> bool {
        self.games += 1;
        let cg = proc::GameCgroup::create(&self.cgroup_base, self.games);
        let before = states::snapshot(&l.states);
        let started = Instant::now();
        let spawned = proc::spawn_game(&l.argv, cg.as_ref().map(|c| c.dir.as_path()));
        let (child, in_cgroup) = match spawned {
            Ok(c) => c,
            Err(e) => {
                log(&format!("game not started ({}): {e}", l.runner));
                self.events.game(false, l, "start-failed", "error", 0);
                return true;
            }
        };
        let cg = if in_cgroup { cg } else { None };
        if cg.is_none() {
            log("cgroup unavailable: the forced end falls back to the process group");
        }
        self.status(&format!("game:{}", l.runner));
        self.events.game_start(l);
        let input = proc::connect_input(&self.input_sock);
        if input.is_none() {
            log("no input daemon: Fn+Start does not end this game");
        }
        let mut end = End::Normal;
        let mut deadline: Option<Instant> = None;
        let mut session_stop = false;
        let exit = loop {
            let mut fds = vec![child.pidfd.as_raw_fd(), self.sig.as_raw_fd()];
            if let Some(i) = &input {
                fds.push(i.as_raw_fd());
            }
            let wait = deadline.map(|d| d.saturating_duration_since(Instant::now()));
            let r = proc::poll(&fds, wait);
            if r[0] {
                break proc::reap(child.pid);
            }
            let mut quit = false;
            if r[1] && self.signalled() {
                session_stop = true;
                end = End::Session;
                quit = true;
            }
            if r.get(2) == Some(&true) {
                match input.as_ref().and_then(|i| proc::read_message(i.as_raw_fd())) {
                    Some(m) if m == "quit" && deadline.is_none() => {
                        end = End::QuitCombo;
                        quit = true;
                    }
                    Some(_) => {}
                    // daemon gone: keep the game running without the combo
                    None => {}
                }
            }
            if quit && deadline.is_none() {
                log(&format!("{}: asking the game to end ({})", end.as_str(), l.runner));
                polite_quit(l, child.pid, self.ra_port);
                deadline = Some(Instant::now() + Duration::from_secs(l.timeout as u64));
            }
            if deadline.is_some_and(|d| Instant::now() >= d) {
                log(&format!("the game did not end in {} s: killing it", l.timeout));
                end = if end == End::Session { End::Session } else { End::Killed };
                self.force_kill(cg.as_ref(), child.pid);
                break proc::reap(child.pid);
            }
        };
        drop(input);
        // whatever the game left behind (a daemon started by a script) ends with it
        match &cg {
            Some(c) if c.populated() => {
                if !c.kill() {
                    log("cgroup.kill unavailable: killing the process group");
                    proc::kill_group(child.pid, libc::SIGKILL);
                }
                if !c.wait_empty(KILL_GRACE) {
                    log("game cgroup still populated after the kill");
                }
            }
            Some(_) => {}
            None => proc::kill_group(child.pid, libc::SIGKILL),
        }
        drop(cg);
        let secs = started.elapsed().as_secs();
        let ok = matches!(exit, Exit::Code(0)) || end == End::QuitCombo;
        self.events.game(ok, l, end.as_str(), &exit.describe(), secs);
        if !l.menu && !l.path.is_empty() {
            self.touch(l, &states::changed(&l.states, &before));
        }
        !session_stop
    }

    fn force_kill(&self, cg: Option<&proc::GameCgroup>, pid: libc::pid_t) {
        match cg {
            Some(c) if c.kill() => {}
            _ => {
                log("cgroup unavailable: killing the process group");
                proc::kill_group(pid, libc::SIGKILL);
            }
        }
    }

    /// playcount, lastplayed and the core of the changed save state slots, in the background.
    fn touch(&mut self, l: &Launch, slots: &[String]) {
        let mut argv = vec![self.index.to_string_lossy().into_owned(), "--touch".into(), l.system.clone(), l.path.clone()];
        if !l.core.is_empty() && !slots.is_empty() {
            argv.push("--core".into());
            argv.push(l.core.clone());
            argv.push("--slots".into());
            argv.push(slots.join(","));
        }
        match proc::spawn(&argv) {
            Ok(c) => self.helpers.push(c.pid),
            Err(e) => log(&format!("lume-index --touch not started: {e}")),
        }
    }
}

fn main() -> ExitCode {
    let mut run = match Run::from_env() {
        Ok(r) => r,
        Err(e) => {
            log(&format!("cannot start: {e}"));
            return ExitCode::FAILURE;
        }
    };
    loop {
        let Some(exit) = run.run_ui() else {
            return ExitCode::SUCCESS;
        };
        let code = match exit {
            Exit::Code(0) => {
                run.status("off");
                return ExitCode::SUCCESS;
            }
            Exit::Code(c @ (EXIT_LAUNCH | EXIT_MENU)) => c,
            other => {
                log(&format!("interface ended with {}", other.describe()));
                return ExitCode::FAILURE;
            }
        };
        let file = run.runtime.join("launch");
        let parsed = std::fs::read_to_string(&file).map_err(|e| e.to_string()).and_then(|t| launch::parse(&t));
        let _ = std::fs::remove_file(&file);
        match parsed {
            Ok(mut l) => {
                l.menu |= code == EXIT_MENU;
                if !run.run_game(&l) {
                    return ExitCode::SUCCESS;
                }
            }
            Err(e) => log(&format!("launch request refused: {e}")),
        }
    }
}
