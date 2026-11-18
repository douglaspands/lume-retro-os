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
# (dropbear -B on 10.55.0.1 only, usb-device-access D4); never on another interface of a
# console (the vm only: on its QEMU user network, reachable from the PC's 127.0.0.1 only).
passwd -d root >/dev/null
echo "$SERIAL_TTY" > /etc/securetty
# SSH over Wi-Fi (lume-launcher D18): "console" is root (uid 0) under another name, so the
# Wi-Fi server can take a password (the code shown on the screen) while root keeps none for
# the cable. Locked until lume-ssh-wifi sets the code in /etc/shadow (the RAM layer).
echo "console:x:0:0:Lume console over Wi-Fi:/root:/bin/sh" >> /etc/passwd
echo "console:!::0:::::" >> /etc/shadow

# No getty on the virtual terminals: tty1 belongs to the frontend. Getty only on the serial.
sed -i -e '/^tty[0-9]*::/d' -e '/^#*ttyS[0-9]*::/d' /etc/inittab
echo "$SERIAL_TTY::respawn:/sbin/getty -L $SERIAL_BAUD $SERIAL_TTY vt100" >> /etc/inittab

# Verbose boot on the screen and on the serial: openrc goes through rc-tee.
mkdir -p /etc/lume
echo "$SERIAL_TTY" > /etc/lume/serial-tty
echo "$BOARD" > /etc/lume/board
chmod 644 /usr/libexec/lume/lib.sh
sed -i -e 's#:/sbin/openrc #:/usr/libexec/lume/rc-tee #' /etc/inittab
# Boot log in ROMS/logs/boot/ (or on BOOT without ROMS), after the default runlevel
# (busybox init: wait before once).
echo "::once:/usr/libexec/lume/bootlog" >> /etc/inittab

# OpenRC: boot log in /var/log/rc.log (used by the boot log).
sed -i -e 's/^#*rc_logger=.*/rc_logger="YES"/' /etc/rc.conf
# cgroup v2 only, mounted on /sys/fs/cgroup: the session hands /sys/fs/cgroup/lume/ to the
# game user and the launcher puts each game in its own cgroup (lume-launcher D9)
sed -i -e 's/^#*rc_cgroup_mode=.*/rc_cgroup_mode="unified"/' /etc/rc.conf
grep -qx 'rc_cgroup_mode="unified"' /etc/rc.conf || echo 'rc_cgroup_mode="unified"' >> /etc/rc.conf
# Services start in parallel (build-speed D20): the order comes only from the depend() of
# each service. The ones no game uses (NetworkManager, Bluetooth, RetroArch playlists,
# lume-index) are "after frontend", so the frontend does not wait for them; the hardware
# snapshot of hwinfo is taken by lume-logd once the frontend is up.
sed -i -e 's/^#*rc_parallel=.*/rc_parallel="YES"/' /etc/rc.conf
grep -qx 'rc_parallel="YES"' /etc/rc.conf || echo 'rc_parallel="YES"' >> /etc/rc.conf

add() { rc-update add "$1" "$2" >/dev/null; }
# cgroups mounts the cgroup v2 of rc_cgroup_mode above: without it in a runlevel nothing mounts
# /sys/fs/cgroup and the games end by process group only (seen in test-vm on 2026-11-14).
# sysfs is listed too: its "after sysfs" only orders services of the same runlevel, and with
# sysfs pulled in later cgroups found no /sys/fs/cgroup, did nothing and still said started.
for s in sysfs devfs dmesg cgroups udev udev-trigger udev-settle; do add "$s" sysinit; done
for s in modules sysctl hostname bootmisc syslog loopback lume-zram; do add "$s" boot; done
# Power profile of each scenario (game-governor D2, D6): early in boot, with the `boot` profile
add lume-power boot
# Before the frontend: what a game or the cable uses (audio, input, saves, the USB network
# for push/dev) and the hardware summary on the screen.
for s in seatd alsa lume-mixer lume-persist lume-logd lume-usb lume-savesync lume-hostshare \
	lume-input lume-hwsummary frontend lume-selftest; do
	add "$s" default
done
# After the frontend (build-speed D20, "after frontend" in their depend() or conf.d): the
# game lists, the card maintenance requests (lume-card, device-fixes D4) and Wi-Fi by USB
# dongle (usb-device-access D9). dbus has no order (NetworkManager needs it). bluetooth only
# on the consoles, below (the vm kernel has no Bluetooth, so bluetoothd would crash there).
for s in lume-playlists lume-index lume-card lume-clock dbus networkmanager lume-ssh-wifi; do
	add "$s" default
done
# Board services that live in the common overlay. lume-vmnet (virtual-gamepad 3.3): the vm's
# local network of `lume vm --ssh` with root ssh for `lume dev`; never on a console.
case "$BOARD" in
r36s) add lume-jack default; add lume-audiotest default ;;
vm) add lume-vmnet default ;;
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
mkdir -p /usr/share/lume/libretro-info
for so in /usr/lib/libretro/*_libretro.so; do
	[ -e "$so" ] || continue
	name=${so##*/}
	info=/usr/share/libretro/info/${name%.so}.info
	if [ -f "$info" ]; then cp "$info" /usr/share/lume/libretro-info/; fi
done
