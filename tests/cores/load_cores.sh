#!/bin/sh
# Task 2.2: every local core loads in RetroArch (dlopen + libretro API), with no content.
# Runs in an alpine:3.24 container with /repo (out/repo) and /keys mounted.
set -u
cp /keys/r36os.rsa.pub /etc/apk/keys/
CORES="snes9x2005-plus genesis-plus-gx picodrive fbneo pcsx-rearmed"
PKGS="retroarch"
for c in $CORES; do PKGS="$PKGS libretro-$c"; done
apk add -q -X /repo $PKGS >/dev/null || exit 1

cat > /tmp/null.cfg <<'EOF'
video_driver = "null"
audio_driver = "null"
input_driver = "null"
menu_driver = "null"
EOF
FAILS=0
for so in /usr/lib/libretro/*_libretro.so; do
	name=$(basename "$so" _libretro.so)
	log=$(timeout 20 retroarch --appendconfig /tmp/null.cfg -L "$so" --max-frames=1 --verbose 2>&1)
	# Carregou: dlopen ok e o core respondeu (roda 1 quadro ou pede conteúdo).
	if echo "$log" | grep -q "Loading dynamic libretro core" \
		&& ! echo "$log" | grep -q "Failed to open libretro core"; then
		echo "PASS $name"
	else
		echo "FAIL $name"; echo "$log" | tail -n 5; FAILS=$((FAILS + 1))
	fi
done
for c in $CORES; do
	f=/usr/lib/libretro/$(echo "$c" | tr - _)_libretro.so
	[ -f "$f" ] || { echo "FAIL ausente $f"; FAILS=$((FAILS + 1)); }
done
echo "falhas: $FAILS"
[ $FAILS -eq 0 ]
