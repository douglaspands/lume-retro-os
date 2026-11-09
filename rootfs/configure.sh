#!/bin/sh
# Configuração do rootfs, executada em chroot dentro do container do arch alvo.
# Argumentos: <tty serial> <baud>
set -eu
SERIAL_TTY="$1"
SERIAL_BAUD="$2"
BOARD="$3"

# Usuário do frontend: sem senha e sem login interativo (conta travada).
adduser -D -u 1000 -h /home/game -s /sbin/nologin game
for g in video input audio; do addgroup game "$g"; done
getent group seat >/dev/null && addgroup game seat

# root sem senha, aceito só na serial de debug (fase de validação).
passwd -d root >/dev/null
echo "$SERIAL_TTY" > /etc/securetty

# Sem getty nos terminais virtuais: o tty1 é do frontend. Getty só na serial.
sed -i -e '/^tty[0-9]*::/d' -e '/^#*ttyS[0-9]*::/d' /etc/inittab
echo "$SERIAL_TTY::respawn:/sbin/getty -L $SERIAL_BAUD $SERIAL_TTY vt100" >> /etc/inittab

# Boot verboso na tela e na serial: openrc passa pelo rc-tee.
mkdir -p /etc/r36os
echo "$SERIAL_TTY" > /etc/r36os/serial-tty
echo "$BOARD" > /etc/r36os/board
chmod 644 /usr/libexec/r36os/lib.sh
sed -i -e 's#:/sbin/openrc #:/usr/libexec/r36os/rc-tee #' /etc/inittab
# Log de boot na BOOT, depois do runlevel default (busybox init: wait antes de once).
echo "::once:/usr/libexec/r36os/bootlog" >> /etc/inittab

# OpenRC: log de boot em /var/log/rc.log (usado pelo log de boot na BOOT).
sed -i -e 's/^#*rc_logger=.*/rc_logger="YES"/' /etc/rc.conf

add() { rc-update add "$1" "$2" >/dev/null; }
for s in devfs dmesg udev udev-trigger udev-settle; do add "$s" sysinit; done
for s in modules sysctl hostname bootmisc syslog loopback; do add "$s" boot; done
for s in seatd alsa r36os-persist r36os-savesync r36os-hostshare r36os-playlists r36os-hwsummary frontend \
	r36os-selftest; do
	add "$s" default
done
for s in killprocs mount-ro savecache; do add "$s" shutdown; done
