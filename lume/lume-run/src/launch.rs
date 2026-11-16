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
//! arg=/usr/libexec/r36os/frontends/retroarch
//! arg=-L
//! ...
//! ```

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
    fn refuses_bad_files() {
        assert!(parse("").is_err());
        assert!(parse("system=x\nrunner=y\n").is_err());
        assert!(parse("system=x\nrunner=y\narg=/bin/true\ntimeout=0\n").is_err());
        assert!(parse("garbage\n").is_err());
        assert!(parse("kind=menu\nsystem=-\nrunner=retroarch\narg=/bin/true\n").unwrap().menu);
    }
}
