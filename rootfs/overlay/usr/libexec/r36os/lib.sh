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
