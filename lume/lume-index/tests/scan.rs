//! lume-index against a fixture card (tasks 5.1, 5.2 and 5.4 of lume-launcher).

use std::fs;
use std::path::{Path, PathBuf};

use image::{ImageFormat, Rgb, RgbImage};
use lume_core::catalog::Catalog;
use lume_index::gamelist::Gamelist;
use lume_index::index::{Index, FLAG_FAVORITE, NO_THUMB};
use lume_index::{update_all, Ctx, DEFAULT_TILE};

const FIXTURE: &str = include_str!("fixtures/snes-gamelist.xml");

fn card(name: &str) -> Ctx {
    let root = std::env::temp_dir().join(format!("lume-scan-{name}-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    let snes = root.join("roms/snes");
    fs::create_dir_all(snes.join("images")).unwrap();
    fs::write(snes.join("gamelist.xml"), FIXTURE).unwrap();
    fs::write(snes.join("Alpha Quest (USA).sfc"), b"rom-a").unwrap();
    fs::write(snes.join("Beta Racer.smc"), b"rom-b").unwrap();
    RgbImage::from_pixel(20, 20, Rgb([200, 10, 10]))
        .save_with_format(snes.join("images/Alpha Quest (USA)-image.png"), ImageFormat::Png)
        .unwrap();
    // media folders are never games, even with a game extension
    fs::write(snes.join("images/stray.sfc"), b"x").unwrap();
    fs::create_dir_all(snes.join("media")).unwrap();
    fs::write(snes.join("media/other.sfc"), b"x").unwrap();
    fs::write(snes.join(".hidden.sfc"), b"x").unwrap();
    fs::write(snes.join("readme.txt"), b"x").unwrap();
    let catalog = Catalog::load(&Path::new(env!("CARGO_MANIFEST_DIR")).join("../../aports/lume-games/files/usr/share/r36os/systems.json")).unwrap();
    Ctx { storage: root, catalog, tile: DEFAULT_TILE }
}

fn snes_dir(ctx: &Ctx) -> PathBuf {
    ctx.roms().join("snes")
}

fn scan(ctx: &Ctx) {
    for (id, r) in update_all(ctx, &["snes".to_string()], false, |_, _, _| {}) {
        r.unwrap_or_else(|e| panic!("{id}: {e}"));
    }
}

fn index(ctx: &Ctx) -> Index {
    Index::open(&ctx.index_path("snes")).unwrap()
}

#[test]
fn scraper_entries_kept_and_new_game_added() {
    let ctx = card("scraper");
    fs::write(snes_dir(&ctx).join("Gamma (Rev 1).sfc"), b"rom-c").unwrap();
    scan(&ctx);
    let text = fs::read_to_string(snes_dir(&ctx).join("gamelist.xml")).unwrap();
    // the old document is a byte-for-byte prefix up to the last existing entry
    let cut = FIXTURE.rfind("</game>").unwrap() + "</game>".len();
    assert!(text.starts_with(&FIXTURE[..cut]));
    assert!(text.contains("<scraperextra lang=\"xx\">must stay</scraperextra>"));
    let gl = Gamelist::parse(text, &snes_dir(&ctx)).unwrap();
    assert_eq!(gl.find("Gamma (Rev 1).sfc").unwrap().field("name"), Some("Gamma (Rev 1)"));

    let idx = index(&ctx);
    let names: Vec<&str> = (0..idx.len()).map(|i| idx.name(i)).collect();
    assert_eq!(names, ["Alpha Quest", "Beta Racer", "Gamma (Rev 1)"]);
    let beta = idx.game(1);
    assert_eq!(beta.flags & FLAG_FAVORITE, FLAG_FAVORITE);
    assert_eq!(beta.playcount, 7);
    assert!(beta.lastplayed > 0);
    assert_ne!(idx.game(0).thumb, NO_THUMB);
    assert_eq!(idx.game(2).thumb, NO_THUMB);
    // the generation counter tells the interface
    assert_eq!(lume_index::index::read_gen(&ctx.gen_path()), 1);
}

#[test]
fn unchanged_gamelist_is_not_written() {
    let ctx = card("unchanged");
    let gl = snes_dir(&ctx).join("gamelist.xml");
    scan(&ctx);
    let before = fs::metadata(&gl).unwrap().modified().unwrap();
    let gen = lume_index::index::read_gen(&ctx.gen_path());
    std::thread::sleep(std::time::Duration::from_millis(20));
    scan(&ctx);
    // forced pass (reads the XML) also leaves it alone
    for (_, r) in update_all(&ctx, &["snes".to_string()], true, |_, _, _| {}) {
        r.unwrap();
    }
    assert_eq!(fs::metadata(&gl).unwrap().modified().unwrap(), before);
    assert_eq!(fs::read_to_string(&gl).unwrap(), FIXTURE);
    assert_eq!(lume_index::index::read_gen(&ctx.gen_path()), gen);
}

#[test]
fn removed_rom_keeps_metadata_and_comes_back_with_cover() {
    let ctx = card("removed");
    scan(&ctx);
    let rom = snes_dir(&ctx).join("Alpha Quest (USA).sfc");
    fs::remove_file(&rom).unwrap();
    scan(&ctx);
    let idx = index(&ctx);
    assert_eq!(idx.len(), 1);
    assert_eq!(idx.name(0), "Beta Racer");
    // still in the XML, with its image; the image file is still there
    let text = fs::read_to_string(snes_dir(&ctx).join("gamelist.xml")).unwrap();
    assert_eq!(text, FIXTURE);
    assert!(snes_dir(&ctx).join("images/Alpha Quest (USA)-image.png").exists());

    fs::write(&rom, b"rom-a").unwrap();
    scan(&ctx);
    let idx = index(&ctx);
    assert_eq!(idx.len(), 2);
    assert_eq!(idx.name(0), "Alpha Quest");
    assert_ne!(idx.game(0).thumb, NO_THUMB);
}

#[test]
fn truncated_index_is_rebuilt() {
    let ctx = card("truncated");
    scan(&ctx);
    let p = ctx.index_path("snes");
    let bytes = fs::read(&p).unwrap();
    fs::write(&p, &bytes[..bytes.len() / 2]).unwrap();
    assert!(Index::open(&p).is_err());
    scan(&ctx);
    assert_eq!(index(&ctx).len(), 2);
}

#[test]
fn touch_and_favorite() {
    let ctx = card("touch");
    scan(&ctx);
    lume_index::touch(&ctx, "snes", "./Beta Racer.smc", 1_800_000_000).unwrap();
    lume_index::set_favorite(&ctx, "snes", "Alpha Quest (USA).sfc", true).unwrap();
    let gl = Gamelist::load(&snes_dir(&ctx).join("gamelist.xml"), &snes_dir(&ctx)).unwrap().unwrap();
    let beta = gl.find("Beta Racer.smc").unwrap();
    assert_eq!(beta.field("playcount"), Some("8"));
    assert_eq!(beta.field("lastplayed"), Some(lume_index::gamelist::format_es_time(1_800_000_000).as_str()));
    let alpha = gl.find("Alpha Quest (USA).sfc").unwrap();
    assert_eq!(alpha.field("favorite"), Some("true"));
    assert_eq!(alpha.field("scraperextra"), Some("must stay"));
    let idx = index(&ctx);
    assert_eq!(idx.game(0).flags & FLAG_FAVORITE, FLAG_FAVORITE);
    assert_eq!(idx.game(1).playcount, 8);
    assert_eq!(idx.game(1).lastplayed, 1_800_000_000);
    lume_index::set_favorite(&ctx, "snes", "Alpha Quest (USA).sfc", false).unwrap();
    assert_eq!(index(&ctx).game(0).flags & FLAG_FAVORITE, 0);
}

#[test]
fn new_system_without_gamelist() {
    let ctx = card("fresh");
    let nes = ctx.roms().join("nes");
    fs::create_dir_all(nes.join("sub")).unwrap();
    fs::write(nes.join("sub/Zed.NES"), b"x").unwrap();
    for (_, r) in update_all(&ctx, &["nes".to_string(), "psx".to_string()], false, |_, _, _| {}) {
        r.unwrap();
    }
    let gl = Gamelist::load(&nes.join("gamelist.xml"), &nes).unwrap().unwrap();
    assert_eq!(gl.find("sub/Zed.NES").unwrap().field("name"), Some("Zed"));
    assert_eq!(Index::open(&ctx.index_path("psx")).unwrap().len(), 0);
    assert!(!ctx.roms().join("psx/gamelist.xml").exists());
}

#[test]
fn broken_gamelist_is_left_untouched() {
    let ctx = card("broken");
    let gl = snes_dir(&ctx).join("gamelist.xml");
    fs::write(&gl, "<gameList><game><path>./a").unwrap();
    fs::write(snes_dir(&ctx).join("New.sfc"), b"x").unwrap();
    scan(&ctx);
    assert_eq!(fs::read_to_string(&gl).unwrap(), "<gameList><game><path>./a");
    assert_eq!(index(&ctx).len(), 3);
}
