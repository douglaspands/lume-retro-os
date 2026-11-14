//! Gamepad input by Linux codes (lume-launcher task 7.1): the interface reads the evdev
//! devices itself (the virtual gamepad of r36os-input, a USB pad, the VM keyboard), so both
//! consoles and the VM map the same way. A thread waits on the devices and hands actions to
//! the main loop, with key repeat while a direction or L1/R1 is held.

use std::os::fd::{AsRawFd, FromRawFd, OwnedFd};
use std::time::{Duration, Instant};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Action {
    Up,
    Down,
    Left,
    Right,
    A,
    B,
    X,
    Y,
    L1,
    R1,
    Start,
    Select,
}

impl Action {
    pub fn repeats(self) -> bool {
        matches!(self, Action::Up | Action::Down | Action::Left | Action::Right | Action::L1 | Action::R1)
    }
}

// linux/input-event-codes.h
const EV_KEY: u16 = 1;
const EV_ABS: u16 = 3;
const ABS_X: u16 = 0;
const ABS_Y: u16 = 1;
const ABS_HAT0X: u16 = 0x10;
const ABS_HAT0Y: u16 = 0x11;

/// The action of a key or button code (gamepad codes, then the VM keyboard layout of the
/// RetroArch factory config: arrows, X = A, Z = B, S = X, A = Y, Q/W = L1/R1, Enter = Start,
/// right Shift = Select; Esc and Backspace also go back).
pub fn map_key(code: u16) -> Option<Action> {
    Some(match code {
        0x220 | 103 => Action::Up,
        0x221 | 108 => Action::Down,
        0x222 | 105 => Action::Left,
        0x223 | 106 => Action::Right,
        0x130 | 45 => Action::A,     // BTN_A (BTN_SOUTH), KEY_X
        0x131 | 44 | 1 | 14 => Action::B, // BTN_B, KEY_Z, KEY_ESC, KEY_BACKSPACE
        0x133 | 31 => Action::X,     // BTN_X, KEY_S
        0x134 | 30 => Action::Y,     // BTN_Y, KEY_A
        0x136 | 16 => Action::L1,    // BTN_TL, KEY_Q
        0x137 | 17 => Action::R1,    // BTN_TR, KEY_W
        0x13B | 28 => Action::Start, // BTN_START, KEY_ENTER
        0x13A | 54 => Action::Select, // BTN_SELECT, KEY_RIGHTSHIFT
        _ => return None,
    })
}

/// Hold-to-repeat: 400 ms before the first repeat, then every 110 ms.
#[derive(Default)]
pub struct Repeater {
    held: Option<(Action, Instant)>,
    next: Option<Instant>,
}

pub const REPEAT_DELAY: Duration = Duration::from_millis(400);
pub const REPEAT_EVERY: Duration = Duration::from_millis(110);

impl Repeater {
    pub fn press(&mut self, a: Action, now: Instant) {
        if a.repeats() {
            self.held = Some((a, now));
            self.next = Some(now + REPEAT_DELAY);
        }
    }

    pub fn release(&mut self, a: Action) {
        if self.held.map(|(h, _)| h) == Some(a) {
            self.held = None;
            self.next = None;
        }
    }

    /// Time left until the next repeat (None: nothing held).
    pub fn timeout(&self, now: Instant) -> Option<Duration> {
        self.next.map(|n| n.saturating_duration_since(now))
    }

    /// The repeats due at `now`.
    pub fn due(&mut self, now: Instant) -> Option<Action> {
        let (a, _) = self.held?;
        let n = self.next?;
        if now >= n {
            self.next = Some(n + REPEAT_EVERY);
            return Some(a);
        }
        None
    }
}

/// Direction of an axis value, with a dead zone of a third of the range around the center.
pub fn axis_dir(value: i32, min: i32, max: i32) -> i32 {
    let center = (min + max) / 2;
    let dead = (max - min) / 3;
    if value < center - dead / 2 - dead / 4 {
        -1
    } else if value > center + dead / 2 + dead / 4 {
        1
    } else {
        0
    }
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct InputEvent {
    sec: libc::c_long,
    usec: libc::c_long,
    kind: u16,
    code: u16,
    value: i32,
}

#[repr(C)]
#[derive(Default, Clone, Copy)]
struct AbsInfo {
    value: i32,
    min: i32,
    max: i32,
    fuzz: i32,
    flat: i32,
    res: i32,
}

const fn ioc_read(nr: u64, size: u64) -> u64 {
    (2 << 30) | (size << 16) | ((b'E' as u64) << 8) | nr
}

struct Device {
    path: std::path::PathBuf,
    fd: OwnedFd,
    abs: [(i32, i32); 2],
    last_dir: [i32; 4], // stick x, stick y, hat x, hat y
}

fn has_bit(bits: &[u8], n: usize) -> bool {
    bits.get(n / 8).is_some_and(|b| b & (1 << (n % 8)) != 0)
}

/// Opens every event device with gamepad buttons or Enter (keyboards), except the ones
/// already open.
fn open_devices(open: &[Device]) -> Vec<Device> {
    let mut out = Vec::new();
    let Ok(dir) = std::fs::read_dir("/dev/input") else { return out };
    for e in dir.flatten() {
        let name = e.file_name().to_string_lossy().into_owned();
        if !name.starts_with("event") || open.iter().any(|d| d.path == e.path()) {
            continue;
        }
        let path = std::ffi::CString::new(e.path().as_os_str().as_encoded_bytes()).unwrap();
        let fd = unsafe { libc::open(path.as_ptr(), libc::O_RDONLY | libc::O_NONBLOCK | libc::O_CLOEXEC) };
        if fd < 0 {
            continue;
        }
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        let mut keys = [0u8; 96];
        unsafe { libc::ioctl(fd.as_raw_fd(), ioc_read(0x20 + EV_KEY as u64, keys.len() as u64) as _, keys.as_mut_ptr()) };
        if !(has_bit(&keys, 0x130) || has_bit(&keys, 28) || has_bit(&keys, 0x220)) {
            continue;
        }
        let mut abs = [(0, 255); 2];
        for (i, code) in [ABS_X, ABS_Y].iter().enumerate() {
            let mut info = AbsInfo::default();
            if unsafe { libc::ioctl(fd.as_raw_fd(), ioc_read(0x40 + *code as u64, 24) as _, &mut info) } >= 0 && info.max > info.min {
                abs[i] = (info.min, info.max);
            }
        }
        out.push(Device { path: e.path(), fd, abs, last_dir: [0; 4] });
    }
    out
}

/// inotify on /dev/input: a node created, or its owner changed by udev right after.
fn watch_input_dir() -> Option<OwnedFd> {
    let fd = unsafe { libc::inotify_init1(libc::IN_CLOEXEC | libc::IN_NONBLOCK) };
    if fd < 0 {
        return None;
    }
    let fd = unsafe { OwnedFd::from_raw_fd(fd) };
    let dir = std::ffi::CString::new("/dev/input").unwrap();
    (unsafe { libc::inotify_add_watch(fd.as_raw_fd(), dir.as_ptr(), libc::IN_CREATE | libc::IN_ATTRIB) } >= 0).then_some(fd)
}

/// Runs forever on its own thread: reads the devices and calls `send` for each action
/// (`true` for a repeat). A device that goes away is dropped, and a new one is opened: the
/// virtual gamepad comes back under a new node when r36os-input restarts (respawned by its
/// service), while the kernel gamepad it grabs stays open here and silent (seen on the GA36,
/// 2026-11-14: the launcher stopped answering).
pub fn run(mut send: impl FnMut(Action, bool)) {
    let mut devs = open_devices(&[]);
    let watch = watch_input_dir();
    let mut rep = Repeater::default();
    loop {
        let now = Instant::now();
        while let Some(a) = rep.due(now) {
            send(a, true);
        }
        let mut pfds: Vec<libc::pollfd> = devs.iter().map(|d| libc::pollfd { fd: d.fd.as_raw_fd(), events: libc::POLLIN, revents: 0 }).collect();
        if let Some(w) = &watch {
            pfds.push(libc::pollfd { fd: w.as_raw_fd(), events: libc::POLLIN, revents: 0 });
        }
        // without the watch, look for devices every 2 s while there is none
        let idle = if devs.is_empty() && watch.is_none() { 2000 } else { -1 };
        let timeout = rep.timeout(Instant::now()).map(|d| d.as_millis() as i32).unwrap_or(idle);
        let n = unsafe { libc::poll(pfds.as_mut_ptr(), pfds.len() as _, timeout) };
        let dir_changed = watch.is_some() && pfds.pop().is_some_and(|p| p.revents & libc::POLLIN != 0);
        if watch.is_none() && devs.is_empty() {
            devs = open_devices(&[]);
            continue;
        }
        if n <= 0 {
            continue;
        }
        let mut gone = Vec::new();
        for (i, p) in pfds.iter().enumerate() {
            if p.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
                gone.push(i);
                continue;
            }
            if p.revents & libc::POLLIN == 0 {
                continue;
            }
            let mut evs = [InputEvent::default(); 32];
            let r = unsafe { libc::read(p.fd, evs.as_mut_ptr().cast(), std::mem::size_of_val(&evs)) };
            if r <= 0 {
                continue;
            }
            let dev = &mut devs[i];
            for ev in &evs[..r as usize / std::mem::size_of::<InputEvent>()] {
                let now = Instant::now();
                match ev.kind {
                    EV_KEY => {
                        if let Some(a) = map_key(ev.code) {
                            match ev.value {
                                1 => {
                                    rep.press(a, now);
                                    send(a, false);
                                }
                                0 => rep.release(a),
                                _ => {} // the kernel's own autorepeat: ours is used
                            }
                        }
                    }
                    EV_ABS => {
                        let (slot, dir, neg, pos) = match ev.code {
                            ABS_X => (0, axis_dir(ev.value, dev.abs[0].0, dev.abs[0].1), Action::Left, Action::Right),
                            ABS_Y => (1, axis_dir(ev.value, dev.abs[1].0, dev.abs[1].1), Action::Up, Action::Down),
                            ABS_HAT0X => (2, ev.value.signum(), Action::Left, Action::Right),
                            ABS_HAT0Y => (3, ev.value.signum(), Action::Up, Action::Down),
                            _ => continue,
                        };
                        let old = dev.last_dir[slot];
                        if dir != old {
                            if old != 0 {
                                rep.release(if old < 0 { neg } else { pos });
                            }
                            if dir != 0 {
                                let a = if dir < 0 { neg } else { pos };
                                rep.press(a, now);
                                send(a, false);
                            }
                            dev.last_dir[slot] = dir;
                        }
                    }
                    _ => {}
                }
            }
        }
        for i in gone.into_iter().rev() {
            devs.remove(i);
        }
        // after the removals: a node that comes back under the same name is opened again
        if let (true, Some(w)) = (dir_changed, &watch) {
            let mut buf = [0u8; 1024];
            while unsafe { libc::read(w.as_raw_fd(), buf.as_mut_ptr().cast(), buf.len()) } > 0 {}
            let new = open_devices(&devs);
            devs.extend(new);
        }
    }
}

/// The input daemon's socket (r36os-input, design D8): "volume" after each volume key it
/// applied, "quit" for Fn+Start (not for the launcher: ignored).
pub const INPUT_SOCK: &str = "/run/r36os/input.sock";

fn connect_seqpacket(path: &std::path::Path) -> Option<OwnedFd> {
    let fd = unsafe { libc::socket(libc::AF_UNIX, libc::SOCK_SEQPACKET | libc::SOCK_CLOEXEC, 0) };
    if fd < 0 {
        return None;
    }
    let fd = unsafe { OwnedFd::from_raw_fd(fd) };
    let mut addr: libc::sockaddr_un = unsafe { std::mem::zeroed() };
    addr.sun_family = libc::AF_UNIX as libc::sa_family_t;
    let bytes = path.as_os_str().as_encoded_bytes();
    if bytes.len() >= addr.sun_path.len() {
        return None;
    }
    for (i, b) in bytes.iter().enumerate() {
        addr.sun_path[i] = *b as libc::c_char;
    }
    let len = std::mem::size_of::<libc::sockaddr_un>() as libc::socklen_t;
    (unsafe { libc::connect(fd.as_raw_fd(), (&addr as *const libc::sockaddr_un).cast(), len) } == 0).then_some(fd)
}

/// Reads the messages of one connection until the daemon closes it: on each "volume",
/// `level` reads the mixer and `send` gets the result.
pub fn serve_volume(fd: &OwnedFd, level: &mut impl FnMut() -> Option<u8>, send: &mut impl FnMut(u8)) {
    let mut buf = [0u8; 64];
    loop {
        let n = unsafe { libc::recv(fd.as_raw_fd(), buf.as_mut_ptr().cast(), buf.len(), 0) };
        if n < 0 && std::io::Error::last_os_error().kind() == std::io::ErrorKind::Interrupted {
            continue;
        }
        if n <= 0 {
            return;
        }
        if &buf[..n as usize] == b"volume" {
            if let Some(v) = level() {
                send(v);
            }
        }
    }
}

/// Runs forever on its own thread: stays connected to the input daemon and reports the
/// volume level after each volume key. The daemon restarts under its service (and is
/// missing in a test without it): connect again every 2 s.
pub fn watch_volume(sock: &std::path::Path, mut level: impl FnMut() -> Option<u8>, mut send: impl FnMut(u8)) {
    loop {
        if let Some(fd) = connect_seqpacket(sock) {
            serve_volume(&fd, &mut level, &mut send);
        }
        std::thread::sleep(Duration::from_secs(2));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn volume_messages_read_the_level_and_quit_is_ignored() {
        let mut fds = [0; 2];
        assert_eq!(unsafe { libc::socketpair(libc::AF_UNIX, libc::SOCK_SEQPACKET, 0, fds.as_mut_ptr()) }, 0);
        let (ours, daemon) = unsafe { (OwnedFd::from_raw_fd(fds[0]), OwnedFd::from_raw_fd(fds[1])) };
        for m in [&b"quit"[..], b"volume", b"other", b"volume"] {
            assert_eq!(unsafe { libc::send(daemon.as_raw_fd(), m.as_ptr().cast(), m.len(), 0) }, m.len() as isize);
        }
        drop(daemon); // the daemon went away: serve returns
        let mut reads = 0;
        let mut got = Vec::new();
        serve_volume(&ours, &mut || {
            reads += 1;
            Some(40 + reads * 5)
        }, &mut |v| got.push(v));
        assert_eq!(got, [45, 50]);
    }

    #[test]
    fn gamepad_and_vm_keyboard_map_the_same() {
        assert_eq!(map_key(0x130), Some(Action::A));
        assert_eq!(map_key(45), Some(Action::A)); // KEY_X
        assert_eq!(map_key(0x13B), Some(Action::Start));
        assert_eq!(map_key(0x13C), None); // Fn belongs to r36os-input and RetroArch
        assert_eq!(map_key(0x223), map_key(106));
    }

    #[test]
    fn repeat_after_delay_then_steady() {
        let t0 = Instant::now();
        let mut r = Repeater::default();
        r.press(Action::Down, t0);
        assert_eq!(r.due(t0 + Duration::from_millis(399)), None);
        assert_eq!(r.due(t0 + REPEAT_DELAY), Some(Action::Down));
        assert_eq!(r.due(t0 + REPEAT_DELAY), None);
        assert_eq!(r.due(t0 + REPEAT_DELAY + REPEAT_EVERY), Some(Action::Down));
        r.release(Action::Down);
        assert_eq!(r.timeout(t0), None);
        r.press(Action::A, t0);
        assert_eq!(r.timeout(t0), None); // A never repeats
    }

    #[test]
    fn stick_dead_zone() {
        assert_eq!(axis_dir(128, 0, 255), 0);
        assert_eq!(axis_dir(170, 0, 255), 0);
        assert_eq!(axis_dir(250, 0, 255), 1);
        assert_eq!(axis_dir(5, 0, 255), -1);
    }
}
