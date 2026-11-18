#!/bin/sh
# usb-device-access task 7.3: a pendrive on the OTG port (host role) is mounted under
# /storage/usb/ and unmounted when it leaves. Runs in busybox (builder container) with fake
# mount and umount that keep their own mounts table, and the udev variables (ID_FS_TYPE,
# ID_FS_LABEL) set by hand.
set -u
cd "$(dirname "$0")/../.."
STORAGE_SH="busybox sh aports/lume-usb/files/usr/libexec/lume/usb-storage"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

mkdir -p "$W/bin" "$W/usb" "$W/dev"
: > "$W/mounts"
LOG="$W/cmd.log"
cat > "$W/bin/mount" <<EOF
#!/bin/sh
echo "mount \$*" >> "$LOG"
for a; do dev=\$dir; dir=\$a; done
[ -f "$W/fail-mount" ] && exit 32
echo "\$dev \$dir fake rw 0 0" >> "$W/mounts"
EOF
cat > "$W/bin/umount" <<EOF
#!/bin/sh
echo "umount \$*" >> "$LOG"
for a; do dir=\$a; done
grep -v " \$dir " "$W/mounts" > "$W/mounts.new"; mv "$W/mounts.new" "$W/mounts"
EOF
chmod +x "$W/bin/"*
export USB_MOUNT_ROOT="$W/usb" MOUNTS_FILE="$W/mounts" MOUNT="$W/bin/mount" UMOUNT="$W/bin/umount" \
	DEV_DIR="$W/dev" GAME_UID=1000 GAME_GID=1000 USB_LIBDIR="$PWD/aports/lume-core/files/usr/libexec/lume" \
	LOGS_RAM="$W/logs" KMSG="$W/kmsg"
EV="$W/logs/events.pending"

### a FAT pendrive with a label
ID_FS_TYPE=vfat ID_FS_LABEL="MY GAMES" $STORAGE_SH add sda1 >/dev/null
check "vfat: mounted under /storage/usb with the label as folder" 'grep -qx "$W/dev/sda1 $W/usb/MY_GAMES fake rw 0 0" $W/mounts'
check "vfat: read-write, the frontend user, flush" 'grep -qx "mount -t vfat -o rw,noatime,uid=1000,gid=1000,umask=022,flush $W/dev/sda1 $W/usb/MY_GAMES" $LOG'
check "vfat: mount event" 'grep -q " usb OK storage: mounted sda1 (vfat, \"MY GAMES\") on $W/usb/MY_GAMES$" $EV'
ID_FS_TYPE=vfat ID_FS_LABEL="MY GAMES" $STORAGE_SH add sda1 >/dev/null
check "vfat: a second add of the same device does nothing" '[ "$(grep -c "^mount " $LOG)" = 1 ]'

### a second pendrive with the same label, exfat without a label, ext4
mkdir -p "$W/usb/MY_GAMES/x"   # the first one has files
ID_FS_TYPE=vfat ID_FS_LABEL="MY GAMES" $STORAGE_SH add sdb1 >/dev/null
check "same label: the second gets the device name too" 'grep -q "^$W/dev/sdb1 $W/usb/MY_GAMES-sdb1 " $W/mounts'
ID_FS_TYPE=exfat ID_FS_LABEL= $STORAGE_SH add sdc1 >/dev/null
check "exfat without a label: folder named after the device" 'grep -qx "mount -t exfat -o rw,noatime,uid=1000,gid=1000,umask=022 $W/dev/sdc1 $W/usb/sdc1" $LOG'
ID_FS_TYPE=ext4 ID_FS_LABEL="../../boot" $STORAGE_SH add sdd1 >/dev/null
check "ext4: plain rw, and a label cannot leave /storage/usb" 'grep -qx "mount -t ext4 -o rw,noatime $W/dev/sdd1 $W/usb/boot" $LOG'

### unsupported or no filesystem
: > "$LOG"
ID_FS_TYPE=ntfs ID_FS_LABEL=WIN $STORAGE_SH add sde1 >/dev/null
check "ntfs: not mounted, a failure event says why" '! grep -q "^mount " $LOG && grep -q " usb FAIL storage: sde1 has ntfs, not mounted (vfat, exfat or ext4 only)$" $EV'
ID_FS_TYPE= $STORAGE_SH add sdf >/dev/null
check "a disk with partitions (no filesystem): nothing" '! grep -q "^mount " $LOG && ! grep -q " sdf" $EV'

### a mount that fails leaves no folder behind
: > "$W/fail-mount"
ID_FS_TYPE=vfat ID_FS_LABEL=BAD $STORAGE_SH add sdg1 >/dev/null
rm -f "$W/fail-mount"
check "failed mount: failure event and no empty folder" 'grep -q " usb FAIL storage: could not mount sdg1 (vfat)$" $EV && [ ! -d $W/usb/BAD ]'

### removal
$STORAGE_SH remove sdc1 >/dev/null
check "remove: lazy unmount, folder removed, event" 'grep -qx "umount -l $W/usb/sdc1" $LOG && ! grep -q "sdc1" $W/mounts && [ ! -d $W/usb/sdc1 ] && grep -q " usb OK storage: removed sdc1 from $W/usb/sdc1$" $EV'
: > "$LOG"
$STORAGE_SH remove sdz1 >/dev/null
check "remove of something never mounted: nothing" '[ ! -s $LOG ]'

### the udev rule: only USB disks, mounted by filesystem, removed by name
R=aports/lume-usb/files/etc/udev/rules.d/90-lume-usb-storage.rules
check "udev rule: add only for filesystems on the USB bus" 'grep -q "^ACTION==\"add\", SUBSYSTEM==\"block\", ENV{ID_BUS}==\"usb\", ENV{ID_FS_USAGE}==\"filesystem\", RUN+=\"/usr/libexec/lume/usb-storage add %k\"$" $R'
check "udev rule: remove on the USB bus" 'grep -q "^ACTION==\"remove\", SUBSYSTEM==\"block\", ENV{ID_BUS}==\"usb\", RUN+=\"/usr/libexec/lume/usb-storage remove %k\"$" $R'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
