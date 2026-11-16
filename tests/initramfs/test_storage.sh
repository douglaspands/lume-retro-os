#!/bin/busybox sh
# Testes da lógica de partições do initramfs (tarefas 4.1-4.3) sobre imagens falsas.
# Roda no container do builder: busybox sh tests/initramfs/test_storage.sh
set -u
cd "$(dirname "$0")"
. ../../initramfs/lib/storage.sh
export TMPDIR=$(mktemp -d)
W=$TMPDIR
FAILS=0
ok()   { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then ok "$1"; else fail "$1"; fi; }

# Imagem com MBR e só a BOOT (1 GiB a partir de 16 MiB), como sai do build.
mkimg() {
	rm -f "$1"; truncate -s "$2" "$1"
	printf 'label: dos\nlabel-id: 0x1a2b3c4d\nstart=32768, size=2097152, type=c\n' | sfdisk -q "$1"
}
p2_bytes() {  # $1 imagem, $2 offset no setor de boot, $3 tamanho -> hex
	dd if="$1" bs=512 skip="$(part_field "$1" 2 start)" count=1 2>/dev/null \
		| dd bs=1 skip="$2" count="$3" 2>/dev/null | hexdump -v -e '/1 "%02x"'
}
p2_md5() { dd if="$1" bs=512 skip="$(part_field "$1" 2 start)" count=2048 2>/dev/null | md5sum | cut -d' ' -f1; }
label_of() { exfatlabel "$1" 2>/dev/null | sed -n 's/.*label: *//p' | tail -n1; }

# Conta chamadas de mkfs (nunca pode acontecer com p2 existente).
MKFS_LOG=$W/mkfs.log; : > "$MKFS_LOG"
format_roms() { echo "$1" >> "$MKFS_LOG"; mkfs.exfat -L ROMS "$1" >/dev/null; }

### 1. Sem partição 2: cria, formata exFAT com rótulo ROMS
IMG=$W/disk.img
mkimg "$IMG" 1200M
check "sem-p2: decisão create" '[ "$(decide_p2 "$IMG")" = create ]'
R=$(setup_storage "$IMG" 2>"$W/log1")
check "sem-p2: setup ok" '[ "$R" = ok ]'
check "sem-p2: p2 criada tipo 7" '[ "$(part_field "$IMG" 2 type)" = 7 ]'
check "sem-p2: p2 alinhada após a BOOT" '[ "$(part_field "$IMG" 2 start)" = 2129920 ]'
check "sem-p2: p2 até o fim do disco" '[ $(( $(part_field "$IMG" 2 start) + $(part_field "$IMG" 2 size) )) = $(disk_sectors "$IMG") ]'
check "sem-p2: exFAT" '[ "$(fs_type_at "$IMG" "$(part_field "$IMG" 2 start)")" = exfat ]'
check "sem-p2: rótulo ROMS" '[ "$(with_part "$IMG" 2 label_of)" = ROMS ]'
check "sem-p2: mensagem na tela" 'grep -q "ROMS partition created" "$W/log1"'
check "sem-p2: BOOT intacta" '[ "$(part_field "$IMG" 1 start)" = 32768 ] && [ "$(part_field "$IMG" 1 size)" = 2097152 ]'

### 2. p2 exFAT existente: só verifica, nunca formata
: > "$MKFS_LOG"
SERIAL=$(p2_bytes "$IMG" 100 4)
check "exfat: decisão check" '[ "$(decide_p2 "$IMG")" = check ]'
R=$(setup_storage "$IMG" 2>"$W/log2")
check "exfat: setup ok" '[ "$R" = ok ]'
check "exfat: mkfs não chamado" '[ ! -s "$MKFS_LOG" ]'
check "exfat: mesmo volume (serial)" '[ "$(p2_bytes "$IMG" 100 4)" = "$SERIAL" ]'
check "exfat: verificação no log" 'grep -q "ROMS checked" "$W/log2"'

### 3. p2 suja (VolumeDirty): fsck -p roda, resultado no log, monta
FLAGS_OFF=$(( $(part_field "$IMG" 2 start) * 512 + 106 ))
printf '\002' | dd of="$IMG" bs=1 seek=$FLAGS_OFF conv=notrunc 2>/dev/null
check "suja: flag marcada" '[ "$(p2_bytes "$IMG" 106 1)" = 02 ]'
R=$(setup_storage "$IMG" 2>"$W/log3")
check "suja: setup ok (monta)" '[ "$R" = ok ]'
check "suja: verificação no log" 'grep -q "ROMS checked" "$W/log3"'
check "suja: mkfs não chamado" '[ ! -s "$MKFS_LOG" ]'
check "suja: mesmo volume (serial)" '[ "$(p2_bytes "$IMG" 100 4)" = "$SERIAL" ]'
check "suja: flag limpa após fsck" '[ "$(p2_bytes "$IMG" 106 1)" = 00 ]'

### 4. p2 com outro sistema de arquivos: não toca, segue sem ROMS
IMG4=$W/foreign.img
mkimg "$IMG4" 1200M
printf 'start=2129920, type=83\n' | sfdisk -q --append "$IMG4"
with_part "$IMG4" 2 sh -c 'mkfs.vfat "$0" >/dev/null'
MD5=$(p2_md5 "$IMG4")
check "outro-fs: decisão foreign" '[ "$(decide_p2 "$IMG4")" = foreign ]'
R=$(setup_storage "$IMG4" 2>"$W/log4")
check "outro-fs: sem ROMS" '[ -z "$R" ]'
check "outro-fs: erro no log" 'grep -q "not exFAT" "$W/log4"'
check "outro-fs: conteúdo intacto" '[ "$(p2_md5 "$IMG4")" = "$MD5" ]'
check "outro-fs: tabela intacta" '[ "$(part_field "$IMG4" 2 type)" = 83 ]'
check "outro-fs: mkfs não chamado" '[ ! -s "$MKFS_LOG" ]'

### 4b. p2 corrupted by the faulty USB reader: a USB command block ("USBC") in its first
### sector. Not formatted either, and the log names the cause (task 11.5)
IMG4B=$W/usbc.img
mkimg "$IMG4B" 1200M
printf 'start=2129920, type=7\n' | sfdisk -q --append "$IMG4B"
with_part "$IMG4B" 2 sh -c 'mkfs.exfat -L ROMS "$0" >/dev/null'
printf 'USBC\001\002\003\004' | dd of="$IMG4B" bs=512 seek=2129920 conv=notrunc 2>/dev/null
MD5=$(p2_md5 "$IMG4B")
: > "$MKFS_LOG"
check "usbc: signature detected" '[ "$(fs_type_at "$IMG4B" 2129920)" = usbc ]'
check "usbc: decision usbc" '[ "$(decide_p2 "$IMG4B")" = usbc ]'
R=$(setup_storage "$IMG4B" 2>"$W/log4b")
check "usbc: no ROMS" '[ -z "$R" ]'
check "usbc: log names the card reader" 'grep -q "USB command block" "$W/log4b" && grep -q "card reader" "$W/log4b"'
check "usbc: content untouched" '[ "$(p2_md5 "$IMG4B")" = "$MD5" ]'
check "usbc: mkfs not called" '[ ! -s "$MKFS_LOG" ]'

### 5. p2 vazia (sem sistema de arquivos): também não formata
IMG5=$W/empty.img
mkimg "$IMG5" 1200M
printf 'start=2129920, type=7\n' | sfdisk -q --append "$IMG5"
check "p2-vazia: decisão foreign" '[ "$(decide_p2 "$IMG5")" = foreign ]'

### 6. Cartão sem espaço depois da BOOT
IMG6=$W/small.img
mkimg "$IMG6" 1050M
check "sem-espaço: decisão nospace" '[ "$(decide_p2 "$IMG6")" = nospace ]'
R=$(setup_storage "$IMG6" 2>/dev/null)
check "sem-espaço: nada criado" '! has_part "$IMG6" 2'

### 7. Estrutura de pastas: recria o que falta sem apagar nada
S=$W/storage
make_folders "$S" nes snes gba
echo jogo > "$S/roms/nes/jogo.nes"
echo save > "$S/saves/x.srm"
rm -r "$S/roms/gba" "$S/screenshots"
make_folders "$S" nes snes gba
check "pastas: gba recriada vazia" '[ -d "$S/roms/gba" ] && [ -z "$(ls "$S/roms/gba")" ]'
check "pastas: screenshots recriada" '[ -d "$S/screenshots" ]'
check "pastas: jogo preservado" '[ "$(cat "$S/roms/nes/jogo.nes")" = jogo ]'
check "pastas: save preservado" '[ "$(cat "$S/saves/x.srm")" = save ]'
for d in roms bios saves states screenshots system; do
	check "pastas: $d existe" '[ -d "$S/$d" ]'
done

### 8. Nome do nó de partição
check "nó: mmcblk0 -> mmcblk0p2" '[ "$(part_node /dev/mmcblk0 2)" = /dev/mmcblk0p2 ]'
check "nó: vda -> vda2" '[ "$(part_node /dev/vda 2)" = /dev/vda2 ]'

### 9. SYSTEM of each console on the single card (r36s-single-card, task 5.1)
check "system: ga36 -> ga36/SYSTEM" '[ "$(system_file ga36)" = ga36/SYSTEM ]'
check "system: r36s -> r36s/SYSTEM" '[ "$(system_file r36s)" = r36s/SYSTEM ]'
check "system: vm -> SYSTEM" '[ "$(system_file vm)" = SYSTEM ]'
check "system: no board -> SYSTEM" '[ "$(system_file "")" = SYSTEM ]'
check "system: labels" '[ "$(console_label ga36)" = GA36 ] && [ "$(console_label r36s)" = R36S ]'
# BOOT of a single card with only the GA36 system: the R36S must not take it
B=$W/boot
mkdir -p "$B/ga36" && : > "$B/ga36/SYSTEM"
check "system: ga36 finds its SYSTEM" '[ -f "$B/$(system_file ga36)" ]'
check "system: r36s does not find one" '[ ! -f "$B/$(system_file r36s)" ]'
# the init rescues with the console and the file in the message, with no fallback
INIT=../../initramfs/init
check "system: init uses system_file" 'grep -q "SYSTEM=\$(system_file \"\$BOARD\")" "$INIT"'
check "system: rescue names the file and the console" \
	'grep -q "rescue \"BOOT has no \$SYSTEM, the system of the \$(console_label \"\$BOARD\")" "$INIT"'
check "system: never mounts /boot/SYSTEM directly" '! grep -q "/boot/SYSTEM " "$INIT"'

### 9b. The .old of a push cut between its two renames (push-boot-swap D4)
check "boot_file: present" '[ "$(boot_file "$B" ga36/SYSTEM 2>"$W/bf1")" = ga36/SYSTEM ] && [ ! -s "$W/bf1" ]'
: > "$B/ga36/SYSTEM.old"
check "boot_file: present wins over .old" '[ "$(boot_file "$B" ga36/SYSTEM 2>/dev/null)" = ga36/SYSTEM ]'
rm "$B/ga36/SYSTEM"
check "boot_file: only .old" '[ "$(boot_file "$B" ga36/SYSTEM 2>"$W/bf2")" = ga36/SYSTEM.old ]'
check "boot_file: .old logged as ERROR" 'grep -qx "lume: ERROR: BOOT has no ga36/SYSTEM; using ga36/SYSTEM.old from the previous build" "$W/bf2"'
check "boot_file: neither fails" '! boot_file "$B" r36s/SYSTEM >/dev/null 2>"$W/bf3" && [ ! -s "$W/bf3" ]'
check "boot_file: no other console" '! boot_file "$B" r36s/SYSTEM >/dev/null 2>&1'
check "system: init mounts the boot_file result" \
	'grep -q "ROOT_FILE=\$(boot_file /boot \"\$SYSTEM\") || rescue" "$INIT" && grep -q "ro,loop \"/boot/\$ROOT_FILE\" /lower" "$INIT"'
rm "$B/ga36/SYSTEM.old"; : > "$B/ga36/SYSTEM"

### 10. Kernel modules image of each console (kernel-modules-image 2.1, 2.2)
check "modules: ga36 -> ga36/modules" '[ "$(modules_file ga36)" = ga36/modules ]'
check "modules: r36s -> r36s/modules" '[ "$(modules_file r36s)" = r36s/modules ]'
check "modules: vm -> nothing" '[ -z "$(modules_file vm)" ] && [ -z "$(modules_file "")" ]'
M=$W/img
mkdir -p "$M/6.18.62"
check "modules: one folder, same release" 'modules_match "$M" 6.18.62'
check "modules: other release" '! modules_match "$M" 6.18.63'
check "modules: no release given" '! modules_match "$M" ""'
mkdir -p "$M/6.18.61"
check "modules: two folders" '! modules_match "$M" 6.18.62'
check "modules: found lists both" '[ "$(modules_found "$M")" = "6.18.61 6.18.62" ]'
check "modules: empty image" '! modules_match "$W/none" 6.18.62'

# mount_modules with fake mount/umount/uname: the "image" is a text file with the
# release folders it holds; the loop mount makes those folders in the mount point
RUNNING=6.18.62-r36os
MOUNT_FAILS=""
MLOG=$W/mount.log
uname() { echo "$RUNNING"; }
mount() {
	echo "mount $*" >> "$MLOG"
	case "$1" in
	--move) cp -a "$2/." "$3/" && rm -rf "$2"/* ;;
	-t) [ -z "$MOUNT_FAILS" ] || return 1
		for d in $(cat "$5"); do mkdir -p "$6/$d"; done ;;
	esac
}
umount() { echo "umount $*" >> "$MLOG"; rm -rf "$1"/*; }
run_modules() {  # $1 board, $2 releases in the image (unset: no file) -> log in $W/mlog
	rm -rf "$W/mb" "$W/mm" "$W/root" "$MLOG"
	mkdir -p "$W/mb/ga36" "$W/mb/r36s" "$W/root/lib/modules"; : > "$MLOG"
	[ $# -lt 2 ] || echo "$2" > "$W/mb/$1/modules"
	mount_modules "$1" "$W/mb" "$W/mm" "$W/root" 2> "$W/mlog"
}
run_modules ga36 "$RUNNING"
check "mount: same release on /lib/modules" '[ -d "$W/root/lib/modules/$RUNNING" ]'
check "mount: read-only loop of its own file" 'grep -qx "mount -t squashfs -o ro,loop $W/mb/ga36/modules $W/mm" "$MLOG"'
check "mount: moved into the new root" 'grep -qx "mount --move $W/mm $W/root/lib/modules" "$MLOG"'
check "mount: logged" 'grep -qx "lume: modules: ga36/modules ($RUNNING)" "$W/mlog"'
run_modules r36s "$RUNNING"
check "mount: r36s uses its own folder" 'grep -q "$W/mb/r36s/modules " "$MLOG" && ! grep -q "/ga36/" "$MLOG"'
run_modules ga36
check "missing: nothing mounted" '[ ! -s "$MLOG" ] && [ -z "$(ls "$W/root/lib/modules")" ]'
check "missing: ERROR with the path" 'grep -qx "lume: ERROR: BOOT has no ga36/modules; starting without kernel modules" "$W/mlog"'
run_modules ga36 6.18.61-r36os
check "release: not on /lib/modules" '[ -z "$(ls "$W/root/lib/modules")" ] && grep -q "^umount $W/mm" "$MLOG"'
check "release: ERROR with both releases" 'grep -qx "lume: ERROR: ga36/modules holds modules for 6.18.61-r36os, the running kernel is $RUNNING; starting without kernel modules" "$W/mlog"'
run_modules ga36 "$RUNNING 6.18.61-r36os"
check "two folders: not mounted" '[ -z "$(ls "$W/root/lib/modules")" ] && grep -q "holds modules for 6.18.61-r36os $RUNNING," "$W/mlog"'
# push-boot-swap D4: only modules.old, from a push cut between its two renames
run_modules ga36
echo "$RUNNING" > "$W/mb/ga36/modules.old"
mount_modules ga36 "$W/mb" "$W/mm" "$W/root" 2> "$W/mlog"
check "old: mounts modules.old" 'grep -qx "mount -t squashfs -o ro,loop $W/mb/ga36/modules.old $W/mm" "$MLOG" && [ -d "$W/root/lib/modules/$RUNNING" ]'
check "old: ERROR names the .old" 'grep -qx "lume: ERROR: BOOT has no ga36/modules; using ga36/modules.old from the previous build" "$W/mlog"'
run_modules ga36
echo 6.18.61-r36os > "$W/mb/ga36/modules.old"
mount_modules ga36 "$W/mb" "$W/mm" "$W/root" 2> "$W/mlog"
check "old: release check still applies" '[ -z "$(ls "$W/root/lib/modules")" ] && grep -q "ga36/modules.old holds modules for 6.18.61-r36os" "$W/mlog"'
MOUNT_FAILS=1 run_modules ga36 "$RUNNING"
check "no mount: ERROR" 'grep -qx "lume: ERROR: failed to mount ga36/modules; starting without kernel modules" "$W/mlog"'
MOUNT_FAILS=""
run_modules vm
check "vm: nothing done, nothing logged" '[ ! -s "$MLOG" ] && [ ! -s "$W/mlog" ]'
unset -f mount umount uname
# the init: after select_dtb and the overlay, before the moves and switch_root
line_of() { grep -n "$1" "$INIT" | head -n1 | cut -d: -f1; }
CALL=$(line_of '^mount_modules "\$BOARD" /boot /modules /newroot$')
check "init: calls mount_modules" '[ -n "$CALL" ]'
check "init: after select_dtb" '[ "$CALL" -gt "$(line_of "^select_dtb$")" ]'
check "init: after the overlay" '[ "$CALL" -gt "$(line_of "^mount -t overlay")" ]'
check "init: before BOOT moves and switch_root" '[ "$CALL" -lt "$(line_of "^mount --move /boot")" ] && [ "$CALL" -lt "$(line_of "exec switch_root")" ]'

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
