//! The interface driven with the fake backend (lume-launcher tasks 7.1 and 7.3 to 7.7).

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use image::{ImageFormat, Rgb, RgbImage};
use lume_core::catalog::Catalog;
use lume_core::runner::Runner;
use lume_ui::app::{App, DockItem, Ev, Exit, Paths, Screen, SetRow};
use lume_ui::canvas::{Canvas, FakeCanvas};
use lume_ui::input::Action;
use lume_ui::system::FakeSystem;

fn repo() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../..")
}

struct Card {
    root: PathBuf,
    catalog: Catalog,
    runners: BTreeMap<String, Runner>,
}

fn card(name: &str, snes_games: usize, covers: bool) -> Card {
    let root = std::env::temp_dir().join(format!("lume-ui-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    let roms = root.join("storage/roms");
    fs::create_dir_all(roms.join("nes")).unwrap();
    for g in ["Super Mario Bros", "Súper Bros Ação", "Zelda"] {
        fs::write(roms.join("nes").join(format!("{g}.nes")), g).unwrap();
    }
    fs::create_dir_all(roms.join("snes/images")).unwrap();
    let mut gl = String::from("<?xml version=\"1.0\"?>\n<gameList>\n");
    for i in 0..snes_games {
        let n = format!("Game {i:04}");
        fs::write(roms.join("snes").join(format!("{n}.sfc")), &n).unwrap();
        let fav = if i == 7 { "<favorite>true</favorite>" } else { "" };
        let img = if covers {
            RgbImage::from_pixel(8, 8, Rgb([i as u8, 0, 0])).save_with_format(roms.join("snes/images").join(format!("{n}.png")), ImageFormat::Png).unwrap();
            format!("<image>./images/{n}.png</image>")
        } else {
            String::new()
        };
        gl.push_str(&format!("<game><path>./{n}.sfc</path><name>{n}</name>{fav}{img}</game>\n"));
    }
    gl.push_str("</gameList>\n");
    fs::write(roms.join("snes/gamelist.xml"), gl).unwrap();
    fs::create_dir_all(roms.join("ports")).unwrap();
    fs::write(roms.join("ports/Tool.sh"), "echo").unwrap();
    let catalog = Catalog::load(&repo().join("rootfs/overlay/usr/share/r36os/systems.json")).unwrap();
    let ctx = lume_index::Ctx { storage: root.join("storage"), catalog: catalog.clone(), tile: lume_index::DEFAULT_TILE };
    for (_, r) in lume_index::update_all(&ctx, &[], false, |_, _, _| {}) {
        r.unwrap();
    }
    let (runners, _) = lume_core::runner::load(&[repo().join("rootfs/overlay/usr/share/lume/runners.d")], false);
    Card { root, catalog, runners }
}

fn app(c: &Card, sys: FakeSystem) -> App<FakeSystem> {
    let p = Paths {
        storage: c.root.join("storage"),
        share: repo().join("rootfs/overlay/usr/share/lume"),
        cores: "/usr/lib/libretro".into(),
        runtime: c.root.join("run"),
        ra_cfg: c.root.join("home/.config/retroarch/retroarch.cfg"),
    };
    fs::create_dir_all(&p.runtime).unwrap();
    App::new(p, c.catalog.clone(), c.runners.clone(), "aarch64", sys)
}

fn press(a: &mut App<FakeSystem>, act: Action) {
    a.handle(Ev::Input(act, false));
}

fn go_dock(a: &mut App<FakeSystem>, want: DockItem) {
    a.dock_focus = a.dock.iter().position(|d| *d == want).unwrap();
}

#[test]
fn dock_rotates_and_skips_empty_systems() {
    let c = card("dock", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let names: Vec<String> = a.lib.systems.iter().map(|s| s.id.clone()).collect();
    assert_eq!(names, ["nes", "snes", "ports"]); // psx and the others have no game
    assert_eq!(a.dock.first(), Some(&DockItem::Favorites));
    assert_eq!(a.dock.last(), Some(&DockItem::Settings));
    assert_eq!(a.dock[a.dock.len() - 2], DockItem::Recent);
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::Right);
    assert_eq!(a.dock[a.dock_focus], DockItem::Favorites);
    press(&mut a, Action::Left);
    assert_eq!(a.dock[a.dock_focus], DockItem::Settings);
}

#[test]
fn no_frame_without_an_event() {
    let c = card("frames", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    assert_eq!(canvas.frames, 1);
    // idle on the Dock: the loop may sleep until an event comes
    assert_eq!(a.wait(), None);
    assert!(a.handle(Ev::Input(Action::Right, false)));
    a.draw(&mut canvas);
    assert_eq!(canvas.frames, 2);
    // the animation of that move asks for frames only until it ends (30 fps cap)
    if let Some(d) = a.wait() {
        assert!(d <= Duration::from_millis(33));
        std::thread::sleep(Duration::from_millis(250));
        a.handle(Ev::Tick);
        assert_eq!(a.wait(), None);
    }
}

#[test]
fn grid_jump_filter_and_back() {
    let c = card("grid", 1000, false);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert_eq!(a.screen, Screen::Grid);
    let page = a.cols * a.rows;
    press(&mut a, Action::R1);
    let first = a.grid.as_ref().unwrap().focus;
    assert!(first > page, "one R1 moved {first}, a page is {page}");
    press(&mut a, Action::R1);
    let second = a.grid.as_ref().unwrap().focus - first;
    assert!(second > first, "a quick second R1 jumps further ({second} after {first})");
    std::thread::sleep(Duration::from_millis(750));
    a.jump.step(Instant::now() + Duration::from_secs(2), 1, 1000, page);
    // filter: case and accents ignored, every word required
    go_back(&mut a);
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    a.search("super bros");
    assert_eq!(a.grid.as_ref().unwrap().items.len(), 2);
    a.search("SUPER acao");
    assert_eq!(a.focused_name().as_deref(), Some("Súper Bros Ação"));
    // B clears the filter before leaving the list
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Grid);
    assert_eq!(a.grid.as_ref().unwrap().items.len(), 3);
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Dock);
    assert_eq!(a.dock[a.dock_focus], DockItem::System(0));
}

fn go_back(a: &mut App<FakeSystem>) {
    while a.screen != Screen::Dock {
        press(a, Action::B);
    }
}

#[test]
fn launch_and_come_back_to_the_same_game() {
    let c = card("launch", 40, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    for _ in 0..9 {
        press(&mut a, Action::Down);
    }
    let name = a.focused_name().unwrap();
    press(&mut a, Action::A); // game menu
    assert!(a.overlay_open());
    press(&mut a, Action::A); // Start
    assert_eq!(a.exit, Some(Exit::Launch));
    let launch = fs::read_to_string(c.root.join("run/launch")).unwrap();
    assert!(launch.contains("system=snes\nrunner=retroarch\ncore=snes9x2005_plus\n"), "{launch}");
    assert!(launch.contains(&format!("arg={}/storage/roms/snes/{name}.sfc\n", c.root.display())));
    a.current_state().save(&a.runtime).unwrap();
    // lume-run runs the game, then opens the interface again
    let b = app(&c, FakeSystem::default());
    assert_eq!(b.screen, Screen::Grid);
    assert_eq!(b.focused_name(), Some(name));
}

#[test]
fn native_runner_has_no_aspect_or_shader() {
    let c = card("native", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    go_dock(&mut a, DockItem::System(2)); // ports
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Emulator"));
    assert!(!canvas.has_text("Aspect") && !canvas.has_text("Shader"));
    // a RetroArch game shows both
    go_back(&mut a);
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Aspect") && canvas.has_text("Shader"));
}

#[test]
fn console_default_then_game_exception() {
    let c = card("options", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(0)); // nes: fceumm, nestopia
    press(&mut a, Action::A);
    press(&mut a, Action::Y); // console options: Emulator first
    press(&mut a, Action::Right); // Default -> fceumm
    press(&mut a, Action::Right); // -> nestopia
    press(&mut a, Action::B);
    let sys = fs::read_to_string(c.root.join("storage/system/lume/systems/nes.toml")).unwrap();
    assert!(sys.contains("nestopia"), "{sys}");
    // one game back on fceumm: an exception with a badge
    press(&mut a, Action::A);
    for _ in 0..2 {
        press(&mut a, Action::Down); // Start, Start state, Emulator
    }
    press(&mut a, Action::Right); // Default -> fceumm (differs from the console)
    let games = fs::read_to_string(c.root.join("storage/system/lume/games/nes.toml")).unwrap();
    assert!(games.contains("fceumm"), "{games}");
    let g = a.grid.as_ref().unwrap().items[0];
    assert!(a.has_badge(g));
    press(&mut a, Action::Left); // back to Default: the exception goes away
    assert!(!a.has_badge(g));
    assert!(!c.root.join("storage/system/lume/games/nes.toml").exists());
}

#[test]
fn favorites_and_recents() {
    let c = card("favs", 12, false);
    let mut a = app(&c, FakeSystem::default());
    assert_eq!(a.lib.favorites().len(), 1); // Game 0007 from the gamelist
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    // Start, Start state, Emulator, Aspect, Shader, Favorites
    for _ in 0..5 {
        press(&mut a, Action::Down);
    }
    press(&mut a, Action::A);
    assert_eq!(a.lib.favorites().len(), 2);
    // recents: lume-run touches after each game, newest first
    let ctx = lume_index::Ctx { storage: c.root.join("storage"), catalog: c.catalog.clone(), tile: lume_index::DEFAULT_TILE };
    lume_index::touch(&ctx, "snes", "Game 0003.sfc", 1000).unwrap();
    lume_index::touch(&ctx, "nes", "Zelda.nes", 2000).unwrap();
    a.handle(Ev::Reload);
    let rec: Vec<String> = a.lib.recents(10).iter().map(|r| a.lib.name(*r).to_string()).collect();
    assert_eq!(rec, ["Zelda", "Game 0003"]);
}

#[test]
fn settings_adapters_language_and_power() {
    let c = card("settings", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    assert!(!a.set_rows().contains(&SetRow::Wifi) && !a.set_rows().contains(&SetRow::Bluetooth));
    let b = app(&c, FakeSystem { wifi: true, bluetooth: true, ..Default::default() });
    assert_eq!(&b.set_rows()[..2], [SetRow::Wifi, SetRow::Bluetooth]);

    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    // Language: en -> pt -> es; RetroArch gets user_language 3 (Spanish)
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert_eq!(a.settings.language, "es");
    let ra = fs::read_to_string(c.root.join("home/.config/retroarch/retroarch.cfg")).unwrap();
    assert_eq!(ra, "user_language = \"3\"\n");
    // no text of the Settings is cut at 640x480 in Spanish (every row, System panel too)
    let mut canvas = FakeCanvas::new(640, 480);
    for _ in 0..a.set_rows().len() {
        a.draw(&mut canvas);
        assert!(canvas.clipped.is_empty(), "cut in Spanish: {:?}", canvas.clipped);
        press(&mut a, Action::Down);
    }
    // the System panel reads only while it is focused
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::System).unwrap();
    press(&mut a, Action::Up);
    press(&mut a, Action::Down);
    let reads = a.sys.info_reads.get();
    assert!(reads >= 1 && a.wait().is_some());
    press(&mut a, Action::Down);
    assert_eq!(a.wait(), None);
    a.handle(Ev::Tick);
    assert_eq!(a.sys.info_reads.get(), reads);
    // Volume in steps of 5
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Volume).unwrap();
    press(&mut a, Action::Left);
    assert_eq!(a.sys.vol, 45);
    // Power off: Cancel first
    a.settings_focus = a.set_rows().len() - 1;
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    assert_eq!(a.exit, None);
    press(&mut a, Action::A);
    press(&mut a, Action::Right);
    press(&mut a, Action::A);
    assert_eq!(a.exit, Some(Exit::Shutdown));
}

#[test]
fn retroarch_item_opens_the_menu_with_code_65() {
    let c = card("ramenu", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::RetroArch).unwrap();
    press(&mut a, Action::A);
    assert_eq!(a.exit, Some(Exit::RetroArch));
    assert!(fs::read_to_string(c.root.join("run/launch")).unwrap().starts_with("kind=menu\n"));
    a.current_state().save(&a.runtime).unwrap();
    // back from the menu: the Settings again, with the volume and brightness read (not "—",
    // seen on the GA36 on 2026-11-14)
    let mut b = app(&c, FakeSystem { vol: 60, bri: 70, ..Default::default() });
    assert_eq!(b.screen, Screen::Settings);
    let mut canvas = FakeCanvas::new(640, 480);
    b.draw(&mut canvas);
    assert!(canvas.has_text("‹60% ›") && canvas.has_text("‹70% ›") && !canvas.has_text("—"));
}

#[test]
fn cover_cache_stays_under_its_ceiling() {
    let c = card("covers", 220, true);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    let cap = a.theme.num("cache_bytes") as usize;
    for _ in 0..80 {
        a.draw(&mut canvas);
        assert!(a.thumb_bytes() <= cap);
        press(&mut a, Action::Down);
    }
    // what the cache let go was given back to the backend
    assert!(canvas.live_textures as usize * 128 * 96 * 2 <= cap);
    assert!(canvas.textures > (cap / (128 * 96 * 2)) as u32);
}

#[test]
fn layouts_fit_three_resolutions() {
    let c = card("layout", 50, false);
    for (w, h) in [(640, 480), (854, 480), (720, 720)] {
        let mut a = app(&c, FakeSystem::default());
        let mut canvas = FakeCanvas::new(w, h);
        go_dock(&mut a, DockItem::System(1));
        press(&mut a, Action::A);
        a.draw(&mut canvas);
        let screen = lume_ui::canvas::Rect::new(0, 0, w, h);
        assert!(canvas.fills.iter().all(|(r, _)| screen.contains(r)), "{w}x{h}");
        if (w, h) == (720, 720) {
            assert!(a.rows > 2, "a square screen gets more rows");
        }
        let _ = canvas.size();
    }
}
