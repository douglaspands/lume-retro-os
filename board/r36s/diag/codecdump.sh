#!/bin/bash
# R36S speaker loudness: RK817 codec register dump while a tone plays (task 4.6).
#
# On the factory ArkOS card the speaker is much louder than on r36os with the same
# volume settings. Run this from the ArkOS Ports menu (/roms/ports): it plays a 440 Hz
# sine for a few seconds and, while it plays, saves next to this script, in
# ../regdump/codec-<kernel>-<date>/:
#   - the RK817 registers through every regmap in debugfs (codec and PMIC);
#   - the RK817 registers 0x00-0xff read over I2C (bus 0, address 0x20), when
#     /dev/i2c-0 exists, as a second source that does not depend on the driver;
#   - the GPIO state (gpio3 20 is the speaker enable), the mixer, the PCM state and
#     the clock tree.
# Compare with the same registers read on r36os (the kernel no longer logs them; read them
# from the debugfs regmap while a tone plays).
#
# Only reads: the I2C reads set the register address and read one byte; nothing is
# ever written to a register.

set -u
if [ "$(id -u)" -ne 0 ]; then
	exec sudo -n "$0" "$@"
fi

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../regdump/codec-$(uname -r)-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "r36s codecdump: writing to $OUT"

mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug 2>/dev/null

# the tone keeps the speaker path powered while the registers are read
speaker-test -t sine -f 440 -c 2 -r 48000 >"$OUT/speaker-test.txt" 2>&1 &
TONE=$!
sleep 2

for d in /sys/kernel/debug/regmap/*; do
	[ -r "$d/registers" ] || continue
	cp "$d/registers" "$OUT/regmap-$(basename "$d").txt" 2>/dev/null
	cat "$d/name" >"$OUT/regmap-$(basename "$d").name" 2>/dev/null
done

if [ -e /dev/i2c-0 ] && command -v python3 >/dev/null 2>&1; then
	python3 - "$OUT/i2c-0-0x20.txt" <<'PY' 2>"$OUT/i2c.err"
import fcntl, os, sys

I2C_SLAVE_FORCE = 0x0706
fd = os.open("/dev/i2c-0", os.O_RDWR)
fcntl.ioctl(fd, I2C_SLAVE_FORCE, 0x20)
with open(sys.argv[1], "w") as f:
    f.write("# RK817 over I2C bus 0 address 0x20, while the tone plays\n")
    for reg in range(0x100):
        try:
            os.write(fd, bytes([reg]))
            val = os.read(fd, 1)[0]
            f.write(f"{reg:#04x} {val:#04x}\n")
        except OSError as e:
            f.write(f"{reg:#04x} error {e.errno}\n")
PY
fi

cat /sys/kernel/debug/gpio >"$OUT/gpio.txt" 2>/dev/null
amixer contents >"$OUT/amixer.txt" 2>&1
for f in /proc/asound/card*/pcm*p/sub*/status /proc/asound/card*/pcm*p/sub*/hw_params; do
	[ -r "$f" ] && { echo "== $f"; cat "$f"; }
done >"$OUT/pcm.txt" 2>/dev/null
cp /sys/kernel/debug/clk/clk_summary "$OUT/clk_summary.txt" 2>/dev/null
dmesg >"$OUT/dmesg.txt" 2>&1
uname -a >"$OUT/uname.txt"

kill "$TONE" 2>/dev/null
wait "$TONE" 2>/dev/null
sync
echo "r36s codecdump: done ($(ls "$OUT" | wc -l) files)"
sleep 3
exit 0
