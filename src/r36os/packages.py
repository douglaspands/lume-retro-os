"""Stage 2: local Alpine packages (abuild) and the local repository `out/repo/<arch>`."""

from __future__ import annotations

import os
from pathlib import Path

from r36os import jobs
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir, out_dir
from r36os.targets import Target

KEY_NAME = "r36os"
REPO_NAME = "r36os"  # abuild writes to $REPODEST/<parent dir name>/<arch>
NO_CCACHE_ENV = "R36OS_CCACHE"  # "0": compile everything (timing and distcc proofs)


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


def _container(target: Target, aports: Path, distcc: bool = False) -> Container:
    cache = cache_dir()
    ensure_dir(keys_dir())
    ensure_dir(cache / "distfiles")
    # distcc (build-speed D7): its own ccache until the P-36 proof shows equal objects
    ccache = cache / "ccache" / (target.alpine_arch + ("-distcc" if distcc else ""))
    ensure_dir(ccache)
    ensure_dir(out_dir() / "repo")
    env = {"REPODEST": "/repodest", "CCACHE_DIR": "/cache/ccache", "USE_CCACHE": "1",
           "JOBS": str(jobs.jobs()), "MAKEFLAGS": f"-j{jobs.jobs()}"}
    if os.environ.get(NO_CCACHE_ENV) == "0":
        env["CCACHE_DISABLE"] = "1"  # ccache still runs CCACHE_PREFIX (distcc)
    if distcc:
        from r36os import distcc as dcc
        env.update(dcc.client_env(target.alpine_arch, jobs.jobs()))
    return Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes={
            aports: f"/aports/{REPO_NAME}",
            out_dir() / "repo": f"/repodest/{REPO_NAME}",
            keys_dir(): "/root/.abuild",
            cache / "distfiles": "/cache/distfiles",
            ccache: "/cache/ccache",
        },
        # USE_CCACHE=1: without it abuild does not put /usr/lib/ccache/bin in PATH, and
        # under emulation (ARM) each rebuild would take hours
        env=env,
    )


_SETUP_KEY = f"""
if [ ! -f /root/.abuild/{KEY_NAME}.rsa ]; then
  openssl genrsa -out /root/.abuild/{KEY_NAME}.rsa 4096
  openssl rsa -in /root/.abuild/{KEY_NAME}.rsa -pubout -out /root/.abuild/{KEY_NAME}.rsa.pub
fi
echo 'PACKAGER_PRIVKEY=/root/.abuild/{KEY_NAME}.rsa' > /root/.abuild/abuild.conf
echo "export JOBS=$JOBS MAKEFLAGS=-j$JOBS" >> /root/.abuild/abuild.conf
cp /root/.abuild/{KEY_NAME}.rsa.pub /etc/apk/keys/
apk update -q
"""


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
    # R36OS_DISTCC (build-speed D7, P-36): the chosen packages compile through distcc
    from r36os import distcc as dcc
    chosen = set() if checksum else dcc.selected()
    for through_distcc, group in dcc.groups(names, target.alpine_arch, chosen):
        # abuild -r installs the dependencies; at the end it updates and signs the APKINDEX.
        script = _SETUP_KEY + ("apk add -q distcc\n" if through_distcc else "") + "".join(
            f"(cd /aports/{REPO_NAME}/{n} && {step})\n" for n in group
        )
        if through_distcc:
            with dcc.distccd(target.alpine_arch):
                _container(target, aports, distcc=True).sh(script)
        else:
            _container(target, aports).sh(script)


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
