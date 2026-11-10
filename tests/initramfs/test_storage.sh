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

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
