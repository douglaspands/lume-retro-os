#!/bin/sh
# r36s-single-card, task 6.6: the RK817 playback mux follows the headphone jack. Runs in
# busybox (builder container) with a fake amixer whose jack state comes from a file and a
# regular file in place of the jack input device (each 24-byte record is one event).
set -u
cd "$(dirname "$0")/../.."
JACK="busybox sh rootfs/overlay/usr/libexec/r36os/jack"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

cat > "$W/amixer" <<'EOF'
#!/bin/sh
case "$*" in
*cget*) echo "  : values=$(cat "$FAKE_STATE")" ;;
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
check "speaker: set only once (no change, no write)" '[ "$(grep -c "" "$FAKE_LOG")" = 1 ]'
check "speaker: logged in English" 'printf "%s\n" "$out" | grep -qx "jack: headphones off, playback mux SPK"'

### headphones plugged in: HP
echo on > "$W/state"
: > "$FAKE_LOG"
JACK_EVDEV="$W/evdev" $JACK >/dev/null
check "headphones: the mux is set to HP" 'grep -qxF -e "-c rk817int -q sset Playback Mux HP" "$FAKE_LOG"'

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
check "change: HP then SPK on the next event" '[ "$(cat "$FAKE_LOG" | tr "\n" "|")" = "-c rk817int -q sset Playback Mux HP|-c rk817int -q sset Playback Mux SPK|" ]'

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
check "service: enabled only on the R36S" 'grep -q "r36s) add r36os-jack default ;;" rootfs/configure.sh'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
