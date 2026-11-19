//! Child processes of the supervisor (lume-launcher D9): the interface, plain, and each game
//! in its own cgroup v2 (`<base>/game-<n>`), in a new session, watched through a pidfd.
//!
//! Spawning a game: `clone3(CLONE_INTO_CGROUP | CLONE_PIDFD)`; if the kernel refuses it, a
//! `fork` whose child moves itself into the cgroup before `exec`, with `pidfd_open`. Without
//! a usable cgroup the game still runs, in its own process group, and the forced end falls
//! back to `kill(-pgid)` (logged as `cgroup unavailable`).
//!
//! The process is single-threaded, so the child of `clone3`/`fork` may run Rust code until
//! `exec`; it only calls async-signal-safe functions anyway, and allocates nothing: argv, the
//! game's environment (gameenv.rs) and the program path are built before the fork, and a game
//! starts with `execve` (the interface with `execvp` and lume-run's own environment).

use std::ffi::CString;
use std::fs;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::os::unix::ffi::{OsStrExt, OsStringExt};
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

fn cstring(bytes: Vec<u8>) -> io::Result<CString> {
    CString::new(bytes).map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "NUL in argument or environment"))
}

/// Everything `exec` needs, built in the parent before `clone3`/`fork`: the child only reads
/// it (no allocation after the fork). The pointers point into the heap buffers of the
/// CStrings, which stay where they are while `Exec` lives.
struct Exec {
    /// the program for `execve`, already looked up in the game's PATH
    path: CString,
    _argv: Vec<CString>,
    _envp: Vec<CString>,
    argv_ptrs: Vec<*const libc::c_char>,
    /// None: `execvp` with lume-run's own environment (the interface)
    envp_ptrs: Option<Vec<*const libc::c_char>>,
}

fn ptrs(v: &[CString]) -> Vec<*const libc::c_char> {
    v.iter().map(|c| c.as_ptr()).chain([std::ptr::null()]).collect()
}

/// `prog` as `execvp` would find it, but in the PATH of the game's environment; a name not
/// found stays as it is (execve then fails and the child ends with 127).
fn resolve(prog: &str, path_var: Option<&[u8]>) -> PathBuf {
    if prog.contains('/') {
        return PathBuf::from(prog);
    }
    let path_var = path_var.unwrap_or(b"/usr/local/bin:/bin:/usr/bin");
    for dir in path_var.split(|&b| b == b':') {
        let dir = if dir.is_empty() { Path::new(".") } else { Path::new(std::ffi::OsStr::from_bytes(dir)) };
        let p = dir.join(prog);
        if let Ok(m) = fs::metadata(&p) {
            use std::os::unix::fs::PermissionsExt;
            if m.is_file() && m.permissions().mode() & 0o111 != 0 {
                return p;
            }
        }
    }
    PathBuf::from(prog)
}

impl Exec {
    fn new(argv: &[String], env: Option<&[crate::gameenv::Var]>) -> io::Result<Exec> {
        let args: Vec<CString> = argv.iter().map(|a| cstring(a.as_bytes().to_vec())).collect::<io::Result<_>>()?;
        let first = argv.first().map(String::as_str).unwrap_or("");
        let (path, envp) = match env {
            Some(env) => {
                let envp: Vec<CString> = env
                    .iter()
                    .map(|(k, v)| cstring([k.as_slice(), b"=", v.as_slice()].concat()))
                    .collect::<io::Result<_>>()?;
                let path = resolve(first, crate::gameenv::get(env, "PATH"));
                (cstring(path.into_os_string().into_vec())?, Some(envp))
            }
            None => (cstring(first.as_bytes().to_vec())?, None),
        };
        let argv_ptrs = ptrs(&args);
        let envp_ptrs = envp.as_deref().map(ptrs);
        Ok(Exec { path, _argv: args, _envp: envp.unwrap_or_default(), argv_ptrs, envp_ptrs })
    }
}

/// In the child, after clone3/fork: default signal mask, optional new session, exec. Only
/// async-signal-safe calls, nothing allocated.
fn exec_child(e: &Exec, new_session: bool, cgroup_procs: Option<RawFd>) -> ! {
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
        match &e.envp_ptrs {
            Some(envp) => libc::execve(e.path.as_ptr(), e.argv_ptrs.as_ptr(), envp.as_ptr()),
            None => libc::execvp(e.path.as_ptr(), e.argv_ptrs.as_ptr()),
        };
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

fn fork_exec(e: &Exec, new_session: bool, cgroup_procs: Option<RawFd>) -> io::Result<Child> {
    let pid = unsafe { libc::fork() };
    match pid {
        -1 => Err(io::Error::last_os_error()),
        0 => exec_child(e, new_session, cgroup_procs),
        pid => Ok(Child { pid, pidfd: pidfd_open(pid)? }),
    }
}

/// Runs a plain child (the interface): same session, no cgroup, lume-run's environment.
pub fn spawn(argv: &[String]) -> io::Result<Child> {
    fork_exec(&Exec::new(argv, None)?, false, None)
}

/// Runs a game with the environment `env` (gameenv.rs) in a new session, inside `cgroup`
/// when given. Returns the child and whether it really is in the cgroup.
pub fn spawn_game(argv: &[String], env: &[crate::gameenv::Var], cgroup: Option<&Path>) -> io::Result<(Child, bool)> {
    let args = Exec::new(argv, Some(env))?;
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

/// Reads one message from the input socket (the `fn_hold` table is the longest); None when
/// the daemon closed it. A spurious wake-up gives an empty message.
pub fn read_message(fd: RawFd) -> Option<String> {
    let mut buf = [0u8; 512];
    let n = unsafe { libc::recv(fd, buf.as_mut_ptr().cast(), buf.len(), libc::MSG_DONTWAIT) };
    if n < 0 && io::Error::last_os_error().kind() == io::ErrorKind::WouldBlock {
        return Some(String::new());
    }
    if n <= 0 {
        return None;
    }
    Some(String::from_utf8_lossy(&buf[..n as usize]).trim().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn program_is_looked_up_in_the_game_path() {
        assert_eq!(resolve("/x/y", None), PathBuf::from("/x/y"));
        assert_eq!(resolve("sh", Some(b"/nonexistent-dir:/bin")), PathBuf::from("/bin/sh"));
        assert_eq!(resolve("no-such-program-xyz", Some(b"/bin")), PathBuf::from("no-such-program-xyz"));
        let e = Exec::new(&["sh".into(), "-c".into()], Some(&[(b"PATH".to_vec(), b"/bin".to_vec())])).unwrap();
        assert_eq!(e.path.as_bytes(), b"/bin/sh");
        assert_eq!(e.argv_ptrs.len(), 3);
        assert_eq!(e.envp_ptrs.as_ref().map(Vec::len), Some(2));
        assert!(Exec::new(&["/bin/sh".into()], Some(&[(b"A".to_vec(), b"x\0y".to_vec())])).is_err());
    }
}
