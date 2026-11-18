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
//! The other Fn gestures and chords (lume-hud-actions) arrive on the same socket: the
//! runner's actions (actions.rs), the Lume menu and the chord hint (menu.rs), the status bar
//! (hud.rs). The game loop waits without a timeout unless the quit deadline, the bar, the
//! menu or the hint need a tick (1 s).
//!
//! Environment (defaults in parentheses): LUME_UI (/usr/bin/lume-ui), LUME_INDEX
//! (/usr/bin/lume-index), LUME_CGROUP (/sys/fs/cgroup/lume), LUME_INPUT_SOCK
//! (/run/r36os/input.sock), LUME_RA_PORT (55355), R36OS_RUN (/run/r36os), XDG_RUNTIME_DIR.

mod actions;
mod events;
mod hud;
mod launch;
mod menu;
mod proc;
mod states;
mod sysmenu;

use std::net::UdpSocket;
use std::os::fd::{AsRawFd, OwnedFd, RawFd};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::time::{Duration, Instant};

use launch::{Launch, Quit};
use lume_core::input::{Action, Message};
use proc::Exit;

/// The tick of the bar, the menu and the hint (their widgets vanish after 3 s without one)
const TICK: Duration = Duration::from_secs(1);

const PROG: &str = "lume-run";
const EXIT_LAUNCH: i32 = 64;
const EXIT_MENU: i32 = 65;
/// After cgroup.kill, how long the cgroup may take to empty
const KILL_GRACE: Duration = Duration::from_secs(2);

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
    /// an end the menu asked for while carrying out its effects
    pending_end: std::cell::Cell<Option<End>>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum End {
    Normal,
    QuitCombo,
    /// "End game" of the Lume menu
    MenuQuit,
    /// "Force close" of the Lume menu (the application did not answer)
    ForceClose,
    Killed,
    Session,
}

impl End {
    fn as_str(self) -> &'static str {
        match self {
            End::Normal => "normal",
            End::QuitCombo => "quit-combo",
            End::MenuQuit => "menu-quit",
            End::ForceClose => "force-close",
            End::Killed => "killed",
            End::Session => "session",
        }
    }
}

/// What is on the screen over the game: the Lume menu, the chord hint, the status bar.
struct Overlay {
    menu: menu::Menu,
    /// how the menu paused the game (None: not paused by the menu)
    paused: Option<actions::Paused>,
    hint: Option<String>,
    hud: Option<(hud::Hud, Instant)>,
    /// `lume-menu --hud`, the bar drawn by the system over any game (None: not on the screen
    /// yet; the next tick tries again, a game may not have a screen in its first second)
    bar: Option<sysmenu::SysMenu>,
    /// `lume-menu --hint`, the chord hint while Fn is held
    hint_proc: Option<sysmenu::SysMenu>,
    /// `lume-menu --shot` of Fn+Y still writing its picture
    shots: Vec<std::process::Child>,
    lang: String,
    /// the menu drawn by the system (lume-menu, D14), while it is open
    sysmenu: Option<sysmenu::SysMenu>,
    /// the group was stopped for the system-drawn menu (SIGCONT when it closes)
    stopped_for_menu: bool,
}

/// Local time as `YYMMDD-HHMMSS`, the suffix of a screenshot's name (RetroArch's own style,
/// so the pictures of both ways sort together).
fn stamp() -> String {
    unsafe {
        let t = libc::time(std::ptr::null_mut());
        let mut tm: libc::tm = std::mem::zeroed();
        libc::localtime_r(&t, &mut tm);
        format!("{:02}{:02}{:02}-{:02}{:02}{:02}", tm.tm_year % 100, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
    }
}

/// The game's title for the menu: the ROM's name without folder and extension.
fn game_title(l: &Launch) -> String {
    Path::new(&l.path).file_stem().map(|s| s.to_string_lossy().into_owned()).unwrap_or_else(|| l.system.clone())
}

fn polite_quit(l: &Launch, pid: libc::pid_t, port: u16) {
    match l.quit {
        Quit::RetroarchCmd => {
            // one QUIT: opened by the launcher, RetroArch runs with quit_press_twice off (the
            // frontend script), so it ends at once with no "press again" on the screen
            if let Ok(s) = UdpSocket::bind("127.0.0.1:0") {
                let _ = s.send_to(b"QUIT", ("127.0.0.1", port));
            }
        }
        Quit::Sigterm => proc::kill_group(pid, libc::SIGTERM),
    }
}

/// `game <system> <core>` to the power FIFO; a native runner has no core, so the runner id
/// stands in (as in the events log). The menu is not a game: the launcher owns that scenario.
fn power_game(l: &Launch) {
    if l.menu {
        return;
    }
    let core = if l.core.is_empty() { l.runner.clone() } else { l.core.clone() };
    lume_core::power::notify(&lume_core::power::Message::Game { system: l.system.clone(), core });
}

/// `end` to the power FIFO, once the game's cgroup is empty.
fn power_end(l: &Launch) {
    if !l.menu {
        lume_core::power::notify(&lume_core::power::Message::End);
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
            pending_end: std::cell::Cell::new(None),
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
        // power service: the scenario changes before the game's exec (non-blocking, never fails)
        power_game(l);
        let spawned = proc::spawn_game(&l.argv, cg.as_ref().map(|c| c.dir.as_path()));
        let (child, in_cgroup) = match spawned {
            Ok(c) => c,
            Err(e) => {
                log(&format!("game not started ({}): {e}", l.runner));
                power_end(l);
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
        let mut input = proc::connect_input(&self.input_sock);
        if input.is_none() {
            log("no input daemon: Fn+Start does not end this game");
        }
        let lang = lume_core::gametext::language(&lume_core::paths::card());
        let app = lume_core::gametext::app_name(&l.runner);
        let mut ov = Overlay {
            menu: menu::Menu::new(&lang, &app, &game_title(l), l.action("reset").is_some(), l.action("app_menu").is_some()),
            paused: None,
            hint: None,
            hud: None,
            bar: None,
            hint_proc: None,
            shots: Vec::new(),
            lang,
            sysmenu: None,
            stopped_for_menu: false,
        };
        // the bar stays on from one game to the next (D6), in any runner: the system draws it
        if !l.menu && hud::load_shown(&self.hud_file()) {
            self.hud_show(&mut ov, child.pid, true);
        }
        let mut end = End::Normal;
        let mut deadline: Option<Instant> = None;
        let mut session_stop = false;
        let mut next_tick = Instant::now() + TICK;
        let exit = loop {
            let mut fds = vec![child.pidfd.as_raw_fd(), self.sig.as_raw_fd()];
            if let Some(i) = &input {
                fds.push(i.as_raw_fd());
            }
            let ticking = ov.hud.is_some() || ov.menu.is_open() || ov.hint.is_some();
            let wake = match (deadline, ticking) {
                (Some(d), true) => Some(d.min(next_tick)),
                (Some(d), false) => Some(d),
                (None, true) => Some(next_tick),
                (None, false) => None,
            };
            let wait = wake.map(|d| d.saturating_duration_since(Instant::now()));
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
                let fd = input.as_ref().map(|i| i.as_raw_fd());
                match fd.and_then(proc::read_message) {
                    Some(m) => match lume_core::input::parse(&m) {
                        Some(msg) if deadline.is_none() => {
                            match self.on_message(msg, l, child.pid, fd, &mut ov) {
                                Some(e @ (End::QuitCombo | End::MenuQuit)) => {
                                    end = e;
                                    quit = true;
                                }
                                Some(End::ForceClose) => {
                                    log("force close: the application did not answer");
                                    end = End::ForceClose;
                                    self.force_kill(cg.as_ref(), child.pid);
                                    break proc::reap(child.pid);
                                }
                                _ => {}
                            }
                        }
                        _ => {}
                    },
                    // daemon gone: keep the game running without the chords
                    None => {
                        log("input daemon gone: the Fn chords do nothing in this game");
                        input = None;
                    }
                }
            }
            if quit && deadline.is_none() {
                self.close_overlays(l, child.pid, input.as_ref().map(|i| i.as_raw_fd()), &mut ov);
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
            if Instant::now() >= next_tick {
                self.tick(&mut ov, child.pid, input.as_ref().map(|i| i.as_raw_fd()));
                next_tick = Instant::now() + TICK;
            }
        };
        // first of all: lume-menu --hud holds a copy of the game's DRM file, which keeps the
        // screen's master open until it is closed (the launcher could not take the screen)
        if let Some(b) = ov.bar.take() {
            b.close();
        }
        if let Some(p) = ov.hint_proc.take() {
            p.close();
        }
        // a picture of Fn+Y still being written holds the game's DRM file too
        for mut c in ov.shots.drain(..) {
            let _ = c.wait();
        }
        if ov.hud.is_some() {
            hud::panfrost_profiling(Path::new("/"), false);
        }
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
        // the cgroup is empty (or given up on): every end path of a started game comes here
        power_end(l);
        let secs = started.elapsed().as_secs();
        let ok = matches!(exit, Exit::Code(0)) || end == End::QuitCombo || end == End::MenuQuit;
        self.events.game(ok, l, end.as_str(), &exit.describe(), secs);
        if !l.menu && !l.path.is_empty() {
            self.touch(l, &states::changed(&l.states, &before));
        }
        !session_stop
    }

    /// The bar's state across games (D6); in the runtime folder, which the boot empties.
    fn hud_file(&self) -> PathBuf {
        self.runtime.join("hud")
    }

    fn ra(&self, cmd: &str) {
        actions::ra_send(self.ra_port, cmd);
    }

    /// The status bar on or off (D6). Everything on it comes from the system (the user,
    /// 2026-11-17: no number and no drawing from the emulator, other emulators come later):
    /// lume-run samples it and `lume-menu --hud` draws it on an overlay plane over the game.
    fn hud_show(&self, ov: &mut Overlay, pid: libc::pid_t, on: bool) {
        if on {
            hud::panfrost_profiling(Path::new("/"), true);
            let mut h = hud::Hud::new(Path::new("/"), pid);
            let text = h.sample(0.0);
            ov.hud = Some((h, Instant::now()));
            self.bar_text(ov, pid, &text);
        } else {
            ov.hud = None;
            if let Some(b) = ov.bar.take() {
                b.close();
            }
            hud::panfrost_profiling(Path::new("/"), false);
        }
    }

    /// One text of the bar: to lume-menu --hud, started when it is not running yet (a game
    /// with no screen yet, or a lume-menu that ended: the next second tries again).
    fn bar_text(&self, ov: &mut Overlay, pid: libc::pid_t, text: &str) {
        if let Some(b) = ov.bar.as_mut() {
            if b.update(text) {
                return;
            }
            log("status bar: lume-menu --hud ended");
            ov.bar = None;
        }
        let Some(bin) = self.menu_bin() else {
            log("status bar: no lume-menu, the bar is not drawn");
            return;
        };
        match sysmenu::SysMenu::start_hud(&bin, pid, text) {
            Ok(b) => ov.bar = Some(b),
            Err(why) => log(&format!("status bar not on the screen yet: {why}")),
        }
    }

    /// lume-menu (D14): LUME_MENU_BIN, else /usr/bin/lume-menu; None when it is not there.
    fn menu_bin(&self) -> Option<PathBuf> {
        let p = env_path("LUME_MENU_BIN", "/usr/bin/lume-menu");
        p.exists().then_some(p)
    }

    /// The menu's state on the screen: to lume-menu when it draws, else RetroArch's widget.
    fn draw_menu(&self, ov: &mut Overlay) {
        let t = ov.menu.draw_text();
        if let Some(m) = ov.sysmenu.as_mut() {
            if !t.is_empty() && !m.update(&t) {
                log("lume-menu gone: the menu falls back to RetroArch's widget");
                ov.sysmenu = None;
            } else {
                return;
            }
        }
        self.ra(&if t.is_empty() { "LUME_MENU -".to_string() } else { format!("LUME_MENU {t}") });
    }

    /// Opens the system-drawn menu (D14): the group stopped, lume-menu on the game's screen.
    /// False when it could not (lume-menu missing or failing): the caller uses the widget.
    fn open_sysmenu(&self, pid: libc::pid_t, ov: &mut Overlay) -> bool {
        let Some(bin) = self.menu_bin() else { return false };
        if ov.paused != Some(actions::Paused::Stopped) {
            // a paused RetroArch still presents frames and would cover the menu
            proc::kill_group(pid, libc::SIGSTOP);
            ov.stopped_for_menu = true;
        }
        use lume_core::gametext::{text, Text};
        let hints = (text(&ov.lang, Text::HintSelect, ""), text(&ov.lang, Text::HintBack, ""));
        let warn = text(&ov.lang, Text::ForceClose, "");
        match sysmenu::SysMenu::start(&bin, pid, (&hints.0, &hints.1), &warn, &ov.menu.draw_text()) {
            Ok(m) => {
                ov.sysmenu = Some(m);
                true
            }
            Err(why) => {
                log(&format!("lume-menu: {why}: the menu falls back to RetroArch's widget"));
                if ov.stopped_for_menu {
                    proc::kill_group(pid, libc::SIGCONT);
                    ov.stopped_for_menu = false;
                }
                false
            }
        }
    }

    /// Closes the system-drawn menu: the game's screen back, then the group continues.
    fn close_sysmenu(&self, pid: libc::pid_t, ov: &mut Overlay) {
        if let Some(m) = ov.sysmenu.take() {
            m.close();
        }
        if ov.stopped_for_menu {
            proc::kill_group(pid, libc::SIGCONT);
            ov.stopped_for_menu = false;
        }
    }

    /// The hint goes away: `lume-menu --hint` gets the end of its stdin and gives the plane back.
    fn hide_hint(&self, ov: &mut Overlay) {
        ov.hint = None;
        if let Some(p) = ov.hint_proc.take() {
            p.close();
        }
    }

    /// Fn+Y in any game (the user, 2026-11-17: from the system, not the emulator): the picture
    /// on the game's screen, without the bar or the hint, in ROMS/screenshots/ named by the game
    /// and the time. lume-menu --shot runs once and exits; the loop does not wait for it.
    fn screenshot(&self, l: &Launch, pid: libc::pid_t, ov: &mut Overlay) {
        let Some(bin) = self.menu_bin() else {
            log("screenshot: no lume-menu");
            return;
        };
        let dir = lume_core::paths::storage().join("screenshots");
        let out = dir.join(format!("{}-{}.png", game_title(l), stamp()));
        match std::process::Command::new(&bin)
            .arg("--shot")
            .arg(pid.to_string())
            .arg(&out)
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .spawn()
        {
            Ok(c) => ov.shots.push(c),
            Err(e) => log(&format!("screenshot: {}: {e}", bin.display())),
        }
    }

    /// Before the game ends: the menu closes (unpausing), the hint goes, the controls return.
    fn close_overlays(&self, l: &Launch, pid: libc::pid_t, input: Option<RawFd>, ov: &mut Overlay) {
        self.hide_hint(ov);
        if ov.menu.is_open() {
            ov.menu.state = menu::State::Closed;
            self.menu_effect(menu::Effect::Close, l, pid, input, ov);
        }
    }

    /// The renewal of every second: the bar's numbers, the menu and the hint (their widgets
    /// vanish after 3 s without one, so a dead lume-run leaves nothing on the screen), the
    /// capture (the daemon ends it after 2 s of silence).
    fn tick(&self, ov: &mut Overlay, pid: libc::pid_t, input: Option<RawFd>) {
        let text = ov.hud.as_mut().map(|(h, since)| h.sample(since.elapsed().as_secs_f64()));
        if let Some(text) = text {
            self.bar_text(ov, pid, &text);
        }
        if ov.menu.is_open() {
            actions::to_daemon(input, lume_core::input::CAPTURE_ON);
            // the widget vanishes after 3 s without a renewal; lume-menu keeps its picture
            if ov.sysmenu.is_none() {
                self.draw_menu(ov);
            }
        }
        // the pictures of Fn+Y that ended (lume-menu --shot exits on its own)
        ov.shots.retain_mut(|c| !matches!(c.try_wait(), Ok(Some(_))));
    }

    /// One message of the input daemon; Some(end) when the game must end.
    fn on_message(&self, msg: Message, l: &Launch, pid: libc::pid_t, input: Option<RawFd>, ov: &mut Overlay) -> Option<End> {
        match msg {
            Message::Action(Action::Quit) => return Some(End::QuitCombo),
            Message::Action(Action::Hud) => {
                // any runner: the system draws the bar (lume-menu --hud)
                self.hide_hint(ov);
                let on = ov.hud.is_none();
                hud::save_shown(&self.hud_file(), on);
                self.hud_show(ov, pid, on);
            }
            Message::Action(a) => {
                self.hide_hint(ov);
                if ov.menu.is_open() {
                    // a chord with the menu open: the menu closes first, the game resumes
                    ov.menu.state = menu::State::Closed;
                    self.menu_effect(menu::Effect::Close, l, pid, input, ov);
                }
                let name = a.as_str();
                if a == Action::Screenshot {
                    self.screenshot(l, pid, ov);
                } else if !actions::run(l.action(name), self.ra_port, pid, input, &log) {
                    log(&format!("action {name} not supported by runner {}", l.runner));
                }
            }
            Message::FnTap => {
                self.hide_hint(ov);
                if !l.overlay && self.menu_bin().is_none() {
                    // no lume-menu (D14) and no widget to draw the menu with
                    log(&format!("fn_tap ignored: runner {} draws no overlay", l.runner));
                } else {
                    for e in ov.menu.tap() {
                        self.menu_effect(e, l, pid, input, ov);
                    }
                }
            }
            Message::FnHold(table) => {
                if ov.menu.is_open() {
                    // the menu is on the screen already
                } else if let Some(bin) = self.menu_bin() {
                    // drawn by the system over any game (lume-menu --hint), only while Fn is
                    // held; the bar and the picture are the system's, so they are always listed
                    let declared = |a: &str| matches!(a, "hud" | "screenshot") || l.action(a).is_some();
                    let app = lume_core::gametext::app_name(&l.runner);
                    let text = menu::hint_text(&ov.lang, &app, &table, &declared);
                    match sysmenu::SysMenu::start_mode(&bin, "--hint", pid, &text) {
                        Ok(p) => {
                            ov.hint_proc = Some(p);
                            ov.hint = Some(text);
                        }
                        Err(why) => log(&format!("hint not shown: {why}")),
                    }
                } else {
                    log(&format!("fn_hold ignored: no lume-menu to draw the hint (runner {})", l.runner));
                }
            }
            Message::FnRelease => self.hide_hint(ov),
            Message::Nav(n) => {
                if ov.menu.is_open() {
                    for e in ov.menu.nav(n) {
                        self.menu_effect(e, l, pid, input, ov);
                    }
                    if ov.menu.is_open() {
                        self.draw_menu(ov);
                    }
                }
                if let Some(e) = self.pending_end.take() {
                    return Some(e);
                }
            }
            Message::Volume | Message::Brightness => {}
        }
        self.pending_end.take()
    }

    /// Carries out what the menu asked for (D10).
    fn menu_effect(&self, e: menu::Effect, l: &Launch, pid: libc::pid_t, input: Option<RawFd>, ov: &mut Overlay) {
        use menu::Effect;
        match e {
            Effect::Open => {
                let r = actions::pause(l.action("pause"), self.ra_port, pid, &log);
                ov.paused = Some(r.paused);
                if r.unresponsive {
                    ov.menu.set_unresponsive();
                }
                // D14: drawn by the system on any runner, frozen or not; the widget otherwise
                if !self.open_sysmenu(pid, ov) && !l.overlay {
                    log(&format!("menu not shown: no lume-menu and runner {} draws no overlay", l.runner));
                    ov.menu.state = menu::State::Closed;
                    if let Some(p) = ov.paused.take() {
                        actions::resume(p, self.ra_port, pid);
                    }
                    return;
                }
                actions::to_daemon(input, lume_core::input::CAPTURE_ON);
                if ov.sysmenu.is_none() {
                    // lume-menu got the first state when it started
                    self.draw_menu(ov);
                }
            }
            Effect::Close => {
                actions::to_daemon(input, lume_core::input::CAPTURE_OFF);
                if ov.sysmenu.is_some() || ov.stopped_for_menu {
                    self.close_sysmenu(pid, ov);
                } else {
                    self.draw_menu(ov);
                }
                if let Some(p) = ov.paused.take() {
                    actions::resume(p, self.ra_port, pid);
                }
            }
            Effect::Reset => {
                self.menu_effect(Effect::Close, l, pid, input, ov);
                if !actions::run(l.action("reset"), self.ra_port, pid, input, &log) {
                    log(&format!("action reset not supported by runner {}", l.runner));
                }
            }
            Effect::AppMenu => {
                if !actions::run(l.action("app_menu"), self.ra_port, pid, input, &log) {
                    log(&format!("action app_menu not supported by runner {}", l.runner));
                }
            }
            Effect::Quit => {
                self.menu_effect(Effect::Close, l, pid, input, ov);
                self.pending_end.set(Some(End::MenuQuit));
            }
            Effect::ForceClose => {
                actions::to_daemon(input, lume_core::input::CAPTURE_OFF);
                // the game's screen back before the kill (the plane keeps our buffer otherwise)
                if ov.sysmenu.is_some() {
                    if let Some(m) = ov.sysmenu.take() {
                        m.close();
                    }
                } else {
                    self.draw_menu(ov);
                }
                self.pending_end.set(Some(End::ForceClose));
            }
        }
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
