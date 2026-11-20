//! Emulator, aspect and shader in 3 layers (lume-launcher D6): the game's choice, then the
//! console default, then the catalog default (first emulator, core aspect, no shader).
//!
//! ```text
//! ROMS/system/lume/systems/<id>.toml   console default
//! ROMS/system/lume/games/<id>.toml     per-game exceptions, keyed by the gamelist <path>
//! ```
//!
//! A game keeps only what differs. "Default" removes the field from the game; an empty game
//! entry is removed, and an empty games file is deleted. Every write is atomic.

use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::atomic;
use crate::catalog::{Emulator, System};

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Layer {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub emulator: Option<Emulator>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub aspect: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub shader: Option<String>,
}

impl Layer {
    pub fn is_empty(&self) -> bool {
        self.emulator.is_none() && self.aspect.is_none() && self.shader.is_none()
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Field {
    Emulator,
    Aspect,
    Shader,
}

/// Where an effective value came from.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Source {
    Game,
    Console,
    Catalog,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Effective {
    pub emulator: Emulator,
    pub emulator_from: Source,
    /// `None` is the aspect of the core
    pub aspect: Option<String>,
    /// `None` is no shader
    pub shader: Option<String>,
    /// The game has at least one exception (badge on the grid)
    pub has_game_options: bool,
}

pub struct Options {
    root: PathBuf,
}

fn read_toml<T: for<'de> Deserialize<'de> + Default>(path: &Path) -> T {
    match std::fs::read_to_string(path) {
        Ok(text) => toml::from_str(&text).unwrap_or_else(|e| {
            crate::log::line("lume", &format!("options file {} ignored: {}", path.display(), e.message()));
            T::default()
        }),
        Err(_) => T::default(),
    }
}

impl Options {
    /// `root` is `ROMS/system/lume`.
    pub fn new(root: impl Into<PathBuf>) -> Options {
        Options { root: root.into() }
    }

    fn system_file(&self, id: &str) -> PathBuf {
        self.root.join("systems").join(format!("{id}.toml"))
    }

    fn games_file(&self, id: &str) -> PathBuf {
        self.root.join("games").join(format!("{id}.toml"))
    }

    pub fn system(&self, id: &str) -> Layer {
        read_toml(&self.system_file(id))
    }

    pub fn games(&self, id: &str) -> BTreeMap<String, Layer> {
        read_toml(&self.games_file(id))
    }

    pub fn game(&self, id: &str, path: &str) -> Layer {
        self.games(id).remove(path).unwrap_or_default()
    }

    pub fn set_system(&self, id: &str, layer: &Layer) -> io::Result<()> {
        let file = self.system_file(id);
        if layer.is_empty() {
            return atomic::remove(&file);
        }
        atomic::write(&file, toml::to_string(layer).expect("layer serializes").as_bytes())
    }

    fn write_games(&self, id: &str, games: &BTreeMap<String, Layer>) -> io::Result<()> {
        let file = self.games_file(id);
        if games.is_empty() {
            return atomic::remove(&file);
        }
        atomic::write(&file, toml::to_string(games).expect("games serialize").as_bytes())
    }

    /// Stores the game's layer, keeping only what differs from the console and catalog
    /// defaults (`system`, `arch`).
    pub fn set_game(&self, system: &System, arch: &str, path: &str, layer: Layer) -> io::Result<()> {
        let console = self.system(&system.id);
        let fallback = Self::resolve_layers(system, arch, &console, &Layer::default());
        let mut keep = layer;
        if keep.emulator.as_ref() == Some(&fallback.emulator) {
            keep.emulator = None;
        }
        if keep.aspect == fallback.aspect {
            keep.aspect = None;
        }
        if keep.shader == fallback.shader {
            keep.shader = None;
        }
        let mut games = self.games(&system.id);
        if keep.is_empty() {
            games.remove(path);
        } else {
            games.insert(path.to_string(), keep);
        }
        self.write_games(&system.id, &games)
    }

    /// "Default" on one field of a game: the exception goes away.
    pub fn clear_game_field(&self, id: &str, path: &str, field: Field) -> io::Result<()> {
        let mut games = self.games(id);
        if let Some(layer) = games.get_mut(path) {
            match field {
                Field::Emulator => layer.emulator = None,
                Field::Aspect => layer.aspect = None,
                Field::Shader => layer.shader = None,
            }
            if layer.is_empty() {
                games.remove(path);
            }
        }
        self.write_games(id, &games)
    }

    /// "Clear game options" of a console.
    pub fn clear_games(&self, id: &str) -> io::Result<()> {
        atomic::remove(&self.games_file(id))
    }

    pub fn resolve(&self, system: &System, arch: &str, path: &str) -> Effective {
        Self::resolve_layers(system, arch, &self.system(&system.id), &self.game(&system.id, path))
    }

    /// Game, then console, then catalog. A stored emulator that the system no longer offers
    /// (runner removed from the card) is skipped.
    pub fn resolve_layers(system: &System, arch: &str, console: &Layer, game: &Layer) -> Effective {
        let available = system.emulators(arch);
        let valid = |e: &Option<Emulator>| e.as_ref().filter(|e| available.contains(e)).cloned();
        let (emulator, emulator_from) = match (valid(&game.emulator), valid(&console.emulator)) {
            (Some(e), _) => (e, Source::Game),
            (None, Some(e)) => (e, Source::Console),
            (None, None) => (
                available.first().cloned().unwrap_or_else(|| Emulator { runner: String::new(), core: None }),
                Source::Catalog,
            ),
        };
        Effective {
            emulator,
            emulator_from,
            aspect: game.aspect.clone().or_else(|| console.aspect.clone()),
            shader: game.shader.clone().or_else(|| console.shader.clone()),
            has_game_options: !game.is_empty(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalog::Catalog;

    fn snes() -> System {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../aports/lume-games/files/usr/share/lume/systems.json");
        let mut cat = Catalog::load(&path).unwrap();
        let mut s = cat.systems.remove(cat.systems.iter().position(|s| s.id == "snes").unwrap());
        s.alt_cores = vec!["snes9x".into(), "bsnes".into()];
        s
    }

    fn tmp(name: &str) -> Options {
        let d = std::env::temp_dir().join(format!("lume-options-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        Options::new(d)
    }

    #[test]
    fn game_then_console_then_catalog() {
        let o = tmp("layers");
        let s = snes();
        let e = o.resolve(&s, "aarch64", "./a.sfc");
        assert_eq!(e.emulator, Emulator::libretro("snes9x2005_plus_lume"));
        assert_eq!(e.emulator_from, Source::Catalog);
        assert_eq!((e.aspect, e.shader), (None, None));

        o.set_system("snes", &Layer { emulator: Some(Emulator::libretro("snes9x")), aspect: Some("4:3".into()), shader: None }).unwrap();
        o.set_game(&s, "aarch64", "./b.sfc", Layer { emulator: Some(Emulator::libretro("bsnes")), ..Default::default() }).unwrap();
        // the console default applies to every game without an exception
        let a = o.resolve(&s, "aarch64", "./a.sfc");
        assert_eq!(a.emulator, Emulator::libretro("snes9x"));
        assert_eq!(a.emulator_from, Source::Console);
        assert_eq!(a.aspect.as_deref(), Some("4:3"));
        assert!(!a.has_game_options);
        // that one game keeps its own
        let b = o.resolve(&s, "aarch64", "./b.sfc");
        assert_eq!(b.emulator, Emulator::libretro("bsnes"));
        assert_eq!(b.emulator_from, Source::Game);
        assert_eq!(b.aspect.as_deref(), Some("4:3"));
        assert!(b.has_game_options);
    }

    #[test]
    fn game_keeps_only_what_differs() {
        let o = tmp("differs");
        let s = snes();
        o.set_game(&s, "aarch64", "./a.sfc", Layer { emulator: Some(Emulator::libretro("snes9x2005_plus_lume")), ..Default::default() }).unwrap();
        assert!(o.games("snes").is_empty());
        assert!(!o.games_file("snes").exists());
    }

    #[test]
    fn default_removes_the_exception() {
        let o = tmp("default");
        let s = snes();
        o.set_game(&s, "aarch64", "./a.sfc", Layer { emulator: Some(Emulator::libretro("bsnes")), shader: Some("crt.glslp".into()), ..Default::default() }).unwrap();
        o.clear_game_field("snes", "./a.sfc", Field::Emulator).unwrap();
        assert_eq!(o.game("snes", "./a.sfc"), Layer { shader: Some("crt.glslp".into()), ..Default::default() });
        o.clear_game_field("snes", "./a.sfc", Field::Shader).unwrap();
        // no exception left: the badge goes away and the file is gone
        assert!(!o.resolve(&s, "aarch64", "./a.sfc").has_game_options);
        assert!(!o.games_file("snes").exists());
    }

    #[test]
    fn clear_game_options() {
        let o = tmp("clear");
        let s = snes();
        for p in ["./a.sfc", "./b.sfc"] {
            o.set_game(&s, "aarch64", p, Layer { aspect: Some("16:9".into()), ..Default::default() }).unwrap();
        }
        assert_eq!(o.games("snes").len(), 2);
        o.clear_games("snes").unwrap();
        assert!(o.games("snes").is_empty());
    }

    #[test]
    fn emulator_no_longer_offered_falls_back() {
        let o = tmp("gone");
        let s = snes();
        o.set_system("snes", &Layer { emulator: Some(Emulator { runner: "removed".into(), core: None }), ..Default::default() }).unwrap();
        assert_eq!(o.resolve(&s, "aarch64", "./a.sfc").emulator_from, Source::Catalog);
    }

    #[test]
    fn interrupted_write_keeps_old_games_file() {
        use std::os::unix::fs::PermissionsExt;
        let o = tmp("interrupted");
        let s = snes();
        o.set_game(&s, "aarch64", "./a.sfc", Layer { aspect: Some("4:3".into()), ..Default::default() }).unwrap();
        let dir = o.root.join("games");
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o555)).unwrap();
        let r = o.set_game(&s, "aarch64", "./b.sfc", Layer { aspect: Some("16:9".into()), ..Default::default() });
        std::fs::set_permissions(&dir, std::fs::Permissions::from_mode(0o755)).unwrap();
        if r.is_err() {
            let games = o.games("snes");
            assert_eq!(games.len(), 1);
            assert_eq!(games["./a.sfc"].aspect.as_deref(), Some("4:3"));
        }
    }
}
