"""Update a console over the USB cable: `r36os push [--build <timestamp>]` (usb-device-access D6).

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
4. on BOOT (remounted rw): the *.old/*.new of an earlier push deleted (nothing holds them
   open after its reboot); each file copied to <name>.new, synced and renamed over the old
   one, VERSION last, so an interrupted push leaves the old VERSION and the next push sends
   everything again. The SYSTEM and modules image of the running console are held open by
   their loop devices: the old one is renamed to <name>.old instead of being replaced,
   because vfat cannot free the clusters of an open file that lost its name (they leak
   when the console powers off, push-boot-swap D1). On the GA36, the boot image of panel
   1 at sector 172032 when it changed, read back and compared;
5. BOOT read-only again, the staging folder removed, reboot. If vfat still refuses
   read-only ("Resource busy"), something holds a deleted file open: warn that this boot
   may leave lost clusters, for the next push to check (D5).
6. unless `--no-wait` (build-speed D12): wait for the console to go away and come back over
   the cable, then check that a new boot started (boot number of /run/r36os/logs/boot-n,
   not the clock: the console clock is not reliable), that /boot/VERSION carries the pushed
   build and that events.log has `boot OK completed` for that boot; print `ok` with the
   send and boot times, or the step that diverged.

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

from r36os import image, manifests
from r36os.archive import images_dir, objects_dir
from r36os.paths import cache_dir, ensure_dir
from r36os.targets import IMAGES

CONSOLE_ADDR = "10.55.0.1"       # the console on the USB network (D5)
PROBE_TIMEOUT = 10               # seconds for one "does the console answer?" ssh probe
STAGING = "/storage/.lume-push"
MIN_BATTERY = 20
ANDROID_SECTOR = 172032          # GA36 kernel boot image (r36os.vendor.ANDROID_BOOT_SECTOR)
PANEL1_IMAGE = "ga36-android-boot-panel1.img"
CHUNK = 1 << 22
LOST_LIMIT = 32 << 20            # BOOT used (df) above what its files take (du): lost clusters
STALE_CLEANUP = (r"find /boot -type f \( -name '*.old' -o -name '*.new' \) -exec rm -f {} \; "
                 "&& sync")

# after the reboot (build-speed D12); measured 2026-11-16: ssh answers again ~40 s after the
# reboot, `boot OK completed` ~34 s from the kernel
GONE_TIMEOUT = 60                # seconds for the console to stop answering after the reboot
BACK_TIMEOUT = 180               # seconds for it to answer again over the cable
BOOT_OK_TIMEOUT = 120            # seconds, once back, for `boot OK completed` in events.log
POLL_INTERVAL = 2.0
BOOT_N = "/run/r36os/logs/boot-n"
EVENTS_LOG = "/storage/logs/events.log"
BOOT_OK = "boot OK completed"
READ_BOOT_N = f"cat {BOOT_N} 2>/dev/null || true"
# one line each: boot number, build of /boot/VERSION, last `boot OK completed` of that boot
BOOT_STATUS = (f"n=$(cat {BOOT_N} 2>/dev/null); echo \"${{n:--}}\"; "
               "sed -n 's/^build: //p' /boot/VERSION; "
               f"awk -v n=\"$n\" '$2 == n && /{BOOT_OK}/' {EVENTS_LOG} 2>/dev/null | tail -n 1")


def running_files(board: str) -> tuple[str, ...]:
    """BOOT files the running console keeps open by a loop device until it powers off: they
    are swapped through <name>.old and their old size stays taken until the next push."""
    return (f"{board}/SYSTEM", f"{board}/modules")


class PushError(RuntimeError):
    pass


class Remote:
    """Commands on the console over ssh (replaced by a fake in the tests).

    Root has no password on the USB cable (D4) and the console makes a new host key every
    boot, so nothing is checked against or written to the user's known_hosts."""

    def __init__(self, host: str = CONSOLE_ADDR):
        self.host = host
        # ServerAlive*: a connection that dies in the middle (the console rebooting) is
        # dropped in ~6 s; ConnectTimeout only covers opening it (J1, 2026-11-16: a probe
        # caught by the reboot hung for minutes)
        self.base = ["ssh", "-o", "UserKnownHostsFile=/dev/null",
                     "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=ERROR",
                     "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
                     "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2",
                     f"root@{host}"]

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
            return subprocess.run([*self.base, "true"], stdin=subprocess.DEVNULL,
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
cat /etc/r36os/board
b=""; for p in /sys/class/power_supply/*; do [ "$(cat $p/type 2>/dev/null)" = Battery ] && b=$(cat $p/capacity); done; echo "${b:--}"
df -Pk /storage | awk 'NR==2{print $4}'
df -Pk /boot | awk 'NR==2{print $4}'
awk '$2=="/boot"{print $1}' /proc/mounts | sed -E 's/p?[0-9]+$//'
find /boot -type f \( -name '*.old' -o -name '*.new' \) -exec du -k {} \; | awk '{s+=$1} END{print s+0}'
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
            "BOOT/FSCK*.REC, or `r36os flash --update`")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def extract_boot(build_dir: Path, wanted: list[str], runner=None) -> Path:
    """The BOOT files `wanted` of the archived image, in a staging folder of the cache,
    checked against boot-files.sha256."""
    from r36os import flash

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
    from r36os.container import Container, ensure_builder
    from r36os.targets import TARGETS

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


def check_room(console: Console, sizes: dict[str, int]) -> None:
    total = sum(sizes.values())
    if console.roms_free < total + (16 << 20):
        raise PushError(f"ROMS has {console.roms_free >> 20} MiB free, the push needs "
                        f"{total >> 20} MiB (plus 16 MiB) for /storage/.lume-push")
    # every file goes to <name>.new before the rename; the running SYSTEM and modules image
    # keep their old blocks as <name>.old until the next push (a loop device holds each one
    # open), and the *.old/*.new of the previous push are deleted before the swap
    need = (max(sizes.values(), default=0)
            + sum(sizes.get(p, 0) for p in running_files(console.board)))
    free = console.boot_free + console.boot_stale
    if free < need:
        raise PushError(f"BOOT has {free >> 20} MiB free"
                        + (f" (with {console.boot_stale >> 20} MiB of an earlier push)"
                           if console.boot_stale else "")
                        + f", the push needs {need >> 20} MiB to swap the files")


def _q(s: str) -> str:
    return shlex.quote(s)


# --- after the reboot (build-speed D12) -------------------------------------------------

@dataclass
class BootState:
    """What the console says about its current boot."""
    boot_n: str | None      # /run/r36os/logs/boot-n
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
AFTER_BOOT_CHECKS: list[AfterBootCheck] = []


def _duration(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}m{s % 60:02d}s" if s >= 60 else f"{s}s"


def verify_boot(remote, build: str, old_boot_n: str | None, sleep=time.sleep,
                now=time.monotonic, checks: list[AfterBootCheck] | None = None
                ) -> BootState:
    """Wait for the console to go away and come back over the cable, then check that a new
    boot started with `build` on /boot/VERSION and reached `boot OK completed`. Raises
    PushError naming the last step confirmed."""
    from r36os.dev import wait_for_console      # dev imports this module

    host = getattr(remote, "host", CONSOLE_ADDR)
    if not wait_for_console(host, GONE_TIMEOUT, POLL_INTERVAL, sleep, now,
                            probe=lambda: not remote.answers()):
        raise PushError(f"the console still answers {GONE_TIMEOUT}s after the reboot "
                        "(last step confirmed: reboot sent)")
    if not wait_for_console(host, BACK_TIMEOUT, POLL_INTERVAL, sleep, now,
                            probe=remote.answers):
        raise PushError(f"the console did not come back over the cable within "
                        f"{BACK_TIMEOUT}s (last step confirmed: the console went away for "
                        "the reboot)")
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
                            f"started with build {build}); see `r36os dev log`")
        sleep(POLL_INTERVAL)
    problems = [p for check in (AFTER_BOOT_CHECKS if checks is None else checks)
                if (p := check(remote, state))]
    if problems:
        raise PushError(f"boot {state.boot_n} completed with build {build}, but: "
                        + "; ".join(problems))
    return state


def push(build: str = "latest", remote: Remote | None = None, yes: bool = False,
         extractor=extract_boot, out=print, wait: bool = True, sleep=time.sleep,
         now=time.monotonic, checks: list[AfterBootCheck] | None = None) -> int:
    build_dir = (images_dir(IMAGES["console"]) / build).resolve()
    list_path = build_dir / image.BOOT_LIST
    if not list_path.exists():
        raise PushError(f"{build_dir.name} has no {image.BOOT_LIST}: rebuild it "
                        "(`r36os build console`) to push it")
    try:
        boot_list = manifests.read_boot_list(list_path)
    except manifests.ManifestError as e:
        raise PushError(str(e)) from None
    remote = remote or Remote()
    console = read_console(remote)
    out(f"console: {console.board}, build {console.build or '?'}, battery "
        f"{'?' if console.battery is None else f'{console.battery}%'}, card {console.device}")
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
    check_room(console, sizes)
    out("files:   " + ", ".join(p for p, _ in files)
        + (f", {PANEL1_IMAGE} (sector {ANDROID_SECTOR})" if panel1_changed else ""))
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
    # 3. checked on the console itself: nothing on BOOT changes if one file differs
    remote.run(f"cd {_q(remote_dir)} && sha256sum -c SHA256SUMS >/dev/null")
    out("checked: SHA256 on the console")

    # 4. BOOT, file by file, VERSION last
    remote.run("mount -o remount,rw /boot")
    ro_refused = None
    running = running_files(console.board)
    try:
        # the *.old/*.new of an earlier push: nothing holds them open after its reboot (D2)
        remote.run(STALE_CLEANUP)
        for p, _ in files:
            dest = f"/boot/{p}"
            new, old = _q(dest + ".new"), _q(dest + ".old")
            # a running file keeps its name as .old: deleting it while its loop holds it
            # open would leak its clusters when the console powers off (D1)
            keep_old = (f"{{ [ ! -e {_q(dest)} ] || mv {_q(dest)} {old}; }} && "
                        if p in running else "")
            remote.run(f"mkdir -p {_q(str(Path(dest).parent))} && "
                       f"cp {_q(f'{remote_dir}/{p}')} {new} && sync && "
                       f"{keep_old}mv {new} {_q(dest)} && sync")
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
                                "with `r36os flash --update` from the reader")
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
    if not wait:
        return 0
    rebooted = now()
    out(f"waiting: the console goes away and comes back (up to {GONE_TIMEOUT}s + "
        f"{BACK_TIMEOUT}s + {BOOT_OK_TIMEOUT}s)")
    state = verify_boot(remote, build_dir.name, old_boot_n, sleep, now, checks)
    detail = state.boot_ok.split(BOOT_OK, 1)[-1].lstrip(": ").strip()
    out(f"ok: boot {state.boot_n} completed with build {build_dir.name}"
        + (f" ({detail})" if detail else "")
        + f"; send {_duration(rebooted - started)}, boot {_duration(now() - rebooted)}")
    return 0


def main_push(build: str, yes: bool, wait: bool = True) -> int:
    try:
        return push(build, Remote(), yes, wait=wait)
    except PushError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
