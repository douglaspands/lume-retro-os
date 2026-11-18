//! The DRM side of lume-menu (lume-hud-actions D14, device-fixes 9.14). No libdrm: the
//! kernel uapi ioctls, as in lume-shot and the J1 proof (4.6).
//!
//! Two DRM files take part:
//!
//! - ours ([`Card`]): opened once per game, never the master. Every buffer we draw into lives
//!   there, allocated once when the game starts (the CMA of the GA36 is full once a game
//!   draws by the GPU: "our buffer: Out of memory", boot 193). A framebuffer id is global to
//!   the device, so the game's file can put ours on a plane.
//! - the game's ([`GameFile`]): a duplicate of the game's master file (pidfd_getfd, same user,
//!   no capability), taken for one operation and closed right after it. Keeping it would
//!   keep a file the game closed alive as the master (a game that reopens the card, as SDL
//!   does when LÖVE recreates its window, could not become the master again), and a file
//!   the game dropped answers EACCES to every SETPLANE (boot 193: "bar not shown:
//!   Permission denied").

use std::fs;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

const fn ioc(dir: u32, nr: u32, size: usize) -> libc::c_ulong {
    ((dir << 30) | ((size as u32) << 16) | ((b'd' as u32) << 8) | nr) as libc::c_ulong
}
const NONE: u32 = 0;
const W: u32 = 1;
const RW: u32 = 3;

#[repr(C)]
#[derive(Default)]
struct SetClientCap {
    capability: u64,
    value: u64,
}

#[repr(C)]
#[derive(Default)]
struct GetPlaneRes {
    plane_id_ptr: u64,
    count_planes: u32,
    _pad: u32,
}

#[repr(C)]
#[derive(Default)]
struct GetPlane {
    plane_id: u32,
    crtc_id: u32,
    fb_id: u32,
    possible_crtcs: u32,
    gamma_size: u32,
    count_format_types: u32,
    format_type_ptr: u64,
}

#[repr(C)]
#[derive(Default, Clone, Copy, Debug)]
pub struct FbCmd2 {
    pub fb_id: u32,
    pub width: u32,
    pub height: u32,
    pub pixel_format: u32,
    pub flags: u32,
    pub handles: [u32; 4],
    pub pitches: [u32; 4],
    pub offsets: [u32; 4],
    pub modifier: [u64; 4],
}

#[repr(C)]
#[derive(Default)]
struct SetPlane {
    plane_id: u32,
    crtc_id: u32,
    fb_id: u32,
    flags: u32,
    crtc_x: i32,
    crtc_y: i32,
    crtc_w: u32,
    crtc_h: u32,
    // uapi order: src_x, src_y, src_h, src_w (16.16)
    src_x: u32,
    src_y: u32,
    src_h: u32,
    src_w: u32,
}

#[repr(C)]
#[derive(Default)]
struct CreateDumb {
    height: u32,
    width: u32,
    bpp: u32,
    flags: u32,
    handle: u32,
    pitch: u32,
    size: u64,
}

#[repr(C)]
#[derive(Default)]
struct MapDumb {
    handle: u32,
    _pad: u32,
    offset: u64,
}

#[repr(C)]
#[derive(Default)]
struct Handle {
    handle: u32,
    _pad: u32,
}

#[repr(C)]
#[derive(Default)]
struct PrimeHandle {
    handle: u32,
    flags: u32,
    fd: i32,
}

#[repr(C)]
#[derive(Default)]
struct CardRes {
    fb_id_ptr: u64,
    crtc_id_ptr: u64,
    connector_id_ptr: u64,
    encoder_id_ptr: u64,
    count_fbs: u32,
    count_crtcs: u32,
    count_connectors: u32,
    count_encoders: u32,
    min_width: u32,
    max_width: u32,
    min_height: u32,
    max_height: u32,
}

#[repr(C)]
#[derive(Default)]
struct ModeInfo {
    clock: u32,
    hdisplay: u16,
    hsync_start: u16,
    hsync_end: u16,
    htotal: u16,
    hskew: u16,
    vdisplay: u16,
    vsync_start: u16,
    vsync_end: u16,
    vtotal: u16,
    vscan: u16,
    vrefresh: u32,
    flags: u32,
    type_: u32,
    name: [u8; 32],
}

#[repr(C)]
#[derive(Default)]
struct GetCrtc {
    set_connectors_ptr: u64,
    count_connectors: u32,
    crtc_id: u32,
    fb_id: u32,
    x: u32,
    y: u32,
    gamma_size: u32,
    mode_valid: u32,
    mode: ModeInfo,
}

#[repr(C)]
#[derive(Default)]
struct Auth {
    magic: u32,
}

const SET_CLIENT_CAP: libc::c_ulong = ioc(W, 0x0d, std::mem::size_of::<SetClientCap>());
const GEM_CLOSE: libc::c_ulong = ioc(W, 0x09, std::mem::size_of::<Handle>());
const AUTH_MAGIC: libc::c_ulong = ioc(W, 0x11, std::mem::size_of::<Auth>());
const DROP_MASTER: libc::c_ulong = ioc(NONE, 0x1f, 0);
const PRIME_HANDLE_TO_FD: libc::c_ulong = ioc(RW, 0x2d, std::mem::size_of::<PrimeHandle>());
const GETRESOURCES: libc::c_ulong = ioc(RW, 0xa0, std::mem::size_of::<CardRes>());
const GETCRTC: libc::c_ulong = ioc(RW, 0xa1, std::mem::size_of::<GetCrtc>());
const RMFB: libc::c_ulong = ioc(RW, 0xaf, 4);
const CREATE_DUMB: libc::c_ulong = ioc(RW, 0xb2, std::mem::size_of::<CreateDumb>());
const MAP_DUMB: libc::c_ulong = ioc(RW, 0xb3, std::mem::size_of::<MapDumb>());
const DESTROY_DUMB: libc::c_ulong = ioc(RW, 0xb4, 4);
const GETPLANERESOURCES: libc::c_ulong = ioc(RW, 0xb5, std::mem::size_of::<GetPlaneRes>());
const GETPLANE: libc::c_ulong = ioc(RW, 0xb6, std::mem::size_of::<GetPlane>());
const SETPLANE: libc::c_ulong = ioc(RW, 0xb7, std::mem::size_of::<SetPlane>());
const ADDFB2: libc::c_ulong = ioc(RW, 0xb8, std::mem::size_of::<FbCmd2>());
const GETFB2: libc::c_ulong = ioc(RW, 0xce, std::mem::size_of::<FbCmd2>());

const CLIENT_CAP_UNIVERSAL_PLANES: u64 = 2;
pub const XRGB8888: u32 = u32::from_le_bytes(*b"XR24");
pub const ARGB8888: u32 = u32::from_le_bytes(*b"AR24");
const DRM_CLOEXEC: u32 = libc::O_CLOEXEC as u32;
const DRM_RDWR: u32 = libc::O_RDWR as u32;

fn ioctl<T>(fd: RawFd, req: libc::c_ulong, arg: &mut T) -> io::Result<()> {
    loop {
        let r = unsafe { libc::ioctl(fd, req as _, arg as *mut T) };
        if r == 0 {
            return Ok(());
        }
        let e = io::Error::last_os_error();
        if e.raw_os_error() != Some(libc::EINTR) && e.raw_os_error() != Some(libc::EAGAIN) {
            return Err(e);
        }
    }
}

/// The name of a fourcc for the log ("AR24").
pub fn fourcc(f: u32) -> String {
    f.to_le_bytes().iter().map(|&b| b as char).collect()
}

/// A mapping that is unmapped on drop.
pub struct Map {
    ptr: *mut u8,
    len: usize,
}

impl Map {
    fn new(fd: RawFd, len: usize, offset: i64, write: bool) -> Option<Map> {
        let prot = libc::PROT_READ | if write { libc::PROT_WRITE } else { 0 };
        let p = unsafe { libc::mmap(std::ptr::null_mut(), len, prot, libc::MAP_SHARED, fd, offset) };
        (p != libc::MAP_FAILED).then(|| Map { ptr: p.cast(), len })
    }

    pub fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.ptr, self.len) }
    }

    pub fn bytes_mut(&mut self) -> &mut [u8] {
        unsafe { std::slice::from_raw_parts_mut(self.ptr, self.len) }
    }
}

impl Drop for Map {
    fn drop(&mut self) {
        unsafe { libc::munmap(self.ptr.cast(), self.len) };
    }
}

/// The processes of a process group (from /proc/<pid>/stat), lowest pid first.
pub fn group_members(pgid: i32) -> Vec<i32> {
    let mut v: Vec<i32> = fs::read_dir("/proc")
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| e.file_name().to_str()?.parse::<i32>().ok())
        .filter(|pid| {
            fs::read_to_string(format!("/proc/{pid}/stat"))
                .ok()
                .and_then(|s| s.rsplit_once(')').map(|(_, r)| r.to_string()))
                .and_then(|r| r.split_whitespace().nth(2)?.parse::<i32>().ok())
                == Some(pgid)
        })
        .collect();
    v.sort();
    v
}

/// The DRM card files the group has open: (pid, fd number, path), without touching them.
pub fn group_cards(pgid: i32) -> Vec<(i32, i32, PathBuf)> {
    let mut out = Vec::new();
    for pid in group_members(pgid) {
        let Ok(entries) = fs::read_dir(format!("/proc/{pid}/fd")) else { continue };
        for e in entries.flatten() {
            let Ok(target) = fs::read_link(e.path()) else { continue };
            if !target.to_string_lossy().starts_with("/dev/dri/card") {
                continue;
            }
            if let Some(n) = e.file_name().to_str().and_then(|s| s.parse::<i32>().ok()) {
                out.push((pid, n, target));
            }
        }
    }
    out
}

fn rdev(fd: RawFd) -> Option<u64> {
    let mut st: libc::stat = unsafe { std::mem::zeroed() };
    (unsafe { libc::fstat(fd, &mut st) } == 0).then_some(st.st_rdev as u64)
}

/// True when `fd` is the current DRM master: AUTH_MAGIC is a master-only ioctl, so a file
/// that is not the master gets EACCES before the magic (0, never valid) is even looked at.
fn is_master(fd: RawFd) -> bool {
    let mut a = Auth { magic: 0 };
    match ioctl(fd, AUTH_MAGIC, &mut a) {
        Err(e) => e.raw_os_error() != Some(libc::EACCES),
        Ok(()) => true,
    }
}

/// A plane as GETPLANE shows it.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct PlaneInfo {
    pub id: u32,
    pub crtc_id: u32,
    pub fb_id: u32,
    pub possible_crtcs: u32,
    pub formats: Vec<u32>,
}

impl PlaneInfo {
    fn has(&self, f: u32) -> bool {
        self.formats.contains(&f)
    }
}

/// The plane with the game's picture: the first active plane on `crtc` whose framebuffer is
/// not one of ours (the menu puts ours on that same plane, the bar and the hint on others).
pub fn game_plane<'a>(planes: &'a [PlaneInfo], crtc: u32, ours: &[u32]) -> Option<&'a PlaneInfo> {
    planes.iter().find(|p| p.crtc_id == crtc && p.fb_id != 0 && !ours.contains(&p.fb_id))
}

/// The (plane, format) pairs to try for an overlay of ours, best first (device-fixes 9.14).
///
/// A plane qualifies when it can sit on our CRTC (`crtc_bit` of possible_crtcs) and is free,
/// or is `current` (the plane this overlay is already on); `skip` holds the planes nobody
/// may take (our other overlay's). Every plane with per-pixel alpha (ARGB8888) comes first;
/// then the same planes opaque (XRGB8888). The second round exists for sun4i-drm: the A33
/// backend blends at most two planes with alpha (sun4i_backend_atomic_check: "Too many planes
/// with alpha"), and SDL's KMSDRM (LÖVE) already puts an ARGB8888 picture on the primary
/// plane, so a second overlay with alpha (the hint over the bar) gets EINVAL from the driver
/// (boot 193: "plane 45: Invalid argument"). An opaque overlay costs no alpha slot.
pub fn overlay_choices(planes: &[PlaneInfo], crtc_bit: u32, current: Option<u32>, skip: &[u32]) -> Vec<(u32, u32)> {
    let usable: Vec<&PlaneInfo> = planes
        .iter()
        .filter(|p| p.possible_crtcs & (1 << crtc_bit) != 0)
        .filter(|p| !skip.contains(&p.id))
        .filter(|p| Some(p.id) == current || (p.fb_id == 0 && p.crtc_id == 0))
        .collect();
    let mut out = Vec::new();
    for fmt in [ARGB8888, XRGB8888] {
        // the plane we are on first, so a renewal does not move to another plane
        let mut round: Vec<&&PlaneInfo> = usable.iter().filter(|p| p.has(fmt)).collect();
        round.sort_by_key(|p| (Some(p.id) != current, p.id));
        out.extend(round.into_iter().map(|p| (p.id, fmt)));
    }
    out
}

/// Every plane of the card (universal planes: the primary and the cursor ones too).
pub fn read_planes(fd: RawFd) -> Vec<PlaneInfo> {
    let mut ids = [0u32; 32];
    let mut res = GetPlaneRes { plane_id_ptr: ids.as_mut_ptr() as u64, count_planes: ids.len() as u32, _pad: 0 };
    if ioctl(fd, GETPLANERESOURCES, &mut res).is_err() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for &id in ids.iter().take(res.count_planes.min(32) as usize) {
        let mut formats = [0u32; 64];
        let mut p = GetPlane { plane_id: id, format_type_ptr: formats.as_mut_ptr() as u64, count_format_types: formats.len() as u32, ..Default::default() };
        if ioctl(fd, GETPLANE, &mut p).is_err() {
            continue;
        }
        let n = p.count_format_types.min(64) as usize;
        out.push(PlaneInfo { id, crtc_id: p.crtc_id, fb_id: p.fb_id, possible_crtcs: p.possible_crtcs, formats: formats[..n].to_vec() });
    }
    out
}

/// The CRTCs of the card, in the order of possible_crtcs' bits.
fn crtcs(fd: RawFd) -> Vec<u32> {
    let mut ids = [0u32; 8];
    let mut res = CardRes { crtc_id_ptr: ids.as_mut_ptr() as u64, count_crtcs: ids.len() as u32, ..Default::default() };
    if ioctl(fd, GETRESOURCES, &mut res).is_err() {
        return Vec::new();
    }
    ids[..res.count_crtcs.min(8) as usize].to_vec()
}

/// One plane's new picture: `fb` (0: off) shown at `x, y` with `w x h` pixels taken from
/// `src_x, src_y` of the framebuffer (no scaling).
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct PlaneSet {
    pub plane: u32,
    pub crtc: u32,
    pub fb: u32,
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
    pub src_x: u32,
    pub src_y: u32,
}

fn set_plane(fd: RawFd, s: &PlaneSet) -> io::Result<()> {
    let on = s.fb != 0;
    let mut sp = SetPlane {
        plane_id: s.plane,
        crtc_id: if on { s.crtc } else { 0 },
        fb_id: s.fb,
        crtc_x: if on { s.x } else { 0 },
        crtc_y: if on { s.y } else { 0 },
        crtc_w: if on { s.w } else { 0 },
        crtc_h: if on { s.h } else { 0 },
        src_x: if on { s.src_x << 16 } else { 0 },
        src_y: if on { s.src_y << 16 } else { 0 },
        src_w: if on { s.w << 16 } else { 0 },
        src_h: if on { s.h << 16 } else { 0 },
        ..Default::default()
    };
    // a page flip of the game may still be pending: retry up to 200 ms on EBUSY
    let end = Instant::now() + Duration::from_millis(200);
    loop {
        match ioctl(fd, SETPLANE, &mut sp) {
            Err(e) if e.raw_os_error() == Some(libc::EBUSY) && Instant::now() < end => std::thread::sleep(Duration::from_millis(5)),
            r => return r,
        }
    }
}

/// Our own DRM file: the buffers, the plane list, the screen's mode. Never the master.
pub struct Card {
    fd: OwnedFd,
    rdev: u64,
}

impl Card {
    /// Opens `path` (the card the game has open, so the game is the master already) and drops
    /// the master at once if the open made us the master anyway (the game between closing
    /// and reopening its card): the screen stays the game's.
    pub fn open(path: &Path) -> io::Result<Card> {
        use std::os::unix::ffi::OsStrExt;
        let c = std::ffi::CString::new(path.as_os_str().as_bytes()).map_err(|_| io::Error::from(io::ErrorKind::InvalidInput))?;
        let fd = unsafe { libc::open(c.as_ptr(), libc::O_RDWR | libc::O_CLOEXEC) };
        if fd < 0 {
            return Err(io::Error::last_os_error());
        }
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        let mut none = 0u8;
        if ioctl(fd.as_raw_fd(), DROP_MASTER, &mut none).is_ok() {
            eprintln!("lume-menu: {} opened as the master: dropped it", path.display());
        }
        let mut cap = SetClientCap { capability: CLIENT_CAP_UNIVERSAL_PLANES, value: 1 };
        let _ = ioctl(fd.as_raw_fd(), SET_CLIENT_CAP, &mut cap);
        let rdev = rdev(fd.as_raw_fd()).unwrap_or(0);
        Ok(Card { fd, rdev })
    }

    /// The KMS card among those the game has open (lima's card has no CRTC).
    pub fn of_group(pgid: i32) -> Option<Card> {
        let mut seen: Vec<PathBuf> = Vec::new();
        for (_, _, path) in group_cards(pgid) {
            if seen.contains(&path) {
                continue;
            }
            seen.push(path.clone());
            if let Ok(c) = Card::open(&path) {
                if !crtcs(c.raw()).is_empty() {
                    return Some(c);
                }
            }
        }
        None
    }

    pub fn raw(&self) -> RawFd {
        self.fd.as_raw_fd()
    }

    /// The first CRTC with a mode set: (id, its bit in possible_crtcs, width, height).
    pub fn active_crtc(&self) -> Option<(u32, u32, u32, u32)> {
        for (i, id) in crtcs(self.raw()).into_iter().enumerate() {
            let mut c = GetCrtc { crtc_id: id, ..Default::default() };
            if ioctl(self.raw(), GETCRTC, &mut c).is_ok() && c.mode_valid != 0 && c.mode.hdisplay > 0 && c.mode.vdisplay > 0 {
                return Some((id, i as u32, c.mode.hdisplay as u32, c.mode.vdisplay as u32));
            }
        }
        None
    }

    pub fn planes(&self) -> Vec<PlaneInfo> {
        read_planes(self.raw())
    }
}

/// One dumb buffer of ours with an opaque and an alpha framebuffer on it, mapped for drawing.
/// Freed on drop (the CMA ran out in the J1 without that); dropped before the card.
pub struct Buffer {
    fd: RawFd,
    handle: u32,
    pub xrgb: u32,
    pub argb: u32,
    pub width: u32,
    pub height: u32,
    pub pitch: usize,
    map: Option<Map>,
}

impl Buffer {
    pub fn new(card: &Card, width: u32, height: u32) -> io::Result<Buffer> {
        let fd = card.raw();
        let mut cd = CreateDumb { width, height, bpp: 32, ..Default::default() };
        ioctl(fd, CREATE_DUMB, &mut cd)?;
        // kept at once, so a failure below still frees it on drop
        let mut b = Buffer { fd, handle: cd.handle, xrgb: 0, argb: 0, width, height, pitch: cd.pitch as usize, map: None };
        let mut md = MapDumb { handle: cd.handle, ..Default::default() };
        ioctl(fd, MAP_DUMB, &mut md)?;
        b.map = Map::new(fd, cd.size as usize, md.offset as i64, true);
        if b.map.is_none() {
            return Err(io::Error::last_os_error());
        }
        for (fmt, slot) in [(XRGB8888, 0), (ARGB8888, 1)] {
            let mut add = FbCmd2 { width, height, pixel_format: fmt, ..Default::default() };
            add.handles[0] = cd.handle;
            add.pitches[0] = cd.pitch;
            match ioctl(fd, ADDFB2, &mut add) {
                Ok(()) if slot == 0 => b.xrgb = add.fb_id,
                Ok(()) => b.argb = add.fb_id,
                // no plane takes ARGB8888: the overlays go opaque
                Err(_) if slot == 1 => {}
                Err(e) => return Err(e),
            }
        }
        Ok(b)
    }

    pub fn pixels(&mut self) -> &mut [u8] {
        self.map.as_mut().expect("mapped").bytes_mut()
    }

    /// The framebuffer of this buffer in `fmt`.
    pub fn fb(&self, fmt: u32) -> u32 {
        if fmt == ARGB8888 { self.argb } else { self.xrgb }
    }
}

impl Drop for Buffer {
    fn drop(&mut self) {
        self.map = None;
        for fb in [self.xrgb, self.argb] {
            if fb != 0 {
                let mut id = fb;
                let _ = ioctl(self.fd, RMFB, &mut id);
            }
        }
        let mut h = self.handle;
        let _ = ioctl(self.fd, DESTROY_DUMB, &mut h);
    }
}

/// A duplicate of the game's master DRM file, for one operation.
pub struct GameFile {
    fd: OwnedFd,
}

impl GameFile {
    fn try_dup(pid: i32, n: i32, rdev_want: Option<u64>) -> Result<GameFile, String> {
        // the number may now hold another file: only a card of the same device counts
        let target = fs::read_link(format!("/proc/{pid}/fd/{n}")).map_err(|e| format!("{pid}/{n}: {e}"))?;
        if !target.to_string_lossy().starts_with("/dev/dri/card") {
            return Err(format!("{pid}/{n}: not a DRM card"));
        }
        let pidfd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) } as i32;
        if pidfd < 0 {
            return Err(format!("pidfd_open {pid}: {}", io::Error::last_os_error()));
        }
        let pidfd = unsafe { OwnedFd::from_raw_fd(pidfd) };
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_getfd, pidfd.as_raw_fd(), n, 0) } as i32;
        if fd < 0 {
            return Err(format!("pidfd_getfd {pid}/{n}: {}", io::Error::last_os_error()));
        }
        let fd = unsafe { OwnedFd::from_raw_fd(fd) };
        if rdev_want.is_some() && rdev(fd.as_raw_fd()) != rdev_want {
            return Err(format!("{pid}/{n}: another DRM device"));
        }
        if !is_master(fd.as_raw_fd()) {
            return Err(format!("{pid}/{n}: not the DRM master"));
        }
        Ok(GameFile { fd })
    }

    /// The group's file that is the DRM master now: `last` (pid, fd number) first, which is
    /// a handful of syscalls, then every card file of the group. `card` (ours) names the
    /// device; None takes any card that is the master.
    pub fn find(pgid: i32, card: Option<&Card>, last: &mut Option<(i32, i32)>) -> Result<GameFile, String> {
        let want = card.map(|c| c.rdev);
        if let Some((pid, n)) = *last {
            if let Ok(f) = GameFile::try_dup(pid, n, want) {
                return Ok(f);
            }
        }
        let mut why = String::from("no process of the group has a DRM card open");
        for (pid, n, _) in group_cards(pgid) {
            match GameFile::try_dup(pid, n, want) {
                Ok(f) => {
                    *last = Some((pid, n));
                    return Ok(f);
                }
                Err(e) => why = e,
            }
        }
        *last = None;
        Err(why)
    }

    pub fn raw(&self) -> RawFd {
        self.fd.as_raw_fd()
    }

    pub fn set_plane(&self, s: &PlaneSet) -> io::Result<()> {
        set_plane(self.raw(), s)
    }

    /// The framebuffer `fb_id` with a handle in this file (only the master gets handles).
    pub fn frame(&self, fb_id: u32) -> Option<Frame<'_>> {
        let mut fb = FbCmd2 { fb_id, ..Default::default() };
        ioctl(self.raw(), GETFB2, &mut fb).ok()?;
        (fb.handles[0] != 0).then_some(Frame { file: self, fb })
    }
}

/// A framebuffer of the game seen through its file; the handle GETFB2 opened is closed on drop.
pub struct Frame<'a> {
    file: &'a GameFile,
    pub fb: FbCmd2,
}

impl Frame<'_> {
    /// Maps the picture for reading: a PRIME dma-buf first, then MAP_DUMB.
    pub fn map(&self) -> Option<Map> {
        let fd = self.file.raw();
        let len = self.fb.pitches[0] as usize * self.fb.height as usize;
        for flags in [DRM_CLOEXEC | DRM_RDWR, DRM_CLOEXEC] {
            let mut p = PrimeHandle { handle: self.fb.handles[0], flags, fd: -1 };
            if ioctl(fd, PRIME_HANDLE_TO_FD, &mut p).is_ok() {
                let dmabuf = unsafe { OwnedFd::from_raw_fd(p.fd) };
                if let Some(m) = Map::new(dmabuf.as_raw_fd(), len, 0, false) {
                    return Some(m);
                }
            }
        }
        let mut md = MapDumb { handle: self.fb.handles[0], ..Default::default() };
        ioctl(fd, MAP_DUMB, &mut md).ok()?;
        Map::new(fd, len, md.offset as i64, false)
    }
}

impl Drop for Frame<'_> {
    fn drop(&mut self) {
        let mut c = Handle { handle: self.fb.handles[0], _pad: 0 };
        let _ = ioctl(self.file.raw(), GEM_CLOSE, &mut c);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ioctl_numbers_match_the_kernel_uapi() {
        // values of the C macros on Linux (drm.h, drm_mode.h), any architecture
        assert_eq!(SET_CLIENT_CAP, 0x4010_640d);
        assert_eq!(AUTH_MAGIC, 0x4004_6411);
        assert_eq!(DROP_MASTER, 0x641f);
        assert_eq!(GETPLANERESOURCES, 0xc010_64b5);
        assert_eq!(GETPLANE, 0xc020_64b6);
        assert_eq!(SETPLANE, 0xc030_64b7);
        assert_eq!(ADDFB2, 0xc068_64b8);
        assert_eq!(GETFB2, 0xc068_64ce);
        assert_eq!(CREATE_DUMB, 0xc020_64b2);
        assert_eq!(MAP_DUMB, 0xc010_64b3);
        assert_eq!(DESTROY_DUMB, 0xc004_64b4);
        assert_eq!(RMFB, 0xc004_64af);
        assert_eq!(GEM_CLOSE, 0x4008_6409);
        assert_eq!(PRIME_HANDLE_TO_FD, 0xc00c_642d);
        assert_eq!(GETRESOURCES, 0xc040_64a0);
        assert_eq!(GETCRTC, 0xc068_64a1);
    }

    #[test]
    fn group_members_finds_our_own_group() {
        let me = std::process::id() as i32;
        let pgid = unsafe { libc::getpgrp() };
        assert!(group_members(pgid).contains(&me));
        assert!(group_members(-5).is_empty());
        assert!(group_cards(-5).is_empty());
    }

    fn plane(id: u32, crtc_id: u32, fb_id: u32, formats: &[u32]) -> PlaneInfo {
        PlaneInfo { id, crtc_id, fb_id, possible_crtcs: 1, formats: formats.to_vec() }
    }

    /// sun4i-drm on the A33 (GA36): four layers, the primary and three overlays, all with
    /// both formats; the game's picture on the primary.
    fn sun4i() -> Vec<PlaneInfo> {
        let f = [ARGB8888, XRGB8888];
        vec![plane(31, 41, 90, &f), plane(33, 0, 0, &f), plane(35, 0, 0, &f), plane(37, 0, 0, &f)]
    }

    #[test]
    fn overlays_try_alpha_on_every_plane_then_opaque() {
        let c = overlay_choices(&sun4i(), 0, None, &[]);
        assert_eq!(c, [(33, ARGB8888), (35, ARGB8888), (37, ARGB8888), (33, XRGB8888), (35, XRGB8888), (37, XRGB8888)]);
    }

    #[test]
    fn the_primary_and_the_other_overlay_are_never_taken() {
        let mut p = sun4i();
        // the bar is on 33 already
        p[1].crtc_id = 41;
        p[1].fb_id = 120;
        // the hint: neither the game's plane nor the bar's
        let hint = overlay_choices(&p, 0, None, &[33]);
        assert!(hint.iter().all(|&(id, _)| id == 35 || id == 37), "{hint:?}");
        // the bar's renewal: its own plane first, in each format
        let bar = overlay_choices(&p, 0, Some(33), &[]);
        assert_eq!(bar[0], (33, ARGB8888));
        assert_eq!(bar.iter().position(|&c| c == (33, XRGB8888)), Some(3));
    }

    #[test]
    fn planes_of_another_crtc_or_without_the_formats_are_left_out() {
        // rockchip VOP of the RK3326 (R36S): win0 primary, win1 overlay, win2 cursor; one
        // plane only for the other CRTC (bit 1), one without any of our formats
        let f = [XRGB8888, ARGB8888];
        let mut p = vec![plane(32, 50, 91, &f), plane(38, 0, 0, &f), plane(44, 0, 0, &f), plane(46, 0, 0, &f), plane(48, 0, 0, &[u32::from_le_bytes(*b"NV12")])];
        p[3].possible_crtcs = 2;
        assert_eq!(overlay_choices(&p, 0, None, &[]), [(38, ARGB8888), (44, ARGB8888), (38, XRGB8888), (44, XRGB8888)]);
        assert!(overlay_choices(&[], 0, None, &[]).is_empty());
    }

    #[test]
    fn the_game_plane_is_the_first_active_one_not_ours() {
        let mut p = sun4i();
        assert_eq!(game_plane(&p, 41, &[]).map(|p| p.id), Some(31));
        // the menu on the primary (our fb 200) and the bar on 33: the game's plane is still
        // found by its crtc while the bar's is skipped
        p[0].fb_id = 200;
        p[1].crtc_id = 41;
        p[1].fb_id = 120;
        assert_eq!(game_plane(&p, 41, &[200, 120]), None);
        assert_eq!(game_plane(&p, 41, &[120]).map(|p| p.id), Some(31));
        assert_eq!(game_plane(&p, 99, &[]), None);
    }
}
