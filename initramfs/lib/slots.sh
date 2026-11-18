# Reader of the slot manifest <console>/SLOTS on BOOT (build-speed D9), for the init.
# Needs the log() of storage.sh. The format (also read and written by
# src/lume_tool/manifests.py, which accepts exactly the same lines):
#
#   lume-slots 1
#   build <build id>
#   console <console>
#   slot <name> slot/<name>-<sha12> <sha256> <bytes> <lower|->
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
	if ($3 != "slot/" n "-" substr($4, 1, 12)) bad("line " NR ": slot " n " has file " $3)
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

# ---- Mounting the root (build-speed 4.5) -------------------------------------------------
#
# The init calls mount_root once, after select_dtb. With a usable slot set the root is
# lume:runtime:base (read-only squashfs slots) under the 32 MiB RAM layer and the modules
# slot goes on /lib/modules. Fallback chain, each step with an ERROR line in the log:
#   SLOTS -> SLOTS.old -> the old <console>/SYSTEM -> rescue (emergency shell).
# A set that fails to mount (squashfs error, no loop device, bad file) is undone entirely
# before the next step: nothing half-built is left on the mount points.

# Mount points of the set being tried, the newest first (slots_undo unmounts in that order).
SLOTS_MOUNTED=""

# Unmount every mount of the set being tried.
slots_undo() {
	local m
	for m in $SLOTS_MOUNTED; do
		umount "$m" 2>/dev/null || umount -l "$m" 2>/dev/null \
			|| log "ERROR: failed to unmount $m"
	done
	SLOTS_MOUNTED=""
}

# Packages of slot $3 in manifest $2 (on the BOOT at $1) as "<package>-<version>" lines of
# at most about 400 characters (a /dev/kmsg record holds about 1 KiB).
_slots_pkg_lines() {
	awk -v s="$3" '
		$1 == "pkg" && $2 == s {
			p = $3 "-" $4
			if (line != "" && length(line) + length(p) > 400) { print line; line = "" }
			line = line (line == "" ? "" : " ") p
		}
		END { if (line != "") print line }' "$1/$2"
}

# Log the slots of manifest $2 (on the BOOT at $1) and their package versions.
slots_log() {
	local name file sha n line
	log "slots: $2 (build $(slots_build "$1" "$2"))"
	while read -r name file sha; do
		[ -n "$name" ] || continue
		n=$(awk -v s="$name" '$1 == "pkg" && $2 == s { n++ } END { print n + 0 }' "$1/$2")
		log "slot $name: $file (packages: $n)"
		while read -r line; do
			[ -n "$line" ] && log "slot $name packages: $line"
		done <<EOF
$(_slots_pkg_lines "$1" "$2" "$name")
EOF
	done <<EOF
$(slots_list "$1" "$2" overlay)
$(slots_list "$1" "$2" modules)
EOF
}

# Try the slot set of manifest $2 (on the BOOT at $1): each overlay slot on $3/<name>, the
# RAM layer on $4, the overlay on $5 and the modules slot on $6. On success sets
# SLOTS_MODULES (BOOT path of the modules slot, still mounted on $6). On any failure logs an
# ERROR line, undoes every mount it made and fails.
slots_try() {
	local boot="$1" man="$2" dir="$3" rw="$4" root="$5" mod="$6" name file sha lower
	SLOTS_MOUNTED=""
	SLOTS_MODULES=""
	while read -r name file sha; do
		[ -n "$name" ] || continue
		mkdir -p "$dir/$name"
		if ! mount -t squashfs -o ro,loop "$boot/$file" "$dir/$name" </dev/null; then
			log "ERROR: failed to mount slot $name ($file) of $man"
			slots_undo
			return 1
		fi
		SLOTS_MOUNTED="$dir/$name $SLOTS_MOUNTED"
	done <<EOF
$(slots_list "$boot" "$man" overlay)
EOF
	lower=$(slots_lowerdir "$boot" "$man" "$dir")
	case "$lower" in
	"$dir/lume:$dir/runtime:$dir/base") ;;
	*)
		log "ERROR: $man gives the overlay lowerdir \"$lower\""
		slots_undo
		return 1
		;;
	esac
	if ! mount -t tmpfs -o size=32m,mode=0755 tmpfs "$rw"; then
		log "ERROR: failed to mount the RAM layer for $man"
		slots_undo
		return 1
	fi
	SLOTS_MOUNTED="$rw $SLOTS_MOUNTED"
	mkdir -p "$rw/upper" "$rw/work"
	if ! mount -t overlay overlay -o "lowerdir=$lower,upperdir=$rw/upper,workdir=$rw/work" "$root"; then
		log "ERROR: failed to mount the overlay of $man"
		slots_undo
		return 1
	fi
	SLOTS_MOUNTED="$root $SLOTS_MOUNTED"
	set -- $(slots_list "$boot" "$man" modules)
	mkdir -p "$mod"
	if [ -z "${2:-}" ] || ! mount -t squashfs -o ro,loop "$boot/$2" "$mod"; then
		log "ERROR: failed to mount slot modules (${2:-none}) of $man"
		slots_undo
		return 1
	fi
	SLOTS_MOUNTED=""
	SLOTS_MODULES=$2
}

# Root of console $2 from its slot set on the BOOT at $1 (build-speed D9): slots on $3/<name>,
# RAM layer on $4, overlay on $5, modules slot through $6 on $5/lib/modules. Fails, with
# nothing left mounted, on the vm, on an old card (no SLOTS nor SLOTS.old: nothing logged)
# and when no set mounts (ERROR lines): the caller then mounts the old <console>/SYSTEM.
slots_mount_root() {
	local boot="$1" console="$2" man why
	case "$console" in ""|vm) return 1 ;; esac
	if ! man=$(slots_pick "$boot" "$console"); then
		if [ -e "$boot/$console/SLOTS" ] || [ -e "$boot/$console/SLOTS.old" ]; then
			log "ERROR: no slot set of $console to mount; trying the old $console/SYSTEM"
		fi
		return 1
	fi
	if ! slots_try "$boot" "$man" "$3" "$4" "$5" "$6"; then
		if [ "$man" != "$console/SLOTS" ]; then
			log "ERROR: $man could not be mounted; trying the old $console/SYSTEM"
			return 1
		fi
		if ! why=$(slots_check "$boot" "$console" SLOTS.old); then
			log "ERROR: $man could not be mounted and $console/SLOTS.old $why; trying the old $console/SYSTEM"
			return 1
		fi
		log "ERROR: $man could not be mounted; using $console/SLOTS.old from the previous build"
		man=$console/SLOTS.old
		if ! slots_try "$boot" "$man" "$3" "$4" "$5" "$6"; then
			log "ERROR: $man could not be mounted either; trying the old $console/SYSTEM"
			return 1
		fi
	fi
	slots_log "$boot" "$man"
	log "root: $man (lume, runtime, base; read-only) + 32 MiB RAM layer"
	modules_attach "$SLOTS_MODULES" "$6" "$5"
}

# Root of console $1 on $6, from the BOOT mounted at $2: the slot set (slots_mount_root, slots
# on $3/<name>) or, without one, the old <console>/SYSTEM on $4 exactly as before the slots;
# RAM layer on $5, kernel modules through $7. Calls the init's rescue() when no root mounts.
mount_root() {
	local board="$1" boot="$2" slots="$3" lower="$4" rw="$5" root="$6" mod="$7" system file
	slots_mount_root "$boot" "$board" "$slots" "$rw" "$root" "$mod" && return 0
	system=$(system_file "$board")
	# Never falls back to the SYSTEM of another console (another architecture); only to the
	# SYSTEM.old of this one, the previous build left by a push cut between its two renames
	file=$(boot_file "$boot" "$system") || {
		rescue "BOOT has no $system, the system of the $(console_label "$board"); write the card again with the console image"
		return 1
	}
	mount -t squashfs -o ro,loop "$boot/$file" "$lower" || { rescue "failed to mount $file"; return 1; }
	mount -t tmpfs -o size=32m,mode=0755 tmpfs "$rw"
	mkdir -p "$rw/upper" "$rw/work"
	mount -t overlay overlay -o "lowerdir=$lower,upperdir=$rw/upper,workdir=$rw/work" "$root" \
		|| { rescue "failed to mount overlay"; return 1; }
	log "root: $file (read-only) + 32 MiB RAM layer"
	# Kernel modules of this console (kernel-modules-image D4): BOOT/<console>/modules on
	# /lib/modules of the new root. After select_dtb: an open loop on BOOT would stop the
	# umount before the kexec.
	mount_modules "$board" "$boot" "$mod" "$root"
}
