//! The Dock's own symbols, drawn by code as alpha masks (no image file and no symbol font):
//! a five-point star (Favorites), a gear (Settings) and a clock (Recent). The prototype draws
//! ★ and ⚙ with a symbol font; Roboto has neither. Each mask is `n` x `n`, 4x4 supersampled.

use std::f32::consts::PI;

/// Rasterizes `inside(x, y)` (coordinates in -1..1, y down) into an `n` x `n` alpha mask.
fn mask(n: u32, inside: impl Fn(f32, f32) -> bool) -> Vec<u8> {
    let mut out = Vec::with_capacity((n * n) as usize);
    for py in 0..n {
        for px in 0..n {
            let mut hits = 0u32;
            for sy in 0..4 {
                for sx in 0..4 {
                    let x = ((px as f32 + (sx as f32 + 0.5) / 4.0) / n as f32) * 2.0 - 1.0;
                    let y = ((py as f32 + (sy as f32 + 0.5) / 4.0) / n as f32) * 2.0 - 1.0;
                    hits += inside(x, y) as u32;
                }
            }
            out.push((hits * 255 / 16) as u8);
        }
    }
    out
}

/// Point in a polygon (even-odd rule).
fn in_polygon(x: f32, y: f32, pts: &[(f32, f32)]) -> bool {
    let mut inside = false;
    let mut j = pts.len() - 1;
    for i in 0..pts.len() {
        let (xi, yi) = pts[i];
        let (xj, yj) = pts[j];
        if (yi > y) != (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi {
            inside = !inside;
        }
        j = i;
    }
    inside
}

/// A filled five-point star, points up, filling the square (inner radius 0.382 of the outer,
/// the regular star), its center a little low so it looks centered.
pub fn star(n: u32) -> Vec<u8> {
    let pts: Vec<(f32, f32)> = (0..10)
        .map(|i| {
            let r = if i % 2 == 0 { 1.0 } else { 0.382 };
            let a = -PI / 2.0 + i as f32 * PI / 5.0;
            (r * a.cos(), 0.1 + r * a.sin())
        })
        .collect();
    mask(n, |x, y| in_polygon(x, y, &pts))
}

/// The same star as an outline (☆, the game menu's "not a favorite"): the star minus a
/// smaller one around the same center.
pub fn star_outline(n: u32) -> Vec<u8> {
    let pts = |k: f32| -> Vec<(f32, f32)> {
        (0..10)
            .map(|i| {
                let r = k * if i % 2 == 0 { 1.0 } else { 0.382 };
                let a = -PI / 2.0 + i as f32 * PI / 5.0;
                (r * a.cos(), 0.1 + r * a.sin())
            })
            .collect()
    };
    let (outer, inner) = (pts(1.0), pts(0.62));
    mask(n, |x, y| in_polygon(x, y, &outer) && !in_polygon(x, y, &inner))
}

/// A gear: eight teeth around a ring, with a hole in the middle.
pub fn gear(n: u32) -> Vec<u8> {
    mask(n, |x, y| {
        let r = (x * x + y * y).sqrt();
        let a = y.atan2(x);
        // a tooth where the angle is within a band of each of 8 directions
        let t = ((a / (2.0 * PI / 8.0)).rem_euclid(1.0) - 0.5).abs();
        let outer = if t < 0.22 { 1.0 } else { 0.76 };
        r <= outer && r >= 0.34
    })
}

/// A clock: a ring and two hands (Recent).
pub fn clock(n: u32) -> Vec<u8> {
    mask(n, |x, y| {
        let r = (x * x + y * y).sqrt();
        let ring = (0.8..=1.0).contains(&r);
        let w = 0.09;
        // the hour hand up to the right, the minute hand straight up
        let minute = x.abs() <= w && (-0.62..=0.0).contains(&y);
        let hour = (y + 0.0).abs() <= w && (0.0..=0.45).contains(&x);
        ring || minute || hour
    })
}

/// Distance from (x, y) to the segment a-b.
fn to_segment(x: f32, y: f32, a: (f32, f32), b: (f32, f32)) -> f32 {
    let (dx, dy) = (b.0 - a.0, b.1 - a.1);
    let t = (((x - a.0) * dx + (y - a.1) * dy) / (dx * dx + dy * dy)).clamp(0.0, 1.0);
    let (px, py) = (a.0 + t * dx, a.1 + t * dy);
    ((x - px).powi(2) + (y - py).powi(2)).sqrt()
}

/// A check mark (✓: the chosen option of a Settings list), two strokes.
pub fn check(n: u32) -> Vec<u8> {
    let (a, b, c) = ((-0.8, 0.05), (-0.25, 0.6), (0.85, -0.65));
    mask(n, |x, y| to_segment(x, y, a, b).min(to_segment(x, y, b, c)) <= 0.14)
}

/// Rasterizes `inside(x, y)`, in view units (`vw` x `vh`, y down), into a `w` x `h` alpha
/// mask, 4x4 supersampled: the icons drawn from an SVG's own coordinates.
fn mask_view(w: u32, h: u32, vw: f32, vh: f32, inside: impl Fn(f32, f32) -> bool) -> Vec<u8> {
    let mut out = Vec::with_capacity((w * h) as usize);
    for py in 0..h {
        for px in 0..w {
            let mut hits = 0u32;
            for sy in 0..4 {
                for sx in 0..4 {
                    let x = (px as f32 + (sx as f32 + 0.5) / 4.0) / w as f32 * vw;
                    let y = (py as f32 + (sy as f32 + 0.5) / 4.0) / h as f32 * vh;
                    hits += inside(x, y) as u32;
                }
            }
            out.push((hits * 255 / 16) as u8);
        }
    }
    out
}

/// The prototype's Wi-Fi icon (its SVG, viewBox 20 x 14): three arcs through (1.5, 5)-(18.5, 5),
/// (4.5, 8)-(15.5, 8) and (7.5, 11)-(12.5, 11) of radius 12, 8 and 4, a 1.8 stroke with
/// round ends, and a dot of radius 1.2 at (10, 12.6). Returns (w, h, mask) for `h` px tall.
pub fn wifi(h: u32) -> (u32, u32, Vec<u8>) {
    let w = (h as f32 * 20.0 / 14.0).round() as u32;
    let half = 0.9;
    // each arc: its circle (center below the chord), its radius and the chord's y
    let arcs = [(1.5f32, 5.0f32, 12.0f32), (4.5, 8.0, 8.0), (7.5, 11.0, 4.0)];
    let m = mask_view(w, h, 20.0, 14.0, |x, y| {
        let on_arc = arcs.iter().any(|&(x0, y0, r)| {
            let dx = 10.0 - x0;
            let cy = y0 + (r * r - dx * dx).sqrt();
            let d = ((x - 10.0).powi(2) + (y - cy).powi(2)).sqrt();
            let body = (d - r).abs() <= half && y <= y0;
            let caps = ((x - x0).powi(2) + (y - y0).powi(2)).sqrt() <= half || ((x - (20.0 - x0)).powi(2) + (y - y0).powi(2)).sqrt() <= half;
            body || caps
        });
        on_arc || ((x - 10.0).powi(2) + (y - 12.6).powi(2)).sqrt() <= 1.2
    });
    (w, h, m)
}

/// The Bluetooth rune in the Wi-Fi icon's style (same 14-unit height, a 1.8 stroke with
/// round ends and joins), viewBox 10 x 14: the stem from (5, 1) to (5, 13) and the two
/// arrows to (8, 4) and (8, 10), crossing back to (2, 4) and (2, 10).
pub fn bluetooth(h: u32) -> (u32, u32, Vec<u8>) {
    let w = (h as f32 * 10.0 / 14.0).round() as u32;
    let pts = [(2.0f32, 4.0f32), (8.0, 10.0), (5.0, 13.0), (5.0, 1.0), (8.0, 4.0), (2.0, 10.0)];
    let m = mask_view(w, h, 10.0, 14.0, |x, y| pts.windows(2).any(|s| to_segment(x, y, s[0], s[1]) <= 0.9));
    (w, h, m)
}

/// The prototype's charge mark (its SVG path in the 30 x 14 battery viewBox):
/// M15.6 2.6 10.4 7.6 h3.1 l-1 3.8 l5.2-5.2 h-3.2 z. Spans x 10.4..17.7, y 2.6..11.4.
const BOLT: [(f32, f32); 6] = [(15.6, 2.6), (10.4, 7.6), (13.5, 7.6), (12.5, 11.4), (17.7, 6.2), (14.5, 6.2)];
/// The bolt's box in the battery's icon units: (left, top, right, bottom).
pub const BOLT_BOX: (f32, f32, f32, f32) = (10.4, 2.6, 17.7, 11.4);
/// Half of the halo's stroke (1.1 units wide) around the bolt.
pub const BOLT_HALO: f32 = 0.55;

/// The bolt as a mask `h` px tall covering exactly `BOLT_BOX`; returns (w, h, mask).
pub fn bolt(h: u32) -> (u32, u32, Vec<u8>) {
    let (l, t, r, b) = BOLT_BOX;
    let (vw, vh) = (r - l, b - t);
    let w = (h as f32 * vw / vh).round() as u32;
    let m = mask_view(w, h, vw, vh, |x, y| in_polygon(x + l, y + t, &BOLT));
    (w, h, m)
}

/// The bolt's halo: the polygon plus a band of `BOLT_HALO` around its edges (round joins),
/// over `BOLT_BOX` grown by that band on every side; returns (w, h, mask) for `h` px tall.
pub fn bolt_halo(h: u32) -> (u32, u32, Vec<u8>) {
    let (l, t, r, b) = BOLT_BOX;
    let (vw, vh) = (r - l + 2.0 * BOLT_HALO, b - t + 2.0 * BOLT_HALO);
    let w = (h as f32 * vw / vh).round() as u32;
    let m = mask_view(w, h, vw, vh, |x, y| {
        let (x, y) = (x + l - BOLT_HALO, y + t - BOLT_HALO);
        in_polygon(x, y, &BOLT) || (0..BOLT.len()).any(|i| to_segment(x, y, BOLT[i], BOLT[(i + 1) % BOLT.len()]) <= BOLT_HALO)
    });
    (w, h, m)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masks_are_square_and_have_shape() {
        for (m, name) in [(star(64), "star"), (gear(64), "gear"), (clock(64), "clock"), (check(64), "check")] {
            assert_eq!(m.len(), 64 * 64, "{name}");
            let on = m.iter().filter(|a| **a > 128).count();
            assert!(on > 64 * 64 / 10 && on < 64 * 64 * 3 / 4, "{name}: {on}");
        }
        // the gear has a hole: its center is empty; the star's center is full
        assert_eq!(gear(64)[32 * 64 + 32], 0);
        assert_eq!(star(64)[34 * 64 + 32], 255);
    }

    #[test]
    fn network_icons_share_the_status_style() {
        // the Wi-Fi icon keeps the prototype's 20:14 box; the rune is as tall, 10:14
        let (w, h, m) = wifi(56);
        assert_eq!((w, h, m.len()), (80, 56, 80 * 56));
        let at = |m: &[u8], w: u32, x: f32, y: f32| m[((y / 14.0 * 56.0) as u32 * w + (x / 20.0 * w as f32) as u32) as usize];
        assert_eq!(at(&m, w, 10.0, 12.6), 255, "the dot");
        // the middle arc's top is at 5.81, the small one's at 10.12 (each ±0.9 of stroke)
        assert_eq!(at(&m, w, 10.0, 8.0), 0, "between the arcs");
        assert_eq!(at(&m, w, 10.0, 13.47 - 12.0), 255, "the top of the outer arc");
        let (bw, bh, b) = bluetooth(56);
        assert_eq!((bw, bh), (40, 56));
        assert_eq!(b[(28 * bw + 20) as usize], 255, "the stem");
        assert_eq!(b[(28 * bw + 2) as usize], 0, "left of the stem, mid height");
    }
}
