#!/bin/sh
# Task 9.8: default mixer of the board (r36os-mixer). Runs in busybox (builder container)
# with a fake amixer that records its arguments.
set -u
cd "$(dirname "$0")/../.."
MIXER="busybox sh rootfs/overlay/usr/libexec/r36os/mixer"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

cat > "$W/amixer" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$*" in *"$FAKE_FAIL"*) [ -n "$FAKE_FAIL" ] && exit 1 ;; esac
exit 0
EOF
chmod +x "$W/amixer"
export AMIXER="$W/amixer" FAKE_LOG="$W/amixer.log" FAKE_FAIL=""

### GA36: the AIF1 -> DAC path is switched on and the digital volumes set
echo ga36 > "$W/board"
: > "$FAKE_LOG"
out=$(BOARD_FILE="$W/board" $MIXER)
rc=$?
check "ga36: exit 0 when every control is set" '[ "$rc" = 0 ]'
check "ga36: AIF1 Slot 0 Digital DAC switched on" 'grep -qxF -e "-c GA36MB -q sset AIF1 Slot 0 Digital DAC on" "$FAKE_LOG"'
check "ga36: AIF1 DA0 at 0 dB (160)" 'grep -qxF -e "-c GA36MB -q sset AIF1 DA0 160" "$FAKE_LOG"'
check "ga36: DAC at 0 dB and on" 'grep -qxF -e "-c GA36MB -q sset DAC 160 on" "$FAKE_LOG"'
check "ga36: headphone fed by the DAC" 'grep -qxF -e "-c GA36MB -q sset Headphone Source DAC" "$FAKE_LOG"'
check "ga36: speaker pin switch on" 'grep -qxF -e "-c GA36MB -q sset Speaker on" "$FAKE_LOG"'
check "ga36: output in English, one line per control" '[ "$(printf "%s\n" "$out" | grep -c "^mixer: ")" = 6 ]'

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
check "r36s: master volume at 0 dB" 'grep -qxF -e "-c rk817int -q sset Master 100%" "$FAKE_LOG"'
check "r36s: speaker pin switch on" 'grep -qxF -e "-c rk817int -q sset Internal Speakers on" "$FAKE_LOG"'
check "r36s: no headphone switch (it does not exist on the card)" '! grep -q "sset Headphones" "$FAKE_LOG"'
check "r36s: only the speaker is a pin switch in the DTS" 'grep -q "simple-audio-card,pin-switches = \"Internal Speakers\";" board/r36s/dts/rk3326-r36s-v5.dts'
check "r36s: card name from the DTS sound card" 'grep -q "simple-audio-card,name = \"rk817_int\"" board/r36s/dts/rk3326-r36s-v5.dts'
check "r36s: one line per control" '[ "$(printf "%s\n" "$out" | grep -c "^mixer: ")" = 3 ]'

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
