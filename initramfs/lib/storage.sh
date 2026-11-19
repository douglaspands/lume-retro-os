# Games partition logic (D6), shared by the init and the tests.
# Works on a real disk (/dev/mmcblk0, /dev/vda) or on an image file: on files, the
# operations on a partition use a temporary copy that is then written back at the
# right offset.
#
# Core rule: an existing partition 2 is never formatted, recreated or resized.

SECTOR=512
ALIGN=2048          # partitions aligned to 1 MiB
MIN_ROMS=131072     # ROMS is only created with at least 64 MiB free
: "${TMPDIR:=/tmp}"

# Messages go to the screen (stderr) and to dmesg, which ends up in the boot log.
log() { echo "lume: $*" >&2; [ -w /dev/kmsg ] && echo "lume: $*" > /dev/kmsg; return 0; }

# Block node of partition N (mmcblk0 -> mmcblk0p2, vda -> vda2).
part_node() {
	case "$1" in
	*[0-9]) echo "${1}p$2" ;;
	*) echo "$1$2" ;;
	esac
}

disk_sectors() {
	if [ -b "$1" ]; then
		cat "/sys/class/block/$(basename "$1")/size"
	else
		echo $(( $(wc -c < "$1") / SECTOR ))
	fi
}

# Field (start|size|type) of partition N, read from the table by sfdisk.
part_field() {
	sfdisk -d "$1" 2>/dev/null | awk -v n="$2" -v f="$3" '
		/ : start=/ { i++; if (i == n) {
			gsub(/ /, ""); sub(/^[^:]*:/, "")
			k = split($0, kv, ",")
			for (j = 1; j <= k; j++) { split(kv[j], p, "="); if (p[1] == f) print p[2] }
		} }'
}

has_part() { [ -n "$(part_field "$1" "$2" start)" ]; }

# File system type from the boot sector of the partition that starts at $2. "usbc": the
# sector holds a USB Mass Storage command block ("USBC" signature) instead of data, the
# mark of a faulty USB card reader (14cd:125d) that wrote its commands into the card.
fs_type_at() {
	local oem fat32
	if [ "$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 count=4 2>/dev/null)" = USBC ]; then
		echo usbc
		return
	fi
	oem=$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 skip=3 count=8 2>/dev/null | tr -d '\000')
	fat32=$(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 skip=82 count=8 2>/dev/null | tr -d '\000')
	case "$oem" in
	"EXFAT   ") echo exfat; return ;;
	"NTFS    ") echo ntfs; return ;;
	esac
	case "$fat32" in "FAT32   ") echo vfat; return ;; esac
	if [ -z "$(dd if="$1" bs=$SECTOR skip="$2" count=8 2>/dev/null | tr -d '\000')" ]; then
		echo empty
	else
		echo unknown
	fi
}

# First free aligned sector after partition 1.
free_start() {
	local s z
	s=$(part_field "$1" 1 start); z=$(part_field "$1" 1 size)
	echo $(( (s + z + ALIGN - 1) / ALIGN * ALIGN ))
}

# What to do with partition 2: create | check | usbc | foreign | nospace
decide_p2() {
	if ! has_part "$1" 2; then
		local start total
		start=$(free_start "$1"); total=$(disk_sectors "$1")
		if [ $(( total - start )) -ge $MIN_ROMS ]; then echo create; else echo nospace; fi
		return
	fi
	case "$(fs_type_at "$1" "$(part_field "$1" 2 start)")" in
	exfat) echo check ;;
	usbc) echo usbc ;;
	*) echo foreign ;;
	esac
}

# Run "$@ <path of partition N>" on the kernel node or on a copy (image file).
with_part() {
	local disk="$1" n="$2" rc; shift 2
	if [ -b "$disk" ]; then
		"$@" "$(part_node "$disk" "$n")"
		return
	fi
	local s z tmp="$TMPDIR/part$n.$$"
	s=$(part_field "$disk" "$n" start); z=$(part_field "$disk" "$n" size)
	dd if="$disk" of="$tmp" bs=$SECTOR skip="$s" count="$z" 2>/dev/null
	rc=0; "$@" "$tmp" || rc=$?
	dd if="$tmp" of="$disk" bs=$SECTOR seek="$s" conv=notrunc 2>/dev/null
	rm -f "$tmp"
	return $rc
}

wait_node() {
	local i=0
	while [ ! -b "$1" ] && [ $i -lt 50 ]; do sleep 0.1; i=$((i + 1)); done
	[ -b "$1" ]
}

create_p2() {
	local start
	start=$(free_start "$1")
	echo "start=$start, type=7" | sfdisk --append --no-reread -q "$1" >/dev/null || return 1
	if [ -b "$1" ]; then
		blockdev --rereadpt "$1" || return 1
		wait_node "$(part_node "$1" 2)" || return 1
	fi
}

format_roms() { mkfs.exfat -L ROMS "$1" >/dev/null; }

# VolumeFlags of the exFAT boot sector of the partition that starts at sector $2, in decimal
# (device-fixes D1): 2 bytes, little-endian, at offset 106. Bit 1 (0x0002) is VolumeDirty:
# the kernel sets it on mount and clears it on unmount or remount, so it stays set after a
# power cut. Bit 2 (0x0004) is MediaFailure. Same mould as fs_type_at: one sector read.
volume_flags() {
	set -- $(dd if="$1" bs=$SECTOR skip="$2" count=1 2>/dev/null | dd bs=1 skip=106 count=2 2>/dev/null | hexdump -v -e '/1 "%u "')
	[ $# = 2 ] || return 1
	echo $(( $1 + $2 * 256 ))
}

# The flags for the log: "0x0002 VolumeDirty", "0x0000".
flags_text() {
	local t
	t=$(printf '0x%04x' "$1")
	[ $(( $1 & 2 )) = 0 ] || t="$t VolumeDirty"
	[ $(( $1 & 4 )) = 0 ] || t="$t MediaFailure"
	echo "$t"
}

# Check and repair of ROMS. $1: why it runs (dirty | requested), $2: the flags for the log,
# $3: the partition. One line "ROMS <why>: checked: <result> (flags <flags>)", which lume-logd
# turns into the event "roms OK <why>: checked: ..."; no "(flags ...)" when $2 is empty.
# fsck.exfat -p: 0 = clean, 1 = errors corrected, others = errors left.
check_roms() {
	local why="$1" flags="${2:+ (flags $2)}" out rc=0
	out=$(fsck.exfat -p "$3" 2>&1) || rc=$?
	case $rc in
	0) log "ROMS $why: checked: clean$flags" ;;
	1) log "ROMS $why: checked: errors corrected$flags" ;;
	*) log "ROMS $why: checked: uncorrected errors (code $rc)$flags"; echo "$out" | while read -r l; do log "  $l"; done ;;
	esac
	return 0
}

# Number of the boot that is starting, for ROMS mounted at $1: lume-logd numbers it later in
# this boot as ROMS/logs/.boot + 1 (logd start), so the same number is computed here.
roms_boot_n() {
	local prev
	prev=$(tr -cd '0-9' < "$1/logs/.boot" 2>/dev/null)
	prev=${prev#"${prev%%[!0]*}"}   # no leading zeros: "08" is no octal number
	echo $(( ${prev:-0} + 1 ))
}

# The check request of the user (device-fixes D3, contract in docs/LAUNCHER.md):
# ROMS/system/card/check-next-boot, seen only once ROMS is mounted at $2. With a request:
# unmount, check the partition of disk $1, mount again with the command $3, then delete the
# request and write ROMS/system/card/last-check with the number of this boot. A volume
# already checked in this boot ($4 = checked: it was dirty) is not checked twice. Without a
# request this is one file test. Fails only when ROMS could not be mounted again (the
# request then stays for the next boot).
roms_request() {
	local disk="$1" mnt="$2" mountcmd="$3" dir="$2/system/card"
	[ -e "$dir/check-next-boot" ] || return 0
	if [ "$4" = checked ]; then
		log "ROMS requested: checked: by the dirty volume check of this boot"
	elif ! umount "$mnt"; then
		log "ERROR: failed to unmount ROMS for the requested check; the request stays for the next boot"
		return 0
	else
		with_part "$disk" 2 check_roms requested ""
		"$mountcmd" || return 1
	fi
	rm -f "$dir/check-next-boot"
	roms_boot_n "$mnt" > "$dir/last-check.tmp" && mv -f "$dir/last-check.tmp" "$dir/last-check"
	return 0
}

# The ROMS lines of this start survive a restart of the kernel in the same boot (kexec, or
# the reboot into a new boot image on the GA36): the next start has a new kernel log, and
# lume-logd reads only that one. Saved on ROMS at $1 right before it is unmounted, each line
# with the suffix $2; the next start logs them again (roms_carry_replay) and deletes the file.
ROMS_CARRY=system/card/.restart-log
roms_carry_save() {  # mnt suffix
	mkdir -p "$1/${ROMS_CARRY%/*}"
	dmesg | sed -n "s/.*lume: \(ROMS [a-z]*: .*\)/\1 $2/p" > "$1/$ROMS_CARRY"
}
roms_carry_replay() {  # mnt
	local l
	[ -f "$1/$ROMS_CARRY" ] || return 0
	while IFS= read -r l; do
		[ -n "$l" ] && log "$l"
	done < "$1/$ROMS_CARRY"
	rm -f "$1/$ROMS_CARRY"
}
# The restart failed and this start goes on: its lines are already in its own log.
roms_carry_drop() { rm -f "$1/$ROMS_CARRY"; }

# Prepare the games partition. Print "ok" if ROMS can be mounted, "ok checked" when it was
# also checked now (a dirty volume), so a check request found after the mount needs no
# second check (roms_request).
setup_storage() {
	local disk="$1" action flags
	action=$(decide_p2 "$disk")
	case "$action" in
	create)
		log "first boot: creating ROMS partition (exFAT) on remaining disk space..."
		if create_p2 "$disk" && with_part "$disk" 2 format_roms; then
			log "ROMS partition created"
			echo ok
		else
			log "ERROR: failed to create ROMS partition"
		fi
		;;
	check)
		# device-fixes D1: the check only on a volume left dirty (power cut, crash) or
		# with a media failure; a clean volume costs this one read
		if ! flags=$(volume_flags "$disk" "$(part_field "$disk" 2 start)"); then
			log "ERROR: ROMS volume flags unreadable; checking the partition"
			with_part "$disk" 2 check_roms dirty unreadable
			echo ok checked
		elif [ $(( flags & 6 )) != 0 ]; then
			with_part "$disk" 2 check_roms dirty "$(flags_text "$flags")"
			echo ok checked
		else
			log "ROMS clean: check skipped (flags $(flags_text "$flags"))"
			echo ok
		fi
		;;
	foreign)
		log "ERROR: partition 2 exists but is not exFAT; nothing formatted. Continuing without ROMS."
		;;
	usbc)
		log "ERROR: the first sector of partition 2 holds a USB command block (\"USBC\") instead of exFAT data: the card was corrupted by a faulty USB card reader on the PC. Nothing formatted; continuing without ROMS. Use another card reader, then repair the partition with fsck.exfat or write the card again (lume flash --full)."
		;;
	nospace)
		log "ERROR: no free space for ROMS partition"
		;;
	esac
}

# Folder structure of the games contract. Only recreates what is missing.
make_folders() {
	local root="$1" s; shift
	for s in "$@"; do mkdir -p "$root/roms/$s"; done
	for s in bios saves states screenshots system; do mkdir -p "$root/$s"; done
}

# SYSTEM of this console on BOOT (design D6 of r36s-single-card): on the single card each
# console has its own folder (ga36/SYSTEM, r36s/SYSTEM); the vm image keeps BOOT/SYSTEM.
# $1: the board name built into the initramfs (/etc/board), empty on older builds.
system_file() {
	case "$1" in
	""|vm) echo SYSTEM ;;
	*) echo "$1/SYSTEM" ;;
	esac
}

# Kernel modules image of this console (kernel-modules-image D1, D4): BOOT/<board>/modules,
# next to its kernel and SYSTEM. Nothing on the vm, which keeps its modules in SYSTEM.
modules_file() {
	case "$1" in
	""|vm) ;;
	*) echo "$1/modules" ;;
	esac
}

# A file of the BOOT mounted at $1, by its path $2 relative to it (push-boot-swap D4):
# prints $2 when it exists. Without it, a push cut between its two renames left only
# $2.old, the previous build, intact: prints that, with an ERROR line in the log. Fails
# when neither exists.
boot_file() {
	if [ -f "$1/$2" ]; then
		echo "$2"
	elif [ -f "$1/$2.old" ]; then
		log "ERROR: BOOT has no $2; using $2.old from the previous build"
		echo "$2.old"
	else
		return 1
	fi
}

# The release folders at the root of a mounted modules image, on one line.
modules_found() { echo $(ls -A "$1" 2>/dev/null); }

# Does the modules image mounted at $1 hold exactly one folder, named $2 (uname -r)?
modules_match() {
	[ -n "$2" ] && [ "$(ls -A "$1" 2>/dev/null)" = "$2" ] && [ -d "$1/$2" ]
}

# Mount the modules image of console $1 from the BOOT at $2 on $4/lib/modules, through the
# mount point $3, only when its release folder is the running kernel's. When it is missing,
# does not mount or is for another kernel, the system starts without modules (the boot
# drivers are built into the kernel) with an ERROR line in the log. Only the .old of an
# interrupted push (boot_file) still passes the release check.
mount_modules() {
	local board="$1" boot="$2" mnt="$3" root="$4" want file
	want=$(modules_file "$board")
	[ -n "$want" ] || return 0
	if ! file=$(boot_file "$boot" "$want"); then
		log "ERROR: BOOT has no $want; starting without kernel modules"
		return 0
	fi
	mkdir -p "$mnt"
	if ! mount -t squashfs -o ro,loop "$boot/$file" "$mnt"; then
		log "ERROR: failed to mount $file; starting without kernel modules"
		return 0
	fi
	modules_attach "$file" "$mnt" "$root"
}

# The modules image $1 (its BOOT path, for the log), already mounted at $2: moved to
# $3/lib/modules when its release folder is the running kernel's; otherwise unmounted, and
# the system starts without modules with an ERROR line in the log. Shared by mount_modules
# and the modules slot of a slot set (build-speed D9).
modules_attach() {
	local file="$1" mnt="$2" root="$3" running found
	running=$(uname -r)
	if ! modules_match "$mnt" "$running"; then
		found=$(modules_found "$mnt")
		umount "$mnt"
		log "ERROR: $file holds modules for ${found:-no kernel}, the running kernel is $running; starting without kernel modules"
		return 0
	fi
	mkdir -p "$root/lib/modules"
	if mount --move "$mnt" "$root/lib/modules"; then
		log "modules: $file ($running)"
	else
		umount "$mnt"
		log "ERROR: failed to move $file to /lib/modules; starting without kernel modules"
	fi
}

# Name of the console for the messages on the screen.
console_label() {
	case "$1" in
	ga36) echo GA36 ;;
	r36s) echo R36S ;;
	""|vm) echo VM ;;
	*) echo "$1" ;;
	esac
}
