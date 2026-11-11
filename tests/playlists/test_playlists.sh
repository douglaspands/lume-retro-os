#!/bin/sh
# Tarefa 6.2: r36os-playlists com fixtures. Roda em busybox + jq (container do builder).
set -u
cd "$(dirname "$0")/../.."
GEN="busybox sh rootfs/overlay/usr/bin/r36os-playlists -c rootfs/overlay/usr/share/r36os/systems.json -i /nao-existe"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

R=$W/roms
mkdir -p "$R/nes/sub" "$R/snes" "$R/gba" "$R/psx" "$R/arcade"
: > "$R/nes/Zelda Aventura.nes"
: > "$R/nes/sub/Outro Jogo.NES"
: > "$R/nes/leia.txt"
: > "$R/nes/._Zelda Aventura.nes"
: > "$R/snes/capa.png"
: > "$R/gba/Corrida.gba"
: > "$R/arcade/jogo.zip"

### x86_64
O=$W/out-x86
$GEN -r "$R" -o "$O" -a x86_64 >/dev/null
check "nes: lista criada" '[ -f "$O/NES.lpl" ]'
check "nes: 2 jogos (extensão maiúscula aceita, .txt e ._ ignorados)" '[ "$(jq ".items | length" "$O/NES.lpl")" = 2 ]'
check "nes: rótulo sem extensão" 'jq -e ".items[] | select(.label == \"Zelda Aventura\")" "$O/NES.lpl" >/dev/null'
check "nes: caminho completo" 'jq -e ".items[] | select(.path == \"$R/nes/Zelda Aventura.nes\")" "$O/NES.lpl" >/dev/null'
check "nes: core fixo fceumm" '[ "$(jq -r ".items[0].core_path" "$O/NES.lpl")" = /usr/lib/libretro/fceumm_libretro.so ]'
check "nes: ordem alfabética" '[ "$(jq -r ".items[0].label" "$O/NES.lpl")" = "Outro Jogo" ]'
check "snes: extensão fora do catálogo ignorada, sem lista" '[ ! -e "$O/Super Nintendo.lpl" ]'
check "psx: sistema vazio sem lista" '[ ! -e "$O/PlayStation.lpl" ]'
check "gba x86_64: gpsp" '[ "$(jq -r ".default_core_path" "$O/Game Boy Advance.lpl")" = /usr/lib/libretro/gpsp_libretro.so ]'
check "arcade x86_64: fbneo" '[ "$(jq -r ".items[0].core_path" "$O/Arcade.lpl")" = /usr/lib/libretro/fbneo_libretro.so ]'

### armv7: core padrão por arquitetura
O7=$W/out-arm
$GEN -r "$R" -o "$O7" -a armv7l >/dev/null
check "gba armv7: gpsp" '[ "$(jq -r ".items[0].core_path" "$O7/Game Boy Advance.lpl")" = /usr/lib/libretro/gpsp_libretro.so ]'
check "arcade armv7: mame2003_plus" '[ "$(jq -r ".items[0].core_path" "$O7/Arcade.lpl")" = /usr/lib/libretro/mame2003_plus_libretro.so ]'
check "nes armv7: fceumm (sem troca)" '[ "$(jq -r ".items[0].core_path" "$O7/NES.lpl")" = /usr/lib/libretro/fceumm_libretro.so ]'

### lista some quando o sistema esvazia; listas do RetroArch ficam
: > "$O/content_history.lpl"
rm "$R/gba/Corrida.gba"
$GEN -r "$R" -o "$O" -a x86_64 >/dev/null
check "gba vazio: lista antiga removida" '[ ! -e "$O/Game Boy Advance.lpl" ]'
check "histórico do RetroArch preservado" '[ -e "$O/content_history.lpl" ]'

rm -rf "$W"
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
