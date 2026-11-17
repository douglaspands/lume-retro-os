#!/bin/sh
# Rootfs configuration, run in a chroot inside the container of the target arch.
# Arguments: <serial tty> <baud> <board>
set -eu
SERIAL_TTY="$1"
SERIAL_BAUD="$2"
BOARD="$3"

# Frontend user: no password and no interactive login (locked account).
adduser -D -u 1000 -h /home/game -s /sbin/nologin game
for g in video input audio; do addgroup game "$g"; done
getent group seat >/dev/null && addgroup game seat

# root without a password: on the debug serial (securetty) and over ssh on the USB cable
# (dropbear -B on 10.55.0.1 only, usb-device-access D4); never on another interface.
passwd -d root >/dev/null
echo "$SERIAL_TTY" > /etc/securetty
# SSH over Wi-Fi (lume-launcher D18): "console" is root (uid 0) under another name, so the
# Wi-Fi server can take a password (the code shown on the screen) while root keeps none for
# the cable. Locked until r36os-ssh-wifi sets the code in /etc/shadow (the RAM layer).
echo "console:x:0:0:Lume console over Wi-Fi:/root:/bin/sh" >> /etc/passwd
echo "console:!::0:::::" >> /etc/shadow

# No getty on the virtual terminals: tty1 belongs to the frontend. Getty only on the serial.
sed -i -e '/^tty[0-9]*::/d' -e '/^#*ttyS[0-9]*::/d' /etc/inittab
echo "$SERIAL_TTY::respawn:/sbin/getty -L $SERIAL_BAUD $SERIAL_TTY vt100" >> /etc/inittab

# Verbose boot on the screen and on the serial: openrc goes through rc-tee.
mkdir -p /etc/r36os
echo "$SERIAL_TTY" > /etc/r36os/serial-tty
echo "$BOARD" > /etc/r36os/board
chmod 644 /usr/libexec/r36os/lib.sh
sed -i -e 's#:/sbin/openrc #:/usr/libexec/r36os/rc-tee #' /etc/inittab
# Boot log in ROMS/logs/boot/ (or on BOOT without ROMS), after the default runlevel
# (busybox init: wait before once).
echo "::once:/usr/libexec/r36os/bootlog" >> /etc/inittab

# OpenRC: boot log in /var/log/rc.log (used by the boot log).
sed -i -e 's/^#*rc_logger=.*/rc_logger="YES"/' /etc/rc.conf
# cgroup v2 only, mounted on /sys/fs/cgroup: the session hands /sys/fs/cgroup/lume/ to the
# game user and the launcher puts each game in its own cgroup (lume-launcher D9)
sed -i -e 's/^#*rc_cgroup_mode=.*/rc_cgroup_mode="unified"/' /etc/rc.conf
grep -qx 'rc_cgroup_mode="unified"' /etc/rc.conf || echo 'rc_cgroup_mode="unified"' >> /etc/rc.conf
# Services start in parallel (build-speed D20): the order comes only from the depend() of
# each service. The ones no game uses (NetworkManager, Bluetooth, RetroArch playlists,
# lume-index) are "after frontend", so the frontend does not wait for them; the hardware
# snapshot of hwinfo is taken by r36os-logd once the frontend is up.
sed -i -e 's/^#*rc_parallel=.*/rc_parallel="YES"/' /etc/rc.conf
grep -qx 'rc_parallel="YES"' /etc/rc.conf || echo 'rc_parallel="YES"' >> /etc/rc.conf

add() { rc-update add "$1" "$2" >/dev/null; }
# cgroups mounts the cgroup v2 of rc_cgroup_mode above: without it in a runlevel nothing mounts
# /sys/fs/cgroup and the games end by process group only (seen in test-vm on 2026-11-14).
# sysfs is listed too: its "after sysfs" only orders services of the same runlevel, and with
# sysfs pulled in later cgroups found no /sys/fs/cgroup, did nothing and still said started.
for s in sysfs devfs dmesg cgroups udev udev-trigger udev-settle; do add "$s" sysinit; done
for s in modules sysctl hostname bootmisc syslog loopback r36os-zram; do add "$s" boot; done
# Power profile of each scenario (game-governor D2, D6): early in boot, with the `boot` profile
add r36os-power boot
# Before the frontend: what a game or the cable uses (audio, input, saves, the USB network
# for push/dev) and the hardware summary on the screen.
for s in seatd alsa r36os-mixer r36os-persist r36os-logd r36os-usb r36os-savesync r36os-hostshare \
	r36os-input r36os-hwsummary frontend r36os-selftest; do
	add "$s" default
done
# After the frontend (build-speed D20, "after frontend" in their depend() or conf.d): the
# game lists and Wi-Fi by USB dongle (usb-device-access D9). dbus has no order (NetworkManager
# needs it). bluetooth only on the consoles, below (the vm kernel has no Bluetooth, so
# bluetoothd would crash there).
for s in r36os-playlists lume-index dbus networkmanager r36os-ssh-wifi; do
	add "$s" default
done
# Board services that live in the common overlay
case "$BOARD" in
r36s) add r36os-jack default; add r36os-audiotest default ;;
esac
# Bluetooth by USB dongle (usb-device-access D10): the consoles' kernels have it
case "$BOARD" in
ga36|r36s) add bluetooth default ;;
esac
for s in killprocs mount-ro savecache; do add "$s" shutdown; done

# Only the info files of the installed cores (lume-launcher 15.1): RetroArch reads every file
# of libretro_info_path on each start (its cache cannot be written in the read-only system),
# and libretro-core-info brings 291 of them for a dozen cores. retroarch-lume.cfg points
# libretro_info_path here.
mkdir -p /usr/share/r36os/libretro-info
for so in /usr/lib/libretro/*_libretro.so; do
	[ -e "$so" ] || continue
	name=${so##*/}
	info=/usr/share/libretro/info/${name%.so}.info
	if [ -f "$info" ]; then cp "$info" /usr/share/r36os/libretro-info/; fi
done
