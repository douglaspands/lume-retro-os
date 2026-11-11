# Logs de diagnóstico (D14): configuração, contador de boot, eventos, descarga em lote
# e rotação. Todos os logs ficam em ROMS/logs/ (LOGS_DIR); os coletores escrevem na RAM
# (LOGS_RAM) e logs_flush descarrega em lote. Requer lib.sh antes (R36OS_RUN, atomic_copy).
# O conteúdo, os nomes de arquivos e os identificadores dos logs são em inglês; o idioma
# só é escolhido na interface com o usuário.
#
# LOGS_DIR, LOGS_RAM, LOGS_CONF e LOGS_MOUNT podem ser trocados pelos testes.

LOGS_DIR=${LOGS_DIR:-/storage/logs}
LOGS_RAM=${LOGS_RAM:-$R36OS_RUN/logs}
LOGS_CONF=${LOGS_CONF:-/storage/system/etc/logs.conf}
LOGS_MOUNT=${LOGS_MOUNT:-/storage}
# Teto de cada CSV de métricas (cerca de 30 h a 5 s) e do events.log antes de girar
METRICS_MAX_BYTES=4194304
EVENTS_MAX_BYTES=1048576
EVENTS_KEEP=3
FRONTEND_MAX_BYTES=4194304
# Rastreio do frontend (trace/boot-<n>.log): teto no cartão e na RAM (buffer entre descargas)
TRACE_MAX_BYTES=2097152
# O log do RetroArch vive na RAM (overlay de 32 MiB): acima de RAM_MAX fica só o fim
FRONTEND_RAM_MAX_BYTES=8388608
FRONTEND_RAM_KEEP_BYTES=1048576
LOG_TYPES="boot hw metrics trace frontend"

LOGS_CONF_DEFAULT='# Lume Retro OS diagnostic logs (ROMS/logs/). Editable on a PC.
# enable=0 turns off the hardware snapshot and the metrics (boot log and events stay on).
enable=1
# seconds between metric samples
interval=5
# seconds between writes to the card (the rest stays in RAM until then)
flush=60
# how many boots to keep in boot/, hw/, metrics/ and frontend/
keep_boots=30
# size cap of ROMS/logs/ in MiB: above it the oldest files are deleted
max_mb=64'

# Lê o logs.conf (valores fora da faixa ficam no padrão).
logs_conf() {
	LOG_ENABLE=1 LOG_INTERVAL=5 LOG_FLUSH=60 LOG_KEEP=30 LOG_MAX_MB=64
	[ -f "$LOGS_CONF" ] || return 0
	local k v
	while IFS='=' read -r k v; do
		k=$(echo "$k" | tr -d ' \t\r')
		v=$(echo "$v" | tr -cd '0-9')
		case "$k" in ''|\#*) continue ;; esac
		[ -n "$v" ] || continue
		case "$k" in
		enable) [ "$v" = 0 ] && LOG_ENABLE=0 || LOG_ENABLE=1 ;;
		interval) [ "$v" -ge 1 ] && LOG_INTERVAL=$v ;;
		flush) [ "$v" -ge 5 ] && LOG_FLUSH=$v ;;
		keep_boots) [ "$v" -ge 1 ] && LOG_KEEP=$v ;;
		max_mb) [ "$v" -ge 8 ] && LOG_MAX_MB=$v ;;
		esac
	done < "$LOGS_CONF"
	return 0
}

# A ROMS está montada (os logs vão para o cartão)?
logs_on_disk() { mountpoint -q "$LOGS_MOUNT" 2>/dev/null; }

# Número deste boot (0 sem ROMS).
boot_n() { cat "$LOGS_RAM/boot-n" 2>/dev/null || echo 0; }

# Evento: event <categoria> <OK|FAIL> <detalhe...>
# Linha: <time> <boot> <category> <OK|FAIL> <detail>
event() {
	local cat="$1" res="$2"; shift 2
	mkdir -p "$LOGS_RAM"
	printf '%s %s %s %s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S')" "$(boot_n)" "$cat" "$res" "$*" \
		>> "$LOGS_RAM/events.pending"
	return 0
}

# Arquivos boot-<n>.* de um diretório, do mais antigo ao mais novo.
_boot_files() {
	ls "$1" 2>/dev/null | sed -n 's/^boot-\([0-9][0-9]*\)\..*$/\1 &/p' | sort -n | cut -d' ' -f2
}

_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

# Rastreio: trace <texto...> -> uma linha com hora na RAM (trace.pending). O buffer na RAM
# também tem teto: sem a ROMS (nada é descarregado) ele não cresce além de TRACE_MAX_BYTES.
trace() {
	mkdir -p "$LOGS_RAM"
	[ "$(_size "$LOGS_RAM/trace.pending")" -lt "$TRACE_MAX_BYTES" ] || return 0
	printf '%s %s\n' "$(date '+%H:%M:%S')" "$*" >> "$LOGS_RAM/trace.pending"
	return 0
}

# Move um buffer da RAM para o fim de um arquivo do cartão, com fsync.
# O nome temporário é único: dois flushes ao mesmo tempo não perdem linhas.
_drain() {  # buffer destino [cabeçalho] [limite]
	local buf="$1" dst="$2" hdr="${3:-}" max="${4:-0}" tmp
	[ -s "$buf" ] || return 0
	tmp="$buf.flush.$$"
	mv -f "$buf" "$tmp" || return 0
	mkdir -p "$(dirname "$dst")"
	if [ -n "$hdr" ] && [ ! -s "$dst" ]; then cat "$hdr" > "$dst"; fi
	if [ "$max" -eq 0 ] || [ "$(_size "$dst")" -lt "$max" ]; then
		cat "$tmp" >> "$dst" && fsync "$dst" 2>/dev/null
	fi
	rm -f "$tmp"
}

# Limita o log do frontend na RAM: passando de FRONTEND_RAM_MAX_BYTES, fica só o fim.
# O RetroArch escreve com O_APPEND, então truncar o arquivo no lugar é seguro.
frontend_log_trim() {  # arquivo
	[ "$(_size "$1")" -gt "$FRONTEND_RAM_MAX_BYTES" ] || return 0
	tail -c "$FRONTEND_RAM_KEEP_BYTES" "$1" > "$1.trim.$$" || { rm -f "$1.trim.$$"; return 0; }
	cat "$1.trim.$$" > "$1"
	rm -f "$1.trim.$$" "$LOGS_RAM/frontend.size"
	return 0
}

# Descarga em lote: eventos, métricas, rastreio e log do frontend; depois a rotação.
logs_flush() {
	logs_on_disk || return 0
	local n f size
	n=$(boot_n)
	mkdir -p "$LOGS_DIR"
	_drain "$LOGS_RAM/events.pending" "$LOGS_DIR/events.log"
	_drain "$LOGS_RAM/metrics.pending" "$LOGS_DIR/metrics/boot-$n.csv" \
		"$LOGS_RAM/metrics.header" "$METRICS_MAX_BYTES"
	_drain "$LOGS_RAM/trace.pending" "$LOGS_DIR/trace/boot-$n.log" "" "$TRACE_MAX_BYTES"
	# Log do frontend: cópia inteira (só o fim, até o teto), quando mudou
	f=${FRONTEND_LOG:-/var/log/frontend.log}
	frontend_log_trim "$f"
	if [ -s "$f" ]; then
		size=$(_size "$f")
		if [ "$size" != "$(cat "$LOGS_RAM/frontend.size" 2>/dev/null)" ]; then
			mkdir -p "$LOGS_DIR/frontend"
			tail -c "$FRONTEND_MAX_BYTES" "$f" > "$LOGS_RAM/frontend.copy"
			atomic_copy "$LOGS_RAM/frontend.copy" "$LOGS_DIR/frontend/boot-$n.log"
			rm -f "$LOGS_RAM/frontend.copy"
			echo "$size" > "$LOGS_RAM/frontend.size"
		fi
	fi
	logs_rotate
}

# Mantém os N boots mais recentes de um diretório.
_keep_newest() {  # dir N
	set -- "$1" "$2" $(_boot_files "$1")
	local dir="$1" keep="$2"; shift 2
	while [ $# -gt "$keep" ]; do rm -f "$dir/$1"; shift; done
}

# Apaga o arquivo mais antigo de um tipo, exceto os do boot atual. 1 se não há.
_drop_oldest() {  # dir
	local f cur
	cur=$(boot_n)
	f=$(_boot_files "$1" | head -n 1)
	[ -n "$f" ] || return 1
	case "$f" in "boot-$cur."*) return 1 ;; esac
	rm -f "$1/$f"
}

logs_rotate() {
	[ -d "$LOGS_DIR" ] || return 0
	logs_conf
	local t i max used
	for t in $LOG_TYPES; do _keep_newest "$LOGS_DIR/$t" "$LOG_KEEP"; done
	# events.log gira em EVENTS_MAX_BYTES, mantendo EVENTS_KEEP antigos
	if [ "$(_size "$LOGS_DIR/events.log")" -ge "$EVENTS_MAX_BYTES" ]; then
		rm -f "$LOGS_DIR/events.$EVENTS_KEEP.log"
		i=$EVENTS_KEEP
		while [ "$i" -gt 1 ]; do
			[ -f "$LOGS_DIR/events.$((i - 1)).log" ] && \
				mv -f "$LOGS_DIR/events.$((i - 1)).log" "$LOGS_DIR/events.$i.log"
			i=$((i - 1))
		done
		mv -f "$LOGS_DIR/events.log" "$LOGS_DIR/events.1.log"
	fi
	# Teto total: métricas mais antigas primeiro, depois frontend, hw, boot e eventos antigos
	max=$((LOG_MAX_MB * 1024))
	while :; do
		used=$(du -sk "$LOGS_DIR" 2>/dev/null | cut -f1)
		[ "${used:-0}" -gt "$max" ] || break
		_drop_oldest "$LOGS_DIR/metrics" && continue
		_drop_oldest "$LOGS_DIR/trace" && continue
		_drop_oldest "$LOGS_DIR/frontend" && continue
		_drop_oldest "$LOGS_DIR/hw" && continue
		_drop_oldest "$LOGS_DIR/boot" && continue
		i=$EVENTS_KEEP
		while [ "$i" -ge 1 ] && [ ! -f "$LOGS_DIR/events.$i.log" ]; do i=$((i - 1)); done
		[ "$i" -ge 1 ] && { rm -f "$LOGS_DIR/events.$i.log"; continue; }
		break
	done
	return 0
}
