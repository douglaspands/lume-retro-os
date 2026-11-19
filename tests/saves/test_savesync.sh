#!/bin/sh
# game-governor 7.2 (D20): savesync waits on inotifyd with no process while nothing changes,
# and syncs every save and save state written, also in directories created later. Runs in
# busybox (builder container).
set -u
cd "$(dirname "$0")/../.."
LIBEXEC="$PWD/aports/lume-saves/files/usr/libexec/lume"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }
now_cs() { read -r u _ </proc/uptime; echo $((${u%.*} * 100 + 1${u#*.} - 100)); }
until_cs() {
	local end=$(($(now_cs) + $1))
	while ! eval "$2"; do
		[ "$(now_cs)" -ge "$end" ] && return 1
		sleep 0.1
	done
}

mkdir -p "$W/storage" "$W/run"
export SAVESYNC_LIBSH="$PWD/aports/lume-core/files/usr/libexec/lume/lib.sh" \
	SAVESYNC_LIBEXEC="$LIBEXEC" SAVESYNC_STORAGE="$W/storage" SAVESYNC_MOUNT=/proc \
	LUME_RUN="$W/run" WATCH_IDLE=0.2
SYNCED="$W/run/savesync.log"

busybox sh "$LIBEXEC/savesync" > "$W/watch.out" 2>&1 &
RUN=$!
until_cs 300 '[ -p "$W/run/watch.savesync" ]'
check "watch: makes saves/ and states/ and waits on its FIFO" '[ -d "$W/storage/saves" ] && [ -d "$W/storage/states" ] && [ -p "$W/run/watch.savesync" ]'

echo sram > "$W/storage/saves/game.srm"
until_cs 200 'grep -q " $W/storage/saves/game.srm$" "$SYNCED" 2>/dev/null'
check "save: synced once written" 'grep -q " $W/storage/saves/game.srm$" "$SYNCED" 2>/dev/null'

echo state > "$W/storage/states/game.state.tmp"
mv "$W/storage/states/game.state.tmp" "$W/storage/states/game.state"
until_cs 200 'grep -q " $W/storage/states/game.state$" "$SYNCED" 2>/dev/null'
check "state: synced when moved in" 'grep -q " $W/storage/states/game.state$" "$SYNCED" 2>/dev/null'

# a directory created later (a core with its own folder): watched again
mkdir -p "$W/storage/saves/snes"
sleep 0.5
echo sram > "$W/storage/saves/snes/other.srm"
until_cs 300 'grep -q " $W/storage/saves/snes/other.srm$" "$SYNCED" 2>/dev/null'
check "new directory: its saves are synced too" 'grep -q " $W/storage/saves/snes/other.srm$" "$SYNCED" 2>/dev/null'

if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
	sleep 0.5
	: & p0=$!
	sleep 2.2   # 10 idle rounds of WATCH_IDLE=0.2
	: & p1=$!
	n=$((p1 - p0 - 2))
	check "still: no process started in 10 rounds (saw $n)" '[ $n = 0 ]'
else
	echo "SKIP still: needs the PID namespace of the builder container"
fi

t0=$(now_cs)
kill -TERM $RUN; wait $RUN
dt=$(($(now_cs) - t0))
check "TERM: stops at once and removes its FIFO (took ${dt} cs)" '[ $dt -lt 100 ] && [ ! -e "$W/run/watch.savesync" ]'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
