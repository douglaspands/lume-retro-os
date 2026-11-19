/* Per-output volume: the user scale (0-100) and its conversion to a mixer control
 * (device-fixes D9, D10, task 3.4). Pure integer functions, no I/O.
 *
 * The scale is perceptual: a percent is a gain in dB under the loudest clean position of
 * the control, not a share of its raw range. 100 = the loudest clean position (0 dB), each
 * 5% is 1.5 to 3 dB, 5% is about -39 dB (the useful end), 0 = mute (the control at its
 * minimum and the output switch off; the caller does the switch).
 *
 * The same curve table lives in lume/lume-ui/src/volume.rs (the launcher shows and sets the
 * same percent); tests/unit/test_volume_scale.py checks that the two tables agree. Each
 * control is data: raw range, the raw of 0 dB (the loudest clean one) and the milli-dB of
 * one raw step.
 *
 * Level file: ROMS/system/audio/level-<output>, output = speaker | headphones; one decimal
 * integer 0-100 and a newline. The GA36 uses only "speaker" (its jack has a mechanical
 * switch and no detection).
 */
#ifndef LUME_VOLUME_H
#define LUME_VOLUME_H

#define VOL_STEP_PCT 5
#define VOL_POINTS 21
#define VOL_DEFAULT_PCT 70	/* when no level file exists and the old level cannot be read */

/* gain in milli-dB at 0%, 5%, 10% ... 100% (index = percent / 5); 0% is mute, its value
 * only keeps the table regular */
static const int vol_curve_mdb[VOL_POINTS] = {
	-96000, -39000, -36000, -33000, -30000, -28000, -26000, -24000, -22000, -20000, -18000,
	-16000, -14000, -12000, -10000, -8000, -6000, -4500, -3000, -1500, 0,
};

struct vol_control {
	int lo, hi;	/* raw limits as amixer prints them */
	int ref;	/* raw of 0 dB: the loudest clean position */
	int mdb_step;	/* milli-dB of one raw step */
};

/* GA36 analog headphone gain (also feeds the speaker amplifier): 0-63, 1 dB per step (the
 * driver's TLV, 63 is 0 dB), 54 (-9 dB) is the loudest clean one on the speaker with a
 * full-scale game (judged by the user, 2026-11-18; 55 and up distort) */
static const struct vol_control VOL_GA36_HEADPHONE = { 0, 63, 54, 1000 };
/* R36S digital Master of the RK817 (rk817_codec.c: 0-255, -95 dB .. 0 dB, so 0.3725 dB per
 * step), kept until the 2.5 R36S measurement */
static const struct vol_control VOL_R36S_MASTER = { 0, 255, 255, 373 };
/* GA36 digital DAC, the control of the old volume: 0-192, 0.75 dB per step, 160 is 0 dB */
static const struct vol_control VOL_GA36_DAC_OLD = { 0, 192, 160, 750 };

/* Gain of a percent in milli-dB (<= 0); 1-4% hold the 5% gain, 0 is mute (the lowest value). */
static inline int vol_db(int pct)
{
	int i, f;

	if (pct <= 0)
		return vol_curve_mdb[0];
	if (pct >= 100)
		return 0;
	if (pct < VOL_STEP_PCT)
		return vol_curve_mdb[1];
	i = pct / VOL_STEP_PCT;
	f = pct % VOL_STEP_PCT;
	/* linear in dB between two table points, rounded to the nearest milli-dB */
	return vol_curve_mdb[i] + (f * (vol_curve_mdb[i + 1] - vol_curve_mdb[i]) + VOL_STEP_PCT / 2) / VOL_STEP_PCT;
}

/* The raw position of a percent: 0 is the minimum, any other percent stays above it. */
static inline int vol_raw(const struct vol_control *c, int pct)
{
	int db, raw;

	if (pct <= 0)
		return c->lo;
	db = vol_db(pct);
	raw = c->ref - (-db + c->mdb_step / 2) / c->mdb_step;
	if (raw > c->ref)
		raw = c->ref;
	if (raw < c->lo + 1)
		raw = c->lo + 1;
	return raw;
}

/* The percent (1-100) nearest to a gain in milli-dB; ties go to the lower percent. */
static inline int vol_pct_from_db(int mdb)
{
	int p, best = 1, bd = 1 << 30;

	for (p = 1; p <= 100; p++) {
		int d = vol_db(p) - mdb;

		if (d < 0)
			d = -d;
		if (d < bd) {
			bd = d;
			best = p;
		}
	}
	return best;
}

/* The percent of a raw position of a control: the raw minimum is 0 (mute), above the
 * loudest clean position is 100. */
static inline int vol_pct_from_raw(const struct vol_control *c, int raw)
{
	if (raw <= c->lo)
		return 0;
	if (raw >= c->ref)
		return 100;
	return vol_pct_from_db((raw - c->ref) * c->mdb_step);
}

/* One key step of `step` percent, on the grid of the step: up from 87 is 90, down from 87
 * is 85; the ends hold (0 and 100). */
static inline int vol_step(int pct, int up, int step)
{
	int v = up ? (pct / step + 1) * step : ((pct + step - 1) / step - 1) * step;

	return v < 0 ? 0 : v > 100 ? 100 : v;
}

/* One-time conversion: the percent that keeps the gain of today's digital level (raw of the
 * old control), the nearest position of the new scale. Used when level-<output> does not
 * exist yet; afterwards the file is the truth. */
static inline int vol_convert_old(const struct vol_control *old, int old_raw)
{
	return vol_pct_from_raw(old, old_raw);
}

#endif
