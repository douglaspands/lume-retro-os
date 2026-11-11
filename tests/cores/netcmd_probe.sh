#!/bin/sh
# Diagnóstico: comandos de rede do RetroArch (GET_STATUS, SAVE_STATE) e carga de state.
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo retroarch libretro-fceumm >/dev/null
cat > /tmp/null.cfg <<'EOF'
video_driver = "null"
audio_driver = "null"
input_driver = "null"
menu_driver = "null"
network_cmd_enable = "true"
network_cmd_port = "55355"
savestate_directory = "/tmp/states"
EOF
ROM="/roms/roms/nes/Test NES.nes"
retroarch --appendconfig /tmp/null.cfg -L /usr/lib/libretro/fceumm_libretro.so --verbose "$ROM" > /tmp/ra1.log 2>&1 &
pid=$!
sleep 3
echo "status: $(printf GET_STATUS | nc -u -w1 127.0.0.1 55355)"
printf SAVE_STATE | nc -u -w1 127.0.0.1 55355
sleep 2
find /tmp/states -type f
kill $pid
wait $pid
retroarch --appendconfig /tmp/null.cfg -L /usr/lib/libretro/fceumm_libretro.so --verbose \
	--entryslot=0 --max-frames=120 "$ROM" 2>&1 | grep -iE "state" | grep -v Override
