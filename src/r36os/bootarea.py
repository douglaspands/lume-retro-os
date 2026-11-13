"""Boot area of the console image (design D2): one card that boots the GA36 and the R36S.

The 128 MiB before BOOT join both factory chains, each at the sectors its BROM or U-Boot
reads. The build starts from the GA36 vendor area (vendor.py), shrinks its boot0 to 24 KiB
(sectors 16-63) and copies the R36S chain (r36s_vendor.py) over it. Before copying, every
R36S sector must fall on a zero sector of the GA36 area or on sectors 64-277 (the end of
the factory boot0 and the unused RSAK block); otherwise the build fails listing the
conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from r36os import r36s_vendor, vendor

SECTOR = 512
AREA_SECTORS = vendor.AREA_SECTORS  # 128 MiB: BOOT starts at sector 262144
DISK_ID = "4c554d32"                # same signature as the GA36 cards written before
# GA36 sectors the R36S chain may cover: end of the factory boot0 (64-79) and RSAK (80-277)
GA36_REPLACEABLE = (64, 278)


@dataclass(frozen=True)
class Region:
    start: int   # first sector
    end: int     # sector after the last one
    origin: str  # "build", "ga36" or "r36s"
    contents: str


LAYOUT = (
    Region(0, 1, "build", "MBR (signature 4c554d32, BOOT only)"),
    Region(1, 16, "ga36", "GA36 factory area"),
    Region(16, 64, "ga36", "boot0 shrunk to 24 KiB (eGON checksum recomputed)"),
    Region(64, 406, "r36s", "idbloader"),
    Region(16384, 32768, "r36s", "uboot.img (x4) and trust.img (x2)"),
    Region(38192, 40960, "ga36", "U-Boot 2017"),
    Region(40960, 73728, "ga36", "softw411 partition table"),
    Region(73728, 139264, "ga36", '"bootloader" FAT'),
    Region(139264, 172032, "ga36", "U-Boot env"),
    Region(vendor.ANDROID_BOOT_SECTOR,
           vendor.ANDROID_BOOT_SECTOR + vendor.ANDROID_BOOT_MAX // SECTOR,
           "build", "Android boot image of GA36 panel 1"),
)

# R36S factory regions by name -> their place in the layout
R36S_PLACEMENT = {r.name: r for r in r36s_vendor.REGIONS}


class BootAreaError(RuntimeError):
    pass


def _ranges(sectors: list[int]) -> str:
    out, i = [], 0
    while i < len(sectors):
        j = i
        while j + 1 < len(sectors) and sectors[j + 1] == sectors[j] + 1:
            j += 1
        out.append(f"{sectors[i]}" if i == j else f"{sectors[i]}-{sectors[j]}")
        i = j + 1
    return ", ".join(out)


def conflicts(ga36_area: bytes, start: int, end: int) -> list[int]:
    """GA36 sectors in [start, end) with data that the R36S chain may not cover."""
    lo, hi = GA36_REPLACEABLE
    return [s for s in range(start, end)
            if not lo <= s < hi and any(ga36_area[s * SECTOR:(s + 1) * SECTOR])]


def assemble(ga36_area: bytes, r36s_regions: dict[str, bytes]) -> bytearray:
    """The combined 128 MiB area (sector 0 and the Android boot image come later)."""
    if len(ga36_area) != AREA_SECTORS * SECTOR:
        raise BootAreaError("the GA36 vendor area must have 128 MiB")
    bad = []
    for name, region in R36S_PLACEMENT.items():
        found = conflicts(ga36_area, region.start, region.end)
        if found:
            bad.append(f"{name}: {_ranges(found)}")
    if bad:
        raise BootAreaError(
            "the R36S boot chain would overwrite data of the GA36 vendor area at sectors "
            + "; ".join(bad))
    area = bytearray(ga36_area)
    vendor.shrink_boot0(area)
    for name, region in R36S_PLACEMENT.items():
        data = r36s_regions[name]
        if len(data) != (region.end - region.start) * SECTOR:
            raise BootAreaError(f"R36S {name}: wrong size {len(data)}")
        area[region.start * SECTOR:region.end * SECTOR] = data
    return area


def write_console_area(dest: Path) -> Path:
    """Build the combined area from both factory chains (checked by SHA256) into dest."""
    area = assemble(vendor.vendor_area().read_bytes(), r36s_vendor.factory_regions())
    tmp = dest.with_suffix(".part")
    tmp.write_bytes(area)
    tmp.replace(dest)
    return dest
