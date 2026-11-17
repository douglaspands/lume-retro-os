"""Stage skipping (build-speed D6): a stage whose inputs did not change is not run again.

Each skippable stage lists its inputs in ONE function (`dtb_inputs`, `rootfs_inputs`,
`initramfs_inputs`, `system_inputs`). `run_stage` hashes them and compares the hash with
`<output>.inputs`, written beside the output after the last successful run:

    stage <sha256 of everything below>
    input <label> <sha256 of that input>
    ...

Same hash and the output present: the stage is skipped (one `skipped (...)` line in the
build summary). `r36os build --clean` (`set_clean`) forces every stage. The `.inputs` file
is removed before the stage runs, so a failed run never leaves a stale hash behind.

Never an input: BOOT/VERSION and its build id (it changes on every build).
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path
from typing import Callable

from r36os.paths import REPO_ROOT
from r36os.stages import StageTimer

_clean = False


def set_clean(value: bool) -> None:
    """`r36os build --clean`: run every stage even if its inputs did not change."""
    global _clean
    _clean = value


def is_clean() -> bool:
    return _clean


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def inputs_file(output: Path) -> Path:
    return output.with_name(output.name + ".inputs")


class Inputs:
    """An ordered list of (label, hash) pairs; `unknown` set means it cannot be proven."""

    def __init__(self) -> None:
        self.items: list[tuple[str, str]] = []
        self.unknown: str = ""

    def text(self, label: str, value: str) -> "Inputs":
        self.items.append((label, hashlib.sha256(value.encode()).hexdigest()))
        return self

    def file(self, label: str, path: Path) -> "Inputs":
        self.items.append((label, sha256_file(path) if path.is_file() else "missing"))
        return self

    def tree(self, label: str, root: Path) -> "Inputs":
        """Every file under `root` (relative name, exec bit, content; symlink targets)."""
        h = hashlib.sha256()
        if root.is_dir():
            for p in sorted(root.rglob("*")):
                if "__pycache__" in p.parts:
                    continue
                rel = str(p.relative_to(root)).encode()
                if p.is_symlink():
                    h.update(b"L\0" + rel + b"\0" + str(p.readlink()).encode() + b"\0")
                elif p.is_file():
                    mode = b"x" if p.stat().st_mode & 0o111 else b"-"
                    h.update(b"F\0" + rel + b"\0" + mode + sha256_file(p).encode() + b"\0")
        else:
            h.update(b"missing")
        self.items.append((label, h.hexdigest()))
        return self

    def files(self, label: str, paths: list[Path]) -> "Inputs":
        h = hashlib.sha256()
        for p in paths:
            h.update(p.name.encode() + b"\0" + sha256_file(p).encode() + b"\0")
        self.items.append((label, h.hexdigest()))
        return self

    def digest(self) -> str:
        h = hashlib.sha256()
        for label, value in self.items:
            h.update(f"{label}\0{value}\0".encode())
        return h.hexdigest()

    def render(self) -> str:
        lines = [f"stage {self.digest()}"]
        lines += [f"input {label} {value}" for label, value in self.items]
        return "\n".join(lines) + "\n"


def _is_fresh(output: Path, required: list[Path], inputs: Inputs) -> bool:
    for p in [output, *required]:
        if not p.exists() or (p.is_dir() and not any(p.iterdir())):
            return False
    try:
        first = inputs_file(output).read_text().splitlines()[0]
    except (OSError, IndexError):
        return False
    return first == f"stage {inputs.digest()}"


def run_stage(timer: StageTimer, name: str, output: Path, inputs: Callable[[], Inputs],
              fn: Callable[[], None], required: list[Path] | None = None) -> bool:
    """Run `fn` as stage `name` unless the inputs match `<output>.inputs`; True if it ran."""
    marker = inputs_file(output)
    inp = inputs()
    if inp.unknown:
        marker.unlink(missing_ok=True)
        with timer.stage(name):
            fn()
        return True
    if not _clean and _is_fresh(output, required or [], inp):
        timer.skip(name, f"inputs unchanged ({inp.digest()[:12]})")
        return False
    marker.unlink(missing_ok=True)
    with timer.stage(name):
        fn()
    marker.write_text(inp.render())
    return True


# --- device tree: which kernel patches count -----------------------------------------------

_DT_PATH = re.compile(
    r"^(Documentation/devicetree/|include/dt-bindings/|arch/[^/]+/boot/dts/)")
_DIFF_GIT = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)


def touches_device_tree(patch_text: str) -> bool:
    return any(_DT_PATH.match(a) or _DT_PATH.match(b) for a, b in _DIFF_GIT.findall(patch_text))


def dt_patches() -> list[Path]:
    from r36os import kernel

    return [p for p in kernel.patches()
            if touches_device_tree(p.read_text(errors="replace"))]


# --- the inputs of each stage (one place per stage) ----------------------------------------

def dtb_inputs(board: str, arch: str, vendor: str) -> Inputs:
    from r36os import kernel

    boarddir = REPO_ROOT / "board" / board
    script = kernel._DTBS_SCRIPT.format(arch=arch, vendor=vendor, dtc_flags=kernel._DTC_FLAGS)
    return (Inputs()
            .text("kernel", f"{kernel.KERNEL_VERSION} {kernel.KERNEL_SHA256}")
            .text("dtbs-script", script)  # compile flags, dt-validate and schema steps
            .tree("dts", boarddir / "dts")
            .tree("dts-vendor", boarddir / "dts-vendor")
            .files("dt-patches", dt_patches()))


_mirror_hashes: dict[str, str] = {}


def mirror_index_hash(version: str, mirror: str, arch: str) -> str:
    """SHA256 of the APKINDEX of main and community the rootfs build installs from; "" if
    the mirror cannot be reached (the stage then cannot be proven unchanged)."""
    h = hashlib.sha256()
    for repo in ("main", "community"):
        url = f"{mirror}/v{version}/{repo}/{arch}/APKINDEX.tar.gz"
        if url not in _mirror_hashes:
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    _mirror_hashes[url] = hashlib.sha256(r.read()).hexdigest()
            except OSError:
                return ""
        h.update(_mirror_hashes[url].encode())
    return h.hexdigest()


def _local_index(target) -> Path:
    from r36os.packages import repo_dir

    return repo_dir(target) / "APKINDEX.tar.gz"


def rootfs_inputs(target, script: str, packages: list[str], language: str,
                  os_release: str, leiame_text: str, mirror_hash: str) -> Inputs:
    """`script` is the formatted build script (mirror, versions, tty, board, language)."""
    inp = (Inputs()
           .text("script", script)
           .text("packages", "\n".join(packages))
           .text("language", language)
           .text("os-release", os_release)
           .text("leiame", leiame_text)
           .file("local-apkindex", _local_index(target))
           .text("mirror-apkindex", mirror_hash)
           .file("configure.sh", REPO_ROOT / "rootfs/configure.sh")
           .file("serial", REPO_ROOT / "board" / target.name / "serial")
           .tree("overlay", REPO_ROOT / "rootfs/overlay"))
    if not mirror_hash:
        inp.unknown = "Alpine mirror APKINDEX not reachable"
    return inp


def initramfs_inputs(target, rootfs_tar: Path) -> Inputs:
    from r36os import initramfs
    from r36os.image import SOC_DIR

    board = REPO_ROOT / "board" / target.name
    inp = (Inputs()
           .text("board", target.name)
           .text("soc", SOC_DIR.get(target.name, ""))
           .text("pack-script", initramfs._PACK)
           .tree("initramfs", REPO_ROOT / "initramfs")
           .file("bootsel-keys", board / "bootsel-keys")
           .file("bootsel-switch", board / "bootsel-switch")
           .file("local-apkindex", _local_index(target)))
    # the modules of the list come out of the rootfs (VM: the packaged kernel's)
    if (REPO_ROOT / f"initramfs/modules-{target.name}.txt").exists():
        inp.file("rootfs.tar", rootfs_tar)
    return inp


def modules_inputs(modules_tar: Path, script: str) -> Inputs:
    """The console modules image (BOOT <console>/modules): the kernel modules.tar and the
    script that packs it (compression included)."""
    return Inputs().file("modules.tar", modules_tar).text("script", script)


def system_inputs(rootfs_tar: Path, squashfs_options: str, limit_mib: int) -> Inputs:
    return (Inputs()
            .file("rootfs.tar", rootfs_tar)
            .text("mksquashfs-options", squashfs_options)
            .text("limit-mib", str(limit_mib)))
