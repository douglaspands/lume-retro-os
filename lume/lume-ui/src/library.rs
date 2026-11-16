//! What the interface shows, read from the files lume-index keeps (lume-launcher D4): one
//! binary index per system and its thumbnails, both mapped read-only. Systems without games
//! are left out; Favorites and Recent gather games of every system. Nothing here parses XML
//! or decodes images.

use std::os::fd::AsRawFd;
use std::path::{Path, PathBuf};

use lume_core::catalog::Catalog;
use lume_index::index::{Game, Index, FLAG_FAVORITE, FLAG_OPTIONS, NO_THUMB};
use lume_index::thumbs;

/// A read-only mapping of a whole file.
pub struct Mapped {
    ptr: *const u8,
    len: usize,
}

impl Mapped {
    pub fn open(path: &Path) -> Option<Mapped> {
        let f = std::fs::File::open(path).ok()?;
        let len = f.metadata().ok()?.len() as usize;
        if len == 0 {
            return None;
        }
        let p = unsafe { libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ, libc::MAP_PRIVATE, f.as_raw_fd(), 0) };
        (p != libc::MAP_FAILED).then_some(Mapped { ptr: p as *const u8, len })
    }

    pub fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.ptr, self.len) }
    }
}

impl Drop for Mapped {
    fn drop(&mut self) {
        unsafe { libc::munmap(self.ptr as *mut libc::c_void, self.len) };
    }
}

pub struct SysList {
    pub id: String,
    pub name: String,
    pub abbr: String,
    pub index: Index,
    pub thumbs: Option<Mapped>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct GameRef {
    pub sys: usize,
    pub i: usize,
}

pub struct Library {
    pub systems: Vec<SysList>,
    pub gen: u64,
    cache: PathBuf,
}

impl Library {
    /// `card` is ROMS/system/lume; the systems keep the catalog order.
    pub fn load(card: &Path, catalog: &Catalog) -> Library {
        let cache = card.join("cache");
        let gen = lume_index::index::read_gen(&cache.join("index/GEN"));
        let mut systems = Vec::new();
        for s in &catalog.systems {
            let Ok(index) = Index::open(&cache.join(format!("index/{}.bin", s.id))) else { continue };
            if index.is_empty() {
                continue;
            }
            let thumbs = Mapped::open(&cache.join(format!("thumbs/{}.bin", s.id)));
            systems.push(SysList { id: s.id.clone(), name: s.name.clone(), abbr: s.abbr.clone(), index, thumbs });
        }
        Library { systems, gen, cache }
    }

    pub fn changed(&self) -> bool {
        lume_index::index::read_gen(&self.cache.join("index/GEN")) != self.gen
    }

    pub fn system_index(&self, id: &str) -> Option<usize> {
        self.systems.iter().position(|s| s.id == id)
    }

    pub fn games_of(&self, sys: usize) -> Vec<GameRef> {
        (0..self.systems[sys].index.len()).map(|i| GameRef { sys, i }).collect()
    }

    pub fn name(&self, r: GameRef) -> &str {
        self.systems[r.sys].index.name(r.i)
    }

    pub fn path(&self, r: GameRef) -> &str {
        self.systems[r.sys].index.path(r.i)
    }

    pub fn game(&self, r: GameRef) -> Game {
        self.systems[r.sys].index.game(r.i)
    }

    pub fn is_favorite(&self, r: GameRef) -> bool {
        self.systems[r.sys].index.field(r.i, 0) & FLAG_FAVORITE != 0
    }

    pub fn has_options(&self, r: GameRef) -> bool {
        self.systems[r.sys].index.field(r.i, 0) & FLAG_OPTIONS != 0
    }

    /// Favorites of every system, sorted by name.
    pub fn favorites(&self) -> Vec<GameRef> {
        let mut out: Vec<GameRef> = (0..self.systems.len())
            .flat_map(|s| self.games_of(s))
            .filter(|r| self.is_favorite(*r))
            .collect();
        out.sort_by_cached_key(|r| lume_core::text::fold(self.name(*r)));
        out
    }

    /// The games played, newest first.
    pub fn recents(&self, max: usize) -> Vec<GameRef> {
        let mut out: Vec<(u32, GameRef)> = (0..self.systems.len())
            .flat_map(|s| self.games_of(s))
            .map(|r| (self.systems[r.sys].index.field(r.i, 1), r))
            .filter(|(t, _)| *t > 0)
            .collect();
        out.sort_by_key(|r| std::cmp::Reverse(r.0));
        out.into_iter().take(max).map(|(_, r)| r).collect()
    }

    /// The RGB565 thumbnail of a game, if it has one.
    pub fn thumb(&self, r: GameRef) -> Option<thumbs::Slot<'_>> {
        let slot = self.systems[r.sys].index.field(r.i, 3);
        if slot == NO_THUMB {
            return None;
        }
        thumbs::read_slot(self.systems[r.sys].thumbs.as_ref()?.bytes(), slot)
    }

    /// Finds a game by system id and gamelist path (the launcher state after a game).
    pub fn find(&self, sys: &str, path: &str) -> Option<GameRef> {
        let s = self.system_index(sys)?;
        (0..self.systems[s].index.len()).find(|&i| self.systems[s].index.path(i) == path).map(|i| GameRef { sys: s, i })
    }
}
