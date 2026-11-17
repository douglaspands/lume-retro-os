"""The console root as slots (build-speed D9): rootfs.tar split by owner into base, runtime
and lume, plus the kernel modules image as the modules slot, and the SLOTS manifest.

    out/<console>/slot/
      base-<sha12> runtime-<sha12> lume-<sha12>   squashfs, from rootfs.tar (stage "slots")
      modules-<sha12>                              copy of kernel/modules (stage 1)
      overlay.json                                 the three overlay slots of the last run
      SLOTS                                        the set, with the build id (every build)

Split rule (D9): each member of rootfs.tar goes to the slot of the package that owns it in
lib/apk/db/installed, by the groups of rootfs/slots.toml. A file with no owner, owned by two
packages of different groups, or changed after the install (content not the checksum of the
database: configure.sh, the overlay, the factory language) goes to `lume`, the top slot;
so do the apk database, /etc/apk/world and the trigger outputs (no owner). A directory goes
to the slot of its owner (lume without one) and to every slot that has something under it,
with the same header: overlayfs merges them. A hard link whose target went to another slot
becomes a regular file. Times do not reach the squashfs (-all-time 0), so the same
rootfs.tar content always gives the same slots, byte for byte.
"""

from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import shutil
import tarfile
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from r36os import manifests
from r36os.manifests import OVERLAY_SLOTS, Slot, SlotSet

SLOTS_TOML = Path(__file__).resolve().parents[2] / "rootfs" / "slots.toml"
TOP = "lume"                    # where files with no owner (or changed ones) go
OVERLAY_RECORD = "overlay.json"
# The sum of the slots of one console (system-image spec)
CONSOLE_SLOTS_LIMIT_MIB = 448
# Version of the split rule: part of the inputs of the stage, so a change of the rule
# rebuilds the slots
SPLIT_FORMAT = "1"
APK_DB = "lib/apk/db/installed"
# zstd level of the slots (build-speed D16): the full console build packs at the maximum,
# a fragment build at a fast level (bigger slots, much quicker to make)
LEVEL_FULL = 19
LEVEL_FAST = 3
_LEVEL_OPTION = "-Xcompression-level"


def with_level(options: str, level: int) -> str:
    """`options` (the mksquashfs options of rootfs.SQUASHFS_OPTIONS) with the zstd level
    set to `level`."""
    words = options.split()
    if _LEVEL_OPTION not in words or words.index(_LEVEL_OPTION) + 1 >= len(words):
        raise SlotsError(f"no {_LEVEL_OPTION} in the squashfs options: {options!r}")
    words[words.index(_LEVEL_OPTION) + 1] = str(level)
    return " ".join(words)


class SlotsError(RuntimeError):
    pass


class SlotsTooLargeError(SlotsError):
    pass


# --- rootfs/slots.toml ---------------------------------------------------------------------

@dataclass(frozen=True)
class Groups:
    patterns: dict[str, tuple[str, ...]]        # slot -> package name patterns
    default: str

    def named(self, package: str) -> list[str]:
        """The groups whose patterns match `package` (none: it goes to the default)."""
        return [g for g, pats in self.patterns.items()
                if any(fnmatch.fnmatchcase(package, p) for p in pats)]

    def group_of(self, package: str) -> str:
        named = self.named(package)
        if len(named) > 1:
            raise SlotsError(f"{SLOTS_TOML.name}: package {package} is in the groups "
                             f"{', '.join(named)}")
        return named[0] if named else self.default


def load_groups(path: Path = SLOTS_TOML) -> Groups:
    try:
        doc = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise SlotsError(f"{path}: {e}") from None
    groups = doc.get("groups")
    default = doc.get("default")
    if set(doc) != {"default", "groups"} or not isinstance(groups, dict):
        raise SlotsError(f"{path}: expected `default` and a [groups] table")
    if set(groups) - set(OVERLAY_SLOTS) or default not in OVERLAY_SLOTS:
        raise SlotsError(f"{path}: the groups and the default are {', '.join(OVERLAY_SLOTS)}")
    patterns = {}
    for name in OVERLAY_SLOTS:
        pats = groups.get(name, [])
        if not isinstance(pats, list) or not all(isinstance(p, str) and p for p in pats):
            raise SlotsError(f"{path}: group {name} is not a list of package patterns")
        patterns[name] = tuple(pats)
    return Groups(patterns=patterns, default=default)


# --- the apk database ----------------------------------------------------------------------

@dataclass
class ApkDb:
    versions: dict[str, str] = field(default_factory=dict)      # package -> version
    files: dict[str, list[tuple[str, str]]] = field(default_factory=dict)  # path -> (pkg, Z)
    dirs: dict[str, list[str]] = field(default_factory=dict)    # path -> packages


def parse_apk_db(text: str) -> ApkDb:
    """Packages, their files (R:, with the Z: checksum) and directories (F:)."""
    db = ApkDb()
    pkg = ""
    folder = ""
    last = None
    for line in text.splitlines():
        if not line:
            pkg, folder, last = "", "", None
            continue
        key, _, value = line.partition(":")
        if key == "P":
            pkg = value
        elif key == "V" and pkg:
            db.versions[pkg] = value
        elif key == "F" and pkg:
            folder = value
            db.dirs.setdefault(value, []).append(pkg)
        elif key == "R" and pkg:
            path = f"{folder}/{value}" if folder else value
            last = [pkg, ""]
            db.files.setdefault(path, []).append(last)
        elif key == "Z" and last is not None:
            last[1] = value
    db.files = {p: [tuple(o) for o in owners] for p, owners in db.files.items()}
    return db


def apk_checksum(data_digest: bytes, kind: str) -> str:
    """The Z: value of a digest (Q1: sha1, Q2: sha256), base64 as apk writes it."""
    prefix = "Q1" if kind == "sha1" else "Q2"
    return prefix + base64.b64encode(data_digest).decode()


def _checksum_of(z: str, data: Iterable[bytes]) -> str:
    h = hashlib.sha1() if z.startswith("Q1") else hashlib.sha256()
    for chunk in data:
        h.update(chunk)
    return apk_checksum(h.digest(), "sha1" if z.startswith("Q1") else "sha256")


# --- the split -----------------------------------------------------------------------------

def _rel(name: str) -> str:
    """Member name as the apk database writes it ('./usr/bin/x' -> 'usr/bin/x')."""
    n = name[2:] if name.startswith("./") else name
    return n.rstrip("/")


def _parents(rel: str) -> list[str]:
    parts = rel.split("/")
    return ["/".join(parts[:i]) for i in range(1, len(parts))]


@dataclass
class Split:
    """Where each member of rootfs.tar goes. `files` holds every member that is not a
    directory (exactly one slot each); `dirs` every directory (one or more slots)."""
    files: dict[str, str] = field(default_factory=dict)         # member name -> slot
    dirs: dict[str, set[str]] = field(default_factory=dict)     # member name -> slots
    packages: dict[str, list[tuple[str, str]]] = field(default_factory=dict)
    to_top: dict[str, str] = field(default_factory=dict)        # member -> why it went up
    unnamed: list[str] = field(default_factory=list)            # packages on the default
    hardlinks_copied: list[str] = field(default_factory=list)


def _data_chunks(t: tarfile.TarFile, m: tarfile.TarInfo):
    f = t.extractfile(m)
    if f is None:
        return
    while chunk := f.read(1 << 20):
        yield chunk


def split_rootfs(tar_path: Path, groups: Groups) -> Split:
    """Assign every member of rootfs.tar to a slot (see the module doc)."""
    sp = Split(packages={n: [] for n in OVERLAY_SLOTS})
    with tarfile.open(tar_path) as t:
        members = t.getmembers()
        by_rel = {_rel(m.name): m for m in members}
        dbm = by_rel.get(APK_DB)
        if dbm is None:
            raise SlotsError(f"{tar_path}: no {APK_DB}")
        db = parse_apk_db(t.extractfile(dbm).read().decode())
        group = {}
        for pkg in sorted(db.versions):
            group[pkg] = groups.group_of(pkg)
            if not groups.named(pkg):
                sp.unnamed.append(pkg)
            sp.packages[group[pkg]].append((pkg, db.versions[pkg]))

        def owner_slot(rel: str, m: tarfile.TarInfo) -> tuple[str, str]:
            owners = db.files.get(rel)
            if not owners:
                return TOP, "no owner"
            slots = {group.get(p, TOP) for p, _ in owners}
            if len(slots) > 1:
                return TOP, "owned by packages of different groups"
            z = owners[-1][1]
            if z and m.isreg():
                if _checksum_of(z, _data_chunks(t, m)) != z:
                    return TOP, "changed after the install"
            elif z and m.issym():
                if _checksum_of(z, [m.linkname.encode()]) != z:
                    return TOP, "changed after the install"
            elif z and m.islnk():
                target = by_rel.get(_rel(m.linkname))
                if target is None or _checksum_of(z, _data_chunks(t, target)) != z:
                    return TOP, "changed after the install"
            return slots.pop(), ""

        for m in members:
            rel = _rel(m.name)
            if m.isdir():
                continue
            slot, why = owner_slot(rel, m)
            sp.files[m.name] = slot
            if why:
                sp.to_top[m.name] = why
        for m in members:
            if not m.isdir():
                continue
            rel = _rel(m.name)
            owners = db.dirs.get(rel, [])
            slots = {group.get(p, TOP) for p in owners} or {TOP}
            sp.dirs[m.name] = slots
        # every directory above a member, in that member's slot
        dir_names = {_rel(n): n for n in sp.dirs}
        root = next((n for n in sp.dirs if _rel(n) in ("", ".")), None)
        for name, slot in [*sp.files.items(),
                           *((n, s) for n, ss in list(sp.dirs.items()) for s in ss)]:
            for parent in _parents(_rel(name)):
                if parent in dir_names:
                    sp.dirs[dir_names[parent]].add(slot)
        if root is not None:
            sp.dirs[root] = set(OVERLAY_SLOTS)
        # hard links whose target went to another slot are copied as regular files
        for m in members:
            if m.islnk():
                target = by_rel.get(_rel(m.linkname))
                if target is None or sp.files.get(target.name) != sp.files[m.name]:
                    sp.hardlinks_copied.append(m.name)
    return sp


def write_slot_tars(tar_path: Path, sp: Split, dest: Path) -> dict[str, Path]:
    """One tar per overlay slot in `dest` (<slot>.tar), members in the order of rootfs.tar,
    headers as there (numeric owners, modes, times)."""
    dest.mkdir(parents=True, exist_ok=True)
    paths = {n: dest / f"{n}.tar" for n in OVERLAY_SLOTS}
    copied = set(sp.hardlinks_copied)
    outs = {n: tarfile.open(p, "w", format=tarfile.GNU_FORMAT) for n, p in paths.items()}
    try:
        with tarfile.open(tar_path) as t:
            for m in t.getmembers():
                if m.isdir():
                    if _rel(m.name) in ("", "."):
                        continue    # mksquashfs ignores the root entry of a tar
                    for n in sorted(sp.dirs[m.name]):
                        outs[n].addfile(_header(m))
                    continue
                slot = sp.files[m.name]
                if m.name in copied:
                    target = t.getmember(m.linkname)
                    info = _header(m)
                    info.type, info.linkname, info.size = tarfile.REGTYPE, "", target.size
                    outs[slot].addfile(info, t.extractfile(target))
                elif m.isreg():
                    outs[slot].addfile(_header(m), t.extractfile(m))
                else:
                    outs[slot].addfile(_header(m))
    finally:
        for o in outs.values():
            o.close()
    return paths


def _header(m: tarfile.TarInfo) -> tarfile.TarInfo:
    info = tarfile.TarInfo(m.name)
    info.type, info.mode, info.uid, info.gid = m.type, m.mode, m.uid, m.gid
    info.uname, info.gname, info.mtime = "", "", int(m.mtime)
    info.linkname, info.size = m.linkname, m.size if m.isreg() else 0
    info.devmajor, info.devminor = m.devmajor, m.devminor
    return info


# --- the slots on disk ---------------------------------------------------------------------

# mksquashfs of each slot tar (same options as SYSTEM: fixed times, -noappend)
SLOT_SCRIPT = """
for s in {names}; do
  mksquashfs - /slots/$s.squashfs -tar {options} -processors {jobs} < /slots/work/$s.tar
done
"""


def _squash(slots_dir: Path, names: list[str], options: str) -> None:
    from r36os import jobs
    from r36os.container import Container, ensure_builder
    from r36os.targets import TARGETS

    # mksquashfs does not depend on the target arch: always the x86_64 builder
    Container(image=ensure_builder(TARGETS["vm"]), volumes={slots_dir: "/slots"}).sh(
        SLOT_SCRIPT.format(names=" ".join(names), options=options, jobs=jobs.jobs()))


def slots_dir(layer_out: Path) -> Path:
    """out/<console>/slot/"""
    return layer_out / manifests.SLOTS_DIR


def overlay_files(slots_dir: Path) -> list[Path]:
    """The slot files of the last overlay run (empty when there is none)."""
    try:
        record = json.loads((slots_dir / OVERLAY_RECORD).read_text())
        return [slots_dir / s["file"] for s in record["slots"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def build_overlay_slots(tar_path: Path, slots_dir: Path, options: str,
                        groups: Groups | None = None, squash=_squash) -> list[Slot]:
    """base, runtime and lume from rootfs.tar in `slots_dir`, named by content, and the
    record overlay.json. `squash(slots_dir, names, options)` makes <name>.squashfs from
    work/<name>.tar."""
    groups = groups or load_groups()
    slots_dir.mkdir(parents=True, exist_ok=True)
    (slots_dir / OVERLAY_RECORD).unlink(missing_ok=True)
    sp = split_rootfs(tar_path, groups)
    work = slots_dir / "work"
    shutil.rmtree(work, ignore_errors=True)
    write_slot_tars(tar_path, sp, work)
    names = list(OVERLAY_SLOTS)
    squash(slots_dir, names, options)
    shutil.rmtree(work, ignore_errors=True)
    out: list[Slot] = []
    for name in names:
        made = slots_dir / f"{name}.squashfs"
        sha = manifests.sha256_file(made)
        lower = tuple((s.name, s.sha256) for s in out)
        slot = Slot(name=name, sha256=sha, size=made.stat().st_size, lower=lower,
                    packages=tuple(sp.packages[name]))
        made.replace(slots_dir / Path(slot.file).name)
        out.append(slot)
    files_in = {n: 0 for n in names}
    for slot in sp.files.values():
        files_in[slot] += 1
    record = {"slots": [{"name": s.name, "sha256": s.sha256, "size": s.size,
                         "file": Path(s.file).name, "lower": [list(x) for x in s.lower],
                         "packages": [list(p) for p in s.packages]} for s in out],
              "files": files_in, "to_top": len(sp.to_top),
              "unnamed_packages": sp.unnamed}
    manifests._write_atomic(slots_dir / OVERLAY_RECORD, json.dumps(record, indent=1) + "\n")
    print("slots: " + ", ".join(f"{s.name} {s.size / 2**20:.1f} MiB ({files_in[s.name]} "
                                f"files)" for s in out)
          + f"; {len(sp.to_top)} files with no owner or changed after the install in lume",
          flush=True)
    return out


def read_overlay(slots_dir: Path) -> list[Slot]:
    path = slots_dir / OVERLAY_RECORD
    try:
        record = json.loads(path.read_text())
        return [Slot(name=s["name"], sha256=s["sha256"], size=s["size"],
                     lower=tuple(tuple(x) for x in s["lower"]),
                     packages=tuple(tuple(p) for p in s["packages"]))
                for s in record["slots"]]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise SlotsError(f"{path}: {e}") from None


def set_size(slots_dir: Path, modules_image: Path) -> int:
    """Bytes of the slot set the overlay record and the modules image would make."""
    return sum(s.size for s in read_overlay(slots_dir)) + modules_image.stat().st_size


def write_slot_set(console: str, build_id: str, slots_dir: Path, modules_image: Path,
                   kernel_release: str = "",
                   limit_mib: int = CONSOLE_SLOTS_LIMIT_MIB) -> SlotSet:
    """The set of this build: the overlay slots of the last run and the modules image
    (copied to modules-<sha12>), in slot/SLOTS; slot files of older sets are removed from
    slots_dir (the archive keeps them as objects). Fails above `limit_mib` in all."""
    overlay = read_overlay(slots_dir)
    sha = manifests.sha256_file(modules_image)
    pkgs = ((("linux", kernel_release),)
            if kernel_release and manifests._WORD.match(kernel_release) else ())
    modules = Slot(name="modules", sha256=sha, size=modules_image.stat().st_size,
                   packages=pkgs)
    dest = slots_dir / Path(modules.file).name
    if not dest.is_file() or manifests.sha256_file(dest) != sha:
        tmp = dest.with_name(dest.name + ".tmp")
        shutil.copyfile(modules_image, tmp)
        tmp.replace(dest)
    ss = SlotSet(build=build_id, console=console, slots=(*overlay, modules))
    manifests.validate_slots(ss)
    for s in ss.slots:
        if not (slots_dir / Path(s.file).name).is_file():
            raise SlotsError(f"{slots_dir}: no {Path(s.file).name} of the slot set")
    total = sum(s.size for s in ss.slots)
    if total > limit_mib * 2**20:
        raise SlotsTooLargeError(
            f"the slots of {console} take {total / 2**20:.1f} MiB, above the {limit_mib} MiB "
            "limit (" + ", ".join(f"{s.name} {s.size / 2**20:.1f}" for s in ss.slots) + ")")
    keep = {Path(s.file).name for s in ss.slots} | {OVERLAY_RECORD,
                                                     OVERLAY_RECORD + ".inputs"}
    for p in slots_dir.iterdir():
        if p.is_file() and p.name not in keep and p.name != manifests.SLOTS_FILE:
            p.unlink()
    manifests.write_slots(slots_dir / manifests.SLOTS_FILE, ss)
    return ss


def boot_files(console: str, slots_dir: Path) -> dict[str, Path]:
    """BOOT path -> source of the slot set of a console: <console>/SLOTS and
    <console>/slot/<name>-<sha12>."""
    ss = manifests.read_slots(slots_dir / manifests.SLOTS_FILE)
    if ss.console != console:
        raise SlotsError(f"{slots_dir}/SLOTS is the set of {ss.console}, not {console}")
    files = {f"{console}/{manifests.SLOTS_FILE}": slots_dir / manifests.SLOTS_FILE}
    for f in ss.files():
        files[f"{console}/{f}"] = slots_dir / Path(f).name
    return files
