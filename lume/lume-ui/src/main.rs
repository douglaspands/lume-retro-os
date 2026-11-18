//! lume-ui: the interface of the lume-launcher (lume-launcher D1, D3). Run by lume-run;
//! exits with 0 (Shut down), 64 (open the game of $XDG_RUNTIME_DIR/lume/launch) or 65 (the
//! RetroArch menu). Any other code is a failure.
//!
//! The loop sleeps on a channel: with no input and no animation nothing is drawn. Threads
//! only wake it up: the gamepad reader, the volume watcher (the input daemon's socket), the
//! index watcher (inotify on cache/index/GEN) and,
//! while "Update game lists" runs, the reader of lume-index's progress. SDL's queue is only
//! drained, never waited on (SDL_WaitEvent polls every millisecond on KMSDRM).

use std::process::ExitCode;

#[cfg(feature = "sdl")]
fn main() -> ExitCode {
    use std::io::BufRead;
    use std::time::Duration;

    use lume_ui::app::{App, Ev, Paths};
    use lume_ui::sdl::SdlCanvas;
    use lume_ui::system::RealSystem;

    let log = |m: &str| lume_core::log::line("lume-ui", m);
    let loaded = match lume_core::catalog::load_all("lume-ui", true) {
        Ok(l) => l,
        Err(e) => {
            log(&format!("catalog not loaded: {e}"));
            return ExitCode::FAILURE;
        }
    };
    let home = std::env::var_os("HOME").map(std::path::PathBuf::from).unwrap_or_else(|| "/home/game".into());
    let paths = Paths {
        storage: lume_core::paths::storage(),
        share: lume_core::paths::share(),
        cores: lume_core::paths::cores_dir(),
        runtime: lume_core::paths::runtime(),
        ra_cfg: home.join(".config/retroarch/retroarch.cfg"),
    };
    let _ = std::fs::create_dir_all(&paths.runtime);
    let card = paths.storage.join("system/lume");
    let mut app = App::new(paths, loaded.catalog, loaded.runners, &lume_core::paths::arch(), RealSystem::new());

    let Some(font) = lume_ui::font::Font::bundled() else {
        log("no font in /usr/share/lume/fonts");
        return ExitCode::FAILURE;
    };
    // linear scaling: the Dock's logos and symbols are masks drawn smaller than decoded, and
    // nearest-neighbour scaling gave them jagged edges (set before any texture exists)
    sdl2::hint::set("SDL_RENDER_SCALE_QUALITY", "1");
    // LUME_SCREENSHOT=out.png [LUME_KEYS=Right,A,...] [LUME_SIZE=640x480]: draws one frame in
    // software after those buttons and saves it (documentation and visual checks; no screen)
    if let Some(out) = std::env::var_os("LUME_SCREENSHOT") {
        return screenshot(&mut app, font, std::path::Path::new(&out));
    }
    // GLES first: on lima (GA36) the default "opengl" renderer only clears the screen, no
    // tiles and no text (seen with lume-shot, 2026-11-14). SDL falls back to the other
    // renderers when GLES is missing; SDL_RENDER_DRIVER in the environment still wins.
    if std::env::var_os("SDL_RENDER_DRIVER").is_none() {
        sdl2::hint::set("SDL_RENDER_DRIVER", "opengles2");
    }
    // SDL turns SIGTERM into a quit event, which this loop does not act on: the process would
    // outlive a plain kill and keep the display (an orphan held the GA36 screen, 2026-11-14)
    sdl2::hint::set("SDL_NO_SIGNAL_HANDLERS", "1");
    let sdl = match sdl2::init() {
        Ok(s) => s,
        Err(e) => {
            log(&format!("SDL: {e}"));
            return ExitCode::FAILURE;
        }
    };
    let video = sdl.video().expect("SDL video");
    // without the display (KMSDRM busy right after a restart) SDL falls back to a driver that
    // shows nothing: fail, so the session starts the frontend again (seen on the GA36)
    if matches!(video.current_video_driver(), "offscreen" | "dummy") {
        log(&format!("no display: SDL chose the {} video driver", video.current_video_driver()));
        return ExitCode::FAILURE;
    }
    let (w, h) = video.current_display_mode(0).map(|m| (m.w as u32, m.h as u32)).unwrap_or((640, 480));
    let window = match video.window("lume", w, h).fullscreen_desktop().build() {
        Ok(win) => win,
        Err(e) => {
            log(&format!("no window: {e}"));
            return ExitCode::FAILURE;
        }
    };
    let canvas = window.into_canvas().accelerated().present_vsync().build().expect("SDL renderer");
    // read by the VM self-test (KMSDRM and a GLES renderer, not software) and the logs
    log(&format!("video {}, renderer {}, {w}x{h}", video.current_video_driver(), canvas.info().name));
    sdl.mouse().show_cursor(false);
    let creator = canvas.texture_creator();
    let mut c = SdlCanvas::new(canvas, creator, font).with_faces(lume_ui::font::Font::bundled_medium(), lume_ui::font::Font::bundled_bold());
    let mut pump = sdl.event_pump().expect("SDL event pump");
    // The threads wake the loop through this channel, not SDL's queue: SDL_WaitEvent has no
    // real wait on KMSDRM and polls every millisecond (42% of a core on the GA36, 2026-11-14).
    // `tx` stays alive here, so recv never fails with Disconnected and never spins.
    let (tx, rx) = std::sync::mpsc::channel::<Ev>();

    // gamepad reader
    let t = tx.clone();
    std::thread::spawn(move || lume_ui::input::run(move |a, rep| {
        let _ = t.send(Ev::Input(a, rep));
    }));
    // volume keys (and Fn + volume keys, the brightness): lume-input applies them and tells
    // its socket clients; the level is read here as the Settings read it
    {
        use lume_ui::input::Level;
        use lume_ui::system::SystemAdapter;
        let mixer = lume_ui::system::this_board_mixer();
        let backlight = RealSystem::new();
        let t = tx.clone();
        let sock = std::env::var_os("LUME_INPUT_SOCK").map(std::path::PathBuf::from).unwrap_or_else(|| lume_ui::input::INPUT_SOCK.into());
        std::thread::spawn(move || {
            use lume_ui::input::Sock;
            lume_ui::input::watch_socket(
                &sock,
                |k| match k {
                    Level::Volume => mixer.as_ref().and_then(|m| m.level()),
                    Level::Brightness => backlight.brightness(),
                },
                move |s| {
                    let _ = t.send(match s {
                        Sock::Level(Level::Volume, v) => Ev::Volume(v),
                        Sock::Level(Level::Brightness, v) => Ev::Brightness(v),
                        Sock::FnTap => Ev::FnTap,
                        Sock::FnHold(table) => Ev::FnHold(table),
                        Sock::FnRelease => Ev::FnRelease,
                        Sock::Sleep(n) => Ev::Sleep(n),
                    });
                },
            )
        });
    }
    // the status bar: Wi-Fi, Bluetooth and the battery (level and charging, for the charge
    // mark and the low-battery warning) every 5 s; a few sysfs reads, no process, an event
    // only when something changes (the loop stays asleep otherwise)
    let t = tx.clone();
    std::thread::spawn(move || {
        let sys = std::path::Path::new("/sys");
        let mut battery = lume_ui::system::read_battery(sys);
        let mut network = lume_ui::system::read_network(sys);
        loop {
            std::thread::sleep(Duration::from_secs(5));
            let now = lume_ui::system::read_network(sys);
            if now != network {
                let _ = t.send(Ev::Network(now.0, now.1));
                network = now;
            }
            let now = lume_ui::system::read_battery(sys);
            if now != battery {
                if let Some((level, charging)) = now {
                    let _ = t.send(Ev::Battery(level, charging));
                }
                battery = now;
            }
        }
    });
    // index watcher: lume-index bumps cache/index/GEN after a scan
    let t = tx.clone();
    let index_dir = card.join("cache/index");
    std::thread::spawn(move || lume_ui::watch::gen(&index_dir, move || {
        let _ = t.send(Ev::Reload);
    }));

    const IDLE: Duration = Duration::from_secs(1);
    // the first screen is the menu scenario for the power service (D9)
    app.announce_menu();
    // The first frame twice: on the GA36 (KMSDRM, lima) the first swap after a game leaves the
    // screen black until the next one, so the launcher only showed on the first key press
    // (2026-11-17). One extra frame at start costs a few ms.
    app.draw(&mut c);
    let mut redraw = true;
    let code = loop {
        if redraw {
            app.draw(&mut c);
        }
        if let Some(exit) = app.exit {
            break exit;
        }
        if app.start_update {
            app.start_update = false;
            let tx = tx.clone();
            std::thread::spawn(move || {
                let child = std::process::Command::new("/usr/bin/lume-index").arg("--progress").stdout(std::process::Stdio::piped()).spawn();
                let ok = match child {
                    Ok(mut ch) => {
                        if let Some(out) = ch.stdout.take() {
                            for line in std::io::BufReader::new(out).lines().map_while(Result::ok) {
                                let f: Vec<&str> = line.split(' ').collect();
                                if f.len() >= 3 && f[0] == "progress" {
                                    let _ = tx.send(Ev::Progress(f[1].parse().unwrap_or(0), f[2].parse().unwrap_or(0)));
                                }
                            }
                        }
                        ch.wait().map(|s| s.success()).unwrap_or(false)
                    }
                    Err(_) => false,
                };
                let _ = tx.send(Ev::UpdateDone(ok));
            });
        }
        // idle: wake once a second only to drain SDL's queue; an animation: its next frame
        // The idle timer is a timeout of this wait, not a polling loop: one wake-up when its
        // time is up (zero: a Tick enters the idle state), nothing while the screen is dimmed.
        let event = match app.wait().into_iter().chain(app.idle_wait()).min() {
            None => rx.recv_timeout(IDLE).ok(),
            Some(d) => Some(rx.recv_timeout(d.max(Duration::from_millis(1))).unwrap_or(Ev::Tick)),
        };
        redraw = event.map(|ev| app.handle(ev)).unwrap_or(false);
        // SDL's own events, without waiting: a window exposed again (VT switch back) draws
        for e in pump.poll_iter() {
            redraw |= matches!(e, sdl2::event::Event::Window { .. });
        }
    };
    if let Err(e) = app.current_state().save(&app.runtime) {
        log(&format!("state not saved: {e}"));
    }
    // Leave without destructors and without atexit handlers. On the R36S (panfrost) Mesa's
    // EGL exit handler runs after SDL has torn the KMSDRM video down and crashes inside
    // libEGL (SIGSEGV, core of 2026-11-15), so every exit (power off, open a game, the
    // RetroArch menu) looked like a failure to lume-run (P-71). The kernel releases the
    // display and the input devices when the process ends; the state is already saved.
    use std::io::Write;
    let _ = std::io::stdout().flush();
    let _ = std::io::stderr().flush();
    // SAFETY: _exit ends the process at once; nothing runs after it
    unsafe { libc::_exit(code as i32) }
}

#[cfg(feature = "sdl")]
fn screenshot(app: &mut lume_ui::app::App<lume_ui::system::RealSystem>, font: lume_ui::font::Font, out: &std::path::Path) -> ExitCode {
    use lume_ui::app::Ev;
    use lume_ui::input::Action;

    let (w, h) = std::env::var("LUME_SIZE")
        .ok()
        .and_then(|s| s.split_once('x').and_then(|(w, h)| Some((w.parse().ok()?, h.parse().ok()?))))
        .unwrap_or((640u32, 480u32));
    let surface = sdl2::surface::Surface::new(w, h, sdl2::pixels::PixelFormatEnum::RGB888).expect("surface");
    let canvas = surface.into_canvas().expect("software canvas");
    let creator = canvas.texture_creator();
    let mut c = lume_ui::sdl::SdlCanvas::new(canvas, creator, font).with_faces(lume_ui::font::Font::bundled_medium(), lume_ui::font::Font::bundled_bold());
    // LUME_BATTERY=82 (or 82+ for charging): a battery for screenshots on a PC without one
    // LUME_NETWORK=wifi,bt: the network icons for screenshots
    if let Ok(n) = std::env::var("LUME_NETWORK") {
        app.network = (n.contains("wifi"), n.contains("bt"));
    }
    if let Ok(b) = std::env::var("LUME_BATTERY") {
        let charging = b.ends_with('+');
        if let Ok(level) = b.trim_end_matches('+').parse::<u8>() {
            app.battery = Some((level.min(100), charging));
        }
    }
    for k in std::env::var("LUME_KEYS").unwrap_or_default().split(',').filter(|k| !k.is_empty()) {
        let a = match k {
            "Up" => Action::Up,
            "Down" => Action::Down,
            "Left" => Action::Left,
            "Right" => Action::Right,
            "A" => Action::A,
            "B" => Action::B,
            "X" => Action::X,
            "Y" => Action::Y,
            "L1" => Action::L1,
            "R1" => Action::R1,
            "Start" => Action::Start,
            _ => Action::Select,
        };
        app.handle(Ev::Input(a, false));
        app.draw(&mut c); // the covers get their textures as on the device
    }
    // let a running animation end, as it would on the device
    while let Some(d) = app.wait().filter(|d| *d <= std::time::Duration::from_millis(40)) {
        std::thread::sleep(d);
        app.handle(Ev::Tick);
    }
    app.draw(&mut c);
    let surf = c.canvas.surface();
    let pitch = surf.pitch() as usize;
    let mut rgb = Vec::with_capacity((w * h * 3) as usize);
    surf.with_lock(|px| {
        for y in 0..h as usize {
            for x in 0..w as usize {
                let p = &px[y * pitch + x * 4..y * pitch + x * 4 + 4];
                rgb.extend_from_slice(&[p[2], p[1], p[0]]);
            }
        }
    });
    match image::save_buffer(out, &rgb, w, h, image::ColorType::Rgb8) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            lume_core::log::line("lume-ui", &format!("screenshot not saved: {e}"));
            ExitCode::FAILURE
        }
    }
}

#[cfg(not(feature = "sdl"))]
fn main() -> ExitCode {
    eprintln!("lume-ui: built without the sdl feature");
    ExitCode::FAILURE
}
