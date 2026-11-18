//! Per-output volume scale (device-fixes D9, D10, task 3.4): the user percent (0-100) and its
//! conversion to a mixer control. Pure integer functions.
//!
//! The scale is perceptual: a percent is a gain in dB under the loudest clean position of
//! the control. 100 is 0 dB, each 5% is 1.5 to 3 dB, 5% is about -39 dB, 0 is mute.
//! This is a mirror of `aports/lume-input/volume.h` (lume-input applies the keys); the
//! test `tests/unit/test_volume_scale.py` checks that the two curve tables agree.
//!
//! Level file: `ROMS/system/audio/level-<output>` (`speaker` or `headphones`), one decimal
//! integer 0-100 and a newline. The GA36 uses only `speaker`.

pub const STEP_PCT: i32 = 5;
pub const DEFAULT_PCT: i32 = 70;

/// Gain in milli-dB at 0%, 5%, 10% ... 100%; 0% is mute, its value only keeps the table regular.
pub const CURVE_MDB: [i32; 21] = [
    -96000, -39000, -36000, -33000, -30000, -28000, -26000, -24000, -22000, -20000, -18000,
    -16000, -14000, -12000, -10000, -8000, -6000, -4500, -3000, -1500, 0,
];

/// A mixer control as data: raw limits as amixer prints them, the raw of 0 dB (the loudest
/// clean position) and the milli-dB of one raw step.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Control {
    pub lo: i32,
    pub hi: i32,
    pub reference: i32,
    pub mdb_step: i32,
}

/// GA36 analog `Headphone` of `GA36MB`: 0-63, 1.5 dB per step (measured, 2.5 J1).
pub const GA36_HEADPHONE: Control = Control { lo: 0, hi: 63, reference: 63, mdb_step: 1500 };
/// R36S digital `Master` of `rk817int` (0-255, -95 dB to 0 dB), until the 2.5 R36S measurement.
pub const R36S_MASTER: Control = Control { lo: 0, hi: 255, reference: 255, mdb_step: 373 };
/// GA36 digital `DAC`, the control of the old volume: 0-192, 0.75 dB per step, 160 is 0 dB.
pub const GA36_DAC_OLD: Control = Control { lo: 0, hi: 192, reference: 160, mdb_step: 750 };

/// Gain of a percent in milli-dB (<= 0); 1-4% hold the 5% gain, 0 is mute (the lowest value).
pub fn db(pct: i32) -> i32 {
    if pct <= 0 {
        return CURVE_MDB[0];
    }
    if pct >= 100 {
        return 0;
    }
    if pct < STEP_PCT {
        return CURVE_MDB[1];
    }
    let (i, f) = ((pct / STEP_PCT) as usize, pct % STEP_PCT);
    CURVE_MDB[i] + (f * (CURVE_MDB[i + 1] - CURVE_MDB[i]) + STEP_PCT / 2) / STEP_PCT
}

/// The raw position of a percent: 0 is the minimum, any other percent stays above it.
pub fn raw(c: &Control, pct: i32) -> i32 {
    if pct <= 0 {
        return c.lo;
    }
    let raw = c.reference - (-db(pct) + c.mdb_step / 2) / c.mdb_step;
    raw.min(c.reference).max(c.lo + 1)
}

/// The percent (1-100) nearest to a gain in milli-dB; ties go to the lower percent.
pub fn pct_from_db(mdb: i32) -> i32 {
    let mut best = (1, i32::MAX);
    for p in 1..=100 {
        let d = (db(p) - mdb).abs();
        if d < best.1 {
            best = (p, d);
        }
    }
    best.0
}

/// The percent of a raw position of a control: the raw minimum is 0 (mute), above the
/// loudest clean position is 100.
pub fn pct_from_raw(c: &Control, raw: i32) -> i32 {
    if raw <= c.lo {
        0
    } else if raw >= c.reference {
        100
    } else {
        pct_from_db((raw - c.reference) * c.mdb_step)
    }
}

/// One-time conversion of today's digital level: the nearest position of the new scale.
pub fn convert_old(old: &Control, old_raw: i32) -> i32 {
    pct_from_raw(old, old_raw)
}

/// One step of `STEP_PCT` on the grid, as `vol_step` of volume.h (the volume keys): up from
/// 87 is 90, down from 87 is 85; the ends hold.
pub fn step(pct: i32, up: bool) -> i32 {
    let v = if up { (pct / STEP_PCT + 1) * STEP_PCT } else { ((pct + STEP_PCT - 1) / STEP_PCT - 1) * STEP_PCT };
    v.clamp(0, 100)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn scale_ends_and_curve() {
        for c in [GA36_HEADPHONE, R36S_MASTER] {
            assert_eq!(raw(&c, 0), c.lo);
            assert_eq!(raw(&c, 100), c.reference);
            assert!((1..=100).all(|p| raw(&c, p) > c.lo));
            assert!((1..=100).all(|p| raw(&c, p) >= raw(&c, p - 1)));
            // the round trip keeps the gain within one raw step
            assert!((1..=100).all(|p| (db(pct_from_raw(&c, raw(&c, p))) - db(p)).abs() <= c.mdb_step));
        }
        assert!((1..=100).all(|p| db(p) >= db(p - 1)));
        // the first step down from 100 is small
        assert!(-db(95) <= 2000);
        assert_eq!(db(0), CURVE_MDB[0]);
        assert_eq!(pct_from_raw(&GA36_HEADPHONE, 63), 100);
        assert_eq!(pct_from_raw(&GA36_HEADPHONE, 0), 0);
    }

    #[test]
    fn old_digital_level_converts_to_the_nearest_position() {
        assert_eq!(convert_old(&GA36_DAC_OLD, 160), 100);
        assert_eq!(convert_old(&GA36_DAC_OLD, 166), 100);
        assert_eq!(convert_old(&GA36_DAC_OLD, 154), 85); // -4.5 dB
        assert_eq!(convert_old(&GA36_DAC_OLD, 0), 0);
        assert_eq!(convert_old(&GA36_DAC_OLD, 1), 1);
        assert_eq!(convert_old(&R36S_MASTER, 255), 100);
    }

    #[test]
    fn steps_stay_on_the_grid() {
        assert_eq!((step(87, true), step(87, false)), (90, 85));
        assert_eq!((step(85, true), step(85, false)), (90, 80));
        assert_eq!((step(100, true), step(0, false)), (100, 0));
        assert_eq!((step(3, true), step(3, false)), (5, 0));
    }
}
