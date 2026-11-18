//! lume-menu: what the system draws over a game on the game's own screen (lume-hud-actions
//! D14, D6; device-fixes 9.14): the Lume menu, the status bar and the chord hint.
//!
//! ```text
//! lume-menu --serve PGID [--hints "Choose|Back"] [--warn "Force close"]
//!     one process per game, started by lume-run with the game; protocol in serve.rs
//! lume-menu --shot PGID OUT.png
//!     the picture on the game's screen (its plane, without the bar or the menu) as PNG
//! ```
//!
//! The server makes its buffers once, in a DRM file of its own, as soon as the game has a
//! screen, then blocks on its stdin. To show something it duplicates the game's master DRM
//! file (pidfd_getfd: the same user, no capability; the card is crw-rw---- root:video and
//! the user `game` is in `video`), sets the plane, and closes the duplicate at once.

mod bar;
mod draw;
mod drm;
mod serve;

use std::io::Write;
use std::os::fd::AsRawFd;
use std::process::ExitCode;
use std::time::{Duration, Instant};

fn say(s: &str) {
    let mut out = std::io::stdout().lock();
    let _ = writeln!(out, "{s}");
    let _ = out.flush();
}

fn fail(why: &str) -> ExitCode {
    say(&format!("fail {why}"));
    eprintln!("lume-menu: {why}");
    ExitCode::from(3)
}

/// `--shot PGID OUT.png`: the picture on the game's screen (its plane, so without the bar,
/// the hint or the menu), saved as PNG; the game keeps running. Written to a temporary name
/// and renamed, so a cut never leaves half a picture.
fn shot(pgid: i32, out: &std::path::Path) -> ExitCode {
    let Some(card) = drm::Card::of_group(pgid) else { return fail("no process of the group has a DRM card open") };
    let Some((crtc, _, _, _)) = card.active_crtc() else { return fail("no screen") };
    let mut last = None;
    let file = match drm::GameFile::find(pgid, Some(&card), &mut last) {
        Ok(f) => f,
        Err(why) => return fail(&why),
    };
    let planes = card.planes();
    let Some(gp) = drm::game_plane(&planes, crtc, &[]) else { return fail("no plane with the game's picture") };
    let Some(fr) = file.frame(gp.fb_id) else { return fail("cannot read the game's framebuffer") };
    let (w, h) = (fr.fb.width as usize, fr.fb.height as usize);
    let mut frame = vec![0u8; w * h * 4];
    {
        let Some(src) = fr.map() else { return fail("cannot map the game's framebuffer") };
        let mut img = draw::Image { px: &mut frame, w, h, pitch: w * 4 };
        draw::copy_frame(&mut img, src.bytes(), fr.fb.pitches[0] as usize, fr.fb.pixel_format);
    }
    drop(fr);
    drop(file);
    // XRGB8888 (B G R X) to RGB
    let rgb: Vec<u8> = frame.chunks_exact(4).flat_map(|p| [p[2], p[1], p[0]]).collect();
    let tmp = out.with_extension("png.part");
    let write = || -> Result<(), String> {
        if let Some(dir) = out.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        let f = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
        let mut enc = png::Encoder::new(std::io::BufWriter::new(f), w as u32, h as u32);
        enc.set_color(png::ColorType::Rgb);
        enc.set_depth(png::BitDepth::Eight);
        enc.set_compression(png::Compression::Fast);
        let mut wr = enc.write_header().map_err(|e| e.to_string())?;
        wr.write_image_data(&rgb).map_err(|e| e.to_string())?;
        wr.finish().map_err(|e| e.to_string())?;
        std::fs::rename(&tmp, out).map_err(|e| e.to_string())
    };
    match write() {
        Ok(()) => {
            say(&format!("ok {}", out.display()));
            ExitCode::SUCCESS
        }
        Err(why) => {
            let _ = std::fs::remove_file(&tmp);
            fail(&format!("{}: {why}", out.display()))
        }
    }
}

/// How long the server waits between looks for the game's screen while it has none: often
/// at first (a game opens its screen in its first second or two), then rarely; after
/// `PREPARE_GIVE_UP` it only looks again when a command comes.
fn prepare_wait(since: Duration) -> Duration {
    if since < Duration::from_secs(10) { Duration::from_millis(250) } else { Duration::from_secs(1) }
}
const PREPARE_GIVE_UP: Duration = Duration::from_secs(60);

/// `--serve PGID`: see serve.rs.
fn serve(pgid: i32, hints: (String, String), warn: Option<String>) -> ExitCode {
    let Some(fonts) = draw::Fonts::bundled() else {
        // no answer can come: every "menu" gets a fail, so lume-run falls back at once
        eprintln!("lume-menu: no font in /usr/share/lume/fonts");
        for line in std::io::stdin().lines() {
            if line.is_ok_and(|l| l.starts_with("menu ") && l.trim_end() != "menu -") {
                say("menu fail no font in /usr/share/lume/fonts");
            } else {
                say("menu closed");
            }
        }
        return ExitCode::from(3);
    };
    let mut srv = serve::Server::new(serve::DrmGpu::new(pgid), fonts, hints, warn);
    let started = Instant::now();
    let stdin = std::io::stdin();
    let fd = stdin.as_raw_fd();
    let mut pending: Vec<u8> = Vec::new();
    let mut buf = [0u8; 4096];
    let mut why_logged = String::new();
    loop {
        // nothing runs here once the buffers are made: poll without a timeout
        let since = started.elapsed();
        let timeout = if srv.prepared() || since >= PREPARE_GIVE_UP { -1 } else { prepare_wait(since).as_millis() as i32 };
        let mut p = libc::pollfd { fd, events: libc::POLLIN, revents: 0 };
        let r = unsafe { libc::poll(&mut p, 1, timeout) };
        if r < 0 {
            if std::io::Error::last_os_error().raw_os_error() == Some(libc::EINTR) {
                continue;
            }
            break;
        }
        if r == 0 {
            match srv.prepare() {
                Ok(_) => {}
                Err(e) if e != why_logged => {
                    eprintln!("lume-menu: not ready yet: {e}");
                    why_logged = e;
                }
                Err(_) => {}
            }
            continue;
        }
        let n = unsafe { libc::read(fd, buf.as_mut_ptr().cast(), buf.len()) };
        if n <= 0 {
            break;
        }
        pending.extend_from_slice(&buf[..n as usize]);
        while let Some(i) = pending.iter().position(|&b| b == b'\n') {
            let line: Vec<u8> = pending.drain(..=i).collect();
            let line = String::from_utf8_lossy(&line);
            srv.handle(&line, &mut |l| say(l));
        }
    }
    srv.finish();
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    let mode = args.get(1).map(String::as_str);
    let pgid = args.get(2).and_then(|a| a.parse::<i32>().ok()).filter(|p| *p > 0);
    match (mode, pgid) {
        (Some("--shot"), Some(p)) if args.len() > 3 => shot(p, std::path::Path::new(&args[3])),
        (Some("--serve"), Some(p)) => {
            let mut hints = ("Select".to_string(), "Back".to_string());
            let mut warn: Option<String> = None;
            let mut i = 3;
            while i + 1 < args.len() {
                match args[i].as_str() {
                    "--hints" => {
                        if let Some((a, b)) = args[i + 1].split_once('|') {
                            hints = (a.into(), b.into());
                        }
                    }
                    "--warn" => warn = Some(args[i + 1].clone()),
                    _ => {}
                }
                i += 2;
            }
            serve(p, hints, warn)
        }
        _ => {
            eprintln!("usage: lume-menu --serve PGID [--hints \"Choose|Back\"] [--warn TEXT] | --shot PGID OUT.png");
            ExitCode::from(2)
        }
    }
}
