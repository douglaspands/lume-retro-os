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
    let catalog = Catalog::load(&repo().join("aports/lume-games/files/usr/share/lume/systems.json")).unwrap();
    let ctx = lume_index::Ctx { storage: root.join("storage"), catalog: catalog.clone(), tile: lume_index::DEFAULT_TILE };
    for (_, r) in lume_index::update_all(&ctx, &[], false, |_, _, _| {}) {
        r.unwrap();
    }
    let (runners, _) = lume_core::runner::load(&[repo().join("aports/lume-games/files/usr/share/lume/runners.d")], false);
    Card { root, catalog, runners }
}

fn app(c: &Card, sys: FakeSystem) -> App<FakeSystem> {
    let p = Paths {
        storage: c.root.join("storage"),
        share: repo().join("aports/lume-launcher-data/files/usr/share/lume"),
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
fn dock_motion_is_the_prototype_spring() {
    use lume_ui::app::cubic_bezier;
    let spring = |t: f32| cubic_bezier(0.22, 1.25, 0.36, 1.0, t);
    assert!(spring(0.0).abs() < 1e-3 && (spring(1.0) - 1.0).abs() < 1e-3);
    // it passes the mark a little and settles (the prototype's "light spring")
    let peak = (1..100).map(|i| spring(i as f32 / 100.0)).fold(0.0f32, f32::max);
    assert!(peak > 1.0 && peak < 1.1, "peak {peak}");
    // and most of the way is done early: smooth, not slow
    assert!(spring(0.3) > 0.75, "{}", spring(0.3));
    // the solver against the browsers' value of the standard "ease" at the middle
    assert!((cubic_bezier(0.25, 0.1, 0.25, 1.0, 0.5) - 0.8024).abs() < 0.002);
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
fn suspend_stops_drawing_answers_with_its_sequence_and_resume_redraws_once() {
    use lume_core::sleep::Notice;
    let c = card("sleep", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let frames = canvas.frames;
    let focus = a.dock_focus;

    // suspend: no frame, the answer is queued with the same sequence
    assert!(!a.handle(Ev::Sleep(Notice::Suspend(4))));
    assert_eq!(a.suspend_reply.take(), Some(4));
    assert!(a.sleeping);
    assert_eq!(a.wait(), None);
    assert_eq!(a.idle_wait(), None);

    // between suspend and resume nothing asks for a frame and the input does nothing
    for ev in [Ev::Input(Action::Right, false), Ev::Tick, Ev::Volume(30), Ev::Brightness(30), Ev::FnTap] {
        assert!(!a.handle(ev));
    }
    assert!(!a.handle(Ev::Battery(50, false)), "data events update the state without a frame");
    assert_eq!(a.dock_focus, focus);
    assert_eq!(a.suspend_reply, None);
    assert_eq!(canvas.frames, frames);

    // resume: one redraw of the current screen, no answer
    assert!(a.handle(Ev::Sleep(Notice::Resume(4))));
    assert!(!a.sleeping);
    assert_eq!(a.suspend_reply, None);
    a.draw(&mut canvas);
    assert_eq!(canvas.frames, frames + 1);
    assert!(!a.handle(Ev::Sleep(Notice::Resume(4))), "a second resume has nothing to redraw");
    // the input works again
    assert!(a.handle(Ev::Input(Action::Right, false)));
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

#[test]
fn card_logo_on_the_dock_in_the_icon_color() {
    let c = card("logo", 3, false);
    // an icons-only folder on the card for the default theme: a white disc on transparency
    let icons = c.root.join("storage/system/lume/themes/lume/icons");
    fs::create_dir_all(&icons).unwrap();
    let logo = image::RgbaImage::from_fn(200, 100, |x, y| {
        let inside = (x as i32 - 100).pow(2) + (y as i32 - 50).pow(2) < 45 * 45;
        image::Rgba([255, 255, 255, if inside { 255 } else { 0 }])
    });
    logo.save_with_format(icons.join("nes.png"), ImageFormat::Png).unwrap();
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(0));
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    // the focused tile shows the logo (2:1, inside 78% x 56% of the tile) in its icon color
    let sel = a.theme.color("icon_sel_fg");
    let logo = canvas.fills.iter().find(|(r, col)| *col == sel && r.w > 50 && r.w < 300).map(|(r, _)| *r).expect("logo drawn");
    assert_eq!(logo.w, logo.h * 2, "{logo:?}");
    let tile = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("icon_sel_bg") && r.contains(&logo)).map(|(r, _)| *r).expect("on its tile");
    assert!(logo.w <= tile.w * 78 / 100 + 1 && logo.h <= tile.h * 56 / 100 + 1, "{logo:?} in {tile:?}");
    // a system without a logo keeps its abbreviation
    assert!(canvas.has_text("SNES"));
}

#[test]
fn footer_centered_and_counter_in_the_middle() {
    let c = card("footer", 12, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    // the hints as a whole: as much room on the left as on the right
    let row: Vec<_> = canvas.texts.iter().filter(|(_, r)| r.y > 440).map(|(_, r)| *r).collect();
    let (left, right) = (row.iter().map(|r| r.x).min().unwrap(), row.iter().map(|r| r.right()).max().unwrap());
    // the first button's chip starts a little left of its letter
    assert!((left - (640 - right)).abs() <= 12, "left {left}, right {}", 640 - right);
    let count = canvas.texts.iter().find(|(t, _)| t == "1 / 12").unwrap().1;
    assert!((count.x + count.w / 2 - 320).abs() <= 2, "{count:?}");
}

#[test]
fn battery_in_the_status_bar_of_every_screen() {
    let c = card("battery", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    assert!(canvas.has_text("82%"), "Dock");
    // one spot on every screen: the Dock, a list and the Settings draw it in the same rect
    let spot = |a: &mut App<FakeSystem>| {
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        cv.texts.iter().find(|(t, _)| t == "82%").map(|(_, r)| *r).unwrap()
    };
    let on_dock = spot(&mut a);
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    let on_list = spot(&mut a);
    // the search keeps it in its spot (the bar ends before it)
    press(&mut a, Action::X);
    assert_eq!(spot(&mut a), on_list, "search");
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let bar = cv.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg_opaque") && r.y < 20 && r.w > 300).map(|(r, _)| *r).unwrap();
    assert!(bar.right() < on_list.x - 30, "the bar {bar:?} ends before the battery {on_list:?}");
    press(&mut a, Action::B);
    // over a menu it stays, undimmed: drawn after the dimming layer, the inside of its
    // stroke in the dimmed background
    press(&mut a, Action::A);
    assert!(a.overlay_open());
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let dim = cv.fills.iter().position(|(r, col)| r.w == 640 && r.h == 480 && *col == a.theme.color("overlay")).expect("the dimming layer");
    let pct = cv.texts.iter().find(|(t, _)| t == "82%").map(|(_, r)| *r).unwrap();
    assert_eq!(pct, on_list, "menu");
    let dimmed = a.theme.color("bg").under(a.theme.color("overlay"));
    let hole = cv.fills.iter().rposition(|(r, col)| *col == dimmed && r.y < 40 && r.x > 500).expect("battery drawn over the dimming");
    assert!(hole > dim);
    press(&mut a, Action::B);
    go_back(&mut a);
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let on_settings = spot(&mut a);
    assert_eq!((on_dock, on_list), (on_settings, on_settings));
    go_back(&mut a);
    // the prototype's icon at 19.2 px (1 icon unit = 19.2 * 0.95 / 14 px): the outer body
    // 26.6 x 13.6 units, the level 20 units at 100%, all in the text color, also charging
    a.battery = Some((82, true));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let u = 19.2 * 0.95 / 14.0;
    let fg = a.theme.color("fg");
    let body = cv.fills.iter().filter(|(r, col)| *col == fg && r.y < 40 && r.x > 500).map(|(r, _)| *r).max_by_key(|r| r.w * r.h).unwrap();
    assert!((body.w as f32 - 26.6 * u).abs() <= 1.0 && (body.h as f32 - 13.6 * u).abs() <= 1.0, "body {body:?}");
    let level = cv.fills.iter().filter(|(r, col)| *col == fg && r.y < 40 && r.x > body.x && r.right() < body.right() && r.h > 5 && r.w > 5).map(|(r, _)| *r).next().unwrap();
    assert!((level.w as f32 - 20.0 * 0.82 * u).abs() <= 1.0 && (level.h as f32 - 7.0 * u).abs() <= 1.0, "level {level:?}");
    assert!(!cv.fills.iter().any(|(r, col)| *col == a.theme.color("accent") && r.y < 40 && r.x > 500), "one color, no charging mark");
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert!(canvas.has_text("82%"), "list");
    // the counter sits left of the battery, both on the header line
    let pct = canvas.texts.iter().find(|(t, _)| t == "82%").unwrap().1;
    let count = canvas.texts.iter().find(|(t, _)| t == "1 / 3").unwrap().1;
    assert!(count.right() < pct.x && pct.right() <= 640 && pct.y < 40, "{count:?} {pct:?}");
    // a change redraws; the same reading does not
    assert!(a.handle(Ev::Battery(81, true)));
    assert!(!a.handle(Ev::Battery(81, true)));
    go_back(&mut a);
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert!(canvas.has_text("81%"), "Settings");
    // no battery (the VM): nothing drawn
    let mut b = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    b.draw(&mut canvas);
    assert!(!canvas.texts.iter().any(|(t, _)| t.ends_with('%')));
}

/// The game list against the prototype measured in the browser at 640x480 (2026-11-15):
/// header title at (28, 11.2) 28 px bold, counter and battery at y 16 (19.2 px), tiles
/// 143.6 x 167 from (16, 56.4) 11.2 apart, the focused name band 408-441.7 (22.4 px), the
/// hint circles 23.7 px at y 449.6. One pixel of rounding allowed.
#[test]
fn grid_matches_the_prototype_ruler() {
    let c = card("ruler", 12, true);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::Right);
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let title = a.lib.systems[1].name.clone();
    let t = canvas.texts.iter().find(|(s, _)| *s == title).unwrap().1;
    assert!(near(t.x, 28.0) && near(t.y, 11.2) && near(t.h, 28.0), "title {t:?}");
    let count = canvas.texts.iter().find(|(s, _)| s == "2 / 12").unwrap().1;
    assert!(near(count.y, 16.0) && near(count.h, 19.2) && (count.x + count.w / 2 - 320).abs() <= 1, "counter {count:?}");
    let batt = canvas.texts.iter().find(|(s, _)| s == "82%").unwrap().1;
    assert!(near(batt.right(), 612.0) && near(batt.y, 16.0), "battery {batt:?}");
    // the unfocused tiles: the first and the third of the first row
    let tiles: Vec<_> = canvas.fills.iter().filter(|(_, col)| *col == a.theme.color("tile_bg")).map(|(r, _)| *r).collect();
    let first = tiles.iter().find(|r| near(r.x, 16.0)).copied().expect("first tile");
    assert!(near(first.y, 56.4) && near(first.w, 143.6) && near(first.h, 167.0), "tile {first:?}");
    let third = tiles.iter().find(|r| r.y == first.y && r.x > 300).copied().unwrap();
    assert!(near(third.x, 16.0 + 2.0 * (143.6 + 11.2)), "third {third:?}");
    let second_row = tiles.iter().find(|r| r.y > 200).copied().unwrap();
    assert!(near(second_row.y, 56.4 + 167.0 + 11.2), "second row {second_row:?}");
    // the focused tile: 3% larger, about its center
    let sel = canvas.fills.iter().find(|(_, col)| *col == a.theme.color("tile_bg_sel")).map(|(r, _)| *r).unwrap();
    assert!(near(sel.w, 147.9) && near(sel.h, 172.0) && near(sel.y, 53.9), "focused {sel:?}");
    // the focused name, 22.4 px in the band 408-441.7
    let name = canvas.texts.iter().find(|(s, _)| s == "Game 0001").unwrap().1;
    assert!(near(name.h, 22.4) && name.y >= 408 && name.bottom() <= 442, "name {name:?}");
    // the hint circles
    let chip = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("accent") && r.w == r.h && r.y > 440).map(|(r, _)| *r).unwrap();
    assert!(near(chip.w, 23.7) && near(chip.y, 449.6), "chip {chip:?}");
}

/// The Dock against the prototype measured in the browser at 640x480 (2026-11-15), Favorites
/// focused: the icons 172.8 at (233.6, 89.1), 130.1 at (414.4, 116.9) and 81.5 at
/// (552.5, 148.5), 8 px apart; the name 33.6 px at y 306.3, its subtitle 22.4 px at 348.2;
/// the battery ending at 622.7; the arrows' chip 39.2 x 23.7 at y 449.6. One pixel allowed.
#[test]
fn dock_matches_the_prototype_ruler() {
    let c = card("dockruler", 12, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    go_dock(&mut a, DockItem::Favorites);
    a.handle(Ev::Tick);
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let fills = |col: &str| canvas.fills.iter().filter(|(_, c)| *c == a.theme.color(col)).map(|(r, _)| *r).collect::<Vec<_>>();
    let sel = fills("icon_sel_bg").into_iter().find(|r| r.w > 100).unwrap();
    assert!(near(sel.x, 233.6) && near(sel.y, 89.1) && near(sel.w, 172.8), "focused {sel:?}");
    let icons = fills("icon_bg");
    let n1 = icons.iter().find(|r| r.x > 400 && r.w > 100).copied().unwrap();
    assert!(near(n1.x, 414.4) && near(n1.y, 116.9) && near(n1.w, 130.1), "neighbor {n1:?}");
    let n2 = icons.iter().find(|r| r.x > 540 && r.x < 600).copied().unwrap();
    assert!(near(n2.x, 552.5) && near(n2.y, 148.5) && near(n2.w, 81.5), "second {n2:?}");
    assert!(near(n1.x - sel.right(), 8.0), "gap {}", n1.x - sel.right());
    // the star on the focused icon: 0.42 of it, in the icon's color
    let star = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("icon_sel_fg") && sel.contains(r) && r.w > 40).map(|(r, _)| *r).unwrap();
    assert!(near(star.w, 172.8 * 0.42), "star {star:?}");
    let name = canvas.texts.iter().find(|(s, _)| s == "Favorites").unwrap().1;
    assert!(near(name.y, 306.3) && near(name.h, 33.6), "name {name:?}");
    let sub = canvas.texts.iter().find(|(s, _)| s.ends_with(" games")).unwrap().1;
    assert!(near(sub.y, 348.2) && near(sub.h, 22.4), "subtitle {sub:?}");
    // the battery: the one spot of every screen (the list's), not the prototype's Dock spot
    let batt = canvas.texts.iter().find(|(s, _)| s == "82%").unwrap().1;
    assert!(near(batt.right(), 612.0) && near(batt.y, 16.0), "battery {batt:?}");
    let nav = fills("nav_bg").into_iter().find(|r| r.y > 440).unwrap();
    assert!(near(nav.w, 39.2) && near(nav.h, 23.7) && near(nav.y, 449.6), "nav chip {nav:?}");
    assert!(canvas.has_text("Navigate") && canvas.has_text("Select"));
}

#[test]
fn dock_symbols_have_one_size() {
    // the star, the gear and the clock: 0.42 of the focused icon each (user's request,
    // 2026-11-15: the gear and the clock were smaller)
    let c = card("docksym", 3, false);
    let mut a = app(&c, FakeSystem::default());
    for item in [DockItem::Favorites, DockItem::Settings, DockItem::Recent] {
        go_dock(&mut a, item);
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        let sel = cv.fills.iter().find(|(r, col)| *col == a.theme.color("icon_sel_bg") && r.w > 100).map(|(r, _)| *r).unwrap();
        let sym = cv.fills.iter().find(|(r, col)| *col == a.theme.color("icon_sel_fg") && sel.contains(r) && r.w > 40).map(|(r, _)| *r).unwrap();
        assert!((sym.w as f32 - 172.8 * 0.42).abs() <= 1.0, "{item:?}: {sym:?}");
    }
}

#[test]
fn ssh_over_wifi_switch_in_the_wifi_panel() {
    let c = card("sshwifi", 3, false);
    let mut a = app(&c, FakeSystem { wifi: true, addr: Some("192.168.1.20".into()), ..Default::default() });
    assert!(!a.settings.ssh_wifi, "off from the factory");
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Wifi).unwrap();
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("SSH over Wi-Fi") && cv.has_text("Off") && !cv.texts.iter().any(|(t, _)| t.starts_with("ssh console@")));
    // ▶ enters the panel on the switch; ◀▶ turns it on, saved for the root service
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert!(a.settings.ssh_wifi);
    let saved = fs::read_to_string(c.root.join("storage/system/lume/settings.toml")).unwrap();
    assert!(saved.lines().any(|l| l == "ssh_wifi = true"), "{saved}");
    // the service has not made the code yet: a dash, and the panel wakes up to show it
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("On") && cv.has_text("ssh console@192.168.1.20") && cv.has_text("Code") && cv.has_text("—"));
    assert_eq!(a.wait(), Some(Duration::from_millis(1000)));
    // the code on the card (made by lume-ssh-wifi): shown as it is; nothing wakes the loop now
    let code_file = c.root.join("storage/system/ssh/wifi-code");
    fs::create_dir_all(code_file.parent().unwrap()).unwrap();
    fs::write(&code_file, "7K4M-9Q2X\n").unwrap();
    assert!(a.handle(Ev::Tick));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("7K4M-9Q2X") && cv.has_text("Generate a new code"));
    assert_eq!(a.wait(), None);
    // the code stays the same until asked: "Generate a new code" (▼ then A)
    press(&mut a, Action::Down);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Select"), "the action line's hint");
    press(&mut a, Action::A);
    let new = fs::read_to_string(&code_file).unwrap().trim().to_string();
    assert!(lume_ui::app::is_ssh_code(&new) && new != "7K4M-9Q2X", "{new}");
    assert_eq!(a.ssh_code().as_deref(), Some(new.as_str()));
    // a broken file is never shown as a code
    fs::write(&code_file, "x; rm\n").unwrap();
    assert_eq!(a.ssh_code(), None);
    // back on the switch: off, and the action line goes away with it
    press(&mut a, Action::Up);
    press(&mut a, Action::A);
    assert!(!a.settings.ssh_wifi && a.ssh_state().is_none() && a.panel_focus == Some(0));
}

#[test]
fn ssh_codes_use_the_alphabet() {
    for _ in 0..50 {
        let code = lume_ui::app::random_ssh_code().unwrap();
        assert!(lume_ui::app::is_ssh_code(&code), "{code}");
    }
    assert!(!lume_ui::app::is_ssh_code("7K4M-9Q2O"), "no O");
    assert!(!lume_ui::app::is_ssh_code("7K4M9Q2X"));
}

#[test]
fn level_colors_follow_the_theme_for_the_line_over_a_game() {
    // lume-input reads them to draw the same lines over a game (RetroArch LUME_LEVEL)
    let c = card("levelcolors", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let path = c.root.join("storage/system/lume/level-colors");
    let hex = |col: lume_ui::canvas::Color| format!("{:02x}{:02x}{:02x}", col.r, col.g, col.b);
    let expect = |a: &App<FakeSystem>| format!("volume={}\nbrightness=ffffff\n", hex(a.theme.color("accent")));
    assert_eq!(fs::read_to_string(&path).unwrap(), expect(&a));
    // another theme: the file follows
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Theme).unwrap();
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert_eq!(a.theme.id, "material-dark");
    assert_eq!(fs::read_to_string(&path).unwrap(), expect(&a));
    assert_eq!(a.theme.color("accent"), lume_ui::canvas::Color::parse("#D0BCFF").unwrap());
}

#[test]
fn fn_volume_keys_show_a_white_line_on_the_left() {
    let c = card("brightbar", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 60, ..Default::default() });
    // on the Dock: the left edge, white, filled from the bottom; no number
    assert!(a.handle(Ev::Brightness(65)));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let white = lume_ui::canvas::Color::rgb(255, 255, 255);
    assert_eq!(a.theme.color("brightness_bar"), white);
    let level = cv.fills.iter().find(|(r, col)| r.x == 0 && r.w == 5 && *col == white).map(|(r, _)| *r).expect("left line");
    assert_eq!((level.h, level.bottom()), (480 * 65 / 100, 480));
    assert!(cv.fills.iter().any(|(r, _)| r.x == 0 && r.w == 5 && r.h == 480), "the track");
    assert!(!cv.has_text("65%"));
    // the Dock's icons keep clear of it (5 px line and the 8 px gap)
    let icons: Vec<_> = cv.fills.iter().filter(|(r, col)| (*col == a.theme.color("icon_bg") || *col == a.theme.color("icon_sel_bg")) && r.w > 40 && r.y < 400).map(|(r, _)| *r).collect();
    assert!(!icons.is_empty() && icons.iter().all(|r| r.x >= 13), "{icons:?}");
    // it goes away after its time, like the volume's
    let wait = a.wait().unwrap();
    assert!(wait <= lume_ui::app::VOLUME_BAR && wait > Duration::from_millis(1000));
    a.brightness_bar = a.brightness_bar.map(|(v, _)| (v, Instant::now()));
    assert!(a.handle(Ev::Tick));
    assert_eq!((a.brightness_bar, a.wait()), (None, None));
    // in the Settings: the Brightness panel shows it, no line
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.handle(Ev::Brightness(70));
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Brightness).unwrap();
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("70%") && !cv.fills.iter().any(|(r, col)| r.x == 0 && *col == white));
}

/// The Settings against the prototype measured in the browser at 640x480 (2026-11-15), Theme
/// focused: title 22.4 px bold at (22.4, 9), battery ending at 617.6; the list from (16, 44.1),
/// 255.4 wide, items 26.7 tall every 28.3, text 16.8 px at +13.44/+3.36; the panel
/// (284.2, 44.1) 339.8 x 391.2, title 19.2 px at (298.6, 53.7), option rows 23.8 tall from
/// 81.6 (text 16 px at +4.8/+1.9), the note 14.4 px 7 px under them; the ▲▼ chip 42.3 wide.
#[test]
fn settings_match_the_prototype_ruler() {
    let c = card("setruler", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), vol: 60, bri: 80, ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Theme).unwrap();
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let text = |s: &str| canvas.texts.iter().filter(|(t, _)| t == s).map(|(_, r)| *r).collect::<Vec<_>>();
    let title = text("Settings")[0];
    assert!(near(title.x, 22.4) && near(title.y, 9.0) && near(title.h, 22.4), "title {title:?}");
    // the battery: the one spot of every screen (the list's)
    let batt = text("82%")[0];
    assert!(near(batt.right(), 612.0) && near(batt.y, 16.0), "battery {batt:?}");
    // the list: Language first, Theme second and focused
    // the list and the panel from 49.6 (user's request, 2026-11-15: the same 14.3 px under
    // the header line, 35.25, as between the panel and the hints' chips; the prototype: 44.1)
    let top = 49.6;
    let sel = canvas.fills.iter().filter(|(r, col)| *col == a.theme.color("sel_bg") && r.x < 100).map(|(r, _)| *r).next().unwrap();
    assert!(near(sel.x, 16.0) && near(sel.y, top + 28.3) && near(sel.w, 255.4) && near(sel.h, 26.7), "focused item {sel:?}");
    let lang = text("Language")[0];
    assert!(near(lang.x, 16.0 + 13.44) && near(lang.y, top + 3.36) && near(lang.h, 16.8), "item text {lang:?}");
    // the panel
    let panel = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 300).map(|(r, _)| *r).unwrap();
    assert!(near(panel.x, 284.2) && near(panel.y, top) && near(panel.w, 339.8) && near(panel.bottom(), 435.3), "panel {panel:?}");
    let ptitle = text("Theme").into_iter().find(|r| r.x > 280).unwrap();
    assert!(near(ptitle.x, 298.6) && near(ptitle.y, top + 9.6) && near(ptitle.h, 19.2), "panel title {ptitle:?}");
    // the options are lines like the list's items (user's request: one text size): Lume
    // chosen (the default), a pill 37.5 under the panel's top, 26.7 tall every 28.3, the
    // text 16.8 px at +13.44/+3.36, as on the left
    let opt = top + 37.5;
    let chosen = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.x > 280).map(|(r, _)| *r).unwrap();
    assert!(near(chosen.y, opt) && near(chosen.h, 26.7) && near(chosen.x, 298.6) && near(chosen.w, 311.0), "chosen {chosen:?}");
    let lume = text("Lume")[0];
    assert!(near(lume.x, 298.6 + 13.44) && near(lume.y, opt + 3.36) && near(lume.h, 16.8), "option {lume:?}");
    assert_eq!(lume.h, lang.h, "the panel's text is the list's size");
    let dark = text("Dark")[0];
    assert!(near(dark.y, opt + 28.3 + 3.36), "second option {dark:?}");
    // the note: one more line under the three options, the same size
    let note = text("to adjust").into_iter().find(|r| r.x > 280).unwrap();
    assert!(near(note.y, opt + 3.0 * 28.3 + 3.36) && near(note.h, 16.8), "note {note:?}");
    // the hints: ▲▼ Navigate, ◀▶ to adjust, B Back
    let ud = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("nav_bg") && r.y > 440 && r.w > 41).map(|(r, _)| *r).unwrap();
    assert!(near(ud.w, 42.3) && near(ud.y, 449.6), "▲▼ chip {ud:?}");
    // equal margins: header line (title box) to the panel, the panel to the chips
    // (the fake canvas gives the text's size as its height; the line is 1.172 of it)
    let above = panel.y - (title.y as f32 + title.h as f32 * 1.172).round() as i32;
    let below = ud.y - panel.bottom();
    assert!((above - below).abs() <= 1, "margins {above} above, {below} below");
    assert!(canvas.has_text("Navigate") && canvas.has_text("Back"));
}

#[test]
fn search_bar_on_top_keyboard_below_and_the_list_between() {
    let c = card("tvsearch", 12, true);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::X);
    // type "1" (numbers row, first key): the list filters as the user types
    press(&mut a, Action::Up);
    press(&mut a, Action::A);
    assert_eq!(a.grid.as_ref().unwrap().filter, "1");
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let n = a.grid.as_ref().unwrap().items.len();
    assert!(n > 0 && n < 12, "{n}");
    // the bar in the header band, with the text and the count; no title, no battery
    let typed = canvas.texts.iter().find(|(s, _)| s == "1").map(|(_, r)| *r).filter(|r| r.y < 53).expect("typed text in the bar");
    assert!(canvas.has_text(&format!("{n} games")) && typed.y < 53);
    assert!(!canvas.has_text(&a.lib.systems[1].name));
    // the keyboard at the bottom, above the hints; the tiles between the bar and it
    let q = canvas.texts.iter().find(|(s, _)| s == "Q").unwrap().1;
    assert!(q.y > 240, "{q:?}");
    // (the keyboard panel may share the tiles' color: the tiles are the tall, narrow ones)
    let tiles: Vec<_> = canvas.fills.iter().filter(|(r, col)| *col == a.theme.color("tile_bg") && r.w > 100 && r.w < 300 && r.h > 100).map(|(r, _)| *r).collect();
    assert!(!tiles.is_empty() && tiles.iter().all(|r| r.y >= 53 && r.bottom() < q.y), "{tiles:?}");
    assert!(canvas.has_text("Close") && !canvas.has_text("Search"));
    // B lowers the keyboard and the bar goes away; the filter stays on the list
    press(&mut a, Action::B);
    assert!(!a.overlay_open());
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    assert!(!canvas.has_text("Q") && !canvas.has_text(&format!("{n} games")));
    // the list name stays whole; the filter shows on the right of the header
    assert!(canvas.has_text(&a.lib.systems[1].name) && canvas.has_text("“1”"));
    assert_eq!(a.grid.as_ref().unwrap().items.len(), n);
}

#[test]
fn settings_panel_text_is_one_size_on_every_item() {
    let c = card("panelsize", 3, false);
    let mut a = app(&c, FakeSystem { vol: 60, bri: 80, wifi: true, ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    for (i, row) in a.set_rows().into_iter().enumerate() {
        a.settings_focus = i;
        a.handle(Ev::Tick);
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        let list_h = cv.texts.iter().find(|(_, r)| r.x < 100 && r.y > 40 && r.y < 400).map(|(_, r)| r.h).unwrap();
        // the panel's texts under its title (and above the hints): all the list's size
        let sizes: Vec<_> = cv.texts.iter().filter(|(_, r)| r.x > 280 && r.y > 75 && r.y < 430).map(|(t, r)| (t.clone(), r.h)).collect();
        assert!(sizes.iter().all(|(_, h)| *h == list_h), "{row:?}: {sizes:?} vs {list_h}");
    }
}

#[test]
fn the_settings_brightness_row_saves_the_level_and_the_volume_row_does_not() {
    // device-fixes 9.15: the user's brightness goes to the card; the volume has its own file
    let c = card("brisave", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let rows = a.set_rows();
    a.settings_focus = rows.iter().position(|r| *r == SetRow::Volume).unwrap();
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert_eq!((a.sys.vol, a.sys.saved_bri), (55, None), "the volume row saves no brightness");
    press(&mut a, Action::B);
    a.settings_focus = rows.iter().position(|r| *r == SetRow::Brightness).unwrap();
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert_eq!((a.sys.bri, a.sys.saved_bri), (85, Some(85)));
    press(&mut a, Action::Left);
    assert_eq!((a.sys.bri, a.sys.saved_bri), (80, Some(80)));
    // nothing about the levels is written to settings.toml any more
    assert!(!card_settings_written(&c) || !fs::read_to_string(c.root.join("storage/system/lume/settings.toml")).unwrap().contains("brightness"));
}

#[test]
fn settings_panel_takes_the_focus() {
    let c = card("panelfocus", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let vol = a.set_rows().iter().position(|r| *r == SetRow::Volume).unwrap();
    a.settings_focus = vol;
    // ◀▶ on the list change nothing
    press(&mut a, Action::Left);
    press(&mut a, Action::Right);
    assert_eq!((a.sys.vol, a.panel_focus), (50, Some(0)), "▶ entered the panel, nothing changed");
    // in the panel: ◀▶ adjust, ▲▼ stay on the one line, the hints are the line's
    press(&mut a, Action::Right);
    assert_eq!(a.sys.vol, 55);
    press(&mut a, Action::Down);
    assert_eq!(a.panel_focus, Some(0));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("to adjust") && !cv.has_text("Navigate") && !cv.has_text("Open"));
    // the owner item: a tonal pill, not the focus pill; the panel's line has the focus
    let sel = a.theme.color("sel_bg");
    assert!(!cv.fills.iter().any(|(r, col)| *col == sel && r.x < 100), "no focus pill on the list");
    let line = cv.fills.iter().find(|(r, col)| *col == sel && r.x > 280).map(|(r, _)| *r).expect("focused line");
    let tonal = cv.fills.iter().find(|(r, col)| r.x == 16 && r.w > 250 && r.h < 30 && *col != sel).map(|(r, _)| *r).expect("owner mark");
    assert!(tonal.y > 49 && line.y > tonal.y - 300);
    // B goes back to the same item of the list
    press(&mut a, Action::B);
    assert_eq!((a.screen, a.settings_focus, a.panel_focus), (Screen::Settings, vol, None));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Navigate") && cv.has_text("Open"));
    // a choice list: entering lands on the chosen one; ▲▼ wrap; A picks
    a.settings_focus = 0; // Language
    press(&mut a, Action::A);
    assert_eq!(a.panel_focus, Some(0));
    press(&mut a, Action::Up);
    assert_eq!(a.panel_focus, Some(2), "wraps to the last");
    assert_eq!(a.settings.language, "en", "moving does not pick");
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Navigate") && cv.has_text("Select"));
    press(&mut a, Action::A);
    assert_eq!(a.settings.language, "es");
    // items without lines: System is only read, Power off is its own action
    press(&mut a, Action::B);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::System).unwrap();
    press(&mut a, Action::Right);
    press(&mut a, Action::A);
    assert_eq!(a.panel_focus, None);
    // B on the list leaves the Settings
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Dock);
}

#[test]
fn settings_panel_focus_matches_the_ruler() {
    let c = card("panelruler", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let theme = a.set_rows().iter().position(|r| *r == SetRow::Theme).unwrap();
    a.settings_focus = theme;
    press(&mut a, Action::A);
    press(&mut a, Action::Down); // the focus on the second theme, Lume still chosen
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let top = 49.6;
    // the owner item where the focus pill was (16, top + 28.3, 255.4 x 26.7), tonal
    let owner = cv.fills.iter().find(|(r, _)| near(r.x, 16.0) && near(r.y, top + 28.3) && near(r.w, 255.4)).map(|(r, col)| (*r, *col)).expect("owner");
    assert!(near(owner.0.h, 26.7) && owner.1 != a.theme.color("sel_bg"), "{owner:?}");
    // the focused line: the second option's pill (one pitch under the first)
    let opt = top + 37.5;
    let pill = cv.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.x > 280).map(|(r, _)| *r).unwrap();
    assert!(near(pill.y, opt + 28.3) && near(pill.h, 26.7) && near(pill.x, 298.6) && near(pill.w, 311.0), "{pill:?}");
    // the chosen one keeps its ✓ but no pill; the hints are the line's
    assert!(cv.has_text("Select") && cv.has_text("Navigate") && cv.has_text("Back"));
}

#[test]
fn game_menu_sheet_matches_the_prototype_ruler() {
    let c = card("sheet", 3, true);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1)); // snes, with covers
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    let name = a.focused_name().unwrap();
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let text = |cv: &FakeCanvas, s: &str| cv.texts.iter().find(|(t, _)| t == s).map(|(_, r)| *r).unwrap_or_else(|| panic!("{s}"));
    // the sheet: 576 wide from 32, centered; the cover column 160 wide from 46.4
    let sheet = cv.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 500).map(|(r, _)| *r).unwrap();
    assert!(near(sheet.x, 32.0) && near(sheet.w, 576.0) && (sheet.y + sheet.bottom() - 480).abs() <= 1, "{sheet:?}");
    let cover = cv.fills.iter().find(|(r, col)| *col == a.theme.color("tile_bg_opaque") && near(r.x, 46.4)).map(|(r, _)| *r).expect("cover column");
    assert!(near(cover.w, 160.0) && near(cover.y, sheet.y as f32 + 14.4) && near(cover.bottom(), sheet.bottom() as f32 - 14.4), "{cover:?}");
    // the title 28 px bold, the subtitle (the system) 19.2 px 35 lower
    // (the grid under the sheet shows the same name above its hints)
    let title = cv.texts.iter().find(|(t, r)| *t == name && r.x > 200 && r.y < 300).map(|(_, r)| *r).unwrap();
    assert!(near(title.x, 220.8) && near(title.h, 28.0), "{title:?}");
    let sub = text(&cv, &a.lib.systems[1].abbr);
    assert!(near(sub.y, title.y as f32 + 35.0) && near(sub.h, 19.2), "{sub:?}");
    // the rows 39.2 tall from 70.5 under the title, the label 20 px at (16, 7.6)
    let pill = cv.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.x > 200 && r.w > 300).map(|(r, _)| *r).unwrap();
    assert!(near(pill.x, 220.8) && near(pill.w, 372.8) && near(pill.h, 39.2) && near(pill.y, title.y as f32 + 70.5), "{pill:?}");
    let start = text(&cv, "Start game");
    assert!(near(start.x, 236.8) && near(start.y, pill.y as f32 + 7.6) && near(start.h, 20.0), "{start:?}");
    let fav = text(&cv, "Add to favorites");
    assert!(near(fav.y, pill.y as f32 + 3.0 * 39.2 + 7.6), "{fav:?}");
    // no states: the row says so, faded
    assert!(cv.has_text("no save states"));
    // the Settings submenu: "Default (value)", ‹ › only on the focused row
    press(&mut a, Action::Down);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text(&format!("{} · Settings", a.lib.systems[1].abbr)));
    let focused = cv.texts.iter().filter(|(t, _)| t.starts_with("‹ Default (") && t.ends_with(") ›")).count();
    let others = cv.texts.iter().filter(|(t, _)| t.starts_with("Default (") && !t.contains('‹')).count();
    assert_eq!((focused, others), (1, 2), "{:?}", cv.texts);
    assert!(cv.has_text("Default (Core)") && cv.has_text("Default (None)"));
    // (three rows: the sheet is shorter and centered again)
    let title = cv.texts.iter().find(|(t, r)| *t == name && r.x > 200 && r.y < 300).map(|(_, r)| *r).unwrap();
    let value = cv.texts.iter().find(|(t, _)| t.starts_with("‹ Default")).map(|(_, r)| *r).unwrap();
    assert!(near(value.right(), 593.6 - 16.0) && near(value.h, 17.0) && near(value.y, title.y as f32 + 70.5 + 9.6), "{value:?} {title:?}");
    // a value of the game's own: plain (no "Default"), and the console options count it
    press(&mut a, Action::Down);
    press(&mut a, Action::Right); // Aspect: Default -> the first one
    press(&mut a, Action::Up); // the focus off it: no arrows
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("Default (Core)") && cv.texts.iter().filter(|(t, _)| t.starts_with("Default (")).count() == 1, "{:?}", cv.texts);
    press(&mut a, Action::B); // the game menu
    press(&mut a, Action::B); // the grid
    assert!(!a.overlay_open());
    press(&mut a, Action::Y);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text(&a.lib.systems[1].name) && cv.has_text("Console options"));
    assert!(cv.has_text("1") && cv.has_text("Clear game options"));
    // the console column shows its abbreviation when the theme has no logo
    assert!(cv.texts.iter().any(|(t, r)| *t == a.lib.systems[1].abbr && r.x < 220));
}

// ---- the system menu of the Fn button (device-fixes 9.11, D19) ----

fn fn_tap(a: &mut App<FakeSystem>) {
    assert!(a.handle(Ev::FnTap));
}

/// The sheet of the system menu: the panel_bg fill that is not the whole width.
fn panel(a: &App<FakeSystem>, cv: &FakeCanvas, min_w: i32) -> lume_ui::canvas::Rect {
    cv.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > min_w).map(|(r, _)| *r).expect("sheet")
}

#[test]
fn system_menu_over_the_grid_and_back_on_the_same_game() {
    let c = card("sys-grid", 12, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    let name = a.focused_name().unwrap();
    fn_tap(&mut a);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("System menu") && cv.has_text("Settings") && cv.has_text("Suspend") && cv.has_text("Restart") && cv.has_text("Power off"));
    // the buttons go to the menu, not to the grid: Down moves the menu's focus
    press(&mut a, Action::Down);
    press(&mut a, Action::Right);
    assert_eq!(a.focused_name().unwrap(), name);
    // another tap closes it; the grid is as it was
    fn_tap(&mut a);
    assert_eq!(a.screen, Screen::Grid);
    assert_eq!(a.focused_name().unwrap(), name);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("System menu"));
    // B closes it too
    fn_tap(&mut a);
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Grid);
    assert_eq!(a.focused_name().unwrap(), name);
}

#[test]
fn system_menu_over_an_open_sheet_keeps_it() {
    let c = card("sys-sheet", 3, true);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::A); // the game sheet
    assert!(a.overlay_open());
    fn_tap(&mut a);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("System menu") && cv.has_text("Start game"), "both layers are drawn");
    fn_tap(&mut a);
    assert!(a.overlay_open(), "the sheet stays open under the menu");
    // the sheet takes the buttons again
    press(&mut a, Action::B);
    assert!(!a.overlay_open());
}

#[test]
fn system_menu_focus_starts_on_settings_and_wraps() {
    let c = card("sys-focus", 3, false);
    let mut a = app(&c, FakeSystem::default());
    fn_tap(&mut a);
    // A on the first item opens the Settings
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    // up from Settings wraps to Power off: its confirmation opens
    let mut b = app(&c, FakeSystem::default());
    fn_tap(&mut b);
    press(&mut b, Action::Up);
    press(&mut b, Action::A);
    let mut cv = FakeCanvas::new(640, 480);
    b.draw(&mut cv);
    assert!(cv.has_text("The device will be turned off."));
}

#[test]
fn restart_and_power_off_confirmations_default_to_cancel_and_only_up_down_change_it() {
    let c = card("sys-confirm", 3, false);
    // (the item index, the exit code the action gives, the question)
    for (downs, exit, ask) in [(2, Exit::Restart, "The device will restart."), (3, Exit::Shutdown, "The device will be turned off.")] {
        let mut a = app(&c, FakeSystem::default());
        fn_tap(&mut a);
        for _ in 0..downs {
            press(&mut a, Action::Down);
        }
        press(&mut a, Action::A);
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        assert!(cv.has_text(ask) && cv.has_text("Cancel"));
        // the focus starts on Cancel: A does nothing and the menu is back
        press(&mut a, Action::A);
        assert_eq!(a.exit, None);
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        assert!(cv.has_text("System menu"), "Cancel goes back to the menu");
        // reopen: left and right change nothing, A still cancels
        press(&mut a, Action::A);
        press(&mut a, Action::Left);
        press(&mut a, Action::Right);
        press(&mut a, Action::A);
        assert_eq!(a.exit, None);
        // reopen: Up picks the action (left/right again do nothing), Down gets back to Cancel
        press(&mut a, Action::A);
        press(&mut a, Action::Up);
        press(&mut a, Action::Down);
        press(&mut a, Action::A);
        assert_eq!(a.exit, None, "Down went back to Cancel");
        press(&mut a, Action::A);
        press(&mut a, Action::Up);
        press(&mut a, Action::Left);
        press(&mut a, Action::Right);
        press(&mut a, Action::A);
        assert_eq!(a.exit, Some(exit));
    }
    assert_eq!(Exit::Restart as i32, 66);
    assert_eq!(Exit::Shutdown as i32, 0);
}

#[test]
fn confirmation_has_the_action_above_cancel_and_matches_the_prototype_ruler() {
    let c = card("sys-confirm-ruler", 3, false);
    let mut a = app(&c, FakeSystem::default());
    fn_tap(&mut a);
    press(&mut a, Action::Down);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let near = |v: i32, b: f32| (v as f32 - b).abs() <= 1.0;
    // the sheet 576 x 177.7 at (32, 151.2)
    let sheet = panel(&a, &cv, 500);
    assert!(near(sheet.x, 32.0) && near(sheet.y, 151.2) && near(sheet.w, 576.0) && near(sheet.h, 177.7), "{sheet:?}");
    let t = |s: &str| cv.texts.iter().find(|(x, _)| x == s).map(|(_, r)| *r).unwrap_or_else(|| panic!("{s}"));
    let (action, cancel) = (t("Restart"), t("Cancel"));
    assert!(action.y < cancel.y);
    // the rows 39.2 tall from 236.1: the action, then Cancel (the focused pill) at 275.3
    let pill = cv.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.w > 500).map(|(r, _)| *r).unwrap();
    assert!(near(pill.x, 46.4) && near(pill.y, 275.3) && near(pill.w, 547.2) && near(pill.h, 39.2), "{pill:?}");
    assert!(near(action.y, 236.1 + 7.6) && near(cancel.y, 275.3 + 7.6), "{action:?} {cancel:?}");
}

#[test]
fn system_menu_sheet_matches_the_prototype_ruler() {
    let c = card("sys-ruler", 3, false);
    let mut a = app(&c, FakeSystem::default());
    // the table was measured in Portuguese
    a.settings.language = "pt".into();
    a.texts = lume_ui::i18n::Texts::load(&repo().join("aports/lume-launcher-data/files/usr/share/lume/i18n"), "pt");
    fn_tap(&mut a);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let near = |v: i32, b: f32| (v as f32 - b).abs() <= 1.0;
    // the sheet 259.6 x 220.5 at (190.2, 129.7)
    // (the last one drawn: the Dock's icons come before the sheet)
    let sheet = cv.fills.iter().rev().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 200 && r.h > 200).map(|(r, _)| *r).expect("sheet");
    assert!(near(sheet.x, 190.2) && near(sheet.y, 129.7) && near(sheet.w, 259.6) && near(sheet.h, 220.5), "{sheet:?}");
    // the first item in focus (the pill) 230.8 x 39.2 at (204.6, 179.1)
    let pill = cv.fills.iter().rev().find(|(r, col)| *col == a.theme.color("sel_bg") && r.w > 100).map(|(r, _)| *r).unwrap();
    assert!(near(pill.x, 204.6) && near(pill.y, 179.1) && near(pill.w, 230.8) && near(pill.h, 39.2), "{pill:?}");
    // the items every 39.2 (Suspend, Restart, Power off at 218.3, 257.5, 296.7 + the 7.6 of the text)
    let items: Vec<(String, i32)> = ["Configurações", "Suspender", "Reiniciar", "Desligar"]
        .iter()
        .map(|s| (s.to_string(), cv.texts.iter().filter(|(t, r)| t == s && r.x > 200 && r.y > 170).map(|(_, r)| r.y).min().unwrap_or_else(|| panic!("{s}"))))
        .collect();
    for (i, (s, y)) in items.iter().enumerate() {
        assert!(near(*y, 179.1 + i as f32 * 39.2 + 7.6), "{s} at {y}");
    }
}

// ---- the Fn hold hint (device-fixes 9.13, D19) ----

fn hold_table() -> Vec<lume_core::input::HoldEntry> {
    ["B=app_menu", "Vol=brightness", "Start=quit"]
        .iter()
        .map(|p| {
            let (b, a) = p.split_once('=').unwrap();
            lume_core::input::HoldEntry { button: b.into(), action: a.into() }
        })
        .collect()
}

fn lang_app(c: &Card, lang: &str) -> App<FakeSystem> {
    let mut a = app(c, FakeSystem::default());
    a.settings.language = lang.into();
    a.texts = lume_ui::i18n::Texts::load(&repo().join("aports/lume-launcher-data/files/usr/share/lume/i18n"), lang);
    a
}

fn hint_panel(a: &App<FakeSystem>, cv: &FakeCanvas) -> Option<lume_ui::canvas::Rect> {
    cv.fills.iter().rev().find(|(r, col)| *col == a.theme.color("panel_bg_opaque") && r.w > 300 && r.h < 120).map(|(r, _)| *r)
}

#[test]
fn hold_hint_matches_the_prototype_ruler_in_pt_and_es() {
    let near = |v: i32, b: f32| (v as f32 - b).abs() <= 1.0;
    // The prototype's widths (pt 352.5, es 358.3; rows 303.2) come from the browser's font; the
    // bundled one is wider, so the width is checked as the widest row plus the 1.1 em paddings
    // (24.64 px each side) and the panel centred. Heights, y and the paddings are font-free.
    for (lang, tap, bri) in [("pt", "(toque): Menu do sistema", ": Brilho"), ("es", "(toque): Menú del sistema", ": Brillo")] {
        let c = card("hold-ruler", 3, false);
        let mut a = lang_app(&c, lang);
        assert!(a.handle(Ev::FnHold(hold_table())));
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        let p = hint_panel(&a, &cv).expect("hint panel");
        assert!(near(p.y, 193.4) && near(p.h, 93.2), "{lang} {p:?}");
        assert!(((p.x + p.w / 2) - 320).abs() <= 1, "centred {p:?}");
        // the two rows at y 209.1 and 243.9 (27 high, 22.4 px text: the text top 2.3 below), x 168.4
        let text = |s: &str| cv.texts.iter().find(|(t, r)| t == s && r.y >= p.y && r.y < p.bottom()).map(|(_, r)| *r).unwrap_or_else(|| panic!("{s}"));
        let (fn1, t1, fn2, t2) = (text("Fn"), text(tap), text("Fn+Vol"), text(bri));
        assert!(near(fn1.x, p.x as f32 + 24.64) && near(fn2.x, p.x as f32 + 24.64), "{fn1:?} {fn2:?}");
        assert!(near(fn1.y, 209.1 + 2.3) && near(t1.y, 209.1 + 2.3) && near(fn2.y, 243.9 + 2.3) && near(t2.y, 243.9 + 2.3));
        // the panel is the widest row (the first here) plus the paddings
        assert!(near(p.w, (t1.right() - fn1.x) as f32 + 49.28), "{p:?} {fn1:?} {t1:?}");
        assert!(t1.x > fn1.x + fn1.w - 1 && t2.x >= fn2.x + fn2.w - 1);
    }
}

#[test]
fn hold_hint_shows_the_two_items_and_hides_on_release_without_opening_the_menu() {
    let c = card("hold-release", 3, false);
    let mut a = lang_app(&c, "en");
    assert!(a.handle(Ev::FnHold(hold_table())));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Fn") && cv.has_text("(tap): System menu") && cv.has_text("Fn+Vol") && cv.has_text(": Brightness"));
    assert!(!cv.has_text("System menu"), "no menu");
    assert!(a.handle(Ev::FnRelease), "the hint needs a frame to go");
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("Fn+Vol") && hint_panel(&a, &cv).is_none());
    assert!(!cv.has_text("System menu") && !cv.has_text("Suspend"), "the release is not a tap");
    // a release without a hint changes nothing
    assert!(!a.handle(Ev::FnRelease));
}

#[test]
fn hold_hint_lists_only_the_chords_the_launcher_handles() {
    let c = card("hold-chords", 3, false);
    let mut a = lang_app(&c, "en");
    assert!(a.handle(Ev::FnHold(vec![])));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(hint_panel(&a, &cv).is_some() && !cv.has_text("Fn+Vol"));
}

#[test]
fn hold_hint_hides_on_brightness() {
    let c = card("hold-bri", 3, false);
    let mut a = lang_app(&c, "en");
    assert!(a.handle(Ev::FnHold(hold_table())));
    assert!(a.handle(Ev::Brightness(40)));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("Fn+Vol") && hint_panel(&a, &cv).is_none());
}

#[test]
fn hold_hint_is_ignored_with_the_system_menu_open_and_goes_when_it_opens() {
    let c = card("hold-menu", 3, false);
    let mut a = lang_app(&c, "en");
    fn_tap(&mut a);
    assert!(!a.handle(Ev::FnHold(hold_table())));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("System menu") && !cv.has_text("Fn+Vol"));
    fn_tap(&mut a);
    // a hint that is up when the menu opens (a tap event while held) goes away
    assert!(a.handle(Ev::FnHold(hold_table())));
    fn_tap(&mut a);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("System menu") && !cv.has_text("Fn+Vol"));
}

#[test]
fn suspend_item_writes_the_request_without_a_confirmation_and_closes_the_menu() {
    let c = card("sys-suspend", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let dir = c.root.join("sleep");
    fs::create_dir_all(&dir).unwrap();
    a.sleep_dir = dir.clone();
    fn_tap(&mut a);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    assert!(dir.join("suspend").is_file());
    assert_eq!(a.exit, None);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("System menu"), "the menu closed");
    // a second one while the first waits makes nothing new and does not fail
    fn_tap(&mut a);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    assert!(dir.join("suspend").is_file());
}

#[test]
fn settings_from_the_menu_and_b_back_to_the_grid_and_to_a_sheet() {
    let c = card("sys-settings", 12, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::Right);
    press(&mut a, Action::Down);
    let name = a.focused_name().unwrap();
    fn_tap(&mut a);
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    assert_eq!(a.settings_focus, 0);
    // B on the list: back to the grid, on the same game
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Grid);
    assert_eq!(a.focused_name().unwrap(), name);
    // with a game sheet open: it comes back open
    press(&mut a, Action::A);
    assert!(a.overlay_open());
    fn_tap(&mut a);
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    assert!(!a.overlay_open(), "the sheet waits behind the Settings");
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Grid);
    assert!(a.overlay_open());
    press(&mut a, Action::B);
    assert!(!a.overlay_open());
    // from the Dock, B goes to the Dock as before
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Dock);
    fn_tap(&mut a);
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    press(&mut a, Action::B);
    assert_eq!(a.screen, Screen::Dock);
}

#[test]
fn settings_lose_power_suspend_and_retroarch_and_wrap_at_games() {
    let c = card("sys-setrows", 3, false);
    let a = app(&c, FakeSystem::default());
    assert_eq!(a.set_rows().last(), Some(&SetRow::Games));
    let mut a = app(&c, FakeSystem { wifi: true, bluetooth: true, ..Default::default() });
    assert_eq!(&a.set_rows()[..2], [SetRow::Wifi, SetRow::Bluetooth]);
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let n = a.set_rows().len();
    assert_eq!(a.set_rows()[n - 1], SetRow::Games);
    // down on Games goes to the first item; up on the first goes to Games
    a.settings_focus = n - 1;
    press(&mut a, Action::Down);
    assert_eq!(a.settings_focus, 0);
    press(&mut a, Action::Up);
    assert_eq!(a.settings_focus, n - 1);
    // no text of the removed items on any row of the list
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("Power off") && !cv.has_text("Suspend") && !cv.has_text("RetroArch"));
}

#[test]
fn dock_footer_shows_the_fn_hint_after_navigate_and_select() {
    let c = card("sys-hint", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let t = |s: &str| cv.texts.iter().find(|(x, _)| x == s).map(|(_, r)| *r).unwrap_or_else(|| panic!("{s}"));
    let (nav, sel, menu) = (t("Navigate"), t("Select"), t("Menu"));
    assert!(nav.x < sel.x && sel.x < menu.x, "the third hint, after ◀▶ and A");
    assert!((menu.y - 448).abs() <= 2 && menu.y == sel.y, "{menu:?} {sel:?}");
    assert!(cv.has_text("Fn"));
}

#[test]
fn games_item_holds_update_lists() {
    let c = card("games-item", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    // "Update lists" is no longer an item of its own: it lives in Games
    let rows = a.set_rows();
    let games = rows.iter().position(|r| *r == SetRow::Games).unwrap();
    a.settings_focus = games;
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let list_texts: Vec<_> = cv.texts.iter().filter(|(_, r)| r.x < 280).map(|(t, _)| t.clone()).collect();
    assert!(list_texts.contains(&"Games".to_string()) && !list_texts.contains(&"Update lists".to_string()), "{list_texts:?}");
    let in_panel = cv.texts.iter().any(|(t, r)| t == "Update lists" && r.x > 280);
    assert!(in_panel, "Update lists is a line of the Games panel");
    assert!(cv.has_text("A to update") && cv.has_text("Open"));
    // A on Games enters its panel; A there starts the update
    press(&mut a, Action::A);
    assert!(!a.start_update && a.panel_focus == Some(0));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Update") && !cv.has_text("Navigate"), "one line: no ▲▼ hint");
    press(&mut a, Action::A);
    assert!(a.start_update && a.updating.is_some());
}

/// The Settings on the Card item with its panel entered (focus on "Optimize now"), the
/// service's folders inside the test card.
fn open_card(c: &Card, free: Option<u64>) -> App<FakeSystem> {
    let mut a = app(c, FakeSystem { free, ..Default::default() });
    a.card_run = c.root.join("cardrun");
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    while a.set_rows()[a.settings_focus] != SetRow::Card {
        press(&mut a, Action::Down);
    }
    a
}

fn draw_texts(a: &mut App<FakeSystem>) -> FakeCanvas {
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    cv
}

#[test]
fn card_item_sits_between_system_and_games() {
    let c = card("card-order", 3, false);
    let a = app(&c, FakeSystem::default());
    let rows = a.set_rows();
    let i = rows.iter().position(|r| *r == SetRow::Card).unwrap();
    assert_eq!((rows[i - 1], rows[i + 1]), (SetRow::System, SetRow::Games));
}

#[test]
fn card_panel_without_history_says_never() {
    let c = card("card-never", 3, false);
    let mut a = open_card(&c, Some(58_400_000_000));
    let cv = draw_texts(&mut a);
    assert!(cv.has_text("Free space") && cv.has_text("58.4 GB"));
    assert!(cv.has_text("Last optimization") && cv.has_text("Last check"));
    assert_eq!(cv.texts.iter().filter(|(t, _)| t == "never").count(), 2);
    assert!(cv.has_text("Optimize now") && cv.has_text("Check on next boot"));
    assert!(!cv.has_text("Scheduled") && !cv.has_text("Optimizing…"));
}

#[test]
fn card_panel_with_history_shows_the_boot_numbers() {
    let c = card("card-history", 3, false);
    let m = c.root.join("storage/system/card");
    fs::create_dir_all(&m).unwrap();
    fs::write(m.join("last-trim"), "150\n").unwrap();
    fs::write(m.join("last-check"), "140\n").unwrap();
    let mut a = open_card(&c, None);
    let cv = draw_texts(&mut a);
    assert!(cv.has_text("boot 150") && cv.has_text("boot 140") && !cv.has_text("never"));
    // free space unreadable: a dash
    assert!(cv.has_text("—"));
    // garbage reads as never
    fs::write(m.join("last-trim"), "junk").unwrap();
    let mut a = open_card(&c, None);
    let cv = draw_texts(&mut a);
    assert!(cv.has_text("never") && cv.has_text("boot 140") && !cv.has_text("boot 150"));
}

#[test]
fn card_trim_request_and_every_state() {
    let c = card("card-trim", 3, false);
    let mut a = open_card(&c, Some(1_000_000_000));
    let run = c.root.join("cardrun");
    press(&mut a, Action::A); // enter the panel
    assert!(!run.join("trim").exists(), "entering writes nothing");
    // a stale answer of an earlier run is dropped when the request is written
    fs::create_dir_all(&run).unwrap();
    fs::write(run.join("status"), "ok 5\n").unwrap();
    press(&mut a, Action::A);
    assert!(run.join("trim").is_file() && !run.join("status").exists(), "A writes the trim request");
    let cv = draw_texts(&mut a);
    assert!(cv.has_text("Optimizing…"));
    // a second A while it runs writes nothing more
    fs::remove_file(run.join("trim")).unwrap();
    press(&mut a, Action::A);
    assert!(!run.join("trim").exists());
    // the service answers: running, then ok with the size (polled once a second)
    fs::write(run.join("status"), "running\n").unwrap();
    std::thread::sleep(Duration::from_millis(1000));
    a.handle(Ev::Tick);
    assert!(draw_texts(&mut a).has_text("Optimizing…"));
    let m = c.root.join("storage/system/card");
    fs::create_dir_all(&m).unwrap();
    fs::write(m.join("last-trim"), "152\n").unwrap();
    fs::write(run.join("status"), "ok 1288490188\n").unwrap();
    std::thread::sleep(Duration::from_millis(1000));
    assert!(a.handle(Ev::Tick));
    let cv = draw_texts(&mut a);
    // the ✓ is drawn, never sent to the font (it has none: a box on the R36S, 2026-11-19)
    assert!(cv.has_text("1.3 GB freed") && cv.has_text("boot 152") && !cv.has_text("Optimizing…"));
    assert!(!cv.texts.iter().any(|(t, _)| t.contains('✓')));
    // fail: the card's message, in red outside the focus
    fs::remove_file(run.join("trim")).ok();
    press(&mut a, Action::A);
    fs::write(run.join("status"), "fail not supported\n").unwrap();
    std::thread::sleep(Duration::from_millis(1000));
    assert!(a.handle(Ev::Tick));
    press(&mut a, Action::Down); // the focus leaves the line
    let cv = draw_texts(&mut a);
    assert!(cv.has_text("Card not supported"));
    // leaving the item drops the state: back, it reads idle
    press(&mut a, Action::B); // out of the panel
    press(&mut a, Action::Up);
    press(&mut a, Action::Down);
    assert!(!draw_texts(&mut a).has_text("Card not supported"));
}

#[test]
fn card_running_trim_is_seen_when_the_panel_opens() {
    let c = card("card-already", 3, false);
    let run = c.root.join("cardrun");
    fs::create_dir_all(&run).unwrap();
    fs::write(run.join("status"), "running\n").unwrap();
    let mut a = open_card(&c, None);
    assert!(draw_texts(&mut a).has_text("Optimizing…"));
}

#[test]
fn card_check_request_is_written_shown_and_cancelled_by_a_again() {
    let c = card("card-check", 3, false);
    let mut a = open_card(&c, None);
    let run = c.root.join("cardrun");
    press(&mut a, Action::A);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    assert!(run.join("check-next-boot").is_file(), "A writes the request");
    assert!(draw_texts(&mut a).has_text("Scheduled"));
    // the service picked it up: the request file went, the marker came
    fs::remove_file(run.join("check-next-boot")).unwrap();
    let m = c.root.join("storage/system/card");
    fs::create_dir_all(&m).unwrap();
    fs::write(m.join("check-next-boot"), "152\n").unwrap();
    // A again cancels: the marker is deleted and the line is idle
    press(&mut a, Action::A);
    assert!(!m.join("check-next-boot").exists() && !run.join("check-next-boot").exists());
    assert!(!draw_texts(&mut a).has_text("Scheduled"));
    // a pending marker from an earlier boot shows when the panel opens
    fs::write(m.join("check-next-boot"), "152\n").unwrap();
    press(&mut a, Action::B); // out of the panel
    press(&mut a, Action::Up);
    press(&mut a, Action::Down);
    assert!(draw_texts(&mut a).has_text("Scheduled"));
}

#[test]
fn card_status_is_polled_only_while_the_trim_runs_and_the_panel_is_open() {
    let c = card("card-poll", 3, false);
    let mut a = open_card(&c, None);
    let run = c.root.join("cardrun");
    // idle: nothing wakes the loop
    assert_eq!(a.wait(), None);
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    assert!(run.join("trim").is_file());
    // running and open: once a second
    assert_eq!(a.wait(), Some(Duration::from_millis(1000)));
    // the panel closes (B, then another item): the polling stops
    press(&mut a, Action::B);
    press(&mut a, Action::Down);
    assert_eq!(a.wait(), None);
    fs::write(run.join("status"), "ok 1\n").unwrap();
    std::thread::sleep(Duration::from_millis(1000));
    assert!(!a.handle(Ev::Tick), "no reading while away");
    // back on the item: the TRIM is over, idle again, nothing to poll
    press(&mut a, Action::Up);
    assert_eq!(a.wait(), None);
}

/// The Card panel against the prototype's table (task 4.1) at 640x480, in the layout of the
/// other panels (lines like the list's items, panel from 49.6): x 298.6, 311.0 wide, title
/// 19.2 px, info rows and the two actions every 28.3 from 37.5 under the panel's top, the
/// pill 26.7 tall, the text 16.8 px at +13.44/+3.36.
#[test]
fn card_matches_the_prototype_ruler() {
    let c = card("card-ruler", 3, false);
    let mut a = open_card(&c, Some(58_400_000_000));
    press(&mut a, Action::A); // the pill on "Optimize now"
    let cv = draw_texts(&mut a);
    let near = |a: i32, b: f32| (a as f32 - b).abs() <= 1.0;
    let text = |s: &str| cv.texts.iter().filter(|(t, _)| t == s).map(|(_, r)| *r).collect::<Vec<_>>();
    let top = 49.6;
    let panel = cv.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 300).map(|(r, _)| *r).unwrap();
    assert!(near(panel.x, 284.2) && near(panel.y, top) && near(panel.w, 339.8) && near(panel.bottom(), 435.3), "panel {panel:?}");
    let title = text("Card").into_iter().find(|r| r.x > 280).unwrap();
    assert!(near(title.x, 298.6) && near(title.y, top + 9.6) && near(title.h, 19.2), "title {title:?}");
    let first = top + 37.5;
    for (i, label) in ["Free space", "Last optimization", "Last check", "Optimize now", "Check on next boot"].into_iter().enumerate() {
        let t = text(label).into_iter().find(|r| r.x > 280).unwrap_or_else(|| panic!("{label}"));
        // (the pitch is 1.769 em = 28.304 px, the text inset 0.21 em rounded to 3 px)
        let y = first + i as f32 * 28.304;
        assert!(near(t.x, 298.6 + 13.44) && near(t.y, y + 3.0) && near(t.h, 16.8), "{label} {t:?}");
    }
    // the focused action: the pill of the same measures as the other panels' lines
    let pill = cv.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.x > 280).map(|(r, _)| *r).unwrap();
    assert!(near(pill.x, 298.6) && near(pill.y, first + 3.0 * 28.3) && near(pill.w, 311.0) && near(pill.h, 26.7), "pill {pill:?}");
    // the values end at the same inset on the right
    let free = text("58.4 GB")[0];
    assert!(near(free.right(), 298.6 + 311.0 - 13.44), "value {free:?}");
    assert!(cv.has_text("Select") && cv.has_text("Navigate") && cv.has_text("Back"));
}

#[test]
fn display_option_hides_the_battery_percent() {
    let c = card("display", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    assert!(a.settings.battery_percent, "on by default");
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    // the item right after Theme, with its option and value in the panel
    let rows = a.set_rows();
    let display = rows.iter().position(|r| *r == SetRow::Display).unwrap();
    assert_eq!(rows[display - 1], SetRow::Theme);
    a.settings_focus = display;
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Display") && cv.has_text("Battery percentage") && cv.has_text("On"));
    // ◀▶ turns it off: no percent, the icon alone ends where the percent ended
    let pct = cv.texts.iter().find(|(t, _)| t == "82%").map(|(_, r)| *r).unwrap();
    press(&mut a, Action::A); // into the panel
    press(&mut a, Action::Right);
    assert!(!a.settings.battery_percent);
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(!cv.has_text("82%") && cv.has_text("Off"));
    let fg = a.theme.color("fg");
    let icon_right = cv.fills.iter().filter(|(r, col)| *col == fg && r.y < 45 && r.x > 500).map(|(r, _)| r.right()).max().unwrap();
    assert!((icon_right - pct.right()).abs() <= 1, "icon ends at {icon_right}, the percent ended at {}", pct.right());
    // saved: a new start keeps it off; ◀▶ again turns it back on
    let b = app(&c, FakeSystem { batt: Some((82, false)), ..Default::default() });
    assert!(!b.settings.battery_percent);
    press(&mut a, Action::Left);
    assert!(a.settings.battery_percent);
}

#[test]
fn network_icons_next_to_the_battery_on_every_screen() {
    let c = card("netbar", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, false)), net: (true, true), ..Default::default() });
    // the icons of the status bar: the text-colored marks right of the middle, in its band
    let marks = |a: &mut App<FakeSystem>| {
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        let fg = a.theme.color("fg");
        let pct = cv.texts.iter().find(|(t, _)| t == "82%").map(|(_, r)| *r).unwrap();
        let mut icons: Vec<_> = cv.fills.iter().filter(|(r, col)| *col == fg && r.y < 45 && r.x > 400 && r.right() < pct.x - 40 && r.h > 10).map(|(r, _)| *r).collect();
        icons.sort_by_key(|r| r.x);
        icons.dedup();
        icons
    };
    let on_dock = marks(&mut a);
    // Wi-Fi then Bluetooth, 0.9 of the 19.2 px text tall, 20:14 and 10:14
    assert_eq!(on_dock.len(), 2, "{on_dock:?}");
    let (wifi, bt) = (on_dock[0], on_dock[1]);
    assert!((wifi.h - 17).abs() <= 1 && (wifi.w - 25).abs() <= 1, "wifi {wifi:?}");
    assert!((bt.h - 17).abs() <= 1 && (bt.w - 12).abs() <= 1, "bt {bt:?}");
    assert!((bt.x - wifi.right() - 10).abs() <= 1, "0.5 of the text between them");
    // the same rects on a list, over a menu, and in the Settings
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    assert_eq!(marks(&mut a), on_dock, "list");
    press(&mut a, Action::A);
    assert_eq!(marks(&mut a), on_dock, "menu");
    press(&mut a, Action::B);
    go_back(&mut a);
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    assert_eq!(marks(&mut a), on_dock, "Settings");
    // a connection that drops takes its icon away (an event only when it changes)
    assert!(a.handle(Ev::Network(true, false)));
    assert!(!a.handle(Ev::Network(true, false)));
    assert_eq!(marks(&mut a).len(), 1);
    assert!(a.handle(Ev::Network(false, false)));
    assert!(marks(&mut a).is_empty());
}

#[test]
fn grid_shows_covers_only_and_the_focused_name_above_the_hints() {
    let c = card("covers-grid", 12, true);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    press(&mut a, Action::Right);
    a.draw(&mut canvas);
    // only the focused game has its name written, once, between the tiles and the hints
    let names: Vec<_> = canvas.texts.iter().filter(|(t, _)| t.starts_with("Game ")).collect();
    assert_eq!(names.len(), 1, "{names:?}");
    assert_eq!(names[0].0, "Game 0001");
    let hint = canvas.texts.iter().find(|(t, _)| t == "Select").unwrap();
    assert!(names[0].1.y < hint.1.y && hint.1.y - names[0].1.y < 60, "{:?} {:?}", names[0].1, hint.1);
    assert!(canvas.has_text("2 / 12"));
    // a tile is a box: portrait, at least as tall as wide
    let tiles: Vec<_> = canvas.fills.iter().filter(|(r, col)| r.y > 40 && r.w > 100 && *col == a.theme.color("tile_bg")).collect();
    assert!(!tiles.is_empty() && tiles.iter().all(|(r, _)| r.h >= r.w), "{tiles:?}");
}

#[test]
fn default_theme_comes_from_the_image_and_cycles() {
    let c = card("theme", 3, false);
    let mut a = app(&c, FakeSystem::default());
    // nothing chosen: the default of themes/base.toml
    assert_eq!(a.settings.theme, "");
    assert_eq!(a.theme.id, "lume");
    assert_eq!(a.set_row_texts(SetRow::Theme).1, "‹Lume ›");
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Theme).unwrap();
    press(&mut a, Action::Right); // into the panel, on the chosen theme
    assert_eq!(a.settings.theme, "", "entering changes nothing");
    press(&mut a, Action::Right);
    assert_eq!(a.settings.theme, "material-dark");
    assert_eq!(a.theme.id, "material-dark");
    assert_eq!(a.set_row_texts(SetRow::Theme).1, "‹Dark ›");
    // the choice is saved and read back
    let b = app(&c, FakeSystem::default());
    assert_eq!(b.theme.id, "material-dark");
}

#[test]
fn search_screen_types_erases_and_closes() {
    let c = card("search", 3, false);
    let mut a = app(&c, FakeSystem::default());
    let mut canvas = FakeCanvas::new(640, 480);
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    press(&mut a, Action::X);
    assert!(a.overlay_open());
    // opens on Q; Z is two rows down; the D-pad stops at the edges
    press(&mut a, Action::Left);
    press(&mut a, Action::Down);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    assert_eq!(a.grid.as_ref().unwrap().filter, "Z");
    assert_eq!(a.grid.as_ref().unwrap().items.len(), 1);
    // the screen shows the typed text, the live count and its own hints
    a.draw(&mut canvas);
    assert!(canvas.has_text("Z"));
    assert!(canvas.has_text("1 games"));
    assert!(canvas.has_text("OK"));
    assert!(!canvas.has_text("Search"), "the grid hints are not drawn under the search");
    // last row: space, backspace, clear, OK
    press(&mut a, Action::Down);
    press(&mut a, Action::Down);
    press(&mut a, Action::Right);
    press(&mut a, Action::A);
    assert_eq!(a.grid.as_ref().unwrap().filter, "");
    assert_eq!(a.grid.as_ref().unwrap().items.len(), 3);
    // the text stops at 24 characters
    press(&mut a, Action::Up);
    for _ in 0..30 {
        press(&mut a, Action::A);
    }
    assert_eq!(a.grid.as_ref().unwrap().filter.chars().count(), 24);
    for _ in 0..24 {
        press(&mut a, Action::Down);
        press(&mut a, Action::A); // backspace (the column stays on it)
        press(&mut a, Action::Up);
    }
    assert_eq!(a.grid.as_ref().unwrap().filter, "");
    // type "S", then B closes the search and keeps the filter, from the first game
    press(&mut a, Action::Up);
    press(&mut a, Action::A);
    assert_eq!(a.grid.as_ref().unwrap().filter, "S");
    press(&mut a, Action::B);
    assert!(!a.overlay_open());
    assert_eq!(a.screen, Screen::Grid);
    let g = a.grid.as_ref().unwrap();
    assert_eq!((g.items.len(), g.focus), (2, 0));
    // then B in the grid clears the filter before leaving the list
    press(&mut a, Action::B);
    assert_eq!(a.grid.as_ref().unwrap().items.len(), 3);
}

/// From a list: the focused game's menu, then its Settings (Start game, Save states,
/// Settings, Favorites).
fn open_game_settings(a: &mut App<FakeSystem>) {
    press(a, Action::A);
    press(a, Action::Down);
    press(a, Action::Down);
    press(a, Action::A);
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
    assert!(launch.contains("system=snes\nrunner=retroarch\ncore=snes9x2005_plus_lume\n"), "{launch}");
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
    open_game_settings(&mut a);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Emulator"));
    assert!(!canvas.has_text("Aspect") && !canvas.has_text("Shader"));
    // a RetroArch game shows both
    go_back(&mut a);
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    open_game_settings(&mut a);
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
    open_game_settings(&mut a); // Emulator first
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
    // Start game, Save states, Settings, Favorites
    for _ in 0..3 {
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
fn settings_adapters_and_language() {
    let c = card("settings", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    assert!(!a.set_rows().contains(&SetRow::Wifi) && !a.set_rows().contains(&SetRow::Bluetooth));
    let b = app(&c, FakeSystem { wifi: true, bluetooth: true, ..Default::default() });
    assert_eq!(&b.set_rows()[..2], [SetRow::Wifi, SetRow::Bluetooth]);

    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    assert_eq!(a.screen, Screen::Settings);
    // Language: ▶ enters the panel, then en -> pt -> es; RetroArch gets user_language 3
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    press(&mut a, Action::Right);
    assert_eq!(a.settings.language, "es");
    let ra = fs::read_to_string(c.root.join("home/.config/retroarch/retroarch.cfg")).unwrap();
    assert_eq!(ra, "user_language = \"3\"\n");
    press(&mut a, Action::B);
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
    press(&mut a, Action::Right);
    press(&mut a, Action::Left);
    assert_eq!(a.sys.vol, 45);
    press(&mut a, Action::B);
    assert_eq!(a.exit, None);
}

#[test]
fn settings_list_ignores_left() {
    let c = card("confirm-nav", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    // in the list, Left does not change the item or enter the panel
    let f = a.settings_focus;
    press(&mut a, Action::Left);
    assert_eq!(a.settings_focus, f);
}

#[test]
fn settings_list_wraps_and_the_panel_takes_half_the_screen() {
    let c = card("setwrap", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    let n = a.set_rows().len();
    assert!(!a.set_rows().iter().any(|r| format!("{r:?}") == "Lite"), "no lite mode");
    // up on the first item goes to the last; down on the last to the first
    press(&mut a, Action::Up);
    assert_eq!(a.settings_focus, n - 1);
    press(&mut a, Action::Down);
    assert_eq!(a.settings_focus, 0);
    // the panel on the right is a little more than half the screen
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let panel = canvas.fills.iter().filter(|(r, col)| *col == a.theme.color("panel_bg") && r.h > 200).map(|(r, _)| *r).next().unwrap();
    assert!(panel.w > 320 && panel.w < 400 && panel.right() >= 600, "{panel:?}");
    // the list keeps to the left of it
    let lang = canvas.texts.iter().find(|(t, r)| t == "Language" && r.x < 100).unwrap().1;
    assert!(lang.right() < panel.x, "{lang:?}");
}

#[test]
fn game_menu_start_states_settings_favorite() {
    let c = card("gamemenu", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    press(&mut a, Action::A);
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    for t in ["Start game", "Save states", "Settings", "Add to favorites"] {
        assert!(canvas.has_text(t), "{t}");
    }
    assert!(!canvas.has_text("Emulator"), "the core is in Settings now");
    // Settings opens core, aspect and shader; B goes back to the game menu
    press(&mut a, Action::Down);
    press(&mut a, Action::Down);
    press(&mut a, Action::A);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Emulator") && canvas.has_text("Aspect") && canvas.has_text("Shader"));
    press(&mut a, Action::B);
    assert!(a.overlay_open());
    a.draw(&mut canvas);
    assert!(canvas.has_text("Start game"));
    // the menu wraps too: up from Start game is Favorites
    press(&mut a, Action::B);
    press(&mut a, Action::A);
    press(&mut a, Action::Up);
    press(&mut a, Action::A);
    assert_eq!(a.lib.favorites().len(), 1);
}

#[test]
fn save_states_show_their_picture() {
    let c = card("statepic", 3, false);
    let mut a = app(&c, FakeSystem::default());
    // two states of the first NES game (by name: Super Mario Bros); one has a picture
    let states = c.root.join("storage/states/nes");
    fs::create_dir_all(&states).unwrap();
    fs::write(states.join("Super Mario Bros.state1"), "x").unwrap();
    fs::write(states.join("Super Mario Bros.state2"), "x").unwrap();
    RgbImage::from_pixel(256, 224, Rgb([200, 30, 30])).save_with_format(states.join("Super Mario Bros.state1.png"), ImageFormat::Png).unwrap();
    go_dock(&mut a, DockItem::System(0));
    press(&mut a, Action::A);
    let first = a.grid.as_ref().unwrap().items.iter().position(|r| a.lib.name(*r) == "Super Mario Bros").unwrap();
    a.grid.as_mut().unwrap().focus = first;
    press(&mut a, Action::A);
    press(&mut a, Action::Down);
    press(&mut a, Action::A); // Save states
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Slot 1") && canvas.has_text("Slot 2"));
    // the panel starts under the header band (53.2), clear of the battery
    let panel = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 500).map(|(r, _)| *r).unwrap();
    assert!((panel.y - 53).abs() <= 1, "{panel:?}");
    let live = canvas.live_textures;
    assert!(live >= 1, "the picture of slot 1 is a texture");
    assert!(!canvas.has_text("No picture"));
    // slot 2 has none: a note, and the previous picture is freed
    press(&mut a, Action::Down);
    a.draw(&mut canvas);
    assert!(canvas.has_text("No picture"));
    assert_eq!(canvas.live_textures, live - 1);
    // the list wraps; B goes back to the game menu on Save states
    press(&mut a, Action::Down);
    a.draw(&mut canvas);
    assert!(!canvas.has_text("No picture"));
    press(&mut a, Action::B);
    a.draw(&mut canvas);
    assert!(canvas.has_text("Start game"));
}

#[test]
fn settings_come_back_with_the_levels_read() {
    let c = card("ramenu", 3, false);
    let mut a = app(&c, FakeSystem::default());
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    a.current_state().save(&a.runtime).unwrap();
    // back from a restart of the launcher: the Settings again, with the volume and brightness
    // read (not "—", seen on the GA36 on 2026-11-14)
    let mut b = app(&c, FakeSystem { vol: 60, bri: 70, ..Default::default() });
    assert_eq!(b.screen, Screen::Settings);
    // the panel of each level shows it
    for (row, text) in [(SetRow::Volume, "60%"), (SetRow::Brightness, "70%")] {
        b.settings_focus = b.set_rows().iter().position(|r| *r == row).unwrap();
        let mut canvas = FakeCanvas::new(640, 480);
        b.draw(&mut canvas);
        assert!(canvas.has_text(text) && !canvas.has_text("—"), "{text}");
    }
}

#[test]
fn volume_keys_show_a_bar_or_the_settings_percent() {
    let c = card("volbar", 3, false);
    let mut a = app(&c, FakeSystem { vol: 50, bri: 80, ..Default::default() });
    let mut canvas = FakeCanvas::new(640, 480);
    // on the Dock: the bar on the right edge, no number, gone after its time
    assert!(a.handle(Ev::Volume(35)));
    a.draw(&mut canvas);
    assert!(!canvas.has_text("35%"));
    // the bar's shapes (the Dock itself runs off both edges on purpose)
    let screen = lume_ui::canvas::Rect::new(0, 0, 640, 480);
    let bar: Vec<_> = canvas.fills.iter().filter(|(r, _)| r.x > 560 && r.h >= 100).collect();
    assert!(!bar.is_empty() && bar.iter().all(|(r, _)| screen.contains(r)), "{bar:?}");
    // the whole right edge: a 5 px track the full height, the level filled from the bottom
    let track = canvas.fills.iter().find(|(r, _)| r.x == 635 && r.h == 480).map(|(r, _)| *r).expect("track");
    assert_eq!((track.w, track.y), (5, 0));
    let level = canvas.fills.iter().find(|(r, col)| r.x == 635 && *col == a.theme.color("accent")).map(|(r, _)| *r).unwrap();
    assert_eq!((level.h, level.bottom()), (480 * 35 / 100, 480));
    // the Dock's icons stop a gap (8 px) before the line
    // (the focused icon may share the accent with the hint circles and the line: the icons
    // are the large shapes of the Dock band)
    let icons: Vec<_> = canvas.fills.iter().filter(|(r, col)| (*col == a.theme.color("icon_bg") || *col == a.theme.color("icon_sel_bg")) && r.w > 40 && r.y < 400 && r.x < 630).map(|(r, _)| *r).collect();
    assert!(!icons.is_empty() && icons.iter().all(|r| r.right() <= 640 - 5 - 8), "{icons:?}");
    // at 100% the line runs the full height
    a.handle(Ev::Volume(100));
    let mut full = FakeCanvas::new(640, 480);
    a.draw(&mut full);
    assert!(full.fills.iter().any(|(r, col)| r.x == 635 && r.h == 480 && *col == a.theme.color("accent")));
    a.handle(Ev::Volume(35));
    // in a list: the bar stays in the right margin, clear of the tiles and their focus ring
    go_dock(&mut a, DockItem::System(1));
    press(&mut a, Action::A);
    for _ in 0..3 {
        press(&mut a, Action::Right); // the focus on the last column
    }
    assert!(a.handle(Ev::Volume(60)));
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    let bar: Vec<_> = canvas.fills.iter().filter(|(r, c)| r.h >= 100 && r.w <= 8 && *c == a.theme.color("accent")).collect();
    let tiles_right = canvas.fills.iter().filter(|(r, _)| r.w > 100 && r.w < 300 && r.h > 100).map(|(r, _)| r.right()).max().unwrap();
    assert!(!bar.is_empty() && bar.iter().all(|(r, _)| r.x >= tiles_right), "{bar:?} vs {tiles_right}");
    go_back(&mut a);
    let wait = a.wait().unwrap();
    assert!(wait <= lume_ui::app::VOLUME_BAR && wait > Duration::from_millis(1000));
    a.volume_bar = a.volume_bar.map(|(v, _)| (v, Instant::now()));
    assert!(a.handle(Ev::Tick));
    assert_eq!(a.volume_bar, None);
    assert_eq!(a.wait(), None);
    // in the Settings: the Volume row changes, no bar
    go_dock(&mut a, DockItem::Settings);
    press(&mut a, Action::A);
    assert!(a.handle(Ev::Volume(100)));
    assert_eq!(a.volume_bar, None);
    a.settings_focus = a.set_rows().iter().position(|r| *r == SetRow::Volume).unwrap();
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    // the Volume panel shows the level, large; no bar on the right edge
    assert!(canvas.has_text("100%"), "the Volume panel shows it");
    assert!(!canvas.fills.iter().any(|(r, col)| r.x > 620 && r.h >= 100 && *col == a.theme.color("accent")), "no volume bar in the Settings");
    // and the next step of the row starts from there
    press(&mut a, Action::A);
    press(&mut a, Action::Left);
    assert_eq!(a.sys.vol, 95);
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

/// A power FIFO for the app to write to, and its reader (non-blocking).
fn power_fifo(c: &Card) -> (PathBuf, fs::File) {
    use std::os::unix::ffi::OsStrExt;
    use std::os::unix::fs::OpenOptionsExt;
    let p = c.root.join("power-fifo");
    let cp = std::ffi::CString::new(p.as_os_str().as_bytes()).unwrap();
    assert_eq!(unsafe { libc::mkfifo(cp.as_ptr(), 0o660) }, 0);
    let rd = fs::OpenOptions::new().read(true).custom_flags(libc::O_NONBLOCK).open(&p).unwrap();
    (p, rd)
}

fn drain(rd: &mut fs::File) -> String {
    use std::io::Read;
    let mut s = String::new();
    let _ = rd.read_to_string(&mut s); // WouldBlock once the pipe is empty
    s
}

#[test]
fn idle_dims_without_saving_and_the_first_button_is_consumed() {
    let c = card("idle", 3, false);
    let (fifo, mut rd) = power_fifo(&c);
    let mut a = app(&c, FakeSystem { bri: 80, ..Default::default() });
    a.power_fifo = fifo;
    // default: 120 s, one wake-up at the end of the timer; the screen itself asks for none
    let d = a.idle_wait().expect("idle timer");
    assert!(d <= Duration::from_secs(120) && d > Duration::from_secs(100), "{d:?}");
    assert_eq!(a.wait(), None);
    // before the time is up a Tick does nothing and draws nothing
    assert!(!a.handle(Ev::Tick));
    assert!(!a.idle && a.sys.bri == 80);
    // the first screen and the return from the idle state tell the service `menu`
    a.announce_menu();
    assert_eq!(drain(&mut rd), "menu\n");
    // time up: dimmed to 10%, `idle` sent, the saved brightness untouched, no more timer
    a.idle_after = Some(Duration::ZERO);
    a.handle(Ev::Tick);
    assert!(a.idle);
    assert_eq!(a.sys.bri, 10);
    assert_eq!(a.sys.saved_bri, None, "the dimming is never saved");
    assert!(!card_settings_written(&c), "no settings file written");
    assert_eq!(drain(&mut rd), "idle\n");
    assert_eq!(a.idle_wait(), None);
    // the first button brings the light back, tells `menu` and does nothing else
    let focus = a.dock_focus;
    assert!(!a.handle(Ev::Input(Action::Right, false)));
    assert_eq!(a.dock_focus, focus, "the button is consumed");
    assert!(!a.idle);
    assert_eq!(a.sys.bri, 80);
    assert_eq!(drain(&mut rd), "menu\n");
    // the next button works, and restarts the timer
    a.idle_after = Some(Duration::from_secs(120));
    press(&mut a, Action::Right);
    assert_ne!(a.dock_focus, focus);
    assert!(a.idle_wait().unwrap() > Duration::from_secs(100));
    // a user brightness below 10% is kept as it is
    a.sys.bri = 4;
    a.idle_after = Some(Duration::ZERO);
    a.handle(Ev::Tick);
    assert_eq!(a.sys.bri, 4);
    // the Fn + volume brightness key is a first button too (the daemon already moved the light)
    a.sys.bri = 15;
    assert!(!a.handle(Ev::Brightness(15)));
    assert!(!a.idle);
    assert_eq!(a.sys.bri, 4, "the user's level is put back");
    assert_eq!(a.brightness_bar, None, "and the key does nothing else");
    let _ = drain(&mut rd);
    // `idle after=0` switches it off
    a.idle_after = None;
    assert_eq!(a.idle_wait(), None);
    a.handle(Ev::Tick);
    assert!(!a.idle);
}

fn card_settings_written(c: &Card) -> bool {
    c.root.join("storage/system/lume/settings.toml").exists()
}

#[test]
fn idle_timeout_comes_from_the_state_then_power_conf_then_120() {
    let d = std::env::temp_dir().join(format!("lume-ui-idlecfg-{}", std::process::id()));
    let _ = fs::remove_dir_all(&d);
    fs::create_dir_all(&d).unwrap();
    let (state, conf) = (d.join("power.state"), d.join("power.conf"));
    assert_eq!(lume_ui::app::idle_config(&state, &conf), (120, 5));
    fs::write(&conf, "idle after=45\nbattery warn=8 critical=3\n").unwrap();
    assert_eq!(lume_ui::app::idle_config(&state, &conf), (45, 8));
    fs::write(&conf, "idle after=0\n").unwrap();
    assert_eq!(lume_ui::app::idle_config(&state, &conf), (0, 5));
    // the service's merged state wins
    fs::write(&state, "idle card after=300\nbattery card warn=10 critical=4\n").unwrap();
    assert_eq!(lume_ui::app::idle_config(&state, &conf), (300, 10));
    let _ = fs::remove_dir_all(&d);
}

#[test]
fn low_battery_warning_once_per_discharge() {
    let c = card("lowbat", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((50, false)), ..Default::default() });
    assert_eq!(a.warn_level, 5);
    let mut canvas = FakeCanvas::new(640, 480);
    a.draw(&mut canvas);
    assert!(!canvas.texts.iter().any(|(t, _)| t.starts_with("Low battery")));
    // above the level: nothing
    a.handle(Ev::Battery(6, false));
    assert_eq!(a.wait(), None, "no toast at 6%");
    // at the level while discharging: the toast, 4 s, with the level
    assert!(a.handle(Ev::Battery(5, false)));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Low battery 5%"), "{:?}", cv.texts);
    let wait = a.wait().expect("toast timer");
    assert!(wait > Duration::from_millis(3500) && wait <= Duration::from_secs(4), "{wait:?}");
    // once: the next readings of the same discharge show nothing new
    a.handle(Ev::Tick);
    assert!(a.handle(Ev::Battery(4, false)), "the level changed: a frame");
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.texts.iter().any(|(t, _)| t == "Low battery 5%"), "still the first toast, not a second one");
    assert!(!cv.texts.iter().any(|(t, _)| t == "Low battery 4%"));
    // charging arms it again; the next discharge at the level warns again
    assert!(a.handle(Ev::Battery(4, true)));
    a.handle(Ev::Battery(4, false));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Low battery 4%"), "{:?}", cv.texts);
    // a level above the limit arms it too
    a.handle(Ev::Battery(30, false));
    a.handle(Ev::Battery(5, false));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    assert!(cv.has_text("Low battery 5%"));
    // the service's level
    let mut b = app(&c, FakeSystem { batt: Some((9, false)), ..Default::default() });
    b.warn_level = 10;
    b.handle(Ev::Battery(9, false));
    let mut cv = FakeCanvas::new(640, 480);
    b.draw(&mut cv);
    assert!(cv.has_text("Low battery 9%"));
    // starting already low shows it from the first frame; charging does not
    let d = app(&c, FakeSystem { batt: Some((3, false)), ..Default::default() });
    assert!(d.wait().is_some());
    let e = app(&c, FakeSystem { batt: Some((3, true)), ..Default::default() });
    assert_eq!(e.wait(), None);
}

#[test]
fn low_battery_texts_in_every_language() {
    let c = card("lowbat-lang", 3, false);
    for (lang, text) in [("pt", "Bateria fraca 5%"), ("es", "Batería baja 5%"), ("en", "Low battery 5%")] {
        let mut a = app(&c, FakeSystem { batt: Some((50, false)), ..Default::default() });
        a.settings.language = lang.into();
        a.texts = lume_ui::i18n::Texts::load(&repo().join("aports/lume-launcher-data/files/usr/share/lume/i18n"), lang);
        a.handle(Ev::Battery(5, false));
        let mut cv = FakeCanvas::new(640, 480);
        a.draw(&mut cv);
        assert!(cv.has_text(text), "{lang}: {:?}", cv.texts);
    }
}

/// The charge mark against the prototype measured at 640x480 (2026-11-17, design-das-telas.md):
/// the bolt 9.5 x 11.5 px at (13.6, 3.4) from the icon's origin, in the text color with a halo
/// in the background color; none when discharging or full; the percent and the icon keep
/// their width. One pixel of rounding allowed.
#[test]
fn charge_mark_matches_the_prototype_ruler() {
    let c = card("bolt", 3, false);
    let mut a = app(&c, FakeSystem { batt: Some((82, true)), ..Default::default() });
    let (fg, bg) = (a.theme.color("fg"), a.theme.color("bg"));
    let mut cv = FakeCanvas::new(640, 480);
    a.draw(&mut cv);
    let body = cv.fills.iter().filter(|(r, col)| *col == fg && r.y < 40 && r.x > 500).map(|(r, _)| *r).max_by_key(|r| r.w * r.h).unwrap();
    let inside = |r: &lume_ui::canvas::Rect| r.x > body.x && r.right() < body.right() && r.y > body.y && r.bottom() < body.bottom();
    let bolt = cv.fills.iter().filter(|(r, col)| *col == fg && inside(r) && r.h > 9 && r.w < 12).map(|(r, _)| *r).next().expect("the bolt");
    // the icon's origin is the body's left edge less 0.2 unit (1 unit = 19.2 * 0.95 / 14 px)
    let u = 19.2 * 0.95 / 14.0;
    let (ox, oy) = (body.x as f32 - 0.2 * u, body.y as f32 - 0.2 * u);
    let near = |a: f32, b: f32| (a - b).abs() <= 1.0;
    assert!(near(bolt.x as f32 - ox, 13.6) && near(bolt.y as f32 - oy, 3.4), "{bolt:?} body {body:?}");
    assert!(near(bolt.w as f32, 9.5) && near(bolt.h as f32, 11.5), "{bolt:?}");
    // the halo: the background color around it, a little larger (1.1 unit stroke)
    let halo = cv.fills.iter().filter(|(r, col)| *col == bg && inside(r) && r.w > bolt.w && r.h > bolt.h && r.w < 14).map(|(r, _)| *r).last().expect("the halo");
    assert!(halo.x < bolt.x && halo.y < bolt.y && halo.right() > bolt.right() && halo.bottom() > bolt.bottom(), "{halo:?} around {bolt:?}");
    assert!(near(halo.w as f32 - bolt.w as f32, 1.1 * u) && near(halo.h as f32 - bolt.h as f32, 1.1 * u), "{halo:?}");
    let pct = cv.texts.iter().find(|(t, _)| t == "82%").unwrap().1;
    // discharging and full: no bolt, and the text and the icon stay where they were
    for charging in [false] {
        a.battery = Some((82, charging));
        let mut cv2 = FakeCanvas::new(640, 480);
        a.draw(&mut cv2);
        assert_eq!(cv2.texts.iter().find(|(t, _)| t == "82%").unwrap().1, pct, "the text does not move");
        let b2 = cv2.fills.iter().filter(|(r, col)| *col == fg && r.y < 40 && r.x > 500).map(|(r, _)| *r).max_by_key(|r| r.w * r.h).unwrap();
        assert_eq!(b2, body, "the icon does not move");
        assert!(!cv2.fills.iter().any(|(r, col)| *col == fg && inside(r) && r.h > 9 && r.w < 12), "no bolt");
    }
    a.battery = Some((100, false));
    let mut cv3 = FakeCanvas::new(640, 480);
    a.draw(&mut cv3);
    assert!(!cv3.fills.iter().any(|(r, col)| *col == fg && r.w < 12 && r.h > 9 && r.y < 40 && r.x > 500 && r.w > 8), "full: no bolt");
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
        // the search screen: every key on screen and no key label cut
        press(&mut a, Action::X);
        a.draw(&mut canvas);
        assert!(canvas.fills.iter().all(|(r, _)| screen.contains(r)), "search {w}x{h}");
        assert!(canvas.clipped.is_empty(), "search {w}x{h}: cut {:?}", canvas.clipped);
        let _ = canvas.size();
    }
}
