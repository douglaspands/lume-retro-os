#!/bin/sh
# Diagnóstico: backtrace de um core que cai. gdb_core.sh <core.so> <rom>
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo retroarch gdb musl-dbg ${PKG:-libretro-fceumm} >/dev/null
printf 'video_driver = "null"\naudio_driver = "null"\ninput_driver = "null"\nmenu_driver = "null"\n' > /tmp/null.cfg
gdb -q -batch -ex run -ex bt -ex "info threads" --args \
	retroarch --appendconfig /tmp/null.cfg -L "/usr/lib/libretro/$1" --max-frames=600 "$2" 2>&1 | tail -n 30
