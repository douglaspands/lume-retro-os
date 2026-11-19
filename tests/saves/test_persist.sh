#!/bin/sh
# game-governor 7.2 (D20): lume-persist waits on inotifyd with no process while nothing
# changes, and still writes every change of the RetroArch configuration to the card, 2 s
# (PERSIST_DEBOUNCE) after the last one. Runs in busybox (builder container).
set -u
cd "$(dirname "$0")/../.."
LIBEXEC="$PWD/aports/lume-saves/files/usr/libexec/lume"
PERSIST="busybox sh $LIBEXEC/persist"
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

mkdir -p "$W/ram" "$W/sys/retroarch" "$W/run"
# /proc is always a mount point: the card counts as present
export PERSIST_LIBSH="$PWD/aports/lume-core/files/usr/libexec/lume/lib.sh" \
	PERSIST_LIBEXEC="$LIBEXEC" PERSIST_RAM="$W/ram" PERSIST_SYS="$W/sys" PERSIST_MOUNT=/proc \
	LUME_RUN="$W/run" PERSIST_DEBOUNCE=0.5 WATCH_IDLE=0.2
CARD="$W/sys/retroarch"

$PERSIST watch > "$W/watch.out" 2>&1 &
RUN=$!
until_cs 300 '[ -p "$W/run/watch.persist" ]'
check "watch: waits on its FIFO" '[ -p "$W/run/watch.persist" ]'

# a change reaches the card after the debounce
echo 'video_driver = "gl"' > "$W/ram/retroarch.cfg"
until_cs 300 '[ -f "$CARD/retroarch.cfg" ]'
check "change: written to the card" 'grep -qx "video_driver = \"gl\"" "$CARD/retroarch.cfg" 2>/dev/null'
check "change: the dirty mark is cleared" '[ ! -e "$W/run/persist.dirty" ]'

# a burst of writes: nothing on the card until 0.5 s after the last one
i=1
while [ $i -le 8 ]; do
	echo "audio_volume = \"$i\"" > "$W/ram/audio.cfg"
	sleep 0.2
	[ $i = 5 ] && [ -f "$CARD/audio.cfg" ] && echo "card copy during the burst" > "$W/early"
	i=$((i + 1))
done
check "debounce: nothing written while the writes keep coming" '[ ! -e "$W/early" ]'
until_cs 300 'grep -qx "audio_volume = \"8\"" "$CARD/audio.cfg" 2>/dev/null'
check "debounce: the last value reaches the card" 'grep -qx "audio_volume = \"8\"" "$CARD/audio.cfg" 2>/dev/null'

# a new directory (inotifyd is not recursive): watched again, its files persist
mkdir -p "$W/ram/config/Genesis Plus GX"
sleep 0.5
echo 'input = "1"' > "$W/ram/config/Genesis Plus GX/Genesis Plus GX.cfg"
until_cs 300 '[ -f "$CARD/config/Genesis Plus GX/Genesis Plus GX.cfg" ]'
check "new directory: a file inside it reaches the card" '[ -f "$CARD/config/Genesis Plus GX/Genesis Plus GX.cfg" ]'

# temporary files of RetroArch are not persisted
echo x > "$W/ram/retroarch.cfg.tmp.1"
sleep 1
check "temporary files stay in RAM" '[ ! -e "$CARD/retroarch.cfg.tmp.1" ]'
rm -f "$W/ram/retroarch.cfg.tmp.1"

# still: no process at all (PIDs are handed out in order inside the container's PID namespace)
if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then
	sleep 1
	: & p0=$!
	sleep 2.2   # 10 idle rounds of WATCH_IDLE=0.2
	: & p1=$!
	n=$((p1 - p0 - 2))
	check "still: no process started in 10 rounds (saw $n)" '[ $n = 0 ]'
else
	echo "SKIP still: needs the PID namespace of the builder container"
fi

# TERM: out of the wait at once, FIFO removed
t0=$(now_cs)
kill -TERM $RUN; wait $RUN
dt=$(($(now_cs) - t0))
check "TERM: stops at once and removes its FIFO (took ${dt} cs)" '[ $dt -lt 100 ] && [ ! -e "$W/run/watch.persist" ]'

# flush (power off): everything now, with no watch running
echo 'menu_driver = "ozone"' > "$W/ram/retroarch.cfg"
$PERSIST flush
check "flush: writes at once" 'grep -qx "menu_driver = \"ozone\"" "$CARD/retroarch.cfg"'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
