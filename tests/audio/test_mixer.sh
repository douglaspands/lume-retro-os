#!/bin/sh
# Task 9.8: default mixer of the board (lume-mixer), and the volume of device-fixes 7.2 (the
# level of the output on the analog control, mute at 0%, the one-time conversion of the old
# DAC level). Runs in busybox (builder container) with a fake amixer that records its
# arguments and answers "sget" with a raw value from a file.
set -u
cd "$(dirname "$0")/../.."
MIXER="busybox sh aports/lume-audio/files/usr/libexec/lume/mixer"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

cat > "$W/amixer" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$*" in *"$FAKE_FAIL"*) [ -n "$FAKE_FAIL" ] && exit 1 ;; esac
case "$3" in
sget)
	[ -s "$FAKE_DAC" ] || exit 1
	printf "Simple mixer control '%s',0\n  Limits: Playback 0 - 192\n  Front Left: Playback %s [83%%] [0.00dB] [on]\n  Front Right: Playback 1 [1%%] [on]\n" "$4" "$(cat "$FAKE_DAC")"
	;;
esac
exit 0
EOF
chmod +x "$W/amixer"
export AMIXER="$W/amixer" FAKE_LOG="$W/amixer.log" FAKE_FAIL="" FAKE_DAC="$W/dac" LEVEL_DIR="$W/audio"
mkdir -p "$W/audio"
set_log() { grep -c -e "-q sset" "$FAKE_LOG"; }

### GA36: the AIF1 -> DAC path is switched on and the digital volumes set
echo ga36 > "$W/board"
echo 160 > "$W/dac"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
rc=$?
check "ga36: exit 0 when every control is set" '[ "$rc" = 0 ]'
check "ga36: AIF1 Slot 0 Digital DAC switched on" 'grep -qxF -e "-c GA36MB -q sset AIF1 Slot 0 Digital DAC on" "$FAKE_LOG"'
check "ga36: AIF1 DA0 at 0 dB (160)" 'grep -qxF -e "-c GA36MB -q sset AIF1 DA0 160" "$FAKE_LOG"'
check "ga36: DAC at 0 dB and on" 'grep -qxF -e "-c GA36MB -q sset DAC 160 on" "$FAKE_LOG"'
check "ga36: headphone fed by the DAC" 'grep -qxF -e "-c GA36MB -q sset Headphone Source DAC" "$FAKE_LOG"'
check "ga36: speaker pin switch on" 'grep -qxF -e "-c GA36MB -q sset Speaker on" "$FAKE_LOG"'
check "ga36: output in English, one line per control and the level" '[ "$(printf "%s\n" "$out" | grep -c "^mixer: ")" = 7 ]'
check "ga36: six controls set" '[ "$(set_log)" = 6 ]'
# no level file and the DAC at 0 dB (a fresh boot): the default 70% (-10 dB, Headphone 56)
check "ga36: no file and the DAC at 0 dB: 70% on the Headphone (56), switch on" 'grep -qxF -e "-c GA36MB -q sset Headphone 56 on" "$FAKE_LOG"'
check "ga36: the level is logged with its origin" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 70% (default)"'
check "ga36: the DAC is read before it is set (the conversion)" '[ "$(grep -n "sget DAC" "$FAKE_LOG" | cut -d: -f1)" -lt "$(grep -n "sset DAC 160 on" "$FAKE_LOG" | cut -d: -f1)" ]'
check "ga36: no level file is written at boot" '[ ! -e "$W/audio/level-speaker" ]'

### the one-time conversion: the DAC still holds a level of the old volume (154 = -4.5 dB)
echo 154 > "$W/dac"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "conversion: old DAC 154 is 85% (Headphone 60)" 'grep -qxF -e "-c GA36MB -q sset Headphone 60 on" "$FAKE_LOG"'
check "conversion: logged with the old raw" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 85% (old DAC 154)"'
check "conversion: the DAC is back at 0 dB" 'grep -qxF -e "-c GA36MB -q sset DAC 160 on" "$FAKE_LOG"'
echo 130 > "$W/dac"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "conversion: old DAC 130 (-22.5 dB) is 39% (Headphone 48), as volume.h" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 39% (old DAC 130)" && grep -qxF -e "-c GA36MB -q sset Headphone 48 on" "$FAKE_LOG"'
echo 1 > "$W/dac"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "conversion: the lowest non-mute raw is 1%, not mute" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 1% (old DAC 1)" && grep -qxF -e "-c GA36MB -q sset Headphone 37 on" "$FAKE_LOG"'
: > "$W/dac"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "conversion: the DAC cannot be read: 70%" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 70% (default)"'
echo 154 > "$W/dac"

### the saved level wins over the DAC; 0% is mute (the Headphone switch off)
echo 50 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "level: 50% (-18 dB) is Headphone 51, switch on" 'grep -qxF -e "-c GA36MB -q sset Headphone 51 on" "$FAKE_LOG"'
check "level: logged from the file" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 50% (level-speaker)"'
check "level: the DAC is not read when the file exists" '! grep -q "sget" "$FAKE_LOG"'
echo 100 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
BOARD_FILE="$W/board" $MIXER >/dev/null
check "level: 100% is the loudest clean position (63)" 'grep -qxF -e "-c GA36MB -q sset Headphone 63 on" "$FAKE_LOG"'
echo 0 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
BOARD_FILE="$W/board" $MIXER >/dev/null
check "level: 0% is mute: Headphone at its minimum and switched off" 'grep -qxF -e "-c GA36MB -q sset Headphone 0 off" "$FAKE_LOG"'
check "level: the DAC stays on at 0 dB with the output muted" 'grep -qxF -e "-c GA36MB -q sset DAC 160 on" "$FAKE_LOG"'
echo junk > "$W/audio/level-speaker"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
check "level: a broken file falls back to the conversion" 'printf "%s\n" "$out" | grep -qx "mixer: speaker level 85% (old DAC 154)"'
rm -f "$W/audio/level-speaker"

### a control that fails is reported and the exit code is not 0, the rest is still set
FAKE_FAIL="AIF1 DA0"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
rc=$?
FAKE_FAIL=""
check "failure: exit code 1" '[ "$rc" = 1 ]'
check "failure: the failed control is named" 'printf "%s\n" "$out" | grep -q "mixer: FAILED to set AIF1 DA0 = 160 on card GA36MB"'
check "failure: the other controls are still set" 'grep -qxF -e "-c GA36MB -q sset Speaker on" "$FAKE_LOG"'

### R36S: RK817 codec, speaker path through the playback mux (r36s-single-card, task 6.3)
echo r36s > "$W/board"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
rc=$?
check "r36s: exit 0 when every control is set" '[ "$rc" = 0 ]'
check "r36s: playback mux on the speaker" 'grep -qxF -e "-c rk817int -q sset Playback Mux SPK" "$FAKE_LOG"'
check "r36s: no file: the default 70% on the Master (228), as the jack service" 'grep -qxF -e "-c rk817int -q sset Master 228" "$FAKE_LOG"'
check "r36s: speaker pin switch on" 'grep -qxF -e "-c rk817int -q sset Internal Speakers on" "$FAKE_LOG"'
check "r36s: no headphone switch (it does not exist on the card)" '! grep -q "sset Headphones" "$FAKE_LOG"'
check "r36s: only the speaker is a pin switch in the DTS" 'grep -q "simple-audio-card,pin-switches = \"Internal Speakers\";" board/r36s/dts/rk3326-r36s-v5.dts'
check "r36s: card name from the DTS sound card" 'grep -q "simple-audio-card,name = \"rk817_int\"" board/r36s/dts/rk3326-r36s-v5.dts'
check "r36s: one line per control and the level" '[ "$(printf "%s\n" "$out" | grep -c "^mixer: ")" = 4 ]'
echo 50 > "$W/audio/level-speaker"
echo 100 > "$W/audio/level-headphones"
: > "$FAKE_LOG"
BOARD_FILE="$W/board" $MIXER >/dev/null
check "r36s: the speaker level (50% = Master 207), not the headphones one" 'grep -qxF -e "-c rk817int -q sset Master 207" "$FAKE_LOG"'
echo 0 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
BOARD_FILE="$W/board" $MIXER >/dev/null
check "r36s: 0% is the Master minimum" 'grep -qxF -e "-c rk817int -q sset Master 0" "$FAKE_LOG"'
rm -f "$W/audio/level-speaker" "$W/audio/level-headphones"

### other boards: nothing is touched
for b in vm; do
	echo "$b" > "$W/board"
	: > "$FAKE_LOG"
	out=$(BOARD_FILE="$W/board" $MIXER)
	rc=$?
	check "$b: no amixer call and exit 0" '[ "$rc" = 0 ] && [ ! -s "$FAKE_LOG" ] && printf "%s\n" "$out" | grep -q "no defaults for board"'
done

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
