"""R36S factory boot chain (design D4): idbloader, uboot.img and trust.img.

Like the GA36 (vendor.py), the R36S boots through the closed chain of its own factory
card, which stays out of git. The build reads it from a copy of the original card given in
R36OS_R36S_FACTORY (raw image or .img.zst; the first 16 MiB are enough):

| sectors       | contents                                                       |
|---------------|----------------------------------------------------------------|
| 64-405        | idbloader (the RK3326 BROM only reads it at sector 64)         |
| 16384-24575   | uboot.img ("LOADER"), copies every 2048 sectors up to 22528    |
| 24576-32767   | trust.img ("BL3X", BL31), at 24576 and 28672                   |

Each region is checked by SHA256 against the card measured on 2026-11-11 (ArkOS for the
"R36S V5") and kept in the cache. Sectors 2048-4566 of that card hold leftovers of an old
FAT and are not part of the chain.

The factory U-Boot also reads files from the root of BOOT (partition 1, FAT32), and those
come from the same copy (task 4.5): the RG351 DTB it loads before boot.ini (without it,
"dtb load fail" and it stops) and logo.bmp, the boot screen it draws (the same picture the
GA36 factory bootloader shows). They are read from the FAT of the copy (the whole card,
since BOOT starts at 16 MiB), checked by SHA256 and kept in the cache.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from r36os.paths import cache_dir, ensure_dir

SECTOR = 512
ENV_VAR = "R36OS_R36S_FACTORY"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


@dataclass(frozen=True)
class FactoryRegion:
    name: str
    start: int  # first sector
    end: int    # sector after the last one
    sha256: str

    @property
    def cache_name(self) -> str:
        return f"r36s-{self.name}.bin"


# SHA256 of each region on the factory card of the user's R36S V5
REGIONS = (
    FactoryRegion("idbloader", 64, 406,
                  "8628ec26e6ebbf483a236de34cad6ab8c521dd5d543855c2c1bdbbcef59b1b12"),
    FactoryRegion("uboot-trust", 16384, 32768,
                  "cce003ea1dab55fd590172ad0d5d08275fa6c583d047eb28a470714108592062"),
)
READ_SECTORS = max(r.end for r in REGIONS)  # 16 MiB


class R36SFactoryError(RuntimeError):
    pass


def read_card_head(path: Path, sectors: int = READ_SECTORS) -> bytes:
    """First sectors of a card copy, raw or zstd-compressed."""
    with open(path, "rb") as f:
        compressed = f.read(4) == _ZSTD_MAGIC
    if compressed:
        from compression import zstd

        with zstd.open(path, "rb") as f:
            return f.read(sectors * SECTOR)
    with open(path, "rb") as f:
        return f.read(sectors * SECTOR)


def _check(region: FactoryRegion, data: bytes, origin: str) -> None:
    size = (region.end - region.start) * SECTOR
    if len(data) != size:
        raise R36SFactoryError(
            f"{origin}: the R36S {region.name} region (sectors {region.start}-"
            f"{region.end - 1}) is incomplete; the copy must hold the first 16 MiB of the card")
    digest = hashlib.sha256(data).hexdigest()
    if digest != region.sha256:
        raise R36SFactoryError(
            f"{origin}: the R36S {region.name} (sectors {region.start}-{region.end - 1}) has "
            f"SHA256 {digest}, but the only chain tested is the factory card of the R36S V5 "
            f"measured on 2026-11-11 ({region.sha256}). Use a copy of that card")


# Files of the factory BOOT root that the console BOOT carries at its root, with their SHA256
# on the factory card of the user's R36S V5 (the two DTBs are the same file, 61797 bytes)
BOOT_FILES = {
    "rg351mp-kernel.dtb": "daa5f234c4ffdfaeadacb39ba71402670eb750b7817d2825195c38e784a38cf0",
    "rg351p-kernel.dtb": "daa5f234c4ffdfaeadacb39ba71402670eb750b7817d2825195c38e784a38cf0",
    "logo.bmp": "01a2178e7412145af73e366b38adaa5164eab494acb182fe75f71fb603b56fdd",
}


def _boot_partition(path: Path) -> bytes:
    """Partition 1 (BOOT) of a card copy, from its MBR."""
    import struct

    mbr = read_card_head(path, 1)
    if len(mbr) < SECTOR or mbr[510:512] != b"\x55\xaa":
        raise R36SFactoryError(f"{path}: no MBR (the copy must be the whole card)")
    start, size = struct.unpack_from("<II", mbr, 446 + 8)
    if not size:
        raise R36SFactoryError(f"{path}: the MBR has no partition 1 (BOOT)")
    card = read_card_head(path, start + size)
    part = card[start * SECTOR:(start + size) * SECTOR]
    if len(part) != size * SECTOR:
        raise R36SFactoryError(f"{path}: the copy ends before the end of BOOT (partition 1)")
    return part


def fat32_root_files(fs: bytes) -> dict[str, bytes]:
    """Files of the root directory of a FAT32 volume, by long name (lowercase).

    Only what the factory BOOT needs: the root directory, long names (VFAT), no
    subdirectories.
    """
    import struct

    bps, spc, reserved, nfats = struct.unpack_from("<HBHB", fs, 11)
    fat_size = struct.unpack_from("<I", fs, 36)[0]
    root = struct.unpack_from("<I", fs, 44)[0]
    if fs[510:512] != b"\x55\xaa" or not bps or not spc or not fat_size or \
            struct.unpack_from("<H", fs, 22)[0]:
        raise R36SFactoryError("BOOT is not a FAT32 volume")
    cluster_bytes = bps * spc
    fat_start = reserved * bps
    data_start = (reserved + nfats * fat_size) * bps

    def chain(first: int):
        c, seen = first, set()
        while 2 <= c < 0x0FFFFFF8 and c not in seen:
            seen.add(c)
            yield data_start + (c - 2) * cluster_bytes
            c = struct.unpack_from("<I", fs, fat_start + 4 * c)[0] & 0x0FFFFFFF

    def read(first: int, size: int) -> bytes:
        data = b"".join(fs[o:o + cluster_bytes] for o in chain(first))
        return data[:size]

    directory = b"".join(fs[o:o + cluster_bytes] for o in chain(root))
    files: dict[str, bytes] = {}
    lfn: dict[int, str] = {}
    for i in range(0, len(directory), 32):
        e = directory[i:i + 32]
        if e[0] == 0:
            break
        if e[0] == 0xE5:
            lfn.clear()
            continue
        attr = e[11]
        if attr == 0x0F:
            part = (e[1:11] + e[14:26] + e[28:32]).decode("utf-16-le", "replace")
            lfn[e[0] & 0x1F] = part.split("\x00", 1)[0]
            continue
        long_name = "".join(lfn[k] for k in sorted(lfn)) if lfn else ""
        lfn.clear()
        if attr & 0x18:  # directory or volume label
            continue
        if not long_name:
            base, ext = e[0:8].decode("ascii", "replace").strip(), e[8:11].decode(
                "ascii", "replace").strip()
            long_name = f"{base}.{ext}" if ext else base
        first = struct.unpack_from("<H", e, 20)[0] << 16 | struct.unpack_from("<H", e, 26)[0]
        size = struct.unpack_from("<I", e, 28)[0]
        files[long_name.lower()] = read(first, size)
    return files


def factory_boot_files() -> dict[str, Path]:
    """BOOT root name -> cached file, extracted from R36OS_R36S_FACTORY if needed."""
    vendor = ensure_dir(cache_dir() / "vendor" / "r36s-boot")
    if not all((vendor / name).exists() for name in BOOT_FILES):
        src = os.environ.get(ENV_VAR)
        if not src or not Path(src).is_file():
            raise R36SFactoryError(
                f"the R36S factory BOOT files ({', '.join(BOOT_FILES)}) are missing. Point "
                f"{ENV_VAR} to a copy of the whole R36S original card (raw image or "
                ".img.zst) and run again")
        found = fat32_root_files(_boot_partition(Path(src)))
        for name, sha in BOOT_FILES.items():
            data = found.get(name)
            if data is None:
                raise R36SFactoryError(f"{src}: no {name} at the root of the factory BOOT")
            if hashlib.sha256(data).hexdigest() != sha:
                raise R36SFactoryError(
                    f"{src}: {name} has SHA256 {hashlib.sha256(data).hexdigest()}, but the "
                    f"only one tested is the factory card of the R36S V5 ({sha})")
            tmp = (vendor / name).with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(vendor / name)
    for name, sha in BOOT_FILES.items():
        if hashlib.sha256((vendor / name).read_bytes()).hexdigest() != sha:
            raise R36SFactoryError(f"{vendor / name}: wrong SHA256 (delete it and extract it again)")
    return {name: vendor / name for name in BOOT_FILES}


def factory_regions() -> dict[str, bytes]:
    """The R36S chain regions by name, from the cache or extracted from R36OS_R36S_FACTORY."""
    vendor = ensure_dir(cache_dir() / "vendor")
    if not all((vendor / r.cache_name).exists() for r in REGIONS):
        src = os.environ.get(ENV_VAR)
        if not src or not Path(src).is_file():
            raise R36SFactoryError(
                f"the R36S factory boot chain is missing. Point {ENV_VAR} to a copy of the "
                "R36S original card (raw image or .img.zst, at least its first 16 MiB) and "
                "run again")
        head = read_card_head(Path(src))
        for r in REGIONS:
            data = head[r.start * SECTOR:r.end * SECTOR]
            _check(r, data, src)
            tmp = (vendor / r.cache_name).with_suffix(".part")
            tmp.write_bytes(data)
            tmp.replace(vendor / r.cache_name)
    out = {}
    for r in REGIONS:
        path = vendor / r.cache_name
        data = path.read_bytes()
        _check(r, data, f"{path} (delete it and extract it again)")
        out[r.name] = data
    return out
