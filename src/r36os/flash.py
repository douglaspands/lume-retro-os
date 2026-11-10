"""Writing the card: `r36os flash <target> <device> [--update] [--build <timestamp>]`.

Two modes:

- full (default): writes the whole image. Erases the card, including the ROMS partition;
- `--update`: writes only the boot area (from 8 KiB to BOOT) and the BOOT partition.
  Sector 0 (the partition table) and ROMS (games, saves, settings, logs) are not
  touched. It only accepts a card whose partition 1 has the same start, size and disk
  signature as the image, that is, a card written before with an image of this target.

The image comes from out/images/<target>/<timestamp>/ (default: `latest`). Before
writing, the command checks that the device is a removable disk, unmounts its partitions
and asks for confirmation; after writing, it reads back and compares the SHA256 of what
was written. Writing uses `sudo dd`, so run it in a terminal (sudo asks for the password).
"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from r36os.archive import images_dir
from r36os.image import BOOT_SECTORS, boot_start
from r36os.paths import cache_dir, ensure_dir
from r36os.targets import Target

SECTOR = 512
BOOTLOADER_START = 8192             # sector 0 (MBR) is never written in update mode
BOOT_BYTES = BOOT_SECTORS * SECTOR  # 1 GiB
CHUNK = 1 << 22


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


def check_update(image: Mbr, card: Mbr) -> None:
    """Update mode only works on a card whose partition 1 matches the image."""
    if card.disk_id != image.disk_id:
        raise FlashError(f"disk signature {card.disk_id:08x} differs from the image "
                         f"({image.disk_id:08x}): the card was not written with this target")
    if (card.p1_start, card.p1_sectors) != (image.p1_start, image.p1_sectors):
        raise FlashError(f"card partition 1 at {card.p1_start}+{card.p1_sectors} sectors, "
                         f"the image uses {image.p1_start}+{image.p1_sectors}")


def update_regions(target: Target | str) -> list[tuple[int, int]]:
    """(offset, bytes) written in update mode: boot area and BOOT. Never sector 0.

    The boot area goes from 8 KiB to the start of BOOT: the bootloader (16 MiB by default)
    or, on the GA36, the vendor area with the Android boot image (128 MiB).
    """
    boot_offset = boot_start(target) * SECTOR
    return [(BOOTLOADER_START, boot_offset - BOOTLOADER_START), (boot_offset, BOOT_BYTES)]


def find_image(target: Target, build: str = "latest") -> Path:
    d = images_dir(target) / build
    found = sorted(d.glob(f"{target.name}-*.img.zst")) if d.is_dir() else []
    if len(found) != 1:
        raise FlashError(f"no image in {d} (build it with: uv run r36os build {target.name})")
    return found[0]


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
        return subprocess.run(cmd, check=True, capture_output=True).stdout
    h = hashlib.sha256()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as p:
        while chunk := p.stdout.read(CHUNK):
            h.update(chunk)
    if p.returncode:
        raise FlashError(f"failed to read {device}")
    return h.hexdigest()


def _sudo_write(img: Path, device: str, offset: int, length: int) -> None:
    subprocess.run(
        ["sudo", "dd", f"if={img}", f"of={device}", "bs=4M",
         "iflag=skip_bytes,count_bytes", "oflag=seek_bytes",
         f"skip={offset}", f"seek={offset}", f"count={length}",
         "conv=notrunc,fsync", "status=progress"], check=True)


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
        subprocess.run(["udisksctl", "unmount", "-b", part], check=True)


def flash(target: Target, device: str, update: bool = False, build: str = "latest",
          yes: bool = False) -> int:
    zst = find_image(target, build)
    desc = _check_device(device)
    mode = "UPDATE (boot area + BOOT; ROMS kept)" if update else \
        "FULL (erases the whole card, including ROMS)"
    print(f"image: {zst}\ncard:  {desc}\nmode:  {mode}")
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
        regions = [(0, img.stat().st_size)]

    for offset, length in regions:
        _sudo_write(img, device, offset, length)
    subprocess.run(["sync"], check=True)

    for offset, length in regions:
        if _sudo_read(device, offset, length) != _sha256_file(img, offset, length):
            raise FlashError(f"verification failed at {offset}+{length}: write it again")
    print(f"ok: written and verified ({zst.parent.name}). You can remove the card.")
    return 0


def main_flash(target: Target, device: str, update: bool, build: str, yes: bool) -> int:
    try:
        return flash(target, device, update, build, yes)
    except (FlashError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
