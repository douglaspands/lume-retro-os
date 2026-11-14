//! lume-ui: the interface of the lume-launcher (lume-launcher D1, D3). Run by lume-run;
//! exits with 0 (Shut down), 64 (open the game of $XDG_RUNTIME_DIR/lume/launch) or 65 (the
//! RetroArch menu). Any other code is a failure.
//!
//! The loop sleeps in SDL_WaitEvent: with no input and no animation nothing is drawn. Threads
//! only wake it up: the gamepad reader, the index watcher (inotify on cache/index/GEN) and,
//! while "Update game lists" runs, the reader of lume-index's progress.

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
    // LUME_SCREENSHOT=out.png [LUME_KEYS=Right,A,...] [LUME_SIZE=640x480]: draws one frame in
    // software after those buttons and saves it (documentation and visual checks; no screen)
    if let Some(out) = std::env::var_os("LUME_SCREENSHOT") {
        return screenshot(&mut app, font, std::path::Path::new(&out));
    }
    let sdl = match sdl2::init() {
        Ok(s) => s,
        Err(e) => {
            log(&format!("SDL: {e}"));
            return ExitCode::FAILURE;
        }
    };
    let video = sdl.video().expect("SDL video");
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
    let mut c = SdlCanvas::new(canvas, creator, font);
    let events = sdl.event().expect("SDL events");
    events.register_custom_event::<Ev>().expect("custom event");
    let mut pump = sdl.event_pump().expect("SDL event pump");

    // gamepad reader
    let tx = events.event_sender();
    std::thread::spawn(move || lume_ui::input::run(move |a, rep| {
        let _ = tx.push_custom_event(Ev::Input(a, rep));
    }));
    // index watcher: lume-index bumps cache/index/GEN after a scan
    let tx = events.event_sender();
    let index_dir = card.join("cache/index");
    std::thread::spawn(move || lume_ui::watch::gen(&index_dir, move || {
        let _ = tx.push_custom_event(Ev::Reload);
    }));

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
            let tx = events.event_sender();
            std::thread::spawn(move || {
                let child = std::process::Command::new("/usr/bin/lume-index").arg("--progress").stdout(std::process::Stdio::piped()).spawn();
                let ok = match child {
                    Ok(mut ch) => {
                        if let Some(out) = ch.stdout.take() {
                            for line in std::io::BufReader::new(out).lines().map_while(Result::ok) {
                                let f: Vec<&str> = line.split(' ').collect();
                                if f.len() >= 3 && f[0] == "progress" {
                                    let _ = tx.push_custom_event(Ev::Progress(f[1].parse().unwrap_or(0), f[2].parse().unwrap_or(0)));
                                }
                            }
                        }
                        ch.wait().map(|s| s.success()).unwrap_or(false)
                    }
                    Err(_) => false,
                };
                let _ = tx.push_custom_event(Ev::UpdateDone(ok));
            });
        }
        let event = match app.wait() {
            None => Some(pump.wait_event()),
            Some(d) => pump.wait_event_timeout(d.max(Duration::from_millis(1)).as_millis() as u32),
        };
        redraw = match event {
            None => app.handle(Ev::Tick),
            Some(e) => match e.as_user_event_type::<Ev>() {
                Some(ev) => app.handle(ev),
                // window exposed again (VT switch back): draw
                None => matches!(e, sdl2::event::Event::Window { .. }),
            },
        };
    };
    if let Err(e) = app.current_state().save(&app.runtime) {
        log(&format!("state not saved: {e}"));
    }
    ExitCode::from(code as u8)
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
    let mut c = lume_ui::sdl::SdlCanvas::new(canvas, creator, font);
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
