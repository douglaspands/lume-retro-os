//! `lume-menu --serve PGID`: one process per game, started by lume-run with the game
//! (device-fixes 9.14). It allocates every buffer it draws into once, as soon as the game has
//! a screen, and reuses them: the menu (two full screens, also used by the chord hint) and the
//! status bar (two strips). After that it blocks on its stdin: nothing runs while the menu,
//! the hint and the bar are off.
//!
//! ```text
//! stdin   menu TITLE|ITEM|...|FOCUS   open the menu (the game already stopped) or redraw it
//!         menu -                      give the screen back to the game
//!         bar TEXT | bar -            the status bar, renewed every second, or off
//!         hint TEXT | hint -          the chord hint ("Fn+B\tName|..."), or off
//!         end of stdin                everything off and given back, exit
//! stdout  "menu ok" once the menu's first picture is on the screen, "menu fail WHY" when it
//!         is not (lume-run then uses RetroArch's widget), "menu closed" after "menu -"
//! ```
//!
//! The bar and the hint answer nothing: their failures go to the log, once per new reason.

use crate::bar;
use crate::draw::{self, Fonts, Image};
use crate::drm::{self, Buffer, Card, FbCmd2, GameFile, PlaneSet};
use std::time::Instant;

/// The two overlays of ours, each on a plane of its own above the game's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Slot {
    Bar = 0,
    Hint = 1,
}

/// What an overlay shows: `w x h` pixels of buffer `buf` from `(src_x, src_y)`, at `(x, y)`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Pic {
    pub buf: usize,
    pub x: i32,
    pub y: i32,
    pub w: u32,
    pub h: u32,
    pub src_x: u32,
    pub src_y: u32,
}

/// The display side, a trait so the server's logic is tested without a screen.
pub trait Gpu {
    /// The screen's size once the game has one (None: not yet).
    fn screen(&mut self) -> Result<Option<(u32, u32)>, String>;
    /// A new buffer of `w x h` pixels (4 bytes each); its index.
    fn alloc(&mut self, w: u32, h: u32) -> Result<usize, String>;
    /// Frees every buffer (a failed preparation, or a new screen size).
    fn free_all(&mut self);
    /// The pixels of a buffer and its pitch.
    fn pixels(&mut self, buf: usize) -> (&mut [u8], usize);
    /// Takes the game's screen for the menu, copying its last picture into `frame`
    /// (`w x h`, XRGB8888).
    fn take(&mut self, frame: &mut [u8], w: usize, h: usize) -> Result<(), String>;
    /// Puts our buffer on the game's plane (after take).
    fn show(&mut self, buf: usize) -> Result<(), String>;
    /// The game's picture back on its plane.
    fn give_back(&mut self);
    /// Shows an overlay, or takes it away (None).
    fn overlay(&mut self, slot: Slot, pic: Option<Pic>) -> Result<(), String>;
}

pub struct Server<G: Gpu> {
    pub gpu: G,
    fonts: Fonts,
    hints: (String, String),
    warn: Option<String>,
    /// the screen the buffers were made for (None: not prepared yet)
    size: Option<(u32, u32)>,
    menu_bufs: [usize; 2],
    bar_bufs: [usize; 2],
    /// the game's last picture, the dimmed base of the current list, the next picture
    frame: Vec<u8>,
    base: Vec<u8>,
    next: Vec<u8>,
    menu_open: bool,
    /// which of the two buffers is on the screen (index into menu_bufs / bar_bufs)
    menu_front: Option<usize>,
    bar_front: Option<usize>,
    hint_front: Option<usize>,
    base_key: Option<(String, Vec<String>)>,
    /// the last failure logged for each overlay (a new line only when it changes)
    last_err: [Option<String>; 2],
}

fn other(i: Option<usize>) -> usize {
    if i == Some(0) { 1 } else { 0 }
}

impl<G: Gpu> Server<G> {
    pub fn new(gpu: G, fonts: Fonts, hints: (String, String), warn: Option<String>) -> Server<G> {
        Server {
            gpu,
            fonts,
            hints,
            warn,
            size: None,
            menu_bufs: [0; 2],
            bar_bufs: [0; 2],
            frame: Vec::new(),
            base: Vec::new(),
            next: Vec::new(),
            menu_open: false,
            menu_front: None,
            bar_front: None,
            hint_front: None,
            base_key: None,
            last_err: [None, None],
        }
    }

    pub fn prepared(&self) -> bool {
        self.size.is_some()
    }

    /// Allocates the buffers for the game's screen, once; again only if the screen's size
    /// changes. Ok(false): the game has no screen yet.
    pub fn prepare(&mut self) -> Result<bool, String> {
        let Some((w, h)) = self.gpu.screen()? else { return Ok(false) };
        if self.size == Some((w, h)) {
            return Ok(true);
        }
        if self.size.is_some() {
            eprintln!("lume-menu: the screen is now {w}x{h}: buffers made again");
            self.release();
        }
        let t = Instant::now();
        let bh = bar::height(h);
        let made = (|| -> Result<([usize; 2], [usize; 2]), String> {
            let m = [self.gpu.alloc(w, h)?, self.gpu.alloc(w, h)?];
            let b = [self.gpu.alloc(w, bh)?, self.gpu.alloc(w, bh)?];
            Ok((m, b))
        })();
        match made {
            Ok((m, b)) => {
                self.menu_bufs = m;
                self.bar_bufs = b;
                // calloc'd: the pages are only touched by the first menu
                let n = w as usize * h as usize * 4;
                self.frame = vec![0; n];
                self.base = vec![0; n];
                self.next = vec![0; n];
                self.size = Some((w, h));
                eprintln!("lume-menu: buffers ready for {w}x{h} in {} ms (menu 2x{} KiB, bar 2x{} KiB)", t.elapsed().as_millis(), n / 1024, w as usize * bh as usize * 4 / 1024);
                Ok(true)
            }
            Err(e) => {
                self.gpu.free_all();
                Err(format!("our buffer: {e}"))
            }
        }
    }

    fn ready(&mut self) -> Result<(u32, u32), String> {
        match self.prepare()? {
            true => Ok(self.size.expect("prepared")),
            false => Err("the game has no screen yet".into()),
        }
    }

    /// Everything off, the buffers freed (a new screen size).
    fn release(&mut self) {
        self.overlay_off(Slot::Hint);
        self.overlay_off(Slot::Bar);
        if self.menu_open {
            self.gpu.give_back();
            self.menu_open = false;
        }
        self.menu_front = None;
        self.gpu.free_all();
        self.size = None;
    }

    /// One line of stdin; `out` gets the answers.
    pub fn handle(&mut self, line: &str, out: &mut dyn FnMut(&str)) {
        let line = line.trim_end_matches(['\n', '\r']);
        let (cmd, arg) = line.split_once(' ').unwrap_or((line, ""));
        match cmd {
            "menu" => self.menu(arg, out),
            "bar" => self.bar(arg),
            "hint" => self.hint(arg),
            "" => {}
            _ => eprintln!("lume-menu: unknown command {cmd:?}"),
        }
    }

    /// The end of stdin: the screen back as the game left it. True when the menu was open,
    /// that is lume-run ended (killed) while the game was stopped for it: the caller wakes
    /// the game up, nobody else will (lume-hud-actions 3.5).
    pub fn finish(&mut self) -> bool {
        self.overlay_off(Slot::Hint);
        self.overlay_off(Slot::Bar);
        if self.menu_open {
            self.gpu.give_back();
            self.menu_open = false;
            return true;
        }
        false
    }

    fn menu(&mut self, arg: &str, out: &mut dyn FnMut(&str)) {
        if arg.trim() == "-" {
            if self.menu_open {
                self.gpu.give_back();
                self.menu_open = false;
                self.menu_front = None;
            }
            out("menu closed");
            return;
        }
        let Some(st) = draw::parse(arg) else {
            if !self.menu_open {
                out("menu fail bad menu line");
            }
            return;
        };
        let t = Instant::now();
        let first = !self.menu_open;
        let (w, h) = if first {
            let (w, h) = match self.ready() {
                Ok(s) => s,
                Err(e) => return out(&format!("menu fail {e}")),
            };
            // the hint shares the menu's buffers, and the menu covers the screen anyway
            self.overlay_off(Slot::Hint);
            if let Err(e) = self.gpu.take(&mut self.frame, w as usize, h as usize) {
                self.gpu.give_back();
                return out(&format!("menu fail {e}"));
            }
            self.menu_open = true;
            self.base_key = None;
            (w as usize, h as usize)
        } else {
            let (w, h) = self.size.expect("open menu has buffers");
            (w as usize, h as usize)
        };
        let key = (st.title.clone(), st.items.clone());
        if self.base_key.as_ref() != Some(&key) {
            self.base.copy_from_slice(&self.frame);
            let mut img = Image { px: &mut self.base, w, h, pitch: w * 4 };
            draw::draw_base(&mut img, &self.fonts, &st, (&self.hints.0, &self.hints.1));
            self.base_key = Some(key);
        }
        self.next.copy_from_slice(&self.base);
        let mut img = Image { px: &mut self.next, w, h, pitch: w * 4 };
        draw::draw_items(&mut img, &self.fonts, &st, self.warn.as_deref());
        // the first picture fades in over a few frames (the user asked for a smoother
        // appearance, J2 on the GA36); later ones are drawn off the screen and swapped in
        let steps: &[u32] = if first { &[72, 140, 200, 256] } else { &[256] };
        for (i, &a) in steps.iter().enumerate() {
            let back = other(self.menu_front);
            let buf = self.menu_bufs[back];
            {
                let (px, pitch) = self.gpu.pixels(buf);
                for y in 0..h {
                    let row = &mut px[y * pitch..y * pitch + w * 4];
                    let to = &self.next[y * w * 4..(y + 1) * w * 4];
                    if a == 256 {
                        row.copy_from_slice(to);
                    } else {
                        draw::mix_into(row, &self.frame[y * w * 4..(y + 1) * w * 4], to, a);
                    }
                }
            }
            match self.gpu.show(buf) {
                Ok(()) => self.menu_front = Some(back),
                Err(e) if first && i == 0 => {
                    self.gpu.give_back();
                    self.menu_open = false;
                    self.menu_front = None;
                    return out(&format!("menu fail SETPLANE: {e}"));
                }
                Err(e) => {
                    eprintln!("lume-menu: menu not redrawn: {e}");
                    break;
                }
            }
            if first && i == 0 {
                out("menu ok");
                eprintln!("lume-menu: first picture in {} ms", t.elapsed().as_millis());
            }
        }
        eprintln!("lume-menu: {} in {} ms", if first { "shown" } else { "redraw" }, t.elapsed().as_millis());
    }

    fn note(&mut self, slot: Slot, err: Option<String>) {
        let i = slot as usize;
        match err {
            Some(e) if self.last_err[i].as_ref() != Some(&e) => {
                eprintln!("lume-menu: {} not shown: {e}", if slot == Slot::Bar { "bar" } else { "hint" });
                self.last_err[i] = Some(e);
            }
            Some(_) => {}
            None => {
                if self.last_err[i].take().is_some() {
                    eprintln!("lume-menu: {} shown again", if slot == Slot::Bar { "bar" } else { "hint" });
                }
            }
        }
    }

    fn overlay_off(&mut self, slot: Slot) {
        let front = match slot {
            Slot::Bar => &mut self.bar_front,
            Slot::Hint => &mut self.hint_front,
        };
        if front.take().is_some() {
            if let Err(e) = self.gpu.overlay(slot, None) {
                eprintln!("lume-menu: {slot:?} not taken away: {e}");
            }
        }
        self.last_err[slot as usize] = None;
    }

    fn bar(&mut self, text: &str) {
        if text.trim() == "-" {
            return self.overlay_off(Slot::Bar);
        }
        let (w, h) = match self.ready() {
            Ok(s) => s,
            Err(e) => return self.note(Slot::Bar, Some(e)),
        };
        let bh = bar::height(h);
        let back = other(self.bar_front);
        let buf = self.bar_bufs[back];
        {
            let (px, pitch) = self.gpu.pixels(buf);
            let mut s = bar::Strip { px, w: w as usize, h: bh as usize, pitch };
            bar::draw(&mut s, &self.fonts, text, h as f32);
        }
        match self.gpu.overlay(Slot::Bar, Some(Pic { buf, x: 0, y: 0, w, h: bh, src_x: 0, src_y: 0 })) {
            Ok(()) => {
                self.bar_front = Some(back);
                self.note(Slot::Bar, None);
            }
            Err(e) => self.note(Slot::Bar, Some(e)),
        }
    }

    fn hint(&mut self, text: &str) {
        if text.trim() == "-" {
            return self.overlay_off(Slot::Hint);
        }
        if self.menu_open {
            return;
        }
        let (sw, sh) = match self.ready() {
            Ok(s) => s,
            Err(e) => return self.note(Slot::Hint, Some(e)),
        };
        let rows = bar::hint_rows(text);
        let (w, h) = bar::hint_size(&self.fonts, &rows, sh as f32);
        let (w, h) = (w.min(sw), h.min(sh));
        let (x, y) = ((sw - w) / 2, (sh - h) / 2);
        // a box of the menu's buffer that is not on the screen (the menu is closed)
        let back = other(self.hint_front);
        let buf = self.menu_bufs[back];
        {
            let (px, pitch) = self.gpu.pixels(buf);
            let off = y as usize * pitch + x as usize * 4;
            let mut s = bar::Strip { px: &mut px[off..], w: w as usize, h: h as usize, pitch };
            bar::draw_hint(&mut s, &self.fonts, &rows, sh as f32);
        }
        let pic = Pic { buf, x: x as i32, y: y as i32, w, h, src_x: x, src_y: y };
        match self.gpu.overlay(Slot::Hint, Some(pic)) {
            Ok(()) => {
                self.hint_front = Some(back);
                self.note(Slot::Hint, None);
            }
            Err(e) => self.note(Slot::Hint, Some(e)),
        }
    }
}

/// The game's screen while the menu is on it.
struct Taken {
    file: GameFile,
    plane: u32,
    game: FbCmd2,
}

/// The real display: our card for the buffers, the game's file for each change.
pub struct DrmGpu {
    pgid: i32,
    // dropped in this order: our framebuffers, the game's file, our card
    bufs: Vec<Buffer>,
    menu: Option<Taken>,
    card: Option<Card>,
    /// the CRTC of the screen: (id, its bit in possible_crtcs)
    crtc: Option<(u32, u32)>,
    /// where the game's master file was last time (pid, fd number)
    last: Option<(i32, i32)>,
    /// each overlay's plane and format
    overlays: [Option<(u32, u32)>; 2],
}

impl DrmGpu {
    pub fn new(pgid: i32) -> DrmGpu {
        DrmGpu { pgid, bufs: Vec::new(), menu: None, card: None, crtc: None, last: None, overlays: [None, None] }
    }

    fn our_fbs(&self) -> Vec<u32> {
        self.bufs.iter().flat_map(|b| [b.xrgb, b.argb]).filter(|&f| f != 0).collect()
    }
}

impl Gpu for DrmGpu {
    fn screen(&mut self) -> Result<Option<(u32, u32)>, String> {
        if self.card.is_none() {
            // only once the game has its card open, so the game is the master and our own
            // open never takes the screen from it
            self.card = Card::of_group(self.pgid);
        }
        let Some(card) = &self.card else { return Ok(None) };
        Ok(card.active_crtc().map(|(id, bit, w, h)| {
            self.crtc = Some((id, bit));
            (w, h)
        }))
    }

    fn alloc(&mut self, w: u32, h: u32) -> Result<usize, String> {
        let card = self.card.as_ref().ok_or("no DRM card")?;
        let b = Buffer::new(card, w, h).map_err(|e| e.to_string())?;
        self.bufs.push(b);
        Ok(self.bufs.len() - 1)
    }

    fn free_all(&mut self) {
        // the kernel takes a plane off when its framebuffer goes
        self.overlays = [None, None];
        self.bufs.clear();
    }

    fn pixels(&mut self, buf: usize) -> (&mut [u8], usize) {
        let b = &mut self.bufs[buf];
        let pitch = b.pitch;
        (b.pixels(), pitch)
    }

    fn take(&mut self, frame: &mut [u8], w: usize, h: usize) -> Result<(), String> {
        let card = self.card.as_ref().ok_or("no DRM card")?;
        let (crtc, _) = self.crtc.ok_or("no screen")?;
        let file = GameFile::find(self.pgid, Some(card), &mut self.last)?;
        let ours = self.our_fbs();
        let planes = card.planes();
        let gp = drm::game_plane(&planes, crtc, &ours).ok_or("no plane with the game's picture")?;
        let plane = gp.id;
        let game = {
            let fr = file.frame(gp.fb_id).ok_or("cannot read the game's framebuffer")?;
            let mut img = Image { px: frame, w, h, pitch: w * 4 };
            match fr.map() {
                Some(m) => draw::copy_frame(&mut img, m.bytes(), fr.fb.pitches[0] as usize, fr.fb.pixel_format),
                None => img.px.fill(0),
            }
            fr.fb
        };
        self.menu = Some(Taken { file, plane, game });
        Ok(())
    }

    fn show(&mut self, buf: usize) -> Result<(), String> {
        let t = self.menu.as_ref().ok_or("the screen is not taken")?;
        let (crtc, _) = self.crtc.ok_or("no screen")?;
        let b = &self.bufs[buf];
        let s = PlaneSet { plane: t.plane, crtc, fb: b.xrgb, x: 0, y: 0, w: b.width, h: b.height, src_x: 0, src_y: 0 };
        t.file.set_plane(&s).map_err(|e| e.to_string())
    }

    fn give_back(&mut self) {
        let (Some(t), Some((crtc, _))) = (self.menu.take(), self.crtc) else { return };
        let s = PlaneSet { plane: t.plane, crtc, fb: t.game.fb_id, x: 0, y: 0, w: t.game.width, h: t.game.height, src_x: 0, src_y: 0 };
        if let Err(e) = t.file.set_plane(&s) {
            eprintln!("lume-menu: the game's picture not put back: {e}");
        }
    }

    fn overlay(&mut self, slot: Slot, pic: Option<Pic>) -> Result<(), String> {
        let card = self.card.as_ref().ok_or("no DRM card")?;
        let (crtc, bit) = self.crtc.ok_or("no screen")?;
        let i = slot as usize;
        // with the menu open the game is stopped and its file is at hand
        let fresh;
        let file = match &self.menu {
            Some(t) => &t.file,
            None => {
                fresh = GameFile::find(self.pgid, Some(card), &mut self.last)?;
                &fresh
            }
        };
        let Some(p) = pic else {
            if let Some((plane, _)) = self.overlays[i].take() {
                file.set_plane(&PlaneSet { plane, ..Default::default() }).map_err(|e| e.to_string())?;
            }
            return Ok(());
        };
        let b = &self.bufs[p.buf];
        let set = |plane: u32, fmt: u32| PlaneSet { plane, crtc, fb: b.fb(fmt), x: p.x, y: p.y, w: p.w, h: p.h, src_x: p.src_x, src_y: p.src_y };
        let current = self.overlays[i];
        if let Some((plane, fmt)) = current {
            if b.fb(fmt) != 0 && file.set_plane(&set(plane, fmt)).is_ok() {
                return Ok(());
            }
        }
        // a plane again: free ones, never the other overlay's nor the menu's
        let mut skip: Vec<u32> = self.overlays[1 - i].map(|o| o.0).into_iter().collect();
        if let Some(t) = &self.menu {
            skip.push(t.plane);
        }
        let planes = card.planes();
        let mut tried = Vec::new();
        for (plane, fmt) in drm::overlay_choices(&planes, bit, current.map(|c| c.0), &skip) {
            if b.fb(fmt) == 0 {
                continue;
            }
            match file.set_plane(&set(plane, fmt)) {
                Ok(()) => {
                    if let Some((old, _)) = current.filter(|c| c.0 != plane) {
                        let _ = file.set_plane(&PlaneSet { plane: old, ..Default::default() });
                    }
                    let after = if tried.is_empty() { String::new() } else { format!(" (refused: {})", tried.join("; ")) };
                    eprintln!("lume-menu: {slot:?} on plane {plane} {}{after}", drm::fourcc(fmt));
                    self.overlays[i] = Some((plane, fmt));
                    return Ok(());
                }
                Err(e) => tried.push(format!("plane {plane} {}: {e}", drm::fourcc(fmt))),
            }
        }
        self.overlays[i] = None;
        Err(if tried.is_empty() { "no free plane on the game's CRTC".into() } else { tried.join("; ") })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A display in memory that counts what the server asks for.
    #[derive(Default)]
    struct Fake {
        screen: Option<(u32, u32)>,
        bufs: Vec<Vec<u8>>,
        allocs: usize,
        fail_alloc_at: Option<usize>,
        takes: usize,
        shown: Vec<usize>,
        given_back: usize,
        overlays: Vec<(Slot, Option<Pic>)>,
        refuse_overlay: bool,
        refuse_take: bool,
    }

    impl Gpu for Fake {
        fn screen(&mut self) -> Result<Option<(u32, u32)>, String> {
            Ok(self.screen)
        }
        fn alloc(&mut self, w: u32, h: u32) -> Result<usize, String> {
            if self.fail_alloc_at == Some(self.allocs) {
                return Err("Out of memory (os error 12)".into());
            }
            self.allocs += 1;
            self.bufs.push(vec![0; (w * h * 4) as usize]);
            Ok(self.bufs.len() - 1)
        }
        fn free_all(&mut self) {
            self.bufs.clear();
        }
        fn pixels(&mut self, buf: usize) -> (&mut [u8], usize) {
            let pitch = self.screen.unwrap().0 as usize * 4;
            (&mut self.bufs[buf], pitch)
        }
        fn take(&mut self, frame: &mut [u8], _w: usize, _h: usize) -> Result<(), String> {
            if self.refuse_take {
                return Err("no process of the group has a DRM card open".into());
            }
            self.takes += 1;
            frame.fill(0x40);
            Ok(())
        }
        fn show(&mut self, buf: usize) -> Result<(), String> {
            self.shown.push(buf);
            Ok(())
        }
        fn give_back(&mut self) {
            self.given_back += 1;
        }
        fn overlay(&mut self, slot: Slot, pic: Option<Pic>) -> Result<(), String> {
            if self.refuse_overlay && pic.is_some() {
                return Err("plane 45 AR24: Invalid argument (os error 22)".into());
            }
            self.overlays.push((slot, pic));
            Ok(())
        }
    }

    fn server(screen: Option<(u32, u32)>) -> Option<Server<Fake>> {
        let Some(fonts) = crate::bar::tests::fonts() else {
            eprintln!("skipped: no Roboto on this host (LUME_TEST_FONTS)");
            return None;
        };
        let fake = Fake { screen, ..Default::default() };
        Some(Server::new(fake, fonts, ("Select".into(), "Back".into()), Some("Force close".into())))
    }

    fn run(s: &mut Server<Fake>, line: &str) -> Vec<String> {
        let mut got = Vec::new();
        s.handle(line, &mut |l| got.push(l.to_string()));
        got
    }

    const MENU: &str = "menu Alpha|Back to game|End game|0";

    #[test]
    fn buffers_are_made_once_when_the_game_has_a_screen() {
        let Some(mut s) = server(None) else { return };
        // no screen yet: nothing made, the server keeps waiting
        assert_eq!(s.prepare(), Ok(false));
        assert_eq!(s.gpu.allocs, 0);
        s.gpu.screen = Some((64, 48));
        assert_eq!(s.prepare(), Ok(true));
        // two for the menu (and the hint), two for the bar
        assert_eq!(s.gpu.allocs, 4);
        assert_eq!(s.prepare(), Ok(true));
        assert_eq!(s.gpu.allocs, 4, "a second preparation makes nothing");
    }

    #[test]
    fn a_second_open_of_the_menu_allocates_nothing() {
        let Some(mut s) = server(Some((64, 48))) else { return };
        s.prepare().unwrap();
        for _ in 0..2 {
            assert_eq!(run(&mut s, MENU), ["menu ok"]);
            assert!(run(&mut s, "menu Alpha|Back to game|End game|1").is_empty(), "a redraw answers nothing");
            assert_eq!(run(&mut s, "menu -"), ["menu closed"]);
        }
        assert_eq!(s.gpu.allocs, 4);
        assert_eq!(s.gpu.takes, 2);
        assert_eq!(s.gpu.given_back, 2);
        // the fade of each opening (4 pictures) and one redraw, alternating the two buffers
        // (after a close the game's picture is on the plane, so the next opening may start
        // on either buffer)
        assert_eq!(s.gpu.shown.len(), 10);
        for open in s.gpu.shown.chunks(5) {
            assert!(open.windows(2).all(|w| w[0] != w[1]), "{:?}", s.gpu.shown);
        }
        // the bar and the hint reuse theirs too
        for t in ["bar FPS 60|CPU 9%", "bar FPS 59|CPU 9%", "hint Fn+B\tMenu", "hint -", "hint Fn+B\tMenu"] {
            run(&mut s, t);
        }
        assert_eq!(s.gpu.allocs, 4);
    }

    #[test]
    fn the_menu_is_made_at_the_first_open_if_the_screen_came_late() {
        let Some(mut s) = server(Some((64, 48))) else { return };
        assert_eq!(run(&mut s, MENU), ["menu ok"]);
        assert_eq!(s.gpu.allocs, 4);
    }

    #[test]
    fn failures_answer_fail_and_leave_the_screen_to_the_game() {
        let Some(mut s) = server(None) else { return };
        assert_eq!(run(&mut s, MENU), ["menu fail the game has no screen yet"]);
        s.gpu.screen = Some((64, 48));
        s.gpu.fail_alloc_at = Some(2);
        assert_eq!(run(&mut s, MENU), ["menu fail our buffer: Out of memory (os error 12)"]);
        assert!(!s.prepared() && s.gpu.bufs.is_empty(), "a half preparation is freed");
        s.gpu.fail_alloc_at = None;
        s.gpu.refuse_take = true;
        assert_eq!(run(&mut s, MENU), ["menu fail no process of the group has a DRM card open"]);
        assert_eq!(run(&mut s, "menu -"), ["menu closed"], "a close always answers");
        s.gpu.refuse_take = false;
        assert_eq!(run(&mut s, MENU), ["menu ok"]);
    }

    #[test]
    fn the_hint_goes_away_when_the_menu_opens_and_waits_while_it_is_open() {
        let Some(mut s) = server(Some((64, 48))) else { return };
        run(&mut s, "hint Fn+B\tMenu");
        assert!(matches!(s.gpu.overlays.last(), Some((Slot::Hint, Some(_)))));
        run(&mut s, MENU);
        assert_eq!(s.gpu.overlays.last(), Some(&(Slot::Hint, None)));
        let n = s.gpu.overlays.len();
        run(&mut s, "hint Fn+B\tMenu");
        assert_eq!(s.gpu.overlays.len(), n, "no hint over the menu");
        // the end of stdin gives everything back
        run(&mut s, "bar FPS 60");
        assert!(s.finish(), "the menu was open: the caller wakes the game up");
        assert_eq!(s.gpu.overlays.last(), Some(&(Slot::Bar, None)));
        assert_eq!(s.gpu.given_back, 1);
        // a second end (nothing open) asks for nothing
        assert!(!s.finish());
    }

    #[test]
    fn the_hint_is_a_box_in_the_middle_of_a_menu_buffer() {
        let Some(mut s) = server(Some((640, 480))) else { return };
        run(&mut s, "hint Fn+B\tMenu|Fn+Start\tEnd game");
        let Some((Slot::Hint, Some(p))) = s.gpu.overlays.last().cloned() else { panic!("{:?}", s.gpu.overlays) };
        assert!(s.menu_bufs.contains(&p.buf));
        assert_eq!((p.x as u32, p.y as u32), (p.src_x, p.src_y));
        assert_eq!((p.x as u32 * 2 + p.w, p.y as u32 * 2 + p.h), (640, 480), "centred");
    }

    #[test]
    fn a_refused_bar_is_logged_once_and_tried_again() {
        let Some(mut s) = server(Some((64, 48))) else { return };
        s.gpu.refuse_overlay = true;
        run(&mut s, "bar FPS 60");
        run(&mut s, "bar FPS 59");
        assert!(s.last_err[0].as_deref().unwrap().contains("Invalid argument"));
        s.gpu.refuse_overlay = false;
        run(&mut s, "bar FPS 58");
        assert!(s.last_err[0].is_none());
        assert_eq!(s.bar_front.map(|i| s.bar_bufs[i]), s.gpu.overlays.last().and_then(|o| o.1).map(|p| p.buf));
    }
}
