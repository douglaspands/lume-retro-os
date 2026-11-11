"""Our own minimal initramfs (D6): static busybox, static sfdisk/exFAT, init.

On the VM it also carries the linux-virt boot modules; on the consoles those drivers are
built into the kernel (and the initramfs itself is built into the kernel too).
"""

from __future__ import annotations

import gzip
import lzma
import shutil
import tarfile
from pathlib import Path, PurePosixPath

from r36os.container import Container, ensure_builder
from r36os.packages import keys_dir
from r36os.paths import REPO_ROOT, ensure_dir, out_dir
from r36os.rootfs import target_out
from r36os.targets import Target


def _decompress(name: str, data: bytes) -> bytes:
    if name.endswith(".gz"):
        return gzip.decompress(data)
    if name.endswith(".xz"):
        return lzma.decompress(data)
    if name.endswith(".zst"):
        from compression import zstd

        return zstd.decompress(data)
    return data


def module_name(path: str) -> str:
    base = PurePosixPath(path).name.split(".ko")[0]
    return base.replace("-", "_")


def resolve_modules(dep_text: str, builtin_text: str, wanted: list[str]) -> list[str]:
    """Paths (relative to the kernel dir) in load order, dependencies first."""
    deps: dict[str, list[str]] = {}
    by_name: dict[str, str] = {}
    for line in dep_text.splitlines():
        if ":" not in line:
            continue
        mod, rest = line.split(":", 1)
        deps[mod] = rest.split()
        by_name[module_name(mod)] = mod
    builtin = {module_name(l) for l in builtin_text.split()}
    order: list[str] = []

    def visit(path: str) -> None:
        for d in deps.get(path, []):
            visit(d)
        if path not in order:
            order.append(path)

    for name in wanted:
        name = name.replace("-", "_")
        if name in by_name:
            visit(by_name[name])
        elif name not in builtin:
            raise KeyError(f"module {name} does not exist in the kernel")
    return order


def _read_list(path: Path) -> list[str]:
    return [l.split("#")[0].strip() for l in path.read_text().splitlines() if l.split("#")[0].strip()]


def stage_modules(rootfs_tar: Path, wanted: list[str], dest: Path) -> list[str]:
    """Copy the (decompressed) modules to dest/lib/modules and return the load order."""
    with tarfile.open(rootfs_tar) as tar:
        names = tar.getnames()
        kdirs = sorted({n.split("/")[3] for n in names
                        if n.startswith("./lib/modules/") and n.count("/") >= 4})
        if len(kdirs) != 1:
            raise RuntimeError(f"expected one kernel in /lib/modules, found {kdirs}")
        base = f"./lib/modules/{kdirs[0]}/"

        def read(rel: str) -> bytes:
            return tar.extractfile(base + rel).read()

        builtin = read("modules.builtin").decode() if base + "modules.builtin" in names else ""
        order = resolve_modules(read("modules.dep").decode(), builtin, wanted)
        moddir = ensure_dir(dest / "lib/modules")
        loaded = []
        for rel in order:
            ko = module_name(rel) + ".ko"
            (moddir / ko).write_bytes(_decompress(rel, read(rel)))
            loaded.append(ko)
    (dest / "etc").mkdir(exist_ok=True)
    (dest / "etc/modules").write_text("\n".join(loaded) + "\n")
    return loaded


_PACK = """
cp /keys/r36os.rsa.pub /etc/apk/keys/
apk add -q -X /repo r36os-initramfs-static
S=/stage
mkdir -p $S/bin $S/sbin $S/proc $S/sys $S/dev $S/tmp $S/boot $S/lower $S/rw $S/newroot
cp /bin/busybox.static $S/bin/busybox
cp /usr/lib/r36os/initramfs/bin/* $S/bin/
cd $S
find . | sort | cpio -o -H newc -R 0:0 --quiet > /out/initramfs.cpio
gzip -9n < /out/initramfs.cpio > /out/initramfs
"""


def build_initramfs(target: Target) -> Path:
    out = target_out(target)
    stage = out / "initramfs-stage"
    shutil.rmtree(stage, ignore_errors=True)
    ensure_dir(stage / "lib")
    shutil.copy(REPO_ROOT / "initramfs/init", stage / "init")
    (stage / "init").chmod(0o755)
    shutil.copy(REPO_ROOT / "initramfs/lib/storage.sh", stage / "lib/storage.sh")
    mods = REPO_ROOT / f"initramfs/modules-{target.name}.txt"
    if mods.exists():
        stage_modules(out / "rootfs.tar", _read_list(mods), stage)
    Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes={stage: "/stage", out: "/out", out_dir() / "repo": "/repo", keys_dir(): "/keys"},
    ).sh(_PACK)
    shutil.rmtree(stage)
    return out / "initramfs"
