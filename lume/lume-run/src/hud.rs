//! The status bar over a game (lume-hud-actions D6, D7): lume-run reads a few small files
//! once a second while the bar is on and sends `LUME_HUD <text>` to RetroArch (patch 0012).
//! Off, nothing is read. The text is language-neutral, one group per field separated by `|`;
//! the widget draws the first word of each group (the label) in the theme's accent, the rest
//! in white, and a thin divider between groups (the user's choice, 2026-11-17):
//!
//! ```text
//! FPS 59.7|CPU 47% 1008|GPU 62% 38M|MEM 124/492 sw 20|BAT 74% 1.9W 2:40
//! ```
//!
//! `--` stands for a value that cannot be read and `--:--` for no estimate yet; charging,
//! `BAT 74% + 0:50` (the time until full). FPS: the game's frames per second, from the frame
//! counter of RetroArch's GET_STATUS between two samples. CPU: the use (mean of the cores) and
//! the clock in MHz. GPU: the use (else the clock in MHz) and the memory the game holds on it
//! in MiB (system RAM: the GPU has none of its own), from the game's DRM fdinfo. MEM is used/total and the swap only when in use, in MiB.
//!
//! Every path hangs from `root` (`/` on the console), so the tests use fake trees.

use std::collections::VecDeque;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// Seconds of samples before an estimate of the battery time
pub const MIN_ESTIMATE: Duration = Duration::from_secs(30);
/// The moving average of the current
pub const AVERAGE: Duration = Duration::from_secs(60);

#[derive(Debug, Clone, Copy, Default)]
struct Cpu {
    busy: u64,
    total: u64,
}

#[derive(Debug, Clone, Copy)]
struct Battery {
    capacity: Option<u32>,
    charging: bool,
    full: bool,
    voltage_uv: Option<i64>,
    current_ua: Option<i64>,
    charge_now: Option<i64>,
    charge_full: Option<i64>,
}

pub struct Hud {
    root: PathBuf,
    pid: libc::pid_t,
    last_cpu: Option<Cpu>,
    drm_fd: Option<Option<String>>,
    last_gpu: Option<(u64, f64)>,
    /// (seconds since the first sample, |current| in uA, capacity)
    samples: VecDeque<(f64, i64, Option<u32>)>,
    battery_dir: Option<Option<PathBuf>>,
    /// (frame counter, seconds) of the last sample and the FPS between the last two
    last_frames: Option<(u64, f64)>,
    fps: Option<f64>,
}

fn read(p: &Path) -> Option<String> {
    fs::read_to_string(p).ok().map(|s| s.trim().to_string())
}

fn read_num(p: &Path) -> Option<i64> {
    read(p)?.parse().ok()
}

impl Hud {
    pub fn new(root: &Path, pid: libc::pid_t) -> Hud {
        Hud {
            root: root.into(),
            pid,
            last_cpu: None,
            drm_fd: None,
            last_gpu: None,
            samples: VecDeque::new(),
            battery_dir: None,
            last_frames: None,
            fps: None,
        }
    }

    /// The game's frame counter now (RetroArch's GET_STATUS, patch 0004), before `sample`;
    /// None when it did not answer. The FPS is the frames between two samples over the time.
    pub fn frames(&mut self, frames: Option<u64>, elapsed: f64) {
        let Some(n) = frames else {
            self.last_frames = None;
            self.fps = None;
            return;
        };
        self.fps = match self.last_frames {
            Some((p, t)) if n >= p && elapsed > t => Some((n - p) as f64 / (elapsed - t)),
            _ => None,
        };
        self.last_frames = Some((n, elapsed));
    }

    fn path(&self, p: &str) -> PathBuf {
        self.root.join(p.trim_start_matches('/'))
    }

    fn cpu(&mut self) -> Option<u32> {
        let stat = read(&self.path("/proc/stat"))?;
        let line = stat.lines().find(|l| l.starts_with("cpu "))?;
        let v: Vec<u64> = line.split_whitespace().skip(1).filter_map(|x| x.parse().ok()).collect();
        if v.len() < 4 {
            return None;
        }
        let idle = v[3] + v.get(4).copied().unwrap_or(0);
        let total: u64 = v.iter().take(8).sum();
        let now = Cpu { busy: total - idle, total };
        let prev = self.last_cpu.replace(now)?;
        let dt = now.total.checked_sub(prev.total).filter(|d| *d > 0)?;
        Some(((now.busy.saturating_sub(prev.busy)) * 100 / dt).min(100) as u32)
    }

    fn mhz(&self) -> Option<u64> {
        let khz = read_num(&self.path("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"))?;
        Some(khz as u64 / 1000)
    }

    /// The fd of the game's DRM device, found once per game (a link to /dev/dri/*).
    fn find_drm_fd(&self) -> Option<String> {
        let dir = self.path(&format!("/proc/{}/fd", self.pid));
        let mut best = None;
        for e in fs::read_dir(dir).ok()?.flatten() {
            let Ok(target) = fs::read_link(e.path()) else { continue };
            let t = target.to_string_lossy();
            if t.starts_with("/dev/dri/") {
                let name = e.file_name().to_string_lossy().into_owned();
                // a fdinfo with drm-engine lines is the one that renders
                let info = read(&self.path(&format!("/proc/{}/fdinfo/{name}", self.pid))).unwrap_or_default();
                if info.contains("drm-engine-") {
                    return Some(name);
                }
                best.get_or_insert(name);
            }
        }
        best
    }

    /// The GPU's clock from devfreq (`/sys/class/devfreq/*gpu*/cur_freq`), in MHz: the field
    /// when the driver has no per-client time in the fdinfo (the GA36's `lima` before kernel
    /// patch 0035, J1 2026-11-17).
    fn gpu_mhz(&self) -> Option<u64> {
        let dir = self.path("/sys/class/devfreq");
        let mut entries: Vec<PathBuf> = fs::read_dir(dir).ok()?.flatten().map(|e| e.path()).collect();
        entries.sort();
        let gpu = entries.into_iter().find(|p| p.file_name().is_some_and(|n| n.to_string_lossy().contains("gpu")))?;
        Some(read_num(&gpu.join("cur_freq"))? as u64 / 1_000_000)
    }

    /// GPU % from the busiest engine's time (ns) in the game's fdinfo, over `elapsed` seconds.
    fn gpu(&mut self, elapsed: f64) -> Option<u32> {
        if self.drm_fd.is_none() {
            self.drm_fd = Some(self.find_drm_fd());
        }
        let fd = self.drm_fd.clone().flatten()?;
        let info = read(&self.path(&format!("/proc/{}/fdinfo/{fd}", self.pid)))?;
        // lima: drm-engine-gp/pp; panfrost: drm-engine-fragment/vertex-tiler
        let busiest = info
            .lines()
            .filter(|l| l.starts_with("drm-engine-") && !l.starts_with("drm-engine-capacity"))
            .filter_map(|l| l.split(':').nth(1)?.split_whitespace().next()?.parse::<u64>().ok())
            .max()?;
        let prev = self.last_gpu.replace((busiest, elapsed));
        let (b0, t0) = prev?;
        let dt = elapsed - t0;
        if dt <= 0.0 {
            return None;
        }
        let pct = (busiest.saturating_sub(b0)) as f64 / (dt * 1e9) * 100.0;
        Some(pct.round().clamp(0.0, 100.0) as u32)
    }

    /// The memory the game holds on the GPU, in MiB: `drm-resident-memory` of its DRM file
    /// (else `drm-total-memory`), printed by panfrost and by lima with kernel patch 0035. On
    /// these consoles the GPU has no memory of its own: these are buffers in the system RAM.
    fn gpu_mem(&mut self) -> Option<u64> {
        if self.drm_fd.is_none() {
            self.drm_fd = Some(self.find_drm_fd());
        }
        let fd = self.drm_fd.clone().flatten()?;
        let info = read(&self.path(&format!("/proc/{}/fdinfo/{fd}", self.pid)))?;
        let value = |key: &str| -> Option<u64> {
            let line = info.lines().find(|l| l.starts_with(key))?;
            let mut f = line.split(':').nth(1)?.split_whitespace();
            let n: u64 = f.next()?.parse().ok()?;
            Some(match f.next().unwrap_or("") {
                "KiB" => n / 1024,
                "MiB" => n,
                "GiB" => n * 1024,
                _ => n / (1024 * 1024),
            })
        };
        value("drm-resident-memory:").or_else(|| value("drm-total-memory:"))
    }

    fn mem(&self) -> Option<(u64, u64, u64)> {
        let text = read(&self.path("/proc/meminfo"))?;
        let get = |k: &str| -> Option<u64> {
            text.lines().find(|l| l.starts_with(k))?.split_whitespace().nth(1)?.parse().ok()
        };
        let total = get("MemTotal:")?;
        let avail = get("MemAvailable:")?;
        let swap = get("SwapTotal:").unwrap_or(0).saturating_sub(get("SwapFree:").unwrap_or(0));
        Some(((total - avail.min(total)) / 1024, total / 1024, swap / 1024))
    }

    fn find_battery(&self) -> Option<PathBuf> {
        let dir = self.path("/sys/class/power_supply");
        let mut entries: Vec<PathBuf> = fs::read_dir(dir).ok()?.flatten().map(|e| e.path()).collect();
        entries.sort();
        entries.into_iter().find(|p| read(&p.join("type")).as_deref() == Some("Battery"))
    }

    fn battery(&mut self) -> Option<Battery> {
        if self.battery_dir.is_none() {
            self.battery_dir = Some(self.find_battery());
        }
        let d = self.battery_dir.clone().flatten()?;
        let status = read(&d.join("status")).unwrap_or_default();
        Some(Battery {
            capacity: read_num(&d.join("capacity")).map(|c| c.clamp(0, 100) as u32),
            charging: status == "Charging",
            full: status == "Full",
            voltage_uv: read_num(&d.join("voltage_now")),
            current_ua: read_num(&d.join("current_now")),
            charge_now: read_num(&d.join("charge_now")),
            // the AXP223 of the GA36 has only the design capacity (J1): the estimate from
            // the first 30 s, with the error of a worn battery
            charge_full: read_num(&d.join("charge_full")).or_else(|| read_num(&d.join("charge_full_design"))),
        })
    }

    /// The battery field; `elapsed` is seconds since this bar started (the average and the
    /// estimate start over with each game, D7).
    fn battery_text(&mut self, elapsed: f64) -> String {
        let Some(b) = self.battery() else { return "BAT --".into() };
        let pct = b.capacity.map(|c| format!("{c}%")).unwrap_or_else(|| "--".into());
        let watts = match (b.voltage_uv, b.current_ua) {
            (Some(v), Some(i)) => format!("{:.1}W", (v as f64 * i as f64).abs() / 1e12),
            _ => "--W".into(),
        };
        // the sign of current_now differs between drivers (AXP223, RK817): the status
        // decides the direction, the size is the same
        if let Some(i) = b.current_ua {
            self.samples.push_back((elapsed, i.abs(), b.capacity));
        } else {
            self.samples.push_back((elapsed, 0, b.capacity));
        }
        while self.samples.front().is_some_and(|(t, _, _)| elapsed - t > AVERAGE.as_secs_f64() * 5.0) {
            self.samples.pop_front();
        }
        let window: Vec<&(f64, i64, Option<u32>)> =
            self.samples.iter().filter(|(t, _, _)| elapsed - t <= AVERAGE.as_secs_f64()).collect();
        let first = self.samples.front().map(|s| s.0).unwrap_or(elapsed);
        let enough = elapsed - first >= MIN_ESTIMATE.as_secs_f64();
        let avg_ua = if window.is_empty() { 0 } else { window.iter().map(|s| s.1).sum::<i64>() / window.len() as i64 };
        let hours = if !enough || b.full {
            None
        } else if avg_ua > 0 && (b.charge_now.is_some() || b.charge_full.is_some()) {
            let now = b.charge_now.or_else(|| Some(b.charge_full? * b.capacity? as i64 / 100));
            let left = if b.charging { b.charge_full.zip(now).map(|(f, n)| f - n) } else { now };
            left.map(|l| l.max(0) as f64 / avg_ua as f64)
        } else {
            // only the percent: its fall (or rise) over the samples
            let first = self.samples.iter().find_map(|(t, _, c)| c.map(|c| (*t, c)));
            match (first, b.capacity) {
                (Some((t0, c0)), Some(c1)) if elapsed > t0 => {
                    let rate = (c1 as f64 - c0 as f64) / ((elapsed - t0) / 3600.0); // % per hour
                    if b.charging && rate > 0.0 {
                        Some((100 - c1) as f64 / rate)
                    } else if !b.charging && rate < 0.0 {
                        Some(c1 as f64 / -rate)
                    } else {
                        None
                    }
                }
                _ => None,
            }
        };
        let time = match hours {
            Some(h) if h.is_finite() && h < 100.0 => {
                let m = (h * 60.0).round() as u64;
                format!("{}:{:02}", m / 60, m % 60)
            }
            _ => "--:--".into(),
        };
        // compact (the user's choice, 2026-11-17): full, or charging at 100% (the AXP223 keeps
        // "Charging" there), shows no time; charging without an estimate yet, only "+"
        if b.full || (b.charging && b.capacity == Some(100)) {
            format!("BAT {pct}{}", if b.charging { " +" } else { "" })
        } else if b.charging {
            if time == "--:--" { format!("BAT {pct} +") } else { format!("BAT {pct} + {time}") }
        } else {
            format!("BAT {pct} {watts} {time}")
        }
    }

    /// One sample: the text of the bar. `elapsed` is seconds since the bar started.
    pub fn sample(&mut self, elapsed: f64) -> String {
        // compact (the user's choice, 2026-11-17): no units where they are obvious (the
        // clocks in MHz, the memory in MiB), the swap only when in use
        let cpu = self.cpu().map(|c| format!("{c}%")).unwrap_or_else(|| "--".into());
        let cpu = match self.mhz() {
            Some(m) => format!("{cpu} {m}"),
            None => cpu,
        };
        // the use when the driver reports it (panfrost), else the clock (lima), else --
        let gpu = match self.gpu(elapsed) {
            Some(g) => format!("{g}%"),
            None => self.gpu_mhz().map(|m| m.to_string()).unwrap_or_else(|| "--".into()),
        };
        // the memory the game holds on the GPU (the user, 2026-11-17: to find the bottleneck);
        // with an M, as the use and the clock have no unit
        let gpu = match self.gpu_mem() {
            Some(m) => format!("{gpu} {m}M"),
            None => gpu,
        };
        let mem = self
            .mem()
            .map(|(u, t, s)| if s > 0 { format!("{u}/{t} sw {s}") } else { format!("{u}/{t}") })
            .unwrap_or_else(|| "--".into());
        let bat = self.battery_text(elapsed);
        // the FPS first (the user, 2026-11-17: "muito importante"); one decimal, as RetroArch's
        let fps = self.fps.map(|f| format!("{f:.1}")).unwrap_or_else(|| "--".into());
        format!("FPS {fps}|CPU {cpu}|GPU {gpu}|MEM {mem}|{bat}")
    }
}

/// panfrost reports the GPU time per client only with its profiling on (D6): the sysfs
/// switch of every panfrost device under `root`, written when the bar shows and hides.
pub fn panfrost_profiling(root: &Path, on: bool) {
    let dir = root.join("sys/bus/platform/drivers/panfrost");
    let Ok(entries) = fs::read_dir(dir) else { return };
    for e in entries.flatten() {
        let p = e.path().join("profiling");
        if p.exists() {
            let _ = fs::write(&p, if on { "1" } else { "0" });
        }
    }
}

/// The bar's state across games (`/run/r36os/hud`, D6): shown when the file says 1.
pub fn load_shown(file: &Path) -> bool {
    read(file).as_deref() == Some("1")
}

pub fn save_shown(file: &Path, shown: bool) {
    let _ = fs::write(file, if shown { "1\n" } else { "0\n" });
}

#[cfg(test)]
mod tests {
    use super::*;

    fn tree(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-hud-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&d);
        fs::create_dir_all(d.join("proc/42/fd")).unwrap();
        fs::create_dir_all(d.join("proc/42/fdinfo")).unwrap();
        fs::create_dir_all(d.join("sys/devices/system/cpu/cpufreq/policy0")).unwrap();
        fs::write(d.join("sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq"), "1008000\n").unwrap();
        fs::write(
            d.join("proc/meminfo"),
            "MemTotal:        1030144 kB\nMemFree:  1 kB\nMemAvailable:     903168 kB\nSwapTotal:  515072 kB\nSwapFree: 310272 kB\n",
        )
        .unwrap();
        d
    }

    fn stat(d: &Path, busy: u64, idle: u64) {
        fs::write(d.join("proc/stat"), format!("cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\ncpu0 1 2 3 4\n")).unwrap();
    }

    fn gpu(d: &Path, engines: &[(&str, u64)]) {
        let link = d.join("proc/42/fd/7");
        let _ = fs::remove_file(&link);
        std::os::unix::fs::symlink("/dev/dri/card0", &link).unwrap();
        let mut s = String::from("pos:\t0\ndrm-driver:\tlima\n");
        for (e, ns) in engines {
            s.push_str(&format!("drm-engine-{e}:\t{ns} ns\n"));
        }
        fs::write(d.join("proc/42/fdinfo/7"), s).unwrap();
    }

    fn battery(d: &Path, status: &str, cap: u32, uv: i64, ua: i64, charge: Option<(i64, i64)>) {
        let b = d.join("sys/class/power_supply/battery");
        fs::create_dir_all(&b).unwrap();
        fs::create_dir_all(d.join("sys/class/power_supply/ac")).unwrap();
        fs::write(d.join("sys/class/power_supply/ac/type"), "Mains\n").unwrap();
        fs::write(b.join("type"), "Battery\n").unwrap();
        fs::write(b.join("status"), format!("{status}\n")).unwrap();
        fs::write(b.join("capacity"), format!("{cap}\n")).unwrap();
        fs::write(b.join("voltage_now"), format!("{uv}\n")).unwrap();
        fs::write(b.join("current_now"), format!("{ua}\n")).unwrap();
        let _ = fs::remove_file(b.join("charge_now"));
        let _ = fs::remove_file(b.join("charge_full"));
        if let Some((now, full)) = charge {
            fs::write(b.join("charge_now"), format!("{now}\n")).unwrap();
            fs::write(b.join("charge_full"), format!("{full}\n")).unwrap();
        }
    }

    #[test]
    fn cpu_gpu_mem_from_lima() {
        let d = tree("lima");
        stat(&d, 100, 900);
        gpu(&d, &[("gp", 0), ("pp", 0)]);
        let mut h = Hud::new(&d, 42);
        // the first sample has no difference yet
        h.frames(Some(1000), 0.0);
        assert_eq!(h.sample(0.0), "FPS --|CPU -- 1008|GPU --|MEM 124/1006 sw 200|BAT --");
        stat(&d, 147, 953); // 47 busy of 100
        gpu(&d, &[("gp", 100_000_000), ("pp", 620_000_000)]);
        h.frames(Some(1060), 1.0);
        assert_eq!(h.sample(1.0), "FPS 60.0|CPU 47% 1008|GPU 62%|MEM 124/1006 sw 200|BAT --");
    }

    #[test]
    fn gpu_memory_from_the_fdinfo() {
        let d = tree("gpumem");
        stat(&d, 0, 0);
        gpu(&d, &[("gp", 0), ("pp", 0)]);
        let info = fs::read_to_string(d.join("proc/42/fdinfo/7")).unwrap();
        // the kernel prints KiB below 1 MiB of rounding and MiB above (drm_print_memory_stats)
        fs::write(d.join("proc/42/fdinfo/7"), format!("{info}drm-total-memory:\t40 MiB\ndrm-resident-memory:\t39424 KiB\n")).unwrap();
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        gpu(&d, &[("gp", 100_000_000), ("pp", 500_000_000)]);
        let info = fs::read_to_string(d.join("proc/42/fdinfo/7")).unwrap();
        fs::write(d.join("proc/42/fdinfo/7"), format!("{info}drm-total-memory:\t40 MiB\ndrm-resident-memory:\t39424 KiB\n")).unwrap();
        assert!(h.sample(1.0).contains("|GPU 50% 38M|"), "{}", h.sample(1.0));
        // only the total (no status callback): that one
        let d2 = tree("gpumem-total");
        gpu(&d2, &[("gp", 0)]);
        let info = fs::read_to_string(d2.join("proc/42/fdinfo/7")).unwrap();
        fs::write(d2.join("proc/42/fdinfo/7"), format!("{info}drm-total-memory:\t12 MiB\n")).unwrap();
        let mut h2 = Hud::new(&d2, 42);
        assert!(h2.sample(0.0).contains(" 12M|"), "{}", h2.sample(0.0));
    }

    #[test]
    fn fps_from_the_frame_counter() {
        let d = tree("fps");
        let mut h = Hud::new(&d, 42);
        h.frames(Some(0), 0.0);
        h.frames(Some(54), 2.0);
        assert!(h.sample(2.0).starts_with("FPS 27.0|"), "{}", h.sample(2.0));
        // RetroArch silent: no value, and the next answer starts the count again
        h.frames(None, 3.0);
        assert!(h.sample(3.0).starts_with("FPS --|"));
        h.frames(Some(200), 4.0);
        assert!(h.sample(4.0).starts_with("FPS --|"));
        h.frames(Some(260), 5.0);
        assert!(h.sample(5.0).starts_with("FPS 60.0|"));
        // a new game resets the counter: no negative FPS
        h.frames(Some(10), 6.0);
        assert!(h.sample(6.0).starts_with("FPS --|"));
    }

    #[test]
    fn gpu_from_panfrost_and_without_drm() {
        let d = tree("panfrost");
        stat(&d, 0, 0);
        gpu(&d, &[("fragment", 0), ("vertex-tiler", 0)]);
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        gpu(&d, &[("fragment", 250_000_000), ("vertex-tiler", 500_000_000)]);
        assert!(h.sample(2.0).contains("GPU 25%"), "the busiest engine over 2 s");
        let d2 = tree("nodrm");
        let mut h2 = Hud::new(&d2, 42);
        h2.sample(0.0);
        assert!(h2.sample(1.0).contains("GPU --"));
        // no cpufreq (the vm): the clock is --
        fs::remove_file(d2.join("sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq")).unwrap();
        assert!(h2.sample(2.0).starts_with("FPS --|CPU --|"), "no clock: only the use");
    }

    #[test]
    fn battery_discharging_with_charge() {
        let d = tree("bat1");
        // 3.8 V, 500 mA: 1.9 W; 1000 mAh left of 2000 at 500 mA: 2:00
        battery(&d, "Discharging", 50, 3_800_000, -500_000, Some((1_000_000, 2_000_000)));
        let mut h = Hud::new(&d, 42);
        assert!(h.sample(0.0).ends_with("BAT 50% 1.9W --:--"), "{}", h.sample(0.0));
        assert!(h.sample(20.0).ends_with("--:--"), "under 30 s of samples");
        assert!(h.sample(31.0).ends_with("BAT 50% 1.9W 2:00"), "{}", h.sample(31.0));
    }

    #[test]
    fn battery_charging_and_without_charge_full() {
        let d = tree("bat2");
        // charging (RK817 reports a positive current): time until full, 1000 of 2000 at 1 A
        battery(&d, "Charging", 50, 4_000_000, 1_000_000, Some((1_000_000, 2_000_000)));
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        assert!(h.sample(40.0).ends_with("BAT 50% + 1:00"), "{}", h.sample(40.0));
        // at 100% the AXP223 keeps "Charging": no time, only the mark (J2, "+ 0:00" before)
        let d = tree("bat100");
        battery(&d, "Charging", 100, 4_250_000, 100_000, None);
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        assert!(h.sample(60.0).ends_with("BAT 100% +"), "{}", h.sample(60.0));
        // only the percent: 80% falling 1% per minute -> 80 minutes
        let d = tree("bat3");
        battery(&d, "Discharging", 80, 3_700_000, 0, None);
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        battery(&d, "Discharging", 79, 3_700_000, 0, None);
        assert!(h.sample(60.0).ends_with("BAT 79% 0.0W 1:19"), "{}", h.sample(60.0));
    }

    #[test]
    fn ga36_lima_clock_and_design_capacity() {
        // J1 (2026-11-17): no drm-engine lines from lima, the devfreq clock instead; the AXP223
        // has only charge_full_design, so the estimate starts from the capacity percent
        let d = tree("ga36");
        let link = d.join("proc/42/fd/5");
        std::os::unix::fs::symlink("/dev/dri/card0", &link).unwrap();
        fs::write(d.join("proc/42/fdinfo/5"), "pos:\t0\nflags:\t0400002\n").unwrap();
        fs::create_dir_all(d.join("sys/class/devfreq/1c40000.gpu")).unwrap();
        fs::write(d.join("sys/class/devfreq/1c40000.gpu/cur_freq"), "240000000\n").unwrap();
        battery(&d, "Discharging", 50, 4_000_000, -500_000, None);
        fs::write(d.join("sys/class/power_supply/battery/charge_full_design"), "3000000\n").unwrap();
        let mut h = Hud::new(&d, 42);
        h.sample(0.0);
        let s = h.sample(31.0);
        assert!(s.contains("GPU 240|"), "{s}");
        // 50% of 3000 mAh at 500 mA: 3:00
        assert!(s.ends_with("BAT 50% 2.0W 3:00"), "{s}");
    }

    #[test]
    fn shown_state_and_profiling() {
        let d = tree("state");
        let f = d.join("hud");
        assert!(!load_shown(&f), "no file: hidden (the boot)");
        save_shown(&f, true);
        assert!(load_shown(&f));
        save_shown(&f, false);
        assert!(!load_shown(&f));
        let p = d.join("sys/bus/platform/drivers/panfrost/ff400000.gpu");
        fs::create_dir_all(&p).unwrap();
        fs::write(p.join("profiling"), "0").unwrap();
        panfrost_profiling(&d, true);
        assert_eq!(fs::read_to_string(p.join("profiling")).unwrap(), "1");
        panfrost_profiling(&d, false);
        assert_eq!(fs::read_to_string(p.join("profiling")).unwrap(), "0");
    }
}
