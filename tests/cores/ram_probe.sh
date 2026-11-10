#!/bin/sh
# Diagnóstico: READ_CORE_RAM com o jogo de NES de teste (o byte $0000 deve mudar).
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo retroarch libretro-fceumm >/dev/null
printf 'video_driver = "null"\naudio_driver = "null"\ninput_driver = "null"\nmenu_driver = "null"\nnetwork_cmd_enable = "true"\n' > /tmp/null.cfg
retroarch --appendconfig /tmp/null.cfg -L /usr/lib/libretro/fceumm_libretro.so "/roms/roms/nes/Test NES.nes" >/dev/null 2>&1 &
sleep 3
for i in 1 2 3; do printf 'READ_CORE_RAM 0 1' | nc -u -w1 127.0.0.1 55355; echo; sleep 0.3; done
printf PAUSE_TOGGLE | nc -u -w1 127.0.0.1 55355
sleep 0.5
for i in 1 2; do printf 'READ_CORE_RAM 0 1' | nc -u -w1 127.0.0.1 55355; echo; sleep 0.3; done
kill %1
