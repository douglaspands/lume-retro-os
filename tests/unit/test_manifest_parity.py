"""Task 11.2: the vm and ga36 images of a build carry the same userland.

Reads the latest archived images (out/images/<target>/latest/manifest.txt); skipped when
either is missing. Only the hardware layer may differ: the kernel and the packages of
board/<target>/hw-packages.txt (with their dependencies), and Mesa, which on the VM is
the local virgl build (aports/mesa, x86_64 only) instead of Alpine's.
"""

import json
import re

import pytest

from r36os.paths import REPO_ROOT, out_dir

TARGETS = ("vm", "ga36")
# the VM's Mesa is the local build with virgl (aports/mesa, arch x86_64)
HW_VARIANTS = re.compile(r"^mesa(-.*)?$")


def _manifest(target: str) -> dict[str, str]:
    path = out_dir() / "images" / target / "latest" / "manifest.txt"
    if not path.exists():
        pytest.skip(f"no {target} image built ({path})")
    pkgs = {}
    for line in path.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        name, version = line.split()
        pkgs[name] = version
    return pkgs


def _listed(path) -> list[str]:
    return [line.split("#", 1)[0].strip() for line in path.read_text().splitlines()
            if line.split("#", 1)[0].strip()]


def test_mesa_variant_is_only_on_the_vm():
    apkbuild = (REPO_ROOT / "aports/mesa/APKBUILD").read_text()
    assert re.search(r'^arch="x86_64"$', apkbuild, re.M)


def test_userland_packages_match_in_name_and_version():
    manifests = {t: _manifest(t) for t in TARGETS}
    for name in _listed(REPO_ROOT / "rootfs/packages.txt"):
        versions = {t: m.get(name) for t, m in manifests.items()}
        assert all(versions.values()), f"{name} missing: {versions}"
        if not HW_VARIANTS.match(name):
            assert len(set(versions.values())) == 1, f"{name} differs: {versions}"


def test_every_catalog_core_is_in_both_images():
    catalog = json.loads((REPO_ROOT / "rootfs/overlay/usr/share/r36os/systems.json").read_text())
    used = set()
    for system in catalog["systems"]:
        used |= {system["core"], *system["core_by_arch"].values(), *system["alt_cores"]}
    packages = {catalog["cores"][core]["package"] for core in used}
    for target in TARGETS:
        manifest = _manifest(target)
        missing = sorted(p for p in packages if p not in manifest)
        assert not missing, f"{target} lacks {missing}"


def test_hardware_packages_are_in_their_own_image_only():
    manifests = {t: _manifest(t) for t in TARGETS}
    for target in TARGETS:
        for name in _listed(REPO_ROOT / f"board/{target}/hw-packages.txt"):
            assert name in manifests[target], f"{name} not in the {target} image"
            others = [t for t in TARGETS if t != target]
            assert not any(name in manifests[o] for o in others), f"{name} leaked out of {target}"
