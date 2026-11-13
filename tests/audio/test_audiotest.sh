#!/bin/sh
# r36s-single-card, task 4.6 (bring-up): the audio rate test runs only with the flag file,
# measures the drain time of aplay from the uptime and plays the 440 Hz tone. Runs in
# busybox with fake aplay, speaker-test and uptime.
set -u
cd "$(dirname "$0")/../.."
AT="busybox sh rootfs/overlay/usr/libexec/r36os/audiotest"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

# fake aplay: logs its arguments and moves the uptime forward by FAKE_PLAY seconds
cat > "$W/aplay" <<'EOF'
#!/bin/sh
echo "$*" >> "$FAKE_LOG"
read -r u _ < "$UPTIME_FILE"
awk -v u="$u" -v d="$FAKE_PLAY" 'BEGIN { printf "%.2f 0.00\n", u + d }' > "$UPTIME_FILE"
exit "${FAKE_RC:-0}"
EOF
cat > "$W/speaker-test" <<'EOF'
#!/bin/sh
echo "speaker-test $*" >> "$FAKE_LOG"
EOF
chmod +x "$W/aplay" "$W/speaker-test"
export APLAY="$W/aplay" SPEAKER_TEST="$W/speaker-test" UPTIME_FILE="$W/uptime" \
	FAKE_LOG="$W/log" AUDIOTEST_FLAG="$W/flag" KMSG="$W/none" AUDIOTEST_TONE=0

### without the flag: nothing runs
echo "20.00 0.00" > "$W/uptime"
: > "$W/log"
out=$($AT)
check "no flag: no output and no aplay" '[ -z "$out" ] && [ ! -s "$W/log" ]'

### with the flag: 10 s of frames drained in 10.47 s is a 4.5% slow clock
touch "$W/flag"
export FAKE_PLAY=10.47
out=$($AT)
check "flag: raw silence straight to hw:0,0 at 48000 Hz, 10 s" \
	'grep -qxF -e "-q -D hw:0,0 -t raw -f S16_LE -r 48000 -c 2 -d 10 /dev/zero" "$W/log"'
check "flag: S16_LE and S32_LE both measured" '[ "$(grep -c "^-q -D hw:0,0" "$W/log")" = 2 ]'
check "flag: real rate from the drain time" \
	'printf "%s\n" "$out" | grep -qxF "audiotest: S16_LE 10 s of frames played in 10.47 s: real rate 45845 frames/s (-4.5%)"'
check "flag: the 440 Hz tone through the plug device" 'grep -q "^speaker-test -D plughw:0,0 -r 48000 -c 2 -t sine -f 440" "$W/log"'
check "flag: ends with done" 'printf "%s\n" "$out" | tail -n 1 | grep -qx "audiotest: done"'

### aplay failing is reported with its error
export FAKE_RC=1
out=$($AT)
check "aplay error: reported with its error" 'printf "%s\n" "$out" | grep -q "^audiotest: S16_LE FAILED"'
unset FAKE_RC

check "service: enabled only on the R36S" 'grep -q "add r36os-audiotest default" rootfs/configure.sh'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
