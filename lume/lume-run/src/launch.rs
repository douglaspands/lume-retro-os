//! The launch request the interface leaves in `$XDG_RUNTIME_DIR/lume/launch` before exiting
//! with code 64 or 65 (lume-launcher D1). Already resolved: lume-run knows nothing of themes,
//! catalog or options. One `key=value` per line; `arg=` repeats, in argv order.
//!
//! ```text
//! kind=game            game | menu
//! system=snes
//! runner=retroarch
//! core=snes9x          (empty for a native runner)
//! quit=retroarch-cmd   retroarch-cmd | sigterm
//! timeout=3
//! path=Alpha (USA).sfc gamelist key, for lume-index --touch
//! states=/storage/states/snes/Alpha (USA)   state files prefix (libretro), may be empty
//! overlay=retroarch    the runner draws the bar and the hint (lume-hud-actions D3), optional
//! action=pause retroarch-pause                 one line per declared action, optional
//! action=save_state retroarch-cmd:SAVE_STATE
//! env=SDL_VIDEODRIVER=kmsdrm  one line per variable of the runner (game-experience-tuning D5)
//! arg=/usr/libexec/lume/frontends/retroarch
//! arg=-L
//! ...
//! ```

use lume_core::runner::{is_valid_env_name, ActionForm, ACTIONS};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Quit {
    RetroarchCmd,
    Sigterm,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Launch {
    pub menu: bool,
    pub system: String,
    pub runner: String,
    pub core: String,
    pub quit: Quit,
    pub timeout: u32,
    pub path: String,
    pub states: String,
    pub argv: Vec<String>,
    /// the runner draws RetroArch's widgets (the bar, the hint)
    pub overlay: bool,
    /// the runner's actions (D3), in the order of the file
    pub actions: Vec<(String, ActionForm)>,
    /// the runner's environment variables (game-experience-tuning D5), in the order of the file
    pub env: Vec<(String, String)>,
}

impl Launch {
    pub fn action(&self, name: &str) -> Option<&ActionForm> {
        self.actions.iter().find(|(n, _)| n == name).map(|(_, f)| f)
    }
}

pub fn parse(text: &str) -> Result<Launch, String> {
    let mut l = Launch {
        menu: false,
        system: String::new(),
        runner: String::new(),
        core: String::new(),
        quit: Quit::Sigterm,
        timeout: 3,
        path: String::new(),
        states: String::new(),
        argv: Vec::new(),
        overlay: false,
        actions: Vec::new(),
        env: Vec::new(),
    };
    for line in text.lines() {
        if line.is_empty() {
            continue;
        }
        let Some((k, v)) = line.split_once('=') else {
            return Err(format!("bad line {line:?}"));
        };
        match k {
            "kind" => {
                l.menu = match v {
                    "game" => false,
                    "menu" => true,
                    _ => return Err(format!("bad kind {v:?}")),
                }
            }
            "system" => l.system = v.into(),
            "runner" => l.runner = v.into(),
            "core" => l.core = v.into(),
            "quit" => {
                l.quit = match v {
                    "retroarch-cmd" => Quit::RetroarchCmd,
                    "sigterm" => Quit::Sigterm,
                    _ => return Err(format!("bad quit {v:?}")),
                }
            }
            "timeout" => {
                l.timeout = v.parse().ok().filter(|t| (1..=30).contains(t)).ok_or("bad timeout")?
            }
            "path" => l.path = v.into(),
            "states" => l.states = v.into(),
            "arg" => l.argv.push(v.into()),
            "overlay" => {
                l.overlay = match v {
                    "retroarch" => true,
                    "" => false,
                    _ => return Err(format!("bad overlay {v:?}")),
                }
            }
            "action" => {
                let (name, form) = v.split_once(' ').ok_or_else(|| format!("bad action {v:?}"))?;
                // an action this lume-run does not know comes from a newer interface
                if ACTIONS.contains(&name) {
                    l.actions.push((name.into(), ActionForm::parse(name, form)?));
                }
            }
            "env" => {
                let (name, value) = v.split_once('=').ok_or_else(|| format!("bad env {v:?}"))?;
                if !is_valid_env_name(name) {
                    return Err(format!("bad env name {name:?}"));
                }
                l.env.push((name.into(), value.into()));
            }
            // unknown keys come from a newer interface: ignored
            _ => {}
        }
    }
    if l.argv.is_empty() || l.argv[0].is_empty() {
        return Err("no argv".into());
    }
    if l.runner.is_empty() || l.system.is_empty() {
        return Err("runner and system are required".into());
    }
    Ok(l)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_game() {
        let l = parse("kind=game\nsystem=snes\nrunner=retroarch\ncore=snes9x\nquit=retroarch-cmd\ntimeout=4\npath=a b.sfc\narg=/bin/ra\narg=-L\narg=/c/x.so\narg=/r/a b=c.sfc\nnewkey=1\n").unwrap();
        assert!(!l.menu);
        assert_eq!(l.quit, Quit::RetroarchCmd);
        assert_eq!(l.timeout, 4);
        assert_eq!(l.argv, ["/bin/ra", "-L", "/c/x.so", "/r/a b=c.sfc"]);
        assert_eq!(l.path, "a b.sfc");
    }

    #[test]
    fn actions_and_overlay_lines() {
        let base = "kind=game\nsystem=snes\nrunner=retroarch\narg=/bin/ra\n";
        let l = parse(base).unwrap();
        assert!(!l.overlay && l.actions.is_empty());
        let l = parse(&format!(
            "{base}overlay=retroarch\naction=pause retroarch-pause\naction=save_state retroarch-cmd:SAVE_STATE\n\
             action=reset key:KEY_F2\naction=rewind retroarch-cmd:REWIND\n"
        ))
        .unwrap();
        assert!(l.overlay);
        assert_eq!(l.action("pause"), Some(&ActionForm::RetroarchPause));
        assert_eq!(l.action("save_state"), Some(&ActionForm::RetroarchCmd("SAVE_STATE".into())));
        assert_eq!(l.action("reset"), Some(&ActionForm::Key("KEY_F2".into())));
        // an action of a newer interface is skipped
        assert_eq!(l.actions.len(), 3);
        assert!(parse(&format!("{base}action=save_state retroarch-pause\n")).is_err());
        assert!(parse(&format!("{base}action=save_state\n")).is_err());
        assert!(parse(&format!("{base}overlay=sdl\n")).is_err());
    }

    #[test]
    fn env_lines() {
        let base = "kind=game\nsystem=love\nrunner=love\narg=/bin/love\n";
        assert!(parse(base).unwrap().env.is_empty());
        let l = parse(&format!("{base}env=SDL_VIDEODRIVER=kmsdrm\nenv=_X=a=b c\nenv=EMPTY=\n")).unwrap();
        assert_eq!(l.env, [("SDL_VIDEODRIVER".to_string(), "kmsdrm".to_string()), ("_X".into(), "a=b c".into()), ("EMPTY".into(), String::new())]);
        for bad in ["env=NOVALUE", "env=1A=x", "env==x", "env=A B=x"] {
            assert!(parse(&format!("{base}{bad}\n")).is_err(), "{bad}");
        }
    }

    #[test]
    fn refuses_bad_files() {
        assert!(parse("").is_err());
        assert!(parse("system=x\nrunner=y\n").is_err());
        assert!(parse("system=x\nrunner=y\narg=/bin/true\ntimeout=0\n").is_err());
        assert!(parse("garbage\n").is_err());
        assert!(parse("kind=menu\nsystem=-\nrunner=retroarch\narg=/bin/true\n").unwrap().menu);
    }
}
