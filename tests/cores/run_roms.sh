#!/bin/sh
# Roda cada ROM de teste (/roms/<sistema>/*) com cada core do catálogo para o
# sistema, por 600 quadros, com vídeo/áudio/entrada null. Mostra a linha de log
# que confirma o conteúdo carregado.
set -u
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo retroarch jq libretro-fceumm libretro-nestopia libretro-gambatte \
	libretro-mgba libretro-gpsp libretro-snes9x2010 libretro-snes9x libretro-genesis-plus-gx \
	libretro-picodrive libretro-fbneo libretro-mame2003-plus libretro-pcsx-rearmed >/dev/null || exit 1
cat > /tmp/null.cfg <<'EOF'
video_driver = "null"
audio_driver = "null"
input_driver = "null"
menu_driver = "null"
EOF
FAILS=0
jq -r '.cores as $c | .systems[] | . as $s
	| ([.core] + [.core_by_arch[]] + .alt_cores | unique[]) as $core
	| [$s.id, $core, $c[$core].file] | @tsv' /catalog/systems.json |
while IFS="$(printf '\t')" read -r sys core file; do
	for rom in /roms/roms/"$sys"/*; do
		[ -f "$rom" ] || continue
		log=$(timeout 60 retroarch --appendconfig /tmp/null.cfg -L "/usr/lib/libretro/$file" \
			--max-frames=600 --verbose "$rom" 2>&1)
		# RetroArch 1.22 não imprime "core loaded": o equivalente é a geometria do core
		# (retro_load_game ok) e o tempo de execução do conteúdo ao descarregar.
		if echo "$log" | grep -q "\[Core\] Geometry:" \
			&& echo "$log" | grep -q "Content ran for a total of"; then
			echo "PASS $sys $core"
		else
			echo "FAIL $sys $core"; echo "$log" | grep -iE "error|content|core" | tail -n 6
			FAILS=$((FAILS + 1))
		fi
	done
done
