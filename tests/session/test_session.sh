#!/bin/sh
# lume-launcher task 6.1: the games cgroup handed to the game user (lume_cgroup in lib.sh)
# and the events buffer the launcher can append to (event in logs.sh). Runs in busybox
# (builder container, as root) on a fake cgroup tree: plain directories and files.
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
chmod 755 "$W"   # like /run/lume: the game user walks through it
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

export CGROUP_ROOT="$W/cg" LOGS_RAM="$W/logs"
. aports/lume-core/files/usr/libexec/lume/lib.sh
. aports/lume-core/files/usr/libexec/lume/logs.sh
owner() { stat -c %U "$1"; }

### no cgroup v2 mounted: nothing is created and the session falls back
mkdir -p "$W/cg"
out=$(lume_cgroup nobody 2>"$W/err"); rc=$?
check "no cgroup v2: fails, prints nothing, creates nothing" '[ $rc = 1 ] && [ -z "$out" ] && [ ! -e "$W/cg/lume" ]'
check "no cgroup v2: the reason is on stderr" 'grep -q "^no cgroup v2 at $W/cg$" "$W/err"'

### cgroup v2: the kernel creates the interface files of a new cgroup; the fake does it here
: > "$W/cg/cgroup.controllers"
mkdir -p "$W/cg/lume/session"
: > "$W/cg/lume/cgroup.procs"; : > "$W/cg/lume/cgroup.subtree_control"
: > "$W/cg/lume/session/cgroup.procs"
out=$(lume_cgroup nobody); rc=$?
check "cgroup v2: prints the session leaf" '[ $rc = 0 ] && [ "$out" = "$W/cg/lume/session/cgroup.procs" ]'
check "cgroup v2: lume/ and its procs and subtree_control belong to the user" '[ "$(owner $W/cg/lume)" = nobody ] && [ "$(owner $W/cg/lume/cgroup.procs)" = nobody ] && [ "$(owner $W/cg/lume/cgroup.subtree_control)" = nobody ]'
check "cgroup v2: the session leaf belongs to the user" '[ "$(owner $W/cg/lume/session)" = nobody ] && [ "$(owner $W/cg/lume/session/cgroup.procs)" = nobody ]'
check "cgroup v2: the root stays root" '[ "$(owner $W/cg)" = root ]'
out=$(lume_cgroup nobody); rc=$?
check "cgroup v2: a second call (frontend restart) is harmless" '[ $rc = 0 ]'

### events buffer: created writable by the launcher user, kept writable by root
event frontend OK "started: lume"
check "events: created with mode 666" '[ "$(stat -c %a $LOGS_RAM/events.pending)" = 666 ]'
su -s /bin/sh -c "echo 'x 0 game OK snes retroarch snes9x start' >> $LOGS_RAM/events.pending" nobody
check "events: the game user appends" 'grep -q " game OK snes retroarch snes9x start$" $LOGS_RAM/events.pending'
event frontend OK "closed"
check "events: root still appends after it" '[ "$(wc -l < $LOGS_RAM/events.pending)" = 3 ]'
# a flush moves the buffer to the card: the game user must not lose the lines it writes
# right after (test-vm, 2026-11-14)
events_shared nobody
check "events: the RAM directory is sticky and writable by the group" '[ "$(stat -c %a $LOGS_RAM)" = 1775 ] && [ "$(stat -c %G $LOGS_RAM)" = nobody ]'
export LOGS_DIR="$W/card" LOGS_MOUNT=/
_drain "$LOGS_RAM/events.pending" "$LOGS_DIR/events.log"
su -s /bin/sh -c "echo 'x 0 game OK snes retroarch snes9x exit=0 end=normal secs=1' >> $LOGS_RAM/events.pending" nobody
check "events: the game user creates the buffer again after a flush" 'grep -q "end=normal secs=1$" $LOGS_RAM/events.pending'
rm -f "$LOGS_RAM/events.pending"
events_file
check "events: the flush leaves an empty buffer with mode 666" '[ "$(stat -c %a $LOGS_RAM/events.pending)" = 666 ] && [ ! -s $LOGS_RAM/events.pending ]'
check "logs_flush: recreates the buffer after the drain" 'grep -A1 "_drain \"\$LOGS_RAM/events.pending\"" aports/lume-core/files/usr/libexec/lume/logs.sh | grep -q events_file'
check "session: shares the events buffer with the game user" 'grep -q "events_shared game" aports/lume-core/files/usr/libexec/lume/session'

### the session uses both
S=aports/lume-core/files/usr/libexec/lume/session
check "session: delegates before the loop and moves the frontend subshell" 'grep -q "CG_PROCS=\$(lume_cgroup game 2>" $S && grep -q "echo 0 > \"\$CG_PROCS\"" $S'
check "session: the reason of a missing cgroup goes to the log" 'grep -q "no cgroup v2 for the games (\$(cat" $S'
check "rc.conf: cgroup v2 only" 'grep -q "rc_cgroup_mode=\"unified\"" rootfs/configure.sh'

### device-fixes 5.2 (D2): the power off of the session leaves ROMS clean. The session is
### loaded with its functions only, with fake sync, mount, umount, mountpoint, poweroff,
### rc-service and persist that write each call to $CALLS
L=$W/libexec
mkdir -p "$L" "$W/bin" "$W/card"
ln -s "$PWD/aports/lume-core/files/usr/libexec/lume/lib.sh" "$L/lib.sh"
ln -s "$PWD/aports/lume-core/files/usr/libexec/lume/logs.sh" "$L/logs.sh"
printf '#!/bin/sh\necho "persist $*" >> "$CALLS"\n' > "$L/persist"
printf '#!/bin/sh\necho "rc-service $*" >> "$CALLS"\n' > "$W/bin/rc-service"
chmod +x "$L/persist" "$W/bin/rc-service"
export CALLS="$W/calls"
run_off() {  # $1: what fails ("", remount, both) or "unmounted" -> $CALLS, kernel log in $W/kmsg
	: > "$CALLS"; : > "$W/kmsg"
	rm -f "$LOGS_RAM"/*.pending "$LOGS_DIR"/events*.log
	(
		PATH="$W/bin:$PATH"
		SESSION_LIB=1
		SESSION_LIBDIR=$L
		STORAGE=$W/storage
		. aports/lume-core/files/usr/libexec/lume/session
		FAILING=$1
		kmsg() { echo "$*" >> "$W/kmsg"; }
		sync() { echo sync >> "$CALLS"; }
		mountpoint() { echo "mountpoint $*" >> "$CALLS"; [ "$FAILING" != unmounted ]; }
		mount() { echo "mount $*" >> "$CALLS"; [ -z "$FAILING" ]; }
		umount() { echo "umount $*" >> "$CALLS"; [ "$FAILING" != both ]; }
		poweroff() { echo poweroff >> "$CALLS"; }
		power_off
	)
}
calls() { tr '\n' '|' < "$CALLS"; }
run_off ""
check "power off: persist, sync, logd stopped, sync, remount read-only, poweroff" \
	'[ "$(calls)" = "persist flush|sync|mountpoint -q $W/storage|rc-service lume-logd stop|sync|mount -o remount,ro $W/storage|poweroff|" ]'
check "power off: the remount in the kernel log" 'grep -qx "storage: remounted read-only" "$W/kmsg"'
check "power off: the closing event reaches the buffer before logd stops" 'grep -q " frontend OK retroarch closed by user: shutting down" "$LOGS_RAM/events.pending"'
check "power off: no storage event when it worked" '! grep -q " shutdown " "$LOGS_RAM/events.pending"'
run_off remount
check "remount fails: unmounted instead, then poweroff" \
	'[ "$(calls)" = "persist flush|sync|mountpoint -q $W/storage|rc-service lume-logd stop|sync|mount -o remount,ro $W/storage|umount $W/storage|poweroff|" ]'
check "remount fails: the unmount in the kernel log" 'grep -qx "storage: unmounted (remount read-only failed)" "$W/kmsg"'
run_off both
check "both fail: poweroff still called, last" '[ "$(tail -n 1 "$CALLS")" = poweroff ] && grep -qx "umount $W/storage" "$CALLS"'
check "both fail: ERROR in the kernel log" 'grep -qx "ERROR: storage: remount read-only and unmount failed; ROMS stays marked dirty" "$W/kmsg"'
check "both fail: the shutdown failure event written to the card" \
	'grep -q " shutdown FAIL storage: remount read-only and unmount failed; ROMS stays marked dirty and is checked at the next boot$" "$LOGS_DIR/events.log"'
### device-fixes 9.1 (D15): the clock is saved before the card goes read-only
printf '#!/bin/sh\necho "lume-clock $*" >> "$CALLS"\n' > "$W/bin/lume-clock"
chmod +x "$W/bin/lume-clock"
run_off ""
check "power off: lume-clock save comes before the remount read-only" \
	'[ "$(calls)" = "persist flush|lume-clock save|sync|mountpoint -q $W/storage|rc-service lume-logd stop|sync|mount -o remount,ro $W/storage|poweroff|" ]'
rm -f "$W/bin/lume-clock"
run_off unmounted
check "no ROMS: nothing to release, poweroff" '[ "$(calls)" = "persist flush|sync|mountpoint -q $W/storage|poweroff|" ]'
check "session: exit 0 of the frontend goes through power_off" \
	'grep -A 2 "if \[ \"\$rc\" -eq 0 \]; then" $S | grep -q "^		power_off$" && [ "$(grep -c "^[[:space:]]*poweroff$" $S)" = 1 ]'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
