"""Update a console over the USB cable: `lume push [--build <timestamp>]` (usb-device-access D6).

The console must be on with the cable on its OTG port. Steps, all through ssh to
root@10.55.0.1 (root has no password on the USB cable, D4):

1. read the console: VERSION, board, battery, free space on ROMS and BOOT, the size of the
   *.old/*.new left by an earlier push, BOOT used (df) against what its files take (du),
   and the SHA256 of the files on BOOT (not *.old/*.new); refuse below 20% battery; warn
   when df passes du by more than 32 MiB (lost clusters, push-boot-swap D3);
2. compare the BOOT list of the build (boot-files.sha256, read back from the FAT when the
   image was built) with the console, leaving VERSION out: when nothing else differs there
   is nothing to send; otherwise the files that differ go, with VERSION last. They are read
   from out/images/objects/<sha256> (build-speed D10), without unpacking the image; a build
   archived before the objects is unpacked once and its files stored as objects;
3. send them to /storage/.lume-push/<build>/ (ROMS) and check them there with
   `sha256sum -c`: nothing on BOOT changes if one differs;
4. on BOOT (remounted rw), in this order (build-speed D9, task 4.6):
   a. the *.old/*.new of an earlier push deleted (nothing holds them open after its
      reboot), except <console>/SLOTS.old; the slot files that neither SLOTS nor SLOTS.old
      cites (nor the new set, nor a loop device) deleted, for room;
   b. the new slot files of both consoles (<console>/slot/<name>-<sha12>: names by content,
      never the name of a file in use) and each new manifest as <console>/SLOTS.new, then
      all of them checked with `sha256sum -c` on BOOT, read back from the card: a mismatch
      stops the push before any set is swapped;
   c. every other file copied to <name>.new, synced and renamed over the old one. A SYSTEM
      or modules image of an old build held open by its loop device is renamed to
      <name>.old instead, because vfat cannot free the clusters of an open file that lost
      its name (push-boot-swap D1). On the GA36, the boot image of panel 1 at sector
      172032 when it changed, read back and compared;
   d. each console's set swapped (swap_command): SLOTS.old deleted, SLOTS renamed to
      SLOTS.old, SLOTS.new renamed to SLOTS, each step synced. The initramfs mounts SLOTS,
      else SLOTS.old, else the old SYSTEM, so a power cut at any moment boots the old set
      or the new one, never a mix;
   e. VERSION last, so an interrupted push leaves the old VERSION and the next push sends
      what still differs;
   f. the slot files of the set before the previous one deleted; on an old card, the
      <console>/SYSTEM and <console>/modules deleted by the push that follows the one that
      wrote its first slot set (never by that one, and never while a loop holds them);
5. BOOT read-only again, the staging folder removed, reboot. If vfat still refuses
   read-only ("Resource busy"), something holds a deleted file open: warn that this boot
   may leave lost clusters, for the next push to check (D5).
6. unless `--no-wait` (build-speed D12): wait for the console to go away and come back over
   the cable, then check that a new boot started (boot number of /run/lume/logs/boot-n,
   not the clock: the console clock is not reliable), that /boot/VERSION carries the pushed
   build and that events.log has `boot OK completed` for that boot, and that it mounted
   <board>/SLOTS (check_slots_mounted); print `ok` with the send and boot times, or the
   step that diverged.

There is no rsync on the console: each file goes as `cat > file` over ssh.
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from lume_tool import image, manifests, sshmux
from lume_tool.archive import images_dir, objects_dir
from lume_tool.paths import cache_dir, ensure_dir
from lume_tool.targets import IMAGES

CONSOLE_ADDR = "10.55.0.1"       # the console on the USB network (D5)
PROBE_TIMEOUT = 10               # seconds for one "does the console answer?" ssh probe
STAGING = "/storage/.lume-push"
MIN_BATTERY = 20
ANDROID_SECTOR = 172032          # GA36 kernel boot image (lume_tool.vendor.ANDROID_BOOT_SECTOR)
PANEL1_IMAGE = "ga36-android-boot-panel1.img"
CHUNK = 1 << 22
LOST_LIMIT = 32 << 20            # BOOT used (df) above what its files take (du): lost clusters
# <console>/SLOTS.old is the previous slot set (build-speed D9), the boot fallback: never stale
STALE_CLEANUP = (r"find /boot -type f \( -name '*.old' -o -name '*.new' \) ! -name SLOTS.old "
                 r"-exec rm -f {} \; && sync")
BOOT_SUMS = "BOOT.SHA256SUMS"    # the slot files and SLOTS.new as written on BOOT
# legacy root files of an old card (before the slots), deleted by the push that follows the
# one that wrote the first slot set of that console
LEGACY_FILES = ("SYSTEM", "modules")

# after the reboot (build-speed D12); measured 2026-11-16: ssh answers again ~40 s after the
# reboot, `boot OK completed` ~34 s from the kernel
GONE_TIMEOUT = 60                # seconds for the console to stop answering after the reboot
BACK_TIMEOUT = 180               # seconds for it to answer again over the cable
BOOT_OK_TIMEOUT = 120            # seconds, once back, for `boot OK completed` in events.log
POLL_INTERVAL = 2.0
BOOT_N = "/run/lume/logs/boot-n"
EVENTS_LOG = "/storage/logs/events.log"
BOOT_OK = "boot OK completed"
READ_BOOT_N = f"cat {BOOT_N} 2>/dev/null || true"
# one line each: boot number, build of /boot/VERSION, last `boot OK completed` of that boot
BOOT_STATUS = (f"n=$(cat {BOOT_N} 2>/dev/null); echo \"${{n:--}}\"; "
               "sed -n 's/^build: //p' /boot/VERSION; "
               f"awk -v n=\"$n\" '$2 == n && /{BOOT_OK}/' {EVENTS_LOG} 2>/dev/null | tail -n 1")


# Which console is on the cable (build-speed 3.4, D18): one card moves between the GA36 and
# the R36S and both answer at CONSOLE_ADDR, so `push`, `push --hot` and `dev` ask the console.
CONSOLES = ("ga36", "r36s")
MACHINE_CONSOLE = {"armv7l": "ga36", "aarch64": "r36s"}    # `uname -m` when there is no board
IDENTIFY = 'b=$(cat /etc/lume/board 2>/dev/null); echo "${b:--}"; uname -m'


def console_name(board: str, machine: str = "") -> str:
    """ga36 or r36s from /etc/lume/board, else from `uname -m`; "" when neither says."""
    board, machine = board.strip(), machine.strip()
    if board in CONSOLES:
        return board
    return MACHINE_CONSOLE.get(machine, "")


def identify_console(run: Callable[[str], str]) -> str:
    """The console on the cable (ga36, r36s or "" if unknown); `run` runs a remote command."""
    lines = run(IDENTIFY).splitlines() + ["", ""]
    return console_name(lines[0], lines[1])


def console_refusal(name: str, wanted: str | None) -> str | None:
    """The refusal when `--console wanted` was given and the console on the cable is another
    one (or unknown); None when it may go on."""
    if not wanted or name == wanted:
        return None
    return (f"the console on the cable is the {name.upper()}, not the {wanted.upper()}"
            if name else f"the console on the cable did not say which one it is, so it may "
                         f"not be the {wanted.upper()}")


def running_files(board: str) -> tuple[str, ...]:
    """BOOT files the running console keeps open by a loop device until it powers off: they
    are swapped through <name>.old and their old size stays taken until the next push."""
    return (f"{board}/SYSTEM", f"{board}/modules")


class PushError(RuntimeError):
    pass


def split_host(addr: str) -> tuple[str, int | None]:
    """"host" or "host:port" (`lume vm --ssh`: 127.0.0.1:2222) -> (host, port or None).

    Only one colon makes a port, so a bare IPv6 address stays a host."""
    host, sep, port = addr.rpartition(":")
    if not sep or ":" in host or not host:
        return addr, None
    if not port.isdigit() or not 1 <= int(port) <= 65535:
        raise PushError(f"bad port in {addr!r}: use HOST:PORT, e.g. 127.0.0.1:2222")
    return host, int(port)


class Remote:
    """Commands on the console over ssh (replaced by a fake in the tests).

    Root has no password on the USB cable (D4) and the console makes a new host key every
    boot, so nothing is checked against or written to the user's known_hosts. `host` may
    carry a port (host:port, the vm's forwarded ssh); `root@host` stays the last word."""

    def __init__(self, host: str = CONSOLE_ADDR):
        self.host = host
        addr, port = split_host(host)
        # ServerAlive*: a connection that dies in the middle (the console rebooting) is
        # dropped in ~6 s; ConnectTimeout only covers opening it (J1, 2026-11-16: a probe
        # caught by the reboot hung for minutes)
        self.plain_base = ["ssh", "-o", "UserKnownHostsFile=/dev/null",
                           "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=ERROR",
                           "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                           "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
                           *(["-p", str(port)] if port is not None else []),
                           f"root@{addr}"]
        # the shared OpenSSH master channel (virtual-gamepad 3.6, lume_tool.sshmux); the same
        # argv as plain_base when LUME_SSH_MUX=0
        mux = sshmux.options(addr, port)
        self.base = [*self.plain_base[:-1], *mux, self.plain_base[-1]]

    def drop_channel(self) -> None:
        """Close the shared master (the console is about to restart or changed)."""
        sshmux.drop(self.base)

    def run(self, cmd: str, stdin: Path | None = None) -> str:
        with (stdin.open("rb") if stdin else open("/dev/null", "rb")) as f:
            r = subprocess.run([*self.base, cmd], stdin=f, capture_output=True)
        if r.returncode != 0:
            err = (r.stderr or b"").decode(errors="replace").strip()
            if r.returncode == 255:
                raise PushError(f"ssh to the console failed: {err or 'no answer'} (is the "
                                "console on, with the cable on its OTG port?)")
            raise PushError(f"on the console, `{cmd}` failed ({r.returncode}): {err}")
        return r.stdout.decode(errors="replace")

    def answers(self) -> bool:
        """True when the console answers ssh over the cable now (False after
        PROBE_TIMEOUT seconds, whatever ssh is doing)."""
        try:
            return subprocess.run([*self.plain_base, "true"], stdin=subprocess.DEVNULL,
                                  capture_output=True, timeout=PROBE_TIMEOUT).returncode == 0
        except subprocess.TimeoutExpired:
            return False


@dataclass
class Console:
    board: str
    build: str
    battery: int | None
    roms_free: int          # bytes
    boot_free: int
    device: str             # the card, e.g. /dev/mmcblk0
    boot_sums: dict[str, str]
    boot_stale: int = 0     # *.old/*.new of an earlier push, deleted before the swap
    boot_used: int = 0      # df "Used" of BOOT
    boot_files: int = 0     # du -s of BOOT

    @property
    def boot_lost(self) -> int:
        """BOOT clusters taken but owned by no file (0 on a clean FAT)."""
        return max(0, self.boot_used - self.boot_files)


_PROBE = r"""
sed -n 's/^build: //p' /boot/VERSION
cat /etc/lume/board
b=""; for p in /sys/class/power_supply/*; do [ "$(cat $p/type 2>/dev/null)" = Battery ] && b=$(cat $p/capacity); done; echo "${b:--}"
df -Pk /storage | awk 'NR==2{print $4}'
df -Pk /boot | awk 'NR==2{print $4}'
awk '$2=="/boot"{print $1}' /proc/mounts | sed -E 's/p?[0-9]+$//'
find /boot -type f \( -name '*.old' -o -name '*.new' \) ! -name SLOTS.old -exec du -k {} \; | awk '{s+=$1} END{print s+0}'
df -Pk /boot | awk 'NR==2{print $3}'
du -sk /boot | awk '{print $1}'
cd /boot && find . -type f ! -name '*.new' ! -name '*.old' | sed 's|^\./||' | while read -r f; do sha256sum "$f"; done
"""
_PROBE_HEAD = 9             # lines before the SHA256 list


def read_console(remote: Remote) -> Console:
    lines = remote.run(_PROBE).splitlines()
    if len(lines) < _PROBE_HEAD:
        raise PushError(f"unexpected answer from the console: {lines!r}")
    sums = {}
    for line in lines[_PROBE_HEAD:]:
        digest, _, name = line.partition("  ")
        if name:
            sums[name] = digest
    battery = None if lines[2].strip() in ("", "-") else int(lines[2])
    return Console(board=lines[1].strip(), build=lines[0].strip(), battery=battery,
                   roms_free=int(lines[3]) * 1024, boot_free=int(lines[4]) * 1024,
                   device=lines[5].strip(), boot_sums=sums,
                   boot_stale=int(lines[6]) * 1024, boot_used=int(lines[7]) * 1024,
                   boot_files=int(lines[8]) * 1024)


def lost_clusters_warning(console: Console) -> str | None:
    """push-boot-swap D3: the warning for BOOT clusters owned by no file, or None."""
    lost = console.boot_lost
    if lost <= LOST_LIMIT:
        return None
    return (f"warning: BOOT has {lost >> 20} MiB in lost clusters (a SYSTEM replaced by an "
            "older push, or a power cut); recover them from the PC with the card in the "
            "reader: `sudo fsck.vfat -a <BOOT, partition 1 of the card>` and delete "
            "BOOT/FSCK*.REC, or `lume flash --update`")


# --- slot sets on BOOT (build-speed D9, task 4.6) ---------------------------------------

# The manifests <console>/SLOTS and SLOTS.old as they are (a truncated one included), the
# files held open by loop devices (the running root and modules) and the size of every slot
# file. Each manifest is "== <path>", its text, a newline and "== eof".
SLOT_STATE = ('for f in /boot/*/SLOTS /boot/*/SLOTS.old; do [ -f "$f" ] || continue; '
              'echo "== ${f#/boot/}"; cat "$f"; echo; echo "== eof"; done; '
              "echo '== loops'; cat /sys/block/loop*/loop/backing_file 2>/dev/null; "
              "echo '== sizes'; find /boot/*/slot -type f -exec du -k {} \\; 2>/dev/null; true")


def is_slot_file(p: str) -> bool:
    """<console>/slot/<name>-<sha12>."""
    parts = p.split("/")
    return len(parts) == 3 and parts[1] == manifests.SLOTS_DIR


def is_slots_manifest(p: str) -> bool:
    """<console>/SLOTS."""
    parts = p.split("/")
    return len(parts) == 2 and parts[1] == manifests.SLOTS_FILE


@dataclass
class SlotFolder:
    """The slot set of one console folder of BOOT, as the push found it."""
    console: str
    current: manifests.SlotSet | None = None     # SLOTS, parsed
    previous: manifests.SlotSet | None = None    # SLOTS.old, parsed
    current_exists: bool = False
    previous_exists: bool = False
    unreadable: bool = False                      # a manifest that does not parse

    def cited(self) -> set[str]:
        """BOOT paths of the slot files SLOTS or SLOTS.old cites."""
        return {f"{self.console}/{f}" for ss in (self.current, self.previous) if ss
                for f in ss.files()}


@dataclass
class SlotState:
    folders: dict[str, SlotFolder]
    running: list[str]                  # backing files of the loop devices
    sizes: dict[str, int]               # BOOT path of each slot file -> bytes (KiB rounded)

    def folder(self, console: str) -> SlotFolder:
        return self.folders.setdefault(console, SlotFolder(console))


def parse_slot_state(text: str) -> SlotState:
    state = SlotState({}, [], {})
    mode, cur, buf = None, None, []
    for line in text.split("\n"):
        if cur is not None:
            if line != "== eof":
                buf.append(line)
                continue
            console, _, name = cur.partition("/")
            folder = state.folder(console)
            body = "\n".join(buf)
            try:
                ss = manifests.parse_slots(body, cur)
                if ss.console != console:
                    raise manifests.ManifestError(f"{cur} is the set of {ss.console}")
            except manifests.ManifestError:
                ss = None
                folder.unreadable = True
            if name == manifests.SLOTS_FILE:
                folder.current, folder.current_exists = ss, True
            else:
                folder.previous, folder.previous_exists = ss, True
            cur, buf = None, []
        elif line == "== loops":
            mode = "loops"
        elif line == "== sizes":
            mode = "sizes"
        elif mode is None and line.startswith("== "):
            cur = line[3:]
        elif mode == "loops" and line.strip():
            state.running.append(line.strip().removesuffix(" (deleted)"))
        elif mode == "sizes" and line.strip():
            kib, _, path = line.strip().partition("\t")
            if not path:
                kib, _, path = line.strip().partition(" ")
            path = path.strip().removeprefix("/boot/")
            if kib.isdigit() and path:
                state.sizes[path] = int(kib) * 1024
    return state


def read_slot_state(remote) -> SlotState:
    return parse_slot_state(remote.run(SLOT_STATE))


def is_running(p: str, running: list[str]) -> bool:
    """The BOOT file p is held open by a loop device (its backing file path ends with it;
    where BOOT is mounted does not matter)."""
    return any(r == p or r.endswith("/" + p) for r in running)


def usable(ss: manifests.SlotSet | None, console: str, present: set[str]) -> bool:
    """What the initramfs mounts (slots_check): a manifest that parses, for this console,
    whose slot files are all on BOOT."""
    return ss is not None and all(f"{console}/{f}" in present for f in ss.files())


def slot_orphans(folder: SlotFolder, present: set[str], running: list[str],
                 keep: set[str]) -> list[str]:
    """Slot files of the folder cited by none of `keep` and not held open: what may be
    deleted. Nothing when a manifest of the folder does not parse (what it cites is
    unknown)."""
    if folder.unreadable:
        return []
    return sorted(p for p in present
                  if is_slot_file(p) and p.split("/")[0] == folder.console
                  and p not in keep and not is_running(p, running))


def swap_command(console: str, current_usable: bool) -> str:
    """The swap of a console's set on BOOT. With a usable SLOTS: SLOTS.old deleted, SLOTS
    renamed to SLOTS.old, SLOTS.new renamed to SLOTS, each step synced. Between the two
    renames SLOTS is missing and the initramfs mounts SLOTS.old, the set that was running;
    no rename goes over an existing name (not atomic on vfat). Without a usable SLOTS (an
    old card, or a push cut between the renames), SLOTS.old stays the fallback and the
    unusable SLOTS is deleted before SLOTS.new takes its name."""
    d = _q(f"/boot/{console}")
    if current_usable:
        return (f"cd {d} && rm -f SLOTS.old && sync && mv SLOTS SLOTS.old && sync && "
                "mv SLOTS.new SLOTS && sync")
    return f"cd {d} && rm -f SLOTS && sync && mv SLOTS.new SLOTS && sync"


def rm_command(paths: list[str]) -> str:
    return "rm -f " + " ".join(_q(f"/boot/{p}") for p in paths) + " && sync"


@dataclass
class SlotPlan:
    slot_files: list[str]               # <console>/slot/* to write, in list order
    manifests: list[str]                # <console>/SLOTS written as SLOTS.new, then swapped
    current_usable: dict[str, bool]     # console -> its SLOTS is a usable set (swap order)
    orphans: list[str]                  # slot files deleted before the copy
    after: list[str]                    # slot files deleted after the swap
    migrate: dict[str, list[str]]       # console -> legacy root files deleted after the swap
    kept_running: list[str]             # legacy root files kept: the console runs from them
    slot_sizes: dict[str, int]          # size of the slot files on BOOT


def plan_slots(files: list[tuple[str, str]], sources: dict[str, Path],
               boot_list: list[tuple[str, str]], console: Console,
               state: SlotState) -> SlotPlan:
    """What the push does with the slot sets of every console folder of BOOT (both consoles
    share the card): which slot files and manifests to write, which slot files no set cites
    any more, and, on an old card (<console>/SYSTEM and <console>/modules), whether its
    legacy root goes: only when the folder already had a usable slot set before this push,
    so the push that writes the first set never deletes SYSTEM."""
    present = set(console.boot_sums)
    listed = {p for p, _ in boot_list}
    slot_files = [p for p, _ in files if is_slot_file(p)]
    manifest_paths = [p for p, _ in files if is_slots_manifest(p)]
    new_sets: dict[str, manifests.SlotSet] = {}
    for p in manifest_paths:
        c = p.split("/")[0]
        try:
            ss = manifests.parse_slots(sources[p].read_text(), p)
        except (OSError, UnicodeDecodeError, manifests.ManifestError) as e:
            raise PushError(f"the {p} of the build is not a usable slot set: {e}") from None
        if ss.console != c:
            raise PushError(f"the {p} of the build is the set of {ss.console}")
        missing = [f"{c}/{f}" for f in ss.files() if f"{c}/{f}" not in listed]
        if missing:
            raise PushError(f"the {p} of the build cites {', '.join(missing)}, not in its "
                            f"{image.BOOT_LIST}")
        new_sets[c] = ss
    consoles = (set(state.folders) | set(new_sets)
                | {p.split("/")[0] for p in present if is_slot_file(p)}
                | {p.split("/")[0] for p in present
                   if p.count("/") == 1 and p.split("/")[1] in LEGACY_FILES})
    orphans: list[str] = []
    after: list[str] = []
    migrate: dict[str, list[str]] = {}
    kept_running: list[str] = []
    current_usable: dict[str, bool] = {}
    for c in sorted(consoles):
        folder = state.folder(c)
        new_files = ({f"{c}/{f}" for f in new_sets[c].files()} if c in new_sets else set())
        # a file the new set cites stays even when no manifest on BOOT cites it: it was
        # found present, so it is not sent again
        orphans += slot_orphans(folder, present, state.running, folder.cited() | new_files)
        cur_ok = usable(folder.current, c, present)
        prev_ok = usable(folder.previous, c, present)
        current_usable[c] = cur_ok
        if c in new_sets:
            # after the swap: SLOTS is the new set and SLOTS.old the running one (or the
            # SLOTS.old that stays when SLOTS was not usable)
            kept = folder.current if cur_ok else folder.previous
            unknown = not cur_ok and folder.previous_exists and folder.previous is None
            if not unknown:
                keep = new_files | ({f"{c}/{f}" for f in kept.files()} if kept else set())
                now_present = (present - set(orphans)) | set(slot_files)
                after += sorted(p for p in now_present
                                if is_slot_file(p) and p.split("/")[0] == c
                                and p not in keep and not is_running(p, state.running))
        if cur_ok or prev_ok:
            for n in LEGACY_FILES:
                p = f"{c}/{n}"
                if p not in present or p in listed:
                    continue
                if is_running(p, state.running):
                    kept_running.append(p)
                else:
                    migrate.setdefault(c, []).append(p)
    return SlotPlan(slot_files, manifest_paths, current_usable, orphans, after, migrate,
                    kept_running, dict(state.sizes))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def extract_boot(build_dir: Path, wanted: list[str], runner=None) -> Path:
    """The BOOT files `wanted` of the archived image, in a staging folder of the cache,
    checked against boot-files.sha256."""
    from lume_tool import flash

    zst = flash.find_image(IMAGES["console"], build_dir.name)
    img = flash._decompress(zst)
    stage = ensure_dir(cache_dir() / "push" / build_dir.name)
    offset = image.boot_start("console") * 512
    lines = [f'mkdir -p "/s/{Path(p).parent}"; mcopy -n -i "/img/{img.name}@@{offset}" '
             f'"::{p}" "/s/{p}"' for p in wanted]
    script = "export MTOOLS_SKIP_CHECK=1\n" + "\n".join(lines)
    (runner or _run_in_builder)({img.parent: "/img", stage: "/s"}, script)
    return stage


def _run_in_builder(volumes: dict[Path, str], script: str) -> None:
    from lume_tool.container import Container, ensure_builder
    from lume_tool.targets import TARGETS

    r = subprocess.run(Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes)
                       .argv(script), capture_output=True, text=True)
    if r.returncode != 0:
        raise PushError(f"could not read BOOT from the image: {(r.stdout + r.stderr).strip()}")


def plan_files(boot_list: list[tuple[str, str]], console: Console,
               other_change: bool = False) -> list[tuple[str, str]]:
    """(path, sha256) to send: the ones the console does not have, in list order, and
    VERSION last. VERSION is left out of the comparison (it differs in every build): it goes
    only together with another file (or with `other_change`, the GA36 boot sector), so a
    build that changed nothing else sends nothing."""
    version = [(p, d) for p, d in boot_list if p == manifests.VERSION_FILE]
    files = [(p, d) for p, d in boot_list
             if p != manifests.VERSION_FILE and console.boot_sums.get(p) != d]
    return files + version if files or other_change else []


def object_sources(build_dir: Path, files: list[tuple[str, str]], extractor,
                   out=print) -> dict[str, Path]:
    """BOOT path -> local file of each of `files`: its object (D10), or, for a build
    archived before the objects, the file unpacked from the image, checked and then stored
    as an object for the next push."""
    objects = objects_dir()
    missing = set(manifests.missing_objects(objects, files))
    sources = {p: manifests.object_path(objects, d) for p, d in files if p not in missing}
    if missing:
        wanted = [p for p, _ in files if p in missing]
        out(f"note: build {build_dir.name} has no stored object for {len(wanted)} file(s) "
            "(archived before build-speed): reading them from its image")
        stage = extractor(build_dir, wanted)
        for p, digest in files:
            if p not in missing:
                continue
            if _sha256(stage / p) != digest:
                raise PushError(f"{p} read from the image does not match {image.BOOT_LIST}")
            sources[p] = manifests.object_path(objects, manifests.store_object(objects,
                                                                               stage / p))
    return sources


def check_room(console: Console, sizes: dict[str, int], reclaim: int = 0) -> None:
    """`reclaim`: bytes of the slot files no manifest cites, deleted before the copy."""
    total = sum(sizes.values())
    if console.roms_free < total + (16 << 20):
        raise PushError(f"ROMS has {console.roms_free >> 20} MiB free, the push needs "
                        f"{total >> 20} MiB (plus 16 MiB) for /storage/.lume-push")
    # the slot files and SLOTS.new are all written before the swap and the running set
    # stays (it becomes SLOTS.old), as does the set of SLOTS.old until after the swap: the
    # new slot files need room of their own. Every other file goes to <name>.new before the
    # rename; the running SYSTEM and modules image of an old build keep their old blocks as
    # <name>.old until the next push (a loop device holds each one open), and the *.old/*.new
    # of the previous push are deleted before the swap
    slots = sum(s for p, s in sizes.items() if is_slot_file(p) or is_slots_manifest(p))
    others = [s for p, s in sizes.items() if not (is_slot_file(p) or is_slots_manifest(p))]
    need = (slots + max(others, default=0)
            + sum(sizes.get(p, 0) for p in running_files(console.board)))
    free = console.boot_free + console.boot_stale + reclaim
    if free < need:
        extra = [f"{console.boot_stale >> 20} MiB of an earlier push"] if console.boot_stale \
            else []
        if reclaim:
            extra.append(f"{reclaim >> 20} MiB of slots no SLOTS cites")
        raise PushError(f"BOOT has {free >> 20} MiB free"
                        + (f" (with {' and '.join(extra)})" if extra else "")
                        + f", the push needs {need >> 20} MiB to swap the files"
                        + (f" ({slots >> 20} MiB of new slots; the running set is kept as "
                           "SLOTS.old)" if slots else ""))


def _q(s: str) -> str:
    return shlex.quote(s)


# --- after the reboot (build-speed D12) -------------------------------------------------

@dataclass
class BootState:
    """What the console says about its current boot."""
    boot_n: str | None      # /run/lume/logs/boot-n
    build: str              # build of /boot/VERSION
    boot_ok: str | None     # its `boot OK completed: ...` line of events.log, if any


def read_boot_state(remote) -> BootState:
    lines = remote.run(BOOT_STATUS).splitlines() + ["", "", ""]
    n = lines[0].strip()
    return BootState(boot_n=None if n in ("", "-") else n, build=lines[1].strip(),
                     boot_ok=lines[2].strip() or None)


# Extra checks of the new boot, run after `boot OK completed`: each takes the remote and the
# BootState and returns what diverged, or None. Slots of SLOTS mounted (node 4.6) and the
# versions of the fragments sent (node 8.2) are added here later.
AfterBootCheck = Callable[[object, BootState], "str | None"]

# The board, the build of its <board>/SLOTS on BOOT ("-" without one), then the `lume: slots:`
# and `lume: root:` lines the initramfs logged in this boot (initramfs/lib/slots.sh), from the
# boot log in RAM, else the one on ROMS, else the kernel buffer
SLOTS_MOUNTED = (
    'n=$(cat /run/lume/logs/boot-n 2>/dev/null); b=$(cat /etc/lume/board 2>/dev/null); '
    'echo "${b:--}"; s=$(sed -n "s/^build //p" "/boot/$b/SLOTS" 2>/dev/null); '
    'echo "${s:--}"; shown=; '
    'for f in "/run/lume/logs/boot/boot-$n.log" "/storage/logs/boot/boot-$n.log"; do '
    'if [ -n "$n" ] && [ -f "$f" ]; then grep -E "lume: (slots|root): " "$f"; shown=1; break; '
    'fi; done; [ -n "$shown" ] || dmesg | grep -E "lume: (slots|root): "; true')


def check_slots_mounted(remote, state: BootState) -> str | None:
    """After a push: the console mounted <board>/SLOTS, the set on BOOT (build-speed 4.6).
    A fallback to SLOTS.old or to the old SYSTEM is an error naming what was mounted. A
    console without <board>/SLOTS (an old build) is not checked."""
    lines = remote.run(SLOTS_MOUNTED).splitlines() + ["", ""]
    board, on_boot = lines[0].strip(), lines[1].strip()
    if on_boot in ("", "-"):
        return None
    slots = root = None
    for line in lines[2:]:
        if "before kexec" in line:              # lines of the first start of a kexec
            continue
        if (i := line.find("lume: slots: ")) >= 0:
            slots = line[i + len("lume: slots: "):].strip()
        elif (i := line.find("lume: root: ")) >= 0:
            root = line[i + len("lume: root: "):].strip()
    want = f"{board}/{manifests.SLOTS_FILE}"
    if root is None:
        return (f"no `lume: root:` line in the log of boot {state.boot_n}: could not confirm "
                f"that it mounted {want} (see `lume dev log`)")
    mounted = root.split(" ", 1)[0]
    if mounted != want:
        what = ("the previous set" if mounted.endswith(manifests.SLOTS_OLD)
                else "the old root image" if mounted.endswith(LEGACY_FILES[0])
                or mounted.endswith(LEGACY_FILES[0] + ".old") else "not the slot set")
        return (f"boot {state.boot_n} mounted {mounted} ({what}), not the pushed set {want} "
                f"(build {on_boot}); see the ERROR lines of `lume dev log`")
    expected = f"{want} (build {on_boot})"
    if slots != expected:
        return (f"boot {state.boot_n} logged `slots: {slots or '(none)'}`, expected "
                f"`slots: {expected}`")
    return None


AFTER_BOOT_CHECKS: list[AfterBootCheck] = [check_slots_mounted]

# "name version" of each installed project fragment, from the apk database (one ssh call)
FRAGMENT_PREFIXES = ("lume-",)
FRAGMENT_VERSIONS = (
    "awk '/^P:/ { p = substr($0, 3) } "
    "/^V:/ { if (p ~ /^lume-/) print p, substr($0, 3) }' /lib/apk/db/installed")


def read_fragment_versions(remote) -> dict[str, str]:
    """The lume-* packages installed on the console and their versions."""
    found = {}
    for line in remote.run(FRAGMENT_VERSIONS).splitlines():
        name, _, version = line.strip().partition(" ")
        if name and version:
            found[name] = version.strip()
    return found


def expected_fragments(boot_list: list[tuple[str, str]], board: str,
                       sources: dict[str, Path]) -> dict[str, str]:
    """The fragment versions of the slot set this push puts on BOOT for `board`: the `pkg`
    lines of its <board>/SLOTS (the build's own record, so an archived build is checked
    against what it holds). Empty when the build has no set for the board or its manifest
    is not stored (an old build): then nothing is checked."""
    path = f"{board}/{manifests.SLOTS_FILE}"
    digest = dict(boot_list).get(path)
    if digest is None:
        return {}
    src = sources.get(path) or manifests.object_path(objects_dir(), digest)
    try:
        ss = manifests.parse_slots(src.read_text(), path)
    except (OSError, UnicodeDecodeError, manifests.ManifestError):
        return {}
    return {n: v for s in ss.slots for n, v in s.packages if n.startswith(FRAGMENT_PREFIXES)}


def fragment_mismatches(expected: dict[str, str], installed: dict[str, str]) -> list[str]:
    """One sentence per fragment whose installed version is not the one that was sent."""
    out = []
    for name, sent in sorted(expected.items()):
        got = installed.get(name)
        if got is None:
            out.append(f"the console has no {name}, the push sent {sent}")
        elif got != sent:
            out.append(f"the console runs {name} {got}, the push sent {sent}")
    return out


def make_fragment_check(expected: dict[str, str]) -> AfterBootCheck:
    """After the boot: every fragment of the pushed set is installed with the version sent
    (build-speed 8.2)."""
    def check_fragments(remote, state: BootState) -> str | None:
        problems = fragment_mismatches(expected, read_fragment_versions(remote))
        return "; ".join(problems) or None
    return check_fragments


def package_changes(new: manifests.SlotSet, current: manifests.SlotSet | None) -> list[str]:
    """`<slot>: <package> <on the card> -> <in the build>` for every package whose version
    differs between the set on the card and the one the push would write (`-` = absent)."""
    def versions(ss):
        return {} if ss is None else {n: (s.name, v) for s in ss.slots for n, v in s.packages}
    old, now = versions(current), versions(new)
    lines = []
    for name in sorted(old.keys() | now.keys()):
        a, b = old.get(name), now.get(name)
        if a is not None and b is not None and a[1] == b[1]:
            continue
        slot = (b or a)[0]
        lines.append(f"{slot}: {name} {a[1] if a else '-'} -> {b[1] if b else '-'}")
    return lines


def _mib(n: int) -> str:
    return f"{n / 2**20:.1f} MiB"


def dry_run_report(files: list[tuple[str, str]], sizes: dict[str, int], sources: dict[str, Path],
                   plan: SlotPlan, state: SlotState, panel1_changed: bool) -> list[str]:
    """What a push would do, without doing it (build-speed 3.7): the packages that change in
    each console's slot set, the files it would send with their sizes and what it would
    delete."""
    out = ["dry run: nothing is sent and the console does not reboot"]
    for p in plan.manifests:
        c = p.split("/")[0]
        try:
            new = manifests.parse_slots(sources[p].read_text(), p)
        except (OSError, UnicodeDecodeError, manifests.ManifestError) as e:
            out.append(f"packages: {c}: the build's {p} cannot be read ({e})")
            continue
        current = state.folder(c).current
        if current is None:
            out.append(f"packages: {c}: no slot set on the card yet (old card or first push): "
                       f"all {sum(len(s.packages) for s in new.slots)} packages are new")
            continue
        changes = package_changes(new, current)
        if not changes:
            out.append(f"packages: {c}: no package changed")
        for line in changes:
            out.append(f"packages: {c}/{line}")
    for p, _ in files:
        out.append(f"send:     {p} ({_mib(sizes[p])})")
    if panel1_changed:
        out.append(f"send:     {PANEL1_IMAGE} ({_mib(sizes[PANEL1_IMAGE])}, sector "
                   f"{ANDROID_SECTOR})")
    out.append(f"total:    {_mib(sum(sizes.values()))} in {len(sizes)} file(s)")
    gone = plan.orphans + plan.after + [p for c in plan.migrate for p in plan.migrate[c]]
    if gone:
        out.append("delete:   " + ", ".join(gone))
    for p in plan.kept_running:
        out.append(f"keep:     {p} (the console runs from it)")
    return out


def _duration(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def _drop_channel(remote) -> None:
    """Close the shared ssh master of `remote` (fakes in the tests have none)."""
    drop = getattr(remote, "drop_channel", None)
    if drop:
        drop()


def verify_boot(remote, build: str, old_boot_n: str | None, sleep=time.sleep,
                now=time.monotonic, checks: list[AfterBootCheck] | None = None
                ) -> BootState:
    """Wait for the console to go away and come back over the cable, then check that a new
    boot started with `build` on /boot/VERSION and reached `boot OK completed`. Raises
    PushError naming the last step confirmed."""
    from lume_tool.dev import wait_for_console      # dev imports this module

    host = getattr(remote, "host", CONSOLE_ADDR)
    _drop_channel(remote)
    if not wait_for_console(host, GONE_TIMEOUT, POLL_INTERVAL, sleep, now,
                            probe=lambda: not remote.answers()):
        raise PushError(f"the console still answers {GONE_TIMEOUT}s after the reboot "
                        "(last step confirmed: reboot sent)")
    if not wait_for_console(host, BACK_TIMEOUT, POLL_INTERVAL, sleep, now,
                            probe=remote.answers):
        raise PushError(f"the console did not come back over the cable within "
                        f"{BACK_TIMEOUT}s (last step confirmed: the console went away for "
                        "the reboot)")
    _drop_channel(remote)       # a new boot: nothing of the old channel may be reused
    end = now() + BOOT_OK_TIMEOUT
    state, last_error = None, None
    while True:
        try:
            state, last_error = read_boot_state(remote), None
        except PushError as e:                  # ssh dropped while the boot goes on
            last_error = e
        if state is not None:
            if state.boot_n is None:
                raise PushError(f"the console is back but has no boot number ({BOOT_N}) "
                                "(last step confirmed: console back over the cable)")
            if state.boot_n == old_boot_n:
                raise PushError(f"the console is back but still runs boot {state.boot_n}, "
                                "the one before the reboot (last step confirmed: console "
                                "back over the cable)")
            if state.build != build:
                raise PushError(f"boot {state.boot_n} runs build {state.build or '?'} from "
                                f"/boot/VERSION, not the pushed build {build} (last step "
                                f"confirmed: boot {state.boot_n} started)")
            if state.boot_ok:
                break
        if now() >= end:
            if state is None:
                raise PushError(f"the console answered but its boot could not be read within "
                                f"{BOOT_OK_TIMEOUT}s: {last_error} (last step confirmed: "
                                "console back over the cable)")
            raise PushError(f"boot {state.boot_n} did not reach `{BOOT_OK}` within "
                            f"{BOOT_OK_TIMEOUT}s (last step confirmed: boot {state.boot_n} "
                            f"started with build {build}); see `lume dev log`")
        sleep(POLL_INTERVAL)
    problems = [p for check in (AFTER_BOOT_CHECKS if checks is None else checks)
                if (p := check(remote, state))]
    if problems:
        raise PushError(f"boot {state.boot_n} completed with build {build}, but: "
                        + "; ".join(problems))
    return state


def push(build: str = "latest", remote: Remote | None = None, yes: bool = False,
         extractor=extract_boot, out=print, wait: bool = True, sleep=time.sleep,
         now=time.monotonic, checks: list[AfterBootCheck] | None = None,
         console_wanted: str | None = None, dry_run: bool = False) -> int:
    build_dir = (images_dir(IMAGES["console"]) / build).resolve()
    list_path = build_dir / image.BOOT_LIST
    if not list_path.exists():
        raise PushError(f"{build_dir.name} has no {image.BOOT_LIST}: rebuild it "
                        "(`lume build console`) to push it")
    try:
        boot_list = manifests.read_boot_list(list_path)
    except manifests.ManifestError as e:
        raise PushError(str(e)) from None
    remote = remote or Remote()
    _drop_channel(remote)       # a push always starts on a fresh connection
    console = read_console(remote)
    out(f"console: {console.board}, build {console.build or '?'}, battery "
        f"{'?' if console.battery is None else f'{console.battery}%'}, card {console.device}")
    if refusal := console_refusal(console_name(console.board), console_wanted):
        raise PushError(f"{refusal}: nothing was sent")
    out(f"push:    build {build_dir.name}")
    if warning := lost_clusters_warning(console):
        out(warning)                    # only a warning: the push goes on (D3)
    if console.battery is not None and console.battery < MIN_BATTERY:
        raise PushError(f"battery at {console.battery}%: charge the console above "
                        f"{MIN_BATTERY}% first (a power cut while BOOT is swapped can leave "
                        "it unable to start)")
    panel1 = build_dir / PANEL1_IMAGE if console.board == "ga36" else None
    panel1_changed = False
    if panel1 is not None and panel1.exists():
        sectors = -(-panel1.stat().st_size // 512)
        on_card = remote.run(f"dd if={_q(console.device)} bs=512 skip={ANDROID_SECTOR} "
                             f"count={sectors} 2>/dev/null | head -c {panel1.stat().st_size} "
                             "| sha256sum | cut -d' ' -f1").strip()
        panel1_changed = on_card != _sha256(panel1)
    files = plan_files(boot_list, console, panel1_changed)
    if not files and not panel1_changed:
        same = console.boot_sums.get(manifests.VERSION_FILE) == dict(boot_list).get(
            manifests.VERSION_FILE)
        out("nothing to send: the console already runs this build" if same else
            "nothing to send: the console already has every file of this build (only "
            "VERSION differs)")
        return 0
    # the console checks every file against SHA256SUMS before BOOT changes, so an object
    # (named by its SHA256) is not hashed again here
    sources = object_sources(build_dir, files, extractor, out)
    sizes = {p: sources[p].stat().st_size for p, _ in files}
    if panel1_changed:
        sizes[PANEL1_IMAGE] = panel1.stat().st_size
    slot_state = read_slot_state(remote)
    plan = plan_slots(files, sources, boot_list, console, slot_state)
    reclaim = sum(plan.slot_sizes.get(p, 0) for p in plan.orphans)
    if dry_run:
        for line in dry_run_report(files, sizes, sources, plan, slot_state, panel1_changed):
            out(line)
        try:
            check_room(console, sizes, reclaim)
            out("room:     enough free space on BOOT")
        except PushError as e:
            out(f"room:     the push would stop here: {e}")
        return 0
    check_room(console, sizes, reclaim)
    out("files:   " + ", ".join(p for p, _ in files)
        + (f", {PANEL1_IMAGE} (sector {ANDROID_SECTOR})" if panel1_changed else ""))
    for c, gone in plan.migrate.items():
        out(f"migrate: {c} has its slot set since an earlier push: {', '.join(gone)} "
            "deleted after the swap")
    if not yes and input("Send them and reboot the console? [y/N] ").strip().lower() != "y":
        out("cancelled")
        return 1

    started = now()                     # the send time leaves out the confirmation
    remote_dir = f"{STAGING}/{build_dir.name}"
    remote.run(f"rm -rf {_q(STAGING)} && mkdir -p {_q(remote_dir)}")
    sums = "".join(f"{d}  {p}\n" for p, d in files)
    for p, _ in files:
        remote.run(f"mkdir -p {_q(str(Path(remote_dir, p).parent))} && "
                   f"cat > {_q(f'{remote_dir}/{p}')}", stdin=sources[p])
        out(f"sent:    {p}")
    if panel1_changed:
        remote.run(f"cat > {_q(f'{remote_dir}/{PANEL1_IMAGE}')}", stdin=panel1)
        sums += f"{_sha256(panel1)}  {PANEL1_IMAGE}\n"
    sums_file = ensure_dir(cache_dir() / "push") / "SHA256SUMS"
    sums_file.write_text(sums)
    remote.run(f"cat > {_q(f'{remote_dir}/SHA256SUMS')}", stdin=sums_file)
    digests = dict(files)
    if plan.slot_files or plan.manifests:
        # what BOOT must hold before any set is swapped: the slot files and each SLOTS.new
        boot_sums = sums_file.with_name(BOOT_SUMS)
        boot_sums.write_text("".join(f"{digests[p]}  {p}\n" for p in plan.slot_files)
                             + "".join(f"{digests[p]}  {p}.new\n" for p in plan.manifests))
        remote.run(f"cat > {_q(f'{remote_dir}/{BOOT_SUMS}')}", stdin=boot_sums)
    # 3. checked on the console itself: nothing on BOOT changes if one file differs
    remote.run(f"cd {_q(remote_dir)} && sha256sum -c SHA256SUMS >/dev/null")
    out("checked: SHA256 on the console")

    # 4. BOOT: the new slot files and SLOTS.new, checked; the other files one by one; each
    # console's set swapped by renames; VERSION last; then what no set cites any more
    remote.run("mount -o remount,rw /boot")
    ro_refused = None
    running = running_files(console.board)
    version = [p for p, _ in files if p == manifests.VERSION_FILE]
    others = [p for p, _ in files if p != manifests.VERSION_FILE
              and not is_slot_file(p) and not is_slots_manifest(p)]

    def copy(p: str) -> None:
        dest = f"/boot/{p}"
        new, old = _q(dest + ".new"), _q(dest + ".old")
        # a running file keeps its name as .old: deleting it while its loop holds it open
        # would leak its clusters when the console powers off (D1)
        keep_old = (f"{{ [ ! -e {_q(dest)} ] || mv {_q(dest)} {old}; }} && "
                    if p in running else "")
        remote.run(f"mkdir -p {_q(str(Path(dest).parent))} && "
                   f"cp {_q(f'{remote_dir}/{p}')} {new} && sync && "
                   f"{keep_old}mv {new} {_q(dest)} && sync")

    try:
        # the *.old/*.new of an earlier push: nothing holds them open after its reboot (D2);
        # SLOTS.old stays (the previous set)
        remote.run(STALE_CLEANUP)
        if plan.orphans:
            # slot files no SLOTS nor SLOTS.old cites (the set before the previous one, or
            # a push cut in the middle): room for the new ones
            remote.run(rm_command(plan.orphans))
        # new slot files never take the name of one in use (names by content)
        for p in plan.slot_files:
            copy(p)
        for p in plan.manifests:
            remote.run(f"mkdir -p {_q(str(Path('/boot', p).parent))} && "
                       f"cp {_q(f'{remote_dir}/{p}')} {_q(f'/boot/{p}.new')} && sync")
        if plan.slot_files or plan.manifests:
            # read back from the card, not from the page cache
            remote.run("sync && echo 3 > /proc/sys/vm/drop_caches && cd /boot && "
                       f"sha256sum -c {_q(f'{remote_dir}/{BOOT_SUMS}')} >/dev/null")
            out("checked: slot files and SLOTS.new on BOOT")
        for p in others:
            copy(p)
        if panel1_changed:
            size = panel1.stat().st_size
            remote.run(f"dd if={_q(f'{remote_dir}/{PANEL1_IMAGE}')} of={_q(console.device)} "
                       f"bs=512 seek={ANDROID_SECTOR} conv=notrunc,fsync 2>/dev/null && sync")
            back = remote.run(f"dd if={_q(console.device)} bs=512 skip={ANDROID_SECTOR} "
                              f"count={-(-size // 512)} 2>/dev/null | head -c {size} "
                              "| sha256sum | cut -d' ' -f1").strip()
            if back != _sha256(panel1):
                raise PushError("the boot image read back from sector "
                                f"{ANDROID_SECTOR} differs: do not reboot; write the card "
                                "with `lume flash --update` from the reader")
        for p in plan.manifests:
            c = p.split("/")[0]
            remote.run(swap_command(c, plan.current_usable[c]))
            out(f"swapped: {c}/SLOTS (the previous set is {c}/SLOTS.old)")
        for p in version:
            copy(p)
        # nothing below can leave a console without a set: a failure is only a warning
        gone = plan.after + [p for c in plan.migrate for p in plan.migrate[c]]
        if gone:
            try:
                remote.run(rm_command(gone))
                out("deleted: " + ", ".join(gone))
            except PushError as e:
                out(f"warning: could not delete what no set cites ({e}); the next push "
                    "tries again")
        for p in plan.kept_running:
            out(f"note: {p} kept: the console runs from it (its slot set did not mount, see "
                "`lume dev log`)")
    finally:
        try:
            remote.run("sync; mount -o remount,ro /boot")
        except PushError as e:
            # vfat refuses read-only while a deleted file is still open ("Resource busy",
            # GA36 2026-11-13). The running files keep their names as .old (D1), so this is
            # no longer expected: everything is written and synced, the push goes on (D5)
            ro_refused = e
    if ro_refused is not None:
        out("warning: BOOT stays read-write until the reboot: something still holds a "
            "deleted file on it open, so this boot may leave lost clusters (the next push "
            "checks)")
    remote.run(f"rm -rf {_q(STAGING)}")
    # the boot number before the reboot: the new boot must have another one (the console
    # clock is not reliable, so times are not compared)
    old_boot_n = (remote.run(READ_BOOT_N).strip() or None) if wait else None
    out("swapped: BOOT updated, rebooting the console")
    remote.run("(sleep 1; reboot) >/dev/null 2>&1 &")
    _drop_channel(remote)       # the master would hang on the dead connection
    if not wait:
        return 0
    rebooted = now()
    out(f"waiting: the console goes away and comes back (up to {GONE_TIMEOUT}s + "
        f"{BACK_TIMEOUT}s + {BOOT_OK_TIMEOUT}s)")
    if checks is None:
        expected = expected_fragments(boot_list, console.board, sources)
        checks = AFTER_BOOT_CHECKS + ([make_fragment_check(expected)] if expected else [])
    state = verify_boot(remote, build_dir.name, old_boot_n, sleep, now, checks)
    detail = state.boot_ok.split(BOOT_OK, 1)[-1].lstrip(": ").strip()
    out(f"ok: boot {state.boot_n} completed with build {build_dir.name}"
        + (f" ({detail})" if detail else "")
        + f"; send {_duration(rebooted - started)}, boot {_duration(now() - rebooted)}")
    return 0


def main_push(build: str, yes: bool, wait: bool = True, console: str | None = None,
              dry_run: bool = False, host: str | None = None) -> int:
    try:
        return push(build, Remote(host or CONSOLE_ADDR), yes, wait=wait, console_wanted=console, dry_run=dry_run)
    except PushError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
