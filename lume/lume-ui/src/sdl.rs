//! The SDL2 backend of [`Canvas`] (lume-launcher D3): the KMSDRM video driver with the GLES
//! renderer on the consoles (lima, panfrost), any driver on a PC. Glyphs are rasterized by
//! fontdue once per size and kept as small white textures tinted per draw.

use std::collections::HashMap;

use sdl2::pixels::PixelFormatEnum;
use sdl2::render::{BlendMode, RenderTarget, Texture, TextureCreator};

use crate::canvas::{Align, Canvas, Color, Rect, TextureId};
use crate::font::Font;

struct GlyphTex {
    tex: Option<Texture>,
    w: u32,
    h: u32,
    xmin: i32,
    ymin: i32,
    advance: f32,
}

/// On a window (the device) or on a software surface (the screenshots).
pub struct SdlCanvas<T: RenderTarget> {
    pub canvas: sdl2::render::Canvas<T>,
    creator: TextureCreator<T::Context>,
    textures: HashMap<TextureId, Texture>,
    next: TextureId,
    font: Font,
    glyphs: HashMap<(char, u32), GlyphTex>,
    /// the medium and bold faces with their glyphs, swapped with the regular ones while
    /// drawing in that weight
    medium: Option<Font>,
    glyphs_medium: HashMap<(char, u32), GlyphTex>,
    bold: Option<Font>,
    glyphs_bold: HashMap<(char, u32), GlyphTex>,
}

#[derive(Clone, Copy)]
enum Face {
    Medium,
    Bold,
}

fn sdl(c: Color) -> sdl2::pixels::Color {
    sdl2::pixels::Color::RGBA(c.r, c.g, c.b, c.a)
}

impl<T: RenderTarget> SdlCanvas<T> {
    /// `creator` is `canvas.texture_creator()` (not generic in sdl2).
    pub fn new(canvas: sdl2::render::Canvas<T>, creator: TextureCreator<T::Context>, font: Font) -> SdlCanvas<T> {
        SdlCanvas {
            canvas,
            creator,
            textures: HashMap::new(),
            next: 1,
            font,
            glyphs: HashMap::new(),
            medium: None,
            glyphs_medium: HashMap::new(),
            bold: None,
            glyphs_bold: HashMap::new(),
        }
    }

    /// Adds the medium (500) and bold (700) faces; without one, that weight uses the
    /// regular face.
    pub fn with_faces(mut self, medium: Option<Font>, bold: Option<Font>) -> SdlCanvas<T> {
        self.medium = medium;
        self.bold = bold;
        self
    }

    /// Runs `f` with another face (and its glyph cache) in place of the regular one.
    fn as_face<R>(&mut self, face: Face, f: impl FnOnce(&mut Self) -> R) -> R {
        let (slot, cache) = match face {
            Face::Medium => (&mut self.medium, &mut self.glyphs_medium),
            Face::Bold => (&mut self.bold, &mut self.glyphs_bold),
        };
        let Some(mut other) = slot.take() else { return f(self) };
        let mut other_glyphs = std::mem::take(cache);
        std::mem::swap(&mut self.font, &mut other);
        std::mem::swap(&mut self.glyphs, &mut other_glyphs);
        let r = f(self);
        std::mem::swap(&mut self.glyphs, &mut other_glyphs);
        std::mem::swap(&mut self.font, &mut other);
        match face {
            Face::Medium => {
                self.medium = Some(other);
                self.glyphs_medium = other_glyphs;
            }
            Face::Bold => {
                self.bold = Some(other);
                self.glyphs_bold = other_glyphs;
            }
        }
        r
    }

    fn glyph(&mut self, ch: char, px: f32) -> &GlyphTex {
        let key = (ch, (px * 4.0).round() as u32);
        if !self.glyphs.contains_key(&key) {
            let g = self.font.glyph(ch, px);
            let (w, h) = (g.metrics.width as u32, g.metrics.height as u32);
            let tex = if w > 0 && h > 0 {
                let mut rgba = Vec::with_capacity((w * h * 4) as usize);
                for a in &g.bitmap {
                    rgba.extend_from_slice(&[255, 255, 255, *a]);
                }
                self.creator.create_texture_static(PixelFormatEnum::ABGR8888, w, h).ok().map(|mut t| {
                    let _ = t.update(None, &rgba, (w * 4) as usize);
                    t.set_blend_mode(BlendMode::Blend);
                    t
                })
            } else {
                None
            };
            let gt = GlyphTex { tex, w, h, xmin: g.metrics.xmin, ymin: g.metrics.ymin, advance: g.metrics.advance_width };
            self.glyphs.insert(key, gt);
        }
        &self.glyphs[&key]
    }
}

impl<T: RenderTarget> Canvas for SdlCanvas<T> {
    fn size(&self) -> (i32, i32) {
        let (w, h) = self.canvas.output_size().unwrap_or((640, 480));
        (w as i32, h as i32)
    }

    fn clear(&mut self, c: Color) {
        self.canvas.set_draw_color(sdl(c));
        self.canvas.clear();
    }

    fn fill(&mut self, r: Rect, radius: i32, c: Color) {
        if r.w <= 0 || r.h <= 0 {
            return;
        }
        self.canvas.set_blend_mode(if c.a < 255 { BlendMode::Blend } else { BlendMode::None });
        self.canvas.set_draw_color(sdl(c));
        let rad = radius.clamp(0, r.w.min(r.h) / 2);
        let _ = self.canvas.fill_rect(sdl2::rect::Rect::new(r.x, r.y + rad, r.w as u32, (r.h - 2 * rad) as u32));
        // the rounded top and bottom bands, one line per row
        for dy in 0..rad {
            let yy = (rad - dy) as f32 - 0.5;
            let dx = rad - ((rad * rad) as f32 - yy * yy).max(0.0).sqrt().round() as i32;
            let w = (r.w - 2 * dx).max(0) as u32;
            let _ = self.canvas.fill_rect(sdl2::rect::Rect::new(r.x + dx, r.y + dy, w, 1));
            let _ = self.canvas.fill_rect(sdl2::rect::Rect::new(r.x + dx, r.bottom() - 1 - dy, w, 1));
        }
    }

    fn texture_rgb565(&mut self, w: u32, h: u32, pixels: &[u8]) -> Option<TextureId> {
        let mut t = self.creator.create_texture_static(PixelFormatEnum::RGB565, w, h).ok()?;
        t.update(None, pixels, (w * 2) as usize).ok()?;
        let id = self.next;
        self.next += 1;
        self.textures.insert(id, t);
        Some(id)
    }

    fn set_clip(&mut self, r: Option<Rect>) {
        self.canvas.set_clip_rect(r.map(|r| sdl2::rect::Rect::new(r.x, r.y, r.w.max(0) as u32, r.h.max(0) as u32)));
    }

    fn texture_mask(&mut self, w: u32, h: u32, alpha: &[u8]) -> Option<TextureId> {
        // white with the mask as alpha, tinted per draw (as the glyphs)
        let mut rgba = Vec::with_capacity(alpha.len() * 4);
        for a in alpha {
            rgba.extend_from_slice(&[255, 255, 255, *a]);
        }
        let mut t = self.creator.create_texture_static(PixelFormatEnum::ABGR8888, w, h).ok()?;
        t.update(None, &rgba, (w * 4) as usize).ok()?;
        t.set_blend_mode(BlendMode::Blend);
        let id = self.next;
        self.next += 1;
        self.textures.insert(id, t);
        Some(id)
    }

    fn draw_mask(&mut self, t: TextureId, dst: Rect, c: Color) {
        if let Some(tex) = self.textures.get_mut(&t) {
            tex.set_color_mod(c.r, c.g, c.b);
            tex.set_alpha_mod(c.a);
            let _ = self.canvas.copy(tex, None, sdl2::rect::Rect::new(dst.x, dst.y, dst.w.max(1) as u32, dst.h.max(1) as u32));
        }
    }

    fn free_texture(&mut self, t: TextureId) {
        if let Some(tex) = self.textures.remove(&t) {
            unsafe { tex.destroy() };
        }
    }

    fn draw_texture(&mut self, t: TextureId, src: Rect, dst: Rect) {
        if let Some(tex) = self.textures.get(&t) {
            let s = sdl2::rect::Rect::new(src.x, src.y, src.w.max(1) as u32, src.h.max(1) as u32);
            let _ = self.canvas.copy(tex, s, sdl2::rect::Rect::new(dst.x, dst.y, dst.w.max(1) as u32, dst.h.max(1) as u32));
        }
    }

    fn text(&mut self, s: &str, x: i32, y: i32, px: f32, c: Color, align: Align, max_w: i32) -> i32 {
        let s = self.font.ellipsize(s, px, max_w.max(0));
        let w = self.font.width(&s, px);
        let mut pen = match align {
            Align::Left => x as f32,
            Align::Center => (x - w / 2) as f32,
            Align::Right => (x - w) as f32,
        };
        let base = y as f32 + self.font.ascent(px);
        for ch in s.chars() {
            let (gx, gy, gw, gh, adv) = {
                let g = self.glyph(ch, px);
                (g.xmin, g.ymin, g.w, g.h, g.advance)
            };
            let key = (ch, (px * 4.0).round() as u32);
            if let Some(tex) = self.glyphs.get_mut(&key).and_then(|g| g.tex.as_mut()) {
                tex.set_color_mod(c.r, c.g, c.b);
                tex.set_alpha_mod(c.a);
                let dst = sdl2::rect::Rect::new(pen.round() as i32 + gx, (base - gy as f32 - gh as f32).round() as i32, gw, gh);
                let _ = self.canvas.copy(tex, None, dst);
            }
            pen += adv;
        }
        w
    }

    fn text_width(&mut self, s: &str, px: f32) -> i32 {
        self.font.width(s, px)
    }

    fn text_bold(&mut self, s: &str, x: i32, y: i32, px: f32, c: Color, align: Align, max_w: i32) -> i32 {
        self.as_face(Face::Bold, |me| me.text(s, x, y, px, c, align, max_w))
    }

    fn text_width_bold(&mut self, s: &str, px: f32) -> i32 {
        self.as_face(Face::Bold, |me| me.font.width(s, px))
    }

    fn text_medium(&mut self, s: &str, x: i32, y: i32, px: f32, c: Color, align: Align, max_w: i32) -> i32 {
        self.as_face(Face::Medium, |me| me.text(s, x, y, px, c, align, max_w))
    }

    fn text_width_medium(&mut self, s: &str, px: f32) -> i32 {
        self.as_face(Face::Medium, |me| me.font.width(s, px))
    }

    fn present(&mut self) {
        self.canvas.present();
    }
}
