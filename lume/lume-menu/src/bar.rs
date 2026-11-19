//! The status bar drawn in software into an ARGB8888 strip (lume-hud-actions D6; drawn by the
//! system since 2026-11-17, so it shows over any game). The layout is the one of RetroArch's
//! LUME_HUD widget that the user approved on the GA36: groups separated by `|`, the first word
//! of each (the label) in the accent and bold, the rest in the text color, spread over the
//! whole width with a thin muted divider in the middle of each space; a black strip at 60%.
//!
//! The pixels are premultiplied ARGB (the default blend of a DRM plane): the strip itself is
//! (0, 0, 0, 235), and a glyph over it keeps its color at full opacity.

use crate::draw::{text_width, Fonts, ACCENT, FG, MUTED, PANEL};

/// Sizes at 640x480, scaled with the screen height (the widget's 0.85 of RetroArch's font)
pub mod px {
    pub const HEIGHT: f32 = 24.0;
    pub const TEXT: f32 = 15.0;
    pub const MARGIN: f32 = 8.0;
    pub const LABEL_GAP: f32 = 4.0;
    /// 14 (was 18) so the temperature group fits next to the others (task 9.7, measured)
    pub const MIN_SPACE: f32 = 14.0;
    pub const DIVIDER_INSET: f32 = 6.0;
}

/// Opacity of the strip: black at 92% (the user, 2026-11-18: at 60%, as RetroArch's widget, the
/// small text over a bright game was hard to read)
const STRIP_ALPHA: u32 = 235;

/// The bar's height in pixels for a screen `h` high.
pub fn height(h: u32) -> u32 {
    (px::HEIGHT * h as f32 / 480.0).round() as u32
}

pub struct Strip<'a> {
    pub px: &'a mut [u8],
    pub w: usize,
    pub h: usize,
    pub pitch: usize,
}

impl Strip<'_> {
    fn fill(&mut self) {
        for y in 0..self.h {
            for p in self.px[y * self.pitch..y * self.pitch + self.w * 4].chunks_exact_mut(4) {
                p.copy_from_slice(&[0, 0, 0, STRIP_ALPHA as u8]);
            }
        }
    }

    /// `color` (opaque) over the pixel at coverage `a` (0-256), premultiplied.
    fn blend(&mut self, x: i32, y: i32, color: u32, a: u32) {
        if x < 0 || y < 0 || x as usize >= self.w || y as usize >= self.h || a == 0 {
            return;
        }
        let o = y as usize * self.pitch + x as usize * 4;
        let a = a.min(256);
        let (r, g, b) = ((color >> 16) & 0xff, (color >> 8) & 0xff, color & 0xff);
        let mix = |old: u8, new: u32| ((old as u32 * (256 - a) + new * a) >> 8) as u8;
        // ARGB8888 little endian: B G R A
        self.px[o] = mix(self.px[o], b);
        self.px[o + 1] = mix(self.px[o + 1], g);
        self.px[o + 2] = mix(self.px[o + 2], r);
        self.px[o + 3] = mix(self.px[o + 3], 255);
    }

    fn text(&mut self, fonts: &Fonts, font: &fontdue::Font, s: &str, size: f32, x: f32, color: u32) {
        let lm = font.horizontal_line_metrics(size);
        let (asc, desc) = lm.map(|m| (m.ascent, m.descent)).unwrap_or((size * 0.93, -size * 0.24));
        let baseline = (self.h as f32 - (asc - desc)) / 2.0 + asc;
        let mut pen = x;
        for c in s.chars() {
            pen += fonts.glyph(font, c, size, |m, bitmap| {
                let gx = pen.round() as i32 + m.xmin;
                let gy = baseline.round() as i32 - m.height as i32 - m.ymin;
                for row in 0..m.height {
                    for col in 0..m.width {
                        let cov = bitmap[row * m.width + col] as u32;
                        self.blend(gx + col as i32, gy + row as i32, color, cov + (cov >> 7));
                    }
                }
                m.advance_width
            });
        }
    }

    fn divider(&mut self, x: f32, s: f32) {
        let x = x.round() as i32;
        let (y0, y1) = ((px::DIVIDER_INSET * s).round() as i32, self.h as i32 - (px::DIVIDER_INSET * s).round() as i32);
        for y in y0..y1 {
            self.blend(x, y, MUTED, 154);
        }
    }
}

/// Draws `text` ("FPS 59.7|CPU 9% 1008|...") into the strip; `screen_h` scales the sizes.
pub fn draw(strip: &mut Strip, fonts: &Fonts, text: &str, screen_h: f32) {
    let s = screen_h / 480.0;
    let size = px::TEXT * s;
    strip.fill();
    let groups: Vec<(&str, &str)> = text
        .split('|')
        .map(str::trim)
        .filter(|g| !g.is_empty())
        .map(|g| g.split_once(' ').map(|(l, v)| (l, v.trim())).unwrap_or((g, "")))
        .collect();
    if groups.is_empty() {
        return;
    }
    let gap = px::LABEL_GAP * s;
    let widths: Vec<f32> = groups
        .iter()
        .map(|(l, v)| text_width(&fonts.bold, l, size) + if v.is_empty() { 0.0 } else { gap + text_width(&fonts.regular, v, size) })
        .collect();
    let total: f32 = widths.iter().sum();
    let margin = px::MARGIN * s;
    let n = groups.len() as f32;
    let space = if groups.len() > 1 { ((strip.w as f32 - 2.0 * margin - total) / (n - 1.0)).max(px::MIN_SPACE * s) } else { 0.0 };
    let mut pen = margin;
    for (i, ((label, value), w)) in groups.iter().zip(&widths).enumerate() {
        if i > 0 {
            strip.divider(pen - space / 2.0, s);
        }
        strip.text(fonts, &fonts.bold, label, size, pen, ACCENT);
        if !value.is_empty() {
            strip.text(fonts, &fonts.regular, value, size, pen + text_width(&fonts.bold, label, size) + gap, FG);
        }
        pen += w + space;
    }
}

/// Sizes of the chord hint at 640x480 (the family of the Lume menu: panel color, radius and
/// the accent on the button)
pub mod hint_px {
    pub const PAD: f32 = 16.0;
    pub const ROW: f32 = 30.0;
    pub const TEXT: f32 = 17.0;
    pub const GAP: f32 = 16.0;
    pub const RADIUS: f32 = 12.8;
}

/// The rows of a hint text: `button\tname` joined by `|`.
pub fn hint_rows(text: &str) -> Vec<(String, String)> {
    text.split('|')
        .filter(|r| !r.trim().is_empty())
        .map(|r| match r.split_once('\t') {
            Some((b, n)) => (b.trim().to_string(), n.trim().to_string()),
            None => (r.trim().to_string(), String::new()),
        })
        .collect()
}

/// The panel's size (w, h) in pixels for those rows on a screen `screen_h` high.
pub fn hint_size(fonts: &Fonts, rows: &[(String, String)], screen_h: f32) -> (u32, u32) {
    let s = screen_h / 480.0;
    let size = hint_px::TEXT * s;
    let keys = rows.iter().map(|(b, _)| text_width(&fonts.bold, b, size)).fold(0.0, f32::max);
    let names = rows.iter().map(|(_, n)| text_width(&fonts.regular, n, size)).fold(0.0, f32::max);
    let w = keys + hint_px::GAP * s + names + 2.0 * hint_px::PAD * s;
    let h = rows.len().max(1) as f32 * hint_px::ROW * s + 2.0 * hint_px::PAD * s;
    // even sizes: some display engines want them
    (((w.ceil() as u32) + 1) & !1, ((h.ceil() as u32) + 1) & !1)
}

/// Draws the hint panel filling the strip: rounded panel, a row per chord.
pub fn draw_hint(strip: &mut Strip, fonts: &Fonts, rows: &[(String, String)], screen_h: f32) {
    let s = screen_h / 480.0;
    let size = hint_px::TEXT * s;
    let (w, h, r) = (strip.w as f32, strip.h as f32, hint_px::RADIUS * s);
    // the panel: PANEL at 94% inside the rounded rectangle, transparent outside
    let (pr, pg, pb) = ((PANEL >> 16) & 0xff, (PANEL >> 8) & 0xff, PANEL & 0xff);
    for y in 0..strip.h {
        for x in 0..strip.w {
            let (cx, cy) = (x as f32 + 0.5, y as f32 + 0.5);
            let dx = (r - cx).max(cx - (w - r)).max(0.0);
            let dy = (r - cy).max(cy - (h - r)).max(0.0);
            let cover = if dx > 0.0 && dy > 0.0 { (r - (dx * dx + dy * dy).sqrt() + 0.5).clamp(0.0, 1.0) } else { 1.0 };
            let a = (240.0 * cover).round() as u32;
            let o = y * strip.pitch + x * 4;
            // premultiplied
            strip.px[o..o + 4].copy_from_slice(&[(pb * a / 255) as u8, (pg * a / 255) as u8, (pr * a / 255) as u8, a as u8]);
        }
    }
    let keys = rows.iter().map(|(b, _)| text_width(&fonts.bold, b, size)).fold(0.0, f32::max);
    let pad = hint_px::PAD * s;
    for (i, (button, name)) in rows.iter().enumerate() {
        let top = pad + i as f32 * hint_px::ROW * s;
        strip.text_in_row(fonts, &fonts.bold, button, size, pad, top, hint_px::ROW * s, ACCENT);
        strip.text_in_row(fonts, &fonts.regular, name, size, pad + keys + hint_px::GAP * s, top, hint_px::ROW * s, FG);
    }
}

impl Strip<'_> {
    fn text_in_row(&mut self, fonts: &Fonts, font: &fontdue::Font, s: &str, size: f32, x: f32, top: f32, row_h: f32, color: u32) {
        let lm = font.horizontal_line_metrics(size);
        let (asc, desc) = lm.map(|m| (m.ascent, m.descent)).unwrap_or((size * 0.93, -size * 0.24));
        let baseline = top + (row_h - (asc - desc)) / 2.0 + asc;
        let mut pen = x;
        for c in s.chars() {
            pen += fonts.glyph(font, c, size, |m, bitmap| {
                let gx = pen.round() as i32 + m.xmin;
                let gy = baseline.round() as i32 - m.height as i32 - m.ymin;
                for row in 0..m.height {
                    for col in 0..m.width {
                        let cov = bitmap[row * m.width + col] as u32;
                        self.blend(gx + col as i32, gy + row as i32, color, cov + (cov >> 7));
                    }
                }
                m.advance_width
            });
        }
    }
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;

    /// Roboto for the tests (also the server's, serve.rs)
    pub(crate) fn fonts() -> Option<Fonts> {
        let base = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../../cache/tmp/fonts");
        // LUME_TEST_FONTS: a worktree has no cache/, point it at the main tree's fonts
        let dirs = [
            std::env::var_os("LUME_TEST_FONTS").map(std::path::PathBuf::from).unwrap_or_default(),
            base.join("usr/share/lume/fonts"),
            base,
        ];
        let load = |n: &str| {
            dirs.iter().find_map(|d| fontdue::Font::from_bytes(std::fs::read(d.join(n)).ok()?, Default::default()).ok())
        };
        Some(Fonts::new(load("Roboto-Regular.ttf")?, load("Roboto-Medium.ttf")?, load("Roboto-Bold.ttf")?))
    }

    fn pixel(px: &[u8], pitch: usize, x: usize, y: usize) -> [u8; 4] {
        let o = y * pitch + x * 4;
        [px[o], px[o + 1], px[o + 2], px[o + 3]]
    }

    #[test]
    fn height_scales_with_the_screen() {
        assert_eq!(height(480), 24);
        assert_eq!(height(720), 36);
    }

    #[test]
    fn strip_is_translucent_black_and_text_is_opaque() {
        let Some(f) = fonts() else {
            eprintln!("skipped: no Roboto on this host");
            return;
        };
        let (w, h) = (640, 24);
        let mut buf = vec![0u8; w * h * 4];
        let mut s = Strip { px: &mut buf, w, h, pitch: w * 4 };
        draw(&mut s, &f, "FPS 59.7|CPU 9% 1008|GPU 11% 51M|MEM 146/492|BAT 100% +", 480.0);
        // a corner of the strip: black at 92%
        assert_eq!(pixel(&buf, w * 4, 0, 0), [0, 0, 0, 235]);
        // some pixel of the first label is the accent at full opacity
        let accent = [(ACCENT & 0xff) as u8, ((ACCENT >> 8) & 0xff) as u8, (ACCENT >> 16) as u8, 255];
        let found = (0..60).any(|x| (0..h).any(|y| pixel(&buf, w * 4, x, y) == accent));
        assert!(found, "no accent pixel in the first label");
        // the last group ends near the right edge (spread over the width)
        let last_text = (0..w).rev().find(|&x| (0..h).any(|y| pixel(&buf, w * 4, x, y)[3] == 255)).unwrap();
        assert!(last_text > w - 20, "last text at {last_text}");
    }

    /// The ruler: the widest realistic bar (with TMP) must fit 640x480 at the minimum spacing,
    /// so no group (BAT last) is cut or squeezed.
    #[test]
    fn widest_bar_with_tmp_fits_640() {
        let Some(f) = fonts() else {
            eprintln!("skipped: no Roboto on this host");
            return;
        };
        let size = px::TEXT;
        let measure = |text: &str| -> (f32, f32) {
            let groups: Vec<(&str, &str)> = text.split('|').map(|g| g.split_once(' ').unwrap_or((g, ""))).collect();
            let total: f32 = groups
                .iter()
                .map(|(l, v)| text_width(&f.bold, l, size) + if v.is_empty() { 0.0 } else { px::LABEL_GAP + text_width(&f.regular, v, size) })
                .sum();
            let need = total + 2.0 * px::MARGIN + (groups.len() - 1) as f32 * px::MIN_SPACE;
            (need, 640.0)
        };
        for text in [
            // GA36 (492 MiB) with swap in use, the example of docs/LAUNCHER.md
            "FPS 59.7|CPU 47% 1008|GPU 62% 38M|MEM 124/492 sw 20|52°|BAT 74% 1.9W 2:40",
            // R36S (1006 MiB), discharging and charging
            "FPS 60.0|CPU 47% 1296|GPU 62% 38M|MEM 300/1006|52°|BAT 74% 1.9W 2:40",
            "FPS 60.0|CPU 47% 1296|GPU 62% 38M|MEM 300/1006|52°|BAT 74% + 0:50",
            // busy: CPU at 100% and a 2-digit GPU memory
            "FPS 59.7|CPU 99% 1008|GPU 99% 38M|MEM 124/492 sw 20|52°|BAT 74% 1.9W 2:40",
        ] {
            let (need, avail) = measure(text);
            eprintln!("ruler {need:.1} of {avail} for {text}");
            assert!(need <= avail, "{text}: needs {need:.1} of {avail}");
        }
    }

    #[test]
    fn hint_rows_and_panel() {
        let rows = hint_rows("Fn+B\tRetroArch menu|Fn+X\tStatus bar|Fn+Start\tEnd game");
        assert_eq!(rows.len(), 3);
        assert_eq!(rows[0], ("Fn+B".to_string(), "RetroArch menu".to_string()));
        let Some(f) = fonts() else { return };
        let (w, h) = hint_size(&f, &rows, 480.0);
        assert_eq!(h, 3 * 30 + 32);
        assert!(w > 150 && w < 400 && w % 2 == 0, "{w}");
        let mut buf = vec![0u8; w as usize * h as usize * 4];
        let mut s = Strip { px: &mut buf, w: w as usize, h: h as usize, pitch: w as usize * 4 };
        draw_hint(&mut s, &f, &rows, 480.0);
        // the corner outside the radius is transparent, the middle of the panel is opaque-ish
        assert_eq!(pixel(&buf, w as usize * 4, 0, 0)[3], 0);
        assert!(pixel(&buf, w as usize * 4, w as usize / 2, 4)[3] >= 200);
    }

    #[test]
    fn empty_text_leaves_only_the_strip() {
        let Some(f) = fonts() else { return };
        let (w, h) = (100, 24);
        let mut buf = vec![0u8; w * h * 4];
        let mut s = Strip { px: &mut buf, w, h, pitch: w * 4 };
        draw(&mut s, &f, "", 480.0);
        assert!(buf.chunks_exact(4).all(|p| p == [0, 0, 0, 235]));
    }
}
