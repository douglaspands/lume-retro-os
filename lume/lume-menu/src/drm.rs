//! The DRM side of lume-menu (D14): the game's own DRM file through pidfd_getfd, its primary
//! plane's framebuffer, a dumb buffer of ours on that plane, and everything given back.
//! No libdrm: the kernel uapi ioctls, as in r36os-shot and the J1 proof (4.6).

use std::fs;
use std::io;
use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
use std::time::{Duration, Instant};

const fn ioc(dir: u32, nr: u32, size: usize) -> libc::c_ulong {
    ((dir << 30) | ((size as u32) << 16) | ((b'd' as u32) << 8) | nr) as libc::c_ulong
}
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
#[derive(Default, Clone, Copy)]
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

const SET_CLIENT_CAP: libc::c_ulong = ioc(W, 0x0d, std::mem::size_of::<SetClientCap>());
const GEM_CLOSE: libc::c_ulong = ioc(W, 0x09, std::mem::size_of::<Handle>());
const PRIME_HANDLE_TO_FD: libc::c_ulong = ioc(RW, 0x2d, std::mem::size_of::<PrimeHandle>());
const RMFB: libc::c_ulong = ioc(RW, 0xaf, 4);
const CREATE_DUMB: libc::c_ulong = ioc(RW, 0xb2, std::mem::size_of::<CreateDumb>());
const MAP_DUMB: libc::c_ulong = ioc(RW, 0xb3, std::mem::size_of::<MapDumb>());
const DESTROY_DUMB: libc::c_ulong = ioc(RW, 0xb4, 4);
const GETPLANERESOURCES: libc::c_ulong = ioc(RW, 0xb5, std::mem::size_of::<GetPlaneRes>());
const GETPLANE: libc::c_ulong = ioc(RW, 0xb6, std::mem::size_of::<GetPlane>());
const SETPLANE: libc::c_ulong = ioc(RW, 0xb7, std::mem::size_of::<SetPlane>());
const ADDFB2: libc::c_ulong = ioc(RW, 0xb8, std::mem::size_of::<FbCmd2>());
const GETFB2: libc::c_ulong = ioc(RW, 0xce, std::mem::size_of::<FbCmd2>());
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

const GETRESOURCES: libc::c_ulong = ioc(RW, 0xa0, std::mem::size_of::<CardRes>());
const CLIENT_CAP_UNIVERSAL_PLANES: u64 = 2;
const XRGB8888: u32 = u32::from_le_bytes(*b"XR24");
const ARGB8888: u32 = u32::from_le_bytes(*b"AR24");
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

/// The game's screen: its DRM file (a duplicate of the same open file, so master), the
/// active primary plane and the framebuffer on it.
pub struct Screen {
    pub fd: OwnedFd,
    pub plane: u32,
    pub crtc: u32,
    pub fb: FbCmd2,
}

fn plane_with_buffer(fd: RawFd) -> Option<(u32, u32, FbCmd2)> {
    let mut cap = SetClientCap { capability: CLIENT_CAP_UNIVERSAL_PLANES, value: 1 };
    let _ = ioctl(fd, SET_CLIENT_CAP, &mut cap);
    let mut ids = [0u32; 32];
    let mut res = GetPlaneRes { plane_id_ptr: ids.as_mut_ptr() as u64, count_planes: ids.len() as u32, _pad: 0 };
    ioctl(fd, GETPLANERESOURCES, &mut res).ok()?;
    for &id in ids.iter().take(res.count_planes.min(32) as usize) {
        let mut p = GetPlane { plane_id: id, ..Default::default() };
        if ioctl(fd, GETPLANE, &mut p).is_err() || p.fb_id == 0 || p.crtc_id == 0 {
            continue;
        }
        let mut fb = FbCmd2 { fb_id: p.fb_id, ..Default::default() };
        if ioctl(fd, GETFB2, &mut fb).is_ok() && fb.handles[0] != 0 {
            return Some((p.plane_id, p.crtc_id, fb));
        }
    }
    None
}

impl Screen {
    /// Finds the screen of the game's process group: the first card fd of a member that
    /// sees an active plane with a buffer handle.
    pub fn of_group(pgid: i32) -> Result<Screen, String> {
        let mut why = String::from("no process of the group has a DRM card open");
        for pid in group_members(pgid) {
            let pidfd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) } as i32;
            if pidfd < 0 {
                why = format!("pidfd_open {pid}: {}", io::Error::last_os_error());
                continue;
            }
            let pidfd = unsafe { OwnedFd::from_raw_fd(pidfd) };
            let Ok(entries) = fs::read_dir(format!("/proc/{pid}/fd")) else { continue };
            for e in entries.flatten() {
                let target = fs::read_link(e.path()).unwrap_or_default();
                if !target.to_string_lossy().starts_with("/dev/dri/card") {
                    continue;
                }
                let Some(n) = e.file_name().to_str().and_then(|s| s.parse::<i32>().ok()) else { continue };
                let fd = unsafe { libc::syscall(libc::SYS_pidfd_getfd, pidfd.as_raw_fd(), n, 0) } as i32;
                if fd < 0 {
                    why = format!("pidfd_getfd {pid}/{n}: {}", io::Error::last_os_error());
                    continue;
                }
                let fd = unsafe { OwnedFd::from_raw_fd(fd) };
                if let Some((plane, crtc, fb)) = plane_with_buffer(fd.as_raw_fd()) {
                    return Ok(Screen { fd, plane, crtc, fb });
                }
                why = format!("{pid}/{n}: no active plane with a buffer handle");
            }
        }
        Err(why)
    }

    /// Maps the game's framebuffer for reading: a PRIME dma-buf first, then MAP_DUMB.
    pub fn map_frame(&self) -> Option<Map> {
        let fd = self.fd.as_raw_fd();
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

    fn set_plane(&self, fb: u32) -> io::Result<()> {
        let (w, h) = (self.fb.width, self.fb.height);
        let mut sp = SetPlane {
            plane_id: self.plane,
            crtc_id: self.crtc,
            fb_id: fb,
            crtc_w: w,
            crtc_h: h,
            src_w: w << 16,
            src_h: h << 16,
            ..Default::default()
        };
        // a page flip of the game may still be pending: retry up to 200 ms on EBUSY
        let end = Instant::now() + Duration::from_millis(200);
        loop {
            match ioctl(self.fd.as_raw_fd(), SETPLANE, &mut sp) {
                Err(e) if e.raw_os_error() == Some(libc::EBUSY) && Instant::now() < end => {
                    std::thread::sleep(Duration::from_millis(5))
                }
                r => return r,
            }
        }
    }
}

/// One dumb buffer of ours with its framebuffer and mapping.
struct Buf {
    handle: u32,
    fb: u32,
    map: Option<Map>,
}

/// Our two buffers on the game's plane: each change is drawn into the one off the screen and
/// then put on the plane, so the screen never shows a half-drawn menu (it blinked on every
/// move of the focus with one buffer, J2 on the GA36). Dropping it puts the game's
/// framebuffer back and frees everything we made in the game's open file (the CMA ran out in
/// the J1 without that).
pub struct Overlay<'a> {
    screen: &'a Screen,
    bufs: Vec<Buf>,
    /// the buffer on the screen (None: the game's)
    front: Option<usize>,
    pub pitch: usize,
}

impl<'a> Overlay<'a> {
    pub fn new(screen: &'a Screen) -> io::Result<Overlay<'a>> {
        let mut ov = Overlay { screen, bufs: Vec::new(), front: None, pitch: 0 };
        for _ in 0..2 {
            ov.add_buffer()?;
        }
        Ok(ov)
    }

    fn add_buffer(&mut self) -> io::Result<()> {
        let fd = self.screen.fd.as_raw_fd();
        let mut cd = CreateDumb { width: self.screen.fb.width, height: self.screen.fb.height, bpp: 32, ..Default::default() };
        ioctl(fd, CREATE_DUMB, &mut cd)?;
        // kept at once, so a failure below still frees it on drop
        self.bufs.push(Buf { handle: cd.handle, fb: 0, map: None });
        let b = self.bufs.last_mut().unwrap();
        self.pitch = cd.pitch as usize;
        let mut md = MapDumb { handle: cd.handle, ..Default::default() };
        ioctl(fd, MAP_DUMB, &mut md)?;
        b.map = Map::new(fd, cd.size as usize, md.offset as i64, true);
        if b.map.is_none() {
            return Err(io::Error::last_os_error());
        }
        let mut add = FbCmd2 { width: cd.width, height: cd.height, pixel_format: XRGB8888, ..Default::default() };
        add.handles[0] = cd.handle;
        add.pitches[0] = cd.pitch;
        ioctl(fd, ADDFB2, &mut add)?;
        b.fb = add.fb_id;
        Ok(())
    }

    fn back(&self) -> usize {
        match self.front {
            Some(0) => 1,
            _ => 0,
        }
    }

    /// The pixels of the buffer off the screen, to draw the next state into.
    pub fn back_pixels(&mut self) -> &mut [u8] {
        let i = self.back();
        self.bufs[i].map.as_mut().expect("mapped").bytes_mut()
    }

    /// Puts the buffer just drawn on the screen.
    pub fn present(&mut self) -> io::Result<()> {
        let i = self.back();
        self.screen.set_plane(self.bufs[i].fb)?;
        self.front = Some(i);
        Ok(())
    }
}

impl Drop for Overlay<'_> {
    fn drop(&mut self) {
        let fd = self.screen.fd.as_raw_fd();
        if self.front.is_some() {
            let _ = self.screen.set_plane(self.screen.fb.fb_id);
        }
        for b in &mut self.bufs {
            b.map = None;
            if b.fb != 0 {
                let mut id = b.fb;
                let _ = ioctl(fd, RMFB, &mut id);
            }
            let mut h = b.handle;
            let _ = ioctl(fd, DESTROY_DUMB, &mut h);
        }
    }
}

/// The index of `crtc` in the card's CRTC list (the bit of a plane's possible_crtcs).
fn crtc_index(fd: RawFd, crtc: u32) -> Option<u32> {
    let mut crtcs = [0u32; 8];
    let mut res = CardRes { crtc_id_ptr: crtcs.as_mut_ptr() as u64, count_crtcs: crtcs.len() as u32, ..Default::default() };
    ioctl(fd, GETRESOURCES, &mut res).ok()?;
    crtcs.iter().take(res.count_crtcs.min(8) as usize).position(|&c| c == crtc).map(|i| i as u32)
}

/// The planes that could carry the bar: unused, on our CRTC, with ARGB8888 (per-pixel alpha).
fn free_alpha_planes(fd: RawFd, crtc: u32) -> Vec<u32> {
    let Some(idx) = crtc_index(fd, crtc) else { return Vec::new() };
    let mut ids = [0u32; 32];
    let mut res = GetPlaneRes { plane_id_ptr: ids.as_mut_ptr() as u64, count_planes: ids.len() as u32, _pad: 0 };
    if ioctl(fd, GETPLANERESOURCES, &mut res).is_err() {
        return Vec::new();
    }
    let mut out = Vec::new();
    for &id in ids.iter().take(res.count_planes.min(32) as usize) {
        let mut formats = [0u32; 64];
        let mut p = GetPlane { plane_id: id, format_type_ptr: formats.as_mut_ptr() as u64, count_format_types: formats.len() as u32, ..Default::default() };
        if ioctl(fd, GETPLANE, &mut p).is_err() || p.fb_id != 0 || p.crtc_id != 0 || p.possible_crtcs & (1 << idx) == 0 {
            continue;
        }
        if formats.iter().take(p.count_format_types.min(64) as usize).any(|&f| f == ARGB8888) {
            out.push(id);
        }
    }
    out
}

/// The status bar on a free overlay plane of the game's CRTC (lume-hud-actions D6, the
/// user's change of 2026-11-17: drawn by the system, so it shows over any game). The game
/// keeps running and presenting on its primary plane; ours, above it, holds an ARGB strip
/// at the top. Two buffers, each new text drawn into the one off the screen. Dropping it
/// turns the plane off and frees our buffers in the game's file.
pub struct Bar<'a> {
    screen: &'a Screen,
    plane: u32,
    bufs: Vec<Buf>,
    front: Option<usize>,
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub pitch: usize,
}

impl<'a> Bar<'a> {
    /// A strip of the screen's width at the top (the status bar).
    pub fn new(screen: &'a Screen, height: u32) -> Result<Bar<'a>, String> {
        Bar::at(screen, 0, 0, screen.fb.width, height)
    }

    /// A box of `w` x `h` at (`x`, `y`) of the screen (the chord hint, in the middle).
    pub fn at(screen: &'a Screen, x: i32, y: i32, w: u32, h: u32) -> Result<Bar<'a>, String> {
        let fd = screen.fd.as_raw_fd();
        let planes = free_alpha_planes(fd, screen.crtc);
        if planes.is_empty() {
            return Err("no free plane with alpha on the game's CRTC".into());
        }
        let mut bar = Bar { screen, plane: 0, bufs: Vec::new(), front: None, x, y, width: w, height: h, pitch: 0 };
        for _ in 0..2 {
            bar.add_buffer().map_err(|e| format!("our buffer: {e}"))?;
        }
        // the first plane that takes our buffer (a cursor plane, say, may refuse the size)
        let mut why = String::new();
        for p in planes {
            bar.plane = p;
            match bar.set(bar.bufs[0].fb) {
                Ok(()) => {
                    bar.front = Some(0);
                    return Ok(bar);
                }
                Err(e) => why = format!("plane {p}: {e}"),
            }
        }
        bar.plane = 0;
        Err(why)
    }

    fn add_buffer(&mut self) -> io::Result<()> {
        let fd = self.screen.fd.as_raw_fd();
        let mut cd = CreateDumb { width: self.width, height: self.height, bpp: 32, ..Default::default() };
        ioctl(fd, CREATE_DUMB, &mut cd)?;
        self.bufs.push(Buf { handle: cd.handle, fb: 0, map: None });
        let b = self.bufs.last_mut().unwrap();
        self.pitch = cd.pitch as usize;
        let mut md = MapDumb { handle: cd.handle, ..Default::default() };
        ioctl(fd, MAP_DUMB, &mut md)?;
        b.map = Map::new(fd, cd.size as usize, md.offset as i64, true);
        if b.map.is_none() {
            return Err(io::Error::last_os_error());
        }
        // transparent until the first text
        b.map.as_mut().unwrap().bytes_mut().fill(0);
        let mut add = FbCmd2 { width: cd.width, height: cd.height, pixel_format: ARGB8888, ..Default::default() };
        add.handles[0] = cd.handle;
        add.pitches[0] = cd.pitch;
        ioctl(fd, ADDFB2, &mut add)?;
        b.fb = add.fb_id;
        Ok(())
    }

    fn set(&self, fb: u32) -> io::Result<()> {
        let (w, h) = (self.width, self.height);
        let mut sp = SetPlane {
            plane_id: self.plane,
            crtc_id: if fb == 0 { 0 } else { self.screen.crtc },
            fb_id: fb,
            crtc_x: if fb == 0 { 0 } else { self.x },
            crtc_y: if fb == 0 { 0 } else { self.y },
            crtc_w: if fb == 0 { 0 } else { w },
            crtc_h: if fb == 0 { 0 } else { h },
            src_w: if fb == 0 { 0 } else { w << 16 },
            src_h: if fb == 0 { 0 } else { h << 16 },
            ..Default::default()
        };
        let end = Instant::now() + Duration::from_millis(200);
        loop {
            match ioctl(self.screen.fd.as_raw_fd(), SETPLANE, &mut sp) {
                Err(e) if e.raw_os_error() == Some(libc::EBUSY) && Instant::now() < end => {
                    std::thread::sleep(Duration::from_millis(5))
                }
                r => return r,
            }
        }
    }

    fn back(&self) -> usize {
        match self.front {
            Some(0) => 1,
            _ => 0,
        }
    }

    /// The ARGB8888 pixels of the buffer off the screen.
    pub fn back_pixels(&mut self) -> &mut [u8] {
        let i = self.back();
        self.bufs[i].map.as_mut().expect("mapped").bytes_mut()
    }

    /// Puts the buffer just drawn on the plane (again: a mode set of the game may have turned
    /// the plane off, and the next text puts it back).
    pub fn present(&mut self) -> io::Result<()> {
        let i = self.back();
        self.set(self.bufs[i].fb)?;
        self.front = Some(i);
        Ok(())
    }
}

impl Drop for Bar<'_> {
    fn drop(&mut self) {
        let fd = self.screen.fd.as_raw_fd();
        if self.plane != 0 && self.front.is_some() {
            let _ = self.set(0);
        }
        for b in &mut self.bufs {
            b.map = None;
            if b.fb != 0 {
                let mut id = b.fb;
                let _ = ioctl(fd, RMFB, &mut id);
            }
            let mut h = b.handle;
            let _ = ioctl(fd, DESTROY_DUMB, &mut h);
        }
    }
}

impl Drop for Screen {
    fn drop(&mut self) {
        // the handle GETFB2 opened in the game's file
        let mut c = Handle { handle: self.fb.handles[0], _pad: 0 };
        let _ = ioctl(self.fd.as_raw_fd(), GEM_CLOSE, &mut c);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn ioctl_numbers_match_the_kernel_uapi() {
        // values of the C macros on Linux (drm.h, drm_mode.h), any architecture
        assert_eq!(SET_CLIENT_CAP, 0x4010_640d);
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
    }

    #[test]
    fn group_members_finds_our_own_group() {
        let me = std::process::id() as i32;
        let pgid = unsafe { libc::getpgrp() };
        assert!(group_members(pgid).contains(&me));
        assert!(group_members(-5).is_empty());
    }
}
