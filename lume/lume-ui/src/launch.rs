//! The launch request (lume-launcher D1, D7): the interface resolves the 3 layers and the
//! runner, writes the argv for lume-run in $XDG_RUNTIME_DIR/lume/launch and exits with 64.
//!
//! For the RetroArch runner (kind libretro) the options of one run go first, read by the
//! frontend script (frontends/retroarch): `--lume-set aspect_ratio_index=N`, and
//! `--lume-keep state_slot` with `-e N` (RetroArch makes the entry slot the current one).
//! The shader goes as `--set-shader`, which RetroArch never saves.

use std::path::{Path, PathBuf};

use lume_core::catalog::{Catalog, Emulator};
use lume_core::options::Effective;
use lume_core::runner::{Context, Kind, Quit, Runner};

/// Aspect choices (value stored in the options, RetroArch aspect_ratio_index).
pub const ASPECTS: &[(&str, u32)] = &[("4:3", 0), ("16:9", 1), ("square", 21), ("core", 22), ("full", 24)];

pub fn aspect_index(name: &str) -> Option<u32> {
    ASPECTS.iter().find(|(n, _)| *n == name).map(|(_, i)| *i)
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Slot {
    N(u32),
    Auto,
}

pub struct Request {
    pub system: String,
    pub runner: Runner,
    pub core: String,
    pub path: String,
    pub states: String,
    pub argv: Vec<String>,
}

pub struct Dirs {
    pub storage: PathBuf,
    pub cores: PathBuf,
}

impl Dirs {
    pub fn roms(&self) -> PathBuf {
        self.storage.join("roms")
    }

    /// The full path of a gamelist path of a system.
    pub fn rom(&self, system: &str, path: &str) -> PathBuf {
        if path.starts_with('/') {
            PathBuf::from(path)
        } else {
            self.roms().join(system).join(path)
        }
    }

    /// RetroArch state files prefix of a ROM: states/<folder of the content>/<name without
    /// extension> (sort_savestates_by_content_enable, checks of task 1.2).
    pub fn states_prefix(&self, rom: &Path) -> PathBuf {
        let folder = rom.parent().and_then(|p| p.file_name()).map(|f| f.to_string_lossy().into_owned()).unwrap_or_default();
        let stem = rom.file_stem().map(|f| f.to_string_lossy().into_owned()).unwrap_or_default();
        self.storage.join("states").join(folder).join(stem)
    }
}

/// The request for a game with its effective options; `slot` for "Start from save state".
pub fn game(dirs: &Dirs, catalog: &Catalog, runner: &Runner, system: &str, path: &str, eff: &Effective, slot: Option<Slot>) -> Request {
    let rom = dirs.rom(system, path);
    let core = eff.emulator.core.clone().unwrap_or_default();
    let ctx = Context {
        rom: rom.to_string_lossy().into_owned(),
        core: core.clone(),
        core_path: if core.is_empty() { String::new() } else { catalog.core_path(&dirs.cores, &core).to_string_lossy().into_owned() },
        system: system.into(),
        bios_dir: dirs.storage.join("bios").to_string_lossy().into_owned(),
        saves_dir: dirs.storage.join("saves").to_string_lossy().into_owned(),
        states_dir: dirs.storage.join("states").to_string_lossy().into_owned(),
    };
    let mut argv = runner.argv(&ctx);
    let mut states = String::new();
    if runner.kind == Kind::Libretro {
        let mut extra: Vec<String> = Vec::new();
        if let Some(i) = eff.aspect.as_deref().and_then(aspect_index) {
            extra.extend(["--lume-set".into(), format!("aspect_ratio_index={i}")]);
        }
        match &slot {
            Some(Slot::N(_)) => extra.extend(["--lume-keep".into(), "state_slot".into()]),
            Some(Slot::Auto) => extra.extend(["--lume-set".into(), "savestate_auto_load=true".into()]),
            None => {}
        }
        // an empty shader is "None" chosen over a console default
        if let Some(sh) = eff.shader.as_ref().filter(|s| !s.is_empty()) {
            extra.extend(["--set-shader".into(), sh.clone()]);
        }
        if let Some(Slot::N(n)) = &slot {
            extra.extend(["-e".into(), n.to_string()]);
        }
        argv.splice(1..1, extra);
        states = dirs.states_prefix(&rom).to_string_lossy().into_owned();
    }
    Request { system: system.into(), runner: runner.clone(), core, path: path.into(), states, argv }
}

/// The RetroArch menu without a game (Settings > RetroArch, exit code 65).
pub fn retroarch_menu(runner: &Runner) -> Request {
    Request {
        system: "-".into(),
        runner: runner.clone(),
        core: String::new(),
        path: String::new(),
        states: String::new(),
        argv: vec![runner.exec[0].clone()],
    }
}

impl Request {
    /// The launch file in the format of lume-run (launch.rs there).
    pub fn file(&self, menu: bool) -> String {
        let mut s = format!(
            "kind={}\nsystem={}\nrunner={}\ncore={}\nquit={}\ntimeout={}\npath={}\nstates={}\n",
            if menu { "menu" } else { "game" },
            self.system,
            self.runner.id,
            self.core,
            match self.runner.quit {
                Quit::RetroarchCmd => "retroarch-cmd",
                Quit::Sigterm => "sigterm",
            },
            self.runner.timeout,
            self.path,
            self.states
        );
        for a in &self.argv {
            s.push_str(&format!("arg={a}\n"));
        }
        s
    }

    /// Writes the launch file; a value with a line break is refused (it would break the
    /// format), which only a strange file name can cause.
    pub fn write(&self, runtime: &Path, menu: bool) -> std::io::Result<()> {
        let text = self.file(menu);
        if self.argv.iter().chain([&self.path, &self.states]).any(|v| v.contains('\n')) {
            return Err(std::io::Error::new(std::io::ErrorKind::InvalidInput, "line break in a path"));
        }
        lume_core::atomic::write(&runtime.join("launch"), text.as_bytes())
    }
}

pub fn emulator_label(e: &Emulator) -> String {
    match &e.core {
        Some(c) => c.clone(),
        None => e.runner.clone(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use lume_core::options::Source;

    fn setup() -> (Dirs, Catalog, Runner) {
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let cat = Catalog::load(&repo.join("rootfs/overlay/usr/share/r36os/systems.json")).unwrap();
        let (runners, _) = lume_core::runner::load(&[repo.join("rootfs/overlay/usr/share/lume/runners.d")], false);
        (Dirs { storage: "/storage".into(), cores: "/usr/lib/libretro".into() }, cat, runners["retroarch"].clone())
    }

    fn eff(core: &str, aspect: Option<&str>, shader: Option<&str>) -> Effective {
        Effective {
            emulator: Emulator::libretro(core),
            emulator_from: Source::Catalog,
            aspect: aspect.map(Into::into),
            shader: shader.map(Into::into),
            has_game_options: false,
        }
    }

    #[test]
    fn default_game_is_the_plain_runner() {
        let (d, cat, ra) = setup();
        let r = game(&d, &cat, &ra, "snes", "Alpha (USA).sfc", &eff("snes9x2005_plus", None, None), None);
        assert_eq!(r.argv, [
            "/usr/libexec/r36os/frontends/retroarch", "-L",
            "/usr/lib/libretro/snes9x2005_plus_libretro.so", "/storage/roms/snes/Alpha (USA).sfc"]);
        assert_eq!(r.states, "/storage/states/snes/Alpha (USA)");
    }

    #[test]
    fn game_options_and_slot() {
        let (d, cat, ra) = setup();
        let r = game(&d, &cat, &ra, "gba", "sub/G.gba", &eff("gpsp", Some("4:3"), Some("/usr/share/libretro/shaders/lume-shaders/gba/x.glslp")), Some(Slot::N(3)));
        assert_eq!(r.argv, [
            "/usr/libexec/r36os/frontends/retroarch",
            "--lume-set", "aspect_ratio_index=0", "--lume-keep", "state_slot",
            "--set-shader", "/usr/share/libretro/shaders/lume-shaders/gba/x.glslp", "-e", "3",
            "-L", "/usr/lib/libretro/gpsp_libretro.so", "/storage/roms/gba/sub/G.gba"]);
        // RetroArch keeps states per content folder: the subfolder, not the system
        assert_eq!(r.states, "/storage/states/sub/G");
        let auto = game(&d, &cat, &ra, "gba", "G.gba", &eff("gpsp", None, None), Some(Slot::Auto));
        assert!(auto.argv.contains(&"savestate_auto_load=true".to_string()));
    }

    #[test]
    fn launch_file_and_menu() {
        let (d, cat, ra) = setup();
        let r = game(&d, &cat, &ra, "nes", "a.nes", &eff("fceumm", None, None), None);
        let text = r.file(false);
        assert!(text.starts_with("kind=game\nsystem=nes\nrunner=retroarch\ncore=fceumm\nquit=retroarch-cmd\ntimeout=3\npath=a.nes\n"));
        assert!(text.ends_with("arg=/storage/roms/nes/a.nes\n"));
        let m = retroarch_menu(&ra);
        assert!(m.file(true).starts_with("kind=menu\nsystem=-\n"));
        assert_eq!(m.argv, ["/usr/libexec/r36os/frontends/retroarch"]);
        let bad = game(&d, &cat, &ra, "nes", "a\nb.nes", &eff("fceumm", None, None), None);
        assert!(bad.write(&std::env::temp_dir(), false).is_err());
    }
}
