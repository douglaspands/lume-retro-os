"""GA36 vendor bootloader (D5): the boot area of the factory card.

The GA36 is only proven to boot with the vendor chain (Allwinner boot0 and U-Boot 2017)
that comes on its factory card. It takes the first 128 MiB of the card:

| sector | contents                                                         |
|--------|------------------------------------------------------------------|
| 16     | boot0 (eGON.BT0)                                                 |
| ~38192 | vendor U-Boot 2017                                               |
| 40960  | Allwinner partition table (softw411), read by the U-Boot         |
| 73728  | "bootloader" FAT (script.bin, logo)                              |
| 139264 | U-Boot env                                                       |
| 172032 | "boot": Android boot image loaded by the U-Boot (here, ours)     |

These binaries are closed and stay out of git: the build reads them from a dump of the
device's original card (its first 128 MiB) given in R36OS_GA36_FACTORY, keeps the 128 MiB
in the cache and checks the SHA256 (without sector 0, the MBR, which is always ours).
"""

from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path

from r36os.paths import cache_dir, ensure_dir

SECTOR = 512
AREA_SECTORS = 262144            # 128 MiB
ANDROID_BOOT_SECTOR = 172032     # "boot" partition of the softw411 table
ANDROID_BOOT_MAX = 65536 * SECTOR  # 32 MiB
# SHA256 of sectors 1..262143 of the GA36-MB V1.2 factory card (vendor boot area of the
# 2026-04-16 factory firmware)
AREA_SHA256 = "c915f899c4e110ad7d1ad35efa853708ab9d5a127ddb18c5118f0716803f607a"
ENV_VAR = "R36OS_GA36_FACTORY"


BOOT0_SECTOR = 16
BOOT0_FACTORY_SIZE = 32 * 1024   # sectors 16-79 on the factory card
BOOT0_SHRUNK_SIZE = 24 * 1024    # sectors 16-63: the R36S idbloader starts at sector 64
EGON_STAMP = 0x5F0A6C39          # checksum field value while the checksum is computed


class VendorAreaError(RuntimeError):
    pass


def egon_checksum(boot0: bytes) -> int:
    """eGON checksum: 32-bit sum of all words, with the checksum field (0x0C) = stamp."""
    if len(boot0) % 4:
        raise VendorAreaError("boot0 size is not a multiple of 4")
    words = list(struct.unpack(f"<{len(boot0) // 4}I", boot0))
    words[3] = EGON_STAMP
    return sum(words) & 0xFFFFFFFF


def shrink_boot0(area: bytearray) -> None:
    """Shrink the factory boot0 at sector 16 to 24 KiB in place (design D3).

    The factory boot0 declares 32 KiB, but its code ends before 24 KiB and the rest is
    0xFF. Sectors 64-79 are needed by the R36S idbloader, so the header gets size 24576
    and a recomputed checksum; only sectors 16-63 keep boot0 data.
    """
    start = BOOT0_SECTOR * SECTOR
    if bytes(area[start + 4:start + 12]) != b"eGON.BT0":
        raise VendorAreaError("no eGON.BT0 boot0 at sector 16")
    size = struct.unpack_from("<I", area, start + 0x10)[0]
    if size != BOOT0_FACTORY_SIZE:
        raise VendorAreaError(f"boot0 declares {size} bytes, expected {BOOT0_FACTORY_SIZE}")
    tail = bytes(area[start + BOOT0_SHRUNK_SIZE:start + BOOT0_FACTORY_SIZE])
    if tail != b"\xff" * len(tail):
        raise VendorAreaError(
            "boot0 has code past its first 24 KiB, so it does not fit before the R36S "
            "idbloader at sector 64; this factory boot0 cannot be shrunk")
    struct.pack_into("<I", area, start + 0x10, BOOT0_SHRUNK_SIZE)
    boot0 = bytes(area[start:start + BOOT0_SHRUNK_SIZE])
    struct.pack_into("<I", area, start + 0x0C, egon_checksum(boot0))
    # sectors 64-79 no longer belong to boot0: zero them for the R36S chain
    area[start + BOOT0_SHRUNK_SIZE:start + BOOT0_FACTORY_SIZE] = bytes(
        BOOT0_FACTORY_SIZE - BOOT0_SHRUNK_SIZE)


def area_digest(data: bytes) -> str:
    return hashlib.sha256(data[SECTOR:AREA_SECTORS * SECTOR]).hexdigest()


def vendor_area() -> Path:
    """The 128 MiB vendor area in the cache, extracted from the original card dump if needed."""
    dest = ensure_dir(cache_dir() / "vendor") / "ga36-factory-128M.bin"
    if not dest.exists():
        src = os.environ.get(ENV_VAR)
        if not src or not Path(src).is_file():
            raise VendorAreaError(
                f"the GA36 vendor boot area is missing. Point {ENV_VAR} to a dump of the "
                "first 128 MiB of the device's original card and run again")
        with open(src, "rb") as f:
            data = f.read(AREA_SECTORS * SECTOR)
        if len(data) != AREA_SECTORS * SECTOR or area_digest(data) != AREA_SHA256:
            raise VendorAreaError(f"{src}: the boot area does not match the known GA36 one")
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
    data = dest.read_bytes()
    if area_digest(data) != AREA_SHA256:
        raise VendorAreaError(f"{dest}: unexpected SHA256; delete it and extract it again")
    if data[16 * SECTOR + 4:16 * SECTOR + 12] != b"eGON.BT0":
        raise VendorAreaError(f"{dest}: no boot0 at sector 16")
    return dest
