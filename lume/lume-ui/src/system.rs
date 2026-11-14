//! The device behind the Settings (lume-launcher D10), kept apart from the screens so tests
//! use a fake one. Nothing here runs unless the user is on that item: Wi-Fi with nmcli,
//! Bluetooth with bluetoothctl, the mixer with amixer (the control of the board's
//! r36os-input profile), the backlight in /sys/class/backlight (writable by the video group,
//! udev rule 90-lume-backlight.rules), and /proc and /sys for the System panel.

use std::path::{Path, PathBuf};
use std::process::Command;

pub trait SystemAdapter {
    fn wifi_present(&self) -> bool;
    fn bluetooth_present(&self) -> bool;
    /// e.g. "Connected: home" or "Disconnected", already in the user's language by the caller
    fn wifi_connected(&self) -> Option<String>;
    fn bluetooth_connected(&self) -> Option<String>;
    fn volume(&self) -> Option<u8>;
    fn set_volume(&mut self, pct: u8);
    fn brightness(&self) -> Option<u8>;
    fn set_brightness(&mut self, pct: u8);
    /// (text key, value) pairs of the System panel
    fn info(&self) -> Vec<(&'static str, String)>;
}

pub struct RealSystem {
    pub sys: PathBuf,
    pub proc_: PathBuf,
    pub mixer: Option<(String, String)>,
}

/// The mixer line of the r36os-input profile of this board ("mixer <card> <control> <step>").
pub fn board_mixer(profile: &Path) -> Option<(String, String)> {
    let text = std::fs::read_to_string(profile).ok()?;
    let line = text.lines().find(|l| l.trim_start().starts_with("mixer "))?;
    let rest = line.trim_start()["mixer ".len()..].trim();
    let (card, rest) = rest.split_once(' ')?;
    let ctl = rest.trim_end_matches(|c: char| c.is_ascii_digit()).trim();
    Some((card.to_string(), ctl.to_string()))
}

impl RealSystem {
    pub fn new() -> RealSystem {
        let board = std::fs::read_to_string("/etc/r36os/board").unwrap_or_default();
        RealSystem {
            sys: "/sys".into(),
            proc_: "/proc".into(),
            mixer: board_mixer(Path::new(&format!("/usr/share/r36os/input/{}.conf", board.trim()))),
        }
    }

    fn backlight(&self) -> Option<PathBuf> {
        std::fs::read_dir(self.sys.join("class/backlight")).ok()?.flatten().map(|e| e.path()).next()
    }
}

impl Default for RealSystem {
    fn default() -> Self {
        RealSystem::new()
    }
}

/// The first "[NN%]" of an `amixer sget` output.
pub fn parse_percent(out: &str) -> Option<u8> {
    let at = out.find("%]")?;
    let start = out[..at].rfind('[')? + 1;
    out[start..at].parse().ok()
}

fn read_num(p: &Path) -> Option<u64> {
    std::fs::read_to_string(p).ok()?.trim().parse().ok()
}

fn output(cmd: &str, args: &[&str]) -> Option<String> {
    let o = Command::new(cmd).args(args).output().ok()?;
    o.status.success().then(|| String::from_utf8_lossy(&o.stdout).into_owned())
}

impl SystemAdapter for RealSystem {
    fn wifi_present(&self) -> bool {
        std::fs::read_dir(self.sys.join("class/net"))
            .map(|d| d.flatten().any(|e| e.path().join("wireless").exists() || e.path().join("phy80211").exists()))
            .unwrap_or(false)
    }

    fn bluetooth_present(&self) -> bool {
        std::fs::read_dir(self.sys.join("class/bluetooth")).map(|d| d.flatten().next().is_some()).unwrap_or(false)
    }

    fn wifi_connected(&self) -> Option<String> {
        let out = output("nmcli", &["-t", "-f", "ACTIVE,SSID", "dev", "wifi"])?;
        out.lines().find_map(|l| l.strip_prefix("yes:").map(str::to_string))
    }

    fn bluetooth_connected(&self) -> Option<String> {
        let out = output("bluetoothctl", &["devices", "Connected"])?;
        out.lines().next().and_then(|l| l.splitn(3, ' ').nth(2)).map(str::to_string)
    }

    fn volume(&self) -> Option<u8> {
        let (card, ctl) = self.mixer.as_ref()?;
        let out = output("amixer", &["-c", card, "sget", ctl])?;
        parse_percent(&out)
    }

    fn set_volume(&mut self, pct: u8) {
        if let Some((card, ctl)) = &self.mixer {
            let _ = Command::new("amixer").args(["-c", card, "-q", "sset", ctl, &format!("{}%", pct.min(100))]).status();
        }
    }

    fn brightness(&self) -> Option<u8> {
        let b = self.backlight()?;
        let (cur, max) = (read_num(&b.join("brightness"))?, read_num(&b.join("max_brightness"))?);
        (max > 0).then(|| (cur * 100 / max) as u8)
    }

    fn set_brightness(&mut self, pct: u8) {
        if let Some(b) = self.backlight() {
            if let Some(max) = read_num(&b.join("max_brightness")) {
                // never fully dark: the screen would look off
                let v = (max * pct.clamp(5, 100) as u64 / 100).max(1);
                let _ = std::fs::write(b.join("brightness"), v.to_string());
            }
        }
    }

    fn info(&self) -> Vec<(&'static str, String)> {
        let mut out = Vec::new();
        let model = std::fs::read_to_string(self.proc_.join("device-tree/model"))
            .map(|s| s.trim_end_matches('\0').trim().to_string())
            .unwrap_or_else(|_| std::fs::read_to_string("/etc/r36os/board").unwrap_or_default().trim().to_string());
        out.push(("model", model));
        let cores = std::fs::read_to_string(self.proc_.join("cpuinfo")).map(|t| t.matches("processor").count()).unwrap_or(0);
        let mhz = read_num(&self.sys.join("devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")).map(|k| format!(" · {} MHz", k / 1000)).unwrap_or_default();
        out.push(("cpu", format!("{cores} × {}{mhz}", std::env::consts::ARCH)));
        let mem = std::fs::read_to_string(self.proc_.join("meminfo")).unwrap_or_default();
        let kb = |k: &str| mem.lines().find(|l| l.starts_with(k)).and_then(|l| l.split_whitespace().nth(1)).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0);
        out.push(("memory", format!("{} / {} MB", (kb("MemTotal:") - kb("MemAvailable:")) / 1024, kb("MemTotal:") / 1024)));
        let rss = std::fs::read_to_string(self.proc_.join("self/status")).unwrap_or_default();
        let rss = rss.lines().find(|l| l.starts_with("VmRSS:")).and_then(|l| l.split_whitespace().nth(1)).unwrap_or("?").to_string();
        out.push(("launcher_rss", format!("{rss} KB")));
        let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
        let storage = std::ffi::CString::new("/storage").unwrap();
        if unsafe { libc::statvfs(storage.as_ptr(), &mut st) } == 0 {
            let gb = |blocks: u64| blocks as f64 * st.f_frsize as f64 / 1e9;
            out.push(("storage", format!("{:.1} / {:.1} GB", gb(st.f_blocks as u64 - st.f_bavail as u64), gb(st.f_blocks as u64))));
        }
        if let Some(bat) = std::fs::read_dir(self.sys.join("class/power_supply")).ok().and_then(|d| {
            d.flatten().map(|e| e.path()).find(|p| std::fs::read_to_string(p.join("type")).map(|t| t.trim() == "Battery").unwrap_or(false))
        }) {
            let cap = read_num(&bat.join("capacity")).unwrap_or(0);
            let status = std::fs::read_to_string(bat.join("status")).unwrap_or_default();
            out.push(("battery", format!("{cap}%{}", if status.trim() == "Charging" { " +" } else { "" })));
        }
        out
    }
}

/// Writes `user_language` into the user's RetroArch config, atomically, so the next game and
/// the system messages (ui_lang in lib.sh) follow the launcher language (D10).
pub fn set_retroarch_language(cfg: &Path, value: u32) -> std::io::Result<()> {
    let text = std::fs::read_to_string(cfg).unwrap_or_default();
    let line = format!("user_language = \"{value}\"");
    let mut found = false;
    let mut out: Vec<String> = text
        .lines()
        .map(|l| {
            if l.split('=').next().map(str::trim) == Some("user_language") {
                found = true;
                line.clone()
            } else {
                l.to_string()
            }
        })
        .collect();
    if !found {
        out.push(line);
    }
    lume_core::atomic::write(cfg, (out.join("\n") + "\n").as_bytes())
}

/// The test adapter.
#[derive(Default)]
pub struct FakeSystem {
    pub wifi: bool,
    pub bluetooth: bool,
    pub vol: u8,
    pub bri: u8,
    pub info_reads: std::cell::Cell<u32>,
}

impl SystemAdapter for FakeSystem {
    fn wifi_present(&self) -> bool {
        self.wifi
    }
    fn bluetooth_present(&self) -> bool {
        self.bluetooth
    }
    fn wifi_connected(&self) -> Option<String> {
        self.wifi.then(|| "home".into())
    }
    fn bluetooth_connected(&self) -> Option<String> {
        None
    }
    fn volume(&self) -> Option<u8> {
        Some(self.vol)
    }
    fn set_volume(&mut self, pct: u8) {
        self.vol = pct;
    }
    fn brightness(&self) -> Option<u8> {
        Some(self.bri)
    }
    fn set_brightness(&mut self, pct: u8) {
        self.bri = pct;
    }
    fn info(&self) -> Vec<(&'static str, String)> {
        self.info_reads.set(self.info_reads.get() + 1);
        vec![("model", "Fake".into()), ("launcher_rss", "1234 KB".into())]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn language_is_written_for_retroarch_and_lib_sh() {
        let p = std::env::temp_dir().join(format!("lume-ra-{}.cfg", std::process::id()));
        std::fs::write(&p, "video_driver = \"gl\"\nuser_language = \"0\"\n").unwrap();
        set_retroarch_language(&p, 3).unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        assert_eq!(text, "video_driver = \"gl\"\nuser_language = \"3\"\n");
        // the same parsing as ui_lang in lib.sh: user_language = "N" -> es
        let v = text.lines().find_map(|l| l.strip_prefix("user_language = \"")).unwrap().trim_end_matches('"');
        assert_eq!(v, "3");
        std::fs::remove_file(&p).unwrap();
        set_retroarch_language(&p, 7).unwrap();
        assert_eq!(std::fs::read_to_string(&p).unwrap(), "user_language = \"7\"\n");
    }

    #[test]
    fn amixer_percent() {
        let out = "Simple mixer control 'Master',0\n  Front Left: Playback 52 [82%] [-6.00dB] [on]\n";
        assert_eq!(parse_percent(out), Some(82));
        assert_eq!(parse_percent("nothing"), None);
    }

    #[test]
    fn mixer_from_the_input_profile() {
        let prof = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../aports/r36os-input");
        assert_eq!(board_mixer(&prof.join("r36s.conf")), Some(("rk817int".into(), "Master".into())));
        assert_eq!(board_mixer(&prof.join("ga36.conf")), Some(("GA36MB".into(), "DAC".into())));
        assert_eq!(board_mixer(&prof.join("vm.conf")), Some(("0".into(), "Master".into())));
    }
}
