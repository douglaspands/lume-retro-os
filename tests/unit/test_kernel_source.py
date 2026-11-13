"""Kernel source tree (kernel.source_tree): the patches really end up in the tree."""

import io
import shutil
import subprocess
import tarfile

import pytest

from r36os import kernel

GIT = shutil.which("git")


@pytest.mark.skipif(GIT is None, reason="no git")
def test_patches_apply_with_the_cache_inside_a_git_repository(tmp_path, monkeypatch):
    # Since the cache moved into the project (.cache/), `git apply` ran from a subdirectory
    # of the project repository and silently skipped every file: the tree was unpatched.
    repo = tmp_path / "project"
    cache = repo / ".cache"
    cache.mkdir(parents=True)
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)

    tar = tmp_path / "linux.tar.xz"
    with tarfile.open(tar, "w:xz") as t:
        data = b"old\n"
        info = tarfile.TarInfo(f"linux-{kernel.KERNEL_VERSION}/drivers/a.c")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "0001-a.patch").write_text(
        "--- a/drivers/a.c\n+++ b/drivers/a.c\n@@ -1 +1 @@\n-old\n+new\n")

    monkeypatch.setattr(kernel, "tarball", lambda: tar)
    monkeypatch.setattr(kernel, "PATCHES_DIR", patches)
    monkeypatch.setattr(kernel, "cache_dir", lambda: cache)
    tree = kernel.source_tree()
    assert (tree / "drivers/a.c").read_text() == "new\n"
