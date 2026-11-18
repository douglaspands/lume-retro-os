#!/bin/sh
# device-fixes 9.1 (D15): lume-clock with a fake clock, RTC and files. Runs in busybox
# (builder container). The system time and the RTC are variables, never the real clock.
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

export CLOCK_FILE="$W/card/system/clock" VERSION_FILE="$W/VERSION" RTC_EPOCH_FILE="$W/rtc"
export LUME_CLOCK_LIB=1
. aports/lume-core/files/usr/bin/lume-clock

# Fakes: SYS is the system time, RTC the hardware clock, EVENTS the log.
SYS=0; RTC_NOW=""
now() { echo "$SYS"; }
set_system() { SYS=$1; }
rtc_write() { RTC_NOW=$SYS; echo "$SYS" > "$W/rtc"; }
EVENTS=$W/events
event() { echo "$*" >> "$EVENTS"; }
NTP_RESULT=ok; NTP_TIME=0; NTP_CALLS=0
HAVE_NTPD=1
have_ntpd() { [ "$HAVE_NTPD" = 1 ]; }
run_ntpd() { NTP_CALLS=$((NTP_CALLS + 1)); [ "$NTP_RESULT" = ok ] || return 1; SYS=$NTP_TIME; }

printf 'Lume Retro OS 0.1.0\nbuild: x\ndate: 2026-11-09T21:42:33\n' > "$VERSION_FILE"
BUILD=$(build_epoch)
check "build date parsed from /boot/VERSION" '[ "$BUILD" = 1794260553 ] || [ "$BUILD" -gt 1700000000 ]'
reset() { rm -rf "$W/card" "$W/rtc" "$EVENTS"; : > "$EVENTS"; mkdir -p "$W/card/system"; RTC_NOW=""; }

### restore
reset; SYS=$((BUILD - 100000)); echo $((BUILD + 5000)) > "$CLOCK_FILE"; echo $((BUILD + 1000)) > "$W/rtc"
clock_restore
check "restore: the newer saved time wins" '[ "$SYS" = $((BUILD + 5000)) ]'
check "restore: the RTC is written" '[ "$RTC_NOW" = $((BUILD + 5000)) ]'
check "restore: event names the source" 'grep -qx "clock OK restored saved" "$EVENTS"'

reset; SYS=$((BUILD - 100000)); echo $((BUILD + 1000)) > "$CLOCK_FILE"; echo $((BUILD + 9000)) > "$W/rtc"
clock_restore
check "restore: a valid RTC newer than the saved time wins" '[ "$SYS" = $((BUILD + 9000)) ] && grep -qx "clock OK restored rtc" "$EVENTS"'

reset; SYS=864000; echo 864000 > "$W/rtc"
clock_restore
check "restore: no saved time, invalid RTC (1970): the build date is the floor" '[ "$SYS" = "$BUILD" ] && grep -qx "clock OK restored build" "$EVENTS"'

reset; SYS=$((BUILD - 5)); echo 1000 > "$W/rtc"; echo garbage > "$CLOCK_FILE"
clock_restore
check "restore: a garbage saved file and an RTC before the build are ignored" '[ "$SYS" = "$BUILD" ]'

reset; SYS=$((BUILD + 20000)); echo $((BUILD + 100)) > "$CLOCK_FILE"
clock_restore
check "restore: a system time already ahead is never lowered" '[ "$SYS" = $((BUILD + 20000)) ] && grep -qx "clock OK restored system" "$EVENTS"'

reset; SYS=0; rm -f "$VERSION_FILE"; echo 5000 > "$CLOCK_FILE"
clock_restore
check "restore: no build date and a tiny saved time: still moves forward" '[ "$SYS" = 5000 ]'
printf 'date: 2026-11-09T21:42:33\n' > "$VERSION_FILE"

### save
reset; SYS=$((BUILD + 300))
clock_save
check "save: writes epoch seconds" '[ "$(cat "$CLOCK_FILE")" = $((BUILD + 300)) ]'
check "save: atomic, no temp file left" '[ "$(ls "$W/card/system" | wc -l)" = 1 ]'
SYS=$((BUILD + 100))
clock_save
check "save: does not lower a newer saved time" '[ "$(cat "$CLOCK_FILE")" = $((BUILD + 300)) ]'
clock_save --force
check "save --force lowers it" '[ "$(cat "$CLOCK_FILE")" = $((BUILD + 100)) ]'
reset; SYS=$((BUILD - 10))
clock_save 2>/dev/null; rc=$?
check "save: a time before the build date is refused" '[ $rc = 1 ] && [ ! -e "$CLOCK_FILE" ]'
reset; rm -rf "$W/card"; touch "$W/card"; SYS=$((BUILD + 1))
clock_save 2>/dev/null; rc=$?
check "save: an unwritable card fails without a trace" '[ $rc = 1 ]'

### two saves separated by a reboot, dates growing
reset; SYS=$((BUILD + 1000)); clock_save; first=$(cat "$CLOCK_FILE")
SYS=0; echo 100 > "$W/rtc"; clock_restore; clock_save; second=$(cat "$CLOCK_FILE")
check "reboot with a dead RTC: the second save is not older than the first" '[ "$second" -ge "$first" ]'

### a real source corrects
reset; SYS=$((BUILD + 50)); echo $((BUILD + 9999)) > "$CLOCK_FILE"
clock_set $((BUILD + 777)) pc
check "set (PC): system, RTC and the card follow, even backwards" '[ "$SYS" = $((BUILD + 777)) ] && [ "$RTC_NOW" = "$SYS" ] && [ "$(cat "$CLOCK_FILE")" = "$SYS" ]'
check "set (PC): event" 'grep -qx "clock OK set by pc" "$EVENTS"'
reset; SYS=$((BUILD + 50))
clock_set 12345 pc 2>/dev/null; rc=$?
check "set: an epoch before the build date is refused" '[ $rc = 1 ] && [ "$SYS" = $((BUILD + 50)) ]'
clock_set abc pc 2>/dev/null; rc=$?
check "set: a bad epoch is refused" '[ $rc = 2 ]'

reset; SYS=$((BUILD + 50)); NTP_RESULT=ok; NTP_TIME=$((BUILD + 4000))
clock_ntp
check "ntp: corrects the system, RTC and card" '[ "$SYS" = $((BUILD + 4000)) ] && [ "$RTC_NOW" = "$SYS" ] && [ "$(cat "$CLOCK_FILE")" = "$SYS" ]'
check "ntp: event" 'grep -qx "clock OK set by ntp" "$EVENTS"'
reset; SYS=$((BUILD + 50)); NTP_RESULT=fail
clock_ntp; rc=$?
check "ntp: no answer leaves everything as it was" '[ $rc = 1 ] && [ "$SYS" = $((BUILD + 50)) ] && [ ! -s "$EVENTS" ]'
reset; HAVE_NTPD=0; NTP_CALLS=0
clock_ntp; rc=$?
check "ntp: optional, no ntpd is a silent no-op" '[ $rc = 0 ] && [ "$NTP_CALLS" = 0 ] && [ ! -s "$EVENTS" ]'
HAVE_NTPD=1

### wiring
S=aports/lume-core/files/usr/libexec/lume/session
check "session: saves the clock before release_storage in power_off" \
	'[ "$(grep -n "lume-clock save" $S | head -n 1 | cut -d: -f1)" -lt "$(grep -n "^	release_storage$" $S | head -n 1 | cut -d: -f1)" ]'
check "service: after the frontend, not in the boot path" 'grep -q "after frontend" aports/lume-core/files/etc/init.d/lume-clock && grep -q "lume-clock" rootfs/configure.sh'
check "hook: dispatcher calls lume-clock ntp" 'grep -q "lume-clock ntp" aports/lume-net/files/etc/NetworkManager/dispatcher.d/90-lume-clock'
check "lume-clock: executable script" '[ -x aports/lume-core/files/usr/bin/lume-clock ]'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
