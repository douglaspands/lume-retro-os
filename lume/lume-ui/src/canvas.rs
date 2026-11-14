//! The drawing boundary of the engine (lume-launcher D3). The screens draw rectangles,
//! textures and text through this trait and never see SDL, so the backend can change per
//! console (task 2.1) and the tests use [`FakeCanvas`].

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Color {
    pub r: u8,
    pub g: u8,
    pub b: u8,
    pub a: u8,
}

impl Color {
    pub const fn rgb(r: u8, g: u8, b: u8) -> Color {
        Color { r, g, b, a: 255 }
    }

    /// `#rrggbb` or `#rrggbbaa`.
    pub fn parse(s: &str) -> Option<Color> {
        let h = s.strip_prefix('#')?;
        let byte = |i: usize| u8::from_str_radix(h.get(i..i + 2)?, 16).ok();
        match h.len() {
            6 => Some(Color { r: byte(0)?, g: byte(2)?, b: byte(4)?, a: 255 }),
            8 => Some(Color { r: byte(0)?, g: byte(2)?, b: byte(4)?, a: byte(6)? }),
            _ => None,
        }
    }

    pub fn opaque(self) -> Color {
        Color { a: 255, ..self }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct Rect {
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
}

impl Rect {
    pub const fn new(x: i32, y: i32, w: i32, h: i32) -> Rect {
        Rect { x, y, w, h }
    }

    pub fn right(&self) -> i32 {
        self.x + self.w
    }

    pub fn bottom(&self) -> i32 {
        self.y + self.h
    }

    pub fn inset(&self, d: i32) -> Rect {
        Rect::new(self.x + d, self.y + d, (self.w - 2 * d).max(0), (self.h - 2 * d).max(0))
    }

    pub fn contains(&self, other: &Rect) -> bool {
        other.x >= self.x && other.y >= self.y && other.right() <= self.right() && other.bottom() <= self.bottom()
    }
}

/// A texture of the backend (thumbnail slot, glyph atlas).
pub type TextureId = u32;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Align {
    Left,
    Center,
    Right,
}

pub trait Canvas {
    fn size(&self) -> (i32, i32);
    fn clear(&mut self, c: Color);
    /// Rounded rectangle; `radius` 0 is square. Alpha below 255 blends.
    fn fill(&mut self, r: Rect, radius: i32, c: Color);
    /// A texture made from RGB565 pixels (thumbnails), owned by the backend.
    fn texture_rgb565(&mut self, w: u32, h: u32, pixels: &[u8]) -> Option<TextureId>;
    fn free_texture(&mut self, t: TextureId);
    /// The `src` part of a texture into `dst`.
    fn draw_texture(&mut self, t: TextureId, src: Rect, dst: Rect);
    /// One line of text with its left (or center, right) at `x` and its top at `y`, clipped
    /// to `max_w` (an ellipsis when it does not fit). Returns the drawn width.
    #[allow(clippy::too_many_arguments)]
    fn text(&mut self, s: &str, x: i32, y: i32, px: f32, c: Color, align: Align, max_w: i32) -> i32;
    fn text_width(&mut self, s: &str, px: f32) -> i32;
    fn present(&mut self);
}

/// The test backend: counts frames and records what was drawn, with no screen.
#[derive(Default)]
pub struct FakeCanvas {
    pub w: i32,
    pub h: i32,
    pub frames: u32,
    pub textures: u32,
    pub live_textures: i64,
    /// Texts of the last frame with their box (x, y, w)
    pub texts: Vec<(String, Rect)>,
    pub fills: Vec<(Rect, Color)>,
    /// Texts of the last frame that did not fit their room (drawn with an ellipsis)
    pub clipped: Vec<String>,
    current_clipped: Vec<String>,
    current_texts: Vec<(String, Rect)>,
    current_fills: Vec<(Rect, Color)>,
    font: Option<crate::font::Font>,
}

impl FakeCanvas {
    pub fn new(w: i32, h: i32) -> FakeCanvas {
        FakeCanvas { w, h, font: crate::font::Font::bundled(), ..Default::default() }
    }

    pub fn has_text(&self, s: &str) -> bool {
        self.texts.iter().any(|(t, _)| t == s)
    }
}

impl Canvas for FakeCanvas {
    fn size(&self) -> (i32, i32) {
        (self.w, self.h)
    }

    fn clear(&mut self, _c: Color) {
        self.current_texts.clear();
        self.current_fills.clear();
        self.current_clipped.clear();
    }

    fn fill(&mut self, r: Rect, _radius: i32, c: Color) {
        self.current_fills.push((r, c));
    }

    fn texture_rgb565(&mut self, _w: u32, _h: u32, _pixels: &[u8]) -> Option<TextureId> {
        self.textures += 1;
        self.live_textures += 1;
        Some(self.textures)
    }

    fn free_texture(&mut self, _t: TextureId) {
        self.live_textures -= 1;
    }

    fn draw_texture(&mut self, _t: TextureId, _src: Rect, dst: Rect) {
        // recorded with the fills: the layout tests check that everything is on screen
        self.current_fills.push((dst, Color::default()));
    }

    fn text(&mut self, s: &str, x: i32, y: i32, px: f32, _c: Color, align: Align, max_w: i32) -> i32 {
        let full = self.text_width(s, px);
        let w = full.min(max_w);
        let left = match align {
            Align::Left => x,
            Align::Center => x - w / 2,
            Align::Right => x - w,
        };
        // a text wider than its room is recorded with its full width: the tests look for it
        self.current_texts.push((s.to_string(), Rect::new(left, y, full, px as i32)));
        if full > max_w {
            self.current_clipped.push(s.to_string());
        }
        w
    }

    fn text_width(&mut self, s: &str, px: f32) -> i32 {
        match &mut self.font {
            Some(f) => f.width(s, px),
            None => (s.chars().count() as f32 * px * 0.55) as i32,
        }
    }

    fn present(&mut self) {
        self.frames += 1;
        self.texts = std::mem::take(&mut self.current_texts);
        self.fills = std::mem::take(&mut self.current_fills);
        self.clipped = std::mem::take(&mut self.current_clipped);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn colors() {
        assert_eq!(Color::parse("#141218"), Some(Color::rgb(0x14, 0x12, 0x18)));
        assert_eq!(Color::parse("#000000a8").unwrap().a, 0xa8);
        assert_eq!(Color::parse("red"), None);
        assert_eq!(Color::parse("#12345"), None);
    }

    #[test]
    fn rects() {
        let r = Rect::new(10, 10, 100, 50);
        assert!(r.contains(&Rect::new(10, 10, 100, 50)));
        assert!(!r.contains(&Rect::new(10, 10, 101, 50)));
        assert_eq!(r.inset(5), Rect::new(15, 15, 90, 40));
    }
}
