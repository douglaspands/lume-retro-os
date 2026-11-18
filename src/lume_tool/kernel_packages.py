"""The kernel of each architecture as packages (build-speed D2, D3, task 7.3).

The console kernel is cross-compiled outside abuild (kernel.build_kernel); its outputs are
wrapped, with no compile, into three packages per architecture, with the same names on
armv7 (GA36) and aarch64 (R36S):

    lume-kernel    boot/zImage (armv7) or boot/Image (aarch64)
    lume-modules   boot/modules.squashfs (the modules image, the `modules` slot)
    lume-dtbs      boot/dtbs/<soc>/*.dtb and boot/dtbs/<soc>/vendor/*.dtb

The files live under /boot inside the package; they are never installed into a rootfs (not
in rootfs/packages.txt). The .apk is written here in Python (data tar with the per-file
SHA1 pax records of `abuild-tar --hash`, .PKGINFO with `datahash`), then goes through the
fragment rule of packages.py: same content as the published version -> nothing published,
the version stays; different -> the next pkgrel, `.lume-content`, signed, out/repo/<arch>/
and hashes.json. The BOOT kernel and DTBs and the modules slot are then taken from the data
of the published packages (extract_published -> out/<console>/kernel-pkg/), so the console
gets exactly what the repository holds, and an architecture whose kernel did not change
keeps its versions and its bytes (a push to it sends nothing).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import tarfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from lume_tool import kernel, manifests
from lume_tool.paths import ensure_dir

NAMES = ("lume-kernel", "lume-modules", "lume-dtbs")
PKG_DIR = "kernel-pkg"                       # out/<console>/kernel-pkg/: published data
MODULES_PATH = "boot/modules.squashfs"
PACKAGES_LIST = "PACKAGES"                   # kernel-pkg/PACKAGES: "<name> <version>"
DESCRIPTIONS = {
    "lume-kernel": "Lume console kernel image",
    "lume-modules": "Lume console kernel modules (squashfs image)",
    "lume-dtbs": "Lume console device trees",
}
LICENSE = "GPL-2.0-only"
URL = "https://www.kernel.org/"
SHA1_PAX = "APK-TOOLS.checksum.SHA1"         # what `abuild-tar --hash` writes per file


class KernelPackageError(RuntimeError):
    pass


# --- what goes in each package -------------------------------------------------------

def soc_dir(board: str) -> str:
    from lume_tool import image
    return image.SOC_DIR[board]


def image_name(board: str) -> str:
    return kernel.KERNEL_TARGETS[board][3]


def package_files(board: str, kdir: Path) -> dict[str, dict[str, Path]]:
    """Package name -> {path in the package -> source in out/<console>/kernel/}."""
    soc = soc_dir(board)
    dtbs = {f"boot/dtbs/{soc}/{p.name}": p for p in sorted((kdir / "dtbs").glob("*.dtb"))}
    dtbs.update({f"boot/dtbs/{soc}/vendor/{p.name}": p
                 for p in sorted((kdir / "dtbs" / "vendor").glob("*.dtb"))})
    files = {
        "lume-kernel": {f"boot/{image_name(board)}": kdir / image_name(board)},
        "lume-modules": {MODULES_PATH: kdir / "modules"},
        "lume-dtbs": dtbs,
    }
    for name, f in files.items():
        missing = [str(src) for src in f.values() if not src.is_file()]
        if not f or missing:
            raise KernelPackageError(f"{name} ({board}): missing "
                                     + (", ".join(missing) or f"files in {kdir}"))
    return files


# --- the .apk ------------------------------------------------------------------------

def _epoch(stamp: str) -> int:
    """KBUILD_BUILD_TIMESTAMP ("YYYY-MM-DD HH:MM:SS UTC") as seconds: the mtime of every
    member, so the same files give a byte-identical data segment."""
    return int(datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S UTC")
               .replace(tzinfo=timezone.utc).timestamp())


def _dirs(paths) -> list[str]:
    out = set()
    for p in paths:
        parts = PurePosixPath(p).parts
        for i in range(1, len(parts)):
            out.add("/".join(parts[:i]))
    return sorted(out)


def _check_path(path: str) -> None:
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] != "boot":
        raise KernelPackageError(f"bad path in a kernel package: {path!r}")


def data_segment(files: dict[str, Path], mtime: int) -> tuple[bytes, int]:
    """(gzip data segment, installed size) of `files` (package path -> source): root-owned,
    0644 files and 0755 directories, sorted, each file with its SHA1 pax record."""
    buf = io.BytesIO()
    size = 0
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as tf:
        for d in _dirs(files):
            m = tarfile.TarInfo(d)
            m.type, m.mode, m.mtime = tarfile.DIRTYPE, 0o755, mtime
            m.uname = m.gname = "root"
            tf.addfile(m)
        for path in sorted(files):
            _check_path(path)
            data = files[path].read_bytes()
            m = tarfile.TarInfo(path)
            m.size, m.mode, m.mtime = len(data), 0o644, mtime
            m.uname = m.gname = "root"
            m.pax_headers = {SHA1_PAX: hashlib.sha1(data).hexdigest()}
            tf.addfile(m, io.BytesIO(data))
            size += len(data)
    return gzip.compress(buf.getvalue(), compresslevel=6, mtime=0), size


def pkginfo(name: str, version: str, arch: str, size: int, commit: str,
            datahash: str, builddate: int) -> str:
    """The .PKGINFO, in the order abuild writes it."""
    pairs = [("pkgname", name), ("pkgver", version), ("pkgdesc", DESCRIPTIONS[name]),
             ("url", URL), ("builddate", str(builddate)), ("packager", "lume"),
             ("size", str(size)), ("arch", arch), ("origin", name), ("commit", commit),
             ("license", LICENSE), ("datahash", datahash)]
    return "# Generated by lume (kernel_packages)\n" + "".join(
        f"{k} = {v}\n" for k, v in pairs)


def control_segment(pkginfo_text: str, mtime: int) -> bytes:
    """The unsigned control segment: .PKGINFO without the end-of-archive blocks."""
    body = pkginfo_text.encode()
    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT)
    m = tarfile.TarInfo(".PKGINFO")
    m.size, m.mode, m.mtime = len(body), 0o644, mtime
    m.uname = m.gname = "root"
    tf.addfile(m, io.BytesIO(body))
    end = tf.offset
    tf.close()
    return gzip.compress(buf.getvalue()[:end], compresslevel=9, mtime=0)


def make_apk(dest_dir: Path, name: str, version: str, arch: str, files: dict[str, Path],
             commit: str, mtime: int) -> Path:
    """Write the unsigned `<name>-<version>.apk` into `dest_dir` (signed on publish)."""
    data, size = data_segment(files, mtime)
    info = pkginfo(name, version, arch, size, commit, hashlib.sha256(data).hexdigest(),
                   int(time.time()))
    apk = ensure_dir(dest_dir) / f"{name}-{version}.apk"
    apk.write_bytes(control_segment(info, mtime) + data)
    return apk


def inputs_of(name: str, pkgver: str, arch: str, files: dict[str, Path]) -> str:
    """The inputs hash of a kernel package: its files, version, arch and this module."""
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731
    inputs = {"name": sha(name), "pkgver": sha(pkgver), "arch": sha(arch),
              "builder": manifests.sha256_file(Path(__file__))}
    for path, src in files.items():
        inputs[f"file:{path}"] = manifests.sha256_file(src)
    return manifests.inputs_hash(inputs)


# --- publish and extract ---------------------------------------------------------------

@dataclass(frozen=True)
class Outcome:
    name: str
    version: str        # the published version the console gets
    published: bool     # a new version entered out/repo/<arch>/ in this run


def publish(board: str, kdir: Path) -> list[Outcome]:
    """Package out/<console>/kernel/ and publish what changed in out/repo/<arch>/.

    Per package: inputs equal to hashes.json (and the file present) -> nothing done; else
    the .apk is made in out/pkg-staging/kernel-<arch>/ with the next pkgrel and kept only
    when its content differs from the published one (packages._settle)."""
    from lume_tool import fragments as frag
    from lume_tool import packages
    from lume_tool.targets import TARGETS

    arch = TARGETS[board].alpine_arch
    pkgver = kernel.KERNEL_VERSION
    mtime = _epoch(kernel.build_stamp(board))
    tag = f"kernel-{arch}"
    staging = packages.staging_dir() / tag
    shutil.rmtree(staging, ignore_errors=True)
    out: list[Outcome] = []
    changed = False
    for name, files in package_files(board, kdir).items():
        inputs = inputs_of(name, pkgver, arch, files)
        new = False
        if packages._up_to_date(name, inputs, [arch]):
            print(f"pkg {name} ({arch}): inputs unchanged, not packaged", flush=True)
        else:
            rel = frag.next_pkgrel([packages.arch_repo_dir(arch)], {name}, pkgver, 0,
                                   [packages.read_repo_hashes(arch)])
            apk = make_apk(staging, name, f"{pkgver}-r{rel}", arch, files,
                           manifests.commit_of_inputs(inputs), mtime)
            new = bool(packages._settle(name, inputs, [apk], [arch], tag))
        changed |= new
        out.append(Outcome(name, packages.read_repo_hashes(arch).packages[name].version,
                           new))
    shutil.rmtree(staging, ignore_errors=True)
    if changed and packages.clean_repo(arch):
        packages.reindex([arch])
    return out


def published(arch: str) -> dict[str, Path]:
    """Package name -> the published .apk that hashes.json of `arch` names, checked by its
    `.lume-content`."""
    from lume_tool import fragments as frag
    from lume_tool import packages

    hashes = packages.read_repo_hashes(arch).packages
    out = {}
    for name in NAMES:
        entry = hashes.get(name)
        apk = packages.arch_repo_dir(arch) / entry.file if entry else None
        if apk is None or not apk.is_file():
            raise KernelPackageError(f"{name} is not published in out/repo/{arch}")
        if frag.apk_lume_content(apk) != entry.content:
            raise KernelPackageError(f"{apk}: content differs from hashes.json")
        out[name] = apk
    return out


def extract_published(board: str, layer_out: Path) -> Path:
    """Extract the data of the published lume-kernel, lume-modules and lume-dtbs of the
    console's arch into out/<console>/kernel-pkg/ (replaced as a whole), with PACKAGES."""
    from lume_tool import fragments as frag
    from lume_tool import packages
    from lume_tool.targets import TARGETS

    arch = TARGETS[board].alpine_arch
    dest = layer_out / PKG_DIR
    tmp = layer_out / (PKG_DIR + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    ensure_dir(tmp)
    lines = []
    for name, apk in published(arch).items():
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(frag.split_apk(apk).data)),
                          mode="r:") as tf:
            for m in tf:
                _check_path(m.name.rstrip("/"))
                target = tmp / m.name
                if m.isdir():
                    ensure_dir(target)
                elif m.isreg():
                    ensure_dir(target.parent)
                    f = tf.extractfile(m)
                    target.write_bytes(f.read() if f else b"")
                else:
                    raise KernelPackageError(f"{apk.name}: {m.name} is not a file")
        version = dict(packages.read_apk_pkginfo(apk))["pkgver"]
        lines.append(f"{name} {version}\n")
    (tmp / PACKAGES_LIST).write_text("".join(lines))
    shutil.rmtree(dest, ignore_errors=True)
    tmp.replace(dest)
    return dest


def package_console(board: str, layer_out: Path) -> list[Outcome]:
    """Publish the kernel packages of `board` from out/<console>/kernel/ and extract the
    published ones into out/<console>/kernel-pkg/."""
    res = publish(board, layer_out / "kernel")
    extract_published(board, layer_out)
    print(f"{board}: " + ", ".join(f"{o.name}-{o.version}"
                                   + (" (new)" if o.published else "") for o in res),
          flush=True)
    return res


def boot_sources(board: str, layer_out: Path) -> dict[str, Path]:
    """BOOT path -> extracted file: <console>/<image> and dtbs/<soc>/[vendor/]*.dtb."""
    root = layer_out / PKG_DIR / "boot"
    files = {f"{board}/{image_name(board)}": root / image_name(board)}
    for dtb in sorted((root / "dtbs").rglob("*.dtb")):
        files[dtb.relative_to(root).as_posix()] = dtb
    return files


def modules_image(layer_out: Path) -> Path:
    """The modules image of the published lume-modules (the `modules` slot)."""
    return layer_out / PKG_DIR / MODULES_PATH
