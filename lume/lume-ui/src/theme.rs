//! Declarative themes (lume-launcher D11, docs/lume-launcher/formato-de-tema.md): a TOML file
//! with tokens (colors, shapes, sizes), an optional parent (`extends`) and feature flags. The
//! engine never knows a theme by name. Sizes are in `em`, 1/40 of the screen width (16 px at
//! 640x480), so layouts follow the resolution.
//!
//! ```toml
//! [theme]
//! id = "material-light"
//! extends = "material-dark"     # only what changes
//! [tokens]
//! bg = "#FEF7FF"
//! [features]
//! lite = false                  # true forces the lite mode
//! ```
//!
//! Themes live in /usr/share/lume/themes/<id>/theme.toml and on the card in
//! ROMS/system/lume/themes/<id>/theme.toml (the card wins). A card theme may bring
//! icons/<system>.png for the Dock; the distro brings none. An invalid theme is logged and
//! the default one is used.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::canvas::Color;

pub const DEFAULT_THEME: &str = "material-dark";

const DEFAULTS: &str = r##"
bg = "#14161a"
fg = "#f0f0f0"
muted = "#9aa0aa"
accent = "#4cc2ff"
accent_fg = "#001018"
overlay = "#000000aa"
radius_icon = 1.4
radius_tile = 0.5
radius_panel = 1.4
radius_item = 1.6
cols = 4
rows = 2
icon = 5.8
dock_gap = 0.6
mag_peak = 1.5
mag_base = 0.8
mag_spread = 0.8
dock_top = 0.45
icon_bg = "#2a2f38"
icon_fg = "#ffffff"
icon_sel_bg = "#2a2f38"
icon_sel_fg = "#ffffff"
tile_bg = "#ffffff18"
tile_bg_sel = "#ffffff30"
tile_bg_opaque = "#22262c"
panel_bg = "#1b1f25e6"
panel_bg_opaque = "#1b1f25"
sel_bg = "#4cc2ff"
sel_fg = "#001018"
toast_bg = "#4cc2ff"
toast_fg = "#001018"
label_px = 1.25
title_px = 1.6
anim_ms = 200
cache_bytes = 4194304
"##;

#[derive(Debug, Clone, PartialEq)]
pub struct Theme {
    pub id: String,
    pub colors: BTreeMap<String, Color>,
    pub nums: BTreeMap<String, f64>,
    pub lite: bool,
    /// Folder of the theme (for icons/<system>.png)
    pub dir: Option<PathBuf>,
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ThemeFile {
    theme: ThemeHead,
    #[serde(default)]
    tokens: toml::Table,
    #[serde(default)]
    features: Features,
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ThemeHead {
    id: String,
    #[serde(default)]
    extends: Option<String>,
}

#[derive(Debug, Default, Clone, Copy, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Features {
    #[serde(default)]
    lite: bool,
}

fn defaults() -> toml::Table {
    toml::from_str(DEFAULTS).expect("default tokens parse")
}

impl Theme {
    pub fn color(&self, k: &str) -> Color {
        self.colors.get(k).copied().unwrap_or(Color::rgb(255, 0, 255))
    }

    pub fn num(&self, k: &str) -> f64 {
        self.nums.get(k).copied().unwrap_or(0.0)
    }

    /// Pixels of a size token for a screen `width` (1 em = width / 40).
    pub fn em(&self, k: &str, width: i32) -> i32 {
        (self.num(k) * width as f64 / 40.0).round() as i32
    }

    /// The theme as drawn with the lite mode: no animation and no transparency (each
    /// translucent color becomes its opaque variant, or itself without alpha).
    pub fn lite(&self) -> Theme {
        let mut t = self.clone();
        t.lite = true;
        t.nums.insert("anim_ms".into(), 0.0);
        let keys: Vec<String> = t.colors.keys().cloned().collect();
        for k in keys {
            let opaque = self.colors.get(&format!("{k}_opaque")).copied();
            let c = t.colors[&k];
            if c.a < 255 {
                t.colors.insert(k, opaque.unwrap_or(c.opaque()));
            }
        }
        t
    }

    fn from_table(id: &str, table: &toml::Table, lite: bool, dir: Option<PathBuf>) -> Result<Theme, String> {
        let base = defaults();
        let mut colors = BTreeMap::new();
        let mut nums = BTreeMap::new();
        for (k, v) in table {
            let Some(default) = base.get(k) else {
                return Err(format!("unknown token {k}"));
            };
            match (default, v) {
                (toml::Value::String(_), toml::Value::String(s)) => {
                    colors.insert(k.clone(), Color::parse(s).ok_or_else(|| format!("{k}: bad color {s:?}"))?);
                }
                (toml::Value::Integer(_) | toml::Value::Float(_), toml::Value::Integer(i)) => {
                    nums.insert(k.clone(), *i as f64);
                }
                (toml::Value::Integer(_) | toml::Value::Float(_), toml::Value::Float(f)) => {
                    nums.insert(k.clone(), *f);
                }
                _ => return Err(format!("{k}: wrong type")),
            }
        }
        for (k, n) in &nums {
            if *n < 0.0 || (["cols", "rows"].contains(&k.as_str()) && !(1.0..=8.0).contains(n)) {
                return Err(format!("{k}: out of range"));
            }
        }
        Ok(Theme { id: id.to_string(), colors, nums, lite, dir })
    }
}

/// Where themes are looked up: the card first, then the image.
pub struct Themes {
    pub dirs: Vec<PathBuf>,
}

impl Themes {
    pub fn new(card: &Path, share: &Path) -> Themes {
        Themes { dirs: vec![card.join("themes"), share.join("themes")] }
    }

    fn file(&self, id: &str) -> Option<PathBuf> {
        if id.is_empty() || id.contains(['/', '.']) {
            return None;
        }
        self.dirs.iter().map(|d| d.join(id).join("theme.toml")).find(|p| p.exists())
    }

    /// Every theme id available, sorted.
    pub fn list(&self) -> Vec<String> {
        let mut ids: Vec<String> = self
            .dirs
            .iter()
            .filter_map(|d| std::fs::read_dir(d).ok())
            .flatten()
            .flatten()
            .filter(|e| e.path().join("theme.toml").exists())
            .map(|e| e.file_name().to_string_lossy().into_owned())
            .collect();
        ids.sort();
        ids.dedup();
        ids
    }

    fn resolve(&self, id: &str, depth: u32) -> Result<(toml::Table, bool, PathBuf), String> {
        if depth > 8 {
            return Err("circular extends".into());
        }
        let path = self.file(id).ok_or_else(|| format!("theme {id} not found"))?;
        let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let file: ThemeFile = toml::from_str(&text).map_err(|e| format!("{}: {}", path.display(), e.message()))?;
        if file.theme.id != id {
            return Err(format!("{}: id {} does not match the folder", path.display(), file.theme.id));
        }
        let (mut table, mut lite) = match &file.theme.extends {
            Some(parent) => {
                let (t, l, _) = self.resolve(parent, depth + 1)?;
                (t, l)
            }
            None => (defaults(), false),
        };
        for (k, v) in file.tokens {
            table.insert(k, v);
        }
        lite |= file.features.lite;
        Ok((table, lite, path.parent().unwrap().to_path_buf()))
    }

    pub fn load(&self, id: &str) -> Result<Theme, String> {
        let (table, lite, dir) = self.resolve(id, 0)?;
        Theme::from_table(id, &table, lite, Some(dir))
    }

    /// The theme `id`, or the default one when it is invalid (logged), or the built-in
    /// defaults when even that one is missing.
    pub fn load_or_default(&self, id: &str) -> Theme {
        match self.load(id) {
            Ok(t) => t,
            Err(e) => {
                lume_core::log::line("lume-ui", &format!("theme {id} refused: {e}; using {DEFAULT_THEME}"));
                self.load(DEFAULT_THEME)
                    .unwrap_or_else(|_| Theme::from_table("builtin", &defaults(), false, None).expect("defaults are valid"))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn image_themes() -> Themes {
        let share = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../rootfs/overlay/usr/share/lume");
        Themes { dirs: vec![share.join("themes")] }
    }

    #[test]
    fn material_themes_load_and_inherit() {
        let t = image_themes();
        assert_eq!(t.list(), ["material-dark", "material-light"]);
        let dark = t.load("material-dark").unwrap();
        let light = t.load("material-light").unwrap();
        assert_eq!(dark.color("bg"), Color::rgb(0x14, 0x12, 0x18));
        assert_eq!(light.color("bg"), Color::rgb(0xFE, 0xF7, 0xFF));
        // shapes and positions come from the dark theme
        assert_eq!(light.num("mag_peak"), dark.num("mag_peak"));
        assert_eq!(light.num("cols"), 4.0);
        assert_eq!(dark.em("icon", 640), 96);
    }

    #[test]
    fn invalid_theme_falls_back_to_the_default() {
        let dir = std::env::temp_dir().join(format!("lume-themes-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        for (id, body) in [
            ("bad-color", "[theme]\nid = \"bad-color\"\nextends = \"material-dark\"\n[tokens]\nbg = \"red\"\n"),
            ("unknown", "[theme]\nid = \"unknown\"\n[tokens]\nsparkles = 3\n"),
            ("loop", "[theme]\nid = \"loop\"\nextends = \"loop\"\n"),
            ("cols", "[theme]\nid = \"cols\"\n[tokens]\ncols = 40\n"),
        ] {
            std::fs::create_dir_all(dir.join(id)).unwrap();
            std::fs::write(dir.join(id).join("theme.toml"), body).unwrap();
        }
        let mut t = image_themes();
        t.dirs.insert(0, dir);
        for id in ["bad-color", "unknown", "loop", "cols", "missing", "../x"] {
            assert!(t.load(id).is_err(), "{id}");
            assert_eq!(t.load_or_default(id).id, DEFAULT_THEME, "{id}");
        }
    }

    #[test]
    fn lite_mode_has_no_animation_or_transparency() {
        let base = Theme::from_table("x", &defaults(), false, None).unwrap();
        assert!(base.color("tile_bg").a < 255 && base.num("anim_ms") > 0.0);
        let lite = base.lite();
        assert_eq!(lite.num("anim_ms"), 0.0);
        assert!(lite.colors.values().all(|c| c.a == 255));
        // the declared opaque variant is used
        assert_eq!(lite.color("tile_bg"), base.color("tile_bg_opaque"));
    }
}
