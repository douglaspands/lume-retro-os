#!/bin/sh
# device-fixes task 5.3: lume-card request handler. Runs in busybox (builder container) with a
# fake fstrim and a fake mountpoint; the handler is called the way inotifyd calls it.
set -u
cd "$(dirname "$0")/../.."
LIB="$PWD/aports/lume-core/files/usr/libexec/lume"
EV="busybox sh aports/lume-saves/files/usr/libexec/lume/card-event"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

mkdir -p "$W/card" "$W/storage" "$W/logs"
cat > "$W/fstrim" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_LOG"
case "$FAKE_MODE" in
ok) echo "/storage: 1.2 GiB (1288490188 bytes) trimmed on /dev/mmcblk0p3" ;;
busybox) echo "/storage: 4096 bytes trimmed" ;;
fail) echo "fstrim: /storage: the discard operation is not supported" >&2; exit 1 ;;
slow) sleep 3; echo "/storage: 10 bytes trimmed" ;;
esac
EOF
printf '#!/bin/sh\nexit 0\n' > "$W/mountpoint"
printf '#!/bin/sh\nexit 1\n' > "$W/nomount"
chmod +x "$W/fstrim" "$W/mountpoint" "$W/nomount"
export CARD_LIBDIR="$LIB" CARD_DIR="$W/card" CARD_STORAGE="$W/storage" CARD_TRIM_PID="$W/trim.pid" \
	FSTRIM="$W/fstrim" MOUNTPOINT="$W/mountpoint" LOGS_RAM="$W/logs" FAKE_LOG="$W/fstrim.log" FAKE_MODE=ok
echo 150 > "$W/logs/boot-n"
: > "$FAKE_LOG"
events() { cat "$W/logs/events.pending" 2>/dev/null; }
request() { : > "$W/card/$1"; $EV w "$W/card" "$1"; }   # the launcher creates, inotifyd calls
wait_status() {  # until the status is not "running" (up to 10 s)
	n=0
	while [ "$n" -lt 100 ] && { [ ! -f "$W/card/status" ] || [ "$(cat "$W/card/status")" = running ]; }; do
		sleep 0.1; n=$((n + 1))
	done
}

### trim, success: status running then ok <bytes>, last-trim with the boot, event, request gone
request trim
wait_status
check "trim: status is ok with the bytes" '[ "$(cat "$W/card/status")" = "ok 1288490188" ]'
check "trim: fstrim -v on the storage" '[ "$(cat "$FAKE_LOG")" = "-v $W/storage" ]'
check "trim: last-trim holds the boot number" '[ "$(cat "$W/storage/system/card/last-trim")" = 150 ]'
check "trim: request file deleted" '[ ! -e "$W/card/trim" ]'
check "trim: event OK with the size" 'events | grep -q " 150 card OK trim: 1288490188 bytes trimmed$"'
check "trim: nothing left in the request folder but the status" '[ "$(ls -A "$W/card")" = status ]'

### busybox fstrim output
export FAKE_MODE=busybox
rm -f "$W/card/status"
request trim
wait_status
check "trim: busybox output parsed" '[ "$(cat "$W/card/status")" = "ok 4096" ]'

### the status is "running" while it works; a second request is deleted without running
rm -f "$W/card/status"
: > "$FAKE_LOG"
export FAKE_MODE=slow
request trim
sleep 0.5
check "double: status is running" '[ "$(cat "$W/card/status")" = running ]'
request trim
check "double: second request deleted" '[ ! -e "$W/card/trim" ]'
check "double: dropped event" 'events | grep -q " card FAIL trim: busy, request dropped$"'
wait_status
check "double: fstrim ran once" '[ "$(grep -c "" "$FAKE_LOG")" = 1 ]'
check "double: the first one finished ok" '[ "$(cat "$W/card/status")" = "ok 10" ]'
sleep 0.2
export FAKE_MODE=ok
rm -f "$W/card/status"
request trim
wait_status
check "double: a new request runs after the first ended" '[ "$(cat "$W/card/status")" = "ok 1288490188" ]'

### trim, failure: fail <reason>, no new last-trim, FAIL event
echo 151 > "$W/logs/boot-n"
export FAKE_MODE=fail
rm -f "$W/card/status"
request trim
wait_status
check "fail: status has the reason" '[ "$(cat "$W/card/status")" = "fail fstrim: /storage: the discard operation is not supported" ]'
check "fail: last-trim untouched" '[ "$(cat "$W/storage/system/card/last-trim")" = 150 ]'
check "fail: failure event" 'events | grep -q " 151 card FAIL trim: fstrim: /storage: the discard operation is not supported$"'

### no games partition
rm -f "$W/card/status"
export MOUNTPOINT="$W/nomount"
request trim
wait_status
export MOUNTPOINT="$W/mountpoint"
check "no storage: fail status" '[ "$(cat "$W/card/status")" = "fail no games partition" ]'

### check-next-boot
echo 152 > "$W/logs/boot-n"
request check-next-boot
check "check: marker holds the boot number" '[ "$(cat "$W/storage/system/card/check-next-boot")" = 152 ]'
check "check: status ok" '[ "$(cat "$W/card/status")" = ok ]'
check "check: request deleted" '[ ! -e "$W/card/check-next-boot" ]'
check "check: event OK" 'events | grep -q " 152 card OK check-next-boot: requested for the next boot$"'

### unknown verb: deleted and logged as refused (name sanitized), nothing run
: > "$FAKE_LOG"
echo ok > "$W/card/status"
request reboot
request 'a b;rm'
check "unknown: files deleted" '[ ! -e "$W/card/reboot" ] && [ ! -e "$W/card/a b;rm" ]'
check "unknown: logged as refused" 'events | grep -q " card FAIL refused request: reboot$"'
check "unknown: name sanitized" 'events | grep -q " card FAIL refused request: a?b?rm$"'
check "unknown: fstrim not run, status untouched" '[ ! -s "$FAKE_LOG" ] && [ "$(cat "$W/card/status")" = ok ]'

### the service's own files are not requests
$EV y "$W/card" status
$EV w "$W/card" .status.tmp.1
check "own files: status kept" '[ "$(cat "$W/card/status")" = ok ]'

### the daemon: folder, stale status, and the pending request; inotifyd blocks, so it runs 1 s
rm -rf "$W/run"
mkdir -p "$W/run/card"
echo running > "$W/run/card/status"
: > "$W/run/card/check-next-boot"
CARD_DIR="$W/run/card" CARD_GROUP=root CARD_HANDLER="$PWD/aports/lume-saves/files/usr/libexec/lume/card-event" \
	timeout 1 busybox sh aports/lume-saves/files/usr/libexec/lume/card > /dev/null 2>&1
check "daemon: stale running status replaced by the pending request's" '[ "$(cat "$W/run/card/status")" = ok ]'
check "daemon: folder is group-writable" '[ "$(stat -c %a "$W/run/card")" = 775 ]'

check "service: in the default runlevel" 'grep -q "lume-card dbus" rootfs/configure.sh'
check "service: after the frontend" 'grep -q "after lume-persist frontend" aports/lume-saves/files/etc/init.d/lume-card'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
