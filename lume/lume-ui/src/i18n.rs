//! Texts of the launcher in en, pt and es (lume-launcher task 7.6): one TOML file per
//! language in /usr/share/lume/i18n/, with exactly the same keys. A missing key shows the
//! key itself (and the test below fails first). `{n}` is replaced by a number.

use std::collections::BTreeMap;
use std::path::Path;

pub const LANGUAGES: &[&str] = &["en", "pt", "es"];

pub struct Texts {
    map: BTreeMap<String, String>,
}

impl Texts {
    pub fn load(dir: &Path, lang: &str) -> Texts {
        let lang = if LANGUAGES.contains(&lang) { lang } else { "en" };
        let map = std::fs::read_to_string(dir.join(format!("{lang}.toml")))
            .ok()
            .and_then(|t| toml::from_str(&t).ok())
            .unwrap_or_default();
        Texts { map }
    }

    pub fn get<'a>(&'a self, key: &'a str) -> &'a str {
        self.map.get(key).map(String::as_str).unwrap_or(key)
    }

    pub fn n(&self, key: &str, n: impl std::fmt::Display) -> String {
        self.get(key).replace("{n}", &n.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    fn dir() -> std::path::PathBuf {
        Path::new(env!("CARGO_MANIFEST_DIR")).join("../../aports/lume-launcher-data/files/usr/share/lume/i18n")
    }

    fn keys(lang: &str) -> BTreeSet<String> {
        let t: BTreeMap<String, String> = toml::from_str(&std::fs::read_to_string(dir().join(format!("{lang}.toml"))).unwrap()).unwrap();
        t.into_keys().collect()
    }

    /// Every string literal of src/ (a key is used when it appears as one: tr("x"),
    /// toast_key("x"), tr(if .. { "x" } else { "y" }), TEXT_KEYS).
    fn literals() -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        for e in std::fs::read_dir(Path::new(env!("CARGO_MANIFEST_DIR")).join("src")).unwrap() {
            let path = e.unwrap().path();
            if path.ends_with("i18n.rs") {
                continue;
            }
            let text = std::fs::read_to_string(path).unwrap();
            for (i, part) in text.split('"').enumerate() {
                if i % 2 == 1 && !part.is_empty() && part.len() < 40 {
                    out.insert(part.to_string());
                }
            }
        }
        out
    }

    /// Keys the code asks for directly: tr("key") and .n("key", ...) in src/.
    fn used() -> BTreeSet<String> {
        let mut out = BTreeSet::new();
        for e in std::fs::read_dir(Path::new(env!("CARGO_MANIFEST_DIR")).join("src")).unwrap() {
            let path = e.unwrap().path();
            if path.ends_with("i18n.rs") {
                continue; // this file: the scanner itself
            }
            let text = std::fs::read_to_string(path).unwrap();
            for pat in ["tr(\"", ".n(\""] {
                for part in text.split(pat).skip(1) {
                    if let Some(k) = part.split('"').next().filter(|k| !k.is_empty()) {
                        out.insert(k.to_string());
                    }
                }
            }
            // keys built at run time from a fixed prefix
            for part in text.split("TEXT_KEYS: &[&str] = &[").skip(1) {
                for k in part.split(']').next().unwrap().split(',') {
                    let k = k.trim().trim_matches('"');
                    if !k.is_empty() {
                        out.insert(k.to_string());
                    }
                }
            }
        }
        out
    }

    #[test]
    fn same_keys_in_every_language_and_all_used() {
        let en = keys("en");
        for lang in ["pt", "es"] {
            assert_eq!(keys(lang), en, "{lang} differs from en");
        }
        let used = used();
        let missing: Vec<_> = used.difference(&en).collect();
        assert!(missing.is_empty(), "keys used but missing: {missing:?}");
        let lits = literals();
        let unused: Vec<_> = en.iter().filter(|k| !lits.contains(*k) && !used.contains(*k)).collect();
        assert!(unused.is_empty(), "keys never used: {unused:?}");
    }

    /// Every character of the three languages and the symbols the code draws exist in the
    /// font given by LUME_FONT (the image's Roboto; skipped without it: the font is not in
    /// git). Run: LUME_FONT=.../Roboto-Regular.ttf cargo test -p lume-ui every_glyph
    #[test]
    fn the_font_has_every_glyph_the_launcher_draws() {
        let Some(font) = crate::font::Font::bundled() else { return };
        let mut chars: BTreeSet<char> = "‹›“”·…%/0123456789".chars().collect();
        for lang in LANGUAGES {
            let t: BTreeMap<String, String> = toml::from_str(&std::fs::read_to_string(dir().join(format!("{lang}.toml"))).unwrap()).unwrap();
            chars.extend(t.values().flat_map(|v| v.chars()));
        }
        let missing: Vec<char> = chars.into_iter().filter(|c| !c.is_whitespace() && !font.has(*c)).collect();
        assert!(missing.is_empty(), "missing glyphs: {missing:?}");
    }

    #[test]
    fn numbers_and_fallback() {
        let t = Texts::load(&dir(), "pt");
        assert_eq!(t.n("other_core", 2), "2 em outro core");
        assert_eq!(t.get("nope"), "nope");
        assert_eq!(Texts::load(&dir(), "xx").get("settings"), "Settings");
    }
}
