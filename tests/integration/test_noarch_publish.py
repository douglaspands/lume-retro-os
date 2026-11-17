"""build-speed 4.1: a noarch fragment built once on x86_64 is published as the same .apk
in every arch repository and `apk add --root` of each arch installs it, with the local
key and without --allow-untrusted.

Requires podman and qemu-user (binfmt) for the armv7 and aarch64 builders.
"""

import shutil

import pytest

from r36os import packages
from r36os.container import Container, ensure_builder
from r36os.manifests import sha256_file
from r36os.paths import REPO_ROOT
from r36os.targets import TARGETS

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="no podman")

TARGET_OF_ARCH = {t.alpine_arch: t for t in TARGETS.values()}


def _install_in_root(arch: str, name: str) -> str:
    """`apk add --root` from the local repository only, trusting only the local key."""
    t = TARGET_OF_ARCH[arch]
    c = Container(
        image=ensure_builder(t), platform=t.oci_platform,
        volumes={packages.out_dir() / "repo": "/repo/r36os",
                 packages.keys_dir(): "/keys"},
    )
    out = c.sh(
        "mkdir -p /t/etc/apk/keys\n"
        f"cp /keys/{packages.KEY_NAME}.rsa.pub /t/etc/apk/keys/\n"
        f"apk add --root /t --initdb --no-network --arch {arch} "
        f"--repositories-file /dev/null --repository /repo/r36os {name}\n"
        f"grep -A3 '^P:{name}$' /t/lib/apk/db/installed\n",
        capture_output=True, text=True,
    )
    return out.stdout


def test_noarch_fragment_is_the_same_file_in_every_arch(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))  # keep the real out/repo clean
    apks = packages.build_noarch(["r36os-hello"], aports=REPO_ROOT / "tests/fixtures/aports")
    assert [a.name for a in apks] == ["r36os-hello-1.0-r0.apk"]
    assert dict(packages.read_apk_pkginfo(apks[0]))["arch"] == "noarch"

    published = packages.publish_noarch(apks)
    assert {sha256_file(p) for p in published} == {sha256_file(apks[0])}

    for arch in packages.REPO_ARCHES:
        db = _install_in_root(arch, "r36os-hello")
        assert "V:1.0-r0" in db
        assert f"A:{arch}" in db  # the index arch, as on the consoles
