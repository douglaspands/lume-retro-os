//! Reader of `/run/r36os/power.state`, the state the `r36os-power` service publishes
//! (openspec game-governor, D16; format in docs/LOGS.md, "power.state").
//!
//! One `key value...` per line; unknown keys are ignored so the service may add keys. The
//! settings screen and the `power.conf` editor (`powerconf`) validate against this.

use std::path::{Path, PathBuf};

/// Where a line came from: the image console file or the card `power.conf`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Origin {
    Image,
    Card,
    /// Built-in default (no line anywhere).
    Default,
}

impl Origin {
    fn parse(s: &str) -> Option<Origin> {
        match s {
            "image" => Some(Origin::Image),
            "card" => Some(Origin::Card),
            "default" => Some(Origin::Default),
            _ => None,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Profile {
    pub origin: Origin,
    pub name: String,
    /// `key=value` pairs in file order.
    pub params: Vec<(String, String)>,
}

impl Profile {
    pub fn get(&self, key: &str) -> Option<&str> {
        self.params.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
    }
}

/// A `class <system> <profile>` or `core <core> <profile>` line.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Binding {
    pub origin: Origin,
    pub name: String,
    pub profile: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refused {
    pub origin: Origin,
    pub kind: String,
    /// `-` when the line had no name.
    pub name: String,
    pub reason: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct PowerState {
    pub console: String,
    /// `false` when profiles are switched off (`enabled 0`).
    pub enabled: bool,
    pub cpu_freqs: Vec<u32>,
    pub cpu_governors: Vec<String>,
    pub cpu_cores: u32,
    pub gpu_freqs: Vec<u64>,
    /// Effective game floor in kHz, `None` without one (R36S).
    pub game_min: Option<u32>,
    pub profiles: Vec<Profile>,
    pub classes: Vec<Binding>,
    pub core_overrides: Vec<Binding>,
    /// `(warn, critical)` in percent, `None` when no `battery` line exists.
    pub battery: Option<(u32, u32)>,
    pub idle_after: u32,
    pub scenario: String,
    pub current_profile: String,
    pub refused: Vec<Refused>,
}

fn nums<T: std::str::FromStr>(s: &str) -> Vec<T> {
    s.split_whitespace().filter_map(|w| w.parse().ok()).collect()
}

fn pairs(s: &str) -> Vec<(String, String)> {
    s.split_whitespace()
        .filter_map(|w| w.split_once('=').map(|(k, v)| (k.to_string(), v.to_string())))
        .collect()
}

impl PowerState {
    pub fn parse(text: &str) -> PowerState {
        let mut st = PowerState { enabled: true, idle_after: 120, ..PowerState::default() };
        for line in text.lines() {
            let line = line.trim();
            let (key, rest) = line.split_once(' ').unwrap_or((line, ""));
            let rest = rest.trim();
            // `<origin> <a> <b...>` helper
            let origin_split = |r: &str| -> Option<(Origin, String)> {
                let (o, tail) = r.split_once(' ').unwrap_or((r, ""));
                Some((Origin::parse(o)?, tail.trim().to_string()))
            };
            match key {
                "console" => st.console = rest.to_string(),
                "enabled" => {
                    if let Some((_, v)) = origin_split(rest) {
                        st.enabled = v != "0";
                    }
                }
                "cpu_freqs" => st.cpu_freqs = nums(rest),
                "cpu_governors" => st.cpu_governors = rest.split_whitespace().map(String::from).collect(),
                "cpu_cores" => st.cpu_cores = rest.parse().unwrap_or(0),
                "gpu_freqs" => st.gpu_freqs = nums(rest),
                "game_min" => st.game_min = rest.parse().ok(),
                "profile" => {
                    if let Some((origin, tail)) = origin_split(rest) {
                        let (name, kv) = tail.split_once(' ').unwrap_or((tail.as_str(), ""));
                        st.profiles.push(Profile { origin, name: name.to_string(), params: pairs(kv) });
                    }
                }
                "class" | "core" => {
                    if let Some((origin, tail)) = origin_split(rest) {
                        let mut w = tail.split_whitespace();
                        if let (Some(n), Some(p)) = (w.next(), w.next()) {
                            let b = Binding { origin, name: n.to_string(), profile: p.to_string() };
                            if key == "class" {
                                st.classes.push(b);
                            } else {
                                st.core_overrides.push(b);
                            }
                        }
                    }
                }
                "battery" => {
                    if let Some((_, tail)) = origin_split(rest) {
                        let kv = pairs(&tail);
                        let get = |k: &str| kv.iter().find(|(a, _)| a == k).and_then(|(_, v)| v.parse().ok());
                        if let (Some(w), Some(c)) = (get("warn"), get("critical")) {
                            st.battery = Some((w, c));
                        }
                    }
                }
                "idle" => {
                    if let Some((_, tail)) = origin_split(rest) {
                        if let Some((_, v)) = pairs(&tail).into_iter().find(|(k, _)| k == "after") {
                            st.idle_after = v.parse().unwrap_or(120);
                        }
                    }
                }
                "scenario" => st.scenario = rest.to_string(),
                "current" => st.current_profile = rest.to_string(),
                "refused" => {
                    if let Some((origin, tail)) = origin_split(rest) {
                        let mut w = tail.splitn(3, ' ');
                        let kind = w.next().unwrap_or("").to_string();
                        let name = w.next().unwrap_or("-").to_string();
                        let reason = w.next().unwrap_or("").to_string();
                        st.refused.push(Refused { origin, kind, name, reason });
                    }
                }
                _ => {}
            }
        }
        st
    }

    /// Reads and parses the file; `None` when the service has not published it.
    pub fn read(path: &Path) -> Option<PowerState> {
        std::fs::read_to_string(path).ok().map(|t| PowerState::parse(&t))
    }

    pub fn profile(&self, name: &str) -> Option<&Profile> {
        self.profiles.iter().find(|p| p.name == name)
    }

    /// `true` when a game uses this profile (`game`, or a class/core target).
    pub fn is_game_profile(&self, name: &str) -> bool {
        name == "game"
            || self.classes.iter().any(|b| b.profile == name)
            || self.core_overrides.iter().any(|b| b.profile == name)
    }
}

/// `$R36OS_RUN/power.state` (default `/run/r36os/power.state`).
pub fn state_path() -> PathBuf {
    std::env::var_os("R36OS_RUN").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/run/r36os")).join("power.state")
}

#[cfg(test)]
pub(crate) const SAMPLE: &str = "\
console ga36
enabled default 1
cpu_freqs 120000 240000 600000 1008000
cpu_governors performance schedutil ondemand
cpu_cores 4
gpu_freqs 144000000 432000000
game_min 600000
limit image game_min=600000
profile image boot governor=performance
profile image game governor=schedutil min=600000 cores=4
profile card heavy governor=performance cores=4 min=1008000
class image nes heavy
core card snes9x2005_plus heavy
battery image warn=5 critical=3
idle default after=120
scenario game
current heavy
refused card profile light min 120000 below game floor 600000
";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_every_key() {
        let s = PowerState::parse(SAMPLE);
        assert_eq!(s.console, "ga36");
        assert!(s.enabled);
        assert_eq!(s.cpu_freqs, vec![120000, 240000, 600000, 1008000]);
        assert_eq!(s.cpu_governors, vec!["performance", "schedutil", "ondemand"]);
        assert_eq!(s.cpu_cores, 4);
        assert_eq!(s.gpu_freqs.len(), 2);
        assert_eq!(s.game_min, Some(600000));
        assert_eq!(s.profiles.len(), 3);
        assert_eq!(s.profile("heavy").unwrap().origin, Origin::Card);
        assert_eq!(s.profile("heavy").unwrap().get("min"), Some("1008000"));
        assert_eq!(s.classes[0], Binding { origin: Origin::Image, name: "nes".into(), profile: "heavy".into() });
        assert_eq!(s.core_overrides[0].name, "snes9x2005_plus");
        assert_eq!(s.battery, Some((5, 3)));
        assert_eq!(s.idle_after, 120);
        assert_eq!((s.scenario.as_str(), s.current_profile.as_str()), ("game", "heavy"));
        assert_eq!(s.refused[0].kind, "profile");
        assert_eq!(s.refused[0].name, "light");
        assert_eq!(s.refused[0].reason, "min 120000 below game floor 600000");
        assert!(s.is_game_profile("heavy") && s.is_game_profile("game") && !s.is_game_profile("boot"));
    }

    #[test]
    fn disabled_and_unknown_keys() {
        let s = PowerState::parse("enabled card 0\nfuture_key x y\nidle card after=300\n");
        assert!(!s.enabled);
        assert_eq!(s.idle_after, 300);
        assert_eq!(s.game_min, None);
    }

    #[test]
    fn missing_file_is_none() {
        assert!(PowerState::read(Path::new("/nonexistent/power.state")).is_none());
    }
}
