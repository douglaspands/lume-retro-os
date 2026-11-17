#!/bin/sh
# usb-device-access tasks 3.2 and 3.3: the "Lume" gadget in configfs, umtprd started before
# the UDC is bound, its configuration, and a clean stop. Runs in busybox (builder
# container) on a fake configfs: plain directories, and fake mount, umount, mountpoint,
# rmdir and umtprd that log what they are asked to do.
set -u
cd "$(dirname "$0")/../.."
GADGET_SH="busybox sh rootfs/overlay/usr/libexec/r36os/usb-gadget"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

mkdir -p "$W/bin" "$W/cfg" "$W/udc" "$W/mmc" "$W/soc0"
LOG="$W/cmd.log"
marker() { echo "$W/mnt$(echo "$1" | tr / _)"; }
cat > "$W/bin/mount" <<EOF
#!/bin/sh
echo "mount \$*" >> "$LOG"
for a; do last=\$a; done
: > "$W/mnt\$(echo "\$last" | tr / _)"
EOF
cat > "$W/bin/umount" <<EOF
#!/bin/sh
echo "umount \$*" >> "$LOG"
rm -f "$W/mnt\$(echo "\$1" | tr / _)" "\$1"/*   # the endpoint files go with the mount
EOF
cat > "$W/bin/mountpoint" <<EOF
#!/bin/sh
[ -e "$W/mnt\$(echo "\$2" | tr / _)" ]
EOF
cat > "$W/bin/rmdir" <<EOF
#!/bin/sh
echo "rmdir \$1" >> "$LOG"
rm -rf "\$1"
EOF
# umtprd: writes its descriptors (the endpoint files) after a moment, noting what the
# UDC file of the gadget held at that time, then serves until killed
cat > "$W/bin/umtprd" <<EOF
#!/bin/sh
echo "[uMTPrd - Info] uMTP Responder"
sleep 0.3
echo "umtprd ready, UDC=[\$(cat "$W/cfg/usb_gadget/lume/UDC" 2>/dev/null)]" >> "$LOG"
touch "\$FFS_DIR/ep0" "\$FFS_DIR/ep1" "\$FFS_DIR/ep2" "\$FFS_DIR/ep3"
while :; do sleep 1; done
EOF
# umtprd that dies before writing its descriptors
printf '#!/bin/sh\necho "uMTPrd: cannot open the configuration file" >&2\nexit 1\n' > "$W/bin/umtprd-broken"
cat > "$W/bin/ip" <<EOF
#!/bin/sh
echo "ip \$*" >> "$LOG"
EOF
# udhcpd: keeps a copy of its configuration, serves until killed
cat > "$W/bin/udhcpd" <<EOF
#!/bin/sh
echo "udhcpd \$*" >> "$LOG"
cp "\$2" "$W/udhcpd.conf.seen"
while :; do sleep 1; done
EOF
# dropbear: logs its arguments, prints the log lines of FAKE_DB_LINES on stderr, serves
cat > "$W/bin/dropbear" <<EOF
#!/bin/sh
echo "dropbear \$*" >> "$LOG"
[ -f "$W/db.lines" ] && cat "$W/db.lines" >&2
while :; do sleep 1; done
EOF
chmod +x "$W/bin/"*

export BOARD_FILE="$W/board" CONFIGFS="$W/cfg" UDC_CLASS="$W/udc" FFS_DIR="$W/ffs" \
	UMTPRD="$W/bin/umtprd" UMTPRD_CONF="$W/umtprd.conf" USB_RUN="$W/run" \
	SOC0_DIR="$W/soc0" MMC_DEVICE="$W/mmc" GAME_UID=1000 GAME_GID=1000 \
	MOUNT="$W/bin/mount" UMOUNT="$W/bin/umount" MOUNTPOINT="$W/bin/mountpoint" \
	RMDIR="$W/bin/rmdir" KMSG="$W/kmsg" USB_LIBDIR="$PWD/aports/lume-core/files/usr/libexec/r36os" \
	LOGS_RAM="$W/logs" NET_CLASS="$W/net" IP="$W/bin/ip" UDHCPD="$W/bin/udhcpd" \
	DROPBEAR="$W/bin/dropbear"
EV="$W/logs/events.pending"
G="$W/cfg/usb_gadget/lume"
echo ga36 > "$W/board"
echo 0x1a2b3c4d > "$W/mmc/serial"
: > "$W/kmsg"     # a writable "kernel log": what say() sends to /dev/kmsg

### the vm: no UDC, nothing is built
out=$($GADGET_SH start); rc=$?
check "vm: no UDC exits 0 and says so" '[ $rc = 0 ] && [ "$out" = "usb: no USB device controller, nothing to do" ]'
check "vm: nothing is built or mounted" '[ ! -e "$G" ] && [ ! -e "$LOG" ]'

### GA36: the gadget is built, umtprd is ready before the UDC is bound
mkdir -p "$W/udc/musb-hdrc.2.auto"
: > "$LOG"
out=$($GADGET_SH start); rc=$?
check "start: exit 0" '[ $rc = 0 ]'
check "start: USB IDs of the composite gadget" '[ "$(cat $G/idVendor)" = 0x1d6b ] && [ "$(cat $G/idProduct)" = 0x0104 ]'
check "start: names the console and the card serial (no soc0 on the A33)" '[ "$(cat $G/strings/0x409/product)" = "Lume GA36" ] && [ "$(cat $G/strings/0x409/manufacturer)" = "Lume Retro OS" ] && [ "$(cat $G/strings/0x409/serialnumber)" = 0x1a2b3c4d ]'
check "start: MTP and NCM linked into the configuration" '[ -L $G/configs/c.1/ffs.mtp ] && [ -L $G/configs/c.1/ncm.usb0 ] && [ -d $G/functions/ffs.mtp ] && [ -d $G/functions/ncm.usb0 ]'
check "start: fixed, locally administered MAC addresses" 'grep -qE "^02(:[0-9a-f]{2}){5}$" $G/functions/ncm.usb0/dev_addr && grep -qE "^06(:[0-9a-f]{2}){5}$" $G/functions/ncm.usb0/host_addr'
check "start: configfs and functionfs mounted" 'grep -qx "mount -t configfs none $W/cfg" "$LOG" && grep -qx "mount -t functionfs mtp $W/ffs" "$LOG"'
check "start: umtprd was ready while the UDC was still empty" 'grep -qx "umtprd ready, UDC=\[\]" "$LOG"'
check "start: then the gadget is bound to the UDC" '[ "$(cat $G/UDC)" = musb-hdrc.2.auto ]'
check "start: logged in English" 'printf "%s\n" "$out" | grep -qx "usb: gadget \"Lume GA36\" bound to musb-hdrc.2.auto (MTP, NCM), serial 0x1a2b3c4d"'
pid=$(cat "$W/run/umtprd.pid")
check "start: umtprd keeps running" 'kill -0 "$pid" 2>/dev/null'
check "start: umtprd output reaches the kernel log and umtprd.log" 'grep -qx "r36os-usb: umtprd: \[uMTPrd - Info\] uMTP Responder" $W/kmsg && grep -q "uMTP Responder" $W/run/umtprd.log'

### umtprd configuration (3.3): only ROMS, with the frontend user, FunctionFS endpoints
C="$W/umtprd.conf"
check "conf: one storage, ROMS on /storage as the game user" '[ "$(grep -c "^storage " $C)" = 1 ] && grep -qx "storage \"/storage\" \"ROMS\" \"rw,uid=1000,gid=1000\"" $C'
check "conf: no path outside /storage and the endpoints (no BOOT)" '! grep -E "\"/" $C | grep -vE "\"/storage\"|\"$W/ffs/ep[0-3]\"" | grep -q . && ! grep -q "/boot" $C'
check "conf: FunctionFS mode on the mounted endpoints" 'grep -qx "usb_functionfs_mode 0x1" $C && grep -qx "usb_dev_path \"$W/ffs/ep0\"" $C && grep -qx "usb_epin_path \"$W/ffs/ep1\"" $C'
check "conf: same IDs and names as the gadget, kept across disconnects" 'grep -qx "usb_vendor_id 0x1d6b" $C && grep -qx "product \"Lume GA36\"" $C && grep -qx "loop_on_disconnect 1" $C'

### stop: unbound, umtprd stopped, functionfs unmounted, configfs emptied in order
: > "$LOG"
out=$($GADGET_SH stop); rc=$?
check "stop: exit 0" '[ $rc = 0 ]'
check "stop: umtprd stopped" '! kill -0 "$pid" 2>/dev/null'
check "stop: functionfs unmounted" 'grep -qx "umount $W/ffs" "$LOG"'
check "stop: the gadget is gone" '[ ! -e "$G" ]'
check "stop: configuration removed before the functions, the gadget last" '[ "$(grep "^rmdir" "$LOG" | sed "s|^rmdir $G||" | tr "\n" " ")" = "/configs/c.1/strings/0x409 /configs/c.1 /functions/ffs.mtp /functions/ncm.usb0 /strings/0x409  " ]'
out=$($GADGET_SH stop); rc=$?
check "stop: a second stop is harmless" '[ $rc = 0 ]'

### umtprd that never becomes ready: no bind, everything removed, failure
: > "$LOG"
out=$(UMTPRD="$W/bin/umtprd-broken" READY_TRIES=5 $GADGET_SH start); rc=$?
check "broken umtprd: start fails and says why" '[ $rc = 1 ] && printf "%s\n" "$out" | grep -q "^usb: ERROR: umtprd exited before writing its descriptors"'
check "broken umtprd: its own error reaches the log" 'printf "%s\n" "$out" | grep -qx "usb: umtprd: uMTPrd: cannot open the configuration file"'
check "umtprd is found by name (Alpine installs /bin/umtprd)" 'grep -qx "UMTPRD=\${UMTPRD:-umtprd}" rootfs/overlay/usr/libexec/r36os/usb-gadget'
check "broken umtprd: nothing left bound or built" '[ ! -e "$G" ] && grep -qx "umount $W/ffs" "$LOG"'

### R36S: the SoC serial number when the kernel gives one
echo r36s > "$W/board"
echo "  c3d9b8674f4b94f6 " > "$W/soc0/serial_number"
rm -rf "$W/udc/"*; mkdir -p "$W/udc/ff300000.usb"
out=$($GADGET_SH start)
check "r36s: product and SoC serial" '[ "$(cat $G/strings/0x409/product)" = "Lume R36S" ] && [ "$(cat $G/strings/0x409/serialnumber)" = c3d9b8674f4b94f6 ] && [ "$(cat $G/UDC)" = ff300000.usb ]'
$GADGET_SH stop >/dev/null

### run (3.4): the R36S role switch follows the ID pin; TERM removes the gadget
mkdir -p "$W/role/ff300000.usb-role-switch" "$W/extcon/extcon0"
echo none > "$W/role/ff300000.usb-role-switch/role"
printf 'USB=0\nUSB-HOST=0\n' > "$W/extcon/extcon0/state"
export ROLE_CLASS="$W/role" EXTCON_CLASS="$W/extcon" POLL=0.1
$GADGET_SH run > "$W/run.out" 2>&1 &
RUN=$!
i=0; while [ ! -s "$G/UDC" ] && [ $i -lt 30 ]; do sleep 0.1; i=$((i + 1)); done
sleep 0.3
check "run: device role with the ID pin high" '[ "$(cat $W/role/ff300000.usb-role-switch/role)" = device ] && [ "$(cat $G/UDC)" = ff300000.usb ]'
printf 'USB=0\nUSB-HOST=1\n' > "$W/extcon/extcon0/state"
sleep 0.4
check "run: host role while an OTG adapter pulls the ID pin low" '[ "$(cat $W/role/ff300000.usb-role-switch/role)" = host ]'
printf 'USB=0\nUSB-HOST=0\n' > "$W/extcon/extcon0/state"
sleep 0.4
check "run: back to device when the adapter is removed" '[ "$(cat $W/role/ff300000.usb-role-switch/role)" = device ]'
check "run: each role change logged once" '[ "$(grep -c "port role device" $W/run.out)" = 2 ] && [ "$(grep -c "port role host (ID pin low: OTG adapter)" $W/run.out)" = 1 ]'
kill -TERM $RUN; wait $RUN; rc=$?
check "run: TERM stops cleanly and removes the gadget" '[ $rc = 0 ] && [ ! -e "$G" ] && grep -q "usb: gadget removed" $W/run.out'

### run on the GA36: no role switch, nothing is written
echo ga36 > "$W/board"
rm -rf "$W/role/"* "$W/udc/"*; mkdir -p "$W/udc/musb-hdrc.2.auto"
printf 'USB=1\nUSB-HOST=1\n' > "$W/extcon/extcon0/state"
$GADGET_SH run > "$W/run.out" 2>&1 &
RUN=$!
sleep 1
kill -TERM $RUN; wait $RUN
check "run: GA36 has no role switch, the MUSB follows the ID pin by itself" '! grep -q "port role" $W/run.out && [ ! -e "$G" ]'

### lume-launcher 5.5: the PC lets go of the gadget -> the game lists are scanned again
printf '#!/bin/sh\necho "rc-service $*" >> "%s"\n' "$LOG" > "$W/bin/rc-service"
chmod +x "$W/bin/rc-service"
echo "not attached" > "$W/udc/musb-hdrc.2.auto/state"
: > "$LOG"
RC_SERVICE="$W/bin/rc-service" $GADGET_SH run > "$W/run.out" 2>&1 &
RUN=$!
sleep 0.5
check "pc: nothing restarted while no PC was ever configured" '! grep -q "^rc-service" "$LOG"'
echo configured > "$W/udc/musb-hdrc.2.auto/state"
sleep 0.4
check "pc: nothing restarted while the PC is configured" '! grep -q "^rc-service" "$LOG"'
echo "not attached" > "$W/udc/musb-hdrc.2.auto/state"
sleep 0.4
check "pc: disconnect restarts lume-index once" '[ "$(grep -c "^rc-service lume-index restart$" "$LOG")" = 1 ] && grep -q "usb: PC disconnected (not attached): rescanning the game lists" $W/run.out'
kill -TERM $RUN; wait $RUN
rm -f "$W/udc/musb-hdrc.2.auto/state"

### USB network and root without a password (4.1, 4.2): the PC brings the NCM link up and down
mkdir -p "$W/net/usb0"
echo 0 > "$W/net/usb0/carrier"
# the lines dropbear 2026.91 writes (seen in Alpine with dropbear -B and an empty root password)
printf '%s\n' "[201] Nov 13 19:00:00 Auth succeeded with blank password for 'root' from 10.55.0.2:40000" \
	"[202] Nov 13 19:00:05 Exit before auth from <10.55.0.2:40002>: (user 'game', 1 fails): Max auth tries reached - user 'game'" > "$W/db.lines"
rm -f "$EV"; : > "$LOG"
$GADGET_SH run > "$W/run.out" 2>&1 &
RUN=$!
sleep 0.6
check "net: the interface is set up when the gadget is bound" 'grep -qx "ip link set usb0 up" "$LOG"'
check "net: nothing served while the PC has not brought the link up" '! grep -q "^udhcpd\|^dropbear " "$LOG"'
echo 1 > "$W/net/usb0/carrier"
sleep 0.8
check "net: 10.55.0.1/30 on the interface when the link comes up" 'grep -qx "ip addr replace 10.55.0.1/30 dev usb0" "$LOG"'
C="$W/udhcpd.conf.seen"
check "net: udhcpd hands out 10.55.0.2 only" 'grep -qx "start 10.55.0.2" $C && grep -qx "end 10.55.0.2" $C && grep -qx "max_leases 1" $C && grep -qx "interface usb0" $C && grep -qx "option subnet 255.255.255.252" $C'
check "net: no router and no DNS for the PC" '! grep -v "^#" $C | grep -qiE "router|dns|domain"'
check "ssh: root with no password, host key made in RAM, no forwarding, on 10.55.0.1 only" 'grep -qx "dropbear -F -E -R -B -j -k -p 10.55.0.1:22" "$LOG"'
check "ssh: events for the network and both logins" 'grep -q " usb OK network: up on usb0 (console 10.55.0.1, PC 10.55.0.2)$" $EV && grep -q " usb OK ssh: login accepted: with blank password for .root. from 10.55.0.2:40000$" $EV && grep -q " usb FAIL ssh: login refused: from <10.55.0.2:40002>: (user .game., 1 fails)" $EV'
db=$(cat "$W/run/dropbear.pid"); dh=$(cat "$W/run/udhcpd.pid")
echo 0 > "$W/net/usb0/carrier"
sleep 0.8
check "net: link down stops udhcpd and dropbear and clears the address" '! kill -0 $db 2>/dev/null && ! kill -0 $dh 2>/dev/null && grep -qx "ip addr flush dev usb0" "$LOG" && grep -q " usb OK network: down on usb0$" $EV'
### the link comes up again: both serve again, with nothing to set up on the card
: > "$LOG"
echo 1 > "$W/net/usb0/carrier"
sleep 0.8
check "ssh: a new link starts udhcpd and dropbear again" 'grep -q "^udhcpd " "$LOG" && grep -q "^dropbear " "$LOG"'
kill -TERM $RUN; wait $RUN
check "run: TERM with the link up stops everything" '[ ! -e "$G" ] && [ ! -e "$W/run/udhcpd.pid" ]'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
