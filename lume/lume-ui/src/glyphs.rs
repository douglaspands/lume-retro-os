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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn masks_are_square_and_have_shape() {
        for (m, name) in [(star(64), "star"), (gear(64), "gear"), (clock(64), "clock")] {
            assert_eq!(m.len(), 64 * 64, "{name}");
            let on = m.iter().filter(|a| **a > 128).count();
            assert!(on > 64 * 64 / 10 && on < 64 * 64 * 3 / 4, "{name}: {on}");
        }
        // the gear has a hole: its center is empty; the star's center is full
        assert_eq!(gear(64)[32 * 64 + 32], 0);
        assert_eq!(star(64)[34 * 64 + 32], 255);
    }
}
