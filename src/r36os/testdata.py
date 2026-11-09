"""Disco de teste da VM (FAT, rótulo TESTDATA): ROMs de teste, lista core -> ROM,
estado do self-test e resultados. Só existe para a VM (6.4)."""

from __future__ import annotations

import hashlib
import shutil
import urllib.request
from pathlib import Path

from r36os import catalog, testroms
from r36os.container import Container, ensure_builder
from r36os.paths import cache_dir, ensure_dir
from r36os.targets import TARGETS

# Romset livre para uso não comercial, distribuído pelo MAMEDev (mamedev.org/roms):
# Gridlee (Videa, 1983). Roda no fbneo e no mame2003_plus.
GRIDLEE_URL = "https://www.mamedev.org/roms/gridlee/gridlee.zip"
GRIDLEE_SHA256 = "df977ceba0ae1c8d0ecf489ae8423390ff5c7c76ce95f5ee6ba9bc892b18056e"

# Sistema usado para testar cada core: o primeiro do catálogo que o usa, exceto
# o mgba, que só aceita GB com o logo do cabeçalho e é testado no GBA.
CORE_SYSTEM_OVERRIDE = {"mgba": "gba"}
SIZE_MIB = 64


def _fetch(url: str, sha256: str, dest: Path) -> Path:
    if not dest.exists() or hashlib.sha256(dest.read_bytes()).hexdigest() != sha256:
        ensure_dir(dest.parent)
        tmp = dest.with_suffix(".part")
        with urllib.request.urlopen(url, timeout=60) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dest)
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    if got != sha256:
        raise RuntimeError(f"{dest.name}: sha256 {got} != {sha256}")
    return dest


def core_tests(cat: dict | None = None) -> dict[str, tuple[str, str]]:
    """core -> (sistema, arquivo da ROM de teste relativo ao disco)."""
    cat = cat or catalog.load()
    roms = {s: f"roms/{s}/{name}" for s, (name, _) in testroms.ROMS.items()}
    roms["arcade"] = "roms/arcade/gridlee.zip"
    tests: dict[str, tuple[str, str]] = {}
    for s in cat["systems"]:
        for core in sorted(catalog.core_refs(s)):
            system = CORE_SYSTEM_OVERRIDE.get(core, s["id"])
            tests.setdefault(core, (system, roms[system]))
    return tests


def build_testdata(dest: Path) -> Path:
    """Gera o disco FAT de teste em `dest` (sobrescreve)."""
    stage = dest.parent / "testdata-stage"
    shutil.rmtree(stage, ignore_errors=True)
    testroms.write_all(stage)
    gz = _fetch(GRIDLEE_URL, GRIDLEE_SHA256, cache_dir() / "distfiles/testroms/gridlee.zip")
    ensure_dir(stage / "roms/arcade")
    shutil.copy(gz, stage / "roms/arcade/gridlee.zip")
    cat = catalog.load()
    lines = [f"{core}\t{cat['cores'][core]['file']}\t{sys}\t{rom}"
             for core, (sys, rom) in sorted(core_tests(cat).items())]
    (stage / "cores.tsv").write_text("\n".join(lines) + "\n")
    (stage / "state").write_text("first\n")
    ensure_dir(stage / "results")
    dest.unlink(missing_ok=True)
    Container(image=ensure_builder(TARGETS["vm"]),
              volumes={dest.parent: "/out", stage: "/stage"}).sh(
        f"truncate -s {SIZE_MIB}M /out/{dest.name}\n"
        f"mkfs.vfat -n TESTDATA /out/{dest.name} >/dev/null\n"
        f"MTOOLS_SKIP_CHECK=1 mcopy -s -i /out/{dest.name} /stage/* ::/\n"
    )
    shutil.rmtree(stage)
    return dest
