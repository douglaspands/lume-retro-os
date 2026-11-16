"""Kernel source tree (kernel.source_tree): the patches really end up in the tree, and a new
patch series rewrites only the files whose content changes (build-speed D5)."""

import io
import os
import shutil
import subprocess
import tarfile

import pytest

from r36os import kernel

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="no git")

OLD_TIME = 1_000_000_000


def _patch(path: str, old: str, new: str) -> str:
    return f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-{old}\n+{new}\n"


@pytest.fixture
def fake_kernel(tmp_path, monkeypatch):
    """A tiny tarball, a patch folder and a cache inside a project git repository."""
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    repo = tmp_path / "project"
    cache = repo / ".cache"
    cache.mkdir(parents=True)
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)

    tar = tmp_path / "linux.tar.xz"
    with tarfile.open(tar, "w:xz") as t:
        for name in ("a.c", "b.c", "c.c"):
            data = f"{name} old\n".encode()
            info = tarfile.TarInfo(f"linux-{kernel.KERNEL_VERSION}/drivers/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
        # a file the kernel's own .gitignore would hide must still be tracked
        for name, data in ((".gitignore", b"*.o\n"), ("drivers/keep.o", b"obj\n")):
            info = tarfile.TarInfo(f"linux-{kernel.KERNEL_VERSION}/{name}")
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "0001-a.patch").write_text(_patch("drivers/a.c", "a.c old", "a.c new"))
    (patches / "0002-b.patch").write_text(_patch("drivers/b.c", "b.c old", "b.c new"))

    monkeypatch.setattr(kernel, "tarball", lambda: tar)
    monkeypatch.setattr(kernel, "PATCHES_DIR", patches)
    monkeypatch.setattr(kernel, "cache_dir", lambda: cache)
    return patches


def _age(tree):
    for p in tree.rglob("*"):
        if p.is_file():
            os.utime(p, (OLD_TIME, OLD_TIME))


def _mtimes(tree):
    return {str(p.relative_to(tree)): p.stat().st_mtime_ns
            for p in tree.rglob("*") if p.is_file()}


def test_patches_apply_with_the_cache_inside_a_git_repository(fake_kernel):
    # Since the cache moved into the project (.cache/), `git apply` ran from a subdirectory
    # of the project repository and silently skipped every file: the tree was unpatched.
    tree = kernel.source_tree()
    assert tree.name == f"linux-{kernel.KERNEL_VERSION}"
    assert (tree / "drivers/a.c").read_text() == "a.c new\n"
    assert (tree / "drivers/b.c").read_text() == "b.c new\n"
    assert (tree / "drivers/c.c").read_text() == "c.c old\n"
    assert (tree / "drivers/keep.o").read_text() == "obj\n"
    # no repository inside the tree mounted in the build container
    assert not (tree / ".git").exists()


def test_same_series_touches_nothing(fake_kernel):
    tree = kernel.source_tree()
    _age(tree)
    before = _mtimes(tree)
    assert kernel.source_tree() == tree
    assert _mtimes(tree) == before


def test_changed_patch_rewrites_only_its_file(fake_kernel):
    tree = kernel.source_tree()
    _age(tree)
    (fake_kernel / "0002-b.patch").write_text(_patch("drivers/b.c", "b.c old", "b.c newer"))
    kernel.source_tree()
    assert (tree / "drivers/b.c").read_text() == "b.c newer\n"
    assert (tree / "drivers/a.c").read_text() == "a.c new\n"
    changed = {k for k, v in _mtimes(tree).items() if v != OLD_TIME * 10**9}
    assert changed == {"drivers/b.c"}


def test_removed_patch_restores_only_its_file(fake_kernel):
    tree = kernel.source_tree()
    _age(tree)
    (fake_kernel / "0001-a.patch").unlink()
    kernel.source_tree()
    assert (tree / "drivers/a.c").read_text() == "a.c old\n"
    changed = {k for k, v in _mtimes(tree).items() if v != OLD_TIME * 10**9}
    assert changed == {"drivers/a.c"}


def test_bad_patch_names_it_and_keeps_the_previous_tree(fake_kernel):
    tree = kernel.source_tree()
    _age(tree)
    before = _mtimes(tree)
    (fake_kernel / "0003-bad.patch").write_text(_patch("drivers/c.c", "not there", "x"))
    with pytest.raises(kernel.PatchError, match="0003-bad.patch"):
        kernel.source_tree()
    assert _mtimes(tree) == before
    assert (tree / "drivers/c.c").read_text() == "c.c old\n"
    # fixed: the next run applies it
    (fake_kernel / "0003-bad.patch").write_text(_patch("drivers/c.c", "c.c old", "c.c new"))
    kernel.source_tree()
    assert (tree / "drivers/c.c").read_text() == "c.c new\n"


def test_hand_edited_tree_is_reset_to_the_recorded_series(fake_kernel):
    tree = kernel.source_tree()
    _age(tree)
    (tree / "drivers/c.c").write_text("edited\n")
    (tree / "drivers/a.c").unlink()
    kernel.source_tree()
    assert (tree / "drivers/c.c").read_text() == "c.c old\n"
    assert (tree / "drivers/a.c").read_text() == "a.c new\n"
    changed = {k for k, v in _mtimes(tree).items() if v != OLD_TIME * 10**9}
    assert changed == {"drivers/a.c", "drivers/c.c"}


def test_aborted_import_is_redone(fake_kernel):
    tree = kernel.source_tree()
    shutil.rmtree(tree.parent / f"linux-{kernel.KERNEL_VERSION}.git")
    kernel.source_tree()
    assert (tree / "drivers/a.c").read_text() == "a.c new\n"
