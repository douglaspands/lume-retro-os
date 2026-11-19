#!/bin/sh
# Cost of the background loops and of the log collector on the console (game-governor D20,
# boot-runtime "Serviços em segundo plano sem processo novo a cada volta").
#
# usage, from the PC with the console on the cable:
#   ssh root@10.55.0.1 'sh -s 120' < tests/device/loops_cost.sh
#
# Over N seconds (default 60):
#  - processes started in the whole system: the "processes" counter of /proc/stat, read with
#    the read builtin after the first snapshot and before the second, minus the window's sleep;
#  - per watched process: the exact run time (se.sum_exec_runtime of /proc/<pid>/sched) and
#    the ticks of its waited-for children (cutime+cstime). Ticks exaggerate a short loop that
#    wakes on the timer tick (each wakeup is charged a whole 10 ms), so run time is the measure.
# Targets (spec): the loops together under 1% of a core, the collector with its children under
# 1%, under 60 new processes per minute with the launcher still. Use 120 s or more: the flush
# of the logs (the shell logd, once a minute, ~24 processes and ~0.4 s of CPU on the GA36 idle)
# dominates a short window.
N=${1:-60}
HZ=100
T0=/tmp/loops_cost.$$.0
T1=/tmp/loops_cost.$$.1
snap() {
	for p in /proc/[0-9]*; do
		c=$(cat "$p/comm" 2>/dev/null) || continue
		case "$c" in lume-logd|logd|sugov:*|lume-input|lume-ui|lume-run|lume-power|lume-powerctl|savesync|persist|usb-gadget|ssh-wifi|inotifyd|lume-jack|jack)
			set -- $(cut -d' ' -f14-17 "$p/stat" 2>/dev/null)
			r=$(sed -n 's/^se.sum_exec_runtime *: *\([0-9]*\)\..*/\1/p' "$p/sched" 2>/dev/null)
			echo "$c ${p#/proc/} $1 $2 $3 $4 ${r:-0}" ;;
		esac
	done
}
forks() {
	local k v
	while read -r k v _; do
		[ "$k" = processes ] && { F=$v; return; }
	done </proc/stat
}
pct() {  # milliseconds -> percent of a core over the window, 3 decimals
	local t=$(($1 * 100 / N))
	printf '%d.%03d%%' $((t / 1000)) $((t % 1000))
}
snap > "$T0"
forks
f0=$F
sleep "$N"
forks
f1=$F
snap > "$T1"
n=$((f1 - f0 - 1))
echo "window ${N}s, processes started in the whole system: $n ($((n * 60 / N)) per minute)"
loops=0 logd=0
while read -r c pid u s cu cs r; do
	set -- $(grep "^$c $pid " "$T1")
	[ -n "$1" ] || continue
	kids=$(($5 + $6 - cu - cs))
	ms=$(($7 - r + kids * 1000 / HZ))
	case "$c" in
	usb-gadget|persist|savesync|ssh-wifi|inotifyd) loops=$((loops + ms)) ;;
	lume-logd) logd=$((logd + ms)) ;;
	esac
	echo "$c pid $pid: $(pct "$ms") (run $(($7 - r)) ms, children $kids ticks)"
done < "$T0"
echo "loops (usb-gadget, persist, savesync, ssh-wifi, inotifyd): $(pct "$loops") of a core"
echo "lume-logd with its children: $(pct "$logd") of a core"
rm -f "$T0" "$T1"
