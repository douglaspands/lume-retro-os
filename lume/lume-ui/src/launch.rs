//! The launch request (lume-launcher D1, D7): the interface resolves the 3 layers and the
//! runner, writes the argv for lume-run in $XDG_RUNTIME_DIR/lume/launch and exits with 64.
//!
//! For the RetroArch runner (kind libretro) the options of one run go first, read by the
//! frontend script (frontends/retroarch): `--lume-set aspect_ratio_index=N` (always),
//! `auto_overrides_enable=false` and `auto_shaders_enable=false` (the launcher's choices
//! win over what was saved in RetroArch), and `--lume-keep state_slot` with `-e N`
//! (RetroArch makes the entry slot the current one). The shader goes as `--set-shader`,
//! which RetroArch never saves, with `video_shader_enable=true`.

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

/// The picture RetroArch saves next to a state (savestate_thumbnail_enable): the state
/// file plus ".png" (`<game>.state3.png`, `<game>.state.png` for slot 0,
/// `<game>.state.auto.png`).
pub fn state_picture(prefix: &Path, slot: &str) -> PathBuf {
    let base = prefix.file_name().map(|b| b.to_string_lossy().into_owned()).unwrap_or_default();
    let name = match slot {
        "auto" => format!("{base}.state.auto.png"),
        "0" => format!("{base}.state.png"),
        n => format!("{base}.state{n}.png"),
    };
    prefix.with_file_name(name)
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
        // the launcher's choices win on every run (user's request, 2026-11-15): the aspect
        // always (the core's when none is chosen), and for this run neither RetroArch's
        // core/game overrides (loaded after the config, they would set another aspect) nor
        // its automatic shader presets (they would load a shader saved in RetroArch's menu)
        let aspect = eff.aspect.as_deref().and_then(aspect_index).or_else(|| aspect_index("core")).unwrap_or(22);
        let set = |k: &str| ["--lume-set".to_string(), k.to_string()];
        extra.extend(set(&format!("aspect_ratio_index={aspect}")));
        extra.extend(set("auto_overrides_enable=false"));
        extra.extend(set("auto_shaders_enable=false"));
        if eff.shader.as_ref().is_some_and(|s| !s.is_empty()) {
            // --set-shader only works with shaders on
            extra.extend(set("video_shader_enable=true"));
        }
        // the quick slot of Fn+R1/Fn+L1 (lume-hud-actions D4): the entry slot when opened
        // from a slot, slot 0 otherwise, whatever slot was last chosen in RetroArch's menu
        match &slot {
            Some(Slot::N(_)) => extra.extend(["--lume-keep".into(), "state_slot".into()]),
            Some(Slot::Auto) => {
                extra.extend(set("savestate_auto_load=true"));
                extra.extend(set("state_slot=0"));
            }
            None => extra.extend(set("state_slot=0")),
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
        // lume-hud-actions D3: what the runner draws and how it carries out each action
        // (a lume-run that does not know these keys ignores them)
        if let Some(o) = &self.runner.overlay {
            s.push_str(&format!("overlay={o}\n"));
        }
        for (name, form) in self.runner.resolved_actions() {
            s.push_str(&format!("action={name} {}\n", form.to_value()));
        }
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
        let cat = Catalog::load(&repo.join("aports/lume-games/files/usr/share/lume/systems.json")).unwrap();
        let (runners, _) = lume_core::runner::load(&[repo.join("aports/lume-games/files/usr/share/lume/runners.d")], false);
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
    fn state_pictures_follow_retroarch_names() {
        let p = std::path::Path::new("/storage/states/snes/Alpha (USA)");
        assert_eq!(state_picture(p, "3"), PathBuf::from("/storage/states/snes/Alpha (USA).state3.png"));
        assert_eq!(state_picture(p, "0"), PathBuf::from("/storage/states/snes/Alpha (USA).state.png"));
        assert_eq!(state_picture(p, "auto"), PathBuf::from("/storage/states/snes/Alpha (USA).state.auto.png"));
    }

    #[test]
    fn default_game_is_the_plain_runner() {
        let (d, cat, ra) = setup();
        let r = game(&d, &cat, &ra, "snes", "Alpha (USA).sfc", &eff("snes9x2005_plus", None, None), None);
        // even with nothing chosen, the run says the core's aspect and ignores what was saved
        // in RetroArch (overrides, automatic shader presets)
        assert_eq!(r.argv, [
            "/usr/libexec/lume/frontends/retroarch",
            "--lume-set", "aspect_ratio_index=22", "--lume-set", "auto_overrides_enable=false",
            "--lume-set", "auto_shaders_enable=false", "--lume-set", "state_slot=0", "-L",
            "/usr/lib/libretro/snes9x2005_plus_libretro.so", "/storage/roms/snes/Alpha (USA).sfc"]);
        assert_eq!(r.states, "/storage/states/snes/Alpha (USA)");
    }

    #[test]
    fn game_options_and_slot() {
        let (d, cat, ra) = setup();
        let r = game(&d, &cat, &ra, "gba", "sub/G.gba", &eff("gpsp", Some("4:3"), Some("/usr/share/libretro/shaders/lume-shaders/gba/x.glslp")), Some(Slot::N(3)));
        assert_eq!(r.argv, [
            "/usr/libexec/lume/frontends/retroarch",
            "--lume-set", "aspect_ratio_index=0", "--lume-set", "auto_overrides_enable=false",
            "--lume-set", "auto_shaders_enable=false", "--lume-set", "video_shader_enable=true",
            "--lume-keep", "state_slot", "--set-shader", "/usr/share/libretro/shaders/lume-shaders/gba/x.glslp", "-e", "3",
            "-L", "/usr/lib/libretro/gpsp_libretro.so", "/storage/roms/gba/sub/G.gba"]);
        // RetroArch keeps states per content folder: the subfolder, not the system
        assert_eq!(r.states, "/storage/states/sub/G");
        // opened from slot 3, the quick slot is 3: no state_slot=0
        assert!(!r.argv.contains(&"state_slot=0".to_string()));
        let auto = game(&d, &cat, &ra, "gba", "G.gba", &eff("gpsp", None, None), Some(Slot::Auto));
        assert!(auto.argv.contains(&"savestate_auto_load=true".to_string()));
        assert!(auto.argv.contains(&"state_slot=0".to_string()));
    }

    #[test]
    fn launch_file_carries_the_actions_and_the_overlay() {
        let (d, cat, ra) = setup();
        let text = game(&d, &cat, &ra, "nes", "a.nes", &eff("fceumm", None, None), None).file(false);
        for line in ["overlay=retroarch", "action=pause retroarch-pause", "action=app_menu retroarch-cmd:MENU_TOGGLE",
                     "action=reset retroarch-cmd:RESET", "action=save_state retroarch-cmd:SAVE_STATE",
                     "action=load_state retroarch-cmd:LOAD_STATE", "action=screenshot retroarch-cmd:SCREENSHOT"] {
            assert!(text.lines().any(|l| l == line), "{line}");
        }
        // a native runner declares nothing
        let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
        let (runners, _) = lume_core::runner::load(&[repo.join("aports/lume-games/files/usr/share/lume/runners.d")], false);
        let sh = Request { system: "ports".into(), runner: runners["sh"].clone(), core: String::new(),
                           path: "x.sh".into(), states: String::new(), argv: vec!["/bin/sh".into()] };
        assert!(!sh.file(false).contains("action=") && !sh.file(false).contains("overlay="));
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
        assert_eq!(m.argv, ["/usr/libexec/lume/frontends/retroarch"]);
        let bad = game(&d, &cat, &ra, "nes", "a\nb.nes", &eff("fceumm", None, None), None);
        assert!(bad.write(&std::env::temp_dir(), false).is_err());
    }
}
