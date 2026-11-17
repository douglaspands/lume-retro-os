//! Editor of `ROMS/system/lume/power.conf` for the settings screen (openspec game-governor,
//! D16, P-85). It parses the file into raw lines, replaces or appends ONE setting, validates it
//! against the state the service publishes (`powerstate`) and writes atomically. Comments,
//! order, blank lines and lines it does not know stay byte for byte.

use crate::powerstate::PowerState;
use std::io::Write;
use std::path::Path;

/// One setting the screen may change (the grammar of docs/LOGS.md, "power.conf").
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Setting {
    Profile { name: String, params: Vec<(String, String)> },
    Class { system: String, profile: String },
    Core { core: String, profile: String },
    Battery { warn: u32, critical: u32 },
    Idle { after: u32 },
    Enabled(bool),
}

#[derive(Debug, PartialEq, Eq)]
pub enum ConfError {
    /// A name or value that cannot be written as one token of a line.
    BadToken(String),
    UnknownKey(String),
    NotANumber(String),
    /// A value the console does not accept (clock outside the table, governor, cores...).
    OutOfState(String),
    /// A game profile with a `min` (or `max`) below the console's game floor.
    BelowFloor { min: u32, floor: u32 },
    /// The class or core points to a profile the service does not know.
    UnknownProfile(String),
    /// The service has not published its state, so nothing can be validated.
    NoState,
}

impl Setting {
    /// The line key that identifies the setting (the one a new value replaces).
    fn key(&self) -> String {
        match self {
            Setting::Profile { name, .. } => format!("profile {name}"),
            Setting::Class { system, .. } => format!("class {system}"),
            Setting::Core { core, .. } => format!("core {core}"),
            Setting::Battery { .. } => "battery".into(),
            Setting::Idle { .. } => "idle".into(),
            Setting::Enabled(_) => "enabled".into(),
        }
    }

    fn line(&self) -> String {
        match self {
            Setting::Profile { name, params } => {
                let mut l = format!("profile {name}");
                for (k, v) in params {
                    l.push_str(&format!(" {k}={v}"));
                }
                l
            }
            Setting::Class { system, profile } => format!("class {system} {profile}"),
            Setting::Core { core, profile } => format!("core {core} {profile}"),
            Setting::Battery { warn, critical } => format!("battery warn={warn} critical={critical}"),
            Setting::Idle { after } => format!("idle after={after}"),
            Setting::Enabled(on) => format!("enabled {}", if *on { 1 } else { 0 }),
        }
    }
}

fn token_ok(s: &str) -> bool {
    !s.is_empty() && !s.chars().any(|c| c.is_whitespace() || c == '#' || c == '=' || c.is_control())
}

fn num<T: std::str::FromStr>(k: &str, v: &str) -> Result<T, ConfError> {
    v.parse().map_err(|_| ConfError::NotANumber(format!("{k}={v}")))
}

/// Validates a setting against the published state (same rules as the shell validator).
pub fn validate(setting: &Setting, st: &PowerState) -> Result<(), ConfError> {
    match setting {
        Setting::Profile { name, params } => {
            if !token_ok(name) {
                return Err(ConfError::BadToken(name.clone()));
            }
            let (mut min, mut max) = (None, None);
            for (k, v) in params {
                if !token_ok(k) || !token_ok(v) {
                    return Err(ConfError::BadToken(format!("{k}={v}")));
                }
                match k.as_str() {
                    "governor" => {
                        if !st.cpu_governors.iter().any(|g| g == v) {
                            return Err(ConfError::OutOfState(format!("governor {v}")));
                        }
                    }
                    "min" | "max" => {
                        let khz: u32 = num(k, v)?;
                        if !st.cpu_freqs.is_empty() && !st.cpu_freqs.contains(&khz) {
                            return Err(ConfError::OutOfState(format!("{k}={v}")));
                        }
                        if k == "min" { min = Some(khz) } else { max = Some(khz) }
                    }
                    "cores" => {
                        let n: u32 = num(k, v)?;
                        if n < 1 || n > st.cpu_cores {
                            return Err(ConfError::OutOfState(format!("cores={v}")));
                        }
                    }
                    "gpu_max" => {
                        let hz: u64 = num(k, v)?;
                        if !st.gpu_freqs.contains(&hz) {
                            return Err(ConfError::OutOfState(format!("gpu_max={v}")));
                        }
                    }
                    "up_threshold" | "sampling_down_factor" | "rate_limit_us" => {
                        let _: u32 = num(k, v)?;
                    }
                    "controller" => {
                        if v != "load" {
                            return Err(ConfError::OutOfState(format!("controller={v}")));
                        }
                    }
                    _ => return Err(ConfError::UnknownKey(k.clone())),
                }
            }
            if let Some(floor) = st.game_min {
                if st.is_game_profile(name) {
                    if let Some(m) = min.filter(|m| *m < floor) {
                        return Err(ConfError::BelowFloor { min: m, floor });
                    }
                    if let Some(m) = max.filter(|m| *m < floor) {
                        return Err(ConfError::BelowFloor { min: m, floor });
                    }
                }
            }
            if let (Some(a), Some(b)) = (min, max) {
                if a > b {
                    return Err(ConfError::OutOfState(format!("min {a} above max {b}")));
                }
            }
            Ok(())
        }
        Setting::Class { system: n, profile } | Setting::Core { core: n, profile } => {
            if !token_ok(n) {
                return Err(ConfError::BadToken(n.clone()));
            }
            let p = st.profile(profile).ok_or_else(|| ConfError::UnknownProfile(profile.clone()))?;
            // a class/core target is a game profile: its floor must hold (the service adds a
            // missing `min`, so only an explicit lower one can break it)
            if let (Some(floor), Some(m)) = (st.game_min, p.get("min").and_then(|m| m.parse::<u32>().ok())) {
                if m < floor {
                    return Err(ConfError::BelowFloor { min: m, floor });
                }
            }
            Ok(())
        }
        Setting::Battery { warn, critical } => {
            if *warn > 100 || critical > warn {
                return Err(ConfError::OutOfState(format!("battery warn={warn} critical={critical}")));
            }
            Ok(())
        }
        Setting::Idle { .. } | Setting::Enabled(_) => Ok(()),
    }
}

/// The file as raw lines; `to_text` gives back exactly what `parse` got.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PowerConf {
    /// Split on `\n`: a file ending in a newline ends with an empty element.
    lines: Vec<String>,
}

impl PowerConf {
    pub fn parse(text: &str) -> PowerConf {
        PowerConf { lines: text.split('\n').map(String::from).collect() }
    }

    pub fn to_text(&self) -> String {
        self.lines.join("\n")
    }

    /// Reads the file; a missing file is an empty configuration.
    pub fn load(path: &Path) -> std::io::Result<PowerConf> {
        match std::fs::read(path) {
            Ok(b) => Ok(PowerConf::parse(&String::from_utf8_lossy(&b))),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(PowerConf::parse("")),
            Err(e) => Err(e),
        }
    }

    /// The value of `key` on the last `<kind>` line of the file (`idle after=N`,
    /// `battery warn=N critical=N`), `None` when the line or the value is missing.
    fn value(&self, kind: &str, key: &str) -> Option<u32> {
        let line = self.lines.iter().rev().find(|l| Self::line_key(l).as_deref() == Some(kind))?;
        let code = line.split('#').next().unwrap_or("");
        code.split_whitespace().find_map(|w| w.strip_prefix(key)?.strip_prefix('=')?.parse().ok())
    }

    /// Seconds of the `idle after=` line (`0` switches the idle state off).
    pub fn idle_after(&self) -> Option<u32> {
        self.value("idle", "after")
    }

    /// Percent of the `battery warn=` line.
    pub fn battery_warn(&self) -> Option<u32> {
        self.value("battery", "warn")
    }

    /// Key of a raw line (`profile x`, `class x`, `battery`...), `None` for comments, blanks
    /// and anything that is not a setting line.
    fn line_key(line: &str) -> Option<String> {
        let code = line.split('#').next().unwrap_or("");
        let mut w = code.split_whitespace();
        let kind = w.next()?;
        match kind {
            "profile" | "class" | "core" => Some(format!("{kind} {}", w.next()?)),
            "battery" | "idle" | "enabled" => Some(kind.to_string()),
            _ => None,
        }
    }

    /// Validates, then replaces the line with the same key (keeping its trailing comment) or
    /// appends a new line at the end. Nothing changes on error.
    pub fn set(&mut self, setting: &Setting, state: Option<&PowerState>) -> Result<(), ConfError> {
        validate(setting, state.ok_or(ConfError::NoState)?)?;
        let key = setting.key();
        let new = setting.line();
        if let Some(i) = self.lines.iter().position(|l| Self::line_key(l).as_deref() == Some(key.as_str())) {
            let old = &self.lines[i];
            let comment = old.find('#').map(|p| {
                let before = &old[..p];
                let ws = before.len() - before.trim_end().len();
                old[p - ws..].to_string()
            });
            self.lines[i] = match comment {
                Some(c) => format!("{new}{}{}", if c.starts_with(char::is_whitespace) { "" } else { " " }, c),
                None => new,
            };
        } else if self.lines.last().is_some_and(|l| l.is_empty()) {
            let at = self.lines.len() - 1;
            self.lines.insert(at, new);
        } else {
            // no final newline (or an empty file): keep the file shape and end it with one
            self.lines.push(new);
            self.lines.push(String::new());
        }
        Ok(())
    }

    /// Atomic write: a temporary file in the same directory, `fsync`, `rename`, `fsync` of the
    /// directory. A power cut leaves the old file or the new one, never half of it.
    pub fn save(&self, path: &Path) -> std::io::Result<()> {
        let dir = path.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or_else(|| Path::new("."));
        let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| "power.conf".into());
        let tmp = dir.join(format!(".{name}.tmp{}", std::process::id()));
        let res = (|| {
            let mut f = std::fs::OpenOptions::new().write(true).create(true).truncate(true).open(&tmp)?;
            if let Ok(meta) = std::fs::metadata(path) {
                let _ = f.set_permissions(meta.permissions());
            }
            f.write_all(self.to_text().as_bytes())?;
            f.sync_all()?;
            drop(f);
            std::fs::rename(&tmp, path)
        })();
        if res.is_err() {
            let _ = std::fs::remove_file(&tmp);
            return res;
        }
        if let Ok(d) = std::fs::File::open(dir) {
            let _ = d.sync_all();
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::powerstate::SAMPLE;

    const FILE: &str = "# my tuning\n\nprofile heavy governor=performance cores=4 # keep\nclass snes heavy\nfuture_line x y\nidle after=300\n";

    fn st() -> PowerState {
        PowerState::parse(SAMPLE)
    }

    fn tmpdir(name: &str) -> std::path::PathBuf {
        let d = std::env::temp_dir().join(format!("lume-powerconf-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(&d).unwrap();
        d
    }

    #[test]
    fn round_trip_is_identical() {
        for t in [FILE, "", "no newline at end", "a\r\nb\r\n", "\n\n", "# only a comment\n"] {
            assert_eq!(PowerConf::parse(t).to_text(), t);
        }
    }

    #[test]
    fn replace_keeps_comments_order_and_unknown_lines() {
        let mut c = PowerConf::parse(FILE);
        let s = Setting::Profile { name: "heavy".into(), params: vec![("governor".into(), "schedutil".into()), ("min".into(), "1008000".into()), ("cores".into(), "4".into())] };
        c.set(&s, Some(&st())).unwrap();
        assert_eq!(
            c.to_text(),
            "# my tuning\n\nprofile heavy governor=schedutil min=1008000 cores=4 # keep\nclass snes heavy\nfuture_line x y\nidle after=300\n"
        );
    }

    #[test]
    fn new_setting_is_appended_before_the_final_newline() {
        let mut c = PowerConf::parse(FILE);
        c.set(&Setting::Enabled(false), Some(&st())).unwrap();
        assert!(c.to_text().ends_with("idle after=300\nenabled 0\n"));
        let mut d = PowerConf::parse("# x");
        d.set(&Setting::Idle { after: 60 }, Some(&st())).unwrap();
        assert_eq!(d.to_text(), "# x\nidle after=60\n");
    }

    #[test]
    fn values_outside_the_state_are_refused_and_nothing_changes() {
        let mut c = PowerConf::parse(FILE);
        let bad = |k: &str, v: &str| Setting::Profile { name: "p".into(), params: vec![(k.into(), v.into())] };
        assert!(matches!(c.set(&bad("min", "700000"), Some(&st())), Err(ConfError::OutOfState(_))));
        assert!(matches!(c.set(&bad("governor", "conservative"), Some(&st())), Err(ConfError::OutOfState(_))));
        assert!(matches!(c.set(&bad("cores", "5"), Some(&st())), Err(ConfError::OutOfState(_))));
        assert!(matches!(c.set(&bad("cores", "0"), Some(&st())), Err(ConfError::OutOfState(_))));
        assert!(matches!(c.set(&bad("gpu_max", "1"), Some(&st())), Err(ConfError::OutOfState(_))));
        assert!(matches!(c.set(&bad("bogus", "1"), Some(&st())), Err(ConfError::UnknownKey(_))));
        assert!(matches!(c.set(&bad("min", "x"), Some(&st())), Err(ConfError::NotANumber(_))));
        assert!(matches!(c.set(&Setting::Class { system: "gba".into(), profile: "nope".into() }, Some(&st())), Err(ConfError::UnknownProfile(_))));
        assert!(matches!(c.set(&Setting::Battery { warn: 3, critical: 5 }, Some(&st())), Err(ConfError::OutOfState(_))));
        assert_eq!(c.set(&Setting::Idle { after: 1 }, None), Err(ConfError::NoState));
        assert_eq!(c.to_text(), FILE);
    }

    #[test]
    fn min_below_the_game_floor_is_refused_for_game_profiles_only() {
        let mut c = PowerConf::parse("");
        // `heavy` is a class target, `game` is the default game profile: floor applies
        for name in ["heavy", "game"] {
            let s = Setting::Profile { name: name.into(), params: vec![("min".into(), "240000".into())] };
            assert_eq!(c.set(&s, Some(&st())), Err(ConfError::BelowFloor { min: 240000, floor: 600000 }));
        }
        // `menu` is not a game profile: a low min is fine
        let s = Setting::Profile { name: "menu".into(), params: vec![("min".into(), "120000".into())] };
        assert!(c.set(&s, Some(&st())).is_ok());
        // above the floor is fine
        let s = Setting::Profile { name: "heavy".into(), params: vec![("min".into(), "1008000".into())] };
        assert!(c.set(&s, Some(&st())).is_ok());
    }

    #[test]
    fn atomic_save_leaves_the_new_file_and_no_temporary() {
        let d = tmpdir("save");
        let p = d.join("power.conf");
        std::fs::write(&p, FILE).unwrap();
        let mut c = PowerConf::load(&p).unwrap();
        c.set(&Setting::Idle { after: 0 }, Some(&st())).unwrap();
        c.save(&p).unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), FILE.replace("idle after=300", "idle after=0"));
        let names: Vec<_> = std::fs::read_dir(&d).unwrap().map(|e| e.unwrap().file_name()).collect();
        assert_eq!(names.len(), 1);
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn failed_save_keeps_the_old_file() {
        let d = tmpdir("fail");
        let p = d.join("power.conf");
        std::fs::write(&p, FILE).unwrap();
        // renaming a file over a directory fails after the temporary was written
        let target = d.join("dirtarget");
        std::fs::create_dir(&target).unwrap();
        assert!(PowerConf::parse("x\n").save(&target).is_err());
        assert_eq!(std::fs::read_to_string(&p).unwrap(), FILE);
        assert!(!d.join(format!(".dirtarget.tmp{}", std::process::id())).exists());
        // a missing directory fails without creating anything
        assert!(PowerConf::parse("x\n").save(&d.join("no/such/power.conf")).is_err());
        let _ = std::fs::remove_dir_all(&d);
    }

    #[test]
    fn idle_and_battery_values_are_read_back() {
        let c = PowerConf::parse("# x\nidle after=45 # note\nbattery warn=8 critical=3\n");
        assert_eq!((c.idle_after(), c.battery_warn()), (Some(45), Some(8)));
        let c = PowerConf::parse("idle after=0\n");
        assert_eq!((c.idle_after(), c.battery_warn()), (Some(0), None));
        assert_eq!(PowerConf::parse("idle after=x\n").idle_after(), None);
        assert_eq!(PowerConf::parse("").idle_after(), None);
    }

    #[test]
    fn missing_file_loads_empty() {
        assert_eq!(PowerConf::load(Path::new("/nonexistent/power.conf")).unwrap().to_text(), "");
    }
}
