#!/bin/sh
# lume-launcher task 6.1: the games cgroup handed to the game user (lume_cgroup in lib.sh)
# and the events buffer the launcher can append to (event in logs.sh). Runs in busybox
# (builder container, as root) on a fake cgroup tree: plain directories and files.
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
chmod 755 "$W"   # like /run/r36os: the game user walks through it
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

export CGROUP_ROOT="$W/cg" LOGS_RAM="$W/logs"
. rootfs/overlay/usr/libexec/r36os/lib.sh
. rootfs/overlay/usr/libexec/r36os/logs.sh
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
check "logs_flush: recreates the buffer after the drain" 'grep -A1 "_drain \"\$LOGS_RAM/events.pending\"" rootfs/overlay/usr/libexec/r36os/logs.sh | grep -q events_file'
check "session: shares the events buffer with the game user" 'grep -q "events_shared game" rootfs/overlay/usr/libexec/r36os/session'

### the session uses both
S=rootfs/overlay/usr/libexec/r36os/session
check "session: delegates before the loop and moves the frontend subshell" 'grep -q "CG_PROCS=\$(lume_cgroup game 2>" $S && grep -q "echo 0 > \"\$CG_PROCS\"" $S'
check "session: the reason of a missing cgroup goes to the log" 'grep -q "no cgroup v2 for the games (\$(cat" $S'
check "rc.conf: cgroup v2 only" 'grep -q "rc_cgroup_mode=\"unified\"" rootfs/configure.sh'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
