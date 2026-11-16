"""Mainline LTS kernel source for the consoles (D3): pinned download, patches and DTBs.

The official tarball is downloaded once into the cache and checked against its sha256.
The tree used by the build is an extracted copy with the patches from `kernel/patches/`
applied in order; when the patches change, only the files whose content differs are
rewritten (git, see source_tree).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
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


# Commit of the patch series checked out in the work tree (build-speed D5)
APPLIED_REF = "refs/r36os/applied"
UPSTREAM_TAG = "upstream"
# Fixed identity and date: the same series always gives the same commit
_GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "r36os", "GIT_AUTHOR_EMAIL": "r36os@localhost",
    "GIT_COMMITTER_NAME": "r36os", "GIT_COMMITTER_EMAIL": "r36os@localhost",
    "GIT_AUTHOR_DATE": "2000-01-01T00:00:00+0000",
    "GIT_COMMITTER_DATE": "2000-01-01T00:00:00+0000",
}


class PatchError(RuntimeError):
    """A kernel patch does not apply on the pristine tree plus the patches before it."""


def _git_env(base: Path, git_dir: Path, tree: Path, **extra: str) -> dict[str, str]:
    # The cache lives inside the project repository (.cache/): git must never pick up the
    # project repository (from a subdirectory, `git apply` silently skips every path outside
    # it). The ceiling plus an explicit GIT_DIR/GIT_WORK_TREE rule out any discovery, and
    # the user's and the system's configuration (signing, hooks, autocrlf) are left out.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(_GIT_IDENTITY, GIT_CEILING_DIRECTORIES=str(base), GIT_DIR=str(git_dir),
               GIT_WORK_TREE=str(tree), GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    env.update(extra)
    return env


def _git(env: dict[str, str], *args: str, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "gc.auto=0", *args],
                       cwd=env["GIT_WORK_TREE"], env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r


def _import_upstream(base: Path, git_dir: Path, tree: Path) -> None:
    """Extract the pristine tarball into `tree` and commit it in `git_dir` (tag upstream).

    Done in a scratch folder and moved into place at the end, so a tree whose repository
    has the `upstream` tag is always complete.
    """
    for p in (tree, git_dir):
        shutil.rmtree(p, ignore_errors=True)
    tmp = base / f"linux-{KERNEL_VERSION}.extract"
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"extracting linux-{KERNEL_VERSION}", flush=True)
    with tarfile.open(tarball()) as t:
        t.extractall(tmp, filter="data")
    work, gd = tmp / f"linux-{KERNEL_VERSION}", tmp / "git"
    env = _git_env(base, gd, work)
    print(f"importing linux-{KERNEL_VERSION} into git (once)", flush=True)
    _git(env, "init", "-q")
    # -f: the tarball holds files that the kernel's own .gitignore files match
    _git(env, "add", "-A", "-f", ".")
    tree_id = _git(env, "write-tree").stdout.strip()
    commit = _git(env, "commit-tree", tree_id, "-m", f"linux-{KERNEL_VERSION}").stdout.strip()
    _git(env, "tag", UPSTREAM_TAG, commit)
    _git(env, "update-ref", APPLIED_REF, commit)
    _git(env, "update-ref", "--no-deref", "HEAD", commit)
    gd.rename(git_dir)
    work.rename(tree)
    tmp.rmdir()


def _series_commit(env: dict[str, str], git_dir: Path) -> str:
    """Commit of upstream plus every patch, built in a scratch index (work tree untouched)."""
    index = git_dir / "r36os-series.index"
    index.unlink(missing_ok=True)
    ienv = dict(env, GIT_INDEX_FILE=str(index))
    try:
        _git(ienv, "read-tree", UPSTREAM_TAG)
        for p in patches():
            print(f"applying {p.name}", flush=True)
            r = _git(ienv, "apply", "--cached", "--whitespace=nowarn", str(p), check=False)
            if r.returncode != 0:
                raise PatchError(f"kernel patch {p.name} does not apply: {r.stderr.strip()}")
        tree_id = _git(ienv, "write-tree").stdout.strip()
        return _git(ienv, "commit-tree", tree_id, "-p", UPSTREAM_TAG,
                    "-m", f"r36os patches {patches_digest()}").stdout.strip()
    finally:
        index.unlink(missing_ok=True)


def _work_tree_matches(env: dict[str, str], commit: str) -> bool:
    """Index and work tree equal to `commit` (untracked files do not count)."""
    _git(env, "update-index", "-q", "--refresh", check=False)
    return (_git(env, "diff-index", "--quiet", "--cached", commit, "--", check=False)
            .returncode == 0
            and _git(env, "diff-index", "--quiet", commit, "--", check=False).returncode == 0)


def source_tree() -> Path:
    """Kernel tree `<cache>/src/linux-<version>/` with the patches applied (build-speed D5).

    The pristine tarball is committed once in a repository of its own (tag `upstream`),
    kept beside the tree in `linux-<version>.git` so that nothing inside the tree mounted
    in the build container is a git repository (with CONFIG_LOCALVERSION_AUTO the kernel
    release would get a `-g<hash>` suffix). Each run builds the series commit outside the
    work tree and moves the tree to it with `git read-tree -m -u`: only the files whose
    content differs are rewritten, so only they get a new mtime and make recompiles only
    what depends on them. A bad patch raises PatchError naming it and leaves the tree as
    it was.
    """
    base = ensure_dir(cache_dir() / "src")
    tree = base / f"linux-{KERNEL_VERSION}"
    git_dir = base / f"linux-{KERNEL_VERSION}.git"
    env = _git_env(base, git_dir, tree)
    if not (tree.is_dir() and git_dir.is_dir()
            and _git(env, "rev-parse", "-q", "--verify", f"{UPSTREAM_TAG}^{{commit}}",
                     check=False).returncode == 0):
        _import_upstream(base, git_dir, tree)

    new = _series_commit(env, git_dir)
    r = _git(env, "rev-parse", "-q", "--verify", f"{APPLIED_REF}^{{commit}}", check=False)
    old = r.stdout.strip() if r.returncode == 0 else ""
    if not old or not _work_tree_matches(env, old):
        # aborted run or hand edits: back to the recorded series, rewriting only what differs
        target = old or UPSTREAM_TAG
        print(f"kernel tree does not match {target}: resetting it", flush=True)
        _git(env, "reset", "-q", "--hard", target)
        old = _git(env, "rev-parse", f"{target}^{{commit}}").stdout.strip()
    if old == new:
        return tree
    # Recorded first: if read-tree is interrupted, the next run sees a tree that does not
    # match the new commit and resets it there.
    _git(env, "update-ref", APPLIED_REF, new)
    _git(env, "update-ref", "--no-deref", "HEAD", new)
    if _git(env, "read-tree", "-m", "-u", old, new, check=False).returncode != 0:
        # e.g. an untracked file in the way of a file the new series adds
        _git(env, "reset", "-q", "--hard", new)
    return tree


# Flags from the kernel scripts/Makefile.dtbs (W=0), plus -@ for overlays
_DTC_FLAGS = ("-Wno-unit_address_vs_reg -Wno-avoid_unnecessary_addr_size -Wno-alias_paths "
              "-Wno-graph_child_address -Wno-interrupt_map -Wno-simple_bus_reg "
              "-Wno-unique_unit_address -Wunique_unit_address_if_enabled -@")

_DTBS_SCRIPT = """
set -eu
inc=/linux/scripts/dtc/include-prefixes
compile() {{  # <source folder> <output folder>
  for f in "$1"/*.dts; do
    [ -e "$f" ] || continue
    n=$(basename "$f" .dts)
    cpp -nostdinc -I "$1" -I /dts -I /linux/arch/{arch}/boot/dts/{vendor} -I $inc -undef \\
        -D__DTS__ -x assembler-with-cpp -o /tmp/$n.pp "$f"
    dtc -O dtb -b 0 {dtc_flags} -i "$1" -o "$2/$n.dtb" /tmp/$n.pp
  done
  echo "dtb: $(ls "$2" | wc -l) in $2"
}}
compile /dts /out
if [ -d /vendor ]; then mkdir -p /out/vendor; compile /vendor /out/vendor; fi
dt-mk-schema -j /linux/Documentation/devicetree/bindings > /tmp/schema.json
# one dt-validate for all (the schema loads once); any output is a failure
out=$(dt-validate -s /tmp/schema.json -m $(find /out -name '*.dtb' | sort) 2>&1) || true
if [ -n "$out" ]; then echo "$out"; exit 1; fi
echo "dt-validate: no errors"
"""


_KERNEL_SCRIPT = """
set -eu
export ARCH={arch} CROSS_COMPILE="ccache {cross}"
# the same inputs give the same image (r36os push skips it): no build date, counter, user
# or host of this machine in the kernel; the date is the last commit of the kernel inputs
export KBUILD_BUILD_TIMESTAMP="{stamp}" KBUILD_BUILD_VERSION=1
export KBUILD_BUILD_USER=lume KBUILD_BUILD_HOST=lume
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
# and every "# CONFIG_X is not set" of the fragment must stay off (a select turns it on)
sed -n 's/^# \\(CONFIG_[A-Za-z0-9_]*\\) is not set$/\\1/p' /board/kernel.config | while read -r off; do
  if grep -q "^$off=" $B/.config; then echo "kernel.config: $off must stay off"; exit 1; fi
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

# Our own drivers and the drivers our patches change: any warning in them fails the build
# (9.1, 9.2; the R36S panel variant is in panel-sitronix-st7703.c, patch 0010; the GA36
# USB gadget Rx fix is in musb_gadget.c, patch 0028)
OWN_DRIVER_FILES = ("panel-ga36mb-jd9366.c", "ga36mb-gamepad.c", "panel-sitronix-st7703.c",
                    "phy-rockchip-inno-dsidphy.c", "dw-mipi-dsi.c", "dw-mipi-dsi-rockchip.c",
                    "musb_gadget.c", "panel-generic-dsi.c")

# target -> (ARCH, cross prefix, starting defconfig, image)
KERNEL_TARGETS = {
    "ga36": ("arm", "arm-linux-gnueabihf-", "sunxi_defconfig", "zImage"),
    "r36s": ("arm64", "aarch64-linux-gnu-", "defconfig", "Image"),
}


def kernel_inputs(board: str) -> list[Path]:
    """What decides a console kernel besides the pinned source: our patches, the board
    fragment and this module (the build script)."""
    return [PATCHES_DIR, REPO_ROOT / "board" / board / "kernel.config", Path(__file__)]


def build_stamp(board: str) -> str:
    """KBUILD_BUILD_TIMESTAMP of a console kernel: the date of the last commit that touched
    its inputs, so it only moves when they do (the kernel also turns it into the mtime of
    the initramfs files with `date -d`, so it must be a date). Without git history, the
    epoch."""
    import subprocess

    rel = [str(p.relative_to(REPO_ROOT)) for p in kernel_inputs(board)]
    r = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%cd",
                        "--date=format-local:%Y-%m-%d %H:%M:%S UTC", "--", *rel],
                       capture_output=True, text=True, env={**os.environ, "TZ": "UTC"})
    return r.stdout.strip() or "1970-01-01 00:00:00 UTC"


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
                               own_files="|".join(OWN_DRIVER_FILES),
                               stamp=build_stamp(board)))
    return out / image


def build_dtbs(board: str, arch: str, vendor: str, out: Path) -> None:
    """Compile `board/<board>/dts/*.dts` against the patched tree and validate the DTBs.

    The trees converted from vendor DTBs (`board/<board>/dts-vendor/`, boot-dtb-select
    D12) go to `out/vendor/`. Fails if dtc warns about anything beyond the kernel
    exceptions or if dt-validate reports anything.
    """
    from r36os.container import Container, ensure_cross

    tree = source_tree()
    shutil.rmtree(out, ignore_errors=True)
    ensure_dir(out)
    volumes = {tree: "/linux", REPO_ROOT / "board" / board / "dts": "/dts", out: "/out"}
    vendor_dts = REPO_ROOT / "board" / board / "dts-vendor"
    if vendor_dts.is_dir():
        volumes[vendor_dts] = "/vendor"
    Container(image=ensure_cross(), volumes=volumes).sh(
        _DTBS_SCRIPT.format(arch=arch, vendor=vendor, dtc_flags=_DTC_FLAGS))
