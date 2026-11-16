"""Shared formats of the fast build (build-speed D3, D9, D10): typed read, write and strict
validation, so the producers (build, pkg) and the consumers (push, flash, initramfs) agree.

    <console>/SLOTS          on BOOT: the slot set of one console (D9); SLOTS.old is the
                             previous set, SLOTS.new the one a push is about to switch to
    boot-files.sha256        out/images/console/<build>/: every BOOT file of a build with its
                             sha256, the files themselves in out/images/objects/<sha256> (D10)
    .lume-content            control area of a fragment .apk: its content hash (D3)
    .PKGINFO `commit`        the inputs hash of the fragment, cut to 40 hex digits (D3)
    hashes.json              out/repo/<arch>/hashes.json: per package its version, inputs
                             hash, content hash and file name (D3)

The SLOTS manifest is also read by busybox sh/awk in the initramfs (initramfs/lib/slots.sh):
both readers accept exactly the same lines. Any truncated or garbled file raises
ManifestError naming the file, the line and the reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

CHUNK = 1 << 22  # 4 MiB


class ManifestError(ValueError):
    """A manifest that is missing, truncated or garbled."""


def _hex64(s: str) -> bool:
    return len(s) == 64 and all(c in "0123456789abcdef" for c in s)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def _write_atomic(path: Path, data: str) -> None:
    """Write through <path>.tmp and a rename, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.replace(path)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ManifestError(f"{path}: missing") from None
    except UnicodeDecodeError:
        raise ManifestError(f"{path}: not UTF-8 text (garbled)") from None


# --------------------------------------------------------------------------------------
# SLOTS (D9)
# --------------------------------------------------------------------------------------
#
#   lume-slots 1
#   build 20261116-214233
#   console ga36
#   slot base slots/base-0123456789ab <sha256> <bytes> -
#   pkg base musl 1.2.5-r10
#   slot runtime slots/runtime-... <sha256> <bytes> base=<sha256>
#   slot lume slots/lume-... <sha256> <bytes> base=<sha256>,runtime=<sha256>
#   pkg lume lume-core 1.0-r3
#   slot modules slots/modules-... <sha256> <bytes> -
#   slot core-snes9x slots/core-snes9x-... <sha256> <bytes> base=<sha256>,runtime=<sha256>
#   end 5 2
#
# Fields are separated by one space and never hold whitespace. The order of the slots is
# fixed (base, runtime, lume, modules, then core-* by name): the overlay mounts base,
# runtime and lume in that order (lume on top). `end <slots> <pkg lines>` closes the file:
# without it, or with other counts, the manifest is truncated.

SLOTS_MAGIC = "lume-slots"
SLOTS_FORMAT = 1
SLOTS_FILE = "SLOTS"
SLOTS_OLD = "SLOTS.old"
SLOTS_NEW = "SLOTS.new"
SLOTS_DIR = "slots"
OVERLAY_SLOTS = ("base", "runtime", "lume")          # mount order, bottom to top
REQUIRED_SLOTS = (*OVERLAY_SLOTS, "modules")
_FIXED_RANK = {"base": 0, "runtime": 1, "lume": 2, "modules": 3}

_SLOT_NAME = re.compile(r"^(base|runtime|lume|modules|core-[a-z0-9][a-z0-9_.+-]*)$")
_WORD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+~-]*$")   # build id, console, package, version
_CONSOLE = re.compile(r"^[a-z0-9]+$")


def slot_file(name: str, sha256: str) -> str:
    """File of a slot, relative to <console>/: slots/<name>-<sha12>."""
    return f"{SLOTS_DIR}/{name}-{sha256[:12]}"


def _slot_rank(name: str) -> tuple[int, str]:
    return (_FIXED_RANK.get(name, 4), name)


@dataclass(frozen=True)
class Slot:
    name: str                                       # base, runtime, lume, modules, core-<x>
    sha256: str                                     # of the squashfs file
    size: int                                       # bytes
    lower: tuple[tuple[str, str], ...] = ()         # (slot, sha256) it was built against
    packages: tuple[tuple[str, str], ...] = ()      # (package, version) it carries

    @property
    def file(self) -> str:
        return slot_file(self.name, self.sha256)

    @property
    def is_core(self) -> bool:
        return self.name.startswith("core-")


@dataclass(frozen=True)
class SlotSet:
    build: str
    console: str
    slots: tuple[Slot, ...]
    format: int = SLOTS_FORMAT

    def __post_init__(self):
        # canonical order, so equal sets give equal files
        object.__setattr__(self, "slots",
                           tuple(sorted(self.slots, key=lambda s: _slot_rank(s.name))))

    def get(self, name: str) -> Slot:
        for s in self.slots:
            if s.name == name:
                return s
        raise KeyError(name)

    def overlay(self) -> tuple[Slot, ...]:
        """base, runtime, lume: the lowerdirs of the root, in mount order (bottom first)."""
        return tuple(self.get(n) for n in OVERLAY_SLOTS)

    def cores(self) -> tuple[Slot, ...]:
        return tuple(s for s in self.slots if s.is_core)

    def files(self) -> tuple[str, ...]:
        """Slot files relative to <console>/, in manifest order."""
        return tuple(s.file for s in self.slots)


def validate_slots(ss: SlotSet) -> None:
    """Every rule the shell reader checks, and a few more (raises ManifestError)."""
    if ss.format != SLOTS_FORMAT:
        raise ManifestError(f"SLOTS: unsupported format {ss.format}")
    if not _WORD.match(ss.build):
        raise ManifestError(f"SLOTS: bad build id {ss.build!r}")
    if not _CONSOLE.match(ss.console):
        raise ManifestError(f"SLOTS: bad console {ss.console!r}")
    seen: dict[str, str] = {}
    for s in ss.slots:
        if not _SLOT_NAME.match(s.name):
            raise ManifestError(f"SLOTS: bad slot name {s.name!r}")
        if s.name in seen:
            raise ManifestError(f"SLOTS: slot {s.name} twice")
        if not _hex64(s.sha256):
            raise ManifestError(f"SLOTS: slot {s.name}: bad sha256 {s.sha256!r}")
        if not isinstance(s.size, int) or isinstance(s.size, bool) or s.size < 0:
            raise ManifestError(f"SLOTS: slot {s.name}: bad size {s.size!r}")
        lower_names = [n for n, _ in s.lower]
        if len(set(lower_names)) != len(lower_names):
            raise ManifestError(f"SLOTS: slot {s.name}: a lower slot twice")
        for n, sha in s.lower:
            if n not in seen:
                raise ManifestError(f"SLOTS: slot {s.name} was built against {n}, which is "
                                    "not a slot below it")
            if seen[n] != sha:
                raise ManifestError(f"SLOTS: slot {s.name} was built against {n} "
                                    f"{sha[:12]}, the set has {n} {seen[n][:12]} "
                                    "(incoherent set)")
        for pkg, ver in s.packages:
            if not _WORD.match(pkg) or not _WORD.match(ver):
                raise ManifestError(f"SLOTS: slot {s.name}: bad package {pkg!r} {ver!r}")
        seen[s.name] = s.sha256
    missing = [n for n in REQUIRED_SLOTS if n not in seen]
    if missing:
        raise ManifestError(f"SLOTS: no {', '.join(missing)} slot")


def format_slots(ss: SlotSet) -> str:
    validate_slots(ss)
    lines = [f"{SLOTS_MAGIC} {ss.format}", f"build {ss.build}", f"console {ss.console}"]
    npkg = 0
    for s in ss.slots:
        lower = ",".join(f"{n}={sha}" for n, sha in s.lower) or "-"
        lines.append(f"slot {s.name} {s.file} {s.sha256} {s.size} {lower}")
        for pkg, ver in s.packages:
            lines.append(f"pkg {s.name} {pkg} {ver}")
            npkg += 1
    lines.append(f"end {len(ss.slots)} {npkg}")
    return "\n".join(lines) + "\n"


def parse_slots(text: str, source: str = SLOTS_FILE) -> SlotSet:
    def bad(n: int, why: str) -> ManifestError:
        return ManifestError(f"{source}: line {n}: {why}")

    if not text:
        raise ManifestError(f"{source}: empty")
    if not text.endswith("\n"):
        raise ManifestError(f"{source}: truncated (no newline at the end)")
    lines = text[:-1].split("\n")
    if lines[0] != f"{SLOTS_MAGIC} {SLOTS_FORMAT}":
        raise bad(1, f"not a SLOTS manifest of format {SLOTS_FORMAT}: {lines[0][:40]!r}")
    if len(lines) < 3:
        raise ManifestError(f"{source}: truncated (no build and console lines)")
    build = lines[1].split(" ")
    if len(build) != 2 or build[0] != "build":
        raise bad(2, "expected `build <id>`")
    console = lines[2].split(" ")
    if len(console) != 2 or console[0] != "console":
        raise bad(3, "expected `console <name>`")
    slots: list[dict] = []
    npkg = 0
    ended = False
    for n, line in enumerate(lines[3:], start=4):
        if ended:
            raise bad(n, "text after the `end` line")
        f = line.split(" ")
        if f[0] == "slot" and len(f) == 6:
            name, file, sha, size, lower = f[1:]
            if not _SLOT_NAME.match(name):
                raise bad(n, f"bad slot name {name!r}")
            if not _hex64(sha):
                raise bad(n, f"bad sha256 of slot {name}")
            if file != slot_file(name, sha):
                raise bad(n, f"slot {name}: file {file!r} is not {slot_file(name, sha)!r}")
            if not size.isdigit() or not size.isascii():
                raise bad(n, f"slot {name}: bad size {size!r}")
            pairs = []
            if lower != "-":
                for item in lower.split(","):
                    ln, eq, lsha = item.partition("=")
                    if not eq or not _SLOT_NAME.match(ln) or not _hex64(lsha):
                        raise bad(n, f"slot {name}: bad lower slot {item!r}")
                    pairs.append((ln, lsha))
            if slots and _slot_rank(name) <= _slot_rank(slots[-1]["name"]):
                raise bad(n, f"slot {name} out of order (base, runtime, lume, modules, "
                             "core-* by name)")
            slots.append({"name": name, "sha256": sha, "size": int(size),
                          "lower": tuple(pairs), "packages": []})
        elif f[0] == "pkg" and len(f) == 4:
            if not slots or slots[-1]["name"] != f[1]:
                raise bad(n, f"pkg line of {f[1]!r} not right after its slot line")
            slots[-1]["packages"].append((f[2], f[3]))
            npkg += 1
        elif f[0] == "end" and len(f) == 3:
            if f[1:] != [str(len(slots)), str(npkg)]:
                raise bad(n, f"end counts {f[1]} {f[2]}, read {len(slots)} slots and {npkg} "
                             "pkg lines (truncated or garbled)")
            ended = True
        else:
            raise bad(n, f"unknown line {line[:60]!r}")
    if not ended:
        raise ManifestError(f"{source}: truncated (no `end` line)")
    ss = SlotSet(build=build[1], console=console[1],
                 slots=tuple(Slot(name=s["name"], sha256=s["sha256"], size=s["size"],
                                  lower=s["lower"], packages=tuple(s["packages"]))
                             for s in slots))
    try:
        validate_slots(ss)
    except ManifestError as e:
        raise ManifestError(f"{source}: {str(e).removeprefix('SLOTS: ')}") from None
    return ss


def read_slots(path: Path) -> SlotSet:
    return parse_slots(_read(path), str(path))


def write_slots(path: Path, ss: SlotSet) -> None:
    _write_atomic(path, format_slots(ss))


def missing_slot_files(console_dir: Path, ss: SlotSet) -> list[str]:
    """Slot files of the set that are not in <console>/ (what the initramfs refuses)."""
    return [f for f in ss.files() if not (console_dir / f).is_file()]


# --------------------------------------------------------------------------------------
# boot-files.sha256 and objects (D10)
# --------------------------------------------------------------------------------------
#
#   <sha256>  <BOOT path>        sha256sum lines (two spaces), VERSION last
#
# The same lines `sha256sum` writes and `sha256sum -c` reads; each file of the list is
# out/images/objects/<sha256>, stored once for every build that has it.

BOOT_LIST = "boot-files.sha256"
VERSION_FILE = "VERSION"
OBJECTS_DIR = "objects"     # out/images/objects/


def _check_boot_path(p: str) -> bool:
    return (bool(p) and not p.startswith(("/", "\\")) and "\n" not in p and "\r" not in p
            and all(part not in ("", ".", "..") for part in p.split("/")))


def format_boot_list(files: Mapping[str, str] | Iterable[tuple[str, str]]) -> str:
    """Lines of `files` (BOOT path -> sha256): sorted by path, VERSION last."""
    items = dict(files.items() if isinstance(files, Mapping) else files)
    if VERSION_FILE not in items:
        raise ManifestError(f"{BOOT_LIST}: no {VERSION_FILE}")
    for p, sha in items.items():
        if not _check_boot_path(p):
            raise ManifestError(f"{BOOT_LIST}: bad BOOT path {p!r}")
        if not _hex64(sha):
            raise ManifestError(f"{BOOT_LIST}: {p}: bad sha256 {sha!r}")
    order = [*sorted(p for p in items if p != VERSION_FILE), VERSION_FILE]
    return "".join(f"{items[p]}  {p}\n" for p in order)


def parse_boot_list(text: str, source: str = BOOT_LIST) -> list[tuple[str, str]]:
    """(BOOT path, sha256) in file order, VERSION last (as image.read_boot_list)."""
    if not text:
        raise ManifestError(f"{source}: empty")
    if not text.endswith("\n"):
        raise ManifestError(f"{source}: truncated (no newline at the end)")
    out: list[tuple[str, str]] = []
    seen = set()
    for n, line in enumerate(text[:-1].split("\n"), start=1):
        sha, sep, path = line.partition("  ")
        if not sep or not _hex64(sha):
            raise ManifestError(f"{source}: line {n}: not `<sha256>  <path>`: {line[:80]!r}")
        if not _check_boot_path(path):
            raise ManifestError(f"{source}: line {n}: bad BOOT path {path!r}")
        if path in seen:
            raise ManifestError(f"{source}: line {n}: {path} twice")
        seen.add(path)
        out.append((path, sha))
    if out[-1][0] != VERSION_FILE:
        raise ManifestError(f"{source}: truncated ({VERSION_FILE} is not the last line)")
    return out


def read_boot_list(path: Path) -> list[tuple[str, str]]:
    return parse_boot_list(_read(path), str(path))


def write_boot_list(path: Path, files: Mapping[str, str] | Iterable[tuple[str, str]]) -> None:
    _write_atomic(path, format_boot_list(files))


def object_path(objects: Path, sha256: str) -> Path:
    if not _hex64(sha256):
        raise ManifestError(f"bad object name {sha256!r}")
    return objects / sha256


def store_object(objects: Path, src: Path) -> str:
    """Copy `src` to objects/<sha256> unless it is there already; return its sha256."""
    sha = sha256_file(src)
    dest = object_path(objects, sha)
    if not dest.is_file():
        objects.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f"{sha}.tmp")
        shutil.copyfile(src, tmp)
        if sha256_file(tmp) != sha:
            tmp.unlink()
            raise ManifestError(f"{src}: changed while it was stored")
        tmp.replace(dest)
    return sha


def missing_objects(objects: Path, files: Iterable[tuple[str, str]]) -> list[str]:
    """BOOT paths of the list whose object is not stored."""
    return [p for p, sha in files if not object_path(objects, sha).is_file()]


# --------------------------------------------------------------------------------------
# .lume-content, the inputs hash in .PKGINFO `commit`, hashes.json (D3)
# --------------------------------------------------------------------------------------
#
#   .lume-content     one line: `lume-content 1 <sha256>`
#   .PKGINFO          `commit = <first 40 hex digits of the inputs sha256>`
#
# The content hash is the sha256 of the content listing: one line per file of the package
# (sorted by path) and one per metadata field of .PKGINFO, minus the fields that change on
# every build (VOLATILE_PKGINFO; pkgver without its -rN):
#
#   f <mode> <uid>:<gid> <sha256 of the data> <path>
#   l <mode> <uid>:<gid> <sha256 of the link target> <path>
#   d <mode> <uid>:<gid> - <path>
#   m <key> <value>
#
# <mode> is the permission bits in 4 octal digits. The inputs hash is the sha256 of the
# sorted lines `<label> <sha256>` of every input (APKBUILD, sources, build script, the
# versions of the build dependencies...): which inputs go in is up to the fragment build.

LUME_CONTENT = ".lume-content"
LUME_CONTENT_MAGIC = "lume-content"
LUME_CONTENT_FORMAT = 1
COMMIT_LEN = 40     # .PKGINFO commit keeps the shape of a git commit id
VOLATILE_PKGINFO = frozenset({"builddate", "commit", "datahash", "size", "packager"})
_PKGREL = re.compile(r"-r[0-9]+$")


def format_lume_content(sha256: str) -> str:
    if not _hex64(sha256):
        raise ManifestError(f"{LUME_CONTENT}: bad sha256 {sha256!r}")
    return f"{LUME_CONTENT_MAGIC} {LUME_CONTENT_FORMAT} {sha256}\n"


def parse_lume_content(text: str, source: str = LUME_CONTENT) -> str:
    f = text.removesuffix("\n").split(" ") if text.endswith("\n") else None
    if (f is None or len(f) != 3 or f[0] != LUME_CONTENT_MAGIC
            or f[1] != str(LUME_CONTENT_FORMAT) or not _hex64(f[2])):
        raise ManifestError(f"{source}: not `{LUME_CONTENT_MAGIC} {LUME_CONTENT_FORMAT} "
                            f"<sha256>`: {text[:90]!r}")
    return f[2]


def commit_of_inputs(inputs_sha256: str) -> str:
    """The .PKGINFO `commit` value for an inputs hash."""
    if not _hex64(inputs_sha256):
        raise ManifestError(f"bad inputs hash {inputs_sha256!r}")
    return inputs_sha256[:COMMIT_LEN]


def parse_pkginfo(text: str) -> list[tuple[str, str]]:
    """(key, value) of a .PKGINFO in order; keys like `depend` repeat."""
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.startswith("#"):
            continue
        key, sep, value = line.partition(" = ")
        if not sep or not key or " " in key:
            raise ManifestError(f".PKGINFO: line {n}: not `key = value`: {line[:80]!r}")
        out.append((key, value))
    return out


def pkginfo_commit(text: str) -> str | None:
    for key, value in parse_pkginfo(text):
        if key == "commit":
            return value
    return None


@dataclass(frozen=True)
class ContentEntry:
    path: str           # relative, no leading slash
    kind: str           # f (file), l (symlink), d (directory)
    mode: int           # permission bits
    digest: str = "-"   # sha256 of the data (f) or of the link target (l); "-" for d
    uid: int = 0
    gid: int = 0

    def line(self) -> str:
        if self.kind not in ("f", "l", "d") or not _check_boot_path(self.path) \
                or " " in self.path:
            raise ManifestError(f"bad content entry {self!r}")
        if (self.kind == "d") != (self.digest == "-") or \
                (self.kind != "d" and not _hex64(self.digest)):
            raise ManifestError(f"bad digest in content entry {self!r}")
        return f"{self.kind} {self.mode & 0o7777:04o} {self.uid}:{self.gid} " \
               f"{self.digest} {self.path}"


def content_entries(root: Path, owner=lambda p: (0, 0)) -> list[ContentEntry]:
    """Entries of the tree `root` (an abuild pkgdir). `owner(path)` gives (uid, gid):
    root by default, as abuild packs files unless package() chowns them."""
    out = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        uid, gid = owner(p)
        if stat.S_ISLNK(st.st_mode):
            digest = hashlib.sha256(os.readlink(p).encode()).hexdigest()
            out.append(ContentEntry(rel, "l", stat.S_IMODE(st.st_mode), digest, uid, gid))
        elif stat.S_ISDIR(st.st_mode):
            out.append(ContentEntry(rel, "d", stat.S_IMODE(st.st_mode), "-", uid, gid))
        elif stat.S_ISREG(st.st_mode):
            out.append(ContentEntry(rel, "f", stat.S_IMODE(st.st_mode), sha256_file(p),
                                    uid, gid))
        else:
            raise ManifestError(f"{p}: not a file, link or directory")
    return out


def content_listing(entries: Iterable[ContentEntry],
                    pkginfo: Iterable[tuple[str, str]] = ()) -> str:
    lines = sorted(e.line() for e in entries)
    meta = []
    for key, value in pkginfo:
        if key in VOLATILE_PKGINFO:
            continue
        if key == "pkgver":
            value = _PKGREL.sub("", value)
        meta.append(f"m {key} {value}")
    return "".join(f"{x}\n" for x in [*lines, *sorted(meta)])


def content_hash(entries: Iterable[ContentEntry],
                 pkginfo: Iterable[tuple[str, str]] = ()) -> str:
    return hashlib.sha256(content_listing(entries, pkginfo).encode()).hexdigest()


def inputs_hash(inputs: Mapping[str, str]) -> str:
    """sha256 of the sorted `<label> <sha256>` lines of every input of a fragment."""
    lines = []
    for label, sha in inputs.items():
        if not label or any(c.isspace() for c in label) or not _hex64(sha):
            raise ManifestError(f"bad input {label!r} {sha!r}")
        lines.append(f"{label} {sha}\n")
    return hashlib.sha256("".join(sorted(lines)).encode()).hexdigest()


HASHES_FILE = "hashes.json"
HASHES_FORMAT = 1


@dataclass(frozen=True)
class PackageHashes:
    version: str        # pkgver-rN of the newest published package
    inputs: str         # inputs sha256 (full; .PKGINFO keeps its first 40 digits)
    content: str        # content sha256 (as in .lume-content)
    file: str           # <name>-<version>.apk in out/repo/<arch>/


@dataclass
class RepoHashes:
    arch: str
    packages: dict[str, PackageHashes] = field(default_factory=dict)


_ARCH = re.compile(r"^[a-z0-9_]+$")
_APK_VERSION = re.compile(r"^[A-Za-z0-9_.+~]+-r[0-9]+$")


def _validate_package(name: str, p: PackageHashes, source: str) -> None:
    if not _WORD.match(name):
        raise ManifestError(f"{source}: bad package name {name!r}")
    if not isinstance(p.version, str) or not _APK_VERSION.match(p.version):
        raise ManifestError(f"{source}: {name}: bad version {p.version!r}")
    for what in ("inputs", "content"):
        if not isinstance(getattr(p, what), str) or not _hex64(getattr(p, what)):
            raise ManifestError(f"{source}: {name}: bad {what} hash {getattr(p, what)!r}")
    if p.file != f"{name}-{p.version}.apk":
        raise ManifestError(f"{source}: {name}: file {p.file!r} is not "
                            f"{name}-{p.version}.apk")


def format_hashes(repo: RepoHashes) -> str:
    if not _ARCH.match(repo.arch):
        raise ManifestError(f"{HASHES_FILE}: bad arch {repo.arch!r}")
    for name, p in repo.packages.items():
        _validate_package(name, p, HASHES_FILE)
    doc = {"format": HASHES_FORMAT, "arch": repo.arch,
           "packages": {n: {"version": p.version, "inputs": p.inputs,
                            "content": p.content, "file": p.file}
                        for n, p in sorted(repo.packages.items())}}
    return json.dumps(doc, indent=2) + "\n"


def parse_hashes(text: str, source: str = HASHES_FILE, arch: str | None = None) -> RepoHashes:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as e:
        raise ManifestError(f"{source}: truncated or garbled JSON ({e})") from None
    if not isinstance(doc, dict) or set(doc) != {"format", "arch", "packages"}:
        raise ManifestError(f"{source}: expected the keys format, arch, packages")
    if doc["format"] != HASHES_FORMAT:
        raise ManifestError(f"{source}: unsupported format {doc['format']!r}")
    if not isinstance(doc["arch"], str) or not _ARCH.match(doc["arch"]):
        raise ManifestError(f"{source}: bad arch {doc['arch']!r}")
    if arch is not None and doc["arch"] != arch:
        raise ManifestError(f"{source}: index of {doc['arch']}, expected {arch}")
    if not isinstance(doc["packages"], dict):
        raise ManifestError(f"{source}: packages is not an object")
    packages = {}
    for name, entry in doc["packages"].items():
        if not isinstance(entry, dict) or set(entry) != {"version", "inputs", "content",
                                                         "file"}:
            raise ManifestError(f"{source}: {name}: expected the keys version, inputs, "
                                "content, file")
        p = PackageHashes(**entry)
        _validate_package(name, p, source)
        packages[name] = p
    return RepoHashes(arch=doc["arch"], packages=packages)


def read_hashes(path: Path, arch: str | None = None) -> RepoHashes:
    """The local index; an empty one when it does not exist yet (first build)."""
    if not path.exists():
        if arch is None:
            raise ManifestError(f"{path}: missing")
        return RepoHashes(arch=arch)
    return parse_hashes(_read(path), str(path), arch)


def write_hashes(path: Path, repo: RepoHashes) -> None:
    _write_atomic(path, format_hashes(repo))
