# Lógica da partição de jogos (D6), compartilhada pelo init e pelos testes.
# Funciona sobre um disco real (/dev/mmcblk0, /dev/vda) ou sobre um arquivo de
# imagem: nos arquivos, as operações na partição usam uma cópia temporária que
# depois é gravada de volta no offset certo.
#
# Regra central: uma partição 2 existente nunca é formatada, recriada ou
# redimensionada.

SECTOR=512
ALIGN=2048          # partições alinhadas a 1 MiB
MIN_ROMS=131072     # só cria a ROMS com pelo menos 64 MiB livres
: "${TMPDIR:=/tmp}"

# Mensagens vão para a tela (stderr) e para o dmesg, que entra no log de boot.
log() { echo "lume: $*" >&2; [ -w /dev/kmsg ] && echo "lume: $*" > /dev/kmsg; return 0; }

# Nó de bloco da partição N (mmcblk0 -> mmcblk0p2, vda -> vda2).
part_node() {
	case "$1" in
	*[0-9]) echo "${1}p$2" ;;
	*) echo "$1$2" ;;
	esac
}

disk_sectors() {
	if [ -b "$1" ]; then
		cat "/sys/class/block/$(basename "$1")/size"
	else
		echo $(( $(wc -c < "$1") / SECTOR ))
	fi
}

# Campo (start|size|type) da partição N, lido da tabela pelo sfdisk.
part_field() {
	sfdisk -d "$1" 2>/dev/null | awk -v n="$2" -v f="$3" '
		/ : start=/ { i++; if (i == n) {
			gsub(/ /, ""); sub(/^[^:]*:/, "")
			k = split($0, kv, ",")
			for (j = 1; j <= k; j++) { split(kv[j], p, "="); if (p[1] == f) print p[2] }
		} }'
}

has_part() { [ -n "$(part_field "$1" "$2" start)" ]; }

# File system type from the boot sector of the partition that starts at $2. "usbc": the
# sector holds a USB Mass Storage command block ("USBC" signature) instead of data, the
# mark of a faulty USB card reader (14cd:125d) that wrote its commands into the card.
fs_type_at() {
	local oem fat32
	if [ "$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 count=4 2>/dev/null)" = USBC ]; then
		echo usbc
		return
	fi
	oem=$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 skip=3 count=8 2>/dev/null | tr -d '\000')
	fat32=$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 skip=82 count=8 2>/dev/null | tr -d '\000')
	case "$oem" in
	"EXFAT   ") echo exfat; return ;;
	"NTFS    ") echo ntfs; return ;;
	esac
	case "$fat32" in "FAT32   ") echo vfat; return ;; esac
	if [ -z "$(dd if="$1" bs=$SECTOR skip="$2" count=8 2>/dev/null | tr -d '\000')" ]; then
		echo empty
	else
		echo unknown
	fi
}

# Primeiro setor livre alinhado depois da partição 1.
free_start() {
	local s z
	s=$(part_field "$1" 1 start); z=$(part_field "$1" 1 size)
	echo $(( (s + z + ALIGN - 1) / ALIGN * ALIGN ))
}

# What to do with partition 2: create | check | usbc | foreign | nospace
decide_p2() {
	if ! has_part "$1" 2; then
		local start total
		start=$(free_start "$1"); total=$(disk_sectors "$1")
		if [ $(( total - start )) -ge $MIN_ROMS ]; then echo create; else echo nospace; fi
		return
	fi
	case "$(fs_type_at "$1" "$(part_field "$1" 2 start)")" in
	exfat) echo check ;;
	usbc) echo usbc ;;
	*) echo foreign ;;
	esac
}

# Roda "$@ <caminho da partição N>" no nó do kernel ou numa cópia (arquivo de imagem).
with_part() {
	local disk="$1" n="$2" rc; shift 2
	if [ -b "$disk" ]; then
		"$@" "$(part_node "$disk" "$n")"
		return
	fi
	local s z tmp="$TMPDIR/part$n.$$"
	s=$(part_field "$disk" "$n" start); z=$(part_field "$disk" "$n" size)
	dd if="$disk" of="$tmp" bs=$SECTOR skip="$s" count="$z" 2>/dev/null
	rc=0; "$@" "$tmp" || rc=$?
	dd if="$tmp" of="$disk" bs=$SECTOR seek="$s" conv=notrunc 2>/dev/null
	rm -f "$tmp"
	return $rc
}

wait_node() {
	local i=0
	while [ ! -b "$1" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
	[ -b "$1" ]
}

create_p2() {
	local start
	start=$(free_start "$1")
	echo "start=$start, type=7" | sfdisk --append --no-reread -q "$1" >/dev/null || return 1
	if [ -b "$1" ]; then
		blockdev --rereadpt "$1" || return 1
		wait_node "$(part_node "$1" 2)" || return 1
	fi
}

format_roms() { mkfs.exfat -L ROMS "$1" >/dev/null; }

# fsck.exfat -p: 0 = limpa, 1 = erros corrigidos, outros = erros restantes.
check_roms() {
	local out rc=0
	out=$(fsck.exfat -p "$1" 2>&1) || rc=$?
	case $rc in
	0) log "ROMS checked: clean" ;;
	1) log "ROMS checked: errors corrected" ;;
	*) log "ROMS checked: uncorrected errors (code $rc)"; echo "$out" | while read -r l; do log "  $l"; done ;;
	esac
	return 0
}

# Prepara a partição de jogos. Imprime "ok" se a ROMS pode ser montada.
setup_storage() {
	local disk="$1" action
	action=$(decide_p2 "$disk")
	case "$action" in
	create)
		log "first boot: creating ROMS partition (exFAT) on remaining disk space..."
		if create_p2 "$disk" && with_part "$disk" 2 format_roms; then
			log "ROMS partition created"
			echo ok
		else
			log "ERROR: failed to create ROMS partition"
		fi
		;;
	check)
		with_part "$disk" 2 check_roms
		echo ok
		;;
	foreign)
		log "ERROR: partition 2 exists but is not exFAT; nothing formatted. Continuing without ROMS."
		;;
	usbc)
		log "ERROR: the first sector of partition 2 holds a USB command block (\"USBC\") instead of exFAT data: the card was corrupted by a faulty USB card reader on the PC. Nothing formatted; continuing without ROMS. Use another card reader, then repair the partition with fsck.exfat or write the card again (r36os flash --full)."
		;;
	nospace)
		log "ERROR: no free space for ROMS partition"
		;;
	esac
}

# Estrutura de pastas do contrato de jogos. Recria só o que falta.
make_folders() {
	local root="$1" s; shift
	for s in "$@"; do mkdir -p "$root/roms/$s"; done
	for s in bios saves states screenshots system; do mkdir -p "$root/$s"; done
}
