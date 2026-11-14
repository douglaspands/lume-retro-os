//! Launcher settings (`ROMS/system/lume/settings.toml`, lume-launcher D6, D10): language,
//! theme, lite mode, preferred volume and brightness. Unknown or invalid values fall back to
//! the default, so an old or hand-edited file never stops the launcher.

use std::io;
use std::path::Path;

use serde::{Deserialize, Serialize};

pub const LANGUAGES: &[&str] = &["en", "pt", "es"];

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct Settings {
    pub language: String,
    pub theme: String,
    pub lite: bool,
    /// 0-100, `None` keeps the mixer as it is
    pub volume: Option<u8>,
    /// 0-100, `None` keeps the backlight as it is
    pub brightness: Option<u8>,
}

impl Default for Settings {
    fn default() -> Self {
        Settings { language: "en".into(), theme: "material-dark".into(), lite: false, volume: None, brightness: None }
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
        s.volume = s.volume.map(|v| v.min(100));
        s.brightness = s.brightness.map(|v| v.min(100));
        s
    }

    pub fn save(&self, path: &Path) -> io::Result<()> {
        crate::atomic::write(path, toml::to_string(self).expect("settings serialize").as_bytes())
    }
}

/// RetroArch `user_language` value of a launcher language (RETRO_LANGUAGE_*: 0 English,
/// 3 Spanish, 7 Portuguese of Brazil), the same mapping as `r36os.lang`.
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
        let s = Settings { language: "es".into(), lite: true, volume: Some(70), ..Default::default() };
        s.save(&p).unwrap();
        assert_eq!(Settings::load(&p), s);
        std::fs::write(&p, "language = \"xx\"\nvolume = 250\nunknown = 1\n").unwrap();
        let l = Settings::load(&p);
        assert_eq!(l.language, "en");
        assert_eq!(l.volume, Some(100));
        std::fs::write(&p, "not toml [").unwrap();
        assert_eq!(Settings::load(&p), Settings::default());
    }
}
