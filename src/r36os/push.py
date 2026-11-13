"""Update a console over the USB cable: `r36os push [--build <timestamp>]` (usb-device-access D6).

The console must have BOOT/ssh/ from `r36os flash --ssh-key`. Steps, all through ssh to
root@10.55.0.1 with the known_hosts of this PC (r36os.sshkeys):

1. read the console: VERSION, board, battery, free space on ROMS and BOOT, and the SHA256
   of the files on BOOT; refuse below 20% battery;
2. take the BOOT files of the build out of the archived image (the list and SHA256 of
   boot-files.sha256, read back from the FAT when the image was built) and keep only the
   ones that differ from the console;
3. send them to /storage/.lume-push/<build>/ (ROMS) and check them there with
   `sha256sum -c`: nothing on BOOT changes if one differs;
4. on BOOT (remounted rw): each file copied to <name>.new, synced and renamed over the old
   one, VERSION last, so an interrupted push leaves the old VERSION and the next push sends
   everything again; on the GA36, the boot image of panel 1 at sector 172032 when it
   changed, read back and compared;
5. BOOT read-only again, the staging folder removed, reboot.

There is no rsync on the console: each file goes as `cat > file` over ssh.
"""

from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from r36os import image, sshkeys
from r36os.archive import images_dir
from r36os.paths import cache_dir, ensure_dir
from r36os.targets import IMAGES

STAGING = "/storage/.lume-push"
MIN_BATTERY = 20
ANDROID_SECTOR = 172032          # GA36 kernel boot image (r36os.vendor.ANDROID_BOOT_SECTOR)
PANEL1_IMAGE = "ga36-android-boot-panel1.img"
CHUNK = 1 << 22


class PushError(RuntimeError):
    pass


class Remote:
    """Commands on the console over ssh (replaced by a fake in the tests)."""

    def __init__(self, host: str = sshkeys.CONSOLE_ADDR, identity: Path | None = None):
        known = sshkeys.known_hosts_path()
        if not known.exists():
            raise PushError(f"no {known}: write the card once with "
                            "`r36os flash console /dev/sdX --update --ssh-key ~/.ssh/<key>.pub`")
        self.base = ["ssh", "-o", f"UserKnownHostsFile={known}", "-o", "StrictHostKeyChecking=yes",
                     "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
        if identity is not None:
            self.base += ["-i", str(identity), "-o", "IdentitiesOnly=yes"]
        self.base.append(f"root@{host}")

    def run(self, cmd: str, stdin: Path | None = None) -> str:
        with (stdin.open("rb") if stdin else open("/dev/null", "rb")) as f:
            r = subprocess.run([*self.base, cmd], stdin=f, capture_output=True)
        if r.returncode != 0:
            err = (r.stderr or b"").decode(errors="replace").strip()
            if r.returncode == 255:
                raise PushError(f"ssh to the console failed: {err or 'no answer'} (is the cable "
                                "on the OTG port, and the key of `flash --ssh-key` yours?)")
            raise PushError(f"on the console, `{cmd}` failed ({r.returncode}): {err}")
        return r.stdout.decode(errors="replace")


@dataclass
class Console:
    board: str
    build: str
    battery: int | None
    roms_free: int          # bytes
    boot_free: int
    device: str             # the card, e.g. /dev/mmcblk0
    boot_sums: dict[str, str]


_PROBE = r"""
sed -n 's/^build: //p' /boot/VERSION
cat /etc/r36os/board
b=""; for p in /sys/class/power_supply/*; do [ "$(cat $p/type 2>/dev/null)" = Battery ] && b=$(cat $p/capacity); done; echo "${b:--}"
df -Pk /storage | awk 'NR==2{print $4}'
df -Pk /boot | awk 'NR==2{print $4}'
awk '$2=="/boot"{print $1}' /proc/mounts | sed -E 's/p?[0-9]+$//'
cd /boot && find . -type f ! -name '*.new' | sed 's|^\./||' | while read -r f; do sha256sum "$f"; done
"""


def read_console(remote: Remote) -> Console:
    lines = remote.run(_PROBE).splitlines()
    if len(lines) < 6:
        raise PushError(f"unexpected answer from the console: {lines!r}")
    sums = {}
    for line in lines[6:]:
        digest, _, name = line.partition("  ")
        if name:
            sums[name] = digest
    battery = None if lines[2].strip() in ("", "-") else int(lines[2])
    return Console(board=lines[1].strip(), build=lines[0].strip(), battery=battery,
                   roms_free=int(lines[3]) * 1024, boot_free=int(lines[4]) * 1024,
                   device=lines[5].strip(), boot_sums=sums)


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


def plan_files(boot_list: list[tuple[str, str]], console: Console) -> list[tuple[str, str]]:
    """(path, sha256) to send: the ones the console does not have, in list order (VERSION
    last). A build that is already on the console sends nothing."""
    return [(p, d) for p, d in boot_list if console.boot_sums.get(p) != d]


def check_room(console: Console, sizes: dict[str, int]) -> None:
    total = sum(sizes.values())
    if console.roms_free < total + (16 << 20):
        raise PushError(f"ROMS has {console.roms_free >> 20} MiB free, the push needs "
                        f"{total >> 20} MiB (plus 16 MiB) for /storage/.lume-push")
    # every file goes to <name>.new before the rename; the running SYSTEM keeps its old
    # blocks until the reboot (the loop device holds it open)
    running = f"{console.board}/SYSTEM"
    need = max(sizes.values(), default=0) + sizes.get(running, 0)
    if console.boot_free < need:
        raise PushError(f"BOOT has {console.boot_free >> 20} MiB free, the push needs "
                        f"{need >> 20} MiB to swap the files")


def _q(s: str) -> str:
    return shlex.quote(s)


def push(build: str = "latest", remote: Remote | None = None, yes: bool = False,
         extractor=extract_boot, out=print) -> int:
    build_dir = (images_dir(IMAGES["console"]) / build).resolve()
    list_path = build_dir / image.BOOT_LIST
    if not list_path.exists():
        raise PushError(f"{build_dir.name} has no {image.BOOT_LIST}: rebuild it "
                        "(`r36os build console`) to push it")
    boot_list = image.read_boot_list(list_path)
    remote = remote or Remote()
    console = read_console(remote)
    out(f"console: {console.board}, build {console.build or '?'}, battery "
        f"{'?' if console.battery is None else f'{console.battery}%'}, card {console.device}")
    out(f"push:    build {build_dir.name}")
    if console.battery is not None and console.battery < MIN_BATTERY:
        raise PushError(f"battery at {console.battery}%: charge the console above "
                        f"{MIN_BATTERY}% first (a power cut while BOOT is swapped can leave "
                        "it unable to start)")
    files = plan_files(boot_list, console)
    panel1 = build_dir / PANEL1_IMAGE if console.board == "ga36" else None
    panel1_changed = False
    if panel1 is not None and panel1.exists():
        sectors = -(-panel1.stat().st_size // 512)
        on_card = remote.run(f"dd if={_q(console.device)} bs=512 skip={ANDROID_SECTOR} "
                             f"count={sectors} 2>/dev/null | head -c {panel1.stat().st_size} "
                             "| sha256sum | cut -d' ' -f1").strip()
        panel1_changed = on_card != _sha256(panel1)
    if not files and not panel1_changed:
        out("nothing to send: the console already runs this build")
        return 0
    stage = extractor(build_dir, [p for p, _ in files]) if files else None
    sizes = {}
    for p, digest in files:
        local = stage / p
        if _sha256(local) != digest:
            raise PushError(f"{p} read from the image does not match {image.BOOT_LIST}")
        sizes[p] = local.stat().st_size
    if panel1_changed:
        sizes[PANEL1_IMAGE] = panel1.stat().st_size
    check_room(console, sizes)
    out("files:   " + ", ".join(p for p, _ in files)
        + (f", {PANEL1_IMAGE} (sector {ANDROID_SECTOR})" if panel1_changed else ""))
    if not yes and input("Send them and reboot the console? [y/N] ").strip().lower() != "y":
        out("cancelled")
        return 1

    remote_dir = f"{STAGING}/{build_dir.name}"
    remote.run(f"rm -rf {_q(STAGING)} && mkdir -p {_q(remote_dir)}")
    sums = "".join(f"{d}  {p}\n" for p, d in files)
    for p, _ in files:
        remote.run(f"mkdir -p {_q(str(Path(remote_dir, p).parent))} && "
                   f"cat > {_q(f'{remote_dir}/{p}')}", stdin=stage / p)
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
    try:
        for p, _ in files:
            dest = f"/boot/{p}"
            remote.run(f"mkdir -p {_q(str(Path(dest).parent))} && "
                       f"cp {_q(f'{remote_dir}/{p}')} {_q(dest + '.new')} && sync && "
                       f"mv {_q(dest + '.new')} {_q(dest)} && sync")
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
        remote.run("sync; mount -o remount,ro /boot")
    remote.run(f"rm -rf {_q(STAGING)}")
    out("swapped: BOOT updated, rebooting the console")
    remote.run("(sleep 1; reboot) >/dev/null 2>&1 &")
    return 0


def main_push(build: str, yes: bool, identity: Path | None) -> int:
    try:
        return push(build, Remote(identity=identity), yes)
    except (PushError, sshkeys.SshKeyError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
