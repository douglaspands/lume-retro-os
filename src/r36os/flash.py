"""Writing the card: `r36os flash <image> <device> [--update] [--build <timestamp>] [--eject]`.

Two modes:

- full (default): writes the whole image. Erases the card, including the ROMS partition,
  then creates ROMS (exFAT) on all the remaining space of the card, with the default
  folders (roms/<system> for every system of the catalog, bios, saves, states,
  screenshots, system) and the factory RetroArch config, so games can be copied before
  the first boot. The console's first boot finds ROMS ready and only checks it (the
  initramfs creates it only when it is missing);
- `--update`: writes only the boot area (from 8 KiB to BOOT) and the BOOT partition.
  Sector 0 (the partition table) and ROMS (games, saves, settings, logs) are not
  touched. It only accepts a card whose partition 1 has the same start, size and disk
  signature as the image, that is, a card written before with an image of this layout.
  The console image has a 2 GiB BOOT partition, so a card written before with a 1 GiB
  BOOT (the older ga36 image) is refused and needs a full write.

Pass `--eject` to safely unmount and power off the device after writing and verification.


The image comes from out/images/<image>/<timestamp>/ (default: `latest`). Before
writing, the command checks that the device is a removable disk, unmounts its partitions
and asks for confirmation; after writing, it reads back and compares the SHA256 of what
was written. Writing uses `sudo dd`, so run it in a terminal (sudo asks for the password).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from r36os import lang
from r36os.archive import images_dir
from r36os.image import boot_sectors, boot_start
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir
from r36os.targets import ImageTarget

_ENV = dict(os.environ, LC_ALL="C", LANG="C")


SECTOR = 512
BOOTLOADER_START = 8192             # sector 0 (MBR) is never written in update mode
CHUNK = 1 << 22
ALIGN = 2048                        # 1 MiB, as the initramfs (initramfs/lib/storage.sh)
MIN_ROMS = 131072                   # 64 MiB, as the initramfs
OVERLAY = REPO_ROOT / "rootfs/overlay"
CATALOG = OVERLAY / "usr/share/r36os/systems.json"
FACTORY = OVERLAY / "usr/share/r36os/factory"
BASE_FOLDERS = ("bios", "saves", "states", "screenshots", "system")


class FlashError(RuntimeError):
    pass


@dataclass(frozen=True)
class Mbr:
    disk_id: int
    p1_start: int     # sectors
    p1_sectors: int
    p1_type: int
    has_p2: bool

    @classmethod
    def parse(cls, sector0: bytes) -> "Mbr":
        if len(sector0) < SECTOR or sector0[510:512] != b"\x55\xaa":
            raise FlashError("sector 0 has no valid MBR partition table")
        disk_id = struct.unpack_from("<I", sector0, 440)[0]
        p1 = sector0[446:462]
        p2 = sector0[462:478]
        start, size = struct.unpack_from("<II", p1, 8)
        return cls(disk_id, start, size, p1[4], p2[4] != 0)


FULL_WRITE_HINT = ("this card needs a full write (without --update), which erases ROMS: "
                   "copy your games and saves to the PC first")


def check_update(image: Mbr, card: Mbr) -> None:
    """Update mode only works on a card whose partition 1 matches the image."""
    if card.disk_id != image.disk_id:
        raise FlashError(f"disk signature {card.disk_id:08x} differs from the image "
                         f"({image.disk_id:08x}), so the card has another layout; "
                         f"{FULL_WRITE_HINT}")
    if (card.p1_start, card.p1_sectors) != (image.p1_start, image.p1_sectors):
        raise FlashError(f"card partition 1 at {card.p1_start}+{card.p1_sectors} sectors, "
                         f"the image uses {image.p1_start}+{image.p1_sectors}; "
                         f"{FULL_WRITE_HINT}")


def update_regions(target: ImageTarget | str) -> list[tuple[int, int]]:
    """(offset, bytes) written in update mode: boot area and BOOT. Never sector 0.

    The boot area goes from 8 KiB to the start of BOOT: the bootloader (16 MiB on the vm)
    or, on the console, the 128 MiB of both factory chains with the Android boot image.
    """
    boot_offset = boot_start(target) * SECTOR
    return [(BOOTLOADER_START, boot_offset - BOOTLOADER_START),
            (boot_offset, boot_sectors(target) * SECTOR)]


def roms_layout(card_sectors: int, image: Mbr) -> tuple[int, int]:
    """(start, sectors) of ROMS: from the first 1 MiB boundary after BOOT to the card end.

    The same rule as the initramfs (free_start in initramfs/lib/storage.sh), so a card
    prepared here looks to the console exactly like one it prepared itself.
    """
    start = (image.p1_start + image.p1_sectors + ALIGN - 1) // ALIGN * ALIGN
    sectors = card_sectors - start
    if sectors < MIN_ROMS:
        raise FlashError(f"only {sectors * SECTOR // 2**20} MiB left after BOOT, "
                         f"ROMS needs at least {MIN_ROMS * SECTOR // 2**20} MiB")
    return start, sectors


def build_language(zst: Path) -> str:
    """Factory menu language of the build (build.json next to the image), default English."""
    try:
        return json.loads((zst.parent / "build.json").read_text()).get("language") or lang.DEFAULT
    except (OSError, ValueError):
        return lang.DEFAULT


def populate_roms(root: Path, language: str = lang.DEFAULT) -> None:
    """Default folders and factory config on a mounted ROMS, as the first boot makes them.

    roms/<id> for every system of the catalog and the base folders (make_folders in the
    initramfs), and system/retroarch/ from the factory config with the build's language
    (what r36os-persist seeds on a card without system/retroarch/).
    """
    ids = [s["id"] for s in json.loads(CATALOG.read_text())["systems"]]
    for sid in ids:
        (root / "roms" / sid).mkdir(parents=True, exist_ok=True)
    for name in BASE_FOLDERS:
        (root / name).mkdir(parents=True, exist_ok=True)
    retro = lang.retro_language(language)
    for src in sorted(FACTORY.rglob("*")):
        dest = root / "system" / src.relative_to(FACTORY)
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = src.read_text()
        if src.name == "retroarch.cfg":
            text = re.sub(r'^user_language = .*$', f'user_language = "{retro}"', text,
                          flags=re.M)
        dest.write_text(text)


def _part_node(device: str, n: int) -> str:
    return f"{device}p{n}" if device[-1].isdigit() else f"{device}{n}"


def _mountpoint(node: str) -> str | None:
    for line in Path("/proc/mounts").read_text().splitlines():
        fields = line.split()
        if fields[0] == node:
            return fields[1].replace("\\040", " ")
    return None


def _mount_roms(node: str, wait: float = 5.0) -> str:
    """Mount point of the new ROMS, mounting it if the desktop did not.

    Right after formatting, the desktop (udisks) often automounts the new partition by
    itself; a mount of ours racing with it fails with "already mounted". So: let udev
    settle, take the automount if it shows up, and only then mount it ourselves (a failed
    mount is fine if the automount won the race meanwhile).
    """
    subprocess.run(["udevadm", "settle", "--timeout=10"], check=False, env=_ENV,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + wait
    while (mp := _mountpoint(node)) is None and time.monotonic() < deadline:
        time.sleep(0.2)
    if mp is not None:
        return mp
    r = subprocess.run(["udisksctl", "mount", "-b", node, "--no-user-interaction"],
                       capture_output=True, text=True, env=_ENV)
    for _ in range(25):
        if (mp := _mountpoint(node)) is not None:
            return mp
        time.sleep(0.2)
    raise FlashError(f"could not mount {node} to create the folders: "
                     f"{(r.stdout + r.stderr).strip() or 'not mounted'}")


def _create_roms(device: str, img: Path, language: str) -> None:
    """Partition 2 (exFAT, label ROMS) on the rest of the card, with folders and config."""
    with img.open("rb") as f:
        image_mbr = Mbr.parse(f.read(SECTOR))
    card_sectors = int((Path("/sys/block") / Path(device).name / "size").read_text())
    start, sectors = roms_layout(card_sectors, image_mbr)
    print(f"ROMS: {sectors * SECTOR / 1e9:.1f} GB (sectors {start}+{sectors})")
    subprocess.run(["sudo", "sfdisk", "--append", "--no-reread", "-q", device],
                   input=f"start={start}, size={sectors}, type=7\n", text=True,
                   check=True, env=_ENV)
    _rereadpt(device)
    node = _part_node(device, 2)
    for _ in range(50):
        if Path(node).is_block_device():
            break
        time.sleep(0.1)
    else:
        raise FlashError(f"{node} did not appear after writing the partition table")
    # the desktop may automount the new partition: it must be free while it is formatted
    _unmount(device)
    subprocess.run(["sudo", "mkfs.exfat", "-L", "ROMS", node], check=True,
                   stdout=subprocess.DEVNULL, env=_ENV)
    mp = _mount_roms(node)
    populate_roms(Path(mp), language)
    subprocess.run(["sync", "-f", mp], check=False, env=_ENV)
    subprocess.run(["udisksctl", "unmount", "-b", node], check=True,
                   stdout=subprocess.DEVNULL, env=_ENV)
    # read-only check of what was written (the USB reader 14cd:125d once corrupted small
    # writes: a problem shows here, not on the console)
    r = subprocess.run(["sudo", "fsck.exfat", "-n", node], capture_output=True, text=True,
                       env=_ENV)
    if r.returncode != 0:
        raise FlashError(f"ROMS check failed after creating it (fsck.exfat exit "
                         f"{r.returncode}): {r.stdout.strip()} {r.stderr.strip()}")


def find_image(target: ImageTarget, build: str = "latest") -> Path:
    d = images_dir(target) / build
    found = sorted(d.glob(f"{target.name}-*.img.zst")) if d.is_dir() else []
    if len(found) != 1:
        raise FlashError(f"no image in {d} (build it with: uv run r36os build {target.name})")
    return found[0]


def mark_flashed(build_dir: Path) -> None:
    """Point out/images/<image>/flashed at the build just written to a card (`clean` keeps it)."""
    link = build_dir.parent / "flashed"
    link.unlink(missing_ok=True)
    link.symlink_to(build_dir.name)


def _decompress(zst: Path) -> Path:
    """Decompress into the cache (reused if the same build is already there)."""
    from compression import zstd

    dest = ensure_dir(cache_dir() / "flash") / zst.name.removesuffix(".zst")
    if not dest.exists() or dest.stat().st_mtime < zst.stat().st_mtime:
        for old in dest.parent.glob("*.img"):
            old.unlink()
        tmp = dest.with_suffix(".part")
        with zstd.open(zst, "rb") as fin, tmp.open("wb") as fout:
            shutil.copyfileobj(fin, fout, CHUNK)
        tmp.replace(dest)
    return dest


def _sha256_file(path: Path, offset: int, length: int) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        f.seek(offset)
        left = length
        while left and (chunk := f.read(min(CHUNK, left))):
            h.update(chunk)
            left -= len(chunk)
    return h.hexdigest()


def _sudo_read(device: str, offset: int, length: int) -> bytes | str:
    """Read from the device with sudo; return the bytes (short) or the sha256 (long)."""
    cmd = ["sudo", "dd", f"if={device}", "bs=4M", "iflag=skip_bytes,count_bytes",
           f"skip={offset}", f"count={length}", "status=none"]
    if length <= SECTOR:
        return subprocess.run(cmd, check=True, capture_output=True, env=_ENV).stdout
    h = hashlib.sha256()
    bytes_read = 0
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, env=_ENV) as p:
        assert p.stdout is not None
        while chunk := p.stdout.read(CHUNK):
            bytes_read += len(chunk)
            h.update(chunk)
    if p.returncode != 0:
        raise FlashError(f"failed to read {device} at {offset}+{length} (exit code {p.returncode})")
    if bytes_read != length:
        raise FlashError(f"read {bytes_read} bytes from {device} at {offset}, expected {length}")
    return h.hexdigest()



def _sudo_write(img: Path, device: str, offset: int, length: int) -> None:
    subprocess.run(
        ["sudo", "dd", f"if={img}", f"of={device}", "bs=4M",
         "iflag=skip_bytes,count_bytes", "oflag=seek_bytes",
         f"skip={offset}", f"seek={offset}", f"count={length}",
         "conv=notrunc,fsync", "status=progress"], check=True, env=_ENV)


# USB card readers known to corrupt cards: the 14cd:125d ("Mass Storage Device") wrote
# its own USB command blocks ("USBC") into small writes (ROMS boot sector, BOOT FSINFO).
BAD_READERS = {("14cd", "125d"): "writes USB commands (\"USBC\") into small writes"}


def usb_reader_ids(device: str, sys_root: Path = Path("/sys")) -> tuple[str, str] | None:
    """(idVendor, idProduct) of the USB device behind a block device, or None (not USB)."""
    node = (sys_root / "block" / Path(device).name / "device").resolve()
    for parent in [node, *node.parents]:
        vendor, product = parent / "idVendor", parent / "idProduct"
        if vendor.is_file() and product.is_file():
            return vendor.read_text().strip().lower(), product.read_text().strip().lower()
        if parent == sys_root:
            break
    return None


def reader_warning(device: str, sys_root: Path = Path("/sys")) -> str | None:
    """Warning text when the card sits in a reader known to corrupt cards."""
    ids = usb_reader_ids(device, sys_root)
    if ids in BAD_READERS:
        return (f"warning: the card reader {ids[0]}:{ids[1]} is known to corrupt cards "
                f"({BAD_READERS[ids]}); use another reader if you can, and check the card "
                f"afterwards (sudo fsck.exfat -n {_part_node(device, 2)})")
    return None


def _check_device(device: str) -> str:
    """A whole, removable disk; return a description for the confirmation."""
    name = Path(device).name
    sys_block = Path("/sys/block") / name
    if not Path(device).is_block_device() or not sys_block.exists():
        raise FlashError(f"{device} is not a whole disk (use /dev/sdX, not /dev/sdX1)")
    if (sys_block / "removable").read_text().strip() != "1":
        raise FlashError(f"{device} is not removable: for safety, only cards and USB readers")
    size = int((sys_block / "size").read_text()) * SECTOR
    model = (sys_block / "device/model").read_text().strip() if (sys_block / "device/model").exists() else "?"
    return f"{device} ({model}, {size / 1e9:.1f} GB)"


def _unmount(device: str) -> None:
    mounted = [line.split()[0] for line in Path("/proc/mounts").read_text().splitlines()
               if line.startswith(device)]
    for part in mounted:
        subprocess.run(["udisksctl", "unmount", "-b", part], check=True, env=_ENV)


def _eject(device: str) -> bool:
    """Safely flush, unmount and power off the device (udisksctl power-off or eject).

    Returns True when the device was powered off or ejected.
    """
    try:
        mounts = [line.split()[1] for line in Path("/proc/mounts").read_text().splitlines()
                  if line.startswith(device)]
        for mp in mounts:
            subprocess.run(["sync", "-f", mp], env=_ENV, check=False)
    except OSError:
        pass
    _unmount(device)
    # extra flush only if sudo needs no password (cached by a flash just before): never
    # prompts. Unmounting and udisksctl power-off already flush everything without root.
    subprocess.run(["sudo", "-n", "blockdev", "--flushbufs", device],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=_ENV, check=False)
    subprocess.run(["sync"], env=_ENV, check=False)
    rc = subprocess.run(["udisksctl", "power-off", "-b", device],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        env=_ENV).returncode
    if rc != 0:
        rc = subprocess.run(["eject", device], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, check=False, env=_ENV).returncode
    return rc == 0



def _wipe_disk(device: str, img_size: int) -> None:
    """Wipe old partition tables and stale signatures beyond the image."""
    subprocess.run(["sudo", "wipefs", "-a", device],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=_ENV, check=False)
    subprocess.run(
        ["sudo", "dd", "if=/dev/zero", f"of={device}", "bs=4M", "count=4",
         f"seek={img_size}", "oflag=seek_bytes", "conv=notrunc"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=_ENV, check=False)


def _rereadpt(device: str) -> None:
    """Inform the kernel that the partition table has changed."""
    subprocess.run(["sudo", "blockdev", "--rereadpt", device],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   env=_ENV, check=False)


def flash(target: ImageTarget, device: str, update: bool = False, build: str = "latest",
          yes: bool = False, eject: bool = False) -> int:
    zst = find_image(target, build)
    desc = _check_device(device)
    mode = "UPDATE (boot area + BOOT; ROMS kept)" if update else \
        "FULL (erases the whole card, including ROMS, then creates an empty ROMS)"
    print(f"image: {zst}\ncard:  {desc}\nmode:  {mode}")
    if warning := reader_warning(device):
        print(warning)
    if not yes:
        answer = input(f"Type the device name ({Path(device).name}) to confirm: ")
        if answer.strip() != Path(device).name:
            print("cancelled")
            return 1
    img = _decompress(zst)
    _unmount(device)

    if update:
        with img.open("rb") as f:
            image_mbr = Mbr.parse(f.read(SECTOR))
        card_mbr = Mbr.parse(_sudo_read(device, 0, SECTOR))
        check_update(image_mbr, card_mbr)
        if not card_mbr.has_p2:
            print("note: the card has no ROMS partition yet (it is created on the next boot)")
        regions = update_regions(target)
    else:
        _wipe_disk(device, img.stat().st_size)
        regions = [(0, img.stat().st_size)]

    for offset, length in regions:
        _sudo_write(img, device, offset, length)
    subprocess.run(["sync"], check=True, env=_ENV)

    if not update:
        _rereadpt(device)


    for offset, length in regions:
        actual_hash = _sudo_read(device, offset, length)
        expected_hash = _sha256_file(img, offset, length)
        if actual_hash != expected_hash:
            raise FlashError(
                f"verification failed at {offset}+{length}: "
                f"expected {expected_hash[:16]}..., got {actual_hash[:16]}...: write it again"
            )

    if not update:
        _create_roms(device, img, build_language(zst))
    mark_flashed(zst.parent)

    if eject:
        _eject(device)
        print(f"ok: written, verified and safely ejected ({zst.parent.name}).")
    else:
        print(f"ok: written and verified ({zst.parent.name}). You can remove the card.")
    return 0


def main_eject(device: str) -> int:
    """`r36os eject <device>`: the safe eject of `flash --eject`, on its own (after copying
    games, for example). Only whole removable disks, as `flash`."""
    try:
        desc = _check_device(device)
        if _eject(device):
            print(f"ok: {desc} flushed, unmounted and powered off; you can remove the card.")
            return 0
        print(f"error: {desc} was flushed and unmounted, but could not be powered off "
              f"(udisksctl power-off and eject failed); wait a few seconds before removing it",
              file=sys.stderr)
        return 1
    except (FlashError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


def main_flash(target: ImageTarget, device: str, update: bool, build: str, yes: bool,
               eject: bool = False) -> int:
    try:
        return flash(target, device, update, build, yes, eject)
    except (FlashError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

