"""Catálogo de sistemas (`/usr/share/r36os/systems.json`) e sua validação.

O esquema está documentado em docs/CATALOG.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from r36os.paths import REPO_ROOT

CATALOG = REPO_ROOT / "rootfs/overlay/usr/share/r36os/systems.json"
ARCHES = {"x86_64", "aarch64", "armv7"}
_ID = re.compile(r"^[a-z0-9]+$")
_EXT = re.compile(r"^[a-z0-9]+$")


def load(path: Path = CATALOG) -> dict:
    return json.loads(path.read_text())


def validate(cat: dict) -> list[str]:
    """Lista de erros de esquema (vazia se o catálogo é válido)."""
    errs: list[str] = []
    if cat.get("schema") != 1:
        errs.append("schema deve ser 1")
    cores = cat.get("cores")
    if not isinstance(cores, dict) or not cores:
        errs.append("cores deve ser um objeto não vazio")
        cores = {}
    for name, c in cores.items():
        if set(c) != {"package", "file"}:
            errs.append(f"core {name}: campos devem ser package e file")
        elif c["file"] != f"{name}_libretro.so":
            errs.append(f"core {name}: file deve ser {name}_libretro.so")
    systems = cat.get("systems")
    if not isinstance(systems, list) or not systems:
        return errs + ["systems deve ser uma lista não vazia"]
    seen_ids, seen_names = set(), set()
    required = {"id", "name", "extensions", "core", "core_by_arch", "alt_cores", "bios"}
    for s in systems:
        sid = s.get("id", "?")
        if set(s) != required:
            errs.append(f"{sid}: campos {sorted(set(s) ^ required)} inválidos")
            continue
        if not _ID.match(sid):
            errs.append(f"{sid}: id deve ser [a-z0-9]+")
        if sid in seen_ids or s["name"] in seen_names:
            errs.append(f"{sid}: id ou nome repetido")
        seen_ids.add(sid)
        seen_names.add(s["name"])
        if "/" in s["name"]:
            errs.append(f"{sid}: nome não pode ter '/' (vira nome de arquivo .lpl)")
        exts = s["extensions"]
        if not exts or not all(isinstance(e, str) and _EXT.match(e) for e in exts):
            errs.append(f"{sid}: extensões devem ser minúsculas, sem ponto")
        for core in core_refs(s):
            if core not in cores:
                errs.append(f"{sid}: core {core} não está em cores")
        if not set(s["core_by_arch"]) <= ARCHES:
            errs.append(f"{sid}: arquitetura desconhecida em core_by_arch")
        for b in s["bios"]:
            if set(b) != {"files", "required", "note"} or not b["files"]:
                errs.append(f"{sid}: bios mal formada")
    return errs


def core_refs(system: dict) -> set[str]:
    return {system["core"], *system["core_by_arch"].values(), *system["alt_cores"]}


def default_core(system: dict, arch: str) -> str:
    return system["core_by_arch"].get(arch, system["core"])


def referenced_packages(cat: dict) -> set[str]:
    names = set().union(*(core_refs(s) for s in cat["systems"]))
    return {cat["cores"][n]["package"] for n in names}
