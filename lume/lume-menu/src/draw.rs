//! The Lume menu drawn in software into an XRGB8888 buffer (lume-hud-actions 3.4, D14), with
//! the measurements approved in the prototype (`docs/lume-launcher/design-das-telas.md`,
//! "Sobre o jogo", 640x480, 1em = 16 px). Sizes scale with the screen height.
//!
//! The state comes as the text of `LUME_MENU`: `title|item|...|focus`.

/// The tokens of the image's default theme (`themes/base.toml`).
pub const OVERLAY: (u32, f32) = (0x000000, 0.667);
pub const PANEL: u32 = 0x1b1f25;
pub const ACCENT: u32 = 0x4cc2ff;
pub const ACCENT_FG: u32 = 0x001018;
pub const FG: u32 = 0xf0f0f0;
pub const MUTED: u32 = 0x9aa0aa;
/// "Force close" out of focus (prototype `.warn`)
pub const WARN: u32 = 0xff8a80;

/// Prototype measurements at 640x480 (design-das-telas.md)
pub mod px {
    pub const PANEL_MIN_W: f32 = 300.0;
    pub const PANEL_RADIUS: f32 = 12.8;
    pub const TITLE_H: f32 = 58.0;
    pub const TITLE_SIZE: f32 = 22.4;
    pub const ITEMS_TOP: f32 = 68.0;
    pub const ROW_STEP: f32 = 47.6;
    pub const ROW_H: f32 = 46.0;
    pub const ROW_INSET: f32 = 8.0;
    pub const ROW_RADIUS: f32 = 5.0;
    pub const ITEM_SIZE: f32 = 20.0;
    pub const TEXT_X: f32 = 24.0;
    /// 276 px for 4 items in the measured panel: 68 + 3 x 47.6 + 46 + 19.2
    pub const BOTTOM_PAD: f32 = 19.2;
    pub const HINT_Y: f32 = 443.0;
    pub const HINT_SIZE: f32 = 19.2;
    pub const HINT_BADGE: f32 = 23.0;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MenuState {
    pub title: String,
    pub items: Vec<String>,
    pub focus: usize,
}

/// Parses `title|item|...|focus`; None for anything shorter or a bad focus.
pub fn parse(line: &str) -> Option<MenuState> {
    let parts: Vec<&str> = line.trim_end_matches(['\n', '\r']).split('|').collect();
    if parts.len() < 3 {
        return None;
    }
    let focus: usize = parts[parts.len() - 1].trim().parse().ok()?;
    let items: Vec<String> = parts[1..parts.len() - 1].iter().map(|s| s.to_string()).collect();
    Some(MenuState { title: parts[0].to_string(), focus: focus.min(items.len() - 1), items })
}

pub struct Fonts {
    pub regular: fontdue::Font,
    pub medium: fontdue::Font,
    pub bold: fontdue::Font,
    /// glyphs rasterized once (a move of the focus redraws the same letters; rasterizing them
    /// again on the Cortex-A7 made the menu slow to answer, J2 on the GA36)
    cache: std::cell::RefCell<std::collections::HashMap<(usize, char, u32), (fontdue::Metrics, Vec<u8>)>>,
}

fn load(env: &str, path: &str) -> Option<fontdue::Font> {
    let p = std::env::var(env).unwrap_or_else(|_| path.to_string());
    let bytes = std::fs::read(p).ok()?;
    fontdue::Font::from_bytes(bytes, fontdue::FontSettings::default()).ok()
}

impl Fonts {
    /// Roboto from /usr/share/lume/fonts (the launcher's), or LUME_FONT* for the tests.
    pub fn bundled() -> Option<Fonts> {
        let regular = load("LUME_FONT", "/usr/share/lume/fonts/Roboto-Regular.ttf")?;
        let medium = load("LUME_FONT_MEDIUM", "/usr/share/lume/fonts/Roboto-Medium.ttf");
        let bold = load("LUME_FONT_BOLD", "/usr/share/lume/fonts/Roboto-Bold.ttf");
        let medium = medium.unwrap_or_else(|| regular.clone());
        let bold = bold.unwrap_or_else(|| medium.clone());
        Some(Fonts::new(regular, medium, bold))
    }

    pub fn new(regular: fontdue::Font, medium: fontdue::Font, bold: fontdue::Font) -> Fonts {
        Fonts { regular, medium, bold, cache: Default::default() }
    }

    /// A glyph of `font`, rasterized once per size.
    fn glyph<R>(&self, font: &fontdue::Font, c: char, size: f32, f: impl FnOnce(&fontdue::Metrics, &[u8]) -> R) -> R {
        let key = (font as *const fontdue::Font as usize, c, (size * 8.0).round() as u32);
        let mut cache = self.cache.borrow_mut();
        let (m, bitmap) = cache.entry(key).or_insert_with(|| font.rasterize(c, size));
        f(m, bitmap)
    }
}

/// An XRGB8888 image in memory: our dumb buffer, or a test's.
pub struct Image<'a> {
    pub px: &'a mut [u8],
    pub w: usize,
    pub h: usize,
    pub pitch: usize,
}

fn rgb(c: u32) -> (u32, u32, u32) {
    ((c >> 16) & 0xff, (c >> 8) & 0xff, c & 0xff)
}

impl Image<'_> {
    #[cfg(test)]
    pub fn get(&self, x: usize, y: usize) -> u32 {
        let o = y * self.pitch + x * 4;
        u32::from_le_bytes([self.px[o], self.px[o + 1], self.px[o + 2], self.px[o + 3]]) & 0xffffff
    }

    /// Blends `color` at `a` (0-256) into one pixel; integer math (the Cortex-A7 of the GA36).
    fn blend(&mut self, x: i32, y: i32, color: u32, a: u32) {
        if x < 0 || y < 0 || x as usize >= self.w || y as usize >= self.h || a == 0 {
            return;
        }
        let o = y as usize * self.pitch + x as usize * 4;
        let (r, g, b) = rgb(color);
        let a = a.min(256);
        let mix = |old: u8, new: u32| ((old as u32 * (256 - a) + new * a) >> 8) as u8;
        // XRGB8888 little endian: B G R X
        self.px[o] = mix(self.px[o], b);
        self.px[o + 1] = mix(self.px[o + 1], g);
        self.px[o + 2] = mix(self.px[o + 2], r);
        self.px[o + 3] = 0xff;
    }

    /// The whole image darkened toward black at `a` (0-1): the menu's background.
    pub fn dim(&mut self, a: f32) {
        let k = ((1.0 - a) * 256.0).round() as u32;
        for y in 0..self.h {
            let row = &mut self.px[y * self.pitch..y * self.pitch + self.w * 4];
            for p in row.chunks_exact_mut(4) {
                p[0] = ((p[0] as u32 * k) >> 8) as u8;
                p[1] = ((p[1] as u32 * k) >> 8) as u8;
                p[2] = ((p[2] as u32 * k) >> 8) as u8;
            }
        }
    }

    /// A rectangle with rounded corners (radius in px), blended at `a`.
    pub fn round_rect(&mut self, x: f32, y: f32, w: f32, h: f32, r: f32, color: u32, a: f32) {
        let (x0, y0, x1, y1) = (x.floor() as i32, y.floor() as i32, (x + w).ceil() as i32, (y + h).ceil() as i32);
        for py in y0..y1 {
            for px in x0..x1 {
                let (cx, cy) = (px as f32 + 0.5, py as f32 + 0.5);
                // distance into the nearest corner circle (only near the corners)
                let dx = (x + r - cx).max(cx - (x + w - r)).max(0.0);
                let dy = (y + r - cy).max(cy - (y + h - r)).max(0.0);
                let cover = if r > 0.0 && dx > 0.0 && dy > 0.0 {
                    (r - (dx * dx + dy * dy).sqrt() + 0.5).clamp(0.0, 1.0)
                } else {
                    1.0
                };
                let inside = (cx - x).min(x + w - cx).min(cy - y).min(y + h - cy).clamp(0.0, 1.0);
                let cov = a * cover.min(inside + 0.5).min(1.0);
                self.blend(px, py, color, (cov * 256.0).round() as u32);
            }
        }
    }

    /// Text with its top-left corner of the line at (x, line_top), line height `line_h`
    /// (the text is centred in it, like the prototype's line boxes).
    pub fn text(&mut self, fonts: &Fonts, font: &fontdue::Font, s: &str, size: f32, x: f32, line_top: f32, line_h: f32, color: u32) {
        let lm = font.horizontal_line_metrics(size);
        let (asc, desc) = lm.map(|m| (m.ascent, m.descent)).unwrap_or((size * 0.93, -size * 0.24));
        let baseline = line_top + (line_h - (asc - desc)) / 2.0 + asc;
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

/// `dst = from + (to - from) * a` per byte, a in 0-256: one step of the fade-in.
pub fn mix_into(dst: &mut [u8], from: &[u8], to: &[u8], a: u32) {
    for ((d, f), t) in dst.iter_mut().zip(from).zip(to) {
        *d = ((*f as u32 * (256 - a) + *t as u32 * a) >> 8) as u8;
    }
}

pub fn text_width(font: &fontdue::Font, s: &str, size: f32) -> f32 {
    s.chars().map(|c| font.metrics(c, size).advance_width).sum()
}

/// The panel's rectangle for a state (x, y, w, h) on a w x h screen.
pub fn panel_rect(fonts: &Fonts, st: &MenuState, w: f32, h: f32) -> (f32, f32, f32, f32) {
    let s = h / 480.0;
    let mut content = text_width(&fonts.medium, &st.title, px::TITLE_SIZE * s);
    for i in &st.items {
        content = content.max(text_width(&fonts.regular, i, px::ITEM_SIZE * s));
    }
    let pw = (content + 2.0 * px::TEXT_X * s).max(px::PANEL_MIN_W * s).min(w - 32.0 * s);
    let ph = (px::ITEMS_TOP + px::ROW_STEP * (st.items.len() as f32 - 1.0) + px::ROW_H + px::BOTTOM_PAD) * s;
    (((w - pw) / 2.0).round(), ((h - ph) / 2.0).round(), pw.round(), ph.round())
}

/// Draws the menu over `img` (which already holds the game's last frame). `hints` are the
/// words of A and B ("Escolher", "Voltar"); `warn` is the item drawn in the warning color
/// out of focus ("Force close").
pub fn draw(img: &mut Image, fonts: &Fonts, st: &MenuState, hints: (&str, &str), warn: Option<&str>) {
    draw_base(img, fonts, st, hints);
    draw_items(img, fonts, st, warn);
}

/// What does not change with the focus: the dimmed game, the panel, the title, the A/B
/// hints. Drawn once per list; a move of the focus only redraws the items over a copy.
pub fn draw_base(img: &mut Image, fonts: &Fonts, st: &MenuState, hints: (&str, &str)) {
    let (w, h) = (img.w as f32, img.h as f32);
    let s = h / 480.0;
    img.dim(OVERLAY.1);
    let (x, y, pw, ph) = panel_rect(fonts, st, w, h);
    img.round_rect(x, y, pw, ph, px::PANEL_RADIUS * s, PANEL, 1.0);
    img.text(fonts, &fonts.medium, &st.title, px::TITLE_SIZE * s, x + px::TEXT_X * s, y, px::TITLE_H * s, FG);
    img.round_rect(x + px::ROW_INSET * s, y + px::TITLE_H * s - 1.0, pw - 2.0 * px::ROW_INSET * s, 1.0, 0.0, MUTED, 0.35);
    draw_hints(img, fonts, hints);
}

/// The items and the focused row, over the base.
pub fn draw_items(img: &mut Image, fonts: &Fonts, st: &MenuState, warn: Option<&str>) {
    let (w, h) = (img.w as f32, img.h as f32);
    let s = h / 480.0;
    let (x, y, pw, _) = panel_rect(fonts, st, w, h);
    for (i, item) in st.items.iter().enumerate() {
        let ry = y + (px::ITEMS_TOP + px::ROW_STEP * i as f32) * s;
        let focused = i == st.focus;
        if focused {
            img.round_rect(x + px::ROW_INSET * s, ry, pw - 2.0 * px::ROW_INSET * s, px::ROW_H * s, px::ROW_RADIUS * s, ACCENT, 1.0);
        }
        let color = if focused { ACCENT_FG } else if Some(item.as_str()) == warn { WARN } else { FG };
        img.text(fonts, &fonts.regular, item, px::ITEM_SIZE * s, x + px::TEXT_X * s, ry, px::ROW_H * s, color);
    }
}

/// The A / B hints at the bottom, like the launcher's footer.
fn draw_hints(img: &mut Image, fonts: &Fonts, hints: (&str, &str)) {
    let (w, h) = (img.w as f32, img.h as f32);
    let s = h / 480.0;
    let size = px::HINT_SIZE * s;
    let badge = px::HINT_BADGE * s;
    let gap = 0.35 * 16.0 * s;
    let space = 1.2 * 16.0 * s;
    let total = 2.0 * (badge + gap) + text_width(&fonts.regular, hints.0, size) + space + text_width(&fonts.regular, hints.1, size);
    let mut pen = (w - total) / 2.0;
    let top = px::HINT_Y * s;
    for (letter, word) in [("A", hints.0), ("B", hints.1)] {
        img.round_rect(pen, top, badge, badge, badge / 2.0, ACCENT, 1.0);
        let lw = text_width(&fonts.bold, letter, size * 0.85);
        img.text(fonts, &fonts.bold, letter, size * 0.85, pen + (badge - lw) / 2.0, top, badge, ACCENT_FG);
        pen += badge + gap;
        img.text(fonts, &fonts.regular, word, size, pen, top, badge, MUTED);
        pen += text_width(&fonts.regular, word, size) + space;
    }
}

/// Copies the game's frame into our XRGB8888 buffer (formats seen: XR24, AR24; RG16 too).
pub fn copy_frame(dst: &mut Image, src: &[u8], src_pitch: usize, fourcc: u32) {
    const XR24: u32 = u32::from_le_bytes(*b"XR24");
    const AR24: u32 = u32::from_le_bytes(*b"AR24");
    const RG16: u32 = u32::from_le_bytes(*b"RG16");
    for y in 0..dst.h {
        for x in 0..dst.w {
            let o = y * dst.pitch + x * 4;
            let px = match fourcc {
                XR24 | AR24 => {
                    let i = y * src_pitch + x * 4;
                    if i + 3 < src.len() { [src[i], src[i + 1], src[i + 2], 0xff] } else { [0, 0, 0, 0xff] }
                }
                RG16 => {
                    let i = y * src_pitch + x * 2;
                    if i + 1 < src.len() {
                        let v = u16::from_le_bytes([src[i], src[i + 1]]);
                        let (r, g, b) = ((v >> 11) & 31, (v >> 5) & 63, v & 31);
                        [(b << 3) as u8, (g << 2) as u8, (r << 3) as u8, 0xff]
                    } else {
                        [0, 0, 0, 0xff]
                    }
                }
                _ => [0, 0, 0, 0xff],
            };
            dst.px[o..o + 4].copy_from_slice(&px);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fonts() -> Option<Fonts> {
        // the launcher's Roboto when the host has it (LUME_FONT* or the Alpine path)
        Fonts::bundled().or_else(|| {
            let p = ["/usr/share/fonts/roboto/Roboto-Regular.ttf", "/usr/share/fonts/google-roboto/Roboto-Regular.ttf"]
                .into_iter()
                .find(|p| std::path::Path::new(p).exists())?;
            let f = fontdue::Font::from_bytes(std::fs::read(p).ok()?, fontdue::FontSettings::default()).ok()?;
            Some(Fonts::new(f.clone(), f.clone(), f))
        })
    }

    #[test]
    fn parse_the_menu_line() {
        let s = parse("Alpha|Voltar ao jogo|Encerrar jogo|Reiniciar|1\n").unwrap();
        assert_eq!(s.title, "Alpha");
        assert_eq!(s.items, ["Voltar ao jogo", "Encerrar jogo", "Reiniciar"]);
        assert_eq!(s.focus, 1);
        assert_eq!(parse("A|B|9").unwrap().focus, 0, "focus past the end: the last item");
        for bad in ["", "-", "A|1", "A|B|x"] {
            assert!(parse(bad).is_none(), "{bad:?}");
        }
    }

    #[test]
    fn copy_converts_the_formats() {
        let mut buf = vec![0u8; 2 * 1 * 4];
        let mut img = Image { px: &mut buf, w: 2, h: 1, pitch: 8 };
        copy_frame(&mut img, &[0x10, 0x20, 0x30, 0x00, 0x40, 0x50, 0x60, 0x00], 8, u32::from_le_bytes(*b"XR24"));
        assert_eq!(img.get(0, 0), 0x302010);
        copy_frame(&mut img, &[0x00, 0xf8, 0xe0, 0x07], 4, u32::from_le_bytes(*b"RG16"));
        assert_eq!(img.get(0, 0), 0xf80000, "pure red in RGB565");
        assert_eq!(img.get(1, 0), 0x00fc00, "pure green in RGB565");
    }

    #[test]
    fn layout_matches_the_prototype_table() {
        let Some(f) = fonts() else {
            eprintln!("skipped: no Roboto on this host");
            return;
        };
        let st = parse("Exemplo de Jogo (Rev 1)|Voltar ao jogo|Encerrar jogo|Reiniciar|Menu do RetroArch|0").unwrap();
        // design-das-telas.md: panel of 4 items, 163/102 313x276 (pt)
        let (x, y, w, h) = panel_rect(&f, &st, 640.0, 480.0);
        assert_eq!(h, 276.0);
        assert_eq!(y, 102.0);
        // 313 px in the capture, made with Noto (the font of the capture's container); with
        // Roboto the title fits the 300 px minimum width of the panel
        assert!((300.0..=320.0).contains(&w), "width {w}");
        assert_eq!(x, ((640.0 - w) / 2.0).round(), "centred");
        let mut buf = vec![0u8; 640 * 480 * 4];
        let mut img = Image { px: &mut buf, w: 640, h: 480, pitch: 640 * 4 };
        draw(&mut img, &f, &st, ("Escolher", "Voltar"), None);
        // the background dimmed (black at 67%), the panel, the focused row in the accent
        assert_eq!(img.get(5, 5), 0x000000);
        assert_eq!(img.get(x as usize + 4, y as usize + 40), PANEL);
        assert_eq!(img.get(x as usize + 12, y as usize + 68 + 3), ACCENT, "row 0 at y+68");
        assert_ne!(img.get(x as usize + 12, y as usize + 68 + 47 + 3), ACCENT, "row 1 is not focused");
        // some text pixel of the title (not the plain panel) in the title line
        let title_has_text = (0..200).any(|dx| img.get(x as usize + 24 + dx, y as usize + 29) != PANEL);
        assert!(title_has_text);
        // the A badge of the footer in the accent at y 443..466
        let badge = (0..640).any(|xx| img.get(xx, 454) == ACCENT);
        assert!(badge);
        // LUME_MENU_PNG=<dir>: the picture, to look at (not part of the check)
        if let Ok(dir) = std::env::var("LUME_MENU_PNG") {
            write_ppm(&img, &std::path::Path::new(&dir).join("menu-pt.ppm"));
        }
    }

    /// A PPM, which the review converts or opens as it is (no image crate here).
    fn write_ppm(img: &Image, path: &std::path::Path) {
        let mut out = format!("P6\n{} {}\n255\n", img.w, img.h).into_bytes();
        for y in 0..img.h {
            for x in 0..img.w {
                let c = img.get(x, y);
                out.extend_from_slice(&[(c >> 16) as u8, (c >> 8) as u8, c as u8]);
            }
        }
        std::fs::write(path, out).unwrap();
    }

    #[test]
    fn the_fade_mixes_toward_the_menu() {
        let mut dst = [0u8; 4];
        mix_into(&mut dst, &[0, 100, 200, 255], &[200, 100, 0, 255], 128);
        assert_eq!(dst, [100, 100, 100, 255]);
        mix_into(&mut dst, &[0, 100, 200, 255], &[200, 100, 0, 255], 256);
        assert_eq!(dst, [200, 100, 0, 255]);
    }
}
