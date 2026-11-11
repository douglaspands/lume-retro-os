"""Mainline LTS kernel source for the consoles (D3): pinned download, patches and DTBs.

The official tarball is downloaded once into the cache and checked against its sha256.
The tree used by the build is an extracted copy with the patches from `kernel/patches/`
applied in order; it is rebuilt when the list or the contents of the patches change.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from r36os.paths import REPO_ROOT, cache_dir, ensure_dir

KERNEL_VERSION = "6.18.62"
KERNEL_URL = f"https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-{KERNEL_VERSION}.tar.xz"
# sha256sums.asc from cdn.kernel.org/pub/linux/kernel/v6.x/
KERNEL_SHA256 = "490a7aedf1b355c565d3a6c05333ccccb5da82064eca46b590448a7099d7d651"

PATCHES_DIR = REPO_ROOT / "kernel/patches"


def patches() -> list[Path]:
    """Patches in `kernel/patches/`, in name order (0001-..., 0002-...)."""
    return sorted(PATCHES_DIR.glob("*.patch"))


def patches_digest() -> str:
    h = hashlib.sha256()
    for p in patches():
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def tarball() -> Path:
    """The kernel tarball in the cache, downloaded and checked if needed."""
    dest = ensure_dir(cache_dir() / "distfiles") / f"linux-{KERNEL_VERSION}.tar.xz"
    if not dest.exists():
        tmp = dest.with_suffix(".part")
        print(f"downloading {KERNEL_URL}", flush=True)
        with urllib.request.urlopen(KERNEL_URL, timeout=120) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dest)
    h = hashlib.sha256()
    with dest.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != KERNEL_SHA256:
        raise RuntimeError(f"{dest.name}: sha256 {h.hexdigest()} != {KERNEL_SHA256}")
    return dest


def source_tree() -> Path:
    """Kernel tree with the patches applied (rebuilt when the patches change)."""
    import subprocess

    base = ensure_dir(cache_dir() / "src")
    tree = base / f"linux-{KERNEL_VERSION}-{patches_digest()}"
    stamp = tree / ".r36os-ready"
    if stamp.exists():
        return tree
    shutil.rmtree(tree, ignore_errors=True)
    for old in base.glob(f"linux-{KERNEL_VERSION}-*"):
        shutil.rmtree(old, ignore_errors=True)
    tmp = base / f"linux-{KERNEL_VERSION}.extract"
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"extracting linux-{KERNEL_VERSION}", flush=True)
    with tarfile.open(tarball()) as t:
        t.extractall(tmp, filter="data")
    (tmp / f"linux-{KERNEL_VERSION}").rename(tree)
    tmp.rmdir()
    for p in patches():
        print(f"applying {p.name}", flush=True)
        subprocess.run(["git", "apply", "--whitespace=nowarn", str(p)], cwd=tree, check=True)
    stamp.write_text(patches_digest() + "\n")
    return tree


# Flags from the kernel scripts/Makefile.dtbs (W=0), plus -@ for overlays
_DTC_FLAGS = ("-Wno-unit_address_vs_reg -Wno-avoid_unnecessary_addr_size -Wno-alias_paths "
              "-Wno-graph_child_address -Wno-interrupt_map -Wno-simple_bus_reg "
              "-Wno-unique_unit_address -Wunique_unit_address_if_enabled -@")

_DTBS_SCRIPT = """
set -eu
inc=/linux/scripts/dtc/include-prefixes
cd /dts
for f in *.dts; do
  n=${{f%.dts}}
  cpp -nostdinc -I /dts -I /linux/arch/{arch}/boot/dts/{vendor} -I $inc -undef -D__DTS__ \\
      -x assembler-with-cpp -o /tmp/$n.pp $f
  dtc -O dtb -b 0 {dtc_flags} -i /dts -o /out/$n.dtb /tmp/$n.pp
  echo "dtb: $n.dtb"
done
dt-mk-schema -j /linux/Documentation/devicetree/bindings > /tmp/schema.json
fail=0
for d in /out/*.dtb; do
  out=$(dt-validate -s /tmp/schema.json -m "$d" 2>&1) || fail=1
  if [ -n "$out" ]; then echo "$out"; fail=1; fi
done
[ $fail = 0 ] && echo "dt-validate: no errors"
exit $fail
"""


_KERNEL_SCRIPT = """
set -eu
export ARCH={arch} CROSS_COMPILE="ccache {cross}"
B=/build
cd /linux
make -s O=$B {defconfig}
scripts/kconfig/merge_config.sh -m -O $B $B/.config /board/kernel.config >/dev/null
make -s O=$B olddefconfig
# every option of the fragment must keep the requested value (a missing dependency drops it silently)
fail=0
grep -E '^CONFIG_' /board/kernel.config | while IFS= read -r want; do
  grep -qxF "$want" $B/.config || {{ echo "kernel.config: $want did not end up in .config"; exit 1; }}
done || fail=1
[ $fail = 0 ] || exit 1
make O=$B -j$(nproc) {image} modules 2> /out/build-warnings.log
rm -rf /tmp/mods
make -s O=$B INSTALL_MOD_PATH=/tmp/mods INSTALL_MOD_STRIP=1 modules_install
tar -C /tmp/mods --numeric-owner --sort=name -cf /out/modules.tar lib
cp $B/arch/{arch}/boot/{image} /out/{image}
cp $B/.config /out/config
make -s O=$B kernelrelease > /out/release
# no warnings accepted in our own drivers (kernel/patches/)
if grep -E '{own_files}' /out/build-warnings.log; then exit 1; fi
"""

# Our own drivers: any warning in them fails the build (9.1, 9.2)
OWN_DRIVER_FILES = ("panel-ga36mb-jd9366.c", "ga36mb-gamepad.c")

# target -> (ARCH, cross prefix, starting defconfig, image)
KERNEL_TARGETS = {
    "ga36": ("arm", "arm-linux-gnueabihf-", "sunxi_defconfig", "zImage"),
}


def build_kernel(board: str, out: Path, initramfs_dir: Path | None = None) -> Path:
    """Cross-compile the console kernel (D3): image, modules.tar, config and release.

    Starts from the target defconfig plus `board/<board>/kernel.config`. The build
    directory lives in the cache (incremental) and so does ccache. `initramfs_dir` (with
    initramfs.cpio) is mounted at /initramfs for CONFIG_INITRAMFS_SOURCE.
    """
    from r36os.container import Container, ensure_cross

    arch, cross, defconfig, image = KERNEL_TARGETS[board]
    tree = source_tree()
    build = ensure_dir(cache_dir() / "kbuild" / f"{board}-{patches_digest()}")
    ccache = ensure_dir(cache_dir() / "ccache" / f"kernel-{board}")
    ensure_dir(out)
    volumes = {tree: "/linux", build: "/build", out: "/out", ccache: "/cache/ccache",
               REPO_ROOT / "board" / board: "/board"}
    if initramfs_dir is not None:
        volumes[initramfs_dir] = "/initramfs"
    Container(
        image=ensure_cross(),
        volumes=volumes,
    ).sh(_KERNEL_SCRIPT.format(arch=arch, cross=cross, defconfig=defconfig, image=image,
                               own_files="|".join(OWN_DRIVER_FILES)))
    return out / image


def build_dtbs(board: str, arch: str, vendor: str, out: Path) -> None:
    """Compile `board/<board>/dts/*.dts` against the patched tree and validate the DTBs.

    Fails if dtc warns about anything beyond the kernel exceptions or if dt-validate
    reports anything.
    """
    from r36os.container import Container, ensure_cross

    tree = source_tree()
    shutil.rmtree(out, ignore_errors=True)
    ensure_dir(out)
    Container(
        image=ensure_cross(),
        volumes={tree: "/linux", REPO_ROOT / "board" / board / "dts": "/dts", out: "/out"},
    ).sh(_DTBS_SCRIPT.format(arch=arch, vendor=vendor, dtc_flags=_DTC_FLAGS))
