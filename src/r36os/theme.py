"""Fontes externas do tema Lume: a fonte completa do Lucide (lucide-static, ISC)."""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from r36os.paths import cache_dir, ensure_dir

LUCIDE_VERSION = "1.70.0"
LUCIDE_URL = f"https://registry.npmjs.org/lucide-static/-/lucide-static-{LUCIDE_VERSION}.tgz"
LUCIDE_SHA256 = "3d1f09df1c468abe512ee6d6596db0dc773fa46c61050e365f0c5fee5120f16a"


def lucide_font() -> tuple[Path, Path]:
    """(lucide.ttf, codepoints.json), baixados e conferidos no cache."""
    base = ensure_dir(cache_dir() / "distfiles/theme")
    tgz = base / f"lucide-static-{LUCIDE_VERSION}.tgz"
    if not tgz.exists():
        tmp = tgz.with_suffix(".part")
        with urllib.request.urlopen(LUCIDE_URL, timeout=60) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(tgz)
    got = hashlib.sha256(tgz.read_bytes()).hexdigest()
    if got != LUCIDE_SHA256:
        raise RuntimeError(f"{tgz.name}: sha256 {got} != {LUCIDE_SHA256}")
    dest = base / f"lucide-static-{LUCIDE_VERSION}"
    if not (dest / "package/font/lucide.ttf").exists():
        with tarfile.open(tgz) as t:
            t.extractall(dest, filter="data")
    return dest / "package/font/lucide.ttf", dest / "package/font/codepoints.json"
