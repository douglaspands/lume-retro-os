//! Thumbnails of one system (lume-launcher D4): `cache/thumbs/<id>.bin`, fixed RGB565 slots
//! of the tile size, so the interface never decodes an image, it only copies a slot into a
//! texture.
//!
//! ```text
//! <id>.bin   "LUMETHB2", w u16, h u16, count u32, then count slots of 4 + w*h*2 bytes:
//!            the size of the image inside the slot (cw u16, ch u16, centered), then the
//!            pixels; the interface draws only that part, fitted to its tile
//! <id>.keys  one line per slot: "<size> <mtime_ns>\t<image path>"; an invalid image is a
//!            line "! <size> <mtime_ns>\t<image path>" with no slot
//! ```
//!
//! The key of a slot is the image path, size and mtime plus the tile size (in the header):
//! only an image that changed is decoded again. A file whose signature is not PNG, JPEG or
//! WebP, or that fails to decode, has no slot (the grid draws the generated box).

use std::collections::HashMap;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::{Path, PathBuf};

use image::imageops::FilterType;
use image::{ImageFormat, ImageReader, Limits, RgbImage};

pub const MAGIC: &[u8; 8] = b"LUMETHB2";
pub const HEADER: usize = 16;
/// Decoding limit per image (a scraper image is a few MB decoded)
const MAX_ALLOC: u64 = 64 << 20;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Tile {
    pub w: u16,
    pub h: u16,
}

impl Tile {
    /// Bytes of one slot: the content size (4) and the pixels.
    pub fn slot_bytes(self) -> usize {
        4 + self.pixel_bytes()
    }

    pub fn pixel_bytes(self) -> usize {
        self.w as usize * self.h as usize * 2
    }

    pub fn packed(self) -> u32 {
        (self.w as u32) << 16 | self.h as u32
    }

    pub fn parse(s: &str) -> Option<Tile> {
        let (w, h) = s.split_once('x')?;
        let t = Tile { w: w.parse().ok()?, h: h.parse().ok()? };
        (t.w >= 8 && t.h >= 8 && t.w <= 1024 && t.h <= 1024).then_some(t)
    }
}

/// Image format from the first bytes; `None` for anything else (text named .png, HTML...).
pub fn sniff(head: &[u8]) -> Option<ImageFormat> {
    if head.starts_with(b"\x89PNG\r\n\x1a\n") {
        Some(ImageFormat::Png)
    } else if head.starts_with(&[0xFF, 0xD8, 0xFF]) {
        Some(ImageFormat::Jpeg)
    } else if head.len() >= 12 && &head[..4] == b"RIFF" && &head[8..12] == b"WEBP" {
        Some(ImageFormat::WebP)
    } else {
        None
    }
}

fn to_rgb565(img: &RgbImage, tile: Tile) -> Vec<u8> {
    // contain: keep the aspect, centered on black
    let (iw, ih) = (img.width().max(1), img.height().max(1));
    let scale = f64::min(tile.w as f64 / iw as f64, tile.h as f64 / ih as f64);
    let (sw, sh) = (((iw as f64 * scale).round() as u32).clamp(1, tile.w as u32), ((ih as f64 * scale).round() as u32).clamp(1, tile.h as u32));
    let small = image::imageops::resize(img, sw, sh, FilterType::Triangle);
    let (ox, oy) = ((tile.w as u32 - sw) / 2, (tile.h as u32 - sh) / 2);
    let mut out = vec![0u8; tile.slot_bytes()];
    out[0..2].copy_from_slice(&(sw as u16).to_le_bytes());
    out[2..4].copy_from_slice(&(sh as u16).to_le_bytes());
    for (x, y, p) in small.enumerate_pixels() {
        let [r, g, b] = p.0;
        let v: u16 = ((r as u16 >> 3) << 11) | ((g as u16 >> 2) << 5) | (b as u16 >> 3);
        let at = 4 + (((y + oy) * tile.w as u32 + (x + ox)) * 2) as usize;
        out[at..at + 2].copy_from_slice(&v.to_le_bytes());
    }
    out
}

/// Decodes and scales one image file; `None` if it is not a valid PNG, JPEG or WebP.
pub fn render(path: &Path, tile: Tile) -> Option<Vec<u8>> {
    let mut f = std::fs::File::open(path).ok()?;
    let mut head = [0u8; 12];
    let n = f.read(&mut head).ok()?;
    let format = sniff(&head[..n])?;
    let mut reader = ImageReader::open(path).ok()?;
    reader.set_format(format);
    let mut limits = Limits::default();
    limits.max_alloc = Some(MAX_ALLOC);
    reader.limits(limits);
    let img = reader.decode().ok()?.to_rgb8();
    Some(to_rgb565(&img, tile))
}

type Key = (u64, i64);

fn file_key(path: &Path) -> Option<Key> {
    let m = std::fs::metadata(path).ok()?;
    m.is_file().then(|| (m.len(), m.mtime() * 1_000_000_000 + m.mtime_nsec()))
}

struct Old {
    tile: Option<Tile>,
    bin: Vec<u8>,
    slots: HashMap<String, (Key, usize)>,
    /// Images known to be invalid, by key: not opened again until they change
    invalid: HashMap<String, Key>,
}

fn parse_key(k: &str) -> Option<Key> {
    let mut it = k.split(' ');
    Some((it.next()?.parse().ok()?, it.next()?.parse().ok()?))
}

fn load_old(bin: &Path, keys: &Path) -> Old {
    let mut old = Old { tile: None, bin: Vec::new(), slots: HashMap::new(), invalid: HashMap::new() };
    let Ok(b) = std::fs::read(bin) else { return old };
    if b.len() < HEADER || &b[..8] != MAGIC {
        return old;
    }
    let tile = Tile { w: u16::from_le_bytes([b[8], b[9]]), h: u16::from_le_bytes([b[10], b[11]]) };
    let count = u32::from_le_bytes(b[12..16].try_into().unwrap()) as usize;
    if b.len() != HEADER + count * tile.slot_bytes() {
        return old;
    }
    let text = std::fs::read_to_string(keys).unwrap_or_default();
    let mut slot = 0;
    for line in text.lines() {
        let Some((k, path)) = line.split_once('\t') else { continue };
        if let Some(k) = k.strip_prefix("! ") {
            if let Some(key) = parse_key(k) {
                old.invalid.insert(path.to_string(), key);
            }
            continue;
        }
        if slot < count {
            if let Some(key) = parse_key(k) {
                old.slots.insert(path.to_string(), (key, slot));
            }
        }
        slot += 1;
    }
    old.tile = Some(tile);
    old.bin = b;
    old
}

pub struct Built {
    /// Slot of each image path given (absent: no thumbnail)
    pub slots: HashMap<String, u32>,
    /// Images decoded in this run (the others were copied from the old file)
    pub decoded: usize,
    pub changed: bool,
}

/// Builds the thumbnails of `images` (paths relative to `system_dir`, in game order) into
/// `bin` and `keys`, reusing every slot whose key did not change.
pub fn build(system_dir: &Path, images: &[String], tile: Tile, bin: &Path, keys: &Path) -> std::io::Result<Built> {
    let old = load_old(bin, keys);
    let reuse = old.tile == Some(tile);
    let mut out_bin = Vec::new();
    out_bin.extend_from_slice(MAGIC);
    out_bin.extend_from_slice(&tile.w.to_le_bytes());
    out_bin.extend_from_slice(&tile.h.to_le_bytes());
    out_bin.extend_from_slice(&0u32.to_le_bytes()); // count, filled in at the end
    let mut out_keys = String::new();
    let mut slots = HashMap::new();
    let mut decoded = 0;
    let mut count = 0u32;
    for rel in images {
        if slots.contains_key(rel) {
            continue;
        }
        let full: PathBuf = if rel.starts_with('/') { PathBuf::from(rel) } else { system_dir.join(rel) };
        let Some(key) = file_key(&full) else { continue };
        if old.invalid.get(rel) == Some(&key) {
            out_keys.push_str(&format!("! {} {}\t{rel}\n", key.0, key.1));
            continue;
        }
        let pixels = match old.slots.get(rel) {
            Some((k, slot)) if reuse && *k == key => {
                let at = HEADER + slot * tile.slot_bytes();
                Some(old.bin[at..at + tile.slot_bytes()].to_vec())
            }
            _ => {
                decoded += 1;
                render(&full, tile)
            }
        };
        let Some(pixels) = pixels else {
            out_keys.push_str(&format!("! {} {}\t{rel}\n", key.0, key.1));
            continue;
        };
        out_bin.extend_from_slice(&pixels);
        out_keys.push_str(&format!("{} {}\t{rel}\n", key.0, key.1));
        slots.insert(rel.clone(), count);
        count += 1;
    }
    out_bin[12..16].copy_from_slice(&count.to_le_bytes());
    let changed = out_bin != old.bin || std::fs::read_to_string(keys).unwrap_or_default() != out_keys;
    if changed {
        lume_core::atomic::write(bin, &out_bin)?;
        lume_core::atomic::write(keys, out_keys.as_bytes())?;
    }
    Ok(Built { slots, decoded, changed })
}

pub struct Slot<'a> {
    pub tile: Tile,
    /// size of the image inside the tile, centered
    pub content: (u16, u16),
    pub pixels: &'a [u8],
}

/// Reads one slot of a thumbnails file (what the interface does after mapping it).
pub fn read_slot(bin: &[u8], slot: u32) -> Option<Slot<'_>> {
    if bin.len() < HEADER || &bin[..8] != MAGIC {
        return None;
    }
    let tile = Tile { w: u16::from_le_bytes([bin[8], bin[9]]), h: u16::from_le_bytes([bin[10], bin[11]]) };
    let at = HEADER + slot as usize * tile.slot_bytes();
    let s = bin.get(at..at + tile.slot_bytes())?;
    let content = (u16::from_le_bytes([s[0], s[1]]).min(tile.w), u16::from_le_bytes([s[2], s[3]]).min(tile.h));
    Some(Slot { tile, content, pixels: &s[4..] })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn dir(name: &str) -> PathBuf {
        let d = std::env::temp_dir().join(format!("lume-thumbs-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&d);
        std::fs::create_dir_all(d.join("images")).unwrap();
        d
    }

    fn png(path: &Path, w: u32, h: u32, rgb: [u8; 3]) {
        RgbImage::from_pixel(w, h, image::Rgb(rgb)).save_with_format(path, ImageFormat::Png).unwrap();
    }

    #[test]
    fn signature() {
        assert_eq!(sniff(b"\x89PNG\r\n\x1a\nxxxx"), Some(ImageFormat::Png));
        assert_eq!(sniff(&[0xFF, 0xD8, 0xFF, 0xE0]), Some(ImageFormat::Jpeg));
        assert_eq!(sniff(b"RIFF\0\0\0\0WEBPVP8 "), Some(ImageFormat::WebP));
        assert_eq!(sniff(b"<html>"), None);
    }

    #[test]
    fn text_named_png_has_no_cover_and_only_changed_image_is_redone() {
        let d = dir("rebuild");
        let tile = Tile { w: 32, h: 24 };
        png(&d.join("images/a.png"), 64, 64, [255, 0, 0]);
        png(&d.join("images/b.png"), 40, 20, [0, 0, 255]);
        std::fs::write(d.join("images/c.png"), "404 Not Found").unwrap();
        let images: Vec<String> = ["images/a.png", "images/b.png", "images/c.png", "images/missing.png"].iter().map(|s| s.to_string()).collect();
        let (bin, keys) = (d.join("cache/t.bin"), d.join("cache/t.keys"));
        let first = build(&d, &images, tile, &bin, &keys).unwrap();
        assert_eq!(first.decoded, 3);
        assert_eq!(first.slots.len(), 2);
        assert!(!first.slots.contains_key("images/c.png"));
        // red square, contained: centered red pixel, black bars on the sides
        let data = std::fs::read(&bin).unwrap();
        let s = read_slot(&data, first.slots["images/a.png"]).unwrap();
        assert_eq!(s.tile, tile);
        assert_eq!(s.content, (24, 24)); // a square in a 32x24 tile
        let px = s.pixels;
        let at = |x: usize, y: usize| u16::from_le_bytes([px[(y * 32 + x) * 2], px[(y * 32 + x) * 2 + 1]]);
        assert_eq!(at(16, 12), 0xF800);
        assert_eq!(at(0, 12), 0);
        let b = read_slot(&data, first.slots["images/b.png"]).unwrap();
        assert_eq!(b.content, (32, 16)); // 40x20, the width fills the tile

        // nothing changed: nothing decoded, nothing written
        let mtime = std::fs::metadata(&bin).unwrap().modified().unwrap();
        let again = build(&d, &images, tile, &bin, &keys).unwrap();
        assert_eq!((again.decoded, again.changed), (0, false));
        assert_eq!(std::fs::metadata(&bin).unwrap().modified().unwrap(), mtime);

        // only b changed (other content and size): one decode
        png(&d.join("images/b.png"), 30, 30, [0, 255, 0]);
        let third = build(&d, &images, tile, &bin, &keys).unwrap();
        assert_eq!(third.decoded, 1); // the invalid c is remembered by its key
        assert!(third.changed);

        // another tile size: every valid image is redone (an invalid one stays invalid)
        let other = build(&d, &images, Tile { w: 16, h: 16 }, &bin, &keys).unwrap();
        assert_eq!(other.decoded, 2);
    }

    #[test]
    fn tile_parse() {
        assert_eq!(Tile::parse("128x96"), Some(Tile { w: 128, h: 96 }));
        assert_eq!(Tile::parse("2x2"), None);
        assert_eq!(Tile::parse("x"), None);
    }
}
