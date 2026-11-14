# Funções comuns dos scripts do Lume Retro OS (ash/busybox).

R36OS_RUN=/run/r36os
mkdir -p "$R36OS_RUN"

# Mensagem na tela/serial (stdout do serviço) e no syslog.
log() { echo "lume: $*"; logger -t lume "$*" 2>/dev/null; return 0; }

# Cópia atômica: temporário no mesmo diretório, fsync, rename, fsync do diretório.
atomic_copy() {
	local src="$1" dst="$2" tmp
	mkdir -p "$(dirname "$dst")"
	tmp="$(dirname "$dst")/.$(basename "$dst").tmp.$$"
	cp "$src" "$tmp" || { rm -f "$tmp"; return 1; }
	fsync "$tmp" 2>/dev/null
	mv -f "$tmp" "$dst" || { rm -f "$tmp"; return 1; }
	fsync "$(dirname "$dst")" 2>/dev/null
	return 0
}

# Espelha $1 em $2 (só arquivos que mudaram, removendo os que sumiram).
# Ignora temporários (*.tmp.*) e a pasta logs/.
mirror() {
	local src="$1" dst="$2" f rel
	mkdir -p "$dst"
	(cd "$src" && find . -type f ! -name '*.tmp.*' ! -path './logs/*') | while read -r rel; do
		cmp -s "$src/$rel" "$dst/$rel" || atomic_copy "$src/$rel" "$dst/$rel"
	done
	(cd "$dst" && find . -type f ! -name '*.tmp.*' ! -path './logs/*') | while read -r rel; do
		[ -e "$src/$rel" ] || rm -f "$dst/$rel"
	done
	(cd "$dst" && find . -mindepth 1 -depth -type d) | while read -r rel; do
		[ -d "$src/$rel" ] || rmdir "$dst/$rel" 2>/dev/null
	done
	return 0
}

# Observa as árvores "$@" com inotifyd e chama "$HANDLER evento dir arquivo".
# Recria o inotifyd quando surge um diretório novo (o inotifyd não é recursivo).
# Uso: WATCH_NAME=<nome> watch_tree <handler> <eventos> <diretório>...
watch_tree() {
	export WATCH_NAME="${WATCH_NAME:-watch}"
	local handler="$1" events="$2" args d old_ifs nl; shift 2
	nl='
'
	pid=""
	trap 'kill $pid 2>/dev/null; exit 0' TERM INT
	while :; do
		# Uma linha por diretório: nomes com espaço ("config/Genesis Plus GX") ficam inteiros.
		args=""
		for d in "$@"; do
			[ -d "$d" ] && args="$args$(find "$d" -type d | sed "s|\$|:$events|")$nl"
		done
		old_ifs=$IFS
		IFS=$nl
		# shellcheck disable=SC2086
		inotifyd "$handler" $args &
		pid=$!
		IFS=$old_ifs
		while kill -0 "$pid" 2>/dev/null; do
			sleep 1
			[ -n "$WATCH_TICK" ] && $WATCH_TICK
			if [ -e "$R36OS_RUN/rescan.$WATCH_NAME" ]; then
				rm -f "$R36OS_RUN/rescan.$WATCH_NAME"
				kill "$pid" 2>/dev/null
				wait "$pid" 2>/dev/null
			fi
		done
		# inotifyd saiu (diretório removido, por exemplo): não perde o debounce
		[ -n "$WATCH_TICK" ] && $WATCH_TICK
		sleep 1
	done
}

# Para os handlers: um diretório novo pede para refazer a lista do inotifyd.
note_new_dir() { [ "$1" = n ] && [ -d "$2/$3" ] && : > "$R36OS_RUN/rescan.${WATCH_NAME:-watch}"; return 0; }

board() { cat "${BOARD_FILE:-/etc/r36os/board}" 2>/dev/null; }

# Device tree in use (boot-dtb-select): chosen by lume-bootsel in the initramfs among the
# DTBs of BOOT/dtbs/<soc>/. DT_ROOT is overridden by the tests.
DT_ROOT=${DT_ROOT:-/proc/device-tree}
# lume,id of the running device tree (empty without the lume-select node)
dtb_id() { [ -r "$DT_ROOT/lume-select/lume,id" ] && tr -d '\000' < "$DT_ROOT/lume-select/lume,id"; return 0; }
# folder of the SoC under BOOT/dtbs/, from the SoC compatible (the same as /etc/soc)
dtb_soc() {
	case " $(tr '\000' ' ' < "$DT_ROOT/compatible" 2>/dev/null) " in
	*" allwinner,sun8i-a33 "*) echo a33 ;;
	*" rockchip,rk3326 "*) echo rk3326 ;;
	esac
}
# SoC serial number, as lume-bootsel reads it: letters and digits only; all zeros is none
SOC0_DIR=${SOC0_DIR:-/sys/devices/soc0}
dtb_serial() {
	local s
	# test first: a failed redirection is reported by the shell, before 2>/dev/null applies
	[ -r "$SOC0_DIR/serial_number" ] || return 0
	s=$(tr -cd '[:alnum:]' < "$SOC0_DIR/serial_number")
	case "$s" in *[!0]*) echo "$s" ;; esac
}
# state file of the choice on ROMS/system/etc: one per device (dtb-<soc>-<serial>.conf),
# or one per SoC without a serial number (dtb-<soc>.conf)
dtb_conf_name() {
	local soc s
	soc=$(dtb_soc)
	[ -n "$soc" ] || return 0
	s=$(dtb_serial)
	echo "dtb-$soc${s:+-$s}.conf"
}
# "<id> (<reason>)": after a kexec the reason is in /chosen, else in the boot log
dtb_in_use() {
	local id reason
	[ -d "$DT_ROOT" ] || { echo "none (no device tree)"; return 0; }
	id=$(dtb_id)
	[ -n "$id" ] || { echo "no lume-select node"; return 0; }
	if [ -r "$DT_ROOT/chosen/lume,dtb-selected" ]; then
		reason="$(tr '\000' '\n' < "$DT_ROOT/chosen/lume,dtb-selected" | sed -n 2p), after kexec"
	else
		reason=$(dmesg 2>/dev/null | sed -n 's/.*lume-bootsel: selected .* (reason: \([a-z]*\))$/\1/p' | tail -n 1)
	fi
	echo "$id (${reason:-reason unknown})"
}

# Idioma das mensagens para o usuário: o user_language do RetroArch (escolhido no menu e
# persistido pelo r36os-persist). Logs são sempre em inglês. Textos em en, pt e es (os
# mesmos idiomas do rótulo "Desligar"); os outros idiomas caem no inglês.
# RETRO_LANGUAGE_*: 3 = espanhol, 7 = português do Brasil, 8 = português de Portugal.
RA_USER_CFG=${RA_USER_CFG:-/home/game/.config/retroarch/retroarch.cfg}
RA_FACTORY_CFG=${RA_FACTORY_CFG:-/usr/share/r36os/factory/retroarch/retroarch.cfg}
ui_lang() {
	local cfg v=""
	for cfg in "$RA_USER_CFG" "$RA_FACTORY_CFG"; do
		v=$(sed -n 's/^user_language *= *"\{0,1\}\([0-9][0-9]*\)"\{0,1\} *$/\1/p' "$cfg" 2>/dev/null | tail -n 1)
		[ -n "$v" ] && break
	done
	case "$v" in 7|8) echo pt ;; 3) echo es ;; *) echo en ;; esac
}

# Games cgroup of the launcher (lume-launcher D9): <root>/lume/ handed to <user>, with the
# leaf <root>/lume/session/ where the frontend runs. lume-run then creates lume/game-<n>/
# itself and may move its games there, because the common ancestor (lume/) is the user's.
# Prints the cgroup.procs file of the session leaf; fails without a cgroup v2 at <root>, with
# the reason on stderr. CGROUP_ROOT only changes for the tests.
lume_cgroup() {  # user
	local root="${CGROUP_ROOT:-/sys/fs/cgroup}" cg f
	cg="$root/lume"
	[ -f "$root/cgroup.controllers" ] || {
		echo "no cgroup v2 at $root" >&2
		return 1
	}
	mkdir -p "$cg/session" 2>/dev/null || {
		echo "cannot create $cg/session" >&2
		return 1
	}
	for f in "$cg" "$cg/cgroup.procs" "$cg/cgroup.subtree_control" "$cg/session" \
		"$cg/session/cgroup.procs"; do
		[ -e "$f" ] || continue
		chown "$1:$1" "$f" 2>/dev/null || {
			echo "cannot hand $f to $1" >&2
			return 1
		}
	done
	echo "$cg/session/cgroup.procs"
}
