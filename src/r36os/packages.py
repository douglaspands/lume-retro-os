"""Stage 2: local Alpine packages (abuild) and the local repository `out/repo/<arch>`."""

from __future__ import annotations

import gzip
import shutil
import tarfile
from pathlib import Path

from r36os import jobs, manifests
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir, out_dir
from r36os.targets import Target

KEY_NAME = "r36os"
REPO_NAME = "r36os"  # abuild writes to $REPODEST/<parent dir name>/<arch>


def aport_arches(apkbuild: Path) -> list[str]:
    """The arch= value of the APKBUILD (e.g. ['all', '!armv7'])."""
    for line in apkbuild.read_text().splitlines():
        if line.startswith("arch="):
            return line.split("=", 1)[1].strip().strip('"').split()
    return ["all"]


def builds_for(apkbuild: Path, arch: str) -> bool:
    arches = aport_arches(apkbuild)
    if f"!{arch}" in arches:
        return False
    return any(a in ("all", "noarch", arch) for a in arches)


def local_aports(target: Target | None = None) -> list[str]:
    """Packages in aports/ (each subdirectory with an APKBUILD), in a stable order.

    With `target`, only those allowed by the APKBUILD arch= (the local mesa is x86_64 only).
    """
    found = sorted((REPO_ROOT / "aports").glob("*/APKBUILD"))
    return [p.parent.name for p in found
            if target is None or builds_for(p, target.alpine_arch)]


def keys_dir() -> Path:
    return cache_dir() / "abuild"


def repo_dir(target: Target) -> Path:
    return out_dir() / "repo" / target.alpine_arch


def public_key() -> Path:
    return keys_dir() / f"{KEY_NAME}.rsa.pub"


def _container(target: Target, aports: Path, repodest: Path | None = None) -> Container:
    cache = cache_dir()
    repodest = repodest or out_dir() / "repo"
    ensure_dir(keys_dir())
    ensure_dir(cache / "distfiles")
    ensure_dir(cache / "ccache" / target.alpine_arch)
    ensure_dir(repodest)
    return Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes={
            aports: f"/aports/{REPO_NAME}",
            repodest: f"/repodest/{REPO_NAME}",
            keys_dir(): "/root/.abuild",
            cache / "distfiles": "/cache/distfiles",
            cache / "ccache" / target.alpine_arch: "/cache/ccache",
        },
        # USE_CCACHE=1: without it abuild does not put /usr/lib/ccache/bin in PATH, and
        # under emulation (ARM) each rebuild would take hours
        env={"REPODEST": "/repodest", "CCACHE_DIR": "/cache/ccache", "USE_CCACHE": "1",
             "JOBS": str(jobs.jobs()), "MAKEFLAGS": f"-j{jobs.jobs()}"},
    )


_KEY = f"""
if [ ! -f /root/.abuild/{KEY_NAME}.rsa ]; then
  openssl genrsa -out /root/.abuild/{KEY_NAME}.rsa 4096
  openssl rsa -in /root/.abuild/{KEY_NAME}.rsa -pubout -out /root/.abuild/{KEY_NAME}.rsa.pub
fi
echo 'PACKAGER_PRIVKEY=/root/.abuild/{KEY_NAME}.rsa' > /root/.abuild/abuild.conf
echo "export JOBS=$JOBS MAKEFLAGS=-j$JOBS" >> /root/.abuild/abuild.conf
cp /root/.abuild/{KEY_NAME}.rsa.pub /etc/apk/keys/
"""
_SETUP_KEY = _KEY + "apk update -q\n"


def ensure_key(target: Target) -> Path:
    """Generate the abuild signing key in the cache (once, shared by all arches)."""
    _container(target, REPO_ROOT / "aports").sh(_SETUP_KEY)
    return public_key()


def build_packages(
    target: Target, names: list[str], aports: Path | None = None, checksum: bool = False
) -> None:
    """Build the `aports/<name>` packages for the target architecture.

    With `checksum=True`, only update the APKBUILD sha512sums (abuild checksum).
    """
    aports = aports or REPO_ROOT / "aports"
    if "lume-launcher" in names and not checksum and aports == REPO_ROOT / "aports":
        # the Rust workspace and its vendored crates (abuild only sees aports/)
        from r36os import lume
        lume.stage()
    step = "abuild -F checksum" if checksum else "abuild -F -r -P /repodest"
    # abuild -r installs the dependencies; at the end it updates and signs the APKINDEX.
    script = _SETUP_KEY + "".join(
        f"(cd /aports/{REPO_NAME}/{n} && {step})\n" for n in names
    )
    _container(target, aports).sh(script)


# --- noarch fragments (build-speed D2) -------------------------------------------------
#
# A noarch fragment is built once, by abuild in the x86_64 builder (no qemu), and the SAME
# .apk file is copied into out/repo/<arch>/ for every arch. abuild writes `arch = noarch` in
# .PKGINFO; each APKINDEX is rebuilt with `apk index --rewrite-arch <arch>` (as abuild does
# for its own repo), so the index says `A:<arch>`. apk fetches a package from
# <repo>/<index arch>/, so an index saying `A:noarch` would send it to <repo>/noarch/ and
# fail with "package mentioned in index not found". The .apk signature (.SIGN.RSA) covers
# the control segment and does not depend on the arch, so one signed file serves all arches.

NOARCH_BUILD_TARGET = Target("noarch", "x86_64", "linux/amd64", "noarch fragments (PC)")
REPO_ARCHES = ("armv7", "aarch64", "x86_64")
ELF_MAGIC = b"\x7fELF"


class NoarchError(RuntimeError):
    """A noarch fragment that cannot be published (ELF inside, wrong arch, collision)."""


def arch_repo_dir(arch: str) -> Path:
    return out_dir() / "repo" / arch


def noarch_staging_dir() -> Path:
    """Where abuild drops the noarch build (<staging>/x86_64/*.apk) before the checks."""
    return out_dir() / "noarch"


def is_noarch_aport(apkbuild: Path) -> bool:
    return aport_arches(apkbuild) == ["noarch"]


def _is_elf(head: bytes) -> bool:
    return head[:4] == ELF_MAGIC


def elf_files_in_dir(root: Path) -> list[str]:
    """Regular files under `root` that start with the ELF magic (relative paths, sorted)."""
    found = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            with p.open("rb") as f:
                if _is_elf(f.read(4)):
                    found.append(p.relative_to(root).as_posix())
    return found


def _apk_stream(apk: Path):
    """The tar members of an .apk (v2: signature, control and data gzip streams in a row,
    the first two without end-of-archive blocks, so they read as one tar)."""
    with gzip.open(apk, "rb") as gz, tarfile.open(fileobj=gz, mode="r|") as tf:
        for m in tf:
            head = b""
            if m.isreg():
                f = tf.extractfile(m)
                head = f.read(4) if f else b""
            yield m, head


def read_apk_pkginfo(apk: Path) -> list[tuple[str, str]]:
    """(key, value) pairs of the .PKGINFO inside an .apk."""
    with gzip.open(apk, "rb") as gz, tarfile.open(fileobj=gz, mode="r|") as tf:
        for m in tf:
            if m.name == ".PKGINFO":
                f = tf.extractfile(m)
                return manifests.parse_pkginfo(f.read().decode() if f else "")
    raise NoarchError(f"{apk.name}: no .PKGINFO")


def elf_files_in_apk(apk: Path) -> list[str]:
    """Data files of an .apk that are ELF (control files, which start with '.', skipped)."""
    return sorted(m.name for m, head in _apk_stream(apk)
                  if not m.name.startswith(".") and _is_elf(head))


def check_noarch_apk(apk: Path, fragment: str) -> None:
    """Fail unless `apk` is a noarch package without ELF files, naming fragment and file."""
    arch = dict(read_apk_pkginfo(apk)).get("arch")
    if arch != "noarch":
        raise NoarchError(f"fragment {fragment}: {apk.name} has arch={arch}, not noarch")
    elf = elf_files_in_apk(apk)
    if elf:
        raise NoarchError(f"noarch fragment {fragment} contains ELF file(s): "
                          + ", ".join(elf) + f" (in {apk.name})")


def check_noarch_aport(aport_dir: Path) -> None:
    """Before the build: the aport must say arch="noarch" and ship no ELF file."""
    fragment = aport_dir.name
    if not is_noarch_aport(aport_dir / "APKBUILD"):
        raise NoarchError(f"fragment {fragment}: APKBUILD arch is not \"noarch\"")
    elf = elf_files_in_dir(aport_dir)
    if elf:
        raise NoarchError(f"noarch fragment {fragment} contains ELF file(s): "
                          + ", ".join(elf))


def build_noarch(names: list[str], aports: Path | None = None) -> list[Path]:
    """Build the noarch `aports/<name>` fragments in the x86_64 builder and check them.

    Returns the built .apk files (in the staging dir); nothing is published yet. Fails
    with NoarchError if a fragment is not noarch or contains an ELF file.
    """
    aports = aports or REPO_ROOT / "aports"
    for n in names:
        check_noarch_aport(aports / n)
    staging = noarch_staging_dir()
    shutil.rmtree(staging / NOARCH_BUILD_TARGET.alpine_arch, ignore_errors=True)
    c = _container(NOARCH_BUILD_TARGET, aports, repodest=staging)
    c.volumes[ensure_dir(out_dir() / "repo")] = "/localrepo"
    # dependencies may be other local fragments, already in out/repo/x86_64
    script = _KEY + (
        "if [ -f /localrepo/x86_64/APKINDEX.tar.gz ]; then\n"
        "  echo /localrepo >> /etc/apk/repositories\nfi\n"
        "apk update -q\n"
    ) + "".join(f"(cd /aports/{REPO_NAME}/{n} && abuild -F -r -P /repodest)\n" for n in names)
    c.sh(script)
    built = sorted((staging / NOARCH_BUILD_TARGET.alpine_arch).glob("*.apk"))
    by_origin: dict[str, list[Path]] = {}
    for apk in built:
        origin = dict(read_apk_pkginfo(apk)).get("origin", "")
        by_origin.setdefault(origin, []).append(apk)
    for n in names:
        if n not in by_origin:
            raise NoarchError(f"fragment {n}: abuild produced no .apk")
        for apk in by_origin[n]:
            check_noarch_apk(apk, n)
    return [apk for n in names for apk in by_origin[n]]


def _copy_identical(apk: Path, dest_dir: Path) -> Path:
    """Copy `apk` into `dest_dir`; refuse a different file already under the same name."""
    dest = ensure_dir(dest_dir) / apk.name
    want = manifests.sha256_file(apk)
    if dest.exists():
        if manifests.sha256_file(dest) != want:
            raise NoarchError(f"{dest}: already published with different content")
        return dest
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(apk, tmp)
    if manifests.sha256_file(tmp) != want:
        tmp.unlink()
        raise NoarchError(f"{dest}: copy does not match {apk}")
    tmp.replace(dest)
    return dest


_REINDEX = f"""
for a in $ARCHES; do
  cd /repodest/{REPO_NAME}/$a
  old=
  if [ -f APKINDEX.tar.gz ]; then old="--index APKINDEX.tar.gz"; fi
  apk index --no-warnings --quiet $old --output APKINDEX.tar.gz.new \\
    --description {REPO_NAME} --rewrite-arch $a *.apk
  abuild-sign -q APKINDEX.tar.gz.new
  chmod 644 APKINDEX.tar.gz.new
  mv APKINDEX.tar.gz.new APKINDEX.tar.gz
done
"""


def reindex(arches: tuple[str, ...] | list[str] = REPO_ARCHES) -> None:
    """Rebuild and sign out/repo/<arch>/APKINDEX.tar.gz (A:<arch> for every package).

    Runs in the x86_64 builder: `apk index` only reads the files, no emulation needed.
    Uses the ARCH:<arch> resource: no `r36os pkg` of that arch may run at the same time.
    """
    c = _container(NOARCH_BUILD_TARGET, REPO_ROOT / "aports")
    c.env["ARCHES"] = " ".join(arches)
    c.sh(_KEY + _REINDEX)


def publish_noarch(apks: list[Path], arches: tuple[str, ...] = REPO_ARCHES) -> list[Path]:
    """Publish the same .apk files in out/repo/<arch>/ for every arch and reindex them."""
    for apk in apks:
        check_noarch_apk(apk, dict(read_apk_pkginfo(apk)).get("origin", apk.name))
    published = [_copy_identical(apk, arch_repo_dir(a)) for a in arches for apk in apks]
    reindex(arches)
    return published


def install_test(target: Target, name: str, aports: Path) -> str:
    """Install `name` in a clean container from the local repository; return `apk info`."""
    c = _container(target, aports)
    out = c.sh(
        _SETUP_KEY
        + f"apk add --repository /repodest/{REPO_NAME} {name} >/dev/null\n"
        + f"apk info -e {name}\n",
        capture_output=True,
        text=True,
    )
    return out.stdout
