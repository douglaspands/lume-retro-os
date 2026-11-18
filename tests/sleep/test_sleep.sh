#!/bin/sh
# device-fixes task 8.3 (D11): the lume-sleep service of lume-power. Runs in busybox (builder
# container, as root) on a fake sysfs (plain files), with a fake lume-input that answers the
# phase file, fake lume-clock, nmcli, sync and poweroff, and a fake session.
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

S=$PWD/aports/lume-power/files/usr/libexec/lume/lume-sleep
L=$W/libexec
mkdir -p "$L" "$W/bin" "$W/run" "$W/conf" "$W/logs"
ln -s "$PWD/aports/lume-core/files/usr/libexec/lume/lib.sh" "$L/lib.sh"
ln -s "$PWD/aports/lume-core/files/usr/libexec/lume/logs.sh" "$L/logs.sh"
DIR=$W/run/sleep
SYS=$W/sys
T=$W/trace
export SL_LIBDIR=$L SL_RUN=$W/run LUME_SLEEP_DIR=$DIR LUME_SLEEP_CONF=$W/conf SL_SYS=$SYS
export SL_GROUP=nobody SL_KMSG=$W/kmsg SL_WAIT=10 SL_USB_DELAY=0.5 SL_POWEROFF=$W/bin/poweroff
export SL_POWEROFF_WAIT=0.5 SL_SESSION_PID=$W/run/frontend.pid SL_CLOCK=$W/bin/lume-clock
export SL_NMCLI=$W/bin/nmcli SL_SYNC=$W/bin/sync SL_POWER_FIFO=$W/run/power SL_TRACE=$T
export BOARD_FILE=$W/board LOGS_RAM=$W/logs CALLS=$W/calls WIFI=$W/wifi

# fake commands: each call goes to $CALLS
printf '#!/bin/sh\necho "clock $*" >> "$CALLS"\n' >"$W/bin/lume-clock"
printf '#!/bin/sh\necho sync >> "$CALLS"\n' >"$W/bin/sync"
printf '#!/bin/sh\necho poweroff >> "$CALLS"\n' >"$W/bin/poweroff"
cat >"$W/bin/nmcli" <<'EOF'
#!/bin/sh
echo "nmcli $*" >> "$CALLS"
case "$*" in
"radio wifi") cat "$WIFI" ;;
"radio wifi off") echo disabled > "$WIFI" ;;
"radio wifi on") echo enabled > "$WIFI" ;;
esac
EOF
chmod +x "$W/bin/"*
mkfifo "$W/run/power"
# a reader that keeps the FIFO of lume-power open, as the service does
exec 5<>"$W/run/power"

# fake sysfs
reset_sys() {
	rm -rf "$SYS"
	mkdir -p "$SYS/class/backlight/backlight" "$SYS/kernel/config/usb_gadget/lume" "$SYS/power"
	echo 7 >"$SYS/class/backlight/backlight/brightness"
	echo musb-hdrc.1.auto >"$SYS/kernel/config/usb_gadget/lume/UDC"
	: >"$SYS/power/state"
	echo "[s2idle]" >"$SYS/power/mem_sleep"
}

# fake lume-input: answers each new `phase suspend <seq>` in `clients` (by rename, as root);
# $1: ok | timeout | spam (answers ok and also makes a second suspend request)
fake_input() {
	(
		last=
		while :; do
			p=
			read -r p <"$DIR/phase" 2>/dev/null
			case $p in
			"suspend "*)
				s=${p#suspend }
				if [ "$s" != "$last" ]; then
					last=$s
					case $1 in
					timeout) printf 'suspend %s timeout 0/1\n' "$s" >"$W/c.tmp" ;;
					*) printf 'suspend %s ok 1/1\n' "$s" >"$W/c.tmp" ;;
					esac
					[ "$1" != spam ] || : >"$DIR/suspend"
					mv -f "$W/c.tmp" "$DIR/clients"
				fi
				;;
			esac
			sleep 0.05
		done
	) &
	FI=$!
}
stop_input() { kill "$FI" 2>/dev/null; wait "$FI" 2>/dev/null; }

fresh() {  # a fresh boot: folder, private state, logs, trace
	rm -rf "$DIR" "$W/run"/sleep.* "$W/logs"/* "$T" "$CALLS" "$W/kmsg"
	mkdir -p "$DIR"
	echo awake >"$W/run/sleep.status"
	: >"$T"; : >"$CALLS"; : >"$W/kmsg"
	echo enabled >"$WIFI"
	echo ga36 >"$BOARD_FILE"
	reset_sys
}
request() {  # request <name>: the file and the inotifyd call
	: >"$DIR/$1"
	busybox sh "$S" w "$DIR" "$1"
}
events() { cat "$LOGS_RAM/events.pending" 2>/dev/null; }
has_event() { events | grep -q " sleep $1\$"; }
trace() { tr '\n' '|' <"$T"; }
fifo_lines() {  # what reached lume-power's FIFO
	local l out=
	while read -t 1 -r l <&5; do out="$out$l|"; [ "$l" != resume ] || break; done
	echo "$out"
}

### 1. the whole sequence, in order
fresh
fake_input ok
request suspend
stop_input
UDC_AT_RETURN=$(cat "$SYS/kernel/config/usb_gadget/lume/UDC")
EXP="phase suspend 1|clients suspend 1 ok 1/1|run $W/bin/lume-clock save|run $W/bin/sync|write class/backlight/backlight/brightness 0|run $W/bin/nmcli radio wifi off|power suspend|write kernel/config/usb_gadget/lume/UDC |write power/state freeze|power resume|run $W/bin/nmcli radio wifi on|write class/backlight/backlight/brightness 7|phase resume 1|"
check "suspend: the steps in the D11 order and back in reverse" '[ "$(trace)" = "$EXP" ]'
check "suspend: the clock hook, sync and Wi-Fi off/on ran" \
	'[ "$(tr "\n" "|" <"$CALLS")" = "clock save|sync|nmcli radio wifi|nmcli radio wifi off|nmcli radio wifi on|" ]'
check "suspend: the governor got suspend and resume on its FIFO" '[ "$(fifo_lines)" = "suspend|resume|" ]'
check "suspend: freeze written to /sys/power/state (GA36 mode)" '[ "$(cat "$SYS/power/state")" = freeze ]'
check "suspend: mem_sleep untouched in freeze" '[ "$(cat "$SYS/power/mem_sleep")" = "[s2idle]" ]'
check "suspend: the screen is back at its level" '[ "$(cat "$SYS/class/backlight/backlight/brightness")" = 7 ]'
check "suspend: the Wi-Fi radio is back on" '[ "$(cat "$WIFI")" = enabled ]'
check "suspend: events OK suspend freeze and OK resume after <s>" \
	'has_event "OK suspend freeze" && events | grep -Eq " sleep OK resume after [0-9]+$" && ! events | grep -q " sleep FAIL"'
check "suspend: phase resume 1 and status awake" \
	'[ "$(cat "$DIR/phase")" = "resume 1" ] && [ "$(cat "$DIR/status")" = awake ] && [ "$(cat "$W/run/sleep.status")" = awake ]'
check "suspend: the request file is gone" '[ ! -e "$DIR/suspend" ]'
check "usb: still unbound when the screen comes back" '[ -z "$UDC_AT_RETURN" ]'
sleep 0.8
check "usb: bound again ~1 s later, in the background" \
	'[ "$(cat "$SYS/kernel/config/usb_gadget/lume/UDC")" = musb-hdrc.1.auto ] && grep -qx "usb rebound musb-hdrc.1.auto" "$T"'

### 2. the wake guard and the sequence number
request suspend
check "guard: a suspend right after the wake is the waking press, dropped" \
	'grep -q "lume-sleep: suspend request dropped: the press that woke the console" "$W/kmsg" && ! grep -q "phase suspend 2" "$T"'
sleep 1.1
fake_input ok
request suspend
stop_input
check "guard: past 1 s the next suspend runs, with sequence 2" '[ "$(cat "$DIR/phase")" = "resume 2" ]'
sleep 0.8

### 3. a mute client, and lume-input not answering
fresh
fake_input timeout
request suspend
stop_input
check "mute client: lume-input's timeout is logged and the suspension goes on" \
	'has_event "FAIL clients: 0/1 answered within 2s" && has_event "OK suspend freeze" && grep -q "^write power/state freeze$" "$T"'
fresh
t0=$(date +%s)
request suspend
t1=$(date +%s)
check "no lume-input: suspends after its own deadline" \
	'has_event "FAIL clients: lume-input did not answer within 3s" && has_event "OK suspend freeze" && [ $((t1 - t0)) -le 4 ]'
sleep 0.8
fresh
# a clients file that is not root's (the game group can create files in the folder) does not
# count; the planter answers right after the phase
(
	while [ "$(cat "$DIR/phase" 2>/dev/null)" != "suspend 1" ]; do sleep 0.05; done
	printf 'suspend 1 ok 1/1\n' >"$W/planted"
	chown nobody "$W/planted"
	mv "$W/planted" "$DIR/clients"
) &
request suspend
wait
check "planted clients: a file not owned by root is ignored" \
	'has_event "FAIL clients: lume-input did not answer within 3s" && grep -qx "clients none" "$T"'
fifo_lines >/dev/null
sleep 0.8

### 4. the kernel refuses: everything back, the screen on
fresh
rm -f "$SYS/power/state"
mkdir "$SYS/power/state"
fake_input ok
request suspend
stop_input
check "kernel refusal: the failed suspend event with the reason" \
	'has_event "FAIL suspend freeze: write /sys/power/state failed (Is a directory)"'
check "kernel refusal: no resume event" '! events | grep -q " sleep OK resume"'
check "kernel refusal: the screen is on again at its level" '[ "$(cat "$SYS/class/backlight/backlight/brightness")" = 7 ]'
check "kernel refusal: Wi-Fi back, governor back, clients resumed, status awake" \
	'[ "$(cat "$WIFI")" = enabled ] && grep -qx "power resume" "$T" && [ "$(cat "$DIR/phase")" = "resume 1" ] && [ "$(cat "$DIR/status")" = awake ]'
fifo_lines >/dev/null
sleep 0.8
check "kernel refusal: the gadget bound again" '[ "$(cat "$SYS/kernel/config/usb_gadget/lume/UDC")" = musb-hdrc.1.auto ]'
fake_input ok
request suspend
stop_input
check "kernel refusal: no wake guard after it (the next request runs)" '[ "$(cat "$DIR/phase")" = "resume 2" ]'
fifo_lines >/dev/null
sleep 0.8

### 5. mem mode, and the console file
fresh
echo r36s >"$BOARD_FILE"
printf '# test\nmode mem # measured\n' >"$W/conf/r36s.conf"
fake_input ok
request suspend
stop_input
check "mem: deep to mem_sleep, then mem to state" \
	'grep -n "" "$T" | grep -q "write power/mem_sleep deep" && [ "$(cat "$SYS/power/mem_sleep")" = deep ] && [ "$(cat "$SYS/power/state")" = mem ] && has_event "OK suspend mem"'
check "mem: mem_sleep before state" '[ "$(grep -n "^write power/mem_sleep" "$T" | cut -d: -f1)" -lt "$(grep -n "^write power/state" "$T" | cut -d: -f1)" ]'
fifo_lines >/dev/null
sleep 0.8
fresh
printf 'mode deep\n' >"$W/conf/ga36.conf"
fake_input ok
request suspend
stop_input
check "mode: a bad value gives freeze" '[ "$(cat "$SYS/power/state")" = freeze ]'
rm -f "$W/conf/ga36.conf"
fifo_lines >/dev/null
sleep 0.8

### 6. what is missing is skipped: no clock hook, no Wi-Fi, no gadget, no backlight, no lume-power
fresh
rm -rf "$SYS/class/backlight" "$SYS/kernel"
echo disabled >"$WIFI"
mv "$W/bin/lume-clock" "$W/lume-clock.off"
exec 5>&-
rm -f "$W/run/power"
fake_input ok
request suspend
stop_input
check "missing pieces: no clock, no Wi-Fi change, no unbind" \
	'! grep -q "^clock" "$CALLS" && ! grep -q "radio wifi off" "$CALLS" && ! grep -q "usb_gadget" "$T"'
check "missing pieces: only the governor is logged (no lume-power FIFO), the suspension runs" \
	'has_event "FAIL governor: power service not running" && [ "$(events | grep -c " sleep FAIL")" = 1 ] && has_event "OK suspend freeze"'
mv "$W/lume-clock.off" "$W/bin/lume-clock"
mkfifo "$W/run/power"
exec 5<>"$W/run/power"

### 7. a second request during the sequence, and a busy status
fresh
fake_input spam
request suspend
stop_input
check "double request: dropped, kernel log only" \
	'[ ! -e "$DIR/suspend" ] && grep -q "lume-sleep: suspend request dropped: busy (suspending 1)" "$W/kmsg" && [ "$(grep -c "^write power/state" "$T")" = 1 ]'
fifo_lines >/dev/null
sleep 0.8
fresh
echo "suspending 4" >"$W/run/sleep.status"
request suspend
check "busy status: the request is dropped without running" \
	'grep -q "suspend request dropped: busy (suspending 4)" "$W/kmsg" && [ ! -s "$T" ] && [ ! -e "$DIR/suspend" ]'

### 8. the power button held during the client wait: no suspension, the power off runs next
fresh
fake_input ok
: >"$DIR/poweroff"
request suspend
stop_input
check "poweroff pending: the suspension is cancelled and everything comes back" \
	'! grep -q "^write power/state" "$T" && [ "$(cat "$SYS/class/backlight/backlight/brightness")" = 7 ] && [ "$(cat "$DIR/phase")" = "resume 1" ] && ! events | grep -q " sleep OK suspend"'
rm -f "$DIR/poweroff"
fifo_lines >/dev/null
sleep 0.8

### 9. poweroff: through the session, with a fallback
fresh
cat >"$W/session.sh" <<EOF
#!/bin/sh
trap 'echo usr1 >> "$CALLS"; exit 0' USR1
while :; do sleep 0.05; done
EOF
busybox sh "$W/session.sh" &
SP=$!
sleep 0.2
echo "$SP" >"$W/run/frontend.pid"
request poweroff
sleep 0.2
check "poweroff: SIGUSR1 to the session and the event" \
	'grep -qx usr1 "$CALLS" && has_event "OK poweroff: power button held" && grep -qx "session $SP" "$T"'
check "poweroff: status poweroff" '[ "$(cat "$DIR/status")" = poweroff ]'
sleep 0.6
check "poweroff: a session that does not power off in time gets the fallback poweroff" \
	'grep -qx poweroff "$CALLS" && grep -qx "poweroff fallback" "$T"'
request poweroff
check "poweroff: a second request is dropped" \
	'grep -q "poweroff request dropped: busy (poweroff)" "$W/kmsg" && [ "$(grep -c " sleep OK poweroff" "$LOGS_RAM/events.pending")" = 1 ]'
request suspend
check "poweroff: a suspend after it is dropped" 'grep -q "suspend request dropped: busy (poweroff)" "$W/kmsg"'
fresh
rm -f "$W/run/frontend.pid"
request poweroff
check "poweroff: no session, powers off at once" \
	'grep -qx poweroff "$CALLS" && grep -qx "poweroff direct" "$T" && has_event "OK poweroff: power button held"'

### 10. unknown names and own files
fresh
request reboot
check "refused: an unknown name is deleted and logged" '[ ! -e "$DIR/reboot" ] && has_event "FAIL refused request: reboot"'
request 'a b$(x)'
check "refused: the name is sanitized" 'has_event "FAIL refused request: a?b??x?"'
echo "suspend 1" >"$DIR/phase"
busybox sh "$S" w "$DIR" phase
busybox sh "$S" w "$DIR" .tmp
check "own files: phase and hidden names are no requests" '[ -e "$DIR/phase" ] && [ ! -s "$T" ] && ! events | grep -q refused.*phase'

### 11. the service: folder, a phase left at suspend, a pending request, inotifyd
fresh
rm -rf "$DIR"
mkdir -p "$DIR"
echo "suspend 7" >"$DIR/phase"
echo "suspend 7 ok 1/1" >"$DIR/clients"
: >"$DIR/bogus"
SL_SELF=$S busybox sh "$S" run &
SV=$!
n=0
while [ $n -lt 40 ] && ! has_event "FAIL refused request: bogus"; do sleep 0.05; n=$((n + 1)); done
sleep 0.3
check "service: the folder is root:nobody 1770" \
	'[ "$(stat -c %a "$DIR")" = 1770 ] && [ "$(stat -c %U:%G "$DIR")" = root:nobody ]'
check "service: a phase left at suspend is answered with resume" '[ "$(cat "$DIR/phase")" = "resume 7" ]'
check "service: status awake, stale clients gone, the pending request handled" \
	'[ "$(cat "$DIR/status")" = awake ] && [ ! -e "$DIR/clients" ] && [ ! -e "$DIR/bogus" ]'
fake_input ok
: >"$DIR/suspend"
n=0
while [ $n -lt 60 ] && ! events | grep -q " sleep OK resume after"; do sleep 0.05; n=$((n + 1)); done
stop_input
check "service: inotifyd runs a request made by creating the file" \
	'has_event "OK suspend freeze" && events | grep -q " sleep OK resume after" && [ ! -e "$DIR/suspend" ]'
kill "$SV" 2>/dev/null
wait "$SV" 2>/dev/null
sleep 0.8

### 12. packaging and wiring
check "init: after the frontend, inotifyd service" \
	'grep -q "after frontend" aports/lume-power/files/etc/init.d/lume-sleep && grep -q "command_args=run" aports/lume-power/files/etc/init.d/lume-sleep'
check "configure.sh: lume-sleep in the default runlevel" 'grep -Eq "^for s in .* lume-sleep " rootfs/configure.sh'
check "the script and the init are executable" '[ -x "$S" ] && [ -x aports/lume-power/files/etc/init.d/lume-sleep ]'

kill "$SP" 2>/dev/null
exec 5>&-
rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" = 0 ]
