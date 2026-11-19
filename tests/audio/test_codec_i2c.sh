#!/bin/sh
# codec-i2c (P-45): guarded RK817 codec access. Runs in busybox (builder container) with fake
# i2cget/i2cset that keep the registers in files, one per register.
set -u
cd "$(dirname "$0")/../.."
TOOL="busybox sh aports/lume-diag/files/usr/libexec/lume/codec-i2c"
W=$(mktemp -d)
FAILS=0
check() { if eval "$2"; then echo "PASS $1"; else echo "FAIL $1"; FAILS=$((FAILS + 1)); fi; }

mkdir -p "$W/regs" "$W/bat"
echo -306000 > "$W/bat/current_avg"
cat > "$W/i2cget" <<'EOF'
#!/bin/sh
# i2cget -f -y <bus> <addr> <reg>
echo "get $*" >> "$LOG"
f="$REGS/$5"
[ -f "$f" ] && cat "$f" || echo 0x00
EOF
cat > "$W/i2cset" <<'EOF'
#!/bin/sh
# i2cset -f -y <bus> <addr> <reg> <value>; register 0x41 keeps only bits 0-6 (self-clearing
# bit 7, like the class D restart bit of the chip)
echo "set $*" >> "$LOG"
v=$6
[ "$5" = 0x41 ] && v=$(printf '0x%02x' $(( $6 & 0x7f )))
echo "$v" > "$REGS/$5"
EOF
chmod 755 "$W/i2cget" "$W/i2cset"
export I2CGET="$W/i2cget" I2CSET="$W/i2cset" REGS="$W/regs" LOG="$W/log" BATTERY="$W/bat"
echo 0x0f > "$W/regs/0x3e"
echo 0x4c > "$W/regs/0x41"

: > "$LOG"
out=$($TOOL get 0x3e)
check "get: prints the register" '[ "$out" = 0x0f ]'
check "get: forced read of bus 0, address 0x20" 'grep -qx "get -f -y 0 0x20 0x3e" "$LOG"'

out=$($TOOL set 0x3e 0x1f)
check "set: writes and prints the value read back" '[ "$out" = 0x1f ] && [ "$(cat "$W/regs/0x3e")" = 0x1f ]'
out=$($TOOL set 0x41 0xf7)
check "set: the read back shows bits the chip did not keep" '[ "$out" = 0x77 ]'

: > "$LOG"
out=$($TOOL set 0x05 0x00 2>&1)
rc=$?
check "set: a PMIC register is refused with exit 2" '[ "$rc" = 2 ]'
check "set: the refusal names the codec range" 'printf "%s" "$out" | grep -q "outside the codec range 0x12-0x4f"'
check "set: nothing is written outside the range" '! grep -q "^set" "$LOG"'
$TOOL set 0x11 0x00 >/dev/null 2>&1
check "set: 0x11, just below the range, is refused" '[ "$?" = 2 ]'
$TOOL set 0x50 0x00 >/dev/null 2>&1
check "set: 0x50, just above the range, is refused" '[ "$?" = 2 ]'
$TOOL set 0x12 0x03 >/dev/null 2>&1
check "set: 0x12, the first codec register, is accepted" '[ "$?" = 0 ]'
$TOOL set 0x4f 0x00 >/dev/null 2>&1
check "set: 0x4f, the last codec register, is accepted" '[ "$?" = 0 ]'
$TOOL set 0x3e 0x1ff >/dev/null 2>&1
check "set: a value above one byte is refused" '[ "$?" = 1 ]'
$TOOL get zz >/dev/null 2>&1
check "get: a bad register is refused" '[ "$?" = 1 ]'

echo 0x0f > "$W/regs/0x3e"
out=$($TOOL try 0x3e 0x1f 0)
check "try: the old value is written back" '[ "$(cat "$W/regs/0x3e")" = 0x0f ]'
check "try: the report has the old, written, read back and current values" \
	'[ "$out" = "reg 0x3e: was 0x0f, wrote 0x1f, read back 0x1f, battery current -306000 uA, restored 0x0f" ]'
: > "$LOG"
$TOOL try 0x05 0x00 0 >/dev/null 2>&1
check "try: a PMIC register is refused with exit 2" '[ "$?" = 2 ] && ! grep -q "^set -f -y 0 0x20 0x05" "$LOG"'

out=$($TOOL dump)
check "dump: 62 codec registers, 0x12 to 0x4f" '[ "$(printf "%s\n" "$out" | grep -c "")" = 62 ] && printf "%s\n" "$out" | head -1 | grep -qx "12: 0x03"'

rm -rf "$W"
echo "failures: $FAILS"
[ "$FAILS" -eq 0 ]
