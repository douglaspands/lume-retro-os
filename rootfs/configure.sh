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

# root without a password, accepted only on the debug serial (validation phase).
passwd -d root >/dev/null
echo "$SERIAL_TTY" > /etc/securetty

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

add() { rc-update add "$1" "$2" >/dev/null; }
for s in devfs dmesg udev udev-trigger udev-settle; do add "$s" sysinit; done
for s in modules sysctl hostname bootmisc syslog loopback r36os-zram; do add "$s" boot; done
for s in seatd alsa r36os-mixer r36os-persist r36os-logd r36os-savesync r36os-hostshare r36os-playlists \
	r36os-hwsummary frontend r36os-selftest; do
	add "$s" default
done
# Services of the hardware layer (board/<board>/hw-packages.txt), when the board has them
for s in r36os-padmerge; do
	if [ -f "/etc/init.d/$s" ]; then add "$s" default; fi
done
# Board services that live in the common overlay
case "$BOARD" in
r36s) add r36os-jack default ;;
esac
for s in killprocs mount-ro savecache; do add "$s" shutdown; done
