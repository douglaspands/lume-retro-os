#!/bin/sh
# Tarefa 6.2: r36os-playlists com fixtures. Roda em busybox + jq (container do builder).
set -u
cd "$(dirname "$0")/../.."
GEN="busybox sh rootfs/overlay/usr/bin/r36os-playlists -c rootfs/overlay/usr/share/r36os/systems.json -i /nao-existe"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

R=$W/roms
mkdir -p "$R/nes/sub" "$R/snes" "$R/gba" "$R/psx" "$R/arcade" \
	"$R/segacd" "$R/sega32x" "$R/cps1" "$R/cps2" "$R/neogeo"
: > "$R/nes/Zelda Aventura.nes"
: > "$R/nes/sub/Outro Jogo.NES"
: > "$R/nes/leia.txt"
: > "$R/nes/._Zelda Aventura.nes"
: > "$R/snes/capa.png"
: > "$R/gba/Corrida.gba"
: > "$R/arcade/jogo.zip"
: > "$R/segacd/Disco.cue"
: > "$R/segacd/Disco.bin"
: > "$R/sega32x/Jogo.32x"
: > "$R/cps1/ghouls.zip"
: > "$R/cps2/sf2.zip"
: > "$R/neogeo/neogeo.zip"
: > "$R/neogeo/mslug.zip"

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
check "segacd x86_64: genesis_plus_gx" '[ "$(jq -r ".items[0].core_path" "$O/Sega CD.lpl")" = /usr/lib/libretro/genesis_plus_gx_libretro.so ]'
check "segacd: só .cue entra (o .bin da imagem é ignorado)" '[ "$(jq ".items | length" "$O/Sega CD.lpl")" = 1 ]'
check "sega32x: picodrive" '[ "$(jq -r ".items[0].core_path" "$O/Sega 32X.lpl")" = /usr/lib/libretro/picodrive_libretro.so ]'
check "cps1: fbalpha2012_cps1" '[ "$(jq -r ".items[0].core_path" "$O/CPS-1.lpl")" = /usr/lib/libretro/fbalpha2012_cps1_libretro.so ]'
check "cps2: fbalpha2012_cps2" '[ "$(jq -r ".items[0].core_path" "$O/CPS-2.lpl")" = /usr/lib/libretro/fbalpha2012_cps2_libretro.so ]'
check "neogeo: fbalpha2012_neogeo" '[ "$(jq -r ".items[0].core_path" "$O/Neo Geo.lpl")" = /usr/lib/libretro/fbalpha2012_neogeo_libretro.so ]'
check "neogeo: a BIOS neogeo.zip da pasta não é jogo" '[ "$(jq ".items | length" "$O/Neo Geo.lpl")" = 1 ] && [ "$(jq -r ".items[0].label" "$O/Neo Geo.lpl")" = mslug ]'

### armv7: core padrão por arquitetura
O7=$W/out-arm
$GEN -r "$R" -o "$O7" -a armv7l >/dev/null
check "gba armv7: gpsp" '[ "$(jq -r ".items[0].core_path" "$O7/Game Boy Advance.lpl")" = /usr/lib/libretro/gpsp_libretro.so ]'
check "arcade armv7: fbneo, as on the other consoles" '[ "$(jq -r ".items[0].core_path" "$O7/Arcade.lpl")" = /usr/lib/libretro/fbneo_libretro.so ]'
check "segacd armv7: picodrive (GA36)" '[ "$(jq -r ".items[0].core_path" "$O7/Sega CD.lpl")" = /usr/lib/libretro/picodrive_libretro.so ]'
check "cps2 armv7: o mesmo core de arcade, sem troca" '[ "$(jq -r ".items[0].core_path" "$O7/CPS-2.lpl")" = /usr/lib/libretro/fbalpha2012_cps2_libretro.so ]'
check "neogeo armv7: o mesmo core de arcade, sem troca" '[ "$(jq -r ".items[0].core_path" "$O7/Neo Geo.lpl")" = /usr/lib/libretro/fbalpha2012_neogeo_libretro.so ]'
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
