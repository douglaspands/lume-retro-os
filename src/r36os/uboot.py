"""Mainline U-Boot for the consoles (D5): pinned source, cross build and image placement.

U-Boot uses the board's own DTS (panel 1): the files from board/<target>/dts/ are copied
to dts/upstream/src/arm/allwinner/ of the build copy and compiled in OF_UPSTREAM mode
(board/<target>/u-boot.config). Console, card and PMIC are the device's, not those of
the starting defconfig board. No upstream file is edited.

The tarball comes from the GitHub mirror (github.com/u-boot/u-boot, fixed tag) and is
checked against the sha256 recorded here. U-Boot changes go in as patches (none yet).
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
from pathlib import Path

from r36os.paths import REPO_ROOT, cache_dir, ensure_dir

UBOOT_VERSION = "2025.10"
UBOOT_URL = f"https://github.com/u-boot/u-boot/archive/refs/tags/v{UBOOT_VERSION}.tar.gz"
# sha256 of the tarball downloaded on 2026-11-09 (the DENX server did not answer)
UBOOT_SHA256 = "5414ee86562abc5ed524c6dc5e092511ad281441020a88e7027de6e83fd16116"

# target -> (starting defconfig, cross prefix, board DT, binary, offset in bytes)
UBOOT_TARGETS: dict[str, tuple[str, str, str, str, int]] = {}

# GA36 with mainline U-Boot: it builds (board/ga36/u-boot.config) but showed no sign of life
# on the device, with no serial to debug. The GA36 uses the vendor bootloader (vendor.py);
# going back to the open U-Boot is pending task 12.2. To try it: UBOOT_TARGETS["ga36"] = GA36_MAINLINE.
GA36_MAINLINE = ("Sinlinx_SinA33_defconfig", "arm-linux-gnueabihf-",
                 "sun8i-a33-ga36-mb-v1.2-panel1", "u-boot-sunxi-with-spl.bin", 8192)


def tarball() -> Path:
    """The tarball in the cache, downloaded in a container (the host network may be blocked)."""
    from r36os.container import Container, ensure_builder
    from r36os.targets import TARGETS

    dest = ensure_dir(cache_dir() / "distfiles") / f"u-boot-{UBOOT_VERSION}.tar.gz"
    if not dest.exists():
        Container(image=ensure_builder(TARGETS["vm"]), volumes={dest.parent: "/d"}).sh(
            f"wget -q -O /d/{dest.name}.part {UBOOT_URL} && mv /d/{dest.name}.part /d/{dest.name}")
    got = hashlib.sha256(dest.read_bytes()).hexdigest()
    if got != UBOOT_SHA256:
        raise RuntimeError(f"{dest.name}: sha256 {got} != {UBOOT_SHA256}")
    return dest


def source_tree() -> Path:
    base = ensure_dir(cache_dir() / "src")
    tree = base / f"u-boot-{UBOOT_VERSION}"
    stamp = tree / ".r36os-ready"
    if stamp.exists():
        return tree
    shutil.rmtree(tree, ignore_errors=True)
    with tarfile.open(tarball()) as t:
        t.extractall(base, filter="data")
    stamp.write_text(UBOOT_SHA256 + "\n")
    return tree


_SCRIPT = """
set -eu
export ARCH=arm CROSS_COMPILE="ccache {cross}"
# system Python (setuptools, pyelftools): the dtschema venv comes first in PATH
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
B=/build
cd /uboot
make -s O=$B {defconfig}
scripts/kconfig/merge_config.sh -m -O $B $B/.config /board/u-boot.config >/dev/null
make -s O=$B olddefconfig
grep -E '^(CONFIG_|# CONFIG_)' /board/u-boot.config | while IFS= read -r want; do
  grep -qxF "$want" $B/.config || {{ echo "u-boot.config: $want did not end up in .config"; exit 1; }}
done
# board DTS (our own files, no upstream file is edited) next to the upstream DTS:
# OF_UPSTREAM compiles CONFIG_DEFAULT_DEVICE_TREE with sunxi-u-boot.dtsi (binman)
cp /board/dts/* dts/upstream/src/arm/allwinner/
make -s O=$B -j$(nproc)
cp $B/{binary} /out/{binary}
cp $B/u-boot.dtb /out/u-boot.dtb
cp $B/.config /out/u-boot.config
"""


def build_uboot(board: str, out: Path) -> Path:
    """Build the console U-Boot with the board DT; return the binary."""
    from r36os.container import Container, ensure_cross

    defconfig, cross, dtb, binary, _ = UBOOT_TARGETS[board]
    tree = source_tree()
    build = ensure_dir(cache_dir() / "ubuild" / board)
    ccache = ensure_dir(cache_dir() / "ccache" / f"uboot-{board}")
    ensure_dir(out)
    Container(
        image=ensure_cross(),
        volumes={tree: "/uboot", build: "/build", out: "/out",
                 ccache: "/cache/ccache", REPO_ROOT / "board" / board: "/board"},
    ).sh(_SCRIPT.format(cross=cross, defconfig=defconfig, dtb=dtb, binary=binary))
    return out / binary


def image_raw_step(board: str, binary_in_container: str) -> str:
    """Image-stage command that writes U-Boot to the disk without touching sector 0."""
    *_, offset = UBOOT_TARGETS[board]
    return (f"dd if={binary_in_container} of=$W/disk.img bs=1024 seek={offset // 1024} "
            "conv=notrunc status=none")
