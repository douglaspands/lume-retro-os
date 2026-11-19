//! Runners (lume-launcher D5): one TOML file per way of opening a game.
//!
//! ```toml
//! [runner]
//! id = "retroarch"
//! kind = "libretro"          # libretro shows Aspect and Shader and takes a core
//! exec = ["/usr/libexec/lume/frontends/retroarch", "-L", "{core_path}", "{rom}"]
//! quit = "retroarch-cmd"     # retroarch-cmd | sigterm
//! timeout = 3                # seconds before the forced end
//! overlay = "retroarch"      # optional: draws the status bar and the chord hint
//!
//! [runner.actions]           # optional (lume-hud-actions D3)
//! pause      = "retroarch-pause"            # GET_STATUS + PAUSE_TOGGLE; only for pause
//! app_menu   = "retroarch-cmd:MENU_TOGGLE"  # UDP command to 127.0.0.1:55355
//! reset      = "key:KEY_F2"                 # a key tapped on the virtual device
//! screenshot = "signal:SIGUSR1"             # a signal to the game's process group
//! ```
//!
//! The image brings `/usr/share/lume/runners.d/` and the card `ROMS/system/lume/runners.d/`;
//! with the same id, the card wins. An invalid file is refused with one log line and the
//! other runners keep working. The rules match `lume_tool.catalog.validate_runner()`.

use std::collections::BTreeMap;
use std::fmt;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use serde::Deserialize;

pub const PLACEHOLDERS: &[&str] =
    &["rom", "core", "core_path", "system", "bios_dir", "saves_dir", "states_dir"];

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Kind {
    Libretro,
    Native,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize)]
pub enum Quit {
    #[serde(rename = "retroarch-cmd")]
    RetroarchCmd,
    #[serde(rename = "sigterm")]
    Sigterm,
}

impl Quit {
    pub fn as_str(self) -> &'static str {
        match self {
            Quit::RetroarchCmd => "retroarch-cmd",
            Quit::Sigterm => "sigterm",
        }
    }

    pub fn parse(s: &str) -> Option<Quit> {
        match s {
            "retroarch-cmd" => Some(Quit::RetroarchCmd),
            "sigterm" => Some(Quit::Sigterm),
            _ => None,
        }
    }
}

/// The actions a runner may declare (D3), in the order of the launch file.
pub const ACTIONS: &[&str] = &["pause", "app_menu", "reset", "save_state", "load_state", "screenshot"];

/// The signals a `signal:` action may send.
pub const SIGNALS: &[(&str, i32)] = &[
    ("SIGHUP", libc::SIGHUP),
    ("SIGINT", libc::SIGINT),
    ("SIGQUIT", libc::SIGQUIT),
    ("SIGUSR1", libc::SIGUSR1),
    ("SIGUSR2", libc::SIGUSR2),
    ("SIGTERM", libc::SIGTERM),
    ("SIGSTOP", libc::SIGSTOP),
    ("SIGCONT", libc::SIGCONT),
    ("SIGTSTP", libc::SIGTSTP),
];

/// How a runner carries out one action (D3).
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ActionForm {
    /// A network command of RetroArch (UDP 127.0.0.1:55355), e.g. `SAVE_STATE`
    RetroarchCmd(String),
    /// A keyboard key tapped on the virtual device (`tap KEY_F2` to lume-input)
    Key(String),
    /// A signal to the game's process group
    Signal(String),
    /// Pause through RetroArch: GET_STATUS, then PAUSE_TOGGLE only when PLAYING (D10)
    RetroarchPause,
}

impl ActionForm {
    /// Parses the value of one action; `retroarch-pause` only for `pause`.
    pub fn parse(action: &str, value: &str) -> Result<ActionForm, String> {
        let bad = |why: &str| Err(format!("action {action} = {value:?}: {why}"));
        if value == "retroarch-pause" {
            return if action == "pause" {
                Ok(ActionForm::RetroarchPause)
            } else {
                bad("retroarch-pause is only for pause")
            };
        }
        let Some((form, arg)) = value.split_once(':') else {
            return bad("expected retroarch-cmd:<CMD>, key:<KEY_*> or signal:<NAME>");
        };
        match form {
            "retroarch-cmd" => {
                let ok = arg.split(' ').next().is_some_and(|w| {
                    !w.is_empty() && w.chars().all(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || c == '_')
                }) && arg.chars().all(|c| c.is_ascii_alphanumeric() || c == '_' || c == ' ');
                if ok {
                    Ok(ActionForm::RetroarchCmd(arg.into()))
                } else {
                    bad("the command must be an upper-case RetroArch command")
                }
            }
            "key" if crate::input::is_key_name(arg) => Ok(ActionForm::Key(arg.into())),
            "key" => bad("the key must be a KEY_ code"),
            "signal" if SIGNALS.iter().any(|(n, _)| *n == arg) => Ok(ActionForm::Signal(arg.into())),
            "signal" => bad("unknown signal"),
            _ => bad("expected retroarch-cmd:<CMD>, key:<KEY_*> or signal:<NAME>"),
        }
    }

    /// The text of the value, as in the runner file and the launch file.
    pub fn to_value(&self) -> String {
        match self {
            ActionForm::RetroarchCmd(c) => format!("retroarch-cmd:{c}"),
            ActionForm::Key(k) => format!("key:{k}"),
            ActionForm::Signal(s) => format!("signal:{s}"),
            ActionForm::RetroarchPause => "retroarch-pause".into(),
        }
    }

    /// The number of a `signal:` action's signal.
    pub fn signal_number(name: &str) -> Option<i32> {
        SIGNALS.iter().find(|(n, _)| *n == name).map(|(_, s)| *s)
    }
}

/// The overlays a runner may draw (D3): only RetroArch's widgets in this version.
pub const OVERLAYS: &[&str] = &["retroarch"];

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Runner {
    pub id: String,
    pub kind: Kind,
    pub exec: Vec<String>,
    pub quit: Quit,
    pub timeout: u32,
    /// `retroarch`: the runner draws the status bar and the chord hint
    #[serde(default)]
    pub overlay: Option<String>,
    /// action name -> form, as written in `[runner.actions]`
    #[serde(default)]
    pub actions: BTreeMap<String, String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RunnerFile {
    runner: Runner,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RunnerError {
    pub file: PathBuf,
    pub reason: String,
}

impl fmt::Display for RunnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "runner {} refused: {}", self.file.display(), self.reason)
    }
}

/// Values of the placeholders for one launch.
#[derive(Debug, Clone, Default)]
pub struct Context {
    pub rom: String,
    pub core: String,
    pub core_path: String,
    pub system: String,
    pub bios_dir: String,
    pub saves_dir: String,
    pub states_dir: String,
}

impl Context {
    fn get(&self, name: &str) -> Option<&str> {
        Some(match name {
            "rom" => &self.rom,
            "core" => &self.core,
            "core_path" => &self.core_path,
            "system" => &self.system,
            "bios_dir" => &self.bios_dir,
            "saves_dir" => &self.saves_dir,
            "states_dir" => &self.states_dir,
            _ => return None,
        })
    }
}

fn is_valid_id(id: &str) -> bool {
    let mut chars = id.chars();
    matches!(chars.next(), Some(c) if c.is_ascii_lowercase() || c.is_ascii_digit())
        && chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_' || c == '-')
}

/// The placeholder name of an argument that is exactly `{name}`.
fn placeholder(arg: &str) -> Option<&str> {
    arg.strip_prefix('{')?.strip_suffix('}').filter(|n| !n.contains(['{', '}']))
}

fn is_executable(path: &Path) -> bool {
    std::fs::metadata(path).map(|m| m.is_file() && m.permissions().mode() & 0o111 != 0).unwrap_or(false)
}

impl Runner {
    /// Rule errors; `check_exec` also requires `exec[0]` to be an executable file.
    pub fn validate(&self, check_exec: bool) -> Result<(), String> {
        if !is_valid_id(&self.id) {
            return Err("id must be [a-z0-9_-]+".into());
        }
        if !(1..=30).contains(&self.timeout) {
            return Err("timeout must be 1 to 30 seconds".into());
        }
        let Some(first) = self.exec.first() else {
            return Err("exec is empty".into());
        };
        if self.exec.iter().any(|a| a.is_empty()) {
            return Err("exec has an empty argument".into());
        }
        if !first.starts_with('/') {
            return Err("exec[0] must be an absolute path".into());
        }
        for arg in &self.exec {
            match placeholder(arg) {
                Some(name) if !PLACEHOLDERS.contains(&name) => {
                    return Err(format!("unknown placeholder {{{name}}}"))
                }
                Some(_) => {}
                None if arg.contains(['{', '}']) => {
                    return Err(format!("a placeholder must be a whole argument ({arg:?})"))
                }
                None => {}
            }
        }
        if self.kind == Kind::Libretro
            && !self.exec.iter().any(|a| a == "{core_path}" || a == "{core}")
        {
            return Err("a libretro runner needs {core_path} or {core}".into());
        }
        if check_exec && !is_executable(Path::new(first)) {
            return Err(format!("{first} is not an executable file"));
        }
        if let Some(o) = &self.overlay {
            if !OVERLAYS.contains(&o.as_str()) {
                return Err(format!("unknown overlay {o:?} (only \"retroarch\")"));
            }
        }
        for (name, value) in &self.actions {
            if !ACTIONS.contains(&name.as_str()) {
                return Err(format!("unknown action {name:?}"));
            }
            ActionForm::parse(name, value)?;
        }
        Ok(())
    }

    /// The declared actions, validated, in the order of `ACTIONS`.
    pub fn resolved_actions(&self) -> Vec<(&'static str, ActionForm)> {
        ACTIONS
            .iter()
            .filter_map(|a| {
                let v = self.actions.get(*a)?;
                ActionForm::parse(a, v).ok().map(|f| (*a, f))
            })
            .collect()
    }

    /// The argv of one launch: each placeholder becomes one whole argument (no shell), so a
    /// ROM named `My Game (Rev 1).zip` is a single argument.
    pub fn argv(&self, ctx: &Context) -> Vec<String> {
        self.exec
            .iter()
            .map(|a| match placeholder(a).and_then(|n| ctx.get(n)) {
                Some(v) => v.to_string(),
                None => a.clone(),
            })
            .collect()
    }
}

/// Parses one runner file.
pub fn parse(text: &str, check_exec: bool) -> Result<Runner, String> {
    let file: RunnerFile = toml::from_str(text).map_err(|e| e.message().to_string())?;
    file.runner.validate(check_exec)?;
    Ok(file.runner)
}

/// Loads the runners of the given folders, in order: a later folder (the card) replaces a
/// runner with the same id. Invalid files are returned as errors, never fatal.
pub fn load(dirs: &[PathBuf], check_exec: bool) -> (BTreeMap<String, Runner>, Vec<RunnerError>) {
    let mut runners = BTreeMap::new();
    let mut errors = Vec::new();
    for dir in dirs {
        let Ok(entries) = std::fs::read_dir(dir) else { continue };
        let mut files: Vec<PathBuf> = entries
            .filter_map(|e| e.ok().map(|e| e.path()))
            .filter(|p| p.extension().is_some_and(|x| x == "toml"))
            .collect();
        files.sort();
        for file in files {
            let parsed = std::fs::read_to_string(&file)
                .map_err(|e| e.to_string())
                .and_then(|t| parse(&t, check_exec));
            match parsed {
                Ok(r) => {
                    runners.insert(r.id.clone(), r);
                }
                Err(reason) => errors.push(RunnerError { file, reason }),
            }
        }
    }
    (runners, errors)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    const SH: &str = r#"
[runner]
id = "sh"
kind = "native"
exec = ["/bin/sh", "{rom}"]
quit = "sigterm"
timeout = 3
"#;

    fn tmpdir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-runner-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn rom_with_spaces_is_one_argument() {
        let r = parse(SH, true).unwrap();
        let ctx = Context { rom: "/storage/roms/ports/My Game (Rev 1).sh".into(), ..Default::default() };
        assert_eq!(r.argv(&ctx), vec!["/bin/sh", "/storage/roms/ports/My Game (Rev 1).sh"]);
    }

    #[test]
    fn libretro_argv() {
        let r = parse(
            r#"[runner]
id = "retroarch"
kind = "libretro"
exec = ["/bin/sh", "-L", "{core_path}", "{rom}"]
quit = "retroarch-cmd"
timeout = 3"#,
            true,
        )
        .unwrap();
        let ctx = Context {
            rom: "/r/a b.sfc".into(),
            core_path: "/usr/lib/libretro/snes9x_libretro.so".into(),
            ..Default::default()
        };
        assert_eq!(r.argv(&ctx), ["/bin/sh", "-L", "/usr/lib/libretro/snes9x_libretro.so", "/r/a b.sfc"]);
        assert_eq!(r.quit, Quit::RetroarchCmd);
    }

    #[test]
    fn refused_runners() {
        let unknown = SH.replace("{rom}", "{game}");
        assert!(parse(&unknown, false).unwrap_err().contains("unknown placeholder"));
        let empty = SH.replace(r#"["/bin/sh", "{rom}"]"#, "[]");
        assert!(parse(&empty, false).unwrap_err().contains("exec is empty"));
        let missing = SH.replace("/bin/sh", "/nonexistent/emu");
        assert!(parse(&missing, true).unwrap_err().contains("not an executable"));
        assert!(parse(&missing, false).is_ok());
        let partial = SH.replace(r#""{rom}""#, r#""--rom={rom}""#);
        assert!(parse(&partial, false).unwrap_err().contains("whole argument"));
        let no_cmd = SH.replace("exec = [\"/bin/sh\", \"{rom}\"]\n", "");
        assert!(parse(&no_cmd, false).unwrap_err().contains("exec"));
        let extra = SH.replace("timeout = 3", "timeout = 3\nshell = true");
        assert!(parse(&extra, false).is_err());
        let relative = SH.replace("/bin/sh", "sh");
        assert!(parse(&relative, false).unwrap_err().contains("absolute"));
    }

    #[test]
    fn runner_without_actions_is_valid() {
        let r = parse(SH, true).unwrap();
        assert!(r.actions.is_empty() && r.overlay.is_none());
        assert!(r.resolved_actions().is_empty());
    }

    #[test]
    fn actions_and_overlay() {
        let text = format!(
            "{SH}overlay = \"retroarch\"\n\n[runner.actions]\npause = \"retroarch-pause\"\n\
             app_menu = \"retroarch-cmd:MENU_TOGGLE\"\nreset = \"key:KEY_F2\"\n\
             screenshot = \"signal:SIGUSR1\"\nsave_state = \"retroarch-cmd:SAVE_STATE\"\n"
        );
        let r = parse(&text, true).unwrap();
        assert_eq!(r.overlay.as_deref(), Some("retroarch"));
        assert_eq!(
            r.resolved_actions(),
            [
                ("pause", ActionForm::RetroarchPause),
                ("app_menu", ActionForm::RetroarchCmd("MENU_TOGGLE".into())),
                ("reset", ActionForm::Key("KEY_F2".into())),
                ("save_state", ActionForm::RetroarchCmd("SAVE_STATE".into())),
                ("screenshot", ActionForm::Signal("SIGUSR1".into())),
            ]
        );
        for (_, f) in r.resolved_actions() {
            let v = f.to_value();
            assert_eq!(ActionForm::parse("pause", &v).unwrap(), f);
        }
        assert_eq!(ActionForm::signal_number("SIGUSR1"), Some(libc::SIGUSR1));
    }

    #[test]
    fn bad_actions_are_refused_with_the_reason() {
        let with = |extra: &str| format!("{SH}\n[runner.actions]\n{extra}\n");
        let e = parse(&with("save_state = \"retroarch-pause\""), false).unwrap_err();
        assert!(e.contains("only for pause"), "{e}");
        let e = parse(&with("save_state = \"telnet:SAVE\""), false).unwrap_err();
        assert!(e.contains("action save_state"), "{e}");
        let e = parse(&with("save_state = \"retroarch-cmd:save state\""), false).unwrap_err();
        assert!(e.contains("upper-case"), "{e}");
        let e = parse(&with("reset = \"key:BTN_A\""), false).unwrap_err();
        assert!(e.contains("KEY_"), "{e}");
        let e = parse(&with("reset = \"signal:SIGKILL\""), false).unwrap_err();
        assert!(e.contains("unknown signal"), "{e}");
        let e = parse(&with("rewind = \"retroarch-cmd:REWIND\""), false).unwrap_err();
        assert!(e.contains("unknown action"), "{e}");
        let e = parse(&format!("{SH}overlay = \"sdl\"\n"), false).unwrap_err();
        assert!(e.contains("unknown overlay"), "{e}");
    }

    #[test]
    fn the_user_guide_example_is_accepted() {
        // docs/LAUNCHER.md (task 7.8): the runner example of the guide parses and builds argv
        let doc = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("../../docs/LAUNCHER.md")).unwrap();
        let block = doc.split("<!-- runner-example -->").nth(1).unwrap();
        let toml = block.split("```toml").nth(1).unwrap().split("```").next().unwrap();
        let r = parse(toml, false).unwrap();
        assert_eq!(r.id, "meu-emulador");
        let ctx = Context { rom: "/storage/roms/snes/A B.sfc".into(), ..Default::default() };
        assert_eq!(r.argv(&ctx).last().unwrap(), "/storage/roms/snes/A B.sfc");
    }

    #[test]
    fn card_wins_and_bad_file_is_skipped() {
        let image = tmpdir("image");
        let card = tmpdir("card");
        fs::write(image.join("sh.toml"), SH).unwrap();
        fs::write(card.join("sh.toml"), SH.replace("timeout = 3", "timeout = 9")).unwrap();
        fs::write(card.join("broken.toml"), "[runner]\nid = \"broken\"\n").unwrap();
        fs::write(card.join("notes.txt"), "ignored").unwrap();
        let (runners, errors) = load(&[image, card.clone()], true);
        assert_eq!(runners.len(), 1);
        assert_eq!(runners["sh"].timeout, 9);
        assert_eq!(errors.len(), 1);
        assert_eq!(errors[0].file, card.join("broken.toml"));
        assert!(errors[0].to_string().starts_with("runner "));
    }
}
