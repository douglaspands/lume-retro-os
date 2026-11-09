#!/bin/sh
# Mostra o log completo de um core com uma ROM (diagnóstico): one_log.sh <core.so> <rom>
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo retroarch ${PKG:-libretro-fceumm} >/dev/null
printf 'video_driver = "null"\naudio_driver = "null"\ninput_driver = "null"\nmenu_driver = "null"\n' > /tmp/null.cfg
timeout 60 retroarch --appendconfig /tmp/null.cfg -L "/usr/lib/libretro/$1" --max-frames=600 --verbose "$2" 2>&1 \
	| grep -vE "Environ|Playlist|Config\]|Video\]|Audio\]|Input\]"
