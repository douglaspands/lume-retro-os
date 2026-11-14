//! lume-index (lume-launcher D4): keeps `roms/<id>/gamelist.xml`, the binary index and the
//! thumbnails of every system in step with the files of `roms/`.
//!
//! - New game: a `<game>` entry with the file name is added to the gamelist.
//! - Existing game: its entry is never rewritten.
//! - Missing game: its entry and images stay; it only leaves the index. Nothing is deleted.
//! - A gamelist with no change is not written, and a system whose input (files, gamelist,
//!   options) did not change since the last index is skipped without reading the XML.

pub mod gamelist;
pub mod index;
pub mod thumbs;

use std::collections::hash_map::DefaultHasher;
use std::collections::HashSet;
use std::fs::File;
use std::hash::{Hash, Hasher};
use std::io;
use std::os::fd::AsRawFd;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

use lume_core::catalog::{Catalog, System};
use lume_core::options::Options;

use gamelist::Gamelist;
use index::{Game, FLAG_FAVORITE, FLAG_OPTIONS, NO_THUMB};
use thumbs::Tile;

pub const PROG: &str = "lume-index";
/// Folders of a system that hold media, never games
pub const MEDIA_DIRS: &[&str] = &["images", "img", "media", "videos", "manuals", "downloaded_images"];
/// Square, so a box (portrait) and a cartridge label (landscape) both keep their shape
pub const DEFAULT_TILE: Tile = Tile { w: 128, h: 128 };

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RomFile {
    /// Relative to the system folder, `/` separators
    pub rel: String,
    pub size: u64,
    pub mtime: i64,
}

/// Every game file of a system folder, recursively, skipping media folders and hidden
/// entries; sorted by path.
pub fn scan(system_dir: &Path, system: &System) -> Vec<RomFile> {
    fn walk(dir: &Path, rel: &str, system: &System, depth: u32, out: &mut Vec<RomFile>) {
        let Ok(entries) = std::fs::read_dir(dir) else { return };
        for e in entries.flatten() {
            let name = e.file_name().to_string_lossy().into_owned();
            if name.starts_with('.') {
                continue;
            }
            let Ok(meta) = e.metadata() else { continue };
            let child_rel = if rel.is_empty() { name.clone() } else { format!("{rel}/{name}") };
            if meta.is_dir() {
                if depth == 0 && MEDIA_DIRS.contains(&name.to_lowercase().as_str()) {
                    continue;
                }
                if depth < 8 {
                    walk(&e.path(), &child_rel, system, depth + 1, out);
                }
            } else if meta.is_file() && system.accepts(&name) {
                out.push(RomFile { rel: child_rel, size: meta.len(), mtime: meta.mtime() });
            }
        }
    }
    let mut out = Vec::new();
    walk(system_dir, "", system, 0, &mut out);
    out.sort_by(|a, b| a.rel.cmp(&b.rel));
    out
}

/// File name without the extension: the name of a new game.
pub fn default_name(rel: &str) -> String {
    let base = rel.rsplit('/').next().unwrap_or(rel);
    match base.rsplit_once('.') {
        Some((stem, _)) if !stem.is_empty() => stem.to_string(),
        _ => base.to_string(),
    }
}

pub struct Ctx {
    pub storage: PathBuf,
    pub catalog: Catalog,
    pub tile: Tile,
}

impl Ctx {
    pub fn roms(&self) -> PathBuf {
        self.storage.join("roms")
    }

    pub fn card(&self) -> PathBuf {
        self.storage.join("system/lume")
    }

    pub fn index_dir(&self) -> PathBuf {
        self.card().join("cache/index")
    }

    pub fn thumbs_dir(&self) -> PathBuf {
        self.card().join("cache/thumbs")
    }

    pub fn index_path(&self, id: &str) -> PathBuf {
        self.index_dir().join(format!("{id}.bin"))
    }

    pub fn gen_path(&self) -> PathBuf {
        self.index_dir().join("GEN")
    }

    /// Exclusive lock of the cache (`cache/lock`), held until the returned file is dropped.
    pub fn lock(&self) -> io::Result<File> {
        let dir = self.card().join("cache");
        std::fs::create_dir_all(&dir)?;
        let f = File::options().create(true).truncate(false).write(true).open(dir.join("lock"))?;
        if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX) } != 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(f)
    }
}

fn meta_key(path: &Path) -> (u64, i64, i64) {
    std::fs::metadata(path).map(|m| (m.len(), m.mtime(), m.mtime_nsec())).unwrap_or((0, 0, 0))
}

fn source_hash(files: &[RomFile], gamelist: &Path, options: &Path, tile: Tile) -> u64 {
    let mut h = DefaultHasher::new();
    files.hash(&mut h);
    meta_key(gamelist).hash(&mut h);
    meta_key(options).hash(&mut h);
    tile.packed().hash(&mut h);
    h.finish()
}

impl Hash for RomFile {
    fn hash<H: Hasher>(&self, h: &mut H) {
        self.rel.hash(h);
        self.size.hash(h);
        self.mtime.hash(h);
    }
}

#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct SystemResult {
    pub games: usize,
    pub added: usize,
    pub skipped: bool,
    pub index_changed: bool,
}

/// Updates one system; `force` reads the gamelist even if the input hash did not change.
pub fn update_system(ctx: &Ctx, system: &System, force: bool) -> Result<SystemResult, String> {
    let dir = ctx.roms().join(&system.id);
    // a system created by the card gets its folder (the image ones come from the boot)
    if !dir.exists() {
        std::fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
    }
    let gl_path = dir.join("gamelist.xml");
    let opt_path = ctx.card().join("games").join(format!("{}.toml", system.id));
    let idx_path = ctx.index_path(&system.id);
    let files = scan(&dir, system);
    let old_index = index::Index::open(&idx_path).ok();
    if !force {
        if let Some(old) = &old_index {
            if old.header.source == source_hash(&files, &gl_path, &opt_path, ctx.tile) {
                return Ok(SystemResult { games: old.len(), skipped: true, ..Default::default() });
            }
        }
    }

    let mut result = SystemResult::default();
    let loaded = Gamelist::load(&gl_path, &dir);
    let mut gl = match loaded {
        Ok(Some(g)) => Some(g),
        Ok(None) => None,
        Err(e) => {
            // a broken gamelist is never overwritten: the games are listed by file name
            lume_core::log::line(PROG, &format!("{}: gamelist unreadable, left untouched: {e}", system.id));
            None
        }
    };
    let broken = gl.is_none() && gl_path.exists();
    let known: HashSet<String> = gl.as_ref().map(|g| g.entries.iter().map(|e| e.key.clone()).collect()).unwrap_or_default();
    let new: Vec<(String, String)> = files
        .iter()
        .filter(|f| !known.contains(&f.rel))
        .map(|f| (f.rel.clone(), default_name(&f.rel)))
        .collect();
    if !new.is_empty() && !broken {
        let base = gl.take().unwrap_or_else(Gamelist::empty);
        let text = base.with_new_games(&new);
        lume_core::atomic::write(&gl_path, text.as_bytes()).map_err(|e| format!("{}: {e}", gl_path.display()))?;
        gl = Some(Gamelist::parse(text, &dir)?);
        result.added = new.len();
    }

    let options = Options::new(ctx.card()).games(&system.id);
    let mut games = Vec::with_capacity(files.len());
    let mut images = Vec::new();
    for f in &files {
        let entry = gl.as_ref().and_then(|g| g.find(&f.rel));
        let field = |n: &str| entry.and_then(|e| e.field(n)).map(str::trim).filter(|v| !v.is_empty());
        let mut flags = 0;
        if field("favorite") == Some("true") {
            flags |= FLAG_FAVORITE;
        }
        if options.contains_key(&f.rel) {
            flags |= FLAG_OPTIONS;
        }
        let image = field("image").map(|i| gamelist::normalize(i, &dir));
        if let Some(i) = &image {
            images.push(i.clone());
        }
        games.push((
            Game {
                name: field("name").map(str::to_string).unwrap_or_else(|| default_name(&f.rel)),
                path: f.rel.clone(),
                flags,
                lastplayed: field("lastplayed").map(gamelist::parse_es_time).unwrap_or(0),
                playcount: field("playcount").and_then(|v| v.parse().ok()).unwrap_or(0),
                thumb: NO_THUMB,
            },
            image,
        ));
    }
    let tdir = ctx.thumbs_dir();
    let built = thumbs::build(&dir, &images, ctx.tile, &tdir.join(format!("{}.bin", system.id)), &tdir.join(format!("{}.keys", system.id)))
        .map_err(|e| format!("thumbnails of {}: {e}", system.id))?;
    let games: Vec<Game> = games
        .into_iter()
        .map(|(mut g, image)| {
            if let Some(slot) = image.and_then(|i| built.slots.get(&i).copied()) {
                g.thumb = slot;
            }
            g
        })
        .collect();
    let bytes = index::encode(&games, source_hash(&files, &gl_path, &opt_path, ctx.tile), ctx.tile.packed());
    let same = std::fs::read(&idx_path).map(|old| old == bytes).unwrap_or(false);
    if !same {
        lume_core::atomic::write(&idx_path, &bytes).map_err(|e| format!("{}: {e}", idx_path.display()))?;
    }
    result.games = games.len();
    // thumbnails moved to other slots also need the interface to reload
    result.index_changed = !same || built.changed;
    Ok(result)
}

/// Scans `ids` (all systems when empty), bumps GEN if an index changed and returns the
/// count per system. `progress` is called before each system.
pub fn update_all(ctx: &Ctx, ids: &[String], force: bool, mut progress: impl FnMut(usize, usize, &str)) -> Vec<(String, Result<SystemResult, String>)> {
    let _lock = ctx.lock();
    let systems: Vec<&System> = ctx.catalog.systems.iter().filter(|s| ids.is_empty() || ids.contains(&s.id)).collect();
    let mut out = Vec::new();
    for (i, s) in systems.iter().enumerate() {
        progress(i, systems.len(), &s.id);
        out.push((s.id.clone(), update_system(ctx, s, force)));
    }
    progress(systems.len(), systems.len(), "");
    if out.iter().any(|(_, r)| matches!(r, Ok(r) if r.index_changed)) {
        if let Err(e) = index::bump_gen(&ctx.gen_path()) {
            lume_core::log::line(PROG, &format!("GEN not written: {e}"));
        }
    }
    out
}

/// Changes fields of one game in its gamelist and refreshes the index of that system.
fn edit_game(ctx: &Ctx, id: &str, path: &str, edit: impl FnOnce(Option<&gamelist::Entry>) -> Vec<(&'static str, String)>) -> Result<(), String> {
    let system = ctx.catalog.system(id).ok_or_else(|| format!("unknown system {id}"))?;
    let _lock = ctx.lock().map_err(|e| e.to_string())?;
    let dir = ctx.roms().join(id);
    let gl_path = dir.join("gamelist.xml");
    let key = gamelist::normalize(path, &dir);
    let mut gl = Gamelist::load(&gl_path, &dir)?.unwrap_or_else(Gamelist::empty);
    if gl.find(&key).is_none() {
        // a game opened before its first scan
        let text = gl.with_new_games(&[(key.clone(), default_name(&key))]);
        gl = Gamelist::parse(text, &dir)?;
    }
    let fields = edit(gl.find(&key));
    let text = gl.with_fields(&key, &fields).expect("entry exists");
    lume_core::atomic::write(&gl_path, text.as_bytes()).map_err(|e| e.to_string())?;
    let r = update_system(ctx, system, true)?;
    if r.index_changed {
        index::bump_gen(&ctx.gen_path()).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// After a game: `playcount` + 1 and `lastplayed` now.
pub fn touch(ctx: &Ctx, id: &str, path: &str, now: u64) -> Result<(), String> {
    edit_game(ctx, id, path, |e| {
        let count = e.and_then(|e| e.field("playcount")).and_then(|v| v.trim().parse::<u32>().ok()).unwrap_or(0);
        vec![("playcount", (count + 1).to_string()), ("lastplayed", gamelist::format_es_time(now))]
    })
}

pub fn set_favorite(ctx: &Ctx, id: &str, path: &str, on: bool) -> Result<(), String> {
    edit_game(ctx, id, path, |_| vec![("favorite", if on { "true" } else { "false" }.to_string())])
}
