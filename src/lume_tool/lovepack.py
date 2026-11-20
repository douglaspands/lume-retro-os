"""Reproducible `.love` packaging (a LÖVE game is a zip with main.lua at its root).

Used by the `push_love` step of `lume dev run` (tests/device/love-probe/): the same source
directory always gives the same bytes (sorted entries, fixed timestamps and permissions), so a
committed `.love` is never needed.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

FIXED_TIME = (1980, 1, 1, 0, 0, 0)       # the zip format's earliest date


class LovePackError(ValueError):
    pass


def source_files(src: Path) -> list[Path]:
    """The files of a game source directory, relative, sorted; hidden entries are skipped."""
    if not src.is_dir():
        raise LovePackError(f"{src} is not a directory")
    files = sorted(p.relative_to(src) for p in src.rglob("*")
                   if p.is_file() and not any(part.startswith(".") for part in p.relative_to(src).parts))
    if Path("main.lua") not in files:
        raise LovePackError(f"{src} has no main.lua")
    return files


def build_love(src: Path) -> bytes:
    """The `.love` (zip) bytes of the source directory `src`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in source_files(src):
            info = zipfile.ZipInfo(rel.as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, (src / rel).read_bytes())
    return buf.getvalue()
