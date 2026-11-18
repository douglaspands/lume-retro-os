#!/bin/sh
# Timeline of the way back from a game to the launcher, on the console (run as root).
# usage: exit-timeline.sh [SECONDS]   (default 12; start it, then press Fn+Start)
# One line per change, with /proc/uptime: the game's processes, lume-run's status, the
# lume-ui process, the DRM framebuffer on the screen, the display vblank interrupt counter
# (moving or stalled) and the TCON GINT0 register (GA36: enable bits 31,30,27; status 15,14,11).
secs=${1:-12}
run=/run/user/1000/lume/status
up() { cut -d' ' -f1 /proc/uptime; }
fb() { sed -n 's/^[[:space:]]*fb=\([0-9]*\).*/\1/p' /sys/kernel/debug/dri/0/state 2>/dev/null | head -n 1; }
vb() { awk '/lcd-controller/ { s = 0; for (i = 2; i <= NF; i++) if ($i ~ /^[0-9]+$/) s += $i; else break; print s }' /proc/interrupts; }
log=$(ls -t /storage/logs/frontend/boot-*.log 2>/dev/null | head -n 1)
lines=$(wc -l < "$log")
last_ra=; last_st=; last_ui=; last_fb=; last_vb=; last_g=; moving=
end=$(( $(cut -d. -f1 /proc/uptime) + secs ))
while [ "$(cut -d. -f1 /proc/uptime)" -lt "$end" ]; do
	ra=$(pidof retroarch love | wc -w)
	st=$(cat "$run" 2>/dev/null)
	ui=$(pidof lume-ui)
	f=$(fb)
	v=$(vb)
	g=$(r36os-devmem 0x1c0c004 2>/dev/null)
	m=stalled
	[ "$v" != "$last_vb" ] && m=moving
	last_vb=$v
	[ "$ra" != "$last_ra" ] && echo "$(up) game processes: $ra" && last_ra=$ra
	[ "$st" != "$last_st" ] && echo "$(up) lume-run status: $st" && last_st=$st
	[ "$ui" != "$last_ui" ] && echo "$(up) lume-ui pid: ${ui:-none}" && last_ui=$ui
	[ "$f" != "$last_fb" ] && echo "$(up) screen fb: ${f:-?}" && last_fb=$f
	[ "$m" != "$moving" ] && echo "$(up) vblank $m ($v)" && moving=$m
	[ "$g" != "$last_g" ] && echo "$(up) tcon gint0 $g" && last_g=$g
	n=$(wc -l < "$log")
	if [ "$n" -gt "$lines" ]; then
		tail -n $((n - lines)) "$log" | grep -E "lume-run|lume-ui|Unloading game|Saved core" |
			sed "s/^/$(up) log: /"
		lines=$n
	fi
	usleep 50000 2>/dev/null || sleep 0.05
done
