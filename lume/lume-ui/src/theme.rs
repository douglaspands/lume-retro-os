//! Declarative themes (lume-launcher D11, docs/lume-launcher/formato-de-tema.md): a TOML file
//! with a display name, tokens (colors, shapes, sizes) and an optional parent (`extends`).
//! The engine knows no theme and no token value: the image brings
//! themes/base.toml, with the default theme and the base value of every token (which also
//! says which tokens exist and their types). A new theme is only a folder with a file.
//!
//! ```toml
//! [theme]
//! id = "material-light"
//! name = { en = "Light", pt = "Claro", es = "Claro" }
//! extends = "material-dark"     # only what changes
//! [tokens]
//! bg = "#FEF7FF"
//! ```
//!
//! Themes live in /usr/share/lume/themes/<id>/theme.toml and on the card in
//! ROMS/system/lume/themes/<id>/theme.toml (the card wins). A card theme may bring
//! icons/<system>.png for the Dock; the distro brings none. An invalid theme is logged and
//! the default one is used.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use crate::canvas::Color;

/// The base of every theme, in the image's themes folder.
pub const BASE_FILE: &str = "base.toml";

#[derive(Debug, Clone, PartialEq)]
pub struct Theme {
    pub id: String,
    pub colors: BTreeMap<String, Color>,
    pub nums: BTreeMap<String, f64>,
    /// Folder of the theme (for icons/<system>.png)
    pub dir: Option<PathBuf>,
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ThemeFile {
    theme: ThemeHead,
    #[serde(default)]
    tokens: toml::Table,
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct ThemeHead {
    id: String,
    /// display name per language (en, pt, es); missing: the id
    #[serde(default)]
    name: BTreeMap<String, String>,
    #[serde(default)]
    extends: Option<String>,
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct BaseFile {
    /// id of the theme used when none is chosen or the chosen one is invalid
    default: String,
    tokens: toml::Table,
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

    /// A theme from its resolved tokens, checked against the base (the known tokens and
    /// their types).
    fn from_table(id: &str, base: &toml::Table, table: &toml::Table, dir: Option<PathBuf>) -> Result<Theme, String> {
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
        Ok(Theme { id: id.to_string(), colors, nums, dir })
    }
}

/// Where themes are looked up (the card first, then the image) and the image's base.
pub struct Themes {
    pub dirs: Vec<PathBuf>,
    /// base value of every token (themes/base.toml of the image)
    pub base: toml::Table,
    /// the default theme id (themes/base.toml of the image)
    pub default: String,
}

impl Themes {
    pub fn new(card: &Path, share: &Path) -> Themes {
        Themes::from_dirs(vec![card.join("themes"), share.join("themes")], &share.join("themes").join(BASE_FILE))
    }

    /// Themes in `dirs`, with the base file `base`. Without a valid base (a broken image)
    /// the error is logged: no token is known and every color shows as magenta.
    pub fn from_dirs(dirs: Vec<PathBuf>, base: &Path) -> Themes {
        let parsed = std::fs::read_to_string(base)
            .map_err(|e| e.to_string())
            .and_then(|t| toml::from_str::<BaseFile>(&t).map_err(|e| e.message().to_string()));
        match parsed {
            Ok(b) => Themes { dirs, base: b.tokens, default: b.default },
            Err(e) => {
                lume_core::log::line("lume-ui", &format!("theme base {} not loaded: {e}", base.display()));
                Themes { dirs, base: toml::Table::new(), default: String::new() }
            }
        }
    }

    /// A folder whose name starts with "_" is not a theme: the card's model of the original
    /// theme (`_lume-original`) lives there for the user to copy.
    fn ignored(id: &str) -> bool {
        id.starts_with('_')
    }

    fn file(&self, id: &str) -> Option<PathBuf> {
        if id.is_empty() || id.contains(['/', '.']) || Themes::ignored(id) {
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
            .filter(|id| !Themes::ignored(id))
            .collect();
        ids.sort();
        ids.dedup();
        ids
    }

    /// The chosen theme, or the default one when none is chosen (empty).
    pub fn chosen<'a>(&'a self, id: &'a str) -> &'a str {
        if id.is_empty() {
            &self.default
        } else {
            id
        }
    }

    /// Where the Dock icons of a theme are looked up, in order: `<dir>/<id>/icons` of the
    /// theme and then of each parent (`extends`), the card before the image. A card folder
    /// themes/<id>/icons/ gives icons to that theme even without a theme.toml there (the
    /// image's own themes bring none: no manufacturer logo in the distro).
    pub fn icon_dirs(&self, id: &str) -> Vec<PathBuf> {
        let mut out = Vec::new();
        let mut cur = Some(self.chosen(id).to_string());
        let mut depth = 0;
        while let Some(id) = cur.take() {
            if depth > 8 || id.is_empty() || id.contains(['/', '.']) {
                break;
            }
            depth += 1;
            out.extend(self.dirs.iter().map(|d| d.join(&id).join("icons")));
            cur = self
                .file(&id)
                .and_then(|p| std::fs::read_to_string(p).ok())
                .and_then(|t| toml::from_str::<ThemeFile>(&t).ok())
                .and_then(|f| f.theme.extends);
        }
        out
    }

    /// Display name of a theme in `lang` (then English, then the id).
    pub fn name(&self, id: &str, lang: &str) -> String {
        let id = self.chosen(id);
        let head = self
            .file(id)
            .and_then(|p| std::fs::read_to_string(p).ok())
            .and_then(|t| toml::from_str::<ThemeFile>(&t).ok())
            .map(|f| f.theme.name)
            .unwrap_or_default();
        head.get(lang).or_else(|| head.get("en")).cloned().unwrap_or_else(|| id.to_string())
    }

    fn resolve(&self, id: &str, depth: u32) -> Result<(toml::Table, PathBuf), String> {
        if depth > 8 {
            return Err("circular extends".into());
        }
        let path = self.file(id).ok_or_else(|| format!("theme {id} not found"))?;
        let text = std::fs::read_to_string(&path).map_err(|e| e.to_string())?;
        let file: ThemeFile = toml::from_str(&text).map_err(|e| format!("{}: {}", path.display(), e.message()))?;
        if file.theme.id != id {
            return Err(format!("{}: id {} does not match the folder", path.display(), file.theme.id));
        }
        let mut table = match &file.theme.extends {
            Some(parent) => self.resolve(parent, depth + 1)?.0,
            None => self.base.clone(),
        };
        for (k, v) in file.tokens {
            table.insert(k, v);
        }
        Ok((table, path.parent().unwrap().to_path_buf()))
    }

    pub fn load(&self, id: &str) -> Result<Theme, String> {
        let id = self.chosen(id);
        let (table, dir) = self.resolve(id, 0)?;
        Theme::from_table(id, &self.base, &table, Some(dir))
    }

    /// The theme `id` (empty: the default one), or the default one when it is invalid
    /// (logged), or the bare base tokens when even that one is missing.
    pub fn load_or_default(&self, id: &str) -> Theme {
        match self.load(id) {
            Ok(t) => t,
            Err(e) => {
                lume_core::log::line("lume-ui", &format!("theme {id} refused: {e}; using {}", self.default));
                self.load(&self.default).unwrap_or_else(|_| Theme::from_table("base", &self.base, &self.base, None).unwrap_or(Theme {
                    id: "base".into(),
                    colors: BTreeMap::new(),
                    nums: BTreeMap::new(),
                    dir: None,
                }))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn share() -> PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../rootfs/overlay/usr/share/lume")
    }

    fn image_themes() -> Themes {
        Themes::from_dirs(vec![share().join("themes")], &share().join("themes").join(BASE_FILE))
    }

    #[test]
    fn image_themes_load_and_inherit() {
        let t = image_themes();
        assert_eq!(t.default, "lume");
        assert_eq!(t.list(), ["lume", "material-dark", "material-light"]);
        // no choice is the default theme
        let lume = t.load("").unwrap();
        assert_eq!(lume.id, "lume");
        let dark = t.load("material-dark").unwrap();
        let light = t.load("material-light").unwrap();
        assert_eq!(lume.color("bg"), Color::rgb(0x0F, 0x17, 0x1E));
        assert_eq!(lume.color("accent"), Color::rgb(0x4D, 0xB3, 0xFF));
        assert_eq!(dark.color("bg"), Color::rgb(0x14, 0x12, 0x18));
        assert_eq!(light.color("bg"), Color::rgb(0xFE, 0xF7, 0xFF));
        // shapes and positions come from the dark theme
        assert_eq!(light.num("mag_peak"), dark.num("mag_peak"));
        assert_eq!(lume.num("mag_peak"), dark.num("mag_peak"));
        assert_eq!(light.num("cols"), 4.0);
        assert_eq!(dark.em("icon", 640), 96);
        // a token no theme sets comes from the base file
        assert_eq!(dark.num("cache_bytes"), 4194304.0);
    }

    #[test]
    fn every_image_theme_has_a_name_in_each_language() {
        let t = image_themes();
        for id in t.list() {
            for lang in crate::i18n::LANGUAGES {
                assert_ne!(t.name(&id, lang), id, "{id} has no {lang} name");
            }
        }
        assert_eq!(t.name("material-dark", "pt"), "Escuro");
        assert_eq!(t.name("", "en"), "Lume");
    }

    #[test]
    fn a_new_theme_is_only_a_folder() {
        let dir = std::env::temp_dir().join(format!("lume-themes-new-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("ocean")).unwrap();
        std::fs::write(dir.join("ocean/theme.toml"), "[theme]\nid = \"ocean\"\nname = { en = \"Ocean\" }\nextends = \"lume\"\n[tokens]\naccent = \"#00ffaa\"\n").unwrap();
        let mut t = image_themes();
        t.dirs.insert(0, dir);
        assert!(t.list().contains(&"ocean".to_string()));
        assert_eq!(t.name("ocean", "pt"), "Ocean"); // English when the language is missing
        let o = t.load("ocean").unwrap();
        assert_eq!(o.color("accent"), Color::rgb(0, 0xff, 0xaa));
        assert_eq!(o.color("bg"), Color::rgb(0x0F, 0x17, 0x1E));
    }

    #[test]
    fn icons_of_a_theme_and_its_parents_card_first() {
        let card = std::env::temp_dir().join(format!("lume-icons-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&card);
        // icons only, no theme.toml: they belong to the image's lume theme
        std::fs::create_dir_all(card.join("lume/icons")).unwrap();
        let mut t = image_themes();
        t.dirs.insert(0, card.clone());
        let image = share().join("themes");
        assert_eq!(t.load("lume").unwrap().id, "lume", "an icons-only folder does not hide the theme");
        assert_eq!(
            t.icon_dirs(""),
            [card.join("lume/icons"), image.join("lume/icons"), card.join("material-dark/icons"), image.join("material-dark/icons")]
        );
        assert!(t.icon_dirs("../x").is_empty());
    }

    #[test]
    fn the_cards_model_is_ignored_and_is_the_original_theme() {
        let template = share().join("theme-template/_lume-original/theme.toml");
        let text = std::fs::read_to_string(&template).unwrap();
        let card = std::env::temp_dir().join(format!("lume-template-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&card);
        // as lume-index copies it: the folder starting with "_" is not a theme
        std::fs::create_dir_all(card.join("_lume-original")).unwrap();
        std::fs::write(card.join("_lume-original/theme.toml"), &text).unwrap();
        // and as the user copies it: another folder, the id changed
        std::fs::create_dir_all(card.join("meu-tema")).unwrap();
        std::fs::write(card.join("meu-tema/theme.toml"), text.replace("id = \"_lume-original\"", "id = \"meu-tema\"")).unwrap();
        let mut t = image_themes();
        t.dirs.insert(0, card);
        assert!(!t.list().iter().any(|id| id.starts_with('_')), "{:?}", t.list());
        assert!(t.load("_lume-original").is_err());
        // the copy is exactly the image's lume theme, in every token
        let copy = t.load("meu-tema").unwrap();
        let lume = t.load("lume").unwrap();
        assert_eq!(copy.colors, lume.colors);
        assert_eq!(copy.nums, lume.nums);
        // and it sets every token, so it shows the whole list
        let set: toml::Table = toml::from_str::<toml::Table>(&text).unwrap()["tokens"].as_table().unwrap().clone();
        let missing: Vec<_> = t.base.keys().filter(|k| !set.contains_key(*k)).collect();
        assert!(missing.is_empty(), "the model lacks {missing:?}");
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
            assert_eq!(t.load_or_default(id).id, t.default, "{id}");
        }
    }

    #[test]
    fn missing_base_does_not_stop_the_launcher() {
        let t = Themes::from_dirs(vec![share().join("themes")], Path::new("/nonexistent/base.toml"));
        assert!(t.default.is_empty());
        // every token is unknown without the base: the theme is refused, nothing panics
        let th = t.load_or_default("material-dark");
        assert_eq!(th.color("bg"), Color::rgb(255, 0, 255));
    }

    #[test]
    fn there_is_no_lite_mode_any_more() {
        // the old [features] lite flag is an unknown section now: such a theme is refused
        let dir = std::env::temp_dir().join(format!("lume-themes-lite-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(dir.join("old")).unwrap();
        std::fs::write(dir.join("old/theme.toml"), "[theme]\nid = \"old\"\n[features]\nlite = true\n").unwrap();
        let mut t = image_themes();
        t.dirs.insert(0, dir);
        assert!(t.load("old").is_err());
        // animation is a token like any other: a theme turns it off with anim_ms = 0
        assert!(t.load("lume").unwrap().num("anim_ms") > 0.0);
    }
}
