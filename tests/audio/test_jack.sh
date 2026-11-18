#!/bin/sh
# r36s-single-card, task 6.6: the RK817 playback mux follows the headphone jack. Runs in
# busybox (builder container) with a fake amixer whose jack state comes from a file and a
# regular file in place of the jack input device (each 24-byte record is one event).
set -u
cd "$(dirname "$0")/../.."
JACK="busybox sh aports/lume-audio/files/usr/libexec/lume/jack"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

# the jack is a CARD control (iface=CARD): asked as a MIXER control, amixer finds nothing
# ("Cannot find the given element", R36S 2026-11-17)
cat > "$W/amixer" <<'EOF'
#!/bin/sh
case "$*" in
*cget*iface=CARD*) echo "  : values=$(cat "$FAKE_STATE")" ;;
*cget*) echo "amixer: Cannot find the given element from control sysdefault:0" >&2; exit 1 ;;
*) echo "$*" >> "$FAKE_LOG" ;;
esac
exit 0
EOF
chmod +x "$W/amixer"
export AMIXER="$W/amixer" FAKE_LOG="$W/amixer.log" FAKE_STATE="$W/state" BOARD_FILE="$W/board"
events() { dd if=/dev/zero bs=24 count="$1" 2>/dev/null; }   # $1 events

### R36S without headphones: the speaker, set once, however many events come
echo r36s > "$W/board"
echo off > "$W/state"
events 4 > "$W/evdev"
: > "$FAKE_LOG"
out=$(JACK_EVDEV="$W/evdev" $JACK)
check "speaker: the mux is set to SPK" 'grep -qxF -e "-c rk817int -q sset Playback Mux SPK" "$FAKE_LOG"'
check "speaker: no level file, the default 70% (raw 228) is applied" 'grep -qxF -e "-c rk817int -q sset Master 228" "$FAKE_LOG"'
check "speaker: set only once (mux and level, no more writes per event)" '[ "$(grep -c "" "$FAKE_LOG")" = 2 ]'
check "speaker: logged in English" 'printf "%s\n" "$out" | grep -qx "jack: headphones off, playback mux SPK"'

### headphones plugged in: HP, with the level of that output (3.4 conversion)
echo on > "$W/state"
mkdir -p "$W/audio"
echo 100 > "$W/audio/level-headphones"
echo 50 > "$W/audio/level-speaker"
export LEVEL_DIR="$W/audio"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "headphones: the mux is set to HP" 'grep -qxF -e "-c rk817int -q sset Playback Mux HP" "$FAKE_LOG"'
check "headphones: 100% is the loudest clean raw (255)" 'grep -qxF -e "-c rk817int -q sset Master 255" "$FAKE_LOG"'
echo off > "$W/state"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "speaker: 50% (-18 dB) is raw 207" 'grep -qxF -e "-c rk817int -q sset Master 207" "$FAKE_LOG"'
echo 0 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "speaker: 0% is the control minimum (mute)" 'grep -qxF -e "-c rk817int -q sset Master 0" "$FAKE_LOG"'
echo 5 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "speaker: 5% (-39 dB) is raw 150" 'grep -qxF -e "-c rk817int -q sset Master 150" "$FAKE_LOG"'
echo 3 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "speaker: 1-4% hold the 5% gain" 'grep -qxF -e "-c rk817int -q sset Master 150" "$FAKE_LOG"'
echo 72 > "$W/audio/level-speaker"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "speaker: between two table points the curve is linear in dB (72% = -9.2 dB, raw 230)" 'grep -qxF -e "-c rk817int -q sset Master 230" "$FAKE_LOG"'
echo 100 > "$W/audio/level-speaker"
echo off > "$W/state"
echo r36s > "$W/board"

### an event after the jack changed switches the mux again (a fake amixer that flips the
### state after the first read)
cat > "$W/amixer" <<'EOF'
#!/bin/sh
case "$*" in
*cget*)
	echo "  : values=$(cat "$FAKE_STATE")"
	echo off > "$FAKE_STATE"   # unplugged right after the first read
	;;
*) echo "$*" >> "$FAKE_LOG" ;;
esac
exit 0
EOF
echo on > "$W/state"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "change: HP then SPK on the next event, each with the level of its output" '[ "$(cat "$FAKE_LOG" | tr "\n" "|")" = "-c rk817int -q sset Playback Mux HP|-c rk817int -q sset Master 255|-c rk817int -q sset Playback Mux SPK|-c rk817int -q sset Master 255|" ]'

### other boards: the service does nothing
for b in ga36 vm; do
	echo "$b" > "$W/board"
	: > "$FAKE_LOG"
	JACK_EVDEV="$W/evdev" $JACK >/dev/null
	rc=$?
	check "$b: exit 0 and no amixer call" '[ "$rc" = 0 ] && [ ! -s "$FAKE_LOG" ]'
done

### the jack input device is found by name in sysfs
echo r36s > "$W/board"
mkdir -p "$W/sys/event3/device" "$W/sys/event5/device"
echo "gpio-keys" > "$W/sys/event3/device/name"
echo "rk817_int Headphones" > "$W/sys/event5/device/name"
out=$(INPUT_SYSFS="$W/sys" $JACK 2>/dev/null)
check "sysfs: the jack device is found by name (event5)" \
	'printf "%s\n" "$out" | grep -qx "jack: watching /dev/input/event5"'
rm -r "$W/sys/event5"
out=$(INPUT_SYSFS="$W/sys" $JACK 2>/dev/null)
rc=$?
check "sysfs: no jack device is an error, named in the output" \
	'[ "$rc" = 1 ] && printf "%s\n" "$out" | grep -q "no input device named \"rk817_int Headphones\""'
### the service blocks on the device with no CPU (a fifo with a silent writer stands for the
### evdev; the real run is 60 s, here a few seconds of CPU time are measured)
mkfifo "$W/fifo"
sleep 8 > "$W/fifo" &
holder=$!
echo off > "$W/state"
JACK_EVDEV="$W/fifo" $JACK >/dev/null 2>&1 &
pid=$!
sleep 4
cpu() { awk '{print $14 + $15}' "/proc/$pid/stat" 2>/dev/null; }
check "alive: the service is still running after 4 s without events" 'kill -0 "$pid" 2>/dev/null'
c1=$(cpu)
sleep 3
c2=$(cpu)
check "alive: no busy loop (under 0.1 s of CPU in 3 s)" '[ -n "$c1" ] && [ $((c2 - c1)) -le 10 ]'
kill "$pid" 2>/dev/null
kill "$holder" 2>/dev/null
wait 2>/dev/null

### a short read or an empty device ends the service with an error (no spin)
: > "$W/empty"
JACK_EVDEV="$W/empty" $JACK >/dev/null 2>&1
check "empty device: the service stops with 1" '[ "$?" = 1 ]'
echo ga36 > "$W/board"
JACK_EVDEV="$W/fifo" $JACK >/dev/null 2>&1
check "ga36: mechanical switch, no detection: returns at once without reading the device" '[ "$?" = 0 ]'
echo r36s > "$W/board"

check "service: enabled only on the R36S" 'grep -q "r36s) add lume-jack default[;]" rootfs/configure.sh'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
