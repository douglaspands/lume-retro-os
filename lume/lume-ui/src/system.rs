//! The device behind the Settings (lume-launcher D10), kept apart from the screens so tests
//! use a fake one. Nothing here runs unless the user is on that item: Wi-Fi with nmcli,
//! Bluetooth with bluetoothctl, the mixer with amixer (the control of the board's
//! lume-input profile), the backlight in /sys/class/backlight (writable by the video group,
//! udev rule 90-lume-backlight.rules), and /proc and /sys for the System panel.

use std::path::{Path, PathBuf};
use std::process::Command;

use crate::volume;

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
    /// Saves the current brightness on the card for the next boot (lume-input re-applies it).
    /// Only the user's choice goes through here, never the idle dimming (device-fixes 9.15).
    fn save_brightness(&mut self);
    /// (text key, value) pairs of the System panel
    fn info(&self) -> Vec<(&'static str, String)>;
    /// battery level in percent and whether it is charging; None without a battery
    fn battery(&self) -> Option<(u8, bool)>;
    /// (Wi-Fi connected, Bluetooth connected), for the status bar
    fn network(&self) -> (bool, bool);
    /// The IPv4 address of the Wi-Fi interface (not a Wi-Fi Direct one), for SSH over Wi-Fi
    fn wifi_address(&self) -> Option<String>;
    /// Free bytes of the games partition (`statvfs` of /storage), for the Card panel
    fn card_free(&self) -> Option<u64>;
}

/// The Wi-Fi interface: one with `wireless/` or `phy80211`, not a Wi-Fi Direct group
/// (`p2p-*`), the same choice as lume-ssh-wifi.
pub fn wifi_interface(sys: &Path) -> Option<String> {
    let mut names: Vec<String> = std::fs::read_dir(sys.join("class/net"))
        .ok()?
        .flatten()
        .filter(|e| e.path().join("wireless").exists() || e.path().join("phy80211").exists())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| !n.starts_with("p2p"))
        .collect();
    names.sort();
    names.into_iter().next()
}

/// The address of an `ip -4 -o addr show` line ("... inet 192.168.1.20/24 ...").
pub fn parse_inet(out: &str) -> Option<String> {
    let rest = out.split(" inet ").nth(1)?;
    rest.split('/').next().map(|a| a.trim().to_string()).filter(|a| !a.is_empty())
}

/// Whether a Wi-Fi interface is up and a Bluetooth link is open, from /sys only (no nmcli
/// or bluetoothctl: a process costs 7 to 41 ms on the A33). Wi-Fi: an interface with
/// `wireless/` whose operstate is "up". Bluetooth: each open link is a `hci<N>:<handle>`
/// entry in class/bluetooth.
pub fn read_network(sys: &Path) -> (bool, bool) {
    let wifi = std::fs::read_dir(sys.join("class/net"))
        .map(|d| {
            d.flatten().any(|e| {
                let p = e.path();
                (p.join("wireless").exists() || p.join("phy80211").exists())
                    && std::fs::read_to_string(p.join("operstate")).map(|s| s.trim() == "up").unwrap_or(false)
            })
        })
        .unwrap_or(false);
    let bt = std::fs::read_dir(sys.join("class/bluetooth"))
        .map(|d| d.flatten().any(|e| e.file_name().to_string_lossy().contains(':')))
        .unwrap_or(false);
    (wifi, bt)
}

/// The CPU temperature in millidegrees: the thermal zone whose type names the CPU or the SoC
/// (GA36 `cpu-thermal`, R36S `soc-thermal`), else the first zone. One sysfs read while the
/// System item is shown.
pub fn read_cpu_temp(sys: &Path) -> Option<i64> {
    let mut zones: Vec<PathBuf> = std::fs::read_dir(sys.join("class/thermal"))
        .ok()?
        .flatten()
        .map(|e| e.path())
        .filter(|p| p.file_name().is_some_and(|n| n.to_string_lossy().starts_with("thermal_zone")))
        .collect();
    zones.sort();
    let kind = |p: &PathBuf| std::fs::read_to_string(p.join("type")).unwrap_or_default();
    let zone = zones.iter().find(|p| {
        let k = kind(p);
        k.contains("cpu") || k.contains("soc")
    });
    let zone = zone.or(zones.first())?;
    std::fs::read_to_string(zone.join("temp")).ok()?.trim().parse().ok()
}

/// The battery of /sys/class/power_supply (the first supply of type Battery): level and
/// charging. Two small sysfs reads; the status bar asks every 5 s from its own thread.
pub fn read_battery(sys: &Path) -> Option<(u8, bool)> {
    let bat = std::fs::read_dir(sys.join("class/power_supply"))
        .ok()?
        .flatten()
        .map(|e| e.path())
        .find(|p| std::fs::read_to_string(p.join("type")).map(|t| t.trim() == "Battery").unwrap_or(false))?;
    let cap = read_num(&bat.join("capacity"))?.min(100) as u8;
    let status = std::fs::read_to_string(bat.join("status")).unwrap_or_default();
    // only "Charging" draws the bolt: "Full" is a full icon without one (design D9)
    Some((cap, status.trim() == "Charging"))
}

pub struct RealSystem {
    pub sys: PathBuf,
    pub proc_: PathBuf,
    pub mixer: Option<Mixer>,
    /// the backlight's raw ceiling from the board's lume-input profile (100% of the launcher)
    pub backlight_max: Option<u64>,
    /// where the brightness level is saved (`BRIGHTNESS_FILE`)
    pub brightness_file: PathBuf,
}

/// The saved brightness (`ROMS/system/display/brightness`, frozen in docs/LAUNCHER.md): an
/// integer 0-100 and a newline, in percent of the launcher's scale (the ceiling is 100%).
pub const BRIGHTNESS_FILE: &str = "/storage/system/display/brightness";

/// The `backlight_max` line of a lume-input profile (GA36: 8 of 10, the panel flickers
/// above it).
pub fn board_backlight_max(profile: &Path) -> Option<u64> {
    let text = std::fs::read_to_string(profile).ok()?;
    let line = text.lines().find(|l| l.trim_start().starts_with("backlight_max "))?;
    line.split_whitespace().nth(1)?.parse().ok().filter(|v| *v > 0)
}

/// The level in percent of a raw backlight value, with the ceiling as 100%.
pub fn backlight_percent(cur: u64, max: u64, ceiling: Option<u64>) -> Option<u8> {
    let top = ceiling.map_or(max, |c| c.min(max));
    (top > 0).then(|| ((cur.min(top) * 100 + top / 2) / top) as u8)
}

/// The raw backlight value of a percent, with the ceiling as 100% (never dark: 5% at least,
/// and at least level 1). Truncated, so a coarse backlight (GA36) still moves on a 5% step.
pub fn backlight_value(pct: u8, max: u64, ceiling: Option<u64>) -> u64 {
    let top = ceiling.map_or(max, |c| c.min(max));
    (top * pct.clamp(5, 100) as u64 / 100).max(1)
}

/// The level folder on the card (`ROMS/system/audio`, frozen in docs/LAUNCHER.md).
pub const LEVEL_DIR: &str = "/storage/system/audio";
/// The active output written by the jack service (R36S); absent: the speaker.
pub const OUTPUT_FILE: &str = "/run/lume/audio/output";

/// The mixer of the board, from the lume-input profile (the same lines lume-input reads, so
/// the Settings row and the volume keys move the same control on the same scale).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Mixer {
    pub card: String,
    pub ctl: String,
    /// `mixer_scale` (device-fixes 7.2): the control on the perceptual scale of volume.rs,
    /// with one level per output; None: amixer's own percent (the vm)
    pub scale: Option<volume::Control>,
    /// `mixer_switch`: 0% turns the control's switch off, any other level on
    pub switch: bool,
    /// `mixer_keep <control> <values>`: set again with every level (GA36: DAC 160 on)
    pub keep: Option<(String, Vec<String>)>,
    /// `mixer_amp <control>` (device-fixes 7.5): the amplifier switch, off at 0%, on otherwise
    pub amp: Option<String>,
    /// `mixer_old <control> <lo> <hi> <ref> <mdb step>`: the old volume, for the one-time
    /// conversion
    pub old: Option<(String, volume::Control)>,
    pub level_dir: PathBuf,
    pub output_file: PathBuf,
}

/// The words of a profile line after its key: the control (every word before the first
/// number) and the numbers or values after it.
fn ctl_and_rest(rest: &str) -> Option<(String, Vec<String>)> {
    let words: Vec<&str> = rest.split_whitespace().collect();
    let n = words.iter().position(|w| w.starts_with(|c: char| c.is_ascii_digit()))?;
    let ctl = words[..n].join(" ");
    (!ctl.is_empty()).then(|| (ctl, words[n..].iter().map(|w| w.to_string()).collect()))
}

fn control_of(v: &[String]) -> Option<volume::Control> {
    let n: Vec<i32> = v.iter().map(|w| w.parse().ok()).collect::<Option<_>>()?;
    let [lo, hi, reference, mdb_step] = n[..] else { return None };
    (lo < reference && reference <= hi && mdb_step > 0).then_some(volume::Control { lo, hi, reference, mdb_step })
}

/// The mixer lines of the lume-input profile of this board ("mixer <card> <control, may
/// have spaces> <step>", "mixer_scale", "mixer_switch", "mixer_keep", "mixer_old").
pub fn board_mixer(profile: &Path) -> Option<Mixer> {
    let text = std::fs::read_to_string(profile).ok()?;
    let mut m: Option<Mixer> = None;
    let (mut scale, mut switch, mut keep, mut old, mut amp) = (None, false, None, None, None);
    for line in text.lines().map(|l| l.split('#').next().unwrap_or("").trim()) {
        let (key, rest) = line.split_once(char::is_whitespace).unwrap_or((line, ""));
        match key {
            "mixer" => {
                let (card, rest) = rest.trim().split_once(char::is_whitespace)?;
                let (ctl, _) = ctl_and_rest(rest)?;
                m = Some(Mixer {
                    card: card.to_string(),
                    ctl,
                    scale: None,
                    switch: false,
                    keep: None,
                    amp: None,
                    old: None,
                    level_dir: LEVEL_DIR.into(),
                    output_file: OUTPUT_FILE.into(),
                });
            }
            "mixer_scale" => scale = control_of(&rest.split_whitespace().map(String::from).collect::<Vec<_>>()),
            "mixer_switch" => switch = true,
            "mixer_keep" => keep = ctl_and_rest(rest),
            "mixer_amp" => amp = Some(rest.trim().to_string()).filter(|c| !c.is_empty()),
            "mixer_old" => old = ctl_and_rest(rest).and_then(|(c, v)| Some((c, control_of(&v)?))),
            _ => {}
        }
    }
    m.map(|m| Mixer { scale, switch, keep, amp, old, ..m })
}

/// The first channel's raw value of an `amixer sget` output ("Playback 160 [83%]").
pub fn parse_raw(out: &str) -> Option<i32> {
    out.lines()
        .filter(|l| !l.contains("Limits:"))
        .find_map(|l| l.split_once("Playback ").and_then(|(_, r)| r.split_whitespace().next()?.parse().ok()))
}

/// A saved level: one integer 0-100 (anything else is no level).
pub fn parse_level(text: &str) -> Option<u8> {
    text.trim().parse::<u8>().ok().filter(|v| *v <= 100)
}

/// The mixer of the board this runs on (/etc/lume/board names the profile).
pub fn this_board_mixer() -> Option<Mixer> {
    let board = std::fs::read_to_string("/etc/lume/board").unwrap_or_default();
    board_mixer(Path::new(&format!("/usr/share/lume/input/{}.conf", board.trim())))
}

impl Mixer {
    /// The active output: "headphones" when the jack service says so, else "speaker".
    pub fn output_name(&self) -> &'static str {
        let text = std::fs::read_to_string(&self.output_file).unwrap_or_default();
        if text.trim() == "headphones" { "headphones" } else { "speaker" }
    }

    fn level_file(&self) -> PathBuf {
        self.level_dir.join(format!("level-{}", self.output_name()))
    }

    /// The level in percent of the active output, the one the volume keys move.
    pub fn level(&self) -> Option<u8> {
        self.level_with(|ctl| output("amixer", &["-c", &self.card, "sget", ctl]))
    }

    /// The level with `sget` standing for "amixer sget <control>": with a scale, the saved
    /// level of the output, else (one-time conversion, as lume-input) the old control while
    /// it is not at its 0 dB, else the control's own position, else 70%; without a scale,
    /// amixer's own percent.
    pub fn level_with(&self, sget: impl Fn(&str) -> Option<String>) -> Option<u8> {
        let Some(scale) = &self.scale else { return parse_percent(&sget(&self.ctl)?) };
        if let Some(v) = std::fs::read_to_string(self.level_file()).ok().as_deref().and_then(parse_level) {
            return Some(v);
        }
        if let Some((ctl, old)) = &self.old {
            if let Some(raw) = sget(ctl).as_deref().and_then(parse_raw).filter(|r| *r != old.reference) {
                return Some(volume::convert_old(old, raw) as u8);
            }
        }
        let own = sget(&self.ctl).as_deref().and_then(parse_raw);
        Some(own.map_or(volume::DEFAULT_PCT, |raw| volume::pct_from_raw(scale, raw)) as u8)
    }

    /// The amixer "sset" argument lists that apply a level (after "-c <card> -q sset").
    pub fn set_args(&self, pct: u8) -> Vec<Vec<String>> {
        let Some(scale) = &self.scale else { return vec![vec![self.ctl.clone(), format!("{}%", pct.min(100))]] };
        let mut first = vec![self.ctl.clone(), volume::raw(scale, pct.min(100) as i32).to_string()];
        if self.switch {
            first.push(if pct > 0 { "on" } else { "off" }.into());
        }
        let mut v = vec![first];
        if let Some((ctl, values)) = &self.keep {
            v.push([vec![ctl.clone()], values.clone()].concat());
        }
        if let Some(amp) = &self.amp {
            v.push(vec![amp.clone(), if pct > 0 { "on" } else { "off" }.into()]);
        }
        v
    }

    /// Applies a level to the mixer and, with a scale, saves it for the active output.
    pub fn set(&self, pct: u8) {
        for args in self.set_args(pct) {
            let _ = Command::new("amixer").args(["-c", &self.card, "-q", "sset"]).args(&args).status();
        }
        if self.scale.is_some() {
            if let Err(e) = self.save(pct) {
                lume_core::log::line("lume-ui", &format!("volume not saved: {e}"));
            }
        }
    }

    /// Writes level-<output> through a hidden file and a rename (as lume-input does).
    pub fn save(&self, pct: u8) -> std::io::Result<()> {
        std::fs::create_dir_all(&self.level_dir)?;
        let path = self.level_file();
        let tmp = self.level_dir.join(format!(".{}.tmp", path.file_name().unwrap_or_default().to_string_lossy()));
        std::fs::write(&tmp, format!("{}\n", pct.min(100)))?;
        std::fs::rename(&tmp, &path)
    }
}

impl RealSystem {
    pub fn new() -> RealSystem {
        let board = std::fs::read_to_string("/etc/lume/board").unwrap_or_default();
        let profile = PathBuf::from(format!("/usr/share/lume/input/{}.conf", board.trim()));
        RealSystem { sys: "/sys".into(), proc_: "/proc".into(), mixer: this_board_mixer(), backlight_max: board_backlight_max(&profile), brightness_file: BRIGHTNESS_FILE.into() }
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
        self.mixer.as_ref()?.level()
    }

    fn set_volume(&mut self, pct: u8) {
        if let Some(m) = &self.mixer {
            m.set(pct);
        }
    }

    fn brightness(&self) -> Option<u8> {
        let b = self.backlight()?;
        let (cur, max) = (read_num(&b.join("brightness"))?, read_num(&b.join("max_brightness"))?);
        // rounded, as lume-input steps it (Fn + volume keys), the ceiling as 100%
        backlight_percent(cur, max, self.backlight_max)
    }

    fn set_brightness(&mut self, pct: u8) {
        if let Some(b) = self.backlight() {
            if let Some(max) = read_num(&b.join("max_brightness")) {
                // never fully dark, never above the board's ceiling (GA36: level 8)
                let v = backlight_value(pct, max, self.backlight_max);
                let _ = std::fs::write(b.join("brightness"), v.to_string());
            }
        }
    }

    fn save_brightness(&mut self) {
        // the level as it reads back, so lume-input applies the same raw value at boot
        if let Some(pct) = self.brightness() {
            if let Err(e) = lume_core::atomic::write(&self.brightness_file, format!("{pct}\n").as_bytes()) {
                lume_core::log::line("lume-ui", &format!("brightness not saved: {e}"));
            }
        }
    }

    fn info(&self) -> Vec<(&'static str, String)> {
        let mut out = Vec::new();
        let model = std::fs::read_to_string(self.proc_.join("device-tree/model"))
            .map(|s| s.trim_end_matches('\0').trim().to_string())
            .unwrap_or_else(|_| std::fs::read_to_string("/etc/lume/board").unwrap_or_default().trim().to_string());
        out.push(("model", model));
        let cores = std::fs::read_to_string(self.proc_.join("cpuinfo")).map(|t| t.matches("processor").count()).unwrap_or(0);
        let mhz = read_num(&self.sys.join("devices/system/cpu/cpu0/cpufreq/scaling_cur_freq")).map(|k| format!(" · {} MHz", k / 1000)).unwrap_or_default();
        out.push(("cpu", format!("{cores} × {}{mhz}", std::env::consts::ARCH)));
        if let Some(t) = read_cpu_temp(&self.sys) {
            out.push(("temperature", format!("{:.1} °C", t as f64 / 1000.0)));
        }
        let mem = std::fs::read_to_string(self.proc_.join("meminfo")).unwrap_or_default();
        let kb = |k: &str| mem.lines().find(|l| l.starts_with(k)).and_then(|l| l.split_whitespace().nth(1)).and_then(|v| v.parse::<u64>().ok()).unwrap_or(0);
        out.push(("memory", format!("{} / {} MB", (kb("MemTotal:") - kb("MemAvailable:")) / 1024, kb("MemTotal:") / 1024)));
        let rss = std::fs::read_to_string(self.proc_.join("self/status")).unwrap_or_default();
        let rss = rss.lines().find(|l| l.starts_with("VmRSS:")).and_then(|l| l.split_whitespace().nth(1)).and_then(|k| k.parse::<u64>().ok());
        out.push(("launcher_rss", rss.map(|k| format!("{} MB", (k + 512) / 1024)).unwrap_or_else(|| "?".into())));
        let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
        let storage = std::ffi::CString::new("/storage").unwrap();
        if unsafe { libc::statvfs(storage.as_ptr(), &mut st) } == 0 {
            let gb = |blocks: u64| blocks as f64 * st.f_frsize as f64 / 1e9;
            out.push(("storage", format!("{:.1} / {:.1} GB", gb(st.f_blocks as u64 - st.f_bavail as u64), gb(st.f_blocks as u64))));
        }
        if let Some((cap, charging)) = read_battery(&self.sys) {
            out.push(("battery", format!("{cap}%{}", if charging { " +" } else { "" })));
        }
        out
    }

    fn battery(&self) -> Option<(u8, bool)> {
        read_battery(&self.sys)
    }

    fn card_free(&self) -> Option<u64> {
        let mut st: libc::statvfs = unsafe { std::mem::zeroed() };
        let storage = std::ffi::CString::new("/storage").ok()?;
        (unsafe { libc::statvfs(storage.as_ptr(), &mut st) } == 0).then(|| st.f_bavail as u64 * st.f_frsize as u64)
    }

    fn network(&self) -> (bool, bool) {
        read_network(&self.sys)
    }

    fn wifi_address(&self) -> Option<String> {
        let iface = wifi_interface(&self.sys)?;
        parse_inet(&output("ip", &["-4", "-o", "addr", "show", "dev", &iface])?)
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
    pub batt: Option<(u8, bool)>,
    pub net: (bool, bool),
    pub addr: Option<String>,
    pub free: Option<u64>,
    /// the brightness last saved with `save_brightness` (the dimming never saves)
    pub saved_bri: Option<u8>,
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
    fn save_brightness(&mut self) {
        self.saved_bri = Some(self.bri);
    }
    fn info(&self) -> Vec<(&'static str, String)> {
        self.info_reads.set(self.info_reads.get() + 1);
        vec![("model", "Fake".into()), ("launcher_rss", "1234 KB".into())]
    }
    fn battery(&self) -> Option<(u8, bool)> {
        self.batt
    }
    fn network(&self) -> (bool, bool) {
        self.net
    }
    fn wifi_address(&self) -> Option<String> {
        self.addr.clone()
    }
    fn card_free(&self) -> Option<u64> {
        self.free
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backlight_ceiling_from_the_profile_is_100_percent() {
        let p = std::env::temp_dir().join(format!("lume-bl-{}.conf", std::process::id()));
        std::fs::write(&p, "name X\nmixer C DAC 3 160\nbacklight_max 8\n").unwrap();
        assert_eq!(board_backlight_max(&p), Some(8));
        std::fs::write(&p, "name X\n").unwrap();
        assert_eq!(board_backlight_max(&p), None);
        // GA36: 0-10 with the ceiling at 8
        assert_eq!(backlight_percent(8, 10, Some(8)), Some(100));
        assert_eq!(backlight_percent(10, 10, Some(8)), Some(100), "above the ceiling reads 100%");
        assert_eq!(backlight_percent(4, 10, Some(8)), Some(50));
        assert_eq!(backlight_value(100, 10, Some(8)), 8);
        assert_eq!(backlight_value(95, 10, Some(8)), 7);
        assert_eq!(backlight_value(5, 10, Some(8)), 1);
        // without a ceiling, as before
        assert_eq!(backlight_value(100, 10, None), 10);
        assert_eq!(backlight_percent(9, 10, None), Some(90));
    }

    #[test]
    fn cpu_temperature_from_the_cpu_zone() {
        let sys = std::env::temp_dir().join(format!("lume-thermal-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&sys);
        assert_eq!(read_cpu_temp(&sys), None, "no thermal class");
        for (z, kind, temp) in [("thermal_zone0", "gpu-thermal", "51000"), ("thermal_zone1", "cpu-thermal", "42606")] {
            let d = sys.join("class/thermal").join(z);
            std::fs::create_dir_all(&d).unwrap();
            std::fs::write(d.join("type"), format!("{kind}\n")).unwrap();
            std::fs::write(d.join("temp"), format!("{temp}\n")).unwrap();
        }
        // a cooling device is not a zone; the CPU's zone wins over the first one
        std::fs::create_dir_all(sys.join("class/thermal/cooling_device0")).unwrap();
        assert_eq!(read_cpu_temp(&sys), Some(42606));
    }

    #[test]
    fn wifi_interface_and_address() {
        let root = std::env::temp_dir().join(format!("lume-wifi-if-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&root);
        for (n, wireless) in [("eth0", false), ("wlan0", true), ("p2p-wlan0-0", true)] {
            std::fs::create_dir_all(root.join("class/net").join(n)).unwrap();
            if wireless {
                std::fs::create_dir_all(root.join("class/net").join(n).join("wireless")).unwrap();
            }
        }
        // the Wi-Fi Direct group is never the one
        assert_eq!(wifi_interface(&root).as_deref(), Some("wlan0"));
        let line = "3: wlan0    inet 192.168.1.20/24 brd 192.168.1.255 scope global dynamic wlan0\\       valid_lft 86000sec";
        assert_eq!(parse_inet(line).as_deref(), Some("192.168.1.20"));
        assert_eq!(parse_inet(""), None);
    }

    #[test]
    fn network_from_sysfs() {
        let sys = std::env::temp_dir().join(format!("lume-net-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&sys);
        std::fs::create_dir_all(sys.join("class/net/eth0")).unwrap();
        std::fs::write(sys.join("class/net/eth0/operstate"), "up\n").unwrap();
        std::fs::create_dir_all(sys.join("class/net/wlan0/wireless")).unwrap();
        std::fs::write(sys.join("class/net/wlan0/operstate"), "down\n").unwrap();
        std::fs::create_dir_all(sys.join("class/bluetooth/hci0")).unwrap();
        // a wired link up and an idle adapter: nothing to show
        assert_eq!(read_network(&sys), (false, false));
        std::fs::write(sys.join("class/net/wlan0/operstate"), "up\n").unwrap();
        std::fs::create_dir_all(sys.join("class/bluetooth/hci0:12")).unwrap();
        assert_eq!(read_network(&sys), (true, true));
        assert_eq!(read_network(Path::new("/nonexistent")), (false, false));
    }

    #[test]
    fn battery_from_sysfs() {
        let sys = std::env::temp_dir().join(format!("lume-sys-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&sys);
        let ps = sys.join("class/power_supply");
        for (name, kind) in [("axp20x-usb", "USB"), ("axp20x-battery", "Battery")] {
            std::fs::create_dir_all(ps.join(name)).unwrap();
            std::fs::write(ps.join(name).join("type"), format!("{kind}\n")).unwrap();
        }
        assert_eq!(read_battery(&sys), None, "no capacity yet");
        std::fs::write(ps.join("axp20x-battery/capacity"), "82\n").unwrap();
        std::fs::write(ps.join("axp20x-battery/status"), "Discharging\n").unwrap();
        assert_eq!(read_battery(&sys), Some((82, false)));
        std::fs::write(ps.join("axp20x-battery/status"), "Charging\n").unwrap();
        assert_eq!(read_battery(&sys), Some((82, true)));
        std::fs::write(ps.join("axp20x-battery/status"), "Full\n").unwrap();
        assert_eq!(read_battery(&sys), Some((82, false)), "full: no charge mark");
        assert_eq!(read_battery(Path::new("/nonexistent")), None);
    }

    #[test]
    fn the_brightness_is_saved_as_it_reads_back() {
        // GA36: 0-10 with the ceiling 7; 3 of 7 reads back as 43% and is saved as 43
        let dir = std::env::temp_dir().join(format!("lume-bri-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let panel = dir.join("sys/class/backlight/panel");
        std::fs::create_dir_all(&panel).unwrap();
        std::fs::write(panel.join("max_brightness"), "10\n").unwrap();
        std::fs::write(panel.join("brightness"), "8\n").unwrap();
        let mut s = RealSystem { sys: dir.join("sys"), proc_: dir.join("proc"), mixer: None, backlight_max: Some(7), brightness_file: dir.join("display/brightness") };
        s.set_brightness(50);
        assert!(!s.brightness_file.exists(), "setting alone saves nothing (the dimming uses it)");
        s.save_brightness();
        assert_eq!(std::fs::read_to_string(&s.brightness_file).unwrap(), "43\n");
        assert_eq!(std::fs::read_to_string(panel.join("brightness")).unwrap().trim(), "3");
        std::fs::remove_dir_all(&dir).unwrap();
    }

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

    fn profile_mixer(board: &str) -> Mixer {
        let prof = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../aports/lume-input");
        board_mixer(&prof.join(format!("{board}.conf"))).unwrap()
    }

    #[test]
    fn mixer_from_the_input_profile() {
        // the same lines lume-input reads (device-fixes 7.2)
        let ga36 = profile_mixer("ga36");
        assert_eq!((ga36.card.as_str(), ga36.ctl.as_str()), ("GA36MB", "Headphone"));
        assert_eq!(ga36.scale, Some(volume::GA36_HEADPHONE));
        assert!(ga36.switch);
        assert_eq!(ga36.keep, Some(("DAC".into(), vec!["160".into(), "on".into()])));
        assert_eq!(ga36.old, Some(("DAC".into(), volume::GA36_DAC_OLD)));
        let r36s = profile_mixer("r36s");
        assert_eq!((r36s.card.as_str(), r36s.ctl.as_str()), ("rk817int", "Master"));
        assert_eq!(r36s.scale, Some(volume::R36S_MASTER));
        assert!(!r36s.switch && r36s.keep.is_none() && r36s.old.is_none());
        let vm = profile_mixer("vm");
        assert_eq!((vm.card.as_str(), vm.ctl.as_str(), vm.scale), ("0", "Master", None));
        assert_eq!((ga36.level_dir.as_path(), ga36.output_file.as_path()), (Path::new(LEVEL_DIR), Path::new(OUTPUT_FILE)));
        // a control name with spaces
        let p = std::env::temp_dir().join(format!("lume-mixer-{}.conf", std::process::id()));
        std::fs::write(&p, "name X\nmixer card0 AIF1 DA0 5\nmixer_scale 0 63 64 1500\n").unwrap();
        let m = board_mixer(&p).unwrap();
        assert_eq!((m.ctl.as_str(), m.scale), ("AIF1 DA0", None), "a bad scale is no scale");
        std::fs::remove_file(&p).unwrap();
    }

    #[test]
    fn amixer_raw_value() {
        let out = "Simple mixer control 'DAC',0\n  Limits: Playback 0 - 192\n  Front Left: Playback 160 [83%] [0.00dB] [on]\n";
        assert_eq!(parse_raw(out), Some(160));
        assert_eq!(parse_raw("  Limits: Playback 0 - 192\n"), None);
        assert_eq!((parse_level("85\n"), parse_level("101"), parse_level("x")), (Some(85), None, None));
    }

    fn sget(raw: i32) -> String {
        format!("  Limits: Playback 0 - 192\n  Front Left: Playback {raw} [83%] [0.00dB] [on]\n")
    }

    fn temp_mixer(board: &str, tag: &str) -> Mixer {
        let dir = std::env::temp_dir().join(format!("lume-vol-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        Mixer { level_dir: dir.join("audio"), output_file: dir.join("output"), ..profile_mixer(board) }
    }

    #[test]
    fn level_of_the_active_output_on_the_user_scale() {
        let m = temp_mixer("ga36", "ga36");
        // no file: the old DAC while it holds an old level (154 = -4.5 dB is 85%) ...
        let read = |dac: i32, hp: Option<i32>| {
            move |ctl: &str| match ctl {
                "DAC" => Some(sget(dac)),
                _ => hp.map(sget),
            }
        };
        assert_eq!(m.level_with(read(154, Some(43))), Some(85));
        // ... else the Headphone's own position (43 = -30 dB is 20%), else 70%
        assert_eq!(m.level_with(read(160, Some(43))), Some(20));
        assert_eq!(m.level_with(read(160, None)), Some(70));
        // the saved file wins and the mixer is not needed
        m.save(35).unwrap();
        assert_eq!(std::fs::read_to_string(m.level_dir.join("level-speaker")).unwrap(), "35\n");
        assert_eq!(m.level_with(|_| None), Some(35));
        assert!(!m.level_dir.join(".level-speaker.tmp").exists());
        // R36S: each output its own file, chosen by the jack service's output file
        let r = temp_mixer("r36s", "r36s");
        r.save(70).unwrap();
        std::fs::write(&r.output_file, "headphones\n").unwrap();
        assert_eq!(r.output_name(), "headphones");
        r.save(30).unwrap();
        assert_eq!(r.level_with(|_| None), Some(30));
        std::fs::write(&r.output_file, "speaker\n").unwrap();
        assert_eq!(r.level_with(|_| None), Some(70));
        // the vm: amixer's own percent
        let vm = profile_mixer("vm");
        assert_eq!(vm.level_with(|_| Some(sget(160))), Some(83));
    }

    #[test]
    fn a_level_sets_the_control_the_switch_and_the_kept_control() {
        let ga36 = profile_mixer("ga36");
        let s = |v: &[&str]| v.iter().map(|w| w.to_string()).collect::<Vec<_>>();
        assert_eq!(ga36.amp.as_deref(), Some("Speaker"));
        assert_eq!(ga36.set_args(50), vec![s(&["Headphone", "51", "on"]), s(&["DAC", "160", "on"]), s(&["Speaker", "on"])]);
        assert_eq!(ga36.set_args(100), vec![s(&["Headphone", "63", "on"]), s(&["DAC", "160", "on"]), s(&["Speaker", "on"])]);
        assert_eq!(ga36.set_args(5)[2], s(&["Speaker", "on"]));
        // 0% is mute: the minimum and the switch off, the amplifier off too (7.5); the DAC
        // stays on at 0 dB
        assert_eq!(ga36.set_args(0), vec![s(&["Headphone", "0", "off"]), s(&["DAC", "160", "on"]), s(&["Speaker", "off"])]);
        // R36S: the Master on the scale, no switch, no amplifier line (until 7.1)
        assert_eq!(profile_mixer("r36s").set_args(70), vec![s(&["Master", "228"])]);
        assert_eq!(profile_mixer("vm").set_args(40), vec![s(&["Master", "40%"])]);
    }
}
