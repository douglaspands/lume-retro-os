# Per-output volume for the shell services (device-fixes D9, D10; sourced by mixer and jack).
# The user scale and its conversion to a mixer control, frozen in docs/LAUNCHER.md "Volume por
# saida": the same table and functions as aports/lume-input/volume.h (C, the volume keys) and
# lume/lume-ui/src/volume.rs (the Settings row); tests/unit/test_volume_scale.py checks that
# the three agree. A control is data: <lo> <ref> <milli-dB per raw step> (ref = raw of 0 dB,
# the loudest clean position).
#
# Level file: $LEVEL_DIR/level-<output> (speaker | headphones), one integer 0-100.
LEVEL_DIR=${LEVEL_DIR:-/storage/system/audio}
VOL_DEFAULT_PCT=70

# Gain curve in milli-dB at 0, 5, 10 ... 100 percent (same table as volume.h)
CURVE="-96000 -39000 -36000 -33000 -30000 -28000 -26000 -24000 -22000 -20000 -18000 -16000 -14000 -12000 -10000 -8000 -6000 -4500 -3000 -1500 0"

curve_at() {  # <index 0..20>
	local n=$(($1 + 1))
	set -- $CURVE
	eval "echo \${$n}"
}

vol_db() {  # <percent> -> milli-dB (<= 0)
	local pct=$1 i f a b
	[ "$pct" -le 0 ] && { curve_at 0; return; }
	[ "$pct" -ge 100 ] && { echo 0; return; }
	[ "$pct" -lt 5 ] && { curve_at 1; return; }
	i=$((pct / 5)) f=$((pct % 5))
	a=$(curve_at "$i") b=$(curve_at $((i + 1)))
	echo $((a + (f * (b - a) + 2) / 5))
}

vol_raw() {  # <lo> <ref> <mdb step> <percent> -> raw position (0% is lo, the rest above it)
	local lo=$1 ref=$2 step=$3 pct=$4 db raw
	[ "$pct" -le 0 ] && { echo "$lo"; return; }
	db=$(vol_db "$pct")
	raw=$((ref - (-db + step / 2) / step))
	[ "$raw" -gt "$ref" ] && raw=$ref
	[ "$raw" -lt $((lo + 1)) ] && raw=$((lo + 1))
	echo "$raw"
}

vol_pct_from_db() {  # <milli-dB> -> nearest percent 1-100 (ties to the lower one)
	local mdb=$1 i=1 a b f d bd best
	# 1-5% share the 5% gain: the lowest of them wins the tie
	[ "$mdb" -le "$(curve_at 1)" ] && { echo 1; return; }
	[ "$mdb" -ge 0 ] && { echo 100; return; }
	while [ "$i" -lt 19 ] && [ "$mdb" -gt "$(curve_at $((i + 1)))" ]; do
		i=$((i + 1))
	done
	a=$(curve_at "$i") b=$(curve_at $((i + 1)))
	best=$((i * 5)) bd=$((mdb - a))
	[ "$bd" -lt 0 ] && bd=$((-bd))
	f=1
	while [ "$f" -le 5 ]; do
		d=$((a + (f * (b - a) + 2) / 5 - mdb))
		[ "$d" -lt 0 ] && d=$((-d))
		[ "$d" -lt "$bd" ] && { bd=$d; best=$((i * 5 + f)); }
		f=$((f + 1))
	done
	[ "$best" = 5 ] && best=1
	echo "$best"
}

vol_pct_from_raw() {  # <lo> <ref> <mdb step> <raw> -> percent (lo is 0, ref and above 100)
	local lo=$1 ref=$2 step=$3 raw=$4
	[ "$raw" -le "$lo" ] && { echo 0; return; }
	[ "$raw" -ge "$ref" ] && { echo 100; return; }
	vol_pct_from_db $(((raw - ref) * step))
}

level_read() {  # <output> -> the saved percent, empty without a valid file
	local v
	v=$(cat "$LEVEL_DIR/level-$1" 2>/dev/null)
	case "$v" in
	'' | *[!0-9]*) return 0 ;;
	esac
	[ "$v" -le 100 ] && echo "$v"
	return 0
}

ctl_raw() {  # <amixer> <card> <control> -> the first channel's raw value, empty if unread
	"$1" -c "$2" sget "$3" 2>/dev/null |
		sed -n '/Limits:/d; s/.*Playback \([0-9][0-9]*\) \[.*/\1/p' | head -n 1
}
