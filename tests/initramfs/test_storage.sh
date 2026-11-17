#!/bin/busybox sh
# Tests of the initramfs storage logic (tasks 4.1-4.3) on fake images, and of the root mount
# sequence (build-speed 4.5) with fake mount/umount.
# Runs in the builder container: busybox sh tests/initramfs/test_storage.sh
set -u
cd "$(dirname "$0")"
. ../../initramfs/lib/storage.sh
. ../../initramfs/lib/slots.sh
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
# the init (mount_root of slots.sh since build-speed 4.5) rescues with the console and the
# file in the message, with no fallback to another console
INIT=../../initramfs/init
SLOTS_SH=../../initramfs/lib/slots.sh
check "system: mount_root uses system_file" 'grep -q "system=\$(system_file \"\$board\")" "$SLOTS_SH"'
check "system: rescue names the file and the console" \
	'grep -q "rescue \"BOOT has no \$system, the system of the \$(console_label \"\$board\")" "$SLOTS_SH"'
check "system: never mounts /boot/SYSTEM directly" '! grep -q "/boot/SYSTEM " "$INIT" "$SLOTS_SH"'

### 9b. The .old of a push cut between its two renames (push-boot-swap D4)
check "boot_file: present" '[ "$(boot_file "$B" ga36/SYSTEM 2>"$W/bf1")" = ga36/SYSTEM ] && [ ! -s "$W/bf1" ]'
: > "$B/ga36/SYSTEM.old"
check "boot_file: present wins over .old" '[ "$(boot_file "$B" ga36/SYSTEM 2>/dev/null)" = ga36/SYSTEM ]'
rm "$B/ga36/SYSTEM"
check "boot_file: only .old" '[ "$(boot_file "$B" ga36/SYSTEM 2>"$W/bf2")" = ga36/SYSTEM.old ]'
check "boot_file: .old logged as ERROR" 'grep -qx "lume: ERROR: BOOT has no ga36/SYSTEM; using ga36/SYSTEM.old from the previous build" "$W/bf2"'
check "boot_file: neither fails" '! boot_file "$B" r36s/SYSTEM >/dev/null 2>"$W/bf3" && [ ! -s "$W/bf3" ]'
check "boot_file: no other console" '! boot_file "$B" r36s/SYSTEM >/dev/null 2>&1'
check "system: mount_root mounts the boot_file result" \
	'grep -q "file=\$(boot_file \"\$boot\" \"\$system\") || {" "$SLOTS_SH" && grep -q "ro,loop \"\$boot/\$file\" \"\$lower\"" "$SLOTS_SH"'
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
# the init: root and modules (mount_root) after select_dtb, before the moves and switch_root
line_of() { grep -n "$1" "$INIT" | head -n1 | cut -d: -f1; }
CALL=$(line_of '^mount_root "\$BOARD" /boot /slots /lower /rw /newroot /modules$')
check "init: calls mount_root" '[ -n "$CALL" ] && [ "$(grep -c "mount_root" "$INIT")" -eq 1 ]'
check "init: after select_dtb" '[ "$CALL" -gt "$(line_of "^select_dtb$")" ]'
check "init: before BOOT moves and switch_root" '[ "$CALL" -lt "$(line_of "^mount --move /boot")" ] && [ "$CALL" -lt "$(line_of "exec switch_root")" ]'
check "init: sources slots.sh after storage.sh" '[ "$(line_of "^\. /lib/slots.sh$")" -gt "$(line_of "^\. /lib/storage.sh$")" ]'
check "init: no root mount of its own" '! grep -q "^[[:space:]]*mount -t \(squashfs\|overlay\|tmpfs\)" "$INIT"'
sed -n '/^mount_root() {/,/^}/p' "$SLOTS_SH" > "$W/mount_root.sh"
OVL=$(grep -n "mount -t overlay" "$W/mount_root.sh" | head -n1 | cut -d: -f1)
MODS=$(grep -n "mount_modules" "$W/mount_root.sh" | head -n1 | cut -d: -f1)
check "mount_root: modules after the overlay" '[ -n "$OVL" ] && [ -n "$MODS" ] && [ "$MODS" -gt "$OVL" ]'

### 11. The root mount sequence (build-speed 4.5) with fake mount/umount/uname/rescue:
### slot set, SLOTS.old, the old SYSTEM, rescue; undo of a half-mounted set
RUNNING=6.18.62-r36os
FAIL_ON=""          # a mount whose arguments contain this text fails
MLOG=$W/root-mount.log
uname() { echo "$RUNNING"; }
mount() {
	echo "mount $*" >> "$MLOG"
	if [ -n "$FAIL_ON" ]; then
		case "$*" in *"$FAIL_ON"*) return 1 ;; esac
	fi
	case "$1" in
	--move) cp -a "$2/." "$3/" && rm -rf "$2"/* ;;
	-t) [ "$2" != squashfs ] || for d in $(cat "$5"); do mkdir -p "$6/$d"; done ;;
	esac
}
umount() { echo "umount $*" >> "$MLOG"; rm -rf "$1"/*; }
rescue() { echo "rescue $*" >> "$MLOG"; return 1; }
sha() { printf "%064d" 0 | tr 0 "$1"; }
s12() { echo "$1" | cut -c1-12; }
SB=$(sha b); SR=$(sha c); SC=$(sha f)
SL=$(sha d); SM=$(sha e)      # lume and modules of the previous set (SLOTS.old)
SL2=$(sha 9); SM2=$(sha 8)    # lume and modules of the new set (SLOTS)
# manifest of ga36 with lume $1, modules $2 and build id $3 (a reserved core line too)
manifest() {
	printf '%s\n' "lume-slots 1" "build $3" "console ga36" \
		"slot base slots/base-$(s12 $SB) $SB 1000 -" \
		"pkg base musl 1.2.5-r10" "pkg base busybox 1.37.0-r20" \
		"slot runtime slots/runtime-$(s12 $SR) $SR 2000 base=$SB" \
		"pkg runtime retroarch 1.22.2-r0" \
		"slot lume slots/lume-$(s12 $1) $1 3000 base=$SB,runtime=$SR" \
		"pkg lume lume-core 1.0-r3" \
		"slot modules slots/modules-$(s12 $2) $2 4000 -" \
		"slot core-snes9x slots/core-snes9x-$(s12 $SC) $SC 5000 base=$SB,runtime=$SR" \
		"end 5 4"
}
# BOOT at $W/sb: both slot sets, both manifests, and the old SYSTEM + modules of an old card
mkcard() {
	local f
	rm -rf "$W/sb"
	mkdir -p "$W/sb/ga36/slots"
	for f in base-$(s12 $SB) runtime-$(s12 $SR) lume-$(s12 $SL) lume-$(s12 $SL2) \
		core-snes9x-$(s12 $SC); do
		: > "$W/sb/ga36/slots/$f"
	done
	echo "$RUNNING" > "$W/sb/ga36/slots/modules-$(s12 $SM)"
	echo "$RUNNING" > "$W/sb/ga36/slots/modules-$(s12 $SM2)"
	manifest "$SL2" "$SM2" 20261117-010000 > "$W/sb/ga36/SLOTS"
	manifest "$SL" "$SM" 20261116-214233 > "$W/sb/ga36/SLOTS.old"
	: > "$W/sb/ga36/SYSTEM"
	echo "$RUNNING" > "$W/sb/ga36/modules"
	: > "$W/sb/SYSTEM"
}
# mount_root of board $1 (default ga36) -> calls in $MLOG, log in $W/rlog, status in $RC
run_root() {
	rm -rf "$W/s" "$W/lower" "$W/rw" "$W/root" "$W/mod"
	mkdir -p "$W/lower" "$W/rw" "$W/root"
	: > "$MLOG"
	RC=0
	mount_root "${1:-ga36}" "$W/sb" "$W/s" "$W/lower" "$W/rw" "$W/root" "$W/mod" 2> "$W/rlog" || RC=$?
}
# expected calls of a whole slot set: lume $1, modules $2
set_calls() {
	printf '%s\n' \
		"mount -t squashfs -o ro,loop $W/sb/ga36/slots/base-$(s12 $SB) $W/s/base" \
		"mount -t squashfs -o ro,loop $W/sb/ga36/slots/runtime-$(s12 $SR) $W/s/runtime" \
		"mount -t squashfs -o ro,loop $W/sb/ga36/slots/lume-$(s12 $1) $W/s/lume" \
		"mount -t tmpfs -o size=32m,mode=0755 tmpfs $W/rw" \
		"mount -t overlay overlay -o lowerdir=$W/s/lume:$W/s/runtime:$W/s/base,upperdir=$W/rw/upper,workdir=$W/rw/work $W/root" \
		"mount -t squashfs -o ro,loop $W/sb/ga36/slots/modules-$(s12 $2) $W/mod" \
		"mount --move $W/mod $W/root/lib/modules"
}
# expected calls of the old card: the same commands as the init before build-speed 4.5, with
# /boot, /lower, /rw, /newroot and /modules in $W
system_calls() {
	printf '%s\n' \
		"mount -t squashfs -o ro,loop $W/sb/ga36/SYSTEM $W/lower" \
		"mount -t tmpfs -o size=32m,mode=0755 tmpfs $W/rw" \
		"mount -t overlay overlay -o lowerdir=$W/lower,upperdir=$W/rw/upper,workdir=$W/rw/work $W/root" \
		"mount -t squashfs -o ro,loop $W/sb/ga36/modules $W/mod" \
		"mount --move $W/mod $W/root/lib/modules"
}
same() { cmp -s "$1" "$2"; }

# good set: SLOTS mounted, cores ignored, every slot and its versions in the log
mkcard
run_root
set_calls "$SL2" "$SM2" > "$W/want"
check "set: mounts lume:runtime:base + RAM layer + modules slot" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "set: modules of the slot on /lib/modules" '[ -d "$W/root/lib/modules/$RUNNING" ]'
check "set: no core slot mounted" '! grep -q core- "$MLOG"'
printf '%s\n' \
	"lume: slots: ga36/SLOTS (build 20261117-010000)" \
	"lume: slot base: ga36/slots/base-$(s12 $SB) (packages: 2)" \
	"lume: slot base packages: musl-1.2.5-r10 busybox-1.37.0-r20" \
	"lume: slot runtime: ga36/slots/runtime-$(s12 $SR) (packages: 1)" \
	"lume: slot runtime packages: retroarch-1.22.2-r0" \
	"lume: slot lume: ga36/slots/lume-$(s12 $SL2) (packages: 1)" \
	"lume: slot lume packages: lume-core-1.0-r3" \
	"lume: slot modules: ga36/slots/modules-$(s12 $SM2) (packages: 0)" \
	"lume: root: ga36/SLOTS (lume, runtime, base; read-only) + 32 MiB RAM layer" \
	"lume: modules: ga36/slots/modules-$(s12 $SM2) ($RUNNING)" > "$W/want"
check "set: boot log lists each slot and its versions" 'same "$W/rlog" "$W/want"'

# SLOTS cites a missing file: SLOTS.old picked before any mount
mkcard
rm "$W/sb/ga36/slots/lume-$(s12 $SL2)"
run_root
set_calls "$SL" "$SM" > "$W/want"
check "missing file: SLOTS.old mounted" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "missing file: ERROR then the old set in the log" \
	'grep -qx "lume: ERROR: ga36/SLOTS cites a missing file ga36/slots/lume-$(s12 $SL2); using ga36/SLOTS.old from the previous build" "$W/rlog" && grep -qx "lume: slots: ga36/SLOTS.old (build 20261116-214233)" "$W/rlog"'

# SLOTS missing (push cut between its renames): SLOTS.old
mkcard
rm "$W/sb/ga36/SLOTS"
run_root
check "SLOTS missing: SLOTS.old mounted" '[ $RC -eq 0 ] && grep -qx "lume: root: ga36/SLOTS.old (lume, runtime, base; read-only) + 32 MiB RAM layer" "$W/rlog"'

# SLOTS and SLOTS.old both cite missing files: the old SYSTEM, as on an old card
mkcard
rm "$W/sb/ga36/slots/lume-$(s12 $SL2)" "$W/sb/ga36/slots/lume-$(s12 $SL)"
run_root
system_calls > "$W/want"
check "both bad: the old SYSTEM mounted" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "both bad: ERROR names both, then the SYSTEM" \
	'grep -q "^lume: ERROR: ga36/SLOTS cites a missing file .* and ga36/SLOTS.old cites a missing file .*; no slot set to mount$" "$W/rlog" && grep -qx "lume: ERROR: no slot set of ga36 to mount; trying the old ga36/SYSTEM" "$W/rlog" && grep -qx "lume: root: ga36/SYSTEM (read-only) + 32 MiB RAM layer" "$W/rlog"'

# a slot of SLOTS fails to mount (squashfs error, no loop): the partial set is undone, newest
# first, then SLOTS.old
mkcard
FAIL_ON=lume-$(s12 $SL2)
run_root
FAIL_ON=""
{
	set_calls "$SL2" "$SM2" | head -n 3
	printf '%s\n' "umount $W/s/runtime" "umount $W/s/base"
	set_calls "$SL" "$SM"
} > "$W/want"
check "slot fails: undone, then SLOTS.old" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "slot fails: ERROR lines" \
	'grep -qx "lume: ERROR: failed to mount slot lume (ga36/slots/lume-$(s12 $SL2)) of ga36/SLOTS" "$W/rlog" && grep -qx "lume: ERROR: ga36/SLOTS could not be mounted; using ga36/SLOTS.old from the previous build" "$W/rlog"'

# the modules slot of SLOTS fails: overlay, RAM layer and slots undone, then SLOTS.old
mkcard
FAIL_ON=modules-$(s12 $SM2)
run_root
FAIL_ON=""
{
	set_calls "$SL2" "$SM2" | head -n 6
	printf '%s\n' "umount $W/root" "umount $W/rw" "umount $W/s/lume" "umount $W/s/runtime" "umount $W/s/base"
	set_calls "$SL" "$SM"
} > "$W/want"
check "modules slot fails: whole set undone, then SLOTS.old" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'

# the overlay of both sets fails: both undone, then the old SYSTEM
mkcard
FAIL_ON="lowerdir=$W/s/"
run_root
FAIL_ON=""
{
	set_calls "$SL2" "$SM2" | head -n 5
	printf '%s\n' "umount $W/rw" "umount $W/s/lume" "umount $W/s/runtime" "umount $W/s/base"
	set_calls "$SL" "$SM" | head -n 5
	printf '%s\n' "umount $W/rw" "umount $W/s/lume" "umount $W/s/runtime" "umount $W/s/base"
	system_calls
} > "$W/want"
check "overlay fails twice: both undone, then the old SYSTEM" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "overlay fails twice: ERROR lines" \
	'[ "$(grep -c "^lume: ERROR: failed to mount the overlay of ga36/SLOTS" "$W/rlog")" -eq 2 ] && grep -qx "lume: ERROR: ga36/SLOTS.old could not be mounted either; trying the old ga36/SYSTEM" "$W/rlog"'

# SLOTS.old picked (SLOTS missing) and its slot fails: straight to the old SYSTEM
mkcard
rm "$W/sb/ga36/SLOTS"
FAIL_ON=runtime-
run_root
FAIL_ON=""
{
	set_calls "$SL" "$SM" | head -n 2
	echo "umount $W/s/base"
	system_calls
} > "$W/want"
check "SLOTS.old fails: the old SYSTEM" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
check "SLOTS.old fails: ERROR line" 'grep -qx "lume: ERROR: ga36/SLOTS.old could not be mounted; trying the old ga36/SYSTEM" "$W/rlog"'

# SLOTS fails to mount and SLOTS.old is unusable: the old SYSTEM
mkcard
manifest "$SL" "$SM" 20261116-214233 | head -n 5 > "$W/sb/ga36/SLOTS.old"
FAIL_ON=base-
run_root
FAIL_ON=""
check "SLOTS fails, SLOTS.old truncated: the old SYSTEM" \
	'[ $RC -eq 0 ] && grep -qx "lume: ERROR: ga36/SLOTS could not be mounted and ga36/SLOTS.old is truncated (no end line); trying the old ga36/SYSTEM" "$W/rlog" && grep -qx "lume: root: ga36/SYSTEM (read-only) + 32 MiB RAM layer" "$W/rlog"'

# no set mounts and no SYSTEM: the existing failure path (rescue), nothing mounted after
mkcard
rm "$W/sb/ga36/SYSTEM"
FAIL_ON=base-
run_root
FAIL_ON=""
check "nothing left: rescue with the old message" \
	'[ $RC -ne 0 ] && [ "$(tail -n 1 "$MLOG")" = "rescue BOOT has no ga36/SYSTEM, the system of the GA36; write the card again with the console image" ]'

# old card: SYSTEM only. The same calls and log lines as the init before build-speed 4.5
mkcard
rm "$W/sb/ga36/SLOTS" "$W/sb/ga36/SLOTS.old"
run_root
system_calls > "$W/want"
check "old card: same calls as before the slots" '[ $RC -eq 0 ] && same "$MLOG" "$W/want"'
printf '%s\n' "lume: root: ga36/SYSTEM (read-only) + 32 MiB RAM layer" \
	"lume: modules: ga36/modules ($RUNNING)" > "$W/want"
check "old card: same log, no slot line" 'same "$W/rlog" "$W/want"'
# old card whose SYSTEM is only SYSTEM.old: as before
mv "$W/sb/ga36/SYSTEM" "$W/sb/ga36/SYSTEM.old"
run_root
check "old card: SYSTEM.old as before" '[ $RC -eq 0 ] && grep -qx "mount -t squashfs -o ro,loop $W/sb/ga36/SYSTEM.old $W/lower" "$MLOG" && grep -qx "lume: ERROR: BOOT has no ga36/SYSTEM; using ga36/SYSTEM.old from the previous build" "$W/rlog"'
# old card whose SYSTEM fails to mount: rescue, as before
mv "$W/sb/ga36/SYSTEM.old" "$W/sb/ga36/SYSTEM"
FAIL_ON=ga36/SYSTEM
run_root
FAIL_ON=""
check "old card: SYSTEM fails -> rescue" '[ $RC -ne 0 ] && [ "$(tail -n 1 "$MLOG")" = "rescue failed to mount ga36/SYSTEM" ]'

# vm: always BOOT/SYSTEM, no modules, no slots (even with a vm/SLOTS)
mkcard
mkdir -p "$W/sb/vm"
cp "$W/sb/ga36/SLOTS" "$W/sb/vm/SLOTS"
run_root vm
printf '%s\n' "mount -t squashfs -o ro,loop $W/sb/SYSTEM $W/lower" \
	"mount -t tmpfs -o size=32m,mode=0755 tmpfs $W/rw" \
	"mount -t overlay overlay -o lowerdir=$W/lower,upperdir=$W/rw/upper,workdir=$W/rw/work $W/root" > "$W/want"
check "vm: BOOT/SYSTEM only" '[ $RC -eq 0 ] && same "$MLOG" "$W/want" && [ "$(cat "$W/rlog")" = "lume: root: SYSTEM (read-only) + 32 MiB RAM layer" ]'

# long package lists are split in lines that fit a kernel log record
mkdir -p "$W/pk"
{
	echo "lume-slots 1"
	i=0
	while [ $i -lt 60 ]; do echo "pkg base package-number-$i 1.0.$i-r0"; i=$((i + 1)); done
} > "$W/pk/M"
check "packages: wrapped under 420 characters" \
	'[ "$(_slots_pkg_lines "$W/pk" M base | wc -l)" -gt 1 ] && [ "$(_slots_pkg_lines "$W/pk" M base | awk "length > 420" | wc -l)" -eq 0 ] && [ "$(_slots_pkg_lines "$W/pk" M base | tr " " "\n" | grep -c .)" -eq 60 ]'
unset -f mount umount uname rescue

rm -rf "$W"
echo "failures: $FAILS"
[ $FAILS -eq 0 ]
