# Reader of the slot manifest <console>/SLOTS on BOOT (build-speed D9), for the init.
# Needs the log() of storage.sh. The format (also read and written by
# src/r36os/manifests.py, which accepts exactly the same lines):
#
#   lume-slots 1
#   build <build id>
#   console <console>
#   slot <name> slots/<name>-<sha12> <sha256> <bytes> <lower|->
#   pkg <slot> <package> <version>          (0 or more, right after their slot line)
#   ...
#   end <number of slot lines> <number of pkg lines>
#
# Slots in fixed order: base, runtime, lume, modules, then core-* by name. <lower> is
# "-" or "<slot>=<sha256>,..." (the slots below it was built against; they must be the
# ones of this set). Without the end line, or with other counts, the file is truncated.
# The sha256 of the slot files is not read at boot (the push checks it before the swap);
# only their presence is.

# Checks of the manifest text, run by awk. Prints nothing when the manifest is good, or
# one line with the reason.
_SLOTS_AWK='
function bad(m) { if (!err) print m; err = 1; exit }
function hex64(s) { return length(s) == 64 && s !~ /[^0-9a-f]/ }
function rank(n) {
	if (n == "base") return "0"; if (n == "runtime") return "1"
	if (n == "lume") return "2"; if (n == "modules") return "3"
	return "4" n
}
function word(s) { return s ~ /^[A-Za-z0-9][A-Za-z0-9_.+~-]*$/ }
BEGIN { nslot = 0; npkg = 0; ended = 0; err = 0; last = "" }
err { exit }
NR == 1 { if ($0 != "lume-slots 1") bad("is not a SLOTS manifest of format 1"); next }
NR == 2 { if (NF != 2 || $1 != "build" || !word($2) || $0 != $1 " " $2) bad("line 2: expected build <id>"); next }
NR == 3 {
	if (NF != 2 || $1 != "console" || $0 != $1 " " $2) bad("line 3: expected console <name>")
	if ($2 != console) bad("is for console " $2)
	next
}
ended { bad("line " NR ": text after the end line") }
$1 == "slot" && NF == 6 && $0 == $1 " " $2 " " $3 " " $4 " " $5 " " $6 {
	n = $2
	if (n !~ /^(base|runtime|lume|modules|core-[a-z0-9][a-z0-9_.+-]*)$/) bad("line " NR ": bad slot name")
	if (!hex64($4)) bad("line " NR ": bad sha256 of slot " n)
	if ($3 != "slots/" n "-" substr($4, 1, 12)) bad("line " NR ": slot " n " has file " $3)
	if ($5 !~ /^[0-9]+$/) bad("line " NR ": bad size of slot " n)
	if (last != "" && !(rank(n) > rank(last))) bad("line " NR ": slot " n " out of order")
	if ($6 != "-") {
		k = split($6, lw, ",")
		for (i = 1; i <= k; i++) {
			eq = index(lw[i], "=")
			ln = substr(lw[i], 1, eq - 1); ls = substr(lw[i], eq + 1)
			if (eq == 0 || !hex64(ls)) bad("line " NR ": bad lower slot of " n)
			if (!(ln in sha)) bad("line " NR ": slot " n " was built against " ln ", not a slot below it")
			if (sha[ln] != ls) bad("line " NR ": slot " n " was built against another " ln " (incoherent set)")
		}
	}
	sha[n] = $4; last = n; nslot++
	next
}
$1 == "pkg" && NF == 4 && $0 == $1 " " $2 " " $3 " " $4 {
	if ($2 != last) bad("line " NR ": pkg line of " $2 " not right after its slot line")
	if (!word($3) || !word($4)) bad("line " NR ": bad package")
	npkg++
	next
}
$1 == "end" && NF == 3 && $0 == $1 " " $2 " " $3 {
	if ($2 "" != nslot "" || $3 "" != npkg "") bad("is truncated or garbled (end counts " $2 " " $3 ", read " nslot " " npkg ")")
	ended = 1
	next
}
{ bad("line " NR ": unknown line") }
END {
	if (err) exit
	if (NR == 0) { print "is empty"; exit }
	if (!ended) { print "is truncated (no end line)"; exit }
	for (i = 1; i <= 4; i++) {
		n = i == 1 ? "base" : i == 2 ? "runtime" : i == 3 ? "lume" : "modules"
		if (!(n in sha)) { print "has no " n " slot"; exit }
	}
}'

# Is <console>/$3 (SLOTS or SLOTS.old) of the BOOT mounted at $1, for console $2, usable?
# Prints nothing and succeeds when it is; otherwise prints the reason ("is missing", "is
# truncated ...", "cites a missing file ...") and fails.
slots_check() {
	local boot="$1" console="$2" m="$1/$2/$3" why f
	if [ ! -f "$m" ]; then
		echo "is missing"
		return 1
	fi
	# a file cut in the middle of its last line has no final newline
	if [ -s "$m" ] && [ -n "$(tail -c 1 "$m")" ]; then
		echo "is truncated (no newline at the end)"
		return 1
	fi
	why=$(awk -v console="$console" "$_SLOTS_AWK" "$m")
	if [ -n "$why" ]; then
		echo "$why"
		return 1
	fi
	for f in $(awk '$1 == "slot" { print $3 }' "$m"); do
		if [ ! -f "$boot/$console/$f" ]; then
			echo "cites a missing file $console/$f"
			return 1
		fi
	done
}

# The manifest of console $2 to mount, on the BOOT mounted at $1: prints <console>/SLOTS,
# or <console>/SLOTS.old (with an ERROR line in the log) when SLOTS is missing, truncated or
# cites a missing slot file. Fails when neither is usable: the caller falls back to the old
# <console>/SYSTEM (an old card, with neither file, logs nothing here).
slots_pick() {
	local boot="$1" console="$2" why why_old
	if why=$(slots_check "$boot" "$console" SLOTS); then
		echo "$console/SLOTS"
		return 0
	fi
	if why_old=$(slots_check "$boot" "$console" SLOTS.old); then
		log "ERROR: $console/SLOTS $why; using $console/SLOTS.old from the previous build"
		echo "$console/SLOTS.old"
		return 0
	fi
	if [ -e "$boot/$console/SLOTS" ] || [ -e "$boot/$console/SLOTS.old" ]; then
		log "ERROR: $console/SLOTS $why and $console/SLOTS.old $why_old; no slot set to mount"
	fi
	return 1
}

# Slots of the manifest $2 (as printed by slots_pick, relative to the BOOT at $1), one per
# line: "<name> <BOOT path of the file> <sha12>". $3 picks which:
#   overlay  base, runtime, lume: the lowerdirs of the root in mount order (bottom first)
#   modules  the kernel modules slot
#   cores    the core-* slots, by name (mounted after the frontend, not at boot)
#   all      every slot, in manifest order (the default)
slots_list() {
	local dir
	dir=$(dirname "$2")
	awk -v dir="$dir" -v want="${3:-all}" '
		$1 != "slot" { next }
		want == "overlay" && $2 != "base" && $2 != "runtime" && $2 != "lume" { next }
		want == "modules" && $2 != "modules" { next }
		want == "cores" && $2 !~ /^core-/ { next }
		{ print $2, dir "/" $3, substr($4, 1, 12) }' "$1/$2"
}

# The overlay lowerdir option for the overlay slots of manifest $2 (on the BOOT at $1),
# each mounted at $3/<name>: top first, "$3/lume:$3/runtime:$3/base".
slots_lowerdir() {
	local out="" name rest
	while read -r name rest; do
		out="$3/$name${out:+:}$out"
	done <<EOF
$(slots_list "$1" "$2" overlay)
EOF
	echo "$out"
}

# Packages of slot $3 in manifest $2 (on the BOOT at $1), on one line as
# "<package>-<version> ...", for the boot log.
slots_packages() {
	echo $(awk -v s="$3" '$1 == "pkg" && $2 == s { print $3 "-" $4 }' "$1/$2")
}

# Build id of manifest $2 (on the BOOT at $1).
slots_build() {
	awk 'NR == 2 && $1 == "build" { print $2 }' "$1/$2"
}
