"""System catalog (`/usr/share/r36os/systems.json`), the launcher runners and their validation.

The schemas are documented in docs/CATALOG.md and docs/LAUNCHER.md.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from r36os.paths import REPO_ROOT

CATALOG = REPO_ROOT / "rootfs/overlay/usr/share/r36os/systems.json"
RUNNERS_DIR = REPO_ROOT / "rootfs/overlay/usr/share/lume/runners.d"
ARCHES = {"x86_64", "aarch64", "armv7"}
_ID = re.compile(r"^[a-z0-9]+$")
_EXT = re.compile(r"^[a-z0-9]+$")
_RUNNER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
# lume-core runner placeholders (lume-launcher D5); each one stands for one whole argument
PLACEHOLDERS = {"rom", "core", "core_path", "system", "bios_dir", "saves_dir", "states_dir"}
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
RUNNER_KINDS = {"libretro", "native"}
QUIT_POLICIES = {"retroarch-cmd", "sigterm"}
# The libretro runner the core fields (core, core_by_arch, alt_cores) expand to
LIBRETRO_RUNNER = "retroarch"


def load(path: Path = CATALOG) -> dict:
    return json.loads(path.read_text())


def load_runners(directory: Path = RUNNERS_DIR) -> dict[str, dict]:
    """The runners of a runners.d folder by id (`[runner]` table of each .toml)."""
    runners = {}
    for f in sorted(directory.glob("*.toml")):
        r = tomllib.loads(f.read_text()).get("runner", {})
        runners[r.get("id", f.stem)] = r
    return runners


def validate_runner(r: dict) -> list[str]:
    """Errors of one runner, the same rules lume-core applies to the card's runners."""
    rid = r.get("id", "?")
    errs = []
    if not isinstance(r.get("id"), str) or not _RUNNER_ID.match(r["id"]):
        errs.append(f"runner {rid}: id must be [a-z0-9_-]+")
    if r.get("kind") not in RUNNER_KINDS:
        errs.append(f"runner {rid}: kind must be one of {sorted(RUNNER_KINDS)}")
    if r.get("quit") not in QUIT_POLICIES:
        errs.append(f"runner {rid}: quit must be one of {sorted(QUIT_POLICIES)}")
    timeout = r.get("timeout")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 30:
        errs.append(f"runner {rid}: timeout must be 1 to 30 seconds")
    exe = r.get("exec")
    if not isinstance(exe, list) or not exe or not all(isinstance(a, str) and a for a in exe):
        errs.append(f"runner {rid}: exec must be a non-empty list of arguments")
        return errs
    if not exe[0].startswith("/"):
        errs.append(f"runner {rid}: exec[0] must be an absolute path")
    for arg in exe:
        for name in _PLACEHOLDER.findall(arg):
            if name not in PLACEHOLDERS:
                errs.append(f"runner {rid}: unknown placeholder {{{name}}}")
        if _PLACEHOLDER.search(arg) and _PLACEHOLDER.fullmatch(arg) is None:
            errs.append(f"runner {rid}: a placeholder must be a whole argument ({arg!r})")
    if r.get("kind") == "libretro" and "{core_path}" not in exe and "{core}" not in exe:
        errs.append(f"runner {rid}: a libretro runner needs {{core_path}} or {{core}}")
    return errs


def validate(cat: dict, runners: dict[str, dict] | None = None) -> list[str]:
    """Schema errors (empty if the catalog is valid).

    `runners` are the image runners (default: rootfs/overlay/usr/share/lume/runners.d); every
    runner a system cites must be there and be valid.
    """
    runners = load_runners() if runners is None else runners
    errs: list[str] = []
    for r in runners.values():
        errs += validate_runner(r)
    if cat.get("schema") != 3:
        errs.append("schema must be 3")
    cores = cat.get("cores")
    if not isinstance(cores, dict) or not cores:
        errs.append("cores must be a non-empty object")
        cores = {}
    for name, c in cores.items():
        if set(c) != {"package", "file"}:
            errs.append(f"core {name}: fields must be package and file")
        elif c["file"] != f"{name}_libretro.so":
            errs.append(f"core {name}: file must be {name}_libretro.so")
    systems = cat.get("systems")
    if not isinstance(systems, list) or not systems:
        return errs + ["systems must be a non-empty list"]
    seen_ids, seen_names = set(), set()
    required = {"id", "name", "abbr", "extensions", "core", "core_by_arch", "alt_cores",
                "emulators", "bios", "romset"}
    for s in systems:
        sid = s.get("id", "?")
        if set(s) != required:
            errs.append(f"{sid}: invalid fields {sorted(set(s) ^ required)}")
            continue
        if not _ID.match(sid):
            errs.append(f"{sid}: id must be [a-z0-9]+")
        if sid in seen_ids or s["name"] in seen_names:
            errs.append(f"{sid}: repeated id or name")
        seen_ids.add(sid)
        seen_names.add(s["name"])
        if "/" in s["name"]:
            errs.append(f"{sid}: name cannot have '/' (it becomes an .lpl file name)")
        abbr = s["abbr"]
        if not isinstance(abbr, str) or not 1 <= len(abbr) <= 5 or abbr != abbr.strip():
            errs.append(f"{sid}: abbr must be 1 to 5 characters")
        exts = s["extensions"]
        if not exts or not all(isinstance(e, str) and _EXT.match(e) for e in exts):
            errs.append(f"{sid}: extensions must be lowercase, without a dot")
        if s["core"] is None:
            if s["core_by_arch"] or s["alt_cores"]:
                errs.append(f"{sid}: a system without core cannot have core_by_arch or alt_cores")
            if not s["emulators"]:
                errs.append(f"{sid}: a system without core needs emulators")
        else:
            for core in core_refs(s):
                if core not in cores:
                    errs.append(f"{sid}: core {core} is not in cores")
            if not set(s["core_by_arch"]) <= ARCHES:
                errs.append(f"{sid}: unknown architecture in core_by_arch")
        errs += _validate_emulators(sid, s["emulators"], runners, cores)
        for b in s["bios"]:
            if set(b) != {"files", "required", "note"} or not b["files"]:
                errs.append(f"{sid}: malformed bios")
        romset = s["romset"]
        if romset is not None and (not isinstance(romset, str) or not romset.strip()):
            errs.append(f"{sid}: romset must be null or a non-empty text")
        elif romset is not None and s["core_by_arch"]:
            # Single card: one arcade romset folder serves every console, and a romset only
            # works on the core version it was built for.
            errs.append(f"{sid}: arcade system (romset) cannot have core_by_arch")
    if any(s.get("core") for s in systems if isinstance(s, dict)) and LIBRETRO_RUNNER not in runners:
        errs.append(f"runner {LIBRETRO_RUNNER} is missing (systems with core use it)")
    return errs


def _validate_emulators(sid: str, emulators, runners: dict, cores: dict) -> list[str]:
    if not isinstance(emulators, list):
        return [f"{sid}: emulators must be a list"]
    errs = []
    for e in emulators:
        if not isinstance(e, dict) or "runner" not in e or not set(e) <= {"runner", "core"}:
            errs.append(f"{sid}: an emulator is {{runner, core?}}")
            continue
        runner = runners.get(e["runner"])
        if runner is None:
            errs.append(f"{sid}: runner {e['runner']} is not installed")
            continue
        if runner.get("kind") == "libretro":
            # The two forms must agree: libretro cores are listed only in core/alt_cores
            errs.append(f"{sid}: libretro runner {e['runner']} goes in core/alt_cores, "
                        "not in emulators")
        elif "core" in e:
            errs.append(f"{sid}: runner {e['runner']} is not libretro and takes no core")
    return errs


def core_refs(system: dict) -> set[str]:
    if system["core"] is None:
        return set()
    return {system["core"], *system["core_by_arch"].values(), *system["alt_cores"]}


def default_core(system: dict, arch: str) -> str | None:
    return system["core_by_arch"].get(arch, system["core"])


def emulators(system: dict, arch: str) -> list[dict]:
    """Ordered emulators of a system on `arch`; the first one is the default.

    The libretro ones come from core/core_by_arch/alt_cores (default core first, then the
    other cores of the system), followed by the `emulators` field.
    """
    out = []
    default = default_core(system, arch)
    if default is not None:
        for core in [default, system["core"], *system["alt_cores"]]:
            entry = {"runner": LIBRETRO_RUNNER, "core": core}
            if entry not in out:
                out.append(entry)
    return out + [dict(e) for e in system["emulators"]]


def referenced_packages(cat: dict) -> set[str]:
    names = set().union(*(core_refs(s) for s in cat["systems"]))
    return {cat["cores"][n]["package"] for n in names}
