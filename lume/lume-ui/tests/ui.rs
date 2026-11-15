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
    let sel = canvas.fills.iter().filter(|(r, col)| *col == a.theme.color("sel_bg") && r.x < 100).map(|(r, _)| *r).next().unwrap();
    assert!(near(sel.x, 16.0) && near(sel.y, 44.1 + 28.3) && near(sel.w, 255.4) && near(sel.h, 26.7), "focused item {sel:?}");
    let lang = text("Language")[0];
    assert!(near(lang.x, 16.0 + 13.44) && near(lang.y, 44.1 + 3.36) && near(lang.h, 16.8), "item text {lang:?}");
    // the panel
    let panel = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("panel_bg") && r.w > 300).map(|(r, _)| *r).unwrap();
    assert!(near(panel.x, 284.2) && near(panel.y, 44.1) && near(panel.w, 339.8) && near(panel.h, 391.2), "panel {panel:?}");
    let ptitle = text("Theme").into_iter().find(|r| r.x > 280).unwrap();
    assert!(near(ptitle.x, 298.6) && near(ptitle.y, 53.7) && near(ptitle.h, 19.2), "panel title {ptitle:?}");
    // the options: Lume chosen (the default), a pill from 81.6, 23.8 tall
    let chosen = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("sel_bg") && r.x > 280).map(|(r, _)| *r).unwrap();
    assert!(near(chosen.y, 81.6) && near(chosen.h, 23.8) && near(chosen.x, 298.6) && near(chosen.w, 311.0), "chosen {chosen:?}");
    let lume = text("Lume")[0];
    assert!(near(lume.x, 303.4) && near(lume.y, 83.5) && near(lume.h, 16.0), "option {lume:?}");
    let dark = text("Dark")[0];
    assert!(near(dark.y, 83.5 + 23.8), "second option {dark:?}");
    // the note under the three options, 14.4 px
    let note = text("to adjust").into_iter().find(|r| r.x > 280).unwrap();
    assert!(near(note.y, 81.6 + 3.0 * 23.8 + 7.0) && near(note.h, 14.4), "note {note:?}");
    // the hints: ▲▼ Navigate, ◀▶ to adjust, B Back
    let ud = canvas.fills.iter().find(|(r, col)| *col == a.theme.color("nav_bg") && r.y > 440 && r.w > 41).map(|(r, _)| *r).unwrap();
    assert!(near(ud.w, 42.3) && near(ud.y, 449.6), "▲▼ chip {ud:?}");
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
