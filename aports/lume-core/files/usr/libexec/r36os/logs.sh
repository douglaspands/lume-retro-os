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
	# shell expansions only (no process per line): logs_rotate reads it at every flush
	while IFS='=' read -r k v; do
		k=${k//[ 	]/}
		v=${v//[!0-9]/}
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

# Is ROMS mounted (the logs go to the card)? Read from the mount table with the shell's own
# read: logs_flush asks at every flush (logd cost budget, game-governor D8).
logs_on_disk() {
	local dev mnt rest
	{
		while read -r dev mnt rest; do
			[ "$mnt" = "$LOGS_MOUNT" ] && return 0
		done < "${MOUNTS_FILE:-/proc/mounts}"
	} 2>/dev/null
	return 1
}

# Number of this boot (0 without ROMS): boot_n prints it, boot_n_var sets BOOT_N without a
# subshell.
boot_n_var() {
	BOOT_N=""
	{ read -r BOOT_N < "$LOGS_RAM/boot-n"; } 2>/dev/null
	BOOT_N=${BOOT_N:-0}
}
boot_n() { boot_n_var; echo "$BOOT_N"; }

# Wall clock without a process per line (game-governor D8): log_clock [uptime] sets LOG_TS
# (2026-11-09T10:00:05) and LOG_HMS (10:00:05). The epoch comes from the shell's
# EPOCHSECONDS when it has one, otherwise from one `date` per batch (LOG_CLOCK_REFRESH
# seconds of uptime) plus the uptime since then; the local UTC offset comes from that same
# `date`. The date is then worked out with shell arithmetic (days to civil date).
LOG_CLK_UP=-100000 LOG_CLK_EPOCH=0 LOG_CLK_OFF=0
LOG_CLOCK_REFRESH=${LOG_CLOCK_REFRESH:-60}
log_clock() {
	local up=${1:-} s z h m d sec era doe yoe doy mp y
	[ -n "$up" ] || { read -r up _ < "${UPTIME_FILE:-/proc/uptime}"; } 2>/dev/null
	up=${up%%.*}
	up=${up:-0}
	if [ $((up - LOG_CLK_UP)) -ge "$LOG_CLOCK_REFRESH" ] || [ "$up" -lt "$LOG_CLK_UP" ]; then
		set -- $(date '+%s %z')
		LOG_CLK_EPOCH=${1:-0} LOG_CLK_UP=$up
		z=${2:-+0000}
		h=${z#?}; h=${h%??}; m=${z#???}
		# "1$h - 100": a leading zero would make "08" an invalid octal number
		LOG_CLK_OFF=$(( (1$h - 100) * 3600 + (1$m - 100) * 60 ))
		case "$z" in -*) LOG_CLK_OFF=$((-LOG_CLK_OFF)) ;; esac
		# other writers of trace.pending: count its size again (see trace)
		TRACE_BYTES=""
	fi
	if [ -n "${EPOCHSECONDS:-}" ]; then
		s=$EPOCHSECONDS
	else
		s=$((LOG_CLK_EPOCH + up - LOG_CLK_UP))
	fi
	s=$((s + LOG_CLK_OFF))
	d=$((s / 86400)) sec=$((s % 86400))
	z=$((d + 719468))
	era=$((z / 146097))
	doe=$((z - era * 146097))
	yoe=$(( (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365 ))
	doy=$((doe - (365 * yoe + yoe / 4 - yoe / 100)))
	mp=$(( (5 * doy + 2) / 153 ))
	d=$((doy - (153 * mp + 2) / 5 + 1))
	y=$((yoe + era * 400))
	if [ "$mp" -lt 10 ]; then m=$((mp + 3)); else m=$((mp - 9)); fi
	[ "$m" -le 2 ] && y=$((y + 1))
	[ "$m" -ge 10 ] || m=0$m
	[ "$d" -ge 10 ] || d=0$d
	h=$((sec / 3600)) z=$((sec / 60 % 60)) sec=$((sec % 60))
	[ "$h" -ge 10 ] || h=0$h
	[ "$z" -ge 10 ] || z=0$z
	[ "$sec" -ge 10 ] || sec=0$sec
	LOG_HMS=$h:$z:$sec
	LOG_TS=$y-$m-${d}T$LOG_HMS
}

# The events buffer is shared with the launcher supervisor (lume-run, user game, appends its
# game lines, lume-launcher D10). The file is created with mode 666, and events_shared makes
# the RAM directory sticky and writable by the game group, so lume-run can create the file
# again when a flush has just moved it to the card (seen in test-vm on 2026-11-14: without
# it the game lines written between a flush and the next root event were lost).
events_file() {
	[ -e "$LOGS_RAM/events.pending" ] && return 0
	: > "$LOGS_RAM/events.pending"
	chmod 666 "$LOGS_RAM/events.pending" 2>/dev/null
	return 0
}
events_shared() {  # group
	mkdir -p "$LOGS_RAM"
	chgrp "$1" "$LOGS_RAM" && chmod 1775 "$LOGS_RAM"
	events_file
}

# Event: event <category> <OK|FAIL> <detail...>
# Linha: <time> <boot> <category> <OK|FAIL> <detail>
event() {
	local cat="$1" res="$2"; shift 2
	[ -d "$LOGS_RAM" ] || mkdir -p "$LOGS_RAM"
	events_file
	log_clock
	boot_n_var
	printf '%s %s %s %s %s\n' "$LOG_TS" "$BOOT_N" "$cat" "$res" "$*" \
		>> "$LOGS_RAM/events.pending"
	return 0
}

# Arquivos boot-<n>.* de um diretório, do mais antigo ao mais novo.
_boot_files() {
	ls "$1" 2>/dev/null | sed -n 's/^boot-\([0-9][0-9]*\)\..*$/\1 &/p' | sort -n | cut -d' ' -f2
}

_size() { stat -c %s "$1" 2>/dev/null || echo 0; }

# Trace: trace <text...> -> one line with the time in RAM (trace.pending). The RAM buffer is
# capped too: without ROMS (nothing is flushed) it does not grow past TRACE_MAX_BYTES.
# No process per line (game-governor D8): the size is counted in TRACE_BYTES as this process
# writes, and measured again (one stat) when the buffer is new to it, after a flush and once
# per clock batch (log_clock), which takes in the lines of the other writers.
TRACE_BYTES=""
trace() {
	local l="$*"
	[ -d "$LOGS_RAM" ] || mkdir -p "$LOGS_RAM"
	log_clock
	if [ ! -e "$LOGS_RAM/trace.pending" ]; then
		TRACE_BYTES=0
	elif [ -z "$TRACE_BYTES" ]; then
		TRACE_BYTES=$(_size "$LOGS_RAM/trace.pending")
	fi
	[ "$TRACE_BYTES" -lt "$TRACE_MAX_BYTES" ] || return 0
	printf '%s %s\n' "$LOG_HMS" "$l" >> "$LOGS_RAM/trace.pending"
	TRACE_BYTES=$((TRACE_BYTES + ${#l} + 10))
	return 0
}

# Move um buffer da RAM para o fim de um arquivo do cartão, com fsync.
# O nome temporário é único: dois flushes ao mesmo tempo não perdem linhas.
_drain() {  # buffer destino [cabeçalho] [limite]
	local buf="$1" dst="$2" hdr="${3:-}" max="${4:-0}" tmp
	[ -s "$buf" ] || return 0
	tmp="$buf.flush.$$"
	mv -f "$buf" "$tmp" || return 0
	[ -d "${dst%/*}" ] || mkdir -p "${dst%/*}"
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
	local n f size old=""
	boot_n_var
	n=$BOOT_N
	[ -d "$LOGS_DIR" ] || mkdir -p "$LOGS_DIR"
	_drain "$LOGS_RAM/events.pending" "$LOGS_DIR/events.log"
	events_file
	_drain "$LOGS_RAM/metrics.pending" "$LOGS_DIR/metrics/boot-$n.csv" \
		"$LOGS_RAM/metrics.header" "$METRICS_MAX_BYTES"
	_drain "$LOGS_RAM/trace.pending" "$LOGS_DIR/trace/boot-$n.log" "" "$TRACE_MAX_BYTES"
	TRACE_BYTES=""
	# Frontend log: whole copy (only the end, up to the cap), when it changed
	f=${FRONTEND_LOG:-/var/log/frontend.log}
	size=$(_size "$f")
	if [ "$size" -gt "$FRONTEND_RAM_MAX_BYTES" ]; then
		frontend_log_trim "$f"
		size=$(_size "$f")
	fi
	if [ "$size" -gt 0 ]; then
		{ read -r old < "$LOGS_RAM/frontend.size"; } 2>/dev/null
		if [ "$size" != "$old" ]; then
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
# With the shell's own glob and arithmetic (it runs for each type at every flush): while
# there are more than N, the lowest boot number goes.
_keep_newest() {  # dir N
	local dir="$1" keep="$2" f n count min minf
	while :; do
		count=0 min="" minf=""
		for f in "$dir"/boot-*.*; do
			n=${f##*/boot-}
			n=${n%%.*}
			case "$n" in ''|*[!0-9]*) continue ;; esac
			count=$((count + 1))
			if [ -z "$min" ] || [ "$n" -lt "$min" ]; then min=$n minf=$f; fi
		done
		[ "$count" -gt "$keep" ] || return 0
		rm -f "$minf"
	done
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
		used=$(du -sk "$LOGS_DIR" 2>/dev/null)
		used=${used%%[!0-9]*}
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
