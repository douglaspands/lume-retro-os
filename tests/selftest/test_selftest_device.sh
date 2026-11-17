#!/bin/sh
# Device mode of the self-test (build-speed 3.2): `selftest device` on a fake console. Runs in
# busybox (builder container, as root); the system facts (mounts, services, processes) are
# plain files and stub functions, so each scenario breaks one thing on purpose.
set -u
cd "$(dirname "$0")/../.."
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

LIBDIR=$PWD/rootfs/overlay/usr/libexec/r36os
export R36OS_LIBDIR=$LIBDIR SELFTEST_DEVICE_SOURCE=1

# One healthy console in $W; a scenario function may then break it
fake_console() {  # board
	rm -rf "$W/c"; mkdir -p "$W/c/run/logs/boot" "$W/c/logs/boot" "$W/c/logs/hw" \
		"$W/c/logs/metrics" "$W/c/logs/frontend" "$W/c/cg/lume"
	echo "$1" > "$W/c/board"
	echo "/dev/mmcblk0p3 /storage exfat rw,noatime 0 0" > "$W/c/mounts"
	echo "overlay / overlay rw,lowerdir=/lower,upperdir=/rw/upper 0 0" >> "$W/c/mounts"
	printf 'Filename Type Size Used Priority\n/dev/zram0 partition 32767 0 100\n' > "$W/c/swaps"
	printf '  video     ok      sun4i-drm\n  audio     ok      rk817\n  battery   ok      80%%\n' > "$W/c/hwsummary"
	echo 7 > "$W/c/run/logs/boot-n"
	: > "$W/c/run/logs/boot/boot-7.log"
	echo "1700000000 7 boot OK completed: 9s" > "$W/c/logs/events.log"
	: > "$W/c/cg/lume/cgroup.kill"
	echo "Jan  9 04:24:48 lumeretro user.notice lume-index: lume-index: scan systems=16 games=33 added=0 failed=0 ms=370" > "$W/c/messages"
	pad=""
	case "$1" in
	ga36) pad="GA36-MB Gamepad" ;;
	r36s) pad="R36S Gamepad" ;;
	esac
	printf 'I: Bus=0006 Vendor=0 Product=0 Version=0\nN: Name="%s"\nH: Handlers=js0 event3\n\n' "$pad" > "$W/c/input"
	STOPPED=""
}

# Runs the device mode in a subshell: stdout in $W/out, exit code in RC
run_device() {
	(
		. "$LIBDIR/selftest-device"
		BOARD_FILE=$W/c/board PROC_MOUNTS=$W/c/mounts PROC_SWAPS=$W/c/swaps
		INPUT_DEVICES=$W/c/input HWSUMMARY=$W/c/hwsummary LOGS=$W/c/logs CGROUP_ROOT=$W/c/cg
		R36OS_RUN=$W/c/run SYSLOG=$W/c/messages
		svc_up() { ! echo " $STOPPED " | grep -q " $1 "; }
		svc_state() { if svc_up "$1"; then echo started; else echo stopped; fi; }
		pidof() { case "$1" in lume-run) echo 100 ;; lume-ui) echo 101 ;; r36os-input) echo 50 ;; *) return 1 ;; esac; }
		uid_of() { echo 1000; }
		stat() { echo game; }
		dmesg() { echo "lume: frontend started: lume"; }
		device_run
	) > "$W/out" 2>&1
	RC=$?
}

### healthy consoles pass, and the summary names the board
for b in ga36 r36s; do
	fake_console "$b"; run_device
	check "$b healthy: exit 0" '[ $RC = 0 ]'
	check "$b healthy: summary line names the board and no failure" 'grep -qE "^SELFTEST-DONE board=$b pass=[0-9]+ fail=0$" "$W/out"'
	check "$b healthy: no failed line" '! grep -q "^SELFTEST .* FAIL" "$W/out"'
done
check "r36s checks the jack service, ga36 does not" 'grep -q "service-r36os-jack PASS" "$W/out" && fake_console ga36 && run_device && ! grep -q "service-r36os-jack" "$W/out"'

### a stopped service fails its own check and nothing else
fake_console r36s; STOPPED="networkmanager"; run_device
check "stopped service: exit 1" '[ $RC = 1 ]'
check "stopped service: names the check" 'grep -q "^SELFTEST service-networkmanager FAIL stopped$" "$W/out"'
check "stopped service: the only failure" '[ "$(grep -c "^SELFTEST .* FAIL" "$W/out")" = 1 ] && grep -q "fail=1$" "$W/out"'

### lume-index is a background scan: done and "crashed" in OpenRC is fine, failures are not
fake_console ga36; STOPPED="lume-index"; run_device
check "finished scan: no service check for lume-index, scan check passes" '[ $RC = 0 ] && ! grep -q "service-lume-index" "$W/out" && grep -q "^SELFTEST lume-index-scan PASS scan systems=16" "$W/out"'
fake_console ga36; sed -i "s/failed=0/failed=2/" "$W/c/messages"; run_device
check "scan with failed systems: lume-index-scan fails" '[ $RC = 1 ] && grep -q "^SELFTEST lume-index-scan FAIL" "$W/out"'
fake_console ga36; : > "$W/c/messages"; run_device
check "no scan line and no scan running: lume-index-scan fails" '[ $RC = 1 ] && grep -q "^SELFTEST lume-index-scan FAIL" "$W/out"'

### the boot did not finish
fake_console ga36; echo "1700000000 7 boot FAIL timeout" > "$W/c/logs/events.log"; run_device
check "boot not completed: boot-completed fails" '[ $RC = 1 ] && grep -q "^SELFTEST boot-completed FAIL" "$W/out"'

### a hardware item failed in the summary
fake_console ga36; printf '  video     fail    no /dev/dri/card0\n' > "$W/c/hwsummary"; run_device
check "hwsummary fail: hwsummary fails with the item" '[ $RC = 1 ] && grep -q "^SELFTEST hwsummary FAIL .*video fail" "$W/out"'

### the games partition is not mounted
fake_console r36s; : > "$W/c/mounts"; run_device
check "no /storage: roms-mounted fails" 'grep -q "^SELFTEST roms-mounted FAIL" "$W/out"'

### the frontend died
fake_console ga36
(
	. "$LIBDIR/selftest-device"
	BOARD_FILE=$W/c/board PROC_MOUNTS=$W/c/mounts PROC_SWAPS=$W/c/swaps INPUT_DEVICES=$W/c/input
	HWSUMMARY=$W/c/hwsummary LOGS=$W/c/logs CGROUP_ROOT=$W/c/cg R36OS_RUN=$W/c/run
	svc_up() { return 0; }; svc_state() { echo started; }; uid_of() { echo 1000; }
	stat() { echo game; }; dmesg() { :; }
	pidof() { case "$1" in r36os-input) echo 50 ;; *) return 1 ;; esac; }
	device_run
) > "$W/out" 2>&1
RC=$?
check "frontend gone: frontend-up and frontend-not-root fail" '[ $RC = 1 ] && grep -q "^SELFTEST frontend-up FAIL" "$W/out" && grep -q "^SELFTEST frontend-not-root FAIL" "$W/out"'

### the VM has its own self-test: device mode refuses it
fake_console vm; echo vm > "$W/c/board"; run_device
check "vm: refused with exit 2" '[ $RC = 2 ] && grep -q "^SELFTEST-ERROR" "$W/out" && ! grep -q "^SELFTEST-DONE" "$W/out"'

### the dispatcher: `selftest device` hands over to selftest-device, other modes are unchanged
check "selftest dispatches device mode first" 'sed -n "/^\[ \"\$1\" = device \]/=" rootfs/overlay/usr/libexec/r36os/selftest | grep -q . && [ "$(grep -n "exec /usr/libexec/r36os/selftest-device" rootfs/overlay/usr/libexec/r36os/selftest | cut -d: -f1)" -lt "$(grep -n "^T=" rootfs/overlay/usr/libexec/r36os/selftest | cut -d: -f1)" ]'
check "selftest still runs the phases" 'grep -q "^run)" rootfs/overlay/usr/libexec/r36os/selftest'

rm -rf "$W"
[ "$FAILS" -eq 0 ]
