//! Launcher settings (`ROMS/system/lume/settings.toml`, lume-launcher D6, D10): language,
//! theme, the display options (the battery's percent). Unknown or invalid values fall back to
//! the default, so an old or hand-edited file never stops the launcher.

use std::io;
use std::path::Path;

use serde::{Deserialize, Serialize};

pub const LANGUAGES: &[&str] = &["en", "pt", "es"];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub language: String,
    /// theme id; empty: the default theme of the image (themes/base.toml)
    pub theme: String,
    /// Display: the battery's percent next to its icon in the status bar
    pub battery_percent: bool,
    /// Wi-Fi: SSH over the Wi-Fi network, key only (lume-launcher D18); off from the factory.
    /// The root service lume-ssh-wifi reads it from this file.
    pub ssh_wifi: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Settings { language: "en".into(), theme: String::new(), battery_percent: true, ssh_wifi: false }
    }
}

impl Settings {
    pub fn load(path: &Path) -> Settings {
        let mut s: Settings = std::fs::read_to_string(path)
            .ok()
            .and_then(|t| toml::from_str(&t).ok())
            .unwrap_or_default();
        if !LANGUAGES.contains(&s.language.as_str()) {
            s.language = Settings::default().language;
        }
        s
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        crate::atomic::write(path, toml::to_string(self).expect("settings serialize").as_bytes())
    }
}

/// RetroArch `user_language` value of a launcher language (RETRO_LANGUAGE_*: 0 English,
/// 3 Spanish, 7 Portuguese of Brazil), the same mapping as `lume_tool.lang`.
pub fn retroarch_language(lang: &str) -> u32 {
    match lang {
        "es" => 3,
        "pt" => 7,
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_fallbacks() {
        let p = std::env::temp_dir().join(format!("lume-settings-{}.toml", std::process::id()));
        let s = Settings { language: "es".into(), ..Default::default() };
        s.save(&p).unwrap();
        assert_eq!(Settings::load(&p), s);
        // a file from before the lite mode was removed still loads
        std::fs::write(&p, "language = \"pt\"\nlite = true\n").unwrap();
        assert_eq!(Settings::load(&p).language, "pt");
        // the battery percent: on unless the file says otherwise
        assert!(Settings::load(&p).battery_percent);
        std::fs::write(&p, "battery_percent = false\n").unwrap();
        assert!(!Settings::load(&p).battery_percent);
        // SSH over Wi-Fi: off unless the file says otherwise; saved as the service reads it
        assert!(!Settings::load(&p).ssh_wifi);
        Settings { ssh_wifi: true, ..Default::default() }.save(&p).unwrap();
        assert!(std::fs::read_to_string(&p).unwrap().lines().any(|l| l == "ssh_wifi = true"));
        std::fs::write(&p, "language = \"xx\"\nvolume = 250\nunknown = 1\n").unwrap();
        let l = Settings::load(&p);
        assert_eq!(l.language, "en");
        // the old volume and brightness fields nobody read are ignored, and not written back
        std::fs::write(&p, "volume = 70\nbrightness = 40\n").unwrap();
        Settings::load(&p).save(&p).unwrap();
        let text = std::fs::read_to_string(&p).unwrap();
        assert!(!text.contains("volume") && !text.contains("brightness"));
        std::fs::write(&p, "not toml [").unwrap();
        assert_eq!(Settings::load(&p), Settings::default());
    }
}
