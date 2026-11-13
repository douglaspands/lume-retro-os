#!/bin/bash
# R36S display path register dump (task 4.6).
#
# Reads, without writing anything to the hardware, the registers of the display path
# of the PX30/RK3326 (DSI host, Innosilicon D-PHY, VOP, GRF and CRU) plus the kernel
# state around it (dmesg, clock tree, DRM state, live device tree), and saves them
# next to this script, in ../regdump/<kernel>-<date>/. Meant to run on the factory
# ArkOS card (Ports menu, /roms/ports) with the screen working, and on r36os, so the
# two dumps can be compared register by register.
#
# Only reads: /dev/mem is mapped read/write because ctypes needs a writable buffer
# to make 32-bit loads, but no value is ever stored.

set -u

# MEM: memory device to read (default /dev/mem; a sparse file for the unit test)
MEM=${MEM:-/dev/mem}
if [ "$(id -u)" -ne 0 ] && [ "$MEM" = /dev/mem ]; then
	exec sudo -n "$0" "$@"
fi

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../regdump/$(uname -r)-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
echo "r36s regdump: writing to $OUT"

# name base size (bytes)
REGIONS="
dsi    0xff450000 0x200
dphy   0xff2e0000 0x800
vop    0xff460000 0x300
grf    0xff140000 0x500
cru    0xff2b0000 0x300
pmucru 0xff2bc000 0x100
"

dump_python() {
	python3 - "$OUT" <<'PY'
import ctypes, mmap, os, sys

out = sys.argv[1]
regions = [l.split() for l in os.environ["REGIONS"].strip().splitlines()]
fd = os.open(os.environ["MEM"], os.O_RDWR | os.O_SYNC)
for name, base, size in regions:
    base, size = int(base, 16), int(size, 16)
    span = (size + mmap.PAGESIZE - 1) // mmap.PAGESIZE * mmap.PAGESIZE
    try:
        mm = mmap.mmap(fd, span, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE,
                       offset=base)
        words = [ctypes.c_uint32.from_buffer(mm, off).value for off in range(0, size, 4)]
    except Exception as e:  # one region failing must not lose the others
        print(f"{name}: {e}", file=sys.stderr)
        continue
    with open(os.path.join(out, f"{name}.txt"), "w") as f:
        f.write(f"# {name} base {base:#010x} size {size:#x}\n")
        for i, val in enumerate(words):
            f.write(f"{base + 4 * i:#010x} {4 * i:#06x} {val:#010x}\n")
    print(f"{name}: {size // 4} registers")
PY
}

dump_devmem() {
	echo "$REGIONS" | while read -r name base size; do
		[ -n "$name" ] || continue
		{
			echo "# $name base $base size $size"
			off=0
			while [ "$off" -lt $((size)) ]; do
				addr=$((base + off))
				printf '%#010x %#06x %s\n' "$addr" "$off" "$($DEVMEM "$addr" 32)"
				off=$((off + 4))
			done
		} >"$OUT/$name.txt"
		echo "$name: done"
	done
}

export REGIONS MEM
if command -v python3 >/dev/null 2>&1; then
	dump_python 2>"$OUT/regs.err" || echo "python dump failed, see regs.err"
elif command -v devmem >/dev/null 2>&1; then
	DEVMEM=devmem dump_devmem 2>"$OUT/regs.err"
elif command -v busybox >/dev/null 2>&1; then
	DEVMEM="busybox devmem" dump_devmem 2>"$OUT/regs.err"
else
	echo "no python3 nor devmem: registers not read" | tee "$OUT/regs.err"
fi

# Kernel state around the display path
uname -a >"$OUT/uname.txt"
cat /proc/cmdline >"$OUT/cmdline.txt"
dmesg >"$OUT/dmesg.txt" 2>&1
mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug 2>/dev/null
cp /sys/kernel/debug/clk/clk_summary "$OUT/clk_summary.txt" 2>/dev/null
for f in /sys/kernel/debug/dri/0/*; do
	[ -f "$f" ] && cp "$f" "$OUT/dri-$(basename "$f").txt" 2>/dev/null
done
for f in /sys/class/drm/*/modes /sys/class/drm/*/status; do
	[ -f "$f" ] && echo "$f: $(tr '\n' ' ' <"$f")"
done >"$OUT/drm-modes.txt" 2>/dev/null
cp /sys/firmware/fdt "$OUT/live.dtb" 2>/dev/null
cat /sys/class/backlight/*/brightness >"$OUT/backlight.txt" 2>/dev/null

sync
echo "r36s regdump: done ($(ls "$OUT" | wc -l) files)"
# leave the message on screen when launched from a menu
[ "$MEM" = /dev/mem ] && sleep 3
exit 0
