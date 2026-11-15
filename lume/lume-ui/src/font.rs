//! Text with fontdue (lume-launcher D3): glyphs rasterized in Rust, no FreeType. The font is
//! Roboto, the prototype's, from /usr/share/lume/fonts in three weights: regular (400),
//! medium (500) and bold (700). LUME_FONT, LUME_FONT_MEDIUM and LUME_FONT_BOLD replace them
//! (the tests, the screenshots on a PC). Glyphs are cached per size, and the backend keeps
//! them in textures.

use std::collections::HashMap;

pub const DEFAULT_PATHS: &[&str] = &["/usr/share/lume/fonts/Roboto-Regular.ttf"];
/// The medium face (counter, battery, the focused game's name).
pub const MEDIUM_PATHS: &[&str] = &["/usr/share/lume/fonts/Roboto-Medium.ttf"];
/// The bold face (titles, button letters).
pub const BOLD_PATHS: &[&str] = &["/usr/share/lume/fonts/Roboto-Bold.ttf"];

pub struct Glyph {
    pub metrics: fontdue::Metrics,
    pub bitmap: Vec<u8>,
}

pub struct Font {
    font: fontdue::Font,
    cache: HashMap<(char, u32), Glyph>,
    advances: HashMap<(char, u32), f32>,
}

impl Font {
    pub fn load(path: &str) -> Option<Font> {
        let bytes = std::fs::read(path).ok()?;
        let font = fontdue::Font::from_bytes(bytes, fontdue::FontSettings::default()).ok()?;
        Some(Font { font, cache: HashMap::new(), advances: HashMap::new() })
    }

    fn face(env: &str, paths: &[&str]) -> Option<Font> {
        if let Some(p) = std::env::var_os(env) {
            return Font::load(&p.to_string_lossy());
        }
        paths.iter().find_map(|p| Font::load(p))
    }

    /// The regular face, or LUME_FONT; None when there is none (the fake backend then
    /// estimates widths).
    pub fn bundled() -> Option<Font> {
        Font::face("LUME_FONT", DEFAULT_PATHS)
    }

    /// The medium face, or LUME_FONT_MEDIUM; None: medium text uses the regular face.
    pub fn bundled_medium() -> Option<Font> {
        Font::face("LUME_FONT_MEDIUM", MEDIUM_PATHS)
    }

    /// The bold face, or LUME_FONT_BOLD; None: bold text uses the regular face.
    pub fn bundled_bold() -> Option<Font> {
        Font::face("LUME_FONT_BOLD", BOLD_PATHS)
    }

    fn key(c: char, px: f32) -> (char, u32) {
        (c, (px * 4.0).round() as u32)
    }

    pub fn advance(&mut self, c: char, px: f32) -> f32 {
        let k = Font::key(c, px);
        if let Some(a) = self.advances.get(&k) {
            return *a;
        }
        let a = self.font.metrics(c, px).advance_width;
        self.advances.insert(k, a);
        a
    }

    pub fn width(&mut self, s: &str, px: f32) -> i32 {
        s.chars().map(|c| self.advance(c, px)).sum::<f32>().ceil() as i32
    }

    pub fn glyph(&mut self, c: char, px: f32) -> &Glyph {
        let k = Font::key(c, px);
        let font = &self.font;
        self.cache.entry(k).or_insert_with(|| {
            let (metrics, bitmap) = font.rasterize(c, px);
            Glyph { metrics, bitmap }
        })
    }

    /// Ascent of the font at `px` (baseline offset from the top of a line).
    pub fn ascent(&self, px: f32) -> f32 {
        self.font.horizontal_line_metrics(px).map(|m| m.ascent).unwrap_or(px * 0.8)
    }

    /// Whether the font has a glyph for `c` (index 0 is the "missing" box).
    pub fn has(&self, c: char) -> bool {
        self.font.lookup_glyph_index(c) != 0
    }

    /// The longest prefix of `s` that fits in `max_w` with an ellipsis.
    pub fn ellipsize(&mut self, s: &str, px: f32, max_w: i32) -> String {
        if self.width(s, px) <= max_w {
            return s.to_string();
        }
        let dots = self.advance('…', px);
        let mut w = 0.0;
        let mut out = String::new();
        for c in s.chars() {
            let a = self.advance(c, px);
            if (w + a + dots).ceil() as i32 > max_w {
                break;
            }
            w += a;
            out.push(c);
        }
        out.push('…');
        out
    }
}
