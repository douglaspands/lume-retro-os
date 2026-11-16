//! Child processes of the supervisor (lume-launcher D9): the interface, plain, and each game
//! in its own cgroup v2 (`<base>/game-<n>`), in a new session, watched through a pidfd.
//!
//! Spawning a game: `clone3(CLONE_INTO_CGROUP | CLONE_PIDFD)`; if the kernel refuses it, a
//! `fork` whose child moves itself into the cgroup before `exec`, with `pidfd_open`. Without
//! a usable cgroup the game still runs, in its own process group, and the forced end falls
//! back to `kill(-pgid)` (logged as `cgroup unavailable`).
//!
//! The process is single-threaded, so the child of `clone3`/`fork` may run Rust code until
//! `exec`; it only calls async-signal-safe functions anyway.

use std::ffi::CString;
use std::fs;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const CLONE_PIDFD: u64 = 0x1000;
const CLONE_INTO_CGROUP: u64 = 0x2_0000_0000;

#[repr(C)]
#[derive(Default)]
struct CloneArgs {
    flags: u64,
    pidfd: u64,
    child_tid: u64,
    parent_tid: u64,
    exit_signal: u64,
    stack: u64,
    stack_size: u64,
    tls: u64,
    set_tid: u64,
    set_tid_size: u64,
    cgroup: u64,
}

pub struct Child {
    pub pid: libc::pid_t,
    pub pidfd: OwnedFd,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Exit {
    Code(i32),
    Signal(i32),
}

impl Exit {
    pub fn describe(self) -> String {
        match self {
            Exit::Code(c) => c.to_string(),
            Exit::Signal(s) => format!("sig{s}"),
        }
    }
}

fn cstrings(argv: &[String]) -> io::Result<Vec<CString>> {
    argv.iter()
        .map(|a| CString::new(a.as_bytes()).map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "NUL in argument")))
        .collect()
}

/// In the child, after clone3/fork: default signal mask, optional new session, exec.
fn exec_child(argv: &[CString], new_session: bool, cgroup_procs: Option<RawFd>) -> ! {
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigprocmask(libc::SIG_SETMASK, &set, std::ptr::null_mut());
        for sig in [libc::SIGTERM, libc::SIGINT, libc::SIGPIPE] {
            libc::signal(sig, libc::SIG_DFL);
        }
        if let Some(fd) = cgroup_procs {
            // "0": the writing process itself
            if libc::write(fd, b"0".as_ptr().cast(), 1) != 1 {
                libc::_exit(126);
            }
            libc::close(fd);
        }
        if new_session {
            libc::setsid();
        }
        let mut ptrs: Vec<*const libc::c_char> = argv.iter().map(|a| a.as_ptr()).collect();
        ptrs.push(std::ptr::null());
        libc::execvp(ptrs[0], ptrs.as_ptr());
        libc::_exit(127);
    }
}

fn pidfd_open(pid: libc::pid_t) -> io::Result<OwnedFd> {
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { OwnedFd::from_raw_fd(fd as RawFd) })
}

fn fork_exec(argv: &[CString], new_session: bool, cgroup_procs: Option<RawFd>) -> io::Result<Child> {
    let pid = unsafe { libc::fork() };
    match pid {
        -1 => Err(io::Error::last_os_error()),
        0 => exec_child(argv, new_session, cgroup_procs),
        pid => Ok(Child { pid, pidfd: pidfd_open(pid)? }),
    }
}

/// Runs a plain child (the interface): same session, no cgroup.
pub fn spawn(argv: &[String]) -> io::Result<Child> {
    fork_exec(&cstrings(argv)?, false, None)
}

/// Runs a game in a new session, inside `cgroup` when given. Returns the child and whether it
/// really is in the cgroup.
pub fn spawn_game(argv: &[String], cgroup: Option<&Path>) -> io::Result<(Child, bool)> {
    let args = cstrings(argv)?;
    let Some(cg) = cgroup else {
        return Ok((fork_exec(&args, true, None)?, false));
    };
    let dir = fs::File::open(cg)?;
    let mut pidfd: RawFd = -1;
    let mut ca = CloneArgs {
        flags: CLONE_PIDFD | CLONE_INTO_CGROUP,
        pidfd: &mut pidfd as *mut RawFd as u64,
        exit_signal: libc::SIGCHLD as u64,
        cgroup: dir.as_raw_fd() as u64,
        ..Default::default()
    };
    let pid = unsafe { libc::syscall(libc::SYS_clone3, &mut ca as *mut CloneArgs, std::mem::size_of::<CloneArgs>()) };
    if pid == 0 {
        exec_child(&args, true, None);
    }
    if pid > 0 {
        return Ok((Child { pid: pid as libc::pid_t, pidfd: unsafe { OwnedFd::from_raw_fd(pidfd) } }, true));
    }
    // clone3 refused (old kernel, seccomp, cgroup not delegated): the child moves itself
    let procs = fs::OpenOptions::new().write(true).open(cg.join("cgroup.procs"));
    match procs {
        Ok(f) => {
            let child = fork_exec(&args, true, Some(f.as_raw_fd()))?;
            Ok((child, true))
        }
        Err(_) => Ok((fork_exec(&args, true, None)?, false)),
    }
}

/// Reaps a child whose pidfd became readable (or blocks until it exits).
pub fn reap(pid: libc::pid_t) -> Exit {
    let mut status = 0;
    loop {
        let r = unsafe { libc::waitpid(pid, &mut status, 0) };
        if r == pid {
            break;
        }
        if r == -1 && io::Error::last_os_error().raw_os_error() != Some(libc::EINTR) {
            return Exit::Code(-1);
        }
    }
    if libc::WIFEXITED(status) {
        Exit::Code(libc::WEXITSTATUS(status))
    } else {
        Exit::Signal(libc::WTERMSIG(status))
    }
}

/// Reaps finished background helpers (lume-index --touch) without blocking.
pub fn reap_some(pids: &mut Vec<libc::pid_t>) {
    pids.retain(|&p| unsafe { libc::waitpid(p, std::ptr::null_mut(), libc::WNOHANG) } == 0);
}

/// Waits until one of `fds` is readable, up to `timeout` (None: forever). Returns the
/// readable flags; EINTR counts as nothing readable.
pub fn poll(fds: &[RawFd], timeout: Option<Duration>) -> Vec<bool> {
    let mut p: Vec<libc::pollfd> = fds.iter().map(|&fd| libc::pollfd { fd, events: libc::POLLIN, revents: 0 }).collect();
    let ms = timeout.map(|d| d.as_millis().min(i32::MAX as u128) as i32).unwrap_or(-1);
    let n = unsafe { libc::poll(p.as_mut_ptr(), p.len() as libc::nfds_t, ms) };
    if n <= 0 {
        return vec![false; fds.len()];
    }
    p.iter().map(|x| x.revents & (libc::POLLIN | libc::POLLHUP | libc::POLLERR) != 0).collect()
}

/// The cgroup of one game, removed when dropped (once empty).
pub struct GameCgroup {
    pub dir: PathBuf,
}

impl GameCgroup {
    /// `<base>/game-<n>`; None when the base is missing or not writable.
    pub fn create(base: &Path, n: u64) -> Option<GameCgroup> {
        let dir = base.join(format!("game-{n}"));
        let _ = fs::remove_dir(&dir);
        fs::create_dir(&dir).ok()?;
        if !dir.join("cgroup.procs").exists() {
            let _ = fs::remove_dir(&dir);
            return None;
        }
        Some(GameCgroup { dir })
    }

    pub fn populated(&self) -> bool {
        fs::read_to_string(self.dir.join("cgroup.events"))
            .map(|t| !t.lines().any(|l| l.trim() == "populated 0"))
            .unwrap_or(false)
    }

    /// Kills everything in the cgroup (cgroup.kill, 5.14+). False if the kernel lacks it.
    pub fn kill(&self) -> bool {
        fs::write(self.dir.join("cgroup.kill"), "1").is_ok()
    }

    /// Waits until the cgroup is empty, up to `limit`.
    pub fn wait_empty(&self, limit: Duration) -> bool {
        let end = Instant::now() + limit;
        while self.populated() {
            if Instant::now() >= end {
                return false;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        true
    }
}

impl Drop for GameCgroup {
    fn drop(&mut self) {
        let _ = fs::remove_dir(&self.dir);
    }
}

pub fn kill_group(pgid: libc::pid_t, sig: i32) {
    unsafe {
        libc::kill(-pgid, sig);
    }
}

/// Blocks SIGTERM and SIGINT and returns a signalfd for them, so the main loop sees them in
/// poll. Children get the default mask back before exec.
pub fn signal_fd() -> io::Result<OwnedFd> {
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigaddset(&mut set, libc::SIGTERM);
        libc::sigaddset(&mut set, libc::SIGINT);
        libc::sigprocmask(libc::SIG_BLOCK, &set, std::ptr::null_mut());
        let fd = libc::signalfd(-1, &set, libc::SFD_CLOEXEC);
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(OwnedFd::from_raw_fd(fd))
    }
}

/// Connects to the input daemon socket (SOCK_SEQPACKET); None if it is not there.
pub fn connect_input(path: &Path) -> Option<OwnedFd> {
    unsafe {
        let fd = libc::socket(libc::AF_UNIX, libc::SOCK_SEQPACKET | libc::SOCK_CLOEXEC, 0);
        if fd < 0 {
            return None;
        }
        let owned = OwnedFd::from_raw_fd(fd);
        let mut addr: libc::sockaddr_un = std::mem::zeroed();
        addr.sun_family = libc::AF_UNIX as libc::sa_family_t;
        let bytes = path.as_os_str().as_bytes();
        if bytes.len() >= addr.sun_path.len() {
            return None;
        }
        for (i, b) in bytes.iter().enumerate() {
            addr.sun_path[i] = *b as libc::c_char;
        }
        let len = std::mem::size_of::<libc::sa_family_t>() + bytes.len() + 1;
        if libc::connect(fd, &addr as *const libc::sockaddr_un as *const libc::sockaddr, len as libc::socklen_t) != 0 {
            return None;
        }
        Some(owned)
    }
}

/// Reads one message from the input socket; None when the daemon closed it.
pub fn read_message(fd: RawFd) -> Option<String> {
    let mut buf = [0u8; 64];
    let n = unsafe { libc::recv(fd, buf.as_mut_ptr().cast(), buf.len(), libc::MSG_DONTWAIT) };
    if n <= 0 {
        return None;
    }
    Some(String::from_utf8_lossy(&buf[..n as usize]).trim().to_string())
}
