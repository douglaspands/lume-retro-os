//! Core of each save state slot (lume-launcher D7, "registro do lume").
//!
//! RetroArch writes `states/<content folder>/<game>.state<N>` with no core in the path or in
//! the file. After each libretro game, lume-run hands the slots that changed to
//! `lume-index --touch ... --core C --slots 3,auto`, which records them here:
//!
//! ```toml
//! # ROMS/system/lume/states/<system>.toml
//! ["Alpha (USA).sfc"]
//! "3" = "snes9x"
//! auto = "snes9x2005_plus"
//! ```
//!
//! The game menu lists the slots of the effective core; slots of another core only count in
//! "N in another core"; a slot with no record (older than the launcher) is listed for any core.

use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};

type Registry = BTreeMap<String, BTreeMap<String, String>>;

fn file(root: &Path, system: &str) -> PathBuf {
    root.join("states").join(format!("{system}.toml"))
}

fn read(root: &Path, system: &str) -> Registry {
    std::fs::read_to_string(file(root, system)).ok().and_then(|t| toml::from_str(&t).ok()).unwrap_or_default()
}

/// Records `core` as the core of `slots` of one game. `root` is `ROMS/system/lume`.
pub fn record(root: &Path, system: &str, path: &str, core: &str, slots: &[&str]) -> io::Result<()> {
    if slots.is_empty() || core.is_empty() {
        return Ok(());
    }
    let mut reg = read(root, system);
    let game = reg.entry(path.to_string()).or_default();
    for s in slots {
        game.insert(s.to_string(), core.to_string());
    }
    crate::atomic::write(&file(root, system), toml::to_string(&reg).expect("registry serializes").as_bytes())
}

/// Recorded core of each slot of one game.
pub fn cores(root: &Path, system: &str, path: &str) -> BTreeMap<String, String> {
    read(root, system).remove(path).unwrap_or_default()
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Slots {
    /// Slots that open with the effective core (recorded for it, or unknown), sorted
    pub usable: Vec<String>,
    /// Slots recorded for another core
    pub other_core: usize,
}

/// Splits the existing `slots` of a game by the effective `core`.
pub fn usable(existing: &[String], recorded: &BTreeMap<String, String>, core: &str) -> Slots {
    let mut usable: Vec<String> = Vec::new();
    let mut other_core = 0;
    for s in existing {
        match recorded.get(s) {
            Some(c) if c != core => other_core += 1,
            _ => usable.push(s.clone()),
        }
    }
    usable.sort_by_key(|s| s.parse::<u32>().unwrap_or(u32::MAX));
    Slots { usable, other_core }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn record_and_split() {
        let root = std::env::temp_dir().join(format!("lume-states-reg-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        record(&root, "snes", "Alpha.sfc", "snes9x", &["1", "2"]).unwrap();
        record(&root, "snes", "Alpha.sfc", "snes9x2005_plus", &["2"]).unwrap();
        let rec = cores(&root, "snes", "Alpha.sfc");
        assert_eq!(rec["1"], "snes9x");
        assert_eq!(rec["2"], "snes9x2005_plus");
        let existing: Vec<String> = ["auto", "1", "2", "5"].iter().map(|s| s.to_string()).collect();
        // spec scenario: 2 states of Snes9x, effective core Snes9x 2010 -> "2 in another core"
        let two_other = usable(&existing[1..2], &rec, "snes9x2005_plus");
        assert_eq!(two_other.other_core, 1);
        let s = usable(&existing, &rec, "snes9x");
        assert_eq!(s.usable, ["1", "5", "auto"]);
        assert_eq!(s.other_core, 1);
        assert!(cores(&root, "snes", "Other.sfc").is_empty());
    }
}
