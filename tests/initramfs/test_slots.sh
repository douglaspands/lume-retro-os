#!/bin/busybox sh
# Tests of the SLOTS reader of the initramfs (build-speed 4.0, D9) on a fake BOOT.
# Runs in the builder container: busybox sh tests/initramfs/test_slots.sh
set -u
cd "$(dirname "$0")"
. ../../initramfs/lib/storage.sh
. ../../initramfs/lib/slots.sh
export TMPDIR=$(mktemp -d)
W=$TMPDIR
FAILS=0
ok()   { echo "PASS $1"; }
fail() { echo "FAIL $1"; FAILS=$((FAILS + 1)); }
check() { if eval "$2"; then ok "$1"; else fail "$1"; fi; }

# a fake sha256 made of one repeated hex digit
sha() { printf "%064d" 0 | tr 0 "$1"; }
B=$(sha b); R=$(sha c); L=$(sha d); M=$(sha e); C=$(sha f)
b12=$(echo "$B" | cut -c1-12); r12=$(echo "$R" | cut -c1-12)
l12=$(echo "$L" | cut -c1-12); m12=$(echo "$M" | cut -c1-12); c12=$(echo "$C" | cut -c1-12)

# a good manifest of console $1 (the same text manifests.format_slots writes)
good() {
	printf '%s\n' \
		"lume-slots 1" \
		"build 20261116-214233" \
		"console $1" \
		"slot base slots/base-$b12 $B 1000 -" \
		"pkg base musl 1.2.5-r10" \
		"pkg base busybox 1.37.0-r20" \
		"slot runtime slots/runtime-$r12 $R 2000 base=$B" \
		"slot lume slots/lume-$l12 $L 3000 base=$B,runtime=$R" \
		"pkg lume lume-core 1.0-r3" \
		"slot modules slots/modules-$m12 $M 4000 -" \
		"slot core-snes9x slots/core-snes9x-$c12 $C 5000 base=$B,runtime=$R" \
		"end 5 3"
}
# BOOT with the slot files of the good manifest for console $1
mkboot() {
	rm -rf "$W/boot"
	mkdir -p "$W/boot/$1/slots"
	for f in base-$b12 runtime-$r12 lume-$l12 modules-$m12 core-snes9x-$c12; do
		: > "$W/boot/$1/slots/$f"
	done
}
D=$W/boot/ga36

### 1. Good SLOTS
mkboot ga36
good ga36 > "$D/SLOTS"
check "good: check passes" 'slots_check "$W/boot" ga36 SLOTS >/dev/null'
check "good: picks SLOTS, nothing logged" '[ "$(slots_pick "$W/boot" ga36 2>"$W/l1")" = ga36/SLOTS ] && [ ! -s "$W/l1" ]'
check "good: overlay in mount order" '[ "$(slots_list "$W/boot" ga36/SLOTS overlay | cut -d" " -f1 | tr "\n" " ")" = "base runtime lume " ]'
check "good: overlay paths" 'slots_list "$W/boot" ga36/SLOTS overlay | grep -qx "lume ga36/slots/lume-$l12 $l12"'
check "good: lowerdir top first" '[ "$(slots_lowerdir "$W/boot" ga36/SLOTS /slots)" = /slots/lume:/slots/runtime:/slots/base ]'
check "good: modules slot" '[ "$(slots_list "$W/boot" ga36/SLOTS modules)" = "modules ga36/slots/modules-$m12 $m12" ]'
check "good: cores" '[ "$(slots_list "$W/boot" ga36/SLOTS cores | cut -d" " -f1)" = core-snes9x ]'
check "good: all slots" '[ "$(slots_list "$W/boot" ga36/SLOTS | wc -l)" -eq 5 ]'
check "good: packages of a slot" '[ "$(slots_packages "$W/boot" ga36/SLOTS base)" = "musl-1.2.5-r10 busybox-1.37.0-r20" ]'
check "good: build id" '[ "$(slots_build "$W/boot" ga36/SLOTS)" = 20261116-214233 ]'

### 2. SLOTS missing (push cut between its two renames): SLOTS.old with an ERROR
mv "$D/SLOTS" "$D/SLOTS.old"
check "missing: picks SLOTS.old" '[ "$(slots_pick "$W/boot" ga36 2>"$W/l2")" = ga36/SLOTS.old ]'
check "missing: ERROR logged" 'grep -qx "lume: ERROR: ga36/SLOTS is missing; using ga36/SLOTS.old from the previous build" "$W/l2"'
check "missing: SLOTS.old lists its slots" '[ "$(slots_list "$W/boot" ga36/SLOTS.old overlay | wc -l)" -eq 3 ]'

### 3. Truncated SLOTS: falls back to SLOTS.old
good ga36 | head -n 7 > "$D/SLOTS"
check "truncated (whole lines): reason" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "is truncated (no end line)" ]'
check "truncated (whole lines): picks SLOTS.old" '[ "$(slots_pick "$W/boot" ga36 2>"$W/l3")" = ga36/SLOTS.old ]'
check "truncated (whole lines): ERROR logged" 'grep -qx "lume: ERROR: ga36/SLOTS is truncated (no end line); using ga36/SLOTS.old from the previous build" "$W/l3"'
good ga36 | head -c 300 > "$D/SLOTS"
check "truncated (mid line): reason" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "is truncated (no newline at the end)" ]'
check "truncated (mid line): picks SLOTS.old" '[ "$(slots_pick "$W/boot" ga36 2>/dev/null)" = ga36/SLOTS.old ]'
good ga36 | sed '/^pkg lume/d' > "$D/SLOTS"
check "lost line: end counts differ" 'slots_check "$W/boot" ga36 SLOTS | grep -q "^is truncated or garbled"'
: > "$D/SLOTS"
check "empty: refused" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "is empty" ]'

### 4. Garbled SLOTS
good ga36 | sed "s/ $R 2000 / $(sha C) 2000 /" > "$D/SLOTS"
check "garbled: bad sha256" 'slots_check "$W/boot" ga36 SLOTS | grep -q "line 7: bad sha256 of slot runtime"'
good ga36 | sed "s/runtime=$R/runtime=$(sha a)/" > "$D/SLOTS"
check "garbled: incoherent lower slot" 'slots_check "$W/boot" ga36 SLOTS | grep -q "incoherent set"'
good ga36 | sed "s|slots/lume-$l12|slots/lume-$b12|" > "$D/SLOTS"
check "garbled: file not named by its sha" 'slots_check "$W/boot" ga36 SLOTS | grep -q "slot lume has file"'
good ga36 | sed 's/^lume-slots 1$/lume-slots 2/' > "$D/SLOTS"
check "garbled: other format" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "is not a SLOTS manifest of format 1" ]'
good r36s > "$D/SLOTS"
check "garbled: other console" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "is for console r36s" ]'
good ga36 | sed 's/^slot base \(.*\)$/slot  base \1/' > "$D/SLOTS"
check "garbled: double space" 'slots_check "$W/boot" ga36 SLOTS | grep -q "line 4: unknown line"'
good ga36 | sed '/^slot modules/d; s/^end 5 3$/end 4 3/' > "$D/SLOTS"
check "garbled: no modules slot" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "has no modules slot" ]'
good ga36 > "$D/SLOTS"; echo "slot extra" >> "$D/SLOTS"
check "garbled: text after end" 'slots_check "$W/boot" ga36 SLOTS | grep -q "text after the end line"'

### 5. SLOTS cites a missing slot file: falls back to SLOTS.old
good ga36 > "$D/SLOTS"
mv "$D/slots/runtime-$r12" "$W/runtime"
check "missing file: reason" '[ "$(slots_check "$W/boot" ga36 SLOTS)" = "cites a missing file ga36/slots/runtime-$r12" ]'
check "missing file: no set usable (old one shares it)" '! slots_pick "$W/boot" ga36 >/dev/null 2>"$W/l5"'
check "missing file: ERROR names both" 'grep -qx "lume: ERROR: ga36/SLOTS cites a missing file ga36/slots/runtime-$r12 and ga36/SLOTS.old cites a missing file ga36/slots/runtime-$r12; no slot set to mount" "$W/l5"'
mv "$W/runtime" "$D/slots/runtime-$r12"
# the new set has a new lume slot that was not copied; the old set is whole
N=$(sha 9); n12=$(echo "$N" | cut -c1-12)
good ga36 | sed "s/$L/$N/; s/lume-$l12/lume-$n12/" > "$D/SLOTS"
check "missing file: picks SLOTS.old" '[ "$(slots_pick "$W/boot" ga36 2>"$W/l6")" = ga36/SLOTS.old ]'
check "missing file: ERROR logged" 'grep -qx "lume: ERROR: ga36/SLOTS cites a missing file ga36/slots/lume-$n12; using ga36/SLOTS.old from the previous build" "$W/l6"'

### 6. Old card: neither SLOTS nor SLOTS.old, the caller mounts <console>/SYSTEM
mkboot ga36
: > "$D/SYSTEM"
check "old card: no set" '! slots_pick "$W/boot" ga36 >/dev/null 2>"$W/l7"'
check "old card: nothing logged" '[ ! -s "$W/l7" ]'
check "old card: SYSTEM still found" '[ "$(boot_file "$W/boot" "$(system_file ga36)" 2>/dev/null)" = ga36/SYSTEM ]'
check "other console: no set" '! slots_pick "$W/boot" r36s >/dev/null 2>&1'

### 7. Both broken: fails with one ERROR line
good ga36 | head -n 5 > "$D/SLOTS"
good ga36 | head -n 4 > "$D/SLOTS.old"
check "both broken: no set" '! slots_pick "$W/boot" ga36 >/dev/null 2>"$W/l8"'
check "both broken: one ERROR line" '[ "$(grep -c "^lume: ERROR: ga36/SLOTS is truncated (no end line) and ga36/SLOTS.old is truncated (no end line); no slot set to mount$" "$W/l8")" -eq 1 ]'

rm -rf "$W"
echo "failures: $FAILS"
[ $FAILS -eq 0 ]
