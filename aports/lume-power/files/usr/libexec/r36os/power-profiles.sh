#!/bin/sh
# Lume power profiles: parser, merger and validator (openspec game-governor, D3/D16).
# Meant to be sourced by r36os-power (node 2.2); it only defines functions.
#
# Two layers: the image console file (/usr/share/lume/power/<console>.conf) and, on top of it,
# the optional card file (ROMS/system/lume/power.conf). Grammar, one entry per line; blank lines
# and `#` comments (also trailing) are ignored:
#   profile <name> key=value...   keys: governor min max cores gpu_min gpu_max up_threshold
#                                 sampling_down_factor rate_limit_us controller
#                                 (min/max in kHz, gpu_min/gpu_max in Hz, controller=load|auto;
#                                 a range of one step locks that resource, D18)
#   class <system> <profile>      profile of a system class
#   core <core> <profile>         exception per libretro core
#   game <key> <profile>          profile of one game (D18); ONLY in the card file. <key> is the
#                                 16 hex digits of lume_core::power::game_key (never a name)
#   battery warn=<%> critical=<%>
#   enabled 0|1
#   idle after=<seconds>          0 disables
#   limit game_min=<khz>          game clock floor; ONLY in the image file (ignored on the card)
#
# Game floor: a profile used in a game (`game`, and the targets of `class`, `core`, `game`, from any
# layer) without `min` gets min=<game_min>; with min (or max) below game_min the profile is
# refused. A profile only named for boot/menu/idle is not subject to the floor. If game_min is
# not an OPP the whole image file is refused and the effective floor is the largest OPP <= 600000.
#
# pp_load <image.conf> [card.conf]
#   stdout, one record per line (origin is image or card):
#     <kind> <origin> <args...>        accepted entry, merged (card wins per key: profile <name>,
#                                      class <system>, core <name>, game <key>, battery, idle,
#                                      enabled);
#                                      profiles come with the floor already in min=
#     refused <origin> <kind> <name|-> <reason...>
#   An entry the card refuses leaves the image entry for the same key in force. Each refused line
#   is also reported with pp_log FAIL "<origin>: rejected <kind> <name>: <reason>".
#   Exit: 0 all accepted, 1 something refused, 2 image file unreadable or refused whole (then
#   only a `refused` record is printed). A missing card file is not an error.
# pp_floor <image.conf>   prints the effective game floor in kHz (empty: none).
# pp_state <console> <image.conf> [card.conf]
#   prints the /run/r36os/power.state content (docs/LOGS.md): header from sysfs, then the pp_load
#   records, then `scenario $PP_SCENARIO` and `current $PP_PROFILE`.
#
# Environment: PP_SYS = sysfs root (default /sys), for tests. pp_log may be defined by the
# caller (the service maps it to `event power`); the default writes to stderr.

PP_SYS=${PP_SYS:-/sys}

if ! command -v pp_log >/dev/null 2>&1; then
	pp_log() { echo "power $1 $2" >&2; }
fi

pp_is_uint() {
	case $1 in
	'' | *[!0-9]*) return 1 ;;
	esac
	return 0
}

# pp_is_game_key <word>: exactly 16 lowercase hex digits (lume_core::power::game_key)
pp_is_game_key() {
	case $1 in
	[0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]) return 0 ;;
	esac
	return 1
}

pp_cpufreq() { echo "$PP_SYS/devices/system/cpu/cpu0/cpufreq"; }

# pp_table <file>: the words of a sysfs table on one line (empty if unreadable)
pp_table() {
	[ -r "$1" ] || return 0
	_pt=$(cat "$1") || return 0
	# shellcheck disable=SC2086
	echo $_pt
}

# pp_in_table <value> <file>
pp_in_table() {
	[ -r "$2" ] || return 1
	_pi=$(cat "$2") || return 1
	for _piw in $_pi; do
		[ "$_piw" = "$1" ] && return 0
	done
	return 1
}

pp_cpu_count() {
	_pn=0
	for _pd in "$PP_SYS"/devices/system/cpu/cpu[0-9]*; do
		[ -d "$_pd" ] && _pn=$((_pn + 1))
	done
	echo "$_pn"
}

# pp_cpu_freq_ok <khz>: in scaling_available_frequencies, or inside cpuinfo_min..max
pp_cpu_freq_ok() {
	_pfc=$(pp_cpufreq)
	if [ -r "$_pfc/scaling_available_frequencies" ]; then
		pp_in_table "$1" "$_pfc/scaling_available_frequencies"
		return
	fi
	[ -r "$_pfc/cpuinfo_min_freq" ] && [ -r "$_pfc/cpuinfo_max_freq" ] || return 1
	read -r _pflo <"$_pfc/cpuinfo_min_freq"
	read -r _pfhi <"$_pfc/cpuinfo_max_freq"
	[ "$1" -ge "$_pflo" ] && [ "$1" -le "$_pfhi" ]
}

# pp_gpu_file: available_frequencies of the first devfreq device (empty if none)
pp_gpu_file() {
	for _pg in "$PP_SYS"/class/devfreq/*; do
		if [ -r "$_pg/available_frequencies" ]; then
			echo "$_pg/available_frequencies"
			return
		fi
	done
}

pp_gpu_freq_ok() {
	_pgf=$(pp_gpu_file)
	[ -n "$_pgf" ] && pp_in_table "$1" "$_pgf"
}

# pp_each_line <file> <callback>: calls <callback> kind args... for each non-empty entry
pp_each_line() {
	[ -r "$1" ] || return 0
	_pel_file=$1
	_pel_cb=$2
	while IFS= read -r _pel_l || [ -n "$_pel_l" ]; do
		_pel_l=${_pel_l%%#*}
		# shellcheck disable=SC2086
		set -- $_pel_l
		[ $# -gt 0 ] || continue
		"$_pel_cb" "$@"
	done <"$_pel_file"
}

# --- floor ---------------------------------------------------------------------------------

_pp_cb_limit() {
	[ "$1" = limit ] || return 0
	case ${2:-} in
	game_min=*) _PP_LIMIT=${2#game_min=} ;;
	*) _PP_LIMIT=bad ;;
	esac
}

# pp_floor_calc <image>: sets _PP_LIMIT, _PP_FLOOR (kHz or empty) and _PP_LIMIT_BAD (0|1)
pp_floor_calc() {
	_PP_LIMIT=
	_PP_FLOOR=
	_PP_LIMIT_BAD=0
	pp_each_line "$1" _pp_cb_limit
	[ -n "$_PP_LIMIT" ] || return 0
	if pp_is_uint "$_PP_LIMIT" && pp_cpu_freq_ok "$_PP_LIMIT"; then
		_PP_FLOOR=$_PP_LIMIT
		return 0
	fi
	_PP_LIMIT_BAD=1
	_pfl_t=$(pp_table "$(pp_cpufreq)/scaling_available_frequencies")
	for _pfl_f in $_pfl_t; do
		if pp_is_uint "$_pfl_f" && [ "$_pfl_f" -le 600000 ] && { [ -z "$_PP_FLOOR" ] || [ "$_pfl_f" -gt "$_PP_FLOOR" ]; }; then
			_PP_FLOOR=$_pfl_f
		fi
	done
}

pp_floor() {
	pp_floor_calc "$1"
	echo "$_PP_FLOOR"
}

# --- profile validation -------------------------------------------------------------------

_pp_no() {
	_PP_WHY=$1
	return 1
}

# pp_check_profile <is_game 0|1> <floor> <key=value...>
# On failure returns 1 with the reason in _PP_WHY; on success _PP_ADD is the min=<floor> to
# append (or empty).
pp_check_profile() {
	_pc_game=$1
	_pc_floor=$2
	shift 2
	_PP_ADD=
	_pc_min=
	_pc_max=
	_pc_gmin=
	_pc_gmax=
	for _pc_kv in "$@"; do
		case $_pc_kv in
		*=*) ;;
		*) _pp_no "'$_pc_kv' is not key=value"; return ;;
		esac
		_pc_k=${_pc_kv%%=*}
		_pc_v=${_pc_kv#*=}
		case $_pc_k in
		governor)
			pp_in_table "$_pc_v" "$(pp_cpufreq)/scaling_available_governors" ||
				{ _pp_no "governor $_pc_v not available"; return; }
			;;
		min | max)
			pp_is_uint "$_pc_v" || { _pp_no "$_pc_k=$_pc_v is not a number"; return; }
			pp_cpu_freq_ok "$_pc_v" || { _pp_no "$_pc_k=$_pc_v not in the clock table"; return; }
			if [ "$_pc_k" = min ]; then _pc_min=$_pc_v; else _pc_max=$_pc_v; fi
			;;
		cores)
			pp_is_uint "$_pc_v" || { _pp_no "cores=$_pc_v is not a number"; return; }
			{ [ "$_pc_v" -ge 1 ] && [ "$_pc_v" -le "$(pp_cpu_count)" ]; } ||
				{ _pp_no "cores=$_pc_v out of range 1..$(pp_cpu_count)"; return; }
			;;
		gpu_min | gpu_max)
			pp_is_uint "$_pc_v" || { _pp_no "$_pc_k=$_pc_v is not a number"; return; }
			pp_gpu_freq_ok "$_pc_v" || { _pp_no "$_pc_k=$_pc_v not in the devfreq table"; return; }
			if [ "$_pc_k" = gpu_min ]; then _pc_gmin=$_pc_v; else _pc_gmax=$_pc_v; fi
			;;
		up_threshold | sampling_down_factor | rate_limit_us)
			pp_is_uint "$_pc_v" || { _pp_no "$_pc_k=$_pc_v is not a number"; return; }
			;;
		controller)
			[ "$_pc_v" = load ] || [ "$_pc_v" = auto ] || { _pp_no "controller=$_pc_v unknown"; return; }
			;;
		*)
			_pp_no "unknown key $_pc_k"
			return
			;;
		esac
	done
	if [ "$_pc_game" = 1 ] && [ -n "$_pc_floor" ]; then
		if [ -n "$_pc_min" ] && [ "$_pc_min" -lt "$_pc_floor" ]; then
			_pp_no "min $_pc_min below game floor $_pc_floor"
			return
		fi
		if [ -n "$_pc_max" ] && [ "$_pc_max" -lt "$_pc_floor" ]; then
			_pp_no "max $_pc_max below game floor $_pc_floor"
			return
		fi
		if [ -z "$_pc_min" ]; then
			_PP_ADD=" min=$_pc_floor"
			_pc_min=$_pc_floor
		fi
	fi
	if [ -n "$_pc_min" ] && [ -n "$_pc_max" ] && [ "$_pc_min" -gt "$_pc_max" ]; then
		_pp_no "min $_pc_min above max $_pc_max"
		return
	fi
	if [ -n "$_pc_gmin" ] && [ -n "$_pc_gmax" ] && [ "$_pc_gmin" -gt "$_pc_gmax" ]; then
		_pp_no "gpu_min $_pc_gmin above gpu_max $_pc_gmax"
		return
	fi
	return 0
}

# --- merge ---------------------------------------------------------------------------------

# pass 0: collect the profiles a game can use (any layer, valid or not: the conservative side)
_pp_cb_targets() {
	case $1 in
	class | core | game) [ $# -eq 3 ] && _PP_GAME="$_PP_GAME|$3|" ;;
	esac
	return 0
}

# _pp_validate <kind> <args...>: sets _PP_WHY (empty = accepted) and _PP_ADD
_pp_validate() {
	_pv_kind=$1
	shift
	_PP_WHY=
	_PP_ADD=
	case $_pv_kind in
	limit)
		if [ "$_PP_ORIGIN" != image ]; then
			_pp_no "limit is only accepted in the image file"
		elif [ $# -ne 1 ] || [ "$1" != "game_min=$_PP_LIMIT" ]; then
			_pp_no "limit needs game_min=<khz>"
		fi
		;;
	profile)
		_pv_isg=0
		case "$_PP_GAME" in *"|$1|"*) _pv_isg=1 ;; esac
		_pv_n=$1
		shift
		pp_check_profile "$_pv_isg" "$_PP_FLOOR" "$@"
		;;
	game)
		if [ "$_PP_ORIGIN" != card ]; then
			_pp_no "game is only accepted in the card file"
		elif [ $# -ne 2 ]; then
			_pp_no "game line needs <key> <profile>"
		elif ! pp_is_game_key "$1"; then
			_pp_no "game key $1 is not 16 hex digits"
		else
			case "$_PP_OK" in
			*"|$2|"*) ;;
			*) _pp_no "profile $2 is refused or unknown" ;;
			esac
		fi
		;;
	class | core)
		if [ $# -ne 2 ]; then
			_pp_no "$_pv_kind line needs <name> <profile>"
		else
			case "$_PP_OK" in
			*"|$2|"*) ;;
			*) _pp_no "profile $2 is refused or unknown" ;;
			esac
		fi
		;;
	battery)
		_pv_w=
		_pv_c=
		_pv_bad=0
		for _pv_kv in "$@"; do
			case $_pv_kv in
			warn=*) _pv_w=${_pv_kv#warn=} ;;
			critical=*) _pv_c=${_pv_kv#critical=} ;;
			*) _pv_bad=1 ;;
			esac
		done
		if [ $_pv_bad = 1 ] || ! pp_is_uint "$_pv_w" || ! pp_is_uint "$_pv_c" || [ "$_pv_w" -gt 100 ] || [ "$_pv_c" -gt "$_pv_w" ]; then
			_pp_no "battery needs warn=<0..100> critical=<=warn>"
		fi
		;;
	idle)
		if [ $# -ne 1 ] || [ "${1#after=}" = "$1" ] || ! pp_is_uint "${1#after=}"; then
			_pp_no "idle needs after=<seconds>"
		fi
		;;
	enabled)
		if [ $# -ne 1 ] || { [ "$1" != 0 ] && [ "$1" != 1 ]; }; then
			_pp_no "enabled needs 0 or 1"
		fi
		;;
	esac
	return 0
}

# pass 1 (limit, profile) and pass 2 (the rest); uses _PP_ORIGIN _PP_PASS _PP_SEEN _PP_OK _PP_RC
_pp_cb_entry() {
	_pe_kind=$1
	_pe_key=
	case $_pe_kind in
	limit | profile)
		[ "$_PP_PASS" = 1 ] || return 0
		;;
	class | core | game | battery | idle | enabled)
		[ "$_PP_PASS" = 2 ] || return 0
		;;
	*)
		[ "$_PP_PASS" = 2 ] || return 0
		_pe_name=-
		_PP_WHY="unknown line $_pe_kind"
		pp_log FAIL "$_PP_ORIGIN: rejected $_pe_kind $_pe_name: $_PP_WHY"
		echo "refused $_PP_ORIGIN $_pe_kind $_pe_name $_PP_WHY"
		_PP_RC=1
		return 0
		;;
	esac
	case $_pe_kind in
	profile | class | core | game) _pe_key="$_pe_kind ${2:-}" ;;
	*) _pe_key=$_pe_kind ;;
	esac
	case "$_PP_SEEN" in
	*"|$_pe_key|"*) return 0 ;; # taken by the card entry already
	esac
	case $_pe_kind in
	profile | class | core | game) _pe_name=${2:--} ;;
	*) _pe_name=- ;;
	esac
	_pp_validate "$@"
	if [ -z "$_PP_WHY" ]; then
		_PP_SEEN="$_PP_SEEN|$_pe_key|"
		[ "$_pe_kind" != profile ] || _PP_OK="$_PP_OK|$2|"
		shift
		echo "$_pe_kind $_PP_ORIGIN $*$_PP_ADD"
		return 0
	fi
	pp_log FAIL "$_PP_ORIGIN: rejected $_pe_kind $_pe_name: $_PP_WHY"
	echo "refused $_PP_ORIGIN $_pe_kind $_pe_name $_PP_WHY"
	_PP_RC=1
	return 0
}

pp_load() {
	if [ ! -r "$1" ]; then
		pp_log FAIL "image profiles file unreadable"
		echo "refused image file - unreadable"
		return 2
	fi
	_pl_img=$1
	_pl_card=${2:-}
	[ -r "$_pl_card" ] || _pl_card=
	pp_floor_calc "$_pl_img"
	if [ "$_PP_LIMIT_BAD" = 1 ]; then
		pp_log FAIL "image: whole file refused, game_min $_PP_LIMIT is not an OPP (floor ${_PP_FLOOR:-none})"
		echo "refused image limit game_min game_min $_PP_LIMIT is not an OPP"
		return 2
	fi
	_PP_GAME="|game|"
	for _pl_f in "$_pl_card" "$_pl_img"; do
		[ -n "$_pl_f" ] && pp_each_line "$_pl_f" _pp_cb_targets
	done
	_PP_SEEN=
	_PP_OK=
	_PP_RC=0
	for _PP_PASS in 1 2; do
		if [ -n "$_pl_card" ]; then
			_PP_ORIGIN=card
			pp_each_line "$_pl_card" _pp_cb_entry
		fi
		_PP_ORIGIN=image
		pp_each_line "$_pl_img" _pp_cb_entry
	done
	return "$_PP_RC"
}

# --- state -----------------------------------------------------------------------------------

# _pp_has <records> <kind>
_pp_has() {
	case "
$1" in
	*"
$2 "*) return 0 ;;
	esac
	return 1
}

pp_state() {
	_ps_recs=$(pp_load "$2" "${3:-}")
	_ps_c=$(pp_cpufreq)
	echo "console $1"
	_pp_has "$_ps_recs" enabled || echo "enabled default 1"
	echo "cpu_freqs $(pp_table "$_ps_c/scaling_available_frequencies")"
	echo "cpu_governors $(pp_table "$_ps_c/scaling_available_governors")"
	echo "cpu_cores $(pp_cpu_count)"
	_ps_gf=$(pp_gpu_file)
	if [ -n "$_ps_gf" ]; then echo "gpu_freqs $(pp_table "$_ps_gf")"; else echo "gpu_freqs"; fi
	pp_floor_calc "$2"
	[ -z "$_PP_FLOOR" ] || echo "game_min $_PP_FLOOR"
	[ -z "$_ps_recs" ] || echo "$_ps_recs"
	_pp_has "$_ps_recs" idle || echo "idle default after=120"
	echo "scenario ${PP_SCENARIO:-boot}"
	echo "current ${PP_PROFILE:--}"
}
