#!/bin/busybox sh
# Tests of the saved brightness the initramfs applies (device-fixes 9.16) on a fake sysfs.
# Runs in the builder container: busybox sh tests/initramfs/test_brightness.sh
set -u
cd "$(dirname "$0")"
. ../../initramfs/lib/storage.sh
. ../../initramfs/lib/brightness.sh
export TMPDIR=$(mktemp -d)
W=$TMPDIR
FAILS=0
ok()   { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then ok "$1"; else fail "$1"; fi; }

F=$W/roms/system/display/brightness
BL=$W/backlight
mkdir -p "$W/roms/system/display"

# a fake backlight class folder: one device with max_brightness $1 and brightness $2
mkbl() {
	rm -rf "$BL"
	mkdir -p "$BL/backlight"
	echo "$1" > "$BL/backlight/max_brightness"
	echo "$2" > "$BL/backlight/brightness"
}
level() { cat "$BL/backlight/brightness"; }
# runs the step with the file content $1 ("-" for no file); its log in $W/log
run() {
	rm -f "$F"
	[ "$1" = - ] || printf '%b' "$1" > "$F"
	brightness_restore "$F" "$BL" 2>"$W/log"
}

### 1. GA36: max 10, the device tree starts at 7
mkbl 10 7
run '40\n'
check "max 10: 40% is level 4" '[ "$(level)" = 4 ]'
check "max 10: logged" 'grep -qx "lume: brightness: backlight 7 set to the saved 40% (4)" "$W/log"'
mkbl 10 7; run '100\n'
check "max 10: 100% is level 10" '[ "$(level)" = 10 ]'
mkbl 10 7; run '0\n'
check "max 10: 0% is the floor, level 1" '[ "$(level)" = 1 ]'
mkbl 10 7; run '74\n'
check "max 10: rounded (74% is 7), nothing written or logged" '[ "$(level)" = 7 ] && [ ! -s "$W/log" ]'
mkbl 10 7; run '75\n'
check "max 10: rounded (75% is 8)" '[ "$(level)" = 8 ]'
mkbl 10 7; run ' 30 \r\n'
check "spaces and CR around the number" '[ "$(level)" = 3 ]'
mkbl 10 7; run '50'
check "no newline at the end" '[ "$(level)" = 5 ]'
mkbl 10 7; run '050\n'
check "leading zero is decimal (050 is 50%)" '[ "$(level)" = 5 ]'
mkbl 10 7; run '20\ngarbage\n'
check "only the first line counts" '[ "$(level)" = 2 ]'

### 2. max 255 (the 5% floor is 13)
mkbl 255 128
run '50\n'
check "max 255: 50% is 128, nothing written" '[ "$(level)" = 128 ] && [ ! -s "$W/log" ]'
mkbl 255 128; run '100\n'
check "max 255: 100% is 255" '[ "$(level)" = 255 ]'
mkbl 255 128; run '1\n'
check "max 255: 1% is the 5% floor (13)" '[ "$(level)" = 13 ]'
mkbl 255 128; run '33\n'
check "max 255: 33% is 84" '[ "$(level)" = 84 ]'

### 3. R36S: max 160, default 80
mkbl 160 80; run '25\n'
check "max 160: 25% is 40" '[ "$(level)" = 40 ]'

### 4. no file: nothing touched, nothing logged
mkbl 10 7; run -
check "no file: level kept" '[ "$(level)" = 7 ] && [ ! -s "$W/log" ]'

### 5. bad files: ignored with a log line
for bad in '' '\n' 'abc\n' '101\n' '-5\n' '5 0\n' '50%\n' '1000\n' '12.5\n'; do
	mkbl 10 7; run "$bad"
	check "bad file '$bad': level kept" '[ "$(level)" = 7 ]'
	check "bad file '$bad': logged" 'grep -qx "lume: brightness: ignoring the bad file $F" "$W/log"'
done

### 6. no backlight (the vm) or a broken one: nothing done, nothing logged
rm -rf "$BL"; mkdir -p "$BL"; run '50\n'
check "no backlight device" '[ ! -s "$W/log" ]'
rm -rf "$BL"; run '50\n'
check "no backlight class folder" '[ ! -s "$W/log" ]'
mkbl 0 0; run '50\n'
check "max 0: nothing written" '[ "$(level)" = 0 ] && [ ! -s "$W/log" ]'
mkbl x 7; run '50\n'
check "max not a number: nothing written" '[ "$(level)" = 7 ]'

### 7. the init: applies it right after ROMS is mounted, before the device tree selection,
### with no wait of its own (P-58)
INIT=../../initramfs/init
line_of() { grep -n "$1" "$INIT" | head -n1 | cut -d: -f1; }
check "init: sources brightness.sh after storage.sh" '[ "$(line_of "^\. /lib/brightness.sh$")" -gt "$(line_of "^\. /lib/storage.sh$")" ]'
check "init: one call, only with ROMS mounted" '[ "$(grep -c "brightness_restore" "$INIT")" = 1 ] && grep -qx "\[ -n \"\$ROMS_MOUNTED\" \] && brightness_restore /roms/system/display/brightness" "$INIT"'
check "init: after the ROMS mount, before select_dtb" '[ "$(line_of "brightness_restore")" -gt "$(line_of "if mount_roms; then")" ] && [ "$(line_of "brightness_restore")" -lt "$(line_of "^select_dtb$")" ]'
check "lib: no sleep, no mount, no wait" '! grep -v "^[[:space:]]*#" ../../initramfs/lib/brightness.sh | grep -Eq "sleep|mount|wait|udevadm|settle"'

rm -rf "$W"
echo "brightness: $FAILS failure(s)"
[ "$FAILS" -eq 0 ]
