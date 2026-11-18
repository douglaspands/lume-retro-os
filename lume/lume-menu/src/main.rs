//! lume-menu: the Lume menu over a game, drawn by the system on the game's own screen
//! (lume-hud-actions D14, task 3.4). lume-run starts it only while the menu is open, with
//! the game already paused and its process group stopped:
//!
//! ```text
//! lume-menu PGID [--hints "Choose|Back"] [--warn "Force close"]
//!   stdin   one line per change: "title|item|...|focus"; "-" or the end of stdin closes
//!   stdout  "ok" once the menu is on the screen, or "fail <why>" (exit 3): lume-run then
//!           falls back to RetroArch's LUME_MENU widget
//! ```
//!
//! It duplicates the game's DRM file (pidfd_getfd: same user, no capability), copies the
//! last frame from the primary plane, draws the menu over it in software into a buffer of
//! its own and puts that buffer on the plane. On close it puts the game's framebuffer back
//! and frees what it made in the game's file, then exits: nothing runs with the menu closed.
//!
//! The status bar (D6; drawn by the system since 2026-11-17, over any game):
//!
//! ```text
//! lume-menu --hud PGID
//!   stdin   one line per second: the bar's text ("FPS 59.7|CPU 9% 1008|..."); "-" or the
//!           end of stdin takes the bar away
//!   stdout  "ok" once the bar is on the screen, or "fail <why>" (exit 3)
//! ```
//!
//! The game keeps running: the bar lives on a free overlay plane with alpha above the game's
//! primary plane. lume-run must end it when the game ends, since the duplicated DRM file
//! keeps the screen's master open until it is closed.

mod bar;
mod draw;
mod drm;

use std::io::{BufRead, Write};
use std::process::ExitCode;

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

/// `--hud PGID`: the status bar until stdin ends.
fn hud(pgid: i32) -> ExitCode {
    let Some(fonts) = draw::Fonts::bundled() else { return fail("no font in /usr/share/lume/fonts") };
    let screen = match drm::Screen::of_group(pgid) {
        Ok(s) => s,
        Err(why) => return fail(&why),
    };
    let screen_h = screen.fb.height;
    let mut strip = match drm::Bar::new(&screen, bar::height(screen_h)) {
        Ok(b) => b,
        Err(why) => return fail(&why),
    };
    let (w, h, pitch) = (strip.width as usize, strip.height as usize, strip.pitch);
    let mut ok_sent = false;
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { break };
        if line.trim() == "-" {
            break;
        }
        {
            let px = strip.back_pixels();
            let mut s = bar::Strip { px, w, h, pitch };
            bar::draw(&mut s, &fonts, &line, screen_h as f32);
        }
        if let Err(e) = strip.present() {
            if !ok_sent {
                return fail(&format!("SETPLANE: {e}"));
            }
            // the game may be changing modes: the next line tries again
            eprintln!("lume-menu: bar not shown: {e}");
            continue;
        }
        if !ok_sent {
            say("ok");
            ok_sent = true;
        }
    }
    drop(strip);
    drop(screen);
    ExitCode::SUCCESS
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().collect();
    if args.get(1).map(String::as_str) == Some("--hud") {
        return match args.get(2).and_then(|a| a.parse::<i32>().ok()).filter(|p| *p > 0) {
            Some(pgid) => hud(pgid),
            None => {
                eprintln!("usage: lume-menu --hud PGID");
                ExitCode::from(2)
            }
        };
    }
    let Some(pgid) = args.get(1).and_then(|a| a.parse::<i32>().ok()).filter(|p| *p > 0) else {
        eprintln!("usage: lume-menu PGID [--hints \"Choose|Back\"] [--warn TEXT]");
        return ExitCode::from(2);
    };
    let mut hints = ("Select".to_string(), "Back".to_string());
    let mut warn: Option<String> = None;
    let mut i = 2;
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
    let Some(fonts) = draw::Fonts::bundled() else { return fail("no font in /usr/share/lume/fonts") };
    let screen = match drm::Screen::of_group(pgid) {
        Ok(s) => s,
        Err(why) => return fail(&why),
    };
    let (w, h) = (screen.fb.width as usize, screen.fb.height as usize);
    // the game's last frame, converted once to XRGB8888
    let mut frame = vec![0u8; w * h * 4];
    {
        let mut img = draw::Image { px: &mut frame, w, h, pitch: w * 4 };
        if let Some(src) = screen.map_frame() {
            draw::copy_frame(&mut img, src.bytes(), screen.fb.pitches[0] as usize, screen.fb.pixel_format);
        }
    }
    let mut ov = match drm::Overlay::new(&screen) {
        Ok(o) => o,
        Err(e) => return fail(&format!("our buffer: {e}")),
    };
    let pitch = ov.pitch;
    let mut ok_sent = false;
    // the base (dimmed game, panel, title, hints) of the current list, drawn once
    let mut base: Vec<u8> = Vec::new();
    let mut base_key: Option<(String, Vec<String>)> = None;
    let mut next = vec![0u8; w * h * 4];
    for line in std::io::stdin().lock().lines() {
        let Ok(line) = line else { break };
        if line.trim() == "-" {
            break;
        }
        let Some(st) = draw::parse(&line) else { continue };
        let t = std::time::Instant::now();
        let key = (st.title.clone(), st.items.clone());
        if base_key.as_ref() != Some(&key) {
            base = frame.clone();
            let mut img = draw::Image { px: &mut base, w, h, pitch: w * 4 };
            draw::draw_base(&mut img, &fonts, &st, (&hints.0, &hints.1));
            base_key = Some(key);
        }
        next.copy_from_slice(&base);
        let mut img = draw::Image { px: &mut next, w, h, pitch: w * 4 };
        draw::draw_items(&mut img, &fonts, &st, warn.as_deref());
        // the first picture fades in over a few frames (the user asked for a smoother
        // appearance, J2 on the GA36); later ones are drawn off the screen and swapped in
        let steps: &[u32] = if ok_sent { &[256] } else { &[72, 140, 200, 256] };
        for &a in steps {
            let buf = ov.back_pixels();
            for y in 0..h {
                let (row, from, to) = (y * pitch, &frame[y * w * 4..(y + 1) * w * 4], &next[y * w * 4..(y + 1) * w * 4]);
                if a == 256 {
                    buf[row..row + w * 4].copy_from_slice(to);
                } else {
                    draw::mix_into(&mut buf[row..row + w * 4], from, to, a);
                }
            }
            if let Err(e) = ov.present() {
                return fail(&format!("SETPLANE: {e}"));
            }
        }
        eprintln!("lume-menu: {} in {} ms", if ok_sent { "redraw" } else { "shown" }, t.elapsed().as_millis());
        if !ok_sent {
            say("ok");
            ok_sent = true;
        }
    }
    // dropping the overlay and the screen gives the plane back and frees our buffers
    drop(ov);
    drop(screen);
    ExitCode::SUCCESS
}
