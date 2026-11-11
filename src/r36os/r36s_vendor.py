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
