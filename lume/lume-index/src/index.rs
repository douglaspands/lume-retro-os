//! Binary index of one system (lume-launcher D4): `ROMS/system/lume/cache/index/<id>.bin`.
//!
//! ```text
//! header (32 bytes, little endian)
//!   0  magic   "LUMEIDX1"
//!   8  count   u32   games
//!  12  strings u32   size of the string table
//!  16  source  u64   hash of the scan input (files, gamelist mtime and size)
//!  24  thumbs  u32   tile size of the thumbnails (w << 16 | h), 0 if none
//!  28  rsv     u32
//! records (count x 32 bytes), sorted by name for the grid
//!   name_off u32, name_len u32, path_off u32, path_len u32,
//!   flags u32 (1 favorite, 2 own options), lastplayed u32 (unix s), playcount u32,
//!   thumb u32 (slot in thumbs/<id>.bin, u32::MAX for none)
//! strings (UTF-8)
//! ```
//!
//! The interface maps the file read-only and reads the records in place, without parsing.
//! A file whose sizes do not add up is refused (and rebuilt by the next scan).
//! `cache/index/GEN` holds a counter bumped after every index change; the interface watches
//! it with inotify.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::path::Path;

pub const MAGIC: &[u8; 8] = b"LUMEIDX1";
pub const HEADER: usize = 32;
pub const RECORD: usize = 32;
pub const NO_THUMB: u32 = u32::MAX;
pub const FLAG_FAVORITE: u32 = 1;
pub const FLAG_OPTIONS: u32 = 2;

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Game {
    pub name: String,
    /// Path relative to the system folder (the gamelist key)
    pub path: String,
    pub flags: u32,
    pub lastplayed: u32,
    pub playcount: u32,
    pub thumb: u32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Header {
    pub count: u32,
    pub strings: u32,
    pub source: u64,
    pub thumbs: u32,
}

fn u32_at(b: &[u8], at: usize) -> u32 {
    u32::from_le_bytes(b[at..at + 4].try_into().unwrap())
}

fn u64_at(b: &[u8], at: usize) -> u64 {
    u64::from_le_bytes(b[at..at + 8].try_into().unwrap())
}

/// Sort key of the grid: case and accents ignored.
pub fn sort_key(name: &str) -> String {
    lume_core::text::fold(name)
}

pub fn encode(games: &[Game], source: u64, thumbs: u32) -> Vec<u8> {
    let mut sorted: Vec<&Game> = games.iter().collect();
    sorted.sort_by_cached_key(|g| (sort_key(&g.name), g.path.clone()));
    let mut strings = Vec::new();
    let mut records = Vec::with_capacity(sorted.len() * RECORD);
    for g in sorted {
        let name_off = strings.len() as u32;
        strings.extend_from_slice(g.name.as_bytes());
        let path_off = strings.len() as u32;
        strings.extend_from_slice(g.path.as_bytes());
        for v in [name_off, g.name.len() as u32, path_off, g.path.len() as u32, g.flags, g.lastplayed, g.playcount, g.thumb] {
            records.extend_from_slice(&v.to_le_bytes());
        }
    }
    let mut out = Vec::with_capacity(HEADER + records.len() + strings.len());
    out.extend_from_slice(MAGIC);
    out.extend_from_slice(&((records.len() / RECORD) as u32).to_le_bytes());
    out.extend_from_slice(&(strings.len() as u32).to_le_bytes());
    out.extend_from_slice(&source.to_le_bytes());
    out.extend_from_slice(&thumbs.to_le_bytes());
    out.extend_from_slice(&0u32.to_le_bytes());
    out.extend_from_slice(&records);
    out.extend_from_slice(&strings);
    out
}

/// Checks the header and the sizes; every string range must be inside the table.
pub fn check(b: &[u8]) -> Result<Header, String> {
    if b.len() < HEADER || &b[..8] != MAGIC {
        return Err("not an index file".into());
    }
    let h = Header { count: u32_at(b, 8), strings: u32_at(b, 12), source: u64_at(b, 16), thumbs: u32_at(b, 24) };
    let expected = HEADER as u64 + h.count as u64 * RECORD as u64 + h.strings as u64;
    if b.len() as u64 != expected {
        return Err(format!("size {} does not match the header ({expected})", b.len()));
    }
    let strings_at = HEADER + h.count as usize * RECORD;
    for i in 0..h.count as usize {
        let r = HEADER + i * RECORD;
        for (off, len) in [(u32_at(b, r), u32_at(b, r + 4)), (u32_at(b, r + 8), u32_at(b, r + 12))] {
            let end = off as u64 + len as u64;
            if end > h.strings as u64 || std::str::from_utf8(&b[strings_at + off as usize..strings_at + end as usize]).is_err() {
                return Err(format!("record {i} has a bad string"));
            }
        }
    }
    Ok(h)
}

/// A checked index, either mapped from a file or owned (tests).
pub struct Index {
    data: Mapping,
    pub header: Header,
}

enum Mapping {
    Mapped(*const u8, usize),
    Owned(Vec<u8>),
}

// The mapping is read-only and private to this value
unsafe impl Send for Mapping {}

impl Drop for Mapping {
    fn drop(&mut self) {
        if let Mapping::Mapped(p, len) = *self {
            if len > 0 {
                unsafe { libc::munmap(p as *mut libc::c_void, len) };
            }
        }
    }
}

impl Index {
    fn bytes(&self) -> &[u8] {
        match &self.data {
            Mapping::Mapped(p, len) => {
                if *len == 0 {
                    &[]
                } else {
                    unsafe { std::slice::from_raw_parts(*p, *len) }
                }
            }
            Mapping::Owned(v) => v,
        }
    }

    pub fn from_vec(v: Vec<u8>) -> Result<Index, String> {
        let header = check(&v)?;
        Ok(Index { data: Mapping::Owned(v), header })
    }

    /// Maps the file read-only and checks it.
    pub fn open(path: &Path) -> Result<Index, String> {
        let f = File::open(path).map_err(|e| format!("{}: {e}", path.display()))?;
        let len = f.metadata().map_err(|e| e.to_string())?.len() as usize;
        if len < HEADER {
            return Err("not an index file".into());
        }
        let p = unsafe { libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ, libc::MAP_PRIVATE, f.as_raw_fd(), 0) };
        if p == libc::MAP_FAILED {
            return Err(io::Error::last_os_error().to_string());
        }
        let data = Mapping::Mapped(p as *const u8, len);
        let header = {
            let b = unsafe { std::slice::from_raw_parts(p as *const u8, len) };
            check(b)?
        };
        Ok(Index { data, header })
    }

    pub fn len(&self) -> usize {
        self.header.count as usize
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    fn string(&self, off: u32, len: u32) -> &str {
        let at = HEADER + self.len() * RECORD + off as usize;
        std::str::from_utf8(&self.bytes()[at..at + len as usize]).unwrap_or("")
    }

    pub fn name(&self, i: usize) -> &str {
        let r = HEADER + i * RECORD;
        let b = self.bytes();
        self.string(u32_at(b, r), u32_at(b, r + 4))
    }

    pub fn path(&self, i: usize) -> &str {
        let r = HEADER + i * RECORD;
        let b = self.bytes();
        self.string(u32_at(b, r + 8), u32_at(b, r + 12))
    }

    pub fn field(&self, i: usize, n: usize) -> u32 {
        u32_at(self.bytes(), HEADER + i * RECORD + 16 + n * 4)
    }

    pub fn game(&self, i: usize) -> Game {
        Game {
            name: self.name(i).into(),
            path: self.path(i).into(),
            flags: self.field(i, 0),
            lastplayed: self.field(i, 1),
            playcount: self.field(i, 2),
            thumb: self.field(i, 3),
        }
    }

    pub fn games(&self) -> Vec<Game> {
        (0..self.len()).map(|i| self.game(i)).collect()
    }
}

/// Reads the generation counter (0 if missing).
pub fn read_gen(path: &Path) -> u64 {
    std::fs::read_to_string(path).ok().and_then(|t| t.trim().parse().ok()).unwrap_or(0)
}

/// Bumps the generation counter atomically.
pub fn bump_gen(path: &Path) -> io::Result<u64> {
    let next = read_gen(path).wrapping_add(1);
    lume_core::atomic::write(path, format!("{next}\n").as_bytes())?;
    Ok(next)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> Vec<Game> {
        vec![
            Game { name: "Zeta".into(), path: "z.sfc".into(), thumb: NO_THUMB, ..Default::default() },
            Game { name: "Ábaco".into(), path: "sub/a b.sfc".into(), flags: FLAG_FAVORITE, lastplayed: 1_700_000_000, playcount: 4, thumb: 0 },
        ]
    }

    #[test]
    fn round_trip_sorted_by_name() {
        let idx = Index::from_vec(encode(&sample(), 42, (128 << 16) | 96)).unwrap();
        assert_eq!(idx.header.source, 42);
        assert_eq!(idx.len(), 2);
        assert_eq!(idx.name(0), "Ábaco");
        assert_eq!(idx.path(0), "sub/a b.sfc");
        assert_eq!(idx.game(0).playcount, 4);
        assert_eq!(idx.game(1).thumb, NO_THUMB);
    }

    #[test]
    fn mapped_file_and_truncation() {
        let dir = std::env::temp_dir().join(format!("lume-index-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let p = dir.join("snes.bin");
        let bytes = encode(&sample(), 1, 0);
        std::fs::write(&p, &bytes).unwrap();
        let idx = Index::open(&p).unwrap();
        assert_eq!(idx.games(), Index::from_vec(bytes.clone()).unwrap().games());
        std::fs::write(&p, &bytes[..bytes.len() - 3]).unwrap();
        assert!(Index::open(&p).is_err());
        let mut bad = bytes.clone();
        bad[HEADER..HEADER + 4].copy_from_slice(&9999u32.to_le_bytes());
        assert!(Index::from_vec(bad).is_err());
        assert!(Index::from_vec(Vec::new()).is_err());
    }

    #[test]
    fn generation_counter() {
        let p = std::env::temp_dir().join(format!("lume-gen-{}", std::process::id()));
        let _ = std::fs::remove_file(&p);
        assert_eq!(read_gen(&p), 0);
        assert_eq!(bump_gen(&p).unwrap(), 1);
        assert_eq!(bump_gen(&p).unwrap(), 2);
    }
}
