# The saved brightness at boot (device-fixes 9.16), shared by the init and the tests.
# Needs log() from storage.sh.
#
# The launcher and lume-input keep the brightness in ROMS/system/display/brightness as a
# percent 0-100 of the launcher's scale (device-fixes 9.15). The init applies it right after
# it mounts ROMS, so the chosen level shows long before lume-input starts: one file read and
# one sysfs write, nothing waited for (P-58). lume-input applies it again when it starts.
#
# The math is backlight_raw() of lume-input: rounded, never below the 5% floor nor level 1,
# never above the top. The top here is max_brightness only: the initramfs has no lume-input
# profile, and no profile has a ceiling (backlight_max) any more since the GA36 lost its own
# (2026-11-18), so max_brightness is the same 100% lume-input uses. A profile that gains a
# ceiling again needs it here too.

# brightness_restore <file> [backlight class folder]
brightness_restore() {
	local f="$1" root="${2:-/sys/class/backlight}" v="" d="" max="" cur="" raw floor_v

	[ -f "$f" ] || return 0
	IFS= read -r v 2>/dev/null < "$f" || [ -n "$v" ] || v=""
	# the same reading as lume-input: the first line, spaces around it ignored, digits only
	v=${v#"${v%%[![:space:]]*}"}
	v=${v%"${v##*[![:space:]]}"}
	case "$v" in
	'' | *[!0-9]*) v="bad" ;;
	*)
		# leading zeros off (the shell would read 010 as octal), then 0-100 only
		v=${v#"${v%%[!0]*}"}
		[ -n "$v" ] || v=0
		[ ${#v} -le 3 ] && [ "$v" -le 100 ] || v="bad"
		;;
	esac
	if [ "$v" = bad ]; then
		log "brightness: ignoring the bad file $f"
		return 0
	fi
	for d in "$root"/*; do
		[ -r "$d/max_brightness" ] && break
		d=""
	done
	[ -n "$d" ] || return 0
	read -r max 2>/dev/null < "$d/max_brightness" || return 0
	case "$max" in '' | *[!0-9]*) return 0 ;; esac
	[ "$max" -gt 0 ] || return 0
	floor_v=$(((max * 5 + 50) / 100))
	[ "$floor_v" -ge 1 ] || floor_v=1
	raw=$(((max * v + 50) / 100))
	[ "$raw" -ge "$floor_v" ] || raw=$floor_v
	[ "$raw" -le "$max" ] || raw=$max
	read -r cur 2>/dev/null < "$d/brightness" || cur=""
	[ "$cur" = "$raw" ] && return 0
	if echo "$raw" 2>/dev/null > "$d/brightness"; then
		log "brightness: backlight ${cur:-?} set to the saved $v% ($raw)"
	else
		log "brightness: cannot write $d/brightness"
	fi
	return 0
}
