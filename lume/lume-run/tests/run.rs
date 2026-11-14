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
    let (n, _) = udp.recv_from(&mut buf).unwrap();
    assert_eq!(&buf[..n], b"QUIT");
    fs::write(e.dir.join("exit"), "").unwrap();
    assert_eq!(wait(&mut run, Duration::from_secs(5)), 0);
    assert!(!e.dir.join("term").exists());
    assert!(e.events().contains("game OK snes fake fakecore exit=0 end=quit-combo"), "{}", e.events());
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
