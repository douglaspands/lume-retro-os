"""kernel-modules-image task 1.1: the console modules squashfs from the kernel modules.tar.

Requires podman (the x86_64 builder runs mksquashfs).
"""

import hashlib
import io
import shutil
import tarfile

import pytest

from lume_tool import rootfs
from lume_tool.container import Container, ensure_builder
from lume_tool.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="no podman")
RELEASE = "6.18.62-test"


def _modules_tar(path, mtime, uid):
    """A modules.tar shaped like the kernel one (lib/modules/<release>/...)."""
    with tarfile.open(path, "w") as tar:
        for d in ("lib", "lib/modules", f"lib/modules/{RELEASE}",
                  f"lib/modules/{RELEASE}/kernel"):
            info = tarfile.TarInfo(d)
            info.type, info.mode, info.mtime, info.uid = tarfile.DIRTYPE, 0o755, mtime, uid
            tar.addfile(info)
        for name, data in ((f"lib/modules/{RELEASE}/kernel/zram.ko", b"\x7fELF zram" * 100),
                           (f"lib/modules/{RELEASE}/modules.dep", b"kernel/zram.ko:\n")):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.uid = len(data), mtime, uid
            tar.addfile(info, io.BytesIO(data))


def test_modules_image_is_reproducible_with_one_release_folder(tmp_path):
    # two modules.tar with the same modules but other install times and owner: same image
    shas = []
    for i, (mtime, uid) in enumerate(((1_700_000_000, 1000), (1_800_000_000, 0))):
        src = tmp_path / f"k{i}" / "modules.tar"
        src.parent.mkdir()
        _modules_tar(src, mtime, uid)
        # next to the tar, as in the build (out/<console>/kernel/)
        dest = rootfs.make_modules_image(src, src.parent / "modules")
        shas.append(hashlib.sha256(dest.read_bytes()).hexdigest())
    assert shas[0] == shas[1]
    # and in another folder
    other = rootfs.make_modules_image(tmp_path / "k0" / "modules.tar", tmp_path / "o" / "modules")
    assert hashlib.sha256(other.read_bytes()).hexdigest() == shas[0]
    listing = Container(image=ensure_builder(get_target("vm")),
                        volumes={tmp_path / "k0": "/out"}).sh(
        "unsquashfs -lln /out/modules", capture_output=True, text=True).stdout
    paths = [line.split()[-1] for line in listing.splitlines() if "squashfs-root" in line]
    top = {p.split("/")[1] for p in paths if p.count("/") >= 1}
    assert top == {RELEASE}                                     # lib/modules/ taken off
    assert f"squashfs-root/{RELEASE}/modules.dep" in paths
    owners = {line.split()[1] for line in listing.splitlines() if "squashfs-root" in line}
    assert owners == {"0/0"}
