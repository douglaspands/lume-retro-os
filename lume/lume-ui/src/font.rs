//! Text with fontdue (lume-launcher D3): glyphs rasterized in Rust, no FreeType. The font is
//! Noto Sans from /usr/share/lume/fonts (LUME_FONT replaces it, for the tests); glyphs are
//! cached per size, and the backend keeps them in a texture atlas.

use std::collections::HashMap;

pub const DEFAULT_PATHS: &[&str] = &["/usr/share/lume/fonts/NotoSans-Regular.ttf"];

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

    /// The image font, or LUME_FONT; None when there is none (the fake backend then
    /// estimates widths).
    pub fn bundled() -> Option<Font> {
        if let Some(p) = std::env::var_os("LUME_FONT") {
            return Font::load(&p.to_string_lossy());
        }
        DEFAULT_PATHS.iter().find_map(|p| Font::load(p))
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
