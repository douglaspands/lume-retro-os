//! System catalog, schema 3 (docs/CATALOG.md), plus the card extension
//! `ROMS/system/lume/systems.d/*.toml` (lume-launcher D5):
//!
//! ```toml
//! [[system]]              # adds emulators to an existing system
//! id = "snes"
//! emulators = [{ runner = "snes9x-sa" }]
//!
//! [[system]]              # or creates a new one
//! id = "pico8"
//! name = "PICO-8"
//! abbr = "P8"
//! extensions = ["p8", "png"]
//! emulators = [{ runner = "pico8" }]
//! ```
//!
//! The emulator list of a system follows `lume_tool.catalog.emulators()`: the libretro cores
//! (default core of the architecture, then `core` and `alt_cores`), then `emulators` of the
//! image, then the ones of the card. A card file that breaks a rule is refused whole, with one
//! log line, and the image catalog keeps working.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use crate::runner::{Kind, Runner};

/// The libretro runner the core fields expand to.
pub const LIBRETRO_RUNNER: &str = "retroarch";

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Emulator {
    pub runner: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub core: Option<String>,
}

impl Emulator {
    pub fn libretro(core: &str) -> Emulator {
        Emulator { runner: LIBRETRO_RUNNER.into(), core: Some(core.into()) }
    }
}

#[derive(Debug, Clone, Deserialize)]
pub struct Core {
    pub package: String,
    pub file: String,
}

#[derive(Debug, Clone, Deserialize)]
pub struct System {
    pub id: String,
    pub name: String,
    pub abbr: String,
    pub extensions: Vec<String>,
    pub core: Option<String>,
    #[serde(default)]
    pub core_by_arch: BTreeMap<String, String>,
    #[serde(default)]
    pub alt_cores: Vec<String>,
    #[serde(default)]
    pub emulators: Vec<Emulator>,
    #[serde(default)]
    pub romset: Option<String>,
    /// BIOS files of the folder itself (neogeo.zip in roms/neogeo/): not games
    #[serde(skip)]
    pub folder_bios: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct RawBios {
    files: Vec<String>,
}

#[derive(Debug, Deserialize)]
struct RawSystem {
    #[serde(flatten)]
    system: System,
    #[serde(default)]
    bios: Vec<RawBios>,
}

#[derive(Debug, Deserialize)]
struct RawCatalog {
    schema: u32,
    systems: Vec<RawSystem>,
    cores: BTreeMap<String, Core>,
}

#[derive(Debug, Clone)]
pub struct Catalog {
    pub systems: Vec<System>,
    pub cores: BTreeMap<String, Core>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CardSystem {
    id: String,
    name: Option<String>,
    abbr: Option<String>,
    extensions: Option<Vec<String>>,
    #[serde(default)]
    emulators: Vec<Emulator>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CardFile {
    #[serde(default)]
    system: Vec<CardSystem>,
}

fn valid_system_id(id: &str) -> bool {
    !id.is_empty() && id.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit())
}

impl System {
    /// Default libretro core on `arch`.
    pub fn default_core(&self, arch: &str) -> Option<&str> {
        self.core_by_arch.get(arch).or(self.core.as_ref()).map(String::as_str)
    }

    /// Ordered emulators on `arch`; the first one is the default.
    pub fn emulators(&self, arch: &str) -> Vec<Emulator> {
        let mut out: Vec<Emulator> = Vec::new();
        if let Some(default) = self.default_core(arch) {
            let cores = std::iter::once(default)
                .chain(self.core.as_deref())
                .chain(self.alt_cores.iter().map(String::as_str));
            for core in cores {
                let e = Emulator::libretro(core);
                if !out.contains(&e) {
                    out.push(e);
                }
            }
        }
        for e in &self.emulators {
            if !out.contains(e) {
                out.push(e.clone());
            }
        }
        out
    }

    /// Whether a file name is a game of this system (extension in the catalog, not a BIOS of
    /// the folder, not hidden).
    pub fn accepts(&self, file_name: &str) -> bool {
        if file_name.starts_with('.') {
            return false;
        }
        let lower = file_name.to_lowercase();
        if self.folder_bios.contains(&lower) {
            return false;
        }
        match lower.rsplit_once('.') {
            Some((_, ext)) => self.extensions.iter().any(|e| *e == ext),
            None => false,
        }
    }
}

impl Catalog {
    pub fn parse(text: &str) -> Result<Catalog, String> {
        let raw: RawCatalog = serde_json::from_str(text).map_err(|e| e.to_string())?;
        if raw.schema != 3 {
            return Err(format!("catalog schema {} (expected 3)", raw.schema));
        }
        let systems = raw
            .systems
            .into_iter()
            .map(|r| {
                let mut s = r.system;
                // BIOS listed for a system and found in its own folder (neogeo.zip)
                s.folder_bios = r
                    .bios
                    .iter()
                    .flat_map(|b| b.files.iter())
                    .filter(|f| f.ends_with(".zip"))
                    .map(|f| f.to_lowercase())
                    .collect();
                s
            })
            .collect();
        Ok(Catalog { systems, cores: raw.cores })
    }

    pub fn load(path: &Path) -> Result<Catalog, String> {
        let text = std::fs::read_to_string(path).map_err(|e| format!("{}: {e}", path.display()))?;
        Catalog::parse(&text)
    }

    pub fn system(&self, id: &str) -> Option<&System> {
        self.systems.iter().find(|s| s.id == id)
    }

    /// Path of a libretro core: the file of the catalog entry, or `<core>_libretro.so` for a
    /// core cited only by the card.
    pub fn core_path(&self, cores_dir: &Path, core: &str) -> PathBuf {
        match self.cores.get(core) {
            Some(c) => cores_dir.join(&c.file),
            None => cores_dir.join(format!("{core}_libretro.so")),
        }
    }

    fn check_card_emulators(
        &self,
        emulators: &[Emulator],
        runners: &BTreeMap<String, Runner>,
    ) -> Result<(), String> {
        for e in emulators {
            let Some(r) = runners.get(&e.runner) else {
                return Err(format!("runner {} is not installed", e.runner));
            };
            match (r.kind, &e.core) {
                (Kind::Libretro, None) => {
                    return Err(format!("libretro runner {} needs a core", e.runner))
                }
                (Kind::Native, Some(_)) => {
                    return Err(format!("runner {} is not libretro and takes no core", e.runner))
                }
                _ => {}
            }
        }
        Ok(())
    }

    /// Applies one systems.d file; on error nothing of the file is applied.
    pub fn apply_card_text(
        &mut self,
        text: &str,
        runners: &BTreeMap<String, Runner>,
    ) -> Result<(), String> {
        let file: CardFile = toml::from_str(text).map_err(|e| e.message().to_string())?;
        let mut next = self.clone();
        for cs in file.system {
            if !valid_system_id(&cs.id) {
                return Err(format!("system id {:?} must be [a-z0-9]+", cs.id));
            }
            next.check_card_emulators(&cs.emulators, runners)?;
            if let Some(s) = next.systems.iter_mut().find(|s| s.id == cs.id) {
                if cs.name.is_some() || cs.abbr.is_some() || cs.extensions.is_some() {
                    return Err(format!("{}: an existing system only takes emulators", cs.id));
                }
                for e in cs.emulators {
                    if !s.emulators.contains(&e) {
                        s.emulators.push(e);
                    }
                }
                continue;
            }
            let (Some(name), Some(extensions)) = (cs.name, cs.extensions) else {
                return Err(format!("{}: a new system needs name and extensions", cs.id));
            };
            if cs.emulators.is_empty() {
                return Err(format!("{}: a new system needs emulators", cs.id));
            }
            if extensions.is_empty()
                || extensions.iter().any(|e| e.is_empty() || !e.chars().all(|c| c.is_ascii_lowercase() || c.is_ascii_digit()))
            {
                return Err(format!("{}: extensions must be lowercase, without a dot", cs.id));
            }
            let abbr = cs.abbr.unwrap_or_else(|| name.chars().take(5).collect::<String>().to_uppercase());
            if abbr.is_empty() || abbr.chars().count() > 5 {
                return Err(format!("{}: abbr must be 1 to 5 characters", cs.id));
            }
            next.systems.push(System {
                id: cs.id,
                name,
                abbr,
                extensions,
                core: None,
                core_by_arch: BTreeMap::new(),
                alt_cores: Vec::new(),
                emulators: cs.emulators,
                romset: None,
                folder_bios: Vec::new(),
            });
        }
        *self = next;
        Ok(())
    }

    /// Applies every `*.toml` of a systems.d folder, in name order. Returns the refused files.
    pub fn apply_card_dir(
        &mut self,
        dir: &Path,
        runners: &BTreeMap<String, Runner>,
    ) -> Vec<(PathBuf, String)> {
        let mut errors = Vec::new();
        let Ok(entries) = std::fs::read_dir(dir) else { return errors };
        let mut files: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|x| x == "toml"))
            .collect();
        files.sort();
        for f in files {
            let r = std::fs::read_to_string(&f)
                .map_err(|e| e.to_string())
                .and_then(|t| self.apply_card_text(&t, runners));
            if let Err(e) = r {
                errors.push((f, e));
            }
        }
        errors
    }
}

/// The catalog of the image with the runners and systems of the card, logging every refused
/// file. This is what the indexer and the interface use.
pub struct Loaded {
    pub catalog: Catalog,
    pub runners: BTreeMap<String, Runner>,
}

pub fn load_all(prog: &str, check_exec: bool) -> Result<Loaded, String> {
    let mut catalog = Catalog::load(&crate::paths::catalog())?;
    let card = crate::paths::card();
    let (runners, errors) = crate::runner::load(
        &[crate::paths::share().join("runners.d"), card.join("runners.d")],
        check_exec,
    );
    for e in errors {
        crate::log::line(prog, &e.to_string());
    }
    for (file, e) in catalog.apply_card_dir(&card.join("systems.d"), &runners) {
        crate::log::line(prog, &format!("systems file {} refused: {e}", file.display()));
    }
    Ok(Loaded { catalog, runners })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn image_catalog() -> Catalog {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../aports/lume-games/files/usr/share/lume/systems.json");
        Catalog::load(&path).unwrap()
    }

    fn image_runners() -> BTreeMap<String, Runner> {
        let dir = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../aports/lume-games/files/usr/share/lume/runners.d");
        let (runners, errors) = crate::runner::load(&[dir], false);
        assert!(errors.is_empty(), "{errors:?}");
        runners
    }

    #[test]
    fn image_catalog_matches_python_rules() {
        let cat = image_catalog();
        let nes = cat.system("nes").unwrap();
        assert_eq!(nes.emulators("x86_64"), vec![Emulator::libretro("fceumm"), Emulator::libretro("nestopia")]);
        let scd = cat.system("segacd").unwrap();
        assert_eq!(scd.emulators("armv7")[0], Emulator::libretro("picodrive"));
        assert_eq!(scd.emulators("aarch64")[0], Emulator::libretro("genesis_plus_gx"));
        let love = cat.system("love").unwrap();
        assert_eq!(love.emulators("armv7"), vec![Emulator { runner: "love".into(), core: None }]);
        // every runner cited by the image exists
        let runners = image_runners();
        for s in &cat.systems {
            for e in s.emulators("aarch64") {
                assert!(runners.contains_key(&e.runner), "{} {}", s.id, e.runner);
            }
        }
    }

    #[test]
    fn accepts_extensions_and_skips_folder_bios() {
        let cat = image_catalog();
        let neo = cat.system("neogeo").unwrap();
        assert!(neo.accepts("mslug.zip"));
        assert!(!neo.accepts("NEOGEO.ZIP"));
        let nes = cat.system("nes").unwrap();
        assert!(nes.accepts("Game (U).NES"));
        assert!(!nes.accepts("notes.txt"));
        assert!(!nes.accepts("._Game.nes"));
        assert!(!nes.accepts("noext"));
    }

    #[test]
    fn card_adds_emulator_and_new_system() {
        let mut cat = image_catalog();
        let mut runners = image_runners();
        runners.insert(
            "snes9x-sa".into(),
            crate::runner::parse(
                "[runner]\nid = \"snes9x-sa\"\nkind = \"native\"\nexec = [\"/bin/true\", \"{rom}\"]\nquit = \"sigterm\"\ntimeout = 2\n",
                false,
            )
            .unwrap(),
        );
        let text = r#"
[[system]]
id = "snes"
emulators = [{ runner = "snes9x-sa" }, { runner = "retroarch", core = "snes9x" }]

[[system]]
id = "pico8"
name = "PICO-8"
extensions = ["p8"]
emulators = [{ runner = "sh" }]
"#;
        cat.apply_card_text(text, &runners).unwrap();
        let snes = cat.system("snes").unwrap().emulators("aarch64");
        assert_eq!(snes[0], Emulator::libretro("snes9x2005_plus"));
        assert_eq!(snes[1].runner, "snes9x-sa");
        assert_eq!(snes[2], Emulator::libretro("snes9x"));
        assert_eq!(cat.core_path(Path::new("/c"), "snes9x"), PathBuf::from("/c/snes9x_libretro.so"));
        let pico = cat.system("pico8").unwrap();
        assert_eq!(pico.abbr, "PICO-");
        assert!(pico.accepts("cart.p8"));
    }

    #[test]
    fn card_file_with_error_is_refused_whole() {
        let mut cat = image_catalog();
        let runners = image_runners();
        let before = cat.systems.len();
        let text = r#"
[[system]]
id = "gb"
emulators = [{ runner = "sh" }]

[[system]]
id = "x"
name = "X"
extensions = ["x"]
emulators = [{ runner = "missing" }]
"#;
        let err = cat.apply_card_text(text, &runners).unwrap_err();
        assert!(err.contains("missing"));
        assert_eq!(cat.systems.len(), before);
        assert_eq!(cat.system("gb").unwrap().emulators.len(), 0);
        assert!(cat.apply_card_text("[[system]]\nid = \"nes\"\nname = \"N\"\n", &runners).is_err());
        assert!(cat
            .apply_card_text("[[system]]\nid = \"nes\"\nemulators = [{ runner = \"retroarch\" }]\n", &runners)
            .unwrap_err()
            .contains("needs a core"));
    }
}
