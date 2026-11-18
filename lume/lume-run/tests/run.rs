//! lume-run with a fake interface (tasks 6.2 and 6.3 of lume-launcher).
//!
//! The fake interface is a shell script that plays `step-<n>` files: the first line is its
//! exit code, the rest becomes the launch file. The cgroup tests use a child of the test's
//! own cgroup v2 when the user may write there (a systemd user session delegates it), and
//! are skipped otherwise.

use std::fs;
use std::net::UdpSocket;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

const FAKE_UI: &str = r#"#!/bin/sh
n=$(cat "$FAKE/n" 2>/dev/null || echo 0)
n=$((n + 1))
echo "$n" > "$FAKE/n"
f="$FAKE/step-$n"
[ -f "$f" ] || exit 99
code=$(head -n 1 "$f")
case "$code" in 64|65) tail -n +2 "$f" > "$XDG_RUNTIME_DIR/lume/launch" ;; esac
exit "$code"
"#;

struct Env {
    dir: PathBuf,
    cgroup: Option<PathBuf>,
}

fn setup(name: &str, cgroup: bool) -> Env {
    let dir = std::env::temp_dir().join(format!("lume-run-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(dir.join("xdg/lume")).unwrap();
    fs::create_dir_all(dir.join("run/logs")).unwrap();
    let ui = dir.join("ui");
    fs::write(&ui, FAKE_UI).unwrap();
    fs::set_permissions(&ui, fs::Permissions::from_mode(0o755)).unwrap();
    let cgroup = if cgroup { test_cgroup(name) } else { None };
    Env { dir, cgroup }
}

/// A child of our own cgroup v2, if we may create it and it has cgroup.kill.
fn test_cgroup(name: &str) -> Option<PathBuf> {
    let own = fs::read_to_string("/proc/self/cgroup").ok()?;
    let rel = own.lines().find_map(|l| l.strip_prefix("0::"))?;
    let base = Path::new("/sys/fs/cgroup").join(rel.trim_start_matches('/')).join(format!("lume-test-{name}-{}", std::process::id()));
    let _ = fs::remove_dir(&base);
    fs::create_dir(&base).ok()?;
    if !base.join("cgroup.kill").exists() {
        let _ = fs::remove_dir(&base);
        return None;
    }
    Some(base)
}

impl Env {
    fn step(&self, n: u32, code: i32, launch: &str) {
        fs::write(self.dir.join(format!("step-{n}")), format!("{code}\n{launch}")).unwrap();
    }

    fn spawn(&self, extra: &[(&str, String)]) -> Child {
        let mut c = Command::new(env!("CARGO_BIN_EXE_lume-run"));
        c.env("FAKE", &self.dir)
            .env("XDG_RUNTIME_DIR", self.dir.join("xdg"))
            .env("LUME_UI", self.dir.join("ui"))
            .env("LUME_INDEX", "/bin/true")
            .env("R36OS_RUN", self.dir.join("run"))
            .env("LUME_INPUT_SOCK", self.dir.join("input.sock"))
            .env("LUME_CGROUP", self.cgroup.clone().unwrap_or_else(|| self.dir.join("no-cgroup")))
            .stdin(Stdio::null());
        for (k, v) in extra {
            c.env(k, v);
        }
        c.spawn().unwrap()
    }

    fn events(&self) -> String {
        fs::read_to_string(self.dir.join("run/logs/events.pending")).unwrap_or_default()
    }

    fn ui_runs(&self) -> u32 {
        fs::read_to_string(self.dir.join("n")).unwrap().trim().parse().unwrap()
    }
}

impl Drop for Env {
    fn drop(&mut self) {
        if let Some(c) = &self.cgroup {
            let _ = fs::write(c.join("cgroup.kill"), "1");
            std::thread::sleep(Duration::from_millis(50));
            if let Ok(entries) = fs::read_dir(c) {
                for e in entries.flatten() {
                    if e.path().is_dir() {
                        let _ = fs::remove_dir(e.path());
                    }
                }
            }
            let _ = fs::remove_dir(c);
        }
    }
}

fn wait(child: &mut Child, limit: Duration) -> i32 {
    let end = Instant::now() + limit;
    loop {
        if let Some(s) = child.try_wait().unwrap() {
            return s.code().unwrap_or(-1);
        }
        if Instant::now() > end {
            let _ = child.kill();
            panic!("lume-run did not end in {limit:?}");
        }
        std::thread::sleep(Duration::from_millis(20));
    }
}

fn launch(system: &str, quit: &str, timeout: u32, argv: &[&str]) -> String {
    let mut s = format!("kind=game\nsystem={system}\nrunner=fake\ncore=fakecore\nquit={quit}\ntimeout={timeout}\npath=Secret Name.bin\n");
    for a in argv {
        s.push_str(&format!("arg={a}\n"));
    }
    s
}

fn alive(pid: i32) -> bool {
    // a zombie waiting for its reaper is dead for us
    match fs::read_to_string(format!("/proc/{pid}/stat")) {
        Ok(stat) => !stat.rsplit(')').next().unwrap_or("").trim_start().starts_with('Z'),
        Err(_) => false,
    }
}

fn read_pid(path: &Path, limit: Duration) -> i32 {
    let end = Instant::now() + limit;
    loop {
        if let Some(p) = fs::read_to_string(path).ok().and_then(|t| t.trim().parse().ok()) {
            return p;
        }
        assert!(Instant::now() < end, "no pid in {}", path.display());
        std::thread::sleep(Duration::from_millis(20));
    }
}

/// A SOCK_SEQPACKET listener standing in for r36os-input.
fn listen(path: &Path) -> OwnedFd {
    unsafe {
        let fd = libc::socket(libc::AF_UNIX, libc::SOCK_SEQPACKET, 0);
        assert!(fd >= 0);
        let mut addr: libc::sockaddr_un = std::mem::zeroed();
        addr.sun_family = libc::AF_UNIX as libc::sa_family_t;
        for (i, b) in path.as_os_str().as_bytes().iter().enumerate() {
            addr.sun_path[i] = *b as libc::c_char;
        }
        let len = std::mem::size_of::<libc::sa_family_t>() + path.as_os_str().len() + 1;
        assert_eq!(libc::bind(fd, &addr as *const _ as *const libc::sockaddr, len as libc::socklen_t), 0);
        assert_eq!(libc::listen(fd, 4), 0);
        OwnedFd::from_raw_fd(fd)
    }
}

fn accept_and_quit(listener: &OwnedFd) {
    unsafe {
        let c = libc::accept(listener.as_raw_fd(), std::ptr::null_mut(), std::ptr::null_mut());
        assert!(c >= 0);
        assert_eq!(libc::send(c, b"quit".as_ptr().cast(), 4, 0), 4);
        // kept open: lume-run closes its side when the game ends
        std::mem::forget(OwnedFd::from_raw_fd(c));
    }
}

#[test]
fn ui_exit_0_ends_with_0() {
    let e = setup("zero", false);
    e.step(1, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    assert_eq!(e.ui_runs(), 1);
}

#[test]
fn ui_failure_ends_with_1() {
    let e = setup("fail", false);
    e.step(1, 3, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 1);
}

#[test]
fn code_64_runs_the_game_and_reopens_the_interface() {
    let e = setup("launch", false);
    let marker = e.dir.join("ran");
    e.step(1, 64, &launch("ports", "sigterm", 2, &["/bin/sh", "-c", &format!("echo \"$0\" > '{}'", marker.display()), "arg with spaces"]));
    e.step(2, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    assert_eq!(fs::read_to_string(&marker).unwrap().trim(), "arg with spaces");
    assert_eq!(e.ui_runs(), 2);
    let ev = e.events();
    assert!(ev.contains(" game OK ports fake fakecore start"), "{ev}");
    assert!(ev.contains(" game OK ports fake fakecore exit=0 end=normal secs="), "{ev}");
    assert!(!ev.contains("Secret"), "game name in the events: {ev}");
    // the launch file is consumed
    assert!(!e.dir.join("xdg/lume/launch").exists());
}

#[test]
fn game_failure_does_not_end_the_supervisor() {
    let e = setup("gamefail", false);
    e.step(1, 64, &launch("snes", "sigterm", 2, &["/bin/sh", "-c", "kill -SEGV $$"]));
    e.step(2, 64, &launch("snes", "sigterm", 2, &["/nonexistent/emulator"]));
    e.step(3, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    assert_eq!(e.ui_runs(), 3);
    let ev = e.events();
    assert!(ev.contains("game FAIL snes fake fakecore exit=sig11 end=normal"), "{ev}");
    assert!(ev.contains("game FAIL snes fake fakecore exit=127 end=normal"), "{ev}");
}

#[test]
fn bad_launch_file_reopens_the_interface() {
    let e = setup("badlaunch", false);
    e.step(1, 64, "garbage\n");
    e.step(2, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    assert_eq!(e.ui_runs(), 2);
}

/// A game that ignores SIGTERM and leaves a grandchild in another session.
fn stubborn_game(e: &Env) -> String {
    let script = e.dir.join("game.sh");
    fs::write(
        &script,
        format!(
            "trap '' TERM\n\
             setsid sh -c 'trap \"\" TERM; echo $$ > \"{d}/grand\"; while :; do sleep 1; done' &\n\
             echo $$ > \"{d}/game\"\n\
             while :; do sleep 1; done\n",
            d = e.dir.display()
        ),
    )
    .unwrap();
    script.to_string_lossy().into_owned()
}

#[test]
fn quit_combo_ends_a_stubborn_game_and_its_grandchild() {
    let e = setup("stubborn", true);
    let Some(_) = &e.cgroup else {
        eprintln!("skipped: no writable cgroup v2 here");
        return;
    };
    let listener = listen(&e.dir.join("input.sock"));
    let game = stubborn_game(&e);
    e.step(1, 64, &launch("ports", "sigterm", 1, &["/bin/sh", &game]));
    e.step(2, 0, "");
    let mut run = e.spawn(&[]);
    let game_pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let grand = read_pid(&e.dir.join("grand"), Duration::from_secs(5));
    let t0 = Instant::now();
    accept_and_quit(&listener);
    assert_eq!(wait(&mut run, Duration::from_secs(10)), 0);
    // timeout (1 s) + 2 s
    assert!(t0.elapsed() < Duration::from_secs(3), "took {:?}", t0.elapsed());
    std::thread::sleep(Duration::from_millis(100));
    assert!(!alive(game_pid), "game still alive");
    assert!(!alive(grand), "grandchild outside the session still alive");
    let ev = e.events();
    assert!(ev.contains("game FAIL ports fake fakecore exit=sig9 end=killed"), "{ev}");
    // the game cgroup is gone
    let left: Vec<_> = fs::read_dir(e.cgroup.as_ref().unwrap()).unwrap().flatten().filter(|d| d.path().is_dir()).collect();
    assert!(left.is_empty(), "{left:?}");
}

#[test]
fn quit_combo_without_cgroup_kills_the_process_group() {
    let e = setup("nocgroup", false);
    let listener = listen(&e.dir.join("input.sock"));
    let game = stubborn_game(&e);
    e.step(1, 64, &launch("ports", "sigterm", 1, &["/bin/sh", &game]));
    e.step(2, 0, "");
    let mut run = e.spawn(&[]);
    let game_pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let grand = read_pid(&e.dir.join("grand"), Duration::from_secs(5));
    accept_and_quit(&listener);
    assert_eq!(wait(&mut run, Duration::from_secs(10)), 0);
    std::thread::sleep(Duration::from_millis(100));
    assert!(!alive(game_pid));
    // the documented limit of the fallback: a process that left the session escapes
    unsafe { libc::kill(grand, libc::SIGKILL) };
}

#[test]
fn retroarch_quit_arrives_before_any_signal() {
    let e = setup("udp", false);
    let udp = UdpSocket::bind("127.0.0.1:0").unwrap();
    udp.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
    let port = udp.local_addr().unwrap().port();
    let listener = listen(&e.dir.join("input.sock"));
    // records any SIGTERM; exits when the test says so (as RetroArch after QUIT)
    let d = e.dir.display().to_string();
    let game = format!("trap 'echo term > \"{d}/term\"' TERM; echo $$ > \"{d}/game\"; while [ ! -f \"{d}/exit\" ]; do sleep 0.05; done");
    e.step(1, 64, &launch("snes", "retroarch-cmd", 3, &["/bin/sh", "-c", &game]));
    e.step(2, 0, "");
    let mut run = e.spawn(&[("LUME_RA_PORT", port.to_string())]);
    read_pid(&e.dir.join("game"), Duration::from_secs(5));
    accept_and_quit(&listener);
    let mut buf = [0u8; 16];
    let (n, _) = udp.recv_from(&mut buf).unwrap();
    assert_eq!(&buf[..n], b"QUIT");
    assert!(!e.dir.join("term").exists(), "a signal came before QUIT");
    // one QUIT only: RetroArch runs with quit_press_twice off under the launcher
    udp.set_read_timeout(Some(Duration::from_millis(400))).unwrap();
    assert!(udp.recv_from(&mut buf).is_err(), "a second QUIT");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    assert!(!e.dir.join("term").exists());
    assert!(e.events().contains("game OK snes fake fakecore exit=0 end=quit-combo"), "{}", e.events());
}

/// The power FIFO `$R36OS_RUN/power`, read without blocking (the test is the power service).
fn power_fifo(e: &Env) -> (PathBuf, fs::File) {
    use std::os::unix::fs::OpenOptionsExt;
    let p = e.dir.join("run/power");
    let c = std::ffi::CString::new(p.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o660) }, 0);
    let r = fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK).open(&p).unwrap();
    (p, r)
}

fn drain(r: &mut fs::File, acc: &mut String) {
    use std::io::Read;
    let mut buf = [0u8; 256];
    while let Ok(n) = r.read(&mut buf) {
        if n == 0 {
            break;
        }
        acc.push_str(&String::from_utf8_lossy(&buf[..n]));
    }
}

#[test]
fn power_fifo_gets_game_before_the_game_runs_and_end_after_it_exits() {
    let e = setup("power", false);
    let (_p, mut r) = power_fifo(&e);
    let d = e.dir.display().to_string();
    let game = format!("echo $$ > \"{d}/game\"; while [ ! -f \"{d}/exit\" ]; do sleep 0.05; done");
    e.step(1, 64, &launch("snes", "sigterm", 2, &["/bin/sh", "-c", &game]));
    e.step(2, 0, "");
    let mut run = e.spawn(&[]);
    read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let mut got = String::new();
    drain(&mut r, &mut got);
    // the game is running: `game` is there, `end` is not; the per-game key (D18), never the name
    let line = format!("game snes fakecore {}\n", lume_core::power::game_key("/storage/roms/snes/Secret Name.bin"));
    assert_eq!(got, line);
    assert!(!got.contains("Secret"));
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    drain(&mut r, &mut got);
    assert_eq!(got, format!("{line}end\n"));
}

#[test]
fn power_end_comes_after_a_forced_kill() {
    let e = setup("powerkill", false);
    let (_p, mut r) = power_fifo(&e);
    let listener = listen(&e.dir.join("input.sock"));
    let game = stubborn_game(&e);
    e.step(1, 64, &launch("ports", "sigterm", 1, &["/bin/sh", &game]));
    e.step(2, 0, "");
    let mut run = e.spawn(&[]);
    let game_pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let grand = read_pid(&e.dir.join("grand"), Duration::from_secs(5));
    accept_and_quit(&listener);
    assert_eq!(wait(&mut run, Duration::from_secs(10)), 0);
    let mut got = String::new();
    drain(&mut r, &mut got);
    assert_eq!(got, format!("game ports fakecore {}\nend\n", lume_core::power::game_key("ports/Secret Name.bin")));
    assert!(!alive(game_pid));
    unsafe { libc::kill(grand, libc::SIGKILL) };
}

#[test]
fn power_native_runner_uses_the_runner_as_core() {
    let e = setup("powernative", false);
    let (_p, mut r) = power_fifo(&e);
    let l = "kind=game\nsystem=ports\nrunner=sh\nquit=sigterm\ntimeout=2\narg=/bin/true\n";
    e.step(1, 64, l);
    e.step(2, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    let mut got = String::new();
    drain(&mut r, &mut got);
    assert_eq!(got, "game ports sh\nend\n");
}

#[test]
fn fifo_without_reader_does_not_stop_the_game() {
    let e = setup("noreader", false);
    // a FIFO nobody reads, and a missing one in the second run
    let p = e.dir.join("run/power");
    let c = std::ffi::CString::new(p.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(c.as_ptr(), 0o660) }, 0);
    let marker = e.dir.join("ran");
    e.step(1, 64, &launch("ports", "sigterm", 2, &["/bin/sh", "-c", &format!("echo ok > '{}'", marker.display())]));
    e.step(2, 0, "");
    assert_eq!(wait(&mut e.spawn(&[]), Duration::from_secs(5)), 0);
    assert_eq!(fs::read_to_string(&marker).unwrap().trim(), "ok");
}

// ---- lume-hud-actions: the runner's actions, the pause and the Lume menu ----

use std::sync::{Arc, Mutex};

/// A fake RetroArch on UDP: records every command and answers GET_STATUS with its state
/// (PAUSE_TOGGLE flips it); `mute` answers nothing.
struct FakeRa {
    port: u16,
    got: Arc<Mutex<Vec<String>>>,
    state: Arc<Mutex<&'static str>>,
}

impl FakeRa {
    fn new(state: &'static str) -> FakeRa {
        let s = UdpSocket::bind("127.0.0.1:0").unwrap();
        let port = s.local_addr().unwrap().port();
        let got = Arc::new(Mutex::new(Vec::new()));
        let st = Arc::new(Mutex::new(state));
        let (g, st2) = (got.clone(), st.clone());
        std::thread::spawn(move || {
            let mut buf = [0u8; 512];
            while let Ok((n, from)) = s.recv_from(&mut buf) {
                let cmd = String::from_utf8_lossy(&buf[..n]).into_owned();
                let mut state = st2.lock().unwrap();
                if cmd == "PAUSE_TOGGLE" {
                    *state = match *state {
                        "PLAYING" => "PAUSED",
                        "PAUSED" => "PLAYING",
                        s => s,
                    };
                }
                if cmd == "GET_STATUS" && *state != "mute" {
                    let _ = s.send_to(format!("GET_STATUS {} snes,Alpha,crc32=0", *state).as_bytes(), from);
                }
                g.lock().unwrap().push(cmd);
            }
        });
        FakeRa { port, got, state: st }
    }

    fn cmds(&self) -> Vec<String> {
        self.got.lock().unwrap().clone()
    }

    /// The commands without the renewals of the widgets.
    fn plain(&self) -> Vec<String> {
        self.cmds().into_iter().filter(|c| !c.starts_with("LUME_")).collect()
    }

    fn wait_for(&self, cmd: &str) {
        let end = Instant::now() + Duration::from_secs(5);
        while !self.cmds().iter().any(|c| c == cmd || c.starts_with(&format!("{cmd} "))) {
            assert!(Instant::now() < end, "RetroArch never got {cmd}: {:?}", self.cmds());
            std::thread::sleep(Duration::from_millis(20));
        }
    }
}

/// The fake input daemon's side of lume-run's connection.
struct Daemon(OwnedFd);

impl Daemon {
    fn accept(listener: &OwnedFd) -> Daemon {
        let c = unsafe { libc::accept(listener.as_raw_fd(), std::ptr::null_mut(), std::ptr::null_mut()) };
        assert!(c >= 0);
        Daemon(unsafe { OwnedFd::from_raw_fd(c) })
    }

    fn send(&self, msg: &str) {
        assert_eq!(unsafe { libc::send(self.0.as_raw_fd(), msg.as_ptr().cast(), msg.len(), 0) }, msg.len() as isize);
        std::thread::sleep(Duration::from_millis(150));
    }

    /// Every message lume-run sent so far.
    fn received(&self) -> Vec<String> {
        let mut v = Vec::new();
        let mut buf = [0u8; 256];
        loop {
            let n = unsafe { libc::recv(self.0.as_raw_fd(), buf.as_mut_ptr().cast(), buf.len(), libc::MSG_DONTWAIT) };
            if n <= 0 {
                return v;
            }
            v.push(String::from_utf8_lossy(&buf[..n as usize]).into_owned());
        }
    }
}

const RA_ACTIONS: &str = "overlay=retroarch\naction=pause retroarch-pause\naction=app_menu retroarch-cmd:MENU_TOGGLE\n\
action=reset retroarch-cmd:RESET\naction=save_state retroarch-cmd:SAVE_STATE\naction=load_state retroarch-cmd:LOAD_STATE\n\
action=screenshot retroarch-cmd:SCREENSHOT\n";

/// A game that runs until `exit` exists and writes its pid; `extra` goes in the launch file.
fn waiting_game(e: &Env, quit: &str, extra: &str) {
    let d = e.dir.display().to_string();
    let game = format!("echo $$ > \"{d}/game\"; while [ ! -f \"{d}/exit\" ]; do sleep 0.05; done");
    e.step(1, 64, &format!("{extra}{}", launch("snes", quit, 1, &["/bin/sh", "-c", &game])));
    e.step(2, 0, "");
}

/// The state letter of a process (R, S, T...).
fn proc_state(pid: i32) -> char {
    let stat = fs::read_to_string(format!("/proc/{pid}/stat")).unwrap();
    stat.rsplit(')').next().unwrap().trim_start().chars().next().unwrap()
}

fn spawn_logged(e: &Env, port: u16) -> Child {
    let mut c = Command::new(env!("CARGO_BIN_EXE_lume-run"));
    c.env("FAKE", &e.dir)
        .env("XDG_RUNTIME_DIR", e.dir.join("xdg"))
        .env("LUME_UI", e.dir.join("ui"))
        .env("LUME_INDEX", "/bin/true")
        .env("R36OS_RUN", e.dir.join("run"))
        .env("LUME_INPUT_SOCK", e.dir.join("input.sock"))
        .env("LUME_CGROUP", e.dir.join("no-cgroup"))
        .env("LUME_STORAGE", e.dir.join("storage"))
        .env("LUME_RA_PORT", port.to_string())
        // a test that writes a fake lume-menu there gets it (fake_lume_menu); else none
        .env("LUME_MENU_BIN", e.dir.join("lume-menu"))
        .stdin(Stdio::null())
        .stderr(Stdio::from(fs::File::create(e.dir.join("stderr")).unwrap()));
    c.spawn().unwrap()
}

fn stderr(e: &Env) -> String {
    fs::read_to_string(e.dir.join("stderr")).unwrap_or_default()
}

#[test]
fn chords_become_retroarch_commands() {
    let e = setup("chords", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    // a fake lume-menu that records its arguments: the picture of Fn+Y is the system's
    let pm = e.dir.join("lume-menu");
    let d_ = e.dir.display().to_string();
    fs::write(&pm, format!("#!/bin/sh\necho \"$*\" >> \"{d_}/shot.args\"\n")).unwrap();
    fs::set_permissions(&pm, fs::Permissions::from_mode(0o755)).unwrap();
    let mut run = spawn_logged(&e, ra.port);
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    for m in ["save_state", "load_state", "screenshot", "app_menu", "volume", "unknown thing"] {
        d.send(m);
    }
    // Fn+Y is taken by the system (any emulator, the user 2026-11-17): no SCREENSHOT to RetroArch
    assert_eq!(ra.plain(), ["SAVE_STATE", "LOAD_STATE", "MENU_TOGGLE"]);
    std::thread::sleep(Duration::from_millis(200));
    let args = fs::read_to_string(e.dir.join("shot.args")).unwrap();
    assert!(args.starts_with(&format!("--shot {pid} ")) && args.contains("/screenshots/") && args.trim_end().ends_with(".png"), "{args}");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

#[test]
fn menu_pauses_retroarch_and_unpauses_only_its_own_pause() {
    let e = setup("pause", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    let mut run = spawn_logged(&e, ra.port);
    read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    d.send("fn_tap");
    ra.wait_for("LUME_MENU");
    assert_eq!(ra.plain(), ["GET_STATUS", "PAUSE_TOGGLE", "GET_STATUS"]);
    assert_eq!(*ra.state.lock().unwrap(), "PAUSED");
    let menu = ra.cmds().into_iter().find(|c| c.starts_with("LUME_MENU ")).unwrap();
    assert_eq!(menu, "LUME_MENU Secret Name|Back to game|End game|Reset|Fake menu|0");
    assert_eq!(d.received(), ["capture on"]);
    // B goes back: unpaused, the menu hidden, the controls returned
    d.send("nav b");
    assert_eq!(*ra.state.lock().unwrap(), "PLAYING");
    assert_eq!(ra.cmds().last().unwrap(), "PAUSE_TOGGLE");
    assert!(ra.cmds().iter().any(|c| c == "LUME_MENU -"));
    assert_eq!(d.received(), ["capture off"]);
    // already paused by the user: the menu does not toggle, and leaves it paused
    *ra.state.lock().unwrap() = "PAUSED";
    let before = ra.plain().len();
    d.send("fn_tap");
    d.send("fn_tap");
    assert_eq!(&ra.plain()[before..], ["GET_STATUS"]);
    assert_eq!(*ra.state.lock().unwrap(), "PAUSED");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

#[test]
fn menu_reset_and_end_go_through_the_runner() {
    let e = setup("menuend", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    let mut run = spawn_logged(&e, ra.port);
    read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    // Reset: Yes on top, No below with the focus; A without moving is No; Up then A is Yes
    d.send("fn_tap");
    d.send("nav down");
    d.send("nav down");
    d.send("nav a");
    assert!(ra.cmds().iter().any(|c| c == "LUME_MENU Reset the game?|Yes|No|1"), "{:?}", ra.cmds());
    d.send("nav a");
    assert!(!ra.plain().contains(&"RESET".to_string()));
    d.send("nav a");
    d.send("nav up");
    d.send("nav a");
    // unpaused before the reset, so RetroArch carries it out
    let plain = ra.plain();
    assert_eq!(&plain[plain.len() - 2..], ["PAUSE_TOGGLE", "RESET"]);
    // the RetroArch menu item: closes the Lume menu, then MENU_TOGGLE
    d.send("fn_tap");
    d.send("nav down");
    d.send("nav down");
    d.send("nav down");
    d.send("nav a");
    assert_eq!(ra.plain().last().unwrap(), "MENU_TOGGLE");
    // End game, second in the list: the polite quit (one QUIT)
    *ra.state.lock().unwrap() = "PLAYING";
    d.send("fn_tap");
    for n in ["nav down", "nav a", "nav up", "nav a"] {
        d.send(n);
    }
    ra.wait_for("QUIT");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    assert!(e.events().contains("end=menu-quit"), "{}", e.events());
}

#[test]
fn silent_retroarch_is_stopped_and_force_closed() {
    let e = setup("silent", false);
    let ra = FakeRa::new("mute");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    let mut run = spawn_logged(&e, ra.port);
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    let t0 = Instant::now();
    d.send("fn_tap");
    ra.wait_for("LUME_MENU");
    // the answer is awaited for 1 s at most
    assert!(t0.elapsed() < Duration::from_millis(1600), "{:?}", t0.elapsed());
    assert_eq!(proc_state(pid), 'T', "the game is stopped");
    assert!(ra.cmds().iter().any(|c| c == "LUME_MENU Fake is not responding|Back to game|End game|Force close|2"), "{:?}", ra.cmds());
    d.send("nav a");
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    assert!(!alive(pid));
    assert!(e.events().contains("end=force-close"), "{}", e.events());
}

#[test]
fn menu_without_a_pause_action_freezes_the_group() {
    let e = setup("sigstop", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "sigterm", "overlay=retroarch\n");
    let mut run = spawn_logged(&e, ra.port);
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    d.send("fn_tap");
    assert_eq!(proc_state(pid), 'T');
    // only Back and End: no reset and no app menu declared
    assert!(ra.cmds().iter().any(|c| c == "LUME_MENU Secret Name|Back to game|End game|0"), "{:?}", ra.cmds());
    d.send("fn_tap");
    std::thread::sleep(Duration::from_millis(100));
    assert_ne!(proc_state(pid), 'T');
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

#[test]
fn key_and_signal_actions_and_undeclared_ones() {
    let e = setup("keysig", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    let d_ = e.dir.display().to_string();
    let game = format!("trap 'echo usr1 > \"{d_}/usr1\"' USR1; echo $$ > \"{d_}/game\"; while [ ! -f \"{d_}/exit\" ]; do sleep 0.05; done");
    e.step(1, 64, &format!("action=save_state key:KEY_F2\naction=load_state signal:SIGUSR1\n{}", launch("snes", "sigterm", 1, &["/bin/sh", "-c", &game])));
    e.step(2, 0, "");
    let mut run = spawn_logged(&e, ra.port);
    read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    d.send("save_state");
    assert_eq!(d.received(), ["tap KEY_F2"]);
    d.send("load_state");
    std::thread::sleep(Duration::from_millis(200));
    assert!(e.dir.join("usr1").exists(), "SIGUSR1 to the game's group");
    // not declared: one log line, nothing else; no lume-menu: the menu, the hint, the bar and
    // the picture of Fn+Y (all drawn or taken by the system, any runner) say so
    d.send("app_menu");
    d.send("fn_tap");
    d.send("fn_hold B=app_menu Start=quit");
    d.send("hud");
    d.send("screenshot");
    assert!(ra.cmds().is_empty(), "{:?}", ra.cmds());
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    let log = stderr(&e);
    for line in ["action app_menu not supported by runner fake", "fn_tap ignored: runner fake draws no overlay",
                 "fn_hold ignored: no lume-menu to draw the hint (runner fake)",
                 "status bar: no lume-menu, the bar is not drawn", "screenshot: no lume-menu"] {
        assert!(log.contains(line), "{line}: {log}");
    }
}

#[test]
fn hint_and_bar_are_drawn_by_the_system() {
    let e = setup("hint", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    fake_lume_menu(&e, "ok");
    let mut run = spawn_logged(&e, ra.port);
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    // the hint: lume-menu --hint while Fn is held (the picture and the bar are the system's,
    // always listed), nothing to RetroArch
    d.send("fn_hold B=app_menu R1=save_state Y=screenshot X=hud Start=quit Vol=brightness");
    std::thread::sleep(Duration::from_millis(200));
    assert_eq!(fs::read_to_string(e.dir.join("menu.args")).unwrap().trim(), format!("--hint {pid}"));
    assert_eq!(fs::read_to_string(e.dir.join("menu.lines")).unwrap().lines().next(),
               Some("Fn+B\tFake menu|Fn+R1\tSave state|Fn+Y\tScreenshot|Fn+X\tStatus bar|Fn+Start\tEnd game"));
    d.send("fn_release");
    std::thread::sleep(Duration::from_millis(200));
    assert_eq!(fs::read_to_string(e.dir.join("menu.lines")).unwrap().lines().last(), Some("closed"));
    assert!(ra.cmds().is_empty(), "{:?}", ra.cmds());
    fs::remove_file(e.dir.join("menu.lines")).unwrap();
    // the bar: drawn by the system (lume-menu --hud), renewed every second, then off;
    // remembered for the next game; nothing of it goes to RetroArch (the user, 2026-11-17)
    d.send("hud");
    std::thread::sleep(Duration::from_millis(1300));
    let args = fs::read_to_string(e.dir.join("menu.args")).unwrap();
    assert_eq!(args.trim(), format!("--hud {pid}"));
    let lines = fs::read_to_string(e.dir.join("menu.lines")).unwrap();
    let bars: Vec<&str> = lines.lines().collect();
    assert!(bars.len() >= 2 && bars[0].starts_with("FPS --|CPU "), "{bars:?}");
    assert_eq!(fs::read_to_string(e.dir.join("xdg/lume/hud")).unwrap(), "1\n");
    d.send("hud");
    std::thread::sleep(Duration::from_millis(300));
    assert_eq!(fs::read_to_string(e.dir.join("menu.lines")).unwrap().lines().last(), Some("closed"));
    assert_eq!(fs::read_to_string(e.dir.join("xdg/lume/hud")).unwrap(), "0\n");
    assert!(!ra.cmds().iter().any(|c| c.starts_with("LUME_HUD")), "{:?}", ra.cmds());
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

/// A fake lume-menu: "ok", then every stdin line into `menu.lines`, "closed" at the end.
fn fake_lume_menu(e: &Env, answer: &str) -> PathBuf {
    let p = e.dir.join("lume-menu");
    let d = e.dir.display().to_string();
    fs::write(
        &p,
        format!("#!/bin/sh\necho \"$*\" > \"{d}/menu.args\"\nread first\necho \"$first\" >> \"{d}/menu.lines\"\necho {answer}\n\
                 while read l; do echo \"$l\" >> \"{d}/menu.lines\"; done\necho closed >> \"{d}/menu.lines\"\n"),
    )
    .unwrap();
    fs::set_permissions(&p, fs::Permissions::from_mode(0o755)).unwrap();
    p
}

#[test]
fn system_drawn_menu_on_a_runner_without_overlay() {
    // D14: lume-menu draws the menu over any runner; the group stays stopped while it is open
    let e = setup("sysmenu", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "sigterm", "");
    let bin = fake_lume_menu(&e, "ok");
    let mut c = Command::new(env!("CARGO_BIN_EXE_lume-run"));
    c.env("FAKE", &e.dir)
        .env("XDG_RUNTIME_DIR", e.dir.join("xdg"))
        .env("LUME_UI", e.dir.join("ui"))
        .env("LUME_INDEX", "/bin/true")
        .env("R36OS_RUN", e.dir.join("run"))
        .env("LUME_INPUT_SOCK", e.dir.join("input.sock"))
        .env("LUME_CGROUP", e.dir.join("no-cgroup"))
        .env("LUME_STORAGE", e.dir.join("storage"))
        .env("LUME_RA_PORT", ra.port.to_string())
        .env("LUME_MENU_BIN", &bin)
        .stdin(Stdio::null());
    let mut run = c.spawn().unwrap();
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    d.send("fn_tap");
    std::thread::sleep(Duration::from_millis(200));
    assert_eq!(proc_state(pid), 'T', "the group is stopped while lume-menu draws");
    let args = fs::read_to_string(e.dir.join("menu.args")).unwrap();
    assert!(args.starts_with(&format!("{pid} --hints Select|Back --warn Force close")), "{args}");
    d.send("nav down");
    // B: back to the game, lume-menu gets the end of its stdin, the group continues
    d.send("nav b");
    std::thread::sleep(Duration::from_millis(300));
    assert_ne!(proc_state(pid), 'T');
    let lines = fs::read_to_string(e.dir.join("menu.lines")).unwrap();
    assert_eq!(lines, "Secret Name|Back to game|End game|0\nSecret Name|Back to game|End game|1\nclosed\n");
    assert!(!ra.cmds().iter().any(|c| c.starts_with("LUME_MENU")), "no widget: {:?}", ra.cmds());
    assert_eq!(d.received(), ["capture on", "capture off"]);
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

#[test]
fn failing_lume_menu_falls_back_to_the_widget() {
    let e = setup("sysmenufail", false);
    let ra = FakeRa::new("PLAYING");
    let listener = listen(&e.dir.join("input.sock"));
    waiting_game(&e, "retroarch-cmd", RA_ACTIONS);
    let bin = fake_lume_menu(&e, "fail no screen");
    let mut c = Command::new(env!("CARGO_BIN_EXE_lume-run"));
    c.env("FAKE", &e.dir)
        .env("XDG_RUNTIME_DIR", e.dir.join("xdg"))
        .env("LUME_UI", e.dir.join("ui"))
        .env("LUME_INDEX", "/bin/true")
        .env("R36OS_RUN", e.dir.join("run"))
        .env("LUME_INPUT_SOCK", e.dir.join("input.sock"))
        .env("LUME_CGROUP", e.dir.join("no-cgroup"))
        .env("LUME_STORAGE", e.dir.join("storage"))
        .env("LUME_RA_PORT", ra.port.to_string())
        .env("LUME_MENU_BIN", &bin)
        .stdin(Stdio::null());
    let mut run = c.spawn().unwrap();
    let pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    let d = Daemon::accept(&listener);
    d.send("fn_tap");
    ra.wait_for("LUME_MENU");
    // the group continues (only RetroArch's pause holds the game), the widget draws
    assert_ne!(proc_state(pid), 'T');
    d.send("fn_tap");
    assert_eq!(*ra.state.lock().unwrap(), "PLAYING");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
}

#[test]
fn session_sigterm_ends_the_game_and_the_supervisor() {
    let e = setup("session", false);
    let d = e.dir.display().to_string();
    e.step(1, 64, &launch("ports", "sigterm", 1, &["/bin/sh", "-c", &format!("echo $$ > \"{d}/game\"; while :; do sleep 1; done")]));
    let mut run = e.spawn(&[]);
    let game_pid = read_pid(&e.dir.join("game"), Duration::from_secs(5));
    unsafe { libc::kill(run.id() as i32, libc::SIGTERM) };
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    std::thread::sleep(Duration::from_millis(100));
    assert!(!alive(game_pid));
    assert_eq!(e.ui_runs(), 1);
}
